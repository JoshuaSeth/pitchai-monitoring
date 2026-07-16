# Python quality gate

`uv run check` is the required fail-closed static gate for the tracked runtime
Python under `domain_checks`, `e2e_registry`, `e2e_runner`, and `e2e_sandbox`. Use
`uv run check --list` to inspect the exact command for every gate.

The portable PitchAI baseline runs five custom preference/architecture
checkers followed by Ruff `ALL`, BasedPyright strict mode with warning failure,
Pylint with a 10.00 score floor, and Semgrep ERROR rules with `--error`. The
aggregate runs every gate, reports every failure, and exits nonzero when any
gate fails. Existing violations are debt to fix, never a reason to disable,
exclude, downgrade, or bypass a gate.

```bash
uv sync --frozen
uv run check --list
uv run check
```

Synthetic failure probes must run only in a fresh detached or otherwise
isolated worktree at the exact audited commit. Add the temporary probe under a
configured runtime root, restore the exact commit and tree, prove the aggregate
returns to its baseline, prove the worktree clean, and remove it after evidence
collection. Never probe a production checkout or a checkout imported by a live
service.

The GitHub workflow has read-only repository permission and runs only the
locked quality command on GitHub-hosted infrastructure. It contains no secret,
environment, deploy, release, publish, SSH, database, or service-control step.

The production deployment workflow ignores every quality-only path listed by
the strict workflow. A quality-gate-only merge must therefore run the strict
workflow without running the SSH/Docker production deployment. Any change that
also touches runtime code remains deploy-triggering and follows the normal
production release path.
