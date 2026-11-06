# -*- coding: utf-8 -*-
"""
Build synthetic bucket indices from point-in-time constituents.

Two jobs, both narrow (Work item 1 was descoped once Step 0 settled the
cadence on stronger evidence):

  (a) **Confirmatory.** Rebuild Largecap / Midcap / Smallcap / Microcap on the
      semi-annual cadence and check them against the official NSE series --
      daily return correlation, annualised tracking error, and above all the
      weekly SIGN agreement, since SIGN is the only thing the backtest
      consumes. The bar is ~97%.

  (b) **Additive.** Nifty Microcap 250's official history starts 2022-01-10
      and `Master_NiftyMicrocap250.xlsx` only 2022-02-18, leaving the first
      months of the 2021-11-01 window with no microcap signal at all -- a real
      hole in the `micro_own` arm. A self-built series can reach back further.
      It is validated over the overlap before any of it is used.

Mechanics follow `52wk-high-portfolio/portfolio_52wk_high.py::simulate()`,
reusing its conventions rather than the function:

  * positions in **units** plus cash, NAV starting at 1.0;
  * fills at **OHLC4** = (o+h+l+c)/4, and a bar with any NaN leg is not
    fillable, so the name is ineligible that session;
  * interior sessions marked at **forward-filled close**, so a price gap
    cannot silently vanish a position out of the NAV;
  * the reconstitution session stamped at the **fill** price, not the close,
    with measurement starting the session *before* the first fill where NAV is
    exactly 1.0 (finding F-M08 -- getting this wrong drops the first
    session's move, and the error is not uniform in sign);
  * equal weight at `nav_now / n_names`, reset at each reconstitution.

Equal weight is a deliberate simplification: the official indices are
free-float capitalisation weighted. It is why the comparison against
`official` is directional and not a level match. It cannot be avoided here --
free-float factors are not in the DB.
"""

from __future__ import annotations

import sys

import numpy as np
import pandas as pd

from common import CACHE_DIR, PG_FETCH_DIR
from mcap_ranks import MICRO_CEILING, load_cache
from supertrend import DAYS_TO_CONSIDER, MUL, load_index_ohlcv, supertrend, to_weekly

BASE = 100.0

# Bucket -> (rank_lo, rank_hi) and the official sheet it is compared against.
BUCKET_BANDS = {
    "Largecap": (1, 100),
    "Midcap": (101, 250),
    "Smallcap": (251, 500),
    "Microcap": (501, MICRO_CEILING),
}
OFFICIAL_SHEET = {
    "Largecap": "Nifty100",
    "Midcap": "NiftyMidcap150",
    "Smallcap": "NiftySmallcap250",
    "Microcap": "NiftyMicrocap250",
}

PRICE_START = "2021-06-01"   # runway before the 2021-11-01 window opens
PRICE_END = "2026-08-21"
CHUNK = 120


# ── Prices ─────────────────────────────────────────────────────────────────
def _engine():
    p = str(PG_FETCH_DIR)
    if p not in sys.path:
        sys.path.insert(0, p)
    import pg_price_client  # noqa: PLC0415

    return pg_price_client._get_engine()


def universe_ohlcv(tickers: list[str], refresh: bool = False) -> pd.DataFrame:
    """
    Long-format daily OHLCV for a ticker list, cached.

    Chunked rather than one query per ticker: 1,337 names over five years is
    ~1.6M rows, and 1,337 round trips to an internal host over VPN is the slow
    way to get them.
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / "universe_ohlcv.parquet"
    if path.exists() and not refresh:
        d = pd.read_parquet(path)
        if set(tickers) <= set(d["ticker"].unique()):
            return d

    from sqlalchemy import text  # noqa: PLC0415

    sql = text(
        "SELECT date, ticker, open, high, low, close FROM merged_historical_data_with_rics "
        "WHERE ticker = ANY(:tickers) AND date >= :start AND date <= :end"
    )
    frames = []
    with _engine().connect() as conn:
        for i in range(0, len(tickers), CHUNK):
            chunk = tickers[i:i + CHUNK]
            frames.append(pd.read_sql(sql, conn, params={
                "tickers": chunk, "start": PRICE_START, "end": PRICE_END}))
            print(f"  fetched {min(i + CHUNK, len(tickers)):>5}/{len(tickers)}", flush=True)

    d = pd.concat(frames, ignore_index=True)
    d["date"] = pd.to_datetime(d["date"])
    d["ticker"] = d["ticker"].str.strip().str.upper()
    for c in ("open", "high", "low", "close"):
        d[c] = pd.to_numeric(d[c], errors="coerce")
    d = d.drop_duplicates(subset=["date", "ticker"]).sort_values(["ticker", "date"])
    d.to_parquet(path, index=False)
    return d


class Panel:
    """Wide OHLC4 / close matrices on a fixed calendar, plus the fill rule."""

    def __init__(self, ohlcv: pd.DataFrame, calendar: pd.DatetimeIndex):
        self.calendar = calendar
        piv = {c: ohlcv.pivot(index="date", columns="ticker", values=c)
               .reindex(calendar) for c in ("open", "high", "low", "close")}
        # OHLC4 is NaN if ANY leg is missing -- that is the "not fillable" rule.
        self.fill = (piv["open"] + piv["high"] + piv["low"] + piv["close"]) / 4.0
        # Marking uses forward-filled close so a gap never vanishes a position.
        self.mark = piv["close"].ffill()
        self.tickers = list(self.fill.columns)

    def fillable(self, i: int, names) -> list[str]:
        row = self.fill.iloc[i]
        return [t for t in names if t in row.index and np.isfinite(row[t])]


def build_index(panel: Panel, members_by_date: dict[pd.Timestamp, list[str]],
                base: float = BASE) -> tuple[pd.Series, pd.DataFrame]:
    """
    Equal-weight, units-based NAV over `panel.calendar`.

    `members_by_date` maps a reconstitution session to its constituent list.
    Returns the rebased level series and a per-reconstitution log.
    """
    cal = panel.calendar
    pos = {d: i for i, d in enumerate(cal)}
    recon = sorted(d for d in members_by_date if d in pos)
    if not recon:
        raise ValueError("no reconstitution date falls on the calendar")

    nav = np.full(len(cal), np.nan)
    units: dict[str, float] = {}
    cash = 1.0
    log = []

    first = pos[recon[0]]
    # Measurement starts the session BEFORE the first fill, where NAV == 1.0.
    if first == 0:
        raise ValueError("first reconstitution is the first session; no prior "
                         "session exists to anchor NAV at 1.0")
    nav[:first] = 1.0

    for k, d in enumerate(recon):
        i = pos[d]
        fill_row = panel.fill.iloc[i]

        # Mark the book at this session's FILL price, not its close: the
        # reconstitution trades here, so the value being redeployed is the
        # value realised at the fill.
        held_val = 0.0
        for t, u in units.items():
            px = fill_row.get(t, np.nan)
            if not np.isfinite(px):
                px = panel.mark.iloc[i].get(t, np.nan)
            held_val += u * (px if np.isfinite(px) else 0.0)
        nav_now = cash + held_val
        if not np.isfinite(nav_now) or nav_now <= 0:
            break

        names = panel.fillable(i, members_by_date[d])
        requested = len(members_by_date[d])
        if names:
            per = nav_now / len(names)
            units = {t: per / float(fill_row[t]) for t in names}
            cash = 0.0
        else:
            units, cash = {}, nav_now

        nav[i] = nav_now
        log.append({"date": d, "requested": requested, "filled": len(names),
                    "dropped_no_price": requested - len(names), "nav": nav_now})

        # Mark forward at ffilled close until the next reconstitution.
        end = pos[recon[k + 1]] if k + 1 < len(recon) else len(cal)
        for j in range(i + 1, end):
            row = panel.mark.iloc[j]
            v = sum(u * row.get(t, np.nan) for t, u in units.items())
            nav[j] = cash + (v if np.isfinite(v) else 0.0)

    s = pd.Series(nav, index=cal, name="level").ffill()
    return s / s.iloc[0] * base, pd.DataFrame(log)


def members_from_ranks(ranks: pd.DataFrame, bucket: str,
                       calendar: pd.DatetimeIndex,
                       start: pd.Timestamp) -> dict[pd.Timestamp, list[str]]:
    """
    Constituents per reconstitution, snapped to the first calendar session on
    or after each effective date.

    The snapshot already in force at `start` is stamped at the first session
    on or after `start` -- deliberately not at `calendar[0]`. The calendar is
    built with one session of lead-in precisely so that this first fill has a
    prior session to anchor NAV at 1.0 against (finding F-M08).
    """
    lo, hi = BUCKET_BANDS[bucket]
    sel = ranks[(ranks["rank"] >= lo) & (ranks["rank"] <= hi)]
    out: dict[pd.Timestamp, list[str]] = {}
    cal = pd.DatetimeIndex(calendar)

    at_start = cal[cal >= start]
    if not len(at_start):
        raise ValueError("calendar ends before `start`")
    first_fill = at_start[0]
    if first_fill == cal[0]:
        raise ValueError(
            "calendar must include at least one session before `start`; "
            "without it the first fill has no prior session to anchor NAV=1.0"
        )

    snaps = sorted(sel["snapshot_date"].unique())
    live = [d for d in snaps if d <= start]
    if live:
        out[first_fill] = sorted(sel[sel["snapshot_date"] == live[-1]]["ticker"])
    for d in snaps:
        if d <= start:
            continue
        later = cal[cal >= d]
        if len(later):
            out[later[0]] = sorted(sel[sel["snapshot_date"] == d]["ticker"])
    return out


# ── Comparison ─────────────────────────────────────────────────────────────
def weekly_signal(daily: pd.DataFrame) -> pd.Series:
    """
    Weekly supertrend SIGN for a daily OHLC frame.

    For a synthetic series there is no intraday data, so the weekly high and
    low are the max and min of the daily index levels inside the ISO week --
    stated explicitly because it is a real difference from the official
    series, whose weekly bars aggregate true intraday extremes.
    """
    return supertrend(to_weekly(daily), mul=MUL, days=DAYS_TO_CONSIDER)["signal"]


def synth_daily_frame(level: pd.Series) -> pd.DataFrame:
    """A synthetic series has one number per session; O=H=L=C at that level."""
    return pd.DataFrame({"open": level, "high": level, "low": level,
                         "close": level, "volume": 0.0})


def compare(synth: pd.Series, official: pd.DataFrame, label: str) -> dict:
    """Correlation, tracking error and weekly SIGN agreement against official."""
    off_close = official["close"]
    common = synth.index.intersection(off_close.index)
    a = synth.reindex(common).pct_change().dropna()
    b = off_close.reindex(common).pct_change().dropna()
    j = a.index.intersection(b.index)
    a, b = a.loc[j], b.loc[j]

    sig_s = weekly_signal(synth_daily_frame(synth)).dropna()
    sig_o = weekly_signal(official).dropna()
    ws = sig_s.index.intersection(sig_o.index)
    agree = (sig_s.loc[ws] == sig_o.loc[ws])

    return {
        "bucket": label,
        "sessions": int(len(j)),
        "overlap_start": str(j.min().date()),
        "overlap_end": str(j.max().date()),
        "corr_daily_returns": float(a.corr(b)),
        "tracking_error_ann": float((a - b).std(ddof=1) * np.sqrt(252)),
        "cagr_synth": float((synth.loc[common].iloc[-1] / synth.loc[common].iloc[0])
                            ** (252 / len(common)) - 1),
        "cagr_official": float((off_close.loc[common].iloc[-1] / off_close.loc[common].iloc[0])
                               ** (252 / len(common)) - 1),
        "weeks_compared": int(len(ws)),
        "weekly_sign_agreement": float(agree.mean()),
        "weeks_sign_differs": int((~agree).sum()),
        "dates_sign_differs": ", ".join(str(d.date()) for d in ws[~agree]),
    }
