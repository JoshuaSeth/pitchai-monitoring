from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


UTC = timezone.utc
_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]")


class PayloadError(RuntimeError):
    """A broker or provider payload did not satisfy the protection contract."""


def utc_now() -> datetime:
    return datetime.now(tz=UTC)


def utc_iso(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("UTC timestamp must be timezone-aware")
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def parse_timestamp(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise PayloadError(f"{field_name} must be a non-empty RFC3339 timestamp")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise PayloadError(f"{field_name} is not a valid RFC3339 timestamp") from exc
    if parsed.tzinfo is None:
        raise PayloadError(f"{field_name} must include a timezone")
    return parsed.astimezone(UTC)


def stable_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def safe_label(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PayloadError("broker account label must be present")
    normalized = _CONTROL_CHARACTERS.sub(" ", value.strip())
    return normalized[:240]


@dataclass(frozen=True)
class AccountDescriptor:
    broker_account_id: str = field(repr=False)
    label: str
    enabled: bool
    priority: int | None = None

    @property
    def account_ref(self) -> str:
        return stable_hash(self.broker_account_id)

    @classmethod
    def from_broker(cls, payload: object) -> "AccountDescriptor":
        if not isinstance(payload, dict):
            raise PayloadError("broker account entry must be an object")
        metadata = payload.get("metadata")
        if not isinstance(metadata, dict):
            raise PayloadError("broker account metadata must be an object")
        account_id = metadata.get("account_id")
        if not isinstance(account_id, str) or not account_id.strip():
            raise PayloadError("broker account metadata is missing account_id")
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
    access_token: str = field(repr=False)
    account_id: str = field(repr=False)


@dataclass(frozen=True)
class ResetCredit:
    provider_id: str = field(repr=False)
    reset_type: str
    status: str
    granted_at: datetime
    expires_at: datetime | None
    title: str | None
    supported_by_plan: bool | None

    @property
    def credit_ref(self) -> str:
        return stable_hash(self.provider_id)

    @property
    def is_redeemable(self) -> bool:
        return (
            self.status == "available"
            and self.reset_type == "codex_rate_limits"
            and self.supported_by_plan is not False
            and self.expires_at is not None
        )

    def sanitized(self) -> dict[str, Any]:
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
    def from_provider(cls, payload: object) -> "ResetCredit":
        if not isinstance(payload, dict):
            raise PayloadError("provider credit entry must be an object")
        provider_id = payload.get("id")
        if not isinstance(provider_id, str) or not provider_id.strip():
            raise PayloadError("provider credit entry is missing its opaque id")
        reset_type = payload.get("reset_type")
        status = payload.get("status")
        if not isinstance(reset_type, str) or not reset_type.strip():
            raise PayloadError("provider credit entry is missing reset_type")
        if not isinstance(status, str) or not status.strip():
            raise PayloadError("provider credit entry is missing status")
        raw_expiry = payload.get("expires_at")
        expiry = (
            parse_timestamp(raw_expiry, field_name="credit.expires_at")
            if raw_expiry is not None
            else None
        )
        raw_title = payload.get("title")
        title = safe_label(raw_title) if isinstance(raw_title, str) and raw_title.strip() else None
        supported = payload.get("is_supported_by_plan")
        supported_by_plan = supported if isinstance(supported, bool) else None
        return cls(
            provider_id=provider_id.strip(),
            reset_type=reset_type.strip(),
            status=status.strip(),
            granted_at=parse_timestamp(payload.get("granted_at"), field_name="credit.granted_at"),
            expires_at=expiry,
            title=title,
            supported_by_plan=supported_by_plan,
        )


@dataclass(frozen=True)
class AccountObservation:
    descriptor: AccountDescriptor
    captured_at: datetime
    broker_state: dict[str, Any]
    usage_state: dict[str, Any]
    available_count: int
    credits: tuple[ResetCredit, ...]
    credentials: ProviderCredentials | None = field(default=None, repr=False, compare=False)

    def sanitized(self) -> dict[str, Any]:
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
        return next((credit for credit in self.credits if credit.credit_ref == credit_ref), None)


@dataclass(frozen=True)
class ConsumeResult:
    code: str
    windows_reset: int

    @classmethod
    def from_provider(cls, payload: object) -> "ConsumeResult":
        if not isinstance(payload, dict):
            raise PayloadError("provider consume response must be an object")
        code = payload.get("code")
        if code not in {"reset", "nothing_to_reset", "no_credit", "already_redeemed"}:
            raise PayloadError("provider consume response contains an unsupported code")
        raw_windows = payload.get("windows_reset", 0)
        if isinstance(raw_windows, bool) or not isinstance(raw_windows, int) or raw_windows < 0:
            raise PayloadError("provider consume response windows_reset must be a non-negative integer")
        return cls(code=code, windows_reset=raw_windows)
