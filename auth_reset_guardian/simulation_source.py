# Copyright (c) 2026 PitchAI. All rights reserved.
"""Provide deterministic in-memory guardian simulations."""

from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING, override

from .broker_payload import parse_credit_inventory, sanitize_usage
from .client_http import AccountScanError, GuardianSource
from .json_contract import decode_json
from .model_values import utc_now
from .models import (
    AccountDescriptor,
    AccountObservation,
    ConsumeResult,
    PayloadError,
    safe_label,
)
from .simulation_inventory import (
    next_simulation_outcome,
    remove_simulation_credit,
    required_simulation_object,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime
    from pathlib import Path

    from .json_contract import JsonObject
    from .models import (
        ResetCredit,
    )


class SimulationSource(GuardianSource):
    """Exercise expiry and redemption behavior without a network."""

    def __init__(
        self,
        fixture: JsonObject,
        *,
        clock: Callable[[], datetime] | None = None,
    ):
        """Initialize this instance.

        Raises:
            PayloadError: If provider data violates the payload contract.

        """
        raw_accounts = fixture.get("accounts")
        if not isinstance(raw_accounts, list):
            msg = "simulation fixture must contain an accounts list"
            raise PayloadError(msg)
        accounts: list[JsonObject] = []
        for raw_account in raw_accounts:
            if not isinstance(raw_account, dict):
                msg = "simulation account must be an object"
                raise PayloadError(msg)
            accounts.append(deepcopy(raw_account))
        self._accounts: list[JsonObject] = accounts
        self._clock: Callable[[], datetime] = clock or utc_now
        self.consume_calls: list[dict[str, str]] = []
        self.refresh_calls: dict[str, int] = {}

    @classmethod
    def from_path(
        cls,
        path: Path,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> SimulationSource:
        """Build a simulation from one JSON fixture path.

        Returns:
            The resulting value.

        Raises:
            PayloadError: If provider data violates the payload contract.

        """
        payload = decode_json(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            msg = "simulation fixture root must be an object"
            raise PayloadError(msg)
        return cls(payload, clock=clock)

    @override
    def list_accounts(self) -> list[AccountDescriptor]:
        """Return deterministic simulation account descriptors."""
        descriptors: list[AccountDescriptor] = []
        for index, account in enumerate(self._accounts):
            label = safe_label(account.get("label"))
            descriptors.append(
                AccountDescriptor(
                    broker_account_id=f"simulation:{index}:{label}",
                    label=label,
                    enabled=bool(account.get("enabled", True)),
                    priority=index,
                ),
            )
        return descriptors

    @override
    def refresh_account(self, descriptor: AccountDescriptor) -> AccountObservation:
        """Refresh one deterministic account observation.

        Returns:
            The resulting value.

        Raises:
            AccountScanError: If the operation violates its documented contract.

        """
        account = self._find(descriptor)
        refresh_count = self.refresh_calls.get(descriptor.account_ref, 0) + 1
        self.refresh_calls[descriptor.account_ref] = refresh_count
        fail_on_refresh = account.get("fail_on_refresh")
        if isinstance(fail_on_refresh, int) and refresh_count >= fail_on_refresh:
            raise AccountScanError(
                descriptor=descriptor,
                error_code="simulation_refresh_failure",
                broker_state={"availability": "unknown"},
            )
        credit_payload = required_simulation_object(
            account,
            "credit_inventory",
            context="simulation account",
        )
        available_count, reset_credits = parse_credit_inventory(credit_payload)
        usage = required_simulation_object(
            account,
            "usage",
            context="simulation account",
        )
        broker_state: JsonObject = {
            "availability": str(account.get("broker_availability", "available")),
        }
        return AccountObservation(
            descriptor=descriptor,
            captured_at=self._clock(),
            broker_state=broker_state,
            usage_state=sanitize_usage(usage),
            available_count=available_count,
            credits=reset_credits,
            credentials=None,
        )

    @override
    def consume_credit(
        self,
        observation: AccountObservation,
        credit: ResetCredit,
        idempotency_key: str,
    ) -> ConsumeResult:
        """Consume one simulated reset credit.

        Returns:
            The resulting value.

        """
        account = self._find(observation.descriptor)
        self.consume_calls.append(
            {
                "account_ref": observation.descriptor.account_ref,
                "credit_ref": credit.credit_ref,
                "provider_id": credit.provider_id,
                "idempotency_key": idempotency_key,
            },
        )
        raw_outcome = next_simulation_outcome(account, credit.provider_id)
        result = ConsumeResult.from_provider(raw_outcome)
        if result.code in {"reset", "already_redeemed", "no_credit"}:
            inventory = required_simulation_object(
                account,
                "credit_inventory",
                context="simulation account",
            )
            remove_simulation_credit(
                inventory,
                credit.provider_id,
                count_available_only=True,
            )
        return result

    def remove_credit_before_next_refresh(
        self,
        *,
        label: str,
        provider_id: str,
    ) -> None:
        """Remove one exact credit before the next simulated refresh."""
        account = self._find_by_label(label)
        inventory = required_simulation_object(
            account,
            "credit_inventory",
            context="simulation account",
        )
        remove_simulation_credit(
            inventory,
            provider_id,
            count_available_only=False,
        )

    def _find(self, descriptor: AccountDescriptor) -> JsonObject:
        return self._find_by_label(descriptor.label)

    def _find_by_label(self, label: str) -> JsonObject:
        for account in self._accounts:
            if account.get("label") == label:
                return account
        msg = "simulation label has no matching account"
        raise PayloadError(msg)
