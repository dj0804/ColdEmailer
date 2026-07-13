"""Pluggable email-verification interface.

Providers implement ``verify(email) -> VerifyResult``. Chosen via
``EMAIL_VERIFY_PROVIDER`` in .env. Currently ships Hunter's verifier;
NeverBounce/ZeroBounce are stubbed with the same shape and easy to fill in.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from ...config import settings


@dataclass
class VerifyResult:
    email: str
    deliverable: bool  # True if safe to send
    status: str        # provider-native status string
    score: int | None = None


def _hunter_verify(email: str) -> VerifyResult:
    try:
        r = httpx.get(
            "https://api.hunter.io/v2/email-verifier",
            params={"email": email, "api_key": settings.email_verify_api_key},
            timeout=20,
        )
        r.raise_for_status()
        data = r.json().get("data", {})
    except (httpx.HTTPError, ValueError):
        return VerifyResult(email, deliverable=False, status="error")
    status = data.get("status", "unknown")
    # Hunter statuses: deliverable | risky | undeliverable | unknown
    deliverable = status in ("deliverable", "risky")
    return VerifyResult(email, deliverable, status, data.get("score"))


def _neverbounce_verify(email: str) -> VerifyResult:
    try:
        r = httpx.get(
            "https://api.neverbounce.com/v4/single/check",
            params={"key": settings.email_verify_api_key, "email": email},
            timeout=20,
        )
        r.raise_for_status()
        result = r.json().get("result", "unknown")
    except (httpx.HTTPError, ValueError):
        return VerifyResult(email, deliverable=False, status="error")
    deliverable = result in ("valid", "catchall")
    return VerifyResult(email, deliverable, result)


def _zerobounce_verify(email: str) -> VerifyResult:
    try:
        r = httpx.get(
            "https://api.zerobounce.net/v2/validate",
            params={"api_key": settings.email_verify_api_key, "email": email},
            timeout=20,
        )
        r.raise_for_status()
        status = r.json().get("status", "unknown")
    except (httpx.HTTPError, ValueError):
        return VerifyResult(email, deliverable=False, status="error")
    deliverable = status in ("valid", "catch-all")
    return VerifyResult(email, deliverable, status)


_PROVIDERS = {
    "hunter": _hunter_verify,
    "neverbounce": _neverbounce_verify,
    "zerobounce": _zerobounce_verify,
}


def verify(email: str) -> VerifyResult:
    provider = _PROVIDERS.get(settings.email_verify_provider.lower())
    if provider is None or not settings.email_verify_api_key:
        # No verifier configured: report unknown, not deliverable.
        return VerifyResult(email, deliverable=False, status="no_verifier")
    return provider(email)
