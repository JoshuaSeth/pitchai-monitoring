<!-- BEGIN CLEAN TEXT -->
# Codex subscription capacity dossier

Evidence cutoff: **6 September 2026 at 20:20 UTC, exclusive**. Accounts use stable anonymous labels A01–A08. Raw workload dates span 5 November 2025–6 September 2026, while useful account quota history is concentrated in July–September 2026. Each analysis below states its narrower population.

## Sources and coverage

| Evidence family | Retained coverage and volume | What it establishes |
| --- | --- | --- |
| Rollout union | 23,705 discovered paths across main/monitoring, Jeff, historical main and FSN1. 20,152 readable, 3,529 missing, 24 inode aliases. 133,998,392,296 bytes scanned. | Timestamped token and model/effort fields, plus quota deadlines where recorded. A file or counter alone does not prove a distinct live request. |
| Historical main | 369 readable of 377 paths, 20.62 GB. | Older workload history. |
| Jeff | 789 readable of 1,134 paths, 17.11 GB. | Additional managed and copied history. |
| Main and monitoring | 18,992 readable of 22,192 paths, 96.28 GB. | Most recovered workload, including overlapping archives and runtime copies. |
| FSN1 | Two readable paths, six token events. | Bounded contribution from the fourth extraction cell. |
| Broker quota database | 40,936 extracted sample rows, 19 August–6 September. Nine backups add no missing quota tuples. | Account-tagged quota snapshots with freshness qualifications. |
| Reset guardian | 15,635 snapshots, 10 August–6 September. Twenty-seven credit references and six recorded successful redemptions. | Direct quota and bank inventory history. |
| Recovery logs | 7,246 unique account/probe quota rows across retained sources. Five-hour fields survive in 104 observations from 5–11 July. | Earlier account-tagged quota and some lease evidence. |
| Normalized quota union | 52,551 observations: 15,635 guardian, 17,701 current, 5,625 recovery, 597 last-known and 12,993 legacy/stale. | Explicit separation of fresh and historical/cached values. Counts differ from raw exports because duplicate provider observations collapse. |
| Manual reset responses | Ten original response records corroborate four actions on 12 July and 10 August. | Action results and delayed fresh quota state, with account/deadline attribution grades. |
| Lease history | 4,563 observations, 2,947 renewal states, 133 issuances. | Partial corroboration of account ownership. Renewal is not a new lease. |
| Historical reports | Related PM workpads, the August usage-history investigation, durable time-series implementation and September historical cost ledger. Telegram search screened 219 receipts and yielded 103 candidate lines. | Corroboration and source discovery. Narrative percentages remain outside the primary quota ledger. |
| Billing evidence | Twenty-four complete provider searches across six matched M365 mailboxes, 616 messages in range, seven provider notices. Fourteen iCloud folders and 28 searches yielded ten matches. | Scheduled nonrenewal dates and offers, but no matched paid subscription invoice amount. |
| Public sources | Official model/pricing pages, dated release changes, ECB daily exchange rates, original Reddit claim and linked author's table. | Reference prices and claims to test. |

The source inventory and extraction manifests record the underlying locations, cutoff rules, hashes and source-specific dispositions. Raw account identities, credentials and client content are excluded from the repository artifacts.

### Earlier research reconciled

The August investigation reported 7,045 unique pre-17-August recovery observations. The surviving inputs reproduce **6,937** under its original account/probe/window/percentage/reset key. The 108-observation difference remains unrecovered after checking the surviving report, logs and artifact roots. It is a coverage gap with no identified quota-policy implication.

The September cost ledger contains 244,113 logical turns. Its 119,835 modern numeric turns permit a direct counter comparison. After replay correction, 104,505 match all four counters exactly, 108 have higher current totals, 51 have lower current totals, 15,072 prior zero-token turns have no current calls, and 99 nonzero prior turns are absent. All 99 map to 23 files recorded as unavailable. Exact matches include 689 turns flagged by the prior study, so agreement alone does not certify consumption. The earlier report repriced historical workload at comparison-model rates. The present account analysis uses dated actual-model reference rates.

### Narrative timestamps

Historical Telegram receipts use a timestamp-without-time-zone column. The current write path uses the database's Europe/Berlin clock. Historical per-row session time zones are unrecorded. Comparing UTC and Berlin interpretations against nearby direct quota probes produces two exact matches under the Berlin interpretation and other one-point differences. These checks qualify narrative timing without promoting the reports into precise telemetry. A July 26 report explicitly says no reset was redeemed and creates no additional reset event.
<!-- END CLEAN TEXT -->

## Internal traceability

Sources: source_inventory.json, extraction-manifest.json, rollout-import-audit.json, historical-corroboration.json, prior-ledger review and billing reviews. Component: usage-history source table. The separate discovery, extraction and normalization counts avoid mixing populations. Source methods belong in this empirical artifact. Current-state receipts do not certify historic clocks or paid access. No email identities or private report contents are included.
