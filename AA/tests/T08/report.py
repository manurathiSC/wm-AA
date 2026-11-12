"""Build report.html for T08 from shipped evidence only (AGENT.md R10). Forked from T06's page; additions only where the MAUc1-timed sleeve and the gold nulls need them.

    python tests/T08/report.py [--run headline]              writes tests/T08/evidence/report.html
    python tests/T08/report.py --evidence DIR [--out DIR]    another evidence directory (e.g. a synthetic one); the page and
                                                             analysis.log are then looked up and written in --out (default DIR)

Every number on the page is computed here from evidence/<run>/ (decisions.csv, gold_signal.csv, stats.csv, draws.csv, daily_nav.csv, trades.csv, sleeve_trades.csv,
positions.csv, draw_states.npz, real_states.npz, draw_curves_20.8.npz, count_table.json, inputs.csv, audit.json, verify_t08.json) and, for the gate verdicts, the 'Gates:' line
of analysis.log. The same numbers are written into the page's embedded JSON blocks (page-data, regime-data, lines-data, bars-data) so check_page.py can recompute them
independently. Imports nothing from the engine. Every chart is hoverable (AGENT.md R10): the hover reads the same arrays that draw the chart.
The two held/randomised tables are copied from T08.md section 2 (nothing typed here).
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
C10, C9 = "#2a6fdb", "#c9811a"   # deciding null (blue), null beside it (orange)
KINDS = ["strategy", "strategy_fixed50", "hold_parent", "constant_mix", "constant_mix_timed", "sleeve_only", "sleeve_only_timed"]
COL = {"strategy": "#2a6fdb", "strategy_fixed50": "#79a8f0", "hold_parent": "#8a8f98", "constant_mix": "#c9811a", "constant_mix_timed": "#e8b45c", "sleeve_only": "#2f9e6e",
       "sleeve_only_timed": "#75cfa6", "published_D17": "#b04a9b"}
LAB = {"strategy": "Rule, MAUc1-timed sleeve", "strategy_fixed50": "Rule, 50/50 sleeve (T06's rule)", "hold_parent": "Hold the parent", "constant_mix": "Constant mix, 50/50 non-stock share",
       "constant_mix_timed": "Constant mix, MAUc1-timed non-stock share", "sleeve_only": "50/50 GOLDBEES + cash", "sleeve_only_timed": "MAUc1-timed GOLDBEES + cash", "published_D17": "Published NAV (D17)"}
CRIT = [("C1", "cagr", "F1", "F2"), ("C2", "max_dd", "F1", "F2"), ("C3", "cagr", "F3", "F4"), ("C4", "max_dd", "F3", "F4")]
FAMS = ("F1", "F2", "F3", "F4")


# ── small helpers ─────────────────────────────────────────────────────────────
def rank(x, draws, hb=True):
    tie = np.isclose(draws, x, rtol=1e-12, atol=0)
    worse = ((draws < x) if hb else (draws > x)) & ~tie
    better = ((draws > x) if hb else (draws < x)) & ~tie
    n = len(draws)
    return {"percentile": float((worse.sum() + 0.5 * tie.sum()) / n * 100), "p": float((1 + better.sum() + tie.sum()) / (n + 1)),
            "worse": int(worse.sum()), "tied": int(tie.sum()), "better": int(better.sum()), "draws": int(n)}


def holm(ps):
    ps = list(map(float, ps))
    m = len(ps)
    order = sorted(range(m), key=lambda i: ps[i])
    adj, run = [0.0] * m, 0.0
    for r, i in enumerate(order):
        run = max(run, min(1.0, (m - r) * ps[i]))
        adj[i] = run
    return adj


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


def replay(seed, ks, S_, bounds, names):
    """Replay a free-length draw from default_rng(seed): the first spell kind's parts first, then the second's, each by the cumulative-sum search."""
    rg = np.random.default_rng(seed)
    steps, res = [], {}
    for name in names:
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


def md_inline(s):
    s = E(s.strip())
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    return re.sub(r"`(.+?)`", r"<code>\1</code>", s)


def md_tables(doc):
    """The first markdown table after each of the two 'Null table' lines of T08.md section 2: (header, rows) of raw cell strings."""
    out = {}
    for key, marker in (("io", "**Null table, in-or-out nulls"), ("gold", "**Null table, gold nulls")):
        i = doc.index(marker)
        lines = doc[i:].replace("\r\n", "\n").split("\n")[1:]
        rows = []
        started = False
        for l in lines:
            if l.startswith("|"):
                started = True
                cells = [c.strip() for c in l.strip().strip("|").split("|")]
                if all(set(c) <= set("-: ") for c in cells):
                    continue
                rows.append(cells)
            elif started:
                break
        out[key] = (rows[0], rows[1:])
    return out


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
        out.append(f'<polyline points="{pts}" fill="none" stroke="{COL[k]}" stroke-width="{2.4 if k == "strategy" else 1.2}" stroke-linejoin="round"/>')
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
    for k_, s_ in ((1e12, "tn"), (1e9, "bn"), (1e6, "m"), (1e3, "k")):
        if abs(v) >= k_:
            return f"{v / k_:g}{s_}"
    return f"{v:g}"


def svg_bars(did, edges, series, marks=(), xk="pct", yk="int", w=460, h=190, xticks=None, xtick_fmt=None, extra=None, binlab=None, yunit="draws", L=44):
    """Overlaid bars (one series per null). series: [{k,label,col,v:[counts per bin],n:total,op}]; marks: [{label,x,col,txt,dash}]. Returns (svg, data)."""
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


NSTRIP = 6  # rule, draw, they differ, MAUc1, rule's sleeve weight, draw's sleeve weight


def svg_regime(dates, ser, rule_runs, draw_runs, pair_runs, gold_runs, rw_runs, dw_runs, draw_label, w=760):
    """Growth-of-1 lines (log) on top; below, one strip per timing (filled = holds the parent), a strip of where they differ, a MAUc1 strip (filled = BUY)
    and the sleeve's GOLDBEES target weight of the rule and of the draw while OUT (bar height = weight)."""
    N = len(dates)
    L, R, T, ph = 56, 62, 8, 210
    rowh, gap = 12, 5
    top = T + ph + 22
    h = top + NSTRIP * (rowh + gap) + 20
    allv = np.concatenate(list(ser.values()))
    lo, hi = math.log(allv.min() * 0.97), math.log(allv.max() * 1.03)
    x = lambda i: L + (w - L - R) * i / (N - 1)
    y = lambda v: T + ph * (1 - (math.log(v) - lo) / (hi - lo))
    bot = top + NSTRIP * (rowh + gap) - gap
    out = [f'<svg id="regime-svg" viewBox="0 0 {w} {h}" role="img" aria-label="Growth of 1: rule versus {E(draw_label)}, with the weeks each held the parent, the MAUc1 signal and the sleeve weights" class="chart">']
    for v, s, e, tip in pair_runs:
        if v in (1, 2):
            fill = "var(--fg)" if v == 1 else COL["strategy"]
            out.append(f'<rect x="{x(s):.1f}" y="{T}" width="{max(x(e) - x(s), 0.6):.1f}" height="{bot - T}" fill="{fill}" opacity="{0.10 if v == 1 else 0.14}"/>')
    for t in (1, 2, 4, 8, 16):
        if math.exp(lo) <= t <= math.exp(hi):
            out.append(f'<line x1="{L}" x2="{w - R}" y1="{y(t):.1f}" y2="{y(t):.1f}" class="grid"/><text x="{L - 4}" y="{y(t) + 3:.1f}" text-anchor="end" class="ax">{t:g}×</text>')
    idx = np.append(np.arange(0, N, 3), N - 1)
    styles = {"hold_parent": (COL["hold_parent"], 1.2), "draw": ("var(--fg)", 1.7), "strategy": (COL["strategy"], 2.4)}
    for k in ("hold_parent", "draw", "strategy"):
        v = ser[k]
        out.append(f'<polyline points="{" ".join(f"{x(i):.1f},{y(v[i]):.1f}" for i in idx)}" fill="none" stroke="{styles[k][0]}" stroke-width="{styles[k][1]}" stroke-linejoin="round"/>')
        out.append(f'<text x="{x(N - 1) + 5:.1f}" y="{y(v[-1]) + 3:.1f}" class="ax" style="fill:var(--fg)">{v[-1]:.1f}×</text>')

    def strip(r_, lab):
        yy = top + r_ * (rowh + gap)
        out.append(f'<rect x="{L}" y="{yy}" width="{w - L - R}" height="{rowh}" fill="var(--line)" rx="2"/><text x="{L - 6}" y="{yy + rowh - 2}" text-anchor="end" class="ax">{E(lab)}</text>')
        return yy
    for r_, (lab, runs_, fill) in enumerate((("Rule", rule_runs, COL["strategy"]), (draw_label, draw_runs, "var(--fg)"))):
        yy = strip(r_, lab)
        for v, s, e in runs_:
            if v == 1:
                out.append(f'<rect x="{x(s):.1f}" y="{yy}" width="{max(x(e) - x(s), 0.6):.1f}" height="{rowh}" fill="{fill}"/>')
    yy = strip(2, "They differ")
    for v, s, e, tip in pair_runs:
        if v in (1, 2):
            out.append(f'<rect x="{x(s):.1f}" y="{yy}" width="{max(x(e) - x(s), 0.6):.1f}" height="{rowh}" fill="{"var(--fg)" if v == 1 else COL["strategy"]}" opacity="{0.55 if v == 1 else 1}"/>')
    yy = strip(3, "MAUc1 BUY")
    for v, s, e in gold_runs:
        if v == 1:
            out.append(f'<rect x="{x(s):.1f}" y="{yy}" width="{max(x(e) - x(s), 0.6):.1f}" height="{rowh}" fill="#c9a227"/>')
    for r_, (lab, runs_, fill) in enumerate((("Rule gold wt", rw_runs, COL["strategy"]), (draw_label + " wt", dw_runs, "var(--fg)")), start=4):
        yy = strip(r_, lab)
        for v, s, e in runs_:
            if v > 0:
                hh = rowh * v / 10
                out.append(f'<rect x="{x(s):.1f}" y="{yy + rowh - hh:.1f}" width="{max(x(e) - x(s), 0.6):.1f}" height="{hh:.1f}" fill="{fill}" opacity="0.8"/>')
    for yr in sorted({d.year for d in dates}):
        i = int(np.argmax([d.year == yr for d in dates]))
        out.append(f'<text x="{x(i):.1f}" y="{h - 6}" text-anchor="middle" class="ax">{yr}</text>')
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
var cols=['#2a6fdb','var(--fg)','#8a8f98'],key=['rule','draw','parent'],lab=['Rule (MAUc1-timed sleeve)',d.draw_label,'Hold the parent'];
function Y(v){return d.T+d.ph*(1-(Math.log(v)-d.lo)/(d.hi-d.lo))}
function X(i){return d.L+(d.w-d.L-d.R)*i/(d.N-1)}
function fx(v){return v.toFixed(2)+'\\u00d7'}
function sl(i,s){return s?'holds the parent':'sleeve '+Math.round(100*d.gw[i])+'% GOLDBEES / '+Math.round(100*(1-d.gw[i]))+'% cash'}
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
 s+='<br>Rule: '+sl(i,d.rs[i])+'<br>'+d.draw_label+': '+sl(i,d.ds[i])+'<br>MAUc1: '+(d.g[i]?'BUY':'SELL');
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
table.wrap td,table.wrap th{white-space:normal;text-align:left;vertical-align:top;min-width:90px}
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="headline")
    ap.add_argument("--evidence", default=None)
    ap.add_argument("--out", default=None, help="directory of report.html and analysis.log")
    ap.add_argument("--t06", default=str(AA / "tests" / "T06" / "evidence" / "headline"))
    ap.add_argument("--doc", default=str(HERE / "T08.md"))
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
    t06 = Path(a.t06)
    dec = pd.read_csv(ev / "decisions.csv")
    st = pd.read_csv(ev / "stats.csv")
    dr = pd.read_csv(ev / "draws.csv")
    tr = pd.read_csv(ev / "trades.csv")
    sl = pd.read_csv(ev / "sleeve_trades.csv")
    nav = pd.read_csv(ev / "daily_nav.csv", parse_dates=["date"])
    pos = pd.read_csv(ev / "positions.csv")
    g4 = pd.read_csv(ev / "g_engine.csv")
    au = json.loads((ev / "audit.json").read_text(encoding="utf-8"))
    ct = json.loads((ev / "count_table.json").read_text(encoding="utf-8"))
    ver = json.loads((ev / "verify_t08.json").read_text(encoding="utf-8")) if (ev / "verify_t08.json").exists() else None
    _z = np.load(ev / "draw_states.npz")
    states = {k_: _z[k_] for k_ in _z.files}  # decompress once
    _r = np.load(ev / "real_states.npz")
    realz = {k_: _r[k_] for k_ in _r.files}
    curves = np.load(ev / "draw_curves_20.8.npz")
    inp, asof_inputs = read_inputs(ev / "inputs.csv")
    if asof_inputs is None:
        asof_inputs = (au.get("data") or {}).get("approved_data_as_of")
    am = re.search(r"\*\*As of: (\d{4}-\d{2}-\d{2})", (AA / "data" / "APPROVED_DATA.md").read_text(encoding="utf-8"))
    asof_file = am.group(1) if am else None
    logp = logdir / "analysis.log"
    gate_line = None
    if logp.exists():
        mg = re.search(r"^Gates: (\{.*\}) ->", logp.read_text(encoding="utf-8"), re.M)
        gate_line = ast.literal_eval(mg.group(1)) if mg else None  # a dict literal of strings written by analyse.py
    doc = Path(a.doc).read_text(encoding="utf-8")
    sha = doc.split("§1–§3 sha256:** `")[1].split("`")[0]
    mdt = md_tables(doc)
    LIQ = "liq" if "liq" in set(st.cash) else "liquidcase"

    S = lambda b, kind="strategy", cost=PRIMARY, win="full", cash="lbes": st[(st.book == b) & (st.window == win) & (st.cash == cash) & (st.cost_bps == cost) & (st.kind == kind)].iloc[0]
    D = lambda b, fam, cost=PRIMARY, win="full", cash="lbes", mode="timed": dr[(dr.book == b) & (dr.window == win) & (dr.cash == cash) & (dr.cost_bps == cost) & (dr.family == fam) & (dr.sleeve_mode == mode)].sort_values("draw_id")
    ND = int(len(D("SCMO_0003", "F1")))
    rule = {b: dec[dec.book == b].sort_values("j").state.values.astype(int) for b in BOOKS}
    gold = {b: dec[dec.book == b].sort_values("j").g.values.astype(int) for b in BOOKS}
    gwk = {b: dec[dec.book == b].sort_values("j").gw.values.astype(float) for b in BOOKS}
    weeks = {b: len(rule[b]) for b in BOOKS}
    rin = {b: lens(rule[b], 1) for b in BOOKS}
    rout = {b: lens(rule[b], 0) for b in BOOKS}
    gbuy = {b: lens(gold[b], 1) for b in BOOKS}
    gsell = {b: lens(gold[b], 0) for b in BOOKS}
    HI = {"in": max(max(rin[b]) for b in BOOKS), "out": max(max(rout[b]) for b in BOOKS), "buy": max(max(gbuy[b]) for b in BOOKS), "sell": max(max(gsell[b]) for b in BOOKS)}
    first_dec = {b: dec[dec.book == b].sort_values("j").decision_date.iloc[0] for b in BOOKS}
    ctab = {}
    for key, ent in (ct.get("tables") or {}).items():
        p_ = key.split("|")
        if len(p_) == 4:
            ctab[tuple(p_)] = {"k": int(ent.get("spells_k", ent.get("k"))), "S": int(ent.get("weeks_S", ent.get("S"))), "lo": int(ent["lo"]), "hi": int(ent["hi"]), "n_ways": int(ent["n_ways"])}
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
    ent = lambda a_: int(((a_[1:] == 1) & (a_[:-1] == 0)).sum()) + int(a_[0] == 1)
    ext = lambda a_: int(((a_[1:] == 0) & (a_[:-1] == 1)).sum())
    rt_of = lambda a_: min(ent(a_), ext(a_))

    def gold_with_out(g, s):
        n_, i = 0, 0
        for v_, ln in runs(g):
            if (s[i:i + ln] == 0).any():
                n_ += 1
            i += ln
        return n_
    live_io = {b: realz[f"{b}|live|io"].astype(int) for b in BOOKS}
    live_g = {b: realz[f"{b}|live|gold"].astype(int) for b in BOOKS}
    notrep_live = [b for b in BOOKS if rt_of(live_io[b]) < 4 or gold_with_out(live_g[b], live_io[b]) < 4]
    notrep = [b for b in BOOKS if rt_of(rule[b]) < 4 or gold_with_out(gold[b], rule[b]) < 4]

    # ── page data ─────────────────────────────────────────────────────────────
    data = {"run": ev.name, "prereg_sha256": sha, "draws": ND, "as_of_file": asof_file, "as_of_inputs": asof_inputs, "end": end_date, "start": start3, "start_0007": start7,
            "weeks": {b: weeks[b] for b in BOOKS}, "bounds": {"lo": LO, "hi_in": HI["in"], "hi_out": HI["out"], "hi_buy": HI["buy"], "hi_sell": HI["sell"]}, "books": {}, "gates": gate_line,
            "not_reportable": notrep, "not_reportable_live": notrep_live}
    for b in BOOKS:
        s = S(b)
        bb = {"cagr": float(s.cagr), "max_dd": float(s.max_dd), "end_nav": float(s.end_nav), "trades": int(s.trades), "cost_paid": float(s.cost_paid), "sleeve_trades": int(s.sleeve_trades), "rule_sessions": rule_sess[b],
              "sessions_total": len(cal[b]) - 1, "rule_in": rin[b], "rule_out": rout[b], "rule_buy": gbuy[b], "rule_sell": gsell[b], "round_trips": rt_of(rule[b]), "gold_spells_with_out": gold_with_out(gold[b], rule[b])}
        for fam in FAMS:
            n = D(b, fam)
            rc, rd = rank(s.cagr, n.cagr.values), rank(s.max_dd, n.max_dd.values)
            q = np.percentile(n.cagr.values, [5, 95])
            bb.update({f"{fam}_median_cagr": float(n.cagr.median()), f"{fam}_median_dd": float(n.max_dd.median()), f"{fam}_pct_cagr": rc["percentile"], f"{fam}_p_cagr": rc["p"],
                       f"{fam}_pct_dd": rd["percentile"], f"{fam}_p_dd": rd["p"], f"{fam}_worse": rc["worse"], f"{fam}_tied": rc["tied"], f"{fam}_better": rc["better"],
                       f"{fam}_sd_cagr": float(n.cagr.std()), f"{fam}_sd_dd": float(n.max_dd.std()), f"{fam}_mde_cagr_pp": float(280 * n.cagr.std()), f"{fam}_mde_dd_pp": float(280 * n.max_dd.std()),
                       f"{fam}_p5_cagr": float(q[0]), f"{fam}_p95_cagr": float(q[1]), f"{fam}_sess_min": int(n.sessions_invested.min()), f"{fam}_sess_median": float(n.sessions_invested.median()),
                       f"{fam}_sess_max": int(n.sessions_invested.max()), f"{fam}_strades_min": int(n.sleeve_trades.min()), f"{fam}_strades_median": float(n.sleeve_trades.median()), f"{fam}_strades_max": int(n.sleeve_trades.max())})
            for c in (0.0, 50.0):
                sc_, nc_ = S(b, cost=c), D(b, fam, cost=c)
                bb[f"{fam}_pct_cagr_{c:g}"] = rank(sc_.cagr, nc_.cagr.values)["percentile"]
                bb[f"{fam}_pct_dd_{c:g}"] = rank(sc_.max_dd, nc_.max_dd.values)["percentile"]
        for fam in ("F1", "F3"):
            bb[f"{fam}_live_pct"] = rank(S(b, win="live").cagr, D(b, fam, win="live").cagr.values)["percentile"]
            bb[f"{fam}_liq_pct"] = rank(S(b, cash=LIQ).cagr, D(b, fam, cash=LIQ).cagr.values)["percentile"]
        n5 = D(b, "F5")
        bb.update({"F5_median_cagr": float(n5.cagr.median()), "F5_sd_cagr": float(n5.cagr.std()), "F5_pct_cagr": rank(s.cagr, n5.cagr.values)["percentile"], "F5_p_cagr": rank(s.cagr, n5.cagr.values)["p"],
                   "F5_pct_dd": rank(s.max_dd, n5.max_dd.values)["percentile"], "F5_p_dd": rank(s.max_dd, n5.max_dd.values)["p"]})
        sf = S(b, "strategy_fixed50")
        bb.update({"r6_rule_dcagr": float(s.cagr - sf.cagr), "r6_rule_ddd": float(s.max_dd - sf.max_dd)})
        for fam in ("F1", "F2"):
            m = D(b, fam, mode="timed").merge(D(b, fam, mode="fixed50"), on="draw_id", suffixes=("_t", "_f"))
            dc, ddn = (m.cagr_t - m.cagr_f).values, (m.max_dd_t - m.max_dd_f).values
            bb.update({f"r6_{fam}_median_dcagr": float(np.median(dc)), f"r6_{fam}_pct_dcagr": rank(s.cagr - sf.cagr, dc)["percentile"], f"r6_{fam}_share_dcagr": float((dc > 0).mean()),
                       f"r6_{fam}_median_ddd": float(np.median(ddn)), f"r6_{fam}_pct_ddd": rank(s.max_dd - sf.max_dd, ddn)["percentile"], f"r6_{fam}_share_ddd": float((ddn > 0).mean())})
        for kind in KINDS:
            bb[f"{kind}_cagr"], bb[f"{kind}_dd"] = float(S(b, kind).cagr), float(S(b, kind).max_dd)
            for c in COSTS:
                bb[f"{kind}_cagr_{c:g}"], bb[f"{kind}_dd_{c:g}"] = float(S(b, kind, c).cagr), float(S(b, kind, c).max_dd)
        pn = nav[(nav.book == b) & (nav.run == "published_D17")].sort_values("date").nav.values
        bb.update({"pub_cagr": nav_stats(pn)["cagr"], "pub_dd": nav_stats(pn)["max_dd"], "live_cagr": float(S(b, win="live").cagr), "liq_cagr": float(S(b, cash=LIQ).cagr)})
        hp_ = holm([bb[f"{f}_p_{k_}"] for f, k_ in (("F1", "cagr"), ("F1", "dd"), ("F3", "cagr"), ("F3", "dd"))])
        bb.update({"holm_C1": hp_[0], "holm_C2": hp_[1], "holm_C3": hp_[2], "holm_C4": hp_[3]})
        data["books"][b] = bb

    def cnt(key, th=90):
        return int(sum(bool(data["books"][b][key] >= th) and b not in notrep for b in BOOKS))
    data["verdict"] = {"C1": cnt("F1_pct_cagr"), "C2": cnt("F1_pct_dd"), "C3": cnt("F3_pct_cagr"), "C4": cnt("F3_pct_dd"), "C1_F2": cnt("F2_pct_cagr"), "C2_F2": cnt("F2_pct_dd"), "C3_F4": cnt("F4_pct_cagr"), "C4_F4": cnt("F4_pct_dd"),
                       "R3_live_C1": cnt("F1_live_pct"), "R3_live_C3": cnt("F3_live_pct"), "R2_liq_C1": cnt("F1_liq_pct"), "R2_liq_C3": cnt("F3_liq_pct")}
    V = data["verdict"]
    A_ok, B_ok = V["C1"] >= 3 and V["C2"] >= 3, V["C3"] >= 3 and V["C4"] >= 3
    gates_ok = bool(gate_line) and all(v == "PASS" for v in gate_line.values()) and len(gate_line) == 6

    # historical reference: T06's stored N4.10 and N4.9 draws (a different window and a fixed sleeve)
    t06ref = {}
    if (t06 / "draws.csv").exists() and (t06 / "stats.csv").exists():
        s6, d6 = pd.read_csv(t06 / "stats.csv"), pd.read_csv(t06 / "draws.csv")
        for b in BOOKS:
            sr = s6[(s6.book == b) & (s6.window == "full") & (s6.cash == "lbes") & (s6.cost_bps == PRIMARY) & (s6.kind == "strategy")].iloc[0]
            ent_ = {"cagr": float(sr.cagr)}
            for typ, nm in (("N4.10", "n10"), ("N4.9", "n9")):
                nd_ = d6[(d6.book == b) & (d6.window == "full") & (d6.cash == "lbes") & (d6.cost_bps == PRIMARY) & (d6.draw_type == typ)]
                ent_.update({f"{nm}_pct_cagr": rank(sr.cagr, nd_.cagr.values)["percentile"], f"{nm}_pct_dd": rank(sr.max_dd, nd_.max_dd.values)["percentile"]})
            t06ref[b] = ent_
    data["t06_reference"] = t06ref
    r7_file = next((p for p in (ev / "r7_raw_fill.csv", ev / "raw_fill_sensitivity.csv", ev / "r7.csv") if p.exists()), None)
    data["r7"] = None if r7_file is None else {"file": r7_file.name, "columns": list(pd.read_csv(r7_file).columns), "rows": pd.read_csv(r7_file).astype(str).values.tolist()}

    # ── worked example: SCMO_0003 ─────────────────────────────────────────────
    b = "SCMO_0003"
    d = dec[dec.book == b].sort_values("j").reset_index(drop=True)
    slq = sl[(sl.book == b) & (sl.cost_bps == PRIMARY)].reset_index(drop=True)
    trq = tr[(tr.book == b) & (tr.run == "strategy") & (tr.cost_bps == PRIMARY)].reset_index(drop=True)
    pq = pos[(pos.book == b) & (pos.cost_bps == PRIMARY) & (pos.run == "strategy")]
    units = lambda date: {r_.instrument: float(r_.units) for r_ in pq[pq.date == date].itertuples() if not str(r_.instrument).endswith(".NS")}
    pdates = sorted(set(pq.date))
    prev_date = lambda date: (pdates[pdates.index(date) - 1] if pdates.index(date) > 0 else None)
    exit_row = slq[slq.kind == "switch_out"].iloc[0]
    flip_row = next(r_ for r_ in slq[slq.kind == "sleeve_rebalance"].itertuples() if prev_date(r_.date) is not None)
    flip_row = slq[(slq.kind == "sleeve_rebalance") & (slq.date == flip_row.date)].iloc[0]
    jx, jf = int(d.index[d.trade_date == exit_row.date][0]), int(d.index[d.trade_date == flip_row.date][0])
    rx, rf = d.loc[jx], d.loc[jf]
    ttx, ttf = trq[trq.date == exit_row.date].iloc[0], trq[trq.date == flip_row.date].iloc[0]
    nv = nav[(nav.book == b) & (nav.cost_bps == PRIMARY) & (nav.run == "strategy")].sort_values("date").reset_index(drop=True)
    k = int(nv.index[nv.date == pd.Timestamp(exit_row.date)][0])
    s0 = S(b)
    Z = {k_: states[f"{b}|full|{k_}"] for k_ in ("io|N4.9", "io|N4.10", "gold|N4.9-g", "gold|N4.10-g")}
    ks = {"in": ctab[(b, "full", "io", "in")]["k"], "out": ctab[(b, "full", "io", "out")]["k"]}
    SS = {"in": ctab[(b, "full", "io", "in")]["S"], "out": ctab[(b, "full", "io", "out")]["S"]}
    bnd = {"in": (LO, ctab[(b, "full", "io", "in")]["hi"]), "out": (LO, ctab[(b, "full", "io", "out")]["hi"])}
    steps, rp = replay([6, 0], ks, SS, bnd, ("in", "out"))
    replay_ok = rp["in"] == lens(Z["io|N4.10"][0], 1) and rp["out"] == lens(Z["io|N4.10"][0], 0)
    ksg = {"buy": ctab[(b, "full", "gold", "buy")]["k"], "sell": ctab[(b, "full", "gold", "sell")]["k"]}
    SSg = {"buy": ctab[(b, "full", "gold", "buy")]["S"], "sell": ctab[(b, "full", "gold", "sell")]["S"]}
    bndg = {"buy": (LO, ctab[(b, "full", "gold", "buy")]["hi"]), "sell": (LO, ctab[(b, "full", "gold", "sell")]["hi"])}
    stepsg, rpg = replay([11, 6, 0], ksg, SSg, bndg, ("buy", "sell"))
    replay_ok_g = rpg["buy"] == lens(Z["gold|N4.10-g"][0], 1) and rpg["sell"] == lens(Z["gold|N4.10-g"][0], 0)
    own_count = {nm: int(dp_table(ks[nm], SS[nm], *bnd[nm])[ks[nm]][SS[nm]]) for nm in ("in", "out")}
    own_count_g = {nm: int(dp_table(ksg[nm], SSg[nm], *bndg[nm])[ksg[nm]][SSg[nm]]) for nm in ("buy", "sell")}
    x0 = {}
    for fam in FAMS:
        r_ = D(b, fam)
        x0[fam] = r_[r_.draw_id == 0].iloc[0]
    rks = {fam: rank(s0.cagr, D(b, fam).cagr.values) for fam in FAMS}
    uxa, ufb, ufa = units(exit_row.date), units(prev_date(flip_row.date)), units(flip_row.date)
    data["example"] = {
        "exit": {"decision_week": jx, "decision_date": str(rx.decision_date), "trade_date": str(rx.trade_date), "g": int(rx.g), "gw": float(rx.gw), "sign_MAUc1": str(rx.sign_MAUc1), "V": float(ttx.V), "traded": float(exit_row.traded),
                 "cost": float(exit_row.cost), "gold_after": float(exit_row.gold_value_after), "cash_after": float(exit_row.cash_value_after), "nav_after": float(ttx.nav_close_after), "units_after": uxa},
        "flip": {"decision_week": jf, "decision_date": str(rf.decision_date), "trade_date": str(rf.trade_date), "g_before": int(d.loc[jf - 1, "g"]), "g_after": int(rf.g), "gw_after": float(rf.gw), "V": float(ttf.V), "traded": float(flip_row.traded),
                 "cost": float(flip_row.cost), "gold_before": float(flip_row.gold_value_before), "cash_before": float(flip_row.cash_value_before), "gold_after": float(flip_row.gold_value_after), "cash_after": float(flip_row.cash_value_after),
                 "nav_after": float(ttf.nav_close_after), "prev_pos_date": prev_date(flip_row.date), "units_before": ufb, "units_after": ufa},
        "sessions": int(s0.sessions), "end_nav": float(s0.end_nav), "cagr": float(s0.cagr), "max_dd": float(s0.max_dd),
        "k_in": ks["in"], "S_in": SS["in"], "hi_in": bnd["in"][1], "k_out": ks["out"], "S_out": SS["out"], "hi_out": bnd["out"][1], "ways_in": str(own_count["in"]), "ways_out": str(own_count["out"]),
        "ways_in_table": str(ctab[(b, "full", "io", "in")]["n_ways"]), "ways_out_table": str(ctab[(b, "full", "io", "out")]["n_ways"]), "replay_in": rp["in"], "replay_out": rp["out"], "replay_ok": bool(replay_ok), "steps": steps,
        "k_buy": ksg["buy"], "S_buy": SSg["buy"], "hi_buy": bndg["buy"][1], "k_sell": ksg["sell"], "S_sell": SSg["sell"], "hi_sell": bndg["sell"][1], "ways_buy": str(own_count_g["buy"]), "ways_sell": str(own_count_g["sell"]),
        "ways_buy_table": str(ctab[(b, "full", "gold", "buy")]["n_ways"]), "ways_sell_table": str(ctab[(b, "full", "gold", "sell")]["n_ways"]), "replay_buy": rpg["buy"], "replay_sell": rpg["sell"], "replay_ok_g": bool(replay_ok_g), "steps_g": stepsg,
        "d0": {fam: {"cagr": float(x0[fam].cagr), "max_dd": float(x0[fam].max_dd), "sessions": int(x0[fam].sessions_invested), "sleeve_trades": int(x0[fam].sleeve_trades)} for fam in FAMS},
        "rank": {fam: rks[fam] for fam in FAMS}}

    # ── tables ────────────────────────────────────────────────────────────────
    chip = lambda ok: ('<span class="chip ok">PASS</span>' if ok else '<span class="chip bad">FAIL</span>')
    bk_ = lambda b: data["books"][b]
    answer_rows = [[E(b), pc(bk_(b)["cagr"]), f"{bk_(b)['F1_pct_cagr']:.1f}", f"{bk_(b)['holm_C1']:.3f}", pc(bk_(b)["max_dd"]), f"{bk_(b)['F1_pct_dd']:.1f}", f"{bk_(b)['holm_C2']:.3f}",
                    f"{bk_(b)['F3_pct_cagr']:.1f}", f"{bk_(b)['holm_C3']:.3f}", f"{bk_(b)['F3_pct_dd']:.1f}", f"{bk_(b)['holm_C4']:.3f}", pc(bk_(b)["live_cagr"]), f"{bk_(b)['F1_live_pct']:.1f}", f"{bk_(b)['F3_live_pct']:.1f}"] for b in BOOKS]
    head_rows_io, head_rows_g = [], []
    for b in BOOKS:
        x = bk_(b)
        head_rows_io.append([E(b), pc(x["hold_parent_cagr"]), pc(x["strategy_fixed50_cagr"]), pc(x["cagr"]), pc(x["F1_median_cagr"]), f"{100 * (x['cagr'] - x['F1_median_cagr']):+.1f} pp", f"<b>{x['F1_pct_cagr']:.1f}</b>", f"{x['F1_p_cagr']:.3f}", f"{x['holm_C1']:.3f}",
                             pc(x["F2_median_cagr"]), f"<b>{x['F2_pct_cagr']:.1f}</b>", f"{x['F2_p_cagr']:.3f}",
                             pc(x["hold_parent_dd"]), pc(x["max_dd"]), pc(x["F1_median_dd"]), f"<b>{x['F1_pct_dd']:.1f}</b>", f"{x['F1_p_dd']:.3f}", f"{x['holm_C2']:.3f}", pc(x["F2_median_dd"]), f"<b>{x['F2_pct_dd']:.1f}</b>", f"{x['F2_p_dd']:.3f}"])
        head_rows_g.append([E(b), pc(x["cagr"]), pc(x["F3_median_cagr"]), f"{100 * (x['cagr'] - x['F3_median_cagr']):+.1f} pp", f"<b>{x['F3_pct_cagr']:.1f}</b>", f"{x['F3_p_cagr']:.3f}", f"{x['holm_C3']:.3f}",
                            pc(x["F4_median_cagr"]), f"<b>{x['F4_pct_cagr']:.1f}</b>", f"{x['F4_p_cagr']:.3f}",
                            pc(x["max_dd"]), pc(x["F3_median_dd"]), f"<b>{x['F3_pct_dd']:.1f}</b>", f"{x['F3_p_dd']:.3f}", f"{x['holm_C4']:.3f}", pc(x["F4_median_dd"]), f"<b>{x['F4_pct_dd']:.1f}</b>", f"{x['F4_p_dd']:.3f}"])
    cost_rows = []
    for b in BOOKS:
        for kind in KINDS:
            row = [E(b) if kind == "strategy" else "", LAB[kind]]
            for cst in COSTS:
                row += [pc(bk_(b)[f"{kind}_cagr_{cst:g}"]), pc(bk_(b)[f"{kind}_dd_{cst:g}"])]
            cost_rows.append(row)
    mde_io = [[E(b), str(bk_(b)["round_trips"])] + [x_ for f in ("F1", "F2") for x_ in (f"{100 * bk_(b)[f'{f}_sd_cagr']:.2f}", f"{bk_(b)[f'{f}_mde_cagr_pp']:.1f}", f"{100 * bk_(b)[f'{f}_sd_dd']:.2f}", f"{bk_(b)[f'{f}_mde_dd_pp']:.1f}")] for b in BOOKS]
    mde_g = [[E(b), str(bk_(b)["gold_spells_with_out"])] + [x_ for f in ("F3", "F4") for x_ in (f"{100 * bk_(b)[f'{f}_sd_cagr']:.2f}", f"{bk_(b)[f'{f}_mde_cagr_pp']:.1f}", f"{100 * bk_(b)[f'{f}_sd_dd']:.2f}", f"{bk_(b)[f'{f}_mde_dd_pp']:.1f}")] for b in BOOKS]
    kk_ = {"cagr": "cagr", "max_dd": "dd"}
    rob1_dec = [[E(b)] + [f"{bk_(b)[f'{f}_pct_{kk_[k_]}_{c}']:.1f}" if c != "20.8" else f"{bk_(b)[f'{f}_pct_{kk_[k_]}']:.1f}" for cr, k_, f, _ in CRIT for c in ("0", "20.8", "50")] for b in BOOKS]
    rob1_bes = [[E(b)] + [f"{bk_(b)[f'{f}_pct_{kk_[k_]}_{c}']:.1f}" if c != "20.8" else f"{bk_(b)[f'{f}_pct_{kk_[k_]}']:.1f}" for cr, k_, _, f in CRIT for c in ("0", "20.8", "50")] for b in BOOKS]
    rob2_rows = [[E(b)] + [f"{bk_(b)['F1_liq_pct']:.1f}", f"{bk_(b)['F3_liq_pct']:.1f}", pc(bk_(b)["liq_cagr"]), f"{bk_(b)['F1_live_pct']:.1f}", f"{bk_(b)['F3_live_pct']:.1f}", pc(bk_(b)["live_cagr"]),
                          ("NOT REPORTABLE" if b in notrep_live else "reportable")] for b in BOOKS]
    r4_io = [[E(b)] + [x_ for f in ("F1", "F2") for x_ in (f"{bk_(b)[f'{f}_pct_cagr']:.1f}", f"{bk_(b)[f'{f}_pct_dd']:.1f}", pc(bk_(b)[f"{f}_median_cagr"]), f"{100 * bk_(b)[f'{f}_sd_cagr']:.2f}", pc(bk_(b)[f"{f}_p5_cagr"]), pc(bk_(b)[f"{f}_p95_cagr"]))] for b in BOOKS]
    r4_g = [[E(b)] + [x_ for f in ("F3", "F4") for x_ in (f"{bk_(b)[f'{f}_pct_cagr']:.1f}", f"{bk_(b)[f'{f}_pct_dd']:.1f}", pc(bk_(b)[f"{f}_median_cagr"]), f"{100 * bk_(b)[f'{f}_sd_cagr']:.2f}", pc(bk_(b)[f"{f}_p5_cagr"]), pc(bk_(b)[f"{f}_p95_cagr"]))] for b in BOOKS]
    t06_rows = [[E(b), pc(t06ref[b]["cagr"]), f"{t06ref[b]['n10_pct_cagr']:.1f}", f"{t06ref[b]['n10_pct_dd']:.1f}", f"{t06ref[b]['n9_pct_cagr']:.1f}", f"{t06ref[b]['n9_pct_dd']:.1f}"] for b in BOOKS] if t06ref else []
    r5_rows = [[E(b), pc(bk_(b)["cagr"]), pc(bk_(b)["F5_median_cagr"]), f"{100 * bk_(b)['F5_sd_cagr']:.2f}", f"{bk_(b)['F5_pct_cagr']:.1f}", f"{bk_(b)['F5_p_cagr']:.3f}", f"{bk_(b)['F5_pct_dd']:.1f}", f"{bk_(b)['F5_p_dd']:.3f}"] for b in BOOKS]
    r6_rows = [[E(b), f"{100 * bk_(b)['r6_rule_dcagr']:+.2f}", f"{100 * bk_(b)['r6_rule_ddd']:+.2f}"] + [x_ for f in ("F1", "F2") for x_ in (f"{100 * bk_(b)[f'r6_{f}_median_dcagr']:+.2f}", f"{bk_(b)[f'r6_{f}_pct_dcagr']:.1f}", f"{100 * bk_(b)[f'r6_{f}_share_dcagr']:.0f}%",
                                                                                                                  f"{100 * bk_(b)[f'r6_{f}_median_ddd']:+.2f}", f"{bk_(b)[f'r6_{f}_pct_ddd']:.1f}", f"{100 * bk_(b)[f'r6_{f}_share_ddd']:.0f}%")] for b in BOOKS]
    ses_rows = [[E(b), f"{bk_(b)['rule_sessions']:,}", f"{bk_(b)['sessions_total']:,}"] + [x_ for f in ("F1", "F2") for x_ in (f"{bk_(b)[f'{f}_sess_min']:,}", f"{bk_(b)[f'{f}_sess_median']:,.1f}", f"{bk_(b)[f'{f}_sess_max']:,}")] for b in BOOKS]
    str_rows = [[E(b), str(bk_(b)["sleeve_trades"])] + [x_ for f in ("F3", "F4") for x_ in (f"{bk_(b)[f'{f}_strades_min']}", f"{bk_(b)[f'{f}_strades_median']:.1f}", f"{bk_(b)[f'{f}_strades_max']}")] for b in BOOKS]

    # ── charts: per-book curves ───────────────────────────────────────────────
    curves_html, lines_data = "", {}
    for b in BOOKS:
        ser, dates = {}, None
        for kind in KINDS:
            q = nav[(nav.book == b) & (nav.cost_bps == PRIMARY) & (nav.run == kind)].sort_values("date")
            ser[kind] = q.nav.values
            dates = list(q.date)
        ser["published_D17"] = nav[(nav.book == b) & (nav.run == "published_D17")].sort_values("date").nav.values
        lsvg, ldata = svg_lines(ser, dates, ylab=b)
        lines_data[b] = ldata
        curves_html += (f'<figure class="card hv"><figcaption><b>{E(b)}</b> · growth of 1 from {dates[0].date()} to {dates[-1].date()}, 20.8 bps · rule ends at {bk_(b)["end_nav"]:.2f}×. '
                        f'Hover (or touch): the crosshair shows the date and the level, and the tooltip lists all eight curves at that date (the lines are drawn every 5th session, and the hover snaps to those sessions).</figcaption>'
                        + lsvg + '<div class="tip" hidden></div></figure>')
    legend = "".join(f'<span class="key"><i style="background:{COL[k_]}"></i>{E(LAB[k_])}</span>' for k_ in COL)

    # ── charts: null histograms, both timings, each deciding null with the null beside it overlaid ──
    bars_data, hists = {}, ""
    pct_fmt = lambda v: f"{100 * v:.1f}%"
    for b in BOOKS:
        x = bk_(b)
        for tim, fd, fb, tlab in (("io", "F1", "F2", "in-or-out timing (F1 deciding, F2 beside); the real MAUc1 signal in every draw"), ("gold", "F3", "F4", "gold timing (F3 deciding, F4 beside); the real in-or-out switch in every draw")):
            nd, nb = D(b, fd), D(b, fb)
            cells = ""
            for what, col, mark, title, note in (("cagr", "cagr", x["cagr"], "After-cost CAGR", "right = better"), ("dd", "max_dd", x["max_dd"], "Maximum drawdown", "shallower is to the right")):
                ad, ab = nd[col].values, nb[col].values
                lo_, hi_ = float(min(ad.min(), ab.min(), mark)), float(max(ad.max(), ab.max(), mark))
                pad = (hi_ - lo_) * 0.04
                edges = np.linspace(lo_ - pad, hi_ + pad, 33)
                cd, _ = np.histogram(ad, bins=edges)
                cb, _ = np.histogram(ab, bins=edges)
                marks = [{"label": "The rule", "x": mark, "col": "var(--fg)", "txt": f"percentile {x[f'{fd}_pct_{what}']:.1f} vs {fd}, {x[f'{fb}_pct_{what}']:.1f} vs {fb}"},
                         {"label": f"{fd} median", "x": float(np.median(ad)), "col": C10, "txt": "(blue, dashed)", "dash": True},
                         {"label": f"{fb} median", "x": float(np.median(ab)), "col": C9, "txt": "(orange, dashed)", "dash": True}]
                did = f"hist|{b}|{tim}|{what}"
                xt = [(float(v), pct_fmt(v)) for v in np.linspace(lo_, hi_, 5)]
                svg, bd = svg_bars(did, edges, [{"k": fb, "label": f"{fb} (spell shuffle)", "col": C9, "v": cb, "n": len(ab)}, {"k": fd, "label": f"{fd} (free lengths)", "col": C10, "v": cd, "n": len(ad)}],
                                   marks=marks, xk="pct", yk="int", xticks=xt, binlab=[f"{pct_fmt(edges[i])} to {pct_fmt(edges[i + 1])}" for i in range(32)], yunit="draws")
                bars_data[did] = bd
                cells += f'<div class="hv"><div class="mini">{title} ({note}; black = the rule, dashed = medians)</div>{svg}<div class="tip wrap" hidden></div></div>'
            hists += (f'<figure class="card"><figcaption><b>{E(b)}</b> · {E(tlab)} · {ND:,} draws of each null, 20.8 bps, {first_dec[b]} → {end_date}</figcaption><div class="two">{cells}</div></figure>')

    # ── charts: spell-length distributions ────────────────────────────────────
    lenhtml = ""
    for b in BOOKS:
        for tim, fd, fb, parts in (("io", "F1", "F2", (("in", 1, "in", rin), ("out", 0, "out", rout))), ("gold", "F3", "F4", (("buy", 1, "buy", gbuy), ("sell", 0, "sell", gsell)))):
            cells = ""
            Ad, Ab = states[f"{b}|full|io|N4.10"] if tim == "io" else states[f"{b}|full|gold|N4.10-g"], states[f"{b}|full|io|N4.9"] if tim == "io" else states[f"{b}|full|gold|N4.9-g"]
            for nm, v_, _, rl_all in parts:
                hi_ = HI[nm]
                ld = np.array([x_ for i in range(Ad.shape[0]) for x_ in lens(Ad[i], v_)])
                lb = np.array([x_ for i in range(Ab.shape[0]) for x_ in lens(Ab[i], v_)])
                edges = np.arange(LO, hi_ + 2) - 0.5
                cd, _ = np.histogram(ld, bins=edges)
                cb, _ = np.histogram(lb, bins=edges)
                rl = rl_all[b]
                extra = [(f"The real series has {rl.count(x_)} {nm}-spell(s) of exactly this length" if rl.count(x_) else None) for x_ in range(LO, hi_ + 1)]
                did = f"len|{b}|{nm}"
                svg, bd = svg_bars(did, edges, [{"k": fb, "label": f"{fb} (= the real series' own lengths)", "col": C9, "v": cb, "n": len(lb)}, {"k": fd, "label": f"{fd} (free lengths)", "col": C10, "v": cd, "n": len(ld)}],
                                   marks=[], xk="wk", yk="int", w=380, h=170, xticks=[(float(v), str(v)) for v in range(LO, hi_ + 1, 8 if hi_ > 30 else 6)], extra=extra,
                                   binlab=[f"{x_} weeks" for x_ in range(LO, hi_ + 1)], yunit="spells")
                bars_data[did] = bd
                cells += (f'<div class="hv"><div class="mini">{nm}-spell lengths in weeks ({LO} to {hi_}); the real series\': {", ".join(map(str, rl))}</div>{svg}<div class="tip wrap" hidden></div></div>')
            lenhtml += f'<figure class="card"><figcaption><b>{E(b)}</b> · every {"in-or-out" if tim == "io" else "gold"} spell of {ND:,} draws of {fd} and {fb}, full window {first_dec[b]} → {end_date}</figcaption><div class="two">{cells}</div></figure>'

    # ── charts: the samplers' first steps (draw 0) ────────────────────────────
    samplers = {}
    for did, kk, SSx, bndx, stp, key_, lab_, nm_ in (("sampler|first", ks["in"], SS["in"], bnd["in"], steps[0], "sampler_first", "in-spell", "in"), ("sampler|first_g", ksg["buy"], SSg["buy"], bndg["buy"], stepsg[0], "sampler_first_g", "BUY spell", "buy")):
        c_ = dp_table(kk, SSx, *bndx)
        xs = list(range(LO, bndx[1] + 1))
        wv = [c_[kk - 1][SSx - x_] if SSx - x_ >= 0 else 0 for x_ in xs]
        edges = np.arange(LO, bndx[1] + 2) - 0.5
        smark = [{"label": "Draw 0 picked", "x": float(stp["x"]), "col": "var(--fg)", "txt": f"(u = {stp['u']:.6f}; P = {stp['p']:.4f})"}]
        ssvg, sbd = svg_bars(did, edges, [{"k": "w", "label": "ways to finish after this length", "col": C10, "v": wv, "n": int(sum(wv)), "op": 0.7}], marks=smark, xk="wk", yk="si", w=520, h=190, L=56,
                             xticks=[(float(v), str(v)) for v in range(LO, bndx[1] + 1, 8)], binlab=[f"first {lab_} = {x_} weeks" for x_ in xs],
                             extra=[f"c({kk - 1}, {SSx} - {x_}) = {wv[i]:,} of c({kk}, {SSx}) = {int(sum(wv)):,} ways" for i, x_ in enumerate(xs)], yunit="ways")
        bars_data[did] = sbd
        data[key_] = {"xs": xs, "weights": [int(v) for v in wv]}
        samplers[did] = (ssvg, xs)

    # ── the highest-CAGR F1 draw against the rule (SCMO_0003) ─────────────────
    bb = "SCMO_0003"
    nbb = D(bb, "F1")
    bbest = nbb.loc[nbb.cagr.idxmax()]
    bid = int(bbest.draw_id)
    rs_ = rule[bb].astype(int)
    ds_ = states[f"{bb}|full|io|N4.10"][bid].astype(int)
    bcurve = curves[f"{bb}|F1_{bid}"].astype(float)
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
        pa, sl_ = pnav[e_] / pnav[s_], snav[e_] / snav[s_]
        cls_w[c_] += wks
        cls_p[c_] *= pa
        cls_s[c_] *= sl_
        tip = f"{bdates[s_].date()} → {bdates[e_].date()}, {wks} wk: {CODE[c_]}. Parent {pr(pa)}, 50/50 sleeve {pr(sl_)}"
        pair_runs.append((c_, s_, e_, tip))
        if c_ in (1, 2):
            right = ("draw" if c_ == 1 else "rule") if pa > sl_ else ("rule" if c_ == 1 else "draw")
            span_stats.append((c_, wks, pa, sl_, right))
            span_rows.append([str(bdates[s_].date()), str(bdates[e_].date()), str(wks), f"Draw {bid}" if c_ == 1 else "Rule", pr(pa), pr(sl_), f"{100 * (pa - sl_):+.1f} pp", f"<b>{right}</b>"])
    rule_runs = [(v_, s_, e_) for v_, s_, e_, *_ in runs_of(rs_, wk0, wk1)]
    draw_runs = [(v_, s_, e_) for v_, s_, e_, *_ in runs_of(ds_, wk0, wk1)]
    gb_ = gold[bb].astype(int)
    gold_runs = [(v_, s_, e_) for v_, s_, e_, *_ in runs_of(gb_, wk0, wk1)]
    wcode = lambda s_: np.where(s_ == 1, -1, np.rint(10 * gwk[bb]).astype(int))
    rw_runs = [(v_, s_, e_) for v_, s_, e_, *_ in runs_of(wcode(rs_), wk0, wk1)]
    dw_runs = [(v_, s_, e_) for v_, s_, e_, *_ in runs_of(wcode(ds_), wk0, wk1)]
    assert abs(np.prod(list(cls_p.values())) / pnav[-1] * pnav[0] - 1) < 1e-9
    ser_b = {"hold_parent": pnav, "draw": bcurve, "strategy": rq.nav.values}
    st_rule, st_draw, tip_ix, g_sess, gw_sess = np.zeros(nses, int), np.zeros(nses, int), np.zeros(nses, int), np.zeros(nses, int), np.zeros(nses)
    for j_ in range(len(rs_)):
        st_rule[wk0[j_]:wk1[j_]], st_draw[wk0[j_]:wk1[j_]] = rs_[j_], ds_[j_]
        g_sess[wk0[j_]:wk1[j_]], gw_sess[wk0[j_]:wk1[j_]] = gb_[j_], gwk[bb][j_]
    for r_, (c_, s_, e_, tip) in enumerate(pair_runs):
        tip_ix[s_:e_] = r_
    st_rule[-1], st_draw[-1], tip_ix[-1], g_sess[-1], gw_sess[-1] = st_rule[-2], st_draw[-2], tip_ix[-2], g_sess[-2], gw_sess[-2]
    hover = {"dates": [d_.strftime("%Y-%m-%d (%a)") for d_ in bdates], "rule": [round(float(v_), 4) for v_ in rq.nav.values], "draw": [round(float(v_), 4) for v_ in bcurve],
             "parent": [round(float(v_), 4) for v_ in pnav], "rs": st_rule.tolist(), "ds": st_draw.tolist(), "g": g_sess.tolist(), "gw": [round(float(v_), 4) for v_ in gw_sess],
             "tip": tip_ix.tolist(), "tips": [p_[3] for p_ in pair_runs], "draw_label": f"Draw {bid}"}
    cls_rows = [[CODE[c_], str(cls_w[c_]), pr(cls_p[c_]), pr(cls_s[c_]), f"{100 * (cls_p[c_] - cls_s[c_]):+.1f} pp"] for c_ in (3, 0, 1, 2)]
    wrong = lambda c_: sum(1 for s in span_stats if s[0] == c_ and s[4] != ("draw" if c_ == 1 else "rule"))
    n1, n2 = sum(1 for s in span_stats if s[0] == 1), sum(1 for s in span_stats if s[0] == 2)
    spr, spd = runs(rs_), runs(ds_)
    ln = lambda s_, v_: [n_ for x_, n_ in s_ if x_ == v_]
    ses_r = sum(wk1[j_] - wk0[j_] for j_ in range(len(rs_)) if rs_[j_] == 1)
    ses_d = sum(wk1[j_] - wk0[j_] for j_ in range(len(ds_)) if ds_[j_] == 1)
    nw = len(rs_)
    fl = lambda ok, txt="held": f'<span class="chip ok">{txt}</span>' if ok else f'<span class="chip warn">{txt}</span>'
    in_ok = all(LO <= x_ <= HI["in"] for x_ in ln(spd, 1)) and sum(ln(spd, 1)) == sum(ln(spr, 1))
    out_ok = all(LO <= x_ <= HI["out"] for x_ in ln(spd, 0)) and sum(ln(spd, 0)) == sum(ln(spr, 0))
    hold_tab = [
        [f"Weeks invested (of {nw})", f"{rs_.sum()} ({pc(rs_.mean(), 2)})", f"{ds_.sum()} ({pc(ds_.mean(), 2)})", fl(rs_.sum() == ds_.sum())],
        [f"Sessions invested (of {nses - 1:,})", f"{ses_r} ({pc(ses_r / (nses - 1), 2)})", f"{ses_d} ({pc(ses_d / (nses - 1), 2)})", fl(ses_r == ses_d, "held" if ses_r == ses_d else f"not held: differs by {abs(ses_r - ses_d)}")],
        ["In-spells · out-spells", f"{len(ln(spr, 1))} · {len(ln(spr, 0))}", f"{len(ln(spd, 1))} · {len(ln(spd, 0))}", fl((len(ln(spr, 1)), len(ln(spr, 0))) == (len(ln(spd, 1)), len(ln(spd, 0))))],
        ["Entries (0→1) · exits (1→0)", f"{ent(rs_)} · {ext(rs_)}", f"{ent(ds_)} · {ext(ds_)}", fl((ent(rs_), ext(rs_)) == (ent(ds_), ext(ds_)))],
        ["First state", "sleeve" if rs_[0] == 0 else "parent", "sleeve" if ds_[0] == 0 else "parent", fl(rs_[0] == ds_[0])],
        ["In-spell lengths (weeks), in order", ", ".join(map(str, ln(spr, 1))), ", ".join(map(str, ln(spd, 1))), fl(in_ok, f"free: sum equal, each in [{LO}, {HI['in']}]" if in_ok else "OUT OF BOUNDS")],
        ["Out-spell lengths (weeks), in order", ", ".join(map(str, ln(spr, 0))), ", ".join(map(str, ln(spd, 0))), fl(out_ok, f"free: sum equal, each in [{LO}, {HI['out']}]" if out_ok else "OUT OF BOUNDS")],
        ["The MAUc1 signal in the weeks each is OUT", "real", "real (the same series)", fl(True, "held, real")],
        ["Timing and lengths of the in-or-out spells", "the rule's own", "drawn from the allowed tuples", '<span class="chip">randomised</span>'],
    ]
    rsvg, geom = svg_regime(bdates, ser_b, rule_runs, draw_runs, pair_runs, gold_runs, rw_runs, dw_runs, f"Draw {bid}")
    hover.update(geom)
    data["best_draw"] = {"book": bb, "draw_id": bid, "cagr": float(bbest.cagr), "end_nav": float(bbest.end_nav), "rule_cagr": bk_(bb)["cagr"], "weeks_both_in": cls_w[3], "weeks_both_out": cls_w[0],
                         "weeks_draw_only": cls_w[1], "weeks_rule_only": cls_w[2], "spans_draw_only": n1, "spans_rule_only": n2, "weeks_invested_rule": int(rs_.sum()), "weeks_invested_draw": int(ds_.sum()),
                         "sessions_invested_rule": int(ses_r), "sessions_invested_draw": int(ses_d), "sessions_span": int(nses - 1), "in_spells": len(ln(spr, 1)), "out_spells": len(ln(spr, 0)),
                         "entries": ent(rs_), "exits": ext(rs_), "draw_in": ln(spd, 1), "draw_out": ln(spd, 0), "pct_vs_F1": bk_(bb)["F1_pct_cagr"]}

    # the highest-CAGR F3 draw: held table only
    ng = D(bb, "F3")
    gbest = ng.loc[ng.cagr.idxmax()]
    gid = int(gbest.draw_id)
    gd_ = states[f"{bb}|full|gold|N4.10-g"][gid].astype(int)
    sp_g, sp_d = runs(gb_), runs(gd_)
    flips_out = lambda gx: int(sum(1 for j_ in range(1, len(rs_)) if rs_[j_ - 1] == 0 and rs_[j_] == 0 and gx[j_] != gx[j_ - 1] and not pd.isna(d.trade_date[j_])))
    gin_ok = all(LO <= x_ <= HI["buy"] for x_ in ln(sp_d, 1)) and sum(ln(sp_d, 1)) == sum(ln(sp_g, 1))
    gout_ok = all(LO <= x_ <= HI["sell"] for x_ in ln(sp_d, 0)) and sum(ln(sp_d, 0)) == sum(ln(sp_g, 0))
    gold_tab = [
        [f"Weeks with the gold signal BUY (of {nw})", f"{gb_.sum()} ({pc(gb_.mean(), 2)})", f"{gd_.sum()} ({pc(gd_.mean(), 2)})", fl(gb_.sum() == gd_.sum())],
        ["BUY-spells · SELL-spells", f"{len(ln(sp_g, 1))} · {len(ln(sp_g, 0))}", f"{len(ln(sp_d, 1))} · {len(ln(sp_d, 0))}", fl((len(ln(sp_g, 1)), len(ln(sp_g, 0))) == (len(ln(sp_d, 1)), len(ln(sp_d, 0))))],
        ["First gold state", "BUY" if gb_[0] else "SELL", "BUY" if gd_[0] else "SELL", fl(gb_[0] == gd_[0])],
        ["BUY-spell lengths (weeks), in order", ", ".join(map(str, ln(sp_g, 1))), ", ".join(map(str, ln(sp_d, 1))), fl(gin_ok, f"free: sum equal, each in [{LO}, {HI['buy']}]" if gin_ok else "OUT OF BOUNDS")],
        ["SELL-spell lengths (weeks), in order", ", ".join(map(str, ln(sp_g, 0))), ", ".join(map(str, ln(sp_d, 0))), fl(gout_ok, f"free: sum equal, each in [{LO}, {HI['sell']}]" if gout_ok else "OUT OF BOUNDS")],
        ["The in-or-out switch", "real", "real (the same series)", fl(True, "held, real")],
        ["Gold flips while OUT on both sides (the sleeve trades)", str(flips_out(gb_)), str(flips_out(gd_)), '<span class="chip warn">not held: the draw\'s flips in IN weeks never trade</span>'],
        ["Timing and lengths of the gold spells", "the real series' own", "drawn from the allowed tuples", '<span class="chip">randomised</span>'],
    ]
    data["best_gold_draw"] = {"book": bb, "draw_id": gid, "cagr": float(gbest.cagr), "end_nav": float(gbest.end_nav), "buy_weeks_real": int(gb_.sum()), "buy_weeks_draw": int(gd_.sum()), "spells_real": [len(ln(sp_g, 1)), len(ln(sp_g, 0))],
                              "spells_draw": [len(ln(sp_d, 1)), len(ln(sp_d, 0))], "draw_buy": ln(sp_d, 1), "draw_sell": ln(sp_d, 0), "flips_out_real": flips_out(gb_), "flips_out_draw": flips_out(gd_), "sleeve_trades_draw": int(gbest.sleeve_trades),
                              "pct_vs_F3": bk_(bb)["F3_pct_cagr"]}

    def md_table_html(key):
        hdr, rows_ = mdt[key]
        return table([[md_inline(c) for c in r_] for r_ in rows_], [re.sub(r"[*`]", "", c) for c in hdr], "wrap")
    null_tables = md_table_html("io") + md_table_html("gold")
    regime = (f'<h2 id="regime">The highest-return F1 draw against the rule ({bb})</h2>'
              f'<p>The right-hand end of the {bb} F1 CAGR histogram above is draw {bid}: CAGR {pc(float(bbest.cagr))} (end value {float(bbest.end_nav):.1f}×), against the rule\'s {pc(bk_(bb)["cagr"])} ({bk_(bb)["end_nav"]:.1f}×). '
              f'It holds the parent for the same {int(bbest.invested_weeks)} weeks and switches the same number of times as the rule, but its spell lengths are its own; its sleeve reads the <b>real</b> MAUc1 signal in whatever weeks it is OUT. '
              f'Its states are row {bid} of <code>evidence/{E(ev.name)}/draw_states.npz</code>, key <code>{bb}|full|io|N4.10</code> (read straight from the file, no rebuild), and its curve is <code>draw_curves_20.8.npz</code> key <code>{bb}|F1_{bid}</code>.</p>'
              f'<h3>What F1 holds, and what it randomises, for this draw</h3>'
              + table(hold_tab, ["Dimension", "The rule", f"Draw {bid}", "Held?"])
              + f'<p class="cap">Weeks invested, spell counts, entries and exits and the first state are held exactly (gate V3); every spell\'s length and so its position are drawn, each length within its bounds and the in- and out-lengths summing to the rule\'s totals. '
                f'Sessions are not held exactly: a week has 3 to 5 sessions. Here the two differ by {abs(ses_r - ses_d)} of {nses - 1:,} sessions ({100 * abs(ses_r - ses_d) / (nses - 1):.2f} pp of the window).</p>'
              f'<div class="legend"><span class="key"><i style="background:{COL["strategy"]}"></i>Rule</span><span class="key"><i style="background:var(--fg)"></i>Draw {bid}</span>'
              f'<span class="key"><i style="background:{COL["hold_parent"]}"></i>Hold the parent</span>'
              f'<span class="key"><i style="background:{COL["strategy"]};height:10px;opacity:.5"></i>only the rule holds the parent</span>'
              f'<span class="key"><i style="background:var(--fg);height:10px;opacity:.4"></i>only the draw holds the parent</span><span class="key"><i style="background:#c9a227;height:10px"></i>MAUc1 BUY</span></div>'
              f'<figure class="card hv"><figcaption><b>{bb}</b> · growth of 1 from {bdates[0].date()} to {bdates[-1].date()}, 20.8 bps (log scale); the grey line is the parent held throughout, before cost. '
              f'Strips: the first two are filled when the book holds the parent that week (empty = in the sleeve), the third marks where they differ, the fourth is filled when the weekly MAUc1 signal is BUY, and the last two show the GOLDBEES target weight of the sleeve '
              f'(bar height: 80% when MAUc1 is BUY, 20% when SELL; empty while holding the parent). Hover (or touch) anywhere on the chart: the crosshair shows the date on the x-axis and the level on the y-axis, and the tooltip lists every value drawn at that date, the signal and the sleeve split.</figcaption>'
              + rsvg + '<div id="regime-tip" class="tip" hidden></div></figure>'
              f'<h3>Weeks by what the two did</h3>'
              + table(cls_rows, ["The two timings", "Weeks", "Parent, compounded over these weeks", "50/50 sleeve, same weeks", "Parent minus sleeve"])
              + f'<p>They agree in {cls_w[3] + cls_w[0]} of {len(code)} weeks and differ in {cls_w[1] + cls_w[2]}, in {n1 + n2} separate stretches. '
                f'In the stretches only the draw held the parent, the parent beat the sleeve in {n1 - wrong(1)} of {n1}; in the stretches only the rule held it, the parent beat the sleeve in {n2 - wrong(2)} of {n2}.</p>'
              + '<h3>Every stretch where they differ</h3>'
              + table(span_rows, ["From", "To", "Weeks", "Holds the parent", "Parent", "50/50 sleeve", "Parent minus sleeve", "Right call"])
              + '<p class="cap">Returns are close to close between trade dates, before cost, and compounded within each stretch, so the stretches explain the gap between the two paths but do not add up exactly to the CAGR difference. '
                '"Right call" is the timing that was in the better of parent and 50/50 sleeve over the stretch (the sleeve here is the plain 50/50 one: the stretch table compares the parent with a neutral sleeve, not with the MAUc1 split). '
                f'Draw {bid} is the best of {len(nbb):,} F1 draws, so it is the extreme of the null by construction, not a rival rule.</p>'
              f'<h3>The highest-return F3 draw (gold timing), {bb}</h3>'
              f'<p>Draw {gid} of F3: CAGR {pc(float(gbest.cagr))} (end value {float(gbest.end_nav):.2f}×) against the rule\'s {pc(bk_(bb)["cagr"])}. It keeps the real in-or-out switch and the number of gold spells and BUY weeks, but its gold spells fall elsewhere (states: row {gid} of <code>draw_states.npz</code>, key <code>{bb}|full|gold|N4.10-g</code>).</p>'
              + table(gold_tab, ["Dimension", "The real series", f"F3 draw {gid}", "Held?"]))

    # ── the worked example html ───────────────────────────────────────────────
    b = "SCMO_0003"
    ex = data["example"]
    exx, exf = ex["exit"], ex["flip"]
    nvw = nv.loc[k - 2:k + 2]
    fmt_units = lambda u_: ", ".join(f"{E(k_)} {v_:.6f}" for k_, v_ in u_.items())
    ex_rows = [[str(j_), str(d.decision_date.iloc[j_]), str(int(rule[b][j_])), str(int(Z["io|N4.9"][0][j_])), str(int(Z["io|N4.10"][0][j_])), str(int(gold[b][j_])), str(int(Z["gold|N4.9-g"][0][j_])), str(int(Z["gold|N4.10-g"][0][j_]))] for j_ in range(20)]
    step_rows = [[s_["spell"], str(s_["part"]), str(s_["m"]), str(s_["t"]), f"{s_['u']:.6f}", f"{s_['total']:,}", f"<b>{s_['x']}</b>", f"{s_['ways_x']:,}", f"{100 * s_['p']:.2f}%"] for s_ in steps]
    step_rows_g = [[s_["spell"], str(s_["part"]), str(s_["m"]), str(s_["t"]), f"{s_['u']:.6f}", f"{s_['total']:,}", f"<b>{s_['x']}</b>", f"{s_['ways_x']:,}", f"{100 * s_['p']:.2f}%"] for s_ in stepsg]
    g4rows = [[E(r_.book), f"{r_.cagr_gap_pp_yr:+.3f}", r_.overall, str(r_.worst_year), f"{r_.worst_year_gap_pp:+.3f}", r_.yearly, (f"{r_.window_first} → {r_.window_last}" if hasattr(r_, "window_first") else "")] for r_ in g4.itertuples()]
    gate_desc = {"V1": "verify_t08.py shares no code with the engine" + (f": {ver['gate_compared']:,} comparisons, {ver.get('gate_failures_and_missing')} failures, a corrupted copy is caught: {ver.get('selftest', {}).get('detected')}" if ver else ""),
                 "V2": "every decision reads Master rows (three indices and MAUc1) dated on or before it; every trade is on a later session",
                 "V3": "all nulls hold their tables: weeks, first state, spell counts and sums of the in-or-out and the gold series; N4.9 and N4.9-g sorted lengths; N4.10 and N4.10-g bounds",
                 "V4": "decisions and NAVs equal T06's on the overlap (sleeve fixed at 50/50); always-in reproduces the published NAV within G0; the gold signal equals D24's file",
                 "V5": "the samplers: chi-square on the small case, DP count equals inclusion-exclusion for every table, mean lengths at each position",
                 "V6": "the sleeve identity: post-trade GOLDBEES and cash equal their targets, cost = traded × cost_bps ÷ 2 ÷ 10,000, no trade while OUT with the signal constant"}
    gate_rows = [[f"{k_} {n_}", f'<span class="chip {"ok" if (gate_line or {}).get(k_) == "PASS" else "bad"}">{(gate_line or {}).get(k_, "NOT RUN")}</span>', E(gate_desc[k_])]
                 for k_, n_ in (("V1", "independent check"), ("V2", "point in time"), ("V3", "the nulls hold their tables"), ("V4", "regression to T06, always-in"), ("V5", "the samplers are exact"), ("V6", "the sleeve identity"))]
    inp_rows = [[E(r_.file), E(r_.through), E(r_.approved_row), E(r_.sha256[:16])] for r_ in inp.itertuples()]
    data["inputs"] = [{"file": r_.file, "through": r_.through, "approved_row": r_.approved_row, "sha16": r_.sha256[:16]} for r_ in inp.itertuples()]
    r7_html = ("<p>Not in evidence: the engine ships no raw-fill file. The sessions after 2026-09-28 (the MCX de-spike range ends there) are filled at the raw OHLC4; <code>sleeve_trades.csv</code> flags the rule's sleeve trades among them (<code>gold_fill_raw</code>).</p>"
               if data["r7"] is None else "<p>From <code>" + E(data["r7"]["file"]) + "</code>:</p>" + table([[E(c) for c in r_] for r_ in data["r7"]["rows"]], [E(c) for c in data["r7"]["columns"]]))
    raw_tr = sl[(sl.cost_bps == PRIMARY) & (sl.gold_fill_raw.astype(bool))]
    data["raw_fill_sleeve_trades"] = [[r_.book, r_.date, r_.kind] for r_ in raw_tr.itertuples()]

    if not gates_ok:
        lead = "A validity gate failed or analysis.log is missing: do not read the results below."
    elif A_ok and B_ok:
        lead = "Yes, on both timings: the equity switch and the MAUc1 timing of the sleeve each beat random timing on this window."
    elif A_ok:
        lead = "The equity switch beats chance; the MAUc1 timing of the sleeve is not distinguishable from random gold timing."
    elif B_ok:
        lead = "The gold timing beats random gold timing, but the equity switch no longer shows an edge with this sleeve."
    else:
        lead = "No: neither timing shows an edge over chance for the failing parts on this window."
    data["outcome"] = {"A": bool(A_ok), "B": bool(B_ok)}
    answer = (f'<div class="answer"><p><b>{lead}</b> Holding the parent only when the Nifty 100, Midcap 100 and Smallcap 100 are all BUY, and otherwise a sleeve of GOLDBEES and cash split 80/20 when the weekly MAUc1 gold supertrend is BUY and 20/80 when it is SELL, '
              f'against random timings, on {start3} → {end_date}, after 20.8 bps. '
              f'<b>C1</b> (return) and <b>C2</b> (worst fall) are judged against F1, random in-or-out timing with the real gold signal: {V["C1"]} of 4 books and {V["C2"]} of 4 at the 90th percentile (pre-registered pass: 3 of 4 each); F2 beside: {V["C1_F2"]} and {V["C2_F2"]}. '
              f'<b>C3</b> and <b>C4</b>, the new claim, are judged against F3, random gold timing with the real in-or-out switch: {V["C3"]} of 4 and {V["C4"]} of 4; F4 beside: {V["C3_F4"]} and {V["C4_F4"]}. Holm-adjusted p-values are in the table.</p>'
              f'<p>The catch: on the live decisions only ({live_start} → {end_date}) return beats the 90th percentile in {V["R3_live_C1"]} of 4 books against F1 and {V["R3_live_C3"]} of 4 against F3; the decisions before 2021-11 are a backfill by the production code, and so is every MAUc1 row; '
              f'the rule, its 80/20 weights and the MAUc1 signal were chosen after seeing 2014-2026 results; the weeks added since T06 (2026-10-23, 2026-10-30) hold one MAUc1 flip and no switch of the index rule; 22 GOLDBEES fills after 2026-09-28 use the raw OHLC4. Every result here is in-sample and PROVISIONAL.</p></div>')
    t06_html = (("<p>Historical reference, <b>a different window and a fixed 50/50 sleeve</b> (2019-01-02 → 2026-10-22, T06's stored N4.10 and N4.9 draws, 20.8 bps; not comparable draw for draw; no pass mark):</p>"
                 + table(t06_rows, ["Book", "T06 rule CAGR", "T06 N4.10 CAGR pct", "T06 N4.10 drawdown pct", "T06 N4.9 CAGR pct", "T06 N4.9 drawdown pct"])) if t06_rows else "")
    rt_n = bk_(EB := "SCMO_0003")["round_trips"]
    steps_chip = '<span class="chip ok">replay equals the stored draw</span>' if replay_ok else '<span class="chip bad">REPLAY DIFFERS from the stored draw</span>'
    steps_chip_g = '<span class="chip ok">replay equals the stored draw</span>' if replay_ok_g else '<span class="chip bad">REPLAY DIFFERS from the stored draw</span>'
    s1_, sg1 = steps[0], stepsg[0]
    mdl = lambda key: f"{min(bk_(b_)[key] for b_ in BOOKS):.1f} to {max(bk_(b_)[key] for b_ in BOOKS):.1f}"
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>T08 MAUc1-timed sleeve timing null</title><style>{CSS}</style></head><body><main>
<p class="eyebrow">AA · T08 · timing rule · pre-registration sha256 {E(sha[:12])} · data: APPROVED_DATA.md as of {E(str(asof_file))}</p>
<h1>Does the three-index switch with a MAUc1-timed GOLDBEES sleeve still choose <em>when</em> to hold the parent better than chance, and does the gold timing itself beat random gold timing?</h1>
<p class="meta">{start3} → {end_date} ({B7} from {start7}) · four parents of the AA books · decisions every Friday, trades next session at OHLC4 · 10.4 bps a side · {ND:,} draws per book, cost and null · every number is computed from <code>evidence/{E(ev.name)}/</code></p>
<h2 id="answer">The answer</h2>{answer}
{table(answer_rows, ["Book", "Rule CAGR", "C1 pct vs F1", "Holm p", "Rule worst fall", "C2 pct vs F1", "Holm p", "C3 pct vs F3", "Holm p", "C4 pct vs F3", "Holm p", "Live-only CAGR", "Live C1 pct vs F1", "Live C3 pct vs F3"])}
<p class="cap">Percentile = share of the {ND:,} draws the rule beats (ties count half). Pass mark: 90 in at least 3 of 4 books, against the deciding null (F1 for C1 and C2, F3 for C3 and C4). Holm p = Holm-adjusted p-value over the four criteria of that book (the pass mark is on the unadjusted percentile). After 20.8 bps round-trip cost. Full window {start3} → {end_date} ({B7} from {start7}); live-only = {live_start} → {end_date}. The four books have the same in-or-out decisions and the same gold series, so "3 of 4" is a consistency check, not four tests.</p>
<div class="tw"><table><tbody><tr><td>C1 equity timing (return), F1</td><td>{chip(V['C1'] >= 3)} {V['C1']} of 4</td><td>F2 beside it: {V['C1_F2']} of 4</td></tr><tr><td>C2 equity-switch protection (worst fall), F1</td><td>{chip(V['C2'] >= 3)} {V['C2']} of 4</td><td>F2 beside it: {V['C2_F2']} of 4</td></tr><tr><td>C3 gold timing (return), F3</td><td>{chip(V['C3'] >= 3)} {V['C3']} of 4</td><td>F4 beside it: {V['C3_F4']} of 4</td></tr><tr><td>C4 gold-timing protection (worst fall), F3</td><td>{chip(V['C4'] >= 3)} {V['C4']} of 4</td><td>F4 beside it: {V['C4_F4']} of 4</td></tr></tbody></table></div>
<h3>What to be careful about</h3><ul>
<li><b>Each null randomises one timing and holds the other real.</b> F1 and F2 move the in-or-out switch and read the real gold signal in whatever weeks they are OUT; F3 and F4 keep the real switch and move the gold signal. A pass says the rule's timing beats random placement of that one ingredient, not that it beats holding the parent. Both random together is only a robustness check (R5).</li>
<li><b>Only C3 and C4 are the new claim.</b> C1 and C2 replicate T06 under a different sleeve. The gold nulls move only the sleeve's split, so their spread is narrower than F1's (see the power tables).</li>
<li><b>Nothing is out of sample.</b> The rule, the 80/20 weights and MAUc1 were chosen after seeing 2014-2026 results. Decisions before 2021-11 and every MAUc1 row are the production code run backwards. On the live decisions only, return is {V['R3_live_C1']} of 4 at the 90th percentile against F1 and {V['R3_live_C3']} of 4 against F3.</li>
<li><b>{rt_n} round trips and {bk_(EB)['sleeve_trades']} sleeve trades per book</b> is all the evidence there is. The smallest return edge detectable at 80% power against F1 is {mdl('F1_mde_cagr_pp')} pp a year; against F3 {mdl('F3_mde_cagr_pp')} pp.</li>
<li><b>The books are one market.</b> {B7}'s return percentile against F1 is {bk_(B7)['F1_pct_cagr']:.1f} and against F3 {bk_(B7)['F3_pct_cagr']:.1f}.</li></ul>

<h2 id="data">The data</h2>
<p>Each parent's NAV is rebuilt every day from its own stocks (Eikon prices, price return, Polyplex's special dividend corrected), not read from a file. The published NAV (D17, extended) gives the calendar and a check: the engine's always-invested book reproduces it within the pre-registered tolerance. The gold signal is the weekly SIGN of MAUc1, MCX gold futures (D24). Every file below is an APPROVED row of <code>data/APPROVED_DATA.md</code>, whose "As of" date is <b>{E(str(asof_file))}</b> (the run recorded {E(str(asof_inputs))}). No price after {end_date} is read.</p>
<p><b>Periods.</b> <i>Full window</i>: {start3} → {end_date} ({B7} {start7} → {end_date}), {weeks['SCMO_0003']} weekly decisions ({B7} {weeks[B7]}). <i>Live window</i>: {live_start} → {end_date}, the decisions that were in production.</p>
{table(inp_rows, ["File (relative to AA/)", "Through", "Approved row", "sha256 (first 16)"])}
<p class="cap">Caveats, disclosed: (1) the LBES file's rows before 2026-08-10 have no recorded source (F-AA-D09); the rows after are LIQUIDCASE returns chained as level[t] = level[t-1] × (1 + r[t]) and run about 0.5 pp/yr rich against LIQUIDBEES (F-AA-D13); cash is 20% to 80% of the sleeve here, so this matters more than in T06 (R2). (2) The window ends inside the last approved basket (SCMO_0003 2026-09-10, the others 2026-09-16); the next rebalance is expected about mid-December 2026. (3) The weeks added since T06 (2026-10-23, 2026-10-30) hold one MAUc1 flip to SELL and no switch of the index rule. (4) The decisions before 2021-11 are a backfill by the production code, and every MAUc1 row is. (5) The MCX de-spike file ends 2026-09-28; the 22 later GOLDBEES sessions are filled at the raw OHLC4, and one real sleeve trade is among them (R7). (6) The rule, its weights and the signal were chosen after seeing the data, and the in-or-out N4.10 bounds after seeing T03's draw 445 (the gold bounds were not).</p>
<p><b>Always-in against the published NAV</b> (gate V4):</p>
{table(g4rows, ["Book", "CAGR gap vs published (pp/yr)", "Within ±0.25", "Worst calendar year", "Gap (pp)", "Within ±0.5", "Window of the always-in book"])}
<p><b>Validity gates</b> (from <code>analysis.log</code>; the page is only to be read if all six pass):</p>
{table(gate_rows, ["Gate", "Result", "What it checks"])}

<h2 id="one">One backtest, end to end ({b}, 20.8 bps, {start3} → {end_date})</h2>
<p><b>1. The decision.</b> On Friday {E(exx['decision_date'])} (week {exx['decision_week']}) the latest weekly rows of the three index files read Nifty 100 {E(str(rx.sign_Nifty100))}, Midcap 100 {E(str(rx.sign_MC100))}, Smallcap 100 {E(str(rx.sign_SC100))}, and the latest MAUc1 row ({E(str(rx.label_MAUc1))}) reads {E(exx['sign_MAUc1'])}. Not all three index signals are BUY, so the target is the sleeve, split {100 * exx['gw']:.0f}% GOLDBEES / {100 * (1 - exx['gw']):.0f}% cash because MAUc1 is {E(exx['sign_MAUc1'])}; last week the book held the parent.</p>
<div class="formula">state(d) = IN  if SIGN_Nifty100 = SIGN_MC100 = SIGN_SC100 = BUY (latest row dated on or before d), else OUT
g(d)     = SIGN of the latest MAUc1 row dated on or before d          w(d) = 0.8 if g(d) = BUY, 0.2 if SELL
IN  → 100% parent basket        OUT → w(d) GOLDBEES + (1 − w(d)) cash        (changed only when the target changes)</div>
<p><b>2. The exit trade.</b> On the next session, {E(exx['trade_date'])}, at the (open+high+low+close)/4 of every instrument the book sells the basket and buys GOLDBEES and cash. Value before: {exx['V']:.6f}; value traded (both sides): {exx['traded']:.6f}; cost = traded × 20.8 ÷ 2 ÷ 10,000 = {exx['cost']:.6f}. After the trade GOLDBEES is worth {exx['gold_after']:.6f} and cash {exx['cash_after']:.6f}, that is {100 * exx['gold_after'] / (exx['gold_after'] + exx['cash_after']):.2f}% in GOLDBEES (target {100 * exx['gw']:.0f}% of the value after cost, {exx['V'] - exx['cost']:.6f}). NAV at the close after the trade: {exx['nav_after']:.6f}.</p>
<div class="formula">traded = Σ |target value − held value|        cost = traded × cost_bps ÷ 2 ÷ 10,000
GOLDBEES value = w × (V − cost)        cash value = (1 − w) × (V − cost)        new units = value ÷ fill price</div>
<p><b>3. Units.</b> After the exit the book holds {fmt_units(exx['units_after'])}.</p>
<p><b>4. A gold flip.</b> While OUT on both sides, a change of the MAUc1 signal re-splits the sleeve; the weights otherwise drift. On Friday {E(exf['decision_date'])} (week {exf['decision_week']}) MAUc1 turned {"BUY" if exf['g_after'] else "SELL"} (the week before: {"BUY" if exf['g_before'] else "SELL"}) while the book was OUT in both weeks, so on {E(exf['trade_date'])} it sold and bought GOLDBEES and cash from their drifted values to {100 * exf['gw_after']:.0f}% / {100 * (1 - exf['gw_after']):.0f}% of the sleeve value after cost. Value before {exf['V']:.6f}; traded {exf['traded']:.6f}; cost {exf['cost']:.6f}.</p>
{table([["GOLDBEES", f"{exf['gold_before']:.6f}", f"{exf['gold_after']:.6f}", f"{exf['units_before'].get('GOLDBEES', float('nan')):.6f}", f"{exf['units_after'].get('GOLDBEES', float('nan')):.6f}"], ["Cash (LBES)", f"{exf['cash_before']:.6f}", f"{exf['cash_after']:.6f}", f"{exf['units_before'].get('LBES', float('nan')):.6f}", f"{exf['units_after'].get('LBES', float('nan')):.6f}"]], ["Instrument", "Value before", "Value after", f"Units before ({E(str(exf['prev_pos_date']))})", f"Units after ({E(exf['trade_date'])})"])}
<p class="cap">Units before are the units held after the previous trade (units do not change between trades). The value before and after use the same session's fill, so GOLDBEES value ÷ units, the fill price, is the same before and after, and so is the cash level.</p>
<p><b>5. Daily value.</b> NAV(t) = Σ units × close(t) over stocks, GOLDBEES and cash. Around the exit:</p>
{table([[str(r_.date.date()), f"{r_.nav:.6f}"] for r_ in nvw.itertuples()], ["Date", "NAV"])}
<p><b>6. Statistics.</b> The path runs from 1.000000 on {nv.date.iloc[0].date()} to {ex['end_nav']:.6f} on {nv.date.iloc[-1].date()}: {ex['sessions']} sessions, years = ({ex['sessions']} − 1) ÷ 252 = {(ex['sessions'] - 1) / 252:.4f}, CAGR = {ex['end_nav']:.4f}^(1 ÷ {(ex['sessions'] - 1) / 252:.4f}) − 1 = <b>{pc(ex['cagr'], 2)}</b>, worst fall {pc(ex['max_dd'], 2)}; {bk_(b)['trades']} trades of which {bk_(b)['sleeve_trades']} sleeve rebalances.</p>
<p><b>7. The real series and the draws.</b> The rule's in-or-out path is {len(rin[b]) + len(rout[b])} spells: {len(rin[b])} in (lengths {", ".join(map(str, rin[b]))}, sum {sum(rin[b])}) and {len(rout[b])} out (lengths {", ".join(map(str, rout[b]))}, sum {sum(rout[b])}), starting {"in" if rule[b][0] else "out"}. The real gold signal is {len(gbuy[b]) + len(gsell[b])} spells: {len(gbuy[b])} BUY (lengths {", ".join(map(str, gbuy[b]))}, sum {sum(gbuy[b])}) and {len(gsell[b])} SELL (lengths {", ".join(map(str, gsell[b]))}, sum {sum(gsell[b])}), starting {"BUY" if gold[b][0] else "SELL"}. The first 20 weekly states of the real series, of F2 draw 0 (the in-or-out spells reordered; seed <code>default_rng([3, 0])</code>), of F1 draw 0 (new in-or-out lengths; seed <code>default_rng([6, 0])</code>), of F4 draw 0 (the gold spells reordered; seed <code>default_rng([11, 3, 0])</code>) and of F3 draw 0 (new gold lengths; seed <code>default_rng([11, 6, 0])</code>). In-or-out: 1 = parent, 0 = sleeve; gold: 1 = BUY, 0 = SELL:</p>
{table(ex_rows, ["Week", "Date", "Real in-or-out", "F2 draw 0", "F1 draw 0", "Real gold", "F4 draw 0", "F3 draw 0"])}
<p><b>8. How one F1 draw is made.</b> It keeps the {ex['k_in']} in-spells and {ex['k_out']} out-spells, the first state ({"in" if rule[b][0] else "out"}) and the totals ({ex['S_in']} weeks in, {ex['S_out']} out), and draws every length as an integer from {LO} to {ex['hi_in']} (in) or {LO} to {ex['hi_out']} (out; the bounds are the rule's longest spells), every allowed set of lengths equally likely. With c(m, t) the number of ways to write t weeks as m lengths in the bounds, c(0, 0) = 1 and c(m, t) = Σ over x of c(m − 1, t − x), the parts are drawn one at a time: with m parts and t weeks left, P(length = x) = c(m − 1, t − x) ÷ c(m, t). The uniform number u is <code>rng.random()</code> and the length is the first x whose cumulative weight exceeds u × c(m, t). In-spell parts come first, then out-spell parts, from the same generator. The real MAUc1 signal is then read in whatever weeks the draw is OUT.</p>
<div class="formula">allowed in-tuples  c({ex['k_in']}, {ex['S_in']}) = {int(ex['ways_in']):,}   (count_table.json: {int(ex['ways_in_table']):,})
allowed out-tuples c({ex['k_out']}, {ex['S_out']}) = {int(ex['ways_out']):,}   (count_table.json: {int(ex['ways_out_table']):,})</div>
<p>The first step of draw 0, in-spell 1: m = {ex['k_in']} parts and t = {ex['S_in']} weeks left, so the {len(samplers['sampler|first'][1])} candidate lengths {LO} … {ex['hi_in']} have weights c({ex['k_in'] - 1}, {ex['S_in']} − x). u = {s1_['u']:.6f}; u × c({ex['k_in']}, {ex['S_in']}) = {s1_['u'] * s1_['total']:,.0f} falls in the weight of length {s1_['x']}, so the first in-spell is {s1_['x']} weeks.</p>
<figure class="card hv"><figcaption>Weights of the candidate first in-spell lengths for F1 draw 0 (m = {ex['k_in']}, t = {ex['S_in']}); the black line is the length drawn. Hover: the crosshair shows the length and the weight at the pointer, the tooltip the weight and its share of c({ex['k_in']}, {ex['S_in']}).</figcaption>{samplers['sampler|first'][0]}<div class="tip wrap" hidden></div></figure>
<p>All {len(steps)} steps of F1 draw 0, replayed here from the seed with the same rule: {steps_chip}.</p>
{table(step_rows, ["Spell", "Part", "Parts left m", "Weeks left t", "u", "c(m, t)", "Length drawn", "c(m−1, t−x)", "P(x)"])}
<p>F1 draw 0's in-spell lengths are {", ".join(map(str, lens(Z['io|N4.10'][0], 1)))} (the rule's: {", ".join(map(str, rin[b]))}) and its out-spell lengths {", ".join(map(str, lens(Z['io|N4.10'][0], 0)))} (the rule's: {", ".join(map(str, rout[b]))}). It earns {pc(ex['d0']['F1']['cagr'], 2)} a year with a worst fall of {pc(ex['d0']['F1']['max_dd'], 2)}, invested for {ex['d0']['F1']['sessions']} sessions (the rule: {rule_sess[b]}; F2 draw 0: {ex['d0']['F2']['sessions']}), the same {int(x0['F1'].invested_weeks)} weeks.</p>
<p><b>9. How one F3 draw is made.</b> The same sampler, with the gold series' spells: {ex['k_buy']} BUY-spells and {ex['k_sell']} SELL-spells, first state {"BUY" if gold[b][0] else "SELL"}, totals {ex['S_buy']} weeks BUY and {ex['S_sell']} SELL; BUY lengths are integers from {LO} to {ex['hi_buy']}, SELL lengths from {LO} to {ex['hi_sell']} (the real series' longest BUY and SELL spells, computed before any return was read), BUY lengths first, then SELL, from <code>default_rng([11, 6, 0])</code>. The real in-or-out switch is kept, so the book holds the parent in exactly the rule's weeks and only the split of its sleeve moves.</p>
<div class="formula">allowed BUY-tuples  c({ex['k_buy']}, {ex['S_buy']}) = {int(ex['ways_buy']):,}   (count_table.json: {int(ex['ways_buy_table']):,})
allowed SELL-tuples c({ex['k_sell']}, {ex['S_sell']}) = {int(ex['ways_sell']):,}   (count_table.json: {int(ex['ways_sell_table']):,})</div>
<p>The first step of F3 draw 0, BUY-spell 1: m = {ex['k_buy']}, t = {ex['S_buy']}; u = {sg1['u']:.6f}; u × c({ex['k_buy']}, {ex['S_buy']}) = {sg1['u'] * sg1['total']:,.0f} falls in the weight of length {sg1['x']}, so the first BUY-spell is {sg1['x']} weeks.</p>
<figure class="card hv"><figcaption>Weights of the candidate first BUY-spell lengths for F3 draw 0 (m = {ex['k_buy']}, t = {ex['S_buy']}); the black line is the length drawn. Hover as above.</figcaption>{samplers['sampler|first_g'][0]}<div class="tip wrap" hidden></div></figure>
<p>All {len(stepsg)} steps of F3 draw 0, replayed from the seed: {steps_chip_g}.</p>
{table(step_rows_g, ["Spell", "Part", "Parts left m", "Weeks left t", "u", "c(m, t)", "Length drawn", "c(m−1, t−x)", "P(x)"])}
<p>F3 draw 0's BUY lengths are {", ".join(map(str, lens(Z['gold|N4.10-g'][0], 1)))} (the real: {", ".join(map(str, gbuy[b]))}) and its SELL lengths {", ".join(map(str, lens(Z['gold|N4.10-g'][0], 0)))} (the real: {", ".join(map(str, gsell[b]))}). It earns {pc(ex['d0']['F3']['cagr'], 2)} a year with a worst fall of {pc(ex['d0']['F3']['max_dd'], 2)} and makes {ex['d0']['F3']['sleeve_trades']} sleeve trades (the rule: {bk_(b)['sleeve_trades']}); F4 draw 0 earns {pc(ex['d0']['F4']['cagr'], 2)}, worst fall {pc(ex['d0']['F4']['max_dd'], 2)}, {ex['d0']['F4']['sleeve_trades']} sleeve trades.</p>
<p><b>10. The ranking.</b> Against F1 the rule's CAGR beat {ex['rank']['F1']['worse']:,} of {ex['rank']['F1']['draws']:,} draws, tied {ex['rank']['F1']['tied']}, and was beaten by {ex['rank']['F1']['better']}: percentile = ({ex['rank']['F1']['worse']} + 0.5 × {ex['rank']['F1']['tied']}) ÷ {ex['rank']['F1']['draws']:,} × 100 = <b>{ex['rank']['F1']['percentile']:.2f}</b>; p-value = (1 + {ex['rank']['F1']['better']} + {ex['rank']['F1']['tied']}) ÷ ({ex['rank']['F1']['draws']:,} + 1) = {ex['rank']['F1']['p']:.4f}. Against F2: beat {ex['rank']['F2']['worse']:,}, tied {ex['rank']['F2']['tied']}, beaten by {ex['rank']['F2']['better']}: percentile <b>{ex['rank']['F2']['percentile']:.2f}</b>, p = {ex['rank']['F2']['p']:.4f}. Against F3: beat {ex['rank']['F3']['worse']:,}, tied {ex['rank']['F3']['tied']}, beaten by {ex['rank']['F3']['better']}: percentile <b>{ex['rank']['F3']['percentile']:.2f}</b>, p = {ex['rank']['F3']['p']:.4f}. Against F4: percentile <b>{ex['rank']['F4']['percentile']:.2f}</b>, p = {ex['rank']['F4']['p']:.4f}.</p>

<h2 id="headline">Headline</h2>
<p>C1 and C2, the equity switch: CAGR and worst fall, after 20.8 bps, full window {start3} → {end_date}, against {ND:,} random in-or-out timings of each kind (F1 free lengths decides, F2 spell shuffle beside), the real MAUc1 signal in every draw. Holm p = Holm-adjusted over C1 to C4.</p>
{table(head_rows_io, ["Book", "Hold parent CAGR", "50/50-sleeve rule CAGR", "Rule CAGR", "F1 median", "Edge over F1 median", "C1: pct vs F1", "p", "Holm p", "F2 median", "pct vs F2", "p", "Hold parent worst fall", "Rule worst fall", "F1 median", "C2: pct vs F1", "p", "Holm p", "F2 median", "pct vs F2", "p"])}
<p>C3 and C4, the gold timing (the new claim): the same rule against {ND:,} random gold timings of each kind (F3 free lengths decides, F4 spell shuffle beside), the real in-or-out switch in every draw.</p>
{table(head_rows_g, ["Book", "Rule CAGR", "F3 median", "Edge over F3 median", "C3: pct vs F3", "p", "Holm p", "F4 median", "pct vs F4", "p", "Rule worst fall", "F3 median", "C4: pct vs F3", "p", "Holm p", "F4 median", "pct vs F4", "p"])}
<h3>Before and after cost, and the comparators ({start3} → {end_date})</h3>
{table(cost_rows, ["Book", "Strategy", "0 bps CAGR", "0 bps worst fall", "20.8 CAGR", "20.8 worst fall", "50 CAGR", "50 worst fall"])}
<p class="cap">The constant mixes hold the rule's average share ({100 * int(rule['SCMO_0003'].sum()) / weeks['SCMO_0003']:.1f}%) in the parent all the time and rebalance weekly, with a 50/50 non-stock share and with a MAUc1-timed one; the 100% sleeves are the other end; the 50/50-sleeve rule is T06's rule on this window, so the gap to the rule is the sleeve's effect. Published NAV (D17) CAGR: {", ".join(f"{b_[-4:]} {pc(bk_(b_)['pub_cagr'])}" for b_ in BOOKS)}.</p>

<h2 id="perbook">Per book</h2><div class="legend">{legend}</div>{curves_html}
<h2 id="nulls">Null distributions, each deciding null with the null beside it overlaid</h2>
<p>For each book the {ND:,} after-cost CAGRs and maximum drawdowns, on the same bins: first the in-or-out timing (blue = F1 free lengths, orange = F2 spell shuffle), then the gold timing (blue = F3, orange = F4). Black line = the rule, dashed = each null's median. The gold nulls are much narrower: they move only the sleeve's split.</p>{hists}
<h2 id="lengths">Spell lengths of the draws against the real series'</h2>
<p>Every spell of the {ND:,} draws, in weeks. The shuffles (F2, F4) can only reuse the real series' own lengths (orange spikes); F1 spreads in-or-out lengths over {LO} to {HI['in']} (in) and {LO} to {HI['out']} (out), F3 spreads gold lengths over {LO} to {HI['buy']} (BUY) and {LO} to {HI['sell']} (SELL), within the totals.</p>{lenhtml}
<h2 id="held">What each null holds and randomises</h2>
<p>The two tables below are copied from <code>T08.md</code> section 2 (frozen).</p>{null_tables}
{regime}
<h2 id="robust">Robustness (decides the finding's status, not the verdict)</h2>
<p><b>R1</b>, C1 to C4 percentiles at 0, 20.8 and 50 bps ({start3} → {end_date}) against the deciding null (F1 for C1 and C2, F3 for C3 and C4); pass mark 90 in at least 3 of 4:</p>
{table(rob1_dec, ["Book"] + [f"{cr} {c}" for cr, *_ in CRIT for c in ("0", "20.8", "50")])}
<p>Against the null beside it (F2 for C1 and C2, F4 for C3 and C4):</p>
{table(rob1_bes, ["Book"] + [f"{cr} {c}" for cr, *_ in CRIT for c in ("0", "20.8", "50")])}
<p class="cap">At ≥ 90 in 3 of 4 books, against the deciding null: C1 at 0 bps {sum(bk_(b_)['F1_pct_cagr_0'] >= 90 for b_ in BOOKS)}, at 20.8 {V['C1']}, at 50 {sum(bk_(b_)['F1_pct_cagr_50'] >= 90 for b_ in BOOKS)}; C2 at 0 {sum(bk_(b_)['F1_pct_dd_0'] >= 90 for b_ in BOOKS)}, at 20.8 {V['C2']}, at 50 {sum(bk_(b_)['F1_pct_dd_50'] >= 90 for b_ in BOOKS)}; C3 at 0 {sum(bk_(b_)['F3_pct_cagr_0'] >= 90 for b_ in BOOKS)}, at 20.8 {V['C3']}, at 50 {sum(bk_(b_)['F3_pct_cagr_50'] >= 90 for b_ in BOOKS)}; C4 at 0 {sum(bk_(b_)['F3_pct_dd_0'] >= 90 for b_ in BOOKS)}, at 20.8 {V['C4']}, at 50 {sum(bk_(b_)['F3_pct_dd_50'] >= 90 for b_ in BOOKS)} (of 4).</p>
<p><b>R2 and R3</b>, C1 and C3 percentiles at 20.8 bps. R2: the cash leg of the sleeve is the desk's LIQUIDCASE file, full window. R3: the live window {live_start} → {end_date} with its own spells, totals and nulls (same bounds); NOT REPORTABLE if fewer than 4 round trips or fewer than 4 gold spells with an OUT week.</p>
{table(rob2_rows, ["Book", "R2 C1 (F1)", "R2 C3 (F3)", "R2 rule CAGR", "R3 C1 (F1)", "R3 C3 (F3)", "R3 rule CAGR", "R3 reportability"])}
<p class="cap">At ≥ 90: R2 {V['R2_liq_C1']} of 4 for C1 and {V['R2_liq_C3']} for C3; R3 {V['R3_live_C1']} of 4 for C1 and {V['R3_live_C3']} for C3.</p>
<p><b>R4</b>, agreement of the paired nulls on this window (20.8 bps, {start3} → {end_date}; no pass mark): the rule's CAGR and drawdown percentile under each null and each null's spread of after-cost CAGR. In-or-out pair:</p>
{table(r4_io, ["Book", "F1 CAGR pct", "F1 DD pct", "median", "SD (pp)", "5th pct", "95th pct", "F2 CAGR pct", "F2 DD pct", "median", "SD (pp)", "5th pct", "95th pct"])}
<p>Gold pair:</p>
{table(r4_g, ["Book", "F3 CAGR pct", "F3 DD pct", "median", "SD (pp)", "5th pct", "95th pct", "F4 CAGR pct", "F4 DD pct", "median", "SD (pp)", "5th pct", "95th pct"])}
{t06_html}
<p><b>R5</b>, both timings random (F5: an F1 draw and an F3 draw of the same id; 20.8 bps; reported only):</p>
{table(r5_rows, ["Book", "Rule CAGR", "F5 median", "F5 SD (pp)", "CAGR pct", "p", "Drawdown pct", "p"])}
<p><b>R6</b>, paired contrast (descriptive, no pass mark): every F1 and F2 draw is also run with the sleeve fixed at 50/50. dCAGR = CAGR(timed) − CAGR(50/50) on the same states; dDD = worst fall (timed) − worst fall (50/50), positive = shallower with timing. The percentile ranks the rule's change among the draws' changes.</p>
{table(r6_rows, ["Book", "Rule dCAGR (pp)", "Rule dDD (pp)", "F1 median dCAGR", "pct", "share > 0", "F1 median dDD", "pct", "share > 0", "F2 median dCAGR", "pct", "share > 0", "F2 median dDD", "pct", "share > 0"])}
<p><b>R7</b>, raw-fill sensitivity (the rule re-run with the close in place of the raw OHLC4 after 2026-09-28):</p>{r7_html}
<h3>Sessions invested per draw (weeks are held exactly, sessions are not; F1 and F2, full window, 20.8 bps)</h3>
{table(ses_rows, ["Book", "Rule", "Sessions in window", "F1 min", "median", "max", "F2 min", "median", "max"])}
<h3>Sleeve trades per gold draw (F3 and F4; draws that flip while IN never trade)</h3>
{table(str_rows, ["Book", "Rule", "F3 min", "median", "max", "F4 min", "median", "max"])}
<h3>Power</h3><p>In-or-out nulls (round trips of the switch):</p>{table(mde_io, ["Book", "Round trips", "F1 SD CAGR (pp)", "MDE CAGR (pp)", "F1 SD worst fall (pp)", "MDE worst fall (pp)", "F2 SD CAGR (pp)", "MDE CAGR (pp)", "F2 SD worst fall (pp)", "MDE worst fall (pp)"])}
<p>Gold nulls (gold spells that contain an OUT week):</p>{table(mde_g, ["Book", "Gold spells with an OUT week", "F3 SD CAGR (pp)", "MDE CAGR (pp)", "F3 SD worst fall (pp)", "MDE worst fall (pp)", "F4 SD CAGR (pp)", "MDE CAGR (pp)", "F4 SD worst fall (pp)", "MDE worst fall (pp)"])}
<p class="cap">MDE = 2.8 × the SD of the draws (80% power, two-sided 5%), per null. The numbers did not exist when the pre-registration was written; its thresholds do not depend on them. T06's N4.10 null SD of CAGR was 5.4 to 6.9 pp.</p>

<h2 id="defs">Definitions</h2>
<ul><li><b>Percentile</b>: (draws worse + 0.5 × draws tied) ÷ draws × 100, ties equal within a relative 1e-12. <b>p-value</b>: (1 + draws at least as good) ÷ (draws + 1). <b>Holm p</b>: the Holm step-down adjustment of the four deciding p-values of a book.</li>
<li><b>CAGR</b>: NAV_end^(252 ÷ (sessions − 1)) − 1, daily NAV, after cost. <b>Worst fall</b> (maximum drawdown): the most negative NAV ÷ running peak − 1.</li>
<li><b>MAUc1</b>: the weekly supertrend (period W, multiplier 2) of MCX gold futures, recomputed with the production code (D24). <b>Gold signal g</b>: its SIGN, BUY or SELL, from the latest weekly row dated on or before the decision date. <b>Sleeve</b>: while the rule is OUT, GOLDBEES and cash, 80/20 when g is BUY and 20/80 when SELL, changed only when g changes.</li>
<li><b>F1</b> in-or-out N4.10 with the real gold signal (seed <code>default_rng([6, id])</code>); <b>F2</b> in-or-out N4.9 spell shuffle (<code>[3, id]</code>); <b>F3</b> gold N4.10-g with the real switch (<code>[11, 6, id]</code>); <b>F4</b> gold N4.9-g spell shuffle (<code>[11, 3, id]</code>); <b>F5</b> an F1 and an F3 draw together (robustness only).</li>
<li><b>N4.10 free-length random timing</b>: the same number of spells of each state and the same totals of weeks in each, every length an integer between the bounds, uniform over all allowed ordered tuples, drawn exactly by a dynamic programme, no rejection. <b>N4.9 spell shuffle</b>: the real series' spells of each state reordered among themselves. All nulls start in the real series' first state.</li>
<li><b>Weeks versus sessions</b>: the in-or-out nulls hold invested weeks exactly; a week has 3 to 5 sessions, so invested sessions differ by draw and are reported.</li>
<li><b>MDE</b>: 2.8 × the SD of the draws' CAGR (or maximum drawdown). <b>Live window</b>: {live_start} → {end_date}.</li></ul>
<p class="meta">Built by <code>tests/T08/report.py</code> from <code>evidence/{E(ev.name)}/</code>. Methods: <code>evidence/METHODS.md</code>. Checked by <code>check_page.py</code>.</p>
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
