# -*- coding: utf-8 -*-
"""
Part E of the N100 AND SC100 study: out of sample on the actual parents,
2014-07 -> 2021-10.

This period is before the AA books existed, and neither Study 1 nor this
study chose anything on it. It runs the four parents' real rebalance
histories through the v2 harness (units, next-session OHLC4 fills,
20.8 bps), priced from `ohlcv_eikon` by quote_id. Rules:

  parent            no overlay
  SC100 only        whole book to the sleeve when Smallcap 100 is SELL
  N100 AND SC100    whole book in equity only when both are BUY
  current rule*     production's FS >= 0.60, count-weighted over rank-band
                    tags. Midcap 100 / Smallcap 100 stand in for Midcap 150 /
                    Smallcap 250, which have no signals before 2019. These are
                    the inputs the production engine itself used before
                    2026-04 (`gate_v2_summary.json`).
  segment rule*     the v2 rule, with the same stand-ins

Each rule is run with the 50/50 gold/cash sleeve and with an all-cash sleeve.
Writes `evidence/why_n100sc100/parents_oos_*.csv`.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

import segment_v2 as V
import segment_v2_data as D
from common import CACHE_DIR, PAIRS
from index_builder import Panel
from mcap_ranks import band_of
from why_n100sc100 import OUT, calendar, eikon_by_isin, gold_cash

START, END = pd.Timestamp("2014-07-07"), pd.Timestamp("2021-10-29")


def old_ranks() -> pd.DataFrame:
    """Month-end market-cap ranks 2014-01 -> 2019-07, same method as the v2 cache."""
    path = CACHE_DIR / "mcap_ranks_monthly_2014_2019.csv"
    if path.exists():
        return pd.read_csv(path, parse_dates=["snapshot_date"], dtype={"isin": "string"})
    df = D._read_sql(
        "SELECT date, ticker, isin, mcap FROM public.mcap_based_universe "
        "WHERE date >= '2013-12-01' AND date <= '2019-07-31' AND instrument_class = 'ordinary' "
        "AND mcap IS NOT NULL AND ticker IS NOT NULL")
    df["date"] = pd.to_datetime(df["date"])
    df["ticker"] = df["ticker"].str.strip().str.upper()
    df["mcap"] = df["mcap"].astype(float)
    df = (df.sort_values("mcap", ascending=False).drop_duplicates(["date", "ticker"])
            .sort_values(["date", "ticker"]))
    df["month"] = df["date"].dt.to_period("M")
    df = df[df["date"] == df.groupby("month")["date"].transform("max")].drop(columns="month")
    df = df.sort_values(["date", "mcap"], ascending=[True, False])
    df["rank"] = df.groupby("date").cumcount() + 1
    df["category"] = df["rank"].map(band_of)
    out = df.rename(columns={"date": "snapshot_date"})[["snapshot_date", "isin", "ticker", "mcap", "rank", "category"]]
    out.to_csv(path, index=False)
    return out


def main() -> None:
    cal_all = calendar()
    prior = cal_all[cal_all < START]
    cal = cal_all[(cal_all >= prior[-1]) & (cal_all <= END)]

    # Signals as BUY/SELL strings on the review grid, with the stand-ins.
    def one(n):
        d = pd.read_excel(D.MASTER_DIR / f"Master_{n}.xlsx")
        d["Date"] = pd.to_datetime(d["Date"])
        s = d.dropna(subset=["SIGN"]).set_index("Date")["SIGN"].sort_index()
        return s[~s.index.duplicated(keep="last")]
    n100, mc100, sc100 = one("Nifty100"), one("MC100"), one("SC100")
    grid = sc100.index[(sc100.index >= START) & (sc100.index <= END)]
    al = lambda s: s.reindex(grid.union(s.index)).ffill(limit=1).reindex(grid)
    sig = pd.DataFrame({V.N100: al(n100), V.MC150: al(mc100), V.SC250: al(sc100),
                        V.MICRO: al(sc100), V.SC100: al(sc100)}, index=grid)
    sig = sig.dropna()
    reviews = sig.index

    hist = {p: D.parent_history(p) for p in PAIRS.values()}
    for p, h in hist.items():
        h["key"] = h["isin"].where(h["isin"] != "", h["ticker"])
    isins = sorted({i for h in hist.values() for i in h[h["eff_date"] <= END]["isin"] if i})
    px = eikon_by_isin(isins, START - pd.Timedelta(days=40), END + pd.Timedelta(days=10),
                       "eikon_ohlcv_2014_2021.parquet")
    panel = Panel(px.drop(columns=["ric"]), cal)
    gc = gold_cash(cal)
    sleeve = pd.DataFrame({V.GOLD: gc["gold"], V.CASH: gc["cash"]}, index=cal).ffill()
    close = px.pivot(index="date", columns="ticker", values="close").reindex(cal)
    sim = V.Simulator(panel, sleeve, close=close)
    tagger = V.HybridTagger(old_ranks(), None, D.load_overrides())

    rows, curves, cover = [], {}, []
    for aa, p in PAIRS.items():
        h = hist[p]
        ctx = V.parent_ctx(p, h[h["eff_date"] <= END], reviews, cal)
        tags = V.tag_table(ctx, tagger)
        rules = {
            "parent": V.build_parent(ctx, sig),
            "SC100 only": V.build_whole_book_and(ctx, sig, keys=(V.SC100,)),
            "N100 AND SC100": V.build_whole_book_and(ctx, sig, keys=(V.N100, V.SC100)),
            "current rule*": V.build_production(ctx, sig, tags),
            "segment rule*": V.build_sleeve(ctx, sig, tags, "event", "micro_own"),
        }
        # price coverage at each entry
        miss = sum(1 for st in rules["parent"] for k in st.weights if not np.isfinite(sim._p(k, st.entry_i, "fill")))
        tot = sum(len(st.weights) for st in rules["parent"])
        cover.append({"aa": aa, "parent": p, "holding_entries": tot, "unfillable": miss,
                      "unfillable_share": miss / tot if tot else np.nan,
                      "rebalances": len(set(ctx.basket_eff))})
        for gs, lab in ((0.5, "gold+cash"), (0.0, "cash")):
            for rn, st in rules.items():
                if rn == "parent" and gs == 0.0:
                    continue
                nav, log = sim.run(st, 20.8, gold_share=gs)
                nav = nav.loc[cal[0]:]
                nav = nav / nav.iloc[0]
                yrs = (nav.index[-1] - nav.index[0]).days / 365.25
                eqw = V.exposure(st, cal).mean()
                rows.append({"aa": aa, "parent": p, "sleeve": lab, "rule": rn,
                             "cagr": float(nav.iloc[-1] ** (1 / yrs) - 1),
                             "max_dd": float((nav / nav.cummax() - 1).min()),
                             "vol": float(nav.pct_change().std() * np.sqrt(252)),
                             "avg_equity": float(eqw), "trades": int(len(log))})
                curves[f"{aa}|{rn}|{lab}"] = nav
        print(f"  {aa} done", flush=True)
    r = pd.DataFrame(rows)
    r.to_csv(OUT / "parents_oos_results.csv", index=False)
    pd.DataFrame(curves).to_csv(OUT / "parents_oos_curves.csv")
    pd.DataFrame(cover).to_csv(OUT / "parents_oos_coverage.csv", index=False)
    pd.set_option("display.width", 220)
    print(pd.DataFrame(cover).to_string(index=False))
    for lab in ("gold+cash", "cash"):
        t = r[(r["sleeve"] == lab) | (r["rule"] == "parent")].pivot(index="rule", columns="aa", values="cagr")
        t["avg"] = t.mean(axis=1)
        d = r[(r["sleeve"] == lab) | (r["rule"] == "parent")].pivot(index="rule", columns="aa", values="max_dd")
        d["avg"] = d.mean(axis=1)
        print(f"\nCAGR % ({lab} sleeve), {START.date()} -> {END.date()}\n", (t * 100).round(2).to_string())
        print(f"Max DD % ({lab})\n", (d * 100).round(1).to_string())


if __name__ == "__main__":
    main()
