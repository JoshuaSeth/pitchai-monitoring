<!-- BEGIN CLEAN TEXT -->
## Accounting, identity and comparison methods

### From cumulative counters to candidate calls

Each source is read in recorded order. Unchanged cumulative counters contribute no new usage. When counters change, the reported last-call tuple is retained and compared with the cumulative difference. Rollbacks, missing prior history and non-reconciling calls remain explicitly classified. No missing increment is fabricated.

Cached input is included in total input. Reasoning output is included in total output. The disjoint workload components are therefore:

`uncached input = input − cached input`

`total workload tokens = uncached input + cached input + output`

The 7,319,366 token events yield 6,149,650 candidate source observations. Exact copied event identities collapse to 6,066,658 candidate calls. A second replay pass uses the turn identifier and all eight last/cumulative token counters across different source files. It requires session identity to be present but permits a fork to replace the session ID. Later cross-source copies are removed. Missing identifiers and same-source repetitions remain visible because identical token counts alone cannot prove a replay.

This pass removes 2,249,296 later copies, or 37.0764% of candidates, and 41.506% of standard reference value. Genuine repeated requests with distinct consumption evidence remain consumption. A transport retry message alone neither proves another billed request nor authorizes deleting one. The residual audit of 1,693,319 strict survivors finds no full-counter coincidences across different nonmissing turns. Sixty-two missing-turn groups contain 163 calls, including 101 later copies that are unpriced, producing no additional dollar deduction.

### Account attribution and its limits

Positive, non-idle quota deadlines supply account fingerprints. The account-window audit finds 280 fingerprints with no shared or adjacent positive deadline across different accounts. Candidate joins use exact deadline matching or a separately graded one-second tolerance. There are 1,950,968 exact candidate joins, 47,082 tolerance joins, 3,518,429 candidates without a historical anchor, and 550,179 with a different limit identifier. These candidate counts precede replay and strict-source controls.

The stricter subset requires a matching outer session header, a timestamp after session creation, a recognized runtime path, reconciled last-call counters, consistent totals and no model/effort conflicts. It contains **1,693,319 calls with $151,117.94 of standard API-equivalent value**. It is a defined evidence subset, not independent attestation that every surviving record executed live or belongs to a verified paid subscription.

Lease evidence remains a separate check. Issue-to-latest-expiry ranges can overlap after renewal or early release and lack reliable capture times. Only 62,696 strict calls have one compatible account range, 4,623 have multiple compatible ranges, 190,876 fit ranges recorded only for other accounts, 1,407,823 have no range and 27,301 lack source affinity. These grades expose the uncertainty instead of silently resolving it. Account totals are conditional on the reset-fingerprint attribution.

### Concurrent workload and fixed-hour controls

An interval includes all recovered calls assigned to the account, including concurrent sessions. Its reported quota movement is counted once. It is never independently assigned in full to each model row. Model/effort dominance is measured by reference-value share, so a dominant-model label still permits up to 5% other workload value.

Candidate windows are fixed UTC hour bins selected independently of observed efficiency. Endpoints use fresh account-tagged provider readings with positive usage. Timing eligibility requires at most one second of reset spread, at least 30 minutes of span, no observation gap over 30 minutes, no step below −1 point and positive net movement. The first/last samples lie inside the hour, so an eligible interval need not last 60 minutes.

Of 3,382 candidate windows, 673 meet timing controls. Forty-four candidates are five-hour windows and none qualifies. Weekly windows produce 641 rows with recovered exposure, of which 192 meet the primary controls: at least five points, at least 95% dominant-model/effort value, at least 95% strict-source value, known supported prices and matching quota deadlines. Sensitivity partitions repeat the analysis at 80%, 90% and 95% dominance and two, five and ten points.

### Reset epochs and uncertainty

Positive weekly readings are segmented when the same account's deadline changes by more than 30 seconds. This tolerance handles probe jitter within an account and is never used for cross-account identity. An epoch's consumption interval runs from its first positive observation to its first observed maximum. Idle zero readings have floating deadlines and are excluded. The resulting 123 positive epochs describe recovered intervals rather than complete paid weeks.

Nearly complete comparisons require at least 80 points, the same provenance/pricing/dominance controls, and no consumption observation gap over 1,830 seconds. Thirty extra seconds allow recorded probe jitter. Most selected epochs cover 99 points, so their dollar sums are observed 99-point values, without extrapolation to an unseen full allowance. The separate historical annotation file revises three original transition labels.

For value `V` and observed quota change `Q`, the descriptive slope is `V/Q`. Timing sensitivities recalculate value inside endpoints inset by 120 seconds and enclosing endpoints extended by 120 seconds. For `n` intervals, rounding sensitivities divide those values by `Q + e×n` and `Q − e×n`, with `e` equal to one or two points. The upper expression is undefined if the denominator is nonpositive. These are conditional sensitivity bounds, not statistical confidence intervals. They do not bound unrecovered workload, unknown service tiers or hidden metering weights.
<!-- END CLEAN TEXT -->

## Internal traceability

Sources: build_ledger.py, replay_audit.py, account_calls.sql, hour_cohorts.sql, bank_epochs.sql, analysis_views.sql, lease-corroboration.json and account-window-audit.json. Component: forensics evidence classes and cross-source proof. Explain population transitions before numerical results. Strict survival and source agreement must not become proof of an entire paid account's delivered consumption. Reader-required implementation details are retained here because they determine estimands and reproducibility.
