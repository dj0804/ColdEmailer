"""Scrape team/about pages for emails — company-domain only, robots-respecting.

Hard rules (guardrails):
- Only fetches hosts that belong to the company's own domain. Never LinkedIn or
  any third-party host.
- Honors robots.txt for every URL before fetching.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup

USER_AGENT = "ApplierBot/0.1 (personal job-search outreach)"

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

# Candidate paths where contact/team emails commonly live.
CANDIDATE_PATHS = [
    "",
    "/team",
    "/about",
    "/about-us",
    "/company",
    "/people",
    "/contact",
    "/careers",
]


def _registrable(host: str) -> str:
    """Crude registrable-domain reducer: last two labels (good enough for allowlisting)."""
    parts = host.lower().lstrip("www.").split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host.lower()


def _same_company(url: str, domain: str) -> bool:
    host = urlparse(url).hostname or ""
    return _registrable(host) == _registrable(domain)


def _robots_ok(url: str) -> bool:
    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    rp = RobotFileParser()
    try:
        rp.set_url(robots_url)
        rp.read()
    except Exception:  # noqa: BLE001 - if robots is unreachable, be permissive
        return True
    return rp.can_fetch(USER_AGENT, url)


def _fetch(url: str) -> str | None:
    try:
        r = httpx.get(
            url,
            headers={"User-Agent": USER_AGENT},
            timeout=15,
            follow_redirects=True,
        )
        if r.status_code == 200 and "text/html" in r.headers.get("content-type", ""):
            return r.text
    except httpx.HTTPError:
        return None
    return None


def scrape_emails(domain: str, max_pages: int = 6) -> list[dict]:
    """Return emails found on the company's own team/about/contact pages.

    Each result: {email, name(None), title(None), page}. Emails are filtered to
    the company domain to avoid picking up vendors/social handles.
    """
    base = domain if domain.startswith("http") else f"https://{domain}"
    root_host = urlparse(base).hostname or domain
    found: dict[str, dict] = {}

    pages_fetched = 0
    for path in CANDIDATE_PATHS:
        if pages_fetched >= max_pages:
            break
        url = urljoin(base + "/", path.lstrip("/"))
        if not _same_company(url, root_host):
            continue
        if not _robots_ok(url):
            continue
        html = _fetch(url)
        pages_fetched += 1
        if not html:
            continue
        soup = BeautifulSoup(html, "html.parser")

        # Prefer mailto: links (most reliable), then raw text matches.
        candidates: set[str] = set()
        for a in soup.select("a[href^=mailto]"):
            addr = a.get("href", "").removeprefix("mailto:").split("?")[0].strip()
            if addr:
                candidates.add(addr)
        candidates.update(EMAIL_RE.findall(soup.get_text(" ")))

        for email in candidates:
            email = email.lower()
            email_domain = email.split("@")[-1]
            if _registrable(email_domain) != _registrable(root_host):
                continue  # skip vendor/social emails
            found.setdefault(
                email, {"email": email, "name": None, "title": None, "page": url}
            )

    return list(found.values())
