# API contract boundaries in PR204

The frozen candidate at `e0c339716257f60540830c33e93bb95df73268f5`
identified a duplicate between `metrics_api_contract.py` and
`synthetic_values.py`. API checks now use the existing synthetic placeholder
implementation. The uppercase grammar, missing-variable error and refusal to
include substituted values in that error are unchanged.

The public API result and sequential entrypoint remain in
`domain_checks/metrics_api_contract.py`. `api_contract_request.py` owns the
existing preparation order; `api_contract_values.py` owns JSON traversal and
bounded validation details; `api_contract_observation.py` owns request timing,
validation precedence and ordinary-error handling. The original private helper
names remain importable aliases. All modules remain in canonical strict scope.

URL/body placeholder and invalid status-conversion failures still occur before
observation. Header substitution and request failures still become failed
results. JSON parse failure retains request elapsed time; request/evaluation
failure samples failure time. Cancellation and other `BaseException` subclasses
propagate. Status, content type, required paths, equality and elapsed-limit
precedence, including the 50-entry evaluation and 25-entry detail limits, remain.
This is compatibility work; it does not add a stronger recovery guarantee.

Protected local proof is under
`/mnt/pitchai-dev-data/artifacts/monitoring-dft-746-20261004/`:

- `api-contract-compatibility.json` and its retained verifier: 558 parent
  comparisons, including actual HTTPX requests through only `MockTransport`,
  helper behavior, request bytes, error messages, clock calls and cancellation.
  Socket and child-process guards recorded zero external attempts.
- `api-contract-focused-final.log`: six new observation cases and four existing
  API phase cases pass. These use response/request doubles and local captures.
- `api-contract-focused-fixture-final.log`: all six new cases pass after only
  replacing a fixture comprehension with an explicit loop for strict policy.
- `api-contract-pretest`, `api-contract-final-pretest`, and
  `api-contract-test-final-before-test.py`: runtime bytes match the differential
  test-start snapshot. Later test-only fixture adjustments have their separate
  snapshots and focused results. Initial gate failures remain retained.
- `api-contract-gates-final.log`: all nine affected-file gates pass. The global
  anti-bypass gate still reports 15 pre-existing repository suppressions.

No source rule, baseline, exclusion or fingerprint accounting changed. A full
candidate and hosted required check remain separate from scoped passes. These
synthetic checks do not validate installed DFT paths, clocks, journal, receiver,
off-host observation, throughput, real 300-second coverage or delivery.
