# T15 Step 4 log: test scripts (2026-11-25)

Files: `analyse.py` (Claude), `fill_writeup.py`, `run.sh` (Claude; forks of T14's), `report.py` and `check_page.py` (a separate page-builder agent, forks of T14's; `check_page.py` imports nothing from the engine, `analyse.py` or `report.py`). Placeholder headings for T15.md sections 5-8 were added after the frozen region (the frozen hash is unchanged: `python tests/T15/check_prereg.py` OK).

- `analyse.py`: reads only the evidence; prints sections 4.0a-4.5; exits 1 on any failed gate (engine gates, regression.json, verify_t15.json required for a `headline` run, derived ties) and prints no result then. T15 has no null: there are no percentiles or p-values. C1-C4 = the difference has the stated sign in >= 3 of 4 books; ties (|diff| <= 1e-12, same drawdown event) are listed and the analysis says whether any verdict would change if they counted as equal (the frozen rule compares the unrounded values).
- `fill_writeup.py`: tested on a copy: sections 1-3 and 5-8 byte-identical, a second run idempotent.
- `report.py` / `check_page.py`: on the verified smoke evidence the page was generated and the checker reported 14,443 checks and 0 failures; it failed on a tampered number, text, verdict, chart value and date (exit 1). Both set stdout to UTF-8.
- `run.sh`: check_approved_data, check_prereg, engine (under a minute), verifier, analyse, fill_writeup, check_prereg, report, check_page, check_prereg.
- Engine fix found by Step 3 (AFFECTS STEP 2, done): `inputs.csv` now lists each window's own files (worker processes' files merged in; W1's seam files in `inputs_seam.csv`).
- Open: `METHODS.md` is written at Step 6; the evidence CSVs are 22 MB (W1) and 36 MB (W2), under the 100 MB limit.
