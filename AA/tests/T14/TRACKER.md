# T14 Progress Tracker

**Overall status: PLAN DRAFT, awaiting Manu's approval (2026-11-23).** Plan: `AA/tests/T14/PLAN.md` (written 2026-11-23 on Manu's request in chat; the frozen design will be `T14.md` §1–§3 and wins where they differ). Read this file and the plan before starting any step; update this file when you finish a step.
Status values: `NOT_STARTED` → `IN_PROGRESS` → `DONE` (or `DONE_WITH_NOTES`).
**Data boundary:** read `AA/data/APPROVED_DATA.md`; use only its `APPROVED` rows; run `python data/check_approved_data.py` first (exit 0 on 2026-11-23: 67 approved rows, 0 problems); if anything is stale, missing or unclear, stop and ask Manu.
**What T14 is:** the three-index switch (T06/T08/T11) with one change: in weeks where the switch is OUT **and** the MAUc1 gold signal is SELL (the OUT-SELL regime), the book holds either **50% parent + 50% GOLDBEES** (`-half`; the parent half follows the parent's rebalances) or **100% liquid ETF** (`-liq`), instead of the original sleeve. Tried on both base sleeves (50/50 = T06/T11 Part A; 80/20 = T08/T11 Part B), on W1 = 2014-09-01 → 2019-01-02 (T11's inputs) and W2 = 2019-01-02 → 2026-10-30 (T08's inputs). Six rules: `50-orig`, `50-half`, `50-liq`, `80-orig`, `80-half`, `80-liq`; the `-orig` rules are comparators and the regression gate. Criteria E1, E2 (vs F1) and G1, G2 (vs F3) for each new rule and window; the difference from the original rule is the descriptive headline.
**Stop rule:** fewer than 4 in-or-out round trips or fewer than 4 OUT-SELL spells in a window → NOT REPORTABLE, stop and ask Manu (from the stored logs: W1 8 round trips, 8 OUT-SELL spells; W2 9 round trips, 8 OUT-SELL spells; Step 1 recounts).
**Open decisions (PLAN §13):** D1 parent rebalance inside `-half`; D2 reuse T08/T11 null draws; D3 one test or two; D4 what decides. Do not start Step 1 until Manu has answered them.

| Step | Status | Blocked by | Agent / Date | Output summary |
|---|---|---|---|---|
| 0 Plan written, tracker created | DONE | — | Claude / 2026-11-23 | `PLAN.md` written directly (no plan-mode file exists to copy), this file created. Awaiting Manu's approval and D1–D4 |
| 1 Pre-registration | NOT_STARTED | 0 + Manu's approval | | |
| 2 Engine | NOT_STARTED | 1 | | |
| 3 Independent verifier | NOT_STARTED | 1 | | |
| 4 Test scripts | NOT_STARTED | 1 | | |
| 5 Run and gate | NOT_STARTED | 2, 3, 4 | | |
| 6 Analyse, report, write-up | NOT_STARTED | 5 | | |

## Step-level notes

- **Step 0 (2026-11-23).** OUT-SELL week counts in the plan (§3.1) were read from the stored `decisions.csv` of T08 and T11 (switch state and gold signal only, no price or return). Step 1 recomputes them from the signal files.

## Files created or modified

### Step 0
- `AA/tests/T14/PLAN.md`, `AA/tests/T14/TRACKER.md`
