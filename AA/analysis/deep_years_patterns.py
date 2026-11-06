# -*- coding: utf-8 -*-
"""
Deep dive, analyst "years": what kind of year does the pair win or lose?

Reads the slice tables written by deep_years_indices.py and writes:

  years_patterns_breakeven.csv  OLS of the yearly gap (pair - bh) on the SC100
                                bh return of the same slice: slope, intercept,
                                R^2 and the break-even SC100 return (gap = 0).
  years_patterns_buckets.csv    mean gap and win count by SC100-return bucket,
                                by the pair's switch count in the year, and by
                                whether the previous calendar year of SC100 was
                                negative (a "year after a down year").
  years_concentration.csv       wealth ratio pair / bh (and pair / sc100) over the
                                sample, and without its best / worst 1-3 years;
                                summed log gap by SC100 regime.
  years_spells_quality.csv      every completed out-spell of the pair (cash
                                sleeve, SC100 and blend legs), classified ex post
                                as "saved" (leg lower at re-entry than at exit) or
                                "whipsaw" (leg higher), with the log gain from
                                sitting out; summarised by exit year and sample.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from why_n100sc100 import OUT, calendar
from triple_and_test import index_levels

DEEP = OUT / "deep"
TIE = 0.001


def main() -> None:
    w = pd.read_csv(DEEP / "years_index_diffs.csv")
    w = w[w["sample"].isin(["OOS", "IS"])].copy()
    rg = pd.read_csv(DEEP / "years_regimes.csv")[["period", "SC100_ret"]]
    w = w.merge(rg, on="period", how="left")

    # previous calendar year's SC100 return, from index levels (full calendar years)
    lv = index_levels(calendar())
    ye = lv["SC100"].dropna().groupby(lv["SC100"].dropna().index.year).last()
    yret = ye.pct_change()
    w["SC100_prev_year_ret"] = w["year"].map(lambda y: yret.get(y - 1, np.nan))

    # ── break-even regression ──────────────────────────────────────────────
    rows = []
    for (leg, sl, smp), g in w.groupby(["leg", "sleeve", "sample"]):
        g = g.dropna(subset=["pair_minus_bh", "SC100_ret"])
        if len(g) < 4:
            continue
        for xname in ("SC100_ret", "bh_ret"):
            x, y = g[xname].values, g["pair_minus_bh"].values
            b, a = np.polyfit(x, y, 1)
            yhat = a + b * x
            r2 = 1 - ((y - yhat) ** 2).sum() / ((y - y.mean()) ** 2).sum()
            rows.append({"leg": leg, "sleeve": sl, "sample": smp, "x": xname, "n": len(g), "slope": b,
                         "intercept_pp": a * 100, "r2": r2, "breakeven_x_pct": -a / b * 100 if b else np.nan,
                         "mean_in_equity": g["pair_in_equity"].mean()})
    pd.DataFrame(rows).to_csv(DEEP / "years_patterns_breakeven.csv", index=False)

    # ── buckets ────────────────────────────────────────────────────────────
    def bucket_ret(v):
        if v < -0.10:
            return "a: SC100 < -10%"
        if v < 0:
            return "b: -10% to 0%"
        if v <= 0.15:
            return "c: 0% to +15%"
        if v <= 0.30:
            return "d: +15% to +30%"
        return "e: > +30%"

    w["ret_bucket"] = w["SC100_ret"].map(bucket_ret)
    w["switch_bucket"] = w["pair_switches"].map(lambda s: "0-2 switches" if s <= 2 else "3 switches" if s == 3 else "4+ switches")
    w["after_down_year"] = np.where(w["SC100_prev_year_ret"] < 0, "SC100 previous year < 0", "SC100 previous year >= 0")
    rows = []
    for dim in ("ret_bucket", "switch_bucket", "after_down_year"):
        for (leg, sl, smp, b), g in w.groupby(["leg", "sleeve", "sample", dim]):
            x = g["pair_minus_bh"]
            rows.append({"dimension": dim, "bucket": b, "leg": leg, "sleeve": sl, "sample": smp, "n": len(g),
                         "periods": " ".join(g["period"].astype(str)),
                         "mean_pair_minus_bh_pp": x.mean() * 100, "median_pair_minus_bh_pp": x.median() * 100,
                         "pair_beats_bh": int((x > TIE).sum()), "pair_loses": int((x < -TIE).sum()),
                         "mean_pair_minus_sc100_pp": g["pair_minus_sc100"].mean() * 100,
                         "mean_SC100_ret_pct": g["SC100_ret"].mean() * 100,
                         "mean_pair_switches": g["pair_switches"].mean(),
                         "mean_pair_in_equity": g["pair_in_equity"].mean()})
    pd.DataFrame(rows).to_csv(DEEP / "years_patterns_buckets.csv", index=False)

    # ── concentration: wealth ratio pair / bh without the best years ───────
    rows = []
    for (leg, sl, smp), g in w.groupby(["leg", "sleeve", "sample"]):
        lg = (np.log1p(g["pair_ret"]) - np.log1p(g["bh_ret"])).values
        per = g["period"].astype(str).values
        order = np.argsort(-lg)
        d = {"leg": leg, "sleeve": sl, "sample": smp, "n": len(g), "wealth_ratio_all": float(np.exp(lg.sum()))}
        for k in (1, 2, 3):
            keep = np.ones(len(lg), bool)
            keep[order[:k]] = False
            d[f"drop_best_{k}"] = " ".join(per[order[:k]])
            d[f"wealth_ratio_without_best_{k}"] = float(np.exp(lg[keep].sum()))
        for k in (1, 2, 3):
            keep = np.ones(len(lg), bool)
            keep[order[::-1][:k]] = False
            d[f"drop_worst_{k}"] = " ".join(per[order[::-1][:k]])
            d[f"wealth_ratio_without_worst_{k}"] = float(np.exp(lg[keep].sum()))
        for gname in ("bull", "bear", "flat"):
            m = (g["SC100_label"] == gname).values
            d[f"log_gap_sum_{gname}"] = float(lg[m].sum())
        # the same against the sc100 rule
        ls = (np.log1p(g["pair_ret"]) - np.log1p(g["sc100_ret"])).values
        o2 = np.argsort(-ls)
        d["vs_sc100_wealth_ratio_all"] = float(np.exp(ls.sum()))
        for k in (1, 2, 3):
            keep = np.ones(len(ls), bool)
            keep[o2[:k]] = False
            d[f"vs_sc100_drop_best_{k}"] = " ".join(per[o2[:k]])
            d[f"vs_sc100_wealth_ratio_without_best_{k}"] = float(np.exp(ls[keep].sum()))
        for gname in ("bull", "bear", "flat"):
            m = (g["SC100_label"] == gname).values
            d[f"vs_sc100_log_gap_sum_{gname}"] = float(ls[m].sum())
        rows.append(d)
    pd.DataFrame(rows).to_csv(DEEP / "years_concentration.csv", index=False)

    # ── out-spell quality ──────────────────────────────────────────────────
    sp = pd.read_csv(DEEP / "years_out_spells.csv", parse_dates=["exit_trade_close", "entry_trade_close"])
    sp = sp[(sp["rule"].isin(["pair", "sc100"])) & (sp["leg"].isin(["SC100", "blend", "N100"]))].copy()
    sp["sample"] = np.where(sp["exit_trade_close"] <= pd.Timestamp("2021-10-29"), "OOS", "IS")
    sp["exit_year"] = sp["exit_trade_close"].dt.year
    sp["outcome_ex_post"] = np.where(sp["leg_ret_while_out"] < 0, "saved (leg fell while out)",
                                     "whipsaw (leg rose while out)")
    sp["log_gain_from_out"] = np.log1p(sp["cash_ret_while_out"]) - np.log1p(sp["leg_ret_while_out"])
    sp.to_csv(DEEP / "years_spells_classified.csv", index=False)
    rows = []
    for keys, g in list(sp.groupby(["rule", "leg", "sample"])) + list(sp.groupby(["rule", "leg", "sample", "exit_year"])):
        d = dict(zip(["rule", "leg", "sample", "exit_year"], list(keys) + ([None] if len(keys) == 3 else [])))
        done = g[~g["open_at_end"]]
        sv = g[g["leg_ret_while_out"] < 0]
        ws = g[g["leg_ret_while_out"] >= 0]
        d.update({"spells": len(g), "saved": len(sv), "whipsaw": len(ws), "open_at_end": int(g["open_at_end"].sum()),
                  "median_weeks_out": g["weeks_out"].median(),
                  "median_leg_ret_while_out_pct": g["leg_ret_while_out"].median() * 100,
                  "mean_leg_ret_while_out_pct": g["leg_ret_while_out"].mean() * 100,
                  "sum_log_gain_saved": sv["log_gain_from_out"].sum(),
                  "sum_log_gain_whipsaw": ws["log_gain_from_out"].sum(),
                  "sum_log_gain_all": g["log_gain_from_out"].sum(),
                  "top3_log_gain": g["log_gain_from_out"].nlargest(3).sum(),
                  "top3_spells": "; ".join(f"{r.exit_trade_close.date()}->{r.entry_trade_close.date()} ({r.leg_ret_while_out * 100:+.0f}%)"
                                           for r in g.nlargest(3, "log_gain_from_out").itertuples())})
        rows.append(d)
    pd.DataFrame(rows).to_csv(DEEP / "years_spells_quality.csv", index=False)
    # by exit trigger (which index was SELL when the pair left equity)
    tr = sp[sp["rule"] == "pair"].groupby(["leg", "sample", "exit_trigger_sell"]).agg(
        spells=("leg_ret_while_out", "size"), saved=("leg_ret_while_out", lambda x: int((x < 0).sum())),
        median_leg_ret_while_out_pct=("leg_ret_while_out", lambda x: x.median() * 100),
        sum_log_gain=("log_gain_from_out", "sum"), median_weeks_out=("weeks_out", "median"),
        spells_list=("exit_trade_close", lambda x: " ".join(str(d.date()) for d in x))).reset_index()
    tr.to_csv(DEEP / "years_spells_by_trigger.csv", index=False)

    pd.set_option("display.width", 250)
    pd.set_option("display.max_colwidth", 200)
    be = pd.DataFrame([r for r in []])
    print(pd.read_csv(DEEP / "years_patterns_breakeven.csv").query("x == 'SC100_ret' and sleeve == 'cash'").round(3).to_string(index=False))
    bk = pd.read_csv(DEEP / "years_patterns_buckets.csv")
    print(bk[(bk.leg.isin(["SC100", "blend", "N100"])) & (bk.sleeve == "cash")].round(2).to_string(index=False))
    q = pd.read_csv(DEEP / "years_spells_quality.csv")
    print(q[q["exit_year"].isna()].round(3).to_string(index=False))


if __name__ == "__main__":
    main()
