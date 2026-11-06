# T06 Plan — T03's three-index switch against a free-length random timing (N4.10)

**Written 2026-11-06. Nothing in this plan has been run.** Format follows `AA/tests/T05/PLAN.md`.

## Multi-Agent Handoff Design

### Dependency graph

```
Step 1 (Pre-Reg) ──┬──→ Step 2 (Engine code)
                   ├──→ Step 3 (Verifier code)       ← evidence format defined below
                   └──→ Step 4 (Test scripts)         ← evidence format defined below

Step 2 + 3 + 4 ──→ Step 5 (Run pipeline) ──→ Step 6 (Fill results + Report + CLAUDE.md + AGENT.md)
```

| Parallelism | Steps |
|---|---|
| **Must be first** | Step 1: the pre-registration is frozen before any engine or verifier code |
| **Fully parallel** | Steps 2, 3, 4: all depend only on Step 1 and on the evidence format below |
| **Sequential gate** | Step 5 cannot start until Steps 2, 3 and 4 are ALL DONE |
| **Strictly sequential** | Step 5 → Step 6 |

**Independence rule for Step 3.** The verifier is written from the spec in T06.md §3 and this plan, **without reading `t06_engine.py`** (the T04 method, F-AA-M04). Its sampler check uses a counting formula the engine does not use (Step 3, check C-count).

### Evidence format (shared contract for Steps 2, 3, 4)

All files are written to `AA/tests/T06/evidence/<run>/`. The base is T03's evidence (`AA/tests/T03/evidence/headline/`); the differences are marked **new**.

| File | Columns / contents |
|---|---|
| `inputs.csv` | `file, bytes, sha256`: every input as in T03, plus `tests/T03/evidence/headline/draws.csv` and `stats.csv` (read for V4 and for the side-by-side) |
| `decisions.csv` | exactly T03's columns, one row per weekly decision and book |
| `stats.csv` | exactly T03's columns: strategy and the comparators (hold parent, constant mix, 100% sleeve) per book, window, cash, cost |
| `draws.csv` | T03's columns with `draw_type = "N4.10"`, plus **new** `sessions_invested`, `in_lengths`, `out_lengths` (strings, lengths in order joined by `\|`). Rows: full window × LBES × 3 costs; full × LIQUIDCASE × 20.8; live window × LBES × 20.8; 2,000 draws per book each |
| `draw_states.npz` | **new.** One array per `"<book>\|<window>"`, shape (draws, weeks), `uint8`, the in-or-out state of every draw in every week. Full window: 400 weeks (SCMO_0007: 399); live window: 251. LIQUIDCASE reuses the full-window states. This is the file T03 did not have, so any draw can be read without a rebuild |
| `draw_curves_20.8.npz` | daily NAV (float32) of every headline draw at 20.8 bps, key `"<book>\|N4.10_<id>"` |
| `trades.csv`, `positions.csv`, `daily_nav.csv` | as T03, for the strategy and comparators |
| `g_engine.csv` | as T03 (V4 of T03: always-in against the published NAV) |
| `count_table.json` | **new.** Per book, window and state: weeks S, spell count k, bounds (lo, hi), and the number of allowed length tuples (exact integer as a string). The page prints it |
| `sampler_selftest.json` | **new.** V5's results (below) |
| `regression_t03.json` | **new.** V4's results (below) |
| `audit.json` | as T03's (point-in-time counts, readings) with a `v3` block for N4.10 and `rule_in_support` per book and window |
| `verify_t06.json` | the verifier's output |

### Tracker file: `AA/tests/T06/TRACKER.md`

Created in Step 1. Same format and rules as T05's tracker (six steps; statuses `NOT_STARTED` → `IN_PROGRESS` → `DONE` / `DONE_WITH_NOTES`; read it before starting; update it on finishing; step logs in `AA/tests/T06/logs/step_<N>_log.md`; warnings prefixed `⚠ AFFECTS STEP X:`; no silent failures; final report lists files with full paths, key results and open issues).

---

## Context

**What T03 showed.** The three-index switch (parent only when Nifty 100, Midcap 100 and Smallcap 100 are all BUY, else 50/50 GOLDBEES and cash) beats the same nine in-spells and nine out-spells placed at random: C1 percentiles 96.0, 86.4, 95.0, 92.4 and C2 97.5, 94.7, 97.5, 97.6 (F-AA-S04, PROVISIONAL: only 1 of 4 books reaches 90 on the live decisions alone).

**What prompted T06.** The highest-CAGR N4.9 draw for SCMO_0003 (draw 445, 44.8% against the rule's 30.1%) was the rule's own spells moved: its 46-week in-spell landed on the 2020-05 → 2021-03 rally. N4.9 holds the rule's nine lengths exactly, so it asks only about *order*. T06 asks whether the result survives when the lengths are free too. Also, N4.9 holds invested **weeks** exactly but invested **sessions** only approximately (draw 445: 945 against 941 of 1,884); T06 reports both.

**What T06 changes.** Only the null. The rule, engine, parents, window (2019-01-02 → 2026-08-21), costs, sleeve, cash and statistics are T03's, unchanged.

**Key files from T03 (to fork from or import):**
- `AA/analysis/t03_engine.py`: the engine. T06 **imports** `Book`, `simulate`, `stats`, `spells`, `spell_sig`, `sha`, `raw_parent`, `PARENTS`, `COSTS`, `PRIMARY`, `LIVE_START`, `END` rather than copying them, so V4 can show the two engines agree. `run_book` hard-codes its draw list and is **copied** into the T06 engine with the draw list replaced.
- `AA/analysis/verify_t03.py`: style and structure for the verifier (read for style only).
- `AA/tests/T03/T03.md`: write-up structure.
- `AA/tests/T03/report.py`, `check_page.py`, `analyse.py`, `fill_writeup.py`, `check_prereg.py`, `run.sh`: forked. T03's `report.py` already has the regime chart, the held/randomised table and the hover layer (`svg_regime`, `HOVER_JS`); `AA/tests/T04/report.py` has hover for histograms and lines (lines ~100–135).
- `AA/tests/T03/best_draw.py`, `rerun_draw.py`: patterns for reproducing one draw.

**Data:** exactly T03's inputs (D03, D05, D09, D11, D12, D17, D18, D19, price corrections). No new data review, **no data extension** (decision 1 below).

**Repo conventions:** `AA/CLAUDE.md` (standing rules), `AGENT.md` R10 (results page, including **every chart hoverable** with a timestamp chip, a y chip and a tooltip listing every data point at that x).

### Decisions taken (2026-11-06)

1. **Same window and inputs as T03, no data extension.** The totals (199 in-weeks, 201 out-weeks) and the comparison with N4.9 depend on it. A re-run on extended data is a later test. This is a deliberate exception to the "keep the data pool current" rule in `AA/CLAUDE.md`, and the write-up says so.
2. **Numbering.** T05 exists as its own plan (monthly stock filter, SELL regime). T06 is independent of it and does not read its outputs.
3. **No bound-sensitivity run** (no variants with other minimums or caps). It would add multiplicity; it can be a later test.

---

## T06 Rule (the test's complete specification)

1. **The strategy** is T03's, byte for byte: weekly decision on the last D17 session of each ISO week; IN iff Nifty 100, Midcap 100 and Smallcap 100 are all BUY; IN = 100% parent, OUT = 50% GOLDBEES + 50% LBES cash; next-session OHLC4 fills; 10.4 bps a side.
2. **The null, N4.10 "random timing with free spell lengths".** From the rule's weekly series s_0 … s_n, take its first state s_0, the number of in-spells k_in and out-spells k_out, and the total weeks S_in and S_out. For each draw:
   - draw the k_in in-spell lengths: integers in [2, 46], sum S_in, **uniform over all ordered tuples** satisfying that;
   - draw the k_out out-spell lengths: integers in [2, 40], sum S_out, uniform likewise, independently;
   - interleave alternately starting in s_0, and run the result through the same engine.
   For the four books' full window: k_in = k_out = 9; S_in = 199, S_out = 201 (SCMO_0003, 0010, 0029, 400 weeks); SCMO_0007 has 399 weeks and uses **its own** S values from its own series.
3. **Bounds.** 2 weeks = 14 days. 46 and 40 are the longest in-spell and out-spell of the rule over the full window (as T03's circular-shift floor of 46 came from the longest spell). The same constants are used for every book and window.
4. **Held:** the first state, the spell counts (so entries and exits), the total weeks invested, the calendar, the book, the costs, execution. **Randomised:** every spell's length and order. **Not held exactly:** sessions invested (weeks hold 3–5 sessions), reported per draw.
5. **The rule is inside the allowed set.** Its lengths (8–46 in, 5–40 out) lie within the bounds, so every N4.9 draw is one allowed configuration of N4.10. V3 checks this per book and window.
6. **Sampler (exact, no rejection).** Let c(m, t) be the number of ways to write t as m integers in [lo, hi], by dynamic programming. Draw the parts one at a time: for part i with m parts and t weeks left, P(length = x) ∝ c(m − 1, t − x) for x in [lo, hi]. The uniform number comes from `rng.random()` and a cumulative-sum search (not `Generator.choice`), so a draw does not change across numpy versions. Seed `numpy.random.default_rng([6, draw_id])`, `draw_id` = 0 … 1,999, in-spell lengths drawn first, then out-spell lengths, from the same generator. The same draw ids are used for every cost and for the three identical books.
7. **Windows and cash.** Headline: full window, LBES, 0 / 20.8 / 50 bps. R2: full, LIQUIDCASE, 20.8. R3: live window (2021-11-01 → 2026-08-21: 251 weeks, spells (out 39, in 20, out 18, in 26, out 5, in 46, out 30, in 11, out 37, in 19); S_in = 122, S_out = 129; k = 5 and 5; first state OUT) with its own totals and the **same bounds**, 2,000 draws, 20.8 bps. The live window's first spell is partial (the series starts mid-spell) and is treated as any other spell, as in T03. If a window's totals cannot be split within the bounds, or it has fewer than 4 round trips, it is NOT REPORTABLE.
8. **Draws:** 2,000 per book and cost, seeded.
9. **Criteria (after cost at 20.8 bps, per book, 4 books), as T03:**
   - **C1** after-cost CAGR percentile against N4.10 ≥ 90 in at least 3 of 4 books;
   - **C2** maximum-drawdown percentile ≥ 90 in at least 3 of 4 books.
   Percentile = (draws worse + 0.5 × ties) ÷ draws × 100; p = (1 + draws at least as good) ÷ (draws + 1). Secondary statistics as T03 (volatility, Ulcer, days ≥ 10% below peak, longest time under water, Calmar).
10. **Robustness (reported; they decide a finding's status, not the verdicts):** R1 C1 and C2 at 0 and 50 bps; R2 C1 with LIQUIDCASE cash; R3 C1 on the live window (own spells, own totals); R4 **agreement with N4.9**: T03's stored percentiles beside T06's per book, and the spread of the two nulls (median, SD, 5th and 95th percentile of CAGR). R4 is a table, with no pass mark. The circular-shift null is **not** rerun; T03's stands.
11. **Outcome map:**

| Pattern | Conclusion |
|---|---|
| C1 and C2 PASS, and N4.9 passed in T03 | The result does not depend on the spell lengths. F-AA-S04 stays PROVISIONAL (in-sample, live window) but is better supported |
| PASS under N4.9, FAIL under N4.10 | The edge depends on the rule's particular spell lengths and where they fall |
| FAIL under both | No timing edge over chance for these books |
| a V gate fails | Nothing is read. Fix and rerun as a new run directory |

12. **Which null decides.** For T06's verdict, N4.10. T03's N4.9 verdict is not changed. If the two disagree, both are reported and F-AA-S04's status note says so.
13. **Multiplicity.** One rule, no grid. N4.10 is the **third** null applied to this rule (N4.9, circular shift, N4.10), declared here; T06 alone cannot upgrade F-AA-S04.
14. **Expectation, declared before any run:** no basis for a direction. A draw can put a long spell on a rally, so the null's spread is probably wider than N4.9's and the rule's percentile may move either way. The pass mark stays 90 whatever the spread.
15. **Disclosures (go in §2):** the bounds were chosen after seeing T03's draw 445; the rule and window have been seen; the decisions before 2021-11 are a production backfill.

---

## Step 1 — Pre-Registration (T06.md §1–§3, `check_prereg.py`, `TRACKER.md`)

**Goal:** write and freeze the pre-registration before any engine or verifier code. Fork T03.md's structure.

**File:** `AA/tests/T06/T06.md`

### §1 — Idea and references
- One sentence: "Holding the parent only when the three indices are all BUY chooses *when* better than random timings that keep the rule's switch count and total weeks invested but may use any spell lengths."
- Origin: T03 draw 445; N4.9 holds the lengths. Decision it changes: whether F-AA-S04 rests on the rule's particular spell lengths. What is known: T03's results, F-AA-S04, F-AA-M02. References: T03.md, `AGENT.md` N4.9.
- What this test is NOT asking: a different rule, a different sleeve, whether the rule beats holding the parent.

### §2 — Hypotheses and criteria
- H1 (timing), H2 (protection) as T03; null N4.10 as in Rule item 2 with its **table** (dimension, randomised or held, how, measured in §4.0): timing of spells **randomised**; spell lengths **randomised within [2, 46] / [2, 40]**; total weeks invested **held** (identical, checked); spell count and first state **held**; sessions invested **not held exactly** (reported); book, calendar, sleeve, cost, execution **held**.
- Statistic, unit, percentile and p-value definitions, pass mark, criteria C1 and C2, validity gates V1–V5 (below), reportability gate, robustness R1–R4, multiplicity, outcome map, expectation and disclosures: Rule items 9–15.

### §3 — Methodology
- Data table as T03's (same IDs and verdicts). Construction steps 1–10 as T03 §3 (they are unchanged); step 11 replaced by the N4.10 sampler of Rule item 6, with the DP stated and a worked small example; step 12 (MDE) as T03.
- **Plain-words section** (AGENT.md task 5 item 13): how one N4.10 draw is made, with the first 20 weeks of a real and a drawn series printed in §4.0a, and the in-spell lengths of that draw beside the rule's.
- Point-in-time, execution and cost, effective sample size and power: as T03 (9 round trips per book; the independent unit is the round trip).

### check_prereg.py
Fork T03's. Change the path constants. Verify the sha256 of §1–§3.

### Also create
`AA/tests/T06/TRACKER.md` (T05's format), `AA/tests/T06/logs/`.

### Handoff block (Step 1)

| Field | Value |
|---|---|
| **Depends on** | Nothing |
| **Produces** | `AA/tests/T06/T06.md` (§1–§3 frozen, sha256 in the header), `check_prereg.py`, `TRACKER.md`, `logs/` |
| **Done when** | `python tests/T06/check_prereg.py` exits 0; TRACKER Step 1 → DONE |
| **Tracker update** | "Pre-registration frozen, sha256=<first 12 chars>" |

---

## Step 2 — Engine (`AA/analysis/t06_engine.py`)

**Goal:** the N4.10 sampler and a run orchestrator on top of T03's engine.

**File:** `AA/analysis/t06_engine.py`

### Contents
1. `from t03_engine import ...` (list under Context). Constants: `T06 = AA / "tests" / "T06"`, `SEED = 6`, `LO = 2`, `HI = {1: 46, 0: 40}`.
2. `count_table(k, S, lo, hi)`: the DP c(m, t) for m = 0…k and t = 0…S as Python ints; returns the table. `n_ways = c[k][S]`; assert `n_ways > 0` (feasibility).
3. `draw_lengths(rng, k, S, lo, hi, table)`: the sequential sampler of Rule item 6 (cumulative-sum search on `rng.random()`).
4. `free_length_draw(s, draw_id)`: spells of `s`; k and S per state; `rng = default_rng([6, draw_id])`; in-lengths then out-lengths; interleave from `s[0]`; return the weekly state array. Asserts length, sums and bounds.
5. `run_book6(...)`: a copy of `t03_engine.run_book` with the draw list = N4.10 only, no circular shifts, writing the extra draw columns (`sessions_invested`, `in_lengths`, `out_lengths`) and collecting the states for `draw_states.npz` and the headline curves.
6. `main()`: as T03's, with `--run`, `--draws`, `--quick`; evidence to `tests/T06/evidence/<run>/`. Also writes `count_table.json`, `sampler_selftest.json` (V5) and `regression_t03.json` (V4) and the audit's `v3` block.

### Self-checks the engine runs (V3, V4, V5; writes results, exits non-zero on failure)
- **V3 (null holds its table), every draw:** length = the book's weeks; first state = the rule's; k_in and k_out equal the rule's; sum of in-lengths = S_in and of out-lengths = S_out (so weeks invested identical); every length within its bounds. **And** `rule_in_support`: the rule's own lengths lie within the bounds.
- **V4 (regression to T03):** (a) the strategy's stats rows equal `tests/T03/evidence/headline/stats.csv` to 1e-12; (b) `t03_engine.spell_shuffle` draws 0–19 per book re-run through T06's orchestrator reproduce T03's `draws.csv` rows (end NAV and CAGR to 1e-12).
- **V5 (sampler):** (a) small case k = 3, S = 12, bounds [2, 6]: enumerate every tuple, draw 200,000 samples, chi-square against equal frequencies, p > 0.001; (b) the production count table's `n_ways` equals the inclusion–exclusion formula Σ_j (−1)^j C(k, j) C(S − k·lo − j·(hi − lo + 1) + k − 1, k − 1); (c) over the 2,000 draws, the mean in-spell length is within 4 standard errors of S_in ÷ k_in (and likewise out).

### Handoff block (Step 2)

| Field | Value |
|---|---|
| **Depends on** | Step 1 DONE |
| **Reads from prior steps** | `T06.md` §3; `TRACKER.md` |
| **Produces** | `AA/analysis/t06_engine.py` |
| **Done when** | `python analysis/t06_engine.py --run smoke --draws 20 --quick` exits 0 and writes the evidence files above; V3, V4, V5 pass in the smoke run; V4's strategy rows match T03 exactly |
| **Tracker update** | "Engine written. V3/V4/V5 pass on smoke. n_ways SCMO_0003: in <N>, out <N>. Smoke OK." |

---

## Step 3 — Independent Verifier (`AA/analysis/verify_t06.py`)

**Goal:** an independent re-derivation, written from the spec **without reading `t06_engine.py`**. Imports nothing from the engine or any AA analysis module (not `t03_engine` either). Style from `verify_t03.py`.

### Checks
1. **C-dec / C-pit / C-nav0 / C-cost / C-comp / C-always-in / C-corrupt:** as `verify_t03.py` (re-derive decisions from the raw Master files and the published calendar, 0-cost and costed NAVs, the comparators, always-in against the published NAV; a corrupted copy must exit non-zero).
2. **C-states (new):** for **every** draw of every book and window in `draw_states.npz`: weeks, first state, spell counts, sums per state, bounds [2, 46] / [2, 40], alternation. Compare with the `draws.csv` columns (`invested_weeks`, `n_in_spells`, `n_out_spells`, `in_lengths`, `out_lengths`, `sessions_invested`).
3. **C-draw-nav (new):** re-simulate the first 20 and 20 random draws per book from the saved states with the verifier's own simulator; end NAV within a relative 1e-9 of `draws.csv`, at each cost.
4. **C-count (new):** count the allowed tuples with the inclusion–exclusion formula (not a DP) and compare with `count_table.json`.
5. **C-support (new):** the rule's own spell lengths lie within the bounds.
6. **C-percentile (new):** recompute each percentile and p from `draws.csv` and compare with `analysis.log` and the page's data.
7. It exits 0 only if rows were compared and none failed; writes `verify_t06.json` with the counts.

### Handoff block (Step 3)

| Field | Value |
|---|---|
| **Depends on** | Step 1 DONE (spec). Code does not need Step 2; the evidence it checks arrives at Step 5 |
| **Reads** | `T06.md` §3, this plan's evidence format, `verify_t03.py` for style |
| **Produces** | `AA/analysis/verify_t06.py` and `AA/tests/T06/logs/verifier_spec.md` (the spec it was written from) |
| **Done when** | `python -c "import verify_t06"` from `AA/analysis/` is clean |
| **Tracker update** | "Verifier written. N checks defined. Awaits Step 5 evidence." |

---

## Step 4 — Test scripts

Fork from T03's equivalents into `AA/tests/T06/`.

- **`analyse.py`:** percentiles per book and cost for C1, C2 and the secondary statistics; R1–R3; **R4** (side by side with T03's N4.9 percentiles and the null spreads); the MDE; writes `analysis.log`; exits non-zero if a gate failed.
- **`fill_writeup.py`:** copies `analysis.log` into T06.md §4. It **must leave §1–§3 byte-identical** (F-AA-M02; two bugs in T03's version deleted them twice). Run `check_prereg.py` straight after.
- **`report.py`:** forked from T03's `report.py` (it already has the regime chart, the held/randomised table and the hover layer). Sections: answer; data; **one backtest end to end including one N4.10 draw** (the sampler's steps, the DP count for the first in-spell, the first 20 weeks of a real and a drawn series); headline table; per-book curves; **null histograms with N4.9's overlaid** (T03's draws read from `tests/T03/evidence/headline/draws.csv`); the spell-length distributions of the draws against the rule's; the highest-return N4.10 draw against the rule (regime chart, held/randomised table); robustness; power; definitions. **Every chart hoverable** (AGENT.md R10): crosshair, timestamp chip on a time axis, y chip, tooltip listing every data point at that x; for histograms the bin edges, count, share and the marked values. The hover arrays come from the same arrays that draw the chart.
- **`check_page.py`:** forked from T03's, re-derives every number, date and **every hover array** from the evidence.
- **`run.sh`:** 
```bash
#!/usr/bin/env bash
# Regenerate every T06 artefact from the raw files. Run from AA/:  bash tests/T06/run.sh
set -euo pipefail
python tests/T06/check_prereg.py
python analysis/t06_engine.py --run headline
python analysis/verify_t06.py
python tests/T06/analyse.py
python tests/T06/fill_writeup.py
python tests/T06/report.py             # reads the best draw's states straight from draw_states.npz
python tests/T06/check_page.py
python tests/T06/check_prereg.py
```
- **`rerun_draw.py`:** `--book --id --cost --window`: rebuilds an N4.10 draw from its id and compares with `draws.csv` and `draw_states.npz` (exit 0 only if equal to 1e-12 and the states match).

### Handoff block (Step 4)

| Field | Value |
|---|---|
| **Depends on** | Step 1 DONE |
| **Produces** | `analyse.py`, `fill_writeup.py`, `report.py`, `check_page.py`, `rerun_draw.py`, `run.sh` in `AA/tests/T06/` |
| **Done when** | all scripts syntactically valid (`python -m py_compile`) |
| **Tracker update** | "Test scripts written." |

---

## Step 5 — Run pipeline

**Command:** `cd AA && bash tests/T06/run.sh`

Runs the pre-registration check, the engine (2,000 draws × 4 books × 3 costs, plus LIQUIDCASE and the live window; no circular shifts, so it should not be slower than T03's engine run, which includes 3,693 shifts per book; measure it in the Step 2 smoke run), the verifier, the analysis, the write-up fill, the report and the page check.

**What to verify after the run:**
- all gates V1–V5 pass; `check_page.py` reports 0 failures;
- every N4.10 draw has 9 + 9 spells and sums of 199 and 201 (SCMO_0007: its own);
- the spread of N4.10's CAGR against N4.9's (printed in R4); no NaN or impossible values;
- `rerun_draw.py` reproduces the highest-CAGR draw;
- §1–§3 unchanged (`check_prereg.py`).

### Handoff block (Step 5)

| Field | Value |
|---|---|
| **Depends on** | Steps 2, 3 and 4 ALL DONE |
| **Produces** | `AA/tests/T06/evidence/headline/`, T06.md §4, `evidence/report.html` |
| **Done when** | the pipeline exits 0 and all gates pass |
| **Tracker update** | "Pipeline OK. V1–V5 PASS. C1 percentiles: <4 numbers>; C2: <4 numbers>. check_page: N checks, 0 failures." |

---

## Step 6 — Results and close

1. **Read `analysis.log`.** C1 and C2 PASS or FAIL against N4.10; R1–R3; R4 (agreement with N4.9).
2. **Fill T06.md §5–§8.** §5 findings with IDs taken from `AA/CLAUDE.md`'s counter **at the time of closing** (T05 may take F-AA-S06 and F-AA-M05 first; do not assume them). Expected entries: a strategy finding on whether F-AA-S04 survives free lengths (updates S04's status note, does not replace it) and a **method finding on N4.9's weeks-versus-sessions wording** (the table says "fraction of sessions invested" held; the gate V3 holds invested weeks; draw 445 differs by 4 of 1,884 sessions). §6 discussion; §7 verdict per hypothesis; §8 next steps.
3. **Add N4.10 to `AGENT.md`:** a new family entry after N4.9 ("Random timing with free spell lengths": recipe, what it holds and breaks, the exact sampler, when to use it beside N4.9), a row in "Choosing among them", and a dated row in the revision history.
4. **Update `AA/CLAUDE.md`:** current test, the finding counter, a pointer to T06's page.
5. **Methods file** `evidence/METHODS.md` with `check_page.py`'s count of checks and failures.
6. `python tests/T06/check_prereg.py` once more.

### Handoff block (Step 6)

| Field | Value |
|---|---|
| **Depends on** | Step 5 DONE |
| **Produces** | T06.md §5–§8, `AGENT.md` N4.10 entry, `AA/CLAUDE.md` update, `METHODS.md` |
| **Done when** | T06.md complete; `check_prereg.py` passes; AGENT.md and CLAUDE.md updated |
| **Tracker update** | "T06 COMPLETE. Verdict: <per hypothesis>. Findings: <IDs>." |

---

## Key edge cases (all agents)

1. **SCMO_0007 has 399 weeks** (it starts 2019-01-04). Its S values come from its own series; its draws use the same seeds but are not identical to the other three books'. The other three books have identical series and therefore identical draws.
2. **The live window's first spell is partial** (it starts mid-spell). It is a spell like any other, with the bounds applied; the first live out-spell is 39 weeks, inside the cap of 40.
3. **Feasibility.** For each window, `2·k ≤ S ≤ hi·k` per state. It holds for the headline (in: 18 ≤ 199 ≤ 414; out: 18 ≤ 201 ≤ 360) and the live window (in: 10 ≤ 122 ≤ 230; out: 10 ≤ 129 ≤ 200). If a window fails it, it is NOT REPORTABLE; do not change the bounds.
4. **A draw can equal the rule exactly** or equal an N4.9 draw; both are allowed and count as ties or draws as usual.
5. **Sessions invested differs by draw.** Record it; do not hold it.
6. **Last decision is not traded** (as T03). The 400th state is the rule's last (IN).
7. **Seeds.** `[6, draw_id]` only; do not reuse T03's `[3, …]`. Determinism: `rng.random()` plus a cumulative-sum search, never `choice`.
8. **`fill_writeup.py` must not touch §1–§3.**

---

## Statistical power note

The independent unit is still the rule's 9 round trips, identical across books, so "3 of 4" is a consistency check. Freeing the lengths widens the null's spread (a draw can place a 46-week spell anywhere and a 2-week spell anywhere), so the MDE (2.8 × null SD) is probably larger than T03's. It is computed after the run, in §4.3, and printed beside every FAIL; the pass mark does not depend on it.

---

## Files to create or modify

| File | Action | Step |
|---|---|---|
| `AA/tests/T06/T06.md` | CREATE | 1 |
| `AA/tests/T06/check_prereg.py` | CREATE | 1 |
| `AA/tests/T06/TRACKER.md` | CREATE | 1 |
| `AA/tests/T06/logs/` | CREATE dir | 1 |
| `AA/analysis/t06_engine.py` | CREATE | 2 |
| `AA/analysis/verify_t06.py` | CREATE | 3 |
| `AA/tests/T06/logs/verifier_spec.md` | CREATE | 3 |
| `AA/tests/T06/analyse.py`, `fill_writeup.py`, `report.py`, `check_page.py`, `rerun_draw.py`, `run.sh` | CREATE | 4 |
| `AA/tests/T06/evidence/headline/` | CREATED by the engine | 5 |
| `AA/tests/T06/T06.md` (§4–§8), `evidence/METHODS.md` | EDIT / CREATE | 5, 6 |
| `AGENT.md` (N4.10, choosing table, revision history) | EDIT | 6 |
| `AA/CLAUDE.md` | EDIT | 6 |

---

## Recommended agent groupings

**Option A (4 agents):** A = Step 1; then B = Step 2, C = Step 3, D = Step 4 in parallel; E = Step 5; F = Step 6.
**Option B (3 agents):** A = Step 1; B = Step 2; C = Steps 3 + 4 in parallel with B; D = Steps 5 + 6.
**Option C (2 agents):** A = Steps 1 + 2; B = Steps 3 + 4 + 5 + 6 (the verifier agent must **not** read `t06_engine.py`, so Step 3 should be a separate agent from Step 2 if independence is to hold; use A or B).

### How to brief an agent
Point it to: (1) this plan, (2) `AA/tests/T06/TRACKER.md`, (3) `AA/CLAUDE.md`, (4) the step number, (5) the T03 files to fork from. Template:

> Read the T06 plan at `AA/tests/T06/PLAN.md`. Read `AA/CLAUDE.md` for repo conventions and finding counters and `AGENT.md` R10 for the page rules (every chart hoverable). Read `AA/tests/T06/TRACKER.md`: if a step you depend on is not DONE, stop and tell me. You are responsible for **Step N**. Fork from the T03 files named in the plan. Write a step log to `AA/tests/T06/logs/step_N_log.md`, update the tracker, and report back with: files created or changed (full paths), key results, open issues.
