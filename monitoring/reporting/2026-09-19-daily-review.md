# Daily monitoring review: 2026-09-19

## Decision

**Not all-clear.** Core production is healthy again after the 2026-09-19
pitchai-main disk-exhaustion incident, and the monitor, registry and runner are
fresh and green on the signals that gate them. Several open items remain, one
of them time-boxed:

- **SkyBuyFly certificate renewal is broken at both ends.** Public DNS for
  `skybuyfly.pitchai.net` now returns `157.180.101.33` (the AIPC HEL1 front
  door), and the HEL1 certbot cannot renew the lineage
  (`Account at /etc/letsencrypt/accounts/acme-v01.api.letsencrypt.org/... does
  not exist`), while pitchai-main's certbot fails because Let's Encrypt
  validates the challenge on HEL1 and gets a 404. The served certificate
  expires **2026-10-19 (29 days)** and nothing currently renews it.
- **DNS/topology mismatch.** `monitoring/topology.yaml` pins public SkyBuyFly
  evaluation to `37.27.67.52`, while authoritative DNS returns the HEL1
  address. The daily runbook states a resolved-address mismatch is an
  escalation signal, not permission to change DNS, so DNS was left untouched.
- **pitchai-main swap is at 100%** (2.7 MB free of 32 GB), sustained at
  89-100% for 14 days.
- **Breakglass events-bus fails every ~5 minutes** with
  `Breakglass JSON audit line is malformed`, and that same prerotate hook made
  `logrotate.service` fail at 2026-09-20T00:00Z, so log rotation is currently
  blocked.
- **Two `critical`-policy demo routes flap** on pitchai-dev
  (`aigenda-rules.demos.pitchai.net/readyz` 503 in 10/612 samples,
  `montrachet-demo.pitchai.net` 500 in 6/612 samples, including samples at
  2026-09-20T03:11Z); both pass direct probes now. The root cause is already
  identified outside this lane: pitchai-dev (135.181.182.48) ran out of disk
  again at 03:06-03:11Z (fourth recurrence on the same fingerprint), the
  monitor escalated it once itself, and recovery was verified at 03:15:56Z.
  The durable headroom work is tracked in PM task
  `c4f8b1d2-6a3e-4c7d-8f21-5d9e0b7a3c88` (Human Review). This lane's SSH key
  is refused on that host, so no independent host-level reading was possible.

This review was performed directly by the current Codex/self-review agent.
Reminder fire `reminder-20260630T073139899030-3b53242d@2026-09-19T030000z` was
executed 2026-09-20T02:56Z (04:56 CEST) and the rolling window is the 24 hours
ending 2026-09-20T03:16Z. Daily PM task `c41d9f0a-7b52-4e63-9a10-5f8de2c3b7aa`,
project `Repo: pitchai-monitoring`.

No infrastructure was changed this run: nothing met the small/safe/reversible
bar, `/data` is intact, and the monitor, registry and runner are all healthy,
so no container restart was warranted. One requester-private Telegram
escalation was delivered to Seth van der Bijl (details under *Actions*).

## State and core domains

State schema version 6, final readback `updated_at=2026-09-20T03:15:54Z` (well
inside the 5-minute freshness target), `state_write_fail_streak=0`,
`browser_degraded_active=false`, `browser_launch_last_error=null`. Latencies
are milliseconds; HTTP p95 is over the window's successful HTTP samples.

| Domain | OK / samples | Availability | HTTP p95 | Last sample |
| --- | ---: | ---: | ---: | --- |
| autopar.pitchai.net | 612/612 | 100% | 64.1 | 200, 12.9 ms |
| afasask.gzb.nl | 612/612 | 100% | 40.4 | 200, 18.2 ms |
| skybuyfly.pitchai.net | 612/612 | 100% | 130.2 | 200, 76.3 ms |
| deplanbook.com | 612/612 | 100% | 10.9 | 200, 2.5 ms |
| cms.deplanbook.com | 380/612 | 62.092% | 199.0 | 200, 72.7 ms |
| dpb.pitchai.net | 612/612 | 100% | 99.7 | 200, 8.3 ms |
| hetcis.nl | 612/612 | 100% | 70.4 | 200, 56.6 ms |
| afasask.pitchai.net | 612/612 | 100% | 68.4 | 200, 21.2 ms |

`cms.deplanbook.com` (and `privacy-gateway.pitchai.net`,
`apologetica-wagtail-staging.pitchai.net`) returned 500 for every sample from
2026-09-19T05:09Z to 14:50Z — the pitchai-main disk-exhaustion window tracked
by PM task `b7d4e2a9-3c11-4f0e-9a5b-2d8c7f6e1a40` — and have been green since
14:50Z; the 62% figure is that incident, not a current fault.
`afasask.pitchai.net` continues to be actively sampled although the reminder
lists it as disabled/skipped (known inventory drift, retained as evidence).

Other domain state: `staging.formatief-toetsen.pitchai.net` is 612/612
effective-OK (607×200, 5×502 within tolerance) after the 2026-09-18 ACME fix;
`whatsapp.pitchai.net` is 0/612 (503 `qr_expired` on `/readyz` all window,
`critical` policy, long-standing); `registry.pitchai.net` is 0/612 (443
connect timeout, expected dashboard-only); `cursussen.pitchai.net` 404;
`support.pitchai.net` and `dashboards.pitchai.net` 502 (dashboard-only);
the three canonical Jeff names are 0% with `ConnectError` (critical policy)
plus their two dashboard-only direct-IP aliases.

## Signals and current sections

| Signal | 24h bad / samples | Latest evidence |
| --- | ---: | --- |
| browser | 0/612 | Healthy, degraded false, launch errors none |
| proxy | 0/612 | Green, success streak 715; latest cycle 367 access requests, 0% 502/504, 0 upstream events |
| dns | 0/91 | Green, no failures |
| container_health | 283/612 (all early-window) | Currently green, fail streak 0; one container with restart count 1, no restart loops |
| host_health | 612/612 | `[ok=0, mem 51.8%, swap 99.99%, cpu 9.6%, load1/cpu 0.384, disk 68.386%, violations 1]` |
| performance | 612/612 | 42 slow domains |
| red | 612/612 | 48 violations |
| slo | 612/612 | 6 violations |
| tls | 23/23 | 3 failures, fail streak 305 |
| meta | 612/612 | 1 reason, cycle 136.6 s against a 60 s interval, write-fail streak 0 |

Current sections: `tls` fail streak 305 with 3 standing failures
(`registry.pitchai.net` and the two direct-IP Jeff aliases, deliberately
excluded from Telegram routing). API contract still red for
`dispatch.pitchai.net` (fail streak 5881, success streak 0) while its domain
check passes; `afasask.gzb.nl`, `codexusage.pitchai.net` and
`demo.afasask.pitchai.net` show fail-streak 1 with recovered events at
2026-09-19T14:57Z. All nine configured synthetics are green (success streaks
37-1556). Web-vitals failures persist for `aigenda-monitor` (159),
`breakglass.pitchai.net` (188) and the Jeff names. The
`database-dependencies` artifact (v2, generated 2026-09-20T03:16:15Z) reports
45 dependencies, 27 healthy and 18 non-healthy, but `alertable_down_count=0`
and `pending_alerts=[]`; the non-healthy set is probe
coverage/configuration gaps (`container_inventory_gap`,
`probe_runtime_missing`, `docker_exec_create_http_409`, two
`credential_missing`) with two `critical`-flagged probe findings
(`autopar-auth` `probe_configuration_invalid` and
`deplanbook-legacy:deplanbook-play` `database_or_pgbouncer_unreachable`) worth
an owner review.

## Dashboard and external E2E

Rolling 24 h dashboard aggregate from `e2e_registry.monitor_dashboard`:
**42743/50184 = 85.173%**, 82 domains, `ok=true`. Warnings list 14 down
domains (montrachet-demo, dispatch, whatsapp, registry, agentcloud,
dashboards, support, cursussen, aigenda-rules.demos and the four Jeff names)
and degraded signals `host_health, performance, slo, red, tls, meta`.
`critical`-policy domains below 99.5%: whatsapp 0%, jeff-codex-voice /
jeff-dispatch / jeff-work-inbox 0%, privacy-gateway 62.09%,
cms.deplanbook.com 62.09%, apologetica-wagtail-staging 62.25%,
aigenda-rules.demos 98.53% and montrachet-demo 99.18% (both driven by the
pitchai-dev ENOSPC recurrences tracked in `c4f8b1d2`).
Dashboard-only zeros (expected-down policy): registry, agentcloud, dashboards,
support, cursussen and the two direct-IP Jeff aliases.

Registry summary: `ok=true`, 36 tests, `failing_tests=2` — both the disabled
historical `dft_prod_exam_import_2doc_sla_daily_e2e` rows. **No enabled test
currently has a non-pass `last_status`.** Runs in the window: 598 total, with
failures confined to the incident window — `deplanbook_cms_home_smoke_py`
160 pass / 95 fail, `deplanbook_cms_on_demand_translation_py` 159/95,
`afasask_demo_codex_fast_ok` 24/20 and
`afasask_production_codex_medium_synthetic_ok` 37/8. Last failures were
14:23-14:47Z on 2026-09-19; passes resumed and the latest passes are
2026-09-20T02:44-03:10Z (the AFASAsk production Codex-medium smoke passed on
its most recent run).

Reminder/registry drift (unchanged from 2026-09-18):
`afasask_gzb_codex_medium_ok_daily` is `enabled=0` with `last_status=fail`
(last run 2026-09-03); the enabled replacement
`afasask_production_codex_medium_synthetic_ok` covers the same production
Codex-medium path and is passing, so AFASAsk smoke coverage is intact.

## Host checks (pitchai-main)

Uptime 202 days; 32 CPUs, load 8.27/12.39/12.41; memory 31/62 GB used; **swap
31/32 GB (2.7 MB free, 99.99%)**. `/dev/md2` is **73%** (1.2 TB used, 459 GB
free) — recovered from the 96% / ENOSPC state of 2026-09-19 — with inodes at
8%. `nginx -t` passes (one benign `chat-staging.pitchai.net` conflicting-name
warning). No container is unhealthy or restarting; `service-monitoring`,
`e2e-registry` and `e2e-runner` have been up 33 hours. Fourteen systemd units
are failed: the breakglass path/service, `aipc-hel1-canary-transport-audit`,
`certbot.service`, `logrotate.service`, `lxd-installer`, nginx/redis/snapd
events-bus units, three systemd-events-bus instances, the potAI staging
cleanup and one transient `nft` helper.

Nginx error log over 24 h: **1375 `connect() failed`** (537 to
`127.0.0.1:8420` for support, 529 to `127.0.0.1:3200` for dashboards, the rest
scanner paths such as `/.env`, `/.git/config`, `wp_mail_smtp.ini` on the same
dead upstreams), **12 `upstream prematurely closed`** (5 × potAI
`127.0.0.1:13140` asset requests, 7 × DFT `127.0.0.1:43202` healthz/UI
requests) and no `no live upstreams`, no `upstream sent too big header`, and
no SkyBuyFly premature-close pattern. Live probes: `monitoring.pitchai.net`
health 200, support 502, dashboards 502, whatsapp readiness 503, cursussen 404,
`registry.pitchai.net` 443 presents the unrelated `2fa-server...nip.io`
certificate (long-standing dashboard-only mismatch).

TLS/renewal: `registry.pitchai.net:5000` serves a valid CN-matching
certificate (to 2026-10-21) and `docker manifest inspect` against the registry
succeeds. `staging.formatief-toetsen.pitchai.net` ACME webroot probes return
404 on HTTP and HTTPS (the 2026-05-13 fix still holds). The
`afasask.gzb.nl-0001` duplicate lineage has not reappeared and
`afasask.gzb.nl` is valid for 64 days. The one broken lineage is
`skybuyfly.pitchai.net` (expires 2026-10-19): pitchai-main's certbot logged
`Failed to renew certificate skybuyfly.pitchai.net ... Some challenges have
failed` at 2026-09-19T15:44Z because the HTTP-01 challenge is now served by
HEL1, and HEL1's certbot fails with the missing ACME account. Other lineages
have 30+ days (deplanbook.pitchai.net 30, dashboards 37, cursussen 38).

`n8n.pitchai.net` shows no reappearance: only the 2026-05-12 disabled backups
in `/etc/nginx/sites-disabled`, no enabled vhost, no certbot lineage, no
runtime. PostgreSQL on `65.109.70.111` is unchanged and its 5432 port is open
from pitchai-main. No `aipc-*` or `ai_price_crawler-*` containers exist on
pitchai-main either, so there is no crawler restart-loop evidence to assess
there.

## Dedicated host: aipc-fsn1-01 (5.9.42.254)

Reachable; read-only SSH works through the `pitchai-fsn1-01` alias. Uptime
14 days 15 h, 8 CPUs, load 20.5/20.3/20.6 — high for 8 CPUs but steady, and
memory is comfortable (3/62 GiB used, 58 GiB available; swap 1/15 GiB).
`/dev/md2` 38% (270 GB free, inodes 14%); `/srv/pitchai-data` 31% (890 GB
free, inodes 4%). Journal 994.5 MB, flat versus the 2026-09-18 reading
(990 MB). Docker holds 8 images / 2.08 GB, 4 containers / 82 MB, 25 volumes
(973 MB reclaimable) and 712 MB build cache.

Containers: `wi-fixture-pg`, `model-agents-md-build` and `dft-lgv-test-pg`
running; `pitchai-host-mcp-main-build-20260915` exited 137 four days ago.
**There are still no `aipc-*` or `ai_price_crawler-*` containers and no
`actions.runner.*` unit/user/directory**, so the container-inventory and
isolated-runner expectations in `monitoring/topology.yaml` cannot be verified
on this host. That is recorded as an unresolved inventory/ownership gap to
coordinate with server-ops (topology PM task `e13a891e-7aed-4225-a370-92da1d4ebdd3`,
in Human Review) — missing access or missing services is not treated as proof
of health. Seven units are failed: `pitchai-agent-node-health.service` (new),
`pitchai-host-audit.service`, three 20260915 proof jobs and two potaito p9
proof jobs; none serve traffic. No privileged, invasive or deep check was run.

Public SkyBuyFly checks were pinned to the contract address: `--resolve`
`skybuyfly.pitchai.net:443:37.27.67.52` returns 200 for `/` (0.25 s) and
200 for `/api/health`, with the served certificate CN `skybuyfly.pitchai.net`
valid 2026-07-21 → 2026-10-19. The default DNS path resolves to
`157.180.101.33` and also returns 200. The resolved-address mismatch against
`37.27.67.52` is recorded as an escalation signal; DNS, certificates,
database routing, public traffic and production runtime were not touched, and
PostgreSQL remains assigned to `65.109.70.111`. HEL1's canary pair shows the
standing split: `aipc-hel1-canary-client.service` active with `NRestarts=6`,
and `aipc-hel1-canary-transport-audit.service` failing every 5 minutes with
`ERROR: client-service-restarted`.

## Actions and escalation

Fixed: nothing. No safe fix was identified this run — the certificate path
requires an ACME account repair on another host, the DNS question is a
contract decision, the swap/logrotate items need server-ops ownership, and
touching the malformed breakglass audit log or any state file is out of scope.
The monitor, registry and runner are healthy and `/data` is intact, so no
container restart was justified.

Escalated: one requester-private Telegram message was sent to Seth van der
Bijl through the typed Telegram helper (requester `seth-ori`, message class
`status`, route kind `private`, sensitive) covering the skybuyfly
renewal/DNS mismatch, pitchai-main swap and logrotate/breakglass failure, the
pitchai-dev SSH authorization gap with the two demo routes that flap on top of
the tracked ENOSPC recurrences (`c4f8b1d2`), and the standing whatsapp QR,
dispatch API-contract, monitor-meta, Jeff and AIPC inventory items. The
monitor's own alert path had already delivered its single Montrachet incident
escalation for the 03:06Z recurrence, so this review message is the daily
summary rather than a duplicate alert. No other message was sent, no group copy
was created, and no secrets were included.

## Remaining work

1. Repair the HEL1 ACME account (or the validation path) so
   `skybuyfly.pitchai.net` renews before 2026-10-19; server-ops owns this and
   it must not be fixed from the monitoring lane.
2. Reconcile `monitoring/topology.yaml` with the live SkyBuyFly routing, or
   restore the contract address — the dedicated HEL1 cutover decision sits
   with PM task `1fd6ade4-a142-40df-8174-66122c429cde` (Human Review).
3. Reduce pitchai-main swap pressure with server-ops; repair the malformed
   breakglass audit line so `pitchai-breakglass-events-bus` and
   `logrotate.service` recover (log data must not be edited from this lane).
4. Obtain SSH authorization for pitchai-dev (135.181.182.48) and investigate
   the intermittent 500/503 responses behind `montrachet-demo.pitchai.net` and
   `aigenda-rules.demos.pitchai.net/readyz` from this lane; the host-side cause
   is the tracked disk-headroom problem `c4f8b1d2`, which now needs a
   capacity/retention decision rather than further monitor-side reclaiming.
5. Standing items: `dispatch.pitchai.net` API contract (5881 cycles),
   monitor `meta` cycle overrun (136.6 s), the Jeff `critical` routes at 0%,
   whatsapp bridge QR expiry, and the AIPC container/runner inventory gap on
   `aipc-fsn1-01`.
