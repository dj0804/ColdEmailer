"""Shared OpenAI client + a chat helper that copes with model quirks.

Newer reasoning models (gpt-5, o3) reject a custom ``temperature`` and use
``max_completion_tokens`` instead of ``max_tokens``. This helper normalizes that
so callers don't have to care which model is configured.
"""

from __future__ import annotations

from openai import OpenAI

from ..config import settings

_client: OpenAI | None = None

# Models that only accept the default temperature (1) and reasoning params.
_REASONING_PREFIXES = ("gpt-5", "o1", "o3", "o4")


def client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=settings.openai_api_key)
    return _client


def _is_reasoning(model: str) -> bool:
    return any(model.startswith(p) for p in _REASONING_PREFIXES)


def chat(
    model: str,
    system: str,
    user: str,
    max_tokens: int = 1200,
    temperature: float | None = None,
    json_mode: bool = False,
) -> str:
    kwargs: dict = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "max_completion_tokens": max_tokens,
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    if not _is_reasoning(model) and temperature is not None:
        kwargs["temperature"] = temperature

    resp = client().chat.completions.create(**kwargs)
    return (resp.choices[0].message.content or "").strip()
