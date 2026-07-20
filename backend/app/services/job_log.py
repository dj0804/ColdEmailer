"""Record when each scheduled job last ran, and what it did.

An unattended pipeline needs a way to answer "did it actually run today?".
APScheduler keeps no history, so we persist the last outcome per job to a small
JSON file beside the DB and surface it on the dashboard.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

STATE_FILE = Path(__file__).resolve().parents[2] / "job_runs.json"
MAX_HISTORY = 20


def _load() -> dict:
    try:
        return json.loads(STATE_FILE.read_text())
    except (OSError, ValueError):
        return {}


def _save(state: dict) -> None:
    try:
        STATE_FILE.write_text(json.dumps(state, indent=2, default=str))
    except OSError:
        pass  # never let bookkeeping break a job


def record(job_id: str, result: dict | None = None, error: str | None = None) -> None:
    state = _load()
    entry = state.setdefault(job_id, {"history": []})
    run = {
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "ok": error is None,
    }
    if error:
        run["error"] = error[:300]
    elif result is not None:
        # Keep the summary small — counts, not full payloads.
        run["result"] = {
            k: v for k, v in result.items() if isinstance(v, (int, float, str, bool))
        }
    entry["last"] = run
    entry["history"] = ([run] + entry.get("history", []))[:MAX_HISTORY]
    _save(state)


def status() -> dict:
    return _load()
