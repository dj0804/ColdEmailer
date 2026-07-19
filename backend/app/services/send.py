"""The ONE and only path that sends outreach/nudge email.

INVARIANT: an email is never sent unless its EmailDraft row is explicitly
approved (status == 'approved' with approved_at set). This function is the sole
place that calls Gmail's send; every route funnels through it. It also enforces
the daily send cap.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Application, Contact, EmailDraft, NudgeHistory
from . import gmail, rate_limit


class NotApproved(Exception):
    pass


class DuplicateContact(Exception):
    """Raised when a cold email would go to someone already contacted."""


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

    # --- Duplicate-contact guard ---------------------------------------------
    # A fresh outreach must never go to someone we've already cold-emailed, even
    # via a different Application row (duplicate company entries are easy to
    # create). Nudges are exempt: they're replies on an existing thread.
    if draft.type == "outreach" and app.contact_id:
        contact = db.get(Contact, app.contact_id)
        if contact and contact.email:
            already = db.scalar(
                select(EmailDraft.id)
                .join(Application, EmailDraft.application_id == Application.id)
                .join(Contact, Application.contact_id == Contact.id)
                .where(
                    func.lower(Contact.email) == contact.email.lower(),
                    EmailDraft.type == "outreach",
                    EmailDraft.status == "sent",
                    EmailDraft.id != draft.id,
                )
            )
            if already:
                raise DuplicateContact(
                    f"{contact.email} already received outreach (draft {already}). "
                    "Refusing to send a duplicate cold email."
                )
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
    else:  # nudge1 / nudge2 — stamp the history row so we don't re-nudge
        history = db.scalar(
            select(NudgeHistory).where(NudgeHistory.draft_id == draft.id)
        )
        if history:
            history.sent_at = now

    db.commit()
    return {
        "draft_id": draft_id,
        "application_id": app.id,
        "to": contact.email,
        "gmail_message_id": msg_id,
        "thread_id": thread_id,
        "sent_at": now.isoformat(),
    }
