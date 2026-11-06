# Methods: the pair rule in every year and regime (`deep/report.html`)

**Rule under study.** "Pair" means N100 AND SC100: the book holds equity only when both weekly production supertrend signals are BUY, and holds the sleeve otherwise.

**Comparators.**
- Triple (N100 AND MC100 AND SC100).
- SC100 only.
- The held index's own signal.
- Buy-and-hold.
- Components (N100 only, MC100 only) and family variants (N50 AND SC100, MC100 AND SC100, N100 AND MC100, N100 OR SC100, N100 AND SC250).

## Shared engine and data (`deep_core_common.py`)

**Signals.**
- Source: the production `Master_*.xlsx` SIGN via `why_n100sc100.weekly_signs()`.
- Weekly only. They reproduce exactly from index prices (`verify_master_signs.py`).
- A decision dated Friday R trades at the close of the next session and first earns the session after (`daily_weight`).

**Engine.** `why_n100sc100.run_rs`. The daily return is w·r_equity + (1−w)·r_sleeve − |Δw|·20.8 bps.

**Held assets.**
- Index closes from the frozen `indices_ohlcv.xlsx`. These are price return.
- "Blend" is the equal-weight daily mix of N100, MC100 and SC100 returns.

**Sleeves.** Each leg is picked explicitly:
- cash: the LBES total-return level, from 2007-06-29;
- gold: GOLDBEES (Eikon), from 2014-07-01;
- 50/50: 0.5 × gold + 0.5 × cash, re-mixed daily.

**Continuous NAVs.** One run per leg × rule × sleeve:
- cash sleeve from 2007-07-02;
- gold sleeves from 2014-07-07;
- all runs to 2026-08-21;
- cached in `core_navs.parquet` and `core_weights.parquet`.

**Samples.**
- OOS: 2007-07-02 → 2021-10-29.
- In-sample: 2021-11-03 → 2026-08-21. The rule was chosen on this window, so it is reported separately and never used as evidence.

**Tie-out.** The pair on SC100, cash sleeve, OOS gives 14.41% CAGR and a −28.6% worst fall, matching `triple_index_results.csv`.

**Period stats** (`core_period_stats.csv`).
- CAGR uses calendar days.
- Max DD on daily closes, and on Friday closes (W-FRI last).
- Volatility = std(daily return) × √252.
- Calmar = CAGR ÷ |daily max DD|.

## Years (`deep_years_episodes.py` → `years_*.csv`)

**Yearly return.** Each continuous NAV is sliced by calendar year, as NAV at year end ÷ NAV at the previous year end − 1. 2007 starts on 07-02 and 2026 ends on 08-21.

**Worst fall inside the year.** Taken on the year's path, prefixed by the prior year-end value, on daily and on Friday closes.

**Year labels** (hindsight), from SC100 buy-and-hold with the cash sleeve:
- bull: > +15%;
- bear: < −10%;
- flat: otherwise;
- V: a Friday-close fall inside the year deeper than 20%, in a year that ended positive.

**Summaries.** Years 2007–2020 are OOS. 2021 is mixed; its Jan–Oct figure is computed separately.

## Swings (`swings_*.csv`)

**Pivots.** A 10% zig-zag on each leg's Friday closes from 2006:
- a high is confirmed once price falls 10% below it;
- a low is confirmed once price rises 10% above it;
- the last pivot is provisional.

**Rule return over a swing.** NAV at the end pivot ÷ NAV at the start pivot − 1, using asof Friday.

**Swings counted.** Only swings the rules traded: the NAV exists and the swing starts after 2007-07-09.

**Share of the move.**
- The share taken is the mean rule return ÷ the mean buy-and-hold return, over completed OOS swings (`swings_capture_oos.csv`).
- Classes: falls of 10–20% or 20%+; rallies that are fast (≤ 13 weeks) or slow.

**Exit and entry timing.**
- Exit fall: the index level at the first out-of-market session inside a fall ÷ the swing's start level − 1. It is 0 if the rule was already out.
- Entry rise: the same, for the first in-market session inside a rally.

**Exit quality** (`swings_exit_quality.csv`). An exit is "real" if the index fell a further 10% below the exit level within 130 sessions.

## Regimes (`deep_regimes_mech.py` → `regime_*.csv`)

**Label alignment.** Labels are computed on Friday reviews and assigned to the sessions each review governs, from the second session after R. The ex-ante labels therefore use only data up to R.

| Label | Definition |
|---|---|
| R1 phase (hindsight) | From SC100's 10% zig-zag. Bear: inside a fall of 20%+. Correction: inside a 10–20% fall. Recovery: inside a rally, below the prior swing high. Bull: inside a rally, above it. |
| R2 | SC100 close above or below its 40-week SMA |
| R3 | SC100 13-week realised volatility, tercile of all past values (expanding window, at least 52 weeks) |
| R4 | SC100 minus N100 26-week return: > +5 pp small-led, < −5 pp large-led, neutral otherwise |
| R5 | Signal state |
| R6 | Number of N50, N100, MC100 and SC100 in BUY |
| R7 | Trailing 52-week correlation of weekly N100 and SC100 log returns, expanding tercile |

**Bucket measures.**
- Annualised return = exp(Σ log(1+r) × 252 ÷ n) − 1 over the bucket's sessions.
- Contribution = [Σ log(1+r_pair) − Σ log(1+r_other)] over the bucket × 252 ÷ the sessions in the whole sample. Contributions add up to the total log gap.

**Forward returns by state.** From each review's entry session: 20 and 65 sessions ahead (`regime_state_cross.csv`).

## Mechanism (`mech_*.csv`)

**Decomposition** (`mech_decomposition.csv`).
- Identity: r_A − r_B = (w_B − w_A)(r_sleeve − r_equity) − cost difference.
- Losses avoided and gains missed are split by the sign of r_equity on the days A is out and B is in.
- All figures are arithmetic pp a year; the residual is 0.

**Signal diagnostics** (`mech_signal_diagnostics.csv`).
- Spells are runs of constant daily weight.
- False entry: the index is lower 65 sessions after the entry level (the close before the first in-market session).
- False exit: the index is higher 65 sessions after the exit level.
- Entry lag: the entry level ÷ the lowest close since the previous exit − 1.
- Exit give-back: the exit level ÷ the highest close since the previous entry − 1.
- An independent recount from the weekly signals gives the same false-entry shares (22% and 39%).

**States** (`mech_states_summary.csv`).
- For each review 2006–2026: the state, and forward 20, 65 and 130-session returns of SC100, N100 and the blend.
- The worst point over the next 26 weeks = the minimum close over the next 130 sessions ÷ the entry close − 1.
- Plus the share of weeks inside an R1 bear phase.
- Run lengths are in `mech_state_run_lengths_oos.csv`.

**Lead-lag** (`mech_lead_lag_sc100_20pct_falls.csv`).
- For each SC100 zig-zag fall of 20%+: the first SELL review on or after the peak for each signal, or "already SELL".
- The first BUY review on or after the trough for each signal, and the first review where both are BUY.
- Weeks are calendar days ÷ 7. Index moves are measured on Friday closes.

## Robustness (`deep_robust.py` → `robust_*.csv`)

**Rolling windows.** From every 5th session, windows of 252, 756 and 1,260 sessions, sliced from the continuous NAVs. "OOS" windows end on or before 2021-10-29. Shares compare CAGR, daily max DD and Calmar.

**Bootstrap.**
- Stationary bootstrap of paired OOS daily returns (pair, bh, sc100): restart probability 1/130, 2,000 draws, seed 20260925.
- Each draw compares the CAGR of each resampled series.

**Shift null.**
- The joint weekly (N100, SC100) SIGN matrix, 2006-01 → 2021-10, is rolled by k reviews, for 26 ≤ k ≤ n − 26: 775 shifts.
- Each shift is re-run on SC100 and the blend over the OOS period.
- The percentile is the share of shifts with a lower CAGR, or a deeper worst fall.

**Delay.** Decisions shifted by k reviews. **Costs.** 0, 20.8, 50 and 100 bps per full switch.

**Settings.**
- `supertrend(to_weekly(ohlc), mul, days)` on the Nifty100 and SC100 sheets.
- Read on the Friday review grid as the latest bar whose last session is on or before the review.
- × 2 with 5 bars matches Master in 100% of weeks from 2007 to 2021.

**Family.** Run on SC100, the blend and N100. N100 AND SC250 starts 2019-03.

## Sleeve and gold (`deep_sleeve_*.py` → `sleeve_*.csv`)

**Scope.** Written by the workflow's sleeve analyst: per-year sleeve lift, every defensive spell, gold across SC100 falls of 10%+, the gold-timing placebo, drift against daily re-mix, and gold counterfactuals.

**Audit.** Its audit did not run because of a usage limit. The key figures were spot-checked against `triple_index_results.csv`:
- pair 50/50 on SC100, 2014–21: 8.93%;
- in-sample: 26.77%;
- blend: 9.41% and 22.2%;
- 4-book: 16.75%.

## Charts

| Chart | Content |
|---|---|
| Year bars | Pair − buy-and-hold and pair − SC100 only, SC100 held, cash, per calendar year; the in-sample years are shaded. Source: `years_wide.csv` |
| Swing shares | Pair's and SC100 only's share of each swing class, OOS. Source: `swings_capture_oos.csv` |
| Phase contributions | R1 contribution vs buy-and-hold and vs SC100 only, SC100 held, OOS. Source: `regime_table.csv` |

## Caveats

- **Price return against total return.** Buy-and-hold is on price-return indices while cash is total return. This flatters timing by about half the dividend yield.
- **Hindsight labels.** R1 and the year labels use hindsight.
- **Small counts.** For example, 12 falls of 20%+.
- **Settings provenance unknown.**
- **Short gold history.** Gold starts 2014-07.
