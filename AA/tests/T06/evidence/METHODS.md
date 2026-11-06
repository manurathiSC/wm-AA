# T06 methods (companion to `report.html`)

The pre-registration is `../T06.md` §1–§3 (frozen; `python tests/T06/check_prereg.py`). This file says how the evidence in `headline/` was produced and how to reproduce it. The implementation plan is `../PLAN_v2.md`.

## What is run

T03's rule, unchanged: **IN** (100% of the parent's stocks) when the latest weekly SIGN of Nifty 100, Midcap 100 and Smallcap 100 are all BUY, else **OUT** (50% GOLDBEES, 50% cash). Decisions at T0 and at the last session of every later ISO week; a changed state is traded on the next session at OHLC4. Four books (SCMO_0003, 0007, 0010, 0029), three costs (0, 20.8, 50 bps round trip), window 2019-01-02 (0007: 2019-01-04) → **2026-10-22**, 409 weekly decisions (0007: 408): 9 in-spells and 10 out-spells, 9 round trips. The trade rule, NAV and statistics are those of `tests/T03/evidence/METHODS.md`.

## Inputs: only the APPROVED rows of `data/APPROVED_DATA.md` (as of 2026-11-06)

D17 published NAVs (calendar, window end, comparator), D18 stock OHLC with `price_corrections.csv`, D19 basket weights with their `_holding_weight_sources.csv` and `_columns.csv`, D05 basket history (skipped flags), D03 Master SIGN (extended to 2026-10-30), D09 GOLDBEES (extended to 2026-11-04), D12 MCX range (de-spike only; later fills use the raw OHLC4), D11 cash (the extended LBES level to 2026-11-05; R2 uses `liquidEtfFinal_extended`). The engine opens every file through `analysis/approved_data.py` (it raises for a file that is not an APPROVED row) and `headline/inputs.csv` records each file's through-date, size and sha256. `python data/check_approved_data.py` runs first in `run.sh`.

## Nulls (2,000 seeded draws per book, cost and null)

- **N4.10, free-length random timing (decides):** nine in-spell lengths in [2, 46] summing to 201 and ten out-spell lengths in [2, 40] summing to 208 (SCMO_0007: 207), uniform over all ordered tuples, drawn by an exact count-and-sample method (`rng.random()` and a cumulative-sum search), alternated starting OUT. `numpy.random.default_rng([6, draw_id])`.
- **N4.9 spell shuffle (re-run beside it):** the rule's own spells reordered; `numpy.random.default_rng([3, draw_id])`.
- Holds weeks invested, spell counts and the first state; sessions invested are reported per draw (`draws.csv`), not held. Every draw goes through the same engine with the real stocks, baskets and costs. `headline/draw_states.npz` holds the state of every draw in every week.
- Percentile = (worse + 0.5 × ties) ÷ draws × 100; p = (1 + at least as good) ÷ (draws + 1); ties within a relative 1e-12.

## Gates

V1 `analysis/verify_t06.py` (independent; written from `../logs/verifier_spec.md` without reading the engine) · V2 point in time (`audit.json`) · V3 the nulls hold their tables · V4 regression to T03 on the overlap (decisions on every shared date; NAVs to 2026-08-07) and always-in against the published NAV within G0 (`headline/g_engine.csv`, `regression_t03.json`) · V5 the sampler is exact (`sampler_selftest.json`, `count_table.json`).

## Engine readings

Listed in `headline/audit.json` under `readings` (E1–E16, T06-1 to T06-9). Corrections to two statements in the frozen §3 are in `../T06.md` under "Added after the run".

## Page checks

`check_page.py` recomputes every number, date and hover array on the page from the evidence: **766 checks, 0 failures** (run 2026-11-06, `run.sh` exit 0). `verify_t06.py`: **973,395 comparisons, 0 failures**, corrupted copy detected.

## Files in `headline/`

`inputs.csv`, `decisions.csv`, `trades.csv`, `positions.csv`, `daily_nav.csv` (strategy at three costs, comparators, published NAV), `stats.csv`, `draws.csv` (every draw of both nulls: full window × LBES × 3 costs, full × LIQUIDCASE, live window), `draw_states.npz`, `draw_curves_20.8.npz` (daily NAV, float32), `g_engine.csv`, `count_table.json`, `sampler_selftest.json`, `regression_t03.json`, `audit.json`, `verify_t06.json`.

## Reproduce

```bash
cd AA && bash tests/T06/run.sh
python tests/T06/rerun_draw.py --book SCMO_0003 --type N4.10 --id 17 --cost 20.8
```

Deterministic: inputs fingerprinted in `inputs.csv` and checked against `data/APPROVED_DATA.md`; seeds fixed; a rerun of the engine is byte-identical. Engine time 147 s.
