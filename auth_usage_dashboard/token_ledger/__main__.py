# Copyright (c) 2026 PitchAI. All rights reserved.
"""Command line for the token ledger exporter (``python3 -m token_ledger``)."""

from __future__ import annotations

import argparse
import fcntl
import json
import sys
from contextlib import closing, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

from .collect import collect
from .deliver import deliver
from .failures import ExpectedFailure
from .fleet_store import DEFAULT_FLEET_DB, connect_fleet, ingest
from .node_store import DEFAULT_STATE, NodeStore
from .sources import DEFAULT_CONFIG, load_config

if TYPE_CHECKING:
    from auth_usage_dashboard.timeseries_types import JsonObject, SqlValue

    from .sources import NodeConfig

_VERSION_FILE = Path(__file__).resolve().parent / "VERSION"
_LOCK_SUFFIX = ".lock"
_STATUS_KEYS = (
    "last_collect_at",
    "last_push_at",
    "acked_seq",
    "change_seq",
    "backlog_bytes",
    "files_tracked",
    "homes",
    "lane_errors",
    "collect_seconds",
)
_FLEET_NODE_FIELDS = ("node", "last_ingest_at", "backlog_bytes", "rows_received")


@dataclass(frozen=True)
class _Arguments:
    """Typed view of the parsed command line."""

    command: str
    config: Path
    state: Path
    fleet_db: Path
    node: str


def _version() -> str:
    with suppress(OSError):
        return _VERSION_FILE.read_text(encoding="utf-8").strip()[:64] or "development"
    return "development"


def _write(document: JsonObject) -> None:
    sys.stdout.write(json.dumps(document, sort_keys=True) + "\n")


def _pass(arguments: _Arguments, config: NodeConfig, store: NodeStore) -> JsonObject:
    """Return the run report of collecting and/or delivering; a delivery failure is reported, not raised."""
    report: JsonObject = {"node": config.node, "version": _version()}
    if arguments.command in {"run", "collect"}:
        report["collect"] = collect(config, store).as_json()
    if arguments.command in {"run", "deliver"}:
        with ExpectedFailure(OSError, RuntimeError, ValueError) as failure:
            report["deliver"] = deliver(config, store, version=_version(), fleet_db=arguments.fleet_db)
        if failure.name is not None:
            report["deliver_error"] = failure.name
    return report


def _run(arguments: _Arguments) -> int:
    config = load_config(arguments.config)
    lock_path = Path(str(arguments.state) + _LOCK_SUFFIX)
    lock_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with lock_path.open("w", encoding="utf-8") as lock:
        with ExpectedFailure(OSError) as busy:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if busy.name is not None:
            _write({"skipped": "another run holds the ledger lock"})
            return 0
        with closing(NodeStore(arguments.state)) as store:
            report = _pass(arguments, config, store)
            _write(report)
    return 1 if "deliver_error" in report else 0


def _ingest(arguments: _Arguments) -> int:
    with closing(connect_fleet(arguments.fleet_db)) as connection, ExpectedFailure(ValueError, KeyError) as failure:
        _write(ingest(connection, arguments.node, sys.stdin))
    if failure.name is None:
        return 0
    _write({"ok": False, "error": failure.name})
    return 1


def _status(arguments: _Arguments) -> int:
    with closing(NodeStore(arguments.state)) as store:
        report: JsonObject = {key: store.meta(key) for key in _STATUS_KEYS}
        report["cursors"] = len(store.cursors())
    if arguments.fleet_db.exists():
        with closing(connect_fleet(arguments.fleet_db, read_only=True)) as connection:
            query = "select node, last_ingest_at, backlog_bytes, rows_received from ledger_nodes order by node"
            nodes = cast("list[tuple[SqlValue, ...]]", connection.execute(query).fetchall())
            report["fleet_nodes"] = [dict(zip(_FLEET_NODE_FIELDS, row, strict=True)) for row in nodes]
            count = cast("tuple[int]", connection.execute("select count(*) from token_usage_hourly").fetchone())
            report["fleet_rows"] = count[0]
    _write(report)
    return 0


def main(argv: list[str] | None = None) -> int:
    """Run one exporter command.

    Returns:
        Process exit status.
    """
    parser = argparse.ArgumentParser(prog="token_ledger", description="Fleet token ledger exporter")
    parser.add_argument("command", choices=("run", "collect", "deliver", "ingest", "status"))
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--fleet-db", type=Path, default=DEFAULT_FLEET_DB)
    parser.add_argument("--node", default="")
    namespace = parser.parse_args(argv)
    arguments = _Arguments(
        command=cast("str", namespace.command),
        config=cast("Path", namespace.config),
        state=cast("Path", namespace.state),
        fleet_db=cast("Path", namespace.fleet_db),
        node=cast("str", namespace.node),
    )
    if arguments.command == "ingest":
        return _ingest(arguments)
    if arguments.command == "status":
        return _status(arguments)
    return _run(arguments)


if __name__ == "__main__":
    raise SystemExit(main())
