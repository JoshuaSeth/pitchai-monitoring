# Copyright (c) 2026 PitchAI. All rights reserved.
"""Protected, cached ``/api/v1/burn-factor`` route."""

from __future__ import annotations

import asyncio
import os
import time
from asyncio import to_thread
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from .burn_factor import build_burn_factors
from .burn_factor_windows import DEFAULT_PAIRS, parse_pairs
from .scheduling_web_runtime import HTTPException, json_response_factory
from .subscription_accounts import SUBSCRIPTION_ACCOUNTS_FILE, read_snapshot
from .subscription_routes import SUBSCRIPTION_ACCOUNTS_FILE_ENVIRONMENT_VARIABLE
from .token_ledger.failures import ExpectedFailure

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from .burn_factor_windows import WindowPair
    from .scheduling_web_runtime import Application, Response
    from .settings import DashboardSettings
    from .timeseries_types import JsonObject

CACHE_SECONDS = 30.0
_HTTP_BAD_REQUEST = 400


@dataclass
class BurnFactorCache:
    """Per-pairs payload cache so polling never recomputes more than every 30 seconds."""

    snapshot: Callable[[], Awaitable[JsonObject]]
    read_samples: Callable[[], list[JsonObject]] | None
    ttl: float = CACHE_SECONDS
    entries: dict[str, tuple[float, JsonObject]] = field(default_factory=dict)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def payload(self, pairs: list[WindowPair], key: str) -> JsonObject:
        """Return a cached or freshly computed burn-factor payload."""
        async with self.lock:
            cached = self.entries.get(key)
            if cached is not None and time.monotonic() - cached[0] < self.ttl:
                return cached[1]
            snapshot = await self.snapshot()
            samples = await to_thread(self.read_samples) if self.read_samples is not None else []
            configured = os.environ.get(SUBSCRIPTION_ACCOUNTS_FILE_ENVIRONMENT_VARIABLE)
            subscriptions = await to_thread(
                read_snapshot,
                Path(configured) if configured else SUBSCRIPTION_ACCOUNTS_FILE,
            )
            payload = await to_thread(build_burn_factors, snapshot, samples, pairs, subscriptions=subscriptions)
            self.entries[key] = (time.monotonic(), payload)
            return payload


def register_burn_factor_route(
    application: Application,
    *,
    settings: DashboardSettings,
    identity_default: str | None,
    require_operator: Callable[[DashboardSettings, str | None], None],
    cache: BurnFactorCache,
) -> None:
    """Register ``GET /api/v1/burn-factor?pairs=30m:24h,24h:6d``."""

    async def burn_factor(pairs: str = DEFAULT_PAIRS, proxy_identity: str | None = identity_default) -> Response:
        require_operator(settings, proxy_identity)
        parsed: list[WindowPair] = []
        with ExpectedFailure(ValueError) as failure:
            parsed = parse_pairs(pairs)
        if failure.message is not None:
            raise HTTPException(status_code=_HTTP_BAD_REQUEST, detail=failure.message)
        key = ",".join(f"{pair.rolling_seconds}:{pair.horizon_seconds}" for pair in parsed)
        return json_response_factory(await cache.payload(parsed, key))

    application.add_api_route("/api/v1/burn-factor", burn_factor, methods=["GET"], response_model=None)
