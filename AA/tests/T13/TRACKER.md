# T13 Progress Tracker

**Overall status: IN PROGRESS (2026-11-18).** Plan: `AA/tests/T13/PLAN.md` (written 2026-11-18 on Manu's go-ahead in chat, 5,956 bytes; the frozen design is `T13.md` §1–§3 and wins where they differ). Read this file before starting any step; update it when you finish.
Status values: `NOT_STARTED` → `IN_PROGRESS` → `DONE` (or `DONE_WITH_NOTES`).
**Data boundary:** read `AA/data/APPROVED_DATA.md`; use only its `APPROVED` rows; run `python data/check_approved_data.py` first; if anything is stale, missing or unclear, stop and ask Manu.
**What T13 is:** T11 with one change: the book holds the parent when **at least two** of the three index SIGNs (Nifty 100, Midcap 100, Smallcap 100) are BUY (T11: all three). Same four real parents, window 2014-09-01 → 2019-01-02, Part A (50/50 sleeve) and Part B (MAUc1-timed sleeve), nulls F1–F5, six criteria A1–C4, gates V1–V6, R1–R7. T11's all-3 rule runs beside it as a descriptive comparator. Seeds start with **16**.
**Stop rule:** fewer than 4 in-or-out round trips → NOT REPORTABLE (Step 1 found 9).

| Step | Status | Blocked by | Agent / Date | Output summary |
|---|---|---|---|---|
| 0 Plan written, tracker created | DONE | — | Claude / 2026-11-18 | `PLAN.md` written directly (no plan-mode file exists to copy), this file created |
| 1 Pre-registration | DONE | 0 | Claude / 2026-11-18 | `spell_counts.py` (fork of T11's, `IN_MIN_BUY = 2`) → `logs/step_1_spell_counts.json`: `check_approved_data.py` exit 0 (67 approved rows); 228 decisions, first IN, last OUT; in 9 spells (S 115, bounds [2, 30]), out 9 spells (S 113, bounds [2, 33]), **9 round trips**; weeks by number of BUY 0/1/2/3 = 78/35/22/93; 22 weeks IN under 2-of-3 and OUT under all-3, 0 the reverse; all-3 recount equals T11 Step 1; gold = T11's series, 8 sleeve trades, 2 flips on exits, 8 while IN, 15 of 19 gold spells touch OUT; R3 (2015-01-02): 210 decisions, 7 round trips. **`T13.md` §1–§3 frozen, sha256 `ab1d6f4747e6…`** (`python tests/T13/check_prereg.py`). |
| 2 Engine | DONE | 1 | Claude / 2026-11-18 | `analysis/t13_engine.py` (fork of `t11_engine.py`; changes in `logs/step_2_log.md`). Smoke `--run smoke --draws 20 --quick` exit 0 (12 s): V2–V6, Step 1 counts, frozen counts all true; **V4(a1): the all-3 comparator equals T11's stored NAVs and decisions exactly (0.0)**; V4(a2) T08/T06 2.2e-16; V4(c) only the 5 intended functions changed + `t11_regression` new. A 4-book 100-draw scratch run (scratchpad) exits 0. Contract deltas `logs/evidence_contract.md` |
| 3 Independent verifier | DONE_WITH_NOTES | 1 | helper agent / 2026-11-18 | `analysis/verify_t13.py` (fork of `verify_t11.py`; never opened either engine). `--run smoke --draws 20` exit 0: 127,690 comparisons, 0 failures, 12 of 12 corruptions detected (T11's 9 + `n_buy`, `state_all3`, a `strategy_all3` NAV row); 4-book 100-draw scratch exit 0: 562,752 comparisons. Worst: NAVs 2.2e-14, draws 5.0e-13, V4(a1) against T11's stored NAVs 9.2e-16 (own re-derivation), V4(a2) T08 1.9e-15 / T06 1.8e-15. Readings (decisions check split in three; R3 n_buy counts from the step-1 json only; V4(c) from the engine's record) in `logs/step_3_log.md`, spec `logs/verifier_spec.md` |
| 4 Test scripts | DONE_WITH_NOTES | 1 | helper agent / 2026-11-18 | `analyse.py`, `fill_writeup.py`, `report.py`, `check_page.py`, `rerun_draw.py`, `plot_parent_vs_partb.py`, `run.sh` (forks of T11's). Tested on copies only: 4-book scratch with the real `verify_t13.json`: analyse V1–V6 PASS, check_page 2,464 checks 0 failures (2,442 with references absent); smoke 1,052 checks 0 failures; fill_writeup 12/12 tests on copies; rerun_draw 9/9 EQUAL; 32 planted corruptions, 32 caught. Adds the all-3 comparator (4.2 and the page) and T11 as the main reference (R4, outcome map). Readings in `logs/step_4_log.md`; browser hover check of the new charts not done |
| 5 Run and gate | DONE | 2, 3, 4 | Claude / 2026-11-18 | `bash tests/T13/run.sh` exit 0 (`logs/step_5_run.log`; engine 317 s). Gates V1–V6 PASS (V1: 3,861,152 comparisons, 0 failures, 12/12 corruptions detected; V4(a1) all-3 = T11 exactly); `check_page.py` 2,464 checks, 0 failures; `check_prereg.py` OK before and after |
| 6 Analyse, report, write-up | DONE | 5 | Claude / 2026-11-18 | **All six criteria FAIL, 0 of 4 books each** (CAGR percentiles against F1: A1 11.7, 16.9, 5.9, 19.6; C1 13.9, 19.9, 7.6, 23.1; C3 42.0). Against T11's all-3 rule (descriptive): timed −1.20, +2.08, −3.52, −2.68 pp CAGR, worst fall deeper in 3 of 4 books. `T13.md` §4 (fill_writeup) and §5–§8, `evidence/METHODS.md`, `evidence/report.html` (rebuilt after §5–§8; check_page 2,464 / 0); finding ID pending; `AA/CLAUDE.md` updated |

## Step-level notes

- **Step 1 (2026-11-18).** No deviation from `PLAN.md`. Nothing in §1–§3 may change now; a correction goes in an Amendments block after §4, never in the frozen text.

## Files created or modified

### Steps 2–6
- `AA/analysis/t13_engine.py`, `AA/analysis/verify_t13.py` (help text of `--run` corrected to T13 after Step 3), `AA/tests/T13/{analyse,fill_writeup,report,check_page,rerun_draw,plot_parent_vs_partb}.py`, `run.sh`, `logs/{evidence_contract,step_2_log,verifier_spec,step_3_log,step_4_log,step_5_run}.md/.log`, `evidence/{smoke,headline,plots}/`, `evidence/report.html`, `evidence/METHODS.md`, `analysis.log`, `T13.md` (§4 generated, §5–§8, header status), `AA/CLAUDE.md`

### Step 1
- `AA/tests/T13/T13.md` (§1–§3 frozen; §4–§8 stubs), `check_prereg.py`, `spell_counts.py`, `logs/step_1_spell_counts.json`, `TRACKER.md`

### Step 0
- `AA/tests/T13/PLAN.md`, `AA/tests/T13/TRACKER.md`
