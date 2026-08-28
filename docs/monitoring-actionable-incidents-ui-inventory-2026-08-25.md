# Monitoring dashboard: actionable incidents and operator views

Date: 2026-08-25

## Product and audience

The PitchAI monitoring dashboard is the internal, read-only operations cockpit at
`monitoring.pitchai.net`. It is used by Seth/ORI and PitchAI operators to answer
three questions quickly:

1. What is broken for users right now?
2. What evidence explains the failure and who is likely responsible?
3. What should the operator inspect or do next?

The dashboard is protected by PitchAI Entra identity. Machine APIs retain their
separate bearer-token boundary. No monitoring UI may expose secrets, cookies,
authorization headers, private response content, or raw credentials.

## Production reproduction

Reference screenshot:
[`docs/evidence/monitoring-actionable-incidents-2026-08-25/production-before-desktop.png`](evidence/monitoring-actionable-incidents-2026-08-25/production-before-desktop.png)

Live headed-Chrome reproduction against the deployed production container:

- 16 current incident rows rendered.
- The incident list contained zero buttons and zero `aria-expanded` controls.
- Each row exposed only a title, one prose sentence, and relative time.
- The first critical row showed `dispatch.pitchai.net`, an API/service subcheck,
  205 failing cycles, and a relative timestamp.
- The incident API exposed `kind`, `severity`, title/detail, identifiers,
  observation time, status code, and Telegram policy for domain failures. It did
  not expose first-seen time, last success, trend, safe response evidence,
  ownership, or a suggested action.
- No console, page, request, or horizontal-overflow errors were present in the
  current production page.

This proves the reported limitation: red/degraded incidents are visible but do
not provide an operator-grade drill-down.

## Existing real data sources

The implementation must reuse these bounded sources instead of adding frequent
new production probes:

- `state.json` domain history: effective up/down, HTTP/browser latency, status
  code, 14-day retention.
- `state.json` signal history: host capacity, SLO, RED, TLS, DNS, containers,
  proxy, browser, performance, and monitor integrity.
- `host_last_snapshot`: CPU, memory, swap, load, disk, and host uptime evidence.
- Docker health collector: running state, health status, restart counts, OOM and
  exit evidence for the configured container scope.
- Monitor events: transition events and recovery events, bounded to 2,000 rows.
- External E2E registry: enabled tests, effective status, failure streaks,
  timestamps, base URLs, and dispatch investigations.
- Canonical domain inventory: project/group, environment, kind, disabled state,
  and explicit Telegram policy.

## External monitoring guidance

- Google SRE says dashboards should answer basic service questions, distinguish
  symptoms from causes, support retrospective debugging, and cover latency,
  traffic, errors, and saturation. It also recommends simple, low-noise alerting:
  <https://sre.google/sre-book/monitoring-distributed-systems/>.
- Grafana recommends RED for user symptoms, USE for infrastructure causes,
  hierarchical drill-downs, meaningful color, and refresh intervals matched to
  data cadence rather than unnecessary polling:
  <https://grafana.com/docs/grafana/latest/visualizations/dashboards/build-dashboards/best-practices/>.
- Grafana incident guidance ties incidents to a service, owner/team, severity,
  environment, SLO impact, and a response timeline:
  <https://grafana.com/docs/grafana-cloud/observe-and-act/respond-to-incidents/guides/best-practices/incidents/>.
- Grafana alerting guidance says an alert should explain what triggered, why it
  exists, who owns it, how it routes, and how to investigate; non-actionable
  conditions belong on a dashboard rather than in notifications:
  <https://grafana.com/docs/grafana/latest/alerting/guides/best-practices/> and
  <https://grafana.com/docs/grafana/latest/alerting/fundamentals/alert-rules/annotation-label/>.
- OpenTelemetry recommends explicit service and deployment identity so telemetry
  can be narrowed to a service, host, process, or container:
  <https://opentelemetry.io/docs/concepts/resources/>.

## Three selected must-have tabs

### 1. Infrastructure

Question: **Are the machines and containers able to serve the product?**

Use the existing host and Docker collectors to show current CPU, memory, swap,
load, disk saturation, host uptime, monitored container state, health, restarts,
and freshness. This is PitchAI's USE/cause view. Missing Docker or host fields
must be labelled unavailable or stale, never guessed.

### 2. Reliability

Question: **Which services are consuming reliability budget or recurring?**

Aggregate retained domain and signal samples by project/group for availability,
error budget, failures, latency, incident transitions, and recoveries. Include a
clear routing-policy inventory so the operator can distinguish alertable
production failures from expected/dashboard-only conditions. This is the
longitudinal SLO/RED and incident-history view.

### 3. Journeys

Question: **Do the business-critical user flows work end to end?**

Use the live E2E registry and dispatch records to show every enabled hotpath,
effective pass/fail state, failure streak, last completion, target service, and
recent automated investigation. This provides a black-box/user-impact view that
domain reachability alone cannot supply.

## Incident expansion contract

Every current incident must have an accessible, stable disclosure control. The
expanded view must show, when available:

- affected check, domain, service/project, and environment;
- current status and failure source;
- first seen and latest seen timestamps;
- HTTP/status/error evidence and a conservatively redacted response excerpt;
- last successful retained sample;
- short-window trend and failure streak;
- likely owner/project;
- severity and explicit Telegram alert policy;
- one concrete suggested next action;
- a clear unavailable label for genuinely missing evidence.

The summary row remains scannable. Expansion uses a native button with
`aria-expanded` and an associated details region, works with Enter/Space, has a
visible focus state, and does not make the entire page horizontally scroll.

## Polling and load budget

- Keep the existing operator-triggered/window-triggered summary load model.
- Return the new tab aggregates in the existing summary response where compact.
- Reuse retained samples; do not re-query monitored domains from the dashboard.
- Reuse the existing periodic Docker and host passes; container inventory is
  persisted from the same Docker inspection rather than collected again.
- Downsample chart series and cap incident/evidence excerpts and event scans.

## Preserved invariants

- The complete canonical domain inventory stays visible.
- The exact dashboard-only domains remain non-Telegram:
  `registry.pitchai.net`, `agentcloud.pitchai.net`, `dashboards.pitchai.net`,
  `support.pitchai.net`, and `cursussen.pitchai.net`.
- Critical production domains continue to route Telegram alerts.
- `aardappelprijs.nl` remains in the `potaito` group.
- DFT and other project groupings remain unchanged.
- Public health remains redacted; dashboard and machine auth modes stay separate.

## Visual direction

Keep the existing calm PitchAI green system and dense operator ergonomics, but
flatten the interface. Navigation should be a single compact tab rail. The
incident list remains the primary focal point; expanded evidence uses alignment,
two-column definition rows, quiet dividers, and one emphasized next-action strip
instead of nested cards. Critical, warning, expected, healthy, stale, and missing
states must be distinguishable by text and iconography as well as color.

Target viewports are 1440×1000 desktop and 390×844 mobile. The UI must remain
usable for 60+ domains, 10+ signals, and dozens of E2E rows without oversized
empty surfaces or repeated summary facts.
