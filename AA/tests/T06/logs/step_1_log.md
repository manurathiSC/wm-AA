# Step 1 log: pre-registration (T06.md §1–§3)

**Date:** 2026-11-06. **Agent:** Claude.

**Order followed (PLAN_v2.md Step 1):**
1. `python data/check_approved_data.py`: exit 0 (32 approved rows OK, 0 problems, 0 pending, 5 superseded).
2. `python tests/T06/spell_counts.py`: spell counts on the new window, from the approved D17 calendar and the extended Master files only; no price, NAV or return read. Output `logs/step_1_spell_counts.json`.
3. Feasibility (2·k ≤ S ≤ HI·k per state) for every book, window and state: all feasible. Number of allowed N4.10 tuples (SCMO_0003, full window): 7,107,131,351,925 in-tuples, 89,734,761,224,680 out-tuples; live window 2,436,435 and 46,175,688.
4. `T06.md` §1–§3 written; the facts in it were re-checked against the outputs before the freeze. Four corrections were made before freezing: "at most one new switch" became "exactly one (an exit decided 2026-09-11)"; the claim about raw GOLDBEES fills was narrowed to the three sessions 2026-10-05, 10-12 and 10-19 (the rule's own last switch was traded on 2026-09-15); a stock-session count was tied to T03's figure; a paraphrase of T03 §7 item 1 was taken out of quotation marks.
5. `python tests/T06/check_prereg.py --freeze`: sha256 `a3851d402acdcff0b60372f3c0ad6a0a1651cfbd6590f1da5d24197d3baf7165`. `check_prereg.py` exits 0; on a copy with one character changed in §2 it exits 1; the original was restored and verified.

**Results of the counts** (SCMO_0003, 0010, 0029; SCMO_0007 differs only in its first out-spell, 10 weeks, sum 207): 409 weekly decisions (0007: 408), first state OUT, ends OUT; in-spells 8, 13, 33, 23, 20, 26, 46, 11, 21 (sum 201); out-spells 11, 29, 15, 16, 40, 18, 5, 30, 37, 7 (sum 208); 9 round trips; longest in 46, longest out 40, so the bounds are 2 / 46 / 40. Live window: 261 weeks, in 20, 26, 46, 11, 21 (sum 124), out 40, 18, 5, 30, 37, 7 (sum 137), 5 round trips. Decisions equal T03's `decisions.csv` on all shared dates (0 state and 0 date mismatches).

**Issues for later steps:** see the two `⚠ AFFECTS` notes in `TRACKER.md`. No open issue for Step 1.
