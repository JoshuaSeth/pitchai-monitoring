# Registry runner HTTP and post-commit notifications

The existing PR204 repair separates two runner routes, their notification
orchestration and the native HTTPX gateway. Completion still validates status,
commits through the unchanged database function, opens the original client,
processes failure/optional dispatch, then independently reads recovery config.
Settings remain late-bound. Ordinary errors and cancellation propagate through
the existing client exit; a transaction failure never opens that client.
This does not add a notification route or change the completion integrator's
transaction hooks. The gateway retains the registry user agent and HTTPX defaults.

Evidence under `/mnt/pitchai-dev-data/artifacts/monitoring-dft-746-20261004/`:
`app-runner-routes-compatibility.json` records 74 parent comparisons against
`fe2abe5`: remaining-main AST, route order, OpenAPI apart from two descriptions,
HTTP responses, exact unsent message/context captures, operation order,
late-bound settings and error/cancellation classes/messages. The database and
transport are substituted, lifespan is not started and outgoing attempts are zero.
`app-runner-routes-tests-final.log` records six focused cases in 0.694 seconds.
The final receipt identifies pretest bytes and subsequent fixture typing and
formatting corrections; these are working-increment proofs, not post-commit runs.
Initial static failures remain retained. The canonical scoped log is
`app-runner-routes-gates-accepted.log`; whole-repository debt remains separate.

This source increment proves no live delivery, DFT allocation, installed checker
or host outage observation. The remaining registry UI/bootstrap, whole-candidate
ratchet and existing runtime admission work remain part of the same objective.
