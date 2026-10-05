"""Shared OpenAI client + a chat helper that copes with model quirks.

Newer reasoning models (gpt-5, o3) reject a custom ``temperature`` and use
``max_completion_tokens`` instead of ``max_tokens``. This helper normalizes that
so callers don't have to care which model is configured.
"""

from __future__ import annotations

import json
import threading
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from openai import OpenAI

from ..config import settings

_client: OpenAI | None = None

# Models that only accept the default temperature (1) and reasoning params.
_REASONING_PREFIXES = ("gpt-5", "o1", "o3", "o4")


# USD per 1M tokens: (input, cached input, output). Used only for the budget
# ledger; an unknown model is priced as gpt-5 so the cap errs on the safe side.
PRICES: dict[str, tuple[float, float, float]] = {
    "gpt-5": (1.25, 0.125, 10.0),
    "gpt-5-mini": (0.25, 0.025, 2.0),
    "gpt-5-nano": (0.05, 0.005, 0.4),
    "gpt-4o": (2.50, 1.25, 10.0),
    "gpt-4o-mini": (0.15, 0.075, 0.60),
}
LEDGER_FILE = Path(__file__).resolve().parents[2] / "llm_spend.json"
_ledger_lock = threading.Lock()


class BudgetExceeded(RuntimeError):
    """The configured OpenAI budget for the current window is used up."""


def _price(model: str) -> tuple[float, float, float]:
    # Longest matching prefix, so dated snapshots ('gpt-5-mini-2025-08-07') work.
    for name in sorted(PRICES, key=len, reverse=True):
        if model.startswith(name):
            return PRICES[name]
    return PRICES["gpt-5"]


def _window_start(today: date) -> date:
    start = date.fromisoformat(settings.llm_budget_start)
    days = max(settings.llm_budget_days, 1)
    while today >= start + timedelta(days=days):
        start += timedelta(days=days)
    return start


def spend() -> dict:
    """Current budget window: start, spent, cap, calls."""
    start = _window_start(datetime.now(timezone.utc).date()).isoformat()
    try:
        data = json.loads(LEDGER_FILE.read_text())
    except (OSError, ValueError):
        data = {}
    if data.get("window_start") != start:
        data = {"window_start": start, "spent_usd": 0.0, "calls": 0}
    data["budget_usd"] = settings.llm_budget_usd
    return data


def _record(model: str, usage) -> None:
    if usage is None:
        return
    cached = getattr(getattr(usage, "prompt_tokens_details", None), "cached_tokens", 0) or 0
    p_in, p_cached, p_out = _price(model)
    cost = (
        (usage.prompt_tokens - cached) * p_in
        + cached * p_cached
        + usage.completion_tokens * p_out
    ) / 1_000_000
    with _ledger_lock:
        data = spend()
        data["spent_usd"] = round(data["spent_usd"] + cost, 6)
        data["calls"] += 1
        try:
            LEDGER_FILE.write_text(json.dumps(data))
        except OSError:
            pass


def _check_budget() -> None:
    cap = settings.llm_budget_usd
    if cap and spend()["spent_usd"] >= cap:
        raise BudgetExceeded(
            f"llm_budget_exceeded: OpenAI budget of ${cap:.2f} for this window is used up"
        )


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
    reasoning_effort: str | None = None,
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
    if _is_reasoning(model):
        # Reasoning models reject custom temperature; cap reasoning spend so the
        # token budget goes to the answer, not hidden reasoning.
        if reasoning_effort is not None:
            kwargs["reasoning_effort"] = reasoning_effort
    elif temperature is not None:
        kwargs["temperature"] = temperature

    _check_budget()
    resp = client().chat.completions.create(**kwargs)
    _record(model, getattr(resp, "usage", None))
    return (resp.choices[0].message.content or "").strip()
