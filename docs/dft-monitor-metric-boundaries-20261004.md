# PR204 browser metric boundaries

The authorized Web Vitals and synthetic transaction participants now have
explicit JSON, step, artifact and resource boundaries in the existing PR204
candidate. No live browser or metric probe was run.

`metrics_web_vitals.py` owns admitted context/page lifetime and ordinary-error
conversion. `vitals_scripts.py` retains the two original JavaScript strings.
The public result fields, viewport, navigation policy, observer/click/stop
tolerance, non-dictionary fallback and cancellation boundaries remain.

`metrics_synthetic.py` owns sequential transactions, skip rules, timing and
resource cleanup. `synthetic_steps.py` implements the existing action set and
60-step bound; `synthetic_values.py` retains text/environment interpretation;
`synthetic_artifacts.py` owns optional screenshots, trace export and bounded
log writes. Playwright errors still include title; ordinary errors do not.
An export failure still attempts an ordinary trace stop. An ordinary cleanup
failure remains tolerated; cancellation during page cleanup still prevents
the subsequent context cleanup, matching the prior boundary.

The public synthetic callable retains four required keyword arguments and
the same three optional keywords/defaults through `Unpack[SyntheticOptions]`.
Unknown keywords are rejected before browser IO. The inspectable Python
signature now groups optional keywords; it is not claimed byte-identical to
the original signature. Playwright still validates selector-state strings.
No new successful fallback replaces an existing failure.

Evidence under `/mnt/pitchai-dev-data/artifacts/monitoring-dft-746-20261004/`:

- `web-vitals-tests-final.log`: eight tests, including four existing browser
  phase tests, pass in 0.066s.
- `web-vitals-compatibility-corrected.log`: 264 retained-parent comparisons of
  result fields and browser call order, including cancellation/partial
  admission. The initial runner import failure remains in its original log.
- `synthetic-tests-1.log`: twenty affected metric/phase/message tests pass in
  0.081s. A later test-only empty-dictionary assertion correction is separately
  snapshotted and covered by five tests in `synthetic-tests-final.log` (0.021s).
- `synthetic-compatibility-1.log`: 260 retained-parent comparisons of results,
  call order and actual temporary optional-log bytes; no socket/child attempts.
  The temporary directory was removed. This proof precedes the runtime
  docstring-only correction and later test addition, not a post-commit run.
- Both final scoped gate logs pass the nine selected-file gates. The full
  anti-bypass gate remains failed on eighteen existing suppression sites.
  No rule, baseline or exclusion was changed.

Parent source, comparison tools, pretest snapshots and all initial gate logs
are retained. These proofs use fake browser objects and do not prove native
browser operation, installed checker/config/clock/reader/journal bindings,
internal or off-host delivery, real throughput, retained-copy disposition or
the actual 300-second cutover. Required full-candidate Quality ratchet repair
and finite Infrastructure admission remain outstanding on the existing route.
