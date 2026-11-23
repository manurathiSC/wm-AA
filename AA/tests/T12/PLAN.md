# T12 Plan: T07's segment holding on the four real parents, 2014-09-01 -> 2019-01-02 (before the published NAVs)

**Written 2026-11-17. Nothing in this plan has been run and no file outside the plan has been written.** On approval it is copied verbatim to `AA/tests/T12/PLAN.md` before any engine code (AA/CLAUDE.md), and the frozen design becomes `T12.md` §1-§3 (Step 1), which wins over this plan where they differ. **Status: DRAFT, awaiting Manu's approval.**

## Context

T07 asked whether holding each parent stock only while its own band's index is BUY (Large: Nifty 100, Mid: Midcap 100, Small and below: Smallcap 100; the dropped weight goes 50/50 to GOLDBEES and cash) chooses *what to drop* better than a random drop of the same weight (N4.6, deciding; N4.8 beside), and whether it beats the whole-book switch. On 2019-01-02 -> 2026-10-30 it failed C1 (2 of 4), C2 (1 of 4) and C3 (0 of 4; −1.7 to −3.7 pp). It started in 2019 because the published NAVs start there and the tags (D20-D23) started 2018-01-31.

Two things changed on 2026-11-17: (1) **D20b/D23b approved** (Manu): market-cap rank tags from 2013-12-31; (2) **T11** (in progress, another thread) established that the parents' real baskets (D19, D05) and stock prices (D18) and GOLDBEES (D09) exist from 2014-07-01, and fixed the pre-2019 conventions (T0 = 2014-09-01, D26 calendar, D24b gold range). T11 put T07 out of scope only because tags started in 2018. **T12 = T07's rule, nulls and criteria on T11's window and conventions.** It adds 4.3 years the segment rule has never been run on with real holdings. T07 keeps its numbers.

## What is known before freezing (§2 quotes it)

- T07's results on 2019-26 are seen (all three criteria FAIL). Study 3 (2021-26) seen. T09 ran the whole-book timing on a proxy over 2011-19 (all criteria FAIL), so this window's signals and the whole-book switch's behaviour on a proxy are seen. T11's results (whole-book switch on these same parents and window) may be seen by the time T12 runs; §2 states whether they were.
- Counts already made, read-only (signals only, no price): 2014-07-01 -> 2018-12-31 has 235 weeks, all BUY 101, all SELL 77, **the three signals disagree in 57 weeks in 11 stretches** (7, 9, 6, 1, 3, 1, 1, 2, 8, 1, 18; the last runs into 2019 and is cut at the window end). T07 had 88 weeks in 16 stretches. Step 1 recounts from T0.
- Baskets: 21 per parent before 2019, quarterly, none skipped; 18 changes after T0 (T11's count).
- Expectation, declared: no basis for a direction; T07 failed on 2019-26, and the four books share one set of signals and events, so "3 of 4" is a consistency check.

## Tags: read only at the dates the rule acts (Manu: "add the relevant dates, not always")

- **Source.** `analysis/tag_lookup.py` (unchanged, reviewed), `TagLookup.from_files(D23b mcap_rank_panel_from_2013-12.csv, D23 membership_panel.csv, D22 symbology_changes.csv)`. Every window date is before the membership cutoff (2026-04-09), so **every tag is a rank tag**: the latest month-end market-cap snapshot on or before the date; no averaging.
- **When.** Tags are read only at **events** (T07 §3 step 4): T0, a signal event, a basket event. At an event on session s the tag is read **as of the information date = the D26 session immediately before s**, and never between events: a stock's band does not change by itself between events even if a new month-end snapshot appears. No snapshot dated after the information date is ever used (V2 counts this).
- **Consequence, disclosed.** A tag can be up to one month stale (month-end snapshots). The 2015-02-28 snapshot (a Saturday Budget session, not in D26) is first usable on 2015-03-02.
- **Unranked holdings.** The rule reads them "Small and below" and counts them. Known: DHFL (listed as PIRAMALFIN) in SCMO_0010 2017-06-01 -> 2017-11-29 (ranks 132-169, so truly Mid). Hexaware's gap (SCMO_0029, 2014-03 -> 05) is before T0. Step 1 lists every unranked holding at every event; **R6** reruns with DHFL read as Mid.
- **A stored tag table** (descriptive, Step 1, reads no price): `tests/T12/evidence/basket_tags_2014-09_2019-01.csv`: one row per parent × basket × stock, tagged as of the information date of the basket's first trade session (its "relevant date"), with weight, rank, n_ranked, band, snapshot used, via. The engine's own tags at every event are in `event_stocks.csv` (as T07).

## The T12 rule (frozen in §3; = T07 §3 with T11's window and calendar)

- **Window.** T0 = **2014-09-01** (first basket effective on or after 2014-07-01; same for all four parents) -> END = **2019-01-02** (the first date of the published NAVs; no overlap with T07). All four parents start 2014-09-01.
- **Calendar.** D26 sessions (2017-10-19 Muhurat: no D18 bars; last-close stand-in as T11, counted and disclosed). Decision dates: T0, then the last D26 session of each ISO week. The decision at 2019-01-02 is made, not traded.
- **Signals.** D03 Masters, latest row on or before the decision date; Smallcap 100 rows from 2011-11-25 only (rule 7; not binding).
- **Events, tags, targets, execution, NAV, statistics:** T07 §3 steps 4-9 exactly, with weights renormalised to 1 as T06/T07 (T07 amendment 2), and T07 amendment 3 (a basket change while no stock is held: nothing traded, the new basket's tags become the current tags). 10.4 bps a side (20.8 round trip primary; 0 and 50 robustness); T0 position free; no sale at the end.
- **GOLDBEES fill:** de-spiked OHLC4 with MCX range from **D24b's daily file** (as T11; D12 starts 2015-02-02).
- **Prices:** D18 with `price_corrections.csv`.

## Hypotheses, nulls, criteria (T07 §2 unchanged except numbers)

- **C1 selection:** after-cost CAGR percentile vs N4.6 ≥ 90 in ≥ 3 of 4 books. **C2 protection:** max-drawdown percentile vs N4.6 ≥ 90 in ≥ 3 of 4. **C3 increment:** rule CAGR − whole-book switch CAGR > 0 in ≥ 3 of 4.
- **N4.6** (decides): at each event a uniform random subset of the held stocks with |Σw − D| ≤ τ (τ = half the smallest weight), exact enumeration (n ≤ 16). **N4.8** beside: persistent label permutation with the rule's per-band counts. 2,000 draws per book, cost, null.
- **Seeds:** first element **15** (3-14 taken: T03-T11 engines, T10's verifier uses 13, T11 uses 14; Step 1 re-checks). N4.6 `[15, 7, draw_id, book_no]`, N4.8 `[15, 8, draw_id, book_no]`, V6 `[15, 9, shift, book_no]`, R5 `[15, 5, draw_id, book_no]`.
- Percentile, p-value, MDE (2.8 × null SD beside every FAIL), calibration ratio, secondary statistics: as T07.
- **Reportability:** ≥ 5 disagreement stretches and ≥ 6 events with 0 < equity share < 1 per book; else NOT REPORTABLE. **Stop rule:** if Step 1 counts fewer than 5 stretches in the window, stop and ask Manu.
- **Outcome map:** T07's. Read beside T07: if C1 passes here where it failed in 2019-26, the tag effect is window-specific.

## Gates (any failure: nothing below is read)

- **V1** independent verifier `analysis/verify_t12.py` (a different agent; written from `logs/verifier_spec.md`; never reads the engine or `tag_lookup.py`; own tag lookup from D23b/D22, checked against `event_stocks.csv`; re-derives decisions, events, every tag, targets, always-in and strategy NAVs at every cost, and a sample of draws of both nulls; corrupted copy must exit non-zero).
- **V2** point in time: decisions read Master rows on or before them; every tag uses a snapshot dated on or before its information date, which is before its trade session; trades after decisions. Counted, 0 violations out of > 0.
- **V3** nulls hold their tables (T07's V3).
- **V4** regression and identities (replaces T07's G0, which needs a published NAV):
  - (a) `--calendar d17`, T0 = 2019-01-02, END = 2019-12-31: rule mode reproduces **T07's stored `daily_nav.csv`** and whole-book mode reproduces **T06's**, to 1e-12 (D23b equals D23 on every 2019 snapshot, so tags are identical; Step 2 confirms the gold range read for 2019 matches what T07 read, else stop and ask);
  - (b) whole-book mode on the T12 window equals **T11 Part A's** stored strategy NAV, and always-in equals T11's hold-the-parent NAV, to 1e-12, **if T11's headline exists when T12 runs** (else reported as not run; not a substitute for (a));
  - (c) AST diff of shared functions against `t07_engine.py` lists only expected changes;
  - (d) tags at every event equal a direct read of D23b.
- **V5** sampler exact (T07's V5).
- **V6** negative control: 100 circular shifts of the joint three-signal matrix (26 ≤ k ≤ n − 26), 200 N4.6 draws each, pass if at most 17 of 100 reach the 90th percentile (T07's amended rule, fixed before any result here).
- **V7** oracle ≥ 99th percentile in every book.

## Robustness (reported; decide a finding's status, not the verdicts)

- **R1** C1, C2 at 0 and 50 bps; trades and cost of the rule and null medians.
- **R2** sub-window from 2015-01-02 (as T11's R3), own events and null.
- **R3** LIQUIDCASE cash leg.
- **R4** agreement of N4.6 and N4.8.
- **R5** tag error: rank tags replaced with probability 7.93% (D23 review's 92.07%; untested before 2026, disclosed), 500 draws.
- **R6** DHFL read as Mid (and any other unranked holding Step 1 finds, mapped by quote_id as the D20b review identified), C1 and C3 rerun.
- **R7** price-quality sensitivity, as T11's R7 (flagged price steps and manual-export stocks).
- **Descriptive:** T07's 2019-26 percentiles beside T12's; T09 and T11 results as context (different rule or portfolio).

## Data (APPROVED rows only; `python data/check_approved_data.py` first and at the top of `run.sh`)

| Role | File |
|---|---|
| Stock OHLC (D18) | `data/holdings_matrix/SCMO_<p>_ohlc.csv`, `price_corrections.csv` |
| Baskets (D19, D05) | `*_holding_weight_matrix.csv`, `*_columns.csv`, `*_holding_weight_sources.csv`; `Historical Data/frozen_2026-09-25/Rebalance_history/` |
| Calendar (D26) | `Historical Data/extended_2026-11-12/index_daily_pre2019/nse_trading_days.csv` |
| Signals (D03) | `Historical Data/extended_2026-10-30/Master/Master_{Nifty100,MC100,SC100}.xlsx` |
| Tags (D23b, D23 membership, D22) | `Historical Data/extended_2026-11-17/mcap_universe_from_2013-12/mcap_rank_panel_from_2013-12.csv`; `extended_2026-11-12/tags/membership_panel.csv`; `extended_2026-11-12/symbology/symbology_changes.csv` |
| GOLDBEES (D09), MCX range (D24b daily) | `analysis/cache/why_gold_ohlc_eikon_extended_2026-11-04.parquet`; `Historical Data/extended_2026-11-12/MAUc1_from_2003/mauc1_daily_clean_extended.csv` |
| Cash (D11) | `LBES_Adjusted_Price_data_extended_2026-11-05.csv` (R3: `liquidEtfFinal_extended_2026-11-05.csv`) |
| V4(a) only | D17 published NAV; `tests/T07/evidence/headline/daily_nav.csv`; `tests/T06/evidence/headline/daily_nav.csv` |

Caveats on the page (from the two tag reviews and T11's coverage review): tags 100% rank-based and untested before 2026; all market-cap rows back-filled (2026-01-03); identifiers are today's; month-stale tags; DHFL unranked; no published NAV validates any rebuild before 2019; manual Eikon exports (HEXT, PIRAMALFIN) and unchecked price steps; every Master row before 2021 is a production backfill; LBES source unrecorded.

## Engine: fork `analysis/t07_engine.py` -> `analysis/t12_engine.py` (copy, never import T07 or T11)

1. Window, calendar, T0, END, last-close stand-in for 2017-10-19, D24b gold range: take from `analysis/t11_engine.py` (its `common()` and calendar code).
2. Remove T07's D17 calendar, G0 against the published NAV, `LIVE_START` (R2 live) and R6 (AA books).
3. Tag reader: `TagLookup.from_files` on D23b's combined panel; the call site (information date of each event) is unchanged from T07.
4. Add `--calendar d17` for V4(a); add the optional T11 cross-check V4(b).
5. Seeds with first element 15. Outputs as T07 plus `basket_tags_2014-09_2019-01.csv`.

## Steps (T07's, with its tracker and hand-off rules)

0. Copy this plan verbatim to `tests/T12/PLAN.md`; create `TRACKER.md` from T11's skeleton.
1. **Pre-registration:** `step1_counts.py` (fork of T07's; signals, calendar, baskets and tags only, no price): decisions, disagreement weeks and stretches, coarse event bounds, partial-equity events, band mix per book, unranked holdings at every event, the basket tag table. Write `T12.md` §1-§3 (plain-words walkthrough included), freeze with `check_prereg.py`.
2. **Engine** `analysis/t12_engine.py`; smoke `--run smoke --draws 20 --quick` exits 0 with V2-V5 passing.
3. **Independent verifier** `analysis/verify_t12.py` (fork `verify_t07.py`; a different agent; never reads the engine).
4. **Test scripts** forked from `tests/T07/` (`analyse.py`, `fill_writeup.py`, `report.py`, `check_page.py`, `rerun_draw.py`, `episodes.py`, `run.sh`). Steps 2-4 in parallel after Step 1.
5. **Run** `bash tests/T12/run.sh` -> `evidence/headline/`.
6. **Results and close:** `T12.md` §4-§8, `METHODS.md`, `evidence/report.html`; finding IDs from the counter only at closing (after T07, T08, T10, T09, T11 take theirs); update `AA/CLAUDE.md`.

## Decision points still open (defaults in brackets)

1. Window [2014-09-01 -> 2019-01-02, as T11]. Alternative: one run 2014-09 -> 2026-10 on a stitched calendar (D26 then D17); not proposed, since 2019-26 repeats T07.
2. DHFL: [read as "Small and below" per the approved rule, counted; R6 as Mid]. Changing the identity rule in `tag_lookup.py` would need its own review.
3. Close T07 (§5-§8, finding IDs) before T12 Step 6 [yes; it does not block Steps 0-5].

## Verification (end to end)

1. `python data/check_approved_data.py` exits 0; `inputs.csv` lists every file with sha256 and approved row.
2. `python tests/T12/check_prereg.py` confirms §1-§3 unchanged; `step1_counts.py` equals the engine's counts.
3. `python -I analysis/tag_lookup.py --selftest` passes; V2's tag count > 0 with 0 violations; V4(d) 0 mismatches.
4. Smoke run, then `verify_t12.py` on it (exit 0, corruptions caught), then `bash tests/T12/run.sh`; `analyse.py` exits 1 on any failed gate; `check_page.py` 0 failures.
5. V4(a): the 2019 slice reproduces T07 and T06 to 1e-12.
