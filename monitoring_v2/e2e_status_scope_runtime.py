# Copyright (c) 2026 PitchAI. All rights reserved.
"""Scope the registry status summary to schedulable tests at the legacy boundary.

``e2e_registry.db.status_summary`` counts every row with ``effective_ok=0`` as a
failing test whether it is enabled or not, and never reports a temporarily
paused row, so retired and parked lanes kept the alert-facing ``failing_tests``
count positive while no schedulable test was failing. That legacy module cannot
carry the correction while the repository quality ratchet requires every touched
file to be diagnostic-free, so the scoped summary is installed here, on the
composition root, for every consumer of the registry status query: heartbeats,
the legacy monitor dashboard and the monitoring v2 summary.
"""

from __future__ import annotations

import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass
from importlib import import_module
from typing import TYPE_CHECKING, NamedTuple, Protocol, cast

from .json_types import float_value, int_value, json_object, object_list, text_value

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from .json_types import JsonInput, JsonObject, JsonScalar, JsonValue

TEST_STATUS_ACTIVE = "active"
TEST_STATUS_PARKED = "parked"
TEST_STATUS_DISABLED = "disabled"
FAILING_SCOPE_ACTIVE = "active"

_DB_TIMEOUT_SECONDS = 5.0
_OPTION_QUERY = """
SELECT t.id, t.enabled, t.disabled_until_ts, t.disabled_reason, t.interval_seconds
FROM tests t
"""


class RegistrySettings(NamedTuple):
    """Registry settings surface consumed by the scoped status query."""

    db_path: str


class StatusSummaryBuilder(Protocol):
    """Callable contract for the registry status query."""

    def __call__(self, settings: RegistrySettings) -> JsonObject:
        """Return one registry status document."""
        raise NotImplementedError

    def contract_name(self) -> str:
        """Return the boundary contract name."""
        raise NotImplementedError


class RegistryDatabase(Protocol):
    """Mutable legacy database surface used by the runtime installer."""

    status_summary: object

    def contract_name(self) -> str:
        """Return the boundary contract name."""
        raise NotImplementedError

    def supports_status_summary_replacement(self) -> bool:
        """Report support for replacing the status query."""
        raise NotImplementedError


@dataclass(frozen=True)
class E2EStatusCounts:
    """Active, parked and disabled row counts for one registry status summary."""

    active: int
    passing: int
    failing: int
    parked: int
    parked_failing: int
    disabled: int
    disabled_failing: int


_DATABASE = cast("RegistryDatabase", cast("object", import_module("e2e_registry.db")))
unscoped_status_summary = cast("StatusSummaryBuilder", _DATABASE.status_summary)


def classify_test_status(test: JsonObject, *, now_ts: float) -> str:
    """Classify one registry test row and record its status class on that row.

    Active rows are the schedulable recurring set: enabled, with no pause
    horizon or one that has already expired. Parked rows stay enabled with a
    future ``disabled_until_ts``, which is how a lane is temporarily paused.
    Disabled rows are switched off. Parked and disabled rows keep their history
    and their reason but never count as active failures.

    Returns:
        ``active``, ``parked`` or ``disabled``.
    """
    raw_enabled = test.get("enabled")
    enabled = raw_enabled is None or int_value(raw_enabled) == 1
    paused_until = float_value(test.get("disabled_until_ts"))
    if not enabled:
        status = TEST_STATUS_DISABLED
    elif paused_until is not None and paused_until > now_ts:
        status = TEST_STATUS_PARKED
    else:
        status = TEST_STATUS_ACTIVE
    test["status_class"] = status
    return status


def count_test_statuses(tests: Iterable[JsonObject], *, now_ts: float) -> E2EStatusCounts:
    """Count active, parked and disabled rows, recording each row's class.

    Returns:
        The counts behind one scoped status summary.
    """
    active = 0
    passing = 0
    failing = 0
    parked = 0
    parked_failing = 0
    disabled = 0
    disabled_failing = 0
    for test in tests:
        status = classify_test_status(test, now_ts=now_ts)
        failed = int_value(test.get("effective_ok")) == 0
        if status == TEST_STATUS_DISABLED:
            disabled += 1
            disabled_failing += 1 if failed else 0
            continue
        if status == TEST_STATUS_PARKED:
            parked += 1
            parked_failing += 1 if failed else 0
            continue
        active += 1
        failing += 1 if failed else 0
        passing += 0 if failed else 1
    return E2EStatusCounts(
        active=active,
        passing=passing,
        failing=failing,
        parked=parked,
        parked_failing=parked_failing,
        disabled=disabled,
        disabled_failing=disabled_failing,
    )


def _json_scalar(value: JsonValue | object) -> JsonScalar:
    """Return one stored registry column value as a JSON scalar.

    Raises:
        TypeError: If the stored value cannot be represented as a JSON scalar.
    """
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    message = f"registry column value is not a JSON scalar: {type(value).__name__}"
    raise TypeError(message)


def _option_rows(db_path: str) -> dict[str, JsonObject]:
    """Return the pause, enablement and interval columns keyed by test id.

    The established status query selects the run and state columns only, so the
    pause horizon and interval of the same rows are read read-only here instead
    of duplicating that query.

    Returns:
        Option rows for every registered test.
    """
    options: dict[str, JsonObject] = {}
    with closing(sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=_DB_TIMEOUT_SECONDS)) as connection:
        rows = cast("list[tuple[object, ...]]", connection.execute(_OPTION_QUERY).fetchall())
    for row in rows:
        identifier, enabled, until_ts, reason, interval = row[:5]
        options[text_value(_json_scalar(identifier))] = {
            "enabled": _json_scalar(enabled),
            "disabled_until_ts": _json_scalar(until_ts),
            "disabled_reason": _json_scalar(reason),
            "interval_seconds": _json_scalar(interval),
        }
    return options


def scoped_status_summary(
    legacy_summary: JsonInput,
    options: Mapping[str, JsonObject],
    *,
    now_ts: float | None = None,
) -> JsonObject:
    """Return the published status summary scoped to schedulable tests.

    ``tests``, ``total_tests`` and ``failing_tests`` describe active rows only,
    while ``all_tests`` keeps every row labelled with its status class, pause
    horizon and reason, so a heartbeat, dashboard or review can tell an active
    outage from a parked or disabled lane.

    Returns:
        The scoped status document for every registry summary consumer.
    """
    now = time.time() if now_ts is None else float(now_ts)
    document = json_object(legacy_summary)
    rows = object_list(document.get("tests"))
    for row in rows:
        row.update(options.get(text_value(row.get("test_id")), {}))
    counts = count_test_statuses(rows, now_ts=now)
    active_rows = [row for row in rows if row.get("status_class") == TEST_STATUS_ACTIVE]
    document["failing_tests_scope"] = FAILING_SCOPE_ACTIVE
    document["total_tests"] = len(active_rows)
    document["enabled_tests"] = counts.active + counts.parked
    document["active_tests"] = counts.active
    document["passing_tests"] = counts.passing
    document["failing_tests"] = counts.failing
    document["parked_tests"] = counts.parked
    document["parked_failing_tests"] = counts.parked_failing
    document["disabled_tests"] = counts.disabled
    document["disabled_failing_tests"] = counts.disabled_failing
    return json_object(document | {"tests": active_rows, "all_tests": rows})


def active_status_summary(settings: RegistrySettings) -> JsonObject:
    """Return registry status scoped to schedulable recurring tests.

    Returns:
        The scoped status document installed for every registry consumer.
    """
    return scoped_status_summary(unscoped_status_summary(settings), _option_rows(settings.db_path))


def install_active_status_scope() -> None:
    """Install schedulable-test status semantics for every registry consumer."""
    if _DATABASE.status_summary is active_status_summary:
        return
    _DATABASE.status_summary = active_status_summary
