# -*- coding: utf-8 -*-
"""
Deep study, part 5: robustness and statistical strength of the pair rule.

  a. Rolling 1 / 3 / 5-year windows from every weekly start (continuous NAVs
     sliced), pair against bh, sc100 and own, on SC100, blend, N100, MC100,
     N50 (cash) and SC100 / blend (50/50 from 2014). Windows ending by
     2021-10-29 are out of sample; the rest touch the in-sample period.
  b. Stationary block bootstrap (mean block 130 sessions, 2,000 draws, seed
     20260925) of paired daily returns, OOS, cash: CI of the CAGR difference.
  c. Circular-shift null: the joint N100+SC100 weekly signals shifted by
     k >= 26 weeks (wrapping inside 2006-01 -> 2021-10).
  d. Execution delay (0 / 1 / 2 / 4 extra weeks) and costs (0 / 20.8 / 50 /
     100 bps per switch).
  e. Supertrend settings: mul {1.5, 2, 2.5, 3} x ATR bars {5, 10}, recomputed
     from the frozen index OHLC and read on the Friday review grid.
  f. The family: other large-AND-small pairs, OR, N100 alone.

Writes evidence/why_n100sc100/deep/robust_*.csv.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

import segment_v2_data as D
from deep_core_common import DEEP, IS0, OOS_END, S0, S_GOLD, build, load, run_one
from supertrend import supertrend, to_weekly
from why_n100sc100 import cagr, mdd

END = pd.Timestamp("2026-08-21")


def part_rolling(N):
    rows = []
    specs = [(leg, "cash") for leg in ("SC100", "blend", "N100", "MC100", "N50")] + [("SC100", "50/50"), ("blend", "50/50")]
    for leg, sl in specs:
        cols = {ru: f"{leg}|{ru}|{sl}" for ru in ("pair", "triple", "sc100", "own", "bh") if f"{leg}|{ru}|{sl}" in N}
        X = N[list(cols.values())].dropna()
        idx = X.index
        V = X.to_numpy()
        starts = list(range(0, len(idx), 5))
        for H, lab in ((252, "1y"), (756, "3y"), (1260, "5y")):
            for s in starts:
                e = s + H
                if e >= len(idx):
                    break
                yrs = (idx[e] - idx[s]).days / 365.25
                seg = V[s:e + 1] / V[s]
                cg = seg[-1] ** (1 / yrs) - 1
                ddv = (seg / np.maximum.accumulate(seg, axis=0) - 1).min(axis=0)
                rec = {"leg": leg, "sleeve": sl, "horizon": lab, "start": idx[s], "end": idx[e],
                       "window": "oos" if idx[e] <= OOS_END else "touches in-sample"}
                for k, ru in enumerate(cols):
                    rec[f"{ru}_cagr"], rec[f"{ru}_dd"] = cg[k], ddv[k]
                rows.append(rec)
    Rw = pd.DataFrame(rows)
    Rw.to_parquet(DEEP / "robust_rolling_windows.parquet")
    summ = []
    for (leg, sl, hz, win), g in Rw.groupby(["leg", "sleeve", "horizon", "window"]):
        rec = {"leg": leg, "sleeve": sl, "horizon": hz, "window": win, "n_windows": len(g)}
        for other in ("bh", "sc100", "own"):
            if f"{other}_cagr" not in g or (other == "own" and leg in ("SC100", "blend")):
                continue
            d = g.pair_cagr - g[f"{other}_cagr"]
            rec[f"pair_cagr_gt_{other}"] = float((d > 0).mean())
            rec[f"pair_dd_shallower_{other}"] = float((g.pair_dd > g[f"{other}_dd"]).mean())
            cal_p = g.pair_cagr / g.pair_dd.abs()
            cal_o = g[f"{other}_cagr"] / g[f"{other}_dd"].abs()
            rec[f"pair_calmar_gt_{other}"] = float((cal_p > cal_o).mean())
            for q in (5, 25, 50, 75, 95):
                rec[f"pair_minus_{other}_p{q}"] = float(np.percentile(d, q))
        rec["pair_worst_dd_p5"] = float(np.percentile(g.pair_dd, 5))
        rec["bh_worst_dd_p5"] = float(np.percentile(g.bh_dd, 5))
        rec["pair_negative_cagr_share"] = float((g.pair_cagr < 0).mean())
        rec["bh_negative_cagr_share"] = float((g.bh_cagr < 0).mean())
        summ.append(rec)
    S = pd.DataFrame(summ)
    S.to_csv(DEEP / "robust_rolling_summary.csv", index=False)
    return S


def part_bootstrap(N):
    rng = np.random.default_rng(20260925)
    out = []
    for leg in ("SC100", "blend", "N100"):
        X = N[[f"{leg}|pair|cash", f"{leg}|bh|cash", f"{leg}|sc100|cash"]].loc[S0:OOS_END].pct_change().dropna().to_numpy()
        n, Dd, p = len(X), 2000, 1 / 130
        idx = np.empty((Dd, n), dtype=np.int64)
        idx[:, 0] = rng.integers(0, n, Dd)
        new = rng.random((Dd, n)) < p
        jump = rng.integers(0, n, (Dd, n))
        for t in range(1, n):
            idx[:, t] = np.where(new[:, t], jump[:, t], (idx[:, t - 1] + 1) % n)
        yrs = n / 252
        g = np.exp(np.log1p(X)[idx].sum(axis=1) / yrs) - 1       # (D, 3) CAGR per series
        for j, other in ((1, "bh"), (2, "sc100")):
            d = g[:, 0] - g[:, j]
            obs = (np.exp(np.log1p(X[:, 0]).sum() / yrs) - 1) - (np.exp(np.log1p(X[:, j]).sum() / yrs) - 1)
            out.append({"leg": leg, "vs": other, "observed_cagr_diff": obs,
                        "ci90_lo": np.percentile(d, 5), "ci90_hi": np.percentile(d, 95),
                        "ci95_lo": np.percentile(d, 2.5), "ci95_hi": np.percentile(d, 97.5),
                        "p_diff_gt_0": float((d > 0).mean())})
    B = pd.DataFrame(out)
    B.to_csv(DEEP / "robust_bootstrap.csv", index=False)
    return B


def part_shift(cal, r, gc, sg):
    grid = sg.loc[pd.Timestamp("2006-01-06"):OOS_END, ["N100", "SC100"]].dropna()
    n = len(grid)
    rows = []
    for k in range(0, n):
        if 0 < k < 26 or k > n - 26:
            continue
        sh = pd.DataFrame(np.roll(grid.to_numpy(), k, axis=0), index=grid.index, columns=grid.columns)
        dec = sh.N100 * sh.SC100
        for leg in ("SC100", "blend"):
            nav, _ = run_one(cal, r, gc, dec, leg, "cash", S0)
            nav = nav.loc[:OOS_END]
            rows.append({"k": k, "leg": leg, "cagr": cagr(nav), "max_dd": mdd(nav)})
    Sh = pd.DataFrame(rows)
    Sh.to_csv(DEEP / "robust_shift_null.csv", index=False)
    summ = []
    for leg, g in Sh.groupby("leg"):
        act = g[g.k == 0].iloc[0]
        nul = g[g.k != 0]
        summ.append({"leg": leg, "actual_cagr": act.cagr, "actual_max_dd": act.max_dd, "shifts": len(nul),
                     "null_median_cagr": nul.cagr.median(), "null_p95_cagr": nul.cagr.quantile(0.95),
                     "cagr_percentile": float((nul.cagr < act.cagr).mean()),
                     "null_median_dd": nul.max_dd.median(), "dd_percentile_shallower": float((nul.max_dd < act.max_dd).mean())})
    S = pd.DataFrame(summ)
    S.to_csv(DEEP / "robust_shift_summary.csv", index=False)
    return S


def part_delay_cost(cal, r, gc, sg):
    rows = []
    base = sg.N100 * sg.SC100
    for leg in ("SC100", "blend"):
        for dly in (0, 1, 2, 4):
            nav, _ = run_one(cal, r, gc, base.dropna().shift(dly).dropna(), leg, "cash", S0)
            nav = nav.loc[:OOS_END]
            rows.append({"leg": leg, "test": f"delay {dly}w", "cagr": cagr(nav), "max_dd": mdd(nav)})
        for c in (0.0, 20.8, 50.0, 100.0):
            nav, _ = run_one(cal, r, gc, base, leg, "cash", S0, cost=c)
            nav = nav.loc[:OOS_END]
            rows.append({"leg": leg, "test": f"cost {c:g} bps", "cagr": cagr(nav), "max_dd": mdd(nav)})
        for dly in (0, 1, 2, 4):
            nav, _ = run_one(cal, r, gc, sg.SC100.dropna().shift(dly).dropna(), leg, "cash", S0)
            nav = nav.loc[:OOS_END]
            rows.append({"leg": leg, "test": f"sc100 only, delay {dly}w", "cagr": cagr(nav), "max_dd": mdd(nav)})
    X = pd.DataFrame(rows)
    X.to_csv(DEEP / "robust_delay_cost.csv", index=False)
    return X


def on_reviews(sig, reviews):
    s = sig.dropna()
    out = s.reindex(reviews.union(s.index)).ffill().reindex(reviews)
    return out[out.index >= s.index[0]]


def part_settings(cal, r, gc, sg):
    xl = D.FROZEN_DIR / "Data" / "indices_ohlcv.xlsx"
    wk = {}
    for k, sh in (("N100", "Nifty100"), ("SC100", "SC100")):
        d = pd.read_excel(xl, sheet_name=sh)
        d["date"] = pd.to_datetime(d["date"])
        d = d.set_index("date").sort_index()
        d = d[~d.index.duplicated()][["open", "high", "low", "close"]].astype(float)
        d["volume"] = 0.0
        wk[k] = to_weekly(d)
    rv = sg.index
    rows = []
    for mul in (1.5, 2.0, 2.5, 3.0):
        for days in (5, 10):
            s = {k: on_reviews(supertrend(w, mul=mul, days=days)["signal"], rv) for k, w in wk.items()}
            match = {k: float((s[k].loc["2007":"2021-10-29"] == sg[k].loc["2007":"2021-10-29"]).mean()) for k in s}
            for rn, dec in (("pair", s["N100"] * s["SC100"]), ("sc100", s["SC100"]), ("N100 only", s["N100"])):
                for leg in ("SC100", "blend"):
                    nav, w = run_one(cal, r, gc, dec, leg, "cash", S0)
                    nav = nav.loc[:OOS_END]
                    rows.append({"mul": mul, "days": days, "rule": rn, "leg": leg, "cagr": cagr(nav), "max_dd": mdd(nav),
                                 "time_in_equity": float(w.loc[:OOS_END].mean()),
                                 "switches": int((dec.loc[S0:OOS_END].diff().abs() > 0).sum()),
                                 "N100_match_master": match["N100"], "SC100_match_master": match["SC100"]})
    X = pd.DataFrame(rows)
    X.to_csv(DEEP / "robust_settings.csv", index=False)
    return X


def part_family(cal, r, gc, sg):
    fam = {"N100 AND SC100": sg.N100 * sg.SC100, "N50 AND SC100": sg.N50 * sg.SC100, "MC100 AND SC100": sg.MC100 * sg.SC100,
           "N100 AND MC100": sg.N100 * sg.MC100, "N100 OR SC100": ((sg.N100 + sg.SC100) > 0).astype(float).where(sg[["N100", "SC100"]].notna().all(axis=1)),
           "N100 only": sg.N100, "SC100 only": sg.SC100, "MC100 only": sg.MC100,
           "N100 AND SC250 (2019+)": sg.N100 * sg.SC250}
    rows = []
    for rn, dec in fam.items():
        for leg in ("SC100", "blend", "N100"):
            st = pd.Timestamp("2019-03-01") if "2019" in rn else S0
            nav, w = run_one(cal, r, gc, dec, leg, "cash", st)
            for per, a, b in (("oos", st, OOS_END), ("in-sample", IS0, END)):
                x = nav.loc[a:b]
                rows.append({"rule": rn, "leg": leg, "period": per, "start": x.index[0].date(), "cagr": cagr(x), "max_dd": mdd(x),
                             "time_in_equity": float(w.loc[a:b].mean())})
    X = pd.DataFrame(rows)
    X.to_csv(DEEP / "robust_family.csv", index=False)
    return X


def main():
    N, W = build()
    cal, px, r, gc, sg = load()
    pd.set_option("display.width", 260); pd.set_option("display.max_columns", 40)
    S = part_rolling(N)
    print(S.round(3).to_string(index=False))
    B = part_bootstrap(N)
    print(B.round(4).to_string(index=False))
    X = part_delay_cost(cal, r, gc, sg)
    print(X.round(4).to_string(index=False))
    Se = part_settings(cal, r, gc, sg)
    print(Se.round(4).to_string(index=False))
    F = part_family(cal, r, gc, sg)
    print(F.round(4).to_string(index=False))
    Sh = part_shift(cal, r, gc, sg)
    print(Sh.round(4).to_string(index=False))


if __name__ == "__main__":
    main()
