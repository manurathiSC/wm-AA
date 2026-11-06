# T03 methods (companion to `report.html`)

The pre-registration is `../T03.md` §1–§3 (frozen; `python check_prereg.py`). This file says how the evidence in `headline/` was produced and how to reproduce it.

## What is run

One rule: **IN** (100% of the parent's stocks) when the latest weekly SIGN of Nifty 100, Midcap 100 and Smallcap 100 are all BUY, else **OUT** (50% GOLDBEES, 50% LBES cash). Decisions at T0 and at the last session of every later ISO week; a changed state is traded on the next session at OHLC4. Four books (SCMO_0003, 0007, 0010, 0029), three costs (0, 20.8, 50 bps round trip), window 2019-01-02 (0007: 2019-01-04) → 2026-08-21.

## The trade rule (the only one)

At a trade session t, with fill prices (stocks (O+H+L+C)/4, GOLDBEES de-spiked (O+H+L+C)/4, cash at its level):

```
V       = Σ stock units × fill + GOLDBEES units × fill + cash units × level
targets = stock i: e·V·w_i ;  GOLDBEES: (1−e)/2·V ;  cash: (1−e)/2·V        (e = 1 IN, 0 OUT; w = basket in force)
traded  = Σ |target − held value|     cost = traded × cost_bps ÷ 2 ÷ 10,000     new units = target × (V−cost)/V ÷ price
```

The same rule does an entry, an exit, a parent rebalance while IN (on the basket's availableDate, first session on or after it) and the constant-mix rebalance. While OUT a parent rebalance trades nothing; the basket in force is tracked. NAV = Σ units × close (stocks, GOLDBEES) + cash units × level, 1.000 at T0's close. The initial position at T0 is free; there is no sale at the end.

## Inputs (data review of 2026-11-05)

D17 published NAVs (calendar and comparator), D18 stock OHLC with `price_corrections.csv` (Polyplex, F-AA-D14), D19 basket weights (skipped baskets dropped, rows renormalised), D03 Master SIGN, D09 GOLDBEES, D12 MCX range (de-spike only), D11 LBES cash (accrued at the trailing 90-session rate after 2026-08-09). `headline/inputs.csv` has every file's size and sha256.

## Nulls

- **N4.9 spell shuffle (decides):** the rule's 9 in-spells and 9 out-spells shuffled among themselves, interleaved from OUT; `numpy.random.default_rng([3, draw_id])`, draw_id 0–1999, the same draws for every book, cost, window and cash variant. 9! × 9! ≈ 1.3 × 10¹¹, so a seeded sample.
- **Circular shift (secondary):** the weekly series rolled by every k with 46 ≤ k ≤ n − 46.
- Every draw goes through the same engine with the real stocks, baskets and costs.
- Percentile = (worse + 0.5 × ties) ÷ draws × 100; p = (1 + at least as good) ÷ (draws + 1); ties within a relative 1e-12.

## Gates

V1 `analysis/verify_t03.py` (independent; its spec is `../logs/verifier_spec.md`) · V2 point in time (`audit.json`) · V3 the null holds its table (`audit.json`, `draws.csv`) · V4 always-in reproduces the Step 1 rebuild and the published NAV within G0 (`headline/g_engine.csv`) · V5 `check_regression.py`.

## Engine readings E1–E15

Listed in `headline/audit.json` under `readings`. The ones that change numbers: E1 calendar is D17's dates; E4 the initial IN position is the basket as drifted since its availableDate; E5 baskets take effect on the first session on or after availableDate; E7 the single trade rule above; E10 cash accrual; E12 V3 for the circular shift is "invested weeks identical", since a rotation can cut one spell at the wrap.

## Files in `headline/`

`inputs.csv`, `decisions.csv` (one row per weekly decision and book, with the three signs and the label dates used), `trades.csv`, `positions.csv`, `daily_nav.csv` (strategy at three costs, comparators, published NAV), `stats.csv`, `draws.csv` (every null draw, three windows/cash variants), `draw_curves_20.8.npz` (daily NAV, float32, every headline draw at 20.8 bps; curves at 0 and 50 bps are not stored, `rerun_draw.py` reproduces any draw), `draw_states_example.csv`, `g_engine.csv`, `audit.json`, `verify_t03.json`, `v5_regression.json`.

## Reproduce

```bash
cd AA && bash tests/T03/run.sh
python tests/T03/rerun_draw.py --book SCMO_0003 --type N4.9 --id 17 --cost 20.8
```

Deterministic: static inputs fingerprinted in `inputs.csv`; seeds fixed; a rerun of the engine is byte-identical.
