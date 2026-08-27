# Copyright (c) 2026 PitchAI. All rights reserved.
"""Bounded, read-only reporting for the usage time-series database."""

from __future__ import annotations

from collections import defaultdict
from contextlib import closing
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from typing import TYPE_CHECKING, cast

from .timeseries_schema import SCHEMA_VERSION, connect_database

if TYPE_CHECKING:
    import sqlite3
    from pathlib import Path

    from .timeseries_types import JsonObject, JsonValue

type Report = JsonObject
MAX_REPORT_LIMIT = 100_000
MAX_HISTORY_HOURS = 24 * 366

_RECENT_SQL = """SELECT * FROM account_usage_report
    WHERE account_label = ?
    ORDER BY sampled_at DESC, sample_id DESC LIMIT ?"""
_HISTORY_SQL = """SELECT * FROM account_usage_report
    WHERE sampled_at >= ?
    ORDER BY sampled_at ASC, account_label ASC LIMIT ?"""
_ACCOUNT_HISTORY_SQL = """SELECT * FROM account_usage_report
    WHERE sampled_at >= ? AND account_label = ?
    ORDER BY sampled_at ASC, sample_id ASC LIMIT ?"""


def database_status(path: Path) -> Report:
    """Return bounded database identity and retention evidence.

    Returns:
        Database schema, counts, and observed retention span.
    """
    with closing(connect_database(path, read_only=True)) as connection:
        batch = cast(
            "sqlite3.Row",
            connection.execute(
                """SELECT COUNT(*) AS count, MIN(sampled_at) AS first_at,
                          MAX(sampled_at) AS last_at FROM collection_batches""",
            ).fetchone(),
        )
        sample_count = cast(
            "int",
            connection.execute("SELECT COUNT(*) FROM account_usage_samples").fetchone()[0],
        )
        latest = cast(
            "sqlite3.Row | None",
            connection.execute(
                """SELECT batch_id, sampled_at, source, collector_version, account_count,
                          (SELECT COUNT(*) FROM account_usage_samples AS samples
                            WHERE samples.batch_id = batches.batch_id) AS sample_count
                     FROM collection_batches AS batches
                    ORDER BY sampled_at DESC, batch_id DESC LIMIT 1""",
            ).fetchone(),
        )
    batch_count = cast("int", batch["count"])
    first_sample = cast("str | None", batch["first_at"])
    last_sample = cast("str | None", batch["last_at"])
    latest_account_count = None if latest is None else cast("int", latest["account_count"])
    latest_sample_count = None if latest is None else cast("int", latest["sample_count"])
    latest_collector_version = None if latest is None else cast("str", latest["collector_version"])
    latest_source = None if latest is None else cast("str", latest["source"])
    return {
        "schema_version": SCHEMA_VERSION,
        "database": str(path.expanduser().resolve()),
        "batch_count": batch_count,
        "sample_count": sample_count,
        "first_sample_at": first_sample,
        "last_sample_at": last_sample,
        "latest_batch_account_count": latest_account_count,
        "latest_batch_sample_count": latest_sample_count,
        "latest_collector_version": latest_collector_version,
        "latest_source": latest_source,
    }


def recent_rows(path: Path, *, account_label: str, limit: int) -> list[Report]:
    """Read the newest rows for exactly one account label.

    Returns:
        Newest rows up to the validated limit.
    """
    _validate_limit(limit)
    with closing(connect_database(path, read_only=True)) as connection:
        rows = cast(
            "list[sqlite3.Row]",
            connection.execute(
                _RECENT_SQL,
                (account_label, limit),
            ).fetchall(),
        )
    return _reports(rows)


def history_rows(
    path: Path,
    *,
    since: datetime,
    account_label: str | None,
    limit: int,
) -> list[Report]:
    """Read a bounded history window for one account or the full inventory.

    Returns:
        Chronological rows up to the validated limit.

    """
    _validate_limit(limit)
    since_text = _isoformat(since)
    with closing(connect_database(path, read_only=True)) as connection:
        if account_label is None:
            rows = cast(
                "list[sqlite3.Row]",
                connection.execute(
                    _HISTORY_SQL,
                    (since_text, limit),
                ).fetchall(),
            )
        else:
            rows = cast(
                "list[sqlite3.Row]",
                connection.execute(
                    _ACCOUNT_HISTORY_SQL,
                    (since_text, account_label, limit),
                ).fetchall(),
            )
    return _reports(rows)


def window_summary(path: Path, *, hours: int, now: datetime) -> Report:
    """Summarize sample coverage, auth-invalid rows, staleness, and gaps.

    Returns:
        Per-account coverage evidence for the requested window.

    Raises:
        ValueError: If the requested window is outside the bounded range.
    """
    if not 1 <= hours <= MAX_HISTORY_HOURS:
        message = f"summary hours must be between 1 and {MAX_HISTORY_HOURS}"
        raise ValueError(message)
    now = now.astimezone(UTC)
    since = now - timedelta(hours=hours)
    with closing(connect_database(path, read_only=True)) as connection:
        rows = cast(
            "list[sqlite3.Row]",
            connection.execute(
                """SELECT sampled_at, account_label, account_ref, auth_state,
                          provider_stale, values_source
                     FROM account_usage_samples
                    WHERE sampled_at >= ? AND sampled_at <= ?
                    ORDER BY account_label ASC, sampled_at ASC, sample_id ASC""",
                (_isoformat(since), _isoformat(now)),
            ).fetchall(),
        )
        batches = cast(
            "int",
            connection.execute(
                "SELECT COUNT(*) FROM collection_batches WHERE sampled_at >= ? AND sampled_at <= ?",
                (_isoformat(since), _isoformat(now)),
            ).fetchone()[0],
        )
    accounts = _summaries(_reports(rows))
    return {
        "schema_version": SCHEMA_VERSION,
        "window_hours": hours,
        "period_start": _isoformat(since),
        "period_end": _isoformat(now),
        "batch_count": batches,
        "account_count": len(accounts),
        "accounts": _json_array(accounts),
    }


def _summaries(rows: list[Report]) -> list[Report]:
    grouped: dict[str, list[Report]] = defaultdict(list)
    for row in rows:
        label = row.get("account_label")
        if isinstance(label, str):
            grouped[label].append(row)
    summaries: list[Report] = []
    for label, account_rows in sorted(grouped.items()):
        timestamps: list[datetime] = []
        for row in account_rows:
            sampled_at = row.get("sampled_at")
            if not isinstance(sampled_at, str):
                message = "history report row lacks a timestamp"
                raise TypeError(message)
            timestamps.append(datetime.fromisoformat(sampled_at).astimezone(UTC))
        gaps: list[int] = []
        for previous, current in pairwise(timestamps):
            gaps.append(int((current - previous).total_seconds()))
        auth_invalid_samples = 0
        provider_stale_samples = 0
        last_known_samples = 0
        for row in account_rows:
            auth_invalid_samples += int(row.get("auth_state") == "invalid")
            provider_stale_samples += int(row.get("provider_stale") == 1)
            last_known_samples += int(row.get("values_source") == "last_known")
        summaries.append(
            {
                "account_label": label,
                "account_ref": account_rows[-1]["account_ref"],
                "sample_count": len(account_rows),
                "first_sample_at": account_rows[0]["sampled_at"],
                "last_sample_at": account_rows[-1]["sampled_at"],
                "max_gap_seconds": max(gaps, default=0),
                "auth_invalid_samples": auth_invalid_samples,
                "provider_stale_samples": provider_stale_samples,
                "last_known_samples": last_known_samples,
            },
        )
    return summaries


def _validate_limit(limit: int) -> None:
    if not 1 <= limit <= MAX_REPORT_LIMIT:
        message = f"report limit must be between 1 and {MAX_REPORT_LIMIT}"
        raise ValueError(message)


def _isoformat(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _reports(rows: list[sqlite3.Row]) -> list[Report]:
    reports: list[Report] = []
    for row in rows:
        report: Report = {}
        keys = row.keys()
        for key in keys:
            value = cast("JsonValue", row[key])
            if value is not None and not isinstance(value, (str, int, float, bool)):
                message = f"unexpected SQLite report value in {key}"
                raise TypeError(message)
            report[key] = value
        reports.append(report)
    return reports


def _json_array(reports: list[Report]) -> list[JsonValue]:
    values: list[JsonValue] = [*reports]
    return values
