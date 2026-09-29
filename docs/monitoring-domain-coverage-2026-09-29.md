# Monitoring domain coverage — 29 September 2026

## Result

Four live endpoints have been added to monitoring. The deployed index contains 89 unique targets: 72 with normal alerts and 17 dashboard-only. All 85 prior target contracts and 42 retirements are unchanged.

| Domain | Contract | Alerts |
|---|---|---|
| `salesengine.demos.pitchai.net` | HTTP 200, Ember Duplex page | Normal |
| `gzb-review.135-181-182-48.sslip.io` | Intentional anonymous HTTP 403, GZB Review page | Disabled |
| `jeugdtandarts-review.135-181-182-48.sslip.io` | Intentional anonymous HTTP 403, Jeugdtandarts Review page | Disabled |
| `apologetica-react-staging.web.app` | HTTP 200, Geloofsverdediging preview | Disabled |

The SalesEngine check only reads the public page. Private review checks use no personal access parameters or media requests. The Firebase preview is a historical review deployment with no completed custom-domain handoff. No DNS changes were made.

## Discovery

The discovery window is 20 September 2026 20:45:04 UTC through 29 September 2026 20:45:04 UTC.

Evidence covers 1,671 unique authorized agent projections, including 402 recent or running lanes and older live lanes. Detailed reads succeeded for 373 recent/running agents after retries. Saved-history search returned 60,710 messages from 501 session/agent identifiers in 27 daily cell batches. No batch reached its 20,000-row limit.

Other evidence covers all 86 PM projects, 558 updated tasks across 29 projects, the 48-project CLI catalog, 134 Git repository stores across Jeff, Main and FSN, 16 recent DNS-engineering artifact locations, current ingress and a fresh 79-record Namecheap zone snapshot. All 75 A/AAAA/CNAME hostnames are monitored or explicitly retired. The only ignored ingress name is the local `dispatch.pitchai.test` fixture.

The [machine-readable inventory](monitoring-domain-coverage-2026-09-29.json) classifies all 4,022 candidates. There are 146 newly encountered strings: four monitored additions and 142 ignored third-party, tenant-identity or extraction references. The ledger contains 3,891 ignored candidates and 42 retirements, alongside the 89 monitored domains.

Twenty-nine detailed agent reads remained unavailable after smaller retries. Their authorized projections were included. FSN's shared saved-history search requires a tenant-scoped index and was not bypassed. Its repository history was scanned through the authorized host route. These are source-visibility limits, not successful history reads.

## Integration and live verification

[PR 178](https://github.com/JoshuaSeth/pitchai-monitoring/pull/178) merged the coverage change into staging. [PR 179](https://github.com/JoshuaSeth/pitchai-monitoring/pull/179) promoted those changes to main. Both required checks passed. The [production deployment](https://github.com/JoshuaSeth/pitchai-monitoring/actions/runs/36631413826) succeeded at `202b3f5635c9b8b3811fa0f2621e4bf798de4d90`.

The focused main suite passed 26 tests; the deployment image suite passed 266 tests with four skips. All six monitoring containers run that release. The live API contains exactly the 89 configured domains and their alert policies, without duplicate targets. All four additions returned their expected status after deployment.

All 17 dashboard-only targets appeared in post-deployment logs: 28 quiet results at INFO level, zero quiet warning/error lines and zero actionable quiet incidents. Existing normal warnings remain enabled. The database collector is healthy with 43 dependencies, the incident producer is healthy with no pending deliveries, and the scheduler observer completed a fresh successful poll.

The rendered dashboard shows all four additions as healthy and labels the three quiet additions “DASHBOARD ONLY”. This check used an administrative SSH tunnel; it does not establish external SSO behavior. The deployment browser check also passed at a 390-pixel mobile width, with no overflow, console errors or failed requests. The installed nginx map matches the release and passes syntax validation.

## Remaining risks

Four pre-existing alert-enabled checks remained down at verification: `dispatch.pitchai.net`, `jeff-codex-voice.pitchai.net`, `jeff-dispatch.pitchai.net` and `jeff-work-inbox.pitchai.net`. They remain monitored with normal incident behavior.

The dashboard also retains pre-existing container/monitor-integrity degradation, nginx emits existing duplicate-server/protocol warnings, and the inventory reports one historical orphaned state row. None creates another active target. The new checks establish page availability or the intended access boundary; they do not exercise sales calls, private media or full application journeys.

## Private handoff

The completion report was sent once to Seth/ORI through the verified private Telegram route. Exact-message readback confirmed one accepted private receipt and no broad or other copies.
