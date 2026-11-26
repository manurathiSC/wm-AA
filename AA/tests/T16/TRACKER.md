# T16 Progress Tracker

**Overall status: COMPLETE (2026-11-26). Manu's "lets execute T16" approved PLAN_v2; Steps 1-6 DONE; 19 of 24 comparisons pass; findings PROVISIONAL, IDs pending.** Plan: `AA/tests/T16/PLAN_v2.md` (supersedes `PLAN.md`, kept beside it). W2 extended to **2026-11-20** (the latest date every role reaches). The frozen design will be `T16.md` §1-§3 (Step 1).
Status values: `NOT_STARTED` → `IN_PROGRESS` → `DONE` (or `DONE_WITH_NOTES`).
**Data boundary:** read `AA/data/APPROVED_DATA.md`; use only its `APPROVED` rows; run `python data/check_approved_data.py` first (exit 0 on 2026-11-26: 98 approved rows, 0 problems); inputs are T15's `inputs.csv` for W1 and the §3 files of `T16.md` for W2. If anything is stale, missing or unclear, stop and ask Manu.
**What T16 is:** T15's setup with a different OUT-SELL holding (three-index switch OUT **and** MAUc1 SELL): **Nifty 100, Midcap 100, Smallcap 100 and the liquid ETF, 25% each, whatever each index's own SIGN** (`50-all`, `80-all`). Set on entry, drift, no trade until the exit (D3 default). T15's eight rules (`-orig`, `-liq`, `-half`, `-idx` on both bases) are comparators and the regression gate. W1 2014-09-01 → 2019-01-02, W2 2019-01-02 → 2026-11-20, four real parents, 20.8 bps. **No null and no chance check**: descriptive comparisons C1-C6 (vs `-orig` CAGR and drawdown, vs `-liq`, vs `-half`, vs `-idx` CAGR and drawdown), R1-R5.
**Stop rule:** any input stale, PENDING or with a changed sha256 → stop and ask Manu.

| Step | Status | Blocked by | Agent / Date | Output summary |
|---|---|---|---|---|
| 0 Plan written, tracker created | DONE | — | Claude / 2026-11-26 | `PLAN.md` written directly (no plan-mode file to copy); counts taken from T15's `logs/step_1_spell_counts.json` (signals only). Manu 2026-11-26: **D1 = (a)** C1-C6; **D3 = (a)** 25% on entry, drift, trade only on leaving OUT-SELL; D2 answered with a request to define every rule in words (now a standing rule, AGENT.md R10 item 1, glossary in `AA/CLAUDE.md`); **D4: extend W2 to 2026-11-20 — blocked**: stock prices D18 (2026-11-04), cash D11 (2026-11-05) and the D17 calendar (2026-11-06) end earlier; asked Manu whether to refresh them. **Same day:** Manu approved D17/D18/D11 to 2026-11-25; checked (98 approved rows, 0 problems; every calendar session to 11-20 has index and GOLDBEES bars); `PLAN_v2.md` written with W2 to 2026-11-20 (earliest of D03/D25d/D24c) |
| 1 Pre-registration | DONE | — | Claude / 2026-11-26 | `spell_counts.py` -> `logs/step_1_spell_counts.json` (W2 1,946 sessions, 413 decisions, OUT-SELL 49 weeks in 8 spells, k 24/3/22; W1 as T15); `T16.md` §1-§3 frozen, sha256 `eda7321d…`; `AA/CLAUDE.md` test-in-progress line. Plan's 1,947 W2 sessions corrected to 1,946 (the count wins). |
| 2 Engine | DONE | — | Claude / 2026-11-26 | `analysis/t16_engine.py` (fork of t15_engine.py; 27 shared functions byte-identical). Smoke (4 books, both windows, scratch `smoke4`, 35 s): V2-V5 pass; **V4(a): the eight T15 rules reproduce T15's NAVs and trades (W1 0.0; W2 to 2026-10-30, 2.2e-16 / 0.0)**; `-all` entries 25% each to 5e-17, no trade inside a spell. `logs/{step_2_log, evidence_contract, verifier_spec}.md` |
| 3 Independent verifier | DONE_WITH_NOTES | — | separate agent / 2026-11-26 | `analysis/verify_t16.py` (3,087 lines, never opened the engine, imports nothing from analysis/ or data/). On smoke4: W1 737,400 and W2 1,174,789 comparisons, 0 failures; 22 corruptions per window each caught by its own check (also 42 real corrupted folders exit 1); 47 s. **Note:** one reading changed after a first mismatch: R5 on a session with no index bar (3 Budget weekend sessions) uses the carried close times the session-i drag factor, as the engine does; the first reading differed by ~1.5e-5 relative on 8 R5 `-all` rows; disclose in the write-up. `logs/step_3_log.md` |
| 4 Test scripts | DONE | — | separate agent / 2026-11-26 | `analyse.py`, `fill_writeup.py` (§1-§3 byte-identical, tested on copies), `report.py`, `check_page.py`, `run.sh`, `logs/step_4_log.md`. On scratch smoke evidence: gates PASS incl. V1 on the real verifier json; page check 19,903 checks 0 failures; 11 tampered pages each fail. Rules-and-runs table is the page's first table (AGENT.md R10 item 1). Not run end to end (that is Step 5). |
| 5 Run and gate | DONE | — | Claude / 2026-11-26 | `bash tests/T16/run.sh` exit 0 in 2 min 51 s, headline run `evidence/headline/{w1,w2}`: V1 (737,400 W1 / 1,174,789 W2 comparisons, 0 failures, corruptions all detected), V2-V5, step-1 counts, window ends all PASS; `check_page.py` 19,903 checks 0 failures; T16.md §4 filled, §1-§3 hash unchanged. `logs/step_5_run.log`, `logs/step_5_runsh.log` |
| 6 Analyse, report, write-up | DONE | — | Claude / 2026-11-26 | `T16.md` §4 generated, §5-§8 written (F-AA-S?? and F-AA-M?? IDs pending), `evidence/METHODS.md`, `evidence/report.html` (check_page 19,903 checks, 0 failures), `AA/CLAUDE.md` completed-test line. **19 of 24 comparisons pass**; C4 fails W1, passes W2 resting on spells 7-8; C2/C6 fail or tie on W2. |

## Files created or modified

### Step 0
- `AA/tests/T16/PLAN.md`, `AA/tests/T16/TRACKER.md`

### Step 1
- `AA/tests/T16/{T16.md, check_prereg.py, spell_counts.py, logs/step_1_log.md, logs/step_1_spell_counts.json}`; `AA/CLAUDE.md` (test-in-progress line); this tracker.

### Step 2
- `AA/analysis/t16_engine.py`, `AA/tests/T16/logs/{step_2_log.md, evidence_contract.md, verifier_spec.md}`; this tracker.

### Step 3
- `AA/analysis/verify_t16.py`, `AA/tests/T16/logs/step_3_log.md`.

### Step 4
- `AA/tests/T16/{analyse,fill_writeup,report,check_page}.py`, `run.sh`, `logs/step_4_log.md`.

### Step 5
- `AA/tests/T16/evidence/` (headline run, report.html, analysis.log), `logs/step_5_run.log`, `logs/step_5_runsh.log`; `T16.md` §4 generated.

### Step 6
- `AA/tests/T16/T16.md` (§4-§8), `AA/tests/T16/evidence/METHODS.md`, `AA/CLAUDE.md`; this tracker.
