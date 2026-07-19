"""Pluggable email-verification interface.

Providers implement ``verify(email) -> VerifyResult``. Chosen via
``EMAIL_VERIFY_PROVIDER`` in .env. Currently ships Hunter's verifier;
NeverBounce/ZeroBounce are stubbed with the same shape and easy to fill in.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import httpx

from ...config import settings
from . import quota


@dataclass
class VerifyResult:
    email: str
    deliverable: bool  # True if safe to send
    status: str        # provider-native status string
    score: int | None = None


def _mx_verify(email: str) -> VerifyResult:
    """Free fallback: syntax + MX-record check. No API, no quota.

    This proves the *domain* can receive mail, NOT that the mailbox exists — so
    results are flagged risky (deliverable=True, but callers should treat the
    contact as unverified and lower-confidence than an API-verified one).
    """
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[A-Za-z]{2,}", email):
        return VerifyResult(email, deliverable=False, status="bad_syntax")
    domain = email.rsplit("@", 1)[1]
    try:
        import dns.resolver

        answers = dns.resolver.resolve(domain, "MX", lifetime=8)
        if len(answers) > 0:
            return VerifyResult(email, deliverable=True, status="mx_ok")
        return VerifyResult(email, deliverable=False, status="no_mx")
    except ImportError:
        return VerifyResult(email, deliverable=False, status="no_dns_lib")
    except Exception:  # noqa: BLE001 - NXDOMAIN, timeout, no answer, etc.
        return VerifyResult(email, deliverable=False, status="mx_lookup_failed")


def _hunter_verify(email: str) -> VerifyResult:
    # Fall through to the free checker once the monthly quota is spent.
    if quota.is_exhausted("hunter"):
        return _mx_verify(email)
    try:
        r = httpx.get(
            "https://api.hunter.io/v2/email-verifier",
            params={"email": email, "api_key": settings.email_verify_api_key},
            timeout=20,
        )
        if r.status_code in (429, 403):
            quota.mark_exhausted("hunter")
            return _mx_verify(email)
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
    "mx": _mx_verify,  # free, no API key needed
}


def verify(email: str) -> VerifyResult:
    provider = _PROVIDERS.get(settings.email_verify_provider.lower())
    if provider is None or not settings.email_verify_api_key:
        # No paid verifier configured — still better than nothing.
        return _mx_verify(email)
    return provider(email)
