#!/usr/bin/env bash
# Regenerate every T14 artefact from the approved data. Run from AA/:  bash tests/T14/run.sh
# Every step must exit 0; `set -e` stops the script at the first non-zero exit. The headline evidence goes to tests/T14/evidence/headline/{w1,w2}.
# The two windows run side by side (4 worker processes each, one per book); each window needs about 10-15 minutes at 2,000 draws.
# A rerun is a NEW run directory: edit RUN below (never overwrite a run that was read).
set -euo pipefail
RUN="${RUN:-headline}"

python data/check_approved_data.py          # the data on disk is the data Manu approved; non-zero = stop and ask
python tests/T14/check_prereg.py            # sections 1-3 of T14.md unchanged since the freeze (first look)

python analysis/t14_engine.py --window w1 --run "$RUN" --workers 4 > tests/T14/logs/step_5_run_w1.log 2>&1 &
PID1=$!
python analysis/t14_engine.py --window w2 --run "$RUN" --workers 4 > tests/T14/logs/step_5_run_w2.log 2>&1 &
PID2=$!
wait "$PID1"                                # `set -e`: a failed window stops the script here
wait "$PID2"

python analysis/verify_t14.py --run "$RUN"  # writes evidence/$RUN/{w1,w2}/verify_t14.json; exits 0 only if rows were compared, none failed, and every planted corruption was caught
python tests/T14/analyse.py --run "$RUN" --require-v1   # reads only evidence/$RUN (and T11's / T08's stored statistics for the -orig reference); prints every table and writes evidence/analysis.log; exits 1 if a gate fails (then prints no result)
python tests/T14/fill_writeup.py            # fills section 4 of T14.md between its markers from evidence/analysis.log; refuses unless sections 1-3 stay byte-identical
python tests/T14/check_prereg.py            # fill_writeup.py must not have touched sections 1-3
python tests/T14/report.py --run "$RUN"     # evidence/report.html: the answer first, every number with its provenance, every chart hoverable
python tests/T14/check_page.py --run "$RUN" # re-derives every number and every date on the page from the evidence; exits 1 on any failure
python tests/T14/check_prereg.py            # last look: the frozen text is still the frozen text

# one null draw, all six rules, rebuilt from its id and compared with draws.csv, draw_states.npz and draw_curves_20.8.npz:
#   python tests/T14/rerun_draw.py --win w1 --book SCMO_0003 --family F1 --id 17
#   python tests/T14/rerun_draw.py --win w2 --book SCMO_0003 --family F3 --id 5
#   python tests/T14/rerun_draw.py --win w2 --book SCMO_0007 --family F5 --id 5
#   python tests/T14/rerun_draw.py --win w1 --book SCMO_0003 --family F1 --id 3 --span r3
#   python tests/T14/rerun_draw.py --win w1 --book SCMO_0003 --family F1 --id 3 --cash liq
