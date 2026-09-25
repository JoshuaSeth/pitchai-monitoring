# Copyright (c) 2026 PitchAI. All rights reserved.
"""Define validated domain models for guardian provider payloads."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .consume_result import ConsumeResult
from .model_values import (
    PayloadError,
    parse_timestamp,
    safe_label,
    utc_iso,
    utc_now,
)

if TYPE_CHECKING:
    from datetime import datetime

    from .json_contract import JsonObject, JsonValue

__all__ = [
    "AccountDescriptor",
    "AccountObservation",
    "ConsumeResult",
    "PayloadError",
    "ProviderCredentials",
    "ResetCredit",
    "parse_timestamp",
    "safe_label",
    "stable_hash",
    "utc_iso",
    "utc_now",
]


def stable_hash(value: str) -> str:
    """Hash one secret-bearing provider identifier into a stable reference.

    Returns:
        The resulting text.

    """
    digest = hashlib.sha256(value.encode("utf-8"))
    return digest.hexdigest()


@dataclass(frozen=True)
class AccountDescriptor:
    """Represent AccountDescriptor."""

    broker_account_id: str = field(repr=False)
    label: str
    enabled: bool
    priority: int | None = None

    @property
    def account_ref(self) -> str:
        """Handle account ref."""
        return stable_hash(self.broker_account_id)

    @classmethod
    def from_broker(cls, payload: JsonValue) -> AccountDescriptor:
        """Build from broker.

        Returns:
            The resulting value.

        Raises:
            PayloadError: If provider data violates the payload contract.

        """
        if not isinstance(payload, dict):
            msg = "broker account entry must be an object"
            raise PayloadError(msg)
        metadata = payload.get("metadata")
        if not isinstance(metadata, dict):
            msg = "broker account metadata must be an object"
            raise PayloadError(msg)
        account_id = metadata.get("account_id")
        if not isinstance(account_id, str) or not account_id.strip():
            msg = "broker account metadata is missing account_id"
            raise PayloadError(msg)
        raw_priority = metadata.get("priority")
        priority = raw_priority if isinstance(raw_priority, int) and not isinstance(raw_priority, bool) else None
        return cls(
            broker_account_id=account_id.strip(),
            label=safe_label(metadata.get("label")),
            enabled=bool(metadata.get("enabled", True)),
            priority=priority,
        )


@dataclass(frozen=True)
class ProviderCredentials:
    """Represent ProviderCredentials."""

    access_token: str = field(repr=False)
    account_id: str = field(repr=False)


@dataclass(frozen=True)
class ResetCredit:
    """Represent ResetCredit."""

    provider_id: str = field(repr=False)
    reset_type: str
    status: str
    granted_at: datetime
    expires_at: datetime | None
    title: str | None
    supported_by_plan: bool | None

    @property
    def credit_ref(self) -> str:
        """Handle credit ref."""
        return stable_hash(self.provider_id)

    @property
    def is_redeemable(self) -> bool:
        """Return whether is redeemable."""
        return (
            self.status == "available"
            and self.reset_type == "codex_rate_limits"
            and self.supported_by_plan is not False
            and self.expires_at is not None
        )

    def sanitized(self) -> JsonObject:
        """Return sanitized."""
        return {
            "credit_ref": self.credit_ref,
            "reset_type": self.reset_type,
            "status": self.status,
            "granted_at": utc_iso(self.granted_at),
            "expires_at": utc_iso(self.expires_at) if self.expires_at else None,
            "title": self.title,
            "supported_by_plan": self.supported_by_plan,
            "redeemable": self.is_redeemable,
        }

    @classmethod
    def from_provider(cls, payload: JsonValue) -> ResetCredit:
        """Build from provider.

        Returns:
            The resulting value.

        Raises:
            PayloadError: If provider data violates the payload contract.

        """
        if not isinstance(payload, dict):
            msg = "provider credit entry must be an object"
            raise PayloadError(msg)
        provider_id = payload.get("id")
        if not isinstance(provider_id, str) or not provider_id.strip():
            msg = "provider credit entry is missing its opaque id"
            raise PayloadError(msg)
        reset_type = payload.get("reset_type")
        status = payload.get("status")
        if not isinstance(reset_type, str) or not reset_type.strip():
            msg = "provider credit entry is missing reset_type"
            raise PayloadError(msg)
        if not isinstance(status, str) or not status.strip():
            msg = "provider credit entry is missing status"
            raise PayloadError(msg)
        raw_expiry = payload.get("expires_at")
        expiry = parse_timestamp(raw_expiry, field_name="credit.expires_at") if raw_expiry is not None else None
        raw_title = payload.get("title")
        title = safe_label(raw_title) if isinstance(raw_title, str) and raw_title.strip() else None
        supported = payload.get("is_supported_by_plan")
        supported_by_plan = supported if isinstance(supported, bool) else None
        return cls(
            provider_id=provider_id.strip(),
            reset_type=reset_type.strip(),
            status=status.strip(),
            granted_at=parse_timestamp(
                payload.get("granted_at"),
                field_name="credit.granted_at",
            ),
            expires_at=expiry,
            title=title,
            supported_by_plan=supported_by_plan,
        )


@dataclass(frozen=True)
class AccountObservation:
    """Represent AccountObservation."""

    descriptor: AccountDescriptor
    captured_at: datetime
    broker_state: JsonObject
    usage_state: JsonObject
    available_count: int
    credits: tuple[ResetCredit, ...]
    credentials: ProviderCredentials | None = field(
        default=None,
        repr=False,
        compare=False,
    )

    def sanitized(self) -> JsonObject:
        """Return sanitized."""
        return {
            "account_ref": self.descriptor.account_ref,
            "account_label": self.descriptor.label,
            "enabled": self.descriptor.enabled,
            "priority": self.descriptor.priority,
            "captured_at": utc_iso(self.captured_at),
            "broker_state": self.broker_state,
            "usage_state": self.usage_state,
            "available_count": self.available_count,
            "credits": [credit.sanitized() for credit in self.credits],
        }

    def find_credit(self, credit_ref: str) -> ResetCredit | None:
        """Return find credit."""
        return next(
            (credit for credit in self.credits if credit.credit_ref == credit_ref),
            None,
        )
