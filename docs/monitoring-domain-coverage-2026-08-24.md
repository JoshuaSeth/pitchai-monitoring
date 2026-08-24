# Monitoring domain coverage audit — 2026-08-24

## Outcome

The production inventory expands from 10 configured domains (9 enabled) to 58 enabled domains in 14 project/system groups. Nineteen non-live, non-canonical, non-HTTP, pending, or not-owned names are retained as classified exclusions instead of becoming expected-live checks.

The reviewed inventory is executable configuration, not a separate documentation list: `domain_checks/config.yaml` is consumed by the minute HTTP/browser loop, DNS and TLS checks, API subchecks, dashboard service/group health, incidents, rolling history, and E2E allowlisting.

## Domain engineer coordination

I asked the PitchAI live-agent lane `domain-engineer-namecheap-dns` for the authoritative domain/subdomain inventory and safe public readiness contracts. The first handoff (2026-08-24 17:57–18:04 UTC) reconciled the Namecheap zone, live Nginx/Caddy routes, running services, nonstandard ports, client zones, DFT deployments, and exclusions. It confirmed a 65-record Namecheap zone with no wildcard and fingerprint `c0c620163f9177686d7b925e7ddb3251610cb9ace2e59473eb308a4f43827913`.

I then asked the same lane for exact production Docker-socket coverage and for a decision on repo-era HetCIS candidates. The second handoff (2026-08-24 18:33–18:35 UTC) supplied every selected `pitchai-main` app/dependency container, documented the cross-host/systemd boundary, added active `www.hetcis.nl`, and classified `cms.hetcis.nl`, `weblog.hetcis.nl`, and `hetcis.pitchai.net` as non-live.

Both handoffs were appended by the lane to PM task `MONITORING-DOMAIN-COVERAGE-20260824` with their source evidence. No hostname was promoted solely from a repository string or guessed from a naming pattern.

## Authoritative source reconciliation

| Source | Evidence used | Reconciliation result |
|---|---|---|
| Domain engineer lane | Two read-only live handoffs | Canonical active set, readiness paths, ports, exclusions, runtime boundaries |
| Authoritative DNS | Namecheap 65-record snapshot, authoritative NS and client-zone probes | No wildcard; DNS-only/mail/invalid aliases do not become uptime checks |
| Repository monitoring config | Previous config and specialized check plugins | Preserved useful deep checks; removed stale `quickchat.pitchai.net` artifact |
| Nginx/Caddy/proxy config | `pitchai-main`, `pitchai-dev`, file-storage and Jeff live ingress | Canonical hostnames, redirects, protected edges, upstream failures |
| Deployment/runtime config | Docker, systemd, AX41 registry and DFT runtime | Exact selected services and nonstandard endpoint contracts |
| PM deployment records | Current deployment/decommission evidence | Expected-live failures remain alertable; `n8n` is retired |
| Live-agent/app-server registry and tools routing | Active host/lane and tools portal routes | Internal/SSO surfaces included without inventing public backend paths |
| Known client deployments | GZB, DePlanBook, HetCIS, crop-price zones | External production routes included; external hosting boundary recorded |
| Live public probes | DNS, TLS, redirect, HTTP, browser and API contract checks | Contracts verified and current failures kept visible |

## Active groups

| Group | Count | Coverage |
|---|---:|---|
| PitchAI public web | 3 | Corporate site, alias, assets |
| Platform apps | 4 | Chat production/staging, Navigation, Orthoparse |
| Operations & identity | 11 | SSO, portals, internal tools, monitoring and wiki |
| Platform infrastructure | 9 | Privacy, storage, registry and owned service routes |
| AFASAsk | 4 | Production, demo, staging and GZB |
| AutoPAR | 3 | Production and auth/staging compatibility routes |
| Formatief Toetsen (DFT) | 3 | Production, staging and SSO-gated marketing staging |
| Potaito | 2 | Protected production and staging |
| SkyBuyFly | 2 | Primary and stable lanes |
| DePlanBook | 4 | Two aliases, application and CMS |
| HetCIS | 3 | Production, production alias and PitchAI staging |
| Learning & demos | 5 | Courses, AIGENDA, DigiBeat, Studentenreisproduct, Apologetica |
| Jeff internal | 3 | Voice, Dispatcher and work inbox aliases |
| Market insights | 2 | Aardappelprijs and Akkerbouwprijs |

## DFT proof contract

- `formatief-toetsen.pitchai.net/healthz`: HTTP 200 JSON with `ok=true` and `db_ok=true`.
- `staging.formatief-toetsen.pitchai.net/healthz`: the same canonical readiness contract.
- `dft-marketing-staging.pitchai.net`: public SSO redirect chain ending at the Microsoft sign-in edge.
- The production Docker socket also covers the selected/rollback web lanes, staging lanes, workers, Redis state, search services, and DFT PgBouncers.
- `app.doorstroomtoets.nl` and `app-staging-no-spend.doorstroomtoets.nl` were explicitly confirmed not owned by PitchAI/DFT and are classified `not-owned`.

## Runtime boundary

The production monitor runs on `pitchai-main` and can inspect only that host through `/var/run/docker.sock`. Its include patterns now cover every selected long-running app and persistent dependency supplied by the domain engineer, while excluding one-shot jobs and unselected canaries. Public readiness, DNS, TLS, content and API contracts cover Docker-external routes on `pitchai-dev`, file-storage, Jeff, Azure Static Web Apps, Hostnet, and systemd services. The dashboard does not claim cross-host container visibility that does not exist.

## Intentionally excluded classes

- Retired: `n8n.pitchai.net`.
- Historical/NXDOMAIN or parking: `quickchat.pitchai.net`, `digibead.demos.pitchai.net`, `weblog.hetcis.nl`, `hetcis.pitchai.net`.
- Replaced/non-canonical: `chat-staging.pitchai.net`, `cowork.pitchai.net`, AFASAsk `www` aliases, and `cms.hetcis.nl`.
- Invalid aliases: the three dotted Jeff names and `www.afasask.gzb.nl`.
- Pending: `apologetica-react-staging.pitchai.net` until its Firebase handoff exists.
- Non-HTTP/namespace: `autodiscover.pitchai.net` and `demos.pitchai.net`.
- Not owned: the two `doorstroomtoets.nl` false positives.

## Expected attention signals at implementation time

The expanded monitor intentionally reports current failures instead of suppressing them: `agentcloud.pitchai.net`, `dashboards.pitchai.net`, `staging.afasask.pitchai.net`, and `support.pitchai.net` return 502; `cursussen.pitchai.net` returns 404 without a designated functional path; Dispatch port `24021` returns 502; and `stable.skybuyfly.pitchai.net` visibly reports that current airport products are temporarily unavailable despite returning HTTP 200. The container snapshot also found three restarting sync workers. These are operational findings, not inventory omissions.

## Pre-deployment validation

- The complete local suite passed with 186 tests passing and four intentional live-only skips.
- The production Docker image passed the same 186-test suite with four intentional skips under Python 3.12, Chromium, and Puppeteer.
- Authoritative live DNS and TLS checks passed for all 58 active domains.
- All 13 expected-up browser/deep checks passed, including both Formatief Toetsen health routes and `www.hetcis.nl`.
- A full 58-domain browser cycle produced 52 healthy primary checks and exactly the six expected primary incidents documented above. The dashboard's effective service rollup was 51/58 after it also incorporated the separate failing Dispatch API contract.
- Twelve of 15 API/service contracts passed from the development host. Two AFAS readiness checks correctly require the production-only `AFASASK_MONITOR_TOKEN`; the remaining failure is the alertable Dispatch port `24021` 502.
- Headed Chrome attached over CDP rendered all 14 groups, exactly three DFT rows, and the real incident rollup with no console errors, page errors, failed requests, or mobile overflow.

Preserved visual evidence:

- [Grouped desktop dashboard](evidence/monitoring-domain-coverage-local-desktop.png)
- [DFT-filtered desktop dashboard](evidence/monitoring-domain-coverage-local-dft.png)
- [DFT-filtered mobile dashboard](evidence/monitoring-domain-coverage-local-mobile-dft.png)
