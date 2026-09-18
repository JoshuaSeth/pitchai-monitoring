# Copyright (c) 2026 PitchAI. All rights reserved.
"""SQLite schema and connection policy for broker usage history."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS collection_batches (
    batch_id INTEGER PRIMARY KEY AUTOINCREMENT,
    sampled_at TEXT NOT NULL UNIQUE,
    source TEXT NOT NULL,
    collector_version TEXT NOT NULL,
    account_count INTEGER NOT NULL CHECK (account_count >= 0)
);

CREATE TABLE IF NOT EXISTS account_usage_samples (
    sample_id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id INTEGER NOT NULL REFERENCES collection_batches(batch_id),
    sampled_at TEXT NOT NULL,
    account_label TEXT NOT NULL,
    account_ref TEXT NOT NULL,
    enabled INTEGER NOT NULL CHECK (enabled IN (0, 1)),
    auth_state TEXT NOT NULL CHECK (auth_state IN ('valid', 'invalid', 'unknown')),
    account_status TEXT NOT NULL,
    availability TEXT NOT NULL,
    five_used_percent REAL,
    five_remaining_percent REAL,
    five_reset_at TEXT,
    five_window_seconds INTEGER,
    weekly_used_percent REAL,
    weekly_remaining_percent REAL,
    weekly_reset_at TEXT,
    weekly_window_seconds INTEGER,
    redeemable_count INTEGER,
    provider_observed_at TEXT,
    provider_age_seconds INTEGER,
    provider_stale INTEGER NOT NULL CHECK (provider_stale IN (0, 1)),
    reset_inventory_observed_at TEXT,
    reset_inventory_stale INTEGER,
    token_usage_observed_at TEXT,
    token_usage_stale INTEGER,
    probe_error TEXT,
    reset_inventory_error TEXT,
    token_usage_error TEXT,
    values_source TEXT NOT NULL CHECK (
        values_source IN ('current', 'last_known', 'unavailable', 'legacy')
    ),
    carried_fields_json TEXT NOT NULL,
    token_date TEXT,
    tokens_today INTEGER,
    source TEXT NOT NULL,
    collector_version TEXT NOT NULL,
    UNIQUE (batch_id, account_ref)
);

CREATE INDEX IF NOT EXISTS account_usage_samples_time_idx
    ON account_usage_samples(sampled_at, sample_id);
CREATE INDEX IF NOT EXISTS account_usage_samples_label_time_idx
    ON account_usage_samples(account_label, sampled_at, sample_id);
CREATE INDEX IF NOT EXISTS account_usage_samples_ref_time_idx
    ON account_usage_samples(account_ref, sampled_at, sample_id);

CREATE VIEW IF NOT EXISTS account_usage_report AS
SELECT
    sampled_at, account_label, account_ref, enabled, auth_state, account_status,
    availability, five_used_percent, five_remaining_percent, five_reset_at,
    five_window_seconds, weekly_used_percent, weekly_remaining_percent,
    weekly_reset_at, weekly_window_seconds, redeemable_count, provider_observed_at,
    provider_age_seconds, provider_stale, reset_inventory_observed_at,
    reset_inventory_stale, token_usage_observed_at, token_usage_stale, probe_error,
    reset_inventory_error, token_usage_error, values_source, carried_fields_json,
    token_date, tokens_today, source, collector_version, sample_id
FROM account_usage_samples;

CREATE TABLE IF NOT EXISTS store_metadata (
    metadata_key TEXT PRIMARY KEY,
    metadata_value TEXT NOT NULL
);
"""

INSERT_SAMPLE_SQL = """
INSERT INTO account_usage_samples(
    batch_id, sampled_at, account_label, account_ref, enabled, auth_state,
    account_status, availability, five_used_percent, five_remaining_percent,
    five_reset_at, five_window_seconds, weekly_used_percent,
    weekly_remaining_percent, weekly_reset_at, weekly_window_seconds,
    redeemable_count, provider_observed_at, provider_age_seconds, provider_stale,
    reset_inventory_observed_at, reset_inventory_stale, token_usage_observed_at,
    token_usage_stale, probe_error, reset_inventory_error, token_usage_error,
    values_source, carried_fields_json, token_date, tokens_today, source,
    collector_version
) VALUES (
    :batch_id, :sampled_at, :account_label, :account_ref, :enabled, :auth_state,
    :account_status, :availability, :five_used_percent, :five_remaining_percent,
    :five_reset_at, :five_window_seconds, :weekly_used_percent,
    :weekly_remaining_percent, :weekly_reset_at, :weekly_window_seconds,
    :redeemable_count, :provider_observed_at, :provider_age_seconds, :provider_stale,
    :reset_inventory_observed_at, :reset_inventory_stale, :token_usage_observed_at,
    :token_usage_stale, :probe_error, :reset_inventory_error, :token_usage_error,
    :values_source, :carried_fields_json, :token_date, :tokens_today, :source,
    :collector_version
)
"""
INSERT_BATCH_SQL = """INSERT INTO collection_batches(
    sampled_at, source, collector_version, account_count
) VALUES (?, ?, ?, ?)"""
INSERT_BATCH_IF_NEW_SQL = """INSERT OR IGNORE INTO collection_batches(
    sampled_at, source, collector_version, account_count
) VALUES (?, ?, ?, ?)"""


def connect_database(path: Path, *, read_only: bool = False) -> sqlite3.Connection:
    """Open a hardened SQLite connection and verify its schema version.

    Returns:
        Configured SQLite connection with row access by column name.

    """
    resolved = path.expanduser().resolve()
    if read_only:
        connection = sqlite3.connect(
            f"file:{resolved}?mode=ro",
            uri=True,
            timeout=30.0,
        )
    else:
        resolved.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        Path(resolved.parent).chmod(0o700)
        connection = sqlite3.connect(resolved, timeout=30.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 30000")
    if not read_only:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = FULL")
        _initialize(connection)
        secure_database_files(resolved)
    else:
        _verify_version(connection)
    return connection


def secure_database_files(path: Path) -> None:
    """Keep the database and transient SQLite files root-private."""
    resolved = path.expanduser().resolve()
    for candidate in (resolved, Path(f"{resolved}-wal"), Path(f"{resolved}-shm")):
        if candidate.exists():
            candidate.chmod(0o600)


def parse_timestamp(value: str) -> datetime:
    """Parse one timezone-aware persisted timestamp.

    Returns:
        Timestamp normalized to UTC.

    Raises:
        ValueError: If the timestamp has no timezone.
    """
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        message = "time-series timestamp lacks a timezone"
        raise ValueError(message)
    return parsed.astimezone(UTC)


def _initialize(connection: sqlite3.Connection) -> None:
    version = cast("int", connection.execute("PRAGMA user_version").fetchone()[0])
    if version not in {0, SCHEMA_VERSION}:
        message = f"unsupported usage time-series schema version: {version}"
        raise RuntimeError(message)
    connection.executescript(_SCHEMA)
    connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    connection.commit()


def _verify_version(connection: sqlite3.Connection) -> None:
    version = cast("int", connection.execute("PRAGMA user_version").fetchone()[0])
    if version != SCHEMA_VERSION:
        message = f"unsupported usage time-series schema version: {version}"
        raise RuntimeError(message)
