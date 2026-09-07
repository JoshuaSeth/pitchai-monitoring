<!-- BEGIN CLEAN TEXT -->
## Prices and account-period reference value

The primary numerator applies the actual recorded model's dated standard API rates to each call's uncached input, cached input and output. Output already includes reasoning tokens. Calls without a supported dated price stay unpriced. A separate comparison reprices the same calls at 6 September rates to separate price changes from workload/quota changes.

| Model and effective period | Uncached input / million | Cached input / million | Output / million |
| --- | ---: | ---: | ---: |
| GPT-5.5, from 24 April | $5 | $0.50 | $30 |
| Sol, 26 June–20 August | $5 | $0.50 | $30 |
| Sol, from 21 August | $4 | $0.40 | $20 |
| Terra, 26 June–29 July | $2.50 | $0.25 | $15 |
| Terra, from 30 July | $2 | $0.20 | $12 |
| Luna, 26 June–29 July | $1 | $0.10 | $6 |
| Luna, from 30 July | $0.20 | $0.02 | $1.20 |
| Astra, from 3 September | $10 | $1 | $50 |

The full dated model table is in [pricing.json](pricing.json). Rates come from official [API pricing](https://developers.openai.com/api/docs/pricing), [dated changes](https://developers.openai.com/api/docs/changelog), [GPT-5.6 preview pricing](https://openai.com/index/previewing-gpt-5-6-sol/), the [30 July price update](https://openai.com/index/advancing-the-price-performance-frontier-with-gpt-5-6/) and [Astra's model page](https://developers.openai.com/api/docs/models/gpt-6-astra). A current rate page alone cannot independently establish that an older rate was unchanged. Such retrospective source limits remain in the pricing manifest.

For supported models, calls with input strictly above 272,000 tokens apply 2× input/cache and 1.5× output rates. No long-context call appears in the primary model-period hourly cohorts. All 6,066,658 candidates lack an explicit service-tier field. Standard rates provide the common reference. Compatible Fast rates form a separate sensitivity. Source code forcing a default tier from 11 July is policy evidence without complete historical deployment or override proof.

Sol's Fast API comparison is 2× and Astra's is 2×, while Astra's Codex Fast quota multiplier can be 2.5×. API prices and subscription quota multipliers describe different systems. New-model cache-write counts are absent, so the retained pricing sidecar includes an additional 0–25% uncached-input premium sensitivity. Neither sensitivity establishes the actual historical bill.

USD amounts are converted using the daily [ECB EUR/USD series](https://data.ecb.europa.eu/data/datasets/EXR/EXR.D.USD.EUR.SP00.A), carrying forward the latest prior published business-day rate. September 4's rate, used over the following weekend, is USD1.1622 per EUR. The retained series has 214 dates. API tool fees, tax and regional billing adjustments are outside the token-only reference value. EUR200 is the requested comparison denominator, with no inferred tax gross-up or discount.

`N200 = Σ(call standard USD ÷ daily USD per EUR) ÷ EUR200`

The exact intraday timing of the 21 August Sol price cut is unrecorded. Pricing all 5,803 strict calls on that boundary day at the old instead of new rate adds $123.98. All belong to A02's 20–22 August epoch. Its dated value therefore ranges from $1,917.21 to $2,041.18 under this timing sensitivity. Primary hourly results and all constant-price comparisons are unchanged. [Price-boundary calculation](evidence/price-boundary-sensitivity.json).

### Recovered value divided by EUR200

Each cell shows the benchmark multiple and, in parentheses, the number of distinct days with strict recovered calls. The columns follow calendar periods. Billing-cycle boundaries and usage on missing days remain unknown.

| Account | July | August | 1–6 September, partial |
| --- | ---: | ---: | ---: |
| A01 | 25.73× (12) | 39.93× (17) | 28.87× (4) |
| A02 | 15.02× (9) | 76.15× (13) | 14.80× (4) |
| A03 | 15.96× (12) | 36.67× (26) | 6.90× (3) |
| A04 | 24.05× (12) | 10.80× (2) | 11.01× (2) |
| A05 | 21.06× (8) | 85.64× (17) | 15.79× (4) |
| A06 | 20.31× (6) | 10.12× (2) | 18.76× (3) |
| A07 | 25.98× (14) | 36.68× (13) | 16.60× (2) |
| A08 | 25.70× (8) | 66.64× (14) | 3.39× (1) |

The corresponding recovered EUR totals across these account labels are EUR34,763.93 in July, EUR72,524.71 in August and EUR23,226.44 in partial September. A fleet return on paid spend requires verified seat-month invoice amounts. June 30 also has partial values for A03, A05 and A08 in the complete account-month CSV. Rows with unpriced calls retain their unpriced counts, including 251 strict A01 calls in September and 99 strict A08 calls in August. No numeric amount is substituted for them.

Account differences reflect usage, routing, idle periods, recovery coverage, reset frequency and workload. A06 received a documented routing-weight increase on 18 July. A04 and A06 have provider notices scheduling nonrenewal for 4 and 6 August and little later August workload. Surviving Pro calls resume from 4 September. Those notices do not establish exact paid exposure or resubscription dates. A complimentary-month offer is not evidence of redemption, and API balance notices are excluded from subscription costs.

The available invoice and attribution evidence leaves the actual paid-subscription multiple unidentifiable. The table supplies a conditional benchmark. Unknown missing use and unresolved identity prevent a finite correction based on these data.
<!-- END CLEAN TEXT -->

## Internal language pass one

Input: [V1](11-value-v1.md). Each numbered unit below is one prose sentence, table row, heading or indivisible code block, in source order. Table rows and code preserve their structure. This is a language review, with factual verification recorded separately.

| Unit | Source opening | Decision |
| ---: | --- | --- |
| 1 | ## Prices and account-period reference value | Retain descriptive heading for navigation. |
| 2 | The primary numerator applies the actual recorded model's dated standard API rates to… | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 3 | Reasoning tokens are not added again. | Make the subset relationship explicit. |
| 4 | Calls without a supported dated price stay unpriced. | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 5 | A separate comparison reprices the same calls at 6 September rates to separate price … | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 6 | / Model and effective period / Uncached input / million / Cached input / million / Ou… | Retain units, numeric precision and evidence qualification in this table row. |
| 7 | / --- / ---: / ---: / ---: / | Retain units, numeric precision and evidence qualification in this table row. |
| 8 | / GPT-5.5, from 24 April / $5 / $0.50 / $30 / | Retain units, numeric precision and evidence qualification in this table row. |
| 9 | / Sol, 26 June–20 August / $5 / $0.50 / $30 / | Retain units, numeric precision and evidence qualification in this table row. |
| 10 | / Sol, from 21 August / $4 / $0.40 / $20 / | Retain units, numeric precision and evidence qualification in this table row. |
| 11 | / Terra, 26 June–29 July / $2.50 / $0.25 / $15 / | Retain units, numeric precision and evidence qualification in this table row. |
| 12 | / Terra, from 30 July / $2 / $0.20 / $12 / | Retain units, numeric precision and evidence qualification in this table row. |
| 13 | / Luna, 26 June–29 July / $1 / $0.10 / $6 / | Retain units, numeric precision and evidence qualification in this table row. |
| 14 | / Luna, from 30 July / $0.20 / $0.02 / $1.20 / | Retain units, numeric precision and evidence qualification in this table row. |
| 15 | / Astra, from 3 September / $10 / $1 / $50 / | Retain units, numeric precision and evidence qualification in this table row. |
| 16 | The full dated model table is in [pricing.json](../pricing.json). | Correct the link for the assembled report location. |
| 17 | Rates come from official [API pricing](https://developers.openai.com/api/docs/pricing… | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 18 | A current rate page alone cannot independently establish that an older rate was uncha… | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 19 | Such retrospective source limits remain in the pricing manifest. | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 20 | For supported models, calls with input strictly above 272,000 tokens apply 2× input/c… | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 21 | No long-context call appears in the primary model-period hourly cohorts. | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 22 | All 6,066,658 candidates lack an explicit service-tier field. | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 23 | The standard reference therefore gives a common comparison, with compatible Fast rate… | Shorten the tier explanation. |
| 24 | Source code forcing a default tier from 11 July is policy evidence without complete h… | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 25 | Sol's Fast API comparison is 2× and Astra's is 2×, while Astra's Codex Fast quota mul… | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 26 | API prices and subscription quota multipliers describe different systems. | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 27 | New-model cache-write counts are absent, so the retained pricing sidecar includes an … | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 28 | Neither sensitivity establishes the actual historical bill. | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 29 | USD amounts are converted using the daily [ECB EUR/USD series](https://data.ecb.europ… | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 30 | September 4's rate, used over the following weekend, is USD1.1622 per EUR. | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 31 | The retained series has 214 dates. | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 32 | API tool fees, tax and regional billing adjustments are outside the token-only refere… | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 33 | EUR200 is the requested comparison denominator, with no inferred tax gross-up or disc… | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 34 | `N200 = Σ(call standard USD ÷ daily USD per EUR) ÷ EUR200` | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 35 | ### Recovered value divided by EUR200 | Add the newly verified intraday price bound next to the price assumptions. |
| 36 | Each cell shows the benchmark multiple and, in parentheses, the number of distinct da… | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 37 | These are calendar periods, not verified billing cycles. | State the time coverage directly. |
| 38 | Missing days are not zero-use days. | State the time coverage directly. |
| 39 | / Account / July / August / 1–6 September, partial / | Retain units, numeric precision and evidence qualification in this table row. |
| 40 | / --- / ---: / ---: / ---: / | Retain units, numeric precision and evidence qualification in this table row. |
| 41 | / A01 / 25.73× (12) / 39.93× (17) / 28.87× (4) / | Retain units, numeric precision and evidence qualification in this table row. |
| 42 | / A02 / 15.02× (9) / 76.15× (13) / 14.80× (4) / | Retain units, numeric precision and evidence qualification in this table row. |
| 43 | / A03 / 15.96× (12) / 36.67× (26) / 6.90× (3) / | Retain units, numeric precision and evidence qualification in this table row. |
| 44 | / A04 / 24.05× (12) / 10.80× (2) / 11.01× (2) / | Retain units, numeric precision and evidence qualification in this table row. |
| 45 | / A05 / 21.06× (8) / 85.64× (17) / 15.79× (4) / | Retain units, numeric precision and evidence qualification in this table row. |
| 46 | / A06 / 20.31× (6) / 10.12× (2) / 18.76× (3) / | Retain units, numeric precision and evidence qualification in this table row. |
| 47 | / A07 / 25.98× (14) / 36.68× (13) / 16.60× (2) / | Retain units, numeric precision and evidence qualification in this table row. |
| 48 | / A08 / 25.70× (8) / 66.64× (14) / 3.39× (1) / | Retain units, numeric precision and evidence qualification in this table row. |
| 49 | The corresponding recovered EUR totals across these account labels are EUR34,763.93 i… | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 50 | These sums should not be divided by assumed paid seat-months to claim a fleet invoice… | Replace a prescriptive warning with the missing denominator. |
| 51 | June 30 also has partial values for A03, A05 and A08 in the complete account-month CS… | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 52 | Rows with unpriced calls retain their unpriced counts, including 251 strict A01 calls… | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 53 | No numeric amount is substituted for them. | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 54 | Account differences reflect usage, routing, idle periods, recovery coverage, reset fr… | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 55 | A06 received a documented routing-weight increase on 18 July. | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 56 | A04 and A06 have provider notices scheduling nonrenewal for 4 and 6 August and little… | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 57 | Surviving Pro calls resume from 4 September. | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 58 | Those notices do not establish exact paid exposure or resubscription dates. | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 59 | A complimentary-month offer is not evidence of redemption, and API balance notices ar… | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 60 | Thus the actual paid-subscription multiple remains unidentifiable from the available … | Remove a canned transition. |
| 61 | The table supplies a reproducible conditional benchmark, with no finite data-derived … | Use concrete terms for the bound. |

Pass one uses direct subjects and verbs, removes formulaic contrasts and expands ambiguous terms. Required limits on identity, pricing and causal interpretation stay beside the affected claims. Technical methods and source citations remain necessary in this empirical report. No commercial promise is added.
