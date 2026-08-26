from __future__ import annotations

import argparse
import fcntl
import json
import math
import os
import shlex
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator

from .audit import AuditStore
from .clients import BrokerProviderSource, SimulationSource
from .guardian import CommandNotifier, Guardian
from .models import parse_timestamp, utc_now


DEFAULT_AUDIT_DB = Path("/var/lib/pitchai-auth-reset-guardian/audit.sqlite3")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Protect broker-managed Codex reset credits before they expire."
    )
    parser.add_argument(
        "--audit-db",
        type=Path,
        default=Path(os.getenv("AUTH_RESET_GUARDIAN_AUDIT_DB", str(DEFAULT_AUDIT_DB))),
        help="Persistent SQLite audit database.",
    )
    parser.add_argument(
        "--lock-wait-seconds",
        type=_bounded_lock_wait,
        default=0.0,
        help="Wait this long for another run to release the audit lock (maximum 600 seconds).",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run", help="Scan every broker account once.")
    run.add_argument("--dry-run", action="store_true", help="Read and recheck, but never POST a consume request.")
    run.add_argument("--simulate", type=Path, help="Use a local fixture instead of broker/provider network calls.")
    run.add_argument("--now", help="Simulation-only RFC3339 clock override.")
    run.add_argument("--no-notify", action="store_true", help="Suppress configured notifications for this run.")
    run.add_argument(
        "--require-notifier",
        action="store_true",
        help="Fail before a live run when the notification command is not configured.",
    )

    manual = subparsers.add_parser(
        "manual-redeem",
        help="Freshly recheck and redeem one exact account/expiry through the guarded path.",
    )
    manual.add_argument("--account-label", required=True)
    manual.add_argument("--expires-at", required=True)
    manual.add_argument("--reason", required=True)
    manual.add_argument("--dry-run", action="store_true")
    manual.add_argument("--no-notify", action="store_true")

    subparsers.add_parser("status", help="Print the latest durable run/account/attempt status.")
    events = subparsers.add_parser("events", help="Print recent durable audit events.")
    events.add_argument("--limit", type=int, default=100)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "status":
        with AuditStore(args.audit_db) as audit:
            print(json.dumps(audit.latest_status(), indent=2, sort_keys=True))
        return 0
    if args.command == "events":
        if args.limit < 1 or args.limit > 10_000:
            parser.error("--limit must be between 1 and 10000")
        with AuditStore(args.audit_db) as audit:
            print(json.dumps(audit.recent_events(limit=args.limit), indent=2, sort_keys=True))
        return 0

    with _exclusive_lock(args.audit_db, wait_seconds=args.lock_wait_seconds):
        if args.command == "run":
            return _run_command(parser, args)
        if args.command == "manual-redeem":
            return _manual_command(parser, args)
    parser.error(f"unsupported command: {args.command}")
    return 2


def _run_command(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    override_now: datetime | None = None
    if args.now:
        if args.simulate is None:
            parser.error("--now is permitted only with --simulate")
        override_now = parse_timestamp(args.now, field_name="now")
    clock = (lambda: override_now) if override_now is not None else utc_now
    if args.simulate is not None:
        source = SimulationSource.from_path(args.simulate.expanduser().resolve(), clock=clock)
        mode = "simulation_dry_run" if args.dry_run else "simulation"
    else:
        source = _live_source(parser)
        mode = "dry_run" if args.dry_run else "live"
    notifier = _notifier(
        parser,
        disabled=bool(args.no_notify or args.simulate is not None or args.dry_run),
        required=bool(args.require_notifier and args.simulate is None and not args.dry_run),
    )
    with AuditStore(args.audit_db) as audit:
        summary = Guardian(source=source, audit=audit, notifier=notifier, clock=clock).run(
            mode=mode,
            dry_run=bool(args.dry_run),
        )
    print(json.dumps(summary.serialized(), indent=2, sort_keys=True))
    if summary.status == "failed" or (args.require_notifier and summary.notification_error_count):
        return 1
    return 0


def _manual_command(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    source = _live_source(parser)
    notifier = _notifier(parser, disabled=bool(args.no_notify or args.dry_run), required=False)
    expires_at = parse_timestamp(args.expires_at, field_name="expires-at")
    reason = args.reason.strip()
    if not reason:
        parser.error("--reason must not be empty")
    with AuditStore(args.audit_db) as audit:
        summary = Guardian(source=source, audit=audit, notifier=notifier).manual_redeem(
            account_label=args.account_label,
            expires_at=expires_at,
            reason=reason,
            dry_run=bool(args.dry_run),
        )
    print(json.dumps(summary.serialized(), indent=2, sort_keys=True))
    return 1 if summary.error_count else 0


def _live_source(parser: argparse.ArgumentParser) -> BrokerProviderSource:
    token = (os.getenv("AUTH_RESET_GUARDIAN_BROKER_ADMIN_TOKEN") or "").strip()
    if not token:
        parser.error("AUTH_RESET_GUARDIAN_BROKER_ADMIN_TOKEN is required for live broker access")
    broker_url = os.getenv("AUTH_RESET_GUARDIAN_BROKER_URL", "http://127.0.0.1:38188").strip()
    provider_url = os.getenv(
        "AUTH_RESET_GUARDIAN_PROVIDER_BASE_URL", "https://chatgpt.com/backend-api"
    ).strip()
    timeout = float(os.getenv("AUTH_RESET_GUARDIAN_HTTP_TIMEOUT_SECONDS", "20"))
    return BrokerProviderSource(
        broker_url=broker_url,
        broker_admin_token=token,
        provider_base_url=provider_url,
        timeout_seconds=timeout,
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
    preflight_raw = (
        os.getenv("AUTH_RESET_GUARDIAN_NOTIFICATION_PREFLIGHT_COMMAND") or ""
    ).strip()
    if required and not preflight_raw:
        parser.error(
            "AUTH_RESET_GUARDIAN_NOTIFICATION_PREFLIGHT_COMMAND is required"
        )
    preflight_command = shlex.split(preflight_raw) if preflight_raw else None
    if preflight_raw and not preflight_command:
        parser.error(
            "AUTH_RESET_GUARDIAN_NOTIFICATION_PREFLIGHT_COMMAND is empty after parsing"
        )
    return CommandNotifier(command, preflight_command=preflight_command)


def _bounded_lock_wait(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("lock wait must be a number") from exc
    if not math.isfinite(parsed) or parsed < 0 or parsed > 600:
        raise argparse.ArgumentTypeError("lock wait must be between 0 and 600 seconds")
    return parsed


@contextmanager
def _exclusive_lock(audit_path: Path, *, wait_seconds: float = 0.0) -> Iterator[None]:
    resolved = audit_path.expanduser().resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock_path = resolved.with_suffix(resolved.suffix + ".lock")
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    deadline = time.monotonic() + wait_seconds
    try:
        while True:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    if wait_seconds:
                        raise SystemExit(
                            "another reset guardian run held the audit lock beyond "
                            f"{wait_seconds:g} seconds"
                        ) from None
                    raise SystemExit("another reset guardian run holds the audit lock") from None
                time.sleep(min(0.1, remaining))
        yield
    finally:
        os.close(descriptor)
