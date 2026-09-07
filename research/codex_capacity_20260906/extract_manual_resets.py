# Copyright (c) 2026 PitchAI. All rights reserved.
"""Extract allowlisted fields from selected historical tool responses.

Run on the source host with its existing broker history database. Source paths,
call identifiers, arguments and raw outputs are hashed; identities are replaced
using the same sorted broker-reference mapping as the primary extraction.
This program reads files and SQLite only; it never repeats a recorded action.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
from contextlib import closing
from pathlib import Path
from typing import cast

from .input_boundary import InputFailure

type Json = bool | int | float | str | list[Json] | dict[str, Json] | None

_FIELDS = frozenset({
    "account", "label", "before", "after", "immediateAfter", "allowed", "availableCredits", "resetsAt", "usedPercent",
    "consumedExpiry", "outcome", "rateLimitReachedType", "observed_used_percent", "reached_type",
    "available_reset_credits", "observed_at", "consume_outcome", "consumed_credit_expires_at",
    "broker_availability", "broker_weekly", "remaining_reset_credits", "auth_changed_during_consume",
    "completed_at", "credit_expiries", "primary", "windowDurationMins", "target_identity",
    "precondition_weekly_used_percent", "before_available_reset_count", "consume_request_count",
    "consume_status", "after_inventory_status", "after_available_reset_count", "july18_target_present_after",
    "after_usage_status", "after_allowed", "after_limit_reached", "after_five_hour_used_percent",
    "after_weekly_used_percent", "enabled", "availability", "rate_limit_allowed", "rate_limit_reached",
    "five_hour", "weekly_usage", "reset_after_seconds", "reset_at", "used_percent", "last_probe_at", "last_error",
    "limit_window_seconds", "reset_credits", "primary_window", "secondary_window", "rate_limit",
    "available", "banked", "available_count", "expired_count", "supported_by_plan", "redeemable",
    "status", "limit_reached", "five_hour_used_percent", "weekly_used_percent", "weekly_reset_at_epoch_present",
})
_ENUMS = frozenset({"reset", "available", "weekly_limit_reached", "weekly", "pro"})
_INSTANT = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+]00:00)")


def aliases_from_broker(path: Path) -> dict[str, str]:
    """Read the frozen-cutoff identity mapping without exposing its private values.

    Returns:
        Exact private labels mapped to public study aliases.
    """
    with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as connection:
        rows = cast("list[tuple[str, str]]", connection.execute("""
            SELECT DISTINCT account_ref,account_label FROM account_usage_samples
            WHERE sampled_at<'2026-09-06T20:20:00Z' ORDER BY account_ref
        """).fetchall())
    refs = sorted({row[0] for row in rows})
    return {label: f"A{refs.index(ref) + 1:02d}" for ref, label in rows if label}


def sanitize(value: Json, aliases: dict[str, str]) -> Json:
    """Keep only known quota fields and safe scalar values.

    Returns:
        Anonymous structure; unknown strings and fields are explicitly omitted.
    """
    if isinstance(value, dict):
        return {key: sanitize(item, aliases) for key, item in value.items() if key in _FIELDS}
    if isinstance(value, list):
        return [sanitize(item, aliases) for item in value]
    if isinstance(value, str):
        if value in aliases:
            return aliases[value]
        return value if value in _ENUMS or _INSTANT.fullmatch(value) else "[omitted]"
    return value


def response_objects(output: Json) -> list[Json]:
    """Parse complete JSON objects from text blocks, including prefixed log lines.

    Returns:
        Parsed objects without executing any recorded code or parsing Python literals.
    """
    objects: list[Json] = []
    blocks = output if isinstance(output, list) else [{"text": output}]
    for block in blocks:
        if not isinstance(block, dict) or not isinstance(block.get("text"), str):
            continue
        text = cast("str", block["text"])
        complete: Json = None
        with InputFailure(ValueError) as failure:
            complete = cast("Json", json.loads(text))
        if failure.error is not None:
            complete = None
        if isinstance(complete, (list, dict)):
            objects.append(complete)
            continue
        for line in text.splitlines():
            for match in re.finditer(r"[{[]", line):
                value: Json = None
                with InputFailure(ValueError) as failure:
                    value, _ = cast("tuple[Json, int]", json.JSONDecoder().raw_decode(line[match.start():]))
                if failure.error is not None:
                    continue
                objects.append(value)
                break
    return objects


def extract(path: Path, selected: set[int], aliases: dict[str, str]) -> list[dict[str, Json]]:
    """Project selected outputs and their matching recorded invocation times.

    Returns:
        Hash-bound anonymous response projections.

    Raises:
        ValueError: If a selected record is not a tool output or has no invocation.
    """
    calls: dict[str, tuple[str, str]] = {}
    result: list[dict[str, Json]] = []
    with path.open(encoding="utf-8") as stream:
        for number, line in enumerate(stream, 1):
            row = cast("dict[str, Json]", json.loads(line))
            payload = cast("dict[str, Json]", row.get("payload", {}))
            call_id = cast("str", payload.get("call_id", ""))
            kind = payload.get("type")
            if kind in {"function_call", "custom_tool_call"}:
                arguments = json.dumps(payload.get("arguments", payload.get("input")), sort_keys=True)
                calls[call_id] = (cast("str", row["timestamp"]), hashlib.sha256(arguments.encode()).hexdigest())
            if number not in selected:
                continue
            if kind not in {"function_call_output", "custom_tool_call_output"} or call_id not in calls:
                message = "Selected record is not a matched tool response"
                raise ValueError(message)
            invocation = calls[call_id]
            result.append({
                "source_sha256": hashlib.sha256(str(path).encode()).hexdigest(), "line": number,
                "invoked_at": invocation[0], "returned_at": row["timestamp"],
                "arguments_sha256": invocation[1], "record_sha256": hashlib.sha256(line.encode()).hexdigest(),
                "objects": [sanitize(value, aliases) for value in response_objects(payload.get("output"))],
            })
    if len(result) != len(selected):
        message = "Not every selected record was recovered"
        raise ValueError(message)
    return result


def main() -> None:
    """Read selected historical records and emit their safe structured projection."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--lines", required=True, help="Comma-separated one-based source record numbers")
    parser.add_argument("--broker", type=Path, required=True)
    args = parser.parse_args()
    line_parts = cast("str", args.lines).split(",")
    selected = {int(part) for part in line_parts}
    result = extract(cast("Path", args.source), selected, aliases_from_broker(cast("Path", args.broker)))
    sys.stdout.write(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
