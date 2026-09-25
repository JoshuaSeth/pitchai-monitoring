# Copyright (c) 2026 PitchAI. All rights reserved.
"""Expose the authentication reset guardian command-line interface."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from .audit import AuditStore
from .cli_arguments import DEFAULT_AUDIT_DB, CliArguments
from .cli_lock import bounded_lock_wait, exclusive_lock
from .clients import BrokerProviderConfig, BrokerProviderSource, SimulationSource
from .guardian import CommandNotifier, Guardian
from .model_values import utc_now
from .models import parse_timestamp

if TYPE_CHECKING:
    from datetime import datetime

    from .json_contract import JsonValue

__all__ = ["build_parser", "exclusive_lock", "main"]


def _write_json(value: JsonValue) -> None:
    """Write one JSON value to standard output."""
    _ = sys.stdout.write(json.dumps(value, indent=2, sort_keys=True))
    _ = sys.stdout.write("\n")


def build_parser() -> argparse.ArgumentParser:
    """Build build parser.

    Returns:
        The resulting value.

    """
    parser = argparse.ArgumentParser(
        description="Protect broker-managed Codex reset credits before they expire.",
    )
    _ = parser.add_argument(
        "--audit-db",
        type=Path,
        default=Path(os.getenv("AUTH_RESET_GUARDIAN_AUDIT_DB", str(DEFAULT_AUDIT_DB))),
        help="Persistent SQLite audit database.",
    )
    _ = parser.add_argument(
        "--lock-wait-seconds",
        type=bounded_lock_wait,
        default=0.0,
        help="Wait this long for another run to release the audit lock (maximum 600 seconds).",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run", help="Scan every broker account once.")
    _ = run.add_argument(
        "--dry-run",
        action="store_true",
        help="Read and recheck, but never POST a consume request.",
    )
    _ = run.add_argument(
        "--simulate",
        type=Path,
        help="Use a local fixture instead of broker/provider network calls.",
    )
    _ = run.add_argument("--now", help="Simulation-only RFC3339 clock override.")
    _ = run.add_argument(
        "--no-notify",
        action="store_true",
        help="Suppress configured notifications for this run.",
    )
    _ = run.add_argument(
        "--require-notifier",
        action="store_true",
        help="Fail before a live run when the notification command is not configured.",
    )

    manual = subparsers.add_parser(
        "manual-redeem",
        help="Freshly recheck and redeem one exact account/expiry through the guarded path.",
    )
    _ = manual.add_argument("--account-label", required=True)
    _ = manual.add_argument("--expires-at", required=True)
    _ = manual.add_argument("--reason", required=True)
    _ = manual.add_argument("--dry-run", action="store_true")
    _ = manual.add_argument("--no-notify", action="store_true")

    _ = subparsers.add_parser(
        "status",
        help="Print the latest durable run/account/attempt status.",
    )
    events = subparsers.add_parser("events", help="Print recent durable audit events.")
    _ = events.add_argument("--limit", type=int, default=100)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run main.

    Returns:
        The computed value.

    Raises:
        RuntimeError: If the operation cannot satisfy its runtime contract.

    """
    parser = build_parser()
    args = parser.parse_args(argv, namespace=CliArguments())
    if args.command == "status":
        with AuditStore(args.audit_db) as audit:
            _write_json(audit.latest_status())
        return 0
    if args.command == "events":
        if not args.events_limit_is_valid():
            parser.error("--limit must be between 1 and 10000")
        with AuditStore(args.audit_db) as audit:
            events: list[JsonValue] = []
            events.extend(audit.recent_events(limit=args.limit))
            _write_json(events)
        return 0

    if not args.is_locked_command():
        msg = f"unsupported command: {args.command}"
        raise RuntimeError(msg)
    with exclusive_lock(args.audit_db, wait_seconds=args.lock_wait_seconds):
        if args.command == "run":
            return _run_command(parser, args)
        if args.command == "manual-redeem":
            return _manual_command(parser, args)
    msg = f"unsupported command: {args.command}"
    raise RuntimeError(msg)


def _run_command(parser: argparse.ArgumentParser, args: CliArguments) -> int:
    override_now: datetime | None = None
    if args.now:
        if args.simulate is None:
            parser.error("--now is permitted only with --simulate")
        override_now = parse_timestamp(args.now, field_name="now")
    clock = (lambda: override_now) if override_now is not None else utc_now
    if args.simulate is not None:
        source = SimulationSource.from_path(
            args.simulate.expanduser().resolve(),
            clock=clock,
        )
        mode = "simulation_dry_run" if args.dry_run else "simulation"
    else:
        source = _live_source(parser)
        mode = "dry_run" if args.dry_run else "live"
    notifier = _notifier(
        parser,
        disabled=bool(args.no_notify or args.simulate is not None or args.dry_run),
        required=bool(
            args.require_notifier and args.simulate is None and not args.dry_run,
        ),
    )
    with AuditStore(args.audit_db) as audit:
        notification_callback = notifier.notify if notifier is not None else None
        summary = Guardian(
            source=source,
            audit=audit,
            notifier=notification_callback,
            clock=clock,
        ).run(
            mode=mode,
            dry_run=bool(args.dry_run),
        )
    _write_json(summary.serialized())
    if summary.status == "failed" or (args.require_notifier and summary.notification_error_count):
        return 1
    return 0


def _manual_command(parser: argparse.ArgumentParser, args: CliArguments) -> int:
    source = _live_source(parser)
    notifier = _notifier(
        parser,
        disabled=bool(args.no_notify or args.dry_run),
        required=False,
    )
    expires_at = parse_timestamp(args.expires_at, field_name="expires-at")
    reason = args.reason.strip()
    if not reason:
        parser.error("--reason must not be empty")
    with AuditStore(args.audit_db) as audit:
        notification_callback = notifier.notify if notifier is not None else None
        summary = Guardian(
            source=source,
            audit=audit,
            notifier=notification_callback,
        ).manual_redeem(
            account_label=args.account_label,
            expires_at=expires_at,
            reason=reason,
            dry_run=bool(args.dry_run),
        )
    _write_json(summary.serialized())
    return 1 if summary.error_count else 0


def _live_source(parser: argparse.ArgumentParser) -> BrokerProviderSource:
    token = (os.getenv("AUTH_RESET_GUARDIAN_BROKER_ADMIN_TOKEN") or "").strip()
    if not token:
        parser.error(
            "AUTH_RESET_GUARDIAN_BROKER_ADMIN_TOKEN is required for live broker access",
        )
    broker_url = os.getenv(
        "AUTH_RESET_GUARDIAN_BROKER_URL",
        "http://127.0.0.1:38188",
    ).strip()
    provider_url = os.getenv(
        "AUTH_RESET_GUARDIAN_PROVIDER_BASE_URL",
        "https://chatgpt.com/backend-api",
    ).strip()
    timeout = float(os.getenv("AUTH_RESET_GUARDIAN_HTTP_TIMEOUT_SECONDS", "20"))
    return BrokerProviderSource(
        BrokerProviderConfig(
            broker_url=broker_url,
            broker_admin_token=token,
            provider_base_url=provider_url,
            timeout_seconds=timeout,
        ),
    )


def _notifier(
    parser: argparse.ArgumentParser,
    *,
    disabled: bool,
    required: bool,
) -> CommandNotifier | None:
    if disabled:
        return None
    raw = (os.getenv("AUTH_RESET_GUARDIAN_NOTIFICATION_COMMAND") or "").strip()
    if not raw:
        if required:
            parser.error("AUTH_RESET_GUARDIAN_NOTIFICATION_COMMAND is required")
        return None
    command = shlex.split(raw)
    if not command:
        parser.error("AUTH_RESET_GUARDIAN_NOTIFICATION_COMMAND is empty after parsing")
    return CommandNotifier(command)
