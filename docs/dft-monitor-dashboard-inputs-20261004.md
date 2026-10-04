# Dashboard input boundaries in PR204

The retained task746 source allocation covers the registry app and dashboard.
This increment separates snapshot IO, scalar/sampling rules and inventory
normalization from summary calculations. All three modules remain under the
unchanged canonical strict gate. The remaining dashboard calculations and
registry app still need repair; this is not whole-file or release acceptance.

`dashboard_data.py` retains the six-field frozen `MonitorData` dataclass and the
state-then-config load order. It normalizes history before determining the
display error, including the original behavior where inserted empty history
prevents a missing-state message. Ordinary file/decoder failures retain the
display-only empty fallback. This does not replace the monitor startup loader
or introduce a new healthy-state claim. Reads do not write input files.

`dashboard_values.py` retains numeric conversion, positive/ISO timestamp and
UTC semantics, range aliases, endpoint-only history bounds and stride sampling
with the original last-object identity check. Scalar contracts cover JSON/YAML
primitive/container values; arbitrary user-defined conversion objects are not
claimed. `dashboard_inventory.py` normalizes every domain before deduplication,
so an invalid policy on a later duplicate still fails. The first domain entry,
group sorting, disablement and policy semantics remain intact. Existing public
and used private import names remain available from `monitor_dashboard.py`.

The parent is42075f43da82e1f0dbcccac6f5cb9bbe7bd74ae2. Protected local evidence is
`/mnt/pitchai-dev-data/artifacts/monitoring-dft-746-20261004/`.
`dashboard_input_compatibility.py` and its retained parent compare1288 cases:
81 scalar,168 inventory,27 group,210 sampling,21 range,529 history-bound,
216 complete synthetic summaries and36 file-loading cases. All returned values
and exception classes/messages match for these inputs; callers remain unchanged.
The15 remaining dashboard definitions have identical ASTs. The proof records
zero network/child attempts and removes its owned synthetic directory.

Six focused tests also exercise immutable snapshot fields, byte/mtime
preservation, YAML dates, error precedence, invalid policy duplicates, numeric
boundaries and sampling identity. The three existing dashboard summary tests
pass; the analyzer environment reports the existing unknown `asyncio_mode`
pytest option warning. No browser, registry service, receiver or production
snapshot was used. Failed gate iterations are retained alongside final proof.

The registry duplicate fingerprint
`ff9e04e9c09c8a98a323018724c065f3fcc0568a2324370011e9028e41590be0`
belongs to the app/dashboard disabled-until parser participant pair. The
42075f4 full report no longer contains that fingerprint after the earlier shared
`disablement.py` repair. Its absence does not erase remaining app/dashboard
diagnostics. That exact report still fails with6223 violation occurrences;
both hosted integrity checks pass and both required ratchet checks fail.

Producer ee5796f/runtime10cc, original owner requests, PR214 completion custody,
paused127/PR156/157 and runtime admission boundaries remain separate. The
checker/config/clock/reader/schema2 journal, internal/off-host receiver,
throughput/copy disposition and finite624 transaction remain unaccepted.
Cutover still requires the original300 seconds after writer adoption and
natural old-worker drain, durable selection and the next successful segment
read. Matching acknowledgement and fresh checker/access health remain necessary.
