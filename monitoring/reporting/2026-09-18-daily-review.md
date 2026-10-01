# Daily monitoring review: 2026-09-18

## Decision

**Not all-clear.** Core production is healthy, one certificate/ACME defect was
repaired, and several standing alertable degradations plus host resource
pressure remain. The current Codex/self-review agent performed this review
directly, starting 2026-09-18T13:00Z (15:00 CEST, late-day fire; the reminder
was scheduled for 03:00Z). The rolling window is the 24 hours ending
2026-09-18T13:08Z. Daily PM task `a2f1f6e4-9c3d-4d21-93b0-7c2f5a1e8d44`,
project `Repo: pitchai-monitoring`.

Repaired and verified during the review (safe, reversible, no application
data touched): `staging.formatief-toetsen.pitchai.net` lost its ACME webroot
location when today's DFT staging deploy regenerated the vhost, so HTTP
challenge requests were redirected to an HTTPS upstream that returns 502 and
every renewal attempt since 2026-09-17 failed. The location was re-applied to
the HTTP and HTTPS server blocks, `nginx -t` passed, nginx was reloaded, the
ACME probe now serves the webroot (404 without a token file), and
`certbot renew` issued a new certificate valid to 2026-12-17. `certbot.service`
is no longer failed. Backup:
`/etc/nginx/sites-disabled/staging.formatief-toetsen.pitchai.net.docker.bak.codex-acme-20260918T1310Z`.

One requester-private Telegram escalation was delivered to Seth van der Bijl
with the standing findings at 2026-09-18T13:18Z through the typed Telegram
helper (requester `seth-ori`, message class `status`, route kind `private`,
sensitive). The helper receipt and the persisted `telegram_inbound_updates`
row both show `route_kind=private` and no group reason, so there was no broad
copy. No DNS, database, application, volume, public traffic or production
runtime was changed, and nothing was deleted.

## State and core domains

State schema version 6. Final readback `updated_at=2026-09-18T13:07:21Z`, 56 s
old at first read and 110 s old at the last check; `state_write_fail_streak=0`,
`browser_degraded_active=false`, `browser_launch_last_error=null`. The monitor
container has been up 3 days. Latencies are milliseconds; slow counts use HTTP
>1500 ms and browser >4000 ms.

| Domain | OK / samples | Availability | HTTP p95 | Last sample |
| --- | ---: | ---: | ---: | --- |
| autopar.pitchai.net | 622/622 | 100% | 62.466 | 200, 14.959 ms |
| afasask.gzb.nl | 622/622 | 100% | 35.881 | 200, 16.282 ms |
| skybuyfly.pitchai.net | 622/622 | 100% | 128.503 | 200, 108.552 ms |
| deplanbook.com | 622/622 | 100% | 10.545 | 200, 3.277 ms |
| cms.deplanbook.com | 622/622 | 100% | 144.034 | 200, 53.093 ms |
| dpb.pitchai.net | 622/622 | 100% | 63.937 | 200, 7.082 ms |
| hetcis.nl | 622/622 | 100% | 71.348 | 200, 55.392 ms |
| afasask.pitchai.net | 622/622 | 100% | 61.026 | 200, 5.946 ms |

All eight domains are 4976/4976 samples = **100%** for the window. As in prior
reviews, `afasask.pitchai.net` is actively sampled although the reminder lists
it as disabled/skipped; retained as inventory drift. Fail streaks: all zero
except `staging.formatief-toetsen.pitchai.net` 578, `whatsapp.pitchai.net` 76,
and the long-standing expected-down set (cursussen/dashboards/registry/support
12980, agentcloud 12569, four Jeff names 6513).

## Signals and current sections

| Signal | 24h bad / samples | Latest evidence |
| --- | ---: | --- |
| browser | 0/622 | Healthy, degraded false, launch failures 0 |
| host_health | 622/622 | Two violations; swap 100.0%, disk 90.289%, mem 48.695%, CPU 9.267% |
| performance | 622/622 | 43 slow domains |
| slo | 622/622 | Five violations |
| red | 622/622 | 47 violations |
| tls | 24/24 | Three failures, fail streak 268 |
| dns | 89/89 | Green, success streak 92 |
| container_health | 622/622 | Six issues, fail streak 12010 |
| proxy | 0/622 | Green, success streak 3673; 427 access requests, 0% 502/504, 0 upstream events |
| meta | 622/622 | One reason, cycle 136.8 s, write-fail streak 0 |

Host snapshot: 32 CPUs, load1/CPU 0.185, memory 48.695%, swap 100.0%
(`swap_free_kb=0` of `swap_total_kb=33520636`), worst disk 90.289%. The 14-day
signal history shows swap **89.383-100%** and disk **82.756-94.323%**, i.e.
sustained swap pressure and a rising disk trend, now 96% on the host's `/dev/md2`
with 80 GB free. PM task `30784674-403b-4a0d-ac98-7a65c87e9272` (In Progress)
already tracks fleet server-space recovery and reported 94% on 2026-09-15.

The six `container_health` issues are all intentionally stopped containers:
`afasask` (exited 2 weeks), `dft-web-app-staging`, `dft-worker-staging`,
`dft-worker-green`, `dft-llm-mock-openai-staging` (2 days / 26 h) and
`orthoparse-worker` (3 weeks). No running container is unhealthy, in a restart
loop, or OOM-killed. The signal remains red purely on stopped-container
inventory, so the aggregate is red while the effective service state is fine.

Other sections: `dispatch.pitchai.net` API contract fails with success streak 0
(fail streak 5536) while its domain check passes; all nine configured
synthetics are green (success streaks 14-1445); web-vitals failures persist for
AIGenda rules/monitor, breakglass, registry and the four Jeff names; TLS
failures are `registry.pitchai.net` and the two direct-IP Jeff aliases, which
the monitor deliberately excludes from Telegram routing; DNS is green with the
topology-consistent `37.27.67.52` for public SkyBuyFly.

## Dashboard and external E2E

Rolling 24 h aggregate availability from `e2e_registry.monitor_dashboard`:
**44107/51004 = 86.478%**, 14 degraded domains of which seven are
`critical`-policy: whatsapp 85.209%, staging.formatief-toetsen 7.235%,
stable.skybuyfly 99.678%, aigenda-rules.demos 99.035%, and jeff-dispatch /
jeff-work-inbox / jeff-codex-voice at 0%. Dashboard-only zeros (expected-down
policy): registry, agentcloud, dashboards, support, cursussen and the two
direct-IP Jeff aliases.

Registry raw summary: `ok=true`, 36 tests, `failing_tests=2`, both disabled
historical `dft_prod_exam_import_2doc_sla_daily_e2e` rows. Runs scheduled in
the last 24 h: **636, all pass** — `afasask_demo_codex_fast_ok` 47,
`afasask_production_codex_medium_synthetic_ok` 47,
`deplanbook_cms_home_smoke_py` 271,
`deplanbook_cms_on_demand_translation_py` 271. Every enabled test's latest
status is `pass`; no enabled test is in a failure grace window.

Reminder/registry drift: the reminder describes
`afasask_gzb_codex_medium_ok_daily` as enabled, but the registry has
`enabled=0` for it with `last_status=fail` (last run 2026-09-03, disabled in
the same bulk update as its replacement). The enabled replacement
`afasask_production_codex_medium_synthetic_ok` covers the same production
Codex-medium path and passed 47/47 in the window, so the AFASAsk smoke coverage
itself is intact; the reminder text should be reconciled with the registry.

## Host checks (pitchai-main)

`nginx -t` passes and nginx was reloaded after the ACME fix. Ten systemd units
are in `failed` state (certbot cleared by this review); they are events-bus,
cleanup, breakglass and the HEL1 canary transport audit, none of which are
request-serving. Nginx error log over 24 h: **1872 `connect() failed`**
(support 1740, dashboards 1323, staging.formatief-toetsen 1198 occurrences of
the marker) plus three `upstream prematurely closed`. Live probes confirm
support.pitchai.net and dashboards.pitchai.net return 502 against
`127.0.0.1:8420` and `127.0.0.1:3200` where nothing listens, and
staging.formatief-toetsen.pitchai.net returns 502 against the default no-spend
slot `127.0.0.1:3202`, which has had no container since 2026-09-16 while the
opt-in spend-enabled slot on 3204 serves 200. The vhost's own routing contract
says the default must stay on 3202, so this is an application-side staging
regression owned by DFT, not a monitor artifact. `whatsapp.pitchai.net`
currently returns 401; production `formatief-toetsen.pitchai.net` returns 200
and `skybuyfly.pitchai.net` returns 200. Registry TLS on
`registry.pitchai.net:5000` is valid (CN matches, expires 2026-10-21) while
port 443 continues to present a certificate without a matching SAN (dashboard
only policy). All other Certbot lineages have at least 30 days left.

## Dedicated host: aipc-fsn1-01 (5.9.42.254)

Reachability: TCP/22 open, SSH read-only access works via the `pitchai-fsn1-01`
alias. Uptime 13 days, 8 CPUs, load 3.84-6.30 (well under capacity). Disk 24%
on `/dev/md2`, 22% on `/srv/pitchai-data`; inodes 10% and 3%; memory 4.6 GiB
used of 62 GiB with 57 GiB available; swap 495 MiB of 15 GiB (3%); journal
990.4 MB; Docker holds 3 containers, 10 volumes, 1.278 GB images and 712 MB
build cache. Seven units are failed; all are leftover one-shot proof/audit
units (`pitchai-host-audit`, three `*-20260915` proof jobs, two potaito
p9 proof jobs) rather than services that serve traffic.

Docker inventory on the host is `model-agents-md-build` and `dft-lgv-test-pg`
(running) plus `pitchai-host-mcp-main-build-20260915` (exited 137, 2 days).
**There are no `aipc-*` or `ai_price_crawler-*` containers at all on this
host**, and no AIPC service or unit. There is also **no isolated GitHub runner
unit, process, user or directory** (`actions.runner.*` absent). Both are
topology expectations for this host, so the evidence is recorded as an
unresolved inventory/ownership gap to coordinate with server-ops rather than
proof of health. The AIPC/SkyBuyFly production lane currently appears to run on
the HEL1 host: `aipc-hel1-canary-client.service` on pitchai-main is active with
`NRestarts=6`, and `aipc-hel1-canary-transport-audit.service` fails with
`ERROR: client-service-restarted`.

## Actions and escalation

Fixed: ACME webroot location in the DFT staging vhost, certificate renewal,
`nginx -t`, reload, served-certificate verification. Escalated privately with
evidence: sustained 98-100% swap and 90-96% disk on pitchai-main; DFT staging
default slot 502; AIPC container/runner absence and the failing HEL1 canary
transport audit; Jeff `critical`-policy routes down since 2026-09-06 with
`94.130.17.246` refusing 443; registry port-443 certificate mismatch. No
monitor/registry/runner restart was needed: browser health, state freshness and
state writes are all green.

## Remaining work

1. Restore or formally retire the DFT staging default no-spend slot on 3202,
   and make the deploy script preserve the ACME location it overwrote today.
2. Reduce pitchai-main swap pressure and disk usage (96%, 80 GB free) with
   server-ops; treat `/mnt/pitchai-dev-data` capacity as still unresolved.
3. Reconcile the AIPC topology contract for `aipc-fsn1-01`: either the
   containers and isolated runner belong there or the topology file and daily
   runbook need updating, and the HEL1 canary transport audit needs an owner.
4. Decide the Jeff route policy: three `critical`-policy domains are 0% with
   the host refusing connections, while their direct-IP aliases are already
   dashboard-only.
5. Reconcile reminder inventory (AFASAsk daily test disabled; dispatch API
   contract red for 5536 cycles).
