import logging
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .config import settings
from .db import Base, engine
from .jobs import check_ghosting, daily_outreach, poll_replies
from .services import job_log

# APScheduler is silent by default, which makes "did the job run?" unanswerable
# from the logs. INFO gives us an execution line per run in journalctl.
logging.getLogger("apscheduler").setLevel(logging.INFO)
_log = logging.getLogger("applier.jobs")
_log.setLevel(logging.INFO)


def _tracked(job_id: str, fn):
    """Run a job, logging and persisting its outcome either way."""

    def wrapper():
        _log.info("job %s starting", job_id)
        try:
            result = fn()
        except Exception as e:  # noqa: BLE001 - never let a job kill the scheduler
            _log.exception("job %s FAILED", job_id)
            job_log.record(job_id, error=f"{type(e).__name__}: {e}")
            return None
        _log.info("job %s finished: %s", job_id, result)
        job_log.record(job_id, result=result if isinstance(result, dict) else None)
        return result

    wrapper.__name__ = f"tracked_{job_id}"
    return wrapper
from .routers import applications as applications_router
from .routers import companies as companies_router
from .routers import dashboard as dashboard_router
from .routers import drafts as drafts_router
from .routers import gmail as gmail_router
from .routers import jobs as jobs_router

app = FastAPI(title="Applier")
scheduler = BackgroundScheduler(timezone="UTC")


@app.on_event("startup")
def startup() -> None:
    from . import models  # noqa: F401  (register tables before create_all)

    Base.metadata.create_all(bind=engine)

    scheduler.add_job(
        _tracked("poll_replies", poll_replies),
        "interval",
        minutes=settings.reply_poll_minutes,
        id="poll_replies",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        _tracked("check_ghosting", check_ghosting),
        "cron",
        hour=settings.ghost_check_hour,
        id="check_ghosting",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    if settings.outreach_enabled:
        # Weekdays only — cold email sent over a weekend just gets buried.
        scheduler.add_job(
            _tracked("daily_outreach", daily_outreach),
            "cron",
            day_of_week="mon-fri",
            hour=settings.outreach_hour,
            id="daily_outreach",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )

    if not scheduler.running:
        scheduler.start()


@app.on_event("shutdown")
def shutdown() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)


app.include_router(gmail_router.router)
app.include_router(companies_router.router)
app.include_router(applications_router.router)
app.include_router(drafts_router.router)
app.include_router(jobs_router.router)
app.include_router(dashboard_router.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}


# Serve the built React dashboard (frontend/dist) when present, so a deployment
# needs no separate web server. Built locally and uploaded — a 512MB box can't
# comfortably run `npm build`. Mounted last so /api/* routes always win.
_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if _DIST.is_dir():
    app.mount("/", StaticFiles(directory=str(_DIST), html=True), name="dashboard")
