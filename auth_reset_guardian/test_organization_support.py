# Copyright (c) 2026 PitchAI. All rights reserved.
"""Typed fixtures for organization reset-guardian policy tests."""

from __future__ import annotations

import threading
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, final

from .audit import AuditStore
from .clients import GuardianSource
from .models import (
    AccountDescriptor,
    AccountObservation,
    ResetCredit,
)
from .organization_guardian import OrganizationGuardian
from .test_organization_assertions import (
    database_rows,
    require,
    require_equal,
    row_integer,
)

if TYPE_CHECKING:
    from pathlib import Path

    from .guardian import GuardianRunSummary
    from .models import ConsumeResult

__all__ = [
    "database_rows",
    "require",
    "require_equal",
    "row_integer",
]


UTC = timezone(timedelta(0))
NOW = datetime(2026, 9, 7, 10, 0, tzinfo=UTC)
FULLY_USED = 100


def reset_credit(provider_id: str, *, expires_at: datetime) -> ResetCredit:
    """Build one available, plan-supported Codex reset credit.

    Returns:
        A provider credit with a stable opaque identity.
    """
    return ResetCredit(
        provider_id=provider_id,
        reset_type="codex_rate_limits",
        status="available",
        granted_at=expires_at - timedelta(days=30),
        expires_at=expires_at,
        title="Full reset",
        supported_by_plan=True,
    )


def account_observation(
    label: str,
    *,
    captured_at: datetime = NOW,
    used_percent: int = 100,
    weekly_reset_at: datetime | None = None,
    credit_bank: tuple[ResetCredit, ...] = (),
) -> AccountObservation:
    """Build one broker account and a coherent provider observation.

    Returns:
        Sanitized account state suitable for pure and workflow tests.
    """
    descriptor = AccountDescriptor(
        broker_account_id=f"broker:{label}",
        label=label,
        enabled=True,
    )
    weekly_reset = weekly_reset_at or captured_at + timedelta(days=7)
    is_exhausted = used_percent >= FULLY_USED
    return AccountObservation(
        descriptor=descriptor,
        captured_at=captured_at,
        broker_state={"availability": "available"},
        usage_state={
            "allowed": not is_exhausted,
            "limit_reached": is_exhausted,
            "primary_window": {
                "limit_window_seconds": 604800,
                "reset_after_seconds": max(
                    0,
                    int((weekly_reset - captured_at).total_seconds()),
                ),
                "reset_at": int(weekly_reset.timestamp()),
                "used_percent": used_percent,
            },
            "secondary_window": None,
            "available_reset_count": len(credit_bank),
            "applicable_reset_count": len(credit_bank),
        },
        available_count=len(credit_bank),
        credits=credit_bank,
    )


def disabled_observation(
    label: str,
    *,
    credit_bank: tuple[ResetCredit, ...],
) -> AccountObservation:
    """Build one broker-disabled account observation.

    Returns:
        An observation whose broker lifecycle excludes it from usable capacity.
    """
    observation = account_observation(label, credit_bank=credit_bank)
    return replace(
        observation,
        descriptor=replace(observation.descriptor, enabled=False),
    )


def contradictory_observation(
    label: str,
    *,
    credit_bank: tuple[ResetCredit, ...],
) -> AccountObservation:
    """Build exhausted windows with provider flags that claim scheduling is allowed.

    Returns:
        An intentionally contradictory observation for fail-closed tests.
    """
    observation = account_observation(label, credit_bank=credit_bank)
    usage_state = {**observation.usage_state, "allowed": True}
    return replace(observation, usage_state=usage_state)


@final
class SequencedSource(GuardianSource):
    """Thread-safe provider double with explicit refresh and consume sequences."""

    def __init__(
        self,
        descriptors: tuple[AccountDescriptor, ...],
        refreshes: dict[str, list[AccountObservation | BaseException]],
        outcomes: list[ConsumeResult | BaseException],
    ) -> None:
        """Bind per-account refresh sequences and provider outcomes."""
        self._descriptors = descriptors
        self._refreshes = refreshes
        self._outcomes = outcomes
        self._lock = threading.Lock()
        self.consume_calls: list[tuple[str, str, str]] = []

    @final
    def list_accounts(self) -> list[AccountDescriptor]:
        """Return each configured broker account once."""
        return list(self._descriptors)

    @final
    def refresh_account(self, descriptor: AccountDescriptor) -> AccountObservation:
        """Return or raise the next configured authoritative refresh."""
        with self._lock:
            items = self._refreshes[descriptor.account_ref]
            item = items.pop(0) if len(items) > 1 else items[0]
        if isinstance(item, BaseException):
            raise item
        return item

    @final
    def consume_credit(
        self,
        observation: AccountObservation,
        credit: ResetCredit,
        idempotency_key: str,
    ) -> ConsumeResult:
        """Record the exact target and return or raise the next outcome.

        Returns:
            The next configured provider outcome.
        """
        with self._lock:
            self.consume_calls.append(
                (
                    observation.descriptor.account_ref,
                    credit.credit_ref,
                    idempotency_key,
                ),
            )
            outcome = self._outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class RecordingNotifier:
    """Requester-private notifier double retaining accepted messages."""

    def __init__(self) -> None:
        """Start with no accepted messages."""
        self.messages: list[str] = []

    def notify(self, message: str) -> None:
        """Accept one requester-private message."""
        self.messages.append(message)

    def message_count(self) -> int:
        """Return the number of accepted messages."""
        return len(self.messages)


def run_guardian(
    db_path: Path,
    *,
    source: GuardianSource,
    now: datetime,
    notifier: RecordingNotifier | None = None,
) -> GuardianRunSummary:
    """Run one live-mode organization guardian pass.

    Returns:
        The persisted guardian summary.
    """
    with AuditStore(db_path) as audit:
        return OrganizationGuardian(
            source=source,
            audit=audit,
            notifier=notifier,
            clock=lambda: now,
        ).run(mode="live", dry_run=False)
