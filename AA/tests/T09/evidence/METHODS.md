# T09 methods (companion to `report.html`)

The pre-registration is `../T09.md` §1–§3 (frozen; `python tests/T09/check_prereg.py`; corrections found before the run are in the amendments block of `../T09.md`, outside the frozen text). This file says how the evidence in `headline/` was produced and how to reproduce it. The implementation plan is `../PLAN.md` (window start changed in `../PLAN_v2.md`); the evidence contract the engine, verifier and scripts were written to is `../logs/evidence_contract.md`.

## What is run

T06's and T08's rule on a **three-index proxy portfolio** in place of each parent's stocks, in the years before the parents' holdings exist. **IN** (the proxy: Nifty 100, Midcap 100 and Smallcap 100 at the book's own fixed average band mix, for example SCMO_0003 9.6 / 19.7 / 70.7) when the latest weekly SIGN of the three indices are all BUY. Otherwise **OUT**: a sleeve of GOLDBEES and cash. **Part A (T06's rule):** the sleeve is fixed 50/50. **Part B (T08's rule):** the sleeve is 80% GOLDBEES / 20% cash when the latest weekly MAUc1 SIGN is BUY and 20% / 80% when SELL. Decisions at T0 and at the last session of every later ISO week. A trade happens on the next session at OHLC4 when the target changes (an exit, an entry, a sleeve rebalance), and **the proxy is reset to its fixed mix on the first session of each quarter while IN** (a fourth trade kind). Cost 10.4 bps a side on every value traded (0 and 50 bps also run). Window 2011-11-25 → 2019-01-02 (T0 is the first date on which the clean Smallcap 100 signal and D03 agree on every column).

## Inputs: only the APPROVED rows of `data/APPROVED_DATA.md` (as of 2026-11-12)

D25 daily index prices and D26 the NSE calendar (copies of production's files, to 2019-01-04; Smallcap 100 prices read from 2011-10-03 only), D03 index Master SIGN (Smallcap 100 from 2011-11-25 only), **D24b the MAUc1 signal from 2003-12-19**, D09b the GOLDBEES proxy built from MAUc1's returns (before 2014-07-01) chained to D09 GOLDBEES (from 2014-07-01), D24b's daily range for the de-spike, D11 cash. `headline/inputs.csv` lists every file opened with its sha256, approved row and usable-from date; the engine stops if a row is not APPROVED or a restricted file is read before its date.

## Nulls (2,000 seeded draws per book, cost and null)

- **F1 (decides A1, A2 with the 50/50 sleeve, and C1, C2 with the timed sleeve):** the in-or-out series drawn as N4.10 (12 in-spells in [1, 32] summing to 172, 13 out-spells in [2, 35] summing to 200). Seed `default_rng([12, 6, id])`. **F2:** the same as an N4.9 shuffle, seed `[12, 3, id]`.
- **F3 (decides C3, C4):** the real in-or-out series, the gold signal drawn as N4.10-g (15 BUY spells in [2, 36] summing to 190, 14 SELL spells in [2, 27] summing to 182). Seed `[12, 11, 6, id]`. **F4:** N4.9-g, seed `[12, 11, 3, id]`.
- **F5 (robustness):** an F1 draw and an F3 draw of the same id together.
- Bounds are the series' own (`lo = min(2, shortest)`, `hi = longest`), computed before any return was read. Weeks invested, BUY weeks, spell counts and first states are held; sessions invested and sleeve trades per draw are reported, not held. Percentile = (worse + 0.5 × ties) ÷ draws × 100; p = (1 + at least as good) ÷ (draws + 1). Holm over m = 6 per book and cost is printed beside each. MDE = 2.8 × null SD.

## Gates

V1 `analysis/verify_t09.py` (independent; written from `../logs/verifier_spec.md` and the contract without reading the engine) · V2 point in time and the Smallcap 100 restriction · V3 the nulls hold their tables · V4 identities (one-index books equal the index, hold-the-proxy equals a plain-loop build, the shared functions equal T08's, signals equal the Master files, the D09b → D09 splice is continuous) · V5 the samplers are exact · V6 the sleeve and reset identities.

## Robustness

R1 0 and 50 bps; R2 LIQUIDCASE cash (equals LBES to 1.6e-10 here, so vacuous); R3 the window from 2012-01-02; R4 pair agreement; R5 both timings random; R6 paired contrast (every F1 and F2 draw also run with the sleeve fixed at 50/50); R7 gold-proxy sensitivity (close in place of OHLC4 before 2014-07-01; gold weight held at 50% before 2014-07-01). R8 (validating the proxy against the real parents) was declined and not run.

## Page checks

`check_page.py` recomputes every number, date and hover array on the page from the evidence and the raw approved files: **2,052 checks, 0 failures** (run 2026-11-12). `verify_t09.py`: **3,895,609 gate comparisons, 0 failures**, corrupted copy detected. The page was built by `report.py` from `headline/` only.

## Files in `headline/`

`inputs.csv`, `decisions.csv`, `gold_signal.csv`, `trades.csv`, `sleeve_trades.csv`, `quarterly_resets.csv`, `proxy_units.csv`, `positions.csv`, `daily_nav.csv`, `stats.csv`, `draws.csv`, `draw_states.npz`, `real_states.npz`, `draw_curves_20.8.npz`, `count_table.json`, `sampler_selftest.json`, `regression.json`, `audit.json` (with the engine's readings E1–E21), `verify_t09.json`. The R7 runs appear in `stats.csv` only.

## Reproduce

```bash
cd AA && bash tests/T09/run.sh            # check data, check freeze, engine, verifier, analysis, write-up, page, page check
python tests/T09/rerun_draw.py --book SCMO_0003 --family F1 --id 17 --cost 20.8
python tests/T09/rerun_draw.py --book SCMO_0003 --family F3 --id 5 --cost 20.8
```

Deterministic: inputs fingerprinted in `inputs.csv` and checked against `data/APPROVED_DATA.md`; seeds fixed; a rerun of the engine is byte-identical.
