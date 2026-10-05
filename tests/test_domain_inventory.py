# Copyright (c) 2026 PitchAI. All rights reserved.
"""Keep complete-inventory acceptance and the original seven invalid mutations."""

from __future__ import annotations

import re
from copy import deepcopy
from typing import TYPE_CHECKING, cast

import pytest

from domain_checks.dft_test_support import require
from domain_checks.inventory import validate_domain_inventory

if TYPE_CHECKING:
    from collections.abc import Callable

    from domain_checks.config_values import ConfigValue
    from e2e_registry.dashboard_records import Record


def _valid_config() -> Record:
    """Build a complete synthetic domain inventory.

    Returns:
        A fresh configuration with the original current and retired domains.
    """
    return {
        "inventory": {
            "version": 1,
            "reviewed_at": "2026-08-24",
            "authoritative_sources": ["authoritative DNS", "active ingress"],
        },
        "domain_groups": {
            "core": {"label": "PitchAI core", "description": "Primary public platform routes", "order": 10},
        },
        "container_health": {"enabled": True, "include_name_patterns": ["^service-monitoring$"]},
        "domains": [
            {
                "domain": "pitchai.net",
                "label": "PitchAI website",
                "group": "core",
                "environment": "production",
                "kind": "application",
                "sources": ["authoritative DNS", "active ingress"],
                "check": {"url": "https://pitchai.net", "required_selectors_all": ["body"]},
            },
        ],
        "retired_domains": [
            {
                "domain": "old.pitchai.net",
                "classification": "retired",
                "reason": "No current DNS or ingress contract",
                "sources": ["authoritative DNS", "active ingress"],
            },
        ],
    }


_MUTATIONS: list[tuple[Callable[[Record], ConfigValue], str]] = [
    (lambda config: cast("list[Record]", config["domains"])[0].pop("group"), "domains[0].group is required"),
    (lambda config: cast("list[Record]", config["domains"])[0].update(group="missing"), "unknown group"),
    (lambda config: cast("list[Record]", config["domains"])[0].pop("sources"), "sources must be a non-empty list"),
    (
        lambda config: cast("list[Record]", config["retired_domains"])[0].update(domain="pitchai.net"),
        "active and retired inventory",
    ),
    (
        lambda config: cast("Record", config["container_health"]).update(include_name_patterns=["["]),
        "include_name_patterns[0] is invalid",
    ),
    (
        lambda config: cast("list[Record]", config["domains"])[0].update(
            alert_policy={"telegram": "silent", "reason": "invalid mode"},
        ),
        "alert_policy.telegram must be one of",
    ),
    (
        lambda config: cast("list[Record]", config["domains"])[0].update(alert_policy={"telegram": "dashboard-only"}),
        "reason is required for dashboard-only domains",
    ),
]


def test_domain_inventory_validation_accepts_complete_metadata() -> None:
    """Accept the original complete inventory without modifying it."""
    config = _valid_config()
    validate_domain_inventory(config)


@pytest.mark.parametrize(("mutation", "message"), _MUTATIONS)
def test_domain_inventory_validation_fails_loudly(mutation: Callable[[Record], ConfigValue], message: str) -> None:
    """Retain each original invalid-field mutation and its expected error."""
    config = deepcopy(_valid_config())
    mutation(config)
    with pytest.raises(ValueError, match=re.escape(message)) as error:
        validate_domain_inventory(config)
    require(condition=message in str(error.value), message="inventory rejection message changed")
