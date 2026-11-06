# Step 1 log — Pre-registration (2026-11-06)

- Forked structure from `tests/T04/T04.md`; wrote `tests/T05/T05.md` §1-§3 per PLAN.md "T05 Rule" (9 points).
- `check_prereg.py` forked from T04's (T04 -> T05). `--freeze` run once; sha256 `90dc7c4dff77ee2f8bad2147e3032075e46cd1275f3b34cf1a0c3ddb7f66ba72`. Re-check exits 0.
- TRACKER.md created; logs/ created.

## Deviations / decisions (all in T05.md before freeze)
1. PLAN.md §2 R1-R5 list conflicts with its Rule 9 ("same R1-R5"); T04's R1-R5 used (R1 100% GOLDBEES, R2 cost, R3 LIQUIDCASE, R4 live window, R5 best-of-sweep).
2. Added status rule: C1 pass is "selection" only if 0 bps percentile also >= 98 (F-AA-M03 lesson).
3. Formalised r(j) (latest flagged decision <= j) and P(j) (stored pass set, basket-independent). Stateless; replaces the plan's `nonlocal last_review_j` in build_events (equivalent given forced review at each SELL spell start).
4. Review flag computed for all decisions, effective only in SELL. n_reviews = flagged SELL decisions. Last decision (2026-11-04) flagged but untraded.
5. Live window (R4) is its own book/decision series; its first decision is a forced review if SELL.
6. Reportability gate unit changed from SELL decisions to review decisions (>= 20 with 1 <= k < n).
7. Seed salt 5: default_rng([5, i, draw_id]), i = 1..5.
