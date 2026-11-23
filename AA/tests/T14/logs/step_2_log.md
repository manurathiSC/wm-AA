# T14 Step 2 log: the engine (2026-11-23)

**Status: DONE.** `analysis/t14_engine.py` (about 1,770 lines) runs both windows; smoke run `--quick` (first book, 20 draws, `--outdir` in the scratchpad) exits 0 for **both** windows with V2–V6, the Step 1 count reproduction and the frozen-text counts passing, and **V4(a) exact**.

## How it was built

A fork of `t11_engine.py` assembled by a builder script: 25 functions are copied **verbatim by AST** from `t11_engine.py` (trade, stats, sessions_invested, spells, spell_sig, spell_shuffle, series_bounds, count_table, draw_lengths, free_length_draw, ie_count, lens_of, v3_check, n_sleeve_trades, gold_spells_with_out, flip_counts, chi2_sf_even, sampler_selftest_small, flush_draws, held_either, flagged_days, zero_return_book, one_instrument_identity, baskets_table, held_src_counts); `shared_code_diff` (V4(d)) re-checks that they are still AST-identical, that `trade`'s arithmetic lines are present in both engines and that nothing else changed unexpectedly (expected changes are listed). New code: the window configuration, `targets` / `rule_arrays`, `trade_basket_partial` and the extended `simulate`, `run_book` over six rules, the regime ledger, V4/V6 for the new rules, the per-book process pool.

## Change list against `t11_engine.py` (what a reviewer must look at)

1. **`WINDOWS`** (W1 = T11's inputs; W2 = T08's: D17-extended calendar per book from its first date, END = last D03 Master row, D24 signal and weekly csv, D12 MCX range, T08's seeds, `liq_from` 2024-01-24, R3 "live" from 2021-11-01 with the full-window bounds). `common(win)`, `Book(parent, win, ...)`, `raw_parent(p, end)`, `cash_levels(cal, kind, win)`, `read_pub`.
2. **Six rules**: `targets(rule, in, g)` (scalar) and `rule_arrays` (vectorised; the V4(d) signals check asserts they agree on every decision); `regime_codes`; `trades_due`.
3. **`simulate(..., reg=None)`**: with `reg` (passed for `-half`/`-liq` only) a trade into or out of OUT-SELL is `regime_in` / `regime_out`, and a parent rebalance while `0 < e < 1` is the **D1 partial trade** `trade_basket_partial`. With `reg=None` the function is T11's, so the `-orig` rules and the constant mixes are unchanged (e is only 0 or 1 for them).
4. **Draws**: every draw runs all six rules (F1–F4 at 0/20.8/50, F5 at 20.8, R2/R3 F1 and F3 at 20.8); `draws.csv` has a `rule` column, `out_sell_weeks` and `trades_due`; the NAV curves are stored for 40 draw ids per family (first 20 + 20 from `default_rng([17, 1])`), not for all 2,000. The draws are **regenerated from T11's / T08's seeds** and asserted equal to their stored `draw_states.npz` (V3).
5. **Gates**: V4(a) compares the `-orig` rules with the stored NAVs (W1 vs T11; W2 vs T08 and, for `50-orig`, T06 to 2026-10-22) and the `-orig` rows of `draws.csv` with the stored `draws.csv`; V4(f) is W1's 2019 seam (from the W2 book's hold-parent path) and W2's G0; V6 adds half-entry, partial-basket, liq-regime identities; the window checks compare the engine's own counts with `step_1_spell_counts.json`.
6. **Comparators**: `hold_parent`, `constant_mix`, `constant_mix_timed`, `sleeve_only`, `sleeve_only_timed` (T08/T11's, regression-checked), plus `cmix_<rule>` (T14.md §2.3: constant mix at the rule's own average parent share and own average gold share of the rest).
7. **Dropped from T11**: the `--calendar d17` mode (W2 is now a full window; its regression is V4(a) itself), `d17_regression`, `seam_check`, `STEP1` bounds asserts specific to T11's JSON (replaced by T14's).

## Smoke results (structure only; no performance figure was read)

W1 and W2, 1 book, 20 draws: V2 1,579 / 2,404 checks, 0 violations; V3 pass including equality with the stored draw states of T11 / T08; V4(a): 21 / 30 NAV rows reproduced to max relative difference **0.0**, draw rows equal; V5 pass; V6 pass (6,417 / 11,277 trades; worst identity 3.8e-16 / 5.2e-16; 48 half-regime entries, 48 liq trades and 18 partial basket changes exercised in each window); the seam gap of SCMO_0003 on 2019 is −0.22 pp (T11 recorded −0.22), W2's G0 passes. One bug found and fixed on the way: V6's partial-basket identity matched the `cmix_*-half` comparator runs (full resets) by name; the gate now tests the run ids `50-half` / `80-half`.

## Run time

20 draws, one book: 5 s (W1) and 6 s (W2). Scaled to 2,000 draws: about 10 minutes per book; the four books run in four processes, so about 10 to 15 minutes per window (`--workers 4`), W1 and W2 can run side by side. `draws.csv` is about 280 MB per window at 2,000 draws: **in `.gitignore`** (one-line reason there).

## Notes that affect later steps

- **AFFECTS STEP 3 / 4:** see `evidence_contract.md` for every file and column. `draw_curves` are float64 and only for the stored ids; the R6 paired contrast and the D-table are computed by Step 4's `analyse.py` from `draws.csv` / `stats.csv` / `regime_ledger.csv`.
- The engine does not print percentiles or any performance figure.
- `r3` for W2 is called `live` in T08's stored files; the engine's own name is `r3` in both windows.
