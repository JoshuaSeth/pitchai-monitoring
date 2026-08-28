# Monitoring operator dashboard audit — 2026-08-24

## Product evidence

This audit is based on current source, the production edge, the running
containers, the production monitor state, and authenticated headed-Chrome
captures. It is not based on a mock dashboard.

| Surface | Current evidence | Decision |
| --- | --- | --- |
| `https://tools.pitchai.net/` | Entra SSO returns the static nine-route company directory. Desktop 1440×1000 and mobile 390×844 have no horizontal overflow, console errors, or failed requests. | Preserve its white/green business system. Make the monitoring destination explicit. |
| `https://monitoring.pitchai.net/dashboard` | The edge requires Entra SSO, but deployed image `service-monitoring:ff1c37af47949d061b96915c42a377d03775928f` redirects an authenticated operator to a second monitoring-token form. | Deploy the already-merged Entra identity contract; remove the redundant token hop. |
| Monitor state | The production state file is about 15 MB and updates within seconds. At inventory it reported 11 known domains, one effective outage, four degraded signal families, and 46 events in the prior 24 hours. | Keep the state file as the dashboard authority and expose freshness honestly. |
| E2E registry | Production contains 36 registered tests and 180,759 runs; the live summary reported two effective failures at inventory time. | Keep this registry as the E2E authority. Never replace unavailable values with fabricated green status. |
| Existing dashboard | Real data and useful diagnostics, but dark glass styling, raw paths, a CDN chart dependency, dense tables, and a second credential prompt make it a poor central operator route. | Surgical redesign of the operator dashboard only; preserve tenant APIs, scheduler, runner, state, and alerting behavior. |

## Relevant-file audit

| File | Classification | Preserved behavior | Planned change |
| --- | --- | --- | --- |
| `e2e_registry/monitor_dashboard.py` | backend/business data | domain history, warning derivation, signal history, range resolution | Add explicit freshness, incident/problem, E2E, and latest-24-hour summaries from existing state. |
| `e2e_registry/app.py` | backend/auth/route shell | Entra identity validation, machine bearer routes, tenant isolation | Keep identity boundaries; mount dashboard-owned static assets and keep browser API aliases under `/dashboard/api/`. |
| `e2e_registry/settings.py` | backend/config | state/config paths and identity-header configuration | No secret-bearing settings in rendered output; preserve config contract. |
| `e2e_registry/templates/base.html` | shared visual primitive | tenant E2E navigation and form primitives | Add a narrow operator-only head/body hook without restyling tenant pages. |
| `e2e_registry/templates/dashboard.html` | operator visual shell | range, domains, signals, events, dispatch diagnostics | Replace the dark inline implementation with a semantic white/green operations cockpit. |
| `tests/test_monitor_dashboard_ui_e2e.py` | test | real FastAPI + browser route/auth/data checks | Assert new summaries, responsive layout, local assets, and SSO-native URLs. |
| `ops/monitoring.pitchai.net.nginx.conf` | edge/security | Entra subrequest, browser identity headers, bearer-only machine API | Keep the boundary exact; verify no dashboard-token form survives. |
| `Dockerfile` and CI | delivery | one reproducible service image and current quality gates | Include local dashboard assets in the existing image; no new service or runtime dependency. |

## Visual extraction

### Palette

- Canvas: cool white `#f4f7f5` to `#eef4f1`.
- Primary ink: deep PitchAI green `#0b4638`.
- Accent: operational green `#08785f`.
- Quiet text: slate/green `#5d6f68`.
- Borders: restrained blue-green gray `#c9d8d2`.
- Healthy, warning, and critical states remain semantic and never rely on color alone.

### Typography

- System sans stack for fast rendering and zero font dependency.
- Compact uppercase labels only for hierarchy, not decoration.
- Large numbers use tabular figures; code/hostnames use the existing monospace stack.
- Plain operator language: “Fresh”, “Needs attention”, “Latest daily status”, “No investigations in this window”.

### Spacing and density

- 24–32 px page rhythm on desktop, 16–20 px on mobile.
- KPI cards stay compact enough to show the first operational row without scrolling at 1440×1000.
- Diagnostic detail moves below current incidents, domain health, and daily status.

### Geometry

- 1 px borders and 14–18 px radii match the live tools portal.
- Cards use clear rectangular structure; no floating decorative blobs, glass panels, or oversized pills.
- Status dots are paired with explicit text.

### Depth

- Very light shadows only on primary cards.
- Sections are separated primarily by spacing and rules.
- No blur or translucent backdrop effects.

### Responsive behavior

- Four KPI columns collapse to two and then one.
- The domain table becomes labeled rows on narrow screens; no viewport overflow.
- Header identity truncates safely and navigation remains reachable.
- Charts use local inline SVG output and scale to their containers.

### Interaction

- Range and refresh controls retain their existing behavior.
- Domain selection remains keyboard- and pointer-usable.
- All data requests stay same-origin and credentialed.
- Loading, stale, unavailable, degraded, and empty states are explicit.

## Information architecture

1. Operator header with Tools return route and current PitchAI identity.
2. Current posture and freshness.
3. Four evidence cards: state freshness, services, E2E, and 24-hour status.
4. Current incidents beside the latest daily status.
5. Domain health and selected-domain history.
6. System signals, recent events, and diagnostic investigations.
7. Compact provenance footer without leaking secrets.

## Data contract prescription

The summary response will add these derived, real-data-only fields:

- `freshness`: monitor state timestamp, age, configured interval, and explicit fresh/stale/unknown state;
- `service_health`: enabled/healthy/down/disabled counts;
- `incidents`: current domain, signal, E2E, and freshness problems;
- `daily_status`: 24-hour observations, aggregate availability, problem events, recoveries, and status;
- `external_e2e`: existing registry summary, preserved without invented defaults.

If a source value is absent, the UI says “Unavailable” or “No observations”. It
does not silently convert missing data into success.

## Concept-generation constraint

The approved ChatGPT Pro browser profile was cloned and opened in headed Chrome
for the requested concept lane. The visible site stopped at a Cloudflare
“Just a moment…” challenge. The browser skill forbids backend/API submission,
cookie extraction, or challenge workarounds, so that lane was stopped. The
fallback is the strongest available first-party visual reference: the verified
live tools portal, combined with this source/data audit and deterministic
browser screenshot iteration.

## Acceptance gates

- Authenticated portal navigation opens `/dashboard` without a second token form.
- Fresh unauthenticated navigation still goes through `auth.pitchai.net`.
- Current freshness, domain/service health, E2E, incidents, and latest daily status are visible and originate in live state.
- No CDN or dummy-data dependency is required for the operator page.
- Desktop 1440×1000 and mobile 390×844 have no overflow, console errors, or failed requests.
- Source, image tag, PR/merge commit, and live runtime are reconciled before closeout.
