# Registry dashboard calculation repair

This PR204 increment carries the typed snapshot boundary through the existing
dashboard calculations. `e2e_registry.monitor_dashboard` retains its public
summary builder and imported compatibility names. The real
`monitoring_v2.registry_runtime.legacy_dashboard` module reference and
`monitoring_v2.summary` builder hook remain connected.

The new modules separate retained-value access (`dashboard_records`), primary
and subcheck history (`dashboard_domain_metrics`, `dashboard_domains`), global
signals (`dashboard_signals`), registry results (`dashboard_e2e`), freshness and
rolling-day classification (`dashboard_health`), display incidents
(`dashboard_incidents`) and time-series selection (`dashboard_timeseries`).
All modules remain within the unchanged canonical strict source discovery.

Configured inventory remains authoritative over retired history. Primary,
API and synthetic failure sources retain their individual observations and
effective timestamps. Disabled, expected-down, unknown and alertable-down
counts remain distinct. Display incident descriptions do not emit events,
acknowledge incidents or establish any notification delivery. Signal display
annotations are added to copies. Series keep inclusive original timestamps,
identical legitimate rows, sampling stride and final-row identity.

The typed boundary accepts retained JSON and YAML values, including date
scalars. Explicit mapping/list fallbacks remain where the original code had
them; unguarded malformed mappings continue to fail. No broader promise is
made for arbitrary user-defined conversion objects or concurrent caller
mutation during summary assembly.

Protected evidence is under
`/mnt/pitchai-dev-data/artifacts/monitoring-dft-746-20261004/`:

- `dashboard-parent-e2d79f0.py` is the immutable parent source.
- `dashboard-calculation-final-pretest/` binds all eleven Python files before
  the final test and comparison runs. A subsequent docstring-only correction
  removes a stale exception declaration; executable ASTs remain unchanged.
- `dashboard-calculation-tests-final.log` records twelve focused/input tests
  passing in 0.005 seconds; `dashboard-calculation-existing-tests.log` records
  the three existing summary tests passing and retains the analyzer pytest
  warning about the unrelated `asyncio_mode` option.
- `dashboard_calculation_compatibility.py` and the final raw log record 1,301
  parent comparisons in 1.199 seconds. They include 432 complete summaries,
  malformed-input exception classes/messages, series and classification
  boundaries, and four actual monitoring-v2 summary calls with synthetic data
  and a substituted database snapshot. There were zero guarded network/child
  attempts and no input mutations. These runs do not start ASGI, a real
  browser, the deployed DFT checker or a receiver.
- Initial failed static passes and earlier comparison logs remain retained.
  The final scoped report is separate from the full candidate report.

The required Quality ratchet at parent `e2d79f0` remains failed. Its complete
frozen report has 6,346 diagnostic occurrences; the typed loader exposed
338 new dashboard typing fingerprints before this calculation repair.
The source increment is not a waiver, merge approval or installed DFT proof.
The existing app/test/dependency diagnostics remain within their allocated
repair and review process; Full zero-debt stays visible separate debt.

Producer source, private runtime allocations, checker/config/clock/reader,
retained schema2 journal, accepted internal receiver and independent off-host
observer, throughput and shared/historical-copy disposition remain separate
admission dependencies. The full original 300 seconds must follow both writer
adoption and natural old-worker drain; complete catch-up, durable selection
and the next successful selected read remain required. Owner acknowledgement,
fresh health and original expiry deadlines are unchanged. No runtime action
or outgoing delivery is performed by this increment.
