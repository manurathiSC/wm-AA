"""T04 independent verifier (gate V1).

Re-derives T04's decisions, indicator tables, selections, NAVs, costs, trades, comparators and
null draws from the RAW files only (plain numpy / pandas, its own loaders) and compares them with
the engine's evidence in tests/T04/evidence/headline/.

It imports nothing from the engine or from any other module in analysis/ or data/, and it never
reads the engine's source. The rules are tests/T04/logs/verifier_spec.md and tests/T04/T04.md s.1-3.
Where those texts are silent the reading taken is written next to the code ("READING:") and
collected in the JSON output.

Usage (from AA/):
    python analysis/verify_t04.py                       # real run + self-test on a corrupted copy
    python analysis/verify_t04.py --evidence DIR --no-selftest

Exit code 0 only if every check compared rows, none failed, and the corrupted copy was detected.
"""
import argparse
import json
import shutil
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

AA = Path(__file__).resolve().parents[1]
HIST = AA / "Historical Data"
HM = AA / "data" / "holdings_matrix"
PARENT = "SCMO_0003"
TOL = 1e-9
ABS_FLOOR = 1e-13
COSTS = [0.0, 20.8, 50.0]
INDS = ["I1", "I2", "I3", "I4", "I5"]
END = pd.Timestamp("2026-11-04")
T0_FULL = pd.Timestamp("2019-01-02")
LIVE_FROM = pd.Timestamp("2021-11-01")
D17_END = pd.Timestamp("2026-10-22")
LIQ_SWITCH = pd.Timestamp("2024-01-24")
STALE_DAYS = 7
SCRATCH = Path(r"C:\Users\manur\AppData\Local\Temp\claude\d384933f9ddb0ecb\7a6d038d-13f6-45c4-9bbc-6398be3adaed\scratchpad")
# READING (spec s.8, parenthetical): in the "ST sits on FLB" branch the desk code tests close < FUB.
# 'B' = ST = FLB if close < FUB else FUB (primary). 'A' = textbook ST = FLB if close >= FLB else FUB (diagnostic only).
ST_READING = "A"


# ======================================================================================
# raw loaders
# ======================================================================================
def load_published():
    d = pd.read_csv(HIST / "parent_nav_2026-10-22" / f"{PARENT}.csv")
    d["date"] = pd.to_datetime(d["_id.date"], format="%Y/%m/%d")
    return d.set_index("date")["index"].sort_index()


def load_masters():
    out = {}
    for name in ["Nifty100", "MC100", "SC100"]:
        m = pd.read_excel(HIST / "extended_2026-10-30" / "Master" / f"Master_{name}.xlsx")
        m = m[["Date", "SIGN"]].copy()
        m["SIGN"] = m["SIGN"].astype("object")
        m = m[m["SIGN"].notna()]
        m["SIGN"] = m["SIGN"].astype(str).str.strip().str.upper()
        m = m[m["SIGN"] != ""]
        m["Date"] = pd.to_datetime(m["Date"])
        m = m.sort_values("Date").reset_index(drop=True)
        out[name] = (m["Date"].values.astype("datetime64[D]"), m["SIGN"].values)
    return out


def load_ohlc():
    o = pd.read_csv(HM / f"{PARENT}_ohlc.csv", usecols=["date", "stock", "open", "high", "low", "close"])
    o["date"] = pd.to_datetime(o["date"])
    c = pd.read_csv(HM / "price_corrections.csv")
    c["ex_date"] = pd.to_datetime(c["ex_date"])
    for _, r in c.iterrows():
        books = [x.strip() for x in str(r["applies_to"]).replace(";", ",").split(",")]
        if PARENT in books:
            msk = (o["stock"] == r["stock"]) & (o["date"] < r["ex_date"])
            for col in ["open", "high", "low", "close"]:
                o.loc[msk, col] = o.loc[msk, col] * float(r["factor"])
    o = o[o["close"].notna()].drop_duplicates(["date", "stock"], keep="last")
    return o


def load_baskets():
    m = pd.read_csv(HM / f"{PARENT}_holding_weight_matrix.csv")
    m = m.rename(columns={m.columns[0]: "avail"})
    m["avail"] = pd.to_datetime(m["avail"])
    s = pd.read_csv(HM / f"{PARENT}_holding_weight_sources.csv")
    s["rebalance_date"] = pd.to_datetime(s["rebalance_date"])
    skipped = set(s.loc[s["source"] == "csv_only_skipped", "rebalance_date"])
    m = m[~m["avail"].isin(skipped)].sort_values("avail").reset_index(drop=True)
    cols = [c for c in m.columns if c != "avail"]
    W = m[cols].fillna(0.0).values.astype(float)
    W = W / W.sum(axis=1, keepdims=True)
    return m["avail"].values.astype("datetime64[D]"), cols, W, len(skipped)


def load_gold(cal):
    g = pd.read_parquet(AA / "analysis" / "cache" / "why_gold_ohlc_eikon_extended_2026-11-04.parquet")
    g = g[["date", "open", "high", "low", "close"]].copy()
    g["date"] = pd.to_datetime(g["date"]).dt.normalize()
    g = g.drop_duplicates("date", keep="last").set_index("date").sort_index()
    m = pd.read_csv(AA / "analysis" / "evidence" / "final_strategy" / "mauc1" / "mauc1_daily_clean.csv")
    m = m.rename(columns={m.columns[0]: "date"})
    m["date"] = pd.to_datetime(m["date"]).dt.normalize()
    m = m.drop_duplicates("date", keep="last").set_index("date").sort_index()
    rng = ((m["high"] - m["low"]) / m["close"]).reindex(g.index)
    band = rng + 0.005
    lo = g["close"] * (1 - band)
    hi = g["close"] * (1 + band)
    o2 = g["open"].clip(lower=lo, upper=hi)
    h2 = np.minimum(g["high"], hi)
    l2 = np.maximum(g["low"], lo)
    h2 = np.maximum(np.maximum(h2, o2), g["close"])
    l2 = np.minimum(np.minimum(l2, o2), g["close"])
    have = rng.notna()
    o_ = g["open"].where(~have, o2)
    h_ = g["high"].where(~have, h2)
    l_ = g["low"].where(~have, l2)
    fill = (o_ + h_ + l_ + g["close"]) / 4.0
    gclose = g["close"].reindex(cal, method="ffill").values.astype(float)
    gfill = fill.reindex(cal).values.astype(float)
    gfill = np.where(np.isnan(gfill), gclose, gfill)
    return gfill, gclose


def load_cash(cal):
    d = pd.read_csv(HIST / "LBES_Adjusted_Price_data_extended_2026-11-05.csv")
    d["date"] = pd.to_datetime(d["date"], format="%d/%m/%y %H:%M").dt.normalize()
    lbes = d.drop_duplicates("date", keep="last").set_index("date")["price"].sort_index()
    L = lbes.reindex(cal, method="ffill").values.astype(float)
    q = pd.read_csv(HIST / "liquidEtfFinal_extended_2026-11-05.csv")
    q["date"] = pd.to_datetime(q["date"], format="%d-%m-%Y")
    lc = q.drop_duplicates("date", keep="last").set_index("date")["liquid_case"].sort_index()
    lc_s = lc.reindex(cal, method="ffill").values.astype(float)
    i0 = int(np.searchsorted(cal.values, np.datetime64(LIQ_SWITCH), side="left")) - 1   # last session before 2024-01-24
    L3 = L.copy()
    L3[i0 + 1:] = L[i0] * lc_s[i0 + 1:] / lc_s[i0]
    return L, L3, str(cal[i0].date())


# ======================================================================================
# calendar, decisions
# ======================================================================================
def build_calendar(pub, d18):
    d17 = pub.index[pub.index >= T0_FULL]
    extra = d18[(d18 > d17[-1]) & (d18 <= END)]
    cal = d17.append(pd.DatetimeIndex(extra)).sort_values().unique()
    return cal


def make_window(cal, masters, t0):
    """Decisions: t0, then the last session of each later ISO week. Returns dict."""
    iso = pd.DatetimeIndex(cal).isocalendar()
    key = (iso["year"].values.astype(int) * 100 + iso["week"].values.astype(int))
    last_of_week = np.r_[np.flatnonzero(key[1:] != key[:-1]), len(cal) - 1]
    idx = [t0] + [int(i) for i in last_of_week if i > t0]
    dec_dates = cal[idx]
    labels, signs = {}, {}
    for name, (md, ms) in masters.items():
        pos = np.searchsorted(md, dec_dates.values.astype("datetime64[D]"), side="right") - 1
        labels[name] = md[pos]
        signs[name] = ms[pos]
    state = np.ones(len(idx), dtype=int)
    for name in masters:
        state &= (signs[name] == "BUY").astype(int)
    return dict(t0=t0, idx=np.array(idx), dates=dec_dates, state=state, labels=labels, signs=signs)


# ======================================================================================
# indicators (own implementation, per stock)
# ======================================================================================
def ema_series(c, N):
    out = np.full(len(c), np.nan)
    if len(c) < N:
        return out
    k = 2.0 / (N + 1.0)
    e = float(np.mean(c[:N]))
    out[N - 1] = e
    for m in range(N, len(c)):
        e = k * c[m] + (1.0 - k) * e
        out[m] = e
    return out


def sma_series(c, N):
    out = np.full(len(c), np.nan)
    if len(c) < N:
        return out
    cs = np.lib.stride_tricks.sliding_window_view(c, N)
    out[N - 1:] = cs.mean(axis=1)
    return out


def st_step(prev, H, L, C_prev, C, atr):
    """One SuperTrend step. prev = (FUB, FLB, ST) of the previous candle or None for the first defined candle."""
    centre = (H + L) / 2.0
    bub = centre + 2.0 * atr
    blb = centre - 2.0 * atr
    if prev is None:
        return bub, blb, bub
    pfub, pflb, pst = prev
    fub = bub if (bub < pfub or C_prev > pfub) else pfub
    flb = blb if (blb > pflb or C_prev < pflb) else pflb
    if pst == pfub:
        st = fub if C <= fub else flb
    elif pst == pflb:
        if ST_READING == "B":
            st = flb if C < fub else fub
        else:
            st = flb if C >= flb else fub
    else:
        st = 0.0
    return fub, flb, st


def weighted_atr(tr5):
    return float((1 * tr5[0] + 2 * tr5[1] + 3 * tr5[2] + 4 * tr5[3] + 5 * tr5[4]) / 15.0)


def true_range(H, L, Cprev):
    return max(H - L, abs(H - Cprev), abs(L - Cprev))


class StockBars:
    """A stock's own admissible bars and the derived series."""

    def __init__(self, dts, close, high, low):
        self.d = dts                       # int64 days since epoch
        self.c = close
        self.h = high
        self.l = low
        n = len(dts)
        self.n = n
        self.ema50 = ema_series(close, 50)
        self.ema200 = ema_series(close, 200)
        self.sma50 = sma_series(close, 50)
        self.sma200 = sma_series(close, 200)
        # weekly candles
        iso = pd.DatetimeIndex(dts.astype("datetime64[D]")).isocalendar()
        key = iso["year"].values.astype(int) * 100 + iso["week"].values.astype(int)
        starts = np.r_[0, np.flatnonzero(key[1:] != key[:-1]) + 1] if n else np.array([], dtype=int)
        ends = np.r_[starts[1:], n] if n else np.array([], dtype=int)
        self.cs, self.ce = starts, ends
        self.week_of_bar = np.zeros(n, dtype=int)
        for ci, (s, e) in enumerate(zip(starts, ends)):
            self.week_of_bar[s:e] = ci
        nc = len(starts)
        H = np.full(nc, np.nan)
        L = np.full(nc, np.nan)
        C = np.full(nc, np.nan)
        for ci, (s, e) in enumerate(zip(starts, ends)):
            hh = high[s:e]
            ll = low[s:e]
            H[ci] = np.nanmax(hh) if np.isfinite(hh).any() else np.nan
            L[ci] = np.nanmin(ll) if np.isfinite(ll).any() else np.nan
            C[ci] = close[e - 1]
        self.H, self.L, self.C = H, L, C
        tr = np.full(nc, np.nan)
        for ci in range(nc):
            tr[ci] = (H[ci] - L[ci]) if ci == 0 else true_range(H[ci], L[ci], C[ci - 1])
        self.tr = tr
        fub = np.full(nc, np.nan)
        flb = np.full(nc, np.nan)
        st = np.full(nc, np.nan)
        prev = None
        for ci in range(4, nc):
            atr = weighted_atr(tr[ci - 4:ci + 1])
            if not np.isfinite(atr) or not np.isfinite(H[ci]) or not np.isfinite(L[ci]):
                prev = None
                continue
            res = st_step(prev, H[ci], L[ci], C[ci - 1], C[ci], atr)
            fub[ci], flb[ci], st[ci] = res
            prev = res
        self.fub, self.flb, self.st = fub, flb, st

    def at(self, qday):
        """Everything at a query day (int days since epoch). Returns dict."""
        nb = int(np.searchsorted(self.d, qday, side="right"))
        if nb == 0:
            return None
        last = int(self.d[nb - 1])
        fresh = (qday - last) <= STALE_DAYS
        r = dict(nb=nb, last_bar=last, fresh=fresh, close=float(self.c[nb - 1]),
                 ema50=self.ema50[nb - 1], ema200=self.ema200[nb - 1], sma50=self.sma50[nb - 1], sma200=self.sma200[nb - 1])
        r["st_sign"] = self._st_sign(nb)
        return r

    def _st_sign(self, nb):
        ci = int(self.week_of_bar[nb - 1])
        if ci < 4:
            return np.nan
        complete = (nb >= self.ce[ci])
        if complete:
            fl, st = self.flb[ci], self.st[ci]
            if not np.isfinite(st):
                return np.nan
            return 1.0 if abs(st - fl) < 1e-9 else 0.0
        s = self.cs[ci]
        hh, ll = self.h[s:nb], self.l[s:nb]
        if not (np.isfinite(hh).any() and np.isfinite(ll).any()):
            return np.nan
        Hc, Lc, Cc = np.nanmax(hh), np.nanmin(ll), self.c[nb - 1]
        trc = true_range(Hc, Lc, self.C[ci - 1])
        tr5 = np.r_[self.tr[ci - 4:ci], trc]
        atr = weighted_atr(tr5)
        if not np.isfinite(atr):
            return np.nan
        if ci == 4:
            prev = None
        else:
            if not np.isfinite(self.st[ci - 1]):
                return np.nan
            prev = (self.fub[ci - 1], self.flb[ci - 1], self.st[ci - 1])
        fub, flb, st = st_step(prev, Hc, Lc, self.C[ci - 1], Cc, atr)
        return 1.0 if abs(st - flb) < 1e-9 else 0.0


def brute_indicators(o_stock, qdate, cal_days, t0_day):
    """Straight-line recomputation from raw rows (V5 style, no shared code with StockBars)."""
    rows = o_stock
    dd = rows["date"].values.astype("datetime64[D]").astype(np.int64)
    keep = (dd <= t0_day) | np.isin(dd, cal_days)
    rows = rows[keep]
    dd = rows["date"].values.astype("datetime64[D]").astype(np.int64)
    qd = int(np.datetime64(qdate, "D").astype(np.int64))
    rows = rows[dd <= qd]
    out = dict(valid=False, close=np.nan, ema50=np.nan, ema200=np.nan, sma50=np.nan, sma200=np.nan, st_sign=np.nan)
    if len(rows) == 0:
        return out
    closes = [float(x) for x in rows["close"].values]
    lastd = int(rows["date"].values.astype("datetime64[D]").astype(np.int64)[-1])
    out["valid"] = (qd - lastd) <= STALE_DAYS
    out["close"] = closes[-1]
    for N, nm in [(50, "50"), (200, "200")]:
        if len(closes) >= N:
            k = 2.0 / (N + 1)
            e = sum(closes[:N]) / N
            for x in closes[N:]:
                e = k * x + (1 - k) * e
            out["ema" + nm] = e
            out["sma" + nm] = sum(closes[-N:]) / N
    # weekly candles
    ts = pd.to_datetime(rows["date"].values)
    iso = ts.isocalendar()
    wk = list(zip(iso["year"].values.astype(int), iso["week"].values.astype(int)))
    candles = []
    for i, w in enumerate(wk):
        h, l, c = rows["high"].values[i], rows["low"].values[i], rows["close"].values[i]
        if candles and candles[-1][0] == w:
            cd = candles[-1]
            cd[1] = np.nanmax([cd[1], h]) if not (np.isnan(cd[1]) and np.isnan(h)) else np.nan
            cd[2] = np.nanmin([cd[2], l]) if not (np.isnan(cd[2]) and np.isnan(l)) else np.nan
            cd[3] = c
        else:
            candles.append([w, h, l, c])
    if len(candles) >= 5:
        trs = []
        for i, (_, h, l, c) in enumerate(candles):
            if i == 0:
                trs.append(h - l)
            else:
                pc = candles[i - 1][3]
                trs.append(max(h - l, abs(h - pc), abs(l - pc)))
        fub = flb = st = None
        for i in range(4, len(candles)):
            _, h, l, c = candles[i]
            atr = sum((m + 1) * trs[i - 4 + m] for m in range(5)) / 15.0
            cen = (h + l) / 2
            bub, blb = cen + 2 * atr, cen - 2 * atr
            if fub is None:
                fub, flb, st = bub, blb, bub
            else:
                pc = candles[i - 1][3]
                nfub = bub if (bub < fub or pc > fub) else fub
                nflb = blb if (blb > flb or pc < flb) else flb
                if st == fub:
                    nst = nfub if c <= nfub else nflb
                elif st == flb:
                    nst = (nflb if c < nfub else nfub) if ST_READING == "B" else (nflb if c >= nflb else nfub)
                else:
                    nst = 0.0
                fub, flb, st = nfub, nflb, nst
        out["st_sign"] = 1.0 if abs(st - flb) < 1e-9 else 0.0
    return out


# ======================================================================================
# derivation of everything
# ======================================================================================
class World:
    pass


def derive(log):
    t_start = time.time()
    Wd = World()
    pub = load_published()
    o = load_ohlc()
    d18 = pd.DatetimeIndex(sorted(o["date"].unique()))
    cal = build_calendar(pub, d18)
    S = len(cal)
    Wd.cal, Wd.S, Wd.pub, Wd.d18 = cal, S, pub, d18
    avail, cols, Wn, n_skipped = load_baskets()
    N = len(cols)
    Wd.avail, Wd.cols, Wd.Wn, Wd.N = avail, cols, Wn, N
    Wd.n_skipped_baskets = n_skipped

    # prices
    wide = {c: o.pivot(index="date", columns="stock", values=c).reindex(d18).reindex(columns=cols) for c in ["open", "high", "low", "close"]}
    close_ff = wide["close"].ffill()
    ohlc4 = (wide["open"] + wide["high"] + wide["low"] + wide["close"]) / 4.0
    all4 = wide["open"].notna() & wide["high"].notna() & wide["low"].notna() & wide["close"].notna()
    bar = wide["close"].notna()
    fill_d18 = ohlc4.where(all4, wide["close"]).where(bar, close_ff)
    Wd.C = np.nan_to_num(close_ff.reindex(cal).values.astype(float), nan=0.0)
    Wd.F = np.nan_to_num(fill_d18.reindex(cal).values.astype(float), nan=0.0)
    Wd.F_d18 = fill_d18
    Wd.gF, Wd.gC = load_gold(cal)
    Wd.L_lbes, Wd.L_liq, Wd.liq_base_date = load_cash(cal)
    masters = load_masters()
    Wd.masters = masters

    # windows
    t0_live = int(np.searchsorted(cal.values, np.datetime64(LIVE_FROM), side="left"))
    Wd.t0_live = t0_live
    Wd.win = {"full": make_window(cal, masters, 0), "live": make_window(cal, masters, t0_live)}

    # baskets: effect session and basket in force
    eff = np.searchsorted(cal.values.astype("datetime64[D]"), avail, side="left")
    eff_by_idx = {}
    for k in range(len(avail)):
        if eff[k] < S:
            eff_by_idx[int(eff[k])] = k            # later availableDate with the same effect session overrides
    keys = sorted(eff_by_idx)
    # READING: eff index 0 means availableDate <= T0 (calendar starts at T0); the latest such basket is in force at T0.
    bk_eff = np.array(keys)
    bk_id = np.array([eff_by_idx[k] for k in keys])
    Wd.bk_eff, Wd.bk_id = bk_eff, bk_id
    Wd.mem = {int(b): np.flatnonzero(Wn[b] > 0) for b in bk_id}
    Wd.avail_str = {int(b): str(np.datetime_as_string(avail[b], unit="D")) for b in bk_id}

    # indicator tables at all needed query dates
    qdates = sorted(set(Wd.win["full"]["dates"]) | set(Wd.win["live"]["dates"]))
    Wd.qdates = pd.DatetimeIndex(qdates)
    Wd.qpos = {d: i for i, d in enumerate(Wd.qdates)}
    qdays = Wd.qdates.values.astype("datetime64[D]").astype(np.int64)
    cal_days = cal.values.astype("datetime64[D]").astype(np.int64)
    t0_day = int(np.datetime64(T0_FULL, "D").astype(np.int64))
    Q = len(qdays)
    Wd.Qdays = qdays
    keys6 = ["nb", "last_bar", "fresh", "close", "ema50", "ema200", "sma50", "sma200", "st_sign"]
    T = {k: np.full((Q, N), np.nan) for k in keys6}
    T["nb"] = np.zeros((Q, N))
    T["fresh"] = np.zeros((Q, N), dtype=bool)
    stock_bars = {}
    og = {s: g for s, g in o.groupby("stock")}
    Wd.o_by_stock = og
    for si, s in enumerate(cols):
        g = og.get(s)
        if g is None:
            continue
        g = g.sort_values("date")
        dd = g["date"].values.astype("datetime64[D]").astype(np.int64)
        keep = (dd <= t0_day) | np.isin(dd, cal_days)         # F-AA-D15: after T0 only calendar sessions
        g = g[keep]
        sb = StockBars(g["date"].values.astype("datetime64[D]").astype(np.int64), g["close"].values.astype(float),
                       g["high"].values.astype(float), g["low"].values.astype(float))
        stock_bars[s] = sb
        for qi, qd in enumerate(qdays):
            r = sb.at(int(qd))
            if r is None:
                continue
            for k in keys6:
                T[k][qi, si] = r[k]
    Wd.T = T
    Wd.stock_bars = stock_bars
    fresh = T["fresh"].astype(bool)
    cl = np.where(fresh, T["close"], np.nan)
    Wd.close_used = cl
    P = {}
    with np.errstate(invalid="ignore"):
        P["I1"] = fresh & (T["nb"] >= 50) & (cl > T["ema50"])
        P["I2"] = fresh & (T["nb"] >= 200) & (cl > T["ema200"])
        P["I3"] = fresh & (T["nb"] >= 50) & (cl > T["sma50"])
        P["I4"] = fresh & (T["nb"] >= 200) & (cl > T["sma200"])
        P["I5"] = fresh & (T["st_sign"] == 1.0)
    for k in P:
        P[k] = np.nan_to_num(P[k]).astype(bool)
    Wd.PASS = P
    log(f"indicator tables built: {Q} dates x {N} stocks ({time.time() - t_start:.1f}s)")
    return Wd


# ======================================================================================
# simulation
# ======================================================================================
def basket_at(Wd, t):
    j = int(np.searchsorted(Wd.bk_eff, t, side="right")) - 1
    return int(Wd.bk_id[j])


def decision_state(Wd, win, ind, j):
    return win["state"][j]


def run_sim(Wd, win, target_fn, bps, share, L, always_trade=False, init_scale=None, record_trades=True):
    """target_fn(j, b) -> stock weight vector (len N). Returns dict(nav, trades, cost_paid)."""
    S, N = Wd.S, Wd.N
    t0 = win["t0"]
    C, F, gC, gF = Wd.C, Wd.F, Wd.gC, Wd.gF
    dec_idx = win["idx"]
    J = len(dec_idx)
    trade_idx = dec_idx + 1
    # events
    ev = set(int(trade_idx[j]) for j in range(1, J) if trade_idx[j] < S)
    if always_trade:
        if trade_idx[0] < S:
            ev.add(int(trade_idx[0]))
    ev |= set(int(k) for k in Wd.bk_eff if k > t0)
    events = sorted(ev)
    # initial position
    b0 = basket_at(Wd, t0)
    x0 = target_fn(0, b0)
    d0 = int(np.searchsorted(Wd.F_d18.index.values.astype("datetime64[D]"), Wd.avail[b0], side="left"))
    Fd = np.nan_to_num(Wd.F_d18.values[d0].astype(float), nan=0.0)
    w0 = Wd.Wn[b0]
    units = np.zeros(N)
    pos = w0 > 0
    units[pos] = w0[pos] / Fd[pos]
    v = float(C[t0] @ units)
    units = units / v
    sleeve_val = 0.0
    if init_scale is None:
        drop = ~(x0 > 0)
        sleeve_val = float((units[drop] * C[t0][drop]).sum())
        units[drop] = 0.0
    else:
        units = units * init_scale
        sleeve_val = 1.0 - init_scale
    ug = sleeve_val * share / gC[t0]
    uc = sleeve_val * (1.0 - share) / L[t0]
    last_x = x0
    nav = np.empty(S - t0)
    trades = []
    cost_paid = 0.0
    seg = t0
    cost_rate = bps / 2.0 / 10000.0
    for t in events:
        nav[seg - t0:t - t0] = C[seg:t] @ units + gC[seg:t] * ug + L[seg:t] * uc
        seg = t
        jf = int(np.searchsorted(trade_idx, t, side="right")) - 1
        if jf < 0:
            jf = 0
        b = basket_at(Wd, t)
        x = target_fn(jf, b)
        if always_trade or not np.array_equal(x, last_x):
            Ft = F[t]
            V = float(Ft @ units + gF[t] * ug + L[t] * uc)
            sx = float(x.sum())
            tv = x * V
            sl = (1.0 - sx) * V
            gt = sl * share
            ct = sl * (1.0 - share)
            traded = float(np.abs(tv - units * Ft).sum() + abs(gt - ug * gF[t]) + abs(ct - uc * L[t]))
            cost = traded * cost_rate
            sc = (V - cost) / V
            nu = np.zeros(N)
            m = x > 0
            nu[m] = tv[m] * sc / Ft[m]
            units = nu
            ug = gt * sc / gF[t]
            uc = ct * sc / L[t]
            cost_paid += cost
            if record_trades:
                navc = float(C[t] @ units + gC[t] * ug + L[t] * uc)
                trades.append(dict(idx=t, j=jf, b=b, x=x.copy(), sx=sx, V=V, traded=traded, cost=cost, nav_close_after=navc))
            last_x = x
    nav[seg - t0:] = C[seg:] @ units + gC[seg:] * ug + L[seg:] * uc
    return dict(nav=nav, trades=trades, cost_paid=cost_paid, ntrades=len(trades) if record_trades else None)


def nav_stats(nav):
    years = (len(nav) - 1) / 252.0
    end = float(nav[-1])
    cagr = end ** (1.0 / years) - 1.0
    peak = np.maximum.accumulate(nav)
    mdd = float((nav / peak - 1.0).min())
    return end, cagr, mdd


def strategy_target(Wd, win, ind):
    P = Wd.PASS[ind]
    qcols = np.array([Wd.qpos[d] for d in win["dates"]])
    Wn = Wd.Wn
    state = win["state"]

    def fn(j, b):
        w = Wn[b]
        if state[j] == 1:
            return w
        return w * (P[qcols[j]] & (w > 0))
    return fn


def hold_target(Wd):
    return lambda j, b: Wd.Wn[b]


def aa_switch_target(Wd, win):
    state = win["state"]

    def fn(j, b):
        return Wd.Wn[b] if state[j] == 1 else np.zeros(Wd.N)
    return fn


def mix_target(Wd, f):
    return lambda j, b: f * Wd.Wn[b]


def decision_k_n(Wd, win, ind, j):
    """n, k, kept index array of decision j on the basket in force at its trade session."""
    S = Wd.S
    ti = win["idx"][j] + 1
    t = int(ti if ti < S else win["idx"][j])
    b = basket_at(Wd, t)
    w = Wd.Wn[b]
    col = Wd.qpos[win["dates"][j]]
    m = (w > 0) & Wd.PASS[ind][col]
    return int((w > 0).sum()), int(m.sum()), np.flatnonzero(m), b


def mean_equity_share(Wd, win, ind):
    tot = 0.0
    J = len(win["idx"])
    for j in range(J):
        n, k, kept, b = decision_k_n(Wd, win, ind, j)
        tot += 1.0 if win["state"][j] == 1 else float(Wd.Wn[b][kept].sum())
    return tot / J


def null_target(Wd, win, ind, u, counter):
    P = Wd.PASS[ind]
    qcols = np.array([Wd.qpos[d] for d in win["dates"]])
    Wn, state, mem = Wd.Wn, win["state"], Wd.mem

    def fn(j, b):
        w = Wn[b]
        if state[j] == 1:
            return w
        m = mem[b]
        k = int(P[qcols[j]][m].sum())
        order = np.argsort(u[j, m], kind="stable")
        x = np.zeros(Wd.N)
        sel = m[order[:k]]
        x[sel] = w[sel]
        return x
    return fn


def check_null_k(Wd, win, ind, u):
    """Independent pass over EVERY decision: kept count == k on SELL, BUY target == whole basket. Returns (compared, failed)."""
    P = Wd.PASS[ind]
    qcols = np.array([Wd.qpos[d] for d in win["dates"]])
    comp = fail = 0
    for j in range(len(win["idx"])):
        n, k, kept, b = decision_k_n(Wd, win, ind, j)
        w = Wd.Wn[b]
        m = Wd.mem[b]
        if win["state"][j] == 1:
            comp += 1
            fail += 0 if np.array_equal(null_target(Wd, win, ind, u, None)(j, b), w) else 1
        else:
            comp += 1
            x = null_target(Wd, win, ind, u, None)(j, b)
            kk = int(P[qcols[j]][m].sum())
            fail += 0 if (int((x > 0).sum()) == min(kk, len(m)) and kk == k and np.array_equal(x[x > 0], w[x > 0])) else 1
    return comp, fail


# ======================================================================================
# evidence loading and comparison helpers
# ======================================================================================
def load_evidence(evdir):
    E = {}
    for nm in ["decisions", "indicators", "selections", "trades", "stats", "draws", "daily_nav", "g_engine"]:
        p = evdir / f"{nm}.csv"
        E[nm] = pd.read_csv(p) if p.exists() else None
    return E


def close_num(a, b, tol=TOL):
    if a is None or b is None:
        return False
    a = float(a)
    b = float(b)
    if np.isnan(a) and np.isnan(b):
        return True
    if np.isnan(a) or np.isnan(b):
        return False
    return abs(a - b) <= tol * max(abs(a), abs(b)) + ABS_FLOOR


class Chk:
    def __init__(self):
        self.d = {}

    def get(self, name):
        if name not in self.d:
            self.d[name] = dict(compared=0, failed=0, missing=0, first_fail=None, notes=[])
        return self.d[name]

    def ok(self, name, good, desc=None):
        c = self.get(name)
        c["compared"] += 1
        if not good:
            c["failed"] += 1
            if c["first_fail"] is None:
                c["first_fail"] = desc

    def miss(self, name, desc):
        c = self.get(name)
        c["missing"] += 1
        if c["first_fail"] is None:
            c["first_fail"] = "missing: " + str(desc)

    def vec(self, name, mine, ev, desc_fn, tol=TOL):
        """Vectorised relative comparison of two arrays."""
        mine = np.asarray(mine, dtype=float)
        ev = np.asarray(ev, dtype=float)
        c = self.get(name)
        both_nan = np.isnan(mine) & np.isnan(ev)
        one_nan = np.isnan(mine) ^ np.isnan(ev)
        with np.errstate(invalid="ignore"):
            diff = np.abs(mine - ev) > tol * np.maximum(np.abs(mine), np.abs(ev)) + ABS_FLOOR
        bad = (~both_nan) & (one_nan | diff)
        c["compared"] += int(len(mine))
        c["failed"] += int(bad.sum())
        if bad.any() and c["first_fail"] is None:
            i = int(np.flatnonzero(bad)[0])
            c["first_fail"] = desc_fn(i) + f": mine={mine[i]!r} evidence={ev[i]!r}"


def date_str(x):
    return str(pd.Timestamp(x).date())


# ======================================================================================
# the checks
# ======================================================================================
def ev_dec_window(Wd, name):
    return Wd.win["full"] if name == "full" else Wd.win["live"]


def compare_all(Wd, R, E, chk, log, selftest=False):
    full = Wd.win["full"]
    cal = Wd.cal
    S = Wd.S

    # ---- C-dec ----
    D = E["decisions"]
    J = len(full["idx"])
    chk.get("C-dec")
    if len(D) != J:
        chk.ok("C-dec", False, f"row count evidence {len(D)} != mine {J}")
    Dr = D.set_index("j")
    for j in range(J):
        if j not in Dr.index:
            chk.miss("C-dec", f"decision j={j}")
            continue
        r = Dr.loc[j]
        lab = {n: full["labels"][n][j] for n in full["labels"]}
        latest = max(lab.values())
        d = full["dates"][j]
        ti = int(full["idx"][j]) + 1
        mine = dict(decision_date=date_str(d), decision_idx=int(full["idx"][j]),
                    trade_date=(date_str(cal[ti]) if ti < S else None),
                    sign_Nifty100=full["signs"]["Nifty100"][j], sign_MC100=full["signs"]["MC100"][j], sign_SC100=full["signs"]["SC100"][j],
                    label_Nifty100=date_str(lab["Nifty100"]), label_MC100=date_str(lab["MC100"]), label_SC100=date_str(lab["SC100"]),
                    latest_label=date_str(latest), label_age_days=int((d - pd.Timestamp(latest)).days),
                    state=int(full["state"][j]), regime="BUY" if full["state"][j] == 1 else "SELL")
        for k_, v_ in mine.items():
            e = r[k_]
            if k_ == "trade_date":
                good = (v_ is None and (pd.isna(e))) or (v_ is not None and not pd.isna(e) and str(e) == v_)
            elif k_ in ("decision_idx", "label_age_days", "state"):
                good = (int(e) == v_)
            else:
                good = (str(e) == str(v_))
            chk.ok("C-dec", good, f"j={j} date={mine['decision_date']} col={k_}: mine={v_!r} evidence={e!r}")

    # ---- C-ind (evidence rows) ----
    I = E["indicators"]
    qpos = Wd.qpos
    colpos = {c: i for i, c in enumerate(Wd.cols)}
    T = Wd.T
    chk.get("C-ind")
    seen_pairs = set()
    ev_rows = len(I)
    mine_cols = {"close_used": Wd.close_used, "ema50": T["ema50"], "ema200": T["ema200"], "sma50": T["sma50"], "sma200": T["sma200"], "st_sign": T["st_sign"]}
    qi_l, si_l = [], []
    bad_lookup = 0
    for dstr, st_ in zip(I["decision_date"].values, I["stock"].values):
        d = pd.Timestamp(dstr)
        if d not in qpos or st_ not in colpos:
            bad_lookup += 1
            chk.ok("C-ind", False, f"decision_date={dstr} stock={st_} not in my table")
            qi_l.append(0)
            si_l.append(0)
            continue
        qi_l.append(qpos[d])
        si_l.append(colpos[st_])
        seen_pairs.add((qpos[d], colpos[st_]))
    qi = np.array(qi_l)
    si = np.array(si_l)
    desc = lambda i: f"decision_date={I['decision_date'].values[i]} stock={I['stock'].values[i]}"
    # valid
    chk.vec("C-ind", T["fresh"][qi, si].astype(float), I["valid"].astype(float).values, lambda i: desc(i) + " col=valid")
    for cn, arr in mine_cols.items():
        chk.vec("C-ind", arr[qi, si], I[cn].values, lambda i, cn=cn: desc(i) + f" col={cn}")
    for ind in INDS:
        chk.vec("C-ind", Wd.PASS[ind][qi, si].astype(float), I["pass_" + ind].astype(float).values, lambda i, ind=ind: desc(i) + f" col=pass_{ind}")
    # last_bar (extra column of the schema)
    chk.vec("C-ind", T["last_bar"][qi, si], pd.to_datetime(I["last_bar"]).values.astype("datetime64[D]").astype(np.int64).astype(float), lambda i: desc(i) + " col=last_bar")
    # weight at the decision's trade session
    wmine = []
    jmap = {d: j for j, d in enumerate(full["dates"])}
    for dstr, st_ in zip(I["decision_date"].values, I["stock"].values):
        d = pd.Timestamp(dstr)
        jd = jmap.get(d)
        if jd is None:
            wmine.append(np.nan)
            continue
        ti = full["idx"][jd] + 1
        t = int(ti if ti < S else full["idx"][jd])
        wmine.append(Wd.Wn[basket_at(Wd, t)][colpos[st_]])
    chk.vec("C-ind", np.array(wmine), I["weight"].values, lambda i: desc(i) + " col=weight")
    # completeness: stocks of the basket at the trade session with a fresh close (my reading of "valid")
    miss = 0
    first_miss = None
    for j, d in enumerate(full["dates"]):
        ti = full["idx"][j] + 1
        t = int(ti if ti < S else full["idx"][j])
        b = basket_at(Wd, t)
        for si_ in Wd.mem[b]:
            if T["fresh"][qpos[d], si_] and (qpos[d], si_) not in seen_pairs:
                miss += 1
                if first_miss is None:
                    first_miss = f"{date_str(d)} {Wd.cols[si_]}"
    c = chk.get("C-ind")
    c["compared"] += 1
    c["notes"].append(f"basket stocks with a fresh close on a decision date but no evidence row: {miss}" + (f" (first {first_miss})" if first_miss else ""))
    if miss:
        c["failed"] += 1
        if c["first_fail"] is None:
            c["first_fail"] = f"{miss} (decision, basket stock) pairs with a fresh close have no row in indicators.csv; first {first_miss}"

    # ---- C-ind-brute (my table vs straight-line recomputation on 300 random pairs, not restricted to a basket) ----
    rng = np.random.default_rng(20261106)
    chk.get("C-ind-brute")
    cal_days = cal.values.astype("datetime64[D]").astype(np.int64)
    t0_day = int(np.datetime64(T0_FULL, "D").astype(np.int64))
    nq = len(Wd.qdates)
    for _ in range(300):
        qi_ = int(rng.integers(0, nq))
        si_ = int(rng.integers(0, Wd.N))
        s = Wd.cols[si_]
        g = Wd.o_by_stock.get(s)
        if g is None:
            continue
        g = g.sort_values("date")
        br = brute_indicators(g, Wd.qdates[qi_], cal_days, t0_day)
        ds = f"{date_str(Wd.qdates[qi_])} {s}"
        chk.ok("C-ind-brute", bool(br["valid"]) == bool(T["fresh"][qi_, si_]), ds + " valid")
        for cn, arr in [("close", T["close"]), ("ema50", T["ema50"]), ("ema200", T["ema200"]), ("sma50", T["sma50"]), ("sma200", T["sma200"]), ("st_sign", T["st_sign"])]:
            chk.ok("C-ind-brute", close_num(br[cn], arr[qi_, si_]), f"{ds} {cn}: brute={br[cn]!r} table={arr[qi_, si_]!r}")

    # ---- C-sel ----
    Sel = E["selections"]
    chk.get("C-sel")
    nrows = {w: len(Sel[Sel["window"] == w]) for w in ["full", "live"]}
    for w in ["full", "live"]:
        win = Wd.win[w]
        if nrows[w] != 5 * len(win["idx"]):
            chk.ok("C-sel", False, f"window {w}: evidence rows {nrows[w]} != 5 x {len(win['idx'])}")
    for _, r in Sel.iterrows():
        w = r["window"]
        win = Wd.win.get(w)
        ind = r["indicator"]
        j = int(r["j"])
        if win is None or j >= len(win["idx"]) or ind not in INDS:
            chk.ok("C-sel", False, f"unknown row {w} {ind} {j}")
            continue
        n, k, kept, b = decision_k_n(Wd, win, ind, j)
        kept_set = set(Wd.cols[i] for i in kept)
        ev_set = set(str(r["kept"]).split(";")) if isinstance(r["kept"], str) else set()
        regime = "BUY" if win["state"][j] == 1 else "SELL"
        nontriv = bool(regime == "SELL" and 1 <= k < n)
        tag = f"{w} {ind} j={j} {date_str(win['dates'][j])}"
        chk.ok("C-sel", date_str(win["dates"][j]) == str(r["decision_date"]), tag + " decision_date")
        chk.ok("C-sel", regime == r["regime"], tag + f" regime mine={regime} ev={r['regime']}")
        chk.ok("C-sel", Wd.avail_str[b] == str(r["basket_eff"]), tag + f" basket_eff mine={Wd.avail_str[b]} ev={r['basket_eff']}")
        chk.ok("C-sel", n == int(r["n"]), tag + f" n mine={n} ev={r['n']}")
        chk.ok("C-sel", k == int(r["k"]), tag + f" k mine={k} ev={r['k']}")
        chk.ok("C-sel", kept_set == ev_set, tag + f" kept mine={sorted(kept_set)} ev={sorted(ev_set)}")
        chk.ok("C-sel", nontriv == bool(r["nontrivial"]), tag + f" nontrivial mine={nontriv} ev={r['nontrivial']}")

    # ---- C-pit ----
    chk.get("C-pit")
    for n_ in full["labels"]:
        for j in range(J):
            chk.ok("C-pit", pd.Timestamp(full["labels"][n_][j]) <= full["dates"][j], f"my label {n_} j={j}")
    for n_ in ["label_Nifty100", "label_MC100", "label_SC100"]:
        ok_ = pd.to_datetime(D[n_]) <= pd.to_datetime(D["decision_date"])
        for i in np.flatnonzero(~ok_.values):
            chk.ok("C-pit", False, f"evidence {n_} after decision row {i}")
        c = chk.get("C-pit")
        c["compared"] += int(len(D)) - int((~ok_).sum())
    # my own table: last bar used <= decision date
    lbm = np.where(np.isfinite(T["last_bar"]), T["last_bar"], -1e18)
    over = (lbm > Wd.Qdays[:, None]).sum()
    chk.ok("C-pit", over == 0, f"{int(over)} table cells use a bar after the query date")
    chk.get("C-pit")["compared"] += int((np.isfinite(T["last_bar"])).sum()) - 1
    # evidence indicator bars
    lbe = pd.to_datetime(I["last_bar"]).values.astype("datetime64[D]")
    dde = pd.to_datetime(I["decision_date"]).values.astype("datetime64[D]")
    badl = int((lbe > dde).sum())
    chk.ok("C-pit", badl == 0, f"{badl} evidence indicator rows with last_bar after decision_date")
    chk.get("C-pit")["compared"] += len(I) - 1
    # trades after decisions
    Tr = E["trades"]
    decdate = {j: full["dates"][j] for j in range(J)}
    bk_eff_dates = set(date_str(cal[k]) for k in Wd.bk_eff)
    exc = 0
    for dj, dt in zip(Tr["decision_j"].values, Tr["date"].values):
        good = pd.Timestamp(dt) > decdate[int(dj)]
        if not good:
            exc += 1
        chk.ok("C-pit", good or (dt in bk_eff_dates), f"trade on {dt} not after decision j={dj} ({date_str(decdate[int(dj)])})")
    chk.get("C-pit")["notes"].append(f"trade rows whose date is not after their decision date: {exc} (all must be basket-change sessions)")

    # ---- C-nav0, C-cost, C-trades, C-comp, extras ----
    DN = E["daily_nav"].copy()
    DN["cost_bps"] = DN["cost_bps"].astype(float)
    ST = E["stats"]
    chk.get("C-nav0")
    chk.get("C-cost")
    chk.get("C-comp")
    cal_str = np.array([date_str(x) for x in cal])
    cal_ix = {s: i for i, s in enumerate(cal_str)}

    def nav_compare(check, kind, ind, bps, nav):
        sub = DN[(DN["kind"] == kind) & (DN["cost_bps"] == bps)]
        if ind is not None:
            sub = sub[sub["indicator"] == ind]
        else:
            sub = sub[sub["indicator"].isna()]
        if len(sub) == 0:
            chk.miss(check, f"daily_nav {kind} {ind} {bps}")
            return
        pos = np.array([cal_ix.get(x, -1) for x in sub["date"].values])
        if (pos < 0).any() or len(sub) != len(nav):
            chk.ok(check, False, f"daily_nav {kind} {ind} {bps}: rows {len(sub)} vs mine {len(nav)} or unknown dates")
            return
        mine = nav[pos]
        chk.vec(check, mine, sub["nav"].values, lambda i: f"daily_nav {kind} {ind} cost {bps} date {sub['date'].values[i]}")

    def stats_row(kind, ind, window, sleeve, cash, bps):
        s = ST[(ST["kind"] == kind) & (ST["window"] == window) & (ST["sleeve"] == sleeve) & (ST["cash"] == cash) & (ST["cost_bps"].astype(float) == bps)]
        if ind is None:
            s = s[s["indicator"].isna()]
        else:
            s = s[s["indicator"] == ind]
        return s.iloc[0] if len(s) else None

    for key, res in R["strategy"].items():
        ind, window, sleeve, cash, bps = key
        end, cagr, mdd = nav_stats(res["nav"])
        r = stats_row("strategy", ind, window, sleeve, cash, bps)
        if bps == 0.0 and window == "full" and sleeve == "50_50" and cash == "lbes":
            chk.vec("C-nav0", [end], [r["end_nav"]] if r is not None else [np.nan], lambda i, k=key: f"stats end_nav {k}")
            nav_compare("C-nav0", "strategy", ind, bps, res["nav"])
        nm = "C-cost" if bps > 0 else None
        if nm:
            if r is None:
                chk.miss(nm, f"stats row {key}")
            else:
                chk.vec(nm, [end, cagr, mdd], [r["end_nav"], r["cagr"], r["max_dd"]], lambda i, k=key: f"stats {k} col {['end_nav', 'cagr', 'max_dd'][i]}")
                if window == "full" and sleeve == "50_50" and cash == "lbes":
                    nav_compare("C-cost", "strategy", ind, bps, res["nav"])
        # extras for every stats row (including 0 cost): max_dd/cagr at zero cost too, trades, cost_paid
        if r is not None:
            if bps == 0.0:
                chk.vec("C-nav0", [cagr, mdd], [r["cagr"], r["max_dd"]], lambda i, k=key: f"stats {k} col {['cagr', 'max_dd'][i]}")
            chk.vec("X-stats-trades-costpaid", [len(res["trades"]), res["cost_paid"]], [r["trades"], r["cost_paid"]], lambda i, k=key: f"stats {k} col {['trades', 'cost_paid'][i]}")
    for ind in INDS:
        r = stats_row("strategy", ind, "full", "50_50", "lbes", 0.0)
        if r is not None:
            chk.vec("X-mean-equity-share", [R["f"][ind]], [r["mean_equity_share"]], lambda i, ind=ind: f"strategy {ind} mean_equity_share")

    for key, res in R["hold"].items():
        end, cagr, mdd = nav_stats(res["nav"])
        r = stats_row("hold_parent", None, "full", "50_50", "lbes", key)
        if r is None:
            chk.miss("C-comp", f"hold_parent {key}")
        else:
            chk.vec("C-comp", [end, cagr, mdd], [r["end_nav"], r["cagr"], r["max_dd"]], lambda i, k=key: f"hold_parent cost {k} col {['end_nav', 'cagr', 'max_dd'][i]}")
            chk.vec("X-stats-trades-costpaid", [len(res["trades"]), res["cost_paid"]], [r["trades"], r["cost_paid"]], lambda i, k=key: f"hold_parent {k} col {['trades', 'cost_paid'][i]}")
        nav_compare("C-comp", "hold_parent", None, key, res["nav"])
    for key, res in R["aa"].items():
        end, cagr, mdd = nav_stats(res["nav"])
        r = stats_row("full_aa_switch", None, "full", "50_50", "lbes", key)
        if r is None:
            chk.miss("C-comp", f"full_aa_switch {key}")
        else:
            chk.vec("C-comp", [end, cagr, mdd], [r["end_nav"], r["cagr"], r["max_dd"]], lambda i, k=key: f"full_aa_switch cost {k} col {['end_nav', 'cagr', 'max_dd'][i]}")
            chk.vec("X-stats-trades-costpaid", [len(res["trades"]), res["cost_paid"]], [r["trades"], r["cost_paid"]], lambda i, k=key: f"full_aa_switch {k} col {['trades', 'cost_paid'][i]}")
        nav_compare("C-comp", "full_aa_switch", None, key, res["nav"])
    for key, res in R["mix"].items():
        ind, bps = key
        end, cagr, mdd = nav_stats(res["nav"])
        r = stats_row("constant_mix", ind, "full", "50_50", "lbes", bps)
        if r is None:
            chk.miss("C-comp", f"constant_mix {key}")
        else:
            chk.vec("C-comp", [end, cagr, mdd], [r["end_nav"], r["cagr"], r["max_dd"]], lambda i, k=key: f"constant_mix {k} col {['end_nav', 'cagr', 'max_dd'][i]}")
            chk.vec("X-stats-trades-costpaid", [len(res["trades"]), res["cost_paid"]], [r["trades"], r["cost_paid"]], lambda i, k=key: f"constant_mix {k} col {['trades', 'cost_paid'][i]}")
            chk.vec("X-mean-equity-share", [R["f"][ind]], [r["mean_equity_share"]], lambda i, k=key: f"constant_mix {k} mean_equity_share")
        nav_compare("C-comp", "constant_mix", ind, bps, res["nav"])

    # published NAV rebased (daily_nav rows of kind published_SCMO_0003)
    sub = DN[DN["kind"] == "published_SCMO_0003"]
    pubn = (Wd.pub / Wd.pub.iloc[0])
    pm = np.array([pubn.get(pd.Timestamp(x), np.nan) for x in sub["date"].values])
    chk.vec("X-published-nav", pm, sub["nav"].values, lambda i: f"published nav {sub['date'].values[i]}")

    # ---- C-trades ----
    chk.get("C-trades")
    nonconv = {}

    def trade_cmp(label, bps, res):
        sub = Tr[(Tr["indicator"] == label) & (Tr["cost_bps"].astype(float) == bps)]
        mine = res["trades"]
        tag = f"{label} cost {bps}"
        chk.ok("C-trades", len(sub) == len(mine), f"{tag}: trade count mine={len(mine)} evidence={len(sub)}")
        evd = {r_["date"]: r_ for _, r_ in sub.iterrows()}
        for tr in mine:
            dt = date_str(cal[tr["idx"]])
            r_ = evd.get(dt)
            if r_ is None:
                chk.miss("C-trades", f"{tag}: my trade on {dt} not in evidence")
                continue
            chk.ok("C-trades", int(r_["idx"]) == tr["idx"], f"{tag} {dt} idx mine={tr['idx']} ev={r_['idx']}")
            chk.ok("C-trades", int(r_["decision_j"]) == tr["j"], f"{tag} {dt} decision_j mine={tr['j']} ev={r_['decision_j']}")
            reg = "BUY" if (label == "hold_parent" or full["state"][tr["j"]] == 1) else "SELL"
            chk.ok("C-trades", r_["regime"] == reg, f"{tag} {dt} regime mine={reg} ev={r_['regime']}")
            chk.ok("C-trades", str(r_["basket_eff"]) == Wd.avail_str[tr["b"]], f"{tag} {dt} basket_eff mine={Wd.avail_str[tr['b']]} ev={r_['basket_eff']}")
            kept = set(Wd.cols[i] for i in np.flatnonzero(tr["x"] > 0))
            ev_set = set(str(r_["kept"]).split(";")) if isinstance(r_["kept"], str) else set()
            chk.ok("C-trades", kept == ev_set, f"{tag} {dt} kept mine={sorted(kept)} ev={sorted(ev_set)}")
            chk.ok("C-trades", len(kept) == int(r_["n_kept"]) and len(Wd.mem[tr["b"]]) == int(r_["n_basket"]), f"{tag} {dt} n_kept/n_basket mine={len(kept)}/{len(Wd.mem[tr['b']])} ev={r_['n_kept']}/{r_['n_basket']}")
            chk.vec("C-trades", [tr["sx"], tr["V"], tr["traded"], tr["cost"], tr["nav_close_after"]],
                    [r_["stock_weight"], r_["V"], r_["traded"], r_["cost"], r_["nav_close_after"]],
                    lambda i, tag=tag, dt=dt: f"{tag} {dt} col {['stock_weight', 'V', 'traded', 'cost', 'nav_close_after'][i]}")
        mine_dates = set(date_str(cal[tr["idx"]]) for tr in mine)
        for dt in evd:
            if dt not in mine_dates:
                chk.miss("C-trades", f"{tag}: evidence trade on {dt} not in mine")

    for key, res in R["strategy"].items():
        ind, window, sleeve, cash, bps = key
        if window == "full" and sleeve == "50_50" and cash == "lbes":
            trade_cmp(ind, bps, res)
    for bps, res in R["hold"].items():
        trade_cmp("hold_parent", bps, res)
    for bps, res in R["aa"].items():
        trade_cmp("full_aa_switch", bps, res)

    # ---- C-null ----
    chk.get("C-null")
    chk.get("C-null-k")
    Dw = E["draws"]
    idx_d = Dw.set_index(["indicator", "window", "sleeve", "cash", "cost_bps", "draw_id"]).sort_index()
    for key, (end, cagr, mdd, nt, cp) in R["null"].items():
        ind, window, sleeve, cash, bps, did = key
        try:
            r = idx_d.loc[(ind, window, sleeve, cash, bps, did)]
        except KeyError:
            chk.miss("C-null", key)
            continue
        chk.vec("C-null", [end, cagr, mdd], [r["end_nav"], r["cagr"], r["max_dd"]], lambda i, k=key: f"draw {k} col {['end_nav', 'cagr', 'max_dd'][i]}")
        chk.vec("X-null-trades-costpaid", [nt, cp], [r["trades"], r["cost_paid"]], lambda i, k=key: f"draw {k} col {['trades', 'cost_paid'][i]}")
    c = chk.get("C-null-k")
    c["compared"] = R["null_k"][0]
    c["failed"] = R["null_k"][1]
    if R["null_k"][1]:
        c["first_fail"] = R["null_k"][2]

    # ---- C-always-in ----
    chk.get("C-always-in")
    ai = R["always_in"]
    chk.ok("C-always-in", ai["cagr_gap_pp"] is not None and abs(ai["cagr_gap_pp"]) <= 0.25, f"CAGR gap {ai['cagr_gap_pp']:.4f} pp/yr beyond 0.25")
    for y, g in ai["yearly_gap_pp"].items():
        chk.ok("C-always-in", abs(g) <= 0.5, f"calendar year {y} gap {g:.4f} pp beyond 0.5")
    # also the always-in daily NAV equals the engine's hold_parent daily NAV at 0 cost
    nav_compare("C-always-in", "hold_parent", None, 0.0, R["hold"][0.0]["nav"])
    ge = E["g_engine"]
    if ge is not None and len(ge):
        chk.get("C-always-in")["notes"].append(f"engine g_engine.csv: gap {float(ge['cagr_gap_pp_yr'].iloc[0]):.4f} pp/yr, worst year {int(ge['worst_year'].iloc[0])} {float(ge['worst_year_gap_pp'].iloc[0]):.4f} pp; mine: gap {ai['cagr_gap_pp']:.4f}, worst year {ai['worst_year']} {ai['worst_year_gap_pp']:.4f}")
    return chk


def run_sims(Wd, log):
    R = dict(strategy={}, hold={}, aa={}, mix={}, null={}, f={})
    full, live = Wd.win["full"], Wd.win["live"]
    t = time.time()
    # strategies
    variants = [("full", "50_50", "lbes", c) for c in COSTS] + [("full", "gold100", "lbes", 20.8), ("full", "50_50", "liquidcase", 20.8), ("live", "50_50", "lbes", 20.8)]
    Lc = {"lbes": Wd.L_lbes, "liquidcase": Wd.L_liq}
    share = {"50_50": 0.5, "gold100": 1.0}
    for ind in INDS:
        for (window, sleeve, cash, bps) in variants:
            win = full if window == "full" else live
            R["strategy"][(ind, window, sleeve, cash, bps)] = run_sim(Wd, win, strategy_target(Wd, win, ind), bps, share[sleeve], Lc[cash])
        R["f"][ind] = mean_equity_share(Wd, full, ind)
    # comparators
    for c in COSTS:
        R["hold"][c] = run_sim(Wd, full, hold_target(Wd), c, 0.5, Wd.L_lbes)
        R["aa"][c] = run_sim(Wd, full, aa_switch_target(Wd, full), c, 0.5, Wd.L_lbes)
        for ind in INDS:
            f = R["f"][ind]
            R["mix"][(ind, c)] = run_sim(Wd, full, mix_target(Wd, f), c, 0.5, Wd.L_lbes, always_trade=True, init_scale=f)
    log(f"strategy / comparator simulations done ({time.time() - t:.1f}s)")
    # always-in vs the published NAV
    nav = R["hold"][0.0]["nav"]
    cal = Wd.cal
    k = int(np.searchsorted(cal.values, np.datetime64(D17_END), side="right"))
    mine = nav[:k]
    pubn = (Wd.pub / Wd.pub.iloc[0]).reindex(cal[:k]).values
    years = (k - 1) / 252.0
    cg_m = mine[-1] ** (1 / years) - 1
    cg_p = pubn[-1] ** (1 / years) - 1
    yrs = pd.DatetimeIndex(cal[:k]).year.values
    yg = {}
    for y in sorted(set(yrs)):
        last = np.flatnonzero(yrs == y)[-1]
        first = np.flatnonzero(yrs == y)[0]
        base_m = mine[first - 1] if first > 0 else mine[0]
        base_p = pubn[first - 1] if first > 0 else pubn[0]
        yg[int(y)] = float(((mine[last] / base_m) - (pubn[last] / base_p)) * 100.0)
    wy = max(yg, key=lambda y: abs(yg[y]))
    R["always_in"] = dict(cagr_gap_pp=float((cg_m - cg_p) * 100.0), mine_cagr=float(cg_m), pub_cagr=float(cg_p), yearly_gap_pp=yg, worst_year=int(wy), worst_year_gap_pp=float(yg[wy]), sessions=int(k))
    # null draws
    t = time.time()
    drawvar = [("full", "50_50", "lbes", c) for c in COSTS] + [("full", "50_50", "liquidcase", 20.8), ("full", "gold100", "lbes", 20.8), ("live", "50_50", "lbes", 20.8)]
    rs = np.random.default_rng(777)
    nk_comp = nk_fail = 0
    nk_first = None
    n_draw_runs = 0
    for ii, ind in enumerate(INDS, start=1):
        # draw ids per variant: 0..19 plus 20 random per variant
        ids_by_var = {v: list(range(20)) + [int(x) for x in rs.choice(np.arange(20, 2000), 20, replace=False)] for v in drawvar}
        needed = sorted(set(i for v in drawvar for i in ids_by_var[v]))
        for did in needed:
            u_by_win = {}
            for window in ("full", "live"):
                win = full if window == "full" else live
                u_by_win[window] = np.random.default_rng([4, ii, did]).random((len(win["idx"]), Wd.N))
            checked_win = set()
            for v in drawvar:
                if did not in ids_by_var[v]:
                    continue
                window, sleeve, cash, bps = v
                win = full if window == "full" else live
                u = u_by_win[window]
                res = run_sim(Wd, win, null_target(Wd, win, ind, u, None), bps, share[sleeve], Lc[cash])
                end, cagr, mdd = nav_stats(res["nav"])
                R["null"][(ind, window, sleeve, cash, bps, did)] = (end, cagr, mdd, len(res["trades"]), res["cost_paid"])
                n_draw_runs += 1
                if window not in checked_win:
                    checked_win.add(window)
                    c_, f_ = check_null_k(Wd, win, ind, u)
                    nk_comp += c_
                    nk_fail += f_
                    if f_ and nk_first is None:
                        nk_first = f"{ind} draw {did} window {window}"
    R["null_k"] = (nk_comp, nk_fail, nk_first)
    log(f"null draws reproduced: {n_draw_runs} simulations ({time.time() - t:.1f}s)")
    return R


# ======================================================================================
# diagnostics that never decide pass/fail (alternate readings)
# ======================================================================================
def st_alt_diag(Wd, E):
    """Re-derive I5's st_sign under the textbook branch (reading A) and count mismatches with the evidence rows."""
    global ST_READING
    keep_reading = ST_READING
    out = {}
    I = E["indicators"]
    colpos = {c: i for i, c in enumerate(Wd.cols)}
    sel = []
    for dstr, st_ in zip(I["decision_date"].values, I["stock"].values):
        sel.append((Wd.qpos[pd.Timestamp(dstr)], colpos[st_]))
    qdays = Wd.Qdays
    cal_days = Wd.cal.values.astype("datetime64[D]").astype(np.int64)
    t0_day = int(np.datetime64(T0_FULL, "D").astype(np.int64))
    for rd in ["A", "B"]:
        ST_READING = rd
        mism = 0
        cache = {}
        for (qi, si), ev in zip(sel, I["st_sign"].values):
            s = Wd.cols[si]
            if s not in cache:
                g = Wd.o_by_stock[s].sort_values("date")
                dd = g["date"].values.astype("datetime64[D]").astype(np.int64)
                g = g[(dd <= t0_day) | np.isin(dd, cal_days)]
                cache[s] = StockBars(g["date"].values.astype("datetime64[D]").astype(np.int64), g["close"].values.astype(float),
                                     g["high"].values.astype(float), g["low"].values.astype(float))
            r = cache[s].at(int(qdays[qi]))
            v = r["st_sign"] if r else np.nan
            if not close_num(v, ev):
                mism += 1
        out[rd] = mism
    ST_READING = keep_reading
    return out


# ======================================================================================
def corrupt_copy(evdir, dst):
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True)
    for nm in ["decisions", "indicators", "selections", "trades", "stats", "draws", "daily_nav", "g_engine"]:
        shutil.copy(evdir / f"{nm}.csv", dst / f"{nm}.csv")
    D = pd.read_csv(dst / "decisions.csv")
    rows = [10, 50, 100, 150, 200]
    for r in rows:
        D.loc[r, "state"] = 1 - int(D.loc[r, "state"])
        D.loc[r, "regime"] = "BUY" if D.loc[r, "regime"] == "SELL" else "SELL"
    D.to_csv(dst / "decisions.csv", index=False)
    N_ = pd.read_csv(dst / "daily_nav.csv")
    m = (N_["kind"] == "strategy") & (N_["indicator"] == "I1") & (N_["cost_bps"] == 0.0)
    N_.loc[m, "nav"] = N_.loc[m, "nav"] * 1.001
    N_.to_csv(dst / "daily_nav.csv", index=False)
    S_ = pd.read_csv(dst / "selections.csv")
    i = int(S_.index[(S_["window"] == "full") & (S_["indicator"] == "I2")][100])
    S_.loc[i, "k"] = int(S_.loc[i, "k"]) + 1
    S_.to_csv(dst / "selections.csv", index=False)
    return rows, i


def summarise(chk):
    return {k: dict(compared=v["compared"], failed=v["failed"], missing=v["missing"], first_fail=v["first_fail"], notes=v["notes"]) for k, v in chk.d.items()}


def print_table(C, title):
    print("\n" + title)
    print(f"{'check':26s} {'compared':>10s} {'failed':>8s} {'missing':>8s}")
    for k, v in C.items():
        print(f"{k:26s} {v['compared']:10d} {v['failed']:8d} {v['missing']:8d}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--evidence", default=str(AA / "tests" / "T04" / "evidence" / "headline"))
    ap.add_argument("--no-selftest", action="store_true")
    ap.add_argument("--no-json", action="store_true")
    ap.add_argument("--st-reading", choices=["A", "B"], default="A",
                    help="SuperTrend 'ST on FLB' branch: A = FLB if close >= FLB else FUB (the desk code, default); B = FLB if close < FUB else FUB (a misreading of the spec text, kept to show the disagreement)")
    args = ap.parse_args()
    global ST_READING
    ST_READING = args.st_reading
    evdir = Path(args.evidence)
    t_all = time.time()

    def log(m):
        print(f"[{time.time() - t_all:7.1f}s] {m}", flush=True)

    Wd = derive(log)
    R = run_sims(Wd, log)
    E = load_evidence(evdir)
    chk = compare_all(Wd, R, E, Chk(), log)
    C = summarise(chk)
    # diagnostics
    diag = {}
    try:
        diag["st_sign_mismatches_vs_evidence_rows"] = st_alt_diag(Wd, E)
    except Exception as ex:  # diagnostics never decide
        diag["st_sign_error"] = repr(ex)
    log(f"always-in: CAGR gap {R['always_in']['cagr_gap_pp']:+.4f} pp/yr, worst year {R['always_in']['worst_year']} {R['always_in']['worst_year_gap_pp']:+.4f} pp")
    log(f"diagnostic: I5 st_sign mismatches against evidence rows by SuperTrend branch reading: {diag.get('st_sign_mismatches_vs_evidence_rows')}")
    print_table(C, "REAL RUN")
    for k, v in C.items():
        if v["failed"] or v["missing"]:
            print(f"  first problem in {k}: {v['first_fail']}")
        for n_ in v["notes"]:
            print(f"  note {k}: {n_}")

    # self-test on a corrupted copy
    selftest = None
    if not args.no_selftest:
        cdir = SCRATCH / "corrupt_evidence"
        rows, krow = corrupt_copy(evdir, cdir)
        Ec = load_evidence(cdir)
        Cc = summarise(compare_all(Wd, R, Ec, Chk(), log))
        print_table(Cc, f"SELF-TEST: corrupted copy in {cdir} (5 decisions flipped at rows {rows}, I1 cost-0 NAV x 1.001, selections row {krow} k+1)")
        hit = {c: Cc[c]["failed"] + Cc[c]["missing"] for c in ["C-dec", "C-nav0", "C-sel"]}
        detected = all(v > 0 for v in hit.values())
        selftest = dict(dir=str(cdir), flipped_decision_rows=rows, selections_row_changed=krow, failures_in_targeted_checks=hit, detected=bool(detected))
        print(f"corrupted copy detected: {detected} {hit}")
        chk.ok("C-corrupt", detected, f"corrupted copy not detected: {hit}")
        C = summarise(chk)
    else:
        chk.get("C-corrupt")["compared"] = 0
        C = summarise(chk)

    all_ok = True
    for k, v in C.items():
        if v["compared"] == 0 or v["failed"] > 0 or v["missing"] > 0:
            if not (k == "C-corrupt" and args.no_selftest):
                all_ok = False
    required = ["C-dec", "C-ind", "C-ind-brute", "C-sel", "C-pit", "C-nav0", "C-cost", "C-trades", "C-null", "C-null-k", "C-comp", "C-always-in"]
    if not args.no_selftest:
        required.append("C-corrupt")
    for k in required:
        if k not in C or C[k]["compared"] == 0:
            all_ok = False
    out = dict(checks=C, always_in=R["always_in"], diagnostics=diag, selftest=selftest, exit_ok=bool(all_ok),
               readings=dict(
                   st_branch="reading A (default, desk code): in the 'ST on FLB' branch ST = FLB if close >= FLB else FUB; B = FLB if close < FUB else FUB was the first reading and disagrees on I5",
                   ema_seed="EMA at the N-th bar = mean of the first N closes, recursion from bar N+1",
                   valuation_ffill="stock valuation close = last close on D18 dates (all D18 dates, including non-calendar ones) forward-filled onto the calendar",
                   n_k_basket="n, k, kept of decision j measured on the basket in force at its trade session (decision session for the last decision)",
                   constant_mix="always trades at event sessions; initial stock holding = drifted basket scaled by f; sleeve (1-f)/2 each",
                   null_draw_ids="draws 0..19 plus 20 random ids (different per indicator and variant, seed 777)",
                   evidence_rows_valid="valid = a bar exists within 7 calendar days of the decision date"))
    if not args.no_json and Path(args.evidence).resolve() == (AA / "tests" / "T04" / "evidence" / "headline").resolve():
        (evdir / ("verify_t04.json" if ST_READING == "A" else "verify_t04_stB.json")).write_text(json.dumps(out, indent=1, default=str))
    log(f"exit_ok = {all_ok}")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
