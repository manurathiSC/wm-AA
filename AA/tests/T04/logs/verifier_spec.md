# Spec for `analysis/verify_t04.py` (independent verifier, gate V1)

The verifier re-derives T04's numbers from the raw files and compares them with the engine's shipped evidence. It **must not read or import `analysis/t04_engine.py`, `analysis/t03_engine.py`, `analysis/verify_t03.py`, or any other file in `analysis/` or `data/` except the raw inputs below**. Read only: the raw inputs, `tests/T04/T04.md` §3 (the frozen pre-registration — it is the full specification; where it is silent, say so in the output instead of guessing silently), this spec, and the evidence in `tests/T04/evidence/headline/`.

## Raw inputs (paths from `AA/`)

| What | Path |
|---|---|
| published NAV, calendar | `Historical Data/parent_nav_2026-10-22/SCMO_0003.csv` (cols `_id.date` YYYY/MM/DD, `index`) |
| stock OHLC | `data/holdings_matrix/SCMO_0003_ohlc.csv` (date, stock, open, high, low, close, src) |
| price correction | `data/holdings_matrix/price_corrections.csv` (prices before `ex_date` × `factor` for the listed stock and parent; nothing applies to SCMO_0003, but implement it) |
| baskets | `data/holdings_matrix/SCMO_0003_holding_weight_matrix.csv` (rows = availableDate, cols = stock), `SCMO_0003_holding_weight_sources.csv` (drop `csv_only_skipped`) |
| signals | `Historical Data/extended_2026-10-30/Master/Master_{Nifty100,MC100,SC100}.xlsx` (`Date`, `SIGN`; drop blank SIGN) |
| GOLDBEES | `analysis/cache/why_gold_ohlc_eikon_extended_2026-11-04.parquet` (date, open, high, low, close) |
| MCX gold (de-spike only) | `analysis/evidence/final_strategy/mauc1/mauc1_daily_clean.csv` (first column date; open, high, low, close, volume) |
| cash | `Historical Data/LBES_Adjusted_Price_data_extended_2026-11-05.csv` (date `%d/%m/%y %H:%M`, price) |
| LIQUIDCASE (R3) | `Historical Data/liquidEtfFinal_extended_2026-11-05.csv` (date dd-mm-yyyy, liquid_case) |

## Conventions the T04.md text leaves to the code (fixed here, same text as the engine's readings)

1. **GOLDBEES fill (de-spiked OHLC4):** rng = (MCX high − low) / MCX close that date (NaN if no MCX bar), band = rng + 0.005, lo = close·(1−band), hi = close·(1+band). Where rng is not NaN: open′ = clip(open, lo, hi), high′ = min(high, hi), low′ = max(low, lo); then high′ = max(high′, open′, close), low′ = min(low′, open′, close). Where rng is NaN: the raw bar. Fill = (open′+high′+low′+close)/4. Valuation = close forward-filled onto the calendar; if the fill is missing on a calendar date, use the valuation close.
2. **Stock fill** = OHLC4 of the bar; if open, high or low is blank the close; if the stock has no bar that session its last close. Stock valuation = close, forward-filled over D18's dates onto the calendar.
3. **Cash level** = LBES price as-of (latest row on or before the session). R3: LBES up to the session before 2024-01-24, then `base × liquid_case[t] / liquid_case[last session before 2024-01-24]` (liquid_case as-of on sessions).
4. **Calendar**: T04.md §3 step 1. **Decisions**: step 2 and 3 (ISO weeks by `isocalendar()` year and week).
5. **Basket in force at session t** = latest basket whose availableDate ≤ t's first calendar session on or after it (a basket takes effect on the first calendar session on or after its availableDate). Basket at T0 = latest with effect on or before T0.
6. **Initial position**: T04.md §3 step 9; the units of the drifted basket use OHLC4 on the first D18 date on or after the basket's availableDate (that date can be before T0), scaled so the value at T0's close is 1.
7. **Events and trades**: step 7 and 8. The decision in force at session t is the latest decision j with trade session (decision session + 1) ≤ t, and decision 0 until decision 1's trade session. An event session is every decision's next session (for j ≥ 1, that is < the number of sessions) and every session where a new basket takes effect (not T0). A trade happens at an event session iff the target stock-weight vector (kept stocks at their normalised basket weights) differs exactly from the last target; the last target at T0 is T0's own target.
8. **Indicators**: step 5. The weekly SuperTrend algorithm is in the supertrend description in step 5; the final-band recursion is: `FUB = BUB if (BUB < prevFUB or prevClose > prevFUB) else prevFUB`; `FLB = BLB if (BLB > prevFLB or prevClose < prevFLB) else prevFLB`; ST latches, tested in this order: if prevST == prevFUB and close ≤ FUB: ST = FUB; elif prevST == prevFUB and close > FUB: ST = FLB; elif prevST == prevFLB and close ≥ FLB: ST = FLB; elif prevST == prevFLB and close < FUB: ST = FUB; else 0. **Clarification added 2026-11-06 after the first verifier run:** the first version of this sentence read as if the last test replaced the `close ≥ FLB` test; it does not. The 4th test is only reached when close < FLB (< FUB), so it is equivalent to 'else FUB'. The verifier's first reading (B) disagreed with the engine on I5 only; the engine's I5 matches the desk port `analysis/supertrend.py` on all 4,084 stock-dates of 123 stocks, and the verifier with the ordered reading (A) matches the engine everywhere (first run kept as `verify_t04_stB_first_run.json`). The first defined candle (5th) has FUB = BUB, FLB = BLB, ST = FUB. BUY iff |ST − FLB| < 1e-9. `prevClose` is the previous weekly candle's close.
9. **Null draws**: step 11. `u = default_rng([4, i, draw_id]).random((J, N))`, i = 1..5 for I1..I5, J = number of decisions of the window, N = number of columns of the weight matrix (column order of the file). On SELL decision j and basket b with k_j(b) = the indicator's count (pass set ∩ basket): keep the k stocks of basket b (stocks with weight > 0, in column order) with the smallest `u[j]` (stable sort); k = 0 keeps none; k ≥ n keeps all.
10. **Percentile**: T04.md §2 (not needed for V1).
11. **Windows**: `full` = 2019-01-02 → 2026-11-04; `live` = first calendar session on or after 2021-11-01 → 2026-11-04 with its own decisions (T0 of the window plus last session of each later ISO week), own k counts (indicator on the window's decision dates), own u of shape (J_live, N); always-in V4 window = 2019-01-02 → 2026-10-22.

## Evidence schemas (engine side; column names as written)

- `decisions.csv`: j, decision_date, decision_idx, trade_date, sign_Nifty100/MC100/SC100, label_*, latest_label, label_age_days, state (1 BUY / 0 SELL), regime.
- `indicators.csv`: one row per full-window decision and stock in the basket at its trade session: decision_date, stock, weight, valid, last_bar, close_used, ema50, ema200, sma50, sma200, st_sign, pass_I1…pass_I5.
- `selections.csv`: window (full|live), indicator, j, decision_date, regime, basket_eff, n, k, kept (`;`-separated), nontrivial.
- `trades.csv`: indicator (I1…I5 / hold_parent / full_aa_switch), cost_bps, date, idx, decision_j, regime, basket_eff, n_kept, n_basket, stock_weight, V, traded, cost, nav_close_after, kept.
- `stats.csv`: kind (strategy / hold_parent / full_aa_switch / constant_mix), indicator, window, sleeve (50_50 | gold100), cash (lbes | liquidcase), cost_bps, end_nav, cagr, max_dd, vol, trades, cost_paid, mean_equity_share…
- `draws.csv`: indicator, window, sleeve, cash, cost_bps, draw_id, end_nav, cagr, max_dd, trades, cost_paid…
- `daily_nav.csv`: kind, indicator, cost_bps, date, nav (strategy rows are full window, 50_50, LBES).

## Checks the verifier must do (counts of compared and failed per check, to stdout and `evidence/headline/verify_t04.json`)

- **C-dec:** every row of `decisions.csv` against its own derivation.
- **C-ind:** for every row of `indicators.csv`: valid, close_used, each average, st_sign and the five pass flags, relative 1e-9; plus, for 300 random (stock, decision date) pairs *not* restricted to a basket, the same values from its own table.
- **C-sel:** every row of `selections.csv` (both windows): n, k, kept set.
- **C-pit:** every Master label date ≤ decision date, every indicator bar date ≤ decision date, every trade date after its decision date (except basket-change sessions).
- **C-nav0:** at 0 cost, for every indicator, the strategy's end NAV and every daily NAV against `daily_nav.csv`, relative 1e-9.
- **C-cost:** at 20.8 and 50 bps, end NAV, CAGR, max drawdown against `stats.csv`; also R1 (gold100) and R3 (liquidcase) at 20.8 and the live window at 20.8, strategy rows.
- **C-trades:** trade dates, regimes, kept sets and number of trades against `trades.csv`, every indicator and cost, plus hold_parent and full_aa_switch.
- **C-null:** reproduce, per indicator, draws 0…19 and 20 random draw ids at every (window, sleeve, cash, cost) variant present in `draws.csv`: end NAV, CAGR, max drawdown (relative 1e-9); and for every draw it reproduces, that the number kept equals k on every SELL decision (and the BUY targets equal the whole basket).
- **C-comp:** the constant mix and the full AA switch at each cost (`stats.csv` end NAV).
- **C-always-in:** always-IN at 0 cost against the published NAV, 2019-01-02 → 2026-10-22: print the CAGR gap and the worst calendar-year gap (G0: ±0.25 pp/yr overall, ±0.5 pp each year).
- **C-corrupt:** on a corrupted copy of the evidence in a scratch directory (flip 5 decisions, scale a NAV column by 1.001, change one `k`) the verifier must exit non-zero; the real run exits 0 only if rows were compared in every check and none failed. "Compared nothing" is a non-zero exit.

If the verifier disagrees with the engine, do **not** adjust either to make them agree: report the first differing row and the reading that differs, so Manu can decide which side is wrong.
