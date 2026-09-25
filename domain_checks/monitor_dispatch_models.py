# Copyright (c) 2026 PitchAI. All rights reserved.
"""Typed dispatcher requests and persisted outcomes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypedDict


@dataclass(frozen=True)
class DispatchRequest:
    """One dispatcher escalation request."""

    prompt: str
    state_key: str
    title: str


@dataclass(frozen=True)
class QueuedDispatch:
    """Dispatcher identifiers and start time for a queued escalation."""

    bundle: str
    runner: str
    started: float


class DispatchOutcome(TypedDict):
    """Fields recorded after a dispatcher escalation finishes."""

    started_ts: float
    bundle: str | None
    runner: str | None
    queue_state: str
    ui_url: str
    ok: bool
    error: str | None
    agent_message: str | None
