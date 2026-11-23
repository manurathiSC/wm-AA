# Step 3 log: independent verifier for T11 (2026-11-17)

Output: `AA/analysis/verify_t11.py` (about 3,000 lines; imports only the standard library (`argparse, hashlib, json, math, re, shutil, sys, tempfile, time, traceback, zlib, fractions, itertools, pathlib`), numpy and pandas; scipy is imported lazily, inside a try, only for the chi-square p-value), `AA/tests/T11/logs/verifier_spec.md` (written before `step_2_log.md` was opened), this log, and `AA/tests/T11/evidence/smoke/verify_t11.json`.

## Independence

- The verifier never opened `t11_engine.py`, `t08_engine.py`, `t09_engine.py`, `t06_engine.py`, `approved_data.py` or any other `analysis/` module (grep of its imports and strings: no such name is imported or opened; the one mention of `t08_engine.py` is in a message string). It forks the structure of `verify_t08.py` / `verify_t09.py` (loaders, simulator arithmetic, sampler, counting, corrupted-copy machinery) and rewrites everything that T11 changes: D26 calendar, own T0, rule starts IN, D24b, bounds per window computed from the series (lo = min(2, shortest spell)), seeds `[14, ...]`, D05's skipped flag, the 19-basket table, R7, the r3 window, the D17-calendar regression against **both** T06 and T08, V4(b), V4(e), V4(f), the parent-NAV file, the frozen text's own numbers as an oracle.
- `step_2_log.md` was opened only after `verifier_spec.md` was written, and only to look up how `sessions_invested` is defined (grep for "sessions_invested", "cover"). It says only that the function is shared with T08 (AST-identical); it states no reading of week 0. The same grep showed the R7 counts (579 / 125 / 564 / 123 zeroed stock-days) and the one flagged stock-day (PURVA.NS 2017-10-23), which the verifier had already derived. **Readings adopted from `step_2_log.md`: none.** The one place the verifier changed after seeing the engine's number is the `sessions_invested` week-0 reading below, argued from the frozen text, not copied.
- Data boundary: only APPROVED rows were opened (the verifier's `rd()` raises otherwise), plus T06/T08 evidence (`daily_nav.csv`, `decisions.csv`) for V4(a), `logs/step_1_spell_counts.json`, and the evidence folder. `price_source_steps.csv`, `*_ohlc_availability.csv`, `*_ohlc_filled_cells.csv`, `g0_gate.csv` and every non-approved file were not opened.
- **Gate-only read (V4(e)):** `Historical Data/extended_2026-11-06/MAUc1/Master_MAUc1.xlsx` (D24, APPROVED) was opened to check D24b against D24 on every shared Master week (1,010 comparisons incl. 52-53 shared decision dates per book; D24's first SIGN row is 2015-03-13). T11.md §3 lists D24 as "Not read" by the test; the engine therefore compared D24b only with T08's stored gold signal on 2019. The read is marked `gate_only` in `verify_t11.json` (`approved_data_files_read`) and is exempt from the "every file the verifier read is in inputs.csv" rule.

## Results

| Run | Command | Exit | Gate comparisons | Failures + missing | Checks (gate) | Self-test |
|---|---|---|---|---|---|---|
| Engine smoke (1 book, 20 draws) | `python analysis/verify_t11.py --run smoke` | 0 | 94,784 | 0 | 43 (41) | all 9 corruptions detected, each by its own check |
| Mock evidence, 4 books, 2,000 draws (built from the contract; draws' NAV stats exact for the sampled ids, fake for the others) | `--evidence <mock> --draws 2000` | 0 | 3,729,487 | 0 | 43 (41) | all 9 detected |

- `python -c "import verify_t11"` from `AA/analysis/` is clean (only the harmless numexpr/NumPy import warning of this machine).
- Worst relative differences on the smoke evidence (limits: 1e-9 NAVs and statistics, 1e-12 regression and identities): strategy NAV 1.3e-15; every trade 1.7e-14; every draw statistic re-simulated 2.5e-14 (the 20.8 bps float32 curves are within 1e-5); comparators and R7 variants 4.2e-15; T08 regression (20,370 rows, all four books, 3 costs, 7 runs) 1.9e-15; T06 regression (11,640 rows) 1.8e-15; V6 post-trade holdings against targets 2.8e-16 of V; one-instrument identity 4.4e-16; seam gaps -0.22, +0.39, +0.45, +0.19 pp (limit 0.5), equal to the engine's to 1e-6.
- Re-derived from the raw files and equal to the frozen text: 1,070 sessions, 228 decisions, 8 in / 8 out spells (lengths 7,1,6,6,28,28,14,3 / 7,9,16,34,12,11,30,16), gold 10 BUY / 9 SELL spells, 18 flips, 9 sleeve trades on the nine dates listed in T11.md §2, 81 / 54 gold weeks while OUT, 19 baskets per book (last 2018-12-17), the r3 window (989 sessions, 210 decisions, 6 / 7 spells starting OUT), the four tuple counts of the full window and the four of r3 (inclusion-exclusion = DP = T11.md), the export-priced held stock-sessions per stock (574 / 123 / 556 / 122 with the stock splits of §3), the session 2017-10-19 with no D18 bar for any stock, one 20% stock-day (PURVA.NS 2017-10-23, SCMO_0010).
- Every saved smoke draw (N4.9, N4.10, N4.9-g, N4.10-g; full and r3) equals the verifier's own regeneration from its seed (160 draws), so the engine's samplers and the verifier's agree draw for draw.
- Negative probes beyond the nine self-test corruptions (all caught by the expected check): a positions unit x1.000001; a stats CAGR x1.0001; a wrong sha256 and a wrong through-date in inputs.csv; a basket session date; a constant-mix `traded` value; the sleeve raw-fill flag; one `sessions_invested`; a parent-NAV cell; an r7_export NAV; a daily NAV of `sleeve_only_timed`; a Smallcap 100 label dated 2011-11-18; the count table's n_ways; the seam gap; a real gold state; a reversed N4.9 draw.

## Disagreement with the engine (investigated, not "fixed" to match)

**`sessions_invested` for a draw or the rule that starts IN (week 0).** The engine's column is one higher than a returns-only count: 443 for the rule (verifier 442), 440 against 439 for every F1 draw 0, and so on, in every draw (the first states are IN in all full-window draws; r3 draws start OUT and agree). Cause: week 0's trade session. The contract says "daily returns earned while the parent is held"; T06/T08 never needed week 0 because their rule starts OUT. The engine (shared function with T08) counts week 0 from T0's session (session 0, which has no return); a returns-only count starts at session 1. The frozen text defines no formula (§2: "weeks hold 3 to 5 sessions; sessions invested per draw, reported"); the first week of T11 is Monday 2014-09-01 to Friday 2014-09-05, 5 sessions, like any other full week, so the engine's reading is consistent with "a week's sessions" and is adopted in the verifier (the engine's column then matches all 1,000 smoke rows). It is a reported, descriptive column; no NAV, criterion or percentile depends on it. **Step 4 and the write-up should say which reading they use** (one more session than the number of daily returns, for the first week only).

No other disagreement: every NAV, trade, cost, statistic, state, count and file compared equal within the tolerances above.

## Frozen-text and contract ambiguities met (none changes a number)

1. `sessions_invested` week 0 (above).
2. T11.md V1 asks for the NAVs of "the first 20 and 20 random ones per book and null": the verifier takes 20 random ids per book and per row group (the draws are the same for all books, so a different 20 for each book); the engine saves curves for every F1 and F3 draw.
3. T11.md V4(e) needs D24 although §3 lists it as not read: done as a gate-only read (above).
4. T11.md V4(c) asks for an automated comparison of the engine's functions with `t08_engine.py`: impossible for a verifier that may not open the engines; the verifier reads the engine's own result from `regression.json` (`c_shared_code.unexpected_changes` empty) and says so in the check's notes. **V4(c) therefore rests on the engine's gate alone.**
5. The contract does not say whether `baskets.csv`'s `basket_no` starts at 0 (it does) nor what an exit row's `gw_before` holds when the exit decision also flips g (the previous gold weight); `count_table.json`'s `bounds` is nested for `full` and flat for `r3`. All accepted.
6. The contract's `r7_export.csv` NAV columns are the 0-cost always-in end NAVs; the verifier recomputes both and compares them.
7. `analysis.log` does not exist yet (Step 4): `C-percentile-log` is informational and compares nothing until it does.

## Runtime

Smoke: 13 to 16 seconds including the self-test. The sample of draws per row group is fixed at 40 per book (20 first, 20 random), so the NAV work does not grow with the number of draws; the structure checks (every draw), the seed regeneration and the percentile loops do. Measured on the 4-book, 2,000-draw mock: derivation 6 s, comparison 20 s, self-test about 11 s more, **37 s in all**; on the engine's real 2,000-draw headline files (200,000 rows of `draws.csv`, a 150 MB curve file) expect about one minute.

## How to rerun

`python analysis/verify_t11.py --run headline` (exit 0 only if everything passes and the corruptions are detected; writes `evidence/headline/verify_t11.json`); `--run smoke` for the smoke evidence; `--no-selftest` skips the corrupted copy.
