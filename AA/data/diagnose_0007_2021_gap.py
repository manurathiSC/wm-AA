# -*- coding: utf-8 -*-
"""
Diagnosis of the SCMO_0007 calendar-2021 gap (T03 Step 1, F-AA-D14). Reproduces every number the finding cites.

    python data/diagnose_0007_2021_gap.py [--scan]        (from AA/; needs data/parent_rebuild_hm.py to have run;
                                                           the DB parts need the read-only Postgres login in wm-aiReports/.env)

A. Daily model-minus-published difference for SCMO_0007 (listed weights, skipped baskets dropped): the biggest days,
   uncorrected and corrected (data/holdings_matrix/price_corrections.csv).
B. Polyplex around the ex-date, ohlcv_eikon (D18's source) against merged_historical_data_with_rics: the ratio step and the
   adjustment factor, compared with the factor from the Rs 100 dividend and the cum close.
C. (--scan, about 3 minutes) for every stock ever held by each of the four parents, the ratio ohlcv_eikon / merged close:
   every step of 2% or more on a date the stock was in the basket in force. Writes data/parent_rebuild_hm/price_source_steps.csv.

Inputs taken from outside the DB: the Rs 100 amount and the ex-date 2021-02-17 (Motilal Oswal filing summary, Business
Standard 2021-02-10; the DB's corp_announcements has nothing for that date).
"""
from __future__ import annotations

import importlib.util
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
AA = Path(__file__).resolve().parents[1]
HM = AA / "data" / "holdings_matrix"
OUT = AA / "data" / "parent_rebuild_hm"
PARENTS = ["SCMO_0003", "SCMO_0007", "SCMO_0010", "SCMO_0029"]
EX_DATE, DIVIDEND, QUOTE_ID = "2021-02-17", 100.0, 55837407889        # Polyplex INE633B01018


def connect():
    spec = importlib.util.spec_from_file_location("bof", AA / "data" / "build_ohlc_file.py")
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m.connect()


def part_a():
    print("== A. SCMO_0007 daily model - published (bp), largest absolute days ==")
    d = pd.read_csv(OUT / "daily.csv", parse_dates=["date"])
    for v in ("listed_weights_skip_dropped", "listed_weights_skip_dropped_corrected"):
        x = d[(d.parent == "SCMO_0007") & (d.variant == v)].set_index("date")
        diff = (x["model"].pct_change() - x["pub"].pct_change()) * 1e4
        print(f"-- {v}")
        print(diff.abs().sort_values(ascending=False).head(6).round(1).to_string())
        y = diff.loc["2021-01-01":"2021-12-31"]
        print(f"   calendar 2021: sum of daily gaps {y.sum():+.1f} bp; excluding {EX_DATE}: {y.drop(pd.Timestamp(EX_DATE)).sum():+.1f} bp")
    yy = pd.read_csv(OUT / "yearly.csv")
    yy = yy[(yy.parent == "SCMO_0007") & yy.variant.str.startswith("listed")]
    print("-- calendar-year gap, pp"); print(yy.pivot(index="year", columns="variant", values="gap_pp").round(3).to_string())


def part_b(c):
    print("\n== B. Polyplex around the ex-date: ohlcv_eikon vs merged_historical_data_with_rics ==")
    e = pd.read_sql("select date, close from ohlcv_eikon where quote_id=%(q)s and date between '2021-02-10' and '2021-02-24' order by date",
                    c, params={"q": QUOTE_ID})
    ric = pd.read_sql("select distinct ric from ohlcv_eikon where quote_id=%(q)s", c, params={"q": QUOTE_ID}).ric.iloc[0]
    m = pd.read_sql("select date, close as merged from merged_historical_data_with_rics where ric=%(r)s and date between '2021-02-10' and '2021-02-24' order by date",
                    c, params={"r": ric})
    x = e.merge(m, on="date"); x["close"] = x["close"].astype(float)
    x["eikon/merged"] = x["close"] / x["merged"]
    x["eikon ret %"] = x["close"].pct_change() * 100; x["merged ret %"] = x["merged"].pct_change() * 100
    print(x.round(4).to_string(index=False))
    pre, post = x[x.date < pd.Timestamp(EX_DATE).date()].iloc[-1], x[x.date == pd.Timestamp(EX_DATE).date()].iloc[0]
    step = post["eikon/merged"] / pre["eikon/merged"]
    cum = float(pre["merged"])
    print(f"ratio step across the ex-date: {pre['eikon/merged']:.4f} -> {post['eikon/merged']:.4f}  (x{step:.5f})")
    print(f"factor from the dividend: (cum close {cum:.2f} - {DIVIDEND:.0f}) / {cum:.2f} = {(cum - DIVIDEND) / cum:.5f}; inverse (the correction) {cum / (cum - DIVIDEND):.6f}")
    print(f"factor in price_corrections.csv: {pd.read_csv(HM / 'price_corrections.csv').factor.iloc[0]}")
    print(f"traded drop on the ex-date (merged close): {post['merged ret %']:.2f}%; Eikon-adjusted: {post['eikon ret %']:+.2f}%")


def part_c(c):
    print("\n== C. every held stock: ohlcv_eikon / merged close, steps >= 2% while in the basket ==")
    rows = []
    for p in PARENTS:
        cols = pd.read_csv(HM / f"{p}_columns.csv")
        w = pd.read_csv(HM / f"{p}_holding_weight_matrix.csv", index_col=0); w.index = pd.to_datetime(w.index)
        o = pd.read_csv(HM / f"{p}_ohlc.csv", parse_dates=["date"]).drop_duplicates(["date", "stock"])
        cl = o[o.src == "db"].pivot(index="date", columns="stock", values="close")
        q = pd.read_sql("select distinct quote_id, isin from symbology_changes where isin=any(%(i)s)", c, params={"i": list(cols.ISIN)})
        qr = pd.read_sql("select distinct quote_id, ric from ohlcv_eikon where quote_id=any(%(q)s)", c,
                         params={"q": [int(x) for x in q.quote_id.unique()]})
        qr = qr.merge(q.drop_duplicates("quote_id"), on="quote_id").merge(cols[["stock", "ISIN"]], left_on="isin", right_on="ISIN")
        m = pd.read_sql("select ric, date, close from merged_historical_data_with_rics where ric=any(%(r)s) and date>='2014-07-01'", c,
                        params={"r": list(qr.ric.unique())})
        m["date"] = pd.to_datetime(m["date"]); m = m.merge(qr[["ric", "stock"]].drop_duplicates(), on="ric")
        mc = m.drop_duplicates(["date", "stock"]).pivot(index="date", columns="stock", values="close")
        no_merged = [s for s in cl.columns if s not in mc]
        print(f"{p}: {len(cl.columns)} stocks, no merged series for {len(no_merged)} (delisted names): {no_merged}")
        for s in cl.columns:
            if s in no_merged: continue
            r = (cl[s] / mc[s]).dropna()
            if len(r) < 20: continue
            step = r / r.shift(1) - 1
            for d, v in step[step.abs() >= 0.02].items():
                held = float(w.loc[:d, s].iloc[-1]) if len(w.loc[:d]) else 0.0
                if held > 0:
                    rows.append({"parent": p, "stock": s, "date": d.date(), "ratio_step_%": round(v * 100, 2), "basket_weight": round(held, 4)})
    df = pd.DataFrame(rows); df.to_csv(OUT / "price_source_steps.csv", index=False)
    print(f"{len(df)} steps; pairs of opposite-sign steps on adjacent sessions are one-day glitches in merged")
    print(df[df.date >= pd.Timestamp("2019-01-02").date()].to_string(index=False))


def part_d(c, thr=0.003):
    """Finer scan, SCMO_0007 only, baskets in force 2020-12-17 .. 2021-12-31: steps >= 0.3% (ordinary dividends show up here)."""
    print(f"\n== D. SCMO_0007, steps >= {thr * 100:.1f}% in ohlcv_eikon / merged while in the basket, 2020-12-17 .. 2021-12-31 ==")
    p = "SCMO_0007"
    cols = pd.read_csv(HM / f"{p}_columns.csv")
    w = pd.read_csv(HM / f"{p}_holding_weight_matrix.csv", index_col=0); w.index = pd.to_datetime(w.index)
    o = pd.read_csv(HM / f"{p}_ohlc.csv", parse_dates=["date"]).drop_duplicates(["date", "stock"])
    cl = o[o.src == "db"].pivot(index="date", columns="stock", values="close")
    q = pd.read_sql("select distinct quote_id, isin from symbology_changes where isin=any(%(i)s)", c, params={"i": list(cols.ISIN)})
    qr = pd.read_sql("select distinct quote_id, ric from ohlcv_eikon where quote_id=any(%(q)s)", c, params={"q": [int(x) for x in q.quote_id.unique()]})
    qr = qr.merge(q.drop_duplicates("quote_id"), on="quote_id").merge(cols[["stock", "ISIN"]], left_on="isin", right_on="ISIN")
    m = pd.read_sql("select ric, date, close from merged_historical_data_with_rics where ric=any(%(r)s) and date between '2020-11-01' and '2022-01-31'",
                    c, params={"r": list(qr.ric.unique())})
    m["date"] = pd.to_datetime(m["date"]); m = m.merge(qr[["ric", "stock"]].drop_duplicates(), on="ric")
    mc = m.drop_duplicates(["date", "stock"]).pivot(index="date", columns="stock", values="close")
    rows = []
    for s in mc.columns:
        r = (cl[s] / mc[s]).dropna().loc["2020-11-01":"2022-01-31"]
        step = (r / r.shift(1) - 1).loc["2020-12-17":"2021-12-31"]
        for d, v in step[step.abs() >= thr].items():
            held = float(w.loc[:d, s].iloc[-1])
            if held > 0:
                rows.append({"stock": s, "date": d.date(), "ratio_step_%": round(v * 100, 3), "basket_weight": round(held, 4)})
    print(pd.DataFrame(rows).sort_values("date").to_string(index=False))


def main():
    part_a()
    c = connect()
    part_b(c)
    part_d(c)
    if "--scan" in sys.argv:
        part_c(c)
    c.close()


if __name__ == "__main__":
    main()
