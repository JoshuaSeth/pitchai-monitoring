# Spec: External Developer-Submitted E2E Test Files (Playwright Python + Puppeteer JS) Registry + Runner

## Original Feature Request (Verbatim)

"""So we want to design some system where external developers can just send their end-to-end tests that must always pass, that are automatically
incorporated in the monitoring system. So I suspect they should supply like a Playwright Python or JavaScript or whatever file and the domain main on
which it runs, something like that. And then they must submit that to some API and monitoring. and then yeah, the test gets always run and gives them a
signal when it's not passing right and the monitoring every... How often do we run these? Every 5 minutes? so So then the end-to-end tests can be
registered in the monitor. So yeah, device and architecture for that."""

## Summary (Updated)

Add a multi-tenant way for external developers to upload real E2E test files (Playwright Python and Puppeteer JS) that continuously run against real deployed services and alert when they fail.

The solution must:

1. Accept test submissions via an API (and optional UI) as files (not YAML-only).
2. Execute tests on a schedule (default 5 minutes, configurable per test).
3. Persist results + artifacts (logs, screenshots, optional Playwright traces) and expose them for humans + automation.
4. Alert and optionally escalate to Dispatcher/Codex when tests fail, with robust anti-spam (debounce + state persistence).
5. Never disrupt running services: tests must be designed and executed as non-destructive, least-privilege, and resource-bounded.

## Context: Existing System (What We Already Have)

This repo (`JoshuaSeth/pitchai-monitoring`) is a Python monitoring service that runs as a single Docker container (`service-monitoring`) and performs:

1. Minute-by-minute per-domain checks:
   - HTTP GET check (`domain_checks/common_check.py:http_get_check`)
   - Playwright UI rendering + expectations (`domain_checks/common_check.py:browser_check`)
2. Debounced alerting with persisted state (`domain_checks/main.py:_update_effective_ok`, persisted to `STATE_PATH`, default `/data/state.json`).
3. Telegram reporting (`domain_checks/telegram.py`).
4. Optional escalation to Dispatcher/Codex for read-only triage and forwarding results back to Telegram:
   - Dispatch client: `domain_checks/dispatch_client.py`
   - Prompts: `domain_checks/main.py:_build_*_dispatch_prompt` and `domain_checks/main.py:_dispatch_read_only_rules`
5. Synthetic end-to-end "transactions" implemented as a safe declarative DSL (a list of step dictionaries) executed by Playwright:
   - Runner: `domain_checks/metrics_synthetic.py:run_synthetic_transactions`
   - Per-domain config: `domain_checks/<domain>/check.py` via `CHECK["synthetic_transactions"]`
   - Orchestration + scheduling: `domain_checks/main.py` section "Synthetic transactions (Playwright step flows)"

Key existing design features we should keep and reuse:

1. The Synthetic StepFlow DSL is already an E2E testing substrate that can be submitted as structured JSON/YAML (no arbitrary code).
2. Debounce + persisted state is already proven to prevent per-minute spam.
3. Dispatcher escalation prompts already include strong read-only safety rules.
4. The monitor already includes reliability mechanisms around Playwright instability (browser-degraded detection + HTTP-only fallback).

## Goals

1. External developers can register E2E tests without changing this repo or redeploying the monitor.
2. Tests run continuously with predictable frequency (default 5 minutes).
3. Failures generate actionable alerts with evidence and stable links:
   - immediate failure details
   - most recent pass timestamp
   - artifacts (screenshot/trace/log)
4. Failures can trigger Dispatcher/Codex triage with a prompt tailored to the test failure and strict non-disruption rules.
5. Tests can be temporarily disabled (per test, with reason + optional until timestamp) to stop repeated noise.
6. All of this works with real deployed services (no mocking in acceptance validation).

## Non-Goals (Adjusted)

1. Running developer-submitted code inside the `service-monitoring` process. (Execution belongs in `e2e-runner`.)
2. Turning this into a full CI system; this is monitoring and operational signaling.
3. Supporting destructive workflows on production. If a test requires writes, it must run on a dedicated staging environment or use least-privilege accounts.

## Architecture Options (1-4) and Decision (Updated)

### Option 1: Declarative StepFlow Tests via API (Legacy/Optional)

External developers submit tests as a structured JSON/YAML "StepFlow" file (the same DSL already used by `synthetic_transactions`).

Execution uses Playwright, but the "test code" is data, not code.

Benefits:

1. Strong security: no arbitrary code execution.
2. Simple execution: reuse `domain_checks/metrics_synthetic.py:run_synthetic_transactions`.
3. Easy validation: schema validation can reject unsafe/invalid steps at submission time.
4. Aligns with current system: the monitor already runs synthetic transactions, debounces, and dispatches triage.

Risks/Cons:

1. Less expressive than full Playwright; some complex flows may not fit without DSL extensions.
2. Developers used to Playwright Test (JS/TS) may need translation to DSL.

When to pick:

Pick this for simple flows or when you want the safest possible "data-not-code" option. This remains supported, but is no longer the primary developer submission workflow.

### Option 2: Upload Playwright Python + Puppeteer JS Files and Run in a Sandbox Runner (Recommended)

External developers submit a single-file Playwright Python test (`.py`) or Puppeteer JS test (`.js`/`.mjs`). The system executes it via `e2e-runner`, capturing artifacts and reporting results.

1. A per-run container/job with strict resource limits and no host mounts.
2. Network allowlisting limited to the target domain(s) via egress proxy or firewall.

Benefits:

1. Max developer flexibility and compatibility with existing Playwright ecosystems.
2. Can support advanced fixtures, richer assertions, and traces out-of-the-box (especially in `@playwright/test`).

Risks/Cons:

1. Security: untrusted code execution is extremely risky without heavy sandboxing and egress control.
2. Operational complexity: container orchestration, dependency management, artifact management, and abuse prevention.
3. Cost: higher CPU/mem/disk and more moving parts.

When to pick:

Pick this when you explicitly want developers to keep authoring real Playwright/Puppeteer code and you accept the operational/security tradeoffs. This is the primary workflow implemented in this repo now.

### Option 3: GitOps Tests (PR-based) Instead of API Uploads

External developers submit tests via PR to a dedicated repo. A review step ensures safety. The monitoring system periodically pulls the repo and runs tests.

Benefits:

1. Reviewable and auditable. Safer than API-uploaded code.
2. Familiar to developers.
3. Strong change control (approval gates).

Risks/Cons:

1. Not "submit to API"; slower feedback loop for onboarding tests.
2. Still runs code; sandboxing remains relevant.

When to pick:

Pick when external devs are trusted and you want strong review workflows, but can accept slower onboarding.

### Option 4: Use a Managed Synthetic Monitoring Vendor (e.g., Checkly) + Integrate Alerts Here

External devs manage tests in vendor UI or via vendor API. This repo only ingests results and forwards to Telegram/Dispatcher.

Benefits:

1. Fastest path to "Playwright monitoring".
2. Scaling, dashboards, and artifact storage is handled.

Risks/Cons:

1. Vendor lock-in and ongoing cost.
2. Harder to enforce "read-only/no-disruption" with internal operational rules and triage workflows.

When to pick:

Pick when operational bandwidth is limited and you accept vendor dependency.

## Chosen Direction (Implemented)

Implement Option 2 as the foundational architecture:

1. External tests are submitted as real code files plus metadata (base_url, schedule, alert policy).
2. Tests are executed by a dedicated "E2E runner" worker that runs:
   - Playwright Python via `e2e_sandbox/playwright_python.py`
   - Puppeteer JS via `e2e_sandbox/puppeteer_js_runner.js`
3. `service-monitoring` integrates `e2e-registry` status summaries in scheduled heartbeats and can optionally trigger dispatch triage.

StepFlow remains supported for simple, declarative tests, but is not required for external developer onboarding.

## Proposed Components

### 1) `e2e-registry` (New Service)

Responsibilities:

1. API for test registration and management (create/update/disable/delete).
2. Store test definitions (StepFlow) and metadata.
3. Store run history and artifact pointers.
4. Expose status endpoints for external developers (polling).
5. Optional simple UI for humans.

Persistence:

1. Prefer Postgres for multi-tenant concurrency and future growth.
2. Allow SQLite for a minimal single-host deployment if Postgres is not available (but keep schema compatible).

AuthN/AuthZ:

1. API keys per "tenant" (external dev org/project).
2. Each test belongs to a tenant; tokens only access their tenant’s tests and results.
3. Admin key for internal operations.

### 2) `e2e-scheduler` (Worker)

Responsibilities:

1. Periodically find tests due to run (respect interval + jitter).
2. Enqueue runs into a durable queue.

Queue (choose one):

1. Postgres-backed queue table (simplest for single-host).
2. Redis queue (better throughput; extra dependency).

### 3) `e2e-runner` (Worker)

Responsibilities:

1. Execute a single StepFlow test against a real target base_url with Playwright.
2. Collect artifacts: logs + screenshot on failure; optionally trace.
3. Store run result in registry DB and publish alert events.

Resource boundaries:

1. Concurrency limit (global and per-tenant).
2. Per-run timeout.
3. Browser lifecycle strategy:
   - start one Chromium process per worker and create a new context/page per run (similar to current monitor)
   - or start a fresh browser per run for stronger isolation (slower but safer)

### 4) `service-monitoring` (Existing Service) Integration

Integration points:

1. Add an optional periodic fetch of E2E test status summaries from `e2e-registry`.
2. Include E2E test status in the twice-daily heartbeat message (similar to "Domains (HTTP / Browser)" section).
3. On newly failing E2E tests (debounced), send Telegram warning and optionally dispatch triage.

Important: do not run untrusted tests inside `service-monitoring`. Keep execution in `e2e-runner`.

## API Contract (e2e-registry)

All endpoints below are illustrative but should be implemented as a stable versioned API (`/api/v1/...`) with OpenAPI.

Authentication:

1. `Authorization: Bearer <api_key>` for external developers.
2. Admin key may be supported via a separate issuer or an `X-Admin-Key` header (implementation choice).

Authorization rules:

1. External keys are scoped to one tenant.
2. Admin can access all tenants/tests.

Endpoints:

1. `POST /api/v1/tests`
   - Creates a new test.
   - Body includes metadata, schedule, and StepFlow definition.
2. `POST /api/v1/tests/upload`
   - Creates a new test from an uploaded file (multipart form).
   - Fields include: `name`, `base_url`, `kind` (`playwright_python` or `puppeteer_js`), schedule/alert config, and `file=@...`.
2. `GET /api/v1/tests`
   - Lists tests for the authenticated tenant (supports filtering by `enabled`, `base_url`, `label`, `status`).
3. `GET /api/v1/tests/{test_id}`
   - Fetch a single test (definition + metadata).
4. `PATCH /api/v1/tests/{test_id}`
   - Updates mutable metadata and schedule fields (interval/timeout/jitter/recipients).
5. `POST /api/v1/tests/{test_id}/disable`
   - Body: `reason` (required), `until` (optional unix ts or ISO date/datetime).
6. `POST /api/v1/tests/{test_id}/enable`
   - Re-enables a disabled test.
7. `POST /api/v1/tests/{test_id}/run`
   - Triggers an immediate run (manual override, still resource-limited).
8. `POST /api/v1/tests/{test_id}/source`
   - Replaces the uploaded source file for a code-based test (multipart file upload).
8. `GET /api/v1/tests/{test_id}/runs?limit=...`
   - List recent runs (newest-first).
9. `GET /api/v1/runs/{run_id}`
   - Fetch a run record including structured errors and artifact references.
10. `GET /api/v1/runs/{run_id}/artifacts/{name}`
   - Download artifacts (screenshot/trace/log) with tenant authorization.
11. `GET /api/v1/status/summary`
   - Lightweight summary for `service-monitoring` heartbeats/alerts.
   - Includes: total tests, failing tests, slow tests, last run timestamps.

Error model:

1. Use structured JSON errors: `{ "error": { "code": "...", "message": "...", "details": {...} } }`
2. Common codes: `invalid_schema`, `unauthorized`, `forbidden`, `not_found`, `rate_limited`, `runner_unavailable`.

## Database Schema (e2e-registry)

Tables (minimum viable; field names illustrative):

1. `tenants`
   - `id` (uuid), `name`, `created_at`
2. `api_keys`
   - `id` (uuid), `tenant_id` (uuid), `name`, `token_hash`, `created_at`, `revoked_at`
3. `tests`
   - `id` (uuid), `tenant_id` (uuid), `name`, `base_url`
   - `enabled` (bool), `disabled_reason` (text), `disabled_until_ts` (float|null)
   - `interval_seconds` (int), `timeout_seconds` (int), `jitter_seconds` (int)
   - `definition_json` (jsonb) StepFlow definition
   - `created_at`, `updated_at`
4. `test_state`
   - `test_id` (uuid, PK)
   - `effective_ok` (bool)
   - `fail_streak` (int), `success_streak` (int)
   - `last_ok_ts` (float|null), `last_fail_ts` (float|null)
   - `last_alert_ts` (float|null)
   - `next_due_ts` (float|null) computed schedule cursor
5. `runs`
   - `id` (uuid), `test_id` (uuid), `scheduled_for_ts`, `started_at`, `finished_at`
   - `ok` (bool), `elapsed_ms` (float|null)
   - `error_kind` (text|null), `error_message` (text|null)
   - `final_url` (text|null), `title` (text|null)
   - `artifacts_json` (jsonb) containing artifact paths/URLs and small summaries
6. `run_queue` (if using Postgres-backed queue)
   - `id` (uuid), `test_id`, `due_ts`, `status` (queued/running/done), `locked_by`, `locked_at`

Indexes:

1. `tests(tenant_id, enabled)`
2. `test_state(next_due_ts)`
3. `runs(test_id, started_at desc)`
4. `run_queue(status, due_ts)`

## Artifact Storage

Requirements:

1. Store evidence for failures (at least: screenshot + logs).
2. Keep artifact references stable for links in Telegram and UI.

Storage approach:

1. Local volume (single-host):
   - mount `/data/e2e-artifacts` into `e2e-runner` and `e2e-registry`
   - artifact path format: `/data/e2e-artifacts/{tenant_id}/{test_id}/{run_id}/...`
2. S3-compatible object storage (future):
   - `e2e-runner` uploads artifacts
   - DB stores object keys and presigned URLs generated by `e2e-registry`

Artifacts to capture:

1. `failure.png` screenshot on failure.
2. `run.log` structured log and step-by-step timing.
3. `trace.zip` (optional) Playwright trace for debugging.

Retention:

1. Default keep 14 days of artifacts; keep run metadata longer (e.g., 90 days).

## Runner Execution Details (Playwright)

The runner should mirror existing stability practices in this repo:

1. Route filter to abort heavy resources by default (image/media/font), like:
   - `domain_checks/common_check.py:browser_check`
   - `domain_checks/metrics_synthetic.py:_apply_route_filter`
2. Optional allowlist:
   - restrict navigation to `base_url` host and configured extra hosts (CDNs/auth)
3. Capture diagnostics:
   - console errors (`page.on("console")`)
   - page errors (`page.on("pageerror")`)
   - request failures (`page.on("requestfailed")`)

Infra failure handling:

1. Any Playwright/Chromium crash/driver disconnect should be classified as infra-degraded, not as a per-test functional failure.
2. Reuse the same classification logic as `domain_checks/common_check.py:_is_browser_infra_error`.

## Deployment Topology (Single Host, Docker)

Target topology matches how this repo is currently deployed via GitHub Actions + SSH + `docker run` (`.github/workflows/ci-cd.yaml`):

1. `service-monitoring` (existing)
2. `e2e-registry` (new)
3. `e2e-runner` (new)
4. `postgres` (optional but recommended)

Networking:

1. Put services on the same docker network (e.g., `pitchai-shared`), consistent with existing deployments.

Config:

1. `e2e-registry` requires DB DSN, API key settings, and Telegram/Dispatch config (if it sends alerts directly).
2. Alternatively, `e2e-registry` only stores results and `service-monitoring` is the sole alert sender.

## StepFlow DSL (Test Definition Format)

Base it on the existing `domain_checks/metrics_synthetic.py` step schema:

1. `goto`: optional `url` (absolute or relative); default base_url.
2. `click`: `selector`
3. `fill`: `selector`, `text` (supports secret placeholders)
4. `press`: optional `selector`, `key`
5. `wait_for_selector`: `selector`, optional `state`
6. `expect_url_contains`: `value`
7. `expect_text`: `text`
8. `sleep_ms`: `ms`

Extensions required for external developers:

1. Add `expect_title_contains`.
2. Add `expect_selector_count` (or `expect_selector_visible`) for more robust assertions.
3. Add `screenshot` step (store as artifact).
4. Add `set_viewport` step (optional).

Schema validation at submission time must reject:

1. Unknown step types.
2. Overly long step lists (> 60) and payloads.
3. Invalid selectors/values.

## Secrets and “No Disruption” Policy

Principle: tests must not perform destructive actions in production.

Mechanisms:

1. Use dedicated monitoring accounts with least privilege.
2. Registry stores references to secrets, not raw secret values:
   - external devs cannot upload secrets
   - internal admins configure secrets per tenant/test in environment or secret manager
3. Inject secrets at runtime using placeholders:
   - `${E2E_USERNAME}`, `${E2E_PASSWORD}`, `${TOKEN}`, etc.
4. Optional enforcement:
   - route filter can block requests to non-allowlisted hosts
   - optionally block navigation to non-allowlisted domains (prevent exfil/SSRF)

Note: full prevention of destructive action is not possible at the browser layer alone. Least-privilege accounts are mandatory.

## Scheduling Policy

Defaults:

1. `interval_seconds`: 300 (5 minutes).
2. `timeout_seconds`: 45 (per run).
3. `jitter_seconds`: 0-30s (randomized per run) to avoid bursts.

Controls:

1. per-test interval overrides (min 60s; max 3600s initially).
2. global concurrency and per-tenant concurrency.
3. backoff when a target is consistently failing (avoid hammering broken services).

## Result Model (What We Persist)

Per test:

1. `test_id`, `tenant_id`, `name`, `base_url`
2. `enabled/disabled`, `disabled_reason`, `disabled_until`
3. `interval_seconds`, `timeout_seconds`
4. `definition`: StepFlow JSON
5. `alert_policy`: debounce and recipients

Per run:

1. `run_id`, `test_id`, `started_at`, `finished_at`, `elapsed_ms`
2. `ok` boolean and structured `error` (category + message)
3. `final_url`, `title` (if available)
4. artifacts:
   - screenshot path (on failure)
   - trace path (optional)
   - console/network error summary (optional)

## Alerting and Anti-Spam (Debounce)

Per-test debounce must match the philosophy already used by `service-monitoring`:

1. Maintain `fail_streak`, `success_streak`, and `effective_ok`.
2. Alert only on effective UP -> DOWN transition (plus initial DOWN after threshold).
3. Persist state so restarts do not re-alert every 5 minutes.

Suggested defaults:

1. `down_after_failures`: 2
2. `up_after_successes`: 2

## Escalation (Dispatcher/Codex)

When an external E2E test is failing and dispatch escalation is enabled:

1. Create a dispatch job with a prompt similar to `domain_checks/main.py:_build_synthetic_dispatch_prompt`.
2. Include:
   - test metadata
   - failure details (error, final_url, screenshot/trace links)
   - strict read-only rules (reuse `domain_checks/main.py:_dispatch_read_only_rules` wording)

Output should be forwarded to Telegram similarly to existing flows.

## Reporting

### For External Developers

1. API endpoint to fetch current status and last N runs.
2. Optional webhook notifications on failure and recovery (HMAC-signed).

### For Internal Ops (Telegram + Heartbeats)

1. Telegram warning message when an E2E test transitions to DOWN (debounced).
2. Include in the 07:30 and 12:00 heartbeat:
   - number of passing vs failing external E2E tests
   - slowest tests by elapsed_ms

### UI (Minimal but Required for True UI E2E Validation)

Add a small web UI in `e2e-registry`:

1. List tests (filter by tenant/project).
2. View a test definition and last runs.
3. Upload a new StepFlow file (authenticated).
4. View artifacts (screenshot/trace download).

## Definition of Done

1. External developer can create a StepFlow test via API and see it listed in the UI.
2. The test is executed automatically on schedule (default 5 minutes) against the real target URL.
3. The latest run status and last successful run are visible via API and UI.
4. On failure, the system:
   - debounces alerts
   - sends a Telegram warning with evidence and links
   - optionally dispatches a read-only triage job and forwards results to Telegram
5. Disabling a test via API immediately stops runs and alerts; the reason and until timestamp are visible.
6. All state (tests, run history, debounce state) persists across restarts.
7. Resource safety:
   - concurrency limits enforced
   - timeouts enforced
   - Playwright crash/infra errors do not generate false per-test "DOWN" (align with existing infra detection logic)

## Validation and Test Plan (Real Systems, Real Conditions)

The following validations must exist and be runnable. They are acceptance-level and intentionally use real services and real browsers.

1. Live acceptance smoke: register a real test for a real monitored domain (example: `https://deplanbook.com/`) that asserts a real selector exists.
   - Verify the runner executes it and stores a PASS run record.
   - Verify `service-monitoring` heartbeat includes that test as PASS with elapsed_ms.

2. Live acceptance negative: register a test that is guaranteed to fail against a real monitored domain (example: expect text "THIS SHOULD NOT EXIST" on `https://deplanbook.com/`).
   - Verify the run is recorded as FAIL.
   - Verify Telegram warning fires only on debounced transition.

3. Live recovery path: fix the failing test (update the expected text to something that exists) and confirm:
   - a PASS run is recorded
   - recovery notifications are emitted if enabled
   - state transitions do not flap

4. Real Dispatcher escalation: enable dispatch escalation for an E2E test failure.
   - Verify a dispatch job is created.
   - Verify the prompt contains read-only rules and correct test metadata.
   - Verify the final agent message is forwarded to Telegram with a stable UI link.

5. Real UI E2E test for the registry UI (Playwright):
   - Start the `e2e-registry` service for real.
   - Use Playwright to log in, upload a StepFlow test, and observe it in the list with correct status.
   - This test must include a negative assertion to ensure it fails when the UI is broken (avoid always-pass tests).

6. Production-like load and stability test:
   - Register 25+ E2E tests and run for at least 30 minutes.
   - Verify scheduler spreads runs (jitter), runner respects concurrency, and host does not enter browser-degraded spam state.
   - Verify no duplicate alerts beyond debounce thresholds.

Test reporting:

1. CI unit tests cover schema validation, state transitions, and persistence logic.
2. Live acceptance tests run in a dedicated "live test" job or post-deploy verification step (similar to existing `pytest.mark.live` tests in `tests/`).
3. The system must store artifacts for failures and expose stable links for debugging.

Stop criteria:

1. All unit tests pass.
2. Live acceptance validations 1-4 pass in the target environment (staging or production).
3. UI E2E test (5) passes and demonstrably fails if the UI is intentionally broken.
4. Load/stability validation (6) completes without infra-induced false positives and without alert spam.

## Implementation Notes (How This Fits This Repo)

This spec is intentionally aligned with existing patterns in this repo:

1. StepFlow DSL reuse is based on `domain_checks/metrics_synthetic.py`.
2. Debounce model is based on `domain_checks/main.py:_update_effective_ok` and `STATE_PATH` persistence.
3. Escalation prompt style and safety rules reuse `domain_checks/main.py:_dispatch_read_only_rules` and `_build_synthetic_dispatch_prompt`.
4. Existing monitor already has optional heartbeat reporting and Telegram chunking.

## Open Questions

1. Do external developers need alerts directly (webhook/email/slack), or is internal Telegram sufficient?
2. Do we require multi-browser/device coverage, or just Chromium desktop?
3. Do we need per-tenant isolation beyond logical RBAC (separate runner pools)?
4. Should the first milestone store data in SQLite-on-volume (fast) or commit immediately to Postgres (best long-term)?
