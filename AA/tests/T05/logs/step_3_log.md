# Step 3 log: independent verifier for T05 (gate V1)

**Built:** `AA/analysis/verify_t05.py`, forked from `verify_t04.py`. Imports only argparse, json, shutil, sys, tempfile, time, pathlib, numpy, pandas. Did not read `t05_engine.py`, `t04_engine.py` or any engine code. Read `evidence/smoke/*` for the schema only (after the coordinator's note). T04's `stats.csv` / `draws.csv` are read as data for the trade-count warning.
Spec of readings: `AA/tests/T05/logs/verifier_spec.md`.

## What changed from T04's verifier
- Evidence path `tests/T05/evidence/headline` (override with `--evidence`), null salt 5, JSON written to `verify_t05.json`; scratch directory is now a `tempfile` dir (T04 hard-coded another session's path); missing evidence file exits 1.
- `review_flags` (5a) and `latest_review` (5b) written from T05.md; every window carries its own flags (live window separate, step 12).
- Strategy target, `decision_k_n`, mean equity share and null target use the stored pass set P(j) = pass set at r(j); null draws use `u[r(j)]`.
- New checks: C-review, C-sel-nonreview, C-frozen, C-nreviews, C-trades-plausible (warning only); modified: C-sel, C-null-k, C-pit, C-dec (adds `basket`, `trade_session`), C-ind (completeness rule per review decisions). Comparisons are strict: an absent evidence column is a `missing`, a failure.
- C-null samples draw ids present in the evidence (a smoke run has 100 draws, not 2,000).
- Self-test adds three T05 corruptions (review flags, a review_j, audit review_mask_count) and requires detection in C-review, C-sel-nonreview and C-nreviews as well as T04's C-dec, C-nav0, C-sel.
- Evidence format: first drafted adapters for PLAN.md's long layouts, removed after the coordinator's note; the verifier reads T04's real layout plus `review`, `trade_session`, `basket` (decisions), `review_j`, `is_review`, `review_nontrivial` (selections), `n_reviews`, `n_reviews_traded` (stats), `review_mask_count`, `review_mask_count_live`, `n_reviews` (audit).

## Smoke test against `evidence/smoke` (engine's smoke run, 100 draws per variant)
Run time about 105 s including the self-test. Exit 0 (`exit_ok = True`), nothing failed or missing.

| Check | compared | failed |
|---|---|---|
| C-dec | 6,165 | 0 |
| C-review | 1,462 | 0 |
| C-ind | 57,177 | 0 |
| C-ind-brute | 2,100 | 0 |
| C-sel | 33,700 | 0 |
| C-sel-nonreview | 3,825 | 0 |
| C-frozen | 1,404 | 0 |
| C-pit | 86,992 | 0 |
| C-nav0 | 9,690 | 0 |
| C-cost | 19,425 | 0 |
| C-comp | 40,698 | 0 |
| C-trades | 15,828 | 0 |
| C-null | 1,800 | 0 |
| C-null-k | 90,700 | 0 |
| C-nreviews | 64 | 0 |
| C-always-in | 1,944 | 0 |
| X checks (stats trades/cost, mean equity share, null trades, published NAV) | 102 / 20 / 1,200 / 1,926 | 0 |
| C-trades-plausible | 15 | 0 warnings |

- Review flags: 101 of 411 decisions; 56 flagged SELL (55 excluding the untraded last decision); live window 66 flags, 38 flagged SELL. These equal the engine's `review` column, `n_reviews`, `n_reviews_traded` and `audit.json`.
- Power notes: at 981 of 1,275 non-review SELL (indicator, decision) pairs a fresh evaluation would have kept a different set than the frozen one, so C-sel-nonreview and C-frozen can tell the two apart; the wrong null (`u[j]`) differs from the engine's draw 0 for 5 of 5 indicators.
- Trade counts (mine = engine's) at 20.8 bps: I1 88, I2 79, I3 89, I4 78, I5 80 against T04's 208, 151, 206, 144, 110: all lower. Null mean trades (my reproduced draws): 89.7, 81.7, 89.0, 84.2, 88.5, against T04's 231, 210, 227, 217, 226: all lower, and now close to the strategy's.
- Always-in: gap +0.0462 pp/yr (engine's 0.0451), worst year 2022 +0.4255 pp. Inside G0.
- SuperTrend: 0 mismatches against the evidence rows under reading A (1,965 under B), as in T04.
- Self-test: the corrupted copy was detected (C-dec 10, C-review 34, C-sel 2, C-sel-nonreview 1, C-nav0 1,935, C-nreviews 1 failures). A direct run with `--evidence <corrupted copy> --no-selftest` exits 1.

## Not yet done
Only the smoke evidence has been verified (100 draws per variant). The headline run (2,000 draws) will be verified in Step 5 by `python analysis/verify_t05.py`; it writes `evidence/headline/verify_t05.json`.
