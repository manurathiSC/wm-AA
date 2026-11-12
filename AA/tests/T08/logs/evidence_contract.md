# T08 evidence contract (shared by Steps 2, 3 and 4)

Written 2026-11-12 by the main agent from `T08.md` §2–§3 (frozen, wins over this file), `PLAN.md`, and the T06 evidence formats (`AA/tests/T06/evidence/headline/`). Where this file is silent, the T06 format and T06 engine behaviour apply unchanged. Evidence goes to `AA/tests/T08/evidence/<run>/` (headline run name: `headline`; smoke: `smoke`).

## Names

- **Books:** `SCMO_0003`, `SCMO_0007`, `SCMO_0010`, `SCMO_0029`. **Windows:** `full` (T0 → 2026-10-30), `live` (T0 = 2021-11-01, then weekly, → 2026-10-30). **Cash:** `lbes` (headline), `liq` (LIQUIDCASE, R2). **Costs:** 0, 20.8, 50 bps.
- **State arrays:** in-or-out `s` (1 = IN/parent, 0 = OUT); gold `g` (1 = BUY, 0 = SELL); sleeve gold weight `gw` = 0.8 if g = 1 else 0.2 (`fixed50` mode: 0.5 always).
- **Null families** (T08.md §2): `F1` = in-or-out N4.10 + real gold; `F2` = in-or-out N4.9 + real gold; `F3` = real in-or-out + gold N4.10-g; `F4` = real in-or-out + gold N4.9-g; `F5` = in-or-out N4.10 + gold N4.10-g together (same draw id; seeds `[6,id]` and `[11,6,id]`). Seeds: N4.9 `default_rng([3, id])`, N4.10 `[6, id]`, N4.9-g `[11, 3, id]`, N4.10-g `[11, 6, id]`; id = 0..1999. Gold N4.10-g bounds: BUY [2, 68], SELL [2, 28] (computed from the real series: lo = min(2, shortest spell of any state), hi = longest BUY / longest SELL; assert they equal 68 and 28 for this window and that every window/state table is feasible).
- **Run (`run` column) values:** `strategy` (the rule, timed sleeve), `strategy_fixed50` (same rule, sleeve 50/50 = T06's rule), `hold_parent`, `constant_mix` (50/50 non-stock share, T06's), `constant_mix_timed` (non-stock share split by w_d, rebalanced each decision's next session like constant_mix), `sleeve_only` (100% sleeve 50/50, T06's), `sleeve_only_timed` (100% sleeve timed by gold, trades only when g changes).
- **Trade `kind` values:** `switch_in`, `switch_out`, `basket_change`, `mix_rebalance` (as T06) and the new `sleeve_rebalance` (OUT on both sides, g changed). `e_after` is the stock share after the trade (1.0 or 0.0 for the strategy); new column `gw_after` is the sleeve's gold weight target after the trade (0.8/0.2/0.5; empty for hold_parent).

## Files

| File | Contents |
|---|---|
| `inputs.csv` | as T06 (`file, through, bytes, sha256, approved_row`), every file opened, includes D24 `Master_MAUc1.xlsx` and the 4 extended D17 files |
| `decisions.csv` | T06's columns, one row per weekly decision and book (full window; `j` from 0), plus `sign_MAUc1`, `label_MAUc1` (date of the MAUc1 row read), `g` (0/1), `gw` |
| `gold_signal.csv` | `book,j,decision_date,label_MAUc1,sign_MAUc1,g,gw` (the gold series alone) |
| `stats.csv` | T06's columns for every `kind` in the run list above (column `kind` = run name), per book, window (`full`/`live`), cash, cost; plus `sleeve_trades` (count of `sleeve_rebalance` trades) |
| `draws.csv` | one row per draw: `book,window,cash,cost_bps,family,io_null,gold_null,sleeve_mode,draw_id,` then T06's metric columns `end_nav,cagr,max_dd,vol,ulcer,days_below_10pct,longest_underwater,calmar,sessions,invested_weeks,n_in_spells,n_out_spells,spell_sig,strategy_sig,sessions_invested,in_lengths,out_lengths,` then `g_buy_weeks,n_buy_spells,n_sell_spells,g_spell_sig,real_g_spell_sig,g_buy_lengths,g_sell_lengths,sleeve_trades`. `io_null` ∈ {`N4.10`,`N4.9`,`real`}, `gold_null` ∈ {`real`,`N4.10-g`,`N4.9-g`}, `sleeve_mode` ∈ {`timed`,`fixed50`}. Lengths strings joined by `|` in order. 2,000 draws per row group |
| rows in `draws.csv` | **full, lbes:** F1, F2, F3, F4 at 0 / 20.8 / 50 bps (timed); F5 at 20.8; F1 and F2 with `sleeve_mode=fixed50` at 20.8 (R6). **full, liq:** F1 and F3 at 20.8. **live, lbes:** F1 and F3 at 20.8 |
| `draw_states.npz` | uint8 arrays shape (2000, weeks), keys `"<book>|<window>|io|N4.9"`, `"…|io|N4.10"`, `"…|gold|N4.9-g"`, `"…|gold|N4.10-g"` for `window` in {full, live}. F5 and R6 reuse these (same ids); `liq` reuses `full` |
| `real_states.npz` | uint8 arrays `"<book>|<window>|io"` and `"<book>|<window>|gold"`, shape (weeks,) |
| `draw_curves_20.8.npz` | float32 daily NAV of every F1 and F3 draw, full window, lbes, timed, 20.8 bps; keys `"<book>|F1_<id>"`, `"<book>|F3_<id>"` |
| `trades.csv` | T06's columns (`book,cost_bps,run,date,idx,kind,e_after,basket_eff,V,traded,cost,nav_close_after`) plus `gw_after`; for the strategy and comparators, all costs |
| `sleeve_trades.csv` | the strategy's exits and sleeve rebalances: `book,cost_bps,decision_date,date,kind,g_before,g_after,gw_before,gw_after,gold_value_before,cash_value_before,gold_value_after,cash_value_after,traded,cost,gold_fill_raw` (`gold_fill_raw` true when the GOLDBEES fill is the raw OHLC4 after the MCX range ends) |
| `positions.csv`, `daily_nav.csv`, `g_engine.csv` | as T06 (run names as above; `g_engine` is always-in against the published NAV, G0, over the whole window) |
| `count_table.json` | `{"bounds": {"io": {"lo","hi_in","hi_out"}, "gold": {"lo_buy","hi_buy","lo_sell","hi_sell"}}, "tables": {"<book>|<window>|<io|gold>|<state>": {"weeks_S","spells_k","lo","hi","n_ways" (exact integer as string)}}}` with state `in`/`out` for io and `buy`/`sell` for gold |
| `sampler_selftest.json` | V5 results (as T06, plus the gold tables) |
| `regression_t06.json` | V4: `decisions` (compared, mismatches), `nav` (rows compared, worst relative difference per run name against T06's `strategy`, `hold_parent`, `sleeve_only`; `strategy_fixed50` is compared with T06's `strategy`), `draws20` (T06's first 20 N4.10 draws replayed; worst relative difference), `g0`, `d17_overlap`, `gold_vs_d24`, `nav_compared_to`, `tolerance_rel`, `pass` |
| `audit.json` | as T06: `readings`, `books`, `v3`, `v4`, `v5`, **`v6`** (sleeve identity: trades checked, worst target gap, cost identity, continuity at 0 cost, constant-g no-trade check), `data`, `run` (command, draws, seconds, python/numpy/pandas versions), `prereg_sha256`, `gates` (V2–V6 pass flags), counts of point-in-time checks, sleeve trades per book, raw-fill sessions and the raw-fill trades the strategy makes |
| `verify_t08.json` | written by `analysis/verify_t08.py` |

`analysis.log` and `evidence/report.html` are written by `tests/T08/analyse.py` / `report.py` (Step 4/6), outside `evidence/<run>/`'s engine files.

## Engine behaviour that the verifier and the scripts must match (T08.md §3 steps 3–10)

1. Decision series: as T06 plus `g_d` = SIGN of the latest `Master_MAUc1.xlsx` row dated on or before the decision date (same as-of rule; one-week-stale rule as for the index Masters). Window end = last D03 row = 2026-10-30; the decision there is made, not traded.
2. Target after a decision: IN → 100% parent; OUT → gold weight `gw` of the sleeve value, cash `1 − gw`. Initial position at T0 free, sleeve at `gw` of T0's `g`.
3. A trade exists on the next D17 session after decision d iff `e` changed or (`e` stayed 0 and `gw` changed). Exit: sell basket, buy GOLDBEES and cash at `gw_d` of proceeds after cost. Sleeve rebalance: targets `gw_d·V'` GOLDBEES and `(1−gw_d)·V'` cash with `V' = V − cost`, `cost = ow·traded`, `traded = |ΔGOLDBEES| + |Δcash|` evaluated as T06's `trade()` does (targets scaled by `k = (V − cost)/V` as T06). Same-decision exit and flip = one exit at the new `gw`. A flip while IN: nothing. Basket changes while OUT: skipped (as T06).
4. Fills: stocks and cash as T06; GOLDBEES de-spiked OHLC4 where the D12 MCX range covers the session, raw OHLC4 after 2026-09-28.
5. `fixed50` mode: `gw = 0.5` always, no sleeve trades; must equal T06's `strategy` NAV exactly on the overlap (to 2026-10-22).
6. Comparators as the run list above; `constant_mix` / `constant_mix_timed` use f = invested weeks ÷ weeks of the strategy.
7. Statistics, percentile and p-value definitions, MDE: T08.md §2–§3.

## Verifier-specific deltas from `verify_t06.py` (Step 3)

The verifier is a fork of `AA/analysis/verify_t06.py` (read it freely; **never read `AA/analysis/t08_engine.py` or any T08 evidence produced by it before the code is written**). Required changes: its own `simulate` generalised with a per-decision `gw` (init, switch construction, targets, trade kinds incl. `sleeve_rebalance`, and the closed form segments); `decisions_for_window` adds the gold column from `Master_MAUc1.xlsx`; new checks `C-gold` (g series vs D24 weekly csv and vs raw Master), `C-sleeve` (every sleeve trade: targets, cost identity, value conservation, kind, dates, raw-fill flag), `C-gold-states` (every F3/F4/F5 draw: weeks, first state, spell counts, BUY weeks, N4.10-g bounds, N4.9-g sorted lengths), `C-count` for the gold tables (inclusion–exclusion), `C-support` for the gold bounds, `C-draw-nav` for all families (first 20 and 20 random per book, family, window, sleeve mode), `C-t06` (V4: replays T06's saved strategy, hold_parent, sleeve_only NAV and T06's first 20 N4.10 draws against `strategy_fixed50` / the draw curves on the overlap), `C-corrupt` extended (flip a gold week, remove a sleeve trade, plus T06's three corruptions); `SCRATCH` path fixed; exits 0 only if rows were compared and none failed; writes `verify_t08.json` with counts. Exempt from "through covers END": D19, D05, D12 (as T06), and D17/D24 are read only up to END.

## Done criteria per step

- **Step 2:** `python analysis/t08_engine.py --run smoke --draws 20 --quick` exits 0; V3–V6 pass on smoke; `regression_t06.json` passes (the key proof); opening a non-approved file raises; evidence written per this contract.
- **Step 3:** `python -c "import verify_t08"` clean from `AA/analysis/`; the verifier validated on a mock evidence set built from the contract and on T06's evidence where applicable (V4 replay); log written.
- **Step 4:** all scripts pass `python -m py_compile`; tested on a synthetic evidence directory built from this contract (small draws), including the corruption tests of `check_page.py` and the hover test; log written.
