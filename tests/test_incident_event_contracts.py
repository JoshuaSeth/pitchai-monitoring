from __future__ import annotations

from pathlib import Path

import pytest

from domain_checks.incident_contract import domain_down_details, domain_recovered_details
from domain_checks.main import _normalize_domain_entries, load_config
from monitoring_v2.database_dependency import cycle, definition, observation
from monitoring_v2.event_bus_delivery import DatabaseEventBus
from monitoring_v2.incident_events import database_transition_events

SECRET = "test-monitoring-event-bus-secret-that-is-long-enough"


def _unimix_entry(domain: str):
    config = load_config(Path(__file__).parents[1] / "domain_checks" / "config.yaml")
    entries = _normalize_domain_entries(config["domains"])
    return next(entry for entry in entries if entry.domain == domain)


def test_unimix_domain_incident_contract_is_grouped_critical_and_redirect_aware():
    entry = _unimix_entry("www.unimixbrasil.com.br")
    details = domain_down_details(
        domain=entry.domain,
        raw_entry=entry.raw_entry,
        routes_telegram=entry.routes_telegram,
        alert_policy=entry.alert_policy.telegram,
        disabled=False,
        reason="http_check_failed",
        check_details={
            "status_code": 503,
            "final_url": "https://unimixbrasil.com.br/",
            "error": "upstream unavailable",
        },
        fail_streak=2,
    )

    assert details["customer_group"] == "unimix"
    assert details["project_group"] == "unimix"
    assert details["site"] == "Unimix Brasil canonical alias"
    assert details["critical"] is True
    assert details["alertable"] is True
    assert details["suppressed"] is False
    assert details["synthetic"] is False
    assert details["incident_key"] == "domain:www.unimixbrasil.com.br"
    assert "after normal redirects" in details["expected_behavior"]
    assert "host suffix unimixbrasil.com.br" in details["expected_behavior"]


def test_domain_fingerprint_ignores_streak_but_changes_with_material_evidence():
    entry = _unimix_entry("unimixbrasil.com.br")

    def build(*, streak: int, status: int):
        return domain_down_details(
            domain=entry.domain,
            raw_entry=entry.raw_entry,
            routes_telegram=entry.routes_telegram,
            alert_policy=entry.alert_policy.telegram,
            disabled=False,
            reason="http_check_failed",
            check_details={"status_code": status, "error": "unavailable"},
            fail_streak=streak,
        )

    assert build(streak=2, status=503)["incident_fingerprint"] == build(streak=9, status=503)[
        "incident_fingerprint"
    ]
    assert build(streak=2, status=503)["incident_fingerprint"] != build(streak=2, status=502)[
        "incident_fingerprint"
    ]


def test_noncritical_domain_is_explicitly_suppressed_from_agent_dispatch():
    details = domain_down_details(
        domain="staging.example.test",
        raw_entry={
            "domain": "staging.example.test",
            "group": "examples",
            "environment": "staging",
            "alert_policy": {"telegram": "none"},
        },
        routes_telegram=False,
        alert_policy="none",
        disabled=False,
        reason="http_check_failed",
        check_details={"status_code": 503},
        fail_streak=2,
    )

    assert details["critical"] is False
    assert details["alertable"] is False
    assert details["suppressed"] is True


def test_domain_recovery_uses_the_same_incident_key():
    entry = _unimix_entry("unimixbrasil.com.br")
    opened = domain_down_details(
        domain=entry.domain,
        raw_entry=entry.raw_entry,
        routes_telegram=True,
        alert_policy="critical",
        disabled=False,
        reason="http_check_failed",
        check_details={"status_code": 503},
        fail_streak=2,
    )
    recovered = domain_recovered_details(
        domain=entry.domain,
        raw_entry=entry.raw_entry,
        routes_telegram=True,
        disabled=False,
    )

    assert recovered["incident_key"] == opened["incident_key"]
    assert recovered["incident_fingerprint"] != opened["incident_fingerprint"]
    assert recovered["reason"] == "domain_recovered"


def test_database_transitions_emit_only_debounced_alertable_down_and_recovery():
    probe = definition("web")
    first_failure = cycle([probe], [observation(probe, at=100.0, ok=False)], at=100.0)
    assert database_transition_events(previous={}, updated=first_failure) == ()

    down = cycle(
        [probe],
        [observation(probe, at=200.0, ok=False)],
        previous=first_failure,
        at=200.0,
    )
    events = database_transition_events(previous=first_failure, updated=down)
    assert len(events) == 1
    opened = events[0]
    assert opened.kind == "database_down"
    assert opened.details["incident_key"] == "database:app-database"
    assert opened.details["owner_project"] == "Example"
    assert opened.details["critical"] is True
    assert opened.details["alertable"] is True
    assert database_transition_events(previous=down, updated=down) == ()

    first_success = cycle(
        [probe],
        [observation(probe, at=300.0, ok=True)],
        previous=down,
        at=300.0,
    )
    assert database_transition_events(previous=down, updated=first_success) == ()
    recovered = cycle(
        [probe],
        [observation(probe, at=400.0, ok=True)],
        previous=first_success,
        at=400.0,
    )
    recovery_events = database_transition_events(previous=first_success, updated=recovered)
    assert len(recovery_events) == 1
    assert recovery_events[0].kind == "database_recovered"
    assert recovery_events[0].details["incident_key"] == opened.details["incident_key"]


def test_database_outbox_stages_transition_before_state_checkpoint(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(
        "PITCHAI_MONITORING_EVENT_BUS_URL",
        "https://pitchai.net/events-bus/webhooks/pitchai-monitoring",
    )
    monkeypatch.setenv("PITCHAI_MONITORING_EVENT_BUS_SECRET", SECRET)
    monkeypatch.setenv("PITCHAI_MONITORING_ENVIRONMENT", "production")
    monkeypatch.setenv("PITCHAI_MONITORING_INSTANCE", "pytest-database")
    probe = definition("web")
    previous = cycle([probe], [observation(probe, at=100.0, ok=False)], at=100.0)
    updated = cycle(
        [probe],
        [observation(probe, at=200.0, ok=False)],
        previous=previous,
        at=200.0,
    )

    event_bus = DatabaseEventBus.from_state({})
    assert event_bus is not None
    staged = event_bus.staged_for_cycle(previous=previous, updated=updated)
    state_value = staged.state_value()

    assert event_bus.outbox.pending_count == 0
    assert staged.outbox.pending_count == 1
    assert isinstance(state_value, list)
    assert state_value[0]["payload"]["event_kind"] == "database_down"
