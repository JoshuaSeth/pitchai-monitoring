# Copyright (c) 2026 PitchAI. All rights reserved.
"""Proof for the layered fleet token ledger dashboard report."""

from __future__ import annotations

import io
import json
from typing import TYPE_CHECKING

from ._timeseries_test_fixtures import check, check_equal, require_array
from ._token_ledger_test_fixtures import value_error_text
from .timeseries_types import require_object
from .token_ledger.fleet_store import connect_fleet, ingest
from .token_ledger.report import build_report

if TYPE_CHECKING:
    from pathlib import Path

    from .timeseries_types import JsonObject, JsonValue

HOUR = 3_600
BASE = 1_791_158_400  # 2026-10-05T00:00:00Z
ROW_DEFAULTS: JsonObject = {
    "change_seq": 1,
    "project_title": None,
    "reasoning": 0,
    "requests": 1,
    "cell": "c",
    "agent": "a",
    "route": "codex_account",
}


def _fleet_with(tmp_path: Path, rows: list[JsonObject]) -> Path:
    fleet = tmp_path / "fleet.sqlite3"
    connection = connect_fleet(fleet)
    header = json.dumps({"kind": "header", "collected_at": BASE, "backlog_bytes": 0})
    body = "\n".join([header, *(json.dumps({**ROW_DEFAULTS, **row}) for row in rows)])
    ingest(connection, "master", io.StringIO(body + "\n"))
    connection.close()
    return fleet


def _objects(value: JsonValue, description: str) -> list[JsonObject]:
    items = require_array(value, description)
    return [require_object(item, description=description) for item in items]


def _point_total(series: JsonObject) -> int:
    points = require_object(series["points"], description="series points")
    values = require_array(points["total"], "total points")
    integers = [value for value in values if isinstance(value, int)]
    check_equal(len(integers), len(values), "every total point is an integer")
    return sum(integers)


def test_report_layers_fold_into_top_series_and_other(tmp_path: Path) -> None:
    """Prove report layers fold into top series and other."""
    indexes = range(9)
    rows: list[JsonObject] = [
        {
            "hour_epoch": BASE + HOUR * (index % 3),
            "project": f"p{index}",
            "provider": "openai" if index % 2 else "anthropic",
            "model": f"m{index}",
            "input": 100 * (index + 1),
            "cached_input": 10,
            "output": 5,
            "total": 100 * (index + 1) + 5,
        }
        for index in indexes
    ]
    fleet = _fleet_with(tmp_path, rows)
    report = build_report(fleet, "24h", expected_nodes=("master", "fsn1"), now=BASE + 3 * HOUR + 30)
    dimensions = require_object(report["dimensions"], description="dimensions")
    projects = _objects(require_object(dimensions["project"], description="project layer")["series"], "projects")
    check_equal([item["key"] for item in projects][:2], ["p8", "p7"], "the largest projects lead the layer")
    check(projects[-1]["other"] is True, "the tail is folded into Other")
    check_equal(projects[-1]["label"], "Other (2)", "Other counts the folded series")
    provider_series = _objects(require_object(dimensions["provider"], description="provider layer")["series"], "p")
    providers = {str(item["key"]): item for item in provider_series}
    check_equal(providers["openai"]["color"], "#2a6fdb", "OpenAI keeps its family color")
    check_equal(providers["anthropic"]["color"], "#f07a24", "Anthropic keeps its family color")
    check_equal(len(require_array(report["buckets"], "buckets")), 24, "a day has 24 hourly buckets")
    point_totals = [_point_total(item) for item in projects]
    expected_total = sum(int(str(row["total"])) for row in rows)
    check_equal(sum(point_totals), expected_total, "folding keeps every token")
    coverage = require_object(report["coverage"], description="coverage")
    sources = _objects(coverage["sources"], "coverage sources")
    stale = {str(item["name"]): item["stale"] for item in sources}
    check_equal(stale, {"fsn1": True, "master": False}, "a node that never reported is stale")


def test_report_without_store_is_explicitly_unavailable(tmp_path: Path) -> None:
    """Prove report without store is explicitly unavailable."""
    report = build_report(tmp_path / "missing.sqlite3", "7d", expected_nodes=("master",), now=BASE)
    check(report["dimensions"] is None, "no dimensions without a store")
    check(bool(report["error"]), "the missing store is explained")
    missing = tmp_path / "missing.sqlite3"
    error = value_error_text(lambda: build_report(missing, "1y", expected_nodes=(), now=BASE))
    check("range" in error, "an unknown range is rejected")


def test_model_layer_groups_provider_families_with_darker_heavier_models(tmp_path: Path) -> None:
    """Prove models are colored by provider family and ordered heaviest-first within a family."""
    usage = (
        ("gpt-5.6-luna", "openai", 900),
        ("gpt-6-astra", "openai", 300),
        ("claude-opus", "anthropic", 500),
        ("claude-fable", "anthropic", 100),
        ("mystery-model", "openai", 50),
    )
    rows: list[JsonObject] = [
        {
            "hour_epoch": BASE,
            "project": "p",
            "provider": provider,
            "model": model,
            "input": total,
            "cached_input": 0,
            "output": 0,
            "total": total,
        }
        for model, provider, total in usage
    ]
    report = build_report(_fleet_with(tmp_path, rows), "24h", expected_nodes=("master",), now=BASE + 60)
    dimensions = require_object(report["dimensions"], description="dimensions")
    models = _objects(require_object(dimensions["model"], description="model layer")["series"], "models")
    check_equal(
        [item["key"] for item in models],
        ["gpt-6-astra", "gpt-5.6-luna", "mystery-model", "claude-fable", "claude-opus"],
        "families stay together, largest family first, heaviest model at the base",
    )
    colors = {str(item["key"]): item["color"] for item in models}
    check_equal(colors["gpt-6-astra"], "#1d3a8f", "Astra is the dark navy shade")
    check_equal(colors["gpt-5.6-luna"], "#38c6d6", "Luna is the light cyan shade")
    check_equal(colors["claude-fable"], "#8a4b1a", "Fable is brown")
    check_equal(colors["claude-opus"], "#d03a2f", "Opus is red")
    check_equal(colors["mystery-model"], "#5b8fd9", "an unlisted model takes its family middle shade")
    check_equal(models[0]["detail"], "OpenAI · AA 53", "the AA index is shown with the provider")
