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
   the Actions secret is absent or shorter than 32 characters.
5. Confirm the automatic `service_started` delivery, then run one explicit
   `integration_test` probe.

The deployment workflow passes the exact GitHub commit SHA into the container.
It requires two stable zero-restart observations and loads the producer
configuration inside the container before reporting success. Do not enable the
producer before the matching receiver and secret are live.

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

Verified on 2026-07-14 UTC:

- Receiver PR 78 deployed merged SHA
  `bbd56429e6c1e074fd7bf0bdce077b3c615793c9` as Events Bus version 0.5.0
  before the producer was enabled. Public readiness and route discovery passed;
  an unsigned monitoring request returned HTTP 401 and persisted no row.
- Producer PR 11 merged as
  `ba4dd9daef16c13659f872f384ac1e2687e531da`. Its first workflow run
  29304853333 exposed a rollout defect: a one-character repository secret passed
  a non-empty gate and a one-time running-state observation raced a restart.
  The receiver stayed healthy and no invalid monitoring row was accepted.
- The protected secret was corrected through stdin. Corrective workflow run
  29305077980 passed the full HTTP/Playwright suite and deployed the exact
  producer SHA. The automatic startup event and controlled internal probe both
  returned HTTP 202 and became durable.
- Guard PR 12 merged as
  `d778415ab16221fc5ab4d9b5f3ec196c8ca60221`. Workflow run 29305408134 then
  passed the full suite, minimum secret-length check, two zero-restart
  observations, and in-container config validation. The final production image
  is tagged with that exact SHA and remained running with restart count zero.
- Final `service_started` row `5dacc61f-b90e-4b64-8584-d1899abdb55f`
  was stored at `2026-07-14T04:14:39.528793Z`. The final explicit probe returned
  HTTP 202 as row `d15364b5-0695-4cae-ae86-09ca6364af6a` at
  `2026-07-14T04:15:33.306723Z` with delivery id
  `monitoring-68cc62b72ba7ae9b4f8594f53958f54f86b89679343d72cc24346594f745f164`.
- The final probe row is queued/available with zero attempts and replays. It
  carries the final deployment SHA and retains 394 protected raw bytes with
  SHA-256
  `3fab139fc3a16509ac8c971bb5389309fbe20797c22ab0f3cc21cb356064bf94`.
  Receiver logs correlate the same ids with HTTP 202; the Events Bus CLI lists
  all four real monitoring rows.
- A controlled receiver restart preserved the exact row digests and queue state
  for the first real startup/probe pair, kept the SQLite inode unchanged, and
  returned `ok` from `quick_check`. The producer state schema is version 6 and
  its persisted outbox had zero pending entries afterward.

No shared secret, raw payload, or client data is included in this evidence.
