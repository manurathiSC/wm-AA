# Step 3 log: the independent verifier `analysis/verify_t12.py` (2026-11-17)

**Independence.** Written from `logs/verifier_spec.md` (and the T07 spec it amends), `T12.md` §1-§3, `logs/evidence_contract.md` (and T07's), `TRACKER.md`, `CLAUDE.md`, `data/APPROVED_DATA.md`, `tests/T07/logs/step_3_log.md`, and the D20b review `data/review/2026-11-17_mcap_pre2018/REVIEW.md` (for R6). Forked from `analysis/verify_t07.py`. `analysis/verify_t11.py` was read for the D26 calendar, T0 and stand-in handling. **Not opened:** `t12_engine.py`, `t07_engine.py`, `t11_engine.py`, `tag_lookup.py`, `approved_data.py`, `check_approved_data.py`. Nothing is imported from `analysis/` or `data/`. The verifier has its own `APPROVED_DATA.md` parser (with the `[usable-from]` guard of rule 7), its own rank lookup on the D23b panel, simulator, subset counter, sampler replay, oracle and percentile code. Evidence files of T07 (headline) and of the T12 smoke run were read as data, never as code. The smoke run's `audit.json` readings were read only after the verifier had passed its mock and corruption tests.

`python data/check_approved_data.py` exits 0 before and after (67 approved rows, 0 problems). Python is run as `python -I` from `AA/`. The numexpr / NumPy-2 traceback printed at pandas import is harmless.

## Checks (output `evidence/<run>/verify_t12.json`, or `--out`)
Exit 0 only if every gate check compared at least one row, none failed and none was missing, and (by default) the self-test detected every corruption.

| Check | What it compares |
|---|---|
| C-data | Every file the verifier read is an APPROVED row, its sha256 matches and its through-date covers END = 2019-01-02 (D19 and D05 exempt; gate-only reads exempt from the through rule). Every `inputs.csv` row is APPROVED, has the prefix sha, matches the sha on disk and the registry's through-date, and covers END. `inputs.csv` must list the D23b combined panel. |
| C-dec | `decisions.csv` against my decisions: D26 calendar from T0 = 2014-09-01, the last session of each ISO week, latest Master row on or before the date (Smallcap 100 rows from 2011-11-25 only). Compares dates, the three SIGN cells, labels, label age, state, `disagree`, `pattern`. Requires 228 full-window decisions per book. r2 is compared if present. |
| C-tag | Every `event_stocks.csv` row (book, window, trade_date, ISIN): listed weight (renormalised), band, `tag_source`, `tag_snapshot`, kept, `info_date`, `band_signal`. Also `tag_detail` (the rank) and `tag_n_ranked` on rank rows, and `tag_via` = `r6_link` on R6 rows. The unranked holdings at events must equal Step 1's list (Hexaware INE093A01041 in 0007, DHFL INE202B01038 in 0010, none in 0003 / 0029; none in `full_r6` under the review ids) and `audit.json`'s `unranked`. |
| C-r6 | `r6_links.csv` (book, ISIN, info_date): linked quote_id, linked rank, linked band, original source. Information only when no R6 book is selected. |
| C-events | `events.csv` per (book, window, trade_date): kind, info date, states, counts per band, n_dropped, D, Σw, s, partial, τ, `basket_eff` (availableDate or effect session), and the event count per book and window. |
| C-target | `events.csv` V_before / traded / cost. `trades.csv` and `positions.csv` for every full-window run (segment, whole_book, parent, constant_mix, sleeve100) at 0 / 20.8 / 50 bps. |
| C-r7 | `r7_flagged_days.csv` against my list: \|close / previous close − 1\| ≥ 0.20 on held stock-days. Compares the row count and each row's close_prev, close and move. The "held" reading that matches is used for the R7 NAVs. |
| C-nav | Every `daily_nav.csv` row of segment / whole_book / parent / constant_mix / sleeve100 (3 costs) and segment_r7 / whole_book_r7 (0, 20.8). The end NAV of the rule at each cost. Every `stats.csv` row of a kind I derive, with the contract's rows required: full × lbes × 3 costs × 5 kinds; full × liq; r2; full_r6 segment and whole_book; R7 kinds. Statistics are compared to 1e-9, counts exactly, plus `events`. |
| C-always-in | My always-in (0 bps) against the engine's `parent` run, every session, to 1e-9 (no G0: there is no published NAV before 2019). |
| C-regress | V4(a): on the D17 calendar (each book's first D17 date to 2019-12-31), my rule against `tests/T07/evidence/headline/daily_nav.csv` (segment, 3 costs) and my whole-book run against `tests/T06/evidence/headline/daily_nav.csv` (strategy), to 1e-12. V4(b): if T11's headline exists, my whole-book and always-in runs on T12's window against T11's `strategy_fixed50` and `hold_parent`, to 1e-9. Also `regression.json` (v4a differences ≤ 1e-12 and session counts; v4b status matches whether T11's headline exists; v4d mismatches = 0). |
| C-standin | My sessions with no D18 bar (2017-10-19) and with no GOLDBEES bar (2016-10-30) equal T12.md step 1. `audit.json`'s `standins` must name both. |
| C-count | Brute-force count of the allowed N4.6 subsets at every event of every window against `events.csv` and `count_table.json`. The rule's own drop set is allowed (V5c). Events with partial equity are counted. |
| C-draws | Every saved draw. N4.6: values 0/1, dropped weight within τ, nothing / everything where the rule drops nothing / everything. N4.8: label counts equal the rule's, dropped iff the label's signal is SELL, one persistent order per ISIN. `draws.csv` `mean_dropped_weight` and `n_events`. 2,000 draws per key in a headline run. Keys: full and r2 × both nulls, full_r6 × N4.6. |
| C-draw-seed (info) | Replays `default_rng([15, 7, draw_id, book_no])` for the first 20 N4.6 draws of every window. |
| C-draw-nav | Re-simulates from the saved drops the first 20 and 20 random draws per book and null (full, LBES, 20.8 bps; daily curves at a relative 1e-6, since they are stored as float32), and draws 0-2 at 0 / 50 bps, LIQUIDCASE, r2 and full_r6. Every statistic is compared to 1e-9. |
| C-oracle | The V7 oracle (lowest Σ w × log return over the allowed set, fill-to-fill or close-to-close; the convention used is reported) and its percentile against `controls_oracle.json`. |
| C-percentile | Every percentile and p-value of `draws.csv` groups, by two implementations. MDE (2.8 × null SD) is recorded. Compared with `analysis.log` when it exists. |
| C-pit | Decisions read Master rows dated on or before the decision date; no Smallcap 100 row before 2011-11-25; tag snapshots on or before the information date; info date before the trade date; trades after decisions. Covers my own counts and the evidence's rows. |
| C-corrupt | Seven corruptions, each in its own copy: flip a tag, change a listed weight, change a position, scale a NAV by 1.001, delete an event, move a drop out of its allowed set, add 7 to an `r6_links.csv` rank. Each must fail its own check, and all of them in one copy must fail the run. The R6 corruption is skipped (not counted as missed) when there are no R6 rows to corrupt. |

Information only: my own ranking of the raw market caps (D20b for 2013-12 → 2017-12, D20 for 2018; ordinary shares, mcap descending, ties by quote_id) against the D23b panel on all 61 snapshots up to END. 94,844 rows, 0 rank mismatches, 0 band-column mismatches.

## Results
- **C-regress (the independent anchor, real data, no T12 evidence needed):** `python -I analysis/verify_t12.py --regress-only`.
  - My rule equals T07's stored NAV on all 243 / 241 / 243 / 243 sessions of 2019 at every cost. Max relative difference 4.5e-16 / 4.4e-16 / 7.0e-16 / 4.5e-16 (SCMO_0003 / 0007 / 0010 / 0029).
  - My whole-book run equals T06's: 4.4e-16 / 6.6e-16 / 6.8e-16 / 4.1e-16 (limit 1e-12).
  - V4(b): T11's headline appeared while I worked, so it ran. My whole-book and always-in runs on T12's window equal T11's `strategy_fixed50` and `hold_parent` on all 1,070 sessions at every cost, worst 1.5e-15.
  - Total 31,500 comparisons, 0 failures.
- **Mock evidence:** built by `<scratchpad>/t12v/make_mock_t12.py` from my own simulator and samplers. It has every contract file, 4 books, 20 draws per key.
  - Clean: 640,312 gate comparisons, 0 failures, exit 0.
  - In-process self-test: all 7 corruptions detected, and the combined copy fails.
  - CLI on full corrupted copies (`--no-selftest`): exit 1 for each of the 7 corruptions and for the combined copy.
  - The same mock renamed `headline` (strict mode) fails only on the 18 keys with 20 rather than 2,000 draws, as it should.
  - A second mock built with the frozen R6 ids passes under `--r6-ids frozen` (R6 corruption skipped: no rows). Under the default review ids it fails on exactly the `full_r6` rows.
  - Scratchpad: `C:\Users\manur\AppData\Local\Temp\claude\d384933f9ddb0ecb\25ca8e7b-9fb5-45af-a5f8-d3a7953e6ac8\scratchpad\t12v\` (`mock20`, `mock20f`, `corrupt20`, `cli`, `strict`). A mock proves the plumbing only; the independent anchors are C-regress and the raw-ranking cross-check.
- **Engine smoke evidence** (`tests/T12/evidence/smoke/`, SCMO_0003 only, 20 draws), run after the mock tests:
  - Command: `python -I analysis/verify_t12.py --evidence tests/T12/evidence/smoke --books SCMO_0003 --out <scratch>/verify_t12_smoke.json`.
  - 149,944 gate comparisons, 0 failures, 0 missing, worst relative difference 1.1e-14 (C-target). Every corruption detected; **exit 0**.
  - The first run exited 1 with 0 failures, because C-r6 (no R6 book in the smoke run) and C-r7 (no flagged day in SCMO_0003, on either side) compared 0 rows. C-r6 is now information-only without an R6 book. C-r7 now counts the list's row count as one comparison. Nothing was changed to match the engine.
  - The JSON was written to scratch, not into `evidence/`, because Step 3 may not write there.
- **The engine's other scratch runs** (run after the smoke check; nothing calibrated to them):
  - `evidence/scratch4`: four books, 100 draws, the engine's default frozen R6 ids. Run with `--r6-ids frozen`: 1,916,356 gate comparisons, 0 failures, **exit 0**.
  - `evidence/r6test`: SCMO_0007 and SCMO_0010, 10 draws, review ids. Run with `--r6-ids review --books SCMO_0007,SCMO_0010`: 0 failures, the 6 R6 rows agree, all 7 corruptions detected, **exit 0**.
  - The first scratch4 run had 4 failures, all in my tolerant reader of `audit.json` `unranked`. It knew only the nested book → window layout, while the engine keys `"<book>|<window>"`. The row-level `tag_source` comparison had already agreed on every row. I fixed the reader (both layouts; an absent entry now counts as MISSING) and changed nothing else.
  - The four-book run settles reading 2 below: r2 `drift` matches to 9.0e-16, `fresh` differs by 4.9e-4.
- **For Step 5:** the verifier's `--r6-ids` must match the engine's. The engine defaults to `frozen`, the verifier to `review` (coordinator's instruction). With mismatched ids, `full_r6` fails by design (tested on the mock).
- **My derivation, for the reportability gate:**
  - Events, full window: 38 / 40 / 37 / 40, of which 15 / 18 / 14 / 16 have 0 < equity share < 1.
  - Events, r2: 32 / 34 / 34 / 34, of which 11 / 14 / 13 / 12 have partial equity. Every book and window is above 6.
  - R6 (review ids) re-tags 6 event rows: 2 in SCMO_0007, 4 in SCMO_0010. Both holdings read Mid.
  - R7: one flagged held stock-day in the whole window: PURVA (SCMO_0010) on 2017-10-23, +20.8%.
  - No rule trade's GOLDBEES leg falls on a session without an MCX range (2014-10-23, 2015-01-01, 2015-11-11).
- Runtime: about 15 s for 4 books on the mock (20 draws) without the self-test. A headline run will be dominated by C-draws (persistence test of every N4.8 draw) and the self-test: a few minutes.

## Readings (where T12.md §1-§3 or the contract left a choice)
1. **R6 quote_ids (coordinator's instruction 2026-11-17, pending Manu).**
   - T12.md §2 R6 and `verifier_spec.md` quote Hexaware 236783369047 and DHFL 236798428431. These are today's listings: they already carry the holdings' ISINs through D22 and have panel rows only from 2025-02, so read literally R6 re-tags nothing.
   - The D20b review identifies the in-window listings as the old quote_ids, Hexaware 55837401060 and DHFL 55837400085, which rank Mid on every snapshot used.
   - `--r6-ids review` (default) uses the old ids. `--r6-ids frozen` (alias `literal`) uses the quoted ids. The checks work with either.
   - R6 applies only where the plain lookup reads `unranked`. `r6_links.csv` rows are the `full_r6` event rows with source `rank_linked`.
2. **r2's initial position.** The frozen text describes T0 only for the full window. `--r2-init auto` (default) takes the convention whose r2 end NAV matches `stats.csv`.
   - `drift` (T07's live-window convention; preferred on a tie): the T0 basket bought at its own availableDate session's fills, scaled to NAV 1 at r2's T0 close.
   - `fresh`: bought at r2's T0 OHLC4.
   - In SCMO_0003 both give the same NAV (the whole book is in the sleeve at r2's T0), so the smoke run cannot tell them apart. They differ by 4.9e-4 in the mock across books.
3. **Weights** renormalised per basket (T12.md step 6), and τ on renormalised weights.
4. **A basket arriving while nothing is held** trades nothing; its tags, read as of the session before, become current (T12.md step 4(iii); `--literal-skipped-basket` is diagnostic only).
5. **Stand-ins.**
   - A stock's close on a session is its latest D18 close on or before it; on a session not in D18 (2017-10-19) the fill is that close.
   - GOLDBEES with no bar (2016-10-30) uses the previous close for valuation and fill.
   - A session with no MCX range uses the raw OHLC4.
6. **R7 "held"** = listed weight > 0 in the basket in force on t−1 or t (T11's reading). The t-only and t−1-only readings are also tried, and the one that matches the evidence is reported. In this window all three give the same single row. Splice as T11: closes and fills of that stock × close_(t−1) / close_t from t on.
7. **Tag lookup.**
   - Exact ISIN first; else any ISIN or quote_id linked through D22 (`isin`, `new_isin`) or the panel's own pairs; the lowest rank wins.
   - `via` is `isin` or `quote_id`, compared only on R6 rows.
   - T0's tags are read as of T0; every other event's tags as of the previous D26 session.
   - Every tag date is asserted to be before the membership cutoff (2026-04-09).
8. **Skipped baskets** = D05's `skipped` flag or D19 sources `csv_only_skipped`; none in the window.
9. **Gate-only reads** (D17 for C-regress, D20 / D20b for the information cross-check) need not be in `inputs.csv`. Through-date exemptions are D19 and D05.
10. **Non-headline runs** compare only the windows present in the evidence and do not require `controls_oracle.json`, `regression.json` or `audit.json`. A headline run requires all windows, all files and 2,000 draws per key.
11. **`regression.json`, `count_table.json`, `controls_oracle.json` and `audit.json`** are read tolerantly (nested per book / window; keys found by pattern), since the contract does not fix their layout.

## Not checked
V6 (`controls_negative.*`), R5 (`r5_tag_error.csv`), V5(a) (`sampler_selftest.json`) and V4(c) (the code diff against `t07_engine.py`, which this verifier may not read) are not re-derived, as in T07's verifier.
