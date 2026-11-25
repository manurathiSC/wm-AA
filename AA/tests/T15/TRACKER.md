# T15 Progress Tracker

**Overall status: IN PROGRESS (2026-11-25). Approved by Manu ("lets execute the T15", D1-D3 defaults); Steps 1-2 DONE (pre-registration frozen; engine written, smoke passes); Steps 3 (verifier) and 4 (scripts) next.** Plan: `AA/tests/T15/PLAN.md`. The frozen design will be `T15.md` §1-§3 (Step 1).
Status values: `NOT_STARTED` → `IN_PROGRESS` → `DONE` (or `DONE_WITH_NOTES`).
**Data boundary:** read `AA/data/APPROVED_DATA.md`; use only its `APPROVED` rows; run `python data/check_approved_data.py` first (exit 0 on 2026-11-25: 70 approved rows, 0 problems); if anything is stale, missing or unclear, stop and ask Manu. Index prices: D25 (W1) and D25c (W2, approved by Manu 2026-11-25).
**What T15 is:** T14's setup with one more holding for the OUT-SELL regime (three-index switch OUT **and** MAUc1 SELL): the liquid ETF plus each index whose own SIGN is BUY, in equal parts (k = 0: 100% cash; k = 1: 1/2 cash, 1/2 the index; k = 2: 1/3 each). A change of the BUY set inside the regime is a rebalance trade. Rules `50-idx`, `80-idx` beside T14's six (`-orig`, `-liq`, `-half` on both bases; comparators and the regression gate). W1 2014-09-01 → 2019-01-02, W2 2019-01-02 → 2026-10-30, four real parents, 20.8 bps. **No null and no chance check (Manu's waiver, chat 2026-11-25)**: descriptive comparisons C1-C4 (vs `-orig` CAGR and drawdown, vs `-liq`, vs `-half`), R1-R5.
**Stop rule:** any input stale, PENDING or with a changed sha256 → stop and ask Manu.

| Step | Status | Blocked by | Agent / Date | Output summary |
|---|---|---|---|---|
| 0 Plan written, tracker created | DONE | — | Claude / 2026-11-25 | `PLAN.md` written directly (no plan-mode file to copy); week counts read from T14's stored `decisions.csv` (signals only). Awaiting approval and D1-D3 |
| 1 Pre-registration | DONE | 0 | Claude / 2026-11-25 | Manu's "lets execute the T15" = approval, D1-D3 defaults. `spell_counts.py` equals PLAN 3.1. `T15.md` 1-3 frozen, sha256 `343566dd...`. Both R3 windows start in OUT-SELL (written into section 3 item 7) |
| 2 Engine | DONE | 1 | Claude / 2026-11-25 | `analysis/t15_engine.py`; smoke (4 books, both windows, 43 s): V2-V5 and step-1 counts pass; V4(a) exact (worst rel diff 0.0 vs T14's NAVs and trades); `logs/{step_2_log,evidence_contract,verifier_spec}.md` |
| 3 Independent verifier | NOT_STARTED | 1 | | |
| 4 Test scripts | NOT_STARTED | 1 | | |
| 5 Run and gate | NOT_STARTED | 2, 3, 4 | | |
| 6 Analyse, report, write-up | NOT_STARTED | 5 | | |

## Step-level notes

- **Step 0 (2026-11-25).** Before the plan: D25c (daily index prices 2019-01-01 → 2026-11-04) extracted read-only from production by `data/extend_index_prices.py` (commit `69090d8`) and approved by Manu (commit `5aa695b`); the production supertrend on D25 + D25c reproduces D03 exactly. Regime counts in PLAN §3.1 were read from T14's stored decision logs (no price or return).

## Files created or modified

### Step 0
- `AA/tests/T15/PLAN.md`, `AA/tests/T15/TRACKER.md`

### Step 1
- `AA/tests/T15/{T15.md, check_prereg.py, spell_counts.py}`, `logs/{step_1_spell_counts.json, step_1_log.md}`; `AA/CLAUDE.md` (test-in-progress line)

### Step 2
- `AA/analysis/t15_engine.py`, `AA/tests/T15/logs/{step_2_log.md, evidence_contract.md, verifier_spec.md}`
