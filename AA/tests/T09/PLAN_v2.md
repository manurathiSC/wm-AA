# T09 Plan v2: one change to `PLAN.md` (written 2026-11-12, after PLAN.md was approved, before any result existed)

**Change:** the window starts **2011-11-25**, not 2011-11-18 (Manu, chat 2026-11-12: "let's use from 25th of November 2011 only"). Everything else in `PLAN.md` stands; where the two differ, this file and then `T09.md` §1-§3 win.

**Why:** a clean recompute of the Smallcap 100 supertrend from the real-range bars only (D03b, a PENDING candidate, not used) matches D03 in every column from 2011-11-25 on; on 2011-11-18 only FLB differs (SIGN and ST agree), and on 2011-11-11 SIGN, ST and FLB differ. Manu chose the first week with every column equal. The D03 Smallcap 100 restriction in `data/APPROVED_DATA.md` moved from 2011-11-18 to 2011-11-25 (no SIGN-only exception any more). The Smallcap 100 price restriction (D25) stays 2011-10-03.

**What the new start changes (counts from `logs/step_1_spell_counts.json`, signals and calendar only):**

| | PLAN.md (start 2011-11-18) | T09 (start 2011-11-25) |
|---|---|---|
| sessions / weekly decisions | 1,759 / 373 | 1,754 / 372 (n = 371) |
| in-spells | 12, S 172, [1, 32] | unchanged |
| out-spells | 13, S 201, [2, 35], first 10 weeks | 13, S 200, [2, 35], first 9 weeks; tuples 480,915,680,540,493,952 |
| gold BUY spells | 15, S 191, [2, 36], first 4 | 15, S 190, [2, 36], first 3; tuples 76,727,187,438,249,573,981 |
| gold SELL spells | 14, S 182, [2, 27] | unchanged |
| sleeve trades (flips while OUT both sides) | 11 | 11 (the first, 2011-12-16, is still inside) |
| OUT weeks, gold BUY / SELL | 113 / 88 | 112 / 88 |
| R3 window (2012-01-02) | 367 decisions | unchanged |

The plan's own quick counts (372 decisions, 14 gold flips while IN, BUY in 112 of 200 OUT weeks) were made from Master rows for the 2011-11-18 start; they agree with the new window's counts by coincidence in places, and `T09.md` §2 is the reference.

**Procedure followed:** `T09.md` §1-§3 were unfrozen, edited and re-frozen the same day (new sha256 `30973068e5cd…`; the first issue's `1704243c…` is superseded). The Step 2 engine was under construction and no run of any kind had been examined.
