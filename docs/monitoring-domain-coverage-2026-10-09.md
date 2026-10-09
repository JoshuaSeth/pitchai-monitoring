# Monitoring domain coverage — 9 October 2026

## Result

Four additions bring the deployed inventory to **97 unique targets: 77 with normal alerts and 20 dashboard-only**. The 42 retirements are unchanged. All five changed targets are healthy under their configured read-only contracts.

| Domain | Contract | Alerts |
|---|---|---|
| `presentaties.pitchai.net` | Anonymous GET `/oudijk/`, expected 401 | Normal |
| `presentations.pitchai.net` | Same protected route; English alias | Disabled |
| `presentations.135-181-182-48.sslip.io` | Same protected route; bootstrap alias | Disabled |
| `montrachet.pitchai.net` | Anonymous SSO redirect to Microsoft login | Normal |
| `dft-openai-info.openai.azure.com` | Existing root GET, expected 200 | Enabled |

The presentation aliases stay visible without duplicate incidents. Montrachet's private data application is separate from the already monitored public demo; current DNS and ingress supersede its earlier ignore decision. Production DFT web and worker containers now use the Azure resource, so its former alert-disabled policy is no longer appropriate.

These checks use no credentials, client data or billable model calls. No DNS changes were made. All 93 existing check contracts are unchanged; only the existing Azure target's metadata and alert policy changed.

## Discovery

Window: **30 September 2026 11:28:17 UTC through 9 October 2026 11:28:17 UTC**, including the missed October 5 occurrence.

Discovery covers 2,389 unique agent records, with 2,030 live/recent projections selected and 338 recently active agents. Detailed reads succeeded for 343 of 362 selected histories. Eighteen unavailable histories have saved messages in the window. One CLMBS logistics history remains unavailable after smaller reads and scoped search; its projection is included.

Saved-history evidence contains 187,548 messages from 977 agent/session names in 324 cell-time batches. No batch reached its 20,000-message limit. Main and Monitoring indexes report 99.8% and 99.6% byte coverage. FSN's supported domain-oriented search supplements the three SQL-capable cells; no restricted history access was bypassed.

Project and infrastructure evidence covers all 85 PM projects, 1,202 updated tasks across 29 projects, 52 CLI catalog projects, 137 repository stores across Jeff, Main and FSN, six recent DNS artifact files, current ingress and a fresh 82-record Namecheap snapshot. The repository scan examined 22,718 commit occurrences across stores, including replicated repositories, with changes in 85 stores. All 78 DNS web hostnames are monitored or explicitly retired. The sole ignored ingress name is the local `dispatch.pitchai.test` fixture.

The [inventory ledger](monitoring-domain-coverage-2026-10-09.json) classifies 5,154 candidate strings: 77 normally monitored, 20 dashboard-only, 42 retired and 5,015 ignored. Of 533 newly encountered strings, three became monitoring targets and 530 are ignored. The previously ignored Montrachet hostname became the fourth addition. No candidate remains unclassified.

Ignored examples include the undeployed Firebase default `aipc-push.web.app`, the obsolete course origin `yellow-forest-07302ed03.1.azurestaticapps.net`, superseded DFT Azure candidates, proposed presentation aliases, external research/vendor sites and code fixtures. The three new `u685372*.your-storagebox.de` names are SSH backup endpoints with WebDAV disabled; backup-job health owns those alerts. `pm.pitchai.net` was a fabricated source locator, absent from DNS and ingress, not an operated PM service.

## Integration and live verification

[PR 245](https://github.com/JoshuaSeth/pitchai-monitoring/pull/245) and [PR 247](https://github.com/JoshuaSeth/pitchai-monitoring/pull/247) merged the inventory and release-contract corrections into staging. [PR 246](https://github.com/JoshuaSeth/pitchai-monitoring/pull/246) and [PR 248](https://github.com/JoshuaSeth/pitchai-monitoring/pull/248) promoted them to main. Required Enforcement integrity and Quality ratchet checks passed.

The first deployment stopped before rollout: the reviewed deployment count still expected 93 targets, and the nginx map incorrectly excluded two production hosts. Both were corrected without weakening a gate. The [replacement production deployment](https://github.com/JoshuaSeth/pitchai-monitoring/actions/runs/37930191272) succeeded at `2827221199180667ed2f460130e1230a295fa968`.

The full deployment image suite passed **419 tests with four skips**. All seven focused nginx/deployment regression tests and 25 staging inventory/contract tests passed. A local full-suite attempt was stopped after its Python build rejected the `posix_spawn` setsid option used by existing account tests; the containerized full suite supplies release proof. The optional full zero-debt gate remains red and is not repository-required.

All six monitoring containers run the deployed release. The live API matches all 97 configured hostnames and every alert policy, with no duplicate targets or unknown results. The five changed targets returned their expected statuses after startup.

All 20 dashboard-only targets appeared in post-deployment logs: **33 quiet results at INFO level, zero quiet warning/error lines and zero actionable quiet incidents**. Normal warning behavior remains active. The database collector is healthy with 45 dependencies, the incident producer is healthy with no pending deliveries, and the scheduler observer completed a fresh successful poll.

The rendered dashboard shows the five changed targets as healthy and marks both presentation aliases “DASHBOARD ONLY”. This check used an administrative SSH tunnel and does not establish external SSO acceptance. The deployment browser check passed at a 390-pixel mobile width with no overflow, console errors, page errors, failed requests or HTTP errors. The installed nginx map matches the release, and nginx syntax validation passes.

The [live verification record](monitoring-domain-coverage-2026-10-09-proof.json) retains runtime, log, browser, release and inventory-preservation evidence.

## Remaining risks

Six existing alert-enabled checks remained down: `dispatch.pitchai.net`, `codexusage.pitchai.net`, `aigenda-rules.demos.pitchai.net`, `jeff-codex-voice.pitchai.net`, `jeff-dispatch.pitchai.net` and `jeff-work-inbox.pitchai.net`. The same six were down before deployment. Their normal alerts remain enabled.

The dashboard still shows existing TLS, container-health and monitor-integrity degradation, plus one historical orphaned state row excluded from the active inventory. Nginx reports 67 existing duplicate-server/protocol warnings while passing syntax validation.

The unavailable CLMBS history and small saved-index backfill gaps remain visibility limits. Agent projections, PM, repository changes, DNS and ingress provide independent evidence, but do not prove that missing history contains no additional domain. All discovered operated web domains are covered or explicitly retired.

The private-service checks verify expected anonymous authentication boundaries, not protected application transactions. The Azure check verifies root availability, not model inference or deployment readiness.
