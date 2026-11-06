# T03 Step 3 log: engine (2026-11-05)

## What was done

- Wrote `analysis/t03_engine.py` (standalone; reads raw files only; numpy). One `trade()` rule for every trade (module docstring): at fill prices, V = value of all holdings; targets e*V*w_i for stocks and (1-e)/2*V each for GOLDBEES and cash; traded = sum |target - held|; cost = traded * cost_bps/2/1e4; all targets scaled by (V-cost)/V. The same function does entry, exit, parent rebalance while IN, and the constant-mix rebalance.
- Wrote engine readings E1-E15 into `audit.json["readings"]` (calendar = D17 dates, drifted initial holdings, paired seeds, V3 reading for the circular shift, etc.).
- Smoke test (`--quick`) then the full run `python analysis/t03_engine.py --run headline` (79 s): 4 books x 3 costs x (strategy, hold-parent, constant mix, sleeve-only) + 2,000 N4.9 draws and 308 circular shifts per book and cost + R3 (LIQUIDCASE cash) + R4 (live window) nulls at 20.8 bps. A rerun is byte-identical (`cmp` on stats.csv and draws.csv).
- `tests/T03/rerun_draw.py` reproduces any draw (checked: SCMO_0003 N4.9 id 17 equals the stored row exactly). `tests/T03/check_regression.py` = V5.

## G-engine / V4 (always-in at 0 cost, to 2026-10-22)

| Parent | CAGR gap vs published (pp/yr) | G0 overall | Worst calendar year (gap pp) | G0 yearly | Max relative difference vs the Step 1 rebuild |
|---|---|---|---|---|---|
| SCMO_0003 | +0.045 | PASS | 2022 (+0.426) | PASS | 1.6e-13 |
| SCMO_0007 | +0.103 | PASS | 2019 (+0.391) | PASS | 2.7e-11 |
| SCMO_0010 | +0.101 | PASS | 2019 (+0.447) | PASS | 5.7e-15 |
| SCMO_0029 | +0.038 | PASS | 2019 (+0.189) | PASS | 3.2e-15 |

These are the same numbers as `data/parent_rebuild_hm/g0_gate.csv`: the engine's always-in path is the Step 1 rebuild (with the Polyplex correction).

## Other gates and audit counts

- V2: 3,194 checks (decisions + trades), 0 violations. Five weeks per book use the previous week's Master row, as pre-registered.
- V3: 40,000 N4.9 draws, 0 signature mismatches, 0 invested-week mismatches; 4,924 circular shifts, 0 invested-week mismatches, largest spell-count gap 1 (the wrap).
- 0 stock trades priced by a stand-in last close (no bar that session) in any run.
- Skipped baskets dropped: SCMO_0007 (2020-03-16, 2021-09-16) and SCMO_0029 (2020-03-16) as in D19.
- LBES accrual: 10 sessions after 2026-08-09 at 0.01833%/session.

## Deviations and readings worth knowing

- The initial IN position is the drifted basket (E4), not fresh weights; the always-in path then equals the rebuild. Every book's first state is OUT, so the strategy never uses it; only the hold-parent comparator and V4 do.
- 0010 and 0029 have the same worst fall (-15.22%): it happens in the sleeve, which is the same 50/50 GOLDBEES / cash in every book.
- The engine now also ships `draw_states_example.csv` (added before any results were read).
- Results printed by `analyse.py` before V1 and V5 had run were seen; nothing in the design changed because of them.

## Files

Created: `analysis/t03_engine.py`, `tests/T03/rerun_draw.py`, `tests/T03/check_regression.py`, `tests/T03/analyse.py`, `tests/T03/evidence/headline/*`, this log.
