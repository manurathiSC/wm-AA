# -*- coding: utf-8 -*-
"""
3. Circular-shift null, out of sample 2007-07-02 -> 2021-10-29, cash sleeve.

The weekly signal matrix on the review grid from 2006-01-06 to 2021-10-29
(N100 and SC100 both present) is rolled circularly by k weeks, for every k
with 26 <= k <= n - 26 (so the rolled signals are at least half a year away
from their true dates in either direction). Three variants:

  joint   - roll N100 and SC100 together (keeps their co-movement and each
            signal's duty cycle / run lengths; breaks their timing vs prices);
  n100    - roll N100 only, SC100 kept at its true dates (does N100's
            TIMING add anything beyond removing exposure?);
  sc100   - roll SC100 only, N100 kept.

For every shift the pair (and, for joint, SC100-only) is re-run on SC100,
the blend and N100. The actual result's percentile = share of shifts that
did worse (lower CAGR / deeper max DD / lower Calmar).

Writes robust_shift_null_runs.csv (every shift) and robust_shift_null.csv (summary).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import deep_robust_common as C

LEGS = ["SC100", "blend", "N100"]
MIN_K = 26


def main():
    cal, sg, lv, gc = C.load()
    win = C.Window(cal, sg, lv, gc, C.FULL_START, C.OOS_END, "cash", legs=LEGS)
    m = sg.loc[(sg.index >= pd.Timestamp("2006-01-06")) & (sg.index <= C.OOS_END), ["N100", "SC100"]].dropna()
    n = len(m)
    M = m.to_numpy()

    def evaluate(n100: np.ndarray, sc: np.ndarray, tag: str, k: int) -> list:
        pair = pd.Series(n100 * sc, index=m.index)
        scs = pd.Series(sc, index=m.index)
        out = []
        for leg in LEGS:
            nav, w = win.nav_w(pair, leg)
            s = C.stats(nav, w)
            row = {"variant": tag, "k": k, "leg": leg, "pair_cagr": s["cagr"], "pair_dd_d": s["max_dd_daily"],
                   "pair_dd_f": s["max_dd_friday"], "pair_calmar_d": s["calmar_daily"],
                   "pair_time_in_equity": s["time_in_equity"]}
            if tag in ("actual", "joint"):
                nav2 = win.nav(scs, leg)
                row["sc100_cagr"] = C.cagr(nav2)
                row["sc100_dd_d"] = C.mdd(nav2.values)
            out.append(row)
        return out

    rows = evaluate(M[:, 0], M[:, 1], "actual", 0)
    ks = [k for k in range(MIN_K, n - MIN_K + 1)]
    for k in ks:
        R = np.roll(M, k, axis=0)
        rows += evaluate(R[:, 0], R[:, 1], "joint", k)
        rows += evaluate(np.roll(M[:, 0], k), M[:, 1], "n100", k)
        rows += evaluate(M[:, 0], np.roll(M[:, 1], k), "sc100", k)
    runs = pd.DataFrame(rows)
    runs.to_csv(C.OUT / "robust_shift_null_runs.csv", index=False)

    # bh reference
    bh = {leg: C.stats(win.nav(C.rule_dec(sg, "bh"), leg)) for leg in LEGS}
    act = runs[runs.variant == "actual"].set_index("leg")
    srows = []
    for var in ("joint", "n100", "sc100"):
        for leg in LEGS:
            g = runs[(runs.variant == var) & (runs.leg == leg)]
            a = act.loc[leg]
            row = {"variant": var, "leg": leg, "shifts": len(g), "k_min": int(g.k.min()), "k_max": int(g.k.max()),
                   "weeks_in_matrix": n, "matrix_start": m.index[0].date(), "matrix_end": m.index[-1].date(),
                   "actual_pair_cagr": a["pair_cagr"], "actual_pair_dd_d": a["pair_dd_d"],
                   "actual_pair_dd_f": a["pair_dd_f"], "actual_pair_calmar_d": a["pair_calmar_d"],
                   "actual_time_in_equity": a["pair_time_in_equity"],
                   "bh_cagr": bh[leg]["cagr"], "bh_dd_d": bh[leg]["max_dd_daily"],
                   "pctile_cagr": float((g.pair_cagr < a["pair_cagr"]).mean()),
                   "pctile_dd_d": float((g.pair_dd_d < a["pair_dd_d"]).mean()),
                   "pctile_dd_f": float((g.pair_dd_f < a["pair_dd_f"]).mean()),
                   "pctile_calmar_d": float((g.pair_calmar_d < a["pair_calmar_d"]).mean()),
                   "null_cagr_p5": float(g.pair_cagr.quantile(0.05)), "null_cagr_median": float(g.pair_cagr.median()),
                   "null_cagr_p95": float(g.pair_cagr.quantile(0.95)), "null_cagr_max": float(g.pair_cagr.max()),
                   "null_dd_d_p5": float(g.pair_dd_d.quantile(0.05)), "null_dd_d_median": float(g.pair_dd_d.median()),
                   "null_dd_d_p95": float(g.pair_dd_d.quantile(0.95)), "null_dd_d_best": float(g.pair_dd_d.max()),
                   "null_time_in_equity_median": float(g.pair_time_in_equity.median()),
                   "null_share_pair_cagr_gt_bh": float((g.pair_cagr > bh[leg]["cagr"]).mean()),
                   "null_share_pair_dd_shallower_than_bh": float((g.pair_dd_d > bh[leg]["max_dd_daily"]).mean())}
            if var == "joint":
                row["actual_pair_minus_sc100"] = a["pair_cagr"] - a["sc100_cagr"]
                d = g.pair_cagr - g.sc100_cagr
                row["null_pair_minus_sc100_median"] = float(d.median())
                row["null_share_pair_beats_sc100"] = float((d > 0).mean())
                row["pctile_pair_minus_sc100"] = float((d < row["actual_pair_minus_sc100"]).mean())
                row["null_sc100_cagr_median"] = float(g.sc100_cagr.median())
            srows.append(row)
    summ = pd.DataFrame(srows)
    summ.to_csv(C.OUT / "robust_shift_null.csv", index=False)
    pd.set_option("display.width", 250)
    print(summ[["variant", "leg", "shifts", "actual_pair_cagr", "null_cagr_median", "null_cagr_p95", "pctile_cagr",
                "actual_pair_dd_d", "null_dd_d_median", "pctile_dd_d", "pctile_dd_f", "pctile_calmar_d"]].round(4).to_string(index=False))


if __name__ == "__main__":
    main()
