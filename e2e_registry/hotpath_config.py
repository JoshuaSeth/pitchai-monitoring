# Copyright (c) 2026 PitchAI. All rights reserved.
"""Runtime configuration for first-class client hotpath signals."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .settings import RegistrySettings

_DEFAULT_INVENTORY_PATH = str(Path(__file__).with_name("hotpath_inventory.json"))


@dataclass(frozen=True)
class HotpathRuntimeConfig:
    """Hotpath-specific configuration composed with established registry state."""

    db_path: str
    reporter_token: str
    reader_tokens: tuple[str, ...]
    dashboard_identity_header: str
    inventory_path: str


def load_hotpath_config(settings: RegistrySettings) -> HotpathRuntimeConfig:
    """Compose dedicated hotpath configuration without widening legacy settings.

    Returns:
        Validated, secret-bearing runtime configuration.
    """
    reporter_token = os.getenv("E2E_HOTPATH_REPORTER_TOKEN", "").strip()
    configured_inventory = os.getenv("E2E_HOTPATH_INVENTORY_PATH", "").strip()
    reader_tokens = tuple(
        token.strip()
        for token in (settings.admin_token, settings.monitor_token)
        if token.strip()
    )
    return HotpathRuntimeConfig(
        db_path=settings.db_path,
        reporter_token=reporter_token,
        reader_tokens=reader_tokens,
        dashboard_identity_header=settings.dashboard_identity_header,
        inventory_path=configured_inventory or _DEFAULT_INVENTORY_PATH,
    )
