"""Send a batch of approved drafts in the background, spaced out like a human.

The user approves the whole set with one click ("Approve all"); this module then
works through that fixed snapshot of draft ids, approving and sending one at a
time with a randomised 1-3 minute gap. Firing 50 emails in the same second is the
pattern Gmail's abuse heuristics look for, so the gap is the point.

Only drafts that were pending at click time are included — anything drafted while
a run is in progress waits for the next explicit approval.

A run can be scheduled for later (e.g. Monday morning, so cold email doesn't land
over a weekend). The schedule is persisted to disk and re-armed on startup, so a
restart or redeploy in between doesn't silently drop it.
"""

from __future__ import annotations

import json
import random
import threading
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from ..db import SessionLocal
from ..models import EmailDraft
from . import job_log, rate_limit, send

MIN_GAP_S = 60
MAX_GAP_S = 180
RATE_LIMIT_BACKOFF_S = 75  # Gmail's per-user quota is per minute

SCHEDULE_FILE = Path(__file__).resolve().parents[2] / "bulk_send_schedule.json"

_lock = threading.Lock()
_stop = threading.Event()
_state: dict = {"running": False}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def status() -> dict:
    with _lock:
        return dict(_state)


def stop() -> dict:
    """Stop a run in progress, or cancel a scheduled one. Unsent drafts stay pending."""
    _stop.set()
    _clear_schedule()
    return status()


def _save_schedule(at: datetime, ids: list[int]) -> None:
    SCHEDULE_FILE.write_text(json.dumps({"at": at.isoformat(), "draft_ids": ids}))


def _clear_schedule() -> None:
    try:
        SCHEDULE_FILE.unlink()
    except FileNotFoundError:
        pass


def _launch(ids: list[int], at: datetime | None) -> None:
    """Reset state and start the worker thread. Caller holds _lock."""
    _stop.clear()
    _state.clear()
    _state.update(
        running=bool(ids), total=len(ids), sent=0, failed=0, skipped=0,
        started_at=None if at else _now(),
        scheduled_for=at.isoformat(timespec="seconds") if at else None,
        next_send_at=None, last_error=None,
    )
    if ids:
        threading.Thread(target=_run, args=(ids, at), daemon=True).start()


def start(at: datetime | None = None) -> dict:
    """Snapshot every pending draft and send them now, or at ``at`` (UTC-aware).

    Returns the new state.
    """
    if at is not None:
        if at.tzinfo is None:
            raise ValueError("Scheduled time must include a timezone")
        if at <= datetime.now(timezone.utc):
            at = None  # a time in the past just means "now"
    with _lock:
        if _state.get("running"):
            return dict(_state)
        db = SessionLocal()
        try:
            ids = list(
                db.scalars(
                    select(EmailDraft.id)
                    .where(EmailDraft.status == "pending")
                    .order_by(EmailDraft.id)
                ).all()
            )
        finally:
            db.close()
        if ids and at:
            _save_schedule(at, ids)
        _launch(ids, at)
        return dict(_state)


def resume_schedule() -> None:
    """Re-arm a persisted schedule after a restart (called at app startup).

    If the time has already passed — e.g. the box was down on Monday morning, or
    it restarted mid-run — the remaining drafts go out now; ones already sent are
    skipped because they're no longer pending.
    """
    try:
        data = json.loads(SCHEDULE_FILE.read_text())
        at = datetime.fromisoformat(data["at"])
        ids = [int(i) for i in data["draft_ids"]]
    except (OSError, ValueError, KeyError, TypeError):
        return
    if at <= datetime.now(timezone.utc):
        at = None
    with _lock:
        if not _state.get("running"):
            _launch(ids, at)


def _send_one(draft_id: int) -> str:
    """Approve + send a single draft. Returns 'sent' | 'skipped' | 'cap'."""
    db = SessionLocal()
    try:
        draft = db.get(EmailDraft, draft_id)
        if draft is None or draft.status != "pending":
            return "skipped"  # edited, rejected or sent elsewhere since the click
        draft.status = "approved"
        draft.approved_at = datetime.now(timezone.utc)
        db.commit()
        try:
            try:
                send.send_approved_draft(db, draft_id)
            except Exception as e:  # noqa: BLE001
                # Gmail's per-minute API quota is shared with the reply poller,
                # which can briefly exhaust it. Nothing was sent, so wait out the
                # minute and retry once before counting this draft as failed.
                if "rateLimitExceeded" not in str(e) and "Quota exceeded" not in str(e):
                    raise
                db.rollback()
                if _stop.wait(RATE_LIMIT_BACKOFF_S):
                    raise
                send.send_approved_draft(db, draft_id)
        except rate_limit.RateLimitExceeded:
            # Put it back so it isn't left approved-but-unsent.
            draft.status = "pending"
            draft.approved_at = None
            db.commit()
            return "cap"
        except send.DuplicateContact:
            draft.status = "rejected"
            draft.approved_at = None
            if draft.application and draft.application.stage in ("draft", "pending_approval"):
                draft.application.stage = "duplicate_suppressed"
            db.commit()
            return "skipped"
        except Exception:
            # Leave it pending for a manual retry rather than stuck in 'approved'.
            db.rollback()
            draft = db.get(EmailDraft, draft_id)
            if draft and draft.status == "approved":
                draft.status = "pending"
                draft.approved_at = None
                db.commit()
            raise
        return "sent"
    finally:
        db.close()


def _run(ids: list[int], at: datetime | None = None) -> None:
    if at is not None:
        wait_s = (at - datetime.now(timezone.utc)).total_seconds()
        if wait_s > 0 and _stop.wait(wait_s):
            with _lock:
                _state["running"] = False
                _state["last_error"] = "Scheduled send cancelled; drafts left pending."
            return
        with _lock:
            _state["scheduled_for"] = None
            _state["started_at"] = _now()
    for i, draft_id in enumerate(ids):
        if _stop.is_set():
            break
        try:
            outcome = _send_one(draft_id)
        except Exception as e:  # noqa: BLE001 - one bad draft shouldn't end the run
            with _lock:
                _state["failed"] += 1
                _state["last_error"] = f"draft {draft_id}: {type(e).__name__}: {e}"[:300]
            outcome = "failed"
        if outcome == "cap":
            with _lock:
                _state["last_error"] = "Daily send cap reached; remaining drafts left pending."
            break
        if outcome in ("sent", "skipped"):
            with _lock:
                _state[outcome] += 1
        if i < len(ids) - 1 and outcome != "skipped":
            gap = random.uniform(MIN_GAP_S, MAX_GAP_S)
            with _lock:
                _state["next_send_at"] = datetime.fromtimestamp(
                    datetime.now(timezone.utc).timestamp() + gap, tz=timezone.utc
                ).isoformat(timespec="seconds")
            if _stop.wait(gap):
                break
    _clear_schedule()
    with _lock:
        _state["running"] = False
        _state["next_send_at"] = None
        _state["finished_at"] = _now()
        summary = {k: v for k, v in _state.items() if isinstance(v, (int, str))}
    job_log.record("bulk_send", result=summary)
