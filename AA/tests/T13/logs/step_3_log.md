# Step 3 log: independent verifier for T13 (2026-11-18)

Output: `AA/analysis/verify_t13.py` (3,400 lines, a fork of `analysis/verify_t11.py`; it imports only the standard library, numpy and pandas, plus scipy lazily for one chi-square p-value), `AA/tests/T13/logs/verifier_spec.md` (the deltas against T11's spec), this log, and `AA/tests/T13/evidence/smoke/verify_t13.json`.

## Independence

- The verifier never opened, read, grepped or imported `analysis/t13_engine.py`, `analysis/t11_engine.py`, `analysis/approved_data.py` or any other `analysis/` module. Its imports are `argparse, hashlib, json, math, re, shutil, sys, tempfile, time, traceback, zlib, fractions, itertools, pathlib`, numpy and pandas. The engines are named only in strings (the expected value of `c_shared_code.against`, docstrings).
- Read: `T13.md` §1–§3 (not edited; `python tests/T13/check_prereg.py` prints OK before and after), `tests/T13/logs/evidence_contract.md`, `tests/T13/logs/step_1_spell_counts.json`, `tests/T11/logs/{evidence_contract.md, verifier_spec.md, step_3_log.md, step_1_spell_counts.json}`, `analysis/verify_t11.py`, `tests/T13/check_prereg.py` (to match its hash region), and as files to compare against: `tests/T13/evidence/smoke/`, the 4-book, 100-draw scratch run (read only; the corrupted copy and the output went to my own scratch directory), `tests/T11/evidence/headline/{decisions.csv, daily_nav.csv, parent_nav_2014-09-01_2019-01-02.csv}` and T06's / T08's stored files as verify_t11 reads them. No step 2 log exists for T13 and none was read.
- Data: only APPROVED rows of `data/APPROVED_DATA.md`, through verify_t11's own `rd()` guard (sha256 prefix, through-date, Smallcap 100 usable-from 2011-11-25), plus the gate-only D24 read for V4(e), as in T11. No data file was edited, extended or fetched.

## What changed against verify_t11.py

1. The decision rule: `n_buy`, `at_least_two_buy`, `all_three_buy` (= `n_buy == 3`), `state` (= `n_buy >= 2`), `state_all3` (= `n_buy == 3`) are derived per decision, and compared with `decisions.csv` in three checks: C-dec (2-of-3 state and T11's columns; plus the evidence's own state against its own signs), C-dec-nbuy (the new columns and the contract's column order), C-dec-all3 (all-3 state against mine, against its own signs and against T11's stored `decisions.csv`).
2. Paths and numbers: `tests/T13/...`, `verify_t13.json`, T13.md's hash, seeds `[16, ...]`, the frozen counts of T13.md §2–§3 and the contract's §5 (every typed T11 count replaced: spells 9 / 9, S 115 / 113, bounds [2, 30] / [2, 33], 9 round trips, 8 sleeve trades on eight dates, 8 flips while IN, 74 / 39 gold weeks while OUT, 15 gold spells with an OUT week, the tuple counts, r3's 7 / 8 spells, S 101 / 109, 7 round trips, its tuples, weeks by n_buy 78 / 35 / 22 / 93, the smoke trade counts 9 / 8 / 8 / 8). T11's all-3 numbers stay in as `FROZEN_ALL3` for the comparator.
3. The all-3 comparator `strategy_all3` / `strategy_all3_fixed50` at 0 / 20.8 / 50 bps is re-derived (the same simulator with the all-3 state) and compared with `daily_nav.csv`, `stats.csv` and `trades.csv` (new check C-all3, plus C-stats-all and C-trades).
4. V4(a1) independently (new check C-regress-t11): my all-3 NAVs and my hold-the-parent / sleeve-only NAVs against T11's stored `daily_nav.csv`, every session, 3 costs, every book of the evidence, at 1e-12; my all-3 decisions against T11's stored `decisions.csv`; the hold-the-parent columns of the parent NAV file against T11's; the engine's `regression_t11.json` (pass, rows compared > 0 and equal to books × 5 × 3, every row and book) and `regression.json` `a1_t11_regression` equal to it.
5. V4(a2) uses the all-3 state (decisions and NAVs) against T06's and T08's stored 2019 runs.
6. Engine gate files: `c_shared_code.against` / `changed_functions` / `new_in_t13` / `dropped_from_t11`, `d_signals` `n_buy_vs_signs` and `state_vs_n_buy`, `a1_t11_regression`, `sampler_selftest.json` `also_seed_16`, the new `audit.json` book keys, `prereg_sha256`, `run.seeds`.
7. Self-test: T11's nine corruptions plus an `n_buy` cell changed, a `state_all3` cell flipped and one `strategy_all3` NAV row × 1.001.
8. `verify_t13.json` has verify_t11.json's keys unchanged plus a new top-level `t13` key.

## Results

| Run | Command | Exit | Gate comparisons | Failures + missing | Checks (gate) | Self-test |
|---|---|---|---|---|---|---|
| Engine smoke (1 book, 20 draws) | `python analysis/verify_t13.py --run smoke --draws 20` | 0 | 127,690 | 0 | 47 (45) | all 12 corruptions detected, each by its own check |
| Scratch run (4 books, 100 draws) | `python analysis/verify_t13.py --evidence <scratch>/t13_scratch4 --draws 100 --out <my scratch>/v13_out/verify_t13_scratch4.json --scratch <my scratch>/v13_out` | 0 | 562,752 | 0 | 47 (45) | all 12 detected |

Runtime: 13 s (smoke), 39 s (scratch run), both including the self-test.

**Worst relative differences** (smoke / scratch run; limits 1e-9 for NAVs and statistics, 1e-12 for regressions and identities):

- Strategy NAV at 0 bps 2.0e-15 / 2.0e-15; at 20.8 and 50 bps 2.3e-15 / 2.2e-14; closed-form end NAV 1.4e-15 / 2.0e-15; every statistic of every run 2.8e-15 / 2.4e-14; comparators and R7 variants 2.8e-15 / 8.0e-15; parent NAV file 4.6e-16 / 8.9e-16; R2 / R3 cells 5.3e-16 / 7.5e-15.
- All-3 comparator (C-all3: NAV, statistics, and the engine's all-3 NAVs against T11's stored rows) 1.4e-15 / 3.7e-15.
- Trades (every trade of every run, basket changes included) 6.8e-15 / 1.8e-14; sleeve trades 3.8e-16 / 5.4e-16; positions 3.3e-16 / 5.1e-16; V6 post-trade holdings against targets 2.0e-16 / 4.2e-16 of V.
- Draws: every draw's structure and its regeneration from the seed exact (smoke 160 saved draws, scratch 3,200); re-simulated draw statistics 5.9e-15 / 5.0e-13 (500 / 4,000 draws); float32 curves 5.9e-8 (limit 1e-5).
- **V4(a1)**, my NAVs against T11's stored `daily_nav.csv` (16,050 / 64,200 rows): `strategy_all3` 5.6e-16 / 9.2e-16, `strategy_all3_fixed50` 4.1e-16 / 6.6e-16, `hold_parent` 4.4e-16 / 8.9e-16, `sleeve_only` 0.0, `sleeve_only_timed` 0.0; my all-3 decisions equal T11's stored decisions in every column compared (228 / 912 rows); the engine's `regression_t11.json` passes with 15 / 60 rows.
- **V4(a2)** (all-3 state, D17 calendar, all four books): T08 1.9e-15 (20,370 rows), T06 1.8e-15 (11,640 rows), 2019 decisions exact (422 comparisons).
- V4(b) one-instrument 4.4e-16 / 7.7e-16; V4(f) seam gaps −0.22, +0.39, +0.45, +0.19 pp (limit 0.5), equal to the engine's to 1e-6.

Re-derived from the raw files and equal to T13.md and `step_1_spell_counts.json`: 1,070 sessions, 228 decisions, the 9 / 9 spells with the lengths of §2, weeks by n_buy 78 / 35 / 22 / 93, 22 weeks IN under 2-of-3 only and none under all-3 only, gold 10 / 9 spells, 18 flips (8 sleeve trades on the eight listed dates, 2 on an exit decision, 8 while IN), 74 / 39 gold weeks while OUT, 15 gold spells with an OUT week, the eight tuple counts (inclusion-exclusion = DP = T13.md), the r3 window, 19 baskets per book, and the smoke strategy's 9 / 8 / 8 / 8 trades at 20.8 bps. The all-3 series equals T11's (8 / 8 spells, S 93 / 135, 9 sleeve trades).

**Extra negative probes** (single corruptions of a copy of the smoke evidence, self-test off; every one exits 1 on the expected check): an `at_least_two_buy` cell flipped (C-dec-nbuy); `d_signals` `n_buy_vs_signs` = 1 (C-engine-files); `also_seed_16` renamed to `also_seed_14` (C-engine-files); an audit `weeks_by_n_buy` cell (C-engine-files); `invested_weeks` of `strategy_all3` set to 115 in stats.csv (C-all3, C-stats-all); `regression_t11.json` pass = false (C-regress-t11); `state` replaced by `state_all3` everywhere, i.e. an engine running T11's rule (C-dec, 44 failures); one `strategy_all3` exit removed from trades.csv (C-trades); `c_shared_code.new_in_t13` emptied (C-engine-files); `state` and `state_all3` columns swapped in order (C-dec-nbuy); a wrong `prereg_sha256` (C-engine-files); `regression_t11.json` deleted (C-regress-t11).

## Disagreement with the engine

None. Every NAV, trade, cost, statistic, state, count and gate file compared equal within the tolerances above. T11's `sessions_invested` week-0 reading (T11 step 3 log) still holds and still matches the engine (the rule's `sessions_invested_rule` in `audit.json` equals the verifier's).

## Interpretations of the contract (none changes a number)

1. T11's single C-dec check is split into C-dec, C-dec-nbuy and C-dec-all3 so that the two new decision corruptions are each caught by a check that no other corruption reaches.
2. The all-3 series' 9 sleeve trades is T11's number (T11.md §2 and T11's step 3 log), confirmed indirectly by T13.md §2 ("T11's list without 2015-01-23").
3. The contract's §5 trade counts for SCMO_0003 are counts of the real rule, so they are asserted whenever SCMO_0003 is in the evidence (the headline included), not only on the smoke run.
4. V4(a1) is checked twice: my own NAVs against T11's stored file (C-regress-t11) and the engine's all-3 NAVs against T11's stored file (C-all3), both at 1e-12. In the smoke run this covers SCMO_0003 only (the evidence holds one book); the scratch run covers all four.
5. The r3 window's weeks by n_buy (78 / 31 / 16 / 85) come from `step_1_spell_counts.json` only (T13.md does not state them).
6. `audit.json` `readings` (E25, reworded E3 / E18 / E21) are text and are not checked; V4(c) remains the engine's own gate, as in T11.

## How to rerun

`python analysis/verify_t13.py --run headline` (after Step 2's headline run; exit 0 only if everything passes and the corruptions are detected; writes `evidence/headline/verify_t13.json`); `--run smoke --draws 20` for the smoke evidence; `--no-selftest` skips the corrupted copy. Expect about a minute on the 2,000-draw headline (T11's verifier took about that on the same size).
