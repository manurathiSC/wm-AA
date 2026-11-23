# T11 Plan: the T06 and T08 rules on the four real parents, 2014-09-01 -> 2019-01-02 (before the published NAVs)

**Written 2026-11-17. Nothing in this plan has been run and no file outside the plan has been written** (the database check and the data-coverage review that led here were read-only). On approval the frozen design becomes `T11.md` §1-§3 (Step 1), which wins over this plan where they differ. This file is kept as written once approved; a revision goes beside it as `PLAN_v2.md`. **Status: DRAFT, awaiting Manu's approval.**

## Context

T06 (fixed 50/50 sleeve, 2019-01-02 -> 2026-10-22, F-AA-S07) and T08 (the same switch with the sleeve timed by the weekly MAUc1 gold supertrend, 2019-01-02 -> 2026-10-30) run on the four real parents (SCMO_0003, 0007, 0010, 0029). T09 ran both rules on a three-index proxy for 2011-11-25 -> 2019-01-02 because it believed no holdings exist before 2019. That premise is wrong: the parents' baskets exist from 2014-03 (D05, D19), the approved stock prices (D18) and GOLDBEES (D09) from 2014-07-01 (the Eikon table `ohlcv_eikon` itself starts that day; checked read-only 2026-11-17 on the whole table, UPL, Aarti Drugs and Emami, no rows earlier). T11 is a **new test (T11)**: the same two rules on the real parents' own stocks over the years before 2019, so the result can be set beside T09 (proxy, 2011-19) and T06/T08 (real, 2019-26). T06, T08 and T09 keep their numbers.

## Decisions taken (Manu, chat 2026-11-17)

1. **T0 = 2014-09-01**: the first basket effective on or after 2014-07-01 (decision 2014-08-31, availableDate 2014-09-01, the same for all four parents). Every starting weight is the listed one. The basket in force on 2014-07-01 (effective 2014-06-02) is **not** used: D18 has no price before 2014-07-01, so its drift from 06-02 cannot be valued.
2. **Window end = 2019-01-02**, the first date of the published NAVs (T06/T08's T0), so T11 and T06/T08 do not overlap.
3. **Validation:** nothing validates a rebuild of the parents before 2019. The plan discloses that, adds the seam checks below (V4) and **writes the rebuilt NAV out** (see "NAV output").
4. **Both rules, as T09.** Part A = T06's rule (fixed 50/50 sleeve); Part B = T08's rule (sleeve 80/20 GOLDBEES/cash when MAUc1 is BUY, 20/80 when SELL, changed only when the signal changes). One engine, `fixed50` as a mode.
5. **Out of scope:** T07 and T10 (they need market-cap tags; D20-D23 start 2018-01-01), any data pull, any edit of approved data, any proxy file (GOLDBEES starts the same day as the stock prices, so D09b is not needed).

## The T11 rule (to be frozen in §3; = T08 §3 on this window)

- **Calendar.** D26 `nse_trading_days.csv` (1,111 sessions 2014-07-01 -> 2019-01-02; D18 has 1,110: 2017-10-19, the Muhurat evening, is in D26 and has no D18 bars). T08's last-close stand-in (E6) covers that session; it is counted and disclosed. Sessions from T0 = 2014-09-01.
- **Decisions weekly:** T0, then the last D26 session of each ISO week after T0. State `s_t` = IN iff the latest Master rows dated on or before the decision date of Nifty 100, Midcap 100 and Smallcap 100 (D03) are all BUY; the one-week-stale rule as T06 step 3; Smallcap 100 rows are read from 2011-11-25 only (rule 7; not binding here). Gold signal `g_t` = SIGN of the latest `Master_MAUc1` row (**D24b**) on or before the decision date.
- **Targets.** IN: the parent's basket in force, listed weights renormalised to 1 as T06/T08. OUT, Part A: 50% GOLDBEES + 50% cash. OUT, Part B: 80/20 when g is BUY, 20/80 when SELL.
- **Trades** (next D26 session after the decision, OHLC4, 10.4 bps a side on every value traded; 20.8 round trip primary, 0 and 50 as robustness): exit, entry, sleeve rebalance (Part B, g flips while OUT), basket-change trade at the basket's availableDate session (as T08; 18 changes after T0, none skipped), no trade on a g flip while IN. The initial position at T0 is free. The last decision (2019-01-02) is made, not traded.
- **GOLDBEES fill:** D09's de-spiked OHLC4 (open/high/low clipped to MCX gold's range that day plus 0.5%); the MCX range comes from D24b's daily file, which covers 2003 onward (D12 starts 2015-02-02 and would miss 2014-09 -> 2015-01).
- **Prices:** D18 with `price_corrections.csv` applied (the Polyplex factor is uniform in this window, so it changes no return inside it).

**What is known before freezing (§2 will quote it).** The rule, the 80/20 weights and MAUc1 were fixed after the `final_strategy`, T03, T06, T08 and T09 looks. **T09 ran the same weekly in-or-out and gold series on the proxy over this window and all six criteria failed** (rule 6.5% a year against 12.7% for holding the proxy over 2011-19), so the window and the timing series are seen. The parents' 2014-21 harness rebuild (`why_n100sc100`, `final_strategy`) was also seen. **There is no unseen stretch and no hold-out**; the reason is written in §2 (the only earlier real-parent data begins here). The real parents' stock selection is new relative to T09. Every Master and MAUc1 row is a production backfill. Counts to be computed in Step 1 (signals and calendar only, no price or return): decisions (about 225), in/out spells, gold spells, bounds, sleeve trades.

## Hypotheses, nulls and criteria

Six statements, each judged per book on the after-cost (20.8 bps) percentile, pass mark 90, at least 3 of 4 books.

| # | Claim | Statistic | Null that decides | Real / randomised |
|---|---|---|---|---|
| A1 (T06's H1) | the switch's exits earn more than random in/out timing, fixed 50/50 sleeve | CAGR | F1: N4.10 in/out, run with the 50/50 sleeve | in/out random |
| A2 (T06's H2) | worst fall shallower | max drawdown | F1 (50/50) | as above |
| C1 (T08's H1) | same, with the MAUc1-timed sleeve | CAGR | F1 (timed sleeve, real MAUc1 in every draw) | in/out random, gold real |
| C2 | worst fall shallower | max drawdown | F1 (timed) | as above |
| C3 | the MAUc1 timing of the sleeve beats random gold timing | CAGR | F3: N4.10-g | in/out real, gold random |
| C4 | worst fall shallower | max drawdown | F3 | as above |

Beside, not criteria: F2 (N4.9 spell shuffle) beside F1; F4 (N4.9-g) beside F3. Robustness only: F5 (both random). One null per timing (AGENT.md N2). The null tables (randomised / held / not matched) are copied from T09 §2 with this window's numbers.

**Bounds (computed from the series before any return is read).** For every state of every series `lo = min(2, shortest spell)`, `hi = longest spell` (T09's `series_bounds`), not T06/T08's typed [2,46], [2,40]. The rule's own spells lie inside by construction (V3 checks it); every table must satisfy lo*k <= S <= hi*k.

**Seeds.** First element **13** (3-9, 11 and 12 are taken; Step 1 re-checks): N4.9 `[13, 3, id]`, N4.10 `[13, 6, id]`, N4.9-g `[13, 11, 3, id]`, N4.10-g `[13, 11, 6, id]`; the exact DP sampler (`rng.random()` plus cumulative-sum search, never `Generator.choice`). 2,000 draws per book, cost and null. The four books share draws (their in-or-out and gold series do not depend on the book).

**Percentile, p-value, pass mark, secondary statistics, MDE, reportability** as T08/T09: percentile = (worse + 0.5 ties)/draws; p = (1 + at least as good)/(draws + 1); pass at 90; MDE = 2.8 x null SD printed beside every FAIL; a realisation with **fewer than 4 equity round trips**, or a gold table that cannot be split within its bounds, is NOT REPORTABLE. **Risk:** the window is about 4.3 years, so the effective sample is small (round trips and sleeve trades counted in Step 1). If Step 1 finds fewer than 4 round trips, stop and ask Manu.

**Multiplicity (N6.8).** Family m = 6 (A1, A2, C1, C2, C3, C4), each judged at 90 unadjusted for continuity with T06/T08/T09, Holm-adjusted p beside each; one rule per part, no grid; five nulls. T11 cannot upgrade F-AA-S04/S07; any finding is PROVISIONAL. The books share one market, so "3 of 4" is a consistency check; A1/A2 and C1/C2 share draws and are not independent.

**Expectation, declared before any run:** no basis for a direction. T09 on the proxy over the same weeks failed all six criteria; T06/T08 passed C1/C2 on the real parents but with edges below their MDE. Real parents add stock selection to the same timing, and the stretch includes the 2014-15 rally and the 2018 small-cap fall. The pass mark stays 90.

**Robustness (reported; they decide a finding's status, not the verdicts):**
- **R1:** all criteria at 0 and 50 bps.
- **R2:** A1, C1, C3 with LIQUIDCASE cash (`liquidEtfFinal_extended_2026-11-05.csv`).
- **R3:** start 2015-01-02 (default; exact date fixed from the Step 1 counts) with its own spells, totals, bounds, 2,000 draws.
- **R4:** agreement of the two nulls per timing; T06/T08/T09's percentiles shown as a historical reference (different window or portfolio). No pass mark.
- **R5:** F5 (both random).
- **R6:** paired contrast: every F1/F2 draw also run with the 50/50 sleeve; the rule's change in CAGR and drawdown from 50/50 to timed and its percentile among the draws' changes. Descriptive.
- **R7 (price-quality sensitivity, descriptive):** the contribution to each parent's NAV of the days flagged in `parent_rebuild_hm/price_source_steps.csv` on held stocks in the window (HINDZINC 2016-04-06 and 2017-03-29, NTPC 2015-03-20, TATASTEEL 2018-01-31, MINDACORP 2015-01-01/05, TCI 2015-01-01), and of the manual-export stocks; the rule re-run with those stocks' flagged days replaced by the previous close. No pass mark.

**Comparators (benchmarks, not nulls):** hold the parent (always IN, 0 cost and each cost); the rule with the 50/50 sleeve (Part A's rule); the constant mix at the rule's average stock share with 50/50 and MAUc1-timed non-stock shares; the 100% sleeve 50/50 and MAUc1-timed.

**Outcome map:** as T08/T09 (both timings pass; equity passes and gold fails; equity fails and gold passes; all fail; F1/F2 or F3/F4 disagree: both reported; a V gate fails: nothing is read). Read beside T09: if the real parents pass where the proxy failed, the difference is stock selection, not timing.

## Data (all `APPROVED` rows of `data/APPROVED_DATA.md`; the engine asserts it)

| Role | File | Through |
|---|---|---|
| Stock OHLC (D18) | `data/holdings_matrix/SCMO_00{03,07,10,29}_ohlc.csv`, `price_corrections.csv` | 2026-11-04 (read to 2019-01-02) |
| Basket weights (D19) | `*_holding_weight_matrix.csv`, `*_columns.csv`, `*_holding_weight_sources.csv` | 2026-09-10 / 09-16 |
| Basket history, skips (D05) | `Historical Data/frozen_2026-09-25/Rebalance_history/Rebalance_history_by_scid_<p>.csv` | 2026-09-16 |
| NSE calendar (D26) | `Historical Data/extended_2026-11-12/index_daily_pre2019/nse_trading_days.csv` | 2019-01-04 |
| Three-index signals (D03) | `Historical Data/extended_2026-10-30/Master/Master_{Nifty100,MC100,SC100}.xlsx` | 2026-10-30 |
| MAUc1 signal and range (D24b) | `Historical Data/extended_2026-11-12/MAUc1_from_2003/{Master_MAUc1.xlsx, mauc1_supertrend_weekly_extended.csv, mauc1_daily_clean_extended.csv}` | 2026-11-06 |
| GOLDBEES (D09) | `analysis/cache/why_gold_ohlc_eikon_extended_2026-11-04.parquet` | 2026-11-04 |
| Cash (D11) | `Historical Data/LBES_Adjusted_Price_data_extended_2026-11-05.csv` (R2: `liquidEtfFinal_extended_2026-11-05.csv`) | 2026-11-05 |
| Published NAV (D17), V4 regression and seam check only | `Historical Data/extended_2026-11-06/published_nav/SCMO_<p>.csv`; `parent_nav_2026-10-22/` | 2026-11-06 / 2026-10-22 |

Not read: D25 index prices, D20-D23 tags, D09b, D12, D03b, D15 AA books. D24 is not used (it starts 2015-02; D24b equals it on every shared week). Run `python data/check_approved_data.py` first and at the top of `run.sh`; non-zero means stop and ask Manu.

**Data-review notes for §3's contaminants** (from the 2026-11-17 coverage review; each to be checked against `DATA_REVIEW.md` in Step 1): D18 in the window is 100% complete for 0003, 0007, 0029 and has 3 carried bars for 0010 (PRAKASH 2017-08-08/09/10); the nine manual Eikon exports (provenance unrecorded; F-AA-D01) supply 574 / 123 / 556 / 122 bars (0003 / 0007 / 0010 / 0029), HEXT and PIRAMALFIN are export-only from 2014-07-01 and nothing checks them against a published series before 2019; the eight price steps above were never checked; dividends are not corrected (price return), and whether the unpublished 2014-19 index took special dividends (HINDZINC, NTPC) is unknown; the Muhurat sessions 2016-10-30 and 2018-11-07 are thin (about 172 stocks).

## What the engine changes (fork `t08_engine.py` into `t11_engine.py`; take `common`, `series_bounds`, the JSON assert and `shared_code_diff` from `t09_engine.py`; no imports from T08 or T09)

1. **Window and calendar.** T0 = the first basket effective on or after 2014-07-01 (assert 2014-09-01), END = 2019-01-02, calendar from D26; assert D18, GOLDBEES, cash and the Masters reach END. Remove `Book`'s D17 calendar and T0, the G0 gate against the published NAV, `LIVE_START`/R3-live, `LIQ_FROM`, and `v4_regression` against T06 evidence.
2. **Signals.** D03 Masters and D24b Master (T09's `common`); gold range from D24b's daily file.
3. **Nulls.** T08's samplers generalised as in T09 (bounds from the series, seeds with 13); F1-F5 and the 50/50 pairs; the four books share draws.
4. **`--calendar d17` option** (kept only for the regression gate, T0 = 2019-01-02, end 2019-12-31).
5. **Outputs** as T08, plus the NAV file below.

## Gates (V1-V6; any failure means nothing below is read)

- **V1** independent verifier `verify_t11.py` (a different agent from Step 2; written from `logs/verifier_spec.md`; imports nothing from the engine, `approved_data.py` or any AA analysis module): parses `APPROVED_DATA.md` itself and checks every input is an APPROVED row with matching sha256 and a through-date that covers the window; re-derives decisions (index and gold), the always-in 0-cost parent NAV, the strategy NAV at every cost, every basket and sleeve trade, and the NAVs of a sample of draws of every null (first 20 plus 20 random per book and null) to relative 1e-9; checks every draw's structure; recomputes tuple counts by inclusion-exclusion; a corrupted copy (a decision flipped, a gold week flipped, a NAV scaled, a draw out of bounds, a trade removed) must exit non-zero.
- **V2** point in time: every decision reads Master rows dated on or before it; every trade is on a later session; counted, violations 0 out of a count > 0.
- **V3** the nulls hold their tables (weeks, first state, spell counts, invested/BUY weeks identical; N4.9 sorted lengths identical; N4.10 within bounds and summing to totals).
- **V4 identities and regression.** (a) with `--calendar d17`, T0 = 2019-01-02, the engine reproduces **T08's stored `daily_nav.csv` (Part B) and T06's (Part A) on 2019-01-02 -> 2019-12-31 to 1e-12** (D17 and D26 calendars agree there; the eight F-AA-D15 sessions are 2020 or later; Step 2 confirms both runs read the same inputs on that slice); (b) one-instrument always-in identity; (c) an automated AST diff of the shared functions against `t08_engine.py` lists only expected changes; (d) the signals equal the SIGN columns of D03/D24b at every decision date; (e) D24b equals D24 on every shared decision date; (f) seam check: G0 on the unchanged rebuild code for 2019-01-02 -> 2019-12-31 against D17 (+-0.5 pp over the year, as the existing G0).
- **V5** samplers exact (chi-square on k = 3, S = 12; DP count equals inclusion-exclusion; mean spell length per position).
- **V6** sleeve, basket-trade and cost identities: post-trade values equal targets to 1e-12 of NAV; cost = traded value x bps / 2 / 10,000; at 0 cost NAV continuous through a trade; one exit, one gold flip and one basket change worked by hand in §4.0a.
- Oracle, negative-control and planted-effect controls (N6.7) are **not run**, listed in §6 as untested.

## NAV output ("add the nav somewhere", Manu)

- `tests/T11/evidence/headline/parent_nav_2014-09-01_2019-01-02.csv`: per parent, per session: hold-the-parent NAV (always IN) at 0 and 20.8 bps, Part A and Part B strategy NAV at 20.8 bps, base 1.0 at T0; header comment "rebuilt from the parent's baskets and Eikon prices, not validated against a published NAV before 2019-01-02".
- A growth chart per parent on the results page with the same caption.
- Not entered in `data/APPROVED_DATA.md` and not readable by other tests; if Manu wants it as data, register it `PENDING` and follow the review and approval procedure.

## Steps (T09's six, same hand-off rules; tracker `tests/T11/TRACKER.md` from T09's skeleton, since `TEST_TEMPLATE.md` named in AGENT.md is not on disk; step logs; "AFFECTS STEP n" warnings)

0. **Copy this plan** verbatim to `tests/T11/PLAN.md` before any engine code (copy, never retype; state its byte size in the hand-over message; never overwrite). Create `TRACKER.md`.
1. **Pre-registration:** `spell_counts.py` (fork of `tests/T09/spell_counts.py`: T0, END, R3, paths; signals and calendar only) -> `logs/step_1_spell_counts.json`; `T11.md` §1-§3 including the plain-words walkthrough (§3) and a written reason for no hold-out; `check_prereg.py --freeze`; sha256 in the header.
2. **Engine** `analysis/t11_engine.py` (inputs through `approved_data.require`). Smoke run `--run smoke --draws 20 --quick` exits 0 with V2-V6 passing.
3. **Independent verifier** `analysis/verify_t11.py` (fork `verify_t08.py` for baskets and prices, sampler code from `verify_t09.py`; drop the T06 and published-NAV parts).
4. **Test scripts** forked from `tests/T09/` (`analyse.py`, `fill_writeup.py`, `report.py`, `check_page.py`, `rerun_draw.py`, `run.sh`); heavy edits to `analyse.py`, `report.py`, `check_page.py` (remove typed `WEIGHTS`, proxy captions, `GB_FIRST`, T09's R7 kinds). Steps 2-4 can run in parallel after Step 1.
5. **Run** `bash tests/T11/run.sh` -> `evidence/headline/`; any gate failure: read nothing, fix, new run directory.
6. **Results and close:** `T11.md` §4-§8, `METHODS.md`, `evidence/report.html`; finding IDs from the `AA/CLAUDE.md` counter only at closing; update `AA/CLAUDE.md`.

## Charts and page: as T08/T09

Answer; data (with the unvalidated-rebuild and manual-export caveats up front); one backtest end to end (inputs -> signal -> trade -> units -> daily value -> curve -> statistics -> one null draw -> ranking) with a worked exit, a gold flip and a basket change; headline for A and B; per-book curves including the rebuilt parent NAV; null histograms for both timings with their companion nulls; paired contrast; comparison with T09 and T06/T08; robustness; power; definitions. Every chart hoverable, a start and end date on every number and curve.

## Key edge cases

1. Stop and ask Manu if any input is stale, `PENDING` or its sha256 differs; do not extend or rebuild data.
2. T0 = 2014-09-01 is a Monday; the decision of 2014-08-31 (Sunday) is the basket's, the first signal read is the last Master row on or before 2014-08-29.
3. 2017-10-19 has D26 but no D18 bars: last-close stand-in, counted.
4. PRAKASH carried bars (0010, 2017-08-08/09/10); export-only stocks (HEXT, PIRAMALFIN) priced from the export from the start.
5. A basket-change session that coincides with an exit or entry: one trade.
6. A gold flip and an exit on the same decision: one exit trade at the new split.
7. `fill_writeup.py` must not touch §1-§3 (F-AA-M02).
8. If Step 1 finds fewer than 4 round trips: NOT REPORTABLE, stop and ask Manu.

## Decision points still open

1. R3's start date (default 2015-01-02), settled from the Step 1 counts.
2. Whether the rebuilt NAV file should later be registered as a `PENDING` data candidate (default: no).

## Files to create (all under `AA/`)

| File | Step |
|---|---|
| `tests/T11/PLAN.md` (this file, verbatim), `T11.md`, `check_prereg.py`, `spell_counts.py`, `TRACKER.md`, `logs/` | 0-1 |
| `analysis/t11_engine.py` | 2 |
| `analysis/verify_t11.py`, `tests/T11/logs/verifier_spec.md` | 3 |
| `tests/T11/{analyse,fill_writeup,report,check_page,rerun_draw}.py`, `run.sh` | 4 |
| `tests/T11/evidence/headline/` (incl. the NAV csv), `analysis.log`, `evidence/report.html`, `METHODS.md` | 5-6 |
| `CLAUDE.md` (edit) | 6 |

Reused without change: `analysis/approved_data.py`, the sampler functions of `t08_engine.py` and `t09_engine.py` (copied, not imported).

## Verification (end to end)

1. `python data/check_approved_data.py` exits 0; `inputs.csv` lists every file read with sha256 and approved row.
2. `python tests/T11/check_prereg.py` confirms §1-§3 unchanged; `spell_counts.py` output equals the engine's run counts.
3. Smoke run, then the independent verifier on it (exit 0, corruptions detected), then `bash tests/T11/run.sh`; `analyse.py` exits 1 on any failed gate; `check_page.py` reports its checks and 0 failures.
4. The 2019 slice reproduces T06 and T08 to 1e-12 (V4a); the NAV csv exists, starts at 1.0 on 2014-09-01 and ends 2019-01-02.
