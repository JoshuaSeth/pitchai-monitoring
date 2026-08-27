# Copyright (c) 2026 PitchAI. All rights reserved.
"""Preserve current mainline domain contracts while installing monitoring v2."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, cast

from .domain_runtime import load_domain_spec
from .inventory import entry_by_domain
from .json_types import json_object, object_list, optional_object, text_value, value_list
from .testing_runtime import pytest

if TYPE_CHECKING:
    from .json_types import JsonInput, JsonObject


def _runtime_objects(values: list[dict[str, object]]) -> list[JsonObject]:
    """Normalize established runtime dictionaries for strict assertions.

    Returns:
        Strict JSON objects for the supplied runtime values.
    """
    return [json_object(cast("JsonInput", value)) for value in values]


def _require_named(values: list[JsonObject], name: str) -> JsonObject:
    """Return one named contract or fail with an actionable message."""
    selected = next((value for value in values if text_value(value.get("name")) == name), None)
    if selected is None:
        pytest.fail(f"missing monitoring contract: {name}")
    return selected


def test_afasask_demo_canary_fails_fast_on_explicit_data_failure() -> None:
    """Keep rendered canary failures out of the generic timeout path."""
    source_path = Path(__file__).resolve().parents[1] / "e2e_tests" / "afasask_demo_codex_fast_ok.py"
    source = source_path.read_text(encoding="utf-8")
    required_fragments = (
        '"afasask_demo_canary_fail"',
        "state.failureMarkers.some",
        "for marker in _FAILURE_MARKERS",
    )
    missing = [fragment for fragment in required_fragments if fragment not in source]
    if missing:
        pytest.fail(f"AFASAsk fail-fast canary contract changed: {missing!r}")


def test_autopar_contract_models_the_protected_login_boundary() -> None:
    """Keep AutoPAR monitoring on its public token-login boundary."""
    specification = load_domain_spec(entry_by_domain("autopar.pitchai.net"))
    if specification.url != "https://autopar.pitchai.net":
        pytest.fail("AutoPAR monitoring URL changed")
    if specification.allowed_status_codes != [200]:
        pytest.fail("AutoPAR allowed status changed")
    if specification.expected_title_contains != "AutoPAR":
        pytest.fail("AutoPAR title assertion changed")
    if specification.expected_final_host_suffix != "autopar.pitchai.net":
        pytest.fail("AutoPAR final-host assertion changed")
    if specification.expected_final_path != "/login-page":
        pytest.fail("AutoPAR protected path changed")
    selectors = [item.selector for item in specification.required_selectors_all]
    if selectors != ["form[action='/login-token'] input[name='token']"]:
        pytest.fail("AutoPAR token-login selector changed")

    health = _require_named(_runtime_objects(specification.api_contract_checks), "health")
    if text_value(health.get("path")) != "/health":
        pytest.fail("AutoPAR health path changed")
    if value_list(health.get("expected_status_codes")) != [200]:
        pytest.fail("AutoPAR health status contract changed")
    if text_value(optional_object(health.get("json_paths_equal")).get("status")) != "healthy":
        pytest.fail("AutoPAR health payload contract changed")

    transaction = _require_named(
        _runtime_objects(specification.synthetic_transactions),
        "token_login_landing",
    )
    steps = object_list(transaction.get("steps"))
    required_steps = {
        ("expect_url_contains", "/login-page"),
        ("expect_title_contains", "AutoPAR"),
    }
    actual_steps = {
        (text_value(step.get("type")), text_value(step.get("value")))
        for step in steps
    }
    if not required_steps.issubset(actual_steps):
        pytest.fail("AutoPAR token-login transaction changed")
    if any("script#wss-connection" in str(step) for step in steps):
        pytest.fail("AutoPAR monitoring returned to an internal implementation selector")


def test_whatsapp_bridge_has_independent_operator_and_readiness_contracts() -> None:
    """Keep WhatsApp readiness independent from Dispatcher port checks."""
    whatsapp = load_domain_spec(entry_by_domain("whatsapp.pitchai.net"))
    dispatch = load_domain_spec(entry_by_domain("dispatch.pitchai.net"))
    if whatsapp.url != "https://whatsapp.pitchai.net/readyz":
        pytest.fail("WhatsApp readiness URL changed")
    if whatsapp.allowed_status_codes != [200] or whatsapp.browser_enabled:
        pytest.fail("WhatsApp readiness transport changed")
    if whatsapp.required_text_all != ["ok", "ready"]:
        pytest.fail("WhatsApp readiness text contract changed")

    boundary = _require_named(_runtime_objects(whatsapp.api_contract_checks), "operator_auth_boundary")
    if text_value(boundary.get("url")) != "https://whatsapp.pitchai.net/operator":
        pytest.fail("WhatsApp operator boundary URL changed")
    if value_list(boundary.get("expected_status_codes")) != [401]:
        pytest.fail("WhatsApp operator authentication boundary changed")
    dispatch_checks = _runtime_objects(dispatch.api_contract_checks)
    if any("18442" in text_value(check.get("url")) for check in dispatch_checks):
        pytest.fail("Dispatcher monitoring reclaimed the independent WhatsApp route")
