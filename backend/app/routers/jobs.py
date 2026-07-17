"""Manual job triggers + reply-event inspection (Phase 4)."""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import jobs, models, schemas
from ..db import get_db

router = APIRouter(prefix="/api", tags=["jobs"])


@router.post("/jobs/poll-replies")
def trigger_poll():
    """Run the reply poller once, now (same code the scheduler runs)."""
    return jobs.poll_replies()


@router.post("/jobs/check-ghosting")
def trigger_ghost_check():
    """Run the ghosting sweep once, now. Only stages drafts; never sends."""
    return jobs.check_ghosting()


@router.get("/reply-events", response_model=list[schemas.ReplyEventOut])
def list_reply_events(db: Session = Depends(get_db)):
    return db.scalars(
        select(models.ReplyEvent).order_by(models.ReplyEvent.id.desc())
    ).all()
