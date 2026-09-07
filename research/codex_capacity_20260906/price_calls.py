# Copyright (c) 2026 PitchAI. All rights reserved.
"""Price disjoint observed tokens using dated reference rates and daily ECB FX.

Standard API value is a comparison, not a claim about the call's actual service
tier or the subscription invoice. Cache-write telemetry is missing; an explicit
upper sensitivity assigns the published 25% premium to all uncached input only
for models that support it. No extra reasoning-output charge is added.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import json
import sqlite3
import sys
from collections import Counter
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple, TypedDict, cast

if TYPE_CHECKING:
    from collections.abc import Iterator


class Rate(TypedDict):
    """One documented rate interval in USD per million tokens."""

    model: str
    from_inclusive: str
    until_exclusive: str | None
    input: float
    cached: float
    output: float
    price_source: str
    cache_write_premium: bool


class ContextRule(TypedDict):
    """Models and input threshold subject to the context surcharge."""

    models: list[str]
    threshold_input_tokens: int


class Specification(TypedDict):
    """Consumed fields of the separately sourced pricing specification."""

    rates: list[Rate]
    long_context_rule: ContextRule


class Call(NamedTuple):
    """A ledger row with cached input already separated from uncached input."""

    key: str
    model: str | None
    day: str
    uncached: int
    cached: int
    output: int


class Quote(NamedTuple):
    """Dated price and its explicit missingness or historical qualification."""

    status: str
    source: str | None
    boundary_day: bool
    standard: float | None
    upper: float | None


@dataclass(frozen=True)
class PriceBook:
    """Dated model rates, context rules and the observed ECB exchange series."""

    rates: list[Rate]
    fx: dict[str, float]
    fx_days: list[str]
    long_models: set[str]
    threshold: int


type PriceRow = tuple[str, str, str | None, int, int, float | None, float | None,
                      float | None, str | None, float | None, float | None, float | None]
_PROGRESS_EVERY = 250_000


def applicable_rate(rates: list[Rate], model: str | None, day: str) -> Rate | None:
    """Require documented API availability and an exact model name.

    Returns:
        The single applicable rate or explicit missingness.

    Raises:
        ValueError: If more than one documented interval applies.
    """
    matches: list[Rate] = []
    for rate in rates:
        if rate["model"] != model or rate["from_inclusive"] > day:
            continue
        end = rate["until_exclusive"]
        if end is None or day < end:
            matches.append(rate)
    if len(matches) > 1:
        message = "Overlapping price periods"
        raise ValueError(message)
    return matches[0] if matches else None


def value(rate: Rate, call: Call, *, long_context: bool) -> tuple[float, float]:
    """Price the whole request at the applicable context rate.

    Returns:
        Standard USD and a separate maximum cache-write-premium sensitivity.
    """
    input_factor, output_factor = (2, 1.5) if long_context else (1, 1)
    input_cost = call.uncached * rate["input"] * input_factor / 1_000_000
    cost = input_cost + (call.cached * rate["cached"] * input_factor
                         + call.output * rate["output"] * output_factor) / 1_000_000
    write_premium = input_cost * 0.25 if rate["cache_write_premium"] else 0
    return cost, cost + write_premium


def dated_quote(rate: Rate | None, call: Call, *, long_context: bool) -> Quote:
    """Preserve unsupported models and retrospective rate qualifications.

    Returns:
        Priced USD values and their provenance, or explicit missing prices.
    """
    if rate is None:
        return Quote(status="no_supported_model_date_price", source=None,
                     boundary_day=False, standard=None, upper=None)
    standard, upper = value(rate, call, long_context=long_context)
    status = "dated_standard_reference"
    if rate["price_source"] == "api_pricing":
        status = "retrospective_rate_historical_continuity_unproved"
    return Quote(status, rate["price_source"], call.day == rate["from_inclusive"], standard, upper)


def price_call(call: Call, book: PriceBook) -> PriceRow:
    """Apply dated rates and the latest available ECB observation on or before the day.

    Returns:
        The exact twelve-column persisted price record.
    """
    long_context = call.model in book.long_models and call.uncached + call.cached > book.threshold
    quote = dated_quote(applicable_rate(book.rates, call.model, call.day), call, long_context=long_context)
    fx_index = bisect.bisect_right(book.fx_days, call.day) - 1
    fx_day = book.fx_days[fx_index] if fx_index >= 0 else None
    exchange = book.fx[fx_day] if fx_day else None
    current_rate = applicable_rate(book.rates, call.model, "2026-09-06")
    reference = value(current_rate, call, long_context=long_context)[0] if current_rate else None
    standard_eur = quote.standard / exchange if quote.standard is not None and exchange else None
    upper_eur = quote.upper / exchange if quote.upper is not None and exchange else None
    return (call.key, quote.status, quote.source, int(long_context), int(quote.boundary_day),
            quote.standard, quote.upper, exchange, fx_day, standard_eur, upper_eur, reference)


def load_book(pricing: Path, fx_path: Path) -> PriceBook:
    """Read the dated pricing specification and complete daily FX series.

    Returns:
        A reusable model/FX/context lookup for every candidate.
    """
    specification = cast("Specification", json.loads(pricing.read_text(encoding="utf-8")))
    with fx_path.open(encoding="utf-8") as stream:
        rows = csv.DictReader(stream)
        fx = {row["date"]: float(row["usd_per_eur"]) for row in rows}
    rule = specification["long_context_rule"]
    return PriceBook(specification["rates"], fx, sorted(fx), set(rule["models"]), rule["threshold_input_tokens"])


def main() -> None:
    """Create a new price sidecar without modifying frozen candidate evidence.

    Raises:
        FileExistsError: If the output already exists.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--calls", type=Path, required=True)
    parser.add_argument("--pricing", type=Path, required=True)
    parser.add_argument("--fx", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    book = load_book(cast("Path", args.pricing), cast("Path", args.fx))
    output, calls = cast("Path", args.output), cast("Path", args.calls)
    if output.exists():
        message = "Choose a new output; existing evidence is not overwritten"
        raise FileExistsError(message)
    with (closing(sqlite3.connect(f"file:{calls}?mode=ro", uri=True)) as source,
          closing(sqlite3.connect(output)) as destination):
        destination.execute("""
            CREATE TABLE prices (
                call_key TEXT PRIMARY KEY, price_status TEXT NOT NULL, price_source TEXT,
                long_context INTEGER NOT NULL, price_boundary_day INTEGER NOT NULL,
                standard_usd REAL, write_upper_usd REAL, usd_per_eur REAL, fx_date TEXT,
                standard_eur REAL, write_upper_eur REAL, september6_reference_usd REAL)
        """)
        counts: Counter[str] = Counter()
        query = "SELECT call_key,model,day,uncached,cached,output FROM calls"
        rows = cast("Iterator[tuple[str, str | None, str, int, int, int]]", iter(source.execute(query)))
        for number, row in enumerate(rows, start=1):
            priced = price_call(Call(*row), book)
            destination.execute("INSERT INTO prices VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", priced)
            counts[priced[1]] += 1
            if number % _PROGRESS_EVERY == 0:
                sys.stdout.write(json.dumps({"calls": number, "status": counts}) + "\n")
                sys.stdout.flush()
        destination.commit()
    sys.stdout.write(json.dumps({"complete": True, "calls": sum(counts.values()), "status": counts}) + "\n")


if __name__ == "__main__":
    main()
