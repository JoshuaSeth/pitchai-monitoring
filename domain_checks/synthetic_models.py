# Copyright (c) 2026 PitchAI. All rights reserved.
"""Typed state for browser-based synthetic transactions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, NamedTuple, NotRequired, TypedDict

if TYPE_CHECKING:
    from playwright.async_api import Browser, BrowserContext, Page

    from domain_checks.types import JsonObject


@dataclass(frozen=True)
class SyntheticTransactionResult:
    """Represent one synthetic transaction outcome."""

    domain: str
    name: str
    ok: bool
    elapsed_ms: float | None
    error: str | None
    details: JsonObject
    browser_infra_error: bool


class SyntheticRunOptions(TypedDict):
    """Optional controls accepted by synthetic transaction execution."""

    timeout_seconds: NotRequired[float]
    artifacts_dir: NotRequired[str | None]
    trace_on_failure: NotRequired[bool]


class SyntheticRunSettings(NamedTuple):
    """Normalized settings shared by each configured transaction."""

    domain: str
    base_url: str
    browser: Browser
    timeout_ms: int
    artifacts_dir: str | None
    trace_on_failure: bool


@dataclass
class SyntheticSession:
    """Mutable resources created while executing one transaction."""

    context: BrowserContext | None = None
    page: Page | None = None
    tracing_started: bool = False
    artifact_names: JsonObject = field(default_factory=dict)


class SyntheticStepContext(NamedTuple):
    """Execution controls needed by individual synthetic steps."""

    base_url: str
    timeout_ms: int
    artifacts_dir: str | None
    artifact_names: JsonObject
