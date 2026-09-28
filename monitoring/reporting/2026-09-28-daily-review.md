# Daily monitoring review: 2026-09-28

## Decision

The monitor, dashboard, proxy, DNS, containers and the dedicated AIPC host are
healthy, and the external E2E lane is green in aggregate: 634 runs in the
window with **633 pass and one timeout that recovered on the next run**.
`nginx -t` passes, the registry certificate and manifest are good into
December, the ACME webroot and n8n/duplicate-lineage checks are as expected,
and `aipc-fsn1-01` is reachable with five healthy containers, zero restarts and
its runner VM pool live.

Two things keep the day off "all clear", and one of them is the same
customer-facing entry point as yesterday.

**`skybuyfly.pitchai.net` lost eight minutes of public service** on
2026-09-27 19:36:47-19:44:34Z (5 of 705 samples, 99.291%) while the staged
stack on the front door `aipc-hel1-01` was cut over: `aipc-shadow-stable`
started 19:44:31Z, `aipc-shadow-primary` 19:45:30Z, with nginx reloads at
19:44:18Z, 19:45:17Z and 19:46:16Z. The host did **not** reboot this time
(boot still 2026-09-26 04:32:23Z), so this is a deploy path that swaps the
public entry point without draining - the second distinct cause of a SkyBuyFly
dip in three days.

**`pitchai-main` capacity keeps deteriorating**: `/dev/md2` is at 88% with
209 GB free, swap is fully consumed for a seventh consecutive review, and the
builder-cache guard has stood down again with roughly 7.4 GiB of margin left
above its 200 GiB reserve.

The SkyBuyFly certificate is now 21 days out with certbot failing on every run,
the AIPC host's disk jumped 28% -> 37% in one day, and two internal demo lanes
had ~50-minute dips. No fix was applied in this lane; one requester-private
escalation was sent.

Live collection ran 2026-09-28T03:00-03:15Z.

## Enabled domains (24 h window, 705 samples each)

| Domain | OK / total | Availability | p95 HTTP | Median HTTP | Codes |
| --- | --- | --- | --- | --- | --- |
| `autopar.pitchai.net` | 705/705 | 100% | 64.0 ms | 18.2 ms | 200 |
| `afasask.gzb.nl` | 705/705 | 100% | 43.1 ms | 17.3 ms | 200 |
| `skybuyfly.pitchai.net` | 700/705 | **99.291%** | 160.8 ms | 112.2 ms | 200, 502, null |
| `deplanbook.com` | 705/705 | 100% | 8.1 ms | 3.7 ms | 200 |
| `cms.deplanbook.com` | 705/705 | 100% | 186.0 ms | 75.1 ms | 200 |
| `dpb.pitchai.net` | 705/705 | 100% | 52.5 ms | 14.1 ms | 200 |
| `hetcis.nl` | 705/705 | 100% | 70.0 ms | 60.4 ms | 200 |

`stable.skybuyfly.pitchai.net` mirrors the public lane exactly (700/705,
99.291%). Per-domain availability and p95 above are derived from
`/data/state.json` with the dashboard's own rules; the dashboard UI itself
needs a session token, so the aggregate `daily_status` panel was not read
directly this morning.

Two internal demo lanes dipped inside the window and both recovered on their
own:

| Domain | OK / total | Availability | Failure | Window (UTC) |
| --- | --- | --- | --- | --- |
| `aigenda-rules.demos.pitchai.net` | 678/705 | 96.17% | 503 | 10:22:04 - 11:12:53 |
| `montrachet-demo.pitchai.net` | 679/705 | 96.312% | 500 | 10:24:01 - 11:12:53 |

## SkyBuyFly: eight-minute public outage during a front-door cutover

Both SkyBuyFly hostnames failed and recovered together:

| Time (UTC) | `skybuyfly.pitchai.net` | `stable.skybuyfly.pitchai.net` |
| --- | --- | --- |
| 19:36:47 | 502 after 10 065 ms | 502 |
| 19:38:53 | 502 after 10 011 ms | 502 |
| 19:40:48 | timeout after 15 048 ms | 502 |
| 19:42:43 | 502 after 7 ms | 502 |
| 19:44:34 | 200, browser 11 992 ms | 200, browser 10 504 ms |

Monitor events: `domain_down` for both names at 19:36:47Z with
`telegram_alert=true`, a `proxy_degraded` event in the same cycle
(`upstream_issues=1`, `pct_502_504=0.0`, `upstream_events=0`), then `domain_up`
and `proxy_recovered` at 19:44:34Z.

**Cause: a staged-stack rollout on `aipc-hel1-01`, not a reboot.** The host has
been up since 2026-09-26 04:32:23Z, so yesterday's unattended-upgrade reboot did
not repeat. What the container start times show instead:

| Container | Started (UTC) |
| --- | --- |
| `aipc-shadow-stable` | 2026-09-27 19:44:31 |
| `aipc-shadow-primary` | 2026-09-27 19:45:30 |

and nginx on that host reloaded at 19:44:18Z, 19:45:17Z (twice) and 19:46:16Z.
The public 502s therefore bracket the window in which the previously serving
container had been replaced but the new one was not yet accepting on the
upstream port - a cutover with no drain, on the address that public DNS
actually points at (`157.180.101.33`, unchanged this morning).

Current state: pinned probe against `37.27.67.52` returns **200 in 0.159 s**,
and both `157.180.101.33` and `37.27.67.52` serve the same certificate
(`CN=skybuyfly.pitchai.net`, Let's Encrypt `YE1`, valid to 2026-10-19). Public
traffic continues to be evaluated against `37.27.67.52` per the topology
contract; no DNS, certificate or routing change was made.

## Signals

`state.json` is schema **v6**, last written 2026-09-28T03:00:08Z (about two
minutes before collection), with `state_write_fail_streak=0` and cycle times of
113-124 s. `monitoring.pitchai.net/health` returns `ok:true`.

| Signal | Bad / total | Latest | Reading |
| --- | --- | --- | --- |
| `browser` | 0/705 | ok | `degraded_active=false`, no launch failures |
| `dns` | 0/89 | ok | 88 domains resolved |
| `proxy` | 5/705 | ok | degraded only during the SkyBuyFly cutover; `pct_502_504` 0.0% |
| `container_health` | 705/705 | **failed** | `dft-worker-green` still `Exited (0)` since 2026-09-21 |
| `host_health` | 705/705 | **failed** | memory 85.5%, swap 100.0%, 3 violations |
| `tls` | 23/23 | **failed** | 3 failures per cycle on Telegram-excluded domains |
| `performance` | 705/705 | failed | 44 slow domains |
| `red` | 705/705 | failed | 40 violations |
| `slo` | 705/705 | failed | 4 violations |
| `meta` | 705/705 | failed | 1 standing reason, 113.5 s cycle |

The standing set is unchanged in composition from yesterday and is now bounded:
`container_health` is the `dft-worker-green` false positive (exited cleanly
seven days ago; no container is unhealthy or restarting - `docker ps` filtered
for both is empty), and `tls` covers the three domains the monitor already
routes away from Telegram (`registry.pitchai.net`, `jeff-codex-voice`,
`jeff-work-inbox`) whose certificates are verified valid below. `performance`,
`red`, `slo` and `meta` are the long-standing slow-domain/render-time baseline
plus the policy-down routes, with the same counts as yesterday (44 slow, 40 red,
4 slo).

## Host: pitchai-main disk, memory and swap

| Metric | Now | Yesterday | Two days ago |
| --- | --- | --- | --- |
| `/dev/md2` used | **88%** (209 GB free) | 88% (212 GB free) | 87% (217 GB free) |
| Swap used | **32 734 / 32 734 MiB (100%)** | 100% | 100% |
| Memory available | 8 633 MiB of 64 039 | 9 466 MiB | - |

Docker storage: `Images 210 GB / 379 images / 150.6 GB reclaimable`,
`Build Cache 104.1 GB / 91.4 GB reclaimable`, `Local Volumes 128.2 GB /
27.38 GB reclaimable`, containers 12 GB of 199. Inodes are comfortable at 12%.

Neither guarded reclamation path fired. `pitchai-production-builder-cache-cleanup`
ran at 03:40:20 CEST with `available_before=222722965504` against
`reserve_bytes=214748364800` and concluded `status=reserve-satisfied`, leaving
about **7.4 GiB** of margin - down from 10.6 GiB yesterday.
`pitchai-potai-staging-release-cleanup.service` failed again at 04:42:02 CEST
with the same retention-floor refusal (`retained=0 minimum=20 total=24
candidates=24`). `logrotate.service` completed successfully for a fourth
consecutive night (`Result=success`, `ExecMainStatus=0`). Nothing was deleted,
pruned, rotated or restarted from this lane.

## Nginx, proxy and logs

`nginx -t` passes (with the standing conflicting-server-name warnings for
`pitchai.net`, `www.pitchai.net`, `chat-staging.pitchai.net`). Since the 00:00
CEST rotation the error log holds **499** `connect() failed` entries for
`support.pitchai.net` and **455** for `dashboards.pitchai.net` (both still dead
upstreams on `localhost:8420` / `:3200`), plus the recurring **102-line
`[emerg] Permission denied`** burst on
`/var/log/pitchai-nginx-events-bus/error.log` at rotation time. No `no live
upstreams`, `upstream prematurely closed` or `upstream sent too big header`
entries anywhere, and zero `skybuyfly` entries in this host's error log - the
evening failures came from the front door, not from `pitchai-main`. Access-log
50x for the day is 995 `502` and no `504`, dominated by the monitoring bot's own
probes of the policy-down routes.

The proxy signal was clean for every cycle except the five during the cutover.

## TLS, ACME and certificates

- `registry.pitchai.net:5000` direct TLS serves `CN=registry.pitchai.net` from
  Let's Encrypt `YE1`, valid 2026-09-21 to **2026-12-20**, and
  `docker manifest inspect registry.pitchai.net:5000/pitchai/codex-runner:latest`
  succeeds, so auto-dispatch is intact.
- **`skybuyfly.pitchai.net` is now at 21 days** (expires 2026-10-19T03:35:18Z)
  and `certbot.service` failed twice inside the window - 2026-09-27 21:48:33
  CEST and 2026-09-28 03:27:44 CEST - both times on that single lineage
  (`Some challenges have failed`, `1 renew failure(s)`). The same certificate is
  served from `157.180.101.33` and from `37.27.67.52`, while DNS sends the ACME
  challenge to the front door and `pitchai-main` holds the lineage; that split
  is still unresolved. `stable.skybuyfly.pitchai.net` is fine at 51 days.
- 49 lineages present, none with a `-0001` suffix; the removed
  `afasask.gzb.nl-0001` has not returned and `afasask.gzb.nl` is valid for 56
  days.
- ACME webroot routing for `staging.formatief-toetsen.pitchai.net` is intact:
a missing challenge file returns **404 from the webroot on both HTTP and
HTTPS**, not an auth redirect.
- `n8n.pitchai.net` shows no reappearance: no enabled site, the retired site
  files remain under `sites-disabled`, the lineage is absent, and the host
  answers 301/400 from the default vhost rather than an application.

## Dedicated AIPC host: `aipc-fsn1-01` (5.9.42.254)

Reachable over SSH (read-only, `BatchMode`); up 2 days 22:30, load 0.91 on 12
CPUs.

| Area | Evidence |
| --- | --- |
| Disk | `/dev/md2` **37%** (323 GB used, 552 GB free) - **was 28% / 243 GB yesterday** |
| Inodes | 6% of 61.4 M |
| Memory / swap | 13 GiB of 125 GiB used, 111 GiB available, swap 768 KiB of 16 GiB |
| Journal | 1.8 GB archived + active (was 1.7 GB) |
| Docker | 116 images / 55.2 GB (23.33 GB reclaimable), 16 containers (5 active), 0 volumes |
| Containers | 5 running and healthy with **0 restarts** (`aipc-shadow-primary`, `aipc-shadow-stable`, `aipc-pgbouncer`, `aipc-meilisearch`, `aipc-qdrant`); 10 `aipc-*-staged` in `created` (prepared, never started); `aipc-crawler-staged` is `created` with no logs and no restart loop |
| Failed units | 2 - `aipc-docker-maintenance.service`, `aipc-host-audit.service` |
| Runner | `aipc-ci-runner-pool-vm.service` **active**, `NRestarts=0`, 2.90 GB RSS; the pool VM is a `qemu-system-x86_64` process with 8 vCPU / 32 GiB on `aipc-runners.slice`, isolated from the AIPC stack |

**New watch item - the day-over-day disk jump is the runner pool's own disk
image.** Usage grew 80 GB in 24 h (243 -> 323 GB), concentrated in `/var/lib`
(176 GB) of which `/var/lib/aipc-ci-runner` is 119 GB: a live
`pool/root.qcow2` of 48.6 GB rewritten at 03:02 today (the running runner VM),
plus **43 GB of stale July candidate-history VM images** (eight
`candidate-history/*` trees and `failed-bootstrap-20260729T1557Z`, all dated
2026-07-29). At 552 GB free this is not urgent, but at today's rate it is a
week-scale constraint, and clearing the July history is a server-ops decision -
not something this lane may delete.

Runner availability, isolation and resource suitability are confirmed by the
VM-pool instrument rather than the runbook's `actions.runner.*` probe, which
this host does not use.

## SkyBuyFly front door: `aipc-hel1-01` (157.180.101.33)

Read-only diagnostic for incident attribution: up 1 day 22:29 (boot
2026-09-26 04:32:23Z), load 2.46, `/dev/md2` 77% (102 GB free), one failed unit
(`certbot.service`). The 14 AIPC containers are healthy after the 19:44-19:45Z
cutover. DNS for `skybuyfly.pitchai.net` still resolves here rather than to the
contract address `37.27.67.52`; recorded as an escalation signal, not as
permission to change DNS.

## External E2E

Registry summary: `ok=true`, **36 tests**, `failing_tests=2`. Both aggregate
failures are the disabled historical
`dft_prod_exam_import_2doc_sla_daily_e2e` rows (last run May 2026), and no
enabled test has a non-pass `last_status`.

Runs in the 24 h window: **634 total, 633 pass, 1 fail**.

| Enabled test | Latest | Streak | Elapsed |
| --- | --- | --- | --- |
| `afasask_demo_codex_fast_ok` | pass | 100 | 8 736 ms |
| `afasask_production_codex_medium_synthetic_ok` | pass | 100 | 23 089 ms |
| `deplanbook_cms_home_smoke_py` | pass | 2 294 | 571 ms |
| `deplanbook_cms_on_demand_translation_py` | pass | 100 | 890 ms |
| three `zz_disabled_temp_*` | pass (February records) | 1 | stale inventory entries |

The single failure is the enabled
`deplanbook_cms_on_demand_translation_py` at 2026-09-27T18:08:04Z:
`TimeoutError: Page.wait_for_function: Timeout 90000ms exceeded` against
`https://cms.deplanbook.com/?tl=ja` after 90 575 ms. It recovered on the next
run and the test is currently at a 100-run success streak, so this is a
one-failure blip rather than a pattern - worth naming because it is the only
enabled-test failure in the window.

The reminder's named `afasask_gzb_codex_medium_ok_daily` remains `enabled=0`
with its 2026-09-03 retirement reason; its active replacement,
`afasask_production_codex_medium_synthetic_ok`, passed every run in the window.
The overnight AFASAsk failure pattern of 2026-09-22/24/25 has not recurred.

## Topology compliance and actions

- Public SkyBuyFly web/API traffic was evaluated against `37.27.67.52` only
  (pinned probe 200 in 0.159 s), with the DNS answer recorded separately.
- PostgreSQL remains assigned to `65.109.70.111`; no database routing changed.
- `5.9.42.254` was treated as a non-public dedicated host: shallow read-only
  checks only, no DNS, certificate, public-API, traffic or PostgreSQL action.
- No cutover or production mutation was made, and this handoff stayed internal.
- No fix was applied in this lane. One requester-private Telegram escalation was
  sent to Seth van der Bijl covering the SkyBuyFly cutover outage, the
  `pitchai-main` capacity position, the SkyBuyFly certificate deadlock, the AIPC
  runner disk growth, and the single E2E timeout.

## Recommended follow-ups

1. Give the `aipc-hel1-01` staged rollout a drain/health gate before it swaps
   the container that is serving `skybuyfly.pitchai.net`; today's eight-minute
   outage and yesterday's auto-reboot are two different mechanisms producing
   the same customer-visible dip.
2. Renew or re-home the `skybuyfly.pitchai.net` certificate before 2026-10-19
   and reconcile the ACME account/challenge split between `pitchai-main` and the
   front door.
3. Reclaim Docker image/build-cache storage on `pitchai-main` before the 200 GiB
   reserve trips - the guard is now ~7.4 GiB above it and consumption runs about
   4-5 GiB/day - and repair `pitchai-potai-staging-release-cleanup`.
4. Review the `aipc-fsn1-01` runner pool images with server-ops: 43 GB of July
   `candidate-history` plus a 48.6 GB live `root.qcow2` now dominate the host's
   disk growth.
