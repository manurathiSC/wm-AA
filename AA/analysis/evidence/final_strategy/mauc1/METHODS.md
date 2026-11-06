# Methods: gold's trend on MAUc1 (`report.html`)

Code:
- `AA/analysis/mauc1_signal.py`: cleaning, weekly candles, supertrend, review read-out, comparison.
- `mauc1_report.py`: this page.

## Data

**Source.** `C:\Users\manur\Downloads\MAUc1_daily1.csv`, the user's Eikon export of MCX gold futures, continuous first month (₹ per 10 g), with daily open, high, low, close and volume. It runs 2015-02-02 → 2026-09-28, 3,000 rows.

**Cleaning** (`mauc1_cleaning_log.csv`; result in `mauc1_daily_clean.csv`, 2,997 rows):
- **Dropped:** 3 rows with no close, all stale copies of the previous day on holidays (2015-10-02, 2015-11-11, 2020-04-14).
- **Close-only rows:** 3 rows (2021-10-04, 2025-01-02, 2026-02-04). The close is kept, and open, high and low are set to it.
- **Widened:** 1 bar whose close lay above its high (2023-10-16). High and low were set to the max and min of open, high, low and close.

## Signal

**Source: the desk's production ST.py, unmodified** (`mauc1_st_production.py`):
- **Same code.** ST.py, QuantBacktester.py, ProspectTheory.py and analysis_master.py are copied byte for byte from the Friday Rebalance Automation folder, with sha256 checked on every run (`Historical Data/FRA_MAUc1/run_manifest.json`).
- **Same call.** `ST.run(scrip, 'W', 2, True, …, TradingDays.xlsx)`, then `analysis_master.build_analysis_master`, exactly as `weekly_rebalance_nse_v2.py` runs it for Nifty 100, Midcap 100 and Smallcap 100.
- **Same layout.** The outputs are laid out like the desk's folders:
  - `RSI/Final/MAUc1/W_allRebal.xlsx`;
  - dated `W_allRebal_<ddmmyy>.xlsx`, one for each production Friday since 2026-07-03;
  - the `indexDf` / `weekIndexDf` / `monthIndexDf` intermediates;
  - `RSI/Final/Analysis/Master_MAUc1.xlsx`, which adds SIGN.
- **Harness proof.** The same harness re-runs production's three equity indices from its own `indices_ohlcv.xlsx` and matches its 2026-09-25 `W_allRebal.xlsx` in every cell (max difference 0.0), with 0 SIGN differences.

**Weekly candles, as ST.py builds them:**
- The MAUc1 daily bars are put on the NSE trading calendar (`TradingDays.xlsx`, built from Nifty 50) and forward-filled.
- They are grouped by ISO week and labelled by the week's last NSE session, which is the review.
- High = max, low = min, close = last.
- Two effects of the NSE calendar:
  - The 118 MCX sessions on NSE holidays (2015-02 → 2026-09) are not in the candles.
  - The 3 NSE days without an MCX bar repeat the previous bar.
- The first trend value is on the 6th candle, 2015-03-13.

**Supertrend (ST.py):**
- ATR = the linearly weighted mean of the last 5 weekly true ranges (weights 1–5 ÷ 15).
- Bands = (high + low) ÷ 2 ± 2 × ATR, with the production ratchet.
- SIGN (analysis_master.py) is BUY when the trend line sits on the lower band.

**Checks** (`mauc1_st_compare.py`; files in `st_production/`):
- **Port check.** The Python port (`supertrend.py`) on ST.py's own candles gives the same line to 6e-11 from the 5th signal week, with no SIGN difference in any week.
- **Previous method.** Before 2026-09-29 the signal used candles cut at each review, which keep the MCX sessions on NSE holidays. Those candles differ in 48 of 603 weeks, but the signal is the same in all 603.
- **The backtest's reads.** Of the 597 reads made before the switch, 596 agree. The exception, 2015-03-05, is a start-up week that ST.py has no signal for yet, and the books held equity that week.
- **Every step** is in `mauc1_supertrend_weekly.csv`.

**Operational note.** The Friday job runs at about 20:00 IST, while MCX trades until 23:30. A live Friday run would see a partial MCX bar. These files use settled closes.

**At each weekly rebalance** (`mauc1_signal_on_reviews.csv`):
- **Reviews and trade sessions:** the final-strategy runs' review dates from the first signal (2015-03-13 → 2026-08-21), 596 reviews, with each review's trade session (the next session, normally Monday).
- **Signal read:** each review reads the latest ST.py week on or before it, which is its own week.
- **Shading:** a signal is in force from its review's trade session until the next review's trade session.

## Charts and tables

| Element | What it shows |
|---|---|
| **Main chart** | MAUc1 close ÷ its 2015-02-02 close, on a log scale. Shaded where the MAUc1 signal in force is SELL. |
| **Strip** | Where each signal in force is SELL (MAUc1; GOLDBEES from `../gold_supertrend_weekly_goldbees.csv`, Friday-close Eikon GBES.NS candles), and the days on which they differ. |
| **KPIs** | Share of reviews in BUY, number of flips, and the agreement rate over 596 reviews (`mauc1_summary.csv`). |
| **Disagreement table** (`mauc1_disagreement_outcomes.csv`) | Each run of reviews where the two signals differ. It runs from the first review's trade session to the trade session of the review where they agree again. Returns are close to close for MAUc1 and for GOLDBEES (Eikon close). "Right" = the signal whose call (BUY = rise, SELL = fall) matched GOLDBEES's return over the stretch. |

## Caveats

- **Short, hand-cleaned history.** The history starts in 2015-02, later than GOLDBEES (2014-07), and 7 rows were cleaned by hand.
- **Continuous-contract rolls.** A continuous futures series has roll effects. No roll jump stands out in the data (the largest daily moves are real events: −11.7% on 2026-01-30, −5.8% on 2024-07-23).
- **Now in the backtest.** The final-strategy backtest reads this signal from `Master_MAUc1.xlsx` (2026-09-29).
