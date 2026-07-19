"""Track API quota exhaustion so the discovery chain can degrade gracefully.

Hunter's free tier is small (~25 lookups/month). Rather than burn a call on every
company only to get a 429, we remember that the quota is dry and skip straight to
the free fallback tiers until the quota resets at the start of next month.

State lives in a small JSON file beside the DB so it survives restarts.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

STATE_FILE = Path(__file__).resolve().parents[3] / "quota_state.json"


def _load() -> dict:
    try:
        return json.loads(STATE_FILE.read_text())
    except (OSError, ValueError):
        return {}


def _save(state: dict) -> None:
    try:
        STATE_FILE.write_text(json.dumps(state, indent=2))
    except OSError:
        pass  # non-fatal: worst case we retry the provider and get a 429


def _next_month_start(today: date) -> date:
    return date(today.year + (today.month == 12), (today.month % 12) + 1, 1)


def mark_exhausted(provider: str) -> None:
    """Record that `provider` is out of quota until the next monthly reset."""
    state = _load()
    state[provider] = {
        "exhausted_until": _next_month_start(date.today()).isoformat(),
        "noticed_at": datetime.now(timezone.utc).isoformat(),
    }
    _save(state)


def is_exhausted(provider: str) -> bool:
    entry = _load().get(provider)
    if not entry:
        return False
    try:
        until = date.fromisoformat(entry["exhausted_until"])
    except (KeyError, ValueError):
        return False
    if date.today() >= until:  # quota reset — clear the flag
        state = _load()
        state.pop(provider, None)
        _save(state)
        return False
    return True


def status() -> dict:
    """Human-readable quota state, surfaced on the dashboard."""
    out = {}
    for provider, entry in _load().items():
        out[provider] = {
            "exhausted": is_exhausted(provider),
            "resets_on": entry.get("exhausted_until"),
        }
    return out


def reset(provider: str | None = None) -> None:
    """Manually clear exhaustion (e.g. after upgrading a plan)."""
    if provider is None:
        _save({})
        return
    state = _load()
    state.pop(provider, None)
    _save(state)
