# Monitoring dashboard completion audit

This audit maps Seth/ORI's monitoring objective to evidence that must exist
before the work is considered complete. A checked implementation box is not a
deployment claim; production rows remain open until verified against the live
service.

## Requirement-to-evidence matrix

| Requirement | Implementation evidence | Validation evidence | Production evidence | State |
|---|---|---|---|---|
| Reproduce the non-actionable production incident view | Baseline inventory and DOM/API capture | `production-before-desktop.png`; 16 incident rows, zero disclosure controls | Existing production image `service-monitoring:b27bdd17f9db6737e332305780ec3cc0baf84721` | Proven baseline |
| Expandable actionable incidents | Stable incident IDs, disclosure UI, safe evidence contract | Summary/API tests and headed-browser disclosure tests | Pending deployed browser capture | Implemented; deployment pending |
| All required incident fields | Check/service/status, first/latest seen, status/error, safe response excerpt, last success, trend, owner, severity, alert policy, next action | Contract assertions in `test_monitor_dashboard_summary.py` and safe-evidence tests | Pending deployed expanded incident capture | Implemented; deployment pending |
| Accessible collapse/expand | Native buttons, `aria-expanded`, `aria-controls`, focus restoration | Keyboard browser assertions | Pending deployed keyboard pass | Implemented; deployment pending |
| Research and select three must-have tabs | Google SRE, Grafana and OpenTelemetry primary-source review in the UI inventory | Architecture rationale selects Infrastructure, Reliability and Journeys | N/A | Proven |
| Infrastructure tab uses real data | Existing host snapshot/history, thresholds and retained container restart counters; no dashboard probes | Aggregation and browser rendering assertions | Pending deployed state/API capture | Implemented; deployment pending |
| Reliability tab uses real data | Existing domain samples/events, SLO target, routing policy and group aggregation | Aggregation and browser rendering assertions | Pending deployed state/API capture | Implemented; deployment pending |
| Journeys tab uses real data | Existing E2E registry summary and dispatch history | Aggregation and browser rendering assertions | Pending deployed state/API capture | Implemented; deployment pending |
| Cheap polling | All tab summaries reuse already-retained monitor/E2E state | Contract exposes `dashboard_extra_probes: 0`; request-count browser test | Pending deployed request trace | Implemented; deployment pending |
| Preserve coverage/grouping/alerts | 60-domain config, DFT/Potato groups, exact five dashboard-only routes | Config, plugin and alert-policy tests | Pending production state reconciliation | Implemented; deployment pending |
| Design workflow | Ten sequential ChatGPT Pro directions; three deterministic Jinja2/Tailwind builds | `design/monitoring-dashboard` renders, screenshots, comparisons and `view_image` review | N/A | Concepts 1–9 generated/submitted; final concept and comparisons pending |
| Local real-browser quality | Desktop/mobile, tabs, disclosure, requests, console and overflow | Headed Chrome suite plus `uv run dev` public preview | N/A | Browser suite green; public preview pending |
| Commit/PR/merge/deploy | Feature branch and task-linked PR | Required checks and merge receipts | Production image/SHA and URL | Pending |
| Private Seth/ORI proof | One requester-private Telegram message only | Telegram delivery receipt | Screenshots, URL, visible details, tabs and residual risks | Pending |
| PM closure | Current PM workpad, PR/deployment links and changelog | Task state `Done` | Changelog record | Pending |

## Safety boundaries

- Response evidence is limited to human-readable text/JSON/XML, bounded before
  persistence/display, and redacted for secrets, credentials, contact data,
  private paths, opaque identifiers and query strings.
- Dashboard-only domains remain visible but do not route Telegram alerts.
- No client, vendor or other external message is authorized by this task.
- Missing, stale, summary-only and unavailable states are labels, not inferred
  values.
