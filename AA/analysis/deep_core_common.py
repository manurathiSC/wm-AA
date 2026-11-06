# -*- coding: utf-8 -*-
"""
Shared inputs for the deep regime study of the pair rule (N100 AND SC100).

Builds, once, continuous whole-history daily NAVs and weights for every
equity leg x rule x sleeve, on the same engine as the published index tests
(`why_n100sc100.run_rs`: weekly decisions, next-session trade, 20.8 bps per
full switch, price-return indices, LBES cash, GOLDBEES gold). Cached to
`evidence/why_n100sc100/deep/core_navs.parquet` and `core_weights.parquet`.

Also: a 10% zig-zag swing finder on Friday closes, used by the episode and
regime scripts.
"""

from __future__ import annotations

import os

import numpy as np
import pandas as pd

from triple_and_test import index_levels
from why_n100sc100 import OUT, calendar, cagr, daily_weight, gold_cash, mdd, run_rs, weekly_signs

DEEP = OUT / "deep"
os.makedirs(DEEP, exist_ok=True)
S0 = pd.Timestamp("2007-07-02")          # first cash price -> first full index test day
S_GOLD = pd.Timestamp("2014-07-07")      # first gold price -> sleeves with gold
IS0 = pd.Timestamp("2021-11-03")         # in-sample starts (rule chosen on 2021-11 -> 2026-08)
OOS_END = pd.Timestamp("2021-10-29")
END = pd.Timestamp("2026-08-21")
LEGS = ["N50", "N100", "MC100", "SC100", "blend"]
OWN = {"N50": "N50", "N100": "N100", "MC100": "MC100", "SC100": "SC100"}
RULES = ["pair", "triple", "sc100", "own", "bh"]
SLEEVES = {"cash": S0, "50/50": S_GOLD, "gold": S_GOLD}


def load():
    cal_all = calendar()
    cal = cal_all[(cal_all >= pd.Timestamp("2004-01-01")) & (cal_all <= END)]
    lv = index_levels(cal)
    gc = gold_cash(cal)
    sg = weekly_signs()
    sg = sg[sg.index <= END]
    r = lv.pct_change()
    r3 = r[["N100", "MC100", "SC100"]]
    r["blend"] = r3.mean(axis=1).where(r3.notna().all(axis=1))
    px = lv.copy()
    px["blend"] = (1 + r["blend"].fillna(0.0)).cumprod().where(r["blend"].notna().cumsum() > 0)
    return cal, px, r, gc, sg


def decisions(sg: pd.DataFrame, leg: str) -> dict:
    d = {"pair": sg["N100"] * sg["SC100"],
         "triple": sg["N100"] * sg["MC100"] * sg["SC100"],
         "sc100": sg["SC100"],
         "bh": pd.Series(1.0, index=sg.index)}
    if leg in OWN:
        d["own"] = sg[OWN[leg]]
    return d


def sleeve_returns(gc: pd.DataFrame, cc: pd.DatetimeIndex, kind: str) -> pd.Series:
    rg, rc = gc["gold"].reindex(cc).pct_change(), gc["cash"].reindex(cc).pct_change()
    s = rc if kind == "cash" else rg if kind == "gold" else 0.5 * rg + 0.5 * rc
    return s.fillna(0.0)


def run_one(cal, r, gc, dec, leg, sleeve, start, cost=20.8):
    cc = cal[(cal >= start) & (cal <= END)]
    d = dec.dropna()
    d = d[d.index >= start - pd.Timedelta(days=7)]
    nav = run_rs(d, r[leg].reindex(cc).fillna(0.0), sleeve_returns(gc, cc, sleeve), cc, cost_bps=cost)
    w = daily_weight(d, cc).reindex(cc).ffill().fillna(1.0)
    return nav / nav.iloc[0], w


def build(force: bool = False):
    pn, pw = DEEP / "core_navs.parquet", DEEP / "core_weights.parquet"
    if pn.exists() and pw.exists() and not force:
        return pd.read_parquet(pn), pd.read_parquet(pw)
    cal, px, r, gc, sg = load()
    navs, ws = {}, {}
    for leg in LEGS:
        for rule, dec in decisions(sg, leg).items():
            for sl, st in SLEEVES.items():
                nav, w = run_one(cal, r, gc, dec, leg, sl, st)
                navs[f"{leg}|{rule}|{sl}"] = nav
                ws[f"{leg}|{rule}|{sl}"] = w
    N, W = pd.DataFrame(navs), pd.DataFrame(ws)
    N.to_parquet(pn)
    W.to_parquet(pw)
    return N, W


def friday(s: pd.Series) -> pd.Series:
    return s.dropna().resample("W-FRI").last().dropna()


def dd(s: pd.Series) -> float:
    s = s.dropna()
    return float((s / s.cummax() - 1).min()) if len(s) else np.nan


def zigzag(p: pd.Series, thr: float = 0.10) -> list[tuple[str, pd.Timestamp]]:
    """Swing pivots on a (weekly) series: a high is confirmed once price falls thr
    below it, a low once price rises thr above it. The last pivot is provisional."""
    p = p.dropna()
    v, idx = p.to_numpy(), p.index
    piv, mode, hi_i, lo_i, ext = [], None, 0, 0, 0
    for i in range(1, len(v)):
        if mode is None:
            if v[i] > v[hi_i]:
                hi_i = i
            if v[i] < v[lo_i]:
                lo_i = i
            if v[i] >= v[lo_i] * (1 + thr):
                piv.append(("L", idx[lo_i])); mode, ext = "up", i
            elif v[i] <= v[hi_i] * (1 - thr):
                piv.append(("H", idx[hi_i])); mode, ext = "down", i
        elif mode == "up":
            if v[i] > v[ext]:
                ext = i
            elif v[i] <= v[ext] * (1 - thr):
                piv.append(("H", idx[ext])); mode, ext = "down", i
        else:
            if v[i] < v[ext]:
                ext = i
            elif v[i] >= v[ext] * (1 + thr):
                piv.append(("L", idx[ext])); mode, ext = "up", i
    if mode:
        piv.append(("H*" if mode == "up" else "L*", idx[ext]))
    return piv


if __name__ == "__main__":
    N, W = build(force=True)
    oos = N.loc[S0:OOS_END]
    # tie-out with the published table: pair on SC100, cash, 2007-07-02 -> 2021-10-29 = 14.4% / -29%
    for c in ["SC100|pair|cash", "SC100|bh|cash", "blend|pair|cash", "N100|pair|cash"]:
        print(c, round(cagr(oos[c]) * 100, 2), round(mdd(oos[c]) * 100, 1))
    print(N.shape, N.index.min(), N.index.max())
