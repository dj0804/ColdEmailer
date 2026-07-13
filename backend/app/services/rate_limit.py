"""Daily send-cap enforcement (Gmail-friendly guardrail)."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import EmailDraft


def sends_today(db: Session) -> int:
    start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return (
        db.scalar(
            select(func.count(EmailDraft.id)).where(
                EmailDraft.status == "sent",
                EmailDraft.sent_at >= start,
            )
        )
        or 0
    )


def remaining_today(db: Session) -> int:
    return max(0, settings.daily_send_cap - sends_today(db))


class RateLimitExceeded(Exception):
    pass


def enforce(db: Session) -> None:
    if sends_today(db) >= settings.daily_send_cap:
        raise RateLimitExceeded(
            f"Daily send cap of {settings.daily_send_cap} reached. "
            "Adjust DAILY_SEND_CAP in .env or try tomorrow."
        )
