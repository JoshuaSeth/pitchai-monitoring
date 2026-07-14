# PitchAI Service Monitoring Events Bus Delivery

## Scope

`service-monitoring` is a distinct PitchAI-owned production service. It emits
debounced operational transitions to the central Events Bus without replacing
its existing Telegram alerts or Dispatcher investigations.

Production receiver:

```text
POST https://pitchai.net/events-bus/webhooks/pitchai-monitoring
```

## Authentication Contract

The producer serializes strict canonical JSON and supplies:

- `Content-Type: application/json`
- `X-PitchAI-Monitoring-Delivery: <stable delivery id>`
- `X-PitchAI-Monitoring-Timestamp: <Unix seconds>`
- `X-PitchAI-Monitoring-Event: <event kind>`
- `X-PitchAI-Monitoring-Signature-256: sha256=<HMAC hex>`

The HMAC-SHA256 input is the exact byte sequence:

```text
v1\n<timestamp>\n<delivery-id>\n<event-kind>\n<exact-request-body>
```

The receiver rejects missing, malformed, incorrect, or more-than-five-minute
stale authentication before parsing JSON. The shared secret must contain at
least 32 characters and exists only in the GitHub Actions secret
`PITCHAI_MONITORING_EVENT_BUS_SECRET` and the root-managed Events Bus service
environment. Never put it in source, state, arguments, logs, PM, or reports.

## Envelope And Identity

Each payload contains schema version 1, delivery id, event kind, UTC occurrence
time, source service/environment/instance/deployment SHA, and a details object.
The delivery id is `monitoring-` plus SHA-256 over the canonical payload before
the id is added. Re-enqueuing or retrying the same transition therefore keeps
the same identity.

The producer persists pending entries under `event_bus_outbox` in the existing
monitor state volume. It sends oldest-first, requires HTTP 202 plus one receiver
event id, and retries failures with exponential backoff capped at five minutes.
The receiver deduplicates on `pitchai-monitoring:<delivery-id>`.

## Event Catalog

The complete initial catalog is:

| Signal | Event kinds |
| --- | --- |
| Lifecycle/probe | `service_started`, `integration_test` |
| Domain | `domain_down`, `domain_up` |
| SLO | `slo_degraded`, `slo_recovered` |
| RED | `red_degraded`, `red_recovered` |
| Host health | `host_health_degraded`, `host_health_recovered` |
| Performance | `performance_degraded`, `performance_recovered` |
| TLS | `tls_degraded`, `tls_recovered` |
| DNS | `dns_degraded`, `dns_recovered` |
| API contract | `api_contract_degraded`, `api_contract_recovered` |
| Container health | `container_health_degraded`, `container_health_recovered` |
| Proxy | `proxy_degraded`, `proxy_recovered` |
| Synthetic transaction | `synthetic_degraded`, `synthetic_recovered` |
| Web vitals | `web_vitals_degraded`, `web_vitals_recovered` |
| Browser infrastructure | `browser_degraded_notice`, `browser_recovered` |
| Monitor pipeline | `meta_degraded`, `meta_recovered` |

The main monitor emits only debounced state transitions. `service_started` is
emitted after a configured process starts. `integration_test` is emitted only
by the explicit internal probe command.

## Deployment Order

1. Deploy the merged Events Bus receiver and configure its secret.
2. Verify bad authentication returns 401 and readiness remains healthy.
3. Store the same value as the monitoring repository Actions secret.
4. Merge and deploy the monitoring producer. The workflow fails loudly when
   the Actions secret is absent.
5. Confirm the automatic `service_started` delivery, then run one explicit
   `integration_test` probe.

The deployment workflow passes the exact GitHub commit SHA into the container.
Do not enable the producer before the matching receiver and secret are live.

## Verification

Producer-side controlled probe:

```bash
docker exec service-monitoring \
  python -m domain_checks.event_bus --probe-label nightly-YYYYMMDD
```

Receiver-side non-sensitive inspection:

```bash
PITCHAI_EVENTS_DB_PATH=/var/lib/pitchai-events-bus/events.db \
  /opt/pitchai-events-bus/.venv/bin/pitchai-events list \
  --origin-system pitchai_monitoring --limit 10
```

Inspect normalized fields only in shared evidence. Raw JSON remains protected
in SQLite. It is sufficient to record event id, delivery id, event type,
occurrence/creation timestamps, source instance, deployment SHA, queue state,
raw byte count/hash, and the SQLite integrity result.

For restart durability, record the selected event id and row hash, restart the
Events Bus service, rerun readiness and `pragma quick_check`, and confirm the
same row plus queue state remain present.

## Incident Procedure

- If producer logs show a non-202 result, inspect only status/error category and
  pending count. The outbox must remain present in `STATE_PATH`.
- If the outbox grows, restore receiver readiness/auth before restarting the
  producer; retries are safe because the delivery id is stable.
- If a receiver accepted a delivery but the producer crashed before persisting
  removal, the replay returns the same SQLite event id.
- Rotate a compromised secret in both services, deploy the receiver first, then
  restart the producer. Do not log either old or new values.
- Never paste protected raw monitoring payloads into PM, chat, or public logs.

## Production Evidence

Populate this section only from merged production source after the real
delivery and restart proof. Do not include secrets, private raw payloads, or
client data.
