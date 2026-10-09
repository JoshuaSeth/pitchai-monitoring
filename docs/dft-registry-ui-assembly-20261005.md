# Registry UI and application assembly

PR204 now assembles the existing routes in a small typed `app.py`. Session,
tenant read/write and presentation modules preserve their original scope.
Startup still runs schema admission before independent best-effort directory
attempts and logged quarantine. Its handler is registered on the same router
startup list through the supported API. Stateless health/root callbacks remain
asynchronous, preserving event-loop execution rather than introducing worker
thread dispatch. Unused imports and the unreferenced duplicate digest helper
were removed; documented compatibility exports remain.

Evidence is under `/mnt/pitchai-dev-data/artifacts/monitoring-dft-746-20261004/`.
`app-ui-assembly-compatibility-accepted.log` and its JSON result compare the
retained `6fcf4ac` parent with the final application: 75 cases cover ordered
routes, schemas apart from new descriptions, exact responses/cookies,
tenant-scoped DB calls, display fallbacks, source preview and startup failures.
Template context, filesystem operations and database calls are substituted;
network/child attempts are zero. The seven focused tests additionally exercise
native templates and ASGI. The combined registry suite records 46 passing tests
in `app-ui-assembly-integration-final.log`, including the earlier API/upload/
runner boundaries. Final-pretest snapshots pin the eight Python files.

`app-ui-assembly-gates-final.log` records passing analyzers for all eight files,
including the full changed `app.py`; the aggregate still fails 15 existing
repository anti-bypass findings. Initial static failures, earlier seven-test
and 26-test runs and earlier 73-case comparisons remain separate retained
receipts. No post-commit campaign or whole-repository gate pass is implied.

The remaining ratchet fingerprints and affected legacy tests stay in this
existing source allocation. Producer files, completion hooks, required rules,
baselines and runtime controls are unchanged. Actual checker/reader/journal,
internal/off-host receiver, throughput/copy lineage and coordinated adoption
remain open; source tests are not delivery or installed-control evidence.
