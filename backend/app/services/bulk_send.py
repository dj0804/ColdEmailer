"""Send a batch of approved drafts in the background, spaced out like a human.

The user approves the whole set with one click ("Approve all"); this module then
works through that fixed snapshot of draft ids, approving and sending one at a
time with a randomised 1-3 minute gap. Firing 50 emails in the same second is the
pattern Gmail's abuse heuristics look for, so the gap is the point.

Only drafts that were pending at click time are included — anything drafted while
a run is in progress waits for the next explicit approval.
"""

from __future__ import annotations

import random
import threading
from datetime import datetime, timezone

from sqlalchemy import select

from ..db import SessionLocal
from ..models import EmailDraft
from . import job_log, rate_limit, send

MIN_GAP_S = 60
MAX_GAP_S = 180

_lock = threading.Lock()
_stop = threading.Event()
_state: dict = {"running": False}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def status() -> dict:
    with _lock:
        return dict(_state)


def stop() -> dict:
    _stop.set()
    return status()


def start() -> dict:
    """Snapshot every pending draft and start sending them. Returns the new state."""
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
        _stop.clear()
        _state.clear()
        _state.update(
            running=bool(ids), total=len(ids), sent=0, failed=0, skipped=0,
            started_at=_now(), next_send_at=None, last_error=None,
        )
        if ids:
            threading.Thread(target=_run, args=(ids,), daemon=True).start()
        return dict(_state)


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


def _run(ids: list[int]) -> None:
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
    with _lock:
        _state["running"] = False
        _state["next_send_at"] = None
        _state["finished_at"] = _now()
        summary = {k: v for k, v in _state.items() if isinstance(v, (int, str))}
    job_log.record("bulk_send", result=summary)
