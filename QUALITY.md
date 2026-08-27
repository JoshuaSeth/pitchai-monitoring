# Python Quality Gate

From the repository root, run the complete fail-closed Python gate with:

```sh
uv run check
```

The root project is only an entrypoint for the locked `quality` package. CI
uses the equivalent explicit command:

```sh
uv run --project quality --python 3.12.12 --frozen check
```

The aggregate runs the anti-bypass policy, all five PitchAI Python preference
checkers, Ruff with every rule selected, BasedPyright in strict mode with fatal
warnings, full Pylint with a score floor of 10 and a 250-line module ceiling,
and Semgrep `ERROR` rules. It checks every repository Python and stub file,
including tests and tools. Only generated caches, virtual environments, build
outputs, and other non-source directories are omitted from discovery.

The read-only GitHub Actions workflow runs for every pull request and every
push branch. It intentionally has no branch-name filter, so repositories whose
default branch is `main`, `master`, `staging`, or another project-specific name
cannot silently skip the gate.

## Immediate ratchet

The workflow separates the still-red full gate from the merge-blocking
`Quality ratchet` job. The ratchet runs the same ten gates and compares their
machine-readable diagnostics with
`.github/quality-baselines/python-strict-activation-main.json`. It fails when a gate
has a new fingerprint, a higher fingerprint multiplicity, a higher aggregate
violation count, or any violation attached to a Python file changed by the
candidate. Moving unchanged code between paths or line numbers does not create
a new identity: ordinary fingerprints use the gate, rule, normalized message,
and source-line digest, while locations remain separate evidence. Pylint's
duplicate-code excerpts are nondeterministic even with a single worker, so
those fingerprints use the complete sorted participant-module set and record
each participant's owned source location. The raw Pylint finding count remains
the aggregate ratchet counter.

The main activation snapshot embeds its authoritative source commit and tree.
Its exact SHA-256 digest is pinned in the read-only workflow and normalized by
the anti-bypass verifier, so the trust anchor can be checked without weakening
the workflow-semantics lock.
`quality/baselines/python-strict-historical-88722fb.json` separately preserves
the requested July evidence at commit
`88722fb26fce1939d2b71c883ca02cae79998309`; it is not accepted as the active
enforcement baseline.

The ratchet also verifies its comparison logic before each run and uploads the
complete candidate report even when the comparison fails. Branch protection
must require `Quality ratchet`; the full gate stays visible and becomes the
release gate only after every counter reaches zero.

The read-only GitHub workflow is the external CI trust root. Before installing
or executing the quality project, it compares the anti-bypass verifier with an
exact SHA-256 digest committed in the workflow and fails loudly on a mismatch.
The verifier hardcodes the exact digest of the required-file manifest. The
manifest, in turn, hashes both lockfiles, the root command contract, both
baseline artifacts, the ratchet and its tests, the runner, all five preference
checkers, every semantic helper, the complete-source resolver,
`strict_policy.py`, tool configuration, Semgrep policy, and this documentation.
The workflow, verifier, and manifest are intentionally excluded from the
manifest to keep the digest chain acyclic.

The verifier rejects missing or unexpected portable files, altered manifest
membership, and every manifested-file hash mismatch. It also validates the
workflow's all-PR/all-push triggers, read-only permissions, trust-anchor step,
frozen install and aggregate commands, full-SHA action pins, and absence of
`continue-on-error: true`. The unavoidable boundary is a coordinated edit to
the external workflow trust root and the chain it anchors: that change must be
identified and judged in code review. Repository-local files cannot
self-authenticate such a coordinated change, this design makes no claim of
mutually authenticated local files, and it uses no operational signing secret.

Python is pinned to 3.12.12. Ruff always receives
`--config quality/pyproject.toml`, BasedPyright receives
`--project quality/pyproject.toml`, Pylint receives
`--rcfile quality/pyproject.toml` and one deterministic worker, and Semgrep
receives the absolute strict config path. Installation and execution both select the frozen `quality`
project. Consequently root dependency files cannot change the quality
environment, and root tool configs cannot weaken these invocations. The
anti-bypass gate also rejects alternate root tool configs and any other GitHub
Actions workflow that invokes the quality project or a direct checker.
Across every workflow, non-local `uses:` references must be pinned to a full
40-hex commit SHA and `continue-on-error` is forbidden. Mutable third-party
action tags and ignored workflow failures are reported as anti-bypass debt;
deployment workflows receive no exemption.

A nonzero result is an enforcement result, not permission to narrow coverage.
Repair violations with real dependencies or stubs and explicit boundary
architecture. Do not add inline suppressions, diagnostic downgrades, source
exclusions, ignored failures, or checker wrappers that hide a tool result.
