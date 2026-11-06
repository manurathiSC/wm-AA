# -*- coding: utf-8 -*-
"""
7. How concentrated is the out-of-sample edge?

From the continuous OOS NAVs (2007-07-02 -> 2021-10-29, cash sleeve; and
2014-07-07 -> 2021-10-29, 50/50):

  a. Fixed sub-periods (regime blocks chosen by calendar, not by result):
     2007-07 -> 2008-12, 2009 -> 2013, 2014 -> 2017, 2018 -> 2021-10, and
     "OOS without the GFC" 2009-01 -> 2021-10.
  b. Leave-one-calendar-year-out: the pair - bh (and pair - sc100) CAGR
     difference recomputed on the OOS daily returns with one calendar
     year's sessions removed.
  c. Weekly concentration: sum of daily log(1+r_pair) - log(1+r_ref) per
     week; share of the total log edge from the best 5 / 10 / 20 weeks, and
     the number of best weeks whose removal leaves no edge.

Writes robust_subperiods.csv, robust_leave_one_year_out.csv, robust_week_concentration.csv.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import deep_robust_common as C

LEGS = ["SC100", "blend", "N100", "MC100", "N50"]


def main():
    cal, sg, lv, gc = C.load()
    sub_rows, lo_rows, wk_rows = [], [], []
    for sl, a in (("cash", C.FULL_START), ("5050", C.GOLD_START)):
        win = C.Window(cal, sg, lv, gc, a, C.OOS_END, sl, legs=LEGS)
        navs = {}
        for leg in LEGS:
            for rn in ("pair", "bh", "sc100", "own"):
                if rn == "own" and leg == "blend":
                    continue
                navs[(leg, rn)] = win.nav(C.rule_dec(sg, rn, leg), leg)
        blocks = ([("2007-07 -> 2008-12 (GFC)", "2007-07-02", "2008-12-31"),
                   ("2009 -> 2013", "2008-12-31", "2013-12-31"),
                   ("2014 -> 2017", "2013-12-31", "2017-12-31"),
                   ("2018 -> 2021-10", "2017-12-31", "2021-10-29"),
                   ("OOS without the GFC: 2009 -> 2021-10", "2008-12-31", "2021-10-29"),
                   ("OOS without 2008-2009: 2010 -> 2021-10", "2009-12-31", "2021-10-29"),
                   ("whole OOS", "2007-07-02", "2021-10-29")] if sl == "cash" else
                  [("2014-07 -> 2017", "2014-07-07", "2017-12-31"),
                   ("2018 -> 2021-10", "2017-12-31", "2021-10-29"),
                   ("whole 2014-07 -> 2021-10", "2014-07-07", "2021-10-29")])
        for lab, x0, x1 in blocks:
            for leg in LEGS:
                for rn in ("pair", "bh", "sc100", "own"):
                    if (leg, rn) not in navs:
                        continue
                    n = navs[(leg, rn)]
                    n = n[(n.index >= n.index[n.index.searchsorted(pd.Timestamp(x0), side="right") - 1]) &
                          (n.index <= pd.Timestamp(x1))]
                    sub_rows.append({"sleeve": sl, "block": lab, "from": n.index[0].date(), "to": n.index[-1].date(),
                                     "leg": leg, "rule": rn, "cagr": C.cagr(n), "max_dd_daily": C.mdd(n.values),
                                     "max_dd_friday": C.mdd_fri(n)})
        # b. leave one year out
        c = win.c
        years = sorted(set(c.year))
        span = (c[-1] - c[0]).days / 365.25
        for leg in LEGS:
            rp = navs[(leg, "pair")].pct_change().fillna(0.0)
            for ref in ("bh", "sc100"):
                rr = navs[(leg, ref)].pct_change().fillna(0.0)
                full = np.expm1(np.log1p(rp).sum() / span) - np.expm1(np.log1p(rr).sum() / span)
                for y in years:
                    keep = c.year != y
                    yrs_left = span * keep.mean()
                    d = np.expm1(np.log1p(rp[keep]).sum() / yrs_left) - np.expm1(np.log1p(rr[keep]).sum() / yrs_left)
                    lo_rows.append({"sleeve": sl, "leg": leg, "vs": ref, "year_removed": y, "diff_full": full,
                                    "diff_without_year": d, "change": d - full})
        # c. weekly concentration of the log edge
        for leg in LEGS:
            lp = np.log1p(navs[(leg, "pair")].pct_change().fillna(0.0))
            for ref in ("bh", "sc100"):
                lr = np.log1p(navs[(leg, ref)].pct_change().fillna(0.0))
                wk = (lp - lr).groupby(c.to_period("W-FRI")).sum()
                tot = wk.sum()
                srt = wk.sort_values(ascending=False)
                cum = srt.cumsum()
                k_zero = int((tot - cum > 0).sum()) + 1 if tot > 0 else 0
                wk_rows.append({"sleeve": sl, "leg": leg, "vs": ref, "weeks": len(wk), "total_log_edge": float(tot),
                                "total_edge_pp_per_yr": float(np.expm1(tot / span)),
                                "weeks_with_nonzero_diff": int((wk.abs() > 1e-9).sum()),
                                "best5_share": float(srt.iloc[:5].sum() / tot) if tot > 0 else np.nan,
                                "best10_share": float(srt.iloc[:10].sum() / tot) if tot > 0 else np.nan,
                                "best20_share": float(srt.iloc[:20].sum() / tot) if tot > 0 else np.nan,
                                "best_weeks_removal_to_erase_edge": k_zero,
                                "best_week": str(srt.index[0]), "best_week_log": float(srt.iloc[0]),
                                "worst_week": str(srt.index[-1]), "worst_week_log": float(srt.iloc[-1])})
    pd.DataFrame(sub_rows).to_csv(C.OUT / "robust_subperiods.csv", index=False)
    lo = pd.DataFrame(lo_rows)
    lo.to_csv(C.OUT / "robust_leave_one_year_out.csv", index=False)
    pd.DataFrame(wk_rows).to_csv(C.OUT / "robust_week_concentration.csv", index=False)
    pd.set_option("display.width", 250)
    sp = pd.DataFrame(sub_rows)
    for sl in ("cash", "5050"):
        x = sp[(sp.sleeve == sl) & sp.leg.isin(["SC100", "blend", "N100"])]
        print(x.pivot_table(index="block", columns=["leg", "rule"], values="cagr", sort=False).round(3))
        print(x.pivot_table(index="block", columns=["leg", "rule"], values="max_dd_daily", sort=False).round(3))
    g = lo[lo.leg.isin(["SC100", "blend", "N100"])]
    print(g.loc[g.groupby(["sleeve", "leg", "vs"]).change.idxmin()].round(4).to_string(index=False))
    print(g.groupby(["sleeve", "leg", "vs"]).apply(lambda z: (z.diff_without_year > 0).mean()).rename("share_years_edge_survives"))
    print(pd.DataFrame(wk_rows).round(3).to_string(index=False))


if __name__ == "__main__":
    main()
