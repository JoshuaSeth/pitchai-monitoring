# Copyright (c) 2026 PitchAI. All rights reserved.
"""Decode allowlisted rollout telemetry while retaining recorded context order."""

from __future__ import annotations

import datetime
import hashlib
import json
import sys
from collections import Counter
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

from .input_boundary import InputFailure

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

type Json = str | int | float | bool | Sequence[Json] | Mapping[str, Json] | None
type Record = dict[str, Json]

TOKEN_KEYS = ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens", "total_tokens")
MARKERS = (b'"token_count"', b'"turn_context"', b'"session_meta"', b'"task_started"')


def emit(kind: str, **fields: Json) -> None:
    """Write one allowlisted telemetry record as compact deterministic JSON."""
    record = json.dumps({"kind": kind, **fields}, sort_keys=True, separators=(",", ":"))
    sys.stdout.write(record + "\n")


def digest(value: str) -> str:
    """Hash an exact identifier without disclosing it.

    Returns:
        Its SHA-256 hexadecimal digest.
    """
    return hashlib.sha256(value.encode()).hexdigest()


def tokens(value: Json) -> Record | None:
    """Select reported token components without validating or coercing counters.

    Returns:
        The token fields, or None when no object was recorded.
    """
    if not isinstance(value, dict):
        return None
    return {key: value.get(key) for key in TOKEN_KEYS}


def limits(value: Json) -> Record | None:
    """Keep reported quota and credit fields without assuming window position.

    Returns:
        An allowlisted quota object, or None for absent evidence.
    """
    if not isinstance(value, dict):
        return None
    quota_fields = ("limit_id", "limit_name", "plan_type")
    result = {key: value.get(key) for key in quota_fields}
    window_fields = ("used_percent", "window_minutes", "resets_at")
    for name in ("primary", "secondary"):
        current = value.get(name)
        result[name] = None
        if isinstance(current, dict):
            result[name] = {key: current.get(key) for key in window_fields}
    credit = value.get("credits")
    if isinstance(credit, dict):
        credit_fields = ("has_credits", "unlimited", "balance")
        result["credits"] = {key: credit.get(key) for key in credit_fields}
    return result


def decode(line: bytes, cutoff: datetime.datetime, stats: Counter[str]) -> tuple[Record, str] | None:
    """Select timestamped candidate events strictly before the frozen cutoff.

    Returns:
        A parsed event and normalized UTC timestamp, or counted missingness.
    """
    if not any(marker in line for marker in MARKERS):
        return None
    stats["candidate_lines"] += 1
    event: Json = None
    with InputFailure(ValueError) as failure:
        event = cast("Json", json.loads(line))
    if failure.error is not None:
        stats["candidate_json_errors"] += 1
        return None
    if not isinstance(event, dict):
        stats["non_object_candidates"] += 1
        return None
    when = event_time(event, cutoff, stats)
    return (event, when) if when is not None else None


def event_time(event: Record, cutoff: datetime.datetime, stats: Counter[str]) -> str | None:
    """Validate one recorded timestamp without inferring a missing timezone.

    Returns:
        A normalized UTC time before the cutoff, or counted missingness.
    """
    when = event.get("timestamp")
    if not isinstance(when, str):
        stats["missing_timestamp"] += 1
        return None
    observed = None
    with InputFailure(ValueError) as failure:
        observed = datetime.datetime.fromisoformat(when)
    if failure.error is not None or observed is None:
        stats["invalid_timestamp"] += 1
        return None
    if observed.tzinfo is None:
        stats["naive_timestamp"] += 1
        return None
    if observed >= cutoff:
        stats["after_cutoff"] += 1
        return None
    return observed.astimezone(datetime.UTC).isoformat()


@dataclass
class Context:
    """Recorded model/session context, updated only by preceding source events."""

    metadata: Record = field(default_factory=dict)
    stats: Counter[str] = field(default_factory=Counter[str])
    first_at: str | None = None
    last_at: str | None = None

    def accept(self, line: bytes, cutoff: datetime.datetime) -> Record | None:
        """Apply a timestamped line and attach its deterministic usage key.

        Returns:
            Export fields for a token event, or None for other lines.
        """
        decoded = decode(line, cutoff, self.stats)
        if decoded is None:
            return None
        event, when = decoded
        self.first_at = min(self.first_at, when) if self.first_at else when
        self.last_at = max(self.last_at, when) if self.last_at else when
        fields = self.observe(event)
        if fields is not None:
            fields["timestamp"] = when
            fields["usage_key"] = digest(json.dumps([when, fields["total"], fields["last"]], sort_keys=True))
        return fields

    def observe(self, event: Record) -> Record | None:
        """Update context and project token events using that recorded context.

        Returns:
            Token telemetry fields, or None for context-only events.
        """
        payload = event.get("payload")
        if not isinstance(payload, dict):
            return None
        event_type = event.get("type")
        metadata = self.metadata
        if event_type == "session_meta":
            self.stats["session_meta"] += 1
            metadata["session"] = digest(str(payload.get("id")))
            metadata["cli_version"] = payload.get("cli_version")
            metadata["provider"] = payload.get("model_provider")
            for key in ("model", "effort", "service_tier", "turn"):
                metadata[key] = None
        elif event_type == "turn_context":
            self.stats["turn_context"] += 1
            metadata["model"] = payload.get("model")
            metadata["effort"] = payload.get("effort") or payload.get("reasoning_effort")
            metadata["service_tier"] = payload.get("service_tier")
            metadata["turn"] = payload.get("turn_id") or metadata.get("turn")
        elif event_type == "event_msg" and payload.get("type") == "task_started":
            metadata["turn"] = payload.get("turn_id") or metadata.get("turn")
        elif event_type == "event_msg" and payload.get("type") == "token_count":
            self.stats["token_events"] += 1
            info = cast("Record", payload.get("info") or {})
            turn = cast("str | None", metadata.get("turn"))
            return {
                "session": metadata.get("session"), "turn": digest(turn) if turn else None,
                "cli_version": metadata.get("cli_version"), "provider": metadata.get("provider"),
                "model": metadata.get("model"), "effort": metadata.get("effort"),
                "service_tier": metadata.get("service_tier"),
                "total": tokens(info.get("total_token_usage")), "last": tokens(info.get("last_token_usage")),
                "rate_limits": limits(payload.get("rate_limits")),
            }
        return None
