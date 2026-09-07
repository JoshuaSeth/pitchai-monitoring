<!-- BEGIN CLEAN TEXT -->
## Reproduction and artifact map

The repository contains anonymous quota exports, sidecar evidence, nine analysis tables, dated pricing, exchange rates and the analysis code. The large rollout exports and intermediate SQLite databases reside in the existing study workspace. They require authorized host access. A fresh scan after raw files rotate may not reproduce the frozen input bytes.

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
4. `replay_audit.py --ledger LEDGER --output NEW_DB` produces the current semantic replay decisions. The v2 audit uses global turn identity.
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

### Figures and PDF

`chart_data.py` exports plotting CSVs from the retained tables and annotated comparison summary. `charts.gnuplot` renders the account, hourly and epoch comparisons with gnuplot 6.0. From the repository root, a fresh plotting export can be compared with the retained CSVs:

```bash
python3.12 -m research.codex-capacity-20260906.chart_data \
  --output /tmp/codex-capacity-figure-data
```

From the research directory, `gnuplot charts.gnuplot` regenerates SVG and PNG figures from `figures/data`. The Markdown reports embed the SVG versions. PDF conversion uses Python-Markdown 3.9 and WeasyPrint 66.0 in isolated `uvx` environments:

```bash
bash render_reports.sh /tmp/codex-capacity-pdfs
```

The output directory must be new. The renderer applies `report.css` to `dossier.md` and `executive-report.md`. Its two PDF files contain the report text and figures. Reproduction establishes the calculation on retained evidence. Missing requests, invoices and hidden credit weights remain outside that evidence.
<!-- END CLEAN TEXT -->

## Internal language pass one

Input: [V1](11-reproduction-v1.md). Each numbered unit below is one prose sentence, table row, heading or indivisible code block, in source order. Table rows and code preserve their structure. This is a language review, with factual verification recorded separately.

| Unit | Source opening | Decision |
| ---: | --- | --- |
| 1 | ## Reproduction and artifact map | Retain descriptive heading for navigation. |
| 2 | The repository contains anonymous quota exports, sidecar evidence, nine analysis tabl… | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 3 | The large rollout exports and intermediate SQLite databases reside in the existing st… | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 4 | They are separate from the repository and require authorized host access. | Remove a repeated location distinction. |
| 5 | A fresh scan after raw files rotate may not reproduce the frozen input bytes. | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 6 | ### Reproduce the published comparisons from small retained tables | Retain descriptive heading for navigation. |
| 7 | Use Python 3.12. | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 8 | From the research directory, choose a new output path: | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 9 | ```bash python3.12 summarize_cohorts.py \   --tables tables \   --annotations evidenc… | Retain executable syntax and paths. Reproduction is checked separately. |
| 10 | The annotations are essential. | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 11 | The original epoch CSV retains its quota-only transition classification. | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 12 | The summary applies the three reviewed historical changes in memory and fails if thei… | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 13 | Hourly model/period totals, account totals and threshold sensitivities remain unchang… | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 14 | ### Raw-source pipeline | Retain descriptive heading for navigation. |
| 15 | The frozen workspace is `/mnt/pitchai-dev-data/codex-capacity-20260906`. `rollouts-ma… | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 16 | Their hashes and completed extraction counts are in `evidence/rollout-import-audit.js… | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 17 | The extractor supports explicit source indexes/roots, cell name and cutoff. | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 18 | It exports allowlisted telemetry and source hashes, keeping the private source map ou… | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 19 | The derivation order is: | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 20 | 1. `extract_rollouts.py` reads the selected cell indexes and roots. `build_ledger.py … | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 21 | It retains freshness, observation-time and source-kind distinctions. 3. `join_calls.p… | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 22 | Use the v2 audit corresponding to global turn identity. 5. `price_calls.py --calls JO… | Turn an implementation instruction into the decisive version property. |
| 23 | Then run the annotated summary command above. | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 24 | The current frozen stages are `usage-ledger.sqlite3`, `account-quota-v2.sqlite3`, `jo… | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 25 | Earlier v1 sidecars preserve the audit history and must not replace v2 in final compa… | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 26 | Existing output protections prevent accidental overwriting of evidence. | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 27 | ### Sidecar evidence and validation | Retain descriptive heading for navigation. |
| 28 | - `source_inventory.json` and extraction manifests distinguish initial discovery coun… | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 29 | These checks address table consistency, not causal identification or missing workload… | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 30 | The pricing refactor comparison checked 6,066,658 rows and twelve fields per row with… | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 31 | Billing reviews preserve the invoice and access gaps without account identities. - `c… | Retain the concrete observation, its population and any necessary uncertainty. No stylistic filler requires an edit. |
| 32 | The accompanying chart and report renderers use these retained values. | Replace anticipated renderer claims with the actual command and data flow. |
| 33 | Figure captions state the population, denominator and source table. | Replace anticipated renderer claims with the actual command and data flow. |
| 34 | Reproduction confirms the declared calculation on the retained evidence. | Replace anticipated renderer claims with the actual command and data flow. |
| 35 | It cannot restore missing requests, infer invoices or observe the provider's hidden c… | Replace anticipated renderer claims with the actual command and data flow. |

Pass one uses direct subjects and verbs, removes formulaic contrasts and expands ambiguous terms. Required limits on identity, pricing and causal interpretation stay beside the affected claims. Technical methods and source citations remain necessary in this empirical report. No commercial promise is added.
