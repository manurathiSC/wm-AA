# -*- coding: utf-8 -*-
"""
T03 Step 1: why is SCMO_0007 (listed weights, avail_ohlc4) +2.04 pp off the published NAV in calendar 2021?

Standalone diagnostic; reuses build()/load_*() from data/parent_rebuild_hm.py. Reads only existing files, writes
data/parent_rebuild_hm/gap_0007_2021_*.csv.  Run from AA/:  python data/parent_gap_0007_2021.py

Sections
  1. DB weight matrix vs frozen rebalance-history CSV (every basket; the 2021-06-17 and 2021-09-16 ones shown)
  2. Daily gap (model - published, cumulative, rebased on 2020-12-31) through 2021: the days where it jumps
  3. Per-stock attribution of the jump day (units held x close move; model vs the published index's move)
  4. Candidate fixes, each rerun through the same build(): skipped basket traded, 2021-09-16 only, Polyplex price
     corrected for the Rs 100 special dividend (ex 2021-02-17), factor sweep
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import parent_rebuild_hm as prh  # noqa: E402

P = "SCMO_0007"
OUT = prh.OUT
HM, REBAL = prh.HM, prh.REBAL


def yr_gap(nav, pub, year):
    c = pd.DataFrame({"m": nav, "p": pub}).dropna(); c = c / c.iloc[0] * 100
    g = c[c.index.year == year]
    prev = c.loc[:g.index[0]].iloc[-2]
    return (g["m"].iloc[-1] / prev["m"] - g["p"].iloc[-1] / prev["p"]) * 100


def main():
    m, cols, px = prh.load_hm(P)
    pub = prh.load_pub(P)
    cal0 = pd.to_datetime(pd.read_csv(prh.CAL_CSV)["date"])
    busy = px["close"].notna().sum(axis=1)
    cal = pd.DatetimeIndex(sorted(set(cal0) | set(pub.index) | set(busy[busy >= 0.5 * busy.median()].index)))
    cal = cal[(cal >= pd.Timestamp("2014-07-01")) & (cal <= pub.index.max())]

    # ---- 1. DB weights vs frozen CSV -------------------------------------------------------------------------
    wm = pd.read_csv(HM / f"{P}_holding_weight_matrix.csv", index_col=0); wm.index = pd.to_datetime(wm.index)
    h = pd.read_csv(REBAL / f"Rebalance_history_by_scid_{P}.csv")
    h["eff"] = pd.to_datetime(h["availableDate"], format="%d/%m/%y %H:%M")
    h["skipped"] = h["skipped"].astype(str).str.lower().eq("true")
    isin2t = {v: k for k, v in cols["ISIN"].items()}
    h["t"] = h["ISIN"].astype(str).str.strip().str.upper().map(isin2t)
    rows = []
    for e, g in h.groupby("eff"):
        if e not in wm.index: continue
        c = pd.Series(0.0, index=wm.columns)
        gg = g.dropna(subset=["t"]); c[gg["t"].values] = pd.to_numeric(gg["weight"]).values
        d = (wm.loc[e] - c).abs()
        rows.append({"eff": e.date(), "skipped": bool(g["skipped"].iloc[0]), "n_db": int((wm.loc[e] > 0).sum()),
                     "n_csv": int((c > 0).sum()), "max_abs_diff": d.max(), "csv_unmapped_isin": int(g["t"].isna().sum())})
    cmp_ = pd.DataFrame(rows); cmp_.to_csv(OUT / "gap_0007_2021_weights_db_vs_csv.csv", index=False)
    print("1. DB weight matrix vs frozen CSV: baskets compared", len(cmp_), "| max |diff| over all", f"{cmp_.max_abs_diff.max():.2e}",
          "| held-set mismatches", int((cmp_.n_db != cmp_.n_csv).sum()), "| unmapped ISINs", int(cmp_.csv_unmapped_isin.sum()))
    print(cmp_[cmp_["eff"].astype(str).between("2020-12-01", "2021-12-31")].to_string(index=False))
    a, b = wm.loc["2021-06-17"], wm.loc["2021-09-16"]
    print("2021-06-17 vs 2021-09-16 (skipped) basket: identical weights ->", bool(np.allclose(a, b)),
          "; stocks:", int((a > 0).sum()))

    # ---- baseline (same as parent_rebuild_hm listed_weights_skip_dropped) ----------------------------------------
    hist_effs = set(h.loc[~h["skipped"], "eff"])
    keep = [e for e in wm.index if e in hist_effs and e >= pd.Timestamp("2014-07-01")]
    wmn = wm.div(wm.sum(axis=1), axis=0)
    base, _ = prh.build(m.loc[keep], px, cal, "avail_ohlc4", wmn.loc[keep])
    print("\nBaseline listed_weights_skip_dropped: 2021 gap = %+.3f pp" % yr_gap(base, pub, 2021))

    # ---- 2. daily gap through 2021 ----------------------------------------------------------------------------
    c = pd.DataFrame({"m": base, "p": pub}).dropna(); c = c / c.iloc[0] * 100
    c21 = c.loc["2020-12-31":"2021-12-31"]; c21 = c21 / c21.iloc[0]
    d = pd.DataFrame({"model_ret_%": c21["m"].pct_change() * 100, "pub_ret_%": c21["p"].pct_change() * 100})
    d["day_gap_pp"] = d["model_ret_%"] - d["pub_ret_%"]
    d["cum_gap_pp"] = (c21["m"] / c21["p"] - 1) * 100
    d.dropna().to_csv(OUT / "gap_0007_2021_daily.csv")
    print("\n2. Largest daily gaps in 2021 (model - published):")
    print(d.dropna().reindex(d.dropna()["day_gap_pp"].abs().sort_values(ascending=False).index).head(8).round(3).to_string())
    j = d["day_gap_pp"].abs().idxmax()
    print("   cumulative gap just before %s: %+.3f pp; after: %+.3f pp; at 2021-12-31: %+.3f pp"
          % (j.date(), d["cum_gap_pp"].shift(1).loc[j], d["cum_gap_pp"].loc[j], d["cum_gap_pp"].iloc[-1]))
    mid = d.loc["2021-03-01":"2021-12-31", "cum_gap_pp"]
    print("   cum gap range after 2021-03-01: min %+.3f max %+.3f (flat => one-off step, not drift)" % (mid.min(), mid.max()))

    # ---- 3. per-stock attribution on the jump day --------------------------------------------------------------
    stk = list(m.columns)
    close = px["close"].reindex(index=cal, columns=stk).ffill()
    eff = max(e for e in keep if e <= j)
    w = wmn.loc[eff]; w = w[w > 0]
    # units at the basket's switch (approx: weights at switch, value 1), then drift to the day before j
    i0 = cal.searchsorted(eff)
    ohlc4 = ((px["open"] + px["high"] + px["low"] + px["close"]).reindex(index=cal, columns=stk) / 4)
    sh = w / ohlc4.loc[cal[i0], w.index]
    prev, day = cal[cal.searchsorted(j) - 1], j
    v0 = sh * close.loc[prev, w.index]
    attr = pd.DataFrame({"weight_at_switch": w, "value_share_before": v0 / v0.sum(),
                         "ret_%_in_ohlc": (close.loc[day, w.index] / close.loc[prev, w.index] - 1) * 100})
    attr["contrib_pp"] = attr["value_share_before"] * attr["ret_%_in_ohlc"]
    attr = attr.sort_values("contrib_pp"); attr.to_csv(OUT / "gap_0007_2021_jumpday_attribution.csv")
    print("\n3. Attribution on %s (basket effective %s). Model day return %.3f%%, published %.3f%%:"
          % (day.date(), eff.date(), d.loc[day, "model_ret_%"], d.loc[day, "pub_ret_%"]))
    print(attr.round(4).to_string())
    pp = "POLYPLEX.NS"
    if pp in px["close"].columns:
        s = px["close"][pp].loc["2021-02-10":"2021-02-24"]
        print("\n   POLYPLEX close in the OHLC file around ex-date 2021-02-17:\n", s.round(2).to_string())
        print("   close(2021-02-16 file) = %.2f ; actual cum close per price_corrections.csv = 911.20 ; ratio = %.6f"
              % (px["close"][pp].loc["2021-02-16"], 911.20 / px["close"][pp].loc["2021-02-16"]))

    # ---- 4. candidate fixes ---------------------------------------------------------------------------------
    res = [("baseline listed_weights_skip_dropped", base)]
    allr = [e for e in wm.index if e >= pd.Timestamp("2014-07-01")]
    nav, _ = prh.build(m.loc[allr], px, cal, "avail_ohlc4", wmn.loc[allr]); res.append(("A. trade the skipped baskets (2020-03-16, 2021-09-16)", nav))
    r2 = [e for e in keep + [pd.Timestamp("2021-09-16")]]; r2 = sorted(set(r2))
    nav, _ = prh.build(m.loc[r2], px, cal, "avail_ohlc4", wmn.loc[r2]); res.append(("B. trade only the 2021-09-16 skipped basket", nav))
    pxc = prh.apply_corrections(px, P)
    nav_c, _ = prh.build(m.loc[keep], pxc, cal, "avail_ohlc4", wmn.loc[keep]); res.append(("C. Polyplex special dividend put back (price_corrections.csv, x1.123274 before 2021-02-17)", nav_c))
    # D: C plus the Redington ordinary dividend (ex 2021-07-16): the only other step >0.3% between ohlcv_eikon and the
    #    unadjusted merged_historical_data_with_rics close for any stock held by 0007 in Dec-2020..Dec-2021 (ratio step +1.196%)
    q = {k: v.copy() for k, v in pxc.items()}
    for k in q: q[k].loc[q[k].index < "2021-07-16", "REDINGTON.NS"] *= 1.01196
    nav_d, _ = prh.build(m.loc[keep], q, cal, "avail_ohlc4", wmn.loc[keep])
    res.append(("D. C plus Redington dividend (x1.01196 before 2021-07-16) - exploratory, NOT in price_corrections.csv", nav_d))
    out = []
    for name, nav in res:
        st = prh.stats(nav, pub, "2019-01-02", "2026-10-22"); g0 = prh.g0_gate(nav, pub)
        out.append({"fix": name, "gap_2021_pp": yr_gap(nav, pub, 2021), "cagr_gap_pp_yr": st["gap_pp_yr"],
                    "worst_year": g0["worst_year"], "worst_year_gap_pp": g0["worst_year_gap_pp"], "G0": g0["overall"] + "/" + g0["yearly"]})
    o = pd.DataFrame(out); o.to_csv(OUT / "gap_0007_2021_fixes.csv", index=False)
    print("\n4. Candidate fixes:"); print(o.round(3).to_string(index=False))

    # factor sweep
    sw = []
    for f in np.round(np.arange(1.00, 1.2001, 0.01), 4):
        q = {k: v.copy() for k, v in px.items()}
        for k in q: q[k].loc[q[k].index < "2021-02-17", pp] *= f
        nav, _ = prh.build(m.loc[keep], q, cal, "avail_ohlc4", wmn.loc[keep]); sw.append({"factor": f, "gap_2021_pp": yr_gap(nav, pub, 2021)})
    sw = pd.DataFrame(sw); sw.to_csv(OUT / "gap_0007_2021_factor_sweep.csv", index=False)
    zero = np.interp(0, sw["gap_2021_pp"][::-1], sw["factor"][::-1])
    print("\n   factor sweep: 2021 gap = 0 at factor ~ %.4f (dividend-implied 1.123274)" % zero)

    # residual: where the corrected model is still off
    cc = pd.DataFrame({"m": nav_c, "p": pub}).dropna(); cc = cc / cc.iloc[0] * 100
    rd = (cc["m"].pct_change() - cc["p"].pct_change()).dropna() * 100
    print("\n   residual after fix C: 2021 gap %+.3f pp; days in 2021 with |daily gap| > 0.1 pp:" % yr_gap(nav_c, pub, 2021))
    print(rd.loc["2021"][rd.loc["2021"].abs() > 0.1].round(3).to_string())


if __name__ == "__main__":
    main()
