# -*- coding: utf-8 -*-
"""
Shared plumbing for the "robust" deep-dive scripts (deep_robust_*.py).

Everything here is a thin, vectorised re-implementation of the study's own
engine (why_n100sc100.daily_weight / run_rs), checked against it in
`selftest()`:

  * a weekly decision dated Friday R trades at the close of the next session
    and first earns the session after that;
  * daily return = w * r_eq + (1 - w) * r_sl - |dw| * cost;
  * weights before the first decision are 1.0.

Sleeves are built leg by leg (cash, gold, or 0.5 x each) so gold's missing
pre-2014 prices never touch the cash return.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd

import why_n100sc100 as W
import triple_and_test as T

HERE = Path(__file__).resolve().parent
OUT = HERE / "evidence" / "why_n100sc100" / "deep"
os.makedirs(OUT, exist_ok=True)

CUT = pd.Timestamp("2026-08-21")
FULL_START = pd.Timestamp("2007-07-02")
GOLD_START = pd.Timestamp("2014-07-07")
OOS_END = pd.Timestamp("2021-10-29")
IS_START = pd.Timestamp("2021-11-03")
COST = 20.8
SEED = 20260925

CORE_LEGS = ["SC100", "blend", "N100", "MC100", "N50"]
OWN = {"N50": "N50", "N100": "N100", "MC100": "MC100", "SC100": "SC100",
       "MC150": "MC150", "SC250": "SC250", "Micro250": "Micro250"}


# ── data ───────────────────────────────────────────────────────────────────
def load():
    cal = W.calendar()
    cal = cal[cal <= CUT]
    sg = W.weekly_signs()
    sg = sg[sg.index <= CUT]
    lv = T.index_levels(cal)
    gc = W.gold_cash(cal)
    return cal, sg, lv, gc


def equity_returns(lv: pd.DataFrame) -> pd.DataFrame:
    """Daily price returns of every leg on the full calendar (NaN before a leg starts)."""
    r = lv.pct_change(fill_method=None)
    r["blend"] = (r["N100"] + r["MC100"] + r["SC100"]) / 3
    return r


def sleeve_returns(gc: pd.DataFrame, sleeve: str) -> pd.Series:
    """Explicit legs: cash, gold, or 50/50. NaN where a needed leg has no price."""
    rc = gc["cash"].pct_change(fill_method=None)
    rg = gc["gold"].pct_change(fill_method=None)
    if sleeve == "cash":
        return rc
    if sleeve == "gold":
        return rg
    if sleeve in ("5050", "gold+cash"):
        return 0.5 * rg + 0.5 * rc
    raise ValueError(sleeve)


def rule_dec(sg: pd.DataFrame, rule: str, leg: str | None = None) -> pd.Series:
    """Weekly 1/0 decisions on the review grid (NaN where an input is missing)."""
    s = sg
    if rule == "bh":
        return pd.Series(1.0, index=s.index)
    if rule == "pair":
        return s["N100"] * s["SC100"]
    if rule == "triple":
        return s["N100"] * s["MC100"] * s["SC100"]
    if rule == "sc100":
        return s["SC100"]
    if rule == "own":
        return s[OWN[leg]]
    if rule == "n50_and_sc100":
        return s["N50"] * s["SC100"]
    if rule == "n100_and_sc250":
        return s["N100"] * s["SC250"]
    if rule == "mc100_and_sc100":
        return s["MC100"] * s["SC100"]
    if rule == "n100_and_mc100":
        return s["N100"] * s["MC100"]
    if rule == "n100_or_sc100":
        o = ((s["N100"] + s["SC100"]) > 0).astype(float)
        return o.where(s["N100"].notna() & s["SC100"].notna())
    if rule == "n100":
        return s["N100"]
    raise ValueError(rule)


# ── engine ─────────────────────────────────────────────────────────────────
def weight_fast(dec: pd.Series, c: pd.DatetimeIndex) -> np.ndarray:
    """Vectorised why_n100sc100.daily_weight, then ffill and fillna(1.0) as run_rs does."""
    d = dec.dropna()
    j = c.searchsorted(d.index.values, side="right") + 1
    ok = j < len(c)
    s = pd.Series(d.values[ok], index=j[ok])
    s = s[~s.index.duplicated(keep="last")]
    w = np.full(len(c), np.nan)
    w[s.index.values] = s.values
    w = pd.Series(w).ffill().fillna(1.0).to_numpy()
    return w


def nav_fast(dec, r_eq: np.ndarray, r_sl: np.ndarray, c: pd.DatetimeIndex, cost_bps=COST):
    """Same arithmetic as why_n100sc100.run_rs; r_eq / r_sl already aligned to c and NaN-free."""
    w = weight_fast(dec, c)
    r = w * r_eq + (1 - w) * r_sl
    sw = np.abs(np.diff(w, prepend=w[0]))
    sw[0] = 0.0
    r = r - sw * cost_bps / 1e4
    return np.cumprod(1 + r), w


class Window:
    """A fixed window [a, b] with its calendar, leg returns and sleeve returns ready."""

    def __init__(self, cal, sg, lv, gc, a, b, sleeve="cash", legs=None, need=("N100", "SC100")):
        self.a, self.b = pd.Timestamp(a), pd.Timestamp(b)
        c = cal[(cal >= self.a) & (cal <= self.b)]
        self.sg = sg.loc[(sg.index >= self.a - pd.Timedelta(days=7)) & (sg.index <= self.b)]
        req = self.sg[list(need)].dropna()
        first = req.index[0] + pd.Timedelta(days=3)
        c = c[c >= first]
        self.c = c
        rr = equity_returns(lv)
        legs = legs or CORE_LEGS
        self.req = {}
        for k in legs:
            x = rr[k].reindex(c)
            x.iloc[0] = 0.0
            self.req[k] = x.fillna(0.0).to_numpy()
        rs = sleeve_returns(gc, sleeve).reindex(c)
        rs.iloc[0] = 0.0
        self.rsl = rs.fillna(0.0).to_numpy()
        self.sleeve = sleeve

    def nav(self, dec: pd.Series, leg: str, cost_bps=COST) -> pd.Series:
        d = dec.loc[(dec.index >= self.a - pd.Timedelta(days=7)) & (dec.index <= self.b)]
        n, w = nav_fast(d, self.req[leg], self.rsl, self.c, cost_bps)
        return pd.Series(n, index=self.c)

    def nav_w(self, dec: pd.Series, leg: str, cost_bps=COST):
        d = dec.loc[(dec.index >= self.a - pd.Timedelta(days=7)) & (dec.index <= self.b)]
        n, w = nav_fast(d, self.req[leg], self.rsl, self.c, cost_bps)
        return pd.Series(n, index=self.c), pd.Series(w, index=self.c)


# ── statistics ─────────────────────────────────────────────────────────────
def cagr(nav: pd.Series) -> float:
    yrs = (nav.index[-1] - nav.index[0]).days / 365.25
    return float((nav.iloc[-1] / nav.iloc[0]) ** (1 / yrs) - 1)


def mdd(x) -> float:
    x = np.asarray(x, dtype=float)
    return float((x / np.maximum.accumulate(x) - 1).min())


def friday(nav: pd.Series) -> pd.Series:
    return nav.resample("W-FRI").last().dropna()


def mdd_fri(nav: pd.Series) -> float:
    return mdd(friday(nav).to_numpy())


def calmar(cg: float, dd: float) -> float:
    return cg / abs(dd) if dd < 0 else (np.inf if cg > 0 else np.nan)


def stats(nav: pd.Series, w: pd.Series | None = None, dec: pd.Series | None = None) -> dict:
    cg, dd, ddf = cagr(nav), mdd(nav.to_numpy()), mdd_fri(nav)
    o = {"cagr": cg, "max_dd_daily": dd, "max_dd_friday": ddf, "calmar_daily": calmar(cg, dd),
         "calmar_friday": calmar(cg, ddf), "vol": float(nav.pct_change().std() * np.sqrt(252))}
    if w is not None:
        o["time_in_equity"] = float(w.mean())
    if dec is not None:
        d = dec.dropna()
        o["switches"] = int((d.diff().abs() > 0).sum())
    return o


def selftest(cal, sg, lv, gc) -> pd.DataFrame:
    """Fast engine vs why_n100sc100.run_rs, and vs triple_index_results.csv."""
    rows = []
    ref = pd.read_csv(HERE / "evidence" / "why_n100sc100" / "triple_index_results.csv")
    ref = ref[ref["period"].isin(["2007-21, cash", "2014-21, gold+cash"])]
    name = {"SC100": "SC100", "blend": "blend N100/MC100/SC100", "N100": "N100", "MC100": "MC100", "N50": "N50"}
    rname = {"pair": "N100 AND SC100", "bh": "buy & hold", "sc100": "SC100 only",
             "triple": "N100 AND MC100 AND SC100", "own": "own signal"}
    for per, a, b, sl in (("2007-21, cash", FULL_START, OOS_END, "cash"),
                          ("2014-21, gold+cash", GOLD_START, OOS_END, "5050")):
        win = Window(cal, sg, lv, gc, a, b, sl, need=("N100", "MC100", "SC100"))
        for leg in CORE_LEGS:
            for rn in ("pair", "bh", "sc100", "triple", "own"):
                if rn == "own" and leg == "blend":
                    continue
                dec = rule_dec(sg, rn, leg)
                n = win.nav(dec, leg)
                # slow engine on the same inputs
                d = dec.loc[(dec.index >= win.a - pd.Timedelta(days=7)) & (dec.index <= win.b)].dropna()
                slow = W.run_rs(d, pd.Series(win.req[leg], index=win.c), pd.Series(win.rsl, index=win.c), win.c)
                r = ref[(ref.period == per) & (ref.equity == name[leg]) & (ref.rule == rname[rn])]
                rows.append({"period": per, "leg": leg, "rule": rn, "cagr_fast": cagr(n),
                             "cagr_run_rs": W.cagr(slow), "max_abs_nav_diff": float(np.abs(n.values - slow.values).max()),
                             "cagr_reference_csv": float(r["cagr"].iloc[0]) if len(r) else np.nan,
                             "mdd_fast": mdd(n.values), "mdd_reference_csv": float(r["max_dd"].iloc[0]) if len(r) else np.nan})
    return pd.DataFrame(rows)
