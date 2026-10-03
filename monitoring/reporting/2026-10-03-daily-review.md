# Daily monitoring review: 2026-10-03

## Decision

The monitor itself is healthy and no monitored product domain is down for
users, but the day is **not** all clear. Four patterns were escalated in one
requester-private Telegram to Seth van der Bijl:

1. **`pitchai-main` swap is still pinned at 100 %** (31 GiB of 31 GiB, 8 KiB
   free) and all three cleanup units still fail on every run. Disk pressure
   eased versus yesterday: `/dev/md2` is at **91 % in `df` terms (154 GB free)**
   against 95 % (104 GB free) yesterday, and the monitor's own worst-disk
   reading fell from 89.25 % to **86.03 %**.
2. **`meilisync-learning-goals-custom-staging` is still in a restart loop and
   got worse** - `RestartCount` 1 032 -> **2 422**, exit 137 roughly every
   62 seconds, no kernel OOM entry, and the container name is still not matched
   by the monitor's container patterns, so the container signal does not cover
   it.
3. **`aipc-fsn1-01` still fails its own host audit** with
   `ci-runner-contract-invalid`, `ci-runner-installed-source-invalid` and
   `deploy-authorized-key-policy-invalid`, plus an installed byte mismatch on
   `/usr/local/sbin/aipc-deploy-ssh-dispatch`, and its Docker maintenance still
   refuses to run while the retained HDD cold tier is quarantined.
4. **New: `pitchai-main` `aipc-hel1-canary-transport-audit.service` has been
   red for about nine days.** The timer fires every ~5 minutes and the run
   fails with `quickchat-health-contract-invalid` (800 times in the last seven
   days, first at 2026-09-30 06:15 CEST, after 1 105 `client-service-restarted`
   failures since 2026-09-24 04:11 CEST). The cause is a strict contract check
   that requires exactly `{"status":"ok"}` while the live endpoint returns
   `{"status":"ok","service":"skybuyfly-quickchat"}` on both the loopback and
   the public route. Live public probes return 200, so this is a broken
   verification contract rather than a visible outage - but the automated
   proof of the HEL1 production transport has been silently failing for over a
   week.

Everything else in the core set is green: the monitor state is fresh
(`updated_at` 2026-10-03T03:13:26Z, version 6, 60 s interval, stale threshold
180 s, `state_write_fail_streak=0`), all seven enabled monitor domains were
100 % available except `skybuyfly.pitchai.net` (96.68 %, 15 null-code samples
plus 4 x 502, all recovered), zero enabled external E2E tests are failing, both
AFASAsk Codex canaries are green (streaks 86 and 81), and every certificate is
valid with at least 34.5 days left.

No fix, reclamation, cutover or production mutation was performed by this
lane. Collection ran 2026-10-03T03:06-03:25Z (05:06-05:25 CEST); the evidence
window is 2026-10-02T03:05Z to 2026-10-03T03:25Z.

## Enabled monitor domains (24 h window, 573 samples each)

| Domain | Samples | OK | HTTP p95 | Browser p95 | Slow samples (http / browser) | Last |
| --- | --- | --- | --- | --- | --- | --- |
| `autopar.pitchai.net` | 573 | 573 (100 %) | 76.1 ms | 14 204 ms | 0 / 572 | 200 |
| `afasask.gzb.nl` | 573 | 573 (100 %) | 54.3 ms | 17 300 ms | 0 / 573 | 200 |
| `skybuyfly.pitchai.net` | 573 | 554 (96.68 %) | 328.9 ms | 17 213 ms | 18 / 554 | 200 |
| `deplanbook.com` | 573 | 573 (100 %) | 11.9 ms | 14 299 ms | 0 / 573 | 200 |
| `cms.deplanbook.com` | 573 | 573 (100 %) | 234.9 ms | 10 400 ms | 0 / 573 | 200 |
| `dpb.pitchai.net` | 573 | 573 (100 %) | 62.1 ms | 15 699 ms | 0 / 573 | 200 |
| `hetcis.nl` | 573 | 573 (100 %) | 73.7 ms | 19 909 ms | 0 / 573 | 200 |

`afasask.pitchai.net` (disabled/skipped as a monitor target) was also 573/573
with HTTP p95 66 ms. `skybuyfly.pitchai.net` and `stable.skybuyfly.pitchai.net`
each had 19 non-OK samples in the window (15 with a null status code plus four
502s) and both recovered; the 03:24Z recovery is visible as a `domain_up`
event. `montrachet-demo.pitchai.net` (97.21 %) and
`aigenda-rules.demos.pitchai.net` (96.86 %) each had a 500/503 blip that
recovered inside the window.

Domain streaks reset on transient primary failures even when effective
availability stays 100 %: `autopar.pitchai.net` is at 250, `cms.deplanbook.com`
at 101 (consistent with the brief CMS upstream refusals below) and
`skybuyfly.pitchai.net` at 46.

Live probes agree: HTTP checks answer 200/302/307 in well under 0.2 s.

## Standing down and excluded set

The dashboard reports `service_health` of **93 enabled domains: 81 healthy, 12
down, of which 7 are expected/policy-down and 5 are alertable**
(`alertable_down=5`). All five are documented standing conditions:

- `dispatch.pitchai.net` - 572/572 HTTP samples OK (success streak 9 054) while
  its `api_contract` check stays red at `fail_streak=8 996`; recorded since
  2026-09-30 as "public URL answers correctly".
- `codexusage.pitchai.net` - same shape, `api_contract fail_streak=53`.
- `jeff-codex-voice.pitchai.net`, `jeff-dispatch.pitchai.net`,
  `jeff-work-inbox.pitchai.net` - `ConnectError`/`ConnectTimeout` to the dead
  94.130.17.246 host, `fail_streak=16 562` (11.5 days), part of the five-name
  `jeff-*` set documented in previous reports.

Expected/policy-down (dashboard-only, no paging): `registry.pitchai.net`
(`ConnectTimeout` after 15 s from the monitor - see TLS section),
`agentcloud.pitchai.net` (502), `dashboards.pitchai.net` (502),
`support.pitchai.net` (502), `cursussen.pitchai.net` (404) and the two
`.nip.io` bootstrap aliases of the `jeff-*` hosts.

## Finding 1 - `pitchai-main` swap, memory and failing cleanup units (escalated)

- Swap: **31 GiB of 31 GiB used, 8 KiB free** (`swap_used_percent=100.0` in the
  monitor's host snapshot across the whole window; 20 KiB free at the latest
  sample). Sustained above the ~90 % escalation threshold, not a spike.
- Memory: 43 GiB of 62 GiB used (69.2 %), 19-20 GiB available.
- Disk: `/dev/md2` 1.5 TB of 1.7 TB used = **91 % (`df`) / 86.03 % (monitor,
  total-bytes basis)**, 154 GB free. Yesterday: 95 % / 89.25 %, 104 GB free, so
  roughly 50 GB was reclaimed in 24 h.
- Docker: images 344 GB (270.5 GB reclaimable), build cache 33.08 GB (20.34 GB
  reclaimable, down from 120.7 GB), volumes 128.2 GB, containers 10.76 GB.
- Cleanup units still failing: `registry-cleanup.service` (03:02 CEST),
  `pitchai-production-builder-cache-cleanup.service` (03:54 CEST),
  `pitchai-potai-staging-release-cleanup.service` (04:55 CEST).
- Other failed units are long-standing
  (`pitchai-breakglass-events-bus.path` 2026-09-23, `lxd-installer@` 2026-08-29,
  `user@1002` 2026-08-26, events-bus helpers, plus the new HEL1 audit below).
- Lane action: none. No reclamation, prune, truncate or deletion was attempted.

## Finding 2 - `meilisync-learning-goals-custom-staging` restart loop (escalated)

- `status=restarting`, `RestartCount=2 422` (yesterday 1 032), exit 137,
  `OOMKilled=false`, restart policy `unless-stopped`, no memory limit; last
  start 2026-10-03T03:11:52Z. 1 390 restarts in 24 h is one per ~62 seconds,
  matching yesterday's measured cadence.
- The name is not covered by `container_health.include_name_patterns`, which
  only matches `^meilisync-formatief-toetsen(?:-staging)?$`, so the monitor's
  container signal cannot see this loop. `docker ps --filter
  status=restarting` returns exactly this one container.
- Lane action: not restarted or edited - the cause is unknown and the container
  writes to Meilisearch, so a blind restart is not safe from this lane.

## Finding 3 - `aipc-fsn1-01` self-audit failures and quarantined cold tier (escalated)

- `aipc-host-audit.service` failed again at 2026-10-03T03:08:13Z with
  `ci-runner-contract-invalid, ci-runner-installed-source-invalid,
  deploy-authorized-key-policy-invalid` and `installed byte mismatch:
  /usr/local/sbin/aipc-deploy-ssh-dispatch`.
- `aipc-docker-maintenance.service` last failed 2026-10-02T03:36:41Z with
  `refusing maintenance while the retained HDD cold tier is quarantined`.
- The host itself is healthy: see the dedicated-host section. Server-ops
  coordination is required for the runner/key contract and the cold tier; no
  privileged or invasive remediation was attempted from this lane.

## Finding 4 - HEL1 production-transport audit red for nine days (escalated)

- Unit: `pitchai-main` `aipc-hel1-canary-transport-audit.service`, triggered by
  `aipc-hel1-canary-transport-audit.timer` every ~5 minutes.
- 800 `quickchat-health-contract-invalid` failures in the last 7 days (first
  2026-09-30 06:15 CEST) and 1 105 `client-service-restarted` failures since the
  unit's first recorded failure at 2026-09-24 04:11 CEST.
- Root cause read from the audit script: the `quickchat` contract requires the
  payload to equal exactly `{"status": "ok"}`; the live endpoint answers
  `{"status":"ok","service":"skybuyfly-quickchat"}` (verified on
  127.0.0.1:13108, on the public HEL1 route and on the pinned 37.27.67.52
  route, all HTTP 200).
- Impact: the audit is the automated proof for the HEL1 transport contract
  (loopback listeners 13108/13120/13121, nginx byte hashes, public health,
  search, product and quickchat contracts). Everything the audit can still
  check is live, but the proof has been red for over a week and the failure
  does not surface in the monitoring signals, so it is escalated instead of
  repaired: the contract belongs to the owning project, and changing the audit
  or the service payload is not a monitoring-lane fix.

## Signals (24 h)

| Signal | Samples | Bad | Latest | Notes |
| --- | --- | --- | --- | --- |
| `browser` | 573 | 0 | ok | `degraded_active=false`, 0 launch failures |
| `dns` | 1/cycle | 0 | ok | `fail_streak=0`, 93 domains resolved |
| `tls` | 4 cycles | 4 | fail | `fail_streak=612`, 3 retained failures per cycle, 6 reproduced live |
| `host_health` | 573 | 573 | fail | swap 100 %, mem 69.2 %, cpu 44.0 %, load1/cpu 0.62, worst disk 86.03 %, 2 violations |
| `performance` | 573 | 573 | fail | 45 slow domains (browser p95 > 4 000 ms) - standing baseline |
| `slo` | 573 | 573 | fail | 7 SLO violations per cycle - standing |
| `red` | 573 | 573 | fail | 48 RED violations per cycle - standing |
| `container_health` | 573 | 573 | fail | `fail_streak=8 134`, 1 issue: retired `dft-worker` `Exited (0)` |
| `proxy` | 573 | ~4 | ok | `success_streak=2`, `pct_502_504=0.0`, 0 upstream events, one cycle with `upstream_issue_count=1`, ~322 access lines/cycle |
| `meta` | 573 | 573 | fail | `reason_count=1` (standing), cycle 146.3 s, `state_write_fail_streak=0` |

`api_contract`: all targets OK except the two standing ones above
(`dispatch.pitchai.net` 8 996, `codexusage.pitchai.net` 53);
`afasask.gzb.nl`, `demo.afasask.pitchai.net`, `autopar.pitchai.net`,
`deplanbook.com`, `dpb.pitchai.net`, `skybuyfly.pitchai.net` and the
`*.sslip.io` helpers all report success streaks of 17-418.
`synthetic`: all nine probes OK (skybuyfly count 5 after its 23:24Z recovery).
`web_vitals`: `unimixbrasil.com.br` is degraded on `lcp_ms>4500`
(`fail_streak=2`, open at the end of the window) - informational, not an
outage.

The `container_health` failure was re-verified from the live config: 59
containers match the patterns and the single issue is
`dft-worker` (`Exited (0) 4 days ago`, `restart_count=0`, exit code 0) - an
exported, non-running container that the include patterns still match. Zero
containers are unhealthy, starting or restarting, so this signal is a standing
false positive, not a production problem.

The `tls` signal retains 3 failures per cycle. A full live sweep of the 93
configured domains reproduces **6**: five `jeff-*` names fail with
`ConnectionRefusedError` to the dead 94.130.17.246 host and
`registry.pitchai.net:5000` times out **from the monitor container only** (the
same TCP connect from the host succeeds in 1.5 ms, `curl -sk .../v2/` returns
401 and `docker manifest inspect` of the Codex runner image succeeds, so the
registry itself is up; the monitor's network path to 37.27.67.52:5000 is
filtered). All 45 certbot lineages are valid; the shortest remaining validity
is 34.5 days (`aardappelprijs.nl`, `akkerbouwprijs.nl`), then 36.5
(`deplanbook.com`, `orthoparse.pitchai.net`) and 37.5
(`cms.deplanbook.com`, `dpb.pitchai.net`).

## External E2E (scoped)

Registry scope first: **36 rows = 4 schedulable recurring tests, 3 temporarily
paused, 29 disabled.**

- Schedulable recurring: `deplanbook_cms_home_smoke_py`,
  `deplanbook_cms_on_demand_translation_py`, `afasask_demo_codex_fast_ok`,
  `afasask_production_codex_medium_synthetic_ok`.
- Temporarily paused: the three `zz_disabled_temp_*` probes
  (`enabled=1`, `disabled_until_ts=1893456000`, reason `temporary probe
  cleanup`); they last ran 2026-02-26 and their historical `pass` is not
  current evidence.
- Disabled: 29 rows, including the retired
  `afasask_gzb_codex_medium_ok_daily` (`enabled=0`, retired 2026-09-03, never
  quoted as current evidence).

Runs in the 24 h window: **634 total, 633 pass, 1 fail.**

| Test | Runs | Result | Streak |
| --- | --- | --- | --- |
| `deplanbook_cms_home_smoke_py` | 271 | 270 pass, 1 fail | success 227 after recovery |
| `deplanbook_cms_on_demand_translation_py` | 269 | 269 pass | 1 442 |
| `afasask_demo_codex_fast_ok` | 47 | 47 pass | 86 |
| `afasask_production_codex_medium_synthetic_ok` | 47 | 47 pass | 81 |

The single non-pass is resolved, not dismissed: at 2026-10-02T07:01:43Z the CMS
smoke test navigated to `https://cms.deplanbook.com/` and received an nginx
**502 Bad Gateway** page (`failure.png` inspected, `browser_infra_error=false`,
`title="502 Bad Gateway"`), which timed out the language-switcher selector. The
nginx error log matches exactly: `connect() failed (111: Connection refused)
while connecting to upstream ... upstream: "http://127.0.0.1:3130/"` at
2026-10-02 09:01:43 +02:00. Two more identical refusals occurred in the window
(13:36Z and 23:02Z) without failing an E2E run, and the sibling
`deplanbook-cms-hotpath-monitor` lane reports success. Classification: a
transient CMS upstream restart, recovered - recorded, and included in the
escalation as context.

The dashboard's own E2E view is `status=healthy`, `enabled=7`,
`passing=7`, `failing=0`, `disabled=29`. The raw `status_summary` still returns
`failing_tests=2` with `enabled_tests/disabled_tests=null`; both failing rows
are **disabled** `dft_prod_exam_import_2doc_sla_daily_e2e` rows, so the split is
**enabled failing = 0, disabled failing = 2**. That aggregate is a known
reporting weakness (queued separately) and is not quoted bare.

Residue pending claims (`error_kind='pending'`, `started_at_ts IS NULL`) are
unchanged at **24 registry-wide: 20 on enabled tests, 4 on disabled**; the
newest is 8.2 days old and none is ever counted as a pass. The hotpath outbox
shows 82 entries, all `delivered` - publisher delivery only, never lane health.

## Hotpath lanes (separate stream)

| Lane | Severity | Fail streak | Last report | Failure class |
| --- | --- | --- | --- | --- |
| `aipc-hotpath-monitor` | critical | 24 | 56.3 h | `image_refresh_trigger_not_observed` |
| `aipc-pedantic-e2e-ui-qa-v2` | critical | 14 | 31.5 h | `RECOMMENDATION_API_DEPLOYMENT_REVISION_MISMATCH` |
| `afasask-hotpath-monitor` | warning | 14 | 79.7 h | `synthetic_authorization_absent` |
| `deplanbook-play-hotpath-monitor` | warning | 2 | 11.5 h | `incomplete_coverage` |
| `quickchat-ridderkerk-hotpath-monitor` | warning | 1 | 50.9 h | `coverage_initial_rollout_incomplete` |
| `quickchat-walburg-hotpath-monitor` | warning | 1 | 50.9 h | `coverage_initial_rollout_incomplete` |
| `monitoring-hotpath-synthetic` | critical | 1 | 868.1 h | intentional synthetic FAIL proof |

Twelve lanes read `info` with `current_success=1`. Several are stale, which
`info` alone hides: `aigenda-calendar` 311.8 h, `aigenda-rules` 311.6 h,
`quickchat-rsr` 311.7 h, `autopar` 80.3 h, `orthoparse` 78.1 h,
`quickchat-waddinxveen` 44.3 h, `dft-frontend` 32.5 h, `deplanbook-cms` 31.7 h,
`apologetica-cms` 29.7 h, `potaito` 29.2 h, `cisnl` 28.9 h,
`pitchai-net` 13.0 h. `aipc-hotpath-monitor` has now been silent for 56.3 h
(yesterday 32.1 h) and remains the stalest critical lane.

## Containers, proxy, TLS, DNS, registry and ACME

- Containers: 262 total, 154 running; the only restarting container is
  `meilisync-learning-goals-custom-staging` (finding 2). No `aipc-*` or
  `ai_price_crawler-*` containers exist on `pitchai-main`.
- Monitor stack: all six containers on image
  `service-monitoring:4f7977b3675b8acf38f4e9aa077fda9b05773f7c`, all started
  2026-10-03T02:52:02Z with `RestartCount=0`; state writes resumed on the normal
  cadence afterwards (freshness confirmed at 03:13:26Z). The `registry`
  container has `RestartCount=0` and has been up since 2026-10-02T02:30:14Z.
- nginx: `nginx -t` successful; three long-standing conflicting-server-name
  warnings (`pitchai.net`, `staging.chat.pitchai.net`,
  `chat-staging.pitchai.net`). No 24 h nginx journal entries with
  emerg/alert/crit, `no live upstreams`, `upstream prematurely closed` or
  `upstream sent too big header` - SkyBuyFly produced **zero** nginx error lines
  in the window.
- nginx error log, 24 h host/reason breakdown: 2 752 `connect() failed` -
  `support.pitchai.net` 1 928 (127.0.0.1:8420), `dashboards.pitchai.net` 821
  (127.0.0.1:3200), `staging.autopar` 42, `orthoparse` 40, `autopar` 31,
  `afasask.gzb.nl` 28, `demo.afasask` 26, `deplanbook` 14 (the three CMS
  refusals), `staging.formatief-toetsen` 9, `autopar-staging-web` 4. Re-probed
  the dead routes directly: ports 3200 and 8420 still have no listener
  (`support` and `dashboards` answer 502 in ~22 ms), 8081 does listen and
  `staging.potaito.pitchai.net` answers 401 as before. These remain the
  2026-05-18 dead-route conditions with no ownership change.
- ACME: `staging.formatief-toetsen.pitchai.net` serves
  `/.well-known/acme-challenge/...` as a webroot **404 with no redirect** on
  both HTTP and HTTPS, so the 2026-05-13 vhost patch still holds.
- Registry TLS: the served certificate on `registry.pitchai.net:5000` is the
  current lineage (`CN=registry.pitchai.net`, valid 2026-09-21 to 2026-12-20)
  and `docker manifest inspect .../pitchai/codex-runner:latest` succeeds.
  `/opt/registry/certs/domain.crt` still holds a stale
  `registry.example.com` placeholder (expired 2026-05-25) but is **not** what
  the registry serves, so auto-dispatch is not affected.
- DNS/TLS for `pitchai-main`: 93 domains resolved, `dns fail_streak=0`; no
  `n8n.pitchai.net` runtime, routing or certbot reappearance; no
  `afasask.gzb.nl-0001` duplicate lineage.
- SkyBuyFly public path: pinned contract probe to `37.27.67.52` returns **200
  in 0.12 s** with `{"status":"healthy","service":"AI Price Crawler API"}`.
  The public DNS answer is still **157.180.101.33** (recorded, not acted on);
  probing that address returns 200 with `x-aipc-origin: hel1-dedicated`,
  `x-aipc-upstream: 127.0.0.1:3120` (status 200) and
  `x-aipc-revision: 44b6e36558ef01df7e167129ef197ab2c4fadc60`, and
  `/quickchat/health` answers `{"status":"ok","service":"skybuyfly-quickchat"}`
  on both addresses. PostgreSQL remains assigned to `65.109.70.111`.

## Dedicated AIPC host `aipc-fsn1-01` (`5.9.42.254`)

- Reachability: ICMP 2/2, 0 % loss, 35.7 ms average; TCP/22 open. Root SSH
  works from the review host (`date` and `hostname` returned
  `aipc-fsn1-01`); from `pitchai-main`, root/ubuntu/debian are
  `Permission denied (publickey)`. The missing authorization from
  `pitchai-main` is recorded as a capability gap, not as evidence of health.
- Host: uptime 7 days 22:40, load 1.00/0.80/0.91 on 12 CPUs, memory 20 GiB of
  125 GiB used (105 GiB available), swap 2.0 MiB of 16 GiB. `/dev/md2`
  587 GB of 921 GB = **68 %** (288 GB free), `/boot` 23 %, cold tier
  `/srv/aipc-cold` 3 %, inodes 6 %. Journal 2.0 GB (yesterday 1.9 GB) - no
  log-growth risk. Docker: images 55.2 GB (23.33 GB reclaimable), containers
  78.6 MB, volumes 0 B, build cache 0 B.
- Containers: five running and healthy with `restarts=0`
  (`aipc-shadow-stable`, `aipc-shadow-primary`, `aipc-pgbouncer`,
  `aipc-meilisearch`, `aipc-qdrant`), ten `*-staged` containers in `created`
  state awaiting activation, and `codex-privacy-edge-fmt-20260904`
  `Exited (1)` four weeks ago. No AIPC restart loops.
- Failed services: `aipc-host-audit.service` (2026-10-03T03:08:13Z, reasons
  above) and `aipc-docker-maintenance.service` (2026-10-02T03:36:41Z,
  quarantine refusal).
- Isolated GitHub runner: `aipc-ci-runner-pool-vm.service` active since
  2026-09-25T04:31:27Z with `NRestarts=0`, `MemoryCurrent` 3.0 GiB against
  `MemoryHigh` 28 GiB / `MemoryMax` 36 GiB and 7 038 s CPU time, inside an
  active `aipc-runners.slice`. With 12 CPUs, 105 GiB free memory and a 68 % RAID
  there is ample capacity, so **availability and resource suitability are
  good; the blocker is the audit contract, not resources.**
- Coordination: server-ops is required for the audit failures, the runner/key
  contract and the cold-tier quarantine. No privileged, invasive or deep check
  was attempted. No cutover or production mutation was made; `5.9.42.254` is
  not a DNS, certificate, public-traffic or PostgreSQL target.

## Coordination, fixes and mutations

- One requester-private Telegram to Seth van der Bijl (Boss), requester
  `seth-ori`, message class `status`, route kind private, no route override and
  no broad copy. Idempotency key
  `daily-monitoring-review-20261003-0325-private`; delivery verified via the
  typed helper: `state=sent`, `attempts=1`, `receipt_count=1`,
  `receipt_ref=2eca6d91f7d9f53de21ee7081fbff281d25b6eafe897b3afc32d4033f273fdb3`,
  `message_sha256=39680858214c3d49700b7fc32f798e881803c7a14199c6574e241e54b8810ad3`.
- No other outgoing message was sent: no email, WhatsApp, client, vendor,
  group, public, payment, order or legal message, and no monitor-container
  credentials were used for delivery.
- Fixes applied: none. None was warranted by the cautious-fix list: all
  certificates are valid, the monitor state is fresh, no monitored container is
  stale or hung, and every remaining finding needs an owning project.
- Deliberately not done: no Docker prune or image/volume deletion, no log or
  journal truncation, no `meilisync` restart, no AIPC remediation, no E2E test
  activation/pause/retirement, and no DNS, certificate, database-routing,
  public-traffic or production-runtime change.

## Evidence window and deliverable

- Collection 2026-10-03T03:06-03:25Z (05:06-05:25 CEST); evidence window
  2026-10-02T03:05Z to 2026-10-03T03:25Z.
- `service-monitoring` `/data/state.json`: version 6, `updated_at`
  2026-10-03T03:13:26Z, `state_write_fail_streak=0`, cycle 146.3 s; dashboard
  freshness `fresh` (60 s interval, 180 s stale threshold).
- Dashboard 24 h: availability 88.63 %, 51 033 observations, 18 problem events
  / 17 recoveries, `attention`; `service_health` 81 healthy / 12 down of 93.
- PM task: `Daily monitoring review 2026-10-03`
  (`81f9f19f-85e0-4c6c-9a07-66d76cecf233`, project
  `Repo: pitchai-monitoring`), tracked by the current Codex/self-review agent.
- Repeating reminder instructions were not changed, so no stored `prompt.md`
  update was required.
