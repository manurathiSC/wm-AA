# T16 Progress Tracker

**Overall status: PLAN DRAFTED (2026-11-26), awaiting Manu's approval and his answers to D1-D4 (PLAN.md §13).** Plan: `AA/tests/T16/PLAN.md`. The frozen design will be `T16.md` §1-§3 (Step 1).
Status values: `NOT_STARTED` → `IN_PROGRESS` → `DONE` (or `DONE_WITH_NOTES`).
**Data boundary:** read `AA/data/APPROVED_DATA.md`; use only its `APPROVED` rows; run `python data/check_approved_data.py` first (exit 0 on 2026-11-26: 84 approved rows, 0 problems); inputs are exactly T15's `inputs.csv` per window. If anything is stale, missing or unclear, stop and ask Manu.
**What T16 is:** T15's setup with a different OUT-SELL holding (three-index switch OUT **and** MAUc1 SELL): **Nifty 100, Midcap 100, Smallcap 100 and the liquid ETF, 25% each, whatever each index's own SIGN** (`50-all`, `80-all`). Set on entry, drift, no trade until the exit (D3 default). T15's eight rules (`-orig`, `-liq`, `-half`, `-idx` on both bases) are comparators and the regression gate. W1 2014-09-01 → 2019-01-02, W2 2019-01-02 → 2026-10-30, four real parents, 20.8 bps. **No null and no chance check**: descriptive comparisons C1-C6 (vs `-orig` CAGR and drawdown, vs `-liq`, vs `-half`, vs `-idx` CAGR and drawdown), R1-R5.
**Stop rule:** any input stale, PENDING or with a changed sha256 → stop and ask Manu.

| Step | Status | Blocked by | Agent / Date | Output summary |
|---|---|---|---|---|
| 0 Plan written, tracker created | DONE | — | Claude / 2026-11-26 | `PLAN.md` written directly (no plan-mode file to copy); counts taken from T15's `logs/step_1_spell_counts.json` (signals only). Manu 2026-11-26: **D1 = (a)** C1-C6; **D3 = (a)** 25% on entry, drift, trade only on leaving OUT-SELL; D2 answered with a request to define every rule in words (now a standing rule, AGENT.md R10 item 1, glossary in `AA/CLAUDE.md`); **D4: extend W2 to 2026-11-20 — blocked**: stock prices D18 (2026-11-04), cash D11 (2026-11-05) and the D17 calendar (2026-11-06) end earlier; asked Manu whether to refresh them. `PLAN_v2.md` to be written once D4 is settled |
| 1 Pre-registration | NOT_STARTED | 0 + approval | | |
| 2 Engine | NOT_STARTED | 1 | | |
| 3 Independent verifier | NOT_STARTED | 1 | | |
| 4 Test scripts | NOT_STARTED | 1 | | |
| 5 Run and gate | NOT_STARTED | 2, 3, 4 | | |
| 6 Analyse, report, write-up | NOT_STARTED | 5 | | |

## Files created or modified

### Step 0
- `AA/tests/T16/PLAN.md`, `AA/tests/T16/TRACKER.md`
