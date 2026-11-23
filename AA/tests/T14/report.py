"""T14 results page: reads ONLY the evidence (evidence/<run>/{w1,w2}) through analyse.py's Win class and writes evidence/report.html (AGENT.md R10).

    python tests/T14/report.py [--run headline] [--evidence DIR] [--out DIR] [--books SCMO_0003]

No number on the page is typed: every number is an element  <span class="v" data-k="KEY" data-v="RAW" data-t="UNIT" data-d="DECIMALS">TEXT</span>  whose KEY names where in the evidence it comes
from, so that check_page.py (which shares no code with this file or analyse.py) can recompute RAW from the raw evidence files and check that TEXT is RAW formatted to DECIMALS.
Strings (verdicts, outcome-map codes, signs, dates) are  <span class="s" data-k="KEY" data-s="STRING">  checked the same way. Charts embed the arrays that draw them (lines-data, bars-data) and read the
hover from those arrays. The key grammar is listed in check_page.py.

Forked in layout from tests/T13/report.py (CSS, svg_lines, svg_bars and the hover scripts); content is T14's: the answer first, the data, one backtest end to end per window (a regime entry, a regime exit,
an in-regime basket change, one F1 and one F3 draw, one ranking), the D-table and regime ledger, per-book curves of the six rules and the parent, null histograms with the real value marked, R6 paired
contrasts, robustness, power, definitions.
"""
from __future__ import annotations

import argparse
import html
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import analyse as A  # noqa: E402

E = html.escape
PRIMARY = A.PRIMARY
RULES, NEW, ORIG_OF, CRIT = A.RULES, A.NEW, A.ORIG_OF, A.CRIT
COL = {"hold_parent": "#8a8f98", "50-orig": "#79a8f0", "50-half": "#2a6fdb", "50-liq": "#5b8fd9", "80-orig": "#e8b45c", "80-half": "#c9811a", "80-liq": "#d89a3d"}
LAB = {"hold_parent": "Hold the parent", "50-orig": "50-orig (T06/T11 Part A)", "50-half": "50-half", "50-liq": "50-liq", "80-orig": "80-orig (T08/T11 Part B)", "80-half": "80-half", "80-liq": "80-liq"}
DASH = {"50-orig": "4 3", "80-orig": "4 3", "hold_parent": "1 0"}
CURVE_KINDS = ["hold_parent", "50-orig", "50-half", "50-liq", "80-orig", "80-half", "80-liq"]
NB = 40


# ── elements that carry their provenance ─────────────────────────────────────
def V(key: str, raw: float, kind: str = "x", d: int = 2) -> str:
    """kind: pct (fraction shown as %), pp (fraction shown as signed pp), ppu (fraction shown as unsigned pp), x (as is), int, sgn (as is, signed)."""
    raw = float(raw)
    if kind == "pct":
        txt = f"{100 * raw:.{d}f}%"
    elif kind == "pp":
        txt = f"{100 * raw:+.{d}f}"
    elif kind == "ppu":
        txt = f"{100 * raw:.{d}f}"
    elif kind == "int":
        txt = f"{raw:,.0f}"
    elif kind == "sgn":
        txt = f"{raw:+.{d}f}"
    else:
        txt = f"{raw:.{d}f}"
    return f'<span class="v" data-k="{E(key)}" data-v="{raw!r}" data-t="{kind}" data-d="{d}">{txt}</span>'


def Sx(key: str, s: str, show: str | None = None) -> str:
    return f'<span class="s" data-k="{E(key)}" data-s="{E(str(s))}">{E(str(s) if show is None else show)}</span>'


def DT(w: str, book: str, window: str, a: str, z: str) -> str:
    """the window of a number or chart: first and last date, checked against the evidence."""
    return f'<span class="dt" data-dates="{w}|{book}|{window}">{a} → {z}</span>'


def fref(*ids) -> str:
    return " ".join(f'<a class="fref" href="#f-{i}">formula: {i}</a>' for i in ids)


def card(title: str, body: str, w: str, book: str, window: str, dates: tuple[str, str], fids=(), cls="") -> str:
    return (f'<section class="card needs-dates {cls}" data-formulas="{",".join(fids)}"><h3>{title} <span class="mini">{DT(w, book, window, *dates)}</span></h3>{body}'
            f'<p class="mini">{fref(*fids)}</p></section>')


def tbl(headers, rows, cls="") -> str:
    th = "".join(f"<th>{h}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f'<div class="tw"><table class="{cls}"><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table></div>'


def bkn(b):
    return b[-4:]


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
    for k_, s_ in ((1e12, "tn"), (1e9, "bn"), (1e6, "m"), (1e3, "k")):
        if abs(v) >= k_:
            return f"{v / k_:g}{s_}"
    return f"{v:g}"


# ── charts ────────────────────────────────────────────────────────────────────
def svg_lines(series: dict, dates, key: str, title: str, w=720, h=270):
    """series: {kind: NAV array}; every 5th session plus the last; log scale; hover read from lines-data[key]."""
    idx = np.arange(0, len(dates), 5)
    if idx[-1] != len(dates) - 1:
        idx = np.append(idx, len(dates) - 1)
    allv = np.concatenate([v[idx] for v in series.values()])
    ymin, ymax = math.log(allv.min() * 0.97), math.log(allv.max() * 1.03)
    L, R, T, B = 44, 8, 8, 24
    x = lambda i: L + (w - L - R) * i / (len(idx) - 1)
    y = lambda v: T + (h - T - B) * (1 - (math.log(v) - ymin) / (ymax - ymin))
    out = [f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="{E(title)}" class="chart lc" data-book="{E(key)}">']
    for t in (0.5, 1, 2, 4, 8, 16, 32, 64):
        if allv.min() * 0.97 <= t <= allv.max() * 1.03:
            out.append(f'<line x1="{L}" x2="{w - R}" y1="{y(t):.1f}" y2="{y(t):.1f}" class="grid"/><text x="{L - 4}" y="{y(t) + 3:.1f}" text-anchor="end" class="ax">{t:g}×</text>')
    years = sorted({pd.Timestamp(d).year for d in dates})
    for yr in years[::2]:
        i = int(np.argmax([pd.Timestamp(d).year == yr for d in dates]))
        j = int(np.argmin(np.abs(idx - i)))
        out.append(f'<text x="{x(j):.1f}" y="{h - 6}" text-anchor="middle" class="ax">{yr}</text>')
    for k, v in series.items():
        pts = " ".join(f"{x(j):.1f},{y(v[i]):.1f}" for j, i in enumerate(idx))
        dash = f' stroke-dasharray="{DASH[k]}"' if k in DASH and DASH[k] != "1 0" else ""
        out.append(f'<polyline points="{pts}" fill="none" stroke="{COL[k]}" stroke-width="{1.3 if k in ("hold_parent", "50-orig", "80-orig") else 2.2}"{dash} stroke-linejoin="round"/>')
    bot = h - B
    out.append('<g class="lc-hv" style="display:none" pointer-events="none">'
               f'<line class="lc-v" y1="{T}" y2="{bot}" stroke="var(--muted)" stroke-width="1"/>'
               f'<line class="lc-h" x1="{L}" x2="{w - R}" stroke="var(--muted)" stroke-width="1" stroke-dasharray="3 3"/>'
               + "".join(f'<circle class="lc-c" r="3.2" fill="{COL[k]}" stroke="var(--card)" stroke-width="1.5"/>' for k in series)
               + f'<g class="lc-yc"><rect x="0" y="-8" width="{L - 3}" height="16" rx="3" fill="var(--fg)"/><text x="{L - 7}" y="3.5" text-anchor="end" font-size="10" fill="var(--bg)" class="lc-yt"></text></g>'
               f'<g class="lc-xc"><rect y="{h - 19}" width="92" height="16" rx="3" fill="var(--fg)" class="lc-xr"/><text y="{h - 7.5}" text-anchor="middle" font-size="10" fill="var(--bg)" class="lc-xt"></text></g></g>')
    out.append(f'<rect class="lc-ov" x="{L}" y="{T}" width="{w - L - R}" height="{bot - T}" fill="transparent" style="cursor:crosshair;touch-action:none"/></svg>')
    data = {"w": w, "h": h, "L": L, "R": R, "T": T, "B": B, "lo": ymin, "hi": ymax, "log": True, "n": len(idx),
            "dates": [pd.Timestamp(dates[i]).strftime("%Y-%m-%d (%a)") for i in idx],
            "series": [{"k": k, "label": LAB[k], "col": COL[k], "v": [round(float(v[i]), 4) for i in idx]} for k, v in series.items()]}
    return "".join(out), data


def hist_bins(draws: np.ndarray, real: float, nb=NB):
    lo, hi = float(min(draws.min(), real)), float(max(draws.max(), real))
    pad = 0.02 * (hi - lo) if hi > lo else 1e-6
    edges = np.linspace(lo - pad, hi + pad, nb + 1)
    counts, _ = np.histogram(draws, bins=edges)
    return edges, counts


def svg_bars(did: str, edges, counts, marks, label: str, xk="pct", w=420, h=180, L=44):
    R, T, B = 8, 8, 30
    x0, x1 = float(edges[0]), float(edges[-1])
    ymax = float(counts.max())
    ticks = nice_ticks(ymax, 4)
    ymax_axis = max(ticks[-1], ymax)
    X = lambda v: L + (w - L - R) * (v - x0) / (x1 - x0)
    Y = lambda v: T + (h - T - B) * (1 - v / ymax_axis)
    o = [f'<svg viewBox="0 0 {w} {h}" class="chart bc" role="img" aria-label="{E(label)}" data-id="{E(did)}">']
    for t in ticks:
        o.append(f'<line x1="{L}" x2="{w - R}" y1="{Y(t):.1f}" y2="{Y(t):.1f}" class="grid"/><text x="{L - 4}" y="{Y(t) + 3:.1f}" text-anchor="end" class="ax">{si(t)}</text>')
    for i, c in enumerate(counts):
        if c > 0:
            o.append(f'<rect x="{X(edges[i]) + 0.4:.1f}" y="{Y(c):.1f}" width="{max(X(edges[i + 1]) - X(edges[i]) - 0.8, 0.5):.1f}" height="{h - B - Y(c):.1f}" fill="#8a8f98" opacity="0.6"/>')
    for m in marks:
        o.append(f'<line x1="{X(m["x"]):.1f}" x2="{X(m["x"]):.1f}" y1="{T}" y2="{h - B}" stroke="{m["col"]}" stroke-width="{2.4 if not m.get("dash") else 1.3}"' + (' stroke-dasharray="3 3"' if m.get("dash") else "") + "/>")
    for k in range(5):
        v = x0 + (x1 - x0) * k / 4
        o.append(f'<text x="{X(v):.1f}" y="{h - 16}" text-anchor="middle" class="ax">{100 * v:.0f}%</text>')
    bot = h - B
    o.append('<g class="bc-hv" style="display:none" pointer-events="none">'
             f'<line class="bc-v" y1="{T}" y2="{bot}" stroke="var(--muted)" stroke-width="1"/>'
             f'<line class="bc-h" x1="{L}" x2="{w - R}" stroke="var(--muted)" stroke-width="1" stroke-dasharray="3 3"/>'
             f'<g class="bc-yc"><rect x="0" y="-8" width="{L - 3}" height="16" rx="3" fill="var(--fg)"/><text x="{L - 7}" y="3.5" text-anchor="end" font-size="10" fill="var(--bg)" class="bc-yt"></text></g>'
             f'<g class="bc-xc"><rect y="{h - 15}" width="74" height="14" rx="3" fill="var(--fg)" class="bc-xr"/><text y="{h - 5}" text-anchor="middle" font-size="10" fill="var(--bg)" class="bc-xt"></text></g></g>')
    o.append(f'<rect class="bc-ov" x="{L}" y="{T}" width="{w - L - R}" height="{bot - T}" fill="transparent" style="cursor:crosshair;touch-action:none"/></svg>')
    data = {"w": w, "h": h, "L": L, "R": R, "T": T, "B": B, "x0": x0, "x1": x1, "ymax": ymax_axis, "xk": xk, "yk": "int", "yunit": "draws", "edges": [round(float(e), 10) for e in edges],
            "binlab": [f"{100 * edges[i]:.2f}% to {100 * edges[i + 1]:.2f}%" for i in range(len(counts))], "extra": None,
            "series": [{"k": "null", "label": label, "col": "#8a8f98", "v": [int(c) for c in counts], "n": int(counts.sum())}],
            "marks": [{"label": m["label"], "x": round(float(m["x"]), 10), "txt": m["txt"]} for m in marks]}
    return "".join(o), data


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

BARS_JS = """(function(){
var all=JSON.parse(document.getElementById('bars-data').textContent);
function f(k,v){if(k==='pct')return (100*v).toFixed(2)+'%';return Math.round(v).toLocaleString('en-US')}
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
  q('.bc-yt').textContent=f('int',d.ymax*(1-(vy-d.T)/ph));
  var xr=q('.bc-xr'),xl=Math.max(0,Math.min(d.w-74,vx-37));xr.setAttribute('x',xl);q('.bc-xt').setAttribute('x',xl+37);q('.bc-xt').textContent=f(d.xk,v);
  var s='<b>'+d.binlab[b]+'</b>';
  for(var n=0;n<d.series.length;n++){var S=d.series[n];s+='<br><i style="background:'+S.col+'"></i>'+S.label+': <b>'+S.v[b].toLocaleString('en-US')+'</b> '+d.yunit+' ('+(100*S.v[b]/S.n).toFixed(2)+'%)'}
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
:root{--bg:#fbfbfa;--fg:#1c1f24;--muted:#6b7280;--card:#ffffff;--line:#e3e5e8;--ok:#1b7f4d;--bad:#b3261e;--warn:#a86400}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#14161a;--fg:#e6e8eb;--muted:#9aa1ab;--card:#1b1e23;--line:#2d3138;--ok:#4cc38a;--bad:#ff7b72;--warn:#e0a43a}}
:root[data-theme=dark]{--bg:#14161a;--fg:#e6e8eb;--muted:#9aa1ab;--card:#1b1e23;--line:#2d3138;--ok:#4cc38a;--bad:#ff7b72;--warn:#e0a43a}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.55 -apple-system,Segoe UI,Roboto,sans-serif}
main{max-width:1040px;margin:0 auto;padding:24px 16px 64px}h1{font-size:25px;line-height:1.25;margin:.2em 0}h2{margin-top:2.2em;font-size:20px;border-top:1px solid var(--line);padding-top:1em}h3{font-size:16px;margin:0 0 .5em}
.mini,.cap,.ax{color:var(--muted);font-size:12.5px}.tw{overflow-x:auto;margin:.6em 0}table{border-collapse:collapse;font-size:12.5px;min-width:100%}th,td{padding:4px 7px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}th{color:var(--muted);font-weight:500}td:first-child,th:first-child{text-align:left}
table.wrap td,table.wrap th{white-space:normal;text-align:left;vertical-align:top}
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:10px 12px;margin:10px 0}.chart{width:100%;height:auto}.grid{stroke:var(--line)}.ax{fill:var(--muted);font-size:10px}
.pass{color:var(--ok);font-weight:600}.fail{color:var(--bad);font-weight:600}.warn{color:var(--warn)}
.formula{background:var(--card);border:1px solid var(--line);border-radius:6px;padding:8px 12px;font:12.5px/1.5 ui-monospace,Consolas,monospace;white-space:pre-wrap;overflow-x:auto;margin:6px 0}
.hv{position:relative}.tip{position:absolute;z-index:5;pointer-events:none;background:var(--card);border:1px solid var(--line);border-radius:6px;padding:6px 9px;font-size:12px;line-height:1.5;white-space:nowrap;box-shadow:0 2px 8px rgba(0,0,0,.18);font-variant-numeric:tabular-nums}.tip i{display:inline-block;width:10px;height:3px;margin-right:6px;vertical-align:middle}
.legend{display:flex;flex-wrap:wrap;gap:6px 16px;font-size:12.5px;margin:6px 0}.legend i{display:inline-block;width:14px;height:3px;margin-right:6px;vertical-align:middle}
.answer{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--warn);border-radius:6px;padding:12px 16px}.grid2{display:grid;grid-template-columns:1fr 1fr;gap:10px}
details{margin:.4em 0}summary{cursor:pointer;color:var(--muted)}@media (max-width:700px){.grid2{grid-template-columns:1fr}h1{font-size:21px}}
"""

FORMULAS = {
    "nav": "NAV_t = cash_t + Σ_i units_i × close_i,t   (cash = LBES units × LBES level; GOLDBEES units × its close); base 1.0 at the close of the first session; daily marks on the window's sessions",
    "cagr": "CAGR = NAV_end ^ (252 ÷ (sessions − 1)) − 1   (sessions = the window's trading sessions; years = (sessions − 1) ÷ 252; arithmetic, price return, after the stated cost)",
    "maxdd": "max drawdown = min over t of ( NAV_t ÷ max(NAV_s, s ≤ t) − 1 )   (negative; 'shallower' = closer to 0)",
    "calmar": "Calmar = CAGR ÷ |max drawdown|",
    "vol": "volatility = standard deviation of the daily NAV returns × √252   (Ulcer index, days ≥ 10% under peak and longest time under water as in T08/T11)",
    "cost": "traded = Σ over every line |target value − held value| at the trade session's prices;  cost = traded × cost_bps ÷ 2 ÷ 10,000  (10.4 bps a side at 20.8 bps; 0 and 50 bps as robustness);\nevery target is then scaled by (V − cost) ÷ V",
    "e_gw": "regime at a decision: IN = all three index SIGNs BUY;  OUT-BUY = not IN and MAUc1 SIGN BUY;  OUT-SELL = not IN and MAUc1 SIGN SELL.\ntarget (e, gw): e = parent share of the book, gw = GOLDBEES share of the non-parent part (the rest is the LBES liquid ETF)\n"
            "50-orig: IN (1, ·), else (0, 0.5);  50-half: OUT-SELL (0.5, 1.0);  50-liq: OUT-SELL (0, 0);  80-orig: OUT-BUY (0, 0.8), OUT-SELL (0, 0.2);  80-half / 80-liq: as 50-half / 50-liq, OUT-BUY (0, 0.8)",
    "pct": "percentile = (draws worse + 0.5 × draws tied) ÷ draws × 100, ties equal within a relative 1e-12;  'worse' = lower CAGR, deeper (more negative) max drawdown;  2,000 draws per book, cost, rule and null",
    "pval": "p = (1 + draws at least as good (better or tied)) ÷ (draws + 1)",
    "mde": "MDE = 2.8 × the SD of the null's statistic (CAGR or max drawdown), in pp; printed beside every FAIL: 'undetectable below the MDE', never 'no effect'",
    "holm": "Holm step-down adjusted p: sort the 16 p-values of a window (per book) ascending, p_adj(i) = max over j ≤ i of min(1, (16 − j + 1) × p_(j))",
    "r6": "R6: Δ_d = statistic(variant, draw d) − statistic(its original, the same draw d), for every F1 and every F3 draw (CAGR and max drawdown; positive = better); the real Δ (variant − original on the real series) is ranked among the Δ_d with the percentile formula",
    "ledger": "ledger return of a rule over an OUT-SELL spell = NAV_end ÷ NAV_start − 1 from the close of the spell's first decision's session to the close of the session of the decision that ends it (or the last session); parent = hold_parent (0 bps); GOLDBEES, cash = close ÷ close − 1",
    "cmix": "constant mix at a rule's own averages: f = mean of e over the decisions, gw_bar = Σ (1 − e) gw ÷ Σ (1 − e); rebalanced at every decision and every basket change",
    "d": "difference from the original = statistic(variant) − statistic(original) on the same window, cost and cash; CAGR, volatility in pp; max drawdown in pp (positive = shallower)",
}


def fbox(i: str) -> str:
    return f'<div class="formula" id="f-{i}">{E(FORMULAS[i])}</div>'


# ── window content ────────────────────────────────────────────────────────────
def keyp(w, b, window="full", cash="lbes", cost=PRIMARY):
    return f"{w}|{b}|{window}|{cash}|{cost}"


def stV(W, b, kind, field, d=2, cost=PRIMARY, window="full", cash="lbes", u="pct"):
    return V(f"st:{keyp(W.name, b, window, cash, cost)}|{kind}|{field}", W.S(b, kind, cost, window, cash)[field], u, d)


def dtV(W, b, v, field, d=2, cost=PRIMARY, window="full", cash="lbes"):
    o = ORIG_OF[v]
    return V(f"dt:{keyp(W.name, b, window, cash, cost)}|{v}|{field}", W.S(b, v, cost, window, cash)[field] - W.S(b, o, cost, window, cash)[field], "pp" if field != "calmar" else "sgn", d)


def rkV(W, b, fam, rule, stat, what, cost=PRIMARY, window="full", cash="lbes", d=1, kind="x"):
    r = W.rk(b, fam, rule, stat, cost, window, cash)
    return V(f"rk:{keyp(W.name, b, window, cash, cost)}|{fam}|{rule}|{stat}|{what}", r[what], kind, d)


def dates_of(W, b, window="full"):
    return W.start_end(b) if window == "full" else W.r3_dates(b)


def verdict_cell(W, rows, rule, crit):
    r = next(x for x in rows if x["rule"] == rule and x["crit"] == crit)
    s = "PASS" if r["pass"] else "FAIL"
    return f'<span class="{"pass" if r["pass"] else "fail"}">' + Sx(f"vd:{W.name}|{rule}|{crit}", s) + "</span> (" + V(f"np:{W.name}|full|lbes|{PRIMARY}|{r['fam']}|{rule}|{r['stat']}", r["n_pass"], "int", 0) + f" of {len(W.books)})"


def section_answer(Ws, crit_by, r6_by, out_by) -> str:
    h = ['<h2 id="answer">1. The answer</h2><div class="answer">']
    h.append("<p><b>Question.</b> In the weeks when the three-index switch is OUT <i>and</i> the MAUc1 gold signal is SELL (the OUT-SELL regime), does holding half the parent plus half GOLDBEES (<code>-half</code>) or only the liquid ETF "
             "(<code>-liq</code>) instead of the original sleeve change what the switch earns, on both base sleeves (50/50 and 80/20), on W1 and W2? Descriptive first (the difference from the original rule, R6), then against chance "
             "(E1, E2 against random in-or-out timing; G1, G2 against random gold timing).</p>")
    h.append("<p><b>Status.</b> T14, a post-hoc variant on two windows that were seen before the variants were proposed: any finding is PROVISIONAL at most; there is no hold-out. Cost 20.8 bps, LBES cash. "
             "The verdicts below are the pre-registered mechanical outcome map (T14.md 2.4); the interpretation is in the write-up (T14.md 5-8).</p>")
    for w, W in Ws.items():
        a, z = W.start_end(W.books[0])
        crit_rows, rows6, orows = crit_by[w], r6_by[w], out_by[w]
        npass = sum(1 for r in crit_rows if r["pass"])
        h.append(f'<h3>{A.WIN_TXT[w]} <span class="mini">{DT(w, W.books[0], "full", a, z)}</span></h3>')
        h.append(f"<p>{V(f'npass:{w}', npass, 'int', 0)} of {V(f'ncrit:{w}', len(crit_rows), 'int', 0)} criteria PASS (a pass = percentile ≥ 90 in at least 3 of the {V(f'nbooks:{w}', len(W.books), 'int', 0)} books). "
                 f"{V(f'ndraws:{w}', W.ndraws, 'int', 0)} draws per book, cost, rule and null. {fref('pct', 'pval', 'mde', 'holm')}</p>")
        recs = []
        for o in orows:
            v = o["variant"]
            cells = [f"<b>{v}</b> vs {o['orig']}"]
            cells.append(" ".join(f"{bkn(b)} " + dtV(W, b, v, "cagr", 2) for b in W.books))
            cells.append(" ".join(f"{bkn(b)} " + dtV(W, b, v, "max_dd", 2) for b in W.books))
            for fam in ("F1", "F3"):
                cells.append(" ".join(f"{bkn(b)} " + V(f"r6:{w}|{b}|{PRIMARY}|{v}|{fam}|cagr|percentile", o["r6"][fam][b], "x", 1) for b in W.books))
            cells.append(Sx(f"pt:{w}|{v}|F1", "P1" if o["direction"] == "positive" and o["r6n"]["F1"] >= 3 else "P2" if o["direction"] == "positive" else "P3" if o["direction"] == "negative" else "none") + " / "
                         + Sx(f"pt:{w}|{v}|F3", "P1" if o["direction"] == "positive" and o["r6n"]["F3"] >= 3 else "P2" if o["direction"] == "positive" else "P3" if o["direction"] == "negative" else "none"))
            for c in ("E1", "E2", "G1", "G2"):
                cells.append(verdict_cell(W, crit_rows, v, c))
            recs.append(cells)
        h.append(tbl(["rule", "Δ CAGR pp (book)", "Δ max drawdown pp", "R6 percentile of ΔCAGR vs F1", "vs F3", "pattern F1 / F3", "E1", "E2", "G1", "G2"], recs))
    h.append('<p class="mini">Pattern codes (T14.md 2.4, read mechanically): <b>P1</b> CAGR difference positive in ≥ 3 books and R6 paired percentile ≥ 90 in ≥ 3 books (improves, by timing; PROVISIONAL); <b>P2</b> positive in ≥ 3 books, '
             'R6 < 90 (the holding earned it: exposure); <b>P3</b> negative in ≥ 3 books (worse); <b>none</b> mixed. R6 is shown against F1 and against F3. A difference of CAGR in pp; percentile in points.</p></div>')
    return "".join(h)


def section_data(Ws) -> str:
    h = ['<h2 id="data">2. The data</h2><p class="mini">Every file is an APPROVED row of data/APPROVED_DATA.md; the engine opens files only through the approved-data check and records them in inputs.csv '
         '(path, through-date, bytes, sha256, approved row, usable-from). Price returns only. W1 rebuilt parent NAV: ' + E(A.CAPTION_W1) + ".</p>"]
    for w, W in Ws.items():
        rows = []
        for r in W.inp.to_dict("records"):
            rows.append([E(r["file"]), Sx(f"in:{w}|{r['file']}|through", r["through"]), Sx(f"in:{w}|{r['file']}|approved_row", r["approved_row"]), Sx(f"in:{w}|{r['file']}|sha", r["sha256"][:12]), E(r["usable_from"])])
        h.append(f"<h3>{A.WIN_TXT[w]}: {len(rows)} input files</h3>" + tbl(["file", "through", "approved row", "sha256 (12)", "usable from"], rows, "wrap"))
    return "".join(h)


def worked(W, w) -> str:
    """One backtest end to end for the first book (R10)."""
    b = W.books[0]
    a, z = W.start_end(b)
    d = W.dbook(b)
    ent, ext, bch, pr = A.pick_trades(W, b)
    cost_k = lambda r, f: f"tr:{w}|{b}|{pr}|{PRIMARY}|{int(r.idx)}|{r.kind}|{f}"
    h = [f'<h3>{A.WIN_TXT[w]}: book {b}, rule {pr}, {PRIMARY} bps <span class="mini">{DT(w, b, "full", a, z)}</span></h3>']
    st = []
    nsess = len(W.curve(b, PRIMARY, "50-orig")[0])
    st.append(["Inputs", f"Parent {b} rebuilt from its baskets and D18 prices; three index SIGN files and MAUc1 SIGN; GOLDBEES, LBES cash; calendar of {A.WIN_TXT[w]}",
               f"{DT(w, b, 'full', a, z)}; sessions " + V(f"n:sessions|{w}|{b}", nsess, "int", 0) + "; weekly decisions " + V(f"rc:{w}|{b}|decisions", W.regime_counts(b)["decisions"], "int", 0)])
    if ent is not None:
        r = d.iloc[int(ent.dec_j)]
        j = int(ent.dec_j)
        st.append(["Signal", "label = latest Master row dated on or before the decision date; state IN iff all three SIGN = BUY; g = MAUc1 SIGN BUY",
                   f"decision j = {V(f'dc:{w}|{b}|{j}|j', j, 'int', 0)} on " + Sx(f"ds:{w}|{b}|{j}|decision_date", r.decision_date) + ": Nifty100 " + Sx(f"ds:{w}|{b}|{j}|sign_Nifty100", r.sign_Nifty100) + ", Midcap100 " +
                   Sx(f"ds:{w}|{b}|{j}|sign_MC100", r.sign_MC100) + ", Smallcap100 " + Sx(f"ds:{w}|{b}|{j}|sign_SC100", r.sign_SC100) + ", MAUc1 " + Sx(f"ds:{w}|{b}|{j}|sign_MAUc1", r.sign_MAUc1) +
                   "; regime " + Sx(f"ds:{w}|{b}|{j}|regime", r.regime) + " (previous week " + Sx(f"ds:{w}|{b}|{j - 1}|regime", d.regime.iloc[j - 1]) + ")"])
        st.append(["Decision", f"target (e, gw) per rule {fref('e_gw')}",
                   "; ".join(f"{ru} (" + V(f"dc:{w}|{b}|{j}|e_{ru}", r[f"e_{ru}"], "x", 2) + ", " + V(f"dc:{w}|{b}|{j}|gw_{ru}", r[f"gw_{ru}"], "x", 2) + ")" for ru in RULES) +
                   "; trade on the next session " + Sx(f"ds:{w}|{b}|{j}|trade_date", r.trade_date) + f" at that session's OHLC4"])
        st.append(["Execution: regime entry", f"{pr}: into OUT-SELL; traded = Σ|target − held|, cost = traded × {PRIMARY} ÷ 2 ÷ 10,000 {fref('cost')}",
                   "date " + Sx(cost_k(ent, "date"), str(ent.date)) + "; V " + V(cost_k(ent, "V"), ent.V, "x", 6) + "; traded " + V(cost_k(ent, "traded"), ent.traded, "x", 6) + "; cost " + V(cost_k(ent, "cost"), ent.cost, "x", 6)
                   + "; V − cost " + V(f"tr2:{w}|{b}|{pr}|{PRIMARY}|{int(ent.idx)}|{ent.kind}|vmc", ent.V - ent.cost, "x", 6)])
        st.append(["Holdings after the entry", "units_i = money_i ÷ price_i: stock part = 0.5 × (V − cost) spread over the basket's listed weights, GOLDBEES = 0.5 × (V − cost), cash 0",
                   "stock " + V(cost_k(ent, "stock_after"), ent.stock_after, "x", 6) + "; GOLDBEES " + V(cost_k(ent, "gold_after"), ent.gold_after, "x", 6) + "; cash " + V(cost_k(ent, "cash_after"), ent.cash_after, "x", 6)
                   + "; before: stock " + V(cost_k(ent, "stock_before"), ent.stock_before, "x", 6) + ", GOLDBEES " + V(cost_k(ent, "gold_before"), ent.gold_before, "x", 6) + ", cash " + V(cost_k(ent, "cash_before"), ent.cash_before, "x", 6)])
    if bch is not None:
        st.append(["One in-regime parent rebalance", "basket change while the rule holds half the parent (D1): only the stock part is re-weighted to the new basket at its current value; GOLDBEES and cash units unchanged; cost on the stock lines is taken from the stock part",
                   "date " + Sx(cost_k(bch, "date"), str(bch.date)) + "; stock before " + V(cost_k(bch, "stock_before"), bch.stock_before, "x", 6) + "; cost " + V(cost_k(bch, "cost"), bch.cost, "x", 6) + "; stock after " + V(cost_k(bch, "stock_after"), bch.stock_after, "x", 6)
                   + " (= before − cost); GOLDBEES " + V(cost_k(bch, "gold_before"), bch.gold_before, "x", 6) + " → " + V(cost_k(bch, "gold_after"), bch.gold_after, "x", 6)])
    if ext is not None:
        j2 = int(ext.dec_j)
        st.append(["One regime exit", "out of OUT-SELL: " + "sell the half parent and the GOLDBEES, buy the new target (back to the full parent, or the sleeve)",
                   "decision " + Sx(f"ds:{w}|{b}|{j2}|decision_date", d.decision_date.iloc[j2]) + " regime " + Sx(f"ds:{w}|{b}|{j2}|regime", d.regime.iloc[j2]) + "; trade " + Sx(cost_k(ext, "date"), str(ext.date)) +
                   "; V " + V(cost_k(ext, "V"), ext.V, "x", 6) + "; traded " + V(cost_k(ext, "traded"), ext.traded, "x", 6) + "; cost " + V(cost_k(ext, "cost"), ext.cost, "x", 6) + "; stock after " + V(cost_k(ext, "stock_after"), ext.stock_after, "x", 6)
                   + ", GOLDBEES after " + V(cost_k(ext, "gold_after"), ext.gold_after, "x", 6)])
    if ent is not None:
        dts, nv = W.curve(b, PRIMARY, pr)
        i = int(ent.idx)
        st.append(["Daily value", f"NAV_t = cash_t + Σ units × close_t {fref('nav')}", "; ".join(
            Sx(f"nvd:{w}|{b}|{PRIMARY}|{pr}|{k}", str(pd.Timestamp(dts[k]).date())) + " " + V(f"nv:{w}|{b}|{PRIMARY}|{pr}|{str(pd.Timestamp(dts[k]).date())}", nv[k], "x", 6) for k in (i - 1, i, i + 1))])
    dts, nv = W.curve(b, PRIMARY, pr)
    yrs = (len(nv) - 1) / 252
    s = W.S(b, pr)
    st.append(["Equity curve", f"growth of 1 invested at the close of {pd.Timestamp(dts[0]).date()} (base 1.000), daily marks",
               "start " + V(f"nv:{w}|{b}|{PRIMARY}|{pr}|{pd.Timestamp(dts[0]).date()}", nv[0], "x", 3) + " on " + DT(w, b, "full", a, z) + "; end " + V(f"st:{keyp(w, b)}|{pr}|end_nav", s["end_nav"], "x", 4) + f" after "
               + V(f"st:{keyp(w, b)}|{pr}|sessions", s["sessions"], "int", 0) + " sessions"])
    st.append(["Statistics", f"{fref('cagr', 'maxdd', 'calmar', 'vol')}",
               "CAGR = " + V(f"st:{keyp(w, b)}|{pr}|end_nav", s["end_nav"], "x", 4) + " ^ (252 ÷ (" + V(f"st:{keyp(w, b)}|{pr}|sessions", s["sessions"], "int", 0) + " − 1)) − 1 = " + stV(W, b, pr, "cagr", 3) +
               "; max drawdown " + stV(W, b, pr, "max_dd", 3) + "; Calmar " + stV(W, b, pr, "calmar", 3, u="x") + "; volatility " + stV(W, b, pr, "vol", 3)])
    # F1 draw
    G0 = A.WORKED_DRAW
    real_io = W.realz[f"{b}|full|io"].astype(int)
    real_g = W.realz[f"{b}|full|gold"].astype(int)
    Ai = W.states[f"{b}|full|io|N4.10"][G0].astype(int)
    Gi = W.states[f"{b}|full|gold|N4.10-g"][G0].astype(int)
    drs = lambda fam, rule, f, d_=4, u="pct": V(f"dr:{keyp(w, b)}|{fam}|{rule}|{G0}|{f}", W.draws(b, fam, rule, f)[G0], u, d_)
    st.append(["Null: one F1 draw", f"N4.10: the real in-or-out series ({len(A.lens(real_io, 1))} in-spells, {len(A.lens(real_io, 0))} out-spells, {int(real_io.sum())} IN weeks) with its spell lengths redrawn within the bounds; "
               f"the real gold signal stays; draw id {G0}. Each rule is run on the draw's own regimes",
               f"rule {pr}: CAGR " + drs("F1", pr, "cagr") + ", max drawdown " + drs("F1", pr, "max_dd") + ", OUT-SELL weeks " + V(f"dr:{keyp(w, b)}|F1|{pr}|{G0}|out_sell_weeks", W.draws(b, "F1", pr, "out_sell_weeks")[G0], "int", 0)
               + f"; real CAGR " + stV(W, b, pr, "cagr", 4)])
    st.append(["Null: one F3 draw", f"N4.10-g: the real in-or-out series with the MAUc1 BUY/SELL weeks redrawn ({len(A.lens(real_g, 1))} BUY spells, {len(A.lens(real_g, 0))} SELL spells, {int(real_g.sum())} BUY weeks); draw id {G0}",
               f"rule {pr}: CAGR " + drs("F3", pr, "cagr") + ", max drawdown " + drs("F3", pr, "max_dd") + ", OUT-SELL weeks " + V(f"dr:{keyp(w, b)}|F3|{pr}|{G0}|out_sell_weeks", W.draws(b, "F3", pr, "out_sell_weeks")[G0], "int", 0)])
    x = W.rk(b, "F1", pr, "cagr")
    st.append(["Ranking (E1)", f"the real CAGR among the {W.ndraws:,} F1 draws' CAGRs of the same rule {fref('pct', 'pval', 'mde')}",
               "draws below " + rkV(W, b, "F1", pr, "cagr", "worse", d=0, kind="int") + ", equal " + rkV(W, b, "F1", pr, "cagr", "tied", d=0, kind="int") + ", above " + rkV(W, b, "F1", pr, "cagr", "better", d=0, kind="int")
               + "; percentile " + rkV(W, b, "F1", pr, "cagr", "percentile", d=2) + "; p " + rkV(W, b, "F1", pr, "cagr", "p", d=4) + "; null median " + rkV(W, b, "F1", pr, "cagr", "median", d=2, kind="pct")
               + "; edge " + rkV(W, b, "F1", pr, "cagr", "edge", d=2, kind="pp") + " pp; MDE " + rkV(W, b, "F1", pr, "cagr", "mde", d=2, kind="ppu") + " pp"])
    st.append(["Comparators", f"hold the parent (basket bought at T0, rebalanced with the parent); constant mix at the rule's own averages {fref('cmix')}",
               "hold CAGR " + stV(W, b, "hold_parent", "cagr", 2) + ", max drawdown " + stV(W, b, "hold_parent", "max_dd", 2) + "; cmix_" + pr + " CAGR " + stV(W, b, "cmix_" + pr, "cagr", 2) + " with f = "
               + V(f"cm:{w}|{b}|{pr}|f", float(W.cmix[(W.cmix.book == b) & (W.cmix.rule == pr)].f.iloc[0]), "x", 4) + ", GOLDBEES share of the rest = " + V(f"cm:{w}|{b}|{pr}|gw_bar", float(W.cmix[(W.cmix.book == b) & (W.cmix.rule == pr)].gw_bar.iloc[0]), "x", 4)])
    h.append(tbl(["Step", "What and formula", f"Real numbers ({b}, {a} → {z})"], [[s_[0], s_[1], s_[2]] for s_ in st], "wrap"))
    # first 20 weeks of the F1 and F3 draws
    rows = []
    nm = lambda v: "IN" if v else "out"
    gm = lambda v: "BUY" if v else "SELL"
    for j in range(20):
        rows.append([str(j), Sx(f"ds:{w}|{b}|{j}|decision_date", d.decision_date.iloc[j]), Sx(f"stw:{w}|{b}|real|io|{j}", nm(real_io[j])), Sx(f"stw:{w}|{b}|io|N4.10|{G0}|{j}", nm(Ai[j])),
                     Sx(f"stw:{w}|{b}|real|gold|{j}", gm(real_g[j])), Sx(f"stw:{w}|{b}|gold|N4.10-g|{G0}|{j}", gm(Gi[j]))])
    h.append(f'<details open><summary>The first 20 weekly decisions of F1 draw {G0} (in-or-out) and F3 draw {G0} (MAUc1) against the real series, {DT(w, b, "full", a, z)}</summary>'
             + tbl(["j", "decision date", "real in-or-out", f"F1 draw {G0}", "real MAUc1", f"F3 draw {G0}"], rows) + "</details>")
    return "".join(h)


def section_example(Ws) -> str:
    h = ['<h2 id="example">3. One backtest, end to end</h2><p>One book (the first), one window at a time, from the signal to the ranking, with the formulas and the real numbers. A reader with a calculator can redo every step.</p>']
    for w, W in Ws.items():
        h.append(worked(W, w))
    return "".join(h)


def section_dtable(W, crit_rows) -> str:
    w = W.name
    a, z = W.start_end(W.books[0])
    h = [f'<h3>{A.WIN_TXT[w]}</h3>']
    rows = []
    for b in W.books:
        rc = W.regime_counts(b)
        aa, zz = W.start_end(b)
        rows.append([bkn(b), DT(w, b, "full", aa, zz)] + [V(f"rc:{w}|{b}|{f}", rc[f], "int", 0) for f in ("sessions", "decisions", "weeks_IN", "weeks_OUT-BUY", "weeks_OUT-SELL", "sess_IN", "sess_OUT-BUY", "sess_OUT-SELL", "out_sell_spells", "round_trips")])
    h.append(card("Weeks and sessions in each regime", tbl(["book", "window", "sessions − 1", "decisions", "IN wk", "OUT-BUY wk", "OUT-SELL wk", "IN sess", "OUT-BUY sess", "OUT-SELL sess", "OUT-SELL spells", "round trips"], rows)
                  + '<p class="mini">weeks = weekly decisions; sessions = from each decision\'s trade session to the next one\'s; they sum to the sessions − 1 of the window.</p>', w, W.books[0], "full", (a, z), ("e_gw",)))
    rows = []
    for b in W.books:
        for r in RULES:
            s = W.S(b, r)
            row = [bkn(b), r, stV(W, b, r, "cagr", 2), dtV(W, b, r, "cagr", 2) if r in ORIG_OF else "", stV(W, b, r, "max_dd", 2), dtV(W, b, r, "max_dd", 2) if r in ORIG_OF else "", stV(W, b, r, "calmar", 3, u="x"),
                   dtV(W, b, r, "calmar", 3) if r in ORIG_OF else "", stV(W, b, r, "vol", 2), dtV(W, b, r, "vol", 2) if r in ORIG_OF else "", stV(W, b, r, "end_nav", 4, u="x"), stV(W, b, r, "trades", 0, u="int"),
                   V(f"st:{keyp(w, b)}|{r}|cost_paid", s["cost_paid"], "ppu", 3)]
            rows.append(row)
    h.append(card("D-table: each new rule beside its own original, 20.8 bps", tbl(["book", "rule", "CAGR", "Δ CAGR pp", "max DD", "Δ max DD pp", "Calmar", "Δ Calmar", "vol", "Δ vol pp", "end NAV", "trades", "cost paid (% of start NAV)"], rows),
                  w, W.books[0], "full", (a, z), ("cagr", "maxdd", "calmar", "vol", "cost", "d")))
    L = W.ledger[(W.ledger.window == "full") & W.ledger.book.isin(W.books)]
    rows = []
    for r in L.to_dict("records"):
        b = r["book"]
        k = f"led:{w}|{b}|{int(r['spell_no'])}"
        rows.append([bkn(b), str(int(r["spell_no"])), Sx(f"{k}|first_decision", r["first_decision"]), Sx(f"{k}|last_decision", r["last_decision"]), V(f"{k}|weeks", r["weeks"], "int", 0), Sx(f"{k}|span_from_close", r["span_from_close"]),
                     Sx(f"{k}|span_to_close", r["span_to_close"]), r["entered_from"], r["exited_to"], V(f"{k}|parent_return", r["parent_return"], "pct", 2), V(f"{k}|goldbees_return", r["goldbees_return"], "pct", 2),
                     V(f"{k}|cash_return", r["cash_return"], "pct", 2)] + [V(f"{k}|ret_{ru}", r[f"ret_{ru}"], "pct", 2) for ru in RULES])
    h.append(card("Regime ledger: every OUT-SELL spell", tbl(["book", "#", "first decision", "last decision", "weeks", "span from close", "span to close", "from", "to", "parent", "GOLDBEES", "cash"] + RULES, rows), w, W.books[0], "full", (a, z), ("ledger",)))
    rows = []
    for b in W.books:
        for k in ["hold_parent", "50-orig", "80-orig", "constant_mix", "constant_mix_timed", "sleeve_only", "sleeve_only_timed"] + [f"cmix_{r}" for r in RULES]:
            rows.append([bkn(b), k, stV(W, b, k, "cagr", 2), stV(W, b, k, "max_dd", 2), stV(W, b, k, "calmar", 3, u="x"), stV(W, b, k, "vol", 2)])
    h.append(card("Comparators (benchmarks, not nulls), 20.8 bps", tbl(["book", "comparator", "CAGR", "max DD", "Calmar", "vol"], rows) +
                  '<p class="mini">constant_mix: f = share of IN weeks in the parent, rest 50/50; constant_mix_timed: rest split by the gold signal; sleeve_only(_timed): 100% sleeve; cmix_&lt;rule&gt;: the rule\'s own average parent share and GOLDBEES share.</p>',
                  w, W.books[0], "full", (a, z), ("cagr", "maxdd", "calmar", "vol", "cmix")))
    return "".join(h)


def section_curves(Ws, lines_data) -> str:
    h = ['<h2 id="curves">5. The curves: the six rules and the parent, per book</h2><p class="mini">Growth of 1 invested at the close of the first session of the window, log scale, 20.8 bps, daily marks (every 5th session drawn, hover reads the same arrays). '
         'The two originals are dashed.</p>']
    for w, W in Ws.items():
        a, z = W.start_end(W.books[0])
        h.append(f'<h3>{A.WIN_TXT[w]}</h3><div class="legend">' + "".join(f'<span><i style="background:{COL[k]}"></i>{E(LAB[k])}</span>' for k in CURVE_KINDS) + "</div>")
        for b in W.books:
            dts, _ = W.curve(b, PRIMARY, "50-orig")
            ser = {k: W.curve(b, PRIMARY, k)[1] for k in CURVE_KINDS}
            aa, zz = W.start_end(b)
            key = f"{w}|{b}"
            svg, data = svg_lines(ser, dts, key, f"{b} growth of 1")
            lines_data[key] = data
            h.append(f'<figure class="card hv needs-dates" data-formulas="nav" style="margin:10px 0"><figcaption><b>{b}</b>: growth of 1 invested at the close of {aa}, log scale, {PRIMARY} bps '
                     f'<span class="mini">{DT(w, b, "full", aa, zz)}; end values ' + ", ".join(f"{LAB[k]} " + V(f"st:{keyp(w, b)}|{k}|end_nav", W.S(b, k)["end_nav"], "x", 2) + "×" for k in CURVE_KINDS) + f'</span></figcaption>{svg}<div class="tip" hidden></div>'
                     f'<p class="mini">{fref("nav")}</p></figure>')
    return "".join(h)


def hist_fig(W, b, fam, rule, stat, crit_name, bars_data, window="full", cash="lbes", cost=PRIMARY):
    w = W.name
    draws = W.draws(b, fam, rule, stat, cost, window, cash)
    s = W.S(b, rule, cost, window, cash)
    real = float(s[stat])
    rk = W.rk(b, fam, rule, stat, cost, window, cash)
    edges, counts = hist_bins(draws, real)
    did = f"h:{keyp(w, b, window, cash, cost)}|{fam}|{rule}|{stat}"
    marks = [{"label": "the rule", "x": real, "col": "#2a6fdb", "txt": f"percentile {rk['percentile']:.1f}"}, {"label": "null median", "x": rk["median"], "col": "var(--fg)", "txt": "", "dash": True}]
    svg, data = svg_bars(did, edges, counts, marks, f"{fam} draws, {rule}, {A.STAT_NAME[stat]}")
    bars_data[did] = data
    a, z = dates_of(W, b, window)
    cap = (f"<b>{crit_name}</b> {rule}, {A.STAT_NAME[stat]} vs {fam}: real " + V(f"rk:{keyp(w, b, window, cash, cost)}|{fam}|{rule}|{stat}|real", real, "pct", 2) + ", percentile " + V(f"rk:{keyp(w, b, window, cash, cost)}|{fam}|{rule}|{stat}|percentile", rk["percentile"], "x", 1)
           + ", p " + V(f"rk:{keyp(w, b, window, cash, cost)}|{fam}|{rule}|{stat}|p", rk["p"], "x", 4) + f" <span class=\"mini\">{DT(w, b, window, a, z)}, {W.ndraws:,} draws</span>")
    return f'<figure class="card hv needs-dates" data-formulas="pct" style="margin:6px 0"><figcaption>{cap}</figcaption>{svg}<div class="tip" hidden></div><p class="mini">{fref("pct")}</p></figure>'


def section_headline(Ws, crit_by, bars_data) -> str:
    h = ['<h2 id="headline">4. The headline and the verdict table</h2>']
    for w, W in Ws.items():
        a, z = W.start_end(W.books[0])
        rows = []
        for r in crit_by[w]:
            cells = [r["rule"], r["crit"], r["fam"], A.STAT_NAME[r["stat"]]]
            for b in W.books:
                cells.append(V(f"rk:{keyp(w, b)}|{r['fam']}|{r['rule']}|{r['stat']}|percentile", r["per"][b]["percentile"], "x", 1))
            cells.append(verdict_cell(W, crit_by[w], r["rule"], r["crit"]))
            cells.append("" if r["pass"] else "undetectable below " + " / ".join(V(f"rk:{keyp(w, b)}|{r['fam']}|{r['rule']}|{r['stat']}|mde", r["per"][b]["mde"], "ppu", 2) for b in W.books) + " pp")
            cells.append(" / ".join(V(f"hl:{w}|{b}|{r['rule']}|{r['crit']}", r["holm"][b], "x", 3) for b in W.books))
            rows.append(cells)
        h.append(card(f"{A.WIN_TXT[w]}: percentile per book, verdict, MDE beside every FAIL, Holm p per book", tbl(["rule", "crit", "null", "statistic"] + [bkn(b) for b in W.books] + ["verdict", "MDE (pp, per book)", "Holm p (per book)"], rows, ""),
                      w, W.books[0], "full", (a, z), ("pct", "pval", "mde", "holm", "cagr", "maxdd")))
        rows = []
        for r in crit_by[w]:
            if r["per2"] is None:
                continue
            rows.append([r["rule"], r["crit"], r["fam2"]] + [V(f"rk:{keyp(w, b)}|{r['fam2']}|{r['rule']}|{r['stat']}|percentile", r["per2"][b]["percentile"], "x", 1) for b in W.books])
        h.append(card("F2 beside F1 and F4 beside F3 (the same percentile against N4.9 / N4.9-g)", tbl(["rule", "crit", "null beside"] + [bkn(b) for b in W.books], rows), w, W.books[0], "full", (a, z), ("pct",)))
        h.append(f'<details><summary>Null histograms of {A.WIN_TXT[w]} for {W.books[0]} (CAGR and max drawdown of each new rule against its deciding null; the real value marked), {DT(w, W.books[0], "full", a, z)}</summary><div class="grid2">'
                 + "".join(hist_fig(W, W.books[0], fam, rule, stat, c, bars_data) for rule in NEW for (c, stat, fam, _f2, _t) in CRIT) + "</div></details>")
    return "".join(h)


def section_r6(Ws, r6_by, bars_data) -> str:
    h = ['<h2 id="r6">6. R6: the paired contrast (is the difference larger than the same change would make in random weeks?)</h2>']
    for w, W in Ws.items():
        a, z = W.start_end(W.books[0])
        rows = []
        for r in r6_by[w]:
            k = f"r6:{w}|{r['book']}|{PRIMARY}|{r['variant']}|{r['fam']}|{r['stat']}"
            rows.append([r["variant"], r["orig"], r["fam"], A.STAT_NAME[r["stat"]], bkn(r["book"]), V(f"{k}|real", r["real"], "pp", 2), V(f"{k}|median", r["median"], "pp", 2), V(f"{k}|sd", r["sd"], "ppu", 2),
                         V(f"{k}|worse", r["worse"], "int", 0) + "/" + V(f"{k}|tied", r["tied"], "int", 0) + "/" + V(f"{k}|better", r["better"], "int", 0), V(f"{k}|percentile", r["percentile"], "x", 1), V(f"{k}|p", r["p"], "x", 4)])
        h.append(card(f"{A.WIN_TXT[w]}: real difference (variant − original) ranked among the draws' differences, 20.8 bps", tbl(["variant", "vs", "null", "statistic", "book", "real Δ pp", "median Δ pp", "SD pp", "below / equal / above", "percentile", "p"], rows),
                      w, W.books[0], "full", (a, z), ("r6", "pct", "pval", "cagr", "maxdd")))
        figs = []
        b = W.books[0]
        for v in NEW:
            for fam in ("F1", "F3"):
                o = ORIG_OF[v]
                dv, do = W.D[(b, "full", "lbes", PRIMARY, fam, v)], W.D[(b, "full", "lbes", PRIMARY, fam, o)]
                delta = dv["cagr"] - do["cagr"]
                real = W.S(b, v)["cagr"] - W.S(b, o)["cagr"]
                edges, counts = hist_bins(delta, real)
                rk_ = next(x for x in r6_by[w] if x["variant"] == v and x["book"] == b and x["fam"] == fam and x["stat"] == "cagr")
                did = f"d:{w}|{b}|{PRIMARY}|{v}|{fam}|cagr"
                svg, data = svg_bars(did, edges, counts, [{"label": "real Δ", "x": real, "col": "#2a6fdb", "txt": f"percentile {rk_['percentile']:.1f}"}, {"label": "median Δ", "x": rk_["median"], "col": "var(--fg)", "txt": "", "dash": True}],
                                     f"Δ CAGR {v} − {o} over {fam} draws")
                bars_data[did] = data
                figs.append(f'<figure class="card hv needs-dates" data-formulas="r6" style="margin:6px 0"><figcaption><b>{v} − {o}</b> over the {fam} draws, ΔCAGR: real ' + V(f"{'r6:' + w}|{b}|{PRIMARY}|{v}|{fam}|cagr|real", real, "pp", 2)
                            + " pp, percentile " + V(f"r6:{w}|{b}|{PRIMARY}|{v}|{fam}|cagr|percentile", rk_["percentile"], "x", 1) + f' <span class="mini">{DT(w, b, "full", a, z)}</span></figcaption>{svg}<div class="tip" hidden></div><p class="mini">{fref("r6")}</p></figure>')
        h.append(f"<details><summary>R6 histograms of ΔCAGR for {W.books[0]}, {A.WIN_TXT[w]}</summary><div class=\"grid2\">" + "".join(figs) + "</div></details>")
    return "".join(h)


def section_robust(Ws, crit_by) -> str:
    h = ['<h2 id="robust">7. Robustness R1-R7</h2><p class="mini">Percentiles per book; verdict = ≥ 90 in at least 3 books. R1: 0 and 50 bps; R2: LIQUIDCASE as the cash leg (E1, G1); R3: the window from 2015-01-02 (W1) or the live decisions from 2021-11-01 (W2) (E1, G1); '
         'R4: F2 beside F1 and F4 beside F3 in section 4; R5: against F5 (both timings random); R7 (W1): price-quality sensitivity.</p>']
    for w, W in Ws.items():
        a, z = W.start_end(W.books[0])
        cells_ = [("R1 at 0 bps", 0.0, "full", "lbes", CRIT), ("R1 at 50 bps", 50.0, "full", "lbes", CRIT), ("R2 LIQUIDCASE cash (20.8 bps)", PRIMARY, "full", "liq", [c for c in CRIT if c[0] in ("E1", "G1")]),
                  ("R3 own window (20.8 bps)", PRIMARY, "r3", "lbes", [c for c in CRIT if c[0] in ("E1", "G1")])]
        for title, cost, window, cash, crits in cells_:
            if (W.books[0], window, cash, cost, "F1", "50-half") not in W.D:
                continue
            aa, zz = dates_of(W, W.books[0], window)
            rows = []
            for r in NEW:
                for c, stat, fam, fam2, txt in crits:
                    pcts = [W.rk(b, fam, r, stat, cost, window, cash) for b in W.books]
                    npass = A.n_pass([x["percentile"] for x in pcts])
                    rows.append([r, c, fam] + [V(f"rk:{keyp(w, b, window, cash, cost)}|{fam}|{r}|{stat}|percentile", x["percentile"], "x", 1) for b, x in zip(W.books, pcts)]
                                + [f'<span class="{"pass" if npass >= 3 else "fail"}">' + Sx(f"vdr:{w}|{window}|{cash}|{cost}|{r}|{c}", "PASS" if npass >= 3 else "FAIL") + "</span>"])
            h.append(card(f"{A.WIN_TXT[w]}: {title}", tbl(["rule", "crit", "null"] + [bkn(b) for b in W.books] + ["verdict"], rows), w, W.books[0], window, (aa, zz), ("pct", "cagr", "maxdd")))
            rows = []
            for b in W.books:
                for r in RULES:
                    s = W.S(b, r, cost, window, cash)
                    rows.append([bkn(b), r, stV(W, b, r, "cagr", 2, cost, window, cash), dtV(W, b, r, "cagr", 2, cost, window, cash) if r in ORIG_OF else "", stV(W, b, r, "max_dd", 2, cost, window, cash),
                                 dtV(W, b, r, "max_dd", 2, cost, window, cash) if r in ORIG_OF else ""])
            h.append(f'<details><summary>{A.WIN_TXT[w]}: D-table, {title}, {DT(w, W.books[0], window, aa, zz)}</summary>' + tbl(["book", "rule", "CAGR", "Δ CAGR pp", "max DD", "Δ max DD pp"], rows) + f'<p class="mini">{fref("cagr", "maxdd", "d")}</p></details>')
        rows = []
        for r in NEW + ["50-orig", "80-orig"]:
            for c, stat in (("CAGR", "cagr"), ("max drawdown", "max_dd")):
                pcts = [W.rk(b, "F5", r, stat) for b in W.books]
                rows.append([r, c, "F5"] + [V(f"rk:{keyp(w, b)}|F5|{r}|{stat}|percentile", x["percentile"], "x", 1) for b, x in zip(W.books, pcts)])
        h.append(card(f"{A.WIN_TXT[w]}: R5, percentile against F5 (both timings random), 20.8 bps", tbl(["rule", "statistic", "null"] + [bkn(b) for b in W.books], rows), w, W.books[0], "full", (a, z), ("pct",)))
        if w == "w1":
            rows = []
            for b in W.books:
                for cost in (0.0, PRIMARY):
                    for tag in ("", "_r7_flagged", "_r7_noexport"):
                        for v in NEW:
                            try:
                                s_, o_ = W.S(b, v + tag, cost), W.S(b, ORIG_OF[v] + tag, cost)
                            except KeyError:
                                continue
                            rows.append([bkn(b), str(cost), tag[1:] or "as run", v, V(f"st:{keyp(w, b, 'full', 'lbes', cost)}|{v + tag}|cagr", s_["cagr"], "pct", 2),
                                         V(f"dt7:{keyp(w, b, 'full', 'lbes', cost)}|{v}|{tag}|cagr", s_["cagr"] - o_["cagr"], "pp", 2), V(f"st:{keyp(w, b, 'full', 'lbes', cost)}|{v + tag}|max_dd", s_["max_dd"], "pct", 2),
                                         V(f"dt7:{keyp(w, b, 'full', 'lbes', cost)}|{v}|{tag}|max_dd", s_["max_dd"] - o_["max_dd"], "pp", 2)])
            h.append(card("R7 (W1 only): stock-days with a ≥ 20% one-day move on held stocks set to zero return (r7_flagged), manual-export stocks set to zero return (r7_noexport)",
                          tbl(["book", "cost bps", "data", "rule", "CAGR", "Δ CAGR pp", "max DD", "Δ max DD pp"], rows), w, W.books[0], "full", (a, z), ("cagr", "maxdd", "d")))
    return "".join(h)


def section_power(Ws, crit_by) -> str:
    h = ['<h2 id="power">8. Power, MDE and sessions invested</h2>']
    for w, W in Ws.items():
        a, z = W.start_end(W.books[0])
        rc = W.regime_counts(W.books[0])
        rows = []
        for r in crit_by[w]:
            rows.append([r["rule"], r["crit"], r["fam"], A.STAT_NAME[r["stat"]]] + [V(f"rk:{keyp(w, b)}|{r['fam']}|{r['rule']}|{r['stat']}|sd", r["per"][b]["sd"], "ppu", 2) for b in W.books]
                        + [V(f"rk:{keyp(w, b)}|{r['fam']}|{r['rule']}|{r['stat']}|mde", r["per"][b]["mde"], "ppu", 2) for b in W.books])
        h.append(card(f"{A.WIN_TXT[w]}: the null's SD and the MDE = 2.8 × SD (pp), 20.8 bps; effective sample " + V(f"rc:{w}|{W.books[0]}|out_sell_spells", rc["out_sell_spells"], "int", 0) + " OUT-SELL spells, " + V(f"rc:{w}|{W.books[0]}|round_trips", rc["round_trips"], "int", 0)
                      + " in-or-out round trips", tbl(["rule", "crit", "null", "statistic"] + [f"SD {bkn(b)}" for b in W.books] + [f"MDE {bkn(b)}" for b in W.books], rows), w, W.books[0], "full", (a, z), ("mde", "cagr", "maxdd")))
        rows = []
        for b in W.books:
            rcb = W.regime_counts(b)
            row = [bkn(b), V(f"rc:{w}|{b}|weeks_IN", rcb["weeks_IN"], "int", 0), V(f"rc:{w}|{b}|sess_IN", rcb["sess_IN"], "int", 0)]
            for fam in ("F1", "F2"):
                x = W.draws(b, fam, "50-orig", "sessions_invested")
                row += [V(f"dm:{keyp(w, b)}|{fam}|50-orig|sessions_invested|mean", x.mean(), "x", 1), V(f"dm:{keyp(w, b)}|{fam}|50-orig|sessions_invested|min", x.min(), "int", 0), V(f"dm:{keyp(w, b)}|{fam}|50-orig|sessions_invested|max", x.max(), "int", 0)]
            x = W.draws(b, "F1", "50-half", "out_sell_weeks")
            row += [V(f"rc:{w}|{b}|weeks_OUT-SELL", rcb["weeks_OUT-SELL"], "int", 0), V(f"dm:{keyp(w, b)}|F1|50-half|out_sell_weeks|mean", x.mean(), "x", 1)]
            rows.append(row)
        h.append(card(f"{A.WIN_TXT[w]}: sessions invested (the parent held; in-or-out nulls hold invested WEEKS exactly, sessions only approximately) and OUT-SELL weeks (not held by the nulls)",
                      tbl(["book", "real IN weeks", "real IN sessions", "F1 mean", "F1 min", "F1 max", "F2 mean", "F2 min", "F2 max", "real OUT-SELL weeks", "F1 draws' mean OUT-SELL weeks"], rows), w, W.books[0], "full", (a, z), ("e_gw",)))
    return "".join(h)


def section_defs() -> str:
    names = ["nav", "cost", "e_gw", "cagr", "maxdd", "calmar", "vol", "cmix", "d", "pct", "pval", "mde", "holm", "r6", "ledger"]
    return '<h2 id="defs">9. Definitions (every statistic once, in full)</h2>' + "".join(f"<p class='mini'><b>{n}</b></p>{fbox(n)}" for n in names)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="headline")
    ap.add_argument("--evidence", default=None)
    ap.add_argument("--out", default=None, help="directory for report.html (default tests/T14/evidence)")
    ap.add_argument("--books", default=None)
    a = ap.parse_args()
    ev = Path(a.evidence) if a.evidence else HERE / "evidence" / a.run
    outdir = Path(a.out) if a.out else (ev if a.evidence else HERE / "evidence")
    books = a.books.split(",") if a.books else None
    Ws = {w: A.Win(ev / w, w, books) for w in ("w1", "w2") if (ev / w / "audit.json").exists()}
    crit_by, orig_by, r6_by, out_by = {}, {}, {}, {}
    for w, W in Ws.items():
        crit_by[w] = A.compute_criteria(W)
        orig_by[w] = A.compute_criteria(W, rules=["50-orig", "80-orig"], with_holm=False)
        r6_by[w] = A.compute_r6(W)
        out_by[w] = A.outcome_rows(W, crit_by[w], r6_by[w], orig_by[w])
    lines_data, bars_data = {}, {}
    doc_hash = A.prereg_hash(HERE / "T14.md")
    parts = [section_answer(Ws, crit_by, r6_by, out_by), section_data(Ws), section_example(Ws)]
    parts.append(section_headline(Ws, crit_by, bars_data))
    parts.append("<h2 id=\"desc\">The descriptive headline: D-table, regime ledger, comparators</h2>" + "".join(section_dtable(W, crit_by[w]) for w, W in Ws.items()))
    parts.append(section_curves(Ws, lines_data))
    parts.append(section_r6(Ws, r6_by, bars_data))
    parts.append(section_robust(Ws, crit_by))
    parts.append(section_power(Ws, crit_by))
    parts.append(section_defs())
    W0 = next(iter(Ws.values()))
    n_books = len(W0.books)
    note = "" if n_books == 4 else f'<p class="warn"><b>Development run: {n_books} book(s), {W0.ndraws:,} draws; every count of books and every verdict on this page means nothing.</b></p>'
    head = (f'<h1>T14: what to hold in the OUT-SELL regime (the three-index switch OUT and MAUc1 SELL)</h1><p class="mini">Test T14, run <b>{E(ev.name)}</b>; pre-registration sha256 {doc_hash[1][:16]} '
            f'(match with the T14.md header: {doc_hash[0] == doc_hash[1]}); windows W1 and W2 with their own dates throughout; <a href="METHODS.md">METHODS.md</a> beside this page. Contents: '
            '<a href="#answer">answer</a>, <a href="#data">data</a>, <a href="#example">one backtest</a>, <a href="#headline">headline</a>, <a href="#desc">D-table</a>, <a href="#curves">curves</a>, <a href="#r6">R6</a>, '
            f'<a href="#robust">robustness</a>, <a href="#power">power</a>, <a href="#defs">definitions</a>.</p>{note}')
    page = (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>T14 OUT-SELL regime results</title><style>{CSS}</style></head>'
            f'<body><main>{head}{"".join(parts)}</main><script id="lines-data" type="application/json">{json.dumps(lines_data)}</script><script id="bars-data" type="application/json">{json.dumps(bars_data)}</script>'
            f'<script>{LINES_JS}</script><script>{BARS_JS}</script></body></html>')
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "report.html").write_text(page, encoding="utf-8")
    nv_ = page.count('class="v"')
    print(f"wrote {outdir / 'report.html'} ({len(page):,} bytes; {nv_:,} numbers with provenance, {len(lines_data)} curve charts, {len(bars_data)} histograms)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
