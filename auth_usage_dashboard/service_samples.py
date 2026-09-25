# Copyright (c) 2026 PitchAI. All rights reserved.
"""Persist usage samples at the explicit service I/O boundary."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

    from .history import UsageSampleStore
    from .models import DashboardSnapshot, UsageSample

LOG = logging.getLogger(__name__)


async def record_usage_samples(
    sample_store: UsageSampleStore | None,
    snapshot: DashboardSnapshot,
    *,
    now: datetime,
) -> tuple[list[UsageSample], str | None]:
    """Contain declared persistence failures and return their stable type name.

    Returns:
        The resulting collection.

    """
    if sample_store is None:
        return [], None
    try:
        samples = await asyncio.to_thread(
            sample_store.record,
            snapshot["accounts"],
            at=now,
        )
    except (OSError, ValueError) as exc:
        error_name = type(exc).__name__
        LOG.warning("Usage sample persistence failed: %s", error_name)
        return [], error_name
    return samples, None
