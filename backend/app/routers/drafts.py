"""Draft review, edit, and the approval->send endpoints.

Approval is the gate: the approve routes set status='approved' + approved_at,
then hand off to send.send_approved_draft — the only path that sends mail.
"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models, schemas
from ..db import get_db
from ..services import drafting, rate_limit, send

router = APIRouter(prefix="/api/drafts", tags=["drafts"])


def _now():
    return datetime.now(timezone.utc)


@router.get("", response_model=list[schemas.DraftOut])
def list_drafts(
    status: str | None = Query(default=None),
    batch_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    q = select(models.EmailDraft).order_by(models.EmailDraft.id.desc())
    if status:
        q = q.where(models.EmailDraft.status == status)
    if batch_id:
        q = q.where(models.EmailDraft.batch_id == batch_id)
    return db.scalars(q).all()


@router.get("/{draft_id}", response_model=schemas.DraftOut)
def get_draft(draft_id: int, db: Session = Depends(get_db)):
    draft = db.get(models.EmailDraft, draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="Draft not found")
    return draft


@router.patch("/{draft_id}", response_model=schemas.DraftOut)
def edit_draft(draft_id: int, payload: schemas.DraftEdit, db: Session = Depends(get_db)):
    draft = db.get(models.EmailDraft, draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="Draft not found")
    if draft.status not in ("pending", "approved"):
        raise HTTPException(
            status_code=400, detail=f"Cannot edit a {draft.status} draft"
        )
    if payload.subject is not None:
        draft.subject = payload.subject
    if payload.body is not None:
        draft.body = payload.body
    # Any edit re-opens approval so an edited email can't ride a stale approval.
    draft.status = "pending"
    draft.approved_at = None
    db.commit()
    db.refresh(draft)
    return draft


def _approve_and_send(db: Session, draft: models.EmailDraft) -> schemas.SendResult:
    draft.status = "approved"
    draft.approved_at = _now()
    db.commit()
    try:
        result = send.send_approved_draft(db, draft.id)
    except rate_limit.RateLimitExceeded as e:
        raise HTTPException(status_code=429, detail=str(e))
    except send.NotApproved as e:
        raise HTTPException(status_code=409, detail=str(e))
    return schemas.SendResult(**result)


@router.post("/{draft_id}/approve", response_model=schemas.SendResult)
def approve_draft(draft_id: int, db: Session = Depends(get_db)):
    draft = db.get(models.EmailDraft, draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="Draft not found")
    if draft.status == "sent":
        raise HTTPException(status_code=409, detail="Draft already sent")
    return _approve_and_send(db, draft)


@router.post("/{draft_id}/reject", response_model=schemas.DraftOut)
def reject_draft(draft_id: int, db: Session = Depends(get_db)):
    """Discard a draft without sending. Never touches Gmail."""
    draft = db.get(models.EmailDraft, draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="Draft not found")
    if draft.status == "sent":
        raise HTTPException(status_code=409, detail="Draft already sent")
    draft.status = "rejected"
    draft.approved_at = None
    db.commit()
    db.refresh(draft)
    return draft


@router.post("/batch/generate", response_model=list[schemas.DraftOut])
def batch_generate(payload: schemas.BatchGenerate, db: Session = Depends(get_db)):
    if not payload.company_ids:
        raise HTTPException(status_code=400, detail="company_ids is empty")
    batch_id = uuid.uuid4().hex[:12]
    drafts: list[models.EmailDraft] = []
    errors: list[str] = []
    for cid in payload.company_ids:
        company = db.get(models.Company, cid)
        if company is None:
            errors.append(f"company {cid}: not found")
            continue
        app = drafting.ensure_application(
            db, cid, payload.role, resume_variant=payload.resume_variant
        )
        if app.contact is None:
            errors.append(f"{company.name}: no contact (run discovery first)")
            continue
        try:
            drafts.append(
                drafting.generate_draft_for_application(db, app, batch_id=batch_id)
            )
        except Exception as e:  # noqa: BLE001 - report per-company, keep going
            errors.append(f"{company.name}: {e}")
    if not drafts:
        raise HTTPException(
            status_code=400, detail="No drafts generated. " + "; ".join(errors)
        )
    return drafts


@router.post("/batch/{batch_id}/approve", response_model=list[schemas.SendResult])
def batch_approve(batch_id: str, db: Session = Depends(get_db)):
    drafts = db.scalars(
        select(models.EmailDraft).where(
            models.EmailDraft.batch_id == batch_id,
            models.EmailDraft.status.in_(["pending", "approved"]),
        )
    ).all()
    if not drafts:
        raise HTTPException(
            status_code=404, detail="No pending drafts for this batch"
        )
    results: list[schemas.SendResult] = []
    for draft in drafts:
        results.append(_approve_and_send(db, draft))
    return results
