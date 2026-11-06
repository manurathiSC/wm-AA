# T06 Plan v2 — the three-index switch against a free-length random timing (N4.10), on the latest approved data

**Written 2026-11-06. Nothing in this plan has been run.** Revises `PLAN.md` (kept beside it, per `AA/CLAUDE.md`). **Where the two differ, this file wins.** Format follows `AA/tests/T05/PLAN.md`.

**What changed from `PLAN.md`:** (1) the window and inputs are the **latest approved data** (`AA/data/APPROVED_DATA.md`), not T03's frozen window; (2) T06 **re-runs N4.9 as well** on the new window, so the two nulls are compared on the same data; (3) the engine is a **fork** of T03's, not an import, because T03's engine hard-codes superseded files and an end date; (4) every input the engine opens must be an `APPROVED` row, checked in code; (5) the regression to T03 is limited to the overlap; (6) the spell counts and totals are recomputed on the new series, and are reported before the pre-registration is frozen.

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

**Independence rule for Step 3.** The verifier is written from the spec in T06.md §3 and this plan, **without reading `t06_engine.py`** (the T04 method, F-AA-M04). Its sampler check uses a counting formula the engine does not use, and it reads `APPROVED_DATA.md` with its own parser.

### Data boundary (applies to every step)

Read `AA/data/APPROVED_DATA.md` first. Use only its `APPROVED` rows. If anything is stale, missing or unclear, **stop and ask Manu**; do not extend, rebuild or re-fetch data. Run `python data/check_approved_data.py` before Step 1 and at the top of `run.sh`.

### Evidence format (shared contract for Steps 2, 3, 4)

All files are written to `AA/tests/T06/evidence/<run>/`. The base is T03's evidence (`AA/tests/T03/evidence/headline/`); the differences are marked **new**.

| File | Columns / contents |
|---|---|
| `inputs.csv` | `file, through, bytes, sha256, approved_row`: every input the run opened, with its APPROVED row and the file's `APPROVED_DATA.md` "As of" date in the header comment. **new:** the engine writes it from the table, and a mismatch stops the run |
| `decisions.csv` | T03's columns, one row per weekly decision and book, on the new window |
| `stats.csv` | T03's columns: strategy and the comparators (hold parent, constant mix, 100% sleeve) per book, window, cash, cost |
| `draws.csv` | T03's columns, with `draw_type` = `"N4.9"` and `"N4.10"`, plus **new** `sessions_invested`, `in_lengths`, `out_lengths` (strings, lengths in order joined by `\|`). Rows per type: full window × LBES × 3 costs; full × LIQUIDCASE × 20.8; live window × LBES × 20.8; 2,000 draws per book each |
| `draw_states.npz` | **new.** One array per `"<book>\|<window>\|<type>"`, shape (draws, weeks), `uint8`: the in-or-out state of every draw in every week. LIQUIDCASE reuses the full-window states. Any draw can be read without a rebuild |
| `draw_curves_20.8.npz` | daily NAV (float32) of every headline draw at 20.8 bps, key `"<book>\|<type>_<id>"` |
| `trades.csv`, `positions.csv`, `daily_nav.csv` | as T03, for the strategy and comparators |
| `g_engine.csv` | as T03 (always-in against the published NAV, G0 tolerance) over the whole new window |
| `count_table.json` | **new.** Per book, window and state: weeks S, spell count k, bounds (lo, hi), and the number of allowed length tuples (exact integer as a string) |
| `sampler_selftest.json` | **new.** V5's results |
| `regression_t03.json` | **new.** V4's results |
| `audit.json` | as T03's (point-in-time counts, readings) with a `v3` block for both nulls and `rule_in_support` per book and window |
| `verify_t06.json` | the verifier's output |

### Tracker file: `AA/tests/T06/TRACKER.md`

Created in Step 1. Same format and rules as T05's tracker (six steps; statuses `NOT_STARTED` → `IN_PROGRESS` → `DONE` / `DONE_WITH_NOTES`; read it before starting; update it on finishing; step logs in `AA/tests/T06/logs/step_<N>_log.md`; warnings prefixed `⚠ AFFECTS STEP X:`; no silent failures; the final report lists files with full paths, key results and open issues).

---

## Context

**What T03 showed.** The three-index switch (parent only when Nifty 100, Midcap 100 and Smallcap 100 are all BUY, else 50/50 GOLDBEES and cash) beat the same nine in-spells and nine out-spells placed at random on 2019-01-02 → 2026-08-21: C1 percentiles 96.0, 86.4, 95.0, 92.4 and C2 97.5, 94.7, 97.5, 97.6 (F-AA-S04, PROVISIONAL: only 1 of 4 books reaches 90 on the live decisions alone).

**What prompted T06.** The highest-CAGR N4.9 draw for SCMO_0003 (draw 445, 44.8% against the rule's 30.1%) was the rule's own spells reordered: its 46-week in-spell landed on the 2020-05 → 2021-03 rally. N4.9 holds the rule's lengths exactly, so it asks only about *order*. T06 asks whether the result survives when the lengths are free too. Also, N4.9 holds invested **weeks** exactly but invested **sessions** only approximately (draw 445: 945 against 941 of 1,884); T06 reports both.

**What T06 changes.** The null (adds N4.10) **and the data**: the latest approved data, window 2019-01-02 → **2026-10-22**. The rule, costs, sleeve and statistics are T03's.

### Data (all from `AA/data/APPROVED_DATA.md`, as of 2026-11-06)

| Role | File (paths relative to `AA/`) | Through |
|---|---|---|
| Calendar and published NAV (D17) | `Historical Data/parent_nav_2026-10-22/SCMO_<p>.csv` | 2026-10-22 (**sets the window end**) |
| Stock OHLC (D18) and corrections | `data/holdings_matrix/SCMO_<p>_ohlc.csv`, `price_corrections.csv` | 2026-11-04 |
| Basket weights (D19), their trace and columns | `data/holdings_matrix/SCMO_<p>_holding_weight_matrix.csv`, `_holding_weight_sources.csv`, `_columns.csv` | newest basket 2026-09-10 (0003) / 2026-09-16 |
| Basket history, skipped flags (D05) | `Historical Data/frozen_2026-09-25/Rebalance_history/…` | 2026-09-16 |
| Signals (D03, extended) | `Historical Data/extended_2026-10-30/Master/Master_{Nifty100,MC100,SC100}.xlsx` | 2026-10-30 |
| GOLDBEES (D09, extended) | `analysis/cache/why_gold_ohlc_eikon_extended_2026-11-04.parquet` | 2026-11-04 |
| Gold de-spike range (D12) | `analysis/evidence/final_strategy/mauc1/mauc1_daily_clean.csv` | 2026-09-28 (later fills use raw OHLC4: 5 sessions up to 2026-11-04) |
| Cash (D11, extended) | `Historical Data/LBES_Adjusted_Price_data_extended_2026-11-05.csv`; R2: `liquidEtfFinal_extended_2026-11-05.csv` | 2026-11-05 |

**Caveats to disclose in §3 and the page:**
- the LBES file's rows before 2026-08-10 have no recorded source (F-AA-D09); the rows after are LIQUIDCASE returns chained as level[t] = level[t-1] × (1 + r[t]) and run about 0.5 pp/yr rich against LIQUIDBEES (F-AA-D13);
- the window ends inside the last approved basket (next rebalance expected about mid-December 2026);
- the added weeks 2026-08-24 → 2026-10-22 are after T03's freeze but hold at most one new switch, so they add almost no evidence for or against timing;
- the decisions before 2021-11 are a production backfill (as T03).

**Key files from T03 (to fork from):**
- `AA/analysis/t03_engine.py` → **fork** into `t06_engine.py`. It must be a copy, not an import: it hard-codes `END = 2026-08-21` and the superseded frozen files (`why_gold_ohlc_eikon.parquet`, `frozen_2026-09-25/Master/…`, `LBES_Adjusted_Price_data_2026_08_10.csv`).
- `AA/analysis/verify_t03.py`: style and structure for the verifier (read for style only).
- `AA/tests/T03/T03.md`, `report.py`, `check_page.py`, `analyse.py`, `fill_writeup.py`, `check_prereg.py`, `rerun_draw.py`, `run.sh`: forked. T03's `report.py` already has the regime chart, the held/randomised table and the hover layer (`svg_regime`, `svg_lines`, `HOVER_JS`, `LINES_JS`); `AA/tests/T04/report.py` has hover for other chart types.
- `AA/tests/T03/evidence/headline/`: read-only reference for V4 and the historical side-by-side.

**Repo conventions:** `AA/CLAUDE.md`, and `AGENT.md` R10 (results page; **every chart hoverable**: timestamp chip on a time axis, y chip, tooltip listing every data point at that x).

### Decisions taken (2026-11-06)

1. **Option B:** run on the latest approved data (window end 2026-10-22), not on T03's frozen window.
2. **T06 re-runs N4.9 on the new window** beside N4.10, so the nulls are compared like for like. T03's stored percentiles are shown only as a historical reference (different window).
3. **No bound-sensitivity run.**
4. **Data boundary:** only `APPROVED` rows; the engine asserts it (Step 2).
5. T05 exists as its own plan (monthly stock filter) and is independent of T06.

---

## T06 Rule (the test's complete specification)

1. **The strategy** is T03's, unchanged: weekly decision on the last D17 session of each ISO week; IN iff Nifty 100, Midcap 100 and Smallcap 100 are all BUY; IN = 100% parent, OUT = 50% GOLDBEES + 50% LBES cash; next-session OHLC4 fills; 10.4 bps a side. The window runs from T0 (2019-01-02; SCMO_0007 2019-01-04) to **2026-10-22**, D17's last session; the decision at the last session is not traded.
2. **Spell counts and totals are recomputed** on the new series (counts only, no returns, before the pre-registration is frozen, as T03 did): per book, the first state, the number of in-spells k_in and out-spells k_out, the totals S_in and S_out, the longest in-spell and out-spell. Expected: the added weeks probably contain the rule's move out of equities (CLAUDE.md: the Smallcap 100 signal flipped BUY → SELL on 2026-10-01), so the series may end in a new out-spell (k_out = 10 against k_in = 9) and the final in-spell is longer. **Whatever the data give is what is registered.**
3. **N4.9 spell shuffle** (T03's, `spell_shuffle`, seed `[3, draw_id]`): shuffle the in-spells among themselves and the out-spells among themselves, interleave from the rule's first state. 2,000 draws.
4. **N4.10 "random timing with free spell lengths".** For each draw: draw the k_in in-spell lengths, integers in [2, HI_in], summing to S_in, uniform over all ordered tuples; draw the k_out out-spell lengths, integers in [2, HI_out], summing to S_out, likewise and independently; interleave alternately from the rule's first state; run through the same engine. **Bounds:** 2 weeks = 14 days; HI_in and HI_out = the rule's longest in-spell and out-spell on the new series. On T03's window these were 46 and 40; they stay 46 and 40 unless a new spell is longer, and Step 1 reports the values before freezing. The same constants apply to every book and window. SCMO_0007 (399 weeks) uses its own S values.
5. **Held:** first state, spell counts (so entries and exits), total weeks invested, calendar, book, costs, execution. **Randomised in N4.10:** every spell's length and order. **Not held exactly in either null:** sessions invested (weeks hold 3–5 sessions), reported per draw.
6. **The rule is inside the allowed set.** Its own lengths lie within the bounds by construction (the bounds are its longest spells and the minimum is 2), so every N4.9 draw is one allowed configuration of N4.10. V3 checks it per book and window.
7. **Sampler (exact, no rejection).** Let c(m, t) be the number of ways to write t as m integers in [lo, hi], by dynamic programming. Draw the parts one at a time: with m parts and t weeks left, P(length = x) ∝ c(m − 1, t − x) for x in [lo, hi]. The uniform number comes from `rng.random()` and a cumulative-sum search (not `Generator.choice`), so a draw does not change across numpy versions. Seed `numpy.random.default_rng([6, draw_id])`, in-spell lengths first, then out-spell lengths, from the same generator. The same draw ids are used for every cost and for books with identical series.
8. **Windows and cash.** Headline: full window, LBES (extended), 0 / 20.8 / 50 bps. R2: full, LIQUIDCASE (`liquidEtfFinal_extended`), 20.8. R3: live window (2021-11-01 → 2026-10-22) with its own spells, totals and the **same bounds**, 2,000 draws, 20.8 bps. The live window's first spell is partial (the series starts mid-spell) and is treated as any other, as in T03. A window whose totals cannot be split within the bounds, or with fewer than 4 round trips, is NOT REPORTABLE.
9. **Draws:** 2,000 per book, cost and null type, seeded.
10. **Criteria (after cost at 20.8 bps, per book, 4 books), as T03, decided on N4.10:**
    - **C1** after-cost CAGR percentile against N4.10 ≥ 90 in at least 3 of 4 books;
    - **C2** maximum-drawdown percentile ≥ 90 in at least 3 of 4 books.
    The same percentiles against N4.9 (re-run on this window) are reported beside them, not as criteria. Percentile = (draws worse + 0.5 × ties) ÷ draws × 100; p = (1 + draws at least as good) ÷ (draws + 1). Secondary statistics as T03 (volatility, Ulcer index, days ≥ 10% below peak, longest time under water, Calmar).
11. **Robustness (reported; they decide a finding's status, not the verdicts):** R1 C1 and C2 at 0 and 50 bps; R2 C1 with LIQUIDCASE cash; R3 C1 on the live window; R4 **agreement of the two nulls on this window** (N4.9 and N4.10 percentiles per book, and the spread of each null: median, SD, 5th and 95th percentile of CAGR), with T03's stored N4.9 percentiles as a historical reference. R4 has no pass mark. The circular-shift null is **not** rerun; T03's stands for its own window.
12. **Outcome map:**

| Pattern | Conclusion |
|---|---|
| C1 and C2 PASS, and N4.9 passes on this window | The result does not depend on the spell lengths. F-AA-S04 stays PROVISIONAL (in-sample, live window) but is better supported |
| PASS under N4.9, FAIL under N4.10 | The edge depends on the rule's particular spell lengths and where they fall |
| FAIL under both | No timing edge over chance for these books on this window |
| a V gate fails | Nothing is read. Fix and rerun as a new run directory |

13. **Which null decides.** For T06's verdict, N4.10. T03's N4.9 verdict (on its own window) is not changed. If the two nulls disagree on this window, both are reported and F-AA-S04's status note says so.
14. **Multiplicity.** One rule, no grid. N4.10 is the third null applied to this rule (N4.9, circular shift, N4.10), declared here; T06 alone cannot upgrade F-AA-S04.
15. **Expectation, declared before any run:** no basis for a direction. A draw can put a long spell on a rally, so the null's spread is probably wider than N4.9's and the rule's percentile may move either way. The pass mark stays 90 whatever the spread.
16. **Disclosures (go in §2):** the bounds were chosen after seeing T03's draw 445; the rule has been seen; the decisions before 2021-11 are a production backfill; the data caveats listed under Context; the 2026-08-24 → 2026-10-22 weeks add almost no evidence about timing.

---

## Step 1 — Pre-Registration (T06.md §1–§3, `check_prereg.py`, `TRACKER.md`)

**Goal:** write and freeze the pre-registration before any engine or verifier code. Fork T03.md's structure.

**File:** `AA/tests/T06/T06.md`

### Before writing (the data boundary, in order)
1. `python data/check_approved_data.py` must exit 0. Record `APPROVED_DATA.md`'s "As of" date and the through-date and sha256 prefix of every file the test will read, in §3's data table.
2. Compute, from the approved Master files and D17's calendar only, the **spell counts** on the new series for each book and for the live window: first state, k_in, k_out, S_in, S_out, longest in- and out-spell, round trips. Counts only, **no return of any kind** (T03's precedent). Put them in §2's "What was already known" and fix HI_in and HI_out from them.
3. Check feasibility for every window and state: 2·k ≤ S ≤ HI·k. If it fails, stop and ask Manu; do not change the bounds.

### §1 — Idea and references
- One sentence: "Holding the parent only when the three indices are all BUY chooses *when* better than random timings that keep the rule's switch count and total weeks invested but may use any spell lengths, on the latest approved data."
- Origin: T03 draw 445; N4.9 holds the lengths. Decision it changes: whether F-AA-S04 rests on the rule's particular spell lengths. What is known: T03's results, F-AA-S04, F-AA-M02. References: T03.md, `AGENT.md` N4.9.
- What this test is NOT asking: a different rule, a different sleeve, whether the rule beats holding the parent.

### §2 — Hypotheses and criteria
- H1 (timing), H2 (protection) as T03; N4.10 as in Rule item 4 with its **table** (dimension, randomised or held, how, measured in §4.0): timing of spells **randomised**; spell lengths **randomised within [2, HI_in] / [2, HI_out]**; total weeks invested **held** (identical, checked); spell count and first state **held**; sessions invested **not held exactly** (reported); book, calendar, sleeve, cost, execution **held**. N4.9 as in T03.
- Statistic, unit, percentile and p-value definitions, pass mark, criteria C1 and C2, validity gates V1–V5, reportability gate, robustness R1–R4, multiplicity, outcome map, expectation and disclosures: Rule items 8–16.

### §3 — Methodology
- Data table as under Context (path, through, sha256 prefix, data-review ID and verdict). Construction steps 1–10 as T03 §3 with the new file names and window end; step 11 replaced by the two nulls of Rule items 3 and 4 (the DP stated, with a worked small example); step 12 (MDE) as T03.
- **Plain-words section** (AGENT.md task 5 item 13): how one N4.10 draw is made, with the first 20 weeks of a real, an N4.9 and an N4.10 series printed in §4.0a, and the in-spell lengths of the draw beside the rule's.
- Point-in-time, execution and cost, effective sample size and power: as T03 (the independent unit is the round trip).

### check_prereg.py
Fork T03's. Change the path constants. Verify the sha256 of §1–§3.

### Also create
`AA/tests/T06/TRACKER.md` (T05's format), `AA/tests/T06/logs/`.

### Handoff block (Step 1)

| Field | Value |
|---|---|
| **Depends on** | Nothing; `check_approved_data.py` must exit 0 |
| **Produces** | `AA/tests/T06/T06.md` (§1–§3 frozen, sha256 in the header), `check_prereg.py`, `TRACKER.md`, `logs/` |
| **Done when** | `python tests/T06/check_prereg.py` exits 0; TRACKER Step 1 → DONE |
| **Tracker update** | "Pre-registration frozen, sha256=<first 12 chars>. Spell counts: <per book>. Bounds: <HI_in>/<HI_out>." |

---

## Step 2 — Engine (`AA/analysis/t06_engine.py`, `AA/analysis/approved_data.py`)

**Goal:** a fork of T03's engine on the approved data, with both nulls.

### `AA/analysis/approved_data.py` (new, small)
Stdlib and pathlib only. Parses the APPROVED rows of `data/APPROVED_DATA.md` (the same table `check_approved_data.py` parses). `require(path)` returns the path if it is an `APPROVED` row and raises an error naming the row's status otherwise; `rows()` returns them with their through-date and sha256 prefix.

### `AA/analysis/t06_engine.py`: copy `t03_engine.py`, then change
1. **Paths.** Replace every hard-coded data path with its APPROVED row (Context, Data table). Every file the engine opens goes through `require()`; the engine writes `inputs.csv` from the rows and stops on a sha256 mismatch.
2. **End date.** `END = 2026-10-22` (D17's last session), read from the approved D17 files, not typed twice. `LIVE_START` unchanged. `V4_END = END`.
3. **Cash.** LBES extended covers the window, so the trailing-90-session accrual branch (reading E10) must not trigger; assert that no session is accrued, and record the first appended row's double-counted weekend accrual (≤ 0.02%, CLAUDE.md) in `audit.json`.
4. **Nulls.** `run_book` copy with the draw list N4.9 (`spell_shuffle`, unchanged) + N4.10 (below); no circular shifts. Save the states of every draw to `draw_states.npz`; write the extra `draws.csv` columns.
5. **N4.10 functions:** `count_table(k, S, lo, hi)` (the DP, Python ints; assert `n_ways > 0`); `draw_lengths(rng, k, S, lo, hi, table)` (Rule item 7); `free_length_draw(s, draw_id)` (k, S, first state from the series; `default_rng([6, draw_id])`; asserts length, sums and bounds). HI_in, HI_out are computed from the rule's own series (not typed).
6. `main()`: `--run`, `--draws`, `--quick`; evidence to `tests/T06/evidence/<run>/`; also writes `count_table.json`, `sampler_selftest.json`, `regression_t03.json`, and the audit's `v3` block.

### Self-checks the engine runs (V3, V4, V5; it writes the results and exits non-zero on failure)
- **V3 (nulls hold their table), every draw of both nulls:** length = the book's weeks; first state = the rule's; k_in and k_out equal the rule's; sum of in-lengths = S_in and of out-lengths = S_out (so weeks invested are identical); for N4.9, sorted lengths equal the rule's; for N4.10, every length within its bounds. Also `rule_in_support`.
- **V4 (regression to T03, on the overlap only):** (a) the weekly decision states equal `tests/T03/evidence/headline/decisions.csv` on every shared decision date (0 mismatches); (b) the strategy's and comparators' daily NAVs equal `tests/T03/evidence/headline/daily_nav.csv` up to **2026-08-07** (relative difference below 1e-12; after that T03 accrued cash at the 90-session rate and T06 reads the extended LBES, the same cut-off T04 used); (c) always-in against the published NAV within G0 over the whole window. N4.9 draws are **not** compared with T03's, since the series is longer.
- **V5 (sampler):** (a) small case k = 3, S = 12, bounds [2, 6]: enumerate every tuple, draw 200,000 samples, chi-square against equal frequencies, p > 0.001; (b) the production `n_ways` equals the inclusion–exclusion formula Σ_j (−1)^j C(k, j) C(S − k·lo − j·(hi − lo + 1) + k − 1, k − 1); (c) over the 2,000 draws the mean in-spell length is within 4 standard errors of S_in ÷ k_in (likewise out).

### Handoff block (Step 2)

| Field | Value |
|---|---|
| **Depends on** | Step 1 DONE |
| **Reads from prior steps** | `T06.md` §3; `TRACKER.md`; `APPROVED_DATA.md` |
| **Produces** | `AA/analysis/approved_data.py`, `AA/analysis/t06_engine.py` |
| **Done when** | `python analysis/t06_engine.py --run smoke --draws 20 --quick` exits 0, writes the evidence files above, and V3, V4, V5 pass; opening a non-approved file raises |
| **Tracker update** | "Engine written. V3/V4/V5 pass on smoke. n_ways SCMO_0003: in <N>, out <N>. Smoke OK." |

---

## Step 3 — Independent Verifier (`AA/analysis/verify_t06.py`)

**Goal:** an independent re-derivation, written from the spec **without reading `t06_engine.py`**. Imports nothing from the engine or any AA analysis module (not `t03_engine` or `approved_data` either). Style from `verify_t03.py`.

### Checks
1. **C-data (new):** parse `APPROVED_DATA.md` with its own code; every input path in `inputs.csv` is an APPROVED row, its sha256 prefix matches, and its through-date covers the window.
2. **C-dec / C-pit / C-nav0 / C-cost / C-comp / C-always-in / C-corrupt:** as `verify_t03.py`, on the new files and window (re-derive decisions from the raw Master files and the published calendar, 0-cost and costed NAVs, the comparators, always-in against the published NAV; a corrupted copy must exit non-zero).
3. **C-states (new):** for **every** draw of every book, window and null in `draw_states.npz`: weeks, first state, spell counts, sums per state, alternation, and for N4.10 the bounds; for N4.9 the sorted lengths. Compare with the `draws.csv` columns.
4. **C-draw-nav (new):** re-simulate the first 20 and 20 random draws per book and null from the saved states with the verifier's own simulator; end NAV within a relative 1e-9 of `draws.csv`, at each cost.
5. **C-count (new):** count the allowed N4.10 tuples with the inclusion–exclusion formula (not a DP) and compare with `count_table.json`.
6. **C-support (new):** the rule's own spell lengths lie within the bounds.
7. **C-percentile (new):** recompute each percentile and p from `draws.csv` and compare with `analysis.log` and the page's data.
8. It exits 0 only if rows were compared and none failed; writes `verify_t06.json` with the counts.

### Handoff block (Step 3)

| Field | Value |
|---|---|
| **Depends on** | Step 1 DONE (spec). Code does not need Step 2; the evidence it checks arrives at Step 5 |
| **Reads** | `T06.md` §3, this plan's evidence format, `APPROVED_DATA.md`, `verify_t03.py` for style |
| **Produces** | `AA/analysis/verify_t06.py` and `AA/tests/T06/logs/verifier_spec.md` (the spec it was written from) |
| **Done when** | `python -c "import verify_t06"` from `AA/analysis/` is clean |
| **Tracker update** | "Verifier written. N checks defined. Awaits Step 5 evidence." |

---

## Step 4 — Test scripts

Fork from T03's equivalents into `AA/tests/T06/`.

- **`analyse.py`:** percentiles per book and cost for C1, C2 and the secondary statistics, against N4.10 (deciding) and N4.9; R1–R3; **R4** (agreement of the nulls, the null spreads, T03's stored N4.9 percentiles as a historical reference); the MDE; writes `analysis.log`; exits non-zero if a gate failed.
- **`fill_writeup.py`:** copies `analysis.log` into T06.md §4. It **must leave §1–§3 byte-identical** (F-AA-M02; two bugs in T03's version deleted them twice). Run `check_prereg.py` straight after.
- **`report.py`:** forked from T03's. Sections: answer; data (with each file's through-date and the "As of" date of `APPROVED_DATA.md`, and the caveats); **one backtest end to end including one N4.10 draw** (the sampler's steps, the DP count for the first in-spell, the first 20 weeks of a real, an N4.9 and an N4.10 series); headline table for both nulls; per-book curves; **null histograms with N4.9 and N4.10 overlaid**; the spell-length distributions of the draws against the rule's; the highest-return N4.10 draw against the rule (regime chart, held/randomised table); robustness; power; definitions. **Every chart hoverable** (AGENT.md R10). The hover arrays come from the same arrays that draw the chart.
- **`check_page.py`:** forked from T03's; re-derives every number, date and every hover array from the evidence.
- **`rerun_draw.py`:** `--book --type {N4.9,N4.10} --id --cost --window`: rebuilds a draw from its id and compares with `draws.csv` and `draw_states.npz` (exit 0 only if equal to 1e-12 and the states match).
- **`run.sh`:**
```bash
#!/usr/bin/env bash
# Regenerate every T06 artefact from the approved data. Run from AA/:  bash tests/T06/run.sh
set -euo pipefail
python data/check_approved_data.py     # the data on disk is the data Manu approved; non-zero = stop and ask
python tests/T06/check_prereg.py
python analysis/t06_engine.py --run headline
python analysis/verify_t06.py
python tests/T06/analyse.py
python tests/T06/fill_writeup.py
python tests/T06/report.py             # reads the best draw's states straight from draw_states.npz
python tests/T06/check_page.py
python tests/T06/check_prereg.py
```

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

Runs the data check, the pre-registration check, the engine (2,000 draws of each null × 4 books × 3 costs, plus LIQUIDCASE and the live window; no circular shifts; measure the time in the Step 2 smoke run), the verifier, the analysis, the write-up fill, the report and the page check.

**What to verify after the run:**
- `check_approved_data.py` exits 0; all gates V1–V5 pass; `check_page.py` reports 0 failures;
- every N4.10 draw has the book's spell counts and sums; N4.9 draws have the rule's sorted lengths;
- V4: decisions equal T03's on the overlap; NAVs equal T03's to 2026-08-07;
- the spread of N4.10's CAGR against N4.9's (printed in R4); no NaN or impossible values;
- `rerun_draw.py` reproduces the highest-CAGR draw of each null;
- §1–§3 unchanged (`check_prereg.py`).

### Handoff block (Step 5)

| Field | Value |
|---|---|
| **Depends on** | Steps 2, 3 and 4 ALL DONE |
| **Produces** | `AA/tests/T06/evidence/headline/`, T06.md §4, `evidence/report.html` |
| **Done when** | the pipeline exits 0 and all gates pass |
| **Tracker update** | "Pipeline OK. V1–V5 PASS. C1 percentiles (N4.10): <4 numbers>; C2: <4 numbers>. check_page: N checks, 0 failures." |

---

## Step 6 — Results and close

1. **Read `analysis.log`.** C1 and C2 PASS or FAIL against N4.10; the N4.9 percentiles beside them; R1–R3; R4.
2. **Fill T06.md §5–§8.** §5 findings with IDs taken from `AA/CLAUDE.md`'s counter **at the time of closing** (T05 may take F-AA-S06 and F-AA-M05 first; do not assume them). Expected entries: a strategy finding on whether F-AA-S04 survives free lengths on the latest data (updates S04's status note, does not replace it); a **method finding on N4.9's weeks-versus-sessions wording** (the table says "fraction of sessions invested" held; the gate V3 holds invested weeks; draw 445 differs by 4 of 1,884 sessions); and, if it applies, a data finding on the cash caveats. §6 discussion; §7 verdict per hypothesis; §8 next steps.
3. **Add N4.10 to `AGENT.md`:** a new family entry after N4.9 ("Random timing with free spell lengths": recipe, what it holds and breaks, the exact sampler, when to use it beside N4.9), a row in "Choosing among them", and a dated row in the revision history.
4. **Update `AA/CLAUDE.md`:** current test, the finding counter, a pointer to T06's page. `APPROVED_DATA.md` is **not** edited by this test (no data was refreshed).
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

1. **Stop and ask Manu** if the approved data is stale for the window, an input is missing or `PENDING`, a sha256 does not match, or a window cannot satisfy feasibility. Do not work around it.
2. **SCMO_0007 has 399 weeks** (it starts 2019-01-04). Its S values come from its own series; its draws use the same seeds but are not identical to the other three books'. Books with identical series have identical draws.
3. **The last decision week is partial** (2026-10-22 is a Thursday): the decision on the last D17 session is made but not traded.
4. **The live window's first spell is partial** (it starts mid-spell). It is a spell like any other, with the bounds applied; check it against HI_out.
5. **Feasibility:** for each window and state, 2·k ≤ S ≤ HI·k (Step 1, item 3). If it fails, the window is NOT REPORTABLE; do not change the bounds.
6. **A draw can equal the rule exactly** or equal an N4.9 draw; both are allowed and count as ties or draws as usual.
7. **Sessions invested differs by draw.** Record it; do not hold it.
8. **Cash:** the extended LBES covers the window; the trailing-90-session branch must not trigger. Disclose the source and richness caveats (Context).
9. **Seeds:** N4.9 `[3, draw_id]` (T03's function, unchanged), N4.10 `[6, draw_id]`. Determinism: `rng.random()` plus a cumulative-sum search, never `choice`.
10. **`fill_writeup.py` must not touch §1–§3.**
11. **No data may be edited, extended or rebuilt** by this test.

---

## Statistical power note

The independent unit is still the rule's round trips (about 9; the exact count is registered in Step 1), identical across books, so "3 of 4" is a consistency check. Freeing the lengths widens the null's spread, so the MDE (2.8 × null SD) is probably larger than T03's. It is computed after the run, in §4.3, and printed beside every FAIL; the pass mark does not depend on it.

---

## Files to create or modify

| File | Action | Step |
|---|---|---|
| `AA/tests/T06/T06.md`, `check_prereg.py`, `TRACKER.md`, `logs/` | CREATE | 1 |
| `AA/analysis/approved_data.py`, `AA/analysis/t06_engine.py` | CREATE | 2 |
| `AA/analysis/verify_t06.py`, `AA/tests/T06/logs/verifier_spec.md` | CREATE | 3 |
| `AA/tests/T06/analyse.py`, `fill_writeup.py`, `report.py`, `check_page.py`, `rerun_draw.py`, `run.sh` | CREATE | 4 |
| `AA/tests/T06/evidence/headline/` | CREATED by the engine | 5 |
| `AA/tests/T06/T06.md` (§4–§8), `evidence/METHODS.md` | EDIT / CREATE | 5, 6 |
| `AGENT.md` (N4.10, choosing table, revision history) | EDIT | 6 |
| `AA/CLAUDE.md` | EDIT | 6 |

---

## Recommended agent groupings

**Option A (4 agents):** A = Step 1; then B = Step 2, C = Step 3, D = Step 4 in parallel; E = Step 5; F = Step 6.
**Option B (3 agents):** A = Step 1; B = Step 2; C = Steps 3 + 4 in parallel with B; D = Steps 5 + 6.
**Option C (2 agents):** A = Steps 1 + 2; B = Steps 3 + 4 + 5 + 6. The verifier agent must **not** read `t06_engine.py`, so Step 3 is best done by an agent that has not written Step 2.

### How to brief an agent
Point it to: (1) this plan (`PLAN_v2.md`), (2) `AA/tests/T06/TRACKER.md`, (3) `AA/CLAUDE.md` and **`AA/data/APPROVED_DATA.md`**, (4) the step number, (5) the T03 files to fork from. Template:

> Read the T06 plan at `AA/tests/T06/PLAN_v2.md`. Read `AA/CLAUDE.md` for repo conventions and finding counters, `AA/data/APPROVED_DATA.md` for the only data you may read (run `python data/check_approved_data.py`; if anything is stale, missing or unclear, stop and ask Manu), and `AGENT.md` R10 for the page rules (every chart hoverable). Read `AA/tests/T06/TRACKER.md`: if a step you depend on is not DONE, stop and tell me. You are responsible for **Step N**. Fork from the T03 files named in the plan. Write a step log to `AA/tests/T06/logs/step_N_log.md`, update the tracker, and report back with: files created or changed (full paths), key results, open issues.
