# Monitoring domain coverage sweep — 2026-09-02

## Result

The production inventory now contains **73 active domains**, **40 explicit exclusions**, and **16 groups**. **Sixty-five active entries use critical incident routing** and **eight are dashboard-only**. Every name is unique, the active and excluded sets do not overlap, and production reports no orphaned state domains.

Two live Jeff direct-IP aliases were the actionable coverage gaps. Both now run as dashboard-only checks because their canonical `pitchai.net` routes already carry critical incident routing. Three SkyBuyFly candidates were added to the exclusion ledger: two parked historical names and one alias with an invalid certificate contract.

The authenticated production dashboard shows both aliases healthy, with Telegram disabled, zero failure streaks, and no incidents, events, or event-bus outbox entries.

## Evidence window

The exact window was `2026-08-24T20:46:54Z` through `2026-09-02T20:46:54Z`.

- The live-agent index reported 100% byte coverage across `dev-jeff`, `dev-main`, and `dev-monitoring`: 348 session sources, about 604,500 messages, and 16,399 messages with domain-oriented candidate text.
- PM DB contained 355 updated tasks across 34 projects. A broad domain pattern matched 284 tasks across all 34 projects. A narrower hostname and DNS pattern matched 109 tasks across 26 projects.
- The production-branch code scan covered 21 repositories, 365 unique commits, and 21,777 changed text blobs. It found 61,569 hostname-shaped strings and skipped 72 blobs larger than 2 MB. PitchAI Monitoring contributed 50 recent `main` commits.
- Current Namecheap evidence contains 72 `pitchai.net` records. The `formatiefleren.nl` zone retains its apex A record and `www` CNAME.
- Classification used current DNS, TLS, HTTP, Nginx, deployment, container, monitor-state, and project evidence.

## Active targets added

| Host | Live contract | Alert policy |
|---|---|---|
| `jeff-codex-voice.94.130.17.246.nip.io` | TLS verifies for the exact hostname. The root returns the expected protected HTTP 401 without a redirect. | Dashboard-only. Canonical `jeff-codex-voice.pitchai.net` remains critical. |
| `jeff-work-inbox.94.130.17.246.nip.io` | TLS verifies for the exact hostname. Three redirects reach Microsoft Entra login with final HTTP 200 and the expected sign-in title. | Dashboard-only. Canonical `jeff-work-inbox.pitchai.net` remains critical. |

Both certificates are valid from 2026-08-31 through 2026-11-29. The alias checks retain DNS, TLS, edge, and redirect visibility. Their canonical routes own incident delivery.

## Explicit exclusions added

| Host | Classification | Evidence |
|---|---|---|
| `skybuyfly.com` | Historical, parked | Resolves to `136.144.212.108` and serves a VDX parking page. |
| `www.skybuyfly.com` | Historical, parked | Resolves to the same parked VDX surface. |
| `api.skybuyfly.com` | Invalid alias | Its public certificate does not match the hostname. |

These names appear only in `retired_domains`. They cannot run checks, create warnings, or route incidents. Canonical `skybuyfly.pitchai.net` and `stable.skybuyfly.pitchai.net` remain active and critical.

## Other candidates classified

- `course.pitchai.net`, `other.pitchai.net`, `proof.pitchai.net`, `autopar.demos.pitchai.net`, and `2ftools.pitchai.net` are fixtures, stale references, or undeployed names.
- `aipc-push.firebasestorage.app` is vendor storage. `www.studentenreisproduct.nl`, `www.driestarwartburg.nl`, and `gzb.nl` are third-party or non-owned surfaces.
- `fsx.gzb.nl` and `ask.gzb.nl` are absent from DNS. Active `afasask.gzb.nl` covers the current GZB application. DFT spelling variants, Potaito research strings, and `unimix.com.br` are replaced, invalid, or research-only candidates.
- `crm.pitchai.net` and `sales.pitchai.net` have no DNS or Namecheap records. Current CRM work uses the Dispatcher `/crm` path and has no separate monitorable hostname.

These candidates produced no additional critical monitoring target.

## Release and live proof

- [Staging PR #105](https://github.com/JoshuaSeth/pitchai-monitoring/pull/105) merged at `f1e06f6480d02b41e4a13719ea98aea91e5b05bf`.
- [Main PR #106](https://github.com/JoshuaSeth/pitchai-monitoring/pull/106) merged at `9f64879808b43b99a5d74e177f9f3cd32583c973`.
- [Deploy run 33690179236](https://github.com/JoshuaSeth/pitchai-monitoring/actions/runs/33690179236) passed its Dockerized HTTP/Playwright test job and production SSH/Docker deployment job against the exact main SHA.
- Focused inventory and config tests passed on both branch bases. Pylint scored 10.00/10. Ruff, BasedPyright, all five architecture gates, and the exact-SHA changed-file quality ratchet passed. Semgrep found no findings. The optional repository-wide zero-debt scan still reports 277 pre-existing findings outside this diff.

Production independently confirms the deployed behavior:

- `service-monitoring`, `e2e-registry`, `e2e-runner`, `database-dependency-monitor`, `domain-incident-events`, and `scheduler-placement-observer` run image `service-monitoring:9f64879808b43b99a5d74e177f9f3cd32583c973` with zero restarts.
- The deployed config reports 73 active domains, 40 exclusions, 8 dashboard-only entries, 65 critical entries, 16 groups, and no active/exclusion overlap.
- The Nginx proxy-SLO map excludes both direct-IP aliases from duplicate global proxy alerting. `nginx -t` succeeds.
- The machine dashboard endpoint returns HTTP 401 without credentials and HTTP 200 with its monitor token. The live summary shows both aliases healthy, active, and `telegram_enabled=false`. Their canonical routes remain healthy, active, and `telegram_enabled=true`.
- Each alias has 100% availability from its first retained production observation, zero failure streaks, and a real domain-series point. Neither alias appears in warnings, incidents, events, or the event-bus outbox.
- Public probes return the expected HTTP 401 for the voice alias and final HTTP 200 at Microsoft login for the work-inbox alias. TLS hostname verification succeeds for both.

## Final active inventory (73)

```text
2fa-server.37.27.67.52.nip.io
aardappelprijs.nl
afasask.gzb.nl
afasask.pitchai.net
agentcloud.pitchai.net
aigenda-monitor.pitchai.net
aigenda-rules.demos.pitchai.net
aigenda.pitchai.net
akkerbouwprijs.nl
apologetica-wagtail-staging.pitchai.net
assets.pitchai.net
auth.autopar.pitchai.net
auth.pitchai.net
autopar-staging-web.37.27.67.52.nip.io
autopar.pitchai.net
breakglass.pitchai.net
chat.pitchai.net
cms.deplanbook.com
codex-cowork.pitchai.net
codex-voice.pitchai.net
codexusage.pitchai.net
cursussen.pitchai.net
dashboards.pitchai.net
demo.afasask.pitchai.net
deplanbook.com
deplanbook.pitchai.net
dft-marketing-staging.pitchai.net
digibeat.demos.pitchai.net
dispatch.pitchai.net
dpb.pitchai.net
filedrop.pitchai.net
formatief-toetsen.pitchai.net
formatiefleren.nl
hetcis.nl
jeff-codex-voice.94.130.17.246.nip.io
jeff-codex-voice.pitchai.net
jeff-dispatch.pitchai.net
jeff-work-inbox.94.130.17.246.nip.io
jeff-work-inbox.pitchai.net
lfs.pitchai.net
livedocuments.pitchai.net
monitoring.pitchai.net
navigation.pitchai.net
onboarding-course.pitchai.net
orthoparse.pitchai.net
pitchai.net
potaito.pitchai.net
privacy-gateway-staging.pitchai.net
privacy-gateway.pitchai.net
registry.pitchai.net
route-anchor.pitchai.net
servers.pitchai.net
skybuyfly.pitchai.net
stable.skybuyfly.pitchai.net
staging.afasask.pitchai.net
staging.autopar.pitchai.net
staging.chat.pitchai.net
staging.formatief-toetsen.pitchai.net
staging.hetcis.pitchai.net
staging.potaito.pitchai.net
storage.pitchai.net
studentenreisproduct.demos.pitchai.net
suggestions.pitchai.net
support.pitchai.net
theplanbook.pitchai.net
tools.pitchai.net
unimixbrasil.com.br
whatsapp.pitchai.net
wiki.pitchai.net
www.formatiefleren.nl
www.hetcis.nl
www.pitchai.net
www.unimixbrasil.com.br
```

## Explicit exclusions (40)

```text
aigenda-rules.135-181-182-48.sslip.io
aigenda.37.27.67.52.nip.io
aipc.skybuyfly.com
api.skybuyfly.com
apologetica-react-staging.pitchai.net
app-staging-no-spend.doorstroomtoets.nl
app.doorstroomtoets.nl
autodiscover.pitchai.net
chat-staging.pitchai.net
cms.hetcis.nl
cowork.pitchai.net
demos.pitchai.net
digibead.demos.pitchai.net
driestar-aigenda.demos.pitchai.net
events.pitchai.net
hetcis.pitchai.net
jeff.codex-voice.pitchai.net
jeff.dispatch.pitchai.net
jeff.work-inbox.pitchai.net
mockopenai.pitchai.net
n8n.pitchai.net
quickchat.pitchai.net
skybuyfly.com
staging.afasask.gzb.nl
staging.dispatch.pitchai.net
staging.hetcis.nl
staging.potai.pitchai.net
staging.potato.pitchai.net
studentenreisproduct.nl
suggestions.demos.pitchai.net
theplanbook.com
unimixbr.netlify.app
weblog.hetcis.nl
www.afasask.gzb.nl
www.afasask.pitchai.net
www.centrumvoorisraelstudies.nl
www.demo.afasask.pitchai.net
www.intern.centrumvoorisraelstudies.nl
www.skybuyfly.com
www.theplanbook.com
```

## Remaining risks and next fire

At final verification, the live dashboard reported 67 healthy and six down domains. `dispatch.pitchai.net` was the only alertable-down domain. The five expected-down entries were `registry.pitchai.net`, `agentcloud.pitchai.net`, `dashboards.pitchai.net`, `support.pitchai.net`, and `cursussen.pitchai.net`, each covered by an existing dashboard-only policy. Host health, performance, SLO, container health, and metadata also remained degraded. These service-health findings remain visible and leave the sweep’s inventory decisions unchanged.

The recurring three-day reminder is the durable follow-up. Its next scheduled fire is `2026-09-05T20:44:32.573496Z`.

This reminder fire prohibited Telegram and every other outgoing message. No Telegram, email, WhatsApp, client, vendor, group, or public message was sent. The repository report and direct completion response are the reports for this fire.
