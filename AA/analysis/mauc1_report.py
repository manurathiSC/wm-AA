# -*- coding: utf-8 -*-
"""
Build evidence/final_strategy/mauc1/report.html: MAUc1 (MCX gold futures)
growth of 1 on daily closes, shaded where its weekly supertrend is SELL as of
each weekly rebalance, against the GOLDBEES signal used so far.
Inputs: mauc1_signal.py outputs.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from common import CACHE_DIR, EVIDENCE_DIR

E = EVIDENCE_DIR / "final_strategy"
M = E / "mauc1"
TPL = EVIDENCE_DIR.parent / "why_report_template.html"


def in_force(dates: pd.DatetimeIndex, R: pd.DataFrame, col: str) -> list:
    """Signal in force on each session: from a review's trade session until the next one."""
    s = pd.Series(R[col].values, index=pd.to_datetime(R.trade_session))
    s = s[~s.index.duplicated(keep="last")]
    out = s.reindex(dates.union(s.index)).ffill().reindex(dates)
    out[dates < s.index[0]] = np.nan
    return [None if pd.isna(v) else int(v) for v in out]


def main():
    d = pd.read_csv(M / "mauc1_daily_clean.csv", index_col=0, parse_dates=True)
    R = pd.read_csv(M / "mauc1_signal_on_reviews.csv", parse_dates=["review", "trade_session"])
    S = pd.read_csv(M / "mauc1_summary.csv", index_col=0)["value"]
    dis = pd.read_csv(M / "mauc1_vs_goldbees_disagreements.csv", parse_dates=["first_review", "last_review"])
    gb = pd.read_parquet(CACHE_DIR / "why_gold_ohlc_eikon.parquet").set_index("date")["close"].sort_index()
    gb = gb[~gb.index.duplicated(keep="last")]
    dates = d.index
    lvl = d.close / d.close.iloc[0]
    # what gold did while the two signals disagreed: trade session of the first review -> trade session that ends the stretch
    rows = []
    for x in dis.itertuples():
        a = R.loc[R.review == x.first_review, "trade_session"].iloc[0]
        nxt = R[R.review > x.last_review].head(1)
        b = nxt.trade_session.iloc[0] if len(nxt) else dates[-1]
        m_ret = d.close.asof(b) / d.close.asof(a) - 1
        g_ret = gb.asof(b) / gb.asof(a) - 1
        right = "MAUc1" if ((x.mauc1 == 0 and g_ret < 0) or (x.mauc1 == 1 and g_ret > 0)) else "GOLDBEES"
        rows.append({"from": a.date(), "to": b.date(), "weeks": int(x.weeks), "mauc1": "BUY" if x.mauc1 == 1 else "SELL",
                     "goldbees": "BUY" if x.goldbees == 1 else "SELL", "mauc1_ret": m_ret, "goldbees_ret": g_ret, "right": right})
    D = pd.DataFrame(rows)
    D.to_csv(M / "mauc1_disagreement_outcomes.csv", index=False)
    payload = {"dates": [str(t.date()) for t in dates], "level": [round(float(v), 5) for v in lvl],
               "close": [float(v) for v in d.close], "sig_m": in_force(dates, R, "mauc1_signal"), "sig_g": in_force(dates, R, "goldbees_signal"),
               "summary": {k: (float(v) if str(v).replace(".", "", 1).isdigit() else v) for k, v in S.items()},
               "dis": [{k: (str(v) if not isinstance(v, (float, int, np.floating, np.integer)) else float(v)) for k, v in r.items()} for r in rows],
               "reviews": [{"r": str(r.review.date()), "t": str(r.trade_session.date()), "m": None if pd.isna(r.mauc1_signal) else int(r.mauc1_signal),
                            "g": None if pd.isna(r.goldbees_signal) else int(r.goldbees_signal)} for r in R.itertuples()]}
    css = TPL.read_text(encoding="utf-8").split("</style>")[0].split("<style>")[1]
    html = PAGE.replace("/*__CSS__*/", css).replace("__DATA__", json.dumps(payload, separators=(",", ":")))
    (M / "report.html").write_text(html, encoding="utf-8")
    print("wrote", M / "report.html", round(len(html) / 1024), "KB")
    print(D.round(4).to_string(index=False))
    print("right:", D.right.value_counts().to_dict(), "weeks:", D.groupby("right").weeks.sum().to_dict())


PAGE = r"""<title>MAUc1 Gold Trend</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600&family=Newsreader:opsz,wght@6..72,400;6..72,500;6..72,600&display=swap">
<style>
/*__CSS__*/
.kpis{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin:16px 0}
.kpi{background:var(--surface-1);border:1px solid var(--border);border-radius:10px;padding:12px 14px}
.kpi .l{font-family:var(--mono);font-size:10.5px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted)}
.kpi .v{font-family:var(--serif);font-size:26px;line-height:1.15;margin-top:4px}
.kpi .s{font-size:12.5px;color:var(--text-secondary);margin-top:2px}
@media (max-width:720px){.kpis{grid-template-columns:repeat(2,minmax(0,1fr))}}
</style>
<div class="wrap">
  <p class="eyebrow">AA final rule · the gold signal · MAUc1 (MCX gold futures, continuous) · weekly supertrend</p>
  <h1>Gold's trend on MAUc1, as of each weekly rebalance</h1>
  <p class="sub">MCX gold futures, growth of 1 on daily closes. Shaded weeks are where MAUc1's weekly supertrend says SELL, so the final rule's sleeve would hold 20% gold / 80% cash. The strip below compares it with the GOLDBEES-based signal used in the backtest so far.</p>
  <p class="meta">Source: MAUc1_daily1.csv (Eikon export, 2015-02-02 → 2026-09-28) · signal from the desk's production ST.py, run unmodified on MAUc1 the way the Friday job runs it for the indices (weekly candles on the NSE calendar, multiplier 2, 5-week linearly weighted ATR; <code>Master_MAUc1.xlsx</code>) · each Friday review reads the latest completed candle; shading starts on the review's trade session (Monday)</p>
  <div class="kpis" id="kpis"></div>
  <div class="card"><div class="legend"><span class="key"><i class="sw" style="background:var(--s4)"></i>MAUc1, growth of 1 (daily closes)</span><span class="key"><i class="sw" style="background:var(--band);box-shadow:inset 0 0 0 1px var(--baseline)"></i>weeks MAUc1's trend is SELL (sleeve 20% gold / 80% cash)</span></div><div id="chart"></div></div>
  <div class="panel-title">Signal in force at each weekly rebalance</div>
  <div class="card"><div class="legend"><span class="key"><i class="sw" style="background:var(--s1)"></i>SELL</span><span class="key"><i class="sw" style="background:var(--s8)"></i>the two signals disagree</span></div><div id="strip"></div></div>
  <h2>Where the two gold signals disagree</h2>
  <p>Each row is a run of weekly reviews where MAUc1 and GOLDBEES gave different signals, from the first trade session to the session where they agree again. "Right" is the signal whose call matched what GOLDBEES, the gold actually held, did over that stretch.</p>
  <div class="tw"><table id="dis"></table></div>
  <div class="foot" id="foot"></div>
</div>
<script id="data" type="application/json">__DATA__</script>
<script>
(function(){
"use strict";
const D = JSON.parse(document.getElementById("data").textContent);
const $ = s => document.querySelector(s);
const NS = "http://www.w3.org/2000/svg";
const el = (t, a, p) => { const e = document.createElementNS(NS, t); for (const k in a) e.setAttribute(k, a[k]); if (p) p.appendChild(e); return e; };
const pct = (x, d=1) => x == null ? "–" : (x*100).toFixed(d).replace("-", "−") + "%";
const T = D.dates.map(d => Date.parse(d + "T00:00:00Z")), n = T.length;
const S = D.summary;
$("#kpis").innerHTML = [["Reviews compared", S["reviews compared"], `from ${S["first signal week"]}`],
  ["Time in BUY", pct(S["share of reviews BUY (MAUc1)"], 0), `GOLDBEES signal ${pct(S["share of reviews BUY (GOLDBEES)"], 0)}`],
  ["Signal flips", S["flips (MAUc1)"], `GOLDBEES signal ${S["flips (GOLDBEES)"]}`],
  ["Agreement with GOLDBEES", pct(S["agreement share"], 0), `${S["reviews where they agree"]} of ${S["reviews compared"]} reviews · ${S["disagreement stretches"]} stretches apart`]]
  .map(k => `<div class="kpi"><div class="l">${k[0]}</div><div class="v">${k[1]}</div><div class="s">${k[2]}</div></div>`).join("");

function runs(sig, val){ const out = []; let i0 = null; for (let i = 0; i < n; i++){ const on = sig[i] === val; if (on && i0 == null) i0 = i; if ((!on || i === n - 1) && i0 != null){ out.push([i0, on ? i : i]); i0 = null; } } return out; }
function chart(){
  const host = $("#chart"); host.innerHTML = ""; host.classList.add("chartbox");
  const W = Math.max(300, host.clientWidth || 900), H = 300, m = {l: 44, r: 12, t: 10, b: 22};
  const svg = el("svg", {viewBox: `0 0 ${W} ${H}`, class: "chart", role: "img", "aria-label": "MAUc1 growth of 1 with SELL weeks shaded"}, host);
  const v = D.level, lo = Math.min(...v) / 1.04, hi = Math.max(...v) * 1.04;
  const X = t => m.l + (t - T[0]) / (T[n-1] - T[0]) * (W - m.l - m.r), Y = x => m.t + (Math.log(hi) - Math.log(x)) / (Math.log(hi) - Math.log(lo)) * (H - m.t - m.b);
  runs(D.sig_m, 0).forEach(([a, b]) => el("rect", {x: X(T[a]), y: m.t, width: Math.max(1, X(T[b]) - X(T[a])), height: H - m.t - m.b, fill: "var(--band)"}, svg));
  [1, 1.5, 2, 3, 4, 5, 6].filter(t => t >= lo && t <= hi).forEach(t => { el("line", {x1: m.l, x2: W - m.r, y1: Y(t), y2: Y(t), class: t === 1 ? "base" : "grid"}, svg); el("text", {x: m.l - 6, y: Y(t) + 3.5, class: "tick", "text-anchor": "end"}, svg).textContent = t + "×"; });
  for (let y = new Date(T[0]).getUTCFullYear() + 1; y <= new Date(T[n-1]).getUTCFullYear(); y += 2) el("text", {x: X(Date.UTC(y, 0, 1)), y: H - 6, class: "tick", "text-anchor": "middle"}, svg).textContent = y;
  let p = ""; v.forEach((x, i) => { p += (i ? "L" : "M") + X(T[i]).toFixed(1) + "," + Y(x).toFixed(1); });
  el("path", {d: p, fill: "none", stroke: "var(--s4)", "stroke-width": 2}, svg);
  const xh = el("line", {y1: m.t, y2: H - m.b, class: "xhair", visibility: "hidden"}, svg);
  const tip = document.createElement("div"); tip.className = "tip"; tip.hidden = true; host.appendChild(tip);
  const ov = el("rect", {x: m.l, y: m.t, width: W - m.l - m.r, height: H - m.t - m.b, fill: "transparent"}, svg);
  const lab = s => s == null ? "–" : s === 1 ? "BUY" : "SELL";
  const mv = ev => { const r = svg.getBoundingClientRect(); const px = (ev.clientX - r.left) / r.width * W; const t = T[0] + (px - m.l) / (W - m.l - m.r) * (T[n-1] - T[0]);
    let a = 0, b = n - 1; while (a < b){ const md = (a + b + 1) >> 1; if (T[md] <= t) a = md; else b = md - 1; } const i = a, x = X(T[i]);
    xh.setAttribute("x1", x); xh.setAttribute("x2", x); xh.setAttribute("visibility", "visible");
    tip.innerHTML = `<div class="d">${D.dates[i]}</div><div class="r"><span>MAUc1 close</span><b>₹${D.close[i].toLocaleString("en-IN")}</b></div><div class="r"><span>growth of 1</span><b>${D.level[i].toFixed(2)}×</b></div><div class="r"><span>MAUc1 signal in force</span><b>${lab(D.sig_m[i])}</b></div><div class="r"><span>GOLDBEES signal in force</span><b>${lab(D.sig_g[i])}</b></div>`;
    tip.hidden = false; const bw = host.clientWidth; let left = x / W * bw + 12; if (left + tip.offsetWidth > bw) left = x / W * bw - tip.offsetWidth - 12; tip.style.left = Math.max(0, left) + "px"; tip.style.top = "6px"; };
  ov.addEventListener("pointermove", mv); ov.addEventListener("pointerdown", mv); ov.addEventListener("pointerleave", () => { tip.hidden = true; xh.setAttribute("visibility", "hidden"); });
}
function strip(){
  const host = $("#strip"); host.innerHTML = ""; host.classList.add("chartbox");
  const W = Math.max(300, host.clientWidth || 900), H = 118, m = {l: 96, r: 12, t: 6, b: 22}, rh = 20;
  const svg = el("svg", {viewBox: `0 0 ${W} ${H}`, class: "chart", role: "img", "aria-label": "SELL periods for MAUc1 and GOLDBEES signals"}, host);
  const X = t => m.l + (t - T[0]) / (T[n-1] - T[0]) * (W - m.l - m.r);
  const rows = [["MAUc1", D.sig_m, 0], ["GOLDBEES", D.sig_g, 1]];
  rows.forEach(([name, sig, k]) => { const y = m.t + k * (rh + 10);
    el("rect", {x: m.l, y, width: W - m.l - m.r, height: rh, fill: "var(--band)"}, svg);
    runs(sig, 0).forEach(([a, b]) => el("rect", {x: X(T[a]), y, width: Math.max(1, X(T[b]) - X(T[a])), height: rh, fill: "var(--s1)"}, svg));
    el("text", {x: m.l - 8, y: y + rh / 2 + 4, class: "elabel", "text-anchor": "end"}, svg).textContent = name + " SELL"; });
  const y = m.t + 2 * (rh + 10);
  const dsig = D.sig_m.map((v, i) => v == null || D.sig_g[i] == null ? null : (v !== D.sig_g[i] ? 1 : 0));
  runs(dsig, 1).forEach(([a, b]) => el("rect", {x: X(T[a]), y, width: Math.max(1, X(T[b]) - X(T[a])), height: rh - 6, fill: "var(--s8)"}, svg));
  el("text", {x: m.l - 8, y: y + rh / 2 + 1, class: "elabel", "text-anchor": "end"}, svg).textContent = "disagree";
  for (let yr = new Date(T[0]).getUTCFullYear() + 1; yr <= new Date(T[n-1]).getUTCFullYear(); yr += 2) el("text", {x: X(Date.UTC(yr, 0, 1)), y: H - 6, class: "tick", "text-anchor": "middle"}, svg).textContent = yr;
}
chart(); strip();
let rt; window.addEventListener("resize", () => { clearTimeout(rt); rt = setTimeout(() => { chart(); strip(); }, 150); });
let h = `<thead><tr><th>From (trade session)</th><th>To</th><th>Weeks</th><th>MAUc1 said</th><th>GOLDBEES said</th><th>MAUc1 return</th><th>GOLDBEES return</th><th>Right</th></tr></thead><tbody>`;
D.dis.forEach(r => { h += `<tr><td>${r.from}</td><td>${r.to}</td><td>${r.weeks}</td><td>${r.mauc1}</td><td>${r.goldbees}</td><td class="${r.mauc1_ret > 0 ? "pos" : "neg"}">${pct(r.mauc1_ret)}</td><td class="${r.goldbees_ret > 0 ? "pos" : "neg"}">${pct(r.goldbees_ret)}</td><td><b>${r.right}</b></td></tr>`; });
$("#dis").innerHTML = h + "</tbody>";
const right = D.dis.reduce((a, r) => { a[r.right] = (a[r.right] || 0) + r.weeks; return a; }, {});
$("#foot").innerHTML = `<p><b>Reading the table.</b> Across the ${D.dis.length} disagreement stretches, MAUc1's call was right for ${right.MAUc1 || 0} weeks and GOLDBEES's for ${right.GOLDBEES || 0} weeks, judged by GOLDBEES's own return over each stretch.</p>
<p><b>Data.</b> Seven rows of the export were cleaned (see <code>mauc1_cleaning_log.csv</code>): three stale holiday rows with no close were dropped; three close-only rows kept the close as open, high and low; one bar whose close sat above its high was widened. The signal is production ST.py's, run on this data by <code>mauc1_st_production.py</code> into a folder laid out like the desk's (<code>AA/Historical Data/FRA_MAUc1/RSI/Final/MAUc1/W_allRebal.xlsx</code>, <code>…/Analysis/Master_MAUc1.xlsx</code>). The harness reproduces production's Nifty 100, Midcap 100 and Smallcap 100 files cell for cell. ST.py puts MAUc1 on the NSE trading calendar, so 118 MCX sessions on NSE holidays are not in its candles; the earlier review-cut candles kept them, and both give the same signal in all 603 weeks (<code>st_production/</code>). The weekly candles and every supertrend step are in <code>mauc1_supertrend_weekly.csv</code>; the signal read at each review, with its trade session, is in <code>mauc1_signal_on_reviews.csv</code>. Files are in <code>AA/analysis/evidence/final_strategy/mauc1/</code>; code is <code>mauc1_signal.py</code> and <code>mauc1_report.py</code>.</p>
<p><b>Why they can differ.</b> MCX gold trades until late evening, so its daily and weekly candles include the overseas session, while GOLDBEES trades only in Indian market hours and can drift from its NAV. Different candles give different true ranges, bands and flip weeks, even though both follow the same metal.</p>`;
})();
</script>
"""


if __name__ == "__main__":
    main()
