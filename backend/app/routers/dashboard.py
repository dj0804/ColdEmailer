"""One aggregated endpoint powering the dashboard table."""

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import models
from ..config import settings
from ..db import get_db
from ..services import nudge, rate_limit
from ..services.discovery import quota

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("")
def dashboard(db: Session = Depends(get_db)):
    apps = db.scalars(
        select(models.Application).order_by(models.Application.id.desc())
    ).all()

    rows = []
    for a in apps:
        company = db.get(models.Company, a.company_id)
        contact = a.contact
        pending = db.scalars(
            select(models.EmailDraft).where(
                models.EmailDraft.application_id == a.id,
                models.EmailDraft.status == "pending",
            )
        ).all()
        last_reply = db.scalar(
            select(models.ReplyEvent)
            .where(models.ReplyEvent.application_id == a.id)
            .order_by(models.ReplyEvent.id.desc())
        )
        rows.append(
            {
                "application_id": a.id,
                "company": company.name if company else "(unknown)",
                "company_id": a.company_id,
                "contact_name": contact.name if contact else None,
                "contact_email": contact.email if contact else None,
                "contact_source": contact.source if contact else None,
                "role": a.role,
                "stage": a.stage,
                "sent_at": a.sent_at,
                "last_contact_at": a.last_contact_at,
                "business_days_silent": (
                    nudge.business_days_silent(a) if a.stage == "sent" else None
                ),
                "last_reply_class": last_reply.classification if last_reply else None,
                "pending_drafts": [
                    {"id": d.id, "type": d.type, "subject": d.subject} for d in pending
                ],
            }
        )

    # Companies with a contact but no application yet — actionable from the UI.
    ready = []
    for c in db.scalars(select(models.Company)).all():
        has_app = db.scalar(
            select(models.Application.id).where(models.Application.company_id == c.id)
        )
        contact = db.scalar(
            select(models.Contact)
            .where(models.Contact.company_id == c.id)
            .order_by(models.Contact.id.desc())
        )
        if not has_app:
            ready.append(
                {
                    "company_id": c.id,
                    "company": c.name,
                    "domain": c.domain,
                    "contact_email": contact.email if contact else None,
                }
            )

    return {
        "rows": rows,
        "companies_without_application": ready,
        "sends_today": rate_limit.sends_today(db),
        "daily_cap": settings.daily_send_cap,
        "pending_count": sum(len(r["pending_drafts"]) for r in rows),
        "queue_remaining": db.scalar(
            select(func.count(models.Company.id)).where(
                models.Company.queue_status == "queued"
            )
        )
        or 0,
        "api_quota": quota.status(),
    }
