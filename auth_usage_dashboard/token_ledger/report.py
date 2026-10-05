# Copyright (c) 2026 PitchAI. All rights reserved.
"""Dashboard payload: layered token usage by provider, model and project.

One read-only aggregate query returns the (bucket, provider, model, project)
cube for the range; the three layers are folded from it in memory, each with
at most seven named series plus "Other".
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .fleet_store import connect_fleet
from .labels import PROVIDER_SLOTS, model_label, project_label, provider_label

if TYPE_CHECKING:
    from pathlib import Path

SCHEMA_VERSION = 1
RANGES = {"24h": (86_400, 3_600), "7d": (7 * 86_400, 10_800), "30d": (30 * 86_400, 86_400)}
METRICS = (
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


@dataclass
class _Series:
    key: str
    label: str
    points: dict[str, list[int]]
    totals: dict[str, int]
    detail: str | None = None
    color_slot: int | None = None


def _blank(count: int) -> dict[str, list[int]]:
    return {metric["key"]: [0] * count for metric in METRICS}


_TOTAL_FIELDS = ("total", "cached_input", "output", "input", "reasoning", "requests", "fresh")


def _add(series: _Series, index: int, values: tuple[int, ...]) -> None:
    total, cached, output = values[0], values[1], values[2]
    fresh = max(0, total - cached)
    for metric, value in (("total", total), ("fresh", fresh), ("output", output)):
        series.points[metric][index] += value
    for name, value in zip(_TOTAL_FIELDS, (*values, fresh)):
        series.totals[name] = series.totals.get(name, 0) + value


def _fold(series: dict[str, _Series], count: int) -> list[dict[str, object]]:
    ranked = sorted(series.values(), key=lambda item: item.totals.get("total", 0), reverse=True)
    named, rest = ranked[:TOP_SERIES], ranked[TOP_SERIES:]
    if rest:
        other = _Series(OTHER_KEY, f"Other ({len(rest)})", _blank(count), {})
        for item in rest:
            for metric, points in item.points.items():
                other.points[metric] = [left + right for left, right in zip(other.points[metric], points)]
            for name, value in item.totals.items():
                other.totals[name] = other.totals.get(name, 0) + value
        named.append(other)
    output: list[dict[str, object]] = []
    for rank, item in enumerate(named):
        slot = item.color_slot if item.color_slot is not None else rank
        output.append(
            {
                "key": item.key,
                "label": item.label,
                "detail": item.detail,
                "other": item.key == OTHER_KEY,
                "color_slot": None if item.key == OTHER_KEY else slot,
                "totals": item.totals,
                "points": item.points,
            },
        )
    return output


def _coverage(connection: sqlite3.Connection, expected: tuple[str, ...], now: float) -> dict[str, object]:
    rows: dict[str, tuple[float | None, float | None, int]] = {
        str(node): (_number(last_ingest), _number(last_collect), int(backlog or 0))
        for node, last_ingest, last_collect, backlog in connection.execute(
            "select node, last_ingest_at, last_collect_at, backlog_bytes from ledger_nodes"
        )
    }
    sources: list[dict[str, object]] = []
    ingests: list[float] = []
    backlog_total = 0
    for node in sorted(set(expected) | set(rows)):
        last_ingest, last_collect, backlog = rows.get(node, (None, None, 0))
        if last_ingest is not None:
            ingests.append(last_ingest)
        backlog_total += backlog
        sources.append(
            {
                "name": node,
                "label": node,
                "last_ingest_at": _iso(last_ingest) if last_ingest is not None else None,
                "last_collect_at": _iso(last_collect) if last_collect is not None else None,
                "backlog_bytes": backlog,
                "stale": last_ingest is None or now - last_ingest > NODE_STALE_SECONDS,
            },
        )
    return {
        "sources": sources,
        "stale": any(item["stale"] for item in sources),
        "last_collected_at": _iso(max(ingests)) if ingests else None,
        "backlog_bytes": backlog_total,
    }


def _number(value: object) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _iso(epoch: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch))


def build_report(path: Path, range_key: str, *, expected_nodes: tuple[str, ...], now: float | None = None) -> dict[str, object]:
    """Return the layered token-usage payload for one range.

    Raises:
        ValueError: For an unknown range key.
    """
    if range_key not in RANGES:
        message = "unknown range"
        raise ValueError(message)
    current = time.time() if now is None else now
    span, bucket = RANGES[range_key]
    last_bucket = int(current) // bucket * bucket
    count = span // bucket
    first_bucket = last_bucket - (count - 1) * bucket
    base: dict[str, object] = {"schema_version": SCHEMA_VERSION, "generated_at": _iso(current), "range": range_key, "bucket_seconds": bucket, "metrics": list(METRICS), "method": METHOD}
    if not path.exists():
        return {**base, "error": "The fleet token ledger has not been collected yet.", "buckets": [], "dimensions": None, "coverage": {"sources": [], "stale": True}}
    connection = connect_fleet(path, read_only=True)
    try:
        cube = connection.execute(_QUERY, {"bucket": bucket, "start": first_bucket, "end": last_bucket + bucket}).fetchall()
        coverage = _coverage(connection, expected_nodes, current)
    finally:
        connection.close()
    layers: dict[str, dict[str, _Series]] = {"provider": {}, "model": {}, "project": {}}
    for bucket_start, provider, model, project, title, *values in cube:
        index = (int(bucket_start) - first_bucket) // bucket
        if not 0 <= index < count:
            continue
        numbers = tuple(int(value or 0) for value in values)
        keys = {
            "provider": (provider, provider_label(provider), None, PROVIDER_SLOTS.get(provider)),
            "model": (model, model_label(model), provider_label(provider), None),
            "project": (project, project_label(project, title), None, None),
        }
        for layer, (key, label, detail, slot) in keys.items():
            series = layers[layer].setdefault(key, _Series(key, label, _blank(count), {}, detail, slot))
            _add(series, index, numbers)
    dimensions = {layer: {"series": _fold(series, count), "series_count": len(series)} for layer, series in layers.items()}
    buckets = [_iso(first_bucket + position * bucket) for position in range(count)]
    return {**base, "error": None, "buckets": buckets, "dimensions": dimensions, "coverage": coverage}
