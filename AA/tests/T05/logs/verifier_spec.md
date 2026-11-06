# Spec for `analysis/verify_t05.py` (independent verifier, gate V1)

Read-only inputs: the raw files (same list as T04's `verifier_spec.md`), `tests/T05/T05.md` §1-§3 (frozen; it wins over `PLAN.md`), this spec, and the engine's evidence in `tests/T05/evidence/<run>/`. The verifier never reads or imports `t05_engine.py`, `t04_engine.py` or any other `analysis/` module. T04's evidence (`tests/T04/evidence/headline/{stats,draws}.csv`) is read as data only, for a trade-count warning.

All of T04's conventions carry over (see `tests/T04/logs/verifier_spec.md`), with these T05 changes.

## Constants
- Null seed `default_rng([5, i, draw_id])`, i = 1..5, `u = rng.random((J, N))`, J = decisions of the window, N = columns of the weight matrix.
- SuperTrend: the ordered branch chain, reading A (the default; reading B stays as `--st-reading B` only to show the F-AA-M04 disagreement). The chain: prevST == prevFUB and close <= FUB gives FUB; prevST == prevFUB otherwise gives FLB; prevST == prevFLB and close >= FLB gives FLB; otherwise FUB.

## The review rule as the verifier reads it
1. **Flag (5a).** `review[j]` = (j is the last decision whose date falls in its own calendar month) OR (state[j] = SELL and (j = 0 or state[j-1] = BUY)). Computed for every decision in every regime, per window (the live window has its own flags, its T0 is a review if SELL).
2. **r(j) (5b)** = largest j' <= j with `review[j']`. Where none exists yet (a BUY decision before the first flag) the engine logs r = j; the verifier reads it the same way.
3. **Stored pass set** P(j) = stocks (of all ever held) passing the indicator at decision r(j), under T04's step-5 rules. Kept set at decision j = P(j) intersect basket b, b the basket in force at j's trade session (the decision session for the last decision, which has no trade session). n = |b|, k = |P(j) intersect b|.
4. **Target** at session t: BUY: whole basket at basket weights; SELL: basket weights of the kept set. The decision in force at t and the basket in force at t come from T04's event logic. A parent rebalance in SELL re-applies P(j) to the new basket. A trade happens iff the target differs from the last target (exact).
5. **Null.** At SELL decision j and basket b the draw keeps the `k = |P(j) intersect b|` stocks of b with the smallest `u[r(j)]` (stable sort). The row is the review's, never `u[j]`.

## Readings where the text is silent
| # | Question | Reading taken |
|---|---|---|
| R1 | `selections.csv` rows on BUY decisions: what are k, kept, review_j? | Same definition as SELL: P(r(j)) intersect b with review_j = r(j), or j itself before the first flag (confirmed on `evidence/smoke`; T05.md step 6 only defines SELL). They are checked strictly. No effect on any NAV |
| R2 | `n_reviews` and the untraded last decision (2026-11-04, flagged, SELL) | `n_reviews` = flagged SELL decisions including the last (56 full, 38 live on the smoke evidence); `n_reviews_traded` excludes it (55 / 37). Both columns are required and compared. T05.md 5a can be read either way; the engine provides both |
| R3 | `review_mask_count` | Flags over all regimes, last decision included, per window: `audit.json` `review_mask_count` (full) and `review_mask_count_live` |
| R4 | `is_review`, `review_nontrivial` in selections | `is_review = review[j]`; `review_nontrivial = review[j] and SELL and 1 <= k < n` |
| R5 | `decisions.basket` / `trade_session` | `basket` = availableDate (string) of the basket in force at the decision's trade session (decision session for the last decision); `trade_session` = `trade_date` |
| R6 | Which indicator rows must `indicators.csv` carry | Every (flagged SELL decision, basket stock with a fresh close); if the file holds any non-review decision it must hold all decisions. Every row present is compared on all columns |
| R7 | Evidence layout | T04's real layout plus the T05 columns. PLAN.md's evidence table (long layouts) is NOT read; an absent required column is a `missing` (a failure) |
| R8 | Null sample draws | Draws 0..19 plus 20 random draw ids per (indicator, variant) that exist in the evidence's `draws.csv` (a smoke run has fewer than 2,000); the variants are those present: full 50_50 lbes at 0 / 20.8 / 50, full liquidcase 20.8, full gold100 20.8, live 50_50 lbes 20.8 |

## Checks (counts of compared / failed / missing to stdout and `verify_t05.json`)
Carried over from T04: **C-dec** (every decisions.csv row incl. `basket` and `trade_session`), **C-ind** (every evidence row, all columns, plus completeness per R6), **C-ind-brute** (300 random stock-dates, not basket-restricted, vs a straight-line recomputation), **C-pit**, **C-nav0**, **C-cost**, **C-trades**, **C-null** (sample draws: end NAV, CAGR, max DD), **C-null-k**, **C-comp**, **C-always-in** (V4), **C-corrupt** (self-test), extras `X-stats-trades-costpaid`, `X-mean-equity-share`, `X-null-trades-costpaid`, `X-published-nav`.

New or modified for T05:
- **C-review.** (a) My review mask equals `decisions.csv` `review`, every decision. (b) Each `selections.csv` SELL row's `review_j` equals r(j) computed from the ENGINE's own `review` column (so the two files agree). (c) My own mask has the first decision of every SELL spell flagged.
- **C-sel.** Every selections row (full and live; SELL and BUY): decision_date, regime, basket_eff, n, k, kept, `review_j` = r(j), `is_review`, `review_nontrivial`, `nontrivial`.
- **C-sel-nonreview.** Rows at non-review SELL decisions only: `review_j` = r(j) < j, kept = P(r(j)) intersect b computed from the review date's own indicator table (not from the decision's), k equals |P(r(j)) intersect b|.
- **C-frozen.** (i) From the evidence: for two consecutive SELL decisions of the same review segment, the kept sets agree on every stock in both baskets (the indicator-only pass set is unchanged; only the basket intersection may differ). (ii) From the trades: a trade under a non-review SELL decision happens only on a session where a new basket takes effect. A power note counts the non-review pairs where a fresh evaluation at j would have differed.
- **C-null-k.** For every reproduced draw and every decision of the window: SELL kept count = |P(r(j)) intersect b| (the review's k for the basket in force), kept stocks at basket weights, BUY target = the whole basket; and two SELL decisions with the same review and basket give an identical null target. A power note shows that the wrong null (`u[j]`) differs from the evidence for draw 0 at every indicator.
- **C-nreviews.** `n_reviews`, `n_reviews_traded` on every strategy stats row, `review_mask_count` and `review_mask_count_live` in `audit.json`, and the audit's `n_reviews` dict.
- **C-pit (added).** `review_j <= j` and the review's decision date is not after j's, on every SELL selections row.
- **C-trades-plausible (warning only, never decides exit).** My reproduced strategy trade count per indicator and cost against T04's stats trade count, and my reproduced null mean trades against T04's draws mean (20.8 bps): a note `WARNING:` for any T05 count not lower.

## Exit rule
Exit 0 only if every required check compared at least one row, none failed, none is missing, and the self-test on a corrupted copy (5 decision states flipped, 3 review flags flipped, I1 cost-0 NAV x 1.001, one `k` + 1, one non-review `review_j` - 1, `review_mask_count` + 1) was detected by C-dec, C-nav0, C-sel, C-sel-nonreview, C-review and C-nreviews. A missing evidence file is exit 1. If the verifier disagrees with the engine, neither is adjusted: the first differing row and the reading are reported.
