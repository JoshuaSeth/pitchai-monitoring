# Copyright (c) 2026 PitchAI. All rights reserved.
"""Keep deployment proof aligned with the canonical domain inventory."""

from __future__ import annotations

from .deploy_contract import production_domain_count
from .domain_runtime import inventory_runtime
from .inventory import production_config
from .json_types import object_list
from .testing_runtime import pytest

_REVIEWED_DOMAIN_COUNT = 73


def test_deployment_domain_count_comes_from_validated_inventory() -> None:
    """Expose one reviewed count from the same inventory startup accepts."""
    config = production_config()
    inventory_runtime.validate_domain_inventory(config)
    active_domain_count = len(object_list(config.get("domains")))

    if active_domain_count != _REVIEWED_DOMAIN_COUNT:
        pytest.fail("reviewed production domain count changed")
    if production_domain_count() != active_domain_count:
        pytest.fail("deployment domain count drifted from production inventory")
