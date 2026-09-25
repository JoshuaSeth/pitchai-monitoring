# Copyright (c) 2026 PitchAI. All rights reserved.
"""Lock service containment to declared external boundary failures."""

from __future__ import annotations

from typing import TYPE_CHECKING, final, override

import pytest

from auth_usage_dashboard.history import UsageSampleStore
from auth_usage_dashboard.service import CapacityService
from auth_usage_dashboard.settings import DashboardSettings
from domain_checks.testing import verify

if TYPE_CHECKING:
    from datetime import datetime
    from pathlib import Path

    from auth_usage_dashboard.json_contract import JsonObject
    from auth_usage_dashboard.models import CapacityAccount, UsageSample


@final
class ReadBoundarySource:
    """Raise one configured exception from the broker read boundary."""

    def __init__(self, error: Exception | None) -> None:
        """Store the exception raised by the next source read."""
        self.error = error

    def read_accounts(self) -> list[JsonObject]:
        """Return no accounts or raise the configured boundary failure."""
        if self.error is not None:
            raise self.error
        return []

    @staticmethod
    def probe_accounts(accounts: list[JsonObject]) -> dict[str, str]:
        """Return a successful probe result."""
        _ = accounts
        return {}

    @staticmethod
    def probe_analytics(accounts: list[JsonObject]) -> dict[str, str]:
        """Return a successful analytics probe result."""
        _ = accounts
        return {}

    def close(self) -> None:
        """Close the source without external resources."""


@final
class FailingSampleStore(UsageSampleStore):
    """Raise one configured exception from sample persistence."""

    def __init__(self, path: Path, error: Exception) -> None:
        """Initialize the concrete store and persistence failure."""
        super().__init__(path)
        self.error = error

    @override
    def record(
        self,
        accounts: list[CapacityAccount],
        *,
        at: datetime,
    ) -> list[UsageSample]:
        """Raise the configured persistence failure."""
        _ = accounts, at
        raise self.error


def _settings(root: Path) -> DashboardSettings:
    """Return settings that perform only the boundary under test."""
    return DashboardSettings(
        root,
        "http://127.0.0.1:38188",
        "test-admin-token",
        safe_probe_enabled=False,
        history_file=None,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "source_error",
    [
        OSError("read failed"),
        RuntimeError("source unavailable"),
        ValueError("bad data"),
    ],
)
async def test_declared_source_failures_produce_a_degraded_snapshot(
    tmp_path: Path,
    source_error: Exception,
) -> None:
    """Keep the service alive when its declared source boundary fails."""
    service = CapacityService(_settings(tmp_path), ReadBoundarySource(source_error))

    await service.refresh(force_probe=False)
    snapshot = await service.snapshot()

    verify(snapshot["source"]["stale"] is True)
    verify(snapshot["source"]["error"] == type(source_error).__name__)


@pytest.mark.asyncio
async def test_unexpected_source_defect_propagates(tmp_path: Path) -> None:
    """Fail loudly when source implementation code raises an undeclared defect."""
    defect = TypeError("programmer defect")
    service = CapacityService(_settings(tmp_path), ReadBoundarySource(defect))

    with pytest.raises(TypeError, match="programmer defect"):
        await service.refresh(force_probe=False)


@pytest.mark.asyncio
async def test_declared_sample_io_failure_preserves_live_capacity(
    tmp_path: Path,
) -> None:
    """Expose a declared sample-store failure without hiding live source state."""
    store = FailingSampleStore(tmp_path / "samples.json", OSError("disk failed"))
    service = CapacityService(
        _settings(tmp_path),
        ReadBoundarySource(None),
        sample_store=store,
    )

    await service.refresh(force_probe=False)
    snapshot = await service.snapshot()

    verify(snapshot["source"]["error"] is None)
    verify(snapshot["source"]["history_error"] == "OSError")
    warning_codes = (warning["code"] for warning in snapshot["warnings"])
    verify("history_error" in warning_codes)


@pytest.mark.asyncio
async def test_unexpected_sample_store_defect_propagates(tmp_path: Path) -> None:
    """Fail loudly when sample-store implementation code is defective."""
    store = FailingSampleStore(
        tmp_path / "samples.json",
        TypeError("programmer defect"),
    )
    service = CapacityService(
        _settings(tmp_path),
        ReadBoundarySource(None),
        sample_store=store,
    )

    with pytest.raises(TypeError, match="programmer defect"):
        await service.refresh(force_probe=False)
