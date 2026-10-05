# Daily monitoring review: 2026-10-05

## Decision

The monitor itself is healthy, all seven enabled monitor domains are up, and
all four schedulable external E2E tests are green. The day is **not** all
clear. Six patterns were escalated in one requester-private Telegram to Seth
van der Bijl:

1. **Recurrence: both AFASAsk Codex lanes failed again - 19 non-passes in the
   window.** `afasask_production_codex_medium_synthetic_ok` failed 11 times and
   `afasask_demo_codex_fast_ok` 8 times, interleaved in an hourly
   double-failure block from 2026-10-04T03:46Z to 07:49Z (8 consecutive
   failures per lane) plus three isolated production failures later
   (14:03Z, 22:20Z and 2026-10-05T02:00:58Z). `failure.png` on both lanes shows
   the real product failure - `Mislukt` / "Het is niet gelukt om Codex-modus te
   voltooien" with the canary prompt unanswered - and both `run.log` files say
   `browser_infra_error=false`. Both lanes have recovered (production success
   streak 1 since 02:35:05Z, demo 37 since 2026-10-04T08:11Z), which is the
   same recover-then-recur shape as the 2026-10-03/04 incident: the pattern,
   not the current snapshot, is the risk.
2. **`pitchai-main` memory, disk and registry-reclaim pressure worsened**
   (carried from 2026-10-04): memory 88.77 % (7.4 GB available), swap pinned at
   100 % (188 KiB free of 31 GiB), `/dev/md2` 94 % with 110 GB free (was 93 % /
   125 GB), and Docker still holds **301.7 GB reclaimable** of 377.1 GB of
   images while the three cleanup units (`registry-cleanup.service`,
   `pitchai-production-builder-cache-cleanup.service`,
   `pitchai-potai-staging-release-cleanup.service`) fail again on every run.
3. **`meilisync-learning-goals-custom-staging` restart loop** 3 803 -> **5 189**
   (Restarting, exit 137 roughly every 62 s, `OOMKilled=false`), still not
   matched by the monitor's container patterns.
4. **Two new critical hotpath lanes**: `quickchat-ridderkerk-hotpath-monitor`
   (fail streak 3, fresh report 2.3 h old) and
   `quickchat-walburg-hotpath-monitor` (fail streak 1, fresh 2.3 h). The
   carried criticals `aipc-hotpath-monitor` (25),
   `aipc-pedantic-e2e-ui-qa-v2` (15) and `potaito-hotpath-monitor` (1) have not
   reported for 30-31 h, so their severity is stale evidence.
5. **`aigenda-rules.demos.pitchai.net` is still failing right now** - 344/573
   (60.03 %) with a 503 on the latest sample and repeated two-failure flaps.
   `whatsapp.pitchai.net` (361/573, 63.0 %) and
   `salesengine.demos.pitchai.net` (323/573, 56.4 %) recovered inside the
   window and both answered 200 on their latest sample.
6. **Dedicated host `aipc-fsn1-01` audits still fail** (runner contract,
   installed source, deploy key policy plus a byte mismatch on
   `/usr/local/sbin/aipc-deploy-ssh-dispatch`; docker-maintenance quarantine
   refusal), and `pitchai-main`'s `aipc-hel1-canary-transport-audit.service`
   stays red on a strict `{"status":"ok"}` contract. Both need server-ops, not
   the monitoring lane.

Everything else in the core set is green: state fresh (version 6, `updated_at`
2026-10-05T03:05:04Z, 32 s old when read, `state_write_fail_streak=0`), all
seven enabled monitor domains up (`skybuyfly` 571/573 after two null captures),
the four schedulable E2E tests green, the monitored containers up with zero
restarts, `nginx -t` passing, ACME webroot routing intact, and all 45 certbot
lineages valid with earliest expiry 2026-11-06 (about 32 days).

No fix, reclamation, cutover or production mutation was performed by this lane.
Collection ran 2026-10-05T03:00-03:10Z (05:00-05:10 CEST); the evidence window
is 2026-10-04T03:00Z to 2026-10-05T03:00Z.

## Enabled monitor domains (24 h window, 573 samples each)

| Domain | Samples | OK | HTTP p95 | Browser p95 | Last | Note |
| --- | --- | --- | --- | --- | --- | --- |
| `autopar.pitchai.net` | 573 | 573 (100 %) | 74.0 ms | 13 198 ms | 200 | one tolerated 502 code, still effective OK |
| `afasask.gzb.nl` | 573 | 573 (100 %) | 65.7 ms | 14 696 ms | 200 | contract + synthetic OK |
| `skybuyfly.pitchai.net` | 573 | 571 (99.65 %) | 192.1 ms | 18 302 ms | 200 | two null captures, no 5xx |
| `deplanbook.com` | 573 | 573 (100 %) | 11.1 ms | 12 700 ms | 200 | - |
| `cms.deplanbook.com` | 573 | 573 (100 %) | 232.4 ms | 8 207 ms | 200 | E2E-covered, all pass |
| `dpb.pitchai.net` | 573 | 573 (100 %) | 68.4 ms | 17 096 ms | 200 | - |
| `hetcis.nl` | 573 | 573 (100 %) | 75.0 ms | 17 992 ms | 200 | - |

`afasask.pitchai.net` (disabled/skipped as a monitor target) was also 573/573.
`stable.skybuyfly.pitchai.net` was 570/573 (99.48 %, three 502 codes).

Aggregate across every domain with samples in the window: **53 289 samples,
46 863 OK = 87.94 %** (yesterday 88.22 %), with 15 domains having at least one
failure: **10 at 0 %**, all expected/policy routes (`registry`,
`agentcloud`, `dashboards`, `support`, `cursussen`, the `jeff-*` trio and its
two `.nip.io` aliases), the three live failures above, and the two skybuyfly
sample sets. The dashboard's own rolling day agrees: 53 382 observations,
46 943 successful, **87.94 %**, status `attention`, 14 problem events and
16 recoveries.

## Finding 1 - AFASAsk Codex canaries failed again (escalated)

Both enabled Codex-path tests run on a 1 800 s cadence and both failed in the
same hourly block, then the production lane kept failing intermittently:

| Lane | Runs (pass/fail) | Failures (UTC) | Error | Current |
| --- | --- | --- | --- | --- |
| `afasask_production_codex_medium_synthetic_ok` | 34 / 11 | 03:46, 04:21, 04:55, 05:30, 06:05, 06:40, 07:14, 07:49, 14:03, 22:20, 02:00:58 | `TimeoutError: Page.wait_for_function: Timeout 240000ms exceeded.` | success streak 1 since 02:35:05Z |
| `afasask_demo_codex_fast_ok` | 38 / 8 | 03:50, 04:25, 04:59, 05:34, 06:04, 06:35, 07:06, 07:36 | `AssertionError: afasask_demo_codex_canary_failed_marker: mislukt` | success streak 37 since 08:11Z |

Artifacts read for the newest failure on each lane
(`ebeac16d-...` production 02:00:58Z, `ce4e025a-...` demo 07:36:47Z):
`browser_infra_error=false` on both, and both screenshots show the live UI's
Codex-mode failure block - the production screenshot renders the
`Mislukt`/"Codex-modus" state that the lane's selector cannot see inside
`article[data-role="assistant"]`, which is why the production lane times out
for 240 s instead of asserting in seconds. This is the same product path that
failed on 2026-10-03 and was escalated on 2026-10-04, so the fix is not holding;
the failure block ran for at least four hours before the lanes recovered on
their own.

## Finding 2 - `pitchai-main` memory and disk pressure (escalated)

| Metric | 2026-10-04 | 2026-10-05 | Change |
| --- | --- | --- | --- |
| Memory used | 85-86 % | **88.77 %** (available 7.4 GB) | +3 points |
| Swap | 100 % (32 KiB free) | 100 % (**188 KiB free**) | pinned |
| Disk `/dev/md2` (`df`) | 93 % / 125 GB free | **94 % / 110 GB free** | -15 GB free |
| Worst disk (monitor) | 88.78 % | 88.59 % (path-scoped) | flat |
| Docker images | 367.3 GB (291.3 GB reclaimable) | **377.1 GB (301.7 GB reclaimable, 79 %)** | +9.8 GB |
| `host_health` violations | 3 per cycle | 3 per cycle (mem, swap, disk) | unchanged |

CPU 45.3 % and load 19.3-20.7 on 32 CPUs (0.60-0.66 per CPU) are unchanged, so
this remains memory and disk, not compute. Journals take 3.9 GB, build cache
33.08 GB, local volumes 128.2 GB (27.4 GB reclaimable). The three cleanup units
that would bound this are still failing every run (exit 1 / exit 22 / exit 1).
No deletion, prune or truncation was attempted.

## Finding 3 - `meilisync-learning-goals-custom-staging` restart loop (escalated)

`RestartCount` 3 803 -> **5 189**, status `restarting`, `OOMKilled=false`,
`unless-stopped`, no memory limit. The name is still not matched by the
monitor's container patterns, so `container_health` keeps reporting a single
unrelated issue (the retired `dft-worker` fixture, `Exited (0)`, fail streak
9 282) while the real loop stays invisible to the monitor.

## Finding 4 - hotpath lanes (separate stream, escalated)

| Lane | Severity | Fail streak | Last report age | Failure class |
| --- | --- | --- | --- | --- |
| `aipc-hotpath-monitor` | critical | 25 | 30.8 h (stale) | `RECOMMENDATION_API_DEPLOYMENT_REVISION_MISMATCH` |
| `aipc-pedantic-e2e-ui-qa-v2` | critical | 15 | 31.3 h (stale) | `RECOMMENDATION_API_DEPLOYMENT_REVISION_MISMATCH` |
| `potaito-hotpath-monitor` | critical | 1 | 30.8 h (stale) | `stylesheet_delivery_failure` |
| `quickchat-ridderkerk-hotpath-monitor` | critical | 3 | 2.3 h (fresh) | `answer_incremental_stream_not_observed` |
| `quickchat-walburg-hotpath-monitor` | critical | 1 | 2.3 h (fresh) | `widget_stylesheet_network_error` |
| `afasask-hotpath-monitor` | warning | 14 | 127.5 h (stale) | `synthetic_authorization_absent` |
| `deplanbook-play-hotpath-monitor` | warning | 2 | 59.3 h (stale) | `incomplete_coverage` |

The two QuickChat lanes are new critical reports on real client embeds:
Ridderkerk failed stage `source_contact:streaming` (one completed answer, but
only one 1053-character DOM sample with no incremental growth; contact/overlay
receipt verified, retainer and layout not reached) and Walburg failed stage
`socket_readiness` (`my.css`/`styles.css` `ERR_NETWORK_CHANGED`, unstyled
widget, zero question POSTs; the lane explicitly avoids inferring an
application regression and asks the release owner to inspect run evidence).
Eleven further lanes read `info`, several long-stale: `aigenda-calendar`
359.6 h, `aigenda-rules` 359.4 h, `quickchat-rsr` 359.5 h, `autopar` 128.2 h,
`orthoparse` 125.9 h, `dft-frontend` 80.4 h, `pitchai-net` 60.8 h,
`quickchat-waddinxveen` 3.9 h, plus `cisnl`, `deplanbook-cms`,
`apologetica-cms` fresh. Registry totals: 18 lane-state rows. The hotpath
outbox holds **87 entries, all `delivered`** - publisher delivery only, never
lane health. There is still no `monitoring-hotpath-synthetic` lane-state row;
its only report is the intentional 2026-08-27 synthetic FAIL proof.

## Finding 5 - live domain failures (escalated)

| Domain | 24 h OK | Latest sample | Behaviour |
| --- | --- | --- | --- |
| `aigenda-rules.demos.pitchai.net` | 344/573 (60.03 %) | 503 | repeated 2-failure flaps, `domain_down`/`domain_up` pairs through the window |
| `whatsapp.pitchai.net` | 361/573 (63.0 %) | 200 | recovered mid-window (was 66.4 % yesterday) |
| `salesengine.demos.pitchai.net` | 323/573 (56.4 %) | 200 | recovered mid-window (was 67.2 % yesterday) |

All three are alertable `critical` routes; dashboard state carries
`aigenda-rules` as the only remaining live alertable domain failure beyond the
five standing names. Their 5xx come from the application behind nginx (no
upstream error-log lines of their own), so this stays an owning-project
signal, not a proxy fault.

## Finding 6 - `aipc-fsn1-01` and the HEL1 transport audit (escalated, server-ops)

- `aipc-fsn1-01` `aipc-host-audit.service` failed again at 2026-10-05T03:02:03Z
  with `ci-runner-contract-invalid`, `ci-runner-installed-source-invalid` and
  `deploy-authorized-key-policy-invalid`, plus
  `installed byte mismatch: /usr/local/sbin/aipc-deploy-ssh-dispatch`.
  `aipc-docker-maintenance.service` still refuses while the retained HDD cold
  tier is quarantined.
- `pitchai-main` `aipc-hel1-canary-transport-audit.service` remains red (first
  failure 2026-09-30 06:15 CEST) because the audit demands exactly
  `{"status":"ok"}` while the live endpoint returns
  `{"status":"ok","service":"skybuyfly-quickchat"}`; live probes return 200, so
  this is a broken verification contract, not an outage.
- Both AIPC hotpath lanes stay `critical` with the revision-mismatch class
  (deployed `44b6e365...` vs expected source `36ddbfc2...` / `56df3d12...`),
  but neither has reported for about 31 h, so only a fresh report can speak to
  the current deployment.

## Signals (24 h)

| Signal | Samples | Bad | Latest | Notes |
| --- | --- | --- | --- | --- |
| `browser` | 573 | 0 | ok | `degraded_active=false`, 0 launch failures |
| `dns` | 89 | 0 | ok | `fail_streak=0`, 93+ domains resolved |
| `proxy` | 573 | 0 | ok | `success_streak=396`, `pct_502_504=0.0`, 0 upstream error events (368 access samples) |
| `tls` | 23 | 23 | fail | `fail_streak=659`, 3 retained failures per cycle |
| `host_health` | 573 | 573 | fail | mem 88.77 %, swap 99.999 %, cpu 45.3 %, load1/cpu 0.603, worst disk 88.59 %, 3 violations |
| `performance` | 573 | 573 | fail | 44 slow domains (standing) |
| `slo` | 573 | 573 | fail | 6 SLO violations per cycle |
| `red` | 573 | 573 | fail | 47 RED violations per cycle |
| `container_health` | 573 | 573 | fail | 1 issue (retired `dft-worker`), fail streak 9 282 |
| `meta` | 573 | 573 | fail | `reason_count=1` (standing), cycle 151.9 s, `state_write_fail_streak=0` |

`api_contract`: all targets OK except the two standing ones
(`dispatch.pitchai.net` fail streak 9 462, `codexusage.pitchai.net` 350).
`synthetic`: all nine probes OK. `web_vitals`: standing informational streaks
only (`agents` 81, `aigenda-monitor`/`aigenda` 278, `breakglass` 307, plus the
`jeff-*` and registry names) - recorded, not an outage. Events in the window:
9 `domain_down`, 11 `domain_up`, 3+3 `api_contract_degraded/recovered`, 2+2
`web_vitals_degraded/recovered` (including `unimixbrasil.com.br` LCP > 4500 ms),
0 `proxy_*`; the tail is dominated by the `aigenda-rules` flaps.

## Standing down and excluded set

The dashboard reports `service_health` **93 enabled domains: 80 healthy, 13
down**, of which **7 are expected/policy-down** and **6 alertable**
(yesterday 8 alertable - the WhatsApp and SalesEngine recoveries dropped two).
The five standing alertable names remain `dispatch.pitchai.net` (every HTTP
sample OK, contract red 9 462), `codexusage.pitchai.net` (same shape, 350) and
the `jeff-codex-voice` / `jeff-dispatch` / `jeff-work-inbox` trio
(`ConnectError` to the dead 94.130.17.246). Expected/policy-down:
`registry.pitchai.net` (monitor-container `ConnectTimeout` - the registry is up,
see TLS section), `agentcloud.pitchai.net`, `dashboards.pitchai.net`,
`support.pitchai.net` (502 to dead localhost ports), `cursussen.pitchai.net`
(404) and the two `.nip.io` aliases of the `jeff-*` hosts.

Group rollups: `operations` attention (2 alertable), `learning-demos` attention
(1 alertable + registry expected), `jeff-internal` attention (3 alertable + 2
expected), `infrastructure` expected (4 expected); corporate, platform-apps,
afasask, autopar, dft and potaito groups are healthy.

## External E2E (scoped)

Registry scope first: **36 rows = 4 schedulable recurring tests, 3 temporarily
paused, 29 disabled.**

- Schedulable recurring: `deplanbook_cms_home_smoke_py`,
  `deplanbook_cms_on_demand_translation_py`, `afasask_demo_codex_fast_ok`,
  `afasask_production_codex_medium_synthetic_ok`.
- Temporarily paused: the three `zz_disabled_temp_*` probes (`enabled=1`,
  `disabled_until_ts=1893456000`); their February history is not current
  evidence.
- Disabled: 29 rows, including the retired `afasask_gzb_codex_medium_ok_daily`
  (`enabled=0`, never quoted as current evidence).

Runs in the 24 h window: **623 total, 604 pass, 19 fail** - every non-pass is
one of the AFASAsk Codex failures analysed in finding 1.

| Test | Runs (pass/fail) | Latest | Streak |
| --- | --- | --- | --- |
| `deplanbook_cms_home_smoke_py` | 266 / 0 | pass 0.2 min before read | success 761 |
| `deplanbook_cms_on_demand_translation_py` | 266 / 0 | pass 0.3 min | success 1 974 |
| `afasask_production_codex_medium_synthetic_ok` | 34 / 11 | pass 27 min | success 1 |
| `afasask_demo_codex_fast_ok` | 38 / 8 | pass 26 min | success 37 |

All four schedulable tests are currently `effective_ok=1` with `fail_streak=0`
- the active `failing_tests` split is **0 active / 0 paused / 2 disabled**
(both disabled rows are `dft_prod_exam_import_2doc_sla_daily_e2e`, auto-disabled
for a disallowed base URL); 15 disabled rows carry a historical non-pass
`last_status`, which is out-of-service history, not current failure. The raw
`status_summary` hardcoded `ok: True` weakness still exists, so the split above
was computed directly. Residue pending claims (`error_kind='pending'`,
`started_at_ts IS NULL`) remain **24 registry-wide**; the newest is 244.9 h
(10.2 days) old and none is counted as a pass.

## Containers, proxy, TLS, DNS, registry and ACME

- Containers: 300 total, 156 running, none unhealthy. The monitored six are up
  on the current image (`service-monitoring`, `e2e-registry`, `e2e-runner`
  started 2026-10-03T02:52Z, `RestartCount=0`). `registry` (`registry:2`) is
  running since 2026-10-05T02:30:14Z with `RestartCount=0` - an in-window
  restart that was not a crash; TLS and manifest probes succeed after it. The
  only restarting container is `meilisync-learning-goals-custom-staging`
  (finding 3); the `autopar-batch-*-crashloop-*` fixtures from 2026-10-01 are
  stopped test artifacts. No `aipc-*` or `ai_price_crawler-*` containers exist
  on `pitchai-main`. Docker df: images 377.1 GB (301.7 GB reclaimable),
  containers 13.18 GB, volumes 128.2 GB, build cache 33.08 GB.
- `systemctl --failed` lists 17 units: the events-bus family, the three cleanup
  units above, `aipc-hel1-canary-transport-audit.service`,
  `lxd-installer@0-...`, two `run-u*` transients and `user@1002`.
- nginx: `nginx -t` successful; **454 `connect() failed`** in the window
  (yesterday 416), dominated by the two dead-but-expected routes
  (`support.pitchai.net` -> `127.0.0.1:8420` 128, `dashboards.pitchai.net` ->
  `127.0.0.1:3200` 123) plus WordPress-scanner probing; ports 3200/8420 still
  have no listener (unchanged ownership), 8081/3130 do. One
  `upstream prematurely closed connection` on `deplanbook.com`
  `/static/styles.css` at 02:43:47Z (transient static fetch). Zero
  `no live upstreams`, zero `too big header`, zero upstream timeouts, zero
  `skybuyfly`/`potaito` error lines, and no emerg/alert/crit entries in the
  nginx journal.
- TLS: the `tls` signal retains its 3 failures per cycle (`fail_streak=659`),
  unchanged in shape. `registry.pitchai.net:5000` serves its current
  certificate (`CN=registry.pitchai.net`, valid 2026-09-21 to 2026-12-20) and
  `docker manifest inspect .../pitchai/codex-runner:latest` succeeds from the
  host; the monitor container's own timeout to that address is a known
  path/policy exclusion, not registry downtime.
- Certificates: 45 certbot lineages, all valid; earliest expiry 2026-11-06
  (about 32 days), 11 lineages inside 45 days. No `afasask.gzb.nl-0001`
  duplicate, and no `n8n.pitchai.net` site, container, unit or certbot
  reappearance.
- ACME: `staging.formatief-toetsen.pitchai.net` serves
  `/.well-known/acme-challenge/...` as a webroot **404 with no redirect** on
  both HTTP and HTTPS, so the 2026-05-13 vhost patch still holds.
- DNS: 89 cycles, `fail_streak=0`. Public `skybuyfly.pitchai.net` still
  resolves to `157.180.101.33` (recorded, not acted on). SkyBuyFly pinned probe
  to `37.27.67.52` returns **200 in 0.167 s**, and the certificate on that
  address is valid 2026-09-29 to 2026-12-28 (`CN=skybuyfly.pitchai.net`).
  PostgreSQL remains assigned to `65.109.70.111`; no DNS, certificate,
  database-routing, public-traffic or production-runtime change was made.
- Monitoring endpoint: `https://monitoring.pitchai.net/health` returns
  `{"ok":true}`.

## Dedicated AIPC host `aipc-fsn1-01` (`5.9.42.254`)

- Reachability: ICMP 3/3, 0 % loss, 34.5 ms average; TCP/22 open; SSH works from
  this review host. From `pitchai-main`, root and ubuntu both return
  `Permission denied (publickey)` - recorded as a capability gap, not as
  evidence of health.
- Host: uptime 9 days 22:32, load 0.35/0.35/0.61 on 12 CPUs, memory 20.1 GB of
  128.7 GB used (108.6 GB available), swap 2 MB of 17.4 GB. `/dev/md2`
  587 GB of 921 GB = **68 %** (288 GB free), `/boot` 23 %, cold tier
  `/srv/aipc-cold` 3 %, inodes 6 %. Journal 2.0 GB - no log-growth risk.
  Docker: images 55.2 GB (23.33 GB reclaimable), containers 78.6 MB, volumes
  and build cache empty.
- Containers: five running and healthy with `restarts=0`
  (`aipc-shadow-stable`, `aipc-shadow-primary`, `aipc-pgbouncer`,
  `aipc-meilisearch`, `aipc-qdrant`), ten `*-staged` containers in `created`
  state awaiting activation. No AIPC restart loop.
- Failed services: `aipc-host-audit.service` and
  `aipc-docker-maintenance.service` (reasons in finding 6).
- Isolated GitHub runner: `aipc-ci-runner-pool-vm.service` is
  `active/running` with `NRestarts=0`, `MemoryCurrent` 3.09 GB against
  `MemoryHigh` 30.06 GB / `MemoryMax` 38.65 GB, inside an active
  `aipc-runners.slice`. There are no `actions.runner.*` units (this is a
  service-first pool). With 12 CPUs, 108 GB free memory and a 68 % RAID there
  is ample capacity: **availability and resource suitability are good; the
  blocker is the audit contract, not resources.**
- Coordination: server-ops is required for the audit failures, the runner/key
  contract and the cold-tier quarantine. No privileged, invasive or deep check
  was attempted, and no cutover or production mutation was made.

## Coordination, fixes and mutations

- One requester-private Telegram to Seth van der Bijl (Boss), requester
  `seth-ori`, message class `status`, route kind private, no route override and
  no broad copy; the receipt is verified by the typed helper and recorded in
  the PM changelog.
- No other outgoing message was sent: no email, WhatsApp, client, vendor, group,
  public, payment, order or legal message, and no monitor-container credentials
  were used for delivery.
- Fixes applied: none. None was warranted by the cautious-fix list: all
  certificates are valid, the monitor state is fresh, `browser` is green, no
  monitored container is stale or hung, and every finding needs an owning
  project or server-ops.
- Deliberately not done: no Docker prune or image/volume deletion, no log or
  journal truncation, no `meilisync` restart, no memory or disk reclamation, no
  AIPC remediation, no E2E test activation/pause/retirement, and no DNS,
  certificate, database-routing, public-traffic or production-runtime change.

## Evidence window and deliverable

- Collection 2026-10-05T03:00-03:10Z (05:00-05:10 CEST); evidence window
  2026-10-04T03:00Z to 2026-10-05T03:00Z.
- `service-monitoring` `/data/state.json`: version 6,
  `updated_at` 2026-10-05T03:05:04Z, 32 s old at read, 60 s interval,
  180 s stale threshold, `state_write_fail_streak=0`, cycle 151.9 s; dashboard
  freshness reports `fresh`.
- Dashboard 24 h: availability 87.94 % across 53 382 observations, 14 problem
  events / 16 recoveries; `service_health` 80 healthy / 13 down of 93 with
  6 alertable.
- PM task: `Daily monitoring review 2026-10-05`
  (`d67680f3-8976-4b6c-949a-4f3652710b2b`, project
  `c3d9154a-25bc-4630-8b42-322e237530c8` = `Repo: pitchai-monitoring`), tracked
  by the current Codex/self-review agent.
- Repeating reminder instructions were not changed, so no stored `prompt.md`
  update was required.
