#!/usr/bin/env bash
# Regenerate every T08 artefact from the approved data. Run from AA/:  bash tests/T08/run.sh
set -euo pipefail
python data/check_approved_data.py     # the data on disk is the data Manu approved; non-zero = stop and ask
python tests/T08/check_prereg.py
python analysis/t08_engine.py --run headline
python analysis/verify_t08.py
python tests/T08/r7_raw_fill.py        # R7: the rule with the close in place of the raw OHLC4 after 2026-09-28 (writes evidence/headline/r7_raw_fill.csv)
python tests/T08/analyse.py
python tests/T08/fill_writeup.py
python tests/T08/report.py             # reads the best draws' states straight from draw_states.npz
python tests/T08/check_page.py
python tests/T08/check_prereg.py
# one null draw: python tests/T08/rerun_draw.py --book SCMO_0003 --family F1 --id 17 --cost 20.8
#                python tests/T08/rerun_draw.py --book SCMO_0003 --family F3 --id 5 --cost 20.8
