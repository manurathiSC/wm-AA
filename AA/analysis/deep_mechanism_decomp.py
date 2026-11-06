# -*- coding: utf-8 -*-
"""
Part 1: where does a rule's excess over another rule come from?

Identity (daily, w in {0,1}): r_A - r_B = (w_B - w_A) * (r_eq - r_sl) - (cost_A - cost_B).
In log space it splits EXACTLY (sums to ln(NAV_A / NAV_B)):
  on days A is out and B is in:
    losses avoided  LA = sum -ln(1 + r_eq) over those days with r_eq < 0   (>0)
    gains missed    GM = sum -ln(1 + r_eq) over those days with r_eq > 0   (<0)
    sleeve earned   SL = sum  ln(1 + r_sl) over those days
  on days A is in and B is out (never happens for pair vs bh / sc100):
    losses taken    LT, gains captured GC, sleeve forgone SF
  switching costs   C  = sum [ln(1+net) - ln(1+gross)]_A - [...]_B
Annualised = sum / years of the window  -> ln(1+CAGR_A) - ln(1+CAGR_B).
The arithmetic version (plain sums of r_eq, as the task defines them) is in
the same file with suffix _ar; its gap to the CAGR difference is the
volatility-drag / compounding residual.

Outputs (evidence/why_n100sc100/deep/):
  mechanism_decomp_periods.csv   per period x equity x comparison
  mechanism_decomp_years.csv     per calendar year (one 2007-07 -> 2026-08 run)
  mechanism_decomp_by_state.csv  the pair's out-of-market days split by signal state
"""

from __future__ import annotations

import numpy as np
import pandas as pd

import deep_mechanism_data as M
from why_n100sc100 import daily_weight

cal, sg, lv, gc = M.load()
EQ = ["SC100", "blend"]
RULES = ["bh", "sc100", "pair", "triple", "n100"]
COMPS = [("pair", "bh"), ("sc100", "bh"), ("pair", "sc100"), ("triple", "bh"), ("triple", "pair"),
         ("n100", "bh")]
PERIODS = [
    ("OOS 2007-07..2021-10", "2007-07-02", "2021-10-29", "cash", "OOS"),
    ("OOS 2007-07..2010-12", "2007-07-02", "2010-12-31", "cash", "OOS"),
    ("OOS 2011-01..2015-12", "2011-01-03", "2015-12-31", "cash", "OOS"),
    ("OOS 2016-01..2021-10", "2016-01-01", "2021-10-29", "cash", "OOS"),
    ("OOS 2007-07..2013-12", "2007-07-02", "2013-12-31", "cash", "OOS"),
    ("OOS 2014-07..2021-10", "2014-07-07", "2021-10-29", "cash", "OOS"),
    ("OOS 2014-07..2021-10 50/50", "2014-07-07", "2021-10-29", "gold+cash", "OOS"),
    ("IS 2021-11..2026-08", "2021-11-03", "2026-08-21", "cash", "IS"),
    ("IS 2021-11..2026-08 50/50", "2021-11-03", "2026-08-21", "gold+cash", "IS"),
    ("FULL 2007-07..2026-08", "2007-07-02", "2026-08-21", "cash", "mixed"),
]


def run_window(a, b, sleeve):
    c = M.window(cal, a, b)
    s = M.sig_window(sg, a, b, ["N100", "SC100", "MC100"])
    r_sl = M.sleeve_returns(gc, c, sleeve)
    req = M.equity_returns(lv, c)
    out = {}
    for ek in EQ:
        for rn in RULES:
            f = M.sim(M.decisions(s, rn), req[ek], r_sl, c)
            assert set(np.unique(f["w"])) <= {0.0, 1.0}
            out[(ek, rn)] = f
    # individual-signal daily weights for the state split
    wN = daily_weight(s["N100"], c).reindex(c).ffill().fillna(1.0)
    wS = daily_weight(s["SC100"], c).reindex(c).ffill().fillna(1.0)
    return c, out, wN, wS


def pieces(A: pd.DataFrame, B: pd.DataFrame) -> pd.DataFrame:
    """Daily exact log pieces of ln(1+net_A) - ln(1+net_B)."""
    le, ls = np.log1p(A["r_eq"]), np.log1p(A["r_sl"])
    a_out = (A["w"] < 0.5) & (B["w"] > 0.5)
    a_in = (A["w"] > 0.5) & (B["w"] < 0.5)
    neg, pos = A["r_eq"] < 0, A["r_eq"] > 0
    cA = np.log1p(A["net"]) - np.log1p(A["gross"])
    cB = np.log1p(B["net"]) - np.log1p(B["gross"])
    d = pd.DataFrame({
        "LA": (-le).where(a_out & neg, 0.0),
        "GM": (-le).where(a_out & pos, 0.0),
        "SL": ls.where(a_out, 0.0),
        "LT": le.where(a_in & neg, 0.0),
        "GC": le.where(a_in & pos, 0.0),
        "SF": (-ls).where(a_in, 0.0),
        "C": cA - cB,
        "total": np.log1p(A["net"]) - np.log1p(B["net"]),
        # arithmetic versions (task definition)
        "LA_ar": (-A["r_eq"]).where(a_out & neg, 0.0),
        "GM_ar": (-A["r_eq"]).where(a_out & pos, 0.0),
        "SL_ar": A["r_sl"].where(a_out, 0.0),
        "LT_ar": A["r_eq"].where(a_in & neg, 0.0),
        "GC_ar": A["r_eq"].where(a_in & pos, 0.0),
        "SF_ar": (-A["r_sl"]).where(a_in, 0.0),
        "C_ar": -(A["cost"] - B["cost"]),
        "total_ar": A["net"] - B["net"],
        "a_out": a_out.astype(int), "a_in": a_in.astype(int),
        "a_out_neg": (a_out & neg).astype(int),
    })
    return d


def summarise(d: pd.DataFrame, yrs: float, navA: pd.Series, navB: pd.Series) -> dict:
    s = d.sum()
    cA, cB = M.cagr_nav(navA), M.cagr_nav(navB)
    lg = ["LA", "GM", "SL", "LT", "GC", "SF", "C"]
    resid = float(s["total"] - s[lg].sum())
    assert abs(resid) < 1e-9, resid
    assert abs(s["total"] - np.log(navA.iloc[-1] / navB.iloc[-1] * navB.iloc[0] / navA.iloc[0])) < 1e-9
    row = {f"{k}_pp_yr": 100 * s[k] / yrs for k in lg + ["total"]}
    row.update({f"{k}_ar_pp_yr": 100 * s[k + "_ar"] / yrs for k in lg + ["total"]})
    row.update({
        "cagr_A": cA, "cagr_B": cB, "cagr_gap_pp": 100 * (cA - cB),
        "ln_gap_pp_yr": 100 * (np.log1p(cA) - np.log1p(cB)),
        "arith_vs_cagr_residual_pp": 100 * (cA - cB) - 100 * s["total_ar"] / yrs,
        "days_A_out_B_in": int(s["a_out"]), "days_A_in_B_out": int(s["a_in"]),
        "share_days_A_out_B_in": float(s["a_out"] / len(d)),
        "hit_rate_out_days_eq_down": float(s["a_out_neg"] / s["a_out"]) if s["a_out"] else np.nan,
        "maxdd_A_daily": M.mdd_daily(navA), "maxdd_B_daily": M.mdd_daily(navB),
        "maxdd_A_weekly": M.mdd_weekly(navA), "maxdd_B_weekly": M.mdd_weekly(navB),
        "years": yrs, "sessions": len(d),
    })
    return row


rows, srows = [], []
for plab, a, b, sleeve, samp in PERIODS:
    c, out, wN, wS = run_window(a, b, sleeve)
    yrs = M.years(c)
    for ek in EQ:
        for A, B in COMPS:
            fa, fb = out[(ek, A)], out[(ek, B)]
            d = pieces(fa, fb)
            r = summarise(d, yrs, fa["nav"], fb["nav"])
            r.update({"period": plab, "sample": samp, "sleeve": sleeve, "equity": ek, "A": A, "B": B,
                      "start": c[0].date(), "end": c[-1].date(),
                      "switches_A": int((fa["w"].diff().abs() > 0).sum()),
                      "switches_B": int((fb["w"].diff().abs() > 0).sum())})
            rows.append(r)
            # state split of the pair's out-of-market days (vs bh and vs sc100)
            if A == "pair" and B in ("bh", "sc100"):
                st = np.select([(wN == 0) & (wS == 0), (wN == 0) & (wS == 1), (wN == 1) & (wS == 0)],
                               ["both SELL", "N100 SELL only (SC100 BUY)", "SC100 SELL only (N100 BUY)"],
                               "both BUY")
                st = pd.Series(st, index=c)
                for k, g in d.groupby(st):
                    if g["a_out"].sum() == 0:
                        continue
                    srows.append({"period": plab, "sample": samp, "sleeve": sleeve, "equity": ek,
                                  "A": A, "B": B, "state": k, "days_out": int(g["a_out"].sum()),
                                  "share_of_A_out_days": float(g["a_out"].sum() / d["a_out"].sum()),
                                  "LA_pp_yr": 100 * g["LA"].sum() / yrs, "GM_pp_yr": 100 * g["GM"].sum() / yrs,
                                  "SL_pp_yr": 100 * g["SL"].sum() / yrs,
                                  "net_before_cost_pp_yr": 100 * (g["LA"] + g["GM"] + g["SL"]).sum() / yrs,
                                  "hit_rate_eq_down": float(g["a_out_neg"].sum() / g["a_out"].sum()),
                                  "mean_daily_eq_ret_bp": 1e4 * float(g.loc[g["a_out"] == 1].index.map(
                                      fa["r_eq"]).to_series().mean()),
                                  "years": yrs})
    print("done", plab, flush=True)

per = pd.DataFrame(rows)
lead = ["period", "sample", "sleeve", "equity", "A", "B", "start", "end"]
per = per[lead + [c_ for c_ in per.columns if c_ not in lead]]
per.to_csv(M.OUT / "mechanism_decomp_periods.csv", index=False)
pd.DataFrame(srows).to_csv(M.OUT / "mechanism_decomp_by_state.csv", index=False)

# ── calendar years, one full run ─────────────────────────────────────────────
c, out, wN, wS = run_window("2007-07-02", "2026-08-21", "cash")
yrows = []
for ek in EQ:
    for A, B in COMPS[:3] + [("triple", "pair")]:
        fa, fb = out[(ek, A)], out[(ek, B)]
        d = pieces(fa, fb)
        for y, g in d.groupby(d.index.year):
            ga, gb = fa.loc[g.index], fb.loc[g.index]
            ra, rb = float((1 + ga["net"]).prod() - 1), float((1 + gb["net"]).prod() - 1)
            yrows.append({"year": int(y), "sample": "OOS" if y <= 2020 else ("mixed" if y == 2021 else "IS"),
                          "partial": bool(y in (2007, 2026)), "equity": ek, "A": A, "B": B,
                          "ret_A": ra, "ret_B": rb, "ret_gap_pp": 100 * (ra - rb),
                          "eq_ret_year": float((1 + ga["r_eq"]).prod() - 1),
                          "LA_pp": 100 * g["LA"].sum(), "GM_pp": 100 * g["GM"].sum(),
                          "SL_pp": 100 * g["SL"].sum(), "C_pp": 100 * g["C"].sum(),
                          "total_log_pp": 100 * g["total"].sum(),
                          "days_A_out_B_in": int(g["a_out"].sum()), "sessions": len(g),
                          "maxdd_A_daily": float((ga["nav"] / ga["nav"].cummax() - 1).min()),
                          "maxdd_B_daily": float((gb["nav"] / gb["nav"].cummax() - 1).min())})
yr = pd.DataFrame(yrows)
yr.to_csv(M.OUT / "mechanism_decomp_years.csv", index=False)

# ── console check ────────────────────────────────────────────────────────────
pd.set_option("display.width", 260)
cols = ["period", "equity", "A", "B", "cagr_A", "cagr_B", "cagr_gap_pp", "ln_gap_pp_yr", "LA_pp_yr", "GM_pp_yr",
        "SL_pp_yr", "C_pp_yr", "total_pp_yr", "share_days_A_out_B_in", "hit_rate_out_days_eq_down",
        "arith_vs_cagr_residual_pp", "maxdd_A_daily", "maxdd_A_weekly"]
print(per[per.A.isin(["pair", "sc100"]) & per.B.isin(["bh", "sc100"])][cols].round(4).to_string(index=False))
print(pd.DataFrame(srows).round(3).to_string(index=False))
x = yr[(yr.A == "pair") & (yr.B == "bh")]
print(x.pivot(index="year", columns="equity", values="ret_gap_pp").round(1).to_string())
