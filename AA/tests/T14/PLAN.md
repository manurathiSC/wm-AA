# T14 Plan: the three-index switch with a different holding when the switch is OUT **and** gold is SELL (half parent + half GOLDBEES, or all liquid ETF), on both base sleeves (50/50 and 80/20), on T11's window 2014-09-01 -> 2019-01-02 and T08's window 2019-01-02 -> 2026-10-30

**Written 2026-11-23 by Claude, on Manu's request in chat.** Nothing in this plan has been run and no engine, verifier or analysis code exists. The only numbers below that were computed are week counts read from the stored decision logs of T08 and T11 (`decisions.csv`: switch state and gold signal per week, no price, NAV or return), and `python data/check_approved_data.py` (exit 0: 67 approved rows, 0 problems, 2026-11-23). **Status: DRAFT, awaiting Manu's approval.** On approval the frozen design becomes `T14.md` §1-§3 (Step 1), which wins over this plan where they differ. This file is kept as written once approved; a revision goes beside it as `PLAN_v2.md` (never overwrite this file). `PLAN.md` is the implementation plan; read it together with `AGENT.md` (the framework) and `AA/CLAUDE.md` (project rules: data boundary, commit rule, finding IDs).

---

## 0. Manu's request, in his words, and what was agreed

> "the changes that I want to make are based on the regimes where the three-regime switch is also in sell, and gold is also in sell. In those cases, I want to test two things: 1. To keep 50/50, both in the portfolio and in gold. 2. iteration is basically not keeping both of those and keeping just the liquid ETF."

Claude restated it and asked two questions. Manu's answers (chat, 2026-11-23):

> "[50% parent and 50% GOLDBEES] ... Plus any rebalances that the parent might be having, we will just trap the parent equities with 50% of the weight in this regime."
>
> "Do two iterations here, both 50/50 gold and cash, and 80/20 gold and cash."
>
> "Make the test folder, a new test folder, and make the plan such that it follows the norm, the framework that we have defined for any plan, such that any agent which is working on this particular test can read the plan and work on it."

So: **one change to the rule**, applied only in the weeks where the three-index switch is OUT (not all three of Nifty 100, Midcap 100, Smallcap 100 are BUY) **and** the weekly MAUc1 gold supertrend is SELL (called **the OUT-SELL regime** below). Two replacements for what the book holds in that regime, each tried on two base sleeves, on the two windows where the switch has already been tested on the real parents. Everything else is the rule of T06/T08/T11.

## 1. Context

| Test | Window | Rule | Result (after 20.8 bps) |
|---|---|---|---|
| T06 (COMPLETE 2026-11-06) | 2019-01-02 -> 2026-10-22, real parents, published-NAV calendar | switch; OUT = 50% GOLDBEES + 50% cash | equity timing PASS against N4.10 (CAGR percentiles 97.4, 94.1, 96.8, 94.6) |
| T08 (COMPLETE 2026-11-12) | 2019-01-02 -> 2026-10-30, same | switch; OUT = 80/20 GOLDBEES/cash when MAUc1 BUY, 20/80 when SELL | equity timing PASS (97.2, 94.2, 97.0, 95.0); gold timing FAIL (61.9 x4) |
| T11 (COMPLETE 2026-11-17) | 2014-09-01 -> 2019-01-02, real parents rebuilt from baskets | both rules (Part A = T06's, Part B = T08's) | all six criteria FAIL, low power |

T14 asks whether changing what the book holds in the OUT-SELL regime changes these results, and by how much against the original rule on the same prices, costs and null draws. **A new question under a changed rule gets a new test number** (AGENT.md task 3); T06, T08 and T11 keep their numbers. **Change one thing at a time** (AGENT.md task 5): the only change is the target in the OUT-SELL regime; the base sleeve (50/50 or 80/20) is not a change but the two existing rules, each run with the change.

## 2. The six rules (targets per weekly decision)

Notation of the existing engines: at each decision the target is `(e, gw)`, where `e` is the share of the book in the parent's basket and `gw` the share of the non-parent part in GOLDBEES (the rest is cash, the LBES liquid ETF series D11). Regimes are read at each weekly decision: **IN** = all three index SIGNs BUY; **OUT-BUY** = switch OUT and MAUc1 SIGN BUY; **OUT-SELL** = switch OUT and MAUc1 SIGN SELL.

| Rule id | Base sleeve | IN | OUT-BUY | **OUT-SELL** | Is |
|---|---|---|---|---|---|
| `50-orig` | 50/50 | e=1 (parent) | e=0, gw=0.5 (50% gold, 50% cash) | e=0, gw=0.5 (50% gold, 50% cash) | T06 / T11 Part A, unchanged (comparator, regression) |
| `50-half` | 50/50 | e=1 | e=0, gw=0.5 | **e=0.5, gw=1.0 (50% parent, 50% gold, 0 cash)** | variant 1 on the 50/50 base |
| `50-liq` | 50/50 | e=1 | e=0, gw=0.5 | **e=0, gw=0.0 (100% liquid ETF)** | variant 2 on the 50/50 base |
| `80-orig` | 80/20 | e=1 | e=0, gw=0.8 | e=0, gw=0.2 (20% gold, 80% cash) | T08 / T11 Part B, unchanged (comparator, regression) |
| `80-half` | 80/20 | e=1 | e=0, gw=0.8 | **e=0.5, gw=1.0** | variant 1 on the 80/20 base |
| `80-liq` | 80/20 | e=1 | e=0, gw=0.8 | **e=0, gw=0.0** | variant 2 on the 80/20 base |

The four rules in bold are new; the two `-orig` rules are the existing ones, re-run by the same engine as comparators and as the regression gate. Note: `50-orig` does not use the gold signal at all; `50-half` and `50-liq` make the 50/50 rule depend on the gold signal for the first time.

### 2.1 Execution of the new states (to be frozen in §3)

Everything not listed here is T08 §3 / T11 §3 unchanged: decide on the last session of each ISO week (and T0); read the latest D03 Master rows and the latest MAUc1 row dated on or before the decision date; trade on the next session at OHLC4 (GOLDBEES at the de-spiked OHLC4, cash at the LBES level), 10.4 bps a side on every value traded (20.8 bps round trip primary, 0 and 50 as robustness); the initial position at T0 is free; the last decision is made, not traded.

1. **When a trade happens.** A trade is due on the session after decision j iff the target `(e, gw)` differs from decision j-1's (the engines' existing trigger `e[j] != e[j-1] or (e[j] < 1 and gw[j] != gw[j-1])` already does this). So in `-half` and `-liq`, every entry into and exit from the OUT-SELL regime trades; a gold flip while IN still does not trade; in `50-orig` a gold flip never trades.
2. **What a trade does.** As the existing `trade()`: the book's value after cost is split into `e` in the parent's basket in force (listed weights, renormalised as T06/T08), `(1-e)*gw` in GOLDBEES and `(1-e)*(1-gw)` in cash. Entering OUT-SELL from IN in `-half` therefore sells about half of the parent (re-weighted to the basket's listed weights) and buys GOLDBEES with it; entering from OUT-BUY buys the parent half from the sleeve; leaving to IN buys back the parent and sells all GOLDBEES.
3. **No reset inside the regime.** While the regime is unchanged the weights drift and nothing is traded weekly (as T08's sleeve, "changed only when the signal changes").
4. **Parent rebalances while in the `-half` regime ("trap the parent equities with 50% of the weight", Manu).** On a basket's availableDate session while `e = 0.5`, the parent half follows the parent's rebalance: **default (decision point D1): only the stock part is re-weighted to the new basket at its current value; GOLDBEES and cash units are unchanged; the cost is charged on the stock trades and taken from the stock part.** The alternative (D1-b) resets the whole book to 50/50 at each basket change (what the existing `trade()` would do if called unchanged). With `e = 1` (IN) the two are identical, so the IN behaviour and the regression gate are unaffected.
5. **Same-session collisions** (as T08/T11): a basket change on the session of a regime trade is one trade to the new basket; a gold flip and an exit on the same decision is one exit trade straight to the new target.

## 3. Windows, pinned to the original tests' inputs

The two windows are run in one engine with a per-window configuration. **Each window uses exactly the inputs and conventions of the test it extends**, so that `50-orig` and `80-orig` reproduce the stored results of those tests (gate V4(a)), and every variant differs from its original only by the OUT-SELL target.

| | **W1** (T11's window) | **W2** (T08's window) |
|---|---|---|
| Dates | 2014-09-01 -> 2019-01-02 | 2019-01-02 (SCMO_0007: 2019-01-04) -> 2026-10-30 |
| Calendar | D26 NSE sessions (1,070) | D17 dates of the EXTENDED published NAVs, as T08 (E1 of `t08_engine.py`) |
| Parent | rebuilt from baskets (D05, D19) and D18 prices, as T11 | the same rebuild from D18, as T08 (T08 checked it against D17 with G0) |
| Gold signal | D24b `Master_MAUc1.xlsx` | D24 `Master_MAUc1.xlsx` (T08 is pinned to D24; equal to D24b on every shared week) |
| GOLDBEES de-spike range | D24b daily file | `analysis/evidence/final_strategy/mauc1/mauc1_daily_clean.csv` (D12, to 2026-09-28), as T08 |
| Null samplers, bounds and seeds | T11's: bounds from the series, seeds `[14, 3, id]`, `[14, 6, id]`, `[14, 11, 3, id]`, `[14, 11, 6, id]` | T08's: N4.10 bounds [2, 46] in, [2, 40] out (T06's), its gold bounds, seeds `[3, id]`, `[6, id]`, `[11, 3, id]`, `[11, 6, id]` |
| R3 | start 2015-01-02 (T11) | live decisions from 2021-11-01 (T08) |
| R2 | LIQUIDCASE as cash, whole window | LIQUIDCASE from 2024-01-24 (T08's `LIQ_FROM`) |

**Null draws are reused on purpose (decision point D2).** Every T14 realisation is judged against **the same 2,000 draw states per null** that T11 (W1) and T08 (W2) used, regenerated from their seeds (not read from their files) and checked equal to their stored `draw_states.npz`. Reason: the variants are then compared with the original rule on common random numbers, so a change in percentile between `80-orig` and `80-half` is due to the OUT-SELL target alone, not to sampling noise; and the originals' percentiles reproduce T08's and T11's stored ones exactly, which is a regression test of the whole null pipeline. This departs from the project habit of a fresh seed prefix per test; the free prefix **17** is reserved for anything new T14 needs to draw (none is planned).

### 3.1 What the regime looks like (counted 2026-11-23 from the stored `decisions.csv`, one book; the four books share the series)

| | W1 (T11) | W2 (T08) |
|---|---|---|
| weekly decisions | 228 | 410 |
| IN weeks | 93 | 201 |
| OUT-BUY weeks | 81 | 163 |
| **OUT-SELL weeks** | **54** (24% of weeks) | **46** (11% of weeks) |
| OUT-SELL spells (entries into the regime) | 8; lengths 7, 6, 7, 1, 11, 11, 9, 2 | 8; lengths 1, 4, 10, 2, 12, 11, 4, 2 |

Step 1 recomputes these from the signal files and calendars (no price or return) and writes them to `logs/step_1_spell_counts.json`; where they differ from this table, Step 1 wins and the difference is noted in the TRACKER. The effective sample for the change is **8 regime spells per window**: power will be low and every write-up says so.

## 4. What is known before freezing (to be quoted in §2 of `T14.md`)

- **Both windows are seen.** T06, T08, T11 and T13 ran these rules on these weeks; every result in the context table, including the per-book CAGR and drawdown of the original rules, was seen before this request. **The variants were proposed after seeing them**, so T14 is a post-hoc variant on seen data, like T13: any finding is **PROVISIONAL at most**, and a pass is not confirmation. There is no hold-out and no unseen stretch (the stock price table starts 2014-07-01; signals after 2026-10-30 are not approved).
- The counts in §3.1 were read from T08's and T11's stored decision logs before this plan was written.
- **Expectation, declared, no direction claimed.** `-half` raises the equity share in the regime from 0 to 0.5 for 54 (W1) and 46 (W2) weeks, so it will move CAGR and drawdown in the direction of the parent over those weeks; a difference that is only extra exposure is not timing skill, which is why the constant-mix comparator at the variant's own average equity share is shown beside it. `-liq` swaps 50% (base 50/50) or 20% (base 80/20) GOLDBEES for cash in the regime; on the 80/20 base this is a small change and may be undetectable.

## 5. Hypotheses, nulls and criteria

For each window w in {W1, W2} and each **new** rule r in {`50-half`, `50-liq`, `80-half`, `80-liq`}, four statements, judged per book on the after-cost (20.8 bps) percentile against the rule's own null draws (the variant target applied in each draw's own OUT-SELL weeks):

| # | Claim about rule r | Statistic | Deciding null | Real / randomised |
|---|---|---|---|---|
| E1 | the switch's in-or-out timing beats random in-or-out timing that keeps its switch count and weeks invested | CAGR | F1: N4.10 random in-or-out | in-or-out random; gold real |
| E2 | its worst fall is shallower than those random timings' | max drawdown | F1 | as above |
| G1 | applying the regime target in the gold signal's SELL weeks (within the real OUT weeks) beats applying it in random gold weeks that keep the gold signal's switch count and BUY weeks | CAGR | F3: N4.10-g random gold timing | in-or-out real; gold random |
| G2 | worst fall shallower | max drawdown | F3 | as above |

**Pass:** percentile >= 90 in at least 3 of the 4 books. 4 rules x 4 criteria = **16 criteria per window, 32 in all**. Beside, not criteria: F2 (N4.9) next to F1, F4 (N4.9-g) next to F3; F5 (both random) as robustness R5. One null per timing (AGENT.md N2, N4.11). The null tables are T11's (W1) and T08's (W2) with one added row: "target in the OUT-SELL regime: held (the variant's) in the rule and in every draw". The `-orig` rules are not re-judged: their percentiles are T08's/T11's (reproduced exactly) and are shown for reference.

- **Percentile** = (draws worse + 0.5 x ties) / draws x 100, ties within relative 1e-12; **p** = (1 + draws at least as good) / (draws + 1), printed beside it; 2,000 draws per book, cost, rule and null. Secondary statistics as T08/T11 (volatility, Ulcer, days >= 10% under peak, longest under water, Calmar), each with its own percentile.
- **MDE** = 2.8 x the null's SD of CAGR (or drawdown), printed beside every FAIL.
- **Reportability:** a realisation is NOT REPORTABLE if its window has fewer than 4 in-or-out round trips (W1 has 8, W2 9) or fewer than 4 OUT-SELL spells (both have 8), or if a gold table cannot be split within its bounds. If Step 1 finds fewer, stop and ask Manu.
- **Multiplicity (N6.8).** Each criterion is judged at 90, unadjusted, for continuity with T06/T08/T11; Holm-adjusted p (per book, over the 16 criteria of the window) is printed beside each. The four books share one market and the same draws, so "3 of 4" is a consistency check. E1/E2 of the four rules share draws and are not independent; nor are `-half` on the two bases. **Picking the best of the six rules from this table is itself a selection on seen data** and the write-up must say so.

### 5.1 The headline the decision needs (descriptive, no pass mark)

Manu's decision is "what should the book hold in the OUT-SELL regime". That is answered descriptively, per window, book and cost:

- **D-table:** for each new rule, CAGR, max drawdown, Calmar, volatility and the **difference from its own original** (`50-half` - `50-orig`, `50-liq` - `50-orig`, `80-half` - `80-orig`, `80-liq` - `80-orig`), with start and end dates; trades and cost paid; weeks and sessions in each regime.
- **R6 paired contrast (the chance check on the difference):** every F1 and F3 draw is run with the original target and with the variant target (common random numbers); the rule's difference (variant minus original, CAGR and drawdown) is ranked among the draws' differences. A difference that is large but ranks near 50 is exposure, not timing.
- **Regime ledger:** for each of the 8 OUT-SELL spells per window: dates, weeks, what the parent, GOLDBEES and cash returned over the spell, and each rule's return over it, so the reader can see which spells carry the difference.

**Comparators** (benchmarks, not nulls): hold the parent; the two `-orig` rules; the constant mix at each rule's own average parent share with its own average gold share of the rest; 100% sleeve (50/50 and timed).

## 6. Robustness (reported; they set a finding's status, not the verdicts)

- **R1:** all criteria and the D-table at 0 and 50 bps.
- **R2:** E1 and G1 and the D-table with LIQUIDCASE as the cash leg (W1 whole window; W2 from 2024-01-24, as T08). For `-liq` this changes 100% of the regime holding, so it is not vacuous there.
- **R3:** E1, G1 and the D-table on W1 from 2015-01-02 (T11's R3) and on W2's live decisions from 2021-11-01 (T08's R3), each with its own spells, bounds and nulls, as in those tests.
- **R4:** agreement of F1 with F2 and F3 with F4 per book; null median, SD, 5th and 95th percentiles; T06/T08/T11's stored percentiles shown as the reference.
- **R5:** percentile against F5 (both timings random).
- **R6:** the paired contrast of §5.1.
- **R7 (W1 only):** T11's price-quality sensitivity (stock-days with a >= 20% one-day move on held stocks set to zero return; manual-export stocks' contribution), for the four new rules.

## 7. Outcome map (to be frozen)

| Pattern (per window, per base) | Conclusion |
|---|---|
| a variant's D-table difference is positive in >= 3 books **and** its R6 paired percentile >= 90 | the variant improves the rule on this window **because of when** the gold signal places it; PROVISIONAL (seen window, post-hoc) |
| difference positive in >= 3 books, R6 paired percentile < 90 | the improvement is what the variant's holding earned over those weeks, not timing; it would have helped about as much in random weeks |
| difference negative in >= 3 books | the variant makes the rule worse on this window |
| the two windows disagree | report both; no general statement; the 2019-2026 window is the one the live product traded |
| E1/E2 pass for a variant where its `-orig` passed (W2) | the change keeps the switch's equity-timing result |
| E1/E2 fail for a variant where its `-orig` passed (W2) | the change weakens the equity-timing result; say by how much (percentile change on common draws) |
| G1/G2 pass | the gold signal picks the right weeks for this regime holding (new: T08/T11's gold timing failed for the 20/80 sleeve) |
| F1/F2 or F3/F4 disagree | both are reported in the verdict and the status note |
| a V gate fails | nothing is read; fix; new run directory |

## 8. Validity gates (any failure: nothing below may be read)

| # | Gate | Pass condition |
|---|---|---|
| V1 | Independent verifier `analysis/verify_t14.py`, written by a **different agent** from the engine's, from `logs/verifier_spec.md`, never opening `t14_engine.py` (it may read `verify_t11.py` and `verify_t08.py`) | Imports nothing from the engine, `approved_data.py` or any AA analysis module; parses `APPROVED_DATA.md` itself; checks every input is an APPROVED row with matching sha256 and a through-date covering the window. Re-derives from the raw files, per window: the decisions and regimes; the six rules' NAVs at every cost; every regime, sleeve and basket trade (including the D1 basket-change rule inside the `-half` regime); the NAVs of the first 20 and 20 random draws of every null for each new rule. End NAV within relative 1e-9. Checks every draw's structure. Exits 0 only if rows were compared and none failed; a corrupted copy (a regime week flipped, a `-half` basket trade done as a full reset, a `-liq` week with gold > 0, a NAV scaled, a draw out of bounds, a trade removed) must exit non-zero |
| V2 | Point in time | every decision reads Master and MAUc1 rows dated on or before it; every trade is on a later session; counted; violations 0 out of a count > 0 |
| V3 | Nulls hold their tables | as T08 (W2) and T11 (W1); plus: **every draw state array equals the stored `draw_states.npz` of T08 (W2) and T11 (W1)** |
| V4 | Regression and identities | (a) W2: `80-orig` reproduces T08's stored `daily_nav.csv` (every book, cost, series) and `50-orig` reproduces T06's stored `daily_nav.csv` to 2026-10-22, both to relative 1e-12; the `-orig` rows of `draws.csv` equal T08's stored draw statistics; (b) W1: `50-orig` and `80-orig` reproduce T11's stored `daily_nav.csv` (Part A, Part B) and `draws.csv` to 1e-12; (c) one-instrument always-in identity; (d) automated diff of shared functions against `t11_engine.py` (and, for the W2 code paths, `t08_engine.py`) lists only the expected changes; (e) the signals equal the SIGN columns of D03, D24 (W2) and D24b (W1) at every decision; (f) W1 seam check as T11 V4(f) |
| V5 | Samplers exact | as T11 V5 (the same samplers; reused draws make it a formality, it is kept) |
| V6 | Trade and cost identities | as T11 V6, plus: after every entry into OUT-SELL in `-half`, stock value = 0.5 and GOLDBEES = 0.5 of the value after cost, cash 0, to 1e-12 of NAV; at a basket change inside the `-half` regime GOLDBEES and cash units are unchanged and stock value after = stock value before - cost (D1 default); in `-liq` GOLDBEES units are 0 throughout the regime; one entry into and one exit from the regime and one in-regime basket change worked by hand in §4.0a |

Oracle, negative-control and planted-effect controls (N6.7) are **not run**; listed in §6 of `T14.md` as untested (as T08/T11).

## 9. Data (APPROVED rows of `data/APPROVED_DATA.md` only; the engine asserts it)

Run `python data/check_approved_data.py` first and at the top of `run.sh`; a non-zero exit means stop and ask Manu. Do not extend, rebuild or re-fetch anything.

| Role | W1 | W2 |
|---|---|---|
| Stock OHLC (D18) + Polyplex correction (F-AA-D14) | `data/holdings_matrix/SCMO_<p>_ohlc.csv`, `price_corrections.csv` | same |
| Basket weights (D19), skips and dates (D05) | `*_holding_weight_matrix.csv`, `_columns.csv`, `_holding_weight_sources.csv`; `Historical Data/frozen_2026-09-25/Rebalance_history/` | same |
| Calendar | D26 `Historical Data/extended_2026-11-12/index_daily_pre2019/nse_trading_days.csv` | D17 extended `Historical Data/extended_2026-11-06/published_nav/SCMO_<p>.csv` (dates; and G0 as T08) |
| Three-index signals (D03) | `Historical Data/extended_2026-10-30/Master/Master_{Nifty100,MC100,SC100}.xlsx` | same |
| MAUc1 signal | D24b `Historical Data/extended_2026-11-12/MAUc1_from_2003/Master_MAUc1.xlsx` (+ weekly csv) | D24 `Historical Data/extended_2026-11-06/MAUc1/Master_MAUc1.xlsx` (+ weekly csv) |
| GOLDBEES (D09) and de-spike range | `analysis/cache/why_gold_ohlc_eikon_extended_2026-11-04.parquet`; range D24b daily file | same parquet; range D12 `analysis/evidence/final_strategy/mauc1/mauc1_daily_clean.csv` |
| Cash (D11) / R2 | `Historical Data/LBES_Adjusted_Price_data_extended_2026-11-05.csv` / `liquidEtfFinal_extended_2026-11-05.csv` | same |

**Test evidence read by gates only (not data):** `tests/T06/evidence/headline/daily_nav.csv`, `tests/T08/evidence/headline/{daily_nav.csv, decisions.csv, draws.csv, draw_states.npz}`, `tests/T11/evidence/headline/{daily_nav.csv, decisions.csv, draws.csv, draw_states.npz}`.
Not read: D25, D09b, D03b, D20-D23 tags, D15 AA books, any PENDING or SUPERSEDED row.
Known contaminants are T08's (W2) and T11's (W1) §3 lists, copied into `T14.md` §3: the 2014-2018 parent NAV is a rebuild with no published series to check it (W1); nine manual Eikon exports of unrecorded provenance are held in W1; price returns only (dividends not credited); the cash file's source before 2026-08-10 is unrecorded (F-AA-D09); GOLDBEES fills after 2026-09-28 use the raw OHLC4 (no D12 range) in W2, as T08.

## 10. What the engine changes (`analysis/t14_engine.py`, a fork of `t11_engine.py`; copy, do not import, from T08/T11)

1. **Per-window configuration** `WINDOWS = {"w1": ..., "w2": ...}` holding the rows of §3's table (calendar, T0, END, gold signal file, range file, sampler bounds rule and constants, seeds, R2 switch date, R3 start). T11's `--calendar d17` path is the start of W2's; port what T08 has that T11 dropped (D17 calendar to END, `LIVE_START`, `LIQ_FROM`, G0 gate, typed T06 bounds, T08 seeds). `--window w1|w2|both`.
2. **Rules.** `RULES = {"50-orig", "50-half", "50-liq", "80-orig", "80-half", "80-liq"}`; one function `targets(rule, s, g) -> (e, gw)` per decision from §2's table, used for the real series and every draw.
3. **Basket change inside the `-half` regime** (§2.1 item 4, D1): a partial basket trade that re-weights the stock part only; with `e = 1` it must give the same numbers as the existing path (V4 checks).
4. **Trade kinds** in `trades.csv`: add `regime_in` (into OUT-SELL) and `regime_out` (out of it) beside `switch_in`, `switch_out`, `sleeve_rebalance`, `basket_change`.
5. **Nulls**: the T11 (W1) and T08 (W2) samplers and seeds unchanged; each draw runs all six rules (the `-orig` rows are the regression); F1-F5; R6 pairs.
6. **Outputs** as T11 (`decisions.csv` with a `regime` and per-rule `(e, gw)` columns, `trades.csv`, `daily_nav.csv`, `draws.csv`, `stats.csv`, `draw_states.npz`, `audit.json`, `inputs.csv`, `regression.json`) per window under `evidence/<run>/<window>/`, plus `regime_ledger.csv` (§5.1).
7. **Run time** is not yet known: T11 (2 rules) took about 10 minutes and T08 425 s; T14 runs six rules on two windows. Step 2 measures it on a 100-draw run and records it in the TRACKER. **Any `.npz` or `.csv` over 100 MB goes in `.gitignore` with a one-line reason** (as T06-T08's `draw_curves_20.8.npz`).

## 11. Steps (same hand-off rules as T11/T13; tracker `tests/T14/TRACKER.md`)

Read `TRACKER.md` before starting any step; update it when you finish; write a `logs/step_<n>_log.md` per step; flag anything that changes a later step as **AFFECTS STEP n**. Commit at every milestone named in `AA/CLAUDE.md` (subject `T14: <outcome>`, explicit paths, never `git add -A`); push only when Manu asks.

0. **Plan and tracker.** This file, written directly to `tests/T14/PLAN.md` (no plan-mode file exists to copy), and `TRACKER.md`. **Wait for Manu's approval of this plan and his answers to the decision points in §13 before Step 1.**
1. **Pre-registration.** `spell_counts.py` (fork of T11's, both windows; signals, calendars and basket dates only, no price or return) -> `logs/step_1_spell_counts.json` (§3.1's counts, regime spells, trades each rule makes, reportability). `T14.md` §1-§3 from T11.md's layout: §1 idea and references; §2 hypotheses, the null tables with the added row, the 32 criteria, gates, outcome map, disclosures (§4 above); §3 data, construction, the plain-words walkthrough (AGENT.md task 5 and rule 10) with the places for real numbers marked. `check_prereg.py --freeze`; sha256 in the header. **Commit** ("T14: pre-registration frozen ...").
2. **Engine** `analysis/t14_engine.py` (§10). Smoke run `--run smoke --draws 20 --quick` exits 0 with V2-V6 passing, **V4(a)/(b) exact** for both windows. Record the change list in `logs/step_2_log.md` and the evidence contract in `logs/evidence_contract.md`. Commit.
3. **Independent verifier** `analysis/verify_t14.py` (separate agent; spec `logs/verifier_spec.md` written in Step 2 from §8 V1). Must pass the smoke run and detect every planted corruption. Commit.
4. **Test scripts** forked from `tests/T11/` and `tests/T13/`: `analyse.py` (reads only evidence; prints every table; exits 1 on any failed gate), `fill_writeup.py` (must leave §1-§3 byte-identical, F-AA-M02), `report.py`, `check_page.py`, `rerun_draw.py`, `run.sh` (runs `check_approved_data.py`, the engine for both windows, the verifier, analyse, fill_writeup, report, check_page). Steps 2-4 may run in parallel after Step 1. Commit.
5. **Run** `bash tests/T14/run.sh` -> `evidence/headline/{w1,w2}/`. Any gate failure: read nothing, fix, new run directory. Commit.
6. **Results and close.** `T14.md` §4 (generated) and §5-§8; `evidence/METHODS.md`; `evidence/report.html` (AGENT.md R10: the answer first; the D-table and the regime ledger; one backtest end to end with a worked regime entry, a regime exit and an in-regime basket change; per-book curves of all six rules; null histograms; R6 paired contrasts; robustness; power; a start and end date on every number and curve). Finding IDs are **pending** (taken from the `AA/CLAUDE.md` counter after T07-T13); update the "Latest completed test" bullet in `AA/CLAUDE.md`. Commit.

## 12. Key edge cases

1. Any input stale, `PENDING` or with a changed sha256: stop and ask Manu.
2. W2 starts OUT (2019-01-02: all three SELL, MAUc1 BUY), so all rules start in the OUT-BUY sleeve; W1 starts IN. SCMO_0007's W2 starts 2019-01-04.
3. A 1-week OUT-SELL spell (one in each window) means a regime entry and exit one week apart: two trades, both costed.
4. A gold flip on an exit or entry decision: one trade straight to the new target.
5. A basket change on the session of a regime trade: one trade to the new basket at the new target.
6. 2017-10-19 (W1) has no D18 bars: T11's last-close stand-in, counted. GOLDBEES sessions without a bar or range: T08/T11's rules, counted.
7. In `-liq`, a regime week where LBES has no row: the cash convention F-AA-D05 (as-of level).
8. `50-orig` never trades on a gold flip; its decision log still records the gold signal.

## 13. Decision points for Manu (defaults in bold; each changes the engine, so settle before Step 1)

- **D1. Parent rebalance inside the `-half` regime:** **(a) re-weight only the parent half at its current value; gold untouched** / (b) reset the whole book to 50/50 parent/gold at every parent rebalance.
- **D2. Null draws:** **reuse T11's (W1) and T08's (W2) draws, so variants and originals are compared on the same draws** / draw fresh with seed prefix 17.
- **D3. One test or two:** **one test, T14, with both windows as parts** / T14 for W2 (2019-2026) and T15 for W1 (2014-2019), each frozen separately.
- **D4. What decides:** **E1/E2/G1/G2 per new rule as criteria, the difference from the original and its R6 paired percentile as the descriptive headline** / make the R6 paired percentile (variant minus original, ranked among the draws' differences) the deciding criterion instead.

## 14. Files to create (all under `AA/`)

| File | Step |
|---|---|
| `tests/T14/PLAN.md` (this file), `TRACKER.md` | 0 |
| `tests/T14/T14.md`, `check_prereg.py`, `spell_counts.py`, `logs/step_1_spell_counts.json` | 1 |
| `analysis/t14_engine.py`, `tests/T14/logs/{step_2_log.md, evidence_contract.md, verifier_spec.md}` | 2 |
| `analysis/verify_t14.py`, `tests/T14/logs/step_3_log.md` | 3 |
| `tests/T14/{analyse,fill_writeup,report,check_page,rerun_draw}.py`, `run.sh`, `logs/step_4_log.md` | 4 |
| `tests/T14/evidence/headline/{w1,w2}/`, `analysis.log`, `evidence/report.html`, `evidence/METHODS.md` | 5-6 |
| `CLAUDE.md` (edit: test-in-progress line, then the completed-test line) | 1, 6 |

Reused without change: `analysis/approved_data.py`; the sampler and simulation functions of `t11_engine.py` and `t08_engine.py` (copied, not imported).

## 15. Verification (end to end)

1. `python data/check_approved_data.py` exits 0; `inputs.csv` lists every file read with its sha256 and approved row.
2. `python tests/T14/check_prereg.py` confirms §1-§3 unchanged; `spell_counts.py` output equals the engine's counts.
3. V4: `50-orig`/`80-orig` reproduce T06, T08 and T11's stored NAVs and draw statistics to 1e-12, and every draw state equals the stored `draw_states.npz`.
4. Smoke run, then the verifier on it (exit 0, every corruption detected), then `bash tests/T14/run.sh`; `analyse.py` exits 1 on any failed gate; `check_page.py` reports its checks and 0 failures.
5. The D-table differences for the `-orig` rules are exactly 0; a `-half` rule's equity share is 0.5 right after every regime entry; a `-liq` rule holds no GOLDBEES in any regime week.
