# Copyright (c) 2026 PitchAI. All rights reserved.
"""Define guardian run state and focused operation contexts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime

    from .audit import AuditStore, RedemptionAttempt
    from .clients import GuardianSource
    from .json_contract import JsonObject
    from .models import (
        AccountDescriptor,
        AccountObservation,
        ConsumeResult,
        ResetCredit,
    )

WARNING_THRESHOLDS_HOURS = (48, 24, 6, 2, 1)
AUTO_REDEEM_HORIZON = timedelta(hours=2)

type Notifier = Callable[[str], None]


class GuardianRunSummary:
    """Accumulate one guardian run without exposing a wide mutable data object."""

    def __init__(self, *, run_id: str, mode: str) -> None:
        """Initialize an empty running summary."""
        self.run_id: str = run_id
        self.mode: str = mode
        self.status: str = "running"
        self._counts: dict[str, int] = {
            "account": 0,
            "scanned_account": 0,
            "credit": 0,
            "redeemable_credit": 0,
            "warning": 0,
            "redemption_attempt": 0,
            "redemption": 0,
            "error": 0,
            "notification_error": 0,
        }

    @property
    def account_count(self) -> int:
        """Return the number of discovered accounts."""
        return self._counts["account"]

    @account_count.setter
    def account_count(self, value: int) -> None:
        self._counts["account"] = value

    @property
    def scanned_account_count(self) -> int:
        """Return the number of successfully scanned accounts."""
        return self._counts["scanned_account"]

    @scanned_account_count.setter
    def scanned_account_count(self, value: int) -> None:
        self._counts["scanned_account"] = value

    @property
    def credit_count(self) -> int:
        """Return the number of observed credits."""
        return self._counts["credit"]

    @credit_count.setter
    def credit_count(self, value: int) -> None:
        self._counts["credit"] = value

    @property
    def redeemable_credit_count(self) -> int:
        """Return the number of redeemable credits."""
        return self._counts["redeemable_credit"]

    @redeemable_credit_count.setter
    def redeemable_credit_count(self, value: int) -> None:
        self._counts["redeemable_credit"] = value

    @property
    def warning_count(self) -> int:
        """Return the number of newly claimed warning thresholds."""
        return self._counts["warning"]

    @warning_count.setter
    def warning_count(self, value: int) -> None:
        self._counts["warning"] = value

    @property
    def redemption_attempt_count(self) -> int:
        """Return the number of redemption attempts."""
        return self._counts["redemption_attempt"]

    @redemption_attempt_count.setter
    def redemption_attempt_count(self, value: int) -> None:
        self._counts["redemption_attempt"] = value

    @property
    def redemption_count(self) -> int:
        """Return the number of verified or reconciled redemptions."""
        return self._counts["redemption"]

    @redemption_count.setter
    def redemption_count(self, value: int) -> None:
        self._counts["redemption"] = value

    @property
    def error_count(self) -> int:
        """Return the number of guardian errors."""
        return self._counts["error"]

    @error_count.setter
    def error_count(self, value: int) -> None:
        self._counts["error"] = value

    @property
    def notification_error_count(self) -> int:
        """Return the number of notification errors."""
        return self._counts["notification_error"]

    @notification_error_count.setter
    def notification_error_count(self, value: int) -> None:
        self._counts["notification_error"] = value

    def serialized(self) -> JsonObject:
        """Return the stable JSON-safe run summary."""
        return {
            "run_id": self.run_id,
            "mode": self.mode,
            "status": self.status,
            "account_count": self.account_count,
            "scanned_account_count": self.scanned_account_count,
            "credit_count": self.credit_count,
            "redeemable_credit_count": self.redeemable_credit_count,
            "warning_count": self.warning_count,
            "redemption_attempt_count": self.redemption_attempt_count,
            "redemption_count": self.redemption_count,
            "error_count": self.error_count,
            "notification_error_count": self.notification_error_count,
        }


@dataclass(frozen=True, slots=True)
class Alert:
    """Represent one deduplicated notification line."""

    key: str
    line: str


@dataclass(frozen=True, slots=True)
class GuardianDependencies:
    """Hold the external boundaries shared by guardian operations."""

    source: GuardianSource
    audit: AuditStore
    notifier: Notifier | None
    clock: Callable[[], datetime]


@dataclass(frozen=True, slots=True)
class RunContext:
    """Carry mutable run results through focused guardian operations."""

    run_id: str
    mode: str
    dry_run: bool
    summary: GuardianRunSummary
    alerts: list[Alert]


@dataclass(frozen=True, slots=True)
class ScanRequest:
    """Identify one account scan within a guardian run."""

    context: RunContext
    descriptor: AccountDescriptor


@dataclass(frozen=True, slots=True)
class CreditDecision:
    """Carry one expiring credit through warning evaluation."""

    context: RunContext
    observation: AccountObservation
    credit: ResetCredit
    remaining: timedelta


@dataclass(frozen=True, slots=True)
class RecheckRequest:
    """Describe one fresh pre-redemption safety recheck."""

    context: RunContext
    descriptor: AccountDescriptor
    expected: ResetCredit
    reason: str
    enforce_horizon: bool


@dataclass(frozen=True, slots=True)
class AttemptRequest:
    """Describe one exact provider redemption attempt."""

    context: RunContext
    observation: AccountObservation
    credit: ResetCredit
    reason: str


@dataclass(frozen=True, slots=True)
class AttemptCompletion:
    """Carry a provider result and fresh post-state into completion."""

    request: AttemptRequest
    attempt: RedemptionAttempt
    result: ConsumeResult
    post: AccountObservation
    still_available: bool
