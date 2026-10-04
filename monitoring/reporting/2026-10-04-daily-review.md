# Daily monitoring review: 2026-10-04

## Decision

The monitor itself is healthy and every monitor-checked product domain that is
expected to be up is up, but the day is **not** all clear. Five patterns were
escalated in one requester-private Telegram to Seth van der Bijl:

1. **New: both AFASAsk Codex canaries failed for about 75 minutes on
   2026-10-03.** `afasask_production_codex_medium_synthetic_ok` failed three
   times (13:08:41Z, 13:43:38Z, 14:17:57Z) with a 240 s
   `wait_for_function` timeout, and `afasask_demo_codex_fast_ok` failed three
   times (13:20:26Z, 13:51:26Z, 14:22:27Z) with
   `afasask_demo_codex_canary_failed_marker: ❌ mislukt`. `failure.png` on
   **both** lanes shows the real product failure: "Codex mode mislukt. De Codex
   subprocess is gestopt met een fout" with
   `ERROR codex_core::models_manager::manager: failed to refresh` at
   13:08:43.920783Z (production) and 13:20:29.205648Z (demo);
   `browser_infra_error=false` on both. Both lanes have recovered - 24
   consecutive passes each, latest 18.5 min and 17.6 min before collection.
2. **`pitchai-main` memory rose sharply and disk kept tightening.** Memory went
   from 69.3 % at the start of the window to 85-86 % (peak 93.63 % around
   12:00Z), leaving 8.1 GiB available where yesterday there were 19-20 GiB.
   Swap stayed pinned at 100 % (32-44 KiB free of 31 GiB) for the whole day,
   and `host_health` violations per cycle went from 2 to 3. `/dev/md2` moved
   from 91 % to **93 % (`df`, 125 GB free, was 154 GB)** in 24 h - about 29 GB
   consumed - and the monitor's own worst-disk reading rose from 86.03 % to
   88.78 %.
3. **Three monitor domains are failing right now, not just historically**:
   `whatsapp.pitchai.net` 383/577 (66.4 %, 194-sample fail streak, live
   `/readyz` 503), `salesengine.demos.pitchai.net` 388/577 (67.2 %, 189-sample
   fail streak, live `/readyz` 502) and `aigenda-rules.demos.pitchai.net`
   432/576 (75.0 %, 23-sample fail streak, live `/readyz` 503). All three are
   in alertable `critical` groups, taking the dashboard's alertable-down count
   from 5 to 8. `whatsapp.pitchai.net` was 705/705 on 2026-09-30 and 684/684 on
   2026-10-01, so this is a fresh regression.
4. **New critical hotpath lane: `potaito-hotpath-monitor`**, first failure
   2026-10-03T20:17:47Z with class `stylesheet_delivery_failure` - production
   failed `pinned-historical-snapshot` and staging failed
   `current-operational-h1-h3`; both recorded `site.css` with
   `net::ERR_HTTP2_PROTOCOL_ERROR` and visibly unstyled pages, and both passed
   revision provenance. The monitoring domain check cannot see this (the route
   answers its expected 401), so this is lane-only evidence.
5. **Carried, worse: `meilisync-learning-goals-custom-staging` restart count
   2 422 -> 3 803** (exit 137 roughly every 62 s, `OOMKilled=false`), still not
   matched by the monitor's container patterns; plus the unchanged
   `aipc-fsn1-01` audit/quarantine failures
   (`ci-runner-contract-invalid`, `ci-runner-installed-source-invalid`,
   `deploy-authorized-key-policy-invalid`, installed byte mismatch on
   `/usr/local/sbin/aipc-deploy-ssh-dispatch`) and the `pitchai-main`
   `aipc-hel1-canary-transport-audit.service` red since 2026-09-30 on a strict
   `{"status":"ok"}` contract while the live endpoint also returns `service`.

Everything else in the core set is green: monitor state is fresh
(`updated_at` 2026-10-04T03:00:23Z, version 6, 60 s interval, 180 s stale
threshold, `state_write_fail_streak=0`), six of the seven enabled monitor
domains were 100 % available across 576 samples each, zero enabled external E2E
tests are currently failing, `nginx -t` passes, the registry serves its current
certificate, and all 45 certbot lineages are valid with the earliest expiry on
2026-11-06 (about 33 days).

No fix, reclamation, cutover or production mutation was performed by this lane.
Collection ran 2026-10-04T03:02-03:10Z (05:02-05:10 CEST); the evidence window
is 2026-10-03T03:00Z to 2026-10-04T03:00Z.

## Enabled monitor domains (24 h window, 576 samples each)

| Domain | Samples | OK | HTTP p95 | Browser p95 | Last | Note |
| --- | --- | --- | --- | --- | --- | --- |
| `autopar.pitchai.net` | 576 | 576 (100 %) | 73.3 ms | 14 101 ms | 302 | success streak 166 |
| `afasask.gzb.nl` | 576 | 576 (100 %) | - | - | 307 | contract + synthetic OK |
| `skybuyfly.pitchai.net` | 576 | 564 (97.92 %) | 210.3 ms | 16 911 ms | 200 | 4 x 502 + 7 null codes, recovered |
| `deplanbook.com` | 576 | 576 (100 %) | - | - | 200 | one transient upstream close (static img) |
| `cms.deplanbook.com` | 576 | 576 (100 %) | - | - | 200 | 269 E2E runs, all pass |
| `dpb.pitchai.net` | 576 | 576 (100 %) | - | - | 302 | - |
| `hetcis.nl` | 576 | 576 (100 %) | - | - | 200 | - |

`afasask.pitchai.net` (disabled/skipped as a monitor target) was also 576/576.
`stable.skybuyfly.pitchai.net` matched `skybuyfly.pitchai.net` at 564/576
(97.92 %). Both skybuyfly routes recovered inside the window
(`domain_down` at 03:18Z and 03:29Z, `domain_up` 03:31Z, `api_contract`
degraded and recovered at 03:52-04:04Z).

Aggregate across every domain with samples in the window: **53 661 samples,
47 339 OK = 88.22 %** (yesterday 88.63 %), with 15 domains having at least one
failure:
10 at 0 % that are all expected/policy routes, the three live failures above,
and the two skybuyfly sample sets.

## New live availability failures (escalated)

| Domain | 24 h OK | Fail streak | Live probe | Group policy |
| --- | --- | --- | --- | --- |
| `whatsapp.pitchai.net` | 383/577 (66.4 %) | 194 | `/readyz` 503 in 0.02 s | `critical`, alertable |
| `salesengine.demos.pitchai.net` | 388/577 (67.2 %) | 189 | `/readyz` 502 in 0.008 s | `critical`, alertable |
| `aigenda-rules.demos.pitchai.net` | 432/576 (75.0 %) | 23 | `/readyz` 503 in 0.13 s | `critical`, alertable |

All three answer through nginx without upstream error-log lines of their own, so
the 5xx comes from the application behind the route rather than a dead nginx
upstream. `aigenda-rules.demos.pitchai.net` also flapped on 2026-09-30 and again
at 2026-10-03T21:28Z; `whatsapp.pitchai.net` was healthy on 2026-09-30 and
2026-10-01 and its readiness path was repaired on 2026-09-28 (PM task
`527893ec`), so this is a regression of a previously fixed surface.

## Finding 1 - AFASAsk Codex canaries failed for ~75 minutes (escalated)

Both enabled Codex-path tests are hourly-ish (1 800 s interval) and both failed
three times in an interleaved pattern:

| Time (UTC) | Test | Error | Evidence |
| --- | --- | --- | --- |
| 13:08:41 | `afasask_production_codex_medium_synthetic_ok` | `TimeoutError: Page.wait_for_function: Timeout 240000ms exceeded.` | screenshot shows `Codex mode mislukt` + `codex_core::models_manager::manager: failed to refresh` at 13:08:43Z |
| 13:20:26 | `afasask_demo_codex_fast_ok` | `AssertionError: ... ❌ mislukt` | screenshot shows the same Codex-mislukt block at 13:20:29Z |
| 13:43:38 | production medium | timeout as above | - |
| 13:51:26 | demo fast | `❌ mislukt` | - |
| 14:17:57 | production medium | timeout as above | - |
| 14:22:27 | demo fast | `❌ mislukt` | - |

Both `run.log` files report `browser_infra_error: false`, and the screenshots
show the failure block that renders outside `article[data-role="assistant"]`, so
neither failure is a harness or selector problem. The shared root signal is the
Codex subprocess dying with
`ERROR codex_core::models_manager::manager: failed to refresh` (the log line is
clipped by the screenshot boundary). Recovery: `success_streak=24` on both
lanes with `fail_streak=0`, last passes 2026-10-04T02:44:54Z (production) and
02:45:48Z (demo).

## Finding 2 - `pitchai-main` memory and disk pressure (escalated)

| Metric | Window start (03:06Z) | Latest (01:32Z-03:00Z) | Change |
| --- | --- | --- | --- |
| Memory used | 69.3 % | 85-86 % (peak 93.63 %) | +16 points |
| Available memory | ~19-20 GiB | 8.1 GiB | -11 GiB |
| Swap used | 100 % (32 KiB free) | 100 % (32-44 KiB free) | unchanged, pinned |
| Worst disk (monitor) | 86.03 % | 88.78 % | +2.75 points |
| Disk `df` `/dev/md2` | 91 % (154 GB free) | 93 % (125 GB free) | -29 GB free |
| `host_health` violations | 2 per cycle | 3 per cycle | +1 |

CPU (43-45 %) and load (18-21 on 32 CPUs, 0.55-0.66 per CPU) are unchanged, so
this is memory and disk, not compute. The largest resident process is a 5.0 GB
gunicorn plus a tail of ~1 GB python processes. Docker accounts for the disk
growth: images went 344 GB -> **367.3 GB** (291.3 GB reclaimable, 79 %) while
volumes (128.2 GB) and build cache (33.08 GB) are flat; journals take 4.0 GB.
The three cleanup units that would normally bound this are still failing every
run: `registry-cleanup.service` (exit 1), `pitchai-production-builder-cache-cleanup.service`
(exit 22) and `pitchai-potai-staging-release-cleanup.service` (exit 1).

## Finding 3 - `meilisync-learning-goals-custom-staging` restart loop (escalated)

`RestartCount` 2 422 -> **3 803**, `status=restarting`, `OOMKilled=false`,
`unless-stopped`, no memory limit; last start 2026-10-04T03:04:19Z. The name is
still not matched by the monitor's container patterns (only
`^meilisync-formatief-toetsen(?:-staging)?$` is matched), so `container_health`
stays a false-positive signal and the loop itself is unmonitored.
`meilisync-formatief-toetsen` and `meilisync-formatief-toetsen-staging` each
show 3 restarts and are running.

## Finding 4 - `potaito-hotpath-monitor` stylesheet delivery failure (escalated)

First failure 2026-10-03T20:17:47Z, severity `critical`, class
`stylesheet_delivery_failure`: production failed `pinned-historical-snapshot`
and staging failed `current-operational-h1-h3` (document width 1 848 px exceeds
the 1 425 px viewport), both with `site.css` aborting on
`net::ERR_HTTP2_PROTOCOL_ERROR` and visibly unstyled pages; provenance was
GREEN on both. This lane was `info` since 2026-10-01Z22:01. An unauthenticated
probe of `potaito.pitchai.net` and `staging.potaito.pitchai.net` returns the
expected 401, so the monitoring lane cannot reproduce or clear this without the
lane's credentials; the lane evidence stands as reported.

## Finding 5 - `aipc-fsn1-01` audits and HEL1 transport audit (escalated, server-ops)

- `aipc-fsn1-01` `aipc-host-audit.service` failed again at 2026-10-04T03:03:38Z
  with `ci-runner-contract-invalid`, `ci-runner-installed-source-invalid` and
  `deploy-authorized-key-policy-invalid`, plus
  `installed byte mismatch: /usr/local/sbin/aipc-deploy-ssh-dispatch`.
  `aipc-docker-maintenance.service` still refuses while the retained HDD cold
  tier is quarantined.
- `pitchai-main` `aipc-hel1-canary-transport-audit.service` remains red
  (first failure 2026-09-30 06:15 CEST, 800+ `quickchat-health-contract-invalid`
  runs) because the audit demands exactly `{"status":"ok"}` while the live
  endpoint returns `{"status":"ok","service":"skybuyfly-quickchat"}`; live
  probes return 200, so this is a broken verification contract, not an outage.
- Both AIPC hotpath lanes stay `critical`:
  `aipc-hotpath-monitor` (fail streak 25,
  `RECOMMENDATION_API_DEPLOYMENT_REVISION_MISMATCH`, observed deployed
  `44b6e365...` vs expected source `36ddbfc2...`) and
  `aipc-pedantic-e2e-ui-qa-v2` (fail streak 15, same class). Both reported
  again after yesterday's silence (6.8 h and 7.3 h old).

## Signals (24 h)

| Signal | Samples | Bad | Latest | Notes |
| --- | --- | --- | --- | --- |
| `browser` | 576 | 0 | ok | `degraded_active=false`, 0 launch failures |
| `dns` | 88 | 0 | ok | 93 domains resolved |
| `tls` | 24 | 24 | fail | `fail_streak=636`, 3 retained failures per cycle |
| `host_health` | 576 | 576 | fail | swap 100 %, mem 85-86 %, cpu 43-45 %, load1/cpu 0.55-0.66, worst disk 88.78 %, 3 violations |
| `performance` | 576 | 576 | fail | 43-45 slow domains (standing) |
| `slo` | 576 | 576 | fail | 8 SLO violations per cycle (standing) |
| `red` | 576 | 576 | fail | 49 RED violations per cycle (standing) |
| `container_health` | 576 | 576 | fail | `fail_streak=8 707`, 1 issue: retired `dft-worker` `Exited (0)` |
| `proxy` | 576 | 4 | ok | `success_streak=38`, `pct_502_504=0.0`, 0 upstream error events |
| `meta` | 576 | 576 | fail | `reason_count=1` (standing), cycle 141-155 s, `state_write_fail_streak=0` |

`api_contract`: all targets OK except the two standing ones
(`dispatch.pitchai.net` fail streak 9 222, `codexusage.pitchai.net` 110);
`afasask.gzb.nl`, `demo.afasask.pitchai.net`, `autopar.pitchai.net`,
`deplanbook.com`, `dpb.pitchai.net`, `skybuyfly.pitchai.net` and the
`*.sslip.io` helpers report success streaks of 6-644. `synthetic`: all nine
probes OK. `web_vitals`: `agents.pitchai.net` (74), `aigenda.pitchai.net`
(272), `breakglass.pitchai.net` (301), `registry.pitchai.net` (301) and the
five `jeff-*` names (206-300) carry long informational fail streaks - recorded,
not an outage.

Events in the window: 13 `domain_down`, 10 `domain_up`, 4 `api_contract_degraded`,
4 `api_contract_recovered`, 2 `proxy_degraded`, 2 `proxy_recovered`.

## Standing down and excluded set

The dashboard reports `service_health` **93 enabled domains: 78 healthy, 15
down, of which 7 are expected/policy-down and 8 alertable**
(`alertable_down=8`, yesterday 5). The five standing alertable names are
`dispatch.pitchai.net` (every HTTP sample OK, contract red 9 222), `codexusage.pitchai.net`
(same shape, 110), and the `jeff-codex-voice` / `jeff-dispatch` /
`jeff-work-inbox` trio (`ConnectError` to the dead 94.130.17.246). The three new
alertable names are the live failures above.

Expected/policy-down (dashboard-only, no paging): `registry.pitchai.net`
(`ConnectTimeout` from the monitor container - see TLS section),
`agentcloud.pitchai.net` (502), `dashboards.pitchai.net` (502),
`support.pitchai.net` (502), `cursussen.pitchai.net` (404) and the two
`.nip.io` bootstrap aliases of the `jeff-*` hosts.

Group rollups: `operations` attention (3 alertable), `learning-demos` attention
(2 alertable + 1 expected), `jeff-internal` attention (3 alertable + 2 expected),
`infrastructure` expected (4 expected); corporate, platform-apps, afasask,
autopar, dft and potaito groups are healthy.

## External E2E (scoped)

Registry scope first: **36 rows = 4 schedulable recurring tests, 3 temporarily
paused, 29 disabled.**

- Schedulable recurring: `deplanbook_cms_home_smoke_py`,
  `deplanbook_cms_on_demand_translation_py`, `afasask_demo_codex_fast_ok`,
  `afasask_production_codex_medium_synthetic_ok`.
- Temporarily paused: the three `zz_disabled_temp_*` probes
  (`enabled=1`, `disabled_until_ts=1893456000`, reason `temporary probe
  cleanup`); they last ran 2026-02-26 and their historical `pass` is not current
  evidence.
- Disabled: 29 rows including the retired `afasask_gzb_codex_medium_ok_daily`
  (`enabled=0`, never quoted as current evidence).

Runs in the 24 h window: **631 total, 625 pass, 6 fail.**

| Test | Runs (pass/fail) | Latest status | Finished | Streak |
| --- | --- | --- | --- | --- |
| `deplanbook_cms_home_smoke_py` | 269 / 0 | pass | 1.6 min before collection | success 495 |
| `deplanbook_cms_on_demand_translation_py` | 269 / 0 | pass | 0.1 min | success 1 709 |
| `afasask_production_codex_medium_synthetic_ok` | 43 / 3 | pass | 18.5 min | success 24 after recovery |
| `afasask_demo_codex_fast_ok` | 44 / 3 | pass | 17.6 min | success 24 after recovery |

Every non-pass in the window is one of the six AFASAsk Codex failures analysed
in finding 1; nothing else failed. The raw `status_summary` still returns
`failing_tests=2` with `enabled_tests/disabled_tests=null`; both failing rows are
**disabled** `dft_prod_exam_import_2doc_sla_daily_e2e` rows, so the split is
**enabled failing = 0, disabled failing = 2**. That aggregate remains the known
reporting weakness queued separately and is not quoted bare.

Residue pending claims (`error_kind='pending'`, `started_at_ts IS NULL`) are
unchanged at **24 registry-wide: 20 on enabled tests, 4 on disabled**; the
newest is 9.2 days old and none is counted as a pass. The hotpath outbox holds
**85 entries, all `delivered`** - publisher delivery only, never lane health.

## Hotpath lanes (separate stream)

| Lane | Severity | Fail streak | Last report | Failure class |
| --- | --- | --- | --- | --- |
| `aipc-hotpath-monitor` | critical | 25 | 6.8 h | `RECOMMENDATION_API_DEPLOYMENT_REVISION_MISMATCH` |
| `aipc-pedantic-e2e-ui-qa-v2` | critical | 15 | 7.3 h | `RECOMMENDATION_API_DEPLOYMENT_REVISION_MISMATCH` |
| `potaito-hotpath-monitor` | critical | 1 | 6.8 h | `stylesheet_delivery_failure` (new) |
| `afasask-hotpath-monitor` | warning | 14 | 103.5 h | `synthetic_authorization_absent` |
| `deplanbook-play-hotpath-monitor` | warning | 2 | 35.3 h | `incomplete_coverage` |
| `quickchat-ridderkerk-hotpath-monitor` | warning | 1 | 74.7 h | `coverage_initial_rollout_incomplete` |
| `quickchat-walburg-hotpath-monitor` | warning | 1 | 74.7 h | `coverage_initial_rollout_incomplete` |

Eleven further lanes read `info`, several long-stale: `aigenda-calendar`
335.6 h, `aigenda-rules` 335.4 h, `quickchat-rsr` 335.5 h, `autopar` 104.2 h,
`orthoparse` 102.0 h, `quickchat-waddinxveen` 68.1 h, `dft-frontend` 56.4 h,
`pitchai-net` 36.8 h, `deplanbook-cms` 7.4 h, `cisnl` 7.4 h, `apologetica-cms`
4.1 h. Registry totals: 18 lane-state rows, 227 reports. There is no
`monitoring-hotpath-synthetic` lane-state row in this registry.

## Containers, proxy, TLS, DNS, registry and ACME

- Containers: 281 total, 156 running; the only restarting container is
  `meilisync-learning-goals-custom-staging` (finding 3). The six
  `service-monitoring` containers are up on the current image with
  `RestartCount=0`, and the `registry` container has `RestartCount=0`. Several
  `autopar-batch-*-crashloop-*` fixtures from 2026-10-01 are stopped with
  22/12/9 historical restarts - test artifacts, not running workloads. No
  `aipc-*` or `ai_price_crawler-*` containers exist on `pitchai-main`.
- nginx: `nginx -t` successful; two long-standing conflicting-server-name
  warnings. 24 h error log holds **416 `connect() failed`** (down from 2 752
  yesterday): `127.0.0.1:8420` 124, `127.0.0.1:3200` 122, plus static-asset
  fetches. Ports 3200 and 8420 still have no listener (the 2026-05-18 dead
  routes, unchanged ownership); 8081 and 3130 do listen. One
  `upstream prematurely closed connection` (deplanbook.com `/static/imgs/20.svg`,
  03:57Z, transient); zero `no live upstreams` and zero
  `upstream sent too big header`. No emerg/alert/crit entries in the 24 h nginx
  journal; SkyBuyFly produced no nginx error lines.
- TLS: the `tls` signal retains 3 failures per cycle (`fail_streak=636`),
  unchanged in shape. Live: `registry.pitchai.net:5000` still times out from the
  monitor container (8.0 s) while the same TLS connect and
  `docker manifest inspect` succeed from the host, so the registry is up and the
  monitor's network path to 37.27.67.52:5000 is filtered. `jeff-dispatch.pitchai.net`
  still resolves to 94.130.17.246 and is unreachable.
- Certificates: 45 certbot lineages, all valid, earliest expiry 2026-11-06
  (about 33 days), no `afasask.gzb.nl-0001` duplicate, and no
  `n8n.pitchai.net` runtime, routing or certbot reappearance.
- Registry TLS: served certificate `CN=registry.pitchai.net`, valid 2026-09-21 to
  2026-12-20, and `docker manifest inspect .../pitchai/codex-runner:latest`
  succeeds.
- ACME: `staging.formatief-toetsen.pitchai.net` serves
  `/.well-known/acme-challenge/...` as a webroot **404 with no redirect** on both
  HTTP and HTTPS, so the 2026-05-13 vhost patch still holds.
- DNS: 88 cycles, `fail_streak=0`. Public `skybuyfly.pitchai.net` still resolves
  to `157.180.101.33` (recorded, not acted on).
- SkyBuyFly public path: pinned probe to `37.27.67.52` returns **200 in 0.196 s**
  and the certificate on that address is valid 2026-09-29 to 2026-12-28
  (`CN=skybuyfly.pitchai.net`). PostgreSQL remains assigned to `65.109.70.111`.
- Monitoring endpoint: `https://monitoring.pitchai.net/health` returns
  `{"ok":true}`.

## Dedicated AIPC host `aipc-fsn1-01` (`5.9.42.254`)

- Reachability: ICMP 2/2, 0 % loss, 34.6 ms average; TCP/22 open; SSH works from
  this review host. From `pitchai-main`, root/ubuntu/debian all return
  `Permission denied (publickey)` - recorded as a capability gap, not as
  evidence of health.
- Host: uptime 8 days 22:33, load 0.26/0.75/1.13 on 12 CPUs, memory 19 GiB of
  125 GiB used (106 GiB available), swap 2.0 MiB of 16 GiB. `/dev/md2`
  587 GB of 921 GB = **68 %** (288 GB free), `/boot` 23 %, cold tier
  `/srv/aipc-cold` 3 %, inodes 6 %. Journal 2.0 GB - no log-growth risk.
  Docker: images 55.2 GB (23.33 GB reclaimable), containers 78.6 MB, volumes
  0 B, build cache 0 B.
- Containers: five running and healthy with `restarts=0`
  (`aipc-shadow-stable`, `aipc-shadow-primary`, `aipc-pgbouncer`,
  `aipc-meilisearch`, `aipc-qdrant`), ten `*-staged` containers in `created`
  state awaiting activation. No AIPC restart loop.
- Failed services: `aipc-host-audit.service` (2026-10-04T03:03:38Z, reasons
  above) and `aipc-docker-maintenance.service` (quarantine refusal).
- Isolated GitHub runner: `aipc-ci-runner-pool-vm.service` is
  `active/running` with `NRestarts=0`, `MemoryCurrent` 3.27 GB against
  `MemoryHigh` 30.06 GB / `MemoryMax` 38.65 GB and 7 626 s CPU time, inside an
  active `aipc-runners.slice`. With 12 CPUs, 106 GiB free memory and a 68 % RAID
  there is ample capacity: **availability and resource suitability are good; the
  blocker is the audit contract, not resources.**
- Coordination: server-ops is required for the audit failures, the runner/key
  contract and the cold-tier quarantine. No privileged, invasive or deep check
  was attempted, and no cutover or production mutation was made.

## Coordination, fixes and mutations

- One requester-private Telegram to Seth van der Bijl (Boss), requester
  `seth-ori`, message class `status`, route kind private, no route override and
  no broad copy; receipt verified by the typed helper (see the PM changelog for
  the receipt reference and message digest).
- No other outgoing message was sent: no email, WhatsApp, client, vendor, group,
  public, payment, order or legal message, and no monitor-container credentials
  were used for delivery.
- Fixes applied: none. None was warranted by the cautious-fix list: all
  certificates are valid, the monitor state is fresh, no monitored container is
  stale or hung, and every finding needs an owning project or server-ops.
- Deliberately not done: no Docker prune or image/volume deletion, no log or
  journal truncation, no `meilisync` restart, no memory or disk reclamation, no
  AIPC remediation, no E2E test activation/pause/retirement, and no DNS,
  certificate, database-routing, public-traffic or production-runtime change.

## Evidence window and deliverable

- Collection 2026-10-04T03:02-03:10Z (05:02-05:10 CEST); evidence window
  2026-10-03T03:00Z to 2026-10-04T03:00Z.
- `service-monitoring` `/data/state.json`: version 6, `updated_at`
  2026-10-04T03:00:23Z, `state_write_fail_streak=0`, cycle 141-155 s; dashboard
  freshness fresh (60 s interval, 180 s stale threshold).
- Dashboard 24 h: availability 88.22 % across 53 661 samples, 13 problem events
  / 10 recoveries plus contract and proxy events; `service_health` 78 healthy /
  15 down of 93 with 8 alertable.
- PM task: `Daily monitoring review 2026-10-04`
  (`376a6dc1-395d-4446-82f2-ada20a3e1aae`, project
  `Repo: pitchai-monitoring`), tracked by the current Codex/self-review agent.
- Repeating reminder instructions were not changed, so no stored `prompt.md`
  update was required.
