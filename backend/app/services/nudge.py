"""Ghosting detection: business-day math + nudge escalation.

Escalation ladder for an application still sitting at stage 'sent' (any reply moves
it off 'sent', so 'sent' == silence):

    day 10  -> stage a nudge1 draft   (pending approval — never auto-sent)
    day 20  -> stage a nudge2 draft   (pending approval — never auto-sent)
    day 30  -> mark stage 'ghosted_dead', stop nudging

Thresholds are configurable. Drafts are only *staged*; the approval gate in
send.send_approved_draft remains the only way anything leaves the outbox.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Application, Company, EmailDraft, NudgeHistory
from . import personalize


def business_days_between(start: datetime, end: datetime) -> int:
    """Weekdays elapsed strictly after `start`'s date, through `end`'s date.

    Weekends only — public holidays are not modelled (personal tool, and holidays
    vary by the recipient's country anyway).
    """
    if end <= start:
        return 0
    d: date = start.date()
    e: date = end.date()
    days = 0
    cur = d + timedelta(days=1)
    while cur <= e:
        if cur.weekday() < 5:  # Mon-Fri
            days += 1
        cur += timedelta(days=1)
    return days


def business_days_silent(app: Application, now: datetime | None = None) -> int:
    if not app.sent_at:
        return 0
    now = now or datetime.now(timezone.utc)
    sent = app.sent_at
    if sent.tzinfo is None:  # SQLite round-trips naive datetimes
        sent = sent.replace(tzinfo=timezone.utc)
    return business_days_between(sent, now)


def _existing_nudge(db: Session, app_id: int, number: int) -> NudgeHistory | None:
    return db.scalar(
        select(NudgeHistory).where(
            NudgeHistory.application_id == app_id,
            NudgeHistory.nudge_number == number,
        )
    )


def _original_outreach(db: Session, app_id: int) -> EmailDraft | None:
    return db.scalar(
        select(EmailDraft)
        .where(EmailDraft.application_id == app_id, EmailDraft.type == "outreach")
        .order_by(EmailDraft.id)
    )


def _create_nudge_draft(
    db: Session, app: Application, number: int, business_days: int
) -> EmailDraft:
    company: Company = db.get(Company, app.company_id)
    original = _original_outreach(db, app.id)
    if original is None:
        raise ValueError(f"Application {app.id} has no original outreach to follow up")

    result = personalize.generate_nudge(
        nudge_number=number,
        company_name=company.name,
        recipient_name=app.contact.name if app.contact else None,
        recipient_title=app.contact.title if app.contact else None,
        original_subject=original.subject,
        original_body=original.body,
        business_days=business_days,
    )

    draft = EmailDraft(
        application_id=app.id,
        type=f"nudge{number}",
        subject=result["subject"],
        body=result["body"],
        attachment_paths=json.dumps([]),  # reply on-thread; resume already sent
        status="pending",
    )
    db.add(draft)
    db.flush()  # need draft.id for the history row
    db.add(
        NudgeHistory(application_id=app.id, nudge_number=number, draft_id=draft.id)
    )
    return draft


def process_application(
    db: Session, app: Application, now: datetime | None = None
) -> str | None:
    """Advance one application along the ghosting ladder. Returns an action label."""
    if app.stage != "sent" or not app.sent_at:
        return None

    bdays = business_days_silent(app, now)

    if bdays >= settings.nudge_dead_business_days:
        app.stage = "ghosted_dead"
        return "marked_ghosted_dead"

    if bdays >= settings.nudge2_business_days:
        if _existing_nudge(db, app.id, 2) is None:
            _create_nudge_draft(db, app, 2, bdays)
            return "nudge2_drafted"
        return None

    if bdays >= settings.nudge1_business_days:
        if _existing_nudge(db, app.id, 1) is None:
            _create_nudge_draft(db, app, 1, bdays)
            return "nudge1_drafted"
        return None

    return None
