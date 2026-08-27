# Copyright (c) 2026 PitchAI. All rights reserved.
"""Exercise parsed monitoring-data cache invalidation."""

from __future__ import annotations

from dataclasses import dataclass, field

from .monitor_data_cache import CachedMonitorDataLoader, MonitorDataSourceVersion
from .registry_runtime import MonitorData
from .testing_runtime import pytest

_EXPECTED_INITIAL_LOADS = 1
_EXPECTED_REFRESHED_LOADS = 2


@dataclass
class _VersionReader:
    version: MonitorDataSourceVersion

    def __call__(self, state_path: str, config_path: str) -> MonitorDataSourceVersion:
        """Return the controlled source version for one test request."""
        if (state_path, config_path) != (self.version.state_path, self.version.config_path):
            pytest.fail("cache requested an unexpected source path")
        return self.version


@dataclass
class _CountingLoader:
    loads: list[MonitorData] = field(default_factory=list)

    def __call__(self, *, state_path: str, config_path: str) -> MonitorData:
        """Return a distinct monitor-data object for every cold parse."""
        load_number = len(self.loads) + 1
        loaded_data = MonitorData(
            state={"load_number": load_number},
            config={},
            state_path=state_path,
            config_path=config_path,
            loaded_at_ts=float(load_number),
            state_error=None,
        )
        self.loads.append(loaded_data)
        return loaded_data

    @staticmethod
    def contract_name() -> str:
        """Return the test adapter contract name."""
        return "counting-monitor-data-loader"


def test_cached_loader_reuses_unchanged_parse_and_invalidates_new_state() -> None:
    """Avoid duplicate parsing while immediately observing source changes."""
    state_path = "/monitoring/state.json"
    config_path = "/monitoring/config.yaml"
    version_reader = _VersionReader(
        MonitorDataSourceVersion(
            state_path=state_path,
            config_path=config_path,
            state_modified_ns=100,
            config_modified_ns=200,
        ),
    )
    delegate = _CountingLoader()
    loader = CachedMonitorDataLoader(
        delegate=delegate,
        version_reader=version_reader,
    )

    first = loader(state_path=state_path, config_path=config_path)
    second = loader(state_path=state_path, config_path=config_path)
    if first is not second or len(delegate.loads) != _EXPECTED_INITIAL_LOADS:
        pytest.fail("unchanged monitoring data was parsed more than once")

    version_reader.version = MonitorDataSourceVersion(
        state_path=state_path,
        config_path=config_path,
        state_modified_ns=101,
        config_modified_ns=200,
    )
    refreshed = loader(state_path=state_path, config_path=config_path)
    if refreshed is first or len(delegate.loads) != _EXPECTED_REFRESHED_LOADS:
        pytest.fail("changed monitoring state did not invalidate the cached parse")
