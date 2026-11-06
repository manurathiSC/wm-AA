"""Build report.html for T06 from shipped evidence only (AGENT.md R10).

    python tests/T06/report.py [--run headline]              writes tests/T06/evidence/report.html
    python tests/T06/report.py --evidence DIR [--out DIR]    another evidence directory (e.g. a synthetic one); the page and
                                                             analysis.log are then looked up and written in --out (default DIR)

Every number on the page is computed here from evidence/<run>/ (decisions.csv, stats.csv, draws.csv, daily_nav.csv, trades.csv,
positions.csv, draw_states.npz, draw_curves_20.8.npz, count_table.json, inputs.csv, audit.json, verify_t06.json) and, for the
gate verdicts, the 'Gates:' line of analysis.log. The same numbers are written into the page's embedded JSON blocks
(page-data, regime-data, lines-data, bars-data) so check_page.py can recompute them independently.
Imports nothing from the engine. Every chart is hoverable (AGENT.md R10): the hover reads the same arrays that draw the chart.
"""
from __future__ import annotations

import argparse
import ast
import html
import json
import math
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
AA = HERE.parents[1]
BOOKS = ["SCMO_0003", "SCMO_0007", "SCMO_0010", "SCMO_0029"]
PRIMARY = 20.8
COSTS = (0.0, PRIMARY, 50.0)
LO = 2
E = html.escape
C10, C9 = "#2a6fdb", "#c9811a"
COL = {"strategy": "#2a6fdb", "hold_parent": "#8a8f98", "constant_mix": "#c9811a", "sleeve_only": "#2f9e6e", "published_D17": "#b04a9b"}
LAB = {"strategy": "Three-index rule", "hold_parent": "Hold the parent", "constant_mix": "Constant mix (same average exposure)",
       "sleeve_only": "50/50 GOLDBEES + cash", "published_D17": "Published NAV (D17)"}


# ── small helpers ─────────────────────────────────────────────────────────────
def rank(x, draws, hb=True):
    tie = np.isclose(draws, x, rtol=1e-12, atol=0)
    worse = ((draws < x) if hb else (draws > x)) & ~tie
    better = ((draws > x) if hb else (draws < x)) & ~tie
    n = len(draws)
    return {"percentile": float((worse.sum() + 0.5 * tie.sum()) / n * 100), "p": float((1 + better.sum() + tie.sum()) / (n + 1)),
            "worse": int(worse.sum()), "tied": int(tie.sum()), "better": int(better.sum()), "draws": int(n)}


def nav_stats(nav):
    yrs = (len(nav) - 1) / 252
    dd = nav / np.maximum.accumulate(nav) - 1
    return {"cagr": float(nav[-1] ** (1 / yrs) - 1), "max_dd": float(dd.min())}


def pc(x, d=1):
    return f"{100 * x:.{d}f}%"


def runs(a):
    a = np.asarray(a)
    cut = np.flatnonzero(a[1:] != a[:-1]) + 1
    st = np.concatenate(([0], cut))
    en = np.concatenate((cut, [len(a)]))
    return [(int(a[i]), int(j - i)) for i, j in zip(st, en)]


def lens(a, v):
    return [n for s, n in runs(a) if s == v]


def dp_table(k, S, lo, hi):
    """c[m][t] = ways to write t as m integers in [lo, hi] (Python ints): c(0,0)=1, c(m,t)=sum_x c(m-1,t-x)."""
    c = [[0] * (S + 1) for _ in range(k + 1)]
    c[0][0] = 1
    for m in range(1, k + 1):
        for t in range(S + 1):
            c[m][t] = sum(c[m - 1][t - x] for x in range(lo, hi + 1) if t - x >= 0)
    return c


def replay(seed_id, ks, S_, bounds, firsts):
    """Replay N4.10 draw `seed_id` from default_rng([6, id]): in-spell parts first, then out-spell parts, each by the cumulative-sum search."""
    rg = np.random.default_rng([6, seed_id])
    steps, res = [], {}
    for name in ("in", "out"):
        k, S, (lo, hi) = ks[name], S_[name], bounds[name]
        c = dp_table(k, S, lo, hi)
        t, parts = S, []
        for m in range(k, 0, -1):
            w = np.array([c[m - 1][t - x] if t - x >= 0 else 0 for x in range(lo, hi + 1)], dtype=float)
            cum = np.cumsum(w)
            u = float(rg.random())
            idx = int(np.searchsorted(cum, u * cum[-1], side="right"))
            x = lo + min(idx, hi - lo)
            steps.append({"spell": name, "part": k - m + 1, "m": m, "t": t, "u": u, "total": int(c[m][t]), "x": x, "ways_x": int(c[m - 1][t - x]), "p": float(w[x - lo] / cum[-1])})
            parts.append(x)
            t -= x
        res[name] = parts
    return steps, res


def fmt_table(rows, cols, cls=""):
    th = "".join(f"<th>{E(c)}</th>" for c in cols)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f'<div class="tw"><table class="{cls}"><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table></div>'


table = fmt_table


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


# ── charts ────────────────────────────────────────────────────────────────────
def svg_lines(series, dates, w=640, h=250, log=True, ylab=""):
    """series: {name: array}; downsampled to every 5th session. Hover: LINES_JS."""
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
    for t in ([0.5, 1, 2, 4, 8, 16, 32] if log else []):
        if allv.min() * 0.97 <= t <= allv.max() * 1.03:
            out.append(f'<line x1="{L}" x2="{w - R}" y1="{y(t):.1f}" y2="{y(t):.1f}" class="grid"/><text x="{L - 4}" y="{y(t) + 3:.1f}" text-anchor="end" class="ax">{t:g}×</text>')
    years = sorted({d.year for d in dates})
    for yr in years[::2]:
        i = int(np.argmax([d.year == yr for d in dates]))
        j = int(np.argmin(np.abs(idx - i)))
        out.append(f'<text x="{x(j):.1f}" y="{h - 6}" text-anchor="middle" class="ax">{yr}</text>')
    for k, v in series.items():
        pts = " ".join(f"{x(j):.1f},{y(v[i]):.1f}" for j, i in enumerate(idx))
        out.append(f'<polyline points="{pts}" fill="none" stroke="{COL[k]}" stroke-width="{2.2 if k == "strategy" else 1.3}" stroke-linejoin="round"/>')
    bot = h - B
    out.append('<g class="lc-hv" style="display:none" pointer-events="none">'
               f'<line class="lc-v" y1="{T}" y2="{bot}" stroke="var(--muted)" stroke-width="1"/>'
               f'<line class="lc-h" x1="{L}" x2="{w - R}" stroke="var(--muted)" stroke-width="1" stroke-dasharray="3 3"/>'
               + "".join(f'<circle class="lc-c" r="3.5" fill="{COL[k]}" stroke="var(--card)" stroke-width="1.5"/>' for k in series)
               + f'<g class="lc-yc"><rect x="0" y="-8" width="{L - 3}" height="16" rx="3" fill="var(--fg)"/><text x="{L - 7}" y="3.5" text-anchor="end" font-size="10" fill="var(--bg)" class="lc-yt"></text></g>'
               f'<g class="lc-xc"><rect y="{h - 19}" width="92" height="16" rx="3" fill="var(--fg)" class="lc-xr"/><text y="{h - 7.5}" text-anchor="middle" font-size="10" fill="var(--bg)" class="lc-xt"></text></g></g>')
    out.append(f'<rect class="lc-ov" x="{L}" y="{T}" width="{w - L - R}" height="{bot - T}" fill="transparent" style="cursor:crosshair;touch-action:none"/>')
    out.append("</svg>")
    data = {"w": w, "h": h, "L": L, "R": R, "T": T, "B": B, "lo": ymin, "hi": ymax, "log": log, "n": len(idx),
            "dates": [dates[i].strftime("%Y-%m-%d (%a)") for i in idx],
            "series": [{"k": k, "label": LAB[k], "col": COL[k], "v": [round(float(v[i]), 4) for i in idx]} for k, v in series.items()]}
    return "".join(out), data


def nice_ticks(hi, k=4):
    s = hi / k
    m = 10 ** math.floor(math.log10(s))
    r = s / m
    st = (1 if r < 1.5 else 2 if r < 3 else 5 if r < 7 else 10) * m
    out, v = [], 0.0
    while v <= hi + 1e-9:
        out.append(v)
        v += st
    return out


def si(v):
    """compact axis number: 1500000 -> 1.5m"""
    for k_, s_ in ((1e12, "tn"), (1e9, "bn"), (1e6, "m"), (1e3, "k")):
        if abs(v) >= k_:
            return f"{v / k_:g}{s_}"
    return f"{v:g}"


def svg_bars(did, edges, series, marks=(), xk="pct", yk="int", w=460, h=190, xticks=None, xtick_fmt=None, extra=None, binlab=None, yunit="draws", L=44):
    """Overlaid bars (one series per null). series: [{k,label,col,v:[counts per bin],n:total,op}]; marks: [{label,x,col,txt,dash}].
    Returns (svg, data). The hover (BARS_JS) reads `data`, which holds the arrays drawn here."""
    R, T, B = 8, 8, 30
    x0, x1 = edges[0], edges[-1]
    ymax = float(max(max(s["v"]) for s in series))
    ticks = nice_ticks(ymax, 4)
    ymax_axis = max(ticks[-1], ymax)
    X = lambda v: L + (w - L - R) * (v - x0) / (x1 - x0)
    Y = lambda v: T + (h - T - B) * (1 - v / ymax_axis)
    o = [f'<svg viewBox="0 0 {w} {h}" class="chart bc" role="img" aria-label="{E(did)}" data-id="{E(did)}">']
    for t in ticks:
        o.append(f'<line x1="{L}" x2="{w - R}" y1="{Y(t):.1f}" y2="{Y(t):.1f}" class="grid"/><text x="{L - 4}" y="{Y(t) + 3:.1f}" text-anchor="end" class="ax">{si(t)}</text>')
    for s in series:
        for i, c in enumerate(s["v"]):
            if c > 0:
                o.append(f'<rect x="{X(edges[i]) + 0.4:.1f}" y="{Y(c):.1f}" width="{max(X(edges[i + 1]) - X(edges[i]) - 0.8, 0.5):.1f}" height="{h - B - Y(c):.1f}" fill="{s["col"]}" opacity="{s.get("op", 0.5)}"/>')
    for m in marks:
        dash = ' stroke-dasharray="3 3"' if m.get("dash") else ""
        o.append(f'<line x1="{X(m["x"]):.1f}" x2="{X(m["x"]):.1f}" y1="{T}" y2="{h - B}" stroke="{m["col"]}" stroke-width="{1.2 if m.get("dash") else 2.4}"{dash}/>')
    for v, lab in (xticks or []):
        o.append(f'<text x="{X(v):.1f}" y="{h - 16}" text-anchor="middle" class="ax">{lab}</text>')
    bot = h - B
    o.append('<g class="bc-hv" style="display:none" pointer-events="none">'
             f'<line class="bc-v" y1="{T}" y2="{bot}" stroke="var(--muted)" stroke-width="1"/>'
             f'<line class="bc-h" x1="{L}" x2="{w - R}" stroke="var(--muted)" stroke-width="1" stroke-dasharray="3 3"/>'
             f'<g class="bc-yc"><rect x="0" y="-8" width="{L - 3}" height="16" rx="3" fill="var(--fg)"/><text x="{L - 7}" y="3.5" text-anchor="end" font-size="10" fill="var(--bg)" class="bc-yt"></text></g>'
             f'<g class="bc-xc"><rect y="{h - 15}" width="74" height="14" rx="3" fill="var(--fg)" class="bc-xr"/><text y="{h - 5}" text-anchor="middle" font-size="10" fill="var(--bg)" class="bc-xt"></text></g></g>')
    o.append(f'<rect class="bc-ov" x="{L}" y="{T}" width="{w - L - R}" height="{bot - T}" fill="transparent" style="cursor:crosshair;touch-action:none"/>')
    o.append("</svg>")
    data = {"w": w, "h": h, "L": L, "R": R, "T": T, "B": B, "x0": x0, "x1": x1, "ymax": ymax_axis, "xk": xk, "yk": yk, "yunit": yunit,
            "edges": [round(float(e), 8) for e in edges], "binlab": binlab, "extra": extra,
            "series": [{"k": s["k"], "label": s["label"], "col": s["col"], "v": [int(c) for c in s["v"]], "n": int(s["n"])} for s in series],
            "marks": [{"label": m["label"], "x": round(float(m["x"]), 8), "txt": m["txt"]} for m in marks]}
    return "".join(o), data


def svg_regime(dates, ser, rule_runs, draw_runs, pair_runs, draw_label, w=760):
    """Growth-of-1 lines (log) on top; below, one strip per timing (filled = holds the parent) and a strip of where they differ."""
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
    for r_, (lab, runs_, fill) in enumerate(rows):
        yy = top + r_ * (rowh + gap)
        out.append(f'<rect x="{L}" y="{yy}" width="{w - L - R}" height="{rowh}" fill="var(--line)" rx="2"/><text x="{L - 6}" y="{yy + rowh - 2}" text-anchor="end" class="ax">{E(lab)}</text>')
        for v, s, e in runs_:
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
    bot = top + 3 * (rowh + gap) - gap
    out.append('<g id="regime-hv" style="display:none" pointer-events="none">'
               f'<line id="hv-v" y1="{T}" y2="{bot}" stroke="var(--muted)" stroke-width="1"/>'
               f'<line id="hv-h" x1="{L}" x2="{w - R}" stroke="var(--muted)" stroke-width="1" stroke-dasharray="3 3"/>'
               + "".join(f'<circle id="hv-c{n}" r="4" fill="{c}" stroke="var(--card)" stroke-width="2"/>' for n, c in enumerate((COL["strategy"], "var(--fg)", COL["hold_parent"])))
               + f'<g id="hv-yc"><rect x="0" y="-8" width="{L - 3}" height="16" rx="3" fill="var(--fg)"/><text x="{L - 7}" y="3.5" text-anchor="end" font-size="10" fill="var(--bg)" id="hv-yt"></text></g>'
               f'<g id="hv-xc"><rect y="{h - 19}" width="70" height="16" rx="3" fill="var(--fg)" id="hv-xr"/><text y="{h - 7.5}" text-anchor="middle" font-size="10" fill="var(--bg)" id="hv-xt"></text></g></g>')
    out.append(f'<rect id="regime-ov" x="{L}" y="{T}" width="{w - L - R}" height="{bot - T}" fill="transparent" style="cursor:crosshair;touch-action:none"/>')
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


# Bar charts (null histograms, spell-length distributions, the sampler's first step): crosshair, an x chip with the value at the pointer,
# a y chip with the count at the pointer, and a tooltip with the bin's edges, every series' count and share, and the marked values.
BARS_JS = """(function(){
var all=JSON.parse(document.getElementById('bars-data').textContent);
function f(k,v){if(k==='si'){var a=Math.abs(v);return a>=1e12?(v/1e12).toFixed(1)+'tn':a>=1e9?(v/1e9).toFixed(1)+'bn':a>=1e6?(v/1e6).toFixed(1)+'m':a>=1e3?(v/1e3).toFixed(1)+'k':Math.round(v)+''}if(k==='pct')return (100*v).toFixed(1)+'%';if(k==='wk')return Math.round(v)+' wk';if(k==='int')return Math.round(v).toLocaleString('en-US');return v.toFixed(4)}
Array.prototype.forEach.call(document.querySelectorAll('svg.bc'),function(svg){
 var d=all[svg.getAttribute('data-id')],fig=svg.parentNode,tip=fig.querySelector('.tip'),g=svg.querySelector('.bc-hv'),ov=svg.querySelector('.bc-ov'),q=function(c){return svg.querySelector(c)};
 var pw=d.w-d.L-d.R,ph=d.h-d.T-d.B,nb=d.edges.length-1;
 function move(e){
  var r=svg.getBoundingClientRect(),k=d.w/r.width,vx=(e.clientX-r.left)*k,vy=(e.clientY-r.top)*k;
  vx=Math.max(d.L,Math.min(d.w-d.R,vx));vy=Math.max(d.T,Math.min(d.T+ph,vy));
  var v=d.x0+(d.x1-d.x0)*(vx-d.L)/pw,b=0;while(b<nb-1&&v>=d.edges[b+1])b++;
  g.style.display='';
  q('.bc-v').setAttribute('x1',vx);q('.bc-v').setAttribute('x2',vx);
  q('.bc-h').setAttribute('y1',vy);q('.bc-h').setAttribute('y2',vy);q('.bc-yc').setAttribute('transform','translate(0,'+vy+')');
  q('.bc-yt').textContent=f(d.yk,d.ymax*(1-(vy-d.T)/ph));
  var xr=q('.bc-xr'),xl=Math.max(0,Math.min(d.w-74,vx-37));xr.setAttribute('x',xl);q('.bc-xt').setAttribute('x',xl+37);q('.bc-xt').textContent=f(d.xk,v);
  var s='<b>'+d.binlab[b]+'</b>';
  for(var n=0;n<d.series.length;n++){var S=d.series[n];s+='<br><i style="background:'+S.col+'"></i>'+S.label+': <b>'+S.v[b].toLocaleString('en-US')+'</b> '+d.yunit+' ('+(100*S.v[b]/S.n).toFixed(2)+'%)'}
  if(d.extra&&d.extra[b])s+='<span class="sub">'+d.extra[b]+'</span>';
  for(var m=0;m<d.marks.length;m++){var M=d.marks[m];s+='<br>'+M.label+': <b>'+f(d.xk,M.x)+'</b> '+M.txt+(M.x>=d.edges[b]&&M.x<d.edges[b+1]?' (in this bin)':'')}
  tip.innerHTML=s;tip.hidden=false;
  var fr=fig.getBoundingClientRect(),px=e.clientX-fr.left+14,py=e.clientY-fr.top+14;
  if(px+tip.offsetWidth>fr.width)px=e.clientX-fr.left-tip.offsetWidth-14;
  if(py+tip.offsetHeight>fr.height)py=Math.max(0,e.clientY-fr.top-tip.offsetHeight-14);
  px=Math.max(0,Math.min(px,fr.width-tip.offsetWidth));tip.style.left=px+'px';tip.style.top=py+'px';
 }
 function out(){g.style.display='none';tip.hidden=true}
 ov.addEventListener('pointermove',move);ov.addEventListener('pointerdown',move);ov.addEventListener('pointerleave',out);
});
})();"""

CSS = """
:root{--bg:#fbfbfa;--fg:#1c1f24;--muted:#6b7280;--card:#ffffff;--line:#e3e5e8;--bar:#c4cad4;--ok:#1b7f4d;--bad:#b3261e;--warn:#a86400}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#14161a;--fg:#e6e8eb;--muted:#9aa1ab;--card:#1b1e23;--line:#2d3138;--bar:#4a5260;--ok:#4cc38a;--bad:#ff7b72;--warn:#e0a43a}}
:root[data-theme=dark]{--bg:#14161a;--fg:#e6e8eb;--muted:#9aa1ab;--card:#1b1e23;--line:#2d3138;--bar:#4a5260;--ok:#4cc38a;--bad:#ff7b72;--warn:#e0a43a}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.55 -apple-system,Segoe UI,Roboto,sans-serif}
main{max-width:980px;margin:0 auto;padding:24px 16px 64px}h1{font-size:26px;line-height:1.2;margin:.2em 0}h2{margin-top:2.2em;font-size:20px;border-top:1px solid var(--line);padding-top:1em}h3{font-size:16px;margin-top:1.6em}
.eyebrow,.meta,.mini,.cap,.ax{color:var(--muted);font-size:12.5px}.tw{overflow-x:auto;margin:.8em 0}table{border-collapse:collapse;font-size:13px;min-width:100%}th,td{padding:5px 8px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}th{color:var(--muted);font-weight:500}td:first-child,th:first-child{text-align:left}
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:10px 12px;margin:10px 0}figcaption{font-size:13px;margin-bottom:4px}.chart{width:100%;height:auto}.grid{stroke:var(--line)}.ax{fill:var(--muted);font-size:10px}
.chip{padding:1px 8px;border-radius:10px;font-weight:600;font-size:12px;border:1px solid currentColor}.ok{color:var(--ok)}.bad{color:var(--bad)}.warn{color:var(--warn)}
.legend{display:flex;flex-wrap:wrap;gap:6px 16px;font-size:12.5px;margin:6px 0}.key i{display:inline-block;width:14px;height:3px;margin-right:6px;vertical-align:middle}
.formula{background:var(--card);border:1px solid var(--line);border-radius:6px;padding:8px 12px;font:12.5px/1.5 ui-monospace,Consolas,monospace;white-space:pre-wrap;overflow-x:auto}.two{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.hv{position:relative}.tip{position:absolute;z-index:5;pointer-events:none;background:var(--card);border:1px solid var(--line);border-radius:6px;padding:6px 9px;font-size:12px;line-height:1.5;white-space:nowrap;box-shadow:0 2px 8px rgba(0,0,0,.18);font-variant-numeric:tabular-nums}.tip b{font-weight:600}.tip i{display:inline-block;width:10px;height:3px;margin-right:6px;vertical-align:middle}.tip .sub{color:var(--muted);white-space:normal;display:block;max-width:300px;margin-top:3px}
.tip.wrap{white-space:normal;width:max-content;max-width:min(300px,92%)}
.answer{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--warn);border-radius:6px;padding:12px 16px}@media (max-width:640px){.two{grid-template-columns:1fr}h1{font-size:22px}}
"""


def read_inputs(path: Path):
    lines = path.read_text(encoding="utf-8").splitlines()
    comment = [l for l in lines if l.startswith("#")]
    asof = None
    for l in comment:
        m = re.search(r"\d{4}-\d{2}-\d{2}", l)
        if m:
            asof = m.group(0)
    df = pd.read_csv(path, comment="#", dtype=str, keep_default_na=False)
    return df, asof


def count_entries(obj, path=()):
    if isinstance(obj, dict):
        if "n_ways" in obj:
            yield path, obj
            return
        for k, v in obj.items():
            yield from count_entries(v, path + (str(k),))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from count_entries(v, path + (str(i),))


def classify(path, ent):
    toks = []
    for p in path:
        toks += re.split(r"[|/ ]", p)
    for f in ("book", "window", "state"):
        if f in ent:
            toks.append(str(ent[f]))
    book = next((t for t in toks if t.startswith("SCMO_")), None)
    win = next((t for t in toks if t in ("full", "live")), None)
    st = next(({"in": "in", "1": "in", "out": "out", "0": "out"}[t.lower()] for t in toks if t.lower() in ("in", "out", "1", "0")), None)
    return book, win, st


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="headline")
    ap.add_argument("--evidence", default=None)
    ap.add_argument("--out", default=None, help="directory of report.html and analysis.log")
    ap.add_argument("--t03", default=str(AA / "tests" / "T03" / "evidence" / "headline"))
    ap.add_argument("--doc", default=str(HERE / "T06.md"))
    ap.add_argument("--books", default=None, help="comma list; for engine smoke runs that hold fewer than the four books")
    a = ap.parse_args()
    if a.books:
        BOOKS[:] = a.books.split(",")
    B7 = "SCMO_0007" if "SCMO_0007" in BOOKS else BOOKS[-1]
    ev = Path(a.evidence) if a.evidence else HERE / "evidence" / a.run
    if a.out:
        logdir = outdir = Path(a.out)
    elif a.evidence:
        logdir = outdir = ev
    else:
        logdir, outdir = HERE, ev.parent
    t03 = Path(a.t03)
    dec = pd.read_csv(ev / "decisions.csv")
    st = pd.read_csv(ev / "stats.csv")
    dr = pd.read_csv(ev / "draws.csv")
    tr = pd.read_csv(ev / "trades.csv")
    nav = pd.read_csv(ev / "daily_nav.csv", parse_dates=["date"])
    pos = pd.read_csv(ev / "positions.csv")
    g4 = pd.read_csv(ev / "g_engine.csv")
    au = json.loads((ev / "audit.json").read_text(encoding="utf-8"))
    ct = json.loads((ev / "count_table.json").read_text(encoding="utf-8"))
    ver = json.loads((ev / "verify_t06.json").read_text(encoding="utf-8")) if (ev / "verify_t06.json").exists() else None
    _z = np.load(ev / "draw_states.npz")
    states = {k_: _z[k_] for k_ in _z.files}  # decompress once
    curves = np.load(ev / "draw_curves_20.8.npz")
    inp, asof_inputs = read_inputs(ev / "inputs.csv")
    if asof_inputs is None:
        asof_inputs = (au.get("data") or {}).get("approved_data_as_of")  # the engine records the As-of date in audit.json
    am = re.search(r"\*\*As of: (\d{4}-\d{2}-\d{2})", (AA / "data" / "APPROVED_DATA.md").read_text(encoding="utf-8"))
    asof_file = am.group(1) if am else None
    logp = logdir / "analysis.log"
    gate_line = None
    if logp.exists():
        mg = re.search(r"^Gates: (\{.*\}) ->", logp.read_text(encoding="utf-8"), re.M)
        gate_line = ast.literal_eval(mg.group(1)) if mg else None  # a dict literal of strings written by analyse.py
    doc = Path(a.doc).read_text(encoding="utf-8")
    sha = doc.split("§1–§3 sha256:** `")[1].split("`")[0]

    S = lambda b, kind="strategy", cost=PRIMARY, win="full", cash="lbes": st[(st.book == b) & (st.window == win) & (st.cash == cash) & (st.cost_bps == cost) & (st.kind == kind)].iloc[0]
    D = lambda b, typ, cost=PRIMARY, win="full", cash="lbes": dr[(dr.book == b) & (dr.window == win) & (dr.cash == cash) & (dr.cost_bps == cost) & (dr.draw_type == typ)].sort_values("draw_id")
    NUL = (("n10", "N4.10"), ("n9", "N4.9"))
    ND = int(len(D("SCMO_0003", "N4.10")))
    rule = {b: dec[dec.book == b].sort_values("j").state.values.astype(int) for b in BOOKS}
    weeks = {b: len(rule[b]) for b in BOOKS}
    rin = {b: lens(rule[b], 1) for b in BOOKS}
    rout = {b: lens(rule[b], 0) for b in BOOKS}
    HI_IN, HI_OUT = max(max(rin[b]) for b in BOOKS), max(max(rout[b]) for b in BOOKS)
    first_dec = {b: dec[dec.book == b].sort_values("j").decision_date.iloc[0] for b in BOOKS}
    last_dec = dec[dec.book == "SCMO_0003"].sort_values("j").decision_date.iloc[-1]
    ctab = {}
    for path, ent in count_entries(ct):
        bk, win, stt = classify(path, ent)
        if bk and win and stt:
            ctab[(bk, win, stt)] = {"k": int(ent.get("k", ent.get("spells_k"))), "S": int(ent.get("S", ent.get("weeks_S"))), "lo": int(ent["lo"]), "hi": int(ent["hi"]), "n_ways": int(ent["n_ways"])}
    cal = {b: nav[(nav.book == b) & (nav.cost_bps == PRIMARY) & (nav.run == "strategy")].sort_values("date").date.reset_index(drop=True) for b in BOOKS}
    wk0s, wsess = {}, {}
    for b in BOOKS:
        d_ = dec[dec.book == b].sort_values("j").reset_index(drop=True)
        n_ = len(cal[b])
        w0 = [0] + [n_ - 1 if pd.isna(t) else int(np.searchsorted(cal[b].values, np.datetime64(pd.Timestamp(t)))) for t in d_.trade_date.iloc[1:]]
        wk0s[b], wsess[b] = np.array(w0), np.array(w0[1:] + [n_ - 1]) - np.array(w0)
    rule_sess = {b: int(rule[b] @ wsess[b]) for b in BOOKS}
    end_date = str(cal["SCMO_0003"].iloc[-1].date())
    start3, start7 = str(cal["SCMO_0003"].iloc[0].date()), str(cal[B7].iloc[0].date())
    live_start = "2021-11-01"

    # ── page data ─────────────────────────────────────────────────────────────
    data = {"run": ev.name, "prereg_sha256": sha, "draws": ND, "as_of_file": asof_file, "as_of_inputs": asof_inputs, "end": end_date, "start": start3, "start_0007": start7,
            "weeks": {b: weeks[b] for b in BOOKS}, "bounds": {"lo": LO, "hi_in": HI_IN, "hi_out": HI_OUT}, "books": {}, "gates": gate_line}
    for b in BOOKS:
        s = S(b)
        bb = {"cagr": float(s.cagr), "max_dd": float(s.max_dd), "end_nav": float(s.end_nav), "trades": int(s.trades), "cost_paid": float(s.cost_paid), "rule_sessions": rule_sess[b],
              "sessions_total": len(cal[b]) - 1, "rule_in": rin[b], "rule_out": rout[b]}
        for nm, typ in NUL:
            n = D(b, typ)
            rc, rd = rank(s.cagr, n.cagr.values), rank(s.max_dd, n.max_dd.values)
            q = np.percentile(n.cagr.values, [5, 95])
            bb.update({f"{nm}_median_cagr": float(n.cagr.median()), f"{nm}_median_dd": float(n.max_dd.median()), f"{nm}_pct_cagr": rc["percentile"], f"{nm}_p_cagr": rc["p"],
                       f"{nm}_pct_dd": rd["percentile"], f"{nm}_p_dd": rd["p"], f"{nm}_worse": rc["worse"], f"{nm}_tied": rc["tied"], f"{nm}_better": rc["better"],
                       f"{nm}_sd_cagr": float(n.cagr.std()), f"{nm}_sd_dd": float(n.max_dd.std()), f"{nm}_mde_cagr_pp": float(280 * n.cagr.std()), f"{nm}_mde_dd_pp": float(280 * n.max_dd.std()),
                       f"{nm}_p5_cagr": float(q[0]), f"{nm}_p95_cagr": float(q[1]),
                       f"{nm}_sess_min": int(n.sessions_invested.min()), f"{nm}_sess_median": float(n.sessions_invested.median()), f"{nm}_sess_max": int(n.sessions_invested.max())})
            for c in (0.0, 50.0):
                sc_, nc_ = S(b, cost=c), D(b, typ, cost=c)
                bb[f"{nm}_pct_cagr_{c:g}"] = rank(sc_.cagr, nc_.cagr.values)["percentile"]
                bb[f"{nm}_pct_dd_{c:g}"] = rank(sc_.max_dd, nc_.max_dd.values)["percentile"]
            live = S(b, win="live")
            bb[f"{nm}_live_pct"] = rank(live.cagr, D(b, typ, win="live").cagr.values)["percentile"]
            liq = S(b, cash="liquidcase")
            bb[f"{nm}_liq_pct"] = rank(liq.cagr, D(b, typ, cash="liquidcase").cagr.values)["percentile"]
        for kind, kk in (("hold_parent", "hold"), ("constant_mix", "mix"), ("sleeve_only", "sleeve")):
            bb[f"{kk}_cagr"], bb[f"{kk}_dd"] = float(S(b, kind).cagr), float(S(b, kind).max_dd)
        pn = nav[(nav.book == b) & (nav.run == "published_D17")].sort_values("date").nav.values
        bb.update({"pub_cagr": nav_stats(pn)["cagr"], "pub_dd": nav_stats(pn)["max_dd"], "live_cagr": float(S(b, win="live").cagr), "liq_cagr": float(S(b, cash="liquidcase").cagr)})
        data["books"][b] = bb
    cnt = lambda key, th=90: int(sum(bool(data["books"][b][key] >= th) for b in BOOKS))
    data["verdict"] = {"C1_N10": cnt("n10_pct_cagr"), "C2_N10": cnt("n10_pct_dd"), "C1_N9": cnt("n9_pct_cagr"), "C2_N9": cnt("n9_pct_dd"),
                       "R3_live_N10": cnt("n10_live_pct"), "R3_live_N9": cnt("n9_live_pct"), "R2_liq_N10": cnt("n10_liq_pct"), "R2_liq_N9": cnt("n9_liq_pct")}
    V = data["verdict"]
    p10, p9 = V["C1_N10"] >= 3 and V["C2_N10"] >= 3, V["C1_N9"] >= 3 and V["C2_N9"] >= 3
    gates_ok = bool(gate_line) and all(v == "PASS" for v in gate_line.values())

    # historical reference (T03's stored N4.9 percentiles; a different window)
    t03ref = {}
    if (t03 / "draws.csv").exists() and (t03 / "stats.csv").exists():
        s3, d3 = pd.read_csv(t03 / "stats.csv"), pd.read_csv(t03 / "draws.csv")
        for b in BOOKS:
            sr = s3[(s3.book == b) & (s3.window == "full") & (s3.cash == "lbes") & (s3.cost_bps == PRIMARY) & (s3.kind == "strategy")].iloc[0]
            nd_ = d3[(d3.book == b) & (d3.window == "full") & (d3.cash == "lbes") & (d3.cost_bps == PRIMARY) & (d3.draw_type == "N4.9")]
            t03ref[b] = {"cagr": float(sr.cagr), "pct_cagr": rank(sr.cagr, nd_.cagr.values)["percentile"], "pct_dd": rank(sr.max_dd, nd_.max_dd.values)["percentile"]}
    data["t03_reference"] = t03ref

    # ── worked example: SCMO_0003 ─────────────────────────────────────────────
    b = "SCMO_0003"
    d = dec[dec.book == b].sort_values("j").reset_index(drop=True)
    j1 = int(d.index[(d.state != d.state.shift()) & (d.index > 0)][0])
    r = d.loc[j1]
    t = tr[(tr.book == b) & (tr.run == "strategy") & (tr.cost_bps == PRIMARY)].reset_index(drop=True)
    tt = t[t.date == r.trade_date].iloc[0]
    held = pos[(pos.book == b) & (pos.cost_bps == PRIMARY) & (pos.run == "strategy") & (pos.date == tt["date"])]
    nv = nav[(nav.book == b) & (nav.cost_bps == PRIMARY) & (nav.run == "strategy")].sort_values("date").reset_index(drop=True)
    k = int(nv.index[nv.date == pd.Timestamp(r.trade_date)][0])
    s0 = S(b)
    Z10, Z9 = states[f"{b}|full|N4.10"], states[f"{b}|full|N4.9"]
    EB = b
    ks = {"in": ctab[(b, "full", "in")]["k"], "out": ctab[(b, "full", "out")]["k"]}
    SS = {"in": ctab[(b, "full", "in")]["S"], "out": ctab[(b, "full", "out")]["S"]}
    bnd = {"in": (LO, ctab[(b, "full", "in")]["hi"]), "out": (LO, ctab[(b, "full", "out")]["hi"])}
    steps, rp = replay(0, ks, SS, bnd, None)
    replay_ok = rp["in"] == lens(Z10[0], 1) and rp["out"] == lens(Z10[0], 0)
    own_count = {nm: int(dp_table(ks[nm], SS[nm], *bnd[nm])[ks[nm]][SS[nm]]) for nm in ("in", "out")}
    x10 = D(b, "N4.10")
    x10 = x10[x10.draw_id == 0].iloc[0]
    x9 = D(b, "N4.9")
    x9 = x9[x9.draw_id == 0].iloc[0]
    rk10, rk9 = rank(s0.cagr, D(b, "N4.10").cagr.values), rank(s0.cagr, D(b, "N4.9").cagr.values)
    data["example"] = {"decision_week": j1, "decision_date": str(r.decision_date), "trade_date": str(r.trade_date), "V": float(tt.V), "traded": float(tt.traded), "cost": float(tt.cost),
                       "nav_after": float(tt.nav_close_after), "sessions": int(s0.sessions), "end_nav": float(s0.end_nav), "cagr": float(s0.cagr), "max_dd": float(s0.max_dd),
                       "k_in": ks["in"], "S_in": SS["in"], "hi_in": bnd["in"][1], "k_out": ks["out"], "S_out": SS["out"], "hi_out": bnd["out"][1],
                       "ways_in": str(own_count["in"]), "ways_out": str(own_count["out"]), "ways_in_table": str(ctab[(b, "full", "in")]["n_ways"]), "ways_out_table": str(ctab[(b, "full", "out")]["n_ways"]),
                       "replay_in": rp["in"], "replay_out": rp["out"], "replay_ok": bool(replay_ok), "steps": steps,
                       "d0_n10_cagr": float(x10.cagr), "d0_n10_dd": float(x10.max_dd), "d0_n10_sessions": int(x10.sessions_invested), "d0_n9_cagr": float(x9.cagr), "d0_n9_dd": float(x9.max_dd),
                       "d0_n9_sessions": int(x9.sessions_invested), "rank10": rk10, "rank9": rk9}

    # ── tables ────────────────────────────────────────────────────────────────
    chip = lambda ok: ('<span class="chip ok">PASS</span>' if ok else '<span class="chip bad">FAIL</span>')
    head_rows = []
    for b in BOOKS:
        x = data["books"][b]
        head_rows.append([E(b), pc(x["hold_cagr"]), pc(x["cagr"]), pc(x["n10_median_cagr"]), f"{100 * (x['cagr'] - x['n10_median_cagr']):+.1f} pp", f"<b>{x['n10_pct_cagr']:.1f}</b>", f"{x['n10_p_cagr']:.3f}",
                          pc(x["n9_median_cagr"]), f"<b>{x['n9_pct_cagr']:.1f}</b>", f"{x['n9_p_cagr']:.3f}"])
    dd_rows = []
    for b in BOOKS:
        x = data["books"][b]
        dd_rows.append([E(b), pc(x["hold_dd"]), pc(x["max_dd"]), pc(x["n10_median_dd"]), f"<b>{x['n10_pct_dd']:.1f}</b>", f"{x['n10_p_dd']:.3f}", pc(x["n9_median_dd"]), f"<b>{x['n9_pct_dd']:.1f}</b>", f"{x['n9_p_dd']:.3f}"])
    cost_rows = []
    for b in BOOKS:
        for kind in ("strategy", "hold_parent", "constant_mix", "sleeve_only"):
            row = [E(b) if kind == "strategy" else "", LAB[kind]]
            for cst in COSTS:
                s = S(b, kind, cst)
                row += [pc(s.cagr), pc(s.max_dd)]
            cost_rows.append(row)
    mde_rows = [[E(b), str(min(int(((rule[b][1:] == 1) & (rule[b][:-1] == 0)).sum()) + int(rule[b][0] == 1), int(((rule[b][1:] == 0) & (rule[b][:-1] == 1)).sum()))), f"{100 * data['books'][b]['n10_sd_cagr']:.2f}", f"{data['books'][b]['n10_mde_cagr_pp']:.1f}", f"{100 * data['books'][b]['n10_sd_dd']:.2f}",
                 f"{data['books'][b]['n10_mde_dd_pp']:.1f}", f"{100 * data['books'][b]['n9_sd_cagr']:.2f}", f"{data['books'][b]['n9_mde_cagr_pp']:.1f}", f"{100 * data['books'][b]['n9_sd_dd']:.2f}", f"{data['books'][b]['n9_mde_dd_pp']:.1f}"] for b in BOOKS]
    rob_rows = []
    for b in BOOKS:
        x = data["books"][b]
        rob_rows.append([E(b)] + [f"{x[f'{nm}_{k_}']:.1f}" for nm in ("n10", "n9") for k_ in ("pct_cagr_0", "pct_cagr", "pct_cagr_50", "pct_dd_0", "pct_dd", "pct_dd_50")])
    rob2_rows = [[E(b)] + [f"{data['books'][b][f'{nm}_liq_pct']:.1f}" for nm in ("n10", "n9")] + [pc(data["books"][b]["liq_cagr"])] + [f"{data['books'][b][f'{nm}_live_pct']:.1f}" for nm in ("n10", "n9")] + [pc(data["books"][b]["live_cagr"])] for b in BOOKS]
    r4_rows = [[E(b)] + [x_ for nm in ("n10", "n9") for x_ in (f"{data['books'][b][f'{nm}_pct_cagr']:.1f}", pc(data["books"][b][f"{nm}_median_cagr"]), f"{100 * data['books'][b][f'{nm}_sd_cagr']:.2f}",
                                                                pc(data["books"][b][f"{nm}_p5_cagr"]), pc(data["books"][b][f"{nm}_p95_cagr"]))] for b in BOOKS]
    t03_rows = [[E(b), pc(t03ref[b]["cagr"]), f"{t03ref[b]['pct_cagr']:.1f}", f"{t03ref[b]['pct_dd']:.1f}"] for b in BOOKS] if t03ref else []
    ses_rows = [[E(b), f"{data['books'][b]['rule_sessions']:,}", f"{data['books'][b]['sessions_total']:,}"] + [x_ for nm in ("n9", "n10") for x_ in (f"{data['books'][b][f'{nm}_sess_min']:,}", f"{data['books'][b][f'{nm}_sess_median']:,.1f}", f"{data['books'][b][f'{nm}_sess_max']:,}")] for b in BOOKS]

    # ── charts: per-book curves ───────────────────────────────────────────────
    curves_html, lines_data = "", {}
    for b in BOOKS:
        ser, dates = {}, None
        for kind in ("strategy", "hold_parent", "constant_mix", "sleeve_only"):
            q = nav[(nav.book == b) & (nav.cost_bps == PRIMARY) & (nav.run == kind)].sort_values("date")
            ser[kind] = q.nav.values
            dates = list(q.date)
        ser["published_D17"] = nav[(nav.book == b) & (nav.run == "published_D17")].sort_values("date").nav.values
        lsvg, ldata = svg_lines(ser, dates, ylab=b)
        lines_data[b] = ldata
        curves_html += (f'<figure class="card hv"><figcaption><b>{E(b)}</b> · growth of 1 from {dates[0].date()} to {dates[-1].date()}, 20.8 bps · rule ends at {data["books"][b]["end_nav"]:.2f}×. '
                        f'Hover (or touch): the crosshair shows the date and the level, and the tooltip lists all five curves at that date (the lines are drawn every 5th session, and the hover snaps to those sessions).</figcaption>'
                        + lsvg + '<div class="tip" hidden></div></figure>')
    legend = "".join(f'<span class="key"><i style="background:{COL[k_]}"></i>{E(LAB[k_])}</span>' for k_ in COL)

    # ── charts: null histograms with both nulls overlaid ──────────────────────
    bars_data, hists = {}, ""
    pct_fmt = lambda v: f"{100 * v:.1f}%"
    for b in BOOKS:
        x = data["books"][b]
        n10, n9 = D(b, "N4.10"), D(b, "N4.9")
        cells = ""
        for what, col, mark, hb, title, note in (("cagr", "cagr", x["cagr"], True, "After-cost CAGR", "right = better"), ("dd", "max_dd", x["max_dd"], True, "Maximum drawdown", "shallower is to the right")):
            a10, a9 = n10[col].values, n9[col].values
            lo_, hi_ = float(min(a10.min(), a9.min(), mark)), float(max(a10.max(), a9.max(), mark))
            pad = (hi_ - lo_) * 0.04
            edges = np.linspace(lo_ - pad, hi_ + pad, 33)
            c10, _ = np.histogram(a10, bins=edges)
            c9, _ = np.histogram(a9, bins=edges)
            marks = [{"label": "The rule", "x": mark, "col": "var(--fg)", "txt": f"percentile {x['n10_pct_' + what]:.1f} vs N4.10, {x['n9_pct_' + what]:.1f} vs N4.9"},
                     {"label": "N4.10 median", "x": float(np.median(a10)), "col": C10, "txt": "(blue, dashed)", "dash": True},
                     {"label": "N4.9 median", "x": float(np.median(a9)), "col": C9, "txt": "(orange, dashed)", "dash": True}]
            did = f"hist|{b}|{what}"
            xt = [(float(v), pct_fmt(v)) for v in np.linspace(lo_, hi_, 5)]
            svg, bd = svg_bars(did, edges, [{"k": "n9", "label": "N4.9 (spell shuffle)", "col": C9, "v": c9, "n": len(a9)}, {"k": "n10", "label": "N4.10 (free lengths)", "col": C10, "v": c10, "n": len(a10)}],
                               marks=marks, xk="pct", yk="int", xticks=xt, binlab=[f"{pct_fmt(edges[i])} to {pct_fmt(edges[i + 1])}" for i in range(32)], yunit="draws")
            bars_data[did] = bd
            cells += f'<div class="hv"><div class="mini">{title} ({note}; black = the rule, dashed = medians)</div>{svg}<div class="tip wrap" hidden></div></div>'
        hists += (f'<figure class="card"><figcaption><b>{E(b)}</b> · {ND:,} draws of each null, 20.8 bps, {first_dec[b]} → {end_date}</figcaption><div class="two">{cells}</div></figure>')

    # ── charts: spell-length distributions ────────────────────────────────────
    lenhtml = ""
    for b in BOOKS:
        cells = ""
        for nm, v_, hi_, kk in (("in", 1, HI_IN, "k_in"), ("out", 0, HI_OUT, "k_out")):
            A10, A9 = states[f"{b}|full|N4.10"], states[f"{b}|full|N4.9"]
            l10 = np.array([x_ for i in range(A10.shape[0]) for x_ in lens(A10[i], v_)])
            l9 = np.array([x_ for i in range(A9.shape[0]) for x_ in lens(A9[i], v_)])
            edges = np.arange(LO, hi_ + 2) - 0.5
            c10, _ = np.histogram(l10, bins=edges)
            c9, _ = np.histogram(l9, bins=edges)
            rl = rin[b] if nm == "in" else rout[b]
            extra = [(f"The rule has {rl.count(x_)} {nm}-spell(s) of exactly this length" if rl.count(x_) else None) for x_ in range(LO, hi_ + 1)]
            did = f"len|{b}|{nm}"
            svg, bd = svg_bars(did, edges, [{"k": "n9", "label": "N4.9 (= the rule's own lengths)", "col": C9, "v": c9, "n": len(l9)}, {"k": "n10", "label": "N4.10 (free lengths)", "col": C10, "v": c10, "n": len(l10)}],
                               marks=[], xk="wk", yk="int", w=380, h=170, xticks=[(float(v), str(v)) for v in range(LO, hi_ + 1, 8 if hi_ > 30 else 6)], extra=extra,
                               binlab=[f"{x_} weeks" for x_ in range(LO, hi_ + 1)], yunit="spells")
            bars_data[did] = bd
            cells += (f'<div class="hv"><div class="mini">{nm}-spell lengths in weeks ({LO} to {hi_}); the rule\'s: {", ".join(map(str, rl))}</div>{svg}<div class="tip wrap" hidden></div></div>')
        lenhtml += f'<figure class="card"><figcaption><b>{E(b)}</b> · every spell of {ND:,} draws, full window {first_dec[b]} → {end_date}</figcaption><div class="two">{cells}</div></figure>'

    # ── chart: the sampler's first step (draw 0, first in-spell) ──────────────
    s_first = steps[0]
    c_ = dp_table(ks["in"], SS["in"], *bnd["in"])
    xs = list(range(LO, bnd["in"][1] + 1))
    wv = [c_[ks["in"] - 1][SS["in"] - x_] if SS["in"] - x_ >= 0 else 0 for x_ in xs]
    edges = np.arange(LO, bnd["in"][1] + 2) - 0.5
    smark = [{"label": f"Draw 0 picked", "x": float(s_first["x"]), "col": "var(--fg)", "txt": f"(u = {s_first['u']:.6f}; P = {s_first['p']:.4f})"}]
    ssvg, sbd = svg_bars("sampler|first", edges, [{"k": "w", "label": "ways to finish after this length", "col": C10, "v": wv, "n": int(sum(wv)), "op": 0.7}], marks=smark, xk="wk", yk="si", w=520, h=190, L=56,
                         xticks=[(float(v), str(v)) for v in range(LO, bnd["in"][1] + 1, 8)], binlab=[f"first in-spell = {x_} weeks" for x_ in xs],
                         extra=[f"c({ks['in'] - 1}, {SS['in']} - {x_}) = {wv[i]:,} of c({ks['in']}, {SS['in']}) = {int(sum(wv)):,} ways" for i, x_ in enumerate(xs)], yunit="ways")
    bars_data["sampler|first"] = sbd
    data["sampler_first"] = {"xs": xs, "weights": [int(v) for v in wv]}

    # ── the highest-CAGR N4.10 draw against the rule (SCMO_0003) ──────────────
    bb = "SCMO_0003"
    nbb = D(bb, "N4.10")
    bbest = nbb.loc[nbb.cagr.idxmax()]
    bid = int(bbest.draw_id)
    rs_ = rule[bb].astype(int)
    ds_ = states[f"{bb}|full|N4.10"][bid].astype(int)
    bcurve = curves[f"{bb}|N4.10_{bid}"].astype(float)
    qn = lambda kind, cost: nav[(nav.book == bb) & (nav.cost_bps == cost) & (nav.run == kind)].sort_values("date")
    rq = qn("strategy", PRIMARY).reset_index(drop=True)
    bdates = list(rq.date)
    nses = len(bdates)
    pnav, snav = qn("hold_parent", 0.0).nav.values, qn("sleeve_only", 0.0).nav.values
    assert len(ds_) == len(rs_) and len(bcurve) == nses
    assert abs(bcurve[-1] / float(bbest.end_nav) - 1) < 1e-5
    wk0, wk1 = list(wk0s[bb]), list(wk0s[bb][1:]) + [nses - 1]
    code = 2 * rs_ + ds_
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
    assert abs(np.prod(list(cls_p.values())) / pnav[-1] * pnav[0] - 1) < 1e-9
    ser_b = {"hold_parent": pnav, "draw": bcurve, "strategy": rq.nav.values}
    st_rule, st_draw, tip_ix = np.zeros(nses, int), np.zeros(nses, int), np.zeros(nses, int)
    for j_ in range(len(rs_)):
        st_rule[wk0[j_]:wk1[j_]], st_draw[wk0[j_]:wk1[j_]] = rs_[j_], ds_[j_]
    for r_, (c_, s_, e_, tip) in enumerate(pair_runs):
        tip_ix[s_:e_] = r_
    st_rule[-1], st_draw[-1], tip_ix[-1] = st_rule[-2], st_draw[-2], tip_ix[-2]
    hover = {"dates": [d_.strftime("%Y-%m-%d (%a)") for d_ in bdates], "rule": [round(float(v_), 4) for v_ in rq.nav.values], "draw": [round(float(v_), 4) for v_ in bcurve],
             "parent": [round(float(v_), 4) for v_ in pnav], "rs": st_rule.tolist(), "ds": st_draw.tolist(), "tip": tip_ix.tolist(), "tips": [p_[3] for p_ in pair_runs], "draw_label": f"Draw {bid}"}
    cls_rows = [[CODE[c_], str(cls_w[c_]), pr(cls_p[c_]), pr(cls_s[c_]), f"{100 * (cls_p[c_] - cls_s[c_]):+.1f} pp"] for c_ in (3, 0, 1, 2)]
    wrong = lambda c_: sum(1 for s in span_stats if s[0] == c_ and s[4] != ("draw" if c_ == 1 else "rule"))
    n1, n2 = sum(1 for s in span_stats if s[0] == 1), sum(1 for s in span_stats if s[0] == 2)
    spr, spd = runs(rs_), runs(ds_)
    ln = lambda s_, v_: [n_ for x_, n_ in s_ if x_ == v_]
    ent = lambda a_: int(((a_[1:] == 1) & (a_[:-1] == 0)).sum()) + int(a_[0] == 1)
    ext = lambda a_: int(((a_[1:] == 0) & (a_[:-1] == 1)).sum())
    ses_r = sum(wk1[j_] - wk0[j_] for j_ in range(len(rs_)) if rs_[j_] == 1)
    ses_d = sum(wk1[j_] - wk0[j_] for j_ in range(len(ds_)) if ds_[j_] == 1)
    nw = len(rs_)
    fl = lambda ok, txt="held": f'<span class="chip ok">{txt}</span>' if ok else f'<span class="chip warn">{txt}</span>'
    in_ok = all(LO <= x_ <= HI_IN for x_ in ln(spd, 1)) and sum(ln(spd, 1)) == sum(ln(spr, 1))
    out_ok = all(LO <= x_ <= HI_OUT for x_ in ln(spd, 0)) and sum(ln(spd, 0)) == sum(ln(spr, 0))
    hold_tab = [
        [f"Weeks invested (of {nw})", f"{rs_.sum()} ({pc(rs_.mean(), 2)})", f"{ds_.sum()} ({pc(ds_.mean(), 2)})", fl(rs_.sum() == ds_.sum())],
        [f"Sessions invested (of {nses - 1:,})", f"{ses_r} ({pc(ses_r / (nses - 1), 2)})", f"{ses_d} ({pc(ses_d / (nses - 1), 2)})", fl(ses_r == ses_d, "held" if ses_r == ses_d else f"not held: differs by {abs(ses_r - ses_d)}")],
        ["In-spells · out-spells", f"{len(ln(spr, 1))} · {len(ln(spr, 0))}", f"{len(ln(spd, 1))} · {len(ln(spd, 0))}", fl((len(ln(spr, 1)), len(ln(spr, 0))) == (len(ln(spd, 1)), len(ln(spd, 0))))],
        ["Entries (0→1) · exits (1→0)", f"{ent(rs_)} · {ext(rs_)}", f"{ent(ds_)} · {ext(ds_)}", fl((ent(rs_), ext(rs_)) == (ent(ds_), ext(ds_)))],
        ["First state", "sleeve" if rs_[0] == 0 else "parent", "sleeve" if ds_[0] == 0 else "parent", fl(rs_[0] == ds_[0])],
        ["In-spell lengths (weeks), in order", ", ".join(map(str, ln(spr, 1))), ", ".join(map(str, ln(spd, 1))), fl(in_ok, f"free: sum equal, each in [{LO}, {HI_IN}]" if in_ok else "OUT OF BOUNDS")],
        ["Out-spell lengths (weeks), in order", ", ".join(map(str, ln(spr, 0))), ", ".join(map(str, ln(spd, 0))), fl(out_ok, f"free: sum equal, each in [{LO}, {HI_OUT}]" if out_ok else "OUT OF BOUNDS")],
        ["Timing and lengths of the spells", "the rule's own", "drawn from the allowed tuples", '<span class="chip">randomised</span>'],
    ]
    rsvg, geom = svg_regime(bdates, ser_b, rule_runs, draw_runs, pair_runs, f"Draw {bid}")
    hover.update(geom)
    data["best_draw"] = {"book": bb, "draw_id": bid, "cagr": float(bbest.cagr), "end_nav": float(bbest.end_nav), "rule_cagr": data["books"][bb]["cagr"], "weeks_both_in": cls_w[3], "weeks_both_out": cls_w[0],
                         "weeks_draw_only": cls_w[1], "weeks_rule_only": cls_w[2], "spans_draw_only": n1, "spans_rule_only": n2, "weeks_invested_rule": int(rs_.sum()), "weeks_invested_draw": int(ds_.sum()),
                         "sessions_invested_rule": int(ses_r), "sessions_invested_draw": int(ses_d), "sessions_span": int(nses - 1), "in_spells": len(ln(spr, 1)), "out_spells": len(ln(spr, 0)),
                         "entries": ent(rs_), "exits": ext(rs_), "draw_in": ln(spd, 1), "draw_out": ln(spd, 0), "pct_vs_n10": data["books"][bb]["n10_pct_cagr"]}
    regime = (f'<h2 id="regime">The highest-return N4.10 draw against the rule ({bb})</h2>'
              f'<p>The right-hand end of the {bb} N4.10 CAGR histogram above is draw {bid}: CAGR {pc(float(bbest.cagr))} (end value {float(bbest.end_nav):.1f}×), against the rule\'s {pc(data["books"][bb]["cagr"])} ({data["books"][bb]["end_nav"]:.1f}×). '
              f'It holds the parent for the same {int(bbest.invested_weeks)} weeks and switches the same number of times as the rule, but its spell lengths are its own. '
              f'Its states are row {bid} of <code>evidence/{E(ev.name)}/draw_states.npz</code>, key <code>{bb}|full|N4.10</code> (read straight from the file, no rebuild), and its curve is <code>draw_curves_20.8.npz</code> key <code>{bb}|N4.10_{bid}</code>.</p>'
              f'<h3>What N4.10 holds, and what it randomises, for this draw</h3>'
              + table(hold_tab, ["Dimension", "The rule", f"Draw {bid}", "Held?"])
              + f'<p class="cap">Weeks invested, spell counts, entries and exits and the first state are held exactly (gate V3); every spell\'s length and so its position are drawn, each length within its bounds and the in- and out-lengths summing to the rule\'s totals. '
                f'Sessions are not held exactly: a week has 3 to 5 sessions, so moving a spell changes how many sessions it covers. Here the two differ by {abs(ses_r - ses_d)} of {nses - 1:,} sessions ({100 * abs(ses_r - ses_d) / (nses - 1):.2f} pp of the window).</p>'
              f'<div class="legend"><span class="key"><i style="background:{COL["strategy"]}"></i>Three-index rule</span><span class="key"><i style="background:var(--fg)"></i>Draw {bid}</span>'
              f'<span class="key"><i style="background:{COL["hold_parent"]}"></i>Hold the parent</span>'
              f'<span class="key"><i style="background:{COL["strategy"]};height:10px;opacity:.5"></i>only the rule holds the parent</span>'
              f'<span class="key"><i style="background:var(--fg);height:10px;opacity:.4"></i>only the draw holds the parent</span></div>'
              f'<figure class="card hv"><figcaption><b>{bb}</b> · growth of 1 from {bdates[0].date()} to {bdates[-1].date()}, 20.8 bps (log scale); the grey line is the parent held throughout, before cost. '
              f'Strips: filled = holds the parent that week, empty = in the 50/50 sleeve. Hover (or touch) anywhere on the chart: the crosshair shows the date on the x-axis and the level on the y-axis, and the tooltip lists every value drawn at that date.</figcaption>'
              + rsvg + '<div id="regime-tip" class="tip" hidden></div></figure>'
              f'<h3>Weeks by what the two did</h3>'
              + table(cls_rows, ["The two timings", "Weeks", "Parent, compounded over these weeks", "Sleeve, same weeks", "Parent minus sleeve"])
              + f'<p>They agree in {cls_w[3] + cls_w[0]} of {len(code)} weeks and differ in {cls_w[1] + cls_w[2]}, in {n1 + n2} separate stretches. '
                f'In the stretches only the draw held the parent, the parent beat the sleeve in {n1 - wrong(1)} of {n1}; in the stretches only the rule held it, the parent beat the sleeve in {n2 - wrong(2)} of {n2}.</p>'
              + '<h3>Every stretch where they differ</h3>'
              + table(span_rows, ["From", "To", "Weeks", "Holds the parent", "Parent", "Sleeve", "Parent minus sleeve", "Right call"])
              + '<p class="cap">Returns are close to close between trade dates, before cost, and compounded within each stretch, so the stretches explain the gap between the two paths but do not add up exactly to the CAGR difference. '
                '"Right call" is the timing that was in the better of parent and sleeve over the stretch. '
                f'Draw {bid} is the best of {len(nbb):,} N4.10 draws, so it is the extreme of the null by construction, not a rival rule.</p>')

    # ── the worked example html ───────────────────────────────────────────────
    b = EB
    ex = data["example"]
    nvw = nv.loc[k - 2:k + 2]
    held_rows = [[E(str(h_.instrument)), f"{h_.units:.6f}"] for h_ in held.head(6).itertuples()]
    ex_rows = [[str(j_), str(d.decision_date.iloc[j_]), str(int(rule[b][j_])), str(int(Z9[0][j_])), str(int(Z10[0][j_]))] for j_ in range(20)]
    step_rows = [[s_["spell"], str(s_["part"]), str(s_["m"]), str(s_["t"]), f"{s_['u']:.6f}", f"{s_['total']:,}", f"<b>{s_['x']}</b>", f"{s_['ways_x']:,}", f"{100 * s_['p']:.2f}%"] for s_ in steps]
    g4rows = [[E(r_.book), f"{r_.cagr_gap_pp_yr:+.3f}", r_.overall, str(r_.worst_year), f"{r_.worst_year_gap_pp:+.3f}", r_.yearly,
               (f"{r_.window_first} → {r_.window_last}" if hasattr(r_, "window_first") else "")] for r_ in g4.itertuples()]
    gate_desc = {"V1": "verify_t06.py shares no code with the engine" + (f": {ver['gate_compared']:,} comparisons, {ver.get('gate_failures_and_missing')} failures, a corrupted copy is caught: {ver.get('selftest', {}).get('detected')}" if ver else ""),
                 "V2": "every decision reads Master rows dated on or before it; every trade is on a later session",
                 "V3": "both nulls hold their tables: weeks, first state, spell counts and sums; N4.9 sorted lengths; N4.10 bounds",
                 "V4": "decisions and NAVs equal T03's on the overlap; always-in reproduces the published NAV within G0",
                 "V5": "the sampler: chi-square on the small case, DP count equals inclusion-exclusion, mean lengths at each position"}
    gate_rows = [[f"{k_} {n_}", f'<span class="chip {"ok" if (gate_line or {}).get(k_) == "PASS" else "bad"}">{(gate_line or {}).get(k_, "NOT RUN")}</span>', E(gate_desc[k_])]
                 for k_, n_ in (("V1", "independent check"), ("V2", "point in time"), ("V3", "the nulls hold their tables"), ("V4", "regression to T03, always-in"), ("V5", "the sampler is exact"))]
    inp_rows = [[E(r_.file), E(r_.through), E(r_.approved_row), E(r_.sha256[:16])] for r_ in inp.itertuples()]
    data["inputs"] = [{"file": r_.file, "through": r_.through, "approved_row": r_.approved_row, "sha16": r_.sha256[:16]} for r_ in inp.itertuples()]

    if not gates_ok:
        lead = "A validity gate failed or analysis.log is missing: do not read the results below."
    elif p10 and p9:
        lead = "Yes: the switch beats randomly timed versions of itself even when their spell lengths are free."
    elif p10:
        lead = "Yes under N4.10, but N4.9 does not agree on this window."
    elif p9:
        lead = "No under the free-length null: the edge under N4.9 depends on the rule's own spell lengths."
    elif V["C1_N10"] >= 3 or V["C2_N10"] >= 3:
        lead = "Partly."
    else:
        lead = "No."
    answer = (f'<div class="answer"><p><b>{lead}</b> Holding the parent only when the Nifty 100, Midcap 100 and Smallcap 100 are all BUY, and a 50/50 GOLDBEES and cash sleeve otherwise, '
              f'against randomly timed versions of itself with the same number of switches and the same weeks invested, on {start3} → {end_date}, after 20.8 bps. '
              f'Against N4.10 (free spell lengths, decides): return beats the 90th percentile in {V["C1_N10"]} of 4 books and the depth of the worst fall in {V["C2_N10"]} of 4 (pre-registered pass: 3 of 4 each). '
              f'Against N4.9 (the rule\'s own lengths, re-run on this window): {V["C1_N9"]} of 4 and {V["C2_N9"]} of 4.</p>'
              f'<p>The catch: on the live decisions only ({live_start} → {end_date}) return beats the 90th percentile in {V["R3_live_N10"]} of 4 books against N4.10; the decisions before 2021-11 are a backfill by the production code; '
              f'the rule was chosen after seeing 2014-2026 results; the bounds of N4.10 were chosen after seeing T03\'s draw 445; and the weeks added since the freeze of T03 (2026-08-24 → {end_date}) hold one switch, so every result here is in-sample and PROVISIONAL.</p></div>')
    t03_html = (("<p>Historical reference, <b>a different window</b> (2019-01-02 → 2026-08-21, T03's stored N4.9 draws, 20.8 bps; not comparable draw for draw; no pass mark):</p>"
                 + table(t03_rows, ["Book", "T03 rule CAGR", "T03 N4.9 CAGR percentile", "T03 N4.9 drawdown percentile"])) if t03_rows else "")
    rt_n = min(int(((rule[EB][1:] == 1) & (rule[EB][:-1] == 0)).sum()) + int(rule[EB][0] == 1), int(((rule[EB][1:] == 0) & (rule[EB][:-1] == 1)).sum()))
    steps_chip = '<span class="chip ok">replay equals the stored draw</span>' if replay_ok else '<span class="chip bad">REPLAY DIFFERS from the stored draw</span>'
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>T06 free-length timing null</title><style>{CSS}</style></head><body><main>
<p class="eyebrow">AA · T06 · timing rule · pre-registration sha256 {E(sha[:12])} · data: APPROVED_DATA.md as of {E(str(asof_file))}</p>
<h1>Does the three-index switch still choose <em>when</em> to hold the parent better than chance when the random timings may use any spell lengths?</h1>
<p class="meta">{start3} → {end_date} ({B7} from {start7}) · four parents of the AA books · decisions every Friday, trades next session at OHLC4 · 10.4 bps a side · {ND:,} draws per book, cost and null · every number is computed from <code>evidence/{E(ev.name)}/</code></p>
<h2 id="answer">The answer</h2>{answer}
{table([[E(b), pc(data['books'][b]['cagr']), f"{data['books'][b]['n10_pct_cagr']:.1f}", f"{data['books'][b]['n10_p_cagr']:.3f}", f"{data['books'][b]['n9_pct_cagr']:.1f}", pc(data['books'][b]['max_dd']), f"{data['books'][b]['n10_pct_dd']:.1f}", f"{data['books'][b]['n10_p_dd']:.3f}", f"{data['books'][b]['n9_pct_dd']:.1f}", pc(data['books'][b]['live_cagr']), f"{data['books'][b]['n10_live_pct']:.1f}"] for b in BOOKS],
        ["Book", "Rule CAGR", "CAGR pct vs N4.10", "p", "CAGR pct vs N4.9", "Rule worst fall", "Drawdown pct vs N4.10", "p", "Drawdown pct vs N4.9", "Live-only CAGR", "Live-only pct vs N4.10"])}
<p class="cap">Percentile = share of the {ND:,} draws the rule beats (ties count half). Pass mark: 90 in at least 3 of 4 books, against N4.10. After 20.8 bps round-trip cost. Full window {start3} → {end_date} ({B7} from {start7}); live-only = {live_start} → {end_date}. The four books have the same in-or-out decisions, so "3 of 4" is a consistency check, not four tests.</p>
<div class="tw"><table><tbody><tr><td>C1 timing (return), N4.10</td><td>{chip(V['C1_N10'] >= 3)} {V['C1_N10']} of 4</td><td>N4.9 beside it: {V['C1_N9']} of 4</td></tr><tr><td>C2 protection (worst fall), N4.10</td><td>{chip(V['C2_N10'] >= 3)} {V['C2_N10']} of 4</td><td>N4.9 beside it: {V['C2_N9']} of 4</td></tr></tbody></table></div>
<h3>What to be careful about</h3><ul>
<li><b>The null is "same number of switches and same weeks in the market, placed at random".</b> A pass says the rule's timing is better than random placement, not that it is better than holding the parent. It was out of the market in about half the weeks, so compare with the constant mix below.</li>
<li><b>Nothing is out of sample.</b> The rule was chosen after seeing 2014-2026. Decisions before 2021-11 are the production code run backwards. On the live decisions only, return is {V['R3_live_N10']} of 4 at the 90th percentile against N4.10.</li>
<li><b>{rt_n} round trips per book</b> is all the evidence there is. The smallest return edge detectable at 80% power against N4.10 is {min(data['books'][b]['n10_mde_cagr_pp'] for b in BOOKS):.0f} to {max(data['books'][b]['n10_mde_cagr_pp'] for b in BOOKS):.0f} pp a year.</li>
<li><b>The books are one market.</b> {B7}'s return percentile against N4.10 is {data['books'][B7]['n10_pct_cagr']:.1f}.</li></ul>

<h2 id="data">The data</h2>
<p>Each parent's NAV is rebuilt every day from its own stocks (Eikon prices, price return, Polyplex's special dividend corrected), not read from a file. The published NAV (D17) gives the calendar and a check: the engine's always-invested book reproduces it within the pre-registered tolerance. Every file below is an APPROVED row of <code>data/APPROVED_DATA.md</code>, whose "As of" date is <b>{E(str(asof_file))}</b> (the run recorded {E(str(asof_inputs))}). No price after {end_date} is read.</p>
<p><b>Periods.</b> <i>Full window</i>: {start3} → {end_date} ({B7} {start7} → {end_date}), {weeks['SCMO_0003']} weekly decisions ({B7} {weeks[B7]}). <i>Live window</i>: {live_start} → {end_date}, the decisions that were in production.</p>
{table(inp_rows, ["File (relative to AA/)", "Through", "Approved row", "sha256 (first 16)"])}
<p class="cap">Caveats, disclosed: (1) the LBES file's rows before 2026-08-10 have no recorded source (F-AA-D09); the rows after are LIQUIDCASE returns chained as level[t] = level[t-1] × (1 + r[t]) and run about 0.5 pp/yr rich against LIQUIDBEES (F-AA-D13). (2) The window ends inside the last approved basket (SCMO_0003 2026-09-10, the others 2026-09-16); the next rebalance is expected about mid-December 2026. (3) The weeks 2026-08-24 → {end_date} follow T03's freeze and hold one switch, an exit, so they add almost no evidence for or against timing. (4) The decisions before 2021-11 are a backfill by the production code. (5) The MCX de-spike file ends 2026-09-28; later GOLDBEES fills use the raw OHLC4. (6) The rule was chosen after seeing the data, and N4.10's bounds after seeing T03's draw 445.</p>
<p><b>Always-in against the published NAV</b> (gate V4):</p>
{table(g4rows, ["Book", "CAGR gap vs published (pp/yr)", "Within ±0.25", "Worst calendar year", "Gap (pp)", "Within ±0.5", "Window of the always-in book"])}
<p><b>Validity gates</b> (from <code>analysis.log</code>; the page is only to be read if all five pass):</p>
{table(gate_rows, ["Gate", "Result", "What it checks"])}

<h2 id="one">One backtest, end to end ({b}, 20.8 bps, {start3} → {end_date})</h2>
<p><b>1. The decision.</b> On Friday {E(ex['decision_date'])} (week {ex['decision_week']}) the latest weekly rows of the three index files read Nifty 100 {E(str(r.sign_Nifty100))}, Midcap 100 {E(str(r.sign_MC100))}, Smallcap 100 {E(str(r.sign_SC100))}. All three are BUY, so the target is the parent; last week it was the sleeve.</p>
<div class="formula">state(d) = IN  if SIGN_Nifty100 = SIGN_MC100 = SIGN_SC100 = BUY (latest row dated on or before d), else OUT
IN  → 100% parent basket        OUT → 50% GOLDBEES + 50% cash</div>
<p><b>2. The trade.</b> On the next session, {E(ex['trade_date'])}, at the (open+high+low+close)/4 of every instrument the book sells the sleeve and buys the basket in force. Value before: {ex['V']:.6f}; value traded (both sides): {ex['traded']:.6f}; cost = traded × 20.8 ÷ 2 ÷ 10,000 = {ex['cost']:.6f}.</p>
<div class="formula">traded = Σ |target value − held value|        cost = traded × cost_bps ÷ 2 ÷ 10,000
new units = target value × (V − cost) ÷ V ÷ fill price</div>
<p><b>3. Units.</b> After the trade the book holds, among others:</p>{table(held_rows, ["Instrument", "Units"])}
<p><b>4. Daily value.</b> NAV(t) = Σ units × close(t) over stocks, GOLDBEES and cash. Around the trade:</p>
{table([[str(r_.date.date()), f"{r_.nav:.6f}"] for r_ in nvw.itertuples()], ["Date", "NAV"])}
<p><b>5. Statistics.</b> The path runs from 1.000000 on {nv.date.iloc[0].date()} to {ex['end_nav']:.6f} on {nv.date.iloc[-1].date()}: {ex['sessions']} sessions, years = ({ex['sessions']} − 1) ÷ 252 = {(ex['sessions'] - 1) / 252:.4f}, CAGR = {ex['end_nav']:.4f}^(1 ÷ {(ex['sessions'] - 1) / 252:.4f}) − 1 = <b>{pc(ex['cagr'], 2)}</b>, worst fall {pc(ex['max_dd'], 2)}.</p>
<p><b>6. The real series, an N4.9 draw and an N4.10 draw.</b> The rule's path is {len(rin[b]) + len(rout[b])} spells: {len(rin[b])} in (lengths {", ".join(map(str, rin[b]))}, sum {sum(rin[b])}) and {len(rout[b])} out (lengths {", ".join(map(str, rout[b]))}, sum {sum(rout[b])}), starting {"in" if rule[b][0] else "out"}. The first 20 weekly states (1 = parent, 0 = sleeve) of the rule, of N4.9 draw 0 (the spells reordered; seed <code>default_rng([3, 0])</code>) and of N4.10 draw 0 (new lengths; seed <code>default_rng([6, 0])</code>):</p>
{table(ex_rows, ["Week", "Date", "Rule", "N4.9 draw 0", "N4.10 draw 0"])}
<p><b>7. How one N4.10 draw is made.</b> It keeps the {ex['k_in']} in-spells and {ex['k_out']} out-spells, the first state ({"in" if rule[b][0] else "out"}) and the totals ({ex['S_in']} weeks in, {ex['S_out']} out), and draws every length as an integer from {LO} to {ex['hi_in']} (in) or {LO} to {ex['hi_out']} (out; 2 weeks = 14 days; the bounds are the rule's longest spells), every allowed set of lengths equally likely. With c(m, t) the number of ways to write t weeks as m lengths in the bounds, c(0, 0) = 1 and c(m, t) = Σ over x of c(m − 1, t − x), the parts are drawn one at a time: with m parts and t weeks left, P(length = x) = c(m − 1, t − x) ÷ c(m, t). The uniform number u is <code>rng.random()</code> and the length is the first x whose cumulative weight exceeds u × c(m, t). In-spell parts come first, then out-spell parts, from the same generator.</p>
<div class="formula">allowed in-tuples  c({ex['k_in']}, {ex['S_in']}) = {int(ex['ways_in']):,}   (count_table.json: {int(ex['ways_in_table']):,})
allowed out-tuples c({ex['k_out']}, {ex['S_out']}) = {int(ex['ways_out']):,}   (count_table.json: {int(ex['ways_out_table']):,})</div>
<p>The first step of draw 0, in-spell 1: m = {ex['k_in']} parts and t = {ex['S_in']} weeks left, so the {len(xs)} candidate lengths {LO} … {ex['hi_in']} have weights c({ex['k_in'] - 1}, {ex['S_in']} − x). u = {s_first['u']:.6f}; u × c({ex['k_in']}, {ex['S_in']}) = {s_first['u'] * s_first['total']:,.0f} falls in the weight of length {s_first['x']}, so the first in-spell is {s_first['x']} weeks.</p>
<figure class="card hv"><figcaption>Weights of the candidate first in-spell lengths for draw 0 (m = {ex['k_in']}, t = {ex['S_in']}); the black line is the length drawn. Hover: the crosshair shows the length and the weight at the pointer, the tooltip the weight and its share of c({ex['k_in']}, {ex['S_in']}).</figcaption>{ssvg}<div class="tip wrap" hidden></div></figure>
<p>All {len(steps)} steps of draw 0, replayed here from the seed with the same rule: {steps_chip}.</p>
{table(step_rows, ["Spell", "Part", "Parts left m", "Weeks left t", "u", "c(m, t)", "Length drawn", "c(m−1, t−x)", "P(x)"])}
<p>Draw 0's in-spell lengths are {", ".join(map(str, lens(Z10[0], 1)))} (the rule's: {", ".join(map(str, rin[b]))}) and its out-spell lengths {", ".join(map(str, lens(Z10[0], 0)))} (the rule's: {", ".join(map(str, rout[b]))}). It earns {pc(ex['d0_n10_cagr'], 2)} a year with a worst fall of {pc(ex['d0_n10_dd'], 2)}, invested for {ex['d0_n10_sessions']} sessions (the rule: {rule_sess[b]}; N4.9 draw 0: {ex['d0_n9_sessions']}), the same {int(x10.invested_weeks)} weeks.</p>
<p><b>8. The ranking.</b> Against N4.10 the rule's CAGR beat {rk10['worse']:,} of {rk10['draws']:,} draws, tied {rk10['tied']}, and was beaten by {rk10['better']}: percentile = ({rk10['worse']} + 0.5 × {rk10['tied']}) ÷ {rk10['draws']:,} × 100 = <b>{rk10['percentile']:.2f}</b>; p-value = (1 + {rk10['better']} + {rk10['tied']}) ÷ ({rk10['draws']:,} + 1) = {rk10['p']:.4f}. Against N4.9: beat {rk9['worse']:,}, tied {rk9['tied']}, beaten by {rk9['better']}: percentile <b>{rk9['percentile']:.2f}</b>, p = {rk9['p']:.4f}.</p>

<h2 id="headline">Headline</h2>
<p>CAGR, after 20.8 bps, full window {start3} → {end_date}, against {ND:,} random timings of each kind. N4.10 decides.</p>
{table(head_rows, ["Book", "Hold parent CAGR", "Rule CAGR", "N4.10 median", "Edge over N4.10 median", "Percentile vs N4.10", "p", "N4.9 median", "Percentile vs N4.9", "p"])}
<p>Maximum drawdown (shallower is better), same window and draws:</p>
{table(dd_rows, ["Book", "Hold parent worst fall", "Rule worst fall", "N4.10 median", "Percentile vs N4.10", "p", "N4.9 median", "Percentile vs N4.9", "p"])}
<h3>Before and after cost, and the comparators ({start3} → {end_date})</h3>
{table(cost_rows, ["Book", "Strategy", "0 bps CAGR", "0 bps worst fall", "20.8 CAGR", "20.8 worst fall", "50 CAGR", "50 worst fall"])}
<p class="cap">The constant mix holds the rule's average share ({100 * int(rule['SCMO_0003'].sum()) / weeks['SCMO_0003']:.1f}%) in the parent all the time and rebalances weekly; the 50/50 sleeve is the other end. Published NAV (D17) CAGR: {", ".join(f"{b_[-4:]} {pc(data['books'][b_]['pub_cagr'])}" for b_ in BOOKS)}.</p>

<h2 id="perbook">Per book</h2><div class="legend">{legend}</div>{curves_html}
<h2 id="nulls">Null distributions, N4.9 and N4.10 overlaid</h2>
<p>For each book the {ND:,} after-cost CAGRs and maximum drawdowns of both nulls on the same bins. Orange = N4.9 (the rule's spells reordered), blue = N4.10 (free lengths), black line = the rule, dashed = each null's median.</p>{hists}
<h2 id="lengths">Spell lengths of the draws against the rule's</h2>
<p>Every in-spell and out-spell of the {ND:,} draws, in weeks. N4.9 can only reuse the rule's own lengths (orange spikes); N4.10 spreads them over {LO} to {HI_IN} (in) and {LO} to {HI_OUT} (out), within the totals.</p>{lenhtml}
{regime}
<h2 id="robust">Robustness (decides the finding's status, not the verdict)</h2>
<p><b>R1</b>, C1 and C2 percentiles at 0, 20.8 and 50 bps ({start3} → {end_date}); pass mark 90 in at least 3 of 4:</p>
{table(rob_rows, ["Book", "N4.10 C1 0", "C1 20.8", "C1 50", "C2 0", "C2 20.8", "C2 50", "N4.9 C1 0", "C1 20.8", "C1 50", "C2 0", "C2 20.8", "C2 50"])}
<p class="cap">C1 at ≥ 90 in 3 of 4 books: against N4.10 at 0 bps {sum(data['books'][b_]['n10_pct_cagr_0'] >= 90 for b_ in BOOKS)}, at 20.8 {V['C1_N10']}, at 50 {sum(data['books'][b_]['n10_pct_cagr_50'] >= 90 for b_ in BOOKS)}; C2 at 0 {sum(data['books'][b_]['n10_pct_dd_0'] >= 90 for b_ in BOOKS)}, at 20.8 {V['C2_N10']}, at 50 {sum(data['books'][b_]['n10_pct_dd_50'] >= 90 for b_ in BOOKS)} (of 4).</p>
<p><b>R2 and R3</b>, C1 percentiles at 20.8 bps. R2: the cash half of the sleeve is the desk's LIQUIDCASE file, full window. R3: the live window {live_start} → {end_date} with its own spells, totals and null (same bounds).</p>
{table(rob2_rows, ["Book", "R2 N4.10", "R2 N4.9", "R2 rule CAGR", "R3 N4.10", "R3 N4.9", "R3 rule CAGR"])}
<p class="cap">At ≥ 90: R2 {V['R2_liq_N10']} of 4 against N4.10, {V['R2_liq_N9']} against N4.9; R3 {V['R3_live_N10']} of 4 against N4.10, {V['R3_live_N9']} against N4.9.</p>
<p><b>R4</b>, agreement of the two nulls on this window (20.8 bps, {start3} → {end_date}; no pass mark): the rule's CAGR percentile and each null's spread of after-cost CAGR.</p>
{table(r4_rows, ["Book", "N4.10 pct", "median", "SD (pp)", "5th pct", "95th pct", "N4.9 pct", "median", "SD (pp)", "5th pct", "95th pct"])}
{t03_html}
<h3>Sessions invested per draw (weeks are held exactly, sessions are not; full window, 20.8 bps)</h3>
{table(ses_rows, ["Book", "Rule", "Sessions in window", "N4.9 min", "median", "max", "N4.10 min", "median", "max"])}
<h3>Power</h3>{table(mde_rows, ["Book", "Round trips", "N4.10 SD CAGR (pp)", "MDE CAGR (pp)", "N4.10 SD worst fall (pp)", "MDE worst fall (pp)", "N4.9 SD CAGR (pp)", "MDE CAGR (pp)", "N4.9 SD worst fall (pp)", "MDE worst fall (pp)"])}
<p class="cap">MDE = 2.8 × the SD of the draws (80% power, two-sided 5%), per null. The numbers did not exist when the pre-registration was written; its thresholds do not depend on them.</p>

<h2 id="defs">Definitions</h2>
<ul><li><b>Percentile</b>: (draws worse + 0.5 × draws tied) ÷ draws × 100, ties equal within a relative 1e-12. <b>p-value</b>: (1 + draws at least as good) ÷ (draws + 1).</li>
<li><b>CAGR</b>: NAV_end^(252 ÷ (sessions − 1)) − 1, daily NAV, after cost. <b>Worst fall</b> (maximum drawdown): the most negative NAV ÷ running peak − 1.</li>
<li><b>N4.9 spell shuffle</b>: the rule's in-spells reordered among themselves and its out-spells among themselves; same weeks invested, same number of switches, same spell lengths. Seed <code>default_rng([3, id])</code>.</li>
<li><b>N4.10 free-length random timing</b>: the same number of in-spells and out-spells and the same totals of weeks in and out, every length an integer from {LO} to {HI_IN} (in) or {HI_OUT} (out), uniform over all allowed ordered tuples, drawn exactly by a dynamic programme, no rejection. Seed <code>default_rng([6, id])</code>. Both nulls start in the rule's first state.</li>
<li><b>Weeks versus sessions</b>: both nulls hold invested weeks exactly; a week has 3 to 5 sessions, so invested sessions differ by draw and are reported.</li>
<li><b>MDE</b>: 2.8 × the SD of the draws' CAGR (or maximum drawdown). <b>Live window</b>: {live_start} → {end_date}.</li></ul>
<p class="meta">Built by <code>tests/T06/report.py</code> from <code>evidence/{E(ev.name)}/</code>. Methods: <code>evidence/METHODS.md</code>. Checked by <code>check_page.py</code>.</p>
<script type="application/json" id="page-data">{json.dumps(data)}</script>
<script type="application/json" id="regime-data">{json.dumps(hover, separators=(",", ":"))}</script>
<script type="application/json" id="lines-data">{json.dumps(lines_data, separators=(",", ":"))}</script>
<script type="application/json" id="bars-data">{json.dumps(bars_data, separators=(",", ":"))}</script>
<script>{LINES_JS}</script>
<script>{BARS_JS}</script>
<script>{HOVER_JS}</script>
</main></body></html>"""
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "report.html").write_text(page, encoding="utf-8")
    print(f"wrote {outdir / 'report.html'} ({len(page) / 1e3:.0f} kB)")


if __name__ == "__main__":
    main()
