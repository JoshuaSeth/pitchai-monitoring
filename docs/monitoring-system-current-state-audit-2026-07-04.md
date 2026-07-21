# PitchAI Monitoring Current-State Audit - 2026-07-04

PM task: `15954561-ab75-4c02-844f-b39c87d466f4`

Audit window: 2026-07-04, production host `pitchai-main`, mostly between
15:40-15:55 UTC. This was a read-only audit: container/process inspection,
logs, SQLite SELECT/PRAGMA queries, state-file reads, public health checks,
systemd/timer inventory, and Telegram `getMe`/`getChat`. No production
containers were restarted, redeployed, pruned, killed, or reconfigured. No
tokens, API keys, webhook secrets, or raw secret env values are included here.

## Executive Summary

The old `service-monitoring` stack is still running and is still sending
Telegram heartbeats and alerts. The `e2e-registry` dashboard and `e2e-runner`
also still exist and are processing jobs. The current production state is not a
full monitoring outage.

The system is not fully behaving as originally intended:

- Telegram delivery works, but the live route is `@pitchai_service_monitoring_bot`
  to Seth's private chat `5246077032`, not the newer KB-standard PitchAI Updates
  group `-5370767158` via `@pitchai_updates_bot`.
- Automatic CodeOps/Dispatcher escalation is effectively broken. The intended
  design still exists in code, but the retained `service-monitoring`
  `dispatch_history` has 500 retained failures and 0 retained successes, and
  recent service-monitoring/e2e-registry attempts fail with Dispatcher `401
  Unauthorized`. `service-monitoring` has disabled dispatch in memory for this
  runtime after the auth failure.
- The loudest current red signal is not an intruder or broad service outage.
  `autopar.pitchai.net` is HTTP 200 and renders its login page, but the deployed
  monitor expects title `AutoPAR Web App` while the live page title is `AutoPAR`.
  A local, uncommitted checkout already contains the matching title correction,
  but it is not deployed.
- Host/SLO/RED/proxy signals are noisy under old thresholds. Current host red is
  driven by swap and occasional load threshold violations; SLO/RED are dominated
  by the AutoPAR browser mismatch and rolling history.
- The external E2E registry is active. It has 35 tests in SQLite, 7 with
  `enabled=1`, of which 3 are effectively parked until 2030 through
  `disabled_until_ts`. The practical active set is 4 tests. No practical active
  test is currently failing. `afasask_gzb_codex_medium_ok_daily` passed on
  2026-07-04T08:29:38Z and remains the daily AFASAsk test that should be
  included in morning monitoring reviews.
- The deployed E2E status summary endpoint still reports `failing_tests=2`
  because disabled `formatief-toetsen.pitchai.net` rows are counted. That is a
  summary/reporting bug, not evidence that enabled DFT tests are currently
  running or failing.

## Reconstructed Architecture

### `service-monitoring`

Source of truth: repo `pitchai-monitoring`, command
`python -m domain_checks.main`.

Main responsibilities:

- Runs minute-by-minute configured domain checks from `domain_checks/config.yaml`
  and per-domain `domain_checks/<domain>/check.py`.
- Performs HTTP checks and Playwright browser checks.
- Maintains persisted state in `STATE_PATH`, currently `/data/state.json` on the
  `service-monitoring-state` Docker volume.
- Sends Telegram DOWN/recovery/degraded/heartbeat messages through
  `domain_checks/telegram.py`.
- Tracks additional signals: host health, performance, SLO, TLS, DNS, RED,
  API contract, synthetic transactions, web vitals, container health, proxy, and
  meta-monitoring.
- Optionally dispatches read-only investigation work to PitchAI Dispatcher using
  `PITCHAI_DISPATCH_BASE_URL` and `PITCHAI_DISPATCH_TOKEN`.
- Includes E2E status summaries in scheduled heartbeats via
  `E2E_REGISTRY_BASE_URL` and `E2E_REGISTRY_MONITOR_TOKEN`.

Alert design:

- Domain DOWN alerts fire after the configured debounce
  `alerting.down_after_failures` and recover after `up_after_successes`.
- Signal degraded alerts use their own debounce and optional
  `dispatch_on_degraded`.
- Telegram sending is independent from Dispatcher dispatch. Telegram can still
  work while Dispatcher dispatch is disabled.

### `e2e-registry`

Source of truth: same Docker image, command `python -m e2e_registry.server`.

Main responsibilities:

- FastAPI registry/dashboard for external and internal E2E tests.
- SQLite DB at `/data/e2e-registry.db`.
- Artifacts under `/artifacts`.
- Dashboard and monitoring APIs behind `https://monitoring.pitchai.net`.
- Reads `/monitor_state/state.json` from the shared monitor volume read-only for
  dashboard views.
- Sends alerts and can optionally dispatch failure investigations when tests have
  `dispatch_on_failure=1`.

### `e2e-runner`

Source of truth: same Docker image, command `python -m e2e_runner.main`.

Main responsibilities:

- Polls `e2e-registry` every 5 seconds.
- Claims due jobs with runner token.
- Executes uploaded/registered E2E tests.
- Posts completion status and artifacts back to the registry.

### Deployment

The repo's GitHub Actions workflow builds one Docker image and deploys three
containers on pushes to `main`:

- `service-monitoring`
- `e2e-registry`
- `e2e-runner`

Runtime is Docker restart policy based, not a systemd timer. Relevant systemd
timers on the host were `codex-git-sync.timer`, `certbot.timer`,
`pitchai-events-bus-renew.timer`, and `mdmonitor-oneshot.timer`; no
`service-monitoring`/`e2e` timer was present.

### Dispatcher / CodeOps Path

Functional design:

- `service-monitoring` queues Dispatcher investigations on debounced domain
  UP->DOWN transitions and on degraded signals configured with
  `dispatch_on_degraded`.
- `e2e-registry` queues Dispatcher investigations for tests with
  `dispatch_on_failure=1` after the E2E failure debounce.
- Both paths call `https://dispatch.pitchai.net/dispatch` with
  `PITCHAI_DISPATCH_TOKEN`, then poll `/runs/<bundle>/status` and forward the
  final agent report to Telegram.
- `service-monitoring` records attempts in `dispatch_history`; on 401/403 it
  disables dispatch for the current runtime until token/config is fixed and the
  service restarts.

Empirical reality in this audit:

- `service-monitoring` retained `dispatch_history_count=500`, `ok_count=0`.
- Recent retained errors are Dispatcher timeouts followed by `401 Unauthorized`
  for `/runs/<bundle>/status` and `/dispatch`.
- Recent service logs show `Dispatch not scheduled ... enabled=False
  reason=auth_error_401`.
- `e2e-registry` has `E2E_REGISTRY_DISPATCH_ENABLED=1`, and AFASAsk tests have
  `dispatch_on_failure=1`, but `dispatch_runs` has 0 rows and recent registry
  logs show `POST /runner/runs/.../complete` returning 500 because dispatch to
  `/dispatch` raised `401 Unauthorized`.
- The `pitchai-codex-dispatcher` container is running, but its recent logs also
  show a project scheduler DB connection failure to `172.26.0.5:6432`.

Conclusion: automatic investigation dispatch is designed, but not reliable in
current production. Treat it as non-functional until Dispatcher auth and the
registry exception path are fixed and validated with a real safe test dispatch.

## Current Production Runtime

Snapshot from `docker ps` / `docker inspect` on 2026-07-04T17:49:48+02:00:

| Container | Image/command | Status | Restart count | Healthcheck | Notes |
| --- | --- | --- | --- | --- | --- |
| `service-monitoring` | `service-monitoring:44405a340b5a44008ec07e9735422c96d9fb9de3`, `python -m domain_checks.main` | Up 7 days | 0 | none | Main monitor. |
| `e2e-registry` | same image, `python -m e2e_registry.server` | Up 4 weeks | 0 | none | Bound to `127.0.0.1:8111`; public via `monitoring.pitchai.net`. |
| `e2e-runner` | same image, `python -m e2e_runner.main` | Up 4 weeks | 0 | none | Current process is running; Docker inspect still has old `OOMKilled=true` marker. |
| `pitchai-codex-dispatcher` | `pitchai-codex-dispatcher:watchdog-20260609T183107Z`, uvicorn on 8129 | Up 3 weeks | 0 | none | Dispatcher target exists, but auth/DB symptoms remain. |

Mounts and network:

- All four containers are attached to `pitchai-shared`.
- `service-monitoring` mounts:
  - `/var/log/nginx` read-only
  - `service-monitoring-state` -> `/data` read-write
  - `/var/run/docker.sock` read-write
- `e2e-registry` mounts:
  - `e2e-artifacts` -> `/artifacts` read-write
  - `service-monitoring-state` -> `/monitor_state` read-only
  - `e2e-registry-data` -> `/data` read-write
- `e2e-runner` mounts:
  - `e2e-artifacts` -> `/artifacts` read-write
  - `e2e-registry-data` -> `/data` read-only
- Dispatcher mounts host and Codex data paths plus Docker socket.

Public endpoint checks:

- `https://monitoring.pitchai.net/health` returned HTTP 200.
- `https://monitoring.pitchai.net/dashboard` returned HTTP 303 to
  `/dashboard/login`.
- Registry status summary without token returns 401, so the monitor API is not
  openly exposed.

Runtime env presence, redacted:

- `service-monitoring` has `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`,
  `PITCHAI_DISPATCH_BASE_URL`, `PITCHAI_DISPATCH_TOKEN`, `STATE_PATH`,
  `E2E_REGISTRY_BASE_URL`, and `E2E_REGISTRY_MONITOR_TOKEN`.
- `e2e-registry` has Telegram env, E2E admin/monitor/runner tokens,
  strict base URL policy enabled, alerts enabled, dispatch enabled, public base
  URL, and Dispatcher env.
- Secret values were not printed. `TELEGRAM_CHAT_ID` is not a token and is
  included below because routing was part of the audit.

## Telegram Routing

Live Telegram API checks using the configured service-monitoring bot token:

- Bot: `@pitchai_service_monitoring_bot`, first name `Service Monitoring Bot`,
  bot id `8559412399`.
- Chat: id `5246077032`, type `private`, first name `Seth`.
- The same `TELEGRAM_CHAT_ID=5246077032` is present in `service-monitoring` and
  `e2e-registry`.

KB/current convention:

- Ordinary PitchAI operational updates should route to group `PitchAI Updates`,
  chat id `-5370767158`, via `@pitchai_updates_bot`.

Finding:

- Monitoring Telegram sends work, but current production monitoring messages go
  to Seth private chat through `@pitchai_service_monitoring_bot`, not the
  PitchAI Updates group. This is routing drift unless Seth explicitly wants this
  monitoring lane to remain private.

Recent Telegram evidence from service logs:

- Heartbeats sent successfully:
  - 2026-07-02 07:30 CEST, message id 6317
  - 2026-07-02 12:00 CEST, message id 6319
  - 2026-07-03 07:30 CEST, message id 6325
  - 2026-07-03 12:00 CEST, message id 6329
  - 2026-07-04 07:30 CEST, message id 6342
  - 2026-07-04 12:00 CEST, message id 6343
- Proxy degraded alerts sent successfully with message ids 6320, 6323, 6337,
  6339, 6341, 6344, 6346, 6350, and 6354.
- Other recent sent alerts included `skybuyfly.pitchai.net` DOWN, container
  health degraded for `aipc`, host health degraded, and browser degraded.

## Current Monitor State

State file:

- Path: `/data/state.json`
- Version: 5
- Updated at: `2026-07-04T15:50:51Z`
- Size: about 13.18 MB
- Freshness at sample: about 14 seconds old
- Retains 20,120 samples per domain/signal in several histories and 2,000 event
  entries.

Domain state at sample:

| Domain | Current | Fail streak | Success streak | Notes |
| --- | --- | ---: | ---: | --- |
| `afasask.gzb.nl` | OK | 0 | 189 | Re-enabled and currently healthy. |
| `autopar.pitchai.net` | BAD | 239 | 0 | HTTP 200; browser title mismatch. |
| `cms.deplanbook.com` | OK | 0 | 240 | Healthy at sample. |
| `deplanbook.com` | OK | 0 | 240 | Healthy at sample. |
| `dpb.pitchai.net` | OK | 0 | 240 | Healthy at sample. |
| `hetcis.nl` | OK | 0 | 240 | Healthy at sample. |
| `skybuyfly.pitchai.net` | OK | 0 | 240 | Had a real transient DOWN alert on July 2, recovered. |

Latest AutoPAR evidence:

- `https://autopar.pitchai.net/login-page` returned HTTP 200.
- Final host was `autopar.pitchai.net`.
- Title was `AutoPAR`.
- Required selectors/text checks passed.
- The deployed production check expects title substring `AutoPAR Web App`.

Conclusion: current AutoPAR red is monitor expectation drift, not evidence of an
intruder or service compromise from this monitor's data.

Signal state at sample:

| Signal | Current | Fail streak | Main driver |
| --- | --- | ---: | --- |
| `browser` | effectively OK | n/a | Browser process had one degraded incident and recovered. |
| `container_health` | OK | 0 | One bad sample in retained history. |
| `dns` | OK | 0 | No current DNS issue. |
| `host_health` | BAD | 242 | Swap about 99.6%; old threshold is 80%. |
| `meta` | OK | 0 | State writes are fresh. |
| `performance` | OK | 0 | No current perf threshold issue. |
| `proxy` | OK | 0 | No current proxy issue, but frequent recent degraded alerts. |
| `red` | BAD | 10159 | Rolling error history, dominated by AutoPAR browser mismatch. |
| `slo` | BAD | 10160 | Rolling SLO burn, dominated by AutoPAR/browser mismatch. |
| `tls` | OK | 0 | No current TLS issue from this monitor. |

Recent important log events:

- 2026-07-02T19:37Z: `skybuyfly.pitchai.net` DOWN alert after two HTTP read
  timeouts; Telegram sent; dispatch not scheduled because of `auth_error_401`.
- 2026-07-02T19:40Z: container health degraded for `aipc`; Telegram sent.
- 2026-07-04T11:51Z: proxy degraded, host health degraded, and browser degraded
  notices sent. Browser process restarted and recovered by 11:56Z.
- 2026-07-04: repeated AutoPAR browser warnings, all showing HTTP 200 and title
  mismatch.

## E2E Registry and Runner State

Registry and runner still exist and are doing work:

- `e2e-runner` polls `/api/v1/runner/claim` every 5 seconds.
- Recent runner logs show claimed jobs and successful completion posts.
- Registry health is OK.

SQLite inventory:

- Total tests: 35
- Rows with `enabled=1`: 7
- Rows with `enabled=0`: 28
- Functionally active tests: 4, because 3 `zz_disabled_temp_*` rows have
  `disabled_until_ts=2030-01-01T00:00:00Z`.

Enabled/active important tests:

| Test name | Base URL | Interval | Dispatch on failure | Latest status |
| --- | --- | ---: | --- | --- |
| `afasask_gzb_codex_medium_ok_daily` | `https://afasask.gzb.nl` | 86400s | yes | pass at 2026-07-04T08:29:38Z |
| `afasask_gzb_codex_medium_ok` | `https://afasask.gzb.nl` | 1800s | yes | pass at 2026-07-04T15:46:11Z |
| `deplanbook_cms_home_smoke_py` | `https://cms.deplanbook.com` | 300s | no | pass at 2026-07-04T15:47:07Z |
| `deplanbook_cms_on_demand_translation_py` | `https://cms.deplanbook.com` | 300s | no | pass at 2026-07-04T15:50:34Z |

Recent E2E result counts:

- Last 24h: 589 pass, 1 fail.
- Recent non-pass runs are AFASAsk `afasask_gzb_codex_medium_ok` assertion
  failures containing the failed-marker text. The latest one was
  2026-07-04T13:44:14Z and later runs passed.
- `dispatch_runs` table count is 0.

Important `formatief-toetsen.pitchai.net` finding:

- The registry contains 28 disabled tests for
  `https://formatief-toetsen.pitchai.net`.
- These are disabled by strict base URL policy and are not currently being run
  as enabled tests.
- The deployed `/api/v1/status/summary` still returns `failing_tests=2` because
  disabled rows are counted in the headline. It does not expose newer
  `enabled_tests`/`disabled_tests` fields.
- The local checkout in `/root/code/pitchai-monitoring` already has uncommitted
  changes that filter disabled rows from the heartbeat and status-summary
  failing count, but those changes are not deployed and were not modified by
  this audit.

## Drift From Intended Behavior

High-impact drift:

- Automatic dispatch is not reliable. This is the largest functional gap,
  because the code path that is supposed to dispatch CodeOps/investigation work
  is currently failing authentication and then being suppressed.
- Telegram route does not match the current KB operational-update convention.
  Messages go to Seth private chat, not PitchAI Updates.
- No Docker healthchecks exist on the monitor, registry, runner, or dispatcher
  containers. Docker can keep a broken process "up" without endpoint-level
  health semantics.
- The deployed AutoPAR browser check is stale relative to the current site
  title.
- The deployed E2E status summary counts disabled rows as failing and lacks
  enabled/disabled counters.

Noise/operability drift:

- Host health thresholds are old and strict for this host's current operating
  profile, especially swap >= 80%. The current host is almost always over that
  threshold, so host health is frequently red.
- SLO/RED burn calculations are currently dominated by the stale AutoPAR browser
  check, reducing their value as service health indicators.
- Proxy degraded alerts are frequent. The local checkout has uncommitted changes
  that reduce shared-host proxy false positives by treating global access logs
  more carefully, but those changes are not deployed.
- Three parked `zz_disabled_temp_*` rows still have `enabled=1` plus
  `disabled_until_ts=2030`, which is semantically confusing for dashboards and
  reviews.
- `e2e-registry` lets a dispatch failure raise through the runner completion
  endpoint, producing a 500 even though the run result is otherwise recorded.

Stale documentation risk:

- README correctly describes intended Dispatcher escalation, but current
  production does not satisfy that behavior.
- Documentation does not clearly state the current Telegram route decision or
  the distinction between the old service-monitoring lane and the newer steward
  lanes.

## Relationship to Newer Monitoring Lanes

Observed newer lanes from PM/KBI/repo inventory:

- `server-health-steward`: recurring host/fleet sweeps across production/dev,
  DB, compute, file storage, Mac/dev-server style resources. This overlaps with
  host health, but it is human/agent sweep oriented rather than minute-by-minute
  domain uptime.
- `seaweedfs-health-steward`: storage topology, space, vacuum, mounts, and
  SeaweedFS-specific health. This owns file-storage monitoring more directly
  than the old generic container/host checks.
- `devops-cicd-monitor`: workflow, runner, deploy, CI/CD inventory and safe YAML
  hotfixes. This owns CI/CD monitoring, not per-domain uptime.
- Hetzner monitor: auction/provider inventory and cost/opportunity monitoring,
  not service uptime.
- Jeff/Jef monitor: activity/dev-server/user-specific monitoring, not generic
  PitchAI domain uptime.
- `pitchai-events-bus`: M365 webhook ingestion and subscription renewal. It is
  active as a systemd service/timer, but it is not replacing the old
  service-monitoring alert path.
- Future event-drainer/rule-based monitoring: not observed as a live replacement
  in this audit. It remains a likely target architecture to unify alerts and
  reduce reminder/container overlap.

Recommended ownership boundary:

- Keep `service-monitoring` responsible for minute-level user-facing domain
  checks, browser correctness checks, Telegram heartbeat/alert synthesis, and
  E2E status inclusion.
- Keep `e2e-registry`/`e2e-runner` responsible for test registration, run
  scheduling/execution, artifacts, and per-test status.
- Move deep host/storage/CI/CD/provider/person-specific investigations to the
  newer specialized lanes.
- Do not rely on the old monitor to dispatch CodeOps until the Dispatcher auth
  path is fixed and a synthetic dispatch canary proves it.

## Recommended Next Steps

Priority 0 - decide routing:

- Decide whether production service monitoring should continue to DM Seth or
  move to PitchAI Updates group `-5370767158`. If moving, update the deployment
  secret/env source, not the repo, and verify with one explicit test message.

Priority 1 - restore automatic investigation dispatch:

- Rotate or correct `PITCHAI_DISPATCH_TOKEN` for `service-monitoring` and
  `e2e-registry`, then restart only after a reviewed change window.
- Add a safe dispatch canary that queues a no-op/read-only investigation and
  verifies `/dispatch` and `/runs/<bundle>/status` end-to-end.
- Fix `e2e-registry` so dispatch failures do not cause runner completion 500s.
  A failed dispatch should be recorded and alerted, not break result ingestion.

Priority 1 - reduce current false red:

- Deploy the AutoPAR title update from `AutoPAR Web App` to `AutoPAR` after
  confirming the login page title is intentionally changed.
- Deploy the E2E summary fix so disabled tests do not count as failing in
  heartbeat/status headlines and expose enabled/disabled counts.

Priority 2 - harden monitor runtime:

- Add Docker healthchecks for `service-monitoring`, `e2e-registry`,
  `e2e-runner`, and Dispatcher, or add an external watchdog that checks each
  process through a real endpoint/state freshness probe.
- Add a monitor self-check that alerts when `dispatch_history` has continuous
  failures or when dispatch has been disabled due auth.
- Revisit host/proxy/SLO/RED thresholds after AutoPAR is fixed. Treat host swap
  separately from immediate service outage unless backed by latency/error
  impact.
- Normalize parked E2E tests: use `enabled=0` for truly disabled rows instead
  of `enabled=1` plus `disabled_until_ts=2030`.

Priority 3 - clarify architecture:

- Update README/docs after routing and dispatch decisions are made so the docs
  distinguish intended behavior from currently validated behavior.
- Define the handoff between `service-monitoring` and specialized steward lanes
  in one operations doc.
- Plan event-drainer/rule-based monitoring as the eventual consolidation layer,
  but do not treat it as currently protecting service-monitoring gaps.

## Bottom Line

`service-monitoring`, `e2e-registry`, and `e2e-runner` are alive and producing
signals. Telegram alert delivery works. The biggest current correctness gaps are
that alert routing is private-DM rather than PitchAI Updates, and automatic
CodeOps/Dispatcher investigation is not currently dependable. The current red
noise is mostly stale monitor expectations and threshold drift, not evidence of
a live intruder from the inspected monitoring data.
