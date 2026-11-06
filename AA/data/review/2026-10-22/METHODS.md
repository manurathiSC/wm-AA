# Methods: AA data review page (`data_review.html`), review of 2026-10-22

**What it is.** The project-level data review that AGENT.md task 0 requires before a test reads any
input. It is not a test: it makes no claim about any strategy.

**How it is built.**
- `data/data_review.py --date 2026-10-22` reads the raw files only, imports nothing from `AA/analysis`,
  and writes every CSV, `summary.json` and the charts into this folder. Its generic checks are in
  `data/review_lib.py`.
- `data/review_page.py --date 2026-10-22` builds this page and `data/DATA_REVIEW.md` from those
  outputs and from `data/review_decisions.json`.
- **Judgement vs computation.** The decisions file holds every judgement: the source and fetch
  details of each input, its verdict and note, the defect texts, the causes of large moves, the
  component map and the open questions. Every number on the page comes from the CSVs.

**Reference calendar.** `Historical Data/FRA_MAUc1/Data/TradingDays.xlsx`: the production job's NSE
calendar built from Refinitiv `.NSEI`, 2000-01-03 → 2026-09-25. The engines' `calendar.csv` is the
same list to 2026-09-18. It is not independent of the data: there is no exchange holiday file in
the project. Disagreements with the other sources are listed, not resolved.

## Page elements

| Element | What it shows | Formula and denominator | Source (file, columns) | Limits |
|---|---|---|---|---|
| **Verdict per input** | One row per input: role, span, source, fetch details, verdict, reason | Span = the first and last date in the input's file (for the Master files, the first and last weekly row) | `review_decisions.json` (inputs); spans from `calendar.csv`, `signals.csv`, `values.csv`, `baskets.csv` | Verdicts are judgements under AGENT.md task 0. A missing source is a FAIL even when the values pass |
| **Component map** | Which series each role uses, why, and the conventions | — | `review_decisions.json` (component_map) | Conventions bind future tests. Earlier studies may differ (F-AA-D05) |
| **Calendar** | Per series: first and last date, rows, reference sessions in its span, missing, extra, weekend rows, duplicates, longest gap | missing = reference sessions in [first, last] with no row; extra = rows on dates not in the reference; longest gap = the most consecutive reference sessions missing | `calendar.csv`, `calendar_diffs.csv` (`review_lib.calendar_check`) | The reference itself misses five real sessions (F-AA-D02) |
| **Special sessions** | Since 2014-07-01: the dates where the reference and an NSE-traded series (published NAVs, GOLDBEES Eikon, GOLDBEES Kite) disagree, plus thin stock-file sessions; who holds each | A date is in the NSE calendar unless some series lists it as extra. "Thin" = stock rows < 0.5 × the median count over the surrounding 11 sessions | `calendar_diffs.csv`, `sessions_absent_from_stock_file.csv` | MCX-only dates (MAUc1 on NSE holidays) are counted, not listed |
| **Values** | Blanks and non-positive values per field; OHLC breaks; stale runs; unit breaks | OHLC break: low > open or low > close or high < open or high < close (tolerance 1e-9 × high). Stale run: ≥ 5 identical consecutive closes (≥ 3 for cash). Unit break: close(t) ÷ close(t−1) > 5 or < 0.2 | `values.csv`, `value_issues.csv` (`review_lib.value_check`) | The stock files are checked as panels: blanks, duplicates on (ISIN, date), dates off the calendar, OHLC breaks |
| **Signals** | Per Master file: span, weeks, share BUY, flips, rows not on the week's last session, weeks missing, SIGN ≠ band, close ≠ index file | Last session of a week = the latest reference session in that ISO week. SIGN must be BUY iff ST = FLB, and SELL iff ST = FUB (tolerance 1e-9 × ST). Close check: Master `Index` ÷ the index file's close on that date − 1, > 1e-6 counts | `signals.csv`, `signal_issues.csv`; Master files; `indices_ohlcv.xlsx` | Checks the files' internal consistency, not whether the supertrend code is right. That was proved separately (the MAUc1 Gold Trend page, cell-for-cell reproduction) |
| **Parent baskets** | Per parent: baskets, first and last effective date, names, weight sums, signal-to-effective lag, skipped rows, blank and '*' tickers, bad and duplicate ISINs | Weight sum per effective date; lag = availableDate − date in days; bad ISIN = fails `IN[EF][A-Z0-9]{8}[0-9]` | `baskets.csv` | Whether a skipped basket traded is unknown (F-AA-D07) |
| **Stock prices over held sessions** | Per window and parent: stocks held, stock-sessions held, those with no Eikon close, the unpriced weight share, the worst day | unpriced weight share = Σ_t Σ_i w(i,t) × 1[no close for i on t] ÷ sessions. w = listed weight in the basket in force on t (no drift). Sessions = reference sessions in the window, excluding thin sessions. A basket is in force from its effective date to the day before the next. Windows: 2014-07-04 → 2021-10-29 and 2021-11-01 → 2026-08-21, the final-strategy engine's | `coverage.csv`, `coverage_missing.csv` | Matches each parent's ISIN directly to the price file's key. The engine's own ISIN resolution may place a few more, so this can overstate gaps for renamed ISINs (two held ISINs have no rows at all) |
| **Histories ending early** | Every ISIN whose rows end more than 30 days before its file does, with the delisting month from its RIC suffix | Eikon writes a delisted RIC as `<code>^<month letter A–L><yy>`. Reading "GAP" when 5 or more histories end on the same date | `price_history_ends_early.csv` | RICs without a suffix (still listed, or Eikon did not mark them) give no delisting month |
| **Coverage maps** | Date × held stock: price present (blue), missing (red), not held (blank) | — | `charts/coverage_<window>.png` | Rows compressed to fit; read the table for counts |
| **Large moves on held stocks** | Every close-to-close move ≥ 20% while a parent held the stock; next-day move | move = close(t) ÷ close(previous row) − 1 | `stock_moves.csv` | Flags a print reversed next day by ≥ 15% as suspect |
| **Eikon against Kite** | Same ISIN, same day, daily return difference > 5 pp | difference = r_Eikon − r_Kite | `stock_source_diffs.csv`, `summary.json` | Kite is not adjusted for demergers or special dividends, so most gaps are Kite's |
| **Largest moves** | Every move beyond the threshold since 2014-07-01 (earlier ones in a fold), a second series' move, and an explanation | Thresholds: index, ETF, futures 5%; smallcase NAV 8%; cash 0.5%. Confirmed when a second series moved the same way by ≥ 0.3 × the size (for MAUc1, GOLDBEES's next session also counts) | `largest_moves.csv` | Event names are the reviewer's notes (`move_notes`); unnamed confirmed moves say "a second source agrees" |
| **Reconciliation** | Pairs on common dates: CAGRs, gap per year, correlation of daily returns, largest daily gaps | CAGR = (P_last ÷ P_first)^(365.25 ÷ calendar days) − 1; gap = CAGR_first − CAGR_second; Pearson correlation of daily returns | `reconciliation.csv` (`review_lib.returns_gap`) | Calendar-day CAGR (not 252-session) |
| **Derived series** | Harness parents, GOLDBEES de-spiked fills, MAUc1 cleaning, cash by calendar year | De-spike change = clean OHLC4 ÷ raw OHLC4 − 1 on changed days; cash year return = last level of the year ÷ last level of the previous year − 1 | `derived.csv`, `summary.json`, `goldbees_fill_despiked.csv`, `mauc1_cleaning_log.csv` | 2026 runs to 2026-08-09 only |
| **Spot checks** | Values on fixed dates for a person to compare with a public source | — | `spot_checks.csv` | None checked yet |
| **Data defects** | F-AA-D01 – D10 | — | `review_decisions.json` (issues), mirrored in `issues.csv` | — |
| **Charts** | Per series: level (log), daily returns with the threshold, histogram (log count); overlays rebased to 1 on the first common date | — | `charts/*.png` | PNG images, drawn for both themes with mid-grey ink |
| **Inventory** | Every file, its size, sha256 and last-modified time | — | `inventory.csv` | File time is not a fetch date |
