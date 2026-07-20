"""Manual job triggers + reply-event inspection (Phase 4)."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from datetime import datetime, timezone

from .. import jobs, models, schemas
from ..db import get_db
from ..services import job_log, queueing

router = APIRouter(prefix="/api", tags=["jobs"])


@router.get("/jobs/status")
def jobs_status():
    """Are the scheduled jobs alive, when do they next fire, what happened last?

    Answers "did the pipeline run today?" without SSH access to the logs.
    """
    from ..main import scheduler  # imported lazily to avoid a circular import

    now = datetime.now(timezone.utc)
    jobs = []
    for j in scheduler.get_jobs():
        nxt = getattr(j, "next_run_time", None)
        jobs.append(
            {
                "id": j.id,
                "trigger": str(j.trigger),
                "next_run": nxt.isoformat(timespec="seconds") if nxt else None,
                "in_seconds": int((nxt - now).total_seconds()) if nxt else None,
            }
        )
    return {
        "scheduler_running": scheduler.running,
        "now_utc": now.isoformat(timespec="seconds"),
        "jobs": jobs,
        "last_runs": job_log.status(),
    }


@router.post("/jobs/poll-replies")
def trigger_poll():
    """Run the reply poller once, now (same code the scheduler runs)."""
    return jobs.poll_replies()


@router.post("/jobs/check-ghosting")
def trigger_ghost_check():
    """Run the ghosting sweep once, now. Only stages drafts; never sends."""
    return jobs.check_ghosting()


@router.post("/jobs/daily-outreach")
def trigger_daily_outreach(limit: int | None = Query(default=None)):
    """Work today's batch from the company queue. Stages drafts; never sends."""
    return jobs.daily_outreach(limit=limit)


@router.post("/queue/bulk")
def bulk_add_targets(payload: schemas.BulkTargets, db: Session = Depends(get_db)):
    """Add many companies to the outreach queue at once."""
    return queueing.add_targets(db, [t.model_dump() for t in payload.targets])


@router.get("/queue")
def queue_status(db: Session = Depends(get_db)):
    upcoming = queueing.next_batch(db, 25)
    return {
        "counts": queueing.queue_counts(db),
        "next_up": [
            {
                "company": c.name,
                "domain": c.domain,
                "target_role": c.target_role,
                "resume_variant": c.resume_variant,
                "priority": c.priority,
            }
            for c in upcoming
        ],
    }


@router.get("/reply-events", response_model=list[schemas.ReplyEventOut])
def list_reply_events(db: Session = Depends(get_db)):
    return db.scalars(
        select(models.ReplyEvent).order_by(models.ReplyEvent.id.desc())
    ).all()
