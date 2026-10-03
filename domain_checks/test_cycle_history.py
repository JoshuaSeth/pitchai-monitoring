# Copyright (c) 2026 PitchAI. All rights reserved.
"""History boundaries preserve retained identity and effective-health semantics."""

from __future__ import annotations

import unittest
from typing import TYPE_CHECKING

from .common_check import DomainCheckResult
from .cycle_history import record_domain_results
from .dft_test_support import require
from .history_migration import migrate_effective_history
from .signal_history import SignalHistory

if TYPE_CHECKING:
    from .event_bus_delivery import JsonObject
    from .history_decode import Sample


class CycleHistoryTests(unittest.TestCase):
    """Exercise malformed optional values, clock order and independent domains."""

    @staticmethod
    def test_signal_append_preserves_map_list_and_row_identity() -> None:
        """Append retains the caller's row, including repeated legitimate values."""
        rows: list[Sample] = [[1, True]]
        samples = {"signal": rows}
        signals = SignalHistory(samples)
        row: Sample = [2, False]
        signals.append(" signal ", row)
        signals.append("signal", row)
        signals.append("", [3, True])
        signals.append("other", [])
        require(condition=signals.samples is samples and samples["signal"] is rows, message="collections copied")
        require(condition=rows[-1] is row and rows[-2] is row, message="equal samples deduplicated or copied")
        require(condition=set(samples) == {"signal"}, message="empty signal entered history")

    @staticmethod
    def test_signal_pruning_keeps_cutoff_and_original_unsorted_suffix() -> None:
        """Only the prefix before the first qualifying row is removed, without sorting."""
        rows: list[Sample] = [[1, True], [], [None], ["invalid"], [10, False], [2, True]]
        samples = {"signal": rows, "empty": []}
        SignalHistory(samples).prune(before_ts=10)
        require(condition=samples == {"signal": [[10, False], [2, True]]}, message="cutoff or suffix changed")
        require(condition=samples["signal"] is rows, message="pruning replaced retained list")

    @staticmethod
    def test_signal_pruning_removes_exhausted_and_nonfinite_prefixes() -> None:
        """Invalid/NaN rows cannot fabricate a qualifying recent observation."""
        rows: list[Sample] = [[float("nan")], ["bad"], []]
        samples: dict[str, list[Sample]] = {
            "invalid": rows, "old": [[1, True]], "infinite": [[float("inf"), True]],
        }
        SignalHistory(samples).prune(before_ts=2)
        require(condition=set(samples) == {"infinite"}, message="prefix exhaustion semantics changed")

    @staticmethod
    def test_migration_is_debounced_independently_per_domain() -> None:
        """A second domain never inherits another domain's failure/recovery streak."""
        source: JsonObject = {"first": [[1, False], [2, False], [3, True], [4, True]], "second": [[1, False]]}
        migrated = migrate_effective_history(source, down_after_failures=2, up_after_successes=2)
        require(condition=[row[1] for row in migrated["first"]] == [True, False, False, True],
                message="effective transition stream changed")
        require(condition=migrated["second"] == [[1, True]], message="domain streak leaked")
        require(condition=source["first"] == [[1, False], [2, False], [3, True], [4, True]],
                message="migration mutated input history")

    @staticmethod
    def test_migration_preserves_order_and_shallow_extra_values() -> None:
        """Migration replaces only effective health, retaining caller-owned extra values."""
        extra: JsonObject = {"synthetic": [1, 2]}
        first: Sample = [9, False, extra]
        second: Sample = [1, True, "extra"]
        source: JsonObject = {"domain": [first, second]}
        rows = migrate_effective_history(source, down_after_failures=1, up_after_successes=1)["domain"]
        require(condition=rows == [first, second] and rows[0] is not first, message="row conversion changed order")
        require(condition=rows[0][2] is extra, message="nested extra value copied")

    @staticmethod
    def test_migration_omits_empty_and_malformed_json_rows() -> None:
        """Only nonempty named domains with rows of at least two fields survive."""
        source: JsonObject = {"": [[1, True]], "bad": "value", "empty": [], "short": [[], [1]],
                              "valid": [None, "bad", [1, False]]}
        result = migrate_effective_history(source, down_after_failures=1, up_after_successes=1)
        require(condition=result == {"valid": [[1, False]]}, message="invalid migration rows survived")

    @staticmethod
    def test_domain_sample_uses_effective_health_and_numeric_fallbacks() -> None:
        """A suppressed flake stays effectively up; a recovering domain stays down."""
        history: dict[str, list[Sample]] = {}
        details: JsonObject = {"http_elapsed_ms": "12.5", "browser_elapsed_ms": [], "status_code": "503"}
        results = {"flake": DomainCheckResult("flake", ok=False, reason="synthetic", details=details),
                   "recovering": DomainCheckResult("recovering", ok=True, reason="synthetic", details={})}
        record_domain_results(history, results, {"flake": True, "recovering": False}, ts=10)
        require(condition=history == {"flake": [[10.0, True, 12.5, None, 503]],
                                      "recovering": [[10.0, False, None, None, None]]},
                message="effective health or optional numeric conversion changed")
        require(condition=details["http_elapsed_ms"] == "12.5", message="result details mutated")

    @staticmethod
    def test_domain_sample_retains_backwards_clock_insertion_and_observed_fallback() -> None:
        """Append still inserts a backdated sample and defaults to observed health."""
        history: dict[str, list[Sample]] = {"domain": [[20, True, None, None, None]]}
        rows = history["domain"]
        result = DomainCheckResult("domain", ok=False, reason="synthetic", details={"status_code": float("inf")})
        record_domain_results(history, {"domain": result}, {}, ts=10)
        require(condition=history["domain"] is rows, message="history list replaced")
        require(condition=rows == [[10.0, False, None, None, None], [20, True, None, None, None]],
                message="backwards clock or observed fallback changed")
