from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---- Stage / status vocabularies (kept as plain strings in SQLite) ----
# Application.stage:
#   draft | pending_approval | sent | recruiter_reply | interview_request
#   | rejection | ghosted_dead
# EmailDraft.type:   outreach | nudge1 | nudge2
# EmailDraft.status: pending | approved | sent | rejected
# Contact.source:    hunter | scrape | pattern_verified


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    domain: Mapped[str | None] = mapped_column(String(255), nullable=True)
    careers_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    contacts: Mapped[list["Contact"]] = relationship(
        back_populates="company", cascade="all, delete-orphan"
    )
    applications: Mapped[list["Application"]] = relationship(
        back_populates="company", cascade="all, delete-orphan"
    )


class Contact(Base):
    __tablename__ = "contacts"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email: Mapped[str] = mapped_column(String(320))
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source: Mapped[str] = mapped_column(String(32))  # hunter|scrape|pattern_verified
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    company: Mapped["Company"] = relationship(back_populates="contacts")


class Application(Base):
    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))
    contact_id: Mapped[int | None] = mapped_column(
        ForeignKey("contacts.id"), nullable=True
    )
    role: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Which role-specific resume PDF to attach (see services/resume.py).
    resume_variant: Mapped[str | None] = mapped_column(String(32), nullable=True)
    stage: Mapped[str] = mapped_column(String(32), default="draft")
    gmail_thread_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_contact_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    company: Mapped["Company"] = relationship(back_populates="applications")
    contact: Mapped["Contact | None"] = relationship()
    drafts: Mapped[list["EmailDraft"]] = relationship(
        back_populates="application", cascade="all, delete-orphan"
    )
    reply_events: Mapped[list["ReplyEvent"]] = relationship(
        back_populates="application", cascade="all, delete-orphan"
    )
    nudge_history: Mapped[list["NudgeHistory"]] = relationship(
        back_populates="application", cascade="all, delete-orphan"
    )


class EmailDraft(Base):
    __tablename__ = "email_drafts"

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id"))
    type: Mapped[str] = mapped_column(String(16))  # outreach|nudge1|nudge2
    subject: Mapped[str] = mapped_column(String(512))
    body: Mapped[str] = mapped_column(Text)
    attachment_paths: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON list
    batch_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    gmail_message_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    application: Mapped["Application"] = relationship(back_populates="drafts")


class ReplyEvent(Base):
    __tablename__ = "reply_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id"))
    gmail_message_id: Mapped[str] = mapped_column(String(64))
    classification: Mapped[str] = mapped_column(String(32))
    snippet: Mapped[str | None] = mapped_column(Text, nullable=True)
    classified_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    application: Mapped["Application"] = relationship(back_populates="reply_events")


class NudgeHistory(Base):
    __tablename__ = "nudge_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id"))
    nudge_number: Mapped[int] = mapped_column(Integer)  # 1 or 2
    draft_id: Mapped[int | None] = mapped_column(
        ForeignKey("email_drafts.id"), nullable=True
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    application: Mapped["Application"] = relationship(back_populates="nudge_history")
