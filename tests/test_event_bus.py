from __future__ import annotations

import ast
import hashlib
import hmac
import json
from pathlib import Path

import httpx
import pytest

from domain_checks.event_bus import (
    MONITORING_EVENT_KINDS,
    EventBusConfig,
    EventBusOutbox,
    build_payload,
    load_event_bus_config,
    signature_for_delivery,
)
from domain_checks.main import _load_monitor_state

SECRET = "test-monitoring-event-bus-secret-that-is-long-enough"
SHA = "a" * 40


def _config(**overrides: object) -> EventBusConfig:
    values = {
        "webhook_url": "https://pitchai.net/events-bus/webhooks/pitchai-monitoring",
        "secret": SECRET,
        "environment": "production",
        "instance": "pitchai-main",
        "deployment_sha": SHA,
        "timeout_seconds": 10.0,
    }
    values.update(overrides)
    return EventBusConfig(**values)


def _accepted(request: httpx.Request) -> httpx.Response:
    delivery_id = request.headers["X-PitchAI-Monitoring-Delivery"]
    return httpx.Response(
        202,
        json={"accepted": 1, "event_ids": [f"event-for-{delivery_id}"]},
        request=request,
    )


def test_load_event_bus_config_is_optional_but_partial_configuration_fails_loudly():
    assert load_event_bus_config({}) is None

    with pytest.raises(RuntimeError, match="Both .*URL and secret"):
        load_event_bus_config({"PITCHAI_MONITORING_EVENT_BUS_URL": "https://example.test/hook"})

    with pytest.raises(RuntimeError, match="HTTPS URL"):
        load_event_bus_config(
            {
                "PITCHAI_MONITORING_EVENT_BUS_URL": "http://example.test/hook",
                "PITCHAI_MONITORING_EVENT_BUS_SECRET": SECRET,
            }
        )

    with pytest.raises(RuntimeError, match="at least 32"):
        load_event_bus_config(
            {
                "PITCHAI_MONITORING_EVENT_BUS_URL": "https://example.test/hook",
                "PITCHAI_MONITORING_EVENT_BUS_SECRET": "short",
            }
        )


def test_load_event_bus_config_validates_routing_identity_and_timeout():
    base = {
        "PITCHAI_MONITORING_EVENT_BUS_URL": "https://pitchai.net/events-bus/webhooks/pitchai-monitoring",
        "PITCHAI_MONITORING_EVENT_BUS_SECRET": SECRET,
    }

    with pytest.raises(RuntimeError, match="ENVIRONMENT"):
        load_event_bus_config({**base, "PITCHAI_MONITORING_ENVIRONMENT": "Not Valid"})
    with pytest.raises(RuntimeError, match="INSTANCE"):
        load_event_bus_config({**base, "PITCHAI_MONITORING_INSTANCE": "bad value"})
    with pytest.raises(RuntimeError, match="40-byte SHA"):
        load_event_bus_config({**base, "PITCHAI_MONITORING_DEPLOYMENT_SHA": "short"})
    with pytest.raises(RuntimeError, match="between 1 and 60"):
        load_event_bus_config({**base, "PITCHAI_MONITORING_EVENT_BUS_TIMEOUT_SECONDS": "0"})

    config = load_event_bus_config(
        {
            **base,
            "PITCHAI_MONITORING_ENVIRONMENT": "production",
            "PITCHAI_MONITORING_INSTANCE": "pitchai-main",
            "PITCHAI_MONITORING_DEPLOYMENT_SHA": SHA,
        }
    )
    assert config is not None
    assert config.environment == "production"
    assert config.instance == "pitchai-main"
    assert config.deployment_sha == SHA


def test_payload_identity_is_deterministic_strict_json_and_excludes_secret():
    config = _config()
    first = build_payload(
        config,
        kind="domain_down",
        occurred_at=1_784_001_600.25,
        details={"domain": "internal.pitchai.net", "status_code": 503},
    )
    second = build_payload(
        config,
        kind="domain_down",
        occurred_at=1_784_001_600.25,
        details={"status_code": 503, "domain": "internal.pitchai.net"},
    )

    assert first == second
    assert first["delivery_id"].startswith("monitoring-")
    assert first["source"] == {
        "service": "service-monitoring",
        "environment": "production",
        "instance": "pitchai-main",
        "deployment_sha": SHA,
    }
    assert SECRET not in json.dumps(first, sort_keys=True)

    with pytest.raises(ValueError, match="strict JSON"):
        build_payload(config, kind="domain_down", occurred_at=1.0, details={"bad": float("nan")})


@pytest.mark.parametrize("event_kind", sorted(MONITORING_EVENT_KINDS))
def test_every_supported_event_kind_builds_a_stable_envelope(event_kind: str):
    payload = build_payload(
        _config(),
        kind=event_kind,
        occurred_at=1_784_001_600.0,
        details={"probe_label": "catalog-test"},
    )

    assert payload["event_kind"] == event_kind
    assert payload["delivery_id"].startswith("monitoring-")


def test_signature_binds_timestamp_delivery_event_and_body():
    body = b'{"example":true}'
    signature = signature_for_delivery(
        body=body,
        secret=SECRET,
        timestamp="1784001600",
        delivery_id="monitoring-example",
        event_kind="integration_test",
    )
    signed = b"v1\n1784001600\nmonitoring-example\nintegration_test\n" + body
    expected = hmac.new(SECRET.encode(), signed, hashlib.sha256).hexdigest()

    assert signature == f"sha256={expected}"


@pytest.mark.asyncio
async def test_successful_delivery_removes_outbox_entry_and_sends_required_headers():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _accepted(request)

    outbox = EventBusOutbox(_config())
    delivery_id = outbox.enqueue(
        "integration_test",
        occurred_at=1_784_001_600.0,
        details={"probe_label": "pytest"},
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        attempts = await outbox.flush(client, now=1_784_001_601.0)

    assert len(attempts) == 1
    assert attempts[0].success is True
    assert attempts[0].delivery_id == delivery_id
    assert attempts[0].event_id == f"event-for-{delivery_id}"
    assert outbox.pending_count == 0
    assert seen[0].headers["X-PitchAI-Monitoring-Delivery"] == delivery_id
    assert seen[0].headers["X-PitchAI-Monitoring-Event"] == "integration_test"
    assert seen[0].headers["X-PitchAI-Monitoring-Timestamp"] == "1784001601"
    assert seen[0].headers["X-PitchAI-Monitoring-Signature-256"].startswith("sha256=")


@pytest.mark.asyncio
async def test_failure_is_persisted_and_retried_after_backoff():
    statuses = [503, 202]

    def handler(request: httpx.Request) -> httpx.Response:
        status = statuses.pop(0)
        if status == 202:
            return _accepted(request)
        return httpx.Response(status, request=request)

    outbox = EventBusOutbox(_config())
    delivery_id = outbox.enqueue(
        "domain_down",
        occurred_at=1_784_001_600.0,
        details={"domain": "internal.pitchai.net"},
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        first = await outbox.flush(client, now=100.0)
        too_soon = await outbox.flush(client, now=101.0)
        persisted = outbox.to_state()
        reloaded = EventBusOutbox(_config(), entries=persisted)
        second = await reloaded.flush(client, now=102.0)

    assert first[0].success is False
    assert first[0].status_code == 503
    assert too_soon == []
    assert persisted[0]["attempts"] == 1
    assert persisted[0]["last_error"] == "http_status_503"
    assert persisted[0]["next_attempt_at"] == 102.0
    assert SECRET not in json.dumps(persisted, sort_keys=True)
    assert second[0].success is True
    assert second[0].delivery_id == delivery_id
    assert reloaded.pending_count == 0


@pytest.mark.asyncio
async def test_network_and_invalid_acceptance_responses_remain_pending():
    def network_failure(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("unavailable", request=request)

    outbox = EventBusOutbox(_config())
    outbox.enqueue("service_started", occurred_at=1.0, details={})
    async with httpx.AsyncClient(transport=httpx.MockTransport(network_failure)) as client:
        attempt = (await outbox.flush(client, now=10.0))[0]
    assert attempt.error == "ConnectError"
    assert outbox.pending_count == 1

    invalid = EventBusOutbox(_config())
    invalid.enqueue("service_started", occurred_at=2.0, details={})
    transport = httpx.MockTransport(lambda request: httpx.Response(202, json={}, request=request))
    async with httpx.AsyncClient(transport=transport) as client:
        attempt = (await invalid.flush(client, now=10.0))[0]
    assert attempt.error == "invalid_acceptance_response"
    assert invalid.pending_count == 1


def test_duplicate_enqueue_and_tampered_persisted_identity_are_rejected():
    outbox = EventBusOutbox(_config())
    first = outbox.enqueue("domain_up", occurred_at=1.0, details={"domain": "example.test"})
    second = outbox.enqueue("domain_up", occurred_at=1.0, details={"domain": "example.test"})
    assert first == second
    assert outbox.pending_count == 1

    state = outbox.to_state()
    state[0]["payload"]["details"]["domain"] = "tampered.test"
    with pytest.raises(RuntimeError, match="delivery identity"):
        EventBusOutbox(_config(), entries=state)


def test_monitor_state_loader_preserves_outbox_across_restart(tmp_path: Path):
    outbox = EventBusOutbox(_config())
    delivery_id = outbox.enqueue(
        "domain_down",
        occurred_at=1_784_001_600.0,
        details={"domain": "internal.pitchai.net"},
    )
    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps({"version": 6, "event_bus_outbox": outbox.to_state()}),
        encoding="utf-8",
    )

    loaded = _load_monitor_state(state_path)
    restored = EventBusOutbox(_config(), entries=loaded["event_bus_outbox"])

    assert restored.pending_count == 1
    assert restored.to_state()[0]["payload"]["delivery_id"] == delivery_id


def test_monitor_state_loader_preserves_malformed_outbox_for_loud_rejection(tmp_path: Path):
    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps({"version": 6, "event_bus_outbox": {"unexpected": "object"}}),
        encoding="utf-8",
    )

    loaded = _load_monitor_state(state_path)

    assert loaded["event_bus_outbox"] == {"unexpected": "object"}


def test_main_transition_catalog_is_fully_supported():
    source_path = Path(__file__).parents[1] / "domain_checks" / "main.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    emitted = {
        node.args[0].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_append_event"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
    }
    required = {
        "service_started",
        "api_contract_degraded",
        "api_contract_recovered",
        "synthetic_degraded",
        "synthetic_recovered",
        "web_vitals_degraded",
        "web_vitals_recovered",
    }

    assert emitted <= MONITORING_EVENT_KINDS
    assert required <= emitted
    source = source_path.read_text(encoding="utf-8")
    assert '"event_bus_outbox": event_bus_outbox.to_state()' in source
    assert "await _flush_event_bus(http_client)" in source


def test_production_workflow_provides_authenticated_event_bus_configuration():
    workflow = (Path(__file__).parents[1] / ".github" / "workflows" / "ci-cd.yaml").read_text(
        encoding="utf-8"
    )

    assert "PITCHAI_MONITORING_EVENT_BUS_URL" in workflow
    assert "PITCHAI_MONITORING_EVENT_BUS_SECRET" in workflow
    assert "PITCHAI_MONITORING_DEPLOYMENT_SHA" in workflow
    assert '[[ "${#EVENT_BUS_SECRET}" -lt 32 ]]' in workflow
    assert "for stability_check in 1 2" in workflow
    assert "{{.State.Restarting}}" in workflow
    assert "{{.RestartCount}}" in workflow
    assert "load_event_bus_config() is not None" in workflow
    assert '"docs/**"' in workflow
    assert '"README.md"' in workflow
