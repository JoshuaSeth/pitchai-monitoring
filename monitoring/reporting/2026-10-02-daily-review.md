# Daily monitoring review: 2026-10-02

## Decision

All seven enabled domains were available for the whole window and the monitor
itself is fresh, but the day is **not** all clear. Three findings need an owner,
and none of them is a monitoring artefact:

1. **`pitchai-main` is at 95 % in `df` terms (98 GB free, 89.3 % of total
   bytes)** and consumed roughly 40 GB in 24 h while all three of its cleanup
   units still fail. Swap is completely full (31/31 GB) and memory sits at 87 %.
2. **`meilisync-learning-goals-custom-staging` is in a restart loop** - 1 023
   restarts, exit 137 roughly every 62 seconds, no kernel OOM entry, and its
   name is not in the monitor's container patterns, so the green container
   signal does not cover it.
3. **`aipc-fsn1-01` fails its own host audit every run** with
   `ci-runner-contract-invalid`, `ci-runner-installed-source-invalid` and
   `deploy-authorized-key-policy-invalid`, and its Docker maintenance refuses to
   run while the retained HDD cold tier is quarantined.

Good news carried forward: the AFASAsk Codex outage escalated yesterday has
**recovered**. Both canaries pass again with 39 and 34 consecutive successes
after failing until 2026-10-01T06:42Z (demo) and 09:12Z (production).

One requester-private escalation was sent to Seth van der Bijl covering the
three findings above. No fix, no reclamation, no cutover and no production
mutation was performed by this lane. Live collection ran
2026-10-02T03:00-03:10Z; the evidence window is 2026-10-01T03:05Z to
2026-10-02T03:05Z.

## Enabled domains (24 h window, 569-570 samples each)

| Domain | Samples | OK | HTTP median | Browser median | Codes |
| --- | --- | --- | --- | --- | --- |
| `autopar.pitchai.net` | 569 | 569 (100 %) | 23.5 ms | 12 706.7 ms | 200 (+1 transient 502) |
| `afasask.gzb.nl` | 569 | 569 (100 %) | 20.8 ms | 14 313.2 ms | 200 |
| `skybuyfly.pitchai.net` | 569 | 569 (100 %) | 120.7 ms | 14 895.7 ms | 200 |
| `deplanbook.com` | 569 | 569 (100 %) | 4.2 ms | 12 204.4 ms | 200 |
| `cms.deplanbook.com` | 569 | 569 (100 %) | 117.5 ms | 8 501.6 ms | 200 |
| `dpb.pitchai.net` | 569 | 569 (100 %) | 17.5 ms | 12 897.7 ms | 200 |
| `hetcis.nl` | 569 | 569 (100 %) | 63.0 ms | 17 508.2 ms | 200 |

One `autopar.pitchai.net` sample recorded a 502 while every sample in the window
still resolved `effective_ok=true`; it is a single transient, not a degraded
domain. Browser medians remain in the 8.5-17.5 s range, which is what keeps the
`performance` signal red (threshold 4 000 ms) - a standing baseline, see
Signals.

Live probes agree: HTTP checks return 200/302/307 in under 0.14 s. The pinned
contract probe `curl --resolve skybuyfly.pitchai.net:443:37.27.67.52` returns
**200 in 0.161 s** with `CN=skybuyfly.pitchai.net` (Let's Encrypt `YE1`, valid
2026-09-29 to 2026-12-28). Public DNS still answers `157.180.101.33` rather than
the contract address `37.27.67.52`; that mismatch is recorded, not acted on,
because this handoff is not a DNS cutover. PostgreSQL remains assigned to
`65.109.70.111`.

## Standing down and excluded set (unchanged)

The dashboard reports `service_health` of 89 enabled domains: 78 healthy, 11
down, of which 7 are expected/policy-down and **4 are alertable**
(`alertable_down=4`). Every one of the four is a documented standing condition:

- `dispatch.pitchai.net` - HTTP answers 302/200 (570/570 samples OK) while its
  `api_contract` check stays red at `fail_streak=8758`; recorded in the
  2026-09-30 report as "public URL answers correctly".
- `jeff-codex-voice.pitchai.net`, `jeff-dispatch.pitchai.net`,
  `jeff-work-inbox.pitchai.net` - `ConnectError: All connection attempts
  failed`, part of the five-name `jeff-*` set documented in previous reports.

Expected/excluded: `registry.pitchai.net` 0/570 (`ConnectTimeout` after 15 s -
the monitor's known exclusion, see Proxy/TLS/registry below),
`agentcloud.pitchai.net` 0/570 (502), `dashboards.pitchai.net` 0/570 (502),
`support.pitchai.net` 0/570 (502), `cursussen.pitchai.net` 0/570 (404), and the
two `jeff-*` `.nip.io` aliases.

## Finding 1 - `pitchai-main` disk, memory and failing cleanup units (escalated)

`/dev/md2` (mounted `/`) holds 1 853 812 338 688 bytes, of which
1 655 085 592 576 are used and **104 482 766 848 are available**: `df` reports
**95 %**, the monitor's `used/total` reading is **89.28 %**. Yesterday the same
figures were 1 614 955 388 928 used and 144 612 970 496 available (92 % in `df`
terms), so roughly **40 GB was consumed in 24 h**.

The guarded reclaimer still hard-fails, and its two neighbours still fail too:

| Unit | Last exit | Result |
| --- | --- | --- |
| `pitchai-production-builder-cache-cleanup.service` | 2026-10-02 03:41:16 CEST | exit **22** |
| `registry-cleanup.service` | 2026-10-02 03:02:23 CEST | exit **1** |
| `pitchai-potai-staging-release-cleanup.service` | 2026-10-02 04:41:27 CEST | exit **1** |

Docker accounts for most of the growth: images 313 GB with **239.3 GB
reclaimable**, build cache 120.7 GB with **108 GB reclaimable**, volumes 128.2 GB
with 27.43 GB reclaimable, containers 8.85 GB with 2.67 GB reclaimable.
Yesterday the same figures were 266.8 GB of images and 109.7 GB of build cache.

Memory pressure is chronic and now total: `swap_used_percent=100.0` with
`swap_free_kb=0` of a 32 GB swap device, `mem_used_percent=87.165`, CPU 44.449 %,
load1 19.67 across 32 CPUs (`load1_per_cpu=0.615`). The 14-day history in
`state.json` shows swap between 92.46 % and 100 % and the worst-disk reading
between 68.31 % and 99.33 %, so this is a sustained condition rather than a
spike - and the rule that sustained swap above ~90 % is escalation-worthy
applies regardless of the host-health signal's own verdict.

Kernel evidence: the `journalctl -k` window contains per-cgroup OOM kills from
2026-10-01 20:32-20:46Z. Cross-checking the killed cgroups shows they are
bounded batch containers (`autopar-batch-stage4-par-*` at its 6 GB memcg limit,
plus two already-removed transient batch containers), i.e. expected per-container
limits rather than host exhaustion. That distinction is recorded so nobody reads
the OOM lines as proof that the meilisync loop below was OOM-killed - it was not.

No reclamation, prune, truncate or deletion was attempted by this lane.

## Finding 2 - `meilisync-learning-goals-custom-staging` restart loop (escalated)

`docker inspect` reports `RestartCount=1023`, `status=restarting`, exit code
**137**, `OOMKilled=false`, restart policy `unless-stopped`, and **no memory
limit**. The container logs one `Start increment sync data from
"SourceType.postgres" to MeiliSearch...` line roughly every 62 seconds and then
dies; the latest cycle ran 2026-10-02T03:01:07.878Z to 03:01:09.974Z.

- `journalctl -k` contains **zero** entries for this container's cgroup, so this
  is not a cgroup OOM kill.
- At a ~62 s cadence, 1 023 restarts correspond to roughly **17.6 hours of
  looping**, placing the start around **2026-10-01 09:20Z** (derived, not
  observed - `docker inspect` keeps only the latest cycle).
- The monitor's own `container_health` patterns do **not** include
  `meilisync-learning-goals-custom-staging` (they cover
  `^meilisync-formatief-toetsen(?:-staging)?$`), so the monitor is blind to this
  loop. Its siblings `meilisync-formatief-toetsen` and
  `meilisync-formatief-toetsen-staging` show 3 restarts each and are running.

Because the cause is unknown and the container owns search-index state, this is
escalated rather than restarted or edited from the monitoring lane.

## Finding 3 - `aipc-fsn1-01` self-audit failures and quarantined cold tier (escalated)

Read-only root SSH access to `5.9.42.254` is now available (yesterday it was
`Permission denied (publickey)` for root/ubuntu/admin), so the full shallow
evidence set was collected. The host itself is healthy; two units are not:

- `aipc-host-audit.service` failed at **2026-10-02T03:02:13Z** reporting
  `ci-runner-contract-invalid`, `ci-runner-installed-source-invalid`,
  `deploy-authorized-key-policy-invalid`, plus
  `installed byte mismatch: /usr/local/sbin/aipc-deploy-ssh-dispatch`.
- `aipc-docker-maintenance.service` has been failing since **2026-10-01
  03:43:56Z** with `refusing maintenance while the retained HDD cold tier is
  quarantined` (exit 1, timer-triggered).

The isolated GitHub runner is a **dedicated KVM pool VM**, not a host unit:
`aipc-ci-runner-pool-vm.service` is active with 0 restarts and runs
`qemu-system-x86_64 -name aipc-fsn1-ci-pool ... -smp 8 -m 32768` on
`/var/lib/aipc-ci-runner/pool/root.qcow2` (48.7 GB, owned by `aipc-ci-vm`). It
lives in `aipc-runners.slice`, whose limits are high 28 GB / max 36 GB, and the
slice has peaked at **3.0 GB** with 25 GB still available - comfortable on a
12-CPU host with 104 GB memory available. The `aipc-ci-runner-vm.service`
variant is inactive by design, and no `actions.runner.*` systemd unit exists on
the host. So availability and resource suitability are good while the audit's
*contract* checks fail - which is exactly what server-ops needs to reconcile.

## Signals

`state.json` is schema **v6**, last written 2026-10-02T03:04:08Z (26 s old at
read time, `state_write_fail_streak=0`, cycle 146.7 s).
`monitoring.pitchai.net/health` returns `ok:true`; the dashboard reports
`freshness.status=fresh` (26 s against a 180 s stale threshold) and
`daily_status` 88.764 % availability (45 030 of 50 730 observations) with status
`attention`, 11 problem events and 13 recoveries.

| Signal | Bad / total | Latest | Reading |
| --- | --- | --- | --- |
| `browser` | 7/569 | ok | `degraded_active=0`, `launch_fail_count=0` |
| `dns` | 0/89 | ok | `fail_streak=0`, 89 domains resolved |
| `proxy` | 7/569 | ok | `success_streak=247`, `pct_502_504=0.0`, 0 upstream events |
| `tls` | 24/24 | **failed** | 3 excluded lineages retained in signal, `fail_streak=589` |
| `container_health` | 567/567 | **failed** | standing `dft-worker` false positive, `fail_streak=7557` |
| `host_health` | 569/569 | **failed** | mem 87.165 %, swap **100 %**, CPU 44.449 %, load1/CPU 0.615, worst disk 89.25 %, 3 violations |
| `performance` | 564/569 | failed | 44 slow domains (browser p95 above 4 000 ms) |
| `red` | 556/569 | failed | 46 violations |
| `slo` | 569/569 | failed | 3 violations |
| `meta` | 564/569 | failed | 1 standing reason, `state_write_fail_streak=0` |

`tls`, `performance`, `red`, `slo`, `meta`, `host_health` and `container_health`
are the long-standing baseline recorded in previous reports. `container_health`
was re-verified this morning by applying the monitor's own
`include_name_patterns` to the Docker API: **59 containers match, exactly one is
non-running** - the intentionally stopped blue/green predecessor `dft-worker`,
`Exited (0)` since 2026-09-28 - and **zero matched containers are unhealthy,
starting or restarting**. `api_contract` is clean everywhere except the two
AFASAsk surfaces during their outage window and the standing
`dispatch.pitchai.net` vhost. `synthetic` is 0 failures on all nine checked
names.

## External E2E (scoped)

The registry holds **36 rows: 4 schedulable recurring tests, 3 temporarily
paused** (`zz_disabled_temp_*`, `enabled=1` with `disabled_until_ts=1893456000`)
**and 29 disabled**. `status_summary` still returns a hardcoded `ok=true` with
`failing_tests=2`; those two are the *disabled* `dft_prod_exam_import_2doc_sla_daily_e2e`
rows, so the enabled failing count is **0**.

Window 2026-10-01T03:05Z to 2026-10-02T03:05Z: **624 runs, 605 pass**, split as

| Test | Runs | Pass | Non-pass | Last pass | Streak |
| --- | --- | --- | --- | --- | --- |
| `deplanbook_cms_home_smoke_py` | 266 | 263 | 3 `infra_degraded` | 303 s ago | ok 3364 |
| `deplanbook_cms_on_demand_translation_py` | 265 | 265 | 0 | 292 s ago | ok 1171 |
| `afasask_demo_codex_fast_ok` | 47 | 39 | 8 `fail` | 550 s ago | ok **39** |
| `afasask_production_codex_medium_synthetic_ok` | 46 | 38 | 8 `fail` | 1 277 s ago | ok **34** |

All 19 non-passes sit in the 2026-10-01T03:05-09:25Z band - the tail of the
Codex outage escalated yesterday - and there has been no non-pass in the last
~17.5 hours. The outage failures are the ones already root-caused on
2026-09-30/10-01 (auth broker `broker_session_overlap`, "no enabled account is
currently available"; the demo lane failing on its `❌ mislukt` marker in
1.4-10 s and the production lane on its 240 s `wait_for_function` timeout with
`browser_infra_error=false`). Both lanes are now green, so the recovery is the
headline and no further escalation was raised for it.

A read-only `GET` of `https://afasask.gzb.nl/internal/monitor/codex-readiness`
now returns **401 Unauthorized** from this lane, i.e. the endpoint is no longer
readable unauthenticated as it was yesterday; the authoritative evidence for
this path is the two canaries plus `api_contract` (`success_streak=52` on both
`afasask.gzb.nl` and `demo.afasask.pitchai.net`), not that probe.

Claim-row audit: **24 rows still sit at `error_kind='pending'` with
`started_at_ts IS NULL` registry-wide, 20 of them on enabled tests**, all at
least 172.9 h old and unchanged from yesterday's count - residue, not an active
claim, and never counted as a pass. Outbox: 82 entries, all `delivered`, which
proves publisher delivery only.

## Hotpath lanes (separate stream)

16 lanes, 219 reports (128 ok). Kept out of the E2E aggregate above:

- **critical** - `aipc-hotpath-monitor` (`image_refresh_trigger_not_observed`,
  `fail_streak=24`, last report **32.1 h** ago, source `6efdad1` / deployed
  `44b6e36`): the lane has stopped reporting, and a stopped lane still reads
  `critical` rather than stale-on-its-own. `aipc-pedantic-e2e-ui-qa-v2`
  (`RECOMMENDATION_API_DEPLOYMENT_REVISION_MISMATCH`, `fail_streak=14`, 7.3 h,
  source `9af148e` / deployed `44b6e36`).
- **warning** - `afasask-hotpath-monitor` (`synthetic_authorization_absent`,
  55.5 h), `deplanbook-play-hotpath-monitor` (`incomplete_coverage`, 8.0 h, new
  since yesterday), `quickchat-ridderkerk-hotpath-monitor` and
  `quickchat-walburg-hotpath-monitor` (`coverage_initial_rollout_incomplete`,
  26.7 h each).
- **info** - 12 lanes, all `current_success=1`, with last-report ages from
  4.7 h to **287.6 h**; the two `aigenda-*` and `quickchat-rsr` lanes are the
  stalest and are called out explicitly because `info` alone hides that.

## Containers, proxy, TLS, DNS, registry and ACME

- **Monitored containers**: 59 match the monitor's patterns; zero unhealthy,
  starting or restarting; the only non-running match is the retired `dft-worker`
  standby (see Signals). The monitor stack (`service-monitoring`,
  `e2e-registry`, `e2e-runner`, `domain-incident-events`,
  `database-dependency-monitor`, `scheduler-placement-observer`) runs image
  `service-monitoring:a3dc66eaf1430de0796deb311c6dd6b569776890`, deployed
  2026-10-01T20:04:39Z, and is up 7 h with 0 restarts. Containers currently
  running with `RestartCount>0`:
  `meilisync-learning-goals-custom-staging` **1023** (Finding 2),
  `meilisync-formatief-toetsen-staging` 3, `meilisync-formatief-toetsen` 3,
  `scheduler-placement-observer` 1, `autopar-batch-stage1-download` 1 and
  `autopar-batch-stage1-download-hp` 1.
- The `registry` container itself was restarted at 2026-10-02T02:30:13Z (uptime
  31 min at collection, `RestartCount=0`, image `registry:2`) - noted so the
  change of uptime is not mistaken for a crash loop.
- **Proxy**: `nginx -t` is successful (one warning, a conflicting
  `chat-staging.pitchai.net` server name on :443). Today's error log holds 373
  `connect() failed` and 2 `recv() failed`, and **zero** `no live upstreams`,
  `upstream prematurely closed` or `upstream sent too big header`. The
  `connect() failed` lines are dominated by the two known dead localhost
  upstreams: `support.pitchai.net` 246 hits (port 8420) and
  `dashboards.pitchai.net` 127 hits (port 3200), unchanged from the 2026-05-18
  record. The `pitchai.net` lines are `[warn]`-level GitHub webhook body
  buffering plus 190 `access forbidden`, not upstream failures. The proxy signal
  itself is green: `access_total=526`, `pct_502_504=0.0`, 0 upstream error
  events, `success_streak=247`.
- **TLS**: every certbot lineage is **VALID**; the shortest are
  `aardappelprijs.nl` and `akkerbouwprijs.nl` at 35 days, then
  `deplanbook.com`/`orthoparse.pitchai.net` 37, `cms.deplanbook.com`/`dpb.pitchai.net`
  38 and `chat.pitchai.net` 43. Nothing is inside the 14-day threshold. The
  `tls` signal is red only because of the standing excluded lineages.
- **Registry**: direct TLS on `registry.pitchai.net:5000` presents
  `CN=registry.pitchai.net` from Let's Encrypt `YE1`, valid 2026-09-21 to
  2026-12-20, and
  `docker manifest inspect registry.pitchai.net:5000/pitchai/codex-runner:latest`
  succeeds. HTTPS on **:443** still presents the default
  `CN=2fa-server.37.27.67.52.nip.io` certificate because that hostname has no
  nginx vhost of its own; that is the monitor's known expected/excluded
  condition (0/570) recorded since at least 2026-09-27, not a new regression,
  and it is why the monitor's own exclusion is the right reading rather than the
  raw failure count.
- **DNS**: 89 domains resolved, `fail_streak=0`.
- **ACME**: `/.well-known/acme-challenge/` probes on
  `staging.formatief-toetsen.pitchai.net` (HTTP and HTTPS, `--noproxy "*"`)
  return webroot **404** from `/var/www/letsencrypt`, i.e. nginx serves the
  webroot rather than redirecting to app auth - the 2026-05-13 patch holds.
  `formatief-toetsen.pitchai.net` answers 303 and `staging.potaito.pitchai.net`
  answers 401 for both the probe path and `/`, i.e. those two vhosts simply have
  no ACME location and are consistently app responses, not a regression.
- **Decommissioned checks**: no `n8n.pitchai.net` runtime, routing or certbot
  reappearance; the retired `afasask.gzb.nl-0001` duplicate lineage has not
  returned and `afasask.gzb.nl` remains the single valid lineage.

## Dedicated AIPC host `aipc-fsn1-01` (`5.9.42.254`)

Reachability: ICMP 2/2 with 0 % loss (34.5 ms average) and TCP/22 open; root SSH
succeeds, `ubuntu` and `admin` still return `Permission denied (publickey)`.

| Check | Result |
| --- | --- |
| Uptime / load | 6 days 22:32, load 2.10 / 2.01 / 2.42 on 12 CPUs |
| Filesystems | `/dev/md2` 921 GB, 583 GB used, 292 GB free, **67 %**; `/boot` 23 %; `/srv/aipc-cold` 3 % |
| Inodes | `/` 6 % (3 554 588 of 61 390 848); `/boot` 1 %; `/srv/aipc-cold` 1 % |
| Memory / swap | 20 GB used of 125 GB, 104 GB available; swap 2.0 MiB of 16 GB |
| Journal growth | 1.9 GB total - no growth risk |
| Docker storage | images 55.2 GB (23.33 GB reclaimable), containers 78.6 MB, volumes 0 B, build cache 0 B |
| Failed services | **2** - `aipc-host-audit.service`, `aipc-docker-maintenance.service` (Finding 3) |
| AIPC containers | 5 running and healthy (`aipc-shadow-stable`, `aipc-shadow-primary`, `aipc-pgbouncer`, `aipc-meilisearch`, `aipc-qdrant`), all `restarts=0`; 9 `*-staged` containers sit in `created` state awaiting activation |
| Isolated runner | `aipc-ci-runner-pool-vm.service` active, 0 restarts, KVM VM with 8 vCPU and 32 GB inside `aipc-runners.slice` (peak 3.0 GB of 28 GB); no host `actions.runner.*` unit |

Server-ops coordination is required for the two failed units, the runner
contract mismatch and the cold-tier quarantine. No privileged, invasive or
deep remediation was attempted, and **no cutover, DNS, certificate, database
routing, public API, public traffic or production-runtime change was made for
this handoff**.

## Coordination, fixes and mutations

- **Escalation**: one requester-private Telegram to Seth van der Bijl via the
  typed helper (`requester=seth-ori`, `message-class=status`, route kind
  private, idempotency key
  `daily-monitoring-review-20261002-0320-private`). Delivery verified:
  `state=sent`, `receipt_count=1`, `receipt_ref=d41ba487…`. No other outgoing
  message was sent - no email, WhatsApp, group, client, vendor or public
  message, and no broad copy.
- **Fixes applied**: none. No safe cautious fix was available or needed:
  certificates are valid, the monitor state is fresh and no monitored container
  was stale or hung.
- **Not done on purpose**: no disk reclamation or prune (guarded cleanup is
  failing, and deletion is out of scope), no restart of the meilisync container
  (unknown cause, search-index state), no AIPC remediation (server-ops), no test
  activation/pause/retirement or edit in the E2E registry.

## Evidence window and deliverable

Collection ran 2026-10-02T03:00-03:10Z against a 24 h evidence window of
2026-10-01T03:05Z to 2026-10-02T03:05Z. PM task
`7da76f88-d9e6-4fe2-a3ef-c9d06e18416f` ("Daily monitoring review 2026-10-02")
under `Repo: pitchai-monitoring` holds the full changelog evidence.
