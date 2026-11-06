#!/usr/bin/env bash
# Regenerate every T04 artefact from the raw files. Run from AA/:  bash tests/T04/run.sh
# Each step must exit 0. The independent verifier (verify_t04.py) runs after the engine and before analyse.py.
set -euo pipefail
python tests/T04/check_prereg.py                        # sections 1-3 are unchanged since the freeze
python analysis/t04_engine.py --run headline --workers 12   # strategy, comparators, nulls, V2-V5 -> tests/T04/evidence/headline/
python analysis/verify_t04.py                           # V1: independent re-derivation; exits non-zero on any failure
python tests/T04/analyse.py                             # prints and writes analysis.log; exits non-zero if a gate failed
python tests/T04/fill_writeup.py                        # copies analysis.log into T04.md section 4 (sections 1-3 untouched)
python tests/T04/report.py                              # evidence/headline/report.html
python tests/T04/check_prereg.py                        # and sections 1-3 are still unchanged
