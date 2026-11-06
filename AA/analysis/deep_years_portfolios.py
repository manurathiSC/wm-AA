# -*- coding: utf-8 -*-
"""
Deep dive, analyst "years": calendar-year returns and worst falls of the
portfolio NAVs in evidence/why_n100sc100/triple_portfolio_curves.csv.

  * "oos|<book>|<rule>|<sleeve>": the four parents' real baskets on the
    unit-based harness, 2014-07-04 -> 2021-10-29 (OUT OF SAMPLE).
  * "in-sample|<book>|<rule>|<sleeve>": the four AA books, 2021-11-03 ->
    2026-08-21 (IN-SAMPLE: the pair was chosen on this window).
  * Rules: pair, triple, sc100, current rule, parent (parent: gold+cash only,
    and it never goes to the sleeve). Sleeves: gold+cash (50/50), cash, gold.

Per slice (calendar year inside each sample; first and last years partial):
return, worst fall on daily closes and on Friday closes. Per book and the
average of the 4 books (mean of the 4 books' yearly figures).

Writes evidence/why_n100sc100/deep/years_portfolio_*.csv.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from why_n100sc100 import OUT, calendar
from triple_and_test import index_levels

DEEP = OUT / "deep"
RN = {"N100 AND SC100": "pair", "N100 AND MC100 AND SC100": "triple", "SC100 only": "sc100",
      "current rule": "current", "parent": "parent"}
SN = {"gold+cash": "50/50", "cash": "cash", "gold": "gold"}
TIE = 0.001


def dd(x: pd.Series) -> float:
    return float((x / x.cummax() - 1).min())


def main() -> None:
    pc = pd.read_csv(OUT / "triple_portfolio_curves.csv", index_col=0, parse_dates=True)
    rows = []
    for col in pc.columns:
        smp, book, rule, sl = col.split("|")
        nav = pc[col].dropna()
        wk = nav.resample("W-FRI").last()
        smp_l = "OOS" if smp == "oos" else "IS"
        for y in sorted(set(nav.index.year)):
            in_y = nav.index[nav.index.year == y]
            prev = nav.index[nav.index < in_y[0]]
            base = prev[-1] if len(prev) else in_y[0]
            last = in_y[-1]
            seg = nav[(nav.index >= base) & (nav.index <= last)]
            f = wk[(wk.index > base) & (wk.index <= last)]
            fseg = pd.concat([nav.loc[[base]], f, nav.loc[[last]]])
            fseg = fseg[~fseg.index.duplicated(keep="last")].sort_index()
            partial = (len(prev) == 0) or last < pd.Timestamp(f"{y}-12-24")
            rows.append({"sample": smp_l, "book": book, "rule": RN[rule], "sleeve": SN[sl],
                         "period": f"{y}" + ("p" if partial else ""), "year": y, "partial": partial,
                         "start_close": base.date(), "end_close": last.date(),
                         "ret": float(seg.iloc[-1] / seg.iloc[0] - 1), "dd_daily": dd(seg), "dd_friday": dd(fseg)})
    yr = pd.DataFrame(rows)
    # parent never goes to the sleeve: copy it under every sleeve for the comparisons
    par = yr[yr["rule"] == "parent"]
    yr = pd.concat([yr[yr["rule"] != "parent"]] + [par.assign(sleeve=s) for s in ("50/50", "cash", "gold")],
                   ignore_index=True)
    yr.to_csv(DEEP / "years_portfolio_yearly.csv", index=False)

    # average of the 4 books
    key = ["sample", "sleeve", "period", "year", "partial", "rule"]
    av = yr.groupby(key).agg(books=("book", "size"), ret_avg=("ret", "mean"), dd_daily_avg=("dd_daily", "mean"),
                             dd_friday_avg=("dd_friday", "mean"), ret_min=("ret", "min"),
                             ret_max=("ret", "max")).reset_index()
    av.to_csv(DEEP / "years_portfolio_avg.csv", index=False)

    # pair versus the others, per slice: avg-of-4 gap, and books (of 4) where the pair is ahead
    wide = yr.pivot_table(index=["sample", "sleeve", "period", "year", "partial", "book"], columns="rule",
                          values=["ret", "dd_daily", "dd_friday"], aggfunc="first")
    wide.columns = [f"{r}_{m}" for m, r in wide.columns]
    wide = wide.reset_index()
    for o in ("parent", "sc100", "current", "triple"):
        wide[f"pair_minus_{o}"] = wide["pair_ret"] - wide[f"{o}_ret"]
        wide[f"pair_dd_minus_{o}_dd_daily"] = wide["pair_dd_daily"] - wide[f"{o}_dd_daily"]
    wide.to_csv(DEEP / "years_portfolio_book_gaps.csv", index=False)
    g = wide.groupby(["sample", "sleeve", "period", "year", "partial"])
    vs = g.agg(**{f"avg_{c}": (c, "mean") for c in ("pair_ret", "parent_ret", "sc100_ret", "current_ret", "triple_ret",
                                                    "pair_dd_daily", "parent_dd_daily", "sc100_dd_daily",
                                                    "current_dd_daily", "pair_dd_friday", "parent_dd_friday")},
               **{f"avg_pair_minus_{o}": (f"pair_minus_{o}", "mean") for o in ("parent", "sc100", "current", "triple")},
               **{f"books_pair_beats_{o}": (f"pair_minus_{o}", lambda x: int((x > TIE).sum()))
                  for o in ("parent", "sc100", "current", "triple")}).reset_index()
    for o in ("parent", "sc100", "current", "triple"):
        vs[f"pair_beats_{o}_avg"] = vs[f"avg_pair_minus_{o}"] > TIE
    # hindsight regime of each slice, from SC100 / N100 index levels over the SAME dates
    lv = index_levels(calendar())
    se = yr.drop_duplicates(["sample", "period"])[["sample", "period", "start_close", "end_close"]]
    reg = []
    for _, r in se.iterrows():
        a, b = pd.Timestamp(r["start_close"]), pd.Timestamp(r["end_close"])
        d = {"sample": r["sample"], "period": r["period"]}
        for k in ("SC100", "N100"):
            x = lv[k].loc[a:b].dropna()
            ret, ddv = float(x.iloc[-1] / x.iloc[0] - 1), dd(x)
            d[f"{k}_ret_same_dates"] = ret
            d[f"{k}_dd_same_dates"] = ddv
            d[f"{k}_label"] = "bull" if ret > 0.15 else "bear" if ret < -0.10 else "flat"
            d[f"{k}_V"] = bool(ddv < -0.20 and ret > 0)
        reg.append(d)
    vs = vs.merge(pd.DataFrame(reg), on=["sample", "period"], how="left")
    vs = vs.sort_values(["sample", "sleeve", "year"], key=lambda s: s.map({"OOS": 0, "IS": 1}) if s.name == "sample" else s)
    vs.to_csv(DEEP / "years_portfolio_pair_vs.csv", index=False)

    # summary counts across slices
    rows = []
    for (smp, sl), gg in vs.groupby(["sample", "sleeve"]):
        r = {"sample": smp, "sleeve": sl, "slices": len(gg), "periods": " ".join(gg["period"])}
        for o in ("parent", "sc100", "current", "triple"):
            x = gg[f"avg_pair_minus_{o}"]
            r[f"slices_pair_beats_{o}_avg"] = int((x > TIE).sum())
            r[f"slices_tie_{o}_avg"] = int((x.abs() <= TIE).sum())
            r[f"slices_pair_behind_{o}_avg"] = int((x < -TIE).sum())
            r[f"book_years_pair_beats_{o}"] = int(gg[f"books_pair_beats_{o}"].sum())
            r[f"mean_gap_vs_{o}_pp"] = x.mean() * 100
        r["book_years"] = int(len(gg) * 4)
        r["pair_compound_avg_pct"] = (np.prod(1 + gg["avg_pair_ret"]) - 1) * 100
        r["parent_compound_avg_pct"] = (np.prod(1 + gg["avg_parent_ret"]) - 1) * 100
        rows.append(r)
    pd.DataFrame(rows).to_csv(DEEP / "years_portfolio_summary.csv", index=False)

    pd.set_option("display.width", 250)
    x = vs[["sample", "sleeve", "period", "avg_pair_ret", "avg_parent_ret", "avg_sc100_ret", "avg_current_ret",
            "avg_triple_ret", "avg_pair_dd_daily", "avg_parent_dd_daily", "books_pair_beats_parent",
            "books_pair_beats_sc100", "books_pair_beats_current"]]
    print(x.round(3).to_string(index=False))
    print(pd.DataFrame(rows).round(2).T.to_string())


if __name__ == "__main__":
    main()
