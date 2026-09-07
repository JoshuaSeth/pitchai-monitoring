<!-- BEGIN CLEAN TEXT -->
## Reproduction and artifact map

The repository contains anonymous quota exports, sidecar evidence, nine analysis tables, dated pricing, exchange rates and the analysis code. The large rollout exports and intermediate SQLite databases reside in the existing study workspace. They are separate from the repository and require authorized host access. A fresh scan after raw files rotate may not reproduce the frozen input bytes.

### Reproduce the published comparisons from small retained tables

Use Python 3.12. From the research directory, choose a new output path:

```bash
python3.12 summarize_cohorts.py \
  --tables tables \
  --annotations evidence/epoch-transition-annotations.json \
  --output /tmp/codex-capacity-comparisons-reproduced.json
cmp evidence/cohort-comparisons.json \
  /tmp/codex-capacity-comparisons-reproduced.json
```

The annotations are essential. The original epoch CSV retains its quota-only transition classification. The summary applies the three reviewed historical changes in memory and fails if their expected original labels no longer match. Hourly model/period totals, account totals and threshold sensitivities remain unchanged by those origin corrections.

### Raw-source pipeline

The frozen workspace is `/mnt/pitchai-dev-data/codex-capacity-20260906`. `rollouts-main.jsonl.gz`, `rollouts-jeff.jsonl.gz`, `rollouts-historical-main.jsonl.gz` and `rollouts-fsn1.jsonl.gz` are the four candidate inputs. Their hashes and completed extraction counts are in `evidence/rollout-import-audit.json`. The extractor supports explicit source indexes/roots, cell name and cutoff. It exports allowlisted telemetry and source hashes, keeping the private source map outside shared artifacts.

The derivation order is:

1. `extract_rollouts.py` reads the selected cell indexes and roots. `build_ledger.py --database NEW_DB --input EXPORT` imports each completed export once and constructs candidate calls without summing cumulative counters.
2. `normalize_quota.py --input EXPORT --output NEW_DB` accepts repeated inputs for the broker and three recovery exports. It retains freshness, observation-time and source-kind distinctions.
3. `join_calls.py --ledger LEDGER --quota QUOTA --expected-inputs 4 --output NEW_DB` adds exact/tolerance reset-fingerprint account joins.
4. `replay_audit.py --ledger LEDGER --output NEW_DB` produces the current semantic replay decisions. Use the v2 audit corresponding to global turn identity.
5. `price_calls.py --calls JOINED --pricing pricing.json --fx evidence/eur-usd-daily.csv --output NEW_DB` prices individual calls and retains missing-price, long-context, boundary-day and cache-write sensitivities.
6. `build_cohorts.py --joined JOINED --replay REPLAY --prices PRICES --quota QUOTA --broker evidence/broker-20260906.jsonl.gz --headers evidence/source-headers-main.jsonl.gz --headers evidence/source-headers-jeff.jsonl.gz --output NEW_DB` runs the retained account, hourly and bank SQL.
7. `export_tables.py --database COHORT_DB --output NEW_DIRECTORY` exports the nine tables and their manifest, including temporary analysis views. Then run the annotated summary command above.

The current frozen stages are `usage-ledger.sqlite3`, `account-quota-v2.sqlite3`, `joined-calls.sqlite3`, `replay-audit-v2.sqlite3`, `call-prices.sqlite3` and `cohort-ledger-v2.sqlite3`. Earlier v1 sidecars preserve the audit history and must not replace v2 in final comparisons. Existing output protections prevent accidental overwriting of evidence.

### Sidecar evidence and validation

- `source_inventory.json` and extraction manifests distinguish initial discovery counts from completed extractions and unresolved source gaps.
- `tables/manifest.json` binds CSV hashes and row counts. `cohort_validation.csv` records seven integrity checks with zero failures. These checks address table consistency, not causal identification or missing workload.
- Replay method validations retain copied/forked cases and the change from session-bound to global-turn identity. The pricing refactor comparison checked 6,066,658 rows and twelve fields per row with zero differences.
- `lease-corroboration.json`, `account-window-audit.json` and `residual-counter-audit.json` provide separate identity and counter checks.
- `historical-corroboration.json` retains SQL and results for reset waves, the manual-to-positive bridge, narrative clocks and revised epoch counts. `manual-reset-responses.json` binds ten selected responses to source-path, invocation and record hashes.
- `prior-ledger-reconciliation.json` and its review distinguish prior/current counter disagreement from unavailable sources. Billing reviews preserve the invoice and access gaps without account identities.
- `cohort-comparisons.json` contains model/effort, account, reset-origin and threshold partitions, component sums and conditional endpoint sensitivities.

The accompanying chart and report renderers use these retained values. Figure captions state the population, denominator and source table. Reproduction confirms the declared calculation on the retained evidence. It cannot restore missing requests, infer invoices or observe the provider's hidden credit weights.
<!-- END CLEAN TEXT -->

## Internal traceability

Sources: actual parser options and frozen file inventory, read before drafting. Component: historical ledger reproduction section. Commands show derivation without exposing source maps or credentials. The final package must add real renderer commands only after those renderers exist and have run. Archive size and worktree lifecycle are operational concerns outside this reader-facing method.
