# Monitoring domain coverage audit — 2026-08-24

## Outcome

The production inventory expands from 10 configured domains (9 enabled) to 59 enabled checks in 14 project/system groups: 58 PitchAI-owned domains/subdomains plus one explicitly labelled PitchAI-operated, non-owned-DNS 2FA route. Nineteen other non-live, non-canonical, non-HTTP, pending, or not-owned names are retained as classified exclusions instead of becoming expected-live checks.

The reviewed inventory is executable configuration, not a separate documentation list: `domain_checks/config.yaml` is consumed by the minute HTTP/browser loop, DNS and TLS checks, API subchecks, dashboard service/group health, incidents, rolling history, and E2E allowlisting.

## Domain engineer coordination

I asked the PitchAI live-agent lane `domain-engineer-namecheap-dns` for the authoritative domain/subdomain inventory and safe public readiness contracts. The first handoff (2026-08-24 17:57–18:04 UTC) reconciled the Namecheap zone, live Nginx/Caddy routes, running services, nonstandard ports, client zones, DFT deployments, and exclusions. It confirmed a 65-record Namecheap zone with no wildcard and fingerprint `c0c620163f9177686d7b925e7ddb3251610cb9ace2e59473eb308a4f43827913`.

I then asked the same lane for exact production Docker-socket coverage and for a decision on repo-era HetCIS candidates. The second handoff (2026-08-24 18:33–18:35 UTC) supplied every selected `pitchai-main` app/dependency container, documented the cross-host/systemd boundary, added active `www.hetcis.nl`, and classified `cms.hetcis.nl`, `weblog.hetcis.nl`, and `hetcis.pitchai.net` as non-live.

Both handoffs were appended by the lane to PM task `MONITORING-DOMAIN-COVERAGE-20260824` with their source evidence. No hostname was promoted solely from a repository string or guessed from a naming pattern.

During production-base reconciliation, current `main` also supplied the already-deployed `2fa-server.37.27.67.52.nip.io` health/readiness plugin and `twofa-server-prod` container selector. The same domain-engineer lane rechecked that route live and classified it as an active PitchAI-operated exception whose `nip.io` parent is not PitchAI-owned; it remains monitored but is not counted among the 58 owned hostnames.

I asked the lane once more after the first production-shaped DFT deep-check cycle saw a single staging `502`. The lane matched it to a deployment startup window: Nginx recorded one upstream reset at 19:27:47 UTC, after the replacement container started at 19:27:26 UTC and before all 32 Uvicorn workers finished startup at 19:27:52–19:27:55 UTC. It then observed no recurrence, zero restarts or OOMs, and 12 public plus 12 loopback probes returning `200 {"ok":true,"db_ok":true}`. The DFT staging monitor therefore remains enabled and strict; nothing was suppressed or reclassified.

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
| Platform infrastructure | 10 | Privacy, storage, registry, 2FA readiness and owned service routes |
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

The production monitor runs on `pitchai-main` and can inspect only that host through `/var/run/docker.sock`. Its include patterns now cover every selected long-running app and persistent dependency supplied by the domain engineer, plus the production-main `twofa-server-prod` route preserved during release reconciliation, while excluding one-shot jobs and unselected canaries. Public readiness, DNS, TLS, content and API contracts cover Docker-external routes on `pitchai-dev`, file-storage, Jeff, Azure Static Web Apps, Hostnet, and systemd services. The dashboard does not claim cross-host container visibility that does not exist.

## Intentionally excluded classes

- Retired: `n8n.pitchai.net`.
- Historical/NXDOMAIN or parking: `quickchat.pitchai.net`, `digibead.demos.pitchai.net`, `weblog.hetcis.nl`, `hetcis.pitchai.net`.
- Replaced/non-canonical: `chat-staging.pitchai.net`, `cowork.pitchai.net`, AFASAsk `www` aliases, and `cms.hetcis.nl`.
- Invalid aliases: the three dotted Jeff names and `www.afasask.gzb.nl`.
- Pending: `apologetica-react-staging.pitchai.net` until its Firebase handoff exists.
- Non-HTTP/namespace: `autodiscover.pitchai.net` and `demos.pitchai.net`.
- Not owned: the two `doorstroomtoets.nl` false positives.

## Expected attention signals at implementation time

The expanded monitor intentionally reports current failures instead of suppressing them: `agentcloud.pitchai.net`, `dashboards.pitchai.net`, `staging.afasask.pitchai.net`, and `support.pitchai.net` return 502; `cursussen.pitchai.net` returns 404 without a designated functional path; and Dispatch port `24021` returns 502. `stable.skybuyfly.pitchai.net` initially reported that current airport products were temporarily unavailable despite HTTP 200, but recovered before the final pre-deployment cycle. The container snapshot also found three restarting sync workers. These are operational findings, not inventory omissions.

## Pre-deployment validation

- The staging-derived integration suite passed with 186 tests and four intentional live-only skips. After reconciling onto current production `main`, its complete 142-test graph passed locally with four intentional skips.
- The exact main-derived production Docker image passed the same 142-test suite with four intentional skips under Python 3.12, Chromium, and Puppeteer.
- Authoritative live DNS and TLS checks passed for all 59 active checks, including the production-base 2FA route.
- All 14 expected-up browser/deep checks passed, including both Formatief Toetsen health routes, the production 2FA readiness exception, `codexusage.pitchai.net`, and `www.hetcis.nl`.
- The final full 59-check browser cycle produced 54 healthy primary checks and exactly the five current primary incidents documented above. The separate failing Dispatch API contract remains part of the dashboard's effective service rollup.
- Twelve of 15 API/service contracts passed from the development host. Two AFAS readiness checks correctly require the production-only `AFASASK_MONITOR_TOKEN`; the remaining failure is the alertable Dispatch port `24021` 502.
- Headed Chrome attached over CDP rendered all 14 groups, exactly three DFT rows, and the real incident rollup with no console errors, page errors, failed requests, or mobile overflow.

Preserved visual evidence:

- [Grouped desktop dashboard](evidence/monitoring-domain-coverage-local-desktop.png)
- [DFT-filtered desktop dashboard](evidence/monitoring-domain-coverage-local-dft.png)
- [DFT-filtered mobile dashboard](evidence/monitoring-domain-coverage-local-mobile-dft.png)

## Production release and verification

- Staging integration landed through [PR #35](https://github.com/JoshuaSeth/pitchai-monitoring/pull/35) at squash commit `f7c8df61c2ae69b24a1b2700443944ad5a53fc10`.
- The current-production reconciliation landed through [PR #36](https://github.com/JoshuaSeth/pitchai-monitoring/pull/36) at squash commit `aee53fc7dfd1b45d70d800b20756ed810bcf51aa`.
- [Production deploy run 32768831031](https://github.com/JoshuaSeth/pitchai-monitoring/actions/runs/32768831031) passed the complete Dockerized HTTP/Playwright test job and the SSH/Docker production deployment job.
- `e2e-registry`, `e2e-runner`, and `service-monitoring` were all running the exact `aee53fc7dfd1b45d70d800b20756ed810bcf51aa` image with zero restarts after deployment.
- The public `https://monitoring.pitchai.net/dashboard` edge returned the expected Entra SSO redirect with production TLS/security headers. A headed Chrome session attached over CDP then exercised the deployed registry directly through an SSH-bound loopback and the same trusted identity header supplied by that edge.
- The live summary returned `ok=true`, 59 enabled checks, 14 groups, 19 classified exclusions, zero orphaned state domains, zero disabled checks, zero unknown checks, and fresh one-minute state.
- Every configured domain had real retained production observations; the minimum was three samples. The three DFT checks were all `200`, healthy, at 100% availability with three retained samples each. The 2FA operational exception was `200`, healthy, and its API contract was passing.
- The grouped UI rendered 15 scope controls (All groups plus 14 project/system groups), exactly three DFT rows, a healthy DFT selected-service chart, current incidents, system signals, E2E status, and rolling metrics.
- Desktop and 390-pixel mobile checks found no horizontal overflow. The production browser run recorded no console errors, page errors, request failures, or HTTP error responses from dashboard requests.
- The effective live service rollup was 50/59 healthy, with nine checks requiring attention: Dispatch and registry effective subchecks, the five primary incidents identified before deployment, and the existing DePlanBook `dpb.pitchai.net`/`deplanbook.com` E2E failures. These remain visible and alertable rather than being excluded to improve the headline.

Production visual evidence:

- [Production grouped desktop dashboard](evidence/monitoring-domain-coverage-production-desktop.png)
- [Production DFT-filtered desktop dashboard](evidence/monitoring-domain-coverage-production-dft.png)
- [Production DFT-filtered mobile dashboard](evidence/monitoring-domain-coverage-production-mobile-dft.png)
