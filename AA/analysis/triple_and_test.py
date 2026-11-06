# -*- coding: utf-8 -*-
"""
Three indices must agree: N100 AND MC100 AND SC100.

Equity (the whole book, or the whole index) only when Nifty 100, Nifty
Midcap 100 and Nifty Smallcap 100 are all BUY on the weekly production
supertrend; otherwise the defensive sleeve. Compared with the pair
(N100 AND SC100), Smallcap 100 alone, each index's own signal, the current
rule and buy-and-hold.

  1. Portfolios: the four AA books in-sample (2021-11 -> 2026-08) and the four
     parents' real baskets out of sample (2014-07 -> 2021-10), on the v2
     harness (units, next-session OHLC4, 20.8 bps), Eikon prices.
  2. Individual indices as the equity leg, return space, 20.8 bps per switch:
     N50, N100, MC100, SC100, MC150, SC250, Micro250, an N100/MC100/SC100
     blend, and gold itself (GOLDBEES, own signal = gold's weekly supertrend).
     Sleeves: all cash, 50/50 gold/cash and all gold. Periods: 2007-21 and
     2007-26 (cash only: no gold prices before 2014-07), 2014-21, 2021-26 and
     2014-26 (all three sleeves).
     Gold held with a gold sleeve never trades, so every rule equals buy &
     hold there; gold held with the 50/50 sleeve trades half the book per
     switch and is charged half the cost.
  3. The marginal weeks: triple and pair disagree only when MC100 is SELL
     while N100 and SC100 are both BUY. What happened next?

Writes `evidence/why_n100sc100/triple_*.csv`.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

import segment_v2 as V
import segment_v2_data as D
from common import PAIRS
from index_builder import Panel
from run_segment_v2 import load_inputs
from gold_sleeve_test import gold_signal
from why_n100sc100 import (COST, OUT, calendar, cagr, daily_weight, eikon_by_isin, gold_cash, mdd,
                           run_rs, vol, weekly_signs)
from why_parents_oos import END as OOS_END
from why_parents_oos import START as OOS_START
from why_parents_oos import old_ranks

SHEETS = {"N50": "NSEI", "N100": "Nifty100", "MC100": "MC100", "SC100": "SC100",
          "MC150": "NiftyMidcap150", "SC250": "NiftySmallcap250", "Micro250": "NiftyMicrocap250"}
OWN = {"N50": "N50", "N100": "N100", "MC100": "MC100", "SC100": "SC100",
       "MC150": "MC150", "SC250": "SC250", "Micro250": "Micro250", "gold": "gold"}
PERIODS = [("2007-21, cash", "2007-07-02", "2021-10-29", "cash"),
           ("2014-21, gold+cash", "2014-07-07", "2021-10-29", "gold+cash"),
           ("2021-26, gold+cash (in-sample)", "2021-11-03", "2026-08-21", "gold+cash"),
           ("2021-26, cash (in-sample)", "2021-11-03", "2026-08-21", "cash"),
           ("2007-26 full, cash", "2007-07-02", "2026-08-21", "cash"),
           ("2014-26 full, gold+cash", "2014-07-07", "2026-08-21", "gold+cash"),
           ("2014-21, cash", "2014-07-07", "2021-10-29", "cash"),
           ("2014-21, gold", "2014-07-07", "2021-10-29", "gold"),
           ("2021-26, gold (in-sample)", "2021-11-03", "2026-08-21", "gold"),
           ("2014-26 full, cash", "2014-07-07", "2026-08-21", "cash"),
           ("2014-26 full, gold", "2014-07-07", "2026-08-21", "gold")]
SLEEVE_GOLD = {"cash": 0.0, "gold+cash": 0.5, "gold": 1.0}


def index_levels(cal) -> pd.DataFrame:
    xl = D.FROZEN_DIR / "Data" / "indices_ohlcv.xlsx"
    out = {}
    for k, sh in SHEETS.items():
        d = pd.read_excel(xl, sheet_name=sh)
        d["date"] = pd.to_datetime(d["date"])
        s = d.set_index("date")["close"].astype(float).sort_index()
        out[k] = s[~s.index.duplicated()]
    return pd.DataFrame(out).reindex(cal).ffill(limit=5)


def rule_decisions(s: pd.DataFrame, own: str) -> dict:
    return {"buy & hold": pd.Series(1.0, index=s.index),
            "own signal": s[own],
            "SC100 only": s["SC100"],
            "N100 AND SC100": s["N100"] * s["SC100"],
            "N100 AND MC100 AND SC100": s["N100"] * s["MC100"] * s["SC100"]}


def main() -> None:
    cal = calendar()
    sg = weekly_signs()
    lv = index_levels(cal)
    gc = gold_cash(cal)
    lv["gold"] = gc["gold"]
    # Gold's weekly supertrend, carried onto the review dates (week-end session <= review).
    gs_ = gold_signal().dropna()
    sg["gold"] = gs_.reindex(sg.index.union(gs_.index)).ffill().reindex(sg.index)
    sg.loc[sg.index < gs_.index[0], "gold"] = np.nan

    # ── 2. individual indices ──────────────────────────────────────────────
    rows, curves = [], {}
    for plab, a, b, sl in PERIODS:
        a, b = pd.Timestamp(a), pd.Timestamp(b)
        c = cal[(cal >= a) & (cal <= b)]
        gsh = SLEEVE_GOLD[sl]
        rg_, rc_ = gc["gold"].reindex(c).pct_change(), gc["cash"].reindex(c).pct_change()
        # Pick the legs explicitly: 0 x NaN gold (before 2014-07) must not wipe the cash return.
        r_sl = (rc_ if gsh == 0 else rg_ if gsh == 1 else gsh * rg_ + (1 - gsh) * rc_).fillna(0.0)
        eqs = {k: lv[k].reindex(c).pct_change() for k in list(SHEETS) + ["gold"]}
        eqs["blend N100/MC100/SC100"] = (eqs["N100"] + eqs["MC100"] + eqs["SC100"]) / 3
        s = sg.loc[(sg.index >= a - pd.Timedelta(days=7)) & (sg.index <= b)]
        for ek, r_eq in eqs.items():
            first = lv[ek].reindex(c).first_valid_index() if ek in lv else c[0]
            need = list(dict.fromkeys(["N100", "MC100", "SC100"] + ([OWN[ek]] if ek in OWN else [])))
            ss = s[need].dropna()
            if first is None or len(ss) < 20:
                continue
            first = max(first, ss.index[0] + pd.Timedelta(days=3))
            cc = c[c >= first]
            if (cc[-1] - cc[0]).days < 365 * 2:
                continue
            for rn, dec in rule_decisions(ss, OWN.get(ek, "SC100")).items():
                if rn == "own signal" and ek not in OWN:
                    continue
                # Gold held: a switch only trades the part of the book that changes asset.
                cost = COST * (1 - gsh) if ek == "gold" else COST
                nav = run_rs(dec, r_eq.reindex(cc).fillna(0.0), r_sl.reindex(cc).fillna(0.0), cc, cost_bps=cost)
                w = daily_weight(dec, cc).reindex(cc).ffill().fillna(1.0)
                rows.append({"period": plab, "equity": ek, "rule": rn, "start": cc[0].date(), "end": cc[-1].date(),
                             "cagr": cagr(nav), "max_dd": mdd(nav), "vol": vol(nav),
                             "calmar": cagr(nav) / abs(mdd(nav)) if mdd(nav) else np.nan,
                             "time_in_equity": float(w.mean()),
                             "switches": int((dec.diff().abs() > 0).sum())})
                if plab in ("2007-26 full, cash", "2014-26 full, gold+cash"):
                    curves[f"{plab}|{ek}|{rn}"] = nav
    ix = pd.DataFrame(rows)
    ix.to_csv(OUT / "triple_index_results.csv", index=False)
    pd.DataFrame(curves).to_csv(OUT / "triple_index_curves.csv")
    print("indices done", flush=True)

    # ── 3. the marginal weeks: MC100 SELL while N100 and SC100 are BUY ─────
    s = sg[["N100", "MC100", "SC100"]].dropna()
    s = s[s.index >= pd.Timestamp("2006-01-06")]
    mk = (s["N100"] == 1) & (s["SC100"] == 1)
    marg = []
    for r, v in s.iterrows():
        if not mk.loc[r]:
            continue
        j = cal.searchsorted(r, side="right")
        if j + 21 >= len(cal):
            continue
        a, e4 = cal[j], cal[j + 21]
        marg.append({"review": r.date(), "mc100_sell": bool(v["MC100"] == 0),
                     **{f"{k}_4w": float(lv[k][e4] / lv[k][a] - 1) if pd.notna(lv[k].get(a)) and pd.notna(lv[k].get(e4)) else None
                        for k in ("N100", "MC100", "SC100")},
                     "gold_4w": float(gc["gold"][e4] / gc["gold"][a] - 1) if pd.notna(gc["gold"].get(a)) and pd.notna(gc["gold"].get(e4)) else None})
    mg = pd.DataFrame(marg)
    mg.to_csv(OUT / "triple_marginal_weeks.csv", index=False)
    ms = mg.groupby("mc100_sell").agg(weeks=("review", "size"), N100_4w=("N100_4w", "mean"),
                                      MC100_4w=("MC100_4w", "mean"), SC100_4w=("SC100_4w", "mean"),
                                      SC100_hit=("SC100_4w", lambda x: (x.dropna() > 0).mean()),
                                      gold_4w=("gold_4w", "mean")).reset_index()
    ms.to_csv(OUT / "triple_marginal_summary.csv", index=False)
    mg2 = mg[mg["mc100_sell"]].copy()
    mg2["review"] = pd.to_datetime(mg2["review"])
    mg2["blk"] = (mg2["review"].diff() > pd.Timedelta(days=8)).cumsum()
    mstr = mg2.groupby("blk").agg(start=("review", "min"), end=("review", "max"), weeks=("review", "size"),
                                  SC100_4w_first=("SC100_4w", "first")).reset_index(drop=True)
    mstr.to_csv(OUT / "triple_marginal_stretches.csv", index=False)
    print("marginal weeks done", flush=True)

    # ── 1a. portfolios, in-sample (the four AA books) ──────────────────────
    inp = load_inputs()
    cal1, eff, rv, start, sim = inp["cal"], inp["eff"].copy(), inp["reviews"], inp["start"], inp["sim"]
    mc = pd.read_excel(D.MASTER_DIR / "Master_MC100.xlsx")
    mc["Date"] = pd.to_datetime(mc["Date"])
    mcs = mc.dropna(subset=["SIGN"]).set_index("Date")["SIGN"].sort_index()
    mcs = mcs[~mcs.index.duplicated(keep="last")]
    eff["MC100"] = mcs.reindex(eff.index.union(mcs.index)).ffill(limit=1).reindex(eff.index)
    prow, pcur = [], {}
    for aa, p in PAIRS.items():
        ctx = V.parent_ctx(p, inp["hold"][inp["hold"]["parent"] == p], rv, cal1)
        tags = V.tag_table(ctx, inp["taggers"]["hybrid"])
        rules = {"N100 AND MC100 AND SC100": V.build_whole_book_and(ctx, eff, keys=(V.N100, "MC100", V.SC100)),
                 "N100 AND SC100": V.build_whole_book_and(ctx, eff),
                 "SC100 only": V.build_whole_book_and(ctx, eff, keys=(V.SC100,)),
                 "current rule": V.build_production(ctx, eff, tags),
                 "parent": V.build_parent(ctx, eff)}
        for rn, st in rules.items():
            for gs, sl in ((0.5, "gold+cash"), (0.0, "cash"), (1.0, "gold")):
                if rn == "parent" and gs != 0.5:
                    continue
                nav, log = sim.run(st, V.PRIMARY_BPS, gold_share=gs)
                nav = nav.loc[start:] / nav.loc[start:].iloc[0]
                prow.append({"period": "in-sample 2021-26", "aa": aa, "rule": rn, "sleeve": sl,
                             "cagr": cagr(nav), "max_dd": mdd(nav), "vol": vol(nav),
                             "avg_equity": float(V.exposure(st, cal1).loc[start:].mean()), "trades": int(len(log))})
                pcur[f"in-sample|{aa}|{rn}|{sl}"] = nav
    print("books in-sample done", flush=True)

    # ── 1b. portfolios, out of sample (the four parents, 2014-21) ──────────
    cal_all = calendar()
    prior = cal_all[cal_all < OOS_START]
    cal2 = cal_all[(cal_all >= prior[-1]) & (cal_all <= OOS_END)]

    def one(n):
        d = pd.read_excel(D.MASTER_DIR / f"Master_{n}.xlsx")
        d["Date"] = pd.to_datetime(d["Date"])
        x = d.dropna(subset=["SIGN"]).set_index("Date")["SIGN"].sort_index()
        return x[~x.index.duplicated(keep="last")]
    n100, mc100, sc100 = one("Nifty100"), one("MC100"), one("SC100")
    grid = sc100.index[(sc100.index >= OOS_START) & (sc100.index <= OOS_END)]
    al = lambda x: x.reindex(grid.union(x.index)).ffill(limit=1).reindex(grid)
    sig = pd.DataFrame({V.N100: al(n100), V.MC150: al(mc100), V.SC250: al(sc100),
                        V.MICRO: al(sc100), V.SC100: al(sc100), "MC100": al(mc100)}, index=grid).dropna()
    rv2 = sig.index
    hist = {p: D.parent_history(p) for p in PAIRS.values()}
    for h in hist.values():
        h["key"] = h["isin"].where(h["isin"] != "", h["ticker"])
    isins = sorted({i for h in hist.values() for i in h[h["eff_date"] <= OOS_END]["isin"] if i})
    px = eikon_by_isin(isins, OOS_START - pd.Timedelta(days=40), OOS_END + pd.Timedelta(days=10),
                       "eikon_ohlcv_2014_2021.parquet")
    gc2 = gold_cash(cal2)
    sleeve = pd.DataFrame({V.GOLD: gc2["gold"], V.CASH: gc2["cash"]}, index=cal2).ffill()
    close = px.pivot(index="date", columns="ticker", values="close").reindex(cal2)
    sim2 = V.Simulator(Panel(px.drop(columns=["ric"]), cal2), sleeve, close=close)
    tagger = V.HybridTagger(old_ranks(), None, D.load_overrides())
    for aa, p in PAIRS.items():
        h = hist[p]
        ctx = V.parent_ctx(p, h[h["eff_date"] <= OOS_END], rv2, cal2)
        tags = V.tag_table(ctx, tagger)
        rules = {"N100 AND MC100 AND SC100": V.build_whole_book_and(ctx, sig, keys=(V.N100, "MC100", V.SC100)),
                 "N100 AND SC100": V.build_whole_book_and(ctx, sig, keys=(V.N100, V.SC100)),
                 "SC100 only": V.build_whole_book_and(ctx, sig, keys=(V.SC100,)),
                 "current rule": V.build_production(ctx, sig, tags),
                 "parent": V.build_parent(ctx, sig)}
        for rn, st in rules.items():
            for gs, sl in ((0.5, "gold+cash"), (0.0, "cash"), (1.0, "gold")):
                if rn == "parent" and gs != 0.5:
                    continue
                nav, log = sim2.run(st, V.PRIMARY_BPS, gold_share=gs)
                nav = nav.loc[cal2[0]:] / nav.loc[cal2[0]:].iloc[0]
                prow.append({"period": "out-of-sample 2014-21", "aa": aa, "rule": rn, "sleeve": sl,
                             "cagr": cagr(nav), "max_dd": mdd(nav), "vol": vol(nav),
                             "avg_equity": float(V.exposure(st, cal2).mean()), "trades": int(len(log))})
                pcur[f"oos|{aa}|{rn}|{sl}"] = nav
    pr = pd.DataFrame(prow)
    pr.to_csv(OUT / "triple_portfolio_results.csv", index=False)
    pd.DataFrame(pcur).to_csv(OUT / "triple_portfolio_curves.csv")
    print("parents out of sample done", flush=True)

    # ── console ────────────────────────────────────────────────────────────
    pd.set_option("display.width", 250)
    for per in pr["period"].unique():
        for sl in ("gold+cash", "cash", "gold"):
            x = pr[(pr["period"] == per) & ((pr["sleeve"] == sl) | (pr["rule"] == "parent"))]
            t = x.pivot(index="rule", columns="aa", values="cagr") * 100
            t["avg"] = t.mean(axis=1)
            d = x.pivot(index="rule", columns="aa", values="max_dd").mean(axis=1) * 100
            t["avg max DD"] = d
            print(f"\n{per} | {sl} sleeve | CAGR %\n", t.round(2).to_string())
    for plab in ["2007-26 full, cash", "2014-26 full, cash", "2014-26 full, gold+cash", "2014-26 full, gold",
                 "2014-21, gold", "2021-26, gold (in-sample)"]:
        x = ix[ix["period"] == plab]
        t = x.pivot(index="equity", columns="rule", values="cagr") * 100
        d = x.pivot(index="equity", columns="rule", values="max_dd") * 100
        print(f"\nINDICES {plab} | CAGR %\n", t.round(2).to_string())
        print(f"INDICES {plab} | max DD %\n", d.round(1).to_string())
    print("\nMARGINAL weeks (N100 and SC100 both BUY):\n", ms.round(4).to_string(index=False))
    print(mstr.to_string(index=False))


if __name__ == "__main__":
    main()
