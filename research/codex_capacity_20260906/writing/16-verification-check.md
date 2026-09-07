# Verification check

Research verification closed on 7 September 2026. The final Markdown and regenerated PDFs include the scheduling and prior-reminder source audits. The full repository ratchet passed at the last Python-code commit, 3282808d9ea210226f84aab00d438e4095bc95fc. Integration and private delivery require separate live receipts, recorded in the existing PM task.

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
| PDF rendering | Pinned Markdown 3.9 / WeasyPrint 66.0 CLI, explicit UTF-8, DejaVu fonts, separate landscape figure pages | Executive 2 pages, dossier 18. No overflowing text spans or detected encoding markers. Both full contact sheets inspected, with detailed source-audit and earlier executive, findings and figure inspections. Small tables remain together. |
| New plotting helper | Ruff, strict BasedPyright, Pylint and five architecture checkers | Clean, Pylint 10.00/10. |
| Research script repairs | Full repository ratchet across all ten gates | Passed at 3282808: all 26 changed Python files clean. Combined focused Pylint 10.00/10, strict BasedPyright zero, Ruff zero and scoped Semgrep zero. No quality policy, baseline or workflow changed. |
| Counter and account-join preservation | Old/new implementations on frozen telemetry | All 7,319,366 token-event classifications and 6,066,658 joined rows match. A separate complete FSN1/Jeff ingestion comparison matches all four database tables. |
| Original extractor behavior | Old/new implementations against existing broker, recovery and rollout sources | 56,596 broker records, 5,722 recovery records and 16,009 records from 22 stable original rollout files match. The rollout check is bounded to 155,592,993 source bytes. |
| Table exporter and package commands | Full new table export and plotting export from the new package path | All retained table files and all three chart CSVs reproduce byte-for-byte. The extractor module help command succeeds under Python 3.12. |
| Scheduling and named prior reminder sources | Frozen scheduling exports, original per-turn source boundaries and original 1 September query/response | 622 turns reconciled without added usage. All 342 earlier reminder outcomes and five token sums reproduce exactly and match the frozen main export. |
| Staging and delivery | Live GitHub checks, exact merged report hashes and requester-private attachment receipts | Required after this artifact checkpoint; tracked in PM task 677d9b15-6d44-489c-9aed-6f7d905c9f82. This source file does not substitute for those external receipts. |

The scientific qualifications survived both language passes and V4. Current prices are supported by the retained official sources and dated changes, with retrospective continuity, intraday cutover, tier and cache-write limitations stated beside the estimates. Original response hashes and historical annotations remain the basis of the reset-origin conclusions.

The original-source checks after the final code repairs are complete. The live integration audit must verify the required Enforcement integrity and Quality ratchet checks on the final PR state, then verify private Telegram delivery against the merged artifact hashes.

The full ratchet at 50adb4e found implicit namespace and input-exception boundary violations; the complete rerun passed at 3282808. Expected file, decode and external-request failures now pass through an explicit input outcome boundary. Fourteen malformed/missing/failed input cases preserve the earlier outputs and unexpected exceptions still propagate. Original-source extraction rechecked 56,596 broker records, 5,722 recovery records and 16,009 rollout records without differences; see evidence/input-boundary-validation.json. Final tables and the annotated comparison summary reproduce byte-for-byte after the package change.
