# Copyright (c) 2026 PitchAI. All rights reserved.
"""History extraction preserves restart, cutoff and metric semantics."""

from __future__ import annotations

import math
import unittest
from typing import TYPE_CHECKING

from .dft_test_support import require
from .history import (
    append_sample,
    coerce_history,
    compute_availability,
    compute_burn_rate,
    compute_error_rate_percent,
    extract_latency_ms,
    latency_percentile_ms,
    prune_history,
    window_samples,
)

if TYPE_CHECKING:
    from .event_bus_delivery import JsonObject, JsonValue
    from .history import Sample


class TestHistoryContract(unittest.TestCase):
    """Verify behavior needed by domain recovery, dashboards and SLO checks."""

    @staticmethod
    def test_restart_decode_sorts_and_preserves_duplicate_samples() -> None:
        """Malformed fields use legacy fallbacks without losing valid rows."""
        raw: JsonObject = {"first": [[2, False, "1.5", "bad", 502], ["1", 1, 0, 3, "200"],
                                     [1, False, None, None], [{}, True], None, [], [3]],
                           "second": [[4, False]], "empty": [], "": [[1, True]]}
        expected: dict[str, list[Sample]] = {
            "first": [[1.0, True, 0.0, 3.0, 200], [1.0, False, None, None, None], [2.0, False, 1.5, None, 502]],
            "second": [[4.0, False, None, None, None]],
        }
        require(condition=coerce_history(raw) == expected, message="restart normalization changed")
        require(condition=not coerce_history(None) and not coerce_history([raw]), message="invalid root accepted")

    @staticmethod
    def test_clock_reversal_uses_existing_equal_timestamp_insertion_rule() -> None:
        """Backwards inserts use the original left boundary; appends keep ties."""
        history: dict[str, list[Sample]] = {}
        for timestamp, healthy in ((5.0, True), (1.0, False), (10.0, True), (5.0, False), (10.0, False)):
            append_sample(history, domain="first", ts=timestamp, ok=healthy,
                          http_elapsed_ms=None, browser_elapsed_ms=None, status_code=None)
        expected: list[Sample] = [[1.0, False, None, None, None], [5.0, False, None, None, None],
                                 [5.0, True, None, None, None], [10.0, True, None, None, None],
                                 [10.0, False, None, None, None]]
        require(condition=history["first"] == expected, message="clock reversal reordered equal timestamps")
        append_sample(history, domain="", ts=3.0, ok=False,
                      http_elapsed_ms=None, browser_elapsed_ms=None, status_code=None)
        require(condition=list(history) == ["first"], message="empty domain created history")

    @staticmethod
    def test_window_and_pruning_keep_cutoff_equality_and_other_domains() -> None:
        """Original timestamps define coverage; a cutoff cannot delete equality."""
        first: list[Sample] = [[1, True, None, None, None], [3, False, None, None, None], [5, True, None, None, None]]
        history: dict[str, list[Sample]] = {"first": first, "second": [[8, True, None, None, None]], "empty": []}
        window = window_samples(first, since_ts=3)
        require(condition=window == first[1:] and window[0] is first[1],
                message="window cutoff or row identity changed")
        prune_history(history, before_ts=3)
        require(condition=history["first"] == window and "empty" not in history, message="pruning boundary changed")
        prune_history(history, before_ts=6)
        require(condition=list(history) == ["second"], message="pruning removed another domain's retained sample")
        require(condition=not window_samples([], since_ts=3), message="empty window fabricated a sample")

    @staticmethod
    def test_empty_metrics_do_not_invent_health_or_latency() -> None:
        """Unavailable coverage retains None, independently of the SLO target."""
        require(condition=compute_availability([]) == (0, 0, None), message="empty history invented availability")
        require(condition=compute_error_rate_percent([]) is None, message="empty history invented zero errors")
        require(condition=compute_burn_rate([], slo_target_percent=99.0) is None, message="empty history invented burn")
        require(condition=latency_percentile_ms([], field="http_elapsed_ms", percentile=95.0) is None,
                message="empty history invented latency")

    @staticmethod
    def test_health_percentages_and_invalid_slo_boundaries_are_unchanged() -> None:
        """Only recorded effective-health values contribute to the percentages."""
        samples: list[Sample] = [[1, True, None, None, None], [2, False, None, None, None]]
        require(condition=compute_availability(samples) == (2, 1, 50.0), message="availability calculation changed")
        errors = compute_error_rate_percent(samples)
        burn = compute_burn_rate(samples, slo_target_percent=99.0)
        require(condition=errors is not None and math.isclose(errors, 50.0), message="error percentage changed")
        require(condition=burn is not None and math.isclose(burn, 50.0), message="burn-rate budget changed")
        for target in (0.0, 100.0, -1.0, float("nan"), float("inf")):
            require(condition=compute_burn_rate(samples, slo_target_percent=target) is None,
                    message="invalid SLO target produced a burn rate")

    @staticmethod
    def test_latency_omission_field_fallback_and_rounded_rank_are_preserved() -> None:
        """Unavailable fields do not become zero, and existing rank rounding stays."""
        raw: list[JsonValue] = [[1, True, "10", "20"], [2, False, "bad", 40], [3, True, 30, None],
                               None, [], [4, True, {}, "bad"]]
        require(condition=extract_latency_ms(raw, field="http_elapsed_ms") == [10.0, 30.0],
                message="HTTP latency filtering changed")
        require(condition=extract_latency_ms(raw, field="unknown") == [20.0, 40.0],
                message="legacy browser field fallback changed")
        samples: list[Sample] = [[1, True, 10, None, None], [2, False, 30, None, None]]
        for percentile, expected in ((-1.0, 10.0), (0.0, 10.0), (50.0, 10.0), (100.0, 30.0), (101.0, 30.0)):
            observed = latency_percentile_ms(samples, field="http_elapsed_ms", percentile=percentile)
            require(condition=observed is not None and math.isclose(observed, expected),
                    message="rounded rank or percentile clamping changed")
