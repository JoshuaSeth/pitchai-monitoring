# Daily review evidence classification

Durable rules for the 05:00 Europe/Berlin morning monitoring review. They exist
because the first 2026-09-30 daily report quoted "36 tests" and a bare
"634/634 E2E passes", which read as "the whole E2E estate is green". The
registry's 36 rows are 4 schedulable recurring tests, 3 temporarily paused tests
and 29 disabled rows, and the 634 passes cover only the schedulable 4. The
corrected report is `monitoring/reporting/2026-09-30-daily-review.md`.

## Classify the registry before quoting any aggregate

Apply the scheduler's own predicate (`e2e_registry/db.py`):
`t.enabled = 1 AND (t.disabled_until_ts IS NULL OR t.disabled_until_ts <= now)`.

| Class | Registry shape | How to report it |
| --- | --- | --- |
| Schedulable recurring | `enabled=1`, no future `disabled_until_ts` | current evidence - quote runs, passes, last finish, streak |
| Temporarily paused | `enabled=1` with a future `disabled_until_ts` | intentional pause - never current evidence, never a scheduler failure |
| Disabled | `enabled=0` | out of service - quote the disable reason, not the historical status |

A paused row keeps its historical `last_status` (for example `pass` from
February) and a stale `next_due_ts`; that is a record of the last run, not
health. Pausing, activating and retiring tests belong to the owning project, not
to the monitoring lane.

## Scope every aggregate

- Quote a pass count together with its window, its scope ("the four schedulable
  recurring tests") and the per-test split. Never present it as "E2E is green".
- Report the last finish and status per schedulable test. Evidence older than
  roughly two intervals is stale evidence and needs investigation.
- Treat a nonzero `failing_tests` from the registry summary as an escalation
  signal even when the summary `ok` flag is true, and inspect enabled tests whose
  `last_status` is not `pass` even when `effective_ok=1` (one-failure grace).

## Resolve claim rows, do not dismiss them

`runs` holds a claim row for the next scheduled attempt before the runner starts
it: `status=infra_degraded`, `error_kind=pending`, `started_at_ts` and
`finished_at_ts` NULL, matching `test_state.running_lock_id`. The scheduler then
updates **that same row** with the outcome, so a lone non-pass in a fresh window
is either a real failure or a claim that has not finished yet. Never quote it as
a pass, and do not wave it away as bookkeeping - wait one cadence or re-read the
row and report what it settles into. Abandoned claims do residue: 25 rows
registry-wide still sit at `pending` with `started_at_ts IS NULL` (oldest
2026-08-27), which is how a claim can also mark a cycle that never executed.

## AFASAsk Codex smoke covers two lanes

The production Codex path is verified by two enabled tests, and both must be
green:

| Test | Surface |
| --- | --- |
| `afasask_production_codex_medium_synthetic_ok` (1 800 s) | `https://afasask.gzb.nl` |
| `afasask_demo_codex_fast_ok` (1 800 s) | `https://demo.afasask.pitchai.net` |

`afasask_gzb_codex_medium_ok_daily` was retired on 2026-09-03 and stays
`enabled=0`; its history is not current evidence. Both live tests drive the auth
broker, Codex execution and the live UI together, so any non-pass is actionable
on its own, and two non-passes across the two surfaces point at Codex mode
rather than at one page.

Read the artifacts before classifying: the production lane only inspects
`article[data-role="assistant"]` for success and failure markers, and the UI's
`Mislukt` block renders outside that article, so a hard UI failure can surface
as a 240 s `TimeoutError` with `browser_infra_error=false`. A `failure.png`
showing `Mislukt - "Het is niet gelukt om Codex-modus te voltooien"` is a
product failure; the demo lane reads the marker directly and fails in seconds.
On 2026-09-30 both lanes failed twice in a row (20:10-20:14Z plus 20:45-20:49Z
on production, 20:15Z plus 20:49Z on demo), which is the difference between one
flaky run and a broken pattern: always wait for the next scheduled run before
calling a single failure transient.

## Hotpath lanes are a separate stream

Project hotpath lane outcomes live in `hotpath_lane_state` / `hotpath_reports`
and are not covered by the E2E registry aggregate. Report them per lane:
severity, failure class, last-report age and streak. A lane's latest severity
describes its last report, not now - a lane that has not reported for days still
reads `info`, so report the staleness explicitly. See
`docs/client-hotpath-monitoring.md` for the lane contract and
`e2e_registry/hotpath_inventory.json` for expected intervals.

Each report carries the `source_sha` / `deployed_sha` observed when it was
written, so the revisions in a stale lane are as old as the report and only a
fresh report can speak to the current deployment. Say which revisions a claim
rests on instead of implying a live deployment check.

## Outbox delivery is not health

`hotpath_event_outbox.status='delivered'` proves the publisher handed the event
to the receiver inbox. It is not lane health, not remediation and not alert
acknowledgement, and it must never be quoted as evidence that lanes are
healthy - a full outbox can coexist with critical lanes and stale lanes.

## Dated evidence (2026-09-30)

Read-only SQLite handle inside `e2e-registry` (`mode=ro`), verified
2026-09-30T20:03-20:17Z:

- 36 rows: 7 `enabled=1` (4 schedulable, 3 paused until `1893456000`), 29
  `enabled=0` (28 auto-disabled `disallowed base_url host:
  formatief-toetsen.pitchai.net`, 1 retired AFASAsk legacy probe).
- Window 2026-09-29T20:03Z - 2026-09-30T20:03Z: 634 runs, 634 pass, split
  271 `deplanbook_cms_home_smoke_py`, 270
  `deplanbook_cms_on_demand_translation_py`, 47 `afasask_demo_codex_fast_ok`,
  46 `afasask_production_codex_medium_synthetic_ok`; all four `effective_ok=1`,
  `fail_streak=0`.
- Minutes later the same window read 634 rows / 633 pass with one in-flight
  claim row; that row resolved at 20:14:16Z as a real failure, and by 20:16:37Z
  the window was 635 runs / 633 pass, the two non-passes being
  `afasask_production_codex_medium_synthetic_ok` (`TimeoutError`, screenshot
  shows `Mislukt`) and `afasask_demo_codex_fast_ok` (marker `❌ mislukt`).
- Verified 20:44-20:50Z: both retries repeated the failure (production
  20:45:20Z - 20:49:35Z, 251 909 ms, same `Mislukt` state; demo 20:49:35Z -
  20:49:47Z, same marker), leaving both lanes `effective_ok=0`,
  `fail_streak=2`, next due 21:19:58Z / 21:19:59Z - a broken pattern, recorded
  for escalation at the next review rather than sent under this follow-up's
  no-external-message constraint.
- 16 live hotpath lanes, 204 lane reports, 81 outbox intents all `delivered`,
  with 2 lanes critical and 4 lanes stale since 20-25 September.
