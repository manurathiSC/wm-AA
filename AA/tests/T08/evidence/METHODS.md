# T08 methods (companion to `report.html`)

The pre-registration is `../T08.md` §1–§3 (frozen; `python tests/T08/check_prereg.py`). This file says how the evidence in `headline/` was produced and how to reproduce it. The implementation plan is `../PLAN.md`; the evidence contract the engine, verifier and scripts were written to is `../logs/evidence_contract.md`.

## What is run

T06's rule with one change. **IN** (100% of the parent's stocks) when the latest weekly SIGN of Nifty 100, Midcap 100 and Smallcap 100 are all BUY. Otherwise **OUT**: a sleeve of GOLDBEES and cash whose split follows the latest weekly SIGN of MAUc1 (MCX gold futures): **80% GOLDBEES / 20% cash when BUY, 20% / 80% when SELL**. Decisions at T0 and at the last session of every later ISO week. A trade happens on the next session at OHLC4 only when the target changes: an exit, an entry, or a **sleeve rebalance** (OUT on both sides and the gold signal changed); between trades the sleeve drifts. Cost 10.4 bps a side on every value traded (0 and 50 bps also run). Window 2019-01-02 → 2026-10-30 (SCMO_0007 from 2019-01-04); the window end is the last row of the approved index signals.

## Inputs: only the APPROVED rows of `data/APPROVED_DATA.md` (as of 2026-11-12)

D17 extended published NAVs (calendar, comparator, read to 2026-10-30), D18 stock OHLC with `price_corrections.csv`, D19 basket weights, D05 basket history, D03 index Master SIGN (to 2026-10-30), **D24 `Master_MAUc1.xlsx` (the gold signal)**, D09 GOLDBEES, D12 MCX range (de-spike; ends 2026-09-28, raw OHLC4 after), D11 cash. `headline/inputs.csv` lists every file opened with its sha256 and approved row; the engine stops if a row is not APPROVED.

## Nulls (2,000 seeded draws per book, cost and null)

- **F1 (decides C1, C2):** the in-or-out series drawn as N4.10 (nine in-spells in [2, 46] summing to 201, ten out-spells in [2, 40] summing to 209; SCMO_0007: 208), the real MAUc1 signal read in the draw's OUT weeks. Seed `default_rng([6, id])`. **F2:** the same as an N4.9 shuffle, seed `[3, id]`.
- **F3 (decides C3, C4):** the real in-or-out series, the gold signal drawn as N4.10-g (nine BUY spells in [2, 68] summing to 265, nine SELL spells in [2, 28] summing to 145; SCMO_0007: 264), same exact sampler. Seed `[11, 6, id]`. **F4:** the gold spells shuffled (N4.9-g), seed `[11, 3, id]`.
- **F5 (robustness):** an F1 draw and an F3 draw of the same id together.
- Holds weeks invested / BUY weeks, spell counts and first states; sessions invested and sleeve trades per draw are reported, not held. Percentile = (worse + 0.5 × ties) ÷ draws × 100; p = (1 + at least as good) ÷ (draws + 1). Holm-adjusted p over C1–C4 is printed beside each. MDE = 2.8 × null SD.
- `headline/draw_states.npz` holds every draw's states (in-or-out and gold), `real_states.npz` the real series, `draw_curves_20.8.npz` the daily NAV of every F1 and F3 draw at 20.8 bps.

## Gates

V1 `analysis/verify_t08.py` (independent; written from `../logs/verifier_spec.md` and the contract without reading the engine; imports nothing from it) · V2 point in time (index and MAUc1 rows) · V3 the nulls hold their tables (in-or-out and gold) · V4 regression to T06 on the overlap (with the sleeve fixed at 50/50 the engine reproduces T06's strategy, hold-the-parent and 100%-sleeve NAVs; T06's first 20 N4.10 draws replayed; always-in against the published NAV within G0; extended D17 equals the old D17; the gold series equals D24's weekly file) · V5 the samplers are exact (chi-square, DP counts equal inclusion–exclusion, per-position mean lengths) · V6 the sleeve identity (post-trade weights, cost identity, value conservation, no trade with a constant gold signal).

## Robustness

R1 0 and 50 bps; R2 LIQUIDCASE cash; R3 live window 2021-11-01 → 2026-10-30; R4 pair agreement (F1 vs F2, F3 vs F4) and T06's stored percentiles as a historical reference; R5 F5; R6 paired contrast (every F1 and F2 draw also run with the sleeve fixed at 50/50); **R7 raw-fill sensitivity**, computed after the run by `tests/T08/r7_raw_fill.py` (the engine ships no such file): the rule re-run with the close in place of the raw OHLC4 on the 22 sessions after 2026-09-28, which reproduces `stats.csv` to 1e-12 before the change (`headline/r7_raw_fill.csv`).

## Page checks

`check_page.py` recomputes every number, date and hover array on the page from the evidence: **1,534 checks, 0 failures** (run 2026-11-12). `verify_t08.py`: **3,195,688 comparisons, 0 failures**, corrupted copy detected. The page was built by `report.py` from `headline/` only.

## Files in `headline/`

`inputs.csv`, `decisions.csv` (with the gold signal and sleeve weight), `gold_signal.csv`, `trades.csv`, `sleeve_trades.csv`, `positions.csv`, `daily_nav.csv` (strategy, the 50/50 rule, comparators), `stats.csv`, `draws.csv` (every draw of every family and cell), `draw_states.npz`, `real_states.npz`, `draw_curves_20.8.npz`, `g_engine.csv`, `count_table.json`, `sampler_selftest.json`, `regression_t06.json`, `audit.json`, `verify_t08.json`, `r7_raw_fill.csv`.

## Reproduce

```bash
cd AA && bash tests/T08/run.sh            # engine 425 s on this machine, then verifier, analysis, write-up, page, page check
python tests/T08/r7_raw_fill.py           # R7, then re-run analyse.py, fill_writeup.py, report.py, check_page.py
python tests/T08/rerun_draw.py --book SCMO_0003 --family F1 --id 17 --cost 20.8
python tests/T08/rerun_draw.py --book SCMO_0003 --family F3 --id 5 --cost 20.8
```

Deterministic: inputs fingerprinted in `inputs.csv` and checked against `data/APPROVED_DATA.md`; seeds fixed; a rerun of the engine is byte-identical.
