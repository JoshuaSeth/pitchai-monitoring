# Copyright (c) 2026 PitchAI. All rights reserved.
"""Restarted browser admission keeps persisted ages and explicit failure edges."""

from __future__ import annotations

import unittest

from .browser_state import browser_state_snapshot, restore_browser_state
from .dft_test_support import require, require_error


class BrowserStateTests(unittest.TestCase):
    """Separate persisted incident evidence from process-local retries."""

    @staticmethod
    def test_restart_retains_ages_and_clears_only_process_counters() -> None:
        """Restart cannot claim recovery, renew age or erase the bounded failure."""
        state = restore_browser_state({
            "browser_degraded_active": True, "browser_degraded_first_seen_ts": 100,
            "browser_degraded_last_notice_ts": 200, "browser_launch_last_error": "failure",
            "browser_degraded_recover_streak": 4, "browser_launch_fail_count": 9,
            "browser_launch_next_try_ts": 999,
        }, "1024")
        expected = {"browser_degraded_active": True, "browser_degraded_first_seen_ts": 100.0,
                    "browser_degraded_last_notice_ts": 200.0, "browser_launch_last_error": "failure"}
        require(condition=browser_state_snapshot(state) == expected, message="restart changed persisted evidence")
        process = (state["browser_degraded_recover_streak"], state["browser_launch_fail_count"],
                   state["browser_launch_next_try_ts"], state["browser_min_mem_available_mb"])
        require(condition=process == (0, 0, 0.0, 1024), message="process defaults changed")

    @staticmethod
    def test_first_seen_fallback_does_not_hide_invalid_notice_time() -> None:
        """Preserve the different error policy of the two retained timestamps."""
        state = restore_browser_state({"browser_degraded_first_seen_ts": "bad"}, "bad")
        require(condition=(state["browser_degraded_first_seen_ts"], state["browser_min_mem_available_mb"])
                == (0.0, 2048), message="legacy startup fallback changed")
        with require_error(ValueError, "float"):
            _ = restore_browser_state({"browser_degraded_last_notice_ts": "bad"}, 0)

    @staticmethod
    def test_memory_bounds_and_binary_yaml_scalar_keep_conversion() -> None:
        """The environment/config value keeps integer conversion and its minimum."""
        expected = {-4: 0, "3": 3, b"7": 7, "bad": 2048}
        for value, minimum in expected.items():
            state = restore_browser_state({}, value)
            require(condition=state["browser_min_mem_available_mb"] == minimum, message="memory minimum changed")

    @staticmethod
    def test_error_bound_and_post_admission_snapshot_keep_current_values() -> None:
        """The snapshot sees subsequent mutations without persisting retry counters."""
        error = "x" * 900
        state = restore_browser_state({"browser_launch_last_error": error}, 0)
        require(condition=state["browser_launch_last_error"] == error[:800], message="error bound changed")
        state.update(browser_degraded_active=True, browser_degraded_last_notice_ts=450.0,
                     browser_launch_last_error=" ", browser_launch_fail_count=8)
        expected = {"browser_degraded_active": True, "browser_degraded_first_seen_ts": 0.0,
                    "browser_degraded_last_notice_ts": 450.0, "browser_launch_last_error": " "}
        require(condition=browser_state_snapshot(state) == expected, message="snapshot lost phase mutation")
