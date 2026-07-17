"""Background jobs: reply polling (Phase 4). Ghosting/nudges added in Phase 5."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from .db import SessionLocal
from .models import Application, EmailDraft, ReplyEvent
from .services import classify, gmail

# Stages we stop polling (definitive outcomes).
TERMINAL_STAGES = {"rejection", "ghosted_dead"}
# Rank used so a later, lesser reply can't downgrade a better stage.
STAGE_RANK = {"sent": 1, "recruiter_reply": 2, "interview_request": 3}


def _ms_to_dt(ms: str | int | None) -> datetime | None:
    if not ms:
        return None
    return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc)


def _apply_classification(app: Application, label: str, when: datetime | None) -> None:
    if when:
        app.last_contact_at = when
    if label == "other":
        return
    if label == "rejection":
        app.stage = "rejection"  # definitive
        return
    # recruiter_reply / interview_request — never downgrade
    if STAGE_RANK.get(label, 0) > STAGE_RANK.get(app.stage, 0):
        app.stage = label


def poll_replies() -> dict:
    """Check every tracked thread for new inbound messages and classify them.

    Returns a small summary dict (useful for the manual-trigger endpoint / logs).
    """
    db = SessionLocal()
    summary = {"threads_checked": 0, "new_replies": 0, "classifications": {}}
    try:
        me = (gmail.get_profile().get("emailAddress") or "").lower()
        apps = db.scalars(
            select(Application).where(
                Application.gmail_thread_id.is_not(None),
                Application.stage.not_in(TERMINAL_STAGES),
            )
        ).all()

        for app in apps:
            summary["threads_checked"] += 1

            # Messages we already know about: our own outbound + already-classified.
            our_ids = set(
                db.scalars(
                    select(EmailDraft.gmail_message_id).where(
                        EmailDraft.application_id == app.id,
                        EmailDraft.gmail_message_id.is_not(None),
                    )
                ).all()
            )
            seen_ids = set(
                db.scalars(
                    select(ReplyEvent.gmail_message_id).where(
                        ReplyEvent.application_id == app.id
                    )
                ).all()
            )

            try:
                messages = gmail.list_thread_messages(app.gmail_thread_id)
            except Exception:  # noqa: BLE001 - a bad thread shouldn't kill the poll
                continue

            for msg in messages:  # Gmail returns oldest-first
                mid = msg.get("id")
                if mid in our_ids or mid in seen_ids:
                    continue
                sender = gmail.message_from(msg)
                if me and me in sender.lower():
                    continue  # our own message not tracked as a draft (edge case)

                body = gmail.message_text(msg)
                result = classify.classify_reply(sender, body)
                label = result["label"]

                db.add(
                    ReplyEvent(
                        application_id=app.id,
                        gmail_message_id=mid,
                        classification=label,
                        snippet=(body[:300] or msg.get("snippet", "")),
                    )
                )
                _apply_classification(app, label, _ms_to_dt(msg.get("internalDate")))

                summary["new_replies"] += 1
                summary["classifications"][label] = (
                    summary["classifications"].get(label, 0) + 1
                )

            db.commit()
        return summary
    finally:
        db.close()
