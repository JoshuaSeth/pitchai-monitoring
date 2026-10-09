# Registry completions for project managers

The legacy registry stores scheduled runs independently of the client hotpath
report registry. Its `dispatch_on_failure` setting is not an Events Bus delivery
receipt. This addition publishes original registry results through the existing
signed monitoring gateway without enabling incident dispatch or running probes.

## Capture and identity

`PITCHAI_REGISTRY_COMPLETION_SOURCES` is a JSON array of exact registry identities:

```json
[{"tenant_id":"00000000-0000-4000-8000-000000000001","test_id":"00000000-0000-4000-8000-000000000002"}]
```

The values above are documentation examples, not activation instructions.
Each pair must already exist in the registry. Engine tenant, project and manager
identities are separate and are resolved only by reviewed recipient rules.
Unknown keys, wildcards, noncanonical UUIDs and duplicate pairs are rejected.
An absent setting means no new capture. Removing a reviewed pair stops future
capture but retains original outbox obligations already committed.

Startup adds two tables and a trigger; it does not scan or replay old runs.
The real registry inserts a pending run as `infra_degraded` with
`error_kind=pending`. Its first completion captures the full result and artifacts
in the same transaction as the original update. Rollback removes both effects.
Run ID is the source deduplication key. Repeated completion updates do not
overwrite an already captured result. Optional runner timestamps stay optional.

The event kind is `registry_run_complete`. Results retain the registry tenant,
test and run IDs, status, original runner timestamps, error text, title, URL and
artifact references. Capture time is distinct from runner completion time.
Nothing in a result grants instructions, Engine ownership or outbound authority.

## Delivery and activation order

The outbox persists its signed payload before sending. A crashed sender or lost
receiver ACK reuses those exact bytes and delivery identity. A stale sender lease
cannot settle a newer lease. HTTP failure retains the original obligation.
HTTP work occurs outside the SQLite writer transaction.

Use the existing coordinated release owner, in this order:

1. Deploy the Events Bus receiver contract for
   `pitchai.monitoring.registry.run.completed`.
2. Install the reviewed manager rule, with exact authenticated source instance,
   environment and registry tenant/test relationships.
3. Deploy this producer and enable only those reviewed source pairs through the
   existing managed service configuration. Reuse the signed gateway configuration.
4. Observe a **natural future completion** through original outbox, Events Bus,
   native paired manager delivery and recipient consumption. Do not generate a
   probe, replay a historical failure or wake a stopped incident worker as proof.

The receiver's existing 128 KiB request limit remains effective. An oversized
result stays pending with a failed delivery; it is never truncated into success.
Receiver acceptance is durable event storage, not manager consumption or ACK.
Keep those acceptance stages separate in reports.

## Verification recorded on 4 October 2026

- Ten disposable producer tests passed, including the actual registry
  claim/completion writer, rollback, full content, exact tenant fencing, source
  removal, lost ACK, immutable retry, stale-lease rejection and the actual async
  sender's accepted and invalid-receipt paths.
- Seven configuration tests passed.
- All nine source-scoped static gates passed for the eight changed Python
  files. The tenth, repository-wide anti-bypass gate, remains red on 21 existing
  unrelated suppression sites. No suppression, rule or threshold was changed.
- Receiver and manager-rule acceptance are separate companion changes. No live
  configuration or original source event was changed by these tests.

The first hosted ratchet exposed an environment mismatch in the local static
proof: the locked quality environment lacked pytest and repository-root import
resolution. The companion quality configuration now pins pytest and resolves
the existing source root explicitly. Both lockfiles and the manifest/verifier/
workflow digest chain are updated together. No baseline, diagnostic severity,
exclusion, gate or threshold is relaxed. The corrected locked environment
reports zero type errors or warnings for the changed sources and passes all
eight ratchet contract tests. Full hosted ratchet acceptance remains separate
from these scoped results; this PR must not be treated as merge-ready from the
earlier enriched-environment proof alone.
