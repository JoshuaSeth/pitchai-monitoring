# DFT monitoring consumer: source work in progress

This is the monitoring counterpart of existing Infrastructure request
`4e2c5d80` / DFT work `746ed086`. Monitoring specialist528 owns these consumer
modules;6f97 owns the writer and checker in DFT PR4478;2042/bb44 own DFT release
semantics;Infrastructure624 owns host admission and incident response. No
deployment, private directory creation, event publication or Telegram send is
part of this source change. Existing stopped workers remain stopped.

## Source contract and current implementation

Producer/checker revision: `15ae402ea589dea5a82e7a5d36eb84bbd6bd3576`, parent
writer correction `ca40adf82100c70659702d75e71ef003f81e7d1b`, DFT PR4478.
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

**Not commissioned:** the exact checker namespace, supported internal receiver
and off-host observer remain unallocated. The local outgoing intent is not yet
an accepted Events delivery envelope. It stays pending when no receiver is
supplied. Source tests do not establish installed configuration or delivery.

All 18 isolated standard-library tests pass (95.928 seconds). They use synthetic
child-process output, temporary
original files, private SQLite journals and in-memory receiver responses. They
cover large-hour bounded catch-up across restart, window/DST boundaries,
partial completion, identical requests, source cutover, process failures,
incident identity, acknowledgement and uncertain delivery ordering. No
production checker, retention file or notification endpoint is invoked.

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

Observed monitor UID/GID is0, nginx workers UID33. Approved design roots are
`/var/log/nginx/dft-access-v1/production` and `/staging`; private state is
`/var/lib/pitchai/dft-web-access-v1/status.json`. The original read-only nginx
mount supplies only the log namespace. The new directories are absent and the
container does not mount private state. Ancestor traversal, allocated config,
reviewed checker source and same-host/boot clock capability require explicit
rollout proof. No new principal/group or guessed SSH/Docker executor is supplied.
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

6f97 is separately implementing a guarded producer acknowledgement operation.
Until its exact revision is reviewed, the checker contract remains pinned to
`15ae402`. Producer acknowledgement never implies consumer recovery. The
consumer needs an explicit matching `acknowledged_incident_id` and a later
healthy checker plus complete access coverage. Restart, a new completion time,
warnings and historical cumulative counts alone cannot close an incident.

## Finite proposed rollout slice

1. Review the complete source and isolated proof, resolve the existing cycle
   module's strict-gate debt through scoped integration custody, and pass normal
   gates against staging. No validation-policy changes or deployment are part
   of this draft. Review the separate producer acknowledgement source when ready.
2.624 binds the existing failure route and independent off-host observer and
   admits the exact checker namespace. Verify config allocation, original clock
   age, source SHA, mount/read/search permissions and checker invocation without
   a synthetic production event or outgoing test.
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
