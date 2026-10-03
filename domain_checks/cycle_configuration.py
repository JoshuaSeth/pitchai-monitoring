# Copyright (c) 2026 PitchAI. All rights reserved.
"""Typed section lookup for the existing monitor cycle configuration."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Mapping

    from .config_values import ConfigValue


type CycleSection = Literal[
    "heartbeat", "host_health", "performance", "history", "slo", "tls", "dns", "red",
    "synthetic", "web_vitals", "api_contract", "container_health", "proxy", "meta_monitoring", "external_e2e",
]


def cycle_section(config: Mapping[str, ConfigValue], name: CycleSection) -> dict[str, ConfigValue]:
    """Retain the existing optional-section behavior without untyped wrappers.

    A populated mapping is returned unchanged. Missing, empty or non-mapping
    values produce a new empty mapping, as the cycle's previous lookups did.
    Required fields and metric defaults remain the caller's responsibility.

    Returns:
        The selected mapping or a fresh empty mapping for an absent section.
    """
    raw = config.get(name) or {}
    return raw if isinstance(raw, dict) else {}
