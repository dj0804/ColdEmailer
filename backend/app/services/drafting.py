"""Helpers to create Application rows and generate outreach EmailDrafts.

Shared by the applications and drafts routers (single- and batch-generation).
"""

from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Application, Company, Contact, EmailDraft
from . import personalize
from .resume import resume_abspath


def default_attachments(resume_variant: str | None = None) -> list[str]:
    """Resume-only outreach, using the role-specific variant for this application."""
    return [str(resume_abspath(resume_variant))]


def latest_contact(db: Session, company_id: int) -> Contact | None:
    return db.scalar(
        select(Contact)
        .where(Contact.company_id == company_id)
        .order_by(Contact.id.desc())
    )


def ensure_application(
    db: Session,
    company_id: int,
    role: str,
    contact_id: int | None = None,
    resume_variant: str | None = None,
) -> Application:
    """Reuse a company's open application if one exists, else create one."""
    if contact_id is None:
        c = latest_contact(db, company_id)
        contact_id = c.id if c else None

    existing = db.scalar(
        select(Application).where(
            Application.company_id == company_id,
            Application.stage.in_(["draft", "pending_approval"]),
        )
    )
    if existing:
        if contact_id and not existing.contact_id:
            existing.contact_id = contact_id
        if role:
            existing.role = role
        if resume_variant:
            existing.resume_variant = resume_variant
        db.commit()
        return existing

    app = Application(
        company_id=company_id,
        contact_id=contact_id,
        role=role,
        resume_variant=resume_variant,
        stage="draft",
    )
    db.add(app)
    db.commit()
    db.refresh(app)
    return app


def generate_draft_for_application(
    db: Session, app: Application, batch_id: str | None = None
) -> EmailDraft:
    company: Company = db.get(Company, app.company_id)
    contact: Contact | None = app.contact

    result = personalize.generate_outreach(
        company_name=company.name,
        company_domain=company.domain,
        company_notes=company.notes,
        recipient_name=contact.name if contact else None,
        recipient_title=contact.title if contact else None,
        role=app.role or "6-month internship (intern-to-FTE)",
        resume_variant=app.resume_variant,
    )

    draft = EmailDraft(
        application_id=app.id,
        type="outreach",
        subject=result["subject"],
        body=result["body"],
        attachment_paths=json.dumps(default_attachments(app.resume_variant)),
        batch_id=batch_id,
        status="pending",
    )
    db.add(draft)
    app.stage = "pending_approval"
    db.commit()
    db.refresh(draft)
    return draft
