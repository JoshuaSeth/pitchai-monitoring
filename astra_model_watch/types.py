# Copyright (c) 2026 PitchAI. All rights reserved.
"""Typed values shared by the ASTRA model watch."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .json_types import JsonObject

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True)
class BrokerAuthentication:
    """Sensitive and filesystem-backed authentication facts for one account."""

    auth_path: Path
    auth_file_mode: str | None
    auth_file_mtime_utc: str | None
    access_token: str | None = field(repr=False)
    account_header_id: str | None = field(repr=False)
    account_id_source: str | None = None
    error_code: str | None = None


@dataclass(frozen=True)
class BrokerAccount:
    """One broker account and its isolated existing authentication state."""

    directory_name: str
    label: str
    enabled: bool
    availability: str
    fingerprint: str
    authentication: BrokerAuthentication

    @property
    def auth_path(self) -> Path:
        """Return the broker-owned authentication source path."""
        return self.authentication.auth_path

    @property
    def auth_file_mode(self) -> str | None:
        """Return the observed authentication file mode."""
        return self.authentication.auth_file_mode

    @property
    def auth_file_mtime_utc(self) -> str | None:
        """Return the authentication file modification time."""
        return self.authentication.auth_file_mtime_utc

    @property
    def access_token(self) -> str | None:
        """Return the existing bearer without exposing it in representations."""
        return self.authentication.access_token

    @property
    def account_header_id(self) -> str | None:
        """Return the signed account identifier used in the provider header."""
        return self.authentication.account_header_id

    @property
    def account_id_source(self) -> str | None:
        """Return how the signed account identity was derived."""
        return self.authentication.account_id_source

    @property
    def error_code(self) -> str | None:
        """Return a sanitized inventory error, if authentication is unusable."""
        return self.authentication.error_code


@dataclass(frozen=True)
class ModelMatch:
    """One catalog model whose ID or name contains ASTRA."""

    identifier: str
    matched_fields: tuple[str, ...]
    matched_values: tuple[str, ...]


@dataclass(frozen=True)
class CatalogResult:
    """Sanitized result of one account's model-catalog GET."""

    model_count: int
    matches: tuple[ModelMatch, ...]
    etag_present: bool


@dataclass(frozen=True)
class AccountCheck:
    """Sanitized outcome for one account in one cycle."""

    account: BrokerAccount
    checked_at_utc: str
    model_count: int | None
    matches: tuple[ModelMatch, ...]
    error_code: str | None
    provider_request_count: int
    unavailable_reason: str | None = None


@dataclass(frozen=True)
class CycleTiming:
    """Timing facts for one scheduled catalog pass."""

    started_at_utc: str
    completed_at_utc: str
    start_lateness_seconds: float


@dataclass(frozen=True)
class CycleAccountCoverage:
    """Account outcome counts for one scheduled catalog pass."""

    account_count: int
    checked_count: int
    unavailable_count: int


@dataclass(frozen=True)
class CycleSummary:
    """Aggregate counts and timing for one scheduled catalog pass."""

    cycle_index: int
    coverage: CycleAccountCoverage
    error_count: int
    match_count: int
    inventory_changed: bool
    timing: CycleTiming

    @property
    def account_count(self) -> int:
        """Return the number of broker account records observed."""
        return self.coverage.account_count

    @property
    def checked_count(self) -> int:
        """Return the number of successful catalog checks."""
        return self.coverage.checked_count

    @property
    def unavailable_count(self) -> int:
        """Return the number of broker-declared unavailable sessions."""
        return self.coverage.unavailable_count

    @property
    def started_at_utc(self) -> str:
        """Return when the cycle began."""
        return self.timing.started_at_utc

    @property
    def completed_at_utc(self) -> str:
        """Return when the cycle completed."""
        return self.timing.completed_at_utc

    @property
    def start_lateness_seconds(self) -> float:
        """Return monotonic scheduling lateness."""
        return self.timing.start_lateness_seconds

    def audit_fields(self) -> JsonObject:
        """Return flattened credential-free audit fields."""
        return {
            "cycle_index": self.cycle_index,
            "account_count": self.account_count,
            "checked_count": self.checked_count,
            "unavailable_count": self.unavailable_count,
            "error_count": self.error_count,
            "match_count": self.match_count,
            "inventory_changed": self.inventory_changed,
            "started_at_utc": self.started_at_utc,
            "completed_at_utc": self.completed_at_utc,
            "start_lateness_seconds": self.start_lateness_seconds,
        }


@dataclass(frozen=True)
class WatchConfig:
    """Runtime controls for a finite watch."""

    accounts_dir: Path
    client_version: str
    interval_seconds: float = 300.0
    duration_seconds: float = 7200.0
    heartbeat_seconds: float = 60.0
    request_timeout_seconds: float = 20.0
    max_start_lateness_seconds: float = 30.0
