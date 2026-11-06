# -*- coding: utf-8 -*-
"""
Part 5: correlation structure of N100 and SC100, and whether the pair adds
more when the two decouple.

Weekly returns: Friday closes (resample W-FRI last) of the daily index closes.
  corr52  = rolling 52-week Pearson correlation of weekly N100 and SC100 returns
  disp    = |r_SC100 - r_N100| weekly, and disp52 = rolling 52-week std of
            (r_SC100 - r_N100), annualised (x sqrt 52)
  volN52  = rolling 52-week N100 volatility (annualised); vol_ratio52 =
            SC100 / N100 52-week volatility
Both are known at the close of week R, i.e. ex ante for the decision dated R.

The pair's added value per week: the engine's daily log excess (SC100 and
blend equity, cash sleeve, one run 2007-07-02 -> 2026-08-21), pair vs sc100
and pair vs bh, bucketed by the review whose decision governs each day (the
first earning session of review R is two sessions after R).

Regimes: terciles of corr52 and of disp52, with cut points from the OOS weeks
(2007-07 -> 2021-10) and applied unchanged to the in-sample weeks. Also a
yearly table and Spearman correlations across years.

Outputs: mechanism_corr_weekly.csv, mechanism_corr_regimes.csv,
         mechanism_corr_yearly.csv
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

import deep_mechanism_data as M

cal, sg, lv, gc = M.load()
wk_px = lv[["N100", "SC100"]].dropna().resample("W-FRI").last()
wr = wk_px.pct_change().dropna()
corr52 = wr["N100"].rolling(52, min_periods=52).corr(wr["SC100"])
spread = wr["SC100"] - wr["N100"]
disp52 = spread.rolling(52, min_periods=52).std() * np.sqrt(52)
beta52 = wr["SC100"].rolling(52).cov(wr["N100"]) / wr["N100"].rolling(52).var()
vol_ratio52 = wr["SC100"].rolling(52).std() / wr["N100"].rolling(52).std()
volN52 = wr["N100"].rolling(52, min_periods=52).std() * np.sqrt(52)

# ── engine runs and daily log excess ─────────────────────────────────────────
a, b = M.OOS_START, M.END
c = M.window(cal, a, b)
s = M.sig_window(sg, a, b, ["N100", "SC100", "MC100"])
r_sl = M.sleeve_returns(gc, c, "cash")
req = M.equity_returns(lv, c)
ex = {}
for ek in ("SC100", "blend"):
    f = {rn: M.sim(M.decisions(s, rn), req[ek], r_sl, c) for rn in ("bh", "sc100", "pair")}
    ln = {k: np.log1p(v["net"]) for k, v in f.items()}
    ex[f"{ek}_pair_vs_sc100"] = ln["pair"] - ln["sc100"]
    ex[f"{ek}_pair_vs_bh"] = ln["pair"] - ln["bh"]
    ex[f"{ek}_sc100_vs_bh"] = ln["sc100"] - ln["bh"]
ex = pd.DataFrame(ex, index=c)

# governing review for each day: review R governs from session j+1 (j = trade session index)
rv = s.index
first_earn = pd.Series({r: c[min(c.searchsorted(r, side="right") + 1, len(c) - 1)] for r in rv})
gov = pd.Series(np.nan, index=c, dtype="object")
lab = pd.Series(pd.NaT, index=c)
for r, d in first_earn.items():
    lab.loc[d] = r
lab = lab.ffill()
exw = ex.groupby(lab).sum()
exw.index.name = "review"

W = pd.DataFrame(index=rv)
W["N100"], W["SC100"] = s["N100"], s["SC100"]
W["state"] = np.select([(W.N100 == 1) & (W.SC100 == 1), (W.N100 == 0) & (W.SC100 == 1),
                        (W.N100 == 1) & (W.SC100 == 0)], ["both BUY", "SC-only BUY", "N-only BUY"], "both SELL")
# weekly stats known at R: take the W-FRI week ending on or before R
def asof(x):
    return x.reindex(x.index.union(rv)).ffill().reindex(rv)
W["corr52"], W["disp52"] = asof(corr52), asof(disp52)
W["beta52"], W["vol_ratio52"] = asof(beta52), asof(vol_ratio52)
W["volN52"] = asof(volN52)
W["abs_spread_w"] = asof(spread.abs())
W = W.join(exw, how="left")
W = W[(W.index >= a - pd.Timedelta(days=7)) & (W.index <= b)]
W["sample"] = np.where(W.index >= M.IS_START, "IS", "OOS")
W.to_csv(M.OUT / "mechanism_corr_weekly.csv")

# ── regimes ──────────────────────────────────────────────────────────────────
oos = W[W["sample"] == "OOS"]
rows = []
for var in ("corr52", "disp52", "volN52", "vol_ratio52"):
    q = oos[var].quantile([1 / 3, 2 / 3]).to_numpy()
    W[f"{var}_tercile"] = pd.cut(W[var], [-np.inf, q[0], q[1], np.inf], labels=["low", "mid", "high"])
    for samp in ("OOS", "IS"):
        x = W[W["sample"] == samp]
        for t_, g in x.groupby(f"{var}_tercile", observed=True):
            yrs = len(g) / 52.18
            r = {"variable": var, "sample": samp, "tercile": t_, "cut_low": q[0], "cut_high": q[1],
                 "weeks": len(g), "years_equiv": yrs, "var_mean": float(g[var].mean()),
                 "share_SC_only": float((g.state == "SC-only BUY").mean()),
                 "share_N_only": float((g.state == "N-only BUY").mean()),
                 "share_disagree": float(g.state.isin(["SC-only BUY", "N-only BUY"]).mean()),
                 "share_both_BUY": float((g.state == "both BUY").mean())}
            for k in ex.columns:
                r[f"{k}_pp_yr"] = float(100 * g[k].sum() / yrs)
            # SC100 return in the SC-only weeks of this regime (what the pair skips)
            rows.append(r)
reg = pd.DataFrame(rows)
reg.to_csv(M.OUT / "mechanism_corr_regimes.csv", index=False)

# ── yearly ───────────────────────────────────────────────────────────────────
yr = []
for y, g in W.groupby(W.index.year):
    yr.append({"year": int(y), "sample": "OOS" if y <= 2020 else ("mixed" if y == 2021 else "IS"),
               "corr52_mean": float(g.corr52.mean()), "disp52_mean": float(g.disp52.mean()),
               "weekly_corr_in_year": float(wr.loc[str(y)].corr().iloc[0, 1]),
               "share_disagree": float(g.state.isin(["SC-only BUY", "N-only BUY"]).mean()),
               "share_SC_only": float((g.state == "SC-only BUY").mean()),
               **{f"{k}_pp": float(100 * g[k].sum()) for k in ex.columns}})
yr = pd.DataFrame(yr)
yr.to_csv(M.OUT / "mechanism_corr_yearly.csv", index=False)
yo = yr[yr["sample"] == "OOS"]
sp = []
for xv in ("weekly_corr_in_year", "disp52_mean", "share_disagree"):
    for yv in ("SC100_pair_vs_sc100_pp", "SC100_pair_vs_bh_pp", "blend_pair_vs_sc100_pp"):
        rho, p = spearmanr(yo[xv], yo[yv])
        sp.append({"x": xv, "y": yv, "years": len(yo), "spearman": rho, "p": p, "sample": "OOS 2007-2020"})
# weekly-level: does lagged corr predict the next week's pair-vs-sc100 excess?
for samp in ("OOS",):
    x = W[(W["sample"] == samp)].dropna(subset=["corr52", "SC100_pair_vs_sc100"])
    rho, p = spearmanr(x["corr52"], x["SC100_pair_vs_sc100"])
    sp.append({"x": "corr52 (weekly)", "y": "SC100_pair_vs_sc100 next week", "years": len(x), "spearman": rho,
               "p": p, "sample": samp + " weeks (overlap-free, but autocorrelated regressor)"})
    xs = x[x.state == "SC-only BUY"]
    rho, p = spearmanr(xs["corr52"], xs["SC100_pair_vs_sc100"])
    sp.append({"x": "corr52 in SC-only weeks", "y": "SC100_pair_vs_sc100 next week", "years": len(xs),
               "spearman": rho, "p": p, "sample": samp})
pd.DataFrame(sp).to_csv(M.OUT / "mechanism_corr_spearman.csv", index=False)

# overall correlation structure
summ = {"corr_weekly_OOS": float(wr.loc["2007-07":"2021-10"].corr().iloc[0, 1]),
        "corr_weekly_IS": float(wr.loc["2021-11":"2026-08"].corr().iloc[0, 1]),
        "corr52_min": float(corr52.loc["2007":].min()), "corr52_min_date": str(corr52.loc["2007":].idxmin().date()),
        "corr52_max": float(corr52.loc["2007":].max()), "corr52_median": float(corr52.loc["2007":].median()),
        "beta_OOS": float(wr.loc["2007-07":"2021-10"].cov().iloc[0, 1] / wr.loc["2007-07":"2021-10", "N100"].var()),
        "vol_SC100_OOS": float(wr.loc["2007-07":"2021-10", "SC100"].std() * np.sqrt(52)),
        "vol_N100_OOS": float(wr.loc["2007-07":"2021-10", "N100"].std() * np.sqrt(52))}
pd.Series(summ).to_csv(M.OUT / "mechanism_corr_overall.csv", header=["value"])

pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 40)
print(pd.Series(summ))
print(reg.round(3).to_string(index=False))
print(yr.round(3).to_string(index=False))
print(pd.DataFrame(sp).round(3).to_string(index=False))
# mean corr52 by state (OOS)
print(W[W["sample"] == "OOS"].groupby("state")[["corr52", "disp52", "volN52", "abs_spread_w"]].mean().round(3))
print("corr52 vs volN52 (OOS weeks, spearman):", spearmanr(oos["corr52"], oos["volN52"], nan_policy="omit"))
print("corr52 vs disp52 (OOS weeks, spearman):", spearmanr(oos["corr52"], oos["disp52"], nan_policy="omit"))
