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

Reviewed producer revision: `3c543bd1d767a1cf57dc912a63eab523cfca17ba`, the
capacity-signal addition on path/install-manifest correction
`51b4a2eb6bc47463b1c3c31e328f70f06ee3a380`. The retained acknowledgement revision
is `6885e80032e02f9189b2b548c7a388eb951773d8`. The retained checker revision is
`15ae402ea589dea5a82e7a5d36eb84bbd6bd3576` and writer correction is
`ca40adf82100c70659702d75e71ef003f81e7d1b`, DFT PR4478.
The checker is `scripts/dft_access_log_status.py`; its output is fixed codes,
original heartbeat age and historical overdue count. Only a zero exit with
trusted age below900 seconds and no errors proves current health. Historical
counts are preserved and do not independently prohibit acknowledged recovery.

The capacity increment adds metadata-only accounting of allocated writer roots,
same-filesystem quarantine and private state. Its12GiB warning and16GiB budget
signals enter the existing failure latch. The unchanged checker maps current
status errors to `retention_run_failed` and an unresolved latch to
`retention_fault_latched`; both codes are already accepted by this consumer.
The three-field checker response, consumer invocation and recovery rules need no
functional change. Additional private status counters are not read directly by
the consumer and do not become incident payload fields. A clean capacity sample
or newly written status cannot acknowledge either producer or consumer incidents.

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
  Each invocation has its own process group. Cleanup terminates that group,
  discards output in bounded chunks and has a separate one-second deadline;
  an inherited stdout pipe cannot extend the ten-second observation deadline
  indefinitely. Cleanup failure remains an unhealthy fixed-code observation.
  Process creation precedes the observation deadline; these separate limits do
  not establish a universal eleven-second bound for a whole monitor cycle.
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
- `domain_checks/dft_journal_storage.py`: require an already allocated0700
  parent owned by the current principal and a0600 regular journal with one
  link. Reject symlink paths and unrelated SQLite files. New journals record
  the consumer application/schema identity in the initial transaction;
  existing identity is inspected read-only before a writable connection is
  opened. No directory creation, permission repair or implicit migration of
  unmarked state is performed.
- `domain_checks/dft_cycle.py` and the narrow `domain_checks.main` hook: the
  existing cycle reads the chosen feed, calls the checker, records content-free
  health and persists its transitions. Default configuration is disabled and
  allocates no journal or process. No receiver is configured by this patch.
  Each observation consumes a fresh access read; previous-cycle coverage cannot
  satisfy recovery when an access check is skipped.
  An allocated asynchronous receiver has a ten-second response deadline. A
  timed-out attempt remains uncertain, retains its exact delivery identity and
  bytes, and uses the journal's persisted retry backoff. Future receiver
  admission must verify cancellation and durable deduplication; a timeout cannot
  establish whether remote acceptance occurred.
- `domain_checks/dft_handoff.py` and `dft_cutover_config.py`: a requested
  segment selection initially retains shared authority. The existing cycle
  advances bounded candidate cursors after its checker call. It selects
  segments only after an actual complete original window and a healthy checker,
  with a successful shared read in that cycle. Selection is durable before the
  next read uses segments; a later segment fault never falls back automatically.
  Writer-adoption and natural old-worker-drain timestamps are explicit admission
  inputs. An active selection rejects changed timestamps on restart.

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
The private-journal increment passed nine affected tests in186.213 seconds:
unrelated-database refusal, unsafe alias/mode refusal, private reopen, durable
retry, bounded catch-up after restart, and the four cycle cases. These are
isolated source results; no existing runtime journal was opened or migrated.
The subsequent receiver-deadline increment passed six affected tests
in88.045 seconds, including an in-memory receiver that never replies until
explicitly released after restart. The original intent remains pending through
the deadline and is retried unchanged. No network receiver is used in that proof.
The bounded handoff increment passed13 affected isolated tests in73.218 seconds.
The added cases cover multi-poll cold catch-up across journal restart, a failed
checker preventing selection after parsing, original drain timing, skipped-read
refusal, durable selection without automatic fallback, explicit rollback
history, invalid boundaries and byte-preserving refusal of prior journal schema.
These fixtures exercise source behavior only; they do not prove actual writer
adoption, natural worker drain, runtime throughput or live delivery.

Numeric boundary validation also rejects integers too large for floating-point
conversion before attempting that conversion. A bounded malformed checker age
becomes `checker_age_unavailable`; malformed original event epochs remain
`invalid_segment_record`, and invalid admission times remain an allocation
refusal. The numeric regression reproduced four `OverflowError` failures before
the correction. Fourteen affected cases then passed in23.216 seconds, including
an actual synthetic local checker, journal restart and matching acknowledgement.
Malformed output preserves the same incident and immutable failed intent until
fresh healthy evidence; the eventual recovery cannot overtake that failed intent.
No real producer checker, retained status or delivery endpoint is used.

Two isolated inherited-pipe regressions reproduced a cleanup hang after an
observation timeout or oversized-response refusal: killing only the parent
left a descendant holding stdout open. The process-group cleanup correction
passed12 affected subprocess, numeric-evidence and cycle cases in41.138 seconds.
The new cases execute only synthetic children in temporary directories; existing
incident/restart/acknowledgement tests continue to require verified recovery.
No deployed checker or host process was invoked or terminated by that proof.
The final four-case checker suite passed13.552 seconds; after allowing the
synthetic descendant enough startup time, both inherited-pipe cases passed in
2.111 seconds. Initial selector, lint and fixture-startup failures remain in
the separate `checker-cleanup-20261002` evidence directory.

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
Producer3c543bd selects configuration `/etc/pitchai/dft-web-access-v1.json`
(root0600) and immutable tooling under
`/opt/pitchai/dft-web-access/releases/<full-reviewed-SHA>`. The exact new release
contains `scripts/__init__.py` plus seven modules including capacity; no `current`
link is proposed. The retained nginx mount does not establish access to those
configuration/tooling paths or host clock capability. The prior absence read
covered older candidate names and cannot establish absence of these targets.
The consumer journal requires its own admitted private path in the monitoring
state volume; it must not point at producer status/config or any access root.
Private ownership checks do not select that allocation or prove the runtime
principal. Existing unmarked consumer state would require a separately reviewed
migration; this source change refuses it and performs no migration.
No path is allocated or created by the default disabled configuration.
The selection-history addition uses consumer journal schema2. Schema1 or
unmarked files are refused byte-for-byte; this source supplies no migration,
state deletion or replacement allocation. No runtime consumer journal has been
commissioned by this work. An existing allocation would require its owner's
explicit preservation/migration disposition before using this version.

## Receiver and delivery limits

`docs/events-bus-delivery.md` records the existing internal webhook at
`https://pitchai.net/events-bus/webhooks/pitchai-monitoring`, signed durable
producer outbox, receiver dedupe and accepted receiver ID requirements. That
record does not identify an off-host availability observer or prove a DFT
retention signal is accepted. `docs/monitoring-service-health-contract.md`
describes same-host worker health/watchdog behavior, which does not survive a
Main outage. Existing Infrastructure624 is resolving the exact retained route
and off-host receiver; no new receiver or repair lane is commissioned here.

The October2 shared-monitoring records review reported no exact independent
off-host Main/service-monitoring checker plus receiver binding in its bounded
set: `monitoring/topology.yaml`, the daily runbook, PM7da76f88's October2
review, PM21dd29b5's six-role healthchecks, and
`docs/production-reverse-proxy-events-bus-watchdog-20261001.md`. That review was
recorded under PMf8aa and supplied to this existing746/4e2c5d80 work. This note
consumes that records-only finding without repeating host or log-body probes.

Those records establish Main's service-monitoring revision `a3dc66e`, a
same-host600-second completed-cycle watchdog and role healthchecks. The
`pitchai-events-bus.service` receiver is also on Main, at `127.0.0.1:8088` and
path `/events-bus/webhooks/pitchai-monitoring`; the retained October1 pressure
event disrupted that receiver itself. Natural proxy failure/recovery events
therefore do not prove delivery during a Main outage.

Still unbound are the off-host execution host, service, schedule and current
owner; an independent receiver and internal recipient; acceptance of the DFT
content-free stale/failure envelope; and natural host-failure/recovery receipts.
Daily-review private Telegram and82 delivered E2E publisher entries establish
neither this route nor its outage independence. This is absence of proof in
the reviewed records, not a claim that no checker exists elsewhere. It grants
no new receiver, event rule, schedule or external communication authority.

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
Infrastructure624 has explicitly assigned the necessary behavior-preserving
cycle decomposition to retained consumer owner528 on this same PR204 branch.
This clears the earlier source-scope uncertainty; it does not allocate runtime
paths or authorize deployment. Clean library checks do not override the failed
cycle-module gate. PR156 removes suppressions elsewhere and cannot repair
`main.py`'s whole-file requirement.

### First cycle decomposition increment

The initial source increment extracts three boundaries from the actual cycle:
`cycle_configuration.py` selects the same15 optional configuration sections;
`cycle_values.py` distinguishes required scalar conversion from existing
retained-state fallbacks; `alert_transition.py` retains the keyword-based
effective-health transition and tuple result used by all domain/metric callers.
Required invalid settings still raise; optional invalid thresholds remain
absent. Existing scalar conversion, boolean/default and nonfinite policies
are preserved. No new health policy is introduced by this extraction.

Nine focused tests pass. Differential comparison with
`4c97c085423ebace7d827cb494aa84b6661f767f` matches1600 health transitions,
180 section lookups and154 numeric/boolean cases. A separate syntax-tree check
confirms the rest of `main.py` is unchanged after accounting for the declared
imports, removed procedures and call substitutions. The DFT reader, checker,
incident, handoff and outgoing-intent implementations are unchanged.

Four new isolated real-launcher runs exercise these extracted boundaries through
config loading, consecutive cycles and persisted state. They verify default
config-path resolution using synthetic input, explicit string thresholds,
independent domains, one DOWN edge and a two-success recovery. The unaffected
domain stays healthy. DFT remains disabled without a checker or journal;
network/subprocess and outgoing-message guards record zero attempts and the
synthetic browser is closed after each run. This supplements, without repeating,
the independently accepted eight-run DFT launcher proof at4c97.

Exact raw source/test/gate evidence and reproducible proof tools are under
`/mnt/pitchai-dev-data/artifacts/monitoring-dft-746-20261002/cycle-config-extraction-20261002/`:
`tests-final.log`, `prove_extracted_boundaries.py` and its JSON result,
`check_integration_ast.py` and its JSON result, `prove_unrelated_launcher.py`
and its JSON result, `gates-focused-final.log` and `gates-changed-files.log`.
The six new modules/tests pass architecture, Ruff, BasedPyright, Pylint and
Semgrep checks. The canonical command still fails its repository-wide
anti-bypass check on21 existing findings. The remaining main module still
fails required quality checks; this is an intermediate source increment.

The current overlapping source patches are PR43/staging at
`8b286115e5c0d228e1cf37545145ccf09ca2adbb` (API-contract scheduling/alert
coordination) and PR45/main at
`cf98683cde25b32132170216518f64c0eebaaecd` (per-domain readiness policy and
persisted delivery receipts). Their owners and branches are preserved. The
overlap was reported to624 under central command
`ec924cdf-5074-4325-bfe4-f9bdd03a7d4e`; central acceptance is not substantive
owner acceptance. Their business behavior is not integrated by this increment.
Further cycle extraction must reconcile those interfaces before changing the
overlapping scheduling, alert-builder or event-persistence slices.

### Persisted-state decomposition increment

The next increment extracts `state_values.py` and `state_sections.py` from the
schema-six loader. The former decodes domain counters, address lists, bounded
event lists and signal histories from persisted JSON. The latter allocates
fresh defaults and normalizes health sections, including each probe family's
independent state. It preserves existing omission/fallback rules, duplicate
records, prefix limits, schema/version behavior and mutable-state ownership.
File I/O, legacy-state detection, event/outbox persistence, probe schedules and
the DFT modules remain unchanged. The main module is reduced by282 lines.

Nine new focused tests pass. Comparison with parent
`d53c7c470682ef2c6b9f829add1c87dc6715c4ce` matches352 collection decodes and874
complete loader cases, plus missing-file, directory and malformed-JSON cases.
Each state file's bytes remain unchanged. A syntax-tree comparison confirms
the remainder of main is identical after reversing the declared extraction.
Four isolated real-launcher runs pass in4.538 seconds with default/explicit
config resolution, persisted independent domain streaks, exactly one failure
and recovery transition, browser cleanup and zero outgoing attempts. These
exercise the changed restart boundary; the earlier DFT/nginx proofs are reused.

The four new modules/tests pass architecture, Ruff, BasedPyright, Pylint10/10
and Semgrep. The aggregate still fails on21 existing repository suppression
findings. Including the changed main module still fails:447 Ruff findings,
1504 typing errors/one warning, Pylint9.19/10,71 Semgrep findings and remaining
architecture violations. This is another intermediate source increment, not
integration or runtime acceptance. No gate or baseline is altered.

Exact evidence is under
`/mnt/pitchai-dev-data/artifacts/monitoring-dft-746-20261002/state-extraction-20261002/`:
`tests-final.log`, `prove_state_compatibility.py` and its JSON result,
`differential-initial.log`, `prove_unrelated_launcher.py` and its JSON result,
`launcher-proof.log`, `gates-final.log` and `gates-with-main.log`.
Earlier failed type/style iterations remain alongside the final proof.

### History and loader decomposition increment

The next increment completes the typed restart boundary. `history_decode.py`
normalizes persisted five-field samples; `history.py` retains append/insertion,
cutoff, availability, error-rate, latency and SLO calculations with explicit
types. `monitor_state.py` owns schema-six/legacy decoding, and
`state_storage.py` owns the actual JSON/file edge. Missing state remains silent;
malformed/unreadable state retains its warning and defaults without rewriting
input. Atomic writes keep the original sibling temporary path, sorted Unicode
JSON and replacement semantics. A failed replacement propagates and preserves
the current file. The broad read fallback is confined to that I/O boundary;
numeric decoding retains its existing narrow conversion fallbacks.

Main imports these boundaries through its original helper names. Its16 existing
package imports are now relative, resolving the same47 imported objects under
the actual launcher. No probe scheduling, threshold, alert-builder, event
persistence call site or DFT implementation changes. After reversing these
declared imports/extractions, the rest of main's syntax tree matches parent
`a70a62d23beaab823121eaa960d7d63b046617ac`. Main is reduced by another80 lines.

Twelve focused tests pass in0.104 seconds. Comparison with the committed parent
matches4470 history operations,598 complete loader cases and three atomic-write
byte comparisons. Four existing history/SLO/RED test functions also pass in the
isolated comparison process. The final four real launcher runs pass in1.348
seconds with default/explicit config, persistent independent domain health,
one failure/recovery pair, browser cleanup and zero outgoing attempts. DFT is
disabled in those synthetic runs; the earlier DFT/nginx proofs remain separate.
This is working-increment proof, not a separately repeated post-commit campaign.

All six scoped modules/tests pass architecture, Ruff, BasedPyright, Pylint10
and Semgrep. The repository aggregate still fails on21 existing suppressions.
With main included, the final local result remains failed:445 Ruff findings,
470 typing errors/one warning, Pylint9.24/10,69 Semgrep findings and remaining
architecture debt. Resolving imports exposes actual source types; no checks,
baselines, exclusions or diagnostic policy are changed.

Evidence is under
`/mnt/pitchai-dev-data/artifacts/monitoring-dft-746-20261002/history-extraction-20261002/`:
`tests-final.log`, `prove_history_compatibility_relative.py` and its JSON,
`differential-relative.log`, `prove_unrelated_launcher_relative.py` and its JSON,
`launcher-relative.log`, `package-import-proof.json`, `gates-focused-final.log`
and `gates-with-main-relative.log`. Earlier pre-import comparisons and failed
style iterations are retained. This source work does not allocate or verify any
live checker, reader, journal, receiver, off-host observer or admission window.

The five-file producer acknowledgement delta at `6885e8` is reviewed as source.
It requires the exact reviewed status digest, bound operations owner, retained
incident reference, existing expiry lock and a fresh trusted clean run. It
clears only the latch and adds acknowledgement metadata, preserving original
age, failure history and cumulative counts. The checker command and three-field
output remain unchanged; consumer invocation requires no functional change.
This review neither runs nor authorizes a live acknowledgement.

Producer correction `51b4a2e` is also reviewed as source. The exact Git diff
changes only `infra/dft-web-access/retention.example.json`,
`infra/dft-web-access/dft-web-access-retention.service` and
`docs/ops/dft_web_access_retention.md`. Configuration and unit each contain one
state-path substitution to `/var/log/nginx/dft-access-state-v1`; the runbook
describes that sibling and the immutable `scripts/__init__.py` plus all six
DFT access modules, including acknowledgement. Scripts and timer are unchanged.
The checker command, output contract and consumer invocation need no change.

Existing `d31-path-correction-receipt.json`, `d31-path-correction-source.patch`,
`d31-path-correction-focused.log`, `d31-path-correction-systemd.log` and
`d31-path-correction-commit-proof.txt` in6f97's evidence root were read. They
retain the focused JSON/disjoint-allocation, allowlist, manifest/AST and
systemd verification results; the systemd log is empty with recorded exit0.
No algorithm suite or service command was repeated. The existing746 entry at
14:45:49UTC records this producer delivery and remains intact. PR4478 is draft,
open against staging, with bb44 retaining integration. This review does not
install or relocate state, renew its allocation age, or satisfy checker/config/
clock/journal/receiver/off-host admission. Original requests remain unreplayed.

The subsequent five-file3c543bd producer delta and its existing raw receipts were
reviewed without rerunning producer/nginx tests. Its four new cases passed16.58s,
two affected regressions passed4.41s, and one corrected assertion case passed2.99s;
scoped gates and template/rendered systemd verification passed in the retained
producer proof. `d31-capacity-receipt.json` and
`d31-release-inputs-3c543bd-20261002/manifest.json` retain the exact15-file source
packet, rendered unit and earlier unchanged vhost candidates. Source/module
identities, checker schema and unit hardening remain distinct from installation.
The sparse threshold fixtures prove accounting boundaries, not physical capacity,
throughput or alert delivery. The4GiB margin still requires actual writer rate,
five-minute cadence, scan/response delay and host headroom evidence. It does not
authorize a quota, young-data deletion or disabling logs. No host path was probed
and neither capacity signal was emitted to a live receiver by this review.

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
   Use the existing-cycle handoff described below. DFT consumer authority and
   shared-feed exclusion change together; every other host retains its feed.
   Rollback must restore the shared DFT writer before selecting it and retain a
   coverage fault until its full window exists. Never delete or rotate old files
   to manufacture coverage or retention compliance.
4. Observe the installed source and content-free checker status through the
   existing cycle. Later natural incidents alone may establish live delivery.

### Bounded first-read handoff in the existing cycle

The producer's prepared `d31-release-inputs-51b4a2e-20261002/adoption-phases.md`
identifies why elapsed300 seconds alone cannot establish cutover readiness:
shared mode does not advance segment cursors, and a cold hour may require
multiple bounded reads. No separate warm-up command or schedule is introduced.

After actual dedicated writer adoption and natural drain of all retained old
nginx workers, the existing owner can prepare `mode: segments` with a `cutover`
mapping containing the original numeric epoch values `writer_adopted_at` and
`old_workers_drained_at`. These fields are claims that require owner evidence;
the consumer cannot verify nginx adoption or drain from inside its namespace.
The admitted interval must have remained uninterrupted. A reload completion,
master PID, copied status, restart or pre-created empty hour is not that evidence.

Until selection is recorded, reads continue using shared DFT counts, excluding
staging and probe traffic as before. Each successful shared read supplies one
candidate-read intent for the existing checker observation. The candidate
window must be at least300 seconds, and its start must be no earlier than both
admission timestamps. The reader advances at most the configured segment byte
budget per candidate poll, persists only validated counters/cursors, and retains
shared authority through incomplete catch-up, missing/invalid segments or a
failed checker. `segment_cutover_pending` remains explicit in consumer health
and cannot satisfy incident recovery. No zero-traffic fallback is manufactured.

After a complete candidate window and healthy checker, the journal commits
selection and the next access read uses segments with shared DFT exclusion.
The selecting observation can already report `active_access_source=segments`
while that cycle's counters came from its preceding shared read. Runtime
acceptance therefore requires the next successful access read/cycle under
selected segment authority, as6f97's retained eebc761 release addendum specifies.
That read revalidates the original files and advances the same cursors; it does
not reuse cached counters as current coverage without reading. Restart restores
selected authority only for the matching original admission. A later missing
or truncated segment is unavailable coverage, with no automatic shared fallback.

An explicitly admitted rollback uses `mode: shared`; its first successful shared
read retires the selection while retaining the original adoption, drain and
selection timestamps in the journal. This source does not itself establish that
the shared writer/window is intact. Re-adoption requires the owner's actual new
boundary and complete proof again. Retention incidents, acknowledgement history
and outgoing intents are independent of source selection and remain preserved.

The prepared producer still writes a shared raw-log copy. Consumer selection
does not remove that copy or satisfy its separate retention disposition.

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
# Host-health decomposition increment

The next source increment separates the existing host diagnostics into
`host_readings.py` (OS readings and CPU arithmetic), `host_snapshot.py`
(typed JSON assembly), and `host_thresholds.py` (thresholds and local alert
text). `main.py` imports the existing helper names; the remaining cycle AST
matches parent `7906fcea75f5e531fd43010112b86d9e02958998` after those declared
extractions. Main is now 4,763 lines, a further reduction of 289 lines.

The public valid-caller contract preserves the five keyword thresholds,
configured disk order, first-worst tie behavior, first CPU sample as baseline,
missing readings, percentage arithmetic, warning text and bounded lists. OS
read/encoding failures are handled at their I/O calls; numeric conversion is
separate from snapshot assembly. No new route, threshold or scheduling policy
is introduced. These modules remain in the complete canonical strict scope.

Evidence is retained at
`/mnt/pitchai-dev-data/artifacts/monitoring-dft-746-20261002/host-extraction-20261002/`:

- Eleven focused synthetic tests pass in 0.004 seconds. The differential tool
  matches 693 parent outcomes, including 128 snapshots, 128 read-order traces,
  128 sorted JSON byte comparisons, malformed fields, exact threshold equality,
  nonfinite retained values and alert text. Four existing host/performance
  cases also pass. No real host or network observations are needed.
- Four real isolated launcher/config/restart runs exercise simultaneous host
  and independent-domain two-failure/two-success transitions, persisted CPU
  baselines, signal history, default config lookup and browser cleanup. HTTP,
  browser and host inputs are synthetic. One host warning is captured by a
  replacement local function returning explicit no-delivery; actual Telegram,
  Events, Dispatch, network and subprocess transports are guarded. DFT stays
  disabled. No receiver IDs or delivery receipts are produced.
- Six runtime/test source files were copied and hashed before final unit,
  differential and launcher verification; final source is checked against that
  snapshot. This improves this increment's provenance without changing earlier
  increments' working-proof limits. The initial launcher fixture used the
  default `/` disk with mocked `statvfs` but did not separately mock existence;
  its proof is retained separately. The final fixture uses an explicit synthetic
  disk with synthetic existence and percentage observations.
- Five new files pass scoped architecture, Ruff, BasedPyright, Pylint 10 and
  Semgrep. Whole-main checks still fail: 415 Ruff findings, 437 typing errors
  and one warning, Pylint 9.25/10, 53 Semgrep findings and architecture debt.
  The aggregate retains 21 repository anti-bypass findings. Initial source and
  test-style gate failures remain in the evidence directory.

This is component source progress. It neither changes the retained DFT
producer nor supplies actual checker/config/clock/reader/journal bindings,
receiver acceptance, off-host coverage, original 300-second adoption/drain
coverage plus the next segment read, throughput/copy disposition or finite
Infrastructure624 admission. PR43/45 interfaces and original coordination
requests retain their separate owners and current status.

# Message-builder decomposition increment

Twenty-one existing pure builders now live in six canonical-scope modules:
`message_templates`, `message_tls_dns`, `message_slo_red`, `message_browser`,
`message_container` and `message_proxy`. Main retains their existing imported
helper names. This removes 512 lines from main, leaving 4,251. The remaining
main AST matches parent `89bc9b5e9048cbffa0d03346f900da84e4f01f82` after the
declared removals and imports. API-readiness builders and PR43/45 interfaces
are untouched. These helpers construct text only; routing, transport,
thresholds, scheduling and state transitions remain in the cycle.

Evidence is retained at
`/mnt/pitchai-dev-data/artifacts/monitoring-dft-746-20261003/messages-extraction-20261003/`:

- Seven focused tests pass. The differential tool matches 1,299 parent
  outcomes across all 21 builders, including 11 matching numeric exceptions,
  Unicode/JSON formatting, stable ordering, prefix limits and unchanged input
  objects. The eight runtime/test files match their pre-test byte snapshot.
- Four actual isolated launcher/config/restart runs preserve two-failure and
  two-success transitions for a domain, host health, TLS and DNS. Synthetic
  HTTP/browser/host/clock/metric inputs and replacement local text captures
  produce three warning strings, zero outbound attempts and no delivery
  receipts. DFT stays disabled; existing DFT launcher proof retains its scope.
- Two fixture failures are retained. The first patched an imported main
  namespace rather than the launcher's separate namespace; the audit guard
  blocked the attempted call. The second omitted an alertable metric domain
  and did not advance the scheduler clock. The final fixture patches source
  dependencies and uses an explicit synthetic metric domain and clock.
- All seven new files pass scoped architecture, Ruff, BasedPyright, Pylint 10
  and Semgrep. Whole-main gates still fail: 394 Ruff findings, 412 typing
  errors and one warning, Pylint 9.25/10, 53 Semgrep findings and architecture
  debt. The aggregate retains 21 repository anti-bypass findings. No policy,
  baseline or suppression changed.

The proxy builders preserve existing sample handling for unrelated feeds.
The new DFT path supplies content-free aggregates upstream; this extraction
does not resolve shared/error/Docker/historical copy disposition. Actual
checker/config/clock/reader/schema2 journal, receiver/off-host, original
300-second adoption/drain interval plus next selected read, throughput and
finite Infrastructure624 admission remain separate runtime dependencies.

# Performance decomposition increment

`performance.py` owns existing healthy-domain performance evaluation;
`message_performance.py` owns millisecond formatting and the two bounded
message builders. Main imports the four existing helper names. No scheduler,
transport, readiness interface or effective-health transition changes. Main
is 4,140 lines; its remaining AST matches parent
`7e7146d797e479e5c78ac6fab504c9689ef32ac2` after declared extraction/imports.

The JSON-valued input contract retains sorted domain keys, DOWN exclusion,
strict greater-than comparison, domain-specific overrides, independent HTTP
and browser observations and numeric override refusal. An exceeded threshold
that cannot be formatted still leaves that metric unavailable, preserving the
legacy behavior; another metric can independently retain a violation. Missing
and nonfinite display values remain `n/a`, with round-to-even for finite values.

Private proof:
`/mnt/pitchai-dev-data/artifacts/monitoring-dft-746-20261003/performance-extraction-20261003/`.
Six focused cases pass, alongside 685 parent outcomes (three matching
override exceptions), four existing host/performance cases and four actual
isolated launcher/config/restart cycles. The launcher preserves independent
domain and performance two-failure/two-success transitions, default config,
history and browser cleanup. It uses synthetic observations, one replacement
local warning capture, no outgoing attempts or receipt IDs, and DFT disabled.
The existing DFT and producer/nginx proofs were not repeated.

Three runtime files match their pre-test snapshots. Test-only style changes
have separate retained snapshots and reruns; no earlier snapshot or failed
gate log was overwritten. Three new files pass canonical scoped architecture,
Ruff, BasedPyright, Pylint 10 and Semgrep. The main-only run still fails with
382 Ruff findings, 388 typing errors and one warning, Pylint 9.15/10, 50
Semgrep findings and architecture debt. The repository aggregate still has
21 anti-bypass findings. Required gates remain binding; this is not runtime
or integration acceptance. All previously listed operational dependencies
and owner boundaries remain open and unchanged.

# Dispatch lifecycle decomposition increment

Twelve canonical-scope modules separate existing dispatch inputs, cooldowns,
bounded records, runner payloads, transport bindings, notices, failures,
results, workflow observation and domain/metric/probe callers. Main retains
the existing caller names and keyword interfaces. The remaining main AST
matches parent `f1b49cc4580c0ffac2afc0e89f384afe77c5cd16` after the declared
extractions and imports; main falls from 4,140 to 3,539 lines. The API-readiness
wrapper, its builders and PR43/45 scheduler interfaces remain unchanged.

`dispatch_workflow` observes one explicit child operation, handles ordinary
transport failures and propagates cancellation after child cleanup. Awaiting
the cancelled task itself retains the original child cancellation message.
The initial differential check caught that `gather` alone lost this message;
the failure and corrected proof are retained. Existing payload bytes, client
functions, audiences, quota/auth stops, 429 cooldown, notice intervals and
bounded history/event shapes are preserved. No route or executor is added.
Existing legacy `ok` records describe dispatch processing; even a returned
agent message with failed forwarding can retain `ok=true`. They are not
delivery evidence, and this extraction does not change the DFT outbox contract.

Private proof:
`/mnt/pitchai-dev-data/artifacts/monitoring-dft-746-20261003/dispatch-extraction-20261003/`.
All 15 runtime/test files have retained pre-test bytes. Eight focused tests
cover state, records, cancellation cleanup and failed notification handling.
The 33-case differential tool uses actual HTTP clients with in-memory
transports to compare parent/current requests, mutable records, errors,
cooldowns and all 13 route callers, including the unchanged API wrapper.
It separately checks runner payload bytes and the remaining main AST.

Five actual isolated launcher invocations cover four restart cycles plus a
continuous four-cycle dispatch-enabled run. They preserve independent domain
and performance two-failure/two-success transitions, default config lookup,
state and browser cleanup. The continuous run exercises the actual dispatch
client through six in-memory HTTP requests, persists one simulated completion,
and receives explicit no-delivery responses for both local notice requests.
Synthetic clock and cycle-sleep controls bound this fixture; they do not prove
real scheduling latency. DFT stays disabled, with no checker or journal.
One separate replacement text capture, zero outgoing network/subprocess
attempts and zero receiver receipts are recorded. The first launcher fixture
omitted the default-false performance dispatch setting; its failed expectation
and diagnostic run are retained before explicitly enabling the synthetic case.

All 14 new files pass scoped architecture, Ruff, BasedPyright, Pylint 10 and
Semgrep. Main-only checks still fail with 370 Ruff findings, 347 typing errors
and one warning, Pylint 9.15/10, 46 Semgrep findings and architecture debt.
The aggregate retains 21 anti-bypass findings. Initial test/gate iterations
remain separate; required gates, policy and baselines are unchanged. Existing
DFT/nginx campaigns were not repeated. The full cycle repair and previously
listed runtime bindings, receiver/off-host proof, copy disposition, original
adoption/drain coverage and finite Infrastructure624 admission remain open.

# Inventory and heartbeat decomposition increment

`config_values`, `domain_time` and `domain_entries` provide typed YAML-valued
inventory, expiry and timezone boundaries. They preserve raw mappings by
reference, explicit stops, expiry equality, supplied UTC offsets, existing
numeric/date distinctions, duplicate refusal and inventory-owned routing.
`domain_alerts` retains warning text and uses the same configured transport
callable. It introduces no audience or trigger. `heartbeat_message`,
`heartbeat_sections` and `heartbeat_external` assemble already observed data
with existing order, prefix limits, optional-value fallbacks and final newline.
No new external status request or schedule is introduced.

Main imports the existing helper names. Nine function removals and one class
extraction account for the complete change to its AST, apart from four added
imports; the rest matches parent `2bbbbf56ecc0628838ba0b0544b1927bf01f9b41`.
Main shrinks by 347 lines to 3,192. Fresh PR43/45 source reads confirm the same
retained heads and API readiness/event-persistence overlaps. Those sections,
branches and owners are untouched by this increment.

Private tools, original snapshots and raw logs are retained at
`/mnt/pitchai-dev-data/artifacts/monitoring-dft-746-20261003/inventory-heartbeat-extraction-20261003/`.
Nine focused tests pass in 0.002 seconds, and all five existing domain-disable
tests pass. The differential tool matches 612 parent outcomes, including
77 matching exceptions across three classes, raw mapping identity, no input
mutations, DST offsets, naive YAML dates, sorting and text prefixes. Two
separate routing cases preserve critical versus dashboard-only decisions
using a replacement local capture returning explicit no-delivery.

Four actual isolated launcher/config/restart runs pass in 0.770 seconds.
A timed-disabled domain begins checking exactly at expiry; an explicit stop
persists despite its elapsed timestamp. Independent ordinary domains and
performance retain two-failure/two-success transitions. Existing heartbeat
scheduling emits four local text captures, alongside one critical-domain
warning and one performance warning. All six are replacement-function
captures with no receipt IDs. HTTP, browser, host and clock inputs are
synthetic; outbound network, subprocess, Events, checker and dispatch paths
are guarded. Default config resolution, state history and browser cleanup
are exercised; DFT stays disabled and allocates no journal. This does not
repeat or expand the accepted DFT/nginx component proof.

Ten runtime/test files were snapshotted before final behavioral verification.
A subsequent test-only range/comprehension style correction has its own
before-run snapshot and focused rerun; all runtime bytes remain unchanged.
All nine new files pass scoped architecture, Ruff, BasedPyright, Pylint 10
and Semgrep. Initial source/test gate iterations remain retained. Whole-main
checks still fail: 325 Ruff findings, 291 typing errors and one warning,
Pylint 9.05/10, 37 Semgrep findings and architecture debt. The aggregate
retains 21 anti-bypass findings. These component passes do not override
required gates or finish the whole-cycle repair. Previously listed runtime,
receiver/off-host, copy/coverage and finite-admission dependencies remain open.

# Browser observation and launch option increment

`domain_observation` separates HTTP failure, explicit HTTP-only contracts,
browser absence, browser infrastructure failure and product browser failure.
Its typed `DomainProbes` carries the cycle's current HTTP/browser callables.
The public `main.check_one_domain` boundary still binds those callables at
each invocation, preserving the existing replacement seam. HTTP failure
retains its original details object; merged browser details keep precedence.
The browser semaphore still releases on failure and cancellation, and the
original cancellation exception propagates.

`browser_launch` builds fresh typed Chromium options, retaining argument
order, the original 512MiB boundary and omission of an absent executable.
The native launch, OS shared-memory read/fallback, retry state and cleanup
remain in the existing cycle. This introduces no browser or process wrapper,
runtime dependency installation or change to quality configuration. Two
function substitutions and two imports account for main's AST difference
from parent `4b35d2c1210edfcfd051ebac59cf6e42defdeb2c`. Main is 3,117 lines,
75 fewer. API readiness/event-persistence sections remain untouched.

Private raw proof and tools are at
`/mnt/pitchai-dev-data/artifacts/monitoring-dft-746-20261003/browser-observation-extraction-20261003/`.
Six focused tests pass in 0.041s; the existing browser-fallback test passes.
Parent comparison covers 240 observation combinations and 24 launch bundles
in 0.523s, plus identical launch RuntimeError and CancelledError propagation.
Four actual isolated launcher/config/restart runs pass in 1.741s with synthetic
HTTP/browser/clock inputs, including a browser-enabled domain after recovery.
Default configuration, state history, independent domain/performance
transitions, expiry/stops and cleanup remain covered. Six replacement text
captures have no delivery receipts; DFT remains disabled, with zero outgoing
network/subprocess attempts. Completed DFT/nginx proof is not repeated.

Five runtime/test files were snapshotted before final behavioral proof. One
test-only optional-key lookup has a separate snapshot and focused rerun; its
exact expected string and every runtime byte remain unchanged. Four new files
pass architecture, Ruff, BasedPyright, Pylint 10 and Semgrep. Initial interface,
dependency and test iterations are retained. Whole-main still fails with 325
Ruff findings, 293 typing errors and one warning, Pylint 9.04, 37 Semgrep
findings and architecture debt. Aggregate 21 anti-bypass findings remain.
No full-cycle or runtime completion is claimed; required checks and all
previous commissioning/admission dependencies remain open.

# Cycle history increment

`history_migration` converts retained observed history to effective health with
independent domain failure/recovery streaks. It preserves row order, original
timestamps and shallow extra values. `cycle_history` records current timings
against debounced health, retaining the existing optional numeric fallbacks and
backwards-clock insertion. `signal_history.SignalHistory` owns operations on
the cycle's existing map: append retains row identity and repeated legitimate
samples; pruning removes only the prefix before the first qualifying original
timestamp, including equality. Persistence and delivery remain in the cycle.

Against parent `5247e9157b53b1dd0b47862fae796de1d1269a0a`, AST restoration
accounts for the startup migration block, two nested signal helpers, the
per-cycle recording loop, three new imports and the removed unused
`append_sample` import. All remaining main AST is identical. Main is 3,023
lines, 94 fewer. Disabled-domain removal, migration error logging and the
existing SLO/RED inputs and prune ordering remain in place. API readiness and
event/outbox integration are unchanged.

Private raw proof and executable comparison/launcher tools are at
`/mnt/pitchai-dev-data/artifacts/monitoring-dft-746-20261003/cycle-history-extraction-20261003/`.
Fourteen tests pass in 0.001s (eight new and six existing history contracts).
Exact-parent comparison passes 800 migration, 40 append, 180 prune and 756
record cases in 0.725s. Its contract covers persisted JSON, list sample rows,
string keys and valid existing caller maps. It does not extend the old helper
contract to arbitrary Python objects.

Six isolated real launcher/config/state runs pass in 0.902s. Four retain the
independent domain/performance failure and two-success recovery sequence; two
additional runs seed observed history, verify one-time migration, restart
without remigration, cutoff equality, signal pruning and disabled-domain
removal. HTTP/browser/host/clock observations are synthetic. Eight local text
captures (six heartbeat, one critical, one performance) are explicitly unsent.
DFT remains disabled, no journal is allocated, and outbound/network/subprocess
guards record zero attempts. Prior DFT/nginx proof is not repeated.

Five runtime/test files were snapshotted before proof. A later unused main
import removal has its own snapshot and final comparison/launcher reruns; the
four new files are unchanged. All four pass scoped architecture, Ruff,
BasedPyright, Pylint 10 and Semgrep. The initial test annotation finding remains
in the raw logs. Whole-main remains failed: 314 Ruff findings, 279 typing errors
and one warning, Pylint 9.05, 33 Semgrep findings and architecture debt. The
aggregate retains 21 anti-bypass findings. Required checks, whole-cycle repair
and all retained runtime/receiver/coverage/copy/admission dependencies stay open.

# Metric configuration increment

`alert_settings` makes enablement, debounce and routing flags explicit.
`resource_settings`, `history_settings` and `network_settings` decode the
existing host/performance, SLO/RED and TLS/DNS sections. DNS drift policy is
separate from transport settings. Required integer failures, optional float
fallbacks, truthiness, metric-specific defaults and numeric minima remain.
Supplied rule lists and domain policy maps retain identity; default SLO rules
are fresh per load. Host path and resolver filtering retain their distinct
falsey-value behavior. Settings loading performs no observations or delivery.

Against parent `0b008e1b7ce2fd3c67eb5f6871acb6478bba9683`, six configuration
blocks, 73 subsequent name reads and three imports account for main's complete
AST change. All remaining AST is identical. Main is 2,937 lines, 86 fewer.
API-readiness configuration, scheduling, state, event/outbox and DFT authority
sections retain their existing control flow; no business branch was integrated.

Private raw proof and tools are at
`/mnt/pitchai-dev-data/artifacts/monitoring-dft-746-20261003/metric-settings-extraction-20261003/`.
Fourteen tests pass in 0.001s: eight settings tests and six existing section and
scalar contracts. Exact-parent comparison passes 1,769 JSON configuration cases
in 0.069s, including 476 matching exception classes and messages. It covers
competing invalid required fields, nonmapping sections, scalar/container
thresholds and original nonfinite float behavior. It does not establish an
arbitrary Python object contract.

Ten actual isolated launcher/config/state runs pass in 1.599s. Six retain the
domain/performance transition and history-migration/restart cases. Four also
enable host, TLS, DNS, SLO and RED with synthetic observations, proving each
recorded degradation and recovery and actual parsed DNS/TLS call arguments.
HTTP/browser/host/clock/TLS/DNS inputs remain substituted. Nineteen replacement
text captures, including ten heartbeats, are unsent. DFT stays disabled, with
no journal and zero guarded network/subprocess attempts. Prior DFT/nginx
commissioning proof was not repeated or expanded by these runs.

All six runtime/test files have unchanged pretest snapshots. Five new files
pass architecture, Ruff, BasedPyright, Pylint 10 and Semgrep (five targets).
Initial type, structure and test-style findings remain retained. Whole-main
still fails with 312 Ruff findings, 277 typing errors and one warning, Pylint
9.01, 33 Semgrep findings and architecture debt. Aggregate 21 anti-bypass
findings remain. Required checks and the whole-cycle repair stay incomplete;
all existing runtime, receiver/off-host, coverage/copy and admission gaps remain.

# Probe and heartbeat configuration increment

`browser_probe_settings` decodes synthetic and Web Vitals settings;
`service_settings` owns container and pipeline-health settings. `proxy_settings`
retains shared-feed paths, window/byte minima and proxy thresholds without
selecting a DFT source. `heartbeat_settings` validates enabled schedules and
preserves ordered duplicate times. Timezone resolution and clock sampling stay
in the cycle. Disabled malformed schedules remain ignored, while disabled
probes still parse their required numeric fields in the original order.
Container pattern lists retain identity and values for the existing matcher.
Whitespace path behavior, optional nonfinite limits and debounce defaults stay
unchanged. These settings modules perform no I/O.

Against parent `360719f3d24e777a4cb3c8a899432ffb2a9e9f77`, six configuration
blocks, 69 subsequent name reads and four imports account for the complete
main AST change. All remaining AST is identical. Main is 2,882 lines, 55 fewer.
API-readiness sections, DFT source selection, incident/outbox handling and
other domains' control flow retain their existing implementation.

Private proof tools and raw results are at
`/mnt/pitchai-dev-data/artifacts/monitoring-dft-746-20261003/probe-settings-extraction-20261003/`.
Sixteen tests pass in 0.002s: ten new settings tests and six existing section
and scalar contracts. Exact-parent comparison passes 2,328 JSON configuration
cases in 0.080s, including 937 matching exception classes and messages. Enabled
and disabled schedules, competing invalid numeric fields, list identity and
original nonfinite semantics are covered; arbitrary Python objects are not.

Four isolated real launcher/config/state runs pass in 1.226s. Each runs the
continuous cycle through post-meta persistence, then exits at a substituted
final sleep. Synthetic, Web Vitals, container, proxy and pipeline health all
retain their debounced failure and two-success recovery across restarts. The
proof checks parsed probe arguments, bounded shared-parser arguments, default
config resolution, heartbeat scheduling and browser cleanup. An unrelated
healthy domain remains healthy; a separate HTTP domain degrades and recovers.
HTTP/browser/container/log/clock inputs are synthetic. Ten local text captures,
including four heartbeats, are unsent. DFT stays disabled, no journal is
allocated and network/subprocess guards record zero attempts. Existing DFT
and nginx proof was not repeated.

All six runtime/test files match their pretest snapshots. Five new files pass
scoped architecture, Ruff, BasedPyright, Pylint 10 and Semgrep (five targets).
Initial type and test-format findings remain in the raw logs. Whole-main
still fails with 311 Ruff findings, 281 typing errors and one warning,
Pylint 8.95, 33 Semgrep findings and architecture debt. Aggregate 21 anti-bypass
findings remain. Whole-cycle repair and required checks remain unfinished;
existing checker/config/clock/reader/journal/receiver/off-host, original-window,
throughput/copy and finite-admission dependencies remain unchanged.

# Browser admission increment

`browser_admission.BrowserAdmission` owns the current native connection and
retains the cycle's scalar retry state. Connected handles bypass retry and
memory checks. Disconnected handles are closed before admission; low known
memory delays launch by 60 seconds without increasing the failure count.
Retry equality admits a launch. `browser_launch_boundary` records ordinary
native launch exceptions with the existing capped exponential delay and error
text. Cancellation remains distinct: cancellation during close retains the
handle for final cleanup, while cancellation after disconnected cleanup leaves
ownership cleared. Missing memory remains unknown; memory-reader failures
still propagate outside launch-error handling.

Native launch arguments and shared-memory observation remain in the original
`_launch_browser` function. Degraded notices, five-success recovery, final
cleanup, API-readiness and DFT control remain in the cycle. Against parent
`70157b1482e7b365b6d907d9cab06523aa906461`, one nested function, its connection
declaration, 16 name references and one import account for the complete main
AST change. Remaining AST is identical. Main is 2,830 lines, 52 fewer.

Private tools and raw proof are at
`/mnt/pitchai-dev-data/artifacts/monitoring-dft-746-20261003/browser-admission-extraction-20261003/`.
Eleven tests pass in 0.021s (eight new lifecycle tests and three existing launch
option tests), plus the existing browser-unavailable fallback case. Exact-parent
comparison passes 2,880 cases in 0.042s, including 1,020 matching exception
classes/messages. It checks returned identity, retained connection ownership,
state mutation and cleanup/probe order for the cycle's scalar state contract.

Five actual isolated launcher invocations cover ten cycles in 3.258s. Four
preserve independent domain and enabled-probe failure/two-success recovery.
The fifth runs six cycles through an initial launch failure, delayed retry,
one degraded notice and recovery only after five healthy cycles. It preserves
healthy HTTP results during browser unavailability. HTTP/browser/container/log,
memory and clock observations are synthetic. Fourteen local text captures,
including seven heartbeats, are unsent. DFT stays disabled with no journal and
zero guarded network/subprocess attempts; prior DFT/nginx proof is unchanged.

All four runtime/test files match their pretest snapshots. Three new files pass
scoped architecture, Ruff, BasedPyright, Pylint 10 and Semgrep. Initial native
launcher candidate, interface/style findings and the comparison fixture's
missing postponed annotations are retained separately from final proof.
Whole-main remains failed: 303 Ruff findings, 288 typing errors and one warning,
Pylint 8.93, 30 Semgrep findings and architecture debt. Aggregate 21 anti-bypass
findings remain. Required gates, whole-cycle repair and all existing operational
bindings and admission dependencies remain open.

# Scalar health state increment

`health_state.HealthState` owns one metric family's effective health and failure
and success streaks. Nine independent instances replace the duplicated scalar
groups for host health, performance, SLO, TLS, DNS, RED, containers, proxy and
meta monitoring. Restart decoding keeps the original boolean/integer rules;
each observation uses the existing debounce implementation. Snapshot creation
preserves the schema-six field names and values. Loading and saving do not
constitute healthy observations. Extra timestamps, CPU counters, DNS addresses,
container restart counts and write-failure counts stay with their current owners.

Against parent `1235e3d82d823700c4211d942b4bbdd17fae74b9`, independent AST reversal
accounts for nine initializers, nine loaders, nine snapshot trios, nine
transitions, 37 field references, one added import and one unused import removal.
The remaining main AST is identical. API-readiness, per-domain maps, DFT
coverage/outbox behavior, scheduling and cleanup remain outside this extraction.
Main is now 2,724 lines, 106 fewer than its parent; whole-cycle repair continues.

Private source snapshots, comparison tools and raw logs are at
`/mnt/pitchai-dev-data/artifacts/monitoring-dft-746-20261003/health-state-extraction-20261003/`.
Thirteen focused and existing tests pass in 0.001s. Comparisons with the nine
retained parent loader/transition blocks pass 24,696 restart cases and 6,912
observation cases in 0.152s. Their contract is persisted JSON/scalar state and
the cycle's typed alert settings, not arbitrary custom objects.

Eight real isolated launcher/config/state runs cover all nine families: four
metric runs in 0.785s and four probe runs in 0.929s. Each family retains DOWN and
two-success recovery across restarts, while CPU, DNS, timer and container
metadata survive. Domain state, stopped-domain exclusion, default config
resolution and final browser cleanup remain covered. HTTP/browser/host/log,
TLS/DNS and clock observations are synthetic. Twenty-one local text captures
include eight heartbeats; none is delivered. DFT is disabled with no journal and
zero guarded network/subprocess attempts. Earlier DFT/nginx proofs retain their
scope and were not repeated.

All three runtime/test files match the final pretest snapshots. Both new Python
files pass scoped architecture, Ruff, BasedPyright, Pylint 10 and Semgrep. Initial
test-style findings, the comparison fixture's indentation error and working
proof before unused-import/format cleanup remain in separate logs. Whole-main
checks still fail with 302 Ruff findings, 253 typing errors and one warning,
Pylint 8.91, 30 Semgrep findings and architecture debt; aggregate 21 anti-bypass
findings remain. Required checks and existing runtime/receiver/copy/admission
dependencies remain open. Validator 6f97's bounded `70157b1` acceptance is
retained separately; it does not extend to this newer increment.

# SLO and RED phase increment

`slo_phase` and `red_phase` now own their complete history-observation phases.
`HistoryFrame` carries the current history, original cycle time, event sink and
signal series. `HistoryHealth` preserves alertable-domain filtering, duplicate
violations, independent debounce and sample ordering. `CycleChannels` references
the existing client, configuration, records and active tasks; it preserves
message selection, response redaction and running-task ownership. It allocates
no route or replacement client. Calculation modules now expose typed inputs and
outcomes under the same strict scope, including original threshold equality,
window boundaries, sorting and caller-owned RED reason lists.

The ordinary computation-error path still logs the exception and evaluates the
existing empty result fallback. This preservation is not a new guarantee that
an SLO/RED calculation failure cannot advance recovery. Cancellation and other
base exceptions propagate. DFT's separate failure latch, owner acknowledgement,
fresh access token and checker requirements are unchanged.

Against parent `e49423903bdac0609120a74f861fd9cabc99622f`, AST reversal accounts
for two phase substitutions, one channel construction, an explicit event
argument adapter, eight removed imports and six added imports. Remaining main
AST is identical, including API-readiness, DFT, scheduling and cleanup. Main is
2,550 lines, 174 fewer than its parent.

Private tools, source snapshots and raw proof are at
`/mnt/pitchai-dev-data/artifacts/monitoring-dft-746-20261003/history-phase-extraction-20261003/`.
Eight focused/existing tests pass. Exact-parent algorithm comparisons pass 720
SLO and 1,620 RED cases in 0.049s, including 60 matching exception classes.
Malformed JSON numeric minima compare exception classes, not exception text;
the supported contract is persisted sample rows and JSON rules. Full old/new
phase comparison passes 488 cases in 1.677s: state, signal/event ordering,
unsent message bytes, dispatch arguments and object identity, active-task
retention, logs, ordinary exceptions and cancellation.

Four real isolated launcher/config/state runs pass in 2.732s. Their complete
recorded results match the retained parent launcher results, including six
metric families, per-domain state, DOWN/two-success recovery, default config
resolution and final browser cleanup. Eleven local text captures include four
heartbeats; all are unsent. HTTP/browser/host/TLS/DNS/clock inputs are synthetic,
DFT is disabled, no journal is allocated and guarded network/subprocess attempts
are zero. Phase and launcher proof preceded the final snapshot; final focused
and algorithm proof followed it. The byte manifest binds both to the committed
increment; this is not a second post-commit execution campaign.

Eight changed/new Python modules pass scoped architecture, Ruff, BasedPyright,
Pylint 10 and Semgrep. Initial typing, interface, test-style and redundant numeric
conversion findings remain in their original logs. Whole-main and aggregate
gates remain failed; no policy, suppression, baseline or exclusion was changed.
Required hosted gates and whole-cycle repair remain outstanding.

The additive 624 transition condition is already implemented by the retained
`dft_handoff.DftHandoff` path. A request for segments starts with shared
authority. Each successful shared read supplies one bounded candidate-read
intent to the existing checker observation. Candidate parsing advances durable
device/inode/byte cursors over multiple cycles; incomplete coverage leaves the
shared feed authoritative. Selection requires a complete original interval of
at least 300 seconds starting after both writer adoption and natural old-worker
drain, plus the bound healthy checker and fresh access token. The journal records
selection before the in-memory switch. The selecting observation still has
shared counters; the next successful selected read establishes segment parsing
and shared-DFT exclusion. No separate warm-up command, forced drain, empty-hour
coverage assumption, automatic fallback or incident acknowledgement is added.

Reuse the original `cutover-handoff-20261002` proof and eight-run
`launcher-cycle-20261002` proof beneath the October 2 owner artifact root.
Elapsed time alone is insufficient. Shared production raw-log output remains
a separate retention/copy-lineage residual after selection. Actual checker,
source/config/clock/reader permissions, schema-two private journal, accepted
internal receiver/off-host observer, throughput/copy disposition and a fresh
finite 624 admission remain unbound. Producer `3c543bd`, original requests,
existing owners and all human stops are unchanged.

# Host phase and continuing release repair

`HostPhase` owns the existing host observation, health transition, signal,
event and dispatch order. `HostObservations` retains CPU baselines and the
shallow dashboard snapshot. A failed second CPU conversion preserves the
first assignment, as before. Send failures and cancellation retain state
already observed; neither constitutes recovery. API-readiness, DFT, scheduling
and cleanup remain unchanged by this extraction.

Private evidence is in
`/mnt/pitchai-dev-data/artifacts/monitoring-dft-746-20261003/host-phase-extraction-20261003/`.
Seventeen focused/existing tests, 964 parent comparisons and four isolated
launcher runs pass. Launcher results equal the retained parent baseline;
eleven local texts (four heartbeats) are unsent, with DFT disabled and zero
guarded network/subprocess attempts. Final snapshots precede final tests and
launcher proof. Earlier differential proof is bound by unchanged runtime bytes.
Three new files pass scoped checks. Main remains failed: 257 Ruff findings,
229 typing errors and one warning, 25 Semgrep findings and architecture debt.
The repository's 21 anti-bypass findings remain visible.

The release objective includes deployed controls through the normal gates.
Source evidence alone does not fulfill it. Remaining cycle repair and required
checks, actual checker/config/clock/reader/journal, accepted internal receiver
and off-host observation, copy disposition and a coordinated finite 624 host
transaction remain necessary. Producer bytes and original request identities
are preserved. No runtime activation occurred in this increment.

# Performance, TLS and DNS cycle phases

`PerformancePhase`, `TlsPhase` and `DnsPhase` now own their observations and
health transitions. `ProbeFrame` shares the existing channels, inventory policy,
event sink and signal history; `ProbeSchedule` preserves attempt timestamps
before asynchronous work. DNS baseline updates precede routing, including muted
domains. Failure and cancellation retain the same state and effect ordering.
The remaining main AST is unchanged after the recorded substitutions.

Evidence is retained at
`/mnt/pitchai-dev-data/artifacts/monitoring-dft-746-20261003/network-phases-extraction-20261003/`.
Thirteen affected tests and 1,392 parent comparisons pass. Four real isolated
launcher runs match the parent's complete recorded results, including default
configuration, persisted restart state and two-success recovery. Eleven local
texts, including four heartbeats, are unsent. DFT is disabled; no journal,
receiver or deployed permission is exercised. Initial fixture and gate failures
remain in the packet. The final protocol declaration follows the launcher run;
its implementation-independent declarations do not alter probe algorithms.

Six changed/new modules pass scoped gates. Main remains failed: 220 Ruff,
213 typing errors and one warning, Pylint 8.83, architecture and Semgrep debt.
The aggregate 21 anti-bypass findings and required whole-file ratchet remain
visible. This work continues the release repair; it is not installed delivery.

# Container, proxy and pipeline-health cycle phases

`ContainerPhase`, `ProxyReader`/`ProxyPhase` and `MetaPhase` now isolate the
remaining shared service observations and their existing transition ordering.
The proxy reader delegates access coverage and source ownership to `DftCycle`.
An unavailable access window still prevents recovery from a degraded proxy
state. Container inspection failure preserves the previous restart baseline;
cancellation advances the attempted timestamp without inventing health.
Pipeline timing remains after ordinary persistence and before the final write
and sleep. Browser connectivity is sampled only for an admitted dispatch.

The legacy header checker now uses its package-relative import and explicit
JSON types. Its primary/backup classification and sorted output are preserved
over 581 parent comparisons. Existing shared-error samples remain a separate
copy-lineage obligation; this extraction adds no deletion or new route.

Evidence is at
`/mnt/pitchai-dev-data/artifacts/monitoring-dft-746-20261003/service-phases-extraction-20261003/`.
Twelve affected tests and 864 complete phase comparisons pass. Four unrelated
domain/metric launcher runs match the parent's complete results, with eleven
unsent local captures and no outgoing attempts. The changed proxy call site
also passes the existing eight-scenario DFT launcher tool against current
working bytes: real local parser/checker subprocess/schema-two journal with
synthetic inputs, shared selection counters followed by next-read segment
authority, and acknowledgement plus fresh checker/access recovery. No receiver
is allocated; both synthetic outbox intents remain unattempted. This is neither
installed producer/checker proof nor a natural delivery receipt.

Six modules pass scoped checks. Main is reduced to 1,723 lines but still has
172 Ruff findings, 194 typing errors plus one warning, Pylint 8.86 and remaining
architecture/Semgrep debt. The 21 aggregate findings remain. Required whole-file
repair continues. The fresh 624 read timed out; the retained additive binding
request remains separate from acceptance and finite runtime admission.

# Browser observation phases

`SyntheticPhase` and `VitalsPhase` use the original per-domain maps and the
native probes supplied by the real launcher. Typed input records preserve the
keyword arguments, browser ownership, timestamps and least-recent attempt
ordering. Infrastructure failures retain their different existing behavior:
synthetic transactions filter them before evaluating health, whereas Vitals
skips its health observation. Domain policy still governs warnings and
dispatch, including unsent transport results. No additional route is created.

The protected `browser-phases-extraction-20261003` directory alongside the
preceding proof contains nine affected tests, 924 parent phase comparisons,
2,160 metric/override comparisons and four actual launcher/config/restart runs.
The launcher uses synthetic observations, enables both browser metric families
and retains unrelated domain transitions. Its seventeen local text captures
include four heartbeats; no network/subprocess attempts or delivery receipts
exist. DFT is disabled in this launcher fixture; the preceding eight-run DFT
proof remains separate. Initial interface/style findings and a fixture that
expected recovery text without enabling recovery notifications are retained.

Six new Python files pass all scoped checks; the aggregate 21 findings remain.
Main still fails with 142 Ruff findings, 180 typing errors plus one warning,
Pylint 8.88, fifteen Semgrep findings and architecture debt. PR43 and PR45 retain
their original open heads and overlapping API-contract slices. Whole-cycle
repair, required integration checks and the actual runtime bindings remain
open. Neither this source result nor local captures establish delivery.

# Heartbeat cycle boundary

`HeartbeatPhase` preserves the configured time order, inclusive start/exclusive
tolerance window and existing daily sent map. The optional registry API has an
explicit observation boundary: ordinary failures become the existing summary
diagnostic; cancellation propagates. An unsent transport response retains the
existing processing/dedup behavior and is not delivery evidence. A failed or
cancelled transport does not mark the scheduled heartbeat processed.

The protected `heartbeat-phase-extraction-20261003` packet contains seven focused
tests, 1,944 comparisons with the retained parent block (285 matching failures)
and four actual launcher/config/restart runs. The remainder of main's AST is
unchanged after the declared substitution. Launcher observations are synthetic,
DFT is disabled, and seventeen local unsent captures include four heartbeats;
there are no outgoing attempts or receiver receipts. Initial assertion-fixture
and test-boundary gate failures are retained. The final unit tests substitute
the HTTP boundary; they do not establish an installed registry connection.

Both new files pass scoped checks. Aggregate 21 findings remain, and main still
fails with 140 Ruff findings, 179 typing errors plus one warning, Pylint 8.87,
fourteen Semgrep findings and architecture debt. This is another part of the
authorized whole-cycle repair, not release acceptance or runtime admission.

# Browser recovery cycle boundary

`BrowserRecoveryPhase` retains pre-transition sampling, throttled notice order,
timestamp persistence before browser restart, and five healthy cycles before
recovery. The browser admission object still owns the handle. An ordinary close
failure allows another admission attempt; cancellation preserves the handle and
propagates. Payload construction and the current write-failure counter remain
with the owning cycle, including event-triggered writes before the immediate
notice write. No new transport, route or automatic incident reset is added.

The `browser-recovery-extraction-20261003` packet contains four focused tests,
528 complete parent comparisons (152 matching failures/cancellations), and five
real isolated launcher runs. Four launcher results equal the parent after JSON
serialization. The fifth injects a browser infrastructure fault and observes
the saved notice timestamp and event before close/restart. All nineteen local
captures are unsent; five are heartbeats. DFT is disabled in these fixtures.
Initial fixture comparison and guarded host-observation failures remain in the
packet; the host read was blocked before data access and then substituted.

Both new files pass scoped checks. The aggregate 21 findings remain. Main still
fails with 127 Ruff findings, 176 typing errors plus one warning, Pylint 8.85,
thirteen Semgrep findings and architecture debt. Whole-cycle repair and actual
DFT runtime bindings remain open. The 11:30 supported self read reports
Astra/xhigh and no lane stop; the Infrastructure detail read timed out. The
existing binding request and source-interface coordination are not replayed.
# Native domain polling and completed dispatch ownership

The existing domain semaphore now owns `DomainPolling.run`; it samples the
current browser only after admission, returns the original observation object,
and keeps ordinary check crashes distinct from cancellation. `CycleChannels`
consumes completed dispatch results in the original snapshot order. A cancelled
task remains owned and interrupts pruning before later entries, as before.

Protected evidence is in
`/mnt/pitchai-dev-data/artifacts/monitoring-dft-746-20261003/domain-polling-extraction-20261003/`.
Four focused tests pass (0.057s), ten native-signature parent comparisons pass
(0.015s, four error/cancellation cases), and five isolated native launcher runs
pass (1.527s). The complete launcher results equal the retained parent,
including persistence before browser restart. Nineteen local text captures,
including five heartbeats, are explicitly unsent. DFT is disabled in this proof;
the earlier dedicated DFT evidence retains its separate scope. Declared source
substitutions restore the remaining parent `main.py` AST exactly.

Three component files pass the canonical scoped checks. Aggregate anti-bypass
debt and the remaining whole-main failures remain release work. This increment
does not establish installed checker/reader/journal, receiver, off-host coverage,
or runtime admission.
# Per-domain result phase

`DomainResultPhase` owns the existing per-domain debounce edge, bounded event,
inventory routing and investigation task reference. It updates the same three
persisted mappings before effects. It preserves the distinction between an
explicitly unsent response and a failed or cancelled transport, retains running
investigation tasks, and leaves unknown inventory failures loud. Enrichment
does not mutate the original observation. No route or audience was added.

The protected `domain-result-phase-20261003` packet under the October 3
`monitoring-dft-746` artifact root records seven final focused tests (0.149s),
1,152 parent comparisons (1.964s, 224 matching failure/cancellation cases), and
five real isolated launcher runs (2.724s). All complete launcher results equal
the previous source. Inputs are synthetic; nineteen local text captures,
including five heartbeats, are unsent. DFT is disabled in these launcher cases.
The declared substitutions restore the complete remaining parent-main AST.
The test-only keyword correction is separately snapshotted and rerun; prior
proof and the initial strict-style finding remain recorded.

Both new files pass scoped strict checks. Whole-main still fails with 120 Ruff
findings, 180 typing errors plus one warning, Pylint 8.78, eleven Semgrep
findings and architecture debt. Aggregate 21 findings remain. Existing source
interface and runtime binding requests are retained; no integration, runtime
admission, installed receiver or delivery is established by this source proof.
# Retained main import compatibility

The whole-cycle review found a concrete collection failure: the existing
`tests/test_host_and_performance_checks.py` still imports host/performance
collectors from `main.py`. Those aliases are restored to their extracted owners.
The explicit export list also retains the domain-entry adapter and disable-time
parser used by current repository callers. Thirty-two unused imports with no
retained caller are removed; import ordering is normalized. Runtime function
bodies and all other non-import AST are unchanged.

The protected `main-compatibility-20261003` packet retains the pre-fix ImportError,
complete before/final source, import inventory, AST comparison and final proof.
The twelve existing host/performance, disabling, alert-state and browser-fallback
tests pass in 0.80s after the final source snapshot. No new synthetic campaign,
host probe or delivery was needed for this import correction.

Whole-main remains failed: 84 Ruff findings, 144 typing errors plus one warning,
Pylint 9.11, eleven Semgrep findings and architecture debt. Repository aggregate
21 findings remain. This fixes a supported import contract; it is not a waiver
of the changed-file policy or an integration/runtime acceptance.

# Cycle restart state

`CycleHealthState` restores independent health sections, original attempt times,
CPU and DNS baselines, container restart counts and the three per-domain probe
maps. Snapshot construction reads those same phase-owned objects. `browser_state`
keeps degradation/notice ages and bounded failure evidence across restart while
resetting only the existing process-local retry counters. Malformed first-seen
time retains its zero fallback; malformed last-notice time still fails startup.
No schema, file allocation, API-readiness logic or event delivery policy changed.

Protected evidence is under the October 3 `monitoring-dft-746` artifact root in
`cycle-state-20261003`. Ten final focused tests pass (0.003s), including actual
isolated atomic state write/read and two-success recovery across restart. The
parent comparisons cover 6,480 health-state cases (0.825s) and 10,648 browser
cases (0.524s, 968 matching error classes). Five native launcher/config/restart
runs pass (1.741s); all results match the retained baseline, including notice
persistence before browser restart. Nineteen local texts, including five
heartbeats, are unsent. DFT is disabled in these launcher cases. Final pretest
bytes and declared full-main AST substitutions are retained. Initial fixture
and strict-style failures remain in the packet.

The four new files pass their scoped canonical gates. Whole-main still fails:
81 Ruff findings, 92 typing errors plus one warning, Pylint 9.03, nine Semgrep
findings and architecture debt. Aggregate 21 anti-bypass findings remain. The
existing whole-cycle source repair and required runtime bindings continue;
these restart proofs do not establish installed delivery or ingress admission.
# Startup boundary follow-through (2026-10-03)

The existing cycle now reads cadence/concurrency, channel configuration and the
optional registry heartbeat through `cycle_startup`. Telegram validation still
precedes Events configuration, and a missing dispatch token retains the same
disabled state. Credentials, audience, environment precedence and empty registry
overrides are unchanged. This loading path performs no delivery.

Protected local proof is in
`/mnt/pitchai-dev-data/artifacts/monitoring-dft-746-20261003/cycle-startup-20261003/`:
seven focused tests pass; five actual isolated launcher/config/restart runs
match the retained parent results (5.300 seconds). Nineteen local text captures
include five heartbeats, all unsent; DFT is disabled and guarded outgoing
attempts are zero. The two new files pass scoped static checks. The repository's
21 anti-bypass findings and the remaining whole-main debt remain open. The
initial assertion/typing fixture failures are retained. This is source proof;
installed checker, journal, receiver and finite admission remain outstanding.
