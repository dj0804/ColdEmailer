"""Company CRUD + contact discovery endpoint."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models, schemas
from ..db import get_db
from ..services.discovery import chain

router = APIRouter(prefix="/api/companies", tags=["companies"])


@router.post("", response_model=schemas.CompanyOut)
def create_company(payload: schemas.CompanyCreate, db: Session = Depends(get_db)):
    company = models.Company(**payload.model_dump())
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


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
