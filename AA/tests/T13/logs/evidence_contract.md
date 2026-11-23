# T13 evidence contract: the deltas against T11's

The evidence of `analysis/t13_engine.py --run <run>` (written to `tests/T13/evidence/<run>/`) is **T11's evidence contract (`tests/T11/logs/evidence_contract.md`) with the changes below and nothing else**. Every file, column, key, unit, sign convention, row group, seed formula (with first element 16 instead of 14) and reading of T11's contract holds unless listed here. Written 2026-11-18 after the smoke run (`tests/T13/evidence/smoke/`, all engine gates true).

## 1. The rule

- `state` (decisions.csv, real_states.npz, draws' states) is the **2-of-3** state: 1 iff at least two of `sign_Nifty100`, `sign_MC100`, `sign_SC100` are `BUY` (T11: all three). Everything that T11's contract derives from `state` (spells, bounds, draws, trades, sleeve trades, `sessions_invested`, constant-mix f = mean of `state`, R2, R3, R6, R7) is derived from this state.
- Gold `g`, `gw`, `label_MAUc1`, `sign_MAUc1`: unchanged (T11's series).

## 2. decisions.csv

New columns, inserted after `label_age_days`: `n_buy` (0-3, number of BUY among the three index signs), `at_least_two_buy` (bool, = `n_buy >= 2`), then `all_three_buy` (bool, **now literally all three BUY**, = `n_buy == 3`; in T11 it equalled `state`), `state` (int, 2-of-3), `state_all3` (int, = `n_buy == 3`). Column order: `book, j, decision_date, decision_idx, trade_date, sign_Nifty100, sign_MC100, sign_SC100, label_Nifty100, label_MC100, label_SC100, latest_label, label_age_days, n_buy, at_least_two_buy, all_three_buy, state, state_all3, sign_MAUc1, label_MAUc1, g, gw`. The R3 window's decisions are not written (as T11).

## 3. New runs: the all-3 comparator (T13.md §3 step 10, descriptive)

- `run` / `kind` values `strategy_all3` (all-3 entry, MAUc1-timed sleeve) and `strategy_all3_fixed50` (all-3 entry, 50/50 sleeve), **headline cell only** (window `full`, cash `lbes`), at costs 0, 20.8 and 50, in `stats.csv` (with `invested_weeks` = number of all-3 IN weeks), `daily_nav.csv` and `trades.csv` (all their trades, incl. basket changes). They are the engine with `state` replaced by `state_all3`; no draw is run for them. They are **not** in `positions.csv` or `sleeve_trades.csv` (those stay the 2-of-3 rule's, as T11's were the rule's).
- By gate V4(a1) they equal T11's stored `strategy` / `strategy_fixed50` rows (smoke: max relative difference 0.0).

## 4. Gates

- **New file `regression_t11.json`** (V4(a1)): `decisions` {book: {compared, only_one_side, mismatches, pass}} comparing `state_all3`, `decision_idx`, `g` with T11's stored `decisions.csv` `state`, `decision_idx`, `g`; `rows` [{book, run, t11_run, cost_bps, dates_compared, sessions, max_rel_diff, pass}] for the pairs `pairs` = {strategy_all3: strategy, strategy_all3_fixed50: strategy_fixed50, hold_parent, sleeve_only, sleeve_only_timed: same names} at 0, 20.8, 50 against T11's stored `daily_nav.csv` (every session); `worst_rel_diff_by_run`, `rows_compared`, `tolerance_rel` (1e-12), `pass`.
- `regression.json`: new key `a1_t11_regression` (the same object as `regression_t11.json`); `a_d17_regression` (now V4(a2)) is computed with the **all-3** state (the stored T08/T06 runs are all-3 runs); `d_signals[book]` has two more counters, `n_buy_vs_signs` and `state_vs_n_buy` (both must be 0); `c_shared_code` is now against `t11_engine.py`: keys `against`, `dropped_from_t11`, `new_in_t13` (T11: `dropped_from_t08`, `new_in_t11`); changed functions exactly `d17_regression, main, run_book, shared_code_diff, v4_identities`; new function exactly `t11_regression`.
- `sampler_selftest.json`: `a_small_case.also_seed_16` (seed `[16, 6, 123456789]`) replaces `also_seed_14`.
- `audit.json`: `books[book]` gains `entry_rule`, `invested_weeks_all3`, `weeks_by_n_buy` ({"0".."3": weeks}), `weeks_in_2of3_not_all3`, `weeks_in_all3_not_2of3`; `run.seeds` names first element 16; `prereg_sha256` is T13.md's; `readings` gains E25 (the comparator and V4(a1)); E3, E18, E21 reworded for the rule and seeds.
- The file `verify_t11.json` becomes `verify_t13.json` (the verifier's output).

## 5. Expected numbers (Step 1, frozen in T13.md §2; the engine asserts them)

Full window: 228 decisions, first state IN, in-spells 7, 7, 15, 6, 30, 28, 14, 3, 5 (S 115, bounds [2, 30]), out-spells 2, 5, 10, 33, 11, 11, 12, 13, 16 (S 113, bounds [2, 33]), 9 round trips; gold as T11 (BUY 10 spells S 132 [2, 36], SELL 9 spells S 96 [2, 19]); 8 sleeve trades (flips while OUT both sides); tuple counts in 120,432,707,298, out 144,224,745,588, BUY 6,835,192,844,305, SELL 4,976,743,356. R3 (2015-01-02): 210 decisions, first OUT, in 7 spells S 101 [2, 30], out 8 spells S 109 [2, 33], 7 round trips, gold BUY 9 S 130 [2, 36], SELL 9 S 80 [2, 15]; tuples 271,511,233, 8,485,744,608, 426,468,399,525, 644,288,463. Weeks by n_buy 0/1/2/3: 78/35/22/93. Smoke strategy trades at 20.8 bps (SCMO_0003): 9 switch_out, 8 switch_in, 8 sleeve_rebalance, 8 basket_change.
