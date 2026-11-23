# T13 Step 2 log: the engine (2026-11-18)

`analysis/t13_engine.py` is `analysis/t11_engine.py` copied and patched by exact text replacements (each asserted to match once; the patch script was a scratch file). Line endings LF (T11's file is CRLF; the AST comparison is unaffected).

## Changes against t11_engine.py

| Where | Change |
|---|---|
| constants | `T13`, `T11E` (T11's stored headline evidence, V4(a1) only), `T11_ENGINE` (V4(c) source), `STEP1` → `tests/T13/logs/step_1_spell_counts.json`, `IN_MIN_BUY = 2`, seeds `(16, 3)`, `(16, 6)`, `(16, 11, 3)`, `(16, 11, 6)` |
| `Book.decisions(min_buy=2)` | counts `n_buy`; `state = n_buy >= 2`; `state_all3 = n_buy == 3`; new columns `n_buy`, `at_least_two_buy`, `state_all3`; `all_three_buy` now means all three BUY |
| `run_book` | headline cell: the all-3 comparator `strategy_all3` (timed) and `strategy_all3_fixed50` at every cost (stats, NAVs, trades) |
| `t11_regression` (new) | V4(a1): `state_all3`, `decision_idx`, `g` against T11's stored decisions.csv; `strategy_all3` / `strategy_all3_fixed50` / `hold_parent` / `sleeve_only` / `sleeve_only_timed` NAVs against T11's stored daily_nav.csv `strategy` / `strategy_fixed50` / same names, every session and cost, relative 1e-12 → `regression_t11.json` |
| `d17_regression` | V4(a2) runs on the all-3 state (the stored T08/T06 runs are all-3 runs) |
| `v4_identities` | takes `a1`; passes only if V4(a1) passes; `d_signals` checks `n_buy` against the signs and `state`/`state_all3` against `n_buy` |
| `shared_code_diff` | V4(c) against `t11_engine.py`: 36 functions must be AST-identical; changed exactly `run_book`, `shared_code_diff`, `d17_regression`, `v4_identities`, `main`; new exactly `t11_regression`; nothing dropped |
| `main` | paths, the audit's new per-book keys (`entry_rule`, `invested_weeks_all3`, `weeks_by_n_buy`, `weeks_in_2of3_not_all3`, `weeks_in_all3_not_2of3`), V5(a) beside-seed `[16, 6, 123456789]` (`also_seed_16`), prereg hash from T13.md |
| `READINGS` | E3, E14, E18, E21 reworded; E25 added (the comparator and V4(a1)) |

Not changed (AST-identical to T11, asserted by V4(c)): `simulate`, `trade`, `stats`, the samplers, `v3_check`, `v6_check`, R7, `common`, `raw_parent`, `cash_levels`, `window_check` and the rest. One cosmetic leftover: `spell_shuffle`'s docstring still says "Seed [14, 3, id]" (the function must stay AST-identical to T11's; the seed actually used is the module constant, 16).

## Runs

- Smoke `python analysis/t13_engine.py --run smoke --draws 20 --quick` → exit 0, 12 s, `tests/T13/evidence/smoke/`. Gates: V2 846 checks 0 violations; V3 true; **V4(a1) worst relative difference 0.0 for every pair** (the all-3 comparator reproduces T11 bit for bit), decisions equal; V4(a2) T08 and T06 worst 2.2e-16; V4(b) 4.4e-16; V4(c) true; V4(d), (e) true; V4(f) seam −0.2195, +0.3909, +0.4469, +0.1889 pp (T11's); V5 p 0.828 and 0.084 (seed 16); V6 1,881 trades, worst 3.2e-16; Step 1 counts and frozen-text counts true. Strategy trades at 20.8 bps (SCMO_0003): 9 switch_out, 8 switch_in, 8 sleeve_rebalance, 8 basket_change.
- Scratch, 4 books, 100 draws: `--run scratch4 --draws 100 --outdir <scratchpad>/t13_scratch4` → exit 0 (for testing the verifier and the scripts; not evidence).
- No performance figure was printed or read.

Evidence contract deltas: `logs/evidence_contract.md`.
