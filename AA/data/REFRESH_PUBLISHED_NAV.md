# Refreshing the published index series (8 portfolios) from Redash

**What:** the daily index (NAV) of SCMO_0003, 0007, 0010, 0029 (the parents) and SCMO_0042, 0043, 0044, 0045 (the AA books on them, in that order). **Source:** Redash query 2396, "scid Historical Indices" (`https://redash.util.smallcase.com/queries/2396`, data source 4, Mongo collection `smallcasesHistorical`; owner Dhruv Seth, whose account is disabled, so the query is read-only for us). One text parameter, `scids`, comma separated (the page URL calls it `p_scids`). It returns the **full history** of each scid every time, columns `_id.scid, _id.date (YYYY/MM/DD), index`.

**Last refresh: 2026-11-09, through 2026-11-06, approved by Manu the same day.** Refreshing needs Manu's request, and the result stays a candidate until he approves it (CLAUDE.md "Data boundary", `APPROVED_DATA.md`).

## Steps

1. **Pull (Redash MCP).** Call `execute_query` with `queryId: 2396`, `parameters: {"scids": "SCMO_0003,SCMO_0007,SCMO_0010,SCMO_0029,SCMO_0042,SCMO_0043,SCMO_0044,SCMO_0045"}`, `maxAge: 0` (maxAge 0 forces a fresh run, not Redash's cache). About 12,700 rows, 1.6 MB: too big for the chat, so the tool saves the result to a file under `C:\Users\manur\.claude\projects\...\tool-results\mcp-redash-execute_query-<n>.txt` and prints the path. Use that path; do not copy rows by hand. (A single scid works the same way, but a refresh covers all 8 so that they end on the same date.)
2. **Check, writing nothing:** `python -I data/refresh_published_nav.py --check --rows <that path>`. It must end with "check only: nothing written." Stop and tell Manu if it prints `PROBLEM`: a scid missing, series ending on different dates, an approved date missing from Redash, a changed value in the overlap (Redash restated its history), duplicates, blanks, a gap over 5 days.
3. **Write the candidate:** the same command without `--check`. It writes `Historical Data/extended_<last date>/published_nav/SCMO_<id>.csv` and `manifest.json` (retrieved-at time, per-series first/last date, rows, last value, sha256). For the parents, the approved D17 rows are copied byte for byte and only the new rows go on top; the originals are never edited. For the AA books the file is written whole from Redash (no approved file to overlap with yet).
4. **Register as `PENDING`** in `data/APPROVED_DATA.md` (path, through-date, sha256 prefix from `python data/check_approved_data.py --sha <path>`, a note), add a change-log line, and tell Manu what the new rows are.
5. **After Manu says "approved":** follow "How this file is updated" in `APPROVED_DATA.md`: the new rows become `APPROVED`; the previous parent rows become `SUPERSEDED` **only if no completed test's engine still requires them APPROVED** (on 2026-11-09 the `parent_nav_2026-10-22` rows stayed APPROVED for that reason: T04-T06 call `approved_data.require()` on them and T06 reads its window end from them), update the "Latest usable date by role" table and the "As of" line, run `python data/check_approved_data.py` (exit 0), and update the "Data currency" bullet in `CLAUDE.md`.

`python -I data/refresh_published_nav.py --status` lists what the approved NAVs and the candidate folders cover.

## What depends on these series

| Dependent | Reads | After an approval |
|---|---|---|
| `tests/T01`-`T06` and their engines/verifiers (`analysis/t03_engine.py`, `t04_engine.py`, `t05_engine.py`, `t06_engine.py`, `verify_t03.py` ... `verify_t06.py`, `tests/T02/backtest.py`, `tests/T03/check_page.py`, `tests/T06/spell_counts.py`) | `Historical Data/parent_nav_2026-10-22/SCMO_<parent>.csv`, hard-coded | **Leave as is.** Completed tests are pinned to their own `inputs.csv` (rule 6); a re-run on the new window is a new test (T07 or later) that reads the new file through `analysis/approved_data.py` |
| `data/data_review.py` (D17 loader `load_parent_nav_2026`), `data/review_page.py`, `data/DATA_REVIEW.md`, `data/review/<date>/` | the same D17 folder, D14/D15 `parentIndices.csv`, `indices.csv` | The 2026-11-05 review stays as the record. A new review (`python data/data_review.py --date <d>`) after an approval should point the loader at the approved folder and add D15/D17 rows for the AA books |
| `data/parent_rebuild_hm.py` (`PUBDIR`), `data/parent_rebuild_hm/PARENT_REBUILD_HM.md` | D17 | Re-run after an approval; its G0 gate compares the rebuild with the published NAV, and the stock prices (D18) end 2026-11-04, so the comparison window ends there |
| `CLAUDE.md` ("Data currency", "Published parent NAVs"), `data/APPROVED_DATA.md` | the table above | Updated in step 5 |

The AA books have no earlier approved file; `Historical Data/indices.csv` (D15, 2021-11-01 → 2026-08-21, with the benchmark column) is the older copy and is the same series (checked 2026-11-09: scale 1 ± 1e-10 and daily returns equal to 4.4e-16 on all 1,186 shared dates).

## Known limits

- The Redash index is the published NAV: a price index on the baskets' own prices; the calendar is whatever the NAV has (includes Budget Saturdays/Sundays, lacks some Diwali muhurat sessions; see `Historical Data/parent_nav_2026-10-22/SOURCE.md`).
- A new-row check against D18 sessions only reaches D18's last session (2026-11-04 at the 2026-11-09 pull).
- The Redash query is not ours: if it changes, the script's overlap check will say so.
