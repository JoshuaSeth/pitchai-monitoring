# Copyright (c) 2026 PitchAI. All rights reserved.
"""Proof of the per-request token arithmetic for cumulative and per-turn counters."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ._timeseries_test_fixtures import check, check_equal
from .token_ledger.rollout import FileState, usage_delta

if TYPE_CHECKING:
    from .timeseries_types import JsonObject


def test_forked_rollout_with_inherited_counter_counts_only_its_own_requests() -> None:
    """Prove a fork that starts from its parent's cumulative total is not counted in full."""
    state = FileState()
    inherited: JsonObject = {
        "total_token_usage": {
            "input_tokens": 9_000_000,
            "cached_input_tokens": 8_000_000,
            "output_tokens": 50_000,
            "total_tokens": 9_050_000,
        },
        "last_token_usage": {
            "input_tokens": 120_000,
            "cached_input_tokens": 100_000,
            "output_tokens": 500,
            "total_tokens": 120_500,
        },
    }
    check_equal(usage_delta(state, inherited), (120_000, 100_000, 500, 0, 120_500), "first event of a fork")
    following: JsonObject = {
        "total_token_usage": {
            "input_tokens": 9_130_000,
            "cached_input_tokens": 8_110_000,
            "output_tokens": 50_700,
            "total_tokens": 9_180_700,
        },
        "last_token_usage": {
            "input_tokens": 130_000,
            "cached_input_tokens": 110_000,
            "output_tokens": 700,
            "total_tokens": 130_700,
        },
    }
    check_equal(usage_delta(state, following), (130_000, 110_000, 700, 0, 130_700), "next event uses the delta")


def test_cumulative_deltas_skip_repeats_and_survive_counter_reset() -> None:
    """Prove cumulative deltas skip repeats and survive counter reset."""
    state = FileState()
    first: JsonObject = {
        "total_token_usage": {"input_tokens": 100, "cached_input_tokens": 40, "output_tokens": 5, "total_tokens": 105},
    }
    check_equal(usage_delta(state, first), (100, 40, 5, 0, 105), "first cumulative total is counted whole")
    check(usage_delta(state, first) is None, "a repeated cumulative total is skipped")
    second: JsonObject = {
        "total_token_usage": {"input_tokens": 160, "cached_input_tokens": 90, "output_tokens": 9, "total_tokens": 169},
    }
    check_equal(usage_delta(state, second), (60, 50, 4, 0, 64), "a higher total counts only the delta")
    reset: JsonObject = {
        "total_token_usage": {"input_tokens": 10, "cached_input_tokens": 0, "output_tokens": 1, "total_tokens": 11},
    }
    check_equal(usage_delta(state, reset), (10, 0, 1, 0, 11), "a lower total is a counter reset")
    claude: JsonObject = {
        "last_token_usage": {"input_tokens": 7, "cached_input_tokens": 3, "output_tokens": 2, "total_tokens": 9},
    }
    check_equal(usage_delta(FileState(), claude), (7, 3, 2, 0, 9), "per-request usage is counted as is")
