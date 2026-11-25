# T15 Step 2 log: engine (2026-11-25)

`analysis/t15_engine.py` (about 1,000 lines), a fork of `t14_engine.py`: copied, not imported; the null machinery (draws, samplers, seeds, `draws.csv`, `draw_states.npz`, R7) is removed; index lines are added to `Book`, `trade`, `simulate`. Command: `python analysis/t15_engine.py [--run NAME] [--window w1|w2|both] [--quick] [--books ...] [--workers N] [--outdir DIR]` (from `AA/`); default output `tests/T15/evidence/<run>/{w1,w2}/`.

## Result of the smoke runs (no result number read; gates and counts only)

- One book, both windows (`--quick`): exit 0, V2 / V3 / V4 / V5 and the step-1 counts pass.
- All four books, both windows, scratch directory `C:\Users\manur\AppData\Local\Temp\claude\d384933f9ddb0ecb\894e698e-0352-47dc-93ef-b966fdca4107\scratchpad\full4\{w1,w2}` (43 seconds in all, W1 24 s and W2 18 s): all gates pass.
  - **V4(a) exact:** the six T14 rules and hold-the-parent reproduce T14's stored `daily_nav.csv` (84 rows per window: 4 books x 7 runs x 3 costs) and `trades.csv` (84 rows per window) with a worst relative difference of **0.0** (bit-identical): the generalised `trade` adds zero-valued index terms and keeps T14's arithmetic order.
  - V4(b): `-idx` priced on cash equals `-liq` to 1.8e-15; V4(c): equal to 0.0 on the sessions before the first index trade (W1 SCMO_0003: first index trade 2014-10-20, 31 sessions); V4(d): the AST diff lists only the expected changes; V4(e): signals and B equal the Master / weekly files at every decision; V4(f): one-instrument identity and the G0 / seam checks pass.
  - V3: the Master `Index` column equals the D25 / D25c close on every label date used (W1 681 labels, W2 1,215, 0 violations).
  - V5: 3,372 (W1) and 4,503 (W2) trades checked at worst 5.8e-16; the `-idx` trades into or inside OUT-SELL leave each index of B and cash at 1/(k+1) to 1.8e-16.
  - Step 1's counts (T15.md section 2) are reproduced by the engine's own series for every book and both R3 windows.
- Run time is **under a minute for both windows** (PLAN section 10 item 6 guessed "a few minutes per window").

## Engine readings (decided here, written into `evidence_contract.md`)

1. **Absolute shares.** A target is (parent, GOLDBEES, cash, three index shares) summing to 1. For the six T14 rules GOLDBEES = (1-e)*gw and cash = (1-e)*(1-gw), so Tg = gold*V is T14's `(1 - e_new) * gw_new * V` in the same floating-point order.
2. **Trade kinds for `-idx`**: `regime_in` / `regime_out` at every change of OUT-SELL membership (an OUT-BUY -> OUT-SELL week with the same e = 0 is `regime_in`); `index_set_change` for B changing with OUT-SELL on both sides; `switch_in` / `switch_out` between IN and OUT-BUY.
3. **R3 windows start in OUT-SELL** (found at Step 1): `-idx` then starts holding cash and the indices of B at T0's closes (free initial position), written into T15.md section 3 item 7 before the freeze.
4. **Ledger span** (T15.md 2.4 says "first fill to last fill"): a = the session on which the first decision of the span is traded, b = the session on which the decision that ends it is traded, closes at a and b. This differs from T14's (decision-session closes); stated in `evidence_contract.md` and `READINGS["E13"]`. It is a descriptive table only.
5. **Index returns for `hold_<index>`**: the price index from T0's close, no cost, no trades (a comparator, 20.8 only; cost-independent).
6. **Constant mixes** (`cmix_<rule>`, 20.8 only) for all eight rules use the means of the weekly target shares; the six T14 rules' mixes are not compared with T14's (a different parametrisation, same weights up to rounding), only the rules and hold-the-parent are the regression.
7. **Draw-free R3 / R2 / R4 / R5** are extra deterministic runs at 20.8 bps (R1 is the headline's 0 and 50 bps). R4 runs `-idx` only (the other rules do not depend on B).
8. **V4(d)**: `targets` gained an assert (`kind in orig, half, liq`) and is on the expected-changed list; `trades_due` and the data-loading functions (`read_pub`, `raw_parent`, `cash_levels`, `stats`, ...) are required identical to T14's.

## Not done / untested

- The independent verifier (Step 3) and the analysis scripts (Step 4) do not exist yet.
- The headline run directory `tests/T15/evidence/headline/` is not written yet (Step 5); the scratch directory above is not evidence.
