# Python zero-debt release evidence

Status: in progress. This record is deliberately incomplete until the all-green
candidate has been released and observed for at least 24 hours.

## Release contract

The Python strict workflow is the release signal for every first-party Python
and stub file in this repository. Its current contract has ten fail-closed
gates: the repository-wide anti-bypass verifier, five architectural checkers,
Ruff, BasedPyright, Pylint, and Semgrep. The historical July workflow had nine
gates; its exact evidence is retained separately and is not used as the active
enforcement baseline.

Production deployment must be initiated by a successful `Python strict gate`
push run on `main`. The deployment workflow revalidates the upstream head SHA
against the current local and remote `main` tip, tests that exact SHA, and sends
the same SHA through the protected `production` environment. A failed or
non-push strict run cannot start a production deployment. The strict run also
records the original push event's `before` and `after` SHAs. Deployment obtains
that provenance from the exact triggering run and attempt, validates its closed
schema and identity, then evaluates exclusions from the last exact successful
production-release marker through the validated SHA. This deployed range spans
any canceled, superseded, or still-queued strict run between releases.

## Requirement evidence

| Requirement | Current evidence | Status |
| --- | --- | --- |
| Exact historical baseline | `quality/baselines/python-strict-historical-88722fb.json`, commit `88722fb26fce1939d2b71c883ca02cae79998309`, tree `d6a477462eab26803b0daad3e460f25d1be7eb8b`, run [29638594691](https://github.com/JoshuaSeth/pitchai-monitoring/actions/runs/29638594691) | Proved |
| Immediate ratchet | PR [#44](https://github.com/JoshuaSeth/pitchai-monitoring/pull/44), implementation `f6eaa2bfde433cdf16a6d699eea0ddd5ed94cd84`, staging merge `5c859f4a9f147f895f5849e71171be528565ca7f`, tree `cee0eed945d84e6d6b87b466fd5f88c8171c2547`, run [32895242021](https://github.com/JoshuaSeth/pitchai-monitoring/actions/runs/32895242021) | Proved |
| Zero debt | Exact final report and all-green workflow run | Pending |
| Behavior preservation | Current local full suite: 250 passed, one documented host-topology xfail, six opt-in live modules collection-skipped; focused domain, AFAS, E2E, event, state, and deployment coverage | Local proof green; exact image/workflow pending |
| Exact-green deployment coupling | `.github/workflows/ci-cd.yaml`, Actionlint validation, production-environment read-back, and live failed/green candidate evidence | Implemented; live proof pending |
| Ten isolated negative probes | One required-check failure and dormant deployment per gate, followed by exact restoration | Pending |
| Controlled release | Explicitly approved deployment of the all-green SHA | Pending |
| 24-hour production proof | Post-release source/runtime parity, fresh cycles, AFAS results, state/registry preservation, and coverage comparison | Pending |

## Before counts

| Gate | Historical `88722fb` | Activation `f4b541b` | Final candidate |
| --- | ---: | ---: | ---: |
| No validation bypasses | Not present | 23 | Pending |
| Nested event loops | 5 | 5 | Pending |
| Vague signatures | 178 | 330 | Pending |
| Single-use one-line functions | 5 | 11 | Pending |
| Pure wrapper functions | 1 | 2 | Pending |
| Dense inline comprehensions | 20 | 67 | Pending |
| Ruff | 1,560 | 4,040 | Pending |
| BasedPyright | 2,507 (2,504 errors, 3 warnings) | 7,422 (7,418 errors, 4 warnings) | Pending |
| Pylint | 357; score 9.48934344156773 | 1,440; score 8.773765659543109 | Pending |
| Semgrep | 226 | 319 | Pending |

The historical baseline covers 42 source files and uses the tool versions
recorded in the artifact. The activation baseline covers 107 files and locks
Python 3.12.12, Ruff 0.15.17, BasedPyright 1.39.8, Pylint 4.0.5, and Semgrep
1.166.0.

An independent baseline-integrity read-back resolved the historical commit to
the recorded tree, matched all 42 source paths, matched the 10 recorded policy
file digests against blobs from that commit, and confirmed the exact historical
tool versions in its committed lockfile.

## Phase-one enforcement proof

The first PR introduced a stable-fingerprint comparison against exact
activation commit `f4b541b13fa19551178855963fac089d4898a6ea`, tree
`1019fdd41f254f85e48abdb6b393a33b3164b125`. It rejects a new fingerprint,
higher fingerprint multiplicity, a higher per-gate aggregate, or any diagnostic
remaining in a changed Python file. The ratchet unit suite passed 8 of 8 tests.

Protected `staging` and `main` both require `Enforcement integrity` and
`Quality ratchet`, use strict up-to-date review, apply the rule to
administrators, and prohibit force pushes and branch deletion. The canonical
phase-one candidate artifact has SHA-256
`106910c7e34018bedc58d0cf86db05809f11aafe2d54328f9692a2bbf967e2cb`.
An independent activation-integrity read-back also matched its exact commit and
tree, all 107 source paths, six policy-file blobs, and locked tool versions.
The `main` protection read-back remained identical at `2026-08-26T01:03:18Z`.
GitHub read-back at `2026-08-26T02:42:30Z` again showed exact tips
`b27bdd17f9db6737e332305780ec3cc0baf84721` on `main` and
`5c859f4a9f147f895f5849e71171be528565ca7f` on `staging`; both protections
still required the two strict, app-bound contexts with administrator
enforcement, strict base freshness, and force-push/deletion denial.
As an interim fail-closed case, open PR
[#45](https://github.com/JoshuaSeth/pitchai-monitoring/pull/45) at exact head
`cf98683cde25b32132170216518f64c0eebaaecd` is `BLOCKED`: current production
`main` still supplies only the legacy failing `python-strict` job, so neither
new required context is present. This proves the configured protection blocks
the PR, but it is not counted as ratchet-execution proof; the final main
candidate carries the new workflow and must produce both exact required jobs.

A reversible downstream-style probe changed only a same-line comment in
`domain_checks/main.py`. It introduced no fingerprint or multiplicity change
and kept every aggregate equal to activation, but the ratchet still rejected
2,618 diagnostics in the changed file. The temporary worktree was removed.

An independent source-topology probe then found a complete-source bypass: a
tracked runtime package could be moved below excluded `build/`, with a tracked
package symlink left at its original import path. Python still executed the
package, while both aggregate discovery and ratchet profiling omitted the
tracked implementation. Enforcement now reads the Git index without a shell,
with ambient `GIT_*` variables removed, and fails closed on every tracked
symlink or tracked `.py`/`.pyi` file below an excluded directory. The durable
tests exercise the exact package-symlink case, a direct internal source
symlink, and the non-regression case for untracked generated Python. Both
discovery paths report all three violations in the compound probe. Independent
validation passed 11 of 11 ratchet tests, the five architectural checkers,
Ruff, BasedPyright with zero diagnostics, and Pylint at 10.00; all four touched
files remain at or below 250 lines. The disposable probe repositories were
removed.

## Downstream compatibility: PR #43

PR [#43](https://github.com/JoshuaSeth/pitchai-monitoring/pull/43), head
`b48648a6d672b6bdfdd31bd01397fc639bd79f4e`, is the concrete downstream
validation case. It necessarily changes `domain_checks/main.py` and
`domain_checks/metrics_api_contract.py`, both of which contain activation-era
debt. GitHub read-back confirmed the open head, its ten changed files, and its
failed pre-ratchet strict runs. The `2026-08-26T02:42:30Z` refresh found that
exact head still open and `BEHIND` protected staging, with both existing strict
checks failed as expected; no sync or exemption had occurred. A disposable
synthetic merge of protected
staging `5c859f4a9f147f895f5849e71171be528565ca7f` with that exact head produced
tree `16dd2a87617d3107ceac7059fe1f4b0f1a80e671`. The locked phase-one ratchet
rejected it with 3,944 failures, including 3,732 changed-file failures: 2,642
owned by `domain_checks/main.py` and 110 by
`domain_checks/metrics_api_contract.py`. The complete candidate report had
SHA-256 `d3f9128d4a06c47d2d080861231ab9a6628afe112e8977d66421ed435aeee0c7`.

| Gate | Activation | PR #43 synthetic merge | Delta |
| --- | ---: | ---: | ---: |
| No validation bypasses | 23 | 23 | 0 |
| Nested event loops | 5 | 5 | 0 |
| Vague signatures | 330 | 330 | 0 |
| Single-use one-line functions | 11 | 11 | 0 |
| Pure wrapper functions | 2 | 2 | 0 |
| Dense inline comprehensions | 67 | 69 | +2 |
| Ruff | 4,040 | 4,100 | +60 |
| BasedPyright | 7,422 | 7,554 | +132 |
| Pylint | 1,440 | 1,461 | +21 |
| Semgrep | 319 | 319 | 0 |

That branch receives no exemption. Before this zero-debt lane lands, the
changed-file-clean boundary is expected to reject it even after its newly
introduced fingerprints are removed. After this lane lands, PR #43 must be
synced by its owner to the new base, its branch-specific debt removed, and its
new exact head revalidated. The post-landing proof must record the landed base
SHA/tree and new PR head, show zero diagnostics in both named files in the
machine-readable candidate report, run both the complete locked `uv run check`
and the ratchet against the landed base, and link the resulting required GitHub
checks. Any intermediate failing head must have no production deployment. The
AFAS worktree is not modified by this lane. Passing that protocol demonstrates
that strict touched-file enforcement is compatible with real downstream work
once the repository has reached zero.

## Open Semgrep rule-governance decision

The locked policy is not presently satisfiable without disguising real
boundaries. `forbid-requests-outside-infra` flags every `requests`, `httpx`,
`aiohttp`, `urllib`, `urllib3`, and `socket` call and defines no positive shape
for an infrastructure gateway. Conversely, `py-try-except-outside-edges`
exempts whole framework callback classes instead of exact reviewed boundary
callables. A moving exact snapshot during the refactor reported 267 findings:
211 exception-boundary findings and 56 transport findings, with zero Semgrep
engine errors. These diagnostics remain visible; code is not being rewritten
through `contextlib.suppress`, dynamic calls, or alternate transport APIs just
to evade them.

A fresh canonical route-around probe made that transport defect executable:
`explicit_infrastructure_gateway.py` contained a function named
`fetch_from_explicit_infrastructure_gateway` whose only boundary operation was
`httpx.get`. The locked checker still emitted one blocking
`quality.forbid-requests-outside-infra` finding, parsed the complete file, and
failed. Thus neither an explicit gateway path nor an explicit gateway callable
can satisfy the current rule; reaching zero without a governed positive
contract would require disguising the call. The temporary probe was removed.

The latest complete integration snapshot at `2026-08-26T02:29:50Z`, still
before any governance change, scanned all 411 discovered Python targets with
locked Semgrep 1.166.0 and reported 249 blocking findings: 191 from
`py-try-except-outside-edges` and 58 from
`forbid-requests-outside-infra`, with zero engine errors. This is the honest
remaining policy boundary after the five architectural gates reached zero and
Ruff passed, BasedPyright reached zero errors and warnings, and Pylint scored
10.00. The anti-bypass gate reports only the deliberately stale portable
manifest and workflow trust anchors pending final source freeze. None of these
results is an allowance or a claimed all-gate green result.

The proposed governance change is an exact manifest-backed `@io_edge`
contract. The decorator must be a typed runtime marker; every decorated
callable and its declared capability must match a reviewed path/qualname entry;
aliases, rebinding, fake decorators, nested laundering, unused capabilities,
and unmanifested edges must fail the anti-bypass gate. Semgrep would then allow
exception handling and transport calls only inside those exact callables, while
removing the current broad framework exemptions. All source files remain in
scope and no path exclusion, suppression, threshold, or finding allowance is
introduced. No Semgrep policy edit will be made until that stricter contract is
explicitly approved.

A scratch probe against locked Semgrep 1.166.0 confirmed the syntactic half of
the design: direct `@io_edge(...)` functions were permitted, while an aliased
decorator and an undecorated business function each produced both expected
blocking findings. It also confirmed why the manifest-aware AST verifier is
mandatory: Semgrep's `pattern-not-inside` alone treats a nested function inside
a decorated function as exempt. The proposed verifier must attribute every
protected construct to its nearest callable and reject nested laundering,
aliases, rebinding, fake decorators, undeclared or unused capabilities, and any
path/qualname not present in the reviewed manifest.

### Governance scope preflight

A deterministic callable-level preflight over the current 411-file source
surface found that the visible 249 Semgrep diagnostics collapse to 214 exact
callable entries. It also proved that the current exception rule is incomplete:
the Python AST contains 215 `try` statements with exception handlers, while the
rule reports only 191. Twelve are intentionally hidden by the broad FastAPI
route exemptions. The other twelve are unintentionally missed because the
Semgrep shape does not match `try/except` statements that also contain `else`
or `finally`. Removing the broad exemptions and closing that syntax hole expands
the honest pre-governance surface to 273 sites across 234 exact callables; there
are no module-level sites.

| Owner | Exact callable entries |
| --- | ---: |
| `auth_reset_guardian` | 23 |
| `auth_usage_dashboard` | 13 |
| `domain_checks` | 88 |
| `e2e_registry` | 25 |
| `e2e_runner` | 27 |
| `e2e_sandbox` | 9 |
| `tests` | 49 |
| **Total** | **234** |

Of those entries, 184 contain exception handling only, 49 contain a currently
matched transport construct only, and one contains both capabilities. The
canonical inventory has SHA-256
`db36076ee017ad1f8d03e3b21e0db1c87330df5f4584ff620f79ee127be4ea28`.
At that preflight snapshot, its exact input set—411 source files plus
`quality/.semgrep.yml`—had SHA-256
`9f8d5aba400d1a2752c822cdd98217abf12550e13e9ad7f85866a6aa70b0d10c`.

Approval must not turn those 234 callables into open-ended exemptions. The
reviewed manifest must bind each path/qualname and declared capability to stable
AST site fingerprints. The anti-bypass verifier must reject a newly added site
inside an already approved callable, as well as unknown, moved, duplicated, or
orphaned sites; require direct canonical decorator imports and literal
capabilities; and continue rejecting nested inheritance, aliases, rebinding,
fake decorators, and unused capabilities. The Semgrep rule must explicitly
cover plain, `else`, `finally`, and combined `else`/`finally` exception shapes,
remove the framework-wide exemptions, and rely on the AST verifier to prevent
nested-function laundering. This is the contract proposed for explicit
governance approval; no policy file has been changed.

Two no-write scratch proofs validate the implementation shape. Locked Semgrep
1.166.0 matched exactly one intended site for each explicit plain, `else`,
`finally`, and combined `else`/`finally` pattern, with zero parse or engine
errors. A normalized `ast.dump(..., include_attributes=False)` site fingerprint
remained identical across blank-line and comment movement, while changing the
handler behavior changed the digest. Manifest multiplicity must still be
checked so duplicating an identical site cannot reuse one approved fingerprint.

## Production-main integration checklist

The zero-debt branch began at protected `staging`, while current production
`main` continued to receive operational work. The zero-debt checkpoint must be
merged with the exact current `main` tip before its final report is generated.
The integration review must retain these production contracts rather than
resolving conflicts in favor of older staging behavior:

The two protected branches also contain a pre-existing scope difference:
`staging` includes dashboard and guardian work that is absent from production
`main`. This campaign does not authorize a blind staging-to-main promotion of
those unrelated features. The staging landing remains the base against which
PR #43 must sync and prove zero debt. Separately, the production-release
candidate must record the exact main tip and tree, enumerate its complete path
delta, and contain only this campaign's quality/refactor/release changes plus
the production contracts below. Any proposal to release other staging work
requires its own explicit approval. Both resulting exact heads must pass the
complete locked gate; only the explicitly approved production head may enter
the protected release environment.

| Production contract | Required preservation evidence | Status |
| --- | --- | --- |
| AFAS demo Basic-auth login and exact credential forwarding | Exact-identity runner tests, `test_e2e_runner_secret_forwarding.py`, and the real AFAS canary fixture | Pending merge |
| Retired Dispatcher isolation | Empty endpoint default, disabled registry/runner dispatch, unavailable-reason behavior, and `test_e2e_registry_dispatch_isolation.py` | Pending merge |
| Two-factor host monitoring | The production plugin/config plus `test_twofa_server_monitoring.py` | Pending merge |
| Entra SSO edge contract | Preserve the production test name and assertions from `test_monitoring_entra_edge_config.py` | Pending merge |
| Domain/event/inventory changes | Focused domain, event, inventory, dispatch, and state tests plus the full suite | Pending merge |
| Quality-tool migration | Keep the locked `quality` package and remove superseded root Semgrep and `scripts/check*.py` entrypoints | Pending merge |
| Production deployment behavior | Exact-SHA release test, migrated non-runtime exclusions, workflow static validation, and protected-environment read-back | Pending merge |

## Deployment provenance

The historical control failure remains visible: strict run
[32853906729](https://github.com/JoshuaSeth/pitchai-monitoring/actions/runs/32853906729)
failed for `8a47f8fe16e8f75b6323ca26ff3ce62552be4739` while deployment run
[32853906420](https://github.com/JoshuaSeth/pitchai-monitoring/actions/runs/32853906420)
succeeded. The replacement deployment workflow has no manual-dispatch path and
accepts only a successful same-repository push run for `main`.

The earlier single-commit selector was rejected during design review because a
multi-commit push could contain a runtime change followed by a documentation-
only final commit. The current strict workflow captures the original push
payload before running repository code. The deployment workflow downloads only
that exact run-attempt artifact, rejects unexpected files or provenance fields,
and validates the immediate push ancestry. It then finds the newest unexpired
marker produced only after a successful exact-SHA production workflow and
recomputes the path decision from that actually deployed SHA to the validated
SHA. Before trusting the marker, it revalidates both the completed deployment
workflow and the marker's successful strict run through the Actions API. It
requires deployment when either provenance source is missing,
malformed, unavailable, non-ancestral, all-zero/new-ref, or otherwise
unprovable. This closes the separate-push case where a runtime strict run is
canceled or superseded before a later documentation-only run succeeds.

An executable probe ran the embedded selector against synthetic Git histories.
A documentation-only single commit selected no deployment; a runtime squash,
a runtime commit followed by a documentation-only commit in the same push, and
a merge commit carrying a runtime change all selected deployment. Missing and
new-ref ancestry also selected deployment. A byte-identical runtime file moved
under `docs/` selected deployment because rename detection is disabled for the
path decision, exposing both the runtime deletion and documentation addition.
A forged `after` SHA was rejected. Those eight original-push cases passed. A
second executable probe then reproduced the separate-push hazard: the immediate
parent range contained only `docs/note.md`, while the range from the last
recorded release still exposed the earlier runtime change and selected
deployment. A marker after that runtime release correctly allowed the later
docs-only commit to skip; missing and malformed markers selected deployment;
invalid strict-run provenance also selected deployment; an already-deployed
exact SHA skipped. All six deployed-range cases passed and their disposable
workspace was removed. Focused release tests pass 5 of 5, including fail-closed
credential-directory/file shape and permission checks plus the run-identity,
workspace-path, and cleanup guards described below, and both
current workflows passed
checksum-verified Actionlint 1.7.12 after this change. The provenance-capture
and deployed-range selector shell blocks also passed ShellCheck 0.8.0, and a direct
capture probe produced the exact closed-schema JSON expected by deployment.

The protected `production` environment requires reviewer `JoshuaSeth`, accepts
only protected branches, and has administrator bypass disabled. Configuration
read-back at `2026-08-25T23:35:35Z` proved `can_admins_bypass=false` while
preserving the reviewer and branch-policy rules. A deployment read-back still
returned an empty inventory, so tightening the approval gate caused no runtime
change.

The production cutover now keeps every complete current container set and any
recognized legacy monitoring container under run-unique rollback names until
the exact-SHA candidate passes two stability rounds and the event-bus
configuration assertion. It refuses partial current sets, unexpected images,
or occupied rollback names before mutation. Its exit trap removes any partial
candidate, renames and restarts every preserved container, and restores the
prior mutable `service-monitoring:latest` image tag. A first deployment with no
prior release rolls back to no containers instead of leaving a partial set.
The remote script accepts only positive-integer run IDs and attempts, derives
one exact `/tmp/service-monitoring-deploy-<run>-<attempt>` workspace and rollback
suffix from them, validates both shapes, makes them read-only, creates the
workspace at mode 700, and repeats the exact path guard immediately before its
only recursive cleanup. The process umask is 077 before any workspace or
credential creation.
Only after stability, exact image-tag identity, and every running container's
immutable image ID matching the validated candidate are proved does it commit
the cutover and remove the stopped rollback set. Focused source-order assertions,
YAML parsing, Actionlint 1.7.12, and ShellCheck 0.8.0 pass; an approved live
rollback drill and the resulting workflow evidence remain pending.

The runner cutover also creates a dedicated `e2e-runner-leases` named volume,
mounts it at `/uid-leases`, and explicitly sets
`E2E_SANDBOX_UID_LEASE_DIR=/uid-leases/locks`. This preserves cross-process UID
leases across container replacement instead of relying on container-local
`/run/lock`. A Dockerfile-built probe then ran the root supervisor with
`no-new-privileges`, successfully dropped a child to UID 60000, and completed a
real Chromium title/DOM check as UID 60000 with `NoNewPrivs=1`. The workflow now
sets `--security-opt no-new-privileges:true` on the registry, runner, and monitor
containers. This does not claim CPU, memory, process-count, output, disk, or
network/egress containment; those remain explicit residual risks.

### Submitted-browser runtime proof

The expanded runner integration exposed two real runtime defects before a
candidate commit was created. First, the original registry fixture placed the
database, uploaded tests, and artifacts below one storage parent that the
production migration correctly seals at mode 0700. The fixture now uses the
production-shaped independent `/data`, `/artifacts`, and `/uid-leases` roots.
Second, Chromium terminated before page execution with
`process_singleton_posix.cc:313 Socket path too long`: its profile socket below
the tenant/test/run artifact tree exceeded the Unix-domain-socket limit.

Submitted browsers now receive a short `TMPDIR` at
`/run/pitchai-e2e-sandbox/tmp-<leased-uid>`. The root supervisor owns the
mode-0711 alias root and each symbolic link; every target must be the absolute,
mode-0700 `sandbox-tmp` directory owned by that exact trusted or untrusted
leased UID. Startup and normal cleanup discover and remove exact aliases before
UID reuse, while unexpected root entries, alias reuse, target substitution, an
out-of-pool UID, or a recovered target outside artifact storage fail closed. A
focused AF_UNIX probe reproduced failure through the long private target and
success through the short alias, with the resulting socket still located in
the private target. The image also deterministically applies mode 0644 to the
copied Puppeteer runtime so a dropped UID can read the entrypoint regardless of
host checkout metadata.

The provisional image-source set (Dockerfile, requirements, and every file
copied from `domain_checks`, `e2e_registry`, `e2e_runner`, `e2e_sandbox`, and
`specs`) had SHA-256
`938ba67267dc73b5a5f2dffa4993b3dde9212567d97d7e552b14d9faa3332ff3`.
Docker built image
`sha256:4a38a48b2903269c559a7d1d886ecf12de91527d22b762f847279a5f0013675e`
from that source. An ephemeral container used that exact image with
`--security-opt no-new-privileges:true` and `--shm-size 1g`; only the `tests`
directory was mounted read-only, so none of the production source packages was
overlaid. The live registry-to-runner integration passed in 10.96 seconds. It
executed a passing Python browser submission, an intentionally failing
JavaScript browser submission with screenshot and log retrieval, disablement,
source replacement, and successful recovery. Both submitted runtimes asserted
a non-root UID and `NoNewPrivs: 1` from `/proc/self/status` inside the
submission itself.

The focused alias/recovery/execution/release set passed 17 tests with the host
integration explicitly xfailed because the host interpreter resolves through
mode-0700 `/root`; the authoritative image run above covers that path. Ruff
passed, BasedPyright reported zero errors and warnings, and Pylint scored
10.00 for the touched runner/release files. The broader 34-test runner set
initially passed 32 tests, with the same expected host xfail and one deliberately
stale AFAS trust-digest sentinel. After the reviewed canary source reached its
final local shape, the credential allowlist retained the live-production digest
`b1cfcdad808133c31f6ab4570b423e171558f6a76277ddf00be6fd807bb1debd`,
removed the obsolete intermediate digest, and authorized only the exact bundled
candidate digest
`dd2d58547022379511dbfea9068bb0ef572b9c15ece76e3390f04a85c14e9bf2`.
The exact-identity credential-forwarding regression passed. On the credential
module and both AFAS canaries, all five architectural checks, Ruff,
BasedPyright with zero diagnostics, Pylint at 10.00, and Semgrep with zero
findings passed under the canonical locked configuration.

After that trust update, the complete 411-file aggregate was rerun for the five
architectural checks, Ruff, BasedPyright, and Pylint; every selected gate passed,
with BasedPyright still at zero diagnostics and Pylint still at 10.00. The only
source edit since the latest complete Semgrep scan was the credential allowlist
digest, and canonical Semgrep reported zero findings on that module and both
canaries. The complete Semgrep total therefore remains 249 pending the explicit
governance decision; the anti-bypass trust anchors remain intentionally stale
until the source and approved policy are frozen together.

The final post-template-migration local suite produced JUnit totals of 257 test
records, zero failures, zero errors, and seven skipped records. Six records are
the explicit opt-in live modules skipped at collection; the seventh is the
documented host-only registry-to-runner xfail. Therefore all 250 runnable tests
passed, including the AFAS digest sentinel, and no warning summary was emitted.
The temporary UID-lease directory and JUnit artifact were removed after the
run. The two affected UI suites had separately passed with
`DeprecationWarning` promoted to an error after all registry template responses
were migrated to Starlette's request-first API. This source-only compatibility
cleanup happened after the provisional image build, so the final exact
candidate still requires the authoritative remote/CI image proof. These are
pre-commit proofs, not substitutes for the final exact-candidate workflow and
regenerated trust manifest. After consumer counts were verified as zero, all
four task-scoped validation image tags were removed; the production
`service-monitoring` image was not modified.

The integration candidate also retains the deployed-main E2E dispatch-disable
convergence, exact AFAS demo credential-file handoff, container stability
checks, log tailing, and deployment-directory cleanup. The deployment workflow
parses as YAML, its embedded remote
Bash passes ShellCheck after GitHub expressions are replaced with inert fixture
values, and the focused event/deployment contract suite passed 42 of 42 tests
before the ongoing domain-module extraction. The split local HTTP/browser suite
also passed 16 of 16 tests with `CHROMIUM_PATH=/usr/bin/google-chrome`. That
explicit executable selection avoids this validation host's snap-packaged
`chromium-browser`, whose private `/tmp` cannot see Playwright's host-created
profile; an independent fresh-profile Google Chrome probe passed while the snap
probe failed before any test assertion. No skip or source fallback was added.
These are provisional local design checks; the exact integrated suite, committed
workflow run, and approved-release proof remain pending.

## Sanitized pre-release production snapshot

Snapshot time: 2026-08-25 20:42 UTC.

- Source and image tag: `b27bdd17f9db6737e332305780ec3cc0baf84721`.
- Image ID: `sha256:e6dbd7b2a736710619d4c58d04f565588569f7e4a6401fafbaaf0562c94e6d5c`.
- `service-monitoring`, `e2e-registry`, and `e2e-runner` were running, not
  restarting, and each had restart count zero.
- Persistent volumes predated the campaign: monitoring state from January 2026
  and registry/artifact volumes from February 2026.
- Monitoring state version was 6, with 60 domain history keys, 60 last-ok keys,
  an empty event-bus outbox, and browser degradation false.
- The registry contained 36 tests, 36 states, 181,519 runs, and 3 dispatch
  runs.
- AFAS demo fast, GZB medium, and GZB daily were enabled with
  `effective_ok=1`, `fail_streak=0`, and latest status `pass`.

Only counts, hashes, timestamps, and operational status were collected. No
tokens, credential values, customer bodies, or raw monitor payloads are part of
this record.

## Negative-probe matrix

Each final probe will be an isolated temporary commit against the exact green
candidate. Evidence must include the probe SHA, failing gate/job link, absence
of a production deployment for that SHA, restoration SHA, and restored green
run. Probe branches and registered worktrees must be removed.

| Gate | Isolated violation | Failing run | Deployment query | Restored run |
| --- | --- | --- | --- | --- |
| No validation bypasses | Mutable or altered enforcement trust anchor | Pending | Pending | Pending |
| Nested event loops | Nested synchronous event-loop creation | Pending | Pending | Pending |
| Vague signatures | Vague top-type parameter or return contract | Pending | Pending | Pending |
| Single-use one-line functions | One-expression helper with one runtime use | Pending | Pending | Pending |
| Pure wrapper functions | Pass-through wrapper around a local callable | Pending | Pending | Pending |
| Dense inline comprehensions | Dense comprehension shape covered by policy | Pending | Pending | Pending |
| Ruff | Ruff-only selected-rule violation | Pending | Pending | Pending |
| BasedPyright | Type-only strict diagnostic | Pending | Pending | Pending |
| Pylint | Pylint-only structural diagnostic | Pending | Pending | Pending |
| Semgrep | Semgrep-only business-boundary violation | Pending | Pending | Pending |

## Final candidate and post-release observation

Pending. This section will record the exact commit and tree IDs, zero-debt
report hash, required PR and main workflow links, protection read-back,
approved deployment ID and URL, deployed image identity, rollback reference,
post-release state hashes and counts, fresh domain/E2E timestamps, AFAS demo and
GZB outcomes, restart counts, and the observation interval of at least 24
hours.
