# T12 Progress Tracker

**Overall status: IN PROGRESS (2026-11-17); Steps 0 and 1 done, Steps 2-4 next (can run in parallel).** Plan: `AA/tests/T12/PLAN.md` (approved by Manu 2026-11-17, copied verbatim from `C:\Users\manur\.claude\plans\giggly-zooming-swing.md`, 14,028 bytes, sha256 `B318E7BFFD9F92E8796272F4EC7BB1543F303F803925A3C743E1EA3CF6CAC553`; its header still reads "DRAFT, awaiting approval" because the copy is verbatim; the frozen design is `T12.md` §1–§3 and wins where they differ). Read this file before starting any step; update it when you finish.
Status values: `NOT_STARTED` → `IN_PROGRESS` → `DONE` (or `DONE_WITH_NOTES`).
**Data boundary:** read `AA/data/APPROVED_DATA.md`; use only its `APPROVED` rows; run `python data/check_approved_data.py` first; if anything is stale, missing or unclear, stop and ask Manu.
**What T12 is:** T07's segment-holding rule, nulls (N4.6 decides, N4.8 beside), criteria C1-C3 and gates V1-V7 on the four real parents (SCMO_0003, 0007, 0010, 0029), window **2014-09-01 → 2019-01-02** (T11's window and D26 calendar). Tags from the D23b rank panel (`Historical Data/extended_2026-11-17/mcap_universe_from_2013-12/mcap_rank_panel_from_2013-12.csv`) through the unchanged `analysis/tag_lookup.py`, read only at events, as of the session before each trade session. No published NAV before 2019: V4 is a regression on the 2019 slice against T07 and T06, plus a cross-check against T11 if its headline exists.
**Stop rule:** a book and window with fewer than 5 disagreement stretches or fewer than 6 partial-equity events is NOT REPORTABLE; if that happens for the full window, stop and ask Manu.

| Step | Status | Blocked by | Agent / Date | Output summary |
|---|---|---|---|---|
| 0 Plan copied, tracker created | DONE | — | Claude / 2026-11-17 | `PLAN.md` copied verbatim with `Copy-Item` (source and copy sha256 equal), this file created |
| 1 Pre-registration | DONE_WITH_NOTES | 0 | Claude / 2026-11-17 | **`T12.md` §1–§3 written and frozen, sha256 `3c361f4bbfd550904df7552635a3cdcd8ea53878b9b1d615a454b13fba5b7407`** (`python tests/T12/check_prereg.py` verifies). Counts (`step1_counts.py`, no price read; `logs/step_1_counts.json`): `check_approved_data.py` exit 0 (67 approved rows); T0 = 2014-09-01 asserted for all four parents; 1,070 D26 sessions, 228 decisions, first state BBB; 57 disagreement weeks in 11 stretches (7, 9, 6, 1, 3, 1, 1, 2, 8, 1, 18); coarse events ≤ 45 (17 in disagreement weeks); partial-equity disagreement weeks 52 / 56 / 53 / 38; R2 (from 2015-01-02) 47 weeks in 10 stretches. Basket tag table `evidence/basket_tags_2014-09_2019-01.csv` (946 rows; 643 Small and below, 190 Mid, 113 Large, 3 unranked). Seed prefix 15 checked unused |
| 2 Engine | DONE_WITH_NOTES | 1 | Claude / 2026-11-17 | `analysis/t12_engine.py` (fork of `t07_engine.py` + `t11_engine.py`, copied, not imported); log `logs/step_2_log.md`. Smoke (`--run smoke --draws 20 --quick`) exit 0, 8 s. Four-book scratch run (100 draws, V6, V7, R5 500) exit 0, 54-80 s: V2-V7 pass. **V4(a) max rel diff 4.4e-16** (2.2e-16 in three books) against T07's and T06's stored 2019 NAVs. V4(b) 0.0 against T11's headline (it appeared during Step 2). V4(c) 19 required definitions AST-identical. V4(d) 4,630 rows, 0 mismatches. V6 13/3/6/1 of 100 (limit 17). V7 100 in all four books. Engine events ≤ coarse bounds (Step 1 attribution). No trade on any stand-in session. R7: PURVA 2017-10-23 only. **Open: R6's frozen quote_ids are today's listings and never rank in the window, so R6 as frozen is vacuous; `--r6-ids review` uses the old ones (Manu's decision).** Headline estimate 3-5 min |
| 3 Independent verifier | DONE_WITH_NOTES | 1 | Claude / 2026-11-17 | `analysis/verify_t12.py` (fork of `verify_t07.py`; engines, `tag_lookup.py` and `approved_data.py` not opened, nothing imported); log `logs/step_3_log.md`. 18 checks plus C-corrupt (7 corruptions). **C-regress:** my rule = T07's stored 2019 NAV (max rel 7.0e-16) and my whole book = T06's (6.8e-16) on every D17 session to 2019-12-31; V4(b) whole book / always-in = T11's headline, 1.5e-15. Own ranking of raw D20b/D20 market caps = D23b panel (61 snapshots, 94,844 rows, 0 mismatches). **Mock** (4 books, 20 draws): clean 640,312 comparisons, 0 failures, exit 0; exit 1 on each corruption and on the combined copy; the frozen-ids mock passes under `--r6-ids frozen`. **Engine evidence:** smoke 149,944 comparisons, 0 failures, exit 0; scratch4 (4 books, frozen ids) 1,916,356, 0 failures, exit 0; r6test (review ids) 0 failures, exit 0. `check_approved_data.py` exit 0 before and after |
| 4 Test scripts | DONE_WITH_NOTES | 1 | Claude / 2026-11-17 | `analyse.py`, `fill_writeup.py`, `report.py`, `check_page.py`, `rerun_draw.py`, `episodes.py` (now engine-free), `run.sh` (forks of T07's; nothing imported from T07, the engine, the verifier or `tag_lookup.py`); log `logs/step_4_log.md`. **Synthetic set** (scratch, 4 books × 200 draws, real calendar/signals/baskets/tags/prices): every script exits 0, `check_page.py` 1,551 checks, 0 failures. **Engine `scratch4`** (copied to scratch; verifier exit 0): every script exits 0, `check_page.py` 1,539 checks, 0 failures, incl. the tag of all 4,630 event rows re-derived from D23b and R7 re-derived from D18 + D19. `r6test` and `smoke` fail only V6/V7 (not run there). **Planted corruptions: 25 of 25 caught** (one printed-number case was missed at first and fixed by checking the four key tables row by row); a clean copy passes. `fill_writeup.py` on copies of `T12.md`: header + §1–§3 byte-identical, §5–§8 identical, `check_prereg.py` OK, idempotent, refuses on 3 broken inputs. Browser: 100 chart hovers per page, light and dark, 1,200 and 390 px, 0 problems. **`run.sh` needs `R6_IDS=review|frozen`** (passed to engine and verifier) |
| 5 Run and gate | NOT_STARTED | 2, 3, 4 | — | `bash tests/T12/run.sh` |
| 6 Analyse, report, write-up | NOT_STARTED | 5 | — | `T12.md` §4–§8, `evidence/report.html`, `METHODS.md`; finding IDs from the counter in `AA/CLAUDE.md` at closing (after T07, T08, T10, T09, T11 take theirs); update `AA/CLAUDE.md` |

## Step-level notes

- **Step 1 (2026-11-17), deviations from `PLAN.md`.** (a) **Two unranked holdings, not one:** besides DHFL (PIRAMALFIN, INE202B01038, SCMO_0010 baskets 2017-06-01 and 2017-09-01, 26 decision weeks), Hexaware (HEXT, INE093A01041) is unranked in SCMO_0007's 2018-02-28 basket (13 decision weeks; the gap the D20b review noted under D23 too). R6 in §2 reads both by their other quote_id (Hexaware 236783369047, DHFL 236798428431). (b) **R7 is a rule on D18** (every held stock-day with an absolute one-day close move ≥ 20%, as T11's amended R7), not the plan's list of days taken from unapproved files. (c) Seeds are listed in full in §3 steps 11-12 and the calibration bootstrap (`[15, 20, book_no]`).
- **⚠ AFFECTS STEP 2:** the engine is T07's with T11's window: calendar = D26 from 2014-09-01 to 2019-01-02; the basket effective 2014-09-01 bought at T0's OHLC4 and scaled to NAV 1.000 at T0's close (T11's E4); 2017-10-19 no D18 bar and 2016-10-30 no GOLDBEES bar (previous close stand-ins, counted); GOLDBEES de-spike range from D24b's daily file; `TagLookup.from_files` on the D23b combined rank panel, D23 membership panel, D22 symbology; tags read only at events as of the information date (unchanged from T07). Remove T07's D17 calendar, G0, `LIVE_START`/live window and R6 (AA books); add R2 (2015-01-02 sub-window), the new R6 (unranked holdings by their other quote_id) and R7. Keep a `--calendar d17` mode for V4(a) (T0 = each book's first D17 date, end 2019-12-31, against `tests/T07/evidence/headline/daily_nav.csv` and `tests/T06/evidence/headline/daily_nav.csv`). V4(b) against T11's headline only if `tests/T11/evidence/headline/` exists; else report "not run".
- **⚠ AFFECTS STEP 3:** the verifier's own tag lookup must handle the combined D23b panel (rank only in this window) and must list the two unranked holdings; work from `T12.md` §1–§3 and a written `logs/verifier_spec.md`, never from the engine.
- **⚠ AFFECTS STEP 4:** there is no live window and no R6 (AA books) on the page; R2 is the 2015 sub-window; the "hold the parent" curve is a rebuild with no published NAV and every chart of it must say so.
- **Step 2 (2026-11-17).** Engine built and gated on a smoke run and a four-book 100-draw scratch run (`evidence/smoke`, `evidence/scratch4`, `evidence/r6test`; scratch, not evidence). Full detail, readings and the "⚠ CONTRACT CHANGES" list are in `logs/step_2_log.md`.
  - **⚠ DECISION FOR MANU (before Step 5): R6's quote_ids.** T12.md §2 names 236783369047 (Hexaware) and 236798428431 (DHFL). In D23b these have rows only from 2025-02-28 and 2025-11-28: they are today's listings. The D20b review's old listings, Hexaware 55837401060 and DHFL 55837400085, rank Mid in the window. With the frozen ids R6 re-tags nothing: `full_r6` equals `full` and `r6_links.csv` is empty. The engine runs the frozen ids by default; `--r6-ids review` runs the old ones (tested: 6 event rows re-tagged Mid, all gates pass). T12.md was not edited.
- **⚠ AFFECTS STEP 3:**
  - R6 depends on Manu's decision above. With the frozen ids, expect no `rank_linked` row and `r6_links.csv` header-only. With `--r6-ids review`, link 55837401060 / 55837400085.
  - Cash `liq` is LIQUIDCASE as-of over the whole window. T07's 2024-01-24 splice is outside the window.
  - V4(b) compares at relative 1e-12 against `tests/T11/evidence/headline/daily_nav.csv` (`strategy_fixed50`, `hold_parent`), which now exists.
  - `event_stocks.csv` `listed_weight` is renormalised.
  - EV2 (a basket change while nothing is held) produces one signal event without a triple change: SCMO_0010 on 2018-06-04.
- **⚠ AFFECTS STEP 4:**
  - `audit.json` `events_vs_section2_coarse_counts` has two in-disagreement counts. Compare `..._step1_attribution` with the §2 bound; under T07's attribution SCMO_0007's full window shows 19 against 17.
  - `r6_links.csv` has an extra `event_no` column.
  - `audit.json` has `r6` (ids used, rows re-tagged, misses) and `t11_headline_seen` (true from now on). §4 must say T11's NAVs were compared by the engine, not read.
  - Engine CLI as the contract, plus `--r6-ids frozen|review`.
- **⚠ AFFECTS STEP 5:**
  - Headline `python -I analysis/t12_engine.py --run headline` (add `--r6-ids review` only if Manu so decides); about 3-5 minutes wall on 4 workers.
  - V4(b) will run, because T11's headline exists.
  - Delete or ignore the scratch folders `evidence/scratch4` and `evidence/r6test`.

- **Step 3 (2026-11-17).** Verifier written and tested; checks, results and readings are in `logs/step_3_log.md`.
  - **R6:** `--r6-ids review|frozen` (alias `literal`), default **review** (old ids 55837401060 / 55837400085, coordinator's instruction pending Manu). Works with either.
  - **r2's T0:** `--r2-init auto` picks drift or fresh from `stats.csv`; the engine's scratch4 confirms drift.
  - **R7:** the "held" reading that matches the evidence is reported; only PURVA 2017-10-23 is flagged in the window.
- **⚠ AFFECTS STEP 5:**
  - Run `python -I analysis/verify_t12.py --evidence tests/T12/evidence/headline --r6-ids <same as the engine>`. The engine defaults to `frozen`, the verifier to `review`; mismatched ids fail `full_r6` by design.
  - The self-test writes corrupted copies to the scratch directory (`--corrupt-dir` to change it).
  - A headline run requires 2,000 draws per key, every window, `controls_oracle.json`, `regression.json` and `audit.json`.
  - V6, R5, V5(a) and V4(c) are not re-derived (as in T07).
- **⚠ AFFECTS STEP 4:** the verifier's output is `evidence/<run>/verify_t12.json` (per check: `compared`, `failed`, `missing`, `worst_rel`, `notes`, `parts`; plus `v4a`, `percentiles`, `selftest`, `exit_ok`).

- **Step 4 (2026-11-17).** Scripts written and tested; details, tests and readings in `logs/step_4_log.md`.
  - The page puts the caveats first (rank tags back-filled 2026-01-03, untested before 2026, today's identifiers; the two unranked holdings and what R6 did; month-old tags; no published NAV before 2019); every chart of hold-the-parent says it is a rebuild with no published NAV before 2019-01-02 (`check_page.py` checks each caption).
  - R2 = the 2015-01-02 sub-window; R6 = `full_r6` + `r6_links.csv` + `audit.json` `r6`; R7 = `r7_flagged_days.csv` + `segment_r7`/`whole_book_r7`; V4 from `regression.json`; V6 at most 17 of 100; T07's percentiles recomputed from its evidence beside T12's; T11's Part A and hold-the-parent as context when its headline exists.
  - "Held stock-day" in R7 = in the parent's D19 basket in force on the day or the day before (the engine's reading; my first reading, the last rule event's basket, was wrong on SCMO_0007 DIVISLAB 2016-12-23).
- **⚠ AFFECTS STEP 5:**
  - `R6_IDS=review bash tests/T12/run.sh` or `R6_IDS=frozen bash tests/T12/run.sh`: `run.sh` stops before anything runs until Manu's R6 decision is made, and passes the same `--r6-ids` to the engine and the verifier. With frozen ids the page says R6 re-tagged nothing and why.
  - Every script except `fill_writeup.py` takes `--evidence DIR` for a dry run elsewhere; `check_page.py` and `analyse.py` default to 2,000 draws (`--expect-draws`).
  - Step 4 saw the percentiles of the engine's 100-draw scratch run and T11's verdict lines (printed by the scripts); no choice in the scripts depends on them.

## Files created or modified

### Step 4
- `AA/tests/T12/{analyse.py, fill_writeup.py, report.py, check_page.py, rerun_draw.py, episodes.py, run.sh}` (new), `AA/tests/T12/logs/step_4_log.md` (new), this file (Step 4 row and notes). Synthetic evidence, copies of the engine's evidence and corrupted copies only in the scratch directory.

### Step 3
- `AA/analysis/verify_t12.py` (new), `AA/tests/T12/logs/step_3_log.md` (new), this file (Step 3 row and notes). Mocks and corrupted copies only in the scratch directory.

### Step 2
- `AA/analysis/t12_engine.py` (new), `AA/tests/T12/logs/step_2_log.md`, `AA/tests/T12/evidence/{smoke,scratch4,r6test}/` (scratch runs), this file (Step 2 row and notes)

### Step 1
- `AA/tests/T12/T12.md` (§1–§3 frozen; §4–§8 stubs), `check_prereg.py`, `step1_counts.py`, `logs/step_1_counts.json`, `evidence/basket_tags_2014-09_2019-01.csv`, `TRACKER.md`

### Step 0
- `AA/tests/T12/PLAN.md` (copy), `AA/tests/T12/TRACKER.md`
