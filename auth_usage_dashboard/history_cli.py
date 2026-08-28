# Copyright (c) 2026 PitchAI. All rights reserved.
"""Operator CLI for durable Codex account usage history."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, cast

from .timeseries_reporting import (
    database_status,
    history_rows,
    recent_rows,
    window_summary,
)

if TYPE_CHECKING:
    from .timeseries_types import JsonObject

DEFAULT_DATABASE = Path("/dashboard-data/usage-history.sqlite3")
MAX_HISTORY_HOURS = 24 * 366


def build_parser() -> argparse.ArgumentParser:
    """Create the bounded history-report command tree.

    Returns:
        Parser for the supported read-only history commands.
    """
    parser = argparse.ArgumentParser(
        description="Inspect append-only Codex broker usage-limit history.",
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=Path(os.getenv("AUTH_USAGE_TIMESERIES_DB", str(DEFAULT_DATABASE))),
        help="Persistent SQLite time-series database.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("status", help="Show schema, row counts, and retention span.")

    recent = subparsers.add_parser(
        "recent",
        help="Show newest rows for one exact account label.",
    )
    recent.add_argument("--account", required=True, help="Exact broker account label.")
    recent.add_argument("--limit", type=int, default=20)

    history = subparsers.add_parser(
        "history",
        help="Show bounded rows from the last N hours.",
    )
    history.add_argument("--hours", type=int, default=24)
    history.add_argument("--account", help="Optional exact broker account label.")
    history.add_argument("--limit", type=int, default=10_000)

    summary = subparsers.add_parser("summary", help="Show per-account counts and gaps.")
    summary.add_argument("--hours", type=int, default=24)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run one read-only report and emit JSON.

    Returns:
        Process exit status.
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    payload = _report_payload(args, now=datetime.now(UTC))
    sys.stdout.write(f"{json.dumps(payload, indent=2, sort_keys=True)}\n")
    return 0


def _report_payload(args: argparse.Namespace, *, now: datetime) -> JsonObject | list[JsonObject]:
    command = cast("str", args.command)
    database = cast("Path", args.database)
    if command == "status":
        return database_status(database)
    if command == "recent":
        return recent_rows(
            database,
            account_label=cast("str", args.account),
            limit=cast("int", args.limit),
        )
    if command == "history":
        hours = cast("int", args.hours)
        _validate_hours(hours)
        return history_rows(
            database,
            since=now - timedelta(hours=hours),
            account_label=cast("str | None", args.account),
            limit=cast("int", args.limit),
        )
    if command == "summary":
        hours = cast("int", args.hours)
        _validate_hours(hours)
        return window_summary(database, hours=hours, now=now)
    message = f"unsupported command: {command}"
    raise ValueError(message)


def _validate_hours(hours: int) -> None:
    if not 1 <= hours <= MAX_HISTORY_HOURS:
        message = f"hours must be between 1 and {MAX_HISTORY_HOURS}"
        raise ValueError(message)


if __name__ == "__main__":
    raise SystemExit(main())
