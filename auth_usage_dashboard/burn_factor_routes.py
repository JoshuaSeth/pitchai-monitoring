# Copyright (c) 2026 PitchAI. All rights reserved.
"""Protected, cached ``/api/v1/burn-factor`` route for the OpenAI, Anthropic, OpenCode and DeepSeek pools."""

from __future__ import annotations

import asyncio
import os
import time
from asyncio import to_thread
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from .burn_factor import build_burn_factors
from .burn_factor_pools import POOL_LABELS, pool_inputs
from .burn_factor_windows import DEFAULT_PAIRS, parse_pairs
from .deepseek_burn import build_deepseek_burn
from .scheduling_web_runtime import HTTPException, json_response_factory
from .subscription_accounts import SUBSCRIPTION_ACCOUNTS_FILE, read_snapshot
from .subscription_routes import SUBSCRIPTION_ACCOUNTS_FILE_ENVIRONMENT_VARIABLE
from .token_ledger.failures import ExpectedFailure
from .token_usage_routes import DEFAULT_TOKEN_LEDGER_FILE, LEDGER_FILE_ENVIRONMENT_VARIABLE

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from .burn_factor_windows import WindowPair
    from .scheduling_web_runtime import Application, Response
    from .settings import DashboardSettings
    from .timeseries_types import JsonObject

CACHE_SECONDS = 30.0
POOLS = frozenset({"openai", "anthropic", "opencode", "deepseek"})
DATA_DIRECTORY = Path("/dashboard-data")
_HTTP_BAD_REQUEST = 400


@dataclass
class BurnFactorCache:
    """Per-pool, per-pairs payload cache so polling never recomputes more than every 30 seconds."""

    snapshot: Callable[[], Awaitable[JsonObject]]
    read_samples: Callable[[], list[JsonObject]] | None
    data_dir: Path = DATA_DIRECTORY
    ledger: Path = DEFAULT_TOKEN_LEDGER_FILE
    ttl: float = CACHE_SECONDS
    entries: dict[str, tuple[float, JsonObject]] = field(default_factory=dict)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def payload(self, pool: str, pairs: list[WindowPair]) -> JsonObject:
        """Return a cached or freshly computed burn-factor payload for one account pool."""
        key = pool + "|" + ",".join(f"{pair.rolling_seconds}:{pair.horizon_seconds}" for pair in pairs)
        async with self.lock:
            cached = self.entries.get(key)
            if cached is not None and time.monotonic() - cached[0] < self.ttl:
                return cached[1]
            computed = await (self._deepseek(pairs) if pool == "deepseek" else self._accounts(pool, pairs))
            payload: JsonObject = {**computed, "pool": pool, "pool_label": POOL_LABELS.get(pool)}
            self.entries[key] = (time.monotonic(), payload)
            return payload

    async def _deepseek(self, pairs: list[WindowPair]) -> JsonObject:
        configured = os.environ.get(LEDGER_FILE_ENVIRONMENT_VARIABLE)
        ledger = Path(configured) if configured else self.ledger
        return await to_thread(build_deepseek_burn, pairs, data_dir=self.data_dir, ledger=ledger)

    async def _accounts(self, pool: str, pairs: list[WindowPair]) -> JsonObject:
        if pool == "openai":
            snapshot = await self.snapshot()
            samples = await to_thread(self.read_samples) if self.read_samples is not None else []
            configured = os.environ.get(SUBSCRIPTION_ACCOUNTS_FILE_ENVIRONMENT_VARIABLE)
            path = Path(configured) if configured else SUBSCRIPTION_ACCOUNTS_FILE
            subscriptions: JsonObject | None = await to_thread(read_snapshot, path)
        else:
            snapshot, samples = await to_thread(pool_inputs, pool, data_dir=self.data_dir)
            subscriptions = None
        return await to_thread(build_burn_factors, snapshot, samples, pairs, subscriptions=subscriptions)


def register_burn_factor_route(
    application: Application,
    *,
    settings: DashboardSettings,
    identity_default: str | None,
    require_operator: Callable[[DashboardSettings, str | None], None],
    cache: BurnFactorCache,
) -> None:
    """Register ``GET /api/v1/burn-factor?pool=openai|anthropic|opencode|deepseek&pairs=30m:24h,24h:6d``."""

    async def burn_factor(
        pairs: str = DEFAULT_PAIRS,
        pool: str = "openai",
        proxy_identity: str | None = identity_default,
    ) -> Response:
        require_operator(settings, proxy_identity)
        if pool not in POOLS:
            detail = "pool must be openai, anthropic, opencode or deepseek"
            raise HTTPException(status_code=_HTTP_BAD_REQUEST, detail=detail)
        parsed: list[WindowPair] = []
        with ExpectedFailure(ValueError) as failure:
            parsed = parse_pairs(pairs)
        if failure.message is not None:
            raise HTTPException(status_code=_HTTP_BAD_REQUEST, detail=failure.message)
        return json_response_factory(await cache.payload(pool, parsed))

    application.add_api_route("/api/v1/burn-factor", burn_factor, methods=["GET"], response_model=None)
