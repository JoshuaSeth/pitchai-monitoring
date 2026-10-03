# Copyright (c) 2026 PitchAI. All rights reserved.
"""Format an already observed external E2E summary without requesting one."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from .cycle_values import coerce_int, required_float
from .message_performance import format_ms

if TYPE_CHECKING:
    from .event_bus_delivery import JsonObject


def external_lines(summary: JsonObject) -> list[str]:
    """Return existing external status, bounded failures and stable slowest rows."""
    if not bool(summary.get("ok", True)):
        lines = ["", "External E2E tests: ERROR"]
        error = summary.get("error")
        if isinstance(error, str) and error.strip():
            lines.append(f"- {error.strip()[:300]}")
        return lines
    total = coerce_int(summary.get("total_tests") or 0)
    failing = coerce_int(summary.get("failing_tests") or 0)
    status = "OK" if failing <= 0 else "DEGRADED"
    lines = ["", f"External E2E tests: {status} (failing={failing}/{total})"]
    tests = summary.get("tests")
    if isinstance(tests, list) and tests:
        # The existing registry contract provides object rows. A malformed row
        # still fails at its field access rather than being silently discarded.
        rows = cast("list[JsonObject]", tests)
        lines.extend(_failing_lines(rows))
        lines.extend(_slow_lines(rows))
    return lines


def _test_name(test: JsonObject) -> str:
    return str(test.get("test_name") or test.get("name") or test.get("test_id") or "test")


def _failing_lines(tests: list[JsonObject]) -> list[str]:
    failures: list[JsonObject] = []
    for test in tests:
        value = test.get("effective_ok")
        effective = 1 if value is None else coerce_int(value, default=1)
        if effective == 0:
            failures.append(test)
    if not failures:
        return []
    lines = ["- Failing:"]
    for test in failures[:5]:
        status = test.get("last_status") or "?"
        milliseconds = format_ms(test.get("last_elapsed_ms"))
        lines.append(f"  - {_test_name(test)}: {status} ({milliseconds})")
    return lines


def _slow_lines(tests: list[JsonObject]) -> list[str]:
    timed = [test for test in tests if test.get("last_elapsed_ms") is not None]
    slow = sorted(timed, key=lambda test: required_float(test.get("last_elapsed_ms") or 0.0), reverse=True)
    if not slow:
        return []
    lines = ["- Slowest:"]
    lines.extend(f"  - {_test_name(test)}: {format_ms(test.get('last_elapsed_ms'))}" for test in slow[:3])
    return lines
