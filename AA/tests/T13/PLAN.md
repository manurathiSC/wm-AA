# T13 Plan: T11 with a 2-of-3 entry rule (hold the parent when at least two of the three index signals are BUY), four real parents, 2014-09-01 -> 2019-01-02

**Written 2026-11-18 by Claude, on Manu's go-ahead in chat** ("can you run T11 on the strategy of atleast 2 indices in buy instead of all 3 should be in buy"; after Claude restated it: "correct understanding lets make and run the test 13"). This plan was not separately reviewed; Manu approved the restatement (T11 with one change, a new test number, T11's window). On the freeze the design becomes `T13.md` §1-§3 (Step 1), which wins over this plan where they differ. Nothing in this plan has been run.

## Context

T11 (COMPLETE 2026-11-17) ran T06's rule (fixed 50/50 sleeve, Part A) and T08's rule (MAUc1-timed sleeve, Part B) on the four real parents' own stocks, 2014-09-01 -> 2019-01-02: the book holds the parent only when the weekly supertrend SIGN of Nifty 100, Midcap 100 **and** Smallcap 100 are all BUY. All six criteria failed (CAGR percentiles against F1 13.0-45.6; against F3 37.2), low power (8 round trips). T13 changes **one thing**: the book holds the parent when **at least two** of the three SIGNs are BUY. Everything else is T11's (AGENT.md task 5, "change one thing at a time"; task 3, "an old question under a changed rule gets a new test number"). T11 keeps its numbers.

## The T13 rule (= T11 §3 with step 3 changed)

- State s_d = IN iff the number of BUY among the latest Master rows (D03) of Nifty 100, Midcap 100 and Smallcap 100 dated on or before d is >= 2; else OUT. Gold g_d from D24b as T11.
- Window, T0 (2014-09-01), END (2019-01-02), D26 calendar, baskets, targets (IN: the parent's basket; OUT: 50/50 in Part A, 80/20 or 20/80 by MAUc1 in Part B), execution (next session OHLC4, 10.4 bps a side), parent rebalances, NAV, statistics: T11 §3 steps 1-10 unchanged.

## What is known before freezing (§2 will quote it)

- T11's whole result on this window with the all-3 rule (all six criteria FAIL; the rule 10.7 / 3.6 / 6.5 / 11.3% against 32.2 / 17.5 / 22.1 / 25.7% for holding each rebuilt parent). **The 2-of-3 variant is proposed after seeing T11 fail**, so T13 is a post-hoc variant: disclosed, any finding PROVISIONAL at most, and a pass cannot be read as confirmation (one more look at the same weeks).
- T10's production rule (FS >= 0.60 of held stocks in a BUY band) on 2019-2026 is a related "not all three" rule; seen.
- Counts (Step 1, signals and calendar only, no price or return) fix the spell tables and bounds before any engine run.

## Hypotheses, nulls, criteria: T11's, unchanged in form

A1/A2 (fixed 50/50 sleeve, F1), C1/C2 (timed sleeve, F1), C3/C4 (MAUc1 gold timing, F3); F2 and F4 beside; F5 robustness. Percentile >= 90 in at least 3 of 4 books, after 20.8 bps. Bounds from the 2-of-3 series (lo = min(2, shortest), hi = longest), Step 1. **Seeds first element 16** (15 is T12's; 16 unused, checked 2026-11-18): N4.9 `[16, 3, id]`, N4.10 `[16, 6, id]`, N4.9-g `[16, 11, 3, id]`, N4.10-g `[16, 11, 6, id]`. 2,000 draws. Reportability: fewer than 4 round trips -> NOT REPORTABLE (stop and ask Manu). The gold series is T11's; its tables are the same, but which gold flips reach the sleeve changes with the in-or-out series.

Robustness R1-R7 as T11 (R3 start 2015-01-02, R7 20% rule on D18). Comparators as T11, **plus the all-3 rule (T11's rule) as a descriptive comparator** at each cost and sleeve, so the page shows 2-of-3 against all-3 on the same prices and costs. No pass mark on that comparison (it is not a null).

**Outcome map additions:** read beside T11: if 2-of-3 passes where all-3 failed, it is one post-hoc variant on a seen window (PROVISIONAL, needs a fresh window); if it fails too, the switch shows no edge on this window under either rule.

## Gates (T11's V1-V6) with V4(a) extended

- **V4(a):** (a1) the engine run with the rule fixed to all-3 reproduces **T11's stored `daily_nav.csv` strategy rows (Part A and Part B, every cost, every book, the full window) and T11's `decisions.csv` states** to relative 1e-12 (this is the all-3 comparator, so it costs nothing extra); (a2) T11's `--calendar d17` regression against T06's and T08's stored 2019 NAVs, with the all-3 rule, kept as in T11.
- **V4(c):** AST diff against `t11_engine.py`: only expected changes.
- **V1** verifier `verify_t13.py`: a fork of `verify_t11.py` written by a different agent from the engine's, which never opens `t11_engine.py` or `t13_engine.py`; implements the 2-of-3 rule independently; re-derives the all-3 comparator too.
- V2, V3, V5, V6 as T11.

## Steps (T11's, same hand-off rules; tracker `tests/T13/TRACKER.md`)

0. This plan, written directly to `tests/T13/PLAN.md` (no plan-mode file exists to copy); `TRACKER.md`.
1. `spell_counts.py` (fork of T11's with the rule changed) -> `logs/step_1_spell_counts.json`; `T13.md` §1-§3 (fork of T11.md §1-§3 with the rule, counts, bounds, seeds, disclosures and V4(a) changed); `check_prereg.py --freeze`.
2. Engine `analysis/t13_engine.py` (fork of `t11_engine.py`: rule, seeds, paths, frozen counts, the all-3 comparator, V4(a1)). Smoke run.
3. Verifier `analysis/verify_t13.py` (fork of `verify_t11.py`, separate agent), spec `logs/verifier_spec.md`.
4. Scripts forked from `tests/T11/` (`analyse.py`, `fill_writeup.py`, `report.py`, `check_page.py`, `rerun_draw.py`, `plot_parent_vs_partb.py`, `run.sh`), with T11 as the main reference beside T06/T08/T09.
5. `bash tests/T13/run.sh` -> `evidence/headline/`; any gate failure: read nothing, fix, new run directory.
6. `T13.md` §4-§8 (via `fill_writeup.py`), `METHODS.md`, `evidence/report.html`; `AA/CLAUDE.md` updated; finding IDs pending as for T07-T12.

## Data

T11's files exactly (all APPROVED rows; `check_approved_data.py` exit 0 on 2026-11-18, 67 approved rows); plus T11's stored evidence (`tests/T11/evidence/headline/daily_nav.csv`, `decisions.csv`) read by gate V4(a1) only, as test evidence, not data.
