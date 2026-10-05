# Copyright (c) 2026 PitchAI. All rights reserved.
"""Redacted OpenCode Go subscription-pool usage for the dashboard (host exporter).

Reads the isolated bridge's rotating keyring, asks OpenCode's read-only plan
usage endpoint (rolling 5-hour, weekly and monthly windows) once per
subscription, and writes labels and numbers only: API keys never leave this
process. Each run also appends one burn-history sample. Standard library only
(Python 3.10); runs every five minutes on the host that holds the keyring.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING, cast

from .bearer_json_gateway import BROWSER_AGENT, fetch_body
from .pool_samples import append_sample, iso_epoch

if TYPE_CHECKING:
    from collections.abc import Sequence

    from .timeseries_types import JsonObject, JsonValue

KEYRING_FILE = Path("/var/lib/pitchai-opencode-isolated/keyring.json")
KEYRING_STATE_FILE = Path("/var/lib/pitchai-opencode-isolated/keyring-state.json")
USAGE_URL = "https://opencode.ai/zen/go/v1/usage"
OUTPUT_FILE = Path("/srv/codex-usage-dashboard/opencode-accounts.json")
SAMPLES_FILE = Path("/srv/codex-usage-dashboard/opencode-usage-samples.json")
WINDOWS = ("rolling", "weekly", "monthly")
SAMPLE_PREFIXES = {"rolling": "five", "weekly": "weekly", "monthly": "monthly"}
AUTH_FAILURES = frozenset({401, 403})
FULL_PERCENT, MAX_RESET_TEXT = 100, 40


def _load(path: Path) -> JsonValue:
    document: JsonValue = None
    with suppress(OSError, ValueError):
        document = cast("JsonValue", json.loads(path.read_text(encoding="utf-8")))
    return document


def pool_entries(keyring: JsonValue) -> list[tuple[str, str]]:
    """Return ``(label, api_key)`` pairs from any supported keyring shape.

    Returns:
        Entries in pool order; unlabelled keys get a positional label, never the key.
    """
    raw = keyring.get("keys") if isinstance(keyring, dict) else keyring
    entries: list[tuple[str, str]] = []
    for position, item in enumerate(raw if isinstance(raw, list) else []):
        key = item.get("api_key") if isinstance(item, dict) else item
        label = item.get("label") if isinstance(item, dict) else None
        if isinstance(key, str) and key:
            entries.append((label if isinstance(label, str) and label else f"subscription-{position + 1}", key))
    return entries


def fetch_usage(api_key: str) -> JsonObject | None:
    """Return the ``usage`` object of the plan usage endpoint, or nothing on any failure."""
    document: JsonValue = None
    with suppress(ValueError):
        document = cast("JsonValue", json.loads(fetch_body(USAGE_URL, api_key, user_agent=BROWSER_AGENT) or b"null"))
    usage = document.get("usage") if isinstance(document, dict) else None
    return usage if isinstance(usage, dict) else None


def _window(raw: JsonValue) -> JsonObject | None:
    window = raw if isinstance(raw, dict) else {}
    percent, resets, status = window.get("percent"), window.get("resetsAt"), window.get("status")
    if isinstance(percent, bool) or not isinstance(percent, (int, float)) or not 0 <= percent <= FULL_PERCENT:
        return None
    reset_text = resets if isinstance(resets, str) and len(resets) <= MAX_RESET_TEXT else None
    return {
        "used_percent": float(percent),
        "resets_at": reset_text,
        "status": status if isinstance(status, str) else None,
    }


def account_row(label: str, usage: JsonObject | None, state: JsonObject) -> JsonObject:
    """Return one redacted account row from its usage and the bridge's rotation state."""
    windows: JsonObject = {}
    for name in WINDOWS:
        parsed = _window(usage.get(name)) if usage is not None else None
        if parsed is not None:
            windows[name] = parsed
    last_status = state.get("last_status")
    cooldown = state.get("cooldown_until")
    return {
        "label": label,
        "windows": windows,
        "auth_valid": last_status not in AUTH_FAILURES,
        "last_status": last_status if isinstance(last_status, int) else None,
        "cooldown_until": float(cooldown)
        if isinstance(cooldown, (int, float)) and not isinstance(cooldown, bool)
        else None,
        "error": None if usage is not None else "usage_unavailable",
    }


def sample_entry(row: JsonObject) -> JsonObject:
    """Return the burn-history fields of one account row (percent and reset per window)."""
    entry: JsonObject = {}
    windows = row.get("windows")
    for name, prefix in SAMPLE_PREFIXES.items():
        window = windows.get(name) if isinstance(windows, dict) else None
        if isinstance(window, dict) and window.get("resets_at") is not None:
            entry[f"{prefix}_used_percent"] = window.get("used_percent")
            entry[f"{prefix}_reset_at"] = window.get("resets_at")
    return entry


def collect(keyring: Path, state_file: Path, *, now: float) -> JsonObject:
    """Return the redacted pool snapshot (labels, windows, rotation state; never keys)."""
    state = _load(state_file)
    rows: list[JsonValue] = []
    for label, key in pool_entries(_load(keyring)):
        key_state = state.get(key) if isinstance(state, dict) else None
        rows.append(account_row(label, fetch_usage(key), key_state if isinstance(key_state, dict) else {}))
    return {"schema_version": 1, "generated_at": now, "accounts": rows}


def main(argv: Sequence[str] | None = None) -> int:
    """Write the redacted OpenCode pool snapshot and append one burn sample.

    Returns:
        Process exit status.
    """
    parser = argparse.ArgumentParser(description="Export redacted OpenCode Go pool usage for the dashboard")
    parser.add_argument("--keyring", type=Path, default=KEYRING_FILE)
    parser.add_argument("--state", type=Path, default=KEYRING_STATE_FILE)
    parser.add_argument("--output", type=Path, default=OUTPUT_FILE)
    parser.add_argument("--samples", type=Path, default=SAMPLES_FILE)
    arguments = parser.parse_args(list(argv) if argv is not None else None)
    now = time.time()
    snapshot = collect(cast("Path", arguments.keyring), cast("Path", arguments.state), now=now)
    output = cast("Path", arguments.output)
    output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".partial")
    temporary.write_text(json.dumps(snapshot, allow_nan=False), encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(output)
    rows = snapshot.get("accounts")
    accounts: JsonObject = {}
    for row in rows if isinstance(rows, list) else []:
        if isinstance(row, dict) and isinstance(row.get("label"), str):
            accounts[str(row["label"])] = sample_entry(row)
    sample: JsonObject = {"at": iso_epoch(now), "accounts": accounts}
    written = append_sample(cast("Path", arguments.samples), sample, now=now)
    sys.stdout.write(json.dumps({"accounts": len(accounts), "sample_written": written}) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
