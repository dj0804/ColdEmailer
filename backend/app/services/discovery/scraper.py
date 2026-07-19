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
    """Crude registrable-domain reducer: last two labels (good enough for allowlisting).

    NB: use removeprefix, not lstrip — lstrip strips *characters*, which turned
    'whatfix.com' into 'hatfix.com' and would have sent mail to another domain.
    """
    h = host.lower().removeprefix("www.")
    parts = h.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else h


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


def fetch_context_text(domain: str, max_chars: int = 2500) -> str:
    """Fetch homepage + /about visible text as grounding for personalization.

    Company-domain-only and robots-respecting, same as the email scraper. Returns
    a trimmed plain-text snippet ('' if nothing usable).
    """
    base = domain if domain.startswith("http") else f"https://{domain}"
    root_host = urlparse(base).hostname or domain
    chunks: list[str] = []
    for path in ("", "/about", "/about-us", "/company"):
        url = urljoin(base + "/", path.lstrip("/"))
        if not _same_company(url, root_host) or not _robots_ok(url):
            continue
        html = _fetch(url)
        if not html:
            continue
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        text = " ".join(soup.get_text(" ").split())
        if text:
            chunks.append(text)
        if sum(len(c) for c in chunks) >= max_chars:
            break
    return " ".join(chunks)[:max_chars]


# Local-parts that indicate a shared/role inbox rather than a person. Cold
# outreach to these lands in a queue nobody owns, and we can't personalise the
# greeting, so they're only used as a last resort.
ROLE_LOCALPARTS = {
    "info", "contact", "hello", "hi", "support", "help", "sales", "admin",
    "careers", "career", "jobs", "job", "hr", "recruiting", "recruitment",
    "team", "press", "media", "marketing", "legal", "privacy", "security",
    "billing", "accounts", "office", "enquiry", "enquiries", "inquiry",
    "noreply", "no-reply", "donotreply", "webmaster", "postmaster", "mail",
    "general", "partnerships", "partner", "business", "bd", "invest",
}

# Job-title words used to spot a title sitting next to a name on a team page.
_TITLE_HINT = re.compile(
    r"\b(founder|co-?founder|ceo|cto|coo|cpo|chief|head|director|vp|vice president|"
    r"lead|manager|engineer|scientist|recruiter|talent|people|hr|principal|"
    r"partner|president|officer)\b",
    re.I,
)
# Two-to-three capitalised words, i.e. a plausible human name.
_NAME_RE = re.compile(r"^[A-Z][a-z'’-]{1,20}(?: [A-Z][a-z'’-]{1,20}){1,2}$")

# Marketing headings are also Capitalised Word Pairs ("Our Vision", "Recent
# Update"), and treating them as people produced fabricated addresses like
# our.vision@company.com. Any phrase containing one of these is not a person.
_NOT_NAME_WORDS = {
    "our", "the", "your", "their", "this", "that", "these", "those", "we",
    "why", "how", "what", "who", "when", "where", "all", "more", "read",
    "learn", "view", "get", "join", "meet", "see", "explore", "discover",
    "contact", "about", "home", "privacy", "terms", "policy", "cookie",
    "recent", "latest", "news", "blog", "press", "media", "case", "study",
    "customer", "client", "partner", "product", "solution", "platform",
    "service", "company", "team", "career", "careers", "job", "jobs",
    "vision", "mission", "values", "story", "journey", "update", "updates",
    "sign", "log", "start", "book", "request", "demo", "free", "trial",
    "privacy", "support", "help", "faq", "resources", "events", "webinar",
    "white", "paper", "ebook", "guide", "report", "download", "subscribe",
    "follow", "share", "copyright", "reserved", "rights", "inc", "ltd",
    "technologies", "solutions", "systems", "labs", "group", "global",
}


def looks_like_person_name(text: str) -> bool:
    """True only for text that plausibly names a human, not a page heading."""
    if not _NAME_RE.match(text):
        return False
    words = [w.lower().strip(".,'’-") for w in text.split()]
    return not any(w in _NOT_NAME_WORDS for w in words)


def is_role_address(email: str) -> bool:
    return email.split("@", 1)[0].lower().strip(".") in ROLE_LOCALPARTS


def name_from_localpart(email: str) -> str | None:
    """Derive a display name from a personal-looking local part.

    'priya.sharma@x.com' -> 'Priya Sharma'. Returns None for ambiguous forms
    (initials, single short tokens, anything numeric) rather than guessing.
    """
    local = email.split("@", 1)[0]
    if is_role_address(email) or any(ch.isdigit() for ch in local):
        return None
    parts = [p for p in re.split(r"[._\-]+", local) if p]
    if len(parts) >= 2 and all(len(p) >= 2 for p in parts[:2]):
        return " ".join(p.capitalize() for p in parts[:2])
    if len(parts) == 1 and len(parts[0]) >= 4:
        return parts[0].capitalize()  # 'pratyush@' -> 'Pratyush'
    return None


def _nearby_person(anchor) -> tuple[str | None, str | None]:
    """Look around a mailto link for a person's name and title."""
    node = anchor
    for _ in range(4):  # walk up a few levels into the card/list-item
        node = node.parent
        if node is None:
            return None, None
        text = " ".join(node.get_text(" ").split())
        if len(text) > 400:  # too broad to attribute reliably
            break
        name = title = None
        for line in re.split(r"\s{2,}|[|·•\n]", node.get_text("\n")):
            line = line.strip()
            if not line:
                continue
            if name is None and looks_like_person_name(line):
                name = line
            elif title is None and _TITLE_HINT.search(line) and len(line) < 70:
                title = line
        if name:
            return name, title
    return None, None


def scrape_people(domain: str, max_pages: int = 4) -> list[dict]:
    """Names + titles from team/about pages, even when no email is published.

    Feeds the pattern-guess tier: knowing 'Priya Sharma, Head of Talent' lets us
    construct and verify priya.sharma@domain without any paid API.
    """
    base = domain if domain.startswith("http") else f"https://{domain}"
    root_host = urlparse(base).hostname or domain
    people: dict[str, dict] = {}

    for path in ("/team", "/about", "/about-us", "/people", "/leadership", "/company"):
        if len(people) >= 12:
            break
        url = urljoin(base + "/", path.lstrip("/"))
        if not _same_company(url, root_host) or not _robots_ok(url):
            continue
        html = _fetch(url)
        if not html:
            continue
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        # Headings and short standalone elements are where names usually sit.
        for el in soup.find_all(["h2", "h3", "h4", "h5", "strong", "b", "p", "span"]):
            txt = " ".join(el.get_text(" ").split())
            if not looks_like_person_name(txt):
                continue
            title = None
            sib = el.find_next(string=_TITLE_HINT)
            if sib:
                cand = " ".join(str(sib).split())
                if len(cand) < 70:
                    title = cand
            people.setdefault(txt, {"name": txt, "title": title, "page": url})
    return list(people.values())


def scrape_emails(domain: str, max_pages: int = 6) -> list[dict]:
    """Return emails found on the company's own team/about/contact pages.

    Each result: {email, name, title, page, is_role}. Emails are filtered to the
    company domain to avoid picking up vendors/social handles. Names come from
    the surrounding DOM where possible, else are inferred from the local part.
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

        # Prefer mailto: links — they carry DOM context we can read a name from.
        candidates: dict[str, tuple[str | None, str | None]] = {}
        for a in soup.select("a[href^=mailto]"):
            addr = a.get("href", "").removeprefix("mailto:").split("?")[0].strip()
            if addr:
                candidates[addr] = _nearby_person(a)
        for addr in EMAIL_RE.findall(soup.get_text(" ")):
            candidates.setdefault(addr, (None, None))

        for email, (dom_name, dom_title) in candidates.items():
            email = email.lower()
            if _registrable(email.split("@")[-1]) != _registrable(root_host):
                continue  # skip vendor/social emails
            found.setdefault(
                email,
                {
                    "email": email,
                    # DOM context beats a guess from the local part.
                    "name": dom_name or name_from_localpart(email),
                    "title": dom_title,
                    "page": url,
                    "is_role": is_role_address(email),
                },
            )

    # Personal, named addresses first; shared role inboxes last.
    return sorted(
        found.values(),
        key=lambda c: (c["is_role"], c["name"] is None),
    )
