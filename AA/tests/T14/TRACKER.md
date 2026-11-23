# T14 Progress Tracker

**Overall status: COMPLETE (2026-11-23).** Manu's "execute T14 plan" (chat 2026-11-23) was taken as approval of the plan with the bold defaults of PLAN §13 (D1 a, D2 reuse draws, D3 one test, D4 criteria + descriptive headline; recorded in T14.md §2). Plan: `AA/tests/T14/PLAN.md`; frozen design `T14.md` §1-§3 (sha256 `99fe0f3a...`). Results: `T14.md` §4-§5, `evidence/report.html`. Finding IDs pending.
Status values: `NOT_STARTED` → `IN_PROGRESS` → `DONE` (or `DONE_WITH_NOTES`).
**Data boundary:** read `AA/data/APPROVED_DATA.md`; use only its `APPROVED` rows; run `python data/check_approved_data.py` first (exit 0 on 2026-11-23: 67 approved rows, 0 problems); if anything is stale, missing or unclear, stop and ask Manu.
**What T14 is:** the three-index switch (T06/T08/T11) with one change: in weeks where the switch is OUT **and** the MAUc1 gold signal is SELL (the OUT-SELL regime), the book holds either **50% parent + 50% GOLDBEES** (`-half`; the parent half follows the parent's rebalances) or **100% liquid ETF** (`-liq`), instead of the original sleeve. Tried on both base sleeves (50/50 = T06/T11 Part A; 80/20 = T08/T11 Part B), on W1 = 2014-09-01 → 2019-01-02 (T11's inputs) and W2 = 2019-01-02 → 2026-10-30 (T08's inputs). Six rules: `50-orig`, `50-half`, `50-liq`, `80-orig`, `80-half`, `80-liq`; the `-orig` rules are comparators and the regression gate. Criteria E1, E2 (vs F1) and G1, G2 (vs F3) for each new rule and window; the difference from the original rule is the descriptive headline.
**Stop rule:** fewer than 4 in-or-out round trips or fewer than 4 OUT-SELL spells in a window → NOT REPORTABLE, stop and ask Manu (from the stored logs: W1 8 round trips, 8 OUT-SELL spells; W2 9 round trips, 8 OUT-SELL spells; Step 1 recounts).
**Decisions (PLAN §13), settled 2026-11-23 by "execute T14 plan" with the defaults:** D1 (a) re-weight only the parent half at a parent rebalance inside `-half`; D2 reuse T08/T11 null draws; D3 one test, both windows as parts; D4 E1/E2/G1/G2 are the criteria, the difference from the original and its R6 paired percentile the descriptive headline. Manu can still overrule any of them before the engine run; the freeze (Step 1) records them.

| Step | Status | Blocked by | Agent / Date | Output summary |
|---|---|---|---|---|
| 0 Plan written, tracker created | DONE | — | Claude / 2026-11-23 | `PLAN.md` written directly (no plan-mode file exists to copy), this file created. Awaiting Manu's approval and D1–D4 |
| 1 Pre-registration | DONE | — | Claude / 2026-11-23 | `spell_counts.py` run (counts equal PLAN §3.1: W1 93/81/54 weeks, 8 OUT-SELL spells; W2 201/163/46, 8 spells; all reportable); `T14.md` §1–§3 written and frozen, sha256 `99fe0f3a…` (`python tests/T14/check_prereg.py`) |
| 2 Engine | DONE | 1 | Claude / 2026-11-23 | `analysis/t14_engine.py` (fork of t11_engine.py; 25 functions copied verbatim and AST-checked); smoke run (1 book, 20 draws) exits 0 on W1 and W2, V4(a) exact (max rel diff 0.0), V2-V6 pass; `logs/{step_2_log,evidence_contract,verifier_spec}.md`; about 10-15 min per window at 2,000 draws |
| 3 Independent verifier | DONE | 1 | Claude (separate agent, never opened the engine) / 2026-11-23 | `analysis/verify_t14.py` (fork of verify_t11/t08); headline: W1 15,351,589 and W2 15,570,927 comparisons, 0 failures; 15 deliberate corruptions each caught by its own check; `logs/step_3_log.md` (F1 ledger has no r3 rows: contract wording fixed; F2 cosmetic invested_weeks on W1 R7 rows) |
| 4 Test scripts | DONE | 1 | Claude (agent) / 2026-11-23 | `analyse.py`, `fill_writeup.py`, `report.py`, `check_page.py`, `rerun_draw.py`, `run.sh`; tested on smoke evidence (check_page 5,116 checks / 0 failures on smoke); `logs/step_4_log.md` (21 readings). Its blocker 18 (W2 crash on SCMO_0007's 409 weeks) was an engine bug, fixed (per-book draw states) |
| 5 Run and gate | DONE | 2, 3, 4 | Claude / 2026-11-23 | headline run both windows, 2,000 draws, 4 books (W1 1,710 s, W2 2,075 s with the machine shared): engine gates V2-V6 pass, V1 passes; `evidence/headline/{w1,w2}` (draws.csv ~285 MB per window in .gitignore). First W2 attempt crashed on SCMO_0007's 409 weeks (engine fixed, folder deleted and re-run; no result had been read) |
| 6 Analyse, report, write-up | DONE | 5 | Claude / 2026-11-23 | `analyse.py` (exit 0, all gates pass) -> `evidence/analysis.log`; `T14.md` §4 generated, §5-§8 written (3 findings, IDs pending); `evidence/report.html` (check_page 13,444 checks, 0 failures); `evidence/METHODS.md`; CLAUDE.md updated |

## Step-level notes

- **Step 0 (2026-11-23).** OUT-SELL week counts in the plan (§3.1) were read from the stored `decisions.csv` of T08 and T11 (switch state and gold signal only, no price or return). Step 1 recomputes them from the signal files.

## Files created or modified

### Step 2
- `AA/analysis/t14_engine.py`, `AA/tests/T14/logs/{step_2_log.md, evidence_contract.md, verifier_spec.md}`, `.gitignore` (draws.csv)

### Step 1
- `AA/tests/T14/{T14.md, check_prereg.py, spell_counts.py, logs/step_1_spell_counts.json}`; `CLAUDE.md` (test-in-progress line)

### Step 0
- `AA/tests/T14/PLAN.md`, `AA/tests/T14/TRACKER.md`
