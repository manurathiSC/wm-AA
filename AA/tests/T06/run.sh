#!/usr/bin/env bash
# Regenerate every T06 artefact from the approved data. Run from AA/:  bash tests/T06/run.sh
set -euo pipefail
python data/check_approved_data.py     # the data on disk is the data Manu approved; non-zero = stop and ask
python tests/T06/check_prereg.py
python analysis/t06_engine.py --run headline
python analysis/verify_t06.py
python tests/T06/analyse.py
python tests/T06/fill_writeup.py
python tests/T06/report.py             # reads the best draw's states straight from draw_states.npz
python tests/T06/check_page.py
python tests/T06/check_prereg.py
# one null draw: python tests/T06/rerun_draw.py --book SCMO_0003 --type N4.10 --id 17 --cost 20.8
