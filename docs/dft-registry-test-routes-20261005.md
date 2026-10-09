# Registry test-management HTTP boundaries

PR204 continues the existing 746 source repair. `app_test_creation.py` owns
creation admission; `app_test_routes.py` owns tenant lookup, patch, disable,
enable and scheduling. The application installs their routers at the original
positions around source-upload routes. URL/StepFlow validation order, explicit
null patches, tenant arguments, write/read ordering and exception/cancellation
behavior remain unchanged. Seven handler descriptions are new; other OpenAPI
fields and the ordered route table match parent `bc30631`.

Evidence is retained at
`/mnt/pitchai-dev-data/artifacts/monitoring-dft-746-20261004/`:
`app-test-routes-tests-final.log` records six focused native-ASGI tests;
`app-test-routes-compatibility.json` records 79 parent comparisons including
remaining-main AST, OpenAPI, admission, missing writes and cancellation.
`app-test-routes-existing-tests.log` and its receipt record the three existing
isolated SQLite/ASGI policy cases. Outbound guards recorded zero attempts.
Owned temporary fixtures were removed. The final scoped gate log passes all
nine file-scoped analyzers; the repository anti-bypass check retains 15 findings.
Initial fixture annotation/style failures remain in the earlier gate log.

The first six-test run preceded the working snapshot because its attempted
snapshot command used an unavailable `python` executable. The corrected
snapshot precedes the parent comparison and existing-policy proof; final test
fixture annotations were corrected afterward and covered by the final focused
run. Runtime bytes did not change in that correction. This is source/component
evidence, with substituted operations or temporary SQLite, no browser execution
or delivery. Required Quality ratchet, remaining source repairs and the DFT
runtime bindings/finite Infrastructure admission remain separate dependencies.
