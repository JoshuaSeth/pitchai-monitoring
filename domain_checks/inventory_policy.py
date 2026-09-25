# Copyright (c) 2026 PitchAI. All rights reserved.
"""Per-domain alert routing policy."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
    from domain_checks.types import JsonObject

_TELEGRAM_ALERT_MODES = {"critical", "dashboard-only"}


class DomainAlertPolicyPayload(TypedDict):
    """Represent dashboard-ready alert routing metadata."""

    telegram: str
    telegram_enabled: bool
    reason: str | None


@dataclass(frozen=True)
class DomainAlertPolicy:
    """Define Telegram routing for one domain."""

    telegram: str
    reason: str | None = None

    @property
    def telegram_enabled(self) -> bool:
        """Return whether critical Telegram alerts are enabled."""
        return self.telegram == "critical"

    def to_dashboard_dict(self) -> DomainAlertPolicyPayload:
        """Return dashboard-ready alert policy metadata."""
        return {
            "telegram": self.telegram,
            "telegram_enabled": self.telegram_enabled,
            "reason": self.reason,
        }


def required_inventory_text(mapping: JsonObject, key: str, path: str) -> str:
    """Return a required, stripped inventory string or fail with its path.

    Raises:
        ValueError: The required value is missing or empty.
    """
    value = str(mapping.get(key) or "").strip()
    if not value:
        message = f"{path}.{key} is required"
        raise ValueError(message)
    return value


def parse_domain_alert_policy(
    raw_domain: JsonObject | None,
    *,
    path: str = "domain",
) -> DomainAlertPolicy:
    """Parse a domain's explicit alert-routing contract.

    Returns:
        The validated alert policy.

    Raises:
        TypeError: The alert policy is not a mapping.
        ValueError: The alert policy contains invalid or incomplete values.
    """
    if raw_domain is None or raw_domain.get("alert_policy") is None:
        return DomainAlertPolicy(telegram="critical")
    raw_policy = raw_domain.get("alert_policy")
    policy_path = f"{path}.alert_policy"
    if not isinstance(raw_policy, dict):
        message = f"{policy_path} must be a mapping"
        raise TypeError(message)
    telegram = required_inventory_text(raw_policy, "telegram", policy_path)
    if telegram not in _TELEGRAM_ALERT_MODES:
        message = f"{policy_path}.telegram must be one of {sorted(_TELEGRAM_ALERT_MODES)}"
        raise ValueError(message)
    reason = str(raw_policy.get("reason") or "").strip() or None
    if telegram == "dashboard-only" and reason is None:
        message = f"{policy_path}.reason is required for dashboard-only domains"
        raise ValueError(message)
    return DomainAlertPolicy(telegram=telegram, reason=reason)
