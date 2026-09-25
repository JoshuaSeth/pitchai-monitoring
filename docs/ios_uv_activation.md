# Apple quality configuration and activation

Run `uv run check` from the repository root. It calls the existing `make check`
Apple aggregate, then retains the previous Python aggregate where one existed.
Both return statuses are preserved; a failed Apple check cannot become success
because the Python check passed. No native/static gate is reimplemented here.

`uv run check --list` lists the configured Apple gates. `uv run check --probe`
runs the deliberate failing-fixture harness through `make check-probe`.
Those diagnostics do not claim that application lint/build/tests pass.

Installation acceptance is configuration correctness, command wiring and
failure propagation. Existing application debt remains visible and does not
prevent installing the checker. Required repository protections still apply.
Native build/test results require a real Mac/Xcode; Linux activation is not
simulator validation. No deployment, signing or artifact publication is part
of this entrypoint.

## Checker compatibility (25 September 2026)

The native runner now uses the modular implementation already maintained in
Aviv's `ios_quality` package, under `scripts/ios_quality` here. The 15-gate
registry, native configuration, strict compiler flags and deliberate failing
fixtures remain active. The uv adapter still calls `make check` followed by
the locked Python aggregate and returns failure from either aggregate.

The copied checker passes the repository's unchanged scoped Ruff,
BasedPyright, Pylint, Semgrep and architecture rules. Installation remains
subject to the enforced full quality ratchet: its portable manifest freezes
root `pyproject.toml` and `uv.lock`, while its workflow contract also rejects
the artifact-publication guard. Those enforcement contracts are not changed
or bypassed by this PR. Application findings remain separate product debt.
