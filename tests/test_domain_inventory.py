from __future__ import annotations

from copy import deepcopy

import pytest

from domain_checks.inventory import validate_domain_inventory


def _valid_config() -> dict:
    return {
        "inventory": {
            "version": 1,
            "reviewed_at": "2026-08-24",
            "authoritative_sources": ["authoritative DNS", "active ingress"],
        },
        "domain_groups": {
            "core": {
                "label": "PitchAI core",
                "description": "Primary public platform routes",
                "order": 10,
            }
        },
        "container_health": {
            "enabled": True,
            "include_name_patterns": ["^service-monitoring$"],
        },
        "domains": [
            {
                "domain": "pitchai.net",
                "label": "PitchAI website",
                "group": "core",
                "environment": "production",
                "kind": "application",
                "sources": ["authoritative DNS", "active ingress"],
                "check": {"url": "https://pitchai.net", "required_selectors_all": ["body"]},
            }
        ],
        "retired_domains": [
            {
                "domain": "old.pitchai.net",
                "classification": "retired",
                "reason": "No current DNS or ingress contract",
                "sources": ["authoritative DNS", "active ingress"],
            }
        ],
    }


def test_domain_inventory_validation_accepts_complete_metadata() -> None:
    validate_domain_inventory(_valid_config())


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda config: config["domains"][0].pop("group"), "domains[0].group is required"),
        (lambda config: config["domains"][0].update(group="missing"), "unknown group"),
        (lambda config: config["domains"][0].pop("sources"), "sources must be a non-empty list"),
        (
            lambda config: config["retired_domains"][0].update(domain="pitchai.net"),
            "active and retired inventory",
        ),
        (
            lambda config: config["container_health"].update(include_name_patterns=["["]),
            "include_name_patterns[0] is invalid",
        ),
        (
            lambda config: config["domains"][0].update(
                alert_policy={"telegram": "silent", "reason": "invalid mode"}
            ),
            "alert_policy.telegram must be one of",
        ),
        (
            lambda config: config["domains"][0].update(
                alert_policy={"telegram": "dashboard-only"}
            ),
            "reason is required for dashboard-only domains",
        ),
    ],
)
def test_domain_inventory_validation_fails_loudly(mutation, message: str) -> None:
    config = deepcopy(_valid_config())
    mutation(config)
    with pytest.raises(ValueError) as error:
        validate_domain_inventory(config)
    assert message in str(error.value)
