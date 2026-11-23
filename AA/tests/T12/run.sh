#!/usr/bin/env bash
# Regenerate every T12 artefact from the approved data. Run from AA/:  R6_IDS=<review|frozen> bash tests/T12/run.sh
# Fork of tests/T07/run.sh. Every step must exit 0; set -e stops at the first that does not.
#
# R6_IDS: which quote_ids R6 reads the two unranked holdings by. T12.md section 2 names 236783369047 / 236798428431, which are today's listings and never
# rank in 2014-19 ("frozen": R6 then re-tags nothing); the D20b review's old listings 55837401060 / 55837400085 rank Mid in the window ("review").
# The engine's default is frozen, the verifier's is review, so the same choice must reach both. It is Manu's decision (T12 Step 2 log, contract change 1);
# this script refuses to run until it is made.
set -euo pipefail
R6_IDS="${R6_IDS:?set R6_IDS=review or R6_IDS=frozen (the decision on the R6 quote_ids is for Manu; see tests/T12/logs/step_2_log.md, contract change 1)}"
case "$R6_IDS" in review|frozen) ;; *) echo "R6_IDS must be review or frozen" >&2; exit 2 ;; esac
python -I data/check_approved_data.py          # the data on disk is the data Manu approved; non-zero = stop and ask
python -I tests/T12/check_prereg.py            # sections 1-3 unchanged since the freeze
python -I analysis/t12_engine.py --run headline --r6-ids "$R6_IDS"
python -I analysis/verify_t12.py --evidence tests/T12/evidence/headline --r6-ids "$R6_IDS"   # writes evidence/headline/verify_t12.json (gate V1)
python -I tests/T12/analyse.py                 # exits non-zero if a validity gate (V1-V7) failed: nothing below may then be read
python -I tests/T12/fill_writeup.py            # section 4 of T12.md from analysis.log; sections 1-3 provably unchanged
python -I tests/T12/episodes.py                # post hoc: where the rule and the whole-book switch part ways (evidence/episodes/, section 'whywhole' of the page)
python -I tests/T12/report.py                  # evidence/report.html
python -I tests/T12/check_page.py              # the page against the evidence and the raw files
python -I tests/T12/check_prereg.py            # sections 1-3 still unchanged after fill_writeup.py
# one null draw: python -I tests/T12/rerun_draw.py --book SCMO_0003 --type N4.6 --id 17 --cost 20.8 [--window full|r2|full_r6]
#   add --r6-ids "$R6_IDS" for a full_r6 draw (forwarded to the engine's --rerun)
