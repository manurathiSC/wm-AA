# T03 Step 1 log, main session: parent rebuild (G0), 0007 calendar-2021 gap

Date 2026-11-05. This is the main session's log. A parallel run wrote `step_1_log.md` (independent re-derivation); read the two together. Where they differ the differences are listed under "Reconciliation".

## What was done

1. Read the plan (handoff rules, Context, Step 1), `AA/CLAUDE.md`, `data/parent_rebuild_hm/PARENT_REBUILD_HM.md`, `data/parent_rebuild_hm.py`. `tests/T03/TRACKER.md` did not exist; created it (Step 0 row left NOT_STARTED, Step 1 DONE).
2. Isolated the gap. Daily model-minus-published for 0007 (`data/parent_rebuild_hm/daily.csv`): one day, 2021-02-17, at -118 bp; no rebalance falls on it (baskets 2020-12-17 and 2021-03-18). Per-stock contributions that day showed no stock whose own return explains it, but a single stock with an implied return difference of about -10 to -14 pp at its ~10% weight would.
3. Compared `ohlcv_eikon` (the source of D18) with `merged_historical_data_with_rics` for the ten stocks of the 2020-12-17 basket. Polyplex's close ratio steps 0.8395 → 0.9430 on 2021-02-17; the other seven comparable stocks are flat at 1.0000 (Coforge ±0.0004 noise). `ohlcv_eikon_bkp_ca_20261103` holds only six unrelated quote_ids, so it is not involved.
4. Looked for the event: DB `corp_announcements` has nothing for Polyplex in Jan-Mar 2021. A web search found a Rs 100/share special dividend, ex-date 2021-02-17 (Motilal Oswal filing summary; Business Standard 2021-02-10). The ex-date and the Rs 100 come from there, not from our data; our data corroborates them (cum close 911.20; factor (911.20 - 100)/911.20 = 0.89025 equals 1/1.123274 and the observed ratio step).
5. Causal test: scaled Polyplex prices before 2021-02-17 by 1.123274 and rebuilt SCMO_0007: 2021 gap +2.04 → +0.17 pp, full-window +0.271 → +0.103 pp/yr.
6. Scanned every stock ever held by the four parents (ratio `ohlcv_eikon` / merged, steps ≥ 2% while in the basket) for other events (142 steps; all the 2019-2026 ones are one-day reversing glitches in merged, or are not matched by a published-NAV difference; see the log).
7. Implemented: `data/holdings_matrix/price_corrections.csv`; `apply_corrections()`, `g0_gate()` and the variant `listed_weights_skip_dropped_corrected` in `data/parent_rebuild_hm.py`; `g0_gate.csv`.
8. Recorded F-AA-D11, D12 (text from PARENT_REBUILD_HM.md) and new F-AA-D14 in `data/review_decisions.json`; updated `PARENT_REBUILD_HM.md` and `CLAUDE.md`.
9. **Logging, added after the user pointed out it was missing:** `data/diagnose_0007_2021_gap.py` (reproduces every number the finding cites, parts A-D), the console logs below, this file, and an R4-format entry for F-AA-D14 in `PARENT_REBUILD_HM.md`. The first investigation ran as scratchpad scripts that are not kept; the diagnosis script is a clean re-run of them, not the same code.

## Results

G0 (±0.25 pp/yr overall, 2019-01-02 → 2026-10-22; ±0.5 pp every calendar year), `data/parent_rebuild_hm/g0_gate.csv`:

| Parent | CAGR gap, pp/yr | Overall | Worst calendar year, pp | Yearly |
|---|---|---|---|---|
| SCMO_0003 | +0.045 | PASS | +0.43 (2022) | PASS |
| SCMO_0007 uncorrected | +0.271 | FAIL | +2.04 (2021) | FAIL |
| **SCMO_0007 corrected** | **+0.103** | **PASS** | **+0.39 (2019)** | **PASS** |
| SCMO_0010 | +0.101 | PASS | +0.45 (2019) | PASS |
| SCMO_0029 | +0.038 | PASS | +0.19 (2019) | PASS |

The 0007 2021 gap is closed; no relaxed gate and no "known contaminant" entry for 0007 is needed. 0007 daily tracking error 0.92 → 0.81 %/yr.

## Reconciliation with `step_1_log.md`

- Same cause, same factor, same G0 numbers. The parallel run also showed the DB weights equal the frozen CSV in all 52 0007 baskets and that trading the skipped 2021-09-16 basket does not fix it (2021 gap +2.04 → +1.86 pp).
- **Redington.** The parallel run found the remaining +0.17 pp of 2021 is a Redington ordinary dividend (ex 2021-07-16, ratio step +1.196%, 7.7% of the 2021-06-17 basket). I re-checked the step independently (diagnosis part D: for 0007 in 2020-12-17 → 2021-12-31 only two steps ≥ 0.3% exist, Polyplex +12.327% and Redington +1.196%, and the corrected 2021 daily gaps sum to +10.8 bp in part A, which is the same size as the +0.11 pp the parallel run attributes to 2021-07-16). I did **not** re-run its "×1.01196 gives +0.002 pp" test; that figure is the parallel run's (`gap_0007_2021_fixes.csv`). My 2 % scan could not see it, so F-AA-D14's "no other persistent step" is true only at the 2% threshold. The Redington row is not in `price_corrections.csv`: it is not needed for G0 and it would be a dividend adjustment chosen after seeing the NAV, so it needs a decision (see below).
- The parallel run's "D14 refinement" text was folded into `review_decisions.json` only as far as the Redington sentence; its `issue` text now also notes that Eikon back-adjusts ordinary dividends too.

## Issues, deviations

- The plan expected an investigation that might end in "accept as contaminant"; it ended with a fix. The fix is a price correction on read, not an edit to the D18 files.
- Eikon back-adjusts dividends generally (Polyplex special, Redington ordinary), against the stated rule of `build_ohlc_file.py` ("not for dividends"). So every stock return over a span with an ex-date is overstated in D18 by about the dividend relative to a price-return index. Index-level effect is inside the G0 gaps (0.04-0.10 pp/yr). The docstring of `build_ohlc_file.py` is not corrected here (not touched this step).
- A first version of this work was produced with a shell command that failed to parse and left a half-applied state; the files were re-checked and re-written before continuing, and nothing was applied twice.
- Python prints a NumPy 1.x/2.x `numexpr` warning on import (harmless); stderr was kept out of the logs.

## Open for the user

- Add the Redington row (REDINGTON.NS, 2021-07-16, ×1.01196, SCMO_0007) to `price_corrections.csv`? Effect: 0007 +0.103 → +0.088 pp/yr, 2021 +0.168 → +0.002 pp. Left out: not needed to pass, and where to stop (ordinary dividends < 0.3% are not enumerated; they likely make up 0007's +0.39 pp in 2019) is a design decision. If added, the V4 reference changes in Step 2/3.

## Files

Created: `tests/T03/TRACKER.md`, `data/holdings_matrix/price_corrections.csv`, `data/diagnose_0007_2021_gap.py`, `data/parent_rebuild_hm/g0_gate.csv`, `data/parent_rebuild_hm/price_source_steps.csv`, `tests/T03/logs/step1_parent_rebuild_hm.log`, `tests/T03/logs/step1_0007_2021_gap_diagnosis.log`, this file.
Modified: `data/parent_rebuild_hm.py`, `data/parent_rebuild_hm/{summary,yearly,daily,...}.csv` (regenerated), `data/parent_rebuild_hm/PARENT_REBUILD_HM.md`, `data/review_decisions.json` (D11, D12, D14), `CLAUDE.md`.

Reproduce: from `AA/`, `python data/parent_rebuild_hm.py` then `python data/diagnose_0007_2021_gap.py --scan` (the scan takes about 3 minutes; the DB parts need `wm-aiReports/.env`).
