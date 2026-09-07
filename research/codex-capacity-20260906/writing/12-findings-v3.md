<!-- BEGIN CLEAN TEXT -->
## Fourteen findings and their confidence

Confidence refers to each stated observation. The provider's hidden rules remain unobserved.

| # | Finding | Evidence and confidence |
| ---: | --- | --- |
| 1 | Replayed history materially inflates naive consumption totals: 37.1% of candidate calls and 41.5% of standard reference value are later cross-source copies. | High for the declared turn/full-counter identity rule. Replay cost and method-validation artifacts retain exceptions. |
| 2 | July account values span 15.0–26.0 times EUR200, while August spans 10.1–85.6 times the benchmark. | High for the conditional arithmetic, limited for delivered or billed value because coverage, identity and paid exposure are incomplete. [Account-month table](tables/account_months.csv). |
| 3 | The actual return on paid subscription spend is unidentifiable from the available receipts. Scheduled cancellation, a free-month offer and current Pro status do not establish invoice amounts or continuous paid exposure. | High for the evidence gap within searched sources. Billing reviews and historical notices. |
| 4 | Sol's August API price cut explains a substantial apparent dollar-capacity reduction. Earlier Sol value changes from $22.52 to $17.59 per point when repriced at later rates. | High arithmetic and dated-price support, with intraday price-boundary qualification. Pricing table and hourly summary. |
| 5 | The constant-price Sol sequence, $17.59→$19.14→$17.65 per point, is not a monotonic decline. | Medium descriptive inference from 179 controlled hours. Different account/date/workload mixtures remain. |
| 6 | Later Astra/high yields $9.34 per point versus September Sol/max's $17.65. The constant-price workload association is about 4.72× after accounting for Astra's 2.5× API prices. | Medium for the association, insufficient for a causal model factor. Eleven Astra hours across three accounts and four epochs. |
| 7 | No pure xhigh cohort passes the primary controls. This history cannot determine whether xhigh or max independently consumes more quota for equal work. | High negative result of the declared controls. Full cohort and threshold tables. |
| 8 | Three directly recorded August bank windows have similar constant-price value to ordinary-compatible controls. They do not show half capacity. | Medium comparative confidence across three bank accounts, one early-start ordinary control and two later same-account controls. This does not settle September. |
| 9 | Two apparent ordinary controls become ambiguous after original manual-reset evidence is restored. | High for response history, medium for capacity origin. [Historical annotations](evidence/epoch-transition-annotations.json) bind the revised origins to the original rows. |
| 10 | Reset action success can precede fresh zero-quota state. Immediate A07/A08 responses still show 100% after the credit decrement. | High for the original response sequence. Follow-up probes, rather than the immediate broker snapshot, show zero. |
| 11 | Nearly complete Astra/high probable-bank windows differ across accounts: $764.51–$1,023.17 for 99 points. | High for the retained sums, insufficient for unequal entitlement. Three epochs and accounts with workload differences. |
| 12 | Cached input dominates the four main model-period cohorts at roughly 97–98%, while component mix still changes. Reasoning contributes 19.9–35.7% of output in the main comparisons. | High descriptive measurement. Each subset is included once in its parent total. Aggregate token counts do not measure a common unit of useful work. |
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

## Internal language pass two

Input: [V2](12-findings-v2.md). Sentence and table review below is independent of the first pass. V1 remains in its original section file. Each numbered unit is a sentence, heading, table row or code block in input order.

| Unit | V2 opening | Second-pass decision |
| ---: | --- | --- |
| 1 | ## Fourteen findings and their confidence | Retain the subject-specific navigation heading. |
| 2 | Confidence refers to each stated observation. | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 3 | The provider's hidden rules remain unobserved. | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 4 | / # / Finding / Evidence and confidence / | Retain the row's units, scope and uncertainty. No unnatural table label remains. |
| 5 | / ---: / --- / --- / | Retain the row's units, scope and uncertainty. No unnatural table label remains. |
| 6 | / 1 / Replayed history materially inflates naive consumption totals: 37.1% of candida… | Retain the row's units, scope and uncertainty. No unnatural table label remains. |
| 7 | / 2 / July account values span 15.0–26.0 times EUR200, while August spans 10.1–85.6 t… | Make the result easy to inspect. |
| 8 | / 3 / The actual return on paid subscription spend is unidentifiable from the availab… | Retain the row's units, scope and uncertainty. No unnatural table label remains. |
| 9 | / 4 / Sol's August API price cut explains a substantial apparent dollar-capacity redu… | Retain the row's units, scope and uncertainty. No unnatural table label remains. |
| 10 | / 5 / The constant-price Sol sequence, $17.59→$19.14→$17.65 per point, is not a monot… | Retain the row's units, scope and uncertainty. No unnatural table label remains. |
| 11 | / 6 / Later Astra/high yields $9.34 per point versus September Sol/max's $17.65. The … | Retain the row's units, scope and uncertainty. No unnatural table label remains. |
| 12 | / 7 / No pure xhigh cohort passes the primary controls. This history cannot determine… | Retain the row's units, scope and uncertainty. No unnatural table label remains. |
| 13 | / 8 / Three directly recorded August bank windows have similar constant-price value t… | Retain the row's units, scope and uncertainty. No unnatural table label remains. |
| 14 | / 9 / Two apparent ordinary controls become ambiguous after original manual-reset evi… | Replace quality self-evaluation with the concrete trace. |
| 15 | / 10 / Reset action success can precede fresh zero-quota state. Immediate A07/A08 res… | Retain the row's units, scope and uncertainty. No unnatural table label remains. |
| 16 | / 11 / Nearly complete Astra/high probable-bank windows differ across accounts: $764.… | Retain the row's units, scope and uncertainty. No unnatural table label remains. |
| 17 | / 12 / Cached input dominates all primary model-period cohorts at roughly 97–98%, but… | Restrict the claim to the four displayed cohorts, excluding the separate GPT-5.5 coverage outlier. State the subset rule directly. |
| 18 | / 13 / Historical identity and clocks remain material limitations: lease ranges are i… | Retain the row's units, scope and uncertainty. No unnatural table label remains. |
| 19 | / 14 / Five-hour history and prior-data gaps limit retrospective claims. No five-hour… | Retain the row's units, scope and uncertainty. No unnatural table label remains. |
| 20 | ### Measurements that distinguish the explanations | Retain the subject-specific navigation heading. |
| 21 | / Competing explanation / Precise passive observations needed / | Retain the row's units, scope and uncertainty. No unnatural table label remains. |
| 22 | / --- / --- / | Retain the row's units, scope and uncertainty. No unnatural table label remains. |
| 23 | / A banked reset replenishes less than an ordinary reset / Same-account repeated ordi… | Retain the row's units, scope and uncertainty. No unnatural table label remains. |
| 24 | / General metering changed with time / Matched model/effort/tier workloads on multipl… | Retain the row's units, scope and uncertainty. No unnatural table label remains. |
| 25 | / Astra or reasoning effort changes quota weights / Provider request IDs, per-request… | Retain the row's units, scope and uncertainty. No unnatural table label remains. |
| 26 | / Fast or cache-write pricing explains the difference / Actual request and response s… | Retain the row's units, scope and uncertainty. No unnatural table label remains. |
| 27 | / Incomplete telemetry or attribution explains a low slope / Append-only account leas… | Retain the row's units, scope and uncertainty. No unnatural table label remains. |
| 28 | / Paid-plan exposure explains account-month differences / Subscription-linked paid in… | Retain the row's units, scope and uncertainty. No unnatural table label remains. |
| 29 | / Quota percentages or state lag explain an apparent discontinuity / Direct timestamp… | Retain the row's units, scope and uncertainty. No unnatural table label remains. |
| 30 | These observations arise during ordinary work. | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 31 | The current data does not identify absolute hidden-credit capacity or a unique decomp… | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |

The English report retains its original language. This pass targets compressed jargon, abstract nouns, repetitive limits and task narration missed in V2. Decimal values, model/effort labels, dates, equations and executable arguments retain their meaning. Figures show the same retained populations. Necessary uncertainty stays next to the affected comparison. No semicolons, formulaic contrast sentences, defensive client reassurances or nonessential disclaimer stacks are introduced. Phase 13 separately inspects all visible surfaces before assembly.
