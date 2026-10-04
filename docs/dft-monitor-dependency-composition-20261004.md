# PR204 frozen dependency composition

The PR204 analyzer environment now resolves the registry, DNS, template and
metric dependencies at the versions already in `requirements.txt`: cbor2 6.1.4,
cryptography 50.0.0, dnspython 2.6.1, FastAPI 0.115.6, httpx 0.27.2, Jinja2 3.1.5,
python-multipart 0.0.12 and tzdata 2025.3. The earlier PyYAML 6.0.2 and Playwright
1.50.0 pins remain. Pytest 9.1.1 composes the exact dependency introduced by
registry-completion PR214 at c8d9df4050972532f2cf8fd9d025329e716d9073. There remains
one `extraPaths = [".."]` source-root setting. No PR214 completion module or
activation change is imported here; its owner retains that source.

Both locks were resolved from this project configuration. Analyzer versions,
rules, source discovery, baselines, manifest membership, workflow semantics and
root project configuration are unchanged. The three changed manifested-file
hashes propagate through the existing manifest, verifier digest and workflow
trust anchor. This is a further coordinated dependency change for ordinary
independent review, beyond the previously reviewed dependency bytes.

Native Uvicorn remains 0.30.6 in application requirements. Adding that exact pin
to the analyzer environment does not resolve: Semgrep 1.166.0 depends on MCP
1.23.3, which requires Uvicorn >=0.31.1. The analyzer's existing transitive
Uvicorn 0.51.0 remains; this environment is not claimed to reproduce the native
server runtime. No native requirement or analyzer version was changed to hide
that incompatibility. Similarly, Pytest 9.1.1 is the composed analyzer/test-tool
pin, not a replacement of `requirements-dev.txt`'s native test environment.

Retained proof is under
`/mnt/pitchai-dev-data/artifacts/monitoring-dft-746-20261004/dependency-composition/`:

- `chain-proof.json`: exact installed package graph and six changed-chain byte
  mutations refused in a disposable source copy, with restored-chain acceptance
  and copy removal. Unchanged semantic tamper cases were not repeated.
- `ratchet-contracts.log`: eight existing comparison contracts passed.
- `disablement-tests.log`: three final parser compatibility tests passed;
  Pytest also reports the existing unknown `asyncio_mode` setting because this
  environment does not install the native pytest-asyncio plugin.
- `anti-bypass.log`: the full repository-wide result remains separate from
  chain integrity and retains unrelated suppression findings.

Staging a5d1c27 was merged without conflict; it adds only the daily-review
document. Source repair, full candidate analysis and required hosted Quality
ratchet acceptance remain outstanding. No runtime, receiver, event, deployment
or DFT commissioning acceptance follows from dependency resolution.
