# Daily monitoring review: 2026-09-22

## Decision

The public websites, monitor, proxy, DNS and dashboard are ready for the day.
Two findings need a human owner rather than a monitoring-lane fix: the
`skybuyfly.pitchai.net` certificate can no longer renew from either lane and
expires in 27 days, and the nightly `logrotate` failure now has a confirmed
root cause with a second-order nginx logging effect. `pitchai-main` is at 78%
disk with swap fully consumed, so both disks and swap pressure are tracked
rather than repaired from this lane. No fix was applied; one
requester-private escalation was sent.

This review covers the window since the 2026-09-20 review; the 2026-09-21 fire
was skipped, so the rolling window is wider than the usual single morning.
Live collection ran 2026-09-22T03:00-03:45Z.

## Core domains (rolling window, 775 samples each)

All eight monitored domains are at 100% effective availability with healthy
p95 HTTP latency:

| Domain | OK / total | Availability | p95 HTTP |
| --- | --- | --- | --- |
| `autopar.pitchai.net` | 775/775 | 100% | 52 ms |
| `afasask.gzb.nl` | 775/775 | 100% | 36 ms |
| `skybuyfly.pitchai.net` | 775/775 | 100% | 155 ms |
| `deplanbook.com` | 775/775 | 100% | 8 ms |
| `cms.deplanbook.com` | 775/775 | 100% | 142 ms |
| `dpb.pitchai.net` | 775/775 | 100% | 51 ms |
| `hetcis.nl` | 775/775 | 100% | 73 ms |
| `afasask.pitchai.net` | 775/775 | 100% | 64 ms |

`cms.deplanbook.com` is fully recovered from the 2026-09-19 incident window.
`afasask.pitchai.net` is still sampled by the monitor although the reminder
lists it as disabled; the enabled/disabled drift is unchanged.

## Signals

`state.json` is schema v6, refreshed 2026-09-22T03:07:22Z (61 s old against a
60 s interval, stale threshold 180 s) with `state_write_fail_streak=0`.

| Signal | Bad / total | Latest | Reading |
| --- | --- | --- | --- |
| `browser` | 0/776 | ok | no launch failures, `degraded_active=false` |
| `dns` | 0/91 | ok | — |
| `proxy` | 0/776 | ok | 0.0% 502/504 across 512 access lines |
| `container_health` | 530/776 | **failed** | fail streak 531 |
| `host_health` | 776/776 | **failed** | swap 100.0%, 1 violation |
| `performance` | 776/776 | failed | 44 slow domains |
| `red` | 776/776 | failed | 41 violations |
| `slo` | 776/776 | failed | 6 violations |
| `tls` | 24/24 | **failed** | 3 failures, fail streak 353 |
| `meta` | 776/776 | failed | 1 reason, 163 s cycle |

`performance`, `red`, `slo` and `meta` sit at the same long-standing levels
recorded in the 2026-09-20 review (45→44 slow, 56→41 red, 6→6 SLO) and the
meta cycle remains slower than the 60 s interval; none of them moved in a way
that indicates a new break. `browser`, `dns` and `proxy` are clean, so the
website-facing paths are unaffected.

Thirty events were recorded in the window: 14 `domain_down`, 12 `domain_up`,
2 `api_contract_degraded`, 1 `api_contract_recovered` and 1
`container_health_degraded`. Three short flaps (staging.formatief-toetsen,
aigenda-rules.demos, stable.skybuyfly) all recovered within minutes. Two
domains are still open:

- `studentenreisproduct.demos.pitchai.net` — 502 since 2026-09-21T13:18Z,
  321/344 samples; demo route, not in the enabled production set.
- `wrist-vault.135-181-182-48.sslip.io` — 502 since 2026-09-21T20:57Z,
  74.1% availability; carries an explicit `dashboard-only` pre-launch policy
  and is configured not to page until an operational handoff exists.

## Container health

The monitor has been red on `container_health` for 531 cycles (roughly 16
hours), and the cause is a single container name rather than a failing
service. `dft-worker-green` **exited 0** at about 2026-09-21T12:42Z when the
DFT lane rolled over to `dft-worker` and `dft-web-app-green`, both of which
are up. The monitor's include pattern
`^dft-worker(?:-green|-staging|-staging-spend-enabled)?$` still matches the
retired green container, so a completed blue/green swap reads as an unhealthy
container indefinitely. `dft-worker-staging` has also gone entirely.

This is a monitor-signal accuracy problem created by a real host state change,
not a customer-facing outage, and the retired container's ownership sits with
the DFT lane. Restarting or removing it from this lane would touch another
team's runtime, so it is escalated for coordination instead.

`pitchai-main` runs 117 of 138 containers; the rest are exited or staged.
Many `afasask-quick-chat-rollback-*` and `quickchat-waddinxveen-luna-*`
containers show `Exited (137)` from normal rollback swaps on 2026-09-21. No
container is in a restart loop, and there are no `aipc-*` or
`ai_price_crawler-*` containers on this host.

## Dashboard and external E2E

Dashboard summary: `ok=true`, 82 enabled domains, 69 healthy, 13 down of
which 8 are documented `expected_down`, leaving 5 alertable. Freshness is
`fresh` at 62 s. Degraded signals listed by the dashboard are `host_health`,
`performance`, `slo`, `red`, `tls`, `container_health` and `meta`.

The down list is the same standing set recorded in earlier reviews —
`dashboards.pitchai.net` and `support.pitchai.net` (active vhosts pointing at
`127.0.0.1:3200` and `127.0.0.1:8420` with no listener), `registry.pitchai.net`
and `agentcloud.pitchai.net` (HTTP probe), `cursussen.pitchai.net`,
`whatsapp.pitchai.net` (503 from the long-standing QR expiry), and the
`jeff-*` routes. `dispatch.pitchai.net` appears in the down list only through
its API contract (`fail_streak` 6365); its website is 100% available at
775/775. `pitchai-main` also carries a stale `dispatch.pitchai.net` vhost
proxying to `127.0.0.1:8088`, which has no listener here because dispatch runs
on `135.181.182.48`; public DNS points there, where the site returns 302 in
50 ms.

External E2E: `ok=true`, 36 tests, 7 enabled, `failing_tests=2` (both are
disabled historical `dft_prod_exam_import_2doc_sla_daily_e2e` rows). No
enabled test has a non-pass `last_status`. The Codex smoke tests are green:
`afasask_demo_codex_fast_ok` passed in 10.7 s with a 118-run success streak,
and `afasask_production_codex_medium_synthetic_ok` passed in 11.8 s with a
131-run success streak. An `infra_degraded` marker seen on
`afasask_demo_codex_fast_ok` early in this run cleared by 03:08Z and was
transient. The reminder's `afasask_gzb_codex_medium_ok_daily` is still
`enabled=0` in the registry with no recent run — the same registry drift as
previous reviews, with the production medium smoke covered by the synthetic
test above.

## Host: pitchai-main

Uptime 204 days, load 13.7 on 32 CPUs (0.43 per CPU), memory 39/62 GB used
with 22 GB available. Memory rose about 8 GB since the 2026-09-20 review.

**Swap is fully consumed**: 31 GiB of 32 GiB used with 120 KiB free, the same
state as the 2026-09-20 reading of 99.973%. This is sustained pressure well
above the 90% escalation threshold even though nothing is currently failing,
and it is the reason `host_health` reads `ok=0`.

**Disk is the growth risk**: `/dev/md2` is at 78% with 363 GB free, down from
73% / 458 GB two days ago, roughly 95 GB in two days. Docker storage accounts
for most of it: `/var/lib/docker` is 525 GB, with 118.9 GB of images (58 GB
reclaimable), 128 GB of volumes (27 GB reclaimable) and 44.4 GB of build cache
(31.6 GB reclaimable) — about 117 GB reclaimable in total. `/var/log` is
6.7 GB and journald holds 3.9 GB. Nothing here is near full yet, and none of
it was deleted, trimmed or pruned from this lane; reclaiming it is a
server-ops decision because the volumes may hold live data.

## Proxy and nginx logs

`nginx -t` passes (one pre-existing duplicate `server_name` warning for
`chat-staging.pitchai.net`). The nginx vhost set has not regressed.

Over the full 24 h (combining `error.log.1` with `error.log`, which was
rotated at midnight): 3073 `connect() failed`, 42 `upstream prematurely
closed`, 4 `upstream timed out`, 72 `[emerg]`, and zero `no live upstreams`
and zero `upstream sent too big header`. The connect failures are dominated
by the two known dead dashboard-only upstreams — `dashboards.pitchai.net`
(1598) and `support.pitchai.net` (1460) — with the remainder a handful of
scanner paths. Both were probed directly this run and still return 502 from
their localhost upstreams on ports 3200 and 8420.

The more interesting signal is the 72 `[emerg]` lines, which connect to the
next section.

## logrotate and the breakglass events bus

`logrotate.service` failed for the third consecutive night, at
2026-09-20T00:00Z, 2026-09-21T00:00Z and 2026-09-22T00:00Z, each with
`status=1`. The root cause is now identified from the journal:

```
error running shared prerotate script for '/var/log/nginx/breakglass-events.jsonl'
Job for pitchai-breakglass-events-bus.service failed because the control process exited with error code.
```

The shared prerotate script restarts `pitchai-breakglass-events-bus.service`,
which is itself permanently failed and restarts every few minutes
(`NRestarts=0`, `ExecMainStatus=1`, last attempt 2026-09-22T05:06:42Z). The
script's nonzero exit aborts the whole logrotate run, so rotation stops
part-way through the run.

The second-order effect is that `/var/log/pitchai-nginx-events-bus` is
recreated by rotation as `root:root 700`, while the `error.log` inside it is
`www-data:root 600`. `www-data` can no longer traverse the directory, so nginx
workers emit
`[emerg] open() "/var/log/pitchai-nginx-events-bus/error.log" failed (13: Permission denied)`
— 72 of these in 24 h, clustered at 00:00:03 after each rotation.

This was not repaired from the monitoring lane. The failing unit feeds a
content-free security audit pipeline, and the directory mode may be
intentional, so both the unit repair and any ownership change are escalated
for an owner decision rather than blind-fixed.

## TLS, ACME and certificates

`registry.pitchai.net:5000` direct TLS is healthy and freshly renewed by
`pitchai-main` on 2026-09-21T15:41Z, valid to 2026-12-20, with
`docker manifest inspect` succeeding. This is the change from the previous
review, where the lineage expired 2026-10-21.

ACME challenge routing behaves correctly on the staging vhost patched on
2026-05-13: `staging.formatief-toetsen.pitchai.net` returns 404 for
`/.well-known/acme-challenge/` probes on both HTTP and HTTPS rather than
redirecting to app auth, so the webroot is still serving and the deploy script
has not overwritten the location.

`n8n.pitchai.net` remains decommissioned: no enabled site, no certbot lineage.
The removed `afasask.gzb.nl-0001` duplicate has not reappeared, and the active
`afasask.gzb.nl` lineage is valid for 62 days. No certificate lineage other
than the one below is inside 30 days.

### SkyBuyFly certificate cannot renew (expires 2026-10-19)

Both front doors still serve the same lineage, serial
`59a688686827c981a7e74fbf73a6e93dbd0`, `notAfter` **2026-10-19T03:35:18Z** —
27 days out — with no renewal since 2026-07-21.

`pitchai-main` failed again at 2026-09-21T03:36Z and 2026-09-21T18:39Z with
`Some challenges have failed`. A `certbot renew --dry-run` run this morning
pinned the mechanism exactly:

```
Detail: 157.180.101.33: Invalid response from
http://skybuyfly.pitchai.net/.well-known/acme-challenge/<token>: 404
```

Public DNS for `skybuyfly.pitchai.net` resolves to `157.180.101.33` (the AIPC
HEL1 front door), so the HTTP-01 challenge is answered there, not by
`pitchai-main`. Certbot on `pitchai-main` writes the token into its own nginx
webroot, HEL1 returns 404 for it, and the authorization fails. The reverse
probe confirms the split: HEL1 and `pitchai-main` both return 404 for an
unknown ACME path, and the challenge only fails on the real token.

HEL1's own renewal fails for an unrelated reason: its ACME account directory
`acme-v01.api.letsencrypt.org/directory/61b97124...` no longer exists. Its last
failure was 2026-09-22T01:37:50Z.

So the authoritative ACME host is HEL1 by DNS, but HEL1's certbot account is
broken, and the host that still holds a working account cannot answer the
challenge. Fixing this means repairing an ACME account and reconciling where
`skybuyfly.pitchai.net` is authoritative — DNS, certificate and public-routing
changes that this review lane is explicitly not authorized to make. Pinned
probes against the topology contract address `37.27.67.52` return 200 for both
`/` and `/api/health` with a matching CN, so the site is serving correctly
today; the risk is what happens on 2026-10-19.

## Dedicated host: aipc-fsn1-01 (5.9.42.254)

Reachable and healthy, and now much quieter than at the last review. Uptime 9
days 22 h (the host has rebooted since the 2026-09-20 reading of 14 d 16 h),
load 0.05/0.10/0.09 on 12 CPUs, memory 7.6/125 GB with swap completely unused.

- **Disk**: `/dev/md2` 22% with 687 GB free; `/dev/sda1` (`/srv/aipc-cold`)
  effectively empty at 1.8 TB free; inodes 3%. No disk or inode pressure.
- **Journal**: 1.5 GB on disk, inside the journald cap, no unexpected growth.
- **Failed units**: two, both one-shot maintenance jobs —
  `aipc-docker-maintenance.service` and `aipc-host-audit.service`. Down from
  seven at the previous review, and neither serves traffic.
- **Containers**: all running AIPC containers are healthy with zero restarts —
  `aipc-shadow-primary`, `aipc-shadow-stable`, `aipc-pgbouncer`,
  `aipc-meilisearch`, `aipc-qdrant`. Ten `aipc-*-staged` containers sit in
  `Created` state with zero restarts, which is the expected shape for a staged
  deployment set that has not been started. No restart loops, no missing-env
  or database-host resolution errors. There are still no `ai_price_crawler-*`
  containers on this host.
- **Docker storage**: 55.2 GB images (23.3 GB reclaimable), 78.6 MB
  containers, no volumes or build cache. Nothing near a limit.
- **Resource headroom**: `docker stats` shows the two shadow apps at 1.7 GB
  each against an 8 GB limit and under 1% CPU — ample room for runner
  workloads.
- **Isolated GitHub runner**: still **no `actions.runner.*` unit exists**.
  This is the same inventory gap recorded at the previous review and on
  topology task `e13a891e-7aed-4225-a370-92da1d4ebdd3`; the host has 12 CPUs
  and 118 GB of available memory, so it is resource-suitable once a runner is
  provisioned. Missing evidence is not proof of health, so this stays open
  for server-ops.

Topology contract confirmed unchanged: public SkyBuyFly is evaluated against
`37.27.67.52`; PostgreSQL remains on `65.109.70.111` (port reachable);
`5.9.42.254` stayed non-public and was not treated as a DNS, certificate,
API, traffic or PostgreSQL target. No cutover or production mutation was
made.

`pitchai-dev` (`135.181.182.48`) still refuses key-based SSH
(`Permission denied (publickey)`), so its disk headroom could not be verified
from this lane even though public `dispatch.pitchai.net` serves correctly from
it. Recorded as missing authorization, not as health.

## Actions

No fix was applied and nothing was deleted, truncated, pruned or restarted.
The certificate, logrotate/events-bus, container and disk findings all either
touch another team's runtime or require DNS, certificate or account changes
that this lane is not authorized to make.

One requester-private Telegram escalation was sent to Seth van der Bijl
covering the SkyBuyFly renewal deadlock, the confirmed logrotate root cause,
sustained 100% swap plus the 95 GB two-day disk growth on `pitchai-main`, the
`dft-worker-green` monitor red, and the refused `pitchai-dev` SSH access, each
with a recommended next action. No other message was sent.

## Remaining work

- Repair the HEL1 ACME account and settle where `skybuyfly.pitchai.net` is
  authoritative before 2026-10-19. Highest priority.
- Repair `pitchai-breakglass-events-bus.service` and confirm the intended
  mode/ownership of `/var/log/pitchai-nginx-events-bus` so nightly rotation
  stops aborting and nginx stops emitting `[emerg]`.
- Decide with the DFT lane how a retired blue/green worker container should be
  represented, so `container_health` does not stay red on a completed swap.
- Reclaim the ~117 GB of reclaimable Docker storage on `pitchai-main` under
  server-ops review, and confirm the `md2` growth rate over the next review.
- Restore read-only SSH access to `pitchai-dev` to close the disk-headroom
  verification gap.
- Provision the isolated GitHub runner on `aipc-fsn1-01` and reconcile the
  AIPC container inventory against topology.
- Standing items unchanged: topology versus DNS reconciliation for
  `skybuyfly.pitchai.net`, the `dispatch.pitchai.net` API contract streak,
  the monitor meta cycle, the `whatsapp.pitchai.net` QR expiry, the
  `dashboards.pitchai.net` and `support.pitchai.net` dead upstreams, and the
  enabled/disabled drift for `afasask.pitchai.net` and
  `afasask_gzb_codex_medium_ok_daily`.
