# T07 Plan: does holding each stock only while its own segment index is BUY choose *what to hold* better than a random exclusion of the same weight?

**Written 2026-11-09. Nothing in this plan has been run, and no data has been read for it.** It re-does Study 3 (`AA/analysis/evidence/segment_v2/`, page 3 in `AA/ARTIFACTS.md`) to the standard of T03–T06. **This file was written in chat, not saved from plan mode, so it is not a verbatim copy of an approved plan.** The frozen design will be `T07.md` §1–§3 (Step 1), and it wins where the two differ. Format follows `AA/tests/T06/PLAN_v2.md`.

## Decisions taken (Manu, 2026-11-09)

1. **Sleeve: 50% GOLDBEES + 50% cash (LBES-adjusted level), fixed. No other sleeve.** No all-cash sleeve, no gold-trend split, no static-mix sleeve variants. (Study 3's G2/G3 are not carried over.)
2. **Segments use the three approved index signals** (D03): Large → Nifty 100, Mid → Midcap 100, Small and Micro → Smallcap 100. No refresh to Midcap 150 / Smallcap 250 / Microcap 250.
3. **Tags need a point-in-time market-cap rank file, which is not approved today.** Manu approves a one-time rank file; it is registered in `AA/data/APPROVED_DATA.md` with a sha256 before Step 1. T07 reads no Postgres table directly. **Until it is approved, T07 does not start.**
4. **Old Study 3 page:** kept as the record of Study 3 and marked "superseded by T07" in `ARTIFACTS.md`; the T07 page gets its own link.
5. **Books: the four parents only** (SCMO_0003, 0007, 0010, 0029; 2019 onward; D18/D19 exist only for them). The AA books' published NAVs (D15) are used only as a NAV-level cross-check on the live window (2021-11 →).

## Why Study 3 is being redone

| Study 3 (Sept 2026) | T07 |
|---|---|
| Hash in `audit.json`; no frozen §1–§3, no `check_prereg.py` | Frozen `T07.md` §1–§3, sha256, `check_prereg.py` |
| `verify_v2.py`, written by the engine's author | Independent verifier written from a spec, without reading the engine |
| No page check | `check_page.py` re-derives every number and hover array |
| G4 circular signal shift (about 236 draws), 70% share-positive rule; one sign test on D | Nulls matched to the claim, 2,000 draws, percentile and p per AGENT.md N6.1, pass marks fixed in advance |
| Nothing checks that the null behaves | N6.7 controls (negative, oracle, planted at the MDE) and the N6.6 calibration ratio |
| Files that are not approved; several price-source repairs | Only APPROVED rows, enforced in code (`approved_data.require()`), `inputs.csv` hashes |
| No finding IDs | `F-AA-S08`, `F-AA-M07`, `F-AA-D16` onward |

## Context

**The rule (as Study 3, on three indices).** At each event (a flip of any of the three signals, a parent rebalance, or the first review), tag every holding by its point-in-time market-cap band. Keep it at its parent weight only while its band's index is BUY; otherwise move its weight to the 50/50 sleeve. Kept stocks are **not** renormalised (equity exposure falls by exactly the weight dropped). All BUY = the parent; all SELL = 100% sleeve (the whole-book rule). Between events the book drifts.

**Comparator:** the whole-book three-index switch of T03–T06 (parent only when all three are BUY, else 100% sleeve), on identical prices, fills, costs and sleeve.

**What the segment rule can add.** The two rules differ only in weeks when the three signals disagree. Study 3 saw 12–14 flips per index and the same 48 events driving all four books, so the number of such weeks may be small. **T07 counts them first (counts only, no returns, as T03 did for spells) and registers the result before freezing.** If too few, the window is NOT REPORTABLE or the power note says what edge is detectable.

**Mechanics (T03's, unchanged):** weekly decision on the last published-NAV session of each ISO week; next-session OHLC4 fills; 10.4 bps a side (20.8 round trip); cash = LBES extended; price return.

### Data (all from `AA/data/APPROVED_DATA.md`; paths relative to `AA/`)

| Role | File | Through |
|---|---|---|
| Calendar and published NAV, parents (D17) | `Historical Data/extended_2026-11-06/published_nav/SCMO_<p>.csv` | 2026-11-06 |
| AA books' NAV, cross-check only (D15) | `Historical Data/extended_2026-11-06/published_nav/SCMO_004x.csv` | 2026-11-06 |
| Stock OHLC and corrections (D18) | `data/holdings_matrix/SCMO_<p>_ohlc.csv`, `price_corrections.csv` | 2026-11-04 |
| Basket weights, trace and columns (D19), history (D05) | `data/holdings_matrix/…`, `Historical Data/frozen_2026-09-25/Rebalance_history/…` | 2026-09-10 / 2026-09-16 |
| Signals (D03, extended) | `Historical Data/extended_2026-10-30/Master/Master_{Nifty100,MC100,SC100}.xlsx` | 2026-10-30 |
| GOLDBEES (D09, extended); de-spike (D12) | `analysis/cache/why_gold_ohlc_eikon_extended_2026-11-04.parquet`; `…/mauc1_daily_clean.csv` | 2026-11-04; 2026-09-28 |
| Cash (D11, extended) | `Historical Data/LBES_Adjusted_Price_data_extended_2026-11-05.csv` | 2026-11-05 |
| **Market-cap rank file (new, PENDING Manu)** | to be registered | to be registered |

**Window end** is the earliest through-date of the roles read: D03, **2026-10-30**. The newest basket (2026-09-10 / 09-16) is inside the window; the next rebalance is expected about mid-December, so a later window must be re-checked.

**Caveats to disclose:** LBES rows before 2026-08-10 have no recorded source (F-AA-D09); the rows after run about 0.5 pp/yr rich (F-AA-D13); tags before the rank file's start, and tag accuracy, can only be judged against the rank file itself (membership snapshots are not approved, so Study 3's classification-error model cannot be re-estimated); decisions before 2021-11 are a production backfill.

## T07 rule and nulls (the specification Step 1 will freeze)

1. **Bands (to fix in Step 1 before freezing, with their count of holdings per band):** Large = ranks 1–100, Mid = 101–250, Small and Micro = rank above 250 (all → Smallcap 100). Unranked names read Smallcap 100. State how many holdings fall in each band per book.
2. **Deciding null, N4.6 size-matched random exclusion.** At every event, among the holdings that are held that week, exclude a random set with the **same total weight** as the segments in SELL (to within a stated tolerance, by a stated sampler), send it to the 50/50 sleeve, and run the same engine. Holds: weight excluded, sleeve, calendar, execution, cost. Randomises: *which* stocks. Redrawn only at events (as the rule). 2,000 draws per book.
3. **Companion null, N4.8 tag permutation.** Permute band labels across that week's holdings, keeping the count and weight per band; permute in blocks per stock because tags persist across weeks (AGENT.md N4.8 persistence note). Reported beside the deciding null, not a criterion.
4. **Reference only (not a criterion): timing.** The whole-book comparator's own percentile against N4.9/N4.10 on this window, so the segment rule is read as an *increment* over timing.
5. **Statistics and criteria (after 20.8 bps, per book, 4 books):**
   - **C1** the segment rule's CAGR percentile against N4.6 ≥ 90 in at least 3 of 4 books;
   - **C2** maximum-drawdown percentile ≥ 90 in at least 3 of 4 books;
   - **C3 (increment)** the segment rule's CAGR minus the whole-book rule's is positive in at least 3 of 4 books, **and** both lie above the null's median difference. (Replaces Study 3's G1; the pass mark is fixed before the run.)
   Percentile = (draws worse + 0.5 × ties) ÷ draws × 100; p = (1 + draws at least as good) ÷ (draws + 1) (N6.1). Report secondary statistics (Ulcer index, days ≥ 10% below peak, Calmar, volatility).
6. **Judging extras (N6):** the calibration ratio (N6.6) beside every percentile; the edge (N6.4) before and after cost (N6.5); the MDE and the number of disagreement weeks (the independent unit) beside every FAIL.
7. **Controls (N6.7):** K ≥ 100 information-free signals run through the real code path (negative control: the share clearing the pass mark must be near its nominal rate); an oracle positive control; a planted-edge control at the MDE.
8. **Robustness (reported; they decide a finding's status, not the verdicts):** R1 C1 and C2 at 0 and 50 bps; R2 live window (2021-11 →) with its own count of disagreement weeks; R3 LIQUIDCASE cash (`liquidEtfFinal_extended`); R4 agreement of N4.6 and N4.8 percentiles; R5 tag-error injection (relabel at a stated rate, since an error model cannot be estimated from approved data); R6 NAV-level cross-check of the live window against the AA books' published NAVs. Settings that vary are judged against the best-of-sweep null (N6.8).
9. **Outcome map (fixed before any run):**

| Pattern | Conclusion |
|---|---|
| C1, C2 and C3 pass against N4.6 (and N4.8 agrees) | Segment tagging picks what to drop better than chance, and improves on the whole-book switch |
| Passes timing, fails N4.6 | The edge is timing, not segmentation |
| Fails both | Study 3's rejection stands, now on a matched null |
| Disagreement weeks too few | NOT REPORTABLE; state the MDE |
| a V gate fails | Nothing is read. Fix and rerun as a new run directory |

10. **Multiplicity.** One rule. Two nulls, declared. The pass marks do not change with the number of books. T07 alone cannot upgrade Study 3's status.
11. **Disclosures (go in §2):** the rule has been seen (Study 3); tags are rank-based and approximate; the window includes the data Study 3 used.

## Steps (same shape as T06; tracker `AA/tests/T07/TRACKER.md`)

| Step | Work | Output |
|---|---|---|
| 0 | Manu approves the market-cap rank file; an agent registers it per the procedure at the bottom of `APPROVED_DATA.md` and runs `python data/check_approved_data.py` (must exit 0) | row in `APPROVED_DATA.md` |
| 1 | Pre-registration. Count the disagreement weeks, the band sizes and the windows' feasibility (counts only). Freeze `T07.md` §1–§3 with its sha256; create `check_prereg.py`, `TRACKER.md`, `logs/`; copy this plan's decisions verbatim | `T07.md`, `check_prereg.py` |
| 2 | Engine `AA/analysis/t07_engine.py`: a fork of `t06_engine.py` plus the segment logic from `segment_v2.py`. Every input through `approved_data.require()`; `inputs.csv` with sha256s. Self-checks: V3 (nulls hold their table: weight excluded, counts, events), V4 (regression to Study 3's `sleeve` and the whole-book comparator on the overlap, with a stated tolerance, and to T06's decisions), V5 (sampler self-test) | engine, `smoke` run |
| 3 | Independent verifier `AA/analysis/verify_t07.py`, written from a spec in `logs/verifier_spec.md` **without reading the engine**: parses `APPROVED_DATA.md` itself, re-derives decisions, tags and targets, re-simulates sample draws, recomputes percentiles, and must catch a corrupted copy | verifier |
| 4 | Scripts in `AA/tests/T07/`: `analyse.py`, `fill_writeup.py` (must leave §1–§3 byte-identical, F-AA-M02), `report.py` (every chart hoverable per AGENT.md R10; one backtest end to end including one N4.6 draw; the held/randomised table), `check_page.py`, `rerun_draw.py`, `run.sh` | scripts |
| 5 | `bash tests/T07/run.sh` (data check, prereg check, engine, verifier, analyse, fill, report, page check) | `evidence/headline/`, `report.html` |
| 6 | Read `analysis.log`; fill §4–§8; findings with IDs from the counter in `AA/CLAUDE.md` at the time of closing; update `AA/CLAUDE.md` (current test, counters), `AA/ARTIFACTS.md` (page 3 marked superseded, T07 added), and `AGENT.md` only if N4.6/N4.8 need a segment-specific recipe | write-up |

Step 3 is best done by an agent that did not write Step 2. Steps 2, 3 and 4 depend only on Step 1 and can run in parallel; Step 5 needs all three.

## Edge cases

1. **Stop and ask Manu** if any input is stale, missing or `PENDING`, a sha256 does not match, or the rank file's coverage does not reach the window.
2. **SCMO_0007 starts 2019-01-04**: its week counts come from its own series.
3. **Tags are rebuilt only at events**; a stock crossing a rank boundary never trades on its own.
4. **Kept weights are not renormalised.** Row sums are 0.9996–1.0005 in D19; the sleeve is the residual `1 − Σ kept`.
5. **A null draw can equal the rule**; ties count as in N6.1.
6. **The last decision week is partial** (the decision on the last session is made but not traded).
7. **`fill_writeup.py` must not touch §1–§3.** Run `check_prereg.py` straight after.
8. **No data may be edited, extended, rebuilt or re-fetched by the test.**

## Open items

- The market-cap rank file: its source (Postgres `mcap_based_universe`, monthly), start date, and whether Manu also wants the Postgres membership snapshots approved (needed only if a tag-error model is to be estimated; otherwise R5 uses a stated rate).
- Band cut-offs (item 1) are provisional until Step 1.
- Tolerance and sampler for "same total weight" in N4.6 (to fix in Step 1 after the band sizes are known).
