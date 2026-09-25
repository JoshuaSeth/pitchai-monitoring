# Copyright (c) 2026 PitchAI. All rights reserved.
"""Shared typed configuration support for live monitoring tests."""

from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from domain_checks.main import load_config, load_domain_spec, normalize_domain_entries

if TYPE_CHECKING:
    from domain_checks.common_check import DomainCheckSpec
    from domain_checks.types import JsonObject, JsonValue


def load_enabled_specs_and_config() -> tuple[JsonObject, list[DomainCheckSpec]]:
    """Load production config and return currently enabled domain specs.

    Returns:
        The parsed config and enabled domain check specs.
    """
    config_path = Path(__file__).resolve().parents[1] / "domain_checks" / "config.yaml"
    config = load_config(config_path)
    raw_domains = config.get("domains")
    if not isinstance(raw_domains, list):
        pytest.fail("Expected domains list in production monitoring config")
    entries = normalize_domain_entries(raw_domains)
    now_ts = time.time()
    enabled_entries = [entry for entry in entries if not entry.is_disabled(now_ts)]
    enabled_specs = [load_domain_spec(entry.raw_entry) for entry in enabled_entries]
    return config, enabled_specs


def numeric_setting(mapping: JsonObject, key: str, default: float) -> float:
    """Read a scalar numeric setting or fail on an invalid configured value.

    Returns:
        The configured numeric value or the explicit default.

    Raises:
        AssertionError: The configured value cannot be converted to a number.
    """
    value: JsonValue = mapping.get(key, default)
    if not isinstance(value, (bool, int, float, str)):
        pytest.fail(f"Expected scalar numeric setting {key!r}, got {value!r}")
    try:
        return float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        msg = f"Invalid numeric setting {key!r}: {value!r}: {exc}"
        raise AssertionError(msg) from exc
