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

The sensitivity values use dated prices. Cached input dominates the token totals, and each cohort's cache share differs. A million total tokens therefore does not represent a common uncached or output workload. Reasoning is included in output and is priced once within that total. Independent per-component hidden quota weights cannot be estimated uniquely when the components move together and the hidden denominator is unknown. The [comparison summary](evidence/cohort-comparisons.json) contains separate component sums and two-point endpoint sensitivities.

Two GPT-5.5/medium hours also pass the declared numerical controls but contain only 51 recovered calls while the account moves 24 points. Their $0.271 per point is sensitive to missing workload and provides weak evidence about model efficiency. A high dominant-model share can still occur when other workload is missing. No pure xhigh cohort passes the primary controls, so this dataset cannot rank xhigh against max.

[Threshold sensitivity tables](evidence/cohort-comparisons.json) report different dominance and point thresholds. Similar results across thresholds support the observed pattern. They still share the limits from unknown tiers, correlated workload and missing calls.

![Dated and fixed-price USD per reported weekly point, with conditional endpoint sensitivities for the four main cohorts.](figures/hourly-value.svg)
<!-- END CLEAN TEXT -->

## Internal V4 provenance

Input: [V3](12-capacity-v3.md). The separate [instruction-leakage audit](instruction-leakage-pass.md) covers this clean text, its figures and the assembled report. Only text between the markers is assembled.
