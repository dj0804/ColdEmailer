from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI

from .config import settings
from .db import Base, engine
from .jobs import poll_replies
from .routers import applications as applications_router
from .routers import companies as companies_router
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
        poll_replies,
        "interval",
        minutes=settings.reply_poll_minutes,
        id="poll_replies",
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


@app.get("/api/health")
def health():
    return {"status": "ok"}
