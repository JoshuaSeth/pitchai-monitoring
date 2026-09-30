# Daily monitoring review: 2026-09-30

## Decision

Six of the seven enabled domains were clean for the whole 24 h window and the
external E2E lane passed every run, but the day is **not** all clear. Three
items need a human decision, and one of them is new.

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

Registry summary: `ok=true`, **36 tests**, `failing_tests=2` - both the disabled
historical `dft_prod_exam_import_2doc_sla_daily_e2e` rows. **Zero enabled tests
carry a non-pass `last_status`** and zero enabled tests have
`effective_ok=0`.

Runs in the 24 h window: **634 total, 634 pass, 0 non-pass.**

| Enabled test | Latest | Streak | Elapsed |
| --- | --- | --- | --- |
| `afasask_demo_codex_fast_ok` | pass | 194 | 9 844 ms |
| `afasask_production_codex_medium_synthetic_ok` | pass | 193 | 21 181 ms |
| `deplanbook_cms_home_smoke_py` | pass | 2 836 | 1 913 ms |
| `deplanbook_cms_on_demand_translation_py` | pass | 642 | 769 ms |
| three `zz_disabled_temp_*` | pass (February records) | 1 | 313-669 ms |

The reminder's named `afasask_gzb_codex_medium_ok_daily` remains `enabled=0`
(retired); its active replacement, `afasask_production_codex_medium_synthetic_ok`,
passed every run in the window and exercises the medium Codex UI end to end.

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
6. Fix `container_health`'s include pattern so the intentionally-stopped
   `dft-worker` standby no longer pins the signal down (9 days now).
