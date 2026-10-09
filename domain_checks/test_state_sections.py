# Copyright (c) 2026 PitchAI. All rights reserved.
"""State defaults and decoded health sections remain independent on restart."""

from __future__ import annotations

import unittest
from typing import TYPE_CHECKING

from .dft_test_support import require
from .state_sections import decode_health_sections, default_monitor_state

if TYPE_CHECKING:
    from .event_bus_delivery import JsonObject


class TestStateSections(unittest.TestCase):
    """Guard all health shapes, restart defaults and mutable-state ownership."""

    @staticmethod
    def test_defaults_preserve_schema_and_allocate_independent_sections() -> None:
        """Changing one instance or section must not change another's counters.

        Raises:
            TypeError: The default health section is not a mapping.
        """
        first, second = default_monitor_state(), default_monitor_state()
        schema_version = 6
        require(condition=first == second and first["version"] == schema_version
                and first["history_ok_mode"] == "effective",
                message="persisted schema defaults changed")
        health = first["host_health"]
        if not isinstance(health, dict):
            message = "host health default is not an object"
            raise TypeError(message)
        health["last_ok"] = False
        require(condition=second["host_health"] != health and first["performance"] == second["performance"],
                message="health defaults share mutable state")
        expected: JsonObject = {"last_ok": {}, "fail_streak": {}, "success_streak": {}, "last_run_ts": {}}
        for name in ("synthetic", "web_vitals", "api_contract"):
            require(condition=first[name] == expected,
                    message="per-domain section defaults changed")
        outbox, events = first["event_bus_outbox"], first["events"]
        require(condition=isinstance(outbox, list) and not outbox and isinstance(events, list) and not events,
                message="fresh state fabricated an incident")

    @staticmethod
    def test_global_sections_decode_only_their_owned_fields() -> None:
        """Special CPU, DNS, restart and write counters survive independently."""
        raw: JsonObject = {}
        names = ("host_health", "performance", "slo", "tls", "dns", "red", "container_health", "proxy", "meta")
        for name in names:
            raw[name] = {"last_ok": False, "fail_streak": "3", "success_streak": "bad", "last_run_ts": "12.5",
                         "cpu_prev_total": "8", "cpu_prev_idle": 4, "last_ips": {"first": [" a ", "a"]},
                         "restart_counts": {"container": "7"}, "state_write_fail_streak": "2", "unknown": "omit"}
        result = decode_health_sections(raw)
        base: JsonObject = {"last_ok": False, "fail_streak": 3, "success_streak": 0}
        require(condition=result["performance"] == base and result["proxy"] == base and result["slo"] == base,
                message="basic health state changed")
        require(condition=result["red"] == base and result["tls"] == {**base, "last_run_ts": 12.5},
                message="timed health state changed")
        require(condition=result["host_health"] == {**base, "cpu_prev_total": 8, "cpu_prev_idle": 4},
                message="CPU delta state changed")
        require(condition=result["dns"] == {**base, "last_run_ts": 12.5, "last_ips": {"first": ["a", "a"]}},
                message="DNS comparison state changed")
        container_expected: JsonObject = {**base, "last_run_ts": 12.5, "restart_counts": {"container": 7}}
        require(condition=result["container_health"] == container_expected,
                message="container restart count changed")
        require(condition=result["meta"] == {**base, "state_write_fail_streak": 2},
                message="write-fault streak changed")

    @staticmethod
    def test_per_domain_sections_do_not_share_recovery_or_scheduling_state() -> None:
        """Each probe family preserves its own health and last-run timestamps."""
        raw: JsonObject = {"synthetic": {"last_ok": {"a": False, "b": "false"}, "fail_streak": {"a": "2"},
                                         "success_streak": {"a": 1}, "last_run_ts": {"a": "10.5"}},
                           "web_vitals": {"last_ok": {"a": True}}, "api_contract": {"last_run_ts": {"b": "20"}}}
        result = decode_health_sections(raw)
        require(condition=result["synthetic"] == {"last_ok": {"a": False}, "fail_streak": {"a": 2},
                                                  "success_streak": {"a": 1}, "last_run_ts": {"a": 10.5}},
                message="synthetic probe restart state changed")
        require(condition=result["web_vitals"] == {"last_ok": {"a": True}, "fail_streak": {},
                                                   "success_streak": {}, "last_run_ts": {}},
                message="web-vitals probe inherited another family")
        require(condition=result["api_contract"] == {"last_ok": {}, "fail_streak": {},
                                                     "success_streak": {}, "last_run_ts": {"b": 20.0}},
                message="contract probe schedule changed")

    @staticmethod
    def test_missing_or_malformed_sections_keep_defaults() -> None:
        """Invalid section shapes cannot make other monitors unavailable."""
        raw: JsonObject = {"host_health": None, "proxy": "false", "api_contract": [], "unknown": {}}
        require(condition=not decode_health_sections(raw), message="invalid section replaced a default")
        require(condition=decode_health_sections({"performance": {"last_ok": "false"}}) == {
            "performance": {"last_ok": True, "fail_streak": 0, "success_streak": 0},
        }, message="truthy string changed default health")
