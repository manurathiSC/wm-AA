# -*- coding: utf-8 -*-
"""
Performance statistics for the v2 report. Every function takes daily levels
on one calendar and handles a series that starts late (Microcap 250 and the
style blends begin 2022-01) by measuring over its own span, which is reported
alongside.

Conventions (repeated in METHODS.md):
  * CAGR is on calendar time: (end/start)^(365.25/days) - 1.
  * Vol is the daily-return std x sqrt(252).
  * Sharpe and Sortino are in excess of the cash leg (LBES-adjusted
    LIQUIDBEES total return). Study 1 reported CAGR/vol instead.
  * Up/down capture use monthly returns: mean series return in months the
    reference rose (fell) / mean reference return in those months.
  * Hit rate: share of rolling 252-session windows where the series beat the
    reference.
  * Best/worst year use full calendar years only (2022-2025); the partial
    2021 and 2026 years appear in the yearly table, labelled.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

TD = 252


def _span(level: pd.Series) -> pd.Series:
    return level.dropna()


def cagr(level: pd.Series) -> float:
    lv = _span(level)
    if len(lv) < 2:
        return np.nan
    yrs = (lv.index[-1] - lv.index[0]).days / 365.25
    return float((lv.iloc[-1] / lv.iloc[0]) ** (1 / yrs) - 1)


def drawdown(level: pd.Series) -> dict:
    lv = _span(level)
    dd = lv / lv.cummax() - 1
    trough = dd.idxmin()
    peak = lv.loc[:trough].idxmax()
    rec = lv.loc[trough:]
    rec = rec[rec >= lv.loc[peak]]
    return {"max_dd": float(dd.min()), "dd_peak": peak.date(), "dd_trough": trough.date(),
            "dd_recovery": rec.index[0].date() if len(rec) else None,
            "time_under_water": float((dd < -1e-9).mean())}


def yearly(level: pd.Series) -> pd.Series:
    lv = _span(level)
    ye = lv.groupby(lv.index.year).last()
    first = lv.iloc[0]
    prev = pd.concat([pd.Series([first], index=[ye.index[0] - 1]), ye]).shift(1).iloc[1:]
    return ye / prev - 1


def absolute(level: pd.Series, cash_level: pd.Series) -> dict:
    lv = _span(level)
    r = lv.pct_change().dropna()
    c = cagr(lv)
    vol = float(r.std(ddof=1) * np.sqrt(TD))
    rf = cagr(cash_level.reindex(lv.index).ffill())
    down = r[r < 0].std(ddof=1) * np.sqrt(TD)
    dd = drawdown(lv)
    yr = yearly(lv)
    full = yr[[y for y in yr.index if 2022 <= y <= 2025]]
    return {"start": lv.index[0].date(), "end": lv.index[-1].date(),
            "cagr": c, "vol": vol,
            "sharpe": (c - rf) / vol if vol else np.nan,
            "sortino": (c - rf) / float(down) if down else np.nan,
            **dd,
            "calmar": c / abs(dd["max_dd"]) if dd["max_dd"] else np.nan,
            "best_year": float(full.max()) if len(full) else np.nan,
            "worst_year": float(full.min()) if len(full) else np.nan}


def relative(level: pd.Series, ref: pd.Series) -> dict:
    j = pd.concat([level.rename("s"), ref.rename("b")], axis=1).dropna()
    if len(j) < 30:
        return {}
    j = j / j.iloc[0]
    r = j.pct_change().dropna()
    act = r["s"] - r["b"]
    te = float(act.std(ddof=1) * np.sqrt(TD))
    m = j.resample("M").last()
    m = pd.concat([j.iloc[[0]], m]).pct_change().dropna()
    up, dn = m["b"] > 0, m["b"] < 0
    roll = (j / j.shift(TD)).dropna()
    return {"rel_start": j.index[0].date(),
            "excess_cagr": cagr(j["s"]) - cagr(j["b"]),
            "tracking_error": te,
            "info_ratio": float(act.mean() * TD / te) if te else np.nan,
            "beta": float(np.cov(r["s"], r["b"])[0, 1] / r["b"].var(ddof=1)),
            "correlation": float(r["s"].corr(r["b"])),
            "up_capture": float(m.loc[up, "s"].mean() / m.loc[up, "b"].mean()) if up.any() else np.nan,
            "down_capture": float(m.loc[dn, "s"].mean() / m.loc[dn, "b"].mean()) if dn.any() else np.nan,
            "hit_rate_12m": float((roll["s"] > roll["b"]).mean()) if len(roll) else np.nan}
