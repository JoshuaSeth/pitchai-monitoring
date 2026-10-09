# Runner boundaries for PR204

The registry runner now reuses the monitored Chromium argument set while
retaining its distinct unknown-shared-memory policy. The previous entry point
mixed configuration, transport, subprocess execution, job classification and
browser retry ownership. Those responsibilities now have explicit modules;
every module remains in the frozen canonical analysis scope.

`main.py` retains the native CLI, HTTP/Playwright lifetime and installed
`_claim_jobs` / `_run_one_job` hooks used by `health_main`. `cycle.py` owns
sequential polling and smoke-mode error boundaries; `browser.py` owns the
existing browser retry/backoff. `transport.py` owns native client defaults,
claim and completion requests. `job.py`, `job_result.py` and `code_process.py`
separate request validation, partial results and submitted-test execution.
`config.py` retains all eight constructor fields, environment normalization,
poll/concurrency bounds and immutable attribute access. The configuration is
now a named tuple: dataclass introspection and dataclass-specific equality are
not preserved APIs. No repository caller uses those operations.

The CLI uses AnyIO's asyncio backend rather than constructing its own event
loop. Seven parent/candidate bootstrap comparisons cover ordinary completion,
empty claim, claim/job/close failures, launch failure and cancellation. They
use real asyncio/AnyIO runners with synthetic IO; they do not establish actual
signal handling, browser operation or deployed process cleanup.

The subprocess HOME is intentionally changed from a shared temporary root to
an owned private temporary directory for each submitted code invocation. The
environment allowlist, command arguments and artifacts destination remain.
The directory is removed when that invocation exits. The isolated test checks
its private permissions during mocked communication and removal afterward.
This does not strengthen the old process supervision contract: ordinary
communication failures still attempt kill without proving child reaping,
and cancellation propagates without a new child-termination guarantee.

## Retained proof

Private evidence root:
`/mnt/pitchai-dev-data/artifacts/monitoring-dft-746-20261004/`.

- `runner_compatibility.py` / `runner-compatibility-final.log`: exact parent
  `b7827af` comparison, 96 job cases, eight native polling scenarios, ten
  Chromium admission cases, 60 configuration cases and seven CLI bootstraps.
  All results/call ordering match within the stated contracts. Outgoing and
  child-process guards report zero attempts; temporary fixtures are removed.
- `runner-tests-final.log`: ten focused tests, including the actual native
  `run_once` path consuming the existing heartbeat hooks. Browser/client and
  child execution are synthetic. `runner-home-module-final.log` rechecks the
  six job tests after the final asynchronous filesystem assertion change.
- `runner-gates-final.log`: all nine scoped analysis gates pass for ten
  Python files. The separate repository-wide anti-bypass check still fails
  on 18 existing suppressions. No baseline, analyzer, rule or discovery change.
- `runner-pretest/manifest.json` records the test-start files. Runtime bytes
  match the final source; the final test-only filesystem assertion change is
  retained separately. Earlier failed gate logs and the keyword-only fixture
  error remain. `runner-home-final.log` is a failed unittest selector before
  execution, superseded by the explicit module run, not a passing proof.

These results do not satisfy the whole PR ratchet or any runtime binding.
Registry app/dashboard and other candidate findings remain. Producer
`ee5796f` / runtime `10cc` is unchanged. The actual checker/config/clock,
reader, schema2 journal, accepted internal receiver, independent off-host
observer, throughput, copy disposition and finite Infrastructure624 admission
remain separate obligations. Keep the original 300 seconds after both writer
adoption and natural old-worker drain, durable selection followed by the next
successful selected read, and explicit acknowledgement plus fresh health.
No deployment, live request, synthetic incident or outgoing delivery was made.
