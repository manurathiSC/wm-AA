# T15 Plan: the three-index switch holding the liquid ETF **plus the indices that are still BUY**, in equal parts, when the switch is OUT **and** gold is SELL, on both base sleeves (50/50 and 80/20), on T11's window 2014-09-01 -> 2019-01-02 and T08's window 2019-01-02 -> 2026-10-30

**Written 2026-11-25 by Claude, on Manu's request in chat.** Nothing in this plan has been run and no engine, verifier or analysis code exists. The only numbers below that were computed are week counts read from T14's stored decision logs (`tests/T14/evidence/headline/{w1,w2}/decisions.csv`: the three index SIGNs, the gold SIGN and the regime per week; no price, NAV or return), the data checks of D25c (`data/extend_index_prices.py`, prices only, no strategy return), and `python data/check_approved_data.py` (exit 0: 70 approved rows, 0 problems, 2026-11-25). **Status: DRAFT, awaiting Manu's approval.** On approval the frozen design becomes `T15.md` §1-§3 (Step 1), which wins over this plan where they differ. This file is kept as written once approved; a revision goes beside it as `PLAN_v2.md` (never overwrite this file). `PLAN.md` is the implementation plan; read it together with `AGENT.md` (the framework), `AA/CLAUDE.md` (project rules: data boundary, commit rule, finding IDs) and `tests/T14/T14.md` (the test this one extends).

---

## 0. Manu's request, in his words, and what was agreed

> "if you understood this, then I want you to make one more test, T15, where, when the 3-switch, 3-index switch, and Gold both are in sell, you will buy Liquid Bees as well as the direct index, which is in buy. If there are 2 indices available, then you will do 33%, 33%, 33%, 33% so that it's some 200 between the liquid and the 2 indices that aren't by. If there is 1, then you do 50-50 between liquid and the index that is in buy."

Claude restated it (thirds summing to 100; at most two indices can be BUY in an OUT week, since three BUY is IN) and asked five questions. Manu's answers (chat, 2026-11-25):

| # | Question | Answer |
|---|---|---|
| 1 | No index BUY in an OUT-SELL week: 100% liquid? | "yes correct" |
| 2 | "Direct index" = the index level itself (price return, no dividends, no ETF cost), filled at OHLC4 as T09; "Liquid Bees" = the LBES cash series of T08/T11/T14? | "yes, direct index" |
| 3 | Both base sleeves (50/50, 80/20) and both windows, as T14? | "yes" |
| 4 | When the BUY set changes inside the regime? | "when new index become buy you should buy that index too, applying a rebalance" |
| 5 | Nulls and chance checks as T14 (E1/E2/G1/G2, R6, a random-index null)? | "No need for null tests and chance check" |

Claude's reading of answer 4, stated in chat and not objected to: the symmetric case is the same, **an index that turns SELL inside the regime is sold and the rest re-equalised** (1/3, 1/3, 1/3 -> 1/2, 1/2). Between changes the weights drift (no weekly reset), as in T14.

Data: daily index prices were approved only to 2019-01-04 (D25). On Manu's go-ahead the 2019-2026 rows were extracted from the same production file (D25c, `data/extend_index_prices.py`, commit `69090d8`) and **approved by Manu 2026-11-25** (commit `5aa695b`): every D25 row equals production's, and the production supertrend run on D25 + D25c reproduces the approved D03 signals exactly (0 SIGN mismatches, 0.0 in every column).

So: **one change to the rule**, applied only in the **OUT-SELL regime** (three-index switch OUT, i.e. not all of Nifty 100, Midcap 100, Smallcap 100 BUY, **and** the weekly MAUc1 gold supertrend SELL): hold the liquid ETF and each index whose own SIGN is BUY, in equal parts. Everything else is the rule of T06/T08/T11/T14. **No null and no chance claim** (Manu's waiver, as T10's): the test is descriptive, with pre-registered comparisons against the other ways of holding the regime.

## 1. Context

| Test | Window | Rule | Result (after 20.8 bps) |
|---|---|---|---|
| T06 / T08 (COMPLETE) | 2019-01-02 -> 2026-10-30, real parents | switch; OUT = 50/50 GOLDBEES/cash (T06) or 80/20 / 20/80 by MAUc1 (T08) | equity timing PASS against random timing (94-97) |
| T11 (COMPLETE) | 2014-09-01 -> 2019-01-02, rebuilt parents | both rules | all criteria FAIL, low power |
| **T14** (COMPLETE 2026-11-23) | both windows | OUT-SELL holds half parent + half GOLDBEES (`-half`) or 100% liquid (`-liq`) | `-half` beat its original in every book (+3.3 to +5.8 pp CAGR W1, +2.0 to +4.7 pp W2), not established as timing; **`-liq` lowered CAGR in 16 of 16 book-windows** (-0.04 to -1.79 pp) |

T15 is a third holding for the same regime. **A new question under a changed rule gets a new test number** (AGENT.md task 3). **Change one thing at a time** (task 5): the only change from T14's rules is the OUT-SELL target. In the OUT-SELL weeks with no index BUY, T15's rule **is** `-liq`; so `-idx` minus `-liq` isolates what holding the BUY indices adds, and `-idx` minus `-orig` is the whole change.

## 2. The eight rules (targets per weekly decision)

Regimes at each weekly decision: **IN** = all three index SIGNs BUY; **OUT-BUY** = switch OUT and MAUc1 SIGN BUY; **OUT-SELL** = switch OUT and MAUc1 SIGN SELL. In OUT-SELL let **B** be the set of indices whose own D03 SIGN is BUY at that decision (0, 1 or 2 of Nifty 100, Midcap 100, Smallcap 100) and k = |B|.

A target is now the book's split across **parent / GOLDBEES / cash / each index**. T14's `(e, gw)` maps to parent e, GOLDBEES (1-e)·gw, cash (1-e)·(1-gw), indices 0.

| Rule id | Base | IN | OUT-BUY | **OUT-SELL** | Is |
|---|---|---|---|---|---|
| `50-orig` | 50/50 | parent 1 | GOLDBEES 0.5, cash 0.5 | GOLDBEES 0.5, cash 0.5 | T06 / T11 A (comparator; regression vs T14) |
| `50-liq` | 50/50 | parent 1 | GOLDBEES 0.5, cash 0.5 | cash 1 | T14 variant (comparator; regression) |
| `50-half` | 50/50 | parent 1 | GOLDBEES 0.5, cash 0.5 | parent 0.5, GOLDBEES 0.5 | T14 variant (comparator; regression) |
| **`50-idx`** | 50/50 | parent 1 | GOLDBEES 0.5, cash 0.5 | **cash 1/(k+1), each index in B 1/(k+1)** | **new** |
| `80-orig` | 80/20 | parent 1 | GOLDBEES 0.8, cash 0.2 | GOLDBEES 0.2, cash 0.8 | T08 / T11 B (comparator; regression) |
| `80-liq` | 80/20 | parent 1 | GOLDBEES 0.8, cash 0.2 | cash 1 | T14 (comparator; regression) |
| `80-half` | 80/20 | parent 1 | GOLDBEES 0.8, cash 0.2 | parent 0.5, GOLDBEES 0.5 | T14 (comparator; regression) |
| **`80-idx`** | 80/20 | parent 1 | GOLDBEES 0.8, cash 0.2 | **cash 1/(k+1), each index in B 1/(k+1)** | **new** |

So in OUT-SELL: k = 0 -> 100% cash; k = 1 -> 50% cash, 50% that index; k = 2 -> 1/3 cash, 1/3 each of the two indices. `-idx` holds no parent and no GOLDBEES in the regime. The six T14 rules are re-run by the same engine as comparators and as the regression gate (decision point D2).

### 2.1 Execution of the new states (to be frozen in §3)

Everything not listed is T14 §3 unchanged (decide on the last session of each ISO week and T0; read the latest D03 and MAUc1 rows dated on or before the decision; trade on the next session at OHLC4; 10.4 bps a side on every value traded, 20.8 bps round trip primary, 0 and 50 as robustness; initial position free; last decision made, not traded).

1. **When a trade happens.** On the session after decision j iff decision j's target differs from decision j-1's. For `-idx` the target includes B, so **a change of B inside OUT-SELL is a trade** (Manu's answer 4), as are every entry into and exit from the regime. A change of an index SIGN while IN or OUT-BUY does not trade (those targets do not depend on B).
2. **What a trade does.** The existing `trade()` generalised to index lines: at the session's fill prices (stocks OHLC4, GOLDBEES de-spiked OHLC4, cash at its level, **each index at its own OHLC4**), V = value of all holdings; target value of each line = target share × V; traded = Σ |target − held| over every line (stocks, GOLDBEES, cash, each index); cost = traded × cost_bps ÷ 2 ÷ 1e4; every target is scaled by (V − cost) ÷ V. **A change of B re-equalises every line** (cash included) to 1/(k+1): MC100+SC100 -> MC100 sells all SC100 and moves MC100 and cash to 1/2 each; SC100 -> MC100+SC100 buys MC100 to 1/3 and trims SC100 and cash to 1/3 each.
3. **No reset inside an unchanged target.** While B and the regime are unchanged, weights drift and nothing is traded weekly.
4. **Parent rebalances while `-idx` is in OUT-SELL:** the parent share is 0, nothing is traded (as `e = 0` in T14). The `-half` comparators keep T14's D1 rule.
5. **Index NAV marking.** Units × the index close. On a calendar session with no index bar (W2: the Budget weekend sessions 2020-02-01, 2025-02-01, 2026-02-01, all last sessions of their ISO week, so decision sessions, never trade sessions) the last close is carried and counted in `audit.json`. If a trade session ever lacks an index bar, the engine stops (it should not happen; asserted).
6. **Same-session collisions** (as T14): a basket change on the session of a regime trade is one trade to the new basket at the new target; a gold flip and an exit on the same decision is one trade straight to the new target; a B change and an exit on the same decision is one exit trade.

## 3. Windows, pinned to T14's inputs

Each window uses exactly T14's inputs and conventions (so the six T14 rules reproduce T14's stored results, gate V4(a)) **plus the daily index prices**:

| | **W1** (T11's / T14's) | **W2** (T08's / T14's) |
|---|---|---|
| Dates | 2014-09-01 -> 2019-01-02 | 2019-01-02 (SCMO_0007: 2019-01-04) -> 2026-10-30 |
| Calendar | D26 NSE sessions (1,070) | D17 dates of the extended published NAVs (1,932) |
| Parent, signals, GOLDBEES, cash | as T14 W1 (D18/D19/D05, D03, D24b, D09 + D24b range, D11) | as T14 W2 (same, D24, D12 range) |
| **Index prices (new)** | **D25** `Historical Data/extended_2026-11-12/index_daily_pre2019/{Nifty100,MC100,SC100}_daily_ohlcv.csv` (SC100 usable from 2011-10-03; the window starts later) | **D25c** `Historical Data/extended_2026-11-25/index_daily_2019_2026/{Nifty100,MC100,SC100}_daily_ohlcv.csv` |
| R3 | from 2015-01-02 | live decisions from 2021-11-01 |
| R2 | LIQUIDCASE as cash, whole window | LIQUIDCASE from 2024-01-24 |

No draws are made, so no seeds are used.

### 3.1 What the regime looks like (counted 2026-11-25 from T14's stored `decisions.csv`, SCMO_0003; the four books share the series)

| | W1 | W2 |
|---|---|---|
| weekly decisions | 228 | 410 (SCMO_0007 409) |
| OUT-SELL weeks / spells | 54 / 8 | 46 / 8 |
| OUT-SELL weeks with k = 0 (`-idx` = `-liq`) | 21 | 24 |
| weeks with k = 1 / k = 2 | 18 / 15 | 2 / 20 |
| **weeks holding at least one index** | **33**, in 6 of the 8 spells | **22**, in 6 of the 8 spells |
| B changes inside the regime (extra trades) | 8 | 6 |
| trades of `-idx` that involve the regime (entries, exits, B changes) | 24 | 21 |

Spell by spell (start, weeks: the B sequence):

- **W1:** 2014-10-17, 7: MC100 2, N100+MC100 5 · 2014-12-12, 6: MC100+SC100 1, MC100 5 · 2015-03-27, 7: MC100+SC100 6, cash 1 · 2015-07-10, 1: cash · 2015-11-13, 11: cash 6, SC100 3, cash 2 · 2016-11-04, 11: MC100+SC100 1, cash 9, SC100 1 · 2018-06-29, 9: N100 7, N100+MC100 2 · 2018-11-22, 2: cash.
- **W2:** 2019-03-08, 1: MC100+SC100 · 2019-05-10, 4: cash 2, N100 1, N100+MC100 1 · **2021-01-29, 10: MC100+SC100 10** · 2021-10-29, 2: N100+MC100 · 2022-05-13, 12: cash 10, N100+MC100 2 · 2024-11-14, 11: cash 3, SC100 1, MC100+SC100 4, cash 3 · 2026-03-20, 4: cash · 2026-10-23, 2: cash.
- **R3 windows:** W1 from 2015-01-02: 44 OUT-SELL weeks, 23 holding an index; W2 live from 2021-11-01: 30 OUT-SELL weeks, **only 8 holding an index** (2021-11-03 1 week, 2022-05 2 weeks, 2024-11 5 weeks).

Step 1 recomputes these from the signal files and calendars and writes `logs/step_1_spell_counts.json`; where they differ, Step 1 wins and the TRACKER notes it. **The effective sample is the index-holding stretches: 6 spells per window, and in W2 one stretch (2021-01-29, 10 weeks) is 10 of the 22 index weeks.** Every write-up says so.

## 4. What is known before freezing (to be quoted in §2 of `T15.md`)

- **Both windows are seen, and so is T14.** T06, T08, T11, T13 and T14 ran rules on these weeks; T14's per-book results, its regime ledger (which spells gained, what the parent, GOLDBEES and cash returned in each) and its finding that `-liq` lost in every book-window were seen before this request. In particular the W2 spell of 2021-01-29, which holds MC100+SC100 for all 10 weeks under `-idx`, is the spell where the parent rose 20.6% and T14's `-half` gained most. **The variant was proposed after seeing all of this**: any finding is **PROVISIONAL at most**, and there is no hold-out (signals after 2026-10-30 are not approved).
- No null is run (Manu's waiver, chat 2026-11-25). **No statement about chance or skill can be made**: the results say what each holding earned over these weeks, nothing about whether the BUY indices were chosen well.
- **Expectation, declared, no direction claimed.** In the 21 (W1) and 24 (W2) cash-only weeks `-idx` equals `-liq`; the whole difference from `-liq` comes from the 33 / 22 index weeks. From `-orig`, `-idx` also drops all GOLDBEES in the regime, which cost `-liq` -0.04 to -1.79 pp in T14.
- The index leg is a price index: it earns no dividends and pays no fund expense or tracking error. A real index fund or ETF would differ by roughly the dividend yield minus its costs, and Smallcap 100 / Midcap 100 funds were thin or absent in 2014-2019. Disclosed, not corrected.

## 5. Comparisons (descriptive; pre-registered pass marks; no null)

For each window w in {W1, W2}, base b in {50, 80}, judged per book after 20.8 bps over the whole window (decision point D1):

| # | Statement about `b-idx` | Comparator | Pass |
|---|---|---|---|
| C1 | earns more than the original rule | `b-orig` | CAGR higher in >= 3 of 4 books |
| C2 | its worst fall is no deeper than the original's | `b-orig` | max drawdown shallower or equal in >= 3 of 4 books |
| C3 | holding the BUY indices adds to holding only cash in the regime | `b-liq` | CAGR higher in >= 3 of 4 books |
| C4 | does better than holding half the parent and half GOLDBEES in the regime | `b-half` | CAGR higher in >= 3 of 4 books |

**16 comparisons** (4 × 2 bases × 2 windows). Printed beside each: the difference in pp per book, Calmar, volatility, trades and cost paid. **The four books are one market seen four times**, and in OUT-SELL weeks `-idx` holds exactly the same indices and cash in every book, so their agreement is close to automatic and "3 of 4" is weaker here than in earlier tests. **A pass is a description of seen weeks, never a claim about chance.** Choosing the best of the eight rules from these tables is a selection on seen data, and the write-up must say so.

### 5.1 The headline the decision needs

- **D-table:** per window, book and cost: CAGR, max drawdown, Calmar, volatility of every rule, and the differences `-idx` − `-orig`, `-idx` − `-liq`, `-idx` − `-half`; start and end dates; trades and cost; weeks and sessions in each regime and in each k.
- **Regime ledger:** for each OUT-SELL spell and each B stretch inside it: dates, weeks, B, the return of each index, cash, GOLDBEES and the parent over the stretch, and each rule's return over it, so the reader sees which stretches carry the difference.
- **Comparators** (benchmarks): hold the parent; hold each index alone over the window; the constant mix at `-idx`'s own average shares of parent, GOLDBEES, cash and each index (shows how much of a difference is just a different average exposure).

## 6. Robustness (reported; they set a finding's status, not the comparisons)

- **R1:** C1-C4 and the D-table at 0 and 50 bps.
- **R2:** with LIQUIDCASE as the cash leg (W1 whole window; W2 from 2024-01-24). Cash is 1/3 to 100% of `-idx`'s regime holding, so this matters.
- **R3:** C1-C4 and the D-table on W1 from 2015-01-02 and on W2's live decisions from 2021-11-01 (each with its own first state, as T14). W2's live window has only 8 index weeks.
- **R4: leave one spell out.** For each OUT-SELL spell s, a run in which `-idx` holds `-liq`'s target (100% cash) during spell s only; C1-C4 recomputed. Shows whether one spell (in W2, 2021-01-29) carries the verdict. Deterministic; no draws.
- **R5: fund-cost drag on the index leg.** C1-C4 with each index's daily return reduced by 0.5 pp a year, accrued daily on the index holding (a fund's expense and tracking error). The opposite side, dividends, is **not run**: no approved dividend series exists; disclosed as untested.

## 7. Outcome map (to be frozen)

| Pattern (per window, per base) | Conclusion |
|---|---|
| C1 and C3 pass | holding the BUY indices with cash earned more than the original sleeve and more than cash alone on this window; PROVISIONAL (seen, post-hoc, no null) |
| C3 passes, C1 fails | the indices beat cash but giving up GOLDBEES cost more than they added |
| C3 fails | holding the BUY indices did not beat cash in the regime on this window |
| C4 passes / fails | `-idx` did better / worse than T14's `-half` on this window |
| R4 flips a passing comparison when one spell is left out | the result rests on that spell; say which; at most a description of it |
| the two windows disagree | report both; no general statement; the 2019-2026 window is the one the live product traded |
| R3 (live) disagrees with the full window | reported in the verdict and status note |
| a V gate fails | nothing is read; fix; new run directory |

## 8. Validity gates (any failure: nothing below may be read)

| # | Gate | Pass condition |
|---|---|---|
| V1 | Independent verifier `analysis/verify_t15.py`, written by a **different agent** from the engine's, from `logs/verifier_spec.md`, never opening `t15_engine.py` (it may read `verify_t14.py`) | Imports nothing from the engine, `approved_data.py` or any AA analysis module; parses `APPROVED_DATA.md` itself; checks every input is APPROVED with matching sha256 and a through-date covering the window. Re-derives from the raw files, per window: the decisions, regimes and B; the eight rules' NAVs at every cost and R1-R4 variant; every trade (regime entries and exits, B changes, sleeve and basket trades). End NAV within relative 1e-9, daily NAV within 1e-9. Exits 0 only if rows were compared and none failed; corrupted copies must exit non-zero (a B week flipped, a B change not traded, an index leg at 1/2 where k = 2, a `-idx` regime week holding GOLDBEES, a NAV scaled, a trade removed, an index price shifted by one session) |
| V2 | Point in time | every decision reads Master and MAUc1 rows dated on or before it; every trade is on a later session; counted; violations 0 of a count > 0 |
| V3 | Index data tie | at every weekly decision of both windows, D03's `Index` column equals the index close of D25 / D25c on that date for all three indices (ties the traded prices to the signals); every trade session has a bar for each index traded |
| V4 | Regression and identities | (a) the six T14 rules reproduce T14's stored `daily_nav.csv` (every book, cost, rule, both windows) and `trades.csv` to relative 1e-12; (b) with every index price replaced by the cash level and cost 0, `-idx` equals `-liq` to 1e-12; (c) `-idx` equals `-liq` on every session before the first trade into an index; (d) automated diff of shared functions against `t14_engine.py` lists only the expected changes; (e) the signals equal the SIGN columns of D03, D24 (W2), D24b (W1) at every decision; (f) one-instrument always-in identity, as T14 |
| V5 | Trade and cost identities | after every `-idx` trade into or inside OUT-SELL, each index in B and cash = 1/(k+1) of the value after cost, parent and GOLDBEES 0, to 1e-12 of NAV; index units 0 outside OUT-SELL; all units constant between trades; cost = traded × cost_bps ÷ 2 ÷ 1e4; one entry with k = 2, one B change and one exit worked by hand in §4.0a |

Oracle, negative-control and planted-effect controls (N6.7) are not run; listed as untested in §6 of `T15.md`.

## 9. Data (APPROVED rows of `data/APPROVED_DATA.md` only; the engine asserts it)

Run `python data/check_approved_data.py` first and at the top of `run.sh`; a non-zero exit means stop and ask Manu. Do not extend, rebuild or re-fetch anything.

Every file of T14 §3's table (both windows), plus:

| Role | W1 | W2 |
|---|---|---|
| Daily index prices (new) | D25 `Historical Data/extended_2026-11-12/index_daily_pre2019/{Nifty100,MC100,SC100}_daily_ohlcv.csv` (`guard_window` with 2014-09-01 for SC100) | D25c `Historical Data/extended_2026-11-25/index_daily_2019_2026/{Nifty100,MC100,SC100}_daily_ohlcv.csv` |

**Test evidence read by gates only (not data):** `tests/T14/evidence/headline/{w1,w2}/{daily_nav.csv, trades.csv, decisions.csv}`.
Not read: D09b, D03b, D20-D23 tags, D15 AA books, any PENDING or SUPERSEDED row, T14's `draws.csv`.
Known contaminants: T14's §3 list (rebuilt 2014-2018 parent with no published series; nine manual Eikon exports in W1; price returns only; cash file source before 2026-08-10 unrecorded, F-AA-D09, which matters more here since cash is 1/3 to all of the regime holding; GOLDBEES raw OHLC4 after 2026-09-28), plus: **the index leg is a price index with no dividends and no fund cost, not a tradable instrument**; the index prices come from production's Refinitiv file with no second source (tied to the signals by D25c's checks and V3); 2017-10-19 (W1 Muhurat) has D25 bars but no D18 bars (T11's stand-in for stocks, counted); three W2 Budget weekend sessions carry the last index close.

## 10. What the engine changes (`analysis/t15_engine.py`, a fork of `t14_engine.py`; copy, do not import)

1. **Index lines.** Load D25 (W1) / D25c (W2) through `approved_data.py`; fills at OHLC4, marks at close; positions gain three index unit columns.
2. **Rules and targets.** `RULES` = the six T14 rules + `50-idx`, `80-idx`; `targets(rule, in, g, B)` returns the split parent / GOLDBEES / cash / index weights; for the six T14 rules it returns exactly T14's `(e, gw)` mapping, so their path is unchanged (V4(a)).
3. **Trade trigger** on any change of the target vector (B included for `-idx`); trade kinds `regime_in`, `regime_out`, **`index_set_change`** beside T14's.
4. **The null machinery is removed** (no draws, no samplers, no `draws.csv`); R1-R4 are extra deterministic runs (cost, cash leg, start date, one spell switched to cash).
5. **Outputs** per window under `evidence/<run>/<window>/`: `decisions.csv` (signs, B, k, regime, per-rule target), `trades.csv`, `positions.csv`, `daily_nav.csv`, `stats.csv`, `regime_ledger.csv` (per spell and per B stretch), `robustness.csv` (R1-R5), `constant_mix_params.csv`, `audit.json`, `inputs.csv`, `regression.json`.
6. **Run time:** a few minutes per window (T14's real paths without its 2,000 draws); Step 2 records it.

## 11. Steps (same hand-off rules as T14; tracker `tests/T15/TRACKER.md`)

Read `TRACKER.md` before any step; update it when you finish; write `logs/step_<n>_log.md` per step; flag anything that changes a later step as **AFFECTS STEP n**. Commit at every milestone named in `AA/CLAUDE.md` (subject `T15: <outcome>`, explicit paths, never `git add -A`); push only when Manu asks.

0. **Plan and tracker.** This file (written directly; no plan-mode file exists to copy) and `TRACKER.md`. **Wait for Manu's approval and his answers to §13 before Step 1.**
1. **Pre-registration.** `spell_counts.py` (fork of T14's; adds B, k and the B stretches; signals, calendars and basket dates only) -> `logs/step_1_spell_counts.json`. `T15.md` §1-§3 in T14.md's layout, the null and chance sections replaced by §5's comparisons and the waiver; the plain-words walkthrough (AGENT.md rule 10) with places for real numbers marked. `check_prereg.py --freeze`; sha256 in the header; `AA/CLAUDE.md` test-in-progress line. **Commit** ("T15: pre-registration frozen ...").
2. **Engine** (§10). Smoke run (one book, both windows) exits 0 with V2-V5 passing, **V4(a) exact** against T14's stored NAVs. `logs/{step_2_log, evidence_contract, verifier_spec}.md`. Commit.
3. **Independent verifier** `analysis/verify_t15.py` (separate agent, from `logs/verifier_spec.md`). Passes the smoke run and catches every planted corruption. Commit.
4. **Test scripts** forked from `tests/T14/`: `analyse.py` (reads only evidence; prints every table; exits 1 on any failed gate), `fill_writeup.py` (§1-§3 byte-identical, F-AA-M02), `report.py`, `check_page.py`, `run.sh`. Steps 2-4 may run in parallel after Step 1. Commit.
5. **Run** `bash tests/T15/run.sh` -> `evidence/headline/{w1,w2}/`. Any gate failure: read nothing, fix, new run directory. Commit.
6. **Results and close.** `T15.md` §4 (generated) and §5-§8; `evidence/METHODS.md`; `evidence/report.html` (AGENT.md R10: the answer first; the D-table and the regime ledger; one backtest end to end with a worked k = 2 entry, a B change and an exit; per-book curves of all eight rules; R4 leave-one-spell-out; robustness; a start and end date on every number and curve). Finding IDs **pending** (counter after T07-T14). Update the "Latest completed test" bullet in `AA/CLAUDE.md`. Commit.

## 12. Key edge cases

1. Any input stale, `PENDING` or with a changed sha256: stop and ask Manu.
2. W2 starts OUT-BUY, W1 starts IN; SCMO_0007's W2 starts 2019-01-04.
3. A B change every week (W2 2019-05-10: cash, cash, N100, N100+MC100): a trade each week, each costed.
4. A 1-week spell (W1 2015-07-10, W2 2019-03-08): an entry and an exit one week apart.
5. B changes and a regime exit on the same decision: one exit trade (§2.1 item 6).
6. An index bar missing on a decision session (3 in W2): last close carried, counted; missing on a trade session: stop.
7. W2's last spell (2026-10-23, 2 weeks) ends at the window end: the last decision (2026-10-30) is not traded.
8. Cash weeks (k = 0): `-idx` and `-liq` must hold identical units (V4(c) until the first index trade; the ledger shows the rest).

## 13. Decision points for Manu (defaults in bold; settle before Step 1)

- **D1. What is judged:** **(a) the four descriptive comparisons C1-C4 of §5 with a pass mark of 3 of 4 books** / (b) no pass marks at all: the D-table and the ledger only.
- **D2. Comparators run in the same engine:** **(a) all six T14 rules (`-orig`, `-liq`, `-half` on both bases), which also makes T14's stored NAVs the regression gate** / (b) only the two `-orig` rules.
- **D3. An index that turns SELL inside the regime:** **(a) sold, the rest re-equalised to 1/(k+1)** (Claude's reading of answer 4, not objected to) / (b) something else (say what).

## 14. Files to create (all under `AA/`)

| File | Step |
|---|---|
| `tests/T15/PLAN.md` (this file), `TRACKER.md` | 0 |
| `tests/T15/T15.md`, `check_prereg.py`, `spell_counts.py`, `logs/step_1_spell_counts.json` | 1 |
| `analysis/t15_engine.py`, `tests/T15/logs/{step_2_log.md, evidence_contract.md, verifier_spec.md}` | 2 |
| `analysis/verify_t15.py`, `tests/T15/logs/step_3_log.md` | 3 |
| `tests/T15/{analyse,fill_writeup,report,check_page}.py`, `run.sh`, `logs/step_4_log.md` | 4 |
| `tests/T15/evidence/headline/{w1,w2}/`, `analysis.log`, `evidence/report.html`, `evidence/METHODS.md` | 5-6 |
| `CLAUDE.md` (edit: test-in-progress line, then the completed-test line) | 1, 6 |

Reused without change: `analysis/approved_data.py`; the real-path functions of `t14_engine.py` (copied, not imported).

## 15. Verification (end to end)

1. `python data/check_approved_data.py` exits 0; `inputs.csv` lists every file read (D25 / D25c included) with sha256 and approved row.
2. `python tests/T15/check_prereg.py` confirms §1-§3 unchanged; `spell_counts.py` equals the engine's counts.
3. V4(a): the six T14 rules reproduce T14's stored NAVs and trades to 1e-12; V4(b)/(c): `-idx` collapses to `-liq` when the indices are priced as cash.
4. Smoke run, then the verifier (exit 0, every corruption detected), then `bash tests/T15/run.sh`; `analyse.py` exits 1 on any failed gate; `check_page.py` reports its checks and 0 failures.
5. Right after every `-idx` regime trade the index and cash lines are each 1/(k+1) of NAV; no GOLDBEES and no parent in any `-idx` OUT-SELL week.
