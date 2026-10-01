# Daily monitoring review: 2026-10-01

## Decision

All seven enabled domains were available for the whole window, the monitor is
fresh, the proxy is clean and every certificate is valid - but the day is **not**
all clear. Two findings need a human decision, and one of them is a live product
outage:

**AFASAsk Codex mode has been broken for roughly seven hours on both surfaces.**
The production and demo canaries have failed every scheduled run since
2026-09-30T20:10Z, with `browser_infra_error=false` and a `Mislukt` screenshot on
both. The monitor's own per-domain API-contract check is failing on the same two
hosts over the same window, and a direct read of the auth broker's readiness
endpoint gives the cause: **11 accounts enabled, 0 selectable**. This is product
impact for AFASAsk users, not a monitoring artefact, and this lane cannot fix it.

**`pitchai-main` is at 92% on `/dev/md2` (135 GiB / 144.6 GB free) and its guarded
builder-cache reclaimer still hard-fails.** Yesterday's review recorded 90% /
172 GB free; the guard now fails against a 200 GiB reserve while 193 GB of
images and 97 GB of build cache are reclaimable. Also still failing:
`registry-cleanup.service` and `pitchai-potai-staging-release-cleanup.service`.

One requester-private escalation was sent to Seth van der Bijl covering both
items. No fix, no cutover and no production mutation was performed by this lane.
Live collection ran 2026-10-01T03:00-03:15Z; the evidence window is
2026-09-30T03:05Z to 2026-10-01T03:05Z.

## Enabled domains (24 h window, 684 samples each)

| Domain | OK / total | Availability | p50 / p95 HTTP | Codes |
| --- | --- | --- | --- | --- |
| `autopar.pitchai.net` | 684/684 | **100%** | 19.3 / 50.6 ms | 200 |
| `afasask.gzb.nl` | 684/684 | **100%** | 18.1 / 44.5 ms | 200 |
| `skybuyfly.pitchai.net` | 684/684 | **100%** | 127.3 / 307.3 ms | 200 |
| `deplanbook.com` | 684/684 | **100%** | 3.8 / 8.7 ms | 200 |
| `cms.deplanbook.com` | 684/684 | **100%** | 79.3 / 186.6 ms | 200 |
| `dpb.pitchai.net` | 684/684 | **100%** | 14.7 / 51.7 ms | 200 |
| `hetcis.nl` | 684/684 | **100%** | 61.6 / 103.7 ms | 200 |

**SkyBuyFly recovered completely.** Yesterday's report recorded 96.454% after
three no-drain upstream interruptions; today's window is 684/684 with 200s only,
`api_contract` `success_streak=250`, and no `no live upstreams` in the current
error-log rotation. Live probes at 03:03Z: all seven enabled names answer
(200/302/307 by design, none slower than 0.14 s) and the pinned contract probe
`curl --resolve skybuyfly.pitchai.net:443:37.27.67.52` returns **200 in 0.140 s**.
Public DNS still answers `157.180.101.33` rather than the contract address
`37.27.67.52`; that mismatch is recorded, not acted on, because this handoff is
not a DNS cutover.

Non-enabled domains moved as follows: `montrachet-demo.pitchai.net` 684/684,
`aigenda-rules.demos.pitchai.net` 684/684 and `whatsapp.pitchai.net` 684/684 all
stay recovered. The standing policy-down set is unchanged - `agentcloud.pitchai.net`
0/684 (502), `cursussen.pitchai.net` 0/684 (404), `dashboards.pitchai.net`
0/684 (502), `support.pitchai.net` 0/684 (502), `registry.pitchai.net` 0/684
(the 15 s TLS timeout is the monitor's known exclusion) and five `jeff-*` names
0/684 (ConnectError).

## Signals

`state.json` is schema **v6**, last written 2026-10-01T03:10:49Z (read back at
68 s age, `state_write_fail_streak=0`, cycle 142.8 s). Dashboard freshness
reports `status=fresh` (145.8 s against a 180 s stale threshold).
`monitoring.pitchai.net/health` returns `ok:true`; the dashboard root answers 302.

| Signal | Bad / total | Latest | Reading |
| --- | --- | --- | --- |
| `browser` | 0/685 | ok | `degraded_active=0`, `launch_fail_count=0` |
| `dns` | 0/88 | ok | `fail_streak=0`, 89 domains resolved |
| `proxy` | 0/685 | ok | `success_streak=374`, `pct_502_504=0.0`, 0 upstream events |
| `tls` | 23/23 | **failed** | 3 excluded lineages, `fail_streak=565` |
| `container_health` | 685/685 | **failed** | standing `dft-worker` false positive, `fail_streak=6991` |
| `host_health` | 685/685 | **failed** | mem 82.176%, swap **99.999%**, CPU 33.515%, load1/CPU 0.48, worst disk 87.075%, 3 violations |
| `performance` | 685/685 | failed | 45 slow domains (browser p95 exceeds the 4 000 ms threshold on all seven enabled names) |
| `red` | 685/685 | failed | 45 violations |
| `slo` | 685/685 | failed | 3 violations |
| `meta` | 685/685 | failed | 1 standing reason |

`tls`, `performance`, `red`, `slo`, `meta` and the `host_health`/`container_health`
signals are the long-standing baseline recorded in the previous reports - the
14-day history shows `host_health` with zero OK samples every day since
2026-09-18 and swap between 92.5% and 100%. `container_health` remains a
monitor-side false positive, re-verified this morning by applying the monitor's
own `include_name_patterns` to `docker ps -a`: 59 containers match, the only
non-running one is the intentionally stopped blue/green predecessor `dft-worker`
(`Exited (0)`, retired, coverage owner `583034b6`), and zero matched containers
are unhealthy, starting or restarting. `api_contract` is clean for every domain
except the two AFASAsk surfaces described below and the standing
`dispatch.pitchai.net` vhost (`fail_streak=8519`, public URL answers correctly).
`synthetic` is 0 failures everywhere.

## Finding 1 - AFASAsk Codex mode is broken (product)

### The two enabled Codex lanes

| Test | Surface | Window runs | Pass | Non-pass | `fail_streak` | Last finish |
| --- | --- | --- | --- | --- | --- | --- |
| `afasask_production_codex_medium_synthetic_ok` | `https://afasask.gzb.nl` | 46 | 33 | 13 | **13** | 2026-10-01T03:04:59Z |
| `afasask_demo_codex_fast_ok` | `https://demo.afasask.pitchai.net` | 47 | 33 | 14 | **13** | 2026-10-01T02:41:16Z |

Both lanes passed until 2026-09-30T20:10Z and have failed every scheduled run
since - production medium at 20:10, 20:45, 21:20, 21:54, 22:28, 23:02, 23:37,
00:11, 00:46, 01:21, 01:56, 02:30 and 03:04Z; demo fast at 20:15, 20:49, 21:24,
21:58, 22:32, 23:07, 23:37, 00:08, 00:39, 01:09, 01:39, 02:10 and 02:41Z. That is
between one and two hours of failure per lane per cadence slot for roughly seven
consecutive hours, across two different products and two different intensities.

This is not an infrastructure classification. Both runs carry
`browser_infra_error=false`. The production lane's 240 s `wait_for_function`
timeout is the known detection gap - the `Mislukt` block renders outside
`article[data-role="assistant"]` - and this review read the artifacts rather
than trusting the timeout: `failure.png` for run `f53f67aa-…` (finished
02:34:33Z) and run `f8473eaa-…` (finished 02:41:16Z) both show
**"Mislukt - Het is niet gelukt om Codex-modus te voltooien. Probeer het later
opnieuw."** The demo lane fails in seconds on its own marker
`afasask_demo_codex_canary_failed_marker: ❌ mislukt`.

### The monitor's own check agrees

`api_contract` has been failing continuously on both hosts since the same
2026-09-30T20:15Z event: `fail_streak=61` for `afasask.gzb.nl` and `demo.afasask.pitchai.net`,
`success_streak=0`, `last_ok=false`, with two `api_contract_degraded` events in
the dashboard's event list. The check is `codex_no_quota_readiness`, which calls
`/internal/monitor/codex-readiness` and asserts `status=ok`,
`broker_canary.status=ok` and `broker_canary.response.status=ok`.

### Root cause (read-only, from the broker itself)

A read-only GET of `/internal/monitor/codex-readiness` on both hosts at
2026-10-01T03:11Z returns **HTTP 503** with:

```
failure_stage = broker_session_overlap
error_code    = RuntimeError
safe_detail   = Codex auth broker lease failed with HTTP 409:
                {"message":"No enabled account is currently available",
                 "affinity_key":"afasask-prod-readiness",
                 "client_name":"afasask-monitor",
                 "summary":{"total_accounts":11,"enabled_accounts":11,
                            "selectable_accounts":0,
                            "selectable_standard_accounts":0,
                            "selectable_last_resort_accounts":0,
                            "last_resort_accounts":1,
                            "active_session_accounts":1,
                            "sessions_blocking_capacity":false,
                            "rate_limited_…"}}
```

Eleven accounts are enabled and **none is selectable**. That is the same
condition the auth-reset guardian classified as indeterminate on 2026-09-30
(11 accounts, 17 banked resets, 0 redeemed, mixed exhausted/positive/contradictory),
and it is the reason the Codex canaries and the readiness contract fail
together. `quota_used`, `prompt_submitted` and `generation_started` are all
`false`, so the failure happens before any prompt is submitted.

### What was and was not done

No fix was applied. Recovering the pool means redeeming banked capacity, which
is a human decision already parked in Human Review under PM task
`b2a2b3a1-faa5-4a4e-9834-a866ab7998ce` ("Redeem one banked reset on verified
organization-wide Codex exhaustion"). The related PM lane
`1f986338-0c2d-4f6e-b430-0b468acde5e2` ("Stop AFASAsk readiness probes from
manufacturing account-pool outages") is also still In Progress. This review did
not activate, pause, retire or edit any test.

## Finding 2 - `pitchai-main` root filesystem and its guard

| Metric | Now | 2026-09-30 | 2026-09-29 |
| --- | --- | --- | --- |
| `/dev/md2` used | **92%** (135 GiB free) | 90% (172 GB free) | 88% (203 GB free) |
| Worst disk reported by the monitor | 87.075% | 84.995% | 85.602% |
| Swap used | **32 734 / 33 520 MiB (99.999%)** | 100% | 99.999% |
| Memory | 82.176% used, 11.7 GiB available of 62.5 GiB | 86.003% | 85.848% |
| Load | load1 15.36 (0.48/CPU on 32 CPUs) | 7.31 (0.228/CPU) | — |

Exact bytes: 1 853 812 338 688 total, 1 614 955 388 928 used, 144 612 970 496
available. `df` reports 92% because it measures used against used-plus-available,
while the monitor's `worst_disk_used_percent` measures used against total
(87.115%); both are the same filesystem and both are rising, so the raw byte
figures above are the numbers to compare day over day.

Reclaimable space is available but the guard will not release it:

```
Images        431  266.8GB  193GB reclaimable (72%)
Build Cache  2971  109.7GB  96.96GB reclaimable
Local Volumes  20  128.2GB  27.38GB reclaimable
```

`pitchai-production-builder-cache-cleanup.service` ran again at
2026-10-01T03:59:09 CEST and exited **status 22** with
`active_cache_records_before=1` and `reclaimable_before=223.1GB` against a
200 GiB reserve - the same `guard_fail=active_cache_records:1` shape recorded
yesterday, so the guard is still blocked exactly when it is needed.
`registry-cleanup.service` failed at 03:03:52 CEST (exit 1) and
`pitchai-potai-staging-release-cleanup.service` remains failed. Outside Docker,
`/srv` holds 32 GB, `/tmp` 28 GB (mostly stale `potaito-promote-*` and
`potai-staging-deploy-*` trees) and `/var/log` 6.9 GB.

No reclamation was attempted. Deleting images, build cache or volumes crosses
the guard's own design and can break live deploys, which puts it outside this
lane's "small, clearly safe, reversible" fix budget.

## External E2E (scoped)

The registry holds **36 rows**, which are **4 schedulable recurring tests**, **3
temporarily paused** (`zz_disabled_temp_*`, `enabled=1` with
`disabled_until_ts=1893456000`, last runs from February - intentional pauses, not
scheduler failures and not current evidence) and **29 disabled**. Pass counts
below cover only the schedulable four.

Window 2026-09-30T03:12Z to 2026-10-01T03:12Z: **622 runs, 595 pass**, split as:

| Schedulable test | Runs | Pass | Non-pass |
| --- | --- | --- | --- |
| `deplanbook_cms_home_smoke_py` | 265 | 265 | 0 |
| `deplanbook_cms_on_demand_translation_py` | 264 | 264 | 0 |
| `afasask_demo_codex_fast_ok` | 47 | 33 | **14** |
| `afasask_production_codex_medium_synthetic_ok` | 46 | 33 | **13** |

The registry summary is not a health verdict and is quoted with its scope:
`status_summary` returns a hardcoded `ok: True`, leaves `enabled_tests` and
`disabled_tests` as `null`, and reports `failing_tests=4` - which is **2 enabled
rows** (the two AFASAsk lanes above) **plus 2 disabled historical
`dft_prod_exam_import_2doc_sla_daily_e2e` rows**. Both schedulable DePlanBook
tests are `effective_ok=1` with `fail_streak=0`; both AFASAsk lanes are
`effective_ok=0` with `fail_streak=13` and `success_streak=0`.

Claim-row audit: 24 rows registry-wide still sit at `error_kind='pending'` with
`started_at_ts IS NULL`, 20 of them on enabled tests (oldest 2026-03-10, newest
2026-09-24). None was scheduled in the last two hours, so they are documented
residue rather than an in-flight cycle - no claim was counted as a pass and no
cycle was left unresolved.

## Hotpath lanes (separate stream)

Kept separate from the E2E aggregate. Several lanes are stale, and a stale lane
still reads its last report's severity - the `source_sha`/`deployed_sha` below
are as old as the report, not a live deployment check.

| Lane | Severity | Failure class | Last report age | Revisions |
| --- | --- | --- | --- | --- |
| `aipc-hotpath-monitor` | **critical** | `image_refresh_trigger_not_observed` | 8.1 h | `source_sha=6efdad1ffa38`, `deployed_sha=44b6e36558ef` |
| `aipc-pedantic-e2e-ui-qa-v2` | **critical** | `RECOMMENDATION_API_DEPLOYMENT_REVISION_MISMATCH` | 31.3 h | `source_sha=e482e9e9b3a8`, `deployed_sha=8d70b334b0f1` |
| `afasask-hotpath-monitor` | warning | `synthetic_authorization_absent` | 31.5 h | `source_sha=36d6ae795b15`, `deployed_sha=a669a9d9b5a3` |
| `quickchat-ridderkerk-hotpath-monitor` | warning | `coverage_initial_rollout_incomplete` | 2.7 h | `source_sha=0f32a28930d5`, `deployed_sha=null` |
| `quickchat-walburg-hotpath-monitor` | warning | `coverage_initial_rollout_incomplete` | 2.7 h | `source_sha=0f32a28930d5`, `deployed_sha=null` |
| 11 further lanes (`autopar`, `cisnl`, `deplanbook-*`, `dft-frontend-*`, `orthoparse`, `pitchai-net`, `potaito`, `quickchat-rsr`, `quickchat-waddinxveen`, `apologetica`, `aigenda-*`) | info | — | 6.9-263.6 h | — |

The `aipc-hotpath-monitor` critical lane is newer than yesterday's warnings and
sits on the same SkyBuyFly surface that recovered in the domain lane; the
`aipc-pedantic` critical lane has not reported for 31.3 h. Hotpath state is
published independently of the E2E registry, so none of this changes the domain
or E2E readings above. `hotpath_event_outbox` holds 81 `delivered` rows - that
proves publisher delivery only and is not quoted as lane health.

## Containers, proxy, TLS, DNS, registry and ACME

- **Monitored containers**: 59 match the monitor's patterns; zero unhealthy,
  starting or restarting. The monitor stack (`service-monitoring`,
  `e2e-registry`, `e2e-runner`, `domain-incident-events`,
  `database-dependency-monitor`, `scheduler-placement-observer`) runs a new
  image `service-monitoring:5ee0d3fa7e229afb9dfe0c8590b9b02f14bf996b`
  (`PITCHAI_MONITORING_DEPLOYMENT_SHA=5ee0d3fa…`) and is up 7 h.
  Six running containers show `RestartCount>0` with no unhealthy state:
  `meilisync-formatief-toetsen` 2, and 1 each for
  `meilisync-learning-goals-custom-staging`, `meilisync-formatief-toetsen-staging`,
  `autopar-batch-stage2_5-has-braces`, `autopar-batch-stage1-download` and
  `autopar-batch-stage1-download-hp`. The `autopar-batch-*-crashloop-*`
  containers are explicit staging experiment artefacts, not monitored services.
- **No `aipc-*` or `ai_price_crawler-*` containers run on `pitchai-main`**, so no
  restart-loop check was possible there; those stacks belong to the dedicated
  host below.
- **Nginx**: `nginx -t` passes (warnings only: redefined `protocol options` and
  duplicate `server_name` entries). `nginx.service` reloaded cleanly at
  2026-10-01T03:25:09 CEST.
- **Nginx error log**, current rotation (since 2026-10-01T00:00Z): 761
  `connect() failed`, 1 `upstream prematurely closed`, **0 `no live upstreams`**
  and 0 `upstream sent too big header`. The `connect()` failures are the standing
  dead-upstream routes - `support.pitchai.net` 484 (to `127.0.0.1:8420`),
  `dashboards.pitchai.net` 277 (to `127.0.0.1:3200`), with the rest of the
  `pitchai.net` lines being generic request-body/`/.git/config` scanner noise.
  The 2026-09-30 rotation has 1 992 `connect() failed` (dashboards 1 009,
  support 983). Access-log 50x counts are not quoted as evidence on their own.
- **TLS**: every lineage is valid; the shortest is
  `staging.autopar.pitchai.net` at 30 days (2026-10-31), then
  `aardappelprijs.nl` and `akkerbouwprijs.nl` at 36 days, `deplanbook.com` and
  `orthoparse.pitchai.net` at 38, and `cms.deplanbook.com`/`dpb.pitchai.net` at
  39. `pitchai-main` holds no `skybuyfly.pitchai.net` lineage - that certificate
  is served by the AIPC front door, and the pinned probe to `37.27.67.52`
  presents `CN=skybuyfly.pitchai.net` issued by Let's Encrypt `YE1`, valid
  2026-09-29 to **2026-12-28**.
- **Registry**: direct TLS on `registry.pitchai.net:5000` presents
  `CN=registry.pitchai.net` issued by Let's Encrypt `YE1`, valid 2026-09-21 to
  2026-12-20, and
  `docker manifest inspect registry.pitchai.net:5000/pitchai/codex-runner:latest`
  succeeds.
- **DNS**: 89 domains resolved, `fail_streak=0`.
- **ACME**: `/.well-known/acme-challenge/` probes on
  `staging.formatief-toetsen.pitchai.net` (HTTP and HTTPS, pinned to
  `127.0.0.1` with `--noproxy "*"`) return webroot **404**, i.e. nginx serves the
  webroot rather than redirecting to app auth. `formatief-toetsen.pitchai.net`
  and `staging.potaito.pitchai.net` behave the same. The 2026-05-13 patch holds.
- **Decommissioned checks**: no `n8n.pitchai.net` in `sites-enabled`, no certbot
  lineage, and only the dated `sites-disabled` backups remain - no unexpected
  reappearance. The retired `afasask.gzb.nl-0001` duplicate lineage has not
  reappeared; `afasask.gzb.nl` is the only lineage for that name and is valid.

## Dedicated AIPC host `aipc-fsn1-01` (5.9.42.254)

| Check | Result |
| --- | --- |
| ICMP reachability | **reachable** - 2/2 replies, 35.8 ms RTT |
| TCP/22 | **open** |
| SSH read-only access | **not authorised** - `Permission denied (publickey)` for `root`, `ubuntu` and `admin` with the host's configured keys; no `aipc` alias exists in `/root/.ssh/config` |
| Host uptime / load / memory / disk / inodes / journal growth | **not collected** (requires SSH) |
| Failed systemd services | **not collected** (requires SSH) |
| `aipc-*` / `ai_price_crawler-*` container inventory, health and restart evidence | **not collected** (requires SSH); no such containers run on `pitchai-main` |
| Isolated GitHub runner availability, isolation and resource suitability | **not collected** (requires SSH) |

The missing SSH authorisation is recorded as missing access, **not** as proof of
health. Deep host, container and runner checks for this host stay with
`server-ops` per `monitoring/topology.yaml`; this lane made no privileged or
invasive attempt beyond a key-based batch-mode login. No DNS, certificate,
database-routing, public-API, public-traffic or production-runtime change was
made for this handoff, and public `skybuyfly.pitchai.net` traffic continues to be
evaluated against `37.27.67.52` only. PostgreSQL remains assigned to
`65.109.70.111`.

## Escalation

One requester-private Telegram message was sent to Seth van der Bijl through the
approved typed helper (`pitchai lane telegram send-private`, requester
`seth-ori`, message class `status`, route kind private, no route override, no
broad copy), idempotency key
`daily-monitoring-review-20261001-0312-private`. Delivery was verified: state
`sent`, `receipt_count=1`, receipt
`7b25963228958cd8f5fd79fd683ba102c86871a52fce33f1133e8e534b30fa5d`,
message SHA-256
`d5094e871898932b7b904046afeb8fc4d6bbb0d59f177ce83b62381acdf4c27f`. No email,
WhatsApp, group, client, vendor, public or payment message was sent, and no
credential, token or raw chat identifier was printed or stored.

## Acceptance matrix

| Surface | Verdict | Basis |
| --- | --- | --- |
| Websites (7 enabled domains) | **ready** | 684/684 each, 200-only, live probes 0.02-0.14 s |
| Monitor | **ready** | v6 state 68 s old, `/health` ok, dashboard fresh, write streak 0 |
| Containers | **ready** | 59 matched, 0 unhealthy/restarting, `dft-worker` false positive only |
| Proxy / nginx | **ready** | `nginx -t` ok, proxy 374 clean cycles, no live-upstream errors today |
| TLS | **ready** | all lineages valid, minimum 30 days, registry direct TLS ok |
| DNS | **ready** | 89 domains, 0 failures |
| External E2E | **not ready** | 2 of the 4 schedulable tests failing continuously for ~7 h |
| Dashboard | **ready** | 88.764% (54 036 / 60 876), status `attention` from the two AFASAsk events only |
| `aipc-fsn1-01` | **unknown** | reachable, but SSH-based checks unauthorised |
| AFASAsk Codex (product) | **not ready** | broker reports 0 of 11 accounts selectable |
| `pitchai-main` disk | **at risk** | 92% used, 135 GiB free, guarded reclaimer failing |

## No-change statement

This review made no production mutation. No DNS record, certificate, database
route, public API route, public traffic path or production runtime was changed;
no volume, database, artefact, log or state file was deleted, truncated, reset
or recreated; no container was restarted; and no E2E test was activated, paused,
retired or edited.
