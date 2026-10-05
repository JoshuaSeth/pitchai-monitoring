# Copyright (c) 2026 PitchAI. All rights reserved.
"""Protected, cached route for the layered fleet token ledger."""

from __future__ import annotations

import asyncio
import os
import sqlite3
import time
from asyncio import to_thread
from pathlib import Path
from typing import TYPE_CHECKING

from .scheduling_web_runtime import json_response_factory
from .token_ledger.report import RANGES, build_report

if TYPE_CHECKING:
    from collections.abc import Callable

    from .scheduling_web_runtime import Application, Response
    from .settings import DashboardSettings
    from .timeseries_types import JsonObject

TOKEN_LEDGER_FILE_ENVIRONMENT_VARIABLE = "AUTH_USAGE_TOKEN_LEDGER_DB"
TOKEN_LEDGER_NODES_ENVIRONMENT_VARIABLE = "AUTH_USAGE_TOKEN_LEDGER_NODES"
DEFAULT_TOKEN_LEDGER_FILE = Path("/dashboard-data/token-ledger.sqlite3")
DEFAULT_NODES = ("master", "jeff-dev", "fsn1")
CACHE_SECONDS = 60.0
DEFAULT_SPAN = "7d"
UNAVAILABLE_ERROR = "The fleet token ledger could not be read."


class TokenUsageCache:
    """Per-range payload cache so polling never re-aggregates more than once a minute."""

    def __init__(self, path: Path, nodes: tuple[str, ...], *, ttl: float = CACHE_SECONDS) -> None:
        """Bind the cache to one fleet store and its expected nodes."""
        self._path = path
        self._nodes = nodes
        self._ttl = ttl
        self._entries: dict[str, tuple[float, JsonObject]] = {}
        self._lock = asyncio.Lock()

    async def payload(self, span: str) -> JsonObject:
        """Return a cached or freshly built payload for one range."""
        async with self._lock:
            cached = self._entries.get(span)
            if cached is not None and time.monotonic() - cached[0] < self._ttl:
                return cached[1]
            try:
                payload: JsonObject = await to_thread(build_report, self._path, span, expected_nodes=self._nodes)  # type: ignore[assignment]
            except (OSError, sqlite3.Error):
                payload = {"schema_version": 1, "range": span, "error": UNAVAILABLE_ERROR, "buckets": [], "dimensions": None}
            self._entries[span] = (time.monotonic(), payload)
            return payload


def _configured_nodes() -> tuple[str, ...]:
    raw = os.environ.get(TOKEN_LEDGER_NODES_ENVIRONMENT_VARIABLE, "")
    nodes = tuple(part.strip() for part in raw.split(",") if part.strip())
    return nodes or DEFAULT_NODES


def register_token_usage_route(
    application: Application,
    *,
    settings: DashboardSettings,
    identity_default: str | None,
    require_operator: Callable[[DashboardSettings, str | None], None],
) -> None:
    """Register ``GET /api/v1/token-usage?span=24h|7d|30d``."""
    configured = os.environ.get(TOKEN_LEDGER_FILE_ENVIRONMENT_VARIABLE)
    cache = TokenUsageCache(Path(configured) if configured else DEFAULT_TOKEN_LEDGER_FILE, _configured_nodes())

    async def token_usage(span: str = DEFAULT_SPAN, proxy_identity: str | None = identity_default) -> Response:
        require_operator(settings, proxy_identity)
        selected = span if span in RANGES else DEFAULT_SPAN
        return json_response_factory(await cache.payload(selected))

    application.add_api_route(
        "/api/v1/token-usage",
        token_usage,
        methods=["GET"],
        response_model=None,
    )
