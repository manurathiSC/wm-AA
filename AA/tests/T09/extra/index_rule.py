"""Descriptive add-on to T09 (NOT pre-registered, no null, no pass mark; asked for by Manu 2026-11-12).
Per-index rule: each week, for each of Nifty 100 / Midcap 100 / Smallcap 100 whose weekly SIGN is BUY, hold that index at the book's own weight
(SCMO_0003: 9.6 / 19.7 / 70.7); the weight of every index that is SELL goes to the sleeve: (a) fixed 50/50 GOLDBEES + cash, (b) 80/20 or 20/80 by MAUc1.
Same window, calendar, OHLC4 fills, cost, and T09 engine data/prices as the engine (imported). Conventions chosen here: a trade to the full targets happens on the session
after a decision when the set of BUY indices changed or (sleeve > 0 and its split changed); quarterly reset to the targets while any index is held.
Check: with the mask set to 'all three BUY' the simulator below equals the engine's `simulate` to 1e-12.
Run from AA/:  python tests/T09/extra/index_rule.py"""
import sys
from pathlib import Path
import numpy as np, pandas as pd
AA = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(AA / "analysis"))
import t09_engine as E
OUT = Path(__file__).parent


def sim(bk, dec_idx, mask, gw, cost_bps, record=False):
    """mask[j] = 0/1 vector over the three indices (BUY), gw[j] = gold weight of the sleeve. Returns daily NAV (and trade log)."""
    T, ow = bk.T, cost_bps / 2e4
    share = lambda m: float((bk.W * m).sum())
    m_cur, gw_cur = mask[0].astype(float), float(gw[0])
    u = bk.u0 * m_cur
    gu = (1 - share(m_cur)) * gw_cur / bk.g[0]
    cu = (1 - share(m_cur)) * (1 - gw_cur) / bk.L[0]
    tgt = {}
    for j in range(1, len(dec_idx)):
        tr = int(dec_idx[j]) + 1
        if tr < T and ((mask[j] != mask[j - 1]).any() or (share(mask[j]) < 1 and gw[j] != gw[j - 1])):
            tgt[tr] = (mask[j].astype(float), float(gw[j]), j)
    ev = sorted(set(tgt) | bk.reset_events)
    nav = np.empty(T)
    a = 0
    nz = np.flatnonzero(u)
    trades = []

    def val(t, nz_):
        return (bk.C[t][nz_] @ u[nz_] if len(nz_) else 0.0) + bk.g[t] * gu + bk.L[t] * cu

    for t in ev:
        if t > a:
            nav[a:t] = (bk.C[a:t][:, nz] @ u[nz] if len(nz) else 0.0) + bk.g[a:t] * gu + bk.L[a:t] * cu
        a = t
        if t in tgt or (t in bk.reset_events and m_cur.any()):
            m_new, gw_new, jd = tgt[t] if t in tgt else (m_cur, gw_cur, None)
            kind = "reset" if t not in tgt else ("index_set_change" if (m_new != m_cur).any() else "sleeve_rebalance")
            ps, gp, lv = bk.P[t], bk.gf[t], bk.L[t]
            held = u * ps
            V = held.sum() + gu * gp + cu * lv
            Te = V * bk.W * m_new
            Tg = (V - Te.sum()) * gw_new
            Tc = (V - Te.sum()) * (1 - gw_new)
            traded = np.abs(Te - held).sum() + abs(Tg - gu * gp) + abs(Tc - cu * lv)
            cost = ow * traded
            k = (V - cost) / V
            u, gu, cu = k * Te / ps, k * Tg / gp, k * Tc / lv
            m_cur, gw_cur = m_new, gw_new
            nz = np.flatnonzero(u)
            if record:
                trades.append({"date": bk.cal[t].date(), "kind": kind, "indices_held": "".join("NMS"[i] if m_new[i] else "-" for i in range(3)), "gw_after": gw_new,
                               "value_before": V, "traded": traded, "cost": cost, "nav_close_after": val(t, nz)})
    nav[a:T] = (bk.C[a:T][:, nz] @ u[nz] if len(nz) else 0.0) + bk.g[a:T] * gu + bk.L[a:T] * cu
    return (nav, trades) if record else nav


rows_nav, rows_stats, rows_dec, rows_tr = [], [], [], []
for b in E.BOOKS:
    bk = E.Book(b, start=E.T0)
    dec = bk.decisions()
    idx = dec["decision_idx"].values
    mask = np.column_stack([(dec[f"sign_{n}"] == "BUY").astype(float).values for n in E.INDICES])
    gwt = dec["gw"].values
    gfix = np.full(len(dec), 0.5)
    # check against the engine's simulate with an all-or-nothing mask
    allb = np.repeat(dec["state"].values[:, None].astype(float), 3, axis=1)
    for gwv, gwe in ((gfix, None), (gwt, gwt)):
        d = np.abs(sim(bk, idx, allb, gwv, 20.8) / E.simulate(bk, idx, dec["state"].values.astype(float), 20.8, gw=gwe) - 1).max()
        assert d < 1e-12, (b, d)
    for variant, gwv in (("index_rule_fixed50", gfix), ("index_rule_timed", gwt)):
        for cost in E.COSTS:
            nav, trades = sim(bk, idx, mask, gwv, cost, record=True)
            st = E.stats(nav)
            st.update(book=b, run=variant, cost_bps=cost, trades=len(trades), cost_paid=sum(t["cost"] for t in trades),
                      index_set_changes=sum(t["kind"] == "index_set_change" for t in trades), sleeve_rebalances=sum(t["kind"] == "sleeve_rebalance" for t in trades),
                      resets=sum(t["kind"] == "reset" for t in trades), avg_equity_share=float((mask * bk.W).sum(axis=1).mean()), weeks=len(idx))
            rows_stats.append(st)
            if cost == E.PRIMARY:
                rows_nav += [{"book": b, "date": d_.date(), "run": variant, "nav": v} for d_, v in zip(bk.cal, nav)]
                rows_tr += [{"book": b, "run": variant, **t} for t in trades]
    d2 = dec[["book", "j", "decision_date", "trade_date", "sign_Nifty100", "sign_MC100", "sign_SC100", "sign_MAUc1", "gw"]].copy()
    d2["equity_share"] = (mask * bk.W).sum(axis=1)
    rows_dec.append(d2)
nav = pd.DataFrame(rows_nav)
prev = pd.read_csv(OUT / "sc100_rule_daily_nav.csv")
prev["date"] = pd.to_datetime(prev["date"]).dt.date
keep = prev.melt(id_vars=["book", "date"], var_name="run", value_name="nav")
nav = pd.concat([nav, keep], ignore_index=True)
nav.pivot_table(index=["book", "date"], columns="run", values="nav").reset_index().to_csv(OUT / "index_rule_daily_nav.csv", index=False)
stt = pd.DataFrame(rows_stats)[["book", "run", "cost_bps", "end_nav", "cagr", "max_dd", "vol", "calmar", "trades", "index_set_changes", "sleeve_rebalances", "resets", "cost_paid", "avg_equity_share", "weeks"]]
stt.to_csv(OUT / "index_rule_stats.csv", index=False)
pd.concat(rows_dec).to_csv(OUT / "index_rule_decisions.csv", index=False)
pd.DataFrame(rows_tr).to_csv(OUT / "index_rule_trades.csv", index=False)
print(stt[stt.cost_bps == 20.8].assign(cagr=lambda d: (d.cagr * 100).round(2), max_dd=lambda d: (d.max_dd * 100).round(2), avg_equity_share=lambda d: d.avg_equity_share.round(3))
      .drop(columns=["vol", "end_nav", "cost_paid", "weeks"]).to_string(index=False))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
wide = pd.read_csv(OUT / "index_rule_daily_nav.csv", parse_dates=["date"])
sty = {"index_rule_timed": ("#1f4fd8", 2.2, "Per-index rule, MAUc1-timed sleeve"), "index_rule_fixed50": ("#e08a1e", 1.8, "Per-index rule, 50/50 sleeve"),
       "sc100_timed": ("#2e9e6b", 1.2, "Smallcap 100 switch, timed sleeve"), "threeindex_timed": ("#6fa0ee", 1.2, "Three-index switch, timed sleeve (T09 rule)"),
       "hold_proxy": ("#808080", 1.4, "Hold the proxy portfolio"), "smallcap100_alone": ("#7a3b78", 1.0, "Smallcap 100 alone")}
fig, axs = plt.subplots(2, 2, figsize=(15, 9))
for ax, b in zip(axs.ravel(), E.BOOKS):
    w = wide[wide.book == b]
    for k, (c, lw, lab) in sty.items():
        ax.plot(w.date, w[k], color=c, lw=lw, label=lab)
    ax.set_yscale("log")
    ax.set_title(f"{b} (growth of 1, 2011-11-25 to 2019-01-02, 20.8 bps, log scale)", fontsize=10)
    ax.set_yticks([0.8, 1, 1.5, 2, 3, 4])
    ax.set_yticklabels(["0.8x", "1x", "1.5x", "2x", "3x", "4x"])
    ax.grid(alpha=.25)
axs[0, 0].legend(fontsize=8, loc="upper left")
fig.suptitle("Per-index rule: hold each index (at the book's weight) while its own signal is BUY, the rest in GOLDBEES + cash (descriptive, not pre-registered)", fontsize=11)
fig.tight_layout()
fig.savefig(OUT / "index_rule_chart.png", dpi=110)
print("written:", *sorted(p.name for p in OUT.glob("index_rule_*")))
