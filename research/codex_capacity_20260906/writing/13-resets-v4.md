<!-- BEGIN CLEAN TEXT -->
## Banked resets and the reported reduction

Bank inventory and quota deadlines identify several different events. Six guardian redemptions have recorded successful action results. Seventeen additional credits disappear before expiry with a one-credit balance drop and a new positive window. These events are classified as probable redemptions because their action responses are missing. Four earlier manual actions have separate original response corroboration. A credit balance, a zero reading or a deadline change alone cannot establish the amount of replenished capacity.

The 123 positive-epoch origins comprise six guardian redemptions, one manual-response/deadline match, two ambiguous post-manual origins, seventeen inferred credit-loss/new-window events, thirty ordinary-expiry-compatible windows, fifty-nine unexplained early replacements and eight left-censored windows. “Ordinary-compatible” means the first positive observation follows the prior recorded deadline. It does not prove that no unobserved action occurred.

### August comparisons

| Account / first positive date | Origin | Observed points | Dated API-equivalent USD | USD at 6 September prices |
| --- | --- | ---: | ---: | ---: |
| A08 / 13 August | Direct guardian bank | 99 | 2,452.59 | 1,914.53 |
| A01 / 14 August | Direct guardian bank | 99 | 2,527.81 | 1,979.41 |
| A05 / 16 August | Direct guardian bank | 99 | 2,473.92 | 1,935.32 |
| A02 / 20 August | Ordinary-compatible, ends 22 August | 94 | 1,917.21 | 1,841.26 |
| A01 / 23 August | Ordinary-compatible | 99 | 2,002.53 | 2,002.53 |
| A08 / 22 August | Ordinary-compatible | 99 | 1,983.80 | 1,983.80 |

These nearly complete windows have dominant Sol/max usage and pass the source, pricing, reset and observation-gap controls. The three direct bank windows average $19.6272 per point at common prices. A02's ordinary-compatible 94-point window averages $19.5878. Its dated dollar sum has the separate $123.98 price-timing sensitivity described above. Same-account bank-to-later-ordinary ratios are approximately 0.988 for A01 and 0.965 for A08 at common prices. The observed differences are much smaller than halving, although the comparisons occur on different dates and workloads.

Positive quota timestamps alone place A07's 12 August window after its prior recorded expiry. Original responses show a manual reset on 10 August, followed by idle zero readings and a new deadline near 11 August midnight. A08 shows a similar sequence. Their inventories do not lose another credit during the deadline shift. A02 simultaneously moves from 41% to zero with an unchanged credit count. The eventual A07/A08 capacity source remains ambiguous, so these windows cannot serve as ordinary controls.

The manual responses also expose state delay. A07 and A08's immediate consume results still report 100% used after a credit decrement. Fresh later probes report zero. A02's initial broker quota and inventory are also stale. A single immediate snapshot could therefore misdescribe a successful reset.

### Later windows

Three September Sol/max probable-bank windows across two accounts average $17.10 per point over 297 points. One September Sol/max unexplained replacement yields $18.22 per point. The three Astra/high probable-bank windows across A02, A04 and A05 average $9.23 per point over 297 points, with individual 99-point values of $764.51, $952.38 and $1,023.17. There is no contemporaneous, comparable ordinary Astra/high cohort that isolates a recent bank penalty.

The August bank history shows no halving in those observed windows. It cannot refute a new September-specific reduction. The later difference remains an association after basic price, cache, context and source controls. Reset origin, model, effort and workload still overlap.

![Nearly complete quota windows at constant prices, separated by direct bank, ordinary-compatible, ambiguous and inferred origins.](figures/reset-epochs.svg)

### The Reddit claim

The [original discussion](https://www.reddit.com/r/codex/comments/1w951h1/when_tibo/) combines an alleged roughly 4.75× Astra quota factor with a half-value bank-reset claim and an approximately $650 resulting allowance. The linked [author's quantitative comparison](https://www.reddit.com/r/codex/comments/1w8zbz9/i_analyzed_the_allowance_a_banked_reset_gives_vs/) reports:

| Author-reported field | Before reset | After reset |
| --- | ---: | ---: |
| Reported quota movement | 85→99%, 14 points | 0→14%, 14 points |
| Responses | 738 | 489 |
| Input / cached input, million | 114.41 / 108.09 | 63.60 / 61.39 |
| Output / reasoning subset, thousand | 465.5 / 226.3 | 284.7 / 124.9 |
| Astra xhigh / max responses | 276 / 202 | 366 / 0 |
| Compactions / transport retry incidents | 10 / 10 | 1 / 3 |

The before period runs 5 September 19:16 to 6 September 00:21 UTC. The after period runs 01:10–03:14 UTC. Other Astra efforts, Terra, Sol and automatic review also differ between periods. The author acknowledges general quota changes, Astra metering and task-specific premiums as alternatives.

The underlying per-response component ledger, actual service tiers, context lengths, cache-write counts, simultaneous account work and timestamped bank/reset responses are unavailable in the post. Response counts cannot allocate aggregate token costs across models. The table documents an author-reported aggregate difference. It leaves the bank-specific causal factor and combined $650 allowance unestablished.
<!-- END CLEAN TEXT -->

## Internal V4 provenance

Input: [V3](12-resets-v3.md). The separate [instruction-leakage audit](instruction-leakage-pass.md) covers this clean text, its figures and the assembled report. Only text between the markers is assembled.
