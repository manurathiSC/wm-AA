# Spec for `analysis/verify_t03.py` (Step 4, independent verifier)

The verifier re-derives T03's numbers from the raw files and compares them with the engine's shipped evidence. It **must not read or import `analysis/t03_engine.py`, any other file in `analysis/`, or `data/parent_rebuild_hm.py`**. Read only: the raw inputs below, `tests/T03/T03.md` §3 (the pre-registration), this spec, and the engine's evidence in `tests/T03/evidence/headline/` (`decisions.csv`, `stats.csv`, `draws.csv`, `trades.csv`, `daily_nav.csv`, `audit.json`, `inputs.csv`). `audit.json["readings"]` lists the engine's readings E1-E15; this spec is the same text.

## Raw inputs (paths from `AA/`)

| What | Path |
|---|---|
| published NAV and calendar | `Historical Data/parent_nav_2026-10-22/SCMO_<p>.csv` (cols `_id.date` YYYY/MM/DD, `index`) |
| stock OHLC | `data/holdings_matrix/<p>_ohlc.csv` (date, stock, open, high, low, close, src) |
| price correction | `data/holdings_matrix/price_corrections.csv` (prices dated **before** `ex_date` are multiplied by `factor`, for `stock` in the parents listed in `applies_to`) |
| basket weights | `data/holdings_matrix/<p>_holding_weight_matrix.csv` (rows = availableDate, cols = stock); drop the rows whose `source` is `csv_only_skipped` in `<p>_holding_weight_sources.csv`; renormalise each row to sum 1 |
| signals | `Historical Data/frozen_2026-09-25/Master/Master_{Nifty100,MC100,SC100}.xlsx` (cols `Date`, `SIGN`; drop blank SIGN) |
| GOLDBEES | `analysis/cache/why_gold_ohlc_eikon.parquet` (date, open, high, low, close) |
| MCX gold (de-spike only) | `analysis/evidence/final_strategy/mauc1/mauc1_daily_clean.csv` (first column date, open, high, low, close, volume) |
| cash | `Historical Data/LBES_Adjusted_Price_data_2026_08_10.csv` (date `%d/%m/%y %H:%M`, price) |
| LIQUIDCASE (R3 only, optional) | `Historical Data/liquidEtfFinal_extended_2026-11-05.csv` |

Parents: SCMO_0003, 0007, 0010, 0029. Window per book: from the first date of its published NAV (2019-01-02; 0007 2019-01-04) to **2026-08-21**.

## Rules (all must be implemented from this text)

1. **Calendar** = the published NAV's dates in the window. No other date is ever read (D18 has 8 extra sessions).
2. **Stock prices.** Apply the price correction. Close series: forward-fill over D18's dates. Fill price = (open+high+low+close)/4 of the bar; if any of open/high/low is blank, the close; if the stock has no bar that session, its last close.
3. **GOLDBEES fill price (de-spiked OHLC4).** rng = (MCX high − low) / MCX close on that date (NaN if no MCX bar), band = rng + 0.005, lo = close·(1−band), hi = close·(1+band). Where rng is not NaN: open' = clip(open, lo, hi), high' = min(high, hi), low' = max(low, lo); then high' = max(high', open', close), low' = min(low', open', close). Where rng is NaN: raw bar. Fill = (open'+high'+low'+close)/4. GOLDBEES valuation = close, forward-filled onto the calendar; if the fill is missing on a calendar date use the valuation close.
4. **Cash level** = LBES price as-of (latest file row on or before the session). After the file's last date (2026-08-09) the level on the k-th session after it is `L(2026-08-09) · (1+r)^k`, with r = (A(s)/A(s−90))^(1/90) − 1, A = the as-of level on calendar sessions, s = the last session on or before 2026-08-09, s−90 = 90 sessions earlier.
5. **Decisions.** Decision dates = T0 (first window date) and the last calendar session of every later ISO week. At decision date d, for each of the three Master files take the latest row dated on or before d; state = 1 (IN) iff all three SIGN are BUY, else 0 (OUT). The decision on the window's last session is not traded.
6. **Baskets.** A basket takes effect on the first calendar session on or after its availableDate. The basket in force at T0 is the latest with effect on or before T0.
7. **Initial position at T0 close** (no cost), NAV 1.000: OUT = 50% GOLDBEES and 50% cash at the closes/levels of T0. IN = the basket in force at T0 held as it has drifted: shares = w / fill price on the first **D18** date on or after that basket's availableDate (use the D18 dates, since that date can be before T0); scale the shares so the value at T0's close is 1.
8. **Trades.** A trade happens at the session after a decision date (the next calendar session) when the state differs from the previous decision's, and also on a basket-change session while IN. At trade session t with e = new stock share (1 IN, 0 OUT): V = Σ shares·fill + GOLDBEES units·GOLDBEES fill + cash units·cash level. Targets: stock i: e·V·w_i (w = the basket in force at t, i.e. the latest with effect on or before t); GOLDBEES and cash: (1−e)/2·V each. traded = Σ |target − current value| over every line (stocks, GOLDBEES, cash). cost = traded·cost_bps/2/10,000. New units = (target·(V−cost)/V) / price. While OUT a basket change trades nothing (the basket in force is tracked). A switch and a basket change on the same session are one trade into/out of the basket in force.
9. **NAV** each session = Σ shares·close + GOLDBEES units·close + cash units·level, with the units after any trade on that session. NAV is 1.000 at T0's close. No sale at the end.
10. **Statistics.** years = (sessions − 1)/252; CAGR = NAV_end^(1/years) − 1; max drawdown = min(NAV/running peak − 1); volatility = SD (ddof 1) of daily returns × √252.
11. **Comparators** (optional): hold the parent (e = 1 always), sleeve only (e = 0 always), constant mix (e = f, f = invested decisions / decisions, rebalanced at every decision's next session and at every basket change).
12. **Null draws.** N4.9: from the decision states s_0…s_n, cut maximal runs; shuffle the in-runs among themselves and the out-runs among themselves with `numpy.random.default_rng([3, draw_id])`: **first** `rng.permutation(len(ins))` then `rng.permutation(len(outs))`, `ins`/`outs` in order of appearance; interleave starting in s_0's state. Circular shift: `np.roll(s, k)` for 46 ≤ k ≤ n−46.

## Checks the verifier must do

- **C-dec:** every row of `decisions.csv` (signs, labels, state, decision date, trade date) against its own derivation. 0 mismatches.
- **C-pit:** every label date ≤ decision date; every trade date after its decision date.
- **C-nav0:** at 0 cost the strategy's **end NAV** and **every daily NAV** against `daily_nav.csv` (run = `strategy`, cost 0), relative 1e-9; also the closed form: between trades units are fixed, so NAV is the product of segment growth factors (state it in the output).
- **C-cost:** the same at 20.8 and 50 bps (the verifier's own cost implementation), end NAV and CAGR and max drawdown against `stats.csv`.
- **C-trades:** trade dates, kinds and number of trades against `trades.csv` for the strategy runs.
- **C-null:** reproduce the first 20 and 20 random N4.9 draws per book at 20.8 bps (draw ids and end NAVs in `draws.csv`; compare CAGR, max drawdown, end NAV, relative 1e-9) and 10 circular shifts; verify for **all** N4.9 draws in `draws.csv` that invested weeks, spell counts and sorted spell lengths equal the strategy's (derive the shuffled states yourself for every draw_id 0…1999 and compare with the engine's `spell_sig`-free columns `invested_weeks`, `n_in_spells`, `n_out_spells`).
- **C-always-in:** always-IN at 0 cost against the published NAV: print the CAGR gap and worst calendar-year gap (G0: ±0.25 pp/yr, ±0.5 pp), run to 2026-10-22.
- **C-corrupt:** run on a corrupted copy of the evidence in a scratch directory (flip 5 decisions, scale a NAV column by 1.001) and exit non-zero there; the real run exits 0 only if rows were compared and none failed ("compared nothing" = non-zero exit).

Output: counts of checks compared and failed per check, to stdout and `tests/T03/evidence/headline/verify_t03.json`. Write findings in the log; do not edit the engine or the evidence. If the verifier disagrees with the engine, do **not** adjust either to make them agree: report the first differing row and the reading that differs.
