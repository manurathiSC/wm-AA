# T10 Plan: hold the whole parent while the weekly FS score is at least 0.60 (the segment_v2 production rule), against the three-index switch and hold-the-parent

**Written 2026-11-12 from Manu's request in chat ("do the FS score using the same mechanism, tag-check every week; if it is at least 0.6 buy the entire portfolio, not just the segment; it is not all three and it is not segmented; design a new test; no need for a null test"). Nothing in this plan has been run, no data has been pulled, and no file outside `AA/tests/T10/` has been created or changed.** This is the implementation plan. The frozen design will be `T10.md` §1-§3 (Step 1) and wins where they differ. Per `AA/CLAUDE.md`, this file is kept verbatim as `PLAN.md`; a revision goes beside it as `PLAN_v2.md`.

## The question

Today the whole-book switch holds a parent only when Nifty 100, Midcap 100 and Smallcap 100 are **all** BUY (T03-T08). T07 asks whether holding each stock by its own band's signal does better. **T10 asks the third version, the one production's `segment_v2` ran** (`analysis/segment_v2.py` `build_production`, `analysis/gate_v2.py` `compute_fs`): every week, tag each stock the parent holds, compute the FS score, and hold the **entire** parent basket at its listed weights if FS is at least 0.60, otherwise put the whole book in the 50/50 GOLDBEES and cash sleeve. No stock is held or dropped individually, and no single index decides.

**The rule, exactly.** At each weekly decision date d:
1. Take the basket in force at d (T06's rule: the latest non-skipped basket whose availableDate is on or before d).
2. Tag every stock in it (listed weight > 0) as Large, Mid or Small and below with `tag_lookup.tag(ISIN, d)`. **Tags are re-read at every weekly decision, not only at events** (Manu's instruction; production re-tags at every review).
3. A stock is *on* if the SIGN of its band's index is BUY at d: Large reads Nifty 100, Mid reads Midcap 100, Small and below reads Smallcap 100 (the three approved signal files, D03).
4. **FS = Σ over bands of (share of the held stocks in that band by count) × (1 if the band's index is BUY else 0).** The share is by stock count, not by weight (as production). This equals the fraction of held stocks that are *on*. T07's rule keeps exactly those stocks; T10 holds all of them or none.
5. **IN if FS ≥ 0.60, else OUT.** IN: every stock at its listed weight. OUT: 50% GOLDBEES and 50% cash. No other state.
6. Trade at the next session's OHLC4, 10.4 bps a side, T06's conventions for events, targets, execution and NAV (no cash account, renormalised weights, first position free, no sale at the end).

**Worked example (invented numbers).** A basket of 15 stocks: 5 Large, 4 Mid, 6 Small. Signals: Nifty 100 BUY, Midcap 100 SELL, Smallcap 100 BUY. FS = 5/15 + 0 + 6/15 = 0.733 ≥ 0.60, so T10 holds all 15 stocks. The three-index switch is OUT (not all BUY). T07 holds 11 and sells the 4 Mid stocks to the sleeve.

**Two exact facts the engine and the verifier will check.**
- **Superset.** If all three signals are BUY, every stock is on and FS = 1, so T10 is IN whenever the three-index switch is IN. T10 can never be more defensive than the switch; it differs only in weeks where the switch is OUT but at least 60% of the stocks (by count) sit in a BUY band. Whatever it gains or loses against the switch comes from those weeks alone.
- **The threshold is exact.** FS ≥ 0.60 is decided in integers: with k stocks on out of n held, IN iff 5k ≥ 3n. FS = 0.60 exactly is IN. Production's float sum can land on either side of 0.6 at an exact tie (n = 5, 10, 15 with k = 3, 6, 9); the engine counts the weeks where the float formula and the exact one disagree and prints them. The exact reading decides; the count is disclosed.

## What is fixed, and why

- **Signals:** Nifty 100, Midcap 100, Smallcap 100 (D03, extended to 2026-10-30; Smallcap 100 usable from 2011-11-25, irrelevant here, the window is 2019+). Production's own FS reads Midcap 150 and Smallcap 250 from 2026-04; no signals for those are approved, and the research stand-ins (MC100 for MC150, SC100 for SC250 and Microcap 250) are what Study 2 documents as the pre-2026-04 FS inputs (`why_n100sc100/METHODS.md` line 88). Disclosed; forced by the approved data, not chosen.
- **Tags:** D20-D23 through `analysis/tag_lookup.py` only, never a private ranking. All the caveats of `AA/CLAUDE.md` (Tags bullet) go on the page. Because FS counts stocks and averages tag errors across the basket, a wrong tag matters less than in T07, but R4 measures it.
- **Window and books:** 2019-01-02 → 2026-10-30 (0007 from 2019-01-04), the four parents SCMO_0003, 0007, 0010, 0029, as T07. Live sub-window 2021-11-01 →. Cost 0, 20.8 (primary) and 50 bps round trip.
- **Data:** the approved rows T07 reads. `python data/check_approved_data.py` must exit 0 before Step 1 and at the top of `run.sh`. No new data is needed; if any file is stale or missing, stop and ask Manu.
- **Engine:** a fork of `analysis/t07_engine.py` (which already has per-stock tags, `tag_lookup`, the T06 execution, the comparators and the report plumbing), with the decision replaced by FS and the tag read moved from events to every weekly decision. New file `analysis/t10_engine.py`; T07's engine is not edited.

## No null: what that means for the claim

Manu waived a null test. A strategy backtest normally ranks its result among random draws (AGENT.md N4); without that, **T10 can say what the rule earned and how it compared, but not that it beats chance.** So:
- The criteria below are **comparisons with named benchmarks**, not percentiles against draws. Their pass marks are written before any run.
- Any finding is capped at **PROVISIONAL**, with the sentence "no chance benchmark was run; the result is descriptive of one window, four books that share one set of signals".
- Three things stand in for a null and are reported beside every number, none with a pass mark: **the constant-mix control** (same average exposure, held all the time, so a gain that is only less exposure shows), a **moving-block bootstrap interval** of the daily-return difference (blocks of 20 sessions, 1,000 resamples, seeded) for rule − switch and rule − parent, and a **stretch table** (below) that shows whether a difference is one episode or many.
- Negative and positive controls (N6.7) need nulls, so they are **not run**; §6 lists that as untested.

## Comparators (benchmarks, same calendar, cost, T0, sleeve)

1. **Hold the parent** (the engine with every stock held, and the published NAV rebased to 1.000).
2. **The three-index switch** (IN iff all three BUY; this is T06's strategy; the engine reproduces T06's NAV, gate V3).
3. **The 100% sleeve.**
4. **Constant mix**: the rule's own average share of NAV in the parent's stocks over the window, held as that share in the parent and the rest half GOLDBEES, half cash, rebalanced at each event at OHLC4 with the same cost.
5. **Descriptive only:** T07's per-stock rule run through the same engine (not T07's verdict, which is its own test), and on the live window the published AA books (D15), which run other rules.

## Pre-registered pass criteria (after 20.8 bps, per book, 4 books; proposed, Manu to confirm before Step 1)

| # | Criterion | Pass condition |
|---|---|---|
| C1 | Return vs the parent | rule CAGR > hold-the-parent CAGR in at least 3 of the 4 books |
| C2 | Protection vs the parent | rule maximum drawdown shallower than hold-the-parent's in at least 3 of the 4 books |
| C3 | Increment vs the three-index switch | rule CAGR > switch CAGR in at least 3 of the 4 books |
| C4 | Risk-adjusted vs the switch | rule Calmar (CAGR ÷ \|maximum drawdown\|) ≥ the switch's in at least 3 of the 4 books |

"3 of 4" is a consistency check, not four independent tests: the books share one market, one set of signals and the same weeks. **Reportability gate** (counts taken in Step 1, before freezing, from signals and tags only, no return): C3 and C4 are quoted only if the rule differs from the switch in at least 5 separate stretches of weeks in the book; otherwise the book is NOT REPORTABLE for them and the page says so.

**Robustness and descriptive checks (reported; they decide a finding's status note, not the verdicts):**
- **R1** cost at 0 and 50 bps; trades and cost paid of the rule, the switch and the constant mix.
- **R2** C1-C4 on the live window alone (2021-11-01 →), if reportable.
- **R3** the cash leg replaced by `liquidEtfFinal_extended_2026-11-05.csv` (LIQUIDCASE).
- **R4** tag error: 500 draws; at every weekly tag read each rank-sourced tag is replaced, with probability 7.93% (one minus the 92.07% agreement in `data/review/2026-11-12_tag_sources/REVIEW.md`), by one of the other two bands with equal probability; membership tags are not perturbed. Reported: the distribution of rule − switch CAGR, the share of draws above zero, and the share of weeks whose IN/OUT decision changes. No pass mark. This is a sensitivity of the data, not a null of the claim.
- **R5** threshold curve, descriptive: CAGR, drawdown and share of time IN at FS thresholds 0.40, 0.50, 0.60, 0.70, 0.80 (decided exactly, as above). Five settings are shown, none is selected; 0.60 is production's value and the only reference setting. No claim comes from this table.
- **R6** weight-weighted FS in place of count-weighted, descriptive.
- **R7 stretch table.** Every maximal run of weeks where the rule is IN and the switch is OUT, with its dates, length, the stock share on, and the rule's log return minus the switch's over it; then the CAGR difference with the single largest stretch removed. Shows whether C3 is one episode.
- **R8** the published AA books beside the rule on the live window (context only).

## Validity gates (nothing below may be read if any fails)

| # | Gate | Pass condition |
|---|---|---|
| V1 | Independent check `verify_t10.py` | Written by a separate agent from a written spec, without reading `t10_engine.py` or `tag_lookup.py`; parses `APPROVED_DATA.md` itself and checks every input's sha256 and through-date; re-derives, from the raw files, every weekly decision (basket in force, every stock's tag from D20-D22 with its own lookup, k, n, FS, IN or OUT), the events, the targets, the 0-cost always-in NAV, the 0-cost and costed strategy NAVs and the comparators; end NAV within a relative 1e-9; exits 0 only if rows were compared and none failed; exits non-zero on a corrupted copy (a tag flipped, a decision flipped, a NAV scaled) |
| V2 | Point in time | Every decision reads Master SIGN rows dated on or before d and tags as of d with no snapshot dated after d; every trade is on a later session than its decision; counted, 0 violations out of a count > 0 |
| V3 | Regression to T06 | With the decision rule replaced by "IN iff all three BUY" the engine reproduces T06's daily NAV (`tests/T06/evidence/headline/daily_nav.csv`) on every shared session to 2026-10-22 (relative difference below 1e-12) and T06's decisions with 0 mismatches; the always-in series reproduces the published NAV within G0 (±0.25 pp/yr overall, ±0.5 pp every calendar year) |
| V4 | The two exact facts | (a) in 0 weeks is the rule OUT while the switch is IN; (b) FS is in [0, 1] and equals k ÷ n, with k and n integers and 5k ≥ 3n iff IN, in every week; (c) the weeks where the integer and float readings of FS ≥ 0.60 disagree are listed, and their count is printed |
| V5 | Tags are read every week | The number of weekly tag reads equals decisions × held stocks, and the engine's tag for a sample of 500 (stock, week) pairs per book equals a direct read of the D23 panels |

## Steps

| Step | Work | Output |
|---|---|---|
| 0 | `AA/tests/T10/`, `TRACKER.md`; this file is `PLAN.md`; Manu confirms C1-C4 and the open items | folder, tracker |
| 1 | Pre-registration `T10.md` §1-§3 frozen (sha256 recorded, `check_prereg.py`). Counts only, no price or return (`step1_counts.py`): per book, weekly decisions; weeks FS ≥ 0.60 against all-three-BUY; weeks the rule is IN and the switch OUT, and their stretches (lengths); exact-tie weeks (k ÷ n = 0.60) and how many the float formula reads differently; the distribution of n and of the share on; tag-source counts per holding-week. The expected result is declared in §2 before the counts are read into it | `T10.md`, `logs/step_1_counts.json` |
| 2 | Engine `analysis/t10_engine.py` (fork of `t07_engine.py`; inputs only through `approved_data.require()`; tags through `tag_lookup.py`); weekly FS, exact threshold, comparators, R1-R8, `--rerun`; writes `decisions.csv` (one row per weekly decision and book: date, n, k, FS, state, signals) and `events.csv` | engine, smoke run |
| 3 | Independent verifier (V1), a different agent | `analysis/verify_t10.py` |
| 4 | `analyse.py`, `fill_writeup.py` (must leave §1-§3 byte-identical, F-AA-M02), `report.py`, `check_page.py`, `run.sh` | scripts |
| 5 | `bash tests/T10/run.sh`; gates V1-V5 first | `evidence/<run>/` |
| 6 | `T10.md` §4-§8, the plain-words walkthrough (one decision by hand: the basket, each stock's tag, the signals, k, n, FS, the target, the trade price), the results page, `AA/ARTIFACTS.md`, `AA/CLAUDE.md`. Finding IDs from the counter at closing; the counter's next IDs are held by T07 and T08's pending findings, so T10 takes the ones after them | page, findings |

Pre-registration must also state what was already seen: Study 3 and Study 2 results on this production rule's family, T03-T08's switch results on the same window, and the 2021-26 live record of the AA books. None of it is out of sample.

## Declared expectation (written before any count)

1. Because T10 is IN whenever the switch is IN, it spends more time invested and will usually earn more in rising markets and fall further in the weeks the switch avoided. Whether C3 passes turns on whether the extra weeks were up or down.
2. For SCMO_0003 and SCMO_0007 (about 71% and 77% of weight in Small and below) the FS decision will be close to the Smallcap 100 signal alone; for SCMO_0029 (about 40% Small) it depends on the mix.
3. The sample is thin: the switch and the rule differ only in some of the 88 weeks where the three signals disagree, in at most 16 stretches shared by all four books. A PASS on C3 is therefore a consistency finding, and a FAIL is not strong evidence against the rule.

## Open items for Manu (defaults stand unless he says otherwise)

1. **Criteria C1-C4 and the 3-of-4 mark** as above. Calmar is used for C4 to avoid choosing a drawdown margin.
2. **R4 (tag error, 500 draws) and R5 (threshold curve)** are included as reported checks. Drop either if you want the test smaller.
3. **T07's rule as a descriptive comparator** is included because the engine is a fork; it is not T07's verdict. T07's headline run does not exist yet, so T10 does not wait for it.
4. **FS inputs are the three approved indices**, not Midcap 150 and Smallcap 250 (no approved signals). Say if you want that stated differently.
5. **The test number is T10** (T09 is in progress). Finding IDs are not assigned until closing.
