# Copyright (c) 2026 PitchAI. All rights reserved.
"""Immediate requester-private alerting for newly observed ASTRA models."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, final

from .evidence import safety_evidence
from .json_types import JsonObject
from .notifier import NotificationError

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from .audit import AlertState, AuditLog
    from .notifier import Notifier
    from .types import AccountCheck, BrokerAccount, ModelMatch


def _match_key(account: BrokerAccount, match: ModelMatch) -> str:
    raw = f"{account.fingerprint}\0{match.identifier.casefold()}".encode()
    return hashlib.sha256(raw).hexdigest()


def _alert_message(
    new_matches: Sequence[tuple[BrokerAccount, ModelMatch]],
    checked_at: str,
) -> str:
    lines = [
        "ASTRA model availability detected by the read-only broker account watch.",
        f"Verified at: {checked_at}",
    ]
    for account, match in new_matches:
        fields = ", ".join(match.matched_fields)
        lines.append(
            f"- Account: {account.label}; model: {match.identifier}; matched field(s): {fields}",
        )
    verification = " ".join(
        (
            "Verification: GET /backend-api/codex/models with each account's own",
            "existing broker bearer and ChatGPT-Account-ID.",
        )
    )
    safety = " ".join(
        (
            "Safety: no generation, lease, OAuth refresh, usage, reset-credit,",
            "claim, consume, redeem, activation, or entitlement endpoint was called.",
        )
    )
    lines.extend((verification, safety))
    return "\n".join(lines)


def _unseen_matches(
    checks: Sequence[AccountCheck],
    alert_state: AlertState,
) -> list[tuple[BrokerAccount, ModelMatch]]:
    """Return matches that have not already produced a private alert.

    Returns:
        Newly observed account and model pairs.
    """
    found: list[tuple[BrokerAccount, ModelMatch]] = []
    for check in checks:
        for match in check.matches:
            found.append((check.account, match))
    keys: list[str] = []
    for account, match in found:
        keys.append(_match_key(account, match))
    unseen_keys = set(alert_state.unseen(keys))
    unseen: list[tuple[BrokerAccount, ModelMatch]] = []
    for pair, key in zip(found, keys, strict=True):
        if key in unseen_keys:
            unseen.append(pair)
    return unseen


@final
class MatchAlerter:
    """Deduplicate and privately deliver newly observed ASTRA model matches."""

    def __init__(
        self,
        *,
        audit: AuditLog,
        alert_state: AlertState,
        notifier: Notifier | None,
        wall_clock: Callable[[], str],
    ) -> None:
        self.audit = audit
        self.alert_state = alert_state
        self.notifier = notifier
        self.wall_clock = wall_clock

    def _log(self, event: JsonObject) -> None:
        self.audit.append(event)

    def preflight(self) -> None:
        """Prove and record that a configured route is requester-private."""
        notifier = self.notifier
        if notifier is None:
            return
        receipt = notifier.preflight()
        self._log(
            {
                "event_type": "private_notification_preflight",
                "timestamp_utc": self.wall_clock(),
                "receipt": receipt,
                "safety": safety_evidence(0),
            },
        )

    def notify_new_matches(self, checks: Sequence[AccountCheck]) -> tuple[int, int]:
        """Alert for unseen matches and return sent/error counts."""
        unseen = _unseen_matches(checks, self.alert_state)
        if not unseen:
            return 0, 0
        notifier = self.notifier
        if notifier is None:
            self._log(
                {
                    "event_type": "astra_alert_failed",
                    "timestamp_utc": self.wall_clock(),
                    "error_code": "notifier_unconfigured",
                    "new_match_count": len(unseen),
                    "safety": safety_evidence(0),
                },
            )
            return 0, 1
        timestamp = self.wall_clock()
        try:
            receipt = self._deliver(notifier, unseen, timestamp)
        except (NotificationError, OSError) as exc:
            error_code = (
                exc.error_code
                if isinstance(exc, NotificationError)
                else f"state_{type(exc).__name__}"
            )
            self._log(
                {
                    "event_type": "astra_alert_failed",
                    "timestamp_utc": self.wall_clock(),
                    "error_code": error_code,
                    "new_match_count": len(unseen),
                    "safety": safety_evidence(0),
                },
            )
            return 0, 1
        self._log(
            {
                "event_type": "astra_alert_sent",
                "timestamp_utc": self.wall_clock(),
                "new_match_count": len(unseen),
                "receipt": receipt,
                "safety": safety_evidence(0),
            },
        )
        return 1, 0

    def _deliver(
        self,
        notifier: Notifier,
        unseen: Sequence[tuple[BrokerAccount, ModelMatch]],
        timestamp: str,
    ) -> JsonObject:
        receipt = notifier.notify(_alert_message(unseen, timestamp))
        delivered_keys: list[str] = []
        for account, match in unseen:
            delivered_keys.append(_match_key(account, match))
        self.alert_state.mark_delivered(delivered_keys)
        return receipt
