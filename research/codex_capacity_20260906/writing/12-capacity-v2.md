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

Astra/high yields 52.9% of September Sol/max's API-equivalent dollars per reported point. Astra's short-context standard token prices are 2.5× Sol's. Expressing Astra's token shape at Sol prices gives about $3.74 per point, compared with $17.65 for September Sol, an approximately 4.72× quota-per-priced-workload association. The corresponding comparison with late-August Sol is about 5.12×. These magnitudes resemble the Reddit model allegation, but the available observations change effort, accounts, dates and reset status together. They do not identify the effect of selecting Astra, high, xhigh or max alone.

### Token components and endpoint sensitivity

| Cohort | Reported points per million total tokens | Reasoning share of output | USD/point with ±120 seconds and ±1 point per interval |
| --- | ---: | ---: | ---: |
| Sol/max, before 21 August | 0.03303 | 30.91% | 18.16–28.27 |
| Sol/max, 21–31 August | 0.02873 | 32.25% | 15.69–23.64 |
| Sol/max, 1–6 September | 0.02988 | 35.66% | 14.60–21.54 |
| Astra/high, 5–6 September | 0.13640 | 19.91% | 8.34–10.48 |

The sensitivity values use dated prices. Cached input dominates the token totals, and each cohort's cache share differs. A million total tokens therefore does not represent a common uncached or output workload. Reasoning is included in output and is priced once within that total. Independent per-component hidden quota weights cannot be estimated uniquely when the components move together and the hidden denominator is unknown. The machine-readable summary retains separate component sums and two-point endpoint sensitivities.

Two GPT-5.5/medium hours also pass the declared numerical controls but contain only 51 recovered calls while the account moves 24 points. Their $0.271 per point is sensitive to missing workload and provides weak evidence about model efficiency. A high dominant-model share can still occur when other workload is missing. No pure xhigh cohort passes the primary controls, so this dataset cannot rank xhigh against max.

[Threshold sensitivity tables](evidence/cohort-comparisons.json) report different dominance and point thresholds. A repeated association under those thresholds strengthens its descriptive stability, while unknown service tiers, correlated workload and missing calls remain outside those controls.
<!-- END CLEAN TEXT -->

## Internal language pass one

Input: [V1](11-capacity-v1.md). Each numbered unit below is one prose sentence, table row, heading or indivisible code block, in source order. Table rows and code preserve their structure. This is a language review, with factual verification recorded separately.

| Unit | Source opening | Decision |
| ---: | --- | --- |
| 1 | ## Capacity over time, models and reasoning | Retain descriptive heading for navigation. |
| 2 | The primary hourly comparison describes workload assigned to an account divided by it… | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 3 | Dominant model and effort identify a cohort rather than a causal treatment. | Explain why the label is descriptive. |
| 4 | / Model / effort and start period / Hours / Accounts / epochs / Calls / Points / Date… | Retain units, numeric precision and evidence qualification in this table row. |
| 5 | / --- / ---: / ---: / ---: / ---: / ---: / ---: / ---: / | Retain units, numeric precision and evidence qualification in this table row. |
| 6 | / Sol/max, before 21 August / 42 / 6 / 12 / 62,002 / 281 / 22.52 / 17.59 / 96.87% / | Retain units, numeric precision and evidence qualification in this table row. |
| 7 | / Sol/max, 21–31 August / 102 / 6 / 17 / 207,537 / 803 / 19.14 / 19.14 / 97.48% / | Retain units, numeric precision and evidence qualification in this table row. |
| 8 | / Sol/max, 1–6 September / 35 / 7 / 11 / 68,833 / 277 / 17.65 / 17.65 / 98.00% / | Retain units, numeric precision and evidence qualification in this table row. |
| 9 | / Astra/high, 5–6 September / 11 / 3 / 4 / 12,104 / 226 / 9.34 / 9.34 / 97.52% / | Retain units, numeric precision and evidence qualification in this table row. |
| 10 | The first Sol cohort falls from $22.52 to $17.59 per point when the same workload is … | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 11 | Its dated dollar decline is therefore partly a price effect. | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 12 | At common prices, the three Sol periods are $17.59, $19.14 and $17.65. | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 13 | That pattern does not show a monotonic decline across these periods. | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 14 | The later Sol decline from $19.14 to $17.65 is a 7.8% descriptive association, with o… | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 15 | Astra/high yields 52.9% of September Sol/max's API-equivalent dollars per reported po… | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 16 | Astra's short-context standard token prices are 2.5× Sol's. | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 17 | Expressing Astra's token shape at Sol prices gives about $3.74 per point, compared wi… | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 18 | The corresponding comparison with late-August Sol is about 5.12×. | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 19 | These magnitudes resemble the Reddit model allegation, but the available observations… | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 20 | They do not identify the effect of selecting Astra, high, xhigh or max alone. | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 21 | ### Token components and endpoint sensitivity | Retain descriptive heading for navigation. |
| 22 | / Cohort / Reported points per million total tokens / Reasoning share of output / USD… | Retain units, numeric precision and evidence qualification in this table row. |
| 23 | / --- / ---: / ---: / ---: / | Retain units, numeric precision and evidence qualification in this table row. |
| 24 | / Sol/max, before 21 August / 0.03303 / 30.91% / 18.16–28.27 / | Retain units, numeric precision and evidence qualification in this table row. |
| 25 | / Sol/max, 21–31 August / 0.02873 / 32.25% / 15.69–23.64 / | Retain units, numeric precision and evidence qualification in this table row. |
| 26 | / Sol/max, 1–6 September / 0.02988 / 35.66% / 14.60–21.54 / | Retain units, numeric precision and evidence qualification in this table row. |
| 27 | / Astra/high, 5–6 September / 0.13640 / 19.91% / 8.34–10.48 / | Retain units, numeric precision and evidence qualification in this table row. |
| 28 | The sensitivity values use dated prices. | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 29 | Cached input dominates the token totals, and each cohort's cache share differs. | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 30 | A million total tokens therefore does not represent a common uncached or output workl… | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 31 | Reasoning is a descriptive subset of output, not an additional priced component. | State the accounting relation directly. |
| 32 | Independent per-component hidden quota weights cannot be estimated uniquely when the … | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 33 | The machine-readable summary retains separate component sums and two-point endpoint s… | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 34 | Two GPT-5.5/medium hours also pass the declared numerical controls but contain only 5… | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 35 | Their $0.271 per point is a coverage warning, not persuasive evidence of an extremely… | Remove a rhetorical contrast and temper the interpretation. |
| 36 | Including them in the published cohort inventory exposes the limitation of dominance … | Present the methodological limitation without narrating report construction. |
| 37 | No pure xhigh cohort passes the primary controls, so this dataset cannot rank xhigh a… | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 38 | Threshold sensitivity tables preserve results at different dominance and point thresh… | Add the actual result location. |
| 39 | A repeated association under those thresholds strengthens its descriptive stability, … | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |

Pass one uses direct subjects and verbs, removes formulaic contrasts and expands ambiguous terms. Required limits on identity, pricing and causal interpretation stay beside the affected claims. Technical methods and source citations remain necessary in this empirical report. No commercial promise is added.
