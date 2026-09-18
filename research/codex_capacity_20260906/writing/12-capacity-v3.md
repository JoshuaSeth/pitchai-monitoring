<!-- BEGIN CLEAN TEXT -->
## Capacity over time, models and reasoning

The primary hourly comparison describes workload assigned to an account divided by its reported quota movement. Each cohort groups observations by dominant model and effort. Several other workload characteristics change at the same time.

| Model / effort and start period | Hours | Accounts / epochs | Calls | Points | Dated USD/point | Fixed-price USD/point | Cache share |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Sol/max, before 21 August | 42 | 6 / 12 | 62,002 | 281 | 22.52 | 17.59 | 96.87% |
| Sol/max, 21–31 August | 102 | 6 / 17 | 207,537 | 803 | 19.14 | 19.14 | 97.48% |
| Sol/max, 1–6 September | 35 | 7 / 11 | 68,833 | 277 | 17.65 | 17.65 | 98.00% |
| Astra/high, 5–6 September | 11 | 3 / 4 | 12,104 | 226 | 9.34 | 9.34 | 97.52% |

The first Sol cohort falls from $22.52 to $17.59 per point when the same workload is valued at the later rates. Its dated dollar decline is therefore partly a price effect. At common prices, the three Sol periods are $17.59, $19.14 and $17.65. That pattern does not show a monotonic decline across these periods. The later Sol decline from $19.14 to $17.65 is a 7.8% descriptive association, with overlapping conditional sensitivities.

Astra/high yields 52.9% of September Sol/max's API-equivalent dollars per reported point. Astra's short-context standard token prices are 2.5× Sol's. Expressing Astra's token shape at Sol prices gives about $3.74 per point, compared with $17.65 for September Sol, an approximately 4.72× ratio in quota points per dollar of workload valued at Sol prices. The corresponding comparison with late-August Sol is about 5.12×. These magnitudes resemble the Reddit model allegation, but the available observations change effort, accounts, dates and reset status together. They do not identify the effect of selecting Astra, high, xhigh or max alone.

### Token components and endpoint sensitivity

| Cohort | Reported points per million total tokens | Reasoning share of output | USD/point with ±120 seconds and ±1 point per interval |
| --- | ---: | ---: | ---: |
| Sol/max, before 21 August | 0.03303 | 30.91% | 18.16–28.27 |
| Sol/max, 21–31 August | 0.02873 | 32.25% | 15.69–23.64 |
| Sol/max, 1–6 September | 0.02988 | 35.66% | 14.60–21.54 |
| Astra/high, 5–6 September | 0.13640 | 19.91% | 8.34–10.48 |

![Dated and fixed-price USD per reported weekly point, with conditional endpoint sensitivities for the four main cohorts.](figures/hourly-value.svg)

The sensitivity values use dated prices. Cached input dominates the token totals, and each cohort's cache share differs. A million total tokens therefore does not represent a common uncached or output workload. Reasoning is included in output and is priced once within that total. Independent per-component hidden quota weights cannot be estimated uniquely when the components move together and the hidden denominator is unknown. The [comparison summary](evidence/cohort-comparisons.json) contains separate component sums and two-point endpoint sensitivities.

Two GPT-5.5/medium hours also pass the declared numerical controls but contain only 51 recovered calls while the account moves 24 points. Their $0.271 per point is sensitive to missing workload and provides weak evidence about model efficiency. A high dominant-model share can still occur when other workload is missing. No pure xhigh cohort passes the primary controls, so this dataset cannot rank xhigh against max.

[Threshold sensitivity tables](evidence/cohort-comparisons.json) report different dominance and point thresholds. Similar results across thresholds support the observed pattern. They still share the limits from unknown tiers, correlated workload and missing calls.
<!-- END CLEAN TEXT -->

## Internal language pass two

Input: [V2](12-capacity-v2.md). Sentence and table review below is independent of the first pass. V1 remains in its original section file. Each numbered unit is a sentence, heading, table row or code block in input order.

| Unit | V2 opening | Second-pass decision |
| ---: | --- | --- |
| 1 | ## Capacity over time, models and reasoning | Retain the subject-specific navigation heading. |
| 2 | The primary hourly comparison describes workload assigned to an account divided by it… | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 3 | Each cohort groups observations by dominant model and effort. | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 4 | Several other workload characteristics change at the same time. | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 5 | / Model / effort and start period / Hours / Accounts / epochs / Calls / Points / Date… | Retain the row's units, scope and uncertainty. No unnatural table label remains. |
| 6 | / --- / ---: / ---: / ---: / ---: / ---: / ---: / ---: / | Retain the row's units, scope and uncertainty. No unnatural table label remains. |
| 7 | / Sol/max, before 21 August / 42 / 6 / 12 / 62,002 / 281 / 22.52 / 17.59 / 96.87% / | Retain the row's units, scope and uncertainty. No unnatural table label remains. |
| 8 | / Sol/max, 21–31 August / 102 / 6 / 17 / 207,537 / 803 / 19.14 / 19.14 / 97.48% / | Retain the row's units, scope and uncertainty. No unnatural table label remains. |
| 9 | / Sol/max, 1–6 September / 35 / 7 / 11 / 68,833 / 277 / 17.65 / 17.65 / 98.00% / | Retain the row's units, scope and uncertainty. No unnatural table label remains. |
| 10 | / Astra/high, 5–6 September / 11 / 3 / 4 / 12,104 / 226 / 9.34 / 9.34 / 97.52% / | Retain the row's units, scope and uncertainty. No unnatural table label remains. |
| 11 | The first Sol cohort falls from $22.52 to $17.59 per point when the same workload is … | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 12 | Its dated dollar decline is therefore partly a price effect. | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 13 | At common prices, the three Sol periods are $17.59, $19.14 and $17.65. | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 14 | That pattern does not show a monotonic decline across these periods. | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 15 | The later Sol decline from $19.14 to $17.65 is a 7.8% descriptive association, with o… | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 16 | Astra/high yields 52.9% of September Sol/max's API-equivalent dollars per reported po… | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 17 | Astra's short-context standard token prices are 2.5× Sol's. | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 18 | Expressing Astra's token shape at Sol prices gives about $3.74 per point, compared wi… | Unpack the invented compound phrase and specify the denominator. |
| 19 | The corresponding comparison with late-August Sol is about 5.12×. | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 20 | These magnitudes resemble the Reddit model allegation, but the available observations… | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 21 | They do not identify the effect of selecting Astra, high, xhigh or max alone. | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 22 | ### Token components and endpoint sensitivity | Retain the subject-specific navigation heading. |
| 23 | / Cohort / Reported points per million total tokens / Reasoning share of output / USD… | Retain the row's units, scope and uncertainty. No unnatural table label remains. |
| 24 | / --- / ---: / ---: / ---: / | Retain the row's units, scope and uncertainty. No unnatural table label remains. |
| 25 | / Sol/max, before 21 August / 0.03303 / 30.91% / 18.16–28.27 / | Retain the row's units, scope and uncertainty. No unnatural table label remains. |
| 26 | / Sol/max, 21–31 August / 0.02873 / 32.25% / 15.69–23.64 / | Retain the row's units, scope and uncertainty. No unnatural table label remains. |
| 27 | / Sol/max, 1–6 September / 0.02988 / 35.66% / 14.60–21.54 / | Retain the row's units, scope and uncertainty. No unnatural table label remains. |
| 28 | / Astra/high, 5–6 September / 0.13640 / 19.91% / 8.34–10.48 / | Retain the row's units, scope and uncertainty. No unnatural table label remains. |
| 29 | The sensitivity values use dated prices. | Place the conditional-sensitivity figure beside the table. |
| 30 | Cached input dominates the token totals, and each cohort's cache share differs. | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 31 | A million total tokens therefore does not represent a common uncached or output workl… | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 32 | Reasoning is included in output and is priced once within that total. | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 33 | Independent per-component hidden quota weights cannot be estimated uniquely when the … | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 34 | The machine-readable summary retains separate component sums and two-point endpoint s… | Link the technical result without self-evaluation. |
| 35 | Two GPT-5.5/medium hours also pass the declared numerical controls but contain only 5… | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 36 | Their $0.271 per point is sensitive to missing workload and provides weak evidence ab… | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 37 | A high dominant-model share can still occur when other workload is missing. | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 38 | No pure xhigh cohort passes the primary controls, so this dataset cannot rank xhigh a… | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 39 | [Threshold sensitivity tables](evidence/cohort-comparisons.json) report different dom… | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 40 | A repeated association under those thresholds strengthens its descriptive stability, … | Replace stiff abstract nouns with the concrete interpretation. |

The English report retains its original language. This pass targets compressed jargon, abstract nouns, repetitive limits and task narration missed in V2. Decimal values, model/effort labels, dates, equations and executable arguments retain their meaning. Figures show the same retained populations. Necessary uncertainty stays next to the affected comparison. No semicolons, formulaic contrast sentences, defensive client reassurances or nonessential disclaimer stacks are introduced. Phase 13 separately inspects all visible surfaces before assembly.
