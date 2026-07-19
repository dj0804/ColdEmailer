"""Company outreach queue: bulk intake + resume-variant inference.

The daily routine (jobs.daily_outreach) pulls from this queue. Companies are
worked in `priority` order, oldest first within a priority.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Application, Company

# Role-title keywords -> resume variant. Checked in order, first match wins,
# so the more specific patterns come first.
_VARIANT_RULES: list[tuple[tuple[str, ...], str]] = [
    (("data scientist", "data science", "data resident", "analytics", "statistic"),
     "data_scientist"),
    (("generative ai", "genai", "llm", "nlp", "agent", "rag", "prompt"),
     "ai_engineer"),
    (("machine learning", "ml engineer", "ml intern", "ai/ml", "computer vision",
      "cv intern", "deep learning", "reinforcement"),
     "ml_engineer"),
    (("ai engineer", "ai software", "ai intern", "ai implementation", "applied ai"),
     "ai_engineer"),
]


def infer_variant(role: str | None) -> str | None:
    """Best-guess resume variant from a role title ('' -> None, caller falls back)."""
    if not role:
        return None
    r = role.lower()
    for keywords, variant in _VARIANT_RULES:
        if any(k in r for k in keywords):
            return variant
    return None


def normalize_domain(domain: str | None) -> str | None:
    if not domain:
        return None
    d = domain.strip().lower()
    for prefix in ("https://", "http://", "www."):
        d = d.removeprefix(prefix)
    return d.rstrip("/") or None


def add_targets(db: Session, targets: list[dict]) -> dict:
    """Bulk-add companies to the queue, skipping ones already present by domain.

    Each target: {name, domain, target_role?, resume_variant?, priority?}
    """
    existing = {
        normalize_domain(d)
        for d in db.scalars(select(Company.domain)).all()
        if d
    }
    added, skipped = [], []
    for t in targets:
        domain = normalize_domain(t.get("domain"))
        name = (t.get("name") or "").strip()
        if not name:
            continue
        if domain and domain in existing:
            skipped.append(name)
            continue
        role = t.get("target_role")
        company = Company(
            name=name,
            domain=domain,
            target_role=role,
            resume_variant=t.get("resume_variant") or infer_variant(role),
            priority=int(t.get("priority", 100)),
            queue_status="queued",
            notes=f"Target role: {role}" if role else None,
        )
        db.add(company)
        added.append(name)
        if domain:
            existing.add(domain)
    db.commit()
    return {"added": len(added), "skipped_duplicates": len(skipped),
            "added_names": added, "skipped_names": skipped}


def next_batch(db: Session, limit: int) -> list[Company]:
    """Queued companies that don't yet have an application, best-priority first."""
    have_app = select(Application.company_id).distinct()
    return list(
        db.scalars(
            select(Company)
            .where(
                Company.queue_status == "queued",
                Company.id.not_in(have_app),
            )
            .order_by(Company.priority, Company.id)
            .limit(limit)
        ).all()
    )


def queue_counts(db: Session) -> dict:
    rows = db.execute(
        select(Company.queue_status, Company.id).select_from(Company)
    ).all()
    counts: dict[str, int] = {}
    for status, _ in rows:
        counts[status] = counts.get(status, 0) + 1
    return counts
