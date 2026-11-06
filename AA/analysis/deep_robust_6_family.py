# -*- coding: utf-8 -*-
"""
6. Family check: is N100 AND SC100 special, or is any "large AND small"
filter as good?

Rules: pair (N100 AND SC100), N50 AND SC100, MC100 AND SC100,
N100 AND SC250 (signals from 2019-02-22 only), N100 OR SC100, plus the
references SC100 only, N100 only, the triple, N100 AND MC100 (a large+mid
contrast) and bh.

Periods: OOS 2007-07 -> 2021-10 cash (primary); OOS 2014-07 -> 2021-10 50/50;
OOS 2019-02 -> 2021-10 (cash and 50/50, the only OOS span with SC250);
2021-11 -> 2026-08 IN-SAMPLE (not evidence); full 2007-07 -> 2026-08 cash.

Also 3-year rolling windows (weekly starts, OOS only, cash) for each rule:
share of windows beating bh on CAGR, share with a shallower max DD.

Writes robust_family.csv and robust_family_rolling3y.csv.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import deep_robust_common as C

RULES = ["pair", "n50_and_sc100", "mc100_and_sc100", "n100_and_sc250", "n100_or_sc100",
         "sc100", "n100", "triple", "n100_and_mc100", "bh"]
LEGS = ["SC100", "blend", "N100", "MC100", "N50", "SC250"]


def main():
    cal, sg, lv, gc = C.load()
    periods = [("OOS 2007-21, cash", C.FULL_START, C.OOS_END, "cash", ("N100", "MC100", "SC100")),
               ("OOS 2014-21, 50/50", C.GOLD_START, C.OOS_END, "5050", ("N100", "MC100", "SC100")),
               ("OOS 2019-21 (SC250 span), cash", pd.Timestamp("2019-02-25"), C.OOS_END, "cash", ("N100", "SC100", "SC250")),
               ("OOS 2019-21 (SC250 span), 50/50", pd.Timestamp("2019-02-25"), C.OOS_END, "5050", ("N100", "SC100", "SC250")),
               ("IN-SAMPLE 2021-26, 50/50 (not evidence)", C.IS_START, C.CUT, "5050", ("N100", "MC100", "SC100", "SC250")),
               ("IN-SAMPLE 2021-26, cash (not evidence)", C.IS_START, C.CUT, "cash", ("N100", "MC100", "SC100", "SC250")),
               ("FULL 2007-26, cash (includes in-sample)", C.FULL_START, C.CUT, "cash", ("N100", "MC100", "SC100"))]
    rows = []
    for lab, a, b, sl, need in periods:
        win = C.Window(cal, sg, lv, gc, a, b, sl, legs=LEGS, need=need)
        for leg in LEGS:
            if leg == "SC250" and win.c[0] < pd.Timestamp("2019-02-25"):
                continue
            for rn in RULES:
                dec = C.rule_dec(sg, rn, leg)
                d = dec.loc[(dec.index >= win.a - pd.Timedelta(days=7)) & (dec.index <= win.b)]
                if d.dropna().empty or d.dropna().index[0] > win.c[0]:
                    continue  # rule has no signal at the window start (SC250 before 2019)
                nav, w = win.nav_w(dec, leg)
                s = C.stats(nav, w, d)
                rows.append({"period": lab, "sleeve": sl, "leg": leg, "rule": rn, "start": win.c[0].date(),
                             "end": win.c[-1].date(), **s})
        print(lab, "done", flush=True)
    out = pd.DataFrame(rows)
    ref = out[out.rule == "bh"][["period", "leg", "cagr", "max_dd_daily", "max_dd_friday"]].rename(
        columns={"cagr": "bh_cagr", "max_dd_daily": "bh_dd_d", "max_dd_friday": "bh_dd_f"})
    pr = out[out.rule == "pair"][["period", "leg", "cagr", "max_dd_daily"]].rename(
        columns={"cagr": "pair_cagr", "max_dd_daily": "pair_dd_d"})
    out = out.merge(ref, on=["period", "leg"], how="left").merge(pr, on=["period", "leg"], how="left")
    out["minus_bh_cagr"] = out["cagr"] - out["bh_cagr"]
    out["minus_pair_cagr"] = out["cagr"] - out["pair_cagr"]
    out["rank_cagr_in_period_leg"] = out.groupby(["period", "leg"])["cagr"].rank(ascending=False)
    out["rank_calmar_in_period_leg"] = out.groupby(["period", "leg"])["calmar_daily"].rank(ascending=False)
    out.to_csv(C.OUT / "robust_family.csv", index=False)

    # rolling 3-year OOS windows, cash
    win = C.Window(cal, sg, lv, gc, C.FULL_START, C.OOS_END, "cash", legs=["SC100", "blend", "N100"],
                   need=("N100", "MC100", "SC100"))
    c = win.c
    s = pd.Series(c, index=c)
    starts = pd.DatetimeIndex(s.groupby(c.to_period("W-FRI")).last().values)
    starts = starts[starts >= c[0] + pd.Timedelta(days=3)]
    pos = {d: i for i, d in enumerate(c)}
    rrows = []
    for leg in ["SC100", "blend", "N100"]:
        navs = {rn: win.nav(C.rule_dec(sg, rn, leg), leg).to_numpy()
                for rn in RULES if rn != "n100_and_sc250"}
        res = {rn: [] for rn in navs}
        for st in starts:
            e_lim = st + pd.DateOffset(years=3)
            if e_lim > C.OOS_END + pd.Timedelta(days=3):
                continue
            e = c[c.searchsorted(e_lim, side="right") - 1]
            i0, i1 = pos[st], pos[e]
            yrs = (e - st).days / 365.25
            for rn, x in navs.items():
                seg = x[i0:i1 + 1]
                res[rn].append(((seg[-1] / seg[0]) ** (1 / yrs) - 1, C.mdd(seg)))
        bh = np.array(res["bh"])
        pair = np.array(res["pair"])
        for rn, v in res.items():
            v = np.array(v)
            rrows.append({"leg": leg, "rule": rn, "windows": len(v),
                          "share_cagr_gt_bh": float((v[:, 0] > bh[:, 0] + 1e-6).mean()),
                          "share_dd_shallower_than_bh": float((v[:, 1] > bh[:, 1] + 1e-6).mean()),
                          "median_minus_bh_cagr": float(np.median(v[:, 0] - bh[:, 0])),
                          "share_cagr_gt_pair": float((v[:, 0] > pair[:, 0] + 1e-6).mean()),
                          "share_cagr_lt_pair": float((v[:, 0] < pair[:, 0] - 1e-6).mean()),
                          "median_minus_pair_cagr": float(np.median(v[:, 0] - pair[:, 0])),
                          "median_dd": float(np.median(v[:, 1])), "worst_dd": float(v[:, 1].min())})
    rr = pd.DataFrame(rrows)
    rr.to_csv(C.OUT / "robust_family_rolling3y.csv", index=False)
    pd.set_option("display.width", 250)
    for per in out.period.unique():
        x = out[(out.period == per) & out.leg.isin(["SC100", "blend", "N100", "SC250"])]
        print(per)
        print(x.pivot_table(index="rule", columns="leg", values="cagr").round(4))
        print(x.pivot_table(index="rule", columns="leg", values="max_dd_daily").round(3))
    print(rr.round(3).to_string(index=False))


if __name__ == "__main__":
    main()
