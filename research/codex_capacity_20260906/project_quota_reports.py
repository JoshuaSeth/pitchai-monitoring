# Copyright (c) 2026 PitchAI. All rights reserved.
"""Project historical quota reports into anonymous review candidates.

Pipe the approved read-only receipt query into stdin. Raw messages and the alias
mapping are consumed in memory only. The output contains hashes, timestamps,
account aliases, percentages and an allowlisted grammar projection. No candidate
is automatically promoted to a fresh provider observation or a reset action.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from collections import Counter
from typing import TypedDict, cast


class RawReport(TypedDict):
    """Private input boundary, never serialized to the result."""

    reported_at: str
    message: str
    current_requester_route: bool


class Input(TypedDict):
    """Private aliases and scoped receipt rows from the source host."""

    aliases: dict[str, str]
    reports: list[RawReport]


class Candidate(TypedDict):
    """Anonymous numeric statement retained for contextual review."""

    reported_at: str
    message_sha256: str
    line_sha256: str
    line_number: int
    current_requester_route: bool
    accounts: list[str]
    percentages: list[float]
    explicit_instants: list[str]
    grammar: str
    preceding_context: str
    report_windows: list[str]


_PERCENTAGE = re.compile(r"(?<![\d.])([0-9]{1,3}(?:\.[0-9]+)?)\s*%")
_INSTANT = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+]00:00| ?UTC| ?CEST| ?CET)")
_TERMS = (
    r"A\d{2}|[0-9]{1,3}(?:\.[0-9]+)?\s*%|weekly|week|five[ -]?hour|5[ -]?h(?:our)?|"
    r"used|remaining|left|free|available|reset|banked|bank|redeemed|redeem|credit|"
    r"before|after|from|to|all|other[s]?|exhausted|fresh|live|cached|stale|"
    r"no|not|never|none|without|unavailable|unredeemed|cancelled|canceled|"
    r"reported|probe|observed|snapshot|UTC|CET|CEST|today|yesterday|tomorrow|"
    r"codex|chatgpt|quota|subscription|allowance|cpu|memory|disk|storage|tokens|"
    r"performance|profit|margin|gross|revenue|api|invoice|paid"
)
_GRAMMAR = re.compile(r"(?<![\w])(?:" + _TERMS + r")(?![\w])", re.IGNORECASE)
_WINDOW = re.compile(r"(?<!\w)(?:weekly|five[ -]?hour|5[ -]?h(?:our)?)(?!\w)", re.IGNORECASE)


def anonymize(text: str, aliases: dict[str, str]) -> str:
    """Replace exact historical account labels without retaining their spellings.

    Returns:
        Locally redacted text used only for allowlisted token selection.
    """
    result = text
    for label in sorted(aliases, key=len, reverse=True):
        result = re.sub(r"(?<!\w)" + re.escape(label) + r"(?!\w)", aliases[label], result, flags=re.IGNORECASE)
    return result


def project(report: RawReport, aliases: dict[str, str]) -> list[Candidate]:
    """Keep quota-shaped lines with account matches and their preceding context.

    Returns:
        Review candidates; time, direction and multiple-account ambiguity remain explicit.
    """
    result: list[Candidate] = []
    raw_lines = report["message"].splitlines()
    lines = [anonymize(line, aliases) for line in raw_lines]
    message_hash = hashlib.sha256(report["message"].encode()).hexdigest()
    report_windows = sorted(set(_WINDOW.findall(report["message"])))
    for index, line in enumerate(lines):
        accounts = sorted(set(re.findall(r"\bA\d{2}\b", line)))
        values = cast("list[str]", _PERCENTAGE.findall(line))
        percentages = [float(value) for value in values]
        context = " ".join(lines[max(0, index - 2):index])
        if not accounts or not percentages:
            continue
        result.append({
            "reported_at": report["reported_at"], "message_sha256": message_hash,
            "line_sha256": hashlib.sha256(raw_lines[index].encode()).hexdigest(),
            "line_number": index + 1, "current_requester_route": report["current_requester_route"],
            "accounts": accounts, "percentages": percentages,
            "explicit_instants": _INSTANT.findall(context + " " + line),
            "grammar": " | ".join(_GRAMMAR.findall(line)),
            "preceding_context": " | ".join(_GRAMMAR.findall(context)),
            "report_windows": report_windows,
        })
    return result


def main() -> None:
    """Read the private stream and emit only the anonymous candidate projection."""
    payload = cast("Input", json.load(sys.stdin))
    candidates: list[Candidate] = []
    report_counts: Counter[str] = Counter()
    for report in payload["reports"]:
        rows = project(report, payload["aliases"])
        candidates.extend(rows)
        report_counts["with_candidates" if rows else "without_candidates"] += 1
    times = [report["reported_at"] for report in payload["reports"]]
    result = {
        "schema": 1, "reports_queried": len(times), "first_report_at": min(times), "last_report_at": max(times),
        "report_classification": dict(report_counts), "candidate_lines": len(candidates),
        "qualification": "Narrative candidates only. Receipt time is not provider observation time. "
                         "Grammar projection omits all nonallowlisted text and cannot resolve every ambiguity.",
        "candidates": candidates,
    }
    sys.stdout.write(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
