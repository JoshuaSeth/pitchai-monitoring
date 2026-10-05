# Copyright (c) 2026 PitchAI. All rights reserved.
"""Command line for the token ledger exporter (``python3 -m token_ledger``)."""

from __future__ import annotations

import argparse
import fcntl
import json
import sys
from pathlib import Path

from .collect import collect
from .deliver import deliver
from .fleet_store import DEFAULT_FLEET_DB, connect_fleet, ingest
from .node_store import DEFAULT_STATE, NodeStore
from .sources import DEFAULT_CONFIG, load_config

_VERSION_FILE = Path(__file__).resolve().parent / "VERSION"
_LOCK_SUFFIX = ".lock"


def _version() -> str:
    try:
        return _VERSION_FILE.read_text(encoding="utf-8").strip()[:64] or "development"
    except OSError:
        return "development"


def _write(document: dict[str, object]) -> None:
    sys.stdout.write(json.dumps(document, sort_keys=True) + "\n")


def _run(arguments: argparse.Namespace) -> int:
    config = load_config(arguments.config)
    lock_path = Path(str(arguments.state) + _LOCK_SUFFIX)
    lock_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with lock_path.open("w", encoding="utf-8") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            _write({"skipped": "another run holds the ledger lock"})
            return 0
        store = NodeStore(arguments.state)
        try:
            report: dict[str, object] = {"node": config.node, "version": _version()}
            if arguments.command in {"run", "collect"}:
                report["collect"] = vars(collect(config, store))
            if arguments.command in {"run", "deliver"}:
                try:
                    report["deliver"] = deliver(config, store, version=_version(), fleet_db=arguments.fleet_db)
                except (OSError, RuntimeError, ValueError) as exc:
                    report["deliver_error"] = type(exc).__name__
            _write(report)
        finally:
            store.close()
    return 1 if "deliver_error" in report else 0


def _ingest(arguments: argparse.Namespace) -> int:
    connection = connect_fleet(arguments.fleet_db)
    try:
        _write(ingest(connection, arguments.node, sys.stdin))
    except (ValueError, KeyError) as exc:
        _write({"ok": False, "error": type(exc).__name__})
        return 1
    finally:
        connection.close()
    return 0


def _status(arguments: argparse.Namespace) -> int:
    store = NodeStore(arguments.state)
    try:
        keys = ("last_collect_at", "last_push_at", "acked_seq", "change_seq", "backlog_bytes", "files_tracked", "homes", "lane_errors", "collect_seconds")
        report: dict[str, object] = {key: store.meta(key) for key in keys}
        report["cursors"] = len(store.cursors())
    finally:
        store.close()
    if arguments.fleet_db.exists():
        connection = connect_fleet(arguments.fleet_db, read_only=True)
        try:
            report["fleet_nodes"] = [
                dict(zip(("node", "last_ingest_at", "backlog_bytes", "rows_received"), row))
                for row in connection.execute("select node, last_ingest_at, backlog_bytes, rows_received from ledger_nodes order by node")
            ]
            report["fleet_rows"] = connection.execute("select count(*) from token_usage_hourly").fetchone()[0]
        finally:
            connection.close()
    _write(report)
    return 0


def main(argv: list[str] | None = None) -> int:
    """Run one exporter command and return its exit status."""
    parser = argparse.ArgumentParser(prog="token_ledger", description="Fleet token ledger exporter")
    parser.add_argument("command", choices=("run", "collect", "deliver", "ingest", "status"))
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--fleet-db", type=Path, default=DEFAULT_FLEET_DB)
    parser.add_argument("--node", default="")
    arguments = parser.parse_args(argv)
    if arguments.command == "ingest":
        return _ingest(arguments)
    if arguments.command == "status":
        return _status(arguments)
    return _run(arguments)


if __name__ == "__main__":
    raise SystemExit(main())
