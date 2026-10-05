# Copyright (c) 2026 PitchAI. All rights reserved.
"""Periodic redacted broker-inventory collector for durable usage history."""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Event, Thread
from typing import TYPE_CHECKING, Self, cast, final

from .capacity import parse_account
from .timeseries_rows import sanitized_error_code
from .timeseries_store import UsageTimeSeriesStore
from .timeseries_types import optional_object, require_object

if TYPE_CHECKING:
    from .settings import DashboardSettings
    from .timeseries_types import JsonObject, JsonValue

LOG = logging.getLogger(__name__)
_DEFAULT_DATABASE = "/dashboard-data/usage-history.sqlite3"
_DEFAULT_LEGACY_JSON = "/dashboard-data/usage-samples.json"
_MIN_INTERVAL_SECONDS = 300
_MAX_INTERVAL_SECONDS = 600
_MAX_STARTUP_DELAY_SECONDS = 120
_THREAD_JOIN_SECONDS = 30


@final
@dataclass(frozen=True)
class CollectorConfiguration:
    """Validated runtime inputs for the lightweight collector."""

    broker_data_dir: Path
    stale_after_seconds: int
    analytics_stale_after_seconds: int
    min_five_hour_remaining_percent: float
    interval_seconds: int
    startup_delay_seconds: int


@final
class UsageHistoryCollector:
    """Append the complete configured account inventory on a fixed cadence."""

    _accounts_dir: Path
    _store: UsageTimeSeriesStore
    _configuration: CollectorConfiguration
    _stop: Event
    _thread: Thread | None
    _executor: ThreadPoolExecutor

    def __init__(
        self,
        configuration: CollectorConfiguration,
        store: UsageTimeSeriesStore,
    ) -> None:
        """Configure one collector owned by the dashboard process.

        Raises:
            ValueError: If cadence or startup delay falls outside safe bounds.
        """
        if not _MIN_INTERVAL_SECONDS <= configuration.interval_seconds <= _MAX_INTERVAL_SECONDS:
            message = "collector interval must be between 300 and 600 seconds"
            raise ValueError(message)
        if not 0 <= configuration.startup_delay_seconds <= _MAX_STARTUP_DELAY_SECONDS:
            message = "collector startup delay must be between 0 and 120 seconds"
            raise ValueError(message)
        self._accounts_dir = configuration.broker_data_dir.expanduser().resolve() / "accounts"
        self._store = store
        self._configuration = configuration
        self._stop = Event()
        self._thread = None
        self._executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="auth-usage-history-read",
        )

    @classmethod
    def from_settings(cls, settings: DashboardSettings) -> Self:
        """Build the production collector from dashboard and history environment.

        Returns:
            Configured collector with a durable SQLite store.
        """
        interval = _environment_integer(
            "AUTH_USAGE_TIMESERIES_SAMPLE_INTERVAL_SECONDS",
            default=300,
        )
        database = Path(os.getenv("AUTH_USAGE_TIMESERIES_DB", _DEFAULT_DATABASE))
        legacy_json = Path(os.getenv("AUTH_USAGE_HISTORY_FILE", _DEFAULT_LEGACY_JSON))
        collector_version = os.getenv("AUTH_USAGE_COLLECTOR_VERSION", "development")
        store = UsageTimeSeriesStore(
            database,
            sample_interval_seconds=interval,
            collector_version=collector_version,
            legacy_json_path=legacy_json,
        )
        configuration = CollectorConfiguration(
            broker_data_dir=settings.broker_data_dir,
            stale_after_seconds=settings.stale_after_seconds,
            analytics_stale_after_seconds=settings.analytics_stale_after_seconds,
            min_five_hour_remaining_percent=settings.min_five_hour_remaining_percent,
            interval_seconds=interval,
            startup_delay_seconds=_environment_integer(
                "AUTH_USAGE_TIMESERIES_STARTUP_DELAY_SECONDS",
                default=30,
            ),
        )
        return cls(configuration, store)

    def start(self) -> None:
        """Start the single background collector thread.

        Raises:
            RuntimeError: If this collector instance was already started.
        """
        if self._thread is not None:
            message = "usage history collector is already started"
            raise RuntimeError(message)
        self._thread = Thread(
            target=self._run,
            name="auth-usage-history-collector",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop the collector and wait for an in-flight lightweight read."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=_THREAD_JOIN_SECONDS)
        self._executor.shutdown(wait=True, cancel_futures=True)

    def collect_once(self, *, at: datetime | None = None) -> bool:
        """Read every redacted account file and append one due batch.

        Returns:
            True when a new batch was appended; False when cadence gating skipped it.

        Raises:
            TypeError: If a parsed account is missing its label.
        """
        observed_at = (at or datetime.now(UTC)).astimezone(UTC)
        raw_accounts = self._read_accounts()
        parsed_accounts: list[JsonObject] = []
        for raw in raw_accounts:
            state = optional_object(raw.get("state"))
            parsed = cast(
                "JsonObject",
                parse_account(
                    raw,
                    now=observed_at,
                    stale_after_seconds=self._configuration.stale_after_seconds,
                    analytics_stale_after_seconds=self._configuration.analytics_stale_after_seconds,
                    min_five_hour_remaining_percent=(self._configuration.min_five_hour_remaining_percent),
                    probe_error=sanitized_error_code(state.get("last_error")),
                ),
            )
            if not isinstance(parsed.get("label"), str):
                message = "parsed broker account is missing its label"
                raise TypeError(message)
            parsed_accounts.append(parsed)
        return self._store.record(
            parsed_accounts,
            raw_accounts=raw_accounts,
            at=observed_at,
        )

    def _read_accounts(self) -> list[JsonObject]:
        if not self._accounts_dir.is_dir():
            message = "broker accounts directory is unavailable"
            raise RuntimeError(message)
        accounts: list[JsonObject] = []
        for root in sorted(path for path in self._accounts_dir.iterdir() if path.is_dir()):
            metadata_path = root / "metadata.json"
            state_path = root / "state.json"
            if metadata_path.is_file():
                state: JsonObject = (
                    _read_object(state_path)
                    if state_path.is_file()
                    else {"availability": "unknown", "last_error": "state_file_missing"}
                )
                accounts.append(
                    {
                        "metadata": _read_object(metadata_path),
                        "state": state,
                    },
                )
        if not accounts:
            message = "broker account inventory is empty"
            raise RuntimeError(message)
        return accounts

    def _run(self) -> None:
        if self._stop.wait(self._configuration.startup_delay_seconds):
            return
        while not self._stop.is_set():
            collection = self._executor.submit(self.collect_once)
            error = collection.exception()
            if isinstance(error, (OSError, RuntimeError, TypeError, ValueError, sqlite3.Error)):
                LOG.error("Usage history collection failed: %s", type(error).__name__)
            elif error is not None:
                LOG.error("Usage history collection failed unexpectedly: %s", type(error).__name__)
            if self._stop.wait(self._configuration.interval_seconds):
                return


def _read_object(path: Path) -> JsonObject:
    decoded = cast("JsonValue", json.loads(path.read_text(encoding="utf-8")))
    return require_object(decoded, description=path.name)


def _environment_integer(name: str, *, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    normalized = raw.strip()
    if not normalized.isdecimal():
        message = f"{name} must be an integer"
        raise RuntimeError(message)
    return int(normalized)
