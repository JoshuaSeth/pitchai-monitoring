"""Durable signed delivery of service-monitoring transitions to the Events Bus."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import hmac
import json
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping
from urllib.parse import urlparse

import httpx

SIGNATURE_HEADER = "X-PitchAI-Monitoring-Signature-256"
DELIVERY_HEADER = "X-PitchAI-Monitoring-Delivery"
TIMESTAMP_HEADER = "X-PitchAI-Monitoring-Timestamp"
EVENT_HEADER = "X-PitchAI-Monitoring-Event"
SIGNATURE_VERSION = "v1"

MONITORING_EVENT_KINDS = frozenset(
    {
        "service_started",
        "integration_test",
        "domain_down",
        "domain_up",
        "slo_degraded",
        "slo_recovered",
        "red_degraded",
        "red_recovered",
        "host_health_degraded",
        "host_health_recovered",
        "performance_degraded",
        "performance_recovered",
        "tls_degraded",
        "tls_recovered",
        "dns_degraded",
        "dns_recovered",
        "api_contract_degraded",
        "api_contract_recovered",
        "container_health_degraded",
        "container_health_recovered",
        "proxy_degraded",
        "proxy_recovered",
        "synthetic_degraded",
        "synthetic_recovered",
        "web_vitals_degraded",
        "web_vitals_recovered",
        "browser_degraded_notice",
        "browser_recovered",
        "meta_degraded",
        "meta_recovered",
    }
)

_DELIVERY_PREFIX = "monitoring-"
_ENVIRONMENT_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
_INSTANCE_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,120}$")
_DEPLOYMENT_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
_MAX_PENDING_DELIVERIES = 10_000
_MAX_FLUSH_BATCH = 100


@dataclass(frozen=True)
class EventBusConfig:
    webhook_url: str
    secret: str
    environment: str
    instance: str
    deployment_sha: str | None
    timeout_seconds: float = 10.0


@dataclass(frozen=True)
class DeliveryAttempt:
    delivery_id: str
    success: bool
    status_code: int | None
    event_id: str | None
    error: str | None


def load_event_bus_config(environ: Mapping[str, str] | None = None) -> EventBusConfig | None:
    """Load optional Events Bus delivery settings and reject partial configuration."""
    source = os.environ if environ is None else environ
    webhook_url = str(source.get("PITCHAI_MONITORING_EVENT_BUS_URL") or "").strip()
    secret = str(source.get("PITCHAI_MONITORING_EVENT_BUS_SECRET") or "").strip()
    if not webhook_url and not secret:
        return None
    if not webhook_url or not secret:
        raise RuntimeError("Both PITCHAI_MONITORING_EVENT_BUS_URL and secret are required")
    parsed = urlparse(webhook_url)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise RuntimeError("PITCHAI_MONITORING_EVENT_BUS_URL must be an HTTPS URL without userinfo")
    if len(secret) < 32:
        raise RuntimeError("PITCHAI_MONITORING_EVENT_BUS_SECRET must contain at least 32 characters")
    environment = str(source.get("PITCHAI_MONITORING_ENVIRONMENT") or "production").strip()
    instance = str(source.get("PITCHAI_MONITORING_INSTANCE") or "pitchai-main").strip()
    deployment_sha = str(source.get("PITCHAI_MONITORING_DEPLOYMENT_SHA") or "").strip() or None
    if not _ENVIRONMENT_PATTERN.fullmatch(environment):
        raise RuntimeError("PITCHAI_MONITORING_ENVIRONMENT is invalid")
    if not _INSTANCE_PATTERN.fullmatch(instance):
        raise RuntimeError("PITCHAI_MONITORING_INSTANCE is invalid")
    if deployment_sha and not _DEPLOYMENT_SHA_PATTERN.fullmatch(deployment_sha):
        raise RuntimeError("PITCHAI_MONITORING_DEPLOYMENT_SHA must be a lowercase 40-byte SHA")
    timeout_seconds = float(source.get("PITCHAI_MONITORING_EVENT_BUS_TIMEOUT_SECONDS") or "10")
    if not 1 <= timeout_seconds <= 60:
        raise RuntimeError("PITCHAI_MONITORING_EVENT_BUS_TIMEOUT_SECONDS must be between 1 and 60")
    return EventBusConfig(
        webhook_url=webhook_url,
        secret=secret,
        environment=environment,
        instance=instance,
        deployment_sha=deployment_sha,
        timeout_seconds=timeout_seconds,
    )


class EventBusOutbox:
    """Persisted at-least-once producer queue with receiver-side dedupe identity."""

    def __init__(self, config: EventBusConfig, entries: list[dict[str, Any]] | None = None) -> None:
        self.config = config
        self._entries = [_validated_entry(entry) for entry in (entries or [])]
        if len(self._entries) > _MAX_PENDING_DELIVERIES:
            raise RuntimeError("PitchAI monitoring Events Bus outbox exceeds its safety limit")

    @property
    def pending_count(self) -> int:
        return len(self._entries)

    def enqueue(self, kind: str, *, occurred_at: float, details: dict[str, Any]) -> str:
        if len(self._entries) >= _MAX_PENDING_DELIVERIES:
            raise RuntimeError("PitchAI monitoring Events Bus outbox is full")
        payload = build_payload(
            self.config,
            kind=kind,
            occurred_at=occurred_at,
            details=details,
        )
        delivery_id = str(payload["delivery_id"])
        if any(_entry_delivery_id(entry) == delivery_id for entry in self._entries):
            return delivery_id
        self._entries.append(
            {
                "payload": payload,
                "attempts": 0,
                "next_attempt_at": 0.0,
                "last_error": None,
            }
        )
        return delivery_id

    def to_state(self) -> list[dict[str, Any]]:
        return json.loads(json.dumps(self._entries, separators=(",", ":"), sort_keys=True))

    async def flush(
        self,
        client: httpx.AsyncClient,
        *,
        now: float | None = None,
        max_deliveries: int = _MAX_FLUSH_BATCH,
    ) -> list[DeliveryAttempt]:
        selected_now = time.time() if now is None else float(now)
        attempts: list[DeliveryAttempt] = []
        processed = 0
        for entry in list(self._entries):
            if processed >= max(1, int(max_deliveries)):
                break
            if float(entry["next_attempt_at"]) > selected_now:
                break
            attempt = await _deliver_entry(client, self.config, entry, now=selected_now)
            attempts.append(attempt)
            processed += 1
            if attempt.success:
                self._entries.remove(entry)
                continue
            _record_failure(entry, attempt, now=selected_now)
            break
        return attempts


def build_payload(
    config: EventBusConfig,
    *,
    kind: str,
    occurred_at: float,
    details: dict[str, Any],
) -> dict[str, Any]:
    if kind not in MONITORING_EVENT_KINDS:
        raise ValueError(f"Unsupported PitchAI monitoring event kind: {kind}")
    if not isinstance(details, dict):
        raise TypeError("PitchAI monitoring event details must be an object")
    source: dict[str, Any] = {
        "service": "service-monitoring",
        "environment": config.environment,
        "instance": config.instance,
    }
    if config.deployment_sha:
        source["deployment_sha"] = config.deployment_sha
    payload: dict[str, Any] = {
        "schema_version": 1,
        "event_kind": kind,
        "occurred_at": _iso_timestamp(occurred_at),
        "source": source,
        "details": details,
    }
    canonical = _canonical_json(payload)
    payload["delivery_id"] = f"{_DELIVERY_PREFIX}{hashlib.sha256(canonical).hexdigest()}"
    _canonical_json(payload)
    return payload


def signature_for_delivery(
    *,
    body: bytes,
    secret: str,
    timestamp: str,
    delivery_id: str,
    event_kind: str,
) -> str:
    signed = f"{SIGNATURE_VERSION}\n{timestamp}\n{delivery_id}\n{event_kind}\n".encode() + body
    digest = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


async def _deliver_entry(
    client: httpx.AsyncClient,
    config: EventBusConfig,
    entry: dict[str, Any],
    *,
    now: float,
) -> DeliveryAttempt:
    payload = entry["payload"]
    delivery_id = _entry_delivery_id(entry)
    event_kind = str(payload["event_kind"])
    body = _canonical_json(payload)
    timestamp = str(int(now))
    headers = {
        "content-type": "application/json",
        SIGNATURE_HEADER: signature_for_delivery(
            body=body,
            secret=config.secret,
            timestamp=timestamp,
            delivery_id=delivery_id,
            event_kind=event_kind,
        ),
        DELIVERY_HEADER: delivery_id,
        TIMESTAMP_HEADER: timestamp,
        EVENT_HEADER: event_kind,
    }
    try:
        response = await client.post(
            config.webhook_url,
            content=body,
            headers=headers,
            timeout=config.timeout_seconds,
        )
    except httpx.HTTPError as exc:
        return DeliveryAttempt(
            delivery_id=delivery_id,
            success=False,
            status_code=None,
            event_id=None,
            error=f"{type(exc).__name__}",
        )
    if response.status_code != 202:
        return DeliveryAttempt(
            delivery_id=delivery_id,
            success=False,
            status_code=response.status_code,
            event_id=None,
            error=f"http_status_{response.status_code}",
        )
    event_id = _accepted_event_id(response)
    if event_id is None:
        return DeliveryAttempt(
            delivery_id=delivery_id,
            success=False,
            status_code=response.status_code,
            event_id=None,
            error="invalid_acceptance_response",
        )
    return DeliveryAttempt(
        delivery_id=delivery_id,
        success=True,
        status_code=response.status_code,
        event_id=event_id,
        error=None,
    )


def _accepted_event_id(response: httpx.Response) -> str | None:
    try:
        payload = response.json()
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict) or payload.get("accepted") != 1:
        return None
    event_ids = payload.get("event_ids")
    if not isinstance(event_ids, list) or len(event_ids) != 1:
        return None
    event_id = event_ids[0]
    return event_id if isinstance(event_id, str) and event_id else None


def _record_failure(entry: dict[str, Any], attempt: DeliveryAttempt, *, now: float) -> None:
    attempt_count = int(entry["attempts"]) + 1
    entry["attempts"] = attempt_count
    entry["last_error"] = attempt.error or "unknown_delivery_error"
    entry["next_attempt_at"] = now + min(300.0, float(2 ** min(attempt_count, 8)))


def _validated_entry(raw_entry: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw_entry, dict):
        raise RuntimeError("PitchAI monitoring Events Bus outbox entry must be an object")
    entry = json.loads(json.dumps(raw_entry, separators=(",", ":"), sort_keys=True))
    payload = entry.get("payload")
    if not isinstance(payload, dict):
        raise RuntimeError("PitchAI monitoring Events Bus outbox payload is missing")
    delivery_id = payload.get("delivery_id")
    event_kind = payload.get("event_kind")
    if not isinstance(delivery_id, str) or not delivery_id.startswith(_DELIVERY_PREFIX):
        raise RuntimeError("PitchAI monitoring Events Bus outbox delivery id is invalid")
    if event_kind not in MONITORING_EVENT_KINDS:
        raise RuntimeError("PitchAI monitoring Events Bus outbox event kind is invalid")
    identity_payload = dict(payload)
    identity_payload.pop("delivery_id", None)
    expected_delivery_id = f"{_DELIVERY_PREFIX}{hashlib.sha256(_canonical_json(identity_payload)).hexdigest()}"
    if delivery_id != expected_delivery_id:
        raise RuntimeError("PitchAI monitoring Events Bus outbox delivery identity is invalid")
    attempts = entry.get("attempts")
    next_attempt_at = entry.get("next_attempt_at")
    if not isinstance(attempts, int) or attempts < 0:
        raise RuntimeError("PitchAI monitoring Events Bus outbox attempt count is invalid")
    if not isinstance(next_attempt_at, (int, float)) or isinstance(next_attempt_at, bool):
        raise RuntimeError("PitchAI monitoring Events Bus retry timestamp is invalid")
    if entry.get("last_error") is not None and not isinstance(entry.get("last_error"), str):
        raise RuntimeError("PitchAI monitoring Events Bus last error is invalid")
    _canonical_json(payload)
    return entry


def _entry_delivery_id(entry: dict[str, Any]) -> str:
    return str(entry["payload"]["delivery_id"])


def _canonical_json(payload: dict[str, Any]) -> bytes:
    try:
        return json.dumps(
            payload,
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    except (TypeError, ValueError) as exc:
        raise ValueError("PitchAI monitoring event payload is not strict JSON") from exc


def _iso_timestamp(value: float) -> str:
    return datetime.fromtimestamp(float(value), tz=timezone.utc).isoformat(
        timespec="microseconds"
    ).replace("+00:00", "Z")


async def _send_probe(config: EventBusConfig, probe_label: str) -> DeliveryAttempt:
    outbox = EventBusOutbox(config)
    outbox.enqueue(
        "integration_test",
        occurred_at=time.time(),
        details={"probe_label": probe_label[:240]},
    )
    async with httpx.AsyncClient(headers={"User-Agent": "PitchAI Service Monitoring"}) as client:
        attempts = await outbox.flush(client)
    if len(attempts) != 1 or not attempts[0].success or outbox.pending_count:
        raise RuntimeError("PitchAI monitoring Events Bus probe was not accepted")
    return attempts[0]


def main() -> int:
    parser = argparse.ArgumentParser(description="PitchAI monitoring Events Bus delivery probe")
    parser.add_argument("--probe-label", required=True, help="Non-sensitive internal probe label")
    args = parser.parse_args()
    config = load_event_bus_config()
    if config is None:
        raise RuntimeError("PitchAI monitoring Events Bus delivery is not configured")
    attempt = asyncio.run(_send_probe(config, str(args.probe_label)))
    print(
        json.dumps(
            {
                "accepted": attempt.success,
                "delivery_id": attempt.delivery_id,
                "event_id": attempt.event_id,
                "status_code": attempt.status_code,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
