"""Application CRUD + single outreach-draft generation."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models, schemas
from ..db import get_db
from ..services import drafting

router = APIRouter(prefix="/api/applications", tags=["applications"])


@router.post("", response_model=schemas.ApplicationOut)
def create_application(payload: schemas.ApplicationCreate, db: Session = Depends(get_db)):
    if db.get(models.Company, payload.company_id) is None:
        raise HTTPException(status_code=404, detail="Company not found")
    app = drafting.ensure_application(
        db,
        payload.company_id,
        payload.role,
        payload.contact_id,
        payload.resume_variant,
    )
    return app


@router.get("", response_model=list[schemas.ApplicationOut])
def list_applications(db: Session = Depends(get_db)):
    return db.scalars(select(models.Application).order_by(models.Application.id)).all()


@router.post("/{app_id}/generate-draft", response_model=schemas.DraftOut)
def generate_draft(app_id: int, db: Session = Depends(get_db)):
    app = db.get(models.Application, app_id)
    if app is None:
        raise HTTPException(status_code=404, detail="Application not found")
    if app.contact is None:
        raise HTTPException(
            status_code=400,
            detail="Application has no contact. Run discovery or set a contact first.",
        )
    try:
        draft = drafting.generate_draft_for_application(db, app)
    except FileNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return draft
