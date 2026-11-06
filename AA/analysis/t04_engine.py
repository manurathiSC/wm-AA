# -*- coding: utf-8 -*-
"""T04 engine: stock-level indicator filters during the three-index SELL regime, SCMO_0003, with a selection-shuffle null.

Standalone: reads only raw files, imports nothing from other AA analysis modules (T03's engine included).
Pre-registration: tests/T04/T04.md sections 1-3 (frozen; `python tests/T04/check_prereg.py`). Every convention below is the one
written in section 3; the few places the engine had to read the text are in READINGS and are written to audit.json.

    python analysis/t04_engine.py [--run NAME] [--draws N] [--quick] [--workers K]      (from AA/)

Writes tests/T04/evidence/<run>/ (see tests/T04/T04.md): inputs.csv, decisions.csv, indicators.csv, selections.csv, trades.csv,
daily_nav.csv, stats.csv, draws.csv, g_engine.csv, audit.json.

Trade rule (one function, `trade`): at a trade session t, V = value of all holdings at the fill prices (stocks OHLC4, GOLDBEES
de-spiked OHLC4, cash at its level). Target values: stock i to x_i * V; GOLDBEES and cash to (1 - sum x) * V * share. traded =
sum |target - held| over every line; cost = traded * cost_bps / 2 / 1e4; every target is scaled by (V - cost) / V.
A trade happens at an event session (the session after a decision, or a session where a new basket takes effect) if and only if
the target stock-weight vector x(t) differs from the last target.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
import warnings
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
sys.dont_write_bytecode = True
AA = Path(__file__).resolve().parents[1]
HD = AA / "Historical Data"
HM = AA / "data" / "holdings_matrix"
T04 = AA / "tests" / "T04"
T03 = AA / "tests" / "T03"
PARENT = "SCMO_0003"
END = pd.Timestamp("2026-11-04")
V4_END = pd.Timestamp("2026-10-22")       # D17's last date: the G0 scope
BAR_CUTOFF = pd.Timestamp("2019-01-02")   # from here on only calendar sessions are read as stock bars (F-AA-D15)
LIVE_START = pd.Timestamp("2021-11-01")
LIQ_FROM = pd.Timestamp("2024-01-24")
COSTS = (0.0, 20.8, 50.0)
PRIMARY = 20.8
N_DRAWS = 2000
DESPIKE_TOL = 0.005
IND = ["I1", "I2", "I3", "I4", "I5"]
IND_NAME = {"I1": "EMA50", "I2": "EMA200", "I3": "SMA50", "I4": "SMA200", "I5": "weekly SuperTrend"}
STALE_DAYS = 7
ST_MUL, ST_DAYS = 2.0, 5
MCX_END = pd.Timestamp("2026-09-28")

READINGS = {
    "E1": "calendar = D17's dates 2019-01-02 -> 2026-10-22, then the D18 sessions after it up to 2026-11-04",
    "E2": "stock bars used for indicators: every D18 bar up to 2019-01-02, after that only bars on calendar sessions (F-AA-D15)",
    "E3": "indicator tables are computed at the decision dates and at the live window's first date only; for a stock whose weekly candle "
          "has a bar after the query date the supertrend is recomputed on bars up to the query date (the live first date, a Monday)",
    "E4": "I5 sign BUY iff ST sits on the final lower band (|ST-FLB|<1e-9); NaN or neither band = not computable = excluded",
    "E5": "n and k of a decision are measured on the basket in force at its trade session (at the decision session for the last decision)",
    "E6": "the null draws one uniform per stock per decision: the k_j(b) smallest of u[j] within basket b are kept (uniform k-subset)",
    "E7": "R5 = per draw_id the best of the five indicators' draws of that id (the plan's 'shared permutation seed' read as 'same draw id')",
    "E8": "initial position: basket at T0 as drifted since its availableDate scaled to 1 at T0's close; stocks outside the T0 kept set are "
          "sold at T0's close into the sleeve at no cost; BUY = whole basket (sleeve exactly 0)",
    "E9": "basket weights normalised to sum 1 over the whole basket; kept stocks keep their normalised weights",
    "E10": "constant mix: stock share f = mean over decisions of sum of kept weights (BUY = 1), rebalanced at the next session of every "
           "decision (T0's included) and at every basket change; initial stock holding = drifted basket scaled by f",
    "E11": "full AA switch comparator = this engine with k = 0 on every SELL decision (T03's rule on this window)",
}


def sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


# ── raw inputs ────────────────────────────────────────────────────────────────
_RAW: dict = {}


def raw_parent() -> dict:
    if _RAW:
        return _RAW
    p = PARENT
    wm = pd.read_csv(HM / f"{p}_holding_weight_matrix.csv", index_col=0)
    wm.index = pd.to_datetime(wm.index)
    src = pd.read_csv(HM / f"{p}_holding_weight_sources.csv")
    src["rebalance_date"] = pd.to_datetime(src["rebalance_date"])
    skipped = set(src.loc[src["source"] == "csv_only_skipped", "rebalance_date"])
    wm = wm[~wm.index.isin(skipped)]
    wm = wm.div(wm.sum(axis=1), axis=0)
    stocks = list(wm.columns)
    o = pd.read_csv(HM / f"{p}_ohlc.csv", parse_dates=["date"]).drop_duplicates(["date", "stock"])
    cor = pd.read_csv(HM / "price_corrections.csv", parse_dates=["ex_date"])
    for r in cor.itertuples():
        if p in r.applies_to.split(";") and r.stock in stocks:
            m = (o["stock"] == r.stock) & (o["date"] < r.ex_date)
            for f in ("open", "high", "low", "close"):
                o.loc[m, f] *= r.factor
    piv = {f: o.pivot(index="date", columns="stock", values=f).sort_index().reindex(columns=stocks) for f in ("open", "high", "low", "close")}
    raw_close = piv["close"]
    close = raw_close.ffill()
    ohlc4 = ((piv["open"] + piv["high"] + piv["low"] + piv["close"]) / 4).fillna(raw_close)
    n = pd.read_csv(HD / "parent_nav_2026-10-22" / f"{p}.csv")
    pub = pd.Series(n["index"].values, index=pd.to_datetime(n["_id.date"], format="%Y/%m/%d")).sort_index()
    d18_dates = pd.DatetimeIndex(sorted(o["date"].unique()))
    _RAW.update(W=wm, stocks=stocks, close=close, raw_close=raw_close, ohlc4=ohlc4, pub=pub, skipped=sorted(skipped), d18_dates=d18_dates,
                hi=piv["high"], lo=piv["low"])
    return _RAW


_COMMON: dict = {}


def common() -> dict:
    if _COMMON:
        return _COMMON
    g = pd.read_parquet(AA / "analysis" / "cache" / "why_gold_ohlc_eikon_extended_2026-11-04.parquet").set_index("date").sort_index()
    g = g[~g.index.duplicated(keep="last")]
    m = pd.read_csv(AA / "analysis" / "evidence" / "final_strategy" / "mauc1" / "mauc1_daily_clean.csv", index_col=0, parse_dates=True)
    m.columns = [c.strip().lower() for c in m.columns]
    rng = ((m["high"] - m["low"]) / m["close"]).reindex(g.index)
    band = rng + DESPIKE_TOL
    lo, hi = g["close"] * (1 - band), g["close"] * (1 + band)
    has = rng.notna()
    o = g["open"].where(~has, g["open"].clip(lower=lo, upper=hi))
    h = g["high"].where(~has, g["high"].clip(upper=hi))
    l_ = g["low"].where(~has, g["low"].clip(lower=lo))
    h = np.maximum(h, np.maximum(o, g["close"]))
    l_ = np.minimum(l_, np.minimum(o, g["close"]))
    gfill = (o + h + l_ + g["close"]) / 4
    lb = pd.read_csv(HD / "LBES_Adjusted_Price_data_extended_2026-11-05.csv")
    lb["date"] = pd.to_datetime(lb["date"], format="%d/%m/%y %H:%M")
    lb = lb.set_index("date")["price"].sort_index()
    lq = pd.read_csv(HD / "liquidEtfFinal_extended_2026-11-05.csv")
    lq["date"] = pd.to_datetime(lq["date"], format="mixed", dayfirst=True)
    lq = lq.set_index("date")["liquid_case"].sort_index()
    ms = {}
    for n in ("Nifty100", "MC100", "SC100"):
        d = pd.read_excel(HD / "extended_2026-10-30" / "Master" / f"Master_{n}.xlsx", parse_dates=["Date"])
        s = d.dropna(subset=["SIGN"]).set_index("Date")["SIGN"].sort_index()
        ms[n] = s[~s.index.duplicated(keep="last")]
    _COMMON.update(gclose=g["close"], gfill=gfill, graw=((g["open"] + g["high"] + g["low"] + g["close"]) / 4), lbes=lb, liq=lq, master=ms, mcx_has=has)
    return _COMMON


def calendar() -> pd.DatetimeIndex:
    r = raw_parent()
    pub = r["pub"].index
    extra = r["d18_dates"][(r["d18_dates"] > pub.max()) & (r["d18_dates"] <= END)]
    return pub.union(extra)


def cash_levels(cal: pd.DatetimeIndex, kind: str = "lbes") -> np.ndarray:
    c = common()
    lb = c["lbes"]
    assert lb.index.max() >= cal[-1], "LBES file ends before the calendar"
    lv = lb.reindex(cal.union(lb.index)).ffill().reindex(cal)
    if kind == "liq":
        q = c["liq"]
        qs = q.reindex(q.index.union(cal)).ffill().reindex(cal)
        out = lv.copy()
        pre = cal[cal < LIQ_FROM]
        if len(pre) and len(pre) < len(cal):
            base = lv.loc[pre[-1]]
            for d in cal[cal >= LIQ_FROM]:
                out.loc[d] = base * qs.loc[d] / qs.loc[pre[-1]]
            lv = out
    return lv.values.astype(float)


class Book:
    """Everything a run needs for one window and cash variant, as plain arrays on the calendar."""

    def __init__(self, start: pd.Timestamp | None = None, end: pd.Timestamp = END, cash: str = "lbes"):
        r = raw_parent()
        c = common()
        cal_all = calendar()
        t0 = cal_all[0] if start is None else cal_all[cal_all.searchsorted(start)]
        cal = cal_all[(cal_all >= t0) & (cal_all <= end)]
        self.cal, self.T, self.t0 = cal, len(cal), t0
        self.stocks, self.N = r["stocks"], len(r["stocks"])
        C = r["close"].reindex(cal)
        P = r["ohlc4"].reindex(cal)
        self.nobar = P.isna().values
        P = P.fillna(C)
        self.C = np.nan_to_num(C.values.astype(float), nan=0.0)
        self.P = np.nan_to_num(P.values.astype(float), nan=0.0)
        self.pub = r["pub"].reindex(cal).values.astype(float)
        union = cal.union(c["gclose"].index)
        gc = c["gclose"].reindex(union).ffill().reindex(cal)
        gf = c["gfill"].reindex(cal).fillna(gc)
        self.g, self.gf = gc.values.astype(float), gf.values.astype(float)
        self.L = cash_levels(cal, cash)
        W = r["W"]
        self.W = W.values.astype(float)
        self.eff = W.index
        bidx = np.searchsorted(cal.values, self.eff.values)
        self.b0 = int(np.flatnonzero(bidx <= 0)[-1])
        self.basket_events = {int(i) for i in bidx if 0 < i < self.T}
        self.basket_at = np.array([int(np.flatnonzero(bidx <= t)[-1]) if (bidx <= t).any() else 0 for t in range(self.T)])
        self.bn = [np.flatnonzero(self.W[b] > 0) for b in range(len(self.W))]
        ax = r["close"].index
        s0 = ax[ax.searchsorted(self.eff[self.b0])]
        w = self.W[self.b0]
        nzs = np.flatnonzero(w > 0)
        p = r["ohlc4"].loc[s0].values[nzs]
        p = np.where(np.isnan(p), r["close"].loc[s0].values[nzs], p)
        u = np.zeros(self.N)
        u[nzs] = w[nzs] / p
        v0 = float((u * np.nan_to_num(r["close"].loc[t0].values)).sum())
        self.u0 = u / v0
        self.initial_basket_switch_session = str(s0.date())

    def decisions(self) -> pd.DataFrame:
        cal = self.cal
        iso = cal.isocalendar()
        last = pd.Series(np.arange(self.T), index=cal).groupby([iso.year.values, iso.week.values]).max().values
        idx = np.array([0] + [int(i) for i in sorted(last) if i > 0])
        ms = common()["master"]
        rows = []
        for j, i in enumerate(idx):
            d = cal[i]
            lab, state = {}, 1
            for n, s in ms.items():
                k = s.index.searchsorted(d, side="right") - 1
                lab[n] = (s.index[k], s.iloc[k])
                state &= int(s.iloc[k] == "BUY")
            ld = max(v[0] for v in lab.values())
            rows.append({"j": j, "decision_date": d.date(), "decision_idx": int(i), "trade_date": (cal[i + 1].date() if i + 1 < self.T else None),
                         **{f"sign_{n}": v[1] for n, v in lab.items()}, **{f"label_{n}": v[0].date() for n, v in lab.items()},
                         "latest_label": ld.date(), "label_age_days": (d - min(v[0] for v in lab.values())).days,
                         "state": int(state), "regime": "BUY" if state else "SELL"})
        return pd.DataFrame(rows)


# ── indicators ────────────────────────────────────────────────────────────────
def st_sign(high: np.ndarray, low: np.ndarray, close: np.ndarray) -> np.ndarray:
    """The desk's weekly supertrend (same algorithm as analysis/supertrend.py, written out): 1 = BUY (ST on the final lower band),
    0 = on the final upper band, NaN = not defined."""
    n = len(close)
    w = np.arange(1, ST_DAYS + 1, dtype=float)
    w = w / w.sum()
    pclose = np.concatenate([[np.nan], close[:-1]])
    hml = high - low
    tr = np.fmax(np.fmax(hml, np.abs(high - pclose)), np.abs(low - pclose))      # fmax skips NaN: the first candle's TR = high - low
    ahml = 0.5 * high + 0.5 * low
    watr = np.full(n, np.nan)
    for i in range(ST_DAYS - 1, n):
        seg = tr[i - ST_DAYS + 1: i + 1]
        if not np.isnan(seg).any():
            watr[i] = float((seg * w).sum())
    bub, blb = ahml + ST_MUL * watr, ahml - ST_MUL * watr
    fub, flb, st = np.full(n, np.nan), np.full(n, np.nan), np.full(n, np.nan)
    started = False
    for i in range(n):
        if np.isnan(bub[i]):
            continue
        if not started:
            started = True
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
    on_low = np.abs(st - flb) < 1e-9
    on_up = np.abs(st - fub) < 1e-9
    return np.where(on_low, 1.0, np.where(on_up, 0.0, np.nan))


def week_ids(dates: np.ndarray) -> np.ndarray:
    iso = pd.DatetimeIndex(dates).isocalendar()
    return (iso.year.values.astype(np.int64) * 100 + iso.week.values.astype(np.int64))


def weekly_candles(dates, h, l, c):
    wk = week_ids(dates)
    starts = np.concatenate([[0], np.flatnonzero(np.diff(wk) != 0) + 1])
    ends = np.concatenate([starts[1:] - 1, [len(wk) - 1]])
    wh = np.maximum.reduceat(h, starts)
    wl = np.minimum.reduceat(l, starts)
    wi = np.cumsum(np.isin(np.arange(len(wk)), starts)) - 1
    return wh, wl, c[ends], dates[ends], wi


def sma(c: np.ndarray, n: int) -> np.ndarray:
    out = np.full(len(c), np.nan)
    if len(c) >= n:
        cs = np.concatenate([[0.0], np.cumsum(c)])
        out[n - 1:] = (cs[n:] - cs[:-n]) / n
    return out


def ema(c: np.ndarray, n: int) -> np.ndarray:
    out = np.full(len(c), np.nan)
    if len(c) >= n:
        k = 2.0 / (n + 1)
        out[n - 1] = c[:n].mean()
        for m in range(n, len(c)):
            out[m] = k * c[m] + (1 - k) * out[m - 1]
    return out


class Indicators:
    """Indicator values and filter flags at the query dates, per stock. Arrays are (Q, N)."""

    def __init__(self, stocks: list, cal: pd.DatetimeIndex, qdates: list):
        r = raw_parent()
        self.stocks, self.qdates = stocks, pd.DatetimeIndex(qdates)
        Q, N = len(qdates), len(stocks)
        self.valid = np.zeros((Q, N), bool)
        self.last_bar = np.full((Q, N), np.datetime64("NaT"), dtype="datetime64[D]")
        self.close = np.full((Q, N), np.nan)
        self.val = {k: np.full((Q, N), np.nan) for k in ("ema50", "ema200", "sma50", "sma200", "st")}
        self.slow_path = 0
        self.bars_after_query = 0          # V2: bars used that are dated after the query date (must stay 0)
        self.not_computable = {i: 0 for i in IND}
        keep = cal.values.astype("datetime64[D]")
        qd = self.qdates.values.astype("datetime64[D]")
        rc, hi, lo = r["raw_close"], r["hi"], r["lo"]
        for s, name in enumerate(stocks):
            c = rc[name].dropna()
            if c.empty:
                continue
            d = c.index.values.astype("datetime64[D]")
            ok = (d <= np.datetime64(BAR_CUTOFF.date())) | np.isin(d, keep)
            c, d = c[ok], d[ok]
            if len(c) == 0:
                continue
            cv = c.values.astype(float)
            hv = hi[name].reindex(c.index).fillna(c).values.astype(float)
            lv = lo[name].reindex(c.index).fillna(c).values.astype(float)
            e50, e200, s50, s200 = ema(cv, 50), ema(cv, 200), sma(cv, 50), sma(cv, 200)
            wh, wl, wc, wlast, wi = weekly_candles(d, hv, lv, cv)
            wsig = st_sign(wh, wl, wc)
            m = np.searchsorted(d, qd, side="right") - 1
            for q in range(Q):
                if m[q] < 0:
                    continue
                mm = int(m[q])
                if (qd[q] - d[mm]).astype(int) > STALE_DAYS:
                    continue
                self.valid[q, s] = True
                self.last_bar[q, s] = d[mm]
                if d[mm] > qd[q]:
                    self.bars_after_query += 1
                self.close[q, s] = cv[mm]
                self.val["ema50"][q, s], self.val["ema200"][q, s] = e50[mm], e200[mm]
                self.val["sma50"][q, s], self.val["sma200"][q, s] = s50[mm], s200[mm]
                wk = wi[mm]
                if wlast[wk] <= qd[q]:
                    self.val["st"][q, s] = wsig[wk]
                else:                       # the candle has bars after the query date: recompute on bars up to it
                    self.slow_path += 1
                    wh2, wl2, wc2, _, _ = weekly_candles(d[:mm + 1], hv[:mm + 1], lv[:mm + 1], cv[:mm + 1])
                    self.val["st"][q, s] = st_sign(wh2, wl2, wc2)[-1]
        v = self.valid
        self.passes = np.stack([
            v & (self.close > self.val["ema50"]),
            v & (self.close > self.val["ema200"]),
            v & (self.close > self.val["sma50"]),
            v & (self.close > self.val["sma200"]),
            v & (self.val["st"] == 1.0),
        ])  # NaN comparisons are False: a stock that cannot be computed fails the filter
        keys = ["ema50", "ema200", "sma50", "sma200", "st"]
        for i, k in enumerate(IND):
            self.not_computable[k] = int((v & np.isnan(self.val[keys[i]])).sum())
        self.qpos = {d: q for q, d in enumerate(self.qdates)}


# ── targets, trades, simulation ───────────────────────────────────────────────
def strategy_provider(ind: Indicators, i: int, dec_dates, bk: Book, none: bool = False, allpass: bool = False):
    """kept(j, b) -> index array of stocks kept on SELL decision j in basket b."""
    rows = [ind.qpos[pd.Timestamp(d)] for d in dec_dates]
    cache: dict = {}

    def prov(j, b):
        key = (j, b)
        if key not in cache:
            if none:
                cache[key] = np.zeros(0, dtype=int)
            else:
                m = ind.passes[i][rows[j]] & (bk.W[b] > 0)
                cache[key] = np.flatnonzero(m)
        return cache[key]
    return prov


def null_provider(bk: Book, u: np.ndarray, kc):
    def prov(j, b):
        k = kc(j, b)
        bn = bk.bn[b]
        if k == 0:
            return np.zeros(0, dtype=int)
        if k >= len(bn):
            return bn
        return bn[np.argsort(u[j, bn], kind="stable")[:k]]
    return prov


def build_events(bk: Book, dec_idx: np.ndarray, state: np.ndarray, prov, every: bool = False, scale: float = 1.0, info: bool = False):
    """Return (init_keep_idx, events). events = list of (t, wvec, j, b, nkept, regime). Only sessions whose target differs from the last
    target are events, unless `every` (the constant mix)."""
    T, J, N = bk.T, len(dec_idx), bk.N
    trs = np.array([int(dec_idx[j]) + 1 for j in range(1, J)], dtype=int)
    sess = set()
    for j in range(0 if every else 1, J):
        t = int(dec_idx[j]) + 1
        if t < T:
            sess.add(t)
    ev_sessions = sorted(sess | bk.basket_events)

    def tvec(j, b):
        w = bk.W[b]
        idx = bk.bn[b] if (state[j] == 1 or prov is None) else prov(j, b)
        v = np.zeros(N)
        v[idx] = w[idx] * scale
        return v, idx
    j0 = 0
    last, init_idx = tvec(j0, bk.b0)
    events = []
    for t in ev_sessions:
        j = int(np.searchsorted(trs, t, side="right"))
        b = int(bk.basket_at[t])
        v, idx = tvec(j, b)
        if every or not np.array_equal(v, last):
            events.append((t, v, j, b, len(idx), int(state[j])))
            last = v
    return init_idx, events


def init_position(bk: Book, keep_idx: np.ndarray, scale: float, gshare: float):
    u = np.zeros(bk.N)
    u[keep_idx] = bk.u0[keep_idx] * scale
    kept_val = float((bk.u0[keep_idx] * bk.C[0][keep_idx]).sum())
    total = float((bk.u0 * bk.C[0]).sum())
    removed_val = total - kept_val if len(keep_idx) < int((bk.u0 > 0).sum()) else 0.0
    sleeve = removed_val + (1 - scale) * kept_val
    return u, sleeve * gshare / bk.g[0], sleeve * (1 - gshare) / bk.L[0]


def trade(bk: Book, t: int, wvec: np.ndarray, u, gu, cu, ow: float, gshare: float):
    ps, gp, lv = bk.P[t], bk.gf[t], bk.L[t]
    held_s = u * ps
    V = held_s.sum() + gu * gp + cu * lv
    Te = V * wvec
    sleeve = V * (1.0 - wvec.sum())
    Tg, Tc = sleeve * gshare, sleeve * (1 - gshare)
    traded = np.abs(Te - held_s).sum() + abs(Tg - gu * gp) + abs(Tc - cu * lv)
    cost = ow * traded
    k = (V - cost) / V
    new_u = np.zeros_like(u)
    pos = (Te > 0) & (ps > 0)
    assert not ((Te > 0) & (ps <= 0)).any(), f"no price for a stock to buy at session {bk.cal[t].date()}"
    new_u[pos] = k * Te[pos] / ps[pos]
    return new_u, k * Tg / gp, k * Tc / lv, dict(V=V, traded=traded, cost=cost)


def simulate(bk: Book, init, events, cost_bps: float, gshare: float = 0.5, record: bool = False):
    T, ow = bk.T, cost_bps / 2e4
    u, gu, cu = init
    nz = np.flatnonzero(u)
    nav = np.empty(T)
    a = 0
    trades = []
    n_tr, cost_paid = 0, 0.0
    for (t, wvec, j, b, nk, reg) in events:
        if t > a:
            nav[a:t] = (bk.C[a:t][:, nz] @ u[nz] if len(nz) else 0.0) + bk.g[a:t] * gu + bk.L[a:t] * cu
        a = t
        u, gu, cu, inf = trade(bk, t, wvec, u, gu, cu, ow, gshare)
        nz = np.flatnonzero(u)
        n_tr += 1
        cost_paid += inf["cost"]
        if record:
            nav_close = float((bk.C[t][nz] @ u[nz] if len(nz) else 0.0) + gu * bk.g[t] + cu * bk.L[t])
            trades.append({"date": bk.cal[t].date(), "idx": t, "decision_j": j, "regime": "BUY" if reg else "SELL", "basket_eff": bk.eff[b].date(),
                           "n_kept": nk, "n_basket": len(bk.bn[b]), "stock_weight": float(wvec.sum()), **inf, "nav_close_after": nav_close,
                           "kept": ";".join(bk.stocks[i] for i in np.flatnonzero(wvec))})
    nav[a:T] = (bk.C[a:T][:, nz] @ u[nz] if len(nz) else 0.0) + bk.g[a:T] * gu + bk.L[a:T] * cu
    return (nav, trades, n_tr, cost_paid) if record else (nav, n_tr, cost_paid)


def stats(nav: np.ndarray) -> dict:
    T = len(nav)
    yrs = (T - 1) / 252
    r = nav[1:] / nav[:-1] - 1
    peak = np.maximum.accumulate(nav)
    dd = nav / peak - 1
    under = dd < 0
    longest, run = 0, 0
    for x in under:
        run = run + 1 if x else 0
        longest = max(longest, run)
    cagr = nav[-1] ** (1 / yrs) - 1
    mdd = float(dd.min())
    return {"end_nav": float(nav[-1]), "cagr": float(cagr), "max_dd": mdd, "vol": float(r.std(ddof=1) * math.sqrt(252)),
            "ulcer": float(math.sqrt(np.mean((100 * dd) ** 2))), "days_below_10pct": int((dd <= -0.10).sum()),
            "longest_underwater": int(longest), "calmar": float(cagr / abs(mdd)) if mdd < 0 else float("nan"), "sessions": T}


# ── the world: books, decisions, indicators, k counts ─────────────────────────
class World:
    def __init__(self):
        self.bk = Book()
        self.bk_liq = Book(cash="liq")
        self.bk_live = Book(start=LIVE_START)
        self.dec = self.bk.decisions()
        self.dec_live = self.bk_live.decisions()
        q = sorted({pd.Timestamp(d) for d in self.dec["decision_date"]} | {pd.Timestamp(d) for d in self.dec_live["decision_date"]})
        self.ind = Indicators(self.bk.stocks, self.bk.cal, q)
        self.cfg = {}
        for win, bk, dec in (("full", self.bk, self.dec), ("live", self.bk_live, self.dec_live)):
            didx = dec["decision_idx"].values
            st = dec["state"].values.astype(int)
            self.cfg[win] = dict(bk=bk, dec=dec, idx=didx, state=st)
        self.kc: dict = {}
        self.strat_prov: dict = {}
        for win in self.cfg:
            for i, nm in enumerate(IND):
                self.strat_prov[(win, nm)] = strategy_provider(self.ind, i, self.cfg[win]["dec"]["decision_date"], self.cfg[win]["bk"])

    def kcount(self, win: str, nm: str):
        prov = self.strat_prov[(win, nm)]
        return lambda j, b: len(prov(j, b))

    def events_strategy(self, win: str, nm: str):
        c = self.cfg[win]
        return build_events(c["bk"], c["idx"], c["state"], self.strat_prov[(win, nm)])

    def events_null(self, win: str, nm: str, i: int, draw_id: int):
        c = self.cfg[win]
        J = len(c["idx"])
        u = np.random.default_rng([4, i + 1, draw_id]).random((J, c["bk"].N))
        prov = null_provider(c["bk"], u, self.kcount(win, nm))
        return build_events(c["bk"], c["idx"], c["state"], prov)


_W: World | None = None


def _init_worker():
    global _W
    _W = World()


VARIANTS = (  # (window, sleeve name, gshare, cash, cost)
    ("full", "50_50", 0.5, "lbes", 0.0), ("full", "50_50", 0.5, "lbes", PRIMARY), ("full", "50_50", 0.5, "lbes", 50.0),
    ("full", "gold100", 1.0, "lbes", PRIMARY), ("full", "50_50", 0.5, "liquidcase", PRIMARY),
    ("live", "50_50", 0.5, "lbes", PRIMARY),
)


def _book_for(w: World, win: str, cash: str) -> Book:
    return w.bk_live if win == "live" else (w.bk_liq if cash == "liquidcase" else w.bk)


def run_draws(task):
    """One worker task: draws [d0, d1) for indicator index i. Returns draw rows and V3 counters."""
    global _W
    if _W is None:
        _W = World()
    w = _W
    i, d0, d1 = task
    nm = IND[i]
    rows = []
    v3 = {"decisions_checked": 0, "k_mismatch": 0, "buy_events_checked": 0, "buy_mismatch": 0, "draws": 0}
    for did in range(d0, d1):
        evs = {}
        for win in ("full", "live"):
            evs[win] = w.events_null(win, nm, i, did)
            bk = w.cfg[win]["bk"]
            kc = w.kcount(win, nm)
            for (t, v, j, b, nk, reg) in evs[win][1]:
                if reg == 0:
                    v3["decisions_checked"] += 1
                    v3["k_mismatch"] += int(nk != kc(j, b))
                else:
                    v3["buy_events_checked"] += 1
                    v3["buy_mismatch"] += int(not np.array_equal(v, bk.W[b]))
        v3["draws"] += 1
        for (win, sl, gs, cash, cost) in VARIANTS:
            bk = _book_for(w, win, cash)
            init_idx, ev = evs[win]
            nav, n_tr, cp = simulate(bk, init_position(bk, init_idx, 1.0, gs), ev, cost, gs)
            rows.append({"indicator": nm, "window": win, "sleeve": sl, "cash": cash, "cost_bps": cost, "draw_id": did, **stats(nav),
                         "trades": n_tr, "cost_paid": cp})
    return rows, v3


# ── V5: a straight-line hand computation of one indicator on one stock and date ─
def hand_indicator(long_df: pd.DataFrame, stock: str, d: pd.Timestamp, cal_set: set, nm: str):
    """From the raw rows only: lists and loops, no vectorisation. Returns (close_used, value, pass) or None if excluded."""
    x = long_df[(long_df["stock"] == stock) & (long_df["date"] <= d)]
    x = x[(x["date"] <= BAR_CUTOFF) | (x["date"].isin(cal_set))].sort_values("date")
    x = x[x["close"].notna()]
    if x.empty:
        return None
    last = x["date"].iloc[-1]
    if (d - last).days > STALE_DAYS:
        return None
    cl = [float(v) for v in x["close"]]
    if nm in ("I1", "I2", "I3", "I4"):
        n = 50 if nm in ("I1", "I3") else 200
        if len(cl) < n:
            return cl[-1], None, False
        if nm in ("I3", "I4"):
            val = sum(cl[-n:]) / n
        else:
            k = 2 / (n + 1)
            val = sum(cl[:n]) / n
            for v in cl[n:]:
                val = k * v + (1 - k) * val
        return cl[-1], val, cl[-1] > val
    # I5: weekly candles by ISO week, then the supertrend loop spelled out
    hi = [float(v) if not np.isnan(v) else c for v, c in zip(x["high"], cl)]
    lo = [float(v) if not np.isnan(v) else c for v, c in zip(x["low"], cl)]
    weeks, order = {}, []
    for dt, h, l_, c in zip(x["date"], hi, lo, cl):
        key = (dt.isocalendar()[0], dt.isocalendar()[1])
        if key not in weeks:
            weeks[key] = [h, l_, c]
            order.append(key)
        else:
            weeks[key][0] = max(weeks[key][0], h)
            weeks[key][1] = min(weeks[key][1], l_)
            weeks[key][2] = c
    H = [weeks[k][0] for k in order]
    L = [weeks[k][1] for k in order]
    Cc = [weeks[k][2] for k in order]
    n = len(Cc)
    TR = [H[0] - L[0]] + [max(H[i] - L[i], abs(H[i] - Cc[i - 1]), abs(L[i] - Cc[i - 1])) for i in range(1, n)]
    wts = [1, 2, 3, 4, 5]
    fub, flb, st = [None] * n, [None] * n, [None] * n
    for i in range(4, n):
        atr = sum(TR[i - 4 + k] * wts[k] for k in range(5)) / 15
        c_mid = (H[i] + L[i]) / 2
        bub, blb = c_mid + 2 * atr, c_mid - 2 * atr
        if i == 4:
            fub[i], flb[i], st[i] = bub, blb, bub
            continue
        pu, pl, ps_ = fub[i - 1], flb[i - 1], st[i - 1]
        fub[i] = bub if (bub < pu or Cc[i - 1] > pu) else pu
        flb[i] = blb if (blb > pl or Cc[i - 1] < pl) else pl
        if ps_ == pu and Cc[i] <= fub[i]:
            st[i] = fub[i]
        elif ps_ == pu and Cc[i] > fub[i]:
            st[i] = flb[i]
        elif ps_ == pl and Cc[i] >= flb[i]:
            st[i] = flb[i]
        elif ps_ == pl and Cc[i] < fub[i]:
            st[i] = fub[i]
        else:
            st[i] = 0.0
    if n < 5 or st[-1] is None:
        return cl[-1], None, False
    sign = 1.0 if abs(st[-1] - flb[-1]) < 1e-9 else (0.0 if abs(st[-1] - fub[-1]) < 1e-9 else float("nan"))
    return cl[-1], sign, bool(sign == 1.0)


# ── orchestration ─────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="headline")
    ap.add_argument("--draws", type=int, default=N_DRAWS)
    ap.add_argument("--quick", action="store_true", help="20 draws, for a smoke test")
    ap.add_argument("--workers", type=int, default=10)
    a = ap.parse_args()
    outdir = T04 / "evidence" / a.run
    outdir.mkdir(parents=True, exist_ok=True)
    t_start = time.time()
    n_draws = 20 if a.quick else a.draws
    audit: dict = {"readings": READINGS}

    files = [HD / "extended_2026-10-30" / "Master" / f"Master_{n}.xlsx" for n in ("Nifty100", "MC100", "SC100")]
    files += [AA / "analysis" / "cache" / "why_gold_ohlc_eikon_extended_2026-11-04.parquet", AA / "analysis" / "evidence" / "final_strategy" / "mauc1" / "mauc1_daily_clean.csv",
              HD / "LBES_Adjusted_Price_data_extended_2026-11-05.csv", HD / "liquidEtfFinal_extended_2026-11-05.csv", HD / "indices.csv", HM / "price_corrections.csv"]
    files += [HM / f"{PARENT}_{x}.csv" for x in ("ohlc", "holding_weight_matrix", "holding_weight_sources", "columns")] + [HD / "parent_nav_2026-10-22" / f"{PARENT}.csv"]
    pd.DataFrame([{"file": str(f.relative_to(AA)), "bytes": f.stat().st_size, "sha256": sha(f)} for f in files]).to_csv(outdir / "inputs.csv", index=False)

    w = World()
    print(f"world built in {time.time() - t_start:.0f}s; stocks {w.bk.N}, sessions {w.bk.T}, decisions {len(w.dec)}", flush=True)
    bk, dec = w.bk, w.dec
    c = common()

    # ── decisions, T03 cross-check, V2 counts
    dec.to_csv(outdir / "decisions.csv", index=False)
    t3 = pd.read_csv(T03 / "evidence" / "headline" / "decisions.csv")
    t3 = t3[t3["book"] == PARENT].set_index("decision_date")["state"]
    mine = dec.assign(decision_date=dec["decision_date"].astype(str)).set_index("decision_date")["state"]
    shared = t3.index.intersection(mine.index)
    audit["t03_regime_crosscheck"] = {"shared_dates": int(len(shared)), "mismatches": int((t3.loc[shared] != mine.loc[shared]).sum()),
                                      "t03_dates_missing_here": int(len(t3.index.difference(mine.index)))}
    lab_ok = int((pd.to_datetime(dec["latest_label"]) <= pd.to_datetime(dec["decision_date"])).sum())
    traded_rows = int(((dec["decision_idx"].values + 1) < bk.T).sum())
    state = dec["state"].values.astype(int)
    audit["v2"] = {"decisions_checked": len(dec), "label_after_decision": len(dec) - lab_ok, "trades_checked": traded_rows, "trade_not_after_decision": 0,
                   "indicator_bars_after_query_date": int(w.ind.bars_after_query), "indicator_stock_dates_checked": int(w.ind.valid.sum()),
                   "weekly_candle_recomputed_stock_dates": int(w.ind.slow_path),
                   "stale_label_weeks(age>=5d, excluding T0)": int((dec["label_age_days"].values[1:] >= 5).sum())}
    audit["decisions"] = {"n": len(dec), "buy": int(state.sum()), "sell": int(len(state) - state.sum()), "t0": str(bk.t0.date()), "sessions": bk.T,
                          "end": str(bk.cal[-1].date()), "live_t0": str(w.bk_live.t0.date()), "live_decisions": len(w.dec_live),
                          "skipped_baskets_dropped": [str(x.date()) for x in raw_parent()["skipped"]],
                          "initial_basket_switch_session": bk.initial_basket_switch_session}
    audit["indicators_not_computable_stock_dates"] = w.ind.not_computable

    # ── indicators.csv and selections.csv
    q = w.ind.qpos
    irows, srows = [], []
    for win in ("full", "live"):
        cf = w.cfg[win]
        for j, d in enumerate(cf["dec"]["decision_date"]):
            row = q[pd.Timestamp(d)]
            t_basket = min(int(cf["idx"][j]) + 1, cf["bk"].T - 1)
            b = int(cf["bk"].basket_at[t_basket])
            for s in cf["bk"].bn[b]:
                if win == "full":
                    irows.append({"decision_date": d, "stock": bk.stocks[s], "weight": bk.W[b][s], "valid": bool(w.ind.valid[row, s]),
                                  "last_bar": str(w.ind.last_bar[row, s]), "close_used": w.ind.close[row, s], "ema50": w.ind.val["ema50"][row, s],
                                  "ema200": w.ind.val["ema200"][row, s], "sma50": w.ind.val["sma50"][row, s], "sma200": w.ind.val["sma200"][row, s],
                                  "st_sign": w.ind.val["st"][row, s], **{f"pass_{nm}": bool(w.ind.passes[i][row, s]) for i, nm in enumerate(IND)}})
            for i, nm in enumerate(IND):
                kept = w.strat_prov[(win, nm)](j, b)
                srows.append({"window": win, "indicator": nm, "j": j, "decision_date": d, "regime": cf["dec"]["regime"].iloc[j], "basket_eff": cf["bk"].eff[b].date(),
                              "n": len(cf["bk"].bn[b]), "k": len(kept), "kept": ";".join(bk.stocks[s] for s in kept),
                              "nontrivial": bool(cf["dec"]["state"].iloc[j] == 0 and 0 < len(kept) < len(cf["bk"].bn[b]))})
    pd.DataFrame(irows).to_csv(outdir / "indicators.csv", index=False)
    sel = pd.DataFrame(srows)
    sel.to_csv(outdir / "selections.csv", index=False)
    rep = {}
    for win in ("full", "live"):
        for nm in IND:
            s = sel[(sel["window"] == win) & (sel["indicator"] == nm) & (sel["regime"] == "SELL")]
            rep[f"{win}|{nm}"] = {"sell_decisions": int(len(s)), "nontrivial": int(s["nontrivial"].sum()), "k_zero": int((s["k"] == 0).sum()),
                                  "k_all": int((s["k"] == s["n"]).sum()), "mean_k": float(s["k"].mean()), "mean_n": float(s["n"].mean()),
                                  "reportable": bool(s["nontrivial"].sum() >= 20)}
    audit["reportability"] = rep
    print("reportability", {k: (v["nontrivial"], v["reportable"]) for k, v in rep.items()}, flush=True)

    # ── V5: indicator spot checks against a straight-line hand computation
    o = pd.read_csv(HM / f"{PARENT}_ohlc.csv", parse_dates=["date"]).drop_duplicates(["date", "stock"])
    cor = pd.read_csv(HM / "price_corrections.csv", parse_dates=["ex_date"])
    for r in cor.itertuples():
        if PARENT in r.applies_to.split(";"):
            m = (o["stock"] == r.stock) & (o["date"] < r.ex_date)
            for f in ("open", "high", "low", "close"):
                o.loc[m, f] *= r.factor
    cal_set = set(bk.cal)
    rng = np.random.default_rng([4, 0, 5])
    v5 = []
    for i, nm in enumerate(IND):
        picks = 0
        while picks < 10:
            j = int(rng.integers(0, len(dec)))
            d = pd.Timestamp(dec["decision_date"].iloc[j])
            row = q[d]
            cand = np.flatnonzero(w.ind.valid[row])
            s = int(cand[rng.integers(0, len(cand))])
            h = hand_indicator(o, bk.stocks[s], d, cal_set, nm)
            eng_pass = bool(w.ind.passes[i][row, s])
            key = ["ema50", "ema200", "sma50", "sma200", "st"][i]
            eng_val = float(w.ind.val[key][row, s])
            hv = np.nan if h is None or h[1] is None else float(h[1])
            ok = (h is not None and h[2] == eng_pass and ((np.isnan(hv) and np.isnan(eng_val)) or abs(hv - eng_val) <= 1e-9 * max(1.0, abs(hv))))
            v5.append({"indicator": nm, "stock": bk.stocks[s], "date": str(d.date()), "engine_value": eng_val, "hand_value": hv, "engine_pass": eng_pass,
                       "hand_pass": None if h is None else bool(h[2]), "ok": bool(ok)})
            picks += 1
    audit["v5"] = {"checked": len(v5), "failed": int(sum(not r["ok"] for r in v5)), "rows": v5}
    print("V5", audit["v5"]["checked"], "checked", audit["v5"]["failed"], "failed", flush=True)

    # ── strategy realisations, comparators
    out_rows, trade_rows, nav_cols = [], [], {}
    f_by_ind = {}
    for nm in IND:
        for (win, sl, gs, cash, cost) in VARIANTS:
            b2 = _book_for(w, win, cash)
            cf = w.cfg[win]
            init_idx, ev = w.events_strategy(win, nm)
            nav, tr, n_tr, cp = simulate(b2, init_position(b2, init_idx, 1.0, gs), ev, cost, gs, record=True)
            # equity share of each decision (BUY = 1, SELL = sum of kept weights)
            eq = []
            for j in range(len(cf["idx"])):
                bsk = int(b2.basket_at[min(int(cf["idx"][j]) + 1, b2.T - 1)])
                eq.append(1.0 if cf["state"][j] == 1 else float(b2.W[bsk][w.strat_prov[(win, nm)](j, bsk)].sum()))
            out_rows.append({"kind": "strategy", "indicator": nm, "window": win, "sleeve": sl, "cash": cash, "cost_bps": cost, **stats(nav),
                             "trades": n_tr, "cost_paid": cp, "mean_equity_share": float(np.mean(eq)), "buy_weeks": int(cf["state"].sum()),
                             "weeks": len(cf["state"])})
            if win == "full" and sl == "50_50" and cash == "lbes":
                nav_cols[("strategy", nm, cost)] = (nav, b2.cal)
                trade_rows += [{"indicator": nm, "cost_bps": cost, **t} for t in tr]
                if cost == PRIMARY:
                    f_by_ind[nm] = float(np.mean(eq))
    # comparators (full window; every cost)
    for cost in COSTS:
        init_idx, ev = build_events(bk, w.cfg["full"]["idx"], np.ones(len(dec), dtype=int), None)
        nav, tr, n_tr, cp = simulate(bk, init_position(bk, init_idx, 1.0, 0.5), ev, cost, record=True)
        out_rows.append({"kind": "hold_parent", "indicator": "", "window": "full", "sleeve": "50_50", "cash": "lbes", "cost_bps": cost, **stats(nav), "trades": n_tr, "cost_paid": cp})
        nav_cols[("hold_parent", "", cost)] = (nav, bk.cal)
        trade_rows += [{"indicator": "hold_parent", "cost_bps": cost, **t} for t in tr]
        prov0 = strategy_provider(w.ind, 0, dec["decision_date"], bk, none=True)
        init_idx, ev = build_events(bk, w.cfg["full"]["idx"], state, prov0)
        nav, tr, n_tr, cp = simulate(bk, init_position(bk, init_idx, 1.0, 0.5), ev, cost, record=True)
        out_rows.append({"kind": "full_aa_switch", "indicator": "", "window": "full", "sleeve": "50_50", "cash": "lbes", "cost_bps": cost, **stats(nav), "trades": n_tr, "cost_paid": cp})
        nav_cols[("full_aa_switch", "", cost)] = (nav, bk.cal)
        trade_rows += [{"indicator": "full_aa_switch", "cost_bps": cost, **t} for t in tr]
        for nm in IND:
            f = f_by_ind[nm]
            init_idx, ev = build_events(bk, w.cfg["full"]["idx"], np.ones(len(dec), dtype=int), None, every=True, scale=f)
            nav, n_tr, cp = simulate(bk, init_position(bk, init_idx, f, 0.5), ev, cost)
            out_rows.append({"kind": "constant_mix", "indicator": nm, "window": "full", "sleeve": "50_50", "cash": "lbes", "cost_bps": cost, **stats(nav),
                             "trades": n_tr, "cost_paid": cp, "mean_equity_share": f})
            nav_cols[("constant_mix", nm, cost)] = (nav, bk.cal)
    # published NAVs (descriptive)
    pub = pd.Series(bk.pub, index=bk.cal).dropna()
    nav_cols[("published_SCMO_0003", "", np.nan)] = (pub.values / pub.values[0], pub.index)
    ix = pd.read_csv(HD / "indices.csv")
    ix = ix[ix["scid"] == "SCMO_0042"]
    ix["date"] = pd.to_datetime(ix["date"], format="%d/%m/%y %H:%M")
    ix = ix.set_index("date")["index"].sort_index()
    nav_cols[("published_SCMO_0042", "", np.nan)] = (ix.values / ix.values[0], ix.index)

    # ── T03 cross-check: the full AA switch on T03's dates reproduces T03's SCMO_0003 strategy NAV (LBES accrual differs after 2026-08-09)
    t3n = pd.read_csv(T03 / "evidence" / "headline" / "daily_nav.csv", parse_dates=["date"])
    t3n = t3n[(t3n["book"] == PARENT) & (t3n["run"] == "strategy")]
    xc = []
    for cost in COSTS:
        a_ = pd.Series(nav_cols[("full_aa_switch", "", cost)][0], index=bk.cal)
        b_ = t3n[t3n["cost_bps"] == cost].set_index("date")["nav"]
        com = a_.index.intersection(b_.index)
        com_early = com[com <= pd.Timestamp("2026-08-07")]
        xc.append({"cost_bps": cost, "dates": int(len(com_early)), "max_rel_diff_to_2026-08-07": float(((a_.loc[com_early] / b_.loc[com_early]) - 1).abs().max()),
                   "rel_diff_at_2026-08-21": float(a_.loc[pd.Timestamp("2026-08-21")] / b_.loc[pd.Timestamp("2026-08-21")] - 1)})
    audit["t03_nav_crosscheck"] = xc

    # ── GOLDBEES fills not de-spiked (after the MCX file's end)
    gl = []
    tdates = sorted({pd.Timestamp(t["date"]) for t in trade_rows if t["indicator"] in IND})
    for d in tdates:
        if d > MCX_END:
            t_ = bk.cal.get_loc(d)
            gl.append({"date": str(d.date()), "goldbees_fill_raw_ohlc4": float(bk.gf[t_]), "goldbees_close": float(bk.g[t_]), "fill_over_close_pct": float(100 * (bk.gf[t_] / bk.g[t_] - 1))})
    audit["goldbees_fills_not_despiked"] = gl

    # ── V4: always in reproduces the published NAV (G0)
    bk4 = Book(end=V4_END)
    d4 = bk4.decisions()
    init_idx, ev = build_events(bk4, d4["decision_idx"].values, np.ones(len(d4), dtype=int), None)
    nav4, _, _ = simulate(bk4, init_position(bk4, init_idx, 1.0, 0.5), ev, 0.0)
    cc = pd.DataFrame({"m": nav4, "p": bk4.pub}, index=bk4.cal)
    cc = cc / cc.iloc[0] * 100
    yrs = (cc.index[-1] - cc.index[0]).days / 365.25
    gap = ((cc.m.iloc[-1] / cc.m.iloc[0]) ** (1 / yrs) - (cc.p.iloc[-1] / cc.p.iloc[0]) ** (1 / yrs)) * 100
    worst, wy = 0.0, None
    yearly = {}
    for yr, g in cc.groupby(cc.index.year):
        prev = cc.loc[:g.index[0]].iloc[-2] if len(cc.loc[:g.index[0]]) > 1 else g.iloc[0]
        dd_ = (g["m"].iloc[-1] / prev["m"] - g["p"].iloc[-1] / prev["p"]) * 100
        yearly[int(yr)] = float(dd_)
        if abs(dd_) > abs(worst):
            worst, wy = dd_, int(yr)
    g4 = {"book": PARENT, "first": str(cc.index[0].date()), "last": str(cc.index[-1].date()), "cagr_gap_pp_yr": float(gap), "overall": "PASS" if abs(gap) <= 0.25 else "FAIL",
          "worst_year": wy, "worst_year_gap_pp": float(worst), "yearly": "PASS" if abs(worst) <= 0.5 else "FAIL", "yearly_gaps_pp": yearly}
    pd.DataFrame([{k: v for k, v in g4.items() if k != "yearly_gaps_pp"}]).to_csv(outdir / "g_engine.csv", index=False)
    audit["v4"] = g4
    print("V4", {k: g4[k] for k in ("cagr_gap_pp_yr", "overall", "worst_year", "worst_year_gap_pp", "yearly")}, flush=True)

    # ── null draws (parallel)
    chunks = []
    per = max(1, math.ceil(n_draws / max(1, a.workers * 2)))
    for i in range(5):
        for d0 in range(0, n_draws, per):
            chunks.append((i, d0, min(n_draws, d0 + per)))
    draws, v3 = [], {"decisions_checked": 0, "k_mismatch": 0, "buy_events_checked": 0, "buy_mismatch": 0, "draws": 0}
    t_d = time.time()
    if a.workers <= 1:
        res = [run_draws(ch) for ch in chunks]
    else:
        with ProcessPoolExecutor(max_workers=a.workers, initializer=_init_worker) as ex:
            res = list(ex.map(run_draws, chunks))
    for rows, v in res:
        draws += rows
        for k in v3:
            v3[k] += v[k]
    print(f"draws done in {time.time() - t_d:.0f}s ({len(draws)} rows)", flush=True)
    audit["v3"] = {**v3, "draws_per_indicator": n_draws, "pass": bool(v3["k_mismatch"] == 0 and v3["buy_mismatch"] == 0 and v3["decisions_checked"] > 0)}

    # ── write
    pd.DataFrame(out_rows).to_csv(outdir / "stats.csv", index=False)
    pd.DataFrame(draws).to_csv(outdir / "draws.csv", index=False)
    pd.DataFrame(trade_rows).to_csv(outdir / "trades.csv", index=False)
    dn = []
    for (kind, nm, cost), (nv, idx) in nav_cols.items():
        dn.append(pd.DataFrame({"kind": kind, "indicator": nm, "cost_bps": cost, "date": idx, "nav": nv}))
    pd.concat(dn).to_csv(outdir / "daily_nav.csv", index=False)
    audit["run"] = {"name": a.run, "draws": n_draws, "seconds": round(time.time() - t_start), "quick": a.quick, "workers": a.workers,
                    "seed": "numpy default_rng([4, i, draw_id]), i = 1..5 for I1..I5; the same draw ids for every cost, sleeve, cash variant"}
    audit["prereg_sha256"] = (T04 / "T04.md").read_text(encoding="utf-8").split("§1–§3 sha256:** `")[1].split("`")[0]
    (outdir / "audit.json").write_text(json.dumps(audit, indent=1, default=str), encoding="utf-8")
    s = pd.DataFrame(out_rows)
    print(s[(s["kind"] == "strategy") & (s["window"] == "full") & (s["sleeve"] == "50_50") & (s["cash"] == "lbes")][["indicator", "cost_bps", "cagr", "max_dd", "end_nav", "trades"]].round(4).to_string(index=False))
    print(s[s["kind"].isin(["hold_parent", "full_aa_switch"])][["kind", "cost_bps", "cagr", "max_dd", "end_nav", "trades"]].round(4).to_string(index=False))
    print("V3", audit["v3"])
    print(f"done in {time.time() - t_start:.0f}s -> {outdir}")


if __name__ == "__main__":
    main()
