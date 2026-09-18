<!-- BEGIN CLEAN TEXT -->
## Prices and account-period reference value

The primary numerator applies the actual recorded model's dated standard API rates to each call's uncached input, cached input and output. Reasoning tokens are not added again. Calls without a supported dated price stay unpriced. A separate comparison reprices the same calls at 6 September rates to separate price changes from workload/quota changes.

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

The full dated model table is in [pricing.json](../pricing.json). Rates come from official [API pricing](https://developers.openai.com/api/docs/pricing), [dated changes](https://developers.openai.com/api/docs/changelog), [GPT-5.6 preview pricing](https://openai.com/index/previewing-gpt-5-6-sol/), the [30 July price update](https://openai.com/index/advancing-the-price-performance-frontier-with-gpt-5-6/) and [Astra's model page](https://developers.openai.com/api/docs/models/gpt-6-astra). A current rate page alone cannot independently establish that an older rate was unchanged. Such retrospective source limits remain in the pricing manifest.

For supported models, calls with input strictly above 272,000 tokens apply 2× input/cache and 1.5× output rates. No long-context call appears in the primary model-period hourly cohorts. All 6,066,658 candidates lack an explicit service-tier field. The standard reference therefore gives a common comparison, with compatible Fast rates treated separately. Source code forcing a default tier from 11 July is policy evidence without complete historical deployment or override proof.

Sol's Fast API comparison is 2× and Astra's is 2×, while Astra's Codex Fast quota multiplier can be 2.5×. API prices and subscription quota multipliers describe different systems. New-model cache-write counts are absent, so the retained pricing sidecar includes an additional 0–25% uncached-input premium sensitivity. Neither sensitivity establishes the actual historical bill.

USD amounts are converted using the daily [ECB EUR/USD series](https://data.ecb.europa.eu/data/datasets/EXR/EXR.D.USD.EUR.SP00.A), carrying forward the latest prior published business-day rate. September 4's rate, used over the following weekend, is USD1.1622 per EUR. The retained series has 214 dates. API tool fees, tax and regional billing adjustments are outside the token-only reference value. EUR200 is the requested comparison denominator, with no inferred tax gross-up or discount.

`N200 = Σ(call standard USD ÷ daily USD per EUR) ÷ EUR200`

### Recovered value divided by EUR200

Each cell shows the benchmark multiple and, in parentheses, the number of distinct days with strict recovered calls. These are calendar periods, not verified billing cycles. Missing days are not zero-use days.

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

The corresponding recovered EUR totals across these account labels are EUR34,763.93 in July, EUR72,524.71 in August and EUR23,226.44 in partial September. These sums should not be divided by assumed paid seat-months to claim a fleet invoice return. June 30 also has partial values for A03, A05 and A08 in the complete account-month CSV. Rows with unpriced calls retain their unpriced counts, including 251 strict A01 calls in September and 99 strict A08 calls in August. No numeric amount is substituted for them.

Account differences reflect usage, routing, idle periods, recovery coverage, reset frequency and workload. A06 received a documented routing-weight increase on 18 July. A04 and A06 have provider notices scheduling nonrenewal for 4 and 6 August and little later August workload. Surviving Pro calls resume from 4 September. Those notices do not establish exact paid exposure or resubscription dates. A complimentary-month offer is not evidence of redemption, and API balance notices are excluded from subscription costs.

Thus the actual paid-subscription multiple remains unidentifiable from the available invoice and attribution evidence. The table supplies a reproducible conditional benchmark, with no finite data-derived correction for unknown missing use or unresolved identity.
<!-- END CLEAN TEXT -->

## Internal traceability

Sources: pricing.json, price_calls.py, account_months.csv, billing-notice-review.json, historical-events.json and ECB series. Component: historical ledger pricing/period tables. These figures answer the benchmark question without defining a month of telemetry as a paid month. Relative links target the assembled dossier directory and need correction during assembly if output location changes. Date-boundary and retrospective price support need explicit final verification. No spend recommendation or tax advice is supplied.
