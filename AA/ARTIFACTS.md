# AA research: index of published pages

Eight pages were published for the AA (asset-allocation) smallcase research, 2026-08 to 2026-10. This file lists each one with:
- its link;
- what it covers;
- what it highlights;
- what it concludes;
- how far that conclusion can be trusted.

**Before you start:**
- **The books.** SCMO_0042, 0043, 0044 and 0045 are the asset-allocation versions of the parent smallcases SCMO_0003, 0007, 0010 and 0029. An AA book holds its parent's basket while an index signal is risk-on, and switches the whole book to a defensive sleeve (gold and cash) when it turns risk-off.
- **The signals.** These are the desk's weekly supertrend files: Nifty 100 (N100), Nifty Midcap 100 (MC100) and Nifty Smallcap 100 (SC100), each giving BUY or SELL every Friday.
- **Access.** The links are private to their owner, and some are shared with named colleagues. Ask the owner (Manu) for access.
- **Two caveats apply everywhere.** Published parent NAVs exist only from 2021-11-01; any earlier parent return is the backtest harness's rebuild from the parents' real baskets, which is price return. And every rule here was designed after looking at at least part of the data shown.

## The eight pages at a glance

| # | Page | The question | Answer in one line | Status |
|---|---|---|---|---|
| 1 | [Gold, Not Timing](https://claude.ai/artifact/MtupD7qNGftVwmK9kZuJrW) | Where did the live AA books' edge over their parents come from? | Mostly from holding gold in a gold bull market, not from timing; two of the four books lost to their parents | Complete (Study 1) |
| 2 | [The Overlay Casebook](https://claude.ai/artifact/XhQkuQ1QDHR6hV15H66c9t) | What did Studies 1 and 2 find, and what went wrong along the way? | Every control added made the claim smaller | Study 1 complete, Study 2 provisional |
| 3 | [Holding by Segment](https://claude.ai/artifact/PMFzwMSEJiSNZrr9TcT9FW) | Should a book hold only the stocks whose own market-cap index is BUY? | No. It helps the strong parents and hurts the weak ones, and the gain doesn't survive a timing null | Rejected (Study 3, pre-registered) |
| 4 | [Why Both Must Agree](https://claude.ai/artifact/4xhkFuxZJp1Woqzp8a7AM5) | Why does "N100 AND SC100 both BUY" look best, and does it hold out of sample? | It is a better risk filter, not a reliably better return signal. Timing gold inside the sleeve doesn't help | Complete |
| 5 | [Pair Rule Regime Atlas](https://claude.ai/artifact/GhzZN9jTGNg3e4T54QfBeB) | How does the pair rule behave in every year, fall, rally and regime since 2007? | It wins in bear markets and pays some back in bull runs; drawdown protection is robust, the return edge is not proven | Complete |
| 6 | [Final Rule Backtest](https://claude.ai/artifact/Rw91HV3p9p5nfeuwXmpVSs) | How do the four books do under the final rule (three indices agree, else gold/cash split by MCX gold's trend)? | 26.6% a year live against 16.6% for the live AA, but below the parents on return in 2014–21 | Backtest; rule chosen in-sample |
| 7 | [MAUc1 Gold Trend](https://claude.ai/artifact/4uSahKWNQr4QFDLKHdRY7k) | Should gold's trend come from MCX gold futures (MAUc1) instead of GOLDBEES? | The two agree on 82% of weeks, and switching barely moves the backtest. The production-code MAUc1 signal is now the one used | Complete |
| 8 | [Own-Momentum Test](https://claude.ai/artifact/NZjkYNzEk4QFBvmwa5ZLJV) | Can a smallcase's own index momentum (65-day percentile, bottom 25%) tell when to de-risk? | No: it fails all three pre-registered tests and is worse than holding in 2021–26 on both return and drawdown | Refuted (test T01, pre-registered) |

---

## 1. Gold, Not Timing (Study 1)

**Link:** https://claude.ai/artifact/MtupD7qNGftVwmK9kZuJrW (also reachable at the older link https://claude.ai/code/artifact/a93640d3-18ba-45ca-b8e9-88a693c2dd9b) · last updated 2026-09-01

**What it covers.** The four live AA books against their parents, 2021-11-01 → 2026-08-21 (1,186 sessions, before costs).
- The gap between each AA book and its parent is split exactly into two parts: **tracking**, the days the book should have held its parent, and **timing**, the days it was out of equity.
- It then asks whether the timing showed skill.

**What it highlights:**
- **Only two of the four books beat their parents.** The overlay added 5.8 pp a year to 0042 and 7.1 to 0043, and cost 0044 4.5 and 0045 3.7. CAGRs: 0042 21.6% vs 15.0%, 0043 14.2% vs 6.7%, 0044 15.2% vs 20.6%, 0045 15.2% vs 19.6%.
- **Gold supplied 84% of everything the defensive sleeve earned.** While the books sat out of equity, the parents mostly *rose*: for 0042 the parent gained 11.5% while the sleeve made 46.3%, because gold nearly doubled.
- **The timing is not statistically distinguishable from random.** No book cleared a random-placement null (best: 0043 at the 84th percentile, z = 1.01). The test could only have detected an edge of about +100% cumulative.
- **0043's case rests on one episode.** August 2025 to April 2026 accounts for 92% of its value added while out of equity.
- **The signal lags by about five weeks.** Switching earlier would have beaten the actual switches every time.
- **The overlay helped exactly where the stock picking was weak.** The parents' selection alpha against their own market-cap blend is −4.8% (0003) and −7.7% (0007), but +3.0% (0010) and +2.4% (0029). That is the pattern of a blunt de-risking rule, not a timing rule.
- **Tracking was not zero, and the cause is operational.** The AA books sometimes failed to adopt the parent's quarterly reconstitution. For example, on 2022-09-15 parent 0010 replaced 6 of its 15 names, and 0044 kept the old six until the end of October.
- **The books don't run the signal they are described as running.** 0042 and 0043 follow the Smallcap 100 supertrend alone; 0044 and 0045 use two-index blends at a 0.6 threshold.
- **Smaller-cap signals mark gold's good periods better,** in strict market-cap order. Microcap 250 is the only one significant on its own (98th percentile), and not after allowing for the eight signals tried. A broad index (Nifty 500) is no better than random.

**Inferences:**
- **The live AA outperformance is mainly gold exposure during a gold bull market,** not skilled timing. Take gold out of the sleeve and the edge goes with it.
- **The cheapest fix is operational:** carry the parent's reconstitutions into the AA book on the same day.
- **On signals,** smaller-cap trends and "both must agree" rules are the promising direction. This finding led to Studies 2–5.

**Caveats:** one five-year window holding one uninterrupted gold bull market; before costs.

**Source:** `AA/analysis/evidence/main/report.html`; methods in `AA/analysis/evidence/main/METHODS.md`.

---

## 2. The Overlay Casebook (Studies 1 and 2)

**Link:** https://claude.ai/artifact/XhQkuQ1QDHR6hV15H66c9t (also reachable at the older link https://claude.ai/code/artifact/f8968d24-d72f-4a2d-b137-5d67b1bde507) · last updated 2026-08-26

**What it covers.** A record of the first two studies: what was asked, what was found, every correction, and what was still open. Study 2 tested **segment-level selection**: classify each holding into a market-cap bucket, keep it only while its own bucket's index is trending, and send the rest to the sleeve.

**What it highlights:**
- **The claim shrank with every control.** It started as "all four outperformed". Then it was two of four. Then 84% of the gain was gold. Then the timing wasn't significant.
- **Study 2's best variant shrank too.** The variant that also required Nifty 100 to be trending beat the parents by +8.16 pp a year on average (after 20.8 bps costs). The static-mix control then showed +2.90 pp of that was just holding a sleeve that out-returned equity, leaving +5.25 pp as possible timing.
- **The point-in-time classifier needed real work.** Semi-annual market-cap ranks reached 94.0% three-bucket accuracy. The microcap band had to be widened to ranks 501–900, which lifted microcap recall from 68% to 92%.
- **Production changed its signal inputs mid-stream.** On 2026-04-24 it switched from Nifty100 | MC100 | SC100 to Nifty100 | Midcap150 | Smallcap250. The published track record was produced by the Smallcap 100 rule (98.9% agreement), not the Smallcap 250 rule now in production (89.9%).
- **A corrections log lists six errors** found by our own controls:
  - LIQUIDBEES priced at a zero return;
  - microcap missing from the factor set;
  - tracking drift attributed to the wrong cause;
  - an agreement bar set too high to reach;
  - a simulator that re-trimmed positions every week;
  - audit counters counting everything three times.

**Inferences:**
- **Study 2's headline was not settled.** It still needed a plain large-cap regime filter as a control, an all-cash sleeve, and a null on the timing term. Study 3 re-ran the idea with those controls.
- **The track record and the current engine are not the same strategy,** because production's signal inputs changed in April 2026.

**Source:** `AA/analysis/evidence/segment_v1/casebook.html`.

---

## 3. Holding by Segment (Study 3, pre-registered)

**Link:** https://claude.ai/artifact/PMFzwMSEJiSNZrr9TcT9FW · last updated 2026-09-25

**What it covers.** The proposed rule, tested against the current whole-book switch on identical prices, fills and costs, 2021-11 → 2026-08:
- tag every holding with its own market-cap index (index membership from 2026-04, monthly market-cap ranks before that);
- hold it only while that index's supertrend is BUY;
- send the freed weight 50/50 to GOLDBEES and cash.

The pass criteria were written down before anything ran.

**What it highlights:**
- **Return against the current whole-book rule,** after 20.8 bps: −2.51 pp a year (0042), −0.43 (0043), +2.09 (0044) and +2.97 (0045). It needed to be positive on at least 3 books, including both 0044 and 0045, so it fails.
- **It helps the parents with strong stock selection** (0010 and 0029, behind 0044 and 0045) and **hurts the weak ones** (0003 and 0007).
- **The gain doesn't survive a timing null.** When the signal history is shifted in time, the rule still beats the whole-book switch in only 45–68% of shifts. So the gain on 0044 and 0045 is specific to this history.
- **It also fails the static-mix control and the all-cash sleeve:** 2 of 4 books each.
- **The baseline doesn't match the published parents.** The harness rebuild of the parents is within ±1 pp a year of the published series on three books; 0045 is off by −2.9 pp a year.
- **A variant also requiring Nifty 100 to be BUY looked strong** (+3 to +7 pp on every book). But it wasn't pre-registered and fails the same shift test, so it is not a recommendation.

**Inferences:**
- **REJECTED:** holding only the stocks whose index is BUY is not a robust improvement on the whole-book switch.
- **One lead remains:** segment holding may help books whose parent has strong stock selection. That idea came from this data, so it needs new books or a later period.

**Source:** `AA/analysis/evidence/segment_v2/report.html`; the pre-registration, gates and methods are in the same folder (`PREREGISTRATION.md`, `gates.json`, `METHODS.md`).

---

## 4. Why Both Must Agree (the N100 AND SC100 rule)

**Link:** https://claude.ai/artifact/4xhkFuxZJp1Woqzp8a7AM5 · last updated 2026-09-25

**What it covers.** Why "hold equity only when Nifty 100 and Smallcap 100 are both BUY" looked best on the live books, and whether that survives out of sample:
- on the indices, 2007–21;
- on the parents' real baskets, 2014–21.

It also covers timing the gold inside the sleeve, and adding Midcap 100 as a third index.

**What it highlights:**
- **The mechanism.** The pair rule differs from "Smallcap 100 only" only in weeks when Smallcap 100 is BUY but Nifty 100 is SELL, and those weeks are followed by losses. Out of sample, Smallcap 100 fell 3.1% over the next four weeks and rose only 44% of the time.
- **On the Smallcap 100 index, 2007–21,** cash sleeve:

  | Rule | CAGR | Worst fall |
  |---|---|---|
  | Pair rule | 14.4% | −29% |
  | Smallcap 100 alone | 8.6% | −50% |
  | Buy-and-hold | 7.6% | −77% |

  Any large-cap AND small-cap pair works this way; "N100 **OR** SC100" does not.
- **On the parents' real baskets, 2014–21,** the pair rule had the best worst fall (−23% vs −26%) but the lowest return of the timing rules (16.8% vs 18.3% for Smallcap 100 alone). It lost 37 pp in 2021's small-cap boom and gained 27 pp in 2016.
- **Why the 2021–26 curve looks so clean:**
  - two long defensive spells happened to cover the 2022 and 2024–25 falls;
  - gold rose 50% during the third spell;
  - four stretches (6% of sessions) made its whole edge over Smallcap 100 alone;
  - it was picked as the best of 15 rules on that same window.
- **Timing gold with GOLDBEES' own supertrend is exposure, not timing.** It lost 2.1–3.2 pp a year in 2021–26 against a fixed sleeve holding the same average gold share. Gold's SELL weeks were as good for gold as its BUY weeks (14.8% vs 14.6% a year), and gold barely trends at 4–13 week horizons.
- **Adding Midcap 100 changes almost nothing.** Midcap 100 was SELL while the other two were BUY in only 5 of 502 weeks since 2006.
- **An all-gold sleeve looks best only because of gold's rally:** on the live books, 34.2% a year against 25.7% with 50/50 and 16.7% with cash.

**Inferences:**
- **The pair rule is the strongest drawdown filter tested, not a proven return improvement.** Expect it to lag small-cap-led booms that large caps don't join, as in 2021.
- **Don't time the gold leg on GOLDBEES' own trend.**
- **The three-index rule behaves almost exactly like the pair.**

**Source:** `AA/analysis/evidence/why_n100sc100/report.html`; code `AA/analysis/why_n100sc100.py`, `why_parents_oos.py`, `gold_why.py`, `triple_and_test.py`.

---

## 5. Pair Rule Regime Atlas (the deep study)

**Link:** https://claude.ai/artifact/GhzZN9jTGNg3e4T54QfBeB · last updated 2026-09-25

**What it covers.** The pair rule out of sample, 2007-07 → 2021-10, measured:
- in every calendar year;
- in every 10% fall and rally;
- under seven different ways of labelling market regimes;
- through its mechanism, robustness tests (rolling windows, a bootstrap, a timing null, cost and settings checks) and the sleeve.

**What it highlights:**
- **On the Smallcap 100 index:**

  | Rule | CAGR | Worst fall | Return ÷ worst fall (Calmar) |
  |---|---|---|---|
  | Pair rule | 14.4% | −28.6% | 0.50 |
  | Buy-and-hold | 7.6% | −77.5% | 0.10 |
  | Smallcap 100 alone | 8.6% | −50.1% | 0.17 |

- **By type of year:**
  - bear years (2008, 2011, 2018): +34.3 pp against buy-and-hold, 3 of 3;
  - crash-then-recovery years: +2.5 pp;
  - flat years: +3.8 pp;
  - bull years: −22.4 pp (it beat buy-and-hold in only 1 of 5).
- **Falls and rallies.** The pair takes 29% of a fall but 45% of a rally. Smallcap 100 alone takes 52% of falls and 47% of rallies.
- **The mechanism:**
  - At the 12 Smallcap 100 falls of 20% or more, Smallcap 100's signal sold first or in the same week 8 times; Nifty 100 never sold first.
  - Large caps refuse to confirm small-cap bear-market rallies: 22% false entries against 39% for Smallcap 100 alone.
- **How robust it is:**
  - It beats Smallcap 100 alone with about 94–96% probability.
  - Its worst fall is shallower than buy-and-hold's in 100% of 3- and 5-year windows.
  - It beats buy-and-hold on return only 80% of the time on Smallcap 100, 63% on a blend of the three indices, and 37% on Nifty 100.
  - A two-week delay in acting removes the drawdown edge.

**Inferences:**
- **The pair is a robust drawdown filter and a better small-cap timer than Smallcap 100 alone,** but it is not proven to beat buy-and-hold on return.
- **What to expect:** worst falls of about −20% to −30%; well ahead in deep-fall years; behind in straight bull years; far behind in small-cap booms large caps don't join (2021 Jan–Oct: +21% against +52%).

**Source:** `AA/analysis/evidence/why_n100sc100/deep/report.html`; full synthesis in `deep/SYNTHESIS.md`, methods in `deep/METHODS.md`.

---

## 6. Final Rule Backtest

**Link:** https://claude.ai/artifact/Rw91HV3p9p5nfeuwXmpVSs · last updated 2026-09-29 (the backtest runs to 2026-08-21; the signal panel runs to 2026-09-25)

**What it covers.** The proposed final rule on each of the four books, with a book and period selector.
- **Equity:** hold the whole parent basket only while N100, MC100 and SC100 are all BUY.
- **Sleeve:** otherwise, hold GOLDBEES and cash, split 80/20 if MCX gold's weekly supertrend (MAUc1) is BUY and 20/80 if SELL, re-checked every week.
- **Timing:** signals at Friday's close; trades on Monday at that day's (open+high+low+close)/4. GOLDBEES fills have ETF-only price spikes clipped; costs are 20.8 bps round trip.
- **Periods:** the live window (2021-11 → 2026-08, the four AA books) and the parents' real baskets before the books existed (2014-07 → 2021-10).
- **What the page shows:**
  - equity and drawdown curves against the parent and the live AA;
  - allocation over time;
  - yearly returns;
  - a holdings-by-week heatmap;
  - every rebalance with holdings before and after;
  - a "where the rule stands now" panel.

**What it highlights (4-book averages):**

| | CAGR 2021–26 | Worst fall (daily) 2021–26 | CAGR 2014–21 | Worst fall (daily) 2014–21 |
|---|---|---|---|---|
| **Final rule** | **26.6%** | −20.7% (−12.9% on Friday closes) | **18.4%** | −23.8% |
| Split fixed when the sleeve is entered | 29.9% | −21.3% | 17.9% | −24.6% |
| Fixed 50/50 sleeve | 25.5% | −16.2% | 17.3% | −23.1% |
| Earlier version (gold signal from GOLDBEES) | 27.3% | −21.3% | 18.1% | −23.5% |
| Current AA rule, re-simulated | 16.5% | −24.9% | 18.0% | −29.5% |
| Live AA, published NAV | 16.6% | −20.5% | – | – |
| Parent, published NAV | 15.3% | −28.9% | – | – |
| Parent, same engine | 13.7% | −30.2% | **25.4%** | **−58.7%** |

- Per book, 2021–26: 0042 27.5%, 0043 22.2%, 0044 29.3%, 0045 27.5%.
- **Where the rule stands as of the 25-09 review:** N100 and MC100 are SELL and SC100 is BUY, so every book is in the sleeve. MAUc1 is BUY, so the sleeve is 80% GOLDBEES / 20% cash, a position held since the trade on 2026-09-15.
- **Cross-check:** an Excel workbook rebuilds the gold signal, every weekly decision and each book's daily value with live formulas. An independent formula engine checked it: 13 checks, 0 mismatches.

**Inferences:**
- **2021–26 looks very strong:** about 10 pp a year ahead of the live AA. Most of it came from being out of equity in the 2022 and 2024–25 falls and holding gold through its rally.
- **2014–21 is the sobering half.** The rule made about 7 pp a year *less* than simply holding the parents (18.4% vs 25.4%), in exchange for a much shallower worst fall (−24% vs −59%).
- **The gold-split choice is secondary.** Across the weekly re-check, the split fixed at entry, 50/50 and the GOLDBEES signal, results span 25.5–29.9% a year in 2021–26 and only 17.3–18.4% in 2014–21.
- **Read this as a drawdown-control rule with a strong recent record,** not a proven return edge. The three-index rule and the gold-timed split were both chosen after looking at 2014–26.

**Caveats:**
- Stock prices are price return.
- MAUc1 history starts in 2015-02, so the 2014–15 sleeve spells hold 50/50.
- The live window's worst daily fall comes from gold's spike in Jan–Mar 2026, with 80% of the book in gold.
- CAGR here is on calendar years.
- The backtest ends 2026-08-21; extending it needs newer LBES and NAV exports.

**Source:** `AA/analysis/evidence/final_strategy/report.html`; methods `final_strategy/METHODS.md`; workbook `final_strategy/final_strategy_workbook_mauc1.xlsx`; code `final_strategy*.py`, `final_book_report.py`.

---

## 7. MAUc1 Gold Trend

**Link:** https://claude.ai/artifact/4uSahKWNQr4QFDLKHdRY7k · last updated 2026-09-29

**What it covers.** The weekly supertrend of MAUc1 (MCX gold futures, continuous, ₹ per 10 g), as it read at each weekly rebalance from 2015-03 on, compared with the GOLDBEES-based gold signal used earlier.
- **Same code as the indices.** The signal is the desk's own production supertrend script (`ST.py`), run unmodified on MAUc1, the same way the Friday job runs it for the indices. Its outputs are laid out like the desk's folders in `AA/Historical Data/FRA_MAUc1/`.
- **Proof the harness matches production.** The same harness reproduces production's Nifty 100, Midcap 100 and Smallcap 100 signal files cell for cell.

**What it highlights:**
- **The two gold signals agree at 491 of 596 weekly reviews (82%).** Both are BUY about 64% of the time; MAUc1 flips more often (31 times vs 22).
- **They disagree in 14 stretches.** In those stretches, GOLDBEES' signal matched what GOLDBEES actually did in 9 (64 weeks); MAUc1's matched in 5 (41 weeks).
- **Latest reading, 25-09 review: BUY.** Close 150,881 against the supertrend line at 144,291.

**Inferences:**
- **Switching the gold signal to MAUc1 barely moves the final-rule backtest:** 26.6% vs 27.3% a year in 2021–26, and 18.4% vs 18.1% in 2014–21. MAUc1 is used at the desk's request, and it now comes from the same production code as the index signals.
- **A separate weekly MAUc1 file built outside the production code** groups every MCX session into Friday-ending weeks. It differs from the production signal in 6 weeks: five in Dec 2018 – Jan 2019 and one in Jun 2023. Both traced to MCX sessions on NSE holidays. The production signal is the one adopted.

**Caveats:**
- The MAUc1 history is a hand-cleaned Eikon export, with 7 rows fixed.
- A live Friday run at about 20:00 would see a partial MCX bar, because MCX trades until 23:30.

**Source:** `AA/analysis/evidence/final_strategy/mauc1/report.html`; methods `mauc1/METHODS.md`; signal files `AA/Historical Data/FRA_MAUc1/RSI/Final/Analysis/Master_MAUc1.xlsx`; code `mauc1_st_production.py`, `mauc1_st_compare.py`.

---

## 8. Own-Momentum Test (test T01, pre-registered)

**Link:** https://claude.ai/artifact/NZjkYNzEk4QFBvmwa5ZLJV · last updated 2026-10-05

**What it covers.** Whether a smallcase's **own** index series can tell when to move its weight into gold and cash.
- **The proposed rule:** each week, compare today's close with the last 65 closes; if it is in the bottom 25%, move to 50/50 gold/cash.
- **Periods:** the four parents in 2015–21 (harness rebuild) and 2021–26 (published series).
- **Comparisons:** holding the smallcase, and a random-timing control that has the rule's own exits placed at other weeks (same exposure, same number of switches).
- **Alongside it:** 27 other own-index rules (other windows and cut-offs, hysteresis, a stepped version, a daily-check version, moving averages, trailing return, falls from the 52-week high, a supertrend on the smallcase's own candles), plus the market-index rule for context.
- **Also on the page:** a table of seven ways to judge a smallcase's momentum.

**What it highlights:**
- **The proposed rule fails all three pre-registered tests:**

  | Test | 2015–21 | 2021–26 |
  |---|---|---|
  | Beat at least 90% of random timings (3 of 4 books needed) | 2 of 4 | 0 of 4 |
  | Worst fall at least 5 pp shallower than holding | 3 of 4 | 0 of 4 |
  | Calmar above holding | 3 of 4 | 0 of 4 |

  Four-book average CAGR: 20.5% vs 18.8% in 2015–21, and **9.6% vs 15.8% in 2021–26**.
- **On drawdown, in 2021–26 it was worse than holding on every measure:**
  - 59% of days spent at least 10% below the previous high, against 46%;
  - a longest drawdown of 750 days, against 606;
  - Ulcer index (average depth below the last high) 15.4, against 12.4.
- **Why it fails.** It exits only after a fall has shown up in the price (13% into the fall on average), and buys back on bounces about 2.8 times per fall. In 2021–26 its Ulcer index was worse than 91% of random timings with the same exposure.
- **No smallcase-own-price rule exits early.** All of them get out 11–15% below the peak.
- **Slow, damage-based rules hold up better.** "More than 10% below the 52-week high" is the only rule that beats holding on return and all four drawdown measures in both periods: CAGR 22.6% / 17.3%, Ulcer 10.4 / 9.3. But against random timing it is only median in 2021–26, so its benefit is mostly being out of equity about 40% of the time.
- **The best of the 28 rules is no better than the best of random draws** (35th–83rd percentile).
- **This design can only detect large edges.** Per book, the smallest timing edge it could detect is 12–18 pp a year.

**Inferences:**
- **A smallcase's own price can't give early warning,** because its own fall is the signal. Early exits need a leading signal, such as the market indices or breadth inside the basket.
- **The own-index signal is better suited as a second check than as the main exit.**
- **Next step:** a pre-registered test on many more smallcases, judged first on drawdown, with the 52-week-high, 200-day-average and weekly-supertrend rules as candidates.
- **Findings:** F-AA-S01 and S02 (refuted), F-AA-S03 (open), F-AA-M01 (the detection limit), all in `T01.md` §5.

**Caveats:**
- The drawdown measures were added after the test ran, so they are descriptive.
- CAGR on this page counts 252 trading sessions a year, so its levels read 0.2–0.5 pp above the calendar-year basis used on page 6.
- Fills are at the next session's close, because the smallcase index has closes only.

**Source:** `AA/tests/T01/evidence/report.html`; design and results `AA/tests/T01/T01.md`; methods `AA/tests/T01/evidence/METHODS.md`. An independent check, `check_page.py`, re-derives every number on the page from the raw files: 911 checks, 0 failures.

---

## What the eight pages add up to

1. **The live AA books beat their parents mainly through gold exposure, not timing,** and only on two of the four books (pages 1–2).
2. **Rebuilding the books holding by holding doesn't fix that** (page 3). A whole-book switch driven by **large and small caps agreeing** is the robust idea (pages 4–5).
   - It cuts worst falls in every period tested.
   - Its return edge depends on the regime: big in bear markets, negative in small-cap-led booms.
3. **The final rule (three indices agree, else gold/cash weighted by MCX gold's trend) has an excellent 2021–26 record** (page 6).
   - It gave up about 7 pp a year against the parents in 2014–21 in exchange for less than half the worst fall.
   - Both the rule and the gold weighting were chosen after seeing the data.
   - The choice of gold signal barely matters (page 7).
4. **Rules based only on a smallcase's own price don't time its falls** (page 8). Any early warning has to come from outside the smallcase's own series.

**Still open:**
- out-of-sample evidence for the final rule;
- a test of the slow own-index rules on many more smallcases;
- a relative-strength rule (smallcase ÷ benchmark);
- extending the backtest past 2026-08-21 once newer cash and NAV exports are available.
