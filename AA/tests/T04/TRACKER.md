# T04 Progress Tracker

**Overall status: COMPLETE (2026-11-06).** V1–V5 pass; C1 passes for I4 only (98.3), C2 for none, R5 fails; F-AA-S05 NOT ESTABLISHED. Plan: `C:\Users\manur\.claude\plans\c-users-manur-repos-wm-aa-aa-data-holdin-drifting-rivest.md`. Read this file before starting any step; update it when you finish.
Status values: `NOT_STARTED` → `IN_PROGRESS` → `DONE` (or `DONE_WITH_NOTES`).

| Step | Status | Agent / Date | Output summary |
|---|---|---|---|
| 1 Pre-registration | DONE | Claude / 2026-11-06 | `T04.md` §1–§3 written and frozen, sha256 `47e48a83…` (`python tests/T04/check_prereg.py` verifies) |
| 2 Engine | DONE | Claude / 2026-11-06 | `analysis/t04_engine.py`, standalone. Cross-checks against T03 (not gates): regime series equals T03's on 400 shared dates; the full-switch comparator reproduces T03's SCMO_0003 NAV to 3e-15 up to 2026-08-07 |
| 3 Independent check | DONE_WITH_NOTES | subagent + main / 2026-11-06 | `analysis/verify_t04.py`, written from `logs/verifier_spec.md` and T04.md §3 without reading the engine. First run disagreed on I5 (1,965 of 4,084) because the spec paraphrased an ordered elif chain ambiguously; engine I5 = the desk port on 4,084/4,084 stock-dates (123 stocks); spec clarified, verifier default set to the ordered reading (F-AA-M04). Then 577,117 comparisons, 0 failures, corrupted copy detected |
| 4 Run and gate | DONE_WITH_NOTES | Claude / 2026-11-06 | `evidence/headline/`: 2,000 draws × 5 indicators × 6 variants in 110 s. V2, V3, V4 (+0.045 pp/yr, worst year 2022 +0.43), V5 (50/50 pairs) pass; V1 PASS (step 3) |
| 5 Analyse, report | DONE | Claude / 2026-11-06 | `analyse.py` → `analysis.log`; `report.py` → `evidence/headline/report.html` (hover checked in Edge: 5 chart types, 0 console errors) |
| 6 Write-up | DONE | Claude / 2026-11-06 | §4 generated, §5–§8 written: F-AA-S05, M03, M04. `bash tests/T04/run.sh` exits 0 (5 min) |

## Notes

- **Readings the text left to the engine** are listed in `audit.json["readings"]` (E1–E11) and in `T04.md` §3 where they were fixed before the run.
- **Data extended 2026-11-06 (F-AA-D13 manner):** GOLDBEES to 2026-11-04, LBES to 2026-11-05, Master to 2026-10-30, D18 OHLC to 2026-11-04. The MCX de-spike file ends 2026-09-28, so five trade sessions after it use raw GOLDBEES OHLC4 (−0.22% to +0.54% from close; `audit.json`).
- **SCMO_0042 published NAV** is not in D17; the descriptive comparator reads `Historical Data/indices.csv` (2021-11-01 → 2026-08-21).
- **Plan deviation, disclosed:** the plan's "shared permutation seed" for R5 is read as "the same draw id" (T04.md §3 step 14).
