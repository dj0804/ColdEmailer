"""Resume ingestion: role-specific variants, text extracted once for LLM context.

Variants are PDFs named ``resume_{variant}.pdf`` in ``settings.resume_dir`` —
e.g. ``resume_ai_engineer.pdf``. Each application records which variant to send,
so a Data Science role gets the stats-leaning resume and an AI Engineering role
gets the GenAI-leaning one.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pypdf import PdfReader

from ..config import settings


def available_variants() -> list[str]:
    d = Path(settings.resume_dir)
    if not d.exists():
        return []
    return sorted(p.stem.removeprefix("resume_") for p in d.glob("resume_*.pdf"))


def resolve_variant(variant: str | None) -> str:
    """Fall back to the default variant when unset or unknown."""
    if variant and (Path(settings.resume_dir) / f"resume_{variant}.pdf").exists():
        return variant
    return settings.resume_default_variant


def resume_abspath(variant: str | None = None) -> Path:
    v = resolve_variant(variant)
    path = (Path(settings.resume_dir) / f"resume_{v}.pdf").resolve()
    if not path.exists():
        raise FileNotFoundError(
            f"Resume variant '{v}' not found at {path}. "
            f"Available: {available_variants() or 'none'}"
        )
    return path


@lru_cache(maxsize=8)
def resume_text(variant: str | None = None) -> str:
    reader = PdfReader(str(resume_abspath(variant)))
    return "\n".join(page.extract_text() or "" for page in reader.pages).strip()
