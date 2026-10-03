# Copyright (c) 2026 PitchAI. All rights reserved.
"""Restart compatibility for independent health, schedule and baseline state."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import TYPE_CHECKING

from .alert_settings import AlertSettings
from .cycle_health_state import CycleHealthState
from .dft_test_support import require
from .monitor_state import load_monitor_state
from .state_storage import write_state_atomic

if TYPE_CHECKING:
    from .event_bus_delivery import JsonObject


def fixture() -> JsonObject:
    """Return distinct persisted values so accidental cross-section reuse fails."""
    result: JsonObject = {}
    names = ("host_health", "performance", "slo", "tls", "dns", "red", "container_health", "proxy", "meta")
    for index, name in enumerate(names):
        result[name] = {"last_ok": False, "fail_streak": index + 1, "success_streak": index + 10,
                        "last_run_ts": float(index * 100), "cpu_prev_total": 1234, "cpu_prev_idle": 234,
                        "last_ips": {"example.invalid": ["192.0.2.1", "192.0.2.1"]},
                        "restart_counts": {"service": 7}, "state_write_fail_streak": 3}
    for index, name in enumerate(("synthetic", "web_vitals", "api_contract")):
        result[name] = {"last_ok": {"example.invalid": False}, "fail_streak": {"example.invalid": index + 1},
                        "success_streak": {"example.invalid": index + 20},
                        "last_run_ts": {"example.invalid": float(index + 30)}}
    return result


class CycleHealthStateTests(unittest.TestCase):
    """Exercise restart values, live references, transient failures and disk bytes."""

    @staticmethod
    def test_sections_and_instances_are_independent() -> None:
        """An empty restart cannot share counters with another monitor family."""
        first, second = CycleHealthState(), CycleHealthState()
        first.restore({})
        second.restore({})
        first.health["host_health"].last_ok = False
        first.probes["synthetic"].fail_streak["example.invalid"] = 3
        first.schedules["tls"].last_run_ts = 123.0
        require(condition=first.health["performance"].last_ok, message='first.health["performance"].last_ok changed')
        require(condition=second.health["host_health"].last_ok, message='second.health["host_health"].last_ok changed')
        require(condition=first.probes["web_vitals"].fail_streak == {}, message="web vitals shared counters")
        require(condition=second.probes["synthetic"].fail_streak == {}, message="second monitor shared counters")
        require(condition=(first.schedules["dns"].last_run_ts,) == (0.0,), message="DNS schedule shared timestamp")

    @staticmethod
    def test_resume_preserves_distinct_counters_and_baselines() -> None:
        """Rehydrate all metric families without renewing their original timestamps."""
        state = CycleHealthState()
        state.restore(fixture())
        actual = (state.host.cpu_prev_total, state.host.cpu_prev_idle, state.write_fail_streak,
                  state.health["meta"].fail_streak, state.schedules["tls"].last_run_ts)
        require(condition=actual == (1234, 234, 3, 9, 300.0), message="restored baselines or counters changed")
        require(condition=state.containers.restart_counts == {"service": 7}, message="restart counts changed")
        expected_ips = {"example.invalid": ["192.0.2.1", "192.0.2.1"]}
        require(condition=state.dns_ips == expected_ips, message="DNS duplicates changed")
        require(condition=state.probes["api_contract"].last_run_ts == {"example.invalid": 32.0},
                message="API timestamp changed")

    @staticmethod
    def test_snapshot_observes_phase_mutation_and_retains_map_aliases() -> None:
        """Capture the actual phase-owned maps without adopting replacement state.

        Raises:
            TypeError: Snapshot sections are no longer JSON objects.
        """
        state = CycleHealthState()
        state.restore(fixture())
        state.health["dns"].success_streak = 88
        state.schedules["dns"].last_run_ts = 990.0
        state.host.cpu_prev_total = 2345
        state.probes["api_contract"].last_run_ts["example.invalid"] = 33.0
        snapshot = state.snapshot(6)
        dns = snapshot["dns"]
        api = snapshot["api_contract"]
        if not isinstance(dns, dict) or not isinstance(api, dict):
            message = "snapshot sections must be JSON objects"
            raise TypeError(message)
        require(condition=dns["last_ips"] is state.dns_ips, message='dns["last_ips"] changed')
        require(condition=api["last_run_ts"] is state.probes["api_contract"].last_run_ts,
                message="API snapshot replaced live mapping")
        require(condition=(dns["success_streak"], dns["last_run_ts"]) == (88, 990.0), message="phase update lost")
        expected_meta = {"last_ok": False, "fail_streak": 9, "success_streak": 18, "state_write_fail_streak": 6}
        require(condition=snapshot["meta"] == expected_meta, message="write-failure update lost")

    @staticmethod
    def test_malformed_sections_keep_original_fallback() -> None:
        """Independent non-mapping sections cannot inject state into another family."""
        state = CycleHealthState()
        state.restore({"host_health": False, "tls": [1], "dns": "bad", "container_health": None,
                       "synthetic": 7, "api_contract": {"last_ok": {"a": "false", "b": False},
                       "fail_streak": {"a": "3", "b": []}, "last_run_ts": {"a": "4.5", "b": {}}}})
        require(condition=state.health["host_health"].last_ok, message='state.health["host_health"].last_ok changed')
        require(condition=(state.schedules["tls"].last_run_ts,) == (0.0,), message="invalid schedule accepted")
        require(condition=not state.dns_ips, message="invalid DNS baseline accepted")
        require(condition=state.probes["synthetic"].last_ok == {}, message='state.probes["synthetic"].last_ok changed')
        api = state.probes["api_contract"]
        require(condition=api.last_ok == {"b": False}, message="invalid boolean accepted")
        require(condition=api.fail_streak == {"a": 3}, message="integer fallback changed")
        require(condition=api.last_run_ts == {"a": 4.5}, message="timestamp fallback changed")

    @staticmethod
    def test_restart_keeps_failure_until_required_recovery_streak() -> None:
        """A healthy observation after restart still needs the configured debounce."""
        state = CycleHealthState()
        state.restore({"host_health": {"last_ok": False, "fail_streak": 2, "success_streak": 0}})
        health = state.health["host_health"]
        thresholds = AlertSettings(enabled=True, down_after_failures=2, up_after_successes=2,
                                   dispatch_on_degraded=False, notify_on_recovery=False)
        require(condition=not health.advance(observed_ok=True, thresholds=thresholds), message="false down edge")
        require(condition=not health.last_ok, message="early recovery")
        restarted = CycleHealthState()
        restarted.restore(state.snapshot(1))
        health = restarted.health["host_health"]
        require(condition=not health.advance(observed_ok=True, thresholds=thresholds),
                message="false recovery down edge")
        require(condition=health.last_ok, message="required recovery missing")
        require(condition=(health.fail_streak, health.success_streak) == (0, 2), message="recovery counters changed")

    @staticmethod
    def test_atomic_state_roundtrip_keeps_schema_and_original_schedule() -> None:
        """Exercise the actual sorted writer/decoder using only a private fixture."""
        state = CycleHealthState()
        state.restore(fixture())
        payload: JsonObject = {"version": 6, "history_ok_mode": "effective", "fail_streak": {}}
        payload.update(state.snapshot(4))
        with tempfile.TemporaryDirectory(prefix="monitor-state-isolated-") as temporary:
            path = Path(temporary) / "state.json"
            write_state_atomic(path, payload)
            expected_bytes = json.dumps(payload, ensure_ascii=False, sort_keys=True)
            require(condition=path.read_text(encoding="utf-8") == expected_bytes, message="persisted bytes changed")
            resumed = CycleHealthState()
            resumed.restore(load_monitor_state(path))
            require(condition=resumed.snapshot(4) == state.snapshot(4), message="roundtrip changed state")
            require(condition=not path.with_name("state.json.tmp").exists(), message="temporary file remained")
