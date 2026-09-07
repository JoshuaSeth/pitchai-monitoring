# Verification check

Current report checkpoint: V4 Markdown assembled. PDFs require regeneration after the package-path correction and scheduling-source audit. Full-goal completion remains unproved until scoped code gates, integration, remaining source checks and private delivery finish.

| Claim family or artifact | Authoritative check | Current result |
| --- | --- | --- |
| Eight-account calendar table | Recomputed every July–September strict row from account_months.csv, including observed-day counts | All displayed two-decimal multiples match. |
| Four primary hourly cohorts | Annotated summarize_cohorts.py regenerated into a new file and compared byte-for-byte | Identical comparison JSON. |
| Main ratios | Recomputed 52.9%, 4.72×, 5.12× and 7.8% from unrounded cohort sums | All displayed rounding matches. |
| Source population | Summed all four cells' recorded paths, readable/missing dispositions, scanned bytes and token events | Matches 23,705 / 20,152 / 3,529, 133,998,392,296 bytes and 7,319,366 token events. |
| Replay headlines | Recalculated percentages from replay-cost-impact-v2.json and checked strict population/value | Matches 37.1%, 41.5%, 1,693,319 and $151,117.94. |
| Original analysis tables | SHA-256, row counts and column order checked for all nine manifest entries | All match. Seven retained table-integrity results remain zero. |
| Figures | chart_data.py regenerated all three CSVs into a new directory and recursive diffed against retained files | Byte-identical. Native gnuplot regenerated SVG and PNG. All three figures visually inspected. |
| Price boundary | Read-only SQL against cohort-ledger-v2.sqlite3, with unsupported boundary rows checked | 5,803 strict Sol calls, zero long-context/unsupported rows, $123.9775028 old-rate increment, no primary hours affected, A02 segment 12 only. |
| Historical recovery input | Re-read the historical-main gzip manifest, completion and full record count | 45 sources, zero quota rows. Its hash and completion are now added to the extraction manifest. |
| Billing and residual counters | Read the final notice review, iCloud review and complete residual audit | No matched invoice denominator. The 101 later missing-turn records are unpriced and are not declared proven replays. |
| Report assembly | Compared both complete Markdown files with ordered V4 clean sections | Exact match. Internal markers and traceability absent. Relative report links resolve. |
| PDF rendering | Pinned Markdown 3.9 / WeasyPrint 66.0 CLI, explicit UTF-8, DejaVu fonts, separate landscape figure pages | Executive 2 pages, dossier 17. Initial encoding defect corrected. Final PDFs have no detected mojibake. Executive, source table, Reddit/findings table and all figure pages inspected. |
| New plotting helper | Ruff, strict BasedPyright, Pylint and five architecture checkers | Clean, Pylint 10.00/10. |
| Research script repairs | Ruff, strict BasedPyright, five architecture checks and combined Pylint | Earlier script violations repaired. Combined Pylint is 10.00/10. The complete study now lives in the valid Python package research.codex_capacity_20260906; the complete repository ratchet remains pending. |
| Counter and account-join preservation | Old/new implementations on frozen telemetry | All 7,319,366 token-event classifications and 6,066,658 joined rows match. A separate complete FSN1/Jeff ingestion comparison matches all four database tables. |
| Original extractor behavior | Old/new implementations against existing broker, recovery and rollout sources | 56,596 broker records, 5,722 recovery records and 16,009 records from 22 stable original rollout files match. The rollout check is bounded to 155,592,993 source bytes. |
| Table exporter and package commands | Full new table export and plotting export from the new package path | All retained table files and all three chart CSVs reproduce byte-for-byte. The extractor module help command succeeds under Python 3.12. |
| Staging and delivery | Current Git and PM state | No PR/merge or final attachment delivery yet. |

The scientific qualifications survived both language passes and V4. Current prices are supported by the retained official sources and dated changes, with retrospective continuity, intraday cutover, tier and cache-write limitations stated beside the estimates. Original response hashes and historical annotations remain the basis of the reset-origin conclusions.

Further verification must recheck original source commands after code repairs, actual required repository gates, final artifact hashes and private Telegram receipts. This file records completed evidence checks without claiming those remaining actions succeeded.

The full ratchet at 50adb4e found implicit namespace and input-exception boundary violations. The repaired package passes focused Ruff, BasedPyright and Pylint (10.00/10); Semgrep found zero research violations. Expected file, decode and external-request failures now pass through an explicit input outcome boundary. Fourteen malformed/missing/failed input cases preserve the earlier outputs and unexpected exceptions still propagate. Original-source extraction rechecked 56,596 broker records, 5,722 recovery records and 16,009 rollout records without differences; see evidence/input-boundary-validation.json. The full ratchet must be rerun on the next committed checkpoint.
