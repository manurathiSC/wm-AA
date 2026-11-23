#!/usr/bin/env bash
# Regenerate every T10 artefact from the approved data. Run from AA/:   bash tests/T10/run.sh [RUN]      (RUN defaults to "headline")
# Every step must exit 0; the script stops at the first one that does not (set -e). The log is tests/T10/logs/run_sh.log.
# Environment (for tests of this script on a scratch run only; the headline uses the defaults):
#   R4=500            R4 tag-error draws per book (the pre-registration requires 500; analyse.py fails on any other number unless --expect-r4 is given the same)
#   T10_DOC=...       the write-up that fill_writeup.py fills (default tests/T10/T10.md)
#   T10_ALLOW_NO_VERIFIER=1   only to test this script before analysis/verify_t10.py exists: the verifier step is then skipped and said so;
#                             analyse.py still fails V1 unless a verify_t10.json is in the run directory, so a real run can never pass without the verifier
set -euo pipefail
RUN="${1:-headline}"
R4="${R4:-500}"
DOC="${T10_DOC:-tests/T10/T10.md}"
mkdir -p tests/T10/logs
exec > >(tee tests/T10/logs/run_sh.log) 2>&1
echo "T10 run.sh: run=$RUN r4=$R4 doc=$DOC $(date -u +%Y-%m-%dT%H:%M:%SZ)"
python -I data/check_approved_data.py                       # the data on disk is the data Manu approved; non-zero = stop and ask
python -I tests/T10/check_prereg.py                         # sections 1-3 unchanged since the freeze
python -I analysis/t10_engine.py --run "$RUN" --r4 "$R4"    # the engine (gates V2-V5 are re-derived by analyse.py; the engine exits non-zero if one of its own failed)
if [ -f analysis/verify_t10.py ]; then
  python -I analysis/verify_t10.py --run "$RUN"             # V1: the independent check; non-zero = stop
elif [ "${T10_ALLOW_NO_VERIFIER:-0}" = "1" ]; then
  echo "WARNING: analysis/verify_t10.py does not exist: the verifier step is SKIPPED (T10_ALLOW_NO_VERIFIER=1); V1 will fail in analyse.py unless a verify_t10.json is in the run directory"
else
  echo "analysis/verify_t10.py does not exist: stop"; exit 1
fi
python -I tests/T10/analyse.py --run "$RUN" --expect-r4 "$R4"   # exits non-zero if a validity gate (V1-V5) or a consistency check failed: nothing below may then be read
python -I tests/T10/fill_writeup.py --run "$RUN" --doc "$DOC"   # section 4 of the write-up; sections 1-3 proved byte-identical
python -I tests/T10/check_prereg.py
python -I tests/T10/report.py --run "$RUN"                  # evidence/$RUN/report.html
python -I tests/T10/check_page.py --run "$RUN"              # every number and date on the page against the evidence; non-zero = the page may not be used
python -I tests/T10/rerun_draw.py --book SCMO_0003 --id 17 --run "$RUN"   # one R4 draw rebuilt by the engine from its seed and compared with the evidence
echo "T10 run.sh: all steps exited 0"
