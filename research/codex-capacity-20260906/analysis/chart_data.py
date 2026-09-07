# Copyright (c) 2026 PitchAI. All rights reserved.
"""Prepare deterministic anonymous plotting tables for the native gnuplot script."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict, cast

from .summarize_cohorts import annotate, epoch_eligible, read_table

if TYPE_CHECKING:
    from .summarize_cohorts import Annotation


class Cohort(TypedDict):
    """Published aggregate fields consumed by the hourly chart."""

    group: dict[str, str]
    intervals: int
    accounts: list[str]
    dated_usd_per_pp: float
    fixed_usd_per_pp: float
    timing_and_1pp_endpoint_sensitivity: dict[str, float]


def write_rows(path: Path, fields: list[str], rows: list[list[str | float | int]]) -> None:
    """Write a named, reproducible table without replacing existing evidence."""
    with path.open("x", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(fields)
        writer.writerows(rows)


def account_values(root: Path, output: Path) -> None:
    """Extract the strict calendar-period EUR200 benchmark values."""
    rows = read_table(root / "tables/account_months.csv")
    selected = [row for row in rows if row["strict_eligible"] == "1"]
    values = {(row["account"], row["month"]): float(row["standard_eur"]) / 200 for row in selected}
    result: list[list[str | float | int]] = []
    for index in range(1, 9):
        account = f"A{index:02d}"
        result.append([account, index, values[account, "2026-07"],
                       values[account, "2026-08"], values[account, "2026-09"]])
    write_rows(output / "account-values.csv", ["account", "row", "july", "august", "september_partial"], result)


def hourly_values(root: Path, output: Path) -> None:
    """Separate dated and fixed-price values and conditional endpoint bounds."""
    data = cast("dict[str, list[Cohort]]", json.loads((root / "evidence/cohort-comparisons.json").read_text()))
    lookup: dict[tuple[str, str], Cohort] = {}
    for cohort in data["hourly_periods"]:
        group = cohort["group"]
        lookup[group["model"], group["period"]] = cohort
    periods = ("before_aug21", "aug21_aug31", "sep01_sep06_partial")
    keys = [("gpt-5.6-sol", period) for period in periods]
    keys.append(("gpt-6-astra", "sep01_sep06_partial"))
    labels = ["Sol/max before 21 Aug", "Sol/max 21-31 Aug", "Sol/max 1-6 Sep", "Astra/high 5-6 Sep"]
    result: list[list[str | float | int]] = []
    for index, key in enumerate(keys, 1):
        row = lookup[key]
        bounds = row["timing_and_1pp_endpoint_sensitivity"]
        result.append([labels[index - 1], index, row["dated_usd_per_pp"], row["fixed_usd_per_pp"],
                       bounds["usd_per_pp_low"], bounds["usd_per_pp_high"], row["intervals"], len(row["accounts"])])
    write_rows(output / "hourly-values.csv", ["cohort", "row", "dated", "fixed", "low", "high", "hours", "accounts"],
               result)


def epoch_values(root: Path, output: Path) -> None:
    """Export every eligible epoch after applying reviewed origin annotations."""
    rows = read_table(root / "tables/epoch_analysis.csv")
    data = cast("dict[str, list[dict[str, str]]]", json.loads((root / "evidence/cohort-comparisons.json").read_text()))
    annotations = cast("list[Annotation]", data["historical_transition_annotations"])
    _ = annotate(rows, annotations)
    selected = [row for row in rows if epoch_eligible(row)]
    grades = ["direct_guardian_redemption", "ordinary_expiry_compatible", "post_manual_reset_origin_ambiguous",
              "credit_loss_and_new_window", "unexplained_early_replacement"]
    result: list[list[str | float | int]] = []
    for row in selected:
        value = float(row["fixed_usd"]) / float(row["delta_pp"])
        grade = grades.index(row["transition_grade"]) + 1
        result.append([row["account"], row["segment"], row["start_utc"][:10],
                       value, grade,
                       row["model"], row["effort"], float(row["delta_pp"]), row["transition_grade"]])
    write_rows(output / "epoch-values.csv", ["account", "segment", "day", "fixed_per_pp", "grade", "model",
                                            "effort", "points", "transition_grade"], result)


def main() -> None:
    """Create plotting tables in a new directory."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).parent.parent)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root, output = cast("Path", args.root), cast("Path", args.output)
    output.mkdir(parents=True, exist_ok=False)
    account_values(root, output)
    hourly_values(root, output)
    epoch_values(root, output)


if __name__ == "__main__":
    main()
