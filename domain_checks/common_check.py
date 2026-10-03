# Copyright (c) 2026 PitchAI. All rights reserved.
"""Public domain-spec and probe interface used by the native monitor and E2E callers."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, cast

from .browser_check import browser_check
from .browser_errors import is_browser_infra_error as _is_browser_infra_error
from .check_text import html_to_visible_text as _html_to_visible_text
from .check_text import normalize_text as _normalize_text
from .check_text import safe_url as _safe_url
from .http_check import http_get_check

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from .config_values import ConfigValue
    from .event_bus_delivery import JsonObject

__all__ = [
    "DEFAULT_MAINTENANCE_TEXT", "DomainCheckResult", "DomainCheckSpec", "SelectorCheck",
    "_compile_selector_list", "_default_selector_state", "_html_to_visible_text", "_is_browser_infra_error",
    "_normalize_text", "_safe_url", "browser_check", "find_chromium_executable", "http_get_check",
    "load_domain_spec_from_module_dict",
]

DEFAULT_MAINTENANCE_TEXT = [
    "maintenance", "temporarily unavailable", "we'll be back", "bad gateway", "service unavailable", "gateway timeout",
]


@dataclass(frozen=True)
class SelectorCheck:
    """One selector with Playwright's state validation retained at the wait boundary."""

    selector: str
    state: str = "visible"


@dataclass(frozen=True)
class _DomainTarget:
    """Original initial fields identify the target and required selectors."""

    domain: str
    url: str
    allowed_status_codes: list[int] | None = None
    expected_title_contains: str | None = None
    expected_final_host_suffix: str | None = None
    required_selectors_all: list[SelectorCheck] = field(default_factory=list)
    required_selectors_any: list[SelectorCheck] = field(default_factory=list)


@dataclass(frozen=True)
class _DomainContent(_DomainTarget):
    """Original middle fields retain independent lists and extended-check mappings."""

    required_text_all: list[str] = field(default_factory=list)
    forbidden_text_any: list[str] = field(default_factory=lambda: list(DEFAULT_MAINTENANCE_TEXT))
    capture_headers: list[str] = field(default_factory=list)
    api_contract_checks: list[JsonObject] = field(default_factory=list)
    synthetic_transactions: list[JsonObject] = field(default_factory=list)
    web_vitals: JsonObject = field(default_factory=dict)
    proxy: JsonObject = field(default_factory=dict)


@dataclass(frozen=True)
class DomainCheckSpec(_DomainContent):
    """Original ordered constructor fields and independent mutable default values."""

    browser_enabled: bool = True
    http_timeout_seconds: float = 15.0
    browser_timeout_seconds: float = 25.0


@dataclass(frozen=True)
class DomainCheckResult:
    """One domain's original product result and JSON details."""

    domain: str
    ok: bool
    reason: str
    details: JsonObject


type CheckValue = ConfigValue | SelectorCheck | list[CheckValue] | dict[str, CheckValue]


def _default_selector_state(selector: str) -> str:
    selected = selector.lstrip()
    if selected.startswith(("meta", "script", "link", "title")):
        return "attached"
    return "visible"


def _compile_selector_list(items: Iterable[CheckValue]) -> list[SelectorCheck]:
    checks: list[SelectorCheck] = []
    for item in items:
        if isinstance(item, SelectorCheck):
            checks.append(item)
        elif isinstance(item, str):
            checks.append(SelectorCheck(selector=item, state=_default_selector_state(item)))
        elif isinstance(item, dict) and "selector" in item:
            selector = str(item["selector"])
            checks.append(SelectorCheck(selector, str(item.get("state") or _default_selector_state(selector))))
        else:
            message = f"Invalid selector check: {item!r}"
            raise ValueError(message)
    return checks


def _status_codes(raw: CheckValue) -> list[int] | None:
    if raw is None:
        return None
    if not isinstance(raw, list) or not raw:
        message = "allowed_status_codes must be a non-empty list of ints"
        raise ValueError(message)
    return [int(cast("str | bytes | int | float", value)) for value in raw]


def load_domain_spec_from_module_dict(module_vars: Mapping[str, CheckValue]) -> DomainCheckSpec:
    """Load the existing CHECK fields without copying the optional extended mappings.

    Returns:
        A spec with the same conversions, defaults and optional mapping identities.

    Raises:
        ValueError: CHECK, selector entries or the status-code list are invalid.
    """
    if "CHECK" not in module_vars or not isinstance(module_vars["CHECK"], dict):
        message = "Domain check module must define a dict named CHECK"
        raise ValueError(message)
    cfg = module_vars["CHECK"]
    required_all = _compile_selector_list(cast("Iterable[CheckValue]", cfg.get("required_selectors_all", [])))
    required_any = _compile_selector_list(cast("Iterable[CheckValue]", cfg.get("required_selectors_any", [])))
    forbidden = cfg.get("forbidden_text_any", None)
    if forbidden is None:
        forbidden = list(DEFAULT_MAINTENANCE_TEXT)
    allowed = _status_codes(cfg.get("allowed_status_codes", None))
    return DomainCheckSpec(
        domain=str(cfg["domain"]), url=str(cfg["url"]), allowed_status_codes=allowed,
        expected_title_contains=cast("str | None", cfg.get("expected_title_contains")),
        expected_final_host_suffix=cast("str | None", cfg.get("expected_final_host_suffix")),
        required_selectors_all=required_all, required_selectors_any=required_any,
        required_text_all=[str(text) for text in cast("Iterable[CheckValue]", cfg.get("required_text_all", []))],
        forbidden_text_any=[str(text) for text in cast("Iterable[CheckValue]", forbidden)],
        capture_headers=[str(header) for header in cast("Iterable[CheckValue]", cfg.get("capture_headers") or [])],
        api_contract_checks=cast("list[JsonObject]", cfg.get("api_contract_checks"))
        if isinstance(cfg.get("api_contract_checks"), list) else [],
        synthetic_transactions=cast("list[JsonObject]", cfg.get("synthetic_transactions"))
        if isinstance(cfg.get("synthetic_transactions"), list) else [],
        web_vitals=cast("JsonObject", cfg.get("web_vitals")) if isinstance(cfg.get("web_vitals"), dict) else {},
        proxy=cast("JsonObject", cfg.get("proxy")) if isinstance(cfg.get("proxy"), dict) else {},
        browser_enabled=bool(cfg.get("browser_enabled", True)),
        http_timeout_seconds=float(cast("str | int | float", cfg.get("http_timeout_seconds", 15.0))),
        browser_timeout_seconds=float(cast("str | int | float", cfg.get("browser_timeout_seconds", 25.0))),
    )


def find_chromium_executable() -> str | None:
    """Return the existing environment override or first existing Chromium candidate."""
    env_path = os.getenv("CHROMIUM_PATH")
    if env_path and Path(env_path).exists():
        return env_path
    candidates = [
        "/usr/bin/chromium", "/usr/bin/chromium-browser", "/usr/bin/google-chrome", "/usr/bin/google-chrome-stable",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    ]
    for path in candidates:
        if Path(path).exists():
            return path
    return None
