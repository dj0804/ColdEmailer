"""LLM-powered, humanized outreach drafting (per company AND per recipient).

Produces a distinct subject + body for each application. Personalization draws
on: the candidate's resume, the specific company (name + scraped site context +
notes), the specific recipient (name + title), and the role framing
(6-month internship -> full-time conversion).
"""

from __future__ import annotations

import json

from ..config import settings
from . import llm
from .discovery import scraper
from .resume import resume_text

SYSTEM = """You personalize a proven cold-outreach email for a CS student seeking a \
6-month internship. The candidate already wrote the email he wants; your job is to \
adapt it to ONE specific company and recipient — NOT to rewrite it in your own \
voice. Preserve his wording, rhythm, brevity, and humble tone. Fill the blanks; \
do not editorialize or pad.

This is the template and voice to follow closely:

  Hi {{first_name}},

  I'll keep this short.

  I'm Dev, a {{year}} at {{school}}. I've been following the work your team is \
doing around {{specific_area}}, and it genuinely looks like the kind of \
engineering environment I want to learn in.

  Over the past year I've worked on ML systems across internships at {{prior}} — \
spanning recommendation engines, computer vision, and scalable AI pipelines. I'm \
now looking for a 6-month internship — {{availability}}.

  {{specific_ask}}

  I've attached my resume. If you think my profile could fit your team or another \
team at {{company}}, I'd really appreciate the chance to chat.

  Either way, thanks for reading — I appreciate it.

  Cheers,
  Dev Jain

Rules:
- Keep it SHORT — roughly 130-160 words in the body, same paragraphing as above.
- {{first_name}} = the recipient's first name.
- {{specific_area}} is the make-or-break slot: it must be a CONCRETE thing this \
company actually does — a real product, research direction, platform, or domain — \
drawn only from the provided company context or the recipient's title. If the \
context is thin, use a genuinely accurate description of the company's domain; \
NEVER invent a product, launch, or detail you weren't given, and never write \
vague filler like "your work in AI".
- {{specific_ask}}: one or two sentences making a direct, specific ask for a \
6-month internship on the recipient's team, and SUBTLY note openness to it \
converting to a full-time role (a light touch like "with the hope it could grow \
into something longer-term" — never pushy, never the main focus).
- Do NOT add new claims about the candidate beyond the resume. Do NOT invent a \
shared connection or that he uses their product.
- Keep the candidate's phrases ("I'll keep this short.", "Either way, thanks for \
reading — I appreciate it.", "Cheers,"). You may lightly adjust the credibility \
line to fit, but keep it brief and non-jargony.
- End with the sign-off block using the exact contact line provided.

Return ONLY a JSON object: {"subject": "...", "body": "..."}. Subject is short, \
specific, low-hype (e.g. "6-month internship — final-year CS student at VIT"), \
tailored to the company where natural. Body is the full email including sign-off."""

USER_TEMPLATE = """Fill the template for this specific recipient and company.

CANDIDATE FACTS (use these exactly):
Name: {name}
Year/School: {year} at {school}
Prior internships: {prior}
Availability: {availability}
Sign-off contact line (use verbatim under "Dev Jain"):
{email} | {phone}
{links}

RECIPIENT:
First name to greet: {recipient_name}
Title: {recipient_title}

TARGET COMPANY: {company}

COMPANY CONTEXT (scraped from their own site; may be empty — if empty, describe \
their domain accurately from the recipient's title and company name, and do NOT \
invent specifics):
{company_context}

Resume (for grounding the credibility line; do not copy jargon wholesale):
{resume}

Produce the JSON now. The {{specific_area}} must be concrete and true for \
{company}. Return only the JSON object."""


def _extract_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("{"):]
    start, end = text.find("{"), text.rfind("}")
    return json.loads(text[start : end + 1])


def generate_outreach(
    *,
    company_name: str,
    company_domain: str | None,
    company_notes: str | None,
    recipient_name: str | None,
    recipient_title: str | None,
    role: str,
) -> dict:
    """Return {'subject': str, 'body': str} for a single personalized outreach email."""
    company_context = ""
    if company_domain:
        try:
            company_context = scraper.fetch_context_text(company_domain)
        except Exception:  # noqa: BLE001 - context is best-effort grounding
            company_context = ""
    if company_notes:
        company_context = f"{company_notes}\n{company_context}".strip()

    user = USER_TEMPLATE.format(
        resume=resume_text(),
        name=settings.candidate_name,
        email=settings.candidate_email,
        phone=settings.candidate_phone,
        links=settings.candidate_links,
        school=settings.candidate_school,
        year=settings.candidate_year,
        prior=settings.candidate_prior,
        availability=settings.candidate_availability,
        company=company_name,
        recipient_name=(recipient_name.split()[0] if recipient_name else "there"),
        recipient_title=recipient_title or "(unknown title)",
        company_context=company_context or "(none available)",
    )

    # gpt-5 occasionally returns empty/unparseable output; retry a couple times.
    last_err: Exception | None = None
    for attempt in range(3):
        raw = llm.chat(
            model=settings.openai_draft_model,
            system=SYSTEM,
            user=user,
            # Reasoning models (gpt-5) spend part of this budget on hidden reasoning
            # before emitting the answer, so leave generous headroom.
            max_tokens=6000,
            temperature=0.8,       # ignored by reasoning models; variety on others
            reasoning_effort="low",  # templated fill — heavy reasoning not needed
            json_mode=True,
        )
        try:
            data = _extract_json(raw)
            subject = (data.get("subject") or "").strip()
            body = (data.get("body") or "").strip()
            if subject and body:
                return {"subject": subject, "body": body}
            last_err = ValueError(f"incomplete draft: {raw[:120]!r}")
        except (ValueError, KeyError) as e:
            last_err = e
    raise ValueError(f"LLM failed to produce a valid draft after 3 tries: {last_err}")
