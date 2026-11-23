# T13 Step 4 log (test scripts), 2026-11-18

## What was built (all in `AA/tests/T13/`)
Forked from T11's scripts (copied from `tests/T11/`, then edited; nothing under `tests/T11` was changed): `analyse.py`, `fill_writeup.py`, `report.py`, `check_page.py`, `rerun_draw.py`, `plot_parent_vs_partb.py`, `run.sh`. Mechanical pass first (paths `tests/T11/` → `tests/T13/`, `T11.md` → `T13.md`, `verify_t11` → `verify_t13`, `t11_engine` → `t13_engine`, seeds `[14, …]` → `[16, …]`, `also_seed_14` → `also_seed_16`), then the edits below.

### Changes against T11's scripts
- **run.sh**: T13 paths; order unchanged (check_approved_data → check_prereg → `t13_engine.py --run headline` → `verify_t13.py` → analyse → fill_writeup → check_prereg → plot → report → check_page → check_prereg); example draw ids 11 / 7 / 3.
- **rerun_draw.py**: imports `analysis/t13_engine.py`; seeds 16 in the text; new example ids; asserts the engine's `state` is the 2-of-3 rule (`n_buy >= 2`); notes that the all-3 rule has no draws.
- **plot_parent_vs_partb.py**: new `--evidence/--out/--books` (default unchanged: `evidence/headline` → `evidence/plots`, the folder report.py reads); labels say "2-of-3 rule"; `squeeze=False` so one book plots.
- **fill_writeup.py**: paths; the 4.2 title now names the all-3 comparator. Block keys 4.0a..4.6 unchanged; hashing and refusal logic unchanged.
- **analyse.py**
  - Rule text (`RULE_TXT`) printed in the header and 4.0a; the worked decision prints `n_buy`, `at_least_two_buy` and `all_three_buy`.
  - Gates: V4 needs `a1_t11_regression` in `regression.json`, `regression_t11.json` present, identical to it, `pass` true, every book's decisions compared with 0 mismatches, worst relative difference below its tolerance for both all-3 runs. `d_signals` adds `n_buy_vs_signs` and `state_vs_n_buy`. `c_shared_code` prints `against`, `changed_functions`, `new_in_t13`, `dropped_from_t11`. A non-empty `unexpected_changes` or `required_not_identical` fails V4. Re-derived here: `n_buy`, `state`, `state_all3` and the two boolean columns from the three signs; the all-3 runs' `invested_weeks`; end NAVs of the all-3 runs. When T11's stored evidence exists (`--t11`), `state_all3` is compared with T11's `decisions.csv` state and the all-3 runs with T11's `daily_nav.csv` strategy runs (need < 1e-12). V5 reads `also_seed_16`.
  - Reportability: a line comparing the counts frozen in T13.md §2 with the evidence (9 round trips, the in- and out-spell lists, 78/35/22/93, 22/0, all-3 93 weeks in 8 spells, 8 sleeve trades, 15 of 19, 74/39, R3 210 decisions starting OUT with 7 round trips). This line only checks the text and is not a gate.
  - **4.2 the all-3 comparator**: decision table per book (IN weeks under each rule, weeks IN under 2-of-3 and OUT under all-3, the reverse, stretches, weeks by n_buy, round trips and sleeve trades of each rule). The stretch table for the first book (decision dates, sessions held, parent and 50/50 sleeve at 0 bps). Part B (`strategy` vs `strategy_all3`) and Part A (`strategy_fixed50` vs `strategy_all3_fixed50`) CAGR, maximum drawdown and the gaps at 0/20.8/50 bps. Trades and cost of the all-3 runs. No percentile and no pass mark.
  - 4.3: the priors are T11's null SDs, computed from T11's stored draws (T13.md §3 step 12). T11's script quoted T06's SDs here.
  - 4.4: T11 replaces T09 in the outcome map. T11's counts at the 90th percentile come from T11's stored draws/stats, cross-checked against `verify_t11.json` `criteria` to its 0.05 rounding. The rows follow T13.md §2: "all FAIL … with T11, neither entry rule shows an edge" and "equity criteria PASS here where T11 failed …".
  - 4.5 R4: T11's stored percentiles (F1f, F2f, F1–F4, CAGR and DD, plus both T11 rules' CAGR) come first. T06, T08 and T09 follow, unchanged.
  - New `--t11` argument (default `tests/T11/evidence/headline`).
- **report.py**: title, h1 (T13.md's question), eyebrow, rule formula, answer, the exit and entry text (counts the BUY signs), the caveats (no hold-out: T11 seen and the 2-of-3 entry proposed after it) and V4's gate description (a1/a2) are all rewritten. **New section `#all3`** (after the gap section): the decision table, the stretch table, a CAGR and worst-fall table per book and cost for Part B and Part A of both rules, and one hoverable growth chart per book. Each chart has hold-the-parent and Part B and Part A of each rule at 20.8 bps, start and end dates and the four end values in its caption, and the rebuilt-NAV caption. The page JSON has `all3` and `t11_counts` (`t09_counts` is removed). `historical_reference` gains `T11`, shown first in R4 as the main reference. The outcome map reads T11. New `--t11`.
- **check_page.py**: now checks `state` = at least two BUY, `n_buy`, `state_all3` and `all_three_buy` against the signs. It types the frozen counts from T13.md:
  - bounds [2, 30] / [2, 33] / [2, 36] / [2, 19];
  - 9 in-spells and 9 out-spells, with their lengths;
  - weeks by n_buy 78/35/22/93; 22 weeks 2-of-3 only, 0 all-3 only; all-3 IN 93 weeks in 8 spells; 9 round trips;
  - OUT-week gold BUY/SELL 74/39; 8 sleeve trades; 15 of 19 gold spells with an OUT week;
  - tuples 120,432,707,298 / 144,224,745,588 / 6,835,192,844,305 / 4,976,743,356;
  - R3: 210 decisions, first OUT, 7/101 and 8/109, 7 round trips, gold first SELL, 9/130 and 9/80, bounds [2, 30] / [2, 33] / [2, 36] / [2, 15], 8 sleeve trades, tuples 271,511,233 / 8,485,744,608 / 426,468,399,525 / 644,288,463.

  It also checks:
  - the all-3 runs' CAGR and worst fall at three costs, from daily_nav.csv and stats.csv;
  - their trades (exits, entries, sleeve rebalances) against `state_all3`, their basket changes, and stats `invested_weeks`/`trades`;
  - the `#all3` section: the three tables row by row, the page data, one chart per book with the caption, the hover arrays, and each chart's own figcaption (book, start and end date, end values);
  - the T11 reference recomputed from T11's draws/stats; T11's stored rule equals this test's all-3 runs; the T11 verdict counts and outcome rows;
  - new phrases, and the negative check that T11's "all BUY" rule text is gone.

  Chart counts are now 3 per book plus the regime chart. The gap section's regex now ends at `#all3`. The length-chart edges check is guarded against a shape mismatch, so a corrupted sign now gives FAILs instead of an exception.

## Tests (copies and scratch only)
Scratch: `C:\Users\manur\AppData\Local\Temp\claude\d384933f9ddb0ecb\ec2b6184-19ff-47bd-84d2-2600c6eb662c\scratchpad\s4\` (`run4/ev` = copy of the 4-book 100-draw scratch run, `runsmoke/ev` = copy of `evidence/smoke`, `T13_copy.md`).

- `python -m py_compile` on all six .py files: OK. `bash -n run.sh`: OK. `check_prereg.py`: OK (`ab1d6f47…`) before and after every test.
- `verify_t13.json`: a clearly marked stand-in was used at first. Then `analysis/verify_t13.py` appeared, and its real output replaced the stand-in in both copies:
  - 4-book scratch, `--draws 100`: exit 0, 562,752 gate comparisons, 0 failures, corrupted copy detected;
  - smoke, `--draws 20 --books SCMO_0003`: exit 0, 127,690 comparisons.
- **4-book scratch (real verifier):** analyse exit 0, gates V1–V6 PASS; report built; check_page **2,464 checks, 0 failures**. Also run:
  - with an amendments copy of T13.md: 2,464 checks, 0 failures, amendment shown;
  - with every reference absent (`--t11/--t06/--t08/--t09` pointing nowhere): analyse exit 0 with omission notes; check_page 2,442 checks, 0 failures.
- **Smoke (1 book, 20 draws, real verifier):** plot, analyse (exit 0, V1–V6 PASS), report; check_page **1,052 checks, 0 failures**.
- **fill_writeup** on copies only (`test_fill.py`): 12 of 12. Results:
  - first fill: §1–§3 hash equals the header, and the bytes before §4 and from §5 are identical;
  - line endings are kept, and the placeholder is replaced;
  - a second run is byte-identical;
  - the blocks 4.0a–4.6 are in order, and the 4.2 table is verbatim;
  - an Amendments block survives a refill;
  - it refuses (file untouched) on: a log missing a block, duplicated markers, a misplaced END marker, a missing §5 heading;
  - an edited §2 in a copy stays visible (its hash differs from the header);
  - a copy with the other line ending is filled correctly;
  - the real T13.md was untouched.
- **rerun_draw** (4-book scratch): 9 of 9 EQUAL:
  - F1 timed, F3, F2 fixed50, F4 at 0 bps, F5, F1 on R3, F1 fixed50 with liq cash, F1 fixed50 at 50 bps, F3 on R3;
  - the F1 and F3 daily curves match to 5.9e-8 and 5.0e-8 (float32).
- **Planted corruptions** (`corrupt.py`): 32 planted, 32 caught (non-zero exit).
  - 12 in the evidence: state_all3 flip, n_buy change, 2-of-3 state replaced by all-3, all-3 NAV scaled, all-3 invested weeks, an all-3 exit removed, an all-3 basket change removed, a draw CAGR, a draw out of bounds, a parent-NAV value, a sleeve rebalance removed, an index sign flipped.
  - 1 in the T11 reference (a copy of T11's stats.csv).
  - 12 in the page: comparator cell, decision count, stretch date, page-data all3 count, formula reverted to all-3, hover value, chart caption end date, T11 count, outcome answer, caption removed, the no-hold-out caveat reverted, a 50 bps all-3 CAGR.
  - 7 analyse gate cases: regression_t11 pass=false, regression_t11 missing, unexpected shared-code change, a1 worst diff 1e-9, also_seed_16 missing, all-3 NAV changed by 1e-7 with stats made consistent (caught only by the T11 re-derivation), verifier failures.
  - First pass: 31 of 32. The miss was a changed end date in one chart caption: the check searched the whole page and found another book's caption. It now reads each chart's own figcaption. The flipped-sign case first ended in an exception; it now gives 107 FAILs.
- Nothing was written inside `tests/T13/` except the scripts and this log (a `__pycache__` from py_compile was removed). No engine headline run was made, no `evidence/headline/`, and no `analysis.log` or `report.html` in `tests/T13`. T13.md, TRACKER.md, the engine, the verifier and `tests/T11` were not edited.
- Not done: a browser check (Playwright) of the new charts' hover in light, dark and phone views. The hover code is T11's (`LINES_JS`, keyed by `data-book`); only new data keys `all3|<book>` were added.

## Silent or ambiguous points (readings taken)
1. **T13.md line endings**: the brief says LF; on disk T13.md is CRLF. fill_writeup keeps whichever it finds (tested both ways). check_prereg strips CR, so it is unaffected.
2. **T11's stored result** is recomputed from T11's `draws.csv`/`stats.csv` (rank of T11's rule against T11's own draws, full window, LBES, 20.8 bps), the same way T11 read T09. analyse cross-checks it against `verify_t11.json` `criteria` (agree to 0.05). These are reference numbers only.
3. **Outcome row "equity criteria PASS here where T11 failed"** reads as: (A1 and A2 pass here and T11's A pair did not) or (C1 and C2 pass here and T11's C pair did not). This is the same logic T11 used for its T09 row. The "all FAIL" row adds T11's stored pattern in brackets.
4. **R4**: T13.md §2 names "T11's stored percentiles … and T06's, T08's and T09's" as a reference. All four are shown; T11 is first and labelled the main reference.
5. **The comparator's extra descriptive tables are a reading.** The decision-level table adds stretches, round trips and sleeve trades of each rule. The stretch table shows parent and 50/50 sleeve returns at 0 bps over the sessions held. The contract asks for CAGR, drawdown, gaps, "weeks in under 2-of-3 but out under all-3" and the all-3 IN weeks. None of these has a percentile.
6. **analyse's V4 also compares the all-3 runs with T11's stored evidence when it is present.** A mismatch fails V4. If the evidence is absent, a note is printed and the engine's V4(a1) decides. This duplicates V4(a1) independently; T13.md asks only for the engine's gate.
7. **The frozen-count line in analyse is informational.** check_page types the same counts and fails on any difference.
8. **rerun_draw** imports the engine, which reads the approved data. This is the one exception to "scripts read only evidence", as in T11 (T13.md §3 step 11 names it).
9. **The 2-of-3 entry rule.** In the worked example, the first entry of the 2-of-3 rule is a week with exactly two BUY signs, so the page's entry text and the check count BUY signs instead of requiring three.
10. **The verifier's `--run` help text** still says "under tests/T11/evidence/". Its code uses `tests/T13/evidence/`. This is cosmetic, in `analysis/verify_t13.py`, which is not mine to edit.

## AFFECTS STEP 5/6
- Step 5: `bash tests/T13/run.sh` from `AA/`. `verify_t13.json` must exist before analyse. check_page expects more than 100,000 verifier comparisons at 2,000 draws. analyse also reads `tests/T11/evidence/headline/` (decisions.csv, daily_nav.csv, draws.csv, stats.csv, verify_t11.json) as a reference.
- Step 6: §4 is filled only by fill_writeup from analysis.log. Amendments go in `### Amendments before the run` after the §4 END marker. `evidence/METHODS.md` is still to write (the page links to it).
