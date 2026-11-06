# T04 — Stock-level filter during SELL regime (SCMO_0003)

## Context

T03 (COMPLETE, 2026-11-05) proved the three-index supertrend switch times the parent's weak stretches better than chance (C1 PASS 3/4, C2 PASS 4/4; F-AA-S04 PROVISIONAL). Its strategy goes **fully** defensive during SELL — 50/50 GOLDBEES + cash.

T02 (descriptive, 2026-11-05) explored a refinement: during SELL, keep stocks whose close > 50-day EMA instead of going fully defensive. Results: 19.9% CAGR vs 21.6% for the full AA overlay (SCMO_0042). But T02 is not a proper test — no null analysis, no pre-registration, and it used external data from Wm-SellRegRes rather than the AA project's own validated holdings matrix (D18/D19). It also used 100% GOLDBEES instead of T03's 50/50 sleeve.

**T04 formalizes this**: during SELL regime, does a stock-level technical indicator select stocks worth keeping — earning more than a random selection of the same size? Five indicators are tested equally with Bonferroni correction.

---

## The question

**In one sentence.** During SELL regime weeks for SCMO_0003, does a technical indicator (EMA, SMA, or SuperTrend) identify stocks that outperform a random same-size selection from the basket?

**What this is NOT asking:**
- Whether the three-index switch times the market (T03 answered that)
- Whether partial equity during SELL beats full defensive (that is a comparator, not a null)
- Whether this generalises to the other three parents (SCMO_0003 only)

---

## Data sources

All from the AA project — no external dependencies (no Wm-SellRegRes).

| File | Purpose | Data-review ID |
|---|---|---|
| `data/holdings_matrix/SCMO_0003_ohlc.csv` | Stock daily OHLC → compute all 5 indicators + valuation | D18 |
| `data/holdings_matrix/SCMO_0003_holding_weight_matrix.csv` | Basket weights per rebalance | D19 |
| `data/holdings_matrix/SCMO_0003_columns.csv` | Column-to-ticker/ISIN map | D19 |
| `data/holdings_matrix/price_corrections.csv` | Polyplex correction (F-AA-D14) — applies to SCMO_0007 only, not 0003 | D18 |
| `Historical Data/parent_nav_2026-10-22/SCMO_0003.csv` | Published NAV (benchmark, V4 gate; ends 2026-10-22 — V4 scope limited to this range) | D17 |
| `Historical Data/extended_2026-10-30/Master/Master_{Nifty100,MC100,SC100}.xlsx` | Three-index regime signals (extended to 2026-10-30, verified vs frozen and production; manifest.json documents provenance) | D03 |
| `analysis/cache/why_gold_ohlc_eikon_extended_2026-11-04.parquet` | GOLDBEES OHLC (extended to 2026-11-04) | D09 |
| `analysis/evidence/final_strategy/mauc1/mauc1_daily_clean.csv` | MCX gold range (de-spike GOLDBEES fills) | D12 |
| `Historical Data/LBES_Adjusted_Price_data_2026_08_10_extended_2026-11-05.csv` | Cash level (LBES, extended to 2026-11-05) | D11 |

**Polyplex note (F-AA-D14):** SCMO_0003 holds Polyplex only from 2021-06-17 (after the 2021-02-17 ex-date). The correction in `price_corrections.csv` applies to SCMO_0007, not 0003. Back-adjusted prices in D18 are correct for indicator computation (continuous series) and post-ex-date fills. No special handling needed.

---

## Strategy rules

1. **Regime.** Same as T03: BUY iff Nifty 100, Midcap 100, and Smallcap 100 weekly supertrends (from Master files) are all BUY. Decision dates = T0 (2019-01-02) and the last D17 session of each ISO week. Window: 2019-01-02 to 2026-11-04.

2. **BUY regime.** Hold the full parent basket at rebalance weights. No indicator filtering. Identical to T03.

3. **SELL regime.** For each stock in the current basket, check the indicator on the decision date:
   - **Keep** stocks that pass the filter at their original rebalance weights.
   - **Exclude** stocks that fail (or have no indicator data). Their combined weight goes to the **defensive sleeve**: 50% GOLDBEES + 50% LBES cash (primary), matching T03.

4. **Execution.** A trade happens only when the target allocation changes (regime switch, indicator filter change, or parent rebalance). Trade on the **next D17 session** after the decision, at that session's OHLC4 fill price. GOLDBEES de-spiked (same method as T03). LBES at its level.

5. **Cost.** 0, 20.8 (primary), 50 bps round trip (10.4 bps per side on every value traded).

6. **Parent rebalances during SELL.** When the basket changes (new `availableDate` in D19), update the basket and re-apply the indicator filter. Trade at OHLC4 on the `availableDate` session, with cost. During BUY, parent rebalances follow T03's logic.

---

## Five indicators

All computed from `SCMO_0003_ohlc.csv` close prices. Indicator values are point-in-time: only closes on or before the decision date.

| # | Indicator | Keep if | Parameters |
|---|---|---|---|
| I1 | 50-day EMA | close > EMA₅₀ | k = 2/51; EMA₀ = SMA of first 50 closes; strict inequality |
| I2 | 200-day EMA | close > EMA₂₀₀ | k = 2/201; EMA₀ = SMA of first 200 closes; strict inequality |
| I3 | 50-day SMA | close > SMA₅₀ | arithmetic mean of last 50 closes; strict inequality |
| I4 | 200-day SMA | close > SMA₂₀₀ | arithmetic mean of last 200 closes; strict inequality |
| I5 | Weekly SuperTrend | SIGN = BUY | On the stock's own weekly OHLC candles; mul=2.0, lookback=5, linearly weighted ATR. Reimplement the desk engine self-contained (same algorithm as `analysis/supertrend.py`) |

**Edge cases:**
- Indicator not yet computable (insufficient history): stock is **excluded** (treated as filter-fail, weight goes to sleeve).
- Stock has no OHLC on the decision date: use the most recent close within 7 calendar days (forward-fill). If none, exclude.
- Indicator selects 0 stocks on a SELL date: entire basket weight goes to the sleeve (100% defensive that week). This draw contributes 0 selection information — reported.
- Indicator selects all stocks: 0% to sleeve (fully invested that week, same as BUY). Also reported.

---

## Null design: N_sel (selection shuffle)

**What is randomised.** On each SELL-regime decision date, *which* k stocks from the n available in the basket are kept, where k is the number the indicator selected on that date.

**What is held fixed:**
| Dimension | Held / randomised | How |
|---|---|---|
| Which stocks are selected on each SELL date | **randomised** | randomly pick k from n (uniform without replacement) |
| k (number selected) per SELL date | held | the indicator's actual count on each date |
| The regime series (BUY/SELL) | held | same decisions as the strategy |
| Weights of selected stocks | held | their original rebalance weights (not renormalised) |
| BUY-regime behaviour | held | full parent basket, identical |
| Parent rebalances, calendar, sleeve, cost, execution | held | constant |
| The sleeve's return path | **not matched** | different weeks have different gold/cash returns |

**Draws.** 2,000 seeded draws per indicator and cost level. Seed: `numpy.random.default_rng([4, indicator_index, draw_id])` (prefix 4 for T04). On each SELL decision date d, the RNG picks k(d) stocks from the n(d) available.

**Best-of-sweep null.** To protect against cherry-picking the best indicator, a secondary null tests whether the *best* indicator's percentile beats the best of 5 random indicators. For each draw, generate random selections under all 5 indicators simultaneously (shared permutation seed), take the best CAGR across the 5. The strategy's best CAGR is ranked against these 2,000 best-of-5 draws. Pass mark: 98th percentile (same Bonferroni).

**Why this null answers the question.** The k stocks are drawn uniformly at random, so every subset of size k is equally likely. If the indicator's CAGR beats most draws, the *specific* stocks it selects (those above the MA, or in SuperTrend BUY) outperform random subsets. If it doesn't, the indicator adds no value over random stock-picking during SELL.

---

## Hypotheses and criteria

**Bonferroni correction.** 5 indicators tested at family-wise α = 0.10. Each indicator is tested at α/5 = 0.02. Pass mark per indicator: **98th percentile** (instead of T03's 90th).

With 2,000 draws, percentile 98 requires the strategy to beat 1,960 draws. Resolution = 0.05 points. Smallest p-value = 1/2001.

**Hypotheses** (after cost at 20.8 bps; SCMO_0003; per indicator):
- **H1ᵢ, selection.** Indicator Iᵢ selects stocks that earn more than a random same-size selection during SELL. Judged on after-cost CAGR. Falsified if C1ᵢ fails.
- **H2ᵢ, protection.** Indicator Iᵢ's selections avoid deeper drawdowns than random selections. Judged on max drawdown. Falsified if C2ᵢ fails.

**Pass criteria** (after cost at 20.8 bps):

| # | Criterion | Pass condition |
|---|---|---|
| C1ᵢ | Selection (H1ᵢ) | After-cost CAGR percentile against N_sel ≥ 98 |
| C2ᵢ | Protection (H2ᵢ) | Max-drawdown percentile against N_sel ≥ 98 |

**Percentile formula** (same as T03): `(draws worse + 0.5 × draws tied) ÷ draws × 100`. Ties: equal within relative 1e-12.

**Outcome map:**

| Pattern | Conclusion |
|---|---|
| Any indicator passes both C1ᵢ and C2ᵢ | That indicator selects stocks with genuine relative strength during SELL. Finding status depends on robustness |
| An indicator passes C1ᵢ but not C2ᵢ | It adds return but not protection; the selected stocks still fall hard during SELL |
| No indicator passes either | Stock-level filters during SELL add no value over random selection for SCMO_0003. The full defensive switch (T03) is the better rule |
| Best-of-sweep null FAIL | Even if per-indicator passes, the best result is not better than the best of 5 random indicators |

**Reportability gate.** An indicator must have at least 20 SELL decision dates with a non-trivial selection (1 ≤ k < n). If fewer, the indicator is NOT REPORTABLE — the null has too few distinct selections.

---

## Validity gates

If any fails, nothing below may be read.

| # | Gate | Pass condition |
|---|---|---|
| V1 | Independent check `verify_t04.py` | Reimplements indicator computation, target weights, 0-cost NAV, costed NAVs, and 20 sample null draws. Imports nothing from the engine. End NAV within relative 1e-9 for every realisation it recomputes. Exits 0 only if rows were compared and none failed |
| V2 | Point in time | Every decision reads Master rows dated ≤ decision date; every indicator uses only closes on or before the decision date; every trade is on a later session |
| V3 | Null holds its table | For every draw and every SELL decision date: the number of stocks selected equals the indicator's count k(d). For every draw: BUY-regime behaviour is identical to the strategy |
| V4 | Always-in reproduces | The engine with decisions fixed at IN (100% parent, no filter) reproduces the published NAV (D17) within G0 tolerance (±0.25 pp/yr overall, ±0.5 pp in every calendar year) over the D17 scope (2019-01-02 to 2026-10-22). The engine's NAV continues to 2026-11-04 past the D17 scope |
| V5 | Indicator reproducibility | Each indicator's values on 10 randomly sampled stock×date pairs are checked against a hand-computed value using the raw OHLC. Printed in audit.json |

---

## Robustness checks

| # | Check | Condition |
|---|---|---|
| R1 | 100% GOLDBEES sleeve | C1ᵢ and C2ᵢ for each indicator with 100% GOLDBEES (no cash) as the sleeve |
| R2 | Cost sensitivity | C1ᵢ at 0 bps and 50 bps |
| R3 | LIQUIDCASE cash | Replace LBES with LIQUIDCASE from 2024-01-24 onward (same as T03's R3) |
| R4 | Live window | C1ᵢ on 2021-11-01 → 2026-11-04 only (decisions actually traded), with its own k counts and its own null, if it passes the reportability gate |
| R5 | Best-of-sweep null | The best indicator's CAGR ranked against the best of 5 random indicators across the same draws |

---

## Comparators (benchmarks, not nulls)

| Comparator | What it is |
|---|---|
| Hold the parent | Engine with decisions fixed at IN, 0 cost and each cost (same as T03 V4) |
| Full AA switch (T03) | 100% defensive during SELL (50/50 GOLDBEES + cash) — T03's strategy curve |
| The constant mix | Average equity share f across the strategy's weeks, held as f parent + (1-f)/2 GOLDBEES + (1-f)/2 cash, rebalanced at each decision date |
| Published NAV | SCMO_0003 and SCMO_0042 (D17, rebased) |

---

## Engine architecture

**File:** `AA/analysis/t04_engine.py` (standalone, imports nothing from T03 or other AA modules)

**Steps:**
1. Load D17 calendar (sessions from 2019-01-02 to 2026-11-04)
2. Load D18 OHLC for SCMO_0003 (all stocks ever held)
3. Load D19 weight matrix and columns
4. Load Master signals → build decision series (BUY/SELL per decision date)
5. Compute all 5 indicators from D18 closes for all stocks with sufficient history
6. Build SELL-regime selection: for each indicator, on each SELL decision date, which stocks pass
7. Build weekly targets: BUY = full basket; SELL = {filtered stocks at weights} + {sleeve at residual}
8. Simulate daily NAV (units-based, OHLC4 fills, cost) for each indicator × cost
9. Run 2,000 null draws per indicator × cost (selection shuffle)
10. Compute percentiles, p-values, statistics
11. Run best-of-sweep null (R5)
12. Run comparators (hold-the-parent, constant mix, full-AA-switch)
13. Run robustness (R1–R4)

**Outputs** (to `tests/T04/evidence/<run>/`):

| File | Contents |
|---|---|
| `inputs.csv` | Every input file with bytes and sha256 |
| `decisions.csv` | One row per weekly decision: date, regime, signals |
| `indicators.csv` | Per-stock per-decision-date indicator values and filter decisions |
| `selections.csv` | Per indicator per SELL date: k selected, n available, which stocks |
| `trades.csv` | Every trade of every indicator variant |
| `daily_nav.csv` | Daily NAV for each indicator × cost, comparators, published NAVs |
| `stats.csv` | Statistics (CAGR, max DD, Sharpe, Calmar, vol) of every non-null realisation |
| `draws.csv` | Every null draw: per indicator, CAGR, max DD, percentiles |
| `audit.json` | V2 counts, V3 checks, V5 indicator spot-checks, readings |
| `g_engine.csv` | V4: always-in vs published NAV |

---

## Files to create

| File | Purpose |
|---|---|
| `AA/tests/T04/T04.md` | Write-up with pre-registration (§1–§3 frozen before run, sha256 hash) |
| `AA/tests/T04/TRACKER.md` | Task tracker (AGENT.md steps 1–11) |
| `AA/analysis/t04_engine.py` | Standalone engine |
| `AA/analysis/verify_t04.py` | Independent check (imports nothing from engine) |
| `AA/tests/T04/analyse.py` | Print results, analysis.log |
| `AA/tests/T04/report.py` | Generate evidence/report.html |
| `AA/tests/T04/run.sh` | Regenerate everything end to end |
| `AA/tests/T04/check_prereg.py` | Verify §1–§3 frozen sections unchanged |

---

## Implementation order

1. **Write T04.md §1–§3** (idea, hypotheses/criteria, methodology). Freeze with sha256. Write `check_prereg.py`.
2. **Build `t04_engine.py`**: indicator computation → regime decisions → simulation → null draws → statistics → evidence output. Follow T03 engine patterns but self-contained.
3. **Build `verify_t04.py`**: reimplement everything independently.
4. **Run and gate**: execute engine, check V1–V5.
5. **Build `analyse.py` and `report.py`**: results tables, charts, report.html.
6. **Fill T04.md §4–§6**: results, robustness, findings.

---

## Verification plan

1. Run `python analysis/t04_engine.py` → evidence output
2. Run `python analysis/verify_t04.py` → V1 (exits 0)
3. Check `audit.json` → V2 (point-in-time counts), V3 (null table checks), V5 (indicator spot-checks)
4. Check `g_engine.csv` → V4 (always-in ≈ published NAV within G0)
5. Run `python tests/T04/check_prereg.py` → §1–§3 hash matches
6. Run `python tests/T04/report.py` → evidence/report.html
7. Visual inspection of report.html charts and metrics

---

## Known contaminants

| Contaminant | Handling |
|---|---|
| 5 indicators not selected blindly | Disclosed. Bonferroni correction accounts for multiplicity |
| SCMO_0003 only | No generalisation to other parents without testing them |
| Regime same as T03 (already seen) | Disclosed. T04 tests selection within SELL, not timing |
| Master rows before 2021-11 are a backfill | Same as T03. R4 repeats on live window |
| D11 (LBES) source unrecorded | Same as T03: bounded at 0.09 pp/yr; R3 checks with LIQUIDCASE |
| Small basket sizes (5–15 stocks) | When n is small and k is close to n, the null has few distinct selections (C(5,4)=5). Reported per date |
| Indicator lookback extends before window start | 200-day MA on 2019-01-02 uses closes from mid-2018. D18 covers from 2014-07-01. No issue |
| Extended data files beyond T03's window | GOLDBEES extended to 2026-11-04, LBES to 2026-11-05, Master signals to 2026-10-30 (verified vs production, manifest.json). The GOLDBEES extension uses Eikon OHLC; LBES extension uses LIQUIDCASE returns (~0.5 pp/yr rich, same as T03). Published NAV (D17) ends 2026-10-22 — V4 gate scope is limited to that range |

## MDE

For each indicator at 80% power: MDE = (z₀.₉₈ + 0.84) × sd_null = 2.894 × sd_null. Computed after the run. The effective independent unit for selection is the SELL spell (9 out-spells); within a spell, indicator selections are correlated. The MDE will likely be large relative to realistic indicator-driven edges.

## Finding IDs

Per CLAUDE.md counters: F-AA-S05 onward (strategy), F-AA-M03 (method), F-AA-D16 (data).
