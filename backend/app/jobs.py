"""Background jobs: reply polling (Phase 4). Ghosting/nudges added in Phase 5."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from .config import settings
from .db import SessionLocal
from .models import Application, Contact, EmailDraft, ReplyEvent
from .services import classify, drafting, gmail, nudge, queueing
from .services.discovery import chain as discovery_chain

# Stages we stop polling (definitive outcomes).
TERMINAL_STAGES = {"rejection", "ghosted_dead", "duplicate_suppressed"}
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


def daily_outreach(limit: int | None = None) -> dict:
    """Work through the company queue: discover a contact, then stage a draft.

    Runs on weekdays only (weekend cold email gets buried). This job NEVER sends
    — every draft lands in 'pending' and still needs explicit approval.
    """
    db = SessionLocal()
    limit = limit or settings.outreach_per_day
    summary: dict = {
        "attempted": 0, "drafted": 0, "no_contact": 0, "errors": [], "companies": []
    }
    try:
        for company in queueing.next_batch(db, limit):
            summary["attempted"] += 1

            contact = db.scalar(
                select(Contact)
                .where(Contact.company_id == company.id)
                .order_by(Contact.id.desc())
            )

            # 1. Discover a contact if we don't already have one.
            if contact is None:
                try:
                    found = discovery_chain.discover_contact(company.domain or "")
                except Exception as e:  # noqa: BLE001 - keep the batch going
                    summary["errors"].append(f"{company.name}: discovery {e}"[:160])
                    continue
                if found is None:
                    company.queue_status = "skipped"
                    company.notes = ((company.notes or "") + " | no contact found").strip()
                    db.commit()
                    summary["no_contact"] += 1
                    summary["companies"].append(
                        {"company": company.name, "result": "no_contact"}
                    )
                    continue
                contact = Contact(
                    company_id=company.id,
                    name=found.name,
                    email=found.email,
                    title=found.title,
                    source=found.source,
                    verified=found.verified,
                )
                db.add(contact)
                db.commit()
                db.refresh(contact)

            # 2. Stage a personalized draft with the role-matched resume.
            try:
                role = company.target_role or "6-month internship (intern-to-FTE)"
                app = drafting.ensure_application(
                    db,
                    company.id,
                    role if role.lower().startswith("6-month") else f"6-month {role} (intern-to-FTE)",
                    contact_id=contact.id,
                    resume_variant=company.resume_variant,
                )
                draft = drafting.generate_draft_for_application(db, app)
            except Exception as e:  # noqa: BLE001
                db.rollback()
                summary["errors"].append(f"{company.name}: draft {e}"[:160])
                continue

            company.queue_status = "done"
            db.commit()
            summary["drafted"] += 1
            summary["companies"].append(
                {
                    "company": company.name,
                    "result": "drafted",
                    "draft_id": draft.id,
                    "to": contact.email,
                    "resume_variant": app.resume_variant,
                }
            )
        return summary
    finally:
        db.close()


def check_ghosting() -> dict:
    """Daily sweep: stage nudge drafts for silent applications, mark dead ones.

    Only ever *stages* drafts for approval — this job never sends anything.
    """
    db = SessionLocal()
    summary: dict = {"checked": 0, "actions": {}}
    try:
        apps = db.scalars(
            select(Application).where(
                Application.stage == "sent",
                Application.sent_at.is_not(None),
            )
        ).all()
        for app in apps:
            summary["checked"] += 1
            try:
                action = nudge.process_application(db, app)
            except Exception as e:  # noqa: BLE001 - one bad app shouldn't kill the sweep
                db.rollback()
                summary["actions"][f"error:{app.id}"] = str(e)[:120]
                continue
            if action:
                summary["actions"][action] = summary["actions"].get(action, 0) + 1
            db.commit()
        return summary
    finally:
        db.close()
