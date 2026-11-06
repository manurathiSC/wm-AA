# T03 Step 1 log: parent rebuild (G0), 0007 calendar-2021 gap

Date 2026-11-05. Independent investigation run alongside the main session's own Step 1 pass. The main session had
already found and corrected the cause (Polyplex special dividend, F-AA-D14, `price_corrections.csv`, variant
`listed_weights_skip_dropped_corrected`) by the time this run reached the same place; this log re-derives it from
scratch, adds the isolation evidence, and finds the remainder of the 2021 gap (a Redington ordinary dividend).

## What was done

1. Read the plan (handoff rules, Context, Step 1), `AA/CLAUDE.md`, `data/parent_rebuild_hm/PARENT_REBUILD_HM.md`, `data/parent_rebuild_hm.py`, `TRACKER.md`.
2. Wrote `data/parent_gap_0007_2021.py` (new, standalone, reuses `build()` etc. from `parent_rebuild_hm.py`; reads only existing files; writes `data/parent_rebuild_hm/gap_0007_2021_*.csv`). Run from `AA/`: `python data/parent_gap_0007_2021.py`.
3. Read-only Postgres queries (scratchpad scripts, not kept in the repo) against `ohlcv_eikon` and `merged_historical_data_with_rics` for Polyplex around the ex-date, and a scan of the ratio of the two closes for every stock 0007 held in Dec-2020..Dec-2021.
4. `data/parent_rebuild_hm.py` was NOT changed by this run and NOT rerun (it already carried the corrected variant; `g0_gate.csv`, `summary.csv`, `yearly.csv` on disk are from 21:30 and consistent with it).
5. No edit to `review_decisions.json`, `DATA_REVIEW.md`, `CLAUDE.md`, any holdings_matrix file, or Historical Data.

## Findings, with numbers (all 0007, listed weights, avail_ohlc4)

**A. Weights are not the problem.** DB weight matrix vs the frozen rebalance-history CSV, all 52 baskets: held sets identical in every basket, 0 unmapped ISINs, max |weight diff| 4.6e-11 (PARENT_REBUILD_HM.md says 5e-13; both are numerical noise; file `gap_0007_2021_weights_db_vs_csv.csv`). 2021 baskets: 2020-12-17 (10 stocks), 2021-03-18 (11), 2021-06-17 (13), 2021-09-16 (13, skipped), 2021-12-16 (11), all diff 0.0.

**B. The skipped 2021-09-16 basket is not the cause.** Its weights are identical to 2021-06-17's (13 stocks at 0.0769, allclose True). Trading it (fix B) moves the 2021 gap only 2.036 -> 1.861 pp (it re-equalises drifted weights), and the full-window gap 0.271 -> 0.255 pp/yr. Trading both skipped baskets (fix A): 2021 1.861, full window 0.134 pp/yr (G0 overall PASS, yearly FAIL). Neither fixes it.

**C. The gap is a single-day step.** Daily model minus published, rebased on 2020-12-31: cumulative gap 0.000 pp through 2021-02-16, +1.190 pp after 2021-02-17 (day gap +1.179 pp: model +0.287 %, published -0.892 %), then 1.14 to 1.32 pp for the rest of the year (flat, no drift). No rebalance falls on 2021-02-17 (baskets: 2020-12-17, 2021-03-18), so it is a price event, not a weight event.

**D. The stock is Polyplex (POLYPLEX.NS), 10.6 % of the basket by value that day.** Rs 100/share special dividend, ex-date 2021-02-17. Unadjusted (`merged_historical_data_with_rics`): close 911.20 on 02-16, 823.80 on 02-17 (-9.6 %). `ohlcv_eikon` (= D18): 764.97 on 02-16, 776.85 on 02-17 (+1.6 %), because Eikon back-adjusts the dividend. Ratio eikon/unadjusted steps 0.8395 -> 0.9430, i.e. a step of 0.8903 = 811.20/911.20, exactly the dividend factor (the further 0.943 is a later adjustment applying to both sides of the ex-date). Model contribution 0.1059 x (+1.55 %) = +0.16 pp against about 0.1059 x (-9.6 %) = -1.0 pp in the published index: the 1.18 pp day gap. (The 1.123274 factor is 1/0.8903; the DB-implied pre/post ratio step is 12.327 %, `1.12327`.)

**E. Fixes tried (`gap_0007_2021_fixes.csv`):**

| Fix | 2021 gap (pp) | Full-window gap (pp/yr) | Worst year (gap) | G0 overall/yearly |
|---|---|---|---|---|
| baseline `listed_weights_skip_dropped` | +2.036 | +0.271 | 2021 (+2.036) | FAIL/FAIL |
| A. trade both skipped baskets | +1.861 | +0.134 | 2021 (+1.861) | PASS/FAIL |
| B. trade only the 2021-09-16 skipped basket | +1.861 | +0.255 | 2021 (+1.861) | FAIL/FAIL |
| C. Polyplex x1.123274 before 2021-02-17 (`price_corrections.csv`) | +0.168 | +0.103 | 2019 (+0.391) | PASS/PASS |
| D. C plus Redington x1.01196 before 2021-07-16 (exploratory) | +0.002 | +0.088 | 2019 (+0.391) | PASS/PASS |

Factor sweep (`gap_0007_2021_factor_sweep.csv`): applying only a Polyplex factor, the 2021 gap crosses zero at 1.1359, versus the dividend-implied 1.1233; the difference is Redington (below) absorbed by the Polyplex factor, not a wrong dividend factor.

**F. The residual 0.17 pp is a Redington ordinary dividend.** After fix C the only 2021 day with |gap| > 0.1 pp is 2021-07-16 (+0.111 pp). A scan of the eikon / unadjusted close ratio for every stock 0007 held in Dec-2020..Dec-2021 shows exactly two steps above 0.3 % while held: Polyplex 2021-02-17 (+12.33 %) and Redington 2021-07-16 (+1.196 %; Redington was 7.7 % of the 2021-06-17 basket). Applying x1.01196 before 2021-07-16 brings the 2021 gap to +0.002 pp and the full-window gap from +0.103 to +0.088 pp/yr. This is below the 2 % threshold of the main session's scan, so not in contradiction with F-AA-D14's "no other persistent step >= 2 %". It is NOT in `price_corrections.csv` (the file was not edited by this run); it is not needed to pass G0. Smaller ordinary-dividend steps (< 0.3 %) were not enumerated and plausibly make up 0007's remaining +0.39 pp in 2019.

## G0 table (variant `listed_weights_skip_dropped_corrected`, from `data/parent_rebuild_hm/g0_gate.csv`)

| Parent | CAGR gap, 2019-01-02 -> 2026-10-22 (pp/yr) | Overall (+-0.25) | Worst calendar year | Yearly (+-0.5) |
|---|---|---|---|---|
| SCMO_0003 | +0.045 | PASS | 2022 (+0.43) | PASS |
| SCMO_0007 | +0.103 (uncorrected +0.271 FAIL) | PASS | 2019 (+0.39) (uncorrected 2021 +2.04 FAIL) | PASS |
| SCMO_0010 | +0.101 | PASS | 2019 (+0.45) | PASS |
| SCMO_0029 | +0.038 | PASS | 2019 (+0.19) | PASS |

The gap is closed (+2.04 -> +0.17 pp with the registered correction; +0.002 pp with Redington too). No relaxed 0007 gate is needed, so no accept-as-contaminant wording is required. Had the correction not been available, the fall-back would have been: G0 yearly +-0.5 pp for 0007 calendar 2021 relaxed to +-2.1 pp, reason "single Polyplex special-dividend back-adjustment, +1.18 pp on 2021-02-17, flat thereafter", listed in T03.md section 3. It is not needed.

## Issues, deviations, unexpected things

- The main session finished Step 1 (row DONE, F-AA-D11/D12/D14 recorded, `price_corrections.csv`, corrected variant, `g0_gate.csv`) while this run was in progress. This run therefore did not modify `parent_rebuild_hm.py`, any existing output, or the TRACKER row; it re-derived and confirmed the cause independently and added file `data/parent_gap_0007_2021.py` plus five `gap_0007_2021_*.csv` outputs.
- Plan said F-AA-D11/D12 were "not yet in review_decisions.json"; they are now (with D14, D15). Their text below is the file's current text, unchanged except for the optional extra sentences marked in D14.
- Python prints a NumPy 1.x/2.x `numexpr` warning on import; harmless, results unaffected.
- The Polyplex ex-date and Rs 100 amount are corroborated here only by the price data (the unadjusted close falls 911.20 -> 823.80 and the Eikon step is exactly 0.8903); the dividend's announcement itself is not in the DB (main session took it from a web search).
- Redington's Rs value/ex-date was inferred from the price-ratio step (+1.196 % on 2021-07-16), not from an announcement.

## Ready-to-paste findings (JSON `issues` objects)

F-AA-D11 and F-AA-D12 are already in `review_decisions.json` as below; the investigation does not change them (only the weights-equality precision, 5e-13 vs the 4.6e-11 observed here, which is immaterial).

```json
{
 "id": "F-AA-D11",
 "input": "D18, D05",
 "issue": "The holdings matrix (data/holdings_matrix/*_holdings_matrix.csv) is 0/1 and carries no weights, and it lists three baskets the rebalance history flags skipped=true (0007 2020-03-16 and 2021-09-16, 0029 2020-03-16; see F-AA-D07).",
 "effect": "A rebuild from the matrix alone is equal weight, which is wrong for most baskets (up to 0.8 pp/yr off the published NAV; 0010 is +6.5 pp off in 2020). Trading the three skipped baskets moves 0007 by -0.12 pp/yr and 0029 by -0.63 pp/yr over 2019-2026. The skipped 2021-09-16 basket of 0007 has the same weights as 2021-06-17, so trading it only re-equalises drift (2021 gap +2.04 -> +1.86 pp) and is not the cause of the 0007 2021 gap (F-AA-D14).",
 "handling": "Use data/holdings_matrix/<p>_holding_weight_matrix.csv (Postgres smallcase_rebal_historical, equals the frozen CSV to better than 1e-10) and drop the csv_only_skipped rows unless a test says otherwise. Never use the 0/1 matrix as weights. Detail: data/parent_rebuild_hm/PARENT_REBUILD_HM.md.",
 "status": "OPEN"
}
```

```json
{
 "id": "F-AA-D12",
 "input": "D18",
 "issue": "Postgres smallcase_rebal_historical is not a drop-in for the frozen rebalance CSV: (a) its rebalance_date is the decision date, not the CSV's date, so join on available_date; (b) each parent's newest basket has available_date NULL (match by identical holdings); (c) it has no skipped baskets; (d) one stock can carry two ISINs (TD Power Systems), so match on sid; (e) its latest dated basket (2026-06-15/23) is older than the CSV's 2026-09 baskets.",
 "effect": "A naive join drops or misdates baskets and silently loses stocks.",
 "handling": "data/build_holding_weight_matrix.py implements the joins above and records the source of every row in <p>_holding_weight_sources.csv. Checked again 2026-11-05 for SCMO_0007: all 52 baskets have the same held set as the frozen CSV, 0 unmapped ISINs, max weight difference 4.6e-11.",
 "status": "OPEN"
}
```

Proposed refinement of F-AA-D14 (the main session's entry stays correct; this adds the isolation evidence and the Redington residual; replace the `effect` and `handling` strings if wanted):

```json
{
 "id": "F-AA-D14",
 "input": "D18, D17",
 "issue": "Eikon back-adjusts Polyplex (POLYPLEX.NS) for its Rs 100/share special dividend (ex-date 2021-02-17, cum close 911.20), although the file's stated rule is adjustment for splits, bonuses and demergers only. ohlcv_eikon prices before the ex-date are 811.20/911.20 = 0.8903 of traded prices (the step is visible against merged_historical_data_with_rics: ratio 0.8395 -> 0.9430 across 2021-02-16/17; unadjusted close 911.20 -> 823.80, Eikon 764.97 -> 776.85). The published SCMO_0007 price-return index takes the drop. Eikon also back-adjusts ordinary dividends: Redington (ex 2021-07-16, ratio step +1.196 %) is the only other step above 0.3 % while held by 0007 in 2021.",
 "effect": "The rebuilt SCMO_0007 ran +118 bp above the published NAV on 2021-02-17 (cumulative gap 0.000 -> +1.190 pp in one day, flat afterwards) and never gave it back: +2.04 pp in calendar 2021, +0.27 pp/yr over 2019-2026 (G0 FAIL). It is not a weight or skipped-basket problem: the DB weights equal the frozen CSV and trading the skipped 2021-09-16 basket only moves the 2021 gap to +1.86 pp. Of the remaining +0.17 pp after the Polyplex correction, +0.17 pp is the Redington dividend (with x1.01196 before 2021-07-16 the 2021 gap is +0.002 pp and the full-window gap +0.088 pp/yr). A scan of every held stock in all four parents (ratio of ohlcv_eikon to merged_historical_data_with_rics, steps >= 2% while held) found no other persistent step in 2019-2026 that matches a published-NAV difference; ordinary dividends below 0.3% were not enumerated.",
 "handling": "data/holdings_matrix/price_corrections.csv multiplies Polyplex prices dated before 2021-02-17 by 911.20/811.20 = 1.123274; data/parent_rebuild_hm.py applies it in the variant listed_weights_skip_dropped_corrected: 0007 2021 gap 2.04 -> 0.17 pp, full-window gap +0.27 -> +0.10 pp/yr, G0 PASS. The D18 *_ohlc.csv files are not edited; the T03 engine must apply price_corrections.csv when it reads them. The Redington step is not corrected (not needed for G0); adding it would be one more row (REDINGTON.NS, 2021-07-16, 1.01196, SCMO_0007). Evidence: data/parent_gap_0007_2021.py and data/parent_rebuild_hm/gap_0007_2021_*.csv.",
 "status": "RESOLVED for D18 via price_corrections.csv; D06/D07 and any other price source are not corrected"
}
```

## Open issues for downstream steps

- Step 3 must apply `price_corrections.csv` (already in the main session's AFFECTS STEP 3 note). If the main session adds the Redington row, the V4 reference numbers become 0007 +0.088 pp/yr, 2021 +0.002 pp; otherwise they are +0.103 and +0.168.
- 0007 2019 (+0.39 pp) is the largest remaining calendar-year gap; inside the +-0.5 gate, cause not investigated (likely ordinary dividends).
- Eikon dividend back-adjustment is a general property of D18, so any stock's return over a holding period that spans an ex-date is overstated by roughly the dividend yield in the rebuild (and in T03's engine) relative to the published price-return index. Impact at index level is about 0.03-0.1 pp/yr (the G0 gaps above).

## Files

- Created: `C:\Users\manur\Repos\wm-AA\AA\data\parent_gap_0007_2021.py`
- Created: `C:\Users\manur\Repos\wm-AA\AA\data\parent_rebuild_hm\gap_0007_2021_weights_db_vs_csv.csv`, `gap_0007_2021_daily.csv`, `gap_0007_2021_jumpday_attribution.csv`, `gap_0007_2021_fixes.csv`, `gap_0007_2021_factor_sweep.csv`
- Created: this log.
- Modified: `C:\Users\manur\Repos\wm-AA\AA\tests\T03\TRACKER.md` (notes appended under Step 1 only)
