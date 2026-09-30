# Monitoring service health contract

Every monitoring container publishes its own service health. A container is
`healthy` only while its worker loop is still making progress, so a monitored
customer outage can never be mistaken for a dead monitoring worker, and a
restart is requested only when the worker itself stopped progressing.

## Role commands

The deployed health check is one role-aware command per container:

```bash
python -m monitoring_v2.service_health --role <role>
```

| Container | Role | Evidence read by the check | Startup grace | Stale after | Long-activity window |
|---|---|---|---|---|---|
| `service-monitoring` | `monitor` | `$STATE_PATH`, default `/data/state.json` | 300s | 600s | — |
| `e2e-registry` | `registry` | `$E2E_REGISTRY_DB_PATH`, default `/data/e2e-registry.db` plus loopback `http://127.0.0.1:$E2E_REGISTRY_PORT/health` | 120s | — | — |
| `e2e-runner` | `runner` | `$E2E_RUNNER_HEARTBEAT_PATH`, default `/run/pitchai-health/e2e-runner-heartbeat.json` | 120s | 120s | 14400s |
| `database-dependency-monitor` | `database-dependency` | `$DATABASE_DEPENDENCY_STATE_PATH`, default `/data/database-dependencies.json` | 600s | 900s | — |
| `scheduler-placement-observer` | `scheduler-observer` | `$SCHEDULER_INCIDENT_STATE_PATH`, default `/data/scheduler-placement-observer.json` | 300s | 120s | 300s |
| `domain-incident-events` | `domain-incident` | `$DOMAIN_INCIDENT_EVENT_STATE_PATH`, default `/data/domain-incident-events.json` | 300s | 120s | — |

`--stale-seconds`, `--grace-seconds`, `--extended-seconds`,
`SERVICE_HEALTH_STALE_SECONDS`, `SERVICE_HEALTH_GRACE_SECONDS` and
`SERVICE_HEALTH_EXTENDED_SECONDS` override those defaults for one probe. The
monitor staleness window deliberately equals the `MONITOR_STALE_AFTER_SECONDS`
default of `ops/run-service-monitoring.sh` (600s), so the container check and
the existing bounded watchdog recovery agree.

## Statuses and operator action

The command prints one line, e.g.
`status=degraded role=runner service=e2e-runner reason=registry_claim_failing:timeout phase=idle completed_jobs=3 claim_failure_streak=4 state_age_seconds=5 stale_after_seconds=120`,
and exits 0. An absent `domain-incident` document outside its grace window
prints `status=unhealthy role=domain-incident service=domain-incident-events reason=producer_state_missing state_path=/data/domain-incident-events.json grace_seconds=300`
and exits 1, while an unsupported role prints
`status=unhealthy role=unknown service=unknown reason=usage_error detail=redacted`
to stderr and exits 2.

| Status | Exit | Docker state | Operator action |
|---|---|---|---|
| `healthy` | 0 | `healthy` | None. Progress is fresh for this role. |
| `starting` | 0 | `starting` inside grace | None. First cycle after a restart is expected. |
| `degraded` | 0 | `healthy` | Investigate the named dependency; the worker is still progressing, so do **not** restart it. |
| `unhealthy` | 1 | `unhealthy` after `--health-retries` | Inspect `docker logs`, then restart or repair. The worker stopped progressing. |

Reasons are short and non-secret. Retained free-form text, URLs and credentials
are replaced by narrow classifiers (`redacted`, `unclassified`), so a health
line is safe to quote in an incident note.

Notable reasons:

| Reason | Meaning |
|---|---|
| `state_missing`, `runner_heartbeat_missing`, `collector_state_missing`, `observer_state_missing`, `producer_state_missing`, `registry_database_missing` | Evidence is still absent; `starting` inside the grace window, `unhealthy` after it. |
| `awaiting_first_cycle` | Retained evidence is older than this container's start; the loop has not finished a cycle yet. |
| `monitor_progress_stale`, `runner_poll_stale`, `collector_progress_stale`, `observer_progress_stale`, `producer_progress_stale` | Worker progress is older than the role window. |
| `runner_job_overrun` | A claimed test held the loop longer than the 14400s long-activity window. |
| `state_write_failing`, `browser_probe_degraded`, `registry_claim_failing:<class>`, `collector_cycle_failed:<class>`, `dependency_unhealthy:<status>`, `cycle_error:<class>`, `central_poll_stale` | Recoverable degradation. The worker keeps running; only the named dependency is failing. |
| `registry_http_status`, `registry_http_not_ok`, `registry_inventory_empty` | The registry liveness route is not answering `{"ok": true}`, or its inventory is empty. |
| `registry_unreachable`, `registry_database_unusable`, `registry_liveness_unreadable`, `registry_probe_invalid_response` | The registry probe could not read its own liveness or database. |
| `state_timestamp_missing` | The retained document exists but proves no progress stamp. |
| `usage_error` | The invocation named an unsupported role or an unusable override. |

An idle runner and a long but legitimate in-flight test both stay `healthy`:
the runner reports `progress_fresh` from its loop heartbeat while idle, and from
the in-flight job start while a test is running. Completed runs alone never
carry progress evidence, so an idle queue cannot look like a dead worker.

The registry probe is strictly read-only. It opens the registry database with
SQLite `mode=ro`, reads the schema version marker and inventory counts, and
performs one loopback `GET /health`. It never submits a test, writes a run, or
migrates a schema.

## Deployment wiring

The staged deploy in `.github/workflows/ci-cd.yaml` attaches the role command
with `--health-cmd`, `--health-interval 30s`, `--health-timeout 10s`,
`--health-start-period` (120s/120s/300s/600s per role) and `--health-retries 3`
to `service-monitoring`, `e2e-registry`, `e2e-runner` and
`database-dependency-monitor`. The runner container also mounts
`--tmpfs /run/pitchai-health`, exports `E2E_RUNNER_HEARTBEAT_PATH` and starts
through `python -m e2e_runner.health_main`, which publishes the heartbeat
document the check reads.

After the containers start, the deploy smoke runs
`assert_health_contract <container> <role>` for each of those four containers.
The helper fails the deployment when the container has no `--health-cmd` for
that role, when the health state is `missing`, when it is `unhealthy`, or when
it never becomes `healthy` inside 30 five-second attempts. Failures print
`.State.Health` and the last 200 log lines before exiting non-zero.

## Ownership and install paths

Both the code and the container wiring for all six services live in this
repository:

| Service | Health code | Container wiring |
|---|---|---|
| `service-monitoring` | `monitoring_v2/service_health*.py` (image `Dockerfile`) | `.github/workflows/ci-cd.yaml` (staging + main) |
| `e2e-registry` | same | same |
| `e2e-runner` | same, plus `e2e_runner/health_main.py` and `e2e_runner/heartbeat.py` | same |
| `database-dependency-monitor` | same | same |
| `scheduler-placement-observer` | same | `origin/main` `.github/workflows/ci-cd.yaml` only |
| `domain-incident-events` | same | `origin/main` `.github/workflows/ci-cd.yaml` only |

The last two containers are started by the main-branch deploy section, which
does not exist on staging. Their evidence defaults
(`/data/scheduler-placement-observer.json`,
`/data/domain-incident-events.json`) already match the state paths those
containers export, and their roles are covered by the contract tests, but their
`--health-cmd` wiring is not attached yet.

## Validation

| Area | Test |
|---|---|
| Role coverage, thresholds and deploy wiring | `monitoring_v2/test_service_health_deploy_contract.py` |
| Shared decision table: fresh, missing, stale, malformed, restart, idle, long test, wedged runner | `monitoring_v2/test_service_health_contract.py` |
| Per-role reasons, dependency failure and recovery, unsupported state version | `monitoring_v2/test_service_health_progress_roles.py` |
| Registry usability, startup grace, degraded liveness, unusable database, no mutation | `monitoring_v2/test_service_health_registry_probe.py` |
| Runner heartbeat writer, atomic write, loop instrumentation, published fields | `e2e_runner/test_runner_heartbeat.py` |

Run them with the repository test environment:

```bash
python -m pytest monitoring_v2 e2e_runner -q
```

## Remaining production acceptance

This change is staged only; no production container has been redeployed with it.
The rollout still has to:

1. Deploy the staged release and confirm `.State.Health.Status=healthy` for
   `e2e-registry`, `e2e-runner`, `service-monitoring` and
   `database-dependency-monitor` on the real host, together with the
   `assert_health_contract` smoke output in the deploy log.
2. Add the matching `--health-cmd`, interval, start-period and smoke assertion
   for `scheduler-placement-observer` and `domain-incident-events` in the
   main-branch deploy section, then deploy and capture their live
   `.State.Health` proof.
3. Prove the recovery path once on the host: stop one worker's evidence
   producer (or wait for a genuine stale window) and confirm the container
   reports `unhealthy` with the role reason, then confirm it returns to
   `healthy` after recovery.
