# Daily monitoring review: 2026-09-30

## Decision

Six of the seven enabled domains were clean for the whole 24 h window and every
run of the external E2E lane's **four schedulable recurring tests** passed
(634/634), but the day is **not** all clear. Three items need a human decision,
and one of them is new. The External E2E section below carries a dated
evidence-classification correction: the registry's 36 rows split into 4
schedulable, 3 temporarily paused and 29 disabled, and the pass aggregate
covers only the schedulable four.

**`skybuyfly.pitchai.net` broke three times in the window** after a clean day -
2026-09-29 16:46-17:49Z, 21:19-21:27Z and 2026-09-30 00:55-01:01Z - finishing at
**96.454% availability** (25 failed samples of 705). The front door
`aipc-hel1-01` logged **401 `no live upstreams` and 294 `upstream timed out`**
entries in today's error log alone (1 668 / 1 515 more in the 2026-09-29
rotation), and both `aipc-shadow-*` containers were restarted at 01:11Z. This is
the same no-drain upstream-swap pattern that produced the 2026-09-26/28
incidents, now recurring.

**`pitchai-main` reached 90% on `/dev/md2` (172 GB free) and its guarded
builder-cache reclamation now hard-fails.** The timer ran at 03:49:22 CEST with
`guard_fail=active_cache_records:1`, `reclaimable_before=222.9GB` and exit code
22 against a 200 GiB reserve - the guard is blocked exactly when it is needed,
and `pitchai-potai-staging-release-cleanup` fails at its retention floor as
well.

**`aipc-hel1-01` (the host serving the public SkyBuyFly entry point) is at 87%,
59 GB free, below its own 100 GiB audit floor**, and its
`aipc-hel1-meilisync-watchdog.service` has entered a tight failure loop: **132
failed runs in 24 h**, every one `critical sequence=... alerts=1` with exit
status 2, retrying roughly every minute since 03:00Z.

Two positives worth recording: **yesterday's SkyBuyFly certificate deadlock is
resolved** - the lineage was renewed 2026-09-29 11:56:09Z and is now valid to
2026-12-28, served identically from both hosts - and the demo lanes
(`montrachet-demo`, `aigenda-rules`) recovered. No fix was applied by this lane;
one requester-private escalation was sent. Live collection ran
2026-09-30T03:00-03:08Z.

## Enabled domains (24 h window, 705 samples each)

| Domain | OK / total | Availability | p50 / p95 HTTP | Codes |
| --- | --- | --- | --- | --- |
| `autopar.pitchai.net` | 705/705 | **100%** | 18.0 / 53.4 ms | 200 |
| `afasask.gzb.nl` | 705/705 | **100%** | 17.1 / 38.7 ms | 200 |
| `skybuyfly.pitchai.net` | 680/705 | **96.454%** | 127.7 / 434.9 ms | 200, 502 |
| `deplanbook.com` | 705/705 | **100%** | 3.7 / 8.6 ms | 200 |
| `cms.deplanbook.com` | 705/705 | **100%** | 75.7 / 172.4 ms | 200 |
| `dpb.pitchai.net` | 705/705 | **100%** | 14.2 / 52.4 ms | 200 |
| `hetcis.nl` | 705/705 | **100%** | 59.9 / 69.7 ms | 200 |

`stable.skybuyfly.pitchai.net` mirrors the public lane and is slightly worse -
**672/705 = 95.319%** with 33 failed samples. Live probes confirm all seven
enabled names answer now (200/302/307 by design, none slower than 0.22 s), and
the pinned contract probe `--resolve skybuyfly.pitchai.net:443:37.27.67.52`
returns **200 in 0.190 s**.

Non-enabled domains that moved in the window:

| Domain | OK / total | Availability | Failure | State |
| --- | --- | --- | --- | --- |
| `montrachet-demo.pitchai.net` | 694/705 | 98.440% | 500 | **recovered** - failures 09-29 03:06-03:26Z only, 200 since |
| `aigenda-rules.demos.pitchai.net` | 693/705 | 98.298% | 503 | **recovered** - 09-29 03:06-03:22Z and 09:38-09:40Z, 200 since |
| `whatsapp.pitchai.net` | 705/705 | 100% | - | fully recovered |

Both demo lanes were still failing in yesterday's report; the ingress owner's
fix holds and today's live probes return 200 in 0.15-0.30 s. The standing
policy-down set is unchanged: `agentcloud.pitchai.net` 0/705 (502),
`cursussen.pitchai.net` 0/705 (404), `dashboards.pitchai.net` 0/705 (502),
`support.pitchai.net` 0/705 (502), `registry.pitchai.net` 0/705 (its 15 s TLS
timeout is the monitor's known exclusion) and five `jeff-*` names 0/705
(ConnectError).

## SkyBuyFly front door `aipc-hel1-01` (157.180.101.33)

Three interruption windows, all with the same signature - the front door has no
live upstream while a cutover is in flight:

| Window (UTC) | Public lane | `stable.` lane | Front-door evidence |
| --- | --- | --- | --- |
| 09-29 16:46-17:49 | 502s + 30-49 s browser renders | 14 of 17 cycles failed (502 / timeout) | 400 log lines at 16h, **2 258 at 17h** |
| 09-29 21:19-21:27 | 15 s timeouts, 502, 39 s browser render | 502 + 15 s timeout | 224 log lines at 21h |
| 09-30 00:55-01:01 | 15 s timeouts, 502 | 502 + 10 s timeout | 621 lines at 00h, 74 at 01h |

Root-cause evidence from `/var/log/nginx/error.log` on the front door:

```
[error] no live upstreams while connecting to upstream, server: stable.skybuyfly.pitchai.net,
        upstream: "http://aipc_stable/snapshots/..."          (401 in today's log, 1 668 on 09-29)
[error] upstream timed out (110: Connection timed out) while reading response header from upstream,
        upstream: "http://127.0.0.1:3121/..."                 (294 today, 1 515 on 09-29)
```

Recovery: `aipc-shadow-primary` restarted at **01:11:02Z** and
`aipc-shadow-stable` at **01:11:49Z** (both `RestartCount=0`, healthy since),
the monitor logged `domain_up` at 01:03:13Z and `api_contract_recovered` at
01:11:33Z, and the proxy signal has been clean for 58 consecutive cycles. All
public traffic was evaluated against the contract address `37.27.67.52`; DNS
still answers `157.180.101.33` and that mismatch is recorded, not acted on.

## Signals

`state.json` is schema **v6**, last written 2026-09-30T03:03:56Z (read back at
near-zero age), cycle 121.5 s, `state_write_fail_streak=0`.
`monitoring.pitchai.net/health` returns `ok:true`.

| Signal | Bad / total | Latest | Reading |
| --- | --- | --- | --- |
| `browser` | 0/706 | ok | `degraded_active=0`, `launch_fail_count=0` |
| `dns` | 0/89 | ok | `fail_streak=0`, 89 domains resolved |
| `proxy` | 3/706 | ok | dips during the SkyBuyFly windows, now `success_streak=58`, `pct_502_504=0.0` on the last 381 accesses |
| `tls` | 24/24 | **failed** | 3 excluded lineages, `fail_streak=542` |
| `container_health` | 706/706 | **failed** | `dft-worker` false positive, `fail_streak=6304` |
| `host_health` | 706/706 | **failed** | memory 86.003%, swap **100.0%**, CPU 18.364%, load1/CPU 0.228, worst disk 84.995%, 3 violations |
| `performance` | 706/706 | failed | 45 slow domains |
| `red` | 706/706 | failed | 39 violations |
| `slo` | 706/706 | failed | 5 violations |
| `meta` | 706/706 | failed | 1 standing reason, 121.5 s cycle |

`container_health` remains a monitor-side false positive, re-verified this
morning: applying the monitor's own `include_name_patterns` to `docker ps -a`
matches 59 containers and the only non-running one is the intentionally stopped
blue/green predecessor `dft-worker` (`Exited (0)`, retired). `dft-worker-green`
is up 43 h, and zero matched containers are unhealthy, starting or restarting.
`tls`, `performance`, `red`, `slo` and `meta` are the long-standing baseline.
`api_contract` is clean for every domain except the standing
`dispatch.pitchai.net` vhost (`fail_streak=8290`, public URL answers 302
correctly), unchanged from prior reports, and `synthetic` is 0 failures
everywhere.

## Host: `pitchai-main` disk, memory and swap

| Metric | Now | Yesterday | Two days ago |
| --- | --- | --- | --- |
| `/dev/md2` used | **90%** (172 GB free) | 88% (203 GB free) | 88% (209 GB free) |
| Swap used | **32 734 / 32 734 MiB (100%)** | 100% | 100% |
| Memory | 8.7 GiB available of 62.5 GiB, 86.003% used | 8 633 MiB | - |
| Load | load1 7.31 (0.228/CPU on 32 CPUs) | - | - |

Docker storage: `Images 228.3 GB / 398 (169.5 GB reclaimable)`,
`Build Cache 109.7 GB (96.95 GB reclaimable)`, `Local Volumes 128.2 GB / 20
(27.38 GB reclaimable)`, containers 13.47 GB of 199. Inodes are comfortable.

**The guarded reclamation path is now failing rather than merely tight.**
`pitchai-production-builder-cache-cleanup` ran 2026-09-30 03:49:22 CEST:

```
active_cache_records_before=1
reclaimable_before=222.9GB
guard_fail=active_cache_records:1
exit_code=22
```

The guard refuses to touch the default builder cache while an active cache
record exists, so the 200 GiB reserve cannot be restored by the automation.
`pitchai-potai-staging-release-cleanup.service` failed again at 04:36:21 CEST
(`retention floor`), and `logrotate.service` completed normally at 00:00 CEST.
Nothing was deleted, pruned, rotated or restarted from this lane.

The monitor stack itself was redeployed about 6 h before this review
(`service-monitoring`, `e2e-registry`, `e2e-runner`, `domain-incident-events`,
`database-dependency-monitor`, `scheduler-placement-observer` all started
2026-09-29T21:11:58Z on image
`service-monitoring:202b3f5635c9b8b3811fa0f2621e4bf798de4d90`, `RestartCount=0`);
state, dashboard and E2E have been healthy since.

## Nginx, proxy and logs

`nginx -t` passes, with the standing `conflicting server name` warnings for
`pitchai.net`, `www.pitchai.net`, `staging.chat.pitchai.net` and
`chat-staging.pitchai.net`. Since the 00:00 CEST rotation
`/var/log/nginx/error.log` holds 1 068 lines, dominated by
`connect() failed (Connection refused)` for `support.pitchai.net` (304),
`pitchai.net` (191) and `dashboards.pitchai.net` (168) - all known dead local
upstreams or scanner traffic. There are **zero** `no live upstreams`,
`upstream prematurely closed`, `upstream sent too big header` and **zero**
`skybuyfly` entries on this host: the SkyBuyFly failures are on the front door
`aipc-hel1-01`. Access-log 5xx for the day is **473, all 502, no 504**.

## TLS, ACME and certificates

- **`skybuyfly.pitchai.net` is fixed.** The lineage was renewed 2026-09-29
  11:56:09Z and is valid to **2026-12-28 11:56:08Z**; the front door's local
  copy shows the same dates, and `pitchai-main` now serves it from
  `/etc/pitchai/tls-replicas/skybuyfly.pitchai.net/current/`. Yesterday's
  escalation item #1 is closed. No `skybuyfly` lineage remains in
  `pitchai-main`'s certbot store.
- `registry.pitchai.net:5000` direct TLS serves `CN=registry.pitchai.net` from
  Let's Encrypt `YE1`, valid 2026-09-21 to **2026-12-20**, and
  `docker manifest inspect .../pitchai/codex-runner:latest` succeeds.
- No `-0001` duplicate lineages exist; the removed `afasask.gzb.nl-0001` has not
  returned.
- `staging.formatief-toetsen.pitchai.net` ACME webroot routing is intact - a
  missing challenge file returns **404 from the webroot on both HTTP and
  HTTPS**, not an auth redirect.
- `n8n.pitchai.net` shows no reappearance: no enabled site, no lineage, no
  container.

## Dedicated AIPC host: `aipc-fsn1-01` (5.9.42.254)

Reachable over SSH (`BatchMode`, read-only); up 4 days 22:33, load 0.11 on 12
CPUs.

| Area | Evidence |
| --- | --- |
| Disk | `/dev/md2` **52%** (450 GB used, 425 GB free) - was 43% / 375 GB yesterday, so **+75 GB in 24 h** |
| Disk growth | `/srv/chronicle` 161 GB + `/srv/chronicle-series` 99 GB + `/var/lib` 181 GB (docker overlay) |
| Inodes | 6% of 61.4 M |
| Memory / swap | 8 GiB of 125 GiB used, 117 GiB available, swap 0 B of 16 GiB |
| Journal | 1.8 GB archived + active |
| Containers | 5 running and healthy with **0 restarts** (`aipc-shadow-primary`, `aipc-shadow-stable`, `aipc-pgbouncer`, `aipc-meilisearch`, `aipc-qdrant`); docker holds 116 images / 55.2 GB (23.3 GB reclaimable), 16 containers, 0 volumes |
| Failed units | 2 - `aipc-docker-maintenance.service` (retained HDD cold tier quarantined) and `aipc-host-audit.service` (`ci-runner-contract-invalid`, `ci-runner-installed-source-invalid`, `deploy-authorized-key-policy-invalid`, plus `installed byte mismatch: /usr/local/sbin/aipc-deploy-ssh-dispatch`) |
| Runner | Runbook probe returns `no_actions_runner_units` (this host uses the VM pool); `aipc-ci-runner-pool-vm.service` **active since 2026-09-25 04:31:27Z, NRestarts=0**, 3.07 GiB RSS under a hard `MemoryMax`, in its own `aipc-runners.slice` |

Runner availability, isolation and resource suitability are confirmed again
(dedicated slice, hard memory cap, zero restarts, qemu control channel
present). The day-over-day growth is the `chronicle` product/video work, not the
runner pool. Coordinate the quarantine, runner contract and any reclamation
with server-ops; nothing was deleted or pruned.

## Front door host `aipc-hel1-01`: storage and the Meilisync failure loop

Up 3 days 22:31, load 6.86, `/dev/md2` **87%** (370 GB used, **59 GB free**),
18 containers running, 0 restarting, 21 exited (including 20 `aipc-usability-*`
batch containers, several `Exited (137)` - an active AIPC batch campaign is
churning this host).

`aipc-hel1-host-audit.service` fails on every run, most recently
02:14:10Z and 02:46:16Z:

```
WARN: AIPC storage headroom below 100 GiB; continue bounded work using existing artifacts
WARN: stale product refresh requests remain active
WARN: stale non-parser OpenAI work remains outside parser ownership
FAIL: Meilisync deep reliability receipt contract mismatch
```

New this morning: `aipc-hel1-meilisync-watchdog.service` (Postgres -> Meilisearch
semantic reliability audit, timer-driven) has **132 failed runs in 24 h**, first
at 2026-09-29 15:48:18Z, currently retrying about once a minute since 03:00Z:

```
aipc-meilisync-watchdog: critical sequence=27153 alerts=1   -> exit status=2/INVALIDARGUMENT
aipc-meilisync-watchdog: critical sequence=27156 alerts=1   -> exit status=2/INVALIDARGUMENT
```

This is a live, repeating critical reliability signal on the host that fronts
public SkyBuyFly, coincident with the storage shortfall - escalated, not
remediated from this lane.

## External E2E

### Registry inventory, classified (re-verified 2026-09-30T20:03Z)

The registry holds **36 test rows**, and that is not the number of tests that
produce current evidence. Applying the scheduler's own predicate
(`e2e_registry/db.py`: `t.enabled=1 AND (t.disabled_until_ts IS NULL OR
t.disabled_until_ts <= now)`) splits the inventory three ways:

| Class | Rows | Tests |
| --- | --- | --- |
| **Schedulable recurring** | 4 | `afasask_demo_codex_fast_ok` (1 800 s), `afasask_production_codex_medium_synthetic_ok` (1 800 s), `deplanbook_cms_home_smoke_py` (300 s), `deplanbook_cms_on_demand_translation_py` (300 s) |
| **Temporarily paused** | 3 | `zz_disabled_temp_1772130669179007598`, `zz_disabled_temp_1772130669316856871`, `zz_disabled_temp_1772130685662537984` - `enabled=1` with `disabled_until_ts=1893456000` (2030-01-01) and reason `temporary probe cleanup` |
| **Disabled** | 29 | 28 rows auto-disabled `disallowed base_url host: formatief-toetsen.pitchai.net`, plus the retired `afasask_gzb_codex_medium_ok_daily` (retirement reason dated 2026-09-03) |

The three paused rows are **intentionally parked, not healthy current evidence
and not a scheduler failure**. They are excluded by design through
`disabled_until_ts`; each has exactly one run ever (last pass
2026-02-26T18:31:10Z, 18:31:11Z and 18:31:41Z), a stale `next_due_ts` from the
same day, and `success_streak=1`. Their `last_status=pass` is a February
record. Pausing, activating or retiring them belongs to the owning project;
this lane leaves them untouched.

### Prior 24 h window (2026-09-29T20:03Z - 2026-09-30T20:03Z)

Only the four schedulable tests ran: **634 runs, 634 pass, 0 non-pass.**

| Schedulable test | Runs | Pass | Last finish | Last status |
| --- | --- | --- | --- | --- |
| `deplanbook_cms_home_smoke_py` | 271 | 271 | 2026-09-30T20:02:30Z | pass |
| `deplanbook_cms_on_demand_translation_py` | 270 | 270 | 2026-09-30T20:02:25Z | pass |
| `afasask_demo_codex_fast_ok` | 47 | 47 | 2026-09-30T19:44:45Z | pass |
| `afasask_production_codex_medium_synthetic_ok` | 46 | 46 | 2026-09-30T19:39:48Z | pass |
| **Total** | **634** | **634** | | |

Scheduler state at the same read: all four `effective_ok=1`, `fail_streak=0`,
success streaks 3 028 / 833 / 227 / 226, and `next_due_ts` a few minutes ahead
of the read, so none of them is stale. The manager's 2026-09-30T12:19Z
reference snapshot showed the same 634 passes split 47/47/270/270; the per-test
split moves with cadence while the aggregate stayed at 634.

Registry summary endpoint (still useful, still needs the scope): `ok=true`,
`failing_tests=2` - both disabled historical
`dft_prod_exam_import_2doc_sla_daily_e2e` rows - and zero enabled tests with a
non-pass `last_status`. The morning report's line "Runs in the 24 h window:
634 total, 634 pass, 0 non-pass" is true **for the four schedulable recurring
tests only** and must not be read as "the whole E2E estate is green". The
earlier table row "three `zz_disabled_temp_*` | pass (February records)" was
ambiguous and is superseded by this section.

### Re-read, and both AFASAsk Codex lanes going red (2026-09-30T20:11-20:17Z)

Re-reading the same window minutes later returned 634 rows with 633 `pass`. The
single non-pass was a run still in flight: the scheduler writes a claim row
before the browser starts (`status=infra_degraded`, `error_kind=pending`,
`started_at_ts`/`finished_at_ts` NULL, id matching
`test_state.running_lock_id`), then updates **that same row** with the outcome.
Minutes later it resolved as a real failure, below. A pending row is therefore
neither a failure nor a dismissal: resolve it, or wait one cadence, before
quoting it either way - and never count it as a pass. Abandoned claims do
residue: 25 rows registry-wide still sit at `pending` with `started_at_ts IS
NULL`, the oldest 2026-08-27.

Both AFASAsk Codex lanes then failed back to back, after a clean 24 h window in
which they contributed 93 passing runs:

| Enabled test | Run (UTC) | Result | Evidence |
| --- | --- | --- | --- |
| `afasask_production_codex_medium_synthetic_ok` | 20:10:08Z - 20:14:16Z, 241 253 ms (typical 10.8-18.8 s) | `fail` / `TimeoutError`: `Page.wait_for_function: Timeout 240000ms exceeded.` | `failure.png` shows **Mislukt** - "Het is niet gelukt om Codex-modus te voltooien. Probeer het later opnieuw." on `afasask.gzb.nl/chat/demo/afasask-production-monitor-codex-medium-...` |
| `afasask_demo_codex_fast_ok` | 20:15:39Z - 20:15:41Z, 1 374 ms | `fail` / `AssertionError`: `afasask_demo_codex_canary_failed_marker: ❌ mislukt` | `demo.afasask.pitchai.net/chat/demo/afasask-demo-monitor-codex-fast-ok-...` |

`test_state` for both flipped to `effective_ok=0`, `fail_streak=1`,
`success_streak=0` (`next_due_ts` 20:45:16Z and 20:45:48Z), while
`deplanbook_cms_home_smoke_py` kept passing at 20:14:19Z. Two surfaces failing
within six minutes is a Codex-mode failure rather than a page hiccup: the auth
broker, Codex medium execution and the live UI together are exactly what these
tests verify, and the lane's own policy makes any non-pass actionable.

Detection gap worth fixing: the production lane looks for success and failure
markers inside `article[data-role="assistant"]`, while the `Mislukt` block
renders outside that article, so a hard UI failure surfaces as a 240 s timeout
instead of a named marker. The demo lane reads the marker directly and fails in
1.4 s. Open the run's `failure.png` / `run.log` before classifying an E2E
timeout as infrastructure - `browser_infra_error` was `false` here.

Related work in the owning project: PM task "Harden AFASAsk Codex account pool
and monitoring alerts" (Human Review, updated 2026-09-30T17:38Z) and the
2026-09-18 "Codex account pool weekly exhaustion" incident (Done), so account
pool exhaustion is a plausible cause to confirm rather than assume.

This finding is recorded, not escalated: the follow-up that produced this
correction is limited to internal documentation, so no external message was
sent. The next scheduled runs (20:45Z) decide whether it is a single episode or
a broken pattern, and the next morning review must re-check it.

## Hotpath lane outcomes (separate evidence stream, 2026-09-30T20:03Z)

Project hotpath lanes are **not** covered by the E2E registry aggregate and are
reported separately. Live registry: **16 real lanes** in `hotpath_lane_state`,
**204 reports** across them (206 rows in `hotpath_reports` including 2
intentional `monitoring-hotpath-synthetic` protocol-proof rows), and **81
outbox intents, all `status=delivered`** (58 `hotpath_red`, 23
`hotpath_recovered`).

| Lane (project) | Latest severity | Latest report (UTC) | Failure class / note |
| --- | --- | --- | --- |
| `aipc-hotpath-monitor` (ai_price_crawler) | **critical** | 2026-09-30T18:58:04Z | `image_refresh_trigger_not_observed`, `fail_streak=24` |
| `aipc-pedantic-e2e-ui-qa-v2` (ai_price_crawler) | **critical** | 2026-09-29T19:45:32Z | `RECOMMENDATION_API_DEPLOYMENT_REVISION_MISMATCH`, `fail_streak=13` |
| `afasask-hotpath-monitor` (afasask) | warning | 2026-09-29T19:33:52Z | `synthetic_authorization_absent`, `fail_streak=14` |
| `pitchai-net-hotpath-monitor` | info | 2026-09-30T14:17:04Z | ok |
| `potaito-hotpath-monitor` | info | 2026-09-29T23:26:04Z | ok |
| `quickchat-waddinxveen-hotpath-monitor` | info | 2026-09-29T23:01:05Z | ok |
| `orthoparse-hotpath-monitor` | info | 2026-09-29T21:06:07Z | ok |
| `cisnl-hotpath-monitor` | info | 2026-09-29T19:38:00Z | ok |
| `deplanbook-cms-hotpath-monitor` | info | 2026-09-29T19:34:14Z | ok |
| `deplanbook-play-hotpath-monitor` | info | 2026-09-29T19:20:42Z | ok |
| `dft-frontend-hotpath-playwright-b2-revival` | info | 2026-09-29T19:09:53Z | ok |
| `autopar-hotpath-monitor` | info | 2026-09-29T18:53:13Z | ok |
| `apologetica-cms-hotpath-monitor` | info | **2026-09-25T18:59:00Z** | stale ~5 days |
| `aigenda-rules-hotpath-monitor` | info | **2026-09-20T03:36:43Z** | stale ~10.7 days |
| `quickchat-rsr-hotpath-monitor` | info | **2026-09-20T03:30:48Z** | stale ~10.7 days |
| `aigenda-calendar-hotpath-monitor` | info | **2026-09-20T03:26:37Z** | stale ~10.7 days |

Reading rules:

- **Outbox `delivered` proves publisher delivery only.** It says the event
  reached the receiver inbox; it is not lane health, not remediation and not
  alert acknowledgement. Today all 81 intents are delivered while two lanes sit
  critical and four have not reported since 20-25 September, which is exactly
  why delivery status cannot be quoted as health.
- A lane's latest severity describes its **last report**, not now: the four
  stale lanes read `info` only because nothing newer exists.
- **A lane report is point-in-time, including its revisions.** Each report
  records the `source_sha` / `deployed_sha` seen when it was written, so a stale
  lane's revisions are as old as its report (the 2026-09-20 aigenda calendar /
  rules and quickchat-rsr rows still cite 20 September revisions) and only a
  fresh report can speak to the current deployment. Both AIPC criticals turn on
  revision evidence: the pedantic UI/QA lane's `expected source e482e9e9` vs
  `served 8d70b334`, and the image-refresh trigger that never observed a new
  reference.
- Delivery receipts are the mirror image of that limit: the 81 `delivered`
  outbox intents prove the publisher handed the event to the receiver inbox, not
  that any recipient acted on it.
- Two AIPC lanes are the live criticals. The 2026-09-30T12:19Z reference
  snapshot recorded both as the 29 September revision mismatch; by 20:03Z the
  UI/API/browser lane had a newer 30 September critical
  (`image_refresh_trigger_not_observed`) while the pedantic UI/QA lane still
  carries the revision mismatch.
- Current-UI and hotpath remediation is owned by the AIPC manager; this report
  records evidence only and starts no competing work.

## Dated evidence and acceptance matrix (correction)

All rows re-verified 2026-09-30T20:03-20:05Z against the live registry on
`pitchai-main` through a read-only SQLite handle
(`sqlite3.connect(f"file:{settings.db_path}?mode=ro", uri=True)`) inside the
`e2e-registry` container. No write, no lock, no runtime change.

| Requirement | Evidence (dated 2026-09-30) | State |
| --- | --- | --- |
| Classify schedulable / paused / disabled | 36 rows = 4 schedulable + 3 paused (`disabled_until_ts=1893456000`) + 29 disabled (28 DFT disallowed-host, 1 retired AFASAsk), predicate from `e2e_registry/db.py` | met |
| Paused rows are deliberate, not a scheduler failure | excluded by design; 1 run each, last pass 2026-02-26T18:31Z, stale `next_due_ts`, `success_streak=1` | met |
| Scope the pass aggregate | 634/634 split 271/270/47/46 over the four schedulable tests, window 2026-09-29T20:03Z-2026-09-30T20:03Z | met |
| Freshness per schedulable test | last finishes 20:02:30Z / 20:02:25Z / 19:44:45Z / 19:39:48Z; all `effective_ok=1`, `fail_streak=0` | met |
| Separate hotpath outcomes from the E2E aggregate | 16 lanes, 204 lane reports, latest severity + timestamp per lane listed above | met |
| Outbox delivery is not lane health | 81/81 `delivered` while 2 lanes are critical and 4 are stale | met |
| In-flight claim rows are resolved, not dismissed | re-read 20:11-20:14Z showed 634 rows / 633 `pass`; the one non-pass was the claim row for the 20:10:08Z AFASAsk production run, which resolved at 20:14:16Z as a real `TimeoutError` failure - reported above, not waved away | met |
| Post-window AFASAsk Codex failure recorded | both enabled AFASAsk lanes red at 20:14:16Z and 20:15:41Z (screenshot shows `Mislukt`), evidence, detection gap and owner named above | met |
| Preserve schedule, human stops, alert policy and data | documentation-only change; no test, scheduler, alert or runtime mutation; runbook edit is additive | met |

## Future review guidance (added 2026-09-30)

Recorded here and in the durable surfaces a later review actually reads: the
tracked guide `docs/daily-review-evidence-classification.md` (the canonical,
reviewable copy with the dated evidence snapshot), the runbook section
`monitoring/runbooks/daily-monitoring-review.md` > "E2E evidence
classification", and the repeating reminder prompt. Together they mean a later
review cannot repeat the ambiguity:

1. Classify the registry before quoting any aggregate: **schedulable recurring**
   (`enabled=1`, no future `disabled_until_ts`), **temporarily paused**
   (`enabled=1` with a future `disabled_until_ts`), **disabled** (`enabled=0`).
2. Quote the pass aggregate with its scope and per-test split - never as a bare
   "E2E is green".
3. Never present a paused or disabled row's historical `last_status` as current
   evidence, and never read a paused row as a scheduler failure.
4. Report each schedulable test's last finish and status; treat a test whose
   last run is older than roughly two intervals as stale evidence to
   investigate.
5. Report hotpath lanes from `hotpath_lane_state` / `hotpath_reports` per lane,
   with severity, failure class and last-report age, kept separate from the E2E
   aggregate.
6. Treat outbox `delivered` as publisher-delivery proof only.
7. Do not activate, pause, retire or edit tests from the monitoring lane; that
   belongs to the owning project.
8. Resolve an in-flight claim row (`error_kind='pending'`, `started_at_ts IS
   NULL`) before quoting it: the scheduler updates that same row with the
   outcome. A lone non-pass is either a real failure or a claim that has not
   finished - it is never a pass and never something to wave away.
9. Open a failing run's `failure.png` / `run.log` artifacts before classifying
   an E2E timeout as infrastructure, and check the sibling lane for the same
   product path (`browser_infra_error=false` plus a `Mislukt` screenshot is a
   product failure, not a runner problem).

## Topology compliance and actions

- Public SkyBuyFly web/API traffic was evaluated against `37.27.67.52` only
  (pinned probe 200 in 0.190 s, `stable.` 200 in 0.211 s), with the DNS answer
  `157.180.101.33` recorded separately.
- PostgreSQL remains on `65.109.70.111`; no database routing changed.
- `5.9.42.254` was treated as a non-public dedicated host: shallow read-only
  checks only, no DNS, certificate, public-API, traffic or PostgreSQL action.
- No cutover or production mutation was made and this handoff stayed internal.
- No fix was applied from this lane - the front-door shortfall, the disk/guard
  conditions and the Meilisync failure loop all need owner decisions, and none
  of them is a safe blind repair.
- One requester-private Telegram escalation was sent to Seth van der Bijl
  covering the SkyBuyFly upstream recurrence, the `pitchai-main` disk/builder
  guard, the `aipc-hel1-01` storage plus Meilisync failure loop, the
  `aipc-fsn1-01` growth and failed audit units, and the resolved certificate.
- The later E2E evidence correction appended to this report was
  documentation-only: no test activation or pause, no synthetic submission, no
  runtime, production or `main` change, and no external message (including
  Telegram). The repeating schedule, human stops, alert policy and data are
  unchanged.

## Recommended follow-ups

1. Fix the SkyBuyFly cutover so the front door drains before the
   `aipc-shadow-*` swap - three windows in 24 h, `no live upstreams` and 110 s
   timeouts, public availability down to 96.45%.
2. Clear the active builder cache record on `pitchai-main` and repair
   `pitchai-potai-staging-release-cleanup` so the 200 GiB reserve can be
   restored; `/dev/md2` is at 90% with 172 GB free.
3. Reclaim or expand storage on `aipc-hel1-01` (87%, 59 GB free - below its own
   audit floor) and clear the `aipc-usability-*` batch backlog.
4. Investigate the `aipc-hel1-meilisync-watchdog` critical alerts
   (132 failures/24 h, exit 2) together with the host-audit
   `Meilisync deep reliability receipt contract mismatch`.
5. Watch the `aipc-fsn1-01` growth (+75 GB/day, `chronicle*` 260 GB) and repair
   its two audit units (`ci-runner-*` contract, `deploy-authorized-key-policy`)
   with server-ops.
6. `container_health` still pins itself on the intentionally-stopped
   `dft-worker` standby; coverage owner **583034b6** owns that fix. This lane
   records the evidence and does not duplicate it.
7. Four hotpath lanes have not reported since 20-25 September (aigenda
   calendar, aigenda rules, quickchat-rsr, apologetica); their owning projects
   should confirm the lanes are still expected to report. AIPC current-UI and
   hotpath remediation stays with the AIPC manager.
