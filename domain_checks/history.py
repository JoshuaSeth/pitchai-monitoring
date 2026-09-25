# Copyright (c) 2026 PitchAI. All rights reserved.
"""PitchAI domain monitoring support for history.

Persisted samples use the compact sequence ``ts``, ``ok``, HTTP latency, browser
latency, and status code. The stable sequence shape keeps ``state.json`` small.
"""

from __future__ import annotations

from bisect import bisect_left
from collections import UserDict
from operator import itemgetter
from typing import TYPE_CHECKING, TypedDict, Unpack

from domain_checks.common_values import coerce_optional_int
from domain_checks.history_metrics import (
    compute_availability,
    compute_burn_rate,
    compute_error_rate_percent,
    extract_latency_ms,
    latency_percentile_ms,
)

__all__ = [
    "Sample",
    "SampleHistory",
    "append_sample",
    "coerce_history",
    "compute_availability",
    "compute_burn_rate",
    "compute_error_rate_percent",
    "extract_latency_ms",
    "latency_percentile_ms",
    "prune_history",
    "window_samples",
]

if TYPE_CHECKING:
    from collections.abc import MutableMapping

    from domain_checks.types import JsonValue

type Sample = tuple[float, bool, float | None, float | None, int | None]

_OK_INDEX = 1
_HTTP_LATENCY_INDEX = 2
_BROWSER_LATENCY_INDEX = 3
_STATUS_CODE_INDEX = 4


class SampleHistory(UserDict[str, list[Sample]]):
    """Keep the persisted sample schema visible across async orchestration."""


def _coerce_float(value: JsonValue) -> float | None:
    if not isinstance(value, bool | int | float | str):
        return None
    try:
        return float(value)
    except (TypeError, ValueError, OverflowError):
        return None


def coerce_history(raw: JsonValue) -> dict[str, list[Sample]]:
    """Best-effort decode for history loaded from state.json.

    Ignores invalid entries to be robust to partial writes or older formats.

    Returns:
        The valid, timestamp-ordered samples grouped by domain.
    """
    if not isinstance(raw, dict):
        return {}

    out: dict[str, list[Sample]] = {}
    for domain, items in raw.items():
        if not domain:
            continue
        if not isinstance(items, list):
            continue

        samples: list[Sample] = []
        for item in items:
            if not isinstance(item, list) or len(item) <= _OK_INDEX:
                continue
            ts = _coerce_float(item[0])
            if ts is None:
                continue
            ok = bool(item[_OK_INDEX])

            http_ms = _coerce_float(item[_HTTP_LATENCY_INDEX]) if len(item) > _HTTP_LATENCY_INDEX else None
            browser_ms = _coerce_float(item[_BROWSER_LATENCY_INDEX]) if len(item) > _BROWSER_LATENCY_INDEX else None
            status_code = (
                coerce_optional_int(item[_STATUS_CODE_INDEX], allow_bool=True)
                if len(item) > _STATUS_CODE_INDEX
                else None
            )

            samples.append((ts, ok, http_ms, browser_ms, status_code))

        samples.sort(key=itemgetter(0))
        if samples:
            out[domain] = samples

    return out


class SampleFields(TypedDict):
    """Keyword fields required when appending one history sample."""

    domain: str
    ts: float
    ok: bool
    http_elapsed_ms: float | None
    browser_elapsed_ms: float | None
    status_code: int | None


def append_sample(
    history: MutableMapping[str, list[Sample]],
    **fields: Unpack[SampleFields],
) -> None:
    """Append one normalized sample while preserving timestamp order."""
    if not fields["domain"]:
        return

    sample: Sample = (
        float(fields["ts"]),
        bool(fields["ok"]),
        (float(fields["http_elapsed_ms"]) if fields["http_elapsed_ms"] is not None else None),
        (float(fields["browser_elapsed_ms"]) if fields["browser_elapsed_ms"] is not None else None),
        int(fields["status_code"]) if fields["status_code"] is not None else None,
    )

    items = history.get(fields["domain"])
    if items is None:
        history[fields["domain"]] = [sample]
        return

    # Normal case: we append in time-order (cycle order). If a clock jump or out-of-order
    # append happens, fall back to sorted insert.
    if not items or items[-1][0] <= sample[0]:
        items.append(sample)
        return

    idx = bisect_left([item[0] for item in items], sample[0])
    items.insert(idx, sample)


def prune_history(
    history: MutableMapping[str, list[Sample]],
    *,
    before_ts: float,
) -> None:
    """Remove samples older than the requested timestamp."""
    cutoff = float(before_ts)
    for domain in list(history.keys()):
        items = history.get(domain) or []
        if not items:
            del history[domain]
            continue

        # Find first sample with ts >= cutoff.
        ts_list = [sample[0] for sample in items]
        idx = bisect_left(ts_list, cutoff)
        if idx <= 0:
            continue
        if idx >= len(items):
            del history[domain]
            continue
        history[domain] = items[idx:]


def window_samples(items: list[Sample], *, since_ts: float) -> list[Sample]:
    """Select samples at or after a timestamp.

    Returns:
        The timestamp-ordered window of matching samples.
    """
    if not items:
        return []
    cutoff = float(since_ts)
    ts_list = [sample[0] for sample in items]
    idx = bisect_left(ts_list, cutoff)
    return items[idx:]
