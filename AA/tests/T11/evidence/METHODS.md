# T11 methods (companion to `report.html`)

The pre-registration is `../T11.md` §1–§3 (frozen, sha256 `0ab77589acbd…`; `python tests/T11/check_prereg.py`). This file says how the evidence in `headline/` was made. Nothing here changes §1–§3.

## What is run

T06's rule (Part A, sleeve fixed 50/50) and T08's rule (Part B, sleeve 80/20 or 20/80 by the weekly MAUc1 supertrend) on the **four real parents' own stocks**, SCMO_0003, 0007, 0010 and 0029, from 2014-09-01 (the first basket effective on or after 2014-07-01, the first day with stock prices) to 2019-01-02 (the first date of the published NAVs). Each week the latest weekly SIGN of the Nifty 100, Midcap 100 and Smallcap 100 is read; if all three are BUY the book holds the parent's basket in force at its listed weights (renormalised to 1), otherwise a GOLDBEES and cash sleeve. Trades are on the next session at OHLC4 with 10.4 bps a side (20.8 round trip primary; 0 and 50 as robustness). The first position (the basket effective 2014-09-01) is free; the 18 later basket changes are traded at the first session on or after each availableDate while the book holds the parent.

## Inputs: only the APPROVED rows of `data/APPROVED_DATA.md` (as of 2026-11-12)

D18 stock OHLC (with the Polyplex correction), D19 basket weights, D05 basket dates, D26 the NSE calendar, D03 index Master SIGN, D24b the MAUc1 signal from 2003 and its daily MCX range for the GOLDBEES de-spike, D09 GOLDBEES, D11 cash (LBES; R2 LIQUIDCASE), D17 published NAVs for the 2019 seam check only. Every file read is listed with its sha256 in `headline/inputs.csv`. No file outside the approved table is read by the engine; the independent verifier opens D24 once, for gate V4(e) only.

## Nulls (2,000 seeded draws per book, cost and null; the four books share draws)

- **F1 (decides A1, A2 with the 50/50 sleeve, and C1, C2 with the timed sleeve):** the in-or-out series drawn as N4.10 (8 in-spells in [1, 28] summing to 93, 8 out-spells in [2, 34] summing to 135, starting IN). Seed `default_rng([14, 6, id])`. **F2:** N4.9 (the real spells shuffled), seed `[14, 3, id]`.
- **F3 (decides C3, C4):** the real in-or-out series, the gold signal drawn as N4.10-g (10 BUY spells in [2, 36] summing to 132, 9 SELL spells in [2, 19] summing to 96, starting BUY). Seed `[14, 11, 6, id]`. **F4:** N4.9-g, seed `[14, 11, 3, id]`.
- **F5 (robustness):** an F1 draw and an F3 draw of the same id together.
- Bounds are the series' own (`lo = min(2, shortest)`, `hi = longest`), computed before any return was read. Weeks invested, BUY weeks, spell counts and first states are held; sessions invested and sleeve trades per draw are reported, not held.

## Gates

V1 `analysis/verify_t11.py` (independent; written from `../logs/verifier_spec.md` and the contract without reading the engine): 3,729,546 comparisons, 0 failures, corrupted copies detected · V2 point in time and the Smallcap 100 restriction · V3 the nulls hold their tables · V4 identities and regressions (with D17's dates and T0 = 2019-01-02 the engine reproduces T08's and T06's stored daily NAVs to 2.2e-16; one-instrument identity 6.7e-16; shared functions identical to `t08_engine.py`; the 2019 seam against the published NAV within ±0.5 pp for all four parents) · V5 the samplers are exact · V6 sleeve, basket and cost identities. All pass (`../analysis.log`, `4.0b`).

## Robustness

R1 0 and 50 bps; R2 LIQUIDCASE cash (equals LBES to 1.3e-10 in daily return here, so it cannot change a number); R3 the window from 2015-01-02; R4 pair agreement; R5 both timings random; R6 paired contrast (every F1 and F2 draw also run with the sleeve fixed at 50/50); R7 price-quality sensitivity: the one held stock-day with a one-day move of 20% or more in D18 (PURVA, SCMO_0010, 2017-10-23) and the nine manual-export stocks' contribution.

## The rebuilt parent NAV

`headline/parent_nav_2014-09-01_2019-01-02.csv` holds, per parent and session, the hold-the-parent NAV at 0 and 20.8 bps and the Part A and Part B strategy NAV at 20.8 bps, base 1.000 on 2014-09-01. Its caption, `headline/parent_nav_2014-09-01_2019-01-02.md`, says: rebuilt from the parent's baskets and Eikon prices, not validated against a published NAV before 2019-01-02. It is not approved data and no other test may read it.

## Page checks

`check_page.py` recomputes every number, date and hover array on the page from the evidence: **2,270 checks, 0 failures** (run 2026-11-17). The page was also tried in Chromium (light, dark, phone width) with no console errors.

## Files in `headline/`

`inputs.csv`, `decisions.csv`, `gold_signal.csv`, `baskets.csv`, `trades.csv`, `sleeve_trades.csv`, `positions.csv`, `daily_nav.csv`, `stats.csv`, `draws.csv`, `draw_states.npz`, `real_states.npz`, `draw_curves_20.8.npz`, `count_table.json`, `sampler_selftest.json`, `regression.json`, `regression_d17.json`, `audit.json`, `verify_t11.json`, `r7_flagged_days.csv`, `r7_export.csv`, `parent_nav_2014-09-01_2019-01-02.csv` and `.md`. Their columns are in `../logs/evidence_contract.md`.

## Reproduce

```bash
cd AA && bash tests/T11/run.sh            # check data, check freeze, engine, verifier, analysis, write-up, page, page check
python tests/T11/rerun_draw.py --book SCMO_0003 --family F1 --id 17 --cost 20.8
```
