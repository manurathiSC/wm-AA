"""Build report.html for T12 from shipped evidence only (AGENT.md R10). Fork of tests/T07/report.py (copied, not imported).

    python tests/T12/report.py [--run headline]              writes tests/T12/evidence/report.html
    python tests/T12/report.py --evidence DIR [--out DIR]    another evidence directory (e.g. a synthetic one); the page and
                                                             analysis.log are then looked up and written in --out (default DIR)

Every number on the page is computed here from evidence/<run>/ (decisions.csv, events.csv, event_stocks.csv, stats.csv, draws.csv, daily_nav.csv,
draw_drops.npz, r5_tag_error.csv, r6_links.csv, r7_flagged_days.csv, regression.json, controls_*.csv/json, inputs.csv, audit.json, verify_t12.json),
from evidence/episodes/ (episodes.py, post hoc) and from T07's shipped evidence (tests/T07/evidence/headline/stats.csv, draws.csv; the comparison) and,
if it exists, T11's (tests/T11/evidence/headline/stats.csv; context); for the gate verdicts, the 'Gates:' line of analysis.log; the caveats of the tag
data are read from T12.md section 3. The same numbers are written into the page's embedded JSON blocks (page-data, lines-data, bars-data, band-data,
regime-data) so check_page.py can recompute them independently.
There is no published NAV before 2019-01-02: every chart that draws 'hold the parent' says it is a rebuild (PARENT_NOTE).
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


def v6_xmax(K: int, p: float = 0.10, alpha: float = 0.05 / 4) -> int:
    """T12.md section 2, V6: largest X with P(Binomial(K, p) >= X) >= alpha (one-sided, 4 books). K = 100: 17."""
    tail = 0.0
    for X in range(K, -1, -1):
        tail += math.comb(K, X) * p ** X * (1 - p) ** (K - X)
        if tail >= alpha:
            return X
    return K
R6_BOOKS = ["SCMO_0007", "SCMO_0010"]
SEED = 15
T0_DATE, END_DATE, R2_START = "2014-09-01", "2019-01-02", "2015-01-02"
PARENT_NOTE = "rebuilt from the parent's baskets and Eikon prices; no published NAV exists before 2019-01-02"
PRIMARY = 20.8
COSTS = (0.0, PRIMARY, 50.0)
E = html.escape
BANDS = ["Large", "Mid", "Small and below"]
SIGS = ["Nifty100", "MC100", "SC100"]
SIGLAB = {"Nifty100": "Nifty 100", "MC100": "Midcap 100", "SC100": "Smallcap 100"}
C6, C8 = "#2a6fdb", "#c9811a"
COL = {"segment": "#2a6fdb", "whole_book": "#1c1f24", "parent": "#8a8f98", "constant_mix": "#c9811a"}
LAB = {"segment": "Segment rule (this test)", "whole_book": "Whole-book switch", "parent": "Hold the parent (rebuilt, no published NAV)", "constant_mix": "Constant mix (same average exposure)"}
BKCOL = {"SCMO_0003": "#2a6fdb", "SCMO_0007": "#c9811a", "SCMO_0010": "#2f9e6e", "SCMO_0029": "#6b4fbb"}
BCOL = ["#6b4fbb", "#c9811a", "#2f9e6e"]  # Large, Mid, Small and below
SECSTATS = ("cagr", "max_dd", "calmar", "vol", "ulcer", "days_below_10pct", "longest_underwater")
HIGHER_BETTER = {"cagr": True, "max_dd": True, "calmar": True, "vol": False, "ulcer": False, "days_below_10pct": False, "longest_underwater": False}
DOWNSAMPLE = 5  # growth and drawdown charts: every 5th session
RG_STEP = 3     # regime chart lines: every 3rd session


# ── small helpers ─────────────────────────────────────────────────────────────
def asbool(s):
    return s.astype(str).str.strip().str.lower().isin(["true", "1", "1.0"]).values


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


def mbb_se(nav_a, nav_b, seed, nboot=1000, blk=20):
    ra, rb = np.log(nav_a[1:] / nav_a[:-1]), np.log(nav_b[1:] / nav_b[:-1])
    n = len(ra)
    nb = int(math.ceil(n / blk))
    rg = np.random.default_rng(seed)
    st = rg.integers(0, n - blk + 1, size=(nboot, nb))
    ix = (st[:, :, None] + np.arange(blk)[None, None, :]).reshape(nboot, -1)[:, :n]
    yrs = n / 252
    return float((np.expm1(ra[ix].sum(1) / yrs) - np.expm1(rb[ix].sum(1) / yrs)).std(ddof=1))


def bitsums(w):
    s = np.zeros(1)
    for x in w:
        s = np.concatenate([s, s + x])
    return s


def allowed_set(w_sorted, D, tau):
    return np.flatnonzero(np.abs(bitsums(w_sorted) - D) <= tau + 1e-12)


def pc(x, d=1):
    return f"{100 * x:.{d}f}%"


def pcs(x, d=1):
    return "" if x is None else pc(x, d)


def f1(x):
    return "" if x is None else f"{x:.1f}"


def fmt_table(rows, cols, cls=""):
    th = "".join(f"<th>{E(c)}</th>" for c in cols)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f'<div class="tw"><table class="{cls}"><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table></div>'


table = fmt_table


def approved_rows():
    txt = (AA / "data" / "APPROVED_DATA.md").read_text(encoding="utf-8")
    asof = re.search(r"\*\*As of: (\d{4}-\d{2}-\d{2})", txt)
    tab = txt[txt.index("<!-- approved-table:start -->"):txt.index("<!-- approved-table:end -->")]
    rows = []
    for l in tab.splitlines():
        if l.startswith("|") and not l.startswith("|---") and not l.startswith("| Status"):
            c = [x.strip() for x in l.strip().strip("|").split("|")]
            rows.append({"status": c[0], "id": c[1], "file": c[2], "through": c[3], "sha": c[4]})
    return (asof.group(1) if asof else None), rows


def find_key(obj, names):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if str(k).lower() in names and not isinstance(v, (dict, list)):
                return v
        for v in obj.values():
            r = find_key(v, names)
            if r is not None:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = find_key(v, names)
            if r is not None:
                return r
    return None


def per_book(obj, book):
    """The dict of one book from {book: {...}}, {'books': {book: {...}}} or [{'book': book, ...}]."""
    if isinstance(obj, dict):
        if book in obj and isinstance(obj[book], dict):
            return obj[book]
        for v in obj.values():
            if isinstance(v, (dict, list)):
                r = per_book(v, book)
                if r is not None:
                    return r
        if obj.get("book") == book:
            return obj
    elif isinstance(obj, list):
        for v in obj:
            r = per_book(v, book)
            if r is not None:
                return r
    return None


def md_plain(t):
    """The markdown of a caveat paragraph as plain text: no ** and no backticks."""
    return t.replace("**", "").replace("`", "")


# ── charts ────────────────────────────────────────────────────────────────────
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


def lp_range(allv):
    """Axis range of a log-point chart: whole multiples of 5 around the data, zero included."""
    return float(math.floor(min(allv.min(), 0.0) / 5) * 5 - 5), float(math.ceil(max(allv.max(), 0.0) / 5) * 5 + 5)


def svg_lines(did, series, dates, kind, w=640, h=250, cols=None, labs=None):
    """series: {name: array}; drawn every DOWNSAMPLE-th session (and the last). kind 'eq' = growth of 1 (log), 'dd' = drawdown from the running peak (linear),
    'lp' = log points (100 x ln of a ratio, linear). cols / labs: colour and label per series (default COL / LAB). Hover: LINES_JS."""
    cols, labs = cols or COL, labs or LAB
    idx = np.arange(0, len(dates), DOWNSAMPLE)
    if idx[-1] != len(dates) - 1:
        idx = np.append(idx, len(dates) - 1)
    log = kind == "eq"
    allv = np.concatenate([v[idx] for v in series.values()])
    if log:
        ymin, ymax = math.log(allv.min() * 0.97), math.log(allv.max() * 1.03)
    elif kind == "lp":
        ymin, ymax = lp_range(allv)
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
    elif kind == "lp":
        step = 5 if ymax - ymin <= 40 else (10 if ymax - ymin <= 100 else 20)
        t = math.ceil(ymin / step) * step
        while t <= ymax + 1e-9:
            out.append(f'<line x1="{L}" x2="{w - R}" y1="{y(t):.1f}" y2="{y(t):.1f}" class="grid"/><text x="{L - 4}" y="{y(t) + 3:.1f}" text-anchor="end" class="ax">{t:+.0f}</text>')
            t += step
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
        out.append(f'<polyline points="{pts}" fill="none" stroke="{cols[k]}" stroke-width="{2.2 if k == "segment" else (1.6 if kind == "lp" else 1.3)}" stroke-linejoin="round"/>')
    bot = h - B
    out.append('<g class="lc-hv" style="display:none" pointer-events="none">'
               f'<line class="lc-v" y1="{T}" y2="{bot}" stroke="var(--muted)" stroke-width="1"/>'
               f'<line class="lc-h" x1="{L}" x2="{w - R}" stroke="var(--muted)" stroke-width="1" stroke-dasharray="3 3"/>'
               + "".join(f'<circle class="lc-c" r="3.5" fill="{cols[k]}" stroke="var(--card)" stroke-width="1.5"/>' for k in series)
               + f'<g class="lc-yc"><rect x="0" y="-8" width="{L - 3}" height="16" rx="3" fill="var(--fg)"/><text x="{L - 7}" y="3.5" text-anchor="end" font-size="10" fill="var(--bg)" class="lc-yt"></text></g>'
               f'<g class="lc-xc"><rect y="{h - 19}" width="92" height="16" rx="3" fill="var(--fg)" class="lc-xr"/><text y="{h - 7.5}" text-anchor="middle" font-size="10" fill="var(--bg)" class="lc-xt"></text></g></g>')
    out.append(f'<rect class="lc-ov" x="{L}" y="{T}" width="{w - L - R}" height="{bot - T}" fill="transparent" style="cursor:crosshair;touch-action:none"/>')
    out.append("</svg>")
    data = {"w": w, "h": h, "L": L, "R": R, "T": T, "B": B, "lo": ymin, "hi": ymax, "log": log, "fmt": "x" if log else ("lp" if kind == "lp" else "pct"), "n": len(idx),
            "dates": [dates[i].strftime("%Y-%m-%d (%a)") for i in idx],
            "series": [{"k": k, "label": labs[k], "col": cols[k], "v": [round(float(v[i]), 4) for i in idx]} for k, v in series.items()]}
    return "".join(out), data


def svg_bars(did, edges, series, marks=(), xk="pct", yk="int", w=460, h=190, xticks=None, extra=None, binlab=None, yunit="draws", L=44):
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


def svg_bands(did, d, w=640, h=230):
    """Stacked bars, one per event: the share of the book's listed weight in Large (bottom), Mid and Small and below; a band whose signal is SELL is drawn faint (dropped).
    d holds the arrays (start, end, wt, on, ...); the hover (BANDS_JS) reads the same arrays."""
    L, R, T, B = 44, 8, 8, 24
    n = d["n"]
    X = lambda j: L + (w - L - R) * j / (n - 1)
    Y = lambda f: T + (h - T - B) * (1 - f)
    o = [f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="{E(did)}" class="chart bd" data-id="{E(did)}">']
    for t in (0, 0.25, 0.5, 0.75, 1.0):
        o.append(f'<line x1="{L}" x2="{w - R}" y1="{Y(t):.1f}" y2="{Y(t):.1f}" class="grid"/><text x="{L - 4}" y="{Y(t) + 3:.1f}" text-anchor="end" class="ax">{100 * t:.0f}%</text>')
    for i in range(len(d["start"])):
        x0, x1 = X(d["start"][i]), X(d["end"][i])
        acc = 0.0
        for bi in range(3):
            wt = d["wt"][i][bi]
            if wt > 0:
                o.append(f'<rect x="{x0:.2f}" y="{Y(acc + wt):.2f}" width="{max(x1 - x0, 0.4):.2f}" height="{(h - T - B) * wt:.2f}" fill="{BCOL[bi]}" opacity="{0.95 if d["on"][i][bi] else 0.28}"/>')
            acc += wt
    years = sorted({int(s_[:4]) for s_ in d["dates"]})
    for yr in years[::2]:
        i = next(k for k, s_ in enumerate(d["dates"]) if int(s_[:4]) == yr)
        o.append(f'<text x="{X(i):.1f}" y="{h - 6}" text-anchor="middle" class="ax">{yr}</text>')
    bot = h - B
    o.append('<g class="bd-hv" style="display:none" pointer-events="none">'
             f'<line class="bd-v" y1="{T}" y2="{bot}" stroke="var(--fg)" stroke-width="1"/>'
             f'<line class="bd-h" x1="{L}" x2="{w - R}" stroke="var(--muted)" stroke-width="1" stroke-dasharray="3 3"/>'
             '<circle class="bd-c" r="3.5" fill="var(--fg)" stroke="var(--card)" stroke-width="1.5"/><circle class="bd-c" r="3.5" fill="var(--fg)" stroke="var(--card)" stroke-width="1.5"/>'
             f'<g class="bd-yc"><rect x="0" y="-8" width="{L - 3}" height="16" rx="3" fill="var(--fg)"/><text x="{L - 7}" y="3.5" text-anchor="end" font-size="10" fill="var(--bg)" class="bd-yt"></text></g>'
             f'<g class="bd-xc"><rect y="{h - 19}" width="92" height="16" rx="3" fill="var(--fg)" class="bd-xr"/><text y="{h - 7.5}" text-anchor="middle" font-size="10" fill="var(--bg)" class="bd-xt"></text></g></g>')
    o.append(f'<rect class="bd-ov" x="{L}" y="{T}" width="{w - L - R}" height="{bot - T}" fill="transparent" style="cursor:crosshair;touch-action:none"/>')
    o.append("</svg>")
    d.update({"w": w, "h": h, "L": L, "R": R, "T": T, "B": B})
    return "".join(o), d


def svg_regime(did, d, w=760):
    """Growth-of-1 lines (log) with the disagreement stretches shaded, and below five strips: the three signals (filled = BUY), the share of the book the rule keeps, the whole-book switch (filled = IN).
    d holds the arrays; the strips are drawn from the weekly and event arrays that the hover (REGIME_JS) also reads."""
    N = d["N"]
    L, R, T, ph = 92, 62, 8, 200
    rowh, gap = 11, 4
    top = T + ph + 18
    nrow = 5
    h = top + nrow * (rowh + gap) + 18
    lo, hi = d["lo"], d["hi"]
    x = lambda i: L + (w - L - R) * i / (N - 1)
    y = lambda v: T + ph * (1 - (math.log(v) - lo) / (hi - lo))
    bot = top + nrow * (rowh + gap) - gap
    o = [f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="{E(did)}" class="chart rg" data-id="{E(did)}">']
    wk0 = d["wk0"]
    wend = wk0[1:] + [N - 1]
    for i, (a_, b_) in enumerate(zip(wk0, wend)):
        if d["wstr"][i] >= 0 and b_ > a_:
            o.append(f'<rect x="{x(a_):.1f}" y="{T}" width="{max(x(b_) - x(a_), 0.6):.1f}" height="{bot - T}" fill="{C8}" opacity="0.16"/>')
    for t in (1, 2, 4, 8, 16):
        if math.exp(lo) <= t <= math.exp(hi):
            o.append(f'<line x1="{L}" x2="{w - R}" y1="{y(t):.1f}" y2="{y(t):.1f}" class="grid"/><text x="{L - 4}" y="{y(t) + 3:.1f}" text-anchor="end" class="ax">{t:g}×</text>')
    for k, sw in (("parent", 1.2), ("whole", 1.7), ("rule", 2.4)):
        v = d[k]
        col = {"parent": COL["parent"], "whole": COL["whole_book"], "rule": COL["segment"]}[k]
        pts = " ".join("%.1f,%.1f" % (x(d["idx"][j]), y(v[j])) for j in range(len(v)))
        o.append(f'<polyline points="{pts}" fill="none" stroke="{col}" stroke-width="{sw}" stroke-linejoin="round"/>')
        o.append(f'<text x="{x(N - 1) + 5:.1f}" y="{y(v[-1]) + 3:.1f}" class="ax" style="fill:var(--fg)">{v[-1]:.1f}×</text>')
    labels = [SIGLAB[s_] for s_ in SIGS] + ["Rule share kept", "Whole-book IN"]
    fills = [BCOL[0], BCOL[1], BCOL[2], COL["segment"], COL["whole_book"]]
    for r_ in range(nrow):
        yy = top + r_ * (rowh + gap)
        o.append(f'<rect x="{L}" y="{yy}" width="{w - L - R}" height="{rowh}" fill="var(--line)" rx="2"/><text x="{L - 6}" y="{yy + rowh - 2}" text-anchor="end" class="ax">{labels[r_]}</text>')
        if r_ < 3:
            for i, (a_, b_) in enumerate(zip(wk0, wend)):
                if d["sg"][i][r_] == 1 and b_ > a_:
                    o.append(f'<rect x="{x(a_):.1f}" y="{yy}" width="{max(x(b_) - x(a_), 0.6):.1f}" height="{rowh}" fill="{fills[r_]}"/>')
        elif r_ == 3:
            es = d["es"]
            for i in range(len(es)):
                a_, b_ = es[i], (es[i + 1] if i + 1 < len(es) else N - 1)
                hh = rowh * d["ek"][i]
                if b_ > a_ and hh > 0:
                    o.append(f'<rect x="{x(a_):.1f}" y="{yy + rowh - hh:.2f}" width="{max(x(b_) - x(a_), 0.6):.1f}" height="{hh:.2f}" fill="{fills[r_]}"/>')
        else:
            for i, (a_, b_) in enumerate(zip(wk0, wend)):
                if d["wst"][i] == 1 and b_ > a_:
                    o.append(f'<rect x="{x(a_):.1f}" y="{yy}" width="{max(x(b_) - x(a_), 0.6):.1f}" height="{rowh}" fill="{fills[r_]}"/>')
    for yr in sorted({int(s_[:4]) for s_ in d["alldates"]}):
        i = next(k for k, s_ in enumerate(d["alldates"]) if int(s_[:4]) == yr)
        o.append(f'<text x="{x(i):.1f}" y="{h - 5}" text-anchor="middle" class="ax">{yr}</text>')
    o.append('<g class="rg-hv" style="display:none" pointer-events="none">'
             f'<line class="rg-v" y1="{T}" y2="{bot}" stroke="var(--muted)" stroke-width="1"/>'
             f'<line class="rg-h" x1="{L}" x2="{w - R}" stroke="var(--muted)" stroke-width="1" stroke-dasharray="3 3"/>'
             + "".join(f'<circle class="rg-c" r="4" fill="{c}" stroke="var(--card)" stroke-width="2"/>' for c in (COL["segment"], COL["whole_book"], COL["parent"]))
             + f'<g class="rg-yc"><rect x="0" y="-8" width="{L - 3}" height="16" rx="3" fill="var(--fg)"/><text x="{L - 7}" y="3.5" text-anchor="end" font-size="10" fill="var(--bg)" class="rg-yt"></text></g>'
             f'<g class="rg-xc"><rect y="{h - 19}" width="92" height="16" rx="3" fill="var(--fg)" class="rg-xr"/><text y="{h - 7.5}" text-anchor="middle" font-size="10" fill="var(--bg)" class="rg-xt"></text></g></g>')
    o.append(f'<rect class="rg-ov" x="{L}" y="{T}" width="{w - L - R}" height="{bot - T}" fill="transparent" style="cursor:crosshair;touch-action:none"/>')
    o.append("</svg>")
    d.update({"w": w, "h": h, "L": L, "R": R, "T": T, "ph": ph})
    return "".join(o), d


TIPPOS = """  var fr=fig.getBoundingClientRect(),px=e.clientX-fr.left+14,py=e.clientY-fr.top+14;
  if(px+tip.offsetWidth>fr.width)px=e.clientX-fr.left-tip.offsetWidth-14;
  if(py+tip.offsetHeight>fr.height)py=Math.max(0,e.clientY-fr.top-tip.offsetHeight-14);
  px=Math.max(0,Math.min(px,fr.width-tip.offsetWidth));tip.style.left=px+'px';tip.style.top=py+'px';"""

LINES_JS = """(function(){
var all=JSON.parse(document.getElementById('lines-data').textContent);
function fx(d,v){return d.fmt==='pct'?(100*v).toFixed(1)+'%%':d.fmt==='lp'?(v>=0?'+':'')+v.toFixed(1)+' log pts':v.toFixed(2)+'\\u00d7'}
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
function f(k,v){if(k==='si'){var a=Math.abs(v);return a>=1e12?(v/1e12).toFixed(1)+'tn':a>=1e9?(v/1e9).toFixed(1)+'bn':a>=1e6?(v/1e6).toFixed(1)+'m':a>=1e3?(v/1e3).toFixed(1)+'k':Math.round(v)+''}if(k==='pct')return (100*v).toFixed(1)+'%%';if(k==='wk')return Math.round(v)+' wk';if(k==='int')return Math.round(v).toLocaleString('en-US');return v.toFixed(4)}
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
  if(d.extra&&d.extra[b])s+='<span class="sub">'+d.extra[b]+'</span>';
  for(var m=0;m<d.marks.length;m++){var M=d.marks[m];s+='<br>'+M.label+': <b>'+f(d.xk,M.x)+'</b> '+M.txt+(M.x>=d.edges[b]&&M.x<d.edges[b+1]?' (in this bin)':'')}
  tip.innerHTML=s;tip.hidden=false;
%s
 }
 function out(){g.style.display='none';tip.hidden=true}
 ov.addEventListener('pointermove',move);ov.addEventListener('pointerdown',move);ov.addEventListener('pointerleave',out);
});
})();""" % TIPPOS

BANDS_JS = """(function(){
var all=JSON.parse(document.getElementById('band-data').textContent);
var NAMES=['Large','Mid','Small and below'],SIGN=['Nifty 100','Midcap 100','Smallcap 100'],COLS=['#6b4fbb','#c9811a','#2f9e6e'];
Array.prototype.forEach.call(document.querySelectorAll('svg.bd'),function(svg){
 var d=all[svg.getAttribute('data-id')],fig=svg.parentNode,tip=fig.querySelector('.tip'),g=svg.querySelector('.bd-hv'),ov=svg.querySelector('.bd-ov'),cs=svg.querySelectorAll('.bd-c'),q=function(c){return svg.querySelector(c)};
 function X(j){return d.L+(d.w-d.L-d.R)*j/(d.n-1)}
 function Y(f){return d.T+(d.h-d.T-d.B)*(1-f)}
 function move(e){
  var r=svg.getBoundingClientRect(),k=d.w/r.width,vx=(e.clientX-r.left)*k,vy=(e.clientY-r.top)*k;
  var j=Math.max(0,Math.min(d.n-1,Math.round((vx-d.L)/(d.w-d.L-d.R)*(d.n-1)))),x=X(j),i=0;
  while(i+1<d.start.length&&d.start[i+1]<=j)i++;
  g.style.display='';
  q('.bd-v').setAttribute('x1',x);q('.bd-v').setAttribute('x2',x);
  var wt=d.wt[i];cs[0].setAttribute('cx',x);cs[0].setAttribute('cy',Y(wt[0]));cs[1].setAttribute('cx',x);cs[1].setAttribute('cy',Y(wt[0]+wt[1]));
  var top=d.T,hgt=d.h-d.T-d.B;vy=Math.max(top,Math.min(top+hgt,vy));
  q('.bd-h').setAttribute('y1',vy);q('.bd-h').setAttribute('y2',vy);q('.bd-yc').setAttribute('transform','translate(0,'+vy+')');q('.bd-yt').textContent=(100*(1-(vy-top)/hgt)).toFixed(0)+'%%';
  var xr=q('.bd-xr'),xl=Math.max(0,Math.min(d.w-92,x-46));xr.setAttribute('x',xl);q('.bd-xt').setAttribute('x',xl+46);q('.bd-xt').textContent=d.dates[j];
  var s='<b>'+d.dates[j]+'</b><span class="sub">Event '+(i+1)+' of '+d.start.length+' ('+d.kind[i]+'), traded '+d.tdate[i]+', basket of '+d.beff[i]+'; holds until the next event.</span>';
  for(var b=2;b>=0;b--)s+='<br><i style="background:'+COLS[b]+'"></i>'+NAMES[b]+': <b>'+(100*wt[b]).toFixed(1)+'%%</b> of the book in '+d.nst[i][b]+' stock(s); '+SIGN[b]+' '+(d.on[i][b]?'BUY: kept':'SELL: dropped');
  s+='<br>Sent to the sleeve: <b>'+(100*d.s[i]).toFixed(1)+'%%</b> ('+d.ndrop[i]+' of '+d.nheld[i]+' stocks dropped)';
  tip.innerHTML=s;tip.hidden=false;
%s
 }
 function out(){g.style.display='none';tip.hidden=true}
 ov.addEventListener('pointermove',move);ov.addEventListener('pointerdown',move);ov.addEventListener('pointerleave',out);
});
})();""" % TIPPOS

REGIME_JS = """(function(){
var all=JSON.parse(document.getElementById('regime-data').textContent);
var SIGN=['Nifty 100','Midcap 100','Smallcap 100'];
function fx(v){return v.toFixed(2)+'\\u00d7'}
Array.prototype.forEach.call(document.querySelectorAll('svg.rg'),function(svg){
 var d=all[svg.getAttribute('data-id')],fig=svg.parentNode,tip=fig.querySelector('.tip'),g=svg.querySelector('.rg-hv'),ov=svg.querySelector('.rg-ov'),cs=svg.querySelectorAll('.rg-c'),q=function(c){return svg.querySelector(c)};
 var key=['rule','whole','parent'],lab=['Segment rule','Whole-book switch','Hold the parent (rebuilt, no published NAV)'],cols=['#2a6fdb','#1c1f24','#8a8f98'];
 function X(i){return d.L+(d.w-d.L-d.R)*i/(d.N-1)}
 function Y(v){return d.T+d.ph*(1-(Math.log(v)-d.lo)/(d.hi-d.lo))}
 function last(arr,v){var i=0;while(i+1<arr.length&&arr[i+1]<=v)i++;return i}
 function move(e){
  var r=svg.getBoundingClientRect(),k=d.w/r.width,vx=(e.clientX-r.left)*k,vy=(e.clientY-r.top)*k;
  var s_=Math.round((vx-d.L)/(d.w-d.L-d.R)*(d.N-1)),j=0,best=1e9;
  for(var m=0;m<d.idx.length;m++){var dd=Math.abs(d.idx[m]-s_);if(dd<best){best=dd;j=m}}
  var si=d.idx[j],x=X(si);
  g.style.display='';
  q('.rg-v').setAttribute('x1',x);q('.rg-v').setAttribute('x2',x);
  for(var n=0;n<3;n++){cs[n].setAttribute('cx',x);cs[n].setAttribute('cy',Y(d[key[n]][j]))}
  var inP=vy>=d.T&&vy<=d.T+d.ph,h=q('.rg-h'),yc=q('.rg-yc');
  h.style.display=yc.style.display=inP?'':'none';
  if(inP){h.setAttribute('y1',vy);h.setAttribute('y2',vy);yc.setAttribute('transform','translate(0,'+vy+')');q('.rg-yt').textContent=fx(Math.exp(d.lo+(1-(vy-d.T)/d.ph)*(d.hi-d.lo)))}
  var xr=q('.rg-xr'),xl=Math.max(0,Math.min(d.w-92,x-46));xr.setAttribute('x',xl);q('.rg-xt').setAttribute('x',xl+46);q('.rg-xt').textContent=d.dates[j].slice(0,10);
  var w=last(d.wk0,si),ev=last(d.es,si),t='<b>'+d.dates[j]+'</b>';
  for(var n=0;n<3;n++)t+='<br><i style="background:'+cols[n]+'"></i>'+lab[n]+': <b>'+fx(d[key[n]][j])+'</b>';
  t+='<br>Signals this week: ';
  for(var n=0;n<3;n++)t+=SIGN[n]+' '+(d.sg[w][n]?'BUY':'SELL')+(n<2?', ':'');
  t+='<br>Rule keeps <b>'+(100*d.ek[ev]).toFixed(1)+'%%</b> of the book in its stocks; whole-book switch: <b>'+(d.wst[w]?'IN':'OUT')+'</b>';
  t+='<span class="sub">'+(d.wstr[w]>=0?d.tips[d.wstr[w]]:'The three signals agree this week.')+'</span>';
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


def caveat_paragraph(doc: str):
    """The paragraph 'Caveats of the tag data, to be stated on the page' of T12.md section 3, split into its numbered caveats (plain text; six in T12)."""
    i = doc.index("**Caveats of the tag data, to be stated on the page**")
    j = doc.index("\n", i)
    para = md_plain(doc[i:j].replace("\r", ""))
    para = para.split("):", 1)[1].strip() if "):" in para else para
    parts = re.split(r"\s*\((\d)\)\s*", para)
    # parts = ['', '1', text1, '2', text2, ...]
    return [parts[k + 1].strip() for k in range(1, len(parts) - 1, 2)]


def flags(obj, key="pass") -> list:
    out_ = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == key and isinstance(v, bool):
                out_.append(v)
            out_ += flags(v, key)
    elif isinstance(obj, list):
        for v in obj:
            out_ += flags(v, key)
    return out_


def dicts(obj):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from dicts(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from dicts(v)


def v4_summary(reg):
    """regression.json read generically (its shape is not fixed by the contract): per part, comparisons, sessions, worst relative difference, verdict."""
    REL = ("max_rel_diff", "max_rel", "rel_diff", "max_relative_difference", "max_rel_difference", "worst_rel_diff")
    CNT = ("sessions", "dates_compared", "compared", "n_compared", "rows", "n", "sessions_compared")
    out_ = {}
    for part in ("v4a", "v4b"):
        blk = reg.get(part)
        r = {"present": blk is not None, "not_run": False, "reason": "", "comparisons": 0, "sessions": 0, "worst": 0.0, "bad": 0}
        if blk is not None:
            st_ = find_key(blk, {"status"})
            if isinstance(st_, str) and "not run" in st_.lower():
                r["not_run"], r["reason"] = True, str(find_key(blk, {"reason"}) or "")
            for d in dicts(blk):
                rel = next((d[k] for k in REL if k in d and isinstance(d[k], (int, float)) and not isinstance(d[k], bool)), None)
                if rel is None:
                    continue
                r["comparisons"] += 1
                r["worst"] = max(r["worst"], float(rel))
                cnt = next((d[k] for k in CNT if k in d and isinstance(d[k], (int, float)) and not isinstance(d[k], bool)), None)
                if cnt is not None:
                    r["sessions"] += int(cnt)
                    r["bad"] += int(cnt <= 0)
                r["bad"] += int(not (float(rel) <= 1e-12))
            r["bad"] += sum(1 for x in flags(blk) if not x)
        out_[part] = r
    blk = reg.get("v4c")
    r = {"present": blk is not None, "functions": 0, "changed": 0, "unexpected": 0}
    if blk is not None:
        for d in dicts(blk):
            if "expected" in d and isinstance(d["expected"], bool):
                r["functions"] += 1
                r["changed"] += int(bool(d.get("changed", False)))
                r["unexpected"] += int(not d["expected"])
        for d in dicts(blk):
            for k in ("unexpected", "n_unexpected", "unexpected_changes"):
                if k in d and isinstance(d[k], (int, float)) and not isinstance(d[k], bool):
                    r["unexpected"] += int(d[k])
        r["unexpected"] += sum(1 for x in flags(blk) if not x)
    if blk is not None:
        fn = blk.get("functions") if isinstance(blk, dict) else None
        if isinstance(fn, dict) and fn and all(isinstance(x, str) for x in fn.values()):
            r["functions"] += len(fn)
            r["changed"] += sum(1 for x in fn.values() if x.lower() == "changed")
        for k_ in ("unexpected_changes", "required_not_identical"):
            if isinstance(blk, dict) and isinstance(blk.get(k_), list):
                r["unexpected"] += len(blk[k_])
    out_["v4c"] = r
    blk = reg.get("v4d")
    r = {"present": blk is not None, "compared": 0, "mismatches": 0}
    if blk is not None:
        r["compared"] = int(find_key(blk, {"compared", "checked", "n_compared", "tags_compared", "rows_checked", "rows", "n"}) or 0)
        r["mismatches"] = int(find_key(blk, {"mismatches", "n_mismatches", "differ", "failures"}) or 0) + sum(1 for x in flags(blk) if not x)
    out_["v4d"] = r
    return out_


KIND_TXT = {
    "False start": "all SELL before and after: one or two indices turned BUY, the third never confirmed",
    "Shake-out": "all BUY before and after: one or two indices turned SELL, then all three were BUY again",
    "Decline": "all BUY before, all SELL after",
    "Recovery": "all SELL before, all BUY after",
    "Open at the window's edge": "the stretch touches the first or the last decision of the window",
}


def kind_of(before, after):
    """The same reading as episodes.py: where the stretch sits between the all-SELL (SSS) and all-BUY (BBB) states."""
    if before == "SSS" and after == "BBB":
        return "Recovery"
    if before == "SSS" and after == "SSS":
        return "False start"
    if before == "BBB" and after == "SSS":
        return "Decline"
    if before == "BBB" and after == "BBB":
        return "Shake-out"
    return "Open at the window's edge"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="headline")
    ap.add_argument("--evidence", default=None)
    ap.add_argument("--out", default=None, help="directory of report.html and analysis.log")
    ap.add_argument("--doc", default=str(HERE / "T12.md"))
    ap.add_argument("--episodes", default=None, help="episodes.py's output (default evidence/episodes for --run, DIR/episodes for --evidence)")
    ap.add_argument("--t07", default=str(AA / "tests" / "T07" / "evidence" / "headline"))
    ap.add_argument("--t11", default=str(AA / "tests" / "T11" / "evidence" / "headline"))
    ap.add_argument("--books", default=None, help="comma list; for engine smoke runs that hold fewer than the four books")
    a = ap.parse_args()
    if a.books:
        BOOKS[:] = a.books.split(",")
    R6B = [b for b in R6_BOOKS if b in BOOKS]
    ev_dir = Path(a.evidence) if a.evidence else HERE / "evidence" / a.run
    if a.out:
        logdir = outdir = Path(a.out)
    elif a.evidence:
        logdir = outdir = ev_dir
    else:
        logdir, outdir = HERE, ev_dir.parent
    ep_dir = Path(a.episodes) if a.episodes else ((ev_dir / "episodes") if a.evidence else HERE / "evidence" / "episodes")
    BNO = {"SCMO_0003": 0, "SCMO_0007": 1, "SCMO_0010": 2, "SCMO_0029": 3}

    dec = pd.read_csv(ev_dir / "decisions.csv", keep_default_na=False, na_values=[""])
    evt = pd.read_csv(ev_dir / "events.csv")
    es = pd.read_csv(ev_dir / "event_stocks.csv", keep_default_na=False, na_values=[""], dtype={"isin": str, "tag_detail": str})
    st = pd.read_csv(ev_dir / "stats.csv")
    dr = pd.read_csv(ev_dir / "draws.csv")
    nav = pd.read_csv(ev_dir / "daily_nav.csv", parse_dates=["date"])
    au = json.loads((ev_dir / "audit.json").read_text(encoding="utf-8"))
    ver = json.loads((ev_dir / "verify_t12.json").read_text(encoding="utf-8")) if (ev_dir / "verify_t12.json").exists() else None
    reg = json.loads((ev_dir / "regression.json").read_text(encoding="utf-8")) if (ev_dir / "regression.json").exists() else None
    zd = np.load(ev_dir / "draw_drops.npz")
    zdrops = {k_: zd[k_] for k_ in zd.files}
    inp, asof_inputs = read_inputs(ev_dir / "inputs.csv")
    if asof_inputs is None:
        asof_inputs = au.get("approved_data_as_of") or (au.get("data") or {}).get("approved_data_as_of")
    asof_file, arows = approved_rows()
    logp = logdir / "analysis.log"
    gate_line = None
    if logp.exists():
        mg = re.search(r"^Gates: (\{.*\}) ->", logp.read_text(encoding="utf-8"), re.M)
        gate_line = ast.literal_eval(mg.group(1)) if mg else None
    doc = Path(a.doc).read_text(encoding="utf-8")
    sha = doc.split("§1–§3 sha256:** `")[1].split("`")[0]
    caveats = caveat_paragraph(doc)
    r6l = pd.read_csv(ev_dir / "r6_links.csv", dtype={"linked_quote_id": str, "isin": str}, keep_default_na=False) if (ev_dir / "r6_links.csv").exists() else None
    r7d = pd.read_csv(ev_dir / "r7_flagged_days.csv", dtype={"isin": str}) if (ev_dir / "r7_flagged_days.csv").exists() else None

    evt["partial_b"] = asbool(evt["partial"])
    es["kept_b"] = asbool(es["kept"])
    evt = evt.sort_values(["book", "window", "event_no"]).reset_index(drop=True)
    EV = {(b, w): g.reset_index(drop=True) for (b, w), g in evt.groupby(["book", "window"])}
    KEYS = [(b, w) for b in BOOKS for w in ("full", "r2")] + [(b, "full_r6") for b in R6B]
    ES = {k_: es[(es.book == k_[0]) & (es.window == k_[1])].reset_index(drop=True) for k_ in KEYS}
    ROWMAP = {}
    for key, rows in ES.items():
        pos = {int(n): i for i, n in enumerate(EV[key].event_no.values)}
        ROWMAP[key] = np.array([pos[int(n)] for n in rows.event_no.values])
    S = lambda b, kind="segment", cost=PRIMARY, win="full", cash="lbes": st[(st.book == b) & (st.window == win) & (st.cash == cash) & (st.cost_bps == cost) & (st.kind == kind)].iloc[0]
    D = lambda b, typ, cost=PRIMARY, win="full", cash="lbes": dr[(dr.book == b) & (dr.window == win) & (dr.cash == cash) & (dr.cost_bps == cost) & (dr.draw_type == typ)].sort_values("draw_id")
    NUL = (("n46", "N4.6"), ("n48", "N4.8"))
    ND = int(len(D(BOOKS[0], "N4.6")))
    rule_dec = {b: dec[dec.book == b].sort_values("j").reset_index(drop=True) for b in BOOKS}
    weeks = {b: len(rule_dec[b]) for b in BOOKS}
    NAV = lambda b, run, cost=PRIMARY: nav[(nav.book == b) & (nav.cost_bps == cost) & (nav.run == run)].sort_values("date").reset_index(drop=True)
    cal = {b: NAV(b, "segment").date for b in BOOKS}
    nses = {b: len(cal[b]) for b in BOOKS}
    end_date = str(cal[BOOKS[0]].iloc[-1].date())
    start3 = str(cal[BOOKS[0]].iloc[0].date())
    r2_first = str(EV[(BOOKS[0], "r2")].trade_date.iloc[0])

    # weeks and stretches (weeks that have a trade date; the last decision, made at the final session, is never traded)
    WK = {}
    for b in BOOKS:
        d_ = rule_dec[b]
        wk0 = [0]
        for t in d_.trade_date.iloc[1:]:
            if pd.isna(t):
                break
            wk0.append(int(np.searchsorted(cal[b].values, np.datetime64(pd.Timestamp(t)))))
        nw = len(wk0)
        sg = [[int(d_.loc[j, f"sign_{s_}"] == "BUY") for s_ in SIGS] for j in range(nw)]
        dis = asbool(d_["disagree"])[:nw]
        wst = [int(asbool(d_["all_three_buy"])[j]) for j in range(nw)]
        wend = wk0[1:] + [nses[b] - 1]
        pat = ["".join("B" if x else "S" for x in sg[q]) for q in range(nw)]
        wstr, stretches = [-1] * nw, []
        j = 0
        while j < nw:
            if dis[j]:
                j2 = j
                while j2 + 1 < nw and dis[j2 + 1]:
                    j2 += 1
                stretches.append({"i": j, "k": j2, "s": wk0[j], "e": wend[j2], "from": str(d_.decision_date.iloc[j]), "to": str(d_.decision_date.iloc[j2]), "weeks": j2 - j + 1,
                                  "patterns": "→".join(dict.fromkeys(pat[q] for q in range(j, j2 + 1))),
                                  "kind": kind_of(pat[j - 1] if j > 0 else None, pat[j2 + 1] if j2 + 1 < nw else None)})
                for q in range(j, j2 + 1):
                    wstr[q] = len(stretches) - 1
                j = j2 + 1
            else:
                j += 1
        WK[b] = {"wk0": wk0, "sg": sg, "wst": wst, "wstr": wstr, "stretches": stretches, "dis": dis}

    # ── page data ─────────────────────────────────────────────────────────────
    data = {"run": ev_dir.name, "prereg_sha256": sha, "draws": ND, "as_of_file": asof_file, "as_of_inputs": asof_inputs, "end": end_date, "start": start3, "r2_first": r2_first,
            "weeks": {b: weeks[b] for b in BOOKS}, "books": {}, "gates": gate_line}
    SE = {}
    for b in BOOKS:
        s, sw_ = S(b), S(b, "whole_book")
        vr, vw = NAV(b, "segment").nav.values, NAV(b, "whole_book").nav.values
        SE[b] = mbb_se(vr, vw, [SEED, 20, BNO.get(b, BOOKS.index(b))])
        bb = {"cagr": float(s.cagr), "max_dd": float(s.max_dd), "end_nav": float(s.end_nav), "trades": int(s.trades), "cost_paid": float(s.cost_paid), "sessions_total": nses[b] - 1, "events": len(EV[(b, "full")]),
              "whole_cagr": float(sw_.cagr), "whole_dd": float(sw_.max_dd), "whole_trades": int(sw_.trades), "whole_cost": float(sw_.cost_paid), "c3_diff": float(s.cagr - sw_.cagr), "c3_se": SE[b]}
        for kind, kk in (("parent", "parent"), ("constant_mix", "mix"), ("sleeve100", "sleeve")):
            bb[f"{kk}_cagr"], bb[f"{kk}_dd"] = float(S(b, kind).cagr), float(S(b, kind).max_dd)
        for c in (0.0, 50.0):
            bb[f"c3_diff_{c:g}"] = float(S(b, cost=c).cagr - S(b, "whole_book", c).cagr)
        for win in ("full", "r2"):
            e_ = EV[(b, win)]
            d_ = rule_dec[b]
            if win == "r2":
                d_ = d_[pd.to_datetime(d_.decision_date) >= pd.Timestamp(str(EV[(b, "r2")].trade_date.iloc[0]))]
            x = asbool(d_["disagree"]).astype(int)
            n_st = int(((x[1:] == 1) & (x[:-1] == 0)).sum()) + int(len(x) > 0 and x[0] == 1)
            n_part = int(e_.partial_b.sum())
            bb[f"{win}_stretches"], bb[f"{win}_partial"], bb[f"{win}_events"], bb[f"{win}_weeks"], bb[f"{win}_dis_weeks"] = n_st, n_part, len(e_), int(len(x)), int(x.sum())
            bb[f"{win}_reportable"] = bool(n_st >= 5 and n_part >= 6)
        for nm, typ in NUL:
            n = D(b, typ)
            rc, rd = rank(s.cagr, n.cagr.values), rank(s.max_dd, n.max_dd.values)
            q = np.percentile(n.cagr.values, [5, 95])
            bb.update({f"{nm}_median_cagr": float(n.cagr.median()), f"{nm}_median_dd": float(n.max_dd.median()), f"{nm}_pct_cagr": rc["percentile"], f"{nm}_p_cagr": rc["p"], f"{nm}_pct_dd": rd["percentile"], f"{nm}_p_dd": rd["p"],
                       f"{nm}_worse": rc["worse"], f"{nm}_tied": rc["tied"], f"{nm}_better": rc["better"], f"{nm}_sd_cagr": float(n.cagr.std()), f"{nm}_sd_dd": float(n.max_dd.std()),
                       f"{nm}_mde_cagr_pp": float(280 * n.cagr.std()), f"{nm}_mde_dd_pp": float(280 * n.max_dd.std()), f"{nm}_p5_cagr": float(q[0]), f"{nm}_p95_cagr": float(q[1]),
                       f"{nm}_min_cagr": float(n.cagr.min()), f"{nm}_max_cagr": float(n.cagr.max()), f"{nm}_med_trades": float(n.trades.median()), f"{nm}_med_cost": float(n.cost_paid.median()),
                       f"{nm}_calib": float(n.cagr.std()) / SE[b], f"{nm}_sec": {k_: rank(s[k_], n[k_].values, hb)["percentile"] for k_, hb in HIGHER_BETTER.items()}})
            for c in (0.0, 50.0):
                sc_, nc_ = S(b, cost=c), D(b, typ, cost=c)
                bb[f"{nm}_pct_cagr_{c:g}"] = rank(sc_.cagr, nc_.cagr.values)["percentile"]
                bb[f"{nm}_pct_dd_{c:g}"] = rank(sc_.max_dd, nc_.max_dd.values)["percentile"]
                bb[f"{nm}_med_trades_{c:g}"], bb[f"{nm}_med_cost_{c:g}"] = float(nc_.trades.median()), float(nc_.cost_paid.median())
            r2s = S(b, win="r2")
            nl = D(b, typ, win="r2")
            bb[f"{nm}_r2_pct_cagr"] = rank(r2s.cagr, nl.cagr.values)["percentile"] if bb["r2_reportable"] else None
            bb[f"{nm}_r2_pct_dd"] = rank(r2s.max_dd, nl.max_dd.values)["percentile"] if bb["r2_reportable"] else None
            liq = S(b, cash="liq")
            bb[f"{nm}_liq_pct"] = rank(liq.cagr, D(b, typ, cash="liq").cagr.values)["percentile"]
        r2s, r2w = S(b, win="r2"), S(b, "whole_book", win="r2")
        bb.update({"r2_cagr": float(r2s.cagr), "r2_whole_cagr": float(r2w.cagr), "r2_c3": float(r2s.cagr - r2w.cagr) if bb["r2_reportable"] else None, "r2_sessions": int(r2s.sessions),
                   "liq_cagr": float(S(b, cash="liq").cagr)})
        # R6: the two unranked holdings by their other listing (full_r6, SCMO_0007 and SCMO_0010)
        if b in R6B:
            s6, w6, n6 = S(b, win="full_r6"), S(b, "whole_book", win="full_r6"), D(b, "N4.6", win="full_r6")
            bb["r6"] = {"cagr": float(s6.cagr), "pct": rank(s6.cagr, n6.cagr.values)["percentile"], "draws": int(len(n6)), "c3": float(s6.cagr - w6.cagr), "events": len(EV[(b, "full_r6")]),
                        "retagged": int((ES[(b, "full_r6")].tag_source == "rank_linked").sum())}
        else:
            bb["r6"] = None
        # R7: the flagged price days set to zero
        r7_ = {}
        for c in (0.0, PRIMARY):
            r7_[f"seg_{c:g}"] = float(S(b, "segment_r7", c).cagr)
            r7_[f"whole_{c:g}"] = float(S(b, "whole_book_r7", c).cagr)
            r7_[f"c3_{c:g}"] = r7_[f"seg_{c:g}"] - r7_[f"whole_{c:g}"]
        r7_["n_days"] = int((r7d.book == b).sum()) if r7d is not None else None
        bb["r7"] = r7_
        # weight by band, tag sources, allowed subsets, gaps
        e_, rows = EV[(b, "full")], ES[(b, "full")]
        ri = ROWMAP[(b, "full")]
        span = np.diff(np.append(e_.trade_idx.values.astype(int), nses[b] - 1)).astype(float)
        span = np.where(span <= 0, 0.0, span)
        w = rows.listed_weight.values.astype(float)
        bandw, dropw = np.zeros((len(e_), 3)), np.zeros((len(e_), 3))
        for bi, bn in enumerate(BANDS):
            sel = rows.band.values == bn
            bandw[:, bi] = np.bincount(ri[sel], weights=w[sel], minlength=len(e_))
            seld = sel & ~rows.kept_b.values
            dropw[:, bi] = np.bincount(ri[seld], weights=w[seld], minlength=len(e_))
        tot = bandw.sum(1, keepdims=True)
        bb["band_ew"] = [float(v) for v in (bandw / tot).mean(0)]
        bb["band_sw"] = [float(v) for v in ((bandw / tot) * span[:, None]).sum(0) / span.sum()]
        dsh = ((dropw / tot) * span[:, None]).sum(0) / span.sum()
        bb["band_dropped"] = [float(v) for v in dsh]
        bb["kept_share"] = float(1 - dsh.sum())
        wt = w * span[ri]
        bb["tagsrc"] = {src: float(wt[rows.tag_source.values == src].sum() / wt.sum()) for src in ("rank", "unranked", "membership", "nonmember_rank")}
        bb["unranked_rows"] = int((rows.tag_source.values == "unranked").sum())
        bb["unranked_stocks"] = sorted(set(rows.stock.values[rows.tag_source.values == "unranked"]))
        al = e_.n_allowed_subsets.values.astype(float)
        bb["allowed"] = {"events": len(al), "ones": int((al == 1).sum()), "min": int(al.min()), "median": float(np.median(al)), "max": int(al.max()), "log10": float(np.log10(al).sum())}
        gap = {}
        for nm, typ in NUL:
            A = zdrops[f"{b}|full|{typ}"].astype(float)
            M = np.zeros((len(rows), len(e_)))
            M[np.arange(len(rows)), ri] = w
            Dd = A @ M
            g_ = np.abs(Dd - e_.dropped_weight.values[None, :])
            gap[nm] = {"rule_mean_D": float(e_.dropped_weight.mean()), "null_mean_D": float(Dd.mean()), "mean_abs_gap": float(g_.mean()), "max_gap_over_tau": float((g_ / e_.tau.values[None, :]).max())}
        bb["gap"] = gap
        data["books"][b] = bb
    r5 = pd.read_csv(ev_dir / "r5_tag_error.csv") if (ev_dir / "r5_tag_error.csv").exists() else None
    ctl = pd.read_csv(ev_dir / "controls_negative.csv") if (ev_dir / "controls_negative.csv").exists() else None
    for b in BOOKS:
        if r5 is not None:
            g = r5[r5.book == b].diff_vs_whole_book.values
            data["books"][b]["r5"] = {"n": int(len(g)), "mean": float(g.mean()), "p5": float(np.percentile(g, 5)), "median": float(np.median(g)), "p95": float(np.percentile(g, 95)), "share_pos": float((g > 0).mean())}
        else:
            data["books"][b]["r5"] = None
    v6 = {}
    if ctl is not None:
        for b in BOOKS:
            g_ = ctl[ctl.book == b]
            K = int(len(g_))
            npass = int((g_.percentile >= 90).sum())
            v6[b] = {"K": K, "n_pass90": npass, "x_max": v6_xmax(K), "within": bool(K >= 100 and npass <= v6_xmax(K))}
    data["v6"] = v6 if ctl is not None else None
    v7 = {}
    oj = ev_dir / "controls_oracle.json"
    if oj.exists():
        o_ = json.loads(oj.read_text(encoding="utf-8"))
        for b in BOOKS:
            d_ = per_book(o_, b)
            cg = find_key(d_, {"cagr", "oracle_cagr", "after_cost_cagr"}) if d_ else None
            pc_ = find_key(d_, {"percentile", "pct", "oracle_percentile", "percentile_vs_n46", "percentile_vs_n4.6", "pct_n46"}) if d_ else None
            own = rank(float(cg), D(b, "N4.6").cagr.values)["percentile"] if cg is not None else None
            v7[b] = {"cagr": None if cg is None else float(cg), "stated": None if pc_ is None else float(pc_), "pct": own if own is not None else (None if pc_ is None else float(pc_))}
    data["v7"] = v7 if oj.exists() else None
    data["v4"] = v4_summary(reg) if reg is not None else None
    cnt = lambda key, th=90: int(sum(bool((data["books"][b][key] or 0) >= th) and data["books"][b]["full_reportable"] for b in BOOKS))
    cnt_any = lambda key, th=90: int(sum(bool((data["books"][b][key] or 0) >= th) for b in BOOKS))
    data["verdict"] = {"C1_N46": cnt("n46_pct_cagr"), "C2_N46": cnt("n46_pct_dd"), "C1_N48": cnt("n48_pct_cagr"), "C2_N48": cnt("n48_pct_dd"),
                       "C3": int(sum(data["books"][b]["c3_diff"] > 0 and data["books"][b]["full_reportable"] for b in BOOKS)),
                       "R2_C1_N46": cnt_any("n46_r2_pct_cagr"), "R2_C2_N46": cnt_any("n46_r2_pct_dd"), "R2_C1_N48": cnt_any("n48_r2_pct_cagr"),
                       "R2_C3": int(sum((data["books"][b]["r2_c3"] or 0) > 0 for b in BOOKS)), "R3_N46": cnt_any("n46_liq_pct"), "R3_N48": cnt_any("n48_liq_pct")}
    V = data["verdict"]
    gates_ok = bool(gate_line) and all(v == "PASS" for v in gate_line.values())
    notrep = [b for b in BOOKS if not data["books"][b]["full_reportable"]]
    data["r6_links"] = [] if r6l is None else [{k_: (str(v_) if k_ in ("linked_quote_id", "isin", "stock", "book", "info_date", "original_source", "linked_band") else (int(v_) if str(v_).lstrip("-").isdigit() else str(v_)))
                                                for k_, v_ in r_.items()} for r_ in r6l.to_dict("records")]
    data["r7_days"] = [] if r7d is None else [{"book": str(r_["book"]), "isin": str(r_["isin"]), "stock": str(r_["stock"]), "date": str(r_["date"]), "move": float(r_["move"])} for r_ in r7d.to_dict("records")]

    # ── T07 beside T12, T11 as context ──────────────────────────────────────────
    t07, t11 = Path(a.t07), Path(a.t11)
    data["t07"] = None
    if (t07 / "stats.csv").exists() and (t07 / "draws.csv").exists():
        s7_, d7_ = pd.read_csv(t07 / "stats.csv"), pd.read_csv(t07 / "draws.csv")
        tt = {}
        for b in BOOKS:
            sel = lambda kind: s7_[(s7_.book == b) & (s7_.window == "full") & (s7_.cash == "lbes") & (s7_.cost_bps == PRIMARY) & (s7_.kind == kind)].iloc[0]
            dd7 = lambda typ: d7_[(d7_.book == b) & (d7_.window == "full") & (d7_.cash == "lbes") & (d7_.cost_bps == PRIMARY) & (d7_.draw_type == typ)]
            x7, w7 = sel("segment"), sel("whole_book")
            tt[b] = {"cagr": float(x7.cagr), "n46_pct": rank(x7.cagr, dd7("N4.6").cagr.values)["percentile"], "n48_pct": rank(x7.cagr, dd7("N4.8").cagr.values)["percentile"],
                     "n46_dd_pct": rank(x7.max_dd, dd7("N4.6").max_dd.values)["percentile"], "c3": float(x7.cagr - w7.cagr), "draws": int(len(dd7("N4.6")))}
        data["t07"] = tt
    data["t11"] = None
    if (t11 / "stats.csv").exists():
        s11 = pd.read_csv(t11 / "stats.csv")
        tt = {}
        for b in BOOKS:
            g = s11[(s11.book == b) & (s11.window == "full") & (s11.cash == "lbes") & (s11.cost_bps == PRIMARY)]
            pa, hpar = g[g.kind == "strategy_fixed50"], g[g.kind == "hold_parent"]
            tt[b] = {"parta_cagr": float(pa.iloc[0].cagr) if len(pa) else None, "parta_dd": float(pa.iloc[0].max_dd) if len(pa) else None,
                     "parent_cagr": float(hpar.iloc[0].cagr) if len(hpar) else None, "parent_dd": float(hpar.iloc[0].max_dd) if len(hpar) else None}
        data["t11"] = tt
    data["t11_seen_at_run"] = au.get("t11_headline_seen")
    r6a = au.get("r6") if isinstance(au.get("r6"), dict) else {}
    data["r6_info"] = {"ids": r6a.get("ids"), "links": r6a.get("links"), "re_tagged_event_rows": r6a.get("re_tagged_event_rows"),
                       "retagged_rows_in_evidence": int(sum((data["books"][b]["r6"] or {}).get("retagged", 0) for b in R6B))}

    # ── the stretches table (one row per disagreement stretch of the first book; each book on its own sessions) ──
    st0 = WK[BOOKS[0]]["stretches"]
    stretch_data = []
    nv = {b: {k_: NAV(b, k_).nav.values for k_ in ("segment", "whole_book", "parent")} for b in BOOKS}
    for s0 in st0:
        row = {"from": s0["from"], "to": s0["to"], "weeks": s0["weeks"], "patterns": s0["patterns"], "kind": s0["kind"], "diff": {}, "rule": {}, "whole": {}, "lp": {}}
        for b in BOOKS:
            m = [x for x in WK[b]["stretches"] if x["from"] == s0["from"] and x["to"] == s0["to"]]
            if m:
                s_, e_ = m[0]["s"], m[0]["e"]
                rr_, ww_ = nv[b]["segment"][e_] / nv[b]["segment"][s_] - 1, nv[b]["whole_book"][e_] / nv[b]["whole_book"][s_] - 1
                row["diff"][b], row["rule"][b], row["whole"][b] = float(rr_ - ww_), float(rr_), float(ww_)
                row["lp"][b] = float(100 * (math.log(nv[b]["segment"][e_] / nv[b]["whole_book"][e_]) - math.log(nv[b]["segment"][s_] / nv[b]["whole_book"][s_])))
            else:
                row["diff"][b] = row["rule"][b] = row["whole"][b] = row["lp"][b] = None
        stretch_data.append(row)
    data["stretches"] = stretch_data
    data["stretch_ahead"] = {b: int(sum(1 for r_ in stretch_data if r_["diff"][b] is not None and r_["diff"][b] > 0)) for b in BOOKS}
    data["stretch_n"] = {b: int(sum(1 for r_ in stretch_data if r_["diff"][b] is not None)) for b in BOOKS}
    data["gap_total_lp"] = {b: float(100 * math.log((nv[b]["segment"][-1] / nv[b]["whole_book"][-1]) / (nv[b]["segment"][0] / nv[b]["whole_book"][0]))) for b in BOOKS}
    for b in BOOKS:
        tips = []
        for x in WK[b]["stretches"]:
            rr_ = nv[b]["segment"][x["e"]] / nv[b]["segment"][x["s"]] - 1
            ww_ = nv[b]["whole_book"][x["e"]] / nv[b]["whole_book"][x["s"]] - 1
            tips.append(f"Stretch {len(tips) + 1} of {len(WK[b]['stretches'])}: decisions {x['from']} to {x['to']}, {x['weeks']} week(s), patterns {x['patterns']} (B = BUY, S = SELL; Nifty 100, Midcap 100, Smallcap 100); "
                        f"sessions {cal[b].iloc[x['s']].date()} to {cal[b].iloc[x['e']].date()}: rule {100 * rr_:+.1f}%, whole-book switch {100 * ww_:+.1f}%")
        WK[b]["tips"] = tips
    # episodes.py's attribution (post hoc), only if it was made from this run
    epi = None
    if (ep_dir / "summary.json").exists() and (ep_dir / "stretches.csv").exists():
        es_sum = json.loads((ep_dir / "summary.json").read_text(encoding="utf-8"))
        if es_sum.get("run") == ev_dir.name:
            esx = pd.read_csv(ep_dir / "stretches.csv")
            epi = {"recon": {b: es_sum["books"][b]["recon_max_rel_err"] for b in BOOKS if b in es_sum["books"]},
                   "first_logged": {b: es_sum["books"][b]["first_logged_position"] for b in BOOKS if b in es_sum["books"]},
                   "rows": [{"stretch": int(r_["stretch"]), "book": str(r_["book"]), "kept": None if pd.isna(r_["kept_share_mean"]) else float(r_["kept_share_mean"]),
                             "sleeve": None if pd.isna(r_["sleeve_ret"]) else float(r_["sleeve_ret"]), "ex": [None if pd.isna(r_[c_]) else float(r_[c_]) for c_ in ("excess_large_pp", "excess_mid_pp", "excess_small_pp")]}
                            for r_ in esx.to_dict("records") if r_["book"] in BOOKS]}
    data["episodes"] = epi

    # ── worked example ────────────────────────────────────────────────────────
    b = BOOKS[0]
    e0, rows0 = EV[(b, "full")], ES[(b, "full")]
    cand = e0[(e0.event_no > 0) & e0.partial_b]
    qx = int(cand.index[0]) if len(cand) else 0
    r = e0.iloc[qx]
    dsel = rule_dec[b][pd.to_datetime(rule_dec[b].decision_date) <= pd.Timestamp(r.info_date)].iloc[-1]
    qr = rows0[rows0.event_no == r.event_no].reset_index(drop=True)
    ri0 = ROWMAP[(b, "full")]
    idx = np.flatnonzero(ri0 == qx)
    order = idx[np.argsort(rows0["isin"].values[idx], kind="stable")]
    al = allowed_set(rows0.listed_weight.values[order].astype(float), float(r.dropped_weight), float(r.tau))
    u = float(np.random.default_rng([SEED, 7, 0, BNO[b]]).random(len(e0))[qx])
    pick = int(math.floor(u * len(al)))
    mask = int(al[pick])
    got = np.array([(mask >> i) & 1 for i in range(len(order))])
    stored = zdrops[f"{b}|full|N4.6"][0][order].astype(int)
    wv = rows0.listed_weight.values[order].astype(float)
    s0 = S(b)
    nvs, nvw = NAV(b, "segment"), NAV(b, "whole_book")
    k0 = int(nvs.index[nvs.date == pd.Timestamp(r.trade_date)][0])
    rk = {nm: rank(s0.cagr, D(b, typ).cagr.values) for nm, typ in NUL}
    x0 = {nm: D(b, typ)[D(b, typ).draw_id == 0].iloc[0] for nm, typ in NUL}
    sw_, Dd0 = float(qr.listed_weight.sum()), float(qr.listed_weight[~qr.kept_b].sum())
    data["example"] = {
        "book": b, "event_no": int(r.event_no), "pos": qx + 1, "n_events": len(e0), "kind": str(r.kind), "trade_date": str(r.trade_date), "trade_idx": int(r.trade_idx), "info_date": str(r.info_date), "basket_eff": str(r.basket_eff),
        "decision_week": int(dsel.j), "decision_date": str(dsel.decision_date), "signs": [str(dsel.sign_Nifty100), str(dsel.sign_MC100), str(dsel.sign_SC100)], "labels": [str(dsel.label_Nifty100), str(dsel.label_MC100), str(dsel.label_SC100)],
        "states": [str(r.state_Nifty100), str(r.state_MC100), str(r.state_SC100)], "V": float(r.V_before), "traded": float(r.traded), "cost": float(r.cost), "sum_w": sw_, "D": Dd0, "s": Dd0 / sw_,
        "ev_D": float(r.dropped_weight), "ev_s": float(r.sleeve_share_s), "n_held": int(r.n_held), "n_dropped": int(r.n_dropped), "tau": float(r.tau), "n_allowed": int(r.n_allowed_subsets),
        "u": u, "pick": pick, "mask": mask, "draw_drops": [str(rows0.stock.values[order[i]]) for i in range(len(order)) if got[i]], "rule_drops": [str(rows0.stock.values[order[i]]) for i in range(len(order)) if not rows0.kept_b.values[order[i]]],
        "draw_weight": float(wv @ got), "stored_equal": bool((got == stored).all()),
        "rows": [{"stock": str(x.stock), "isin": str(x.isin), "w": float(x.listed_weight), "band": str(x.band), "src": str(x.tag_source), "snap": str(x.tag_snapshot), "detail": "" if pd.isna(x.tag_detail) else str(x.tag_detail),
                  "via": "" if pd.isna(x.tag_via) else str(x.tag_via), "sig": str(x.band_signal), "kept": bool(x.kept_b)} for x in qr.itertuples()],
        "nav_around": [{"date": str(nvs.date.iloc[i].date()), "rule": float(nvs.nav.iloc[i]), "whole": float(nvw.nav.iloc[i])} for i in range(max(k0 - 2, 0), min(k0 + 3, len(nvs)))],
        "end_nav": float(s0.end_nav), "sessions": int(s0.sessions), "path_start": str(nvs.date.iloc[0].date()), "path_end": str(nvs.date.iloc[-1].date()), "cagr": float(s0.cagr), "max_dd": float(s0.max_dd),
        "d0": {nm: {"cagr": float(x0[nm].cagr), "max_dd": float(x0[nm].max_dd), "trades": int(x0[nm].trades), "cost_paid": float(x0[nm].cost_paid)} for nm, _ in NUL},
        "rank": {nm: rk[nm] for nm, _ in NUL}, "rule_trades": int(s0.trades), "rule_cost_paid": float(s0.cost_paid)}
    ex = data["example"]
    data["inputs"] = [{"file": r_.file, "through": r_.through, "approved_row": r_.approved_row, "sha16": r_.sha256[:16]} for r_ in inp.itertuples()]
    data["caveats"] = caveats

    # ── charts ────────────────────────────────────────────────────────────────
    lines_data, curves_html = {}, ""
    for b in BOOKS:
        ser = {k_: NAV(b, k_).nav.values for k_ in ("segment", "whole_book", "parent", "constant_mix")}
        dates = list(cal[b])
        eq_svg, eq_d = svg_lines(f"eq|{b}", ser, dates, "eq")
        ddser = {k_: v / np.maximum.accumulate(v) - 1 for k_, v in ser.items()}
        dd_svg, dd_d = svg_lines(f"dd|{b}", ddser, dates, "dd")
        lines_data[f"eq|{b}"], lines_data[f"dd|{b}"] = eq_d, dd_d
        curves_html += (f'<h3>{E(b)}</h3><div class="two"><figure class="card hv"><figcaption>Growth of 1 invested at the close of {dates[0].date()}, log scale, to {dates[-1].date()}, 20.8 bps · rule ends at {data["books"][b]["end_nav"]:.2f}×. '
                        f'Hold the parent is {PARENT_NOTE}. Hover: the date and the level at the pointer; the tooltip lists the four curves (drawn every {DOWNSAMPLE}th session).</figcaption>{eq_svg}<div class="tip" hidden></div></figure>'
                        f'<figure class="card hv"><figcaption>Drawdown from the running peak, {dates[0].date()} to {dates[-1].date()}, 20.8 bps · rule worst {pc(data["books"][b]["max_dd"])}, whole-book {pc(data["books"][b]["whole_dd"])}, parent {pc(data["books"][b]["parent_dd"])}. '
                        f'Hold the parent is {PARENT_NOTE}. Hover as on the left.</figcaption>{dd_svg}<div class="tip" hidden></div></figure></div>')
    legend = "".join(f'<span class="key"><i style="background:{COL[k_]}"></i>{E(LAB[k_])}</span>' for k_ in COL)
    # the gap curve of the whole-book section: 100 x ln(rule / whole-book), every book
    gser = {b: 100 * np.log(nv[b]["segment"] / nv[b]["whole_book"]) for b in BOOKS}
    gap_svg, gap_d = svg_lines("gap|all", gser, list(cal[BOOKS[0]]), "lp", w=900, h=280, cols=BKCOL, labs={b: b for b in BOOKS})
    lines_data["gap|all"] = gap_d

    bars_data, hists = {}, ""
    pct_fmt = lambda v: f"{100 * v:.1f}%"
    for b in BOOKS:
        x = data["books"][b]
        n6, n8 = D(b, "N4.6"), D(b, "N4.8")
        cells = ""
        for what, col, mark, title, note in (("cagr", "cagr", x["cagr"], "After-cost CAGR", "right = better"), ("dd", "max_dd", x["max_dd"], "Maximum drawdown", "shallower is to the right")):
            a6, a8 = n6[col].values, n8[col].values
            lo_, hi_ = float(min(a6.min(), a8.min(), mark)), float(max(a6.max(), a8.max(), mark))
            pad = max((hi_ - lo_) * 0.04, 1e-9)
            edges = np.linspace(lo_ - pad, hi_ + pad, 33)
            c6, _ = np.histogram(a6, bins=edges)
            c8, _ = np.histogram(a8, bins=edges)
            marks = [{"label": "The rule", "x": mark, "col": "var(--fg)", "txt": f"percentile {x['n46_pct_' + what]:.1f} vs N4.6, {x['n48_pct_' + what]:.1f} vs N4.8"},
                     {"label": "N4.6 median", "x": float(np.median(a6)), "col": C6, "txt": "(blue, dashed)", "dash": True},
                     {"label": "N4.8 median", "x": float(np.median(a8)), "col": C8, "txt": "(orange, dashed)", "dash": True}]
            did = f"hist|{b}|{what}"
            svg, bd = svg_bars(did, edges, [{"k": "n48", "label": "N4.8 (label permutation)", "col": C8, "v": c8, "n": len(a8)}, {"k": "n46", "label": "N4.6 (size-matched exclusion)", "col": C6, "v": c6, "n": len(a6)}],
                               marks=marks, xk="pct", yk="int", xticks=[(float(v), pct_fmt(v)) for v in np.linspace(lo_, hi_, 5)], binlab=[f"{pct_fmt(edges[i])} to {pct_fmt(edges[i + 1])}" for i in range(32)], yunit="draws")
            bars_data[did] = bd
            cells += f'<div class="hv"><div class="mini">{title} ({note}; black = the rule, dashed = medians)</div>{svg}<div class="tip wrap" hidden></div></div>'
        hists += f'<figure class="card"><figcaption><b>{E(b)}</b> · {ND:,} draws of each null, 20.8 bps, {cal[b].iloc[0].date()} → {end_date}</figcaption><div class="two">{cells}</div></figure>'

    band_data, bands_html = {}, ""
    for b in BOOKS:
        e_, rows = EV[(b, "full")], ES[(b, "full")]
        ri = ROWMAP[(b, "full")]
        w = rows.listed_weight.values.astype(float)
        bandw = np.zeros((len(e_), 3))
        nst = np.zeros((len(e_), 3), int)
        for bi, bn in enumerate(BANDS):
            sel = rows.band.values == bn
            bandw[:, bi] = np.bincount(ri[sel], weights=w[sel], minlength=len(e_))
            nst[:, bi] = np.bincount(ri[sel], minlength=len(e_))
        wt = bandw / bandw.sum(1, keepdims=True)
        starts = [int(v) for v in e_.trade_idx.values]
        ends = starts[1:] + [nses[b] - 1]
        on = [[bool(e_.iloc[q][f"state_{s_}"] == "BUY") for s_ in SIGS] for q in range(len(e_))]
        bd = {"n": nses[b], "dates": [d_.strftime("%Y-%m-%d (%a)") for d_ in cal[b]], "start": starts, "end": ends, "no": [int(v) for v in e_.event_no.values], "kind": [str(v) for v in e_.kind.values],
              "tdate": [str(v) for v in e_.trade_date.values], "beff": [str(v) for v in e_.basket_eff.values], "wt": [[round(float(v), 5) for v in row] for row in wt], "on": on, "nst": nst.tolist(),
              "s": [round(float(v), 5) for v in e_.sleeve_share_s.values], "ndrop": [int(v) for v in e_.n_dropped.values], "nheld": [int(v) for v in e_.n_held.values]}
        svg, bd = svg_bands(f"band|{b}", bd)
        band_data[f"band|{b}"] = bd
        bands_html += (f'<figure class="card hv"><figcaption><b>{E(b)}</b> · weight by band at each of the {len(e_)} events, {cal[b].iloc[0].date()} → {end_date}: the share of the book\'s listed weight in Large (purple, bottom), Mid (orange) and Small and below (green); '
                       f'a faint block is a band whose index signal was SELL at the event (its stocks are dropped). Hover: the date, the event holding then, the weight of each band and whether it is kept.</figcaption>{svg}<div class="tip wrap" hidden></div></figure>')

    regime_data, regime_html = {}, ""
    for b in BOOKS:
        n_ = nses[b]
        idx = np.append(np.arange(0, n_, RG_STEP), n_ - 1)
        idx = np.unique(idx)
        sr, sw2, sp = (nv[b][k_] for k_ in ("segment", "whole_book", "parent"))
        e_ = EV[(b, "full")]
        allv = np.concatenate([sr[idx], sw2[idx], sp[idx]])
        w_ = WK[b]
        rd = {"N": n_, "idx": [int(i) for i in idx], "dates": [cal[b].iloc[i].strftime("%Y-%m-%d (%a)") for i in idx], "alldates": [d_.strftime("%Y-%m-%d") for d_ in cal[b]],
              "rule": [round(float(sr[i]), 4) for i in idx], "whole": [round(float(sw2[i]), 4) for i in idx], "parent": [round(float(sp[i]), 4) for i in idx],
              "lo": math.log(allv.min() * 0.97), "hi": math.log(allv.max() * 1.03), "wk0": w_["wk0"], "sg": w_["sg"], "wst": w_["wst"], "wstr": w_["wstr"], "tips": w_["tips"],
              "es": [int(v) for v in e_.trade_idx.values], "ek": [round(float(1 - v), 5) for v in e_.sleeve_share_s.values]}
        svg, rd = svg_regime(f"regime|{b}", rd)
        regime_data[f"regime|{b}"] = rd
        regime_html += (f'<figure class="card hv"><figcaption><b>{E(b)}</b> · growth of 1 from {cal[b].iloc[0].date()} to {end_date} (log scale, 20.8 bps) for the rule, the whole-book switch and the parent held throughout (the parent is {PARENT_NOTE}); the orange bands are the {len(w_["stretches"])} stretches where the three signals disagree. '
                        f'Strips below, one per signal (filled = BUY), the share of the book the rule keeps in its stocks (bar height), and the whole-book switch (filled = IN). Hover (or touch): the date, the three curves, the signals, the rule\'s share kept and the stretch the date is in.</figcaption>{svg}<div class="tip wrap" hidden></div></figure>')
    stretch_tab = [[str(i + 1), r_["from"], r_["to"], str(r_["weeks"]), r_["patterns"], E(r_["kind"])] + [("" if r_["diff"][b] is None else f"{100 * r_['diff'][b]:+.1f}") for b in BOOKS] for i, r_ in enumerate(stretch_data)]
    stretch_tab.append(["", "", "", "", "", "Rule ahead of the whole-book switch in"] + [f"{data['stretch_ahead'][b]} of {data['stretch_n'][b]}" for b in BOOKS])

    # ── the whole-book section (post hoc) ───────────────────────────────────────
    kinds = list(dict.fromkeys(r_["kind"] for r_ in stretch_data))
    kind_rows = []
    for k_ in kinds:
        ids = [i for i, r_ in enumerate(stretch_data) if r_["kind"] == k_]
        kind_rows.append([f"<b>{E(k_)}</b><br><span class='cap'>{E(KIND_TXT.get(k_, ''))}</span>", ", ".join(str(i + 1) for i in ids),
                          f"{sum(1 for i in ids for b in BOOKS if (stretch_data[i]['lp'][b] or 0) > 0)} of {len(ids) * len(BOOKS)}"]
                         + [f"{sum(stretch_data[i]['lp'][b] or 0 for i in ids):+.1f}" for b in BOOKS])
    insum = {b: sum(r_["lp"][b] or 0 for r_ in stretch_data) for b in BOOKS}
    kind_rows.append(["Outside the stretches (all BUY or all SELL: both rules hold the same weights; costs and drift only)", "", ""] + [f"{data['gap_total_lp'][b] - insum[b]:+.1f}" for b in BOOKS])
    kind_rows.append(["<b>Total: rule against the whole-book switch</b>", "", ""] + [f"<b>{data['gap_total_lp'][b]:+.1f}</b>" for b in BOOKS])
    pooled = [float(np.mean([r_["lp"][b] for b in BOOKS if r_["lp"][b] is not None])) for r_ in stretch_data]
    big = int(np.argmax(np.abs(pooled))) if pooled else None
    lo_rows = []
    if big is not None:
        lo_rows = [["All stretches (the result)"] + [f"{data['gap_total_lp'][b]:+.1f}" for b in BOOKS],
                   [f"Without stretch {big + 1} ({stretch_data[big]['from']} → {stretch_data[big]['to']}, the largest average gap, {pooled[big]:+.1f})"] + [f"{data['gap_total_lp'][b] - (stretch_data[big]['lp'][b] or 0):+.1f}" for b in BOOKS]]
    attr_rows = []
    if epi is not None:
        for i, r_ in enumerate(stretch_data):
            er = [x for x in epi["rows"] if x["stretch"] == i + 1]
            kept = [x["kept"] for x in er if x["kept"] is not None]
            slv = [x["sleeve"] for x in er if x["sleeve"] is not None]
            exs = [[x["ex"][j] for x in er if x["ex"][j] is not None] for j in range(3)]
            attr_rows.append([str(i + 1), E(r_["kind"]), f"{100 * np.mean(kept):.0f}" if kept else "", f"{100 * np.mean(slv):+.1f}" if slv else ""] + [f"{np.mean(x):+.1f}" if x else "" for x in exs])
    whywhole = (f'<h2 id="whywhole">Where the rule and the whole-book switch part ways</h2>'
                f'<p class="cap">Post hoc and descriptive: not part of the pre-registered test, it changes no verdict. {start3} → {end_date}, 20.8 bps, the same runs as everything above. '
                f'The two rules hold the same weights whenever the three signals agree, so the gap between them can only open in the disagreement stretches. Every figure in this section is in log points: 100 × ln(rule value ÷ whole-book switch value); positive = the rule is ahead.</p>'
                f'<figure class="card hv"><figcaption>The rule against the whole-book switch through time, every book, {start3} → {end_date}, 20.8 bps, log points (both start at 1). Hover: the date and each book\'s gap at the pointer (drawn every {DOWNSAMPLE}th session).</figcaption>'
                f'<div class="legend">{"".join(f"<span class=key><i style=background:{BKCOL[b]}></i>{b}</span>" for b in BOOKS)}</div>{gap_svg}<div class="tip" hidden></div></figure>'
                + table(kind_rows, ["Kind of stretch (from the signals just before and just after it)", "Stretches", "Rule ahead in (book-stretches)"] + [f"{b} (log pts)" for b in BOOKS])
                + (f'<p>Leave one out: the total without the stretch with the largest average gap ({start3} → {end_date}).</p>' + table(lo_rows, ["Rule against the whole-book switch, log points"] + BOOKS) if lo_rows else "")
                + ((f'<p>What the rule kept in each stretch (from <code>episodes.py</code>, which rebuilds the rule\'s holdings from <code>positions.csv</code> and the approved prices; they reproduce its NAV to {max(epi["recon"].values()):.0e} relative, '
                    f'from the first logged position {epi["first_logged"].get(BOOKS[0])}): the share of the book kept in stocks, the sleeve\'s return over the stretch, and the kept stocks\' return against the sleeve by band (percentage points of the book), averages of the four books.</p>'
                    + table(attr_rows, ["#", "Kind", "Kept % of book", "Sleeve return %", "Large vs sleeve (pp)", "Mid (pp)", "Small and below (pp)"])) if epi is not None else
                   '<p class="cap">episodes.py has not been run on this evidence: the attribution by band is not shown.</p>'))

    # ── tables ────────────────────────────────────────────────────────────────
    chip = lambda ok: ('<span class="chip ok">PASS</span>' if ok else '<span class="chip bad">FAIL</span>')
    bk = data["books"]
    head_rows = [[E(b), pc(bk[b]["parent_cagr"]), pc(bk[b]["whole_cagr"]), pc(bk[b]["cagr"]), pc(bk[b]["n46_median_cagr"]), f"{100 * (bk[b]['cagr'] - bk[b]['n46_median_cagr']):+.2f} pp", f"<b>{bk[b]['n46_pct_cagr']:.1f}</b>", f"{bk[b]['n46_p_cagr']:.3f}",
                  pc(bk[b]["n48_median_cagr"]), f"<b>{bk[b]['n48_pct_cagr']:.1f}</b>", f"{bk[b]['n48_p_cagr']:.3f}"] for b in BOOKS]
    dd_rows = [[E(b), pc(bk[b]["parent_dd"]), pc(bk[b]["whole_dd"]), pc(bk[b]["max_dd"]), pc(bk[b]["n46_median_dd"]), f"<b>{bk[b]['n46_pct_dd']:.1f}</b>", f"{bk[b]['n46_p_dd']:.3f}", pc(bk[b]["n48_median_dd"]), f"<b>{bk[b]['n48_pct_dd']:.1f}</b>", f"{bk[b]['n48_p_dd']:.3f}"] for b in BOOKS]
    c3_rows = [[E(b), pc(bk[b]["whole_cagr"]), pc(bk[b]["cagr"]), f"<b>{100 * bk[b]['c3_diff']:+.2f}</b>", f"{100 * bk[b]['c3_se']:.2f}", f"{bk[b]['c3_diff'] / bk[b]['c3_se']:+.2f}", chip(bk[b]["c3_diff"] > 0), f"{100 * bk[b]['c3_diff_0']:+.2f}", f"{100 * bk[b]['c3_diff_50']:+.2f}"] for b in BOOKS]
    cost_rows = []
    for b in BOOKS:
        for kind, lab in (("segment", LAB["segment"]), ("whole_book", LAB["whole_book"]), ("parent", LAB["parent"]), ("constant_mix", LAB["constant_mix"]), ("sleeve100", "50/50 GOLDBEES + cash")):
            row = [E(b) if kind == "segment" else "", lab]
            for cst in COSTS:
                s = S(b, kind, cst)
                row += [pc(s.cagr), pc(s.max_dd)]
            cost_rows.append(row)
    sec_rows = []
    for nm, typ in NUL:
        for b in BOOKS:
            sec_rows.append([typ if b == BOOKS[0] else "", E(b)] + [f"{bk[b][f'{nm}_sec'][k_]:.1f}" for k_ in SECSTATS])
    rob1 = [[E(b)] + [f"{bk[b][f'{nm}_{k_}']:.1f}" for nm in ("n46", "n48") for k_ in ("pct_cagr_0", "pct_cagr", "pct_cagr_50", "pct_dd_0", "pct_dd", "pct_dd_50")] for b in BOOKS]
    r1trades = []
    for b in BOOKS:
        r1trades.append([E(b), str(bk[b]["trades"]), f"{bk[b]['cost_paid']:.4f}", str(bk[b]["whole_trades"]), f"{bk[b]['whole_cost']:.4f}"] + [f"{bk[b][f'{nm}_med_trades']:.1f}" for nm in ("n46", "n48")] + [f"{bk[b][f'{nm}_med_cost']:.4f}" for nm in ("n46", "n48")] +
                        [f"{bk[b][f'{nm}_med_trades'] / max(bk[b]['trades'], 1):.2f}" for nm in ("n46", "n48")])
    rob2 = [[E(b), f1(bk[b]["n46_r2_pct_cagr"]), f1(bk[b]["n48_r2_pct_cagr"]), f1(bk[b]["n46_r2_pct_dd"]), "" if bk[b]["r2_c3"] is None else f"{100 * bk[b]['r2_c3']:+.2f}", pc(bk[b]["r2_cagr"]), pc(bk[b]["r2_whole_cagr"]),
             f1(bk[b]["n46_liq_pct"]), f1(bk[b]["n48_liq_pct"]), pc(bk[b]["liq_cagr"])] for b in BOOKS]
    r4rows = [[E(b)] + [x_ for nm in ("n46", "n48") for x_ in (f"{bk[b][f'{nm}_pct_cagr']:.1f}", pc(bk[b][f"{nm}_median_cagr"]), f"{100 * bk[b][f'{nm}_sd_cagr']:.2f}", pc(bk[b][f"{nm}_p5_cagr"]), pc(bk[b][f"{nm}_p95_cagr"]))] +
              [f"{bk[b]['n46_med_trades'] / max(bk[b]['trades'], 1):.2f}", f"{bk[b]['n48_med_trades'] / max(bk[b]['trades'], 1):.2f}"] for b in BOOKS]
    r5rows = [[E(b), str(bk[b]["r5"]["n"]), f"{100 * bk[b]['c3_diff']:+.2f}", f"{100 * bk[b]['r5']['mean']:+.2f}", f"{100 * bk[b]['r5']['p5']:+.2f}", f"{100 * bk[b]['r5']['median']:+.2f}", f"{100 * bk[b]['r5']['p95']:+.2f}", f"{100 * bk[b]['r5']['share_pos']:.1f}%"]
              for b in BOOKS if bk[b]["r5"]]
    r6rows = [[E(b), str(bk[b]["r6"]["events"]), str(bk[b]["r6"]["retagged"]), pc(bk[b]["r6"]["cagr"], 2), pc(bk[b]["cagr"], 2), f"{bk[b]['r6']['pct']:.1f}", f"{bk[b]['n46_pct_cagr']:.1f}", f"{100 * bk[b]['r6']['c3']:+.2f}", f"{100 * bk[b]['c3_diff']:+.2f}"]
              for b in R6B if bk[b]["r6"]]
    r6link_rows = [[E(x["book"]), E(x["stock"]), E(x["isin"]), E(str(x["original_source"])), E(str(x["linked_quote_id"])), E(str(x["info_date"])), E(str(x["linked_rank"])), E(str(x["linked_band"]))] for x in data["r6_links"]]
    r7day_rows = [[E(x["book"]), E(x["stock"]), E(x["isin"]), E(x["date"]), f"{100 * x['move']:+.1f}%"] for x in data["r7_days"]]
    r7rows = [[E(b), str(bk[b]["r7"]["n_days"]), pc(bk[b]["cagr"], 2), pc(bk[b]["r7"]["seg_20.8"], 2), pc(bk[b]["whole_cagr"], 2), pc(bk[b]["r7"]["whole_20.8"], 2), f"{100 * bk[b]['c3_diff']:+.2f}", f"{100 * bk[b]['r7']['c3_20.8']:+.2f}", f"{100 * bk[b]['r7']['c3_0']:+.2f}"] for b in BOOKS]
    mde_rows = [[E(b), str(bk[b]["full_stretches"]), str(bk[b]["full_partial"])] + [x_ for nm in ("n46", "n48") for x_ in (f"{100 * bk[b][f'{nm}_sd_cagr']:.2f}", f"{bk[b][f'{nm}_mde_cagr_pp']:.1f}", f"{100 * bk[b][f'{nm}_sd_dd']:.2f}", f"{bk[b][f'{nm}_mde_dd_pp']:.1f}")] for b in BOOKS]
    calib_rows = [[E(b), typ, f"{100 * bk[b][f'{nm}_sd_cagr']:.2f}", f"{100 * bk[b]['c3_se']:.2f}", f"{bk[b][f'{nm}_calib']:.2f}"] for b in BOOKS for nm, typ in NUL]
    spread_rows = [[E(b), typ, pc(bk[b][f"{nm}_min_cagr"]), pc(bk[b][f"{nm}_p5_cagr"]), pc(bk[b][f"{nm}_median_cagr"]), pc(bk[b][f"{nm}_p95_cagr"]), pc(bk[b][f"{nm}_max_cagr"])] for b in BOOKS for nm, typ in NUL]
    rep_rows = [[E(b), win, str(bk[b][f"{win}_weeks"]), str(bk[b][f"{win}_dis_weeks"]), str(bk[b][f"{win}_stretches"]), str(bk[b][f"{win}_events"]), str(bk[b][f"{win}_partial"]),
                 '<span class="chip ok">reportable</span>' if bk[b][f"{win}_reportable"] else '<span class="chip bad">NOT REPORTABLE</span>'] for b in BOOKS for win in ("full", "r2")]
    al_rows = [[E(b), str(bk[b]["allowed"]["events"]), str(bk[b]["allowed"]["ones"]), str(bk[b]["allowed"]["min"]), f"{bk[b]['allowed']['median']:.1f}", str(bk[b]["allowed"]["max"]), f"{bk[b]['allowed']['log10']:.1f}"] +
              [f"{bk[b]['gap'][nm]['rule_mean_D']:.4f}" for nm in ("n46",)] + [x_ for nm in ("n46", "n48") for x_ in (f"{bk[b]['gap'][nm]['null_mean_D']:.4f}", f"{bk[b]['gap'][nm]['mean_abs_gap']:.4f}", f"{bk[b]['gap'][nm]['max_gap_over_tau']:.2f}")] for b in BOOKS]
    wb_rows = [[E(b)] + [f"{100 * bk[b]['band_ew'][i]:.1f}" for i in range(3)] + [f"{100 * bk[b]['band_sw'][i]:.1f}" for i in range(3)] + [f"{100 * bk[b]['band_dropped'][i]:.1f}" for i in range(3)] + [f"{100 * bk[b]['kept_share']:.1f}"] for b in BOOKS]
    ts_rows = [[E(b)] + [f"{100 * bk[b]['tagsrc'][s_]:.2f}" for s_ in ("rank", "unranked", "membership", "nonmember_rank")] + [str(bk[b]["unranked_rows"]), E(", ".join(bk[b]["unranked_stocks"]) or "none")] for b in BOOKS]
    v4s = data["v4"]
    if v4s is not None:
        a4, b4, c4, d4 = v4s["v4a"], v4s["v4b"], v4s["v4c"], v4s["v4d"]
        v4rows = [["(a) the engine on the D17 calendar of 2019 (T0 = each book's first D17 date, to 2019-12-31) against T07's stored rule NAV and T06's stored whole-book NAV", f"{a4['comparisons']:,} comparisons, {a4['sessions']:,} sessions", f"{a4['worst']:.1e}", chip(a4["present"] and not a4["not_run"] and a4["comparisons"] > 0 and a4["bad"] == 0)],
                  ["(b) whole-book and always-in modes on this window against T11's Part A and hold-the-parent NAVs", ("not run: " + E(b4["reason"])) if b4["not_run"] else f"{b4['comparisons']:,} comparisons, {b4['sessions']:,} sessions",
                   "" if b4["not_run"] else f"{b4['worst']:.1e}", '<span class="chip warn">NOT RUN</span>' if b4["not_run"] else chip(b4["comparisons"] > 0 and b4["bad"] == 0)],
                  ["(c) the functions shared with t07_engine.py, changed only where expected", f"{c4['functions']} listed, {c4['changed']} changed, {c4['unexpected']} unexpected", "", chip(c4["present"] and c4["unexpected"] == 0)],
                  ["(d) the tag at every event against a direct read of the D23b rank panel", f"{d4['compared']:,} compared, {d4['mismatches']} mismatches", "", chip(d4["present"] and d4["compared"] > 0 and d4["mismatches"] == 0)]]
    else:
        v4rows = [["regression.json missing", "", "", chip(False)]]
    gate_desc = {"V1": "verify_t12.py shares no code with the engine" + (f": {ver.get('gate_compared', 0):,} comparisons, corrupted copy caught" if ver and "gate_compared" in ver else ""),
                 "V2": "every decision reads Master rows dated on or before it; every tag a snapshot on or before its information date; every trade is on a later session",
                 "V3": "both nulls hold their tables at every event of every draw; the sampler replays from its seed",
                 "V4": "no published NAV before 2019: the same code reproduces T07's and T06's stored NAVs on 2019 (D17 calendar), T11's when it exists, shared functions unchanged, tags equal a direct read",
                 "V5": "the sampler: chi-square on the small case, the count of allowed subsets by brute force, the rule's own subset is allowed",
                 "V6": "negative control: 100 shifted signal sets, at most 17 reach the 90th percentile",
                 "V7": "positive control: the oracle reaches the 99th percentile against N4.6 in every book"}
    gate_names = {"V1": "independent check", "V2": "point in time", "V3": "the nulls hold their tables", "V4": "regression and identities", "V5": "the sampler is exact", "V6": "negative control", "V7": "positive control (oracle)"}
    gate_rows = [[f"{k_} {gate_names[k_]}", f'<span class="chip {"ok" if (gate_line or {}).get(k_) == "PASS" else "bad"}">{(gate_line or {}).get(k_, "NOT RUN")}</span>', E(gate_desc[k_])] for k_ in gate_names]
    v6rows = [[E(b), str(data["v6"][b]["K"]), str(data["v6"][b]["n_pass90"]), f"at most {data['v6'][b]['x_max']}",
               '<span class="chip ok">within</span>' if data["v6"][b]["within"] else '<span class="chip bad">OUTSIDE: V6 FAILS</span>'] for b in BOOKS] if data["v6"] else []
    v7rows = [[E(b), pcs(data["v7"][b]["cagr"], 2), f1(data["v7"][b]["stated"]), f1(data["v7"][b]["pct"]), '<span class="chip ok">&ge; 99</span>' if (data["v7"][b]["pct"] or 0) >= 99 else '<span class="chip bad">BELOW 99: V7 FAILS</span>'] for b in BOOKS] if data["v7"] else []
    v6bad = [b for b in BOOKS if data["v6"] and not data["v6"][b]["within"]]
    inp_rows = [[E(r_.file), E(r_.through), E(r_.approved_row), E(r_.sha256[:16])] for r_ in inp.itertuples()]
    cmp_rows = []
    if data["t07"]:
        for b in BOOKS:
            t7 = data["t07"][b]
            cmp_rows.append([E(b), pc(bk[b]["cagr"]), pc(t7["cagr"]), f"{bk[b]['n46_pct_cagr']:.1f}", f"{t7['n46_pct']:.1f}", f"{bk[b]['n48_pct_cagr']:.1f}", f"{t7['n48_pct']:.1f}", f"{bk[b]['n46_pct_dd']:.1f}", f"{t7['n46_dd_pct']:.1f}",
                             f"{100 * bk[b]['c3_diff']:+.2f}", f"{100 * t7['c3']:+.2f}"])
    t11_rows = []
    if data["t11"]:
        for b in BOOKS:
            t1 = data["t11"][b]
            t11_rows.append([E(b), pcs(t1["parta_cagr"], 2), pc(bk[b]["whole_cagr"], 2), pcs(t1["parent_cagr"], 2), pc(bk[b]["parent_cagr"], 2), pc(bk[b]["cagr"], 2)])

    t11_html = ((f'<p>T11 (context): the whole-book switch with the fixed 50/50 sleeve (its Part A) and hold-the-parent on the same parents and window, from <code>tests/T11/evidence/headline/stats.csv</code> ({start3} → {end_date}, 20.8 bps), '
                 f'beside T12’s own whole-book switch and parent (V4(b) requires them equal when it is run). Hold the parent is {PARENT_NOTE}.</p>')
                + table(t11_rows, ["Book", "T11 Part A CAGR", "T12 whole-book CAGR", "T11 hold-parent CAGR", "T12 parent CAGR", "T12 rule CAGR"])) if t11_rows else "<p>T11's headline evidence does not exist: no T11 context is shown.</p>"
    # ── the answer ────────────────────────────────────────────────────────────
    c1, c2, c3p = V["C1_N46"] >= 3, V["C2_N46"] >= 3, V["C3"] >= 3
    if not gates_ok:
        lead = "A validity gate failed or analysis.log is missing: do not read the results below."
    elif c1 and c2 and c3p and V["C1_N48"] >= 3:
        lead = "Yes, on 2014-19: tagging each stock by its own band's signal chose what to drop better than a random exclusion of the same weight, and beat the whole-book switch; with T07's failure on 2019-26 the effect is window-specific."
    elif c3p and not c1:
        lead = "Partly: the rule beats the whole-book switch, but a random exclusion of the same weight does as well, so the gain is partial de-risking, not the tag."
    elif c1 and not c3p:
        lead = "Partly: the tag picks better than a random exclusion, but not by enough to beat the whole-book switch."
    elif not c1 and not c3p:
        lead = "No: T07's rejection holds on 2014-19 too."
    else:
        lead = "Mixed: see the table."
    answer = (f'<div class="answer"><p><b>{lead}</b> Holding each stock a parent holds only while the index of its size band is BUY (Large: Nifty 100, Mid: Midcap 100, Small and below: Smallcap 100), '
              f'and sending the weight of the rest to a 50/50 GOLDBEES and cash sleeve, against dropping a random set of the same weight at the same events (N4.6, decides), on {start3} → {end_date}, after 20.8 bps. '
              f'C1 (return beats the 90th percentile of the null): {V["C1_N46"]} of 4 books; C2 (worst fall): {V["C2_N46"]} of 4; C3 (rule minus the whole-book switch above zero): {V["C3"]} of 4 (pre-registered pass: 3 of 4 each). '
              f'N4.8 (label permutation, beside it): C1 {V["C1_N48"]} of 4, C2 {V["C2_N48"]} of 4.</p>'
              f'<p>The catch: the three signals disagree in only {bk[BOOKS[0]]["full_dis_weeks"]} of {bk[BOOKS[0]]["full_weeks"]} weeks, in {bk[BOOKS[0]]["full_stretches"]} stretches shared by all four books, so the rule differs from the whole-book switch in only {bk[BOOKS[0]]["full_stretches"]} independent places and "3 of 4" is a consistency check. '
              f'On the R2 sub-window ({r2_first} → {end_date}) C1 reaches the 90th percentile in {V["R2_C1_N46"]} of 4 books and C3 is positive in {V["R2_C3"]} of 4. '
              f'T12 alone cannot reverse T07, so any finding is PROVISIONAL at most.{"" if not notrep else " NOT REPORTABLE: " + ", ".join(notrep) + "."}</p></div>')
    verdict_rows = [["C1 selection (H1): CAGR percentile vs N4.6 ≥ 90", chip(c1), f"{V['C1_N46']} of 4", f"N4.8 beside it: {V['C1_N48']} of 4"],
                    ["C2 protection (H2): maximum-drawdown percentile vs N4.6 ≥ 90", chip(c2), f"{V['C2_N46']} of 4", f"N4.8 beside it: {V['C2_N48']} of 4"],
                    ["C3 increment (H3): rule minus whole-book switch CAGR > 0", chip(c3p), f"{V['C3']} of 4", "no null: a direct difference"]]
    summ_rows = [[E(b), pc(bk[b]["cagr"]), f"{bk[b]['n46_pct_cagr']:.1f}", f"{bk[b]['n46_p_cagr']:.3f}", f"{bk[b]['n48_pct_cagr']:.1f}", pc(bk[b]["max_dd"]), f"{bk[b]['n46_pct_dd']:.1f}", f"{bk[b]['n48_pct_dd']:.1f}",
                  f"{100 * bk[b]['c3_diff']:+.2f}", pc(bk[b]["r2_cagr"]), f1(bk[b]["n46_r2_pct_cagr"])] for b in BOOKS]
    ex_tab = [[E(x["stock"]), E(x["isin"]), f"{x['w']:.5f}", E(x["band"]), E(x["src"]), E(x["snap"]), E(x["detail"]), E(x["via"]), E(x["sig"]), "kept" if x["kept"] else "<b>dropped</b>"] for x in ex["rows"]]
    nav_tab = [[x["date"], f"{x['rule']:.6f}", f"{x['whole']:.6f}"] for x in ex["nav_around"]]
    n_held = ex["n_held"]
    r6i = data["r6_info"]
    if r6i["retagged_rows_in_evidence"] == 0:
        r6_note = (f"R6 re-tagged no row in this run: the quote_ids it was given ({E(json.dumps(r6i['links']))}, audit.json) have no rank on any snapshot of the window, so R6 equals the headline. "
                   "T12.md names these ids; the D20b review shows that they are today's listings and that the old listings (which rank Mid in the window) are other quote_ids (Step 2 log, contract change 1). ")
    else:
        r6_note = f"R6 re-tagged {r6i['retagged_rows_in_evidence']} event rows (quote_ids {E(json.dumps(r6i['links']))}). "
    unr = "; ".join(f"{b}: {', '.join(bk[b]['unranked_stocks'])}" for b in BOOKS if bk[b]["unranked_stocks"]) or "none at the events of this run"
    cv_ = lambda k_: (caveats[k_][:1].upper() + caveats[k_][1:].rstrip(";").rstrip() + ".") if len(caveats) > k_ else ""   # a caveat as a sentence
    careful = (f'<h3>What to be careful about (read before the numbers)</h3><ul>'
               f'<li><b>Every tag in this window is a market-cap rank tag</b> (real index membership is used only from 2026-04-09). {E(cv_(1))} {E(cv_(0))} {E(cv_(2))}</li>'
               f'<li><b>Two holdings have no rank.</b> {E(cv_(3))} At this run\'s events: {E(unr)}. {r6_note}R6 reads them by their other listing: '
               + "; ".join(f"{b} C1 {bk[b]['r6']['pct']:.1f} (headline {bk[b]['n46_pct_cagr']:.1f}), C3 {100 * bk[b]['r6']['c3']:+.2f} pp (headline {100 * bk[b]['c3_diff']:+.2f})" for b in R6B if bk[b]["r6"]) + '.</li>'
               f'<li><b>Tags are up to about a month old.</b> They are read only at events, from the latest month-end snapshot on or before the session before the trade, and do not change between events.</li>'
               f'<li><b>There is no published NAV before 2019-01-02.</b> "Hold the parent" here is {PARENT_NOTE}; no rebuild in this window is checked against a published series. V4(a) checks the same code on 2019, where T07\'s and T06\'s stored NAVs exist.</li>'
               f'<li><b>The null is "drop a random set of the same weight at the same events".</b> A pass on C1 says the tag chooses better than a random set of the same size, not that it beats holding the whole book or the parent; C3 and the constant mix answer that.</li>'
               f'<li><b>Nothing is out of sample.</b> T07\'s, Study 3\'s and T09\'s results were seen before the design was frozen; the signals of these weeks were seen in T09. T11\'s headline evidence existed when this run started: {E(str(data["t11_seen_at_run"]))}.</li>'
               f'<li><b>{bk[BOOKS[0]]["full_stretches"]} disagreement stretches</b> is all the evidence there is. The smallest return edge detectable at 80% power against N4.6 is {min(bk[b]["n46_mde_cagr_pp"] for b in BOOKS):.1f} to {max(bk[b]["n46_mde_cagr_pp"] for b in BOOKS):.1f} pp a year, '
               f'and N4.6 draws from only {min(bk[b]["allowed"]["min"] for b in BOOKS)} to {max(bk[b]["allowed"]["max"] for b in BOOKS):,} allowed subsets per event.</li></ul>')
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>T12 segment holding 2014-19</title><style>{CSS}</style></head><body><main>
<p class="eyebrow">AA · T12 · segment holding before the published NAVs · pre-registration sha256 {E(sha[:12])} · data: APPROVED_DATA.md as of {E(str(asof_file))}</p>
<h1>Does holding each stock only while its own market-cap index is BUY choose <em>what to hold</em> better than a random exclusion of the same weight, on 2014-09-01 → 2019-01-02?</h1>
<p class="meta">{start3} → {end_date} (every book) · four real parents of the AA books · decisions every Friday, trades next session at OHLC4 · 10.4 bps a side · {ND:,} draws per book, cost and null · every number is computed from <code>evidence/{E(ev_dir.name)}/</code> · run on {E(str(data['as_of_inputs']))} data</p>
<h2 id="answer">The answer</h2>{answer}
{careful}
{table(summ_rows, ["Book", "Rule CAGR", "CAGR pct vs N4.6", "p", "CAGR pct vs N4.8", "Rule worst fall", "Drawdown pct vs N4.6", "Drawdown pct vs N4.8", "Rule minus whole-book (pp)", "R2 CAGR", "R2 pct vs N4.6"])}
<p class="cap">Percentile = share of the {ND:,} draws the rule beats (ties count half). Pass mark: 90 in at least 3 of 4 books against N4.6. After 20.8 bps round-trip cost. Full window {start3} → {end_date}; R2 = {r2_first} → {end_date}. The four books share one market, one set of signals and one list of signal dates.</p>
{table(verdict_rows, ["Criterion (after 20.8 bps, 4 books)", "Verdict", "Books passing", "Beside it"])}

<h2 id="data">The data</h2>
<p>Each parent's NAV is rebuilt every day from its own stocks (Eikon prices, price return, Polyplex's special dividend corrected), not read from a file: there is no published NAV before 2019-01-02. Every file below is an APPROVED row of <code>data/APPROVED_DATA.md</code>, whose "As of" date is <b>{E(str(asof_file))}</b> (the run recorded {E(str(asof_inputs))}). No price after {end_date} is read in the T12 window (V4(a) reads 2019 on its own).</p>
<p><b>Periods.</b> <i>Full window</i>: {start3} → {end_date}, {weeks[BOOKS[0]]} weekly decisions, the same for every book. <i>R2</i>: {r2_first} → {end_date} (the first session on or after {R2_START}), its own events and null.</p>
{table(inp_rows, ["File (relative to AA/)", "Through", "Approved row", "sha256 (first 16)"])}
<p><b>Caveats of the tag data</b> (T12.md section 3, from the independent reviews <code>data/review/2026-11-17_mcap_pre2018/REVIEW.md</code> and <code>data/review/2026-11-12_tag_sources/REVIEW.md</code>):</p>
<ol>{"".join(f"<li>{E(c_)}</li>" for c_ in caveats)}</ol>
<p><b>Tag source of the exposure</b> (share of listed weight × sessions, full window, by the source of the tag; membership tags start on 2026-04-09 and cannot occur here):</p>
{table(ts_rows, ["Book", "rank %", "unranked %", "membership %", "nonmember_rank %", "Unranked event rows", "Unranked stocks"])}
<p class="cap">Stand-ins (audit.json): {E(json.dumps(au.get("standins"), default=str))}. Other caveats, disclosed: the LBES file's rows have no recorded source (F-AA-D09); the Master rows are a production backfill; D18 holds manual Eikon exports for some stocks (F-AA-D01); the planted-effect control is not run.</p>
<p><b>Regression and identities</b> (gate V4; there is no published NAV before 2019-01-02, so T07's G0 check cannot be made):</p>
{table(v4rows, ["Check", "Compared", "Worst relative difference", "Result"])}
<p><b>Validity gates</b> (from <code>analysis.log</code>; the page is only to be read if all seven pass):</p>
{table(gate_rows, ["Gate", "Result", "What it checks"])}
<p><b>Controls.</b> V6, the negative control: 100 circular shifts of the joint three-signal weekly matrix (information-free signals that look like the real ones), each run through the rule and judged against its own N4.6 null; a book passes if at most {v6_xmax(100)} of the 100 reach the 90th percentile of CAGR ({v6_xmax(100)} is the largest count that chance, at 10% a shift, produces with probability at least 0.05 ÷ 4: a one-sided exact binomial test across the four books; T07's amended rule, fixed in T12.md before any T12 number existed). {('<b class="bad">V6 FAILS for ' + ', '.join(v6bad) + ': by the pre-registration nothing on this page may be read until it is fixed and rerun as a new run directory.</b>') if v6bad else ''}</p>
{table(v6rows, ["Book", "Shifted signal sets (K)", "Reaching percentile ≥ 90", "Allowed", "V6"]) if v6rows else "<p>controls_negative.csv missing.</p>"}
<p>V7, the positive control: at every event the oracle drops the allowed subset with the lowest sum of listed weight × realised log return to the next event; its CAGR percentile against N4.6 must be at least 99 in every book.</p>
{table(v7rows, ["Book", "Oracle CAGR", "Percentile (engine)", "Percentile (recomputed against draws.csv)", "V7"]) if v7rows else "<p>controls_oracle.json missing.</p>"}
<p><b>Reportability</b> (a realisation needs at least 5 separate disagreement stretches and at least 6 events with 0 &lt; equity share &lt; 1):</p>
{table(rep_rows, ["Book", "Window", "Weekly decisions", "Weeks the signals disagree", "Stretches", "Events", "Events with partial equity", "Verdict"])}

<h2 id="one">One rule, end to end ({ex['book']}, 20.8 bps, {ex['path_start']} → {ex['path_end']})</h2>
<p><b>1. The decision and the event.</b> The latest weekly decision before the event is week {ex['decision_week']}, {E(ex['decision_date'])}: the latest Master rows read Nifty 100 {E(ex['signs'][0])} (row {E(ex['labels'][0])}), Midcap 100 {E(ex['signs'][1])} ({E(ex['labels'][1])}), Smallcap 100 {E(ex['signs'][2])} ({E(ex['labels'][2])}).
Event {ex['pos']} of {ex['n_events']} (kind: {E(ex['kind'])}) is traded on session {E(ex['trade_date'])} (index {ex['trade_idx']}); its information date is the session before, {E(ex['info_date'])}; the basket in force became available on {E(ex['basket_eff'])}. Its states: Nifty 100 {E(ex['states'][0])}, Midcap 100 {E(ex['states'][1])}, Smallcap 100 {E(ex['states'][2])}.</p>
<div class="formula">band on  ⇔  SIGN of its index (latest Master row dated on or before the decision date) = BUY      Large → Nifty 100, Mid → Midcap 100, Small and below → Smallcap 100
kept stock → V × listed weight       dropped stock → its weight goes half to GOLDBEES, half to cash</div>
<p><b>2. The tag of every held stock</b>, read as of the information date from the latest month-end market-cap snapshot on or before it ({n_held} stocks held; rank 1-100 Large, 101-250 Mid, above 250 Small and below):</p>
{table(ex_tab, ["Stock", "ISIN", "Listed weight", "Band", "Tag source", "Snapshot used", "Rank", "Found by", "Band's signal", "Kept?"])}
<p><b>3. The targets.</b> The listed weights of a basket are renormalised to a row sum of 1 (as T06 and T07), so Σw = 1. Sum of listed weights Σw = {ex['sum_w']:.6f}; weight dropped D = {ex['D']:.6f} ({ex['n_dropped']} of {ex['n_held']} stocks); s = D ÷ Σw = {ex['s']:.6f}. Kept stock i gets V × w_i; GOLDBEES and cash units each get V × s ÷ 2 = V × {ex['s'] / 2:.6f}; every new position is then scaled by (V − cost) ÷ V.</p>
<div class="formula">s = D ÷ Σw          GOLDBEES target = cash target = V × s ÷ 2          stock i (kept) target = V × w_i</div>
<p><b>4. The trade.</b> On {E(ex['trade_date'])} at each instrument's (open + high + low + close) ÷ 4: value before cost V = {ex['V']:.6f}; value traded (both sides) {ex['traded']:.6f}; cost = traded × 20.8 ÷ 2 ÷ 10,000 = {ex['traded'] * 20.8 / 2 / 10000:.6f} (engine: {ex['cost']:.6f}).</p>
<p><b>5. Daily value.</b> NAV(t) = Σ units × close(t) over stocks, GOLDBEES and cash. Around the trade, with the whole-book switch beside it:</p>
{table(nav_tab, ["Date", "Rule NAV", "Whole-book NAV"])}
<p><b>6. Statistics.</b> The path runs from 1.000000 on {ex['path_start']} to {ex['end_nav']:.6f} on {ex['path_end']}: {ex['sessions']} sessions, years = ({ex['sessions']} − 1) ÷ 252 = {(ex['sessions'] - 1) / 252:.4f}, CAGR = {ex['end_nav']:.4f}^(1 ÷ {(ex['sessions'] - 1) / 252:.4f}) − 1 = <b>{pc(ex['cagr'], 2)}</b>, worst fall {pc(ex['max_dd'], 2)}.</p>
<p><b>7. One N4.6 draw.</b> The null keeps this event, the stocks held and the weight the rule drops, and drops a random subset of about that weight instead: every subset whose listed weight is within τ = half the smallest listed weight = {ex['tau']:.6f} of D. The stocks are indexed in ISIN order, subsets are listed by increasing bitmask (bit i = stock i), and the draw takes element floor(u × count) of the list, with u the next <code>rng.random()</code> of <code>default_rng([{SEED}, 7, draw_id, book_no])</code>, one per event.</p>
<p>Here {ex['n_allowed']} of 2^{ex['n_held']} = {2 ** ex['n_held']} subsets are allowed. Draw 0 uses uniform number {ex['pos']} of {ex['n_events']}: u = {ex['u']:.6f}; index floor({ex['u']:.6f} × {ex['n_allowed']}) = {ex['pick']}; bitmask {ex['mask']}. It drops {E(", ".join(ex['draw_drops']) or "nothing")} (listed weight {ex['draw_weight']:.6f}), where the rule drops {E(", ".join(ex['rule_drops']) or "nothing")} (weight {ex['D']:.6f}); the gap {abs(ex['draw_weight'] - ex['D']):.6f} is within τ. The drops stored for draw 0 equal this replay: <b>{"yes" if ex['stored_equal'] else "NO"}</b>.</p>
<p>Over the whole window ({ex['path_start']} → {ex['path_end']}) draw 0 earns {pc(ex['d0']['n46']['cagr'], 2)} a year with a worst fall of {pc(ex['d0']['n46']['max_dd'], 2)} and {ex['d0']['n46']['trades']} trades (the rule: {ex['rule_trades']} trades); N4.8 draw 0 earns {pc(ex['d0']['n48']['cagr'], 2)}, worst fall {pc(ex['d0']['n48']['max_dd'], 2)}.</p>
<p><b>8. The ranking.</b> Against N4.6 the rule's CAGR beat {ex['rank']['n46']['worse']:,} of {ex['rank']['n46']['draws']:,} draws, tied {ex['rank']['n46']['tied']}, and was beaten by {ex['rank']['n46']['better']}: percentile = ({ex['rank']['n46']['worse']} + 0.5 × {ex['rank']['n46']['tied']}) ÷ {ex['rank']['n46']['draws']:,} × 100 = <b>{ex['rank']['n46']['percentile']:.2f}</b>; p-value = (1 + {ex['rank']['n46']['better']} + {ex['rank']['n46']['tied']}) ÷ ({ex['rank']['n46']['draws']:,} + 1) = {ex['rank']['n46']['p']:.4f}. Against N4.8: beat {ex['rank']['n48']['worse']:,}, tied {ex['rank']['n48']['tied']}, beaten by {ex['rank']['n48']['better']}: percentile <b>{ex['rank']['n48']['percentile']:.2f}</b>, p = {ex['rank']['n48']['p']:.4f}.</p>
<p><b>9. The comparators.</b> The whole-book switch holds every stock while all three signals are BUY and the 50/50 sleeve otherwise (T06's rule; T11's Part A on this window); the parent holds every stock throughout ({PARENT_NOTE}); the constant mix holds the rule's average share all the time. Their CAGRs and worst falls on the same dates are in the tables below.</p>

<h2 id="headline">Headline</h2>
<p>CAGR, after 20.8 bps, full window {start3} → {end_date}, against {ND:,} random exclusions of each kind. N4.6 decides. The parent column is {PARENT_NOTE}.</p>
{table(head_rows, ["Book", "Parent CAGR (rebuilt)", "Whole-book CAGR", "Rule CAGR", "N4.6 median", "Edge over N4.6 median", "Percentile vs N4.6", "p", "N4.8 median", "Percentile vs N4.8", "p"])}
<p>Maximum drawdown (shallower is better), same window and draws:</p>
{table(dd_rows, ["Book", "Parent worst fall (rebuilt)", "Whole-book worst fall", "Rule worst fall", "N4.6 median", "Percentile vs N4.6", "p", "N4.8 median", "Percentile vs N4.8", "p"])}
<p><b>C3</b>, the rule minus the whole-book switch (same prices, fills, costs and sleeve), after cost, {start3} → {end_date}. SE = standard error from a moving-block bootstrap of the paired daily returns (blocks of 20 sessions, 1,000 resamples, seed <code>default_rng([{SEED}, 20, book_no])</code>):</p>
{table(c3_rows, ["Book", "Whole-book CAGR", "Rule CAGR", "Rule minus whole-book (pp, 20.8 bps)", "SE (pp)", "Difference ÷ SE", "C3 sign", "At 0 bps (pp)", "At 50 bps (pp)"])}
<h3>Before and after cost, and the comparators ({start3} → {end_date})</h3>
{table(cost_rows, ["Book", "Strategy", "0 bps CAGR", "0 bps worst fall", "20.8 CAGR", "20.8 worst fall", "50 CAGR", "50 worst fall"])}
<p class="cap">The constant mix holds the rule's average share of NAV in the parent's stocks all the time and rebalances at each event; the 50/50 sleeve is the other end. Hold the parent is {PARENT_NOTE}.</p>
<h3>Secondary statistics, percentile against each null (20.8 bps, full window {start3} → {end_date})</h3>
{table(sec_rows, ["Null", "Book", "CAGR", "Maximum drawdown", "Calmar", "Volatility (lower better)", "Ulcer index (lower)", "Days ≥ 10% below peak (fewer)", "Longest under water (shorter)"])}

<h2 id="perbook">Per book: equity and drawdown against the whole-book switch and the parent</h2><div class="legend">{legend}</div>{curves_html}
<h2 id="nulls">Null distributions, N4.6 and N4.8 overlaid</h2>
<p>For each book the {ND:,} after-cost CAGRs and maximum drawdowns of both nulls on the same bins ({start3} → {end_date}). Blue = N4.6 (size-matched exclusion), orange = N4.8 (label permutation), black line = the rule, dashed = each null's median.</p>{hists}
<h2 id="bands">Weight by band</h2>
<p>At each event the engine tags every held stock Large, Mid or Small and below; each band follows its own index. Mean listed weight by band (event-weighted over the events, session-weighted with each event's weights held until the next event), the mean share of the book dropped from each band, and the mean share of the book kept (not sent to the sleeve), full window {start3} → {end_date}:</p>
{table(wb_rows, ["Book", "Large event-wtd %", "Mid", "Small and below", "Large session-wtd %", "Mid", "Small and below", "Large dropped %", "Mid", "Small and below", "Kept %"])}
{bands_html}
<h2 id="regime">The disagreement weeks</h2>
<p>The rule differs from the whole-book switch only when the three signals disagree. Below, for each book, the curves and the signals through time, and then every stretch of disagreement and how the rule did against the whole-book switch in it (the compounded return of the rule minus that of the whole-book switch over the stretch's sessions, in percentage points, 20.8 bps).</p>
{regime_html}
{table(stretch_tab, ["#", "First decision", "Last decision", "Weeks", "Patterns (Nifty 100, Midcap 100, Smallcap 100)", "Kind"] + [f"{b[-4:]} rule − whole-book (pp)" for b in BOOKS])}
<p class="cap">A stretch is a run of consecutive weekly decisions whose three signals are neither all BUY nor all SELL; its sessions run from the first decision's trade session to the next decision's. The stretches are the same in the four books; the independent unit of this test is the stretch, not the book. Kind: read from the signals just before and just after the stretch.</p>
{whywhole}
<h2 id="robust">Robustness (decides the finding's status, not the verdict)</h2>
<p><b>R1</b>, C1 and C2 percentiles at 0, 20.8 and 50 bps ({start3} → {end_date}); pass mark 90 in at least 3 of 4:</p>
{table(rob1, ["Book", "N4.6 C1 0", "C1 20.8", "C1 50", "C2 0", "C2 20.8", "C2 50", "N4.8 C1 0", "C1 20.8", "C1 50", "C2 0", "C2 20.8", "C2 50"])}
<p><b>R1, trades and cost paid</b> (full window, 20.8 bps; cost paid is the sum of the costs of all trades as a share of the starting NAV; the null redraws at every event, so its turnover can differ from the rule's):</p>
{table(r1trades, ["Book", "Rule trades", "Rule cost paid", "Whole-book trades", "Whole-book cost paid", "N4.6 median trades", "N4.8 median trades", "N4.6 median cost paid", "N4.8 median cost paid", "N4.6 trades ÷ rule", "N4.8 trades ÷ rule"])}
<p><b>R2 and R3</b>, 20.8 bps. R2: the sub-window {r2_first} → {end_date} with its own events and null (C1, C2 and C3; a book that fails the reportability gate shows blank). R3: the cash half of the sleeve is the desk's LIQUIDCASE file, full window {start3} → {end_date}, C1.</p>
{table(rob2, ["Book", "R2 C1 vs N4.6", "R2 C1 vs N4.8", "R2 C2 vs N4.6", "R2 C3 (pp)", "R2 rule CAGR", "R2 whole-book CAGR", "R3 C1 vs N4.6", "R3 C1 vs N4.8", "R3 rule CAGR"])}
<p class="cap">At ≥ 90: R2 C1 {V['R2_C1_N46']} of 4 against N4.6, {V['R2_C1_N48']} against N4.8; R2 C2 {V['R2_C2_N46']} of 4 against N4.6; R2 C3 above zero in {V['R2_C3']} of 4; R3 {V['R3_N46']} of 4 against N4.6, {V['R3_N48']} against N4.8.</p>
<p><b>R4</b>, agreement of the two nulls ({start3} → {end_date}, 20.8 bps; no pass mark): the rule's CAGR percentile and each null's spread of after-cost CAGR.</p>
{table(r4rows, ["Book", "N4.6 pct", "median", "SD (pp)", "5th pct", "95th pct", "N4.8 pct", "median", "SD (pp)", "5th pct", "95th pct", "N4.6 trades ÷ rule", "N4.8 trades ÷ rule"])}
<p><b>R5</b>, tag error ({start3} → {end_date}, 20.8 bps; at every event each rank-rule tag is replaced with probability 7.93% by one of the other two bands, the error rate of the rank rule against real membership measured in 2026 only; no pass mark): the rule's CAGR minus the whole-book switch's.</p>
{table(r5rows, ["Book", "Draws", "Unperturbed (pp)", "Mean (pp)", "5th pct (pp)", "Median (pp)", "95th pct (pp)", "Share of draws above zero"])}
<p><b>R6</b>, the two unranked holdings read by their other listing ({start3} → {end_date}, 20.8 bps; no pass mark): C1 against the realisation's own N4.6 draws, and C3, beside the headline numbers. {r6_note}</p>
{table(r6rows, ["Book", "Events", "Re-tagged event rows", "R6 rule CAGR", "Headline rule CAGR", "R6 C1 vs own N4.6", "Headline C1", "R6 C3 (pp)", "Headline C3 (pp)"]) if r6rows else "<p>No full_r6 rows in this run.</p>"}
{table(r6link_rows, ["Book", "Stock", "ISIN", "Source without R6", "Linked quote_id", "Information date", "Linked rank", "Linked band"]) if r6link_rows else "<p>r6_links.csv is empty or missing.</p>"}
<p><b>R7</b>, price quality ({start3} → {end_date}; descriptive, no pass mark): every held stock-day with an absolute one-day close move of 20% or more in D18, and the rule and the whole-book switch re-run with each listed day's return set to zero.</p>
{table(r7day_rows, ["Book", "Stock", "ISIN", "Date", "One-day move"]) if r7day_rows else "<p>No held stock-day moved 20% or more.</p>"}
{table(r7rows, ["Book", "Flagged days", "Rule CAGR", "Rule CAGR, R7", "Whole-book CAGR", "Whole-book CAGR, R7", "C3 (pp)", "C3, R7 (pp, 20.8 bps)", "C3, R7 (pp, 0 bps)"])}
<h2 id="beside">Beside T07 (2019-01-02 → 2026-10-30) and T11 (this window, the whole-book switch)</h2>
<p>Descriptive, no claim. T07 ran the same rule, nulls and criteria on the published-NAV years; its percentiles are recomputed here from its shipped evidence (<code>tests/T07/evidence/headline/</code>, full window, LBES cash, 20.8 bps). Different windows, different baskets and band mixes: the two are not one sample.</p>
{table(cmp_rows, ["Book", "T12 rule CAGR", "T07 rule CAGR", "T12 C1 vs N4.6", "T07 C1 vs N4.6", "T12 C1 vs N4.8", "T07 C1 vs N4.8", "T12 C2 vs N4.6", "T07 C2 vs N4.6", "T12 C3 (pp)", "T07 C3 (pp)"]) if cmp_rows else "<p>T07's evidence was not found.</p>"}
{t11_html}
<h2 id="power">Power</h2>
{table(mde_rows, ["Book", "Disagreement stretches", "Events with partial equity", "N4.6 SD CAGR (pp)", "MDE CAGR (pp)", "N4.6 SD worst fall (pp)", "MDE worst fall (pp)", "N4.8 SD CAGR (pp)", "MDE CAGR (pp)", "N4.8 SD worst fall (pp)", "MDE worst fall (pp)"])}
<p class="cap">MDE = 2.8 × the SD of the draws (80% power, two-sided 5%), per null, {start3} → {end_date}. The numbers did not exist when the pre-registration was written; its thresholds do not depend on them. The planted-effect control is not run.</p>
<p><b>The calibration ratio</b> (diagnostic, no pass mark): the SD of the null's after-cost CAGR divided by the standard error of the rule's CAGR minus the whole-book switch's (the bootstrap of C3). Below 1, the null is calmer than the real increment's own noise.</p>
{table(calib_rows, ["Book", "Null", "Null SD of CAGR (pp)", "SE of rule − whole-book (pp)", "Calibration ratio"])}
<p><b>Null spreads</b> of after-cost CAGR (20.8 bps, full window {start3} → {end_date}):</p>
{table(spread_rows, ["Book", "Null", "Min", "5th pct", "Median", "95th pct", "Max"])}
<p><b>N4.6 is random only at the partial events.</b> At {min(bk[b]['allowed']['ones'] for b in BOOKS)} to {max(bk[b]['allowed']['ones'] for b in BOOKS)} of the {min(bk[b]['allowed']['events'] for b in BOOKS)} to {max(bk[b]['allowed']['events'] for b in BOOKS)} events of a book on the full window only one subset is allowed (the rule drops nothing or everything, or only one subset fits), so the null makes the same choice as the rule there; it differs from the rule only at the {min(bk[b]['full_partial'] for b in BOOKS)} to {max(bk[b]['full_partial'] for b in BOOKS)} partial events.</p>
<p><b>How many random exclusions there are, and how close they stay to the rule's dropped weight</b> (full window {start3} → {end_date}): events, events where only one subset is allowed, the allowed subsets per event, log10 of the product of the counts (the number of distinct N4.6 draws), the rule's mean dropped weight per event D (listed weights), and for each null the mean dropped weight, the mean absolute gap to the rule's per event, and the largest gap in units of τ (N4.6 must be ≤ 1; N4.8 is not matched exactly).</p>
{table(al_rows, ["Book", "Events", "Events with 1 allowed subset", "Min", "Median", "Max", "log10 distinct draws", "Rule mean D", "N4.6 mean D", "N4.6 mean |gap|", "N4.6 max gap ÷ τ", "N4.8 mean D", "N4.8 mean |gap|", "N4.8 max gap ÷ τ"])}

<h2 id="defs">Definitions</h2>
<ul><li><b>Event</b>: a trade session on which targets are rebuilt: T0; a session after a weekly decision on which the set of stocks the current tags would drop differs from the set currently dropped; the first session on or after a basket's availableDate. Tags are read at events only, as of the session before.</li>
<li><b>Tag</b>: Large, Mid or Small and below, from the stock's market-cap rank on the latest month-end snapshot on or before the date (1 to 100, 101 to 250, above 250); a stock with no rank reads Small and below (unranked). Real index membership is used only from 2026-04-09, after this window.</li>
<li><b>Percentile</b>: (draws worse + 0.5 × draws tied) ÷ draws × 100, ties equal within a relative 1e-12. <b>p-value</b>: (1 + draws at least as good) ÷ (draws + 1).</li>
<li><b>CAGR</b>: NAV_end^(252 ÷ (sessions − 1)) − 1, daily NAV, after cost. <b>Worst fall</b> (maximum drawdown): the most negative NAV ÷ running peak − 1. Volatility: SD of daily returns × √252. Ulcer index: root mean square of the percentage drawdown. Calmar: CAGR ÷ |maximum drawdown|.</li>
<li><b>N4.6 size-matched random exclusion</b> (decides): at every event a random subset of the held stocks whose total listed weight is within τ = half the smallest listed weight of the weight the rule drops, uniform over all such subsets, redrawn at every event. Seed <code>default_rng([{SEED}, 7, draw_id, book_no])</code>.</li>
<li><b>N4.8 persistent label permutation</b> (beside it): one random score per ISIN per draw; at every event the held stocks are ranked by score and given the labels Large, Mid, Small and below in the rule's counts per band; the real signals act on the labels. Seed <code>default_rng([{SEED}, 8, draw_id, book_no])</code>.</li>
<li><b>Whole-book switch</b>: every stock follows the single state IN iff all three signals are BUY, else 50/50 GOLDBEES and cash (T06's rule). <b>C3</b>: the rule's after-cost CAGR minus the whole-book switch's. <b>MDE</b>: 2.8 × the SD of the draws' CAGR (or maximum drawdown). <b>R2</b>: {r2_first} → {end_date}. <b>Hold the parent</b>: {PARENT_NOTE}.</li></ul>
<p class="meta">Built by <code>tests/T12/report.py</code> from <code>evidence/{E(ev_dir.name)}/</code>. Methods: <code>evidence/METHODS.md</code>. Checked by <code>check_page.py</code>.</p>
<script type="application/json" id="page-data">{json.dumps(data)}</script>
<script type="application/json" id="lines-data">{json.dumps(lines_data, separators=(",", ":"))}</script>
<script type="application/json" id="bars-data">{json.dumps(bars_data, separators=(",", ":"))}</script>
<script type="application/json" id="band-data">{json.dumps(band_data, separators=(",", ":"))}</script>
<script type="application/json" id="regime-data">{json.dumps(regime_data, separators=(",", ":"))}</script>
<script>{LINES_JS}</script>
<script>{BARS_JS}</script>
<script>{BANDS_JS}</script>
<script>{REGIME_JS}</script>
</main></body></html>"""
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "report.html").write_text(page, encoding="utf-8")
    print(f"wrote {outdir / 'report.html'} ({len(page) / 1e3:.0f} kB)")


if __name__ == "__main__":
    main()
