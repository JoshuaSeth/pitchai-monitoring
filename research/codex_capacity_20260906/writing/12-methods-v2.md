<!-- BEGIN CLEAN TEXT -->
## Accounting, identity and comparison methods

### From cumulative counters to candidate calls

Each source is read in recorded order. Unchanged cumulative counters contribute no new usage. When counters change, the reported last-call tuple is retained and compared with the cumulative difference. Rollbacks, missing prior history and non-reconciling calls remain explicitly classified. Unrecovered increments remain unknown.

Cached input is included in total input. Reasoning output is included in total output. The disjoint workload components are therefore:

`uncached input = input − cached input`

`total workload tokens = uncached input + cached input + output`

The 7,319,366 token events yield 6,149,650 candidate source observations. Exact copied event identities collapse to 6,066,658 candidate calls. A second replay pass uses the turn identifier and all eight last/cumulative token counters across different source files. It requires session identity to be present but permits a fork to replace the session ID. Later cross-source copies are removed. Missing identifiers and same-source repetitions remain visible because identical token counts alone cannot prove a replay.

This pass removes 2,249,296 later copies, or 37.0764% of candidates, and 41.506% of standard reference value. Genuine repeated requests with distinct consumption evidence remain consumption. A transport retry message alone neither proves another billed request nor authorizes deleting one. The residual audit of 1,693,319 strict survivors finds no full-counter coincidences across different nonmissing turns. Sixty-two missing-turn groups contain 163 calls, including 101 later records that are unpriced. They produce no additional dollar deduction.

### Account attribution and its limits

Positive, non-idle quota deadlines supply account fingerprints. The account-window audit finds 280 fingerprints with no shared or adjacent positive deadline across different accounts. Candidate joins use exact deadline matching or a separately graded one-second tolerance. There are 1,950,968 exact candidate joins, 47,082 tolerance joins, 3,518,429 candidates without a historical anchor, and 550,179 with a different limit identifier. These candidate counts precede replay and strict-source controls.

The stricter subset requires a matching outer session header, a timestamp after session creation, a recognized runtime path, reconciled last-call counters, consistent totals and no model/effort conflicts. It contains **1,693,319 calls with $151,117.94 of standard API-equivalent value**. These source checks do not independently attest to live execution or a verified paid subscription.

Lease evidence remains a separate check. Issue-to-latest-expiry ranges can overlap after renewal or early release and lack reliable capture times. Only 62,696 strict calls have one compatible account range, 4,623 have multiple compatible ranges, 190,876 fit ranges recorded only for other accounts, 1,407,823 have no range and 27,301 lack source affinity. The retained lease grades distinguish these cases. Account totals are conditional on the reset-fingerprint attribution.

### Concurrent workload and fixed-hour controls

An interval includes all recovered calls assigned to the account, including concurrent sessions. Its reported quota movement is counted once. Model rows share that account-level denominator. Model/effort dominance is measured by reference-value share, so a dominant-model label still permits up to 5% other workload value.

Candidate windows are fixed UTC hour bins selected independently of observed efficiency. Endpoints use fresh account-tagged provider readings with positive usage. Timing eligibility requires at most one second of reset spread, at least 30 minutes of span, no observation gap over 30 minutes, no step below −1 point and positive net movement. The first/last samples lie inside the hour, so an eligible interval need not last 60 minutes.

Of 3,382 candidate windows, 673 meet timing controls. Forty-four candidates are five-hour windows and none qualifies. Weekly windows produce 641 rows with recovered exposure, of which 192 meet the primary controls: at least five points, at least 95% dominant-model/effort value, at least 95% strict-source value, known supported prices and matching quota deadlines. Sensitivity partitions repeat the analysis at 80%, 90% and 95% dominance and two, five and ten points.

### Reset epochs and uncertainty

Positive weekly readings are segmented when the same account's deadline changes by more than 30 seconds. This tolerance handles probe jitter within an account and is never used for cross-account identity. An epoch's consumption interval runs from its first positive observation to its first observed maximum. Idle zero readings have floating deadlines and are excluded. The resulting 123 positive epochs describe recovered intervals. Their endpoints can cover only part of a quota week.

Nearly complete comparisons require at least 80 points, the same provenance/pricing/dominance controls, and no consumption observation gap over 1,830 seconds. Thirty extra seconds allow recorded probe jitter. Most selected epochs cover 99 points, so their dollar sums are observed 99-point values, without extrapolation to an unseen full allowance. The separate historical annotation file revises three original transition labels.

For value `V` and observed quota change `Q`, the descriptive slope is `V/Q`. Timing sensitivities recalculate value inside endpoints inset by 120 seconds and enclosing endpoints extended by 120 seconds. For `n` intervals, rounding sensitivities divide those values by `Q + e×n` and `Q − e×n`, with `e` equal to one or two points. The upper expression is undefined if the denominator is nonpositive. These conditional sensitivity bounds vary endpoint timing and rounding assumptions. They have no statistical confidence level. They do not bound unrecovered workload, unknown service tiers or hidden metering weights.
<!-- END CLEAN TEXT -->

## Internal language pass one

Input: [V1](11-methods-v1.md). Each numbered unit below is one prose sentence, table row, heading or indivisible code block, in source order. Table rows and code preserve their structure. This is a language review, with factual verification recorded separately.

| Unit | Source opening | Decision |
| ---: | --- | --- |
| 1 | ## Accounting, identity and comparison methods | Retain descriptive heading for navigation. |
| 2 | ### From cumulative counters to candidate calls | Retain descriptive heading for navigation. |
| 3 | Each source is read in recorded order. | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 4 | Unchanged cumulative counters contribute no new usage. | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 5 | When counters change, the reported last-call tuple is retained and compared with the … | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 6 | Rollbacks, missing prior history and non-reconciling calls remain explicitly classifi… | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 7 | No missing increment is fabricated. | Describe missing evidence directly. |
| 8 | Cached input is included in total input. | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 9 | Reasoning output is included in total output. | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 10 | The disjoint workload components are therefore: | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 11 | `uncached input = input − cached input` | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 12 | `total workload tokens = uncached input + cached input + output` | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 13 | The 7,319,366 token events yield 6,149,650 candidate source observations. | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 14 | Exact copied event identities collapse to 6,066,658 candidate calls. | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 15 | A second replay pass uses the turn identifier and all eight last/cumulative token cou… | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 16 | It requires session identity to be present but permits a fork to replace the session … | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 17 | Later cross-source copies are removed. | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 18 | Missing identifiers and same-source repetitions remain visible because identical toke… | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 19 | This pass removes 2,249,296 later copies, or 37.0764% of candidates, and 41.506% of s… | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 20 | Genuine repeated requests with distinct consumption evidence remain consumption. | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 21 | A transport retry message alone neither proves another billed request nor authorizes … | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 22 | The residual audit of 1,693,319 strict survivors finds no full-counter coincidences a… | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 23 | Sixty-two missing-turn groups contain 163 calls, including 101 later copies that are … | Do not label ambiguous counter coincidences as proven copies. |
| 24 | ### Account attribution and its limits | Retain descriptive heading for navigation. |
| 25 | Positive, non-idle quota deadlines supply account fingerprints. | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 26 | The account-window audit finds 280 fingerprints with no shared or adjacent positive d… | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 27 | Candidate joins use exact deadline matching or a separately graded one-second toleran… | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 28 | There are 1,950,968 exact candidate joins, 47,082 tolerance joins, 3,518,429 candidat… | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 29 | These candidate counts precede replay and strict-source controls. | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 30 | The stricter subset requires a matching outer session header, a timestamp after sessi… | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 31 | It contains **1,693,319 calls with $151,117.94 of standard API-equivalent value**. | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 32 | It is a defined evidence subset, not independent attestation that every surviving rec… | Remove formulaic contrast while preserving the substantive limitation. |
| 33 | Lease evidence remains a separate check. | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 34 | Issue-to-latest-expiry ranges can overlap after renewal or early release and lack rel… | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 35 | Only 62,696 strict calls have one compatible account range, 4,623 have multiple compa… | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 36 | These grades expose the uncertainty instead of silently resolving it. | Remove process comparison. |
| 37 | Account totals are conditional on the reset-fingerprint attribution. | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 38 | ### Concurrent workload and fixed-hour controls | Retain descriptive heading for navigation. |
| 39 | An interval includes all recovered calls assigned to the account, including concurren… | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 40 | Its reported quota movement is counted once. | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 41 | It is never independently assigned in full to each model row. | State the accounting rule positively. |
| 42 | Model/effort dominance is measured by reference-value share, so a dominant-model labe… | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 43 | Candidate windows are fixed UTC hour bins selected independently of observed efficien… | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 44 | Endpoints use fresh account-tagged provider readings with positive usage. | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 45 | Timing eligibility requires at most one second of reset spread, at least 30 minutes o… | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 46 | The first/last samples lie inside the hour, so an eligible interval need not last 60 … | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 47 | Of 3,382 candidate windows, 673 meet timing controls. | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 48 | Forty-four candidates are five-hour windows and none qualifies. | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 49 | Weekly windows produce 641 rows with recovered exposure, of which 192 meet the primar… | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 50 | Sensitivity partitions repeat the analysis at 80%, 90% and 95% dominance and two, fiv… | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 51 | ### Reset epochs and uncertainty | Retain descriptive heading for navigation. |
| 52 | Positive weekly readings are segmented when the same account's deadline changes by mo… | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 53 | This tolerance handles probe jitter within an account and is never used for cross-acc… | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 54 | An epoch's consumption interval runs from its first positive observation to its first… | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 55 | Idle zero readings have floating deadlines and are excluded. | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 56 | The resulting 123 positive epochs describe recovered intervals rather than complete p… | Explain incomplete exposure. |
| 57 | Nearly complete comparisons require at least 80 points, the same provenance/pricing/d… | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 58 | Thirty extra seconds allow recorded probe jitter. | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 59 | Most selected epochs cover 99 points, so their dollar sums are observed 99-point valu… | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 60 | The separate historical annotation file revises three original transition labels. | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 61 | For value `V` and observed quota change `Q`, the descriptive slope is `V/Q`. | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 62 | Timing sensitivities recalculate value inside endpoints inset by 120 seconds and encl… | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 63 | For `n` intervals, rounding sensitivities divide those values by `Q + e×n` and `Q − e… | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 64 | The upper expression is undefined if the denominator is nonpositive. | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 65 | These are conditional sensitivity bounds, not statistical confidence intervals. | Name what the bounds mean directly. |
| 66 | They do not bound unrecovered workload, unknown service tiers or hidden metering weig… | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |

Pass one uses direct subjects and verbs, removes formulaic contrasts and expands ambiguous terms. Required limits on identity, pricing and causal interpretation stay beside the affected claims. Technical methods and source citations remain necessary in this empirical report. No commercial promise is added.
