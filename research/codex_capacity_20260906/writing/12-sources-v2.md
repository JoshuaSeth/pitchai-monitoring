<!-- BEGIN CLEAN TEXT -->
# Codex subscription capacity dossier

Evidence cutoff: **6 September 2026 at 20:20 UTC, exclusive**. Accounts use stable anonymous labels A01–A08. Raw workload dates span 5 November 2025–6 September 2026, while useful account quota history is concentrated in July–September 2026. The account-month benchmark ranges from 15.0–26.0× EUR200 in July to 10.1–85.6× in August. Comparable hourly data links later Astra/high usage to lower API-equivalent value per reported quota point. August banked windows show similar constant-price value to ordinary-compatible windows, while a September-specific bank penalty remains unresolved.

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

The [source inventory](source_inventory.json) and extraction manifests record locations, cutoff rules, hashes and source-specific gaps.

### Earlier research reconciled

The August investigation reported 7,045 unique pre-17-August recovery observations. The surviving inputs reproduce **6,937** under its original account/probe/window/percentage/reset key. The 108-observation difference remains unrecovered after checking the surviving report, logs and artifact roots. The missing observations limit coverage and provide no evidence of a quota-policy change.

The September cost ledger contains 244,113 logical turns. Its 119,835 modern numeric turns permit a direct counter comparison. After replay correction, 104,505 match all four counters exactly, 108 have higher current totals, 51 have lower current totals, 15,072 prior zero-token turns have no current calls, and 99 nonzero prior turns are absent. All 99 map to 23 files recorded as unavailable. Exact matches include 689 turns flagged by the prior study, so agreement alone does not certify consumption. The earlier report repriced historical workload at comparison-model rates. Account values here use dated rates for the recorded model.

### Narrative timestamps

Historical Telegram receipts use a timestamp-without-time-zone column. The current write path uses the database's Europe/Berlin clock. Historical per-row session time zones are unrecorded. Comparing UTC and Berlin interpretations against nearby direct quota probes produces two exact matches under the Berlin interpretation and other one-point differences. The nearby probes support a local-time interpretation, with insufficient precision for the primary quota ledger. A July 26 report explicitly says no reset was redeemed and creates no additional reset event.
<!-- END CLEAN TEXT -->

## Internal language pass one

Input: [V1](11-sources-v1.md). Each numbered unit below is one prose sentence, table row, heading or indivisible code block, in source order. Table rows and code preserve their structure. This is a language review, with factual verification recorded separately.

| Unit | Source opening | Decision |
| ---: | --- | --- |
| 1 | # Codex subscription capacity dossier | Retain descriptive heading for navigation. |
| 2 | Evidence cutoff: **6 September 2026 at 20:20 UTC, exclusive**. | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 3 | Accounts use stable anonymous labels A01–A08. | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 4 | Raw workload dates span 5 November 2025–6 September 2026, while useful account quota … | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 5 | Each analysis below states its narrower population. | Add the outcome before the source inventory, using results already stated in the executive report. |
| 6 | ## Sources and coverage | Retain descriptive heading for navigation. |
| 7 | / Evidence family / Retained coverage and volume / What it establishes / | Retain units, numeric precision and evidence qualification in this table row. |
| 8 | / --- / --- / --- / | Retain units, numeric precision and evidence qualification in this table row. |
| 9 | / Rollout union / 23,705 discovered paths across main/monitoring, Jeff, historical ma… | Retain units, numeric precision and evidence qualification in this table row. |
| 10 | / Historical main / 369 readable of 377 paths, 20.62 GB. / Older workload history. / | Retain units, numeric precision and evidence qualification in this table row. |
| 11 | / Jeff / 789 readable of 1,134 paths, 17.11 GB. / Additional managed and copied histo… | Retain units, numeric precision and evidence qualification in this table row. |
| 12 | / Main and monitoring / 18,992 readable of 22,192 paths, 96.28 GB. / Most recovered w… | Retain units, numeric precision and evidence qualification in this table row. |
| 13 | / FSN1 / Two readable paths, six token events. / Bounded contribution from the fourth… | Retain units, numeric precision and evidence qualification in this table row. |
| 14 | / Broker quota database / 40,936 extracted sample rows, 19 August–6 September. Nine b… | Retain units, numeric precision and evidence qualification in this table row. |
| 15 | / Reset guardian / 15,635 snapshots, 10 August–6 September. Twenty-seven credit refer… | Retain units, numeric precision and evidence qualification in this table row. |
| 16 | / Recovery logs / 7,246 unique account/probe quota rows across retained sources. Five… | Retain units, numeric precision and evidence qualification in this table row. |
| 17 | / Normalized quota union / 52,551 observations: 15,635 guardian, 17,701 current, 5,62… | Retain units, numeric precision and evidence qualification in this table row. |
| 18 | / Manual reset responses / Ten original response records corroborate four actions on … | Retain units, numeric precision and evidence qualification in this table row. |
| 19 | / Lease history / 4,563 observations, 2,947 renewal states, 133 issuances. / Partial … | Retain units, numeric precision and evidence qualification in this table row. |
| 20 | / Historical reports / Related PM workpads, the August usage-history investigation, d… | Retain units, numeric precision and evidence qualification in this table row. |
| 21 | / Billing evidence / Twenty-four complete provider searches across six matched M365 m… | Retain units, numeric precision and evidence qualification in this table row. |
| 22 | / Public sources / Official model/pricing pages, dated release changes, ECB daily exc… | Retain units, numeric precision and evidence qualification in this table row. |
| 23 | The source inventory and extraction manifests record the underlying locations, cutoff… | Use a navigable source citation and remove an operational compliance claim. |
| 24 | Raw account identities, credentials and client content are excluded from the reposito… | Use a navigable source citation and remove an operational compliance claim. |
| 25 | ### Earlier research reconciled | Retain descriptive heading for navigation. |
| 26 | The August investigation reported 7,045 unique pre-17-August recovery observations. | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 27 | The surviving inputs reproduce **6,937** under its original account/probe/window/perc… | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 28 | The 108-observation difference remains unrecovered after checking the surviving repor… | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 29 | It is a coverage gap with no identified quota-policy implication. | Name the direct implication. |
| 30 | The September cost ledger contains 244,113 logical turns. | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 31 | Its 119,835 modern numeric turns permit a direct counter comparison. | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 32 | After replay correction, 104,505 match all four counters exactly, 108 have higher cur… | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 33 | All 99 map to 23 files recorded as unavailable. | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 34 | Exact matches include 689 turns flagged by the prior study, so agreement alone does n… | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 35 | The earlier report repriced historical workload at comparison-model rates. | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 36 | The present account analysis uses dated actual-model reference rates. | Simplify the methodological distinction. |
| 37 | ### Narrative timestamps | Retain descriptive heading for navigation. |
| 38 | Historical Telegram receipts use a timestamp-without-time-zone column. | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 39 | The current write path uses the database's Europe/Berlin clock. | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 40 | Historical per-row session time zones are unrecorded. | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 41 | Comparing UTC and Berlin interpretations against nearby direct quota probes produces … | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 42 | These checks qualify narrative timing without promoting the reports into precise tele… | State the clock result and its analytical limit. |
| 43 | A July 26 report explicitly says no reset was redeemed and creates no additional rese… | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |

Pass one uses direct subjects and verbs, removes formulaic contrasts and expands ambiguous terms. Required limits on identity, pricing and causal interpretation stay beside the affected claims. Technical methods and source citations remain necessary in this empirical report. No commercial promise is added.
