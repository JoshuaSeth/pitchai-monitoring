# Daily monitoring review: 2026-09-23

## Decision

Everything that serves customers is working: all seven enabled domains are
reachable, the monitor is fresh, DNS, browser and proxy signals are healthy,
the dashboard is green and the certificate story is unchanged. But the day has
four findings that need a human owner, and two of them are new since
2026-09-22. No fix was applied; one requester-private escalation was sent.

The two new findings are a three-hour AFASAsk Codex outage that the aggregate
status never reported, and a disk trajectory on `pitchai-main` that lost 85 GB
in a day while the jobs meant to reclaim it are failing. The other two are the
carried-forward SkyBuyFly renewal deadlock and the root cause of the nightly
`logrotate` failure, which is now pinned to a single malformed line.

Live collection ran 2026-09-23T07:24-07:40Z. The rolling window covers since
the 2026-09-22 review.

## Enabled domains (rolling window, 765 samples each)

| Domain | OK / total | Availability | p95 HTTP |
| --- | --- | --- | --- |
| `autopar.pitchai.net` | 765/765 | 100% | 54 ms |
| `afasask.gzb.nl` | 765/765 | 100% | 30 ms |
| `skybuyfly.pitchai.net` | 756/765 | 98.824% | 162 ms |
| `deplanbook.com` | 765/765 | 100% | 9 ms |
| `cms.deplanbook.com` | 765/765 | 100% | 165 ms |
| `dpb.pitchai.net` | 765/765 | 100% | 51 ms |
| `hetcis.nl` | 765/765 | 100% | 70 ms |

`skybuyfly.pitchai.net` dropped below 100% for the first time in the recent
record, on two `ReadTimeout` failures at 12:34Z and 20:01Z and a correlated
502 burst. It is serving correctly now.

Dashboard-only and demo routes moved more sharply:
`montrachet-demo.pitchai.net` 98.196% → **68.277%** on repeated 500s,
`aigenda-rules.demos.pitchai.net` 95.490% → **56.789%** on repeated 503s and
one browser-check failure, `stable.skybuyfly.pitchai.net` 99.098% → 98.303%,
and `wrist-vault.135-181-182-48.sslip.io` 74.4% → **0%** (502 since
2026-09-22T20:57Z, `dashboard-only` policy, no paging by design).

`aigenda-rules.demos.pitchai.net` is the one domain currently open: down since
2026-09-23T07:22Z with a 503 and a `critical` alert policy. Forty-one events
were recorded in the window: 17 `domain_down`, 16 `domain_up`, 3
`api_contract_degraded`, 3 `api_contract_recovered`, 1 `proxy_degraded` and 1
`proxy_recovered`.

## AFASAsk Codex outage, 2026-09-22 17:52-20:47Z

Both Codex smoke tests failed repeatedly over roughly three hours and then
recovered:

| Time (UTC) | Test | Status | Elapsed | Error |
| --- | --- | --- | --- | --- |
| 17:54 | `afasask_production_codex_medium_synthetic_ok` | fail | 241 s | `TimeoutError Page.wait_for_function: Timeout 240000ms exceeded` |
| 17:54 | `afasask_demo_codex_fast_ok` | fail | 1.1 s | `afasask_demo_codex_canary_failed_marker: ❌ mislukt` |
| 18:29 | both | fail | 241 s / 1.1 s | same pair of errors |
| 19:03 | both | fail | 241 s / 1.2 s | same pair of errors |
| 19:34 | `afasask_demo_codex_fast_ok` | fail | 1.1 s | `❌ mislukt` |
| 19:38 | `afasask_production_codex_medium_synthetic_ok` | fail | 241 s | 240 s timeout |
| 20:04 | `afasask_demo_codex_fast_ok` | fail | 1.3 s | `❌ mislukt` |
| 20:12 | `afasask_production_codex_medium_synthetic_ok` | fail | 241 s | 240 s timeout |
| 20:35 | `afasask_demo_codex_fast_ok` | fail | 6.6 s | `❌ mislukt` |
| 20:47 | `afasask_production_codex_medium_synthetic_ok` | fail | 241 s | 240 s timeout |

The pattern matters. The fast canary failed within about a second on the
`mislukt` marker, while the medium run hung until its 240-second ceiling. That
is the signature of the Codex path being unavailable rather than the page being
slow, and it lines up with the AFASAsk API contract degrading at 17:52Z and
recovering at 20:52Z.

The monitor never paged on this. `failing_tests=2` stayed pointed at the
disabled historical DFT rows, the aggregate `ok` stayed true, and the enabled
tests' `success_streak` simply reset to 20 and 21 — which is the only trace
left in the summary view. Reading the raw run history is what surfaced it. Both
tests have passed every run since, and the medium test currently shows a
20-run success streak.

The same window produced a `proxy_degraded` event at 20:04Z that recovered at
20:13Z: four consecutive samples with `upstream_issue_count=1` at 20:04, 20:06,
20:08 and 20:10, all with `pct_502_504` at 0.0% and normal access volume
(543-585 lines per cycle). The `skybuyfly.pitchai.net` 502 and
`stable.skybuyfly.pitchai.net` ReadTimeout at 20:01Z sit immediately in front
of it, so these look like one correlated SkyBuyFly-side event rather than
independent faults.

## Signals

`state.json` is schema v6, refreshed 2026-09-23T07:25:00Z, 84 seconds old
against a 60-second interval with a 180-second stale threshold, so freshness is
`fresh` and `state_write_fail_streak` is 0.

| Signal | Bad / total | Latest | Reading |
| --- | --- | --- | --- |
| `browser` | 0/766 | ok | no launch failures, `degraded_active=false` |
| `dns` | 0/90 | ok | — |
| `proxy` | 5/766 | ok | four upstream-issue samples during the 20:04-20:13Z event |
| `container_health` | 766/766 | **failed** | unchanged, see below |
| `host_health` | 766/766 | **failed** | memory 75.56%, swap 100%, 1 violation |
| `tls` | 23/23 | **failed** | 3 failures |
| `performance` | 766/766 | failed | 41 slow domains (was 44) |
| `red` | 766/766 | failed | 42 violations (was 41) |
| `slo` | 766/766 | failed | 6 violations |
| `meta` | 766/766 | failed | 1 reason, 150 s cycle |

The sustained-failure signals are the same set as yesterday, and the
`container_health` cause is unchanged: `dft-worker-green` is still `Exited (0)`
43 hours after the DFT blue/green rollover and still matches the monitor's
include pattern. `dft-worker` and `dft-web-app-green` are both up. Nothing in
that lane was touched.

## Host: pitchai-main disk

`/dev/md2` is at **84% with 278 GB free**, down from 73% and 458 GB on
2026-09-20 and 78% and 363 GB on 2026-09-22. That is 85 GB lost in about 28
hours and 180 GB in three days. Sampling inside this review showed the free
space oscillating in a narrow band around 297.6 GB over six minutes
(297.59 → 297.77 → 297.74 GB), so the loss is bursty rather than continuous —
it tracks deploy and build activity, not a steady leak.

At the observed day-over-day rate there are roughly three to four days of
headroom. That is the reason to escalate today rather than at the next review.
Nothing was deleted, trimmed or pruned from this lane.

What is holding the space:

| Location | Size | Note |
| --- | --- | --- |
| Docker images | 168.3 GB | 262 images, **107.1 GB reclaimable** (was 166 images / 118.9 GB / 58 GB yesterday) |
| Docker build cache | 91.08 GB | 2013 entries, **78.34 GB reclaimable** (was 44.38 GB / 31.6 GB yesterday) |
| Docker volumes | 128 GB | 27.38 GB reclaimable |
| `/opt/potai-staging` | 124 GB | 24 releases at ~5.2 GB each, all dated Aug 28-29 |
| `/opt/registry/data` | 76 GB | the Docker registry store |

Roughly 213 GB is reclaimable through Docker alone, which would take the
filesystem from 84% back to about 72%.

The largest single image family is `quickchat-waddinxveen-demo` with 79 images,
followed by 36 `hakbijl5/potai-staging`, 34 dangling `<none>` images and 26
`registry.pitchai.net:5000/autopar-webapp-staging`. The demo family matches the
many `quickchat-waddinxveen-luna-*` containers left in `Exited (137)` state
yesterday, so each demo run appears to build an image that is never reclaimed.

Three reclamation jobs are supposed to bound this, and all three are
under-delivering:

- **`registry-cleanup.service` fails.** Today's run at 03:03:30 CEST deleted
  untagged manifests, stopped the registry, then ran
  `docker run --rm ... registry:2 garbage-collect --delete-untagged` and got
  exit status 1. The wrapper logs the `CalledProcessError` traceback but the
  subprocess output is captured and never printed, so the actual registry error
  is not visible anywhere — that gap is itself worth fixing. The registry was
  restarted and is serving normally.
- **A second job touches the same registry.** `/etc/cron.d/registry-auto-prune`
  runs `/usr/local/bin/registry-auto-prune.sh` at 04:30 daily and also stops
  and starts the `registry` container, writing a 137 MB
  `/var/log/registry-auto-prune.log`. Two independent jobs stopping and
  starting one container and walking one data directory is a plausible cause
  of the GC failure, and it is not something this lane should reconcile.
  `registry` was last started at 2026-09-23T02:30:09Z by the cron job.
- **`pitchai-potai-staging-release-cleanup.service` refuses to prune and exits
  1.** It has failed every night (Sep 20, 21, 22, 23) with
  `potai release cleanup skipped: retention floor retained=0` and
  `minimum=20 total=24 candidates=24`. It sees 24 releases against a floor of
  20 and still retains nothing, so the 124 GB is never touched. `pitchai-production-builder-cache-cleanup.service`
  by contrast reports `Result=success`, yet 78 GB of build cache remains
  reclaimable.

Memory and swap are also tighter than yesterday: memory is at 75.56% used
(was 64.28%) with 16 GB available, and swap is fully consumed at 31 GiB of
32 GiB with 16 KiB free, unchanged from yesterday and still above the 90%
escalation threshold.

## Nginx, proxy and logs

`nginx -t` passes with the same pre-existing duplicate `server_name` warning
for `chat-staging.pitchai.net`.

Over the 24-hour window: 3676 `connect() failed`, 64 `[emerg]`, 33
`upstream prematurely closed`, 2 `upstream timed out`, and zero
`no live upstreams` and zero `upstream sent too big header`. The connect
failures remain concentrated on the two dead dashboard-only upstreams —
`support.pitchai.net` (2500, up from 1460) and `dashboards.pitchai.net` (1175)
— which still point at localhost ports with no listener. Both were re-probed
this run and still return 502.

## logrotate root cause: one malformed audit line

The nightly `logrotate` failure is now traced to a single line. Of 3006
non-blank lines in `/var/log/nginx/breakglass-events.jsonl`, exactly **one**
is malformed JSON: line 207, 172 bytes. That one line makes the breakglass
producer fail on every pass:

```
pitchai-breakglass-events[1852621]: Breakglass event producer failed: Breakglass JSON audit line is malformed
```

The unit retries roughly every minute and fails with `status=1`. Because the
logrotate prerotate script for that file restarts this unit and treats a
nonzero exit as fatal, logrotate aborts the whole run — 2026-09-20, 09-21,
09-22 and again 2026-09-23 at 00:00 CEST. The aborted run leaves
`/var/log/pitchai-nginx-events-bus` recreated as `root:root 700` while
`www-data` must write inside it, which produces the 64 nginx `[emerg]
Permission denied` lines in 24h.

So one 172-byte line in a 477 KB audit log is the root of a four-night
logrotate failure and an nginx logging fault. Repairing it means touching an
audit log, which this lane must not do, so it is escalated with the exact
line number.

The wider Events Bus family is also degraded and the failed-unit count on
`pitchai-main` rose from 15 to 29 (36 lines in `systemctl --failed`, of which
12 are the derived `pitchai-systemd-events-bus@<unit>` persistence entries).
Newly failed alongside the long-standing ones are
`pitchai-nginx-events-bus.service` (which reports
`Nginx producer failed: source_binary_binding_invalid`),
`pitchai-redis-events-bus.service`, `pitchai-sudo-events-bus.service`,
`pitchai-ufw-events-bus.service`, `pitchai-snapd-events-bus.service`,
`pitchai-systemd-events-bus-retry.service` and `registry-cleanup.service`.
The Events Bus service itself (`pitchai-events-bus.service`) is active, so this
is the publisher side failing, and the derived `@` units are symptoms rather
than separate faults.

## TLS, ACME and certificates

`registry.pitchai.net:5000` direct TLS is valid to 2026-12-20 (renewed
2026-09-21) and `docker manifest inspect` succeeds, so the auto-dispatch path
is intact.

`skybuyfly.pitchai.net` is unchanged and now at 26 days: both front doors still
serve serial `59A688686827C981A7E74FBF73A6E93DBD0` expiring
**2026-10-19T03:35:18Z**, public DNS still resolves to `157.180.101.33` (the
AIPC HEL1 front door), and `pitchai-main`'s certbot failed again at
2026-09-23T07:50:41 CEST. The pinned probe against the topology contract
address `37.27.67.52` returns 200 in 0.73 s with a matching CN. Yesterday's
diagnosis stands: the host that answers the HTTP-01 challenge has no working
ACME account, and the host with the working account cannot answer it.

No other lineage is inside 30 days, `n8n.pitchai.net` has no enabled site or
lineage, and the removed `afasask.gzb.nl-0001` duplicate has not reappeared.

## Dedicated host: aipc-fsn1-01 (5.9.42.254)

Reachable and stable, unchanged from yesterday. Uptime 11 days 3 h, load
0.11/0.11/0.10 on 12 CPUs, memory 7.7/125 GB with swap completely unused.
`/dev/md2` is 22% with 687 GB free and inodes at 3%; `/srv/aipc-cold` is
empty at 1.8 TB free; journal is 1.5 GB. Two failed one-shot units
(`aipc-docker-maintenance.service`, `aipc-host-audit.service`), neither
serving traffic. All five running AIPC containers are healthy with zero
restarts (`aipc-shadow-primary`, `aipc-shadow-stable`, `aipc-pgbouncer`,
`aipc-meilisearch`, `aipc-qdrant`); ten `aipc-*-staged` containers remain in
`Created` state as expected for a staged set. Docker holds 55.2 GB of images
with no volumes or build cache. **No `actions.runner.*` unit exists**, the same
inventory gap recorded before; the host has plenty of headroom for runner work
once one is provisioned.

Topology contract confirmed unchanged: public SkyBuyFly evaluated against
`37.27.67.52` only, PostgreSQL on `65.109.70.111`, and `5.9.42.254` was not
treated as a DNS, certificate, API, traffic or PostgreSQL target. No cutover
or production mutation was made.

## Actions

No fix was applied and nothing was deleted, truncated, pruned, rotated or
restarted. Every finding either touches another team's runtime, requires DNS
or certificate or account changes, or would mean editing an audit log or
reclaiming storage that may hold live data.

One requester-private Telegram escalation was sent to Seth van der Bijl
covering the three-hour AFASAsk Codex outage that stayed invisible to the
aggregate status, the `pitchai-main` disk trajectory with its three
under-delivering reclamation jobs, the single malformed audit line behind the
four-night logrotate failure, and the unchanged SkyBuyFly renewal deadlock,
each with a recommended next action. No other message was sent.

## Remaining work

- Root-cause the 2026-09-22 AFASAsk Codex outage before it recurs, and make the
  enabled-test failures visible even when the aggregate stays green. Highest
  priority, because the silent part is the dangerous part.
- Reclaim the ~213 GB of reclaimable Docker storage on `pitchai-main` under
  server-ops review, and fix `registry-cleanup.service` so its GC output is
  actually logged; decide which of the two registry jobs is authoritative.
- Repair the retention logic in
  `pitchai-potai-staging-release-cleanup.service` so the 124 GB of August
  releases is bounded.
- Repair line 207 of `/var/log/nginx/breakglass-events.jsonl` through its owner
  so logrotate completes and nginx stops emitting `[emerg]`, and review the
  newly failed Events Bus publishers.
- Repair the HEL1 ACME account and settle where `skybuyfly.pitchai.net` is
  authoritative before 2026-10-19.
- Provision the isolated GitHub runner on `aipc-fsn1-01` and reconcile the AIPC
  container inventory against topology.
- Standing items unchanged: `aigenda-rules.demos.pitchai.net` and
  `montrachet-demo.pitchai.net` flapping,
  `wrist-vault.135-181-182-48.sslip.io` down under its dashboard-only policy,
  the `dispatch.pitchai.net` API contract streak, the monitor meta cycle, the
  `whatsapp.pitchai.net` QR expiry, the `dashboards.pitchai.net` and
  `support.pitchai.net` dead upstreams, `pitchai-dev` SSH access, and the
  enabled/disabled drift for `afasask.pitchai.net` and
  `afasask_gzb_codex_medium_ok_daily`.
