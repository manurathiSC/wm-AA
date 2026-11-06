# Methods appendix: "Why Both Must Agree"

Companion to `report.html` in this folder. It lists, for every table and
chart, the formula, the denominator, any null test, and the source files.

**Code**
- `AA/analysis/why_n100sc100.py`: parts A–D and F.
- `AA/analysis/why_parents_oos.py`: part E.
- `AA/analysis/why_report.py` and `why_report_template.html`: the page.

## Inputs

| Input | Source | Coverage |
|---|---|---|
| Weekly supertrend `SIGN` (BUY/SELL) | frozen production `Master_{Nifty100,SC100,NSEI,MC100,NiftySmallcap250,NiftyMidcap150,NiftyMicrocap250}.xlsx` | Nifty 100 from 2006-01, SC100 from 2004-02, NSEI from 2000-02, MC100 from 2005-08; the 150/250 indices from 2019-02 |
| Index levels | `frozen_2026-09-25/Data/indices_ohlcv.xlsx` (price return) | from 2004–05 |
| Stock prices (part E) | `ohlcv_eikon`, joined on `quote_id` via `symbology_changes` (`cache/eikon_ohlcv_2014_2021.parquet`) | 97–99.5% of holding-entries fillable (`parents_oos_coverage.csv`) |
| Gold | GOLDBEES, Eikon `GBES.NS` (quote_id 55837402194) | from 2014-07-01 |
| Cash | `LBES_Adjusted_Price_data_2026_08_10.csv` (dividend-reinvested LIQUIDBEES) | from 2007-06-29 |
| Market-cap ranks (part E tags) | `mcap_based_universe`, ordinary shares, month-end, ranked on `mcap` (`cache/mcap_ranks_monthly_2014_2019.csv`) | 2013-12 → 2019-07 |
| In-sample books | `evidence/segment_v2/` (`nav_curves.csv`, `exposure_daily.csv`, `scorecard.csv`) | 2021-11-03 → 2026-08-21 |

## A. In-sample attribution (`attribution_in_sample.csv`, `disagreement_stretches.csv`)

Inputs per book:
- `e_X,t` is rule X's target equity weight, lagged one session so that it is the weight held going into day t (`exposure_daily.csv`).
- `r_p` is the harness parent's gross daily return.
- `r_s` is the 50/50 gold/cash sleeve return.

Formulas:
- **Gap between rules A and B:** `Σ_t [log(1 + e_A r_p + (1−e_A) r_s) − log(1 + e_B r_p + (1−e_B) r_s)]`.
- **Annualised gap:** `expm1(gap / years)`.
- **Disagreement sessions:** days where `e_A ≠ e_B`.
- **A stretch:** a run of consecutive disagreement sessions. Its "effect" is `expm1` of the summed log contribution over the run.

This is in return space (daily rebalancing, no fill-timing effect). It reproduces the simulated CAGR gaps to within about 1 pp/yr.

## B. Switch anatomy (`switch_anatomy.csv`)

- **Scope:** every change in `N100 × SC100` from 2006 on the review grid.
- **Exits:** "triggered by" means the index or indices that were SELL at the exit.
- **Entries:** "triggered by" means the index that turned BUY last.
- **Forward returns:** from the first session after the review, over 21 and 63 sessions.

## C. Signal states (`states_*.csv`, `states_*_summary.csv`)

- **States.** Each review is one of four: both BUY, only N100 BUY, only SC100 BUY, both SELL.
- **Forward windows.** The 1-week return is from the close of the first session after the review to 5 sessions later; the 4-week return is to 21 sessions later.
- **Assets:**
  - SC100, N100 and MC100 index levels;
  - gold;
  - in-sample only, the average of the four harness parents.
- **Hit rate.** The share of observations above zero. Weeks without a value (for example gold before 2014-07) are excluded; `gold_4w_n` gives the count.
- **Periods.** Out of sample is 2007-07-02 → 2021-10-29; in-sample is 2021-11-03 → 2026-08-21.

## D. Index backtests (`index_backtests.csv`, `index_curves_*.csv`)

- **Weight.** A Friday decision is traded at the close of the next session and first earns the session after that (`daily_weight`).
- **Daily return:**
  - `r = w·r_equity + (1−w)·r_sleeve`;
  - 20.8 bps is charged per full switch (`|Δw| × 20.8 bps`).
- **Equity legs:**
  - the SC100 index;
  - the N100 index;
  - the MC100 index;
  - an equal-weight daily blend of the three.
- **Sleeves:**
  - all cash, 2007-07 → 2021-10 (no gold history before 2014-07);
  - 50/50 gold/cash, 2014-07 → 2021-10;
  - both sleeves, in-sample.
- **Rules:**
  - buy-and-hold;
  - single indices;
  - AND pairs and the triple AND;
  - `N100 OR SC100`, equity if either index is BUY.
- **Statistics.** CAGR on calendar time. Max DD is from daily levels. Vol is daily std × √252. "In equity" is the mean daily weight.

**Year-by-year** (`oos_yearly_blend_cash.csv`): year-end level ÷ previous year-end − 1. The first year (2007) is partial.

## E. Actual parents, out of sample (`parents_oos_results.csv`, `parents_oos_curves.csv`)

**Setup**
- **Engine:** the v2 harness (`segment_v2.Simulator`, with the close fallback). Positions are held in units, fills are at next-session OHLC4, and costs are 20.8 bps round trip.
- **Reviews:** the SC100 Master's Friday dates, 2014-07-11 → 2021-10-29.
- **Baskets:** each parent's latest `availableDate` on or before the review.

**Rules**
- **`current rule*`.** `segment_v2.build_production` (count-weighted FS ≥ 0.60) on rank-band tags. Tags come from `HybridTagger` with 2014–2019 month-end ranks and no membership. The stand-ins are MC100 for MC150 and SC100 for SC250 and Micro250. These are the FS inputs the production engine used before 2026-04 (`segment_v1/gate_v2_summary.json`).
- **`segment rule*`.** `segment_v2.build_sleeve`, with the same tags and stand-ins.

**Sleeves.** The 50/50 gold/cash sleeve (GOLDBEES and LBES), and an all-cash sleeve.

**Caveat.** The parents' pre-2021 rebalance rows may include pre-launch backtest history. That would flatter the "parent" line but not the comparison between the timing rules, which all hold the same baskets.

## F. Robustness (`robustness_in_sample.csv`)

- **Scope.** Return-space runs per book on the harness parent and the 50/50 sleeve.
- **Delay tests.** Every decision acts 1 or 2 reviews late.
- **Shift null.** The joint (N100, SC100) in-window signal matrix is rolled circularly by every k with 8 ≤ k ≤ N−8 (236 runs), keeping the two signals' co-movement. Reported:
  - the AND rule's percentile among the shifts;
  - the share of shifts where AND beats SC100-only.
- **Best stretch.** The largest single contribution to AND − SC100-only, and its share of the total.

## Findings the page states, with their evidence

| Claim | Evidence |
|---|---|
| "Only SC100 BUY" weeks lose money over the next four weeks | `states_oos_summary.csv`: 63 weeks, SC100 −3.14%, hit rate 44%. `states_in_sample_summary.csv`: 15 weeks, parents −3.84% |
| The AND rule beats SC100-only out of sample on the indices | `index_backtests.csv`, SC100 with cash sleeve: 14.41% against 8.60% CAGR, −28.6% against −50.1% max DD |
| It does not beat SC100-only on return on the parents, 2014–21 | `parents_oos_results.csv`, gold+cash: 16.75% against 18.26% average. Max DD −23.2% against −26.4% |
| The 2014–21 parent gap nets 2016 (+27 pp) and 2021 (−37 pp) | `yr_par` in the page payload (from `parents_oos_curves.csv`) |
| The in-sample edge over SC100-only came from 4 stretches | `disagreement_stretches.csv`; the best is 53–77% of the gap per book (`robustness_in_sample.csv`) |
| Gold's contribution in-sample | segment_v2 runs with gold share 0: 25.7% falls to 16.7% average CAGR. In the 2025-08 → 2026-04 spell gold rose 50%, against +1.1% for the parents |

## Limitations

- **Index-level tests.** They use return space and price-return indices (no dividends). Parent tests use the full harness.
- **Selection.** Study 1 chose the rule on 2021–26, so the in-sample numbers are selected. Only parts D and E are out of sample.
- **Before 2014.** There is no gold price, so the 2007–2021 test can only be run with cash. That understates what a gold sleeve would have added in 2008–2012.
- **The current-rule proxy.** Before 2019 it uses MC100 and SC100, not MC150 and SC250.

## G. Timing the gold inside the sleeve (`gold_sleeve_results.csv`, `gold_sleeve_gold_itself.csv`, `gold_signal_weekly.csv`)

Code: `AA/analysis/gold_sleeve_test.py`.

**The gold signal**
- **Construction:** `supertrend.supertrend(to_weekly(...))` (5-bar linearly weighted ATR, multiplier 2), run on Eikon GOLDBEES (GBES.NS) daily OHLC. Weekly bars are labelled by their last session.
- **Timing:** read as of each Friday review, the same point in time as the index signals.
- **Warm-up:** until the first valid value (mid-2014-08) the sleeve holds 50/50.

**Sleeve variants.** Each is the gold share of the defensive sleeve, set at every review.

| Variant | Gold share |
|---|---|
| Fixed 50/50 | 0.5 |
| Gold trend 100% (Study 1's version) | 1.0 if the gold signal is BUY, else 0.0 |
| Gold trend 50/50 | 0.5 if BUY, else 0.0 |
| All cash | 0.0 |
| All gold | 1.0 |
| **Fixed, same gold share** (the control) | a constant equal to the gold-trend-100% sleeve's average gold share over the weeks that rule is defensive (0.74–0.86 in-sample, 0.66–0.76 out of sample) |

A change of gold share between reviews trades gold against cash at the next fill, and pays 20.8 bps.

**Timing value** = CAGR(gold trend 100%) − CAGR(fixed, same gold share). This is the same logic as gate G2's static-mix control.

**Runs**
- **In-sample** (2021-11 → 2026-08): the v2 inputs on the four AA books.
- **Out of sample** (2014-07 → 2021-10): the part-E setup, with the sub-periods 2014-07 → 2018-12 (gold +2.0% a year) and 2019-01 → 2021-10 (gold +14.7% a year), each measured from the same NAV path.

**Results** (averages of the four books)

| Period | Timing value | Trend 100% vs fixed 50/50 |
|---|---|---|
| In-sample | −2.1 to −3.2 pp/yr | CAGR +1.5 to +2.5 pp/yr; max DD 3.9–8.3 pp deeper |
| Out of sample, whole period | +0.4 to +0.6 pp/yr | |
| 2014–18 | −0.1 to −1.0 pp/yr | |
| 2019–21 | +1.9 to +3.5 pp/yr | |

The gold-trend 50/50 variant is within ±0.1 pp of fixed 50/50 out of sample, and 2.2–3.4 pp/yr lower in-sample.

**Daily and Friday-close drawdowns.**
- **What the table shows.** Max DD here is measured on daily NAV. The report also shows it on Friday closes (`max_dd_friday` in the payload), the marks the weekly signals see.
- **The Jan–Mar 2026 spike.**
  - GOLDBEES closed at a one-day high on 2026-01-29 (146.53, +7.9% that day, −10.5% the next).
  - It closed at a one-day low on 2026-03-23 (110.72, −8.5%, then +4.3%).
  - Kite shows the same moves (147.15 and 110.99).
- **Size of the fall.** On daily closes it is −24.4%. On Friday closes the 2021–26 worst fall is −12.6%, from 2026-02-27 to 2026-06-26.
- **Where it shows up.**
  - Under N100 AND SC100 the books were defensive through it. It sets the daily max DD of the 50/50 sleeve on 0043/0044/0045 (−15.3%), and of the gold-trend and all-gold sleeves on all four books (−24.6%).
  - The in-sample "max DD 3.9–8.3 pp deeper" is therefore mostly this event under N100 AND SC100. On Friday closes the gap is 1.2 pp there, and 4.2–4.6 pp under the other three rules.
- **The chart.** The gold chart plots daily closes, with the weekly signal carried forward from its week-end session.

**Limitations**
- There is no gold data before 2014-07, so gold timing cannot be tested through 2008–2013.
- The gold signal is this study's own port applied to GOLDBEES, not a production signal.

## H. Three must agree: N100 AND MC100 AND SC100 (`triple_*.csv`)

Code: `AA/analysis/triple_and_test.py`.

**Rule.** The whole book (or the whole index) is in equity only when the weekly production `SIGN` of Nifty 100, Nifty Midcap 100 and Nifty Smallcap 100 are all BUY. Otherwise it holds the defensive sleeve. The MC100 signal is `Master_MC100.xlsx`, aligned to the review grid with a carry of at most one week.

**Portfolios** (`triple_portfolio_results.csv`)
- **Books 2021–26:** the v2 inputs on the four AA books.
- **Parents 2014–21:** the part-E setup.
- **Engine:** the v2 harness in both. Each rule is run with three sleeves: 50/50, all cash and all gold (`gold_share` 0.5 / 0 / 1).

**Indices** (`triple_index_results.csv`, `triple_index_curves.csv`)
- **Engine:** part D's return-space engine, with each index as the equity leg: N50, N100, MC100, SC100, MC150, SC250, Micro250, an equal-weight N100/MC100/SC100 blend, and gold itself.
- **Gold as the held asset:**
  - The asset is GOLDBEES (Eikon GBES.NS, from 2014-07). Its "own signal" is gold's weekly supertrend, read at each Friday review as the latest bar whose last session is on or before the review.
  - The equity rules (triple, pair, SC100 only) hold gold whenever they would hold equity.
  - A switch trades only the part of the book that changes asset, so the cost is 20.8 bps × (1 − the sleeve's gold share).
  - With the all-gold sleeve it never trades, and every rule equals buy-and-hold.
- **Rules:**
  - buy-and-hold;
  - the index's own signal;
  - SC100 only;
  - the pair;
  - the triple.
- **Periods and sleeves:**
  - 2007–21 and 2007–26: cash only, since there are no gold prices before 2014-07.
  - 2014–21, 2021–26 and 2014–26: cash, 50/50 and all gold.
  - Sleeve returns pick their legs explicitly (cash, gold, or 0.5 × each), so gold's missing pre-2014 prices never touch the cash sleeve.
- **Start dates.** Each index starts at its first price and signal. MC150 and SC250 start in 2019-02, Micro250 in 2022-02.

**Marginal weeks** (`triple_marginal_summary.csv`, `triple_marginal_stretches.csv`). These are the weeks with N100 and SC100 both BUY and MC100 SELL, the only state in which the triple and the pair differ. There were 5 such weeks since 2006, out of 502 with both BUY, and none in 2021–26. In 2014–21 the only one is 2020-06-05, and the triple's entire lead over the pair on the parents (1.6–4.6% cumulative) appears in that month.

**Results** (averages of four; CAGR and max DD)

| Test | Triple | Pair | SC100 only | Current rule | Parent |
|---|---|---|---|---|---|
| Books 2021–26, 50/50 | 25.67%, −16.3% | identical | 19.08%, −21.8% | 16.62%, −24.6% | 13.65%, −30.1% |
| Parents 2014–21, 50/50 | 17.21%, −23.2% | 16.75%, −23.2% | 18.26%, −26.4% | 17.92%* | 25.36%, −58.3% |

- **On the indices:** the triple is never behind the pair, and 0–1.0 pp/yr ahead.
- **Full-history 2007–26, cash, on SC100:** the triple made 15.5% with a −28% worst fall, against 9.1% and −77% for buy-and-hold.
- **All-gold sleeve, pair rule** (CAGR, worst fall):

  | Test | Cash | 50/50 | All gold |
  |---|---|---|---|
  | Books 2021–26 | 16.7%, −13.6% | 25.7%, −16.3% | 34.2%, −24.6% |
  | Parents 2014–21 | 15.8%, −23.7% | 16.7%, −23.2% | 17.5%, −25.8% |

  - On the SC100 index, all gold beat 50/50 by 0.6 pp/yr in 2014–21 (gold +6.7%/yr) and by 8.8 pp/yr in 2021–26 (gold +27.4%/yr).
  - Every rule's −24% worst fall with the all-gold sleeve in 2021–26 is gold's 2026-01-29 → 2026-03-23 move on daily closes (see G).
- **Gold held under the equity rules, 2014–26, cash sleeve:** the triple made 6.5%, the pair 6.7% and gold's own signal 9.7%, against 14.4% for buy-and-hold.

## I. Why timing gold does not pay (`gold_why_*.csv`)

Code: `AA/analysis/gold_why.py`. Every signal is read on the Friday review grid, the production Master dates: the latest weekly bar whose last session is on or before the review. A week that ends in a Saturday or Sunday special session (e.g. Budget day 2025-02-01) is acted on at the next review, as in the harness. Window 2014-08 → 2026-08 (Eikon GOLDBEES, GBES.NS, starts 2014-07-01). Gold is price return, cash is LBES total return, costs 20.8 bps per full switch. Smallcap 100 is run alongside as the contrast case.

- **Timing value, asset alone** (`gold_why_timing.csv`).
  - The asset switches to cash on SELL and is compared with an exposure-matched static mix: a constant weight equal to the signal's own average weight over the period, rebalanced daily at no cost.
  - Timing value = timed CAGR − static CAGR.
  - The grid covers supertrend multipliers 1.5/2/3/4 × ATR windows of 5/10/20 bars, close above its 20- or 40-week average, and 13-, 26- and 52-week return above zero.
- **State returns** (`gold_why_states.csv`).
  - The annualised return over the sessions the signal held the asset (BUY) and the sessions it did not (SELL). A decision on Friday R earns from the second session after R.
  - Forward 4w and 13w returns run from each weekly decision's entry-session close, with the share of cases that rose.
- **Episodes** (`gold_why_episodes.csv`, `gold_why_episode_summary.csv`).
  - An episode runs from one switch's entry session to the next.
  - *Entry lag* = the entry price ÷ the lowest close of the preceding SELL episode − 1.
  - *Exit give-back* = the exit price ÷ the highest close in the BUY episode − 1.
  - *Worst fall avoided* = the lowest close in a SELL episode ÷ its start price − 1.
- **Structure** (`gold_why_structure.csv`). These use weekly Friday closes, 2014-08 → 2026-08.
  - Autocorrelation of weekly log returns, lags 1–4.
  - Variance ratio VR(q) = var(q-week log return) ÷ (q × var(1-week)), overlapping. VR > 1 means moves persist; VR < 1 means they reverse.
  - The number of separate drawdowns deeper than 10%.
- **Inside the sleeve** (`gold_why_inside_sleeve.csv`). The sessions in which N100 AND SC100 had the book defensive, split by the gold signal's state. For each, gold's and cash's annualised return.
- **Results:**
  - **The signal carries no information on gold.** Gold spent 38% of sessions in SELL and made 39% of its log gain there. Over 2014–26 it returned 14.8%/yr while SELL and 14.6% while BUY. In 2021–26 the gap was 50.8% (SELL) against 20.2% (BUY).
  - **Most SELL spells were false alarms.** Gold rose in 11 of 13 completed SELL episodes. The median worst fall avoided was −2.5%, against a median entry lag of +7.0% and an exit give-back of −6.1%.
  - **Structure.** For gold, VR(4w) is 1.09 and VR(13w) 1.07, against 1.27 and 1.32 for SC100. Gold's max DD was −21% on weekly closes, against −64% for SC100.
  - **Drawdowns.**
    - On daily NAV, every rule in the grid kept buy-and-hold's −24.4% max DD. That is the 2026-01-29 one-day high to the 2026-03-23 one-day low, which no weekly rule can react to. On Friday closes it is −12.6%.
    - Gold's deepest Friday-close fall is 2020-08-07 → 2021-03-12 (−21.4%). The production signal sold in the week of 2020-09-25, after an 11.9% give-back, and sat out the rest. Its 2019–21 timed max DD was −12.1%, against −22.4% for buy-and-hold.
  - **The production setting was one of the worst.** Supertrend ×2, 5 bars, gave −0.9 pp/yr. The ×3 and ×4 settings gave +1.5 to +3.6 pp/yr from 5–9 switches in 12 years, a result chosen after seeing the data that rests on two or three calls.
  - **Inside the sleeve.** While the book was defensive, gold returned 17.1%/yr on the days the gold signal held cash, which earned 4.3%. In 2021–26 that figure was 52.6%.

## J. Where the pre-2021 signals come from (`master_sign_check.csv`, `master_sign_mismatches.csv`)

Code: `AA/analysis/verify_master_signs.py`.

- **Source.** Every index signal is the `SIGN` column of the production `Master_*.xlsx` files. These are the output tables of the desk's supertrend script (`wm-AA-smallcase-rebalance-automation/Python_Scripts/ST.py`), taken from the Friday Rebalance Automation folder.
  - Frozen on 2026-09-25 in `AA/Historical Data/frozen_2026-09-25/Master/`, with sha256 values in `SHA256SUMS.txt`.
  - Each file carries the whole weekly calculation (weekly close, weighted ATR `EMA_TR`, bands `BUB/BLB/FUB/FLB`, `ST`, `SIGN`) back to the index's first data: Nifty 50 2000-02, SC100 2004-02, MC100 2005-08, Nifty 100 2006-01, MC150/SC250 2019-02, Micro250 2022-02.
- **What the pre-2021 values are.**
  - They are the production formula run over historical index prices (a backfill), not signals anyone traded at the time. The AA books first acted on them in 2021-11.
  - The supertrend uses only past weekly bars, so the backfill equals what the formula would have said live, as long as the index history was not revised and the formula did not change.
- **Check.** The weekly supertrend is recomputed from the frozen `indices_ohlcv.xlsx` with `supertrend.py` (the port of ST.py) and compared week by week with `SIGN`.
  - It matches 100% of weeks for Nifty 50, MC100, SC100, MC150, SC250 and Micro250, both before and after 2021-11.
  - Nifty 100 matches 821 of 826 weeks before 2021-11. The 5 misses are the warm-up weeks 2006-01-27 → 2006-02-24, before any test period.
  - Each Master file's weekly `Index` close equals the weekly close built from the index file in 100% of weeks.
- **Limits.** The supertrend settings (5-bar ATR, ×2) were set by the desk. If they were ever tuned on history that includes 2007–21, the "out of sample" periods are out of sample for the choice of *rule*, not for the choice of *settings*. The gold signal is not a production signal; this study computes it with the same port on Eikon GOLDBEES OHLC.
