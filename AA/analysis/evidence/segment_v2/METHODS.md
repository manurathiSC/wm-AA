# Methods appendix: "Holding by Segment" (Study 3, segment v2)

Companion to `report.html` in this folder. Every chart and table on the page
is listed here with its formula, denominator, null (where there is one) and
source files. The rule, gates and thresholds were fixed in
`PREREGISTRATION.md` before any run (sha256 `113a5133c18a…`, recorded in
`audit.json` and `gates.json`).

## 0. Conventions that apply everywhere

| Item | Definition | Code |
|---|---|---|
| Window | 2021-11-03 → 2026-08-21: 1,187 calendar sessions, 251 weekly reviews | `segment_v2.common_start`, `window_reviews` |
| Rebase | Every series = 1.0 at 2021-11-03, the last session on or before the first review (2021-11-05) that exists in the published NAV files | `run_segment_v2.rebase` |
| CAGR | `(end/start)^(365.25/days) − 1`, days counted from the base date | `stats_v2.cagr` |
| Vol | daily-return std × √252 | `stats_v2.absolute` |
| Sharpe / Sortino | (CAGR − cash CAGR) / vol, or / downside vol. Cash is the LBES-adjusted LIQUIDBEES level. Study 1 used CAGR/vol with rf = 0, so these are not comparable with Study 1's Sharpe | `stats_v2.absolute` |
| Max DD | min of `level / cummax(level) − 1` on daily levels, with peak, trough and first recovery date | `stats_v2.drawdown` |
| Best / worst year | full calendar years 2022–2025 only; 2021 and 2026 are partial and marked `*` in the yearly table | `stats_v2.absolute` |
| Relative stats | on the overlap with the reference, both rebased at the overlap start. TE = std(daily active) × √252. IR = mean(daily active) × 252 / TE. Beta and correlation on daily returns. Up/down capture on **monthly** returns: mean series return in up (down) months of the reference / mean reference return in those months. Hit rate = share of rolling 252-session windows where the series beat the reference | `stats_v2.relative` |
| D | CAGR(new rule) − CAGR(current rule re-simulated), same cost level | `run_segment_v2.main` |
| Costs | 0 / 20.8 / 50 bps round trip, half charged per side on each position's traded value. The primary level is 20.8 | `segment_v2.Simulator.run` |
| Cost drag | CAGR at 0 bps − CAGR at the chosen cost | `segment_v2_report.py` |
| Turnover | Σ(traded value / NAV at the fill) / years. Buys and sells both count | `run_segment_v2.main` |

## 1. The rule and its inputs

- **Parent holdings.** `AA/Historical Data/frozen_2026-09-25/Rebalance_history/Rebalance_history_by_scid_SCMO_{0003,0007,0010,0029}.csv`. These are frozen copies of the Drive exports, with sha256 values in `SHA256SUMS.txt`. Parents are keyed on `availableDate`. Holdings are **matched on ISIN**, because the Sep-2026 export writes current tickers onto historical rows: Gujarat Gas `INE844O01030` is `GUJENERGY` in the file but `GUJGASLTD` in the DB until 2026-06-30. Trailing `*` is stripped from tickers, and a blank ticker (0029's BSE Ltd row, 2025-06-03) is filled from ISIN. See `segment_v2_data.resolve_holdings`.
- **Signals.** The `SIGN` column of the frozen `Master_{Nifty100,NiftyMidcap150,NiftySmallcap250,NiftyMicrocap250,SC100}.xlsx`. The review grid is the union of the four event indices' dates. Microcap 250 falls back to Smallcap 250 on its 15 in-window reviews with no SIGN (2021-11-05 → 2022-02-11). See `segment_v2.load_signs`, `effective_signs`.
- **Tags** (`segment_v2.HybridTagger`). A cascade, first match wins:
  1. manual override (`AA/Historical Data/bucket_overrides.csv`, empty);
  2. membership in the latest `index_constituents_monthly` snapshot on or before the review (six snapshots, 2026-04-09 → 2026-09-01; the last falls after the window), with priority N100 > MC150 > SC250 > Micro250;
  3. `nonmember_rank`: a snapshot exists but the stock is in no index, so use its rank band;
  4. `rank`: before 2026-04-09, the month-end rank from `public.mcap_based_universe` (ordinary shares, ranked on `mcap` descending), with bands 1–100 / 101–250 / 251–500 / 501–900;
  5. `rank>900`: use the Microcap 250 signal;
  6. `unranked`: use the Smallcap 250 signal.

  The v2 rank cache (`cache/mcap_ranks_monthly_v2.csv`) reproduces the v1 cache's ranks on 100% of 173,708 rows across 84 common snapshots. Steps 5 and 6 never fired in the window. Step 3 fired on 29 holding-weeks: Happy Forgings (0042, rank 436–481) and TCI (0043, rank 599–672).
- **Events** (`segment_v2._events`). An event is the first review, any review where one of the four effective signals differs from the previous review, or a change in the basket's `availableDate`. There are 48 events per book, the same 48 on every book: 19 parent rebalances, 12 N100 flips, 14 MC150, 12 SC250 and 12 Micro250 (a review can carry several). Tags are read only at events.
- **Targets** (`segment_v2.build_sleeve`). Hold a name iff its signal index is BUY, at its parent weight. The sleeve weight is 1 − the sum of held weights, split 50% GOLDBEES and 50% cash.
- **Comparators.**
  - `build_production`: count-weighted FS ≥ 0.60, re-tagged every review on the same tags.
  - `build_whole_book_and`: N100 AND SC100.
  - `build_whole_book_and(keys=(SC100,))` and `(SC250,)`: Smallcap 100 only and Smallcap 250 only. The whole book goes to the sleeve whenever that one index is SELL, whatever the market-cap mix. SC100-only is what 0042/0043 actually ran live, and it was Study 1's best single index.
  - `build_parent`: the parent itself.
- **Mechanics** (`segment_v2.Simulator`). These are identical to Study 2's `segment_backtest.simulate`, except for the close fallback (§5, deviation 3):
  - positions are held in units;
  - fills at the next session's OHLC4. When a leg is missing, the fill is at that session's close if there is one; otherwise the name cannot be filled;
  - interior sessions marked at forward-filled close;
  - a review whose targets are unchanged does not trade;
  - names that cannot be filled are dropped and the rest renormalised.
- **Prices (primary): `ohlcv_eikon`, joined on `quote_id`** (`segment_v2_data.eikon_ohlcv`, cached in `cache/keyed_ohlcv_eikon_v2.parquet`).
  - **Keying.** Each held ISIN is mapped to every `quote_id` that `symbology_changes` links to it (`cache/isin_quote_id_v2.csv`). A `quote_id` is the permanent instrument key, so it survives ticker and RIC changes and delist/relist. No ISIN has two live quote_ids on the same date.
  - **Coverage.** All 257 securities held in the window can be filled at every entry session (`unfillable_holdings.csv` is empty). That includes Kirloskar Ferrous (KRFI.NS) for 2021–22, EQUITAS (EQHL.NS^B23) and SHRIRAMCIT (SHCU.NS^K22).
  - **Basis.** Split-, bonus- and demerger-adjusted, not dividend-adjusted. The per-stock median Eikon−Kite log-return drift is +0.006 pp/yr, and ITC's is +0.12. So the series is price return, the same basis as the Nifty benchmarks.
  - **Fill rule.** OHLC4 on the fill session. If a leg is missing but the session has a close, the fill is at that close; 14 cells use this.
- **Prices (sensitivity): Kite, `merged_historical_data_with_rics`** (`cache/keyed_ohlcv_v2.parquet`). Fetched by every ticker an ISIN has carried (market-cap table plus `symbology_changes` aliases) and spliced by date. Its known defects, which are why it is no longer primary:
  - **No history across delist/relist.** Kirloskar Ferrous has no bars before 2026-04-20.
  - **Missing names.** There are no rows for EQUITAS or SHRIRAMCIT.
  - **No demerger or special-dividend adjustment.** Siemens −25.1% on 2025-04-07, NIIT −44.4% on 2023-06-08, Aster DM −22.2% on 2024-04-23, ITC on 2025-01-06.
  - **Missing opens.** 2,401 of 2,768 rows on 2025-11-24.
  - **Effect.** On Kite prices D is −2.25 / −0.43 / +2.09 / +2.95 (the "Kite prices" sensitivity).
- **Sleeve prices.** Gold is GOLDBEES closes (`cache/defensive_etf_closes.csv`). Cash is `LBES_Adjusted_Price_data_2026_08_10.csv`, with the short tail at the trailing rate.

## 2. Gates: formulas and results (`gates.json`)

| Gate | Statistic | Denominator / null | Result |
|---|---|---|---|
| G0 | CAGR(harness parent) − CAGR(published parent) | none | −0.96 / −0.19 / −0.91 / **−2.88** pp → FAIL (0045 only) |
| G1 | D at 20.8 bps | none | −2.51 / −0.43 / **+2.09** / **+2.97** → 2 of 4, FAIL |
| G2 | CAGR(new rule @20.8) − CAGR(static mix). Static mix = e̅·r(harness parent, gross) + (1−e̅)·r(50/50 sleeve), rebalanced daily, zero cost, where e̅ is the session-average target equity weight of the new rule (0.60 / 0.58 / 0.63 / 0.62) | none | −0.18 / +4.16 / +2.48 / −0.25 → 2 of 4, FAIL |
| G3 | D with gold share 0, applied to both the new rule and the current rule | none | −0.77 / −0.18 / +1.27 / +2.07 → 2 of 4, FAIL |
| G4 | share(D_k > 0) over circular shifts k = 8 … 243 of the whole in-window effective-SIGN matrix (236 shifts) | null = the shift distribution | 50% / 51% / 45% / 68% → 0 of 4, FAIL |
| G5 | 10th percentile of D over 500 re-labellings | null = label-noise distribution (seed 20260924) | −3.38 / −1.63 / +0.50 / +0.97 → 2 of 4, FAIL |

**Verdict: REJECTED, conditional on the unresolved G0 gap** (`segment_v2_nulls.py`).

**G5 error model** (`null_labels_error_model.csv`). This is P(true bucket | predicted rank band), pooled over the six membership snapshots and 16,907 universe rows. It is matched by ISIN, with truth "Unknown" meaning the stock is in no index.

| Predicted | P(predicted band is correct) |
|---|---|
| Largecap | 0.87 |
| Midcap | 0.79 |
| Smallcap | 0.69 |
| Microcap | 0.49, with 0.36 truly in no index |
| rank > 900 | 0.99 not in any index |

- **How draws are made.** A draw is taken once per (security, rank snapshot) and shared across books. A drawn "Unknown" keeps the original band, which is what cascade step 3 would do.
- **What is never perturbed.** Membership-sourced tags.
- **Independence caveat.** Draws are independent per security, which ignores correlated errors near a band edge.

**Holdings-level tag accuracy** (`tag_accuracy_holdings.csv`). On these books' own holdings at each membership snapshot, the monthly rank band agrees with real membership on 78.7% of rows (79.4% weight-weighted).

## 3. Report elements

| Element | Formula / construction | Source files |
|---|---|---|
| Gate table | as §2 | `gates.json`, `gates_g1_g3.json`, `gate_g0.json` |
| Across the four books | CAGRs, D, new rule − published parent / AA, excess CAGR over the style blend (from 2022-01-11), max DD | `headline.csv` |
| Growth of 1 | daily NAV rebased at 2021-11-03, log scale, 20.8 bps for simulated series | `nav_curves.csv` (`{aa}\|{strategy}\|20.8`, `{aa}\|published_parent`, `{aa}\|published_aa`, `{aa}\|style_blend`, `bench\|…`) |
| Drawdown | `level / cummax − 1` of the same series; the end label shows each series' worst | `nav_curves.csv` |
| Equity held | target equity weight in force from each fill (new rule: Σ held parent weights; current rule: 0 or 1) | `exposure_daily.csv` |
| Relative wealth | new rule NAV ÷ published parent NAV, and ÷ published AA NAV | `nav_curves.csv` |
| Return and risk / relative stats | §0 definitions; the static-mix row is G2's static mix | `stats_panel.csv`, `scorecard.csv` |
| Calendar-year returns | year-end level / previous year-end level − 1 (the first year runs from the base date) | `yearly_returns.csv` |
| Rebalance history | one row per event. Weight before = units × fill price / NAV before the trade; after = filled target weight. Action: buy / sell / hold / rebalance (a held name whose weight changed by > 0.05 pp at a traded event) / stay out. Turnover as §0 | `rebalance_summary.csv`, `rebalance_history.csv`, `trade_log.csv` |
| Market-cap mix | Σ parent weight by bucket at every review under the hybrid tagger. `rank>900` and `unranked` are shown as Unknown. The dashed line is the first membership snapshot | `bucket_distribution.csv`, `bucket_tags.csv` |
| G4 / G5 histograms | 0.5 pp bins of D across shifts or draws; dark line = observed D | `null_shift.csv`, `null_labels.csv` |
| Sensitivities | D at 20.8 bps against the current rule on the same tags as the variant | `sensitivities.csv` |
| G0 table | published vs replica vs harness CAGR. Replica = each basket bought at its `availableDate` close at parent weights, buy-and-hold at closes to the next `availableDate` | `parent_gap_summary.csv`, `parent_gap_periods.csv`, `parent_gap_jumps.csv` |

## 4. Verification (`regression.json`, `verification.json`, all passing)

- **Study 2 reproduces.** Study 2's own code on its original inputs (the `_v0` exports, the v1 price cache, semi-annual ranks, `micro_proxy`) reproduces `segment_v1/scorecard.csv` to |ΔCAGR| < 1e-16.
- **The v2 engine matches it.** On identical inputs the v2 builders and `Simulator` match Study 2's targets on every review, and its NAVs to 4e-15, at 0 and 20.8 bps.
- **Unit checks on 0044:**
  - on the 117 weeks with every index in BUY, the book holds exactly the parent;
  - on the 73 weeks with every index in SELL, it holds 100% sleeve;
  - NAV is monotonic in cost;
  - targets never change between events. 0 non-event trade(s) came from a name becoming unfillable.
- **Point in time.** No tag snapshot is after its review. Tag sources are `rank` before 2026-04-09 and `membership` / `nonmember_rank` after. The Microcap fallback covers exactly 15 reviews.
- **The report ties to its evidence.** Every scorecard CAGR and max DD recomputes from `nav_curves.csv` to 1e-12, and the last traded NAV in the rebalance history matches the curve.
- **Published series tie to Study 1.** On Study 1's window and CAGR convention they match its scorecard to 7e-15. The v2 CAGR convention (years from the base date, not the first return date) differs from Study 1's by ≤ 0.014 pp.

## 5. Deviations from pre-registration

1. **Common start 2021-11-03, not 2021-11-01.** The first in-window review is 2021-11-05 (a market holiday), and no simulated book can hold anything before its first fill on 2021-11-08. The 2021-11-04 Diwali session exists in the trading calendar but not in `parentIndices.csv` / `indices.csv`, so rebasing there would hand the published series an extra day's return. The window end is unchanged. This affects the published-NAV comparisons, not D.
2. **Exploratory G4 run on `sleeve_n100gate`.** This was added after seeing that the sensitivity had the largest D. It is labelled exploratory in `gates.json` and on the page, and it does not enter the verdict.
3. **Price-data repairs, found after the first run when a rebalance review showed Kirloskar Ferrous at 0%.** The whole pipeline was re-run afterwards, and every number in the report is from the repaired run. The repairs and their effect on G0 and D:
   - **Symbology aliases.** Renamed stocks are priced through their old ticker. This restores Cemindia Projects / ITD Cementation for 0029 over 2023-06 → 2024-03, about 8% of the book.
   - **Close fallback for incomplete bars.** On 2025-11-24, Study 2's "drop what can't fill and renormalise" rule had put every book into its 1–3 names with a full bar for one week: up to 185% turnover, twice, in every strategy.
   - **Coverage checked at entry sessions.** The earlier check had passed Kirloskar Ferrous because it has rows from 2026.
   - **Effect on G0:** 0003 −0.92 → −1.89, 0029 −4.72 → −3.00.
   - **Effect on D:** 0042 −2.14 → −2.25, 0044 +2.07 → +2.09, 0045 +3.52 → +2.95; 0043 unchanged.
   - **The verdict is unchanged.**
   - `regression_v2.py` runs with the fallback off, and still reproduces Study 2 exactly.
4. **A new label in the rebalance history.** "no price" replaces the misleading "buy" for a name the rule holds but cannot fill. It no longer occurs on Eikon prices.
5. **Price source switched from Kite to `ohlcv_eikon` (joined on `quote_id`)**, on the data owner's advice after the second run. The reasons are the Kite defects in §1. The whole pipeline was re-run.
   - **G0** 0042 −1.89 → −0.96 (now inside the bar), 0044 −0.27 → −0.91, 0045 −3.00 → −2.88.
   - **D** 0042 −2.25 → −2.51; the other three move by ≤ 0.02.
   - **G2** flips from pass (3 of 4) to fail (2 of 4). On 0042, with Kirloskar Ferrous priced, the static mix now edges the rule's timing by 0.18 pp.
   - **Verdict** unchanged: REJECTED, still conditional on G0 through 0045.
   - **Kite reference.** The Kite-price result is kept as a sensitivity, and `regression_v2.py` still runs Study 2's Kite inputs.

6. **Two reference comparators added after the results, at the user's request.** These are Smallcap 100 only and Smallcap 250 only, whole book, on the same sleeve, prices and costs. They are not in any gate and do not change the verdict. At 20.8 bps:
   - **SC100-only CAGR:** 20.33 / 14.48 / 21.36 / 20.16%, averaging 19.1% against the new rule's 17.2%.
   - **New rule − SC100-only:** −5.10 / +0.64 / +0.13 / −3.40 pp/yr.
   - **Selection caveat:** both SC100-only and N100 AND SC100 were selected in-sample on this window in Study 1.
   - **Where it is reported:** `headline.csv` (`cagr_sc100_only`, `sleeve_minus_sc100_only`, and the SC250 equivalents), `scorecard.csv`, and the report's "Every rule, side by side" table.

7. **The section "N100 AND SC100 applied to all four books" was added at the user's request.** It is still a reference comparator (`build_whole_book_and`, keys N100 and SC100), not gated.
   - **Rule:** every Friday, if Nifty 100 and Nifty Smallcap 100 are both BUY, hold the whole parent basket; otherwise hold 100% in the 50/50 sleeve. Same fills and costs as every other rule.
   - **All-cash variant:** the same steps with gold share 0 (`nav_curves.csv`: `{aa}|n100_and_sc100_allcash|20.8`).
   - **Switch log:** `n100_sc100_trades.csv`, with both signals at every trade and a trigger of first review / signal switch / parent rebalance.
   - **Shaded weeks:** the weeks its target equity weight is below 0.5 (`exposure_daily.csv`).
   - **Results at 20.8 bps:** CAGR 26.52 / 21.26 / 28.33 / 26.58%, averaging 25.7%. With an all-cash sleeve the average is 16.7%, against the parents' 13.7%. In equity 49% of weeks, 9 signal switches.

Nothing else was changed after results existed: no thresholds, statistics, draw counts, seeds or windows.

## 6. Limitations that bear on the conclusion

- **One history.** All four books share the same 48 events (the parents rebalance on the same dates and the signals are global). The four books are therefore not four independent tests.
- **Membership tags were untestable here.** All four index signals agreed every week from 2026-04-09 to 2026-08-21, so membership tags could not change a trade.
- **The G0 gap on 0045 (−2.88 pp/yr).** It splits into index convention (−1.24), which is the platform's rebalance-day fills, and execution cadence (−1.64), where a new parent basket is picked up at the next Friday review, as the live AA books do. D is unaffected because both arms share the harness. "New rule − published parent" on 0045 carries the full gap. The other three parents track their published NAVs to within 1 pp/yr on Eikon prices.
- **Price-return benchmarks.** Nifty indices exclude dividends.
- **The narrower claim is untested.** That segment holding helps books with strong-selection parents is a **new hypothesis generated by this data**. It needs out-of-sample books or a later window.
