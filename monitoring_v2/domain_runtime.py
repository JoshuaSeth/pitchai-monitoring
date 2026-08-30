# Copyright (c) 2026 PitchAI. All rights reserved.
"""Typed adapters for established domain-monitoring runtime contracts."""

from __future__ import annotations

from collections.abc import Callable
from importlib import import_module
from typing import TYPE_CHECKING, NamedTuple, Protocol, cast

from .json_types import json_object

if TYPE_CHECKING:
    import asyncio
    from pathlib import Path

    import httpx

    from .browser_runtime import Browser
    from .json_types import JsonInput, JsonObject


class SelectorRequirement(NamedTuple):
    """Selector assertion exposed by an established domain check."""

    selector: str


class DomainCheckSpec(NamedTuple):
    """Read-only check shape consumed by monitoring v2 and its proof."""

    domain: str
    url: str
    allowed_status_codes: list[int] | None
    expected_title_contains: str | None
    expected_final_host_suffix: str | None
    expected_final_path: str | None
    required_selectors_all: list[SelectorRequirement]
    required_selectors_any: list[SelectorRequirement]
    required_text_all: list[str]
    forbidden_text_any: list[str]
    api_contract_checks: list[dict[str, object]]
    synthetic_transactions: list[dict[str, object]]
    browser_enabled: bool
    http_timeout_seconds: float


class DomainCheckResult(NamedTuple):
    """Result fields needed by inventory routing proof."""

    domain: str
    ok: bool


class AlertPolicy(NamedTuple):
    """Alert-routing fields consumed by the strict inventory proof."""

    telegram: str
    reason: str | None

    telegram_enabled: bool


class DomainEntry(NamedTuple):
    """Runtime domain entry fields used by alert-routing proof."""

    routes_telegram: bool


type AlertPolicyFactory = Callable[[str, str | None], AlertPolicy]
type DomainEntryFactory = Callable[[str, JsonInput, AlertPolicy], DomainEntry]


class _CheckOneDomain(Protocol):
    async def __call__(
        self,
        spec: DomainCheckSpec,
        client: httpx.AsyncClient,
        browser: Browser,
        *,
        browser_semaphore: asyncio.Semaphore,
    ) -> DomainCheckResult:
        """Execute one established domain check."""
        raise NotImplementedError

    def contract_name(self) -> str:
        """Return the adapter contract name."""
        raise NotImplementedError


class _CommonModule(NamedTuple):
    find_chromium_executable: Callable[[], str | None]
    load_domain_spec_from_module_dict: Callable[[JsonObject], DomainCheckSpec]


class _InventoryModule(NamedTuple):
    DomainAlertPolicy: AlertPolicyFactory
    parse_domain_alert_policy: Callable[[JsonObject], AlertPolicy]
    validate_domain_inventory: Callable[[JsonObject], None]


class _MainModule(NamedTuple):
    DomainEntryConfig: DomainEntryFactory
    browser_check: object
    check_one_domain: _CheckOneDomain
    http_get_check: object
    load_config: Callable[[Path], object]
    load_domain_spec: Callable[[JsonObject], DomainCheckSpec]


common_runtime = cast("_CommonModule", cast("object", import_module("domain_checks.common_check")))
inventory_runtime = cast("_InventoryModule", cast("object", import_module("domain_checks.inventory")))
monitoring_runtime = cast("_MainModule", cast("object", import_module("domain_checks.main")))


def load_domain_spec_from_module_dict(module_vars: JsonObject) -> DomainCheckSpec:
    """Load a domain specification through the established parser.

    Returns:
        The executable established domain-check contract.

    Raises:
        RuntimeError: If the established parser returns an empty domain.
    """
    specification = common_runtime.load_domain_spec_from_module_dict(module_vars)
    if not specification.domain:
        message = "established domain parser returned an empty domain"
        raise RuntimeError(message)
    return specification


def load_config(path: Path) -> JsonObject:
    """Load and normalize the established monitoring configuration.

    Returns:
        The normalized monitoring configuration.
    """
    loaded = cast("JsonInput", monitoring_runtime.load_config(path))
    return json_object(loaded)


def load_domain_spec(entry: JsonObject) -> DomainCheckSpec:
    """Load one established executable domain specification.

    Returns:
        The executable domain-check contract.

    Raises:
        RuntimeError: If the established inventory parser returns an empty domain.
    """
    specification = monitoring_runtime.load_domain_spec(entry)
    if not specification.domain:
        message = "established inventory parser returned an empty domain"
        raise RuntimeError(message)
    return specification


def domain_alert_policy(*, telegram: str, reason: str | None = None) -> AlertPolicy:
    """Construct one established domain alert-routing policy.

    Returns:
        The constructed alert-routing policy.

    Raises:
        RuntimeError: If the established policy changes the requested mode.
    """
    policy = inventory_runtime.DomainAlertPolicy(telegram, reason)
    if policy.telegram != telegram:
        message = "established alert policy changed the requested Telegram mode"
        raise RuntimeError(message)
    return policy


def domain_entry_config(
    *,
    domain: str,
    raw_entry: JsonInput,
    alert_policy: AlertPolicy,
) -> DomainEntry:
    """Construct one established runtime domain entry.

    Returns:
        The constructed runtime domain entry.

    Raises:
        RuntimeError: If the entry disagrees with the supplied alert policy.
    """
    domain_entry = monitoring_runtime.DomainEntryConfig(domain, raw_entry, alert_policy)
    if domain_entry.routes_telegram != alert_policy.telegram_enabled:
        message = "established domain entry changed the requested alert decision"
        raise RuntimeError(message)
    return domain_entry


async def check_one_domain(
    spec: DomainCheckSpec,
    client: httpx.AsyncClient,
    browser: Browser,
    *,
    browser_semaphore: asyncio.Semaphore,
) -> DomainCheckResult:
    """Exercise one established HTTP and browser check path.

    Returns:
        The established domain-check result.
    """
    return await monitoring_runtime.check_one_domain(
        spec,
        client,
        browser,
        browser_semaphore=browser_semaphore,
    )
