"""Descriptive add-on to T09 (NOT pre-registered, no null, no pass mark; asked for by Manu 2026-11-12).
Rule: hold the whole proxy portfolio (the book's own mix of Nifty 100 / Midcap 100 / Smallcap 100) while the weekly Smallcap 100 SIGN is BUY;
when it is SELL, hold the sleeve: (a) fixed 50/50 GOLDBEES + cash, (b) 80/20 or 20/80 by the weekly MAUc1 SIGN. Same window, calendar, fills (OHLC4),
cost (10.4 bps a side; 0 and 50 also), quarterly reset while IN and trade arithmetic as T09's engine (it is imported, nothing is re-implemented).
Run from AA/:  python tests/T09/extra/sc100_rule.py"""
import sys
from pathlib import Path
import numpy as np, pandas as pd
AA = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(AA / "analysis"))
import t09_engine as E
OUT = Path(__file__).parent
HL = AA / "tests" / "T09" / "evidence" / "headline"
rows_nav, rows_stats, rows_dec, rows_tr = [], [], [], []
for b in E.BOOKS:
    bk = E.Book(b, start=E.T0)
    dec = bk.decisions()
    idx = dec["decision_idx"].values
    e = (dec["sign_SC100"] == "BUY").astype(float).values
    gw = dec["gw"].values
    for variant, gwv in (("sc100_fixed50", None), ("sc100_timed", gw)):
        for cost in E.COSTS:
            nav, trades, _ = E.simulate(bk, idx, e, cost, record=True, gw=gwv)
            st = E.stats(nav)
            st.update(book=b, run=variant, cost_bps=cost, trades=len(trades), cost_paid=sum(t["cost"] for t in trades),
                      switches=sum(t["kind"] in ("switch_in", "switch_out") for t in trades), sleeve_rebalances=sum(t["kind"] == "sleeve_rebalance" for t in trades),
                      quarterly_resets=sum(t["kind"] == "quarterly_reset" for t in trades), weeks_in=int(e.sum()), weeks=len(e))
            rows_stats.append(st)
            if cost == E.PRIMARY:
                for d, v in zip(bk.cal, nav):
                    rows_nav.append({"book": b, "date": d.date(), "run": variant, "nav": v})
                for t in trades:
                    rows_tr.append({"book": b, "run": variant, "date": t["date"], "kind": t["kind"], "e_after": t["e_after"], "gw_after": t["gw_after"],
                                    "value_before": t["V"], "traded": t["traded"], "cost": t["cost"], "nav_close_after": t["nav_close_after"]})
    d2 = dec[["book", "j", "decision_date", "trade_date", "sign_SC100", "sign_MAUc1", "gw"]].copy()
    d2["proxy_share"] = e
    rows_dec.append(d2)
nav = pd.DataFrame(rows_nav)
old = pd.read_csv(HL / "daily_nav.csv")
old = old[(old.cost_bps == 20.8) & old.run.isin(["strategy", "strategy_fixed50", "hold_proxy", "index_SC100"])]
old = old.assign(run=old.run.map({"strategy": "threeindex_timed", "strategy_fixed50": "threeindex_fixed50", "hold_proxy": "hold_proxy", "index_SC100": "smallcap100_alone"}))
old["date"] = pd.to_datetime(old["date"]).dt.date
nav = pd.concat([nav, old[["book", "date", "run", "nav"]]], ignore_index=True)
nav.pivot_table(index=["book", "date"], columns="run", values="nav").reset_index().to_csv(OUT / "sc100_rule_daily_nav.csv", index=False)
stt = pd.DataFrame(rows_stats)[["book", "run", "cost_bps", "end_nav", "cagr", "max_dd", "vol", "calmar", "trades", "switches", "sleeve_rebalances", "quarterly_resets", "cost_paid", "weeks_in", "weeks"]]
stt.to_csv(OUT / "sc100_rule_stats.csv", index=False)
pd.concat(rows_dec).to_csv(OUT / "sc100_rule_decisions.csv", index=False)
pd.DataFrame(rows_tr).to_csv(OUT / "sc100_rule_trades.csv", index=False)
print(stt[stt.cost_bps == 20.8].assign(cagr=lambda d: (d.cagr * 100).round(2), max_dd=lambda d: (d.max_dd * 100).round(2)).drop(columns=["vol", "end_nav", "cost_paid"]).to_string(index=False))

# chart
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
wide = pd.read_csv(OUT / "sc100_rule_daily_nav.csv", parse_dates=["date"])
sty = {"sc100_timed": ("#1f4fd8", 2.2, "Smallcap 100 switch, MAUc1-timed sleeve"), "sc100_fixed50": ("#e08a1e", 1.8, "Smallcap 100 switch, 50/50 sleeve"),
       "threeindex_timed": ("#6fa0ee", 1.2, "Three-index switch, timed sleeve (T09 rule)"), "threeindex_fixed50": ("#9bb7e6", 1.0, "Three-index switch, 50/50 sleeve (T09 Part A)"),
       "hold_proxy": ("#808080", 1.4, "Hold the proxy portfolio"), "smallcap100_alone": ("#7a3b78", 1.0, "Smallcap 100 alone")}
fig, axs = plt.subplots(2, 2, figsize=(15, 9), sharey=False)
for ax, b in zip(axs.ravel(), E.BOOKS):
    w = wide[wide.book == b]
    for k, (c, lw, lab) in sty.items():
        ax.plot(w.date, w[k], color=c, lw=lw, label=lab)
    ax.set_yscale("log"); ax.set_title(f"{b} (growth of 1, 2011-11-25 to 2019-01-02, 20.8 bps, log scale)", fontsize=10)
    ax.set_yticks([0.8, 1, 1.5, 2, 3, 4]); ax.set_yticklabels(["0.8×", "1×", "1.5×", "2×", "3×", "4×"]); ax.grid(alpha=.25)
axs[0, 0].legend(fontsize=8, loc="upper left")
fig.suptitle("Smallcap 100 as the only signal: whole proxy portfolio while Smallcap 100 is BUY, else GOLDBEES + cash (descriptive, not pre-registered)", fontsize=11)
fig.tight_layout(); fig.savefig(OUT / "sc100_rule_chart.png", dpi=110)
print("written:", *sorted(p.name for p in OUT.glob("sc100_rule_*")))
