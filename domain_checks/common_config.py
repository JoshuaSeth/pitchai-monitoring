# Copyright (c) 2026 PitchAI. All rights reserved.
"""Strict configuration loading for domain checks."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from domain_checks.common_models import (
    DEFAULT_MAINTENANCE_TEXT,
    DomainCheckSpec,
    SelectorCheck,
)

if TYPE_CHECKING:
    from domain_checks.common_models import (
        SelectorState,
    )
    from domain_checks.types import JsonObject, JsonValue


def _default_selector_state(selector: str) -> SelectorState:
    selector_without_space = selector.lstrip()
    if selector_without_space.startswith(("meta", "script", "link", "title")):
        return "attached"
    return "visible"


def _selector_state(value: JsonValue, *, default: SelectorState) -> SelectorState:
    if value is None:
        return default
    if value in {"attached", "detached", "hidden", "visible"}:
        return cast("SelectorState", value)
    message = f"Invalid selector state: {value!r}"
    raise ValueError(message)


def _selector_check(item: JsonValue) -> SelectorCheck:
    if isinstance(item, str):
        return SelectorCheck(selector=item, state=_default_selector_state(item))
    if isinstance(item, dict) and "selector" in item:
        selector = str(item["selector"])
        return SelectorCheck(
            selector=selector,
            state=_selector_state(
                item.get("state"),
                default=_default_selector_state(selector),
            ),
        )
    message = f"Invalid selector check: {item!r}"
    raise ValueError(message)


def _compile_selector_list(value: JsonValue) -> list[SelectorCheck]:
    if not isinstance(value, list):
        message = "Selector checks must be a list"
        raise TypeError(message)
    return [_selector_check(item) for item in value]


def _string_list(value: JsonValue, *, setting: str) -> list[str]:
    if not isinstance(value, list):
        message = f"{setting} must be a list"
        raise TypeError(message)
    strings: list[str] = []
    for item in value:
        if not isinstance(item, str):
            message = f"{setting} must contain only strings"
            raise TypeError(message)
        strings.append(item)
    return strings


def _object_list(value: JsonValue, *, setting: str) -> list[JsonObject]:
    if not isinstance(value, list):
        message = f"{setting} must be a list"
        raise TypeError(message)
    objects: list[JsonObject] = []
    for item in value:
        if not isinstance(item, dict):
            message = f"{setting} must contain only mappings"
            raise TypeError(message)
        objects.append(item)
    return objects


def _object_setting(value: JsonValue, *, setting: str) -> JsonObject:
    if not isinstance(value, dict):
        message = f"{setting} must be a mapping"
        raise TypeError(message)
    return value


def _optional_text(value: JsonValue, *, setting: str) -> str | None:
    if value is None or isinstance(value, str):
        return value
    message = f"{setting} must be a string"
    raise TypeError(message)


def _float_setting(value: JsonValue, *, default: float, setting: str) -> float:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        message = f"{setting} must be numeric"
        raise TypeError(message)
    try:
        return float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        message = f"{setting} must be numeric"
        raise ValueError(message) from exc


def _allowed_status_codes(value: JsonValue) -> list[int] | None:
    if value is None:
        return None
    if not isinstance(value, list) or not value:
        message = "allowed_status_codes must be a non-empty list of ints"
        raise ValueError(message)
    status_codes: list[int] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int | float | str):
            message = "allowed_status_codes must contain only integers"
            raise TypeError(message)
        status_codes.append(int(item))
    return status_codes


def _required_identity(config: JsonObject) -> tuple[str, str]:
    domain = config.get("domain")
    url = config.get("url")
    if domain is None or url is None:
        message = "Domain check module requires domain and url"
        raise ValueError(message)
    return str(domain), str(url)


def _forbidden_text(config: JsonObject) -> list[str]:
    forbidden = config.get("forbidden_text_any")
    if forbidden is None:
        return list(DEFAULT_MAINTENANCE_TEXT)
    return _string_list(forbidden, setting="forbidden_text_any")


def _extended_checks(config: JsonObject) -> tuple[list[JsonObject], list[JsonObject]]:
    api_checks = _object_list(
        config.get("api_contract_checks", []),
        setting="api_contract_checks",
    )
    transactions = _object_list(
        config.get("synthetic_transactions", []),
        setting="synthetic_transactions",
    )
    return api_checks, transactions


def load_domain_spec_from_module_dict(module_vars: JsonObject) -> DomainCheckSpec:
    """Load and validate a domain check contract from module globals.

    Returns:
        The validated domain check specification.

    Raises:
        TypeError: The ``CHECK`` value is not a mapping.
        ValueError: The ``CHECK`` value is missing or contains invalid settings.
    """
    raw_config = module_vars.get("CHECK")
    if raw_config is None:
        message = "Domain check module must define a dict named CHECK"
        raise ValueError(message)
    if not isinstance(raw_config, dict):
        message = "Domain check module must define a dict named CHECK"
        raise TypeError(message)

    domain, url = _required_identity(raw_config)
    api_checks, transactions = _extended_checks(raw_config)
    return DomainCheckSpec(
        domain=domain,
        url=url,
        allowed_status_codes=_allowed_status_codes(
            raw_config.get("allowed_status_codes"),
        ),
        expected_title_contains=_optional_text(
            raw_config.get("expected_title_contains"),
            setting="expected_title_contains",
        ),
        expected_final_host_suffix=_optional_text(
            raw_config.get("expected_final_host_suffix"),
            setting="expected_final_host_suffix",
        ),
        required_selectors_all=_compile_selector_list(
            raw_config.get("required_selectors_all", []),
        ),
        required_selectors_any=_compile_selector_list(
            raw_config.get("required_selectors_any", []),
        ),
        required_text_all=_string_list(
            raw_config.get("required_text_all", []),
            setting="required_text_all",
        ),
        forbidden_text_any=_forbidden_text(raw_config),
        capture_headers=_string_list(
            raw_config.get("capture_headers", []),
            setting="capture_headers",
        ),
        api_contract_checks=api_checks,
        synthetic_transactions=transactions,
        web_vitals=_object_setting(
            raw_config.get("web_vitals", {}),
            setting="web_vitals",
        ),
        proxy=_object_setting(raw_config.get("proxy", {}), setting="proxy"),
        browser_enabled=bool(raw_config.get("browser_enabled", True)),
        http_timeout_seconds=_float_setting(
            raw_config.get("http_timeout_seconds"),
            default=15.0,
            setting="http_timeout_seconds",
        ),
        browser_timeout_seconds=_float_setting(
            raw_config.get("browser_timeout_seconds"),
            default=25.0,
            setting="browser_timeout_seconds",
        ),
    )
