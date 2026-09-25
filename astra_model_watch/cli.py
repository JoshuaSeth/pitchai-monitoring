# Copyright (c) 2026 PitchAI. All rights reserved.
"""Command-line entrypoint for the finite ASTRA watch."""

from __future__ import annotations

import argparse
import re
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import TypedDict, cast

from .audit import AlertState, AuditLog, exclusive_watch_lock
from .notifier import PrivateCommandNotifier
from .types import WatchConfig
from .watch import AstraModelWatch
from .watch_runtime import WatchDependencies

VERSION_PATTERN = re.compile(r"\bcodex-cli\s+([0-9][0-9A-Za-z.+-]*)\b")


class CliArguments(TypedDict):
    """Validated argparse values used by the monitor."""

    accounts_dir: Path
    log_path: Path
    alert_state_path: Path
    notify_command: Path | None
    client_version: str | None
    interval_seconds: float
    duration_seconds: float
    heartbeat_seconds: float
    request_timeout_seconds: float
    once: bool


def _installed_client_version() -> str:
    try:
        result = subprocess.run(
            ["codex", "--version"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10.0,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise RuntimeError("codex_client_version_unavailable") from None
    match = VERSION_PATTERN.search(result.stdout)
    if result.returncode != 0 or match is None:
        raise RuntimeError("codex_client_version_unavailable")
    return match.group(1)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Poll every broker account through the read-only Codex model-catalog GET.",
    )
    _ = parser.add_argument(
        "--accounts-dir",
        type=Path,
        default=Path("/srv/auth-token-server/data/accounts"),
    )
    _ = parser.add_argument("--log-path", type=Path, required=True)
    _ = parser.add_argument("--alert-state-path", type=Path, required=True)
    _ = parser.add_argument("--notify-command", type=Path)
    _ = parser.add_argument("--client-version")
    _ = parser.add_argument("--interval-seconds", type=float, default=300.0)
    _ = parser.add_argument("--duration-seconds", type=float, default=7200.0)
    _ = parser.add_argument("--heartbeat-seconds", type=float, default=60.0)
    _ = parser.add_argument("--request-timeout-seconds", type=float, default=20.0)
    _ = parser.add_argument(
        "--once",
        action="store_true",
        help="Run one safe validation cycle; this is not accepted as the two-hour proof.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Validate CLI invariants, execute the finite watch, and return its status."""
    raw_arguments = cast("object", vars(_parser().parse_args(argv)))
    args = cast("CliArguments", raw_arguments)
    duration_seconds = 0.0 if args["once"] else args["duration_seconds"]
    if not args["once"] and args["interval_seconds"] != 300.0:
        raise SystemExit("the monitored run requires exactly a 300-second interval")
    if not args["once"] and duration_seconds < 7200.0:
        raise SystemExit("the monitored run requires at least 7200 seconds")
    if args["notify_command"] is None:
        raise SystemExit(
            "every live catalog run requires a requester-private notification command",
        )
    client_version = args["client_version"] or _installed_client_version()
    notifier = PrivateCommandNotifier((str(args["notify_command"]),))
    config = WatchConfig(
        accounts_dir=args["accounts_dir"],
        client_version=client_version,
        interval_seconds=args["interval_seconds"],
        duration_seconds=duration_seconds,
        heartbeat_seconds=args["heartbeat_seconds"],
        request_timeout_seconds=args["request_timeout_seconds"],
    )
    with exclusive_watch_lock(args["alert_state_path"]):
        watch = AstraModelWatch(
            config=config,
            audit=AuditLog(args["log_path"]),
            alert_state=AlertState(args["alert_state_path"]),
            dependencies=WatchDependencies(notifier=notifier),
        )
        summary = watch.run()
    if args["once"]:
        return 0 if summary.error_count == 0 else 1
    return 0 if summary.valid_window else 1
