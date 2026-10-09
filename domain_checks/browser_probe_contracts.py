# Copyright (c) 2026 PitchAI. All rights reserved.
"""Explicit callable contracts for cycle-owned native browser observations."""

from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from .event_bus_delivery import JsonObject
    from .metrics_synthetic import SyntheticTransactionResult
    from .metrics_web_vitals import WebVitalsResult


class SyntheticInputs[BrowserT](TypedDict):
    """Named native transaction arguments without positional reordering."""

    domain: str
    base_url: str
    browser: BrowserT
    transactions: list[JsonObject]
    timeout_seconds: float


class VitalsInputs[BrowserT](TypedDict):
    """Named native metric arguments including the original post-load delay."""

    domain: str
    url: str
    browser: BrowserT
    timeout_seconds: float
    post_load_wait_ms: int


# The cycle binds native keyword-only callables to these complete input records.
type SyntheticProbe[BrowserT] = Callable[[SyntheticInputs[BrowserT]], Awaitable[list[SyntheticTransactionResult]]]
type VitalsProbe[BrowserT] = Callable[[VitalsInputs[BrowserT]], Awaitable[WebVitalsResult]]
