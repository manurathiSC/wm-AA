# Independent review of the T07 tag sources (D20, D21, D22 and the D23 panels)

Reviewer: fresh agent, 2026-11-12. Script: `data/review_tag_sources.py` (`python -I data/review_tag_sources.py` from `AA/` regenerates `results.json`, `trace_table.csv` and `check6_member_predictions.csv`; about 75 seconds). I changed no data, registered nothing and did not touch `data/APPROVED_DATA.md`. `python data/check_approved_data.py` exited 0 before I started (40 approved rows OK, 5 PENDING, 1 unlisted file `extended_2026-11-12/SOURCE.md`, which I did not open). The verdict is advice; Manu decides.

## Verdict: PASS WITH NOTES

- Both hard gates hold with zero differences: my own rebuild of both panels equals the puller's file row for row (794,066 rows compared, check 3), and my own tag lookup equals `analysis/tag_lookup.py` on 327,511 lookups (check 4).
- Coverage is 100.0% overall and for every parent, with no unranked holding at all (check 5, threshold 99% / 98%).
- The rank rule agrees with real index membership on 92.07% of the 6,001 member-snapshots (check 6, threshold 90%).
- It is not a clean PASS because checks 1, 2, 6 and 7 raise caveats the T07 page must disclose (listed below). The main one: 91.4% of the holding-weeks (every week before 2026-04-09) are tagged by the rank rule from a back-filled history, and nothing tests that rule before 2026-04.

## Files written
- `C:\Users\manur\Repos\wm-AA\AA\data\review\2026-11-12_tag_sources\REVIEW.md` (this file)
- `C:\Users\manur\Repos\wm-AA\AA\data\review\2026-11-12_tag_sources\results.json`
- `C:\Users\manur\Repos\wm-AA\AA\data\review\2026-11-12_tag_sources\trace_table.csv` (28 holdings)
- `C:\Users\manur\Repos\wm-AA\AA\data\review\2026-11-12_tag_sources\check6_member_predictions.csv` (every member-snapshot of check 6 with the rank-rule band; extra, not in the spec)
- `C:\Users\manur\Repos\wm-AA\AA\data\review_tag_sources.py`
- No `mismatches_*.csv`: no gate failed.
- Scratch only: my rebuilt panels (`my_rank_panel.csv`, sha256 prefix `066c26990cc01c44`; `my_membership_panel.csv`, `3079f4edbddbff7f`) and the corrupted copies, in `C:\Users\manur\AppData\Local\Temp\claude\d384933f9ddb0ecb\ea0af580-06c7-4ce3-8c4f-77d4828a38b0\scratchpad\review_tag`.

Inputs (sha256 prefix): D20 `f0288a5b09a604ec`, D21 `532c816e53cb49a0`, D22 `038b1d7922735910`, D23 rank panel `e7c98ec5e0cc144c`, D23 membership panel `c5ac673b322945b1`. All match the registry and the puller's manifest.

Order of work: I wrote and ran checks 1-3 and saved my rebuild before opening `data/build_tag_panels.py` and `analysis/tag_lookup.py`. I did not open `pull_tag_sources.py` for anything but its docstring and SQL constants (after check 3), and I did not read `PLAN_v2.md`.

## Check 1. Raw schema and sanity: PASS WITH NOTES
- Columns are exactly as expected in D20 (13) and D21 (7); D22 has 21 columns. Rows: 788,112 / 6,001 / 9,231.
- D20: no duplicate (date, quote_id). Duplicate (date, isin): 0 among non-null ISINs (448 if empty ISINs are counted as equal to each other, so all of them are null-ISIN rows). `instrument_class` is `ordinary` on every row. `mcap` > 0 wherever present, `close` > 0 everywhere. `mcap` / 1e7 agrees with `mcap_scaled_in_cr` to 0.026%.
- Nulls, as in the context: 539 empty `isin`, 426 empty `ticker`, 47 empty `mcap` (same 47 rows for `mcap_scaled_in_cr`). Where they sit: null ISIN rows are all in 2025 (12) and 2026 (527). 515 of the 539 have an `mcap` and are ranked; their best rank is 343 (median 1,733). **None ranks in the top 250** (confirmed; the same for null ticker, best rank 343). Null `mcap` rows: 1 in 2018, 1 in 2023, 2 in 2025, 43 in 2026, on 30 dates; none can hold a top-250 position because they are not ranked.
- Ties: 56 ranked rows share an `mcap` with another row on the same date; none within the top 260, none straddling a band edge, so the quote_id tie-break never changes a band.
- Dates: 309 snapshots, 2018-01-31 to 2026-11-11: 12 per year 2018-2024, 13 in 2025, 212 in 2026. Through 2025 every date is the last D17 session of its month (2019 on) or the last weekday (2018; 2018-03-28 is right because 29 and 30 March 2018 were holidays) **except that 2025 has 13 dates: 2025-12-30 is an extra snapshot** (not the last session of December; 2025-12-31 is), written live. 2026: daily, longest gap 4 days, no gap over 4; the 2026-02-01 Sunday is a D17 session (budget day), and every D17 session of 2026 to 2026-11-06 is in D20. D20 also holds 2026-11-09 and 2026-11-11, beyond D17's end (cannot be checked against a calendar).
- D21: 8 snapshots (2026-04-09 to 2026-11-01), no duplicate (snapshot_date, isin), no ISIN in two indices, `market_cap_bucket` agrees with `index_name` on all 6,001 rows. Index sizes 100 / 150 / 250 / 250 on seven snapshots. **2026-11-01 has 251 in NIFTY MICROCAP 250.** Two names are new in that index against 2026-10-01: PFIZER (INE182A01018) and TRIVENIPT (INE2WKE01011). Both are in D20 (Pfizer on all 309 dates, Triveni Power Transmission on 19, since 2026-10-14). The data cannot say which one is the extra.
- D22: every one of the 3,522 `quote_id`s of D20 is in D22 (7,154 distinct quote_ids in D22). 276 ISINs map to more than one `quote_id` (counting `isin` and `new_isin`); 48 of them are ISINs that were in D20's top 250 at some date or are in D21. Within D20 alone one ISIN (INE225C01029) sits on two quote_ids and 46 quote_ids carry more than one ISIN over time (renames). None of this produced an ambiguous answer in the population (0 ambiguous membership alias cases).
- Note on D21 and D22 together: see "Identity" in the caveats.

## Check 2. Point in time: PASS WITH NOTES
`updated_at` minus `date` in D20 (days, min / median / max):

| Year | Rows | Lag |
|---|---|---|
| 2018 | 20,166 | 2560 / 2713 / 2894 |
| 2019 | 20,102 | 2195 / 2348 / 2529 |
| 2020 | 20,097 | 1828 / 1981 / 2163 |
| 2021 | 21,057 | 1463 / 1617 / 1799 |
| 2022 | 22,674 | 1099 / 1253 / 1432 |
| 2023 | 24,394 | 735 / 886 / 1067 |
| 2024 | 27,482 | 367 / 520 / 702 |
| 2025 | 33,061 | 0 / 153 / 334 |
| 2026 | 599,079 | 0 / 0 / 8 |

- 2018-2024 were written in one batch on 2026-01-02 and 2026-01-03 (each year in a 20-45 minute run). 2025-01-31 to 2025-11-28 were written on 2025-12-31 (lag 33-334 days). The live part starts 2025-12-30; every 2026 row was written 0-8 days after its date (178 distinct write days). D21 was inserted on the snapshot day for all 8 snapshots. So the history through 2025-11-28 was **back-filled**.
- What that could mean for the tags: (a) the ISIN on a back-filled row could be today's ISIN, not the one then. Evidence against it: 2,298 back-filled rows carry an ISIN different from the latest one of their quote_id (46 quote_ids change ISIN over time), so old ISINs are kept at least there. (b) Rank values depend on the share count and price used; a back-fill may use today's share count. I can test this only by a probe: implied shares (`mcap`/`close`) jump by more than 25% between consecutive month-ends for 45 of 23,457 top-250 monthly observations 2018-2025 (0.19%), against 11 of 52,844 daily 2026 observations. That is no sign of a systematic back-adjustment by later share counts, but it is a probe, not a proof: a consistent use of today's share count in the past would not show as a jump. (c) Survivorship: delisted instruments are in the history (rows with a `^` suffix in `ric`: 9.6% of the 2018 rows, 171 of 1,659 on 2018-01-31), so it is not a survivors-only universe.
- Cannot be tested: what the table held on the day (no vintage), whether prices and share counts were as-reported or restated, and whether the historical band edges (rank 100 / 250) were stable. Nothing in D20 or D21 gives an as-of copy.
- No look-ahead in the rule itself: all 327,511 tag lookups use a snapshot dated on or before the as-of date (0 exceptions among the population's 16,218 distinct lookups, and the edge sweeps include as-of dates between snapshots and before the first). A weekly date before 2026-04-09 uses a month-end snapshot that is up to a month old (2018-2025) or at most 4 days old (2026).

## Check 3. Independent rebuild: PASS (hard gate, zero differences)
My own code, from D20 and D21 and the rule only: rank panel 788,065 rows (788,112 minus the 47 null-`mcap` rows) and membership panel 6,001 rows. Compared with `tags/mcap_rank_panel.csv` and `tags/membership_panel.csv` on the keys (date, quote_id) and (snapshot_date, index_name, isin): 788,065 + 6,001 = 794,066 rows compared; 0 only in mine, 0 only in theirs, 0 duplicate keys, 0 field differences in `isin, ticker, mcap, rank, n_ranked, band` (mcap max absolute difference 0.0) and in `symbol, band`; the row order is identical too. Column lists match.

## Check 4. Exact tag check: PASS (hard gate, zero mismatches)
Population: parents SCMO_0003, 0007, 0010, 0029. Weekly dates = last D17 session of each ISO week, 409 per parent, from 2019-01-04 to 2026-10-30 (the first weekly date is 2019-01-04 for all four; 0003/0010/0029 start on 2019-01-02 and 0007 on 2019-01-04). Baskets from D19 (52 per parent; 0007 has 2 skipped, 0029 has 1, 0003 and 0010 none), ISIN through `_columns.csv`; the basket in effect is the latest non-skipped one with `rebalance_date` (the available date) on or before the weekly date. D19's skipped flags agree with D05 for every basket and every matrix date is in D05, with no basket having mixed flags. Holding-weeks: 18,949 (0003 4,060; 0007 4,486; 0010 5,434; 0029 4,969), 338 distinct ISINs, 16,218 distinct (ISIN, date) pairs.

Tagged by source: rank 17,325, membership 1,581, nonmember_rank 43, unranked 0. Bands: Small and below 11,252, Mid 4,086, Large 3,611.

I compared band, source, snapshot date used and the rank / index detail (stricter than the spec) between my lookup and `TagLookup.tag`:

| Test | Lookups | Mismatches |
|---|---|---|
| Every population holding on every weekly date | 16,218 | 0 |
| Edge dates x every ISIN of D20, D21 and the baskets (3,573 ISINs x 23 dates: before the first snapshot 2018-01-15, first snapshot, between month-ends, 2024-06-14, 2025-12-30/31, 2026-01-01, the Sunday 2026-02-01, 2026-04-07/08/09/10 around the cutoff, 2026-05-03/04/05 around a D21 snapshot, 2026-11-01, after the last snapshots, 2027-01-01) | 82,179 | 0 |
| Renamed ISINs: all ISINs of the 46 renamed quote_ids, one month before to one month after each ISIN change | 442 | 0 |
| Wide sweep: 3,573 ISINs x 64 dates (every 5th D20 date plus the cutoff pair) | 228,672 | 0 |
| **Total** | **327,511** | **0** |

At the cutoff my reading and the puller's are the same: 2026-04-08 uses the rank snapshot of 2026-04-08; 2026-04-09 uses the D21 snapshot of 2026-04-09 (for example RELIANCE: rank 1 Large on 04-08, NIFTY 100 on 04-09). A renamed ISIN gets the same tag under its old and new ISIN (checked on all 46). 78 holding-weeks (0.34% of the weight) are found only through D22: TDPOWERSYS (INE419M01035, 0003, 54 weeks) and KIRLPNU (INE811A01038, 0007 11 weeks, 0029 13 weeks); the baskets carry today's ISIN, D20 carries the old ISIN until 2026-08. Where my reading of the rule needed a choice (several alias ISINs of one stock sitting in different indices) none occurred in the population; the puller's rule order (the stock's own ISIN first, then aliases in sorted order) is the same as mine.

## Check 5. Coverage: PASS
Weight-weighted share of holding-weeks with a tag source (everything except "unranked"): **100.0% overall; 100.0% for each parent**; 18,949 of 18,949 holding-weeks. No unranked name, and so no holding above 2% weight is unranked. Thresholds (99% overall, 98% per parent; fail if a single holding above 2% is untagged) are met with room to spare.
The caveat is how it got there: without D22 (an ISIN-only lookup) 78 holding-weeks would be unranked and coverage would be 99.66%, still PASS. 43 holding-weeks read "nonmember_rank" after the cutoff (stocks in none of the four indices: SJS, HAPPYFORGE, VARROC for 0003 and TCI for 0007).

## Check 6. Accuracy of the rank rule against real membership: PASS
Rank rule only (latest D20 snapshot on or before each D21 date, ignoring membership) on every real member of the four indices, 8 snapshots:

- **Primary figure: pooled three-band agreement 92.07% (5,525 of 6,001 member-snapshots).** Mean of the 8 snapshots 92.07%; per snapshot 93.2, 92.8, 92.4, 91.3, 91.6, 91.3, 92.3, 91.6 (751 members on 2026-11-01). Threshold 90% PASS.
- 15 member-snapshots have no rank (the unranked rule reads them Small and below): 0, 0, 0, 2, 1, 3, 6, 3 per snapshot, equal to the expected counts. Excluding them: 92.20%.
- Confusion matrix, pooled (rows real, columns rank rule):

| Real \ Rank rule | Large | Mid | Small and below |
|---|---|---|---|
| Large (800) | 705 | 88 | 7 |
| Mid (1,200) | 86 | 958 | 156 |
| Small and below (4,001) | 0 | 139 | 3,862 |

- Recall per band: Large 88.1%, Mid 79.8%, Small and below 96.5% (Smallcap 250: 93.1%, Microcap 250: 99.95%).
- Precision per band (share of the rank-rule band that are real members of it): Large 88.1% (705 of 800 called Large), Mid 79.8% (958 of 1,200). Among all ranked D20 shares on the 8 dates (22,985 share-snapshots): 9 ranked non-members are called Large and 15 are called Mid (pooled; 1 to 3 per snapshot for Large, 1 to 4 for Mid). Small and below holds 16,975 ranked non-members, so its precision against index membership is not meaningful.
- On the parents' holdings at those 8 dates (434 holding observations, 423 of them real members, 11 non-members with 2.4% of the weight): weight-weighted agreement **88.9%** among members (count 88.7%); by parent 0003 91.1%, 0007 88.2%, 0010 80.0%, 0029 96.3%; weight-weighted recall Large 98.2%, Mid 90.0%, Small and below 86.4%. The parents mostly hold stocks inside the Smallcap 250 / Microcap 250 / Midcap 150 band edges, where the rank rule is least accurate: 13.6% of the weight of real Small and below holdings is called Mid by the rank rule.
- One regime: all 8 snapshots are in 2026-04 to 2026-11. Nothing in this review tests the tags before 2026-04. The same 92% cannot be assumed for the 2019-2025 baskets.

## Check 7. Stability and flags (not gates): PASS WITH NOTES
- Rank moves between consecutive month-ends (210,098 pairs, 107 month-ends): with three bands the largest band move is two bands, so "more than two bands" cannot occur. Exactly-two-band moves (Large <-> Small and below): 1 in all (LODHA, 2021-10-29 to 2021-11-30, rank 723 to 77, per year: 2021 = 1; no other year). One-band moves: 1,917. The 20 largest rank moves among stocks inside the top 250 at either end are in `results.json`; the top ones are LODHA (2021: rank 106 to 729 in Sep, 723 to 77 in Nov), GFL (2019-07/08: 212 to 807), ABFRL (2025-05: 238 to 513, consistent with its May 2025 demerger), ARVIND, VAKRANGEE, INFIBEAM.
- The LODHA 2021 case is a data error: its implied share count falls from 894.6m to 35.0m on 2021-09-30 and 2021-10-29, and returns to 963m on 2021-11-30, so the stock reads rank 729 for two month-ends when it was about rank 80-100. My blip probe (implied shares jump more than 25% against both neighbours and come back, rank within 300) finds 7 isolated blips in the whole table: AARTIIND 2019-09-30, UTIAMC 2021-10-29, NUVAMA 2025-12-30, GUJENERGY 2026-07-01, ANANDRATHI 2026-06-01/02, and **AXISBANK 2026-10-07 (rank 237 between ranks 18 and 15)**; two of them cross a band edge. None of the parents' holding-weeks is tagged from a blip snapshot that changes its band (0 weeks); persistent errors such as LODHA (two consecutive snapshots) are not caught by the probe.
- D21 members absent from D20 by ISIN, per snapshot: 0, 0, 0, 2, 1, 3, 6, 3 (the expected counts; the same whether I look at the latest D20 date on or before the snapshot or at all of D20). **D22 resolves none of the 15.** Nine of the 15 are three stocks listed in D21 under the ISIN of a preference share: JSWSTEEL (INE019A04016, NIFTY 100), VEDL (INE205A04011, NIFTY 100), ZEEL (INE256A04022, NIFTY SMALLCAP 250). D22 gives those ISINs their own quote_ids, class `special`, not the ordinary share's. The ordinary shares are in D20 under INE019A01038, INE205A01025, INE256A01028 (ranks on 2026-10-01: 26, 115, 716). The other six are trust units (EMBASSY, BIRET, BAGMANE), outside D20 by design (ordinary shares only). For these names a holding under the ordinary ISIN reads "nonmember_rank" instead of "membership". No parent basket to 2026-10-30 holds one of them, but the next basket (expected mid-December) could.

## Check 8. Trace table and hand check: PASS
`trace_table.csv`: 28 holdings (7 dates x 4 parents, seeded pick, 20 before the cutoff and 8 after; sources: 20 rank, 8 membership). Columns: parent, date, ISIN, stock, weight, source, snapshot used, raw market cap (rank rows) or membership entry (membership rows), rank, n_ranked, band, signal bucket, and the puller's band and source; all 28 agree with the puller. "Signal bucket" is my reading of the spec: the index signal that governs the band (Large = Nifty 100, Mid = Midcap 100, Small and below = Smallcap 100). Examples: ICICIBANK in SCMO_0029 on 2023-06-30 used the 2023-06-30 snapshot, mcap 6.54e12, rank 4 of 2,001, Large; LTFOODS in 0003 on 2025-03-28, rank 421 of 2,503, Small and below; LUPIN in 0010 on 2026-05-29, NIFTY MIDCAP 150 entry of 2026-05-04, Mid.
Hand check of ten large caps over all 107 month-ends (and the 309 snapshots): RELIANCE (ranks 1-2), HDFCBANK (2-4), TCS (1-7), INFY (4-17), ICICIBANK (4-14), ITC (4-26), SBIN (4-16), LT (8-23), BHARTIARTL (2-23), HINDUNILVR (3-13). All ten are inside the top 100 on every one of the 309 snapshots; none outside it.

## Check 9. Self-test of the checks: PASS
Corrupted copies of the rank panel in scratch (300 rows from the pre-cutoff snapshots that the parents' tags use, seeded), each run through check 3 (my rebuild against the corrupted file) and check 4 (the puller's lookup built on the corrupted file against my lookup, on the 16,218 population pairs):

| Corruption | Check 3 | Check 4 (population mismatches) |
|---|---|---|
| Ranks shifted by 60 (300 rows) | flagged: 300 rows | flagged: 1,026 |
| Bands flipped (300 rows) | flagged: 300 | flagged: 1,026 |
| Rows deleted (300) | flagged: 300 only in mine | flagged: 1,026 |
| quote_id changed (300) | flagged: 300 / 287 unmatched, 13 differ | flagged: 44 |
| ISIN overwritten (300 cells) | flagged: 300 | not flagged (0) |
| mcap changed by 1e-7 relative (3 rows) | flagged: 3 | not flagged (0) |
| 5 membership bands flipped (members that the parents' tags use) | flagged: 5 | flagged: 20 |

The last two rank corruptions change no tag, so check 4 should not flag them: the lookup recovers a stock with a missing or wrong ISIN through its `quote_id` and D22. That is a property of the design to know about, not a miss; check 3 is what protects those columns. Every corruption that changes a tag is flagged by both checks.

## Caveats the T07 results page must disclose
1. **Back-filled history.** The rank history to 2025-11-28 was written in one batch on 2025-12-31 and 2026-01-02/03 (up to 2,894 days after the date); only 2025-12-30 onwards is live. It cannot be shown that ranks, share counts or prices are as they stood on each date (check 2).
2. **Nothing tests the rank rule before 2026-04.** 91.4% of the holding-weeks (all weeks before 2026-04-09) use it. Its accuracy against real membership is measured on 8 snapshots in 2026-04 to 2026-11 only: 92.07% pooled, but Mid recall 79.8%, Large 88.1%, and 88.9% (80.0% for SCMO_0010) weight-weighted on the parents' own holdings at those dates (check 6).
3. **Cutoff discontinuity.** On 2026-04-09 the tag source changes from the rank rule to index membership. About 8% of stocks differ between the two on any date, so a stock's tag can flip on the cutoff date without any change in the stock.
4. **Stale snapshot.** Before 2026 the tag on a date comes from the month-end snapshot up to a month earlier; from 2026 it comes from the same or previous day (rank) or the previous monthly D21 snapshot (membership, which is as old as the last index list, up to about a month).
5. **Identity.** The baskets carry today's ISIN; D20 carries the ISIN of the day. 78 holding-weeks (0.34% of weight; TDPOWERSYS, KIRLPNU) are found only through D22. Three D21 index members (JSWSTEEL, VEDL, ZEEL) are listed under the ISIN of a preference share that D22 does not link to the ordinary share, and three trust units are outside D20; a basket holding them would read by rank, not membership. No basket to 2026-10-30 does.
6. **Data errors in D20.** Isolated implied-share-count blips (7 in the top 300; AXISBANK rank 237 on 2026-10-07) and one two-month error (LODHA, 2021-09/10, rank about 725 instead of about 90) exist. None changes a parent holding's band; the page should say rank-based tags have a small error rate that was not measured against a truth before 2026.
7. **Month-end calendar.** 2025 has an extra snapshot (2025-12-30); a snapshot 2026-11-09 and 2026-11-11 lies beyond D17's last session (2026-11-06). The signal data end (2026-10-30) is earlier than all of them.

## Open issues
- The puller's lookup and mine could be wrong in the same way where the spec was silent: (a) both use D20's ISIN-to-quote_id pairs as well as D22's for identity (the spec names D22 only; D22 covers D20's pairs, so the answer is the same, but it is a choice); (b) when several alias ISINs of one stock sit in different indices the order of aliases decides (does not occur in the population).
- JSWSTEEL / VEDL / ZEEL (and the trust units) are Nifty members that cannot be linked to an ordinary-share quote_id by ISIN or D22. If T07's rule or a later basket needs them, Manu may want a mapping by symbol (not part of the rule as decided).
- The 251st stock in NIFTY MICROCAP 250 on 2026-11-01 (PFIZER or TRIVENIPT) cannot be identified from the data; it affects one snapshot, one stock.
- "Signal bucket" in the trace table follows my reading; confirm against the T07 design.
- I did not check D20's mcap against any external source, so whether an individual rank is right (beyond internal consistency, the ten large caps and the isolated blips) is untested.
