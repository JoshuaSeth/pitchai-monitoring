# Copyright (c) 2026 PitchAI. All rights reserved.
"""Domain inventory parsing, plugin loading, and alert routing."""

from __future__ import annotations

import logging
import runpy
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, cast

import yaml

from domain_checks.common_check import load_domain_spec_from_module_dict
from domain_checks.inventory import DomainAlertPolicy, parse_domain_alert_policy
from domain_checks.monitor_values import json_float

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence
    from datetime import tzinfo

    import httpx

    from domain_checks.common_check import DomainCheckSpec
    from domain_checks.telegram import TelegramConfig
    from domain_checks.types import JsonObject, JsonValue

    ChunkSender = Callable[
        [httpx.AsyncClient, TelegramConfig, str],
        Awaitable[tuple[bool, list[JsonObject]]],
    ]

LOGGER = logging.getLogger("service-monitoring")


def load_config(path: Path) -> JsonObject:
    """Load a strict mapping-valued YAML monitor configuration.

    Returns:
        The loaded configuration object.

    Raises:
        ValueError: The YAML root is not a mapping.
    """
    with path.open(encoding="utf-8") as config_file:
        data = cast("JsonValue", yaml.safe_load(config_file))
    if data is None:
        return {}
    if isinstance(data, dict):
        return data
    message = "Config YAML must be a mapping"
    raise ValueError(message)


@dataclass(frozen=True)
class DomainEntryConfig:
    """Describe a configured domain and its operational policy."""

    domain: str
    raw_entry: str | JsonObject
    alert_policy: DomainAlertPolicy = field(default_factory=lambda: DomainAlertPolicy(telegram="critical"))
    disabled: bool = False
    disabled_reason: str | None = None
    disabled_until_ts: float | None = None

    def is_disabled(self, now_ts: float) -> bool:
        """Return whether the domain must be skipped at the supplied time."""
        return self.disabled or bool(self.disabled_until_ts is not None and now_ts < self.disabled_until_ts)

    @property
    def routes_telegram(self) -> bool:
        """Return whether critical Telegram routing is enabled."""
        return self.alert_policy.telegram_enabled


async def route_domain_telegram_alert(
    *,
    http_client: httpx.AsyncClient,
    telegram_cfg: TelegramConfig,
    entry: DomainEntryConfig,
    message: str,
    send_chunks: ChunkSender,
) -> tuple[bool, list[JsonObject]] | None:
    """Route a domain alert according to its inventory policy.

    Returns:
        The Telegram delivery result, or ``None`` when routing is disabled.
    """
    if not entry.routes_telegram:
        LOGGER.info(
            "Telegram alert suppressed by inventory policy domain=%s mode=%s reason=%s",
            entry.domain,
            entry.alert_policy.telegram,
            entry.alert_policy.reason,
        )
        return None
    return await send_chunks(http_client, telegram_cfg, message)


def parse_disabled_until_ts(value: JsonValue) -> float | None:
    """Parse an optional positive timestamp or ISO-8601 date/time.

    Returns:
        A Unix timestamp, or ``None`` when the setting is absent or non-positive.

    Raises:
        ValueError: The supplied value is not a timestamp or ISO-8601 value.
    """
    if value is None:
        return None
    if isinstance(value, int | float):
        timestamp = json_float(value)
        return timestamp if timestamp > 0 else None
    text = str(value).strip()
    if not text:
        return None
    try:
        timestamp = json_float(text)
    except ValueError:
        timestamp = 0.0
    else:
        return timestamp if timestamp > 0 else None
    iso_text = f"{text[:-1]}+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(iso_text)
    except ValueError:
        try:
            parsed_date = date.fromisoformat(text)
        except ValueError as exc:
            message = f"Invalid disabled_until value {value!r}; expected unix timestamp or ISO-8601 datetime/date"
            raise ValueError(message) from exc
        parsed = datetime(parsed_date.year, parsed_date.month, parsed_date.day, tzinfo=UTC)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.timestamp()


def _entry_config(entry: JsonValue, index: int) -> DomainEntryConfig:
    if isinstance(entry, str):
        domain = entry.strip()
        if domain:
            return DomainEntryConfig(domain=domain, raw_entry=domain)
        message = f"domains[{index}] is empty"
        raise ValueError(message)
    if not isinstance(entry, dict):
        message = f"domains[{index}] must be a string or mapping, got {type(entry).__name__}"
        raise TypeError(message)
    domain = str(entry.get("domain") or "").strip()
    if not domain:
        message = f"domains[{index}].domain is required"
        raise ValueError(message)
    return DomainEntryConfig(
        domain=domain,
        raw_entry=entry,
        alert_policy=parse_domain_alert_policy(entry, path=f"domains[{index}]"),
        disabled=bool(entry.get("disabled")) or entry.get("enabled") is False,
        disabled_reason=str(entry.get("disabled_reason") or "").strip() or None,
        disabled_until_ts=parse_disabled_until_ts(entry.get("disabled_until")),
    )


def normalize_domain_entries(domains_cfg: Sequence[JsonValue]) -> list[DomainEntryConfig]:
    """Normalize and validate the configured domain inventory.

    Returns:
        The validated domain entries in configuration order.

    Raises:
        ValueError: A domain entry is incomplete or duplicated.
    """
    entries: list[DomainEntryConfig] = []
    for index, raw_entry in enumerate(domains_cfg):
        entries.append(_entry_config(raw_entry, index))
    seen: set[str] = set()
    for entry in entries:
        if entry.domain in seen:
            message = f"Duplicate domain entry: {entry.domain}"
            raise ValueError(message)
        seen.add(entry.domain)
    return entries


def format_disabled_domain_line(entry: DomainEntryConfig, timezone: tzinfo) -> str:
    """Format one disabled-domain heartbeat line.

    Returns:
        The formatted heartbeat line.
    """
    parts = ["DISABLED"]
    if entry.disabled_until_ts is not None and entry.disabled_until_ts > 0:
        until = datetime.fromtimestamp(entry.disabled_until_ts, tz=timezone)
        parts.append(f"until {until.strftime('%Y-%m-%d %H:%M %Z')}")
    if entry.disabled_reason:
        parts.append(f"({entry.disabled_reason})")
    return f"- {entry.domain}: {' '.join(parts)}"


def load_domain_spec(domain_entry: str | JsonObject) -> DomainCheckSpec:
    """Load a domain check from its plugin or explicit inline contract.

    Returns:
        The validated domain check specification.

    Raises:
        FileNotFoundError: Neither a plugin nor an inline contract exists.
    """
    if isinstance(domain_entry, str):
        domain = domain_entry
        inline_check = None
    else:
        domain = str(domain_entry["domain"])
        inline_value = domain_entry.get("check")
        inline_check = inline_value if isinstance(inline_value, dict) else None
    plugin_path = Path(__file__).parent / domain / "check.py"
    if plugin_path.exists():
        check_value = cast("JsonValue", runpy.run_path(str(plugin_path)).get("CHECK"))
        return load_domain_spec_from_module_dict({"CHECK": check_value})
    if inline_check is not None:
        return load_domain_spec_from_module_dict({"CHECK": {"domain": domain, **inline_check}})
    message = f"Missing domain check module for {domain}: expected {plugin_path} (or inline 'check' in config.yaml)"
    raise FileNotFoundError(message)
