# Independent review of D20b and D23b (market-cap tag source extended back to 2013-12-31)

Reviewer: fresh agent, 2026-11-17. Script: `data/review_mcap_pre2018.py` (`python -I data/review_mcap_pre2018.py --scratch <dir>` from `AA/`; about 3 minutes, of which about 2 minutes are the read-only Postgres pulls of check 4). It regenerates `results.json`, `trace_table.csv`, `check6_unranked_holdings.csv` and `check7_band_spikes_2014_2017.csv`. I changed no data file, registered nothing and did not touch `data/APPROVED_DATA.md`, `CLAUDE.md` or any existing script. `python data/check_approved_data.py` exited 0 before I started and after I finished (64 approved rows OK, 8 PENDING, 5 superseded, 1 unlisted file `extended_2026-11-12/SOURCE.md`, which I did not open). This verdict is advice. Manu decides.

Inputs (sha256 prefix): D20b `8b5b657c0911a97b`, D23b pre-2018 `fdc99de8d6fcb62c`, D23b combined `ba2ce96cf71b907f`, D20 `f0288a5b09a604ec`, D23 rank panel `e7c98ec5e0cc144c`, D23 membership panel `c5ac673b322945b1`, D22 `038b1d7922735910`, D26 `41d72926915826be`, D19 matrices, columns and sources files. All candidate sha256s match the registry and `manifest.json`. The puller's own sha256 (`373c2fd9…`) matches the manifest's `script_sha256`.

Order of work: I wrote and ran checks 1-3 (my rebuild included) before I opened `data/pull_mcap_pre2018.py`, `data/build_tag_panels.py` or `analysis/tag_lookup.py`. Before that I read only the candidate files, their manifest, the registry, `CLAUDE.md`, the 2026-11-12 review, D19 and D26. My Postgres query (check 4) is my own: explicit columns, `BETWEEN`, no class filter in SQL. My tag lookup (check 5) is my own, built from the rule text, and it reads my rebuild from raw D20b, not the candidate panel.

## Verdict: PASS WITH NOTES

- **All three hard gates hold with zero differences.**
  - Check 3: my rebuild of the 2013-12 to 2017-12 rank panel equals D23b row for row (74,679 rows). It is even byte-identical: same sha256 `fdc99de8…`. The combined file is exactly D23b's pre-2018 file followed by D23's body, byte for byte.
  - Check 4: D20b equals a fresh read-only Postgres pull value for value (74,729 rows, 822,019 cells). D20's own window (2018-01-01 to 2026-11-11) still equals D20 in the DB (788,112 rows, 8,669,232 cells).
  - Check 5: my tag lookup equals `TagLookup` on the combined file in all 118,667 lookups (0 mismatches).
- Coverage of the parents' holding-days from 2014-03-03 to 2017-12-29 is 99.68% (weight-weighted), and at least 99.12% for every parent (check 6). The thresholds were 99% overall and 98% per parent.
- **It is not a clean PASS.** Four notes, listed under "Caveats":
  - Two parent holdings are unranked because of an identity gap. Their correct band is Mid, but the lookup returns "Small and below" with source `unranked`.
  - The reference columns (ISIN, ticker, name, RIC) and `close` are today's values, not those of the date.
  - Every row was back-filled on 2026-01-03.
  - Nothing tests the rank rule in 2014-2017.

## Files written
- `C:\Users\manur\Repos\wm-AA\AA\data\review\2026-11-17_mcap_pre2018\REVIEW.md` (this file)
- `C:\Users\manur\Repos\wm-AA\AA\data\review\2026-11-17_mcap_pre2018\results.json` (every number below)
- `C:\Users\manur\Repos\wm-AA\AA\data\review\2026-11-17_mcap_pre2018\trace_table.csv` (20 holdings, check 8)
- `C:\Users\manur\Repos\wm-AA\AA\data\review\2026-11-17_mcap_pre2018\check6_unranked_holdings.csv` (the 2 unranked holdings and why)
- `C:\Users\manur\Repos\wm-AA\AA\data\review\2026-11-17_mcap_pre2018\check7_band_spikes_2014_2017.csv` (225 one-month band-edge spikes, check 7)
- `C:\Users\manur\Repos\wm-AA\AA\data\review_mcap_pre2018.py`
- No `mismatches_*.csv`: no gate failed. The script writes them only when a gate fails.
- Scratch only, in `C:\Users\manur\AppData\Local\Temp\claude\d384933f9ddb0ecb\25ca8e7b-9fb5-45af-a5f8-d3a7953e6ac8\scratchpad\rv`:
  - my rebuilt panel, `my_rank_panel_2013-12_2017-12.csv`, sha256 `fdc99de8…`, the same as the candidate;
  - the 8 corrupted copies of check 9;
  - `check_after.txt`.

## Check 1. Raw schema and sanity of D20b: PASS WITH NOTES
- **Schema.** 74,729 rows. The 13 columns and their order are identical to D20's. `instrument_class` is `ordinary` on all rows. `instrument_type` is "Fully Paid Ordinary Shares" on 62,762 rows and "Ordinary Shares" on 11,967.
- **Nulls.**
  - Every column is full except `mcap` and `mcap_scaled_in_cr`, which are empty on the same 50 rows. There are 0 empty `isin` and 0 empty `ticker`.
  - The 50 rows belong to 8 stocks and fall in 2014 (15), 2015 (4) and 2016 (31). The stocks are OSWALMIN, HIRAFERRO, CAPLIPOINT, ELITE, GIRRESORTS, RAMASTEEL, HUSYSLTD and ASPINWALL.
  - Their best rank on any other snapshot is 334 (CAPLIPOINT). Their best rank on a neighbouring snapshot is 672. OSWALMIN and HIRAFERRO are never ranked. **None of them sits in the top 250 on a neighbouring snapshot.**
  - In the DB all 50 are SQL NULL, not numeric NaN.
- **Duplicates.** 0 duplicates on (date, quote_id), (date, isin), (date, instrument_id) or (date, ticker), and 0 duplicate full rows.
- **Values.**
  - `mcap` > 0 and `close` > 0 on every row; `close` is never empty.
  - `mcap`/1e7 agrees with `mcap_scaled_in_cr` within 8.4e-5 relative (5e-5 crore absolute, which is rounding to 4 decimals).
  - mcap runs from 0.59 crore to 5.96 lakh crore.
- **Snapshot dates.** 49, one per month from 2013-12 to 2017-12, none missing and none extra. Against the D26 calendar, 48 of 49 are the last NSE session of their month:
  - 2014-08-28 is right: D26's last August 2014 session is 08-28.
  - 2016-10-30 (Sunday, Muhurat) is a D26 session and the last one of October 2016.
  - **2015-02-28 (Saturday) is not a D26 session.** D26's last February 2015 session is 2015-02-27. NSE did trade on Saturday 2015-02-28 (Union Budget), so the snapshot is probably real, but the approved calendar does not have that session. Effect on tags: none. A date on the D26 calendar first reads the 2015-02-28 snapshot on 2015-03-02, and 2015-02-27 reads 2015-01-30.
  - The registry note calls 2015-02-28 "the month's last session". That is true of NSE but not of D26, so I suggest rewording it.
- **Ties.** 10 rows share an mcap with another row on the same date; the best of them is rank 1,055. None is within the top 260 and none straddles a band edge. The smallest gap at the edges is 0.15% (rank 100 against 101) and 0.024% (rank 250 against 251). The quote_id tie-break never decides a band.

## Check 2. Point in time and vintage: PASS WITH NOTES
- **When the rows were written.** All 74,729 rows were written on 2026-01-03, between 05:59:06 and 07:05:33 as stored. There is one `updated_at` value per snapshot, and the writes run in date order.

| Year | Rows | Lag in days (min / median / max) | Written |
|---|---|---|---|
| 2013 | 1,368 | 4386 / 4386 / 4386 | 05:59 |
| 2014 | 17,560 | 4021 / 4174 / 4355 | 06:00-06:15 |
| 2015 | 17,455 | 3656 / 3809 / 3991 | 06:16-06:31 |
| 2016 | 19,106 | 3291 / 3445 / 3627 | 06:32-06:48 |
| 2017 | 19,240 | 2927 / 3078 / 3259 | 06:49-07:05 |

  D20's 2018 rows were written at 07:06:57-07:23:24 the same morning. So D20b is the head of the same back-fill run that wrote D20 2018-2024, and none of it was written live.
- **What the back-fill kept and what it replaced.** I tested this on known stocks.
  - **The mcap values look as of the date.** On 2014-03-31, INFY mcap is 1.876 lakh crore (about 3,293 × 571m shares, from memory of public figures). On 2013-12-31, TCS is 4.25 lakh crore and RELIANCE 2.89 lakh crore. INFY's share count falls 4.9% by 2017-12-29, which matches its December 2017 buyback. Over 2014-2017 the implied share counts of the top 300 do not drift.
  - **`close` is not the traded price.** It is back-adjusted for later splits, bonuses and dividends: INFY 2014-03-31 close 402.64 (traded about 3,290), HDFCBANK 186.32 (traded about 740), EICHERMOT 596.15 (traded about 5,960). Do not use `close` as a price.
  - **ISIN, ticker, name and RIC are today's values.**
    - HDFCBANK carries INE040A01034 (its post-2019 ISIN) in 2014.
    - Tata Motors appears as `TMPV`, "Tata Motors Passenger Vehicles Ltd" (its 2025 name).
    - In 2014 Bharti Infratel appears as `INDUSTOWER`, Shriram Transport as `SHRIRAMFIN`, and DHFL as "Piramal Finance Ltd".
    - No quote_id carries two ISINs within D20b. 721 rows (20 quote_ids) carry an ISIN different from the latest one D20 gives that quote_id.
  - This helps the parents' baskets, which also carry today's ISINs: 42,801 of 42,984 lookups match directly by ISIN. It fails where a company moved to a new quote_id (check 6).
- **Universe size.**
  - 1,368 (2013-12-31) to 1,662 (2017-02-28) shares per snapshot, against 1,655-1,709 in D20's 2018. 2017-12-29 has 1,650 and 2018-01-31 has 1,659 (+0.5%).
  - The largest monthly change is −6.0% on 2017-03-31. 115 shares leave that month (median rank 1,537, best 225; 53% carry a delisted RIC), and 48 of them return later.
  - Monthly entries and exits (median 27.5 and 22.5) are lower than in D20 2018-2025 (49.5 and 37.5).
  - **Survivorship:** 12-20% of rows per year carry a delisted RIC (`^`), including 271 of 1,368 on 2013-12-31. So this is not a survivors-only universe.
  - None of this is implausible. The early universe is smaller than in 2018, which changes `n_ranked`, not the top-250 ranks (check 7 holes).
- **The table holds more history.** `mcap_based_universe` goes back to 2005-01-31: 131,994 rows on 107 dates before 2013-12-01, not pulled. This is for information only.

## Check 3. Independent rebuild: PASS (hard gate, zero differences)
- **My rebuild against D23b's pre-2018 file.** My code ranks raw D20b:
  - null mcap is not ranked;
  - sort by mcap descending, then quote_id ascending as an integer;
  - bands are 1-100, 101-250 and above 250.

  The result has 74,679 rows. Compared with `mcap_rank_panel_2013-12_2017-12.csv` on (date, quote_id):

  | What | Result |
  |---|---|
  | Rows only in mine / only in theirs | 0 / 0 |
  | Duplicate keys | 0 |
  | Field differences in `isin`, `ticker`, `mcap`, `rank`, `n_ranked`, `band` | 0 (mcap max abs diff 0.0) |
  | Row order | identical |
  | Their band against their own rank | 0 inconsistent |
  | My panel written in the same CSV form | byte-identical (sha256 `fdc99de8d6fcb62c…`) |

- **The combined file.** Its first 6,074,721 bytes are D23b's pre-2018 file (sha256 `fdc99de8…`). The rest is D23's `mcap_rank_panel.csv` minus its header: sha256 `f0e1b82c…`, the same for both parts. Total length 71,315,144 = 6,074,721 + 65,240,473 − 50 (D23's header line). Rows: 862,744 = 74,679 + 788,065. The line endings are LF throughout and the three headers are identical.
- **sha256s.**
  - All three candidate files match the registry prefixes and the manifest's full sha256 and row counts.
  - The manifest's input sha256s for D20 and D23 match the approved files.
  - D20 and D23 match their APPROVED rows.

## Check 4. Provenance: PASS (hard gate)
- **The session.** Read-only (`transaction_read_only = on`), credentials from `wm-aiReports/.env`, neither printed nor written.
- **My query.** `SELECT <the 13 D20 columns> FROM public.mcap_based_universe WHERE date BETWEEN '2013-12-01' AND '2017-12-31'`, with no class filter, so I could see what the filter drops.
  - 77,332 rows: ordinary 74,729, etf 2,277, special 282, unknown 29, trust 15.
  - No rows lie between 2017-12-29 and 2018-01-31.
- **D20b against the DB.** On key (date, quote_id): 74,729 against 74,729 rows, 0 only in the file, 0 only in the DB, 0 duplicate keys, 0 differing values in all 11 non-key columns (822,019 cells). Columns are compared in the same order.
  - Numbers are compared as normalised decimals and timestamps as parsed values. NULL equals the empty cell.
- **D20 against the DB (2018-01-01 to 2026-11-11, ordinary).** 788,112 against 788,112 rows, 0 differences in 8,669,232 cells. The DB has moved on only after D20's end: 9,279 ordinary rows on 3 dates after 2026-11-11, the last written 2026-11-16 17:48. The latest `updated_at` on or before 2026-11-11 is still 2026-11-11 17:47:55.
- **What the class filter leaves out.** It is consistent with D20 and harmless.
  - The dropped `special` rows are DVR and preference lines (TATAMTRDVR, JISLDVREQS, FELDVR, GUJNREDVR, GATECHDVR and the VEDL, ZEEL, JSWSTEEL and MUKANDLTD preference lines). Their stored mcaps are clearly not those lines' own: TATAMTRDVR would rank 11 and the VEDL preference line 23. Leaving them out is right.
  - `trust` holds IRBINVIT and INDIGRID (best would-be rank 311). `unknown` holds 29 closed-end fund rows with no mcap.
  - The ordinary lines of those companies are all in D20b. Tata Motors ranks 11-22, VEDL and ZEEL are in the 2014 top 100, and JSWSTEEL ranks around 66.

## Check 5. Exact tag check: PASS (hard gate, zero mismatches)
- **My lookup.** For a date, take the latest snapshot on or before it. On that snapshot, find the stock by its own ISIN. If that fails, find it by any quote_id that D22 (`isin`, `new_isin`) or the panel links to the ISIN, or by any other ISIN on those quote_ids. If several rows hit, the best rank wins; this never happened (0 ambiguous cases).
  - It reads my rebuild (from raw D20b) plus the approved D23 rank panel. It does not read the candidate files.
  - `TagLookup.from_files(combined, D23 membership panel, D22)` is the side under test.
  - I compared band, source, snapshot date, rank (`detail`) and `via` on every lookup.
- **The population.**
  - Every holding of SCMO_0003, 0007, 0010 and 0029 on every D26 session from 2014-03-03 to 2018-01-31: 965 sessions, 50,555 holding-days (0003 13,507; 0007 8,241; 0010 14,411; 0029 14,396), 259 ISINs, 42,984 distinct (ISIN, date) pairs.
  - The basket on a session is the latest D19 basket with `rebalance_date` on or before it. There are no skipped baskets before 2018, and 0029's first basket is 2014-03-04, so it holds nothing on 2014-03-03.

| Test | Lookups | Mismatches |
|---|---|---|
| Population: every holding on every session 2014-03-03 to 2018-01-31 | 42,984 | 0 |
| Random D20b ISINs not held by the parents x 169 edge dates (each snapshot, the day before, the session before and after; 2013-11-30, 2013-12-01, 2013-12-30 before the first snapshot; 2015-02-27/28, 03-01/02; 2016-10-29/31; 2017-12-31; 2018-01-01/30/31, 02-01/27; a few 2019-2026 pre-cutoff dates), seed 20261117 | 40,000 | 0 |
| Random D20b ISINs x random sessions 2013-12-02 to 2018-02-28 | 30,000 | 0 |
| ISINs only in D22 (renamed or not in D20b) x edge dates | 5,000 | 0 |
| All 40 ISINs of quote_ids with more than one ISIN across D20b and D23 x every 4th snapshot and the join dates | 680 | 0 |
| Unknown, empty and malformed ISINs | 3 | 0 |
| **Total** | **118,667** | **0** |

In the population, 42,801 pairs read `rank` via `isin` and 183 read `unranked` (check 6). None needs D22. A date before 2013-12-31 reads `unranked` with no snapshot, as the registry says. The random sample stops before the 2026-04-09 cutoff, because the membership part of the rule is unchanged and was checked on 2026-11-12.

## Check 6. Coverage: PASS WITH NOTES
- **Coverage.** Holding-days from 2014-03-03 to 2017-12-29 (49,455), weighted by weight:
  - overall 99.68% (count 99.63%);
  - SCMO_0003 100.0%, 0007 100.0%, 0010 99.12%, 0029 99.59%.

  The thresholds (99% overall, 98% per parent) are met.
- **Every unranked holding.** There are two. Both are identity gaps: the stock is in D20b under a different quote_id that neither D22 nor the panel links to the basket's ISIN.

| Parent | Basket entry (today's ISIN) | What it was then | Holding-days | Weight | Rank in D20b on the snapshots used | Correct band |
|---|---|---|---|---|---|---|
| SCMO_0010 | PIRAMALFIN.NS, INE202B01038 (sid DWNH) | DHFL, quote_id 55837400085, INE202B01012 | 125 (2017-06-01 to 2017-11-29) | 6.67% (0.88% of the parent's weight-days) | 132-169 | Mid |
| SCMO_0029 | HEXT.NS, INE093A01041 (sid HEXT) | Hexaware, quote_id 55837401060, INE093A01033 (delisted 2020, relisted 2025 under a new quote_id) | 58 (2014-03-04 to 2014-05-30) | 6.67% (0.41%) | 182-232 | Mid |

  `TagLookup` returns band "Small and below", source `unranked` for both. A test that uses the band without checking `source` puts two Mid holdings in Small for 183 holding-days.
  - The same gap exists in the approved D23 era: SCMO_0007 holds HEXT.NS in its 2018-02-28 basket, and `TagLookup` on the approved D23 panel returns `unranked` for INE093A01041 on 2018-03-15 and 2018-05-30. The earlier review's 2019+ population did not include it.
- **Identity cross-check (extra).** For each matched holding-day I compared the basket's `sid` (an Eikon RIC root) with the RIC root of the D20b row the ISIN matched. It agrees on 46,902 of 49,272. The 2,370 that differ are all renames of the same listed company, which the RIC shows as today's name:
  - Essel Propack → EPL
  - Sundaram-Clayton → TVS Holdings
  - Minda Industries → UNO Minda
  - Bharti Infratel → Indus Towers
  - Orient Refractories → RHI Magnesita India
  - Cadila → Zydus Lifesciences
  - Nava Bharat → Nava
  - Astral Poly → Astral
  - Indiabulls Housing → Sammaan Capital
  - 8K Miles → SecureKloud

  No holding matched a different company.

## Check 7. Plausibility of the bands (flags, not gates): PASS WITH NOTES
- **Bad mcap rows (implied shares = mcap/close).** My probe: a move of more than 30% against both neighbouring snapshots, in opposite directions, with the neighbours within 10% of each other. With `close` back-adjusted, implied shares are a consistency probe only.
  - The probe finds 4 such blips in 2014-2017 (14 in D20 2018-2025). In the top 300 there is 1 (0.68 per 10,000 rank observations, against 0.35 for 2018-2025).
  - **DHANUKA 2016-02-29:** implied shares ×1.73 and back, rank 245 (Mid) between 371 and 344. Repaired (close × the neighbours' mean shares), it would be rank 334, Small. DHANUKA is in a parent basket at other times, not in March 2016, and repairing it changes no held band (0 of 988 holding-days on that snapshot).
  - MINDACORP 2015-01-30: ×0.1 and back, rank 963 between 446 and 433, Small either way.
  - 17 one-way jumps above 30% in the top 300 are corporate events, not errors as far as I can tell:
    - ABFRL 2016-01 (the Pantaloons scheme)
    - ADANIENT 2015-06 (demerger)
    - IDFC 2015-10 (bank demerger)
    - PFIZER 2014-12 (Wyeth merger)
    - CIEINDIA 2015-01
    - HMT 2016/2017
    - ABIRLANUVO, MFSL, NATIONALUM, CHOLAHLDNG and others
- **Band-edge spikes that revert the next month.** 225 in 2014-2017 (4.79 per snapshot) against 467 in D23 2018-2025 month-ends (4.97). 88 of the 225 are on stocks some parent holds at some time. One moves by more than 100 ranks: DHANUKA, above. List in `check7_band_spikes_2014_2017.csv`.
- **Holes (a stock missing on a snapshot but present before and after).**
  - There are 512 one-snapshot holes, concentrated in 2014-01 to 2015-10 and 2017-03 to 2017-11, and almost all far down the ranking.
  - **Castrol India is missing on 2014-02-28.** It ranks 81 on 2014-01-31 and 89 on 2014-03-31, and its interpolated rank is 84. So on that snapshot every stock below it reads one place higher: BRITANNIA at 100 and REDINGTON at 250 would be 101 and 251.
  - CHOLAHLDNG is missing on 2017-08-31 (158 before, 203 after).
  - Longer gaps reaching the top 260 are GUJGASLTD 2015-05 to 2015-08 and CMC 2015-09/10. Gujarat Gas was not trading during its 2015 merger, so that gap is genuine.
  - I re-ranked each affected snapshot with the missing stock put back at a geometrically interpolated mcap. **No parent holding-day changes band**, except a hypothetical one: with GUJGASLTD put back on 2015-06-30, EROSMEDIA (SCMO_0029, 23 holding-days) would move from Mid to Small. Since Gujarat Gas did not trade then, this is not a correction.
- **Turnover.**
  - Top-100 names changing per month: median 2, mean 2.4, max 5 (2014-07-31), against 2018-2025 median 4, mean 3.9, max 8 (2020-03).
  - Top 250: median 6.5, mean 6.7, max 11 (2014-05-30), against median 6, mean 5.7, max 14.
  - Nothing unusual.
- **The join from 2017-12-29 to 2018-01-31.**
  - Top-100 change: 1. Top-250 change: 7.
  - Spearman rank correlation of the top 500 is 0.9943, against 0.9926 for 2016-12 to 2017-01, 0.9925 for 2017-11 to 2017-12 and 0.9942 for 2018-01 to 2018-02.
  - `n_ranked` 1,650 → 1,659; total mcap 149.5 → 151.1 lakh crore.
  - Implied shares are unchanged for 93.6% of common stocks (15 move by more than 10%), against 93.4-96.1% (11-19) in the three months before.
  - Rank-100 mcap is 31,731 → 30,836 crore and rank-250 is 10,116 → 10,008 crore.
  - **No break at the join.**
- **Edge levels over time.** Rank-100 and rank-250 mcap (crore):

  | Date | Rank 100 | Rank 250 |
  |---|---|---|
  | 2013-12-31 | 11,818 | 2,931 |
  | 2014-12-31 | 18,811 | 4,728 |
  | 2015-12-31 | 20,138 | 5,484 |
  | 2016-12-30 | 20,612 | 6,107 |
  | 2017-12-29 | 31,731 | 10,116 |
  | 2018-12-31 | 29,119 | 8,497 |

  The rise in 2017 follows that year's midcap rally. From memory, the levels are in line with SEBI/AMFI's first categorisation list (early 2018, cutoffs of very roughly 28,000 and 8,500 crore on six-month averages). I did not check this against the source.
- **Well-known large caps.** I listed 40 2014 large caps; 39 are found by ticker and Tata Motors is under `TMPV`.
  - 38 of the 39 are in the top 100 on all 49 snapshots, with worst ranks from 3 (TCS) to 97 (TATASTEEL).
  - BAJFINANCE is outside the top 100 on 14 snapshots: ranks 104-148 from 2013-12-31 to 2014-12-31, and 101 on 2015-04-30. After that it is inside. Bajaj Finance was about 10,000-15,000 crore in 2014, so this is right.
  - The 2014-03-31 top 100 is recognisable throughout, with today's tickers. CAIRN, RANBAXY, IDEA and RCOM are there as they should be. JPASSOCIAT is just outside, at rank 104.
  - The small caps in the trace table (JTEKTINDIA, ICIL, ATULAUTO, DALMIASUG, KNRCON, MBLINFRA) rank 460-670.
- **The parents' band split under the same rule.** Weight share at the rank-snapshot month-ends, 2014-03 to 2017-12 against 2019-01 to 2026-03, as Large / Mid / Small (and unranked):

  | Parent | 2014-2017 | 2019-2026-03 |
  |---|---|---|
  | SCMO_0003 | 6.2 / 9.5 / 84.3 | 9.4 / 20.5 / 70.1 |
  | SCMO_0007 | 23.8 / 35.4 / 40.8 | 5.4 / 17.3 / 77.3 |
  | SCMO_0010 | 10.2 / 14.1 / 74.9 (+0.7 unranked) | 26.9 / 19.8 / 53.3 |
  | SCMO_0029 | 8.5 / 24.5 / 66.5 (+0.4 unranked) | 30.0 / 29.7 / 40.3 |

  The mixes differ a lot, and 0007 runs the opposite way to 0010 and 0029. I read this as the parents changing what they hold, not as a data fault: the bands of the large caps above and the join are clean. But a write-up must not assume the 2019+ band mix holds before 2018.

## Check 8. Trace table and hand check: PASS
`trace_table.csv` has 20 holdings. 16 are one per parent per year 2014-2017, from a seeded random pick. The other 4 sit near an edge: UPL rank 108 and RAJESHEXPO 110 in 2015, MANAPPURAM 242 in 2016, KEC 255 in 2017.

For each holding the table shows:
- the snapshot used;
- the raw D20b row: ticker, close, mcap and mcap in crore;
- n_ranked counted by hand;
- **the rank by hand** (1 + the number of rows on that snapshot with a larger mcap, plus the tie count);
- the mcap at ranks 100, 101, 250 and 251;
- the band by hand;
- the lookup's rank, band, source and via.

All 20 agree on both rank and band (3 Large, 7 Mid, 10 Small and below; 4 in 2014, 6 in 2015, 5 in 2016, 5 in 2017). Examples:
- GAIL in SCMO_0007 on 2014-07-02 uses 2014-06-30: 58,737 crore, rank 32 of 1,486, Large.
- MANAPPURAM in SCMO_0010 on 2016-07-13 uses 2016-06-30: 5,801 crore against a rank-250 mcap of 5,565 crore, rank 242, Mid.
- KEC in SCMO_0029 on 2017-10-18 uses 2017-09-29: 7,891 crore, below the rank-250 mcap of 8,006, rank 255, Small and below.

## Check 9. Self-test of the checks: PASS
I made corrupted copies of D23b's pre-2018 file and the matching combined file in scratch, each on a row the population's tags use (seed 99). I ran each through check 3 (my rebuild against the corrupted pre-2018 file and against the pre-2018 part of the corrupted combined file, the concatenation, and the sha256s) and through check 5 (`TagLookup` on the corrupted combined file against my lookup, on the 42,984 population pairs).

| Corruption | Check 3 | Check 5 (population mismatches) |
|---|---|---|
| Drop a row (2016-09-30 DISHMAN, rank 325) | flagged: 1 only in mine, row order, sha | flagged: 19 |
| Swap two ranks and bands (2016-06-30 RAMCOCEM 136 ↔ GESHIP 273) | flagged: 2 rank, 2 band, sha | flagged: 40 |
| Change one mcap ×1.5, rank kept (2016-07-29 DISHMAN) | flagged: 1 mcap, sha | not flagged (0) |
| Duplicate a row (2015-05-29 MOIL) | flagged: 1 duplicate key, row order, sha | not flagged (0) |
| Control: the real files | 0 differences, sha OK | (0, check 5) |

The last two corruptions change no tag, so check 5 should not flag them: tags read rank and band, not mcap, and a duplicate row gives the same answer. Check 3 is what protects those columns. Every corruption that changes a tag is caught by both checks.

## Caveats a write-up using these tags must disclose
1. **Back-filled history.** Every 2013-12 to 2017-12 row was written on 2026-01-03 (05:59-07:05 as stored), 2,927-4,386 days after its date, in the same run as D20's 2018-2024 rows. The mcap values look as of the date (INFY, TCS, RELIANCE, EICHERMOT and HDFCBANK spot checks; buyback-sized share changes show up), but point-in-time vintage cannot be proven.
2. **Reference columns are today's, and `close` is adjusted.** ISIN, ticker, name and RIC are the current values, not those of the date (HDFCBANK has its 2019 ISIN in 2014; Tata Motors is `TMPV`). `close` is back-adjusted for later splits, bonuses and dividends, so it is not the traded price. Only `mcap` and the rank built from it are used for tags.
3. **Rank tags in 2014-2017 are untested.** There is no index-membership data before 2026-04-09. The 92.07% agreement measured in 2026 (Mid recall 79.8%) is the only accuracy figure, and it is from a different market and probably a different index method. The rank uses full market cap, while the indices use free float.
4. **Identity gaps.** Two parent holdings read `unranked`, which gives band "Small and below", when they were Mid by rank: DHFL in SCMO_0010 (2017-06-01 to 2017-11-29, 125 holding-days at 6.67%; the basket calls it PIRAMALFIN, INE202B01038) and Hexaware in SCMO_0029 (2014-03-04 to 2014-05-30, 58 holding-days at 6.67%). Coverage is still 99.68% overall and at least 99.12% per parent. A test must count `unranked` and say how it treats them.
5. **Stale snapshot.** A date's tag comes from the month-end snapshot up to about a month old. The 2015-02-28 snapshot is a Saturday that the D26 calendar does not list, so it is first used on 2015-03-02.
6. **Isolated data errors.**
   - Castrol India (rank about 84) is missing on 2014-02-28, so the stocks below it read one place high on that snapshot.
   - DHANUKA reads rank 245 instead of about 334 on 2016-02-29.
   - There are 512 one-snapshot holes, almost all below rank 260.
   - No parent holding-day changes band because of any of these.
7. **The band mix before 2018 is not the 2019+ mix** (for example, SCMO_0007 has 23.8% of its weight in Large in 2014-2017 against 5.4% from 2019; SCMO_0029 has 8.5% against 30.0%). Results on the pre-2018 stretch come from different exposures.
8. The D20/D23 caveats still apply from 2018: the 2026-04-09 source switch, and LODHA 2021 and AXISBANK 2026-10-07.

## Open issues
- **DHFL and Hexaware.** Manu may want a mapping from old to new quote_id (DHFL 55837400085 → 236798428431; Hexaware 55837401060 → 236783369047) so that these holdings read Mid. It is not in D22, and adding it would change the identity rule, so it is his call. Until then a test reports them as `unranked`. The Hexaware gap also hits SCMO_0007's 2018-02-28 basket under the approved D23.
- The registry note for D20b says 2015-02-28 is "the month's last session". That is true for NSE, but D26 does not list it. I suggest wording it as "a Saturday Budget session not in D26".
- I did not compare any mcap with an external source. The plausibility rests on internal consistency, the join, the edge levels and a handful of figures from memory.
- `mcap_based_universe` holds 107 earlier snapshots (2005-01-31 to 2013-11) that were not pulled. This is for information, not a request.
- Which band an `unranked` holding should take is a decision for the test design, not the data. The lookup's default of "Small and below" is wrong for both cases here.
