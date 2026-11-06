# Step 5 log: run

**Date:** 2026-11-06. **Command:** `bash tests/T06/run.sh > tests/T06/logs/run_sh.log` (exit 0; the engine took 147 s, the whole script a few minutes more).

Order and results: `check_approved_data.py` (32 approved rows, 0 problems) → `check_prereg.py` (OK, `a3851d40…`) → `t06_engine.py --run headline` (2,000 draws of each null, 4 books, 3 costs, plus LIQUIDCASE and the live window) → `verify_t06.py` (973,395 comparisons, 0 failures, corrupted copy detected) → `analyse.py` (gates all pass) → `fill_writeup.py` (§4 filled, §1–§3 and §5–§8 unchanged) → `report.py` → `check_page.py` (766 checks, 0 failures) → `check_prereg.py` (OK).

Checked by hand afterwards, from the files and not from the summary: `verify_t06.json` (exit_ok true, per-check counts), the gate section of `analysis.log`, and `rerun_draw.py --book SCMO_0003 --type N4.10 --id 17 --cost 20.8` (every difference 0.0, saved states equal).

Headline: C1 against N4.10 4 of 4 (97.4, 94.1, 96.8, 94.6), C2 4 of 4 (97.9, 97.8, 97.2, 98.8); N4.9 re-run beside it 96.9, 92.8, 96.0, 94.8 and 98.2, 96.9, 98.2, 98.4. R1, R2 pass; R3 passes in 4 of 4.

Looked at after the run, because the live-window result differs from T03's (1 of 4): over 2026-08-21 → 2026-10-22 SCMO_0003's parent fell 7.3%, the sleeve 8.0% and the rule 4.3%; the live null medians fell from about 20.6% to 13.2% CAGR and the rule's from 28.2% to 26.0%. So the live pass turns on one exit. Recorded in T06.md §5 and §6, not in any criterion.

The Step 2 smoke evidence folder (`evidence/smoke`) was deleted after the headline run.
