# Copyright (c) 2026 PitchAI. All rights reserved.
"""Cache parsed monitoring data while its source files remain unchanged."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from _thread import LockType
    from collections.abc import Callable

    from .registry_runtime import MonitorData, MonitorDataLoader


@dataclass(frozen=True)
class MonitorDataSourceVersion:
    """Filesystem version of one monitoring state and configuration pair."""

    state_path: str
    config_path: str
    state_modified_ns: int | None
    config_modified_ns: int | None


def monitor_data_source_version(
    state_path: str,
    config_path: str,
) -> MonitorDataSourceVersion:
    """Read the source-file versions used to validate one cached parse.

    Returns:
        The normalized paths and nanosecond modification timestamps.
    """
    modified_times: list[int | None] = []
    for raw_path in (state_path, config_path):
        source_path = Path(raw_path)
        modified_times.append(source_path.stat().st_mtime_ns if source_path.exists() else None)
    return MonitorDataSourceVersion(
        state_path=state_path,
        config_path=config_path,
        state_modified_ns=modified_times[0],
        config_modified_ns=modified_times[1],
    )


@dataclass
class CachedMonitorDataLoader:
    """Serialize cold parses and reuse data until either source file changes."""

    delegate: MonitorDataLoader
    version_reader: Callable[[str, str], MonitorDataSourceVersion] = monitor_data_source_version
    _lock: LockType = field(default_factory=Lock, init=False, repr=False)
    _cached_version: MonitorDataSourceVersion | None = field(default=None, init=False, repr=False)
    _cached_data: MonitorData | None = field(default=None, init=False, repr=False)

    def __call__(self, *, state_path: str, config_path: str) -> MonitorData:
        """Return a stable cached parse or load and retain the current version.

        Returns:
            Parsed monitoring data for the requested source files.
        """
        with self._lock:
            source_version = self.version_reader(state_path, config_path)
            if source_version == self._cached_version and self._cached_data is not None:
                return self._cached_data

            loaded_data = self.delegate(
                state_path=state_path,
                config_path=config_path,
            )
            loaded_version = self.version_reader(state_path, config_path)
            if loaded_version == source_version:
                self._cached_version = loaded_version
                self._cached_data = loaded_data
            else:
                self._cached_version = None
                self._cached_data = None
            return loaded_data

    @staticmethod
    def contract_name() -> str:
        """Return the adapter contract name."""
        return "cached-monitor-data-loader"
