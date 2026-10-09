# Standalone sandbox HOME ownership

The native runner now supplies a private child HOME, but direct sandbox CLI
invocation could still default missing HOME to shared `/tmp`. PR204 replaces
that fallback with an owned temporary directory for the invocation. An existing
HOME, including an empty value, remains unchanged. The missing-HOME environment
entry and only the allocated directory are removed after completion, an ordinary
exception, cancellation or interrupt. This is an intentional isolation change;
the prior missing-HOME fallback persisted its environment entry after return.

`e2e_sandbox/python_home.py` owns this synchronous CLI resource boundary.
`playwright_python.main` retains the existing AnyIO asyncio backend, arguments,
normal exit and interrupt exit130. Cleanup does not claim to terminate arbitrary
submitted threads or processes; browser/runtime behavior is unchanged by this
increment. It does not admit a live browser or deployment.

Four isolated tests cover configured/empty HOME, private permission bits and
owned-file cleanup after failure, real asyncio-backed CLI completion/cancellation,
and the existing interrupt mapping. CLI bodies are synthetic; no browser or
child process is launched. Raw passing and failed gate iterations are retained
under `/mnt/pitchai-dev-data/artifacts/monitoring-dft-746-20261004/sandbox-home-*`.
The three affected Python files pass the nine scoped gates; the aggregate
anti-bypass check continues to report18 repository findings.
