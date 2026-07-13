"""Resume ingestion: extract text once from the PDF for LLM context."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pypdf import PdfReader

from ..config import settings


def resume_abspath() -> Path:
    return Path(settings.resume_path).resolve()


@lru_cache(maxsize=1)
def resume_text() -> str:
    path = resume_abspath()
    if not path.exists():
        raise FileNotFoundError(
            f"Resume not found at {path}. Place the PDF at {settings.resume_path}."
        )
    reader = PdfReader(str(path))
    return "\n".join(page.extract_text() or "" for page in reader.pages).strip()
