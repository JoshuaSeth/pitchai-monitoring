# Copyright (c) 2026 PitchAI. All rights reserved.
"""Build bounded retained problem/recovery history for Reliability."""

from __future__ import annotations

from typing import TYPE_CHECKING

from domain_checks.json_types import float_value, text_value
from domain_checks.safe_evidence import safe_text_excerpt
from e2e_registry.monitoring_v2.event_analysis import (
    event_is_problem,
    event_is_recovery,
)

if TYPE_CHECKING:
    from domain_checks.json_types import JsonObject

_EVENT_WINDOW_SECONDS = 604_800.0
_MAX_EVENTS = 60


def build_event_history(
    events: list[JsonObject],
    domains: list[JsonObject],
    *,
    now_ts: float,
) -> list[JsonObject]:
    """Return recent retained problem and recovery transitions."""
    owners = {
        text_value(domain.get("domain")): text_value(domain.get("group_label"), default="Unconfigured")
        for domain in domains
    }
    rows: list[JsonObject] = []
    for event in reversed(events):
        timestamp = float_value(event.get("ts"))
        kind = text_value(event.get("kind"))
        if timestamp is None or timestamp < now_ts - _EVENT_WINDOW_SECONDS:
            continue
        if not (event_is_problem(kind) or event_is_recovery(kind)):
            continue
        domain = text_value(event.get("domain"))
        rows.append(
            {
                "observed_at_ts": timestamp,
                "kind": kind,
                "state": "problem" if event_is_problem(kind) else "recovery",
                "domain": domain or None,
                "owner_project": owners.get(domain, "PitchAI core / monitoring"),
                "detail": safe_text_excerpt(
                    event.get("reason") or event.get("error") or event.get("violations"),
                    max_chars=240,
                ),
            },
        )
        if len(rows) >= _MAX_EVENTS:
            break
    return rows
