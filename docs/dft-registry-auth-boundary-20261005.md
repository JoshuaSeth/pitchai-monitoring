# Registry authentication boundary in PR204

The authentication module now types the native FastAPI application-state read
and shares the existing bearer and role-token procedures. The same `Depends`
default resolves current settings. Missing/invalid settings retain the existing
`RuntimeError`; missing bearer precedes configuration and database access.
Tenant lookup remains hash-only. Admin and runner tokens remain independent,
with the original constant-time comparison and 401/403/503 outcomes.

Against parent `2adef5ed984faf889dcfd8c446dbc9e4da34e8ba`, 154 isolated
comparisons cover token normalization, role admission, omitted dependency
arguments, tenant lookup failures/cancellation, invalid and replaced settings,
OpenAPI and 12 native in-memory ASGI requests. Both sides use substituted tenant
lookup and runner claim results; no lifespan or real database starts. The final
comparison records zero external attempts. Five focused tests pass in 2.05s.

Initial evidence remains separate: four tests passed and one new native fixture
expected the wrong body-validation result. The first comparison reached the
guarded runner database boundary because the fixture lacked a claim substitute;
the guard refused it. Both fixture corrections are retained with the failed
logs. The final tests and comparisons use the snapshotted source bytes.

Both affected files pass their scoped architecture, Ruff, BasedPyright, Pylint
and Semgrep checks. Repository anti-bypass still fails with 15 existing
findings, and required whole-candidate Quality ratchet acceptance remains open.
The pytest log retains the existing unknown `asyncio_mode` warning.

Raw evidence, comparison tool and final pretest manifest are under
`/mnt/pitchai-dev-data/artifacts/monitoring-dft-746-20261004/`, using the
`auth-` prefix and `verify_auth_compatibility.py`.

This source change does not change credentials, authorization policy, runtime
configuration or DFT delivery bindings. All existing cutover, acknowledgement,
copy-lineage and finite Infrastructure admission requirements remain open.
