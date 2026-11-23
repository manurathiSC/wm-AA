# -*- coding: utf-8 -*-
"""Rebuild every T11 NAV (hold the parent, Part A, Part B at 0 / 20.8 / 50 bps) from tests/T11/evidence/backcalc/ ALONE.

Imports nothing from the engine. Steps (the same steps a hand calculation follows; see evidence/backcalc/README.md):
  1. prices: corrected = raw x correction_factor; OHLC4 = (O+H+L+C)/4 (the close if O/H/L blank); close_used = close carried forward;
     fill_used = OHLC4 where the stock has a bar, else close_used. GOLDBEES: de-spiked OHLC4 from the raw bar and the MCX range; a session without its own
     bar uses the previous close for both. Each is checked against the exported "used" columns.
  2. the rule: initial units at T0, then trades on the session after each decision whose state (or, when out, gold weight) changed, and basket changes
     while in; trade arithmetic V -> targets -> traded -> cost -> scale k -> new units.
  3. daily NAV = sum(units x close_used) + GOLDBEES units x close + LBES units x level; compared with evidence/headline/daily_nav.csv, stats.csv and the
     parent NAV file, and with the pack's own holdings_units.csv.

    python tests/T11/backcalc_verify.py        (from AA/)
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd

AA = Path(__file__).resolve().parents[2]
PK = AA / "tests" / "T11" / "evidence" / "backcalc"
HEAD = AA / "tests" / "T11" / "evidence" / "headline"
TOL = 1e-12
fails = []


def check(name, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'} {name} {detail}")
    if not ok:
        fails.append(name)


def rel(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    return float(np.max(np.abs(a - b) / np.maximum(np.abs(b), 1e-300))) if len(a) else 0.0


def gold_fill(g: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    band = (g["mcx_high"] - g["mcx_low"]) / g["mcx_close"] + 0.005
    lo, hi = g["gb_close"] * (1 - band), g["gb_close"] * (1 + band)
    has = band.notna()
    o = g["gb_open"].where(~has, g["gb_open"].clip(lower=lo, upper=hi))
    h = g["gb_high"].where(~has, g["gb_high"].clip(upper=hi))
    l_ = g["gb_low"].where(~has, g["gb_low"].clip(lower=lo))
    h = np.maximum(h, np.maximum(o, g["gb_close"]))
    l_ = np.minimum(l_, np.minimum(o, g["gb_close"]))
    fill = (o + h + l_ + g["gb_close"]) / 4
    close = g["gb_close"].ffill()
    return close.values, fill.fillna(close).values


def simulate(T, C, P, G, GF, L, stocks, baskets, wts, dec, e, gw, cost_bps):
    sidx = {s: k for k, s in enumerate(stocks)}
    W = np.zeros((len(baskets), len(stocks)))
    for r in wts.itertuples():
        W[r.basket_no, sidx[r.stock]] = r.weight
    bsess = baskets.sort_values("basket_no")["idx"].values
    basket_at = np.array([int(np.flatnonzero(bsess <= t)[-1]) for t in range(T)])
    bevents = {int(i) for i in bsess if 0 < i < T}
    ow = cost_bps / 2e4
    di = dec["decision_idx"].values
    # initial position at T0's close (free): basket 0 bought at T0's fill, scaled to NAV 1 at T0's close
    w0 = W[0]
    u = np.where(w0 > 0, w0 / np.where(P[0] > 0, P[0], 1), 0.0)
    u = u / float((u * C[0]).sum()) * e[0]
    gu = (1 - e[0]) * gw[0] / G[0]
    cu = (1 - e[0]) * (1 - gw[0]) / L[0]
    tgt = {}
    for j in range(1, len(di)):
        tr = int(di[j]) + 1
        if tr < T and (e[j] != e[j - 1] or (e[j] < 1 and gw[j] != gw[j - 1])):
            tgt[tr] = (e[j], gw[j])
    nav = np.empty(T)
    a, ecur, gcur = 0, e[0], gw[0]
    log = []
    for t in sorted(set(tgt) | bevents):
        nav[a:t] = C[a:t] @ u + G[a:t] * gu + L[a:t] * cu
        a = t
        if t in tgt or (t in bevents and ecur > 0):
            en, gn = tgt.get(t, (ecur, gcur))
            w = W[basket_at[t]]
            V = float(u @ P[t] + gu * GF[t] + cu * L[t])
            Te, Tg, Tc = en * V * w, (1 - en) * gn * V, (1 - en) * (1 - gn) * V
            traded = float(np.abs(Te - u * P[t]).sum() + abs(Tg - gu * GF[t]) + abs(Tc - cu * L[t]))
            cost = ow * traded
            k = (V - cost) / V
            u = np.where(Te > 0, k * Te / np.where(P[t] > 0, P[t], 1), 0.0)
            gu, cu = k * Tg / GF[t], k * Tc / L[t]
            ecur, gcur = en, gn
            log.append((t, V, traded, cost))
    nav[a:T] = C[a:T] @ u + G[a:T] * gu + L[a:T] * cu
    return nav, log


def stats(nav):
    yrs = (len(nav) - 1) / 252
    dd = nav / np.maximum.accumulate(nav) - 1
    r = nav[1:] / nav[:-1] - 1
    return {"end_nav": nav[-1], "cagr": nav[-1] ** (1 / yrs) - 1, "max_dd": dd.min(), "vol": r.std(ddof=1) * math.sqrt(252)}


def main():
    sp = pd.read_csv(PK / "stock_prices_long.csv")
    sg = pd.read_csv(PK / "sessions_gold_cash.csv")
    bas = pd.read_csv(PK / "baskets.csv")
    wts = pd.read_csv(PK / "basket_weights.csv")
    dec = pd.read_csv(PK / "decisions.csv")
    hold = pd.read_csv(PK / "holdings_units.csv")
    trs = pd.read_csv(PK / "trades_summary.csv")
    hd = pd.read_csv(HEAD / "daily_nav.csv")
    hs = pd.read_csv(HEAD / "stats.csv")
    pn = pd.read_csv(HEAD / "parent_nav_2014-09-01_2019-01-02.csv")
    for p in sorted(sp["book"].unique()):
        print(p)
        d = sp[sp["book"] == p]
        # 1. prices
        corr = d[["open_raw", "high_raw", "low_raw", "close_raw"]].mul(d["correction_factor"], axis=0).values
        check("corrected = raw x factor", np.allclose(corr, d[["open", "high", "low", "close"]].values, rtol=1e-15, atol=0, equal_nan=True))
        o4 = ((d["open"] + d["high"] + d["low"] + d["close"]) / 4).fillna(d["close"])
        check("ohlc4 recomputed", np.allclose(o4, d["ohlc4"], rtol=1e-15, atol=0, equal_nan=True))
        C = d.pivot(index="idx", columns="stock", values="close")
        seed = d.pivot(index="idx", columns="stock", values="close_used").iloc[0]
        n_seed = int((C.iloc[0].isna() & (seed > 0)).sum())
        C.iloc[0] = C.iloc[0].fillna(seed)                         # a stock without a bar on T0: its last close before T0 (from D18, outside this pack)
        C = C.ffill().fillna(0.0)
        P = d.pivot(index="idx", columns="stock", values="ohlc4").fillna(C)
        check("close_used = close carried forward", rel(C.values[C.values > 0], d.pivot(index="idx", columns="stock", values="close_used").values[C.values > 0]) == 0,
              f"(stocks seeded from before T0: {n_seed})")
        check("fill_used = OHLC4, else close_used", np.array_equal(P.values, d.pivot(index="idx", columns="stock", values="fill_used").values))
        stocks = list(C.columns)
        g = sg[sg["book"] == p].sort_values("idx")
        G, GF = gold_fill(g)
        check("GOLDBEES close / de-spiked fill recomputed", np.array_equal(G, g["goldbees_close_used"].values) and np.array_equal(GF, g["goldbees_fill_used"].values))
        L = g["lbes_level_used"].values
        T = len(g)
        bp, wp, dp = bas[bas["book"] == p], wts[wts["book"] == p], dec[dec["book"] == p].sort_values("j")
        check("basket weights sum to 1", bool(np.allclose(wp.groupby("basket_no")["weight"].sum(), 1, rtol=0, atol=1e-12)))
        check("weight = raw_weight / raw_weight_sum", np.allclose(wp["weight"], wp["raw_weight"] / wp["raw_weight_sum"], rtol=1e-12, atol=0))
        s = dp["state"].values.astype(float)
        gwr = np.where(dp["g"].values == 1, 0.8, 0.2)
        for run in ("hold_parent", "strategy_fixed50", "strategy"):
            for cost in (0.0, 20.8, 50.0):
                e = np.ones(len(s)) if run == "hold_parent" else s
                gw = gwr if run == "strategy" else np.full(len(s), 0.5)
                nav, log = simulate(T, C.values, P.values, G, GF, L, stocks, bp, wp, dp, e, gw, cost)
                h = hd[(hd["book"] == p) & (hd["run"] == run) & (hd["cost_bps"] == cost)].sort_values("date")
                ts = trs[(trs["book"] == p) & (trs["run"] == run) & (trs["cost_bps"] == cost)].sort_values("idx")
                ok_tr = len(ts) == len(log) and rel([x[1] for x in log], ts["V_at_fill"]) < TOL and rel([x[3] for x in log], ts["cost"].replace(0, np.nan).fillna(0)) < TOL if cost else len(ts) == len(log)
                st, hst = stats(nav), hs[(hs["book"] == p) & (hs["window"] == "full") & (hs["cash"] == "lbes") & (hs["cost_bps"] == cost) & (hs["kind"] == run)].iloc[0]
                ok_st = all(abs(st[k] - hst[k]) <= 1e-12 * max(1, abs(hst[k])) for k in st)
                check(f"{run:17s} {cost:>4} bps: NAV vs headline daily_nav.csv", rel(nav, h["nav"].values) < TOL and ok_tr and ok_st,
                      f"max rel {rel(nav, h['nav'].values):.1e}; trades {len(log)}; end NAV {nav[-1]:.6f}; CAGR {st['cagr']:.4%}; max DD {st['max_dd']:.2%}")
        # the pack's holdings reproduce its NAV: hold the parent at 0 bps, every interval
        hp = hold[(hold["book"] == p) & (hold["run"] == "hold_parent") & (hold["cost_bps"] == 0.0)]
        nav_h = np.zeros(T)
        for r in hp.itertuples():
            a, b = int(r.from_idx), int(g.index[g["date"] == r.to_date][0] - g.index[0]) + 1
            nav_h[a:b] += r.units * C[r.instrument].values[a:b]
        h0 = hd[(hd["book"] == p) & (hd["run"] == "hold_parent") & (hd["cost_bps"] == 0.0)].sort_values("date")["nav"].values
        check("holdings_units.csv x close_used = hold_parent 0 bps NAV", rel(nav_h, h0) < TOL, f"max rel {rel(nav_h, h0):.1e}")
        pp = pn[pn["book"] == p]
        check("parent NAV file columns = rebuilt runs", rel(pp["hold_parent_0bps"], h0) < TOL)
    print(f"\n{len(fails)} failures" if fails else "\nall checks pass: every T11 NAV series is reproduced from evidence/backcalc alone")
    raise SystemExit(1 if fails else 0)


if __name__ == "__main__":
    main()
