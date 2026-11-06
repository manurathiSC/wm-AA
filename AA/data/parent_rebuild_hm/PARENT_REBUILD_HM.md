# Parent rebuild from `data/holdings_matrix/` (log of 2026-11-05)

Requested by Manu 2026-11-05: "rebuild using this particular holdings and price" (`data/holdings_matrix/`), then "make a holding_weight_matrix.csv with the actual weights, using the DB table `smallcase_rebal_historical`".
Numbers below come from the CSVs in this folder (`summary.csv`, `yearly.csv`, `daily.csv`, `holdings_vs_history.csv`) and `data/holdings_matrix/*_holding_weight_sources.csv`. Reproduce: from `AA/`, `python data/parent_rebuild_hm.py` and `python data/build_holding_weight_matrix.py` (the second needs the read-only Postgres login in `wm-aiReports/.env`).

## Inputs

| What | File | Notes |
|---|---|---|
| Holdings | `data/holdings_matrix/SCMO_<p>_holdings_matrix.csv` | 52 rows each, row = availableDate; **0/1 flags, no weights** |
| Prices | `data/holdings_matrix/SCMO_<p>_ohlc.csv` | Eikon (`src=db`), plus manual exports for delisted names (`export`), 3-12 carried cells per parent (`carried`); 2014-07-01 → 2026-11-04; no missing bars on any switch day (`ohlc_coverage.csv`) |
| Published NAV | `Historical Data/parent_nav_2026-10-22/SCMO_<p>.csv` | 2019-01-02 (0007: 01-04) → 2026-10-22 |
| Weights (new) | `data/holdings_matrix/SCMO_<p>_holding_weight_matrix.csv` | built from Postgres `smallcase_rebal_historical`, see below |

Method as `data/parent_rebuild.py`: switch at the (O+H+L+C)/4 of the rebalance date, price return, no costs, last close carried.

## Result: rebuilt CAGR minus published CAGR, pp/yr (avail_ohlc4 switch)

| Parent | Equal weight, 2019-01 → 2026-10 | Equal weight, 2021-11 → 2026-08 | Listed weights, 2019-01 → 2026-10 | Listed weights, 2021-11 → 2026-08 |
|---|---|---|---|---|
| SCMO_0003 | +0.25 | +0.14 | +0.05 | +0.12 |
| SCMO_0007 | +0.13 | +0.19 | +0.27 | +0.01 |
| SCMO_0010 | +0.83 | -0.02 | +0.10 | +0.00 |
| SCMO_0029 | -0.06 | +0.01 | +0.04 | +0.01 |

Equal weight and listed weights both drop the baskets the history flags `skipped=true`. Tracking error against the published NAV, 2019 → 2026-10: equal weight 0.5-1.1 %/yr, listed weights 0.15-0.9 %/yr (0007 the worst).
The (O+H+L+C)/4-of-R timing is again the best of the seven tested (`summary.csv`, equal-weight rows).

SCMO_0010 with equal weights is +6.5 pp off in 2020, so its early baskets were not equal-weighted.

## G0 gate and the 0007 2021 gap (T03 Step 1, 2026-11-05)

G0 = CAGR gap within ±0.25 pp/yr over 2019-01-02 → 2026-10-22 **and** every calendar-year return gap within ±0.5 pp. Output: `g0_gate.csv`. Variant `listed_weights_skip_dropped_corrected` = listed weights, skipped baskets dropped, plus `data/holdings_matrix/price_corrections.csv` (F-AA-D14).

| Parent | CAGR gap, pp/yr | Overall (±0.25) | Worst calendar year, pp | Yearly (±0.5) |
|---|---|---|---|---|
| SCMO_0003 | +0.045 | PASS | +0.43 (2022) | PASS |
| SCMO_0007 (uncorrected) | +0.271 | FAIL | +2.04 (2021) | FAIL |
| **SCMO_0007 (corrected)** | **+0.103** | **PASS** | **+0.39 (2019)** | **PASS** |
| SCMO_0010 | +0.101 | PASS | +0.45 (2019) | PASS |
| SCMO_0029 | +0.038 | PASS | +0.19 (2019) | PASS |

**The 0007 2021 gap is one event.** The daily model-minus-published difference is -118 bp on 2021-02-17 (no rebalance that day) and then flat; the next largest 2021 day is 11 bp. On that day Polyplex (10.6% of the 2020-12-17 basket) paid a Rs 100/share special dividend (cum close 911.20, so a -11% price drop). The published price-return index takes the drop; Eikon back-adjusts it, so `ohlcv_eikon` (and therefore D18) has Polyplex at +1.5% that day instead of about -9.6%. The adjustment factor is 811.20/911.20 = 0.8903, which equals the step between `ohlcv_eikon` and `merged_historical_data_with_rics` on the two sessions (ratio 0.8395 → 0.9430). Multiplying pre-ex-date Polyplex prices by 1.123274 takes the 2021 gap from +2.04 to +0.17 pp. Scan of all held stocks in all four parents for other persistent ohlcv_eikon-vs-merged steps ≥ 2%: none that matches a published-NAV difference in 2019-2026 (steps inside 2026 are one-day reversing glitches in merged; 2014-2018 steps are outside the published window).
Residual: 0007 +0.39 pp in 2019 and +0.16 pp in 2020. On the Budget Saturday 2020-02-01 (+152 bp) and the next session 2020-02-03 (-154 bp) the model and the published index split a move differently and the two cancel; same pair on 2025-02-01/03 for 0029 (±48 bp). They do not move any level.
Not checked: whether other special dividends are back-adjusted in other price sources (D06/D07).

## The weight matrix

`SCMO_<p>_holding_weight_matrix.csv`: same rows (availableDate) and columns as the holdings matrix; the cell is the stock's weight in that basket, 0 if not held. Weights are as stored, not renormalised; row sums are 0.9996-1.0005.
Weights come from `smallcase_rebal_historical` (matched on `available_date`, stocks on platform `sid`). Two baskets for 0007 (2020-03-16, 2021-09-16) and one for 0029 (2020-03-16) are not in the table; they are the CSV's `skipped=true` baskets and take the CSV's drifted weights (`source = csv_only_skipped` in `*_holding_weight_sources.csv`).
Checks (all pass): in every row the held set equals the holdings matrix's and the frozen CSV's; the DB weights equal the CSV weights to 5e-13 (so the earlier "listed weights" runs, which read the CSV, are the same numbers).

## Findings

**F-AA-D11 (open) — the holdings matrix carries no weights and includes skipped baskets.** It is 0/1, so a rebuild from it alone is equal weight, which is wrong for most baskets (see the table). It also lists three baskets the history flags skipped (F-AA-D07); trading them moves 0007 by -0.12 pp/yr and 0029 by -0.63 pp/yr over 2019-2026. *Handling:* use the weight matrix; drop `csv_only_skipped` rows unless a test says otherwise.

**F-AA-D12 (open) — `smallcase_rebal_historical` is not a drop-in for the frozen CSV.** (a) Its `rebalance_date` is not the CSV's `date` (decision date): for most baskets they differ by several days, so join on `available_date`. (b) The newest basket of each parent (0003 version 42, 0007 version 42, 0010 version 42, 0029 version 39) has `available_date` NULL; it is matched to the matrix row by identical holdings. (c) It has no skipped baskets. (d) One stock can carry two ISINs (TD Power Systems: the table has INE419M01027 on 2025-06-03 where the columns file has INE419M01035), so match on `sid`. (e) The table's latest dated basket is 2026-06-15/23, before the CSV's 2026-09 baskets.

### F-AA-D14 — Eikon back-adjusts Polyplex's Rs 100 special dividend (ex 2021-02-17) but the published index does not, which is the whole +2.04 pp SCMO_0007 gap in 2021

**Status:** FIXED for D18 (by `price_corrections.csv`, applied on read). Not corrected: D06/D07, and ordinary dividends (Redington, ex 2021-07-16, +1.196% step, is the remaining +0.17 pp of 2021).
**Evidence:** `data/parent_rebuild_hm/{g0_gate,daily,yearly,summary}.csv`; `data/holdings_matrix/price_corrections.csv`; `tests/T03/logs/step1_0007_2021_gap_diagnosis.log`; `tests/T03/logs/step_1_main_log.md`; `tests/T03/logs/step_1_log.md` (parallel re-derivation).
**Claim:** on 2021-02-17 the rebuilt SCMO_0007 gains 118 bp on the published NAV with no rebalance that day, and the gap never reverses (calendar 2021 +2.04 pp; 2019-2026 +0.271 pp/yr; G0 FAIL). Polyplex was 10.6% of the basket; `ohlcv_eikon` has it +1.55% that day, the traded close fell 9.59% (911.20 → 823.80); the Eikon-to-unadjusted ratio steps 0.8395 → 0.9430 = 1/1.123274 = 811.20/911.20, the Rs 100 dividend on the cum close. With Polyplex prices before 2021-02-17 × 1.123274: 2021 gap +0.17 pp, 2019-2026 +0.103 pp/yr, G0 PASS. The ex-date and the Rs 100 come from a web search (Motilal Oswal; Business Standard 2021-02-10); the DB has no announcement for it. 142 steps of 2% or more were found over all four parents; none in 2019-2026 matches a published-NAV difference.
**Falsified by:** any held stock other than Polyplex whose Eikon-to-unadjusted ratio steps by 2% or more while held and whose date shows a matching one-day gap between rebuild and published NAV; or the corrected rebuild failing G0 on any parent.
**Cross-check:**
```bash
python data/parent_rebuild_hm.py                     # g0_gate.csv
python data/diagnose_0007_2021_gap.py --scan         # parts A-D, about 3 minutes, needs wm-aiReports/.env
```

Next free IDs: F-AA-D16, F-AA-S04, F-AA-M02. F-AA-D11, D12, D14 and D15 are in `data/review_decisions.json` (D15, the eight sessions D18 has and D17 skips, was added by T03 Step 0); D13 (LIQUIDCASE extension) is logged only in `AA/CLAUDE.md`.

## Files

| File | Contents |
|---|---|
| `summary.csv` | every parent × variant × switch timing × window: CAGRs, gap, tracking error, day counts |
| `daily.csv`, `yearly.csv` | daily levels (model and published, both 100 on the first common day) and calendar-year returns, avail_ohlc4 |
| `holdings_vs_history.csv` | matrix holdings against the rebalance history, per basket |
| `ohlc_coverage.csv`, `switch_prices_missing.csv` | price coverage |
| `g0_gate.csv` | G0 gate per parent and variant (listed weights) |
| `price_source_steps.csv` | held-stock steps of 2% or more, `ohlcv_eikon` against `merged_historical_data_with_rics` (written by `data/diagnose_0007_2021_gap.py --scan`) |
| `../holdings_matrix/price_corrections.csv` | factors that undo Eikon adjustments the published index does not make (F-AA-D14) |
