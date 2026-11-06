# T03 Plan: Three-Index Switch with 50/50 GOLDBEES/Cash Sleeve

## Multi-Agent Handoff Design

### Dependency graph

```
Step 0 (Data Review) ──┐
                       ├──→ Step 2 (Pre-Reg) ──→ Step 3 (Engine) ──┬──→ Step 4 (Verifier)
Step 1 (Rebuild)    ───┘                                            └──→ Step 5+6 (Run+Nulls) ──→ Step 7 (Analyse) ──→ Step 8 (Report)
```

| Parallelism | Steps |
|---|---|
| **Fully parallel** | 0 and 1 — no shared inputs, no shared outputs |
| **Sequential** | 2 waits for 0 AND 1 |
| **Write-parallel, run-sequential** | 3 and 4 code can be WRITTEN after 2 is DONE, but 4 cannot RUN until 3's evidence exists. Similarly, 5+6 is a run of the Step 3 engine. |
| **Strictly sequential** | 5→6→7→8 (each consumes the prior's output) |

### Tracker file: `AA/tests/T03/TRACKER.md`

Every agent MUST read this file before starting work on its step. After completing a step, the agent MUST update the tracker. Format:

```markdown
# T03 Progress Tracker

| Step | Status | Blocked by | Agent / Date | Output summary |
|---|---|---|---|---|
| 0 | NOT_STARTED | — | — | — |
| 1 | LARGELY_DONE | — | — | 3/4 parents PASS G0; 0007 2021 gap open |
| 2 | NOT_STARTED | 0, 1 | — | — |
| 3 | NOT_STARTED | 2 | — | — |
| 4 | NOT_STARTED | 3 | — | — |
| 5 | NOT_STARTED | 3 | — | — |
| 6 | NOT_STARTED | 5 | — | — |
| 7 | NOT_STARTED | 5, 6 | — | — |
| 8 | NOT_STARTED | 7 | — | — |

## Step-level notes
(Agents append notes here when completing a step — decisions made, issues found, deviations from plan.)

## Files created or modified
(Agents append here after completing a step. One section per step, with full paths.)

### Step 0
(pending)

### Step 1
(pending)

...
```

**Status values:** `NOT_STARTED` → `IN_PROGRESS` → `DONE` (or `DONE_WITH_NOTES` if there's an open issue, like the 0007 gap).

**Rules for agents:**
1. Before starting: read TRACKER.md. If your step's "Blocked by" column lists a step that is not DONE or DONE_WITH_NOTES, STOP and tell the user.
2. Set your step to IN_PROGRESS with date.
3. On completion: set to DONE, fill "Output summary" with a one-line result, and append a note under "Step-level notes" describing what was done and any deviations.
4. If you discover something that affects a downstream step, append a warning under "Step-level notes" prefixed with `⚠ AFFECTS STEP X:`.
5. **Logging:** Write a step log file at `AA/tests/T03/logs/step_<N>_log.md` documenting:
   - What was done (commands run, scripts created, decisions made)
   - Any issues encountered and how they were resolved
   - Key numerical results (e.g. G0 gaps, check counts, CAGR values)
   - Deviations from the plan and why
   - `## Formulas used` — every metric formula used in this step (see Rule 8)
6. **Final report:** When done, report back to the user with:
   - A list of every file created or modified (full paths)
   - A list of every log or evidence file produced
   - The updated TRACKER.md status for the step(s)
   - Any open issues or warnings for downstream steps
   - Key results in a summary table (not just "see the log")
7. **No silent failures:** If a gate fails, a check doesn't pass, or a result looks unexpected, do NOT silently continue. Document it in the log, flag it in the tracker notes, and report it to the user explicitly.
8. **Formula verification and logging:** Before computing any derived metric, the agent MUST:
   - **List every formula** it will use in that step (present them to the user before running).
   - **Get user confirmation** that each formula is correct before proceeding with computation.
   - **Log every formula** in the step log under a `## Formulas used` section, with the exact expression and a plain-English description.

   Metrics that require this treatment include (but are not limited to):
   | Metric | Expected formula |
   |---|---|
   | CAGR | `(NAV_final / NAV_initial) ^ (252 / n_sessions) - 1` (annualised at 252 sessions/yr) |
   | Max drawdown | `max over t of (1 - NAV_t / running_peak_t)` |
   | Ulcer index | `sqrt(mean(drawdown_pct²))` over the full series |
   | Volatility | `std(daily_log_returns) × sqrt(252)` |
   | Percentile | `(worse + 0.5 × ties) / draws × 100` |
   | p-value | `(1 + at_least_as_good) / (draws + 1)` |
   | MDE | `2.8 × null_sd` (80% power, two-sided 5%) |
   | Tracking error | `std(daily_return_diff) × sqrt(252)` |
   | OHLC4 fill price | `(Open + High + Low + Close) / 4` |
   | Cost per side | `10.4 bps × traded_value` (20.8 bps round trip) |
   | LBES accrual | Trailing 90-session rate past file end (F-AA-D05) |
   | Supertrend band | `(H+L)/2 ± 2.0 × LW_mean(weekly_TR, 5)` (NOT standard ATR) |
   | Fraction invested | `sessions_in / total_sessions` |
   | Days ≥10% below peak | Count of sessions where `NAV_t < 0.9 × running_peak_t` |
   | Longest underwater | Max consecutive sessions where `NAV_t < running_peak_t` |

   If the agent introduces any formula not in this table, it MUST present it to the user for approval before computing. The step log's `## Formulas used` section serves as the audit trail — any downstream agent can check what upstream steps computed and how.

### Step-specific agent briefing

Each step below has a **Handoff block** at the end with:
- **Depends on:** which steps (and what specifically from them)
- **Produces:** files and artifacts the step creates
- **Done when:** concrete pass criteria
- **Tracker update:** what to write

The agent for a step should read: (1) the Context section, (2) its own step, (3) the Tracker. That's sufficient — it does not need to read other steps.

---

## Context

**What T01 showed and what carries over.** T01 (COMPLETE, 2026-10-01) tested whether a parent's own 65-day bottom-25% percentile can time weakness. All three hypotheses were falsified: the own-index momentum rule does not work. Several issues from T01 feed directly into T03's design:

| Issue | What it means for T03 |
|---|---|
| **F-AA-M01** (MDE 12-18 pp/yr per book) | T03 must compute its MDE before running and state what edge is detectable. Still only 4 books. |
| **F-AA-D01** (13 ISINs' Eikon histories stop at 2016-06-30) | **Already handled.** `data/build_ohlc_file.py` reads directly from the Eikon DB and fills the dead ISINs via manual exports in `data/missing_rics/`. The per-parent OHLC availability reports (`data/holdings_matrix/*_ohlc_availability.csv`) show 0 missing and 0 carried sessions for every stock across all 4 parents. T03 should use the holdings_matrix OHLC files as its stock price source. |
| **F-AA-D09** (sources of LBES/D11 and published NAVs/D14 not recorded) | Still blocking the data review's DRAFT status. The new NAVs (parent_nav_2026-10-22) also lack a recorded source. At minimum, the reconciliation against parentIndices.csv (< 1e-11 bp) provides strong evidence. |
| **T01 traded at close, not OHLC4** | T01 used spliced parent index levels (close only). T03 holds individual stocks and trades at OHLC4, matching the published index convention. |
| **No published parent history before 2021** | Now resolved: parent_nav_2026-10-22 runs from 2019-01-02 (0007: 2019-01-04) to 2026-10-22. |
| **Parent rebuild accuracy** | parent_rebuild.py at `avail_ohlc4` convention reproduces published NAV within +0.13 pp/yr over 2021-26. Must be extended to 2019 and re-validated against the new NAVs. |

**What T03 tests.** The three-index supertrend switch is the core production rule for the four AA books. T03 tests it with a simplified 50/50 GOLDBEES/cash sleeve (no MAUc1 gold-timing split) over 2019-01-02 to 2026-08-21. The question: does the timing beat random timing at the same exposure?

**Honest framing.** The rule was chosen after seeing 2014-2026 results. This is not out-of-sample. The 0029 demo (87th/88th percentile in earlier descriptive work) has already been seen.

---

## Step 0 — Data Review Update

**Goal:** Add the new published parent NAVs to the data review and close the blockers relevant to T03.

**What to do:**

1. **Assign data ID D17** to `Historical Data/parent_nav_2026-10-22/SCMO_*.csv` and add it to `data/review_decisions.json`. SOURCE.md already provides sha256, date ranges, and reconciliation against parentIndices.csv.

2. **Assign data ID D18** to `data/holdings_matrix/*_ohlc.csv` (the per-parent OHLC files built by `build_ohlc_file.py`). These pull from Eikon DB + `missing_rics/` manual exports, cover 2014-07-01 to 2026-11-04, and have 0 missing / 0 carried sessions per the availability reports. This is the stock price source T03 will use, superseding the older D06/D07 parquets for T03's purposes.

3. **F-AA-D01 is resolved for T03.** The `build_ohlc_file.py` pipeline already fills the 13 dead ISINs from manual Eikon exports in `data/missing_rics/`. The availability reports confirm complete coverage. Record this in the data review: F-AA-D01 remains OPEN for D06 but does not affect D18.

4. **Special sessions.** The new NAV files skip the same Muhurat sessions that the OHLC files skip, and include the same Budget Saturdays. Verify by comparing D17 dates against D18 date coverage. No Kite fill needed if both sides skip the same dates.

5. **F-AA-D09.** Escalate to the user: until at least D17's source is recorded, it gets PASS WITH NOTES (strong reconciliation) rather than PASS. The LBES source (D11) remains FAIL. Record the status.

6. **Regenerate the data review:** run `python data/data_review.py --date <new_date>` and `python data/review_page.py --date <new_date>` after updating review_decisions.json.

**Files modified:** `data/review_decisions.json`, `data/DATA_REVIEW.md` (regenerated).

### Handoff block (Step 0)

| Field | Value |
|---|---|
| **Depends on** | Nothing — can start immediately |
| **Produces** | Updated `data/review_decisions.json` (with D17, D18, F-AA-D11, F-AA-D12); regenerated `data/DATA_REVIEW.md` |
| **Done when** | The review lists every T03 input (D03, D05, D09, D11, D17, D18) with a verdict. Each is PASS or PASS WITH NOTES, or FAIL with the impact quantified. |
| **Tracker update** | Set Step 0 → DONE. Output summary: list the verdicts (e.g. "D03 PASS, D05 PASS WITH NOTES, ..."). Append note with any FAIL verdicts and their quantified impact. |

---

## Step 1 — Parent Rebuild (G0) — LARGELY DONE

**Status:** The rebuild already exists at `data/parent_rebuild_hm/`, run by `data/parent_rebuild_hm.py` using the holdings_matrix OHLC files + the DB-sourced weight matrix. With `listed_weights_skip_dropped` variant:

| Parent | CAGR gap (2019→2026-10) | Worst calendar-year gap | G0 overall (±0.25) | G0 yearly (±0.5) |
|---|---|---|---|---|
| SCMO_0003 | +0.05 pp/yr | +0.43 pp (2022) | PASS | PASS |
| SCMO_0007 | +0.27 pp/yr | **+2.04 pp (2021)** | FAIL (barely) | **FAIL** |
| SCMO_0010 | +0.10 pp/yr | +0.45 pp (2019) | PASS | PASS |
| SCMO_0029 | +0.04 pp/yr | +0.19 pp (2019) | PASS | PASS |

**SCMO_0007's 2021 gap (+2.04 pp) is the one open issue.** It falls before 2021-11-01 and is noted as unexplained in PARENT_REBUILD_HM.md. This needs investigation: possibly a basket weight discrepancy or an OHLC data issue in that period.

**What remains for Step 1:**
1. **Investigate the 0007 2021 gap.** Identify which basket(s) and stock(s) contribute. Check whether the DB weight matrix disagrees with the rebalance history CSV for the 2021-06-17 or 2021-09-16 baskets (the skipped basket). Try isolating the gap to a single rebalance.
2. **Record findings F-AA-D11 and F-AA-D12** in `data/review_decisions.json`.
3. If the gap cannot be closed: accept it as a known contaminant in T03.md §3, and relax the G0 gate for 0007's 2021 calendar year with a documented reason.

**Inputs (all existing):**
- `data/holdings_matrix/<parent>_ohlc.csv` — stock OHLC (D18)
- `data/holdings_matrix/<parent>_holding_weight_matrix.csv` — target weights from DB
- `Historical Data/parent_nav_2026-10-22/SCMO_<parent>.csv` — published NAVs (D17)
- `data/parent_rebuild_hm.py` — the rebuild script
- `data/build_holding_weight_matrix.py` — weight matrix builder

### Handoff block (Step 1)

| Field | Value |
|---|---|
| **Depends on** | Nothing — can start immediately (runs parallel with Step 0) |
| **Produces** | Updated `data/parent_rebuild_hm/` results; possibly updated `parent_rebuild_hm.py`; F-AA-D11 and F-AA-D12 recorded in `data/review_decisions.json` |
| **Done when** | G0 gate documented for all 4 parents. Either the 0007 2021 gap is closed, or it is accepted as a known contaminant with a documented reason. |
| **Tracker update** | Set Step 1 → DONE or DONE_WITH_NOTES (if 0007 gap remains). Output summary: "G0: 0003 PASS, 0007 PASS/FAIL (gap=X), 0010 PASS, 0029 PASS". Append note explaining 0007 resolution or acceptance. If gap remains, add `⚠ AFFECTS STEP 2: 0007 2021 gap (+X pp) is a known contaminant — must be listed in T03.md §3.` |

---

## Step 2 — Pre-Registration (T03.md §1-§3)

**Goal:** Write and freeze the pre-registration before any engine run. Copy the structure from T01.md (the TEST_TEMPLATE at `wm-research/TEST_TEMPLATE.md` is the canonical source, but T01.md is the closest completed example).

**File:** `AA/tests/T03/T03.md`

### Section 1 — Idea and references
- One sentence: "Does the three-index switch — holding the parent only when Nifty 100, Midcap 100 and Smallcap 100 supertrend signals are all BUY — choose *when* better than chance?"
- Origin: The production rule from `final_strategy.py`, simplified to always 50/50 GOLDBEES/cash (removing the MAUc1 gold-timing split).
- Prior knowledge: This rule was chosen after seeing 2014-2026 results. The 0029 demo (index level, 87th/88th percentile) has already been seen. Full disclosure.
- References: `evidence/final_strategy/` (the rule on all 4 books with the full MAUc1 sleeve), `evidence/why_n100sc100/` (why the triple beats single-index rules).

### Section 2 — Hypotheses and null

**H1 (timing):** The rule's exits earn more than randomly timed exits at the same exposure. Judged on CAGR.
**H2 (protection):** The rule's worst fall is shallower than randomly timed exits. Judged on maximum drawdown.

**Primary null: N4.9 spell shuffle.**

| Dimension | Randomised / held | How |
|---|---|---|
| timing of spells relative to the market | **randomised** | in-spells shuffled independently, out-spells shuffled independently, re-interleaved starting in the rule's first state |
| fraction of sessions invested | held | same spell lengths |
| entries and exits count | held | same number of spells |
| spell lengths | held | same spells, reordered |
| book, prices, parent rebalances, cost | held | constant for the run |

Draws: if `m! × n!` (in-spells × out-spells) is ≤ 50,000, enumerate all; otherwise 2,000 seeded draws.

**Secondary null: circular shift** of the weekly in/out series, shifts from 8 to (n−8) weeks.

**Statistics:** CAGR and max drawdown, per book, per cost, separately against each null.

**Pass criteria:** To be set in the pre-registration (T03.md §2) before any run. The exact percentile threshold and the "k of 4 books" rule will be decided there, informed by the MDE estimate from the pilot circular shifts.

**Validity gates:**

| # | Gate | Pass condition |
|---|---|---|
| V1 | Independent verifier | `verify_t03.py` imports nothing from the engine. End NAV within 1e-9 for 0-cost strategy and every costed realisation |
| V2 | Point in time | Every decision reads signals ≤ decision date; every trade is on a later session |
| V3 | Null holds | For every draw: fraction invested identical, spell count identical, spell lengths identical |
| V4 | Always-in reproduces rebuild | Engine at 0 cost, always IN, reproduces the step-1 rebuild within the G0 tolerance |

**Reportability:** A book with fewer than 4 round trips is NOT REPORTABLE. Count spells before running.

**MDE:** Computed before running, from the expected null-CAGR spread (estimate from circular shifts as a pilot). State the smallest edge detectable at 80% power.

### Section 3 — Methodology

Full specification as given in the user's T03 spec: decision calendar (Friday close), entry/exit at next session's OHLC4, parent rebalances on availableDate at OHLC4, 10.4 bps per side, NAV starting at 1.000, statistics (CAGR at 252 sessions/yr, max DD, Ulcer, days ≥10% below peak, longest underwater, vol), comparators (hold parent, constant mix, 100% sleeve), and the null engine rules.

**Known contaminants** (from T01 + data review):

| Contaminant | Handling |
|---|---|
| F-AA-D01: dead ISINs in the old D06 parquet | Resolved by using D18 (holdings_matrix OHLC files), which include manual exports from `missing_rics/`. Availability reports show 0 missing sessions. |
| LBES ends 2026-08-09 | Accrued at trailing 90-session rate for the last ~9 sessions (F-AA-D05) |
| The rule was chosen after seeing 2014-2026 results | Disclosed; the null tests timing, not the choice of rule |
| The four books share one market | Not independent; "3 of 4" is a consistency check, not four independent tests |

**sha256 of T03.md §1-§3 recorded in the header before any run.**

### Handoff block (Step 2)

| Field | Value |
|---|---|
| **Depends on** | Step 0 DONE (needs data IDs D17, D18 and their verdicts for §3 methodology) AND Step 1 DONE or DONE_WITH_NOTES (needs G0 results for §3 known contaminants, and the rebuild accuracy numbers for the validity gate V4) |
| **Reads from prior steps** | From Step 0: data verdicts in `data/DATA_REVIEW.md`. From Step 1: G0 table in TRACKER notes and `data/parent_rebuild_hm/summary.csv`. Any `⚠ AFFECTS STEP 2` notes in the tracker. |
| **Produces** | `AA/tests/T03/T03.md` (§1-§3 frozen, sha256 in header); `AA/tests/T03/` directory created |
| **Done when** | T03.md §1-§3 written, sha256 recorded in the header. The pre-registration is frozen — no changes after this point. |
| **Tracker update** | Set Step 2 → DONE. Output summary: "Pre-registration frozen, sha256=<first 12 chars>". Append note listing hypotheses, null design chosen, and pass criteria. |

---

## Step 3 — Engine

**File:** `AA/analysis/t03_engine.py` (standalone, like own_momentum.py)

**Architecture: standalone engine, not wrapping final_strategy.py.** Rationale: final_strategy.py is coupled to segment_v2.py's Simulator/Step/ParentCtx/HybridTagger machinery (designed for per-stock tag-based rules, not a whole-book timing rule). T03 needs clean null-generation loops. Reuse the *logic* from final_strategy.py (OHLC4 fills, de-spiked GOLDBEES, three-index decision) but not the code.

**Reusable code to reference** (for implementation, not import):
- `final_strategy.py:despiked_goldbees()` — GOLDBEES spike-clipping logic
- `final_strategy.py:master()` — Master SIGN file reader
- `parent_rebuild.py` — basket switch logic at avail_ohlc4
- `own_momentum.py` — overall engine structure, evidence format, audit.json
- `data/holdings_matrix/*_ohlc.csv` — complete per-parent OHLC data (the engine's stock price source)
- `data/holdings_matrix/*_holding_weight_matrix.csv` — target weights at each rebalance
- `data/holdings_matrix/*_columns.csv` — stock → ISIN mapping

**Engine structure:**

```
INPUTS = {
    "ohlc":       "data/holdings_matrix/<parent>_ohlc.csv",         # D18: per-parent stock OHLC
    "weights":    "data/holdings_matrix/<parent>_holding_weight_matrix.csv",  # target weights
    "columns":    "data/holdings_matrix/<parent>_columns.csv",      # stock → ISIN mapping
    "baskets":    "Historical Data/frozen_2026-09-25/Rebalance_history/...", # D05: availableDate
    "signs_n100": "Historical Data/frozen_2026-09-25/Master/Master_Nifty100.xlsx",  # D03
    "signs_mc100":"Historical Data/frozen_2026-09-25/Master/Master_MC100.xlsx",
    "signs_sc100":"Historical Data/frozen_2026-09-25/Master/Master_SC100.xlsx",
    "gold":       "analysis/cache/why_gold_ohlc_eikon.parquet",     # D09: GOLDBEES OHLC
    "mauc1":      "analysis/evidence/final_strategy/mauc1/mauc1_daily_clean.csv",  # D12: for despiking
    "cash":       "Historical Data/LBES_Adjusted_Price_data_2026_08_10.csv",  # D11
    "pub_navs":   "Historical Data/parent_nav_2026-10-22/SCMO_<parent>.csv",  # D17
}

load_data()        → calendar, baskets_by_parent, stock_prices, gold_ohlc, 
                     gold_despiked_fill, cash_lbes, master_signs, published_navs

decisions(cal, signs, parent)
                   → weekly in/out series: for each Friday, all-three-BUY → 1, else → 0

spells(decision_series)
                   → list of in-spell lengths, list of out-spell lengths, first_state

simulate(decisions, parent_id, baskets, prices, gold_fill, gold_close, 
         cash_level, cal, cost_bps)
                   → daily_nav, ledger, positions_log
    
    Key: tracks stock units, gold units, cash units
    Handles parent rebalances DURING equity spells on availableDate
    Entry: sell sleeve at OHLC4, buy basket at OHLC4, cost on each side
    Exit: sell basket at OHLC4, buy 50% gold 50% cash, cost on each side
    While IN: parent rebalances at OHLC4 on availableDate, cost on traded value
    While OUT: sleeve drifts (gold and cash units fixed)
    NAV_t = cash_account + Σ(stock_units × close) + gold_units × gold_close + cash_units × LBES_level

spell_shuffle_draw(in_spells, out_spells, first_state, rng)
                   → new weekly decision series

circular_shift_draw(decisions, k)
                   → shifted weekly decision series

stats(daily_nav)   → CAGR, max_dd, peak_date, trough_date, ulcer, 
                     days_below_10pct, longest_underwater, vol

main()             → runs all 4 books × 3 costs × (strategy + always_in + sleeve + const_mix)
                     + all null draws. Writes evidence/.
```

**Critical detail — parent rebalances during equity spells:** When the book is "IN", a parent rebalance on `availableDate` triggers a basket switch at that session's OHLC4, with cost charged on the traded shares. When the book is "OUT" (in sleeve), the parent rebalance still updates which basket is current, so that re-entry buys the correct basket. The engine maintains `current_basket_idx` at all times.

**Gate (G-engine):** At 0 cost, with decision = always IN, the engine reproduces the step-1 rebuild within G0 tolerance (±0.25 pp/yr, ±0.5 pp/calendar-year).

**Output:** `AA/tests/T03/evidence/<run>/` — `spliced_inputs.csv`, `decisions.csv`, `realisations.csv` (strategy + all draws), `trades.csv`, `daily_nav.csv`, `positions.csv`, `audit.json`.

### Handoff block (Step 3)

| Field | Value |
|---|---|
| **Depends on** | Step 2 DONE (pre-registration must be frozen before engine code is written, to prevent the engine from influencing the hypotheses) |
| **Reads from prior steps** | From Step 2: `AA/tests/T03/T03.md` §3 methodology (decision calendar, fill rules, cost model, null design). From Step 1: `data/parent_rebuild_hm/summary.csv` for the G-engine validation gate. |
| **Produces** | `AA/analysis/t03_engine.py`; evidence directory structure at `AA/tests/T03/evidence/` |
| **Done when** | Engine runs without error on all 4 books. G-engine gate passes: always-in at 0 cost reproduces Step 1 rebuild within G0 tolerance. The engine also produces strategy NAVs and null draws, but those are validated in Steps 4-6. |
| **Tracker update** | Set Step 3 → DONE. Output summary: "Engine written. G-engine gate: 0003 ±X, 0007 ±X, 0010 ±X, 0029 ±X pp/yr". Note the evidence run directory name. |

**Note on Steps 3+4 parallelism:** The engine code (Step 3) and verifier code (Step 4) CAN be written by the same agent in one pass, since the verifier's structure depends on the engine's output format. If assigning to separate agents, the Step 4 agent must wait for Step 3 DONE to know the evidence file layout.

---

## Step 4 — Independent Verifier

**File:** `AA/analysis/verify_t03.py`

**Imports nothing from the engine or any AA analysis module.** Reads raw files and the engine's shipped evidence.

Re-derives independently:
1. The decision series (reads Master SIGN xlsx files, computes Friday reviews, determines all-three-BUY)
2. The 0-cost always-in NAV (its own basket-switch implementation)
3. The 0-cost strategy NAV (decision series + basket trading)
4. The costed strategy NAV (its own cost implementation)
5. Sample null draws (verify spell lengths and counts match, reproduce a few draws' NAVs)

**Must also fail on a deliberately corrupted copy** (flip decisions, scale NAVs).

**Gate:** V1 passes (0 failures, 0 missing rows, corrupted copy detected).

### Handoff block (Step 4)

| Field | Value |
|---|---|
| **Depends on** | Step 3 DONE (needs the engine's evidence output to verify against) |
| **Reads from prior steps** | From Step 3: evidence file layout (TRACKER note names the run directory). Raw input files (D03, D05, D09, D11, D17, D18) — same paths as the engine but read independently. |
| **Produces** | `AA/analysis/verify_t03.py`; verification log |
| **Done when** | V1 gate passes: 0 failures, 0 missing rows, corrupted copy detected. |
| **Tracker update** | Set Step 4 → DONE. Output summary: "V1 PASS: X checks, 0 failures, corruption detected". |

---

## Step 5 — Run

For each of 4 books × 3 costs (0, 20.8, 50 bps), produce:
- Strategy equity curve (daily NAV)
- Trade ledger
- Statistics table (CAGR, max DD, Ulcer, days ≥10% below peak, longest underwater, vol)
- Comparators: hold-parent (rebuilt + published), constant mix (at strategy's average exposure, rebalanced weekly), 100% sleeve

### Handoff block (Step 5)

| Field | Value |
|---|---|
| **Depends on** | Step 3 DONE (engine must exist and pass G-engine gate) |
| **Reads from prior steps** | Engine at `AA/analysis/t03_engine.py`. Pre-registration at `AA/tests/T03/T03.md` for cost levels and comparator definitions. |
| **Produces** | Evidence files: `daily_nav.csv`, `trades.csv`, `stats.csv`, comparator curves — all under `AA/tests/T03/evidence/<run>/` |
| **Done when** | All 4 books × 3 costs produce strategy + comparator curves. Stats table complete. |
| **Tracker update** | Set Step 5 → DONE. Output summary: "4 books × 3 costs run. Strategy CAGRs at 20.8bps: 0003=X, 0007=X, 0010=X, 0029=X". |

**Note on Steps 5+6:** Steps 5 and 6 are logically part of the same engine run (the engine's `main()` runs strategy + nulls together). They can be handled by one agent. If split, Step 6 needs Step 5's spell structure.

---

## Step 6 — Nulls

**Primary (N4.9 spell shuffle):**
1. Extract spell structure from the strategy's weekly in/out decisions.
2. Count in-spells (m) and out-spells (n).
3. If m! × n! ≤ 50,000: enumerate all orderings. Otherwise: 2,000 seeded draws (numpy default_rng with documented seed formula).
4. Each draw runs through the same engine with real stocks, real parent rebalances, real costs.
5. Record in `draws.csv`: draw_type, draw_id, seed/k, book, cost, CAGR, max_dd, vol, and all statistics.
6. Save all curves (parquet or compressed CSV).
7. `rerun_draw.py` reproduces any draw from its seed.

**Secondary (circular shift):**
- Shift the weekly in/out series by k for 8 ≤ k ≤ n−8.
- Each shift through the same engine.

**Power (computed before running):**
- Count round trips per book.
- Estimate null-CAGR spread from the circular shifts (a pilot).
- MDE = 2.8 × null_sd (80% power, two-sided 5%).

### Handoff block (Step 6)

| Field | Value |
|---|---|
| **Depends on** | Step 5 DONE (needs strategy's decision series to extract spell structure) |
| **Reads from prior steps** | Strategy decisions from `decisions.csv`. Engine at `AA/analysis/t03_engine.py`. |
| **Produces** | `draws.csv` (all null draw statistics), null curves (parquet/compressed), `rerun_draw.py`, MDE estimates |
| **Done when** | All draws complete (spell shuffle + circular shift). V3 gate passes: every draw has identical fraction invested, spell count, spell lengths as strategy. MDE computed per book. |
| **Tracker update** | Set Step 6 → DONE. Output summary: "Spell shuffle: m=X in-spells, n=X out-spells, Y draws per book. Circular shift: Z shifts. MDE per book: 0003=X, 0007=X, 0010=X, 0029=X pp/yr". |

---

## Step 7 — Analyse and Gate

**File:** `AA/tests/T03/analyse.py`

Reads only shipped evidence. Prints to stdout and `analysis.log`:

1. **Gates (§4.0):** V1-V4 pass/fail. Null-holds check (spell counts, fraction invested).
2. **Worked example (§4.0):** One real decision, one trade, NAV around the trade, one null draw with its ranking.
3. **Headline results (§4.1):** Per book per cost: strategy CAGR, null median, edge, percentile, p-value, draws. Same for max DD.
4. **Comparators (§4.2):** Hold parent (rebuilt + published), constant mix, 100% sleeve.
5. **MDE (§4.3):** Per book: round trips, null_sd, MDE, smallest edge detectable.
6. **Verdict (§4.4):** Per hypothesis per criterion: PASS/FAIL, with MDE beside each FAIL.

**Percentile:** `(worse + 0.5 × ties) / draws × 100`. p-value: `(1 + at_least_as_good) / (draws + 1)`.

**`fill_writeup.py`:** Copies analyse.py output verbatim into T03.md §4. No hand-typed numbers.

### Handoff block (Step 7)

| Field | Value |
|---|---|
| **Depends on** | Step 5 DONE AND Step 6 DONE (needs strategy evidence + all null draws) |
| **Reads from prior steps** | All evidence under `AA/tests/T03/evidence/<run>/`: `daily_nav.csv`, `draws.csv`, `stats.csv`, `trades.csv`. Pre-registration at `T03.md` for pass criteria. |
| **Produces** | `AA/tests/T03/analyse.py`, `AA/tests/T03/fill_writeup.py`, `analysis.log`, updated `T03.md` §4 |
| **Done when** | All gates (V1-V4) pass/fail documented. Headline results, comparators, MDE, and verdict printed. `fill_writeup.py` copies results into T03.md §4. |
| **Tracker update** | Set Step 7 → DONE. Output summary: "H1: PASS/FAIL (percentile=X). H2: PASS/FAIL (percentile=X). Gates: V1=PASS, V2=PASS, V3=PASS, V4=PASS". Append findings (F-AA-S04+, F-AA-M02+) if any. |

---

## Step 8 — Results Page and Check

**Files:**
- `AA/tests/T03/report.py` — generates `evidence/report.html` from evidence only, per R10 spec.
- `AA/tests/T03/check_page.py` — independent page checker, shares no code with any other script. Re-computes every number on the page from raw files. Prints checks count and failures. Exits non-zero on failure.
- `AA/tests/T03/evidence/METHODS.md` — companion methods document.

**Page structure (per R10):** Answer, data, one backtest end to end, headline, per-book detail, null distributions, definitions.

**Findings:** F-AA-S04 onward for strategy findings, F-AA-M02 onward for method findings.

### Handoff block (Step 8)

| Field | Value |
|---|---|
| **Depends on** | Step 7 DONE (needs analysis results and filled T03.md §4) |
| **Reads from prior steps** | All evidence under `AA/tests/T03/evidence/<run>/`. `T03.md` (now with §4). `analysis.log`. |
| **Produces** | `AA/tests/T03/report.py`, `AA/tests/T03/check_page.py`, `evidence/report.html`, `evidence/METHODS.md` |
| **Done when** | `report.py` generates the page. `check_page.py` re-computes every number from raw files and exits 0. |
| **Tracker update** | Set Step 8 → DONE. Output summary: "Report generated. check_page.py: X checks, 0 failures". Set T03 overall status to COMPLETE in tracker header. |

---

## Verification

1. **G0 (step 1):** Rebuild within ±0.25 pp/yr overall, ±0.5 pp per calendar year vs D17 published NAVs.
2. **V1 (step 4):** Independent verifier passes; corrupted copy detected.
3. **V2 (step 3):** Point-in-time assertions pass (signal ≤ decision date, trade > decision date).
4. **V3 (step 6):** Every null draw holds fraction invested, spell count, spell lengths identical to strategy.
5. **V4 (step 3):** Always-in at 0 cost reproduces the rebuild.
6. **check_page.py (step 8):** All checks pass, 0 failures.
7. **End-to-end:** Run `t03_engine.py`, `verify_t03.py`, `analyse.py`, `report.py`, `check_page.py` in sequence. All exit 0.

---

## Files to create or modify

| File | Action |
|---|---|
| `AA/tests/T03/TRACKER.md` | **New** — progress tracker for multi-agent handoff (create in Step 0 or Step 1, whichever runs first) |
| `AA/data/review_decisions.json` | Add D17, D18, F-AA-D11, F-AA-D12 entries |
| `AA/data/parent_rebuild_hm.py` | Already exists — investigate 0007 2021 gap only |
| `AA/tests/T03/T03.md` | **New** — pre-registration (copied from TEST_TEMPLATE, following T01 structure) |
| `AA/analysis/t03_engine.py` | **New** — standalone engine |
| `AA/analysis/verify_t03.py` | **New** — independent verifier |
| `AA/tests/T03/analyse.py` | **New** — analysis script |
| `AA/tests/T03/fill_writeup.py` | **New** — copy analysis.log into T03.md §4 |
| `AA/tests/T03/report.py` | **New** — results page generator |
| `AA/tests/T03/check_page.py` | **New** — independent page checker |
| `AA/tests/T03/run.sh` | **New** — regenerate all evidence |
| `AA/tests/T03/rerun_draw.py` | **New** — reproduce a single null draw |
| `AA/CLAUDE.md` | Update current test to T03, update finding counters |

---

## Recommended Agent Groupings

You can assign steps to agents in several ways. The constraint is the dependency graph above. Here are two options:

### Option A: Maximum parallelism (5 agents)

| Agent | Steps | Can start |
|---|---|---|
| Agent A | 0 (Data Review) | Immediately |
| Agent B | 1 (Rebuild investigation) | Immediately (parallel with A) |
| Agent C | 2 (Pre-Registration) | After A and B finish |
| Agent D | 3 + 4 + 5 + 6 (Engine + Verifier + Run + Nulls) | After C finishes |
| Agent E | 7 + 8 (Analyse + Report) | After D finishes |

### Option B: Fewer agents, natural groupings (3 agents)

| Agent | Steps | Can start |
|---|---|---|
| Agent A | 0 + 1 (Data + Rebuild) | Immediately |
| Agent B | 2 + 3 + 4 (Pre-Reg + Engine + Verifier) | After A finishes |
| Agent C | 5 + 6 + 7 + 8 (Run + Nulls + Analyse + Report) | After B finishes |

### How to brief an agent

Point the agent to:
1. This plan file (for context + its step's specification)
2. `AA/tests/T03/TRACKER.md` (for current status and prior step outputs)
3. `AA/CLAUDE.md` (for repo conventions, data IDs, finding counters)
4. The specific step number(s) to execute

Example prompt for Steps 0+1:

> Read the T03 plan at `<plan_path>`. Read `AA/CLAUDE.md` for repo conventions and finding counters. You are responsible for **Step 0** (Data Review Update) and **Step 1** (Parent Rebuild). These two steps have no dependencies — execute both. Create `AA/tests/T03/TRACKER.md` using the format in the plan, then update it as you complete each step. Write step logs to `AA/tests/T03/logs/step_0_log.md` and `step_1_log.md`. When done, report back with: all files created/modified (full paths), key results, and any open issues for downstream steps.

Example prompt for Step 3 (Engine):

> Read the T03 plan at `<plan_path>`. Read `AA/CLAUDE.md`. Read `AA/tests/T03/TRACKER.md` — if Step 2 is not DONE, stop and tell me. You are responsible for **Step 3** (Engine). Execute as specified in the plan. Write a step log to `AA/tests/T03/logs/step_3_log.md`. Update the TRACKER when done. Report back with: all files created/modified, G-engine gate results per parent, and the evidence run directory path.

---

## Backfill: Step 1 log (2026-11-05)

Step 1 finished before Rules 5 and 8 existed, so `AA/tests/T03/logs/step_1_log.md` is missing. Backfill it from facts already on disk (no new computation, no re-run).

**Write:** `AA/tests/T03/logs/step_1_log.md` (create `logs/`). Sections:
1. **What was done:** the 0007 2021 gap investigation, with the files it produced (`data/parent_rebuild_hm/gap_0007_2021_{daily,jumpday_attribution,weights_db_vs_csv,fixes,factor_sweep}.csv`, `g0_gate.csv`), `data/holdings_matrix/price_corrections.csv`, the `apply_corrections()` and `g0_gate()` additions to `data/parent_rebuild_hm.py`, and the F-AA-D11/D12/D14 entries in `data/review_decisions.json`, `AA/CLAUDE.md` and `PARENT_REBUILD_HM.md` updates.
2. **Issues and resolution:** Polyplex Rs 100 special dividend, ex-date 2021-02-17, -118 bp one-day gap, factor 811.20/911.20, 2021 gap +2.04 to +0.17 pp.
3. **Key results:** the G0 table from `g0_gate.csv`.
4. **Deviations:** (a) the step log and the Rule 8 formula sign-off were not done at the time (rules added later); (b) the Polyplex ex-date and Rs 100 amount came from a web search, not the DB (taken from the tracker note); (c) D18 files left unedited, the correction is applied on read.
5. **Formulas used** (read from `data/parent_rebuild_hm.py:73-152`), marked "backfilled, not yet user-confirmed":
   - CAGR = `(end/start) ** (1/yrs) - 1`, `yrs = calendar days / 365.25`
   - CAGR gap = `(model CAGR - published CAGR) * 100`, pp/yr
   - Calendar-year gap = `(model_end / model_prior_year_end - pub_end / pub_prior_year_end) * 100`, pp
   - Tracking error = `std(daily model return - daily published return) * sqrt(252) * 100`
   - Basket switch price = `(O+H+L+C)/4` on availableDate; shares = `V_switch * w / price`, weights renormalised over stocks with a price
   - Price correction = prices dated before `ex_date` multiplied by `factor` (911.20/811.20 = 1.123274)
   - G0 = `|CAGR gap| <= 0.25 pp/yr` and `max |calendar-year gap| <= 0.5 pp`

**Flag for the user to confirm (Rule 8):** Step 1 annualises CAGR over calendar days / 365.25, but Rule 8's table says `252 / n_sessions`. Both are defensible; T03.md §3 must pick one. Recommendation: keep 365.25 days for the G0 comparison (already run) and decide for the T03 statistics in Step 2.

**Also update:** TRACKER.md Step 1 row, add one line "log: `AA/tests/T03/logs/step_1_log.md` (backfilled 2026-11-05)" and a "Files created or modified" entry for Step 1 listing the files above (the tracker has no such section filled in).
