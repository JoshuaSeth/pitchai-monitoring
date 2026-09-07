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
from typing import cast

type Row = dict[str, str]
_MINIMUM_STRICT_SHARE = .95
_MAXIMUM_EPOCH_GAP_SECONDS = 1830


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


def aggregate(rows: list[Row]) -> dict[str, object]:
    """Count pool quota once and sum disjoint token components.

    Returns:
        Descriptive values, sample counts and explicit sensitivity bounds.
    """
    keys = ("delta_pp", "strict_calls", "strict_usd", "fixed_usd", "uncached", "cached", "output",
            "reasoning", "long_context_calls", "interior_usd", "enclosing_usd")
    sums = {key: sum(number(row, key) for row in rows) for key in keys}
    points, count = sums["delta_pp"], len(rows)
    result: dict[str, object] = {
        "intervals": count, "accounts": sorted({row["account"] for row in rows}),
        "account_epochs": len({(row["account"], row["segment"]) for row in rows}),
        "first_day": min(row["start_utc"][:10] for row in rows),
        "last_start_day": max(row["start_utc"][:10] for row in rows), "sums": sums,
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


def grouped(rows: list[Row], dimensions: tuple[str, ...]) -> list[dict[str, object]]:
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
    """Write descriptive comparisons; uncertainty does not imply causal proof."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tables", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    tables, output = cast("Path", args.tables), cast("Path", args.output)
    hours = read_table(tables / "hourly_analysis.csv")
    primary = [row for row in hours if eligible(row, .95, 5)]
    epochs = [row for row in read_table(tables / "epoch_analysis.csv")
              if row["dominant_value_share"] and eligible(row, .95, 80)
              and number(row, "consumption_max_gap_seconds") <= _MAXIMUM_EPOCH_GAP_SECONDS]
    result = {
        "schema": 1, "scope": "descriptive_recovered_workload_comparisons",
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
