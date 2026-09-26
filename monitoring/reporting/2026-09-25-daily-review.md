# Daily monitoring review: 2026-09-25

## Decision

Everything that serves customers is healthy. All seven enabled domains returned
**100% availability for the whole 24-hour window with 200s only**, the monitor
state is fresh, DNS, browser and proxy signals are clean, containers are
running, and the certificates that matter are valid. Two findings that the
2026-09-23 report escalated as broken infrastructure closed on their own and
are now verified fixed.

The day is still not clean. The AFASAsk Codex path failed again for **10.5
hours overnight** — the second outage in three days — and the aggregate status
stayed green through it for the second time. Memory and swap on `pitchai-main`
tightened further, disk reached 86%, and the jobs meant to bound that disk
still decline to act. No fix was applied; one requester-private escalation was
sent.

This review covers **two days**, because the 2026-09-24 fire did not run. Live
collection ran 2026-09-25T03:00-03:30Z.

## Enabled domains (24 h window, 731 samples each)

| Domain | OK / total | Availability | p95 HTTP | Median HTTP | Codes |
| --- | --- | --- | --- | --- | --- |
| `autopar.pitchai.net` | 731/731 | 100% | 63.6 ms | 17.5 ms | 200 |
| `afasask.gzb.nl` | 731/731 | 100% | 38.5 ms | 16.7 ms | 200 |
| `skybuyfly.pitchai.net` | 731/731 | 100% | 157.3 ms | 106.1 ms | 200 |
| `deplanbook.com` | 731/731 | 100% | 8.3 ms | 3.7 ms | 200 |
| `cms.deplanbook.com` | 731/731 | 100% | 172.2 ms | 74.6 ms | 200 |
| `dpb.pitchai.net` | 731/731 | 100% | 52.5 ms | 14.0 ms | 200 |
| `hetcis.nl` | 731/731 | 100% | 69.2 ms | 60.8 ms | 200 |

This is the first fully clean 24-hour window for the enabled set in the recent
record — `skybuyfly.pitchai.net`, which dropped to 98.824% on 2026-09-23, is
back to 731/731.

The dashboard's aggregate `daily_status` reads **85.290%**
(52 160 / 61 156 observations, 6 problem events, 7 recoveries, status
`attention`). That figure is dominated by routes that are down by policy or
by neglect rather than by customer impact: thirteen non-enabled domains sit at
0% for the full window — `agentcloud.pitchai.net` (502),
`cursussen.pitchai.net` (404), `dashboards.pitchai.net` (502),
`support.pitchai.net` (502), `whatsapp.pitchai.net` (503),
`registry.pitchai.net`, `wrist-vault.135-181-182-48.sslip.io` (502), and the
five `jeff-*` routes. `aigenda-rules.demos.pitchai.net` and
`montrachet-demo.pitchai.net` both recovered and finished the window at
84.815% (up from 56.789% and 68.277% on 2026-09-23);
`staging.formatief-toetsen.pitchai.net` is at 99.726%.

## AFASAsk Codex outage recurrence: 2026-09-24T15:54Z to 2026-09-25T02:26Z

Both enabled Codex smoke tests failed repeatedly through the night and then
recovered minutes before this review ran:

| Test | Runs (48 h) | Pass | Fail | First fail | Last fail | Last run |
| --- | --- | --- | --- | --- | --- | --- |
| `afasask_demo_codex_fast_ok` | 93 | 73 | 20 | 2026-09-24T16:10Z | 2026-09-25T02:13Z | **pass**, 10.4 s, 02:44Z |
| `afasask_production_codex_medium_synthetic_ok` | 91 | 72 | 19 | 2026-09-24T15:54Z | 2026-09-25T02:26Z | **pass**, 11.4 s, 02:57Z |

Registry-wide over the same window: **1209 pass, 39 fail**.

The failure signature is identical to 2026-09-22 and it is the reason this
matters: the fast canary dies in 1-8 seconds on
`afasask_demo_codex_canary_failed_marker: ❌ mislukt`, while the medium run
hangs to its 240-second `Page.wait_for_function: Timeout 240000ms exceeded`
ceiling. That is the Codex execution path being unavailable, not a slow page.
The window is also ~3.5x longer than the 2026-09-22 incident (10.5 h against
3 h) and lands in the same overnight band.

The monitoring blind spot reproduced exactly as described on 2026-09-23.
`failing_tests=2` stayed pointed at the disabled historical DFT rows
(`dft_prod_exam_import_2doc_sla_daily_e2e`, last failure 2026-05-22), the
aggregate `ok` stayed `true`, and the only trace in the summary view was the
enabled tests' success streaks resetting. Reading raw run history is what
surfaced it again. Note the enabled/disabled drift: the reminder names
`afasask_gzb_codex_medium_ok_daily` as the enabled smoke test, but in the
registry that test is **disabled** (last run 2026-09-04, `fail`); the enabled
equivalent is `afasask_production_codex_medium_synthetic_ok`.

## Signals

`state.json` is schema **v6**, last written 2026-09-25T03:01:45Z and 17 seconds
old when read, so freshness is `fresh` against a 60-second interval and
`state_write_fail_streak` is 0. The rolling window holds 731 samples per
enabled domain and per signal.

| Signal | Bad / total | Latest | Reading |
| --- | --- | --- | --- |
| `browser` | 0/731 | ok | `degraded_active=false`, no launch failures |
| `dns` | 0/90 | ok | — |
| `proxy` | 3/731 | ok | one `proxy_degraded` event 07:22-07:28Z on 2026-09-24, recovered; `pct_502_504` 0.0% |
| `container_health` | 731/731 | **failed** | 1 issue per cycle, see below |
| `host_health` | 731/731 | **failed** | memory 80.527%, swap 100.0%, 3 violations |
| `tls` | 23/23 | **failed** | 3 failures per cycle, see below |
| `performance` | 731/731 | failed | 45 slow domains |
| `red` | 731/731 | failed | 42 violations |
| `slo` | 731/731 | failed | 4 violations |
| `meta` | 731/731 | failed | 1 reason, 121.4 s cycle |

The sustained-failure set is unchanged from 2026-09-23, with the same two known
causes. `container_health` is `dft-worker-green`, still `Exited (0)` three days
after the DFT blue/green rollover and still matching the monitor's include
pattern (`fail_streak` 2778). `tls` is the same three domains the monitor
already routes away from Telegram — `registry.pitchai.net`,
`jeff-codex-voice.94.130.17.246.nip.io` and
`jeff-work-inbox.94.130.17.246.nip.io` — and the registry's own direct TLS is
verified valid below, so this is a check artefact rather than a serving fault.

Host health is the signal that genuinely worsened: memory peaked at **94.42%**
inside the window, swap has been pinned at **100.0%** for the entire window,
and `worst_disk_used_percent` rose from 78.9% to 81.275% (the monitor's
used/total view of the same filesystem `df` reports at 86%).

## Host: pitchai-main memory, swap and disk

Swap is fully consumed: **32 734 MiB of 32 734 MiB used, 0-8 KiB free**, at or
above the 90% escalation threshold for a fourth consecutive review. Memory is
51 445 MiB used of 64 039 MiB with **12 594 MiB available**, down from 16 GB on
2026-09-23. The trajectory over the three reviews is 64.28% → 75.56% → 80.18%,
and the 24-hour peak was 94.42%.

`/dev/md2` is at **86%, 236 GB free** (was 84% / 278 GB on 2026-09-23 and
78% / 363 GB on 2026-09-22). That is 42 GB over two days, roughly 21 GB/day
against 85 GB/day in the prior interval, and three free-space samples taken
minutes apart moved only ~20 MB, so the loss is bursty and tracks deploy and
build activity rather than a steady leak.

| Location | Size | Note |
| --- | --- | --- |
| Docker images | 192.2 GB | 313 images, **131.2 GB reclaimable** (was 168.3 GB / 107.1 GB) |
| Docker build cache | 104.1 GB | 2459 entries, **91.38 GB reclaimable** (was 91.08 GB / 78.34 GB) |
| Docker volumes | 128.2 GB | 27.38 GB reclaimable |
| `/opt/potai-staging/releases` | 124 GB | 24 releases, all dated Aug 28-29 |
| `/opt/registry/data` | 76 GB | unchanged since 2026-09-23 |
| `/var/log/registry-auto-prune.log` | 132 MB | unbounded, ~1.6 MB/day |

The growth is entirely in the local Docker image and build-cache layer
(+24 GB and +13 GB), not in the registry store, which is flat. The largest
uncapped family is again `quickchat-waddinxveen-demo` with 79 images, followed
by 46 dangling `<none>` images.

Two jobs are supposed to bound this and neither does:

- **`pitchai-potai-staging-release-cleanup.service` still refuses to prune.**
  Today's run at 04:37:46 CEST exited 1 with `potai release cleanup skipped:
  retention floor retained=0, minimum=20 total=24 candidates=24`. It sees 24
  releases against a floor of 20, retains nothing, and the 124 GB is never
  touched. Failing every night since at least 2026-09-20.
- **`registry-cleanup.service` now succeeds by doing nothing.**
  `Result=success` at 03:02:10 CEST, but the log reads `Protected digests: 11`,
  `Registry contains 44 repositories`, `No tags scheduled for deletion`,
  `Skipping garbage-collect (nothing deleted)`. Yesterday's wrapper traceback is
  gone; the retention policy itself simply nominates nothing.

The only working guard is `pitchai-production-builder-cache-cleanup.service`,
which ran at 03:58:10 CEST in `mode=check` with `until_age=24h`,
`reserve_bytes=214748364800` (200 GiB) and `available_before=250760597504`
(233.6 GiB), concluding `status=reserve-satisfied` and doing nothing. So the
host is deliberately allowed to fill to a 200 GiB reserve — currently about
30 GB away — and roughly 250 GB is reclaimable on demand once it is crossed.
Nothing was deleted, trimmed, pruned, rotated or restarted from this lane.

## Closed since the last review

Both escalated findings from 2026-09-23 are verified fixed:

- **The breakglass/logrotate chain is repaired.** `logrotate.service` is
  `Result=success` (exit 0 at 2026-09-25T00:00:09 CEST, next run 2026-09-26),
  `pitchai-breakglass-events-bus.service` is `inactive` with `Result=success`,
  and `/var/log/nginx/breakglass-events.jsonl` now holds **167 non-blank lines
  with 0 malformed** — the single bad line that aborted four nightly runs is
  gone. `pitchai-breakglass-events-bus.service` and
  `registry-cleanup.service` have both dropped out of the failed-unit list.
- **The `[emerg]` burst is now a one-shot.** All 102 `Permission denied` lines
  in today's nginx error log carry timestamps of 00:00:03-00:00:09, i.e. the
  seconds around rotation, and `journalctl -u nginx` shows zero in 24 hours.
  The underlying condition survives though: `/var/log/pitchai-nginx-events-bus`
  is still `root:root 700` while nginx workers run as `www-data`, so the same
  burst should be expected at the next rotation, and
  `pitchai-nginx-events-bus.service` still fails with
  `source_binary_binding_invalid`.

Failed units stand at **37 lines, 13 of them not derived `@` units**:
`pitchai-nginx-events-bus`, `pitchai-nftables-events-bus` (newly failed),
`pitchai-redis-events-bus`, `pitchai-sudo-events-bus`,
`pitchai-snapd-events-bus`, `pitchai-ufw-events-bus`,
`pitchai-systemd-events-bus-retry`, `pitchai-potai-staging-release-cleanup`,
`certbot`, `aipc-hel1-canary-transport-audit`, `lxd-installer@0` and three
transient `run-u*`. The Events Bus publisher family remains degraded while the
bus itself is active.

## Nginx, proxy and logs

`nginx -t` passes with only the long-standing duplicate `server_name` warnings
for `pitchai.net`, `www.pitchai.net`, `staging.chat.pitchai.net` and
`chat-staging.pitchai.net`.

Over the last 5000 error-log lines: 631 `[error]`, 495 `[warn]`, 102
`[emerg]`. The `[emerg]` lines are the closed one-shot above. Access-log 50x
counts for the window are 491 `502` and 1 `504`; against ~470-650 requests per
monitor cycle that is scanner and dead-route noise rather than customer
impact, and the monitor's own `proxy` signal reports `pct_502_504` at 0.0%
with `success_streak` 594.

The concentrated error sources are unchanged and were re-probed:

- `dashboards.pitchai.net` — 160 `connect() failed (111: Connection refused)`,
  direct probe returns **502**; no listener on port 3200.
- `support.pitchai.net` — 157 + 10 `connect() failed`, direct probe returns
  **502**; no listener on port 8420.
- `staging.potaito.pitchai.net` — now returns **401** rather than 502, and
  port 8081 has a live `docker-proxy` listener, so this route is serving behind
  auth again.

One `upstream prematurely closed` and one `upstream timed out` appeared in the
window, with no `no live upstreams` and no `upstream sent too big header` —
down from 33 and 2 on 2026-09-23.

## TLS, ACME and certificates

- `registry.pitchai.net:5000` direct TLS serves CN `registry.pitchai.net` from
  Let's Encrypt `YE1`, valid 2026-09-21 to **2026-12-20** (86 days), and
  `docker manifest inspect registry.pitchai.net:5000/pitchai/codex-runner:latest`
  succeeds, so the auto-dispatch path is intact.
- `skybuyfly.pitchai.net` is now at **24 days**. The certificate served on the
  topology contract address `37.27.67.52` is CN `skybuyfly.pitchai.net` from
  `YE1`, expiring **2026-10-19T03:35:18Z**, unchanged. The pinned probe returns
  **200 in 0.14 s**. Public DNS still resolves to `157.180.101.33` and
  `certbot.service` failed again at 2026-09-24T15:32:44 CEST, so the renewal
  deadlock described on 2026-09-23 is unresolved and now inside its 30-day
  window.
- ACME webroot routing for `staging.formatief-toetsen.pitchai.net` is intact:
  probes for a missing challenge file return **404 from the webroot on both
  HTTP and HTTPS**, not an auth redirect, so the 2026-05-13 patch has not been
  overwritten by a deploy.
- `n8n.pitchai.net` shows no reappearance: no enabled site, no certbot lineage.
  The removed `afasask.gzb.nl-0001` duplicate has not returned.

## Dedicated host: aipc-fsn1-01 (5.9.42.254)

Reachable and quiet, essentially unchanged from 2026-09-23. Port 22 accepts
connections and the `aipc-fsn1-01` SSH alias authenticates; uptime 12 days
22.5 h, load 0.00/0.05/0.07 on 12 CPUs.

| Check | Reading |
| --- | --- |
| `/dev/md2` | 22% used, **687 GB free**, inodes 3% |
| `/dev/md0` (`/boot`) | 23%, inodes 1% |
| `/dev/sda1` (`/srv/aipc-cold`) | 1% used, 1.8 TB free, inodes 1% |
| Memory / swap | 8.0 GB of 125 GB used, 117 GB available; **swap 0 B of 16 GB** |
| Journal | 1.6 GB total on disk, `/var/lib/docker/containers` 29 MB |
| Failed units | **2**, both one-shot: `aipc-docker-maintenance.service`, `aipc-host-audit.service` |
| Docker storage | 55.2 GB images, 78.6 MB containers, **0 B volumes and 0 B build cache** |

All five running AIPC containers are `healthy` with **`restarts=0`** and a
common start time of 2026-09-12T04:31Z: `aipc-shadow-primary`,
`aipc-shadow-stable`, `aipc-pgbouncer`, `aipc-meilisearch`, `aipc-qdrant`. CPU
use is 0.03-0.59% and the two shadow workers sit at ~1.7 GiB of an 8 GiB
limit. The ten `aipc-*-staged` containers remain in `Created` state, as
expected for a staged set. No `aipc-*` or `ai_price_crawler-*` stack runs on
`pitchai-main`, so there is no crawler restart loop to report on either host.

**Runner gap unchanged: no `actions.runner.*` unit exists.** The host has
12 CPUs, 117 GB free memory, 687 GB free on `/dev/md2` and a 1.8 TB empty
scratch disk, so the blocker is provisioning, not capacity. Runner
provisioning and reconfiguration remain server-ops work; no deep or invasive
check was attempted from this lane.

Topology contract confirmed: public SkyBuyFly was evaluated against
`37.27.67.52` only, PostgreSQL remains on `65.109.70.111`, and `5.9.42.254` was
not treated as a DNS, certificate, API, traffic or PostgreSQL target. No
cutover or production mutation was made.

## Actions

No fix was applied and nothing was deleted, truncated, pruned, rotated or
restarted. Every finding either touches another team's runtime, requires DNS
or certificate or account changes, or would mean reclaiming storage that may
hold live release or image data.

One requester-private Telegram escalation was sent to Seth van der Bijl
covering the recurring AFASAsk Codex outage and its monitoring blind spot, the
swap and memory pressure on `pitchai-main`, the disk trajectory with the two
reclamation jobs that decline to act, and the SkyBuyFly renewal deadlock now
inside its 30-day window, each with a recommended next action. No other
message was sent.

## Remaining work

- Root-cause the AFASAsk Codex path and stop the overnight failure band before
  the third occurrence. Make enabled-test failures visible even when the
  aggregate stays green — the silent part is the dangerous part. Highest
  priority.
- Give `pitchai-main` swap and memory a real owner: swap has been at 100% for
  four reviews and memory peaked at 94.4% in this window.
- Reclaim the ~250 GB of reclaimable Docker storage under server-ops review,
  and decide whether a 200 GiB free-space reserve is the intent for a volume
  at 86%; bound the `quickchat-waddinxveen-demo` image family and the 46
  dangling images.
- Repair the retention logic in
  `pitchai-potai-staging-release-cleanup.service` so the 124 GB of August
  releases is bounded, and confirm whether `registry-cleanup.service`
  nominating zero tags is intended.
- Restore `www-data` write access to `/var/log/pitchai-nginx-events-bus` so the
  00:00 `[emerg]` burst stops, and clear the failed Events Bus publishers.
- Settle the HEL1 ACME account and where `skybuyfly.pitchai.net` is
  authoritative before **2026-10-19**.
- Provision the isolated GitHub runner on `aipc-fsn1-01` and reconcile the AIPC
  container inventory against topology.
- Standing items unchanged: the `dashboards.pitchai.net` and
  `support.pitchai.net` dead upstreams, `agentcloud.pitchai.net` and
  `cursussen.pitchai.net` at 0%, the `jeff-*` routes, the
  `dispatch.pitchai.net` API contract streak (7114), `wrist-vault` under its
  dashboard-only policy, the `whatsapp.pitchai.net` QR expiry, the monitor meta
  cycle, the `dft-worker-green` container-health false positive, and the
  enabled/disabled drift for `afasask.pitchai.net` and
  `afasask_gzb_codex_medium_ok_daily`.
