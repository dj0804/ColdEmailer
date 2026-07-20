from datetime import datetime

from pydantic import BaseModel, ConfigDict


class CompanyCreate(BaseModel):
    name: str
    domain: str | None = None
    careers_url: str | None = None
    notes: str | None = None


class CompanyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    domain: str | None
    careers_url: str | None
    notes: str | None
    created_at: datetime


class ContactOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    company_id: int
    name: str | None
    email: str
    title: str | None
    source: str
    verified: bool
    created_at: datetime


class DiscoverRequest(BaseModel):
    # Optional named person to enable pattern-guess + verify as a fallback.
    person_first: str | None = None
    person_last: str | None = None


class DiscoverResponse(BaseModel):
    company_id: int
    found: bool
    contact: ContactOut | None = None
    source: str | None = None
    detail: str | None = None


# ---- Applications ----
class ApplicationCreate(BaseModel):
    company_id: int
    contact_id: int | None = None  # defaults to the company's latest contact
    role: str = "6-month Software/ML Engineering Internship (intern-to-FTE)"
    resume_variant: str | None = None  # ai_engineer | ml_engineer | data_scientist


class ApplicationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    company_id: int
    contact_id: int | None
    role: str | None
    resume_variant: str | None
    stage: str
    gmail_thread_id: str | None
    sent_at: datetime | None
    last_contact_at: datetime | None
    created_at: datetime


# ---- Drafts ----
class DraftOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    application_id: int
    type: str
    subject: str
    body: str
    attachment_paths: str | None
    batch_id: str | None
    status: str
    approved_at: datetime | None
    sent_at: datetime | None
    gmail_message_id: str | None
    created_at: datetime


class DraftEdit(BaseModel):
    subject: str | None = None
    body: str | None = None


class BatchGenerate(BaseModel):
    company_ids: list[int]
    role: str = "6-month Software/ML Engineering Internship (intern-to-FTE)"
    resume_variant: str | None = None  # applied to every app in the batch


class SendResult(BaseModel):
    draft_id: int
    application_id: int
    to: str
    gmail_message_id: str | None
    thread_id: str | None
    sent_at: str


class TargetIn(BaseModel):
    name: str
    domain: str | None = None
    target_role: str | None = None
    resume_variant: str | None = None  # inferred from target_role when omitted
    priority: int = 100


class BulkTargets(BaseModel):
    targets: list[TargetIn]


class ManualContact(BaseModel):
    """Add a contact you found yourself and draft outreach in one step."""

    company_name: str
    domain: str | None = None
    contact_name: str
    email: str
    title: str | None = None
    target_role: str | None = None
    resume_variant: str | None = None  # inferred from target_role when omitted


class ReplyEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    application_id: int
    gmail_message_id: str
    classification: str
    snippet: str | None
    classified_at: datetime
