# T16 Plan v2: the three-index switch holding **all three indices and the liquid ETF, 25% each**, when the switch is OUT **and** gold is SELL, on both base sleeves (50/50 and 80/20), on T11's window 2014-09-01 -> 2019-01-02 and an **extended** W2 2019-01-02 -> **2026-11-20**

**Written 2026-11-26 by Claude; revision of `PLAN.md` (kept beside it, unchanged) after Manu's answers to its decision points.** What changed from `PLAN.md`: D1-D4 are settled (§13); **W2 is extended from 2026-10-30 to 2026-11-20** on the data Manu approved on 2026-11-25/26 (§3, §9), so the regression gate against T15 covers W2 to 2026-10-30 only (V4(a)); the counts in §3.1 gain the three new weeks; every page and write-up carries the rules-and-runs table (new standing rule, AGENT.md R10 item 1). Nothing in this plan has been run and no T16 engine, verifier or analysis code exists. The numbers below are week and spell counts stored by T15 Step 1 (`tests/T15/logs/step_1_spell_counts.json`; signals, calendars and basket dates only), the three new weeks' SIGNs as recorded in the approved-data notes (no price, NAV or return), a session check of the new files (2026-10-28 → 11-25: every calendar session to 11-20 has a bar in all three index files and GOLDBEES; GOLDBEES's Muhurat bar 2026-11-08 is not a calendar session), T15's published results (seen, quoted in §4), and `python data/check_approved_data.py` (exit 0 on 2026-11-26: 98 approved rows, 0 problems). **Status: DRAFT v2, awaiting Manu's go-ahead.** On approval the frozen design becomes `T16.md` §1-§3 (Step 1), which wins over this plan where they differ. This file is kept as written once approved; a further revision goes beside it as `PLAN_v3.md`. Read it with `AGENT.md`, `AA/CLAUDE.md` (its glossary of rule ids) and `tests/T15/T15.md` (the test this one changes).

---

## 0. Manu's request, in his words

> "can you plan a T16. just the plan without the null, where in the out-sell weeks we will buy the Nifty 100, MC100, SC100 and Liquid ETF in equal weight ie. 25% each. its the same as the T15 but the buy conditions changes during the out sell weeks"

His answers to `PLAN.md` §13 (chat, 2026-11-26): "D1, what is judged: (a) all six comparisons, C1–C6"; on D2 he asked what the eight rules are and that every rule and run be described in words on the page and in the md files (done: AGENT.md R10 item 1, glossary in `AA/CLAUDE.md`; default (a) kept, all eight T15 rules run as comparators); "D3 ... (a) set 25% each on entry, then let the weights drift until the exit, obviously here exit mean we are out of OUT-SELL regime right?" (yes: the exit is the first decision that is IN or OUT-BUY); "window should be extended to the latest period till 20/11/2026 or beyond" and "data is approved to latest dates, please check" (checked: §3).

Claude's reading, confirmed by those answers:

- **One change from T15:** in the OUT-SELL regime (three-index switch OUT **and** weekly MAUc1 SIGN SELL) the book holds **Nifty 100 25%, Midcap 100 25%, Smallcap 100 25%, liquid ETF 25%**, whatever each index's own SIGN is. T15's rule held only the indices whose SIGN was BUY (1/(k+1) each); T16 drops that condition.
- "Index" and "Liquid ETF" mean exactly what they meant in T15: the index level itself (price return, no dividends, no fund cost), filled at its own OHLC4; and the LBES cash series.
- Everything outside the OUT-SELL weeks is unchanged (IN: the parent; OUT-BUY: the base sleeve).
- **No null and no chance claim** (as T15, Manu's waiver): descriptive, pre-registered comparisons against the other ways of holding the regime.

## 1. Context

| Test | Rule in the OUT-SELL weeks | Result (after 20.8 bps) |
|---|---|---|
| T06 / T08 / T11 | the original sleeve (`-orig`) | equity timing PASS on 2019-2026 (94-97 vs random timing); FAIL on 2014-2018, low power |
| T14 (COMPLETE 2026-11-23) | half parent + half GOLDBEES (`-half`), or 100% liquid ETF (`-liq`) | `-half` beat `-orig` in every book (+2.0 to +5.8 pp CAGR); `-liq` lowered CAGR in 16 of 16 book-windows |
| **T15** (COMPLETE 2026-11-25) | liquid ETF + the BUY indices, 1/(k+1) each (`-idx`) | 4 of 16 comparisons pass; the windows disagree; **never beats `-half`** (-6.0 to -3.0 pp); the W2 passes rest on one 10-week stretch (2021-01-29) |

T16 is a fourth holding for the same regime. **A new rule gets a new test number** (AGENT.md task 3); **one thing changes** (task 5): only the OUT-SELL target. Because T16 always holds all three indices in the regime, `-all` minus `-idx` measures **what following the index signals inside the regime did** (together with the weight change from 1/(k+1) to 1/4, §4).

## 2. The ten rules (targets per weekly decision)

Regimes at each weekly decision, as T15: **IN** = all three index SIGNs BUY; **OUT-BUY** = switch OUT and MAUc1 SIGN BUY; **OUT-SELL** = switch OUT and MAUc1 SIGN SELL. B and k as T15 (the BUY indices in OUT-SELL); `-all` does not use them.

A target is the split parent / GOLDBEES / cash / Nifty 100 / Midcap 100 / Smallcap 100.

| Rule id | Base | IN | OUT-BUY | **OUT-SELL** | Is |
|---|---|---|---|---|---|
| `50-orig` | 50/50 | parent 1 | GOLDBEES 0.5, cash 0.5 | GOLDBEES 0.5, cash 0.5 | comparator; regression vs T15 |
| `50-liq` | 50/50 | parent 1 | GOLDBEES 0.5, cash 0.5 | cash 1 | comparator; regression |
| `50-half` | 50/50 | parent 1 | GOLDBEES 0.5, cash 0.5 | parent 0.5, GOLDBEES 0.5 | comparator; regression |
| `50-idx` | 50/50 | parent 1 | GOLDBEES 0.5, cash 0.5 | cash and each BUY index 1/(k+1) | T15; comparator; regression |
| **`50-all`** | 50/50 | parent 1 | GOLDBEES 0.5, cash 0.5 | **cash 0.25, Nifty 100 0.25, Midcap 100 0.25, Smallcap 100 0.25** | **new** |
| `80-orig` | 80/20 | parent 1 | GOLDBEES 0.8, cash 0.2 | GOLDBEES 0.2, cash 0.8 | comparator; regression |
| `80-liq` | 80/20 | parent 1 | GOLDBEES 0.8, cash 0.2 | cash 1 | comparator; regression |
| `80-half` | 80/20 | parent 1 | GOLDBEES 0.8, cash 0.2 | parent 0.5, GOLDBEES 0.5 | comparator; regression |
| `80-idx` | 80/20 | parent 1 | GOLDBEES 0.8, cash 0.2 | cash and each BUY index 1/(k+1) | T15; comparator; regression |
| **`80-all`** | 80/20 | parent 1 | GOLDBEES 0.8, cash 0.2 | **cash 0.25, Nifty 100 0.25, Midcap 100 0.25, Smallcap 100 0.25** | **new** |

`-all` holds no parent and no GOLDBEES in the regime, and 75% in the three indices. Since the switch is OUT in every OUT-SELL week, **at least one of the indices `-all` holds is on its own SELL signal in every regime week, and all three are in the k = 0 weeks.**

### 2.1 Execution (to be frozen in §3)

Everything not listed is T15 §2.2 / T14 §3 unchanged (decide on the last session of each ISO week and T0; read the latest D03 and MAUc1 rows dated on or before the decision; trade on the next session at OHLC4; 10.4 bps a side on every value traded, 20.8 bps round trip primary, 0 and 50 as robustness; initial position free; the last decision is made, not traded).

1. **When a trade happens.** On the session after decision j iff decision j's target differs from decision j-1's. For `-all` the OUT-SELL target is fixed, so **only entries into and exits from the regime trade**; an index SIGN change inside the regime does **not** trade (the opposite of T15).
2. **What a trade does.** T15's `trade()` unchanged: at the session's fill prices (stocks OHLC4, GOLDBEES de-spiked OHLC4, cash at its level, each index at its own OHLC4), V = value of all holdings; target value of each line = share × V; traded = Σ |target − held|; cost = traded × cost_bps ÷ 2 ÷ 1e4; every target scaled by (V − cost) ÷ V.
3. **No reset inside the regime** (D3 = a, Manu): the four lines are set to 25% on entry and then drift until the exit; nothing is traded weekly. **The exit is the first decision that is not OUT-SELL**: IN (all three SIGNs BUY: back to the parent) or OUT-BUY (MAUc1 turns BUY: to the base sleeve); the trade is on the next session.
4. **Parent rebalances while `-all` is in OUT-SELL:** parent share 0, nothing traded.
5. **Index marking and missing bars:** as T15 (units × close; the three W2 Budget weekend sessions carry the last close and are decision sessions only; a trade session without an index bar stops the engine).
6. **Same-session collisions:** as T15 (a basket change on the session of a regime trade is one trade to the new basket; a gold flip and an exit on the same decision is one trade straight to the new target).
7. **Initial position** in an R3 window that starts in OUT-SELL (both do): `-all` holds 25% of each line at that day's closes, free.

## 3. Windows: W1 pinned to T15's inputs, W2 extended to 2026-11-20

**W1** uses exactly T15's W1 inputs (same files, same sha256). **W2 is extended to 2026-11-20** (D4, Manu 2026-11-26). Latest usable dates of the roles W2 reads (`data/APPROVED_DATA.md`, checked 2026-11-26): calendar / published NAV D17 2026-11-25, stock prices D18 2026-11-25, cash D11 2026-11-25, GOLDBEES D09 2026-11-23, **index signals D03, daily index prices D25d and MAUc1 D24c 2026-11-20**, basket weights 2026-09-10/16 (no newer basket exists; the next is expected mid-December, after the window). So **2026-11-20 is the latest possible end** (the earliest of the roles; 2026-11-27 has not happened yet). Every extended file holds the rows T15 read verbatim (registry notes: D17 and D11 verbatim tails / byte prefixes, D18 append mode, D25d equal to D25c, D03 equal on every used column, D24c equal to D24b, which equals D24's SIGN and ST on every W2 week), so the eight T15 rules must reproduce T15's stored W2 results on every session to 2026-10-30 (V4(a)).

| | **W1** (T11's / T14's / T15's) | **W2** (T08's window, extended) |
|---|---|---|
| Dates | 2014-09-01 -> 2019-01-02 | 2019-01-02 (SCMO_0007: 2019-01-04) -> **2026-11-20** (the last decision, made, not traded) |
| Calendar | D26 NSE sessions (1,070) | D17 dates of `Historical Data/extended_2026-11-25/published_nav/SCMO_<p>.csv`, cut at 2026-11-20 (1,932 + 15 = 1,947 sessions; Step 1 counts them) |
| Stock prices (D18) | `data/holdings_matrix/SCMO_<p>_ohlc.csv` + `price_corrections.csv` | `Historical Data/extended_2026-11-25/holdings_ohlc/SCMO_<p>_ohlc.csv` + `data/holdings_matrix/price_corrections.csv` |
| Baskets (D19, D05) | as T15 | as T15 (newest baskets 2026-09-10/16) |
| Index signals (D03) | `extended_2026-10-30/Master/` (SC100 from 2011-11-25) | `Historical Data/extended_2026-11-20/Master/Master_{Nifty100,MC100,SC100}.xlsx` |
| MAUc1 signal | D24b `extended_2026-11-12/MAUc1_from_2003/Master_MAUc1.xlsx` | **D24c** `Historical Data/extended_2026-11-20/MAUc1_from_2003/Master_MAUc1.xlsx` |
| GOLDBEES (D09), de-spike range | as T15 W1 | `analysis/cache/why_gold_ohlc_eikon_extended_2026-11-23.parquet`; D12 range to 2026-09-28, raw OHLC4 after (as T15) |
| Cash (D11) / R2 | as T15 W1 | `Historical Data/LBES_Adjusted_Price_data_extended_2026-11-25.csv` / `liquidEtfFinal_extended_2026-11-25.csv` |
| Index prices | D25 (SC100 usable from 2011-10-03; the window starts later) | **D25d** `Historical Data/extended_2026-11-20/index_daily_2019_2026/{Nifty100,MC100,SC100}_daily_ohlcv.csv` |
| R3 | from 2015-01-02 | live decisions from 2021-11-01 to 2026-11-20 |
| R2 | LIQUIDCASE as cash, whole window | LIQUIDCASE from 2024-01-24 |

No draws, no seeds.

**The three new W2 weeks** (SIGNs as recorded in the approved-data notes; Step 1 recomputes): 2026-11-06 Nifty 100 BUY, Midcap 100 SELL, Smallcap 100 SELL; 2026-11-13 and 11-20 Nifty 100 BUY, Midcap 100 BUY, Smallcap 100 SELL; MAUc1 SELL in all three. So the switch stays OUT, gold stays SELL, and **W2's last OUT-SELL spell runs 2026-10-23 → 2026-11-20 (5 weeks instead of 2)**. Under `-idx` B becomes Nifty 100 (11-06), then Nifty 100 + Midcap 100 (11-13), so `-idx` trades twice more; `-all` and the other rules do not trade. The window ends inside the spell: the last decision (11-20) is not traded, and the result includes an open position marked at the 2026-11-20 closes.

### 3.1 What the regime looks like (W1 and W2 to 2026-10-30 from T15's `logs/step_1_spell_counts.json`; W2's three new weeks from §3; the four books share it)

| | W1 | W2 (to 2026-11-20) |
|---|---|---|
| weekly decisions | 228 | 413 (SCMO_0007 412) |
| OUT-SELL weeks / spells | 54 / 8 | 49 / 8 |
| **weeks `-all` holds the indices** | **54, in all 8 spells** (T15 `-idx`: 33 in 6) | **49, in all 8 spells** (`-idx`: 25 in 7) |
| of which k = 0 (all three indices held are on SELL; `-idx` = cash) | 21 | 24 |
| k = 1 / k = 2 | 18 / 15 | 3 / 22 |
| trades from regime and gold changes, `-all` (equal to `-liq`'s by construction) | 24 | 27 (expected; the new weeks add none) |
| R3: OUT-SELL weeks / spells; trades | W1 from 2015-01-02: 44 / 7; 21 | W2 live from 2021-11-01: 34 / 5; 16 |

Spells (start, weeks), as T15: **W1** 2014-10-17 7 · 2014-12-12 6 · 2015-03-27 7 · 2015-07-10 1 · 2015-11-13 11 · 2016-11-04 11 · 2018-06-29 9 · 2018-11-22 2. **W2** 2019-03-08 1 · 2019-05-10 4 · **2021-01-29 10** · 2021-10-29 2 · 2022-05-13 12 · 2024-11-14 11 · 2026-03-20 4 · **2026-10-23 5** (cash 2, Nifty 100 1, Nifty 100 + Midcap 100 2 under `-idx`; ends at the window end, the last decision not traded).

Step 1 recomputes these with `spell_counts.py` and writes `logs/step_1_spell_counts.json`; where they differ, Step 1 wins. **The effective sample is the 8 OUT-SELL spells per window** (7 and 5 in the R3 windows); the four books are one market seen four times.

## 4. What is known before freezing (to be quoted in §2 of `T16.md`)

- **Both windows are seen, and so are T14's and T15's results.** In particular: `-liq` lost CAGR in every book-window (T14); `-idx` lost to `-orig` and `-liq` on W1 and gained +0.7 to +0.8 pp over `-liq` on W2, almost all from the 2021-01-29 stretch (Midcap 100 + Smallcap 100, 10 weeks), and never beat `-half` (T15). The ledgers of both tests (what the parent, GOLDBEES, cash and each index returned in each spell) were seen. **The variant was proposed after seeing all of this: any finding is PROVISIONAL at most**, and there is no hold-out. The three new weeks (2026-11-06 → 11-20) were not in any test, but they are not unseen either: they happened before the request and their signals are in the approved-data notes; they are 3 weeks of one spell, so they cannot serve as a hold-out.
- No null is run (waiver). **No statement about chance or skill can be made.**
- **Expectation, declared, no direction claimed.** `-all` puts 75% of the book in equities in every OUT-SELL week against `-idx`'s 0-67% and `-liq`'s 0%, so it is closer to "stay invested" than any earlier variant except `-half` (50% parent + 50% GOLDBEES). Its difference from `-idx` has two parts that this test **cannot separate**: holding the indices whose own signal is SELL (the 21 / 24 k = 0 weeks are this alone), and the weight change from 1/(k+1) to 1/4 in the k ≥ 1 weeks. The ledger splits the difference by k so the reader sees where it comes from.
- The index leg is a price index (no dividends, no fund cost), as T15; disclosed, R5 tests the cost side.

## 5. Comparisons (descriptive; pre-registered pass marks; no null)

For each window w in {W1, W2} and base b in {50, 80}, per book after 20.8 bps over the whole window (D1):

| # | Statement about `b-all` | Comparator | Pass |
|---|---|---|---|
| C1 | earns more than the original rule | `b-orig` | CAGR higher in >= 3 of 4 books |
| C2 | its worst fall is no deeper than the original's | `b-orig` | max drawdown shallower or equal in >= 3 of 4 books |
| C3 | holding the three indices adds to holding only cash in the regime | `b-liq` | CAGR higher in >= 3 of 4 books |
| C4 | does better than half parent + half GOLDBEES in the regime | `b-half` | CAGR higher in >= 3 of 4 books |
| C5 | ignoring the index signals in the regime earns more than following them | `b-idx` | CAGR higher in >= 3 of 4 books |
| C6 | ignoring them does not deepen the worst fall | `b-idx` | max drawdown shallower or equal in >= 3 of 4 books |

**24 comparisons** (6 × 2 bases × 2 windows). "Higher" and "shallower or equal" by the unrounded statistics. Printed beside each: the difference in pp per book, Calmar, volatility, trades and cost paid. In OUT-SELL weeks `-all` holds the same four lines in every book, so "3 of 4" is close to automatic for the regime part; **a pass describes seen weeks, never chance.** Choosing the best of the ten rules from these tables is a selection on seen data, and the write-up says so. No multiplicity adjustment (nothing is tested against chance).

### 5.1 The headline the decision needs

- **Rules and runs table** (AGENT.md R10 item 1): every rule id (`50-orig` ... `80-all`), window label (W1, W2, live) and run (R1-R5) in plain words, its role and origin, before any other table; the same table in `T16.md` §2.
- **D-table:** per window, book and cost: CAGR, max drawdown, Calmar, volatility of all ten rules; the differences `-all` − `-orig`, − `-liq`, − `-half`, − `-idx`; start and end dates; trades and cost; weeks and sessions per regime and per k.
- **Regime ledger:** per OUT-SELL spell and per B stretch inside it (so by k): dates, weeks, B, each index's return, cash, GOLDBEES and the parent over the stretch, and each rule's return over it. **`-all` − `-idx` summed separately over the k = 0 weeks and the k ≥ 1 weeks.**
- **Comparators:** hold the parent; hold each index alone; the equal-weight three-index basket alone; the constant mix at `-all`'s own average shares, rebalanced at every decision.

## 6. Robustness (reported; they set a finding's status, not the comparisons)

- **R1:** C1-C6 and the D-table at 0 and 50 bps.
- **R2:** LIQUIDCASE as the cash leg (W1 whole window; W2 from 2024-01-24).
- **R3:** W1 from 2015-01-02 and W2's live decisions from 2021-11-01, each with its own first state (both start in OUT-SELL).
- **R4: leave one spell out.** For each OUT-SELL spell s, `-all` holds `-liq`'s target (100% cash) during s only; C1-C6 recomputed. Shows whether one spell (e.g. W2 2021-01-29) carries the verdict.
- **R5: fund-cost drag** on the index leg: each index OHLC4 and close of session i multiplied by (1 − 0.005 ÷ 252)^i from T0, as T15. Dividends (the other side) not run: no approved series; disclosed.
- **R6 (only if D3 = b): weekly reset**: the four lines reset to 25% at every OUT-SELL decision (one trade a week), to show what drift did.

## 7. Outcome map (to be frozen)

| Pattern (per window, per base) | Conclusion |
|---|---|
| C1 and C3 pass | holding the three indices with cash earned more than the original sleeve and more than cash alone on this window; PROVISIONAL (seen, post-hoc, no null) |
| C3 passes, C1 fails | the indices beat cash but giving up GOLDBEES cost more than they added |
| C3 fails | holding the three indices did not beat cash in the regime on this window |
| C5 passes / fails | ignoring the index signals in the regime earned more / less than following them (T15) on this window; the ledger's k = 0 / k ≥ 1 split says where |
| C6 fails | ignoring the signals deepened the worst fall against T15 |
| C4 passes / fails | `-all` did better / worse than T14's `-half` |
| R4 flips a passing comparison when one spell is left out | the result rests on that spell; say which |
| the two windows disagree | report both; no general statement; 2019-2026 is the window the live product traded |
| R3 (live) disagrees with the full window | reported in the verdict and status note |
| a V gate fails | nothing is read; fix; new run directory |

## 8. Validity gates (any failure: nothing below may be read)

| # | Gate | Pass condition |
|---|---|---|
| V1 | Independent verifier `analysis/verify_t16.py`, written by a **different agent** from `logs/verifier_spec.md`, never opening `t16_engine.py` (it may read `verify_t15.py`) | Imports nothing from the engine, `approved_data.py` or any AA analysis module; parses `APPROVED_DATA.md` itself; checks every input is APPROVED with matching sha256. Re-derives per window the decisions and regimes; the ten rules' NAVs at every cost and R variant; every trade. End NAV within relative 1e-9, daily NAV within 1e-9. Exits 0 only if rows were compared and none failed; corrupted copies must exit non-zero (a `-all` regime week at 1/3 or without one index, an index SIGN change traded inside the regime, GOLDBEES held in a `-all` regime week, a NAV scaled, a trade removed, an index price shifted by one session) |
| V2 | Point in time | every decision reads Master and MAUc1 rows dated on or before it; every trade on a later session; counted; 0 violations of a count > 0 |
| V3 | Index data tie | at every weekly decision, D03's `Index` column equals the D25 / D25c close for all three indices; every trade session has a bar for each index |
| V4 | Regression and identities | (a) the eight T15 rules reproduce T15's stored `daily_nav.csv` and `trades.csv` to relative 1e-12: W1 on every session; **W2 on every session 2019-01-02 → 2026-10-30 and every trade on or before 2026-10-30** (T15's last W2 decision was not traded, so later trades are new); every book, cost and rule; (b) with every index price replaced by the cash level and cost 0, `-all` equals `-liq` to 1e-12; (c) `-all` equals `-liq` on every session before the first regime entry; (d) automated diff of shared functions against `t15_engine.py` lists only the expected changes; (e) the signals equal the SIGN columns of D03, D24c (W2), D24b (W1), and on W2 to 2026-10-30 equal T15's stored `decisions.csv`; (f) T15's one-instrument identity |
| V5 | Trade and cost identities | after every `-all` regime entry each index and cash = 0.25 of the value after cost, parent and GOLDBEES 0, to 1e-12 of NAV; index units constant through every spell (no trade on an index SIGN change); index units 0 outside OUT-SELL; cost = traded × cost_bps ÷ 2 ÷ 1e4; one entry and one exit worked by hand in §4.0a |

Oracle, negative-control and planted-effect controls (N6.7) are not run; listed as untested in §6 of `T16.md`.

## 9. Data (APPROVED rows of `data/APPROVED_DATA.md` only; the engine asserts it)

Run `python data/check_approved_data.py` first and at the top of `run.sh`; non-zero exit = stop and ask Manu. Do not extend, rebuild or re-fetch anything. Files: W1 exactly T15's W1 `inputs.csv`; W2 the files of §3's table (approved 2026-11-25/26: D17 / D18 / D11 to 2026-11-25 by Manu himself; D03, D25d, D24c, D09 auto-approved on his instruction of 2026-11-25). The engine reads only to 2026-11-20 from the files that run later.

**Test evidence read by gates only (not data):** `tests/T15/evidence/headline/{w1,w2}/{daily_nav.csv, trades.csv, decisions.csv}`.
Not read: D09b, D03b, D20-D23 tags, D15 AA books, the superseded or older copies of the W2 files, any PENDING or SUPERSEDED row.
Extra contaminants for the extension: D03, D25d, D24c and the 2026-11-23 GOLDBEES file were auto-approved on Manu's instruction, not reviewed by him; Postgres `ohlcv_eikon` was rewritten on 2026-11-08 and the D18 extension keeps the approved rows verbatim and appends only the new sessions after a seam check (AA/CLAUDE.md); GOLDBEES fills after 2026-09-28 use the raw OHLC4 (more sessions than in T15); GOLDBEES has a Muhurat bar on 2026-11-08 that is not a calendar session (ignored, as every non-calendar bar).
Known contaminants: T15's §3 list unchanged (rebuilt 2014-2018 parent with no published series; nine manual Eikon exports in W1; price returns only; **the index leg is a price index with no dividends and no fund cost**, and Smallcap 100 / Midcap 100 funds were thin or absent in 2014-2019; cash file source before 2026-08-10 unrecorded, F-AA-D09; three W2 Budget weekend sessions carry the last index close; GOLDBEES raw OHLC4 after 2026-09-28).

## 10. What the engine changes (`analysis/t16_engine.py`, a fork of `t15_engine.py`; copy, do not import)

0. **W2 inputs and end date.** W2 reads the §3 files (D17/D18/D11 2026-11-25, D03/D25d/D24c 2026-11-20, D09 2026-11-23) and ends at 2026-11-20; W1 is unchanged. The data self-test and `inputs.csv` follow.
1. **Rules and targets.** `RULES` = T15's eight + `50-all`, `80-all`; `targets()` returns `(cash 0.25, each index 0.25)` for `-all` in OUT-SELL and T15's mapping for every other rule (V4(a)).
2. **Trigger** unchanged (any change of the target vector); for `-all` that is only regime entries and exits.
3. **Ledger** gains the `-all` − `-idx` split by k.
4. **R4** switches `-all` to cash for one spell; **R6** only if D3 = b.
5. **Outputs** as T15 under `evidence/<run>/<window>/`: `decisions.csv`, `trades.csv`, `positions.csv`, `daily_nav.csv`, `stats.csv`, `regime_ledger.csv`, `robustness.csv`, `constant_mix_params.csv`, `audit.json`, `inputs.csv`, `regression.json`.
6. **Run time:** about two minutes (T15: 2 min 11 s for eight rules).

## 11. Steps (tracker `tests/T16/TRACKER.md`)

Read `TRACKER.md` before any step; update it when you finish; write `logs/step_<n>_log.md` per step; flag anything that changes a later step as **AFFECTS STEP n**. Commit at every milestone of `AA/CLAUDE.md` (subject `T16: <outcome>`, explicit paths, never `git add -A`); push only when Manu asks.

0. **Plan and tracker.** This file (written directly; no plan-mode file) and `TRACKER.md`. **Wait for Manu's approval and his answers to §13 before Step 1.**
1. **Pre-registration.** `spell_counts.py` (fork of T15's; adds `-all`'s trade counts and index weeks) -> `logs/step_1_spell_counts.json`. `T16.md` §1-§3 in T15.md's layout with the plain-words walkthrough (AGENT.md rule 10). `check_prereg.py --freeze`; sha256 in the header; `AA/CLAUDE.md` test-in-progress line. **Commit.**
2. **Engine** (§10). Smoke run (four books, both windows) exits 0 with V2-V5 passing and **V4(a) exact** against T15's stored NAVs and trades. `logs/{step_2_log, evidence_contract, verifier_spec}.md`. Commit.
3. **Independent verifier** `analysis/verify_t16.py` (separate agent, from `logs/verifier_spec.md`). Passes the smoke run and catches every planted corruption. Commit.
4. **Test scripts** forked from `tests/T15/`: `analyse.py`, `fill_writeup.py` (§1-§3 byte-identical, F-AA-M02), `report.py`, `check_page.py`, `run.sh`. Steps 2-4 may run in parallel after Step 1. Commit.
5. **Run** `bash tests/T16/run.sh` -> `evidence/headline/{w1,w2}/`. Any gate failure: read nothing, fix, new run directory. Commit.
6. **Results and close.** `T16.md` §4 (generated) and §5-§8; `evidence/METHODS.md`; `evidence/report.html` (AGENT.md R10: the answer first; D-table; regime ledger with the k split; one backtest end to end with an entry and an exit worked by hand; per-book curves of all ten rules; R4; robustness; a start and end date on every number). Finding IDs **pending** (counter after T07-T15). Update the "Latest completed test" bullet in `AA/CLAUDE.md`. Commit.

## 12. Key edge cases

1. Any input stale, `PENDING` or with a changed sha256 against T15's `inputs.csv`: stop and ask Manu.
2. W2 starts OUT-BUY, W1 starts IN; SCMO_0007's W2 starts 2019-01-04; both R3 windows start in OUT-SELL (`-all` starts at 25% each).
3. A 1-week spell (W1 2015-07-10, W2 2019-03-08): entry and exit one week apart, each costed.
4. Index SIGN changes inside a spell (8 in W1, 6 in W2, which T15 traded): `-all` must **not** trade (V5).
5. A gold flip OUT-BUY -> OUT-SELL with no switch change: an entry trade from the sleeve to the four lines.
6. W2's last spell (2026-10-23 → 2026-11-20, 5 weeks) ends at the window end: the last decision is not traded and the open position is marked at the 2026-11-20 closes; R4's leave-out of this spell is reported like the others.
7. An index bar missing on a decision session (3 in W2): last close carried, counted; on a trade session: stop.
8. The W2 regression boundary: T15's W2 ended on the untraded decision of 2026-10-30; in T16 the same decision is traded where a rule's target changed (none expected: 10-30's targets equal 10-23's). V4(a) compares only to 2026-10-30.

## 13. Decision points (settled by Manu, chat 2026-11-26)

| | Decision | Settled |
|---|---|---|
| D1 | What is judged | **(a) C1-C6, pass mark 3 of 4 books** ("all six comparisons, C1–C6") |
| D2 | Comparators in the same engine | **(a) all eight T15 rules** (default kept; he asked for each rule to be described in words, now a standing rule) |
| D3 | Inside a spell | **(a) 25% each on entry, drift, trade only when the book leaves OUT-SELL** (no R6) |
| D4 | Window end | **W2 extended to 2026-11-20**, the latest date every role reaches (§3); W1 unchanged |

## 14. Files to create (all under `AA/`)

| File | Step |
|---|---|
| `tests/T16/PLAN.md` (this file), `TRACKER.md` | 0 |
| `tests/T16/T16.md`, `check_prereg.py`, `spell_counts.py`, `logs/step_1_spell_counts.json` | 1 |
| `analysis/t16_engine.py`, `tests/T16/logs/{step_2_log.md, evidence_contract.md, verifier_spec.md}` | 2 |
| `analysis/verify_t16.py`, `tests/T16/logs/step_3_log.md` | 3 |
| `tests/T16/{analyse,fill_writeup,report,check_page}.py`, `run.sh`, `logs/step_4_log.md` | 4 |
| `tests/T16/evidence/headline/{w1,w2}/`, `analysis.log`, `evidence/report.html`, `evidence/METHODS.md` | 5-6 |
| `CLAUDE.md` (edit: test-in-progress line, then the completed-test line) | 1, 6 |

## 15. Verification (end to end)

1. `python data/check_approved_data.py` exits 0; W1's `inputs.csv` equals T15's (paths and sha256); W2's lists the §3 files with their APPROVED rows and sha256.
2. `python tests/T16/check_prereg.py` confirms §1-§3 unchanged; `spell_counts.py` equals the engine's counts.
3. V4(a): the eight T15 rules reproduce T15's stored NAVs and trades to 1e-12; V4(b)/(c): `-all` collapses to `-liq` when the indices are priced as cash.
4. Smoke run, then the verifier (exit 0, every corruption detected), then `bash tests/T16/run.sh`; `analyse.py` exits 1 on any failed gate; `check_page.py` reports its checks and 0 failures.
5. Right after every `-all` entry the three indices and cash are each 25% of NAV; no GOLDBEES and no parent in any `-all` OUT-SELL week; no `-all` trade inside a spell.
