<!-- BEGIN CLEAN TEXT -->
## Accounting, identity and comparison methods

### From cumulative counters to candidate calls

Each source is read in recorded order. Unchanged cumulative counters contribute no new usage. When counters change, the reported last-call tuple is retained and compared with the cumulative difference. Rollbacks, missing prior history and non-reconciling calls remain explicitly classified. Unrecovered increments remain unknown.

Cached input is included in total input. Reasoning output is included in total output. The disjoint workload components are therefore:

`uncached input = input − cached input`

`total workload tokens = uncached input + cached input + output`

The 7,319,366 token events yield 6,149,650 candidate source observations. Exact copied event identities collapse to 6,066,658 candidate calls. A second replay pass uses the turn identifier and all eight last/cumulative token counters across different source files. It requires session identity to be present but permits a fork to replace the session ID. Later cross-source copies are removed. Missing identifiers and same-source repetitions remain visible because identical token counts alone cannot prove a replay.

This pass removes 2,249,296 later copies, or 37.0764% of candidates, and 41.506% of standard reference value. Genuine repeated requests with distinct consumption evidence remain consumption. A transport retry message alone leaves the number of consumed requests unresolved. The residual audit of 1,693,319 strict survivors finds no full-counter coincidences across different nonmissing turns. Sixty-two missing-turn groups contain 163 calls, including 101 later records that are unpriced. They produce no additional dollar deduction.

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

Nearly complete comparisons require at least 80 points, the same provenance/pricing/dominance controls, and no consumption observation gap over 1,830 seconds. Thirty extra seconds allow recorded probe jitter. Most selected epochs cover 99 points, so their dollar sums are observed 99-point values, without extrapolation to an unseen full allowance. [Historical annotations](evidence/epoch-transition-annotations.json) revise three quota-only transition labels.

For value `V` and observed quota change `Q`, the descriptive slope is `V/Q`. Timing sensitivities recalculate value inside endpoints inset by 120 seconds and enclosing endpoints extended by 120 seconds. For `n` intervals, rounding sensitivities divide those values by `Q + e×n` and `Q − e×n`, with `e` equal to one or two points. The upper expression is undefined if the denominator is nonpositive. These conditional sensitivity bounds vary endpoint timing and rounding assumptions. They have no statistical confidence level and leave unrecovered workload, unknown service tiers and hidden metering weights unbounded.
<!-- END CLEAN TEXT -->

## Internal language pass two

Input: [V2](12-methods-v2.md). Sentence and table review below is independent of the first pass. V1 remains in its original section file. Each numbered unit is a sentence, heading, table row or code block in input order.

| Unit | V2 opening | Second-pass decision |
| ---: | --- | --- |
| 1 | ## Accounting, identity and comparison methods | Retain the subject-specific navigation heading. |
| 2 | ### From cumulative counters to candidate calls | Retain the subject-specific navigation heading. |
| 3 | Each source is read in recorded order. | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 4 | Unchanged cumulative counters contribute no new usage. | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 5 | When counters change, the reported last-call tuple is retained and compared with the … | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 6 | Rollbacks, missing prior history and non-reconciling calls remain explicitly classifi… | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 7 | Unrecovered increments remain unknown. | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 8 | Cached input is included in total input. | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 9 | Reasoning output is included in total output. | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 10 | The disjoint workload components are therefore: | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 11 | `uncached input = input − cached input` | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 12 | `total workload tokens = uncached input + cached input + output` | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 13 | The 7,319,366 token events yield 6,149,650 candidate source observations. | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 14 | Exact copied event identities collapse to 6,066,658 candidate calls. | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 15 | A second replay pass uses the turn identifier and all eight last/cumulative token cou… | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 16 | It requires session identity to be present but permits a fork to replace the session … | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 17 | Later cross-source copies are removed. | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 18 | Missing identifiers and same-source repetitions remain visible because identical toke… | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 19 | This pass removes 2,249,296 later copies, or 37.0764% of candidates, and 41.506% of s… | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 20 | Genuine repeated requests with distinct consumption evidence remain consumption. | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 21 | A transport retry message alone neither proves another billed request nor authorizes … | Remove permission language from the accounting method. |
| 22 | The residual audit of 1,693,319 strict survivors finds no full-counter coincidences a… | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 23 | Sixty-two missing-turn groups contain 163 calls, including 101 later records that are… | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 24 | They produce no additional dollar deduction. | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 25 | ### Account attribution and its limits | Retain the subject-specific navigation heading. |
| 26 | Positive, non-idle quota deadlines supply account fingerprints. | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 27 | The account-window audit finds 280 fingerprints with no shared or adjacent positive d… | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 28 | Candidate joins use exact deadline matching or a separately graded one-second toleran… | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 29 | There are 1,950,968 exact candidate joins, 47,082 tolerance joins, 3,518,429 candidat… | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 30 | These candidate counts precede replay and strict-source controls. | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 31 | The stricter subset requires a matching outer session header, a timestamp after sessi… | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 32 | It contains **1,693,319 calls with $151,117.94 of standard API-equivalent value**. | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 33 | These source checks do not independently attest to live execution or a verified paid … | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 34 | Lease evidence remains a separate check. | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 35 | Issue-to-latest-expiry ranges can overlap after renewal or early release and lack rel… | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 36 | Only 62,696 strict calls have one compatible account range, 4,623 have multiple compa… | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 37 | The retained lease grades distinguish these cases. | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 38 | Account totals are conditional on the reset-fingerprint attribution. | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 39 | ### Concurrent workload and fixed-hour controls | Retain the subject-specific navigation heading. |
| 40 | An interval includes all recovered calls assigned to the account, including concurren… | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 41 | Its reported quota movement is counted once. | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 42 | Model rows share that account-level denominator. | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 43 | Model/effort dominance is measured by reference-value share, so a dominant-model labe… | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 44 | Candidate windows are fixed UTC hour bins selected independently of observed efficien… | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 45 | Endpoints use fresh account-tagged provider readings with positive usage. | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 46 | Timing eligibility requires at most one second of reset spread, at least 30 minutes o… | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 47 | The first/last samples lie inside the hour, so an eligible interval need not last 60 … | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 48 | Of 3,382 candidate windows, 673 meet timing controls. | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 49 | Forty-four candidates are five-hour windows and none qualifies. | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 50 | Weekly windows produce 641 rows with recovered exposure, of which 192 meet the primar… | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 51 | Sensitivity partitions repeat the analysis at 80%, 90% and 95% dominance and two, fiv… | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 52 | ### Reset epochs and uncertainty | Retain the subject-specific navigation heading. |
| 53 | Positive weekly readings are segmented when the same account's deadline changes by mo… | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 54 | This tolerance handles probe jitter within an account and is never used for cross-acc… | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 55 | An epoch's consumption interval runs from its first positive observation to its first… | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 56 | Idle zero readings have floating deadlines and are excluded. | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 57 | The resulting 123 positive epochs describe recovered intervals. | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 58 | Their endpoints can cover only part of a quota week. | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 59 | Nearly complete comparisons require at least 80 points, the same provenance/pricing/d… | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 60 | Thirty extra seconds allow recorded probe jitter. | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 61 | Most selected epochs cover 99 points, so their dollar sums are observed 99-point valu… | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 62 | The separate historical annotation file revises three original transition labels. | Name the evidence distinction and provide the exact source. |
| 63 | For value `V` and observed quota change `Q`, the descriptive slope is `V/Q`. | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 64 | Timing sensitivities recalculate value inside endpoints inset by 120 seconds and encl… | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 65 | For `n` intervals, rounding sensitivities divide those values by `Q + e×n` and `Q − e… | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 66 | The upper expression is undefined if the denominator is nonpositive. | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 67 | These conditional sensitivity bounds vary endpoint timing and rounding assumptions. | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 68 | They have no statistical confidence level. | Combine closely related mathematical limits without extra disclaimers. |
| 69 | They do not bound unrecovered workload, unknown service tiers or hidden metering weig… | Combine closely related mathematical limits without extra disclaimers. |

The English report retains its original language. This pass targets compressed jargon, abstract nouns, repetitive limits and task narration missed in V2. Decimal values, model/effort labels, dates, equations and executable arguments retain their meaning. Figures show the same retained populations. Necessary uncertainty stays next to the affected comparison. No semicolons, formulaic contrast sentences, defensive client reassurances or nonessential disclaimer stacks are introduced. Phase 13 separately inspects all visible surfaces before assembly.
