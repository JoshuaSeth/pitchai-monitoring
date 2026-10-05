# Registry application boundaries for PR204

This increment continues the existing746/4e2c5d80 source repair from
`21f7356ff5ebd098720635034f5d5657aa465b7d`. It does not integrate PR214's
completion modules, change the frozen dependency graph, or admit runtime work.

`app_inputs.py` preserves identity validation, test-kind aliases and upload
filenames. `app_host_policy.py` owns the existing strict URL policy and sequential
startup quarantine. Numeric reserved addresses use the existing `ipaddress`
classification; name and suffix admission remains separate and performs no DNS.
`app_access.py` keeps tenant-cookie authentication distinct from dashboard SSO
and internal bearer authentication. `app_context.py` reads the current settings
and template renderer from application state, and retains the five-second cache
with both source mtimes, original age and unavailable-state evidence.

The real `create_app` factory calls those boundaries. Ten former closure helpers
are removed; 66 state reads and 21 call sites are explicitly accounted for. Its
remaining executable AST equals the parent after those substitutions, three
context initializers and two error-translation changes. Invalid-until translation
now occurs in the actual API/UI handlers: the API retains HTTP400 and
`invalid_until: <original parser error>`, while the UI retains its redirect. The
private `_parse_until` wrapper is removed; the shared parser itself is unchanged.
Other extracted module-level helper aliases remain available from `app.py`.

Seven focused tests pass, followed by the single cache test after correcting its
static description of mutable application state. The retained comparison runner
passes445 parent/candidate cases:142 identities,13 aliases,22 filenames,95 hosts,
9 hostname parses,96 admissions,12 replaced-settings cases,40 cache cases, one
complete OpenAPI comparison and15 real in-process ASGI requests. Database and
snapshot functions are substituted for that runner; lifecycle is not started.
All return/error comparisons match. The first runner attempt failed at the
database guard because the authentication module retained an imported function;
the corrected runner substitutes that exact binding. No database was opened by
the failed attempt.

Three existing base-URL policy cases also pass with an isolated real SQLite
database and actual ASGI startup/API calls. Uploaded code is fixture data and is
never executed. Network and child-process guards report zero attempts. The owned
temporary fixture directory is removed. Existing pytest configuration and
FastAPI startup-deprecation warnings remain in the raw output.

All five new Python files pass the nine scoped gates. The global anti-bypass gate
still fails with18 retained findings. The whole app remains red:167 Ruff,
140 typing errors, Pylint8.96 and one Semgrep finding, plus vague-signature debt.
These results do not establish required Quality ratchet success or readiness to
merge. The prior21f7356 hosted Integrity checks pass and both Quality ratchet
checks fail; Full zero-debt remains visible but is not a separate required branch
check. The current increment must retain its own source and gate evidence.

Protected proof lives in
`/mnt/pitchai-dev-data/artifacts/monitoring-dft-746-20261004/` under
`app-boundaries-*`, `app_boundary_compatibility.py`,
`app_boundary_ast_check.py` and `app_boundary_existing_tests.py`. Initial failed
gates, pretest snapshots, the corrected test and the final logs remain separate.
The existing quality environment is retained for ongoing repair; no new
validation environment was created.

Producer ee5796f/runtime10cc, reader/checker/config/clock/schema2 journal,
accepted internal/off-host receiver, throughput and copy disposition, and a
finite624 admission interval remain separate dependencies. Preserve300 original
seconds after both writer adoption and natural old-worker drain, complete
catch-up, durable selection then the next successful selected read, and matching
owner acknowledgement plus fresh checker/access health. No runtime install,
live browser, delivery, acknowledgement, expiry, reload or human-stop change is
performed by this source increment.
