# Copyright (c) 2026 PitchAI. All rights reserved.
"""Restart and transition contracts for independently owned metric counters."""

from __future__ import annotations

import unittest

from .alert_settings import AlertSettings
from .dft_test_support import require
from .health_state import HealthState


class TestHealthState(unittest.TestCase):
    """Exercise interrupted recovery and independent persisted section state."""

    @staticmethod
    def test_restart_requires_remaining_successes_and_emits_only_one_down_edge() -> None:
        """A cold restart preserves the unresolved state and its partial streak."""
        thresholds = AlertSettings(enabled=True, down_after_failures=2, up_after_successes=3,
                                   dispatch_on_degraded=False, notify_on_recovery=False)
        state = HealthState()
        observations = (False, False, False, True, False, True, True, True)
        expected_health = (True, False, False, False, False, False, False, True)
        edges: list[bool] = []
        for index, (observed, expected) in enumerate(zip(observations, expected_health, strict=True)):
            if index:
                state = HealthState.from_section(state.to_state())
            edges.append(state.advance(observed_ok=observed, thresholds=thresholds))
            require(condition=state.last_ok is expected, message="restart changed debounce state")
        require(condition=edges == [False, True, False, False, False, False, False, False],
                message="repeated failures created another DOWN edge")
        require(condition=state.to_state() == {"last_ok": True, "fail_streak": 0, "success_streak": 3},
                message="recovery counters changed")

    @staticmethod
    def test_loading_keeps_only_owned_fields_without_changing_input() -> None:
        """Unrelated timestamps, addresses and fault counts stay with their owner."""
        raw = {"last_ok": "false", "fail_streak": "4", "success_streak": "bad", "state_write_fail_streak": "9"}
        before = dict(raw)
        state = HealthState.from_section(raw)
        require(condition=state.to_state() == {"last_ok": True, "fail_streak": 4, "success_streak": 0},
                message="persisted conversion/defaults changed")
        require(condition=raw == before, message="decoding mutated source state")

    @staticmethod
    def test_invalid_counters_keep_original_defaults() -> None:
        """Invalid numbers default independently; a false boolean stays DOWN."""
        state = HealthState.from_section({"last_ok": False, "fail_streak": [1], "success_streak": float("inf")})
        require(condition=state.to_state() == {"last_ok": False, "fail_streak": 0, "success_streak": 0},
                message="invalid persisted counters changed effective health")
        require(condition=HealthState.from_section({}).to_state() == HealthState().to_state(),
                message="missing counter defaults differ")

    @staticmethod
    def test_instances_and_snapshots_never_share_mutable_health() -> None:
        """Changing one family cannot alter another family or a retained snapshot."""
        first, second = HealthState(), HealthState()
        snapshot = first.to_state()
        thresholds = AlertSettings(enabled=True, down_after_failures=1, up_after_successes=1,
                                   dispatch_on_degraded=True, notify_on_recovery=True)
        edge = first.advance(observed_ok=False, thresholds=thresholds)
        require(condition=edge and not first.last_ok and second.last_ok,
                message="independent monitor state leaked")
        snapshot["last_ok"] = False
        require(condition=second.to_state() == {"last_ok": True, "fail_streak": 0, "success_streak": 0},
                message="snapshot aliases live counters")

    @staticmethod
    def test_empty_observation_does_not_advance_recovery() -> None:
        """Serialization and repeated loading are not successful observations."""
        state = HealthState(last_ok=False, fail_streak=0, success_streak=1)
        expected = state.to_state()
        for _ in range(3):
            state = HealthState.from_section(state.to_state())
        require(condition=state.to_state() == expected and not state.last_ok,
                message="loading or saving fabricated a healthy observation")

    @staticmethod
    def test_zero_thresholds_retain_minimum_one_and_ignore_routing_flags() -> None:
        """Caller-supplied thresholds retain the transition's original clamping."""
        thresholds = AlertSettings(enabled=False, down_after_failures=0, up_after_successes=-2,
                                   dispatch_on_degraded=False, notify_on_recovery=False)
        state = HealthState()
        require(condition=state.advance(observed_ok=False, thresholds=thresholds) and not state.last_ok,
                message="minimum DOWN threshold changed")
        require(condition=not state.advance(observed_ok=True, thresholds=thresholds) and state.last_ok,
                message="minimum recovery threshold changed")
