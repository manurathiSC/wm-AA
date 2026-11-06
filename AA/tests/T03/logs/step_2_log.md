# T03 Step 2 log: pre-registration (2026-11-05)

## What was done

- Wrote `tests/T03/T03.md` (header, §1–§3; §4–§8 are placeholders) from `wm-research/TEST_TEMPLATE.md`, following T01.md's structure and the plan.
- Counted the weekly decision series **before** writing §2, from the three Master SIGN files and D17's calendar only (no return was computed): 400 decisions per book (T0 plus 399 Friday reviews), 9 in-spells and 9 out-spells (17 switches), 49.7% invested, **identical in all four books**, first state OUT. In-spells (weeks) 8, 13, 33, 23, 20, 26, 46, 11, 19; out-spells 11 (0007: 10), 29, 15, 16, 40, 18, 5, 30, 37. 9! × 9! = 131,681,894,400 > 50,000, so 2,000 seeded draws (`default_rng([3, draw_id])`).
- Wrote `tests/T03/check_prereg.py` and froze: the sha256 of §1–§3 is in the header; rerun `python check_prereg.py` to verify (exits non-zero on any change).

## Decisions made in the pre-registration (all mine; the plan left them open)

| Choice | What | Why |
|---|---|---|
| Pass mark | percentile ≥ 90 in ≥ 3 of 4 books, after cost at 20.8 bps; C1 on CAGR, C2 on max drawdown | T01's precedent |
| Secondary null range | circular shift 46 ≤ k ≤ n − 46 | AGENT.md N4.9 says "beyond the longest spell" (46 weeks); the plan said 8 ≤ k ≤ n − 8. **Deviation from the plan** |
| Initial position | NAV 1.000 at T0's close, holding the state decided at T0, no cost, no end-of-window sale | the published NAV and the rebuild start the same way, and V4 needs it |
| Decision calendar | last D17 session of each ISO week; Master row = latest dated ≤ d; five weeks use the previous week's row (Muhurat or special session after D17's last) | no look-ahead; consistent with F-AA-D15 |
| Robustness | R1 shift null ≥ 75; R2 0 and 50 bps; R3 LIQUIDCASE cash from 2024-01-24; R4 live sub-window 2021-11 → 2026-08 | covers the D11 and backfill contaminants |
| MDE | 2.8 × null_sd, after the run, disclosed as not existing at writing | the plan's "pilot" needs the engine, which must come after the freeze |
| Gates | V1–V4 from the plan, plus V5 regression (parent_rebuild_hm reruns to the same g0_gate.csv); N6.7 controls listed as not run | template requires saying so |

## Things the plan got wrong or left open

- The plan's note that the OHLC and NAV files skip the same sessions is false (Step 0, F-AA-D15); §3 states D17's dates are the calendar.
- 0007 needs no G0 contaminant (F-AA-D14 handled); the Redington residual (+0.17 pp in 2021) is listed as not corrected.
- The four books have the same decision series, so the N4.9 draws are paired across books (same seeds) and "3 of 4" is weaker than it sounds; stated in §2.

## Files

Created: `tests/T03/T03.md`, `tests/T03/check_prereg.py`, this log. Modified: `tests/T03/TRACKER.md`.
