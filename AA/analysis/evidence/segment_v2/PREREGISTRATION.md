# Segment-level overlay v2: pre-registration

Written 2026-09-25, before any v2 run. Its sha256 is recorded in `audit.json`
by every v2 script. If this file changes after a result exists, the hash no
longer matches and the audit says so.

## Hypothesis

**H1.** For the four AA books (SCMO_0042–0045), holding only the parent
constituents whose own market-cap index is in a supertrend BUY beats switching
the whole book on the combined score, net of costs. The weight freed by
stocks whose index is in SELL goes to 50% gold / 50% cash.

The mechanism it predicts: a whole-book switch de-risks the entire parent when
only part of it is weak. Segment-level holding de-risks only the weak segment,
so a parent with good stock selection (0010 and 0029, the parents of 0044 and
0045) keeps more of its alpha.

## The rule under test (`sleeve`)

- **Reviews.** The Friday `Date` rows of production's `Master_*.xlsx` SIGN
  columns, from 2021-11-01 to 2026-08-21. A review's decision applies from the
  next session on the trading calendar, never the same session.
- **Parent basket.** The latest `availableDate` on or before the review.
- **Events.** An event is:
  - the first review;
  - any review where one of the four effective signals (Nifty 100,
    Nifty Midcap 150, Nifty Smallcap 250, Nifty Microcap 250) differs from the
    previous review; or
  - any review where the parent basket in effect changed.

  Tags and targets are rebuilt only at events. Between events the book is
  left to drift.
- **Effective signals.** Microcap 250 falls back to the Smallcap 250 SIGN
  wherever its own SIGN is missing (before 2022-02-18, and on its in-window
  NaNs).
- **Tags: a point-in-time cascade, applied per holding at each event, first
  match wins.** Holdings are matched on ISIN, with ticker as a fallback.
  1. `manual`: a row in `AA/Historical Data/bucket_overrides.csv` (empty at
     registration).
  2. `membership`: the latest `index_constituents_monthly` snapshot on or
     before the review lists the stock. Priority is Nifty 100 → Large,
     Midcap 150 → Mid, Smallcap 250 → Small, Microcap 250 → Micro.
  3. `nonmember_rank`: a membership snapshot exists but the stock is in none
     of the four indices. Use its monthly rank band.
  4. `rank`: no membership snapshot exists yet. Use the monthly rank band
     from `public.mcap_based_universe`, ordinary shares only, taking the
     latest month-end snapshot on or before the review. Bands are 1–100 Large,
     101–250 Mid, 251–500 Small, 501–900 Micro.
  5. `rank>900`: ranked, but beyond 900. Use the Microcap 250 signal.
  6. `unranked`: no rank at all. Use the Smallcap 250 signal.
- **Signal per bucket.** Large → Nifty 100, Mid → Midcap 150,
  Small → Smallcap 250, Micro → Microcap 250.
- **Weights.** Held names keep their parent weights. Freed weight goes 50%
  GOLDBEES and 50% LBES-adjusted cash.
- **Mechanics.** As in `segment_backtest.simulate`: units, OHLC4 fills,
  forward-filled close marks. Costs are charged on the change in each
  position, half the round-trip rate per side.

## Comparator and primary statistic

- **Comparator.** `production_v2`: production's whole-book rule
  (count-weighted FS ≥ 0.60 over Large → Nifty 100, Mid → Midcap 150,
  Small/Micro/Unknown → Smallcap 250). It is re-simulated on identical
  prices, fills, costs, sleeve and tags, re-tagged at every review as
  production does.
- **Primary statistic.** `D` = CAGR(`sleeve`) − CAGR(`production_v2`), at
  20.8 bps round-trip, over the common window.

## Gates (thresholds fixed now)

| Gate | Statistic | Pass rule |
|---|---|---|
| G0 data | CAGR(harness parent) − CAGR(published parent NAV, `parentIndices.csv`) per book | \|gap\| ≤ 1.00 pp/yr on all 4 books |
| G1 headline | `D` per book | D > 0 on ≥ 3 of 4 books **and** on both SCMO_0044 and SCMO_0045 |
| G2 static mix | CAGR(`sleeve` @ 20.8 bps) − CAGR(static mix). The static mix holds the harness parent at a constant equity weight equal to the arm's time-average equity weight, with the rest in the same 50/50 sleeve, rebalanced daily in return space at zero cost | > 0 on ≥ 3 books |
| G3 all-cash sleeve | `D` with the sleeve set to 100% cash for both `sleeve` and `production_v2` | D > 0 on ≥ 3 books |
| G4 timing luck | Circularly roll the joint weekly effective-SIGN matrix (all four indices together) by k reviews, for every k with 8 ≤ k ≤ N−8, where N is the number of in-window reviews. Recompute `D` at 20.8 bps for each k | share(D_k > 0) ≥ 0.70 on ≥ 3 books |
| G5 classification noise | 500 draws, seed 20260924. Re-sample each tag whose source is `rank` or `rank>900` from P(true bucket \| predicted bucket). The error model is estimated from monthly ranks against every membership snapshot, over the whole ranked universe. Draws are made per (ticker, rank snapshot), so a stock's error persists while the same snapshot is in use. A drawn truth of "not in any index" keeps the original band, which is what the cascade's step 3 would do. `membership`, `nonmember_rank`, `manual` and `unranked` tags are never perturbed. Recompute `D` each time | 10th percentile of D > 0 on ≥ 3 books |

**Verdict:**
- G0–G5 all pass → **SUPPORTED**.
- G1 passes but any of G2–G5 fails → **NOT PROVEN**, naming each failing gate.
- G1 fails → **REJECTED**.
- G0 is a precondition. If it fails after diagnosis, the verdict is still
  computed, but it is labelled as conditional on the unresolved gap, and the
  headline is also shown against the published parent NAV.

The verdict is written to `gates.json` whatever it is. No threshold, statistic,
draw count, seed or window may be changed after results exist. Any deviation is
logged in `METHODS.md` under "Deviations from pre-registration", with the
reason.

**Note on the Study 2 rule.** The noise rule in `micro_noise.verdict`
("inside p10–p90 means noise") is not used. An observed value inside the
perturbed band means the result is *robust* to mislabelling, so that rule is
inverted.

## Reported but not gated

- **Timing percentile.** The arm's CAGR minus the harness parent's CAGR,
  ranked within the G4 shift distribution.
- **Performance stats:** drawdown, Sharpe, turnover and cost for every
  series.
- **Comparisons against published NAVs:** the new rule against the
  published parent NAV and the published AA NAV.
- **Benchmarks:** Nifty 50/100/Midcap 150/Smallcap 250/Microcap 250, and each
  book's 4-factor style blend.
- **Sensitivities:**
  - ranks-only tagging;
  - every non-`membership` Unknown → sleeve;
  - every Unknown → Smallcap 250;
  - semi-annual ranks;
  - `micro_proxy`;
  - weekly re-tagging;
  - 0 and 50 bps costs;
  - `sleeve_n100gate`;
  - whole-book `N100 AND SC100`.

## Window

2021-11-01 → 2026-08-21, the same as Study 1, Study 2 and the published AA
NAVs.
