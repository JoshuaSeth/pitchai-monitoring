# Copyright (c) 2026 PitchAI. All rights reserved.
"""Structured completion evidence for a finite ASTRA watch."""

from __future__ import annotations

from dataclasses import dataclass

from .json_types import JsonObject


@dataclass(frozen=True)
class WatchWindow:
    """Wall and monotonic timing facts for a finite watch."""

    started_at_utc: str
    completed_at_utc: str
    elapsed_seconds: float


@dataclass(frozen=True)
class WatchCoverage:
    """Coverage counts for a finite watch."""

    cycle_count: int
    expected_cycle_count: int
    baseline_account_count: int
    account_observation_count: int
    account_check_count: int
    unavailable_observation_count: int
    provider_request_count: int


@dataclass(frozen=True)
class WatchOutcome:
    """Error, match, alert, and validity outcomes for a finite watch."""

    error_count: int
    astra_match_count: int
    alert_count: int
    valid_window: bool


@dataclass(frozen=True)
class WatchSummary:
    """Completion proof for one finite monitoring process."""

    window: WatchWindow
    coverage: WatchCoverage
    outcome: WatchOutcome

    @property
    def started_at_utc(self) -> str:
        """Return when the finite watch began."""
        return self.window.started_at_utc

    @property
    def completed_at_utc(self) -> str:
        """Return when the finite watch completed."""
        return self.window.completed_at_utc

    @property
    def elapsed_seconds(self) -> float:
        """Return the monotonic observation span."""
        return self.window.elapsed_seconds

    @property
    def cycle_count(self) -> int:
        """Return the observed cycle count."""
        return self.coverage.cycle_count

    @property
    def expected_cycle_count(self) -> int:
        """Return the required cycle count."""
        return self.coverage.expected_cycle_count

    @property
    def baseline_account_count(self) -> int:
        """Return the baseline account inventory size."""
        return self.coverage.baseline_account_count

    @property
    def account_check_count(self) -> int:
        """Return the number of successful account catalog checks."""
        return self.coverage.account_check_count

    @property
    def account_observation_count(self) -> int:
        """Return the number of account outcomes recorded."""
        return self.coverage.account_observation_count

    @property
    def unavailable_observation_count(self) -> int:
        """Return the number of broker-declared unavailable observations."""
        return self.coverage.unavailable_observation_count

    @property
    def provider_request_count(self) -> int:
        """Return the number of provider model-list requests attempted."""
        return self.coverage.provider_request_count

    @property
    def error_count(self) -> int:
        """Return the total sanitized error count."""
        return self.outcome.error_count

    @property
    def astra_match_count(self) -> int:
        """Return the total ASTRA catalog-match count."""
        return self.outcome.astra_match_count

    @property
    def alert_count(self) -> int:
        """Return the number of private alerts sent."""
        return self.outcome.alert_count

    @property
    def valid_window(self) -> bool:
        """Return whether all finite-watch validity invariants held."""
        return self.outcome.valid_window

    def audit_fields(self) -> JsonObject:
        """Return flattened credential-free completion fields."""
        return {
            "started_at_utc": self.started_at_utc,
            "completed_at_utc": self.completed_at_utc,
            "elapsed_seconds": self.elapsed_seconds,
            "cycle_count": self.cycle_count,
            "expected_cycle_count": self.expected_cycle_count,
            "baseline_account_count": self.baseline_account_count,
            "account_observation_count": self.account_observation_count,
            "account_check_count": self.account_check_count,
            "unavailable_observation_count": self.unavailable_observation_count,
            "provider_request_count": self.provider_request_count,
            "error_count": self.error_count,
            "astra_match_count": self.astra_match_count,
            "alert_count": self.alert_count,
            "valid_window": self.valid_window,
        }
