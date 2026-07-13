"""Hunter.io client: domain search + email finder.

Docs: https://hunter.io/api-documentation/v2
Free tier allows a limited number of requests/month, so callers should treat
failures/quota errors as "no result" and fall through to the next strategy.
"""

from __future__ import annotations

import httpx

from ...config import settings

BASE = "https://api.hunter.io/v2"


def domain_search(domain: str, limit: int = 10) -> list[dict]:
    """Return candidate contacts for a domain, best (highest confidence) first."""
    if not settings.hunter_api_key:
        return []
    try:
        r = httpx.get(
            f"{BASE}/domain-search",
            params={
                "domain": domain,
                "limit": limit,
                "api_key": settings.hunter_api_key,
            },
            timeout=20,
        )
        r.raise_for_status()
        emails = r.json().get("data", {}).get("emails", [])
    except (httpx.HTTPError, ValueError):
        return []

    results: list[dict] = []
    for e in emails:
        results.append(
            {
                "email": e.get("value"),
                "name": " ".join(
                    p for p in [e.get("first_name"), e.get("last_name")] if p
                )
                or None,
                "title": e.get("position"),
                "confidence": e.get("confidence"),
            }
        )
    # Prefer contacts most likely to read outreach (recruiting/talent/people/hr).
    results.sort(key=lambda c: (c.get("confidence") or 0), reverse=True)
    return results


def email_finder(domain: str, first_name: str, last_name: str) -> dict | None:
    """Find a specific person's email at a domain. Returns dict or None."""
    if not settings.hunter_api_key:
        return None
    try:
        r = httpx.get(
            f"{BASE}/email-finder",
            params={
                "domain": domain,
                "first_name": first_name,
                "last_name": last_name,
                "api_key": settings.hunter_api_key,
            },
            timeout=20,
        )
        r.raise_for_status()
        data = r.json().get("data", {})
    except (httpx.HTTPError, ValueError):
        return None
    if not data.get("email"):
        return None
    return {
        "email": data["email"],
        "name": f"{first_name} {last_name}",
        "title": data.get("position"),
        "confidence": data.get("score"),
    }
