# -*- coding: utf-8 -*-
"""Print every table T04.md section 4 uses, from the stored evidence only. Writes analysis.log; exits non-zero if a validity gate failed.

    python tests/T04/analyse.py [--run headline]            (from AA/)
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.dont_write_bytecode = True
T04 = Path(__file__).resolve().parent
AA = T04.parents[1]
IND = ["I1", "I2", "I3", "I4", "I5"]
NAME = {"I1": "50-day EMA", "I2": "200-day EMA", "I3": "50-day SMA", "I4": "200-day SMA", "I5": "weekly SuperTrend"}
PRIMARY = 20.8
PASS_MARK = 98.0
Z = 0.84 + 2.054          # z(0.98) + z(0.80) = 2.894
OUT: list = []


def p(s: str = ""):
    OUT.append(s)
    print(s)


def md(df: pd.DataFrame, floatfmt: dict | None = None) -> str:
    floatfmt = floatfmt or {}
    cols = list(df.columns)
    lines = ["| " + " | ".join(str(c) for c in cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    for _, r in df.iterrows():
        cells = []
        for c in cols:
            v = r[c]
            if isinstance(v, (float, np.floating)):
                cells.append("" if np.isnan(v) else (floatfmt.get(c, "{:.2f}")).format(v))
            else:
                cells.append(str(v))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def percentile(x, v, higher_better=True):
    x = np.asarray(x, float)
    tol = 1e-12 * max(1.0, abs(v))
    worse = int((x < v - tol).sum()) if higher_better else int((x > v + tol).sum())
    tied = int((np.abs(x - v) <= tol).sum())
    ge = int((x >= v - tol).sum()) if higher_better else int((x <= v + tol).sum())
    return (worse + 0.5 * tied) / len(x) * 100, (1 + ge) / (len(x) + 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="headline")
    a = ap.parse_args()
    ev = T04 / "evidence" / a.run
    audit = json.loads((ev / "audit.json").read_text(encoding="utf-8"))
    s = pd.read_csv(ev / "stats.csv")
    d = pd.read_csv(ev / "draws.csv")
    dec = pd.read_csv(ev / "decisions.csv")
    sel = pd.read_csv(ev / "selections.csv")
    nav = pd.read_csv(ev / "daily_nav.csv", parse_dates=["date"])
    trades = pd.read_csv(ev / "trades.csv")
    ind_csv = pd.read_csv(ev / "indicators.csv")
    gates_ok = True

    p(f"# T04 analysis of evidence/{a.run}")
    p()
    # ── gates
    p("## Validity gates")
    v1p = ev / "verify_t04.json"
    v1 = json.loads(v1p.read_text(encoding="utf-8")) if v1p.exists() else None
    v2 = audit["v2"]
    v2_ok = v2["label_after_decision"] == 0 and v2["trade_not_after_decision"] == 0 and v2["indicator_bars_after_query_date"] == 0 and v2["decisions_checked"] > 0
    v3 = audit["v3"]
    v4 = audit["v4"]
    v4_ok = v4["overall"] == "PASS" and v4["yearly"] == "PASS"
    v5 = audit["v5"]
    v5_ok = v5["failed"] == 0 and v5["checked"] >= 50
    v1_ok = bool(v1 and v1.get("exit_ok") and all(c.get("compared", 0) > 0 and c.get("failed", 0) == 0 and c.get("missing", 0) == 0 for c in v1["checks"].values()))
    rows = [("V1", "independent check verify_t04.py", "PASS" if v1_ok else ("FAIL" if v1 else "NOT RUN"),
             (f"{sum(c.get('compared', 0) for c in v1['checks'].values()):,} comparisons, {sum(c.get('failed', 0) for c in v1['checks'].values())} failures; corrupted copy detected: {v1['selftest']['detected']}; I5 SuperTrend branch: desk reading" if v1 else "")),
            ("V2", "point in time", "PASS" if v2_ok else "FAIL",
             f"{v2['decisions_checked']} decisions, 0 labels after the decision; {v2['trades_checked']} trades, 0 not after their decision; {v2['indicator_stock_dates_checked']:,} indicator stock-dates, {v2['indicator_bars_after_query_date']} bars after the query date; {v2['weekly_candle_recomputed_stock_dates']} weekly-candle recomputations on bars up to the query date"),
            ("V3", "null holds its table", "PASS" if v3["pass"] else "FAIL",
             f"{v3['draws']:,} draws x 2 windows; {v3['decisions_checked']:,} SELL decisions with k mismatches {v3['k_mismatch']}; {v3['buy_events_checked']:,} BUY events with mismatches {v3['buy_mismatch']}"),
            ("V4", "always-in reproduces the published NAV", "PASS" if v4_ok else "FAIL",
             f"{v4['first']} -> {v4['last']}: CAGR gap {v4['cagr_gap_pp_yr']:+.3f} pp/yr (limit 0.25); worst calendar year {v4['worst_year']} {v4['worst_year_gap_pp']:+.3f} pp (limit 0.5)"),
            ("V5", "indicator reproducibility", "PASS" if v5_ok else "FAIL", f"{v5['checked']} stock-date pairs vs a hand computation, {v5['failed']} failed")]
    gates_ok = all(r[2] == "PASS" for r in rows)
    p(md(pd.DataFrame(rows, columns=["gate", "what", "result", "detail"])))
    p()
    t3x = audit["t03_regime_crosscheck"]
    nx = audit["t03_nav_crosscheck"]
    p(f"Cross-checks against T03 (not gates): regime series equals T03's on {t3x['shared_dates']} shared decision dates with {t3x['mismatches']} mismatches; "
      f"the full-switch comparator reproduces T03's SCMO_0003 strategy NAV (cost 0 / 20.8 / 50) to a maximum relative difference of "
      f"{max(x['max_rel_diff_to_2026-08-07'] for x in nx):.1e} up to 2026-08-07 (after that T03 accrued cash by a 90-session rate; this run reads the extended LBES).")
    p()

    # ── decisions
    st = dec["state"].values
    spells, cur, c = [], int(st[0]), 0
    for v in st:
        if int(v) == cur:
            c += 1
        else:
            spells.append((cur, c)); cur, c = int(v), 1
    spells.append((cur, c))
    sell_sp = [c for v, c in spells if v == 0]
    p("## 4.0 The decision series")
    p(f"- Window {audit['decisions']['t0']} -> {audit['decisions']['end']}: {audit['decisions']['sessions']:,} sessions, {audit['decisions']['n']} weekly decisions (T0 plus the last session of each later ISO week), the last one not traded.")
    p(f"- BUY {audit['decisions']['buy']} weeks, SELL {audit['decisions']['sell']} weeks; {sum(1 for v, _ in spells if v == 0)} SELL spells (the independent unit) of {sorted(sell_sp)} decisions, {sum(1 for v, _ in spells if v == 1)} BUY spells.")
    p(f"- Live window starts {audit['decisions']['live_t0']}: {audit['decisions']['live_decisions']} decisions.")
    p()

    # ── reportability
    p("## 4.0b Reportability and selection counts (SELL decisions only)")
    rp = audit["reportability"]
    rows = []
    for win in ("full", "live"):
        for nm in IND:
            r = rp[f"{win}|{nm}"]
            rows.append({"window": win, "indicator": f"{nm} {NAME[nm]}", "SELL decisions": r["sell_decisions"], "1 <= k < n": r["nontrivial"], "k = 0": r["k_zero"], "k = n": r["k_all"],
                         "mean k": r["mean_k"], "mean n": r["mean_n"], "reportable (>= 20)": "yes" if r["reportable"] else "NO"})
    p(md(pd.DataFrame(rows), {"mean k": "{:.2f}", "mean n": "{:.2f}"}))
    nc = audit["indicators_not_computable_stock_dates"]
    p()
    p(f"Stock-dates where an indicator could not be computed (valid bar, too little history) and the stock was excluded: " + ", ".join(f"{k} {v}" for k, v in nc.items()) + ".")
    p()

    # ── worked example
    p("## 4.0a The worked example (one SELL decision, one trade, one null draw)")
    full_sel = sel[(sel["window"] == "full") & (sel["indicator"] == "I1") & (sel["regime"] == "SELL") & (sel["nontrivial"]) & (sel["n"] >= 8)]
    ex = full_sel[pd.to_datetime(full_sel["decision_date"]) >= pd.Timestamp("2022-06-01")].iloc[0]
    j = int(ex["j"])
    dr = dec[dec["j"] == j].iloc[0]
    p(f"**The decision.** Decision j = {j}, {ex['decision_date']} (the last session of its week). Master SIGN rows: Nifty 100 {dr['sign_Nifty100']} ({dr['label_Nifty100']}), Midcap 100 {dr['sign_MC100']} ({dr['label_MC100']}), Smallcap 100 {dr['sign_SC100']} ({dr['label_SC100']}); not all three BUY, so the regime is SELL.")
    ic = ind_csv[ind_csv["decision_date"] == ex["decision_date"]].copy()
    ic["EMA50 test: close > EMA50"] = np.where(ic["pass_I1"], "keep", "drop")
    p(f"The basket in force (effective {ex['basket_eff']}) has n = {int(ex['n'])} stocks. Indicator I1 (close > 50-day EMA) on their closes up to {ex['decision_date']}:")
    p()
    p(md(ic[["stock", "weight", "close_used", "ema50", "EMA50 test: close > EMA50"]].rename(columns={"close_used": "close", "weight": "basket weight"}), {"basket weight": "{:.4f}", "close": "{:.2f}", "ema50": "{:.2f}"}))
    kept_w = ic.loc[ic["pass_I1"], "weight"].sum()
    p()
    p(f"k = {int(ex['k'])} kept, with basket weights adding to {kept_w:.4f}; the other {1 - kept_w:.4f} of the book goes to the sleeve, half GOLDBEES and half LBES cash ({(1 - kept_w) / 2:.4f} each).")
    tr = trades[(trades["indicator"] == "I1") & (trades["cost_bps"] == PRIMARY)]
    nxt = dec[dec["j"] == j]["trade_date"].iloc[0]
    t1 = tr[tr["date"] == nxt]
    if len(t1):
        t1 = t1.iloc[0]
        p(f"**The trade** (next session, {nxt}, at each instrument's OHLC4): portfolio value before V = {t1['V']:.6f}; value traded = {t1['traded']:.6f}; cost = traded x 20.8 / 2 / 10,000 = {t1['cost']:.6f}; every target is then scaled by (V - cost) / V = {(t1['V'] - t1['cost']) / t1['V']:.6f}. Kept after the trade: {t1['kept']}. NAV at that day's close {t1['nav_close_after']:.6f}.")
    else:
        p(f"**The trade:** the selection on {ex['decision_date']} left the target unchanged, so no trade was made on {nxt}.")
    nv = nav[(nav["kind"] == "strategy") & (nav["indicator"] == "I1") & (nav["cost_bps"] == PRIMARY)].set_index("date")["nav"]
    yrs = (len(nv) - 1) / 252
    p(f"**The path.** I1 at 20.8 bps: NAV 1.0000 on {nv.index[0].date()} -> {nv.iloc[-1]:.4f} on {nv.index[-1].date()}; {len(nv):,} sessions, years = ({len(nv):,} - 1) / 252 = {yrs:.3f}; CAGR = {nv.iloc[-1]:.4f}^(1/{yrs:.3f}) - 1 = {100 * (nv.iloc[-1] ** (1 / yrs) - 1):.2f}%.")
    wmx = pd.read_csv(AA / "data" / "holdings_matrix" / "SCMO_0003_holding_weight_matrix.csv", index_col=0, nrows=0)
    ncol = len(wmx.columns)
    stocks_all = list(wmx.columns)
    uu = np.random.default_rng([4, 1, 0]).random((len(dec), ncol))
    bset = [stocks_all.index(x) for x in ic["stock"]]
    pick = [stocks_all[bset[i]] for i in np.argsort(uu[j, bset], kind="stable")[: int(ex["k"])]]
    p(f"**One null draw** (I1, draw_id 0, seed `default_rng([4, 1, 0])`, u of shape ({len(dec)}, {ncol})): on the same decision the draw keeps the k = {int(ex['k'])} stocks of the {int(ex['n'])} with the smallest u: {', '.join(pick)} (the indicator kept {ex['kept'].replace(';', ', ')}). Everything else is as the strategy. That draw's after-cost CAGR is "
      f"{100 * d[(d.indicator == 'I1') & (d.window == 'full') & (d.sleeve == '50_50') & (d.cash == 'lbes') & (d.cost_bps == PRIMARY) & (d.draw_id == 0)]['cagr'].iloc[0]:.2f}%.")
    p()

    # ── headline
    p("## 4.1 Headline: after cost at 20.8 bps, full window, 50/50 sleeve, LBES cash")
    rows = []
    res = {}
    base = (s["window"] == "full") & (s["sleeve"] == "50_50") & (s["cash"] == "lbes")
    for nm in IND:
        r = s[(s.kind == "strategy") & (s.indicator == nm) & base & (s.cost_bps == PRIMARY)].iloc[0]
        x = d[(d.indicator == nm) & (d.window == "full") & (d.sleeve == "50_50") & (d.cash == "lbes") & (d.cost_bps == PRIMARY)]
        pc, pv = percentile(x["cagr"], r["cagr"])
        pm, pvm = percentile(x["max_dd"], r["max_dd"])
        rep = rp[f"full|{nm}"]["reportable"]
        res[nm] = dict(pc=pc, pm=pm, rep=rep, sd_c=x["cagr"].std(), sd_m=x["max_dd"].std(), cagr=r["cagr"], mdd=r["max_dd"], null_c=x["cagr"].mean(), null_m=x["max_dd"].mean(),
                       trades=r["trades"], null_trades=float(x["trades"].mean()), c1=rep and pc >= PASS_MARK, c2=rep and pm >= PASS_MARK, pv_c=pv, pv_m=pvm)
        rows.append({"indicator": f"{nm} {NAME[nm]}", "CAGR %": 100 * r["cagr"], "null mean %": 100 * x["cagr"].mean(), "null SD pp": 100 * x["cagr"].std(), "C1 percentile": pc, "p": pv,
                     "C1": "PASS" if res[nm]["c1"] else "FAIL", "max DD %": 100 * r["max_dd"], "null mean DD %": 100 * x["max_dd"].mean(), "C2 percentile": pm, "C2": "PASS" if res[nm]["c2"] else "FAIL",
                     "end NAV": r["end_nav"], "trades": int(r["trades"])})
    p(f"Window {audit['decisions']['t0']} -> {audit['decisions']['end']}; 2,000 draws per indicator; pass mark percentile >= {PASS_MARK:.0f} (Bonferroni, 5 indicators, alpha 0.10).")
    p()
    p(md(pd.DataFrame(rows), {"p": "{:.4f}", "C1 percentile": "{:.1f}", "C2 percentile": "{:.1f}", "end NAV": "{:.3f}"}))
    p()

    p("### Secondary statistics (percentile against the same draws; direction: higher is better for Calmar, lower is better for the rest)")
    rows = []
    for nm in IND:
        r = s[(s.kind == "strategy") & (s.indicator == nm) & base & (s.cost_bps == PRIMARY)].iloc[0]
        x = d[(d.indicator == nm) & (d.window == "full") & (d.sleeve == "50_50") & (d.cash == "lbes") & (d.cost_bps == PRIMARY)]
        row = {"indicator": f"{nm} {NAME[nm]}"}
        for col, hb, lab in (("vol", False, "vol"), ("ulcer", False, "Ulcer"), ("days_below_10pct", False, "days >=10% below peak"), ("longest_underwater", False, "longest under water"), ("calmar", True, "Calmar")):
            row[lab] = f"{r[col]:.3g} (pct {percentile(x[col], r[col], hb)[0]:.1f})"
        rows.append(row)
    p(md(pd.DataFrame(rows)))
    p()

    # ── what the null does not hold: turnover
    p("### What the null does not hold: trades and cost paid (20.8 bps)")
    rows = []
    for nm in IND:
        r = s[(s.kind == "strategy") & (s.indicator == nm) & base & (s.cost_bps == PRIMARY)].iloc[0]
        x = d[(d.indicator == nm) & (d.window == "full") & (d.sleeve == "50_50") & (d.cash == "lbes") & (d.cost_bps == PRIMARY)]
        rows.append({"indicator": f"{nm} {NAME[nm]}", "strategy trades": int(r["trades"]), "null mean trades": x["trades"].mean(), "strategy cost paid (NAV)": r["cost_paid"], "null mean cost paid": x["cost_paid"].mean(),
                     "CAGR gap pp (strategy - null mean)": 100 * (r["cagr"] - x["cagr"].mean())})
    p(md(pd.DataFrame(rows), {"null mean trades": "{:.0f}", "strategy cost paid (NAV)": "{:.3f}", "null mean cost paid": "{:.3f}", "CAGR gap pp (strategy - null mean)": "{:+.2f}"}))
    p()
    p("A random pick changes every week, so a null draw trades far more than a moving-average filter does. The null is built to hold *how many* stocks are kept, not *how often the kept set changes*; the 0 bps row of R2 shows how much of each indicator's after-cost edge is this turnover difference.")
    p()

    # ── comparators
    p("## 4.2 Comparators (benchmarks, not nulls), full window")
    rows = []
    for kind, lab in (("hold_parent", "hold the parent"), ("full_aa_switch", "full AA switch (100% sleeve in SELL; T03's rule)")):
        for cost in (0.0, PRIMARY, 50.0):
            r = s[(s.kind == kind) & (s.cost_bps == cost)].iloc[0]
            rows.append({"run": lab, "cost bps": cost, "CAGR %": 100 * r["cagr"], "max DD %": 100 * r["max_dd"], "vol %": 100 * r["vol"], "Calmar": r["calmar"], "end NAV": r["end_nav"], "trades": int(r["trades"])})
    for nm in IND:
        for cost in (PRIMARY,):
            r = s[(s.kind == "constant_mix") & (s.indicator == nm) & (s.cost_bps == cost)].iloc[0]
            rows.append({"run": f"constant mix at {nm}'s equity share f = {r['mean_equity_share']:.3f}", "cost bps": cost, "CAGR %": 100 * r["cagr"], "max DD %": 100 * r["max_dd"], "vol %": 100 * r["vol"], "Calmar": r["calmar"], "end NAV": r["end_nav"], "trades": int(r["trades"])})
    for nm in IND:
        r = s[(s.kind == "strategy") & (s.indicator == nm) & base & (s.cost_bps == PRIMARY)].iloc[0]
        rows.append({"run": f"strategy {nm} {NAME[nm]}", "cost bps": PRIMARY, "CAGR %": 100 * r["cagr"], "max DD %": 100 * r["max_dd"], "vol %": 100 * r["vol"], "Calmar": r["calmar"], "end NAV": r["end_nav"], "trades": int(r["trades"])})
    p(md(pd.DataFrame(rows), {"Calmar": "{:.2f}", "end NAV": "{:.3f}"}))
    p()
    pub = nav[nav["kind"] == "published_SCMO_0003"].set_index("date")["nav"]
    pub42 = nav[nav["kind"] == "published_SCMO_0042"].set_index("date")["nav"]
    yp = (pub.index[-1] - pub.index[0]).days / 365.25
    y42 = (pub42.index[-1] - pub42.index[0]).days / 365.25
    p(f"Published NAV SCMO_0003 (D17, rebased): {pub.index[0].date()} -> {pub.index[-1].date()}, {100 * (pub.iloc[-1] ** (1 / yp) - 1):.2f}% a year (calendar-day years). "
      f"Published SCMO_0042 (production overlay, `indices.csv`, descriptive only): {pub42.index[0].date()} -> {pub42.index[-1].date()}, {100 * (pub42.iloc[-1] ** (1 / y42) - 1):.2f}% a year.")
    p()
    # yearly returns
    p("### Calendar-year returns at 20.8 bps (strategy NAV, % ; first and last years are part years)")
    series = {"hold parent": nav[(nav.kind == "hold_parent") & (nav.cost_bps == PRIMARY)], "full AA switch": nav[(nav.kind == "full_aa_switch") & (nav.cost_bps == PRIMARY)]}
    for nm in IND:
        series[nm] = nav[(nav.kind == "strategy") & (nav.indicator == nm) & (nav.cost_bps == PRIMARY)]
    ytab = {}
    for k, v in series.items():
        sr = v.set_index("date")["nav"]
        ye = sr.groupby(sr.index.year).last()
        ytab[k] = (ye / ye.shift(1).fillna(1.0) - 1) * 100
    yt = pd.DataFrame(ytab).rename_axis("year").reset_index()
    yt["year"] = yt["year"].astype(int)
    p(md(yt, {c: "{:.1f}" for c in yt.columns if c != "year"}))
    p()

    # ── power
    p("## 4.3 Power and the minimum detectable edge (80% power, pass mark 98)")
    rows = [{"indicator": f"{nm} {NAME[nm]}", "SD of null CAGR pp": 100 * res[nm]["sd_c"], "MDE CAGR pp": Z * 100 * res[nm]["sd_c"], "SD of null max DD pp": 100 * res[nm]["sd_m"], "MDE max DD pp": Z * 100 * res[nm]["sd_m"],
             "strategy minus null mean, CAGR pp": 100 * (res[nm]["cagr"] - res[nm]["null_c"])} for nm in IND]
    p(md(pd.DataFrame(rows), {"strategy minus null mean, CAGR pp": "{:+.2f}"}))
    p()
    p(f"MDE = (z_0.98 + z_0.80) x SD = 2.894 x SD of the null. With {sum(1 for v, _ in spells if v == 0)} SELL spells the effective sample is small, and the MDE is the edge the test could have seen at 80% power.")
    p()

    # ── verdict
    p("## 4.4 Verdict against each pre-registered criterion")
    rows = [{"indicator": f"{nm} {NAME[nm]}", "reportable": "yes" if res[nm]["rep"] else "NO", "C1 CAGR pct": res[nm]["pc"], "C1": "PASS" if res[nm]["c1"] else "FAIL",
             "C2 max-DD pct": res[nm]["pm"], "C2": "PASS" if res[nm]["c2"] else "FAIL"} for nm in IND]
    p(md(pd.DataFrame(rows), {"C1 CAGR pct": "{:.1f}", "C2 max-DD pct": "{:.1f}"}))
    p()
    c1p = [nm for nm in IND if res[nm]["c1"]]
    c2p = [nm for nm in IND if res[nm]["c2"]]
    both = [nm for nm in IND if res[nm]["c1"] and res[nm]["c2"]]
    p(f"- Passing C1 (selection): {', '.join(c1p) if c1p else 'none'}. Passing C2 (protection): {', '.join(c2p) if c2p else 'none'}. Passing both: {', '.join(both) if both else 'none'}.")
    fa = s[(s.kind == "full_aa_switch") & (s.cost_bps == PRIMARY)].iloc[0]
    best = max(IND, key=lambda n: res[n]["cagr"])
    p(f"- Best indicator by after-cost CAGR: {best} {NAME[best]} at {100 * res[best]['cagr']:.2f}% against the full AA switch's {100 * fa['cagr']:.2f}% and holding the parent's {100 * s[(s.kind == 'hold_parent') & (s.cost_bps == PRIMARY)].iloc[0]['cagr']:.2f}%.")
    p()

    # ── robustness
    p("## Robustness (R1 to R5)")
    rows = []

    def row_for(nm, win, sl, cash, cost):
        r = s[(s.kind == "strategy") & (s.indicator == nm) & (s.window == win) & (s.sleeve == sl) & (s.cash == cash) & (s.cost_bps == cost)].iloc[0]
        x = d[(d.indicator == nm) & (d.window == win) & (d.sleeve == sl) & (d.cash == cash) & (d.cost_bps == cost)]
        return r, x, percentile(x["cagr"], r["cagr"])[0], percentile(x["max_dd"], r["max_dd"])[0]
    for nm in IND:
        row = {"indicator": f"{nm} {NAME[nm]}"}
        for lab, win, sl, cash, cost in (("R2 0 bps", "full", "50_50", "lbes", 0.0), ("R2 50 bps", "full", "50_50", "lbes", 50.0), ("R3 LIQUIDCASE", "full", "50_50", "liquidcase", PRIMARY)):
            r, x, pc, pm = row_for(nm, win, sl, cash, cost)
            row[f"{lab} C1 pct"] = pc
        r, x, pc, pm = row_for(nm, "full", "gold100", "lbes", PRIMARY)
        row["R1 C1 pct"], row["R1 C2 pct"] = pc, pm
        rl = rp[f"live|{nm}"]["reportable"]
        r, x, pc, pm = row_for(nm, "live", "50_50", "lbes", PRIMARY)
        row["R4 live CAGR %"] = 100 * r["cagr"]
        row["R4 C1 pct"] = pc if rl else float("nan")
        row["R4 C2 pct"] = pm if rl else float("nan")
        rows.append(row)
    rb = pd.DataFrame(rows)
    p(md(rb, {c: "{:.1f}" for c in rb.columns if c != "indicator"}))
    p()
    p("R1 uses a 100% GOLDBEES sleeve (own null); R2 changes the cost; R3 swaps LBES for LIQUIDCASE from 2024-01-24; R4 is the live window 2021-11 onward with its own k counts and its own null. Percentiles at or above 98 are marked in section 4.4's logic; here every column is just the percentile.")
    p()
    best_draw = d[(d.window == "full") & (d.sleeve == "50_50") & (d.cash == "lbes") & (d.cost_bps == PRIMARY)].pivot(index="draw_id", columns="indicator", values="cagr").max(axis=1)
    sb = max(res[n]["cagr"] for n in IND)
    pc5, pv5 = percentile(best_draw.values, sb)
    p(f"**R5 best-of-sweep null.** The best of the five indicators ({best} {NAME[best]}, after-cost CAGR {100 * sb:.2f}%) is ranked against the best of five random indicators per draw id: percentile {pc5:.1f}, p = {pv5:.4f} (pass mark {PASS_MARK:.0f}); the null's best-of-five averages {100 * best_draw.mean():.2f}% (SD {100 * best_draw.std():.2f} pp). R5: **{'PASS' if pc5 >= PASS_MARK else 'FAIL'}**.")
    p()
    p(f"READINGS (engine): " + "; ".join(f"{k}: {v}" for k, v in audit["readings"].items()))
    p()
    gl = audit["goldbees_fills_not_despiked"]
    p("GOLDBEES trade sessions after the MCX file's end (2026-09-28), fill = raw OHLC4: " + "; ".join(f"{g['date']} {g['fill_over_close_pct']:+.2f}% from close" for g in gl) + ".")
    p()
    p(f"Run: {audit['run']['name']}, {audit['run']['draws']} draws per indicator, {audit['run']['seconds']} s, seed {audit['run']['seed']}; pre-registration sha256 {audit['prereg_sha256']}.")
    (T04 / "analysis.log").write_text("\n".join(OUT) + "\n", encoding="utf-8")
    json.dump({"res": res, "r5": {"pct": pc5, "p": pv5, "best": best}, "gates_ok": gates_ok}, open(ev / "analysis_summary.json", "w"), indent=1, default=float)
    if not gates_ok:
        print("A VALIDITY GATE DID NOT PASS: nothing above may be read.")
        sys.exit(1)


if __name__ == "__main__":
    main()
