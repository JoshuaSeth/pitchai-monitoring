# Copyright (c) 2026 PitchAI. All rights reserved.
"""Verify 2FA Server has complete production monitoring coverage."""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, cast

from .domain_runtime import (
    load_config,
    load_domain_spec,
)
from .expectations import present
from .json_types import (
    json_object,
    object_list,
    optional_object,
    text_value,
    value_list,
)
from .testing_runtime import pytest

if TYPE_CHECKING:
    from .domain_runtime import DomainCheckSpec
    from .json_types import JsonInput, JsonObject

DOMAIN = "2fa-server.37.27.67.52.nip.io"
_HTTP_OK = 200


def _load_twofa_spec() -> tuple[JsonObject, DomainCheckSpec]:
    """Load the active 2FA inventory entry and executable check.

    Returns:
        The full monitor config and the executable 2FA check.
    """
    config_path = Path(__file__).resolve().parents[1] / "domain_checks" / "config.yaml"
    config = json_object(cast("JsonInput", load_config(config_path)))
    domains = object_list(config.get("domains"))
    domain_entries = (item for item in domains if text_value(item.get("domain")) == DOMAIN)
    entry = present(
        next(domain_entries, None),
        label="2FA Server is missing from active monitoring inventory",
    )
    if entry.get("disabled") is True:
        pytest.fail("2FA Server monitoring is disabled")
    return config, load_domain_spec(entry)


def test_twofa_health_contract_is_monitored() -> None:
    """Cover the public 2FA health route and response assertions."""
    _config, spec = _load_twofa_spec()

    if spec.url != f"https://{DOMAIN}/healthz":
        pytest.fail("2FA health URL changed")
    if spec.allowed_status_codes != [_HTTP_OK]:
        pytest.fail("2FA allowed status changed")
    if set(spec.required_text_all) != {"ok", "time_utc"}:
        pytest.fail("2FA health assertions changed")


def test_twofa_event_bus_outbox_readiness_is_monitored_without_credentials() -> None:
    """Cover the read-only 2FA event-bus/outbox readiness contract."""
    _config, spec = _load_twofa_spec()
    raw_checks = spec.api_contract_checks
    normalized_checks = [json_object(cast("JsonInput", check)) for check in raw_checks]
    checks = {text_value(check.get("name")): check for check in normalized_checks}
    if set(checks) != {"health", "event_bus_outbox_readiness"}:
        pytest.fail("2FA API checks changed")
    if checks["health"]["path"] != "/healthz":
        pytest.fail("2FA health path changed")
    if checks["event_bus_outbox_readiness"]["path"] != "/readyz":
        pytest.fail("2FA outbox readiness path changed")
    for check in checks.values():
        if check["method"] != "GET":
            pytest.fail("2FA check is not read-only GET")
        if check["expected_status_codes"] != [_HTTP_OK]:
            pytest.fail("2FA check status changed")
        if check["expected_content_type_contains"] != "application/json":
            pytest.fail("2FA check content type changed")
        if check["json_paths_equal"] != {"ok": True}:
            pytest.fail("2FA JSON equality changed")
        if check["json_paths_required"] != ["ok", "time_utc"]:
            pytest.fail("2FA JSON fields changed")
        if "headers" in check:
            pytest.fail("2FA monitoring added credential-bearing headers")


def test_twofa_production_container_is_in_required_health_inventory() -> None:
    """Require the live 2FA container in the socket-visible health inventory."""
    config, _spec = _load_twofa_spec()
    container_config = optional_object(config.get("container_health"))
    raw_patterns = value_list(container_config.get("include_name_patterns"))
    patterns = [text_value(item) for item in raw_patterns]
    if not any(re.fullmatch(pattern, "twofa-server-prod") for pattern in patterns):
        pytest.fail("2FA production container is not covered")
