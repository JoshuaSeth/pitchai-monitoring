# Copyright (c) 2026 PitchAI. All rights reserved.
"""Redacted DeepSeek API balance for the dashboard (host exporter).

Reads the DeepSeek owners' private ``api-key`` files, asks DeepSeek's read-only
``/user/balance`` endpoint once per distinct key, and writes the remaining
prepaid balance only: keys never leave this process. Standard library only
(Python 3.10); runs every five minutes on a host that holds an owner key.
"""

from __future__ import annotations

import argparse
import json
import stat
import sys
import time
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING, cast

from .bearer_json_gateway import fetch_body

if TYPE_CHECKING:
    from collections.abc import Sequence

    from .timeseries_types import JsonObject, JsonValue

OWNERS_ROOT = Path("/var/lib/pitchai-cli-new/deepseek-owners")
BALANCE_URL = "https://api.deepseek.com/user/balance"
OUTPUT_FILE = Path("/srv/codex-usage-dashboard/deepseek-balance.json")
PREFERRED_CURRENCY = "USD"
MAX_KEY_BYTES = 512
_PRIVATE_MODE = 0o600
_AMOUNTS = ("total_balance", "granted_balance", "topped_up_balance")


def owner_keys(root: Path) -> list[str]:
    """Return each distinct private owner credential once (owners usually share one account)."""
    keys: list[str] = []
    for path in sorted(root.glob("*/api-key")):
        text = ""
        with suppress(OSError, UnicodeDecodeError):
            info = path.lstat()
            if stat.S_ISREG(info.st_mode) and stat.S_IMODE(info.st_mode) == _PRIVATE_MODE:
                text = path.read_bytes()[:MAX_KEY_BYTES].decode("ascii").strip()
        if text and text not in keys:
            keys.append(text)
    return keys


def _amount(value: JsonValue) -> float | None:
    with suppress(TypeError, ValueError):
        if isinstance(value, (str, int, float)) and not isinstance(value, bool):
            return float(value) + 0.0
    return None


def balance_row(document: JsonValue) -> JsonObject:
    """Return the balance in the preferred currency from one ``/user/balance`` document."""
    infos = document.get("balance_infos") if isinstance(document, dict) else None
    rows = [info for info in infos if isinstance(info, dict)] if isinstance(infos, list) else []
    preferred = [info for info in rows if info.get("currency") == PREFERRED_CURRENCY]
    chosen = (preferred or rows or [{}])[0]
    row: JsonObject = {
        "is_available": isinstance(document, dict) and document.get("is_available") is True,
        "currency": chosen.get("currency") if isinstance(chosen.get("currency"), str) else None,
        "error": None if rows else "balance_unavailable",
    }
    for name in _AMOUNTS:
        row[name] = _amount(chosen.get(name))
    return row


def collect(root: Path, *, now: float) -> JsonObject:
    """Return the redacted balance snapshot: per-key rows plus their sum, never a key."""
    rows: list[JsonObject] = []
    for key in owner_keys(root):
        document: JsonValue = None
        with suppress(ValueError):
            document = cast("JsonValue", json.loads(fetch_body(BALANCE_URL, key) or b"null"))
        rows.append(balance_row(document))
    totals: JsonObject = {}
    for name in _AMOUNTS:
        amounts = [row.get(name) for row in rows]
        known = [amount for amount in amounts if isinstance(amount, float)]
        totals[name] = sum(known) if known else None
    return {
        "schema_version": 1,
        "generated_at": now,
        "keys": len(rows),
        "is_available": any(row.get("is_available") is True for row in rows),
        "currency": PREFERRED_CURRENCY,
        **totals,
        "accounts": cast("list[JsonValue]", rows),
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Write the redacted DeepSeek balance snapshot.

    Returns:
        Process exit status.
    """
    parser = argparse.ArgumentParser(description="Export the redacted DeepSeek API balance for the dashboard")
    parser.add_argument("--owners", type=Path, default=OWNERS_ROOT)
    parser.add_argument("--output", type=Path, default=OUTPUT_FILE)
    arguments = parser.parse_args(list(argv) if argv is not None else None)
    snapshot = collect(cast("Path", arguments.owners), now=time.time())
    output = cast("Path", arguments.output)
    output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".partial")
    temporary.write_text(json.dumps(snapshot, allow_nan=False), encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(output)
    sys.stdout.write(json.dumps({"keys": snapshot["keys"], "total_balance": snapshot["total_balance"]}) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
