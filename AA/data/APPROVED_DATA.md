# Approved data — the boundary for every agent working in AA

**As of: 2026-11-06.** Approved by Manu. This file is the only list of data an agent may read. It is changed only after Manu approves a data refresh, by the procedure at the bottom. `CLAUDE.md` and `AGENT.md` both point here.

## The rules

1. **Read only rows marked `APPROVED` in the table below.** Everything else on disk is off-limits, including files that look newer or that sit in `Historical Data/`, `analysis/cache/` or Downloads. A file that is not in the table is not approved.
2. **A test's window may not end after the latest usable date of any role it reads** (second table). If a test needs a later date, **stop and ask Manu**.
3. **Do not edit, extend, rebuild or re-fetch data unless Manu asks.** If the approved data is stale for what the test needs, or something is missing or ambiguous, **stop and ask Manu**. Do not work around it.
4. **Say which data you used.** Every test's data table names each file's path, its through-date and this file's "As of" date.
5. **Run `python data/check_approved_data.py`** before a test's Step 1 and at the top of its `run.sh`. If it exits non-zero, stop and ask Manu.
6. **Completed tests are pinned** to the files listed in their own `inputs.csv`. `SUPERSEDED` rows exist only so those tests can be reproduced; do not use them for a new test. A re-run on newer data is a new test, not an edit.

## Approved data

Status: `APPROVED` (use), `SUPERSEDED` (reproduce old tests only), `PENDING` (not usable until Manu rules; see the section below). The sha256 column is the first 16 hex characters. "Through" is the last date the file covers. Paths are relative to `AA/`.

<!-- approved-table:start -->
| Status | ID | File | Through | sha256 | Note |
|---|---|---|---|---|---|
| APPROVED | D17 | Historical Data/parent_nav_2026-10-22/SCMO_0003.csv | 2026-10-22 | f12dc65dbba94343 | published NAV, PASS WITH NOTES; the calendar of sessions |
| APPROVED | D17 | Historical Data/parent_nav_2026-10-22/SCMO_0007.csv | 2026-10-22 | 4898737391ecf932 | starts 2019-01-04 |
| APPROVED | D17 | Historical Data/parent_nav_2026-10-22/SCMO_0010.csv | 2026-10-22 | 184bc46f31acf6f1 | |
| APPROVED | D17 | Historical Data/parent_nav_2026-10-22/SCMO_0029.csv | 2026-10-22 | 156fc872d159e0b3 | |
| APPROVED | D18 | data/holdings_matrix/SCMO_0003_ohlc.csv | 2026-11-04 | 9f9c235e988f471d | stock OHLC, Eikon, price return; apply price_corrections.csv (F-AA-D14) |
| APPROVED | D18 | data/holdings_matrix/SCMO_0007_ohlc.csv | 2026-11-04 | 7b06630a548e8c9e | |
| APPROVED | D18 | data/holdings_matrix/SCMO_0010_ohlc.csv | 2026-11-04 | 90ad2dc40030cd83 | |
| APPROVED | D18 | data/holdings_matrix/SCMO_0029_ohlc.csv | 2026-11-04 | 6ab8c679e9a6e378 | |
| APPROVED | D18 | data/holdings_matrix/price_corrections.csv | n/a | 995afcc645c0f966 | Polyplex special dividend; mandatory |
| APPROVED | D19 | data/holdings_matrix/SCMO_0003_holding_weight_matrix.csv | 2026-09-10 | 273a2183c11f78d2 | basket weights; newest basket in the file is this date |
| APPROVED | D19 | data/holdings_matrix/SCMO_0007_holding_weight_matrix.csv | 2026-09-16 | db31ee707f15de23 | |
| APPROVED | D19 | data/holdings_matrix/SCMO_0010_holding_weight_matrix.csv | 2026-09-16 | b5828d51017b5d06 | |
| APPROVED | D19 | data/holdings_matrix/SCMO_0029_holding_weight_matrix.csv | 2026-09-16 | 36bb3d6432fb2af1 | |
| APPROVED | D19 | data/holdings_matrix/SCMO_0003_columns.csv | n/a | 4d78b45553191dc8 | column-to-ISIN map |
| APPROVED | D19 | data/holdings_matrix/SCMO_0007_columns.csv | n/a | 98561ee62412cbe0 | |
| APPROVED | D19 | data/holdings_matrix/SCMO_0010_columns.csv | n/a | a9b5a8754fbded8b | |
| APPROVED | D19 | data/holdings_matrix/SCMO_0029_columns.csv | n/a | 6189102e32c16603 | |
| APPROVED | D05 | Historical Data/frozen_2026-09-25/Rebalance_history/Rebalance_history_by_scid_SCMO_0003.csv | 2026-09-16 | e345cd1dc66e415c | basket history; which baskets are skipped. Through-date from the review, not machine-checked |
| APPROVED | D05 | Historical Data/frozen_2026-09-25/Rebalance_history/Rebalance_history_by_scid_SCMO_0007.csv | 2026-09-16 | 7be61e882194f5bd | |
| APPROVED | D05 | Historical Data/frozen_2026-09-25/Rebalance_history/Rebalance_history_by_scid_SCMO_0010.csv | 2026-09-16 | 0ac9ded9cb55dd83 | |
| APPROVED | D05 | Historical Data/frozen_2026-09-25/Rebalance_history/Rebalance_history_by_scid_SCMO_0029.csv | 2026-09-16 | fdc30a6ef3b0fa8a | |
| APPROVED | D03 | Historical Data/extended_2026-10-30/Master/Master_Nifty100.xlsx | 2026-10-30 | 4285f9f1832f3da2 | index signals; extension of the frozen file, adds the weeks 2026-09-25 to 2026-10-30 |
| APPROVED | D03 | Historical Data/extended_2026-10-30/Master/Master_MC100.xlsx | 2026-10-30 | b191eb9739949228 | |
| APPROVED | D03 | Historical Data/extended_2026-10-30/Master/Master_SC100.xlsx | 2026-10-30 | c7f4acdbe4143637 | |
| APPROVED | D09 | analysis/cache/why_gold_ohlc_eikon_extended_2026-11-04.parquet | 2026-11-04 | 3e02141265537443 | GOLDBEES OHLC, Eikon; extension of the frozen file, adds 2026-09-25 to 2026-11-04 |
| APPROVED | D12 | analysis/evidence/final_strategy/mauc1/mauc1_daily_clean.csv | 2026-09-28 | 3f5af3dfd2aa1b83 | MCX gold range, only to de-spike GOLDBEES fills; after this date fills use the raw OHLC4 |
| SUPERSEDED | D03 | Historical Data/frozen_2026-09-25/Master/Master_Nifty100.xlsx | 2026-09-18 | 8a80c502a85098b2 | replaced by the extended file; T01 to T03 read it |
| SUPERSEDED | D03 | Historical Data/frozen_2026-09-25/Master/Master_MC100.xlsx | 2026-09-18 | 114e654a28a950bd | |
| SUPERSEDED | D03 | Historical Data/frozen_2026-09-25/Master/Master_SC100.xlsx | 2026-09-18 | 63ad46a9cb9104b2 | |
| SUPERSEDED | D09 | analysis/cache/why_gold_ohlc_eikon.parquet | 2026-09-24 | 6b67c997eea1d5e9 | replaced by the extended file; T01 to T03 read it |
| APPROVED | D11 | Historical Data/LBES_Adjusted_Price_data_extended_2026-11-05.csv | 2026-11-05 | 7f9806bc0a163d2b | cash level. Rows to 2026-08-09 are the supplied LBES file, copied verbatim (its own source is still unrecorded, F-AA-D09; it equals the desk's LIQUIDCASE file until 2024-01-24 and runs about 0.54 pp/yr below it after). Rows 2026-08-10 to 2026-11-05 are level[t] = level[t-1] x (1 + r[t]), r[t] = LIQUIDCASE close[t] / close[t-1] - 1, from Postgres `merged_historical_data_with_rics` (ticker LIQUIDCASE), by `data/extend_liquid.py` (F-AA-D13). The extension runs about 0.5 pp/yr rich against LIQUIDBEES: disclose it. Approved by Manu 2026-11-06; formula and DB source re-verified the same day (appended rows equal a fresh recomputation, max diff 0.0) |
| APPROVED | D11 | Historical Data/liquidEtfFinal_extended_2026-11-05.csv | 2026-11-05 | 7361432852741fc8 | the desk's LIQUIDCASE file, extended the same way from 2026-09-07 to 2026-11-05 (recomputation max diff 0.0). Use for LIQUIDCASE-cash robustness only |
| SUPERSEDED | D11 | Historical Data/LBES_Adjusted_Price_data_2026_08_10.csv | 2026-08-09 | f3a3c0f12065fcf7 | replaced by the extended file, which copies its rows verbatim; T01 to T03 read it. Review verdict FAIL (source not recorded) |
| APPROVED | D19 | data/holdings_matrix/SCMO_0003_holding_weight_sources.csv | 2026-09-10 | 3ca63a25a4202ee1 | trace of where each basket's weights came from (DB `smallcase_rebal_historical`, or the CSV for skipped baskets), written by `data/build_holding_weight_matrix.py`. Approved by Manu 2026-11-06; a fresh rebuild from the DB reproduces it exactly |
| APPROVED | D19 | data/holdings_matrix/SCMO_0007_holding_weight_sources.csv | 2026-09-16 | 8080b296a5250d23 | |
| APPROVED | D19 | data/holdings_matrix/SCMO_0010_holding_weight_sources.csv | 2026-09-16 | 2908a21ddbf79bc1 | |
| APPROVED | D19 | data/holdings_matrix/SCMO_0029_holding_weight_sources.csv | 2026-09-16 | 3dfb14e1da651b39 | |
<!-- approved-table:end -->

## Latest usable date by role

A test's window must end on or before the earliest date of the roles it reads.

| Role | Approved through | Limits |
|---|---|---|
| Calendar of sessions and published NAV (D17) | 2026-10-22 | tests that use D17's dates cannot go past this |
| Index signals (D03, extended) | 2026-10-30 | |
| Stock prices (D18) | 2026-11-04 | |
| GOLDBEES (D09, extended) | 2026-11-04 | |
| Gold de-spike range (D12) | 2026-09-28 | fills on later sessions use the raw GOLDBEES OHLC4: 25 sessions up to 2026-11-04, 16 of them up to 2026-10-22 (T04 had 5 trade sessions among them) |
| Basket weights and history (D19, D05) | 2026-09-10 (SCMO_0003) / 2026-09-16 (others) | these are the newest baskets in Postgres `smallcase_rebal_historical` (checked 2026-11-06: nothing newer exists; the last three baskets are quarterly, so the next is expected about mid-December 2026). A window past mid-December must be re-checked: stop and ask Manu |
| Cash (D11, extended) | 2026-11-05 | LIQUIDCASE in Postgres also ends 2026-11-05 (checked 2026-11-06). Source caveats are in the table's note: disclose them in every write-up |

## Needs Manu's decision

None open (2026-11-06).

## How this file is updated (after Manu approves)

1. A refresh writes a **new** file next to the old one (`<name>_extended_<last session>`); originals are never edited. Candidate files are off-limits until step 4.
2. Only the **new rows** are checked, against the statistics of the approved history: the overlap with the approved file is unchanged, and the new rows' count, gaps, returns and spikes are in line with the older data. The approved history is not re-reviewed.
3. Manu says "approved", or names what is not.
4. An agent edits this file in one change: add the new row as `APPROVED` (path, through-date, the sha256 prefix from `python data/check_approved_data.py --sha <path>`, a note saying what was added and over which dates), set the row it replaces to `SUPERSEDED`, update the "Latest usable date" table and the "As of" line, and add a line to the change log.
5. Run `python data/check_approved_data.py`. It must exit 0.
6. Tell Manu what changed.

An agent never marks a row `APPROVED` on its own judgement, and never from a message that is not Manu's.

## Change log

| Date | Change |
|---|---|
| 2026-11-06 | File created. Approved: D17, D18, D19 (matrices and columns), D05, D12, the extended D03 (to 2026-10-30) and D09 (to 2026-11-04) on Manu's instruction in chat ("holdings matrix and everything", "no need to review it, good to go"); the 2026-11-05 data review inventoried D17 to D19, D05, D03 and D09 and its fingerprints match the files on disk (the review is still DRAFT; its open blockers concern T02, D06 and provenance). The extended D03 and D09 rows were not separately reviewed. Cash and the weight-sources files left PENDING |
| 2026-11-06 | Cash and weight sources approved by Manu in chat. Checked first, read-only: (a) `python data/extend_liquid.py --check` shows LIQUIDCASE in Postgres ends 2026-11-05, so the extended cash files are current; the appended rows of both files equal a fresh recomputation of level[t] = level[t-1] x (1 + r[t]) from the DB (max diff 0.0), and the original rows are copied verbatim; (b) the DB's newest basket per parent (SCMO_0003 2026-09-09, the others 2026-09-15) is the last row of each matrix, and a rebuild with `build_holding_weight_matrix.build` into a temporary folder reproduces all four weight matrices and `_sources.csv` files exactly (max diff 0.0). Nothing newer exists, so no file was changed. The frozen LBES row is now SUPERSEDED. The cash file's own source before 2026-08-10 is still unrecorded (F-AA-D09) and the LIQUIDCASE extension runs about 0.5 pp/yr rich: both stay disclosed |
| 2026-11-06 | Note corrected, no approval changed: the registry said later GOLDBEES fills use raw OHLC4 on "5 sessions"; that was T04's count of trade sessions. The extended GOLDBEES file has 25 sessions after the MCX file ends on 2026-09-28 (16 up to 2026-10-22). Found by the T06 engine agent and re-counted |
