# -*- coding: utf-8 -*-
"""
Build evidence/final_strategy/report.html: the final rule on each of the four
AA books. Per book and period: equity curve against the parent and the live
AA, drawdowns, allocation over time (and the live AA's own allocation), stats,
yearly returns, a constituents-by-rebalance weight grid, and every rebalance
with its holdings before and after. Data comes from final_strategy.py's CSVs.
"""

from __future__ import annotations

import datetime
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from common import EVIDENCE_DIR, PAIRS, load_state

E = EVIDENCE_DIR / "final_strategy"
TPL = EVIDENCE_DIR.parent / "why_report_template.html"
PER = {"live": ("live 2021-11 -> 2026-08", "live", "Live window 2021-11 → 2026-08"),
       "oos": ("before the books 2014-07 -> 2021-10", "2014_2021", "Before the books 2014-07 → 2021-10")}
STRATS = [("final", "FINAL: triple + 80/20 gold-timed sleeve (weekly re-check)", "Final rule"),
          ("variant", "variant: triple + 80/20 split fixed at sleeve entry", "Final rule, split fixed at sleeve entry"),
          ("gb_signal", "variant: final rule with the GOLDBEES gold signal (previous)", "Final rule, GOLDBEES gold signal (previous version)"),
          ("t5050", "triple + fixed 50/50 sleeve", "Three-index rule + fixed 50/50 sleeve"),
          ("current", "current rule (FS>=0.60) + 50/50 sleeve", "Current AA rule (re-simulated)"),
          ("parent_h", "parent (no overlay)", "Parent (same engine)"),
          ("parent_pub", "published parent NAV", "Parent, published NAV"),
          ("aa_pub", "published AA NAV (as traded)", "Live AA, published NAV")]


def r4(x, d=5):
    return None if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))) else round(float(x), d)


def clean(x):
    if isinstance(x, dict):
        return {str(k): clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [clean(v) for v in x]
    if isinstance(x, (np.floating, float)):
        return r4(x)
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (pd.Timestamp, datetime.date)):
        return str(pd.Timestamp(x).date())
    return x


PROD_MASTER = Path(r"G:\.shortcut-targets-by-id\0B7f_UMMZHM_JNXljMVVXY2VPcHM\Investment Research_N"
                   r"\Shubham_Shreshtha\Friday Rebalance Automation\RSI\Final\Analysis")
SIG_SRC = [("N100", "Nifty 100", PROD_MASTER / "Master_Nifty100.xlsx"), ("MC100", "Midcap 100", PROD_MASTER / "Master_MC100.xlsx"),
           ("SC100", "Smallcap 100", PROD_MASTER / "Master_SC100.xlsx"), ("MAUc1", "MAUc1 (gold)", None)]


def latest_signals(n_weeks: int = 8) -> dict:
    """
    The last n weekly reviews from the four ST.py Master files: the Friday job's
    Nifty100 / MC100 / SC100 (read live, read-only) and Master_MAUc1.xlsx. For each
    signal: SIGN, the week's close, its supertrend line, and the move a close would
    need to cross that line (line / close - 1). The rule's holding follows from them.
    """
    from final_strategy import FRA_MAUC1, IS_END
    M = {}
    for k, _, path in SIG_SRC:
        path = path or FRA_MAUC1 / "RSI" / "Final" / "Analysis" / "Master_MAUc1.xlsx"
        d = pd.read_excel(path)
        d["Date"] = pd.to_datetime(d["Date"])
        M[k] = d.drop_duplicates("Date", keep="last").set_index("Date").sort_index()
    weeks = M["SC100"].index[-n_weeks:]
    assert all(w in M[k].index for k in M for w in weeks), "a signal is missing a week"
    rows = []
    for w in weeks:
        t = M["SC100"].loc[w, "WGH_SRT"]
        r = {"review": w, "trade": None if pd.isna(t) else pd.Timestamp(t), "after": bool(w > IS_END), "sig": {}}
        for k in M:
            x = M[k].loc[w]
            r["sig"][k] = {"s": x.SIGN, "c": float(x.Index), "st": float(x.ST), "gap": float(x.ST / x.Index - 1)}
        all3 = all(r["sig"][k]["s"] == "BUY" for k in ("N100", "MC100", "SC100"))
        r["holds"] = ("100% parent basket" if all3 else
                      "80% GOLDBEES / 20% cash" if r["sig"]["MAUc1"]["s"] == "BUY" else "20% GOLDBEES / 80% cash")
        rows.append(r)
    # the latest holding, and the review whose trade put it in place
    alln = M["SC100"].index[M["SC100"].index <= weeks[-1]]
    def holds_at(w):
        s3 = [M[k].loc[w, "SIGN"] if w in M[k].index else None for k in ("N100", "MC100", "SC100")]
        g = M["MAUc1"].loc[w, "SIGN"] if w in M["MAUc1"].index else None
        return "100% parent basket" if all(x == "BUY" for x in s3) else ("80% GOLDBEES / 20% cash" if g == "BUY" else "20% GOLDBEES / 80% cash")
    since = weeks[-1]
    for w in reversed(alln[:-1]):
        if holds_at(w) != rows[-1]["holds"]:
            break
        since = w
    return {"rows": rows, "labels": {k: lab for k, lab, _ in SIG_SRC}, "order": [k for k, _, _ in SIG_SRC],
            "since_review": since, "since_trade": M["SC100"].loc[since, "WGH_SRT"], "backtest_end": IS_END,
            "read_on": datetime.date.today()}


def main():
    C = pd.read_csv(E / "nav_curves_daily.csv", index_col=0, parse_dates=True)
    S = pd.read_csv(E / "summary_stats.csv")
    Y = pd.read_csv(E / "yearly_returns.csv", index_col=0)
    T = pd.read_csv(E / "trade_log.csv", parse_dates=["entry", "review"])
    P = pd.read_csv(E / "position_log.csv", parse_dates=["entry", "review"])
    V = pd.read_csv(E / "verification.csv") if (E / "verification.csv").exists() else None
    final_name = STRATS[0][1]
    T = T[T.strategy == final_name]
    P = P[P.strategy == final_name]
    data = {}
    for pk, (plab, tag, _) in PER.items():
        for aa in PAIRS:
            key = f"{pk}|{aa}"
            cols = {k: f"{plab}|{aa}|{nm}" for k, nm, _ in STRATS if f"{plab}|{aa}|{nm}" in C}
            X = C[list(cols.values())].dropna(how="all")
            X.columns = list(cols)
            X = X[X["final"].notna()]
            dd = pd.read_csv(E / f"daily_{aa}_{tag}.csv", index_col=0, parse_dates=True).reindex(X.index)
            first_trade = T[(T.period == plab) & (T.aa == aa)].entry.min()
            al = pd.DataFrame({"equity": dd.equity_value / dd.harness_nav, "gold": dd.gold_value / dd.harness_nav,
                               "cash": dd.cash_value / dd.harness_nav}, index=X.index)
            al.loc[al.index < first_trade] = np.nan
            rec = {"dates": [str(d.date()) for d in X.index],
                   "series": {k: [r4(v) for v in X[k]] for k in X.columns},
                   "alloc": {k: [r4(v, 4) for v in al[k]] for k in al.columns}}
            if pk == "live":
                st = load_state(aa)
                st = st[(st.index >= X.index[0]) & (st.index <= X.index[-1])]
                rec["aa_alloc"] = {"dates": [str(d.date()) for d in st.index], "equity": [r4(v, 4) for v in st.w_equity],
                                   "gold": [r4(v, 4) for v in st.w_gold], "cash": [r4(v, 4) for v in st.w_liquid],
                                   "bond": [r4(v, 4) for v in st.w_bond], "last": str(st.index.max().date())}
            srows = []
            for k, nm, lab in STRATS:
                x = S[(S.period == plab) & (S.aa == aa) & (S.strategy == nm)]
                if len(x):
                    r = x.iloc[0]
                    srows.append({"key": k, "label": lab, "cagr": r.cagr, "vol": r.vol, "dd": r.max_dd_daily, "ddf": r.max_dd_friday,
                                  "calmar": r.calmar, "sharpe": r.sharpe_vs_cash, "tr": r.total_return,
                                  "eqw": r.get("avg_equity_weight"), "sw": r.get("switches_equity_sleeve"),
                                  "rs": r.get("sleeve_resplits"), "cost": r.get("cost_paid_share_of_nav")})
            rec["stats"] = srows
            yrows = []
            for k, nm, lab in STRATS:
                idx = f"{plab}|{aa}|{nm}"
                if idx in Y.index:
                    y = Y.loc[idx].dropna()
                    yrows.append({"key": k, "label": lab, "vals": {str(int(float(c))): r4(v) for c, v in y.items()}})
            rec["yearly"] = yrows
            tt = T[(T.period == plab) & (T.aa == aa)].sort_values("entry")
            pp = P[(P.period == plab) & (P.aa == aa)]
            trades, pos = [], {}
            for r in tt.itertuples():
                g = pp[pp.entry == r.entry]
                gold = float(g[g.key == "GOLDBEES"].w_after.sum())
                cash = float(g[g.key == "CASH"].w_after.sum())
                eq = float(g[~g.key.isin(["GOLDBEES", "CASH"])].w_after.sum())
                trades.append({"entry": r.entry, "review": r.review, "kind": r.kind, "eq": eq, "gold": gold, "cash": cash,
                               "n": int((g.w_after > 0).sum()), "turn": r.turnover_frac, "cost": r.cost / (r.nav_at_fill + r.cost) if hasattr(r, "nav_at_fill") else r.cost,
                               "nav": r.nav})
                items = []
                for q in g.itertuples():
                    tk = q.ticker if isinstance(q.ticker, str) and q.ticker and q.ticker != q.key else ""
                    label = {"GOLDBEES": "GOLDBEES", "CASH": "Cash (LBES)"}.get(q.key, tk or q.key)
                    items.append({"k": q.key, "t": label, "n": q.name if isinstance(q.name, str) else "", "b": q.w_before, "a": q.w_after, "p": q.fill_price})
                items.sort(key=lambda z: (-(z["a"] or 0), -(z["b"] or 0)))
                pos[str(r.entry.date())] = items
            rec["trades"] = trades
            rec["pos"] = pos
            data[key] = rec
    payload = clean({"books": list(PAIRS), "parent": PAIRS, "periods": {k: {"label": v[2]} for k, v in PER.items()},
                     "data": data, "verification": V.to_dict(orient="records") if V is not None else [],
                     "latest": latest_signals()})
    css = TPL.read_text(encoding="utf-8").split("</style>")[0].split("<style>")[1]
    html = PAGE.replace("/*__CSS__*/", css).replace("__DATA__", json.dumps(payload, separators=(",", ":"), allow_nan=False))
    (E / "report.html").write_text(html, encoding="utf-8")
    print("wrote", E / "report.html", round(len(html) / 1024), "KB")


PAGE = r"""<title>Final Rule Backtest</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600&family=Newsreader:opsz,wght@6..72,400;6..72,500;6..72,600&display=swap">
<style>
/*__CSS__*/
.bar{position:sticky;top:env(safe-area-inset-top,0px);z-index:5;background:var(--page);padding:10px 0 10px;border-bottom:1px solid var(--border);margin:0 0 8px}
.bar .controls{margin:0}
.ctl{font-family:var(--mono);font-size:10.5px;letter-spacing:.1em;text-transform:uppercase;color:var(--muted)}
.rule{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin:18px 0 6px}
.rule div{background:var(--surface-1);border:1px solid var(--border);border-radius:10px;padding:12px 14px;font-size:13.5px;line-height:1.5}
.rule b{display:block;font-family:var(--mono);font-size:10.5px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);font-weight:500;margin-bottom:4px}
@media (max-width:820px){.rule{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media (max-width:480px){.rule{grid-template-columns:1fr}}
.kpis{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin:14px 0}
.kpi{background:var(--surface-1);border:1px solid var(--border);border-radius:10px;padding:12px 14px}
.kpi .l{font-family:var(--mono);font-size:10.5px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted)}
.kpi .v{font-family:var(--serif);font-size:28px;line-height:1.15;margin-top:4px}
.kpi .s{font-size:12.5px;color:var(--text-secondary);margin-top:2px}
@media (max-width:720px){.kpis{grid-template-columns:repeat(2,minmax(0,1fr))}}
.toggles{display:flex;flex-wrap:wrap;gap:8px;margin:6px 0 8px}
.tg{display:inline-flex;align-items:center;gap:7px;font:500 11.5px var(--mono);color:var(--text-secondary);background:transparent;border:1px solid var(--border);border-radius:999px;padding:5px 10px;cursor:pointer}
.tg[aria-pressed="false"]{opacity:.45}
.tg i{width:14px;height:3px;border-radius:2px;display:inline-block}
.heat{border-collapse:separate;border-spacing:0;font-size:11px}
.heat th,.heat td{padding:3px 5px;border-bottom:1px solid var(--border);text-align:right}
.heat th{font-size:9.5px;letter-spacing:.02em;text-transform:none;white-space:nowrap;writing-mode:vertical-rl;transform:rotate(180deg);height:78px;vertical-align:bottom;padding:4px 2px}
.heat th.nm,.heat td.nm{position:sticky;left:0;background:var(--page);z-index:2;text-align:left;writing-mode:horizontal-tb;transform:none;height:auto;min-width:150px;max-width:190px;overflow:hidden;text-overflow:ellipsis;font-family:var(--sans);font-size:12px}
.heat td.c{min-width:30px;font-family:var(--mono);font-size:10px;color:var(--text-primary)}
.heat tr.sl td.nm{font-weight:600}
.kind{display:inline-block;font:500 10.5px var(--mono);padding:2px 7px;border-radius:999px;border:1px solid var(--border);white-space:nowrap}
.kind.out{color:var(--neg)} .kind.in{color:var(--pos)}
.sig{display:inline-block;font-family:var(--mono);font-size:11px;font-weight:600;letter-spacing:.04em;padding:1px 6px;border-radius:4px;border:1px solid currentColor}
.sig.buy{color:var(--pos)} .sig.sell{color:var(--neg)}
.flip{display:block;font-size:11.5px;color:var(--muted);margin-top:2px;font-variant-numeric:tabular-nums}
tr.after td:first-child::after{content:"after backtest";display:block;font-size:10.5px;color:var(--muted);font-family:var(--mono);letter-spacing:.04em}
.nowlead{font-size:15px;line-height:1.55;max-width:75ch;margin:6px 0 10px}
.rb td{vertical-align:top}
.rb button{font:500 11px var(--mono);background:transparent;border:1px solid var(--border);border-radius:6px;padding:3px 8px;cursor:pointer;color:var(--text-secondary)}
.detail td{background:var(--surface-1)}
.detail table{margin:6px 0 10px;font-size:12px}
.detail td,.detail th{padding:4px 8px}
.note{font-size:13px;color:var(--text-secondary)}
#stats th,#stats td,#rb th,#rb td{padding:7px 6px}
#rb .detail td{padding:0 6px}
#stats td.l{white-space:normal;min-width:170px}
.bar .seg{flex-wrap:wrap;max-width:100%}
.bar .controls{gap:8px 14px}
</style>

<div class="wrap">
  <p class="eyebrow">AA smallcases · final rule backtest · four books · signal at Friday close, trade Monday at OHLC4</p>
  <h1>Three indices must agree for equity; otherwise gold and cash, weighted by MCX gold's trend</h1>
  <p class="sub">Each AA book is shown against its parent smallcase and the live AA as it actually traded. Pick a book and a period. Every chart, table and holding below comes from the same backtest the Excel workbook reproduces.</p>
  <p class="meta">Live window 2021-11 → 2026-08, plus the parents' real baskets 2014-07 → 2021-10 · every signal from the desk's production ST.py on weekly candles: Nifty 100, Midcap 100, Smallcap 100 and MAUc1 (MCX gold futures) · stocks filled at the Monday OHLC4, GOLDBEES at the Monday OHLC4 with ETF-only spikes clipped · 20.8 bps round trip · workbook: <code>AA/analysis/evidence/final_strategy/final_strategy_workbook_mauc1.xlsx</code></p>

  <div class="rule">
    <div><b>1 · Equity</b>Hold the whole parent portfolio while Nifty 100, Nifty Midcap 100 and Nifty Smallcap 100 are all BUY on the weekly supertrend.</div>
    <div><b>2 · Sleeve</b>If any of the three is SELL, move the whole book to gold (GOLDBEES) and cash (LBES).</div>
    <div><b>3 · Split</b>Inside the sleeve, 80% GOLDBEES / 20% cash if the weekly supertrend of MAUc1 (MCX gold futures) is BUY; 20% / 80% if it is SELL. Re-checked each week while in the sleeve. Before MAUc1's first signal (2015-03-13) the sleeve holds 50/50.</div>
    <div><b>4 · Timing</b>Signals at Friday's close; trades on the next session (Monday, or Tuesday after a holiday) at (open+high+low+close)/4. For GOLDBEES, open, high and low are first pulled into its close ± (MCX gold's range that day + 0.5%). No trade while the target is unchanged.</div>
  </div>

  <h2 id="now" style="margin-top:26px">Where the rule stands now</h2>
  <p class="nowlead" id="nowLead"></p>
  <div class="tw"><table id="nowT"></table></div>
  <p class="cap" id="nowCap"></p>

  <div class="bar"><div class="controls"><span class="ctl">Book</span><div class="seg" id="bk"></div><span class="ctl">Period</span><div class="seg" id="pr"></div></div></div>

  <h2 id="summary" style="margin-top:28px">Summary</h2>
  <div class="kpis" id="kpis"></div>
  <div class="tw"><table id="stats"></table></div>
  <p class="cap" id="statsCap"></p>

  <h2 id="curve">Equity curve</h2>
  <div class="toggles" id="tgl"></div>
  <div class="card"><div id="chart"></div></div>
  <div class="panel-title">Drawdown from peak</div>
  <div class="card"><div id="dd"></div></div>
  <div class="grid2">
    <div><div class="panel-title">Final rule: allocation</div><div class="card"><div id="alloc"></div></div></div>
    <div><div class="panel-title" id="aaAllocTitle">Live AA: allocation from its weight file</div><div class="card"><div id="aaAlloc"></div></div></div>
  </div>
  <p class="cap" id="allocCap"></p>

  <h2 id="yearly">Year by year</h2>
  <div class="tw"><table id="yr"></table></div>

  <h2 id="constituents">Constituents over time</h2>
  <p>One column per rebalance of the final rule, one row per holding. Each cell is the holding's weight straight after that rebalance. Between rebalances weights drift with prices. Hover a cell for its value.</p>
  <div class="tw" style="max-height:640px;overflow:auto"><table class="heat" id="heat"></table></div>

  <h2 id="rebalances">Every rebalance</h2>
  <p>Each row is one trade day. "Show" opens every holding's weight before and after, with its fill price.</p>
  <div class="tw"><table class="rb" id="rb"></table></div>

  <div class="foot" id="foot"></div>
</div>
<script id="data" type="application/json">__DATA__</script>
<script>
(function(){
"use strict";
const D = JSON.parse(document.getElementById("data").textContent);
const $ = s => document.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const pct = (x, d=1) => x == null ? "–" : (x*100).toFixed(d).replace("-", "−") + "%";
const pp = (x, d=1) => x == null ? "–" : (x >= 0 ? "+" : "−") + Math.abs(x*100).toFixed(d);
const cls = x => x == null ? "" : x > 0.0005 ? "pos" : x < -0.0005 ? "neg" : "";
const SER = {final: ["Final rule", "var(--s1)", 2.6, ""], parent_pub: ["Parent, published NAV", "var(--s5)", 1.8, ""],
  parent_h: ["Parent (same engine)", "var(--s5)", 1.6, "5 4"], aa_pub: ["Live AA, published NAV", "var(--s2)", 1.8, ""],
  t5050: ["Three-index + 50/50 sleeve", "var(--s3)", 1.6, ""], current: ["Current AA rule (re-simulated)", "var(--s4)", 1.6, ""],
  variant: ["Final rule, split fixed at entry", "var(--s7)", 1.6, "3 3"], gb_signal: ["Final rule, GOLDBEES gold signal (previous)", "var(--s8)", 1.6, "2 3"]};
const ORDER = ["final", "aa_pub", "parent_pub", "parent_h", "t5050", "current", "variant", "gb_signal"];
const ON = {live: new Set(["final", "aa_pub", "parent_pub"]), oos: new Set(["final", "parent_h", "t5050"])};
const LAYER = {equity: ["Equity (parent basket)", "var(--s7)"], gold: ["Gold (GOLDBEES)", "var(--s4)"], cash: ["Cash (LBES)", "var(--s3)"], bond: ["Bond ETF", "var(--s8)"]};
let book = "SCMO_0042", per = "live";
try { const h = (location.hash || "").replace("#", ""); const m = D.books.find(b => b.endsWith(h)); if (m) book = m; } catch (e) {}

function seg(host, vals, labels, get, set){
  host.innerHTML = vals.map((v, i) => `<button type="button" aria-pressed="${v===get()}" data-i="${i}">${labels[i]}</button>`).join("");
  host.querySelectorAll("button").forEach(b => b.addEventListener("click", () => { set(vals[+b.dataset.i]); host.querySelectorAll("button").forEach(x => x.setAttribute("aria-pressed", x === b)); }));
}
const NS = "http://www.w3.org/2000/svg";
const el = (t, a, p) => { const e = document.createElementNS(NS, t); for (const k in a) e.setAttribute(k, a[k]); if (p) p.appendChild(e); return e; };
function logTicks(lo, hi){ const c = [0.25,0.5,0.75,1,1.25,1.5,2,2.5,3,4,5,6,8,10]; return c.filter(v => v >= lo && v <= hi); }
function frame(host, H){ host.innerHTML = ""; host.classList.add("chartbox"); const W = Math.max(300, host.clientWidth || 800); return [W, H]; }
function xAxis(svg, T, X, H, m){ const y0 = new Date(T[0]).getUTCFullYear(), y1 = new Date(T[T.length-1]).getUTCFullYear(), st = (y1 - y0) > 9 ? 2 : 1;
  for (let y = y0 + 1; y <= y1; y += st){ el("text", {x: X(Date.UTC(y, 0, 1)), y: H - 6, class: "tick", "text-anchor": "middle"}, svg).textContent = y; } }
function hover(host, svg, W, H, m, T, X, rowsAt){
  const xh = el("line", {y1: m.t, y2: H - m.b, class: "xhair", visibility: "hidden"}, svg);
  const tip = document.createElement("div"); tip.className = "tip"; tip.hidden = true; host.appendChild(tip);
  const ov = el("rect", {x: m.l, y: m.t, width: W - m.l - m.r, height: H - m.t - m.b, fill: "transparent"}, svg);
  const mv = ev => { const r = svg.getBoundingClientRect(); const px = (ev.clientX - r.left) / r.width * W; const t = T[0] + (px - m.l) / (W - m.l - m.r) * (T[T.length-1] - T[0]);
    let lo = 0, hi = T.length - 1; while (lo < hi){ const mid = (lo + hi + 1) >> 1; if (T[mid] <= t) lo = mid; else hi = mid - 1; } const i = lo;
    const x = X(T[i]); xh.setAttribute("x1", x); xh.setAttribute("x2", x); xh.setAttribute("visibility", "visible");
    tip.innerHTML = rowsAt(i); tip.hidden = false; const bw = host.clientWidth; let left = x / W * bw + 12; if (left + tip.offsetWidth > bw) left = x / W * bw - tip.offsetWidth - 12; tip.style.left = Math.max(0, left) + "px"; tip.style.top = "6px"; };
  ov.addEventListener("pointermove", mv); ov.addEventListener("pointerdown", mv); ov.addEventListener("pointerleave", () => { tip.hidden = true; xh.setAttribute("visibility", "hidden"); });
}
function lineChart(host, dates, series, H){
  const [W] = frame(host, H), narrow = W < 560, m = {l: 44, r: narrow ? 12 : 190, t: 10, b: 22};
  const T = dates.map(d => Date.parse(d + "T00:00:00Z"));
  const svg = el("svg", {viewBox: `0 0 ${W} ${H}`, class: "chart", role: "img", "aria-label": "Equity curves, growth of 1, log scale"}, host);
  let lo = Infinity, hi = -Infinity; series.forEach(s => s.values.forEach(v => { if (v != null && v > 0){ lo = Math.min(lo, v); hi = Math.max(hi, v); } }));
  lo = Math.min(lo, 1) / 1.04; hi = Math.max(hi, 1) * 1.04;
  const X = t => m.l + (t - T[0]) / (T[T.length-1] - T[0]) * (W - m.l - m.r), Y = v => m.t + (Math.log(hi) - Math.log(v)) / (Math.log(hi) - Math.log(lo)) * (H - m.t - m.b);
  logTicks(lo, hi).forEach(v => { el("line", {x1: m.l, x2: W - m.r, y1: Y(v), y2: Y(v), class: v === 1 ? "base" : "grid"}, svg); el("text", {x: m.l - 6, y: Y(v) + 3.5, class: "tick", "text-anchor": "end"}, svg).textContent = v + "×"; });
  xAxis(svg, T, X, H, m);
  series.forEach(s => { let d = "", pen = false; s.values.forEach((v, i) => { if (v == null || v <= 0){ pen = false; return; } d += (pen ? "L" : "M") + X(T[i]).toFixed(1) + "," + Y(v).toFixed(1); pen = true; });
    el("path", {d, fill: "none", stroke: s.color, "stroke-width": s.width, "stroke-dasharray": s.dash, "stroke-linejoin": "round"}, svg); });
  if (!narrow){ const L = series.map(s => { let i = s.values.length - 1; while (i >= 0 && s.values[i] == null) i--; return i < 0 ? null : {s, y: Y(s.values[i]), v: s.values[i]}; }).filter(Boolean).sort((a, b) => a.y - b.y);
    for (let k = 1; k < L.length; k++) if (L[k].y - L[k-1].y < 13) L[k].y = L[k-1].y + 13;
    L.forEach(l => { el("rect", {x: W - m.r + 8, y: l.y - 4, width: 8, height: 8, rx: 2, fill: l.s.color}, svg); el("text", {x: W - m.r + 21, y: l.y + 3.5, class: "elabel"}, svg).textContent = `${l.s.label} ${l.v.toFixed(2)}×`; }); }
  hover(host, svg, W, H, m, T, X, i => `<div class="d">${dates[i]}</div>` + series.map(s => ({s, v: s.values[i]})).filter(r => r.v != null).sort((a, b) => b.v - a.v)
    .map(r => `<div class="r"><span><i class="sw" style="background:${r.s.color}"></i>${esc(r.s.label)}</span><b>${r.v.toFixed(3)}×</b></div>`).join(""));
}
function ddChart(host, dates, series, H){
  const [W] = frame(host, H), m = {l: 44, r: 12, t: 8, b: 22};
  const T = dates.map(d => Date.parse(d + "T00:00:00Z"));
  const svg = el("svg", {viewBox: `0 0 ${W} ${H}`, class: "chart", role: "img", "aria-label": "Drawdown from running peak"}, host);
  const dds = series.map(s => { let pk = -Infinity; return {s, v: s.values.map(v => { if (v == null) return null; pk = Math.max(pk, v); return v / pk - 1; })}; });
  let lo = 0; dds.forEach(d => d.v.forEach(v => { if (v != null) lo = Math.min(lo, v); })); lo = Math.floor(lo * 10) / 10 - 0.02;
  const X = t => m.l + (t - T[0]) / (T[T.length-1] - T[0]) * (W - m.l - m.r), Y = v => m.t + (0 - v) / (0 - lo) * (H - m.t - m.b);
  for (let v = 0; v >= lo; v -= 0.1){ el("line", {x1: m.l, x2: W - m.r, y1: Y(v), y2: Y(v), class: v === 0 ? "base" : "grid"}, svg); el("text", {x: m.l - 6, y: Y(v) + 3.5, class: "tick", "text-anchor": "end"}, svg).textContent = Math.round(v * 100) + "%"; }
  xAxis(svg, T, X, H, m);
  dds.forEach(d => { let p = "", pen = false; d.v.forEach((v, i) => { if (v == null){ pen = false; return; } p += (pen ? "L" : "M") + X(T[i]).toFixed(1) + "," + Y(v).toFixed(1); pen = true; });
    el("path", {d: p, fill: "none", stroke: d.s.color, "stroke-width": Math.max(1.4, d.s.width - 0.6), "stroke-dasharray": d.s.dash}, svg); });
  hover(host, svg, W, H, m, T, X, i => `<div class="d">${dates[i]}</div>` + dds.filter(d => d.v[i] != null).map(d => `<div class="r"><span><i class="sw" style="background:${d.s.color}"></i>${esc(d.s.label)}</span><b>${pct(d.v[i])}</b></div>`).join(""));
}
function stackChart(host, dates, layers, H, stepEnd){
  const [W] = frame(host, H), m = {l: 40, r: 10, t: 6, b: 22};
  if (!dates.length){ host.innerHTML = "<p class='note' style='margin:8px'>No live AA in this period: the AA books start in 2021-11.</p>"; return; }
  const T = dates.map(d => Date.parse(d + "T00:00:00Z")); const T1 = stepEnd ? Date.parse(stepEnd + "T00:00:00Z") : T[T.length-1];
  const svg = el("svg", {viewBox: `0 0 ${W} ${H}`, class: "chart", role: "img", "aria-label": "Allocation over time"}, host);
  const X = t => m.l + (t - T[0]) / (T1 - T[0]) * (W - m.l - m.r), Y = v => m.t + (1 - v) * (H - m.t - m.b);
  [0, 0.5, 1].forEach(v => { el("line", {x1: m.l, x2: W - m.r, y1: Y(v), y2: Y(v), class: v === 0 ? "base" : "grid"}, svg); el("text", {x: m.l - 6, y: Y(v) + 3.5, class: "tick", "text-anchor": "end"}, svg).textContent = v * 100 + "%"; });
  xAxis(svg, [T[0], T1], X, H, m);
  let base = dates.map(() => 0);
  layers.forEach(L => { const top = L.values.map((v, i) => v == null ? null : base[i] + Math.max(0, v));
    let d = ""; const n = dates.length;
    for (let i = 0; i < n; i++){ if (top[i] == null) continue; const x0 = X(T[i]), x1 = X(i + 1 < n ? T[i+1] : T1);
      d += `M${x0.toFixed(1)},${Y(base[i]).toFixed(1)}V${Y(top[i]).toFixed(1)}H${x1.toFixed(1)}V${Y(base[i]).toFixed(1)}Z`; }
    el("path", {d, fill: L.color, stroke: "none", opacity: 0.92}, svg);
    base = top.map((v, i) => v == null ? base[i] : v); });
  hover(host, svg, W, H, m, T, X, i => `<div class="d">${dates[i]}</div>` + layers.filter(L => L.values[i] != null).map(L => `<div class="r"><span><i class="sw" style="background:${L.color}"></i>${esc(L.label)}</span><b>${pct(L.values[i], 0)}</b></div>`).join(""));
}

const KIND = {"initial buy": ["first position", ""], "equity -> sleeve": ["equity → sleeve", "out"], "sleeve -> equity": ["sleeve → equity", "in"],
  "sleeve re-split": ["sleeve re-split (gold signal flipped)", ""], "parent rebalance": ["parent rebalanced", ""]};
const show = {};

function draw(){
  const R = D.data[`${per}|${book}`], par = D.parent[book];
  try { history.replaceState(null, "", "#" + book.slice(-4)); } catch (e) {}
  // KPIs
  const st = k => R.stats.find(s => s.key === k);
  const F = st("final"), Pp = st(per === "live" ? "parent_pub" : "parent_h"), A = st("aa_pub");
  const kp = [["Final rule CAGR", pct(F.cagr), `worst fall ${pct(F.dd)} (Friday closes ${pct(F.ddf)})`],
    [per === "live" ? "Parent, published" : "Parent (same engine)", pct(Pp.cagr), `worst fall ${pct(Pp.dd)}`],
    A ? ["Live AA, published", pct(A.cagr), `worst fall ${pct(A.dd)}`] : ["Three-index + 50/50", pct(st("t5050").cagr), `worst fall ${pct(st("t5050").dd)}`],
    ["Time in equity", pct(F.eqw, 0), `${F.sw} switches · ${F.rs} sleeve re-splits`]];
  $("#kpis").innerHTML = kp.map(k => `<div class="kpi"><div class="l">${k[0]}</div><div class="v">${k[1]}</div><div class="s">${k[2]}</div></div>`).join("");
  // stats table
  let h = `<thead><tr><th>Series</th><th>CAGR</th><th>Volatility</th><th>Worst fall<br>daily</th><th>Worst fall<br>Friday</th><th>Calmar</th><th>Sharpe<br>vs cash</th><th>Total return</th><th>Time in<br>equity</th><th>Switches</th><th>Final − this<br>(CAGR pp)</th></tr></thead><tbody>`;
  ORDER.forEach(k => { const s = st(k); if (!s) return; const d = F.cagr - s.cagr;
    h += `<tr${k === "final" ? ' class="hl"' : ""}><td class="l"><i class="sw" style="background:${SER[k][1]};margin-right:7px"></i>${esc(s.label)}</td><td>${pct(s.cagr)}</td><td>${pct(s.vol)}</td><td>${pct(s.dd)}</td><td>${pct(s.ddf)}</td><td>${s.calmar == null ? "–" : s.calmar.toFixed(2)}</td><td>${s.sharpe == null ? "–" : s.sharpe.toFixed(2)}</td><td>${pct(s.tr, 0)}</td><td>${s.eqw == null ? "–" : pct(s.eqw, 0)}</td><td>${s.sw == null ? "–" : s.sw}</td><td class="${k === "final" ? "" : cls(d)}">${k === "final" ? "" : pp(d)}</td></tr>`; });
  $("#stats").innerHTML = h + "</tbody>";
  $("#statsCap").innerHTML = `${book} holds parent ${par}. ${D.periods[per].label}. Every series is rebased to 1 on the period's first date. "Same engine" series are simulated on identical prices, fills and costs, so they compare like for like with the final rule. Published NAVs come from the smallcase index files and may differ in conventions (dividends, fills). Worst fall on daily closes, and on Friday closes.` + (per === "live" && book === "SCMO_0042" ? " SCMO_0042's weight file ends 2026-06-15, so its live-AA allocation strip stops there." : "");
  // toggles + curves
  const avail = ORDER.filter(k => R.series[k] && R.series[k].some(v => v != null));
  if (!show[per]) show[per] = new Set(ON[per]);
  $("#tgl").innerHTML = avail.map(k => `<button type="button" class="tg" data-k="${k}" aria-pressed="${show[per].has(k)}"><i style="background:${SER[k][1]}"></i>${SER[k][0]}</button>`).join("");
  $("#tgl").querySelectorAll("button").forEach(b => b.addEventListener("click", () => { const k = b.dataset.k; if (show[per].has(k)) { if (k !== "final") show[per].delete(k); } else show[per].add(k); curves(); b.setAttribute("aria-pressed", show[per].has(k)); }));
  const curves = () => { const ser = avail.filter(k => show[per].has(k)).map(k => ({label: SER[k][0], color: SER[k][1], width: SER[k][2], dash: SER[k][3], values: R.series[k]}));
    lineChart($("#chart"), R.dates, ser, 340); ddChart($("#dd"), R.dates, ser, 190); };
  curves();
  stackChart($("#alloc"), R.dates, ["equity", "gold", "cash"].map(k => ({label: LAYER[k][0], color: LAYER[k][1], values: R.alloc[k]})), 150);
  if (R.aa_alloc){ const a = R.aa_alloc; stackChart($("#aaAlloc"), a.dates, ["equity", "gold", "cash", "bond"].map(k => ({label: LAYER[k][0], color: LAYER[k][1], values: a[k]})), 150, a.last); }
  else stackChart($("#aaAlloc"), [], [], 150);
  $("#allocCap").innerHTML = `<span class="legend" style="display:inline-flex">${["equity", "gold", "cash", "bond"].map(k => `<span class="key"><i class="sw" style="background:${LAYER[k][1]}"></i>${LAYER[k][0]}</span>`).join("")}</span><br>Final rule: weights at each close, after drift. Live AA: the weights in its weekly weight file (gold and liquid ETFs, and a bond ETF until 2023), shown as steps.`;
  // yearly
  const yrs = [...new Set(R.yearly.flatMap(r => Object.keys(r.vals)))].sort();
  let y = `<thead><tr><th>Series</th>${yrs.map(v => `<th>${v}</th>`).join("")}</tr></thead><tbody>`;
  ORDER.forEach(k => { const r = R.yearly.find(z => z.key === k); if (!r) return; y += `<tr${k === "final" ? ' class="hl"' : ""}><td class="l">${esc(r.label)}</td>${yrs.map(v => `<td class="${cls(r.vals[v])}">${pct(r.vals[v])}</td>`).join("")}</tr>`; });
  $("#yr").innerHTML = y + `</tbody>`;
  // constituents heatmap
  const dates = R.trades.map(t => t.entry), rows = new Map();
  dates.forEach(d => (R.pos[d] || []).forEach(p => { if (!rows.has(p.k)) rows.set(p.k, {t: p.t, n: p.n, w: {}}); rows.get(p.k).w[d] = p.a; }));
  const keys = [...rows.keys()].filter(k => Object.values(rows.get(k).w).some(v => v > 0));
  const slv = ["GOLDBEES", "CASH"].filter(k => keys.includes(k)), stk = keys.filter(k => !slv.includes(k));
  const firstIdx = k => dates.findIndex(d => (rows.get(k).w[d] || 0) > 0);
  stk.sort((a, b) => firstIdx(a) - firstIdx(b) || (rows.get(b).w[dates[firstIdx(b)]] || 0) - (rows.get(a).w[dates[firstIdx(a)]] || 0));
  let hm = `<thead><tr><th class="nm">Holding</th>${R.trades.map(t => `<th title="${esc(KIND[t.kind] ? KIND[t.kind][0] : t.kind)}">${t.entry}</th>`).join("")}</tr></thead><tbody>`;
  [...slv, ...stk].forEach(k => { const r = rows.get(k);
    hm += `<tr${slv.includes(k) ? ' class="sl"' : ""}><td class="nm" title="${esc(r.n)} (${esc(k)})">${esc(r.t)}</td>` + dates.map(d => { const v = r.w[d] || 0;
      if (v <= 0) return `<td class="c"></td>`; const a = Math.min(100, Math.round(12 + 88 * Math.min(1, v / 0.25)));
      return `<td class="c" style="background:color-mix(in oklab, ${slv.includes(k) ? (k === "GOLDBEES" ? "var(--s4)" : "var(--s3)") : "var(--s1)"} ${a}%, transparent)" title="${esc(r.t)} · ${d}: ${pct(v)}">${Math.round(v * 100)}</td>`; }).join("") + `</tr>`; });
  $("#heat").innerHTML = hm + "</tbody>";
  // rebalance table
  let rb = `<thead><tr><th></th><th>Trade day</th><th>Signal (Friday)</th><th style="text-align:left">What happened</th><th>Equity</th><th>Gold</th><th>Cash</th><th>Holdings</th><th>Traded<br>(% of book)</th><th>Cost<br>(% of book)</th><th>NAV at close</th></tr></thead><tbody>`;
  R.trades.forEach((t, i) => { const kd = KIND[t.kind] || [t.kind, ""];
    rb += `<tr><td><button type="button" data-i="${i}" aria-expanded="false">Show</button></td><td>${t.entry}</td><td>${t.review}</td><td style="text-align:left"><span class="kind ${kd[1]}">${kd[0]}</span></td><td>${pct(t.eq, 0)}</td><td>${pct(t.gold, 0)}</td><td>${pct(t.cash, 0)}</td><td>${t.n}</td><td>${pct(t.turn, 0)}</td><td>${pct(t.cost, 3)}</td><td>${t.nav.toFixed(4)}</td></tr>
      <tr class="detail" id="d${i}" hidden><td colspan="11"><div class="tw" style="margin:0"><table><thead><tr><th>Holding</th><th>Name</th><th>Weight before</th><th>Weight after</th><th>Change</th><th>Fill price (Monday OHLC4)</th></tr></thead><tbody>${(R.pos[t.entry] || []).map(p => `<tr><td class="l">${esc(p.t)}</td><td class="l">${esc(p.n)}</td><td>${pct(p.b)}</td><td>${pct(p.a)}</td><td class="${cls(p.a - p.b)}">${pp(p.a - p.b)}</td><td>${p.p == null ? "–" : p.p.toFixed(2)}</td></tr>`).join("")}</tbody></table></div></td></tr>`; });
  $("#rb").innerHTML = rb + "</tbody>";
  $("#rb").querySelectorAll("button").forEach(b => b.addEventListener("click", () => { const d = document.getElementById("d" + b.dataset.i); d.hidden = !d.hidden; b.textContent = d.hidden ? "Show" : "Hide"; b.setAttribute("aria-expanded", !d.hidden); }));
}

(function nowPanel(){
  const L = D.latest; if (!L) return;
  const num = x => x == null ? "–" : Math.round(x).toLocaleString("en-IN");
  const flip = x => `<span class="flip">to flip ${x.gap >= 0 ? "+" : "−"}${Math.abs(x.gap*100).toFixed(1)}%</span>`;
  const chip = x => `<span class="sig ${x.s === "BUY" ? "buy" : "sell"}">${x.s}</span>${flip(x)}`;
  const last = L.rows[L.rows.length - 1], S = last.sig;
  const sells = ["N100", "MC100", "SC100"].filter(k => S[k].s === "SELL").map(k => L.labels[k]);
  const buys = ["N100", "MC100", "SC100"].filter(k => S[k].s === "BUY").map(k => L.labels[k]);
  const idx = sells.length ? `${sells.join(" and ")} ${sells.length > 1 ? "are" : "is"} SELL${buys.length ? `, ${buys.join(" and ")} ${buys.length > 1 ? "are" : "is"} BUY` : ""}, so every book is in the sleeve` : "all three indices are BUY, so every book holds its parent basket";
  const gold = sells.length ? `; MAUc1 is ${S.MAUc1.s}, so the sleeve is ${last.holds}` : "";
  $("#nowLead").innerHTML = `<b>Review ${esc(last.review)}:</b> ${idx}${gold}. The rule has held <b>${esc(last.holds)}</b> since the trade on ${esc(L.since_trade)}, after the ${esc(L.since_review)} review.`;
  let h = `<thead><tr><th class="l">Review</th><th class="l">Trade session</th>${L.order.map(k => `<th>${esc(L.labels[k])}</th>`).join("")}<th class="l">Final rule holds</th></tr></thead><tbody>`;
  L.rows.forEach(r => { h += `<tr class="${r.after ? "after" : ""}"><td class="l">${esc(r.review)}</td><td class="l">${esc(r.trade || "next session")}</td>${L.order.map(k => `<td>${chip(r.sig[k])}</td>`).join("")}<td class="l">${esc(r.holds)}</td></tr>`; });
  $("#nowT").innerHTML = h + "</tbody>";
  const lines = L.order.map(k => `${L.labels[k]} ${num(S[k].c)} against a line at ${num(S[k].st)}`).join("; ");
  $("#nowCap").innerHTML = `Each cell is that week's ST.py SIGN, from the Friday job's Master files for the three indices (read ${esc(L.read_on)}, read-only) and <code>Master_MAUc1.xlsx</code> for gold. "To flip" is the supertrend line against the week's close: the move a close would need to cross it. The line itself moves each week. Latest closes: ${lines}. The trade session is the next NSE session after the review. The backtest above ends ${esc(L.backtest_end)}, where its stock and cash prices end; rows marked "after backtest" are signals only, not simulated returns.`;
})();

seg($("#bk"), D.books, D.books.map(b => `${b.slice(-4)} · parent ${D.parent[b].slice(-4)}`), () => book, v => { book = v; draw(); });
seg($("#pr"), ["live", "oos"], ["Live 2021–26", "2014–21 (parents, before the books)"], () => per, v => { per = v; draw(); });
draw();
let rt; window.addEventListener("resize", () => { clearTimeout(rt); rt = setTimeout(draw, 150); });
const V = D.verification || [];
$("#foot").innerHTML = `<p><b>How this was computed.</b> The v2 backtest engine holds units of every stock, GOLDBEES and cash. A Friday decision trades on the next session at (open+high+low+close)/4, falling back to the close when a price leg is missing. Nothing trades while the target is unchanged. Each trade costs 10.4 bps of the value traded (20.8 bps round trip). Stock prices come from Eikon, keyed by ISIN through quote_id. The index signals are the production Master files' SIGN column, computed on weekly candles and reproduced exactly from index prices. Gold's signal is the same production ST.py, run unmodified on MAUc1 (MCX gold futures, continuous; the user's Eikon export) into a folder laid out like the desk's (<code>AA/Historical Data/FRA_MAUc1/RSI/Final/MAUc1/W_allRebal.xlsx</code>, <code>…/Analysis/Master_MAUc1.xlsx</code>), and read from its Master file like the indices. That harness reproduces production's three index files cell for cell. ST.py's signal matches the earlier review-cut MAUc1 candles in all 603 weeks, so no result changed. The book still buys GOLDBEES, at its de-spiked Monday OHLC4. "Final rule, GOLDBEES gold signal (previous)" is the earlier version, with gold's trend read from GOLDBEES itself.</p>
<p><b>Cross-check.</b> The Excel workbook recomputes the gold supertrend, every weekly decision and every book's daily NAV with live formulas. ${V.length ? `Checked with an independent Excel formula engine (pycel): ${V.length} checks over ${V.reduce((a, v) => a + v.rows, 0).toLocaleString()} rows (the gold supertrend week by week, every weekly decision, and each book's daily NAV against a Python replica), with ${V.reduce((a, v) => a + v.mismatches, 0)} mismatches.` : ""} The formula model differs from the engine only inside equity spells: it follows the parent's own drifted NAV, while the engine re-buys the parent's current published weights at each re-entry.</p>
<p><b>Caveats.</b> The three-index rule and the gold-timed split were both chosen after looking at 2014–2026 data, so neither period is a clean out-of-sample test. The stock prices are price return. MAUc1 history starts in 2015-02, so the two sleeve spells of 2014-15 hold 50/50. The live-window daily worst fall of the final rule is gold's Jan–Mar 2026 spike with 80% of the book in gold; on Friday closes it is much smaller.</p>
<p><b>Files.</b> <code>AA/analysis/final_strategy.py</code>, <code>final_strategy_excel.py</code>, <code>final_strategy_verify.py</code>, <code>final_book_report.py</code>; evidence and CSVs in <code>AA/analysis/evidence/final_strategy/</code>; methods in its <code>METHODS.md</code>.</p>`;
})();
</script>
"""


if __name__ == "__main__":
    main()
