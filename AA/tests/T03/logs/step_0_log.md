# T03 Step 0 log: data review update (2026-11-05)

## What was done

1. **New inputs in `data/review_decisions.json`:** D17 (published parent NAVs 2019-2026), D18 (per-parent stock OHLC + `price_corrections.csv`), and **D19 (basket weights: `*_holding_weight_matrix.csv` and `*_columns.csv`)**. D19 is not in the plan; the engine reads the weights, so they need a verdict and a sha256 like every other input (deviation, see below).
2. **Existing text kept.** D01-D16 and X01-X02 verdicts are unchanged (a test may cite them). T03's use of each is recorded in a new block `t03_inputs`, with D11's FAIL quantified. F-AA-D09 gained D17 in its inputs. F-AA-D11, D12 and D14 were already in the file (written during Step 1).
3. **New finding F-AA-D15** (D17 and D18 do not have the same sessions), status HANDLED by the calendar rule: T03 uses D17's dates.
4. **`data/data_review.py`:** loads D17 and runs the same calendar, value and large-move checks on it; reconciles D17 against D14 on returns; checks D18 (rows, stocks, sources, duplicates, blanks, OHLC breaks, needed / missing / carried stock-sessions, carried on D17 sessions) and compares its sessions with D17's; checks D19 (row sums, held per basket). New outputs `holdings_ohlc.csv`, `d17_d18_sessions.csv`, `holdings_weights.csv`. D17's large moves use the D18/D19 rebuild (`parent_rebuild_hm/daily.csv`, listed weights, F-AA-D14 applied) as second source. Fixed a pandas-version break (`resample("Y")` fails on pandas 3.1.1; now a groupby on the year).
5. **`data/review_page.py`:** new section 3b / "Inputs of T03" (verdicts, impact, conditions, D18, session differences, D19); header lines read the previous review and citations from the decisions file.
6. **Regenerated:** `python data/data_review.py --date 2026-11-05`, `python data/review_page.py --date 2026-11-05`. The 2026-10-22 `DATA_REVIEW.md` was copied to `data/review/2026-10-22/DATA_REVIEW.md` first, so the earlier review stays intact.

## Corrections to the plan's premises (found by checking)

| Plan said | Found |
|---|---|
| "The new NAV files skip the same Muhurat sessions that the OHLC files skip" | **False.** D18 has eight sessions D17 skips: six Diwali Muhurat evenings (2020-11-14, 2021-11-04, 2022-10-24, 2023-11-12, 2024-11-01, 2025-10-21) and two special Saturdays (2024-03-02, 2024-05-18). Every D17 date is in D18, so no Kite fill is needed, but the engine's calendar must be D17's dates. F-AA-D15. |
| "0 missing and 0 carried sessions for every stock" | 0 **missing**, but **31 carried** bars in all (3, 12, 5, 11 per parent), 19 of them on D17 sessions inside the T03 window. Listed in `*_ohlc_filled_cells.csv`. Negligible against 147,167 needed stock-sessions, but not zero. |
| D18 "supersedes D06/D07" with no caveats | Also has 98, 99, 104 and 2 bars (0003, 0007, 0010, 0029) whose high or low lies outside the open-close range (median 0.12-0.13%, max 1.96%) and 7, 2, 0, 1 bars with a blank open, high or low; none is a needed stock-session (partial = 0). Eikon back-adjusts Polyplex's special dividend: `price_corrections.csv` must be applied (F-AA-D14). |

## Verdicts for T03's inputs

| ID | Verdict | T03 impact |
|---|---|---|
| D01 calendar | PASS WITH NOTES | 5 real sessions absent; T03 uses D17's dates |
| D03 signals | PASS | rows before 2021 are a production-code backfill |
| D05 baskets | PASS WITH NOTES | skipped baskets dropped; weights from D19 |
| D09 GOLDBEES | PASS WITH NOTES | de-spiked OHLC4 fill |
| D11 LBES cash | **FAIL** (source unrecorded) | LBES 4.19%/yr vs desk LIQUIDCASE 4.37%/yr over 2019-01-02 to 2026-08-07 (gap 0.18 pp/yr; identical to 2024-01-24, 0.54 pp/yr after). Cash is half the sleeve, so at most 0.09 pp/yr on a book's CAGR, and the same in every null draw |
| D12 MAUc1 | PASS WITH NOTES | only de-spikes GOLDBEES; no gold timing in T03 |
| D17 NAVs | PASS WITH NOTES | source unrecorded; equals D14 to <1e-11 bp on 1,186 common dates; 0 blanks/stale/unit breaks; all 40 moves of 8%+ matched by the rebuild |
| D18 OHLC | PASS WITH NOTES | 0 missing; 31 carried; 8 extra sessions never read |
| D19 weights | PASS WITH NOTES | equal D05's to 5e-13 |

Review totals (21 inputs): PASS 2, PASS WITH NOTES 12, FAIL 7.

## Issues and deviations

- **Another session is editing the same files.** `CLAUDE.md`, `review_decisions.json` (F-AA-D11/12/14), `PARENT_REBUILD_HM.md` and `TRACKER.md` were changed by someone else while this step ran (the TRACKER was rewritten, which reset the Step 0 row). The Step 1 subagent reports it did not write them. Edits here were made as read-modify-write on the then-current file; a backup of the JSON before the D17-D19 patch is in the session scratchpad.
- **D19 added** beyond the plan.
- **F-AA-D09 escalated, not closed:** the source of the LBES file (D11) and of the D17 export is still unknown; question for Manu.
- **Not done:** spot checks of D17/D18 prices against a public source; the review stays DRAFT.
- **A pre-existing environment break** (pandas 3.1.1, `resample("Y")`) was fixed in `data_review.py` so the review could run.

## Files

Created: `data/review/2026-11-05/` (all CSVs, `summary.json`, `charts/`, `data_review.html`), `data/review/2026-10-22/DATA_REVIEW.md` (copy of the earlier record), this log.
Modified: `data/review_decisions.json`, `data/data_review.py`, `data/review_page.py`, `data/DATA_REVIEW.md` (regenerated).
