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

SYSTEM = """You are helping a strong CS undergraduate write cold outreach emails \
to real people at companies he wants to intern at (a 6-month internship intended \
to convert to a full-time role). You write like a sharp, genuine human — not a \
template, not a marketing bot.

Hard rules:
- Sound like a real person emailing another real person. Vary sentence rhythm.
- Open with something specific to THIS company and THIS recipient's role. Never \
open with a generic "I hope this email finds you well" or "I am writing to".
- Ground every company-specific claim in the provided company context or the \
recipient's title. Do NOT invent facts, products, or news you weren't given.
- Connect 1-2 concrete, relevant things from the candidate's resume to what this \
company/person likely cares about. Be specific (name the tech or the result), not \
a laundry list.
- Be concise: 110-170 words in the body. Short paragraphs.
- Confident but humble; no groveling, no hype, no buzzword soup.
- The ask is a brief chat about a 6-month internship that could convert to \
full-time. Make the ask easy to say yes to.
- Do not fabricate a shared connection, a prior meeting, or that you use their \
product unless the context supports it.
- End with a sign-off using the candidate's real name and contact line provided.

Return ONLY a JSON object: {"subject": "...", "body": "..."}. The subject is \
specific and low-hype (no clickbait, no ALL CAPS). The body is the full email \
text including the sign-off."""

USER_TEMPLATE = """CANDIDATE RESUME (source of truth for the candidate's background):
{resume}

CANDIDATE CONTACT (use exactly in the sign-off):
Name: {name}
Email: {email}
Phone: {phone}
Links: {links}

TARGET COMPANY: {company}
ROLE THE CANDIDATE WANTS: {role}

RECIPIENT:
Name: {recipient_name}
Title: {recipient_title}

COMPANY CONTEXT (scraped from their site; may be empty — if empty, rely only on \
the recipient's title and do NOT invent specifics):
{company_context}

Write the email now. Make it clearly tailored to {company} and to {recipient_name}'s \
role. Return only the JSON object."""


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
        company=company_name,
        role=role,
        recipient_name=recipient_name or "the hiring team",
        recipient_title=recipient_title or "(unknown title)",
        company_context=company_context or "(none available)",
    )

    raw = llm.chat(
        model=settings.openai_draft_model,
        system=SYSTEM,
        user=user,
        # Reasoning models (gpt-5) spend part of this budget on hidden reasoning
        # before emitting the answer, so leave generous headroom.
        max_tokens=5000,
        temperature=0.8,  # ignored by reasoning models; adds variety on others
        json_mode=True,
    )
    data = _extract_json(raw)
    subject = (data.get("subject") or "").strip()
    body = (data.get("body") or "").strip()
    if not subject or not body:
        raise ValueError(f"LLM returned incomplete draft: {raw[:200]}")
    return {"subject": subject, "body": body}
