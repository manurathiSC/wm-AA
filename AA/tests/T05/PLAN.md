# T05 Plan — Monthly stock filter review during SELL

## Multi-Agent Handoff Design

### Dependency graph

```
Step 1 (Pre-Reg) ──┬──→ Step 2 (Engine code)
                   ├──→ Step 3 (Verifier code)       ← evidence format defined below
                   └──→ Step 4 (Test scripts)         ← evidence format defined below

Step 2 + 3 + 4 ──→ Step 5 (Run pipeline) ──→ Step 6 (Fill results + Report + CLAUDE.md)
```

| Parallelism | Steps |
|---|---|
| **Must be first** | Step 1 — pre-registration frozen before any engine/verifier code |
| **Fully parallel** | Steps 2, 3, 4 — all depend only on Step 1; evidence format is defined in this plan so the verifier and test scripts do not need the engine code to be written first |
| **Sequential gate** | Step 5 cannot start until Steps 2, 3, and 4 are ALL DONE |
| **Strictly sequential** | Step 5 → Step 6 (results consume the pipeline output) |

### Evidence format (shared contract for Steps 2, 3, 4)

All files written to `AA/tests/T05/evidence/<run>/`. The format is T04's with one addition (`review` column):

| File | Columns / contents |
|---|---|
| `decisions.csv` | `j, decision_date, trade_session, state, basket, review` — `review` (bool) is True at monthly review dates and forced BUY→SELL reviews; **new column vs T04** |
| `indicators.csv` | `j, decision_date, indicator, stock_col, passes` — same as T04 |
| `selections.csv` | `j, decision_date, indicator, stock_col, selected, k, review_j` — `review_j` is the review date this selection came from (= j if review, else the most recent review j); **new column vs T04** |
| `trades.csv` | `session, trigger, cost_bps, stock_col, units_before, units_after, fill_price, traded_value` — same as T04 |
| `daily_nav.csv` | `session, indicator, cost_bps, nav` — same as T04 |
| `stats.csv` | `indicator, cost_bps, metric, value` — same as T04 (CAGR, max_dd, vol, ulcer, days_below_10pct, longest_underwater, fraction_invested, n_trades, n_reviews) plus `n_reviews` |
| `draws.csv` | `indicator, cost_bps, draw_id, metric, value` — same as T04 |
| `g_engine.csv` | `metric, engine, published, gap` — same as T04 |
| `audit.json` | sha256 of inputs, parameters, run timestamp, version — same as T04 with `review_mask_count` added |
| `inputs.csv` | `key, path, sha256` — same as T04 |

### Tracker file: `AA/tests/T05/TRACKER.md`

Every agent MUST read this file before starting work on its step. After completing a step, the agent MUST update the tracker. Format:

```markdown
# T05 Progress Tracker

| Step | Status | Blocked by | Agent / Date | Output summary |
|---|---|---|---|---|
| 1 | NOT_STARTED | — | — | — |
| 2 | NOT_STARTED | 1 | — | — |
| 3 | NOT_STARTED | 1 | — | — |
| 4 | NOT_STARTED | 1 | — | — |
| 5 | NOT_STARTED | 2, 3, 4 | — | — |
| 6 | NOT_STARTED | 5 | — | — |

## Step-level notes
(Agents append notes here when completing a step.)

## Files created or modified
(Agents append here after completing a step. One section per step, with full paths.)

### Step 1
(pending)

### Step 2
(pending)

### Step 3
(pending)

### Step 4
(pending)

### Step 5
(pending)

### Step 6
(pending)
```

**Status values:** `NOT_STARTED` → `IN_PROGRESS` → `DONE` (or `DONE_WITH_NOTES`).

**Rules for agents:**
1. Before starting: read TRACKER.md. If your step's "Blocked by" column lists a step that is not DONE or DONE_WITH_NOTES, STOP and tell the user.
2. Set your step to IN_PROGRESS with date.
3. On completion: set to DONE, fill "Output summary" with a one-line result, and append a note under "Step-level notes".
4. If you discover something that affects a downstream step, append a warning prefixed with `⚠ AFFECTS STEP X:`.
5. **Logging:** Write a step log file at `AA/tests/T05/logs/step_<N>_log.md`.
6. **Final report:** When done, report back with: files created/modified (full paths), key results, open issues.
7. **No silent failures.** Document and report any gate failures or unexpected results.

### Step-specific agent briefing

Each step below has a **Handoff block** at the end. The agent for a step should read: (1) the Context section, (2) its own step, (3) the Evidence format section above, (4) the Tracker. That's sufficient.

---

## Context

**What T04 showed.** T04 tested whether a stock-level filter during weekly SELL decisions keeps stocks better than a random same-size pick. Result: only I4 (200-day SMA) passed C1 (percentile 98.3), but the edge was mostly lower turnover — the null re-drew every week and traded far more. F-AA-S05 NOT ESTABLISHED; F-AA-M03 (null does not hold turnover); F-AA-M04 (verifier spec ambiguity, fixed).

**What T05 changes.** Monthly filter review during SELL instead of weekly. This naturally reduces both the strategy's and the null's turnover, shrinking the turnover gap that confounded T04.

**Key files from T04 (to fork from):**
- `AA/analysis/t04_engine.py` — the engine (~620 lines)
- `AA/analysis/verify_t04.py` — the independent verifier (~1200 lines)
- `AA/tests/T04/T04.md` — the write-up (structure template for T05.md)
- `AA/tests/T04/analyse.py` — analysis script
- `AA/tests/T04/fill_writeup.py` — fills §4 from analysis.log
- `AA/tests/T04/report.py` — HTML results page
- `AA/tests/T04/check_prereg.py` — §1-§3 sha256 check
- `AA/tests/T04/run.sh` — pipeline script

**Data (same as T04, no new data review needed):**
- D03: Master signals (Nifty100, MC100, SC100) — frozen + extended to 2026-10-30
- D05: Rebalance history (basket availableDates)
- D09: GOLDBEES OHLC (extended to 2026-11-04)
- D11: LBES cash level (extended to 2026-11-05)
- D17: Published parent NAVs (to 2026-10-22)
- D18: Per-parent OHLC (to 2026-11-04)
- Holdings weight matrix, price corrections (F-AA-D14)

**Repo conventions:** See `AA/CLAUDE.md`. Finding IDs: next free are F-AA-S06, F-AA-M05, F-AA-D16.

---

## T05 Rule (all 9 points — the test's complete specification)

1. **Regime check: weekly** — at the last session of each ISO week, read the three Master signals (Nifty100, MC100, SC100). BUY iff all three BUY, else SELL. Same as T04.
2. **Stock filter review: monthly** — during ongoing SELL, re-evaluate the indicator only at the last weekly decision of each calendar month.
3. **Forced review at BUY→SELL transition** — when the regime first flips to SELL, apply the filter immediately at that weekly decision (even if not month-end). Next review at the next month-end.
4. **SELL→BUY exit** — immediately go fully into equities (the basket in force at `bk.basket_at[t]`, at that basket's normalised weights). The BUY switch overrides the monthly cadence.
5. **Frozen kept set** — between monthly reviews during SELL, the kept set doesn't change. Stocks that passed at the last review stay; the rest stays in the sleeve.
6. **Basket changes during SELL** — the frozen indicator pass set (basket-independent) is intersected with the new basket's stocks. Same intersection logic as T04.
7. **Indicators** — same five as T04: I1 50-day EMA, I2 200-day EMA, I3 50-day SMA, I4 200-day SMA, I5 weekly SuperTrend. Bonferroni α/5 = 0.02, pass mark 98th percentile.
8. **Null (N_sel)** — re-draw only at the same review dates (monthly + forced). The null's k = the indicator's k at each review. Between reviews, the null's kept set is also frozen. Random values drawn from `u[rj]` (the review date's row), not `u[j]`.
9. **Everything else** — same parent (SCMO_0003), window (2019-01-02 → 2026-11-04), costs (0, 20.8, 50 bps), sleeve (50/50 GOLDBEES + LBES cash), 2,000 draws, R1-R5 robustness, V1-V5 validity gates.

---

## Step 1 — Pre-Registration (T05.md §1-§3 + check_prereg.py)

**Goal:** Write and freeze the pre-registration before any engine or verifier code. Fork from T04.md's structure.

**File:** `AA/tests/T05/T05.md`

### §1 — Idea and references
- One sentence: "With monthly filter reviews during SELL (not weekly), does a stock-level indicator keep stocks better than a random same-size pick drawn at the same monthly cadence?"
- Origin: T04 found the after-cost edge was mostly lower turnover (F-AA-M03); monthly reviews reduce both sides' turnover, isolating the selection signal from the turnover confound.
- What decision it changes: whether to use a monthly stock filter in production, or stay fully defensive in SELL.
- What is already known: T04's results (F-AA-S05 NOT ESTABLISHED, F-AA-M03, F-AA-M04), T03's regime timing (F-AA-S04 PROVISIONAL).
- References: T04.md, T03.md.

### §2 — Hypotheses and criteria
- **H1_i (selection):** Indicator i's monthly filter earns more (CAGR) than a random same-size monthly pick. Five hypotheses (i = 1..5).
- **H2_i (protection):** Indicator i's monthly filter has a shallower worst fall (max drawdown) than a random same-size monthly pick.
- **Null (N_sel):** Random draw of k stocks (k = indicator's count) from the basket at each review date only. Between reviews, the null's set is frozen. 2,000 seeded draws per indicator.
- **Pass marks:** Bonferroni α/5 = 0.02 → 98th percentile for each indicator.
- **Validity gates V1-V5:** Same as T04 (adapted: V3 checks k at review dates, not every SELL decision).
- **Robustness R1-R5:** R1 (0 bps), R2 (50 bps), R3 (max DD), R4 (Ulcer), R5 (best-of-sweep: does max(percentile across i=1..5) exceed 98th percentile of the same max under the null?).

### §3 — Methodology
- Same data files as T04 (extended files). Same parent (SCMO_0003), same window.
- The monthly review / frozen-set mechanics as specified in the T05 Rule above.
- Construction steps: fork from T04, with decision dates unchanged (weekly), review_mask added.
- Plain-words walkthrough adapted for the monthly cadence.
- Known contaminants: same as T04, plus: fewer filter decisions (~50-60 vs ~210) → wider null spread → larger MDE. The turnover confound (F-AA-M03) is reduced but may not be eliminated.

### check_prereg.py
- Fork from T04's `check_prereg.py`. Change path constants from T04 to T05. Verify sha256 of §1-§3.

### Also create
- `AA/tests/T05/` directory
- `AA/tests/T05/TRACKER.md` (using the format above)
- `AA/tests/T05/logs/` directory

### Handoff block (Step 1)

| Field | Value |
|---|---|
| **Depends on** | Nothing — can start immediately |
| **Produces** | `AA/tests/T05/T05.md` (§1-§3 frozen, sha256 in header); `AA/tests/T05/check_prereg.py`; `AA/tests/T05/TRACKER.md`; `AA/tests/T05/logs/` |
| **Done when** | T05.md §1-§3 written and frozen (sha256 recorded in header). `python tests/T05/check_prereg.py` exits 0. TRACKER.md created with Step 1 → DONE. |
| **Tracker update** | Set Step 1 → DONE. Output summary: "Pre-registration frozen, sha256=<first 12 chars>". |

---

## Step 2 — Engine (`AA/analysis/t05_engine.py`)

**Goal:** Fork t04_engine.py and implement the monthly review logic.

**File:** `AA/analysis/t05_engine.py`

### Changes from T04

#### a) Constants
- `T05 = AA / "tests" / "T05"` (was T04)
- Evidence goes to `tests/T05/evidence/<run>/`

#### b) `_review_mask(dec_dates, state)` — new function

Compute which weekly decisions are filter review dates:

```python
def _review_mask(dec_dates, state):
    """True at monthly review dates and BUY→SELL forced reviews."""
    dates = pd.to_datetime(dec_dates)
    n = len(dates)
    mask = np.zeros(n, dtype=bool)
    
    # Monthly: last decision of each (year, month)
    ym = dates.to_period("M")
    for p in ym.unique():
        idxs = np.flatnonzero(ym == p)
        mask[idxs[-1]] = True
    
    # Forced: first SELL of each SELL spell
    for j in range(n):
        if state[j] == 0:  # SELL
            if j == 0 or state[j-1] == 1:
                mask[j] = True
    
    return mask
```

The review_mask is passed to `build_events` and stored in `decisions.csv`.

#### c) `build_events` — frozen kept set between reviews

Replace T04's `tvec(j, b)` logic. Currently calls `prov(j, b)` at every SELL decision. For T05:

```python
def build_events(bk, dec_idx, state, prov, review_mask, every=False, scale=1.0):
    # ... setup same as T04 ...
    last_review_j = None
    
    def tvec(j, b):
        nonlocal last_review_j
        w = bk.W[b]
        if state[j] == 1 or prov is None:
            # BUY: full basket
            last_review_j = None
            idx = bk.bn[b]
        elif review_mask[j]:
            # SELL + review date: evaluate the filter fresh
            last_review_j = j
            idx = prov(j, b)
        else:
            # SELL + frozen: reuse last review's indicator on today's basket
            if last_review_j is not None:
                idx = prov(last_review_j, b)
            else:
                idx = bk.bn[b]  # shouldn't happen with forced reviews
        v = np.zeros(N)
        v[idx] = w[idx] * scale
        return v, idx
```

#### d) `strategy_provider` modification

Cache the indicator pass mask per `j` (not per `(j, b)`), and always intersect with `bk.bn[b]` at call time. This way `prov(last_review_j, b)` correctly uses the review date's indicator values but the current basket:

```python
def strategy_provider(ind, i, dec_dates, bk):
    rows = [ind.qpos[pd.Timestamp(d)] for d in dec_dates]
    pass_cache = {}  # j → indicator-only pass set (all stocks, ignoring basket)
    def prov(j, b):
        if j not in pass_cache:
            pass_cache[j] = np.flatnonzero(ind.passes[i][rows[j]])
        return np.intersect1d(pass_cache[j], bk.bn[b])
    return prov
```

#### e) `null_provider` modification

The null re-draws only at review dates. Between reviews, it uses the same random values from the review date:

```python
def null_provider(bk, u, kc, review_mask):
    last_review_j = [None]
    cache = {}
    def prov(j, b):
        rj = j if review_mask[j] else last_review_j[0]
        if review_mask[j]:
            last_review_j[0] = j
        k = kc(rj, b)
        bn = bk.bn[b]
        if k == 0: return np.zeros(0, dtype=int)
        if k >= len(bn): return bn
        return bn[np.argsort(u[rj, bn], kind="stable")[:k]]
    return prov
```

#### f) Seed change

Salt: `[5, i+1, draw_id]` (was `[4, ...]` in T04). Makes T05 draws independent.

#### g) Evidence output

`decisions.csv` gets the `review` column. `selections.csv` gets the `review_j` column (the review date each selection traces back to). `stats.csv` includes `n_reviews`. `audit.json` includes `review_mask_count`.

#### h) `kcount` function

Returns the indicator's k at the **review date**, not the current decision. This is already handled by the provider calling `prov(last_review_j, b)`.

### Handoff block (Step 2)

| Field | Value |
|---|---|
| **Depends on** | Step 1 DONE (pre-registration must be frozen before engine code) |
| **Reads from prior steps** | `AA/tests/T05/T05.md` §3 for methodology. `AA/tests/T05/TRACKER.md` for status. |
| **Produces** | `AA/analysis/t05_engine.py` |
| **Done when** | Engine code written. A quick smoke test (`python analysis/t05_engine.py --run smoke --draws 2 --quick`) exits 0 and produces evidence files matching the format above. G-engine gate passes (always-in at 0 cost reproduces published NAV within G0 tolerance). |
| **Tracker update** | Set Step 2 → DONE. Output summary: "Engine written. G-engine: ±X.XX pp/yr. Review dates: N. Smoke test OK." |

---

## Step 3 — Independent Verifier (`AA/analysis/verify_t05.py`)

**Goal:** Fork verify_t04.py and adapt for T05's monthly review logic.

**File:** `AA/analysis/verify_t05.py`

**Imports nothing from t05_engine.py or any AA analysis module.** Reads raw files and the engine's evidence.

### Changes from T04's verifier

All of T04's checks carry over. Additional/modified checks:

1. **C-review (new):** Independently compute the review mask (monthly + forced) from the decision dates and states. Compare against the engine's `review` column in `decisions.csv`. Must be identical.

2. **C-sel (modified):** Verify that selections at non-review SELL dates trace back to the correct review date (the `review_j` column). Verify that the indicator pass set at non-review dates equals the pass set at `review_j` intersected with the current basket.

3. **C-frozen (new):** Between review dates during a SELL spell, verify that the indicator-only pass set (before basket intersection) does not change. Only the basket intersection may change (if a new basket became active).

4. **C-null-k (modified):** Verify that the null's k at non-review dates equals the indicator's k at the review date (not the current date).

5. **C-trades (modified):** Verify that the trade count is plausible (should be lower than T04's, since fewer rebalancing events).

6. All other checks unchanged: C-dec (decisions), C-ind (indicators), C-pit (point-in-time), C-nav0 (0-cost NAV), C-cost (costed NAV), C-null (null draws), C-comp (comparators), C-always-in (published NAV reproduction), C-corrupt (self-test).

### Handoff block (Step 3)

| Field | Value |
|---|---|
| **Depends on** | Step 1 DONE (needs the methodology spec in T05.md §3 to independently re-derive). Does NOT depend on Step 2 for code — only for the evidence files the verifier checks against, which are produced at Step 5 runtime. The verifier CODE can be written using the evidence format defined in this plan. |
| **Reads from prior steps** | `AA/tests/T05/T05.md` §3 methodology. Evidence format from this plan (above). T04's verifier at `AA/analysis/verify_t04.py` as the fork base. |
| **Produces** | `AA/analysis/verify_t05.py` |
| **Done when** | Verifier code written and syntactically valid (`python -c "import verify_t05"` from `AA/analysis/`). Cannot fully test until Step 5 produces evidence. |
| **Tracker update** | Set Step 3 → DONE. Output summary: "Verifier written. N checks defined (C-dec, C-review, C-frozen, ...). Awaits Step 5 evidence." |

---

## Step 4 — Test Scripts

**Goal:** Create the remaining test folder scripts. Fork from T04's equivalents.

### Files

#### `AA/tests/T05/analyse.py`
Fork from T04's `analyse.py`. Changes:
- Path constants: T05 instead of T04
- Add review count in the header output
- Print the review dates (first few and last few) for sanity
- Otherwise identical: percentile computation, R1-R5 robustness, R5 best-of-sweep

#### `AA/tests/T05/fill_writeup.py`
Fork from T04's `fill_writeup.py`. Change T04 → T05 path constants.

#### `AA/tests/T05/report.py`
Fork from T04's `report.py`. Changes:
- Path constants: T05 instead of T04
- Add a "Review dates" section showing the monthly + forced review schedule
- Add a "Reviews vs T04 decisions" comparison (count)
- Otherwise same structure: charts, tables, per-indicator detail

#### `AA/tests/T05/run.sh`
```bash
#!/usr/bin/env bash
# Regenerate every T05 artefact from the raw files. Run from AA/:  bash tests/T05/run.sh
set -euo pipefail
python tests/T05/check_prereg.py
python analysis/t05_engine.py --run headline --workers 12
python analysis/verify_t05.py
python tests/T05/analyse.py
python tests/T05/fill_writeup.py
python tests/T05/report.py
python tests/T05/check_prereg.py
```

### Handoff block (Step 4)

| Field | Value |
|---|---|
| **Depends on** | Step 1 DONE (check_prereg.py needs T05.md; analyse.py needs the evidence format; fill_writeup.py needs T05.md). Does NOT depend on Steps 2 or 3 for code — evidence format is defined in this plan. |
| **Reads from prior steps** | T04's test scripts as fork bases. Evidence format from this plan (above). |
| **Produces** | `AA/tests/T05/analyse.py`, `AA/tests/T05/fill_writeup.py`, `AA/tests/T05/report.py`, `AA/tests/T05/run.sh` |
| **Done when** | All scripts written and syntactically valid. Cannot fully test until Step 5 produces evidence. |
| **Tracker update** | Set Step 4 → DONE. Output summary: "Test scripts written: analyse.py, fill_writeup.py, report.py, run.sh." |

---

## Step 5 — Run Pipeline

**Goal:** Execute the full pipeline and verify all gates pass.

**Command:** `cd AA && bash tests/T05/run.sh`

This runs (in order):
1. `check_prereg.py` — §1-§3 hash unchanged
2. `t05_engine.py --run headline --workers 12` — strategy + 2,000 null draws × 5 indicators × 3 costs; V2-V5 gates
3. `verify_t05.py` — V1: independent re-derivation; all C-* checks
4. `analyse.py` — percentiles, R1-R5, analysis.log
5. `fill_writeup.py` — copies analysis.log into T05.md §4
6. `report.py` — evidence/headline/report.html
7. `check_prereg.py` — §1-§3 still unchanged

**Expected runtime:** ~5 minutes (same as T04; fewer review dates but same number of draws).

**What to verify after the run:**
- All gates pass (V1-V5)
- Number of review dates is ~50-60 (not ~210)
- Strategy trade count is lower than T04's
- Null trade count is also lower and closer to the strategy's
- No NaN or impossible values in stats.csv

### Handoff block (Step 5)

| Field | Value |
|---|---|
| **Depends on** | Steps 2, 3, and 4 ALL DONE |
| **Reads from prior steps** | All code from Steps 1-4. |
| **Produces** | `AA/tests/T05/evidence/headline/` (all evidence files); updated `AA/tests/T05/T05.md` §4 (via fill_writeup.py); `AA/tests/T05/evidence/headline/report.html` |
| **Done when** | Pipeline exits 0. All gates V1-V5 pass. Evidence files are complete. |
| **Tracker update** | Set Step 5 → DONE. Output summary: "Pipeline OK. V1-V5 PASS. Reviews: N. Headline at 20.8 bps: I1=X%, I2=X%, I3=X%, I4=X%, I5=X% (percentile). R5 best-of-sweep: X%." |

---

## Step 6 — Results & Close

**Goal:** Review results, fill remaining T05.md sections, and update CLAUDE.md.

### What to do

1. **Review the analyse.py output.** For each indicator at 20.8 bps:
   - C1 (CAGR percentile ≥ 98): PASS/FAIL
   - C2 (max DD percentile ≥ 98): PASS/FAIL
   - R5 (best-of-sweep): PASS/FAIL

2. **Fill T05.md §5-§8** (findings, discussion, verdict):
   - §5: Assign finding IDs (F-AA-S06+ for strategy, F-AA-M05+ for method)
   - §6: Discussion — compare with T04's results, note turnover gap change
   - §7: Verdict — ESTABLISHED / PROVISIONAL / NOT ESTABLISHED per hypothesis
   - §8: Next steps

3. **Update `AA/CLAUDE.md`:**
   - Change "Current test: T04" → "Current test: T05" (or mark T05 COMPLETE)
   - Bump finding counter to reflect any new F-AA-S/M/D IDs used

4. **Check pre-registration one final time:** `python tests/T05/check_prereg.py`

### Handoff block (Step 6)

| Field | Value |
|---|---|
| **Depends on** | Step 5 DONE |
| **Reads from prior steps** | `AA/tests/T05/evidence/headline/analysis.log`, `stats.csv`, `draws.csv`, `report.html`. T05.md (with §4 filled). TRACKER notes from all prior steps. |
| **Produces** | Updated `AA/tests/T05/T05.md` (§5-§8 filled); updated `AA/CLAUDE.md` |
| **Done when** | T05.md complete. CLAUDE.md updated. `check_prereg.py` still passes. |
| **Tracker update** | Set Step 6 → DONE. Output summary: "T05 COMPLETE. Verdict: <per hypothesis>. Findings: <IDs>." Mark T05 overall as COMPLETE in tracker header. |

---

## Key edge cases (all agents should be aware)

1. **A SELL spell shorter than one month:** The forced review at BUY→SELL is the only filter evaluation. The kept set is frozen for the entire spell.
2. **Monthly review coincides with a forced review:** Both flags are True — no conflict, same effect.
3. **First decision (2019-01-02 area) is SELL:** This is a forced review (first SELL).
4. **Last decision is not traded:** Same as T04.
5. **Basket change between reviews:** The frozen indicator pass set (basket-independent) is intersected with the new basket. No fresh indicator evaluation.
6. **Basket change ON a review date:** The review evaluates the indicator at the new basket. The new basket's stocks determine the intersection.

---

## Statistical power note

T04 had ~210 SELL decisions (weekly). T05 will have far fewer filter reviews:
- ~92 calendar months in the window × fraction in SELL ≈ ~40-50 monthly review dates
- Plus ~10 forced reviews at BUY→SELL transitions
- Total: ~50-60 filter reviews vs T04's ~210 SELL decisions

The effective independent unit is still the SELL spell (~10 spells), so the MDE is similar, but the null spread may widen (fewer re-draws = more variance per draw). Computed post-run in §4.3.

---

## Files to create or modify

| File | Action | Step |
|------|--------|------|
| `AA/tests/T05/T05.md` | CREATE | 1 |
| `AA/tests/T05/check_prereg.py` | CREATE | 1 |
| `AA/tests/T05/TRACKER.md` | CREATE | 1 |
| `AA/tests/T05/logs/` | CREATE dir | 1 |
| `AA/analysis/t05_engine.py` | CREATE | 2 |
| `AA/analysis/verify_t05.py` | CREATE | 3 |
| `AA/tests/T05/analyse.py` | CREATE | 4 |
| `AA/tests/T05/fill_writeup.py` | CREATE | 4 |
| `AA/tests/T05/report.py` | CREATE | 4 |
| `AA/tests/T05/run.sh` | CREATE | 4 |
| `AA/tests/T05/evidence/headline/` | CREATED by engine | 5 |
| `AA/tests/T05/T05.md` (§4-§8) | EDIT | 5+6 |
| `AA/CLAUDE.md` | EDIT | 6 |

---

## Recommended Agent Groupings

### Option A: Maximum parallelism (4 agents)

| Agent | Steps | Can start |
|---|---|---|
| Agent A | 1 (Pre-Registration) | Immediately |
| Agent B | 2 (Engine) | After A finishes |
| Agent C | 3 (Verifier) | After A finishes (parallel with B) |
| Agent D | 4 (Test scripts) | After A finishes (parallel with B and C) |
| *Consolidation* | — | Wait for B, C, D to all finish |
| Agent E | 5 (Run pipeline) | After B, C, D finish |
| Agent F | 6 (Results & Close) | After E finishes |

**Note:** Agents B, C, D run in parallel. This is the primary parallelization opportunity — all three fork from T04 code and depend only on Step 1's output (T05.md §3 methodology) and the evidence format defined in this plan.

### Option B: Balanced (3 agents)

| Agent | Steps | Can start |
|---|---|---|
| Agent A | 1 (Pre-Reg) | Immediately |
| Agent B | 2 + 3 (Engine + Verifier) | After A finishes |
| Agent C | 4 (Test scripts) | After A finishes (parallel with B) |
| *Consolidation* | — | Wait for B and C |
| Agent D | 5 + 6 (Run + Results) | After B and C finish |

### Option C: Minimal (2 agents, mostly sequential)

| Agent | Steps | Can start |
|---|---|---|
| Agent A | 1 + 2 + 3 (Pre-Reg + Engine + Verifier) | Immediately |
| Agent B | 4 + 5 + 6 (Scripts + Run + Results) | After A finishes |

### How to brief an agent

Point the agent to:
1. This plan file (for context + its step's specification + evidence format)
2. `AA/tests/T05/TRACKER.md` (for current status)
3. `AA/CLAUDE.md` (for repo conventions, data IDs, finding counters)
4. The specific step number(s) to execute
5. The T04 file(s) to fork from (named in each step)

**Example prompt for Step 1 (Pre-Registration):**

> Read the T05 plan at `<plan_path>`. Read `AA/CLAUDE.md` for repo conventions and finding counters. Read `AA/tests/T04/T04.md` for the write-up structure to fork from. You are responsible for **Step 1** (Pre-Registration). Create `AA/tests/T05/` directory, write `T05.md` §1-§3 following the plan's §1-§3 specification, create `check_prereg.py` (fork from T04's), create `TRACKER.md` using the format in the plan, and create `logs/` directory. Freeze §1-§3 by recording the sha256 in the header. Run `python tests/T05/check_prereg.py` to verify. Update the TRACKER when done. Report back with: all files created (full paths), the sha256, and any issues.

**Example prompt for Step 2 (Engine — parallel with Steps 3, 4):**

> Read the T05 plan at `<plan_path>`. Read `AA/CLAUDE.md`. Read `AA/tests/T05/TRACKER.md` — if Step 1 is not DONE, stop and tell me. You are responsible for **Step 2** (Engine). Fork `AA/analysis/t04_engine.py` into `AA/analysis/t05_engine.py` and implement the monthly review logic as specified in the plan (review_mask, frozen kept set in build_events, modified providers, seed salt [5,...], evidence format changes). Run a smoke test (`python analysis/t05_engine.py --run smoke --draws 2 --quick`). Write a step log to `AA/tests/T05/logs/step_2_log.md`. Update the TRACKER when done. Report back with: files created, G-engine gate result, review date count, smoke test result.

**Example prompt for Steps 3+4 (Verifier + Scripts — can be one agent, parallel with Step 2):**

> Read the T05 plan at `<plan_path>`. Read `AA/CLAUDE.md`. Read `AA/tests/T05/TRACKER.md` — if Step 1 is not DONE, stop and tell me. You are responsible for **Step 3** (Verifier) and **Step 4** (Test Scripts). Fork `AA/analysis/verify_t04.py` into `verify_t05.py`, adding C-review and C-frozen checks as described in the plan. Fork T04's test scripts (analyse.py, fill_writeup.py, report.py, run.sh) into `AA/tests/T05/`, adjusting path constants and adding review-related output. Use the evidence format defined in the plan. Write step logs. Update the TRACKER when done.

**Example prompt for Step 5 (Run — consolidation point):**

> Read the T05 plan at `<plan_path>`. Read `AA/tests/T05/TRACKER.md` — if Steps 2, 3, and 4 are not ALL DONE, stop and tell me. You are responsible for **Step 5** (Run Pipeline). Execute `cd AA && bash tests/T05/run.sh`. Verify: all gates V1-V5 pass, review date count is ~50-60, trade counts are lower than T04's. Write a step log. Update the TRACKER when done. Report back with: gate results, headline percentiles per indicator, R5 result, review count, any failures.
