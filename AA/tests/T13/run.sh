#!/usr/bin/env bash
# Regenerate every T13 artefact from the approved data. Run from AA/:  bash tests/T13/run.sh
# Every step must exit 0; `set -e` stops the script at the first non-zero exit. The headline evidence goes to tests/T13/evidence/headline.
set -euo pipefail
python data/check_approved_data.py     # the data on disk is the data Manu approved; non-zero = stop and ask
python tests/T13/check_prereg.py       # sections 1-3 of T13.md unchanged since the freeze
python analysis/t13_engine.py --run headline
python analysis/verify_t13.py          # writes evidence/headline/verify_t13.json; exits 0 only if rows were compared and none failed
python tests/T13/analyse.py            # reads only evidence/headline (and T11's, T06's, T08's and T09's stored evidence as a reference); writes analysis.log; exits 1 if a gate V1-V6 fails
python tests/T13/fill_writeup.py       # fills section 4 of T13.md between its markers from analysis.log
python tests/T13/check_prereg.py       # fill_writeup.py must not have touched sections 1-3
python tests/T13/plot_parent_vs_partb.py   # evidence/plots/: hold the parent against Part A and Part B at 0, 20.8 and 50 bps (the 0 bps pair goes on the page)
python tests/T13/report.py             # evidence/report.html, plain words, every chart hoverable; reads the best draws' states straight from draw_states.npz
python tests/T13/check_page.py         # re-derives every number on the page from the evidence
python tests/T13/check_prereg.py       # last look: the frozen text is still the frozen text
# one null draw: python tests/T13/rerun_draw.py --book SCMO_0003 --family F1 --id 11 --cost 20.8
#                python tests/T13/rerun_draw.py --book SCMO_0003 --family F3 --id 7 --cost 20.8
#                python tests/T13/rerun_draw.py --book SCMO_0003 --family F1 --id 11 --cost 20.8 --sleeve-mode fixed50
#                python tests/T13/rerun_draw.py --book SCMO_0003 --family F1 --id 3 --window r3
