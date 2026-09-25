# Copyright (c) 2026 PitchAI. All rights reserved.
"""Tests for test alerting state behavior."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from domain_checks.main import load_monitor_state, update_effective_ok
from domain_checks.testing import verify

if TYPE_CHECKING:
    from pathlib import Path

_TRANSITION_STREAK = 2


def test_update_effective_ok_debounces_down_and_up() -> None:
    """Verify update effective ok debounces down and up."""
    prev = True
    fail = 0
    succ = 0

    # 1st failure: no alert, still effectively UP (threshold=2)
    prev, fail, succ, alerted = update_effective_ok(
        prev_effective_ok=prev,
        observed_ok=False,
        fail_streak=fail,
        success_streak=succ,
        down_after_failures=_TRANSITION_STREAK,
        up_after_successes=_TRANSITION_STREAK,
    )
    verify(prev is True)
    verify(fail == 1)
    verify(succ == 0)
    verify(alerted is False)

    # 2nd consecutive failure: alert + effectively DOWN
    prev, fail, succ, alerted = update_effective_ok(
        prev_effective_ok=prev,
        observed_ok=False,
        fail_streak=fail,
        success_streak=succ,
        down_after_failures=_TRANSITION_STREAK,
        up_after_successes=_TRANSITION_STREAK,
    )
    verify(prev is False)
    verify(fail == _TRANSITION_STREAK)
    verify(succ == 0)
    verify(alerted is True)

    # 1st success while DOWN: no recovery (threshold=2)
    prev, fail, succ, alerted = update_effective_ok(
        prev_effective_ok=prev,
        observed_ok=True,
        fail_streak=fail,
        success_streak=succ,
        down_after_failures=_TRANSITION_STREAK,
        up_after_successes=_TRANSITION_STREAK,
    )
    verify(prev is False)
    verify(fail == 0)
    verify(succ == 1)
    verify(alerted is False)

    # 2nd consecutive success: recover to UP
    prev, fail, succ, alerted = update_effective_ok(
        prev_effective_ok=prev,
        observed_ok=True,
        fail_streak=fail,
        success_streak=succ,
        down_after_failures=_TRANSITION_STREAK,
        up_after_successes=_TRANSITION_STREAK,
    )
    verify(prev is True)
    verify(fail == 0)
    verify(succ == _TRANSITION_STREAK)
    verify(alerted is False)


def test_load_monitor_state_back_compat_last_ok_only(tmp_path: Path) -> None:
    """Verify load monitor state back compat last ok only."""
    p = tmp_path / "state.json"
    _ = p.write_text(json.dumps({"last_ok": {"a": True}}), encoding="utf-8")
    state = load_monitor_state(p)
    verify(state["last_ok"] == {"a": True})
    verify(not state["fail_streak"])
    verify(not state["success_streak"])
