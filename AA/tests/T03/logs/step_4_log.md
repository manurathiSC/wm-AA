# T03 Step 4 log: independent verifier (2026-11-05)

`analysis/verify_t03.py` was written by a separate agent that was told not to read the engine, from `logs/verifier_spec.md` and the raw files. The agent hit an API spend limit before it finished (it left a half-edited string, a syntax error at line 879). The main session repaired that one line and ran the file; it made no other change to the verifier's logic.

## Result (after the engine fix below)

`python analysis/verify_t03.py` exits 0: **119,999 gate comparisons, 0 failures, 0 missing**; worst relative NAV difference 1.2e-15; all 32,000 sampled N4.9 draws reproduced (invested weeks, spell counts, sorted spell lengths: 0 differences); the always-in book gives the same G0 gaps (+0.046, +0.105, +0.103, +0.040 pp/yr). On a corrupted copy (5 decisions flipped, a NAV column x 1.001) it fails on 7,543 comparisons and exits non-zero: detected.

| Check | Compared | Failed | Worst relative difference |
|---|---|---|---|
| decisions (signs, labels, state, dates) | 1,599 | 0 | 0 |
| point in time | 12,988 | 0 | 0 |
| 0-cost strategy NAV, every day | 7,542 | 0 | 7.8e-16 |
| closed form (product of segment factors) | 24 | 0 | 2.7e-15 |
| costed strategy (20.8, 50 bps) | 15,084 | 0 | 7.4e-16 |
| hold-parent and sleeve-only comparators | 45,252 | 0 | 1.2e-15 |
| constant mix (literal spec reading) | 22,626 | 0 | 1.6e-15 |
| trades (dates, kinds, count) | 405 | 0 | 2.4e-16 |
| null draws (200 NAV reproductions, all 32,000 signatures) | 32,200 | 0 | 4.6e-14 |
| audit counts | 60 | 0 | 0 |

## The disagreement it found (and its resolution)

The first verifier run (before the engine fix) disagreed on the **constant-mix comparator**: 22,614 of 22,626 rows. The verifier read section 3 step 10 literally (rebalance at every decision date's next session, T0 included); the engine started with the drifted basket scaled by f and did not rebalance after T0's decision. The verifier's variant without that first rebalance matched the engine to 1e-15, so the difference was exactly that one trade. The frozen text says every decision date, so the **engine was wrong**; fixed in `simulate()` (the constant mix now trades after j = 0) and rerun. Strategy, hold-parent, sleeve-only and all draws are byte-identical before and after (checked: `draws.csv` identical, `stats.csv` differs only in the constant-mix rows, by at most 0.004 in end NAV). The comparator is descriptive: no criterion depends on it.

A second apparent disagreement, `accrued_sessions` 51 against the engine's 10, was the verifier counting sessions of its extended always-in calendar; it had already corrected this itself before it stopped. 10 is right for the 2026-08-21 window.

## Files

Created: `analysis/verify_t03.py`, `tests/T03/evidence/headline/verify_t03.json`, this log (written by the main session; the agent had not written one).
