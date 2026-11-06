# -*- coding: utf-8 -*-
"""
Replication of the desk's supertrend, ported from
`wm-AA-smallcase-rebalance-automation/Python_Scripts/ST.py`.

It is not a textbook ATR supertrend. Two differences matter:

  * the volatility term is a **linearly weighted** mean of weekly true range
    over `days_to_consider` bars (weights 1..n normalised), not a Wilder or
    exponential ATR - the column is named EMA_TR but the code computes
    `sum(weight * TR)`;
  * the band centre is the current bar's **(high + low) / 2**, not its close.

Bands and the trend ratchet then follow the standard construction:

    BUB = AHML + mul * wATR          FUB = BUB if (BUB < pFUB or pClose > pFUB) else pFUB
    BLB = AHML - mul * wATR          FLB = BLB if (BLB > pFLB or pClose < pFLB) else pFLB

with ST latching to FUB in a downtrend and FLB in an uptrend, so
`ST == FUB` reads as defensive and `ST == FLB` as equity.

Parameters are not guessed: `mul` is recovered exactly from the published
files as (BUB - BLB) / (2 * EMA_TR) = 2.0000 for every index, and weekly
`days_to_consider` is 5 per ST.py's own default.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

MUL = 2.0
DAYS_TO_CONSIDER = 5

INDICES_OHLCV = Path(
    r"G:\.shortcut-targets-by-id\0B7f_UMMZHM_JNXljMVVXY2VPcHM\Investment Research_N"
    r"\Shubham_Shreshtha\Friday Rebalance Automation\Data\indices_ohlcv.xlsx"
)


def linear_weights(n: int) -> np.ndarray:
    """ST.py getLinearWeighing: 1..n normalised, so the newest bar weighs most."""
    x = np.arange(1, n + 1, dtype=float)
    return x / x.sum()


def to_weekly(daily: pd.DataFrame) -> pd.DataFrame:
    """
    Aggregate daily OHLCV into weekly bars the way ST.py's setData does:
    high = max, low = min, close = last, volume = sum, labelled by the last
    trading day of the week.
    """
    d = daily.copy()
    d.index = pd.to_datetime(d.index)
    d = d.sort_index()
    key = d.index.to_period("W")
    g = d.groupby(key)
    w = pd.DataFrame({
        "high": g["high"].max(),
        "low": g["low"].min(),
        "close": g["close"].last(),
        "volume": g["volume"].sum() if "volume" in d else 0.0,
    })
    w.index = g.apply(lambda x: x.index[-1])
    w.index.name = "date"

    w["HML"] = w["high"] - w["low"]
    w["PClose"] = w["close"].shift()
    w["HMC"] = (w["high"] - w["PClose"]).abs()
    w["LMC"] = (w["low"] - w["PClose"]).abs()
    w["TR"] = w[["HML", "HMC", "LMC"]].max(axis=1)
    w["AHML"] = 0.5 * w["high"] + 0.5 * w["low"]
    return w


def supertrend(weekly: pd.DataFrame, mul: float = MUL,
               days: int = DAYS_TO_CONSIDER) -> pd.DataFrame:
    """
    Weekly supertrend. Returns BUB/BLB/FUB/FLB/ST/wATR and `signal`
    (1 = equity when ST sits on the lower band, 0 = defensive on the upper).

    The first `days` bars have no window and are left NaN, matching ST.py's
    `rebalStartIndex`.
    """
    w = linear_weights(days)
    tr = weekly["TR"].to_numpy(dtype=float)
    ahml = weekly["AHML"].to_numpy(dtype=float)
    close = weekly["close"].to_numpy(dtype=float)
    pclose = weekly["PClose"].to_numpy(dtype=float)
    n = len(weekly)

    watr = np.full(n, np.nan)
    for i in range(days - 1, n):
        seg = tr[i - days + 1: i + 1]
        if np.isnan(seg).any():
            continue
        watr[i] = float((seg * w).sum())

    bub = ahml + mul * watr
    blb = ahml - mul * watr
    fub = np.full(n, np.nan)
    flb = np.full(n, np.nan)
    st = np.full(n, np.nan)

    start = None
    for i in range(n):
        if np.isnan(bub[i]):
            continue
        if start is None:
            start = i
            fub[i], flb[i] = bub[i], blb[i]
            st[i] = fub[i]
            continue
        pf_u, pf_l, p_st = fub[i - 1], flb[i - 1], st[i - 1]
        fub[i] = bub[i] if (bub[i] < pf_u or pclose[i] > pf_u) else pf_u
        flb[i] = blb[i] if (blb[i] > pf_l or pclose[i] < pf_l) else pf_l

        if p_st == pf_u and close[i] <= fub[i]:
            st[i] = fub[i]
        elif p_st == pf_u and close[i] > fub[i]:
            st[i] = flb[i]
        elif p_st == pf_l and close[i] >= flb[i]:
            st[i] = flb[i]
        elif p_st == pf_l and close[i] < fub[i]:
            st[i] = fub[i]
        else:
            st[i] = 0.0

    out = pd.DataFrame(
        {"wATR": watr, "BUB": bub, "BLB": blb, "FUB": fub, "FLB": flb, "ST": st},
        index=weekly.index,
    )
    tol = 1e-9
    on_low = (out["ST"] - out["FLB"]).abs() < tol
    on_up = (out["ST"] - out["FUB"]).abs() < tol
    out["signal"] = np.where(on_low, 1.0, np.where(on_up, 0.0, np.nan))
    return out


def load_index_ohlcv(sheet: str) -> pd.DataFrame:
    d = pd.read_excel(INDICES_OHLCV, sheet_name=sheet)
    d["date"] = pd.to_datetime(d["date"])
    return d.set_index("date").sort_index()


def build(sheet: str) -> pd.DataFrame:
    return supertrend(to_weekly(load_index_ohlcv(sheet)))
