# Client hotpaths as first-class monitoring signals

Client hotpaths are visible, value-bearing product journeys. They are deliberately separate from domain uptime checks: a host can be reachable while an assessment, recommendation, search, editor, share, diary, or calendar story is broken. Both signal families use the same PitchAI Events Inbox response path when a real incident is critical.

## Canonical inventory and timing

`e2e_registry/hotpath_inventory.json` is the checked-in runtime inventory. Version 1 contains the complete 13-lane estate: DFT, AutoPAR, AIPC/SkyBuyFly, potAIto, AFASAsk/GZB, Orthoparse, QuickChat RSR, DePlanBook Play, CISNL, AIGENDA Rules, DePlanBook CMS, Apologetica CMS, and AIGENDA Calendar. OrthoShare is not admitted because it has no deployed product surface.

Every row binds lane ID, project, display name, target surface, primary domain, PitchAI live-agent global ID, exact reminder ID, and the expected visible behavior. Callers cannot rename those values. The canonical PitchAI engine tag is `hot-path-testing`; normal cadence is 172,800 seconds, stale threshold is 259,200 seconds, and incident cooldown is exactly 1,800 seconds.

## HTTP interface and authentication

- `POST /api/v1/hotpaths/reports` accepts one strict version 1 report with `Authorization: Bearer <E2E_HOTPATH_REPORTER_TOKEN>`. This path is machine-only at the edge; browser identity headers are stripped.
- `GET /dashboard/api/v1/hotpaths/summary` is the Entra-protected operator route used by dashboard JavaScript.
- `GET /api/v1/hotpaths/summary` is the bearer-authenticated machine alias.

Reports require exactly: schema version, canonical lane/project/name/target, offset-aware occurrence time, full 40-character source SHA, optional full deployed SHA, success, severity, concise failure reason/class/phase, private SeaweedFS evidence URI, duration, terminal artifact-receipt SHA-256, stable run ID, and synthetic controls. Unknown keys fail closed. Evidence must be under `s3://pitchai-hotpath-artifacts/client-hotpaths/v1/<lane>/<source-sha>/`; the supported lane reporter further requires the terminal `audit-receipt.json` URI.

The reporter token is created or backfilled during deployment in the existing mode-0600 registry env file. The deployment atomically writes the same value, and only that value, to `/root/service-monitoring/hotpath-reporter.token` with mode 0600 for reminder/manual clients. Neither value is logged. Production containers receive the token only through their environment.

## Persistence and idempotency

The registry SQLite database owns three additive structures: immutable reports, one current state row per real lane, and a durable event outbox. Report identity is `hotpath-v1-<sha256(canonical-report-json)>`. An exact retry returns the original hash-bound receipt with `duplicate=true`; it does not write a second report or event intent.

Current state advances only for a newer real occurrence. Out-of-order values remain immutable history and return `out_of_order`, but cannot replace the lane projection. Synthetic protocol proof is retained independently and never mutates a real lane.

For critical real failures, the material incident fingerprint binds lane ID, severity, target surface, normalized failure reason, failure class, failure phase, source SHA, and deployed SHA. It intentionally excludes run IDs, timestamps, evidence keys, and receipt hashes. A `hotpath_red` intent is created on the first critical failure, an immediate material fingerprint change, or unchanged persistence after 1,800 seconds. Identical material failures inside that cooldown are `suppressed_cooldown`. Warning failures are `warning_only`. The first later real PASS emits `hotpath_recovered` with the prior incident fingerprint.

## Events Inbox delivery

The outbox worker claims due intents transactionally and passes an immutable event payload through the shared `domain_checks.event_bus_delivery.deliver_event_bus_payload` gateway. Real RED payloads are production, critical, alertable, non-synthetic, and use incident key `hotpath:<lane_id>` plus `repair_dispatch=asap`. Recovery retains that critical, alertable incident identity so the receiver can close the same repair lane. Project routing prefers the exact project ID, then project ownership and project group, then the loud `pitchai_monitoring` fallback. Primary domain and private artifact fields are normalized into the Events Inbox while the complete raw payload remains retained.

The shared receiver normalizes events to `pitchai.monitoring.hotpath.red` and `pitchai.monitoring.hotpath.recovered`. It applies the same 1,800-second persistent-incident cooldown, allows changed fingerprints immediately, and closes the matching incident on recovery. The registry records the receiver event ID and delivery status. Retryable transport failures remain in the durable outbox with bounded backoff rather than being silently dropped.

The reserved `monitoring-hotpath-synthetic` lane can exercise ingestion and, only when explicitly requested, the event path. Its FAIL payload is marked synthetic, test-only, non-alertable, and `repair_dispatch=test_only`; it cannot dispatch a production repair agent.

## Operator dashboard

`https://monitoring.pitchai.net/dashboard#hotpaths` has a dedicated Client hotpaths tab. It does not mix journey failures into domain-up/down rows. The view shows total/passing/warning/critical/stale/never-reported counts, tag and timing policy, each canonical lane and reminder, expected story, target, current source/deployed SHA, duration, first failure, evidence URI and receipt hash, event action, and synthetic PASS/FAIL delivery proof.

The hotpath fetch is independent of the main monitoring summary. A hotpath API failure renders a scoped unavailable state and does not blank domain, infrastructure, journey, database, incident, or evidence views.

## Safe protocol proof

Use the reserved synthetic identity only. Publish a sanitized evidence packet through the normal private SeaweedFS contract, then POST one PASS (`success=true`, `severity=info`, `exercise_event_bus=false`) and one intentional FAIL (`success=false`, `severity=critical`, `exercise_event_bus=true`). Verify all of the following:

1. Both POST responses bind the local canonical report SHA-256 and a server receipt SHA-256.
2. The dashboard synthetic proof list shows PASS as `synthetic_only` and FAIL as `queued_synthetic_test`.
3. The FAIL outbox row reaches `delivered` with a receiver event ID.
4. The emitted payload remains non-alertable and test-only, and no real lane state or repair dispatch changes.

Then submit at least one safe current real lane result with `synthetic=false` and verify its exact lane row becomes passing, warning, or critical. Do not manufacture duration, revision, or receipt hashes; derive them from retained evidence.

## Verification and operational checks

Focused local proof:

```bash
python -m pytest -q \
  monitoring_v2/test_hotpath_contract.py \
  monitoring_v2/test_hotpath_incidents.py \
  monitoring_v2/test_hotpath_api.py \
  monitoring_v2/test_monitor_dashboard_browser.py
```

After deployment, verify container stability, reporter-token presence without printing it, both summary authentication boundaries, a real current lane row, synthetic PASS/FAIL rows, delivered receiver ID, and the Events Inbox test-only payload. The image build must include `monitoring_v2`, `domain_checks`, `e2e_registry`, templates, static assets, and the canonical inventory.

The complete lane-side request construction, exact identities, secret-safe command, receipt retention, and reminder behavior live in `pitchai_infrastructure/docs/client-hotpath-agent-prompts/monitoring-signal-contract.md`.
