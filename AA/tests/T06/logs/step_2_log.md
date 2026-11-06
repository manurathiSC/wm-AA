# T06 Step 2 log: engine (2026-11-06)

**Files created:** `AA/analysis/approved_data.py`, `AA/analysis/t06_engine.py`, this log. Smoke evidence: `AA/tests/T06/evidence/smoke/` (1 book, 20 draws). Nothing else was edited (T06.md, PLAN files, TRACKER.md, APPROVED_DATA.md, data, `t03_engine.py`, T03/T04 untouched; `verify_t06.py` not read).

## Data boundary
`python data/check_approved_data.py` exited 0 before work (32 approved rows, 0 problems, 5 superseded). The engine opens every data file through `ap()` = `approved_data.require()` + sha256-prefix check. It writes `inputs.csv` (32 files: the 24 it parses and the 8 `_columns.csv` / D05 files it only registers) and stops on a mismatch. END (2026-10-22) is read from the four approved D17 files and checked against their rows' through-date. Opening a SUPERSEDED Master, GOLDBEES, LBES file or a path not in the table raises `NotApprovedError` (recorded in `audit.json` data.non_approved_open_raises; part of the exit status).

## Smoke run
`python analysis/t06_engine.py --run smoke --draws 20 --quick` exits 0 in 9 s of engine time (10.6 s wall, including 1.8 s to read and build the book). Gates: V3, V4, V5, approved-data self-test, step-1 spell counts all pass.
Timing for the headline: a simulation takes about 1.2 ms. A throwaway 4-book run with 100 draws (not kept) took 16 s, so 2,000 draws per type and book is about 20 times the draw work: estimate 3 to 6 minutes for the engine, plus CSV writing (draws.csv about 80,000 rows).

## Key numbers (SCMO_0003, full window)
- 409 weeks, first state OUT, 9 in-spells (201 weeks), 10 out-spells (208), bounds 46 / 40; equals `step_1_spell_counts.json` for every book and for the live window (261 weeks, 5 in / 124, 6 out / 137).
- n_ways: in 7,107,131,351,925; out 89,734,761,224,680 (0007 out 89,568,225,513,130); live in 2,436,435, out 46,175,688. All equal the inclusion-exclusion count.
- V3: 20 + 20 draws per series pass (and a tampered series fails, tested on a scratch copy).
- V4: 400 shared decisions (0007: 399), 0 mismatches; 13 NAV series per book compared up to 2026-08-07 (1,875 dates), max relative difference 0.0 (below 1e-12); G0 passes: always-in gap +0.045, +0.103, +0.101, +0.038 pp/yr (worst calendar year 0.43, 0.39, 0.45, 0.19 pp; limits 0.25 and 0.5).
- V5: small case 19 tuples, chi-square p = 0.83; DP = inclusion-exclusion on all 16 (book, window, state) tables; per-position mean length within 4 SE.
- Cash: 0 accrued sessions (extended LBES covers the window). First appended row (2026-08-10) chains from the Sunday 2026-08-09 level; the weekend accrual already in that level (level(Sun) / level(Fri 08-07) - 1) is 0.0234%, slightly above the 0.02% quoted in CLAUDE.md; recorded, not corrected.
- GOLDBEES raw OHLC4 fills: the MCX file ends 2026-09-28; the GOLDBEES file has 25 sessions after it (16 inside the window, 2026-09-29 to 2026-10-22). The strategy trades on none of them; the smoke draws (20 + 20 draws, 3 costs) made 9 such trades.

## Readings chosen (all in `audit.json` readings)
T06-1 sessions_invested = daily returns earned while the parent is held (reproduces T03's 945 for the rule and 941 for draw 445 of 1,884). T06-2 V4(b) constant mix re-run with T03's f (T06's own f uses the longer series). T06-3 no comparison with the Step 1 rebuild (not an approved file): those two g_engine.csv columns are empty. T06-4 one uniform per part, including the forced last part. T06-5 V5(c) is per spell position (a draw's mean length is fixed). T06-6 inputs.csv has no comment line (As-of date is in audit.json). T06-7 coverage check exempts D12 and the basket files. T06-8/9 weeks and bounds. E16: de-spike unchanged up to the MCX last date, raw OHLC4 after (the max/min repair of high and low is also not applied after it).

## Open issues
1. `APPROVED_DATA.md` says the raw-OHLC4 fills are "5 sessions up to 2026-11-04"; the files give 25 sessions after 2026-09-28 (16 in the window). Wording, not data; Manu may want it corrected.
2. The cash weekend double count measures 0.0234% against the 0.02% quoted.
3. The spec asks for the As-of date in an inputs.csv "header comment"; a comment line breaks plain `read_csv`, so it is in audit.json (reading T06-6). The verifier's author should know.
4. D19/D05 through-dates (2026-09-10 / 09-16) are before the window end by design (newest basket); a verifier check "through covers the window" must exempt them.
