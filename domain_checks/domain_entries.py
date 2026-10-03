# Copyright (c) 2026 PitchAI. All rights reserved.
"""Typed inventory entries with existing disablement and routing policy."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from .domain_time import parse_disabled_until_ts
from .inventory import DomainAlertPolicy, parse_domain_alert_policy

if TYPE_CHECKING:
    from datetime import tzinfo

    from .config_values import ConfigValue

_DEFAULT_POLICY = DomainAlertPolicy(telegram="critical")


@dataclass(frozen=True)
class DomainEntryConfig:
    """One inventory entry, retaining the original raw mapping by reference."""

    domain: str
    raw_entry: str | dict[str, ConfigValue]
    alert_policy: DomainAlertPolicy = _DEFAULT_POLICY
    disabled: bool = False
    disabled_reason: str | None = None
    disabled_until_ts: float | None = None

    def is_disabled(self, now_ts: float) -> bool:
        """Return whether the explicit stop or not-yet-elapsed expiry applies."""
        if self.disabled:
            return True
        return self.disabled_until_ts is not None and now_ts < float(self.disabled_until_ts)

    @property
    def routes_telegram(self) -> bool:
        """Return the same inventory-owned alert audience decision."""
        return self.alert_policy.telegram_enabled


def normalize_domain_entries(domains_cfg: list[ConfigValue]) -> list[DomainEntryConfig]:
    """Retain order and raw values while rejecting empty or duplicate domains.

    Returns:
        Entries with parsed expiry and the established alert policy.

    Raises:
        ValueError: An input entry or domain identity is invalid.
    """
    entries: list[DomainEntryConfig] = []
    for index, entry in enumerate(domains_cfg):
        match entry:
            case str():
                domain = entry.strip()
                if not domain:
                    message = f"domains[{index}] is empty"
                    raise ValueError(message)
                entries.append(DomainEntryConfig(domain=domain, raw_entry=domain))
            case dict():
                entries.append(_mapping_entry(entry, index))
            case _:
                message = f"domains[{index}] must be a string or mapping, got {type(entry).__name__}"
                raise ValueError(message)
    seen: set[str] = set()
    for parsed_entry in entries:
        if parsed_entry.domain in seen:
            message = f"Duplicate domain entry: {parsed_entry.domain}"
            raise ValueError(message)
        seen.add(parsed_entry.domain)
    return entries


def _mapping_entry(entry: dict[str, ConfigValue], index: int) -> DomainEntryConfig:
    domain = str(entry.get("domain") or "").strip()
    if not domain:
        message = f"domains[{index}].domain is required"
        raise ValueError(message)
    disabled = bool(entry.get("disabled")) or (entry.get("enabled") is False)
    reason = str(entry.get("disabled_reason") or "").strip() or None
    until = parse_disabled_until_ts(entry.get("disabled_until"))
    policy = parse_domain_alert_policy(entry, path=f"domains[{index}]")
    return DomainEntryConfig(domain, entry, policy, disabled, reason, until)


def format_disabled_domain_line(entry: DomainEntryConfig, tz: tzinfo | None) -> str:
    """Return the existing display without changing whether the entry is stopped."""
    parts = ["DISABLED"]
    if entry.disabled_until_ts is not None and float(entry.disabled_until_ts) > 0:
        until = datetime.fromtimestamp(float(entry.disabled_until_ts), tz=tz)
        parts.append(f"until {until.strftime('%Y-%m-%d %H:%M %Z')}")
    if entry.disabled_reason:
        parts.append(f"({entry.disabled_reason})")
    return f"- {entry.domain}: {' '.join(parts)}"
