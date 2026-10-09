# Registry monitoring request boundary

The existing PR204 app repair extracts the three monitoring handlers (six
registered paths) into `e2e_registry/app_monitoring_routes.py`. Registration
stays between the existing UI and administration routes. Both credential
domains, route names, query names, default ranges and dictionary response
models remain unchanged. `range_label` is an internal Python name; the HTTP
query parameter remains `range`.

`app_dashboard_window.py` preserves response-only range filtering: inclusive
endpoints, malformed event omission, undated dispatch retention, row identity
and the previous nonfinite comparison behavior. It does not mutate incident
state or establish recovery. Series bounds share the same completion and
invalid-order check. Authentication still precedes cache observation; summary
database calls remain sequential before response construction. Observation
exceptions and cancellation propagate.

Evidence is retained under the existing local packet
`/mnt/pitchai-dev-data/artifacts/monitoring-dft-746-20261004/`:

- `app-monitoring-routes-compatibility.json`: 445 retained-parent comparisons,
  including exact OpenAPI and 15 isolated ASGI request outcomes. Database and
  monitoring inputs are substituted; lifecycle is not started. Outgoing
  network and child-process guards record zero attempts.
- `app-monitoring-routes-native-tests.log`: six focused cases exercise range
  filtering, shape fallback, nonfinite timestamps, authentication/observation
  order, cancellation and partial/invalid query bounds.
- `app-monitoring-routes-native-gates.log`: all nine scoped analyzers pass for
  both runtime modules, the test and its in-memory ASGI protocol harness. The
  repository anti-bypass scan still fails on 15 existing findings. Earlier
  fixtures incorrectly used a synchronous HTTPX context and expected 403
  rather than the existing 401. The strict HTTP-client finding led to a direct
  ASGI harness with no HTTPX constructor. All earlier failures are retained.

The native ASGI harness supplies one request body, captures response messages
and waits for response completion before signaling disconnect. It starts no
lifespan or listener. The final native working proof is separate from the
earlier HTTPX comparison and pretest snapshot; neither establishes live IO.

This is source/component evidence. PR204 remains subject to the required
Enforcement integrity and Quality ratchet checks. Producer installation,
checker/config/clock/reader/journal, accepted receiver/off-host observation,
throughput, retained copies and finite Infrastructure admission remain open.
Actual selection still requires the original 300-second window after both
writer adoption and natural worker drain, followed by the next successful
selected-source read. No live receiver, event or Telegram send was performed.
