# Copyright (c) 2026 PitchAI. All rights reserved.
"""Rolling usage-percentage samples for the Claude and OpenCode account pools.

Host exporters append one sample per fresh quota reading so the dashboard can
measure a reset-aware burn rate exactly as it does for the Codex broker pool.
Samples use the broker sample shape (``at`` plus per-label
``weekly_used_percent``/``weekly_reset_at``), are kept for eight days and are
written atomically with private permissions. Standard library only (Python 3.10).
"""

from __future__ import annotations

import argparse
import calendar
import json
import sys
import time
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Sequence

    from .timeseries_types import JsonObject, JsonValue

RETENTION_SECONDS = 8 * 86_400
MIN_INTERVAL_SECONDS = 240.0
MAX_FILE_BYTES = 16 * 1024 * 1024
CLAUDE_SAMPLES_FILE = Path("/srv/codex-usage-dashboard/claude-usage-samples.json")
CLAUDE_SNAPSHOT_FILE = Path("/srv/codex-usage-dashboard/claude-accounts.json")
_WINDOW_FIELDS = (("seven_day", "weekly"), ("five_hour", "five"))


def iso_epoch(epoch: float) -> str:
    """Return one epoch second as a UTC ISO-8601 timestamp with a ``Z`` suffix."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch))


def read_samples(path: Path) -> list[JsonObject]:
    """Return the retained samples, or none when the file is absent or invalid."""
    document: JsonValue = None
    with suppress(OSError, ValueError):
        if path.stat().st_size <= MAX_FILE_BYTES:
            document = cast("JsonValue", json.loads(path.read_text(encoding="utf-8")))
    samples = document.get("samples") if isinstance(document, dict) else None
    return [sample for sample in samples if isinstance(sample, dict)] if isinstance(samples, list) else []


def append_sample(path: Path, sample: JsonObject, *, now: float) -> bool:
    """Append ``sample`` when it is at least four minutes newer than the last one.

    Returns:
        Whether the sample was written.
    """
    samples = read_samples(path)
    cutoff = iso_epoch(now - RETENTION_SECONDS)
    kept = [item for item in samples if str(item.get("at", "")) >= cutoff]
    last_at = str(kept[-1].get("at", "")) if kept else ""
    last_epoch = float(calendar.timegm(time.strptime(last_at, "%Y-%m-%dT%H:%M:%SZ"))) if last_at else 0.0
    if last_at and str(sample.get("at", "")) <= iso_epoch(last_epoch + MIN_INTERVAL_SECONDS):
        return False
    kept.append(sample)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".partial")
    temporary.write_text(json.dumps({"schema_version": 1, "samples": kept}, allow_nan=False), encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(path)
    return True


def _number(value: JsonValue) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def claude_sample(snapshot: JsonObject) -> JsonObject | None:
    """Return one sample from the Claude exporter snapshot, keyed by account email.

    Returns:
        The sample, or nothing when no account carries a quota reading.
    """
    rows = snapshot.get("accounts")
    accounts: JsonObject = {}
    observed: list[float] = []
    for raw in rows if isinstance(rows, list) else []:
        row = raw if isinstance(raw, dict) else {}
        label, seen, windows = row.get("email"), _number(row.get("quota_observed_at")), row.get("windows")
        if not isinstance(label, str) or seen is None or not isinstance(windows, dict):
            continue
        entry: JsonObject = {}
        for window_key, prefix in _WINDOW_FIELDS:
            window = windows.get(window_key)
            used = _number(window.get("used_percent")) if isinstance(window, dict) else None
            reset = _number(window.get("resets_at")) if isinstance(window, dict) else None
            if used is not None and reset is not None:
                entry[f"{prefix}_used_percent"] = used
                entry[f"{prefix}_reset_at"] = iso_epoch(reset)
        if entry:
            accounts[label] = entry
            observed.append(seen)
    return {"at": iso_epoch(max(observed)), "accounts": accounts} if observed else None


def main(argv: Sequence[str] | None = None) -> int:
    """Append one Claude sample from the exporter snapshot (run after the exporter).

    Returns:
        Process exit status.
    """
    parser = argparse.ArgumentParser(description="Append one Claude quota sample for burn-factor history")
    parser.add_argument("--claude", type=Path, default=CLAUDE_SNAPSHOT_FILE)
    parser.add_argument("--samples", type=Path, default=CLAUDE_SAMPLES_FILE)
    arguments = parser.parse_args(list(argv) if argv is not None else None)
    snapshot_path = cast("Path", arguments.claude)
    document: JsonValue = None
    with suppress(OSError, ValueError):
        document = cast("JsonValue", json.loads(snapshot_path.read_text(encoding="utf-8")))
    sample = claude_sample(document) if isinstance(document, dict) else None
    written = sample is not None and append_sample(cast("Path", arguments.samples), sample, now=time.time())
    sys.stdout.write(json.dumps({"sample_written": written}) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
