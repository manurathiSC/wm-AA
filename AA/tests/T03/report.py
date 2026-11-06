"""Build evidence/<run>/report.html for T03 from shipped evidence only (AGENT.md R10).

    python report.py [--run headline]

Every number on the page is computed here from evidence/<run>/*.csv and audit.json; the same numbers are written into the page's
embedded JSON block (id="page-data") so check_page.py can recompute them independently. Imports nothing from the engine.
"""
from __future__ import annotations

import argparse
import html
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
BOOKS = ["SCMO_0003", "SCMO_0007", "SCMO_0010", "SCMO_0029"]
PRIMARY = 20.8
E = html.escape
COL = {"strategy": "#2a6fdb", "hold_parent": "#8a8f98", "constant_mix": "#c9811a", "sleeve_only": "#2f9e6e", "published_D17": "#b04a9b"}
LAB = {"strategy": "Three-index rule", "hold_parent": "Hold the parent", "constant_mix": "Constant mix (same average exposure)",
       "sleeve_only": "50/50 GOLDBEES + cash", "published_D17": "Published NAV (D17)"}


def rank(x, draws, hb=True):
    tie = np.isclose(draws, x, rtol=1e-12, atol=0)
    worse = ((draws < x) if hb else (draws > x)) & ~tie
    better = ((draws > x) if hb else (draws < x)) & ~tie
    n = len(draws)
    return {"percentile": float((worse.sum() + 0.5 * tie.sum()) / n * 100), "p": float((1 + better.sum() + tie.sum()) / (n + 1)),
            "worse": int(worse.sum()), "tied": int(tie.sum()), "better": int(better.sum()), "draws": int(n)}


def nav_stats(nav):
    T = len(nav)
    yrs = (T - 1) / 252
    dd = nav / np.maximum.accumulate(nav) - 1
    return {"cagr": float(nav[-1] ** (1 / yrs) - 1), "max_dd": float(dd.min())}


def f2(x):
    return f"{x:.2f}"


def pc(x, d=1):
    return f"{100 * x:.{d}f}%"


def svg_lines(series, dates, w=640, h=250, log=True, ylab=""):
    """series: {name: array}; downsampled to every 5th session."""
    step = 5
    idx = np.arange(0, len(dates), step)
    if idx[-1] != len(dates) - 1:
        idx = np.append(idx, len(dates) - 1)
    allv = np.concatenate([v[idx] for v in series.values()])
    ymin, ymax = (math.log(allv.min() * 0.97), math.log(allv.max() * 1.03)) if log else (allv.min(), allv.max())
    L, R, T, B = 44, 8, 8, 24
    x = lambda i: L + (w - L - R) * i / (len(idx) - 1)
    y = lambda v: T + (h - T - B) * (1 - ((math.log(v) if log else v) - ymin) / (ymax - ymin))
    out = [f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="{E(ylab)}" class="chart lc" data-book="{E(ylab)}">']
    ticks = [0.5, 1, 2, 4, 8, 16, 32] if log else []
    for t in ticks:
        if allv.min() * 0.97 <= t <= allv.max() * 1.03:
            out.append(f'<line x1="{L}" x2="{w - R}" y1="{y(t):.1f}" y2="{y(t):.1f}" class="grid"/><text x="{L - 4}" y="{y(t) + 3:.1f}" text-anchor="end" class="ax">{t:g}×</text>')
    years = sorted({d.year for d in dates})
    for yr in years[::2]:
        i = int(np.argmax([d.year == yr for d in dates]))
        j = int(np.argmin(np.abs(idx - i)))
        out.append(f'<text x="{x(j):.1f}" y="{h - 6}" text-anchor="middle" class="ax">{yr}</text>')
    for k, v in series.items():
        pts = " ".join(f"{x(j):.1f},{y(v[i]):.1f}" for j, i in enumerate(idx))
        wd = 2.2 if k == "strategy" else 1.3
        out.append(f'<polyline points="{pts}" fill="none" stroke="{COL[k]}" stroke-width="{wd}" stroke-linejoin="round"/>')
    # hover layer, driven by LINES_JS: crosshair, a dot on each line, a y-axis level chip, an x-axis date chip, and a transparent overlay that takes the pointer
    bot = h - B
    out.append('<g class="lc-hv" style="display:none" pointer-events="none">'
               f'<line class="lc-v" y1="{T}" y2="{bot}" stroke="var(--muted)" stroke-width="1"/>'
               f'<line class="lc-h" x1="{L}" x2="{w - R}" stroke="var(--muted)" stroke-width="1" stroke-dasharray="3 3"/>'
               + "".join(f'<circle class="lc-c" r="3.5" fill="{COL[k]}" stroke="var(--card)" stroke-width="1.5"/>' for k in series)
               + f'<g class="lc-yc"><rect x="0" y="-8" width="{L - 3}" height="16" rx="3" fill="var(--fg)"/><text x="{L - 7}" y="3.5" text-anchor="end" font-size="10" fill="var(--bg)" class="lc-yt"></text></g>'
               f'<g class="lc-xc"><rect y="{h - 19}" width="92" height="16" rx="3" fill="var(--fg)" class="lc-xr"/><text y="{h - 7.5}" text-anchor="middle" font-size="10" fill="var(--bg)" class="lc-xt"></text></g></g>')
    out.append(f'<rect class="lc-ov" x="{L}" y="{T}" width="{w - L - R}" height="{bot - T}" fill="transparent" style="cursor:crosshair"/>')
    out.append("</svg>")
    # what the hover reads: the same plotted sessions and values that draw the lines above
    data = {"w": w, "h": h, "L": L, "R": R, "T": T, "B": B, "lo": ymin, "hi": ymax, "log": log, "n": len(idx),
            "dates": [dates[i].strftime("%Y-%m-%d (%a)") for i in idx],
            "series": [{"k": k, "label": LAB[k], "col": COL[k], "v": [round(float(v[i]), 4) for i in idx]} for k, v in series.items()]}
    return "".join(out), data


def svg_hist(draws, mark, w=300, h=120, bins=32, xfmt=lambda v: f"{100 * v:.0f}%", better_high=True):
    lo, hi = min(draws.min(), mark), max(draws.max(), mark)
    pad = (hi - lo) * 0.04
    lo, hi = lo - pad, hi + pad
    cnt, edges = np.histogram(draws, bins=bins, range=(lo, hi))
    L, R, T, B = 6, 6, 6, 20
    x = lambda v: L + (w - L - R) * (v - lo) / (hi - lo)
    ym = cnt.max()
    out = [f'<svg viewBox="0 0 {w} {h}" class="chart small" role="img" aria-label="null distribution">']
    for c, a, b in zip(cnt, edges[:-1], edges[1:]):
        hh = (h - T - B) * c / ym
        out.append(f'<rect x="{x(a) + 0.5:.1f}" y="{h - B - hh:.1f}" width="{max(x(b) - x(a) - 1, 0.5):.1f}" height="{hh:.1f}" class="bar"/>')
    out.append(f'<line x1="{x(mark):.1f}" x2="{x(mark):.1f}" y1="{T}" y2="{h - B}" stroke="{COL["strategy"]}" stroke-width="2.4"/>')
    med = float(np.median(draws))
    out.append(f'<line x1="{x(med):.1f}" x2="{x(med):.1f}" y1="{T}" y2="{h - B}" stroke="var(--muted)" stroke-width="1" stroke-dasharray="3 3"/>')
    out.append(f'<text x="{L}" y="{h - 6}" class="ax">{xfmt(lo + pad)}</text><text x="{w - R}" y="{h - 6}" text-anchor="end" class="ax">{xfmt(hi - pad)}</text>')
    out.append("</svg>")
    return "".join(out)


def svg_regime(dates, ser, rule_runs, draw_runs, pair_runs, draw_label, w=760):
    """Growth-of-1 lines (log) on top; below, one strip per timing (filled = holds the parent) and a strip of where they differ.
    ser: {key: full-resolution array}; *_runs: lists of (value, first_session, last_session); pair_runs also carries a tooltip."""
    N = len(dates)
    L, R, T, ph = 56, 62, 8, 210
    rowh, gap = 12, 5
    top = T + ph + 22
    h = top + 3 * (rowh + gap) + 20
    allv = np.concatenate(list(ser.values()))
    lo, hi = math.log(allv.min() * 0.97), math.log(allv.max() * 1.03)
    x = lambda i: L + (w - L - R) * i / (N - 1)
    y = lambda v: T + ph * (1 - (math.log(v) - lo) / (hi - lo))
    out = [f'<svg id="regime-svg" viewBox="0 0 {w} {h}" role="img" aria-label="Growth of 1: three-index rule versus random timing {E(draw_label)}, with the weeks each held the parent" class="chart">']
    for v, s, e, tip in pair_runs:
        if v in (1, 2):
            fill = "var(--fg)" if v == 1 else COL["strategy"]
            out.append(f'<rect x="{x(s):.1f}" y="{T}" width="{max(x(e) - x(s), 0.6):.1f}" height="{top + 3 * (rowh + gap) - gap - T}" fill="{fill}" opacity="{0.10 if v == 1 else 0.14}"/>')
    for t in (1, 2, 4, 8, 16):
        if math.exp(lo) <= t <= math.exp(hi):
            out.append(f'<line x1="{L}" x2="{w - R}" y1="{y(t):.1f}" y2="{y(t):.1f}" class="grid"/><text x="{L - 4}" y="{y(t) + 3:.1f}" text-anchor="end" class="ax">{t:g}×</text>')
    idx = np.append(np.arange(0, N, 3), N - 1)
    styles = {"hold_parent": (COL["hold_parent"], 1.2), "draw": ("var(--fg)", 1.7), "strategy": (COL["strategy"], 2.4)}
    for k in ("hold_parent", "draw", "strategy"):
        v = ser[k]
        out.append(f'<polyline points="{" ".join(f"{x(i):.1f},{y(v[i]):.1f}" for i in idx)}" fill="none" stroke="{styles[k][0]}" stroke-width="{styles[k][1]}" stroke-linejoin="round"/>')
        out.append(f'<text x="{x(N - 1) + 5:.1f}" y="{y(v[-1]) + 3:.1f}" class="ax" style="fill:var(--fg)">{v[-1]:.1f}×</text>')
    rows = [("Rule", rule_runs, COL["strategy"]), (draw_label, draw_runs, "var(--fg)")]
    for r_, (lab, runs, fill) in enumerate(rows):
        yy = top + r_ * (rowh + gap)
        out.append(f'<rect x="{L}" y="{yy}" width="{w - L - R}" height="{rowh}" fill="var(--line)" rx="2"/><text x="{L - 6}" y="{yy + rowh - 2}" text-anchor="end" class="ax">{E(lab)}</text>')
        for v, s, e in runs:
            if v == 1:
                out.append(f'<rect x="{x(s):.1f}" y="{yy}" width="{max(x(e) - x(s), 0.6):.1f}" height="{rowh}" fill="{fill}"/>')
    yy = top + 2 * (rowh + gap)
    out.append(f'<rect x="{L}" y="{yy}" width="{w - L - R}" height="{rowh}" fill="var(--line)" rx="2"/><text x="{L - 6}" y="{yy + rowh - 2}" text-anchor="end" class="ax">They differ</text>')
    for v, s, e, tip in pair_runs:
        if v in (1, 2):
            out.append(f'<rect x="{x(s):.1f}" y="{yy}" width="{max(x(e) - x(s), 0.6):.1f}" height="{rowh}" fill="{"var(--fg)" if v == 1 else COL["strategy"]}" opacity="{0.55 if v == 1 else 1}"/>')
    for yr in sorted({d.year for d in dates}):
        i = int(np.argmax([d.year == yr for d in dates]))
        out.append(f'<text x="{x(i):.1f}" y="{h - 6}" text-anchor="middle" class="ax">{yr}</text>')
    # hover layer, driven by the script at the end of the page: crosshair, a dot on each line, a y-axis chip, an x-axis date chip
    bot = top + 3 * (rowh + gap) - gap
    out.append('<g id="regime-hv" style="display:none" pointer-events="none">'
               f'<line id="hv-v" y1="{T}" y2="{bot}" stroke="var(--muted)" stroke-width="1"/>'
               f'<line id="hv-h" x1="{L}" x2="{w - R}" stroke="var(--muted)" stroke-width="1" stroke-dasharray="3 3"/>'
               + "".join(f'<circle id="hv-c{n}" r="4" fill="{c}" stroke="var(--card)" stroke-width="2"/>' for n, c in enumerate((COL["strategy"], "var(--fg)", COL["hold_parent"])))
               + f'<g id="hv-yc"><rect x="0" y="-8" width="{L - 3}" height="16" rx="3" fill="var(--fg)"/><text x="{L - 7}" y="3.5" text-anchor="end" font-size="10" fill="var(--bg)" id="hv-yt"></text></g>'
               f'<g id="hv-xc"><rect y="{h - 19}" width="70" height="16" rx="3" fill="var(--fg)" id="hv-xr"/><text y="{h - 7.5}" text-anchor="middle" font-size="10" fill="var(--bg)" id="hv-xt"></text></g></g>')
    out.append(f'<rect id="regime-ov" x="{L}" y="{T}" width="{w - L - R}" height="{bot - T}" fill="transparent" style="cursor:crosshair"/>')
    out.append("</svg>")
    return "".join(out), {"w": w, "h": h, "L": L, "R": R, "T": T, "ph": ph, "lo": lo, "hi": hi, "N": N}


HOVER_JS = """(function(){
var d=JSON.parse(document.getElementById('regime-data').textContent),svg=document.getElementById('regime-svg'),ov=document.getElementById('regime-ov'),
tip=document.getElementById('regime-tip'),fig=tip.parentNode,g=document.getElementById('regime-hv'),$=function(i){return document.getElementById(i)};
var cols=['#2a6fdb','var(--fg)','#8a8f98'],key=['rule','draw','parent'],lab=['Three-index rule',d.draw_label,'Hold the parent'];
function Y(v){return d.T+d.ph*(1-(Math.log(v)-d.lo)/(d.hi-d.lo))}
function X(i){return d.L+(d.w-d.L-d.R)*i/(d.N-1)}
function fx(v){return v.toFixed(2)+'\\u00d7'}
function move(e){
 var r=svg.getBoundingClientRect(),k=d.w/r.width,vx=(e.clientX-r.left)*k,vy=(e.clientY-r.top)*k;
 var i=Math.max(0,Math.min(d.N-1,Math.round((vx-d.L)/(d.w-d.L-d.R)*(d.N-1)))),x=X(i);
 g.style.display='';
 $('hv-v').setAttribute('x1',x);$('hv-v').setAttribute('x2',x);
 for(var n=0;n<3;n++){var c=$('hv-c'+n);c.setAttribute('cx',x);c.setAttribute('cy',Y(d[key[n]][i]))}
 var inPrice=vy>=d.T&&vy<=d.T+d.ph,h=$('hv-h'),yc=$('hv-yc');
 h.style.display=yc.style.display=inPrice?'':'none';
 if(inPrice){h.setAttribute('y1',vy);h.setAttribute('y2',vy);yc.setAttribute('transform','translate(0,'+vy+')');
  $('hv-yt').textContent=Math.exp(d.lo+(1-(vy-d.T)/d.ph)*(d.hi-d.lo)).toFixed(2)+'\\u00d7'}
 var xt=d.dates[i].slice(0,10),xr=$('hv-xr'),xl=Math.max(0,Math.min(d.w-70,x-35));
 xr.setAttribute('x',xl);$('hv-xt').setAttribute('x',xl+35);$('hv-xt').textContent=xt;
 var s='<b>'+d.dates[i]+'</b>';
 for(var n=0;n<3;n++)s+='<br><i style="background:'+cols[n]+'"></i>'+lab[n]+': <b>'+fx(d[key[n]][i])+'</b>';
 s+='<br>Rule: '+(d.rs[i]?'holds the parent':'in the sleeve')+'<br>'+d.draw_label+': '+(d.ds[i]?'holds the parent':'in the sleeve');
 s+='<span class="sub">This stretch: '+d.tips[d.tip[i]]+'</span>';
 tip.innerHTML=s;tip.hidden=false;
 var fr=fig.getBoundingClientRect(),px=e.clientX-fr.left+14,py=e.clientY-fr.top+14;
 if(px+tip.offsetWidth>fr.width)px=e.clientX-fr.left-tip.offsetWidth-14;
 if(py+tip.offsetHeight>fr.height)py=Math.max(0,e.clientY-fr.top-tip.offsetHeight-14);
 tip.style.left=px+'px';tip.style.top=py+'px';
}
function out(){g.style.display='none';tip.hidden=true}
ov.addEventListener('pointermove',move);ov.addEventListener('pointerdown',move);ov.addEventListener('pointerleave',out);
})();"""


LINES_JS = """(function(){
var all=JSON.parse(document.getElementById('lines-data').textContent);
function fx(v){return v.toFixed(2)+'\\u00d7'}
Array.prototype.forEach.call(document.querySelectorAll('svg.lc'),function(svg){
 var d=all[svg.getAttribute('data-book')],fig=svg.parentNode,tip=fig.querySelector('.tip'),g=svg.querySelector('.lc-hv'),ov=svg.querySelector('.lc-ov'),
 cs=svg.querySelectorAll('.lc-c'),q=function(c){return svg.querySelector(c)};
 function X(j){return d.L+(d.w-d.L-d.R)*j/(d.n-1)}
 function Y(v){return d.T+(d.h-d.T-d.B)*(1-((d.log?Math.log(v):v)-d.lo)/(d.hi-d.lo))}
 function move(e){
  var r=svg.getBoundingClientRect(),k=d.w/r.width,vx=(e.clientX-r.left)*k,vy=(e.clientY-r.top)*k;
  var j=Math.max(0,Math.min(d.n-1,Math.round((vx-d.L)/(d.w-d.L-d.R)*(d.n-1)))),x=X(j);
  g.style.display='';
  q('.lc-v').setAttribute('x1',x);q('.lc-v').setAttribute('x2',x);
  for(var n=0;n<cs.length;n++){cs[n].setAttribute('cx',x);cs[n].setAttribute('cy',Y(d.series[n].v[j]))}
  var top=d.T,hgt=d.h-d.T-d.B,hl=q('.lc-h'),yc=q('.lc-yc');
  hl.setAttribute('y1',vy);hl.setAttribute('y2',vy);yc.setAttribute('transform','translate(0,'+vy+')');
  var f=1-(vy-top)/hgt,lv=d.lo+f*(d.hi-d.lo);q('.lc-yt').textContent=fx(d.log?Math.exp(lv):lv);
  var xr=q('.lc-xr'),xl=Math.max(0,Math.min(d.w-92,x-46));
  xr.setAttribute('x',xl);q('.lc-xt').setAttribute('x',xl+46);q('.lc-xt').textContent=d.dates[j];
  var s='<b>'+d.dates[j]+'</b>';
  for(var n=0;n<d.series.length;n++)s+='<br><i style="background:'+d.series[n].col+'"></i>'+d.series[n].label+': <b>'+fx(d.series[n].v[j])+'</b>';
  tip.innerHTML=s;tip.hidden=false;
  var fr=fig.getBoundingClientRect(),px=e.clientX-fr.left+14,py=e.clientY-fr.top+14;
  if(px+tip.offsetWidth>fr.width)px=e.clientX-fr.left-tip.offsetWidth-14;
  if(py+tip.offsetHeight>fr.height)py=Math.max(0,e.clientY-fr.top-tip.offsetHeight-14);
  tip.style.left=px+'px';tip.style.top=py+'px';
 }
 function out(){g.style.display='none';tip.hidden=true}
 ov.addEventListener('pointermove',move);ov.addEventListener('pointerdown',move);ov.addEventListener('pointerleave',out);
});
})();"""


def runs_of(vals, starts, ends):
    """Merge consecutive weeks with the same value into (value, first_session, last_session, first_week, last_week)."""
    res, i = [], 0
    while i < len(vals):
        k = i
        while k + 1 < len(vals) and vals[k + 1] == vals[i]:
            k += 1
        if ends[k] > starts[i]:
            res.append((int(vals[i]), starts[i], ends[k], i, k))
        i = k + 1
    return res


def table(rows, cols, cls=""):
    th = "".join(f"<th>{E(c)}</th>" for c in cols)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f'<div class="tw"><table class="{cls}"><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table></div>'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="headline")
    a = ap.parse_args()
    ev = HERE / "evidence" / a.run
    dec = pd.read_csv(ev / "decisions.csv")
    st = pd.read_csv(ev / "stats.csv")
    dr = pd.read_csv(ev / "draws.csv")
    tr = pd.read_csv(ev / "trades.csv")
    nav = pd.read_csv(ev / "daily_nav.csv", parse_dates=["date"])
    pos = pd.read_csv(ev / "positions.csv")
    g4 = pd.read_csv(ev / "g_engine.csv")
    exs = pd.read_csv(ev / "draw_states_example.csv")
    au = json.loads((ev / "audit.json").read_text(encoding="utf-8"))
    ver = json.loads((ev / "verify_t03.json").read_text(encoding="utf-8")) if (ev / "verify_t03.json").exists() else None
    t03 = (HERE / "T03.md").read_text(encoding="utf-8")
    sha = t03.split("§1–§3 sha256:** `")[1].split("`")[0]

    S = lambda b, kind="strategy", cost=PRIMARY, win="full", cash="lbes": st[(st.book == b) & (st.window == win) & (st.cash == cash) & (st.cost_bps == cost) & (st.kind == kind)].iloc[0]
    D = lambda b, typ, cost=PRIMARY, win="full", cash="lbes": dr[(dr.book == b) & (dr.window == win) & (dr.cash == cash) & (dr.cost_bps == cost) & (dr.draw_type == typ)]
    data = {"books": {}, "run": a.run, "prereg_sha256": sha}
    for b in BOOKS:
        s = S(b)
        n, sh = D(b, "N4.9"), D(b, "shift")
        rc, rd = rank(s.cagr, n.cagr.values), rank(s.max_dd, n.max_dd.values)
        data["books"][b] = {"cagr": float(s.cagr), "max_dd": float(s.max_dd), "end_nav": float(s.end_nav), "null_median_cagr": float(n.cagr.median()),
                            "null_median_dd": float(n.max_dd.median()), "pct_cagr": rc["percentile"], "p_cagr": rc["p"], "pct_dd": rd["percentile"], "p_dd": rd["p"],
                            "draws": rc["draws"], "shift_pct_cagr": rank(s.cagr, sh.cagr.values)["percentile"], "shift_pct_dd": rank(s.max_dd, sh.max_dd.values)["percentile"],
                            "null_sd_cagr": float(n.cagr.std()), "null_sd_dd": float(n.max_dd.std()), "mde_cagr_pp": float(280 * n.cagr.std()), "mde_dd_pp": float(280 * n.max_dd.std()),
                            "hold_cagr": float(S(b, "hold_parent").cagr), "hold_dd": float(S(b, "hold_parent").max_dd), "mix_cagr": float(S(b, "constant_mix").cagr),
                            "mix_dd": float(S(b, "constant_mix").max_dd), "sleeve_cagr": float(S(b, "sleeve_only").cagr), "sleeve_dd": float(S(b, "sleeve_only").max_dd),
                            "trades": int(s.trades), "cost_paid": float(s.cost_paid)}
        pn = nav[(nav.book == b) & (nav.run == "published_D17")].nav.values
        data["books"][b].update({"pub_cagr": nav_stats(pn)["cagr"], "pub_dd": nav_stats(pn)["max_dd"]})
        live = S(b, win="live")
        nl = D(b, "N4.9", win="live")
        data["books"][b].update({"live_cagr": float(live.cagr), "live_pct": rank(live.cagr, nl.cagr.values)["percentile"]})
        liq = S(b, cash="liquidcase")
        nq = D(b, "N4.9", cash="liquidcase")
        data["books"][b].update({"liq_cagr": float(liq.cagr), "liq_pct": rank(liq.cagr, nq.cagr.values)["percentile"]})
        for c in (0.0, 50.0):
            data["books"][b][f"pct_cagr_{c:g}"] = rank(S(b, cost=c).cagr, D(b, "N4.9", cost=c).cagr.values)["percentile"]
    c1 = sum(data["books"][b]["pct_cagr"] >= 90 for b in BOOKS)
    c2 = sum(data["books"][b]["pct_dd"] >= 90 for b in BOOKS)
    r4 = sum(data["books"][b]["live_pct"] >= 90 for b in BOOKS)
    data["verdict"] = {"C1": c1, "C2": c2, "R4_live_ge90": r4}

    # worked example: SCMO_0003
    b = "SCMO_0003"
    d = dec[dec.book == b].reset_index(drop=True)
    j1 = int(d.index[(d.state != d.state.shift()) & (d.index > 0)][0])
    r = d.loc[j1]
    t = tr[(tr.book == b) & (tr.run == "strategy") & (tr.cost_bps == PRIMARY)].reset_index(drop=True)
    tt = t[t.date == r.trade_date].iloc[0]
    held = pos[(pos.book == b) & (pos.cost_bps == PRIMARY) & (pos.run == "strategy") & (pos.date == tt["date"])]
    nv = nav[(nav.book == b) & (nav.cost_bps == PRIMARY) & (nav.run == "strategy")].reset_index(drop=True)
    k = int(nv.index[nv.date == pd.Timestamp(r.trade_date)][0])
    s0 = S(b)
    e0 = exs[(exs.book == b) & (exs.draw_id == 0)].head(20)
    x0 = D(b, "N4.9")
    x0 = x0[x0.draw_id == 0].iloc[0]
    rk = rank(s0.cagr, D(b, "N4.9").cagr.values)
    data["example"] = {"decision_week": j1, "decision_date": str(r.decision_date), "trade_date": str(r.trade_date), "V": float(tt.V), "traded": float(tt.traded), "cost": float(tt.cost),
                       "nav_after": float(tt.nav_close_after), "draw0_cagr": float(x0.cagr), "draw0_dd": float(x0.max_dd), "rank_worse": rk["worse"], "rank_tied": rk["tied"],
                       "rank_better": rk["better"], "pct": rk["percentile"], "p": rk["p"], "sessions": int(s0.sessions), "end_nav": float(s0.end_nav), "cagr": float(s0.cagr)}

    # ── html ──────────────────────────────────────────────────────────────────
    verdict_word = lambda ok: ('<span class="chip ok">PASS</span>' if ok else '<span class="chip bad">FAIL</span>')
    head_rows = []
    for b in BOOKS:
        x = data["books"][b]
        head_rows.append([E(b), pc(x["hold_cagr"]), pc(x["cagr"]), pc(x["null_median_cagr"]), f"{100 * (x['cagr'] - x['null_median_cagr']):+.1f} pp",
                          f"<b>{x['pct_cagr']:.1f}</b>", f"{x['p_cagr']:.3f}", pc(x["hold_dd"]), pc(x["max_dd"]), pc(x["null_median_dd"]), f"<b>{x['pct_dd']:.1f}</b>", f"{x['p_dd']:.3f}"])
    cost_rows = []
    for b in BOOKS:
        for kind in ("strategy", "hold_parent", "constant_mix", "sleeve_only"):
            row = [E(b) if kind == "strategy" else "", LAB[kind]]
            for cst in (0.0, PRIMARY, 50.0):
                s = S(b, kind, cst)
                row += [pc(s.cagr), pc(s.max_dd)]
            cost_rows.append(row)
    mde_rows = [[E(b), str(au["books"][b]["round_trips"]), f"{100 * data['books'][b]['null_sd_cagr']:.2f}", f"{data['books'][b]['mde_cagr_pp']:.1f}", f"{100 * data['books'][b]['null_sd_dd']:.2f}", f"{data['books'][b]['mde_dd_pp']:.1f}"] for b in BOOKS]
    rob_rows = [[E(b), f"{data['books'][b]['shift_pct_cagr']:.1f}", f"{data['books'][b]['shift_pct_dd']:.1f}", f"{data['books'][b]['pct_cagr_0']:.1f}", f"{data['books'][b]['pct_cagr']:.1f}", f"{data['books'][b]['pct_cagr_50']:.1f}",
                 f"{data['books'][b]['liq_pct']:.1f}", f"{data['books'][b]['live_pct']:.1f}", pc(data["books"][b]["live_cagr"])] for b in BOOKS]
    curves, lines_data = "", {}
    for b in BOOKS:
        ser, dates = {}, None
        for kind in ("strategy", "hold_parent", "constant_mix", "sleeve_only"):
            q = nav[(nav.book == b) & (nav.cost_bps == PRIMARY) & (nav.run == kind)]
            ser[kind] = q.nav.values
            dates = list(q.date)
        ser["published_D17"] = nav[(nav.book == b) & (nav.run == "published_D17")].nav.values
        x = data["books"][b]
        lsvg, ldata = svg_lines(ser, dates, ylab=b)
        lines_data[b] = ldata
        curves += (f'<figure class="card hv"><figcaption><b>{E(b)}</b> · growth of 1 from {dates[0].date()} to {dates[-1].date()}, 20.8 bps · rule ends at {x["end_nav"]:.2f}×. '
                   f'Hover (or touch): the crosshair shows the date and the level, and the tooltip lists all five curves at that date (the lines are drawn every 5th session, and the hover snaps to those sessions).</figcaption>'
                   + lsvg + '<div class="tip" hidden></div></figure>')
    legend = "".join(f'<span class="key"><i style="background:{COL[k]}"></i>{E(LAB[k])}</span>' for k in COL)
    hists = ""
    for b in BOOKS:
        n = D(b, "N4.9")
        x = data["books"][b]
        hists += (f'<figure class="card"><figcaption><b>{E(b)}</b> · {x["draws"]:,} random timings, 20.8 bps</figcaption>'
                  f'<div class="two"><div><div class="mini">CAGR (blue = the rule, dashed = median of draws)</div>{svg_hist(n.cagr.values, x["cagr"])}</div>'
                  f'<div><div class="mini">Maximum drawdown (shallower is to the right)</div>{svg_hist(n.max_dd.values, x["max_dd"])}</div></div></figure>')
    # ── the highest-CAGR random timing against the rule (SCMO_0003) ───────────
    bb = "SCMO_0003"
    nbb = D(bb, "N4.9")
    bbest = nbb.loc[nbb.cagr.idxmax()]
    bid = int(bbest.draw_id)
    bstate = pd.read_csv(ev / f"draw_{bid}_states.csv")
    bcurve = np.load(ev / "draw_curves_20.8.npz")[f"{bb}|N4.9_{bid}"].astype(float)
    qn = lambda kind, cost: nav[(nav.book == bb) & (nav.cost_bps == cost) & (nav.run == kind)]
    rq = qn("strategy", PRIMARY)
    bdates = list(rq.date)
    nses = len(bdates)
    pnav, snav = qn("hold_parent", 0.0).nav.values, qn("sleeve_only", 0.0).nav.values
    bdec = dec[dec.book == bb].reset_index(drop=True)
    assert len(bstate) == len(bdec) and (bstate.real_state.values == bdec.state.values).all() and len(bcurve) == nses
    assert abs(bcurve[-1] / float(bbest.end_nav) - 1) < 1e-5
    dnp = np.array(rq.date.values, dtype="datetime64[ns]")
    wk0 = [0]
    for td in bdec.trade_date.iloc[1:]:
        wk0.append(nses - 1 if pd.isna(td) else int(np.searchsorted(dnp, np.datetime64(pd.Timestamp(td)))))
    wk1 = wk0[1:] + [nses - 1]
    rs_, ds_ = bstate.real_state.values.astype(int), bstate.draw_state.values.astype(int)
    code = 2 * rs_ + ds_  # 3 both in, 0 both out, 1 draw only, 2 rule only
    CODE = {3: "Both hold the parent", 0: "Both in the sleeve", 1: f"Draw {bid} holds the parent, rule in the sleeve", 2: "Rule holds the parent, draw in the sleeve"}
    pr = lambda r_: f"{100 * (r_ - 1):+.1f}%"
    cls_w, cls_p, cls_s = {c: 0 for c in CODE}, {c: 1.0 for c in CODE}, {c: 1.0 for c in CODE}
    pair_runs, span_rows, span_stats = [], [], []
    for c_, s_, e_, i_, k_ in runs_of(code, wk0, wk1):
        wks = k_ - i_ + 1
        pa, sl = pnav[e_] / pnav[s_], snav[e_] / snav[s_]
        cls_w[c_] += wks
        cls_p[c_] *= pa
        cls_s[c_] *= sl
        tip = f"{bdates[s_].date()} → {bdates[e_].date()}, {wks} wk: {CODE[c_]}. Parent {pr(pa)}, sleeve {pr(sl)}"
        pair_runs.append((c_, s_, e_, tip))
        if c_ in (1, 2):
            right = ("draw" if c_ == 1 else "rule") if pa > sl else ("rule" if c_ == 1 else "draw")
            span_stats.append((c_, wks, pa, sl, right))
            span_rows.append([str(bdates[s_].date()), str(bdates[e_].date()), str(wks), f"Draw {bid}" if c_ == 1 else "Rule", pr(pa), pr(sl), f"{100 * (pa - sl):+.1f} pp", f"<b>{right}</b>"])
    rule_runs = [(v_, s_, e_) for v_, s_, e_, *_ in runs_of(rs_, wk0, wk1)]
    draw_runs = [(v_, s_, e_) for v_, s_, e_, *_ in runs_of(ds_, wk0, wk1)]
    assert abs(np.prod(list(cls_p.values())) / pnav[-1] * pnav[0] - 1) < 1e-9  # the four classes tile the whole window
    ser_b = {"hold_parent": pnav, "draw": bcurve, "strategy": rq.nav.values}
    # per-session hover data: every value the chart draws, for every session
    st_rule, st_draw, tip_ix = np.zeros(nses, int), np.zeros(nses, int), np.zeros(nses, int)
    for j_ in range(len(bstate)):
        st_rule[wk0[j_]:wk1[j_]], st_draw[wk0[j_]:wk1[j_]] = rs_[j_], ds_[j_]
    for r_, (c_, s_, e_, tip) in enumerate(pair_runs):
        tip_ix[s_:e_] = r_
    st_rule[-1], st_draw[-1], tip_ix[-1] = st_rule[-2], st_draw[-2], tip_ix[-2]
    hover = {"dates": [d_.strftime("%Y-%m-%d (%a)") for d_ in bdates], "rule": [round(float(v_), 4) for v_ in rq.nav.values], "draw": [round(float(v_), 4) for v_ in bcurve],
             "parent": [round(float(v_), 4) for v_ in pnav], "rs": st_rule.tolist(), "ds": st_draw.tolist(), "tip": tip_ix.tolist(), "tips": [p_[3] for p_ in pair_runs],
             "draw_label": f"Draw {bid}"}
    cls_rows = [[CODE[c_], str(cls_w[c_]), pr(cls_p[c_]), pr(cls_s[c_]), f"{100 * (cls_p[c_] - cls_s[c_]):+.1f} pp"] for c_ in (3, 0, 1, 2)]
    wrong = lambda c_: sum(1 for s in span_stats if s[0] == c_ and s[4] != ("draw" if c_ == 1 else "rule"))
    n1, n2 = sum(1 for s in span_stats if s[0] == 1), sum(1 for s in span_stats if s[0] == 2)
    data["best_draw"] = {"book": bb, "draw_id": bid, "cagr": float(bbest.cagr), "end_nav": float(bbest.end_nav), "rule_cagr": data["books"][bb]["cagr"],
                         "weeks_both_in": cls_w[3], "weeks_both_out": cls_w[0], "weeks_draw_only": cls_w[1], "weeks_rule_only": cls_w[2],
                         "spans_draw_only": n1, "spans_rule_only": n2}
    # what the shuffle holds and what it randomises, for this draw (weeks come from the weekly states, sessions from the trade-date spans)
    def sp(a):
        out_, i_ = [], 0
        while i_ < len(a):
            k_ = i_
            while k_ + 1 < len(a) and a[k_ + 1] == a[i_]:
                k_ += 1
            out_.append((int(a[i_]), k_ - i_ + 1))
            i_ = k_ + 1
        return out_
    spr, spd = sp(rs_), sp(ds_)
    ln = lambda s_, v_: [n_ for x_, n_ in s_ if x_ == v_]
    ent = lambda a: int(((a[1:] == 1) & (a[:-1] == 0)).sum())
    ext = lambda a: int(((a[1:] == 0) & (a[:-1] == 1)).sum())
    ses_r = sum(wk1[j_] - wk0[j_] for j_ in range(len(rs_)) if rs_[j_] == 1)
    ses_d = sum(wk1[j_] - wk0[j_] for j_ in range(len(ds_)) if ds_[j_] == 1)
    nw = len(rs_)
    fl = lambda ok, txt="held": f'<span class="chip ok">{txt}</span>' if ok else f'<span class="chip warn">{txt}</span>'
    hold_tab = [
        [f"Weeks invested (of {nw})", f"{rs_.sum()} ({pc(rs_.mean(), 2)})", f"{ds_.sum()} ({pc(ds_.mean(), 2)})", fl(rs_.sum() == ds_.sum())],
        [f"Sessions invested (of {nses - 1:,})", f"{ses_r} ({pc(ses_r / (nses - 1), 2)})", f"{ses_d} ({pc(ses_d / (nses - 1), 2)})",
         fl(ses_r == ses_d, "held" if ses_r == ses_d else f"not held: differs by {abs(ses_r - ses_d)}")],
        ["In-spells · out-spells", f"{len(ln(spr, 1))} · {len(ln(spr, 0))}", f"{len(ln(spd, 1))} · {len(ln(spd, 0))}", fl(len(spr) == len(spd))],
        ["Entries (0→1) · exits (1→0)", f"{ent(rs_)} · {ext(rs_)}", f"{ent(ds_)} · {ext(ds_)}", fl((ent(rs_), ext(rs_)) == (ent(ds_), ext(ds_)))],
        ["First state", "sleeve" if rs_[0] == 0 else "parent", "sleeve" if ds_[0] == 0 else "parent", fl(rs_[0] == ds_[0])],
        ["In-spell lengths (weeks), in order", ", ".join(map(str, ln(spr, 1))), ", ".join(map(str, ln(spd, 1))), fl(sorted(ln(spr, 1)) == sorted(ln(spd, 1)), "same lengths")],
        ["Out-spell lengths (weeks), in order", ", ".join(map(str, ln(spr, 0))), ", ".join(map(str, ln(spd, 0))), fl(sorted(ln(spr, 0)) == sorted(ln(spd, 0)), "same lengths")],
        ["Order of the spells", "the rule's own", "shuffled", '<span class="chip">randomised</span>'],
    ]
    data["best_draw"].update({"weeks_invested_rule": int(rs_.sum()), "weeks_invested_draw": int(ds_.sum()), "sessions_invested_rule": int(ses_r), "sessions_invested_draw": int(ses_d),
                              "sessions_span": int(nses - 1), "in_spells": len(ln(spr, 1)), "out_spells": len(ln(spr, 0)), "entries": ent(rs_), "exits": ext(rs_)})
    rsvg, geom = svg_regime(bdates, ser_b, rule_runs, draw_runs, pair_runs, f"Draw {bid}")
    hover.update(geom)
    regime = (f'<h2 id="regime">The highest-return random timing against the rule ({bb})</h2>'
              f'<p>The right-hand end of the {bb} histogram above is draw {bid}: CAGR {pc(float(bbest.cagr))} (end value {float(bbest.end_nav):.1f}×), against the rule\'s {pc(data["books"][bb]["cagr"])} ({data["books"][bb]["end_nav"]:.1f}×). '
              f'It holds the parent for the same {int(bbest.invested_weeks)} weeks and switches the same number of times as the rule, in a different order. '
              f'Its states are in <code>evidence/{E(a.run)}/draw_{bid}_states.csv</code>, rebuilt from the seed <code>default_rng([3, {bid}])</code> and equal to the stored row.</p>'
              f'<h3>What the shuffle holds, and what it randomises, for this draw</h3>'
              + table(hold_tab, ["Dimension", "The rule", f"Draw {bid}", "Held?"])
              + f'<p class="cap">Weeks, spell counts and spell lengths are held exactly: the draw reorders the rule\'s nine in-spells among themselves and its nine out-spells among themselves, '
                f'alternates them starting in the rule\'s first state, and lays them out from {bdates[0].date()}. The gate V3 checks exactly these. '
                f'Sessions are not held exactly: a week has 3 to 5 sessions because of holidays, so moving a spell changes how many sessions it covers. '
                f'Here the two differ by {abs(ses_r - ses_d)} of {nses - 1:,} sessions ({100 * abs(ses_r - ses_d) / (nses - 1):.2f} pp of the window).</p>'
              f'<div class="legend"><span class="key"><i style="background:{COL["strategy"]}"></i>Three-index rule</span><span class="key"><i style="background:var(--fg)"></i>Draw {bid}</span>'
              f'<span class="key"><i style="background:{COL["hold_parent"]}"></i>Hold the parent</span>'
              f'<span class="key"><i style="background:{COL["strategy"]};height:10px;opacity:.5"></i>only the rule holds the parent</span>'
              f'<span class="key"><i style="background:var(--fg);height:10px;opacity:.4"></i>only the draw holds the parent</span></div>'
              f'<figure class="card hv"><figcaption><b>{bb}</b> · growth of 1 from {bdates[0].date()} to {bdates[-1].date()}, 20.8 bps (log scale); the grey line is the parent held throughout, before cost. '
              f'Strips: filled = holds the parent that week, empty = in the 50/50 sleeve. Hover (or touch) anywhere on the chart: the crosshair shows the date on the x-axis and the level on the y-axis, '
              f'and the tooltip lists every value drawn at that date.</figcaption>'
              + rsvg + '<div id="regime-tip" class="tip" hidden></div></figure>'
              f'<h3>Weeks by what the two did</h3>'
              + table(cls_rows, ["The two timings", "Weeks", "Parent, compounded over these weeks", "Sleeve, same weeks", "Parent minus sleeve"])
              + f'<p>They agree in {cls_w[3] + cls_w[0]} of {len(code)} weeks and differ in {cls_w[1] + cls_w[2]}, in {n1 + n2} separate stretches. '
                f'In the stretches only the draw held the parent, the parent beat the sleeve in {n1 - wrong(1)} of {n1}; in the stretches only the rule held it, the parent beat the sleeve in {n2 - wrong(2)} of {n2}.</p>'
              + '<h3>Every stretch where they differ</h3>'
              + table(span_rows, ["From", "To", "Weeks", "Holds the parent", "Parent", "Sleeve", "Parent minus sleeve", "Right call"])
              + '<p class="cap">Returns are close to close between trade dates, before cost, and compounded within each stretch, so the stretches explain the gap between the two paths but do not add up exactly to the CAGR difference. '
                '"Right call" is the timing that was in the better of parent and sleeve over the stretch. '
                f'Draw {bid} is the best of {len(nbb):,} draws, so it is the extreme of the null by construction, not a rival rule.</p>')
    nvw = nv.loc[k - 2:k + 2]
    ex = data["example"]
    held_rows = [[E(str(h_.instrument)), f"{h_.units:.6f}"] for h_ in held.head(6).itertuples()]
    ex_rows = [[str(h_.j), str(h_.decision_date), str(h_.real_state), str(h_.draw_state)] for h_ in e0.itertuples()]
    g4rows = [[E(r_.book), f"{r_.cagr_gap_pp_yr:+.3f}", r_.overall, str(r_.worst_year), f"{r_.worst_year_gap_pp:+.3f}", r_.yearly, f"{r_.max_rel_diff_vs_step1_rebuild:.1e}"] for r_ in g4.itertuples()]
    v = au["v3"]
    gates = [("V1 independent check", ("PASS" if ver and ver.get("exit_ok") and ver.get("gate_failures_and_missing", 1) == 0 else "NOT RUN / FAIL"), (f"verify_t03.py shares no code with the engine: {ver['gate_compared']:,} comparisons, 0 failures, a corrupted copy is caught" if ver else "verify_t03.py shares no code with the engine")),
             ("V2 point in time", "PASS" if all(au["books"][bb]["v2_label_after_decision"] == 0 for bb in BOOKS) else "FAIL",
              f"{sum(au['books'][bb]['v2_decisions_checked'] + au['books'][bb]['v2_trades_checked'] for bb in BOOKS):,} checks, 0 violations"),
             ("V3 the null holds its table", "PASS" if v["n49_sig_mismatch"] == 0 and v["n49_invested_weeks_mismatch"] == 0 else "FAIL",
              f"{v['n49_draws']:,} draws: same invested weeks, spell count and spell lengths as the rule"),
             ("V4 always-in reproduces the rebuild", "PASS" if (g4.overall == "PASS").all() and (g4.yearly == "PASS").all() else "FAIL", "G0 on all four parents")]
    css = """
:root{--bg:#fbfbfa;--fg:#1c1f24;--muted:#6b7280;--card:#ffffff;--line:#e3e5e8;--bar:#c4cad4;--ok:#1b7f4d;--bad:#b3261e;--warn:#a86400}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#14161a;--fg:#e6e8eb;--muted:#9aa1ab;--card:#1b1e23;--line:#2d3138;--bar:#4a5260;--ok:#4cc38a;--bad:#ff7b72;--warn:#e0a43a}}
:root[data-theme=dark]{--bg:#14161a;--fg:#e6e8eb;--muted:#9aa1ab;--card:#1b1e23;--line:#2d3138;--bar:#4a5260;--ok:#4cc38a;--bad:#ff7b72;--warn:#e0a43a}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.55 -apple-system,Segoe UI,Roboto,sans-serif}
main{max-width:980px;margin:0 auto;padding:24px 16px 64px}h1{font-size:26px;line-height:1.2;margin:.2em 0}h2{margin-top:2.2em;font-size:20px;border-top:1px solid var(--line);padding-top:1em}h3{font-size:16px;margin-top:1.6em}
.eyebrow,.meta,.mini,.cap,.ax{color:var(--muted);font-size:12.5px}.tw{overflow-x:auto;margin:.8em 0}table{border-collapse:collapse;font-size:13px;min-width:100%}th,td{padding:5px 8px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}th{color:var(--muted);font-weight:500}td:first-child,th:first-child{text-align:left}
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:10px 12px;margin:10px 0}figcaption{font-size:13px;margin-bottom:4px}.chart{width:100%;height:auto}.grid{stroke:var(--line)}.ax{fill:var(--muted);font-size:10px}.bar{fill:var(--bar)}
.chip{padding:1px 8px;border-radius:10px;font-weight:600;font-size:12px;border:1px solid currentColor}.ok{color:var(--ok)}.bad{color:var(--bad)}.warn{color:var(--warn)}
.legend{display:flex;flex-wrap:wrap;gap:6px 16px;font-size:12.5px;margin:6px 0}.key i{display:inline-block;width:14px;height:3px;margin-right:6px;vertical-align:middle}
.formula{background:var(--card);border:1px solid var(--line);border-radius:6px;padding:8px 12px;font:12.5px/1.5 ui-monospace,Consolas,monospace;white-space:pre-wrap;overflow-x:auto}.two{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.hv{position:relative}.tip{position:absolute;z-index:5;pointer-events:none;background:var(--card);border:1px solid var(--line);border-radius:6px;padding:6px 9px;font-size:12px;line-height:1.5;white-space:nowrap;box-shadow:0 2px 8px rgba(0,0,0,.18);font-variant-numeric:tabular-nums}.tip b{font-weight:600}.tip i{display:inline-block;width:10px;height:3px;margin-right:6px;vertical-align:middle}.tip .sub{color:var(--muted);white-space:normal;display:block;max-width:300px;margin-top:3px}
.answer{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--warn);border-radius:6px;padding:12px 16px}@media (max-width:640px){.two{grid-template-columns:1fr}h1{font-size:22px}}
"""
    lead = ("Yes on the full 2019 → 2026 window, with a catch." if (c1 >= 3 and c2 >= 3) else
            "Partly." if (c1 >= 3 or c2 >= 3) else "No.")
    answer = (f'<div class="answer"><p><b>{lead}</b> Holding the parent only when the Nifty 100, Midcap 100 and Smallcap 100 are all BUY, '
              f'and a 50/50 GOLDBEES and cash sleeve otherwise, beat randomly timed versions of itself in {c1} of 4 books on return (pre-registered pass: 3 of 4 at the 90th percentile) '
              f'and in {c2} of 4 on the depth of the worst fall.</p><p>The catch: judged only on the decisions that were live in production (2021-11 → 2026-08), return beats the 90th percentile in {r4} of 4 books, '
              f'and the decisions before 2021 are a backfill by the production code. The rule was also chosen after seeing 2014-2026 results, so every result here is in-sample and PROVISIONAL.</p></div>')
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>T03 three-index switch</title><style>{css}</style></head><body><main>
<p class="eyebrow">AA · T03 · timing rule · pre-registration sha256 {E(sha[:12])}</p>
<h1>Does the three-index switch choose <em>when</em> to hold the parent better than chance?</h1>
<p class="meta">2019-01-02 → 2026-08-21 (SCMO_0007 from 2019-01-04) · four parents of the AA books · decisions every Friday, trades next session at OHLC4 · 10.4 bps a side · every number is computed from <code>evidence/{E(a.run)}/</code></p>
<h2 id="answer">The answer</h2>{answer}
{table([[E(b), pc(data['books'][b]['cagr']), f"{data['books'][b]['pct_cagr']:.1f}", f"{data['books'][b]['p_cagr']:.3f}", pc(data['books'][b]['max_dd']), f"{data['books'][b]['pct_dd']:.1f}", f"{data['books'][b]['p_dd']:.3f}", pc(data['books'][b]['live_cagr']), f"{data['books'][b]['live_pct']:.1f}"] for b in BOOKS],
        ["Book", "Rule CAGR", "CAGR percentile", "p", "Rule worst fall", "Drawdown percentile", "p", "Live-only CAGR", "Live-only percentile"])}
<p class="cap">Percentile = share of 2,000 random timings the rule beats (ties count half). Pass mark: 90 in at least 3 of 4 books. After 20.8 bps round-trip cost. The four books have the same in-or-out decisions, so "3 of 4" is a consistency check, not four tests.</p>
<table><tbody><tr><td>C1 timing (return)</td><td>{verdict_word(c1 >= 3)} {c1} of 4</td></tr><tr><td>C2 protection (worst fall)</td><td>{verdict_word(c2 >= 3)} {c2} of 4</td></tr></tbody></table>
<h3>What to be careful about</h3><ul>
<li><b>The null is "same weeks in the market, placed at random".</b> A pass says the rule's timing is better than random placement, not that it is better than holding. It was out of the market in about half the weeks, so compare with the constant mix below.</li>
<li><b>Nothing is out of sample.</b> The rule was chosen after seeing 2014-2026. Decisions before 2021-11 are the production code run backwards, not signals traded at the time. On the live decisions only, return is {r4} of 4 at the 90th percentile.</li>
<li><b>Nine round trips per book</b> is all the evidence there is. The smallest return edge detectable at 80% power is {min(data['books'][b]['mde_cagr_pp'] for b in BOOKS):.0f} to {max(data['books'][b]['mde_cagr_pp'] for b in BOOKS):.0f} pp a year.</li>
<li><b>The books are one market.</b> SCMO_0007 misses the 90th percentile on return ({data['books']['SCMO_0007']['pct_cagr']:.1f}).</li></ul>

<h2 id="data">The data</h2>
<p>Each parent's NAV is rebuilt every day from its own stocks (Eikon prices, price return, Polyplex's special dividend corrected), not read from a file. The published NAV (D17) is used for the calendar and as a check: the engine's always-invested book reproduces it within the pre-registered tolerance.</p>
{table(g4rows, ["Book", "CAGR gap vs published (pp/yr)", "Within ±0.25", "Worst calendar year", "Gap (pp)", "Within ±0.5", "Max difference vs Step 1 rebuild"])}
<p class="cap">Inputs and verdicts (data review of 2026-11-05): signals D03 PASS · stock OHLC D18, weights D19, published NAV D17, GOLDBEES D09 PASS WITH NOTES · cash D11 FAIL (source unrecorded; bounded at 0.09 pp/yr on a book's CAGR). Calendar = D17's dates. Gates:</p>
{table([[E(n), f'<span class="chip {"ok" if s == "PASS" else "bad"}">{s}</span>', E(t_)] for n, s, t_ in gates], ["Gate", "Result", "What it checks"])}

<h2 id="one">One backtest, end to end ({b})</h2>
<p><b>1. The decision.</b> On Friday {E(ex['decision_date'])} (week {ex['decision_week']}) the latest weekly rows of the three index files read Nifty 100 {E(str(r.sign_Nifty100))}, Midcap 100 {E(str(r.sign_MC100))}, Smallcap 100 {E(str(r.sign_SC100))}. All three are BUY, so the target is the parent; last week it was the sleeve.</p>
<div class="formula">state(d) = IN  if SIGN_Nifty100 = SIGN_MC100 = SIGN_SC100 = BUY (latest row dated on or before d), else OUT
IN  → 100% parent basket        OUT → 50% GOLDBEES + 50% cash</div>
<p><b>2. The trade.</b> On the next session, {E(ex['trade_date'])}, at the (open+high+low+close)/4 of every instrument the book sells the sleeve and buys the basket in force. Value before: {ex['V']:.6f}; value traded (both sides): {ex['traded']:.6f}; cost = traded × 20.8 ÷ 2 ÷ 10,000 = {ex['cost']:.6f}.</p>
<div class="formula">traded = Σ |target value − held value|        cost = traded × cost_bps ÷ 2 ÷ 10,000
new units = target value × (V − cost) ÷ V ÷ fill price</div>
<p><b>3. Units.</b> After the trade the book holds, among others:</p>{table(held_rows, ["Instrument", "Units"])}
<p><b>4. Daily value.</b> NAV(t) = Σ units × close(t) over stocks, GOLDBEES and cash. Around the trade:</p>
{table([[str(r_.date.date()), f"{r_.nav:.6f}"] for r_ in nvw.itertuples()], ["Date", "NAV"])}
<p><b>5. Statistics.</b> The path runs from 1.000000 on {nv.date.iloc[0].date()} to {ex['end_nav']:.6f} on {nv.date.iloc[-1].date()}: {ex['sessions']} sessions, years = ({ex['sessions']} − 1) ÷ 252 = {(ex['sessions'] - 1) / 252:.4f}, CAGR = {ex['end_nav']:.4f}^(1 ÷ {(ex['sessions'] - 1) / 252:.4f}) − 1 = <b>{pc(ex['cagr'], 2)}</b>, worst fall {pc(data['books'][b]['max_dd'], 2)}.</p>
<p><b>6. One random timing.</b> The rule's path is 18 spells (9 in, 9 out) of fixed lengths. A draw shuffles the in-spells among themselves and the out-spells among themselves. The first 20 weekly states of the rule and of draw 0 (seed <code>default_rng([3, 0])</code>); the draw's CAGR is {pc(ex['draw0_cagr'], 2)} and its worst fall {pc(ex['draw0_dd'], 2)}:</p>
{table(ex_rows, ["Week", "Date", "Rule (1 = parent)", "Draw 0"])}
<p><b>7. The ranking.</b> Among the {rk['draws']:,} draws the rule's CAGR beat {ex['rank_worse']:,}, tied {ex['rank_tied']}, and was beaten by {ex['rank_better']}: percentile = ({ex['rank_worse']} + 0.5 × {ex['rank_tied']}) ÷ {rk['draws']:,} × 100 = <b>{ex['pct']:.2f}</b>; p-value = (1 + {ex['rank_better']}) ÷ ({rk['draws']:,} + 1) = {ex['p']:.4f}.</p>

<h2 id="headline">Headline</h2>
<p>After 20.8 bps, full window, against the 2,000 random timings:</p>
{table(head_rows, ["Book", "Hold parent CAGR", "Rule CAGR", "Draws' median", "Edge", "Percentile", "p", "Hold worst fall", "Rule worst fall", "Draws' median", "Percentile", "p"])}
<p class="cap">Second null (circular shift of the in-or-out series, every shift from 46 to n−46 weeks, 308 shifts): CAGR percentiles {", ".join(f"{data['books'][b]['shift_pct_cagr']:.1f}" for b in BOOKS)}; drawdown percentiles {", ".join(f"{data['books'][b]['shift_pct_dd']:.1f}" for b in BOOKS)}.</p>
<h3>Before and after cost, and the comparators</h3>
{table(cost_rows, ["Book", "Strategy", "0 bps CAGR", "0 bps worst fall", "20.8 CAGR", "20.8 worst fall", "50 CAGR", "50 worst fall"])}
<p class="cap">The constant mix holds the rule's average share ({100 * au['books']['SCMO_0003']['invested_weeks'] / au['books']['SCMO_0003']['decisions']:.1f}%) in the parent all the time and rebalances weekly; the 50/50 sleeve is the other end. Published NAV (D17) CAGR: {", ".join(f"{b[-4:]} {pc(data['books'][b]['pub_cagr'])}" for b in BOOKS)}.</p>

<h2 id="perbook">Per book</h2><div class="legend">{legend}</div>{curves}
<h2 id="nulls">Null distributions</h2>{hists}
{regime}
<h2 id="robust">Robustness (decides the finding's status, not the verdict)</h2>
{table(rob_rows, ["Book", "Shift null CAGR pct", "Shift null drawdown pct", "C1 at 0 bps", "C1 at 20.8", "C1 at 50", "C1 with LIQUIDCASE cash", "C1 live window only", "Live-only CAGR"])}
<h3>Power</h3>{table(mde_rows, ["Book", "Round trips", "Null SD CAGR (pp)", "MDE CAGR (pp)", "Null SD worst fall (pp)", "MDE worst fall (pp)"])}
<p class="cap">MDE = 2.8 × the SD of the draws (80% power, two-sided 5%). The numbers did not exist when the pre-registration was written; its thresholds do not depend on them.</p>

<h2 id="defs">Definitions</h2>
<ul><li><b>Percentile</b>: (draws worse + 0.5 × draws tied) ÷ draws × 100. <b>p-value</b>: (1 + draws at least as good) ÷ (draws + 1).</li>
<li><b>CAGR</b>: NAV_end^(252 ÷ (sessions − 1)) − 1. <b>Worst fall</b>: the most negative NAV ÷ running peak − 1.</li>
<li><b>Random timing (N4.9)</b>: the rule's in-spells and out-spells reordered; same weeks invested, same number of switches, same spell lengths. 2,000 seeded draws per book and cost.</li>
<li><b>Live window</b>: 2021-11-01 → 2026-08-21, the decisions that were in production.</li></ul>
<p class="meta">Built by <code>tests/T03/report.py</code> from <code>evidence/{E(a.run)}/</code>. Methods: <code>evidence/METHODS.md</code>. Checked by <code>check_page.py</code>.</p>
<script type="application/json" id="page-data">{json.dumps(data)}</script>
<script type="application/json" id="regime-data">{json.dumps(hover, separators=(",", ":"))}</script>
<script type="application/json" id="lines-data">{json.dumps(lines_data, separators=(",", ":"))}</script>
<script>{LINES_JS}</script>
<script>{HOVER_JS}</script>
</main></body></html>"""
    (ev.parent / "report.html").write_text(page, encoding="utf-8")
    print(f"wrote {ev.parent / 'report.html'} ({len(page) / 1e3:.0f} kB)")


if __name__ == "__main__":
    main()
