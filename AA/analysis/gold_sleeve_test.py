# -*- coding: utf-8 -*-
"""
Does timing the gold inside the defensive sleeve help?

Study 1 (`phase9_improve.sleeve_trend_variant`) found that switching the sleeve
to 100% gold when gold's own supertrend is BUY, and to 100% cash when it is
SELL, beat the fixed 50/50 split on 3 of 4 books in 2021-26. It also made
drawdown worse on all four, and it never beat simply holding all gold. That
window had no year in which gold fell, which is exactly where a gold trend
filter should earn its keep. This re-tests it:

  * on the v2 harness (units, next-session OHLC4, 20.8 bps; gold<->cash
    switches pay costs too), with Eikon prices;
  * in-sample (2021-11 -> 2026-08, the four AA books) and out of sample
    (2014-07 -> 2021-10, the four parents' real baskets). The out-of-sample
    window includes 2014-18, when gold went nowhere;
  * under four equity rules: N100 AND SC100, SC100 only, the current rule
    and the segment rule (* = MC100 / SC100 stand-ins before 2019);
  * with five sleeves: fixed 50/50; gold-trend 100% (all gold on BUY, all cash
    on SELL, Study 1's version); gold-trend 50/50 (50/50 on BUY, all cash on
    SELL); all cash; all gold.

The gold signal is the production supertrend port (`supertrend.py`: 5-bar
linearly weighted ATR, multiplier 2) on weekly GOLDBEES bars built from Eikon
daily OHLC (GBES.NS). It is read on the same Friday as the index signals.
Before its first value (warm-up, 2014-07 -> 2014-08) the sleeve holds 50/50.

Writes `evidence/why_n100sc100/gold_sleeve_*.csv`.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

import segment_v2 as V
import segment_v2_data as D
from common import CACHE_DIR, PAIRS
from index_builder import Panel
from run_segment_v2 import load_inputs
from supertrend import supertrend, to_weekly
from why_n100sc100 import OUT, calendar, eikon_by_isin, gold_cash
from why_parents_oos import END as OOS_END
from why_parents_oos import START as OOS_START
from why_parents_oos import old_ranks

SLEEVES = ["50/50", "gold trend 100%", "gold trend 50/50", "all cash", "all gold"]
RULES = ["N100 AND SC100", "SC100 only", "current rule", "segment rule"]


def gold_signal() -> pd.Series:
    """Weekly GOLDBEES supertrend (1 BUY / 0 SELL), indexed by each week's last session."""
    path = CACHE_DIR / "why_gold_ohlc_eikon.parquet"
    if path.exists():
        g = pd.read_parquet(path)
    else:
        g = D._read_sql("SELECT date, open, high, low, close FROM ohlcv_eikon "
                        "WHERE quote_id = 55837402194 ORDER BY date")
        g["date"] = pd.to_datetime(g["date"])
        for c in ("open", "high", "low", "close"):
            g[c] = pd.to_numeric(g[c], errors="coerce").astype(float)
        g.to_parquet(path, index=False)
    d = g.set_index("date").sort_index()
    d["volume"] = 0.0
    return supertrend(to_weekly(d))["signal"]


def share_map(reviews, gsig: pd.Series, kind: str) -> float | dict:
    if kind == "50/50":
        return 0.5
    if kind == "all cash":
        return 0.0
    if kind == "all gold":
        return 1.0
    on = 1.0 if kind == "gold trend 100%" else 0.5
    out = {}
    idx = gsig.dropna().index
    for r in reviews:
        prior = idx[idx <= r]
        v = gsig.loc[prior[-1]] if len(prior) else np.nan
        out[r] = 0.5 if np.isnan(v) else (on if v == 1.0 else 0.0)
    return out


def stats(nav: pd.Series) -> dict:
    n = nav.dropna()
    yrs = (n.index[-1] - n.index[0]).days / 365.25
    r = n.pct_change().dropna()
    c = float((n.iloc[-1] / n.iloc[0]) ** (1 / yrs) - 1)
    dd = float((n / n.cummax() - 1).min())
    v = float(r.std() * np.sqrt(252))
    return {"cagr": c, "max_dd": dd, "vol": v, "calmar": c / abs(dd) if dd else np.nan}


def run_period(label, sim, steps_by_book, reviews, gsig, start, cal, subperiods):
    rows, curves = [], {}
    for aa, rules in steps_by_book.items():
        for rn, st in rules.items():
            defensive = [s.review for s in st if s.sleeve > 0.5]
            # The control for "timing vs just more gold": a fixed split equal to
            # the gold-trend sleeve's average gold share while defensive.
            tr = share_map(reviews, gsig, "gold trend 100%")
            same = float(np.mean([tr[r] for r in defensive])) if defensive else 0.5
            for sk in (SLEEVES + ["static, same gold share"]) if rn != "parent" else ["n/a"]:
                gs = 0.5 if rn == "parent" else (same if sk == "static, same gold share"
                                                  else share_map(reviews, gsig, sk))
                nav, log = sim.run(st, V.PRIMARY_BPS, gold_share=gs)
                nav = nav.loc[start:]
                nav = nav / nav.iloc[0]
                row = {"period": label, "aa": aa, "rule": rn, "sleeve": sk, **stats(nav), "trades": int(len(log))}
                if isinstance(gs, dict) and defensive:
                    row["gold_buy_share_when_defensive"] = float(np.mean([gs[r] > 0 for r in defensive]))
                row["avg_gold_share_when_defensive"] = same if rn != "parent" else None
                for a_, b_, lab in subperiods:
                    seg = nav.loc[a_:b_]
                    if len(seg) > 20:
                        row[f"cagr_{lab}"] = stats(seg)["cagr"]
                        row[f"max_dd_{lab}"] = stats(seg)["max_dd"]
                rows.append(row)
                curves[f"{label}|{aa}|{rn}|{sk}"] = nav
    return rows, curves


def main() -> None:
    gsig = gold_signal()

    # ── in-sample: the four AA books on the v2 inputs ───────────────────────
    inp = load_inputs()
    cal, eff, rv, start, sim = inp["cal"], inp["eff"], inp["reviews"], inp["start"], inp["sim"]
    steps_is = {}
    for aa, p in PAIRS.items():
        ctx = V.parent_ctx(p, inp["hold"][inp["hold"]["parent"] == p], rv, cal)
        tags = V.tag_table(ctx, inp["taggers"]["hybrid"])
        steps_is[aa] = {"N100 AND SC100": V.build_whole_book_and(ctx, eff),
                        "SC100 only": V.build_whole_book_and(ctx, eff, keys=(V.SC100,)),
                        "current rule": V.build_production(ctx, eff, tags),
                        "segment rule": V.build_sleeve(ctx, eff, tags, "event", "micro_own"),
                        "parent": V.build_parent(ctx, eff)}
    r_is, c_is = run_period("in-sample 2021-26", sim, steps_is, rv, gsig, start, cal, [])
    print("in-sample done", flush=True)

    # ── out of sample: the parents, 2014-07 -> 2021-10 ─────────────────────
    cal_all = calendar()
    prior = cal_all[cal_all < OOS_START]
    cal2 = cal_all[(cal_all >= prior[-1]) & (cal_all <= OOS_END)]

    def one(n):
        d = pd.read_excel(D.MASTER_DIR / f"Master_{n}.xlsx")
        d["Date"] = pd.to_datetime(d["Date"])
        s = d.dropna(subset=["SIGN"]).set_index("Date")["SIGN"].sort_index()
        return s[~s.index.duplicated(keep="last")]
    n100, mc100, sc100 = one("Nifty100"), one("MC100"), one("SC100")
    grid = sc100.index[(sc100.index >= OOS_START) & (sc100.index <= OOS_END)]
    al = lambda s: s.reindex(grid.union(s.index)).ffill(limit=1).reindex(grid)
    sig = pd.DataFrame({V.N100: al(n100), V.MC150: al(mc100), V.SC250: al(sc100),
                        V.MICRO: al(sc100), V.SC100: al(sc100)}, index=grid).dropna()
    rv2 = sig.index
    hist = {p: D.parent_history(p) for p in PAIRS.values()}
    for h in hist.values():
        h["key"] = h["isin"].where(h["isin"] != "", h["ticker"])
    isins = sorted({i for h in hist.values() for i in h[h["eff_date"] <= OOS_END]["isin"] if i})
    px = eikon_by_isin(isins, OOS_START - pd.Timedelta(days=40), OOS_END + pd.Timedelta(days=10),
                       "eikon_ohlcv_2014_2021.parquet")
    gc = gold_cash(cal2)
    sleeve = pd.DataFrame({V.GOLD: gc["gold"], V.CASH: gc["cash"]}, index=cal2).ffill()
    close = px.pivot(index="date", columns="ticker", values="close").reindex(cal2)
    sim2 = V.Simulator(Panel(px.drop(columns=["ric"]), cal2), sleeve, close=close)
    tagger = V.HybridTagger(old_ranks(), None, D.load_overrides())
    steps_oos = {}
    for aa, p in PAIRS.items():
        h = hist[p]
        ctx = V.parent_ctx(p, h[h["eff_date"] <= OOS_END], rv2, cal2)
        tags = V.tag_table(ctx, tagger)
        steps_oos[aa] = {"N100 AND SC100": V.build_whole_book_and(ctx, sig, keys=(V.N100, V.SC100)),
                         "SC100 only": V.build_whole_book_and(ctx, sig, keys=(V.SC100,)),
                         "current rule": V.build_production(ctx, sig, tags),
                         "segment rule": V.build_sleeve(ctx, sig, tags, "event", "micro_own"),
                         "parent": V.build_parent(ctx, sig)}
    subs = [(pd.Timestamp("2014-07-07"), pd.Timestamp("2018-12-31"), "2014_18"),
            (pd.Timestamp("2019-01-01"), OOS_END, "2019_21")]
    r_oos, c_oos = run_period("out-of-sample 2014-21", sim2, steps_oos, rv2, gsig, cal2[0], cal2, subs)
    print("out of sample done", flush=True)

    res = pd.DataFrame(r_is + r_oos)
    res.to_csv(OUT / "gold_sleeve_results.csv", index=False)
    pd.DataFrame({**c_is}).to_csv(OUT / "gold_sleeve_curves_is.csv")
    pd.DataFrame({**c_oos}).to_csv(OUT / "gold_sleeve_curves_oos.csv")

    # gold itself, and its signal, per period
    g = gc["gold"]
    gd = []
    for lab, a_, b_ in [("2014-07 -> 2018-12", "2014-07-07", "2018-12-31"), ("2019-01 -> 2021-10", "2019-01-01", "2021-10-29"),
                        ("2021-11 -> 2026-08", "2021-11-03", "2026-08-21")]:
        gg = gold_cash(calendar())["gold"].loc[a_:b_].dropna()
        yrs = (gg.index[-1] - gg.index[0]).days / 365.25
        ws = gsig.loc[a_:b_].dropna()
        gd.append({"period": lab, "gold_cagr": float((gg.iloc[-1] / gg.iloc[0]) ** (1 / yrs) - 1),
                   "gold_max_dd": float((gg / gg.cummax() - 1).min()),
                   "gold_signal_buy_share": float(ws.mean()), "gold_signal_switches": int((ws.diff().abs() > 0).sum())})
    pd.DataFrame(gd).to_csv(OUT / "gold_sleeve_gold_itself.csv", index=False)
    wk = gsig.dropna()
    pd.DataFrame({"week_end": wk.index, "gold_signal": wk.values}).to_csv(OUT / "gold_signal_weekly.csv", index=False)

    pd.set_option("display.width", 250)
    print(pd.DataFrame(gd).round(4).to_string(index=False))
    for per in res["period"].unique():
        x = res[(res["period"] == per) & (res["rule"] != "parent")]
        for f in ["cagr", "max_dd"]:
            t = x.groupby(["rule", "sleeve"])[f].mean().unstack() * 100
            print(f"\n{per} — average {f} across 4 books (%)\n", t[SLEEVES].round(2).to_string())
        p = res[(res["period"] == per) & (res["rule"] == "parent")][["cagr", "max_dd"]].mean() * 100
        print("parent:", p.round(2).to_dict())
    x = res[res["period"].str.startswith("out")]
    for lab in ("2014_18", "2019_21"):
        t = x[x["rule"] != "parent"].groupby(["rule", "sleeve"])[f"cagr_{lab}"].mean().unstack() * 100
        print(f"\nOOS sub-period {lab} — avg CAGR (%)\n", t[SLEEVES].round(2).to_string())


if __name__ == "__main__":
    main()
