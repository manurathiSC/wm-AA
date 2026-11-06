#!/usr/bin/env bash
# Regenerate every T03 artefact from the raw files. Run from AA/:  bash tests/T03/run.sh
# Each step must exit 0. The independent verifier (verify_t03.py) runs after the engine and before analyse.py.
set -euo pipefail
python tests/T03/check_prereg.py                       # sections 1-3 are unchanged since the freeze
python data/parent_rebuild_hm.py >/dev/null            # Step 1 rebuild (V5 compares g0_gate.csv before and after)
python analysis/t03_engine.py --run headline           # strategy, comparators, nulls, V2-V4 -> tests/T03/evidence/headline/
python analysis/verify_t03.py                          # V1: independent re-derivation; exits non-zero on any failure
python tests/T03/check_regression.py                   # V5
python tests/T03/analyse.py                            # prints and writes analysis.log; exits non-zero if a gate failed
python tests/T03/fill_writeup.py                       # copies analysis.log into T03.md section 4
python tests/T03/best_draw.py                          # weekly states of the highest-CAGR random timing (for the page's regime chart); exits non-zero if the rebuild differs
python tests/T03/report.py                             # evidence/report.html
python tests/T03/check_page.py                         # every number on the page, recomputed
python tests/T03/check_prereg.py                       # and sections 1-3 are still unchanged
# one null draw: python tests/T03/rerun_draw.py --book SCMO_0003 --type N4.9 --id 17 --cost 20.8
