# Monitoring domain coverage sweep — 2026-08-27

## Result

The nine-day evidence sweep reconciled the monitoring inventory to **69 active domains**, **16 groups**, and **33 explicit exclusions**. Of the active entries, **63 use normal critical Telegram incident routing** and **six are dashboard-only**. No active hostname is duplicated or also present in the exclusion ledger.

The sweep found seven previously unrepresented live targets: six new `pitchai.net` Namecheap records and the dedicated AutoPAR staging web application. The two Unimix production hosts were already on `main` but absent from `staging`; they are included so both branch inventories converge on the same 69-host contract.

## Evidence scanned

The window was 2026-08-18 through 2026-08-27.

- The live-agent registry returned 355 relevant registered or saved-session sources across the three active cells (319 registered agents and 36 saved-session-only histories). The indexed agent search covered 100% of the available bytes in each cell, including the Namecheap/domain-engineering, DNS, server-fleet, Live Documents, Git LFS, AIGENDA, WhatsApp, AutoPAR, Unimix, and monitoring lanes.
- PM DB inspection covered all 82 projects, 480 tasks updated in the window, and 291 domain-relevant tasks. Candidate extraction found 588 distinct hostname-shaped strings before ownership and deployment classification.
- Local repository history covered 395 distinct commits from the six materialized repositories with current work in the window: PitchAI Infrastructure, PitchAI CLI New, PitchAI Monitoring, Suggestions Backend, Aviv Editor, and Codex Home Skills.
- Configuration evidence included Namecheap zone artifacts, Terraform and ingress configuration, Nginx/Caddy routes, deployment archives, PM reports, and live-agent handoffs.
- Runtime proof included authoritative DNS, certificate verification, HTTP contracts, container/service state, the deployed monitoring config and state, and the current Namecheap lane's 72-record authoritative `pitchai.net` snapshot. Snapshot ID `20260827T211642Z-d7dbcb644f38-af90dc1d` has SHA-256 fingerprint `d7dbcb644f38136f38e276c4b19e75c0f742f0637578bac28d67c17fb9186102`.

The production baseline at sweep start was `main` commit `75f2099a1bcf1e0ff353de449743cecc3e12476c`, deployed from image commit `d7b9c683758b8977b8747a3c8e9ca00609eaf3ae`, with 62 active checks, 19 exclusions, 15 groups, and five dashboard-only targets. `staging` began with 60 active checks and did not yet contain the Unimix pair.

## Added or reconciled alerting targets

| Domain | Evidence and public contract | Decision |
| --- | --- | --- |
| `aigenda.pitchai.net` | Namecheap A record to `37.27.67.52`; valid TLS; expected Basic-auth `401`; healthy production container | Critical |
| `aigenda-monitor.pitchai.net` | Separate Namecheap A record, ingress, data/auth boundary, and healthy synthetic-monitor container; expected `401` | Critical |
| `livedocuments.pitchai.net` | Namecheap A record to `37.27.67.52`; valid TLS; expected Bearer-auth `401`; active systemd service | Critical |
| `lfs.pitchai.net` | Namecheap A record to `95.216.7.236`; valid TLS; `/readyz` returns `200 ok`; LFS and canary services active | Critical |
| `servers.pitchai.net` | Namecheap A record to `37.27.67.52`; valid TLS; root reaches Microsoft Entra SSO; server-fleet service active | Critical |
| `theplanbook.pitchai.net` | Namecheap A record to `37.27.67.52`; valid TLS; canonical redirect to `deplanbook.com` returns `200` with `DePlanBook` content | Dashboard-only; exact alias would duplicate DePlanBook incidents |
| `autopar-staging-web.37.27.67.52.nip.io` | Dedicated persistent Nginx vhost; valid TLS; AutoPAR login surface returns `200`; web and database containers healthy | Critical |
| `unimixbrasil.com.br` | Existing `main` production contract; valid TLS; `200`; title/content identify Unimix | Critical; reconciled into `staging` |
| `www.unimixbrasil.com.br` | Existing `main` canonical alias contract; valid TLS; `200`; title/content identify Unimix | Critical; reconciled into `staging` |

The AIGENDA production and synthetic-monitor containers plus the AutoPAR staging web and database containers are also added to same-host Docker health coverage.

## Alert-disabled active targets

These six entries remain visible in dashboards and history but cannot emit Telegram downtime or recovery noise:

- `agentcloud.pitchai.net`
- `cursussen.pitchai.net`
- `dashboards.pitchai.net`
- `registry.pitchai.net`
- `support.pitchai.net`
- `theplanbook.pitchai.net`

`theplanbook.pitchai.net` is the only newly discovered live target assigned dashboard-only behavior. The Namecheap/domain-engineering lane confirmed it is an exact redirect alias of the already-critical `deplanbook.com`; retaining the check proves DNS, TLS, and redirect integrity without duplicate paging.

## Newly recorded exclusions

| Domain | Classification | Reason |
| --- | --- | --- |
| `staging.dispatch.pitchai.net` | Pending | Referenced staging route has no authoritative DNS record |
| `aigenda.37.27.67.52.nip.io` | Invalid alias | Direct-IP alias has no matching TLS identity; canonical AIGENDA is monitored |
| `aigenda-rules.135-181-182-48.sslip.io` | Replaced | Duplicate route for monitored `aigenda-rules.demos.pitchai.net` |
| `driestar-aigenda.demos.pitchai.net` | Pending | Fallback recommendation was never provisioned |
| `theplanbook.com`, `www.theplanbook.com` | Not owned | External spelling variants have no PitchAI deployment contract |
| `staging.afasask.gzb.nl` | Replaced | NXDOMAIN historical client-zone name; canonical PitchAI staging is monitored |
| `staging.hetcis.nl` | Replaced | Historical self-signed host; canonical PitchAI staging is monitored |
| `suggestions.demos.pitchai.net` | Historical | NXDOMAIN with no current ingress contract |
| `staging.potai.pitchai.net`, `staging.potato.pitchai.net` | Replaced | NXDOMAIN typo/legacy aliases; canonical Potaito staging is monitored |
| `studentenreisproduct.nl` | Not owned | External source site rather than a PitchAI deployment |
| `www.centrumvoorisraelstudies.nl`, `www.intern.centrumvoorisraelstudies.nl` | Replaced | Legacy Solcon names with invalid TLS; current HetCIS routes are monitored |

These entries are in `retired_domains`, which is a non-executable ledger and cannot create incidents or Telegram alerts.

## Fresh active inventory

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
hetcis.nl
jeff-codex-voice.pitchai.net
jeff-dispatch.pitchai.net
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
www.hetcis.nl
www.pitchai.net
www.unimixbrasil.com.br
```

## Residual observation

The sweep observed an existing alerting failure on `staging.afasask.pitchai.net` (`HTTP 500`). That hostname was already monitored with normal incident behavior and is not a coverage gap. It remains a service-health risk for the owning AFASAsk lane; the monitoring inventory must continue alerting on it.
