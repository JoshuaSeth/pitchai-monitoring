from __future__ import annotations

from e2e_registry.monitor_dashboard import MonitorData, build_dashboard_summary


def test_operator_summary_reports_real_staleness_incidents_and_rolling_day() -> None:
    now = 2_000_000_000.0
    data = MonitorData(
        state={
            "updated_at": now - 400,
            "history": {
                "down.pitchai.net": [
                    [now - 120, True, 100.0, 300.0, 200],
                    [now - 60, False, 900.0, 1800.0, 503],
                ]
            },
            "last_ok": {"down.pitchai.net": False},
            "fail_streak": {"down.pitchai.net": 2},
            "success_streak": {"down.pitchai.net": 0},
            "host_health": {"last_ok": False, "fail_streak": 3, "success_streak": 0},
            "events": [
                {"ts": now - 90000, "kind": "domain_down", "domain": "old.pitchai.net"},
                {"ts": now - 100, "kind": "domain_down", "domain": "down.pitchai.net"},
                {"ts": now - 50, "kind": "proxy_recovered"},
            ],
        },
        config={
            "interval_seconds": 60,
            "domains": [{"domain": "down.pitchai.net"}],
        },
        state_path="/monitor/state.json",
        config_path="/monitor/config.yaml",
        loaded_at_ts=now,
        state_error=None,
    )
    e2e = {
        "ok": True,
        "total_tests": 2,
        "failing_tests": 1,
        "tests": [
            {
                "test_id": "passing",
                "test_name": "Passing route",
                "base_url": "https://passing.pitchai.net",
                "enabled": 1,
                "effective_ok": 1,
                "last_status": "pass",
                "last_finished_at_ts": now - 20,
            },
            {
                "test_id": "failing",
                "test_name": "Failing route",
                "base_url": "https://failing.pitchai.net",
                "enabled": 1,
                "effective_ok": 0,
                "fail_streak": 2,
                "last_status": "fail",
                "last_finished_at_ts": now - 10,
            },
        ],
    }

    summary = build_dashboard_summary(
        data=data,
        now_ts=now,
        e2e_status_summary=e2e,
        e2e_dispatch_runs=[],
    )

    assert summary["freshness"] == {
        "status": "stale",
        "state_updated_at_ts": now - 400,
        "age_seconds": 400.0,
        "interval_seconds": 60,
        "stale_after_seconds": 180,
        "source": "state.updated_at",
    }
    assert summary["service_health"] == {
        "enabled": 1,
        "healthy": 0,
        "down": 1,
        "unknown": 0,
        "disabled": 0,
    }
    assert summary["e2e"]["passing_tests"] == 1
    assert summary["e2e"]["failing_tests"] == 1
    assert summary["e2e"]["problems"][0]["test_id"] == "failing"
    assert [incident["kind"] for incident in summary["incidents"]] == [
        "monitor_freshness",
        "domain_down",
        "signal_degraded",
        "e2e_failure",
    ]
    assert summary["daily_status"]["observations"] == 2
    assert summary["daily_status"]["successful_observations"] == 1
    assert summary["daily_status"]["availability_pct"] == 50.0
    assert summary["daily_status"]["problem_events"] == 1
    assert summary["daily_status"]["recoveries"] == 1
    assert summary["daily_status"]["latest_event_at_ts"] == now - 50
    assert summary["daily_status"]["status"] == "attention"
