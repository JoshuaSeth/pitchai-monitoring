# Copyright (c) 2026 PitchAI. All rights reserved.
"""Dashboard payload: layered token usage by provider, model and project.

One read-only aggregate query returns the (bucket, provider, model, project)
cube for the range; the three layers are folded from it in memory, each with
at most seven named series plus "Other".
"""

from __future__ import annotations

import time
from contextlib import closing
from dataclasses import dataclass
from typing import TYPE_CHECKING, NamedTuple, cast

from .fleet_store import connect_fleet
from .labels import PROVIDER_LABELS, PROVIDER_SLOTS, model_label, project_label

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Iterator
    from pathlib import Path

    from auth_usage_dashboard.timeseries_types import JsonObject, JsonValue, SqlValue

SCHEMA_VERSION = 1
RANGES = {"24h": (86_400, 3_600), "7d": (7 * 86_400, 10_800), "30d": (30 * 86_400, 86_400)}
METRICS: tuple[JsonObject, ...] = (
    {"key": "total", "label": "All tokens"},
    {"key": "fresh", "label": "Uncached input + output"},
    {"key": "output", "label": "Output tokens"},
)
TOP_SERIES = 7
NODE_STALE_SECONDS = 1_200
OTHER_KEY = "_other"
METHOD = (
    "Hourly totals from each runtime's own per-request token records (rollout token counts), "
    "collected on every node every five minutes. Cached input is part of input. "
    "Claude lanes report per turn, so a long turn lands in the hour it finished."
)
_QUERY = """
SELECT (hour_epoch / :bucket) * :bucket AS bucket, provider, model, project, max(project_title),
       sum(total), sum(cached_input), sum(output), sum(input), sum(reasoning), sum(requests)
FROM token_usage_hourly
WHERE hour_epoch >= :start AND hour_epoch < :end
GROUP BY bucket, provider, model, project
"""
# (bucket, provider, model, project, title, then the six token sums in ``_QUERY`` order)
_CubeRow = tuple[int, str, str, str, "str | None", int, int, int, int, int, int]


@dataclass
class _Series:
    key: str
    label: str
    points: dict[str, list[int]]
    totals: dict[str, int]
    detail: str | None = None
    color_slot: int | None = None


class _SeriesKey(NamedTuple):
    """Identity and labels of one series within a layer."""

    key: str
    label: str
    detail: str | None
    slot: int | None


class _Window(NamedTuple):
    """Bucket grid of one range: bucket width, bucket count and first bucket start."""

    bucket: int
    size: int
    first_bucket: int


def _window(range_key: str, current: float) -> _Window:
    span, bucket = RANGES[range_key]
    last_bucket = int(current) // bucket * bucket
    count = span // bucket
    return _Window(bucket, count, last_bucket - (count - 1) * bucket)


def _blank(count: int) -> dict[str, list[int]]:
    return {str(metric["key"]): [0] * count for metric in METRICS}


_TOTAL_FIELDS = ("total", "cached_input", "output", "input", "reasoning", "requests", "fresh")


def _add(series: _Series, index: int, values: tuple[int, ...]) -> None:
    total, cached, output = values[0], values[1], values[2]
    fresh = max(0, total - cached)
    for metric, value in (("total", total), ("fresh", fresh), ("output", output)):
        series.points[metric][index] += value
    for name, value in zip(_TOTAL_FIELDS, (*values, fresh), strict=True):
        series.totals[name] = series.totals.get(name, 0) + value


def _other(rest: list[_Series], count: int) -> _Series:
    other = _Series(OTHER_KEY, f"Other ({len(rest)})", _blank(count), {})
    for item in rest:
        for metric, points in item.points.items():
            pairs = zip(other.points[metric], points, strict=True)
            other.points[metric] = [left + right for left, right in pairs]
        for name, value in item.totals.items():
            other.totals[name] = other.totals.get(name, 0) + value
    return other


def _fold(series: dict[str, _Series], count: int) -> list[JsonValue]:
    ranked = sorted(series.values(), key=lambda item: item.totals.get("total", 0), reverse=True)
    named, rest = ranked[:TOP_SERIES], ranked[TOP_SERIES:]
    if rest:
        named.append(_other(rest, count))
    output: list[JsonValue] = []
    for rank, item in enumerate(named):
        slot = item.color_slot if item.color_slot is not None else rank
        point_items = item.points.items()
        point_lists: JsonObject = {metric: list(values) for metric, values in point_items}
        output.append(
            {
                "key": item.key,
                "label": item.label,
                "detail": item.detail,
                "other": item.key == OTHER_KEY,
                "color_slot": None if item.key == OTHER_KEY else slot,
                "totals": dict(item.totals),
                "points": point_lists,
            },
        )
    return output


def _coverage(connection: sqlite3.Connection, expected: tuple[str, ...], now: float) -> JsonObject:
    query = "select node, last_ingest_at, last_collect_at, backlog_bytes from ledger_nodes"
    rows: dict[str, tuple[float | None, float | None, int]] = {}
    for node, last_ingest, last_collect, backlog in cast("Iterator[tuple[SqlValue, ...]]", connection.execute(query)):
        rows[str(node)] = (_number(last_ingest), _number(last_collect), int(backlog or 0))
    sources: list[JsonValue] = []
    stale_flags: list[bool] = []
    ingests: list[float] = []
    backlog_total = 0
    for node in sorted(set(expected) | set(rows)):
        last_ingest, last_collect, backlog = rows.get(node, (None, None, 0))
        if last_ingest is not None:
            ingests.append(last_ingest)
        backlog_total += backlog
        stale = last_ingest is None or now - last_ingest > NODE_STALE_SECONDS
        stale_flags.append(stale)
        sources.append(
            {
                "name": node,
                "label": node,
                "last_ingest_at": _iso(last_ingest) if last_ingest is not None else None,
                "last_collect_at": _iso(last_collect) if last_collect is not None else None,
                "backlog_bytes": backlog,
                "stale": stale,
            },
        )
    return {
        "sources": sources,
        "stale": any(stale_flags),
        "last_collected_at": _iso(max(ingests)) if ingests else None,
        "backlog_bytes": backlog_total,
    }


def _number(value: SqlValue) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _iso(epoch: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch))


def _layer_keys(row: _CubeRow) -> dict[str, _SeriesKey]:
    _, provider, model, project, title = row[:5]
    provider_name = PROVIDER_LABELS.get(provider, provider)
    return {
        "provider": _SeriesKey(provider, provider_name, None, PROVIDER_SLOTS.get(provider)),
        "model": _SeriesKey(model, model_label(model), provider_name, None),
        "project": _SeriesKey(project, project_label(project, title), None, None),
    }


def _dimensions(cube: list[_CubeRow], window: _Window) -> JsonObject:
    """Return the provider, model and project layers folded from the aggregate cube."""
    layers: dict[str, dict[str, _Series]] = {"provider": {}, "model": {}, "project": {}}
    for row in cube:
        index = (int(row[0]) - window.first_bucket) // window.bucket
        if not 0 <= index < window.size:
            continue
        numbers = tuple(int(value or 0) for value in row[5:])
        for layer, spec in _layer_keys(row).items():
            blank = _Series(spec.key, spec.label, _blank(window.size), {}, spec.detail, spec.slot)
            _add(layers[layer].setdefault(spec.key, blank), index, numbers)
    dimensions: JsonObject = {}
    for layer, series_by_key in layers.items():
        dimensions[layer] = {"series": _fold(series_by_key, window.size), "series_count": len(series_by_key)}
    return dimensions


def build_report(
    path: Path,
    range_key: str,
    *,
    expected_nodes: tuple[str, ...],
    now: float | None = None,
) -> JsonObject:
    """Return the layered token-usage payload for one range.

    Raises:
        ValueError: For an unknown range key.
    """
    if range_key not in RANGES:
        message = "unknown range"
        raise ValueError(message)
    current = time.time() if now is None else now
    window = _window(range_key, current)
    base: JsonObject = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _iso(current),
        "range": range_key,
        "bucket_seconds": window.bucket,
        "metrics": list(METRICS),
        "method": METHOD,
    }
    if not path.exists():
        return {
            **base,
            "error": "The fleet token ledger has not been collected yet.",
            "buckets": [],
            "dimensions": None,
            "coverage": {"sources": [], "stale": True},
        }
    end = window.first_bucket + window.size * window.bucket
    with closing(connect_fleet(path, read_only=True)) as connection:
        bounds = {"bucket": window.bucket, "start": window.first_bucket, "end": end}
        cube = cast("list[_CubeRow]", connection.execute(_QUERY, bounds).fetchall())
        coverage = _coverage(connection, expected_nodes, current)
    positions = range(window.size)
    buckets: list[JsonValue] = [_iso(window.first_bucket + position * window.bucket) for position in positions]
    return {**base, "error": None, "buckets": buckets, "dimensions": _dimensions(cube, window), "coverage": coverage}
