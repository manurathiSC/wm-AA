# -*- coding: utf-8 -*-
"""
Deep study, parts 1 and 2: every calendar year, and every 10% swing.

Part 1 - years. Continuous whole-history NAVs (deep_core_common) sliced by
calendar year: return, intra-year worst fall (daily and Friday closes),
share of sessions in equity, switches. Hindsight year labels from SC100
buy-and-hold: bull (> +15%), bear (< -10%), flat; "V" = intra-year fall
deeper than 20% but the year ended positive.

Part 2 - swings. 10% zig-zag pivots on Friday closes of each leg. Every down
leg (a fall of 10%+) and up leg (a rise of 10%+), with each rule's NAV return
over the leg, exit / entry timing, and speed classes. Also false exits.

Writes evidence/why_n100sc100/deep/years_*.csv and swings_*.csv.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from deep_core_common import (DEEP, IS0, LEGS, OOS_END, S0, S_GOLD, build, dd, friday, load, zigzag)

YEARS = list(range(2007, 2027))


def year_slices(idx: pd.DatetimeIndex):
    for y in YEARS:
        a = pd.Timestamp(f"{y}-01-01") if y > 2007 else S0
        b = pd.Timestamp(f"{y}-12-31")
        yield y, a, b


def part_years(N, W):
    rows = []
    for col in N.columns:
        leg, rule, sl = col.split("|")
        nav, w = N[col].dropna(), W[col]
        for y, a, b in year_slices(nav.index):
            seg = nav.loc[a:b]
            if len(seg) < 20:
                continue
            prev = nav.loc[:a - pd.Timedelta(days=1)]
            base = prev.iloc[-1] if len(prev) else seg.iloc[0]
            path = pd.concat([pd.Series([base], index=[seg.index[0] - pd.Timedelta(days=1)]), seg])
            ws = w.loc[seg.index]
            rows.append({"leg": leg, "rule": rule, "sleeve": sl, "year": y,
                         "partial": (y == 2007) or (y == 2026) or (sl != "cash" and y == 2014),
                         "sample": "in-sample" if y >= 2022 else ("mixed" if y == 2021 else "oos"),
                         "ret": float(seg.iloc[-1] / base - 1), "worst_daily": dd(path),
                         "worst_friday": dd(friday(path)), "in_equity": float(ws.mean()),
                         "switches": int((ws.diff().abs() > 0).sum())})
    Y = pd.DataFrame(rows)
    # hindsight labels from SC100 and N100 buy-and-hold (cash run; bh has no sleeve)
    lab = []
    for y in YEARS:
        rec = {"year": y}
        for leg in ("SC100", "N100"):
            x = Y[(Y.leg == leg) & (Y.rule == "bh") & (Y.sleeve == "cash") & (Y.year == y)]
            if not len(x):
                continue
            ret, wd = x.ret.iloc[0], x.worst_friday.iloc[0]
            rec[f"{leg}_ret"], rec[f"{leg}_worst"] = ret, wd
            rec[f"{leg}_label"] = "bull" if ret > 0.15 else "bear" if ret < -0.10 else "flat"
            rec[f"{leg}_V"] = bool(wd < -0.20 and ret > 0)
        lab.append(rec)
    L = pd.DataFrame(lab)
    Y = Y.merge(L[["year", "SC100_label", "SC100_V", "N100_label"]], on="year", how="left")
    Y.to_csv(DEEP / "years_long.csv", index=False)
    L.to_csv(DEEP / "years_labels.csv", index=False)

    # wide: pair vs bh vs sc100 per year, per leg, cash sleeve (and 50/50 from 2014)
    wide = []
    for (leg, sl, y), g in Y.groupby(["leg", "sleeve", "year"]):
        g = g.set_index("rule")
        if not {"pair", "bh", "sc100"} <= set(g.index):
            continue
        rec = {"leg": leg, "sleeve": sl, "year": y, "sample": g["sample"].iloc[0],
               "SC100_label": g["SC100_label"].iloc[0], "SC100_V": g["SC100_V"].iloc[0]}
        for ru in ("pair", "triple", "sc100", "own", "bh"):
            if ru in g.index:
                rec[f"{ru}_ret"] = g.loc[ru, "ret"]
                rec[f"{ru}_worst_friday"] = g.loc[ru, "worst_friday"]
        rec["pair_in_equity"] = g.loc["pair", "in_equity"]
        rec["pair_switches"] = g.loc["pair", "switches"]
        rec["pair_minus_bh"] = rec["pair_ret"] - rec["bh_ret"]
        rec["pair_minus_sc100"] = rec["pair_ret"] - rec["sc100_ret"]
        rec["triple_minus_pair"] = rec["triple_ret"] - rec["pair_ret"]
        wide.append(rec)
    Wd = pd.DataFrame(wide)
    Wd.to_csv(DEEP / "years_wide.csv", index=False)

    # summaries: out of sample = full years 2008-2020 plus 2007 (from Jul) - 2021 is split, left out
    oos = Wd[(Wd.year <= 2020)]
    s = []
    for (leg, sl), g in oos.groupby(["leg", "sleeve"]):
        s.append({"leg": leg, "sleeve": sl, "years": len(g),
                  "pair_beats_bh": int((g.pair_minus_bh > 0).sum()),
                  "pair_beats_sc100": int((g.pair_minus_sc100 > 0).sum()),
                  "pair_worst_shallower_than_bh": int((g.pair_worst_friday > g.bh_worst_friday).sum()),
                  "avg_pair_minus_bh": g.pair_minus_bh.mean(), "median_pair_minus_bh": g.pair_minus_bh.median(),
                  "avg_pair_minus_sc100": g.pair_minus_sc100.mean()})
    S = pd.DataFrame(s)
    S.to_csv(DEEP / "years_summary_oos.csv", index=False)
    byreg = (oos[oos.sleeve == "cash"].assign(reg=lambda d: np.where(d.SC100_V, "V (fell >20%, ended up)", d.SC100_label))
             .groupby(["leg", "reg"]).agg(years=("year", "size"), yrs=("year", lambda x: ",".join(map(str, x))),
                                          avg_bh=("bh_ret", "mean"), avg_pair=("pair_ret", "mean"),
                                          avg_sc100=("sc100_ret", "mean"),
                                          avg_pair_minus_bh=("pair_minus_bh", "mean"),
                                          pair_beats_bh=("pair_minus_bh", lambda x: int((x > 0).sum())),
                                          avg_pair_minus_sc100=("pair_minus_sc100", "mean"),
                                          avg_pair_worst=("pair_worst_friday", "mean"),
                                          avg_bh_worst=("bh_worst_friday", "mean")).reset_index())
    byreg.to_csv(DEEP / "years_by_regime_oos.csv", index=False)
    return Y, Wd, S, byreg


def part_swings(N, W, px, sg):
    rows = []
    fx_rows = []
    for leg in LEGS:
        p = friday(px[leg].loc[pd.Timestamp("2006-01-01"):])
        piv = zigzag(p, 0.10)
        for k in range(len(piv) - 1):
            (t0, a), (t1, b) = piv[k], piv[k + 1]
            kind = "fall" if t0.startswith("H") else "rise"
            depth = float(p[b] / p[a] - 1)
            weeks = int(round((b - a).days / 7))
            rec = {"leg": leg, "kind": kind, "start": a.date(), "end": b.date(), "weeks": weeks,
                   "index_move": depth, "provisional": piv[k + 1][0].endswith("*"),
                   "sample": "in-sample" if a >= IS0 else "oos" if b <= OOS_END else "straddles"}
            if kind == "fall":
                rec["size"] = "20%+" if depth <= -0.20 else "10-20%"
                rec["speed"] = "fast (<=13w)" if weeks <= 13 else "slow (>13w)"
            else:
                prev = rows[-1] if rows and rows[-1]["leg"] == leg and rows[-1]["kind"] == "fall" else None
                rec["after"] = (prev["size"] + ", " + prev["speed"]) if prev else ""
                rec["speed"] = "fast (<=13w)" if weeks <= 13 else "slow (>13w)"
            for sl in ("cash", "50/50"):
                for rule in ("pair", "triple", "sc100", "own", "bh"):
                    col = f"{leg}|{rule}|{sl}"
                    if col not in N:
                        continue
                    nav = N[col].dropna()
                    if a < nav.index[0] + pd.Timedelta(days=7):
                        continue
                    na, nb = nav.asof(a), nav.asof(b)
                    rec[f"{rule}_{sl}"] = float(nb / na - 1)
                    if sl == "cash":
                        w = W[col]
                        seg = w.loc[a:b]
                        rec[f"{rule}_in_at_start"] = float(w.asof(a))
                        rec[f"{rule}_share_in"] = float(seg.mean())
                        pxs = px[leg].reindex(seg.index)
                        if kind == "fall":
                            ex = seg[seg == 0]
                            if rec[f"{rule}_in_at_start"] == 0:
                                rec[f"{rule}_exit_fall"] = 0.0
                            elif len(ex):
                                rec[f"{rule}_exit_fall"] = float(pxs[ex.index[0]] / px[leg].asof(a) - 1)
                        else:
                            en = seg[seg == 1]
                            if rec[f"{rule}_in_at_start"] == 1:
                                rec[f"{rule}_entry_rise"] = 0.0
                            elif len(en):
                                rec[f"{rule}_entry_rise"] = float(pxs[en.index[0]] / px[leg].asof(a) - 1)
            rows.append(rec)
        # false exits on this leg (cash runs)
        for rule in ("pair", "triple", "sc100", "own"):
            col = f"{leg}|{rule}|cash"
            if col not in W:
                continue
            w = W[col]
            exits = w.index[(w.diff() < 0)]
            pl = px[leg].reindex(w.index)
            cash = N[f"{leg}|bh|cash"]  # placeholder for index; cash leg below
            for e in exits:
                i = w.index.get_loc(e)
                if i + 130 >= len(w):
                    continue
                lvl = pl.iloc[i - 1]
                fut = pl.iloc[i:i + 130]
                further = bool(fut.min() <= lvl * 0.90)
                r13 = float(pl.iloc[min(i + 65, len(pl) - 1)] / lvl - 1)
                fx_rows.append({"leg": leg, "rule": rule, "exit": e.date(),
                                "sample": "in-sample" if e >= IS0 else "oos",
                                "further_10pct_fall_26w": further, "index_13w_after": r13})
    Sw = pd.DataFrame(rows)
    Sw.to_csv(DEEP / "swings_all.csv", index=False)
    FX = pd.DataFrame(fx_rows)
    FX.to_csv(DEEP / "swings_exits.csv", index=False)

    # aggregates, out of sample, cash sleeve
    agg = []
    o = Sw[(Sw["sample"] == "oos") & ~Sw.provisional]
    for (leg, kind), g in o.groupby(["leg", "kind"]):
        for key, gg in [("all", g)] + ([(f"{s}", x) for s, x in g.groupby("size")] if kind == "fall" else [(f"{s}", x) for s, x in g.groupby("speed")]):
            rec = {"leg": leg, "kind": kind, "group": key, "n": len(gg), "avg_index_move": gg.index_move.mean()}
            for rule in ("pair", "triple", "sc100", "own", "bh"):
                c = f"{rule}_cash"
                if c in gg:
                    rec[f"avg_{rule}"] = gg[c].mean()
                    rec[f"sum_log_{rule}"] = float(np.log1p(gg[c].dropna()).sum())
            if "pair_exit_fall" in gg:
                rec["pair_median_exit_fall"] = gg["pair_exit_fall"].median()
                rec["sc100_median_exit_fall"] = gg.get("sc100_exit_fall", pd.Series(dtype=float)).median()
            if "pair_entry_rise" in gg:
                rec["pair_median_entry_rise"] = gg["pair_entry_rise"].median()
                rec["sc100_median_entry_rise"] = gg.get("sc100_entry_rise", pd.Series(dtype=float)).median()
            agg.append(rec)
    A = pd.DataFrame(agg)
    A.to_csv(DEEP / "swings_summary_oos.csv", index=False)
    fx = (FX.groupby(["leg", "rule", "sample"]).agg(exits=("exit", "size"),
                                                    real_share=("further_10pct_fall_26w", "mean"),
                                                    avg_13w_after=("index_13w_after", "mean")).reset_index())
    fx2 = (FX[~FX.further_10pct_fall_26w].groupby(["leg", "rule", "sample"])
           .agg(false_exits=("exit", "size"), false_avg_13w_after=("index_13w_after", "mean")).reset_index())
    fx = fx.merge(fx2, on=["leg", "rule", "sample"], how="left")
    fx.to_csv(DEEP / "swings_exit_quality.csv", index=False)
    return Sw, A, fx


def main():
    N, W = build()
    cal, px, r, gc, sg = load()
    Y, Wd, S, byreg = part_years(N, W)
    Sw, A, fx = part_swings(N, W, px, sg)
    pd.set_option("display.width", 250); pd.set_option("display.max_columns", 40)
    t = Wd[(Wd.sleeve == "cash") & Wd.leg.isin(["SC100", "blend", "N100"])].pivot_table(
        index="year", columns="leg", values=["bh_ret", "pair_ret", "sc100_ret"]) * 100
    print(t.round(1).to_string())
    print(S.round(3).to_string(index=False))
    print(byreg.round(3).to_string(index=False))
    print(A[A.leg.isin(["SC100", "blend"])].round(3).to_string(index=False))
    print(fx[fx.leg.isin(["SC100", "blend"])].round(3).to_string(index=False))


if __name__ == "__main__":
    main()
