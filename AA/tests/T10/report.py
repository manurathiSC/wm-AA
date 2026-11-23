"""Build report.html for T10 from shipped evidence only (AGENT.md R10).

    python -I tests/T10/report.py [--run headline]             writes evidence/<run>/report.html (needs evidence/<run>/analysis.json from analyse.py)
    python -I tests/T10/report.py --evidence DIR               another evidence directory (e.g. the smoke run or a scratch copy); the page is written there

Every number on the page is either a <span class="n" data-k="PATH" data-f="FORMAT"> whose PATH points into the embedded page-data block (= analysis.json, which
analyse.py computed from the evidence), or a point of a chart array embedded as JSON (lines-data, fs-data, st-data, bars-data) computed here from daily_nav.csv,
decisions.csv, stretches.csv and r4_tag_error.csv. check_page.py recomputes page-data and every array independently from the evidence and checks every span against it.
There is NO NULL in T10: the page says so next to every headline. Imports nothing from the engine. The page is a local file (not published as an Artifact).
Every chart is hoverable (AGENT.md R10): the hover reads the same arrays that draw the chart.
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
E = html.escape
PRIMARY = 20.8
SEP = "~"
BANDS = ["Large", "Mid", "Small and below"]
SIGS = ["Nifty100", "MC100", "SC100"]
SIGLAB = {"Nifty100": "Nifty 100", "MC100": "Midcap 100", "SC100": "Smallcap 100"}
BCOL = ["#6b4fbb", "#c9811a", "#2f9e6e"]
COL = {"rule": "#2a6fdb", "switch": "var(--fg)", "parent": "#8a8f98", "constant_mix": "#c9811a", "published_parent": "#a14fa1"}
LAB = {"rule": "FS rule (this test)", "switch": "Three-index switch", "parent": "Hold the parent", "constant_mix": "Constant mix (same average exposure)", "published_parent": "Published parent (D17)"}
DASH = {"published_parent": "4 3"}
KINDS = ["rule", "switch", "parent", "constant_mix", "sleeve100", "published_parent", "t07_rule"]
KLAB = {"rule": "FS rule (this test)", "switch": "Three-index switch", "parent": "Hold the parent (rebuilt)", "constant_mix": "Constant mix (same average exposure)",
        "sleeve100": "100% sleeve", "published_parent": "Published parent (D17)", "t07_rule": "T07 per-stock rule (descriptive, unverified)"}
THR = ["thr_2/5", "thr_1/2", "rule", "thr_7/10", "thr_4/5"]
THR_LAB = {"thr_2/5": "2/5", "thr_1/2": "1/2", "rule": "3/5 = 0.60 (production)", "thr_7/10": "7/10", "thr_4/5": "4/5"}
DOWNSAMPLE = 5
NOCHANCE = "no chance benchmark was run"


# ── the number formats (check_page.py has its own copy) ───────────────────────────────────────────
def _nn(f):
    return lambda x: "" if x is None else f(x)


FMT = {
    "pc0": _nn(lambda x: f"{100 * x:.0f}%"), "pc1": _nn(lambda x: f"{100 * x:.1f}%"), "pc2": _nn(lambda x: f"{100 * x:.2f}%"),
    "pp1": _nn(lambda x: f"{100 * x:+.1f}"), "pp2": _nn(lambda x: f"{100 * x:+.2f}"),
    "n2": _nn(lambda x: f"{x:.2f}"), "n3": _nn(lambda x: f"{x:.3f}"), "n4": _nn(lambda x: f"{x:.4f}"), "n6": _nn(lambda x: f"{x:.6f}"), "n8": _nn(lambda x: f"{x:.8f}"),
    "int": _nn(lambda x: f"{x:,.0f}"), "str": _nn(lambda x: str(x)), "sci": _nn(lambda x: f"{x:.1e}"),
    "pf": _nn(lambda x: "PASS" if x else "FAIL"), "yn": _nn(lambda x: "yes" if x else "no"), "rep": _nn(lambda x: "REPORTABLE" if x else "NOT REPORTABLE"),
}


class Page:
    def __init__(self, R):
        self.R = R

    def get(self, path):
        o = self.R
        for p in path.split(SEP):
            o = o[int(p)] if isinstance(o, list) else o[p]
        return o

    def N(self, path, fmt="n3", cls=""):
        v = self.get(path)
        t = FMT[fmt](v)
        c = ("n " + cls).strip()
        if fmt == "pf":
            c += " chip " + ("ok" if v else "bad")
        return f'<span class="{c}" data-k="{E(path)}" data-f="{fmt}">{E(t)}</span>'


def asbool(s):
    return s.astype(str).str.strip().str.lower().isin(["true", "1", "1.0"]).values


def fmt_table(rows, cols, cls=""):
    th = "".join(f"<th>{c}</th>" for c in cols)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f'<div class="tw"><table class="{cls}"><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table></div>'


def md_plain(t):
    return t.replace("**", "").replace("`", "")


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


# ── charts ────────────────────────────────────────────────────────────────────────────────────────
def svg_lines(did, series, dates, kind, w=640, h=250):
    """series: {name: array}; drawn every DOWNSAMPLE-th session (and the last). kind 'eq' = growth of 1 (log) or 'dd' = drawdown from the running peak (linear). Hover: LINES_JS."""
    idx = np.arange(0, len(dates), DOWNSAMPLE)
    if idx[-1] != len(dates) - 1:
        idx = np.append(idx, len(dates) - 1)
    log = kind == "eq"
    allv = np.concatenate([v[idx] for v in series.values()])
    if log:
        ymin, ymax = math.log(allv.min() * 0.97), math.log(allv.max() * 1.03)
    else:
        ymin, ymax = float(allv.min()) * 1.04, 0.0
    L, R, T, B = 44, 8, 8, 24
    x = lambda i: L + (w - L - R) * i / (len(idx) - 1)
    y = lambda v: T + (h - T - B) * (1 - ((math.log(v) if log else v) - ymin) / (ymax - ymin))
    out = [f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="{E(did)}" class="chart lc" data-id="{E(did)}">']
    if log:
        for t in [0.5, 1, 2, 4, 8, 16, 32]:
            if allv.min() * 0.97 <= t <= allv.max() * 1.03:
                out.append(f'<line x1="{L}" x2="{w - R}" y1="{y(t):.1f}" y2="{y(t):.1f}" class="grid"/><text x="{L - 4}" y="{y(t) + 3:.1f}" text-anchor="end" class="ax">{t:g}×</text>')
    else:
        step = 0.1 if ymin < -0.25 else 0.05
        t = 0.0
        while t >= ymin - 1e-9:
            out.append(f'<line x1="{L}" x2="{w - R}" y1="{y(t):.1f}" y2="{y(t):.1f}" class="grid"/><text x="{L - 4}" y="{y(t) + 3:.1f}" text-anchor="end" class="ax">{100 * t:.0f}%</text>')
            t -= step
    years = sorted({d.year for d in dates})
    for yr in years[::2]:
        i = int(np.argmax([d.year == yr for d in dates]))
        j = int(np.argmin(np.abs(idx - i)))
        out.append(f'<text x="{x(j):.1f}" y="{h - 6}" text-anchor="middle" class="ax">{yr}</text>')
    for k, v in series.items():
        pts = " ".join(f"{x(j):.1f},{y(v[i]):.1f}" for j, i in enumerate(idx))
        dash = f' stroke-dasharray="{DASH[k]}"' if k in DASH else ""
        out.append(f'<polyline points="{pts}" fill="none" stroke="{COL[k]}" stroke-width="{2.4 if k == "rule" else 1.3}" stroke-linejoin="round"{dash}/>')
    bot = h - B
    out.append('<g class="lc-hv" style="display:none" pointer-events="none">'
               f'<line class="lc-v" y1="{T}" y2="{bot}" stroke="var(--muted)" stroke-width="1"/>'
               f'<line class="lc-h" x1="{L}" x2="{w - R}" stroke="var(--muted)" stroke-width="1" stroke-dasharray="3 3"/>'
               + "".join(f'<circle class="lc-c" r="3.5" fill="{COL[k]}" stroke="var(--card)" stroke-width="1.5"/>' for k in series)
               + f'<g class="lc-yc"><rect x="0" y="-8" width="{L - 3}" height="16" rx="3" fill="var(--fg)"/><text x="{L - 7}" y="3.5" text-anchor="end" font-size="10" fill="var(--bg)" class="lc-yt"></text></g>'
               f'<g class="lc-xc"><rect y="{h - 19}" width="92" height="16" rx="3" fill="var(--fg)" class="lc-xr"/><text y="{h - 7.5}" text-anchor="middle" font-size="10" fill="var(--bg)" class="lc-xt"></text></g></g>')
    out.append(f'<rect class="lc-ov" x="{L}" y="{T}" width="{w - L - R}" height="{bot - T}" fill="transparent" style="cursor:crosshair;touch-action:none"/>')
    out.append("</svg>")
    data = {"w": w, "h": h, "L": L, "R": R, "T": T, "B": B, "lo": ymin, "hi": ymax, "log": log, "fmt": "x" if log else "pct", "n": len(idx),
            "dates": [dates[i].strftime("%Y-%m-%d (%a)") for i in idx],
            "series": [{"k": k, "label": LAB[k], "col": COL[k], "v": [round(float(v[i]), 4) for i in idx]} for k, v in series.items()]}
    return "".join(out), data


def svg_bars(did, edges, series, marks=(), xk="pct", yk="int", w=460, h=190, xticks=None, binlab=None, yunit="draws", L=44):
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
            "edges": [round(float(e), 8) for e in edges], "binlab": binlab,
            "series": [{"k": s["k"], "label": s["label"], "col": s["col"], "v": [int(c) for c in s["v"]], "n": int(s["n"])} for s in series],
            "marks": [{"label": m["label"], "x": round(float(m["x"]), 8), "txt": m["txt"]} for m in marks]}
    return "".join(o), data


def svg_fs(did, d, w=760):
    """Weekly FS (= k / n) as a step line with the 0.60 line; the extra weeks shaded; below it five strips: the three signals (filled = BUY), the rule's state and the switch's (filled = IN). Hover: FS_JS."""
    n = d["n"]
    L, R, T, ph = 92, 8, 8, 120
    rowh, gap = 11, 4
    top = T + ph + 16
    nrow = 5
    h = top + nrow * (rowh + gap) + 16
    X = lambda j: L + (w - L - R) * j / n
    Y = lambda f: T + ph * (1 - f)
    bot = top + nrow * (rowh + gap) - gap
    o = [f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="{E(did)}" class="chart fs" data-id="{E(did)}">']
    for j in range(n):
        if d["extra"][j]:
            o.append(f'<rect x="{X(j):.1f}" y="{T}" width="{max(X(j + 1) - X(j), 0.6):.1f}" height="{bot - T}" fill="{BCOL[1]}" opacity="0.16"/>')
    for t in (0, 0.25, 0.5, 0.75, 1.0):
        o.append(f'<line x1="{L}" x2="{w - R}" y1="{Y(t):.1f}" y2="{Y(t):.1f}" class="grid"/><text x="{L - 4}" y="{Y(t) + 3:.1f}" text-anchor="end" class="ax">{t:.2f}</text>')
    o.append(f'<line x1="{L}" x2="{w - R}" y1="{Y(0.6):.1f}" y2="{Y(0.6):.1f}" stroke="{BCOL[1]}" stroke-width="1.4" stroke-dasharray="5 3"/><text x="{w - R - 2}" y="{Y(0.6) - 3:.1f}" text-anchor="end" class="ax" style="fill:var(--fg)">0.60 (IN at or above)</text>')
    pts = []
    for j in range(n):
        pts.append(f"{X(j):.1f},{Y(d['fs'][j]):.1f}")
        pts.append(f"{X(j + 1):.1f},{Y(d['fs'][j]):.1f}")
    o.append(f'<polyline points="{" ".join(pts)}" fill="none" stroke="{COL["rule"]}" stroke-width="1.5" stroke-linejoin="round"/>')
    labels = [SIGLAB[s_] for s_ in SIGS] + ["FS rule IN", "Switch IN"]
    fills = [BCOL[0], BCOL[1], BCOL[2], COL["rule"], COL["switch"]]
    for r_ in range(nrow):
        yy = top + r_ * (rowh + gap)
        o.append(f'<rect x="{L}" y="{yy}" width="{w - L - R}" height="{rowh}" fill="var(--line)" rx="2"/><text x="{L - 6}" y="{yy + rowh - 2}" text-anchor="end" class="ax">{labels[r_]}</text>')
        for j in range(n):
            on = d["pat"][j][r_] == "B" if r_ < 3 else (d["rule"][j] if r_ == 3 else d["sw"][j])
            if on:
                o.append(f'<rect x="{X(j):.1f}" y="{yy}" width="{max(X(j + 1) - X(j), 0.6):.1f}" height="{rowh}" fill="{fills[r_]}"/>')
    ys = sorted({int(s_[:4]) for s_ in d["dates"]})
    for yr in ys:
        j = next(k for k, s_ in enumerate(d["dates"]) if int(s_[:4]) == yr)
        o.append(f'<text x="{X(j):.1f}" y="{h - 4}" text-anchor="middle" class="ax">{yr}</text>')
    o.append('<g class="fs-hv" style="display:none" pointer-events="none">'
             f'<line class="fs-v" y1="{T}" y2="{bot}" stroke="var(--muted)" stroke-width="1"/>'
             f'<line class="fs-h" x1="{L}" x2="{w - R}" stroke="var(--muted)" stroke-width="1" stroke-dasharray="3 3"/>'
             f'<circle class="fs-c" r="4" fill="{COL["rule"]}" stroke="var(--card)" stroke-width="2"/>'
             f'<g class="fs-yc"><rect x="0" y="-8" width="{L - 3}" height="16" rx="3" fill="var(--fg)"/><text x="{L - 7}" y="3.5" text-anchor="end" font-size="10" fill="var(--bg)" class="fs-yt"></text></g>'
             f'<g class="fs-xc"><rect y="{h - 19}" width="92" height="16" rx="3" fill="var(--fg)" class="fs-xr"/><text y="{h - 7.5}" text-anchor="middle" font-size="10" fill="var(--bg)" class="fs-xt"></text></g></g>')
    o.append(f'<rect class="fs-ov" x="{L}" y="{T}" width="{w - L - R}" height="{bot - T}" fill="transparent" style="cursor:crosshair;touch-action:none"/>')
    o.append("</svg>")
    d.update({"w": w, "h": h, "L": L, "R": R, "T": T, "ph": ph})
    return "".join(o), d


def svg_st(did, d, w=460, h=200):
    """One bar per stretch of extra weeks: the rule's log return minus the switch's over the stretch's span (percentage points); positive up. Hover: ST_JS."""
    L, R, T, B = 44, 8, 8, 22
    vals = d["diff"]
    hi, lo = max(max(vals), 0.0), min(min(vals), 0.0)
    pad = (hi - lo) * 0.08 or 0.01
    hi, lo = hi + pad, lo - pad
    n = len(vals)
    Y = lambda v: T + (h - T - B) * (1 - (v - lo) / (hi - lo))
    slot = (w - L - R) / n
    o = [f'<svg viewBox="0 0 {w} {h}" class="chart sb" role="img" aria-label="{E(did)}" data-id="{E(did)}">']
    step = next(s_ for s_ in (0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5) if (hi - lo) / s_ <= 7)
    k0_ = math.ceil(lo / step - 1e-9)
    while k0_ * step <= hi:
        t = round(k0_ * step, 6)
        o.append(f'<line x1="{L}" x2="{w - R}" y1="{Y(t):.1f}" y2="{Y(t):.1f}" class="grid"/><text x="{L - 4}" y="{Y(t) + 3:.1f}" text-anchor="end" class="ax">{100 * t + 0:+.1f}</text>')
        k0_ += 1
    o.append(f'<line x1="{L}" x2="{w - R}" y1="{Y(0):.1f}" y2="{Y(0):.1f}" stroke="var(--fg)" stroke-width="1"/>')
    for i, v in enumerate(vals):
        y0, y1 = Y(0), Y(v)
        o.append(f'<rect x="{L + slot * i + slot * 0.15:.1f}" y="{min(y0, y1):.1f}" width="{slot * 0.7:.1f}" height="{max(abs(y1 - y0), 0.6):.1f}" fill="{BCOL[2] if v > 0 else BCOL[1]}" opacity="0.8"/>')
        o.append(f'<text x="{L + slot * (i + 0.5):.1f}" y="{h - 8}" text-anchor="middle" class="ax">{d["first"][i][2:4]}</text>')
    bot = h - B
    o.append('<g class="sb-hv" style="display:none" pointer-events="none">'
             f'<rect class="sb-b" y="{T}" height="{bot - T}" width="{slot:.1f}" fill="var(--fg)" opacity="0.08"/>'
             f'<line class="sb-h" x1="{L}" x2="{w - R}" stroke="var(--muted)" stroke-width="1" stroke-dasharray="3 3"/>'
             f'<g class="sb-yc"><rect x="0" y="-8" width="{L - 3}" height="16" rx="3" fill="var(--fg)"/><text x="{L - 7}" y="3.5" text-anchor="end" font-size="10" fill="var(--bg)" class="sb-yt"></text></g>'
             f'<g class="sb-xc"><rect y="{h - 17}" width="70" height="14" rx="3" fill="var(--fg)" class="sb-xr"/><text y="{h - 6}" text-anchor="middle" font-size="10" fill="var(--bg)" class="sb-xt"></text></g></g>')
    o.append(f'<rect class="sb-ov" x="{L}" y="{T}" width="{w - L - R}" height="{bot - T}" fill="transparent" style="cursor:crosshair;touch-action:none"/>')
    o.append("</svg>")
    d.update({"w": w, "h": h, "L": L, "R": R, "T": T, "B": B, "lo": lo, "hi": hi})
    return "".join(o), d


TIPPOS = """  var fr=fig.getBoundingClientRect(),px=e.clientX-fr.left+14,py=e.clientY-fr.top+14;
  if(px+tip.offsetWidth>fr.width)px=e.clientX-fr.left-tip.offsetWidth-14;
  if(py+tip.offsetHeight>fr.height)py=Math.max(0,e.clientY-fr.top-tip.offsetHeight-14);
  px=Math.max(0,Math.min(px,fr.width-tip.offsetWidth));tip.style.left=px+'px';tip.style.top=py+'px';"""

LINES_JS = """(function(){
var all=JSON.parse(document.getElementById('lines-data').textContent);
function fx(d,v){return d.fmt==='pct'?(100*v).toFixed(1)+'%%':v.toFixed(2)+'\\u00d7'}
Array.prototype.forEach.call(document.querySelectorAll('svg.lc'),function(svg){
 var d=all[svg.getAttribute('data-id')],fig=svg.parentNode,tip=fig.querySelector('.tip'),g=svg.querySelector('.lc-hv'),ov=svg.querySelector('.lc-ov'),
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
  vy=Math.max(top,Math.min(top+hgt,vy));
  hl.setAttribute('y1',vy);hl.setAttribute('y2',vy);yc.setAttribute('transform','translate(0,'+vy+')');
  var f=1-(vy-top)/hgt,lv=d.lo+f*(d.hi-d.lo);q('.lc-yt').textContent=fx(d,d.log?Math.exp(lv):lv);
  var xr=q('.lc-xr'),xl=Math.max(0,Math.min(d.w-92,x-46));
  xr.setAttribute('x',xl);q('.lc-xt').setAttribute('x',xl+46);q('.lc-xt').textContent=d.dates[j];
  var s='<b>'+d.dates[j]+'</b>';
  for(var n=0;n<d.series.length;n++)s+='<br><i style="background:'+d.series[n].col+'"></i>'+d.series[n].label+': <b>'+fx(d,d.series[n].v[j])+'</b>';
  tip.innerHTML=s;tip.hidden=false;
%s
 }
 function out(){g.style.display='none';tip.hidden=true}
 ov.addEventListener('pointermove',move);ov.addEventListener('pointerdown',move);ov.addEventListener('pointerleave',out);
});
})();""" % TIPPOS

BARS_JS = """(function(){
var all=JSON.parse(document.getElementById('bars-data').textContent);
function f(k,v){if(k==='pct')return (100*v).toFixed(1)+'%%';if(k==='int')return Math.round(v).toLocaleString('en-US');return v.toFixed(4)}
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
  for(var n=0;n<d.series.length;n++){var S=d.series[n];s+='<br><i style="background:'+S.col+'"></i>'+S.label+': <b>'+S.v[b].toLocaleString('en-US')+'</b> '+d.yunit+' ('+(100*S.v[b]/S.n).toFixed(2)+'%%)'}
  for(var m=0;m<d.marks.length;m++){var M=d.marks[m];s+='<br>'+M.label+': <b>'+f(d.xk,M.x)+'</b> '+M.txt+(M.x>=d.edges[b]&&M.x<d.edges[b+1]?' (in this bin)':'')}
  tip.innerHTML=s;tip.hidden=false;
%s
 }
 function out(){g.style.display='none';tip.hidden=true}
 ov.addEventListener('pointermove',move);ov.addEventListener('pointerdown',move);ov.addEventListener('pointerleave',out);
});
})();""" % TIPPOS

FS_JS = """(function(){
var all=JSON.parse(document.getElementById('fs-data').textContent);
var SIGN=['Nifty 100','Midcap 100','Smallcap 100'];
Array.prototype.forEach.call(document.querySelectorAll('svg.fs'),function(svg){
 var d=all[svg.getAttribute('data-id')],fig=svg.parentNode,tip=fig.querySelector('.tip'),g=svg.querySelector('.fs-hv'),ov=svg.querySelector('.fs-ov'),c=svg.querySelector('.fs-c'),q=function(s){return svg.querySelector(s)};
 function X(j){return d.L+(d.w-d.L-d.R)*j/d.n}
 function Y(f){return d.T+d.ph*(1-f)}
 function move(e){
  var r=svg.getBoundingClientRect(),k=d.w/r.width,vx=(e.clientX-r.left)*k,vy=(e.clientY-r.top)*k;
  var j=Math.max(0,Math.min(d.n-1,Math.floor((vx-d.L)/(d.w-d.L-d.R)*d.n))),x=X(j+0.5);
  g.style.display='';
  q('.fs-v').setAttribute('x1',x);q('.fs-v').setAttribute('x2',x);c.setAttribute('cx',x);c.setAttribute('cy',Y(d.fs[j]));
  var inP=vy>=d.T&&vy<=d.T+d.ph,h=q('.fs-h'),yc=q('.fs-yc');
  h.style.display=yc.style.display=inP?'':'none';
  if(inP){h.setAttribute('y1',vy);h.setAttribute('y2',vy);yc.setAttribute('transform','translate(0,'+vy+')');q('.fs-yt').textContent=(1-(vy-d.T)/d.ph).toFixed(2)}
  var xr=q('.fs-xr'),xl=Math.max(0,Math.min(d.w-92,x-46));xr.setAttribute('x',xl);q('.fs-xt').setAttribute('x',xl+46);q('.fs-xt').textContent=d.dates[j];
  var t='<b>'+d.dates[j]+'</b> (decision '+(j+1)+' of '+d.n+')<br>FS = k / n = <b>'+d.k[j]+' / '+d.nn[j]+' = '+d.fs[j].toFixed(3)+'</b>; 5k = '+5*d.k[j]+' '+(5*d.k[j]>=3*d.nn[j]?'>=':'<')+' 3n = '+3*d.nn[j]+'<br>';
  for(var n=0;n<3;n++)t+=SIGN[n]+' '+(d.pat[j][n]==='B'?'BUY':'SELL')+(n<2?', ':'');
  t+='<br>FS rule: <b>'+(d.rule[j]?'IN':'OUT')+'</b>; three-index switch: <b>'+(d.sw[j]?'IN':'OUT')+'</b>';
  t+='<span class="sub">'+(d.extra[j]?d.tips[d.str[j]]:'Not an extra week (the rule and the switch agree, or both OUT).')+'</span>';
  tip.innerHTML=t;tip.hidden=false;
%s
 }
 function out(){g.style.display='none';tip.hidden=true}
 ov.addEventListener('pointermove',move);ov.addEventListener('pointerdown',move);ov.addEventListener('pointerleave',out);
});
})();""" % TIPPOS

ST_JS = """(function(){
var all=JSON.parse(document.getElementById('st-data').textContent);
Array.prototype.forEach.call(document.querySelectorAll('svg.sb'),function(svg){
 var d=all[svg.getAttribute('data-id')],fig=svg.parentNode,tip=fig.querySelector('.tip'),g=svg.querySelector('.sb-hv'),ov=svg.querySelector('.sb-ov'),q=function(s){return svg.querySelector(s)};
 var n=d.diff.length,slot=(d.w-d.L-d.R)/n,ph=d.h-d.T-d.B;
 function pp(v){return (100*v>=0?'+':'')+(100*v).toFixed(1)}
 function move(e){
  var r=svg.getBoundingClientRect(),k=d.w/r.width,vx=(e.clientX-r.left)*k,vy=(e.clientY-r.top)*k;
  var i=Math.max(0,Math.min(n-1,Math.floor((vx-d.L)/slot)));
  g.style.display='';
  q('.sb-b').setAttribute('x',d.L+slot*i);
  vy=Math.max(d.T,Math.min(d.T+ph,vy));
  q('.sb-h').setAttribute('y1',vy);q('.sb-h').setAttribute('y2',vy);q('.sb-yc').setAttribute('transform','translate(0,'+vy+')');
  q('.sb-yt').textContent=pp(d.lo+(1-(vy-d.T)/ph)*(d.hi-d.lo));
  var xr=q('.sb-xr'),xl=Math.max(0,Math.min(d.w-70,d.L+slot*(i+0.5)-35));xr.setAttribute('x',xl);q('.sb-xt').setAttribute('x',xl+35);q('.sb-xt').textContent='stretch '+(i+1)+' of '+n;
  var t='<b>Stretch '+(i+1)+' of '+n+'</b>: decisions '+d.first[i]+' to '+d.last[i]+', '+d.weeks[i]+' week(s), mean k/n '+d.mfs[i].toFixed(3)
   +'<span class="sub">Span '+d.s0[i]+' to '+d.s1[i]+' (closes)</span>FS rule: <b>'+pp(d.rule[i])+'</b>; switch: <b>'+pp(d.sw[i])+'</b>; rule minus switch: <b>'+pp(d.diff[i])+'</b> (percentage points of log return)';
  tip.innerHTML=t;tip.hidden=false;
%s
 }
 function out(){g.style.display='none';tip.hidden=true}
 ov.addEventListener('pointermove',move);ov.addEventListener('pointerdown',move);ov.addEventListener('pointerleave',out);
});
})();""" % TIPPOS

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
.hv{position:relative;margin:10px 0}.tip{position:absolute;z-index:5;pointer-events:none;background:var(--card);border:1px solid var(--line);border-radius:6px;padding:6px 9px;font-size:12px;line-height:1.5;white-space:nowrap;box-shadow:0 2px 8px rgba(0,0,0,.18);font-variant-numeric:tabular-nums}.tip b{font-weight:600}.tip i{display:inline-block;width:10px;height:3px;margin-right:6px;vertical-align:middle}.tip .sub{color:var(--muted);white-space:normal;display:block;max-width:300px;margin-top:3px}
.answer{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--warn);border-radius:6px;padding:12px 16px}.nonull{background:var(--card);border:1px solid var(--warn);border-radius:6px;padding:8px 12px;margin:10px 0;font-weight:600}
@media (max-width:640px){.two{grid-template-columns:1fr}h1{font-size:22px}}
"""


def caveats_from(doc: str):
    """The five numbered tag caveats of T10.md section 3 (plain text) and the sentence that follows them."""
    i = doc.index("**Caveats, to be stated on the page**")
    j = doc.index("\n", i)
    para = md_plain(doc[i:j].replace("\r", ""))
    para = para.split("):", 1)[1].strip()
    tail = ""
    m = re.search(r"\s*T10 reads tags at every weekly decision", para)
    if m:
        tail = para[m.start():].strip()
        para = para[:m.start()].strip()
    parts = re.split(r"\s*\((\d)\)\s*", para)
    return [parts[k + 1].strip() for k in range(1, len(parts) - 1, 2)], tail


def header_line(doc: str, label: str) -> str:
    for l in doc.splitlines():
        if l.startswith(f"**{label}:**"):
            return md_plain(l.split(":**", 1)[1]).strip()
    return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="headline")
    ap.add_argument("--evidence", default=None)
    ap.add_argument("--doc", default=str(HERE / "T10.md"))
    ap.add_argument("--books", default=None)
    a = ap.parse_args()
    ev_dir = Path(a.evidence) if a.evidence else HERE / "evidence" / a.run
    R = json.loads((ev_dir / "analysis.json").read_text(encoding="utf-8"))
    BOOKS = R["meta"]["books"]
    pg = Page(R)
    N = pg.N
    if not R["gates"]["all"]:
        raise SystemExit("analysis.json says a gate failed: no page is built")
    dec = pd.read_csv(ev_dir / "decisions.csv")
    nav = pd.read_csv(ev_dir / "daily_nav.csv", parse_dates=["date"])
    stc = pd.read_csv(ev_dir / "stretches.csv")
    r4 = pd.read_csv(ev_dir / "r4_tag_error.csv")
    inp = pd.read_csv(ev_dir / "inputs.csv", comment="#", dtype=str, keep_default_na=False)
    doc = Path(a.doc).read_text(encoding="utf-8")
    logtxt = (ev_dir / "analysis.log").read_text(encoding="utf-8")
    mg = re.search(r"^Gates: (\{.*\}) ->", logtxt, re.M)
    gate_line = ast.literal_eval(mg.group(1)) if mg else None
    caveats, caveat_tail = caveats_from(doc)
    asof_m = re.search(r"\*\*As of: (\d{4}-\d{2}-\d{2})", (AA / "data" / "APPROVED_DATA.md").read_text(encoding="utf-8"))
    asof = asof_m.group(1) if asof_m else "?"
    M = R["meta"]
    start, end, live_first = M["start"], M["end"], M["live_first"]
    b0 = BOOKS[0]
    b7 = "SCMO_0007" if "SCMO_0007" in BOOKS else BOOKS[-1]
    CH = f"crit{SEP}full|lbes|20.8"

    def NAV(b, run, cost=PRIMARY):
        d = nav[(nav.book == b) & (nav.run == run)]
        if run != "published_parent":
            d = d[np.isclose(d.cost_bps.astype(float), cost)]
        return d.sort_values("date").reset_index(drop=True)

    # ── charts ────────────────────────────────────────────────────────────────────────────────────
    lines_data, fs_data, st_data, bars_data = {}, {}, {}, {}
    curves_html = ""
    for b in BOOKS:
        ser = {k_: NAV(b, k_).nav.values for k_ in ("rule", "switch", "parent", "constant_mix", "published_parent")}
        dates = list(NAV(b, "rule").date)
        eq_svg, eq_d = svg_lines(f"eq|{b}", ser, dates, "eq")
        ddser = {k_: v / np.maximum.accumulate(v) - 1 for k_, v in ser.items()}
        dd_svg, dd_d = svg_lines(f"dd|{b}", ddser, dates, "dd")
        lines_data[f"eq|{b}"], lines_data[f"dd|{b}"] = eq_d, dd_d
        H = f"headline{SEP}{b}"
        curves_html += (f'<h3>{E(b)}</h3><div class="two"><figure class="card hv"><figcaption>Growth of 1 invested at the close of {dates[0].date()}, log scale, to {dates[-1].date()}, {PRIMARY:g} bps · rule ends at {N(H + SEP + "rule" + SEP + "end_nav", "n2")}×. '
                        f'Hover: the date and the level at the pointer; the tooltip lists the five curves (drawn every {DOWNSAMPLE}th session).</figcaption>{eq_svg}<div class="tip" hidden></div></figure>'
                        f'<figure class="card hv"><figcaption>Drawdown from the running peak, {dates[0].date()} to {dates[-1].date()}, {PRIMARY:g} bps · rule worst {N(H + SEP + "rule" + SEP + "max_dd", "pc1")}, switch {N(H + SEP + "switch" + SEP + "max_dd", "pc1")}, '
                        f'parent {N(H + SEP + "parent" + SEP + "max_dd", "pc1")}. Hover as on the left.</figcaption>{dd_svg}<div class="tip" hidden></div></figure></div>')
    legend = "".join(f'<span class="key"><i style="background:{COL[k_]}"></i>{E(LAB[k_])}{" (dashed)" if k_ in DASH else ""}</span>' for k_ in COL)

    fs_html = ""
    for b in BOOKS:
        d = dec[(dec.book == b) & (dec.window == "full")].sort_values("j").reset_index(drop=True)
        ex = asbool(d["extra"])
        runs, tips, strno = [], [], [-1] * len(d)
        j = 0
        while j < len(d):
            if ex[j]:
                j2 = j
                while j2 + 1 < len(d) and ex[j2 + 1]:
                    j2 += 1
                runs.append((j, j2))
                for q in range(j, j2 + 1):
                    strno[q] = len(runs) - 1
                j = j2 + 1
            else:
                j += 1
        for i, (a_, b_) in enumerate(runs):
            tips.append(f"Extra stretch {i + 1} of {len(runs)}: decisions {d.decision_date.iloc[a_]} to {d.decision_date.iloc[b_]}, {b_ - a_ + 1} week(s): the rule is IN while the switch is OUT")
        fd = {"n": len(d), "dates": [str(x) for x in d.decision_date], "fs": [round(float(x), 6) for x in d.fs], "k": [int(x) for x in d.k_on], "nn": [int(x) for x in d.n_held], "pat": list(d.pattern),
              "rule": [int(x) for x in d.state_rule], "sw": [int(x) for x in d.state_switch], "extra": [int(x) for x in ex], "str": strno, "tips": tips}
        svg, fd = svg_fs(f"fs|{b}", fd)
        fs_data[f"fs|{b}"] = fd
        fs_html += (f'<figure class="card hv"><figcaption><b>{E(b)}</b>: FS = k / n at each weekly decision, {d.decision_date.iloc[0]} to {d.decision_date.iloc[-1]} ({len(d)} decisions), with the 0.60 line. Shaded: the {len(ex[ex])} extra weeks '
                    f'(rule IN, switch OUT) in {len(runs)} stretches. Strips: each signal (filled = BUY), the FS rule (filled = IN), the switch (filled = IN). Hover: the week, k / n, 5k against 3n, the signals, both states and the stretch.</figcaption>'
                    f'{svg}<div class="tip" hidden></div></figure>')
    st_html = ""
    for b in BOOKS:
        s = stc[(stc.book == b) & (stc.window == "full") & (stc.stretch_no > 0)].sort_values("stretch_no").reset_index(drop=True)
        sd = {"first": list(s.first_decision_date), "last": list(s.last_decision_date), "weeks": [int(x) for x in s.weeks], "mfs": [round(float(x), 6) for x in s.mean_fs], "s0": list(s.span_start_date), "s1": list(s.span_end_date),
              "rule": [round(float(x), 6) for x in s.rule_log_return], "sw": [round(float(x), 6) for x in s.switch_log_return], "diff": [round(float(x), 6) for x in s.diff_log_return]}
        svg, sd = svg_st(f"st|{b}", sd)
        st_data[f"st|{b}"] = sd
        st_html += (f'<figure class="card hv"><figcaption><b>{E(b)}</b>: rule minus switch, log return in percentage points, over each of the {len(s)} stretches of extra weeks, {start[b]} to {end}, {PRIMARY:g} bps. '
                    f'Green = the rule was ahead over that span. Labels are the year of the stretch. Hover for the dates and both returns.</figcaption>{svg}<div class="tip" hidden></div></figure>')
    hist_html = ""
    for b in BOOKS:
        g = r4[r4.book == b].diff_vs_switch.values
        pt = R["r4"][b]["point"]
        lo_, hi_ = min(g.min(), 0.0, pt), max(g.max(), 0.0, pt)
        span = hi_ - lo_ or 0.01
        lo_, hi_ = lo_ - 0.03 * span, hi_ + 0.03 * span
        nb_ = 20
        edges = np.linspace(lo_, hi_, nb_ + 1)
        cnt, _ = np.histogram(g, bins=edges)
        binlab = [f"{100 * edges[i]:+.2f} to {100 * edges[i + 1]:+.2f} pp" for i in range(nb_)]
        series = [{"k": "r4", "label": "R4 draws", "col": COL["rule"], "v": cnt, "n": len(g), "op": 0.6}]
        marks = [{"label": "Unperturbed rule", "x": pt, "col": COL["switch"], "txt": f"({100 * pt:+.2f} pp; rule CAGR minus switch CAGR)"},
                 {"label": "Zero (rule = switch)", "x": 0.0, "col": COL["constant_mix"], "txt": "(no difference)", "dash": True}]
        svg, bd = svg_bars(f"r4|{b}", edges, series, marks, xk="pct", yk="int", xticks=[(float(v), f"{100 * v:+.1f}") for v in np.linspace(lo_, hi_, 5)], binlab=binlab)
        bars_data[f"r4|{b}"] = bd
        x = R["r4"][b]
        hist_html += (f'<figure class="card hv"><figcaption><b>{E(b)}</b>: rule CAGR minus switch CAGR over {N("r4" + SEP + b + SEP + "n", "int")} tag-error draws (percentage points), full window {start[b]} to {end}, {PRIMARY:g} bps. '
                      f'Black line = the unperturbed rule ({N("r4" + SEP + b + SEP + "point", "pp2")}), dashed = zero. {N("r4" + SEP + b + SEP + "n_pos", "int")} of {N("r4" + SEP + b + SEP + "n", "int")} draws are above zero. '
                      f'A sensitivity of the data to the tag error, not a null: it has no pass mark.</figcaption>{svg}<div class="tip" hidden></div></figure>')

    # ── page sections ─────────────────────────────────────────────────────────────────────────────
    ex_ = R["example"]
    HY = {"C1": ("H1", "Return against the parent: rule CAGR above the hold-the-parent CAGR"), "C2": ("H2", "Protection against the parent: rule maximum drawdown shallower than the parent's"),
          "C3": ("H3", "Increment against the switch: rule CAGR above the three-index switch's"), "C4": ("H4", "Risk-adjusted against the switch: rule Calmar at least the switch's")}
    nrep = [b for b in BOOKS if not R["crit"]["full|lbes|20.8"]["books"][b]["reportable"]]
    verdict_rows = [[c_, E(HY[c_][0]), E(HY[c_][1]), N(f"{CH}{SEP}count{SEP}{c_}", "int") + f" of {len(BOOKS)}", N(f"{CH}{SEP}pass{SEP}{c_}", "pf")] for c_ in ("C1", "C2", "C3", "C4")]
    outcome = "".join(f"<li>{E(x)}</li>" for x in R["outcome_map"]) or "<li>(none of the listed patterns)</li>"
    gates_txt = " ".join(f"{k_} {v_}" for k_, v_ in (gate_line or {}).items())
    answer = f"""<div class="answer"><p class="eyebrow">T10 · IN PROGRESS · run {E(M['run'])} · data as of {E(asof)} · window {E(start[b0])} to {E(end)}</p>
<p><b>The question.</b> Does holding the whole parent while the weekly FS score is at least 0.60 (segment_v2's production rule) do better, after cost, than holding the parent, or than the three-index switch, on the latest approved data?
FS = the share (by count) of the stocks the parent holds whose Large / Mid / Small-and-below band has a BUY supertrend (Nifty 100 / Midcap 100 / Smallcap 100). Below 0.60 the book holds 50% GOLDBEES and 50% cash.</p>
<p class="nonull">There is no null and no random draws in the four criteria (Manu waived it, 2026-11-12): {NOCHANCE}. Nothing on this page says the rule beats chance, and no finding from this test is stronger than PROVISIONAL.</p>
<p><b>Verdicts</b> (after cost at {PRIMARY:g} bps, full window {E(start[b0])} to {E(end)}; each criterion passes if at least 3 of the 4 books pass; the four books share one market, one set of signals and the same weeks of difference, so 3 of 4 is a consistency check):</p>
{fmt_table(verdict_rows, ["criterion", "hypothesis", "what is compared", "books passing", "verdict"])}
<p class="mini">Outcome map rows that apply (T10.md section 2; {NOCHANCE}):</p><ul>{outcome}</ul>
<p class="mini">Validity gates: {E(gates_txt)}. {('NOT REPORTABLE for C3 and C4: ' + ', '.join(nrep) + '.') if nrep else 'All four books clear the 5-stretch reportability gate on the full window.'} Pre-registration sha256 {E(M['prereg_recomputed'][:16])} (header {E(M['prereg_header'][:16])}).</p></div>"""

    inputs_rows = [[E(r_.file), E(r_.through), E(r_.approved_row), E(r_.sha256[:16])] for r_ in inp.itertuples()]
    data_sec = f"""<h2>2 · The data</h2>
<p>{E(header_line(doc, 'Data boundary'))}</p>
<p>{E(header_line(doc, 'Prices and cash'))}</p>
<p>Windows: <b>full</b> = {E(start[b0])} to {E(end)} ({E(b7)} from {E(start[b7])}, the first date of its published NAV); <b>live</b> = {E(live_first[b0])} (the first session on or after 2021-11-01) to {E(end)}. The decisions before 2021-11 are a backfill by the production code, not signals traded at the time.
The universe is the four parents of the AA books: {E(', '.join(BOOKS))}.</p>
<p class="mini">Inputs the run opened (inputs.csv: path, through-date, approved row of data/APPROVED_DATA.md as of {E(asof)}, sha256 prefix):</p>
{fmt_table(inputs_rows, ["file", "through", "approved row", "sha256 (16)"])}
<h3>The tag data and its limits</h3>
<p>The weekly tag of every stock comes from the shared tag rule (reviewed 2026-11-12). The caveats of the review, which apply to every number on this page:</p>
<ol>{''.join(f'<li>{E(c_)}</li>' for c_ in caveats)}</ol><p>{E(caveat_tail)}</p>
<p>Share of the weekly tag reads that use the rank rule, full window: {', '.join(f'{E(b)} {N("tag_sources" + SEP + b + SEP + "rank_share", "pc1")}' for b in BOOKS)}.</p>"""

    # worked example
    ek = "example"
    st_rows = [[E(s["stock"]), N(f"{ek}{SEP}stk{SEP}{i}{SEP}w", "n4"), E(s["band"]), E(s["src"]), E(str(s["snap"])), E("" if s["detail"] is None else str(s["detail"])), E(SIGLAB[SIGS[BANDS.index(s["band"])]]), E(s["sig"]), N(f"{ek}{SEP}stk{SEP}{i}{SEP}on", "yn")]
               for i, s in enumerate(ex_["stk"])]
    fill_rows = [[E(f["stock"]), N(f"{ek}{SEP}stocks{SEP}{i}{SEP}open", "n2"), N(f"{ek}{SEP}stocks{SEP}{i}{SEP}high", "n2"), N(f"{ek}{SEP}stocks{SEP}{i}{SEP}low", "n2"), N(f"{ek}{SEP}stocks{SEP}{i}{SEP}close_bar", "n2"),
                  N(f"{ek}{SEP}stocks{SEP}{i}{SEP}ohlc4", "n4"), N(f"{ek}{SEP}stocks{SEP}{i}{SEP}target", "n6"), N(f"{ek}{SEP}stocks{SEP}{i}{SEP}units", "n6"), N(f"{ek}{SEP}stocks{SEP}{i}{SEP}value_close", "n6")] for i, f in enumerate(ex_["stocks"])]
    around = [[E(x["date"]), N(f"{ek}{SEP}around{SEP}{i}{SEP}rule", "n6"), N(f"{ek}{SEP}around{SEP}{i}{SEP}switch", "n6"), N(f"{ek}{SEP}around{SEP}{i}{SEP}parent", "n6")] for i, x in enumerate(ex_["around"])]
    sn = ex_["switch_next"]
    example_sec = f"""<h2>3 · One decision, end to end ({E(ex_['book'])}, decision of {E(ex_['decision_date'])})</h2>
<p>One real weekly decision, picked by a stated rule and not for its result: the first week of the full window ({E(start[ex_['book']])} to {E(end)}) in which the rule is IN, the three-index switch is OUT and the rule trades. Every number is printed from the evidence; the stock prices are from the approved OHLC file (D18).
It is decision no. {N(ek + SEP + 'decision_no', 'int')} of {N(ek + SEP + 'n_decisions', 'int')}, made at the close of {E(ex_['decision_date'])} ({E(ex_['weekday'])}).</p>
<h3>Step 1 · the basket in force</h3><p>The latest non-skipped basket with availableDate on or before {E(ex_['decision_date'])} is the basket of {E(ex_['basket_eff'])}: {N(ek + SEP + 'n', 'int')} stocks with listed weight above zero (weights renormalised to sum to 1, as in T06).</p>
<h3>Step 2 · tag every stock as of {E(ex_['decision_date'])}</h3>
{fmt_table(st_rows, ["stock", "listed weight", "band", "source", "snapshot", "rank", "band's index", "SIGN", "band on"])}
<p class="mini">'rank' = the stock's rank on the market-cap snapshot (1 to 100 Large, 101 to 250 Mid, above 250 Small and below). Before 2026-04-09 only the rank rule exists. A band is on if its index's SIGN is BUY.</p>
<h3>Step 3 · the three signals</h3><p>The latest Master row of each index on or before the decision date: Nifty 100 {E(ex_['signs'][0])} (row dated {E(ex_['labels'][0])}), Midcap 100 {E(ex_['signs'][1])} (row dated {E(ex_['labels'][1])}), Smallcap 100 {E(ex_['signs'][2])} (row dated {E(ex_['labels'][2])}): pattern {E(ex_['pattern'])}.</p>
<h3>Step 4 · the FS score and the decision</h3>
<div class="formula">n = stocks held = {N(ek + SEP + 'n', 'int')}   (Large {N(ek + SEP + 'n_band' + SEP + '0', 'int')}, Mid {N(ek + SEP + 'n_band' + SEP + '1', 'int')}, Small and below {N(ek + SEP + 'n_band' + SEP + '2', 'int')})
k = stocks whose band is on = {N(ek + SEP + 'k', 'int')}
FS = k ÷ n = {N(ek + SEP + 'k', 'int')} ÷ {N(ek + SEP + 'n', 'int')} = {N(ek + SEP + 'fs', 'n3')}
rule: IN iff 5k ≥ 3n (FS ≥ 0.60 decided in integers): 5 × {N(ek + SEP + 'k', 'int')} = {N(ek + SEP + 'lhs', 'int')} against 3 × {N(ek + SEP + 'n', 'int')} = {N(ek + SEP + 'rhs', 'int')}  →  {E(ex_['state_rule'])}
switch: IN iff the pattern is BBB; {E(ex_['pattern'])}  →  {E(ex_['state_switch'])}   (an extra week: the rule is IN while the switch is OUT)</div>
<p class="mini">FS weighted by the listed weights ({N(ek + SEP + 'weight_fs', 'n3')}) is robustness R6 only; it plays no part in the decision.</p>
<h3>Step 5 · the trade</h3>
<p>The decision is made at the close of {E(ex_['decision_date'])}; the trade is on the next session, {E(ex_['trade_date'])} (session no. {N(ek + SEP + 'trade_idx', 'int')} of {N('meta' + SEP + 'sessions' + SEP + ex_['book'] + SEP + 'full', 'int')}), at each instrument's OHLC4 = (open + high + low + close) ÷ 4 of that session. The book held {E(ex_['state_before'])} (50% GOLDBEES, 50% cash).</p>
<div class="formula">V = the book's value at that session's fill prices before cost = {N(ek + SEP + 'V', 'n6')}      (NAV is 1.000 at the close of {E(start[ex_['book']])})
target for stock i = V × w_i; GOLDBEES and cash 0 (so the whole sleeve, {N(ek + SEP + 'V', 'n6')}, is sold and {N(ek + SEP + 'V', 'n6')} of stocks is bought)
traded = Σ |target − current| over stocks, GOLDBEES and cash = {N(ek + SEP + 'traded', 'n6')}
cost = traded × {PRIMARY:g} ÷ 2 ÷ 10,000 = {N(ek + SEP + 'traded', 'n6')} × {PRIMARY / 2 / 1e4:.6f} = {N(ek + SEP + 'cost', 'n6')}
every new position is scaled by (V − cost) ÷ V = {N(ek + SEP + 'kc', 'n8')}      units_i = V × w_i × that ÷ OHLC4_i</div>
{fmt_table(fill_rows, ["stock", "open", "high", "low", "close", "OHLC4 fill", "target value", "units bought", f"value at the close of {ex_['trade_date']}"])}
<p>Sum of units × close on {E(ex_['trade_date'])} reproduces the NAV after the trade in trades.csv, {N(ek + SEP + 'nav_after_close', 'n6')} (difference {N(ek + SEP + 'sum_units_close_diff', 'sci')}). The GOLDBEES fill and the cash level are not shown here; the sleeve is simply sold in full.</p>
<h3>Step 6 · the daily NAV around the trade, with the switch beside it</h3>
{fmt_table(around, ["date", "FS rule NAV", "switch NAV", "parent NAV"])}
<p>NAV_t = Σ stock units × close + GOLDBEES units × close + cash units × level, 1.000 at the close of {E(start[ex_['book']])}, {PRIMARY:g} bps. The switch stays OUT{(' until its own event on ' + E(sn['date']) + ' (' + E(sn['kind']) + ', state after: ' + E(sn['state_after']) + ')') if sn else ''}.</p>
<h3>Step 7 · the equity curve and its statistics</h3>
<p>The rule's path runs {E(ex_['start'])} to {E(ex_['end'])}: {N(ek + SEP + 'sessions', 'int')} sessions, end NAV {N(ek + SEP + 'end_nav', 'n4')}.</p>
<div class="formula">CAGR = end NAV ^ (252 ÷ (sessions − 1)) − 1 = {N(ek + SEP + 'end_nav', 'n4')} ^ (252 ÷ {N(ek + SEP + 'sessions', 'int')} − 1) − 1 = {N(ek + SEP + 'cagr', 'pc2')}
max drawdown = min over t of NAV_t ÷ (max NAV up to t) − 1 = {N(ek + SEP + 'max_dd', 'pc2')}   (peak {N(ek + SEP + 'dd_peak', 'n4')} on {E(ex_['dd_peak_date'])}, trough {N(ek + SEP + 'dd_trough', 'n4')} on {E(ex_['dd_trough_date'])})</div>
<h3>Step 8 · the comparators on the same path</h3>
<p>{E(ex_['start'])} to {E(ex_['end'])}, {PRIMARY:g} bps: three-index switch CAGR {N(ek + SEP + 'switch' + SEP + 'cagr', 'pc2')}, max drawdown {N(ek + SEP + 'switch' + SEP + 'max_dd', 'pc2')}; hold the parent CAGR {N(ek + SEP + 'parent' + SEP + 'cagr', 'pc2')}, max drawdown {N(ek + SEP + 'parent' + SEP + 'max_dd', 'pc2')}. {NOCHANCE.capitalize()}.</p>"""

    # headline tables
    rows1, rows2 = [], []
    for b in BOOKS:
        p = f"{CH}{SEP}books{SEP}{b}{SEP}"
        rows1.append([E(b), N(p + "rule_cagr", "pc1"), N(p + "parent_cagr", "pc1"), N(p + "C1", "pf"), N(p + "rule_dd", "pc1"), N(p + "parent_dd", "pc1"), N(p + "C2", "pf")])
        rows2.append([E(b), N(p + "stretches", "int"), N(p + "reportable", "rep"), N(p + "rule_cagr", "pc1"), N(p + "switch_cagr", "pc1"), N(p + "C3", "pf"), N(p + "rule_calmar", "n3"), N(p + "switch_calmar", "n3"), N(p + "C4", "pf")])
    head_sec = f"""<h2>4 · The headline and the verdict</h2>
<p class="nonull">After cost at {PRIMARY:g} bps round trip, full window {E(start[b0])} to {E(end)} ({E(b7)} from {E(start[b7])}); LBES cash. {NOCHANCE.capitalize()}: these are differences on one window.</p>
<h3>C1 and C2: the rule against holding the parent</h3>
{fmt_table(rows1, ["book", "rule CAGR", "parent CAGR", "C1", "rule max drawdown", "parent max drawdown", "C2"])}
<p>C1 passes in {N(CH + SEP + 'count' + SEP + 'C1', 'int')} of {len(BOOKS)} books, C2 in {N(CH + SEP + 'count' + SEP + 'C2', 'int')} of {len(BOOKS)} (each needs 3). No reportability gate applies to comparisons with the parent.</p>
<h3>C3 and C4: the rule against the three-index switch</h3>
{fmt_table(rows2, ["book", "stretches of extra weeks", "reportable (≥ 5)", "rule CAGR", "switch CAGR", "C3", "rule Calmar", "switch Calmar", "C4"])}
<p>C3 passes in {N(CH + SEP + 'count' + SEP + 'C3', 'int')} of {len(BOOKS)} books, C4 in {N(CH + SEP + 'count' + SEP + 'C4', 'int')} of {len(BOOKS)}. A book with fewer than 5 separate stretches of extra weeks counts as not passing C3 and C4.</p>
<h3>Growth of 1 and drawdown, per book</h3><div class="legend">{legend}</div>{curves_html}
<h3>FS by week, per book</h3>{fs_html}
<h3>The extra weeks, stretch by stretch (R7)</h3><div class="two">{st_html}</div>"""

    # all-series table
    ser_rows = []
    for b in BOOKS:
        for k_ in KINDS:
            p = f"headline{SEP}{b}{SEP}{k_}{SEP}"
            ser_rows.append([E(b), E(KLAB[k_]), N(p + "cagr", "pc1"), N(p + "max_dd", "pc1"), N(p + "calmar", "n3"), N(p + "vol", "pc1"), N(p + "ulcer", "n2"), N(p + "days_below_10pct", "int"), N(p + "longest_underwater", "int"),
                             N(p + "trades", "int"), N(p + "cost_paid", "n4"), N(p + "share_in", "pc1")])
    boot_rows = [[E(b), N(f"boot{SEP}{b}{SEP}switch{SEP}point", "pp1"), N(f"boot{SEP}{b}{SEP}switch{SEP}lo", "pp1") + " to " + N(f"boot{SEP}{b}{SEP}switch{SEP}hi", "pp1"),
                  N(f"boot{SEP}{b}{SEP}parent{SEP}point", "pp1"), N(f"boot{SEP}{b}{SEP}parent{SEP}lo", "pp1") + " to " + N(f"boot{SEP}{b}{SEP}parent{SEP}hi", "pp1")] for b in BOOKS]
    yl = sorted(R["years"][b0]["rule"], key=int)
    yr_tabs = ""
    for b in BOOKS:
        rows_ = [[E(LAB[run])] + [N(f"years{SEP}{b}{SEP}{run}{SEP}{y}", "pp1") if y in R["years"][b][run] else "" for y in yl] for run in ("rule", "switch", "parent", "constant_mix", "published_parent")]
        yr_tabs += f'<p class="mini">{E(b)}, percent per calendar year (first year from the base 1.000 at the close of {E(start[b])}, last year to {E(end)}):</p>' + fmt_table(rows_, ["series"] + yl)
    detail_sec = f"""<h2>5 · The detail</h2>
<h3>All series (full window, {PRIMARY:g} bps)</h3>
<p class="mini">Each row: {E(start[b0])} to {E(end)} ({E(b7)} from {E(start[b7])}). Days ≥ 10% below = sessions with NAV at least 10% under its running peak; longest underwater in sessions; trades and cost paid (NAV units, base 1.000) of the rebuilt series; share IN = IN decisions ÷ weekly decisions (the constant mix: f, its fixed share in the parent's stocks; the 100% sleeve: 0).
T07's rule is run by the same engine, is not covered by the independent check and is descriptive only.</p>
{fmt_table(ser_rows, ["book", "series", "CAGR", "max DD", "Calmar", "vol", "Ulcer", "days ≥10% below", "longest underwater", "trades", "cost paid", "share IN"])}
<h3>Bootstrap intervals (reported, no pass mark)</h3>
<p class="mini">Rule CAGR minus comparator CAGR over {E(start[b0])} to {E(end)}, {PRIMARY:g} bps; moving blocks of 20 sessions, 1,000 resamples; interval = 2.5th and 97.5th percentile (percentage points). The uncertainty of this window's difference, not a test against chance.</p>
{fmt_table(boot_rows, ["book", "rule − switch", "95% interval", "rule − parent", "95% interval"])}
<h3>Per-year returns</h3>{yr_tabs}"""

    def crit_block(key, title):
        win, cash, cost = key.split("|")
        rows_ = []
        for b in BOOKS:
            p = f"crit{SEP}{key}{SEP}books{SEP}{b}{SEP}"
            rows_.append([E(b), N(p + "rule_cagr", "pc1"), N(p + "parent_cagr", "pc1"), N(p + "C1", "pf"), N(p + "rule_dd", "pc1"), N(p + "parent_dd", "pc1"), N(p + "C2", "pf"),
                          N(p + "stretches", "int"), N(p + "switch_cagr", "pc1"), N(p + "C3", "pf"), N(p + "rule_calmar", "n3"), N(p + "switch_calmar", "n3"), N(p + "C4", "pf")])
        c = f"crit{SEP}{key}{SEP}count{SEP}"
        w0 = start[b0] if win == "full" else live_first[b0]
        return (f"<h3>{E(title)}</h3><p class='mini'>{cost} bps, {win} window {E(w0)} to {E(end)}, {'LBES' if cash == 'lbes' else 'LIQUIDCASE (from 2024-01-24)'} cash. Books passing: C1 {N(c + 'C1', 'int')}, C2 {N(c + 'C2', 'int')}, C3 {N(c + 'C3', 'int')}, C4 {N(c + 'C4', 'int')} of {len(BOOKS)}.</p>"
                + fmt_table(rows_, ["book", "rule CAGR", "parent CAGR", "C1", "rule max DD", "parent max DD", "C2", "stretches", "switch CAGR", "C3", "rule Calmar", "switch Calmar", "C4"]))
    tc_rows = [[E(b), E(KLAB[k_].split(" (")[0])] + [N(f"tc{SEP}{b}{SEP}{k_}{SEP}{c}{SEP}trades", "int") for c in ("0", "20.8", "50")] + [N(f"tc{SEP}{b}{SEP}{k_}{SEP}{c}{SEP}cost_paid", "n4") for c in ("0", "20.8", "50")] for b in BOOKS for k_ in ("rule", "switch", "constant_mix")]
    r4_rows = [[E(b)] + [N(f"r4{SEP}{b}{SEP}{k_}", f_) for k_, f_ in (("n", "int"), ("point", "pp2"), ("mean", "pp2"), ("p5", "pp2"), ("median", "pp2"), ("p95", "pp2"), ("min", "pp2"), ("max", "pp2"), ("n_pos", "int"), ("share_pos", "pc1"), ("wk_mean", "pc2"), ("wk_max", "pc2"))] for b in BOOKS]
    r5_secs = ""
    for b in BOOKS:
        rows_ = [[E(THR_LAB[k_])] + [N(f"r5{SEP}{b}{SEP}{k_}{SEP}{f}", fm) for f, fm in (("cagr", "pc1"), ("max_dd", "pc1"), ("calmar", "n3"), ("share_in", "pc1"), ("events", "int"))] for k_ in THR]
        r5_secs += f"<p class='mini'>{E(b)}:</p>" + fmt_table(rows_, ["threshold t (IN iff k ÷ n ≥ t)", "CAGR", "max DD", "Calmar", "share IN", "events"])
    r6_rows = [[E(b)] + [N(f"r6{SEP}{b}{SEP}{k_}", f_) for k_, f_ in (("cagr", "pc1"), ("rule_cagr", "pc1"), ("max_dd", "pc1"), ("rule_dd", "pc1"), ("calmar", "n3"), ("share_in", "pc1"), ("weeks_differ", "int"))] for b in BOOKS]
    r7_rows = []
    for b in BOOKS:
        for win in ("full", "live"):
            p = f"r7{SEP}{b}{SEP}{win}{SEP}"
            r7_rows.append([E(b), E(win), N(p + "n", "int"), N(p + "n_ahead", "int"), N(p + "cagr_diff_all", "pp2"), N(p + "cagr_diff_wo", "pp2"), N(p + "largest_no", "int"), N(p + "largest_diff", "pp1"), N(p + "sign_change", "yn")])
    r8_rows = [[E(b), E(str(R["r8"][b]["aa_scid"] or ""))] + [N(f"r8{SEP}{b}{SEP}{k_}", f_) for k_, f_ in (("aa_cagr", "pc1"), ("aa_dd", "pc1"), ("rule", "pc1"), ("switch", "pc1"), ("parent", "pc1"), ("pub_parent", "pc1"))] for b in BOOKS]
    pat_secs = ""
    for b in BOOKS:
        rows_ = [[E(pat), N(f"patterns{SEP}{b}{SEP}patterns{SEP}{pat}{SEP}weeks", "int"), N(f"patterns{SEP}{b}{SEP}patterns{SEP}{pat}{SEP}rule_in", "int"), N(f"patterns{SEP}{b}{SEP}patterns{SEP}{pat}{SEP}switch_in", "int"), N(f"patterns{SEP}{b}{SEP}patterns{SEP}{pat}{SEP}mean_fs", "n3")] for pat in R["patterns"][b]["patterns"]]
        rows_ += [[E(nm), N(f"patterns{SEP}{b}{SEP}fs{SEP}{nm}{SEP}weeks", "int"), N(f"patterns{SEP}{b}{SEP}fs{SEP}{nm}{SEP}rule_in", "int"), N(f"patterns{SEP}{b}{SEP}fs{SEP}{nm}{SEP}switch_in", "int"), ""] for nm in R["patterns"][b]["fs"]]
        x = f"weeks{SEP}{b}{SEP}full{SEP}"
        pat_secs += (f"<p class='mini'>{E(b)}, {E(start[b])} to {E(end)}: stocks held min {N(x + 'nheld_min', 'int')}, median {N(x + 'nheld_median', 'n2')}, max {N(x + 'nheld_max', 'int')}; weeks with 0 &lt; FS &lt; 1: {N(x + 'partial_fs', 'int')}; exact ties FS = 0.60: {N(x + 'ties', 'int')} "
                     f"(float formula differs in {N(x + 'float_differs', 'int')}); decision flips rule / switch: {N(x + 'flips_rule', 'int')} / {N(x + 'flips_switch', 'int')}; rule flips with no signal flip (a tag change): {N(x + 'flips_rule_no_signal', 'int')}.</p>"
                     + fmt_table(rows_, ["pattern (Nifty 100, Midcap 100, Smallcap 100) or FS band", "weeks", "rule IN", "switch IN", "mean FS"]))
    robust_sec = f"""<h2>6 · Robustness and the descriptive checks (R1 to R8)</h2>
<p class="nonull">Reported; they decide a finding's status note, not the verdicts. {NOCHANCE.capitalize()}.</p>
{crit_block('full|lbes|0', 'R1a · before cost (0 bps)')}{crit_block('full|lbes|50', 'R1b · 50 bps')}
<h3>R1c · trades and cost paid, full window {E(start[b0])} to {E(end)}</h3>{fmt_table(tc_rows, ["book", "series", "trades @0", "trades @20.8", "trades @50", "cost paid @0", "cost paid @20.8", "cost paid @50"])}
{crit_block('live|lbes|20.8', 'R2 · the live window alone')}{crit_block('full|liq|20.8', 'R3 · the cash half replaced by LIQUIDCASE')}
<h3>R4 · tag error (a sensitivity of the data, not a null of the claim; no pass mark)</h3>
<p>{N('meta' + SEP + 'n_r4' + SEP + b0, 'int')} draws per book. At every weekly tag read each stock whose tag comes from the rank rule has its band replaced, with probability 7.93% (one minus the 92.07% agreement of REVIEW.md check 6), by one of the other two bands with equal probability; membership tags are not perturbed.
Full window {E(start[b0])} to {E(end)}, {PRIMARY:g} bps. Rule CAGR minus switch CAGR across the draws (percentage points), the share of draws above zero, and the share of weekly decisions whose IN or OUT state changes.</p>
{fmt_table(r4_rows, ["book", "draws", "unperturbed", "mean", "5th pct", "median", "95th pct", "min", "max", "draws > 0", "share > 0", "weeks changed (mean)", "weeks changed (max)"])}
<div class="two">{hist_html}</div>
<h3>R5 · threshold curve (descriptive; five settings shown, none selected; no claim comes from it)</h3><p class="mini">Full window {E(start[b0])} to {E(end)}, {PRIMARY:g} bps. 0.60 is production's value and the only reference setting.</p>{r5_secs}
<h3>R6 · FS weighted by listed weights (descriptive)</h3><p class="mini">Full window, {PRIMARY:g} bps; IN iff the listed weight of the stocks on is at least 0.60.</p>
{fmt_table(r6_rows, ["book", "weight-FS CAGR", "count-FS CAGR", "weight-FS max DD", "count-FS max DD", "weight-FS Calmar", "share IN", "weeks the decision differs"])}
<h3>R7 · does one stretch carry the difference?</h3><p class="mini">CAGR difference rule − switch (percentage points) over the whole path and with the stretch of largest |difference| removed from both series; 'sign changes' says whether removing it flips the sign. Stretch charts above; every stretch is in the log.</p>
{fmt_table(r7_rows, ["book", "window", "stretches", "rule ahead in", "CAGR diff, all", "CAGR diff, without the largest", "largest stretch no.", "its diff (pp of log return)", "sign changes"])}
<h3>R8 · context only: the published AA books on the live window</h3><p class="mini">Live window {E(live_first[b0])} to {E(end)}. The AA books run other rules, so this is context, not a test.</p>
{fmt_table(r8_rows, ["book", "AA book", "AA CAGR", "AA max DD", "rule CAGR", "switch CAGR", "parent CAGR (rebuilt)", "published parent CAGR"])}
<h3>Weeks by signal pattern and by FS</h3>{pat_secs}"""

    # gates
    v3 = R["v3"]
    gate_rows = [["V1 independent check", E("PASS" if R["gates"]["V1"] else "FAIL"), E("verify_t10.py re-derives decisions, tags, FS, events, NAVs, stretches, bootstrap and R4 draws from the raw files; deliberate corruptions must be detected")],
                 ["V2 point in time", E("PASS" if R["gates"]["V2"] else "FAIL"), f"violations {N('v2' + SEP + 'own_violations', 'int')} of {N('v2' + SEP + 'own_checked', 'int')} checks (re-derived); the engine's own: {N('v2' + SEP + 'engine_violations', 'int')} of {N('v2' + SEP + 'engine_checked', 'int')}"],
                 ["V3 regression to T06", E("PASS" if R["gates"]["V3"] else "FAIL"), f"{N('v3' + SEP + 'rows', 'int')} NAV rows against T06, worst relative difference {N('v3' + SEP + 'max_rel', 'sci')}; {N('v3' + SEP + 'dec_shared', 'int')} shared decision dates, {N('v3' + SEP + 'dec_mismatch', 'int')} mismatches; always-in against the published NAV within the G0 tolerance"],
                 ["V4 the exact facts", E("PASS" if R["gates"]["V4"] else "FAIL"), "the rule is never OUT while the switch is IN; FS = k ÷ n; the state is IN iff 5k ≥ 3n; the float formula's disagreements listed (none expected)"],
                 ["V5 tags read every week", E("PASS" if R["gates"]["V5"] else "FAIL"), "the number of weekly tag reads equals the sum of the stocks held over the decisions; the verifier's 500-pair sample per book equals the D23 panels"]]
    g0_rows = [[E(g["book"]), E(g["first"] + " to " + g["last"]), N(f"g0{SEP}{i}{SEP}gap", "n3"), E(str(g["worst_year"])), N(f"g0{SEP}{i}{SEP}worst_gap", "n3")] for i, g in enumerate(R["g0"])]
    gates_sec = f"""<h2>7 · Validity gates</h2><p>If any gate fails nothing on this page may be read. All gates passed for this page to be built.</p>{fmt_table(gate_rows, ["gate", "result", "what it checks"])}
<p class="mini">Always-in (every stock held, 0 cost) against the published NAV: gap in percentage points a year over the window, and the worst calendar year's gap (tolerance 0.25 and 0.5).</p>{fmt_table(g0_rows, ["book", "window", "CAGR gap (pp/yr)", "worst year", "its gap (pp)"])}"""

    defs = f"""<h2>8 · Definitions</h2>
<div class="formula">Weekly decision: T0, then the last session of each ISO week; trade on the next session at OHLC4; the last decision (2026-10-30) is made but not traded.
Band of a stock: Large / Mid / Small and below, from the shared tag rule as of the decision date. A band is on if its index (Nifty 100 / Midcap 100 / Smallcap 100) has SIGN = BUY.
FS = k ÷ n, k = stocks whose band is on, n = stocks held (listed weight above zero). Rule: IN iff 5k ≥ 3n; IN holds the whole basket at listed weights (renormalised), OUT holds 50% GOLDBEES + 50% cash.
Three-index switch: IN iff all three SIGNs are BUY. Extra week: rule IN and switch OUT. Stretch: a maximal run of extra weeks.
Cost: cost_bps ÷ 2 ÷ 10,000 per side on Σ |target − current| over every stock, GOLDBEES and cash; the first position at T0 is free; there is no sale at the end.
NAV_t = Σ stock units × close + GOLDBEES units × close + cash units × level, 1.000 at the close of T0.
CAGR = end NAV ^ (252 ÷ (sessions − 1)) − 1.   Max drawdown = min over t of NAV_t ÷ max(NAV_s, s ≤ t) − 1.   Calmar = CAGR ÷ |max drawdown|.   Volatility = SD of daily log returns × √252.
Ulcer = √(mean over sessions of (100 × drawdown)²).   Days ≥ 10% below = sessions with NAV at least 10% under its running peak.   Longest underwater = longest run of sessions below the previous peak.
Constant mix: the rule's average share of NAV in the parent's stocks, f, held all the time (f in the parent at listed weights, half of 1 − f in GOLDBEES, half in cash), rebalanced at each of the rule's event sessions at OHLC4 with the same cost.
C1: rule CAGR &gt; parent CAGR.  C2: rule max drawdown shallower than the parent's.  C3: rule CAGR &gt; switch CAGR.  C4: rule Calmar ≥ switch Calmar.  Each: at least 3 of 4 books. C3 and C4 only where the rule has at least 5 separate stretches of extra weeks.
Bootstrap: daily log-return difference (rule − comparator) resampled in moving blocks of 20 sessions, 1,000 resamples; interval = 2.5th and 97.5th percentile of the CAGR difference.
R4: each rank-sourced tag replaced with probability 0.0793 by one of the other two bands; the rule re-run on the perturbed tags (no null, no pass mark).</div>
<h3>What this page cannot say</h3><p>With no random benchmark, a better number is a difference on this window, not proof of skill. The negative control and the oracle (which need a null) were not run, so the pipeline's ability to detect an edge is untested. The rule's family and this window have been seen
(Studies 2 and 3, T03 to T08, the AA live record); the threshold 0.60 is production's and was not tuned. FS here reads Nifty 100, Midcap 100 and Smallcap 100, not production's Midcap 150 and Smallcap 250 (no approved signals). About 91% of holding-weeks are tagged by the rank rule, which is untested before 2026-04-09.
The decisions before 2021-11 are a production backfill. The cash file's source before 2026-08-10 is unrecorded and its extension runs about 0.5 pp a year rich. The window ends inside the last approved basket.</p>"""

    page_data = json.dumps(R, separators=(",", ":"), sort_keys=False).replace("</", "<\\/")
    js_data = lambda i, o: f'<script type="application/json" id="{i}">' + json.dumps(o, separators=(",", ":")).replace("</", "<\\/") + "</script>"
    body = f"""<main>
<p class="eyebrow">AA · test T10 · results page generated by tests/T10/report.py from evidence/{E(M['run'])}/</p>
<h1>Does holding the whole parent while FS ≥ 0.60 beat holding the parent, or the three-index switch?</h1>
{answer}
<h2>1 · How to read this page</h2><p>Every number in a table or caption is generated from the run's evidence; every chart is hoverable (the crosshair shows the date and level, the tooltip lists everything drawn at that point). Every statistic's formula is in section 8 and every table and curve states its start and end dates.
The page is checked by <code>check_page.py</code> (every number recomputed from the evidence by code that shares nothing with this page's code).</p>
{data_sec}{example_sec}{head_sec}{detail_sec}{robust_sec}{gates_sec}{defs}
</main>
{js_data('lines-data', lines_data)}{js_data('fs-data', fs_data)}{js_data('st-data', st_data)}{js_data('bars-data', bars_data)}
<script type="application/json" id="page-data">{page_data}</script>
<script>{LINES_JS}</script><script>{FS_JS}</script><script>{ST_JS}</script><script>{BARS_JS}</script>"""
    page = (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>T10 results: FS rule</title><style>{CSS}</style></head><body>{body}</body></html>')
    out = ev_dir / "report.html"
    out.write_text(page, encoding="utf-8")
    print(f"wrote {out} ({len(page) / 1e6:.2f} MB)")


if __name__ == "__main__":
    main()
