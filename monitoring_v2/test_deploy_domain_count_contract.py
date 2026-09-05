# Copyright (c) 2026 PitchAI. All rights reserved.
"""Keep deployment proof aligned with the canonical domain inventory."""

from __future__ import annotations

import re
from pathlib import Path

from .deploy_contract import production_domain_count
from .domain_runtime import inventory_runtime
from .inventory import production_config
from .json_types import object_list
from .testing_runtime import pytest

_REVIEWED_DOMAIN_COUNT = 79
_WORKFLOW_PATH = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "ci-cd.yaml"
_COUNT_COMMAND = "from monitoring_v2.deploy_contract import production_domain_count; print(production_domain_count())"
_COUNT_INPUT = '-e MONITORING_DASHBOARD_EXPECTED_DOMAINS="$expected_domain_count"'
_LITERAL_COUNT_INPUT = re.compile(
    r'MONITORING_DASHBOARD_EXPECTED_DOMAINS="[0-9]+"',
)


def test_deployment_domain_count_comes_from_validated_inventory() -> None:
    """Expose one reviewed count from the same inventory startup accepts."""
    config = production_config()
    inventory_runtime.validate_domain_inventory(config)
    active_domain_count = len(object_list(config.get("domains")))

    if active_domain_count != _REVIEWED_DOMAIN_COUNT:
        pytest.fail("reviewed production domain count changed")
    if production_domain_count() != active_domain_count:
        pytest.fail("deployment domain count drifted from production inventory")


def test_ssh_deploy_uses_validated_inventory_count() -> None:
    """Prevent the live-dashboard gate from returning to a stale literal."""
    workflow = _WORKFLOW_PATH.read_text(encoding="utf-8")

    if workflow.count(_COUNT_COMMAND) != 1:
        pytest.fail("SSH deploy must compute one validated production domain count")
    if workflow.count(_COUNT_INPUT) != 1:
        pytest.fail("live-dashboard verifier must consume the validated domain count")
    if _LITERAL_COUNT_INPUT.search(workflow) is not None:
        pytest.fail("live-dashboard verifier must not use a literal domain count")
    if workflow.index(_COUNT_COMMAND) > workflow.index(_COUNT_INPUT):
        pytest.fail("SSH deploy computes the domain count after using it")
