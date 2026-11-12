#!/usr/bin/env bash
# Regenerate every T07 artefact from the approved data. Run from AA/:  bash tests/T07/run.sh
set -euo pipefail
python data/check_approved_data.py     # the data on disk is the data Manu approved; non-zero = stop and ask
python tests/T07/check_prereg.py
python analysis/t07_engine.py --run headline
python analysis/verify_t07.py
python tests/T07/analyse.py            # exits non-zero if a validity gate (V1-V7) failed: nothing below may then be read
python tests/T07/fill_writeup.py
python tests/T07/episodes.py          # post hoc: where and why the whole-book switch beats the rule (evidence/episodes/, section 'whywhole' of the page)
python tests/T07/report.py
python tests/T07/check_page.py
python tests/T07/check_prereg.py
# one null draw: python tests/T07/rerun_draw.py --book SCMO_0003 --type N4.6 --id 17 --cost 20.8
