# -*- coding: utf-8 -*-
"""
Shared inputs for the "mechanism" deep-dive (deep_mechanism_*.py).

Everything comes from the existing helpers; nothing is re-derived:
  - calendar, weekly production SIGNs, daily weights, the return-space engine
    and the gold/cash series from why_n100sc100;
  - index closes (incl. Micro250) from triple_and_test.index_levels.
Every series is cut at 2026-08-21.

Also provides:
  - sim(): the run_rs engine, returning the daily pieces (weight, equity
    return, sleeve return, cost) so returns can be decomposed exactly. It is
    asserted to reproduce run_rs to machine precision.
  - zigzag(): swing peaks/troughs on daily closes (hindsight).
  - dd_episodes(): peak -> trough -> recovery drawdown episodes (hindsight).
"""

from __future__ import annotations

import os

import numpy as np
import pandas as pd

import why_n100sc100 as W
import triple_and_test as T

END = pd.Timestamp("2026-08-21")
OOS_START, OOS_END = pd.Timestamp("2007-07-02"), pd.Timestamp("2021-10-29")
IS_START, IS_END = pd.Timestamp("2021-11-03"), END
GOLD_START = pd.Timestamp("2014-07-07")
SIG_START = pd.Timestamp("2006-01-06")            # first N100 SIGN
COST = W.COST                                      # 20.8 bps per full switch
OUT = W.OUT / "deep"
os.makedirs(OUT, exist_ok=True)

OWN = {"N50": "N50", "N100": "N100", "MC100": "MC100", "SC100": "SC100",
       "MC150": "MC150", "SC250": "SC250", "Micro250": "Micro250"}


def load():
    cal = W.calendar()
    cal = cal[cal <= END]
    sg = W.weekly_signs()
    sg = sg[sg.index <= END]
    lv = T.index_levels(cal)
    lv = lv[lv.index <= END]
    gc = W.gold_cash(cal)
    gc = gc[gc.index <= END]
    return cal, sg, lv, gc


def decisions(s: pd.DataFrame, rule: str, own: str | None = None) -> pd.Series:
    if rule == "bh":
        return pd.Series(1.0, index=s.index)
    if rule == "pair":
        return s["N100"] * s["SC100"]
    if rule == "triple":
        return s["N100"] * s["MC100"] * s["SC100"]
    if rule == "sc100":
        return s["SC100"]
    if rule == "n100":
        return s["N100"]
    if rule == "own":
        return s[own]
    raise KeyError(rule)


def sleeve_returns(gc: pd.DataFrame, c: pd.DatetimeIndex, kind: str) -> pd.Series:
    """Pick the legs explicitly; never 0 x NaN-gold."""
    rc = gc["cash"].reindex(c).pct_change()
    if kind == "cash":
        r = rc
    elif kind == "gold":
        r = gc["gold"].reindex(c).pct_change()
    elif kind == "gold+cash":
        r = 0.5 * gc["gold"].reindex(c).pct_change() + 0.5 * rc
    else:
        raise KeyError(kind)
    return r.fillna(0.0)


def equity_returns(lv: pd.DataFrame, c: pd.DatetimeIndex) -> dict:
    r = {k: lv[k].reindex(c).pct_change() for k in lv.columns}
    r["blend"] = (r["N100"] + r["MC100"] + r["SC100"]) / 3
    return r


def blend_level(lv: pd.DataFrame) -> pd.Series:
    """Equal-weight daily-rebalanced N100/MC100/SC100 level (from 2005-11-30)."""
    r = (lv["N100"].pct_change() + lv["MC100"].pct_change() + lv["SC100"].pct_change()) / 3
    first = lv[["N100", "MC100", "SC100"]].dropna().index[0]
    r = r[r.index >= first].fillna(0.0)
    r.iloc[0] = 0.0
    return (1 + r).cumprod()


def sim(dec: pd.Series, r_eq: pd.Series, r_sl: pd.Series, c: pd.DatetimeIndex,
        cost_bps: float = COST) -> pd.DataFrame:
    """run_rs with its daily pieces. Columns: w, r_eq, r_sl, cost, gross, net, nav."""
    r_eq = r_eq.reindex(c).fillna(0.0)
    r_sl = r_sl.reindex(c).fillna(0.0)
    w = W.daily_weight(dec, c).reindex(c).ffill().fillna(1.0)
    gross = w * r_eq + (1 - w) * r_sl
    cost = w.diff().abs().fillna(0.0) * cost_bps / 1e4
    net = (gross - cost).fillna(0.0)
    nav = (1 + net).cumprod()
    ref = W.run_rs(dec, r_eq, r_sl, c, cost_bps=cost_bps)
    assert np.allclose(nav.to_numpy(), ref.reindex(c).to_numpy(), rtol=1e-12, atol=1e-12), "engine mismatch"
    return pd.DataFrame({"w": w, "r_eq": r_eq, "r_sl": r_sl, "cost": cost, "gross": gross,
                         "net": net, "nav": nav})


def window(cal, a, b):
    return cal[(cal >= pd.Timestamp(a)) & (cal <= pd.Timestamp(b))]


def sig_window(sg, a, b, cols):
    s = sg.loc[(sg.index >= pd.Timestamp(a) - pd.Timedelta(days=7)) & (sg.index <= pd.Timestamp(b)), cols]
    return s.dropna()


def years(c: pd.DatetimeIndex) -> float:
    return (c[-1] - c[0]).days / 365.25


def cagr_nav(nav: pd.Series) -> float:
    return W.cagr(nav)


def mdd_daily(nav: pd.Series) -> float:
    return W.mdd(nav)


def mdd_weekly(nav: pd.Series) -> float:
    wk = nav.dropna().resample("W-FRI").last().dropna()
    return float((wk / wk.cummax() - 1).min())


def trade_session(cal: pd.DatetimeIndex, r: pd.Timestamp):
    """Session at whose close a decision dated r trades (next session after r)."""
    j = cal.searchsorted(r, side="right")
    return cal[j] if j < len(cal) else None


def zigzag(px: pd.Series, thr: float = 0.20, up: float | None = None) -> pd.DataFrame:
    """
    Swing points on closes (hindsight). A peak is confirmed once price falls
    thr below it; a trough once price rises `up` (default thr) above it.
    Returns alternating rows: date, level, kind. The last, unconfirmed
    extreme is returned with confirmed=False.
    """
    up = thr if up is None else up
    p = px.dropna()
    pts = []
    mode = None
    ext_d, ext_v = p.index[0], p.iloc[0]
    lo_d, lo_v, hi_d, hi_v = ext_d, ext_v, ext_d, ext_v
    for d, v in p.items():
        if mode is None:
            if v > hi_v:
                hi_d, hi_v = d, v
            if v < lo_v:
                lo_d, lo_v = d, v
            if v <= hi_v * (1 - thr):
                pts.append((hi_d, hi_v, "peak", True))
                mode, ext_d, ext_v = "down", d, v
            elif v >= lo_v * (1 + up):
                pts.append((lo_d, lo_v, "trough", True))
                mode, ext_d, ext_v = "up", d, v
            continue
        if mode == "up":
            if v > ext_v:
                ext_d, ext_v = d, v
            elif v <= ext_v * (1 - thr):
                pts.append((ext_d, ext_v, "peak", True))
                mode, ext_d, ext_v = "down", d, v
        else:
            if v < ext_v:
                ext_d, ext_v = d, v
            elif v >= ext_v * (1 + up):
                pts.append((ext_d, ext_v, "trough", True))
                mode, ext_d, ext_v = "up", d, v
    pts.append((ext_d, ext_v, "peak" if mode == "up" else "trough", False))
    return pd.DataFrame(pts, columns=["date", "level", "kind", "confirmed"])


def dd_episodes(px: pd.Series, depth: float = 0.20) -> pd.DataFrame:
    """Peak -> trough -> recovery episodes whose depth is >= depth (hindsight)."""
    p = px.dropna()
    rows = []
    peak_d, peak_v = p.index[0], p.iloc[0]
    tr_d, tr_v = peak_d, peak_v
    for d, v in p.items():
        if v >= peak_v:
            if tr_v / peak_v - 1 <= -depth:
                rows.append((peak_d, peak_v, tr_d, tr_v, d, True))
            peak_d, peak_v, tr_d, tr_v = d, v, d, v
        elif v < tr_v:
            tr_d, tr_v = d, v
    if tr_v / peak_v - 1 <= -depth:
        rows.append((peak_d, peak_v, tr_d, tr_v, p.index[-1], False))
    e = pd.DataFrame(rows, columns=["peak", "peak_level", "trough", "trough_level", "recovery", "recovered"])
    e["depth"] = e["trough_level"] / e["peak_level"] - 1
    return e
