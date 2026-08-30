# Copyright (c) 2026 PitchAI. All rights reserved.
"""Typed source of truth for production deployment proof."""

from __future__ import annotations

from .domain_runtime import inventory_runtime
from .inventory import production_config
from .json_types import object_list


def production_domain_count() -> int:
    """Return the validated canonical domain count used by deployment proof."""
    config = production_config()
    inventory_runtime.validate_domain_inventory(config)
    return len(object_list(config.get("domains")))
