# -*- coding: utf-8 -*-
"""
Shared helpers for the "sleeve" deep-dive (deep_sleeve_analysis.py).

Everything reuses the production pieces in why_n100sc100.py: the NSE calendar,
the weekly production SIGN, index closes, GOLDBEES / LBES, the weekly-decision
-> daily-weight mapping, and the return-space engine run_rs (20.8 bps per full
switch). Windows are built exactly as triple_and_test.py builds them, so the
period CAGRs reproduce evidence/why_n100sc100/triple_index_results.csv.
"""

from __future__ import annotations

import os

import numpy as np
import pandas as pd

from why_n100sc100 import (COST, OUT, cagr, calendar, daily_weight, gold_cash, index_closes, mdd,
                           run_rs, weekly_signs)

END = pd.Timestamp("2026-08-21")
W14 = pd.Timestamp("2014-07-07")
OOS_END = pd.Timestamp("2021-10-29")
IS_START = pd.Timestamp("2021-11-03")
W07 = pd.Timestamp("2007-07-02")
PERIODS = {"2014-21 OOS": (W14, OOS_END),
           "2021-26 IS": (IS_START, END),
           "2014-26 full": (W14, END)}
DEEP = OUT / "deep"
os.makedirs(DEEP, exist_ok=True)

EQUITY_LEGS = ["N50", "N100", "MC100", "SC100", "blend"]
OWN = {"N50": "N50", "N100": "N100", "MC100": "MC100", "SC100": "SC100"}

# Calendar-year segments. 2021 is split at the in-sample boundary: the OOS part
# ends 2021-10-29 and the in-sample part is measured from the 2021-11-03 close
# (the first value of the in-sample book curves). Returns on 2021-11-01..03
# fall in neither half.
SEGMENTS = ([(str(y), "OOS", pd.Timestamp(f"{y}-01-01"), pd.Timestamp(f"{y}-12-31"))
             for y in range(2014, 2021)]
            + [("2021 Jan-Oct", "OOS", pd.Timestamp("2021-01-01"), OOS_END),
               ("2021 Nov-Dec", "IS", pd.Timestamp("2021-11-04"), pd.Timestamp("2021-12-31"))]
            + [(str(y), "IS", pd.Timestamp(f"{y}-01-01"), pd.Timestamp(f"{y}-12-31"))
               for y in range(2022, 2026)]
            + [("2026 to Aug-21", "IS", pd.Timestamp("2026-01-01"), END)])


def load():
    cal = calendar()
    cal = cal[cal <= END]
    sg = weekly_signs()
    sg = sg[sg.index <= END]
    lv = index_closes(cal)
    gc = gold_cash(cal)
    return cal, sg, lv, gc


def window(cal, sg, a, b, need=("N100", "MC100", "SC100")):
    """Sessions and decisions for a window, as triple_and_test.py builds them."""
    c = cal[(cal >= a) & (cal <= b)]
    s = sg.loc[(sg.index >= a - pd.Timedelta(days=7)) & (sg.index <= b)]
    ss = s[list(need)].dropna()
    first = max(c[0], ss.index[0] + pd.Timedelta(days=3))
    return c[c >= first], ss


def rules(ss: pd.DataFrame, own: str | None) -> dict:
    out = {"pair": ss["N100"] * ss["SC100"],
           "sc100": ss["SC100"],
           "bh": pd.Series(1.0, index=ss.index)}
    if own is not None and own in ss:
        out["own"] = ss[own]
    return out


def equity_returns(lv: pd.DataFrame, cc) -> dict:
    r = {k: lv[k].reindex(cc).pct_change() for k in ("N50", "N100", "MC100", "SC100")}
    r["blend"] = (r["N100"] + r["MC100"] + r["SC100"]) / 3
    return {k: v.fillna(0.0) for k, v in r.items()}


def sleeve_returns(gc: pd.DataFrame, cc) -> dict:
    """Daily sleeve returns; legs picked explicitly (no 0 x NaN gold)."""
    rg = gc["gold"].reindex(cc).pct_change()
    rc = gc["cash"].reindex(cc).pct_change()
    return {"cash": rc.fillna(0.0),
            "5050": (0.5 * rg + 0.5 * rc).fillna(0.0),
            "gold": rg.fillna(0.0)}


def weight(dec: pd.Series, cc) -> pd.Series:
    """The weight run_rs uses: equity weight earning each session's return."""
    return daily_weight(dec, cc).reindex(cc).ffill().fillna(1.0)


def drift_sleeve(w: pd.Series, gc: pd.DataFrame, cc, gold_share: float = 0.5) -> pd.Series:
    """
    Sleeve return when the sleeve is set to gold_share/1-gold_share at each
    entry into the sleeve (the close of the session before the first w == 0
    session) and then left to drift until exit.
    """
    g = gc["gold"].reindex(cc).ffill().to_numpy()
    c = gc["cash"].reindex(cc).ffill().to_numpy()
    wz = (w.reindex(cc).to_numpy() == 0)
    r = np.zeros(len(cc))
    i, n = 0, len(cc)
    while i < n:
        if not wz[i]:
            i += 1
            continue
        j = i
        while j + 1 < n and wz[j + 1]:
            j += 1
        a = max(i - 1, 0)                     # anchor: the close the sleeve is bought at
        val = gold_share * g[a:j + 1] / g[a] + (1 - gold_share) * c[a:j + 1] / c[a]
        r[a + 1:j + 1] = val[1:] / val[:-1] - 1
        i = j + 1
    return pd.Series(np.nan_to_num(r), index=cc)


def fri(nav: pd.Series) -> pd.Series:
    """Friday closes (resample W-FRI last), with the starting value kept."""
    n = nav.dropna()
    return pd.concat([n.iloc[:1], n.resample("W-FRI").last().dropna()])


def mdd_fri(nav: pd.Series) -> float:
    return mdd(fri(nav))


def seg_slice(nav: pd.Series, a: pd.Timestamp, e: pd.Timestamp) -> pd.Series | None:
    """NAV from the last close before a (or the first close, if none) to e."""
    n = nav.dropna()
    before = n.index[n.index < a]
    ref = before[-1] if len(before) else (n.index[n.index >= a][0] if (n.index >= a).any() else None)
    if ref is None or ref > e:
        return None
    s = n.loc[ref:e]
    return s if len(s) > 1 else None


def seg_stats(nav: pd.Series, a, e) -> dict:
    s = seg_slice(nav, a, e)
    if s is None:
        return {"ret": np.nan, "dd_daily": np.nan, "dd_fri": np.nan}
    return {"ret": float(s.iloc[-1] / s.iloc[0] - 1), "dd_daily": mdd(s), "dd_fri": mdd_fri(s)}


def spells(w: pd.Series) -> list[tuple[int, int]]:
    """(first, last) positions of runs with w == 0."""
    z = (w.to_numpy() == 0)
    out, i, n = [], 0, len(z)
    while i < n:
        if z[i]:
            j = i
            while j + 1 < n and z[j + 1]:
                j += 1
            out.append((i, j))
            i = j + 1
        else:
            i += 1
    return out


__all__ = ["COST", "DEEP", "END", "EQUITY_LEGS", "IS_START", "OOS_END", "OWN", "PERIODS", "SEGMENTS", "W07",
           "W14", "cagr", "drift_sleeve", "equity_returns", "fri", "load", "mdd", "mdd_fri", "rules", "run_rs",
           "seg_stats", "sleeve_returns", "spells", "weight", "window"]
