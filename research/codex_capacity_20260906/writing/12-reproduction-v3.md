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

The frozen workspace is `/mnt/pitchai-dev-data/codex-capacity-20260906`. `rollouts-main.jsonl.gz`, `rollouts-jeff.jsonl.gz`, `rollouts-historical-main.jsonl.gz` and `rollouts-fsn1.jsonl.gz` are the four candidate inputs. Their hashes and completed extraction counts are in `evidence/rollout-import-audit.json`. The extractor supports explicit source indexes/roots, cell name and cutoff. The exports contain telemetry fields and source hashes. Resolving the hashes back to original files requires the restricted source map.

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
- `tables/manifest.json` binds CSV hashes and row counts. `cohort_validation.csv` records seven integrity checks with zero failures. These checks establish table consistency. Causal identification and missing workload require separate evidence.
- Replay method validations retain copied/forked cases and the change from session-bound to global-turn identity. The pricing refactor comparison checked 6,066,658 rows and twelve fields per row with zero differences.
- `lease-corroboration.json`, `account-window-audit.json` and `residual-counter-audit.json` provide separate identity and counter checks.
- `historical-corroboration.json` retains SQL and results for reset waves, the manual-to-positive bridge, narrative clocks and revised epoch counts. `manual-reset-responses.json` binds ten selected responses to source-path, invocation and record hashes.
- `prior-ledger-reconciliation.json` and its review distinguish prior/current counter disagreement from unavailable sources. Billing reviews preserve the invoice and access gaps without account identities.
- `cohort-comparisons.json` contains model/effort, account, reset-origin and threshold partitions, component sums and conditional endpoint sensitivities.

### Figures and PDF

`chart_data.py` exports plotting CSVs from the retained tables and annotated comparison summary. `charts.gnuplot` renders the account, hourly and epoch comparisons with gnuplot 6.0. From the repository root, a fresh plotting export can be compared with the retained CSVs:

```bash
python3.12 -m research.codex_capacity_20260906.chart_data \
  --output /tmp/codex-capacity-figure-data
```

From the research directory, `gnuplot charts.gnuplot` regenerates SVG and PNG figures from `figures/data`. The Markdown reports embed the SVG versions. PDF conversion uses Python-Markdown 3.9 and WeasyPrint 66.0 in isolated `uvx` environments:

```bash
bash render_reports.sh /tmp/codex-capacity-pdfs
```

The output directory must be new, and `uv` must be available. The renderer applies `report.css` to `dossier.md` and `executive-report.md`. Its two PDF files contain the report text and figures. Reproduction establishes the calculation on retained evidence. Missing requests, invoices and hidden credit weights remain outside that evidence.
<!-- END CLEAN TEXT -->

## Internal language pass two

Input: [V2](12-reproduction-v2.md). Sentence and table review below is independent of the first pass. V1 remains in its original section file. Each numbered unit is a sentence, heading, table row or code block in input order.

| Unit | V2 opening | Second-pass decision |
| ---: | --- | --- |
| 1 | ## Reproduction and artifact map | Retain the subject-specific navigation heading. |
| 2 | The repository contains anonymous quota exports, sidecar evidence, nine analysis tabl… | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 3 | The large rollout exports and intermediate SQLite databases reside in the existing st… | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 4 | They require authorized host access. | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 5 | A fresh scan after raw files rotate may not reproduce the frozen input bytes. | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 6 | ### Reproduce the published comparisons from small retained tables | Retain the subject-specific navigation heading. |
| 7 | Use Python 3.12. | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 8 | From the research directory, choose a new output path: | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 9 | ```bash python3.12 summarize_cohorts.py \   --tables tables \   --annotations evidenc… | Retain code syntax and versioned paths. |
| 10 | The annotations are essential. | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 11 | The original epoch CSV retains its quota-only transition classification. | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 12 | The summary applies the three reviewed historical changes in memory and fails if thei… | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 13 | Hourly model/period totals, account totals and threshold sensitivities remain unchang… | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 14 | ### Raw-source pipeline | Retain the subject-specific navigation heading. |
| 15 | The frozen workspace is `/mnt/pitchai-dev-data/codex-capacity-20260906`. | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 16 | `rollouts-main.jsonl.gz`, `rollouts-jeff.jsonl.gz`, `rollouts-historical-main.jsonl.g… | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 17 | Their hashes and completed extraction counts are in `evidence/rollout-import-audit.js… | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 18 | The extractor supports explicit source indexes/roots, cell name and cutoff. | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 19 | It exports allowlisted telemetry and source hashes, keeping the private source map ou… | Describe the evidence format and access prerequisite. |
| 20 | The derivation order is: | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 21 | 1. | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 22 | `extract_rollouts.py` reads the selected cell indexes and roots. | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 23 | `build_ledger.py --database NEW_DB --input EXPORT` imports each completed export once… | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 24 | 2. | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 25 | `normalize_quota.py --input EXPORT --output NEW_DB` accepts repeated inputs for the b… | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 26 | It retains freshness, observation-time and source-kind distinctions. | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 27 | 3. | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 28 | `join_calls.py --ledger LEDGER --quota QUOTA --expected-inputs 4 --output NEW_DB` add… | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 29 | 4. | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 30 | `replay_audit.py --ledger LEDGER --output NEW_DB` produces the current semantic repla… | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 31 | The v2 audit uses global turn identity. | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 32 | 5. | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 33 | `price_calls.py --calls JOINED --pricing pricing.json --fx evidence/eur-usd-daily.csv… | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 34 | 6. | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 35 | `build_cohorts.py --joined JOINED --replay REPLAY --prices PRICES --quota QUOTA --bro… | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 36 | 7. | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 37 | `export_tables.py --database COHORT_DB --output NEW_DIRECTORY` exports the nine table… | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 38 | Then run the annotated summary command above. | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 39 | The current frozen stages are `usage-ledger.sqlite3`, `account-quota-v2.sqlite3`, `jo… | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 40 | Earlier v1 sidecars preserve the audit history and must not replace v2 in final compa… | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 41 | Existing output protections prevent accidental overwriting of evidence. | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 42 | ### Sidecar evidence and validation | Retain the subject-specific navigation heading. |
| 43 | - `source_inventory.json` and extraction manifests distinguish initial discovery coun… | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 44 | - `tables/manifest.json` binds CSV hashes and row counts. | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 45 | `cohort_validation.csv` records seven integrity checks with zero failures. | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 46 | These checks address table consistency, not causal identification or missing workload… | Remove a contrast formula without overstating validation. |
| 47 | - Replay method validations retain copied/forked cases and the change from session-bo… | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 48 | The pricing refactor comparison checked 6,066,658 rows and twelve fields per row with… | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 49 | - `lease-corroboration.json`, `account-window-audit.json` and `residual-counter-audit… | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 50 | - `historical-corroboration.json` retains SQL and results for reset waves, the manual… | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 51 | `manual-reset-responses.json` binds ten selected responses to source-path, invocation… | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 52 | - `prior-ledger-reconciliation.json` and its review distinguish prior/current counter… | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 53 | Billing reviews preserve the invoice and access gaps without account identities. | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 54 | - `cohort-comparisons.json` contains model/effort, account, reset-origin and threshol… | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 55 | ### Figures and PDF | Retain the subject-specific navigation heading. |
| 56 | `chart_data.py` exports plotting CSVs from the retained tables and annotated comparis… | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 57 | `charts.gnuplot` renders the account, hourly and epoch comparisons with gnuplot 6.0. | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 58 | From the repository root, a fresh plotting export can be compared with the retained C… | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 59 | ```bash python3.12 -m research.codex_capacity_20260906.chart_data \   --output /tmp/c… | Retain code syntax and versioned paths. |
| 60 | From the research directory, `gnuplot charts.gnuplot` regenerates SVG and PNG figures… | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 61 | The Markdown reports embed the SVG versions. | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 62 | PDF conversion uses Python-Markdown 3.9 and WeasyPrint 66.0 in isolated `uvx` environ… | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 63 | ```bash bash render_reports.sh /tmp/codex-capacity-pdfs ``` | Retain code syntax and versioned paths. |
| 64 | The output directory must be new. | Make the executable prerequisite explicit. |
| 65 | The renderer applies `report.css` to `dossier.md` and `executive-report.md`. | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 66 | Its two PDF files contain the report text and figures. | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 67 | Reproduction establishes the calculation on retained evidence. | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |
| 68 | Missing requests, invoices and hidden credit weights remain outside that evidence. | Retain this sentence after checking for weak verbs, vague nouns, repeated caveats and task narration. Its factual content or necessary limit serves the reader. |

The English report retains its original language. This pass targets compressed jargon, abstract nouns, repetitive limits and task narration missed in V2. Decimal values, model/effort labels, dates, equations and executable arguments retain their meaning. Figures show the same retained populations. Necessary uncertainty stays next to the affected comparison. No semicolons, formulaic contrast sentences, defensive client reassurances or nonessential disclaimer stacks are introduced. Phase 13 separately inspects all visible surfaces before assembly.
