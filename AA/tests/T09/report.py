"""Build report.html for T09 from shipped evidence only (AGENT.md R10). Forked from T08's page; the parent's stocks become a three-index proxy portfolio, the criteria become
A1, A2, C1 to C4, and the page adds the entry and the quarterly reset to the worked example.

    python tests/T09/report.py [--run headline]              writes tests/T09/evidence/report.html
    python tests/T09/report.py --evidence DIR [--out DIR]    another evidence directory (e.g. a synthetic one); the page and
                                                             analysis.log are then looked up and written in --out (default DIR)
    options: --books SCMO_0003   for an evidence directory that holds fewer than the four books

Every number on the page is computed here from evidence/<run>/ (decisions.csv, gold_signal.csv, stats.csv, draws.csv, daily_nav.csv, trades.csv, sleeve_trades.csv,
quarterly_resets.csv, proxy_units.csv, draw_states.npz, real_states.npz, draw_curves_20.8.npz, count_table.json, inputs.csv, audit.json, verify_t09.json) and, for the gate
verdicts, the 'Gates:' line of analysis.log. The same numbers are written into the page's embedded JSON blocks (page-data, regime-data, lines-data, bars-data) so check_page.py
can recompute them independently. Imports nothing from the engine. Every chart is hoverable (AGENT.md R10): the hover reads the same arrays that draw the chart, and every
tooltip and caption names the start and end date of what it shows. The two held/randomised tables are copied from T09.md section 2 (nothing typed here). No performance figure
is typed in this file.
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
KINDS = ["strategy", "strategy_fixed50", "hold_proxy", "constant_mix", "constant_mix_timed", "sleeve_only", "sleeve_only_timed", "index_Nifty100", "index_MC100", "index_SC100"]
COL = {"strategy": "#2a6fdb", "strategy_fixed50": "#79a8f0", "hold_proxy": "#8a8f98", "constant_mix": "#c9811a", "constant_mix_timed": "#e8b45c", "sleeve_only": "#2f9e6e",
       "sleeve_only_timed": "#75cfa6", "index_Nifty100": "#b04a9b", "index_MC100": "#d98ac9", "index_SC100": "#7a3f6f"}
LAB = {"strategy": "Rule, MAUc1-timed sleeve", "strategy_fixed50": "Rule, 50/50 sleeve (Part A)", "hold_proxy": "Hold the proxy portfolio", "constant_mix": "Constant mix, 50/50 non-proxy share",
       "constant_mix_timed": "Constant mix, MAUc1-timed non-proxy share", "sleeve_only": "50/50 GOLDBEES + cash", "sleeve_only_timed": "MAUc1-timed GOLDBEES + cash",
       "index_Nifty100": "Nifty 100 alone", "index_MC100": "Midcap 100 alone", "index_SC100": "Smallcap 100 alone"}
# criterion, statistic, deciding null, null beside it, sleeve mode of the null's draws, the rule's stats.csv kind
CRIT = [("A1", "cagr", "F1", "F2", "fixed50", "strategy_fixed50"), ("A2", "max_dd", "F1", "F2", "fixed50", "strategy_fixed50"), ("C1", "cagr", "F1", "F2", "timed", "strategy"),
        ("C2", "max_dd", "F1", "F2", "timed", "strategy"), ("C3", "cagr", "F3", "F4", "timed", "strategy"), ("C4", "max_dd", "F3", "F4", "timed", "strategy")]
FAMS = ("F1", "F2", "F3", "F4")
R7_KINDS = ["strategy_r7a_proxy_fill_at_close", "strategy_r7b_gold_weight_50_before_2014-07-01"]
INDEX_NAMES = ("Nifty100", "MC100", "SC100")
UC = ["units_Nifty100", "units_MC100", "units_SC100", "units_GOLDBEES", "units_LBES"]
GB_FIRST = "2014-07-01"


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
    """The first markdown table after each of the two 'Null table' lines of T09.md section 2: (header, rows) of raw cell strings."""
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
    """Growth-of-1 lines (log) on top; below, one strip per timing (filled = holds the proxy), a strip of where they differ, a MAUc1 strip (filled = BUY)
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
    out = [f'<svg id="regime-svg" viewBox="0 0 {w} {h}" role="img" aria-label="Growth of 1: rule versus {E(draw_label)}, with the weeks each held the proxy portfolio, the MAUc1 signal and the sleeve weights" class="chart">']
    for v, s, e, tip in pair_runs:
        if v in (1, 2):
            fill = "var(--fg)" if v == 1 else COL["strategy"]
            out.append(f'<rect x="{x(s):.1f}" y="{T}" width="{max(x(e) - x(s), 0.6):.1f}" height="{bot - T}" fill="{fill}" opacity="{0.10 if v == 1 else 0.14}"/>')
    for t in (1, 2, 4, 8, 16):
        if math.exp(lo) <= t <= math.exp(hi):
            out.append(f'<line x1="{L}" x2="{w - R}" y1="{y(t):.1f}" y2="{y(t):.1f}" class="grid"/><text x="{L - 4}" y="{y(t) + 3:.1f}" text-anchor="end" class="ax">{t:g}×</text>')
    idx = np.append(np.arange(0, N, 3), N - 1)
    styles = {"hold_proxy": (COL["hold_proxy"], 1.2), "draw": ("var(--fg)", 1.7), "strategy": (COL["strategy"], 2.4)}
    for k in ("hold_proxy", "draw", "strategy"):
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
               + "".join(f'<circle id="hv-c{n}" r="4" fill="{c}" stroke="var(--card)" stroke-width="2"/>' for n, c in enumerate((COL["strategy"], "var(--fg)", COL["hold_proxy"])))
               + f'<g id="hv-yc"><rect x="0" y="-8" width="{L - 3}" height="16" rx="3" fill="var(--fg)"/><text x="{L - 7}" y="3.5" text-anchor="end" font-size="10" fill="var(--bg)" id="hv-yt"></text></g>'
               f'<g id="hv-xc"><rect y="{h - 19}" width="70" height="16" rx="3" fill="var(--fg)" id="hv-xr"/><text y="{h - 7.5}" text-anchor="middle" font-size="10" fill="var(--bg)" id="hv-xt"></text></g></g>')
    out.append(f'<rect id="regime-ov" x="{L}" y="{T}" width="{w - L - R}" height="{bot - T}" fill="transparent" style="cursor:crosshair;touch-action:none"/>')
    out.append("</svg>")
    return "".join(out), {"w": w, "h": h, "L": L, "R": R, "T": T, "ph": ph, "lo": lo, "hi": hi, "N": N}


HOVER_JS = """(function(){
var d=JSON.parse(document.getElementById('regime-data').textContent),svg=document.getElementById('regime-svg'),ov=document.getElementById('regime-ov'),
tip=document.getElementById('regime-tip'),fig=tip.parentNode,g=document.getElementById('regime-hv'),$=function(i){return document.getElementById(i)};
var cols=['#2a6fdb','var(--fg)','#8a8f98'],key=['rule','draw','proxy'],lab=['Rule (MAUc1-timed sleeve)',d.draw_label,'Hold the proxy'];
function Y(v){return d.T+d.ph*(1-(Math.log(v)-d.lo)/(d.hi-d.lo))}
function X(i){return d.L+(d.w-d.L-d.R)*i/(d.N-1)}
function fx(v){return v.toFixed(2)+'\\u00d7'}
function sl(i,s){return s?'holds the proxy':'sleeve '+Math.round(100*d.gw[i])+'% GOLDBEES / '+Math.round(100*(1-d.gw[i]))+'% cash'}
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



def amendments_block(doc):
    """The 'Amendments before the run' block of T09.md (outside the frozen sections), as a list of (kind, text)."""
    txt = doc.replace("\r\n", "\n")
    i = txt.index("### Amendments before the run")
    j = txt.index("\n## 5. Findings", i)
    items = []
    for l in txt[i:j].split("\n")[1:]:
        l = l.strip()
        if not l:
            continue
        items.append(l)
    return items


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="headline")
    ap.add_argument("--evidence", default=None)
    ap.add_argument("--out", default=None, help="directory of report.html and analysis.log")
    ap.add_argument("--t06", default=str(AA / "tests" / "T06" / "evidence" / "headline"))
    ap.add_argument("--t08", default=str(AA / "tests" / "T08" / "evidence" / "headline"))
    ap.add_argument("--doc", default=str(HERE / "T09.md"))
    ap.add_argument("--books", default=None, help="comma list; for evidence directories that hold fewer than the four books")
    a = ap.parse_args()
    if a.books:
        BOOKS[:] = a.books.split(",")
    B0 = BOOKS[0]
    B7 = "SCMO_0007" if "SCMO_0007" in BOOKS else BOOKS[-1]
    ev = Path(a.evidence) if a.evidence else HERE / "evidence" / a.run
    if a.out:
        logdir = outdir = Path(a.out)
    elif a.evidence:
        logdir = outdir = ev
    else:
        logdir, outdir = HERE, ev.parent
    t06, t08 = Path(a.t06), Path(a.t08)
    dec = pd.read_csv(ev / "decisions.csv")
    st = pd.read_csv(ev / "stats.csv")
    dr = pd.read_csv(ev / "draws.csv")
    tr = pd.read_csv(ev / "trades.csv")
    sl = pd.read_csv(ev / "sleeve_trades.csv")
    qr = pd.read_csv(ev / "quarterly_resets.csv")
    pu = pd.read_csv(ev / "proxy_units.csv")
    nav = pd.read_csv(ev / "daily_nav.csv", parse_dates=["date"])
    au = json.loads((ev / "audit.json").read_text(encoding="utf-8"))
    ct = json.loads((ev / "count_table.json").read_text(encoding="utf-8"))
    ver = json.loads((ev / "verify_t09.json").read_text(encoding="utf-8")) if (ev / "verify_t09.json").exists() else None
    _z = np.load(ev / "draw_states.npz")
    states = {k_: _z[k_] for k_ in _z.files}  # decompress once
    _r = np.load(ev / "real_states.npz")
    realz = {k_: _r[k_] for k_ in _r.files}
    curves = np.load(ev / "draw_curves_20.8.npz")
    inp = pd.read_csv(ev / "inputs.csv", dtype=str, keep_default_na=False)
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
    amend = amendments_block(doc)
    LIQ = "liq" if "liq" in set(st.cash) else "liquidcase"

    S = lambda b, kind="strategy", cost=PRIMARY, win="full", cash="lbes": st[(st.book == b) & (st.window == win) & (st.cash == cash) & (st.cost_bps == cost) & (st.kind == kind)].iloc[0]
    D = lambda b, fam, cost=PRIMARY, win="full", cash="lbes", mode="timed": dr[(dr.book == b) & (dr.window == win) & (dr.cash == cash) & (dr.cost_bps == cost) & (dr.family == fam) & (dr.sleeve_mode == mode)].sort_values("draw_id")
    ND = int(len(D(B0, "F1")))
    rule = {b: dec[dec.book == b].sort_values("j").state.values.astype(int) for b in BOOKS}
    gold = {b: dec[dec.book == b].sort_values("j").g.values.astype(int) for b in BOOKS}
    gwk = {b: dec[dec.book == b].sort_values("j").gw.values.astype(float) for b in BOOKS}
    weeks = {b: len(rule[b]) for b in BOOKS}
    rin = {b: lens(rule[b], 1) for b in BOOKS}
    rout = {b: lens(rule[b], 0) for b in BOOKS}
    gbuy = {b: lens(gold[b], 1) for b in BOOKS}
    gsell = {b: lens(gold[b], 0) for b in BOOKS}
    ctab = {}
    for key, ent in (ct.get("tables") or {}).items():
        p_ = key.split("|")
        if len(p_) == 4:
            ctab[tuple(p_)] = {"k": int(ent.get("spells_k", ent.get("k"))), "S": int(ent.get("weeks_S", ent.get("S"))), "lo": int(ent["lo"]), "hi": int(ent["hi"]), "n_ways": int(ent["n_ways"])}
    BND = {}   # per book, window, kind: {1: (lo, hi), 0: (lo, hi)}, from the real series themselves
    for b in BOOKS:
        for win in ("full", "r3"):
            for kind in ("io", "gold"):
                r_ = realz[f"{b}|{win}|{kind}"].astype(int)
                BND[(b, win, kind)] = {s_: (min(2, min(lens(r_, s_))), max(lens(r_, s_))) for s_ in (1, 0)}
    cal = {b: nav[(nav.book == b) & (nav.cost_bps == PRIMARY) & (nav.run == "strategy")].sort_values("date").date.reset_index(drop=True) for b in BOOKS}
    wk0s, wsess = {}, {}
    for b in BOOKS:
        d_ = dec[dec.book == b].sort_values("j").reset_index(drop=True)
        n_ = len(cal[b])
        w0 = [0] + [n_ - 1 if pd.isna(t) else int(np.searchsorted(cal[b].values, np.datetime64(pd.Timestamp(t)))) for t in d_.trade_date.iloc[1:]]
        wk0s[b], wsess[b] = np.array(w0), np.array(w0[1:] + [n_ - 1]) - np.array(w0)
    rule_sess = {b: int(rule[b] @ wsess[b]) for b in BOOKS}
    end_date = str(cal[B0].iloc[-1].date())
    start3 = str(cal[B0].iloc[0].date())
    r3_start = (au["books"][B0].get("r3_window") or {}).get("t0", "2012-01-02")
    W = {b: au["books"][b]["weights"] for b in BOOKS}
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
    r3_io = {b: realz[f"{b}|r3|io"].astype(int) for b in BOOKS}
    r3_g = {b: realz[f"{b}|r3|gold"].astype(int) for b in BOOKS}
    feas = {w: all(e["k"] * e["lo"] <= e["S"] <= e["hi"] * e["k"] for (b, w_, k_, s_), e in ctab.items() if w_ == w) for w in ("full", "r3")}
    nr_io = [b for b in BOOKS if rt_of(rule[b]) < 4 or not feas["full"]]
    nr_gold = [b for b in BOOKS if gold_with_out(gold[b], rule[b]) < 4]
    nr_io_r3 = [b for b in BOOKS if rt_of(r3_io[b]) < 4 or not feas["r3"]]
    nr_gold_r3 = [b for b in BOOKS if gold_with_out(r3_g[b], r3_io[b]) < 4]
    notrep = lambda cr, r3=False: (nr_io_r3 if r3 else nr_io) + ((nr_gold_r3 if r3 else nr_gold) if cr in ("C3", "C4") else [])

    # ── page data ─────────────────────────────────────────────────────────────
    TAGS = {"F1": ("F1", "timed", "strategy"), "F2": ("F2", "timed", "strategy"), "F3": ("F3", "timed", "strategy"), "F4": ("F4", "timed", "strategy"), "F5": ("F5", "timed", "strategy"),
            "F1f": ("F1", "fixed50", "strategy_fixed50"), "F2f": ("F2", "fixed50", "strategy_fixed50")}
    data = {"run": ev.name, "prereg_sha256": sha, "draws": ND, "as_of_file": asof_file, "as_of_inputs": asof_inputs, "end": end_date, "start": start3, "r3_start": r3_start,
            "weeks": {b: weeks[b] for b in BOOKS}, "weights": W, "books": {}, "gates": gate_line,
            "not_reportable": {"io": nr_io, "gold": nr_gold, "io_r3": nr_io_r3, "gold_r3": nr_gold_r3}}
    for b in BOOKS:
        bb = {}
        for kind in KINDS + R7_KINDS:
            if ((st.book == b) & (st.kind == kind) & (st.window == "full") & (st.cash == "lbes") & (st.cost_bps == PRIMARY)).any():
                bb[f"{kind}_cagr"], bb[f"{kind}_dd"], bb[f"{kind}_end"] = float(S(b, kind).cagr), float(S(b, kind).max_dd), float(S(b, kind).end_nav)
                for c in COSTS:
                    if ((st.book == b) & (st.kind == kind) & (st.window == "full") & (st.cash == "lbes") & (st.cost_bps == c)).any():
                        bb[f"{kind}_cagr_{c:g}"], bb[f"{kind}_dd_{c:g}"] = float(S(b, kind, c).cagr), float(S(b, kind, c).max_dd)
        s0, sf0 = S(b), S(b, "strategy_fixed50")
        bb.update({"trades": int(s0.trades), "cost_paid": float(s0.cost_paid), "sleeve_trades": int(s0.sleeve_trades), "quarterly_resets": int(s0.quarterly_resets), "fixed50_trades": int(sf0.trades),
                   "rule_sessions": rule_sess[b], "sessions_total": len(cal[b]) - 1, "rule_in": rin[b], "rule_out": rout[b], "rule_buy": gbuy[b], "rule_sell": gsell[b],
                   "round_trips": rt_of(rule[b]), "gold_spells_with_out": gold_with_out(gold[b], rule[b]), "r3_round_trips": rt_of(r3_io[b]), "r3_gold_spells_with_out": gold_with_out(r3_g[b], r3_io[b])})
        for tag, (fam, mode, rk) in TAGS.items():
            s_ = S(b, rk)
            n = D(b, fam, mode=mode)
            rc, rd = rank(s_.cagr, n.cagr.values), rank(s_.max_dd, n.max_dd.values)
            q = np.percentile(n.cagr.values, [5, 95])
            bb.update({f"{tag}_median_cagr": float(n.cagr.median()), f"{tag}_median_dd": float(n.max_dd.median()), f"{tag}_pct_cagr": rc["percentile"], f"{tag}_p_cagr": rc["p"],
                       f"{tag}_pct_dd": rd["percentile"], f"{tag}_p_dd": rd["p"], f"{tag}_worse": rc["worse"], f"{tag}_tied": rc["tied"], f"{tag}_better": rc["better"],
                       f"{tag}_sd_cagr": float(n.cagr.std()), f"{tag}_sd_dd": float(n.max_dd.std()), f"{tag}_mde_cagr_pp": float(280 * n.cagr.std()), f"{tag}_mde_dd_pp": float(280 * n.max_dd.std()),
                       f"{tag}_p5_cagr": float(q[0]), f"{tag}_p95_cagr": float(q[1]), f"{tag}_sess_min": int(n.sessions_invested.min()), f"{tag}_sess_median": float(n.sessions_invested.median()),
                       f"{tag}_sess_max": int(n.sessions_invested.max()), f"{tag}_strades_min": int(n.sleeve_trades.min()), f"{tag}_strades_median": float(n.sleeve_trades.median()),
                       f"{tag}_strades_max": int(n.sleeve_trades.max())})
            if tag != "F5":
                for c in (0.0, 50.0):
                    sc_, nc_ = S(b, rk, c), D(b, fam, cost=c, mode=mode)
                    bb[f"{tag}_pct_cagr_{c:g}"] = rank(sc_.cagr, nc_.cagr.values)["percentile"]
                    bb[f"{tag}_pct_dd_{c:g}"] = rank(sc_.max_dd, nc_.max_dd.values)["percentile"]
        for tag in ("F1f", "F1", "F3"):
            fam, mode, rk = TAGS[tag]
            bb[f"{tag}_r3_pct"] = rank(S(b, rk, win="r3").cagr, D(b, fam, win="r3", mode=mode).cagr.values)["percentile"]
            bb[f"{tag}_liq_pct"] = rank(S(b, rk, cash=LIQ).cagr, D(b, fam, cash=LIQ, mode=mode).cagr.values)["percentile"]
        bb.update({"r3_cagr": float(S(b, win="r3").cagr), "r3_fixed50_cagr": float(S(b, "strategy_fixed50", win="r3").cagr), "liq_cagr": float(S(b, cash=LIQ).cagr), "liq_fixed50_cagr": float(S(b, "strategy_fixed50", cash=LIQ).cagr)})
        bb.update({"r6_rule_dcagr": float(s0.cagr - sf0.cagr), "r6_rule_ddd": float(s0.max_dd - sf0.max_dd)})
        for fam in ("F1", "F2"):
            m = D(b, fam, mode="timed").merge(D(b, fam, mode="fixed50"), on="draw_id", suffixes=("_t", "_f"))
            dc, ddn = (m.cagr_t - m.cagr_f).values, (m.max_dd_t - m.max_dd_f).values
            bb.update({f"r6_{fam}_median_dcagr": float(np.median(dc)), f"r6_{fam}_pct_dcagr": rank(s0.cagr - sf0.cagr, dc)["percentile"], f"r6_{fam}_share_dcagr": float((dc > 0).mean()),
                       f"r6_{fam}_median_ddd": float(np.median(ddn)), f"r6_{fam}_pct_ddd": rank(s0.max_dd - sf0.max_dd, ddn)["percentile"], f"r6_{fam}_share_ddd": float((ddn > 0).mean())})
        hp_ = holm([bb[f"{t}_p_{k_}"] for t, k_ in (("F1f", "cagr"), ("F1f", "dd"), ("F1", "cagr"), ("F1", "dd"), ("F3", "cagr"), ("F3", "dd"))])
        for cr, h_ in zip(("A1", "A2", "C1", "C2", "C3", "C4"), hp_):
            bb[f"holm_{cr}"] = h_
        data["books"][b] = bb
    TAG_OF = {"A1": ("F1f", "F2f", "cagr"), "A2": ("F1f", "F2f", "dd"), "C1": ("F1", "F2", "cagr"), "C2": ("F1", "F2", "dd"), "C3": ("F3", "F4", "cagr"), "C4": ("F3", "F4", "dd")}

    def cnt(tag, stat, cr, r3=False, key=None):
        k_ = key or f"{tag}_pct_{stat}"
        return int(sum(bool(data["books"][b][k_] >= 90) and b not in notrep(cr, r3) for b in BOOKS))
    V = {}
    for cr, (d_, b_, stat) in TAG_OF.items():
        V[cr], V[cr + "_beside"] = cnt(d_, stat, cr), cnt(b_, stat, cr)
    for tag, cr in (("F1f", "A1"), ("F1", "C1"), ("F3", "C3")):
        V[f"R3_{cr}"] = cnt(tag, "cagr", cr, r3=True, key=f"{tag}_r3_pct")
        V[f"R2_{cr}"] = cnt(tag, "cagr", cr, key=f"{tag}_liq_pct")
    data["verdict"] = V
    A_ok, C_ok, G_ok = V["A1"] >= 3 and V["A2"] >= 3, V["C1"] >= 3 and V["C2"] >= 3, V["C3"] >= 3 and V["C4"] >= 3
    gates_ok = bool(gate_line) and all(v == "PASS" for v in gate_line.values()) and len(gate_line) == 6

    # historical reference (only if the evidence files exist)
    ref = {"T06": {}, "T08": {}}
    if (t06 / "draws.csv").exists() and (t06 / "stats.csv").exists():
        s6 = pd.read_csv(t06 / "stats.csv")
        d6 = pd.read_csv(t06 / "draws.csv", usecols=["book", "window", "cash", "cost_bps", "draw_type", "cagr", "max_dd"])
        for b in BOOKS:
            sr = s6[(s6.book == b) & (s6.window == "full") & (s6.cash == "lbes") & (s6.cost_bps == PRIMARY) & (s6.kind == "strategy")]
            if sr.empty:
                continue
            sr = sr.iloc[0]
            e_ = {"cagr": float(sr.cagr)}
            for typ, nm in (("N4.10", "n10"), ("N4.9", "n9")):
                nd_ = d6[(d6.book == b) & (d6.window == "full") & (d6.cash == "lbes") & (d6.cost_bps == PRIMARY) & (d6.draw_type == typ)]
                e_.update({f"{nm}_pct_cagr": rank(sr.cagr, nd_.cagr.values)["percentile"], f"{nm}_pct_dd": rank(sr.max_dd, nd_.max_dd.values)["percentile"]})
            ref["T06"][b] = e_
    if (t08 / "draws.csv").exists() and (t08 / "stats.csv").exists():
        s8 = pd.read_csv(t08 / "stats.csv")
        d8 = pd.read_csv(t08 / "draws.csv", usecols=["book", "window", "cash", "cost_bps", "family", "sleeve_mode", "cagr", "max_dd"])
        for b in BOOKS:
            sr = s8[(s8.book == b) & (s8.window == "full") & (s8.cash == "lbes") & (s8.cost_bps == PRIMARY) & (s8.kind == "strategy")]
            if sr.empty:
                continue
            sr = sr.iloc[0]
            e_ = {"cagr": float(sr.cagr)}
            for fam in FAMS:
                nd_ = d8[(d8.book == b) & (d8.window == "full") & (d8.cash == "lbes") & (d8.cost_bps == PRIMARY) & (d8.family == fam) & (d8.sleeve_mode == "timed")]
                if len(nd_):
                    e_.update({f"{fam}_pct_cagr": rank(sr.cagr, nd_.cagr.values)["percentile"], f"{fam}_pct_dd": rank(sr.max_dd, nd_.max_dd.values)["percentile"]})
            ref["T08"][b] = e_
    data["historical_reference"] = ref

    # ── worked example: first book ────────────────────────────────────────────
    b = B0
    d = dec[dec.book == b].sort_values("j").reset_index(drop=True)
    slq = sl[(sl.book == b) & (sl.cost_bps == PRIMARY)].reset_index(drop=True)
    trq = tr[(tr.book == b) & (tr.run == "strategy") & (tr.cost_bps == PRIMARY)].sort_values("idx").reset_index(drop=True)
    puq = pu[(pu.book == b) & (pu.cost_bps == PRIMARY) & (pu.run == "strategy")].sort_values("idx").reset_index(drop=True)
    qrq = qr[(qr.book == b) & (qr.cost_bps == PRIMARY)].reset_index(drop=True)
    wb = [float(W[b][n_]) for n_ in INDEX_NAMES]

    def urow(date, which):
        i = int(puq.index[puq.date == date][0]) + which
        return None if i < 0 else {c: float(puq.loc[i, c]) for c in UC} | {"date": str(puq.loc[i, "date"])}
    exit_row = slq[slq.kind == "switch_out"].iloc[0]
    flip_row = next(r_ for r_ in slq[slq.kind == "sleeve_rebalance"].itertuples() if urow(r_.date, -1) is not None)
    flip_row = slq[(slq.kind == "sleeve_rebalance") & (slq.date == flip_row.date)].iloc[0]
    in_tr = next(r_ for r_ in trq[trq.kind == "switch_in"].itertuples() if urow(r_.date, -1) is not None)
    rst = qrq.iloc[0]
    nv = nav[(nav.book == b) & (nav.cost_bps == PRIMARY) & (nav.run == "strategy")].sort_values("date").reset_index(drop=True)
    k = int(nv.index[nv.date == pd.Timestamp(exit_row.date)][0])
    s0, sf0 = S(b), S(b, "strategy_fixed50")
    Z = {k_: states[f"{b}|full|{k_}"] for k_ in ("io|N4.9", "io|N4.10", "gold|N4.9-g", "gold|N4.10-g")}
    bi, bg = BND[(b, "full", "io")], BND[(b, "full", "gold")]
    ks = {"in": ctab[(b, "full", "io", "in")]["k"], "out": ctab[(b, "full", "io", "out")]["k"]}
    SS = {"in": ctab[(b, "full", "io", "in")]["S"], "out": ctab[(b, "full", "io", "out")]["S"]}
    bnd = {"in": bi[1], "out": bi[0]}
    steps, rp = replay([12, 6, 0], ks, SS, bnd, ("in", "out"))
    replay_ok = rp["in"] == lens(Z["io|N4.10"][0], 1) and rp["out"] == lens(Z["io|N4.10"][0], 0)
    ksg = {"buy": ctab[(b, "full", "gold", "buy")]["k"], "sell": ctab[(b, "full", "gold", "sell")]["k"]}
    SSg = {"buy": ctab[(b, "full", "gold", "buy")]["S"], "sell": ctab[(b, "full", "gold", "sell")]["S"]}
    bndg = {"buy": bg[1], "sell": bg[0]}
    stepsg, rpg = replay([12, 11, 6, 0], ksg, SSg, bndg, ("buy", "sell"))
    replay_ok_g = rpg["buy"] == lens(Z["gold|N4.10-g"][0], 1) and rpg["sell"] == lens(Z["gold|N4.10-g"][0], 0)
    own_count = {nm: int(dp_table(ks[nm], SS[nm], *bnd[nm])[ks[nm]][SS[nm]]) for nm in ("in", "out")}
    own_count_g = {nm: int(dp_table(ksg[nm], SSg[nm], *bndg[nm])[ksg[nm]][SSg[nm]]) for nm in ("buy", "sell")}
    x0, rks = {}, {}
    for tag, (fam, mode, rk) in TAGS.items():
        if tag == "F5":
            continue
        r_ = D(b, fam, mode=mode)
        x0[tag] = r_[r_.draw_id == 0].iloc[0]
        rks[tag] = rank(S(b, rk).cagr, r_.cagr.values)
    jx, jf, jn = (int(d.index[d.trade_date == x_][0]) for x_ in (exit_row.date, flip_row.date, in_tr.date))
    ttx, ttf, ttn = (trq[trq.date == x_].iloc[0] for x_ in (exit_row.date, flip_row.date, in_tr.date))
    ttr = trq[trq.date == rst.date].iloc[0]
    data["example"] = {
        "book": b,
        "exit": {"decision_week": jx, "decision_date": str(d.decision_date[jx]), "trade_date": str(d.trade_date[jx]), "g": int(d.g[jx]), "gw": float(d.gw[jx]), "sign_MAUc1": str(d.sign_MAUc1[jx]), "V": float(ttx.V),
                 "traded": float(exit_row.traded), "cost": float(exit_row.cost), "gold_after": float(exit_row.gold_value_after), "cash_after": float(exit_row.cash_value_after), "nav_after": float(ttx.nav_close_after),
                 "units_before": urow(exit_row.date, -1), "units_after": urow(exit_row.date, 0), "proxy_fill": bool(exit_row.gold_fill_proxy_period)},
        "flip": {"decision_week": jf, "decision_date": str(d.decision_date[jf]), "trade_date": str(d.trade_date[jf]), "g_before": int(d.g[jf - 1]), "g_after": int(d.g[jf]), "gw_after": float(d.gw[jf]), "V": float(ttf.V),
                 "traded": float(flip_row.traded), "cost": float(flip_row.cost), "gold_before": float(flip_row.gold_value_before), "cash_before": float(flip_row.cash_value_before),
                 "gold_after": float(flip_row.gold_value_after), "cash_after": float(flip_row.cash_value_after), "nav_after": float(ttf.nav_close_after), "units_before": urow(flip_row.date, -1), "units_after": urow(flip_row.date, 0),
                 "proxy_fill": bool(flip_row.gold_fill_proxy_period)},
        "entry": {"decision_week": jn, "decision_date": str(d.decision_date[jn]), "trade_date": str(d.trade_date[jn]), "V": float(ttn.V), "traded": float(ttn.traded), "cost": float(ttn.cost), "nav_after": float(ttn.nav_close_after),
                  "units_before": urow(in_tr.date, -1), "units_after": urow(in_tr.date, 0), "sign": [str(d.sign_Nifty100[jn]), str(d.sign_MC100[jn]), str(d.sign_SC100[jn])], "sign_MAUc1": str(d.sign_MAUc1[jn])},
        "reset": {"date": str(rst.date), "V": float(rst.V), "traded": float(rst.traded), "cost": float(rst.cost), "nav_after": float(ttr.nav_close_after), "units_before": urow(rst.date, -1), "units_after": urow(rst.date, 0),
                  "before": [float(rst[f"value_before_{n_}"]) for n_ in INDEX_NAMES], "after": [float(rst[f"value_after_{n_}"]) for n_ in INDEX_NAMES]},
        "sessions": int(s0.sessions), "end_nav": float(s0.end_nav), "cagr": float(s0.cagr), "max_dd": float(s0.max_dd),
        "k_in": ks["in"], "S_in": SS["in"], "lo_in": bnd["in"][0], "hi_in": bnd["in"][1], "k_out": ks["out"], "S_out": SS["out"], "lo_out": bnd["out"][0], "hi_out": bnd["out"][1],
        "ways_in": str(own_count["in"]), "ways_out": str(own_count["out"]), "ways_in_table": str(ctab[(b, "full", "io", "in")]["n_ways"]), "ways_out_table": str(ctab[(b, "full", "io", "out")]["n_ways"]),
        "replay_in": rp["in"], "replay_out": rp["out"], "replay_ok": bool(replay_ok), "steps": steps,
        "k_buy": ksg["buy"], "S_buy": SSg["buy"], "lo_buy": bndg["buy"][0], "hi_buy": bndg["buy"][1], "k_sell": ksg["sell"], "S_sell": SSg["sell"], "lo_sell": bndg["sell"][0], "hi_sell": bndg["sell"][1],
        "ways_buy": str(own_count_g["buy"]), "ways_sell": str(own_count_g["sell"]), "ways_buy_table": str(ctab[(b, "full", "gold", "buy")]["n_ways"]), "ways_sell_table": str(ctab[(b, "full", "gold", "sell")]["n_ways"]),
        "replay_buy": rpg["buy"], "replay_sell": rpg["sell"], "replay_ok_g": bool(replay_ok_g), "steps_g": stepsg,
        "d0": {t_: {"cagr": float(x0[t_].cagr), "max_dd": float(x0[t_].max_dd), "sessions": int(x0[t_].sessions_invested), "sleeve_trades": int(x0[t_].sleeve_trades)} for t_ in x0},
        "rank": {t_: rks[t_] for t_ in rks}}

    # ── tables ────────────────────────────────────────────────────────────────
    chip = lambda ok: ('<span class="chip ok">PASS</span>' if ok else '<span class="chip bad">FAIL</span>')
    bk_ = lambda b: data["books"][b]
    answer_rows = [[E(b)] + [x_ for cr in ("A1", "A2", "C1", "C2", "C3", "C4") for x_ in (f"{bk_(b)[TAG_OF[cr][0] + '_pct_' + TAG_OF[cr][2]]:.1f}", f"{bk_(b)['holm_' + cr]:.3f}")] for b in BOOKS]
    head_a, head_c, head_g = [], [], []
    for b in BOOKS:
        x = bk_(b)
        for rows_, tags, rk, hold in ((head_a, ("F1f", "F2f"), "strategy_fixed50", True), (head_c, ("F1", "F2"), "strategy", True)):
            t1, t2 = tags
            r_ = [E(b), pc(x["hold_proxy_cagr"]), pc(x[f"{rk}_cagr"]), pc(x[f"{t1}_median_cagr"]), f"{100 * (x[f'{rk}_cagr'] - x[f'{t1}_median_cagr']):+.1f} pp", f"<b>{x[f'{t1}_pct_cagr']:.1f}</b>", f"{x[f'{t1}_p_cagr']:.3f}",
                  f"{x['holm_' + ('A1' if t1 == 'F1f' else 'C1')]:.3f}", pc(x[f"{t2}_median_cagr"]), f"<b>{x[f'{t2}_pct_cagr']:.1f}</b>", f"{x[f'{t2}_p_cagr']:.3f}",
                  pc(x["hold_proxy_dd"]), pc(x[f"{rk}_dd"]), pc(x[f"{t1}_median_dd"]), f"<b>{x[f'{t1}_pct_dd']:.1f}</b>", f"{x[f'{t1}_p_dd']:.3f}", f"{x['holm_' + ('A2' if t1 == 'F1f' else 'C2')]:.3f}",
                  pc(x[f"{t2}_median_dd"]), f"<b>{x[f'{t2}_pct_dd']:.1f}</b>", f"{x[f'{t2}_p_dd']:.3f}"]
            rows_.append(r_)
        head_g.append([E(b), pc(x["strategy_cagr"]), pc(x["F3_median_cagr"]), f"{100 * (x['strategy_cagr'] - x['F3_median_cagr']):+.1f} pp", f"<b>{x['F3_pct_cagr']:.1f}</b>", f"{x['F3_p_cagr']:.3f}", f"{x['holm_C3']:.3f}",
                       pc(x["F4_median_cagr"]), f"<b>{x['F4_pct_cagr']:.1f}</b>", f"{x['F4_p_cagr']:.3f}",
                       pc(x["strategy_dd"]), pc(x["F3_median_dd"]), f"<b>{x['F3_pct_dd']:.1f}</b>", f"{x['F3_p_dd']:.3f}", f"{x['holm_C4']:.3f}", pc(x["F4_median_dd"]), f"<b>{x['F4_pct_dd']:.1f}</b>", f"{x['F4_p_dd']:.3f}"])
    cost_rows = []
    for b in BOOKS:
        for kind in KINDS:
            row = [E(b) if kind == "strategy" else "", LAB[kind]]
            for cst in COSTS:
                row += [pc(bk_(b)[f"{kind}_cagr_{cst:g}"]), pc(bk_(b)[f"{kind}_dd_{cst:g}"])]
            cost_rows.append(row)
    mde_tab = lambda tags: [[E(b)] + [x_ for t_ in tags for x_ in (f"{100 * bk_(b)[f'{t_}_sd_cagr']:.2f}", f"{bk_(b)[f'{t_}_mde_cagr_pp']:.1f}", f"{100 * bk_(b)[f'{t_}_sd_dd']:.2f}", f"{bk_(b)[f'{t_}_mde_dd_pp']:.1f}")] for b in BOOKS]
    mde_io = [[r_[0], str(bk_(r_[0])["round_trips"])] + r_[1:] for r_ in mde_tab(("F1f", "F2f", "F1", "F2"))]
    mde_g = [[r_[0], str(bk_(r_[0])["gold_spells_with_out"])] + r_[1:] for r_ in mde_tab(("F3", "F4"))]
    rob1_dec = [[E(b)] + [f"{bk_(b)[f'{TAG_OF[cr][0]}_pct_{TAG_OF[cr][2]}_{c}']:.1f}" if c != "20.8" else f"{bk_(b)[f'{TAG_OF[cr][0]}_pct_{TAG_OF[cr][2]}']:.1f}" for cr, *_ in CRIT for c in ("0", "20.8", "50")] for b in BOOKS]
    rob1_bes = [[E(b)] + [f"{bk_(b)[f'{TAG_OF[cr][1]}_pct_{TAG_OF[cr][2]}_{c}']:.1f}" if c != "20.8" else f"{bk_(b)[f'{TAG_OF[cr][1]}_pct_{TAG_OF[cr][2]}']:.1f}" for cr, *_ in CRIT for c in ("0", "20.8", "50")] for b in BOOKS]
    rob2_rows = [[E(b), f"{bk_(b)['F1f_liq_pct']:.1f}", f"{bk_(b)['F1_liq_pct']:.1f}", f"{bk_(b)['F3_liq_pct']:.1f}", pc(bk_(b)["liq_fixed50_cagr"]), pc(bk_(b)["liq_cagr"]), f"{bk_(b)['F1f_r3_pct']:.1f}", f"{bk_(b)['F1_r3_pct']:.1f}", f"{bk_(b)['F3_r3_pct']:.1f}",
                  pc(bk_(b)["r3_fixed50_cagr"]), pc(bk_(b)["r3_cagr"]), ("NOT REPORTABLE" if (b in nr_io_r3 or b in nr_gold_r3) else "reportable")] for b in BOOKS]
    r4 = lambda tags: [[E(b)] + [x_ for t_ in tags for x_ in (f"{bk_(b)[f'{t_}_pct_cagr']:.1f}", f"{bk_(b)[f'{t_}_pct_dd']:.1f}", pc(bk_(b)[f"{t_}_median_cagr"]), f"{100 * bk_(b)[f'{t_}_sd_cagr']:.2f}", pc(bk_(b)[f"{t_}_p5_cagr"]), pc(bk_(b)[f"{t_}_p95_cagr"]))] for b in BOOKS]
    r4_cols = lambda tags: ["Book"] + [f"{t_} {c}" for t_ in tags for c in ("CAGR pct", "DD pct", "median", "SD (pp)", "5th pct", "95th pct")]
    r5_rows = [[E(b), pc(bk_(b)["strategy_cagr"]), pc(bk_(b)["F5_median_cagr"]), f"{100 * bk_(b)['F5_sd_cagr']:.2f}", f"{bk_(b)['F5_pct_cagr']:.1f}", f"{bk_(b)['F5_p_cagr']:.3f}", f"{bk_(b)['F5_pct_dd']:.1f}", f"{bk_(b)['F5_p_dd']:.3f}"] for b in BOOKS]
    r6_rows = [[E(b), f"{100 * bk_(b)['r6_rule_dcagr']:+.2f}", f"{100 * bk_(b)['r6_rule_ddd']:+.2f}"] + [x_ for f in ("F1", "F2") for x_ in (f"{100 * bk_(b)[f'r6_{f}_median_dcagr']:+.2f}", f"{bk_(b)[f'r6_{f}_pct_dcagr']:.1f}", f"{100 * bk_(b)[f'r6_{f}_share_dcagr']:.0f}%",
               f"{100 * bk_(b)[f'r6_{f}_median_ddd']:+.2f}", f"{bk_(b)[f'r6_{f}_pct_ddd']:.1f}", f"{100 * bk_(b)[f'r6_{f}_share_ddd']:.0f}%")] for b in BOOKS]
    r7_rows = [[E(b), pc(bk_(b)["strategy_cagr"]), pc(bk_(b)["strategy_dd"])] + [x_ for k_ in R7_KINDS for x_ in ((pc(bk_(b)[f"{k_}_cagr"], 3), f"{100 * (bk_(b)[f'{k_}_cagr'] - bk_(b)['strategy_cagr']):+.3f} pp", pc(bk_(b)[f"{k_}_dd"]), f"{100 * (bk_(b)[f'{k_}_dd'] - bk_(b)['strategy_dd']):+.3f} pp")
                                                                                   if f"{k_}_cagr" in bk_(b) else ("n/a",) * 4)] for b in BOOKS]
    ses_rows = [[E(b), f"{bk_(b)['rule_sessions']:,}", f"{bk_(b)['sessions_total']:,}"] + [x_ for f in ("F1", "F2") for x_ in (f"{bk_(b)[f'{f}_sess_min']:,}", f"{bk_(b)[f'{f}_sess_median']:,.1f}", f"{bk_(b)[f'{f}_sess_max']:,}")] for b in BOOKS]
    str_rows = [[E(b), str(bk_(b)["sleeve_trades"])] + [x_ for f in ("F3", "F4") for x_ in (f"{bk_(b)[f'{f}_strades_min']}", f"{bk_(b)[f'{f}_strades_median']:.1f}", f"{bk_(b)[f'{f}_strades_max']}")] for b in BOOKS]
    ref_html = ""
    for nm_, rows_ in ref.items():
        if rows_:
            if nm_ == "T06":
                ref_html += ("<p>Historical reference, <b>a different window (2019-01-02 → 2026-10-22), real parents and a fixed 50/50 sleeve</b>: T06's rule against T06's own stored N4.10 and N4.9 draws, 20.8 bps; not comparable draw for draw; no pass mark:</p>"
                             + table([[E(b), pc(r_["cagr"]), f"{r_['n10_pct_cagr']:.1f}", f"{r_['n10_pct_dd']:.1f}", f"{r_['n9_pct_cagr']:.1f}", f"{r_['n9_pct_dd']:.1f}"] for b, r_ in rows_.items()],
                                     ["Book", "T06 rule CAGR", "N4.10 CAGR pct", "N4.10 drawdown pct", "N4.9 CAGR pct", "N4.9 drawdown pct"]))
            else:
                ref_html += ("<p>Historical reference, <b>a different window (2019-01-02 → 2026-10-30) and real parents</b>: T08's rule (timed sleeve) against T08's own stored draws, 20.8 bps; not comparable draw for draw; no pass mark:</p>"
                             + table([[E(b), pc(r_["cagr"])] + [x_ for f in FAMS for x_ in (f"{r_[f + '_pct_cagr']:.1f}", f"{r_[f + '_pct_dd']:.1f}")] for b, r_ in rows_.items()],
                                     ["Book", "T08 rule CAGR"] + [f"{f} {c}" for f in FAMS for c in ("CAGR pct", "DD pct")]))
        else:
            ref_html += f"<p class='cap'>Historical reference to {nm_}: omitted, its evidence files (draws.csv, stats.csv) were not found.</p>"

    # ── charts: per-book curves ───────────────────────────────────────────────
    curves_html, lines_data = "", {}
    for b in BOOKS:
        ser, dates = {}, None
        for kind in KINDS:
            q = nav[(nav.book == b) & (nav.cost_bps == PRIMARY) & (nav.run == kind)].sort_values("date")
            ser[kind] = q.nav.values
            dates = list(q.date)
        lsvg, ldata = svg_lines(ser, dates, ylab=b)
        lines_data[b] = ldata
        curves_html += (f'<figure class="card hv"><figcaption><b>{E(b)}</b> · growth of 1 from {dates[0].date()} to {dates[-1].date()}, 20.8 bps · the rule (timed sleeve) ends at {bk_(b)["strategy_end"]:.2f}×. '
                        f'Hover (or touch): the crosshair shows the date and the level, and the tooltip lists all {len(KINDS)} curves at that date (the lines are drawn every 5th session, and the hover snaps to those sessions).</figcaption>'
                        + lsvg + '<div class="tip" hidden></div></figure>')
    legend = "".join(f'<span class="key"><i style="background:{COL[k_]}"></i>{E(LAB[k_])}</span>' for k_ in COL)

    # ── charts: null histograms: fixed-sleeve in-or-out pair, timed in-or-out pair, gold pair ──
    bars_data, hists = {}, ""
    pct_fmt = lambda v: f"{100 * v:.1f}%"
    HTIM = (("io50", "F1f", "F2f", "strategy_fixed50", "in-or-out timing with the sleeve fixed at 50/50 (A1 and A2: F1 deciding, F2 beside)"),
            ("io", "F1", "F2", "strategy", "in-or-out timing with the MAUc1-timed sleeve (C1 and C2: F1 deciding, F2 beside); the real MAUc1 signal in every draw"),
            ("gold", "F3", "F4", "strategy", "gold timing (C3 and C4: F3 deciding, F4 beside); the real in-or-out switch in every draw"))
    for b in BOOKS:
        x = bk_(b)
        for tim, td, tb, rk, tlab in HTIM:
            fd, md_ = TAGS[td][0], TAGS[td][1]
            fb = TAGS[tb][0]
            nd, nb = D(b, fd, mode=md_), D(b, fb, mode=md_)
            cells = ""
            for what, col, mark, title, note in (("cagr", "cagr", x[f"{rk}_cagr"], "After-cost CAGR", "right = better"), ("dd", "max_dd", x[f"{rk}_dd"], "Maximum drawdown", "shallower is to the right")):
                what_lab = "After-cost CAGR" if what == "cagr" else "Maximum drawdown"
                ad, ab = nd[col].values, nb[col].values
                lo_, hi_ = float(min(ad.min(), ab.min(), mark)), float(max(ad.max(), ab.max(), mark))
                pad = (hi_ - lo_) * 0.04
                edges = np.linspace(lo_ - pad, hi_ + pad, 33)
                cd, _ = np.histogram(ad, bins=edges)
                cb, _ = np.histogram(ab, bins=edges)
                marks = [{"label": "The rule", "x": mark, "col": "var(--fg)", "txt": f"percentile {x[f'{td}_pct_{what}']:.1f} vs {fd}, {x[f'{tb}_pct_{what}']:.1f} vs {fb}"},
                         {"label": f"{fd} median", "x": float(np.median(ad)), "col": C10, "txt": "(blue, dashed)", "dash": True},
                         {"label": f"{fb} median", "x": float(np.median(ab)), "col": C9, "txt": "(orange, dashed)", "dash": True}]
                did = f"hist|{b}|{tim}|{what}"
                xt = [(float(v), pct_fmt(v)) for v in np.linspace(lo_, hi_, 5)]
                svg, bd = svg_bars(did, edges, [{"k": fb, "label": f"{fb} (spell shuffle)", "col": C9, "v": cb, "n": len(ab)}, {"k": fd, "label": f"{fd} (free lengths)", "col": C10, "v": cd, "n": len(ad)}],
                                   marks=marks, xk="pct", yk="int", xticks=xt, binlab=[f"{pct_fmt(edges[i])} to {pct_fmt(edges[i + 1])}" for i in range(32)], yunit="draws",
                                   extra=[f"{what_lab} of {ND:,} draws and of the rule, {start3} → {end_date}, 20.8 bps"] * 32)
                bars_data[did] = bd
                cells += f'<div class="hv"><div class="mini">{title} ({note}; black = the rule, dashed = medians)</div>{svg}<div class="tip wrap" hidden></div></div>'
            hists += (f'<figure class="card"><figcaption><b>{E(b)}</b> · {E(tlab)} · {ND:,} draws of each null, 20.8 bps, {start3} → {end_date}</figcaption><div class="two">{cells}</div></figure>')

    # ── charts: spell-length distributions (per-state bounds) ─────────────────
    lenhtml = ""
    for b in BOOKS:
        for tim, fd, fb, parts in (("io", "F1", "F2", (("in", 1, rin), ("out", 0, rout))), ("gold", "F3", "F4", (("buy", 1, gbuy), ("sell", 0, gsell)))):
            cells = ""
            Ad, Ab = (states[f"{b}|full|io|N4.10"], states[f"{b}|full|io|N4.9"]) if tim == "io" else (states[f"{b}|full|gold|N4.10-g"], states[f"{b}|full|gold|N4.9-g"])
            for nm, v_, rl_all in parts:
                lo_, hi_ = BND[(b, "full", tim)][v_]
                ld = np.array([x_ for i in range(Ad.shape[0]) for x_ in lens(Ad[i], v_)])
                lb = np.array([x_ for i in range(Ab.shape[0]) for x_ in lens(Ab[i], v_)])
                edges = np.arange(lo_, hi_ + 2) - 0.5
                cd, _ = np.histogram(ld, bins=edges)
                cb, _ = np.histogram(lb, bins=edges)
                rl = rl_all[b]
                extra = [(f"The real series has {rl.count(x_)} {nm}-spell(s) of exactly this length; " if rl.count(x_) else "") + f"spells of {ND:,} draws, full window {start3} → {end_date}" for x_ in range(lo_, hi_ + 1)]
                did = f"len|{b}|{nm}"
                svg, bd = svg_bars(did, edges, [{"k": fb, "label": f"{fb} (= the real series' own lengths)", "col": C9, "v": cb, "n": len(lb)}, {"k": fd, "label": f"{fd} (free lengths)", "col": C10, "v": cd, "n": len(ld)}],
                                   marks=[], xk="wk", yk="int", w=380, h=170, xticks=[(float(v), str(v)) for v in range(lo_, hi_ + 1, 8 if hi_ > 30 else 6)], extra=extra,
                                   binlab=[f"{x_} weeks" for x_ in range(lo_, hi_ + 1)], yunit="spells")
                bars_data[did] = bd
                cells += (f'<div class="hv"><div class="mini">{nm}-spell lengths in weeks ({lo_} to {hi_}); the real series\': {", ".join(map(str, rl))}</div>{svg}<div class="tip wrap" hidden></div></div>')
            lenhtml += f'<figure class="card"><figcaption><b>{E(b)}</b> · every {"in-or-out" if tim == "io" else "gold"} spell of {ND:,} draws of {fd} and {fb}, full window {start3} → {end_date}</figcaption><div class="two">{cells}</div></figure>'

    # ── charts: the samplers' first steps (draw 0) ────────────────────────────
    samplers = {}
    for did, kk, SSx, bndx, stp, key_, lab_ in (("sampler|first", ks["in"], SS["in"], bnd["in"], steps[0], "sampler_first", "in-spell"), ("sampler|first_g", ksg["buy"], SSg["buy"], bndg["buy"], stepsg[0], "sampler_first_g", "BUY spell")):
        c_ = dp_table(kk, SSx, *bndx)
        xs = list(range(bndx[0], bndx[1] + 1))
        wv = [c_[kk - 1][SSx - x_] if SSx - x_ >= 0 else 0 for x_ in xs]
        edges = np.arange(bndx[0], bndx[1] + 2) - 0.5
        smark = [{"label": "Draw 0 picked", "x": float(stp["x"]), "col": "var(--fg)", "txt": f"(u = {stp['u']:.6f}; P = {stp['p']:.4f})"}]
        ssvg, sbd = svg_bars(did, edges, [{"k": "w", "label": "ways to finish after this length", "col": C10, "v": wv, "n": int(sum(wv)), "op": 0.7}], marks=smark, xk="wk", yk="si", w=520, h=190, L=56,
                             xticks=[(float(v), str(v)) for v in range(bndx[0], bndx[1] + 1, 8)], binlab=[f"first {lab_} = {x_} weeks" for x_ in xs],
                             extra=[f"c({kk - 1}, {SSx} - {x_}) = {wv[i]:,} of c({kk}, {SSx}) = {int(sum(wv)):,} ways" for i, x_ in enumerate(xs)], yunit="ways")
        bars_data[did] = sbd
        data[key_] = {"xs": xs, "weights": [int(v) for v in wv]}
        samplers[did] = (ssvg, xs)

    # ── the highest-CAGR F1 draw (timed) against the rule ─────────────────────
    bb = B0
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
    pnav, snav = qn("hold_proxy", 0.0).nav.values, qn("sleeve_only", 0.0).nav.values
    assert len(ds_) == len(rs_) and len(bcurve) == nses
    assert abs(bcurve[-1] / float(bbest.end_nav) - 1) < 1e-5
    wk0, wk1 = list(wk0s[bb]), list(wk0s[bb][1:]) + [nses - 1]
    code = 2 * rs_ + ds_
    CODE = {3: "Both hold the proxy", 0: "Both in the sleeve", 1: f"Draw {bid} holds the proxy, rule in the sleeve", 2: "Rule holds the proxy, draw in the sleeve"}
    pr = lambda r_: f"{100 * (r_ - 1):+.1f}%"
    cls_w, cls_p, cls_s = {c: 0 for c in CODE}, {c: 1.0 for c in CODE}, {c: 1.0 for c in CODE}
    pair_runs, span_rows, span_stats = [], [], []
    for c_, s_, e_, i_, k_ in runs_of(code, wk0, wk1):
        wks = k_ - i_ + 1
        pa, sl_ = pnav[e_] / pnav[s_], snav[e_] / snav[s_]
        cls_w[c_] += wks
        cls_p[c_] *= pa
        cls_s[c_] *= sl_
        tip = f"{bdates[s_].date()} → {bdates[e_].date()}, {wks} wk: {CODE[c_]}. Proxy {pr(pa)}, 50/50 sleeve {pr(sl_)}"
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
    ser_b = {"hold_proxy": pnav, "draw": bcurve, "strategy": rq.nav.values}
    st_rule, st_draw, tip_ix, g_sess, gw_sess = np.zeros(nses, int), np.zeros(nses, int), np.zeros(nses, int), np.zeros(nses, int), np.zeros(nses)
    for j_ in range(len(rs_)):
        st_rule[wk0[j_]:wk1[j_]], st_draw[wk0[j_]:wk1[j_]] = rs_[j_], ds_[j_]
        g_sess[wk0[j_]:wk1[j_]], gw_sess[wk0[j_]:wk1[j_]] = gb_[j_], gwk[bb][j_]
    for r_, (c_, s_, e_, tip) in enumerate(pair_runs):
        tip_ix[s_:e_] = r_
    st_rule[-1], st_draw[-1], tip_ix[-1], g_sess[-1], gw_sess[-1] = st_rule[-2], st_draw[-2], tip_ix[-2], g_sess[-2], gw_sess[-2]
    hover = {"dates": [d_.strftime("%Y-%m-%d (%a)") for d_ in bdates], "rule": [round(float(v_), 4) for v_ in rq.nav.values], "draw": [round(float(v_), 4) for v_ in bcurve],
             "proxy": [round(float(v_), 4) for v_ in pnav], "rs": st_rule.tolist(), "ds": st_draw.tolist(), "g": g_sess.tolist(), "gw": [round(float(v_), 4) for v_ in gw_sess],
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
    in_ok = all(bi[1][0] <= x_ <= bi[1][1] for x_ in ln(spd, 1)) and sum(ln(spd, 1)) == sum(ln(spr, 1))
    out_ok = all(bi[0][0] <= x_ <= bi[0][1] for x_ in ln(spd, 0)) and sum(ln(spd, 0)) == sum(ln(spr, 0))
    hold_tab = [
        [f"Weeks invested (of {nw})", f"{rs_.sum()} ({pc(rs_.mean(), 2)})", f"{ds_.sum()} ({pc(ds_.mean(), 2)})", fl(rs_.sum() == ds_.sum())],
        [f"Sessions invested (of {nses - 1:,})", f"{ses_r} ({pc(ses_r / (nses - 1), 2)})", f"{ses_d} ({pc(ses_d / (nses - 1), 2)})", fl(ses_r == ses_d, "held" if ses_r == ses_d else f"not held: differs by {abs(ses_r - ses_d)}")],
        ["In-spells · out-spells", f"{len(ln(spr, 1))} · {len(ln(spr, 0))}", f"{len(ln(spd, 1))} · {len(ln(spd, 0))}", fl((len(ln(spr, 1)), len(ln(spr, 0))) == (len(ln(spd, 1)), len(ln(spd, 0))))],
        ["Entries (0→1) · exits (1→0)", f"{ent(rs_)} · {ext(rs_)}", f"{ent(ds_)} · {ext(ds_)}", fl((ent(rs_), ext(rs_)) == (ent(ds_), ext(ds_)))],
        ["First state", "sleeve" if rs_[0] == 0 else "proxy", "sleeve" if ds_[0] == 0 else "proxy", fl(rs_[0] == ds_[0])],
        ["In-spell lengths (weeks), in order", ", ".join(map(str, ln(spr, 1))), ", ".join(map(str, ln(spd, 1))), fl(in_ok, f"free: sum equal, each in [{bi[1][0]}, {bi[1][1]}]" if in_ok else "OUT OF BOUNDS")],
        ["Out-spell lengths (weeks), in order", ", ".join(map(str, ln(spr, 0))), ", ".join(map(str, ln(spd, 0))), fl(out_ok, f"free: sum equal, each in [{bi[0][0]}, {bi[0][1]}]" if out_ok else "OUT OF BOUNDS")],
        ["The MAUc1 signal in the weeks each is OUT", "real", "real (the same series)", fl(True, "held, real")],
        ["Quarterly resets, portfolio, weights, cost, execution", "as in the rule", "as in the rule", fl(True, "held")],
        ["Timing and lengths of the in-or-out spells", "the rule's own", "drawn from the allowed tuples", '<span class="chip">randomised</span>'],
    ]
    rsvg, geom = svg_regime(bdates, ser_b, rule_runs, draw_runs, pair_runs, gold_runs, rw_runs, dw_runs, f"Draw {bid}")
    hover.update(geom)
    data["best_draw"] = {"book": bb, "draw_id": bid, "cagr": float(bbest.cagr), "end_nav": float(bbest.end_nav), "rule_cagr": bk_(bb)["strategy_cagr"], "weeks_both_in": cls_w[3], "weeks_both_out": cls_w[0],
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
    gin_ok = all(bg[1][0] <= x_ <= bg[1][1] for x_ in ln(sp_d, 1)) and sum(ln(sp_d, 1)) == sum(ln(sp_g, 1))
    gout_ok = all(bg[0][0] <= x_ <= bg[0][1] for x_ in ln(sp_d, 0)) and sum(ln(sp_d, 0)) == sum(ln(sp_g, 0))
    gold_tab = [
        [f"Weeks with the gold signal BUY (of {nw})", f"{gb_.sum()} ({pc(gb_.mean(), 2)})", f"{gd_.sum()} ({pc(gd_.mean(), 2)})", fl(gb_.sum() == gd_.sum())],
        ["BUY-spells · SELL-spells", f"{len(ln(sp_g, 1))} · {len(ln(sp_g, 0))}", f"{len(ln(sp_d, 1))} · {len(ln(sp_d, 0))}", fl((len(ln(sp_g, 1)), len(ln(sp_g, 0))) == (len(ln(sp_d, 1)), len(ln(sp_d, 0))))],
        ["First gold state", "BUY" if gb_[0] else "SELL", "BUY" if gd_[0] else "SELL", fl(gb_[0] == gd_[0])],
        ["BUY-spell lengths (weeks), in order", ", ".join(map(str, ln(sp_g, 1))), ", ".join(map(str, ln(sp_d, 1))), fl(gin_ok, f"free: sum equal, each in [{bg[1][0]}, {bg[1][1]}]" if gin_ok else "OUT OF BOUNDS")],
        ["SELL-spell lengths (weeks), in order", ", ".join(map(str, ln(sp_g, 0))), ", ".join(map(str, ln(sp_d, 0))), fl(gout_ok, f"free: sum equal, each in [{bg[0][0]}, {bg[0][1]}]" if gout_ok else "OUT OF BOUNDS")],
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
              f'<p>The right-hand end of the {bb} F1 (timed sleeve) CAGR histogram above is draw {bid}: CAGR {pc(float(bbest.cagr))} (end value {float(bbest.end_nav):.1f}×), against the rule\'s {pc(bk_(bb)["strategy_cagr"])} ({bk_(bb)["strategy_end"]:.1f}×). '
              f'It holds the proxy portfolio for the same {int(bbest.invested_weeks)} weeks and switches the same number of times as the rule, but its spell lengths are its own; its sleeve reads the <b>real</b> MAUc1 signal in whatever weeks it is OUT. '
              f'Its states are row {bid} of <code>evidence/{E(ev.name)}/draw_states.npz</code>, key <code>{bb}|full|io|N4.10</code> (read straight from the file, no rebuild), and its curve is <code>draw_curves_20.8.npz</code> key <code>{bb}|F1_{bid}</code>.</p>'
              f'<h3>What F1 holds, and what it randomises, for this draw</h3>'
              + table(hold_tab, ["Dimension", "The rule", f"Draw {bid}", "Held?"])
              + f'<p class="cap">Weeks invested, spell counts, entries and exits and the first state are held exactly (gate V3); every spell\'s length and so its position are drawn, each length within its bounds and the in- and out-lengths summing to the rule\'s totals. '
                f'Sessions are not held exactly: a week has 3 to 5 sessions. Here the two differ by {abs(ses_r - ses_d)} of {nses - 1:,} sessions ({100 * abs(ses_r - ses_d) / (nses - 1):.2f} pp of the window).</p>'
              f'<div class="legend"><span class="key"><i style="background:{COL["strategy"]}"></i>Rule</span><span class="key"><i style="background:var(--fg)"></i>Draw {bid}</span>'
              f'<span class="key"><i style="background:{COL["hold_proxy"]}"></i>Hold the proxy</span>'
              f'<span class="key"><i style="background:{COL["strategy"]};height:10px;opacity:.5"></i>only the rule holds the proxy</span>'
              f'<span class="key"><i style="background:var(--fg);height:10px;opacity:.4"></i>only the draw holds the proxy</span><span class="key"><i style="background:#c9a227;height:10px"></i>MAUc1 BUY</span></div>'
              f'<figure class="card hv"><figcaption><b>{bb}</b> · growth of 1 from {bdates[0].date()} to {bdates[-1].date()}, 20.8 bps (log scale); the grey line is the proxy portfolio held throughout, before cost. '
              f'Strips: the first two are filled when the book holds the proxy portfolio that week (empty = in the sleeve), the third marks where they differ, the fourth is filled when the weekly MAUc1 signal is BUY, and the last two show the GOLDBEES target weight of the sleeve '
              f'(bar height: 80% when MAUc1 is BUY, 20% when SELL; empty while holding the proxy portfolio). Hover (or touch) anywhere on the chart: the crosshair shows the date on the x-axis and the level on the y-axis, and the tooltip lists every value drawn at that date, the signal and the sleeve split.</figcaption>'
              + rsvg + '<div id="regime-tip" class="tip" hidden></div></figure>'
              f'<h3>Weeks by what the two did</h3>'
              + table(cls_rows, ["The two timings", "Weeks", "Proxy portfolio, compounded over these weeks", "50/50 sleeve, same weeks", "Proxy minus sleeve"])
              + f'<p>They agree in {cls_w[3] + cls_w[0]} of {len(code)} weeks and differ in {cls_w[1] + cls_w[2]}, in {n1 + n2} separate stretches. '
                f'In the stretches only the draw held the proxy, the proxy beat the sleeve in {n1 - wrong(1)} of {n1}; in the stretches only the rule held it, the proxy beat the sleeve in {n2 - wrong(2)} of {n2}.</p>'
              + '<h3>Every stretch where they differ</h3>'
              + table(span_rows, ["From", "To", "Weeks", "Holds the proxy", "Proxy", "50/50 sleeve", "Proxy minus sleeve", "Right call"])
              + '<p class="cap">Returns are close to close between trade dates, before cost, and compounded within each stretch, so the stretches explain the gap between the two paths but do not add up exactly to the CAGR difference. '
                '"Right call" is the timing that was in the better of the proxy portfolio and the 50/50 sleeve over the stretch (the sleeve here is the plain 50/50 one: the stretch table compares the proxy portfolio with a neutral sleeve, not with the MAUc1 split). '
                f'Draw {bid} is the best of {len(nbb):,} F1 draws, so it is the extreme of the null by construction, not a rival rule.</p>'
              f'<h3>The highest-return F3 draw (gold timing), {bb}</h3>'
              f'<p>Draw {gid} of F3: CAGR {pc(float(gbest.cagr))} (end value {float(gbest.end_nav):.2f}×) against the rule\'s {pc(bk_(bb)["strategy_cagr"])}. It keeps the real in-or-out switch and the number of gold spells and BUY weeks, but its gold spells fall elsewhere (states: row {gid} of <code>draw_states.npz</code>, key <code>{bb}|full|gold|N4.10-g</code>).</p>'
              + table(gold_tab, ["Dimension", "The real series", f"F3 draw {gid}", "Held?"]))

    # ── the worked example html ───────────────────────────────────────────────
    ex = data["example"]
    exx, exf, exn, exr = ex["exit"], ex["flip"], ex["entry"], ex["reset"]
    nvw = nv.loc[k - 2:k + 2]
    fmt_units = lambda u_: "none (the initial position at the first close is not in proxy_units.csv)" if u_ is None else ", ".join(f"{E(c_[6:])} {u_[c_]:.8f}" for c_ in UC)
    ex_rows = [[str(j_), str(d.decision_date.iloc[j_]), str(int(rule[b][j_])), str(int(Z["io|N4.9"][0][j_])), str(int(Z["io|N4.10"][0][j_])), str(int(gold[b][j_])), str(int(Z["gold|N4.9-g"][0][j_])), str(int(Z["gold|N4.10-g"][0][j_]))] for j_ in range(20)]
    step_tab = lambda stp: [[s_["spell"], str(s_["part"]), str(s_["m"]), str(s_["t"]), f"{s_['u']:.6f}", f"{s_['total']:,}", f"<b>{s_['x']}</b>", f"{s_['ways_x']:,}", f"{100 * s_['p']:.2f}%"] for s_ in stp]
    inp_rows = [[E(r_.file), E(r_.through), E(r_.approved_row), E(r_.sha256[:16]), E(r_.usable_from)] for r_ in inp.itertuples()]
    data["inputs"] = [{"file": r_.file, "through": r_.through, "approved_row": r_.approved_row, "sha16": r_.sha256[:16], "usable_from": r_.usable_from} for r_ in inp.itertuples()]
    gate_desc = {"V1": "verify_t09.py shares no code with the engine" + (f": {ver['gate_compared']:,} comparisons, {ver.get('gate_failures_and_missing')} failures, a corrupted copy is caught: {ver.get('selftest', {}).get('detected')}" if ver else ""),
                 "V2": "every decision reads Master rows (three indices and MAUc1) dated on or before it; every trade is on a later session; no Smallcap 100 row before its usable-from date",
                 "V3": "all nulls hold their tables: weeks, first state, spell counts and sums of the in-or-out and the gold series; N4.9 and N4.9-g sorted lengths; N4.10 and N4.10-g per-state bounds; both windows",
                 "V4": "identities: a one-index book is that index, hold-the-proxy equals a plain-loop hand build, the shared code equals T08's, the signals equal the Master files, the gold splice is continuous",
                 "V5": "the samplers: chi-square on the small case, DP count equals inclusion-exclusion for every table, mean lengths at each position",
                 "V6": "the sleeve and reset identities: post-trade values equal their targets, cost = traded × cost_bps ÷ 2 ÷ 10,000, no trade while OUT with the signal constant, resets at the book's weights"}
    gate_rows = [[f"{k_} {n_}", f'<span class="chip {"ok" if (gate_line or {}).get(k_) == "PASS" else "bad"}">{(gate_line or {}).get(k_, "NOT RUN")}</span>', E(gate_desc[k_])]
                 for k_, n_ in (("V1", "independent check"), ("V2", "point in time"), ("V3", "the nulls hold their tables"), ("V4", "identities and regressions"), ("V5", "the samplers are exact"), ("V6", "the sleeve and reset identities"))]
    rep_rows = [[E(b), str(bk_(b)["round_trips"]), str(bk_(b)["gold_spells_with_out"]), str(bk_(b)["r3_round_trips"]), str(bk_(b)["r3_gold_spells_with_out"]), "yes" if (b not in nr_io and b not in nr_gold) else "NOT REPORTABLE"] for b in BOOKS]
    num_re = re.compile(r"^\d+\.\s*")
    amend_html = "<ol>" + "".join("<li>" + md_inline(num_re.sub("", l)) + "</li>" for l in amend if num_re.match(l)) + "</ol>"
    fill_txt = ("the proxy's OHLC4 (the session is before " + GB_FIRST + ")") if exx["proxy_fill"] else "GOLDBEES's own de-spiked OHLC4"
    b = B0
    if not gates_ok:
        lead = "A validity gate failed or analysis.log is missing: do not read the results below."
    else:
        parts_ = []
        parts_.append("the fixed-50/50 rule beats random in-or-out timing (A1, A2)" if A_ok else "the fixed-50/50 rule does not clear the pass mark against random in-or-out timing (A1 or A2 fails)")
        parts_.append("the MAUc1-timed rule beats random in-or-out timing (C1, C2)" if C_ok else "the MAUc1-timed rule does not clear the pass mark against random in-or-out timing (C1 or C2 fails)")
        parts_.append("the MAUc1 timing of the sleeve beats random gold timing (C3, C4)" if G_ok else "the MAUc1 timing of the sleeve is not distinguishable from random gold timing (C3 or C4 fails)")
        lead = "On this stretch with a proxy portfolio: " + "; ".join(parts_) + "."
    data["outcome"] = {"A": bool(A_ok), "C": bool(C_ok), "G": bool(G_ok)}
    nb_ = lambda cr: f"{V[cr]} of {len(BOOKS)}"
    answer = (f'<div class="answer"><p><b>{lead}</b> The proxy portfolio holds the Nifty 100, Midcap 100 and Smallcap 100 at each book\'s fixed mix (reset at the start of every quarter while held) only when the three weekly supertrends are all BUY, and otherwise a sleeve of GOLDBEES and cash: '
              f'50/50 in Part A, and 80/20 when the weekly MAUc1 gold supertrend is BUY and 20/80 when it is SELL in Part B. Judged against random timings on {start3} → {end_date}, after 20.8 bps. '
              f'<b>A1</b> (return) and <b>A2</b> (worst fall) of the 50/50 rule against F1 run with the 50/50 sleeve: {nb_("A1")} books and {nb_("A2")} at the 90th percentile (pre-registered pass: 3 of 4 each); F2 beside: {V["A1_beside"]} and {V["A2_beside"]}. '
              f'<b>C1</b> and <b>C2</b>, the timed rule against F1 (real MAUc1 signal in every draw): {nb_("C1")} and {nb_("C2")}; F2 beside: {V["C1_beside"]} and {V["C2_beside"]}. '
              f'<b>C3</b> and <b>C4</b>, the gold timing against F3 (real in-or-out switch): {nb_("C3")} and {nb_("C4")}; F4 beside: {V["C3_beside"]} and {V["C4_beside"]}. Holm-adjusted p-values (m = 6) are in the table.</p>'
              f'<p>The catch: the window starts {start3}, before the parents\' holdings exist, and the portfolio is a proxy that no investor held; its mixes come from the parents\' 2019-2026 holdings. The rule, its weights and the signals were chosen after the 2014-2026 results were seen; '
              f'only {start3} → 2014-06-30 predates that look, and the GOLDBEES leg before 2014-07-01 is a MAUc1-based proxy. Every three-index and MAUc1 row is a backfill by the production code. On the window starting {r3_start} (R3) the 50/50 rule, the timed rule and the gold timing '
              f'clear the 90th percentile in {V["R3_A1"]}, {V["R3_C1"]} and {V["R3_C3"]} of {len(BOOKS)} books. Every result here is in-sample and PROVISIONAL.</p></div>')
    steps_chip = '<span class="chip ok">replay equals the stored draw</span>' if replay_ok else '<span class="chip bad">REPLAY DIFFERS from the stored draw</span>'
    steps_chip_g = '<span class="chip ok">replay equals the stored draw</span>' if replay_ok_g else '<span class="chip bad">REPLAY DIFFERS from the stored draw</span>'
    s1_, sg1 = steps[0], stepsg[0]
    mdl = lambda key: f"{min(bk_(b_)[key] for b_ in BOOKS):.1f} to {max(bk_(b_)[key] for b_ in BOOKS):.1f}"
    rk_ = ex["rank"]
    wd = lambda lst: "(" + ", ".join(f"{100 * x_:.4f}%" for x_ in lst) + ")"
    wbe, waf = [v_ / exr["V"] for v_ in exr["before"]], [v_ / (exr["V"] - exr["cost"]) for v_ in exr["after"]]
    n_in_val = [wb[i] * (exn["V"] - exn["cost"]) for i in range(3)]
    ncrit = len(CRIT)
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>T09 proxy portfolio timing null</title><style>{CSS}</style></head><body><main>
<p class="eyebrow">AA · T09 · timing rule · pre-registration sha256 {E(sha[:12])} · data: APPROVED_DATA.md as of {E(str(asof_file))}</p>
<h1>Do the three-index switch, with a fixed 50/50 sleeve and with a MAUc1-timed GOLDBEES sleeve, still choose <em>when</em> to hold the portfolio better than chance on a three-index proxy portfolio, {start3} → {end_date}, before the parents' holdings exist?</h1>
<p class="meta">{start3} → {end_date} · four proxy books (the names only label four band mixes) · decisions every Friday, trades next session at OHLC4 · 10.4 bps a side · {ND:,} draws per book, cost and null · every number is computed from <code>evidence/{E(ev.name)}/</code></p>
<h2 id="answer">The answer</h2>{answer}
{table(answer_rows, ["Book"] + [x_ for cr, *_ in CRIT for x_ in (f"{cr} pct", "Holm p")])}
<p class="cap">Percentile = share of the {ND:,} draws the rule beats (ties count half). Pass mark: 90 in at least 3 of 4 books, against the deciding null (F1 for A1, A2, C1, C2, with the 50/50 sleeve in the draws for A1 and A2; F3 for C3 and C4). Holm p = Holm-adjusted p-value over the six criteria (m = 6) of that book (the pass mark is on the unadjusted percentile). After 20.8 bps round-trip cost. Window {start3} → {end_date}. The four books have the same in-or-out decisions and the same gold series and share their draws, so "3 of 4" is a consistency check, not four tests.</p>
<div class="tw"><table><tbody><tr><td>A1 equity timing, 50/50 sleeve (return), F1 with the 50/50 sleeve</td><td>{chip(V['A1'] >= 3)} {V['A1']} of {len(BOOKS)}</td><td>F2 beside it: {V['A1_beside']} of {len(BOOKS)}</td></tr><tr><td>A2 protection, 50/50 sleeve (worst fall), F1 with the 50/50 sleeve</td><td>{chip(V['A2'] >= 3)} {V['A2']} of {len(BOOKS)}</td><td>F2 beside it: {V['A2_beside']} of {len(BOOKS)}</td></tr><tr><td>C1 equity timing, timed sleeve (return), F1</td><td>{chip(V['C1'] >= 3)} {V['C1']} of {len(BOOKS)}</td><td>F2 beside it: {V['C1_beside']} of {len(BOOKS)}</td></tr><tr><td>C2 protection, timed sleeve (worst fall), F1</td><td>{chip(V['C2'] >= 3)} {V['C2']} of {len(BOOKS)}</td><td>F2 beside it: {V['C2_beside']} of {len(BOOKS)}</td></tr><tr><td>C3 gold timing (return), F3</td><td>{chip(V['C3'] >= 3)} {V['C3']} of {len(BOOKS)}</td><td>F4 beside it: {V['C3_beside']} of {len(BOOKS)}</td></tr><tr><td>C4 gold-timing protection (worst fall), F3</td><td>{chip(V['C4'] >= 3)} {V['C4']} of {len(BOOKS)}</td><td>F4 beside it: {V['C4_beside']} of {len(BOOKS)}</td></tr></tbody></table></div>
<h3>What to be careful about</h3><ul>
<li><b>Each null randomises one timing and holds the other real.</b> F1 and F2 move the in-or-out switch and read the real gold signal in whatever weeks they are OUT (with the sleeve fixed at 50/50 for A1 and A2); F3 and F4 keep the real switch and move the gold signal. A pass says the rule's timing beats random placement of that one ingredient, not that it beats holding the portfolio. Both random together is only a robustness check (R5).</li>
<li><b>Only C3 and C4 bear on the gold timing.</b> A1 and A2 replicate T06 and C1 and C2 replicate T08 on a different stretch and a proxy. The gold nulls move only the sleeve's split, so their spread is narrower than F1's (see the power tables).</li>
<li><b>Nothing is out of sample.</b> The rule, the 80/20 weights and MAUc1 were chosen after seeing 2014-2026 results; the stretch {start3} → 2014-06-30 predates that look but its decisions are a backfill by the production code, as is every MAUc1 row. On the window starting {r3_start}, the 50/50 rule, the timed rule and the gold timing clear the 90th percentile in {V['R3_A1']}, {V['R3_C1']} and {V['R3_C3']} of {len(BOOKS)} books.</li>
<li><b>{bk_(B0)['round_trips']} round trips and {bk_(B0)['sleeve_trades']} sleeve trades per book</b> is all the evidence there is. The smallest return edge detectable at 80% power against F1 (timed) is {mdl('F1_mde_cagr_pp')} pp a year; against F3 {mdl('F3_mde_cagr_pp')} pp.</li>
<li><b>The books are one market.</b> {B7}'s return percentile for the timed rule against F1 is {bk_(B7)['F1_pct_cagr']:.1f} and against F3 {bk_(B7)['F3_pct_cagr']:.1f}.</li></ul>

<h2 id="data">The data</h2>
<p>The proxy portfolio is three raw indices (price indices, no dividends), the Nifty 100, Midcap 100 and Smallcap 100, held at fixed weights per book and filled at the (open+high+low+close)/4 of each index's daily bar (D25, copied from production's index file). The calendar is D26's. The three weekly index signals are D03's Master files; the Smallcap 100 rows are read from 2011-11-25 and its prices from {start3} (standing rule 7: its prices before 2011-10-03 are corrupt). The gold signal is the weekly SIGN of MAUc1, MCX gold futures, recomputed from the start of the export (D24b). The GOLDBEES leg is GOLDBEES from 2014-07-01 (D09) and a MAUc1-based proxy before (D09b). Cash is the LBES level. Every file below is an APPROVED row of <code>data/APPROVED_DATA.md</code>, whose "As of" date is <b>{E(str(asof_file))}</b> (the run recorded {E(str(asof_inputs))}). No price after {end_date} is read, and no stock, basket or published NAV.</p>
<p><b>Band mixes</b> (Nifty 100, Midcap 100, Smallcap 100), the parents' average listed basket weight in each market-cap band over 2019-2026 (tags D20-D23), not what the parents held in 2011-2019:</p>
{table([[E(b)] + [f"{W[b][n_]:.8f}" for n_ in INDEX_NAMES] for b in BOOKS], ["Book", "Nifty 100", "Midcap 100", "Smallcap 100"])}
{table(inp_rows, ["File (relative to AA/)", "Through", "Approved row", "sha256 (first 16)", "Usable from"])}
<p class="cap">Caveats, disclosed: (1) the proxy is not a book anyone held: the mixes are 2019-2026 averages, the indices are price indices with no tracking error or dividends, and fills at an index's OHLC4 at 10.4 bps a side are an assumption; there is no check of the proxy against the real parents in this test. (2) The GOLDBEES leg before 2014-07-01 is a MAUc1 proxy that tracks GOLDBEES only loosely (the correlations are in T09.md section 2); MAUc1 is a futures series with roll artifacts; R7 re-runs the rule with two variants of the proxy leg. (3) The LBES file's source before 2026-08-10 is unrecorded (F-AA-D09); LIQUIDCASE cash (R2) cannot change a number in this window. (4) Decisions are a backfill by the production code, and so is every MAUc1 row. (5) The rule, its weights and the signals were chosen after seeing 2014-2026 results. (6) The Smallcap 100 prices before 2011-10-03 and its signal before 2011-11-25 are not read.</p>
<p><b>Amendments before the run</b> (outside the frozen sections of <code>T09.md</code>; found while the engine was built, before any NAV or return of a run was read):</p>{amend_html}
<p><b>Validity gates</b> (from <code>analysis.log</code>; the page is only to be read if all six pass):</p>
{table(gate_rows, ["Gate", "Result", "What it checks"])}
<p><b>Reportability</b> (a book with fewer than 4 round trips of the in-or-out switch, or fewer than 4 gold spells that contain an OUT week for C3 and C4, is NOT REPORTABLE):</p>
{table(rep_rows, ["Book", "Round trips", "Gold spells with an OUT week", "R3 round trips", "R3 gold spells with an OUT week", "Reportable"])}

<h2 id="one">One backtest, end to end ({b}, 20.8 bps, {start3} → {end_date})</h2>
<p><b>1. The decision.</b> On Friday {E(exx['decision_date'])} (week {exx['decision_week']}) the latest weekly rows of the three index files read Nifty 100 {E(str(d.sign_Nifty100[jx]))}, Midcap 100 {E(str(d.sign_MC100[jx]))}, Smallcap 100 {E(str(d.sign_SC100[jx]))}, and the latest MAUc1 row ({E(str(d.label_MAUc1[jx]))}) reads {E(exx['sign_MAUc1'])}. Not all three index signals are BUY, so the target is the sleeve, split {100 * exx['gw']:.0f}% GOLDBEES / {100 * (1 - exx['gw']):.0f}% cash because MAUc1 is {E(exx['sign_MAUc1'])} (Part A would split it 50/50); last week the book held the proxy portfolio.</p>
<div class="formula">state(d) = IN  if SIGN_Nifty100 = SIGN_MC100 = SIGN_SC100 = BUY (latest row dated on or before d), else OUT
g(d)     = SIGN of the latest MAUc1 row dated on or before d          w(d) = 0.8 if g(d) = BUY, 0.2 if SELL
IN  → Nifty 100 / Midcap 100 / Smallcap 100 at {tuple(round(w_, 8) for w_ in wb)}, reset on entry and at the first session of each quarter
OUT → w(d) GOLDBEES + (1 − w(d)) cash        (changed only when the target changes)</div>
<p><b>2. The exit trade.</b> On the next session, {E(exx['trade_date'])}, at the (open+high+low+close)/4 of every instrument the book sells the three index positions and buys GOLDBEES and cash. Value before: {exx['V']:.6f}; value traded (both sides): {exx['traded']:.6f}; cost = traded × 20.8 ÷ 2 ÷ 10,000 = {exx['cost']:.6f}. After the trade GOLDBEES is worth {exx['gold_after']:.6f} and cash {exx['cash_after']:.6f}, that is {100 * exx['gold_after'] / (exx['gold_after'] + exx['cash_after']):.2f}% in GOLDBEES (target {100 * exx['gw']:.0f}% of the value after cost, {exx['V'] - exx['cost']:.6f}). The GOLDBEES fill is {fill_txt}. NAV at the close after the trade: {exx['nav_after']:.6f}.</p>
<div class="formula">traded = Σ |target value − held value|        cost = traded × cost_bps ÷ 2 ÷ 10,000
GOLDBEES value = w × (V − cost)        cash value = (1 − w) × (V − cost)        new units = value ÷ fill price</div>
<p><b>3. Units.</b> Before the exit (after the previous trade, {E(str(exx['units_before']['date'])) if exx['units_before'] else 'none'}) the book holds {fmt_units(exx['units_before'])}; after it ({E(exx['trade_date'])}) {fmt_units(exx['units_after'])}.</p>
<p><b>4. A gold flip (sleeve rebalance).</b> While OUT on both sides, a change of the MAUc1 signal re-splits the sleeve; the weights otherwise drift. On Friday {E(exf['decision_date'])} (week {exf['decision_week']}) MAUc1 turned {"BUY" if exf['g_after'] else "SELL"} (the week before: {"BUY" if exf['g_before'] else "SELL"}) while the book was OUT in both weeks, so on {E(exf['trade_date'])} it sold and bought GOLDBEES and cash from their drifted values to {100 * exf['gw_after']:.0f}% / {100 * (1 - exf['gw_after']):.0f}% of the sleeve value after cost. Value before {exf['V']:.6f}; traded {exf['traded']:.6f}; cost {exf['cost']:.6f}.</p>
{table([["GOLDBEES", f"{exf['gold_before']:.6f}", f"{exf['gold_after']:.6f}", f"{exf['units_before']['units_GOLDBEES']:.8f}", f"{exf['units_after']['units_GOLDBEES']:.8f}"], ["Cash (LBES)", f"{exf['cash_before']:.6f}", f"{exf['cash_after']:.6f}", f"{exf['units_before']['units_LBES']:.8f}", f"{exf['units_after']['units_LBES']:.8f}"]], ["Instrument", "Value before", "Value after", f"Units before ({E(exf['units_before']['date'])})", f"Units after ({E(exf['trade_date'])})"])}
<p class="cap">Units before are the units held after the previous trade (units do not change between trades). The value before and after use the same session's fill, so GOLDBEES value ÷ units, the fill price, is the same before and after, and so is the cash level.</p>
<p><b>5. An entry.</b> On Friday {E(exn['decision_date'])} (week {exn['decision_week']}) the three index signals read {", ".join(E(x_) for x_ in exn['sign'])}: all BUY, so the target is the proxy portfolio (MAUc1 reads {E(exn['sign_MAUc1'])} but it only matters while OUT). On {E(exn['trade_date'])} the book sells the sleeve (value before {exn['V']:.6f}, traded {exn['traded']:.6f}, cost {exn['cost']:.6f}) and buys the three indices at the book's weights of the value after cost ({exn['V'] - exn['cost']:.6f}): Nifty 100 {n_in_val[0]:.6f}, Midcap 100 {n_in_val[1]:.6f}, Smallcap 100 {n_in_val[2]:.6f}. Units after: {fmt_units(exn['units_after'])}. NAV at the close after the trade: {exn['nav_after']:.6f}.</p>
<p><b>6. A quarterly reset.</b> While IN the weights drift with the three indices. On {E(exr['date'])}, the first session of a quarter, with the book holding the proxy portfolio and no decision trade that day, it sells and buys the three index positions from their drifted values back to the book's weights of the value after cost, at that session's OHLC4. Value {exr['V']:.6f}; traded {exr['traded']:.6f}; cost {exr['cost']:.6f}. Weights before {wd(wbe)} and after {wd(waf)} (the book's: {wd(wb)}). Values before {', '.join(f'{v_:.6f}' for v_ in exr['before'])}, after {', '.join(f'{v_:.6f}' for v_ in exr['after'])}. Units before ({E(str(exr['units_before']['date']))}): {fmt_units(exr['units_before'])}; after: {fmt_units(exr['units_after'])}. NAV at the close after the reset: {exr['nav_after']:.6f}.</p>
<p><b>7. Daily value.</b> NAV(t) = Σ units × close(t) over the three indices, GOLDBEES and cash. Around the exit:</p>
{table([[str(r_.date.date()), f"{r_.nav:.6f}"] for r_ in nvw.itertuples()], ["Date", "NAV"])}
<p><b>8. Statistics.</b> The path runs from 1.000000 on {nv.date.iloc[0].date()} to {ex['end_nav']:.6f} on {nv.date.iloc[-1].date()}: {ex['sessions']} sessions, years = ({ex['sessions']} − 1) ÷ 252 = {(ex['sessions'] - 1) / 252:.4f}, CAGR = {ex['end_nav']:.4f}^(1 ÷ {(ex['sessions'] - 1) / 252:.4f}) − 1 = <b>{pc(ex['cagr'], 2)}</b>, worst fall {pc(ex['max_dd'], 2)}; {bk_(b)['trades']} trades of which {bk_(b)['sleeve_trades']} sleeve rebalances and {bk_(b)['quarterly_resets']} quarterly resets. The same rule with the fixed 50/50 sleeve (Part A) ends at {bk_(b)['strategy_fixed50_end']:.4f}: CAGR {pc(bk_(b)['strategy_fixed50_cagr'], 2)}, worst fall {pc(bk_(b)['strategy_fixed50_dd'], 2)}, {bk_(b)['fixed50_trades']} trades.</p>
<p><b>9. The real series and the draws.</b> The rule's in-or-out path is {len(rin[b]) + len(rout[b])} spells: {len(rin[b])} in (lengths {", ".join(map(str, rin[b]))}, sum {sum(rin[b])}) and {len(rout[b])} out (lengths {", ".join(map(str, rout[b]))}, sum {sum(rout[b])}), starting {"in" if rule[b][0] else "out"}. The real gold signal is {len(gbuy[b]) + len(gsell[b])} spells: {len(gbuy[b])} BUY (lengths {", ".join(map(str, gbuy[b]))}, sum {sum(gbuy[b])}) and {len(gsell[b])} SELL (lengths {", ".join(map(str, gsell[b]))}, sum {sum(gsell[b])}), starting {"BUY" if gold[b][0] else "SELL"}. The first 20 weekly states of the real series ({d.decision_date.iloc[0]} → {d.decision_date.iloc[19]}), of F2 draw 0 (the in-or-out spells reordered; seed <code>default_rng([12, 3, 0])</code>), of F1 draw 0 (new in-or-out lengths; seed <code>default_rng([12, 6, 0])</code>), of F4 draw 0 (the gold spells reordered; seed <code>default_rng([12, 11, 3, 0])</code>) and of F3 draw 0 (new gold lengths; seed <code>default_rng([12, 11, 6, 0])</code>). In-or-out: 1 = proxy portfolio, 0 = sleeve; gold: 1 = BUY, 0 = SELL:</p>
{table(ex_rows, ["Week", "Date", "Real in-or-out", "F2 draw 0", "F1 draw 0", "Real gold", "F4 draw 0", "F3 draw 0"])}
<p><b>10. How one F1 draw is made.</b> It keeps the {ex['k_in']} in-spells and {ex['k_out']} out-spells, the first state ({"in" if rule[b][0] else "out"}) and the totals ({ex['S_in']} weeks in, {ex['S_out']} out), and draws every length as an integer from {ex['lo_in']} to {ex['hi_in']} (in) or {ex['lo_out']} to {ex['hi_out']} (out; each bound is the series' own: the lower is min(2, shortest spell of the state), the upper its longest spell), every allowed set of lengths equally likely. With c(m, t) the number of ways to write t weeks as m lengths in the bounds, c(0, 0) = 1 and c(m, t) = Σ over x of c(m − 1, t − x), the parts are drawn one at a time: with m parts and t weeks left, P(length = x) = c(m − 1, t − x) ÷ c(m, t). The uniform number u is <code>rng.random()</code> and the length is the first x whose cumulative weight exceeds u × c(m, t). In-spell parts come first, then out-spell parts, from the same generator. The real MAUc1 signal is then read in whatever weeks the draw is OUT; for A1 and A2 the same states are run with the sleeve fixed at 50/50.</p>
<div class="formula">allowed in-tuples  c({ex['k_in']}, {ex['S_in']}) = {int(ex['ways_in']):,}   (count_table.json: {int(ex['ways_in_table']):,})
allowed out-tuples c({ex['k_out']}, {ex['S_out']}) = {int(ex['ways_out']):,}   (count_table.json: {int(ex['ways_out_table']):,})</div>
<p>The first step of draw 0, in-spell 1: m = {ex['k_in']} parts and t = {ex['S_in']} weeks left, so the {len(samplers['sampler|first'][1])} candidate lengths {ex['lo_in']} … {ex['hi_in']} have weights c({ex['k_in'] - 1}, {ex['S_in']} − x). u = {s1_['u']:.6f}; u × c({ex['k_in']}, {ex['S_in']}) = {s1_['u'] * s1_['total']:,.0f} falls in the weight of length {s1_['x']}, so the first in-spell is {s1_['x']} weeks.</p>
<figure class="card hv"><figcaption>Weights of the candidate first in-spell lengths for F1 draw 0 (m = {ex['k_in']}, t = {ex['S_in']}); the black line is the length drawn. Hover: the crosshair shows the length and the weight at the pointer, the tooltip the weight and its share of c({ex['k_in']}, {ex['S_in']}).</figcaption>{samplers['sampler|first'][0]}<div class="tip wrap" hidden></div></figure>
<p>All {len(steps)} steps of F1 draw 0, replayed here from the seed with the same rule: {steps_chip}.</p>
{table(step_tab(steps), ["Spell", "Part", "Parts left m", "Weeks left t", "u", "c(m, t)", "Length drawn", "c(m−1, t−x)", "P(x)"])}
<p>F1 draw 0's in-spell lengths are {", ".join(map(str, lens(Z['io|N4.10'][0], 1)))} (the rule's: {", ".join(map(str, rin[b]))}) and its out-spell lengths {", ".join(map(str, lens(Z['io|N4.10'][0], 0)))} (the rule's: {", ".join(map(str, rout[b]))}). With the timed sleeve it earns {pc(ex['d0']['F1']['cagr'], 2)} a year with a worst fall of {pc(ex['d0']['F1']['max_dd'], 2)}, invested for {ex['d0']['F1']['sessions']} sessions (the rule: {rule_sess[b]}; F2 draw 0: {ex['d0']['F2']['sessions']}), the same {int(x0['F1'].invested_weeks)} weeks; with the 50/50 sleeve {pc(ex['d0']['F1f']['cagr'], 2)} and {pc(ex['d0']['F1f']['max_dd'], 2)}.</p>
<p><b>11. How one F3 draw is made.</b> The same sampler, with the gold series' spells: {ex['k_buy']} BUY-spells and {ex['k_sell']} SELL-spells, first state {"BUY" if gold[b][0] else "SELL"}, totals {ex['S_buy']} weeks BUY and {ex['S_sell']} SELL; BUY lengths are integers from {ex['lo_buy']} to {ex['hi_buy']}, SELL lengths from {ex['lo_sell']} to {ex['hi_sell']} (the real series' shortest and longest spells, computed before any return was read), BUY lengths first, then SELL, from <code>default_rng([12, 11, 6, 0])</code>. The real in-or-out switch is kept, so the book holds the proxy portfolio in exactly the rule's weeks and only the split of its sleeve moves.</p>
<div class="formula">allowed BUY-tuples  c({ex['k_buy']}, {ex['S_buy']}) = {int(ex['ways_buy']):,}   (count_table.json: {int(ex['ways_buy_table']):,})
allowed SELL-tuples c({ex['k_sell']}, {ex['S_sell']}) = {int(ex['ways_sell']):,}   (count_table.json: {int(ex['ways_sell_table']):,})</div>
<p>The first step of F3 draw 0, BUY-spell 1: m = {ex['k_buy']}, t = {ex['S_buy']}; u = {sg1['u']:.6f}; u × c({ex['k_buy']}, {ex['S_buy']}) = {sg1['u'] * sg1['total']:,.0f} falls in the weight of length {sg1['x']}, so the first BUY-spell is {sg1['x']} weeks.</p>
<figure class="card hv"><figcaption>Weights of the candidate first BUY-spell lengths for F3 draw 0 (m = {ex['k_buy']}, t = {ex['S_buy']}); the black line is the length drawn. Hover as above.</figcaption>{samplers['sampler|first_g'][0]}<div class="tip wrap" hidden></div></figure>
<p>All {len(stepsg)} steps of F3 draw 0, replayed from the seed: {steps_chip_g}.</p>
{table(step_tab(stepsg), ["Spell", "Part", "Parts left m", "Weeks left t", "u", "c(m, t)", "Length drawn", "c(m−1, t−x)", "P(x)"])}
<p>F3 draw 0's BUY lengths are {", ".join(map(str, lens(Z['gold|N4.10-g'][0], 1)))} (the real: {", ".join(map(str, gbuy[b]))}) and its SELL lengths {", ".join(map(str, lens(Z['gold|N4.10-g'][0], 0)))} (the real: {", ".join(map(str, gsell[b]))}). It earns {pc(ex['d0']['F3']['cagr'], 2)} a year with a worst fall of {pc(ex['d0']['F3']['max_dd'], 2)} and makes {ex['d0']['F3']['sleeve_trades']} sleeve trades (the rule: {bk_(b)['sleeve_trades']}); F4 draw 0 earns {pc(ex['d0']['F4']['cagr'], 2)}, worst fall {pc(ex['d0']['F4']['max_dd'], 2)}, {ex['d0']['F4']['sleeve_trades']} sleeve trades.</p>
<p><b>12. The ranking.</b> A1 (50/50 rule against F1 run with the 50/50 sleeve): the rule's CAGR beat {rk_['F1f']['worse']:,} of {rk_['F1f']['draws']:,} draws, tied {rk_['F1f']['tied']}, and was beaten by {rk_['F1f']['better']}: percentile = ({rk_['F1f']['worse']} + 0.5 × {rk_['F1f']['tied']}) ÷ {rk_['F1f']['draws']:,} × 100 = <b>{rk_['F1f']['percentile']:.2f}</b>; p-value = (1 + {rk_['F1f']['better']} + {rk_['F1f']['tied']}) ÷ ({rk_['F1f']['draws']:,} + 1) = {rk_['F1f']['p']:.4f}. Against F2 with the 50/50 sleeve: percentile <b>{rk_['F2f']['percentile']:.2f}</b>, p = {rk_['F2f']['p']:.4f}.
C1 (timed rule against F1): beat {rk_['F1']['worse']:,}, tied {rk_['F1']['tied']}, beaten by {rk_['F1']['better']}: percentile <b>{rk_['F1']['percentile']:.2f}</b>, p = {rk_['F1']['p']:.4f}; against F2 <b>{rk_['F2']['percentile']:.2f}</b>, p = {rk_['F2']['p']:.4f}. C3 (against F3): beat {rk_['F3']['worse']:,}, tied {rk_['F3']['tied']}, beaten by {rk_['F3']['better']}: percentile <b>{rk_['F3']['percentile']:.2f}</b>, p = {rk_['F3']['p']:.4f}; against F4 <b>{rk_['F4']['percentile']:.2f}</b>, p = {rk_['F4']['p']:.4f}.</p>

<h2 id="headline">Headline</h2>
<p>A1 and A2, Part A: the rule with the sleeve fixed at 50/50 against {ND:,} random in-or-out timings (F1 free lengths decides, F2 spell shuffle beside), every draw run with the sleeve fixed at 50/50. After 20.8 bps, window {start3} → {end_date}. Holm p = Holm-adjusted over the six criteria.</p>
{table(head_a, ["Book", "Hold proxy CAGR", "50/50 rule CAGR", "F1 (50/50) median", "Edge over F1 median", "A1: pct vs F1", "p", "Holm p", "F2 (50/50) median", "pct vs F2", "p", "Hold proxy worst fall", "50/50 rule worst fall", "F1 (50/50) median", "A2: pct vs F1", "p", "Holm p", "F2 (50/50) median", "pct vs F2", "p"])}
<p>C1 and C2, Part B: the MAUc1-timed rule against {ND:,} random in-or-out timings of each kind (F1 decides, F2 beside), the real MAUc1 signal in every draw.</p>
{table(head_c, ["Book", "Hold proxy CAGR", "Timed rule CAGR", "F1 median", "Edge over F1 median", "C1: pct vs F1", "p", "Holm p", "F2 median", "pct vs F2", "p", "Hold proxy worst fall", "Timed rule worst fall", "F1 median", "C2: pct vs F1", "p", "Holm p", "F2 median", "pct vs F2", "p"])}
<p>C3 and C4, the gold timing: the same timed rule against {ND:,} random gold timings of each kind (F3 free lengths decides, F4 spell shuffle beside), the real in-or-out switch in every draw.</p>
{table(head_g, ["Book", "Rule CAGR", "F3 median", "Edge over F3 median", "C3: pct vs F3", "p", "Holm p", "F4 median", "pct vs F4", "p", "Rule worst fall", "F3 median", "C4: pct vs F3", "p", "Holm p", "F4 median", "pct vs F4", "p"])}
<h3>Before and after cost, and the comparators ({start3} → {end_date})</h3>
{table(cost_rows, ["Book", "Strategy", "0 bps CAGR", "0 bps worst fall", "20.8 CAGR", "20.8 worst fall", "50 CAGR", "50 worst fall"])}
<p class="cap">The comparators are benchmarks, not nulls. Hold the proxy: the engine with the decision fixed IN (quarterly resets). The constant mixes hold the rule's average share ({100 * int(rule[B0].sum()) / weeks[B0]:.1f}%, invested weeks ÷ weeks) in the proxy portfolio all the time and rebalance at every decision, with a 50/50 non-proxy share and with a MAUc1-timed one; the 100% sleeves are the other end; the 50/50-sleeve rule is Part A's rule, so the gap to the timed rule is the sleeve's effect; each single index is held with no resets. There is no published-NAV comparator (the parents' NAVs start on 2019-01-02).</p>

<h2 id="perbook">Per book</h2><div class="legend">{legend}</div>{curves_html}
<h2 id="nulls">Null distributions, each deciding null with the null beside it overlaid</h2>
<p>For each book the {ND:,} after-cost CAGRs and maximum drawdowns, on the same bins: first the in-or-out timing with the 50/50 sleeve (A1, A2), then the in-or-out timing with the timed sleeve (C1, C2), then the gold timing (C3, C4) (blue = the free-length null, orange = the spell shuffle). Black line = the rule (the 50/50 rule in the first chart), dashed = each null's median. The gold nulls are much narrower: they move only the sleeve's split. Window {start3} → {end_date}.</p>{hists}
<h2 id="lengths">Spell lengths of the draws against the real series'</h2>
<p>Every spell of the {ND:,} draws, in weeks. The shuffles (F2, F4) can only reuse the real series' own lengths (orange spikes); F1 spreads in-or-out lengths over the bounds of each state, F3 spreads gold lengths over the BUY and SELL bounds, within the totals.</p>{lenhtml}
<h2 id="held">What each null holds and randomises</h2>
<p>The two tables below are copied from <code>T09.md</code> section 2 (frozen).</p>{null_tables}
{regime}
<h2 id="robust">Robustness (decides the finding's status, not the verdict)</h2>
<p><b>R1</b>, the six percentiles at 0, 20.8 and 50 bps ({start3} → {end_date}) against the deciding null (F1 with the 50/50 sleeve for A1 and A2, F1 for C1 and C2, F3 for C3 and C4); pass mark 90 in at least 3 of 4:</p>
{table(rob1_dec, ["Book"] + [f"{cr} {c}" for cr, *_ in CRIT for c in ("0", "20.8", "50")])}
<p>Against the null beside it (F2 with the 50/50 sleeve for A1 and A2, F2 for C1 and C2, F4 for C3 and C4):</p>
{table(rob1_bes, ["Book"] + [f"{cr} {c}" for cr, *_ in CRIT for c in ("0", "20.8", "50")])}
<p class="cap">At ≥ 90 in the books listed (of {len(BOOKS)}), against the deciding null: {"; ".join(f"{cr} at 0 bps {sum(bk_(b_)[f'{TAG_OF[cr][0]}_pct_{TAG_OF[cr][2]}_0'] >= 90 for b_ in BOOKS)}, at 20.8 {V[cr]}, at 50 {sum(bk_(b_)[f'{TAG_OF[cr][0]}_pct_{TAG_OF[cr][2]}_50'] >= 90 for b_ in BOOKS)}" for cr, *_ in CRIT)}.</p>
<p><b>R2 and R3</b>, A1, C1 and C3 percentiles at 20.8 bps. R2: the cash leg of the sleeve (the whole non-proxy share for Part A's cash half, the cash leg for Part B) is the desk's LIQUIDCASE file, full window. <b>R2 is a null result by construction:</b> LIQUIDCASE's daily returns equal LBES's in this window to the precision printed in <code>audit.json</code> ({(au.get('data') or {}).get('cash', {}).get('lbes_vs_liquidcase_max_abs_daily_return_diff_in_window')}), so it cannot change a number. R3: the window starting {r3_start} → {end_date} with its own spells, totals and nulls (bounds from that window's series); NOT REPORTABLE if fewer than 4 round trips or fewer than 4 gold spells with an OUT week.</p>
{table(rob2_rows, ["Book", "R2 A1 (F1, 50/50)", "R2 C1 (F1)", "R2 C3 (F3)", "R2 50/50 rule CAGR", "R2 timed rule CAGR", "R3 A1 (F1, 50/50)", "R3 C1 (F1)", "R3 C3 (F3)", "R3 50/50 rule CAGR", "R3 timed rule CAGR", "R3 reportability"])}
<p class="cap">At ≥ 90: R2 {V['R2_A1']} of {len(BOOKS)} for A1, {V['R2_C1']} for C1 and {V['R2_C3']} for C3; R3 {V['R3_A1']} for A1, {V['R3_C1']} for C1 and {V['R3_C3']} for C3.</p>
<p><b>R4</b>, agreement of the paired nulls on this window (20.8 bps, {start3} → {end_date}; no pass mark): the rule's CAGR and drawdown percentile under each null and each null's spread of after-cost CAGR. In-or-out pairs (the first with the 50/50 sleeve, F1f and F2f, against the 50/50 rule):</p>
{table(r4(("F1f", "F2f", "F1", "F2")), r4_cols(("F1f", "F2f", "F1", "F2")))}
<p>Gold pair:</p>
{table(r4(("F3", "F4")), r4_cols(("F3", "F4")))}
{ref_html}
<p><b>R5</b>, both timings random (F5: an F1 draw and an F3 draw of the same id; 20.8 bps; reported only):</p>
{table(r5_rows, ["Book", "Rule CAGR", "F5 median", "F5 SD (pp)", "CAGR pct", "p", "Drawdown pct", "p"])}
<p><b>R6</b>, paired contrast (descriptive, no pass mark): every F1 and F2 draw is also run with the sleeve fixed at 50/50. dCAGR = CAGR(timed) − CAGR(50/50) on the same states; dDD = worst fall (timed) − worst fall (50/50), positive = shallower with timing. The percentile ranks the rule's change among the draws' changes.</p>
{table(r6_rows, ["Book", "Rule dCAGR (pp)", "Rule dDD (pp)", "F1 median dCAGR", "pct", "share > 0", "F1 median dDD", "pct", "share > 0", "F2 median dCAGR", "pct", "share > 0", "F2 median dDD", "pct", "share > 0"])}
<p><b>R7</b>, gold-proxy sensitivity (descriptive, 20.8 bps): the rule re-run (a) with the GOLDBEES fills before {GB_FIRST} at the proxy's close instead of its OHLC4, and (b) with the sleeve's gold weight held at 50% for decisions dated before {GB_FIRST}.</p>
{table(r7_rows, ["Book", "Rule CAGR", "Rule worst fall", "(a) CAGR", "change", "(a) worst fall", "change", "(b) CAGR", "change", "(b) worst fall", "change"])}
<h3>Sessions invested per draw (weeks are held exactly, sessions are not; F1 and F2, full window, 20.8 bps)</h3>
{table(ses_rows, ["Book", "Rule", "Sessions in window", "F1 min", "median", "max", "F2 min", "median", "max"])}
<h3>Sleeve trades per gold draw (F3 and F4; draws that flip while IN never trade)</h3>
{table(str_rows, ["Book", "Rule", "F3 min", "median", "max", "F4 min", "median", "max"])}
<h3>Power</h3><p>In-or-out nulls (round trips of the switch; F1f and F2f are the nulls run with the 50/50 sleeve):</p>{table(mde_io, ["Book", "Round trips"] + [f"{t_} {c}" for t_ in ("F1f", "F2f", "F1", "F2") for c in ("SD CAGR (pp)", "MDE CAGR (pp)", "SD worst fall (pp)", "MDE worst fall (pp)")])}
<p>Gold nulls (gold spells that contain an OUT week):</p>{table(mde_g, ["Book", "Gold spells with an OUT week"] + [f"{t_} {c}" for t_ in ("F3", "F4") for c in ("SD CAGR (pp)", "MDE CAGR (pp)", "SD worst fall (pp)", "MDE worst fall (pp)")])}
<p class="cap">MDE = 2.8 × the SD of the draws (80% power, two-sided 5%), per null. The numbers did not exist when the pre-registration was written; its thresholds do not depend on them.</p>

<h2 id="defs">Definitions</h2>
<ul><li><b>Percentile</b>: (draws worse + 0.5 × draws tied) ÷ draws × 100, ties equal within a relative 1e-12. <b>p-value</b>: (1 + draws at least as good) ÷ (draws + 1). <b>Holm p</b>: the Holm step-down adjustment of the six deciding p-values of a book.</li>
<li><b>CAGR</b>: NAV_end^(252 ÷ (sessions − 1)) − 1, daily NAV, after cost. <b>Worst fall</b> (maximum drawdown): the most negative NAV ÷ running peak − 1.</li>
<li><b>Proxy portfolio</b>: the Nifty 100, Midcap 100 and Smallcap 100 at a book's fixed weights, reset to those weights on entry and at the first session of each quarter while held. <b>MAUc1</b>: the weekly supertrend (period W, multiplier 2) of MCX gold futures (D24b). <b>Gold signal g</b>: its SIGN, BUY or SELL, from the latest weekly row dated on or before the decision date. <b>Sleeve</b>: while the rule is OUT, GOLDBEES and cash, 50/50 (Part A) or 80/20 when g is BUY and 20/80 when SELL (Part B), changed only when g changes.</li>
<li><b>F1</b> in-or-out N4.10 with the real gold signal (seed <code>default_rng([12, 6, id])</code>); <b>F2</b> in-or-out N4.9 spell shuffle (<code>[12, 3, id]</code>); <b>F3</b> gold N4.10-g with the real switch (<code>[12, 11, 6, id]</code>); <b>F4</b> gold N4.9-g spell shuffle (<code>[12, 11, 3, id]</code>); <b>F5</b> an F1 and an F3 draw together (robustness only). F1 and F2 are also run with the sleeve fixed at 50/50 (F1f, F2f in the tables), the nulls of A1 and A2.</li>
<li><b>N4.10 free-length random timing</b>: the same number of spells of each state and the same totals of weeks in each, every length an integer between the series' own bounds for that state, uniform over all allowed ordered tuples, drawn exactly by a dynamic programme, no rejection. <b>N4.9 spell shuffle</b>: the real series' spells of each state reordered among themselves. All nulls start in the real series' first state.</li>
<li><b>Weeks versus sessions</b>: the in-or-out nulls hold invested weeks exactly; a week has 3 to 5 sessions, so invested sessions differ by draw and are reported.</li>
<li><b>MDE</b>: 2.8 × the SD of the draws' CAGR (or maximum drawdown). <b>R3 window</b>: {r3_start} → {end_date}.</li></ul>
<p class="meta">Built by <code>tests/T09/report.py</code> from <code>evidence/{E(ev.name)}/</code>. Methods: <code>evidence/METHODS.md</code>. Checked by <code>check_page.py</code>.</p>
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
