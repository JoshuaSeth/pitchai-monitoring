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

from .coverage import iso_utc, node_coverage
from .fleet_store import connect_fleet
from .labels import PROVIDER_LABELS, canonical_model, canonical_provider, model_label, project_label
from .model_palette import OTHER_COLOR, PROVIDER_COLORS, model_shade

if TYPE_CHECKING:
    from pathlib import Path

    from .json_types import JsonObject, JsonValue

SCHEMA_VERSION = 1
RANGES = {"24h": (86_400, 3_600), "7d": (7 * 86_400, 10_800), "30d": (30 * 86_400, 86_400)}
METRICS: tuple[JsonObject, ...] = (
    {"key": "total", "label": "All tokens"},
    {"key": "fresh", "label": "Uncached input + output"},
    {"key": "output", "label": "Output tokens"},
)
TOP_SERIES = 7
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


class _Style(NamedTuple):
    """Family color, provider family and capability order of one series."""

    color: str | None = None
    family: str | None = None
    strength: float = 0.0


_NO_STYLE = _Style()


@dataclass
class _Series:
    key: str
    label: str
    points: dict[str, list[int]]
    totals: dict[str, int]
    detail: str | None = None
    style: _Style = _NO_STYLE


class _SeriesKey(NamedTuple):
    """Identity, labels and style of one series within a layer."""

    key: str
    label: str
    detail: str | None
    style: _Style


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


def _family_order(named: list[_Series]) -> list[_Series]:
    """Keep each provider family together (largest first), heaviest model at the base.

    Returns:
        The named series in stacking order.
    """
    family_totals: dict[str, int] = {}
    for item in named:
        family = item.style.family or item.key
        family_totals[family] = family_totals.get(family, 0) + item.totals.get("total", 0)
    return sorted(named, key=lambda item: (-family_totals[item.style.family or item.key], -item.style.strength))


def _fold(series: dict[str, _Series], count: int) -> list[JsonValue]:
    ranked = sorted(series.values(), key=lambda item: item.totals.get("total", 0), reverse=True)
    named, rest = _family_order(ranked[:TOP_SERIES]), ranked[TOP_SERIES:]
    if rest:
        named.append(_other(rest, count))
    output: list[JsonValue] = []
    for rank, item in enumerate(named):
        point_items = item.points.items()
        point_lists: JsonObject = {metric: list(values) for metric, values in point_items}
        output.append(
            {
                "key": item.key,
                "label": item.label,
                "detail": item.detail,
                "other": item.key == OTHER_KEY,
                "color_slot": None if item.key == OTHER_KEY else rank,
                "color": item.style.color,
                "totals": dict(item.totals),
                "points": point_lists,
            },
        )
    return output


def _layer_keys(row: _CubeRow) -> dict[str, _SeriesKey]:
    _, stored_provider, stored_model, project, title = row[:5]
    # Rows keep the exporter's raw keys; the layers merge router and free-tier aliases.
    model = canonical_model(stored_model)
    provider = canonical_provider(model, stored_provider)
    provider_name = PROVIDER_LABELS.get(provider, provider)
    shade = model_shade(model, provider)
    model_detail = provider_name if shade.intelligence is None else f"{provider_name} · AA {shade.intelligence:g}"
    return {
        "provider": _SeriesKey(provider, provider_name, None, _Style(PROVIDER_COLORS.get(provider, OTHER_COLOR))),
        "model": _SeriesKey(model, model_label(model), model_detail, _Style(shade.color, provider, shade.order)),
        "project": _SeriesKey(project, project_label(project, title), None, _NO_STYLE),
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
            blank = _Series(spec.key, spec.label, _blank(window.size), {}, spec.detail, spec.style)
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
        "generated_at": iso_utc(current),
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
        coverage = node_coverage(connection, expected_nodes, current)
    positions = range(window.size)
    buckets: list[JsonValue] = [iso_utc(window.first_bucket + position * window.bucket) for position in positions]
    return {**base, "error": None, "buckets": buckets, "dimensions": _dimensions(cube, window), "coverage": coverage}
