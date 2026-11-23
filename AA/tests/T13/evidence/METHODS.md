# T13 methods (companion to `report.html`)

The pre-registration is `../T13.md` §1–§3 (frozen, sha256 `ab1d6f4747e6…`; `python tests/T13/check_prereg.py`). This file says how the evidence in `headline/` was made. Nothing here changes §1–§3.

## What is run

T11 with one change: **the book holds the parent when at least two of the three weekly index SIGNs (Nifty 100, Midcap 100, Smallcap 100) are BUY** (T11: all three). Part A (sleeve fixed 50/50) and Part B (sleeve 80/20 or 20/80 by the weekly MAUc1 supertrend) on the **four real parents' own stocks**, SCMO_0003, 0007, 0010 and 0029, from 2014-09-01 to 2019-01-02. Trades are on the next session at OHLC4 with 10.4 bps a side (20.8 round trip primary; 0 and 50 as robustness). The first position (the basket effective 2014-09-01) is free; the 18 later basket changes are traded at the first session on or after each availableDate while the book holds the parent. T11's all-3 rule is run beside the rule on the same prices, baskets and costs (`strategy_all3`, `strategy_all3_fixed50`) as a descriptive comparator: no null, no pass mark.

## Inputs: only the APPROVED rows of `data/APPROVED_DATA.md` (as of 2026-11-18)

T11's inputs exactly: D18 stock OHLC (with the Polyplex correction), D19 basket weights, D05 basket dates, D26 the NSE calendar, D03 index Master SIGN, D24b the MAUc1 signal and its daily MCX range, D09 GOLDBEES, D11 cash (LBES; R2 LIQUIDCASE), D17 published NAVs for the 2019 seam check only. Every file read is listed with its sha256 in `headline/inputs.csv`. T11's stored `decisions.csv` and `daily_nav.csv` (and T06's and T08's stored NAVs) are read by gate V4(a) only, as test evidence.

## Nulls (2,000 seeded draws per book, cost and null; the four books share draws)

- **F1 (decides A1, A2 with the 50/50 sleeve, and C1, C2 with the timed sleeve):** the in-or-out series drawn as N4.10 (9 in-spells in [2, 30] summing to 115, 9 out-spells in [2, 33] summing to 113, starting IN). Seed `default_rng([16, 6, id])`. **F2:** N4.9 (the real spells shuffled), seed `[16, 3, id]`.
- **F3 (decides C3, C4):** the real in-or-out series, the gold signal drawn as N4.10-g (10 BUY spells in [2, 36] summing to 132, 9 SELL spells in [2, 19] summing to 96, starting BUY; T11's gold series). Seed `[16, 11, 6, id]`. **F4:** N4.9-g, seed `[16, 11, 3, id]`.
- **F5 (robustness):** an F1 draw and an F3 draw of the same id together.
- Bounds are the series' own (`lo = min(2, shortest)`, `hi = longest`), computed before any return was read (`../logs/step_1_spell_counts.json`).

## Gates

V1 `analysis/verify_t13.py` (independent; a fork of `verify_t11.py` written by a different agent from the engine's, which never opened either engine): 3,861,152 comparisons, 0 failures, 12 of 12 corruptions detected · V2 point in time and the Smallcap 100 restriction · V3 the nulls hold their tables · V4 identities and regressions: **(a1) the all-3 comparator equals T11's stored NAVs and decisions exactly**; (a2) with D17's dates the all-3 engine reproduces T08's and T06's stored 2019 NAVs to 2.2e-16; one-instrument identity; shared functions identical to `t11_engine.py` except the five intended; the 2019 seam within ±0.5 pp · V5 the samplers are exact · V6 sleeve, basket and cost identities. All pass (`../analysis.log`, `4.0b`).

## Robustness

R1 0 and 50 bps; R2 LIQUIDCASE cash (equals LBES to 1.3e-10 in daily return here); R3 the window from 2015-01-02; R4 pair agreement, with T11's stored percentiles as the main reference; R5 both timings random; R6 paired contrast; R7 price-quality sensitivity (as T11).

## The rebuilt parent NAV

`headline/parent_nav_2014-09-01_2019-01-02.csv`: per parent and session, hold-the-parent at 0 and 20.8 bps (identical to T11's) and the 2-of-3 rule's Part A and Part B NAV at 20.8 bps, base 1.000 on 2014-09-01. Caption in the sidecar `.md`: rebuilt from the parent's baskets and Eikon prices, not validated against a published NAV before 2019-01-02. Not approved data.

## Page checks

`check_page.py` recomputes every number, date and hover array on the page from the evidence: **2,464 checks, 0 failures** (run 2026-11-18). The new comparator charts were not opened in a browser.

## Files in `headline/`

T11's set (`inputs.csv`, `decisions.csv`, `gold_signal.csv`, `baskets.csv`, `trades.csv`, `sleeve_trades.csv`, `positions.csv`, `daily_nav.csv`, `stats.csv`, `draws.csv`, `draw_states.npz`, `real_states.npz`, `draw_curves_20.8.npz`, `count_table.json`, `sampler_selftest.json`, `regression.json`, `regression_d17.json`, `audit.json`, `r7_flagged_days.csv`, `r7_export.csv`, `parent_nav_2014-09-01_2019-01-02.csv` and `.md`) plus `regression_t11.json` and `verify_t13.json`. Columns: `tests/T11/logs/evidence_contract.md` and the deltas in `../logs/evidence_contract.md`.

## Reproduce

```bash
cd AA && bash tests/T13/run.sh            # check data, check freeze, engine, verifier, analysis, write-up, page, page check (about 10 minutes)
python tests/T13/rerun_draw.py --book SCMO_0003 --family F1 --id 11 --cost 20.8
```
