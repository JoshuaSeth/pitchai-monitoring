# Copyright (c) 2026 PitchAI. All rights reserved.
"""Summarize frozen descriptive cohorts with timing and rounding sensitivities.

Intervals share account quota across all concurrent workloads. Model/effort
dominance does not isolate a causal effect. Bounds below are conditional on
recovered workload and the stated endpoint errors; missing work and unknown
service tiers are not bounded by these calculations.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import TypedDict, cast

type Row = dict[str, str]
type Json = bool | int | float | str | list[Json] | dict[str, Json] | None
_MINIMUM_STRICT_SHARE = .95
_MAXIMUM_EPOCH_GAP_SECONDS = 1830


class Annotation(TypedDict):
    """Reviewed historical correction to a quota-only transition classification."""

    account: str
    segment: str
    previous_grade: str
    revised_grade: str


def annotate(rows: list[Row], annotations: list[Annotation]) -> int:
    """Apply historical labels in memory while keeping the source tables immutable.

    Returns:
        Number of rows whose classification was annotated.

    Raises:
        ValueError: If an annotation disagrees with its expected source classification.
    """
    changes = {(item["account"], item["segment"]): item for item in annotations}
    changed = 0
    for row in rows:
        change = changes.get((row["account"], row["segment"]))
        if change is None:
            continue
        if row["transition_grade"] != change["previous_grade"]:
            message = "Historical annotation no longer matches its source classification"
            raise ValueError(message)
        row["transition_grade"] = change["revised_grade"]
        changed += 1
    return changed


def number(row: Row, key: str) -> float:
    """Read a required numeric field; missing evidence is never replaced by zero.

    Returns:
        The parsed numeric value.
    """
    return float(row[key])


def period(row: Row) -> str:
    """Separate the dated Sol price change from the later model transition.

    Returns:
        A calendar period chosen independently of observed efficiency.
    """
    day = row["start_utc"][:10]
    if day < "2026-08-21":
        return "before_aug21"
    if day < "2026-09-01":
        return "aug21_aug31"
    return "sep01_sep06_partial"


def eligible(row: Row, dominance: float, points: float) -> bool:
    """Apply the declared provenance, price, identity and workload controls.

    Returns:
        Whether a row satisfies the specified sensitivity threshold.
    """
    return (number(row, "dominant_value_share") >= dominance
            and number(row, "strict_value_share") >= _MINIMUM_STRICT_SHARE
            and number(row, "delta_pp") >= points
            and all(number(row, key) == 0 for key in (
                "unpriced_calls", "uncertain_price_calls", "different_reset_calls", "missing_reset_calls",
            )))


def aggregate(rows: list[Row]) -> dict[str, Json]:
    """Count pool quota once and sum disjoint token components.

    Returns:
        Descriptive values, sample counts and explicit sensitivity bounds.
    """
    keys = ("delta_pp", "strict_calls", "strict_usd", "fixed_usd", "uncached", "cached", "output",
            "reasoning", "long_context_calls", "interior_usd", "enclosing_usd")
    sums = {key: sum(number(row, key) for row in rows) for key in keys}
    points, count = sums["delta_pp"], len(rows)
    accounts = {row["account"] for row in rows}
    result: dict[str, Json] = {
        "intervals": count, "accounts": cast("list[Json]", sorted(accounts)),
        "account_epochs": len({(row["account"], row["segment"]) for row in rows}),
        "first_day": min(row["start_utc"][:10] for row in rows),
        "last_start_day": max(row["start_utc"][:10] for row in rows), "sums": cast("dict[str, Json]", sums),
        "dated_usd_per_pp": sums["strict_usd"] / points,
        "fixed_usd_per_pp": sums["fixed_usd"] / points,
        "quota_pp_per_million_total_tokens": points * 1e6 / (sums["uncached"] + sums["cached"] + sums["output"]),
        "cache_hit_fraction": sums["cached"] / (sums["uncached"] + sums["cached"]),
        "reasoning_fraction_of_output": sums["reasoning"] / sums["output"],
        "long_context_call_fraction": sums["long_context_calls"] / sums["strict_calls"],
    }
    for error in (1, 2):
        result[f"timing_and_{error}pp_endpoint_sensitivity"] = {
            "usd_per_pp_low": sums["interior_usd"] / (points + error * count),
            "usd_per_pp_high": sums["enclosing_usd"] / (points - error * count)
            if points > error * count else None,
        }
    return result


def epoch_eligible(row: Row) -> bool:
    """Require substantial consumption, known dominance and continuous sampling.

    Returns:
        Whether an epoch satisfies the declared descriptive comparison controls.
    """
    if not row["dominant_value_share"]:
        return False
    return (eligible(row, .95, 80)
            and number(row, "consumption_max_gap_seconds") <= _MAXIMUM_EPOCH_GAP_SECONDS)


def grouped(rows: list[Row], dimensions: tuple[str, ...]) -> list[dict[str, Json]]:
    """Summarize a partition without duplicating an interval within that partition.

    Returns:
        Sorted group labels and their descriptive aggregates.
    """
    groups: defaultdict[tuple[str, ...], list[Row]] = defaultdict(list)
    for row in rows:
        key = tuple(period(row) if field == "period" else row[field] for field in dimensions)
        groups[key].append(row)
    return [{"group": dict(zip(dimensions, key, strict=True)), **aggregate(values)}
            for key, values in sorted(groups.items())]


def read_table(path: Path) -> list[Row]:
    """Read one anonymous exported table.

    Returns:
        CSV rows without silently filling missing values.
    """
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def main() -> None:
    """Write descriptive comparisons; uncertainty does not imply causal proof.

    Raises:
        ValueError: If historical annotations do not each match one exported epoch.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tables", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--annotations", type=Path, help="Reviewed historical epoch transition corrections")
    args = parser.parse_args()
    tables, output = cast("Path", args.tables), cast("Path", args.output)
    hours = read_table(tables / "hourly_analysis.csv")
    all_epochs = read_table(tables / "epoch_analysis.csv")
    annotations: list[Annotation] = []
    annotation_path = cast("Path | None", args.annotations)
    if annotation_path is not None:
        annotations = cast("list[Annotation]", json.loads(annotation_path.read_text(encoding="utf-8")))
        if annotate(all_epochs, annotations) != len(annotations):
            message = "Every historical annotation must match exactly one exported epoch"
            raise ValueError(message)
        _ = annotate(hours, annotations)
    primary = [row for row in hours if eligible(row, .95, 5)]
    epochs = [row for row in all_epochs if epoch_eligible(row)]
    result = {
        "schema": 1, "scope": "descriptive_recovered_workload_comparisons",
        "historical_transition_annotations": annotations,
        "primary_control": "95% dominant value; 95% strict value; >=5pp; dated price and matching reset",
        "epoch_control": "same controls; >=80pp; maximum consumption observation gap <=1830 seconds",
        "epoch_gap_tolerance": "30 minutes plus 30 seconds for observed provider-probe jitter",
        "uncertainty": "Sensitivity bounds include +/-120 seconds and +/-1 or +/-2 pp per interval; "
                       "they are not confidence intervals and cannot bound missing workload or unknown service tiers.",
        "hourly_periods": grouped(primary, ("model", "effort", "period")),
        "hourly_accounts": grouped(primary, ("model", "effort", "period", "account")),
        "hourly_bank_grades": grouped(primary, ("model", "effort", "period", "transition_grade")),
        "epoch_periods": grouped(epochs, ("model", "effort", "period", "transition_grade")),
        "epoch_accounts": grouped(epochs, ("model", "effort", "period", "transition_grade", "account")),
        "threshold_sensitivity": [
            {"dominance": dominance, "minimum_pp": points,
             "cohorts": grouped([row for row in hours if eligible(row, dominance, points)],
                                ("model", "effort", "period"))}
            for dominance in (.80, .90, .95) for points in (2, 5, 10)
        ],
    }
    with output.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
