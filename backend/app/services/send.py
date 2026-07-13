"""The ONE and only path that sends outreach/nudge email.

INVARIANT: an email is never sent unless its EmailDraft row is explicitly
approved (status == 'approved' with approved_at set). This function is the sole
place that calls Gmail's send; every route funnels through it. It also enforces
the daily send cap.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from ..models import Application, EmailDraft
from . import gmail, rate_limit


class NotApproved(Exception):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def send_approved_draft(db: Session, draft_id: int) -> dict:
    draft = db.get(EmailDraft, draft_id)
    if draft is None:
        raise ValueError(f"Draft {draft_id} not found")

    # --- The approval gate. Nothing below runs without this being satisfied. ---
    if draft.status != "approved" or draft.approved_at is None:
        raise NotApproved(
            f"Draft {draft_id} is not approved (status={draft.status!r}). "
            "Refusing to send."
        )
    if draft.status == "sent" or draft.gmail_message_id:
        raise NotApproved(f"Draft {draft_id} was already sent.")

    rate_limit.enforce(db)

    app: Application = db.get(Application, draft.application_id)
    if app is None:
        raise ValueError(f"Application {draft.application_id} not found")
    contact = app.contact
    if contact is None or not contact.email:
        raise ValueError(
            f"Application {app.id} has no contact email to send to."
        )

    attachments = json.loads(draft.attachment_paths) if draft.attachment_paths else []

    sent = gmail.send_message(
        to=contact.email,
        subject=draft.subject,
        body=draft.body,
        attachments=attachments,
        thread_id=app.gmail_thread_id,  # None for first outreach; set for nudges
    )

    msg_id = sent.get("id")
    thread_id = sent.get("threadId")

    # Best-effort label; never fail the send over a label error.
    try:
        gmail.apply_label(msg_id)
    except Exception:  # noqa: BLE001
        pass

    now = _now()
    draft.status = "sent"
    draft.sent_at = now
    draft.gmail_message_id = msg_id

    app.gmail_thread_id = thread_id
    app.last_contact_at = now
    if draft.type == "outreach":
        app.sent_at = now
        app.stage = "sent"

    db.commit()
    return {
        "draft_id": draft_id,
        "application_id": app.id,
        "to": contact.email,
        "gmail_message_id": msg_id,
        "thread_id": thread_id,
        "sent_at": now.isoformat(),
    }
