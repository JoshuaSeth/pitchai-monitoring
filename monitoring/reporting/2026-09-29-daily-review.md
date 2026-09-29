# Daily monitoring review: 2026-09-29

## Decision

Every customer-facing surface is ready for the day, and for the first time this
week the enabled monitor set is **100% clean for the whole 24 h window** -
including `skybuyfly.pitchai.net`, which had no dip at all after three
consecutive days of public interruption. The monitor state is fresh, the
dashboard answers, the proxy and DNS signals have zero bad cycles, the external
E2E lane ran **636/636 passes**, all monitored containers are running, the
registry certificate and manifest are good into December, `nginx -t` passes and
n8n has not reappeared.

Three things still keep the day off "all clear", and two of them are time-bound
rather than incidental.

**The `skybuyfly.pitchai.net` certificate is now 20 days out** (expires
2026-10-19T03:35:18Z) and **both** hosts failed renewal again inside the window
- `pitchai-main` at 2026-09-28 16:32:04 CEST (http-01 served a 404 from
`157.180.101.33`) and `aipc-hel1-01` at 2026-09-28 15:50:56Z. The lineage lives
on `pitchai-main`, public DNS sends the ACME challenge to the front door, and
neither side can complete alone. This is a fixed fuse, not a backlog item.

**The front door `aipc-hel1-01` now fails its own storage audit** -
`aipc-hel1-host-audit.service`: `FAIL: AIPC storage free space below 100 GiB`
(100 GB free, 77%). Its `certbot.service` is failed for the same SkyBuyFly
lineage. The host serving the public SkyBuyFly entry point is the one running
out of room.

**The demo ingress `135.181.182.48` is failing for a second day.**
`montrachet-demo.pitchai.net` returns **500 right now** (app-level, ~30 ms, no
timeout) and `aigenda-rules.demos.pitchai.net/readyz` answers
`503 {"status":"not-ready","python_rule_runtime":false}` while the rest of the
site is 200. Both are non-enabled internal demo lanes, but this is a repeat.

`pitchai-main` capacity keeps tightening as well: swap is fully consumed for an
eighth consecutive review and the builder-cache guard is now only **3.0 GiB**
above its 200 GiB reserve (7.4 GiB yesterday).

No fix was applied in this lane; one requester-private escalation was sent.
Live collection ran 2026-09-29T03:00-03:07Z.

## Enabled domains (24 h window, 704 samples each)

| Domain | OK / total | Availability | p95 HTTP | Codes |
| --- | --- | --- | --- | --- |
| `autopar.pitchai.net` | 704/704 | **100%** | 63.5 ms | 200 |
| `afasask.gzb.nl` | 704/704 | **100%** | 42.9 ms | 200 |
| `skybuyfly.pitchai.net` | 704/704 | **100%** | 173.5 ms | 200 |
| `deplanbook.com` | 704/704 | **100%** | 8.0 ms | 200 |
| `cms.deplanbook.com` | 704/704 | **100%** | 188.4 ms | 200 |
| `dpb.pitchai.net` | 704/704 | **100%** | 50.1 ms | 200 |
| `hetcis.nl` | 704/704 | **100%** | 69.3 ms | 200 |

`stable.skybuyfly.pitchai.net` mirrors the public lane exactly (704/704, 100%).
Availability and p95 are derived from `/data/state.json` with the dashboard's
own rules; the dashboard UI itself needs a session token, so the aggregate
`daily_status` panel was not read directly this morning.

Non-enabled domains that moved in the window:

| Domain | OK / total | Availability | Failure | State |
| --- | --- | --- | --- | --- |
| `aigenda-rules.demos.pitchai.net` | 643/704 | 91.335% | 503 | **active** - `/readyz` still 503 |
| `montrachet-demo.pitchai.net` | 681/704 | 96.733% | 500 | **active** - 500 every cycle since 01:55Z |
| `whatsapp.pitchai.net` | 513/704 | 72.869% | 503 | recovered 2026-09-28 09:35:51Z, 200 since |

The standing policy-down set is unchanged: `agentcloud.pitchai.net` 0/704 (502),
`cursussen.pitchai.net` 0/704 (404), `dashboards.pitchai.net` 0/704 (502),
`support.pitchai.net` 0/704 (502), `registry.pitchai.net` 0/704 (its 15 s TLS
timeout is the monitor's known exclusion) and five `jeff-*` names 0/704
(ConnectError). `dashboards` and `support` still point at `localhost:3200` /
`:8420` with no listener - unchanged from 2026-05-18.

## Demo ingress `135.181.182.48`

`montrachet-demo.pitchai.net` moved from "dipped and recovered" (yesterday
10:24-11:12Z) to a standing failure:

| Time (UTC) | Result |
| --- | --- |
| 01:55:01 | `domain_down` (500) |
| 02:16:54 | `domain_down` (500) |
| 02:46:43 - 03:00:15 | 500 on every cycle, ~30-140 ms |
| 03:01-03:04 live probes | 500 in 0.03-0.10 s from this workstation and from `pitchai-main` |

The response is nginx's own `Internal Server Error` from the demo ingress, not a
timeout, so the upstream app is answering with a fault. `aigenda-rules` shares
the host and its readiness endpoint names the cause precisely:

```
{"status":"not-ready","checks":{"agent_runtime":true,"bubblewrap":true,
 "python_rule_runtime":false,"auth_broker":true,"database":true},
 "environment":"production","revision":"294d8fd4..."}  -> 503
```

The plain site root returns 200 in 0.02 s, so only the sandboxed Python rule
runtime is down. The monitor saw 503s on `/readyz` from 02:46:43Z through the
last cycle and a `browser_check_failed` (HTTP 200, fail_streak 2) at
00:59:46Z. Both hosts are outside this repo's SSH inventory (`135.181.182.48` is
not `pitchai-main`, `pitchai-ax41`, `pitchai-jeff-dev`, `pitchai-file-storage`
or `dft-db-hel1-5950x`), so ownership and remediation belong to the demo-ingress
owner; no probe was repaired from this lane.

## Signals

`state.json` is schema **v6**, last written 2026-09-29T03:02:18Z (read back at
zero age), cycle 123.4 s, `state_write_fail_streak=0`.
`monitoring.pitchai.net/health` returns `ok:true`.

| Signal | Bad / total | Latest | Reading |
| --- | --- | --- | --- |
| `browser` | 0/704 | ok | `degraded_active=0`, `launch_fail_count=0` |
| `dns` | 0/88 | ok | 88 domains resolved |
| `proxy` | 0/704 | ok | 0 upstream issues, `pct_502_504=0.0`, 477 accesses sampled, 0 upstream events |
| `tls` | 24/24 | **failed** | 3 failures per cycle on the Telegram-excluded domains |
| `container_health` | 704/704 | **failed** | `dft-worker` false positive - root-caused below |
| `host_health` | 704/704 | **failed** | memory 85.626%, swap 100.0%, CPU 20.136%, load1/CPU 0.193, worst disk 83.149%, 3 violations |
| `performance` | 704/704 | failed | 43 slow domains |
| `red` | 704/704 | failed | 42 violations |
| `slo` | 704/704 | failed | 5 violations |
| `meta` | 704/704 | failed | 1 standing reason, 123.4 s cycle |

**`container_health` root cause, confirmed this morning.** The signal has been
false for 5,596 consecutive cycles since the 2026-09-21 degrade event, and it is
not the container yesterday's report named. Re-running the monitor's own
`include_name_patterns` from `domain_checks/config.yaml` against
`docker ps -a` matches 59 containers, of which exactly one is not running:

```
dft-worker | Exited (0) 20 hours ago
```

`^dft-worker(?:-green|-staging|-staging-spend-enabled)?$` matches both the live
`dft-worker-green` (up 19 h) and the retired blue/green predecessor
`dft-worker`, which exits 0 after every cutover. Zero matched containers are
unhealthy, starting or restarting. This is a monitor-side pattern defect - the
signal cannot recover while an intentionally-stopped standby matches - not an
infrastructure fault. `tls`, `performance`, `red`, `slo` and `meta` are the
long-standing baseline (three excluded lineages, slow-domain/render-time
counter, policy-down routes).

## Host: pitchai-main disk, memory and swap

| Metric | Now | Yesterday | Two days ago |
| --- | --- | --- | --- |
| `/dev/md2` used | **88%** (203 GB free) | 88% (209 GB free) | 87% (217 GB free) |
| Swap used | **32 682 / 33 520 MiB (100%)** | 100% | 100% |
| Memory | available 8.3 GiB of 62.5 GiB, 85.626% used | 8 633 MiB | - |
| Load | load1 7.32 (0.229/CPU on 32 CPUs) | - | - |

Docker storage: `Images 213 GB / 384 (152.7 GB reclaimable)`,
`Build Cache 104.2 GB (91.4 GB reclaimable)`, `Local Volumes 128.2 GB /
27.38 GB reclaimable`, containers 12 GB of 199. Inodes are comfortable at 12%.

Neither guarded reclamation path helped:
`pitchai-production-builder-cache-cleanup` ran at 03:48:36 CEST with
`available_before=217951195136` against `reserve_bytes=214748364800` and
concluded `status=reserve-satisfied` - **3.0 GiB of margin**, down from 7.4 GiB
yesterday, with consumption running 4-6 GiB/day.
`pitchai-potai-staging-release-cleanup.service` failed again at 04:59:05 CEST
(`retention floor retained=0 minimum=20 total=24 candidates=24`).
`logrotate.service` completed successfully at 00:00:05 CEST for a fifth
consecutive night. Nothing was deleted, pruned, rotated or restarted from this
lane.

## Nginx, proxy and logs

`nginx -t` passes, with the standing `conflicting server name` warnings for
`pitchai.net`, `www.pitchai.net`, `staging.chat.pitchai.net` and
`chat-staging.pitchai.net` ("configuration file test is successful"). Since the
00:00 CEST rotation `/var/log/nginx/error.log` holds 950 lines, dominated by
`connect() failed (Connection refused)` for `support.pitchai.net` (50) and
`dashboards.pitchai.net` (57) - both the known dead local upstreams, now also
being probed by scanners (`/wp-config*.php`, `aws_credentials.json`). There are
**zero** `no live upstreams`, `upstream prematurely closed` or `upstream sent
too big header` entries, and **zero** `montrachet` entries on this host - the
demo failures are on the ingress at `135.181.182.48`, not here. Access-log 5xx
for the day is **491, all 502, no 504**, dominated by the monitor's own probes
of the policy-down routes.

The proxy signal was clean for all 704 cycles.

## TLS, ACME and certificates

- `registry.pitchai.net:5000` direct TLS serves `CN=registry.pitchai.net` from
  Let's Encrypt `YE1`, valid 2026-09-21 to **2026-12-20**, and
  `docker manifest inspect registry.pitchai.net:5000/pitchai/codex-runner:latest`
  succeeds, so auto-dispatch is intact.
- **`skybuyfly.pitchai.net` is at 20 days** (expires 2026-10-19T03:35:18Z).
  `pitchai-main` failed at 2026-09-28 16:32:04 CEST with
  `Detail: 157.180.101.33: Invalid response from
  http://skybuyfly.pitchai.net/.well-known/acme-challenge/...: 404`, and
  `aipc-hel1-01`'s `certbot.service` failed at 2026-09-28 15:50:56Z on the same
  lineage. The renewal config is ordinary (`authenticator = nginx`,
  `renew_before_expiry = 30 days`); the blocker is that DNS points at the front
  door while the lineage and its webroot live on `pitchai-main`. No safe
  one-sided fix exists from this lane, and repeating `certbot renew` would only
  consume rate limit, so the ambiguity is escalated instead.
  `stable.skybuyfly.pitchai.net` is healthy at 50 days (2026-11-18).
- No `-0001` duplicate lineages exist; the removed `afasask.gzb.nl-0001` has not
  returned and `afasask.gzb.nl` is valid for 55 days (2026-11-24).
  `staging.formatief-toetsen.pitchai.net` webroot routing is intact - a missing
  challenge file returns **404 from the webroot on both HTTP and HTTPS**, not an
  auth redirect.
- `n8n.pitchai.net` shows no reappearance: no enabled site, no lineage, no
  container.
- The `registry` container's 02:30:09Z start is the routine daily
  `registry-auto-prune` cron (04:30 local: prune, garbage-collect, then
  `docker start registry`), not a crash or restart - `RestartCount=0` and the
  registry answered throughout.

## Dedicated AIPC host: `aipc-fsn1-01` (5.9.42.254)

Reachable over SSH (`BatchMode`, read-only); up 3 days 22:33, load 0.33 on 12
CPUs.

| Area | Evidence |
| --- | --- |
| Disk | `/dev/md2` **43%** (375 GB used, 501 GB free) - was 37% / 323 GB yesterday |
| Disk growth | `/srv` (176 GB) is the driver: `chronicle-series` 99 GB + `chronicle` 85 GB; **runner storage is flat at 119 GB** |
| Inodes | 6% of 61.4 M |
| Memory / swap | 8.6 GiB of 125 GiB used, 117 GiB available, swap 0 B of 17 GiB |
| Journal | 1.8 GB archived + active (unchanged), 41 196 lines in 24 h |
| Containers | 5 running and healthy with **0 restarts** (`aipc-shadow-primary`, `aipc-shadow-stable`, `aipc-pgbouncer`, `aipc-meilisearch`, `aipc-qdrant`); 9 `aipc-*-staged` in `created` (prepared, never started); `codex-privacy-edge-fmt-20260904` exited 3 weeks ago |
| Failed units | 2 - `aipc-docker-maintenance.service` (`refusing maintenance while the retained HDD cold tier is quarantined`, cold tier `/srv/aipc-cold` is empty at 36 KB) and `aipc-host-audit.service` (`ci-runner-contract-invalid, ci-runner-installed-source-invalid, deploy-authorized-key-policy-invalid`, plus `installed byte mismatch: /usr/local/sbin/aipc-deploy-ssh-dispatch`) |
| Runner | Runbook probe returns `no_actions_runner_units` (this host uses the VM pool instrument); `aipc-ci-runner-pool-vm.service` **active since 2026-09-25 04:31:27Z, NRestarts=0**, 2.8 GiB RSS, `MemoryMax` 36 GiB, slice `aipc-runners.slice`, qemu with 8 vCPU / 32 GiB |
| Cold tier | `/dev/sda1` (`/srv/aipc-cold`) mounted, 1.8 T, 36 KB used - held empty by the quarantine |

Runner availability, isolation and resource suitability are confirmed: the pool
VM runs under its own slice with a hard memory cap, zero restarts, and the
`qmp.sock` control channel present. The day-over-day growth is **not** the
runner pool this time - it is the `chronicle` video/product work under `/srv`,
which gained roughly 52 GB in 24 h. Coordinate the quarantine, runner contract
and any reclamation with server-ops; nothing was deleted or pruned.

## SkyBuyFly front door: `aipc-hel1-01` (157.180.101.33)

Read-only diagnostics for incident attribution: up 2 days 22:29 (boot
2026-09-26 04:32:23Z), load 2.60, `/dev/md2` **77%** (330 GB used, **100 GB
free**), inodes 4%, memory 20 GiB of 64 GiB used, swap 0 B of 16 GiB, journal
271.8 MB. 17 containers running with zero restarting. Failed units: 2 -
`aipc-hel1-host-audit.service` (`FAIL: AIPC storage free space below 100 GiB`,
plus stale-writer warnings) and `certbot.service` (SkyBuyFly renewal,
2026-09-28 15:50:56Z).

Public traffic is still evaluated against the contract address only: the pinned
probe `--resolve skybuyfly.pitchai.net:443:37.27.67.52` returns **200 in
0.164 s**. DNS still answers `157.180.101.33`; that mismatch is recorded as an
escalation signal, not as permission to change DNS.

## External E2E

Registry summary: `ok=true`, **36 tests**, `failing_tests=2` - both the disabled
historical `dft_prod_exam_import_2doc_sla_daily_e2e` rows, with no enabled test
carrying a non-pass `last_status`.

Runs in the 24 h window: **636 total, 636 pass, 0 non-pass** - the first
flawless E2E day this week.

| Enabled test | Latest | Streak | Elapsed |
| --- | --- | --- | --- |
| `afasask_demo_codex_fast_ok` | pass | 147 | 12 406 ms |
| `afasask_production_codex_medium_synthetic_ok` | pass | 146 | 10 996 ms |
| `deplanbook_cms_home_smoke_py` | pass | 2 565 | 590 ms |
| `deplanbook_cms_on_demand_translation_py` | pass | 371 | 3 733 ms |
| three `zz_disabled_temp_*` | pass (February records) | 1 | 313-669 ms |

Yesterday's single failure (`deplanbook_cms_on_demand_translation_py`, 90 s
`wait_for_function` timeout at 19:08Z) has fully recovered: the test is at 371
consecutive passes. The reminder's named `afasask_gzb_codex_medium_ok_daily`
remains `enabled=0` with its 2026-09-03 retirement reason; its active
replacement, `afasask_production_codex_medium_synthetic_ok`, passed every run in
the window and exercises the medium Codex UI end to end.

## Topology compliance and actions

- Public SkyBuyFly web/API traffic was evaluated against `37.27.67.52` only
  (pinned probe 200 in 0.164 s), with the DNS answer recorded separately.
- PostgreSQL remains on `65.109.70.111` (verified as `dft-db-hel1-5950x`);
  no database routing changed.
- `5.9.42.254` was treated as a non-public dedicated host: shallow read-only
  checks only, no DNS, certificate, public-API, traffic or PostgreSQL action.
- No cutover or production mutation was made, and this handoff stayed internal.
- No fix was applied: the registry start was routine maintenance, the stale
  monitor signals are standing or monitor-side defects, and the certificate
  blocker needs an ownership decision rather than a blind renewal.
- One requester-private Telegram escalation was sent to Seth van der Bijl
  covering the SkyBuyFly certificate deadlock, the `aipc-hel1-01` storage
  audit failure, the demo-ingress failures, the `pitchai-main` reserve margin,
  and the `aipc-fsn1-01` chronicle growth plus failed audit units.

## Recommended follow-ups

1. Break the `skybuyfly.pitchai.net` certificate deadlock before 2026-10-19:
   either serve `/.well-known/acme-challenge/` from the front door
   `aipc-hel1-01` for that webroot, move the lineage to the host DNS points at,
   or switch the lineage to DNS-01. Two hosts failed renewal on 2026-09-28.
2. Reclaim or expand storage on `aipc-hel1-01` - it is now below its own 100 GiB
   audit floor (100 GB free, 77%) and it is the public SkyBuyFly entry point.
3. Reclaim Docker images/build cache on `pitchai-main` before the 200 GiB
   builder reserve trips; the guard is 3.0 GiB above it and burn is 4-6 GiB/day.
   Repair `pitchai-potai-staging-release-cleanup`.
4. Have the demo-ingress owner look at `135.181.182.48`: `montrachet-demo`
   answers 500 and `aigenda-rules/readyz` reports
   `python_rule_runtime=false`. Second consecutive day.
5. Fix `container_health`'s include pattern so the intentionally-stopped
   `dft-worker` standby no longer pins the signal down (it has masked the real
   container state for 8 days), and repair the two `aipc-fsn1-01` audit units
   (`ci-runner-*` contract, `deploy-authorized-key-policy`) with server-ops.
