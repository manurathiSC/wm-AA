# T11 back-calculation pack: rebuild every T11 NAV by hand

Window **2014-09-01 → 2019-01-02**, 1,070 NSE sessions (`idx` 0…1069), four parents (SCMO_0003, 0007, 0010, 0029). Base **NAV = 1.000 at 2014-09-01's close**.

This pack has every number the T11 engine used to make its NAV series:
- **hold_parent**: the rebuilt parent index, always in the parent's stocks.
- **strategy_fixed50**: Part A, the three-index switch with a 50/50 GOLDBEES/cash sleeve.
- **strategy**: Part B, the same switch with the MAUc1-timed 80/20 or 20/80 sleeve.

Each run is given at 0, 20.8 and 50 bps round trip. `hold_parent` at 0 bps is the "rebuilt parent NAV" (`../headline/parent_nav_2014-09-01_2019-01-02.csv`, column `hold_parent_0bps`). It is **not validated against any published NAV before 2019-01-02**.

Made by `tests/T11/backcalc_export.py` from the engine's own arrays. `tests/T11/backcalc_verify.py` imports nothing from the engine and rebuilds all 36 series from these files alone. Every series matches `../headline/daily_nav.csv` to ≤ 2.3e-15 relative, and `stats.csv` (end NAV, CAGR, max DD, vol) to 1e-12. Run both from `AA/`.

## Files

| File | Rows are | What you use it for |
|---|---|---|
| `baskets.csv` | book × basket (19 per book: 1 `initial` + 18 `change`) | `available_date`; `session_date` = first NSE session on or after it (the trade day); `idx`; `n_held`; `raw_weight_sum` |
| `basket_weights.csv` | book × basket × stock (non-zero only) | `raw_weight` as listed (Postgres `smallcase_rebal_historical`); `weight` = raw_weight / raw_weight_sum (renormalised to 1; **this is what's traded**) |
| `stock_prices_long.csv` | book × session × stock (every stock ever held in the window) | `open_raw…close_raw` = D18 bar as on file (Eikon, price return, NaN = no bar); `src` (db / export / carried); `correction_factor` (≠ 1 only for POLYPLEX in SCMO_0007: 1.123274, F-AA-D14); `open…close` = corrected; `ohlc4`; **`close_used`** (valuation) and **`fill_used`** (trade price) |
| `close_used_<book>.csv`, `fill_used_<book>.csv` | session × stock (wide) | The same two columns as a matrix, for a spreadsheet |
| `sessions_gold_cash.csv` | book × session | GOLDBEES raw OHLC (D09), MCX gold H/L/C (D24b daily), each de-spike step, **`goldbees_close_used`**, **`goldbees_fill_used`**, **`lbes_level_used`** (cash, LBES as-of); flags `gb_has_own_bar`, `gb_has_mcx_range`. Identical across books |
| `decisions.csv` | book × weekly decision (228) | `decision_date`, `decision_idx`, `trade_date`; the three index SIGNs and the Master row dates read (`label_*`); `state` (1 = IN iff all three BUY); `sign_MAUc1`, `g`, `gw` (0.8 / 0.2) |
| `holdings_units.csv` | book × run × cost × holding interval × instrument | **Units held** from `from_date`'s close through `to_date` (event 0 = the free initial position at T0); `close_on_from_date`, `value_at_close` |
| `trades_summary.csv` | book × run × cost × trade | `V_at_fill`, `traded`, `ow_per_side`, `cost`, `k_scale`, `V_after_at_fill`, `nav_close_after`, `e_after`, `gw_after`, `basket_eff` |
| `trade_lines.csv` | trade × instrument | `fill_price`, `units_before`, `value_before_at_fill`, `target_weight`, `target_value_precost`, `abs_traded`, `units_after`, `value_after_at_fill` |
| `nav_daily.csv` | book × session × run × cost | `stock_value`, `goldbees_value`, `lbes_value`, `nav` (= their sum) |
| `T11_backcalc.xlsx` | Excel workbook | All three runs with live formulas. Hold the parent: raw weights → renormalised → units per basket. Part A and Part B: the weekly Master rows of Nifty 100, Midcap 100, Smallcap 100 and MAUc1 (`IndexSignals`) → each decision's SIGNs (latest row on or before the decision date) → state and gold weight → GOLDBEES de-spike → trade or not on each of 240 candidate sessions → V, traded, cost, k → stock, GOLDBEES and cash units. Then daily NAV → stats. To check each move in or out against the three signals: `Signals` (filter "Equity move"; which SIGNs changed, which are on SELL), the signal columns U–AC beside every RuleA/RuleB row, and `InOut` (every session, all parents). Edit `Inputs!C4` (cost in bps). Built by `tests/T11/backcalc_workbook.py`. Checked in Excel 16 at 0, 20.8 and 50 bps: 412,850 formulas, 0 errors, trade counts equal, max daily NAV gap 4.4e-16 against the engine; the SIGNs and Master row dates read equal `decisions.csv` in all 228 weeks, and the equity held agrees with the signals in every row and session |

The upstream raw files and their sha256 are in `../headline/inputs.csv`. You need nothing outside this folder to rebuild the NAVs. No stock lacks a bar on T0, so nothing comes from before 2014-09-01.

## The formulas

**Prices** (per stock *i*, session *t*)
- corrected = raw × correction_factor
- OHLC4 = (O + H + L + C) / 4, or the close if O, H or L is blank
- close_used(i,t) = the last corrected close on or before *t*. This covers sessions with no bar: 2017-10-19 (no D18 bar for any stock) and the thin Muhurat sessions 2016-10-30 and 2018-11-07.
- fill_used(i,t) = OHLC4 if the stock has a bar at *t*, else close_used

**GOLDBEES** (used only by Part A/B when out)
- band = (MCX high − MCX low) / MCX close + 0.005
- O and L are clipped to [close·(1−band), close·(1+band)] and H is clipped above. Then H = max(H, O, C) and L = min(L, O, C).
- fill = (O + H + L + C) / 4. If the day has no MCX range, the fill is the raw OHLC4.
- 2016-10-30 has no GOLDBEES bar: the previous close is both the value and the fill.

**Cash**: LBES level as-of on each session. Cash units × level is the value.

**Initial position (T0 = 2014-09-01, no cost)**: basket 0 at weights wᵢ, bought at fill_used(i,0) and scaled so NAV = 1 at T0's close.

  uᵢ = (wᵢ / fillᵢ(0)) / Σⱼ (wⱼ / fillⱼ(0)) · closeⱼ(0)

The rule starts IN in every run, so there's no gold or cash at T0.

**Daily NAV between trades**

  NAV(t) = Σᵢ uᵢ · close_usedᵢ(t) + u_gold · goldbees_close_used(t) + u_cash · lbes_level_used(t)

**When a trade happens** (each is filled on its session at fill prices)
- **Switch.** On `trade_date` (the session after decision *j*) if `state` changed, or if state = 0 and `gw` changed. `gw` changes only in Part B; Part A and hold_parent use gw = 0.5. A gold flip while IN is not a trade. The last decision, 2019-01-02, is not traded.
- **Basket change.** On a basket's `session_date` while IN (e > 0). While OUT nothing trades, and the next `switch_in` buys the basket then in force. If a basket change falls on an entry or exit session, it is that one trade.
- **hold_parent** has only the 18 basket changes.

**Trade arithmetic** at session *t*, new stock share e (1 or 0), gold weight gw, basket weights w:
1. V = Σᵢ uᵢ·fillᵢ(t) + u_gold·gold_fill(t) + u_cash·lbes(t)
2. Targets: stocks e·V·wᵢ; GOLDBEES (1−e)·gw·V; cash (1−e)·(1−gw)·V
3. traded = Σ |target − current value at fill| over every line, the outgoing stocks included
4. cost = traded × (bps / 2 / 10,000). So 20.8 bps gives 0.00104 per rupee traded.
5. k = (V − cost) / V. New units = k × target / fill price.

**Statistics**: years = (sessions − 1)/252 = 1069/252; CAGR = NAV_end^(1/years) − 1; max DD = min(NAV / running max − 1); vol = SD(daily returns) × √252.

## Worked example: SCMO_0003, hold the parent

**T0, 2014-09-01.** The initial basket has 15 stocks at raw weight 0.0667 each (sum 1.0005), so each w = 1/15 = 0.0666667.

AARTIDRUGS: O 93.75, H 94.3625, L 91.25, C 92.25, so OHLC4 = 92.903125. Over all 15 stocks, Σ (w/OHLC4)·close = 1.0062458. So u = (0.0666667 / 92.903125) / 1.0062458 = 0.000713 units.

**2014-09-02.** NAV = Σ u·close = **1.0162174** (`nav_daily.csv` row idx 1).

**First basket change, 2014-12-01 (idx 58), 20.8 bps.**
- V at fill = 1.311607. Five stocks leave (ARVIND, CCL, CENTUM, TVSSRICHAK, VSTTILLERS) and five enter (BANCOINDIA, BBTC, JKTYRE, KRBL, MINDACORP).
- Every target = 1.311607 / 15 = 0.087440.
- traded = 1.040104, so cost = 1.040104 × 0.00104 = 0.001082 and k = 0.999175.
- AARTIDRUGS fill 98.8188: units after = 0.999175 × 0.087440 / 98.8188 = 0.000884.
- NAV at that close = 1.301161 (1.302235 at 0 bps, where k = 1).

**End, 2019-01-02.** NAV 3.326255 at 0 bps, CAGR 32.75%, max DD −39.38%. Every line is in `trade_lines.csv` (filter book SCMO_0003, run hold_parent, cost_bps 20.8, idx 58).

## Caveats (from T11.md)

- **Price return**: dividends are not added back.
- **Manual exports**: nine manual Eikon exports for delisted stocks (`src = export`; provenance unrecorded) are held: 574 / 123 / 556 / 122 stock-sessions in 0003 / 0007 / 0010 / 0029.
- **Carried bars**: PRAKASH in SCMO_0010 has 3 (2017-08-08/09/10, `src = carried`).
- **No published check**: the 2019 seam against the published NAV is −0.22, +0.39, +0.45, +0.19 pp. Nothing checks the rebuild before 2019.
