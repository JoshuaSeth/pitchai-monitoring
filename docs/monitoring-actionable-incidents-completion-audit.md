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
| Design workflow | Ten sequential ChatGPT Pro directions; three deterministic Jinja2/Tailwind builds | Exactly 10 final Pro images retained after the 20-minute cutoff; SHA-256 index complete; concepts 01/03/04 score 96.4097%/97.6084%/97.0438% with no masks, crops, or self-comparison | N/A | Proven |
| Local real-browser quality | Desktop/mobile, tabs, disclosure, requests, console and overflow | All 216 repository tests plus bounded public HTTPS preview receipt and original-resolution screenshots | N/A | Proven: five tabs, two incidents, database coverage, 390px fit, zero browser/network errors |
| Commit/PR/merge/deploy | Feature branch and task-linked PR | Required checks and merge receipts | Production image/SHA and URL | Pending |
| Private proof | Retained requester-private evidence bundle | Local screenshots, URL, visible details, tabs and residual risks | No transmission while the latest no-outgoing boundary is active | Live capture pending; outgoing delivery superseded |
| PM closure | Current PM workpad, PR/deployment links and changelog | Task state `Human Review` | Changelog record | Pending |

## Safety boundaries

- Response evidence is limited to human-readable text/JSON/XML, bounded before
  persistence/display, and redacted for secrets, credentials, contact data,
  private paths, opaque identifiers and query strings.
- Dashboard-only domains remain visible but do not route Telegram alerts.
- No client, vendor or other external message is authorized by this task.
- Missing, stale, summary-only and unavailable states are labels, not inferred
  values.
