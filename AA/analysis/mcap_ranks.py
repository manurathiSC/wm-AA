# -*- coding: utf-8 -*-
"""
Point-in-time market-cap classification for the segment-selection study.

Production (`cap_classifier_v2.py`) classifies a ticker by looking up which
NSE index it is *currently* a member of, reading `index_constituents_monthly`.
That table holds five snapshots (2026-04-09 -> 2026-08-01) and nothing before,
so it cannot classify a 2022 holding. Using it anyway would stamp 2026
membership onto 2021-2023 books, mis-tagging precisely the stocks that changed
size -- a bias sitting directly on the mechanism this study tests.

`mcap_based_universe` is the way out: 902k rows of per-ticker market cap on 412
snapshot dates from 2005-01-31, month-end through 2025 and daily from 2026.
Every calendar month from 2021-01 to 2026-08 is present, none missing.

Ranking that on NSE's own methodology reproduces production's three-bucket
output on the parent holdings to 95.7% (see `classify_validate.py`). Two
choices get it there:

  1. **Rank on a six-month average market cap, not a point-in-time one.** NSE
     ranks on average full market capitalisation over the six months ending
     31-Jan / 31-Jul. Point-in-time ranking scores 89.8%.
  2. **Reconstitute semi-annually, not monthly.** Membership is effective at
     end-March / end-September and held constant between. A monthly re-ranking
     churns names across the boundary that the real index never moved.

Ranking is over `instrument_class == 'ordinary'` only. ETFs, trusts (InvITs /
REITs) and partly-paid special classes are not eligible for these indices, and
leaving them in pushes every ordinary stock down the ranks.

What this does not reproduce: NSE's buffer rules (an incumbent is retained
unless it falls well past the boundary) and free-float adjustments. Those are
what most of the residual disagreement with production is made of.

Caveat on Microcap. Even after widening the band to 501-900 (see below and
`band_sweep.py`), Microcap remains the least reliable bucket -- precision
0.575 against 0.68 for the 501-750 band, because widening trades false
negatives for false positives. The false positives are names in no index at
all, which under `micro_own` get routed to the Microcap 250 signal rather than
Smallcap 250; for a company too small to make Microcap 250 that is arguably
the better proxy, but it is an assumption, not a validated result. The
`micro_own` arm ships with a resampling error bar for this reason
(`micro_noise.py`).
"""

from __future__ import annotations

import sys

import pandas as pd

from common import CACHE_DIR, PG_FETCH_DIR

# Strict priority, no overlaps. The first three boundaries are the ones
# `cap_classifier_v2.py` uses and NSE's methodology confirms: Nifty 100 is the
# top 100, Midcap 150 the next 150, and Nifty 500 the top 500 so Smallcap 250
# is 251-500.
#
# The Microcap ceiling is NOT 750. Nominally Microcap 250 is "the top 250
# beyond the Nifty 500", but a constituent must also rank inside the top 1000
# on six-month average turnover and market cap and must have traded on 90% of
# sessions; names in 501-750 that fail those filters are replaced by
# lower-ranked ones, so realised membership reaches past 750. Sweeping the
# ceiling against the five real membership snapshots (`band_sweep.py`) picks
# 900: Microcap recall 68.5% -> 92.4%, F1 0.684 -> 0.709, and the number of
# true Microcap 250 members misfiled as Unknown falls from 62 to 3.
MICRO_CEILING = 900

BANDS: list[tuple[int, str]] = [
    (100, "Largecap"),
    (250, "Midcap"),
    (500, "Smallcap"),
    (MICRO_CEILING, "Microcap"),
]
UNKNOWN = "Unknown"
CATEGORIES = [c for _, c in BANDS] + [UNKNOWN]

# Production's own three-bucket label, as written into the weekly
# `rebalance_{DDMMYY}.xlsx` sheets. Small, Micro and Unknown all collapse.
CAT_TO_MCAT = {
    "Largecap": "LCAP",
    "Midcap": "MCAP",
    "Smallcap": "SCAP",
    "Microcap": "SCAP",
    "Unknown": "SCAP",
}

# NSE index_name -> our category, for validating against real membership.
INDEX_NAME_TO_CAT = {
    "NIFTY 100": "Largecap",
    "NIFTY MIDCAP 150": "Midcap",
    "NIFTY SMALLCAP 250": "Smallcap",
    "NIFTY MICROCAP 250": "Microcap",
}

# NSE's reference window ends 31-Jan / 31-Jul; the change is effective at the
# end of the following March / September.
LOOKBACK_MONTHS = 6
REFERENCE_MONTH_ENDS = (1, 7)   # Jan, Jul
EFFECTIVE_MONTH_ENDS = (3, 9)   # Mar, Sep

START = "2019-08-01"   # two reconstitutions of runway before the 2021-11 window
END = "2026-08-31"


def band_of(rank: int) -> str:
    """Rank (1 = largest) -> cap category."""
    for hi, cat in BANDS:
        if rank <= hi:
            return cat
    return UNKNOWN


def _engine():
    p = str(PG_FETCH_DIR)
    if p not in sys.path:
        sys.path.insert(0, p)
    import pg_price_client  # noqa: PLC0415

    return pg_price_client._get_engine()


def raw_mcap(refresh: bool = False) -> pd.DataFrame:
    """
    Every ordinary-share market cap snapshot in the window: date, ticker, mcap.

    Cached, because the study re-runs many times and this is the only query
    that touches the whole universe rather than a handful of tickers.
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / "mcap_universe_raw.csv"
    if path.exists() and not refresh:
        return pd.read_csv(path, parse_dates=["date"])

    from sqlalchemy import text  # noqa: PLC0415

    sql = text(
        "SELECT date, ticker, mcap FROM public.mcap_based_universe "
        "WHERE date >= :start AND date <= :end "
        "AND instrument_class = 'ordinary' AND mcap IS NOT NULL AND ticker IS NOT NULL"
    )
    with _engine().connect() as conn:
        df = pd.read_sql(sql, conn, params={"start": START, "end": END})

    df["date"] = pd.to_datetime(df["date"])
    df["ticker"] = df["ticker"].str.strip().str.upper()
    df["mcap"] = df["mcap"].astype(float)
    # One row per (date, ticker); keep the largest if a ticker ever doubles up.
    df = (
        df.sort_values("mcap", ascending=False)
        .drop_duplicates(subset=["date", "ticker"], keep="first")
        .sort_values(["date", "ticker"])
        .reset_index(drop=True)
    )
    df.to_csv(path, index=False)
    return df


def _month_end_grid(df: pd.DataFrame) -> pd.DataFrame:
    """
    Collapse to one snapshot per calendar month -- the last available date in
    each month. Pre-2026 the source is already month-end; from 2026 it turns
    daily, and keeping that would silently refresh classification every day in
    the last eight months of the window while it refreshes monthly everywhere
    else. Holding the cadence fixed is what makes the window comparable.
    """
    d = df.copy()
    d["month"] = d["date"].dt.to_period("M")
    last = d.groupby("month")["date"].transform("max")
    return d[d["date"] == last].drop(columns="month")


def monthly_ranks(refresh: bool = False) -> pd.DataFrame:
    """
    Monthly point-in-time ranks: snapshot_date, ticker, mcap, rank, category.

    Rank 1 is the largest. This is the `monthly` cadence arm -- a fresh
    re-ranking every month, which is *not* how the real indices behave.
    """
    d = _month_end_grid(raw_mcap(refresh=refresh))
    d = d.sort_values(["date", "mcap"], ascending=[True, False])
    d["rank"] = d.groupby("date").cumcount() + 1
    d["category"] = d["rank"].map(band_of)
    return d.rename(columns={"date": "snapshot_date"}).reset_index(drop=True)


def reconstitution_dates(index) -> list[pd.Timestamp]:
    """
    The end-March / end-September effective dates spanned by `index`, plus the
    one immediately before it so the first review date has a live membership.
    """
    lo, hi = pd.Timestamp(min(index)), pd.Timestamp(max(index))
    out = []
    for year in range(lo.year - 1, hi.year + 2):
        for m in EFFECTIVE_MONTH_ENDS:
            out.append(pd.Timestamp(year=year, month=m, day=1) + pd.offsets.MonthEnd(0))
    out = sorted(d for d in out if d <= hi)
    # Keep everything from the last effective date on or before `lo` onwards.
    prior = [d for d in out if d <= lo]
    floor = prior[-1] if prior else out[0]
    return [d for d in out if d >= floor]


def semiannual_ranks(refresh: bool = False, effective_dates=None) -> pd.DataFrame:
    """
    Ranks on NSE's reconstitution calendar: for each effective date (end-March
    / end-September), rank on the mean market cap over the six months ending
    the preceding 31-Jan / 31-Jul, and hold that until the next effective date.

    Returns snapshot_date (= effective date), ticker, mcap (the six-month
    mean), rank, category, ref_start, ref_end, n_months.
    """
    raw = raw_mcap(refresh=refresh)
    if effective_dates is None:
        effective_dates = reconstitution_dates(raw["date"])

    frames = []
    for eff in effective_dates:
        # Mar -> reference ends 31-Jan same year; Sep -> 31-Jul same year.
        ref_month = REFERENCE_MONTH_ENDS[EFFECTIVE_MONTH_ENDS.index(eff.month)]
        ref_end = pd.Timestamp(year=eff.year, month=ref_month, day=1) + pd.offsets.MonthEnd(0)
        ref_start = ref_end - pd.DateOffset(months=LOOKBACK_MONTHS) + pd.Timedelta(days=1)

        w = raw[(raw["date"] >= ref_start) & (raw["date"] <= ref_end)]
        if w.empty:
            continue
        avg = (
            w.groupby("ticker")["mcap"].mean()
            .sort_values(ascending=False)
            .reset_index()
        )
        avg["rank"] = range(1, len(avg) + 1)
        avg["category"] = avg["rank"].map(band_of)
        avg["snapshot_date"] = eff
        avg["ref_start"] = ref_start
        avg["ref_end"] = ref_end
        avg["n_months"] = w["date"].dt.to_period("M").nunique()
        frames.append(avg)

    return pd.concat(frames, ignore_index=True)[
        ["snapshot_date", "ticker", "mcap", "rank", "category",
         "ref_start", "ref_end", "n_months"]
    ]


def build_cache(refresh: bool = False) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Write both cadences to `cache/` and return them."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    m = monthly_ranks(refresh=refresh)
    s = semiannual_ranks(refresh=refresh)
    m.to_csv(CACHE_DIR / "mcap_ranks_monthly.csv", index=False)
    s.to_csv(CACHE_DIR / "mcap_ranks_semiannual.csv", index=False)
    return m, s


CACHE_NAME = {"monthly": "mcap_ranks_monthly.csv",
              "semiannual": "mcap_ranks_semiannual.csv"}


def load_cache(cadence: str = "semiannual") -> pd.DataFrame:
    """Read a cached rank table, building it if absent."""
    path = CACHE_DIR / CACHE_NAME[cadence]
    if not path.exists():
        build_cache()
    head = pd.read_csv(path, nrows=0).columns
    dates = [c for c in ("snapshot_date", "ref_start", "ref_end") if c in head]
    return pd.read_csv(path, parse_dates=dates)


class PITClassifier:
    """
    Point-in-time ticker -> category lookup.

    `classify(ticker, asof)` uses the latest snapshot dated on or before
    `asof`, never a later one. A ticker absent from that snapshot is
    `Unknown`, matching production's treatment of anything past rank 750.
    """

    def __init__(self, ranks: pd.DataFrame):
        self._snaps = sorted(pd.to_datetime(ranks["snapshot_date"]).unique())
        self._by_snap = {
            d: dict(zip(g["ticker"], g["category"]))
            for d, g in ranks.groupby("snapshot_date")
        }
        self._rank_by_snap = {
            d: dict(zip(g["ticker"], g["rank"]))
            for d, g in ranks.groupby("snapshot_date")
        }

    @classmethod
    def from_cache(cls, cadence: str = "semiannual") -> "PITClassifier":
        return cls(load_cache(cadence))

    def snapshot_asof(self, asof):
        asof = pd.Timestamp(asof)
        prior = [d for d in self._snaps if d <= asof]
        return prior[-1] if prior else None

    def classify(self, ticker: str, asof) -> str:
        snap = self.snapshot_asof(asof)
        if snap is None:
            return UNKNOWN
        return self._by_snap[snap].get(str(ticker).strip().upper(), UNKNOWN)

    def rank(self, ticker: str, asof):
        snap = self.snapshot_asof(asof)
        if snap is None:
            return None
        return self._rank_by_snap[snap].get(str(ticker).strip().upper())

    def classify_many(self, tickers, asof) -> dict[str, str]:
        snap = self.snapshot_asof(asof)
        lut = self._by_snap.get(snap, {})
        return {t: lut.get(str(t).strip().upper(), UNKNOWN) for t in tickers}

    def mcat(self, ticker: str, asof) -> str:
        """Production's three-bucket label, for validation against `mcat`."""
        return CAT_TO_MCAT[self.classify(ticker, asof)]


if __name__ == "__main__":
    m, s = build_cache(refresh=False)
    print(f"monthly    {len(m):>8,} rows  {m['snapshot_date'].nunique():>3} snapshots  "
          f"{m['snapshot_date'].min().date()} -> {m['snapshot_date'].max().date()}")
    print(f"semiannual {len(s):>8,} rows  {s['snapshot_date'].nunique():>3} snapshots  "
          f"{s['snapshot_date'].min().date()} -> {s['snapshot_date'].max().date()}")
