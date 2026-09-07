# Required facts

| Required fact | Evidence and disposition |
| --- | --- |
| Reader and decision | Seth: understand observed subscription value, banking and model/effort associations; decide which measurements would distinguish the unresolved explanations. |
| Population and time | Eight anonymous account labels. Raw candidate history runs November 2025–September 6, 2026; quota evidence starts July 2026. Analysis cutoff is September 6 at 20:20 UTC, exclusive. Individual cohorts have narrower coverage. |
| Source coverage | `source_inventory.json`, `evidence/extraction-manifest.json`, `evidence/rollout-import-audit.json`; discovery counts are distinguished from completed extraction totals. Remaining historical reconciliation is tracked explicitly. |
| Workload count | 6,066,658 candidate calls; primary replay correction removes 2,249,296 later cross-source copies. 1,693,319 account-attributed calls survive the stricter source/counter controls. |
| Financial denominator | EUR200 is the user's comparison benchmark. Six matched mailboxes yielded dated provider notices but no paid invoice amount. Actual billing exposure, discounts, tax and resubscription dates remain unproved. |
| Numerator | Dated actual-model standard API-equivalent prices in `pricing.json`; daily ECB exchange rates. Cached input is a subset of input and reasoning is a subset of output. Missing model prices remain missing. |
| Subscription attribution | Historical positive reset fingerprints identify accounts. Lease corroboration is separately graded; renewal intervals are outer bounds, with missing and conflicting history retained. |
| Capacity controls | Fixed UTC-hour and reconstructed-epoch cohorts include reset stability, endpoint freshness, observed quota movement, dominant model/effort, source integrity and dated pricing. |
| Main negative finding | Three directly recorded early banked windows resemble the remaining ordinary-compatible controls at common prices. This is evidence against an always-half-value interpretation; August controls do not identify or disprove a September-specific reduction. A07's August 12 window has ambiguous origin after a manual reset and is excluded from ordinary controls. |
| Main unresolved association | Later Astra/high cohorts show less standard API-equivalent value per reported weekly percentage point than Sol/max cohorts. Model, effort, calendar period, workload and bank status are confounded. No pure xhigh cohort passes the controls. |
| Precision | Timing and percentage-rounding sensitivities are conditional bounds, not confidence intervals and not bounds on missing workloads or unknown service tiers. |
| Output and ownership | Reproducible dossier, concise executive report, standalone graphs/tables and PDF in this research directory; scoped staging PR and merge through repository gates. |
| Delivery | Private Telegram to Seth, with final Markdown and PDF attachments. Existing objective authorizes this exact route. No public or client distribution. |
| Remaining work | Historical reconciliation, remaining accessible billing/reset corroboration, final interpretation and artifacts, quality repairs, integration, delivery and requirement audit. |

No proposal price, legal terms, implementation estimate, maintenance promise or production change is part of this research report.
