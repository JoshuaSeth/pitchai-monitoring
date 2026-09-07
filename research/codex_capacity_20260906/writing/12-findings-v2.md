<!-- BEGIN CLEAN TEXT -->
## Fourteen findings and their confidence

Confidence refers to each stated observation. The provider's hidden rules remain unobserved.

| # | Finding | Evidence and confidence |
| ---: | --- | --- |
| 1 | Replayed history materially inflates naive consumption totals: 37.1% of candidate calls and 41.5% of standard reference value are later cross-source copies. | High for the declared turn/full-counter identity rule. Replay cost and method-validation artifacts retain exceptions. |
| 2 | July account values span 15.0–26.0 times EUR200, while August spans 10.1–85.6 times the benchmark. | High for the conditional arithmetic, limited for delivered or billed value because coverage, identity and paid exposure are incomplete. Account-month CSV. |
| 3 | The actual return on paid subscription spend is unidentifiable from the available receipts. Scheduled cancellation, a free-month offer and current Pro status do not establish invoice amounts or continuous paid exposure. | High for the evidence gap within searched sources. Billing reviews and historical notices. |
| 4 | Sol's August API price cut explains a substantial apparent dollar-capacity reduction. Earlier Sol value changes from $22.52 to $17.59 per point when repriced at later rates. | High arithmetic and dated-price support, with intraday price-boundary qualification. Pricing table and hourly summary. |
| 5 | The constant-price Sol sequence, $17.59→$19.14→$17.65 per point, is not a monotonic decline. | Medium descriptive inference from 179 controlled hours. Different account/date/workload mixtures remain. |
| 6 | Later Astra/high yields $9.34 per point versus September Sol/max's $17.65. The constant-price workload association is about 4.72× after accounting for Astra's 2.5× API prices. | Medium for the association, insufficient for a causal model factor. Eleven Astra hours across three accounts and four epochs. |
| 7 | No pure xhigh cohort passes the primary controls. This history cannot determine whether xhigh or max independently consumes more quota for equal work. | High negative result of the declared controls. Full cohort and threshold tables. |
| 8 | Three directly recorded August bank windows have similar constant-price value to ordinary-compatible controls. They do not show half capacity. | Medium comparative confidence across three bank accounts, one early-start ordinary control and two later same-account controls. This does not settle September. |
| 9 | Two apparent ordinary controls become ambiguous after original manual-reset evidence is restored. | High for response history, medium for capacity origin. Historical annotations preserve the change transparently. |
| 10 | Reset action success can precede fresh zero-quota state. Immediate A07/A08 responses still show 100% after the credit decrement. | High for the original response sequence. Follow-up probes, rather than the immediate broker snapshot, show zero. |
| 11 | Nearly complete Astra/high probable-bank windows differ across accounts: $764.51–$1,023.17 for 99 points. | High for the retained sums, insufficient for unequal entitlement. Three epochs and accounts with workload differences. |
| 12 | Cached input dominates all primary model-period cohorts at roughly 97–98%, but component mix still changes. Reasoning contributes 19.9–35.7% of output in the main comparisons. | High descriptive measurement. Neither subset should be added twice or treated as a common unit of useful work. |
| 13 | Historical identity and clocks remain material limitations: lease ranges are incomplete, and narrative receipts have no stored time zone. | High for source contracts and missing fields. Nearby-probe clock checks support a local-time interpretation without certifying every row. |
| 14 | Five-hour history and prior-data gaps limit retrospective claims. No five-hour candidate passes the primary timing controls, and 108 previously reported recovery observations remain unrecovered. | High for the present inventory. Neither missing telemetry nor absent fields establish zero usage or a quota reduction. |

### Measurements that distinguish the explanations

| Competing explanation | Precise passive observations needed |
| --- | --- |
| A banked reset replenishes less than an ordinary reset | Same-account repeated ordinary and successful banked epochs, with action request/response times, pre/post credit inventory, actual deadlines, stable model/effort and complete concurrent workload. Compare contemporaneous ordinary accounts as well. |
| General metering changed with time | Matched model/effort/tier workloads on multiple accounts spanning the suspected boundary, with ordinary and banked status separated and price held constant. |
| Astra or reasoning effort changes quota weights | Provider request IDs, per-request model and effort, all token components and quota snapshots across naturally occurring within-account model/effort changes. Equal aggregate tokens alone do not establish equal task work. |
| Fast or cache-write pricing explains the difference | Actual request and response service tier, input context length and cache-write/read counters. Distinguish API reference premiums from Codex quota multipliers. |
| Incomplete telemetry or attribution explains a low slope | Append-only account lease acquisition, renewal and release events with capture timestamps, plus a stable anonymous account ID on each request and terminal execution record. |
| Paid-plan exposure explains account-month differences | Subscription-linked paid invoices, currency, tax, discount, entitlement start/end and resubscription times. Reconcile calendar usage with each billing cycle. |
| Quota percentages or state lag explain an apparent discontinuity | Direct timestamped provider snapshots before and after the action, continuing until inventory and quota agree, with observation time distinct from capture time. |

These observations arise during ordinary work. The current data does not identify absolute hidden-credit capacity or a unique decomposition of the later association into model, effort, workload and bank effects.
<!-- END CLEAN TEXT -->

## Internal language pass one

Input: [V1](11-findings-v1.md). Each numbered unit below is one prose sentence, table row, heading or indivisible code block, in source order. Table rows and code preserve their structure. This is a language review, with factual verification recorded separately.

| Unit | Source opening | Decision |
| ---: | --- | --- |
| 1 | ## Fourteen findings and their confidence | Retain descriptive heading for navigation. |
| 2 | Confidence describes support for the stated observation, not certainty about a provid… | Explain the confidence scale directly. |
| 3 | / # / Finding / Evidence and confidence / | Retain units, numeric precision and evidence qualification in this table row. |
| 4 | / ---: / --- / --- / | Retain units, numeric precision and evidence qualification in this table row. |
| 5 | / 1 / Replayed history materially inflates naive consumption totals: 37.1% of candida… | Retain units, numeric precision and evidence qualification in this table row. |
| 6 | / 2 / July account values span 15.0–26.0 times EUR200, while August spans 10.1–85.6 t… | Retain units, numeric precision and evidence qualification in this table row. |
| 7 | / 3 / Actual subscription ROI is unidentifiable from the available receipts. Schedule… | Expand the unexplained acronym. |
| 8 | / 4 / Sol's August API price cut explains a substantial apparent dollar-capacity redu… | Retain units, numeric precision and evidence qualification in this table row. |
| 9 | / 5 / The constant-price Sol sequence, $17.59→$19.14→$17.65 per point, is not a monot… | Retain units, numeric precision and evidence qualification in this table row. |
| 10 | / 6 / Later Astra/high yields $9.34 per point versus September Sol/max's $17.65. The … | Retain units, numeric precision and evidence qualification in this table row. |
| 11 | / 7 / No pure xhigh cohort passes the primary controls. This history cannot determine… | Retain units, numeric precision and evidence qualification in this table row. |
| 12 | / 8 / Three directly recorded August bank windows have similar constant-price value t… | Retain units, numeric precision and evidence qualification in this table row. |
| 13 | / 9 / Two apparent ordinary controls become ambiguous after original manual-reset evi… | Retain units, numeric precision and evidence qualification in this table row. |
| 14 | / 10 / Reset action success can precede fresh zero-quota state. Immediate A07/A08 res… | Retain units, numeric precision and evidence qualification in this table row. |
| 15 | / 11 / Nearly complete Astra/high probable-bank windows differ across accounts: $764.… | Retain units, numeric precision and evidence qualification in this table row. |
| 16 | / 12 / Cached input dominates all primary model-period cohorts at roughly 97–98%, but… | Retain units, numeric precision and evidence qualification in this table row. |
| 17 | / 13 / Historical identity and clocks remain material limitations: lease ranges are i… | Retain units, numeric precision and evidence qualification in this table row. |
| 18 | / 14 / Five-hour history and prior-data gaps limit retrospective claims. No five-hour… | Retain units, numeric precision and evidence qualification in this table row. |
| 19 | ### Measurements that distinguish the explanations | Retain descriptive heading for navigation. |
| 20 | / Competing explanation / Precise passive observations needed / | Retain units, numeric precision and evidence qualification in this table row. |
| 21 | / --- / --- / | Retain units, numeric precision and evidence qualification in this table row. |
| 22 | / A banked reset replenishes less than an ordinary reset / Same-account repeated ordi… | Retain units, numeric precision and evidence qualification in this table row. |
| 23 | / General metering changed with time / Matched model/effort/tier workloads on multipl… | Retain units, numeric precision and evidence qualification in this table row. |
| 24 | / Astra or reasoning effort changes quota weights / Provider request IDs, per-request… | Retain units, numeric precision and evidence qualification in this table row. |
| 25 | / Fast or cache-write pricing explains the difference / Actual request and response s… | Retain units, numeric precision and evidence qualification in this table row. |
| 26 | / Incomplete telemetry or attribution explains a low slope / Append-only account leas… | Retain units, numeric precision and evidence qualification in this table row. |
| 27 | / Paid-plan exposure explains account-month differences / Subscription-linked paid in… | Retain units, numeric precision and evidence qualification in this table row. |
| 28 | / Quota percentages or state lag explain an apparent discontinuity / Direct timestamp… | Retain units, numeric precision and evidence qualification in this table row. |
| 29 | These observations can be collected from ordinary work. | Avoid an implied delivery commitment. |
| 30 | The current data does not identify absolute hidden-credit capacity or a unique decomp… | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |

Pass one uses direct subjects and verbs, removes formulaic contrasts and expands ambiguous terms. Required limits on identity, pricing and causal interpretation stay beside the affected claims. Technical methods and source citations remain necessary in this empirical report. No commercial promise is added.
