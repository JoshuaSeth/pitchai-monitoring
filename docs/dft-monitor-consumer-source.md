# DFT monitoring consumer: source work in progress

This is the monitoring counterpart of existing Infrastructure request
`4e2c5d80` / DFT work `746ed086`. Monitoring specialist528 owns these consumer
modules;6f97 owns the writer and checker in DFT PR4478;2042/bb44 own DFT release
semantics;Infrastructure624 owns host admission and incident response. No
deployment, private directory creation, event publication or Telegram send is
part of this source change. Existing stopped workers remain stopped.
Infrastructure624 confirms528's existing counterpart acceptance at11:23:59UTC
on October2 and the supported11:27 Astra/medium, active/no-stop observation.
This is retained against the existing746 task; withdrawn manager80f3 remains
stopped. These historical observations do not establish a newer compute sample.

## Source contract and current implementation

Reviewed producer revision: `6885e80032e02f9189b2b548c7a388eb951773d8`, parent
checker `15ae402ea589dea5a82e7a5d36eb84bbd6bd3576` and writer correction
`ca40adf82100c70659702d75e71ef003f81e7d1b`, DFT PR4478.
The checker is `scripts/dft_access_log_status.py`; its output is fixed codes,
original heartbeat age and historical overdue count. Only a zero exit with
trusted age below900 seconds and no errors proves current health. Historical
counts are preserved and do not independently prohibit acknowledged recovery.

The consumer source currently contains:

- `domain_checks/dft_segment_io.py`: original offset-qualified hour selection,
  coverage checks, bounded incremental reads, no symlink traversal, and
  cross-cycle metadata checks for replacement/truncation. A poll reads at most
  its byte budget across all selected segments. A cold scan can span multiple
  polls; validated cursor progress survives restart, while incomplete catch-up
  remains a coverage fault. The byte limit no longer limits total hourly size.
- `domain_checks/dft_access_segments.py`: production-root counters, probe-UA
  exclusion, complete-line parsing and original event-time filtering. Original
  device/inode plus byte offset prevents a second count on the next poll.
  Equal records at distinct byte positions remain separate requests. Only
  timestamps and aggregate status counters accompany durable cursor metadata;
  IP, agent, URI and record text never enter that state.
- `domain_checks/dft_checker_process.py`: proposed bounded local invocation of
  the producer-owned checker. It neither provides a remote executor nor makes
  private state or host clock services accessible inside a container.
- `domain_checks/dft_retention_consumer.py`: sanitized observations and incident
  identity transitions, persisted by the journal before delivery.
  A warning cannot close it; owner acknowledgement and verified healthy proof
  are both required. This pure model is not durable delivery by itself.
- `domain_checks/dft_access_cutover.py` and `metrics_nginx.py`: one source
  selection changes DFT shared-feed exclusion and segment authority together.
  Production DFT is counted once, staging and self-probes are excluded, and
  other hosts retain their shared feed. DFT samples are removed before proxy
  incident construction. Missing segment coverage never falls back to shared
  DFT counts. Host-aware JSON preserves the observed production format.
- `domain_checks/dft_journal.py`: consumer-owned SQLite transactions commit the
  incident and immutable outgoing intent together. Uncertain delivery retains
  the original delivery ID and payload through restart; oldest-first bounded
  retries keep recovery behind failure. A sanitized receiver ID is a separate
  acceptance field. Pending capacity exhaustion fails loudly rather than
  deleting an incident or silently dropping an intent.
- `domain_checks/dft_cycle.py` and the narrow `domain_checks.main` hook: the
  existing cycle reads the chosen feed, calls the checker, records content-free
  health and persists its transitions. Default configuration is disabled and
  allocates no journal or process. No receiver is configured by this patch.
  Each observation consumes a fresh access read; previous-cycle coverage cannot
  satisfy recovery when an access check is skipped.

The format adapter is explicit: producer `event_unix` becomes the original
monitoring event timestamp, and `agent` supplies the transient `user_agent`
probe filter. `status` feeds aggregate counters. The production root binds
host `formatief-toetsen.pitchai.net` and environment `production`; no host field
is inferred from a record. Staging is excluded by source selection. The
offset-qualified `capture_hour` and filename select every original hour
intersecting the window, including an hour or DST boundary. Neither mtime nor
copy time substitutes for event age. The adapter emits no raw request sample.

**Not commissioned:** the exact checker namespace, supported internal receiver
and off-host observer remain unallocated. The local outgoing intent is not yet
an accepted Events delivery envelope. It stays pending when no receiver is
supplied. Source tests do not establish installed configuration or delivery.

The prior18 isolated standard-library tests passed (95.928 seconds). They use synthetic
child-process output, temporary
original files, private SQLite journals and in-memory receiver responses. They
cover large-hour bounded catch-up across restart, window/DST boundaries,
partial completion, identical requests, source cutover, process failures,
incident identity, acknowledgement and uncertain delivery ordering. No
production checker, retention file or notification endpoint is invoked.
The subsequent four-case cycle suite passed in21.453 seconds, including the new
regression for matching acknowledgement with stale access coverage. The failed
incident stays open until a fresh access read and healthy checker agree.

The producer review at `de1f3e3` demonstrated a 1,000,200-byte valid hour with
only 150 current-window bytes rejected by the former whole-hour reader. The new
regression exceeds the same 1 MB budget, faults on the first bounded scan,
restores its cursor from SQLite and obtains complete current counts on the
next poll. A partial final record is counted once after completion. Sustained
incoming bytes must remain below admitted read throughput, and a complete
individual record must fit one poll budget. Catch-up is a required admission
predicate; an oversized record or growing backlog cannot establish coverage.

## Retained metadata and namespace

6f97 supplied `d31-monitor-consumer-review.md`,
`d31-monitor-consumer-container.json`, and `d31-monitor-permissions.json` under
`/mnt/pitchai-dev-data/artifacts/dft-conformity-release-validation-20261002`.
No log, retained incident or state bodies were read for this source task.

Main runs `service-monitoring:a3dc66eaf1430de0796deb311c6dd6b569776890`, container
`63dfee2b3ada2b83cab4de04f25e642c8cd46fa94a01b26898d08421973a103c`.
`monitoring_v2.monitor_launcher` delegates to `domain_checks.main`, using baked
`/app/domain_checks/config.yaml`; the proxy window is300 seconds and cycle60.
The deployed parser accepts host-aware JSON and excludes the monitor UA.
The source adapter restores the observed deployed host-aware JSON semantics
while retaining historical combined-format parsing.

The supplied11:31 metadata observed monitor UID/GID0 and nginx worker UID33.
Infrastructure624's corrected design selects new nginx-UID-owned0700 parent
`/var/log/nginx/dft-access-v1`, production/staging0700 leaves and0600 files.
The writer must traverse every parent; a root-owned0700 writer ancestor is
invalid. Keep shared ancestors unchanged, without copying fixture0711 modes.
Private state moves to new root-owned0700 sibling
`/var/log/nginx/dft-access-state-v1/status.json`, with root-owned0600 status.
This supersedes the earlier `/var/lib/pitchai/dft-web-access-v1` candidate.
Both design roots fall within the existing read-only `/var/log/nginx` mount;
this removes the proposed mount gap but does not prove installed files or a
working checker. Neither new path is created by this change. Admission must
refuse an unexpected existing path and verify current monitor identity, actual
ancestor traversal/read permissions, allocated config, reviewed checker source
and same-host/boot clock capability. Do not widen credentials/groups or relax
0600 to obtain access. No guessed SSH/Docker executor is supplied.
The consumer journal requires its own admitted private path in the monitoring
state volume; it must not point at producer status/config or any access root.
No path is allocated or created by the default disabled configuration.

## Receiver and delivery limits

`docs/events-bus-delivery.md` records the existing internal webhook at
`https://pitchai.net/events-bus/webhooks/pitchai-monitoring`, signed durable
producer outbox, receiver dedupe and accepted receiver ID requirements. That
record does not identify an off-host availability observer or prove a DFT
retention signal is accepted. `docs/monitoring-service-health-contract.md`
describes same-host worker health/watchdog behavior, which does not survive a
Main outage. Existing Infrastructure624 is resolving the exact retained route
and off-host receiver; no new receiver or repair lane is commissioned here.

No natural qualifying DFT failure/recovery delivery receipt has been established
by this work. Source callbacks, accepted commands and isolated tests are not
such receipts. Events and stopped Telegram ownership remain unchanged.

Original Infrastructure binding request `371567fa-1734-4c96-aae9-c8b4c50e0a91`
remains outstanding. Supplement `bf7aaf19-6969-4274-b3a7-ba1932e0feda` records
the concrete integration-gate dependency below; central queue acceptance does
not prove substantive owner acceptance. Neither request is replayed.

## Integration gate and acknowledgement dependencies

The actual cycle hook changes legacy `domain_checks/main.py`. The repository
Quality ratchet requires every changed Python file to be wholly clean. Local
canonical checks expose extensive existing module debt, including468 Ruff
findings at the initial hook revision and additional typing/architecture
failures. Therefore PR204 remains draft and is not integration-ready. The
real hook is included for review; checks, exclusions and baselines are unchanged.
The activation baseline already records 468 Ruff, 1757 typing, 214 Pylint and 76
Semgrep findings in that same module, plus architecture findings. The separate
new/scoped consumer modules pass their targeted static gates; the repository
anti-bypass check still reports 21 unchanged suppressions outside this change.
Infrastructure624 holds the scoped integration-custody request. Clean library
checks do not override the failed cycle-module gate.

The five-file producer acknowledgement delta at `6885e8` is reviewed as source.
It requires the exact reviewed status digest, bound operations owner, retained
incident reference, existing expiry lock and a fresh trusted clean run. It
clears only the latch and adds acknowledgement metadata, preserving original
age, failure history and cumulative counts. The checker command and three-field
output remain unchanged; consumer invocation requires no functional change.
This review neither runs nor authorizes a live acknowledgement.

Producer acknowledgement never implies consumer recovery. The consumer needs
an explicit matching `acknowledged_incident_id` and a later healthy checker plus
complete access coverage. Restart, a new completion time, warnings and historical
cumulative counts alone cannot close an incident. Producer test receipts remain
under `d31-ack-proof-6885e80032`; those tests were read, not repeated here.

## Finite proposed rollout slice

1. Review the complete source and isolated proof, resolve the existing cycle
   module's strict-gate debt through scoped integration custody, and pass normal
   gates against staging. No validation-policy changes or deployment are part
   of this draft. The producer acknowledgement source is reviewed; neither PR
   is deployed by this source handoff.
2.624 binds the existing failure route and independent off-host observer and
   admits the exact checker namespace. Verify config allocation, original clock
   age, source SHA, mount/read/search permissions and checker invocation without
   a synthetic production event or outgoing test.
   The08:50 window is closed. A fresh finite624 window, after source/reader/
   receiver acceptance, retains6f97 as the sole live executor. The16GiB planning
   log budget is an alert/capacity reservation, not permission to delete young
   records or disable logging. Quarantine stays private on the same filesystem
   in6f97's reviewed layout.
3. Verify sufficient original segment coverage for a complete300-second window
   and bounded-reader catch-up at the admitted request volume.
   Change DFT consumer authority and shared-feed exclusion together; preserve
   every other host. Rollback must restore the shared DFT writer before selecting
   it and retain a coverage fault until its full window exists. Never delete or
   rotate old files to manufacture coverage or retention compliance.
4. Observe the installed source and content-free checker status through the
   existing cycle. Later natural incidents alone may establish live delivery.

Raw proxy `sample_lines`, incident text and dispatch payloads in deployed
`domain_checks.main` are potential downstream copies requiring separate DFT
original-age and owner disposition. Shared monitoring/error logs, Docker output,
historical copies and excluded4443 are not inputs to the DFT expiry policy.
Their exact retained contents and original-age coverage remain unproved; this
source task does not inspect, erase or reclassify them.

For the proposed new input, the source copy path is bounded and content-free
after parsing:

| Stage | Transient input | Retained or forwarded output |
| --- | --- | --- |
| `dft_segment_io` / `dft_access_segments` | Bounded original JSONL bytes and agent for probe exclusion | Segment identity/byte cursor and timestamp/status counters; no record text, IP, agent or URI |
| `DftAccessCutover` | Production aggregates and existing unrelated-host feed | Empty DFT `sample_lines`; unrelated hosts retain their existing samples |
| Main proxy alert/dispatch builders | Selected access counters and sample list | No DFT access record from the new input can enter those sample fields |
| Checker / `DftJournal` / local outgoing intent | Bounded checker result | Fixed errors, age, historical overdue count, incident identity and immutable transition; no log content |

This source trace does not account for historical deployed copies. In
particular, the separate existing `nginx_upstream_errors` dispatch field still
originates from shared `error.log`; it is not supplied by the new hourly reader.
No historical delivery or original-age disposition is inferred from these
builders, and their other-site behavior is unchanged.
