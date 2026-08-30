# Copyright (c) 2026 PitchAI. All rights reserved.
"""Verify the deployed domain inventory remains startup-compatible."""

from __future__ import annotations

from .domain_runtime import inventory_runtime
from .inventory import production_config


def test_production_config_is_accepted_by_startup_validator() -> None:
    """Load canonical production YAML through the service startup validator."""
    config = production_config()
    inventory_runtime.validate_domain_inventory(config)
