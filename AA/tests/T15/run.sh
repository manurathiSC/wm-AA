#!/usr/bin/env bash
# Regenerate every T15 artefact from the approved data. Run from AA/:  bash tests/T15/run.sh
# Every step must exit 0; `set -e` stops the script at the first non-zero exit. The headline evidence goes to tests/T15/evidence/headline/{w1,w2}.
# The engine takes under a minute for both windows (no draws); the verifier a few minutes.
# A rerun is a NEW run directory: edit RUN below (never overwrite a run that was read).
set -euo pipefail
RUN="${RUN:-headline}"

python data/check_approved_data.py          # the data on disk is the data Manu approved; non-zero = stop and ask
python tests/T15/check_prereg.py            # sections 1-3 of T15.md unchanged since the freeze (first look)

python analysis/t15_engine.py --window both --run "$RUN" --workers 4 > tests/T15/logs/step_5_run.log 2>&1

python analysis/verify_t15.py --run "$RUN"  # writes evidence/$RUN/{w1,w2}/verify_t15.json; exits 0 only if rows were compared, none failed, and every planted corruption was caught
python tests/T15/analyse.py --run "$RUN" --require-v1   # reads only evidence/$RUN; prints every table and writes evidence/analysis.log; exits 1 if a gate fails (then prints no result)
python tests/T15/fill_writeup.py            # fills section 4 of T15.md between its markers from evidence/analysis.log; refuses unless sections 1-3 stay byte-identical
python tests/T15/check_prereg.py            # fill_writeup.py must not have touched sections 1-3
python tests/T15/report.py --run "$RUN"     # evidence/report.html: the answer first, every number with its provenance, every chart hoverable
python tests/T15/check_page.py --run "$RUN" # re-derives every number and every date on the page from the evidence; exits 1 on any failure
python tests/T15/check_prereg.py            # last look: the frozen text is still the frozen text
