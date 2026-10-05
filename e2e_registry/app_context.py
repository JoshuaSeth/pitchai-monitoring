# Copyright (c) 2026 PitchAI. All rights reserved.
"""Late-bound application state and the existing five-second snapshot cache."""

from __future__ import annotations

import time
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final, cast

from . import monitor_dashboard as md

if TYPE_CHECKING:
    from fastapi import FastAPI
    from fastapi.templating import Jinja2Templates

    from domain_checks.config_values import ConfigValue

    from .settings import RegistrySettings

type CacheValue = ConfigValue | md.MonitorData
type MonitorCache = dict[str, CacheValue]
_CACHE_TTL: Final = 5.0


def file_mtime(path: str) -> float | None:
    """Retain the cache's unavailable metadata sentinel on ordinary stat errors.

    Returns:
        The file modification time or None when metadata is unavailable.
    """
    # Cache invalidation metadata has always been best-effort. Loading the
    # actual snapshot below retains its separate unavailable/error contract.
    if not path:
        return None
    with suppress(Exception):
        return float(Path(path).stat().st_mtime)
    return None


@dataclass(frozen=True)
class RegistryContext:
    """The same mutable FastAPI state, read at each existing operation boundary."""

    app: FastAPI

    @property
    def settings(self) -> RegistrySettings:
        """Read current settings without pinning an earlier state assignment.

        Returns:
            The settings object installed by create_app or its caller.
        """
        return cast("RegistrySettings", self.app.state.settings)

    @property
    def templates(self) -> Jinja2Templates:
        """Read the existing replaceable template renderer.

        Returns:
            The renderer currently held by application state.
        """
        return cast("Jinja2Templates", self.app.state.templates)

    async def monitor_data(self) -> md.MonitorData:
        """Reuse a matching fresh snapshot, otherwise load and update the same cache.

        Returns:
            The retained snapshot, including its unavailable-state evidence.
        """
        settings = self.settings
        supplied = cast("MonitorCache | None", getattr(self.app.state, "monitor_cache", None))
        if not isinstance(supplied, dict):
            empty: MonitorCache = {"loaded_at_ts": 0.0, "state_mtime": None, "config_mtime": None, "data": None}
            supplied = empty
            self.app.state.monitor_cache = supplied
        now_ts = time.time()
        state_mtime = file_mtime(settings.monitor_state_path)
        config_mtime = file_mtime(settings.monitor_config_path)
        data = supplied.get("data")
        loaded_at = 0.0
        # Existing malformed cache timestamps expire the cache. They do not
        # fabricate a successful observation or renew retained source age.
        with suppress(Exception):
            loaded_at = float(cast("str | bytes | int | float", supplied.get("loaded_at_ts") or 0.0))
        if (
            isinstance(data, md.MonitorData)
            and supplied.get("state_mtime") == state_mtime
            and supplied.get("config_mtime") == config_mtime
            and now_ts - loaded_at < _CACHE_TTL
        ):
            return data
        loaded = md.load_monitor_data(state_path=settings.monitor_state_path, config_path=settings.monitor_config_path)
        supplied["data"] = loaded
        supplied["loaded_at_ts"] = now_ts
        supplied["state_mtime"] = state_mtime
        supplied["config_mtime"] = config_mtime
        return loaded
