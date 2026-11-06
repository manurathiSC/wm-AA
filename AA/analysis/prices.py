# -*- coding: utf-8 -*-
"""
Price inputs for the AA attribution study: the defensive-sleeve ETFs and the
three market-cap indices the switching signal is defined on.

Two wrinkles handled here:

  1. The DB's index series stop at 2025-09-15, ~11 months short of the study
     window. `wm-aiReports/reports/benchmarks/benchmark_closes.csv` covers
     2025-07-01 -> 2026-08-05 and overlaps by 53 sessions. We splice on
     *returns*, not levels, because the two vendors' closes differ by up to
     ~0.2% (rounding/convention), which would put a visible step in a
     level-chained series.

  2. Everything is cached to CSV so later phases and re-runs never need the
     database.
"""

from __future__ import annotations

import sys

import pandas as pd

from common import (
    BENCHMARK_CLOSES,
    CACHE_DIR,
    DATA_DIR,
    DEFENSIVE_TICKERS,
    INDEX_CSV_COLUMNS,
    INDEX_DB_LAST,
    INDEX_DB_TICKERS,
    PG_FETCH_DIR,
)

START = "2021-10-01"
END = "2026-08-31"


def _client():
    p = str(PG_FETCH_DIR)
    if p not in sys.path:
        sys.path.insert(0, p)
    import pg_price_client  # noqa: PLC0415

    return pg_price_client


def _fetch_close(ticker: str) -> pd.Series:
    rows = _client().get_ohlcv_history(ticker, START, END, limit=10000)
    if not rows:
        raise ValueError(f"no rows in price DB for ticker {ticker!r}")
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    s = df.set_index("date")["close"].astype(float).sort_index()
    return s[~s.index.duplicated(keep="first")]


def defensive_prices(refresh: bool = False) -> pd.DataFrame:
    """Daily closes for the five sleeve ETFs, one column per ticker."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / "defensive_etf_closes.csv"
    if path.exists() and not refresh:
        return pd.read_csv(path, index_col=0, parse_dates=True)
    out = {t: _fetch_close(t) for t in sorted(DEFENSIVE_TICKERS)}
    df = pd.DataFrame(out).sort_index()
    df.to_csv(path)
    return df


def _spliced_index(key: str, bench_csv: pd.DataFrame) -> pd.Series:
    """
    One market-cap index over the full window: DB levels through 2025-09-15,
    then extended with returns from benchmark_closes.csv.
    """
    db = _fetch_close(INDEX_DB_TICKERS[key])
    db = db[db.index <= INDEX_DB_LAST]

    col = INDEX_CSV_COLUMNS[key]
    ext = bench_csv[col].dropna()
    ext_ret = ext.pct_change()

    # Chain the tail's returns onto the DB level at the join.
    tail = ext_ret[ext_ret.index > db.index[-1]]
    level = db.iloc[-1]
    chained = {}
    for dt, r in tail.items():
        level = level * (1.0 + r)
        chained[dt] = level

    return pd.concat([db, pd.Series(chained)]).sort_index().rename(key)


def splice_report(bench_csv: pd.DataFrame) -> pd.DataFrame:
    """
    Per-index agreement between the two sources over their overlap. Recorded
    in the audit so no downstream conclusion silently rests on the splice.
    """
    rows = []
    for key, dbt in INDEX_DB_TICKERS.items():
        db = _fetch_close(dbt)
        col = INDEX_CSV_COLUMNS[key]
        ext = bench_csv[col].dropna()
        j = pd.concat([db.rename("db"), ext.rename("csv")], axis=1).dropna()
        if j.empty:
            rows.append({"index": key, "overlap_sessions": 0})
            continue
        rel = (j["db"] / j["csv"] - 1.0).abs()
        # Return-space agreement matters more than level agreement.
        rr = (db.pct_change().reindex(j.index) - ext.pct_change().reindex(j.index)).abs()
        rows.append(
            {
                "index": key,
                "overlap_sessions": int(len(j)),
                "overlap_start": j.index.min().date().isoformat(),
                "overlap_end": j.index.max().date().isoformat(),
                "max_rel_level_diff": float(rel.max()),
                "max_abs_return_diff": float(rr.max()),
                "median_abs_return_diff": float(rr.median()),
            }
        )
    return pd.DataFrame(rows)


def mcap_indices(refresh: bool = False) -> pd.DataFrame:
    """Spliced daily levels for Nifty 100 / Midcap 150 / Smallcap 250 / Nifty 50."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / "mcap_index_levels.csv"
    if path.exists() and not refresh:
        return pd.read_csv(path, index_col=0, parse_dates=True)

    bench = pd.read_csv(BENCHMARK_CLOSES)
    bench["date"] = pd.to_datetime(bench["date"])
    bench = bench.set_index("date").sort_index()

    df = pd.DataFrame({k: _spliced_index(k, bench) for k in INDEX_DB_TICKERS}).sort_index()
    df.to_csv(path)

    splice_report(bench).to_csv(CACHE_DIR / "splice_report.csv", index=False)
    return df


LBES_ADJ_CSV = DATA_DIR / "LBES_Adjusted_Price_data_2026_08_10.csv"


def cash_total_return(calendar: pd.Index, refresh: bool = False) -> pd.Series:
    """
    Total-return series for the cash leg, from the adjusted LIQUIDBEES history.

    LIQUIDBEES holds a constant NAV and distributes its yield as daily
    dividends, so its raw *price* history returns exactly 0.00% over any
    window and would credit the cash half of the sleeve with nothing. The
    adjusted file reinvests those distributions: 1000 -> 2389 across
    2007-2026, +4.99% a year over this study's window, following a realistic
    rate path (2.4% in 2021 rising to 5.9% in 2024, easing to 4.5% in 2026).

    The file ends a little before the study window does; the short tail
    accrues at the trailing realised rate rather than at zero.
    """
    d = pd.read_csv(LBES_ADJ_CSV)
    d["date"] = pd.to_datetime(d["date"], format="%d/%m/%y %H:%M")
    s = d.set_index("date")["price"].astype(float).sort_index()
    s = s[~s.index.duplicated(keep="first")]

    lvl = s.reindex(s.index.union(calendar)).ffill().reindex(calendar)
    r = lvl.pct_change()

    tail = calendar > s.index.max()
    if tail.any():
        recent = s.loc[s.index >= s.index.max() - pd.Timedelta(days=90)]
        yrs = (recent.index[-1] - recent.index[0]).days / 365.25
        ann = float((recent.iloc[-1] / recent.iloc[0]) ** (1.0 / yrs) - 1.0) if yrs > 0 else 0.05
        r = r.where(~tail, (1.0 + ann) ** (1.0 / 252.0) - 1.0)
    return r.rename("cash_tr")


def splice_report_cached() -> pd.DataFrame:
    path = CACHE_DIR / "splice_report.csv"
    if path.exists():
        return pd.read_csv(path)
    bench = pd.read_csv(BENCHMARK_CLOSES)
    bench["date"] = pd.to_datetime(bench["date"])
    return splice_report(bench.set_index("date").sort_index())
