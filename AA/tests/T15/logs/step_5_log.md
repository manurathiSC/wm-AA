# T15 Step 5 log: run and gate (2026-11-25)

`bash tests/T15/run.sh` (about 2 minutes 11 s; log `logs/step_5_runsh.log`, engine log `logs/step_5_run.log`), all steps exit 0:
data check (70 approved rows, 0 problems); prereg hash OK; engine (both windows, all gates pass); `verify_t15.py` (W1 603,123 and W2 954,208 gate comparisons, 0 failures or missing, every planted corruption detected); `analyse.py --require-v1` (all gates PASS, `evidence/analysis.log`); `fill_writeup.py` (T15.md section 4 filled; sections 1-3 and 5-8 byte-identical); `report.py` (`evidence/report.html`, 1.87 MB); `check_page.py` (14,651 checks, 0 failures); prereg hash OK.

Evidence: `tests/T15/evidence/headline/{w1,w2}/` (22 MB and 36 MB; under the 100 MB limit, committed).
