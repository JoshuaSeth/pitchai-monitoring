# Copyright (c) 2026 PitchAI. All rights reserved.
"""Independent monitor domains retain their own debounced health state."""

from __future__ import annotations

import unittest

from .alert_transition import HealthObservation, update_effective_ok
from .dft_test_support import require


class TestAlertTransition(unittest.TestCase):
    """Cover repeated failures, interrupted recovery and threshold clamping."""

    @staticmethod
    def test_interrupted_recovery_needs_consecutive_successes() -> None:
        """A clean sample alone cannot close a two-success recovery policy."""
        observation = HealthObservation(prev_effective_ok=True, observed_ok=True, fail_streak=0,
                                        success_streak=0, down_after_failures=2, up_after_successes=2)
        observed = [False, False, False, True, False, True, True]
        expected = [
            (True, 1, 0, False), (False, 2, 0, True), (False, 3, 0, False),
            (False, 0, 1, False), (False, 1, 0, False), (False, 0, 1, False), (True, 0, 2, False),
        ]
        for healthy, result in zip(observed, expected, strict=True):
            observation["observed_ok"] = healthy
            actual = update_effective_ok(**observation)
            require(condition=actual == result, message="consecutive-health transition changed")
            observation["prev_effective_ok"], observation["fail_streak"], observation["success_streak"] = actual[:3]

    @staticmethod
    def test_domains_do_not_share_streaks_and_inputs_are_unchanged() -> None:
        """One domain's failure does not consume another domain's recovery."""
        failed = HealthObservation(prev_effective_ok=True, observed_ok=False, fail_streak=1,
                                   success_streak=0, down_after_failures=2, up_after_successes=2)
        recovering = HealthObservation(prev_effective_ok=False, observed_ok=True, fail_streak=0,
                                       success_streak=1, down_after_failures=2, up_after_successes=2)
        require(condition=update_effective_ok(**failed) == (False, 2, 0, True), message="DOWN edge lost")
        require(condition=update_effective_ok(**recovering) == (True, 0, 2, False), message="recovery changed")
        require(condition=failed["fail_streak"] == 1 and recovering["success_streak"] == 1,
                message="observation input was mutated")

    @staticmethod
    def test_nonpositive_thresholds_still_require_one_observation() -> None:
        """Legacy zero/negative limits clamp to one, without instant recovery."""
        for threshold in (0, -3):
            observation = HealthObservation(prev_effective_ok=True, observed_ok=False, fail_streak=0,
                                            success_streak=5, down_after_failures=threshold,
                                            up_after_successes=threshold)
            require(condition=update_effective_ok(**observation) == (False, 1, 0, True),
                    message="nonpositive failure threshold changed")
            observation.update(prev_effective_ok=False, observed_ok=True, fail_streak=6, success_streak=0)
            require(condition=update_effective_ok(**observation) == (True, 0, 1, False),
                    message="nonpositive recovery threshold changed")
