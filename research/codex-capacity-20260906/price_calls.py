"""Price disjoint observed tokens using dated reference rates and daily ECB FX.

Standard API value is a comparison, not a claim about the call's actual service
tier or the subscription invoice. Cache-write telemetry is missing; an explicit
upper sensitivity assigns the published 25% premium to all uncached input only
for models that support it. No extra reasoning-output charge is added.
"""

import argparse
import bisect
import collections
import csv
import json
import pathlib
import sqlite3


def applicable_rate(rates, model, day):
    """Do not apply prices before documented API availability or alias unknowns."""
    matches = [
        rate for rate in rates
        if rate["model"] == model and rate["from_inclusive"] <= day
        and (rate["until_exclusive"] is None or day < rate["until_exclusive"])
    ]
    if len(matches) > 1:
        raise ValueError("Overlapping price periods")
    return matches[0] if matches else None


def value(rate, uncached, cached, output, long_context):
    """Price the entire request at its applicable context rate."""
    input_factor, output_factor = (2, 1.5) if long_context else (1, 1)
    input_cost = uncached * rate["input"] * input_factor / 1_000_000
    cost = input_cost + (cached * rate["cached"] * input_factor + output * rate["output"] * output_factor) / 1_000_000
    write_premium = input_cost * 0.25 if rate["cache_write_premium"] else 0
    return cost, cost + write_premium


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--calls", type=pathlib.Path, required=True)
    parser.add_argument("--pricing", type=pathlib.Path, required=True)
    parser.add_argument("--fx", type=pathlib.Path, required=True)
    parser.add_argument("--output", type=pathlib.Path, required=True)
    args = parser.parse_args()
    specification = json.loads(args.pricing.read_text())
    rates = specification["rates"]
    with args.fx.open() as stream:
        fx = {row["date"]: float(row["usd_per_eur"]) for row in csv.DictReader(stream)}
    fx_days = sorted(fx)
    long_models = set(specification["long_context_rule"]["models"])
    threshold = specification["long_context_rule"]["threshold_input_tokens"]
    source = sqlite3.connect(f"file:{args.calls}?mode=ro", uri=True)
    if args.output.exists():
        raise FileExistsError("Choose a new output; existing evidence is not overwritten")
    destination = sqlite3.connect(args.output)
    destination.execute("""
        CREATE TABLE prices (
            call_key TEXT PRIMARY KEY, price_status TEXT NOT NULL, price_source TEXT,
            long_context INTEGER NOT NULL, price_boundary_day INTEGER NOT NULL,
            standard_usd REAL, write_upper_usd REAL, usd_per_eur REAL, fx_date TEXT,
            standard_eur REAL, write_upper_eur REAL, september6_reference_usd REAL)
    """)
    counts = collections.Counter()
    query = "SELECT call_key,model,day,uncached,cached,output FROM calls"
    for number, (key, model, day, uncached, cached, output) in enumerate(source.execute(query), start=1):
        long_context = model in long_models and uncached + cached > threshold
        rate = applicable_rate(rates, model, day)
        fx_index = bisect.bisect_right(fx_days, day) - 1
        fx_day = fx_days[fx_index] if fx_index >= 0 else None
        exchange = fx[fx_day] if fx_day else None
        status = "dated_standard_reference"
        standard = upper = price_source = None
        boundary_day = False
        if rate is None:
            status = "no_supported_model_date_price"
        else:
            standard, upper = value(rate, uncached, cached, output, long_context)
            price_source = rate["price_source"]
            boundary_day = day == rate["from_inclusive"]
            if price_source == "api_pricing":
                status = "retrospective_rate_historical_continuity_unproved"
        current_rate = applicable_rate(rates, model, "2026-09-06")
        reference = value(current_rate, uncached, cached, output, long_context)[0] if current_rate else None
        standard_eur = standard / exchange if standard is not None and exchange else None
        upper_eur = upper / exchange if upper is not None and exchange else None
        destination.execute("INSERT INTO prices VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (
            key, status, price_source, int(long_context), int(boundary_day),
            standard, upper, exchange, fx_day, standard_eur, upper_eur, reference,
        ))
        counts[status] += 1
        if number % 250000 == 0:
            print(json.dumps({"calls": number, "status": counts}), flush=True)
    destination.commit()
    print(json.dumps({"complete": True, "calls": sum(counts.values()), "status": counts}), flush=True)
    destination.close()
    source.close()


if __name__ == "__main__":
    main()
