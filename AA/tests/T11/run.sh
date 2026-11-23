#!/usr/bin/env bash
# Regenerate every T11 artefact from the approved data. Run from AA/:  bash tests/T11/run.sh
# Every step must exit 0; `set -e` stops the script at the first non-zero exit. The headline evidence goes to tests/T11/evidence/headline.
set -euo pipefail
python data/check_approved_data.py     # the data on disk is the data Manu approved; non-zero = stop and ask
python tests/T11/check_prereg.py       # sections 1-3 of T11.md unchanged since the freeze
python analysis/t11_engine.py --run headline
python analysis/verify_t11.py          # writes evidence/headline/verify_t11.json; exits 0 only if rows were compared and none failed
python tests/T11/analyse.py            # reads only evidence/headline (and T06, T08, T09 evidence as a historical reference); writes analysis.log; exits 1 if a gate V1-V6 fails
python tests/T11/fill_writeup.py       # fills section 4 of T11.md between its markers from analysis.log
python tests/T11/check_prereg.py       # fill_writeup.py must not have touched sections 1-3
python tests/T11/plot_parent_vs_partb.py   # evidence/plots/: hold the parent against Part A and Part B at 0, 20.8 and 50 bps (the 0 bps pair goes on the page)
python tests/T11/report.py             # evidence/report.html, plain words, every chart hoverable; reads the best draws' states straight from draw_states.npz
python tests/T11/check_page.py         # re-derives every number on the page from the evidence
python tests/T11/check_prereg.py       # last look: the frozen text is still the frozen text
# one null draw: python tests/T11/rerun_draw.py --book SCMO_0003 --family F1 --id 17 --cost 20.8
#                python tests/T11/rerun_draw.py --book SCMO_0003 --family F3 --id 5 --cost 20.8
#                python tests/T11/rerun_draw.py --book SCMO_0003 --family F1 --id 17 --cost 20.8 --sleeve-mode fixed50
#                python tests/T11/rerun_draw.py --book SCMO_0003 --family F1 --id 3 --window r3
