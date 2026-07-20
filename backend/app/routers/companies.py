"""Company CRUD + contact discovery endpoint."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models, schemas
from ..db import get_db
from ..services.discovery import chain
from ..services.queueing import normalize_domain

router = APIRouter(prefix="/api/companies", tags=["companies"])


@router.post("", response_model=schemas.CompanyOut)
def create_company(payload: schemas.CompanyCreate, db: Session = Depends(get_db)):
    """Idempotent: an existing company with the same domain (or name) is returned
    as-is rather than duplicated.

    Creating a second row for a company you've already contacted is how the same
    person ends up emailed twice, so this must not create blindly.
    """
    data = payload.model_dump()
    data["domain"] = normalize_domain(data.get("domain"))

    existing = None
    if data["domain"]:
        existing = db.scalar(
            select(models.Company).where(models.Company.domain == data["domain"])
        )
    if existing is None:
        existing = db.scalar(
            select(models.Company).where(models.Company.name == data["name"])
        )
    if existing is not None:
        # Fill in blanks from the payload, but never clobber existing values.
        for field in ("domain", "careers_url", "notes", "target_role"):
            if not getattr(existing, field, None) and data.get(field):
                setattr(existing, field, data[field])
        db.commit()
        db.refresh(existing)
        return existing

    company = models.Company(**data)
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


@router.post("/manual-contact", response_model=schemas.DraftOut)
def manual_contact(payload: schemas.ManualContact, db: Session = Depends(get_db)):
    """Add a hand-picked contact and immediately draft outreach to them.

    For contacts you sourced yourself — no discovery API involved, so this works
    regardless of quota, and you get to choose a better target than an automated
    search would. The draft still lands in the approval queue like any other.
    """
    from ..services import drafting, queueing

    email = payload.email.strip().lower()
    if "@" not in email:
        raise HTTPException(status_code=400, detail="That doesn't look like an email")

    domain = queueing.normalize_domain(payload.domain) or email.split("@", 1)[1]

    company = db.scalar(select(models.Company).where(models.Company.domain == domain))
    if company is None:
        company = db.scalar(
            select(models.Company).where(models.Company.name == payload.company_name)
        )
    if company is None:
        company = models.Company(
            name=payload.company_name,
            domain=domain,
            target_role=payload.target_role,
            queue_status="done",  # handled manually, keep it out of the auto queue
        )
        db.add(company)
        db.commit()
        db.refresh(company)

    # Reuse the contact if this address is already on file for the company.
    contact = db.scalar(
        select(models.Contact).where(
            models.Contact.company_id == company.id, models.Contact.email == email
        )
    )
    if contact is None:
        contact = models.Contact(
            company_id=company.id,
            name=payload.contact_name,
            email=email,
            title=payload.title,
            source="manual",
            verified=True,  # a human picked it, which beats any automated guess
        )
        db.add(contact)
        db.commit()
        db.refresh(contact)

    role = payload.target_role or company.target_role or "6-month internship"
    variant = payload.resume_variant or queueing.infer_variant(role)
    app = drafting.ensure_application(db, company.id, role, contact.id, variant)

    try:
        draft = drafting.generate_draft_for_application(db, app)
    except FileNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return draft


@router.get("", response_model=list[schemas.CompanyOut])
def list_companies(db: Session = Depends(get_db)):
    return db.scalars(select(models.Company).order_by(models.Company.id)).all()


@router.get("/{company_id}/contacts", response_model=list[schemas.ContactOut])
def list_contacts(company_id: int, db: Session = Depends(get_db)):
    return db.scalars(
        select(models.Contact).where(models.Contact.company_id == company_id)
    ).all()


@router.post("/{company_id}/discover", response_model=schemas.DiscoverResponse)
def discover(
    company_id: int,
    payload: schemas.DiscoverRequest | None = None,
    db: Session = Depends(get_db),
):
    company = db.get(models.Company, company_id)
    if company is None:
        raise HTTPException(status_code=404, detail="Company not found")
    if not company.domain:
        raise HTTPException(
            status_code=400, detail="Company has no domain to search against"
        )

    payload = payload or schemas.DiscoverRequest()
    result = chain.discover_contact(
        company.domain,
        person_first=payload.person_first,
        person_last=payload.person_last,
    )
    if result is None:
        return schemas.DiscoverResponse(company_id=company_id, found=False)

    # Persist the discovered contact (dedupe by email within the company).
    existing = db.scalar(
        select(models.Contact).where(
            models.Contact.company_id == company_id,
            models.Contact.email == result.email,
        )
    )
    if existing:
        contact = existing
    else:
        contact = models.Contact(
            company_id=company_id,
            name=result.name,
            email=result.email,
            title=result.title,
            source=result.source,
            verified=result.verified,
        )
        db.add(contact)
        db.commit()
        db.refresh(contact)

    return schemas.DiscoverResponse(
        company_id=company_id,
        found=True,
        contact=schemas.ContactOut.model_validate(contact),
        source=result.source,
        detail=result.detail,
    )
