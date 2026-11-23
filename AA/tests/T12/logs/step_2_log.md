# T12 Step 2 log: the engine (`AA/analysis/t12_engine.py`)

**Written 2026-11-17.** Data check first: `python -I data/check_approved_data.py` exits 0 (67 approved rows, 0 problems; it lists `Historical Data/extended_2026-11-12/SOURCE.md` as off-limits, not read). `python -I tests/T12/check_prereg.py` OK (`3c361f4b…`). `T12.md` was not touched. I did not read `analysis/verify_t12.py`, `logs/verifier_spec.md` beyond its file list, or any Step 4 script. No CAGR, drawdown or percentile was printed or read, apart from the gate values (V6 counts, V7 percentiles, V4 differences). The engine prints gates and counts only.

## ⚠ CONTRACT CHANGES

1. **R6 as frozen re-tags nothing (frozen text inconsistent with the data; Manu's decision).** T12.md §2 R6 and contract point 1 name the quote_ids 236783369047 (Hexaware) and 236798428431 (DHFL). In D23b these quote_ids have rows only from 2025-02-28 (Hexaware, relisted 2025) and 2025-11-28 (PIRAMALFIN). They are today's listings, so they never rank in 2014-19. The D20b review's table names the **old** listings, which do rank Mid in the window: Hexaware 55837401060 (INE093A01033; rank 225-247 around the 2018-02-28 basket) and DHFL 55837400085 (INE202B01012; rank 139-169 in 2017). The review's "Manu may want a mapping from old to new quote_id (DHFL 55837400085 → 236798428431; Hexaware 55837401060 → 236783369047)" was copied into T12.md the wrong way round.
   - **What the engine does by default (`--r6-ids frozen`):** it uses the frozen ids. The linked quote_id is absent on every snapshot (misses counted: 3 reads in SCMO_0007, 5 in SCMO_0010), so the holdings stay `unranked` in `full_r6`. `full_r6` equals `full`, and `r6_links.csv` has a header only. Contract point 3 ("the two linked holdings carry `rank_linked`") therefore does not happen with the frozen ids.
   - **`--r6-ids review`** uses the old listings. Tested in the scratch run `evidence/r6test` (books 0007 and 0010, 10 draws): 6 event rows re-tagged `rank_linked` Mid (Hexaware 2018-04-27 rank 225 and 2018-05-18 rank 205; DHFL 2017-05-31 to 2017-10-27, ranks 169, 159, 147, 139), V4(d) 0 mismatches, every gate passes.
   - **Decision needed before Step 5:** which id set R6 uses. If Manu picks the review ids, `run.sh` must pass `--r6-ids review`, and the verifier (Step 3) must use 55837401060 / 55837400085. The verifier spec currently lists the frozen ids.
2. **`r6_links.csv`** has an extra column `event_no` (after the contract's columns).
3. **Events in disagreement weeks: two attributions.** `audit.json` → `events_vs_section2_coarse_counts` holds two counts:
   - `engine_events_in_disagreement_weeks`, T07's definition: the state's decision, i.e. the latest decision before the trade session.
   - `engine_events_in_disagreement_weeks_step1_attribution`, Step 1's counting: a signal event belongs to its decision; a basket-only event belongs to the first decision on or after its session, because Step 1 takes the basket in force at the decision date.

   The coarse bound is compared with the second. Under T07's attribution, SCMO_0007's full window has 19 events against the bound of 17, because the 2014-12-01 and 2015-09-01 basket events follow a mixed week but fall in unmixed weeks. Under Step 1's attribution the count is 17.
4. **Cash `liq` (R3)** is LIQUIDCASE as-of over the whole window (T11 E9). T07's code splices LBES → LIQUIDCASE at 2024-01-24, which in this window would have left the cash leg as LBES and made R3 vacuous. T12.md R3 says to replace the cash half with liquidEtfFinal.
5. **Extra files and keys** (additions only):
   - `v5_counts.json` (as T07);
   - `regression_d17.json`, written only by `--calendar d17`;
   - in `controls_negative.json`, per-book `share_pass90` and `v3_failures`;
   - in `audit.json`: `r6`, `step1_counts_reproduced`, `rule_counters` and `recorded_trade_counters`.
   - `stats.csv` and `draws.csv` have T07's extra columns.
   - `event_stocks.csv` has `row`, `listed_weight_raw` and `tag_n_ranked` (as the contract asks).
6. **V4(b) ran.** `tests/T11/evidence/headline/` appeared on disk at 19:53 on 2026-11-17, while Step 2 was running. Every run after that compares with it: whole_book vs T11's `strategy_fixed50`, parent vs `hold_parent`. Both NAVs were compared only, never printed. `audit.json` `t11_headline_seen` records whether the folder existed when the run started. The engine's tolerance is relative 1e-12; the verifier spec says 1e-9.

## What was built

`analysis/t12_engine.py` (1,708 lines) is a fork of `t07_engine.py`. The window, D26 calendar, T0, stand-ins, D24b gold range, R7 splice and d17 Book come from `t11_engine.py`. Both are copied, not imported.
- **Data access:** every input is opened with `approved_data.require()` and its sha256 prefix checked; `inputs.csv` lists 36 files.
- **Self-test:** a superseded Master, GOLDBEES and LBES, the PENDING D03b, a missing file, the off-limits SOURCE.md and a Smallcap 100 read before 2011-11-25 all raise.
- **Tags:** read through `TagLookup.from_files(D23b combined rank panel, D23 membership panel, D22 symbology)` only at events. `tag_lookup.py` is unchanged. R6 calls its internal `_rank_snapshot` on the same snapshot; it does not modify the module.
- **Windows:** `full`, `r2` (2015-01-02) and `full_r6` (books 0007 and 0010). Each has its own events, draws and drops arrays.
- **Removed from T07:** D17 calendar, G0, the live window, R6 (AA books) and `published_*` rows.
- **Added:** R7 (`r7_flagged_days.csv`; `segment_r7` and `whole_book_r7` at 0 and 20.8 bps) and stand-in counters.
- **V4:** (a) per book inside the worker, plus `--calendar d17`; (b) conditional on T11's headline; (c) AST diff of functions and classes; (d) a direct pandas read of D23b + D22.
- **Seeds** have first element 15: N4.6 `[15,7,id,b]`, N4.8 `[15,8,id,b]`, V6 `[15,9,100000,b]` / `[15,9,i,b]`, R5 `[15,5,id,b]`, V5(a) `[15,7,123456789,99]`.
- **V6** passes at ≤ 17 of 100. The engine asserts this equals T07's amended `v6_xmax(100)`.
- **CLI as the contract:**
  - `--run NAME [--draws N] [--quick] [--controls]`;
  - `--rerun --book --type --id --cost --window full|r2|full_r6 [--cash] --out`;
  - `--calendar d17`.
- **Testing-only options:** `--books`, `--out-root`, `--jobs`, `--r5`, `--v6-shifts`, `--v6-draws`, `--v4b-dir`, `--r6-ids`.
- The calibration bootstrap (seed `[15,20,b]`) is not in the engine. As in T07, it belongs to `analyse.py` (Step 4).

## Results of the runs (gates only)

**Smoke:** `python -I analysis/t12_engine.py --run smoke --draws 20 --quick` (SCMO_0003, 20 draws, R5 20, no V6/V7) exits 0 in about 8 s.
- V2 pass: 2,028 checked, 0 violations.
- V3 pass.
- V4 pass:
  - (a) max relative difference 2.2e-16;
  - (b) run, 0.0;
  - (c) pass;
  - (d) 908 rows, 0 mismatches.
- V5 pass: (a) 21 subsets, χ² 12.1 on 20 df, p = 0.91.

**Four-book scratch run:** `--run scratch4 --draws 100`, with V6 (100 shifts × 200 draws), V7 and R5 500. It exits 0 in 80 s wall (54 s on a quieter run), with 4 workers. Every gate passes:
- **V2:** 10,213 checked, 0 violations (2,208 decisions, 5,451 tag reads, 356 events, 2,198 decision trades; 148 T0 tag reads as of T0 counted apart). No Smallcap 100 label before 2011-11-25; the earliest is 2014-08-28.
- **V3:** every draw of N4.6 and N4.8, every window.
- **V4(a):** on D17's dates, T0 2019-01-02 (SCMO_0007: 2019-01-04) to 2019-12-31, with 243 / 241 / 243 / 243 sessions:
  - 12 series per book against T07's stored `daily_nav.csv` (segment, whole_book, parent and sleeve100 at 0, 20.8 and 50 bps);
  - 9 series per book against T06's (strategy, hold_parent and sleeve_only);
  - every session compared;
  - **max relative difference 2.2e-16, 2.2e-16, 2.2e-16 and 4.4e-16** (SCMO_0003, 0007, 0010, 0029);
  - decisions (sign triple and decision_idx) equal T07's on all 53 / 52 / 53 / 53 shared dates; the engine's 2019-12-31 decision has no stored counterpart.

  The D23b vs D23 and D24b vs D12 inputs make no difference on 2019.
- **V4(b):** run (T11's headline exists). 6 series per book; max relative difference **0.0** in all four books.
- **V4(c):**
  - 19 required-identical definitions are AST-identical to `t07_engine.py`: `v6_xmax`, `dropped_of`, `Events`, `build_events`, `bits_matrix`, `subset_sums`, `prepare_allowed`, `pick_index`, `v3_n46`, `v3_n48`, `sim`, `stats`, `pctile`, `gammaincc`, `kind_row`, `draw_rows`, `stretches`, `oracle_drops`, `r5_book`.
  - 18 definitions changed, all expected, with reasons in `V4C_EXPECTED_CHANGED`: `Book`, `Perturb`, `Tagger`, `ap`, `cash_levels`, `check_inputs`, `common`, `controls_book`, `draws_n46`, `draws_n48`, `event_tables`, `input_list`, `main`, `process_book`, `raw_parent`, `rerun`, `run_variants`, `sampler_selftest`.
  - Dropped: `cash_note`, `d17_path`, `v4_book`.
- **V4(d):** 4,630 event rows (every window), 0 mismatches of band, rank, snapshot, source or n_ranked.
- **V5:** (a) as above; (b) brute-force counts equal the engine's at every event; (c) the rule's own drop set is in A at every event.
- **V6:** n_pass90 = 13, 3, 6, 1 of 100 (limit 17); 0 V3 failures in the shifted nulls.
- **V7:** the oracle's percentile against the run's 100 N4.6 draws is 100 in all four books.
- `--rerun` reproduces draws exactly in four cases: SCMO_0007 full N4.6, SCMO_0010 r2 N4.8, SCMO_0010 full_r6 N4.6 and SCMO_0029 full N4.6 with liq cash. The CAGR is equal to 1e-15 and the drop vector is identical.

**Stand-ins:** the only D26 session with a held stock and no D18 bar is 2017-10-19. That gives 11 / 6 / 15 / 15 held stock-sessions priced at the previous close. GOLDBEES has no bar on 2016-10-30, and has a bar but no MCX range on 2014-10-23, 2015-01-01 and 2015-11-11. **No event session of any realisation falls on any of these sessions**: rule, comparators, r2, full_r6, the 100 V6 shifts and the 500 R5 rebuilds. The recorded trade counters are also 0.

**R7:** one flagged stock-day, PURVA.NS in SCMO_0010 on 2017-10-23 (+20.8%), the same as T11; 0 in the other books.

**Unranked holdings at events:** Hexaware INE093A01041 in SCMO_0007 (2 event rows in full, 2 in r2) and DHFL INE202B01038 in SCMO_0010 (4 and 4), as Step 1 found. No other unranked tag.

### Event counts against T12.md §2's coarse bounds

| Book, window | Events incl. T0 / bound | In disagreement weeks: Step 1 attribution / bound (T07 attribution) | Partial | Stretches | Reportable | Allowed subsets min / median / max | Events with one subset | Skipped basket events | Whole-book events |
|---|---|---|---|---|---|---|---|---|---|
| SCMO_0003 full | 38 / 45 | 14 / 17 (16) | 15 | 11 | yes | 1 / 1 / 1,365 | 23 | 8 | 23 |
| SCMO_0003 r2 | 32 / 40 | 10 / 14 (11) | 11 | 10 | yes | 1 / 1 / 1,365 | 21 | 8 | 20 |
| SCMO_0007 full | 40 / 45 | 17 / 17 (19) | 18 | 11 | yes | 1 / 1 / 6,435 | 22 | 8 | 23 |
| SCMO_0007 r2 | 34 / 40 | 13 / 14 (14) | 14 | 10 | yes | 1 / 1 / 1,716 | 20 | 8 | 20 |
| SCMO_0010 full | 37 / 45 | 13 / 17 (15) | 14 | 11 | yes | 1 / 1 / 6,435 | 23 | 9 | 23 |
| SCMO_0010 r2 | 34 / 40 | 12 / 14 (13) | 13 | 10 | yes | 1 / 1 / 6,435 | 21 | 9 | 20 |
| SCMO_0029 full | 40 / 45 | 15 / 17 (17) | 16 | 11 | yes | 1 / 1 / 8,008 | 24 | 8 | 24 |
| SCMO_0029 r2 | 34 / 40 | 11 / 14 (12) | 12 | 10 | yes | 1 / 1 / 8,008 | 22 | 8 | 21 |

With Step 1's attribution, every engine count is at or below its coarse bound. Step 1's other counts are reproduced (`step1_counts_reproduced` true): 228 / 210 decisions, the stretch lengths and the pattern counts. All eight realisations pass the reportability gate; the thinnest is SCMO_0003 r2 with 11 partial events. No event has exact τ ties (`tau_boundary_cases` 0). One signal event has no change of the signal triple: SCMO_0010 on 2018-06-04. The 2018-05-31 basket arrived while the book held no stock under BSS; its Large stock is kept at the next decision (T07's EV2 reading, unchanged).

## Readings (all in `audit.json` `readings`; full text in `READINGS`)

- **E1:** D26 calendar, 1,070 sessions; the previous close stands in on 2017-10-19 and on any held stock-session without a bar, counted.
- **E2:** decisions are T0 plus the last D26 session of each ISO week (228); the END decision is not traded.
- **E3:** state = the latest Master SIGN of each index on or before the decision date; the Smallcap 100 Master is sliced from 2011-11-25 and passed through `guard_window`.
- **E4:** initial position: the T0 basket (effective 2014-09-01, T0's own session, no drift) is bought at T0's OHLC4 and scaled to NAV 1 at T0's close. Stocks dropped at T0 go half to GOLDBEES and half to cash at the closes. For r2, the basket effective 2014-12-01 is drifted from its availableDate session to r2's T0.
- **E5:** weights are renormalised to 1 (T07 E5; T12.md step 6 says so).
- **E6:** a basket is effective on its first D26 session on or after its availableDate. D19's dates equal D05's in the window (asserted through Step 1's counts). No basket in the window is skipped.
- **E7:** stock fill = OHLC4, or the close if open/high/low is blank, or the previous close if there is no bar. Polyplex correction applied.
- **E8:** LBES as-of; `liq` = LIQUIDCASE as-of over the whole window (contract change 4).
- **E9:** GOLDBEES OHLC4 clipped to D24b's MCX range + 0.5%. Raw OHLC4 where there is no range; previous close on 2016-10-30. `Book.gold_raw` (read by T07's unchanged `sim`) marks the no-range sessions.
- **EV1-EV3:** T07's event rule, skipped-basket rule and comparator modes, unchanged.
- **N1, N1b, N2:** T07's N4.6 and N4.8 with seed prefix 15. r2 and full_r6 use the same seeds on their own event lists. N4.8 is not run on full_r6 (contract).
- **R5:** T07's tag-error draw with seed `[15,5,id,b]`; only `rank`/`nonmember_rank` sources are perturbed.
- **R6:** only reads whose `tag_lookup` source is `unranked` are replaced ("instead of Small and below"). The replacement is the linked quote_id's rank and band on the same snapshot `tag_lookup` used. If that quote_id is absent, the tag stays unranked and is counted. Source `rank_linked`, via `r6_link`.
- **R6b:** the frozen ids are today's listings (contract change 1).
- **R7:** T11 E12. Flagged = held on t-1 or t and |move| ≥ 20% on the ffilled, Polyplex-corrected close. A return-preserving splice. Rule and whole-book are re-run on their unchanged event lists (events read no price).
- **V6:** distinct shifts 26 ≤ k ≤ 202, seeds as above, pass ≤ 17.
- **V7:** T07's oracle.
- **S1, S2, S4:** constant mix f from the rule's path at the same cost; invested_weeks; the events/trades convention.
- **V2:** the T0 tag reads are counted apart.
- **V4:** as described under the results above.
- **G1-G3:** reportability; tables written for every window; controls per worker.
- **C1:** the two attributions (contract change 3).
- **T1:** `tag_n_ranked`.
- **ST:** stand-in counting.

## Time

The four-book run with 100 draws, V6, V7 and R5 500 took 54-80 s wall. V6 dominates it: about 20,000 simulated paths per book at roughly 2-3 ms each. Each draw id adds 11 paths per book: full lbes 3 costs × 2 nulls, liq × 2, r2 × 2, full_r6 × 1. **Headline (2,000 draws):** about 22,000 draw paths plus 20,000 V6 paths plus R5 per book, roughly 2-3 minutes per book in parallel on 4 workers. Writing (about 32,000 draw curves, 88,000 draws.csv rows) adds about 0.5-1 minute. **Estimate: 3-5 minutes wall.** Memory is small.

## Scratch directories written

- `tests/T12/evidence/smoke` (the smoke run)
- `tests/T12/evidence/scratch4` (four books, 100 draws, controls; not evidence)
- `tests/T12/evidence/r6test` (`--r6-ids review` test, books 0007 and 0010, 10 draws; not evidence)

These can be deleted before the headline. `run.sh` should write `headline` only.

## Data problems

None in the approved data. Every input is APPROVED with a matching sha256 and covers the window. The issue is the frozen R6 quote_ids (contract change 1): T12.md disagrees with the data, which is a pre-registration error, not a data error.
