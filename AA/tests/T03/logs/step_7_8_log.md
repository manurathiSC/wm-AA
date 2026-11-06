# T03 Steps 7 and 8 log: analysis, page and check (2026-11-05)

## Step 7: analyse and gate

`tests/T03/analyse.py` reads only `evidence/headline/`; its output is `tests/T03/analysis.log`; `fill_writeup.py` copies it verbatim into T03.md section 4. Gates: V1 PASS (119,999 comparisons), V2 PASS (0 of 3,194), V3 PASS (40,000 draws), V4 PASS (G0 on all four; max difference vs the Step 1 rebuild 2.7e-11), V5 PASS.

**H1 (timing): PASS (C1)**, CAGR percentiles 96.0, 86.4, 95.0, 92.4 (3 of 4 at 90; p 0.041, 0.137, 0.050, 0.076). **H2 (protection): PASS (C2)**, drawdown percentiles 97.5, 94.7, 97.5, 97.6 (4 of 4). R1 (shift null) PASS, R2 (0 and 50 bps) PASS, R3 (LIQUIDCASE) PASS, **R4 (live decisions only) FAIL, 1 of 4** (85.7, 80.1, 92.0, 84.9).

Findings: F-AA-S04 (PROVISIONAL) and F-AA-M02 (FIXED) in T03.md section 5.

Notes: the first analyse.py run printed numbers before V1 and V5 had run, so results were seen then; nothing in the design changed because of them. A bug in `fill_writeup.py` (it anchored on the first mention of "## 4. Results", which is inside the header) deleted T03.md sections 1-3 twice; both times the text was restored and its sha256 equals the frozen value exactly. The writer now asserts the hash before it writes.

## Step 8: results page and check

- `tests/T03/report.py` builds `evidence/report.html` (137 kB, inline SVG, light and dark): the answer, the data and gates, one backtest end to end (decision, trade, units, daily NAV, statistics, one null draw, ranking), headline, comparators, per-book curves, null distributions, robustness, power, definitions.
- `tests/T03/check_page.py` shares no code with `report.py`, `analyse.py` or the engine. It re-derives every weekly decision from the raw Master files and the published NAVs, the published CAGR and worst fall from the raw NAV files, recomputes every statistic in the page's embedded JSON from the NAV curves and draws, checks the printed numbers appear in the page text, and requires the verifier's JSON to say passed. **168 checks, 0 failures.**
- Limit: the checker does not re-run the strategy from raw prices; that is the verifier's job (V1), and the checker requires V1 to have passed.
- `evidence/METHODS.md` is the companion methods file; `tests/T03/run.sh` regenerates everything and exits 0 (3 m 45 s).
- The page was not opened in a browser and was not published to an Artifact; it is a local file.
