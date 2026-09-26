# Daily monitoring review: 2026-09-26

## Decision

Six of the seven enabled domains returned a clean 24-hour window and the
platform side of the stack is in better shape than yesterday: the failed-unit
count on `pitchai-main` fell from 37 lines to 26, `logrotate` and the breakglass
audit chain completed a second consecutive clean night, `nginx -t` passes, DNS,
browser and proxy signals are perfect, and the registry, ACME webroot and n8n
checks are all as expected.

One enabled domain did not stay clean. **`skybuyfly.pitchai.net` had a real
13-minute outage** on 2026-09-25T23:16-23:29Z and a shorter repeat at
02:23-02:28Z, both of which line up with a staged-stack rollout on the SkyBuyFly
front door. The AFASAsk Codex smoke failed again for a third consecutive night,
this time briefly. Disk on `pitchai-main` reached 87%, swap is still pegged at
100%, and the SkyBuyFly certificate is now 23 days from expiry with renewal
still deadlocked. No fix was applied; one requester-private escalation was sent.

Live collection ran 2026-09-26T03:00-03:20Z.

## Enabled domains (24 h window, 699 samples each)

| Domain | OK / total | Availability | p95 HTTP | Median HTTP | Codes |
| --- | --- | --- | --- | --- | --- |
| `autopar.pitchai.net` | 699/699 | 100% | 52.0 ms | 16.6 ms | 200 |
| `afasask.gzb.nl` | 699/699 | 100% | 42.8 ms | 18.0 ms | 200 |
| `skybuyfly.pitchai.net` | 693/699 | **99.142%** | 154.0 ms | 105.9 ms | 200, null |
| `deplanbook.com` | 699/699 | 100% | 8.7 ms | 3.7 ms | 200 |
| `cms.deplanbook.com` | 699/699 | 100% | 156.3 ms | 75.2 ms | 200 |
| `dpb.pitchai.net` | 699/699 | 100% | 65.8 ms | 14.1 ms | 200 |
| `hetcis.nl` | 699/699 | 100% | 72.8 ms | 60.9 ms | 200 |

Dashboard-derived `daily_status` reads **86.195%** (50 538 / 58 632, 6 problem
events, 8 recoveries, status `attention`), diluted by the same
policy-down routes as yesterday: `dispatch.pitchai.net`,
`whatsapp.pitchai.net` (503), `registry.pitchai.net`,
`agentcloud.pitchai.net` (502), `dashboards.pitchai.net` (502),
`support.pitchai.net` (502), `cursussen.pitchai.net` (404) and the five
`jeff-*` routes. `wrist-vault.135-181-182-48.sslip.io` **recovered** at
16:38Z yesterday and is no longer in the down set.

## SkyBuyFly outage and the front-door rollout

Both SkyBuyFly hostnames failed together and recovered together:

| Time (UTC) | `skybuyfly.pitchai.net` | `stable.skybuyfly.pitchai.net` |
| --- | --- | --- |
| 23:16:24 | ReadTimeout after 15 007 ms | 502 |
| 23:18:45 | ReadTimeout after 15 018 ms | 502 |
| 23:20:44 | ReadTimeout after 15 006 ms | 502 |
| 23:22:35 | ReadTimeout after 15 010 ms | 502 |
| 23:25:33 | ReadTimeout after 15 011 ms | 502 |
| 23:27:42 | HTTP 200, browser check failed | HTTP 200, browser check failed |
| 02:23:56 | — | 502 |
| 02:25:56 | browser check failed | HTTP 200, browser check passed |

Monitor events: `domain_down` at 23:16:24Z (502 plus a 15-second read timeout),
`api_contract_degraded` at 23:22:35Z, `domain_up` at 23:29:47Z,
`api_contract_recovered` at 23:34:11Z, then `domain_down` at 02:23:56Z and
`domain_up` at 02:28:04Z.

The cause is not in nginx on `pitchai-main` — that error log records **zero**
`skybuyfly` entries in the current and previous file. The correlation is with
the front door the public DNS actually points at. `skybuyfly.pitchai.net`
resolves to `157.180.101.33` (`aipc-hel1-01`), and that host restarted its AIPC
staged stack inside the failure window:

| Time (UTC) | Event on `aipc-hel1-01` |
| --- | --- |
| 23:27:16 | `aipc-meilisync-staged` started |
| 23:27:29 | ten more `aipc-*-staged` containers started together |
| 23:28:43 | `aipc-shadow-stable` started |
| 23:29:38 | `aipc-shadow-primary` started |
| 23:30:23 | nginx reloaded |
| 23:50:08 | `aipc-crawler-staged` started, exited 6 s later |

So a rollout ran roughly 23:1x-23:50Z, the outage brackets it, and service
returned as the replacement containers came up at 23:27Z. The second dip
matches the last write to that host's nginx error log at 02:24Z. Whether this
was a planned deployment or a recovery from one cannot be determined from the
monitoring lane, and the public contract (traffic evaluated against
`37.27.67.52` only, no DNS or certificate change) was respected throughout.

Current state: the pinned probe against `37.27.67.52` returns **200 in 0.109 s**,
the unpinned probe returns 200 in 0.118 s, and the certificate is unchanged.

## AFASAsk Codex, third consecutive night — and much shorter

| Test | Runs (24 h) | Pass | Fail | Failure times |
| --- | --- | --- | --- | --- |
| `afasask_demo_codex_fast_ok` | 47 | 45 | 2 | 22:46:09Z, 23:17:24Z |
| `afasask_production_codex_medium_synthetic_ok` | 46 | 44 | 2 | 23:01:39Z, 23:36:26Z |

Registry-wide: **628 pass, 4 fail**. Every enabled test's `last_status` is
`pass` and `success_streak` resumed (last fast run 02:51:46Z in 11.8 s, last
medium run 02:41:59Z in 15.3 s). `failing_tests=2` is still the disabled
historical DFT rows, not a live failure.

This is the same overnight band as 2026-09-22 (3 h) and 2026-09-24/25 (10.5 h),
but the shortest instance so far at roughly 50 minutes. Note that it overlaps
the SkyBuyFly dip at 23:16-23:29Z; both touch the same public front door, so a
single underlying event is plausible, but this lane cannot attribute it.

## Signals

`state.json` is schema **v6**, last written 2026-09-26T02:58:45Z and 115 seconds
old when read — inside the 180-second stale threshold with
`state_write_fail_streak` 0.

| Signal | Bad / total | Latest | Reading |
| --- | --- | --- | --- |
| `browser` | 0/698 | ok | `degraded_active=false`, no launch failures |
| `dns` | 0/89 | ok | — |
| `proxy` | **0/698** | ok | clean for the whole window, `pct_502_504` 0.0% |
| `container_health` | 698/698 | **failed** | `dft-worker-green` still `Exited (0)`, now 4 days |
| `host_health` | 698/698 | **failed** | memory 85.675%, swap 99.999%, 3 violations |
| `tls` | 24/24 | **failed** | 3 failures per cycle, Telegram-excluded domains |
| `performance` | 698/698 | failed | 43 slow domains |
| `red` | 698/698 | failed | 44 violations |
| `slo` | 698/698 | failed | 6 violations |
| `meta` | 698/698 | failed | 1 reason, 113.5 s cycle |

The sustained set is unchanged in composition from the last two reviews, with
the same two known causes: `container_health` is the `dft-worker-green`
false positive, and `tls` is the three domains the monitor already routes away
from Telegram (`registry.pitchai.net`, `jeff-codex-voice` and
`jeff-work-inbox` on `94.130.17.246.nip.io`) whose registry certificate is
independently verified valid below. `host_health` is the one that worsened
again — see below.

## Host: pitchai-main disk, memory and swap

`/dev/md2` is now at **87% with 217 GB free**, down from 86% / 236 GB yesterday
and 84% / 278 GB two days ago. Memory is **85.675% used** (55 678 MiB of
64 039) with only **8 360 MiB available**, down from 12 594 MiB yesterday and
15-16 GB before that. **Swap is fully consumed again**: 32 734 MiB of
32 734 MiB, 0 free — the fifth consecutive review above the 90% threshold.

| Location | Size | Note |
| --- | --- | --- |
| Docker images | **205.6 GB** | **365 images**, 146.2 GB reclaimable (was 192.2 GB / 313) |
| Docker build cache | 104.1 GB | 2643 entries, 91.4 GB reclaimable |
| Docker volumes | 128.2 GB | 27.38 GB reclaimable |
| `/opt/potai-staging/releases` | 124 GB | 24 releases, unchanged |
| `/opt/registry/data` | 76 GB | flat |

The growth driver is again images, and this time specifically **dangling ones:
90 `<none>` images against 46 yesterday**, alongside the unchanged
`quickchat-waddinxveen-demo` family at 79. The registry store itself is flat,
so this is local build output, not registry retention.

Reclamation still does not fire. `pitchai-production-builder-cache-cleanup`
ran at 03:48:51 CEST with `available_before=231548268544` (215.6 GiB) against
its 200 GiB reserve and concluded `status=reserve-satisfied`, so it took no
action — the tripwire is now roughly **15 GiB away**. Meanwhile
`pitchai-potai-staging-release-cleanup.service` failed again at 04:48:09 CEST
with the same retention-floor refusal, and `registry-cleanup` continues to
nominate zero tags. Nothing was deleted, pruned, rotated or restarted from this
lane.

## Nginx, proxy and logs

`nginx -t` passes. Over the current and previous error-log files: **877**
`connect() failed` for `dashboards.pitchai.net` and **869** for
`support.pitchai.net` (both still dead upstreams, both re-probed at 502),
**204** `[emerg] Permission denied` on
`/var/log/pitchai-nginx-events-bus/error.log`, 1675 warn plus 519 buffered
response warnings for `orthoparse.pitchai.net`, and 915 warn for the
`/events-bus/webhooks/github` uploads on `pitchai.net`.

The 204 `[emerg]` lines are two nights of the same ~102-line burst at
00:00:03-00:00:09, exactly as predicted yesterday: logrotate now completes, but
it still recreates `/var/log/pitchai-nginx-events-bus` as `root:root 700` while
nginx workers run as `www-data`. Access-log 50x counts are 491 `502` and no
`504`, matching scanner and dead-route noise rather than customer impact, and
the proxy signal itself stayed green for the entire window for the first time
in recent memory.

`staging.potaito.pitchai.net` returns **401** (serving behind auth) rather than
502, so that route remains resolved.

## TLS, ACME and certificates

- `registry.pitchai.net:5000` direct TLS serves CN `registry.pitchai.net` from
  Let's Encrypt `YE1`, valid 2026-09-21 to **2026-12-20**, and
  `docker manifest inspect registry.pitchai.net:5000/pitchai/codex-runner:latest`
  succeeds, so auto-dispatch is intact.
- `skybuyfly.pitchai.net` is now at **23 days**, expiring
  **2026-10-19T03:35:18Z**. `certbot.service` failed again at
  2026-09-26T03:00:45 CEST. The renewal deadlock from the last two reviews is
  unresolved: public DNS points at `157.180.101.33`, whose ACME account is
  broken, while `pitchai-main` holds the working account and cannot answer the
  challenge. `certbot.service` is also the single failed unit on the HEL1 host.
- ACME webroot routing for `staging.formatief-toetsen.pitchai.net` is intact:
  a missing challenge file returns **404 from the webroot on both HTTP and
  HTTPS**, not an auth redirect.
- `n8n.pitchai.net` shows no reappearance (no enabled site, no lineage), and
  the removed `afasask.gzb.nl-0001` duplicate has not returned.

## Failed units and the closed items

`pitchai-main` now reports **26 failed unit lines, 12 of them not derived `@`
units** — down from 37 lines and 13 yesterday. Remaining:
`pitchai-nginx-events-bus` (`source_binary_binding_invalid`),
`pitchai-redis-events-bus`, `pitchai-sudo-events-bus`,
`pitchai-snapd-events-bus`, `pitchai-ufw-events-bus`,
`pitchai-systemd-events-bus-proof`, `pitchai-potai-staging-release-cleanup`,
`certbot`, `aipc-hel1-canary-transport-audit` and three transient `run-u*`
units. `pitchai-nftables-events-bus` and `pitchai-systemd-events-bus-retry`
dropped out.

Holding:

- `logrotate.service` is `Result=success` again (exit 0 at
  2026-09-26T00:00:07 CEST) and `pitchai-breakglass-events-bus.service` is
  `inactive` with `Result=success` — second clean night for the chain that
  failed four nights running before 2026-09-25.
- `pitchai-docker-engine-events-retry.service` runs every ~60 s but exits
  `Result=success` with `acknowledged=0 pending=0`, so it is an idle spool
  drain, not a failure loop.

## Dedicated host: aipc-fsn1-01 (5.9.42.254)

Reachable through the `aipc-fsn1-01` alias. **The host rebooted on
2026-09-25T04:30Z** — the previous boot had run 12 days, and this review a day
ago saw that older uptime, so the reboot happened after the last review. It
came back cleanly: uptime 22 h 30 m, and the reboot reason recorded in the
prior boot's journal is an orderly `systemd-reboot` shutdown, not a crash.

| Check | Reading |
| --- | --- |
| `/dev/md2` | 23% used, **682 GB free**, inodes 3% |
| `/dev/md0` (`/boot`) | 23%, inodes 1% |
| `/dev/sda1` (`/srv/aipc-cold`) | 1% used, 1.8 TB free, inodes 1% |
| Memory / swap | 7.6 GB of 125 GB used, 118 GB available; **swap 0 B of 16 GB** |
| Journal | 1.6 GB; `/var/lib/docker/containers` 32 MB |
| Docker storage | 55.2 GB images, 78.6 MB containers, **0 B volumes, 0 B build cache** |
| Failed units | **1**: `aipc-host-audit.service` (`aipc-docker-maintenance` now succeeds) |

All five running AIPC containers are `healthy` with **`restarts=0`** and came
back with the reboot (`aipc-shadow-primary`, `aipc-shadow-stable`,
`aipc-pgbouncer`, `aipc-meilisearch`, `aipc-qdrant`). The ten
`aipc-*-staged` containers remain in `Created` state as expected. **No
`actions.runner.*` unit exists**, the same provisioning gap as before; the host
has 12 CPUs, 118 GB free memory, 682 GB free on `/dev/md2` and a 1.8 TB empty
scratch disk, so the blocker remains provisioning rather than capacity.

Read-only diagnostic on `aipc-hel1-01` (`157.180.101.33`, the SkyBuyFly front
door) for incident attribution only: uptime 12 d 22 h, load 2.43/2.97/3.05,
`/dev/md2` **76%** (323 GB used, 107 GB free of 452 GB), memory 19 GiB of 62 GiB
with 42 GiB available, swap 61 MiB of 15 GiB, one failed unit (`certbot`). Its
long-running core (`skybuyfly-quick-chat-staged`, `aipc-postgres`,
`aipc-qdrant`, `aipc-meilisearch`, `aipc-pgbouncer`) has been up 12 days and is
healthy. **`aipc-crawler-staged` started at 23:50:08Z and exited after 6
seconds with `PermissionError: [Errno 13] Permission denied: '/.local'`** —
a scrapy job-file write to an unwritable path, exit code 0, `restarts=0`, so a
single failed run rather than a restart loop. That is an environment or
ownership defect in the AIPC lane and is recorded for server-ops rather than
fixed here.

Topology contract confirmed: public SkyBuyFly was evaluated against
`37.27.67.52` only, PostgreSQL remains on `65.109.70.111`, and `5.9.42.254` was
not treated as a DNS, certificate, API, traffic or PostgreSQL target. No
cutover or production mutation was made.

## Actions

No fix was applied and nothing was deleted, truncated, pruned, rotated or
restarted. Every finding either belongs to another team's runtime, needs DNS or
certificate or account changes, or would mean reclaiming storage that may hold
live release or image data.

One requester-private Telegram escalation was sent to Seth van der Bijl
covering the SkyBuyFly outage with its front-door rollout correlation, the
`pitchai-main` disk and swap position, the failed AIPC crawler run, the third
AFASAsk night, and the SkyBuyFly certificate now 23 days out, each with a
recommended next action. No other message was sent.

## Remaining work

- Attribute the SkyBuyFly outage: if it was the AIPC staged rollout, make that
  path drain and cut over without dropping the public site; if it was not,
  find what restarted the HEL1 stack. Highest priority, because it hit a
  customer-facing enabled domain.
- Fix the `aipc-crawler-staged` `/.local` permission failure so the crawler can
  write its job files.
- Reclaim Docker storage on `pitchai-main` before the 200 GiB guard trips —
  365 images with 90 dangling and ~250 GB reclaimable — and repair
  `pitchai-potai-staging-release-cleanup`, which has now failed every night for
  a week.
- Give `pitchai-main` swap and memory a real owner: swap 100% for a fifth
  review, available memory down to 8.4 GB.
- Settle the HEL1 ACME account and where `skybuyfly.pitchai.net` is
  authoritative before **2026-10-19**.
- Root-cause the AFASAsk overnight band before a fourth night, and make
  enabled-test failures page even when the aggregate stays green.
- Restore `www-data` write access to `/var/log/pitchai-nginx-events-bus` so the
  00:00 `[emerg]` burst stops, and clear the remaining Events Bus publishers.
- Provision the isolated GitHub runner on `aipc-fsn1-01` and confirm the
  2026-09-25T04:30Z reboot was planned.
- Standing items unchanged: the `dashboards.pitchai.net`,
  `support.pitchai.net` and `agentcloud.pitchai.net` dead upstreams,
  `cursussen.pitchai.net` and the five `jeff-*` routes,
  the `dispatch.pitchai.net` API contract streak, the `whatsapp.pitchai.net` QR
  expiry, the monitor meta cycle, the `dft-worker-green` container-health false
  positive, and the enabled/disabled drift for `afasask.pitchai.net` and
  `afasask_gzb_codex_medium_ok_daily`.
