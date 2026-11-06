# Methods appendix — "Gold, Not Timing" (Study 1)

Companion to the report at `evidence/main/report.html`
(artifact: https://claude.ai/code/artifact/a93640d3-18ba-45ca-b8e9-88a693c2dd9b).

For every section and every chart this file states: **what is plotted**, the
**window and denominator**, the **formula**, the **statistical test** if there is
one, the **files** that produce and hold the number, and the **limitations of
that specific number**.

Read the two warnings at the top of §0 before quoting anything from the report.

---

## 0. Conventions that apply everywhere

| Convention | Value | Where |
|---|---|---|
| Study window | **2021-11-01 → 2026-08-21**, 1,186 sessions, 4.80 calendar years | `AA/Historical Data/indices.csv` |
| Panel used by every phase | `evidence/main/panel_daily.csv` (1,186 rows) | built by `build_panel.py` |
| CAGR | annualised on **calendar** time: `(Π(1+r))^(365.25/days) − 1`. Not 252/n. | `common.py:cagr_from_returns` |
| Ann. vol | `std(r, ddof=1) × √252` | `common.py:ann_vol` |
| Sharpe | `cagr / ann_vol`, **rf = 0** | `attribute.py:describe` |
| Excess / value-add | always accumulated in **log space** then converted back with `expm1`, so pieces add exactly | `attribute.py`, `robustness.py` |
| Returns | gross of cost. Study 1 has no cost model — every number in the report is gross. | — |
| Reference sleeve for counterfactuals | fixed **50 % GOLDBEES + 50 % cash**, daily rebalanced, spanning the whole window | `robustness.py:reference_sleeves` |
| Realized sleeve | the actual per-date instrument weights, which changed composition twice (3-leg gold/liquid/bond → 2-leg) | `common.py:load_state` |
| Cash | **not** LIQUIDBEES price return, which is exactly 0.00 % because it distributes its yield. Uses the supplied adjusted series. | `prices.py:cash_total_return`, `LBES_Adjusted_Price_data_2026_08_10.csv` |
| Seed / draws | `SEED = 1729`; 10,000 draws for the timing null, 1,200 for the gold null, 2,000 for phase 12 | `robustness.py`, `phase8_signals.py`, `phase12_ownindex.py` |

### ⚠ Two things to know before quoting the report

1. **`wdef` is not always 0 or 1.** 0042 and 0043 are binary — 534 and 539
   fully-defensive sessions, no partial. **0044 had 27 sessions and 0045 had 58
   sessions at a 50 % defensive weight** (half in equity, half in the sleeve).
   Every "sessions out" count in §4 counts `w > 0`, but every *return* weights
   by `w`. This is exactly why the §4 → §5 reconciliation below is exact for
   0042/0043 and not for 0044/0045.
2. **Prose and tables were generated from different runs in two places.** The
   §5d prose says "0043 at the 85th percentile (z = 1.03)"; the table and
   `null_random_timing.csv` say **84.3rd percentile, z = 1.013**. The §5e prose
   says "84th and 87th percentile, z of 1.04 and 1.16"; the table and
   `gold_timing.csv` say **83.7th / 87.7th, z = 1.00 / 1.23**. **The tables are
   authoritative.** Nothing about the conclusion changes, but cite the tables.

---

## §3 — "The overlay helped exactly where the stock picking was bad"

### What is plotted

A table, not a chart: per parent, four blend weights, R², parent CAGR, blend
CAGR, and selection alpha.

### Is the distribution based on recent holdings? **No.**

This is the question most likely to be misread, and the report's own §8b says it
in one line without elaborating, so in full:

There is **no holdings-based classification anywhere in these numbers.** The
weights come from a **regression on daily returns over the whole window**. It is
a non-negative, sum-to-one least-squares fit:

```
minimise  Σ_t ( Σ_k w_k · r_k,t  −  r_parent,t )²
subject to  w_k ≥ 0  and  Σ_k w_k = 1
```

- `k` ∈ {Nifty 100, Nifty Midcap 150, Nifty Smallcap 250, **Nifty Microcap 250**}
- `t` = every session where the parent and all four indices have a return:
  **1,138 sessions, 2022-01-11 → 2026-08-21, 4.608 calendar years**

### ⚠ §3 runs on a SHORTER window than the rest of the report

The headline window is 1,186 sessions / 4.799 years from 2021-11-01. §3 gets
**1,138 sessions / 4.608 years from 2022-01-11**, because the fit needs all four
index returns present and **Nifty Microcap 250's history starts only
2022-01-10** (the other three begin 2005 or 2019). The first **47 sessions**
(2021-11-02 → 2022-01-10) drop out of the intersection.

Adding the fourth factor was necessary — omitting it overstated selection alpha
by 2–5 pp — but truncating the window is its side effect, and it was previously
undocumented.

**Two different 6.7 %s exist in this report:**

| Where | Sessions | Window | Years | CAGR |
|---|---|---|---|---|
| §1 scorecard | 1,185 | 2021-11-02 → 2026-08-21 | 4.799 | **6.667 %** |
| §3 table | 1,138 | 2022-01-11 → 2026-08-21 | 4.608 | **6.685 %** |

They round alike by **coincidence**: 0007 returned only +1.17 % over the 47
excluded sessions. For a book where that stretch mattered more they would
visibly diverge. Never carry a §3 CAGR into a §1, §2 or §4 calculation.

**What is not threatened:** `selection_alpha_ann = parent_cagr − blend_cagr` has
both legs on the same 1,138 sessions, so it is internally consistent for every
book.

**Two knock-ons.** The excluded stretch sits almost entirely inside **episode 1**
for all four books (2021-11-01/02 → 2022-01-14), a *losing* risk-off episode — so
§3's window omits part of the overlay's worst start. And it compounds the
instability of the thirds-refit ranges above: 4.6 years split three ways is
~1.5 years per sub-fit.
- solver: `scipy.optimize.minimize(method="SLSQP")`, `ftol = 1e-14`, `maxiter = 500`
- index levels come from **one** source — the desk's `Data/indices_ohlcv.xlsx` —
  so the fit and the scorecard cannot disagree about what an index did

`blend_cagr` is the CAGR of the fitted series `Σ w_k r_k,t`.
`selection_alpha_ann = parent_cagr − blend_cagr`.

### Source files

| Thing | Path |
|---|---|
| Code | `AA/analysis/attribute.py:implied_mcap_blend` (lines 222–289) |
| Output | `evidence/main/mcap_exposure.csv` |
| Fitted series | `evidence/main/mcap_blend_returns.csv` |
| Index levels | `…/Friday Rebalance Automation/Data/indices_ohlcv.xlsx` via `supertrend.py:load_index_ohlcv` |
| Why 4 factors not 3 | `phase11_classification.py` → `evidence/main/regression_spec_comparison.csv` |

### Why a returns fit rather than counting holdings

Because for most of this window a point-in-time holdings classification did not
exist. Under the 2026-membership approach, **12–33 % of 2021-2023 holdings were
unmappable**, and the ones that were unmappable are precisely the names that
changed size — the bias sits on the mechanism being measured. Step 0 of Study 2
later fixed this (see §8b below); Study 1 was written before that.

### ⚠ Limitation this number carries — and it is larger than the report implies

`implied_mcap_blend` also refits on **thirds of the sample** and records the
range of each weight. Those ranges are large:

| Parent | Nifty 100 range | Midcap 150 range | Smallcap 250 range | Microcap 250 range |
|---|---|---|---|---|
| 0003 | 0.065 | 0.263 | 0.241 | **0.384** |
| 0007 | 0.036 | 0.341 | **0.426** | 0.250 |
| 0010 | 0.215 | 0.189 | **0.449** | **0.580** |
| 0029 | 0.221 | 0.301 | **0.746** | 0.284 |

**0029's smallcap weight moves by 75 percentage points across thirds of the
sample.** So the single full-window blend is a reasonable *average* description
of each book's factor exposure, but it is **not a stable estimate**, and
selection alpha inherits that instability. Treat the blend column as
"roughly what this book behaves like", not as a measured allocation. R² of
0.71–0.76 says a quarter of the daily variance is unexplained by any static mix
of the four indices.

Second limitation: the four factors are highly correlated with each other, so
the *split* between adjacent buckets (Small vs Micro especially) is weakly
identified even where the total equity beta is well identified.

---

## §4 — "While out of equity, equity mostly went up"

### What is plotted — the bar chart

Three bars per portfolio. **All three are cumulative (total, not annualised)
returns, compounded over the risk-off sessions only.**

| Bar | Exactly what it is |
|---|---|
| Parent while out | the parent basket's compounded return over the sessions the AA was defensive |
| Sleeve earned | the **realized** sleeve's compounded return over those same sessions |
| Gold alone | GOLDBEES compounded over those same sessions |

For a series `x`, over the set of sessions `T_off = { t : w_t > 0 }`:

```
return = expm1( Σ_{t ∈ T_off} log(1 + r_x,t) )
```

Note what this is **not**: it is not the return over the calendar span from the
first to the last risk-off day. Sessions are **spliced** — six or seven separate
episodes concatenated. The 2.12 years in the table is `off_sessions / 252`, an
*equivalent* duration, not an elapsed one.

Denominators: 534 / 539 / 482 / 491 sessions for 0042 / 0043 / 0044 / 0045.

### Source files

| Thing | Path |
|---|---|
| Code | `phase9_improve.py` (off-window economics), consumed at `report.py:770–800` |
| Output | `evidence/main/offwindow_economics.csv` |
| Episode-by-episode version | `evidence/main/episode_ledger.csv` (each episode's start, end, sessions, parent/AA/sleeve return) |

### Limitation

"In three of four cases the parent rose" is a statement about *this* window's
sequence of episodes. With 6–7 episodes per book, that is a 4-observation
finding about 26 episodes total. It is descriptively exact and inferentially
weak, which is what §5d then tests.

---

## §4b — "Gold did 84 % of the work"

### What is plotted

Each defensive leg's **contribution to the sleeve's return**, cumulative over
the risk-off sessions. "Sleeve" here means the **realized** defensive basket —
the actual instruments held, at their actual weights, which changed twice over
the history:

- **gold** = GOLDCASE or GOLDBEES, whichever was held
- **cash / "liquid"** = LIQUIDBEES or LIQUIDCASE, priced with `cash_total_return`
  because the raw price return is exactly 0.00 %
- **bonds** = EBBETF0431, held only until Apr-2023

The contribution of leg `ℓ` is its **weight-multiplied** log return, summed over
risk-off sessions:

```
contrib_log_ℓ  =  Σ_{t ∈ T_off}  w_ℓ,t · log(1 + r_ℓ,t)
contrib_return_ℓ = expm1( contrib_log_ℓ )
```

### What `w_ℓ,t` is, and why the bars are smaller than the leg returns

`w_ℓ,t` is leg ℓ's weight **in the whole portfolio**, not its share of the
sleeve. So these bars are **contributions**, not returns: each leg's return
already scaled down by how much of the book was actually in it.

On 0042's 534 risk-off sessions there are exactly two weight regimes, because
the sleeve's composition changed once mid-history:

| Regime | Sessions | gold | cash | bond | total |
|---|---|---|---|---|---|
| 3-leg (from 2021-11-01) | 256 | 0.333 | 0.333 | 0.333 | 1.000 |
| 2-leg (from 2024-10-28) | 278 | 0.500 | 0.500 | 0.000 | 1.000 |

They sum to 1.0 because the book is *fully* defensive on those days — the legs
are splitting the whole portfolio between them, so no single leg can be 1.0.
(The 0.420 / 0.420 / 0.160 figures in `sleeve_legs.csv` are **averages across
the 534 sessions**, not any day's actual weight. An earlier draft of this file
said gold "sits near 0.42 on a fully-defensive day", which was wrong — on any
given day it is exactly 1/3 or exactly 1/2.)

The consequence, for 0042 over those same 534 sessions:

| Leg | Held **alone** at 100 % | Its **contribution** at actual weight | avg weight |
|---|---|---|---|
| gold | **+101.68 %** | **+38.34 %** | 0.420 |
| cash | +10.03 % | +4.19 % | 0.420 |
| bond | +11.18 % | +1.14 % | 0.160 |
| | | **sum of logs → +45.78 %** | |
| | | realized sleeve → **+46.33 %** | |

Gold roughly doubled, but the book only ever held a third to a half of it, so
gold *gave the portfolio* +38 %, not +102 %. That is the number in the bar.

Two loose ends this table exposes, both benign:

- **Sum +45.78 % vs realized sleeve +46.33 %.** The 0.55 pp gap is daily
  rebalancing: `log(1 + Σ w·r) ≠ Σ w·log(1 + r)`. The decomposition is a very
  close approximation here, not an exact identity — unlike the risk-on/risk-off
  attribution in §2, which is exact.
- **+101.68 % here vs the +99.7 % "Gold alone" bar in §4.** §4 uses **GOLDBEES
  only**, for one continuous series across the whole window. This uses whichever
  gold instrument was *actually held* — GOLDCASE early, GOLDBEES later — so it is
  the realized gold leg. Both are correct for their own purpose; the 2 pp gap is
  the instrument switch.

### Where "84 %" comes from

Gold's share of the **sum of the three log contributions**:

| Book | gold | cash | bonds | total | gold share |
|---|---|---|---|---|---|
| 0042 | 0.3245 | 0.0411 | 0.0113 | 0.3769 | 86.1 % |
| 0043 | 0.3404 | 0.0415 | 0.0113 | 0.3932 | 86.6 % |
| 0044 | 0.2016 | 0.0358 | 0.0139 | 0.2514 | 80.2 % |
| 0045 | 0.2001 | 0.0355 | 0.0111 | 0.2467 | 81.1 % |

Mean = **83.5 %**, reported as 84 %.

### Source files

`attribute.py:sleeve_leg_split` (lines 189–219) → `evidence/main/sleeve_legs.csv`.
Prices from `prices.py:defensive_prices` (cached at
`cache/defensive_etf_closes.csv`) and `prices.py:cash_total_return`.

### Limitation

Gold BeES compounded at 27.3 %/yr over this window — a single uninterrupted
bull market. Any statement of the form "gold did most of the work" is
**regime-bound by construction** and says nothing about whether gold will again.

---

## §5 vs §4 — why they look the same and give different numbers

This is the most common confusion in the report and it is a real reporting
failure on my part: the two charts share a session set but not a quantity.

|  | §4 chart | §5a chart |
|---|---|---|
| Quantity | **level** — what each asset returned | **excess** — what the overlaid portfolio beat the naked parent by |
| Session set | risk-off sessions only | whole window, but the excess is *zero by construction* on risk-on sessions, so it is effectively the same sessions |
| Sleeve | the **realized** sleeve (composition changed twice) | a **fixed reference** sleeve, one of all-cash / 50-50 / all-gold |
| Weighting | **unweighted** — no portfolio weight enters | **weighted by `w_t`**, which is 0.5 on some 0044/0045 sessions |

### What "weighted" and "unweighted" mean here

§4 asks *what did this asset do over these dates*. The portfolio's weight in the
asset never enters the arithmetic:

```
§4 bar  =  expm1( Σ_{t ∈ T_off} log(1 + r_asset,t) )
```

§5 asks *what did the portfolio gain by switching*. The portfolio's weight is
inside the formula, because the portfolio only earns the swap on the fraction of
itself that actually moved:

```
synth_t   = (1 − w_t)·r_parent,t  +  w_t·r_sleeve,t
§5a bar   = expm1( Σ_t [ log(1 + synth_t) − log(1 + r_parent,t) ] )
```

When `w_t = 1` the whole book is in the sleeve, `synth_t = r_sleeve,t`, and the
day's excess is the full `log(1+r_sleeve) − log(1+r_parent)`. When `w_t = 0.5`
half the book is still sitting in the parent, so the day contributes only about
half that excess. `w_t = 0` contributes exactly zero, which is why §5's sum over
the whole window collapses onto §4's off-session set.

**This is the entire source of the discrepancy — verified, not assumed.** Re-run
0044's value-add over the same sessions but with `w` forced to 1.0:

| 0044, sleeve | ratio identity | `w` forced to 1 | actual `w` |
|---|---|---|---|
| all cash | −14.80 % | **−14.80 %** | −18.42 % |
| 50/50 | +3.90 % | **+3.90 %** | −0.96 % |
| all gold | +23.64 % | **+23.64 %** | +17.37 % |

Forcing the switch to be complete reproduces the ratio identity to the decimal
in every arm. Nothing else differs. (0042 and 0043 have no fractional sessions at
all, so all three columns already agree for them.)

### ⚠ And this is not just bookkeeping — it cost those two books real money

The half-weight sessions were **not** scattered randomly. They were the single
best risk-off stretch either book had:

| Book | Half-weight sessions | Window | Parent over just those sessions | Cash | Gold |
|---|---|---|---|---|---|
| 0044 | 27 | 2022-04-11 → 2022-08-05 | **−8.10 %** | +0.36 % | +2.11 % |
| 0045 | 58 | 2021-11-01 → 2022-05-06 | **−21.69 %** | +0.67 % | +1.50 % |

Both books were only **half** out of equity during precisely the windows their
own signal called correctly. Cost of that half-sizing, holding everything else
fixed:

| Arm | 0045 full switch | 0045 actual | Cost |
|---|---|---|---|
| all cash | −12.45 % | −22.66 % | **−10.21 pp** |
| 50/50 | **+6.33 %** | **−6.27 %** | **−12.60 pp** |
| all gold | +26.01 % | +10.91 % | **−15.10 pp** |

On the 50/50 sleeve, **0045's overlay flips from +6.33 % to −6.27 % purely
because of the half-sizing.** Same signal, same dates, same sleeve — only the
position size differs. For 0044 the equivalent cost is −4.9 pp on the 50/50 arm.

So part of why these two books underperformed is not that the signal was wrong on
those dates; it is that the book was only half-committed when the signal was at
its most right. Whether that half weight was a deliberate ramp or an execution
artefact is not answerable from the weight files alone, and it is worth asking the
desk. Source: `panel_daily.csv:wdef_*`, derived in `common.py:load_state` from
`SCMO_004x_Weight.csv`.

The two are linked by a ratio, not a difference. For a full switch (`w ∈ {0,1}`):

```
§5a value-add  =  (1 + sleeve_return_while_out) / (1 + parent_return_while_out)  −  1
```

Verified against the evidence files:

| Book | (1+gold)/(1+parent)−1 | §5a "all gold" | (1+cash)/(1+parent)−1 | §5a "all cash" |
|---|---|---|---|---|
| 0042 | **+79.17 %** | **+79.17 %** | **−1.28 %** | **−1.28 %** |
| 0043 | **+114.27 %** | **+114.27 %** | **+14.78 %** | **+14.78 %** |
| 0044 | +23.64 % | +17.37 % | −14.80 % | −18.42 % |
| 0045 | +26.01 % | +10.91 % | −12.45 % | −22.66 % |

0042 and 0043 reconcile **exactly**. 0044 and 0045 do not, and the reason is
mechanical, not an error: those two books spent 27 and 58 sessions at a **50 %**
defensive weight, so half the position stayed in equity and the ratio identity
does not apply. The 50/50 column never reconciles for anyone, because §4's
"sleeve" is the realized basket (which included bonds and different gold
instruments) while §5's is the fixed GOLDBEES/cash reference.

**Short answer to "if they are the same why are the numbers different":** §4
tells you what each asset *did*; §5 tells you what the switch *gained relative
to not switching*, using a standardised sleeve so the three arms are comparable.
Neither is wrong; the report should have said this under both charts.

---

## §5c — the static-mix control

### What "average defensive portfolio" means

A portfolio that holds a **constant** defensive weight equal to the overlay's
own realized time-average, for every session in the window — no signal, no
switching, never rebalanced into or out of anything.

```
w̄        = mean over ALL 1,186 sessions of w_def,t      (not just off sessions)
static_t = w̄  for every t
r_static = (1 − w̄)·r_parent + w̄·r_sleeve      (daily rebalanced)
```

### How the weight number was arrived at

It is not chosen or fitted. It is `panel["wdef_<scid>"].fillna(0).mean()` —
one line, `robustness.py:214`. Because `wdef` is 1.0 on fully-defensive days and
0 on risk-on days, `w̄` is essentially the **share of time spent defensive**:

| Book | avg defensive wt | share of sessions defensive | why they differ |
|---|---|---|---|
| 0042 | 45.03 % | 44.98 % | tiny difference: staleness handling |
| 0043 | 45.45 % | 45.40 % | ditto |
| 0044 | **39.50 %** | 40.59 % | 27 sessions at w = 0.5 pull the mean below the count |
| 0045 | **38.95 %** | 41.35 % | 58 sessions at w = 0.5 |

### The comparison

```
timing_premium = expm1( overlay_value_add_log  −  static_value_add_log )
```

Both terms are log excesses over the same parent with the same reference sleeve,
so the subtraction is exact.

### What it answers

Whether the switching did anything **beyond simply holding less equity on
average**. If overlay ≈ static, the overlay is a de-risking rule wearing a
timing rule's clothes.

### Source files

`robustness.py:static_mix` (lines 208–231) → `evidence/main/static_mix_control.csv`.

### Limitation

The static control holds the sleeve continuously, which over this window means
holding gold continuously through a gold bull market. So the static arm is
itself flattered, and the timing premium is measured against a generous
baseline. It is favourable to the overlay in only two of four books even so.

---

## Reading the statistics — a plain-language primer

Three quantities appear beside almost every return in this study. Worked through
on 0043, the strongest of the four.

### Why a null at all

We want to know whether the *timing* was skilled. Comparing against "no overlay"
cannot answer that, because sitting in gold at all had an effect regardless of
when. So we need a comparison that holds everything constant *except* the timing.

The analogy: someone claims they can pick when to take holiday to get good
weather. Last year they took 6 holidays totalling 45 days and got great weather.
Skill? Test it by taking **those same 6 holidays, same lengths**, and sliding them
to random dates in the same year, 10,000 times. Same trip count, same durations,
same total days off — only *when* changes. That is exactly the episode-relocation
null, applied to 0043's 6 risk-off episodes.

### `null_sd` — how much luck alone swings the answer

The 10,000 random placements produce 10,000 outcomes, with an average
(`null_mean`, +23.95 % for 0043 — random placement does well here because gold
rose over the window) and a spread.

**`null_sd` is that spread**: if you had no skill at all, how much would your
result bounce around purely from where the episodes happened to land?

0043's is **0.247 in log terms** — large. Random placement routinely lands
anywhere from roughly −20 % to +80 %. So a good result is not impressive on its
own; luck produces good results here constantly.

0043 observed +59.18 %. The **edge** over luck is a ratio, not a difference:
`1.5918 / 1.2395 − 1` = **+28.4 %**. Better than average, but 16 of every 100
random placements still beat it. Not a rare event.

#### The exact formula

Not a closed form — an empirical (Monte Carlo) standard deviation.
`robustness.py:155-167`:

```
For each draw k = 1 … K   (K = 10,000, seed 1729):

  1.  w⁽ᵏ⁾  = place the SAME episode blocks at random, non-overlapping
              positions in the 1,186-session window; each block keeps its
              exact length and internal weight profile
  2.  s⁽ᵏ⁾ₜ = (1 − w⁽ᵏ⁾ₜ)·r_parent,ₜ + w⁽ᵏ⁾ₜ·r_sleeve,ₜ
  3.  Vₖ    = Σₜ [ log(1 + s⁽ᵏ⁾ₜ) − log(1 + r_parent,ₜ) ]

  V̄       = (1/K) · Σₖ Vₖ                        →  null_mean_log
  null_sd = √[ (1/(K−1)) · Σₖ (Vₖ − V̄)² ]        →  numpy .std(ddof=1)
```

Reproduced independently at 3,000 draws: **0.2497** against the published
**0.2469** at 10,000 draws.

**The trap: this is the sd of the distribution, not the standard error of its
mean.** It answers "how much does a *single* random placement vary?", not "how
precisely do I know the null's average?".

| | Value | z for 0043 |
|---|---|---|
| `null_sd` = std(V, ddof=1) | 0.2497 | **0.98** ✓ |
| standard error = null_sd/√K | 0.0046 | 53.46 ✗ |

Using the standard error would make every result in this study look
overwhelmingly significant and be nonsense — the question is whether *one*
random placement could produce +59 %. More draws sharpen `null_mean`; they leave
`null_sd` where it is. That is the tell that it is a property of the process, not
of our sampling effort.

**`ddof=1`** divides by K−1 (Bessel). Immaterial at K=10,000; present for
consistency with the bootstrap, where n is 6.

**Units differ between the two nulls.** §5d's `V` is a **log** value-add, so
`null_sd_log` is in log units and `mde_log = 2.80 × null_sd` is converted back
with `expm1`. §5e's draws are already **annualised returns**
(`expm1(mean(log r_gold) × 252)`, `phase8_signals.py:216-229`), so its `null_sd`
is in return units and `mde_pp = 2.80 × sd × 100` is directly in percentage
points. Do not compare 0.247 against 28 pp.

**Why `null_sd` is so large.** 0043's six blocks are **52, 120, 84, 27, 84 and
172 sessions**. A 172-session block landing in a good stretch rather than a bad
one moves the entire statistic. Six chunky blocks are a far noisier thing to
place than 600 individual days would be — that, not the test design, is what sets
the MDE.

### `obs_sd` — how much our own measurement would swing

The +59.18 % is itself one sample. Had history rolled slightly differently we
would have measured something else. How much else?

Estimated by **bootstrap**: the total is the sum of 6 episode-level
contributions, so resample those 6 with replacement (some appear twice, some not
at all), sum, repeat 2,000 times, take the spread. `obs_sd` = **0.330**.

**Why the ratio is reported.** `null_sd / obs_sd` = 0.247 / 0.330 = **0.749**. The
statistic's own wobble is *wider than the entire null distribution*. So "84th
percentile" is not a stable number — a slightly different history could have put
the same strategy at the 40th or the 99th. The percentile implicitly assumes the
null's spread is a fair yardstick for the statistic's noise; below 1, it is not,
and the nominal figure **overstates** the evidence. All four books are below 1.

### `MDE` — how big an effect the test could even see

Minimum detectable effect. Asked *before* looking at any answer: given this much
noise, how large would a real effect have to be for the test to reliably find it?

```
MDE = 2.80 × null_sd          # 2.80 = 1.96 + 0.84
```

1.96 is the 5 % two-sided significance bar; 0.84 buys 80 % power — if the effect
really is that big you catch it 4 times in 5. Below the MDE a real effect usually
hides in the noise and you wrongly conclude "nothing here".

0043: `2.80 × 0.247 = 0.691` in logs → **+99.6 % cumulative**.

### Putting it together

| Book | Observed | Null mean | **Edge** | **MDE** | Edge as a fraction of MDE |
|---|---|---|---|---|---|
| 0042 | +34.99 % | +7.93 % | +25.07 % | +120.6 % | **1/4.8** |
| 0043 | +59.18 % | +23.95 % | +28.42 % | +99.6 % | **1/3.5** |
| 0044 | −0.96 % | −6.54 % | +5.97 % | +89.7 % | **1/15.0** |
| 0045 | −6.27 % | −5.07 % | negative | +106.3 % | — |

Every edge is a small fraction of the smallest effect its test can resolve. The
conclusion is therefore **not** "there was no skill" but **"this test was never
capable of answering the question"**. A genuine +28 % edge would fail to appear
here about as often as it appeared.

### Why the MDE is so large, and what would fix it

Only **6–7 episodes**. Noise falls roughly as 1/√n, so to shrink the MDE enough
to resolve the edge each book actually delivered:

| Book | Episodes now | Episodes needed | Years at this switching rate |
|---|---|---|---|
| 0042 | 6 | ~75 | **~60** |
| 0043 | 6 | ~46 | **~37** |
| 0044 | 7 | ~854 | ~585 |

(1/√n scaling is a heuristic here, since episodes vary in length — treat these as
orders of magnitude, not precise requirements.)

That is the binding constraint on this whole study. It is not a harsh test or a
modelling choice: 4.8 years at roughly 1.25 switches a year does not contain
enough independent decisions to separate a +28 % edge from luck. Which is why
every negative here reads **underpowered, not absent** — and why the *mechanism*
findings (gold supplied 84 % of the sleeve, the parent rose in 3 of 4 risk-off
windows, the rule loses on midcap's own index, two books half-sized their best
call) carry more weight than any significance test in this document. Those are
arithmetic on what happened, not inferences about what repeats.

---

## §5d — the episode-relocation null (the "random timing" test)

### The test, precisely

It is a **Monte Carlo permutation test with block preservation** — not a
t-test, not a bootstrap of returns, and there is no distributional assumption.

1. Extract the realized risk-off **episodes** as contiguous blocks of daily
   defensive weights. A block keeps its exact length *and* its internal weight
   profile, so a 0044 block that runs `[0.5, 0.5, 1.0, 1.0]` stays that shape.
   `robustness.py:episode_blocks`.
2. For each of **10,000 draws**: place all blocks at uniformly random
   **non-overlapping** start positions in the 1,186-session window.
   Rejection-sample 200 times per block, then fall back to sequential packing so
   an episode is never silently dropped. `robustness.py:random_state`.
3. For each draw compute the statistic:
   ```
   V = Σ_t [ log(1 + r_synth,t) − log(1 + r_parent,t) ]
   where r_synth,t = (1 − w_t)·r_parent,t + w_t·r_sleeve,t
   ```
   `robustness.py:value_add_log`.
4. Report the observed `V`'s **percentile** in the 10,000 draws, and
   `z = (V − mean(draws)) / sd(draws)`.

**What is held fixed:** the number of episodes, every episode's duration, every
episode's weight profile, and therefore total time spent defensive. **What
varies:** only *when* the episodes happen. So the null is precisely "was being
out of equity for this much time, in this many chunks, good on average in this
window?" and the alternative is "was the *placement* informative?"

### Two extra columns that stop the test being read as stronger than it is

- **`null_sd / observed_sd`.** The observed statistic's own sampling spread is
  estimated by an **episode-level bootstrap** — resample the 6–7 per-episode
  value-adds with replacement, 2,000 times, and take the sd of the sum
  (`robustness.py:162–166`). If the null's spread is *narrower* than the
  statistic's own, the percentile flatters the result. All four are **below 1**
  (0.75–1.00), so the percentiles are if anything overstated.
- **`MDE`, computed before the draws are looked at.** `mde_log = 2.80 × null_sd`
  — the two-sided 5 %, 80 %-power detectable effect. 2.80 = 1.96 + 0.84.

### Results (authoritative — from `null_random_timing.csv`)

| Book | observed | null mean | percentile | z | null_sd/obs_sd | MDE | episodes |
|---|---|---|---|---|---|---|---|
| 0042 | +34.99 % | +7.93 % | 77.6th | 0.792 | 0.970 | +120.6 % | 6 |
| 0043 | +59.18 % | +23.95 % | 84.3rd | **1.013** | 0.749 | +99.6 % | 6 |
| 0044 | −0.96 % | −6.54 % | 60.2nd | 0.254 | 0.996 | +89.7 % | 7 |
| 0045 | −6.27 % | −5.07 % | 48.5th | −0.049 | 0.921 | +106.3 % | 6 |

### Limitation — and the correct conclusion

With 6–7 episodes the MDE is roughly **+90 % to +120 % cumulative value-add**,
i.e. about twice the largest effect observed. The honest reading is **"this
history cannot distinguish skill from luck"**, not "there was no skill". A
negative result at this power level is not evidence of absence.

### Source files

`robustness.py:random_timing_null` → `evidence/main/null_random_timing.csv`,
`evidence/main/phase45_summary.json`.

---

## §5e — was the *gold* exposure well timed?

### Why this test exists separately

Gold is a **fixed half of the sleeve** and **no gold data enters the rule
anywhere**. The signal is a supertrend on equity indices. So the only lever the
strategy has over gold is *when it is holding the sleeve at all*. This test asks
whether that incidental lever landed in gold's better periods.

### The statistic

Gold's **annualised** return over exactly the sessions the book was defensive:

```
obs_ann = expm1( mean( log(1 + r_gold,t) for t ∈ T_off ) × 252 )
```

compared against the unconditional `expm1(mean(all log gold returns) × 252)` =
**27.9 %/yr**. `edge_pp = (obs_ann − uncond_ann) × 100`.

Note this is a **mean-of-log-returns annualisation**, not a CAGR over an elapsed
span — the off sessions are spliced, so there is no elapsed span to annualise over.

### The test

Same episode-relocation null as §5d, **1,200 draws**, seed 1729
(`phase8_signals.py:gold_timing`, lines 191–233). Episode count, durations and
total time in gold are all held fixed; only placement varies. `mde_pp = 2.80 × null_sd × 100`.

### Results (authoritative — from `gold_timing.csv`)

| Book | gold p.a. while held | unconditional | edge | percentile | z | MDE |
|---|---|---|---|---|---|---|
| 0042 | 38.60 % | 27.90 % | +10.70 pp | 83.7th | 1.005 | +28.4 pp |
| 0043 | 40.07 % | 27.90 % | +12.17 pp | 87.7th | **1.228** | +27.6 pp |
| 0044 | 27.10 % | 27.90 % | −0.79 pp | 50.3rd | −0.044 | +30.8 pp |
| 0045 | 26.06 % | 27.90 % | −1.84 pp | 45.3rd | −0.175 | +29.8 pp |

### How 38.60 % relates to §4 and §5a — one fact, three yardsticks

All three are the **same measurement**: gold's return over 0042's 534 risk-off
sessions. Both links are exact identities, not approximations:

```
§5e  =  §4's gold bar, annualised
        (1 + 0.9972) ^ (252/534) − 1  =  38.60 %     ✓ published 38.60 %

§5a  =  §4's gold bar ÷ §4's parent bar
        1.9972 / 1.1147 − 1           =  79.17 %     ✓ published 79.17 %
```

534 sessions ÷ 252 = **2.119 "years"**, so gold nearly doubling over that stretch
is 38.60 % a year.

| | Cumulative | Annualised |
|---|---|---|
| Parent | +11.47 % | +5.26 %/yr |
| Gold | **+99.72 %** ← §4 bar | **+38.60 %/yr** ← §5e |
| Gold ÷ parent | **+79.17 %** ← §5a all-gold | +31.68 %/yr |

Same numerator throughout. Only the yardstick changes:

| Section | Value | Presented as | Measured against |
|---|---|---|---|
| §4 | +99.72 % | cumulative | nothing — the raw level |
| §5a | +79.17 % | cumulative | **the parent** — what was given up to hold it |
| §5e | 38.60 %/yr | annualised | **gold's own all-window rate, 27.90 %** |

Three questions of one fact: §4 asks what gold did while the book was out of
equity (nearly doubled); §5a asks whether that beat the equity skipped (yes, by
79 points); §5e asks whether those were unusually good months *for gold* (yes by
10.7 pp/yr, but well inside what random placement produces).

**§5e is the only one where gold is compared to itself rather than to equity, and
that is the point.** §5a can be won purely by gold beating equity over the window,
which it did everywhere, always. §5e is the only test that isolates whether the
*choice of dates* carried information — and the +99.72 % cumulative figure cannot
answer that alone, because it has no baseline to beat.

Keep this separate from §4b's **+38.34 %**, which is gold's *weight-scaled
contribution* and does not annualise to anything in this table. See the
disambiguation note above.

### Limitations

1. Not significant. An 11–12 pp edge against a ~28–31 pp MDE is well inside what
   random placement produces.
2. **Fewer draws than §5d** (1,200 vs 10,000) because the statistic is more
   expensive; the percentile therefore has coarser resolution (~±1.4 pp).
3. Structurally, this cannot be *skill* — the rule has no gold input. It is an
   exposure the strategy happens to carry when equity trend is weak. That
   co-movement has an economic basis, so some persistence is reasonable to
   expect, but it is not a capability the strategy exercises.

---

## §6 — the 4×4 cross-application grid, and the "parent matters more" claim

### What is plotted

Each portfolio's **realized state series** applied to **every** parent. Rows =
whose signal; columns = which equity book. Values are `value_add_ann`:

```
value_add_ann = expm1( value_add_log / 4.80 years )
```

Because the *parent* replaces the AA's equity leg in every cell, the grid is
free of the tracking drift measured in §2. Own pairings are flagged
(`own_pairing = True`) and outlined in the chart.

Code: `robustness.py:cross_grid` → `evidence/main/cross_grid.csv`.

### ⚠ Correction — the claim in the report is not robust

The report says: *"the column spread (about 7 points from 0007 to 0010) is wider
than the row spread (about 5)."* The grid, in %/yr:

|  signal ↓ / parent → | 0003 | 0007 | 0010 | 0029 | row mean |
|---|---|---|---|---|---|
| 0042 | 6.45 | 9.73 | 2.24 | 3.79 | 5.55 |
| 0043 | 7.61 | 10.16 | 2.50 | 4.14 | 6.10 |
| 0044 | 0.46 | 3.17 | −0.20 | −2.60 | 0.21 |
| 0045 | 1.04 | 3.90 | 0.75 | −1.34 | 1.09 |
| **col mean** | **3.89** | **6.74** | **1.32** | **1.00** | |

There are two defensible ways to compute "spread", and they disagree:

| Measure | Signal effect | Parent effect | Verdict |
|---|---|---|---|
| Spread of **means** (best − worst) | **5.90 pp** | 5.74 pp | signal marginally wider |
| Mean **within-row / within-column** spread | 5.90 pp | **6.54 pp** | parent marginally wider |

The report's "about 7" is neither: it is the single **widest row**
(0043's row, 10.16 → 2.50 = **7.66 pp**), which is the most favourable cell pair
available. **The correct statement is that the two effects are the same size to
within about half a point, and this grid cannot rank them.** What the grid *does*
support, unambiguously, is that the 0042/0043 signals beat the 0044/0045 signals
on every single parent (16/16 cells), and that every signal does best on 0007 and
worst on 0010/0029.

New evidence file: `evidence/main/cross_grid_spreads.csv` (`phase12_ownindex.py:grid_spreads`).

---

## §6b — "Why the signals differ at all" (the agreement matrix)

### How the number is calculated

Not weeks — **daily sessions**. For each pair of books, the fraction of the
1,186 sessions on which both were in the same binary state:

```
state_i,t = 1 if wdef_i,t > 0 else 0          # risk-off flag, per session
agreement(i,j) = mean over all t of  1[ state_i,t == state_j,t ]
```

Four lines of code: `robustness.py:signal_agreement` (lines 306–313) →
`evidence/main/signal_agreement.csv`.

### Notes and limitations

- It is **binary and unweighted**. A session where 0044 sat at `w = 0.5`
  counts as fully "off" and therefore as *agreeing* with a fully-defensive
  0042 — the matrix cannot see partial states.
- Because states are forward-filled from weekly reviews, consecutive sessions
  are highly dependent. **The effective sample is ~236 weeks, not 1,186
  sessions**, so do not read these percentages as having 1,186-observation
  precision. A 0.4 pp difference (0042↔0043 at 99.58 %) is 5 weeks.
- 0042 and 0043 agree on **99.58 %** of sessions; 0044↔0045 on **97.55 %**;
  across the clusters 91.9–94.8 %.

### ⚠ Correction — two sentences in the report were stale

Both were written against the **three-factor** blend and survived the switch to
four factors. Fixed in this revision:

1. §6b said *"0003 and 0007 are 74–93% smallcap"*. On the four-factor fit 0003
   is 22 % smallcap and 58 % microcap; 0007 is 43 % and 22 %. The correct
   statement is that they carry **80 % and 65 % of their risk below the midcap
   line** (smallcap plus microcap), against 46–49 % midcap for 0010 and 0029.
2. §9 said *"all four parents are Smallcap-250-dominated (55–93 % implied), so
   'use the highest-weight index' collapses to running Smallcap 250
   everywhere"*. It does not. On four factors the largest bucket is **Microcap
   250** for 0003, **Smallcap 250** for 0007 and **Midcap 150** for both 0010 and
   0029 — so that policy sends the two midcap-tilted books to the worst signal
   in the grid. The conclusion (the policy is worse than what runs today) is
   unchanged and is if anything better supported; only the stated reason was wrong.


---

## §7b — the threshold sweep, and a framing correction

### What the sweep actually varies

`phase8_signals.py:threshold_sweep` scores each book's identified blend, then
sweeps the threshold 0.05 → 0.95 in 0.05 steps:

```
score_t = Σ_k  weight_k · SIGN_k,t            # SIGN is 0 or 1 per index
w_t     = 1  if score_t ≤ threshold  else 0   # 1 = defensive
```

**Because every `SIGN` is binary, a two-index blend can only produce four
possible scores.** The threshold therefore does not tune anything continuously —
it selects among exactly three logical rules. Decoded:

| Book | Weights | Possible scores | OR<br>(either buys) | SINGLE<br>(one index decides) | AND<br>(both must buy) |
|---|---|---|---|---|---|
| 0042 | SC100 .55 / MC150 .45 | 0, .45, .55, 1 | −0.67 % | **+7.61 %** ← actual, th 0.50 | **+8.11 %** |
| 0043 | SC100 .55 / MC150 .45 | 0, .45, .55, 1 | +1.70 % | **+10.16 %** ← actual, th 0.50 | **+10.20 %** |
| 0044 | SC100 .40 / MC150 .60 | 0, .40, .60, 1 | +0.05 % | +0.07 % | **+2.52 %** ← actual, th 0.60 |
| 0045 | MC100 .60 / SC100 .40 | 0, .40, .60, 1 | −2.92 % | −0.26 % | **+6.99 %** ← actual, th 0.60 |

Thresholds 0.05–0.35/0.40 all mean OR; 0.40/0.45–0.55 all mean SINGLE;
0.60–0.95 all mean AND. Verified by enumerating every binary combination against
each threshold.

### ⚠ Correction — the "cliff edge" reading was wrong

The report said *"0044 and 0045 sit exactly on a cliff edge … a genuine
fragility."* That is withdrawn.

**AND wins on all four books without exception**, and 0.60 → 0.95 all give the
identical answer. So 0044 and 0045 are **already at the best point available, on a
plateau nine steps wide**. The step at 0.60 is a step *up onto* the plateau, not a
ledge they are perched on. The only risk was ever setting the threshold *lower*,
which demotes them to SINGLE and costs 2.5 and 7.2 points.

**The mis-set books are 0042 and 0043**, sitting at SINGLE and giving up +0.50 and
+0.04 points a year by not requiring the second index to agree.

This is the same structural result §9 reaches independently and recommends as
`N100 AND SC100`. §7 had it first and mis-read it as fragility; the two sections
previously agreed on the arithmetic and contradicted each other in tone.

### One device to be aware of

For 0042 and 0043 the SC100 0.55 / MC150 0.45 blend in `SPEC` is a **construct for
the sweep**, not a claim about the live rule. At threshold 0.50 it is
mathematically identical to "Smallcap 100 alone" — which is what §7a's
reconciliation identified at 99.6 % and 100 % agreement. That equivalence is why
the sweep's 0.45–0.50 values (+7.61 %, +10.16 %) match the pure Smallcap 100 cells
in the §6c grid to the decimal.

Source: `phase8_signals.py:SPEC` and `:threshold_sweep` →
`evidence/main/threshold_sweep.csv`.

---

## §6c — "Which index times best?" (the 7×4 single-signal grid)

### What is plotted

Each index's **own published supertrend**, applied alone (no blend, no
threshold) to each parent basket, with the same fixed 50/50 reference sleeve.
Values are `value_add_ann`, %/yr.

- Signal source: the desk's own weekly `W_allRebal.xlsx` per index, decoded as
  `ST == FLB → BUY`, `ST == FUB → SELL` (`signals.py:load_index_signal`).
  These are **production's own signals**, not re-derived.
- Applied from the session **after** the Friday review date
  (`signals.py:daily_signals` shifts by +1 day, then forward-fills).
- `w = 1 − signal`, so SELL → fully in the sleeve.

Code: `phase8_signals.py:signal_grid` → `evidence/main/signal_grid.csv`.

### ⚠ Two gaps the report left, both now closed — see §12 below

1. **The diagonal was missing.** No index's signal was ever applied to the index
   it is computed on. That is the cleanest read of signal quality there is,
   because it removes stock selection entirely.
2. **Point-to-point returns with no dispersion.** A single 4.8-year cumulative
   number cannot tell a steady rule from one good quarter. `signal_grid.csv`
   did already carry `cagr`, `max_drawdown` and `pct_defensive` — the report
   simply did not show them.

Both are fixed in **§12**.

---

## §8b — how holdings get assigned to a market-cap bucket

### The honest state of this in Study 1

**Nothing in the Study 1 report depends on classifying a stock.** Every
market-cap figure comes from the §3 returns regression. The classification
discussion in §8b exists only to defend that choice and to report a sanity
check (`evidence/main/holdings_classification.csv`), and the report's treatment
of it is too thin — this section rewrites it.

### Why a holdings classification was not used

Over 2021-2023 the only membership data available was a **2026** snapshot.
Stamping 2026 membership on a 2022 holding mis-tags exactly the stocks that
changed size, and that bias sits directly on the mechanism being measured.
Measured cost of that approach: **12–33 % of 2021-2023 holdings were unmappable
at all.**

### What Study 2's Step 0 changed

`public.mcap_based_universe` supplied per-ticker market cap on **237 snapshot
dates, 2019-08-30 → 2026-08-24**, every month present. Two cadences were built:

| Cache file | Construction | Snapshots |
|---|---|---|
| `cache/mcap_ranks_monthly.csv` | point-in-time mcap, last snapshot of each calendar month | 85 |
| `cache/mcap_ranks_semiannual.csv` | NSE methodology: rank on **mean full market cap over the 6 months ending 31-Jan / 31-Jul**, effective end-March / end-September, held constant between | 13 |

Bands (from production's `cap_classifier_v2.py`, with the Microcap ceiling
widened from 750 to 900 after a band sweep): `1-100 Largecap`,
`101-250 Midcap`, `251-500 Smallcap`, `501-900 Microcap`, `>900 Unknown`.
Filter: `instrument_class = 'ordinary'` — ETFs, InvITs/REITs and partly-paid
classes are ineligible for these indices and leaving them in pushes every
ordinary stock down and breaks the boundaries.

Unmappable share fell from 12–33 % to **0.52 % overall** (max 1.85 % in 2026).

### Does `mcap_ranks_semiannual.csv` replicate the historical constituents? **No — and here is exactly how far off it is.**

Validated against real index membership on the 5 snapshots where we have it
(750 names each, 2026-04-09 → 2026-08-01), from
`evidence/segment_v1/classifier_vs_membership.csv`:

| Classifier | exact 4-bucket | 3-bucket (production's collapse) | recall Large | Mid | Small | Micro |
|---|---|---|---|---|---|---|
| **PIT semi-annual** | **86.7 %** | **94.0 %** | 88.0 % | 85.3 % | 81.7 % | 92.0 % |
| PIT monthly | 74.8–80.7 % | 91.5–92.4 % | 87–89 % | 79–81 % | 66–73 % | 76–85 % |

And precision is worse than recall for the bucket that was widened —
`band_sweep.csv`, band 501-900: **Microcap precision 57.5 %** against recall
92.0 %. The wide band catches almost every true microcap by also calling ~400
names microcap when only 250 are.

**So: roughly 1 name in 8 is in the wrong bucket, about 1 in 5 for Smallcap, and
the Microcap bucket is over-inclusive by ~60 %.** It also only reproduces
production's own three-bucket `mcat` label at 95.7 %, and reproduces
production's *bucket distribution* per book-week (the thing that actually feeds
the signal score) on only **64.3 %** of book-weeks
(`gate_v2_summary.json:pit_classifier_mcat_dist_match`).

**A rank band cannot do better than this, for structural reasons:**

1. **Buffers.** NSE does not remove an incumbent that merely slips a rank; it
   applies a buffer, so membership is **sticky and path-dependent**. A pure rank
   cut has no memory.
2. **Eligibility filters** that rank ignores: minimum listing history, trading
   frequency ≥ 90 %, turnover / impact cost, and F&O eligibility for Nifty 100.
3. **Parent-universe nesting.** Midcap 150 is ranks 101-250 *of the Nifty 500*,
   not of the whole market; Smallcap 250 is 251-500 of it. Our ranking is over
   the full ordinary universe (1,667 → 3,034 names), which is not the same
   ladder.
4. **Full vs free-float market cap** — selection uses one, weighting the other.
5. **Intra-period changes** from mergers, delistings and demergers, which happen
   off the semi-annual calendar entirely.
6. The 86.7 % is itself measured **only on 2026**. There is no way to know the
   2021-2023 error rate from this data.

### Recommended fix, in priority order

**A. NSE's own reconstitution change lists — do this one.** At each semi-annual
review NSE Indices publishes the additions and deletions per index. Roll
*backwards* from the membership we already hold (5 real snapshots, 2026-04-09 →
2026-08-01) by reversing each change list, and you recover **exact** point-in-time
membership. Over 2021-11 → 2026-08 that is roughly **10 review events** plus a
handful of intra-period change notices — a small, one-time, auditable job, and it
gives ground truth rather than a proxy. Also worth pulling the current
`ind_nifty100list.csv` / `ind_niftymidcap150list.csv` / `…smallcap250` /
`…microcap250` constituent files, which the old `cap_classifier.py` used and
which no longer exist on disk, as the anchor.

**B. Index-fund / ETF monthly portfolio disclosures — your suggestion, and a
good cross-check, but not sufficient alone.** SEBI mandates monthly portfolio
disclosure, so tracking funds give dated holdings *with weights*:

| Index | A usable tracker | Coverage issue |
|---|---|---|
| Nifty 100 | ICICI Pru Nifty 100 ETF / Index Fund | fine |
| Nifty Midcap 150 | Motilal Oswal Nifty Midcap 150 Index Fund | fine |
| Nifty Smallcap 250 | Nippon India Nifty Smallcap 250 Index Fund | fine |
| **Nifty Microcap 250** | Motilal Oswal Nifty Microcap 250 Index Fund | **launched Aug-2023** — nothing covers 2021-11 → 2023-08 |

Its four real drawbacks: the microcap gap lands on the bucket we most need; a
fund's holdings are its *tracking position*, not the index (cash drag, in-transit
trades, capped or sampled positions); monthly snapshots do not reveal the exact
reconstitution date; and it is ~4-5 funds × 58 months of files to scrape and
normalise. Use it to **validate** A, and to cover microcap from Aug-2023 on.

**C. Buy NSE Indices' historical constituent data.** Exact, dated, weighted.
Right answer if this becomes production infrastructure; needs procurement.

**D. Free, immediate, no new data: add a buffer rule to the rank classifier.**
Most of the 13 % error is churn at the boundaries, and NSE's buffer is exactly
the mechanism that suppresses that churn. Make bucket membership sticky — a name
only moves once it crosses the boundary by a buffer margin — and re-score
against the 5 real snapshots. This should recover a meaningful part of the gap
for an afternoon's work, and it is testable against evidence we already hold.

### Where this actually matters

For **Study 1**: nowhere load-bearing. §3 uses returns, not classification.
For **Study 2**: it is a **first-order input** — the arms literally select stocks
by bucket, so a 13 % bucket error and a 64 % distribution match propagate
straight into the headline. That is already pre-registered as a sensitivity
(`micro_noise.py` error model, `evidence/segment_v1/micro_noise_error_model.csv`),
and it is listed as an open item.

---

## §12 — NEW: the missing diagonal, and the dispersion the grid hid

Added in response to review. Code: `AA/analysis/phase12_ownindex.py`.
Run: `python phase12_ownindex.py --draws 2000`.

### 12a. Each index's supertrend applied to the index itself

**What is plotted / tabulated.** For each of the seven indices: hold the index
when its own signal is BUY, hold the fixed 50/50 GOLDBEES+cash sleeve when it is
SELL. Compare against buy-and-hold of the same index. This removes stock
selection completely — the only thing being measured is whether the trend rule
beat its own underlying.

Daily index levels: all seven sheets of
`…/Friday Rebalance Automation/Data/indices_ohlcv.xlsx`, reindexed to the study
calendar and forward-filled. Signals: as §6c, applied from the session after the
review date.

| Index | index CAGR | overlay CAGR | value-add p.a. | index Sharpe | overlay Sharpe | index max DD | overlay max DD | % defensive | rolling-12m win rate | percentile | z | MDE |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Nifty 50 | 6.50 % | 8.60 % | +1.98 % | 0.47 | 0.72 | −16.5 % | −16.4 % | 44.5 % | 63.5 % | 32nd | −0.50 | +56 % |
| Nifty 100 | 7.27 % | 12.93 % | **+5.28 %** | 0.51 | 1.10 | −17.5 % | −12.4 % | 40.1 % | 76.3 % | 72nd | 0.62 | +61 % |
| Midcap 100 | 16.19 % | 14.49 % | **−1.45 %** | 0.90 | 0.99 | −21.4 % | −16.1 % | 36.8 % | 33.9 % | 40th | −0.25 | +86 % |
| Midcap 150 | 15.79 % | 13.88 % | **−1.65 %** | 0.93 | 0.96 | −21.1 % | −16.8 % | 33.6 % | 42.0 % | 37th | −0.33 | +76 % |
| Smallcap 100 | 13.54 % | 21.85 % | **+7.33 %** | 0.67 | 1.40 | −33.4 % | −18.0 % | 45.5 % | 69.3 % | 85th | **1.04** | +117 % |
| Smallcap 250 | 14.85 % | 22.22 % | +6.43 % | 0.81 | 1.46 | −26.9 % | −20.0 % | 43.0 % | 61.6 % | 83rd | 0.98 | +111 % |
| Microcap 250 | 21.21 % | 24.91 % | +3.85 % | 1.01 | 1.55 | −28.5 % | −22.5 % | 42.5 % | 59.3 % | 79th | 0.84 | +132 % |

**Three things this says that the parent-only grid could not:**

1. **The rule loses money on both midcap indices.** −1.45 %/yr on Midcap 100 and
   −1.65 %/yr on Midcap 150, with rolling-12m win rates of 34 % and 42 %. On its
   own underlying, the midcap supertrend is worse than doing nothing. That is a
   cleaner indictment than anything in §6c, and it matters because Midcap 150
   carries ~46-49 % of the 0010 and 0029 blends — the two books the overlay hurt.
2. **Sharpe improves for every single index, and max drawdown falls for every
   single index.** Even where returns fall. The rule is a **risk-reduction
   mechanism**; that is its consistent, real effect. The return effect is the
   inconsistent part.
3. **Still no significance.** Best is Smallcap 100 at the 85th percentile,
   z = 1.04, against an MDE of +117 % cumulative. Same conclusion as §5d, now on
   the cleanest possible test bed: **the window is too short to call it.**

Equity curves for every row: `evidence/main/own_index_curves.csv`
(`<index>_index` and `<index>_overlay`, both based at 100).
Table: `evidence/main/own_index_signal_test.csv`.

Null: identical episode-relocation design to §5d, 2,000 draws, seed 1729.

### 12b. The dispersion the point-to-point numbers hid

**Rolling 12-month win rate** — the share of 252-session windows in which the
overlay beat the naked parent (`evidence/main/signal_grid_dispersion.csv`):

| signal ↓ / parent → | 0003 | 0007 | 0010 | 0029 |
|---|---|---|---|---|
| Nifty 50 | 47.1 % | 57.4 % | 45.2 % | 30.4 % |
| Nifty 100 | 51.2 % | 61.1 % | 50.7 % | 37.6 % |
| Midcap 100 | 47.4 % | 63.1 % | 36.8 % | 35.3 % |
| Midcap 150 | 44.5 % | 60.6 % | 30.1 % | 29.6 % |
| Smallcap 100 | 62.3 % | 65.6 % | 52.8 % | 44.9 % |
| Smallcap 250 | 57.9 % | **74.8 %** | 44.4 % | 40.5 % |
| Microcap 250 | 63.0 % | 69.4 % | 40.1 % | 42.3 % |

Only **one** of 28 cells exceeds 75 %. Most sit between 40 % and 65 % — a coin
flip. The 4.8-year cumulative numbers in §6c are not describing a rule that
worked consistently.

**Value-add by calendar year**, for the best signal in the grid (Smallcap 100),
from `evidence/main/signal_grid_yearly.csv`:

| Year | 0003 | 0007 | 0010 | 0029 |
|---|---|---|---|---|
| 2021 (2 months) | −1.7 % | −0.3 % | −3.7 % | −4.3 % |
| 2022 | +6.6 % | +7.6 % | −0.1 % | −3.8 % |
| 2023 | +6.3 % | +8.8 % | −0.1 % | −2.7 % |
| 2024 | **−9.1 %** | **−9.4 %** | −6.3 % | **−12.7 %** |
| 2025 | **+35.0 %** | **+32.4 %** | **+18.9 %** | **+39.3 %** |
| 2026 (8 months) | +4.1 % | +13.7 % | +5.2 % | +11.5 % |

**Essentially the entire multi-year edge is 2025.** In 2024 the same signal lost
6-13 points on all four books. This is the single most important thing to know
before quoting any number from §6c, and the report did not show it.

**Consequence for how the report should be read:** the cross-grid and
single-signal grid establish *ordering* — smallcap-family signals beat
midcap-family signals, weak parents are more improvable than strong ones — and
those orderings are stable. They do **not** establish that any of these rules
delivers a repeatable annual edge, and the year table is why.

---

## File index

### Code (`AA/analysis/`)

| File | What it produces |
|---|---|
| `common.py` | paths, `PAIRS`, state loader (keys on `availableDate`), CAGR/vol/DD helpers |
| `prices.py` | defensive ETF closes, `cash_total_return`, spliced index levels |
| `supertrend.py` | validated port of production `ST.py` (`MUL=2`, `DAYS_TO_CONSIDER=5`, linearly weighted ATR) |
| `signals.py` | decodes `ST/FUB/FLB` → BUY/SELL, projects weekly → daily with the +1 session shift |
| `build_panel.py` | `panel_daily.csv`, identity/tracking-drift check |
| `attribute.py` | scorecard, exact log attribution, episode ledger, `implied_mcap_blend` |
| `robustness.py` | timing null, static mix, lag shift, sleeve swap, cross grid, agreement |
| `regime.py` | regime conditioning |
| `phase8_signals.py` | signal reconciliation, 7×4 single-signal grid, threshold sweep, gold-timing null |
| `phase9_improve.py` | off-window economics, improvement search |
| `phase10_policy.py` | policy ranking (`N100 AND SC100` etc.) |
| `phase11_classification.py` | 3- vs 4-factor comparison, holdings classification |
| **`phase12_ownindex.py`** | **NEW — own-index diagonal, grid dispersion, cross-grid spreads** |
| `report.py` | the HTML report and all chart helpers |
| `casebook.py` | the cross-study casebook artifact |

### External data

| Source | Path |
|---|---|
| AA & parent NAVs | `AA/Historical Data/{indices,parentIndices}.csv` |
| AA weight history | `AA/Historical Data/SCMO_004x_Weight.csv` |
| Adjusted LIQUIDBEES | `AA/Historical Data/LBES_Adjusted_Price_data_2026_08_10.csv` |
| Index OHLCV (7 sheets) | `…/Friday Rebalance Automation/Data/indices_ohlcv.xlsx` |
| Per-index supertrend | `…/Friday Rebalance Automation/RSI/Final/<Index>/W_allRebal.xlsx` |
| Production signal masters | `…/Friday Rebalance Automation/RSI/Final/Analysis/Master_*.xlsx` |
| Parent rebalance history | `…/Friday Rebalance Automation/Rebalance_history/Rebalance_history_by_scid_*.csv` |
| Trading calendar | `…/Friday Rebalance Automation/Data/calendar.csv` |
| Market caps | Postgres `public.mcap_based_universe` (read-only) |
| Stock prices | Postgres `merged_historical_data_with_rics` (read-only) |

### Reproduce

```bash
cd AA/analysis
python build_panel.py            # panel_daily.csv + identity check
python attribute.py              # scorecard, attribution, blends, episodes
python robustness.py             # nulls, static mix, cross grid   (~3 min)
python phase8_signals.py         # signal grid, threshold sweep, gold null
python phase9_improve.py
python phase10_policy.py
python phase11_classification.py
python phase12_ownindex.py       # own-index diagonal + dispersion  (NEW)
python report.py                 # rebuild evidence/main/report.html
```

---

## Standing caveats for the whole study

1. **Gross only.** No transaction cost anywhere in Study 1. The episode summary
   reports a breakeven round-trip cost (`episode_summary.csv:breakeven_roundtrip_bps`)
   but no arm is charged.
2. **One gold bull market.** Gold BeES compounded at 27.3 %/yr across the whole
   window with no interruption. Every sleeve-dependent result is regime-bound.
3. **4.8 years, 6-7 episodes per book, ~236 weekly reviews.** MDEs of +90 % to
   +130 % cumulative follow from that, and they are why nothing in this study
   reaches significance. Read every negative as "underpowered", not "absent".
4. **Time concentration.** 2022Q2 is 81 % of 0042's total excess; 2026Q1 is 69 %
   of 0043's (`time_concentration.csv`). Only 35-55 % of quarters are positive.
5. **The published AA NAVs contain execution defects the backtests do not.** All
   four books desynced from their parent's 2022-09-19 reconstitution, up to 6 of
   15 names off, on 5-6 % of in-equity reviews.
6. **Spec drift.** The live 0042/0043 track record was produced by a Smallcap
   **100** rule; production v2 uses Smallcap **250**. Confirmed from production's
   own `index_signal` string in Study 2's gate.
7. **`wm-research/.git` is broken/empty — none of this is version controlled.**
   Flagged, not fixed; `git init` needs your say-so.
