#!/usr/bin/env bash
# Regenerate every T05 artefact from the raw files. Run from AA/:  bash tests/T05/run.sh
set -euo pipefail
python tests/T05/check_prereg.py
python analysis/t05_engine.py --run headline --workers 12
python analysis/verify_t05.py
python tests/T05/analyse.py
python tests/T05/fill_writeup.py
python tests/T05/report.py
python tests/T05/check_prereg.py
