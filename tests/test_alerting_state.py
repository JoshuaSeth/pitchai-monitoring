from __future__ import annotations

import json
from pathlib import Path

from domain_checks.main import _load_monitor_state, _update_effective_ok


def test_update_effective_ok_debounces_down_and_up() -> None:
    prev = True
    fail = 0
    succ = 0

    # 1st failure: no alert, still effectively UP (threshold=2)
    prev, fail, succ, alerted = _update_effective_ok(
        prev_effective_ok=prev,
        observed_ok=False,
        fail_streak=fail,
        success_streak=succ,
        down_after_failures=2,
        up_after_successes=2,
    )
    assert prev is True
    assert fail == 1
    assert succ == 0
    assert alerted is False

    # 2nd consecutive failure: alert + effectively DOWN
    prev, fail, succ, alerted = _update_effective_ok(
        prev_effective_ok=prev,
        observed_ok=False,
        fail_streak=fail,
        success_streak=succ,
        down_after_failures=2,
        up_after_successes=2,
    )
    assert prev is False
    assert fail == 2
    assert succ == 0
    assert alerted is True

    # 1st success while DOWN: no recovery (threshold=2)
    prev, fail, succ, alerted = _update_effective_ok(
        prev_effective_ok=prev,
        observed_ok=True,
        fail_streak=fail,
        success_streak=succ,
        down_after_failures=2,
        up_after_successes=2,
    )
    assert prev is False
    assert fail == 0
    assert succ == 1
    assert alerted is False

    # 2nd consecutive success: recover to UP
    prev, fail, succ, alerted = _update_effective_ok(
        prev_effective_ok=prev,
        observed_ok=True,
        fail_streak=fail,
        success_streak=succ,
        down_after_failures=2,
        up_after_successes=2,
    )
    assert prev is True
    assert fail == 0
    assert succ == 2
    assert alerted is False


def test_load_monitor_state_back_compat_last_ok_only(tmp_path: Path) -> None:
    p = tmp_path / "state.json"
    p.write_text(json.dumps({"last_ok": {"a": True}}), encoding="utf-8")
    state = _load_monitor_state(p)
    assert state["last_ok"] == {"a": True}
    assert state["fail_streak"] == {}
    assert state["success_streak"] == {}

