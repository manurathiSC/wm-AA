# Final strategy test: methods

Code:
- `AA/analysis/final_strategy.py`: harness runs and all CSVs.
- `final_strategy_excel.py`: builds the workbook.
- `final_strategy_verify.py`: evaluates the workbook's formulas with pycel and reconciles them.

## Rule

1. **Equity.** At each Friday review, if the production weekly SIGN of Nifty 100, Nifty Midcap 100 and Nifty Smallcap 100 are all BUY, the book holds 100% of the parent portfolio (its current basket at its published weights).
2. **Sleeve.** Otherwise the book holds 100% sleeve, gold (GOLDBEES) plus cash (LBES). The split follows gold's weekly supertrend computed on **MAUc1** (MCX gold futures, continuous first month):
   - 80% GOLDBEES / 20% cash if MAUc1's supertrend is BUY at that review;
   - 20% GOLDBEES / 80% cash if it is SELL;
   - 50/50 before MAUc1's first signal (review 2015-03-13). This covers two sleeve spells in 2014-10 → 2015-02.
   - The earlier version read gold's trend from GOLDBEES itself. It is kept as the comparator "variant: final rule with the GOLDBEES gold signal (previous)", and its full outputs are in `previous_goldbees_signal/`.
3. **When the split is decided.** The split is only decided while the book is in the sleeve.
   - **FINAL:** re-checked at every weekly review in the sleeve.
   - **Variant:** fixed at the review that moves the book into the sleeve, and held until equity resumes.
4. **Timing and prices.**
   - **Signal:** known at Friday's close, from that week's weekly candle.
   - **Trade day:** the next session — Monday (238 of 250 live reviews and 358 of 381 in 2014–21), or Tuesday when Monday is a holiday.
   - **Holiday weeks:** when Friday is a holiday the candle closes on Thursday. In a few production weeks the index candle closes on a special Saturday or Sunday session (2016-10-30, 2019-10-27, 2020-11-14, 2024-01-20, 2024-05-18). There the Master file dates the signal on that day, and the trade is the next session.
   - **Fill prices:**
     - every stock at OHLC4 = (open + high + low + close) ÷ 4 of that session, with a close fallback when a leg is missing;
     - GOLDBEES at the OHLC4 of that session after de-spiking: its open, high and low are pulled into close × (1 ± (MCX gold's high−low range that day ÷ its close + 0.5%)).
       - This removes ETF-only prints, such as the 2026-03-04 low 22% below the close on a day MCX gold moved 1.7% (`goldbees_spikes/`).
       - It changes the fill on 552 of 3,019 days (median 43 bps), but on only 5 of the backtest's 49 GOLDBEES trade days (5 bps on average).
       - The inputs, the band and the result for every day are in `goldbees_fill_despiked.csv`, and in the workbook's GOLDBEES_fill sheet.
     - cash (LBES) at its daily level.
   - **No-trade weeks:** nothing trades while the target is unchanged, so holdings drift.
   - **Cost:** 10.4 bps on the value traded (20.8 bps round trip).
   - **Trade-day value:** the book is valued at that session's close (`Simulator.run(close_on_trade_day=True)`). The default elsewhere values it at the fill prices.

## Signals

- **Index signals.** The SIGN column of `AA/Historical Data/frozen_2026-09-25/Master/Master_{Nifty100,MC100,SC100}.xlsx`.
  - These are copies of the production files `Friday Rebalance Automation/RSI/Final/Analysis/Master_*.xlsx` on the shared Drive (Investment Research_N/Shubham_Shreshtha), as written by the 2026-09-18 weekly run.
  - Checked on 2026-09-29 against the current production files, which have one more week (2026-09-25): SIGN and ST are identical on every shared week (MC100: 1,100 of 1,100). They also agree with each index's `RSI/Final/<index>/W_allRebal.xlsx`.
  - The same-named files under `test_outputs/case_*` are unrelated test cases.
  - The signals reproduce exactly from the frozen index prices (`verify_master_signs.py`).
  - Live window: the harness review grid (`segment_v2.window_reviews`), with MC100 aligned by forward fill of at most one week.
  - 2014-21: the SC100 Master dates, with the other signals aligned the same way.
- **Gold signal (MAUc1).**
  - **Data:** MAUc1 daily OHLC from the user's Eikon export `C:/Users/manur/Downloads/MAUc1_daily1.csv`, 2015-02-02 → 2026-09-28. Cleaned by `mauc1_signal.load_clean`: 3 no-close holiday rows dropped, 3 close-only rows filled, 1 bar widened (`mauc1/mauc1_cleaning_log.csv`).
  - **Signal source: production ST.py, unmodified.** `mauc1_st_production.py` runs the desk's `Python_Scripts/ST.py` and `analysis_master.py` on MAUc1. The files are byte-identical copies with sha256 checked; the call is `ST.run(scrip, 'W', 2, True, …)`, the same one `weekly_rebalance_nse_v2.py` makes for the indices.
    - The output is laid out like the desk's index folders, in `AA/Historical Data/FRA_MAUc1/`:
      - `RSI/Final/MAUc1/W_allRebal.xlsx`;
      - the dated `W_allRebal_<ddmmyy>.xlsx` files and the intermediates;
      - `RSI/Final/Analysis/Master_MAUc1.xlsx`.
    - The backtest reads SIGN from `Master_MAUc1.xlsx` through `final_strategy.mauc1_st()`, the same way it reads the index signals.
    - **Harness proof:** re-running production's Nifty 100, Midcap 100 and Smallcap 100 through the same harness reproduces its 2026-09-25 `W_allRebal.xlsx` cell for cell, with 0 SIGN differences.
  - **Candles (ST.py):**
    - The MAUc1 daily bars are put on the NSE trading calendar and forward-filled, then grouped by ISO week and labelled by the week's last NSE session, which is the review.
    - The 118 MCX sessions on NSE holidays are not in the candles, and the 3 NSE days without an MCX bar repeat the previous bar.
    - The first trend value is on the 6th candle (2015-03-13).
  - **Check against the previous construction** (candles cut at each review; `mauc1_st_compare.py`, `mauc1/st_production/`): the candles differ in 48 of 603 weeks, but the signal is the same in all 603. The previous run's outputs are in `previous_review_cut_signal/`.
    - The backtest's 597 earlier reads all agree except 2015-03-05, a start-up week with no ST.py signal. The books held equity then, so every NAV, stat and trade is unchanged (max difference 4e-16).
  - Output: `gold_supertrend_weekly.csv` (ST.py candles, supertrend and SIGN, indexed by review); the daily bars ST.py used, with their candle, in `gold_signal_daily_mauc1.csv`.
  - **Against the GOLDBEES signal:** MAUc1 and the previous GOLDBEES signal agree on 493 of 598 reviews (`gold_signal_mauc1_vs_goldbees.csv`).
  - Supertrend: multiplier 2; ATR = the linearly weighted mean of the last 5 weekly true ranges (weights 1–5 ÷ 15); band centre = (high + low) ÷ 2; the production ratchet. BUY when the trend line sits on the lower band.
  - Read at each review as the latest bar whose last session is on or before the review.
  - The 50% fallback is used only in the 2014-10 → 2015-02 sleeve spells, before MAUc1's first signal.

## Portfolios and periods

**Portfolios.** The four AA books SCMO_0042 → 0045 hold the parents SCMO_0003 / 0007 / 0010 / 0029.

**Periods.**
- **Live window, 2021-11-03 → 2026-08-21.**
  - Parents' baskets from the frozen rebalance histories, with ISIN-keyed Eikon prices.
  - Sleeve: GOLDBEES from Eikon (close for marking, OHLC4 for fills, as in 2014–21), and the LBES total-return level for cash (`segment_backtest.sleeve_frame`).
- **2014-07-04 → 2021-10-29.**
  - The same parents' real baskets, with Eikon prices and the Eikon GOLDBEES close as gold.
  - Tags for the current-rule comparator come from the 2014–19 rank snapshots.

**Rebasing.** Every series is rebased to 1 on the first date of its period.

## Comparators (same harness, prices, fills and costs)

| Comparator | Description |
|---|---|
| Variant | Split fixed at sleeve entry |
| Triple + fixed 50/50 sleeve | Isolates what the new sleeve changes |
| Triple + fixed "same average gold" sleeve | A constant gold share equal to the FINAL sleeve's average (65% live, 59% in 2014–21). FINAL minus this is the value of timing gold |
| Triple + all-cash sleeve | |
| Current rule | FS ≥ 0.60, 50/50 sleeve |
| Parent | No overlay |
| Published NAVs (live window only) | The published parent NAV (`parentIndices.csv`) and the published AA NAV as traded (`indices.csv`). No published parent series covers the 2014-21 period from its start |

## Statistics (`summary_stats.csv`)

- **CAGR:** (last ÷ first)^(365.25 ÷ days) − 1.
- **Volatility:** std(daily return) × √252.
- **Worst fall:** min(NAV ÷ running max − 1), on daily closes and on Friday closes.
- **Calmar:** CAGR ÷ |daily worst fall|.
- **Sharpe vs cash:** mean(r − r_cash) ÷ std × √252, where r_cash is the LBES level's return.
- **Average equity weight:** from the targets in force.
- **Switches:** trades between equity and sleeve.
- **Re-splits:** trades inside the sleeve when the gold signal flips.
- **Cost paid:** Σ cost ÷ NAV at each trade.

**Yearly returns** (`yearly_returns.csv`): year-end NAV ÷ previous year-end NAV − 1. The first and last years are partial.

## Workbook (`final_strategy_workbook_mauc1.xlsx`)

The workbook was saved under this name because `final_strategy_workbook.xlsx` (the GOLDBEES-signal version) was open in Excel.

- **Gold_daily / Gold_ST:** MAUc1 daily bars as ST.py saw them (NSE days, forward-filled), with the week each belongs to, and MAUc1's supertrend on ST.py's candles, with every step a formula. The first trend value is on the 6th candle, as in ST.py.
  - Checked against ST.py's SIGN (`Master_MAUc1.xlsx`) on every candle. Candle high and low are checked with MAXIFS / MINIFS over the daily sheet.
- **GOLDBEES_fill:** the de-spiked GOLDBEES fill with formulas: band, limits, clean open/high/low, OHLC4. Checked against the engine on every day. The tolerance sits on Params (B9).
- **Signals_live / Signals_1421:** the decision, the gold lookup (INDEX/MATCH, match type 1), the weights and the variant.
  - Checked against the engine in every review.
- **D_<book>_<period>:** the daily check model. Each session:
  1. Carry every holding from the previous close to today's fill price: the parent at its value at OHLC4 prices (column F, from the parent's units × fill prices), gold at OHLC4, cash at its level.
  2. If a review executes today and the target changes, rebalance to target at those fill values and pay 10.4 bps × Σ|target value − value at fill|.
  3. Carry every holding from the fill to today's close (the parent × close value ÷ fill value; gold × close ÷ OHLC4).
  - On other days, steps 1 and 3 reduce to close-to-close.
  - NAV = equity + gold + cash. The drawdown uses a running max.
- **Check model against the harness** (`check_model_gap_attribution.csv`, by kind of day):
  - inside sleeve spells: 0.000;
  - days moving into the sleeve: at most 0.013 pp/yr;
  - days moving back to equity: at most 0.034 pp/yr;
  - inside equity spells: −0.39 to +0.49 pp/yr. Here the check model follows the parent's drifted NAV, while the harness re-buys the parent's current published weights at each re-entry.
  - The Python replica of the model is `final_strategy_check.py`.
- **Trades_final / Positions_final:** every harness trade of the FINAL rule, with each holding's weight before and after, and its fill price.
- **Sleeve_spells:** every sleeve stretch, with gold, cash and parent returns, and the sleeve return under 80/20, 20/80, 50/50 and the FINAL rule.
- **Params:** the editable inputs (yellow cells).

## Caveats

- **Chosen after seeing the data.** The three-index rule and the gold-timed split were chosen after the 2014–2026 analyses, so neither period is a clean out-of-sample test of this combination.
- **Short gold history.** Gold history starts in 2014-07.
- **Price return against total return.** Indices and parents are price return; cash is total return.
- **The 2026 gold spike.** The live-window daily worst fall of the FINAL rule (−21.4% on every book) is the 2026-01-29 → 2026-03-23 gold move with 80% of the book in gold. It is about −12% on Friday closes.

## Report page (`report.html`, built by `final_book_report.py`)

One page with two selectors: book (0042 → 0045) and period (live window, or 2014–21).

| Element | Formula | Source |
|---|---|---|
| **Where the rule stands now** (the same for every book) | The last 8 weekly reviews. Each signal cell is that week's ST.py SIGN. "To flip" = supertrend line ÷ the week's close − 1: the move a close would need to cross that week's line (the line moves each week, so it is a distance, not a forecast). "Final rule holds" = 100% parent basket if all three indices are BUY, else 80% GOLDBEES / 20% cash if MAUc1 is BUY, 20% / 80% if SELL. The trade session is ST.py's WGH_SRT (the next NSE session). "Since" = the earliest review of the current unbroken run of the same holding. Rows after 2026-08-21 are signals only: the backtest's stock and cash prices end there. | Index SIGN, ST and close: the Friday job's live `RSI/Final/Analysis/Master_{Nifty100,MC100,SC100}.xlsx`, read-only, when the page was built. MAUc1: `AA/Historical Data/FRA_MAUc1/RSI/Final/Analysis/Master_MAUc1.xlsx`. Built by `final_book_report.latest_signals` |
| **Summary tiles and stats table** | CAGR, volatility, worst fall (daily and Friday closes), Calmar, Sharpe vs cash, total return, time in equity, switches. "Final − this" = CAGR(final) − CAGR(series) | `summary_stats.csv` |
| **Equity curve** | Daily NAV on a log scale. Every series is rebased to 1 on the period's first date (live 2021-11-03; 2014-21 2014-07-04). Toggles add the comparators | `nav_curves_daily.csv` |
| **Drawdown** | NAV ÷ running peak − 1, for the series shown | `nav_curves_daily.csv` |
| **Final rule: allocation** | Equity, gold and cash value ÷ NAV at each close. Gold and cash are units × price; equity is the rest. Weights drift between trades | `daily_<book>_<period>.csv` |
| **Live AA: allocation** | The live book's weights from its weekly weight file, as steps from each effective date (`common.load_state`). Only for the live window; SCMO_0042's file ends 2026-06-15 | the AA weight file |
| **Year by year** | Year-end NAV ÷ previous year-end NAV − 1. The first and last years are partial | `yearly_returns.csv` |
| **Constituents over time** | Each cell is a holding's weight straight after that rebalance (`w_after`) | `position_log.csv` (FINAL rule) |
| **Every rebalance** | Per trade: kind, the equity / gold / cash weights after it, the number of holdings, value traded ÷ book, cost ÷ book before trade, NAV at close. "Show" lists each holding's weight before and after, with its fill price (Monday OHLC4 for stocks and GOLDBEES; the level for cash) | `trade_log.csv`, `position_log.csv` |

**Published series.** "Parent, published NAV" and "Live AA, published NAV" come from `parentIndices.csv` and `indices.csv`. The published NAVs' conventions for fills and dividends may differ from the backtest's, so the like-for-like parent comparison is "Parent (same engine)".
