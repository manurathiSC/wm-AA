# T08 Plan: T06's three-index switch with a MAUc1-timed sleeve (80/20 or 20/80) instead of the fixed 50/50

**Written 2026-11-12. Nothing in this plan has been run and no file outside the plan has been written.** On approval the first action is to copy this file verbatim to `AA/tests/T08/PLAN.md` (standing rule, `AA/CLAUDE.md`), before any engine code. The frozen design will be `T08.md` §1-§3 (Step 1); it wins over this plan where they differ.

## Context

T06 (COMPLETE 2026-11-06) holds the parent only while Nifty 100, Midcap 100 and Smallcap 100 are all BUY, otherwise a fixed 50% GOLDBEES / 50% cash sleeve, and beat 2,000 random timings (N4.10, N4.9 beside it) in 4 of 4 books (F-AA-S07, PROVISIONAL). Manu now wants the **same test with one change: the sleeve**. While the rule is OUT:

- weekly MAUc1 signal **BUY**: 80% GOLDBEES / 20% cash;
- weekly MAUc1 signal **SELL**: 20% GOLDBEES / 80% cash.

Everything else is T06 copied: the IN/OUT rule, books, costs (0 / 20.8 / 50 bps), prices, cash, execution, statistics, nulls for the equity switch, charts and page. This is the "80/20 gold-timed sleeve" item (T06 §7, item 6). By AGENT.md task 3 a changed rule gets a new test number: **T08** (T07 is in progress; T08 extends T06). The signal is MAUc1 (MCX gold futures); the instrument traded is still GOLDBEES.

## Decisions taken (Manu, 2026-11-12)

1. **Window: the latest approved data, 2019-01-02 -> 2026-10-30** (SCMO_0007 from 2019-01-04). The end is set by the last approved index-signal row (D03, 2026-10-30), not by the published NAVs (D17 runs to 2026-11-06). The decision on 2026-10-30 is made but not traded. Consequence: T06's in/out series are one out-spell longer-ending (the extra two weeks 2026-10-23 and 10-30 are all-SELL), so T08's in/out draws are **new draws on new totals**, not T06's. T06 is reproduced on the overlap only (V4 below).
2. **Sleeve trades only when MAUc1 changes** (plus the exit and entry trades). Between events the sleeve weights drift, as T06's 50/50 did. No weekly rebalance to target.
3. **One null per timing.** Randomising two things at once hides which one a result is about (AGENT.md N2, lines 593-607), so the deciding nulls randomise one timing and hold the other real. A both-random null is a robustness check only.

## The T08 rule (complete specification, to be frozen in §3)

- **Decision weekly**, last D17 session of each ISO week after T0, as T06. State `s_t` = IN iff all three index SIGNs are BUY (latest Master row dated on or before the decision date; T06 step 3 incl. the one-week-stale rule).
- **Gold signal `g_t`**: the SIGN (BUY/SELL) of the latest `Master_MAUc1` row dated on or before the decision date, same as-of rule. All MAUc1 rows are a backfill by the production ST.py on MAUc1 (it is not in the Friday job; `FRA_MAUc1/README.md`), disclosed as the index backfill is.
- **Targets.** IN: 100% parent. OUT with g = BUY: 80% GOLDBEES + 20% cash. OUT with g = SELL: 20% GOLDBEES + 80% cash.
- **Trades** (next D17 session after the decision, OHLC4 fills, 10.4 bps a side on every value traded, cash included, as T06) happen only when the target changes:
  - exit (IN -> OUT): sell the basket, buy GOLDBEES and cash at the weights for the **current g**;
  - entry (OUT -> IN): sell the sleeve, buy the basket;
  - **new, sleeve rebalance** (OUT, g flips): sell and buy GOLDBEES and cash from their drifted values to the new weights, cost on the value traded;
  - g flips while IN: no trade, and the gold weight is read at the next exit.
- Initial position at T0 is free (as T06): sleeve weights per g at T0 if OUT. GOLDBEES fills use the de-spiked OHLC4 (D12 MCX range) where covered and raw OHLC4 after 2026-09-28.
- Parent basket rebalances while OUT: not traded, as T06.

**What is known before freezing (to be quoted at the top of §2, AGENT.md task 5, lines 404-405):** everything through 2026-10-22 was seen in T03 and T06 for the equity switch. Earlier studies (`analysis/evidence/final_strategy/` incl. `mauc1/mauc1_summary.csv`, `why_n100sc100/gold_sleeve_*`) examined gold-timed sleeves and the MAUc1-versus-GOLDBEES signal choice in-sample; Step 1 reads them and quotes what they reported about the 80/20 sleeve. The 80/20 weights are Manu's, not searched here. The MAUc1 signal choice may have followed earlier results (disclosed).

## Hypotheses, nulls and criteria

Four statements, each judged per book on the after-cost (20.8 bps) percentile, pass mark 90, "at least 3 of 4 books" (T06's C1/C2 form).

| # | Claim | Statistic | Null that decides | Real / randomised |
|---|---|---|---|---|
| C1 (H1) | the equity switch's exits earn more than random in/out timing, with the gold-timed sleeve in place | CAGR, higher better | **F1: N4.10** free-length in/out | in/out **random**; MAUc1 signal **real** in every draw |
| C2 (H2) | the rule's worst fall is shallower | max drawdown | F1 | as above |
| C3 (H3, **new**) | the MAUc1 timing of the sleeve earns more than random MAUc1 timing | CAGR | **F3: N4.10-g** free-length gold signal | in/out **real**; MAUc1 signal **random** |
| C4 (H4, **new**) | the sleeve timing lowers the worst fall more than random gold timing | max drawdown | F3 | as above |

**Beside, not criteria:** F2 = N4.9 spell shuffle of in/out (as T06) beside F1; F4 = N4.9-g spell shuffle of the gold signal beside F3.
**Robustness only:** F5 = both random (N4.10 in/out and N4.10-g together), the rule's percentile against "everything random".

**What each null holds and breaks (table for §2, N9):**

| Dimension | F1 / F2 (in/out random) | F3 / F4 (gold random) |
|---|---|---|
| in/out switch | randomised: spell lengths (F1, free within [2, HI]) or order (F2); first state, spell counts, weeks invested held | real, held |
| MAUc1 signal | real series in every draw (the draw's OUT weeks see the real g of those weeks) | randomised: BUY/SELL spells; first state, number of BUY and SELL spells, total BUY weeks held |
| book, calendar, costs, execution | held | held |
| fraction of sessions in the parent | not held exactly (weeks hold 3-5 sessions; reported) | held (in/out real) |
| gold weeks seen by the sleeve | not matched (a draw is OUT in other weeks) | not matched: the sleeve only sees g in the rule's OUT weeks, so fewer than the whole-series switches count |
| persistence of the signal | not held | not held |

**N4.10-g sampler.** The T06 exact sampler (`count_table`, `draw_lengths`, `free_length_draw`, DP counts, `rng.random()` plus cumulative-sum search) reused unchanged on the gold series' spells. Bounds per state: `lo = min(2, the shortest actual spell of that state)`, `hi` = the longest actual spell of that state, **computed from the actual series before any return is read** (T06's bounds were set after seeing draw 445; this is not repeated). The rule's own spells lie inside the bounds by construction (V3 checks it). Seeds: in/out as T06, `[3, id]` (N4.9) and `[6, id]` (N4.10), so the in/out sampler is unchanged; gold `[11, 3, id]` (N4.9-g) and `[11, 6, id]` (N4.10-g); checked in Step 1 against T03-T07 seeds (T07 uses 7, 8, 9). 2,000 draws per book, cost and null.

**Percentile, p-value, pass mark, draws, MDE, secondary statistics, reportability gate (4 round trips; also at least 4 gold spells overlapping OUT weeks)**: exactly T06 §2/§3. MDE = 2.8 x null SD, printed beside every FAIL. Effective sample size: 9-10 equity round trips and the (counted in Step 1) number of MAUc1 spells; "3 of 4" is a consistency check, the four books share one signal series.

**Multiplicity (N6.8, lines 993-1001), declared in §2:** family of m = 4 criteria (C1-C4), each judged at the T06 pass mark of 90, **unadjusted** (continuity with T06), with Holm-adjusted p beside each reported; one rule, no grid; five nulls applied (F1-F5) plus T03/T06's earlier ones. The finding is PROVISIONAL whatever the outcome (seen window). C1/C2 replicate T06 under the timed sleeve; **only C3/C4 are the new claim.**

**Expectation, declared before any run:** no basis for a direction. Gold's long rally to late 2025 and the 80% gold weight while MAUc1 is BUY could lift the rule; a trending gold market also makes any trend signal look good against random spell placements. The pass mark stays 90.

**Robustness (reported; they decide a finding's status, not the verdicts):**
- **R1:** C1-C4 at 0 and 50 bps.
- **R2:** C1 and C3 with LIQUIDCASE cash (R2 of T06), 20.8 bps.
- **R3:** C1 and C3 on the live sub-window 2021-11-01 -> 2026-10-30 (own spells, totals, bounds; reportability applies).
- **R4:** agreement of the two nulls per timing: F1 vs F2 and F3 vs F4 percentiles per book, each null's median / SD / 5th / 95th percentile of CAGR; T06's stored percentiles as a historical reference (different window). No pass mark.
- **R5:** F5, both random.
- **R6 (paired contrast, descriptive):** every F1/F2 draw is also run with the sleeve fixed at 50/50 (T06's sleeve; the T08 engine's `fixed50` mode). The rule's CAGR and drawdown change from 50/50 to timed, and its percentile among the draws' changes. Answers "does the overlay add anything, and is that special to the rule's equity timing?". No pass mark.
- **R7 (raw fill sensitivity):** the actual MAUc1 flip decided 2026-10-23 trades on 2026-10-26, after the MCX de-spike file ends (2026-09-28), so it fills at the raw GOLDBEES OHLC4. Re-run the rule with the close on every raw-fill session and report the change. Count-first: the number of raw-fill sessions in the window and the bar ranges on them are listed in Step 1.

**Comparators (benchmarks, not nulls):** hold the parent; the rule with the **fixed 50/50 sleeve** (T06's rule on this window); the constant mix at the rule's average parent share with a 50/50 non-stock share (T06's) **and** with a MAUc1-timed non-stock share; the 100% sleeve 50/50 and 100% MAUc1-timed sleeve; the published NAV. The constant mix says how much of any gain is only a different average exposure.

**Outcome map:**

| Pattern | Conclusion |
|---|---|
| C1, C2 PASS; C3, C4 PASS | both timings beat chance; the gold-timed sleeve is supported as timing (PROVISIONAL) |
| C1, C2 PASS; C3 or C4 FAIL | the equity switch carries the result; the MAUc1 timing is not distinguishable from random gold timing, so any gain over 50/50 (R6) is gold exposure, not timing skill |
| C1 or C2 FAIL; C3, C4 PASS | the sleeve timing does something the equity switch no longer shows, with the new sleeve |
| all FAIL | no timing edge over chance on this window |
| a V gate fails | nothing is read; fix and rerun as a new run directory |

If F1 and F2 (or F3 and F4) disagree, both are reported and the status note says so (N6.8). Not rerun: the circular-shift null. Not run (listed in §6): the oracle, negative-control and planted-effect controls (N6.7), as T06.

## Data (all `APPROVED` rows of `AA/data/APPROVED_DATA.md`; the engine asserts it)

| Role | File | Through |
|---|---|---|
| Calendar, published NAV (D17, **extended**) | `Historical Data/extended_2026-11-06/published_nav/SCMO_<p>.csv` (new format: `_id.scid, _id.date, index`, newest first; the reader must be adapted) | 2026-11-06 (window ends earlier) |
| Index signals (D03 extended) | `Historical Data/extended_2026-10-30/Master/Master_{Nifty100,MC100,SC100}.xlsx` | 2026-10-30 (**sets the window end**) |
| **MAUc1 signal (D24, new)** | `Historical Data/extended_2026-11-06/MAUc1/Master_MAUc1.xlsx` (weekly CSV there as a cross-check) | 2026-11-06 |
| Stock OHLC, corrections, weights, rebalance history (D18, D19, D05) | as T06 | 2026-11-04 / newest basket 2026-09-10 and 2026-09-16 |
| GOLDBEES (D09) | `analysis/cache/why_gold_ohlc_eikon_extended_2026-11-04.parquet` | 2026-11-04 |
| Gold de-spike range (D12) | `analysis/evidence/final_strategy/mauc1/mauc1_daily_clean.csv` | 2026-09-28 (raw OHLC4 after; the one actual sleeve trade of the tail, 2026-10-26, is among them) |
| Cash (D11 extended; R2 LIQUIDCASE) | `Historical Data/LBES_Adjusted_Price_data_extended_2026-11-05.csv`, `liquidEtfFinal_extended_2026-11-05.csv` | 2026-11-05 |

Caveats go in §3 and the page: T06's (cash source F-AA-D09 and the 0.5 pp/yr richness, last approved basket, 2021-11 backfill) plus the MAUc1 backfill (all rows), the raw-fill sessions after 2026-09-28, and `check_approved_data.py` currently lists `extended_2026-11-12/SOURCE.md` as unregistered (exit code 0; to be registered or removed by Manu before the run).

## What the engine changes (fork `t06_engine.py` into `t08_engine.py`; no imports from T06)

Map from the read of `analysis/t06_engine.py` (944 lines); line numbers are T06's.
1. **Sleeve weights.** `trade()` l.347-364 hard-codes `Tg = Tc = (1 - e_new)/2 * V` (l.353), and `simulate()` l.372-373 sets the initial units the same way. Add a per-decision gold weight `gw` (0.8 / 0.2, default 0.5 = T06): `Tg = (1 - e_new)*gw*V`, `Tc = (1 - e_new)*(1 - gw)*V`. `trade()` already handles a sleeve-only trade (`e_new = 0`, no stocks held: `traded = |Tg - held_g| + |Tc - held_c|`, cost included).
2. **Trade key** (`simulate` l.375-378, 388-391): a target exists when `(e, gw)` differs from the current pair, not only `e`. Carry `gw_cur`. New trade kind `sleeve_rebalance`. The l.388 condition (`t in basket_events and e_cur > 0`) stays, so basket changes while OUT are still skipped.
3. **Gold column.** `Book.decisions()` l.323-343 gains `g_sign` and `gw` from `Master_MAUc1` with the same as-of rule (E3); `common()` l.188-225 loads it through `ap()`; the coverage assertion l.745-747 includes D24. `run_book` l.602-635 passes `gw` to every `simulate` call (strategy l.609, comparators l.620, draws l.627, live window, R2).
4. **Window end.** `_d17_end()` l.136-145 sets `END` from D17; change to END = last D03 Master row (2026-10-30), assert every D17 / D18 / D09 / D11 / D24 file runs to at least END. `raw_parent()` l.155-182 reads the new published-NAV format.
5. **Nulls.** Keep `spell_shuffle` l.457, `free_length_draw` l.521, `rule_bounds` l.476, `count_table` l.485, `draw_lengths` l.501 unchanged for in/out. Add the same functions applied to the gold series (generalised to a state series and its own bounds, `lo = min(2, shortest)`), `make_states` for gold draws, and a family loop F1-F5 in `run_book`. `draws.csv` gains `io_null`, `gold_null`, `sleeve_mode`, `g_lengths`. F1/F2 draws are also simulated with `gw = 0.5` (R6).
6. **Comparators** (`constant_mix` l.618 with `every=True`; `sleeve_only` l.619) get both the 50/50 and the timed variants.
7. **Outputs** as T06 plus `gold_signal.csv` (the g series per book and week), `count_table.json` for gold tables, `sleeve_trades.csv` (every sleeve rebalance), `regression_t06.json`; `audit.json` readings updated (E4, E8: the 50/50 statements).

## Gates (V1-V5 as T06; V6 new; any failure means nothing below is read)

- **V1 independent check.** `verify_t08.py`, forked from `verify_t06.py` (1,874 lines, imports nothing from the engine) and written from `logs/verifier_spec.md` **without reading `t08_engine.py`** (F-AA-M04). Changes: its own `simulate` (l.327-438: init l.355-356, switch construction l.358-367, targets l.392-393, kind rule l.378) and `decisions_for_window` (l.293-321) get the gold column; new checks for sleeve trades, gold states and tables; the corrupted-copy test also corrupts a gold signal week and a sleeve trade. Exits 0 only if rows were compared; `SCRATCH` (l.48) path fixed.
- **V2 point in time.** Every decision reads Master rows (index and MAUc1) dated on or before the decision date; every trade, sleeve rebalances included, is on a later session. Counted, violations 0 of a count > 0.
- **V3 nulls hold their tables.** In/out as T06 for F1/F2/F5. Gold draws (F3/F4/F5): weeks, first state, spell counts, total BUY weeks identical to the real g series; N4.10-g lengths in bounds and summing to the totals; N4.9-g sorted lengths identical; the rule's own g spells in support.
- **V4 regression to T06, on the overlap.** (a) In/out decisions equal T06's `decisions.csv` on every shared date; (b) with `gw` fixed at 0.5 the engine reproduces T06's strategy, hold-parent, 100%-sleeve (50/50) and constant-mix NAVs to relative 1e-12 up to 2026-10-22; (c) T06's first 20 N4.10 draws replayed from T06's `draw_states.npz` (rule states appended after 2026-10-22) reproduce T06's `draw_curves_20.8.npz` on the overlap; (d) always-in against the published NAV within G0 (+-0.25 pp/yr, +-0.5 pp each year) over the whole window; (e) the extended D17 equals the old D17 on its rows; (f) the g series equals the SIGN column of D24's weekly CSV.
- **V5 sampler exact.** As T06 for in/out tables; the DP count equals inclusion-exclusion for every gold table; chi-square on a small case; mean spell length per position within 4 SE.
- **V6 sleeve identity (new).** At every sleeve rebalance, exit and entry: post-trade GOLDBEES and cash values equal their targets to 1e-12 of NAV; cost = `ow x traded`; at 0 cost NAV is continuous through the trade; with `g` constant the weights never change while OUT; a held-out hand-computed example (one exit, one g flip) printed in §4.0a.
- **Reportability gate** as T06 plus the gold-spell condition above. NOT REPORTABLE realisations are not quoted.

## Steps (T06's six, same handoff rules; tracker `AA/tests/T08/TRACKER.md`, step logs, "AFFECTS STEP n" warnings)

1. **Pre-registration** (`T08.md` §1-§3, `check_prereg.py` forked from T06's, hash frozen with `--freeze`). Before writing: `check_approved_data.py` exits 0; counts only, no return of any kind: in/out spells on the new window (k_in, k_out, S, longest, round trips, per book and live window), the **MAUc1 spells** (k_buy, k_sell, S, shortest, longest) on the full and live windows, how many MAUc1 flips fall in OUT weeks (the sleeve's trade events), raw-fill sessions, feasibility (2k <= S <= hi x k) for every table, HI/lo for the gold bounds. Quote what earlier studies reported about the 80/20 MAUc1 sleeve. `spell_counts.py` forked.
2. **Engine** (`analysis/t08_engine.py`, uses `approved_data.require`). Smoke run `--run smoke --draws 20 --quick` exits 0 with V3-V6 passing.
3. **Independent verifier** (`analysis/verify_t08.py`, a different agent from Step 2, never reads the engine).
4. **Test scripts** forked from `tests/T06/`: `analyse.py` (C1-C4, R1-R7, MDE, Holm p, writes `analysis.log`), `fill_writeup.py` (must leave §1-§3 byte-identical; `check_prereg.py` straight after), `report.py`, `check_page.py`, `rerun_draw.py` (adds `--family`, `--gold-id`), `run.sh` (as T06 with T08 names and the data check first).
5. **Run** `bash tests/T08/run.sh` (data check, prereg check, engine, verifier, analysis, fill, report, page check). Expected size: about 4-5x T06's sims per book (F1-F5 plus the 50/50 pair), so roughly 5-10 minutes; measured at the smoke run.
6. **Results and close:** `T08.md` §4-§8; findings with IDs taken from the `AA/CLAUDE.md` counter **at closing** (T07 holds F-AA-S08, F-AA-M07, F-AA-D16 until it closes); `AGENT.md` gets an entry for the gold-signal (component) null and the rule "one null per timing, joint null as robustness" beside N4.10, a row in "Choosing among them", and a revision-history row; `AA/CLAUDE.md` current-test bullet; `METHODS.md`; `check_prereg.py` once more.

## Charts and page (same as T06; additions only where the new rule or nulls need them)

`report.py` forks T06's page: answer; data; one backtest end to end (now including the **worked sleeve trade**: one exit with the g weights, one g flip with the GOLDBEES/cash units before and after, costs); headline for both timings; per-book curves; null histograms (in/out F1 with F2 overlaid, **gold F3 with F4 overlaid**); the highest-return draw against the rule (regime chart with a **MAUc1 strip and the sleeve weights** added); held/randomised tables for both nulls; paired contrast (R6); robustness; power; definitions. Every chart hoverable (R10); hover arrays from the arrays that draw the charts; `check_page.py` re-derives every number, date and hover array and mirrors the changed captions (T06's "50/50" text at `report.py` l.38, 772, 815, 854, 881 and `analyse.py` l.448).

## Verification (end to end)

- `python data/check_approved_data.py` exits 0 before Step 1 and at the top of `run.sh`.
- `python tests/T08/check_prereg.py` exits 0 before and after every write-up script.
- Smoke: engine V3-V6 pass; verifier on smoke evidence passes every comparison; corrupted copy detected.
- Headline: V1-V6 PASS; `check_page.py` 0 failures; `rerun_draw.py` reproduces the best draw of each family exactly; with `gw = 0.5` the run reproduces T06 to 1e-12 on the overlap (the key proof that only the sleeve changed).
- Read `analysis.log`: C1-C4 per book, the nulls side by side (R4), R6 paired contrast, R7.

## Key edge cases

1. Stop and ask Manu if any input is stale, `PENDING`, or its sha256 differs; do not extend or rebuild data.
2. SCMO_0007 starts 2019-01-04 (one week fewer); its S values come from its own series.
3. A g flip decided on a session whose trade falls on a raw-fill GOLDBEES day uses raw OHLC4; counted and shown (R7).
4. The last decision (2026-10-30) is made, not traded. The MAUc1 SELL flip decided 2026-10-23 is traded 2026-10-26, inside the window.
5. Exit and a g flip on the same decision: one exit trade at the new g weights, no extra sleeve trade.
6. A draw can equal the rule exactly; ties count as usual.
7. `fill_writeup.py` must not touch §1-§3 (F-AA-M02).
8. The template `TEST_TEMPLATE.md` lives at `wm-research/TEST_TEMPLATE.md` (the link in `AA/CLAUDE.md` does not resolve); T08.md is forked from `T06.md`.

## Files to create (all under `AA/` unless stated)

| File | Step |
|---|---|
| `tests/T08/PLAN.md` (verbatim copy of this plan), `T08.md`, `check_prereg.py`, `spell_counts.py`, `TRACKER.md`, `logs/` | 1 |
| `analysis/t08_engine.py` | 2 |
| `analysis/verify_t08.py`, `tests/T08/logs/verifier_spec.md` | 3 |
| `tests/T08/{analyse,fill_writeup,report,check_page,rerun_draw}.py`, `run.sh` | 4 |
| `tests/T08/evidence/headline/`, `analysis.log`, `evidence/report.html`, `METHODS.md` | 5-6 |
| `../AGENT.md`, `CLAUDE.md` (edits) | 6 |

Reused without change: `analysis/approved_data.py`, the sampler functions of `t06_engine.py` (copied, not imported), `analysis/mauc1_st_production.py` (not run; D24 is already approved).
