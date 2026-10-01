# Daily monitoring review: 2026-09-27

## Decision

Six of the seven enabled domains returned a clean 24-hour window and the
external E2E lane was **completely clean** for the first time in a week: 636
passes, zero failures, including both AFASAsk Codex canaries. `nginx -t`
passes, the ACME webroot, n8n-absence and duplicate-lineage checks are as
expected, the registry certificate is valid into December, and the dedicated
AIPC host is healthy with its VM runner pool live.

Two things keep the day off "all clear". **`skybuyfly.pitchai.net` dipped for a
third consecutive night**, and this time the cause is provable: the public
front door `aipc-hel1-01` rebooted itself at 04:30-04:32Z under
unattended-upgrades auto-reboot, so every kernel update takes the customer-facing
SkyBuyFly entry point down for a few minutes. Separately, the
`scheduler-placement-observer` container has failed **every** cycle since the
2026-09-26 21:15Z deploy, which is why every `main` deploy gate stays red — and
the missing piece of that puzzle is now measured rather than guessed.

Disk is at 88% with the reclamation tripwire about 10.6 GiB away, swap is
pegged at 100% for a sixth consecutive review, and the SkyBuyFly certificate is
at 22 days with renewal still failing. No fix was applied in this lane; one
requester-private escalation was sent.

Live collection ran 2026-09-27T03:00-03:20Z.

## Enabled domains (24 h window, 706 samples each)

| Domain | OK / total | Availability | p95 HTTP | Median HTTP | Codes |
| --- | --- | --- | --- | --- | --- |
| `autopar.pitchai.net` | 706/706 | 100% | 52.8 ms | 19.1 ms | 200 |
| `afasask.gzb.nl` | 706/706 | 100% | 39.4 ms | 17.1 ms | 200 |
| `skybuyfly.pitchai.net` | 704/706 | **99.717%** | 174.7 ms | 114.5 ms | 200, 502, null |
| `deplanbook.com` | 706/706 | 100% | 8.4 ms | 3.7 ms | 200 |
| `cms.deplanbook.com` | 706/706 | 100% | 198.5 ms | 76.4 ms | 200 |
| `dpb.pitchai.net` | 706/706 | 100% | 49.9 ms | 14.2 ms | 200 |
| `hetcis.nl` | 706/706 | 100% | 70.5 ms | 60.7 ms | 200 |

Dashboard-derived `daily_status` reads **86.936%** (51 707 / 59 477, 2 problem
events, 2 recoveries, status `attention`) — an improvement on yesterday's
86.195% and now diluted almost entirely by the standing policy-down routes:
`dispatch.pitchai.net`, `whatsapp.pitchai.net` (503),
`registry.pitchai.net` (see below), `agentcloud.pitchai.net` (502),
`dashboards.pitchai.net` (502), `support.pitchai.net` (502),
`cursussen.pitchai.net` (404) and the five `jeff-*` names. The only real
problem events in the window are the two SkyBuyFly samples below.

## SkyBuyFly: third night, and now the cause is known

Both SkyBuyFly hostnames failed together and recovered together:

| Time (UTC) | `skybuyfly.pitchai.net` | `stable.skybuyfly.pitchai.net` |
| --- | --- | --- |
| 04:31:59 | 502 after 7 173 ms | 502 |
| 04:33:54 | HTTP 200, browser check failed (11.5 s) | HTTP 200, browser check failed |
| 04:35:59 | recovered | recovered |

Monitor events: `domain_down` at 04:31:59Z for both names, `domain_up` at
04:35:59Z. That is 2 of 706 samples each, leaving both lanes at 99.717%.

**Root cause: the front-door host rebooted.** `skybuyfly.pitchai.net` resolves to
`157.180.101.33` (`aipc-hel1-01`), and that host's boot record shows
`Sat Sep 26 04:32:23 UTC` — inside the failure window to the minute. It carries
`Unattended-Upgrade::Automatic-Reboot "true"` with
`Automatic-Reboot-Time "04:30"`, and the reboot installed kernel
`6.8.0-139` → `6.8.0-142` (utilities/upgrades at 04:30:00, shutdown at 04:32:24).
The same host rebooted on 2026-09-13 04:31 and 2026-09-07 04:32, so this is a
recurring nightly-reboot pattern rather than a one-off crash: every kernel
update silently takes the public SkyBuyFly entry point down for a few minutes.
That also explains why the earlier 2026-09-25 23:16-23:29Z outage and the second
dip at 02:23-02:28Z bracketed a staged-stack rollout on the same host.

Current state: pinned probe against `37.27.67.52` returns **200 in 0.137 s**, the
unpinned probe returns 200 in 0.113 s via `157.180.101.33`, and
`stable.skybuyfly.pitchai.net` returns 200 in 0.169 s. The served certificate is
unchanged. Public traffic continues to be evaluated against `37.27.67.52` per
the topology contract; no DNS, certificate or routing change was made.

## Scheduler observer: why every `main` deploy gate is red

`scheduler-placement-observer` restarted with the 2026-09-26T21:15:11Z deploy and
has logged **1 399 failed cycles since** (latest 03:04:52Z), every one ending in
`TimeoutError` inside `monitoring_v2/scheduler_incident_gateway.py`
`read_scheduler_json()` at `connection.getresponse()`.

The missing evidence is that the feed itself is slow, not unreachable:

| Probe through the observer's own network namespace | Result |
| --- | --- |
| `GET /internal/global-api/v2/directory` | 200 in 0.25 s |
| `GET /internal/global-api/v2/scheduler/new-lane-transitions` (no query) | 200 in **20.5 s** |
| `GET /internal/global-api/v2/scheduler/new-lane-transitions` (observer query) | 200 in **20.4 s** |

The observer's configured request timeout is 10 s (the deploy passes
`SCHEDULER_INCIDENT_POLL_SECONDS=15` but no
`SCHEDULER_INCIDENT_FEED_TIMEOUT_SECONDS`, and the code default is `10`), so a
~20.5 s feed response can never satisfy the deploy gate's "healthy poll"
assertion. The tunnel (`pitchai-cli-thomas-central-tunnel.service` →
`94.130.17.246:8128`) is healthy and answers the directory endpoint in
milliseconds, so the latency is on the central feed path, not the transport.
This matches the open PM task
`4d2c8f61-7a53-4e0b-9c8e-2f6b1d0a7e93` ("Monitoring main deploy gate fails on
the scheduler-placement observer healthy poll", Todo, unassigned), whose open
question was exactly why the poll times out. The last green `main` deploy was
run 35595830566 on 2026-09-21T11:46Z; every deploy since has rolled the new
image out successfully and then failed this check.

No restart or configuration change was attempted: restarting the container
cannot fix a 20.5 s upstream response, and changing the timeout is a
deploy-configuration change on the production monitoring stack.

## Signals

`state.json` is schema **v6**, last written 2026-09-27T03:00:32Z. Dashboard
freshness reports a 99-second age against a 180-second stale threshold with a
60-second interval, and `state_write_fail_streak` is 0.

| Signal | Bad / total | Latest | Reading |
| --- | --- | --- | --- |
| `browser` | 0/706 | ok | `degraded_active=false`, no launch failures |
| `dns` | 0/88 | ok | — |
| `proxy` | **0/706** | ok | clean all window, `pct_502_504` 0.0%, 0 upstream error events |
| `container_health` | 706/706 | **failed** | `dft-worker-green` still `Exited (0)` since 2026-09-21 |
| `host_health` | 706/706 | **failed** | memory 86.719%, swap 100.0%, 3 violations |
| `tls` | 24/24 | **failed** | 3 failures per cycle on Telegram-excluded domains |
| `performance` | 706/706 | failed | 44 slow domains |
| `red` | 706/706 | failed | 45 violations |
| `slo` | 706/706 | failed | 4 violations |
| `meta` | 706/706 | failed | 1 reason, 119.7 s cycle |

The sustained set is unchanged in composition from yesterday. Two causes remain
known and benign: `container_health` is the `dft-worker-green` false positive
(exited cleanly five days ago, `docker ps --filter health=unhealthy` is empty
and no container is in a restart loop), and `tls` covers the three domains the
monitor already routes away from Telegram (`registry.pitchai.net`,
`jeff-codex-voice` and `jeff-work-inbox`) whose own certificate is verified
valid below. `host_health` is the one that keeps degrading — see below.

## Host: pitchai-main disk, memory and swap

`/dev/md2` is now at **88% with 212 GB free**, down from 87% / 217 GB yesterday
and 86% / 236 GB two days ago. Memory is 86.719% (54 572 MiB of 64 039) with
**9 466 MiB available** — slightly better than yesterday's 8 360 MiB. **Swap is
fully consumed again**: 32 734 MiB of 32 734 MiB, 0 free, 100 kB residual; that
is the sixth consecutive review above the 90% escalation threshold.

| Location | Size | Note |
| --- | --- | --- |
| Docker images | **207.8 GB** | **375 images**, 148.4 GB reclaimable, **111 dangling** (was 90) |
| Docker build cache | 104.1 GB | 2 666 entries, 91.4 GB reclaimable |
| Docker volumes | 128.2 GB | 27.38 GB reclaimable |
| Containers | 11.98 GB | 199 total, 155 running |

Reclamation still does not fire. `pitchai-production-builder-cache-cleanup` ran
at 03:41:37 CEST with `available_before=226190966784` (210.6 GiB) against its
200 GiB reserve and concluded `status=reserve-satisfied`, so it took no action —
the margin is now about **10.6 GiB**, down from roughly 15.6 GiB yesterday and
shrinking by ~5 GiB per day. `pitchai-potai-staging-release-cleanup.service`
failed again at 04:31:11 CEST with the same retention-floor refusal
(`retained=0 minimum=20 total=24`). `logrotate.service` completed successfully
for a third consecutive night. Nothing was deleted, pruned, rotated or
restarted from this lane.

## Nginx, proxy and logs

`nginx -t` passes. Since the 00:00 CEST rotation the error log holds **302**
`connect() failed` entries for `support.pitchai.net` and **271** for
`dashboards.pitchai.net` (both still dead upstreams on `localhost:8420` /
`:3200`, both re-probed at 502), 14 for `pitchai.net`, and the recurring
**102-line `[emerg] Permission denied`** burst on
`/var/log/pitchai-nginx-events-bus/error.log` at 00:00:02 — the third night of
the same logrotate-owned-permission issue (the directory is recreated
`root:root 700` while nginx workers run as `www-data`). Access-log 50x counts are
573 `502` and no `504`, dominated by the monitoring bot's own probes of the
policy-down routes plus scanner paths such as `/xex.php`.

The proxy signal itself was **clean for the entire window** (0/706 bad,
`pct_502_504` 0.0%, 0 upstream error events) for the second consecutive day.

## TLS, ACME and certificates

- `registry.pitchai.net:5000` direct TLS serves CN `registry.pitchai.net` from
  Let's Encrypt `YE1`, valid 2026-09-21 to **2026-12-20**, and
  `docker manifest inspect registry.pitchai.net:5000/pitchai/codex-runner:latest`
  succeeds, so auto-dispatch is intact. (The monitor's HTTP check on
  `https://registry.pitchai.net/` still times out after 15 s because the
  registry answers on port 5000, not 443 — this is the long-standing entry in
  the Telegram-excluded TLS set, not a new failure.)
- **`skybuyfly.pitchai.net` is now at 22 days**, expiring
  **2026-10-19T03:35:18Z**, and `certbot.service` failed again at
  2026-09-26 20:07:28 CEST with `1 renew failure(s)` on exactly that lineage.
  `stable.skybuyfly.pitchai.net` is fine at 52 days. The renewal deadlock is
  still unresolved: public DNS points at `157.180.101.33` (whose own
  `certbot.service` is also failed) while `pitchai-main` holds the lineage and
  cannot answer the challenge.
- ACME webroot routing for `staging.formatief-toetsen.pitchai.net` is intact:
  a missing challenge file returns **404 from the webroot on both HTTP and
  HTTPS**, not an auth redirect.
- `n8n.pitchai.net` shows no reappearance (no enabled site, no lineage), and the
  removed `afasask.gzb.nl-0001` duplicate has not returned.

## Dedicated AIPC host: `aipc-fsn1-01` (5.9.42.254)

Reachable over SSH (read-only, `BatchMode`); booted 2026-09-25T04:30:55Z.

| Area | Evidence |
| --- | --- |
| Load / CPU | load 12.38 on **12 CPUs**; 30 GiB of 125 GiB memory used, 95 GiB available; swap 0 B of 16 GiB |
| Disk | `/dev/md2` **28%** (243 GB used, 632 GB free); `/srv/aipc-cold` 1% of 1.8 TB; `/boot` 23% |
| Inodes | 5% on `/`, 1% on the cold store |
| Journal | 1.7 GB archived + active |
| Docker storage | 116 images / 55.2 GB (23.33 GB reclaimable), 16 containers (5 active), 0 volumes, 0 build cache |
| Containers | 5 running and healthy with **0 restarts** since boot (`aipc-shadow-primary`, `aipc-shadow-stable`, `aipc-pgbouncer`, `aipc-meilisearch`, `aipc-qdrant`); 10 `aipc-*-staged` containers exist in `created` state (prepared, never started) |
| Failed units | 2 — `aipc-docker-maintenance.service`, `aipc-host-audit.service` |
| Runner | `aipc-ci-runner-pool-vm.service` **active** since 2026-09-25T04:31:27Z, qemu-system-x86 VM at 2.91 GB inside `aipc-runners.slice` (12 tasks, 1 773 s CPU); `aipc-ci-runner-vm.service` and `aipc-ci-runner-host-egress.service` are inactive one-shot helpers by design |

Runner availability and isolation are therefore confirmed by a different
instrument than the runbook's `actions.runner.*` probe: this host runs a
VM-pool runner, not systemd runner units, and there are no runner containers.
It is isolated to the `aipc-ci-vm` account and the dedicated `aipc-runners.slice`,
and the host has ample CPU, memory, disk and inode headroom to carry it.

The earlier "no runner units" reading in previous reviews was an artefact of
probing only for `actions.runner.*`; recorded here as a correction.

## SkyBuyFly front door: `aipc-hel1-01` (157.180.101.33)

Read-only diagnostic for incident attribution: booted 2026-09-26T04:32:23Z (the
auto-reboot above), load 3.03, `/dev/md2` 76% (104 GB free), AIPC containers up
22 hours, one failed unit (`certbot.service`). DNS for `skybuyfly.pitchai.net`
still resolves here rather than to the contract address `37.27.67.52`; recorded
as an escalation signal, not as permission to change DNS.

## External E2E

Registry summary: `ok=true`, **36 tests, 7 enabled**, `failing_tests=2`. Both
aggregate failures are the disabled historical
`dft_prod_exam_import_2doc_sla_daily_e2e` rows, unchanged for months; no enabled
test has a non-pass `last_status`.

Runs in the 24 h window: **636 pass, 0 fail** — the first fully clean E2E day
this week (yesterday: 628 pass / 4 fail).

| Enabled test | Latest | Streak | Elapsed |
| --- | --- | --- | --- |
| `afasask_demo_codex_fast_ok` | pass (02:56Z) | 54 | 13 647 ms |
| `afasask_production_codex_medium_synthetic_ok` | pass (02:49Z) | 53 | 11 946 ms |
| `deplanbook_cms_home_smoke_py` / `deplanbook_cms_on_demand_translation_py` | pass | — | — |
| three `zz_disabled_temp_*` | pass (February records) | 0/1 | stale inventory entries |

The reminder's named `afasask_gzb_codex_medium_ok_daily` remains `enabled=0` with
`last_status=fail` and the explicit 2026-09-03 retirement reason; its active
replacement, `afasask_production_codex_medium_synthetic_ok`, passed every run in
the window. The overnight AFASAsk failure pattern that ran for three nights
(2026-09-22, 09-24, 09-25) **did not recur**.

## Topology compliance and actions

- Public SkyBuyFly web/API traffic was evaluated against `37.27.67.52` only
  (pinned probe 200 in 0.137 s), with the DNS answer recorded separately.
- PostgreSQL remains assigned to `65.109.70.111`; no database routing changed.
- `5.9.42.254` was treated as a non-public dedicated host: shallow read-only
  checks only, no DNS, certificate, public-API, traffic or PostgreSQL action.
- No cutover or production mutation was made, and this handoff stayed internal.
- No fix was applied in this lane. One requester-private Telegram escalation was
  sent to Seth van der Bijl covering the SkyBuyFly auto-reboot root cause, the
  scheduler-observer feed latency, the disk/swap trend, and the SkyBuyFly
  certificate renewal failure.

## Recommended follow-ups

1. Stop the SkyBuyFly front door from rebooting underneath customer traffic —
   either move the public entry point back to the contract address, or give
   `aipc-hel1-01` a maintenance window with draining instead of
   `Automatic-Reboot "true"` at 04:30.
2. Raise `SCHEDULER_INCIDENT_FEED_TIMEOUT_SECONDS` above the observed ~20.5 s
   feed latency (the parser accepts 1-60 s) or fix the central feed latency, then
   confirm a `main` deploy completes with its fail-closed checks green
   (PM task `4d2c8f61`).
3. Renew or re-home `skybuyfly.pitchai.net` before 2026-10-19, and reconcile the
   ACME account split between `pitchai-main` and the front door.
4. Treat `pitchai-main` disk as the next operational cliff: the guard is ~10.6
   GiB from its 200 GiB reserve and falling by ~5 GiB per day while 148 GB of
   reclaimable image data and 111 dangling images accumulate.
