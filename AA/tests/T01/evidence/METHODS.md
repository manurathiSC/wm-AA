# Methods: T01 results page (`report.html`)

**Sources.**
- The page is built by `AA/tests/T01/report.py` from `evidence/headline/` only: `realisations.csv`, read with `keep_default_na=False, na_values=[""]`, and `daily_reference.csv`.
- The design, gates and criteria are in `AA/tests/T01/T01.md`. The full printed analysis is in `AA/tests/T01/analysis.log`.
- **Build check.** The build refuses to write if R's CAGR or percentile for any book and window differs from `analysis.log`, or if its C1–C3 counts differ from the pre-registered verdicts.

**Page check** (added 2026-10-05). `AA/tests/T01/check_page.py <page.html>` shares no code with the engine, the verifier, analyse.py or report.py. It re-runs the reference rule from the raw input files and compares every number in the published page's data block with the evidence. It also checks every number in the page's prose. Result on 2026-10-05: 400 checks, 0 failed. One fix followed: the prose had called the 192,584 point-in-time checks "decisions". There are 78,088 decisions.

**Common definitions.**

| Term | Definition |
|---|---|
| **Books, parents** | SCMO_0042 → 0003, 0043 → 0007, 0044 → 0010, 0045 → 0029. Each book is scored on its parent's index |
| **Periods** | 2015–21 (W1) is 2015-07-31 → 2021-10-29, on the harness rebuild of the parents from their real baskets (price return). 2021–26 (W2) is 2021-11-01 → 2026-08-21, on the published parent NAVs. Lookbacks reach into the rebuild |
| **Rule R ("your rule")** | `pct_w65_q25`. At each week's last session d, p = the share of the 65 previous closes below today's close, × 100. Hold 0% of the smallcase if p < 25, else 100%. The rest is 50% GOLDBEES / 50% LBES. Trade on the next session at its close, only when the target changes. 20.8 bps round trip, charged per side on the value traded |
| **Hold** | The parent index from the period's first session to its last, close to close, no cost |
| **CAGR** | NAV_end^(252 ÷ (sessions − 1)) − 1. This is AGENT.md's convention of 252 sessions a year. NSE has about 247, so levels run 0.2–0.5 pp above a calendar-year CAGR (days ÷ 365.25), which is the basis the final-strategy page uses. Rule-vs-hold and rule-vs-null comparisons are unaffected |
| **Worst fall** | Maximum drawdown of daily NAV |
| **Random timing (the null)** | The rule's own weekly target series (in or out each week), rotated by k weeks for every k from 8 to n+1−8: 312 draws in 2015–21 and 237 in 2021–26. Each draw runs through the identical engine at the same cost. It holds the share of weeks in the sleeve and the switch count (±2, at the wrap) fixed, and moves only *when* the exits happen. No seeds |
| **Percentile ("beats %")** | (draws with lower after-cost CAGR + 0.5 × draws equal within 1e-12) ÷ draws × 100 |
| **Edge** | The rule's CAGR minus the median CAGR of its draws, in pp |
| **Detectable edge (MDE)** | 2.8 × SD of the draws' CAGR: the smallest edge this design would detect 80% of the time at two-sided 5%. null_sd ÷ observed_se is 0.86–1.28 for R (`analysis.log`) |

## Page elements

| Element | What it shows | Formula and denominator | Source columns | Limits |
|---|---|---|---|---|
| **Tiles** | C1 (timing) and C2 (worst fall) verdicts; the 4-book average CAGR of R against hold | C1: books with percentile ≥ 90, reportable, out of 4 per period. C2: books where R's worst fall is ≥ 5.0 pp shallower than hold's. "FAIL — 2015–21 only" means it passed in one period. The average is the simple mean of the four books' CAGR | `realisations.csv`: `kind`, `config`, `cagr`, `max_dd`, `n_switches`, `share_sleeve_weeks` | The four books move together; "3 of 4" is consistency, not four independent tests |
| **Ideas table** | Seven families of momentum signal, with what each asks, its strength and weakness, and what this test found | "Here": the range of median percentiles (median across the four books) over the configs of that family, per period | `realisations.csv` | The families are the author's summary. Relative strength and breadth were not tested |
| **Strip chart** | Per book and period: every random-timing draw (grey dot), the rule (large mark) and hold (tick), on after-cost CAGR | x = CAGR. The vertical jitter of the dots is deterministic and carries no meaning. The right-hand number is the percentile | `realisations.csv` (`kind` = null / strategy / bh), cost 20.8 | Hover titles on the rule and hold marks only |
| **Reference table** | R per book and period: CAGR, hold, random median, edge, percentile, MDE, worst falls, share of weeks in the sleeve, switches | As defined above | as above | MDE is per book-window; pooling books was not done |
| **Path chart** | Growth of 1 for R (after cost) and hold, daily closes, log scale. Shading where R held < 50% in the smallcase | NAV from the engine; hold = P ÷ P_T0 | `daily_reference.csv`: `nav`, `nav_bh`, `w_equity` (drifted weight at the close) | 2015–21 uses the price-return rebuild |
| **Drawdowns and time under water** (added 2026-10-05, after the run; descriptive) | For holding, R and five comparison rules: the worst fall, the share of days ≥ 10% below the previous high, the longest drawdown, the Ulcer index, and the Ulcer index against random timing | DD_t = NAV_t ÷ running peak − 1, on daily NAV after cost (20.8 bps, 50/50 sleeve). Days ≥ 10% down = share of sessions with DD_t ≤ −10%. Longest drawdown = the longest stretch, in calendar days, from a high to the next new high; one still open at the window end runs to the last date. Ulcer = √mean(DD_t²) × 100. The first table holds 4-book means, except "Ulcer vs random", which is the median across books of the share of null draws with a higher Ulcer. The per-book table shows R against hold | `evidence/diagnostics/drawdown_profile.csv` (and `_nulls.csv`, `_summary.csv`), written by `drawdown_profile.py` for all 30 configs. That script re-simulates every strategy path and null draw from `spliced_inputs.csv` and `decisions_all_configs.csv`. Its gate passed: all 74,216 paths reproduce the engine's `nav_end` and the strategies' `max_dd` within relative 1e-9 | **Not pre-registered**, so no verdict rests on it, and the measures were chosen after the return results were known. "Any day below the last high" is 85–97% for every series and does not separate them, so it is not shown. The four books are not independent |
| **Sweep table** | Every config (28 pre-registered + 2 descriptive market-index rows), for the period chosen. Timing against random: median percentile, median edge, books ≥ 90th (reportable only). Then 4-book averages of CAGR, worst fall, the share of days ≥ 10% down, the longest drawdown and the Ulcer index; the Ulcer column against random is a median percentile. A first row holds the smallcase for reference, and CAGR and drawdown cells are coloured against it (added 2026-10-05) | Medians across the four books. The tint is green above a median percentile of 50 and red below; its strength ∝ \|pct − 50\| | `realisations.csv` | **Descriptive only.** The best config per book-window ranks at the 35–83rd percentile of the null's best rows (`analysis.log`, MULTIPLICITY), so no sweep row is a claim. NOT REPORTABLE rows (fewer than 4 switches, or under 5% / over 95% of weeks in the sleeve) are excluded from the "≥ 90th" count. The only ones are `pct_w250_q10` in 2021–26 on 0042 and 0045 |

## Statistical status

- **Validity gates V1–V5 pass** (`analysis.log` §4.0):
  - the independent checker made 459,722 comparisons with 0 failures, and failed a corrupted copy as it should;
  - point in time: 192,584 checks, 0 violations;
  - every one of the 147,952 null draws holds the strategy's target levels;
  - the splice and the B&H tie-out match within 1e-12.
- **Verdicts:** C1 FAIL, C2 FAIL (W1 only), C3 FAIL (W1 only). Robustness R4–R7 FAIL.
- **Findings:** F-AA-S01 and S02 are REFUTED, S03 is OPEN, F-AA-M01 is CONFIRMED (`T01.md` §5).
- **Largest caveats:**
  - No period was unseen.
  - Before 2021-11 the parents are price-return rebuilds.
  - Fills are at the next close, not OHLC4, because the index has closes only.
