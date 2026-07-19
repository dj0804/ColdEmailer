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


def _from_scraped_person(c: dict) -> DiscoveredContact:
    return DiscoveredContact(
        email=c["email"],
        name=c.get("name"),
        title=c.get("title"),
        source="scrape",
        verified=False,  # published on their own site, but mailbox unconfirmed
        detail=f"named contact on {c.get('page')}",
    )


def _pattern_guess_for(
    domain: str, first: str, last: str | None
) -> DiscoveredContact | None:
    """Construct likely addresses for a known person and verify them.

    A guessed address is only accepted when a *mailbox-level* verifier confirms
    it. An MX record proves the domain accepts mail, not that the mailbox
    exists, so anything@realdomain.com passes an MX check — accepting on that
    basis fabricates plausible-looking addresses. When no real verifier is
    available this tier declines rather than guessing.
    """
    for candidate in pattern_guess.guess_patterns(first, last or "", domain):
        result = verify.verify(candidate)
        if result.deliverable and result.status != "mx_ok":
            return DiscoveredContact(
                email=candidate,
                name=" ".join(p for p in [first, last] if p),
                title=None,
                source="pattern_verified",
                verified=True,
                confidence=result.score,
                detail=f"verifier: {result.status}",
            )
    return None


def discover_contact(
    domain: str,
    person_first: str | None = None,
    person_last: str | None = None,
) -> DiscoveredContact | None:
    """Find the best contact for a domain, cheapest strategy first.

    Order is deliberate: the free tiers run before the metered API, but a
    *named* contact always beats a shared role inbox, because the outreach is
    personalised to a specific person and lands badly in an unowned mailbox.

      1. scrape the company's own pages for a named person's address
      2. scrape names off the team page, then pattern-guess + verify
      3. Hunter.io (metered)
      4. a generic role inbox found while scraping — last resort
    """
    scraped: list[dict] = []

    # --- Strategy 1 (free): a named person's address published on their site ---
    try:
        scraped = scraper.scrape_emails(domain)
    except Exception:  # noqa: BLE001 - scraping is best-effort
        scraped = []
    for c in scraped:
        if not c.get("is_role") and c.get("name"):
            return _from_scraped_person(c)

    # --- Strategy 2 (free): name from the team page + guessed/verified address --
    if person_first:
        hit = _pattern_guess_for(domain, person_first, person_last)
        if hit:
            return hit
    try:
        for person in scraper.scrape_people(domain):
            parts = person["name"].split()
            hit = _pattern_guess_for(domain, parts[0], parts[-1] if len(parts) > 1 else None)
            if hit:
                hit.title = person.get("title")
                hit.detail = f"{hit.detail}; name from {person.get('page')}"
                return hit
    except Exception:  # noqa: BLE001
        pass

    # --- Strategy 3 (metered): Hunter.io domain search ---
    # Returns [] immediately when the key is missing or the monthly quota is
    # known-spent, so we fall through without wasting a call.
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

    # --- Strategy 4 (last resort): a shared role inbox found while scraping ---
    # Worse than everything above — nobody owns careers@, and the email can't be
    # personalised to a person — but it beats not contacting the company at all.
    for c in scraped:
        if c.get("is_role"):
            return DiscoveredContact(
                email=c["email"],
                name=None,
                title=None,
                source="scrape_generic",
                verified=False,
                detail=f"role inbox on {c.get('page')}",
            )

    return None


def to_dict(c: DiscoveredContact | None) -> dict | None:
    return asdict(c) if c else None
