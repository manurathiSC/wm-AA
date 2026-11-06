# T05 Progress Tracker

**Overall status: COMPLETE (2026-11-06).** V1–V5 pass; no indicator passes C1 or C2, R5 fails (10.3); F-AA-S06 NOT ESTABLISHED, F-AA-M05 OBSERVED. Plan: `PLAN.md` (this folder). Read this file before starting any step; update it when you finish.
Status values: `NOT_STARTED` → `IN_PROGRESS` → `DONE` (or `DONE_WITH_NOTES`).

| Step | Status | Blocked by | Agent / Date | Output summary |
|---|---|---|---|---|
| 1 | DONE | — | Claude / 2026-11-06 | Pre-registration frozen, sha256=90dc7c4dff77 (full 90dc7c4dff77ee2f8bad2147e3032075e46cd1275f3b34cf1a0c3ddb7f66ba72) |
| 2 | DONE_WITH_NOTES | 1 | subagent / 2026-11-06 | Engine written. G-engine: +0.045 pp/yr (worst year 2022 +0.43). Reviews in SELL: 56 full (55 traded), 38 live. Smoke test OK; V3/V5 pass; strategy trades 78-89 (T04: 110-208) |
| 3 | DONE_WITH_NOTES | 1 | subagent / 2026-11-06 | Verifier written (independent; never read an engine). Checks: C-dec, C-review, C-ind, C-pit, C-sel-nonreview, C-frozen, C-nreviews, C-nav0, C-cost, C-trades(+plausible), C-null, C-null-k, C-comp, C-always-in, C-corrupt. On smoke evidence: rows compared, 0 failures, exit 0; corrupted copy exits 1 |
| 4 | DONE_WITH_NOTES | 1 | subagent / 2026-11-06 | Test scripts written: analyse.py, fill_writeup.py, report.py, run.sh. Tested on smoke evidence + scratch copies only (analyse exits 0, report page 0.42 MB, fill_writeup keeps §1-§3 byte-identical); needs real verify_t05.json |
| 5 | DONE | 2, 3, 4 | Claude / 2026-11-06 | Pipeline OK (`run.sh` exit 0, engine 76 s). V1-V5 PASS (V1: 683,010 comparisons, 0 failures; V4 +0.045 pp/yr). Reviews in SELL: 56 (55 traded). Headline at 20.8 bps C1 percentile: I1=28.0, I2=65.0, I3=5.1, I4=67.8, I5=29.8; C2: 18.7, 62.7, 11.3, 42.5, 58.9. R5 best-of-sweep: 10.3 (FAIL) |
| 6 | DONE | 5 | Claude / 2026-11-06 | T05 COMPLETE. Verdict: H1ᵢ and H2ᵢ falsified for all five indicators (C1, C2 fail; R5 10.3). Findings: F-AA-S06 (NOT ESTABLISHED), F-AA-M05 (OBSERVED). `AA/CLAUDE.md` updated (next free S07, M06, D16); `check_prereg.py` OK |

## Step-level notes
(Agents append notes here when completing a step.)

- **Step 1 (2026-11-06):** `PLAN.md` §2 lists R1-R5 as (0 bps, 50 bps, max DD, Ulcer, best-of-sweep), but its Rule 9 says "same R1-R5 robustness" and the engine fork keeps T04's variants. T05.md §2 uses T04's R1-R5 (R1 100% GOLDBEES, R2 cost, R3 LIQUIDCASE, R4 live window, R5 best-of-sweep); max DD (C2) and Ulcer are already reported as C2 and a secondary statistic. Added to §2 (declared before any run): a status rule that a C1 pass counts as selection only if its 0 bps percentile is also ≥ 98 (F-AA-M03). Added to §3: the stored pass set P(j) = pass set at r(j), r(j) = latest flagged decision ≤ j; live window R4 is its own book with its own review flags.
- Review-flag semantics fixed in T05.md §3 step 5a: the flag is computed for every decision (month-end by the decision's own date, plus first SELL of a spell) and takes effect only in SELL; `n_reviews` counts flagged SELL decisions; the last decision (2026-11-04) is flagged but not traded.

- **Step 2 notes (2026-11-06):** the engine keeps T04's real evidence file format (long `selections.csv` with a `kept` string, `trade_date`), not PLAN.md's table; new columns `review` (decisions), `review_j`/`is_review`/`review_nontrivial` (selections), `n_reviews` and `n_reviews_traded` (stats). `n_reviews` includes the untraded last decision (T05.md 5a). ⚠ AFFECTS STEP 3 and 4: read the smoke files for the schema (both agents were told).

## Files created or modified
(Agents append here after completing a step. One section per step, with full paths.)

### Step 1
- `C:\Users\manur\Repos\wm-AA\AA\tests\T05\T05.md` (§1-§3 frozen)
- `C:\Users\manur\Repos\wm-AA\AA\tests\T05\check_prereg.py`
- `C:\Users\manur\Repos\wm-AA\AA\tests\T05\TRACKER.md`
- `C:\Users\manur\Repos\wm-AA\AA\tests\T05\logs\` (dir)
- `C:\Users\manur\Repos\wm-AA\AA\tests\T05\logs\step_1_log.md`

### Step 2
- `C:\Users\manur\Repos\wm-AA\AA\analysis\t05_engine.py`
- `C:\Users\manur\Repos\wm-AA\AA\tests\T05\logs\step_2_log.md`
- `C:\Users\manur\Repos\wm-AA\AA\tests\T05\evidence\smoke\` (smoke evidence, 20 draws)

### Step 3
- `C:\Users\manur\Repos\wm-AA\AA\analysis\verify_t05.py`
- `C:\Users\manur\Repos\wm-AA\AA\tests\T05\logs\verifier_spec.md`
- `C:\Users\manur\Repos\wm-AA\AA\tests\T05\logs\step_3_log.md`

### Step 4
- `C:\Users\manur\Repos\wm-AA\AA\tests\T05\analyse.py`
- `C:\Users\manur\Repos\wm-AA\AA\tests\T05\fill_writeup.py`
- `C:\Users\manur\Repos\wm-AA\AA\tests\T05\report.py`
- `C:\Users\manur\Repos\wm-AA\AA\tests\T05\run.sh`
- `C:\Users\manur\Repos\wm-AA\AA\tests\T05\logs\step_4_log.md`

### Step 5
- `C:\Users\manur\Repos\wm-AA\AA\tests\T05\evidence\headline\` (all evidence files, `verify_t05.json`, `analysis_summary.json`, `report.html`)
- `C:\Users\manur\Repos\wm-AA\AA\tests\T05\analysis.log`
- `C:\Users\manur\Repos\wm-AA\AA\tests\T05\logs\run_sh.log`
- `C:\Users\manur\Repos\wm-AA\AA\tests\T05\T05.md` (§4 generated)

### Step 6
- `C:\Users\manur\Repos\wm-AA\AA\tests\T05\T05.md` (§5-§8 and header status; §1-§3 byte-identical, hash unchanged)
- `C:\Users\manur\Repos\wm-AA\AA\CLAUDE.md` (current test, finding counter)
