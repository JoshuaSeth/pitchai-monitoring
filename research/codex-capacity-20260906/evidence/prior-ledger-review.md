# Independent reconciliation with the September 4 cost study

The earlier ledger contains 244,113 logical turns. Of these, 119,835 have a modern turn identifier and complete nonnegative input, cached-input, output and reasoning-output counters. Another 105,094 modern turns have unavailable or invalid numeric tuples, and 19,184 legacy rows lack a modern turn identifier. These exclusions are explicit; they are not zero consumption.

The comparison hashes the prior raw turn identifier with SHA256 and joins it to the current hashed turn. Current call events are restricted to timestamps strictly before the prior snapshot cutoff, September 4, 2026 at 12:03:50 UTC. Three scopes remain separate: the prior selected source path, every current candidate, and current replay-corrected calls across sources.

| Scope | Exact agreement on all four counters | Current higher | Current lower | Mixed differences | No current calls, prior zero | No current calls, prior nonzero |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Prior selected source | 104,536 | 75 | 50 | 0 | 15,072 | 102 |
| Every current candidate | 91,994 | 12,625 | 41 | 4 | 15,072 | 99 |
| Replay corrected | 104,505 | 108 | 51 | 0 | 15,072 | 99 |

Thus 104,505 of the 104,664 turns with current calls agree exactly after replay correction (99.848%). This is an independent counter comparison, not proof of live execution, complete workload coverage or paid subscription value. The prior integrity flags remain material: **689 exactly matching turns are still flagged by the earlier study**. Agreement does not rehabilitate them.

The uncorrected scope has 12,625 componentwise-higher turns; replay correction reduces that count to 108. Of those 108, 84 were already marked completion-pending or missing in the earlier export. Five were marked crashed and 19 completed. The remaining discrepancies must not be interpreted as quota changes. The retained JSON groups them by source class, token confidence, control-summary status and turn status. Those labels describe the earlier ledger's evidence; they do not prove a cause for every difference.

All **99 nonzero turns with no current call coverage** belong to the earlier main-cell export: 94 began in July and five in June. Their 23 selected source-path hashes all match `FileNotFoundError` records in the current source-header inventory. Their earlier totals are 237,126,964 input tokens, including 219,932,672 cached input, and 1,129,157 output tokens, including 113,991 reasoning output. The prior aggregates survive, but the current call-level/account-window analysis cannot recover those missing records from them. They are not silently added to account totals.

The source-loss check takes the set of distinct current `calls.turn` values before the same cutoff, hashes each prior modern `turn_id`, and selects nonzero prior turns absent from that set. It then matches `canonical_source_sha256` to the `source` field of `source_header` records in both retained source-header exports. It reads no prompt, response or private account identity. The prior source hash is SHA256 of its selected source path, which is compatible with the current header export's hash.

Reproduce the main comparison with Python 3.12 or newer:

```bash
python3 research/codex-capacity-20260906/reconcile_prior_ledger.py \
  --prior /code/pitchai-cli-new/runs/historical-rollout-cost-ledger/2026-09-04/turn_ledger.csv.gz \
  --joined /mnt/pitchai-dev-data/codex-capacity-20260906/joined-calls.sqlite3 \
  --replay /mnt/pitchai-dev-data/codex-capacity-20260906/replay-audit-v2.sqlite3 \
  --cutoff 2026-09-04T12:03:50Z \
  --output NEW_RECONCILIATION_JSON
```

The JSON records the prior compressed CSV's SHA256. Extending the comparison with provenance groups left every numeric scope unchanged. All four token fields are compared separately: cached input and reasoning output remain subsets and are never added as extra charges.
