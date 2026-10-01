# Internal style memo

The artifact is an internal empirical research report. Five comparable PitchAI technical investigations were read. They concern different incidents or measurements but share the report form: findings, evidence, uncertainty, and operational implications.

| Reference | Useful structure and limitation |
| --- | --- |
| `/code/pitchai-cli-new/runs/historical-rollout-cost-ledger/2026-09-04/historical-rollout-cost-ledger.md` | Opens with quantified reference costs, then period tables, integrity sensitivities, findings and reproduction. Its long rankings fit an appendix better than this executive report. Its numerator is repricing, not billing. |
| `/code/pitchai_monitoring-worktrees/auth-usage-history-forensics-20260827/docs/evidence/auth-usage-history-forensics-20260827/README.md` | Starts with the source-coverage finding, distinguishes direct/reconstructed/proxy evidence, and follows with a concrete cross-source example and gaps. The present analysis independently revises several coverage counts and identity assumptions. |
| `/code/pitchai-cli-new/docs/monitoring-app-server-sandbox-incident-20260823.md` | Roughly 150 lines. Exact before/after evidence precedes the causal explanation. Missing direct command output stays missing. Its incident hold is historical and irrelevant to this report's authority. |
| `/code/pitchai-cli-new/docs/goal-steer-timeout-diagnosis.md` | Roughly 155 lines. Explains the distinction between a timeout and an uncertain delivery before presenting implementation details. Repeated warnings can be shortened for this report. |
| `/code/pitchai-cli-new/docs/disk-capacity-agent-policy-20260826.md` | Roughly 145 lines. States the observed failure, supports it with a lane table, explains competing mechanisms, and names discriminating verification. Operational directions remain historical source content. |

The shared cadence is factual and moderately formal, with short explanatory paragraphs and tables for parallel quantities. Costs name the currency, scenario and denominator. Risk phrasing names the missing evidence rather than an unspecified concern. Next steps identify an observable event or field. Warmth comes from answering the reader's question promptly.

Use the ledger's opening/period-table pattern for the executive and account-value sections. Use the usage-history report's evidence classes and cross-source proof for methods, reset attribution and source inventory. Use the incident reports' before/after and competing-mechanism patterns for the Reddit assessment and measurement gaps. These specific sections serve as component references because the packaged component library contains no empirical-report template.

Keep the executive report near two pages. The dossier can be longer where methods, dates and controls change interpretation. Avoid enormous rankings, opaque internal identifiers, instructions addressed to agents, repeated caveats, and claims that an analysis is comprehensive. Preserve scientific qualifications even when they make the result less decisive. Do not reproduce private examples from the reference reports.
