# AGENT.md — how to research a strategy or a signal

This is the working framework for anyone — a researcher or a coding agent — who wants to find out
whether an idea about the market actually works: a trading strategy, a market-timing rule, a ranking
signal, a filter, an event, a model's predictions. It gives you three things:

1. **The workflow** (Part 1): a data review done once per project before its first test (task 0),
   then eleven tasks per test, in order, each with what to do, what it produces, and how you know it
   is done.
2. **The null book** (Part 2): how to test a result against chance correctly — what a null is, how
   to build one, the families of null and when each fits, how to judge a result against it, and
   what goes wrong.
3. **Reference** (Part 3): the backtest convention, the logging formats, and the checklists.

**Why it exists.** Most market "discoveries" are luck, look-ahead or a measurement bug. Each of
those produces a number that looks exactly like a real edge. Every rule below exists because one of
them did, and most rules say what it cost. Follow the tasks in order and you will catch them before
anyone acts on the number.

**Start here.**
1. **You need nothing else in this repository.** The studies quoted ("in one study") are lessons, not
   dependencies; no existing project's code or data is required.
2. **Read [R3 — Words used here](#r3-words-used-here) first.** Part 1 uses its terms (setting, start
   date, realisation, slot, band, OHLC4, MDE) before Part 3 defines them.
3. **Before a project's first test, review its data** (task 0): copy
   [DATA_REVIEW_TEMPLATE.md](DATA_REVIEW_TEMPLATE.md) to `<project>/data/DATA_REVIEW.md`.
4. **Copy [TEST_TEMPLATE.md](TEST_TEMPLATE.md)** for every experiment. It has a slot for everything the
   tasks ask for.
5. **Write your own engine to R1**, or use the team's `wm-quantBacktester` with the corrections in R2.

---

## Contents

**Part 1 — The workflow**
[The ten rules](#the-ten-rules) ·
[0 Review the project's data](#0-review-the-projects-data--once-per-project-before-its-first-test) ·
[1 Frame the question](#1-frame-the-question) ·
[2 Choose the kind of experiment](#2-choose-the-kind-of-experiment) ·
[3 Set up the project](#3-set-up-the-project) ·
[4 Get the data right](#4-get-the-data-right) ·
[5 Pre-register the design](#5-pre-register-the-design) ·
[6 Build the engine](#6-build-the-engine) ·
[7 Build the independent check](#7-build-the-independent-check) ·
[8 Run and gate](#8-run-and-gate) ·
[9 Read the results](#9-read-the-results) ·
[10 Log the findings](#10-log-the-findings) ·
[11 Report, revise, retire](#11-report-revise-retire)

**Part 2 — The null book**
[N1 What a null is](#n1-what-a-null-is) ·
[N2 The one-ingredient rule](#n2-the-one-ingredient-rule) ·
[N3 Designing a null in seven steps](#n3-designing-a-null-in-seven-steps) ·
[N4 The families of null](#n4-the-families-of-null) ·
[N5 What "held identical" really requires](#n5-what-held-identical-really-requires) ·
[N6 Judging a result against its null](#n6-judging-a-result-against-its-null) ·
[N7 When the null misleads you](#n7-when-the-null-misleads-you) ·
[N8 Worked examples](#n8-worked-examples) ·
[N9 Writing the null down](#n9-writing-the-null-down)

**Part 3 — Reference**
[R1 The backtest convention](#r1-the-backtest-convention) ·
[R2 Using wm-quantBacktester](#r2-using-wm-quantbacktester) ·
[R3 Words used here](#r3-words-used-here) ·
[R4 Findings](#r4-findings) ·
[R5 The write-up](#r5-the-write-up) ·
[R6 Evidence and scripts](#r6-evidence-and-scripts) ·
[R7 Writing numbers and keeping history](#r7-writing-numbers-and-keeping-history) ·
[R8 Rules in force across wm-research](#r8-rules-in-force-across-wm-research) ·
[R9 Checklists](#r9-checklists) ·
[R10 The results page](#r10-the-results-page) ·
[Revision history](#revision-history)

---

# Part 1 — The workflow

## The ten rules

Every task applies these.

1. **Every experiment is a numbered test that owns a folder.** `tests/T<NN>/` holds its write-up,
   the scripts that regenerate it and its evidence. A result is cited from there or not at all.
2. **The design is written before anything runs, and never edited after.** Criteria written after
   seeing the numbers are not criteria — they are a description of the numbers.
3. **No number travels alone.** A result sits beside its null, its statistic, its denominator and
   its window — the first and last date it covers; wherever a trade is modelled, beside both its
   before-cost and after-cost value; wherever it is computed, beside its formula; and a failed
   criterion beside the smallest effect the test could have detected.
4. **Numbers are generated, never typed.** A script reads the stored evidence and prints every table
   the write-up uses.
5. **Every result is checked by code that shares nothing with the code that produced it.**
6. **Every claim is a finding**, with an ID, a status, its evidence, what would prove it wrong, and a
   command that reproduces it.
7. **History is never rewritten.** Old results get a banner saying what replaced them; they are not
   edited. A killed idea stays on the record as killed.
8. **Every decision uses only what was known at the time**, and that is checked in code, not assumed.
9. **No test reads data the project has not reviewed.** Every input has a named source, a fetch date,
   a fingerprint and a verdict in the project's data review (task 0) before any test uses it. What an
   agent may read is the owner-approved list in `data/APPROVED_DATA.md`; anything else is off-limits.
10. **Every test can be redone by hand from its write-up.** It explains in plain words how each
    series was built, how one decision was made, how one null draw was made and how one result was
    ranked, each with a worked example in real numbers. Formulas alone are not an explanation.

---

## 0. Review the project's data — once per project, before its first test

**Goal:** before any test reads it, every input has a known source and fetch date, has passed a set of
quality checks that a script prints, has been looked at in charts, and has a written verdict. Tests
come and go; the data is shared by all of them, so it is reviewed once, at project level, and
re-reviewed whenever it changes.

**When:** before the project's first test; again whenever an input is re-fetched, extended, corrected
or replaced, or a new input is added. Each review is dated, and a test records the review it used
(R6). A review is never edited after a test has cited it; a new one is written beside it.

**Where:** `<project>/data/` (layout in task 3). Copy [DATA_REVIEW_TEMPLATE.md](DATA_REVIEW_TEMPLATE.md)
to `data/DATA_REVIEW.md`. `data/data_review.py` runs every check and draws every chart from the raw
files, imports nothing from any engine, and writes `data/review/<YYYY-MM-DD>/`.

**Do, in this order:**

1. **Inventory every input** — prices, volumes, index levels, published NAVs, signals, weights,
   calendars, universes, fundamentals, model outputs. One row each:
   - **what it is and its role** in the project: signal, fill price, valuation, benchmark, cash,
     universe, calendar;
   - **where it came from**: the source system (database and table, vendor terminal, API, a person's
     export), the exact query, endpoint or script that fetched it, and who fetched it;
   - **when**: the fetch timestamp, and the last date the data covers. A file name's date is not a fetch
     date unless someone confirms it;
   - **the fingerprint**: path, sha256, size, rows, columns, first and last date, frequency;
   - **what the numbers mean**: units and currency; the timestamp's meaning (close of which exchange,
     which time zone); for prices, what they are adjusted for (splits, bonuses, rights, demergers,
     dividends) — price return or total return;
   - **its restrictions**: licence, sharing limits, anything known to be restated after the fact.

   A file whose source nobody can name is a **FAIL** until someone can.
2. **Check the calendar** against the trading calendar of the exchange each series trades on (name it:
   NSE, BSE, MCX…), for every series:
   - missing sessions; extra dates (weekends, holidays); duplicate and out-of-order dates;
   - special sessions (Muhurat trading, exchange-declared extra sessions) present or absent;
   - for a panel, every name's coverage over its own listed life, and the number of names with data
     on each date;
   - every gap longer than a stated number of sessions, listed one by one.
3. **Check the values:**
   - blanks and NaNs; zero or negative prices; zero or negative volume;
   - OHLC consistency (low ≤ open, close ≤ high);
   - stale runs: the same value for a stated number of sessions or more;
   - the largest moves: every daily return beyond a stated threshold for that kind of series (for
     example 20% for a stock, 5% for an index, 0.5% for a money-market fund), listed one by one, each
     explained — a corporate action, a real event, or a data error — and checked against a second
     source or a corporate-action list;
   - unit breaks (paise and rupees, a ×10 or ×100 jump), and level jumps at any splice point;
   - spot checks: at least three dates per series compared with an independent public source (the
     exchange's own site, the fund's factsheet), recorded with the values found.
4. **Reconcile overlapping sources.** Wherever two sources cover the same thing (a vendor and a
   database, a published NAV and a rebuild), compare their *returns*: the gap per year, the
   correlation, the largest daily differences, and a chart of the ratio. Decide which source each
   role uses, and why.
5. **Document every derived series** the project builds — a rebuilt index, a splice, a
   dividend-adjusted cash line, a continuous futures series, a forward fill. For each: its inputs, its
   construction in plain words and as a formula, the splice dates, the script that builds it, its
   reconciliation against an official series where one exists, and a chart of the two together. A
   derived series is an input like any other: it gets an inventory row and a verdict.
6. **Look at it.** For every series: the level (log scale), daily returns over time, the histogram of
   daily returns, and the largest-moves table; for a panel, a map of missing data (date × name) and the
   count of names per date. These charts are for seeing the data, not for presenting it — plain is
   fine, but every chart is generated by `data_review.py`, never by hand.
7. **Write the component map**: one row per role the strategy needs (the asset traded, its fill
   price, its valuation price, each benchmark, the cash leg, each signal, the calendar) → the exact
   series and field used, and why that one. Fix the project-wide conventions here — how gaps are
   filled, how a series that ends early is extended, which calendar wins when two disagree — so that
   two tests cannot quietly make different choices.
8. **Give each input a verdict:** **PASS**, **PASS WITH NOTES** (each note a known issue with its
   handling: fixed by a script, excluded, or accepted with its likely effect), or **FAIL** (not usable).
   Every data defect gets a finding ID `F-<P>-D##` (R4).

**Lessons — what skipping a check cost:**

| Check | What it cost when it was skipped |
|---|---|
| What a price means | A liquid fund that pays its yield out as daily dividends has a flat price: its price series returns exactly 0.00% over any window, and a cash leg built on it earns nothing. The dividend-reinvested series earned about 5% a year |
| Calendar against the exchange | A published index file that skipped two special sessions gained a day's return in every comparison with a series that held them |
| Adjustment basis | A price table not adjusted for demergers showed one-day falls of 22% to 44% on held stocks that never happened to a holder |
| Names and identifiers | A re-export stamped today's tickers on historical rows; a ticker join called held stocks "unpriced" and "unranked", and both were false |
| Coverage over the held dates, not "has rows" | One session had a close but no open for about 2,400 of 2,768 stocks; an OHLC4 fill on it fails without a fallback |
| Extra dates | A cash file posted most of its daily accruals on Sundays (934 rows); a strategy reading it on a trading calendar must say how those rows are carried |
| One convention per project | Two studies extended the same cash file past its last date differently — one held it flat, one accrued it at the trailing rate |

**Produces:** `data/DATA_REVIEW.md` (inventory, component map, derived series, issues, verdicts),
and `data/review/<date>/` with `inventory.csv`, `checks.csv`, `issues.csv`, the charts and a
`data_review.html` with its methods file (R8). **Done when** every input any planned test needs has a
verdict, every check is printed by `data_review.py`, every chart exists, every large move is
explained, and a reader can answer "which price is used for X, where did it come from, and when?" for
every X from the component map alone.

---

## 1. Frame the question

**Goal:** a question precise enough that a result can answer it — and fail it.

**Do:**
- Write the idea in **one sentence**: what you think predicts what, over what horizon, in which
  universe.
- Write **where it came from** — a paper, an observation, a colleague, a hunch. Quote the person if
  it was someone's idea. A hunch is a legitimate origin; call it one.
- Write **what decision the answer will change**. If none, stop.
- Collect **what is already known**: earlier tests of this or nearby ideas, and how this one relates
  to each (depends on it, extends it, contradicts it).
- Write **what this test is not asking** — the nearest question it cannot answer, because that is the
  question it will be over-read as answering.

**Produces:** §1 of the write-up. **Done when** a colleague can read the sentence and say what result
would make it false.

---

## 2. Choose the kind of experiment

**Goal:** name the shape of the experiment, because the shape decides the unit of analysis, the
null, and how much evidence you really have.

| Kind | The question | Unit | Default statistic | Natural null (Part 2) | Independent observations | Classic trap |
|---|---|---|---|---|---|---|
| **Strategy backtest** — choosing which stocks to hold | Does a rule, run as a portfolio, beat chance after costs? | one portfolio path | total return per start date, before and after cost | the same rules on a shuffled signal (N4.1) | non-overlapping holding periods | an unwritten execution calendar |
| **Timing rule** — when to be in one asset or index, and when in cash | Does the rule choose *when* better than chance? | one in-or-out path | total return and drawdown, before and after cost | random timing at matched exposure (N4.9) | round trips (one entry plus one exit), not sessions | lower drawdown that is only lower exposure |
| **Cross-sectional signal** | Does a score *order* future returns across stocks? | one date's cross-section | per-date rank correlation, or top-minus-bottom spread | per-date shuffle, persistent random score, time shift (N4.1, N4.3, N4.4); a stratified shuffle (N4.2) if the score is tilted | dates with non-overlapping horizons | a null calmer than reality (N7) |
| **Event study** | Does a feature of an event — a beat, a type of news — move stocks? | one event | the tradable return over the event's own window, against a benchmark over that same window | the feature permuted among same-date events (N4.8); placebo events for "does any event move it" (N4.7) | distinct event dates or clusters | an event dated before it was knowable |
| **Screen or filter** | Does narrowing the universe help? | the portfolio built from the narrowed pool | its result against the unfiltered portfolio | a random exclusion of the same size (N4.6) | as for a backtest | the filter removes the thing that worked |
| **Classifier or judge** — rules, a model, an LLM | Are its picks better than chance from the same candidates? | one decision | the return of picks minus rejects | label permutation within date (N4.8) | decision dates, not decisions | a model that already knows the outcome |
| **Parameter sweep** | Which setting works best? | one setting | the primary statistic, setting by setting | each setting's own null, plus a best-of-sweep null (N6.8) | far fewer than the number of settings | choosing the best-looking setting, which is choosing noise |

**Test at the unit the decision is made at.** In one study a sleeve of news-flagged stocks whose
average stock earned +0.84% returned −0.90% per stock held once it was run as a 15-stock portfolio:
capacity, not the signal, decided the result. An average over names is not a portfolio.

**Produces:** the "kind of experiment and unit" line in the write-up's header.

---

## 3. Set up the project

**Goal:** a folder where every number can be traced to the code and data that made it.

**Where things live in `wm-research`:**

```
wm-research/
  AGENT.md, TEST_TEMPLATE.md,    this framework and its two templates
  DATA_REVIEW_TEMPLATE.md
  <project>/                     one folder per research line
    README.md          the front door: what this is, which test is current, the register of tests
                       and findings, how to read every column, how to run it, every file
    CLAUDE.md          short and blunt: hard rules, conventions, traps already hit, the current-test
                       line, and the finding-ID counter
    AGENT.md           how this project applies the framework: its settings, its nulls, its gaps
    GLOSSARY.md        every term and statistic in plain words, with a real example
    TEST_TEMPLATE.md   a copy of wm-research/TEST_TEMPLATE.md
    data/              the project's data review (task 0) — shared by every test
      DATA_REVIEW.md           inventory, component map, derived series, issues, verdicts
      data_review.py           runs every check and draws every chart from the raw files
      build_<series>.py        one script per derived series (a splice, a rebuild, an adjusted line)
      review/<YYYY-MM-DD>/     one folder per review: inventory.csv, checks.csv, issues.csv,
                               charts/, data_review.html and its METHODS.md
    <engine>.py        the experiment; writes a full evidence set wherever --out-dir says
    verify_<engine>.py the independent check (task 7); imports nothing from the engine
    output/            scratch — overwritten by every ad-hoc run, never cited
    tests/
      T01/
        PLAN.md                the approved plan, copied verbatim (see below)
        T01.md                 the write-up
        run_grid.sh            regenerates every run of the test
        analyse.py             reads only evidence/, prints every table → analysis.log
        grid_<run>.log         each run's console output
        verify_*.json          the independent checks' verdicts
        <decision log>.csv     one row per decision (R6)
        evidence/<run>/        one folder per run: summaries, every realisation, ledger, audit.json
```

- **Every test keeps its plan as `tests/T<NN>/PLAN.md`.** When a plan for the test is written or
  approved (in plan mode the agent saves it under `~/.claude/plans/`, outside the repository), copy it
  *verbatim* to `tests/T<NN>/PLAN.md` before any engine code is written — create the folder if it does
  not exist yet. Copy, never retype, and never overwrite an existing `PLAN.md`: a revised plan is
  saved as `PLAN_v2.md` beside it, and the changes stay on the record (rule 7). `PLAN.md` is the
  implementation plan (steps, hand-offs, dependencies), not the pre-registration: the design is
  frozen in `T<NN>.md` §1–§3 (task 5), and where the two disagree `T<NN>.md` wins. State the copy and
  its byte size in the hand-over message.
- **Raw inputs are read-only.** Reference them by path; never copy or edit them inside a test. A
  derived input is built by a script in the project, and the script is the record.
- **A new question gets a new test number**, and so does an old question under a changed rule. The
  old test keeps its numbers.
- **Choose the project's finding prefix** `<P>` before the first finding (R4), check nobody uses it,
  and write it in CLAUDE.md beside the counter line.

**Done when** the data review (task 0) has a verdict for every input the test will read,
`run_grid.sh`, `analyse.py` and the verifier exist as stubs, and an ad-hoc run cannot write into
`tests/`.

---

## 4. Get the data right

**Goal:** every number the strategy uses was knowable at the moment it used it, every price means
what you think it means, and every name that existed at the time is in the universe.

**This task builds on the data review (task 0).** The review asks "is the data right?" once for the
project; this task asks "is it used right?" for this test.
- Read every input through the review's component map. A test that departs from it (another price,
  another gap rule) says so in §3 with the reason.
- An input the review does not cover is added to the review first, with its verdict, before the test
  reads it. Every PASS WITH NOTES note becomes a row in §3's known contaminants.
- The run checks each input's sha256 against the review's inventory (R6). A file that changed since
  the review stops the run.
- **Use only the data the project has approved.** The project keeps one file, `data/APPROVED_DATA.md`,
  listing every input an agent may read, with its path, through-date and fingerprint, and the latest
  usable date per role. Anything not listed there is off-limits. If an approved input is stale for the
  test, missing or unclear, **stop and ask the owner**; do not extend, rebuild or work around it.
- **Refreshing is the owner's decision.** When the owner asks for a refresh: read-only, same source and
  adjustment basis, originals kept, output a new `<name>_extended_<last session>` file, overlap checked.
  The new file is a candidate and stays off-limits until the owner approves it; the approval check covers
  only the new rows, against the statistics of the approved history, and an agent then updates
  `APPROVED_DATA.md` by the procedure at its bottom. The project's CLAUDE.md names the scripts and the
  credentials.

| Rule | Why — what it cost when it was broken |
|---|---|
| **Date every input, and assert in code that it predates the decision.** Count the checks and the violations in the run's provenance record, against the dates of the data actually used, so that a violation can register | Ranking on the entry day's own close and buying at its open turned +16.8% into +73.0% |
| **The exit is a point-in-time question too.** A sale triggered by a signal must be executable when the signal exists | Pricing signal-driven sells at the signal day's average price added a fake +5.7pp |
| **Write the execution calendar down** — which day the signal is read, which day and price the trade happens, where each period ends — and check it against the data | An unwritten calendar was worth +4.2pp and manufactured a "best" holding period |
| **Use adjusted prices, and say what they include.** Adjust every price for splits, bonuses and rights before computing any signal, fill or return, and use the same adjusted series for OHLC4 and the close. Either credit dividends (a total-return series, or cash on the ex-date) or state that returns are price-only, and use the matching benchmark (total-return index or price index). Divide a per-share fundamental only by a price on the same share basis, or compute ratios from totals (earnings ÷ market cap) | An unadjusted 1:1 bonus reads as a −50% day; pre-bonus EPS over the post-bonus price doubles a stock's earnings yield and puts it at the top of a value ranking |
| **Use the universe as it was on each date.** A list taken today and applied to the past keeps only the survivors, and overstates every level | A top-1000 list taken at the end of the window and applied backwards |
| **A held name that stops trading is a cost, not a gap.** Count every held name that is suspended or delisted, and report the result with those positions written down to zero beside the result at their last close | Suspensions and delistings cluster in cheap stocks; valuing them at the last close flatters a value portfolio |
| **Decide eligibility per date, never from the whole window** | Admitting a stock because it *ever* had news in the window leaks the future through the universe |
| **Non-price data is dated by publication**, to the minute where possible, not by the period it describes. Drop anything dated after its source file. A model's output is dated by the latest input it saw | An after-hours result is not knowable at that day's close |
| **A fundamental with no publication timestamp gets a stated, conservative lag**, never its period-end date. For Indian listed companies, quarterly results are due within 45 days of quarter end and annual results within 60 days of year end (SEBI LODR Regulation 33): date each figure at period end + 45 days (quarters 1–3) or + 60 days (the fourth quarter and the year), and rerun with a longer lag as a robustness check. Use figures as first reported, not later restatements; a source that keeps only restated figures is a known contaminant | A trailing EPS dated at its quarter end is used up to two months before anyone could read it |
| **A model's knowledge has a date.** A model run today on old inputs may know what happened next. Record its id, version and training cutoff; the headline uses only decisions after the cutoff; earlier decisions are reported separately as contaminated. If the whole window predates the cutoff, test for leakage — mask names and dates, and ask the model for the outcome directly | In one study only two months of the window were clean of the model's cutoff |
| **Start every return window at the first price that could act on the event.** Name which return you measure: the *reaction* (from the last close before publication — nobody could trade it) or the *tradable* return (from the first fill after it). Only the tradable return is an edge | An after-hours call measured from that day's close is pure overnight gap |
| **Report everything dropped** — skipped dates, excluded names, missing bars, rejected placebo draws — and why | One day with missing bars would have cut a 859-stock choice set to 40 |

**Produces:** §3's point-in-time rule. The check and violation counts are outputs of the run: they go
in the run's provenance record (`audit.json`, R6) and in §4.0.

---

## 5. Pre-register the design

**Goal:** fix, before any result exists, everything that could otherwise be chosen after seeing it.

**Write, in §2 and §3 of the write-up, before running anything:**

1. **The hypothesis**, stated so it can fail, and the outcome you expect.
2. **What you already know** — earlier runs, a pilot — disclosed so a reader can discount it.
3. **The null**, specified as in N3, with its table. If there is more than one null, which one
   decides and what happens if they disagree.
4. **The statistic** the null is judged on, its direction, before or after cost, how it is
   aggregated, and **why it answers the hypothesis** (N6.3).
5. **The pass mark** — the percentile or p-value a primary criterion must clear (N6.1 gives the
   default), and the number of draws, enough for that mark after any multiplicity adjustment (N6.2).
6. **Validity gates** — checks that must pass before any result is read: the independent check, the
   point-in-time count, the regression gate, the null holding its table (N5), the controls (N6.7).
7. **Reportability gates** — conditions without which a setting's number may not be quoted (for
   example, the pool must be larger than the portfolio; N7) — and which settings you expect to fail.
8. **Pass criteria** — a table of exact thresholds and counts.
9. **Robustness checks** — leave-one-period-out, agreement across estimators (mean, median, trimmed
   mean), splits by market direction and volatility — and the multiplicity: how many settings, which
   p-values are adjusted, and how (N6.8).
10. **The reference setting**, chosen by its position in the grid — the middle value of each
    parameter — never by its result.
11. **The effective sample size and the MDE** for every criterion that could fail (task 9 says how),
    written in §3 now, along with the rest of §3: data, construction, point-in-time rule, execution
    and cost, known contaminants.
12. **What is descriptive only** and generates no claims.
13. **How the test works, in plain words** (§3) — the walkthrough below, written now, with the places
    for its real numbers marked. `analyse.py` fills them after the run (task 9).

**The plain-words walkthrough.** §3's construction steps are written for someone rebuilding the code;
the walkthrough is written for someone who knows markets but has never seen the code, and must let
them redo one decision and one null draw by hand. It covers, in this order:

| Part | What it says | Its worked example (real numbers, printed by `analyse.py`) |
|---|---|---|
| **The series** | Every price or level the test reads, where it comes from (the data review's component map), and how each derived one was built — the splice, the rebuild, the adjustment — restated in a paragraph, not only cited | Each series' first and last value, and one splice date with the values on either side |
| **One decision** | What the rule looks at on a decision date, what it computes, the threshold, the target it sets, and when and at what price the trade happens | One real row of the decision log: the date, the inputs, the computed value, the target, the trade date and price |
| **The result of one path** | How the daily value is built from units and prices, and how the statistic is computed from it | The path's start and end value, its sessions, and its statistic |
| **One null draw** | What a draw is in words; what is randomised and what is kept identical; how many draws there are and why; which draws are excluded and why | One real draw: its identifier (the shift k, or the seed), the first stretch of the real and the randomised series side by side (for a timing rule, 20 or so weeks of in/out), and the draw's statistic |
| **The ranking** | How the result is placed among the draws, how ties count, what the percentile and the p-value mean in one sentence each, and the pass mark | One realisation: the result, the number of draws below, equal and above, the percentile, the p-value, the null's median and the edge |
| **The comparators** | What each benchmark is (buy-and-hold, a constant mix) and how it is computed | Each comparator's statistic on the same realisation |

A walkthrough that would let a reader rebuild the method but not one draw of it is not finished. If a
part does not apply, say why.

**Rules for criteria:**

| Rule | Why |
|---|---|
| **Hold data back.** Keep a stretch of history unseen until the design is fixed, then run the final test on it once. Tune anything — thresholds, prompts — only outside it. If a criterion needs more than one look to pass, it has failed | One research line found the same "result" three times: strong in the months used to discover it, gone everywhere else |
| **Make every criterion satisfiable.** Check each count against the shape of the grid, and write counts as fractions of what each setting actually has, rounded up. Check that the null can deliver the pass mark (a time shift with 40 draws cannot reach the 99th percentile) | "≥ 3 of 4 start dates" was impossible for settings that only had 2 |
| **Make every criterion complete.** State every count and every choice, or the analysis script will make it for you silently | An unstated count let a script use "≥ 1", which changed which variants passed |
| **Change one thing at a time**, or plan an extra run that separates the changes | Two changes made together read +1.9pp and −0.7pp separately; together they were one meaningless number |
| **Optional: an outcome map** — each possible pattern of results and the conclusion it will lead to, written now | It removes interpretation from the moment judgement is least reliable |

If you looked at data before writing criteria, say so at the top of §2, quote what you saw in full,
and set thresholds by the default pass mark (N6.1) rather than by what you saw.

**Produces:** §2 and §3 of the write-up, frozen together with §1. **Done when** every row of the null
table and every criterion is filled, and nothing in them depends on a number you have not yet seen.

---

## 6. Build the engine

**Goal:** code that produces the result exactly as the design describes, and leaves a complete
evidence trail.

- **A trading backtest follows the backtest convention** (R1): decide on session T's close, make
  every trade at the next session's OHLC4, hold shares, and compute the index as cash + Σ shares ×
  price.
- **The null runs through the same code path** as the strategy, with only the tested ingredient
  randomised (N5).
- **Write every run to `tests/T<NN>/evidence/<run>/`**: a summary per setting; every realisation,
  strategy and null draws alike; a ledger of every decision; the daily path where there is one; and
  `audit.json` (R6).
- **Assert point in time** in the code, and count the checks (task 4).
- **New behaviour is off by default**, so earlier results stay reproducible bit for bit.
- **Refuse, don't warn,** on any combination of settings that would produce a plausible number that
  means something else.
- **Make it deterministic**: fixed seeds from a stated formula, ties broken on a stated key, static
  inputs.
- **Model outputs are data, not code**: generate them once, ship them as a file in `evidence/`, and
  never call the model from the analysis (R6).

**Done when** one setting runs end to end and its evidence folder is complete.

---

## 7. Build the independent check

**Goal:** a second route to the same number, written without reusing the engine, so that a bug would
have to be written twice to survive.

- **For a trading backtest, a closed-form check.** Pick the one setting whose answer is a formula —
  an equal-weight portfolio with no buffer, no cost, weights reset each period and every slot filled
  (R1.6) — and re-derive it from the raw inputs. That is usually not the reference setting, so also
  re-derive the reference setting's decision log (R6) for one start date with a second script.
- **For an event study or a classifier,** re-derive each event's or decision's window return and
  benchmark from the raw price and event files, joined by your own code, and compare row by row on
  the reference setting.
- **Controls (N6.7):** an oracle signal (labels set from the realised future return) must reach the
  top of the null; at least 100 uninformative signals that look like the real one must clear the pass
  mark at about its nominal rate; a signal planted at the MDE must clear it about 80% of the time.
- **Check the checker both ways**: it must pass known-good output *and* fail a deliberately corrupted
  copy.
- **Regression gate**: after any code change, rerun the previous test and require identical numbers.
- The check **exits non-zero** on any gap above its stated tolerance, on any missing row, and when it
  compared nothing.

In one project a closed-form check caught three real defects; every one of them had produced a curve
that looked right.

**Done when** the check passes on its own setting and fails on a corrupted copy, and the controls are
built.

---

## 8. Run and gate

**Goal:** produce the evidence, then refuse to read it until the gates pass.

1. Run `run_grid.sh`; each run writes its own evidence folder and console log.
2. Run every validity gate: the independent check, the point-in-time count, the regression gate,
   the null check (N5), the controls (N6.7).
3. **If any gate fails, stop.** Nothing downstream may be read, quoted or summarised until it is
   fixed and rerun.
4. Apply the reportability gates, and mark failing settings **NOT REPORTABLE** rather than quoting
   them.

**Done when** every gate's result is printed by a script and recorded at the top of §4.

---

## 9. Read the results

**Goal:** say what the evidence supports — no more.

In this order:

0. **The worked example** — the walkthrough's real numbers (task 5, item 13), printed by
   `analyse.py` from the decision log and the stored draws: one decision, one path, one null draw,
   one ranking. A reader checks these by hand before reading anything else.
1. **The null check** — strategy against null on every dimension the null was meant to hold, and
   the size of every mismatch (N5).
2. **The headline** — each result beside its null, its statistic, its percentile and p-value (with
   the number of draws), and its calibration ratio (N6.6); before and after cost wherever a trade is
   modelled.
3. **How much evidence there is:**
   - **Count independent observations, not rows.** Overlapping holding periods are one observation
     seen several times — one study had about 10 independent periods, not the 1,449 trades it
     appeared to have. When observations overlap, use a Newey–West (HAC) standard error with at least
     h − 1 lags for h-period returns sampled every period (more if the signal is persistent), read
     against a t distribution with n_eff − 1 degrees of freedom. HAC is unreliable below about 30
     independent observations: there, also compute the non-overlapping version (every h-th period
     only) and quote the larger standard error.
   - **Print the MDE computed before the run (§3)** beside every failed criterion: "undetectable
     below X", never "no effect". At 80% power, for the test as pre-registered:
     - a percentile criterion ("above the q-th percentile of the null"):
       `MDE = (z_q + 0.84) × sd of the null statistic` — 2.5× the null's spread for the 95th
       (1.645 + 0.84), 3.2× for the 99th. The null draws reveal nothing about the result, so this can
       be computed first. If the calibration ratio is below 1, use the active standard error (N6.6)
       instead of the null's spread.
     - a t-test on n_eff independent observations: `MDE = (z + 0.84) × sd / √n_eff` — 2.8× the
       standard error two-sided at 5% (1.96 + 0.84), 2.5× one-sided.
     - Give it in the criterion's own units (pp of total return, rank-correlation points, pp per
       event). If the realised sample differs from the plan, recompute it in a dated block beside the
       original, never in place of it.
   - **Report distinct realisations beside setting counts.** 18 settings on a thin pool were 10
     distinct portfolios.
4. **Robustness** — the pre-registered checks; an edge one month carries is one month's edge.
5. **Multiplicity** — how many settings, variants, prompts and ideas were tried on this window; the
   best setting against the best-of-sweep null; the adjusted p-values (N6.8). Every idea tested goes
   on the record, dead or alive, so a reader can see how many were tried before one worked.
6. **The verdict table** — one row per criterion: PASS or FAIL, with the MDE beside each FAIL. Then a
   verdict per hypothesis.

**Produces:** §4 of the write-up, every number printed by `analyse.py`. **Done when** each criterion
has a verdict and nothing in §4 was typed.

---

## 10. Log the findings

**Goal:** turn each claim into a record whose status travels with it.

- **One finding per claim**, with an ID from the project's counter, a status, the evidence path, the
  claim with its numbers and denominators, **what would falsify it**, and a command that reproduces
  it (format in R4).
- **Record kills as carefully as survivors.** A refuted idea, written down, is what makes the next
  survivor believable.
- **List what the test does not establish** in two lists, never merged: tested and inconclusive;
  not tested at all.
- **List the next things to do**, ordered by what would change a decision most per unit of effort.

**Done when** every claim in §4 has an entry, and the project README's register lists them.

---

## 11. Report, revise, retire

**Goal:** a number quoted anywhere still means what the test said it means.

- **Every test ends with a results page** — an HTML file generated by a script from the evidence,
  built to R10: one backtest shown end to end, a start and end date on every number and every curve,
  and the formula beside every statistic. A page that fails its own check (R10) is not published.
- Quote every number as N9 shows: with its setting, its window, its null, its statistic, its
  percentile and draws, before and after cost, its finding ID and status, and the largest open
  caveat (R7).
- When a later test replaces a result, **banner the old write-up** — what changed, old and new
  numbers side by side, what still stands — and set its status to SUPERSEDED. Never edit the old
  numbers.
- A revised finding says what it revises; a killed one stays, marked REFUTED.

---

# Part 2 — The null book

## N1. What a null is

A **null** answers one question: *what would I have seen if my idea were worthless?*

You build it by running **the same experiment** — same universe, same dates, same rules, same
costs — with **one ingredient replaced by randomness**: the ingredient your hypothesis says carries
information. Run it many times (each run is a *draw*), and you get the range of results that luck
alone produces. Your real result is then judged by where it falls in that range.

A null is not:

| Not a null | What it is | Why it is not enough |
|---|---|---|
| **A benchmark** (an index, an equal-weight universe, buy-and-hold) | a level to beat | It does not share your pool, your rules or your costs, so beating it can come from any of those |
| **A bootstrap** | an estimate of how uncertain your own statistic is | It resamples your result; it says nothing about what chance would produce |
| **A train/test split** | protection against overfitting | A result can survive out of sample and still be no better than chance |
| **A positive control** | a known signal planted to prove the pipeline can see one | It checks the measuring instrument, not the idea (N6.7) |

**Why you need one.** A "+17%" screen in one study reproduced its claimed return exactly — and the
same portfolio without the screen earned more on the same dates. It had never been compared with
anything. A bare return is not a result.

---

## N2. The one-ingredient rule

**Randomise exactly the ingredient the hypothesis claims carries information. Hold everything else
fixed.**

| If the hypothesis is… | The ingredient is… | Randomise it by… |
|---|---|---|
| "Ranking stocks by X picks better stocks" | the order X imposes | shuffling the order on each date (N4.1) |
| "Being in the index only when rule R says so beats chance" | *when* you are in | rearranging the in and out spells (N4.9) |
| "Stocks with feature Y beat the others" | which stocks have Y | assigning Y to random stocks, keeping the count (N4.5) |
| "Excluding stocks with Z helps" | which stocks are excluded | excluding the same number at random (N4.6) |
| "Stocks that *beat estimates* move after results" | which announcements are beats | permuting the beat label among the same date's announcements (N4.8) |
| "Stocks move after *any* event E" | when the events happen | placebo events (N4.7) |
| "The model's buy labels pick winners" | which candidates are labelled buy | permuting labels within each date (N4.8) |
| "Signal S predicts at the right time" | the alignment of S with returns | shifting S in time (N4.4) |

If you randomise two things at once, you cannot tell which one the result is about. If you
randomise something other than the claimed ingredient, the null answers a different question —
randomising the *date* of a results announcement when the claim is about *beats* credits beats with
the whole announcement effect.

---

## N3. Designing a null in seven steps

1. **Name the ingredient** (N2), in one sentence.
2. **List every other dimension of the experiment.** The pool of candidates on each date; how many
   names the strategy holds on each date; the calendar; the start dates; the weights; the rules
   (bands, caps, filters); the cost model; the risk and style of what gets held (volatility, size,
   sector, liquidity); how persistent the holdings are from one period to the next. For a timing
   rule: the fraction of time invested, the number of entries and exits, and how long each spell
   lasts.
3. **Decide how each is held**: constant for the run, matched to the strategy **on each date**, or
   matched per start date. Default to *per date* — it is the only way to match a strategy whose pool
   or portfolio size changes over time.
4. **Choose the randomisation** — permute, give a random score, shift in time, rearrange spells, or
   draw at random (N4).
5. **Predict what the randomisation breaks.** Shuffling the order every date destroys persistence, so
   the null trades more; drawing random names destroys the strategy's style tilt, so the null is
   calmer than reality. Decide whether to repair it (a stratified shuffle, N4.2; a persistent score,
   N4.3; a time shift, N4.4) or to report it.
6. **Choose the statistic, the pass mark and the number of draws** (N6).
7. **Write the specification table** (N9), and the measurements that will prove it held (N5).

---

## N4. The families of null

### N4.1 Per-date shuffle of the signal

**Tests:** does the signal's *order* carry information?
**Recipe:** on each date, take the eligible pool, shuffle it at random, and feed the shuffled list to
the strategy in place of the ranked list. Everything downstream — selection, bands, weights, costs —
runs unchanged. Repeat for each draw with a new seed.

```
for draw in 1..D:
    for date in rebalance_dates:
        pool  = eligible(date)                          # identical to the strategy's pool
        order = random_permutation(pool, seed(draw, date))
        book  = strategy_rules(order, previous_book)    # identical rules
    result[draw] = statistic(book_path)
```

**Holds:** the pool and the number of names on every date, the calendar, the rules, the cost model.
**Breaks:** persistence (a fresh shuffle each date keeps few names), so the null trades more and
pays more cost; style exposure (random names are not tilted like the signal's picks).
**Bias:** anti-conservative when the signal is persistent or tilted — the null is calmer than reality.
**Use when:** the default null for a stock-picking strategy. Read the **before-cost** edge for
selection skill, since the after-cost edge includes the strategy's lower turnover.
**Does not work** for a single asset: with one name the shuffle returns the strategy itself. Use N4.9.

### N4.2 Stratified shuffle

**Tests:** does the signal carry information *beyond* its style tilt?
**Recipe:** on each date, put every name in the pool in a bucket using data known at T — its sector,
or its size or volatility tercile computed on that date's pool. **Permute the signal's values among
the names inside each bucket**, then rank the whole pool on the permuted values and run the strategy
unchanged. Each bucket keeps its own set of values, so the null picks as many names from each bucket
as the strategy does on that date.
**Keep buckets wide.** Crossing sector × size × volatility on a 100-name pool leaves cells of one or
two names, where the shuffle has no freedom and the null becomes the strategy. Stratify on one or two
variables, report the share of picks in cells where every name is picked, and treat a high share as a
failed reportability gate.
**Holds:** everything N4.1 holds, plus the per-bucket counts. It does **not** hold the tilt *within* a
bucket — the signal may still pick the calmest names of the calm tercile — so measure that (N5).
**Breaks:** persistence.

### N4.3 Persistent random score

**Tests:** does the signal's order beat a random order that is *as sticky* as the real signal?
**Recipe:** give each name a random score that drifts slowly:
`s_t = ρ × s_(t−1) + √(1 − ρ²) × e_t`, with `e` standard normal per name and date, and a new name
starting at a fresh `e`. Fix ρ by a pre-registered rule: the value at which the null's names replaced
per rebalance match the strategy's, tuned on null runs alone. ρ = 1 — one score for the whole run —
is the extreme case: a name then leaves only when it leaves the pool, so that null is stickier than
any real signal and brackets the strategy from the side opposite N4.1.
**Holds:** everything N4.1 holds, plus turnover when ρ is matched (show it in the null check).
**Breaks:** style exposure. **Bias:** with ρ matched, it closes N4.1's turnover gap; it is still too
calm if the signal has a style tilt, so pair it with N4.2.

### N4.4 Time shift

**Tests:** is the signal's *timing* informative, beyond its persistence and tilt?
**Recipe:** keep each rebalance date's real pool, rules, calendar and cost; rank that pool by the
signal dated k rebalance periods away, and rerun. Shift in whole periods. Drop names in the pool that
have no signal at the shifted date, and count them for every k.
**Which k are allowed.** A shift is a null only if the shifted signal can neither see the returns
being traded nor still carry their information. Let L = the signal's lookback and h = the holding
period, in rebalance periods.
- *A signal taken from the future* (a lead of k): exclude k < L + h. A twelve-month momentum score
  dated six months later is built from the very returns being traded — look-ahead inside the null,
  which makes the null look strong.
- *A signal taken from the past* (a lag of k): exclude k < h, and every k inside the signal's memory —
  the lag at which the rank correlation between the signal on d and on d + k (averaged over d) falls
  below about 0.2 (for a timing rule, the autocorrelation of the in/out series). A slow signal such as
  earnings yield barely re-ranks in a few months, so a short lag is not random: that null asks "does
  fresh beat stale?", not "does it beat chance?".
- Write the excluded band, and print the rank correlation for every k used.

**Circular or not.** Default to circular — the series wraps around, so every draw has the real run's
length and total return stays comparable. A non-circular shift shortens the overlap as k grows; if you
use one, judge only on a per-period statistic (mean period return, mean rank correlation) over each
draw's own dates, never on total return.
**Holds:** the signal's own persistence and tilt. **Breaks:** its alignment with returns.
**Valid only if** the relation is stable across the window; a tilt whose factor paid in one half and
not the other moves with the shift and blurs the null.
**Draws:** one per allowed k, no seed. Neighbouring shifts are strongly correlated, so the effective
number of draws is about window ÷ max(h, signal memory) — often 10 to 30. Write its criteria as counts
("beats at least 38 of 40 shifts"), never as a percentile finer than 100 ÷ K points (N6.2).
**Use when:** the per-date shuffle and the persistent score may be too calm. In one study the same
spread sat at the **100th** percentile of a per-date shuffle and the **27th** of a time shift.

### N4.5 Random selection of the same count from the same pool

**Tests:** do the chosen names beat names chosen at random from the same candidates?
**Recipe:** on each date, draw as many names at random as the strategy chose, from the same pool,
with no rules.
**Holds:** the pool and the count. **Breaks:** every mechanic of the strategy — bands, holding rules.
**Use when:** the strategy has no mechanics beyond picking; otherwise prefer N4.1.

### N4.6 Size-matched random exclusion

**Tests:** does a *filter* help, beyond the fact that it shrinks the pool?
**Recipe:** on each date, remove as many names at random as the filter removes, then run the
strategy on what is left.
**Holds:** how many names are removed, and everything downstream. **Breaks:** whatever the removed
names have in common. **Use when:** testing a screen or exclusion rule, not a ranking.

### N4.7 Placebo events

**Tests:** does *any* event of this kind move stocks — not a particular feature of the event (for a
feature, use N4.8)?
**Recipe:** keep the number of events and the window, and choose one of two placebos — they hold
different things:
- *same name, random date* — holds the stock (size, sector, volatility) and breaks the date (season,
  market state). Draw dates with the real events' day-of-week and calendar-month mix.
- *same date, random name* — holds the date and its market move, and breaks the stock. Draw within the
  event's size and sector bucket if those matter.

**Draw only name-dates outside every real event window of that name** — in results season a random
name on the same date is often reporting itself — and report how many draws were rejected.
**Judge with** standard errors clustered by calendar period at least as long as the window: events on
the same day share one market move, and so do events whose windows overlap.

### N4.8 Label permutation — for a classifier, a judge, or a feature of an event

**Tests:** do the labels (buy/avoid, beat/miss) pick winners, or would random labels do as well?
**Recipe:** on each date, permute the labels across that date's candidates, keeping the number of
each label per date. Score the picks-minus-rejects return. Use 1,000 draws.
**Holds:** the candidates, the number of picks per date, the dates. **Breaks:** any link between
label and stock.
**Persistent labels.** If the same stock carries the same label on consecutive dates with overlapping
return windows, a per-date permutation scatters one repeated bet into independent ones and the null is
too calm. Keep one decision per stock per open window (drop the repeats and count them), or permute in
blocks that keep each stock's run of labels together.
**Also:** drop dates where every candidate has the same label (they carry no information) and count
them; pre-register whether picks-minus-rejects is averaged per decision or per date (default per date,
so busy days do not dominate); and compare what was rejected with what was kept — in one study a
model's veto was inverted, and the names it removed beat the names it kept.

### N4.9 Random timing at matched exposure

**Tests:** does a timing rule — in one asset or index, or in cash — choose *when* better than chance?
**Why the others do not fit:** with one asset the pool *is* the asset, so a per-date shuffle returns
the strategy itself. The ingredient is not *which* name but *when*.
**Recipe:** after the warm-up (the sessions the longest input needs, such as 200 for a 200-day
average), take the rule's daily in/out series and cut it into spells — maximal runs of "in" and of
"out". For each draw, shuffle the order of the in-spells and, separately, of the out-spells;
re-interleave them, starting in the rule's first state; and run the result through the same engine
(R1). Use 1,000 draws.
**Holds:** the asset, the calendar, the cost, the cash rate, the fraction of sessions invested, the
number of entries and exits, and every spell's length. **Breaks:** only *when* the spells fall. When the
rule decides weekly and the engine trades daily, the spells are in weeks: invested weeks are then held
exactly and invested sessions only approximately (a week has 3 to 5 sessions; F-AA-M06). Report sessions
invested per draw.
**Secondary null:** a circular time shift of the in/out series (N4.4), at shifts beyond the longest
lookback and the longest spell.
**Evidence:** count round trips, not sessions — a 50/200-day crossover on 25 years of an index makes a
few dozen. Compute the MDE from that count.
**Benchmarks beside it (not nulls):** buy-and-hold, and a constant mix at the rule's average exposure
f (f in the asset, 1 − f in cash, rebalanced on the same calendar). Most of a timing rule's lower
drawdown is lower exposure; the constant mix shows how much.

### N4.10 Random timing with free spell lengths

**Tests:** does a timing rule choose *when* better than chance when the null may also use spell lengths
the rule never had? N4.9 holds every spell's length, so a rule whose few long spells happen to sit on
large moves can still beat reorderings of itself; this null asks whether the lengths matter.
**Recipe:** take the rule's first state, its number of in-spells k_in and out-spells k_out, and the total
weeks in (S_in) and out (S_out). For each draw pick k_in in-spell lengths in [lo, HI_in] summing to S_in,
uniformly over all ordered tuples, and k_out out-spell lengths in [lo, HI_out] summing to S_out,
independently; alternate them starting in the rule's first state; run the result through the same engine
(R1). lo is the shortest spell worth calling a switch (T06: 2 weeks); HI are the rule's own longest
spells, so the rule and every N4.9 draw lie inside the allowed set (check it).
**Exact sampler, no rejection:** c(m, t) = the number of ways to write t as m integers in [lo, hi], with
c(0, 0) = 1 and c(m, t) = Σ_x c(m − 1, t − x). Draw the parts one at a time with P(x) ∝ c(m − 1, t − x),
using `rng.random()` and a cumulative-sum search (not `Generator.choice`, so draws do not change across
numpy versions). Check the count against inclusion–exclusion and the sampler by enumerating a small case.
**Holds:** the asset, calendar, cost, cash, first state, the number of entries and exits, the total weeks
invested. **Breaks:** when the spells fall and how long each is. **Reports, does not hold:** sessions
invested (see N4.9).
**Use:** beside N4.9, never instead. Pre-register which decides and the bounds before looking at any
return, and disclose how the bounds were chosen (T06's came from the rule's longest spells, and were
fixed after seeing a best N4.9 draw). In the one test so far (T06: three-index switch, four books,
9 round trips) it gave percentiles within 1.3 points of N4.9's and no wider spread.

### N4.11 Random timing of a second signal (one null per timing)

**Tests:** a rule can have two timing components: a main switch (in or out) and a second signal that sets
what the book holds in one of the states (a gold signal that splits the out-of-market sleeve 80/20 or
20/80). Does the second signal time better than chance, with the main switch real? A null that
randomises only the main switch cannot say, and one that randomises both at once cannot say which of the
two a result is about (N2).
**Recipe:** keep the main series real. Cut the second signal's series into its spells (first state, k per
state, total weeks per state) and draw them as N4.9 (shuffle) or N4.10 (free lengths, the exact sampler),
with bounds per state set from the real series before any return is read: lo = the smaller of 2 weeks and
its shortest spell, hi = its longest spell of that state. Run each draw through the same engine (R1), so
the draw trades only where the real main series lets it.
**Holds:** the main series, calendar, cost, cash, the second signal's first state, number of switches and
total weeks in each state. **Breaks:** when the second signal's spells fall and how long each is.
**Reports, does not hold:** how many drawn flips reach the book (a flip in a week the main series is
in the other state never trades), so the draws' trade counts vary.
**Use:** one deciding null per timing, each holding the other timing real; the joint null (both random) is
a robustness check only, because the main switch can carry it. In the one test so far (T08: three-index
switch with a MAUc1-timed sleeve) the equity switch beat random in-or-out timing (CAGR percentiles 94 to
97), while the gold timing sat at percentiles 61 to 62 against random gold timing (and the joint null
read 95 to 98). The joint null alone would have hidden that.

### Choosing among them

| Your situation | Start with | Add |
|---|---|---|
| A stock-picking strategy with rules | N4.1 | N4.2 if its picks are tilted; N4.3 (ρ matched) or N4.4 if it is persistent |
| A timing rule on one asset | N4.9 | the circular time shift; N4.10 if its few long spells might be luck; buy-and-hold and the constant-exposure mix as benchmarks |
| A timing rule with a second timed signal (for example a timed sleeve split) | N4.9 and N4.10 on the main switch with the second signal real | N4.11 on the second signal with the main switch real; both random only as a robustness check |
| A cross-sectional score (no portfolio) | N4.1 | N4.3 and N4.4 — run all three and pre-register which decides |
| A filter or screen | N4.6 | N4.1 on the filtered pool |
| A feature of an event (a beat, a type of news) | N4.8 among same-date events | N4.7 for "does any event move it" |
| Any event | N4.7 | a matched benchmark over each event's own window |
| A model's labels | N4.8 | the rejected-vs-kept comparison; the controls (N6.7) |
| A parameter sweep | each setting's own null | the best-of-sweep null (N6.8) |

---

## N5. What "held identical" really requires

**Match per date, not on average.** If the strategy holds 15 names on some dates and 4 on others
(because the pool was thin), the null must hold 15 and 4 on the same dates. Running the null through
the same selection code on the same pool achieves this automatically; drawing "the average number"
does not.

**The null is the strategy with a random signal, not a random portfolio.** Every rule — bands,
caps, weights, calendar, cost — runs on the null's own holdings. Otherwise the comparison measures
your rules plus your signal against neither.

**Measure it; do not assert it.** The first table of the results compares strategy and null on
every dimension in the specification:

| Dimension | Strategy | Null | Should be |
|---|---|---|---|
| pool size per date (range) | | | identical |
| names held per date (range, mean) — or, for a timing rule, fraction invested, entries and exits | | | identical |
| names replaced per rebalance | | | the mismatch, shown |
| volatility, drawdown, exposures | | | the mismatch, shown |

In one study the null held exactly the strategy's 15 names on every date — but replaced 14.7 of them
each rebalance against the strategy's 12.5, and its portfolios were more volatile (0.196 vs 0.175).
Both mismatches were real, and both changed how the edge should be read.

**A null that fails to hold what it claims is a failed validity gate**, not a footnote.

---

## N6. Judging a result against its null

### N6.1 The percentile, the p-value and the pass mark

**The percentile** says where the result sits. For each start date (or other independent unit), rank
the strategy's statistic x among that unit's D null draws, counting ties as half:

```
percentile = 100 × ( #{null < x − ε} + #{null ≤ x + ε} ) / (2 × D)          ε = 1e-12
```

Then take the median across start dates. The tolerance ε matters: where strategy and null are the
same portfolio, floating-point dust makes a strict percentile read a confident 88 instead of 50.
**Never pool null draws across start dates**; rank each against its own.

**The p-value** is what a test uses:

```
p = (1 + #{null ≥ x − ε}) / (D + 1)        one-sided, higher is better (flip ≥ to ≤ where lower is better)
```

It is never 0: with 200 draws the smallest possible p is 1/201 = 0.005, so "the 100th percentile"
means "p ≤ 0.005". Ties count against the strategy, so where strategy and null are the same book,
p = 1.

**The default pass mark**, unless the hypothesis argues for another (write the one you use in §2):
- p ≤ 0.05 (the 95th percentile) on the deciding null, start date by start date;
- the median across start dates clears it;
- at least ⌈0.75 × S⌉ of the S start dates clear it (if S = 1, that one).

### N6.2 How many draws

The percentile is itself an estimate. With D draws its standard error near percentile p (as a
fraction: 0.95, not 95) is about `100 × √(p(1−p)/D)` points — ±1.5 at the 95th with 200 draws. So:
- **at least 200 draws for a headline, and at least 1,000 for any claim beyond the 99th percentile** —
  with 200 draws, "99th" rests on two draws;
- **enough for the multiplicity adjustment:** if m p-values will be adjusted at level α (N6.8), the
  smallest must be able to reach α ÷ m, so **D + 1 ≥ m ÷ α** at the very least — 24 settings at 5% need
  at least 480 draws; with 200, no setting could ever pass. Use several times the minimum;
- **a time shift cannot reach 200 draws** (N4.4): quote it as "beats k of K shifts", with K stated.

### N6.3 Which statistic

A percentile ranks the strategy **on one statistic**, and another statistic can give another answer.
Choose it before running, from the hypothesis:

| The hypothesis says | Judge on |
|---|---|
| it picks better than chance | total return |
| it earns more per unit of risk | Sharpe ratio, volatility |
| it hurts less | maximum drawdown |
| it works on the typical stock, not just the tail | median return, hit rate |
| it orders the cross-section | rank correlation, top-minus-bottom spread |

- **Some statistics are the same test.** When every draw covers the same span, CAGR ranks exactly like
  total return — reporting both adds nothing.
- **Report the others as secondary**, each with its own percentile, and say whether the verdict
  depends on the choice. In one study the verdict held on every statistic, but strength did not: the
  drawdown percentile cleared the 90th in 7 of 24 settings where total return cleared it in 17, and
  the volatility percentile showed the strategy's portfolios were simply calmer than random ones.
- **Always quote a percentile with its statistic and draws**: "99.5th percentile of 1,000 draws on
  after-cost total return".

### N6.4 The edge

`edge = the strategy's median − the null's median`, in percentage points. It says how much better;
the percentile says how unusual. If the null median is pooled across start dates for the edge, say
so where it is quoted.

### N6.5 Before and after cost

Where a trade is modelled, judge both. A null that trades more pays more cost, so the after-cost
edge includes a turnover advantage; **the before-cost edge measures selection**. A test with no
trade — an event study, labels scored per decision — says "cost: none — not a tradable return" and
is never quoted as an edge a portfolio could earn.

### N6.6 Is the null as noisy as reality?

A permutation null holds the market path fixed: every draw lives through the same days, so its
spread measures only how much *picking* varies. If the strategy's picks carry a tilt (a factor, a
sector, low volatility), the real result also carries that factor's luck, which no draw shares — and
then anything looks extreme. **Print the ratio beside every percentile:**

```
calibration = sd(statistic across null draws) / SE of the strategy's ACTIVE statistic
```

The **active statistic** is the strategy's statistic minus the same statistic for the pool's
equal-weight portfolio on the same dates, so the market's move cancels, as it does across null
draws. For total return: SE = sd(active log return per non-overlapping period) × √(number of
periods), HAC if they overlap (task 9). For a statistic with no simple standard error (drawdown), take
it from a block bootstrap of the active daily returns, with blocks at least one holding period long.
**Never use the raw statistic's standard error**: it contains the market's variance and puts the
ratio far below 1 for every long-only test, whatever the null.

The ratio is a diagnostic, not a correction. Below 1, the distance from the null's median in null
standard deviations is too large by about 1 ÷ ratio. To read a percentile honestly, convert it:
`z = Φ⁻¹(percentile / 100) × ratio`. At a ratio of 0.34, a 99th percentile (z = 2.33) becomes
z = 0.79 — about the 79th. A percentile answers "better than random picks from this pool on these
days?", never "reliably positive?" — that is the MDE's job.

### N6.7 Controls: check the null and the pipeline themselves

- **Negative control — the false-positive rate.** Ranking one null draw among the other draws of the
  same null is uniform by construction and proves nothing. Instead, build K ≥ 100 signals that carry
  no information but look like the real one — the real signal time-shifted outside the excluded band
  (N4.4), or a random score with the real signal's persistence (N4.3, ρ matched), drawn within the same
  buckets where the signal is tilted (N4.2). Run each through the **strategy's** code path and judge it
  against the null exactly as the real result will be judged. The share that clears the pass mark
  must be close to its nominal rate: for the 95th percentile, 5% ± 2 × √(0.05 × 0.95 / K) — 0.6% to
  9.4% for K = 100. More means the null is too calm and every percentile is overstated; fewer means the
  null is too hard to beat.
- **Positive control — the oracle.** Labels set from the realised future return must reach the top of
  the null. If they do not, the pipeline cannot see an edge at all.
- **Positive control — at the size you claim to detect.** Plant a signal whose true edge equals the
  MDE (the realised return plus noise, scaled so the expected edge is the MDE), K times with fresh
  noise. It should clear the pass mark in about 80% of plantings. Far fewer means the MDE is wrong,
  and so is every "undetectable below X".

### N6.8 Many settings, many nulls, many ideas

- **Many settings — the best-of-sweep null.** The eye goes to the best row, so judge the best row
  against the best of chance:
  1. **Share the randomness across settings.** Draw d must use the same random scores in every setting
     — seed one random number per (draw, name, date) and rank by it — so the null keeps the real
     correlation between settings.
  2. **Put settings on one scale.** For each setting and draw, convert the statistic to its p-value
     within that setting's own null; a raw maximum is won by the noisiest setting.
  3. For each draw, take the smallest p-value across settings. The real best setting, chosen by the
     same rule, has adjusted `p = (1 + #{draws whose smallest p ≤ the real smallest p}) / (D + 1)`.
     Report it beside the unadjusted percentile.
- **Several nulls:** run them, name the deciding one in advance, and pre-register the conclusion if
  they disagree (for example: the softer null passes and the stricter fails → inconclusive; build a
  better-matched null before claiming anything).
- **Several related p-values — Holm–Bonferroni.** Name the family and its size m in §2. Sort the
  p-values ascending; compare the i-th smallest with α ÷ (m − i + 1); reject while it passes, and stop
  at the first that fails. Holm is valid under any dependence but strict when the p-values are strongly
  correlated (settings of one strategy); there, the best-of-sweep null is more powerful.
- **Many ideas:** every idea, prompt and threshold tried on the test window is a setting. Keep them
  all on the record.

---

## N7. When the null misleads you

| Symptom | Likely cause | What to do |
|---|---|---|
| Percentiles near 100 everywhere, but the t-statistic of the active return is about 1 | the null is calmer than reality — no persistence, no style tilt | print the calibration ratio (N6.6); add a stratified shuffle, a matched persistent score or a time shift; run the negative control (N6.7) |
| Percentile exactly 50, or many null draws tied with the strategy | the null has no choice — the pool is no bigger than the portfolio, so strategy and null are the same book | a reportability gate: mark the setting NOT REPORTABLE |
| The null of a single-asset timing rule equals the strategy | a per-date shuffle of a pool of one | use random timing at matched exposure (N4.9) |
| The strategy beats its null only after cost | a turnover advantage, not selection | read the before-cost edge |
| The verdict flips between two nulls | the choice of null decides the answer | the pre-registered deciding null decides; report both |
| The null holds a different number of names than the strategy | matched on average, not per date | run the null through the same selection code |
| A time-shift null looks strong, or absorbs the effect | shifts inside the signal's lookback or memory | exclude that band (N4.4) |
| The placebo gives a strong effect too | real events inside the placebo draws, or the wrong ingredient randomised | exclude every real event window (N4.7); for a feature of an event, permute the feature (N4.8) |
| Strategy and null differ only in their rules | the null skipped the strategy's mechanics | rerun the null through identical mechanics |
| A large edge but a modest percentile | wide null spread, or a pooled-vs-per-date mismatch | report both, and the calibration ratio |
| No setting can pass, however strong | too few draws for the multiplicity adjustment | D + 1 ≥ m ÷ α (N6.2) |
| The null was chosen after seeing results | a forking path | pre-register; if it already happened, say so, and test once more on held-back data |

---

## N8. Worked examples

These are illustrations of the method, not results.

**A. A momentum stock-picking strategy.** *Hypothesis:* ranking stocks by their return over the past
twelve months (skipping the latest month) and holding the top 15, rebalanced monthly, picks better
stocks than chance.

| Dimension | Randomised / held / not matched | How | Measured as |
|---|---|---|---|
| the ranking | randomised | the eligible pool shuffled each rebalance, 1,000 draws per start date | — |
| eligible pool | held | per date — the same list | pool range in both |
| names held | held | per date — the same selection code | names held, min / mean / max in both |
| calendar, start dates, band, weights, cost | held | constant | identical rules |
| persistence and turnover | not matched | a fresh shuffle keeps few names | names replaced per rebalance, strategy vs null; a ρ-matched persistent score (N4.3) as a secondary null |
| style and risk | not matched | random names are not tilted | volatility and drawdown, strategy vs null; a stratified shuffle (N4.2) as a secondary null |

*Judged on* total return per start date, before and after cost, median across start dates — because
the hypothesis is about picking. *Pass mark:* the default (N6.1). *Secondary:* Sharpe, drawdown,
volatility. *A time shift*, if used, must exclude leads shorter than 12 + 1 months (N4.4).

**B. An earnings event study.** *Hypothesis:* stocks that beat estimates outperform over the next
10 sessions. *The ingredient* is the beat, not the announcement — stocks move around any announcement,
so a placebo on non-earnings dates would credit beats with the whole announcement effect. *Deciding
null:* the beat label permuted among the announcements of the same date (or week, if days are thin),
keeping each date's number of beats (N4.8). *Secondary null:* placebo events — the same stocks on
random non-earnings dates outside every real earnings window, rejected draws reported (N4.7) — which
answers a different question: does any announcement move the stock? *Window:* the tradable return from
the first session that opens after each announcement, against the market over the same window.
*Judged on* beats minus non-beats, mean and median, with standard errors clustered by calendar period
at least as long as the window. *Cost:* none — not a tradable return.

**C. An LLM buy/avoid classifier.** *Hypothesis:* stocks the model labels "buy" from each day's news
beat the ones it labels "avoid". *Null:* labels permuted within each date, keeping each date's number
of buys, one decision per stock per open window; 1,000 draws (N4.8). *Point in time:* only decisions
after the model's training cutoff count toward the headline. *Controls:* the oracle reaches the top of
the null; 100 uninformative label sets clear the pass mark at about 5%; a signal planted at the MDE
clears it about 80% of the time (N6.7); the rejected names are compared with the kept ones. *Data:*
labels generated once and shipped as a file, with the model, prompt hash and date recorded.

**D. A market-timing rule.** *Hypothesis:* holding the Nifty 50 only while its 50-day average is above
its 200-day average, and cash otherwise, beats chance. *Null:* random timing at matched exposure — the
rule's in and out spells rearranged, 1,000 draws (N4.9); a circular time shift beyond 200 sessions and
the longest spell as a secondary null. *Held:* fraction invested, number of entries and exits, spell
lengths, cost, cash rate. *Benchmarks:* buy-and-hold, and the constant mix at the rule's average
exposure. *Judged on* total return and maximum drawdown, before and after cost. *Evidence:* round trips
— a few dozen — not sessions.

---

## N9. Writing the null down

**In §2 of the write-up, before running** — one table per null:

| Dimension | Randomised / held / not matched | How: constant, per date, or per start date | Measured in §4.0 as |
|---|---|---|---|
| *the ingredient under test* | randomised | *how it is randomised, how many draws* | — |
| *pool* | held | | |
| *number of names or events* (for a timing rule: fraction invested, entries and exits, spell lengths) | held | *per date if it varies* | |
| *calendar, start dates, rules, weights, cost* | held | | |
| *persistence / turnover* | *not matched?* | | |
| *risk and style* | *not matched?* | | |

Then: the deciding null if there is more than one; the statistic, its direction and **why**; the pass
mark and the number of draws; the secondary statistics.

**In §3, before running — the null in plain words** (part of the walkthrough, task 5 item 13). The
table says *what* is held; this says *how a draw is made*, so a reader could make one by hand. For a
circular time shift, for example:

> The rule's real decisions are a list of weekly targets, one per week of the window — 250 of them in
> a five-year window, each "in" or "out". A draw takes the same list and starts it k weeks later; the
> last k weeks wrap round to the front. Every k from 8 to 242 is one draw: 235 draws, no randomness.
> Shifts under 8 weeks are left out because a list moved by only a few weeks still lines up with the
> market moves the rule reacted to. Each draw is then run through the same engine, at the same cost,
> as the rule. It spends exactly as many weeks out as the rule, in spells of the same lengths, but at
> different times. If the rule's timing carries information, it should beat most of these draws.

Then a 20-week illustration (the real series and one shifted draw, side by side), the excluded band
and its reason, and what the draws do *not* hold.

**In §4.0, after running** — the worked example (task 9, step 0), then the null check (N5) and the
controls (N6.7), printed by a script.

**In every sentence that quotes the result:** "*X* (setting `<setting>`) returned +20.7% after cost
(+23.0% before) against its null's −1.3% (+2.5% before) — the 99.5th percentile of 1,000 draws on
after-cost total return (p = 0.006; calibration 0.9; 4 of 4 start dates above the null median).
Finding F-<P>-S03, PROVISIONAL: one window only."

---

# Part 3 — Reference

## R1. The backtest convention

Every quotable trading backtest runs one rule: **decide on session T's close; make every buy and
every sell on the next trading session, T+1, at OHLC4 = (O + H + L + C) / 4 of T+1's own bar; hold
the money as shares, units = money ÷ OHLC4; and compute the index as cash + Σ shares × price.**

### R1.1 The calendar

- **Sessions are the trading dates in the data**; "+1" is the next session, not the next calendar day:
  a Friday signal fills on Monday.
- **For a stock-picking strategy, rebalance dates are fixed from the session dates alone**, before any
  price or signal is read — for example the first session of every H-th week or month. Each of the H
  possible start dates is run as its own realisation. The signal decides *which* names trade, never
  *when*.
- **A timing rule rebalances every session** (H = 1, one start date): the signal on T sets the target
  weight for T+1, and a session whose target is unchanged trades nothing. This is the one case where
  the signal decides *when*.
- **The signal session is T = e − 1**, the last session strictly before the rebalance session e.
- **Every trade happens on e** — sells, trims, top-ups and buys. Period k's exit is period k+1's
  entry. The final rebalance only liquidates.

### R1.2 Eligibility and prices

- On T: a member of the universe as of T, a finite signal, enough history. On e: a fillable bar
  (OHLC4 finite and > 0). These apply to held names too: **a held name that fails any test is sold.**
  Decide explicitly whether a zero-volume bar counts as fillable.
- **OHLC4 of e's own bar** prices every trade on e and values the old book; **the close** is used for
  the signal and for daily marks between rebalances. All prices are adjusted (task 4).
- A held name with no fillable bar on e is valued and sold at its last close. That models a sale that
  may not have been possible; say so, or defer the sale — and count suspended and delisted names
  (task 4).

### R1.3 Money in shares

At every rebalance, in this order:

```
ow = cost_bps / 2 / 10,000                                    the one-way cost
1  nav_now = cash + Σ units_i × px_i          px = OHLC4 (or the fallback); before any trade
2  target  = the new book, from the signal, the rules and the band
3  sell every held name not in target:        cash += units × px × (1 − ow)
4  resize every retained name to its target weight w_i × nav_now (equal weight: nav_now / N):
     4a  first every trim   (delta < 0):  units −= |delta| / px;  cash += |delta| × (1 − ow)
     4b  then every top-up  (delta > 0):  v = min(delta, cash);  units += v × (1 − ow) / px;  cash −= v
5  buy every new name, in target order:
     stop once cash ≤ nav_now × 1e-12, and count the rest as unfunded
     budget = min(w_i × nav_now, cash);  units = budget × (1 − ow) / px;  cash −= budget
```

- **Divide by the number of slots**, not the number of names found; an unfilled slot stays in cash.
  Dividing by the names actually held is a separate, declared choice.
- **Cash earns 0% unless stated.** A strategy that sits in cash for long stretches (a timing rule) must
  also be run with a point-in-time overnight or liquid-fund rate, recorded in `audit.json`.
- **Shares are fractional**, so starting capital cannot change a return.
- **Weights are reset to their targets at every rebalance.** Letting them drift is a different
  strategy, and on wide portfolios it leaves names unfunded.
- **Trims come before top-ups.** Done in one pass, a top-up that comes before the trim that would fund
  it stays short and leaves cash idle — 13.3% of a three-name book in the simplest case.
- **Cost is charged at the trade, on the change in each position**: sells and trims keep (1 − ow) of
  their proceeds, buys and top-ups receive (1 − ow) of the cash committed, and an unchanged position
  pays nothing. `cost_bps` is a round trip, charged half per side. Asymmetric or fixed fees need
  separate buy and sell rates.

### R1.4 The index

```
NAV_t = cash_t + Σ_i units_i × p_i,t
    p = OHLC4 after the trades and costs, or the fallback     on a rebalance session
      = the forward-filled close                              on every other session
```

The base is 1.0 (or 100) before the first rebalance. A rebalance session is stamped once, after
trading. A missing close is carried forward; a position is never dropped from the NAV.

### R1.5 Returns and statistics

- **Measure from T, the session before the first rebalance**, to the liquidation session, so the
  first purchase's cost and its first session's move are inside the return. Measuring from the entry
  day's close while buying at another price silently dropped that move: −2.7pp on one path, +0.9pp
  on another.
- `years = sessions / 252`; `CAGR = (NAV_end / NAV_start)^(1/years) − 1`; volatility = standard
  deviation of daily returns × √252; `Sharpe = (CAGR − r_f) / volatility`, with r_f stated;
  `Calmar = CAGR / |maximum drawdown|`.
- **At the last rebalance, sell everything** at OHLC4 and pay the exit cost.
- **Benchmarks** run close to close, at no cost, over the same span as the portfolio, on the same
  basis (price or total return) as the strategy's returns.
- A non-finite or non-positive NAV raises an error; it never ends the run quietly.

### R1.6 The closed-form check

For a stock-picking strategy with no buffer, zero cost, weights reset, every slot filled and every
top-up funded:

```
total_return = Π over periods of  mean over names ( px_exit / px_entry )  − 1
```

For a timing rule at zero cost, it is the product of `px_exit / px_entry` over the in-spells. The
verifier re-derives dates, eligibility, ranking and skips from the raw inputs, imports nothing from
the engine, and compares each start date's total return within a stated tolerance.

### R1.7 Skipped rebalances

Skip a rebalance when too few names live that day have a fillable bar, measured on the whole universe
before any filter. Nothing trades; the book is carried and the skip is logged.

### R1.8 Traps

| Trap | What it did |
|---|---|
| Sell on a signal at the average price of the day that produced it | Look-ahead: +5.7pp |
| Rank on the entry day's own close and fill at its open | Look-ahead: +16.8% → +73.0% |
| Leave the execution calendar unwritten | An unchosen weekend geometry: +4.2pp, and a fake "best" hold |
| Sell leavers on the signal session at its close | Clean, but 2.6pp worse than trading on e |
| Size positions from the book while it is being traded | The mid-trade count is the retained names: 3 of 8 sizes everything at 1/3 |
| Count names sold at a rebalance as part of the new book | A 15-name book was recorded as 27 |

---

## R2. Using wm-quantBacktester

`wm-quantBacktester` is the team's shared engine, a sibling repository next to `wm-research`
(`../wm-quantBacktester`: index code in `quant_backtester/engine/index_calculator.py`, weights in
`quant_backtester/strategy/weights.py`, dates in `quant_backtester/data/utils.py`; see its README.md
and USAGE.md). **You do not need it.** If you use it, it agrees with R1 on the core —
`getSimpleNextDayRebalIndex` values the old book at OHLC4, sets `shares = weight × money / OHLC4` and
builds the index from shares × price — but differs in ten places:

| | `wm-quantBacktester` | R1 |
|---|---|---|
| The +1 | Not applied: it trades on the date its weight row is keyed to. `UtilsQB.getNextDate` exists but nothing calls it — re-key the weights to T+1 yourself | built in |
| First build | at the close, no cost | at OHLC4, buy-side cost charged |
| Cash | no cash account: an unfilled weight, or a name given 0 shares, loses its money | kept as cash |
| Unfilled slots | `getEqualWeightsSr` renormalises over the names selected | not renormalised |
| Cost | off by default; when on, 10.39 bps per rupee on `\|Δshares\| × close` of trial units sized at the close, deducted as one lump; no stamp duty | a flat rate per side on the value traded at the fill price |
| Rebalance stamp | new shares × close | cash + units × OHLC4 |
| Missing prices | a NaN OHLC4 on a rebalance loses the holding's value for good | the last close is carried |
| End of run | no liquidation, no exit cost | liquidated, exit cost charged |
| Expense ratio | optional | none |
| Statistics | 250 days a year; rolling 250-day Sharpe | 252 days; Sharpe = (CAGR − r_f) / volatility |

Do not model on `run_backtest` (`quant_backtester/engine/__init__.py`, also wrapped by
`quant_backtester/api/backtest.py`): it calls `getSimpleIndex`, which trades at the same session's
close and ignores its cost flag.

---

## R3. Words used here

| Word | Meaning |
|---|---|
| **test** | One experiment with one pre-registered question, numbered `T<NN>`, with its own folder |
| **arm** | One variant of the treatment inside a test, run the same way as the others |
| **setting** (config) | One combination of parameters |
| **start date** (phase) | For a process that repeats every H periods, one of the H places it could have started. Each is a separate realisation a live portfolio could have followed — but they overlap in time, so they are **not** independent observations |
| **realisation** | One path the strategy could actually have taken: setting × start date × arm |
| **slot, band, leaver** | A portfolio of N slots holds up to N names; a held name is kept while it ranks inside the band (R8); a leaver is a held name dropped at a rebalance |
| **spell, round trip** | For a timing rule: a maximal run of "in" or of "out"; one entry plus its exit |
| **OHLC4** | (open + high + low + close) ÷ 4 of one session's bar — the fill price (R1) |
| **null**, **draw** | The experiment with one ingredient randomised (N1); one run of it |
| **null result** | A test that found no effect — not the same thing as *the null* |
| **edge** | The result's median minus the null's median |
| **percentile**, **p-value** | Where the result falls among the null draws, on a named statistic; the probability a draw does at least as well (N6.1) |
| **pass mark** | The p-value or percentile a primary criterion must clear (N6.1) |
| **calibration ratio** | The null's spread divided by the standard error of the strategy's active statistic (strategy minus the pool's equal-weight portfolio). Below 1, the null is calmer than reality (N6.6) |
| **MDE** | Minimum detectable effect: the smallest true effect the test, as pre-registered, would detect 80% of the time (task 9 gives the formulas) |
| **HAC** | A Newey–West standard error that allows for overlapping or serially correlated observations; its lag is at least the overlap (h − 1) |
| **before / after cost** | Also written *gross* and *net* |
| **gate** | A check that must pass before any result is read |
| **finding** | One claim, with an ID, a status and a falsification criterion (R4) |
| **evidence** | The stored output a number is read from |
| **decision log** | One row per decision, with the value that drove it (R6) |
| **data review** | The project-level record of every input — source, fetch date, fingerprint, checks, charts, verdict — done before the first test (task 0) |
| **component map** | The data review's table of each role the strategy needs (fill price, cash, benchmark, signal…) → the exact series used, and why |
| **derived series** | A series the project builds from others — a splice, a rebuild, an adjusted line. Reviewed like a raw input |
| **walkthrough, worked example** | The plain-words account of how a test works (§3), and its real numbers for one decision, one path, one null draw and one ranking (§4.0) |

---

## R4. Findings

Every finding ID carries the project's prefix `<P>`, a short code chosen in task 3 (for example `EV`
for an event-study project):

| Form | About |
|---|---|
| `F-<P>-S##` | the strategy or signal: what it does and earns |
| `F-<P>-M##` | method: how we measure, and measurement bugs |
| `F-<P>-D##` | data and pipeline defects |

- Unprefixed `F-S`, `F-M` and `F-D` IDs are already used by other projects in `wm-research`; never use
  them bare. Before choosing `<P>`, search the repository for `F-<P>-` to confirm nobody uses it.
- **Each project keeps one counter line** in its CLAUDE.md ("Current highest IDs in use: …") and takes
  the next number from it, never from the highest ID in sight — tests run concurrently. IDs are never
  reused or renumbered.

| Status | Meaning |
|---|---|
| **CONFIRMED** | Survived adversarial checks. Overturning it needs new data, not re-analysis |
| **PROVISIONAL** | Real in-sample, but resting on one window. Not evidence yet |
| **REFUTED** | Tested and killed. Recorded so it stays killed |
| **FIXED** | A defect found and corrected. Kept for the lesson |
| **OPEN** | A known unknown. Named, not yet tested |

````markdown
### F-<P>-S<NN> — <the claim as a full sentence, carrying its headline number>

**Status:** PROVISIONAL — <why it is not CONFIRMED>. <Revises F-<P>-Sxx, if it does>
**Evidence:** `evidence/<run>/<file>`
**Claim:** the numbers, each with its denominator
**Falsified by:** a concrete, checkable result — or "n/a — arithmetic" for a defect
**Cross-check:**
```bash
python tests/T<NN>/analyse.py     # the block that prints it
```
````

The heading is a claim, not a topic. **Falsified by** is non-negotiable: a claim nothing could
disprove is an opinion. Write it before the data exists.

---

## R5. The write-up

Copy [TEST_TEMPLATE.md](TEST_TEMPLATE.md) to `tests/T<NN>/T<NN>.md`. Fill every section; if one does
not apply, write why — a blank section reads as "not considered".

**Header block:** status (DRAFT, RUNNING, COMPLETE, SUPERSEDED), run date, kind of experiment and unit,
script and check, evidence folders and their roles, the data review used (its date), model-generated
inputs, the decision log and the one setting it covers, window / universe / hold-out, cost / null /
seeds, what it extends or supersedes.

| § | Section | Holds | Written |
|---|---|---|---|
| 1 | Idea and references | task 1 | before the run |
| 2 | Hypothesis and pre-registered criteria | task 5, with the null table (N9) | before the run |
| 3 | Methodology | data (each input with its data-review verdict), construction, the plain-words walkthrough with the null in plain words (task 5 item 13, N9), point-in-time rule, execution and cost, effective sample and MDE, known contaminants | before the run |
| 4 | Results | the worked example, then gates, the null check and the controls; then the headline, multiplicity and the verdict table (task 9) | after |
| 5 | Findings | one entry per claim (R4) | after |
| 6 | What this does not establish | tested and inconclusive; not tested at all | after |
| 7 | Next things to work on | question, method, cost, what it would change | after |
| 8 | Reproduction | every command, in order, and what makes the run deterministic | after |

**After the run, §1–§3 are frozen.** Anything learned later goes in a block labelled "added after the
run, <date>", and the status line says so. A statistic introduced later sits beside the
pre-registered one, never instead of it.

---

## R6. Evidence and scripts

- **`audit.json`, per run:** what the run was for; the data review used (its date) and, for every
  input, its path, size and sha256 checked against that review's inventory — a mismatch stops the run
  (task 4); the rules in prose;
  the parameters; cost levels, cash rate and seeds; whether prices are adjusted and returns include
  dividends; any model's id, version and training cutoff; the point-in-time rule with its count of
  checks and violations; caveats.
- **The decision log:** one row per decision — per period per name held, per spell, per event, or per
  candidate — with the date, the item, the value that drove the decision, its rank and its outcome.
  Ship two: one named setting, and the whole test. It is the one artifact a reader can check by eye.
- **`run_grid.sh`** regenerates every run; **`analyse.py`** reads only stored evidence and prints every
  table the write-up uses, into `analysis.log`.
- **Model outputs:** generated once and shipped as a file, with the model id and version, training
  cutoff, prompt file and hash, temperature and date. Relabel a random sample and report the agreement
  rate. As a validity gate, check that every output field varies — in one study a model's "conviction"
  field had one value on 98% of rows. Every prompt version tried on the test window counts as a setting.
- **A new dimension gets a new column name**; never reuse one that already means something.
- After any code change, regenerate the stored artifacts, even if no number can move.

---

## R7. Writing numbers and keeping history

- Returns in %, differences in pp; every count with its denominator ("24 of 24 settings").
- **Every number with its window**: the first and last date it covers, as dates, not as labels —
  "CAGR 18.4% (2014-07-04 → 2021-10-29)", never "CAGR 18.4% (2014–21)" alone. A label such as "the
  live window" is defined once with its dates and may then be used, but the dates stay on every table
  and chart. Every equity curve says its start date and base: "growth of 1 invested at the close of
  2021-11-03".
- **Every computed number with its formula**, where it is first shown, with its conventions: the year
  basis (252 sessions or days ÷ 365.25), daily or weekly marks, before or after cost.
- Every percentile with its statistic, its number of draws and its calibration ratio; before and
  after cost together wherever a trade is modelled; the setting named whenever a number covers one.
- Verdicts as table rows: **PASS**, **FAIL**, **FAIL, as pre-registered**, **NOT REPORTABLE**.
  Hypotheses: **NOT FALSIFIED**, **FALSIFIED**, **NOT REPRODUCED**. A failure reads "undetectable
  below X".
- Say the largest open caveat before quoting any level.
- **Superseding:** a banner at the top of the old write-up — what changed, old and new numbers, what
  still stands; its status becomes "SUPERSEDED (was COMPLETE)". The old numbers are never edited:
  the history of a number is evidence about how far to trust the current one.

---

## R8. Rules in force across wm-research

- **The 30% buffer rule** (adopted 2026-09-24), for any rank-and-hold portfolio: three band levels,
  **1.0 / 1.3 / 1.6 × the number of slots, rounded up** — for 15 slots, keep a held name while it
  ranks inside the top 15, 20 or 24 — computed as `ceil(round(N × multiple, 9))`, because in floating
  point `10 × 1.3` is slightly more than 13. It is a convention, not a measured optimum. How it enters
  a test:
  - the three bands are three settings of one test — for 20 slots, b20 / b26 / b32;
  - the 1.0× band is the no-buffer book, the one the closed-form check covers (R1.6);
  - the 1.3× band is the reference setting (task 5, by position);
  - three bands are a sweep: judge the best against the best-of-sweep null (N6.8);
  - labels read `n<slots>_h<rebalance interval>_b<band>`: `n15_h4w_b20` is 15 slots, rebalanced every
    4 weeks, a held name kept while inside the top 20.
- **Every HTML report ships with a companion methods file** in its evidence folder, linked from the
  report, stating for each section and chart what is plotted, the denominator and window, the formula,
  the null and its statistic, the generating script and columns, and that number's own limitations.
  The page itself follows R10.

---

## R9. Checklists

**Before a project's first test, and after any change to its data (task 0)**
- [ ] Every input inventoried: role, source system, the query or script that fetched it, who, when,
      the last date covered, sha256, units, adjustment basis
- [ ] Calendar checked against the named exchange calendar: missing, extra and duplicate dates, special
      sessions, coverage per name
- [ ] Values checked: blanks, zero or negative values, OHLC consistency, stale runs, unit breaks,
      splice jumps; every move beyond the threshold listed and explained
- [ ] At least three spot checks per series against an independent public source, recorded
- [ ] Overlapping sources reconciled on returns; the source for each role chosen, with the reason
- [ ] Every derived series documented — inputs, construction, formula, script, reconciliation, chart
- [ ] Charts drawn by `data_review.py`: level, returns, histogram, largest moves, missing-data map
- [ ] The component map written, with the project-wide gap and extension conventions
- [ ] A verdict per input; every defect a `F-<P>-D##` finding; the review dated and not edited after
      a test cites it

**Before the first run**
- [ ] The approved plan copied verbatim to `tests/T<NN>/PLAN.md` (task 3)
- [ ] Every input this test reads has a PASS or PASS WITH NOTES in the data review; the notes copied
      into §3's contaminants; the review's date in the header (task 4)
- [ ] The plain-words walkthrough written in §3 — the series, one decision, one path, one null draw,
      the ranking, the comparators — with the places for its real numbers marked (task 5 item 13, N9)
- [ ] The question in one sentence, with what would make it false (task 1)
- [ ] The kind of experiment and its unit named (task 2)
- [ ] Every input dated, prices adjusted, fundamentals lagged; point-in-time checks in code; universe
      as of each date (task 4)
- [ ] Each event's window starts at the first fillable price; reaction or tradable return named
- [ ] Any model's id, version and cutoff recorded; clean and contaminated decisions separated
- [ ] A hold-out stretch kept unseen, or the reason there is none written down
- [ ] The null specified with its table: randomised / held (constant or per date) / not matched (N9)
- [ ] The deciding null named, if there is more than one
- [ ] The statistic named, with its direction and why (N6.3); secondary statistics listed
- [ ] The pass mark and the number of draws fixed, enough for the multiplicity adjustment (N6.1, N6.2)
- [ ] Validity and reportability gates written; criteria complete and satisfiable
- [ ] §3 written — data, construction, execution and cost, effective sample and MDE, contaminants —
      and frozen with §1–§2 (R5)
- [ ] Robustness checks and multiplicity planned; the reference setting fixed by position; prior
      knowledge disclosed; one thing changed at a time
- [ ] For a rank-and-hold portfolio, the three band levels in the grid (R8)
- [ ] The independent check passes on its own setting and fails on a corrupted copy; the controls and
      the regression gate built (task 7, N6.7)

**Before marking COMPLETE**
- [ ] The worked example printed by `analyse.py` and checked by hand: one decision, one path, one
      null draw, one ranking (task 9, step 0)
- [ ] Every gate passed, printed by a script; point-in-time counts read from `audit.json`
- [ ] The null check shown first: held dimensions identical, mismatches measured (N5)
- [ ] The controls: oracle at the top, negative-control false-positive rate near nominal, MDE plant
      detected about 80% of the time (N6.7)
- [ ] Every percentile with its statistic, draws, p-value and calibration ratio (N6)
- [ ] Before and after cost wherever a trade is modelled; distinct realisations beside setting counts
- [ ] The MDE beside every failed criterion
- [ ] Multiplicity reported: settings, variants, prompts and ideas tried; the best setting against the
      best-of-sweep null; adjusted p-values (N6.8)
- [ ] Everything dropped counted, with reasons (task 4)
- [ ] Every claim a finding with its falsification criterion; refuted ideas logged too
- [ ] "Does not establish" split into inconclusive and untested; next steps listed
- [ ] Anything written after the run is in a dated block, and the status line says so (R5)
- [ ] The README register, findings table and file list updated; banners on anything superseded;
      every HTML report has its methods file (R8)

**Before quoting any number**
- [ ] It comes from a test's evidence folder, not from scratch output
- [ ] Its setting, null, statistic, percentile, draws, calibration ratio and denominator go with it —
      and before and after cost where it trades; for a FAIL, the MDE
- [ ] Its finding ID and status go with it
- [ ] Its window — first and last date — and, where it is computed, its formula go with it
- [ ] The largest open caveat is said out loud

**Before publishing a results page (R10)**
- [ ] "One backtest, end to end" present, every step with its formula and real numbers
- [ ] Every number, table and chart carries its start and end date; every curve its base and start
- [ ] Every statistic's formula on the page, with its conventions
- [ ] Every chart has a hover: crosshair, a timestamp chip on a time x-axis, a level chip on the y-axis,
      and a tooltip with every data point drawn at that x (tried with the pointer, in light and dark)
- [ ] `check_page.py` passed: every number and every date on the page recomputed, 0 failures

---

## R10. The results page

Every test ends with an HTML page (task 11), generated by `tests/T<NN>/report.py` from the evidence
only — no typed numbers — with its methods file beside it (R8). The write-up is the record; the page is
what most readers will see, so it must stand on its own: a reader who opens only the page can say what
was tested, on which data, over which dates, how every number was computed, and what the verdict is.

**The page, in order:**

1. **The answer.** The question, the verdict per hypothesis, the test ID and status, the run date, the
   data review used.
2. **The data.** One row per input: what it is, its source, its fetch date, the field used, what it is
   adjusted for, its first and last date (from the data review's component map).
3. **One backtest, end to end.** One realisation — the reference setting, one book or start date, one
   window — followed from raw data to its final number, each step with its formula and its real
   numbers, so a reader could redo it with a calculator:

   | Step | Shows | Example of what is written |
   |---|---|---|
   | Inputs | each series used, its first and last date, the field | "Index close, 2021-11-01 → 2026-08-21, 1,186 sessions; gold ETF close; cash: the dividend-reinvested liquid-fund level" |
   | Signal | its formula, then its value on one real decision date with the inputs shown | "p = share of the 65 previous closes below today's close × 100 = 0 ÷ 65 × 100 = 0 on 2022-02-18" |
   | Decision | the rule and the target it sets | "p < 25 → equity 0%, gold 50%, cash 50%" |
   | Execution | the trade date, the price used (close, OHLC4) and why, the cost formula and the cost paid | "traded 2022-02-21 at that session's close; cost = value traded × 10.4 bps per side = ₹ …" |
   | Holdings | units bought and sold, with the formula | "units = money × (1 − ow) ÷ price" |
   | Daily value | the NAV formula and its value on a few dates around the trade | "NAV_t = cash_t + Σ units_i × close_i,t" |
   | Equity curve | its start date, base value, end date, end value | "1.000 at the close of 2021-11-01 → 1.538 on 2026-08-21, 1,186 sessions" |
   | Statistics | each formula with the numbers substituted | "CAGR = 1.538^(252 ÷ 1,185) − 1 = 9.6%"; "max drawdown = min over t of (NAV_t ÷ max of NAV up to t − 1) = −35.5%, peak 2022-01-17, trough 2023-03-09" |
   | Null | how one draw is made, that draw's numbers, its statistic | "draw k = 8: the same 252 weekly targets started 8 weeks later … CAGR 9.1%" |
   | Ranking | the counts behind the percentile | "67 of 237 draws below, 0 equal, 170 above → 28.3rd percentile; p = (1 + 170) ÷ (237 + 1) = 0.72" |
   | Comparators | each benchmark's formula, start date and value | "hold: P_end ÷ P_start, close to close, no cost, 2021-11-01 → 2026-08-21: 15.3% a year" |

   The examples are one real path: a weekly timing rule on one index, 2021-11-01 → 2026-08-21.

4. **The headline and the verdict table**, each number with its window and statistic.
5. **The detail**: per-setting and per-period tables, robustness, multiplicity, what was dropped.
6. **Definitions**: every statistic's formula and conventions, on the page — not only in the methods
   file — next to the first table or chart that uses it.

**Dates on everything.**
- Every number carries the first and last date it covers. Where a whole table shares one window, the
  dates go in its title; where columns differ, in each column's header.
- Every chart states its window in its title and starts its x-axis on that date. An equity curve
  states its start date and its base: "Growth of 1 invested at the close of 2021-11-03, log scale".
  Two curves on one chart share one start date and one base, or the chart says why not.
- A period label ("2014–21", "the live window") is defined once with its exact dates in the data
  section, and every table that uses it repeats the dates.
- Dates are written YYYY-MM-DD.

**Every chart is hoverable, and the hover shows every data point.** A chart is not finished until
hovering (or touching) it shows what is under the pointer — the reader should never have to read a value
off the axis by eye or look it up in a table.
- **A crosshair at the pointer, with both axes read out.** A vertical line at the pointer's x, and where
  the y-axis is continuous a horizontal guide too, with a chip on each axis: the x-axis chip carries the
  full timestamp where the x-axis is time (YYYY-MM-DD, plus the weekday for daily data and the clock time
  for intraday data), and the y-axis chip carries the level at the pointer. A dot sits on every line at
  that x.
- **A tooltip listing every data point drawn at that x**, none left out: each line's, bar's or cell's
  value in the units and rounding of the tables, with its series swatch; every strip, band or state the
  chart draws (in the market or out, which regime, which book); and the period or stretch the point falls
  in, with its dates. A histogram's tooltip gives the bin's edges, count and share of draws, and the
  marked values (the rule, the median) with their percentiles. A chart with series hidden by a legend
  filter lists only what is shown.
- **It works on touch and near the edges** (the tooltip flips to stay inside the card), in light and in
  dark mode.
- **The hover reads the same arrays that draw the chart** (embedded in the page as JSON by `report.py`),
  never retyped numbers, so the tooltip cannot disagree with the picture. `check_page.py` recomputes the
  hover arrays from the evidence like every other number on the page.

**Formulas on everything.** Each statistic is written once on the page in full, with every variable
named and its conventions stated — the year basis (252 sessions, or days ÷ 365.25), daily or weekly
marks, before or after cost, arithmetic or log — and every other use points to it. A number whose
formula a reader cannot find on the page is not finished.

**Checking the page.** `tests/T<NN>/check_page.py <page.html>` shares no code with the engine, the
verifier, `analyse.py` or `report.py`. It re-runs the end-to-end example from the raw files,
recomputes every number in the page's data, and checks every number and every date in its prose and
captions against the evidence. It prints its count of checks and failures, and exits non-zero on any
failure or when it checked nothing. A page is published only after it passes; the count goes in the
methods file. In one test this check caught a page calling 192,584 point-in-time checks "decisions"
(there were 78,088 decisions).

---

## Revision history

| Date | Change |
|---|---|
| 2026-10-22 | Added task 0 (the project's data review), with `DATA_REVIEW_TEMPLATE.md`, the `data/` folder and its checklist. Added rules 9 and 10. Added the plain-words walkthrough (task 5 item 13), the worked example (task 9 step 0) and the null in plain words (N9). Task 4, R3, R5, R6 and R9 link to them. Nothing earlier was removed. A test written before this date is not out of date; its next revision adds a walkthrough in a dated block |
| 2026-10-22 | Added R10, the results page: one backtest end to end with formulas and real numbers, a start and end date on every number and curve, formulas on the page, and `check_page.py` before publishing. Rule 3, task 11, R7, R8 and R9 updated to match |
| 2026-11-06 | R10: every chart is hoverable. A crosshair with a timestamp chip on a time x-axis and a level chip on the y-axis, and a tooltip with every data point drawn at that x, read from the arrays that draw the chart. Added to the R10 publishing checklist. First applied to T03's regime chart; T03's four per-book growth-of-1 charts got the hover the same day (`svg_lines`, `LINES_JS`, checked by `check_page.py`); T03's null-distribution histograms still predate the rule |
| 2026-11-06 | Task 3 and the R9 "before the first run" checklist: every test keeps its approved plan, copied verbatim, as `tests/T<NN>/PLAN.md`. T03, T04 and T05 were back-filled the same day |
| 2026-11-06 | Data boundary: the project keeps `data/APPROVED_DATA.md`, the only list of inputs an agent may read (path, through-date, fingerprint, latest usable date per role), with `data/check_approved_data.py` to verify it against the files. Rule 9 and task 4 updated: stale, missing or unclear data means stop and ask the owner; refreshing is the owner's decision, the new file stays off-limits until the owner approves it, and the approval check covers only the new rows. Replaces the earlier instruction to extend stale files before use |
| 2026-11-06 | N4.10, random timing with free spell lengths, added after N4.9 (recipe, exact sampler, when to use it, first use in T06), with a row in "Choosing among them". N4.9 now says that for a weekly rule traded daily, invested weeks are held exactly and sessions only approximately (F-AA-M06) |
| 2026-11-12 | N4.11, random timing of a second signal (one null per timing), added after N4.10 (recipe, bounds set before any return, what it holds and breaks, first use in T08), with a row in "Choosing among them" |
