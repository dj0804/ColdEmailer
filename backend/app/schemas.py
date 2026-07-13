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
