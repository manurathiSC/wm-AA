# Step 4 log: test scripts (2026-11-06)

Files: `tests/T05/analyse.py`, `fill_writeup.py`, `report.py`, `run.sh` (run.sh is the plan's verbatim). Nothing in T04, T05.md, TRACKER.md or the engine/verifier was touched.

## Checks done
- `python -m py_compile` on the three scripts and `bash -n run.sh`: OK (the generated `__pycache__` was removed).
- Ran analyse.py, report.py and fill_writeup.py end to end on a scratch copy of `evidence/smoke` (20 draws, with T04's verify_t04.json copied in as a stand-in `verify_t05.json`) via the new `--root` option; nothing was written into the real T05 folder. analyse.py exits 0, report.py writes a 0.42 MB page (JS passes `node --check`, page data parses, new chart and sections present), fill_writeup.py writes §4 into a scratch copy of T05.md with §1-§3 and the header byte-identical and CRLF line endings kept. `check_prereg.py` still exits 0 on the real T05.md.
- Also ran analyse.py once on a synthetic T05 shape built from T04's evidence (review flags added by the 5a rule): same output shape; T04-vs-T04 columns were identical as expected.

## What changed vs T04
analyse.py
- T04 -> T05 titles/constants, seed salt 5 (`default_rng([5, 1, 0])`, `u[review_j]` in the worked example), `verify_t05.json`, `--root`/`--t04` options (defaults: this folder, `tests/T04`).
- Header: review count (all, traded, monthly only, forced, forced that are also month-end, `review_mask_count`, flags in BUY weeks) and first/last five review dates; 4.0 gets a first/last five review table with n and k per indicator.
- Reportability recomputed from `selections.csv` as the review decisions in SELL with 1<=k<n (>=20), full and live; the last decision of each window (not traded) is excluded and the result is cross-checked against the engine's `reviews_1_le_k_lt_n_traded_only` in audit.json.
- Worked example is a review decision (`is_review`), shows the weeks after it reusing the stored pass set, and the null draw from row `review_j`.
- Headline table gains the 0 bps percentile; turnover table (strategy vs null mean trades, cost paid, ratio) shows the 20.8 and 0 bps percentiles side by side; new status-rule table (C1 pass is `selection` only if 0 bps percentile >= 98, else `turnover-driven`).
- "T04 beside T05" table: T04 percentiles, 0 bps percentiles, trades, CAGR and status copied from T04's `analysis_summary.json` and the Robustness table of T04's `analysis.log` (never recomputed); T04's null SDs and R5 printed beside T05's.
- Cross-checks printed (not gates): decision series vs T04's on shared dates, engine `review` flag vs the calendar rule.
- analysis_summary.json now also carries `pc0`, `cls`, `reviews` (counts) and `rep` (reportability), which report.py reads.
- The calendar-year table prints the year as text (T04's log shows 2019.00).

fill_writeup.py
- T04 -> T05; works on raw bytes so the file's CRLF endings are kept; additionally checks that the header and §1-§3 are byte-identical (not only hash-equal) before and after, and writes via a temp file.

report.py
- Imports the loaders and the review rule from analyse.py (same folder).
- New "Review dates" section (reviews per year, the full monthly + forced schedule with n and k, BUY-week flags that do nothing) and "Reviews vs T04 decisions" (cumulative-evaluations chart with crosshair, x and y chips, and an all-series tooltip that also names the review kind; a counts table read from T04's evidence as data).
- Share-kept chart tooltip notes the review kind per week; headline text and per-indicator cards show the 0 bps percentile and the status; the T04-specific "every indicator earns less than the full switch" sentence is now computed.

## Assumptions about evidence columns (confirmed against evidence/smoke after the coordinator's correction)
- T04's real format: `decisions.csv` (`trade_date`, `state`, `regime`, new `review`), long `selections.csv` (`window, indicator, j, decision_date, regime, basket_eff, n, k, kept, nontrivial` plus `review_j`, `is_review`), `stats.csv` wide with `n_reviews`, `audit.json` with `review_mask_count`.
- Loaders also tolerate the plan's table names (`trade_session`, per-stock `stock_col, selected`, `session`) and derive `regime`/`review_j` when missing; if the engine's `review_j` is present it is used (`review_j == j` marks a review).

## Open issues
- The full pipeline (verify_t05 outputs `verify_t05.json` in the same shape as T04's, `exit_ok`, `checks`, `selftest`) is assumed; analyse.py reports V1 NOT RUN and exits non-zero without it.
- "2,000 draws" text is now taken from `audit['run']['draws']`; the T05.md §4 text will say 20 draws if ever built from smoke evidence (do not fill_writeup from smoke).
