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
  coverage checks, bounded reads, no symlink traversal, and cross-cycle metadata
  checks for replacement/truncation. No content is persisted.
- `domain_checks/dft_access_segments.py`: production-root counters, probe-UA
  exclusion, complete-line parsing and original event-time filtering. Repeated
  polls recompute the window; they never add a second copy of its counters.
  Equal records at distinct byte positions remain separate requests.
- `domain_checks/dft_checker_process.py`: proposed bounded local invocation of
  the producer-owned checker. It neither provides a remote executor nor makes
  private state or host clock services accessible inside a container.
- `domain_checks/dft_retention_consumer.py`: sanitized observations and incident
  identity transitions. The caller must persist the identity before delivery.
  A warning cannot close it; owner acknowledgement and verified healthy proof
  are both required. This pure model is not durable delivery by itself.

**Not yet connected:** the existing60-second cycle, explicit shared/segment
feed selection, persisted incident/outbox state, and supported internal route.
These libraries are not a commissioned monitor and must not be deployed as if
they were. Source tests do not establish installed configuration or delivery.

Isolated validation uses11 standard-library test methods, including tables of
failure cases and synthetic child-process output. No production checker,
retention files or notification endpoint is invoked. These tests cover the
library contracts; they do not yet prove the cycle or durable delivery adapter.

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
Staging's parser differs; a later source integration must preserve the deployed
semantics instead of treating a filename replacement as an adapter.

Observed monitor UID/GID is0, nginx workers UID33. Approved design roots are
`/var/log/nginx/dft-access-v1/production` and `/staging`; private state is
`/var/lib/pitchai/dft-web-access-v1/status.json`. The original read-only nginx
mount supplies only the log namespace. The new directories are absent and the
container does not mount private state. Ancestor traversal, allocated config,
reviewed checker source and same-host/boot clock capability require explicit
rollout proof. No new principal/group or guessed SSH/Docker executor is supplied.

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

## Finite proposed rollout slice

1. Complete source integration and isolated tests for production-only selection,
   unrelated-host preservation, shared/new duplicate avoidance, checker failures,
   durable restart/retry behavior and acknowledged recovery. Pass normal gates
   against staging; no validation-policy changes.
2.624 binds the existing failure route and independent off-host observer and
   admits the exact checker namespace. Verify config allocation, original clock
   age, source SHA, mount/read/search permissions and checker invocation without
   a synthetic production event or outgoing test.
3. Verify sufficient original segment coverage for a complete300-second window.
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
