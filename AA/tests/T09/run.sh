#!/usr/bin/env bash
# Regenerate every T09 artefact from the approved data. Run from AA/:  bash tests/T09/run.sh
# Every step must exit 0; `set -e` stops the script at the first non-zero exit.
set -euo pipefail
python data/check_approved_data.py     # the data on disk is the data Manu approved; non-zero = stop and ask
python tests/T09/check_prereg.py       # sections 1-3 of T09.md unchanged since the freeze
python analysis/t09_engine.py --run headline
python analysis/verify_t09.py
python tests/T09/analyse.py
python tests/T09/fill_writeup.py
python tests/T09/check_prereg.py       # fill_writeup.py must not have touched sections 1-3
python tests/T09/report.py             # reads the best draws' states straight from draw_states.npz
python tests/T09/check_page.py
# one null draw: python tests/T09/rerun_draw.py --book SCMO_0003 --family F1 --id 17 --cost 20.8
#                python tests/T09/rerun_draw.py --book SCMO_0003 --family F3 --id 5 --cost 20.8
#                python tests/T09/rerun_draw.py --book SCMO_0003 --family F1 --id 17 --cost 20.8 --sleeve-mode fixed50
