# T09 Plan: the T06 and T08 rules on a three-index proxy portfolio, 2011-11-18 -> 2019-01-02 (before the parents' holdings exist)

**Written 2026-11-12. Nothing in this plan has been run and no file outside the plan has been written** (the data candidates D03b and the checks that led here are logged in `data/APPROVED_DATA.md`). On approval the frozen design becomes `T09.md` §1-§3 (Step 1), which wins over this plan where they differ. **Status: APPROVED by Manu 2026-11-12.** The decision points at the end were settled the same day: window start 2011-11-18, R8 skipped, plan approved as written (R8 stays described below, marked skipped). This file is kept as written; a revision goes beside it as `PLAN_v2.md`.

## Context

T06 (fixed 50/50 sleeve, 2019-01-02 -> 2026-10-22, F-AA-S07) and T08 (the same switch with the sleeve timed by the weekly MAUc1 gold supertrend, 80/20 or 20/80, 2019-01-02 -> 2026-10-30) both run on the four real parents' stocks, so they cannot start before the parents' baskets (2019). Manu wants the same two rules tested on the years before that, where there are no holdings, using a **proxy portfolio built from the raw indices**: Nifty 100 (Large), Midcap 100 (Mid) and Smallcap 100 (Small and below), held at each book's own average band mix. This is a new test (**T09**); T06 and T08 stay as they are. The question is whether the rule's timing, with no stock selection in it at all, beats random timing on an earlier, partly unseen stretch.

## Decisions taken (Manu, 2026-11-12)

1. **Proxy weights are each book's own mix**, e.g. SCMO_0003 = 9.6% Large / 19.7% Mid / 70.7% Small and below. Source: the full-window "mean band share, all weeks" of `tests/T07/logs/step_1_counts.json` (written by T07's `step1_counts.py` from D18-D23, sha256 recorded here at Step 1); the 12 numbers are typed into T09.md §3 as constants, so the engine never reads that file. Renormalised to sum to 1:

   | Book | Large (Nifty 100) | Mid (Midcap 100) | Small and below (Smallcap 100) |
   |---|---|---|---|
   | SCMO_0003 | 0.09626177 | 0.19679459 | 0.70694364 |
   | SCMO_0007 | 0.04799800 | 0.17801859 | 0.77398341 |
   | SCMO_0010 | 0.26590767 | 0.21230665 | 0.52178568 |
   | SCMO_0029 | 0.31294405 | 0.28378774 | 0.40326821 |
2. **Proxy trading:** the proxy is valued and traded from the indices' prices. Entry sets the three index positions to the book's weights; while IN, the positions are **reset to the weights at the first session of each calendar quarter** (the sessions after Mar, Jun, Sep, Dec); between resets weights drift; no reset while OUT. Fills at the next session's OHLC4 of each index, cost ow = 10.4 bps per side (20.8 round trip primary; 0 and 50 as robustness) on every value traded, as T06/T08. Indices are price indices (no dividends), as the parents are.
3. **Window: 2011-11-18 -> 2019-01-02** (default, decision point 1 below). Smallcap 100 prices have no real open/high/low before 2011-10-03 (standing rule 7); the Smallcap 100 supertrend recomputed from real bars only (D03b, a candidate) agrees with D03 on SIGN in every week from 2011-11-18 and on every column from 2011-11-25 (on 2011-11-18 only the ST and FLB values differ, and the decision reads SIGN only), so 2011-11-18 is the first week whose decision does not depend on the flat-bar history. The end is the first date of the real parents' NAVs (T06's T0). Counts (signals only, no price read): **372 weekly decisions, first state OUT, 12 round trips, 172 weeks IN / 200 OUT; MAUc1 flips 28, of which 11 are sleeve trades (OUT both sides), 14 while IN, 2 on an exit decision; gold BUY in 112 of the 200 OUT weeks.**
4. **Both rules, as T06 and T08.** Part A = T06's rule (fixed 50/50 sleeve); Part B = T08's rule (sleeve 80/20 GOLDBEES/cash when MAUc1 is BUY, 20/80 when SELL, changed only when the signal changes). One engine, `fixed50` as a mode, as T08.
5. **Gold before GOLDBEES.** GOLDBEES (D09) starts 2014-07-01; before that the sleeve's gold leg is the MAUc1 proxy **D09b** (2005-05-10 -> 2014-06-30, MAUc1 returns chained back from GOLDBEES's first close, Manu's formula), spliced at 2014-07-01 with MAUc1's own return on that day. The proxy tracks real GOLDBEES loosely (2014-2026: weekly return correlation 0.82, daily 0.51 because MCX trades after the NSE close, CAGR 1.3 pp/yr higher, equal volatility), so the first 2.6 years of the window carry a noisier gold leg. Disclosed, and measured by robustness R7.
6. **Smallcap 100 rule 7** is enforced in code: the engine and verifier call `approved_data.guard_window(path, first_read_date)` on every Smallcap 100 file (D25 and D03) with the earliest date they read (the window start, plus the one-week stale-row lookback).

## The T09 rule (to be frozen in §3)

- **Decision weekly**, last D26 (NSE calendar) session of each ISO week after T0; T0 = 2011-11-18 is the window's base and has a decision. State `s_t` = IN iff the latest Master rows dated on or before the decision date of Nifty 100, Midcap 100 and Smallcap 100 (D03; the Smallcap 100 rows read are dated 2011-11-18 or later) are all BUY; the one-week-stale rule as T06 step 3. Gold signal `g_t` = SIGN of the latest `Master_MAUc1` row (D24b) on or before the decision date.
- **Targets.** IN: the proxy at the book's weights. OUT, Part A: 50% GOLDBEES + 50% cash. OUT, Part B: 80% / 20% when g is BUY, 20% / 80% when g is SELL.
- **Trades** (next D26 session after the decision, OHLC4, 10.4 bps a side on every value traded, cash included): exit (sell the three index positions, buy the sleeve at g's split of the proceeds after cost), entry (sell the sleeve, buy the three index positions at the weights), sleeve rebalance (Part B only, g flips while OUT, trade GOLDBEES and cash to the new split), quarterly reset (IN only, three index positions back to the weights). g flips while IN: no trade. The initial position at T0 is free. The last decision (2019-01-02) is made, not traded.
- **GOLDBEES fill** on a session: D09b's OHLC4 before 2014-07-01 (the proxy is MAUc1 itself, so nothing to de-spike); from 2014-07-01 T03's de-spike (OHLC4 of open/high/low clipped to MCX gold's range that day plus 0.5% tolerance), the MCX range read from D24b's daily file (it holds D12's rows verbatim from 2015-02-02 and adds 2003-2015, which D12 lacks). Engine reading to record: sessions 2014-07-01 -> 2015-01-30 have no D12 range.

**What is known before freezing (§2 will quote it):** the rule was chosen after seeing 2014-2026 results (`final_strategy`, T03, T06, T08), so **2011-11-18 -> 2014-06-30 (about 2.6 years) predates that look**, and 2014-07 -> 2019-01 is seen. The three-index signal for 2011-2019 is a production backfill. T08's own window (2019+) is not part of T09 and its results are not tuned on here. Spell counts above were computed from the signal files only; no price, NAV or return was read.

## Hypotheses, nulls and criteria

Six statements, each judged per book on the after-cost (20.8 bps) percentile, pass mark 90, at least 3 of 4 books.

| # | Claim | Statistic | Null that decides | Real / randomised |
|---|---|---|---|---|
| A1 (T06's H1) | the switch's exits earn more than random in/out timing, with the **fixed 50/50** sleeve | CAGR | F1: N4.10 in/out, run with the 50/50 sleeve | in/out random |
| A2 (T06's H2) | worst fall shallower | max drawdown | F1 (50/50) | as above |
| C1 (T08's H1) | same, with the **MAUc1-timed** sleeve in place | CAGR | F1 (timed sleeve, real MAUc1 in every draw) | in/out random, gold real |
| C2 | worst fall shallower | max drawdown | F1 (timed) | as above |
| C3 (gold timing) | the MAUc1 timing of the sleeve beats random gold timing | CAGR | F3: N4.10-g free-length gold | in/out real, gold random |
| C4 | worst fall shallower | max drawdown | F3 | as above |

Beside, not criteria: F2 (N4.9 spell shuffle) beside F1 for A1/A2/C1/C2; F4 (N4.9-g) beside F3. Robustness only: F5 (both random). One null per timing, as T08 (AGENT.md N2).

**Bounds (new, computed from the actual series before any return was read).** For every state of every series, `lo = min(2, shortest actual spell)`, `hi = longest actual spell`. This differs from T06/T08's in/out constants ([2, 46], [2, 40]) which were set after seeing T03's draw 445 and would exclude this window's 1-week in-spell; the rule's own spells lie inside by construction (V3 checks it). Step 1 prints k, S, lo, hi and the exact tuple counts per table; all tables must satisfy lo*k <= S <= hi*k.

**Seeds.** First element 12, which no earlier test uses (T03-T08 use 3-11; Step 1 re-checks): N4.9 `[12, 3, id]`, N4.10 `[12, 6, id]`, N4.9-g `[12, 11, 3, id]`, N4.10-g `[12, 11, 6, id]`; same sampler code as T06/T08 (exact DP, `rng.random()` plus cumulative-sum search, never `Generator.choice`). 2,000 draws per book, cost and null. The same draw ids serve every cost and the four books (their in/out series are identical here, so the four books share draws).

**Percentile, p-value, pass mark, secondary statistics, MDE, reportability** exactly as T08 (percentile = (worse + 0.5 ties)/draws; p = (1 + at least as good)/(draws + 1); pass at 90; MDE = 2.8 x null SD printed beside every FAIL; a realisation with fewer than 4 equity round trips, or a gold table that cannot be split within its bounds, is NOT REPORTABLE). Effective sample: **12 equity round trips and 11 sleeve trades**, shared by the four books ("3 of 4" is a consistency check; the proxies differ only in their band weights).

**Multiplicity (N6.8).** Family of m = 6 (A1, A2, C1, C2, C3, C4), each judged at 90 **unadjusted** for continuity with T06 and T08, Holm-adjusted p beside each; one rule per part, no grid; five nulls. T09 cannot upgrade F-AA-S04/S07; any finding is PROVISIONAL (the later part of the window is seen and the 2011-2014 part is one short stretch). Part A and Part B C1/C2 share the same draws' in/out states, so they are not independent.

**Expectation, declared before any run:** no basis for a direction. T06's and T08's edges were +9 to +14 pp CAGR but below their minimum detectable edge; a proxy with no stock selection removes any selection component, so the result isolates timing. 2011-2013 was a weak, trendless market for Indian small caps and a falling gold market from 2013, which could lower the edge of a trend rule. The pass mark stays 90.

**Robustness (reported; they decide a finding's status, not the verdicts):**
- **R1:** all criteria at 0 and 50 bps.
- **R2:** C1, C3, A1 with LIQUIDCASE cash.
- **R3:** start 2012-01-02 instead of 2011-11-18 (SC100 buffer; own spells, totals, bounds, 2,000 draws).
- **R4:** agreement of the two nulls per timing; T06's and T08's percentiles shown as a historical reference (different window and holdings). No pass mark.
- **R5:** F5 (both random).
- **R6:** paired contrast: every F1/F2 draw is also run with the 50/50 sleeve; the rule's change in CAGR and drawdown from 50/50 to timed, and its percentile among the draws' changes. Descriptive.
- **R7 (gold proxy sensitivity):** rerun the rule with the GOLDBEES leg in the proxy period replaced by the plain MAUc1-scaled close (fills at the close instead of OHLC4) and, separately, with the sleeve's gold weight held at the 50/50 mix over the proxy period; report the change. Descriptive.
- **R8 (proxy validation): SKIPPED by Manu 2026-11-12 (not run, not registered, no extra data).** It would have been: the same engine run on 2019-01-02 -> 2026-10-30 with the 0-cost always-in proxy against each parent's published NAV (D17): CAGR gap, daily-return correlation, maximum drawdown, tracking by calendar year. Says how close the proxy is to the real books; no pass mark.

**Comparators (benchmarks, not nulls):** hold the proxy (always IN, 0 cost and each cost); the rule with the 50/50 sleeve (Part A's rule); the constant mix at the rule's average proxy share with 50/50 and MAUc1-timed non-stock shares; the 100% sleeve 50/50 and MAUc1-timed; each single index held (Nifty 100, Midcap 100, Smallcap 100) as a reference.

**Outcome map:** as T08's (both timings pass; equity passes and gold fails; equity fails and gold passes; all fail; F1/F2 or F3/F4 disagree: both reported; a V gate fails: nothing is read). Part A alone is T06's question on the earlier window.

## Data (all `APPROVED` rows of `data/APPROVED_DATA.md`; the engine asserts it and calls `guard_window`)

| Role | File | Through |
|---|---|---|
| Index daily OHLCV (D25) | `Historical Data/extended_2026-11-12/index_daily_pre2019/{Nifty100,MC100,SC100}_daily_ohlcv.csv` (SC100 read from 2011-10-03 only) | 2019-01-04 |
| NSE calendar (D26) | `.../nse_trading_days.csv` | 2019-01-04 |
| Three-index signals (D03) | `Historical Data/extended_2026-10-30/Master/Master_{Nifty100,MC100,SC100}.xlsx` (SC100 rows from 2011-11-18) | 2026-10-30 |
| MAUc1 signal and daily range (D24b) | `Historical Data/extended_2026-11-12/MAUc1_from_2003/Master_MAUc1.xlsx`, `mauc1_daily_clean_extended.csv` | 2026-11-06 |
| Gold proxy (D09b) and GOLDBEES (D09) | `analysis/cache/why_gold_ohlc_proxy_mauc1_2005-05-10_2014-06-30.parquet`, `why_gold_ohlc_eikon_extended_2026-11-04.parquet` | 2014-06-30 / 2026-11-04 |
| Cash (D11) | `Historical Data/LBES_Adjusted_Price_data_extended_2026-11-05.csv`, `liquidEtfFinal_extended_2026-11-05.csv` | 2026-11-05 |

Not read: stock prices, baskets, holdings (D18, D19, D05), published NAVs (except R8), D03b (candidate; not needed if D03's SC100 restriction moves to 2011-11-18).

## What the engine changes (fork `t08_engine.py`, 1,275 lines, into `t09_engine.py`; no imports from T08)

1. **Portfolio.** Replace the stock basket (`raw_parent`, baskets, `price_corrections`, rebalance history) by three index instruments with fixed weights per book; units per index, quarterly reset events, entry/exit trading three instruments. Costs and fills unchanged.
2. **Calendar and window.** Calendar from D26; T0 = 2011-11-18, END = 2019-01-02; assert every file reaches END (D25 reaches 2019-01-04).
3. **Gold chain.** `gclose` and `gfill` from D09b then D09 (chained at 2014-07-01); de-spike range from D24b's daily file; `gold_raw` sessions only if D24b were missing a date (assert none).
4. **Signals.** D03 Master rows (SC100 guarded), D24b Master (as T08's `gold_master`).
5. **Nulls.** T08's samplers, generalised so bounds come from the series (`lo = min(2, shortest)`, `hi = longest`), seeds with first element 12; F1-F5 loop and the 50/50 pairs as T08; the four books share draws.
6. **Comparators** per the list above (hold-the-proxy replaces hold-the-parent; no published NAV, except R8).
7. **Outputs** as T08, plus `proxy_units.csv` (positions per index and date), `quarterly_resets.csv`, `regression.json` (V4).

## Gates (V1-V6 as T08, V4 changed; any failure means nothing below is read)

- **V1** independent check `verify_t09.py`: imports nothing from the engine; written from `logs/verifier_spec.md` by an agent that does not read `t09_engine.py`; re-derives decisions (index and gold), the always-in 0-cost proxy NAV, the strategy NAV at every cost, every sleeve trade and reset, and the NAVs of a sample of draws of every null (first 20 plus 20 random per book and null) to relative 1e-9; checks every draw's structure; recomputes the tuple counts by inclusion-exclusion; corrupted copy (a decision flipped, a gold week flipped, a NAV scaled, a draw's lengths out of bounds, a reset removed) must exit non-zero. It calls `guard_window` on the Smallcap 100 files.
- **V2** point in time: every decision reads Master rows dated on or before the decision date; every trade is on a later session; no Smallcap 100 row before 2011-10-03 (or before the window start) is read; counted.
- **V3** the nulls hold their tables (as T08, with the new bounds).
- **V4 identities and regression (changed).** (a) The engine on a one-index book at weight 1, 0 cost, always in, reproduces that index's close/close_0 to 1e-12; (b) hold-the-proxy at 0 cost equals the hand-built weighted NAV with quarterly resets (verifier); (c) every code path the sleeve shares with T08 is unchanged: an automated diff of the sleeve functions against `t08_engine.py` lists only expected changes; (d) the signals equal the SIGN columns of D03/D24b at every decision date (verifier); (e) D09b chained into D09 has no gap in the return series (splice-day return equals MAUc1's).
- **V5** samplers exact (as T08).
- **V6** sleeve identity (as T08) plus a quarterly-reset identity: post-reset index values equal weights x NAV after cost to 1e-12; one exit, one gold flip and one reset worked by hand in §4.0a.
- **Reportability** as above.

## Steps (T08's six, same handoff rules; tracker `tests/T09/TRACKER.md`, step logs, "AFFECTS STEP n" warnings)

1. **Pre-registration** (`T09.md` §1-§3, `check_prereg.py`, `spell_counts.py` forked from T08's; hash frozen with `--freeze`). Before writing: `check_approved_data.py` exits 0; counts only, no price: spells and bounds for the in/out and gold series on the window and R3's, feasibility, sleeve-trade count, seed check, the 12 weights with the T07 file's sha256, the quoted look of earlier studies at the 80/20 sleeve, the 2011-10-03 -> 2011-11-18 buffer rationale.
2. **Engine** (`analysis/t09_engine.py`, uses `approved_data.require` and `guard_window`). Smoke run `--run smoke --draws 20 --quick` exits 0 with V2-V6 passing.
3. **Independent verifier** (`analysis/verify_t09.py`, a different agent from Step 2, never reads the engine).
4. **Test scripts** forked from `tests/T08/` (`analyse.py`, `fill_writeup.py`, `report.py`, `check_page.py`, `rerun_draw.py`, `run.sh`); every "parent"/"50/50 only" caption changed; `check_page.py` re-derives every number.
5. **Run** `bash tests/T09/run.sh`. Expected size about T08's: roughly 5-10 minutes (smaller window, three instruments instead of about 60 stocks).
6. **Results and close:** `T09.md` §4-§8; finding IDs from the `AA/CLAUDE.md` counter at closing; `AGENT.md` and `AA/CLAUDE.md` updated; `METHODS.md`.

## Charts and page: as T08

Answer; data (with the Smallcap 100 and gold-proxy caveats up front); one backtest end to end (inputs -> signal -> trade in three indices -> units -> daily value -> curve -> statistics -> one null draw -> ranking), including a worked exit, a gold flip and a quarterly reset; headline for A and B; per-book curves; null histograms for both timings with their companion nulls; the best draw against the rule; paired contrast; proxy validation (R8 if approved); robustness; power; definitions. Every chart hoverable, a start and end date on every number and curve.

## Key edge cases

1. Stop and ask Manu if any input is stale, `PENDING`, or its sha256 differs; do not extend or rebuild data.
2. Smallcap 100: never a row before 2011-10-03; a one-week lookback for the stale-row rule must not read before the window start.
3. A reset session that coincides with an exit or entry: one trade (the exit or entry), no extra reset.
4. D26 omits Saturday special sessions that the index files contain (7 in 2007-2019); the calendar is D26's. SC100 is missing 2011-05-13 (before the window).
5. Gold flip and exit on the same decision: one exit trade at the new split.
6. The one flat Smallcap 100 bar on 2015-11-11 and the 2015-08-20 bar with a close outside high/low are read as they are, disclosed.
7. `fill_writeup.py` must not touch §1-§3 (F-AA-M02).

## Decision points (settled 2026-11-12)

1. **Window start: 2011-11-18** (chosen over 2011-10-03).
2. **D03b stays PENDING and is not used;** D03's Smallcap 100 restriction moved from 2011-10-03 to 2011-11-18 (APPROVED_DATA.md, CLAUDE.md, rule 7 text); D25's Smallcap 100 prices stay usable from 2011-10-03 (they are real) but T09 reads them only from the window start.
3. **R8 proxy validation: skipped.** T09 has no direct check of the proxy against the real parents; the page says so.

## Files to create (all under `AA/` unless stated)

| File | Step |
|---|---|
| `tests/T09/PLAN.md` (this file), `T09.md`, `check_prereg.py`, `spell_counts.py`, `TRACKER.md`, `logs/` | 1 |
| `analysis/t09_engine.py` | 2 |
| `analysis/verify_t09.py`, `tests/T09/logs/verifier_spec.md` | 3 |
| `tests/T09/{analyse,fill_writeup,report,check_page,rerun_draw}.py`, `run.sh` | 4 |
| `tests/T09/evidence/headline/`, `analysis.log`, `evidence/report.html`, `METHODS.md` | 5-6 |
| `../AGENT.md`, `CLAUDE.md` (edits) | 6 |

Reused without change: `analysis/approved_data.py`, the sampler functions of `t08_engine.py` (copied, not imported), `data/build_gold_proxy.py` and `data/rebuild_sc100_signal.py` (already run; D09b approved, D03b pending).
