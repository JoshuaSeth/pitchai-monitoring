# Monitoring domain coverage — 3 October 2026

## Result

Four new endpoints bring monitoring to 93 unique targets: 74 with normal alerts and 19 dashboard-only. All 89 prior target contracts and 42 retirements are unchanged.

| Domain | Read-only contract | Alerts |
|---|---|---|
| `upload-to-wasabi-7v37bcjssa-uc.a.run.app` | GET `/`, HTTP 403 with `origin_required` and `Request origin is required` | Normal |
| `submit-maatje-form-7v37bcjssa-uc.a.run.app` | GET `/`, HTTP 400 with `INVALID_ARGUMENT` and `Bad Request` | Normal |
| `us-central1-cis-db-e9fd3.cloudfunctions.net` | GET `/upload_to_wasabi`, the same upload-service contract | Disabled |
| `dft-openai-info.openai.azure.com` | GET `/`, HTTP 200 on the historical Azure resource | Disabled |

The upload alias stays visible with alerts disabled to avoid duplicate incidents. The DFT resource is under migration review and is not an approved production model route. These checks send no forms, uploads, credentials or model requests. No DNS changes were made.

## Discovery

The discovery window is 24 September 2026 01:27:47 UTC through 3 October 2026 01:27:47 UTC.

Inventory sources include 1,735 unique authorized agent projections, including 305 recent or running agents and older live lanes. Detailed reads succeeded for 182 of the 305 agents. Saved-history search returned 120,632 messages from 929 agent/session names in 126 cell-time batches. Daily and two-hour batches remained below their limits.

Project and infrastructure sources include all 86 PM projects, 977 updated tasks across 30 projects, the 51-project CLI catalog, 132 Git repository stores across Jeff, Main and FSN, two recent DNS artifact locations, current ingress and a fresh 79-record Namecheap snapshot. All 75 A/AAAA/CNAME web hostnames are monitored or explicitly retired. The only unmonitored ingress name is the local `dispatch.pitchai.test` fixture.

The [inventory ledger](monitoring-domain-coverage-2026-10-03.json) classifies 4,624 candidate strings: 74 normally monitored, 19 dashboard-only, 42 retired and 4,489 ignored. There are 602 newly encountered strings: the four additions and 598 ignored external, historical, fixture or extraction references.

Ignored examples include obsolete `cis.s3.eu-central-1.wasabisys.com` (NoSuchBucket), unconfigured or mistaken `apologetica.pitchai.net`, `dpb-cms.pitchai.net`, `dft.pitchai.net` and `staging.skybuyfly.pitchai.net`, and temporary historical tunnel names. The operated canonical services remain monitored.

Of the 123 unavailable detailed agent reads, 120 have messages in the authorized saved-history evidence. Two AutoPAR visual-audit histories and the DFT spend-cutover history remained unavailable after smaller retries. Their projections were included. FSN's normal registered history search also returned eight relevant lane records. The tenant-restricted shared history index was not bypassed. Those three detailed histories remain a visibility gap.

## Integration and live verification

[PR 207](https://github.com/JoshuaSeth/pitchai-monitoring/pull/207) merged the coverage change into staging. [PR 208](https://github.com/JoshuaSeth/pitchai-monitoring/pull/208) promoted it to main. The required Enforcement integrity and Quality ratchet gates passed. The [production deployment](https://github.com/JoshuaSeth/pitchai-monitoring/actions/runs/37091125819) succeeded at `4f7977b3675b8acf38f4e9aa077fda9b05773f7c`.

The focused tests on main passed all 24 cases. The deployment image suite passed 270 tests with four skips. The optional full zero-debt gate remains red. The required quality ratchet passed for all four changed Python files.

All six monitoring containers run that release. The live API matches all 93 configured domains and their alert policies. There are no duplicate targets. All four additions returned their expected status after deployment.

All 19 dashboard-only targets appeared in post-deployment logs: 30 quiet results at INFO level, zero quiet warning/error lines and zero actionable quiet incidents. Normal warnings remain enabled. The database collector is healthy with 44 dependencies, the incident producer is healthy with no pending deliveries, and the scheduler observer completed a fresh successful poll.

The rendered dashboard shows all four additions as healthy and labels both quiet additions “DASHBOARD ONLY”. This check used an administrative SSH tunnel and does not establish external SSO behavior. The deployment browser check passed at a 390-pixel mobile width with no overflow, console errors or failed requests. The installed nginx map matches the release, and nginx syntax validation passes.

The [live verification record](monitoring-domain-coverage-2026-10-03-proof.json) retains the measured runtime, log and release results.

## Remaining risks

Five existing alert-enabled checks remained down at verification: `dispatch.pitchai.net`, `codexusage.pitchai.net`, `jeff-codex-voice.pitchai.net`, `jeff-dispatch.pitchai.net` and `jeff-work-inbox.pitchai.net`. The same five were down before deployment. They retain normal monitoring and incident behavior.

The dashboard still reports container-health and monitor-integrity degradation and one historical orphaned state row. Nginx still emits existing duplicate-server/protocol warnings. The orphaned row is excluded from the active inventory.

The HetCIS contracts verify deployed service availability and expected unauthenticated responses, not submission or storage behavior. The historical DFT check verifies only root availability, not model access or deployment readiness.

