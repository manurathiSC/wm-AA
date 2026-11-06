# -*- coding: utf-8 -*-
"""
5. Supertrend settings: knife-edge or plateau?

N100 and SC100 weekly signals are recomputed with
supertrend.supertrend(to_weekly(ohlc), mul, days) from the frozen
AA/Historical Data/frozen_2026-09-25/Data/indices_ohlcv.xlsx (sheets
"Nifty100" and "SC100", volume set to 0), for mul in {1.5, 2, 2.5, 3} x
days in {5, 10}. Each signal is put on the Friday review grid (the Master
dates) as the latest weekly bar whose last session is on or before the
review date.

  a. mul=2, days=5 vs production Master SIGN, week by week.
  b. Same setting on both indices: pair, SC100-only and N100-own on the SC100
     and blend legs, OOS 2007-07-02 -> 2021-10-29, cash sleeve (primary);
     extras: OOS 2014-07 -> 2021-10 with 50/50, and 2021-11 -> 2026-08
     IN-SAMPLE (not evidence).
  c. Cross grid: N100 setting x SC100 setting (8 x 8 = 64) for the pair, OOS cash.

Writes robust_st_match.csv, robust_st_grid.csv, robust_st_cross.csv,
robust_st_weekly_signals.csv.
"""
from __future__ import annotations

import itertools

import numpy as np
import pandas as pd

import deep_robust_common as C
import segment_v2_data as D
from supertrend import supertrend, to_weekly

MULS = [1.5, 2.0, 2.5, 3.0]
DAYS = [5, 10]
SHEETS = {"N100": "Nifty100", "SC100": "SC100"}
LEGS = ["SC100", "blend"]


def on_grid(sig: pd.Series, grid: pd.DatetimeIndex) -> pd.Series:
    """Latest weekly bar whose last session is on or before each review date."""
    s = sig.dropna()
    pos = s.index.searchsorted(grid, side="right") - 1
    v = np.where(pos >= 0, s.values[np.clip(pos, 0, None)], np.nan)
    return pd.Series(v, index=grid)


def main():
    cal, sg, lv, gc = C.load()
    grid = sg.index
    xl = D.FROZEN_DIR / "Data" / "indices_ohlcv.xlsx"
    ohlc = {}
    for k, sh in SHEETS.items():
        d = pd.read_excel(xl, sheet_name=sh)
        d["date"] = pd.to_datetime(d["date"])
        d = d.set_index("date").sort_index()
        d = d[~d.index.duplicated()][["open", "high", "low", "close"]].astype(float)
        d["volume"] = 0.0
        ohlc[k] = to_weekly(d)
    sigs = {}
    for k in SHEETS:
        for mul, days in itertools.product(MULS, DAYS):
            sigs[(k, mul, days)] = on_grid(supertrend(ohlc[k], mul, days)["signal"], grid)
    wk = pd.DataFrame({f"{k}|x{m}|{d}": v for (k, m, d), v in sigs.items()})
    wk.to_csv(C.OUT / "robust_st_weekly_signals.csv")

    # a. production check
    mrows = []
    for k in SHEETS:
        ours = sigs[(k, 2.0, 5)]
        prod = sg[k]
        for lab, lo, hi in (("2006-01 -> 2007-06 (warm-up)", "2006-01-01", "2007-06-30"),
                            ("OOS 2007-07 -> 2021-10", "2007-07-01", "2021-10-29"),
                            ("2021-11 -> 2026-08", "2021-11-01", "2026-08-21")):
            j = pd.concat([ours.rename("o"), prod.rename("p")], axis=1).loc[lo:hi].dropna()
            mrows.append({"index": k, "span": lab, "weeks": len(j), "match_share": float((j.o == j.p).mean()),
                          "mismatches": int((j.o != j.p).sum()),
                          "mismatch_dates": ";".join(str(d.date()) for d in j.index[j.o != j.p])})
    match = pd.DataFrame(mrows)
    match.to_csv(C.OUT / "robust_st_match.csv", index=False)
    print(match.to_string(index=False))

    periods = [("OOS 2007-21, cash", C.FULL_START, C.OOS_END, "cash"),
               ("OOS 2014-21, 50/50", C.GOLD_START, C.OOS_END, "5050"),
               ("IN-SAMPLE 2021-26, 50/50 (not evidence)", C.IS_START, C.CUT, "5050")]
    rows = []
    for lab, a, b, sl in periods:
        win = C.Window(cal, sg, lv, gc, a, b, sl, legs=LEGS)
        bh = {leg: C.stats(win.nav(C.rule_dec(sg, "bh"), leg)) for leg in LEGS}
        for mul, days in itertools.product(MULS, DAYS):
            n1, s1 = sigs[("N100", mul, days)], sigs[("SC100", mul, days)]
            decs = {"pair": n1 * s1, "sc100": s1, "n100_own": n1}
            for leg in LEGS:
                for rn, dec in decs.items():
                    nav, w = win.nav_w(dec, leg)
                    d = dec.loc[(dec.index >= win.a - pd.Timedelta(days=7)) & (dec.index <= win.b)]
                    s = C.stats(nav, w, d)
                    rows.append({"period": lab, "leg": leg, "mul": mul, "days": days,
                                 "production": bool(mul == 2.0 and days == 5), "rule": rn, **s,
                                 "bh_cagr": bh[leg]["cagr"], "bh_max_dd_daily": bh[leg]["max_dd_daily"],
                                 "bh_max_dd_friday": bh[leg]["max_dd_friday"]})
    grid_df = pd.DataFrame(rows)
    # per-setting comparisons
    piv = grid_df.pivot_table(index=["period", "leg", "mul", "days"], columns="rule",
                              values=["cagr", "max_dd_daily", "max_dd_friday"])
    comp = pd.DataFrame({
        "pair_minus_sc100_cagr": piv[("cagr", "pair")] - piv[("cagr", "sc100")],
        "pair_minus_n100own_cagr": piv[("cagr", "pair")] - piv[("cagr", "n100_own")],
        "pair_minus_sc100_dd_d": piv[("max_dd_daily", "pair")] - piv[("max_dd_daily", "sc100")],
        "pair_minus_n100own_dd_d": piv[("max_dd_daily", "pair")] - piv[("max_dd_daily", "n100_own")],
    }).reset_index()
    grid_df = grid_df.merge(comp, on=["period", "leg", "mul", "days"], how="left")
    grid_df["minus_bh_cagr"] = grid_df["cagr"] - grid_df["bh_cagr"]
    grid_df.to_csv(C.OUT / "robust_st_grid.csv", index=False)

    # c. cross grid, OOS cash
    win = C.Window(cal, sg, lv, gc, C.FULL_START, C.OOS_END, "cash", legs=LEGS)
    bh = {leg: C.stats(win.nav(C.rule_dec(sg, "bh"), leg)) for leg in LEGS}
    xrows = []
    for (m1, d1), (m2, d2) in itertools.product(itertools.product(MULS, DAYS), repeat=2):
        dec = sigs[("N100", m1, d1)] * sigs[("SC100", m2, d2)]
        for leg in LEGS:
            nav, w = win.nav_w(dec, leg)
            s = C.stats(nav, w)
            sc = C.cagr(win.nav(sigs[("SC100", m2, d2)], leg))
            xrows.append({"leg": leg, "n100_mul": m1, "n100_days": d1, "sc100_mul": m2, "sc100_days": d2,
                          "production": bool(m1 == 2 and d1 == 5 and m2 == 2 and d2 == 5), **s,
                          "sc100_only_cagr_same_sc_setting": sc, "pair_minus_sc100_cagr": s["cagr"] - sc,
                          "bh_cagr": bh[leg]["cagr"], "bh_max_dd_daily": bh[leg]["max_dd_daily"]})
    cross = pd.DataFrame(xrows)
    cross.to_csv(C.OUT / "robust_st_cross.csv", index=False)

    pd.set_option("display.width", 250)
    x = grid_df[grid_df.period == "OOS 2007-21, cash"]
    print(x.pivot_table(index=["leg", "mul", "days"], columns="rule", values="cagr").round(4))
    print(x.pivot_table(index=["leg", "mul", "days"], columns="rule", values="max_dd_daily").round(3))
    for leg in LEGS:
        c = cross[cross.leg == leg]
        print(leg, "cross grid pair CAGR: min %.4f median %.4f max %.4f; share > bh %.3f; share pair > sc100-only %.3f; prod rank %d/64"
              % (c.cagr.min(), c.cagr.median(), c.cagr.max(), (c.cagr > c.bh_cagr).mean(),
                 (c.pair_minus_sc100_cagr > 0).mean(), int((c.cagr > c[c.production].cagr.iloc[0]).sum()) + 1))


if __name__ == "__main__":
    main()
