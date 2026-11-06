# Step log: independent verifier for T04 (gate V1)

**Built:** `analysis/verify_t04.py` (about 900 lines, plain numpy/pandas, own loaders; nothing imported from or read in `analysis/` or `data/` other than the raw CSV/parquet inputs; `verify_t03.py` read for CLI style only). Read only the spec, T04.md s.1-3 and the evidence CSV/JSON files.
Run time about 200 s (indicator tables 5 s, 1,200 null simulations about 105 s, comparisons plus the corrupted-copy test the rest).
Outputs: `tests/T04/evidence/headline/verify_t04.json` (default run, SuperTrend reading B) and `verify_t04_stA.json` (run with `--st-reading A`).

## Result

The default run (spec reading B of the SuperTrend branch) **exits 1**: the only disagreement with the engine is I5 (the SuperTrend). Everything else agrees. The same code with reading A (the textbook branch) **exits 0** with every check passing. I did not tweak the code to match: the reading is a switch (`--st-reading`), default is the literal spec reading. Manu decides which reading is right.

| Check | compared (reading B / A) | failed B | failed A |
|---|---|---|---|
| C-dec | 5,343 / 5,343 | 0 | 0 |
| C-ind (every evidence row: valid, close_used, 4 averages, st_sign, 5 pass flags, last_bar, weight; plus completeness) | 57,177 | 3,930 | 0 |
| C-ind-brute (300 random stock-date pairs, not basket-restricted, own table vs a straight-line recomputation from raw rows) | 2,100 | 0 | 0 |
| C-sel (both windows, n, k, kept set, regime, basket, nontrivial) | 23,590 | 1,292 | 0 |
| C-pit | 86,462 | 0 | 0 |
| C-nav0 (end NAV, CAGR, max DD, every daily NAV, 5 indicators) | 9,690 | 1,937 | 0 |
| C-cost (20.8 and 50 bps, R1 gold100, R3 liquidcase, live window; end NAV, CAGR, max DD, plus daily NAV of the 50_50 rows) | 19,425 | 3,883 | 0 |
| C-comp (hold_parent, full AA switch, constant mix; end NAV, CAGR, max DD, daily NAV) | 40,698 | 5,811 | 0 |
| C-trades (every indicator, every cost, plus hold_parent and full_aa_switch; date, idx, decision, regime, basket, kept set, counts, weight, V, traded, cost, NAV after) | 28,137 (+177 missing) / 29,193 | 1,317 | 0 |
| C-null (1,200 simulations: draws 0..19 plus 20 random ids, at each of the 6 variants, for each of 5 indicators; end NAV, CAGR, max DD) | 3,600 | 720 | 0 |
| C-null-k (kept count = k on every decision, BUY target = whole basket, for every reproduced draw and window) | 293,446 | 0 | 0 |
| C-always-in (G0) | 1,944 | 0 | 0 |
| C-corrupt | detected (both runs) | | |
| extras: X-stats-trades-costpaid (trades, cost_paid) | 102 | 13 | 0 |
| X-mean-equity-share | 20 | 4 | 0 |
| X-null-trades-costpaid | 2,400 | 439 | 0 |
| X-published-nav | 1,926 | 0 | 0 |

All reading-B failures are I5 rows (and the constant mix of I5 and null draws of I5, which inherit I5's k). I1 to I4: every check is clean under both readings, to relative 1e-9.

**Always-in (V4):** my CAGR gap against the published NAV is +0.0462 pp/yr (engine's `g_engine.csv`: 0.0451), worst calendar year 2022 at +0.4255 pp (engine 0.4255). Both inside G0 (0.25 / 0.5). The small difference in the overall gap (0.0462 vs 0.0451) is not explained; it may be the engine annualising differently or the published NAV's rebasing, and it is well inside G0.

## The one disagreement: SuperTrend branch (I5)

Spec item 8 says: "elif prevST == prevFLB: ST = FLB if close >= FLB else FUB (this last test compares with FUB in the desk code: `close < FUB`)". That is ambiguous. I read it as: in the "ST on the lower band" branch the desk code's condition for choosing FLB is `close < FUB` (reading B, default). The engine's 4,084 `st_sign` values are reproduced exactly (0 mismatches) by the textbook branch `ST = FLB if close >= FLB else FUB` (reading A), and 1,965 of them differ under reading B.

First differing row under B: `indicators.csv`, decision 2019-01-02, stock GMBREW.NS, `st_sign` mine 0.0 vs evidence 1.0 (the pass_I5 flag differs with it). First differing selection row: `selections.csv` full I5 j=0 (2019-01-02): k mine 3, evidence 4. First differing NAV: I5 end NAV at 0 cost, mine 3.8369 vs evidence 4.7528.

So either the spec parenthetical is a misdescription of the desk code (the engine follows the textbook), or the engine did not implement what the spec says. I cannot tell which from the spec alone; the text of T04.md s.3 step 5 says only "the final bands and the trend ratchet follow `analysis/supertrend.py`", which I was not allowed to read. This needs Manu's call. I note that the weekly-candle partial-candle logic, the weighted ATR, the 5-candle start and the band recursion agree with the engine under reading A, so the rest of the I5 chain is confirmed.

## Readings the spec / T04.md did not settle (the most literal one was taken; all of them agree with the engine's evidence except the SuperTrend one above)

1. EMA seed: EMA at the N-th bar equals the mean of the first N closes; the recursion starts at bar N+1. Matches the engine.
2. Stock valuation close: last close over all D18 dates (including the 8 non-calendar sessions after 2019-01-02) forward-filled onto the calendar, as spec convention 2 states, even though F-AA-D15 says those sessions are "never read". For SCMO_0003 this has no visible effect (all checks agree).
3. `valid` in `indicators.csv`: read as "a bar exists within 7 calendar days of the decision date". The evidence has no `valid=False` and no NaN rows; every basket stock with a fresh close has a row (0 missing), so stocks with fewer than N bars cannot occur among the basket stocks in the evidence rows.
4. n, k and kept of decision j: measured on the basket in force at its trade session (the decision session for the last decision, which has no trade session). The spec says "the basket in force" without naming the session. Agrees with the evidence.
5. Initial position of the constant mix (not in T04.md): drifted basket scaled by f (the mean equity share), the remainder (1-f)/2 each in GOLDBEES and cash; the mix trades at every event session (every decision's next session including T0's, and every basket change), with no "target unchanged" test. The step-13 text says "rebalanced", and the evidence trade counts (433) fit this. Agrees to 1e-9 for I1 to I4.
6. `nontrivial` in `selections.csv`: SELL regime and 1 <= k < n (it is False on BUY rows). Not in the spec; agrees.
7. Which weekly bars are included in the supertrend candles: only admissible bars (all D18 bars up to 2019-01-02, then calendar sessions only), the same set as the other indicators.
8. The `trade date after decision date` test (C-pit) is applied to every evidence trade; zero exceptions, so the "except basket-change sessions" clause was never needed.
9. Draw ids: 0..19 plus 20 random ids (seeded, different per indicator and variant) at each of the 6 variants in `draws.csv`: 1,200 simulations, 3,600 (end NAV, CAGR, max DD) comparisons.
10. The published SCMO_0042 daily NAV in `daily_nav.csv` is not checked (its source file `indices.csv` is not in the spec's raw input list).

## Self-test

On a copy in `...\scratchpad\corrupt_evidence` (5 decisions' state and regime flipped at rows 10, 50, 100, 150, 200; I1 cost-0 `daily_nav` scaled by 1.001; one `k` increased in `selections.csv`): detected under both readings (reading A: C-dec 10, C-nav0 1,935, C-sel 1 failures; reading B shows the same plus the I5 disagreement). The verifier exits non-zero on it, and on the real data only if rows were compared in every check and none failed ("compared nothing" is non-zero).
