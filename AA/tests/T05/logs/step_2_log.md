# T05 Step 2 log: engine (2026-11-06)

File: `AA/analysis/t05_engine.py`, forked from `t04_engine.py` (924 lines). T05.md was not edited (`python tests/T05/check_prereg.py` exits 0, sha256 `90dc7c4d...`). No T04 file, verify_t05.py, TRACKER.md, analyse/fill_writeup/report/run.sh was touched.

## What changed from T04
- Paths: `T05 = AA/tests/T05`; evidence to `tests/T05/evidence/<run>/`; prereg hash read from T05.md; title/docstring now T05. `T04` constant kept only to read T04's headline `decisions.csv` for a printed cross-check.
- `_review_mask(dec_dates, state)` (T05.md 5a): last decision of each (year, month) by the decision's own date, OR first SELL decision of a SELL spell (j=0 if SELL). Computed for every decision; effective only in SELL. `_review_prev(mask)` = `np.maximum.accumulate(np.where(mask, arange, -1))`, i.e. r(j), stateless (no `nonlocal last_review_j`).
- `Book.decisions()` adds `review`, plus `trade_session` (= trade_date) and `basket` (effective date of the basket in force at the trade session) so both T04's real column names and PLAN.md's names are present.
- `strategy_provider(ind, i, dec_dates, bk, rev, none)`: caches the all-stock pass set per review decision r (independent of any basket), and returns `intersect1d(P(r), bk.bn[b])` (cached per (r, b)). Exposes `.rev`, `.rj`.
- `null_provider(bk, u, kc, rev)`: draws from `u[r(j)]`, never `u[j]`; k = `kc(j, b)` = `|P(j) & b|`; derives its own r(j) from the flags it is given.
- `build_events`: signature kept except an optional `log` list; the freezing lives in the providers (they read the stored pass set at r(j)), so between reviews the target changes only when the basket does. The log records every session the target is evaluated at (used by V3).
- Seed `default_rng([5, i + 1, draw_id])` for i = 0..4 in code (= salt 5, i = 1..5 in the spec; same mapping as T04). V5's sampler seed `[5, 0, 5]`.
- V3 now checks, per draw and per window: at EVERY evaluated SELL session null kept count == strategy's `|P(j) & b|`; at every BUY session null target == whole basket at its weights; null review flags (rebuilt per draw from dates and states) and r(j) equal the strategy's; every SELL decision's r(j) is a flagged decision inside its own SELL spell.
- Evidence: `decisions.csv` + `review` (+ `trade_session`, `basket`); `selections.csv` (T04's long format) + `review_j`, `is_review`, `review_nontrivial`; `stats.csv` strategy rows + `n_reviews` (flagged SELL decisions, last decision included as 5a defines) and `n_reviews_traded` (last decision excluded); `audit.json` + `review_mask_count`, `review_mask_count_live`, `n_reviews`, `reviews` (per window: flags, month-end/forced counts, SELL spells, review dates), per-indicator `reportability` on reviews with 1 <= k < n, `t04_regime_crosscheck`, `v3` extended counters.
- READINGS: E5, E6 rewritten; E12-E16 added.

## Smoke test (`python analysis/t05_engine.py --run smoke --draws 2 --quick --workers 4`; `--quick` forces 20 draws, as in T04)
Exit 0, 15 s. Evidence in `AA/tests/T05/evidence/smoke/` (all ten files).
- G-engine (V4): +0.045 pp/yr overall (PASS), worst year 2022 +0.43 pp (PASS); same as T04 (the always-in path is unchanged).
- Decision series equals T04's on all 411 dates (0 mismatches); T03 cross-check unchanged.
- Review flags: full window 411 decisions, 101 flagged (month-end + forced), 56 flagged in SELL (55 traded; the 2026-11-04 decision is flagged SELL and untraded), 210 SELL decisions, 10 SELL spells. Live window: 66 flagged, 38 flagged in SELL (37 traded), 139 SELL decisions, 6 spells.
- Reviews with 1 <= k < n (full): I1 48, I2 45, I3 48, I4 48, I5 52; (live): 33, 32, 34, 33, 35. All reportable (>= 20).
- Strategy trades (20.8 bps, full): I1 88, I2 79, I3 89, I4 78, I5 80 (T04: 208, 151, 206, 144, 110). Mean null trades over 20 smoke draws: 89.7, 81.7, 89.0, 84.3, 88.5.
- V3 pass (36,400 SELL sessions and 34,600 BUY sessions checked over 100 draws x windows; 0 mismatches; 200 flag series equal; 34,900 r(j) checks, 0 bad). V5 50 checked, 0 failed.
- Own correctness tests: (a) at 770 non-review SELL rows of the full window, whenever the basket equals the review's basket, the kept set equals the review's kept set (0 mismatches); (b) 1,850 (decision, basket) pairs including parent rebalances inside the spell: provider output equals `passes[review row] & basket` recomputed directly (0 bad).

## Open points / ambiguities (not silently resolved)
1. PLAN.md evidence table names `decisions.csv` columns `trade_session, basket` and `selections.csv` columns `stock_col, selected`, but T04's real files use `trade_date` and one row per (window, indicator, decision) with a `kept` string. Kept T04's real format (T05.md says "as in PLAN.md" and PLAN says "same as T04"); added `trade_session` and `basket` to decisions.csv as aliases. selections.csv has no per-stock rows.
2. `n_reviews` includes the untraded last decision (5a's definition); `n_reviews_traded` excludes it. The reportability count uses the 5a definition (last included), with a traded-only count beside it; no indicator is near 20, so the choice does not matter.
3. PLAN.md Step 2(c) puts the freezing in `build_events` with `review_mask` and a `nonlocal` variable; implemented stateless in the providers via r(j) (as the lead's brief asked), `build_events` gains only an optional `log`.
4. For BUY decisions selections.csv still carries a row (as T04), with `review_j = r(j)`; for j=0 in BUY (no earlier flag) review_j is written as j. BUY targets never use it.
5. `--draws 2 --quick` runs 20 draws (T04's `--quick` overrides `--draws`).
