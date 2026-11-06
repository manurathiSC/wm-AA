# -*- coding: utf-8 -*-
"""
1. Rolling windows.

Continuous whole-history NAVs (cash sleeve 2007-07-02 -> 2026-08-21; 50/50
gold/cash sleeve 2014-07-07 -> 2026-08-21) for pair, bh, sc100 and own on the
five core legs, sliced into 1-, 3- and 5-year windows starting at every
week's last session. Each window: CAGR, worst fall on daily closes and on
Friday closes (W-FRI last), Calmar on each.

Windows are tagged:
  oos      - end on or before 2021-10-29 (entirely out of sample)
  touch_is - end after 2021-10-29 (touches the in-sample period)
  is_only  - start on or after 2021-11-03 (a subset of touch_is)

Writes:
  robust_rolling_windows.csv          every window, every rule
  robust_rolling_summary.csv          win shares and percentiles by leg / L / tag
  robust_rolling_by_market.csv        pair vs bh by the leg's own bh CAGR bucket (EX-POST)
  robust_rolling_extremes.csv         worst and best pair - bh windows
  robust_calendar_years.csv           calendar-year returns per rule (2007 partial, 2026 to 08-21)
"""
from __future__ import annotations

import time

import numpy as np
import pandas as pd

import deep_robust_common as C

RULES = ["pair", "bh", "sc100", "own"]
LENS = [1, 3, 5]


def week_ends(c: pd.DatetimeIndex) -> pd.DatetimeIndex:
    s = pd.Series(c, index=c)
    return pd.DatetimeIndex(s.groupby(c.to_period("W-FRI")).last().values)


def main():
    t0 = time.time()
    cal, sg, lv, gc = C.load()
    rows, yrows = [], []
    for sleeve, a in (("cash", C.FULL_START), ("5050", C.GOLD_START)):
        win = C.Window(cal, sg, lv, gc, a, C.CUT, sleeve)
        c = win.c
        navs = {}
        for leg in C.CORE_LEGS:
            for rn in RULES:
                if rn == "own" and leg == "blend":
                    continue
                navs[(leg, rn)] = win.nav(C.rule_dec(sg, rn, leg), leg)
        # calendar years (first/last partial), from the same continuous NAVs
        for (leg, rn), n in navs.items():
            ye = n.groupby(n.index.year).last()
            prev = pd.concat([pd.Series([n.iloc[0]], index=[ye.index[0] - 1]), ye]).shift(1).iloc[1:]
            fri = C.friday(n)
            for y in ye.index:
                seg = n[n.index.year == y]
                base = prev.loc[y]
                seg2 = pd.concat([pd.Series([base]), seg.reset_index(drop=True)])
                fseg = fri[fri.index.year == y]
                fseg2 = pd.concat([pd.Series([base]), fseg.reset_index(drop=True)])
                yrows.append({"sleeve": sleeve, "leg": leg, "rule": rn, "year": int(y),
                              "return": float(ye.loc[y] / base - 1),
                              "max_dd_daily": C.mdd(seg2.values), "max_dd_friday": C.mdd(fseg2.values),
                              "first": seg.index[0].date(), "last": seg.index[-1].date()})
        starts = week_ends(c)
        starts = starts[starts >= c[0] + pd.Timedelta(days=3)]
        pos = {d: i for i, d in enumerate(c)}
        arr = {k: v.to_numpy() for k, v in navs.items()}
        fri = {k: C.friday(v) for k, v in navs.items()}
        fri_idx = next(iter(fri.values())).index
        # map each Friday label to position for slicing
        for L in LENS:
            for s in starts:
                e_lim = s + pd.DateOffset(years=L)
                if e_lim > C.CUT + pd.Timedelta(days=3):
                    continue
                e = c[c.searchsorted(e_lim, side="right") - 1]
                i0, i1 = pos[s], pos[e]
                yrs = (e - s).days / 365.25
                tag = "oos" if e <= C.OOS_END else "touch_is"
                row = {"sleeve": sleeve, "L": L, "start": s.date(), "end": e.date(), "tag": tag,
                       "is_only": bool(s >= C.IS_START)}
                f0 = fri_idx.searchsorted(s)             # Friday label on/after the start session
                f1 = fri_idx.searchsorted(e, side="right")
                for leg in C.CORE_LEGS:
                    for rn in RULES:
                        if (leg, rn) not in arr:
                            continue
                        x = arr[(leg, rn)][i0:i1 + 1]
                        cg = (x[-1] / x[0]) ** (1 / yrs) - 1
                        dd = C.mdd(x)
                        xf = np.r_[x[0], fri[(leg, rn)].to_numpy()[f0:f1]]
                        ddf = C.mdd(xf)
                        row[f"{leg}|{rn}|cagr"] = cg
                        row[f"{leg}|{rn}|dd_d"] = dd
                        row[f"{leg}|{rn}|dd_f"] = ddf
                        row[f"{leg}|{rn}|calmar_d"] = C.calmar(cg, dd)
                        row[f"{leg}|{rn}|calmar_f"] = C.calmar(cg, ddf)
                rows.append(row)
        print(f"{sleeve} windows done ({time.time() - t0:.0f}s)", flush=True)

    wdf = pd.DataFrame(rows)
    wdf.to_csv(C.OUT / "robust_rolling_windows.csv", index=False)
    pd.DataFrame(yrows).to_csv(C.OUT / "robust_calendar_years.csv", index=False)

    # ── summary ────────────────────────────────────────────────────────────
    TOL = 1e-6  # tie = identical path (both rules held the same position all window)
    srows, mrows, xrows = [], [], []
    for (sleeve, L), g0 in wdf.groupby(["sleeve", "L"]):
        subsets = {"all": g0, "oos": g0[g0.tag == "oos"], "touch_is": g0[g0.tag == "touch_is"],
                   "is_only": g0[g0.is_only]}
        for tag, g in subsets.items():
            if not len(g):
                continue
            span = (pd.to_datetime(g["end"]).max() - pd.to_datetime(g["start"]).min()).days / 365.25
            for leg in C.CORE_LEGS:
                p = f"{leg}|pair|"
                row = {"sleeve": sleeve, "L": L, "tag": tag, "leg": leg, "windows": len(g),
                       "first_start": g["start"].min(), "last_end": g["end"].max(),
                       "approx_independent_windows": round(span / L, 1)}
                for ref in ("bh", "sc100", "own"):
                    q = f"{leg}|{ref}|"
                    if q + "cagr" not in g:
                        continue
                    if leg == "SC100" and ref == "own":
                        row["own_note"] = "own = sc100 on SC100"
                    dc = g[p + "cagr"] - g[q + "cagr"]
                    row[f"vs_{ref}|cagr_win"] = float((dc > TOL).mean())
                    row[f"vs_{ref}|cagr_tie"] = float((dc.abs() <= TOL).mean())
                    row[f"vs_{ref}|cagr_loss"] = float((dc < -TOL).mean())
                    row[f"vs_{ref}|cagr_win_of_untied"] = float((dc > TOL).sum() / max((dc.abs() > TOL).sum(), 1))
                    row[f"vs_{ref}|cagr_win_by_0p5pp"] = float((dc > 0.005).mean())
                    for dk in ("dd_d", "dd_f"):
                        dd = g[p + dk] - g[q + dk]
                        row[f"vs_{ref}|{dk}_shallower"] = float((dd > TOL).mean())
                        row[f"vs_{ref}|{dk}_tie"] = float((dd.abs() <= TOL).mean())
                        row[f"vs_{ref}|{dk}_deeper"] = float((dd < -TOL).mean())
                    for ck in ("calmar_d", "calmar_f"):
                        a_, b_ = g[p + ck], g[q + ck]
                        same = (g[p + "cagr"] - g[q + "cagr"]).abs() <= TOL
                        row[f"vs_{ref}|{ck}_win"] = float(((a_ > b_) & ~same).mean())
                        row[f"vs_{ref}|{ck}_tie"] = float(same.mean())
                    for pc in (5, 25, 50, 75, 95):
                        row[f"vs_{ref}|cagr_diff_p{pc}"] = float(np.percentile(dc, pc))
                    row[f"vs_{ref}|cagr_diff_mean"] = float(dc.mean())
                    row[f"vs_{ref}|dd_d_diff_median"] = float((g[p + "dd_d"] - g[q + "dd_d"]).median())
                    row[f"vs_{ref}|dd_f_diff_median"] = float((g[p + "dd_f"] - g[q + "dd_f"]).median())
                row["pair_cagr_median"] = float(g[p + "cagr"].median())
                row["bh_cagr_median"] = float(g[f"{leg}|bh|cagr"].median())
                row["pair_dd_d_median"] = float(g[p + "dd_d"].median())
                row["bh_dd_d_median"] = float(g[f"{leg}|bh|dd_d"].median())
                row["pair_dd_d_worst"] = float(g[p + "dd_d"].min())
                row["bh_dd_d_worst"] = float(g[f"{leg}|bh|dd_d"].min())
                row["pair_cagr_negative_share"] = float((g[p + "cagr"] < 0).mean())
                row["bh_cagr_negative_share"] = float((g[f"{leg}|bh|cagr"] < 0).mean())
                srows.append(row)
                # extremes of pair - bh
                if tag in ("oos", "touch_is"):
                    dc = (g[p + "cagr"] - g[f"{leg}|bh|cagr"])
                    for kind, idx in (("worst", dc.idxmin()), ("best", dc.idxmax())):
                        xrows.append({"sleeve": sleeve, "L": L, "tag": tag, "leg": leg, "kind": kind,
                                      "start": g.loc[idx, "start"], "end": g.loc[idx, "end"],
                                      "pair_cagr": g.loc[idx, p + "cagr"], "bh_cagr": g.loc[idx, f"{leg}|bh|cagr"],
                                      "diff": dc.loc[idx], "pair_dd_d": g.loc[idx, p + "dd_d"],
                                      "bh_dd_d": g.loc[idx, f"{leg}|bh|dd_d"]})
                # by market regime of the window (EX-POST: bh CAGR of the same leg over the same window)
                if tag in ("oos", "all", "touch_is"):
                    bh = g[f"{leg}|bh|cagr"]
                    bins = [-np.inf, -0.10, 0.0, 0.10, 0.20, 0.30, np.inf]
                    labs = ["< -10%", "-10% to 0", "0 to 10%", "10% to 20%", "20% to 30%", "> 30%"]
                    b = pd.cut(bh, bins, labels=labs)
                    for lab in labs:
                        m = b == lab
                        if not m.any():
                            continue
                        dc = g.loc[m, p + "cagr"] - bh[m]
                        ddd = g.loc[m, p + "dd_d"] - g.loc[m, f"{leg}|bh|dd_d"]
                        mrows.append({"sleeve": sleeve, "L": L, "tag": tag, "leg": leg,
                                      "bh_cagr_bucket_EXPOST": lab, "windows": int(m.sum()),
                                      "share_of_windows": float(m.mean()),
                                      "pair_beats_bh_share": float((dc > 0).mean()),
                                      "pair_minus_bh_median": float(dc.median()),
                                      "pair_minus_bh_p10": float(np.percentile(dc, 10)),
                                      "pair_minus_bh_p90": float(np.percentile(dc, 90)),
                                      "pair_dd_shallower_share": float((ddd > 0).mean()),
                                      "pair_minus_bh_dd_d_median": float(ddd.median()),
                                      "pair_beats_sc100_share": float((g.loc[m, p + "cagr"] > g.loc[m, f"{leg}|sc100|cagr"]).mean())})
    pd.DataFrame(srows).to_csv(C.OUT / "robust_rolling_summary.csv", index=False)
    pd.DataFrame(mrows).to_csv(C.OUT / "robust_rolling_by_market.csv", index=False)
    pd.DataFrame(xrows).to_csv(C.OUT / "robust_rolling_extremes.csv", index=False)
    print(f"done ({time.time() - t0:.0f}s)")


if __name__ == "__main__":
    main()
