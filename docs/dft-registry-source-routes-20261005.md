# Registry source-file and upload boundaries

The existing PR204 repair moves six UI/API upload, download and replacement
handlers out of `app.py`. `app_source_files.py` owns filename checks, resolved
path confinement, file operations, definition decoding and the UI's explicit
ordinary-failure result. `app_upload_values.py` binds existing multipart fields
through native FastAPI dataclasses; it adds no input constraints. API creation,
UI creation and replacement retain their distinct admission/error order. The
UI still renders ordinary write/insert failures; cancellation propagates.
Replacement writes the new file, attempts existing best-effort old-file
cleanup, then updates the database. A missing final database row does not
retroactively undo those existing file effects.

Evidence under `/mnt/pitchai-dev-data/artifacts/monitoring-dft-746-20261004/`:
`app-source-routes-compatibility.json` records 70 parent comparisons against
`8b200f3`, including the remaining-main AST, ordered routes, OpenAPI, exact
responses, database call order/arguments and temporary source bytes. Six route
descriptions differ; the remaining schema is identical. This uses native ASGI
and multipart parsing with a substituted database, no lifespan and zero guarded
network/child attempts. All owned temporary source trees were removed.

`app-source-routes-tests-complete.log` records seven focused tests after moving
the unchanged UI failure context to the IO module. The earlier 70-case comparison
preceded that import-only move; it is not represented as a later campaign.
The pretest snapshot and final receipt identify runtime/test annotation and
fixture-lifecycle corrections. The initial dataclass postponed-annotation
OpenAPI failure and static failures are retained. Runtime form annotations now
resolve concretely; the IO module retains postponed type-only annotations.
`app-source-routes-gates-accepted.log` contains the final nine-file scoped
checks; repository anti-bypass findings remain separate from scoped results.

The remaining application bootstrap/UI/runner and whole-candidate ratchet work
continues in the same branch. No registry completion hook, producer code,
runtime receiver, DFT journal allocation, deployment or delivery is changed by
this increment. Existing runtime admission, original 300-second adoption/drain
coverage and the next selected read remain separate acceptance conditions.
