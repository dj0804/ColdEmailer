"""Contact-discovery chain: Hunter.io -> page scrape -> pattern-guess + verify.

Returns a single best contact (or None) with a ``source`` tag describing which
strategy produced it: 'hunter' | 'scrape' | 'pattern_verified'.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from . import hunter, pattern_guess, scraper, verify


@dataclass
class DiscoveredContact:
    email: str
    name: str | None
    title: str | None
    source: str          # hunter | scrape | pattern_verified
    verified: bool
    confidence: int | None = None
    detail: str | None = None  # human-readable note (page url, verify status, etc.)


# Titles we most want to reach for job outreach.
_PREFERRED_TITLE_HINTS = (
    "recruit",
    "talent",
    "people",
    "human resources",
    "hr",
    "hiring",
    "university",
    "campus",
    "founder",
    "ceo",
)


def _title_rank(title: str | None) -> int:
    if not title:
        return 0
    t = title.lower()
    return sum(1 for h in _PREFERRED_TITLE_HINTS if h in t)


def discover_contact(
    domain: str,
    person_first: str | None = None,
    person_last: str | None = None,
) -> DiscoveredContact | None:
    """Run the strategy chain and return the best contact found, or None."""

    # --- Strategy 1: Hunter.io domain search ---
    # Returns [] immediately when the key is missing or the monthly quota is
    # known-spent, so we fall through to the free tiers without wasting a call.
    hunter_hits = hunter.domain_search(domain)
    if hunter_hits:
        # Rank by preferred title, then confidence.
        hunter_hits.sort(
            key=lambda c: (_title_rank(c.get("title")), c.get("confidence") or 0),
            reverse=True,
        )
        best = hunter_hits[0]
        if best.get("email"):
            return DiscoveredContact(
                email=best["email"],
                name=best.get("name"),
                title=best.get("title"),
                source="hunter",
                verified=(best.get("confidence") or 0) >= 80,
                confidence=best.get("confidence"),
                detail=f"hunter confidence {best.get('confidence')}",
            )

    # --- Strategy 2: scrape the company's own team/about/contact pages ---
    scraped = scraper.scrape_emails(domain)
    if scraped:
        best = scraped[0]
        return DiscoveredContact(
            email=best["email"],
            name=best.get("name"),
            title=best.get("title"),
            source="scrape",
            verified=False,
            detail=f"found on {best.get('page')}",
        )

    # --- Strategy 3: pattern-guess a named person, then verify ---
    if person_first:
        for candidate in pattern_guess.guess_patterns(
            person_first, person_last or "", domain
        ):
            result = verify.verify(candidate)
            if result.deliverable:
                # An MX-only check proves the domain accepts mail, not that the
                # mailbox exists — don't claim 'verified' on that basis.
                mx_only = result.status == "mx_ok"
                return DiscoveredContact(
                    email=candidate,
                    name=" ".join(p for p in [person_first, person_last] if p),
                    title=None,
                    source="pattern_verified",
                    verified=not mx_only,
                    confidence=result.score,
                    detail=f"verifier: {result.status}",
                )

    return None


def to_dict(c: DiscoveredContact | None) -> dict | None:
    return asdict(c) if c else None
