# The pair rule (N100 AND SC100) in every year and every regime

The rule holds the whole equity book only when the weekly supertrend of **Nifty 100 and Nifty Smallcap 100 are both BUY**. Otherwise it holds the defensive sleeve.

This note covers every calendar year from 2007 to 2026, every 10% swing, seven regime labellings, robustness tests, the mechanism, and the sleeve. Every number cites the file it comes from, in `evidence/why_n100sc100/deep/`.

"OOS" means out of sample: 2007-07-02 → 2021-10-29, before the rule was chosen. "IS" means in-sample: 2021-11-03 → 2026-08-21, the window the rule was chosen on. IS results are shown for completeness and **never used as evidence**.

## 1. Conclusion

1. **Out of sample, the pair is two things:**
   - a robust drawdown filter;
   - a clearly better small-cap timer than Smallcap 100's own signal.

   It is **not** a proven way to beat buy-and-hold on return. On the Smallcap 100 index it made 14.4% a year, with a −28.6% worst fall. That compares with 7.6% and −77.5% for buy-and-hold, and 8.6% and −50.1% for Smallcap 100's own signal (`core_period_stats.csv`).
2. **The edge is earned in bear markets and partly paid back in recoveries and bull runs.**
   - In hindsight-labelled Smallcap 100 bear phases, the pair lost 14% a year while buy-and-hold lost 60%. That is worth +20.9 log-points a year over the whole period.
   - Recoveries cost 9.5 log-points and bull phases 4.6 (`regime_table.csv`).
3. **It works because the two signals make different mistakes, and "AND" keeps each one's strength:**
   - **Small caps break first at market tops.** At the 12 Smallcap 100 falls of 20% or more in 2006–2020, Smallcap 100's signal sold first or in the same week 8 times. Nifty 100 never sold first; in the other 4, it was already SELL.
   - **Large caps refuse to confirm small-cap bear-market rallies.** 22% of the pair's entries were false, against 39% for Smallcap 100 alone. In the 59 weeks when only Smallcap 100 said BUY, Smallcap 100 fell at a 44% annualised rate (`mech_lead_lag_sc100_20pct_falls.csv`, `mech_signal_diagnostics.csv`, `regime_table.csv`).
4. **Evidence strength:**
   - **Beats Smallcap 100 alone:** P ≈ 94–96% in a resampling test, and higher CAGR in 92% of 5-year windows on every index tested.
   - **Worst fall shallower than buy-and-hold:** in 100% of 3- and 5-year windows. On the Smallcap 100 index it is shallower than 774 of 775 randomly shifted signal histories.
   - **Beats buy-and-hold on return:** only P = 80% on Smallcap 100, 63% on the blend and 37% on Nifty 100 (`robust_bootstrap.csv`, `robust_rolling_summary.csv`, `robust_shift_summary.csv`).
5. **What to expect:**
   - worst falls of about −20% to −30%;
   - well ahead of buy-and-hold in years with a deep fall (+34 pp a year on average in 2008, 2011 and 2018);
   - behind in straight bull years (−22 pp in 2007, 2010, 2012, 2014 and 2017);
   - far behind in small-cap booms that large caps don't join: 2021 Jan–Oct, +21% against +52% (`years_by_regime_oos.csv`).

## 2. What was tested

| Item | Detail |
|---|---|
| Rules | pair (N100 AND SC100), triple (N100 AND MC100 AND SC100), Smallcap 100 only, the held index's own signal, buy-and-hold |
| Signals | production `Master_*.xlsx` SIGN, weekly, reproduced exactly from index prices (`verify_master_signs.py`); a Friday decision trades at the next session's close |
| Held indices | Nifty 50, Nifty 100, Midcap 100, Smallcap 100, and the equal-weight blend of N100/MC100/SC100 (2007–26) |
| Sleeves | cash (LBES, 2007+); 50/50 gold/cash and all gold (GOLDBEES, 2014-07+) |
| Portfolios | the 4 parents' real baskets 2014-07 → 2021-10 (OOS) and the 4 AA books 2021-11 → 2026-08 (IS), on the unit-based harness |
| Costs | 20.8 bps per full switch; the sensitivity runs to 100 bps |
| Engine check | the continuous NAVs reproduce the published table: the pair on Smallcap 100, 2007–21, is 14.41% and −28.6% (`deep_core_common.py`) |

Code:
- `deep_core_common.py`: data and continuous NAVs.
- `deep_years_episodes.py`: years and swings.
- `deep_regimes_mech.py`: regimes and mechanism.
- `deep_robust.py`: robustness.
- `deep_sleeve_*.py`: sleeve and gold, from the workflow analyst.

## 3. The whole out-of-sample period, cash sleeve (`core_period_stats.csv`)

| Held index | Buy & hold | Own signal | Smallcap 100 only | **Pair** | Triple |
|---|---|---|---|---|---|
| Smallcap 100 | 7.6%, −77.5% | (= SC100 only) | 8.6%, −50.1% | **14.4%, −28.6%** | 14.7%, −27.8% |
| Blend | 10.3%, −70.0% | – | 7.6%, −47.8% | **12.6%, −22.4%** | 12.9%, −21.9% |
| Midcap 100 | 12.0%, −69.6% | 14.0%, −35.6% | 9.1%, −50.0% | **13.9%, −23.8%** | 13.9%, −23.8% |
| Nifty 100 | 10.6%, −61.5% | 10.5%, −22.9% | 4.8%, −44.0% | **9.2%, −18.1%** | 9.7%, −20.7% |
| Nifty 50 | 10.3%, −59.9% | 10.5%, −22.1% | 4.5%, −42.3% | **8.7%, −19.4%** | 9.3%, −21.8% |

- **Return per unit of worst fall (Calmar):** the pair's is 0.50 on Smallcap 100, against 0.10 for buy-and-hold and 0.17 for Smallcap 100 alone. On the blend it is 0.56 against 0.15 and 0.16.
- **Volatility:** 14.7% against 23.7% for buy-and-hold on Smallcap 100.

## 4. Year by year (`years_wide.csv`, `years_by_regime_oos.csv`)

Smallcap 100 held, cash sleeve. Each year's return is from one continuous run, so positions carry across year ends. The label comes from Smallcap 100 buy-and-hold, in hindsight: bull > +15%, bear < −10%, and V = an intra-year fall deeper than 20% in a year that still ended up.

| Year | Label | Buy & hold | SC100 only | **Pair** | Pair − B&H | Pair − SC100 |
|---|---|---|---|---|---|---|
| 2007 (Jul–Dec) | bull | +54.2 | +42.4 | +37.4 | −16.8 | −5.0 |
| 2008 | bear | −71.0 | −39.1 | **−15.5** | **+55.5** | **+23.6** |
| 2009 | V | +107.0 | +40.1 | +65.1 | −41.9 | +25.0 |
| 2010 | bull | +17.6 | +17.6 | +17.7 | +0.1 | +0.1 |
| 2011 | bear | −33.9 | −22.0 | **+2.0** | **+35.9** | **+24.0** |
| 2012 | bull | +36.8 | +5.6 | +3.5 | −33.3 | −2.1 |
| 2013 | flat | −8.3 | +11.1 | +11.1 | +19.4 | 0.0 |
| 2014 | bull | +55.0 | +25.3 | +26.6 | −28.4 | +1.3 |
| 2015 | flat | +7.2 | −9.1 | −6.6 | −13.8 | +2.5 |
| 2016 | V | +2.3 | −6.1 | **+20.6** | +18.3 | **+26.7** |
| 2017 | bull | +57.3 | +25.9 | +23.8 | −33.5 | −2.1 |
| 2018 | bear | −29.1 | −17.4 | −17.4 | +11.7 | 0.0 |
| 2019 | flat | −9.5 | −3.0 | −3.6 | +5.9 | −0.6 |
| 2020 | V | +21.5 | +52.4 | +52.4 | +30.9 | 0.0 |
| 2021 Jan–Oct | bull | +51.9 | +51.9 | **+21.4** | **−30.5** | **−30.5** |
| 2022 (IS) | bear | −13.8 | −12.2 | +3.6 | +17.4 | +15.8 |
| 2023 (IS) | bull | +55.6 | +58.1 | +38.8 | −16.8 | −19.3 |
| 2024 (IS) | bull | +23.9 | +14.9 | +25.3 | +1.4 | +10.4 |
| 2025 (IS) | flat | −5.6 | −5.8 | +4.9 | +10.5 | +10.7 |
| 2026 to Aug (IS) | flat | +12.8 | +15.5 | +15.5 | +2.7 | 0.0 |

**By type of year, OOS 2007–2020, Smallcap 100 held** (`years_by_regime_oos.csv`):

| Year type | Years | Buy & hold | Pair | SC100 only | Pair − B&H | Pair − SC100 | Worst fall inside the year: pair / B&H |
|---|---|---|---|---|---|---|---|
| Bear | 2008, 2011, 2018 | −44.6% | −10.3% | −26.2% | **+34.3 pp** (3 of 3) | +15.8 pp | −17% / −49% |
| V (crash, then up) | 2009, 2016, 2020 | +43.6% | +46.0% | +28.8% | +2.5 pp (2 of 3) | **+17.2 pp** | −13% / −30% |
| Flat | 2013, 2015, 2019 | −3.5% | +0.3% | −0.3% | +3.8 pp (2 of 3) | +0.6 pp | −11% / −24% |
| Bull | 2007, 2010, 2012, 2014, 2017 | +44.2% | +21.8% | +23.3% | **−22.4 pp** (1 of 5) | −1.5 pp | −11% / −11% |

- **Other indices, same pattern.** On the blend, the pair beat buy-and-hold in 3 of 3 bear years by +27.6 pp, and lost in all 5 bull years by −21.4 pp. On Nifty 100 the figures are +21.2 pp and −19.1 pp (`years_by_regime_oos.csv`).
- **Year counts, OOS 2007–2020** (`years_summary_oos.csv`):
  - The pair beat buy-and-hold in 8 of 14 years on Smallcap 100, 6 on the blend and 5 on Nifty 100.
  - Against Smallcap 100 alone on the Smallcap 100 index: better in 7 years, equal in 3 (the signals never disagreed), worse in 4.
  - Its worst fall inside the year was shallower than buy-and-hold's in 11 of 14 years.
- **The costliest stretch is small-cap-led rallies that large caps don't join.** In 2021 Jan–Oct, Smallcap 100 alone stayed invested all year (+51.9%), while the pair was out for Nifty 100 weakness (+21.4%).

**With gold in the sleeve, and on the actual portfolios** (sleeve analyst, `sleeve_yearly_table.csv`):
- The same years-and-rule pattern holds.
- 50/50 adds return in years when gold rose (2016, 2019, 2020, and 2022–26 IS), and subtracts in 2014–15.
- On the 4 parents OOS (2014–21), the pair with 50/50 lost to the parent in 2014, 2015, 2017 and 2021 (−24 to −44 pp). It won in 2016, 2018, 2019 and 2020 (+8 to +20 pp).

## 5. Falls and rallies: every 10% swing (`swings_all.csv`, `swings_capture_oos.csv`)

The swings are 10% zig-zag pivots on Friday closes: a fall is confirmed when the index rises 10% off its low, and a rally when it falls 10% off its high. OOS, completed swings the rules traded (2008-01 → 2021-10), Smallcap 100 held, cash sleeve. Each figure is the average return over the swing.

| Swing type | n | Buy & hold | **Pair** | SC100 only | Share of the move the pair took | SC100 only's share |
|---|---|---|---|---|---|---|
| All falls | 18 | −25.6% | **−7.5%** | −13.4% | **29%** | 52% |
| Falls of 20%+ | 11 | −33.4% | **−6.9%** | −14.9% | **21%** | 45% |
| Falls of 10–20% | 7 | −13.3% | −8.6% | −11.1% | 65% | 83% |
| All rallies | 17 | +38.5% | +17.3% | +18.3% | 45% | 47% |
| Fast rallies (≤13 weeks) | 9 | +27.8% | +12.6% | +13.3% | 45% | 48% |
| Slow rallies (>13 weeks) | 8 | +50.5% | +22.6% | +23.8% | 45% | 47% |

**The asymmetry is the whole story.** The pair takes about 45% of a rally and only 29% of a fall. Smallcap 100 alone takes a similar share of rallies (47%) but 52% of falls. The pair gives up almost nothing extra in rallies and saves a lot in falls.

- **On the blend:** falls 26% against 51% for Smallcap 100 alone; rallies 40% against 43%.
- **Timing:**
  - In falls, the pair's median exit came after the index had fallen 6.7% from the swing high, against 10.3% for Smallcap 100 alone.
  - In rallies, its median entry came when the index was 12.8% off the low, against 12.5%.
  - So it exits earlier and enters barely later.
- **Where the pair beat Smallcap 100 alone.** These are falls in which Smallcap 100's signal re-entered a bear-market rally and Nifty 100's did not (pair against SC100 only):

  | Fall | Pair | SC100 only |
  |---|---|---|
  | 2008-05 → 07 | +1.3% | −15.0% |
  | 2008-08 → 12 | +2.4% | −11.3% |
  | 2009-01 → 03 | +0.7% | −18.1% |
  | 2011-04 → 12 | −2.5% | −25.4% |
  | 2015-04 → 06 | +0.9% | −9.0% |
  | 2016-01 → 02 | +0.5% | −15.9% |
  | 2016-10 → 12 | −4.4% | −12.1% |

- **Where it lagged Smallcap 100 alone:**
  - the 2020-04 → 2022-01 rally, +95% against +144% (it straddles the OOS/IS boundary);
  - 2014-10 → 2015-04, −1.2% against +5.3%;
  - 2008-12 → 2009-01, +0.4% against +4.1%.
- **Exit quality** (`swings_exit_quality.csv`, OOS). The pair had 24 exits and Smallcap 100 alone 29. About half of each were followed by a further fall of 10% or more within 26 weeks (50% against 52%). The false exits cost less for the pair: the index averaged +18.8% over the next 13 weeks, against +23.1%.

## 6. Regimes (`regime_table.csv`, `regime_state_cross.csv`)

Each session carries the label in force at the review that governs it, so the ex-ante labels use only data known at that review. "Contribution" is the log-point gap earned inside the bucket, per year of the whole period, so the buckets add up to the total gap.

**R1, market phase (hindsight), Smallcap 100 held, OOS:**

| Phase | Weeks | Buy & hold (ann.) | Pair (ann.) | SC100 only (ann.) | Pair in equity | Pair − B&H contribution | Pair − SC100 contribution |
|---|---|---|---|---|---|---|---|
| Bear (inside a 20%+ fall) | 194 | −59.9% | −14.2% | −28.9% | 9% | **+20.9** | **+5.1** |
| Correction (10–20% fall) | 70 | −19.0% | −23.2% | −30.5% | 47% | −0.5 | +1.0 |
| Recovery (rising, below the prior high) | 207 | +87.7% | +35.5% | +32.5% | 43% | **−9.5** | +0.7 |
| Bull (above the prior high) | 236 | +62.5% | +41.7% | +48.2% | 76% | −4.6 | −1.5 |
| **Total** | | | | | | **+6.3** | **+5.3** |

- **Where the edge comes from:**
  - **Against buy-and-hold:** bear phases, less the cost of re-entering late in recoveries.
  - **Against Smallcap 100 alone:** mostly bear phases (+5.1). It gives back only 1.5 in bull phases.
- **Corrections of 10–20% don't pay.** The rule exits partway down and does not avoid enough.
- **The same pattern on the blend:** bear +15.4, recovery −8.3, bull −4.0.

**Ex-ante labels, which need no hindsight, OOS, Smallcap 100 held:**

| Label | Bucket | Weeks | Pair − B&H (ann.) | Pair − SC100 (ann.) | Pair − B&H contribution | Pair − SC100 contribution |
|---|---|---|---|---|---|---|
| R2 trend | SC100 below its 40-week average | 285 | +24.1 pp | +13.9 pp | **+9.6** | **+5.2** |
| | above | 423 | −6.6 pp | +0.1 pp | −3.3 | +0.1 |
| R3 volatility (expanding terciles) | high | 178 | +21.2 pp | +13.0 pp | +4.6 | +2.7 |
| | mid | 294 | +6.8 pp | +6.1 pp | +2.6 | +2.3 |
| | low | 236 | −3.1 pp | +0.9 pp | −0.9 | +0.3 |
| R4 leadership (SC100 − N100, 26 weeks) | large-led | 237 | +18.8 pp | +7.7 pp | +5.4 | +2.1 |
| | neutral | 223 | +11.4 pp | +9.9 pp | +3.4 | +3.0 |
| | small-led | 248 | −8.5 pp | +0.7 pp | −2.6 | +0.2 |

- **The edge survives without hindsight.** Against Smallcap 100 alone, it is earned almost entirely when small caps are already below their 40-week average (+5.2 of +5.3). In those conditions a small-cap BUY without large-cap confirmation is usually a bear-market rally.
- **It pays in high and mid volatility, and when small caps are not leading.**
- **It costs against buy-and-hold** when small caps are leading and trending up.
- **The co-movement hypothesis is not supported.** R7, the trailing N100/SC100 correlation, shows no monotone pattern. By correlation tercile, the pair − SC100 annualised gap is low +2.5 pp, mid +11.3 and high +10.5. So the idea that "the pair adds more when large and small caps move apart" fails.
- **In-sample differs.** The edge over Smallcap 100 came in above-trend weeks instead. The in-sample window holds only 32 bear weeks.

**Forward returns by signal state and phase, OOS** (`regime_state_cross.csv`):
- **Only-SC100-BUY in a bear phase:** Smallcap 100 averaged −10.9% over the next 4 weeks (21 weeks).
- **Only-SC100-BUY while SC100 is below its 40-week average:** −9.2% over 4 weeks, and 36% rose over 13 weeks (28 weeks).
- **The same state above the average is benign:** +2.9% over 4 weeks, and 85% rose over 13 weeks (47 weeks). This is where the pair pays a cost.

## 7. The mechanism: why large-cap confirmation works

**a. Where the return gap comes from** (`mech_decomposition.csv`, OOS, Smallcap 100 held, cash; arithmetic pp a year, which add up exactly with zero residual):

| Comparison | Losses avoided | Gains missed | Sleeve earned | Extra costs | Total (arith.) |
|---|---|---|---|---|---|
| Pair vs buy-and-hold | 78.6 | 76.0 | 2.6 | 0.7 | +4.5 |
| SC100 only vs buy-and-hold | 64.1 | 66.1 | 2.3 | 0.8 | −0.6 |
| Pair vs SC100 only | 14.5 | 10.0 | 0.4 | −0.2 | **+5.1** |

- **Being out is costly in both directions.** Out-of-market days carry enormous gains and losses (76–79 pp a year each way). Smallcap 100 alone loses more than it avoids (−0.6). The pair avoids more than it misses (+4.5).
- **The CAGR gap is larger than the arithmetic gap:** +6.8 pp against +4.5. The extra comes from lower volatility (14.7% against 23.7%): compounding a −77% crash costs far more than its arithmetic average suggests.
- **The pair and Smallcap 100 alone differ on only 295 sessions** (8% of the period). On those sessions the pair avoided 14.5 pp a year of losses and missed 10.0.

**b. Signal quality on Smallcap 100** (`mech_signal_diagnostics.csv`, OOS; an independent recount from the weekly signals gives the same false-entry figures):

| | Pair | SC100 only | N100 only | Triple |
|---|---|---|---|---|
| Entries | 23 | 28 | 22 | 23 |
| Whipsaws (in-market spells ≤ 4 weeks) | 3 | 6 | 0 | 4 |
| **False entries** (lower 13 weeks later) | **22%** | 39% | 27% | 26% |
| False exits (higher 13 weeks later) | 61% | 61% | 55% | 57% |
| Median entry lag (% off the low) | 14.0% | 13.1% | 13.6% | 14.0% |
| Median exit give-back (% off the high) | −9.1% | −10.9% | −9.9% | −7.1% |
| Time in equity | 45% | 53% | 57% | 44% |

The pair nearly halves false entries, for 0.9 pp of extra entry lag, and exits 1.8 pp earlier.

**c. The disagreement state** (`mech_states_summary.csv`, `mech_state_run_lengths_oos.csv`, OOS 2006–21):
- **How often:** "Only SC100 BUY" occurred in 75 review weeks (9%). Its runs are short: median 3 weeks, maximum 16.
- **While it lasts, it loses heavily.** Smallcap 100 returned −43.7% annualised over the sessions it governed (`regime_table.csv`).
- **What follows is worse than after "both BUY":**

  | After the state | Only SC100 BUY | Both BUY |
  |---|---|---|
  | Smallcap 100, next 4 weeks | −1.7% (48% up) | +2.0% (68% up) |
  | Worst point over the next 26 weeks | −17.0% | −11.1% |
  | Share of weeks inside a Smallcap 100 bear phase | 28% | 5% |

- **"Mostly bear-market rallies" is overstated.** Only 28–33% of these weeks are inside a bear or correction phase. The damage is concentrated there, as in the 2008, 2011 and 2016 rows of section 5.
- **Over 13 weeks the average turns positive (+7.5%),** because the state usually resolves into "both BUY", and the pair re-enters then.

**d. Lead-lag at the 12 Smallcap 100 falls of 20%+ in 2006–2020** (`mech_lead_lag_sc100_20pct_falls.csv`; signals only, so 2006 counts):

| | Count |
|---|---|
| Smallcap 100 sold first | 5 (2008-01, 2010-11, 2011-04, 2013-01, 2018-01) |
| Both sold the same week | 3 (2006-05, 2019-04, 2020-01) |
| Nifty 100 was already SELL at the peak, so the pair was out before the fall began | 4 (2008-05, 2008-08, 2009-01, 2016-01) |
| **Nifty 100 sold strictly first** | **0** |

- **At troughs the pair waits for the later of the two.** It re-entered the same week as Smallcap 100 alone in 6 of the 12, and 1 week later in 3. It waited much longer 3 times, all in 2008, and each wait kept it out of the next leg down:
  - after the 2008-03 low: 53 weeks, against 6;
  - after the 2008-07 low: 36 weeks, against 3;
  - after the 2008-12 low: 16 weeks, against 2.
- **In 2013, 2016 and 2019 it was Smallcap 100's signal that re-entered late,** so the pair lost nothing to Smallcap 100 alone.

**e. The two jobs, shown by the component rules** (`robust_family.csv`, OOS, Smallcap 100 held):

| Rule | CAGR | Worst fall |
|---|---|---|
| Nifty 100's signal alone | 13.9% | −42.9% |
| Smallcap 100's signal alone | 8.6% | −50.1% |
| Pair | 14.4% | −28.6% |

- **Nifty 100's signal supplies most of the return.** It is a better small-cap timer than small caps' own signal, because it does not chase bear-market rallies.
- **Smallcap 100's signal supplies the early exit,** which cuts the worst fall by 14 pp.
- **"AND" keeps both.** "OR" keeps the worst of each: 8.1% and −50.0%.

**In plain words.** Small caps are the first to crack at a top, so their signal is the better exit trigger. After a crack, small caps throw off sharp rallies inside a larger decline; large caps don't join these, so the large-cap signal is the better entry filter. Requiring both means leaving on the first warning and returning only when the whole market confirms. That asymmetry, early out and confirmed in, is why the pair keeps 45% of rallies but takes only 29% of falls.

## 8. Robustness (`robust_*.csv`)

**Rolling windows, OOS only** (`robust_rolling_summary.csv`, cash, windows ending by 2021-10-29):

| Held index | Horizon | Pair CAGR > B&H | Worst fall shallower than B&H | Calmar > B&H | Pair CAGR > SC100 only | Median pair − B&H |
|---|---|---|---|---|---|---|
| Smallcap 100 | 3 years | 57% | 100% | 78% | 81% | +2.0 pp |
| Smallcap 100 | 5 years | 56% | 100% | 79% | **93%** | +0.7 pp |
| Blend | 5 years | 26% | 100% | 61% | 92% | −2.4 pp |
| Midcap 100 | 5 years | 28% | 100% | 69% | 92% | −2.0 pp |
| Nifty 100 | 5 years | 15% | 100% | 38% | 92% | −4.9 pp |
| Nifty 50 | 5 years | 16% | 100% | 32% | 92% | −4.9 pp |
| Smallcap 100, 50/50 (2014+) | 5 years | 84% | 100% | 89% | 68% | +2.7 pp |

On Smallcap 100, buy-and-hold lost money over 19% of 5-year windows (30% of 3-year windows); the pair lost money over 1% (8%).

**Resampling test** (`robust_bootstrap.csv`; block bootstrap of paired daily returns, 26-week mean blocks, 2,000 draws, OOS cash):

| Held index | Comparison | Observed CAGR gap | 90% interval | P(gap > 0) |
|---|---|---|---|---|
| Smallcap 100 | vs buy-and-hold | +6.9 pp | −6.2 to +20.1 | 80% |
| Smallcap 100 | vs SC100 only | +5.9 pp | −0.3 to +12.2 | **94%** |
| Blend | vs buy-and-hold | +2.4 pp | −7.9 to +13.4 | 63% |
| Blend | vs SC100 only | +5.1 pp | −0.1 to +10.5 | **95%** |
| Nifty 100 | vs buy-and-hold | −1.4 pp | −9.8 to +7.6 | 37% |
| Nifty 100 | vs SC100 only | +4.5 pp | +0.1 to +9.1 | **96%** |

**Random-timing test** (`robust_shift_summary.csv`). The joint N100 + SC100 signal history is shifted by 26 weeks or more, with wrap-around, 775 times.
- **Smallcap 100 held:** the actual 14.4% beats 97% of the shifts (median shift 4.4%). The actual −28.6% worst fall is shallower than 99.9% of them (median −59%).
- **Blend:** 94% and 99.9%.

**Execution delay and costs** (`robust_delay_cost.csv`, Smallcap 100 held):

| Test | Pair | SC100 only |
|---|---|---|
| On time | 14.4%, −29% | 8.6%, −50% |
| 1 week late | 12.8%, −30% | 8.6%, −42% |
| 2 weeks late | 10.4%, −46% | 4.7%, −60% |
| 4 weeks late | 8.8%, −53% | 3.7%, −66% |
| 50 bps per switch | 13.3% | – |
| 100 bps per switch | 11.5% | – |

The rule is time-sensitive: a two-week delay loses most of the drawdown protection, so execution discipline matters. Costs matter much less.

**Supertrend settings** (`robust_settings.csv`). Signals are recomputed from index prices; multiplier 2 with 5 bars reproduces Master exactly. OOS, Smallcap 100 held, CAGR and worst fall:

| Multiplier × bars | Pair | SC100 only | N100 only |
|---|---|---|---|
| 1.5 × 5 | 13.7%, −38% | 9.8%, −49% | 14.1%, −46% |
| **2 × 5 (production)** | **14.4%, −29%** | 8.6%, −50% | 13.9%, −43% |
| 2 × 10 | 13.5%, −36% | 10.7%, −36% | 16.2%, −42% |
| 2.5 × 5 | 22.0%, −30% | 15.7%, −38% | 19.6%, −36% |
| 3 × 5 | 19.7%, −30% | 20.6%, −30% | 15.5%, −39% |

- **The pair beats Smallcap 100 alone at every setting up to 2.5,** and ties or loses at 3.
- **It always has the shallowest or equal worst fall.**
- **Confirmation helps most when the underlying signal is noisy** (tight bands). Once the signal is slow, a second filter adds little.
- **Production is not the best setting.** Multiplier 2.5 beats production for every rule out of sample. That grid was chosen after seeing the data, so it is a lead for a pre-registered test, not a reason to change.

**The rule family** (`robust_family.csv`, OOS, Smallcap 100 held):

| Rule | CAGR | Worst fall |
|---|---|---|
| **N100 AND SC100** | **14.4%** | **−28.6%** |
| N50 AND SC100 | 13.6% | −28.6% |
| MC100 AND SC100 | 13.9% | −34.8% |
| N100 AND MC100 | 14.1% | −43.1% |
| N100 OR SC100 | 8.1% | −50.0% |

Any "large AND small" pairing works. What matters is having a large-cap entry filter together with a small-cap exit trigger.

## 9. The sleeve and gold

From the sleeve analyst (`sleeve_*.csv`). The workflow's auditor did not run because of the usage limit; the key figures were spot-checked against the published tables.

| Test | Result |
|---|---|
| OOS 2014–21: 50/50 instead of cash | +0.9 pp a year on every index. It did **not** lift the pair above buy-and-hold: SC100 8.9% against 9.6%, blend 9.4% against 12.2%, 4 parents 16.8% against 25.4% |
| Where the OOS lift comes from | One defensive spell, 2019-05 → 2019-12, when gold rose 18.2%. Without it, 50/50 is below cash (7.8% against 8.0%) |
| In-sample 2021–26 | 68% (SC100), 89% (blend) and 75% (4 books) of the pair's excess over buy-and-hold came from gold. With a cash sleeve, the pair on the blend beats buy-and-hold by only 1.0 pp |
| Gold as a crisis hedge | Across the 14 Smallcap 100 falls of 10% or more since 2014, gold rose in 11, averaging +9.0% against −21.0% for Smallcap 100. Weekly correlation is about 0 (+0.01) |
| Does the rule time gold? | No. Out of sample, gold made 7.0% a year in the pair's defensive time and 6.9% in its equity time |
| Daily re-mix vs drifting 50/50 | At most 0.15 pp a year of difference |

## 10. Scenario playbook

| Market scenario (examples) | Pair vs buy-and-hold | Pair vs SC100 only | Why |
|---|---|---|---|
| Deep, drawn-out bear (2008, 2011, 2018) | **+34 pp a year** on SC100 (3 of 3); takes about a fifth of the fall | +16 pp | Exits after a ~7% fall; Nifty 100 blocks re-entry into bear-market rallies |
| Crash, then a V (2009, 2016, 2020) | About even (+2.5 pp) | **+17 pp** | Exits after about 10%; re-enters about 9 weeks after the low, at +27% |
| Choppy or flat (2013, 2015, 2019) | +3.8 pp; shallower falls (−11% against −24%) | +0.6 pp | Fewer whipsaws than SC100 alone |
| Straight bull (2007, 2010, 2012, 2014, 2017) | **−22 pp a year** (1 of 5) | −1.5 pp | Sits out 10–20% corrections and re-enters late |
| Small-cap boom that large caps don't join (2021; 2023 in-sample) | **−30 pp** (2021 Jan–Oct) | −30 pp | Nifty 100's SELL keeps the pair out while small caps run |
| Holding large caps (Nifty 50 / 100) | Behind in 85% of 5-year windows (median −4.9 pp) | Ahead | Large caps rarely fall far enough for the protection to pay back its cost |

## 11. Recommendation and evidence grades

| Claim | Grade | Backing |
|---|---|---|
| The pair cuts the worst fall to about −20% to −30% (from −60% to −77%) | **Strong** | 100% of 3- and 5-year windows; 99.9% of random shifts; every index |
| The pair is a better timer than Smallcap 100's own signal | **Strong** | P 94–96%; 92–93% of 5-year windows; every index; settings up to multiplier 2.5 |
| Large-cap confirmation is the mechanism (entry filter plus small-cap exit trigger) | **Strong** | False entries 22% against 39%; only-SC100 weeks at −44% annualised; lead-lag 8 of 12 exits with SC100 first or together; the family and component tests |
| The pair beats buy-and-hold on return on small caps | **Moderate** | +6.9 pp observed, P 80%; 56% of 5-year windows; depends on bear markets occurring |
| The pair beats buy-and-hold on return on large caps or the blend | **Not supported** | P 37–63%; 15–26% of 5-year windows |
| The triple improves on the pair | **Weak** | 0–1 pp; identical in-sample |
| The 2021–26 in-sample curve shows what to expect | **No** | 68–89% of its excess over buy-and-hold is gold's rally |

**Recommendation.**
- **Use N100 AND SC100 as a drawdown filter** for small- and mid-cap-heavy books. Expect it to beat Smallcap 100's own signal, and to beat buy-and-hold only over periods that contain a real bear market.
- **Keep the fixed 50/50 sleeve,** and treat its return as a bet on gold.
- **Execute on time:** two weeks late loses most of the protection.
- **Don't retune the supertrend settings on this evidence.** If the settings are revisited (multiplier 2.5 looked better for every rule), pre-register the test.

## 12. Caveats

- **Price return against total return.** The equity indices are price return and cash is total return. This flatters timing against buy-and-hold by about half the dividend yield, roughly 0.5–0.7 pp a year.
- **Hindsight labels.** Phase and year labels (R1, bull/bear/V) are hindsight descriptions. The ex-ante labels (R2–R4, R7) are the test that the edge exists without hindsight.
- **Small counts.** There are 12 OOS falls of 20%+, 14 OOS years and 11 OOS defensive spells with gold. The bootstrap intervals reflect this.
- **Unknown provenance of the settings.** The desk set the supertrend settings; if they were tuned on 2007–21, the OOS test is out of sample for the rule but not for the settings.
- **Short gold history.** Gold starts in 2014-07, with only one gold bear phase (2014–15).
- **Unaudited sleeve section.** The sleeve section comes from a workflow analyst whose auditor did not run (usage limit). The other sections were computed in this session, with tie-outs to the published table, a zero-residual decomposition identity, and an independent recount of false entries.
- **Daily-close worst falls.** Worst falls are on daily closes. Friday-close figures are in `years_long.csv` and `sleeve_period_results.csv`; they differ most for gold-heavy sleeves (the 2026-01/03 gold spike).
