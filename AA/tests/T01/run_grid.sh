#!/usr/bin/env bash
# T01 -- regenerate every run of the test (AGENT.md section 11.4).
# Each run writes a full evidence set (AA/tests/T01/evidence/<run>/) and its console
# output to AA/tests/T01/grid_<run>.log. Deterministic: static inputs, every null
# offset is run, no seeds. Must exit 0.
#
# Reading the evidence with pandas: realisations.csv has kind == 'null' rows, and
# 'null' is one of read_csv's default NA strings. Read it with
#   pd.read_csv(path, keep_default_na=False, na_values=[""])
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../../.." && pwd)"          # wm-research repo root
cd "$ROOT"

# headline: 50/50 GOLDBEES / LBES sleeve; all 30 configs x 4 books x 2 windows x {0, 20.8} bps; every null draw
python AA/analysis/own_momentum.py --run headline --sleeve gold_cash --out-dir AA/tests/T01/evidence/headline \
    2>&1 | tee AA/tests/T01/grid_headline.log

# cash_sleeve (robustness R4): the same with a 100% LBES sleeve, removing gold's path from the comparison
python AA/analysis/own_momentum.py --run cash_sleeve --sleeve cash --out-dir AA/tests/T01/evidence/cash_sleeve \
    2>&1 | tee AA/tests/T01/grid_cash_sleeve.log
