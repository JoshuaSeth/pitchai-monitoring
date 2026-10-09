# Copyright (c) 2026 PitchAI. All rights reserved.
"""Isolated response and error contracts for dashboard calculations."""

from __future__ import annotations

import math
import unittest
from copy import deepcopy
from typing import TYPE_CHECKING

import pytest

from domain_checks.dft_test_support import require

from .dashboard_data import MonitorData
from .dashboard_domains import summarize_domains
from .dashboard_e2e import summarize_e2e
from .dashboard_health import summarize_freshness
from .dashboard_records import object_or_empty, required_object
from .dashboard_signals import summarize_signals
from .dashboard_timeseries import domain_timeseries, signal_timeseries
from .monitor_dashboard import build_dashboard_summary

if TYPE_CHECKING:
    from domain_checks.config_values import ConfigValue
    from domain_checks.event_bus_delivery import JsonObject

_NOW = 2_000_000_000.0
_EXPECTED_SERIES_COUNT = 3


class DashboardCalculationTests(unittest.TestCase):
    """Synthetic retained values; no browser, database, service or delivery access."""

    @staticmethod
    def test_subcheck_failure_preserves_primary_and_effective_identity() -> None:
        """A newer API failure cannot be hidden by a passing primary request."""
        state: JsonObject = {
            "history": {"a.invalid": [[_NOW - 60, True, 80, 100, 200]]},
            "api_contract": {"last_ok": {"a.invalid": False}, "last_run_ts": {"a.invalid": _NOW - 10}},
            "synthetic": {"last_ok": {"a.invalid": True}, "last_run_ts": {"a.invalid": _NOW - 20}},
        }
        before = deepcopy(state)
        data = MonitorData(state, {"domains": ["a.invalid"]}, "fixture", "fixture", _NOW, None)
        result = summarize_domains(data=data, now_ts=_NOW)
        require(condition=result[0]["last"] == {
            "ts": _NOW - 10, "primary_ts": _NOW - 60, "ok": False, "primary_ok": True,
            "failure_sources": ["api_contract"], "http_ms": 80.0, "browser_ms": 100.0,
            "status_code": None, "primary_status_code": 200,
        }, message="effective subcheck result lost primary evidence")
        require(condition=state == before, message="summary mutated observations")

    @staticmethod
    def test_inventory_keeps_disabled_and_expected_failure_separate() -> None:
        """Retired history never becomes inventory; policy does not fabricate health."""
        state: JsonObject = {"updated_at": _NOW, "last_ok": {
            "expected.invalid": False, "disabled.invalid": False, "retired.invalid": False,
        }}
        domains: list[ConfigValue] = [
            {"domain": "expected.invalid", "alert_policy": {"telegram": "dashboard-only", "reason": "fixture"}},
            {"domain": "disabled.invalid", "disabled": True}, "unknown.invalid",
        ]
        data = MonitorData(state, {"domains": domains}, "fixture", "fixture", _NOW, None)
        result = build_dashboard_summary(data=data, now_ts=_NOW, e2e_status_summary=None, e2e_dispatch_runs=[])
        require(condition=result["service_health"] == {
            "enabled": 2, "healthy": 0, "down": 1, "alertable_down": 0,
            "expected_down": 1, "unknown": 1, "disabled": 1,
        }, message="inventory health classification changed")
        require(condition=required_object(result["inventory"])["orphaned_state_domains"] == 1,
                message="removed state was not retained as orphaned")
        incidents = result["incidents"]
        require(condition=isinstance(incidents, list), message="incident shape changed")
        if isinstance(incidents, list):
            kinds = [required_object(item)["kind"] for item in incidents]
            require(condition=kinds == ["domain_down", "domain_unknown"], message="incident order changed")
            require(condition=required_object(incidents[0])["telegram_alert"] is False, message="policy ignored")

    @staticmethod
    def test_stale_boundary_and_absent_registry_are_not_healthy() -> None:
        """Freshness equality is inclusive; a missing registry response is unavailable."""
        data = MonitorData({"updated_at": _NOW - 180}, {}, "fixture", "fixture", _NOW, None)
        fresh = summarize_freshness(data=data, now_ts=_NOW, history_max_ts=None)
        stale = summarize_freshness(data=data, now_ts=_NOW + 1, history_max_ts=None)
        require(condition=fresh["status"] == "fresh" and stale["status"] == "stale", message="freshness boundary moved")
        require(condition=summarize_e2e(None, now_ts=_NOW)["status"] == "unavailable",
                message="missing registry healthy")
        with pytest.raises(OverflowError):
            summarize_e2e({"ok": True, "tests": [{"enabled": math.inf}]}, now_ts=_NOW)
        with pytest.raises(TypeError, match="int\\(\\) argument"):
            summarize_e2e({"ok": True, "tests": [{"enabled": [1]}]}, now_ts=_NOW)

    @staticmethod
    def test_series_keep_identical_requests_and_inclusive_original_times() -> None:
        """Identical rows count separately and signal rows keep their source identity."""
        rows: list[ConfigValue] = [[0, True], [1, False], [1, False], [2, True], [3, True], ["bad", False]]
        state: JsonObject = {"history": {"a.invalid": [[0, True], [1, False], [1, False], [2, True], [3, True]]}}
        data = MonitorData(state, {}, "fixture", "fixture", _NOW, None)
        result = domain_timeseries(data=data, domain="a.invalid", since_ts=1, until_ts=2, max_points=100)
        samples = result["samples"]
        require(condition=isinstance(samples, list) and len(samples) == _EXPECTED_SERIES_COUNT,
                message="inclusive/duplicate row lost")
        # This fixture supplies the same JSON-compatible list through the loader's public input contract.
        signal_data = MonitorData({"signal_history": {"proxy": []}}, {}, "fixture", "fixture", _NOW, None)
        raw = object_or_empty(signal_data.state["signal_history"])
        raw["proxy"] = rows
        signals = signal_timeseries(data=signal_data, signal="proxy", since_ts=1, until_ts=2, max_points=100)
        chosen = signals["samples"]
        require(condition=isinstance(chosen, list), message="signal series shape changed")
        if isinstance(chosen, list):
            require(condition=chosen[0] is rows[1] and chosen[1] is rows[2],
                    message="signal rows copied or deduplicated")

    @staticmethod
    def test_signals_copy_display_annotations_without_mutating_source() -> None:
        """Observed history time enriches the display while retained records stay exact."""
        state: JsonObject = {"host_health": {"last_ok": False}, "signal_history": {"host_health": [[_NOW, False]]}}
        before = deepcopy(state)
        data = MonitorData(state, {}, "fixture", "fixture", _NOW, None)
        output = summarize_signals(data=data)
        require(condition=required_object(output["host_health"])["observed_at_ts"] == _NOW, message="history time lost")
        require(condition=state == before, message="display annotation persisted into source")

    @staticmethod
    def test_corrupt_subcheck_remains_an_error() -> None:
        """Malformed retained state must not turn a failed calculation into healthy output."""
        data = MonitorData({"last_ok": {"a.invalid": True}, "api_contract": None}, {}, "fixture", "fixture", _NOW, None)
        with pytest.raises(AttributeError, match="has no attribute 'get'"):
            summarize_domains(data=data, now_ts=_NOW)
