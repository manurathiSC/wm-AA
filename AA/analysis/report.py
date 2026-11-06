# -*- coding: utf-8 -*-
"""
Phase 7 — assemble the findings into a self-contained HTML report.

Charts are hand-written inline SVG against CSS custom properties, so light and
dark are each selected rather than one being an automatic inversion of the
other. Colours come from the validated reference palette; every chart carries
direct labels (three light-mode slots sit below 3:1 on the light surface, so
the relief rule applies) and a table view beneath it.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from common import EVIDENCE_DIR

# Categorical slots 1-4 from the validated palette, light / dark steps.
SERIES = ["s1", "s2", "s3", "s4"]
ORDER = ["0042", "0043", "0044", "0045"]
PARENT_OF = {"0042": "0003", "0043": "0007", "0044": "0010", "0045": "0029"}


def pct(x: float, dp: int = 1, sign: bool = False) -> str:
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "&mdash;"
    s = f"{x * 100:+.{dp}f}" if sign else f"{x * 100:.{dp}f}"
    return f"{s}%"


def num(x: float, dp: int = 2) -> str:
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "&mdash;"
    return f"{x:.{dp}f}"


# ── SVG helpers ────────────────────────────────────────────────────────────
def _sc(v, d0, d1, p0, p1):
    if d1 == d0:
        return (p0 + p1) / 2
    return p0 + (v - d0) * (p1 - p0) / (d1 - d0)


def _nice(lo: float, hi: float, n: int = 5):
    if hi == lo:
        hi = lo + 1
    raw = (hi - lo) / n
    mag = 10 ** np.floor(np.log10(abs(raw)))
    step = min([1, 2, 2.5, 5, 10], key=lambda m: abs(m * mag - raw)) * mag
    lo2 = np.floor(lo / step) * step
    hi2 = np.ceil(hi / step) * step
    ticks = list(np.arange(lo2, hi2 + step / 2, step))
    return lo2, hi2, ticks


def grouped_bars(
    cats: list[str],
    series: dict[str, list[float]],
    *,
    width=760, height=300, fmt=lambda v: pct(v, 1, True),
    ylab="", pad_l=64, pad_r=16, pad_t=28, pad_b=46, color_by_sign=False,
    colors: list[str] | None = None,
) -> str:
    """
    Vertical grouped bars with 4px rounded data-ends and a 2px surface gap.

    `colors` pins each series to an explicit palette slot; without it slots are
    taken in order, which silently disagrees with any legend that names
    different slots.
    """
    keys = list(series)
    slots = colors or [SERIES[i % 4] for i in range(len(keys))]
    allv = [v for vs in series.values() for v in vs if np.isfinite(v)]
    lo, hi, ticks = _nice(min(min(allv), 0.0), max(max(allv), 0.0))
    x0, x1 = pad_l, width - pad_r
    y0, y1 = height - pad_b, pad_t
    gw = (x1 - x0) / len(cats)
    bw = min(38.0, (gw - 14) / max(len(keys), 1))
    zero = _sc(0, lo, hi, y0, y1)

    out = [f'<svg viewBox="0 0 {width} {height}" role="img" class="chart">']
    for t in ticks:
        y = _sc(t, lo, hi, y0, y1)
        out.append(f'<line class="grid" x1="{x0}" y1="{y:.1f}" x2="{x1}" y2="{y:.1f}"/>')
        out.append(f'<text class="tick tick-y" x="{x0 - 8}" y="{y + 4:.1f}">{fmt(t)}</text>')
    out.append(f'<line class="baseline" x1="{x0}" y1="{zero:.1f}" x2="{x1}" y2="{zero:.1f}"/>')

    for ci, c in enumerate(cats):
        cx = x0 + gw * ci + gw / 2
        span = bw * len(keys) + 2 * (len(keys) - 1)
        for ki, k in enumerate(keys):
            v = series[k][ci]
            if not np.isfinite(v):
                continue
            bx = cx - span / 2 + ki * (bw + 2)
            y = _sc(v, lo, hi, y0, y1)
            top, h = (min(y, zero), abs(y - zero))
            cls = (("pos" if v >= 0 else "neg") if color_by_sign else slots[ki])
            out.append(
                f'<rect class="bar {cls}" x="{bx:.1f}" y="{top:.1f}" width="{bw:.1f}" '
                f'height="{max(h,1):.1f}" rx="4"><title>{c} · {k}: {fmt(v)}</title></rect>'
            )
            ly = top - 6 if v >= 0 else top + h + 13
            out.append(
                f'<text class="dlabel" x="{bx + bw/2:.1f}" y="{ly:.1f}">{fmt(v)}</text>'
            )
        out.append(f'<text class="tick tick-x" x="{cx:.1f}" y="{y0 + 20}">{c}</text>')
    if ylab:
        out.append(f'<text class="axis-title" x="{x0}" y="{pad_t - 12}">{ylab}</text>')
    out.append("</svg>")
    return "\n".join(out)


def lines_chart(
    xs: list[float], series: dict[str, list[float]], *,
    width=760, height=320, fmt=lambda v: pct(v, 0, True), xlab="", ylab="",
    pad_l=64, pad_r=76, pad_t=28, pad_b=44, mark_x: float | None = None,
    x_tick_every: int = 1,
) -> str:
    allv = [v for vs in series.values() for v in vs if np.isfinite(v)]
    lo, hi, ticks = _nice(min(min(allv), 0.0), max(allv))
    x0, x1 = pad_l, width - pad_r
    y0, y1 = height - pad_b, pad_t
    out = [f'<svg viewBox="0 0 {width} {height}" role="img" class="chart">']
    for t in ticks:
        y = _sc(t, lo, hi, y0, y1)
        out.append(f'<line class="grid" x1="{x0}" y1="{y:.1f}" x2="{x1}" y2="{y:.1f}"/>')
        out.append(f'<text class="tick tick-y" x="{x0 - 8}" y="{y + 4:.1f}">{fmt(t)}</text>')
    zero = _sc(0, lo, hi, y0, y1)
    out.append(f'<line class="baseline" x1="{x0}" y1="{zero:.1f}" x2="{x1}" y2="{zero:.1f}"/>')

    if mark_x is not None:
        mx = _sc(mark_x, min(xs), max(xs), x0, x1)
        out.append(f'<line class="marker-v" x1="{mx:.1f}" y1="{y1}" x2="{mx:.1f}" y2="{y0}"/>')
        out.append(f'<text class="anno" x="{mx + 6:.1f}" y="{y1 + 12}">actual</text>')

    for xi, xv in enumerate(xs):
        if xi % x_tick_every:
            continue
        x = _sc(xv, min(xs), max(xs), x0, x1)
        out.append(f'<text class="tick tick-x" x="{x:.1f}" y="{y0 + 20}">{xv:g}</text>')

    ends: list[tuple[float, float, str, str]] = []
    for ki, (k, vs) in enumerate(series.items()):
        pts = [
            (_sc(xv, min(xs), max(xs), x0, x1), _sc(v, lo, hi, y0, y1))
            for xv, v in zip(xs, vs) if np.isfinite(v)
        ]
        d = " ".join(f"{'M' if i == 0 else 'L'}{x:.1f},{y:.1f}" for i, (x, y) in enumerate(pts))
        out.append(f'<path class="line {SERIES[ki % 4]}" d="{d}"/>')
        for (x, y), v in zip(pts, vs):
            out.append(
                f'<circle class="dot {SERIES[ki % 4]}" cx="{x:.1f}" cy="{y:.1f}" r="4">'
                f"<title>{k} · {fmt(v)}</title></circle>"
            )
        ends.append((pts[-1][0], pts[-1][1], k, SERIES[ki % 4]))

    # Nudge end-labels apart so near-equal series stay legible.
    ends.sort(key=lambda e: e[1])
    min_gap = 14.0
    for i in range(1, len(ends)):
        if ends[i][1] - ends[i - 1][1] < min_gap:
            x, _, k, c = ends[i]
            ends[i] = (x, ends[i - 1][1] + min_gap, k, c)
    for x, y, k, c in ends:
        out.append(f'<text class="slabel {c}" x="{x + 8:.1f}" y="{y + 4:.1f}">{k}</text>')

    if ylab:
        out.append(f'<text class="axis-title" x="{x0}" y="{pad_t - 12}">{ylab}</text>')
    if xlab:
        out.append(f'<text class="axis-title" x="{(x0+x1)/2:.0f}" y="{height - 8}" '
                   f'text-anchor="middle">{xlab}</text>')
    out.append("</svg>")
    return "\n".join(out)


def scatter_chart(
    pts: list[tuple[float, float, str]], *,
    width=760, height=340, xlab="", ylab="",
    pad_l=70, pad_r=30, pad_t=28, pad_b=52,
) -> str:
    xsv = [p[0] for p in pts]
    ysv = [p[1] for p in pts]
    xlo, xhi, xt = _nice(min(min(xsv), 0), max(max(xsv), 0))
    ylo, yhi, yt = _nice(min(min(ysv), 0), max(max(ysv), 0))
    x0, x1 = pad_l, width - pad_r
    y0, y1 = height - pad_b, pad_t
    out = [f'<svg viewBox="0 0 {width} {height}" role="img" class="chart">']
    for t in yt:
        y = _sc(t, ylo, yhi, y0, y1)
        out.append(f'<line class="grid" x1="{x0}" y1="{y:.1f}" x2="{x1}" y2="{y:.1f}"/>')
        out.append(f'<text class="tick tick-y" x="{x0-8}" y="{y+4:.1f}">{pct(t,0,True)}</text>')
    for t in xt:
        x = _sc(t, xlo, xhi, x0, x1)
        out.append(f'<text class="tick tick-x" x="{x:.1f}" y="{y0+20}">{pct(t,0,True)}</text>')
    zx = _sc(0, xlo, xhi, x0, x1)
    zy = _sc(0, ylo, yhi, y0, y1)
    out.append(f'<line class="baseline" x1="{x0}" y1="{zy:.1f}" x2="{x1}" y2="{zy:.1f}"/>')
    out.append(f'<line class="baseline" x1="{zx:.1f}" y1="{y1}" x2="{zx:.1f}" y2="{y0}"/>')

    # Least-squares guide through the four points: the relationship is the point.
    b, a = np.polyfit(xsv, ysv, 1)
    gx = [xlo, xhi]
    gy = [a + b * g for g in gx]
    out.append(
        f'<path class="trend" d="M{_sc(gx[0],xlo,xhi,x0,x1):.1f},{_sc(gy[0],ylo,yhi,y0,y1):.1f} '
        f'L{_sc(gx[1],xlo,xhi,x0,x1):.1f},{_sc(gy[1],ylo,yhi,y0,y1):.1f}"/>'
    )
    for i, (xv, yv, lab) in enumerate(pts):
        x = _sc(xv, xlo, xhi, x0, x1)
        y = _sc(yv, ylo, yhi, y0, y1)
        out.append(
            f'<circle class="pt {SERIES[i % 4]}" cx="{x:.1f}" cy="{y:.1f}" r="8">'
            f"<title>{lab}: selection {pct(xv,1,True)}, overlay {pct(yv,1,True)}</title></circle>"
        )
        out.append(f'<text class="dlabel-lg" x="{x:.1f}" y="{y - 14:.1f}">{lab}</text>')
    out.append(f'<text class="axis-title" x="{x0}" y="{pad_t-12}">{ylab}</text>')
    out.append(f'<text class="axis-title" x="{(x0+x1)/2:.0f}" y="{height-8}" '
               f'text-anchor="middle">{xlab}</text>')
    out.append("</svg>")
    return "\n".join(out)


def heatmap(
    rows: list[str], cols: list[str], vals: list[list[float]], *,
    width=620, cell=64, rowlab="", collab="", diag_ring=True,
    labels: list[list[str]] | None = None,
    tip: str = "signal {r} on parent {c}", unit: str = " p.a.",
) -> str:
    """
    Diverging cell grid, colour keyed to `vals` and centred on zero.

    `labels` overrides the printed cell text without touching the colour scale,
    which is what a metric centred somewhere other than zero needs: pass the
    signed distance from the centre as `vals` and the readable figure as
    `labels`, so nobody has to add 50 in their head.
    """
    pad_l, pad_t = 96, 52
    height = pad_t + cell * len(rows) + 34
    m = max(abs(v) for r in vals for v in r if np.isfinite(v)) or 1.0
    out = [f'<svg viewBox="0 0 {width} {height}" role="img" class="chart">']
    for cj, c in enumerate(cols):
        x = pad_l + cj * cell + cell / 2
        out.append(f'<text class="tick tick-x" x="{x:.1f}" y="{pad_t-10}">{c}</text>')
    out.append(f'<text class="axis-title" x="{pad_l}" y="{pad_t-32}">{collab}</text>')
    for ri, r in enumerate(rows):
        y = pad_t + ri * cell
        out.append(f'<text class="tick tick-y" x="{pad_l-12}" y="{y+cell/2+4:.1f}">{r}</text>')
        for cj, c in enumerate(cols):
            v = vals[ri][cj]
            x = pad_l + cj * cell
            ratio = abs(v) / m
            bin_ = 1 if ratio < 0.2 else 2 if ratio < 0.45 else 3 if ratio < 0.7 else 4
            sign = "pos" if v >= 0 else "neg"
            ring = ' data-own="1"' if diag_ring and ri == cj else ""
            out.append(
                f'<rect class="cell hm-{sign}-{bin_}" x="{x+1}" y="{y+1}" '
                f'width="{cell-2}" height="{cell-2}" rx="4"{ring}>'
                f"<title>{tip.format(r=r, c=c)}: "
                f"{labels[ri][cj] if labels else pct(v,2,True) + unit}</title></rect>"
            )
            ink = "hm-ink-deep" if bin_ >= 3 else "hm-ink"
            txt = labels[ri][cj] if labels else f"{v*100:+.1f}"
            out.append(
                f'<text class="cellv {ink}" x="{x+cell/2:.1f}" y="{y+cell/2+4:.1f}">'
                f"{txt}</text>"
            )
    out.append(f'<text class="axis-title" x="6" y="{height-10}">{rowlab}</text>')
    out.append("</svg>")
    return "\n".join(out)


def small_multiples(panel: pd.DataFrame, *, width=760, ph=150) -> str:
    """One panel per pair: the AA index against its parent, weekly."""
    wk = panel.resample("W").last().dropna(how="all")
    pad_l, pad_r, pad_t, pad_b, gap = 52, 96, 22, 20, 16
    height = len(ORDER) * (ph + gap)
    out = [f'<svg viewBox="0 0 {width} {height}" role="img" class="chart">']
    for i, aa in enumerate(ORDER):
        pa = PARENT_OF[aa]
        top = i * (ph + gap)
        a = wk[f"lvl_SCMO_{aa}"]
        p = wk[f"lvl_SCMO_{pa}"]
        lo, hi, ticks = _nice(min(a.min(), p.min()), max(a.max(), p.max()), 3)
        x0, x1 = pad_l, width - pad_r
        y0, y1 = top + ph - pad_b, top + pad_t
        for t in ticks:
            y = _sc(t, lo, hi, y0, y1)
            out.append(f'<line class="grid" x1="{x0}" y1="{y:.1f}" x2="{x1}" y2="{y:.1f}"/>')
            out.append(f'<text class="tick tick-y" x="{x0-8}" y="{y+4:.1f}">{t:g}</text>')
        n = len(a)
        for name, s, cls in ((aa, a, "s1"), (pa, p, "s2")):
            d = " ".join(
                f"{'M' if j == 0 else 'L'}{_sc(j,0,n-1,x0,x1):.1f},{_sc(v,lo,hi,y0,y1):.1f}"
                for j, v in enumerate(s.values)
            )
            out.append(f'<path class="line thin {cls}" d="{d}"><title>{name}</title></path>')
            out.append(
                f'<text class="slabel {cls}" x="{x1+8}" '
                f'y="{_sc(s.values[-1],lo,hi,y0,y1)+4:.1f}">{name}</text>'
            )
        out.append(f'<text class="panel-title" x="{x0}" y="{top+14}">'
                   f"AA {aa} vs parent {pa}</text>")
    out.append("</svg>")
    return "\n".join(out)


def table(df: pd.DataFrame, cols: list[tuple[str, str, object]], *, cls="") -> str:
    th = "".join(f"<th>{h}</th>" for _, h, _ in cols)
    body = []
    for _, r in df.iterrows():
        tds = []
        for key, _, f in cols:
            v = r[key]
            tds.append(f"<td>{f(v) if callable(f) else v}</td>")
        body.append("<tr>" + "".join(tds) + "</tr>")
    return (f'<div class="tw"><table class="{cls}"><thead><tr>{th}</tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table></div>')


def details(label: str, inner: str) -> str:
    return f"<details><summary>{label}</summary>{inner}</details>"


FONTS = (
    '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?'
    "family=IBM+Plex+Mono:wght@400;500&"
    "family=IBM+Plex+Sans:wght@400;500;600&"
    "family=Newsreader:opsz,wght@6..72,400;6..72,500;6..72,600&display=swap\">"
)

# Neutrals are cool-biased toward the blue accent rather than inherited warm
# greys; the series hues are the validated set and are re-checked against these
# surfaces (light #fcfcfd, dark #16181d) before shipping.
CSS = """
:root{
  --page:#f6f7f9; --surface-1:#fcfcfd; --band:#eceff4;
  --text-primary:#101319; --text-secondary:#4a5160; --muted:#7d8595;
  --grid:#e3e6ec; --baseline:#c4c9d4; --border:rgba(16,19,25,.11);
  --pos:#2a78d6; --neg:#e34948;
  --s1:#2a78d6; --s2:#eb6834; --s3:#1baf7a; --s4:#eda100;
  --hm-pos-1:#e7effa; --hm-pos-2:#9ec5f4; --hm-pos-3:#2a78d6; --hm-pos-4:#184f95;
  --hm-neg-1:#fbeceb; --hm-neg-2:#f2b3b2; --hm-neg-3:#e34948; --hm-neg-4:#a52c2b;
  --hm-ink:#101319; --hm-ink-deep:#ffffff;
  --serif:"Newsreader",Georgia,"Times New Roman",serif;
  --sans:"IBM Plex Sans",system-ui,-apple-system,"Segoe UI",sans-serif;
  --mono:"IBM Plex Mono",ui-monospace,"SFMono-Regular",Consolas,monospace;
}
@media (prefers-color-scheme: dark){ :root:not([data-theme="light"]){
  --page:#0c0e12; --surface-1:#16181d; --band:#22252c;
  --text-primary:#f2f4f8; --text-secondary:#b3bac7; --muted:#7d8595;
  --grid:#262a32; --baseline:#3a3f4a; --border:rgba(242,244,248,.12);
  --pos:#3987e5; --neg:#e66767;
  --s1:#3987e5; --s2:#d95926; --s3:#199e70; --s4:#c98500;
  --hm-pos-1:#16273a; --hm-pos-2:#1c5cab; --hm-pos-3:#3987e5; --hm-pos-4:#86b6ef;
  --hm-neg-1:#33201f; --hm-neg-2:#8f3230; --hm-neg-3:#e66767; --hm-neg-4:#f2b3b2;
  --hm-ink:#f2f4f8; --hm-ink-deep:#101319;
}}
:root[data-theme="dark"]{
  --page:#0c0e12; --surface-1:#16181d; --band:#22252c;
  --text-primary:#f2f4f8; --text-secondary:#b3bac7; --muted:#7d8595;
  --grid:#262a32; --baseline:#3a3f4a; --border:rgba(242,244,248,.12);
  --pos:#3987e5; --neg:#e66767;
  --s1:#3987e5; --s2:#d95926; --s3:#199e70; --s4:#c98500;
  --hm-pos-1:#16273a; --hm-pos-2:#1c5cab; --hm-pos-3:#3987e5; --hm-pos-4:#86b6ef;
  --hm-neg-1:#33201f; --hm-neg-2:#8f3230; --hm-neg-3:#e66767; --hm-neg-4:#f2b3b2;
  --hm-ink:#f2f4f8; --hm-ink-deep:#101319;
}
*{box-sizing:border-box}
body{margin:0;background:var(--page);color:var(--text-primary);
  font-family:var(--sans);font-size:15.5px;line-height:1.65;
  -webkit-font-smoothing:antialiased}
.wrap{max-width:940px;margin:0 auto;padding:52px 24px 96px}
.eyebrow{font-family:var(--mono);font-size:11px;letter-spacing:.14em;
  text-transform:uppercase;color:var(--muted);margin:0 0 14px}
h1{font-family:var(--serif);font-size:44px;font-weight:500;line-height:1.08;
  margin:0 0 12px;letter-spacing:-.018em;text-wrap:balance;max-width:22ch}
.sub{font-family:var(--serif);font-size:20px;font-weight:400;line-height:1.4;
  color:var(--text-secondary);margin:0 0 14px;max-width:56ch}
.meta{font-family:var(--mono);color:var(--muted);font-size:11.5px;
  letter-spacing:.03em;margin:0 0 30px;padding-bottom:26px;
  border-bottom:1px solid var(--border)}
h2{font-family:var(--serif);font-size:28px;font-weight:500;margin:60px 0 10px;
  letter-spacing:-.012em;text-wrap:balance;max-width:34ch}
h3{font-size:15.5px;font-weight:600;margin:34px 0 8px;letter-spacing:-.002em}
h4{font-family:var(--mono);font-size:11.5px;font-weight:500;margin:30px 0 8px;
  letter-spacing:.06em;text-transform:uppercase;color:var(--text-secondary);
  max-width:68ch}
h3.fine{font-weight:600;color:var(--text-primary)}
p{margin:12px 0;max-width:68ch}
.lede{font-size:17.5px;line-height:1.6;color:var(--text-secondary);max-width:64ch}
ul,ol{margin:12px 0;padding-left:24px;max-width:68ch}
li{margin:7px 0}
.card{background:var(--surface-1);border:1px solid var(--border);border-radius:10px;
  padding:22px 22px 14px;margin:22px 0}
.chart{width:100%;height:auto;display:block;overflow:visible}
.grid{stroke:var(--grid);stroke-width:1}
.baseline{stroke:var(--baseline);stroke-width:1}
.marker-v{stroke:var(--muted);stroke-width:1;stroke-dasharray:3 3}
.trend{stroke:var(--baseline);stroke-width:1.5;stroke-dasharray:5 4;fill:none}
.tick{fill:var(--muted);font-family:var(--mono);font-size:10.5px}
.tick-y{text-anchor:end}.tick-x{text-anchor:middle}
.axis-title{fill:var(--text-secondary);font-family:var(--mono);font-size:10px;
  text-transform:uppercase;letter-spacing:.11em}
.panel-title{fill:var(--text-secondary);font-size:12px;font-weight:500}
.dlabel{fill:var(--text-secondary);font-family:var(--mono);font-size:10px;
  text-anchor:middle}
.dlabel-lg{fill:var(--text-primary);font-size:13px;text-anchor:middle;font-weight:600}
.slabel{font-family:var(--mono);font-size:11px;font-weight:500}
.anno{fill:var(--muted);font-family:var(--mono);font-size:10px}
.bar{stroke:var(--surface-1);stroke-width:2}
.bar.pos,.pt.pos{fill:var(--pos)}.bar.neg,.pt.neg{fill:var(--neg)}
.bar.s1,.pt.s1,.dot.s1{fill:var(--s1)}.bar.s2,.pt.s2,.dot.s2{fill:var(--s2)}
.bar.s3,.pt.s3,.dot.s3{fill:var(--s3)}.bar.s4,.pt.s4,.dot.s4{fill:var(--s4)}
.line{fill:none;stroke-width:2}.line.thin{stroke-width:1.6}
.line.s1{stroke:var(--s1)}.line.s2{stroke:var(--s2)}
.line.s3{stroke:var(--s3)}.line.s4{stroke:var(--s4)}
.slabel.s1{fill:var(--s1)}.slabel.s2{fill:var(--s2)}
.slabel.s3{fill:var(--s3)}.slabel.s4{fill:var(--s4)}
.dot,.pt{stroke:var(--surface-1);stroke-width:2}
.cell{stroke:var(--surface-1);stroke-width:2}
.cell[data-own="1"]{stroke:var(--text-primary);stroke-width:2}
.hm-pos-1{fill:var(--hm-pos-1)}.hm-pos-2{fill:var(--hm-pos-2)}
.hm-pos-3{fill:var(--hm-pos-3)}.hm-pos-4{fill:var(--hm-pos-4)}
.hm-neg-1{fill:var(--hm-neg-1)}.hm-neg-2{fill:var(--hm-neg-2)}
.hm-neg-3{fill:var(--hm-neg-3)}.hm-neg-4{fill:var(--hm-neg-4)}
.cellv{font-family:var(--mono);font-size:11.5px;text-anchor:middle;font-weight:500}
.hm-ink{fill:var(--hm-ink)}.hm-ink-deep{fill:var(--hm-ink-deep)}
.legend{display:flex;flex-wrap:wrap;gap:18px;margin:2px 0 14px;
  font-family:var(--mono);font-size:11px;color:var(--text-secondary);
  letter-spacing:.02em}
.key{display:inline-flex;align-items:center;gap:7px}
.sw{width:10px;height:10px;border-radius:2px;display:inline-block;flex:none}
.tw{overflow-x:auto;margin:16px 0}
table{border-collapse:collapse;width:100%;font-size:13px;
  font-variant-numeric:tabular-nums}
th,td{text-align:right;padding:8px 11px;border-bottom:1px solid var(--border);
  white-space:nowrap}
td{font-family:var(--mono);font-size:12.5px}
th{color:var(--muted);font-family:var(--mono);font-weight:500;font-size:10.5px;
  text-transform:uppercase;letter-spacing:.08em;
  border-bottom:1px solid var(--baseline)}
th:first-child,td:first-child{text-align:left}
td:first-child{font-family:var(--sans);font-weight:500}
tbody tr:hover{background:var(--band)}
details{margin:14px 0}
summary{cursor:pointer;color:var(--text-secondary);font-size:13px;padding:6px 0;
  user-select:none;border-bottom:1px solid var(--border);max-width:68ch}
summary:hover{color:var(--text-primary)}
summary:focus-visible,a:focus-visible{outline:2px solid var(--pos);
  outline-offset:2px;border-radius:2px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(196px,1fr));
  gap:14px;margin:28px 0 34px}
.tile{background:var(--surface-1);border:1px solid var(--border);
  border-radius:10px;padding:17px 18px}
.tile .k{font-family:var(--mono);font-size:10px;color:var(--muted);
  text-transform:uppercase;letter-spacing:.1em;margin-bottom:10px;line-height:1.4}
.tile .v{font-family:var(--serif);font-size:32px;font-weight:500;
  letter-spacing:-.02em;line-height:1.05}
.tile .n{font-size:12.5px;color:var(--text-secondary);margin-top:7px;
  line-height:1.45}
.callout{border-left:2px solid var(--pos);background:var(--surface-1);
  padding:16px 20px;margin:24px 0;border-radius:0 8px 8px 0;max-width:70ch}
.callout.warn{border-left-color:var(--neg)}
.callout p{margin:7px 0;max-width:none}
.cap{color:var(--muted);font-size:12.5px;margin:10px 0 2px;max-width:72ch;
  line-height:1.55}
code{background:var(--band);padding:2px 5px;border-radius:3px;
  font-family:var(--mono);font-size:12px}
.formula{background:var(--surface-1);border:1px solid var(--border);
  border-radius:8px;padding:16px 20px;margin:18px 0;font-family:var(--mono);
  font-size:12.5px;line-height:1.7;overflow-x:auto;max-width:none}
.fine{color:var(--text-secondary);font-size:13.5px}
hr{border:0;border-top:1px solid var(--border);margin:52px 0}
@media (prefers-reduced-motion: reduce){*{transition:none!important;
  animation:none!important}}
@media (max-width:640px){
  h1{font-size:33px}h2{font-size:23px}.wrap{padding:36px 18px 70px}
  .sub{font-size:17px}
}
"""


def legend(items: list[tuple[str, str]]) -> str:
    keys = "".join(
        f'<span class="key"><span class="sw" style="background:var(--{c})"></span>{n}</span>'
        for n, c in items
    )
    return f'<div class="legend">{keys}</div>'


def build(run: str) -> str:
    E = EVIDENCE_DIR / run
    attr = pd.read_csv(E / "attribution.csv")
    sc = pd.read_csv(E / "scorecard.csv")
    rank = pd.read_csv(E / "ranking.csv", index_col=0)
    mcap = pd.read_csv(E / "mcap_exposure.csv")
    ep = pd.read_csv(E / "episode_ledger.csv")
    eps = pd.read_csv(E / "episode_summary.csv")
    off = pd.read_csv(E / "offwindow_economics.csv")
    legs = pd.read_csv(E / "sleeve_legs.csv")
    nul = pd.read_csv(E / "null_random_timing.csv")
    stat = pd.read_csv(E / "static_mix_control.csv")
    lag = pd.read_csv(E / "lag_shift.csv")
    swap = pd.read_csv(E / "sleeve_swap.csv")
    grid = pd.read_csv(E / "cross_grid.csv")
    agree = pd.read_csv(E / "signal_agreement.csv", index_col=0)
    yr = pd.read_csv(E / "yearly_attribution.csv")
    conc = pd.read_csv(E / "time_concentration.csv")
    recon = pd.read_csv(E / "signal_reconciliation.csv")
    gpred = pd.read_csv(E / "gold_prediction_by_signal.csv")
    bsync = pd.read_csv(E / "basket_sync.csv")
    churn = pd.read_csv(E / "constituent_churn.csv")
    hold = pd.read_csv(E / "holdings_classification.csv")
    regspec = pd.read_csv(E / "regression_spec_comparison.csv")
    hwbasis = pd.read_csv(E / "highest_weight_policy_by_basis.csv")
    prank = pd.read_csv(E / "signal_policy_ranking.csv")
    pbook = pd.read_csv(E / "signal_policy_by_book.csv")
    sbp = pd.read_csv(E / "signal_by_parent_full.csv")
    stv = pd.read_csv(E / "sleeve_trend_variant.csv")
    psw = pd.read_csv(E / "supertrend_param_sweep.csv")
    onav = pd.read_csv(E / "own_nav_signal.csv")
    sgrid = pd.read_csv(E / "signal_grid.csv")
    own = pd.read_csv(E / "own_index_signal_test.csv")
    gdisp = pd.read_csv(E / "signal_grid_dispersion.csv")
    frac = pd.read_csv(E / "fractional_weight_cost.csv")
    gyear = pd.read_csv(E / "signal_grid_yearly.csv")
    sweep = pd.read_csv(E / "threshold_sweep.csv")
    gtime = pd.read_csv(E / "gold_timing.csv")
    sagree = pd.read_csv(E / "signal_agreement_single.csv")
    panel = pd.read_csv(E / "panel_daily.csv", index_col=0, parse_dates=True)
    audit = json.loads((E / "audit.json").read_text(encoding="utf-8"))

    for d in (attr, mcap, ep, eps, off, legs, nul, stat, lag, swap, conc,
              recon, sweep, gtime, sagree):
        for c in ("aa_label", "aa"):
            if c in d:
                d[c] = d[c].astype(str).str.zfill(4)
    for d in (sgrid, sbp, gdisp, gyear, frac):
        d["parent"] = d["parent"].astype(str).str.zfill(4)
    frac["aa"] = frac["aa"].astype(str).str.zfill(4)
    hold["period"] = np.where(hold["year"] == 0, "all", hold["year"].astype(str))
    for d in (hold, regspec, hwbasis):
        d["parent"] = d["parent"].astype(str).str.zfill(4)
    for d in (stv, onav, psw, bsync, pbook):
        for c in ("aa", "parent"):
            if c in d:
                d[c] = d[c].astype(str).str.zfill(4)

    def polname(p: str) -> str:
        if p == "realized":
            return "As run today"
        if p == "policy_highest_weight":
            return "Highest-weight index"
        if p.startswith("single::"):
            return "Only " + SHORT.get(p.split("::")[1], p.split("::")[1])
        a, b = p.split("::")[1].split("+")
        return f"{SHORT.get(a,a)} AND {SHORT.get(b,b)}"

    SHORT = {"nifty50": "N50", "nifty100": "N100", "nifty500_synth": "N500*",
             "midcap100": "MC100", "midcap150": "MC150", "smallcap100": "SC100",
             "smallcap250": "SC250", "microcap250": "Micro250"}
    for d in (mcap,):
        d["parent_label"] = d["parent_label"].astype(str).str.zfill(4)
    grid["signal_from"] = grid["signal_from"].astype(str).str.zfill(4)
    grid["parent"] = grid["parent"].astype(str).str.zfill(4)
    sc["portfolio"] = sc["portfolio"].apply(
        lambda v: str(v).zfill(4) if str(v).isdigit() else str(v)
    )
    rank.index = [str(i).zfill(4) for i in rank.index]
    agree.index = [str(i).zfill(4) for i in agree.index]
    agree.columns = [str(c).zfill(4) for c in agree.columns]

    A = attr.set_index("aa_label")
    M = mcap.set_index("aa_label")
    O = off.set_index("aa_label")
    L = legs.set_index("aa_label")
    N = nul.set_index("aa_label")
    S = stat.set_index("aa_label")
    C = conc.set_index("aa_label")
    SC = sc.set_index("portfolio")

    w = audit["window"]
    H: list[str] = []
    H.append("<title>Gold, Not Timing</title>")
    H.append(FONTS)
    H.append(f"<style>{CSS}</style>")
    H.append('<div class="wrap">')
    H.append('<p class="eyebrow">Research note &middot; Asset-allocation overlay</p>')
    H.append("<h1>Gold, Not Timing</h1>")
    H.append('<p class="sub">Where the asset-allocation overlay on SCMO_0042&ndash;0045 '
             "actually got its returns &mdash; and where it gave them away.</p>")
    H.append(f'<p class="meta">SCMO_0042&ndash;0045 vs SCMO_0003 / 0007 / 0010 / 0029 '
             f'&nbsp;&middot;&nbsp; {w["start"]} &rarr; {w["end"]} '
             f'&nbsp;&middot;&nbsp; {w["sessions"]} sessions &nbsp;&middot;&nbsp; gross</p>')

    # ── Headline ───────────────────────────────────────────────────────────
    H.append('<p class="lede">The overlay switches a parent equity basket into a '
             "gold-plus-cash sleeve when a market-cap-weighted supertrend signal "
             "weakens. Over this window it added 5.8 and 7.1 points a year to two "
             "portfolios and subtracted 4.5 and 3.7 from the other two. The "
             "decomposition below is exact, and it does not support the reading "
             "that good timing was responsible.</p>")

    H.append('<div class="tiles">')
    tiles = [
        ("Gold's share of the sleeve's gain", "84%", "",
         "of everything the defensive sleeve earned"),
        ("Gold's edge while actually held", "+12 pp", "up",
         "a year above its own average, for 0043 &mdash; but only 87th percentile"),
        ("Signal lag", "~5 weeks", "",
         "switching earlier would have beaten actual in every case"),
        ("Timing vs a random null", "z &le; 1.01", "",
         "no portfolio is statistically distinguishable"),
        ("Signal actually used by 0043", "1 index", "",
         "pure Smallcap 100 trend, not a market-cap blend"),
        ("0043's edge in one episode", "92%", "",
         "of its total risk-off value-add"),
    ]
    for k, v, cls, n in tiles:
        H.append(f'<div class="tile"><div class="k">{k}</div>'
                 f'<div class="v {cls}">{v}</div><div class="n">{n}</div></div>')
    H.append("</div>")

    H.append('<div class="callout"><p><strong>Every chart in this report has a '
             "written method.</strong> <code>evidence/main/METHODS.md</code> "
             "states, per section and per chart, exactly what is plotted, over "
             "which sessions and which denominator, the formula, the statistical "
             "test with its seed and draw count and minimum detectable effect, "
             "the generating script and evidence CSV, and the limitations of that "
             "specific number. Where two charts look alike but are computed on "
             "different bases &mdash; sections 4 and 5 especially &mdash; it "
             "reconciles them line by line. Read it before quoting anything "
             "here.</p></div>")

    # ── 1. The reframe ─────────────────────────────────────────────────────
    H.append("<h2>1. Two of the four overlays destroyed value</h2>")
    H.append("<p>The premise for this study was that all four asset-allocation "
             "versions outperformed. They did not. Measured against the parent "
             "each one is built on, the overlay helped 0042 and 0043 and hurt "
             "0044 and 0045.</p>")

    cats = ORDER
    H.append('<div class="card">')
    H.append(legend([("AA version", "s1"), ("Parent", "s2")]))
    H.append(grouped_bars(
        cats,
        {"AA": [SC.loc[a, "cagr"] for a in cats],
         "Parent": [SC.loc[PARENT_OF[a], "cagr"] for a in cats]},
        fmt=lambda v: pct(v, 0), ylab="CAGR", height=290,
    ))
    H.append('<p class="cap">Nifty 50 returned '
             f'{pct(SC.loc["Nifty 50","cagr"],1)} a year over the same window.</p>')
    H.append("</div>")

    H.append('<div class="card">')
    H.append(small_multiples(panel))
    H.append('<p class="cap">Index levels, both rebased to 100 at inception, '
             "sampled weekly. 0044 and 0045 track below their parents for most "
             "of the history.</p>")
    H.append("</div>")

    H.append(details(
        "Full scorecard &mdash; all eight portfolios, Nifty 50 and the three market-cap indices",
        table(sc, [
            ("portfolio", "Portfolio", None), ("kind", "Type", None),
            ("cagr", "CAGR", lambda v: pct(v, 1)),
            ("ann_vol", "Vol", lambda v: pct(v, 1)),
            ("sharpe_cagr_over_vol", "Return/Vol", lambda v: num(v, 2)),
            ("sortino", "Sortino", lambda v: num(v, 2)),
            ("calmar", "Calmar", lambda v: num(v, 2)),
            ("max_drawdown", "Max DD", lambda v: pct(v, 1)),
            ("up_capture", "Up cap", lambda v: num(v, 2)),
            ("down_capture", "Down cap", lambda v: num(v, 2)),
            ("beta", "Beta", lambda v: num(v, 2)),
        ])))

    H.append("<h3>Which one is &ldquo;best&rdquo; depends entirely on the yardstick</h3>")
    H.append("<p>0042 wins on both return and risk-adjusted return. 0043 is last "
             "on CAGR, second on return-per-unit-of-vol, and first on excess over "
             "its own parent &mdash; because its parent was the weakest of the four. "
             "All three columns are shown rather than one being picked.</p>")
    rk = rank.reset_index().rename(columns={"index": "aa"})
    H.append(table(rk, [
        ("aa", "AA", None),
        ("cagr", "CAGR", lambda v: pct(v, 1)),
        ("rank_cagr", "Rank", None),
        ("sharpe", "Return/Vol", lambda v: num(v, 2)),
        ("rank_sharpe", "Rank", None),
        ("excess_vs_parent", "Excess vs parent", lambda v: pct(v, 1, True)),
        ("rank_excess_vs_parent", "Rank", None),
    ]))

    # ── 2. Exact decomposition ─────────────────────────────────────────────
    H.append("<h2>2. The spread splits exactly into two parts</h2>")
    H.append("<p>An AA version holds <em>precisely</em> its parent when risk-on, so "
             "the difference between them is earned only on the days they differ. "
             "In log space the split is additive and therefore exact &mdash; it "
             f"reconciles to {2.8e-17:.0e} &mdash; with no residual term:</p>")
    H.append('<div class="formula">log(AA) &minus; log(parent)<br>'
             "&nbsp;&nbsp;= &Sigma;<sub>risk-on</sub> excess &nbsp;&rarr;&nbsp; TRACKING"
             "<br>&nbsp;&nbsp;+ &Sigma;<sub>risk-off</sub> excess &nbsp;&rarr;&nbsp; TIMING"
             "</div>")
    H.append("<p><strong>Tracking</strong> should be zero: while both are in "
             "equities they hold the same basket. It is not zero, and it cost "
             "0044 nearly 3 points a year, most of it inside one 93-session "
             "risk-on stretch in late 2022.</p>")
    H.append("<p>Comparing the AA books against the parents' own rebalance "
             "histories identifies the cause, and it is narrower than a general "
             "drift. The parents reconstitute <strong>quarterly</strong> (median "
             "gap 91 days, 19 rebalances in the window) and the AA books match "
             "them on 97&ndash;98% of holdings overall. But every AA version "
             "intermittently <strong>failed to adopt a reconstitution</strong>: "
             "on 2022-09-15 parent 0010 rotated six of fifteen names, and 0044 "
             "kept the old six until the end of October &mdash; 40% of the book "
             "wrong for ten weeks. All four desynchronised for the first time on "
             "the same date, 2022-09-19, and it recurs on 5&ndash;6% of "
             "in-equity reviews.</p>")
    H.append(table(bsync, [
        ("aa", "AA", None), ("parent", "Parent", None),
        ("parent_rebalances", "Parent rebals", None),
        ("parent_median_gap_days", "Median gap", lambda v: f"{v} d"),
        ("reviews_in_equity", "Reviews in equity", None),
        ("reviews_2plus_names_off", "Desynced", None),
        ("pct_reviews_off", "% desynced", lambda v: pct(v, 1)),
        ("max_names_off", "Worst names off", None),
        ("name_match_pct", "Name match", lambda v: pct(v, 1)),
        ("first_desync", "First desync", None),
    ]))
    H.append('<div class="callout warn"><p>This is an operational defect, not a '
             "property of the strategy: the overlay is meant to hold the parent "
             "verbatim when risk-on, and on these dates it did not. It is "
             "separable from every signal question in this report, and it is the "
             "cheapest thing on the list to fix &mdash; propagate the parent's "
             "quarterly reconstitution into the AA book on the same date, "
             "regardless of whether the allocation signal changed.</p></div>")

    H.append('<div class="card">')
    H.append(legend([("Tracking (risk-on)", "s3"), ("Timing (risk-off)", "s4")]))
    H.append(grouped_bars(
        cats,
        {"Tracking": [A.loc[a, "tracking_ann"] for a in cats],
         "Timing": [A.loc[a, "timing_ann"] for a in cats]},
        fmt=lambda v: pct(v, 1, True), ylab="Contribution p.a.", height=300,
        colors=["s3", "s4"],
    ))
    H.append('<p class="cap">0044 and 0045 both underperformed, for different '
             "reasons: 0044 mostly lost to tracking, 0045 almost entirely to timing.</p>")
    H.append("</div>")

    H.append(details("Attribution table", table(attr, [
        ("aa_label", "AA", None), ("parent_label", "Parent", None),
        ("aa_cagr", "AA CAGR", lambda v: pct(v, 2)),
        ("parent_cagr", "Parent CAGR", lambda v: pct(v, 2)),
        ("total_excess_ann", "Excess p.a.", lambda v: pct(v, 2, True)),
        ("tracking_ann", "Tracking p.a.", lambda v: pct(v, 2, True)),
        ("timing_ann", "Timing p.a.", lambda v: pct(v, 2, True)),
        ("pct_sessions_defensive", "% defensive", lambda v: pct(v, 1)),
    ])))

    # ── 3. The inverse relationship ────────────────────────────────────────
    H.append("<h2>3. The overlay helped exactly where the stock picking was bad</h2>")
    H.append("<p>Each parent's stock-selection skill is measured against its own "
             "implied market-cap blend &mdash; a non-negative, sum-to-one fit of "
             "its daily returns on Nifty 100, Midcap 150, Smallcap 250 and "
             "Microcap 250. Section 8 explains why all four factors are needed "
             "and why a holdings-based classification is not available over this "
             "window.</p>")
    H.append('<p class="cap"><strong>This table runs on a shorter window than the '
             "rest of the report: 1,138 sessions, 2022-01-11 to 2026-08-21, 4.61 "
             "years.</strong> The fit needs all four index returns present, and "
             "Nifty Microcap 250's history only starts 2022-01-10, so the first 47 "
             "sessions drop out. Adding the fourth factor was necessary &mdash; "
             "omitting it overstated selection alpha by 2&ndash;5 points (section "
             "8b) &mdash; but it costs the first two months. <strong>Do not mix "
             "these CAGRs with section 1's.</strong> 0007 reads 6.685% here and "
             "6.667% in the scorecard's full 1,185 sessions; both round to 6.7%, "
             "which is coincidence, not construction. Selection alpha is safe "
             "because parent and blend CAGR are computed on the same 1,138 "
             "sessions. Note the excluded stretch sits almost entirely inside the "
             "first risk-off episode for all four books, so this window quietly "
             "omits part of the overlay's worst start.</p>")
    H.append(table(mcap, [
        ("parent_label", "Parent", None),
        ("w_nifty100", "Nifty 100", lambda v: pct(v, 0)),
        ("w_midcap150", "Midcap 150", lambda v: pct(v, 0)),
        ("w_smallcap250", "Smallcap 250", lambda v: pct(v, 0)),
        ("w_microcap250", "Microcap 250", lambda v: pct(v, 0)),
        ("r_squared", "R&sup2;", lambda v: num(v, 2)),
        ("parent_cagr", "Parent CAGR", lambda v: pct(v, 1)),
        ("blend_cagr", "Blend CAGR", lambda v: pct(v, 1)),
        ("selection_alpha_ann", "Selection alpha", lambda v: pct(v, 1, True)),
    ]))
    H.append("<p>Two are microcap-and-smallcap books (0003, 0007) and two carry "
             "roughly half their risk in midcaps (0010, 0029). None is a "
             "large-cap book: Nifty 100 loadings run 0&ndash;21%. On selection, "
             "0007 &mdash; 0043's parent &mdash; gave up 7.7 points a year against "
             "its own blend and 0003 gave up 4.8, while 0010 and 0029 beat theirs "
             "by 3.0 and 2.4.</p>")

    H.append('<div class="card">')
    H.append(scatter_chart(
        [(M.loc[a, "selection_alpha_ann"], A.loc[a, "timing_ann"], a) for a in cats],
        xlab="Parent's stock-selection alpha p.a.",
        ylab="Overlay timing contribution p.a.",
    ))
    H.append('<p class="cap">The relationship is almost perfectly inverse. The '
             "overlay was worth most on the weakest stock engine and cost the most "
             "on the strongest &mdash; which is what a de-risking rule does, not "
             "what a skilled market-timing rule does.</p>")
    H.append("</div>")

    # ── 4. What actually happened ──────────────────────────────────────────
    H.append("<h2>4. While out of equity, equity mostly went up</h2>")
    H.append("<p>This is the central table. For the sessions each portfolio "
             "actually spent defensive, it shows what the parent did in the "
             "meantime and what the sleeve earned instead.</p>")
    H.append('<div class="card">')
    H.append(legend([("Parent while out", "s2"), ("Sleeve earned", "s1"),
                     ("Gold alone", "s4")]))
    H.append(grouped_bars(
        cats,
        {"Parent": [O.loc[a, "parent_return_while_out"] for a in cats],
         "Sleeve": [O.loc[a, "actual_sleeve_return_while_out"] for a in cats],
         "Gold": [O.loc[a, "gold_return_while_out"] for a in cats]},
        fmt=lambda v: pct(v, 0, True), ylab="Cumulative return over risk-off sessions",
        height=310, colors=["s2", "s1", "s4"],
    ))
    H.append('<p class="cap">Roughly two years of risk-off time per portfolio. In '
             "three of four cases the parent <em>rose</em> while the portfolio sat "
             "out of it.</p>")
    H.append('<p class="cap"><strong>What these are:</strong> cumulative '
             "(not annualised) returns of each asset, compounded over the "
             "534/539/482/491 sessions each book was defensive. The sessions are "
             "spliced from six or seven separate episodes, so &ldquo;2.12 "
             "years&rdquo; is <code>sessions / 252</code>, not an elapsed span. "
             "The sleeve here is the <em>realized</em> basket, whose composition "
             "changed twice. <strong>What these are not:</strong> excesses over "
             "the parent &mdash; that is section 5a, which is the same session "
             "set expressed as a ratio against the parent with a standardised "
             "sleeve, and is reconciled line by line in "
             "<code>METHODS.md</code>.</p>")
    H.append("</div>")
    H.append(details("Off-window economics", table(off, [
        ("aa_label", "AA", None), ("parent", "Parent", None),
        ("off_sessions", "Sessions out", None),
        ("off_years_equivalent", "Years", lambda v: num(v, 2)),
        ("parent_return_while_out", "Parent", lambda v: pct(v, 1, True)),
        ("actual_sleeve_return_while_out", "Sleeve", lambda v: pct(v, 1, True)),
        ("gold_return_while_out", "Gold", lambda v: pct(v, 1, True)),
        ("cash_return_while_out", "Cash", lambda v: pct(v, 1, True)),
        ("mechanism", "Mechanism", None),
    ])))

    H.append('<div class="callout warn"><p>The switch did not, in general, dodge a '
             "fall. It earned a better asset. For 0042 the parent gained "
             f'{pct(O.loc["0042","parent_return_while_out"],1,True)} during the '
             "very windows the portfolio was avoiding it, while the sleeve made "
             f'{pct(O.loc["0042","actual_sleeve_return_while_out"],1,True)} '
             "&mdash; because gold nearly doubled.</p></div>")

    H.append("<h3>Gold did 84% of the work</h3>")
    H.append('<div class="card">')
    H.append(legend([("Gold", "s4"), ("Cash", "s1"), ("Bonds", "s3")]))
    H.append(grouped_bars(
        cats,
        {"Gold": [L.loc[a, "gold_contrib_return"] for a in cats],
         "Cash": [L.loc[a, "liquid_contrib_return"] for a in cats],
         "Bonds": [L.loc[a, "bond_contrib_return"] for a in cats]},
        fmt=lambda v: pct(v, 0, True),
        ylab="Contribution to sleeve return", height=290,
        colors=["s4", "s1", "s3"],
    ))
    H.append('<p class="cap">Gold BeES compounded at 27.3% a year over this window. '
             "The sleeve's job was mostly to be holding it.</p>")
    H.append('<p class="cap"><strong>These are contributions, not leg '
             "returns.</strong> Each bar is the leg's return already scaled by how "
             "much of the <em>whole portfolio</em> sat in it. On a fully-defensive "
             "day the legs split the book between them &mdash; exactly a third each "
             "until Oct-2024, then half gold and half cash &mdash; so no leg is "
             "ever 100%. For 0042, gold held alone over those 534 sessions returned "
             "+101.7%, but at a one-third-to-one-half weight it <em>gave the "
             "portfolio</em> +38.3%. That is why these bars are smaller than the "
             "&ldquo;Gold alone&rdquo; bar above, and why the three of them sum to "
             "roughly the sleeve's own +46.3% rather than to anything larger.</p>")
    H.append("</div>")

    # ── 5. Was it skill? ───────────────────────────────────────────────────
    H.append("<h2>5. Four tests for whether the timing was skilled</h2>")

    H.append("<h3>a. Swap the sleeve</h3>")
    H.append("<p>If the edge were timing, it would survive changing what the "
             "portfolio switches <em>into</em>. It does not.</p>")
    sw = swap.pivot(index="sleeve", columns="aa_label", values="value_add_return")
    sw_order = ["all cash", "50/50 gold+cash", "all gold"]
    H.append('<div class="card">')
    H.append(legend([(a, s) for a, s in zip(cats, SERIES)]))
    H.append(grouped_bars(
        sw_order, {a: [sw.loc[s, a] for s in sw_order] for a in cats},
        fmt=lambda v: pct(v, 0, True), ylab="Overlay value-add vs parent", height=300,
    ))
    H.append('<p class="cap">Switching into cash alone, the overlay adds almost '
             "nothing to 0042 and loses money on 0044 and 0045. Every positive "
             "result depends on gold.</p>")
    H.append('<p class="cap"><strong>How this differs from section 4</strong>, '
             "which looks similar and reports different numbers: these are "
             "<em>excesses over the parent</em>, not asset levels, and the sleeve "
             "is a fixed 50/50 Gold BeES + cash reference rather than the realized "
             "basket, so the three arms are comparable. For a full switch the two "
             "sections are linked exactly by "
             "<code>(1+sleeve)/(1+parent) &minus; 1</code>: section 4's gold and "
             "parent figures give +79.17% for 0042 and +114.27% for 0043, which "
             "are the all-gold bars here to the last decimal. 0044 and 0045 do "
             "not reconcile that cleanly because they spent 27 and 58 sessions at "
             "a <em>half</em> defensive weight, so the ratio identity does not "
             "apply. Worked through in <code>METHODS.md</code>.</p>")
    H.append("</div>")

    H.append("<h4 class=\"fine\">A finding that fell out of reconciling these "
             "two charts</h4>")
    H.append("<p>Section 4 and this chart disagree for 0044 and 0045, and chasing "
             "the reason turned up something worth reporting on its own. Those two "
             "books did not always switch <em>fully</em>: 0044 spent 27 sessions "
             "and 0045 spent 58 sessions at a <strong>half</strong> defensive "
             "weight, with the other half still in equity. Forcing the switch to "
             "be complete over the very same dates reproduces section 4's ratio "
             "exactly, which confirms the half-sizing is the whole of the "
             "discrepancy &mdash; and prices what it cost.</p>")
    fr = frac[frac.half_weight_sessions > 0].copy()
    H.append(table(fr, [
        ("aa", "AA", None), ("sleeve", "Sleeve", None),
        ("half_weight_sessions", "Half-wt sessions", None),
        ("parent_over_half_sessions", "Parent over those", lambda v: pct(v, 1, True)),
        ("value_add_full_switch", "If fully switched", lambda v: pct(v, 2, True)),
        ("value_add_actual", "Actual", lambda v: pct(v, 2, True)),
        ("cost_of_half_sizing_pp", "Cost", lambda v: f"{v:+.2f} pp"),
    ]))
    H.append('<div class="callout warn"><p><strong>Both books were only half out '
             "of equity during the best window their own signal ever found.</strong> "
             "0044's 27 half-weight sessions run 2022-04-11 to 2022-08-05, over "
             "which its parent fell 8.1%; 0045's 58 run 2021-11-01 to 2022-05-06, "
             "over which its parent fell <strong>21.7%</strong> &mdash; while the "
             "sleeve was flat to slightly up. On the 50/50 sleeve that half-sizing "
             "alone takes 0045's overlay from <strong>+6.33% to &minus;6.27%</strong>: "
             "same signal, same dates, same sleeve, only the position size "
             "differs.</p><p>So part of why these two underperformed is not that "
             "the signal was wrong on those dates &mdash; it is that the book was "
             "half-committed when the signal was at its most right. Whether that "
             "was a deliberate ramp or an execution artefact cannot be settled from "
             "the weight files, and is worth asking the desk. Evidence: "
             "<code>fractional_weight_cost.csv</code>.</p></div>")

    H.append("<h3>b. Shift the timing</h3>")
    H.append("<p>Moving the realized state earlier or later shows whether the "
             "actual switch dates were well chosen.</p>")
    shifts = sorted(lag["shift_weeks"].unique())
    H.append('<div class="card">')
    H.append(lines_chart(
        [float(s) for s in shifts],
        {a: [lag[(lag.aa_label == a) & (lag.shift_weeks == s)]["value_add_return"].iloc[0]
             for s in shifts] for a in cats},
        xlab="Weeks the state is shifted (negative = act earlier)",
        ylab="Overlay value-add", mark_x=0.0, height=340,
    ))
    H.append('<p class="cap">The actual timing sits at or near the bottom of the '
             "curve for all four. Acting five weeks earlier would have been worth "
             "150 to 236 percentage points instead of &minus;5 to +61.</p>")
    H.append("</div>")
    H.append("<p>Acting earlier is not implementable &mdash; it uses information "
             "that did not exist yet &mdash; but it is diagnostic. The falls the "
             "signal was meant to avoid had largely already happened by the time "
             "it fired, and the portfolio then stayed defensive through the "
             "recovery. That is the classic lag of a trend-following filter, and "
             "it is visible in all four independently.</p>")

    H.append("<h3>c. Compare against holding the same amount of equity, statically</h3>")
    H.append("<p>A portfolio permanently holding the average defensive weight "
             "&mdash; no signal, no switching &mdash; is the control that asks "
             "whether timing beat simply de-risking.</p>")
    H.append(table(stat, [
        ("aa_label", "AA", None),
        ("avg_defensive_weight", "Avg defensive wt", lambda v: pct(v, 1)),
        ("overlay_value_add_return", "Overlay", lambda v: pct(v, 1, True)),
        ("static_same_exposure_value_add_return", "Static, same exposure",
         lambda v: pct(v, 1, True)),
        ("timing_premium_over_static_return", "Timing premium",
         lambda v: pct(v, 1, True)),
    ]))
    H.append("<p>Here the overlay does earn a premium over static de-risking for "
             "0042 and 0043 (about 28 and 30 points cumulative). This is the one "
             "test that is favourable, and it is why the next one matters.</p>")

    H.append("<h3>d. Compare against randomly placed episodes</h3>")
    H.append("<p>The strongest control: keep the number of risk-off episodes, "
             "their durations and their weight profiles exactly as they were, but "
             "relocate them at random through the window. 10,000 draws. If the "
             "real timing carried information, it should sit far out in the tail "
             "of that distribution.</p>")
    H.append(table(nul, [
        ("aa_label", "AA", None),
        ("observed_value_add_return", "Observed", lambda v: pct(v, 1, True)),
        ("null_mean_return", "Null mean", lambda v: pct(v, 1, True)),
        ("percentile", "Percentile", lambda v: f"{v*100:.0f}th"),
        ("z_vs_null", "z", lambda v: num(v, 2)),
        ("null_sd_over_observed_sd", "null sd / obs sd", lambda v: num(v, 2)),
        ("mde_return", "MDE", lambda v: pct(v, 0, True)),
        ("episodes", "Episodes", None),
    ]))
    H.append('<div class="callout warn"><p>None of the four is significant. The '
             "best is 0043 at the 84th percentile (z = 1.01), which is ordinary "
             "sampling variation. The minimum detectable effect is around +100% "
             "cumulative value-add: with six or seven episodes, this test could "
             "only have detected an edge roughly twice the size of the largest one "
             "observed. The honest conclusion is not &ldquo;the timing had no "
             "skill&rdquo; but &ldquo;this history cannot distinguish skill from "
             "luck&rdquo;.</p>"
             "<p>Note also that <code>null sd / obs sd</code> is below 1 for every "
             "portfolio, so those percentiles, already unimpressive, are if "
             "anything overstated.</p></div>")

    # ── 5e. Gold timing ───────────────────────────────────────────────────
    H.append(details("How to read null sd, observed sd and MDE", "".join([
        "<p><strong>What the null is.</strong> Someone claims they can pick when "
        "to take holiday to get good weather &mdash; 6 trips, 45 days, great "
        "weather every time. To test it you take <em>those same 6 trips, same "
        "lengths</em> and slide them to random dates, 10,000 times. Same trip "
        "count, same durations, same total days off; only <em>when</em> changes. "
        "That is this test, applied to each book's risk-off episodes.</p>",
        "<p><strong>null sd</strong> is the spread of those 10,000 random "
        "outcomes &mdash; how much your result bounces around with no skill at "
        "all, purely from where the episodes land. 0043's is 0.247 in logs, which "
        "is large: random placement routinely lands between roughly &minus;20% "
        "and +80%. Its observed +59.2% against a null mean of +23.9% is an edge of "
        "+28.4%, and 16 of every 100 random placements still beat it.</p>",
        "<p><strong>observed sd</strong> is how much <em>our own measurement</em> "
        "would swing if history had rolled differently. The total is the sum of 6 "
        "episode contributions, so we resample those 6 with replacement 2,000 "
        "times and take the spread: 0.330. <strong>The ratio matters</strong> "
        "because 0.247/0.330 = 0.749 means the statistic's own wobble is wider "
        "than the whole null distribution &mdash; so &ldquo;84th percentile&rdquo; "
        "is unstable, and a slightly different history could have put the same "
        "strategy at the 40th or the 99th. Below 1, the percentile overstates the "
        "evidence. All four are below 1.</p>",
        "<p><strong>MDE</strong> asks, before looking at any answer: how big would "
        "a real effect have to be for this test to reliably find it? "
        "<code>2.80 &times; null sd</code>, where 2.80 = 1.96 (the 5% bar) + 0.84 "
        "(80% power). For 0043 that is +99.6% cumulative. Its actual edge is "
        "+28.4% &mdash; <strong>one third of the smallest effect the test can "
        "resolve</strong>. So the finding is not &ldquo;no skill&rdquo;; it is "
        "&ldquo;this test could never have answered the question&rdquo;.</p>",
        "<p><strong>Why so underpowered, and what would fix it.</strong> Six "
        "episodes. Noise falls as roughly 1/&radic;n, so resolving the edge each "
        "book actually delivered would need about 75 episodes for 0042 "
        "(<strong>~60 years</strong> at this switching rate), 46 for 0043 "
        "(<strong>~37 years</strong>) and 854 for 0044. That is the binding "
        "constraint on the whole study, and it is why every negative here reads "
        "<em>underpowered, not absent</em> &mdash; and why the mechanism findings "
        "carry more weight than any significance test in this report. Full "
        "derivation in <code>METHODS.md</code>.</p>",
    ])))

    H.append("<h3>e. Was the <em>gold</em> exposure well timed?</h3>")
    H.append("<p>Since gold turned out to be the engine, the sharper question is "
             "not whether equity was well avoided but whether gold was well "
             "caught. Gold is a fixed half of the sleeve, so the only lever is "
             "when the sleeve is held. The statistic is gold's annualised return "
             "over exactly the sessions each portfolio was defensive; the null "
             "relocates the same episodes at random, holding count, durations "
             "and total time in gold fixed so only <em>placement</em> varies.</p>")
    H.append(table(gtime, [
        ("aa", "AA", None),
        ("gold_ann_while_defensive", "Gold p.a. while held", lambda v: pct(v, 1)),
        ("gold_ann_unconditional", "Gold p.a. unconditional", lambda v: pct(v, 1)),
        ("edge_pp", "Edge", lambda v: f"{v:+.1f} pp"),
        ("percentile", "Percentile", lambda v: f"{v*100:.0f}th"),
        ("z_vs_null", "z", lambda v: num(v, 2)),
        ("mde_pp", "MDE", lambda v: f"{v:+.0f} pp"),
    ]))
    H.append('<div class="callout"><p><strong>Do not confuse these numbers with the ones in section 4.</strong> Three quantities in this report sit near 38% and mean different things.</p>'
             '<p><strong>38.60% here</strong> is gold&rsquo;s <em>annualised</em> return over the 534 sessions 0042 was defensive, with <em>no</em> weight scaling &mdash; gold at 100%. <strong>+38.34% in section 4b</strong> is gold&rsquo;s <em>cumulative contribution</em> to the portfolio over those same sessions, already scaled by the one-third-to-one-half the book actually held. <strong>+99.72%</strong>, the &ldquo;Gold alone&rdquo; bar in section 4, is gold&rsquo;s cumulative unscaled return over those sessions. The two 38s are a coincidence.</p>'
             '<p><strong>And 27.90% is the benchmark, not a portfolio number.</strong> It is gold&rsquo;s annualised return over the <em>whole</em> 1,186-session window &mdash; &ldquo;you held gold always and never switched&rdquo;. That is why it is identical for all four books: it does not depend on the portfolio at all. Gold rose 218.4% cumulatively over the window.</p>'
             '<p><strong>One inconsistency, flagged rather than hidden.</strong> Section 4b quotes gold at 27.3% a year and this table at 27.90% &mdash; the same series, annualised two ways. 27.3% is CAGR on calendar time, the convention used everywhere else; 27.90% assumes 252 sessions a year where this window actually holds 247.0. Nothing here turns on it, because the observed rate, the unconditional rate and all 1,200 null draws use the same convention. On calendar annualisation the four edges read +10.43, +11.86, &minus;0.78 and &minus;1.80 pp instead of +10.70, +12.17, &minus;0.79 and &minus;1.84.</p></div>')

    H.append("<p>This is the most favourable evidence in the study, and it splits "
             "the four cleanly. The two portfolios that outperformed held gold "
             "when gold was compounding at 38.6% and 40.1% a year against an "
             "unconditional 27.9% &mdash; an edge of 10.7 and 12.2 points. The "
             "two that underperformed held it at almost exactly average times "
             "(&minus;0.8 and &minus;1.8 points). So the difference between the "
             "winners and the losers is not only how much sleeve they held but "
             "<em>when</em>.</p>")
    H.append('<div class="callout warn"><p>Two things stop this being a finding of '
             "skill. It is not significant &mdash; 84th and 88th percentile, "
             "z of 1.00 and 1.23, against an MDE of about 28 points, so an edge "
             "of 11&ndash;12 points is well inside what random placement "
             "produces. And more fundamentally, <strong>no gold data enters the "
             "rule anywhere</strong>. The signal is a supertrend on equity "
             "indices; gold's weight never varies. Whatever gold timing exists "
             "is a by-product of equity-trend weakness coinciding with gold "
             "strength.</p>"
             "<p>That co-movement has a real economic basis, so some persistence "
             "is reasonable to expect. But it is an exposure the strategy "
             "happens to carry, not a capability it exercises &mdash; which "
             "matters, because the two readings imply different things about "
             "whether it repeats, and one of them invites adding a gold signal "
             "that does not currently exist.</p></div>")

    # ── 6. Cross-application grid ──────────────────────────────────────────
    H.append("<h2>6. Signal quality vs parent quality, separated</h2>")
    H.append("<p>Applying each portfolio's realized state series to every parent "
             "separates the two. Rows are the signal; columns are the equity book "
             "it is applied to. The outlined cell on each row is the real pairing. "
             "Because the parent replaces the AA's equity leg here, these numbers "
             "are free of the tracking drift from section 2.</p>")
    rows = cats
    cols = ["0003", "0007", "0010", "0029"]
    gv = [[grid[(grid.signal_from == r) & (grid.parent == c)]["value_add_ann"].iloc[0]
           for c in cols] for r in rows]
    H.append('<div class="card">')
    H.append(heatmap(rows, cols, gv, rowlab="signal from", collab="applied to parent"))
    H.append('<p class="cap">Value-add per year, in percent. Blue is positive.</p>')
    H.append("</div>")
    H.append("<p>Both effects are real and they are separable:</p>")
    H.append("<ul>")
    H.append("<li><strong>Row effect (signal).</strong> The 0042 and 0043 signals "
             "beat the 0044 and 0045 signals on every parent without exception. "
             "0043's signal is the best of the four.</li>")
    H.append("<li><strong>Column effect (parent).</strong> Every signal does best "
             "on 0007 and worst on 0010, mirroring their selection alpha. Even the "
             "best signal adds only 2.7 points a year to 0010.</li>")
    H.append("</ul>")
    H.append("<p>So for the question you raised about 0043: <strong>both</strong> "
             "factors favour it. Its signal is genuinely the strongest of the four, "
             "and its parent is by far the most improvable.</p>")
    H.append('<div class="callout"><p><strong>Which of the two matters more '
             "cannot be answered from this grid.</strong> On the spread of row "
             "and column <em>means</em> the signal effect is 5.90pp and the "
             "parent effect 5.74pp; on the mean within-row and within-column "
             "spread it is 5.90pp and 6.54pp. The two measures disagree about "
             "the ordering and both margins are under a point, so the honest "
             "reading is that the effects are the same size. An earlier version "
             "of this section claimed the parent effect was ~7pp against ~5pp; "
             "that 7 was the single widest row (0043: 10.16 &rarr; 2.50), not an "
             "average, and the claim is withdrawn. Arithmetic in "
             "<code>cross_grid_spreads.csv</code>.</p></div>")

    H.append("<h3>Why the signals differ at all</h3>")
    ag = agree.reset_index().rename(columns={"index": "aa"})
    H.append(table(ag, [("aa", "", None)] + [
        (c, c, lambda v: pct(v, 1)) for c in agree.columns
    ]))
    H.append("<p>The four form two tight clusters. 0042 and 0043 agree on "
             f'{pct(agree.loc["0042","0043"],1)} of sessions; 0044 and 0045 on '
             f'{pct(agree.loc["0044","0045"],1)}. Across the clusters agreement '
             "drops to about 92%. That follows from the market-cap blends: 0003 and "
             "0007 carry 80% and 65% of their risk below the midcap line "
             "(smallcap plus microcap), while 0010 and 0029 sit at 46&ndash;49% "
             "midcap, so their signals fire on different indices at different times. "
             "The whole performance gap between the two clusters rests on that "
             "~8% of sessions where they disagree.</p>")

    # ── 7. The signals themselves ─────────────────────────────────────────
    H.append("<h2>7. What the raw signal files reveal</h2>")
    H.append("<p>The weekly per-index supertrend files carry the signal itself "
             "rather than only its realized consequence, with the trend read off "
             "which band the supertrend sits on: <code>ST == FUB</code> is "
             "defensive, <code>ST == FLB</code> is equity. Across all six index "
             "series, every row matches one band or the other &mdash; no "
             "ambiguous cases &mdash; so the rule is unambiguous.</p>")

    H.append("<h3>The described method is not the method that ran</h3>")
    H.append("<p>Searching every one-, two- and three-index combination and "
             "threshold against the realized states identifies what actually "
             "drove each portfolio:</p>")
    rc = recon.groupby("aa").head(1).reset_index(drop=True)
    H.append(table(rc, [
        ("aa", "AA", None),
        ("combo", "Indices searched", None),
        ("weights", "Fitted weights", None),
        ("threshold", "Threshold", lambda v: num(v, 2)),
        ("agreement", "Agreement", lambda v: pct(v, 1)),
    ]))
    H.append('<div class="callout"><p><strong>0042 and 0043 are driven by the '
             "Smallcap 100 supertrend alone</strong> &mdash; a single index, "
             "matching 99.6% and <strong>100.0%</strong> of 1,185 sessions. Not a "
             "three-index market-cap-weighted blend. That is why those two agree "
             "with each other on 99.6% of sessions and why their signals behave "
             "identically throughout this study.</p>"
             "<p>0044 and 0045 <em>do</em> use two-index blends at a 0.6 "
             "threshold &mdash; 40/60 Smallcap 100 / Midcap 150 and 60/40 "
             "Midcap 100 / Smallcap 100 respectively. So the 60% rule is real, "
             "but only for two of the four, and the index sets are not the "
             "Nifty 100 / Midcap 150 / Smallcap 250 trio described.</p></div>")
    H.append("<p>The search covers all one-, two- and three-index combinations "
             "of seven index signals, Microcap 250 included. Adding microcap does "
             "produce a <em>perfect</em> fit for 0042 &mdash; Nifty 100 0.05 + "
             "Smallcap 100 0.65 + Microcap 250 0.30 at a 0.3 threshold matches "
             "100% of the 1,110 sessions microcap covers, against 99.55% for "
             "Smallcap 100 alone on those same sessions. I am not adopting it. "
             "That fit resolves <strong>five</strong> disagreeing weeks, and the "
             "search evaluates roughly 47,000 candidate rules per portfolio, so a "
             "perfect score on five residuals is what overfitting looks like "
             "rather than evidence of the real rule. The parsimonious reading "
             "stands: 0042 is Smallcap 100 with about five unexplained "
             "weeks.</p>")
    H.append(details("Agreement of every single index signal with every realized state",
                     table(sagree.pivot(index="index", columns="aa", values="agreement")
                           .reset_index(),
                           [("index", "Signal", None)] +
                           [(c, c, lambda v: pct(v, 1)) for c in ORDER])))

    H.append("<h3>The 60% threshold is not a tuning knob</h3>")
    H.append("<p>This is the test that was impossible with the weight files "
             "alone. Sweeping the threshold on each identified blend, holding "
             "everything else fixed:</p>")
    ths = sorted(sweep["threshold"].unique())
    H.append('<div class="card">')
    H.append(lines_chart(
        [float(t) for t in ths],
        {a: [sweep[(sweep.aa == a) & (sweep.threshold == t)]["value_add_ann"].iloc[0]
             for t in ths] for a in cats},
        xlab="Signal threshold for going defensive",
        ylab="Value-add p.a. (clean implementation)",
        fmt=lambda v: pct(v, 0, True), mark_x=0.6, width=800, height=340,
        x_tick_every=2,
    ))
    H.append('<p class="cap">Step functions, because the underlying signals are '
             "binary per index. Levels here are not comparable with the realized "
             "attribution &mdash; this is a clean re-implementation on the parent "
             "with a fixed 50/50 gold-cash sleeve, so it carries no tracking "
             "drift and no bond leg.</p>")
    H.append("</div>")
    H.append("<p><strong>The threshold is not a dial. It is a three-way choice of "
             "logic.</strong> Each index signal is binary, so a two-index blend can "
             "only produce four scores &mdash; and the threshold merely picks which "
             "of three rules you are running:</p>")
    H.append('<div class="tw"><table><thead><tr>'
             "<th>Book</th><th>Possible scores</th>"
             "<th>OR<br>equity if <em>either</em> buys</th>"
             "<th>SINGLE<br>one index decides</th>"
             "<th>AND<br>equity only if <em>both</em> buy</th>"
             "</tr></thead><tbody>"
             "<tr><td>0042</td><td>0, .45, .55, 1</td><td>&minus;0.67%</td>"
             "<td><strong>+7.61%</strong> &larr; actual</td><td>+8.11%</td></tr>"
             "<tr><td>0043</td><td>0, .45, .55, 1</td><td>+1.70%</td>"
             "<td><strong>+10.16%</strong> &larr; actual</td><td>+10.20%</td></tr>"
             "<tr><td>0044</td><td>0, .40, .60, 1</td><td>+0.05%</td>"
             "<td>+0.07%</td><td><strong>+2.52%</strong> &larr; actual</td></tr>"
             "<tr><td>0045</td><td>0, .40, .60, 1</td><td>&minus;2.92%</td>"
             "<td>&minus;0.26%</td><td><strong>+6.99%</strong> &larr; actual</td></tr>"
             "</tbody></table></div>")
    H.append('<div class="callout"><p><strong>AND wins on all four books, without '
             "exception</strong> &mdash; and every threshold from 0.60 to 0.95 gives "
             "the identical answer, because they all mean AND.</p>"
             "<p>So <strong>0044 and 0045 are already at the best point "
             "available</strong>, on a plateau running 0.60 to 0.95. The step at "
             "0.60 is a step <em>up onto</em> that plateau, not a precarious ledge: "
             "the risk was only ever in setting the threshold <em>lower</em>, which "
             "would demote them to SINGLE and cost 2.5 and 7.2 points. An earlier "
             "version of this section called that a &ldquo;cliff edge&rdquo; and a "
             "&ldquo;genuine fragility&rdquo;; that reading was wrong and is "
             "withdrawn.</p>"
             "<p><strong>The two books actually mis-set are 0042 and 0043</strong>, "
             "which sit at SINGLE and give up +0.50 and +0.04 points a year by not "
             "requiring the second index to agree.</p>"
             "<p>This is the same structural finding that section 9 arrives at "
             "independently and recommends as <code>N100 AND SC100</code>. It was "
             "already visible here.</p></div>")
    H.append("<p>One caveat specific to 0042 and 0043: their 0.55/0.45 blend is a "
             "<em>device for the sweep</em>, not a claim about the real rule. At "
             "threshold 0.50 it is mathematically identical to &ldquo;Smallcap 100 "
             "alone&rdquo;, which is what the reconciliation above identified &mdash; "
             "which is why its 0.45&ndash;0.50 values (+7.61%, +10.16%) match the "
             "pure Smallcap 100 cells in the next grid exactly.</p>")

    H.append("<h3>Which index times best?</h3>")
    H.append("<p>Applying each index's supertrend, on its own, to each parent "
             "&mdash; six signals across four equity books, all with the same "
             "sleeve and no tracking drift.</p>")
    srows = ["nifty50", "nifty100", "midcap100", "midcap150",
             "smallcap100", "smallcap250", "microcap250"]
    scols = ["0003", "0007", "0010", "0029"]
    sv = [[sgrid[(sgrid.signal == r) & (sgrid.parent == c)]["value_add_ann"].iloc[0]
           for c in scols] for r in srows]
    H.append('<div class="card">')
    H.append(heatmap([r.replace("smallcap", "SC").replace("midcap", "MC")
                      .replace("nifty", "N") for r in srows],
                     scols, sv, rowlab="signal index", collab="applied to parent",
                     diag_ring=False, width=660))
    H.append('<p class="cap">Value-add per year, in percent. Blue is positive.</p>')
    H.append("</div>")
    H.append("<p>Three things fall out of this:</p>")
    H.append("<ul>")
    H.append("<li><strong>Smallcap trend is the best timing signal</strong> for "
             "three of the four books &mdash; Smallcap 100 adds 7.6, 10.2 and "
             "4.1 points a year on 0003, 0007 and 0029. Smallcap 250 is close "
             "behind and best of all on 0007 at +10.7.</li>")
    H.append("<li><strong>Nifty 50 trend is the worst</strong>, negative on two "
             "of the four books. The large-cap index is too smooth to flag the "
             "risk that a smallcap-heavy portfolio actually carries.</li>")
    H.append("<li><strong>0044 used close to the worst available signal for its "
             "own book.</strong> Its blend leans 60% on Midcap 150, which adds "
             "+0.07 points a year on parent 0010 &mdash; while a plain Nifty 100 "
             "supertrend on that same parent adds <strong>+6.4 points a year and "
             "produces a 28.3% CAGR</strong>, the best cell in the grid. The "
             "signal was not merely mistimed; it was the wrong index.</li>")
    H.append("</ul>")
    H.append(details("Full signal grid, with CAGR and drawdown", table(sgrid, [
        ("signal", "Signal", None), ("parent", "Parent", None),
        ("value_add_ann", "Value-add p.a.", lambda v: pct(v, 2, True)),
        ("value_add_return", "Cumulative", lambda v: pct(v, 1, True)),
        ("cagr", "CAGR", lambda v: pct(v, 1)),
        ("max_drawdown", "Max DD", lambda v: pct(v, 1)),
        ("pct_defensive", "% defensive", lambda v: pct(v, 1)),
    ])))

    # ── 7c. The diagonal, and the dispersion the grid hid ──────────────────
    H.append("<h3>The grid above was missing its diagonal</h3>")
    H.append('<p class="cap">Distinct from item 4 in section 9, which runs the '
             "supertrend on each <em>parent basket&rsquo;s own NAV</em>. This one "
             "runs each <em>market index&rsquo;s</em> published signal on that same "
             "market index.</p>")
    H.append("<p>Every cell above applies an index's signal to a <em>stock "
             "basket</em>, so stock selection is mixed into the answer. The "
             "cleanest reading of signal quality is to apply each index's "
             "supertrend to <strong>the index it is computed on</strong>, which "
             "removes selection entirely. That was not in the original grid; it "
             "is here now, and it changes the picture.</p>")
    ordr = ["nifty50", "nifty100", "midcap100", "midcap150",
            "smallcap100", "smallcap250", "microcap250"]
    oi = own.set_index("index").reindex(ordr).dropna(how="all")
    olab = [i.replace("smallcap", "SC").replace("midcap", "MC").replace("nifty", "N")
            for i in oi.index]
    H.append('<div class="card">')
    H.append(legend([("Index, buy and hold", "s2"), ("With its own signal", "s1")]))
    H.append(grouped_bars(
        olab,
        {"Index": [oi.loc[i, "index_cagr"] for i in oi.index],
         "Overlay": [oi.loc[i, "overlay_cagr"] for i in oi.index]},
        fmt=lambda v: pct(v, 0), ylab="CAGR, 2021-11 to 2026-08",
        height=300, colors=["s2", "s1"], width=700,
    ))
    H.append('<p class="cap">The trend rule <em>loses</em> to buy-and-hold on '
             "both midcap indices. It wins on the large-cap and small/micro ends. "
             "No cell is statistically distinguishable from randomly placed "
             "episodes.</p>")
    H.append("</div>")
    H.append("<ul>")
    H.append("<li><strong>The rule loses money on midcap, on midcap's own "
             "index.</strong> &minus;1.45 points a year on Midcap 100 and "
             "&minus;1.65 on Midcap 150, winning only 34% and 42% of rolling "
             "12-month windows. That matters because Midcap 150 carries 46&ndash;49% "
             "of the 0010 and 0029 blends &mdash; the two books the overlay hurt.</li>")
    H.append("<li><strong>Sharpe rises and drawdown falls for every single "
             "index</strong>, including the two where return falls. Risk "
             "reduction is the rule's consistent effect; return is the "
             "inconsistent part.</li>")
    H.append("<li><strong>Still nothing significant.</strong> Best is Smallcap "
             "100 at the 85th percentile, z = 1.04, against a minimum detectable "
             "effect of +117% cumulative &mdash; the same verdict as section 5d, "
             "now on the cleanest available test bed.</li>")
    H.append("</ul>")
    H.append(details("Own-index test, full statistics", table(own, [
        ("index", "Index", None),
        ("index_cagr", "Index CAGR", lambda v: pct(v, 2)),
        ("overlay_cagr", "Overlay CAGR", lambda v: pct(v, 2)),
        ("value_add_ann", "Value-add p.a.", lambda v: pct(v, 2, True)),
        ("index_sharpe", "Index Sharpe", lambda v: num(v, 2)),
        ("overlay_sharpe", "Overlay Sharpe", lambda v: num(v, 2)),
        ("index_max_dd", "Index max DD", lambda v: pct(v, 1)),
        ("overlay_max_dd", "Overlay max DD", lambda v: pct(v, 1)),
        ("pct_defensive", "% defensive", lambda v: pct(v, 1)),
        ("roll12m_win_rate", "12m win rate", lambda v: pct(v, 1)),
        ("percentile", "Null pctile", lambda v: pct(v, 1)),
        ("z_vs_null", "z", lambda v: num(v, 2)),
        ("mde_return", "MDE", lambda v: pct(v, 0, True)),
    ])))

    H.append("<h3>And the point-to-point numbers hid everything that matters</h3>")
    H.append("<p>A single 4.8-year cumulative value-add cannot tell a rule that "
             "worked steadily from one that worked in a single quarter. Two views "
             "of the same grid make the difference visible.</p>")
    H.append("<p><strong>First: how often did it actually win?</strong> The share "
             "of rolling 12-month windows in which the overlay beat the naked "
             "parent.</p>")
    gd = gdisp
    gv2 = [[gd[(gd.signal == r) & (gd.parent == c)]["roll12m_win_rate"].iloc[0]
            for c in scols] for r in srows]
    H.append('<div class="card">')
    H.append(heatmap([r.replace("smallcap", "SC").replace("midcap", "MC")
                      .replace("nifty", "N") for r in srows],
                     scols, [[v - 0.5 for v in row] for row in gv2],
                     labels=[[f"{v*100:.0f}%" for v in row] for row in gv2],
                     tip="signal {r} on parent {c}, 12m win rate", unit="",
                     rowlab="signal index", collab="applied to parent",
                     diag_ring=False, width=660))
    H.append('<p class="cap">Cells show the raw win rate; colour is the margin '
             "over a coin flip, so blue means the overlay won more than half of "
             "rolling 12-month windows and red means it lost more than half. Only "
             "one of 28 cells exceeds 75%, and the median cell is 47%.</p>")
    H.append("</div>")
    H.append("<p><strong>Second: when did it win?</strong> Value-add by calendar "
             "year for the best signal in the grid, Smallcap 100.</p>")
    yrs_ = sorted(gyear["year"].unique())
    H.append('<div class="card">')
    H.append(legend([(c, f"s{i+1}") for i, c in enumerate(scols)]))
    H.append(grouped_bars(
        [str(y) for y in yrs_],
        {c: [float(gyear[(gyear.signal == "smallcap100") & (gyear.parent == c) &
                         (gyear.year == y)]["value_add"].iloc[0]) for y in yrs_]
         for c in scols},
        fmt=lambda v: pct(v, 0, True), ylab="Value-add vs parent, by year",
        height=310, width=700,
    ))
    H.append('<p class="cap">2021 is two months and 2026 is eight. Essentially '
             "the entire multi-year edge is 2025; in 2024 the same signal lost "
             "6&ndash;13 points on all four books.</p>")
    H.append("</div>")
    H.append('<div class="callout warn"><p><strong>This is the most important '
             "caveat on the two grids above.</strong> They establish "
             "<em>ordering</em> &mdash; smallcap-family signals beat "
             "midcap-family signals, weak parents are more improvable than "
             "strong ones &mdash; and those orderings are stable. They do "
             "<strong>not</strong> establish that any of these rules delivers a "
             "repeatable annual edge. One year carries almost all of it.</p></div>")

    # ── 8. Episodes ────────────────────────────────────────────────────────
    H.append("<h2>8. The episode ledger</h2>")
    H.append("<p>Every risk-off episode, with what the parent did while the "
             "portfolio was out of it. These partition the timing term exactly.</p>")
    H.append(table(ep, [
        ("aa_label", "AA", None), ("episode", "#", None),
        ("start", "From", None), ("end", "To", None),
        ("weeks", "Weeks", lambda v: num(v, 1)),
        ("parent_return", "Parent did", lambda v: pct(v, 1, True)),
        ("sleeve_return", "Sleeve did", lambda v: pct(v, 1, True)),
        ("value_add_return", "Value added", lambda v: pct(v, 1, True)),
    ]))
    H.append(table(eps, [
        ("aa_label", "AA", None), ("episodes", "Episodes", None),
        ("median_weeks", "Median weeks", lambda v: num(v, 1)),
        ("total_value_add_return", "Total value-add", lambda v: pct(v, 1, True)),
        ("hit_rate", "Hit rate", lambda v: pct(v, 0)),
        ("payoff_ratio", "Payoff", lambda v: num(v, 2)),
        ("top1_share_of_total", "Best episode share", lambda v: pct(v, 0)),
        ("breakeven_roundtrip_bps", "Breakeven cost/trip",
         lambda v: f"{v:,.0f} bps"),
    ]))
    H.append('<div class="callout warn"><p>0043 wins on a hit rate of only 67%, '
             "and a single episode &mdash; August 2025 to April 2026, when its "
             "parent fell 10.1% while the sleeve made 27.2% &mdash; accounts for "
             "92% of its entire risk-off value-add. Strip that one window out and "
             "the case largely disappears. 0042 is better spread but still has 61% "
             "in one episode.</p></div>")
    H.append("<p>The breakeven cost column is the only friction figure here, since "
             "the study is otherwise gross. With so few round trips, trading costs "
             "are not what decides these outcomes &mdash; 0042 and 0043 could absorb "
             "several hundred basis points per switch, and no plausible cost saves "
             "0044 or 0045.</p>")

    H.append("<h3>Concentration in time</h3>")
    H.append(table(conc, [
        ("aa_label", "AA", None),
        ("best_quarter", "Best quarter", None),
        ("best_quarter_share_of_total", "Share of total excess", lambda v: pct(v, 0)),
        ("quarters_positive", "Quarters positive", lambda v: pct(v, 0)),
        ("quarters", "Quarters", None),
    ]))
    H.append("<p>Fewer than half of all quarters were positive for three of the "
             "four. The excess is not a steady drip; it arrives in a couple of "
             "windows.</p>")

    yp = yr.copy()
    yp["aa_label"] = yp["aa_label"].astype(str).str.zfill(4)
    years = sorted(yp["year"].unique())
    H.append('<div class="card">')
    H.append(legend([(a, s) for a, s in zip(cats, SERIES)]))
    H.append(grouped_bars(
        [str(y) for y in years],
        {a: [yp[(yp.aa_label == a) & (yp.year == y)]["excess"].iloc[0] for y in years]
         for a in cats},
        fmt=lambda v: pct(v, 0, True), ylab="Excess over parent, by year",
        width=820, height=320,
    ))
    H.append('<p class="cap">2025 carries nearly all of it &mdash; the year gold '
             "re-rated. 2024 was negative for all four.</p>")
    H.append("</div>")

    # ── 8b. Classification ────────────────────────────────────────────────
    H.append("<h2>8b. How holdings get assigned to a market-cap bucket</h2>")
    H.append("<p>Every market-cap figure in this report comes from the returns "
             "regression in section 3, not from classifying stocks. That choice "
             "has to be defended, because a biased assignment would propagate "
             "into which index signal each book is judged to need.</p>")

    H.append("<h4>The regression was mis-specified, and it was unstable</h4>")
    H.append("<p>Two problems, both since corrected:</p>")
    H.append("<ul>")
    H.append("<li><strong>Microcap was missing.</strong> The original fit offered "
             "only Nifty 100, Midcap 150 and Smallcap 250. The parents hold "
             "10&ndash;34% microcap by holdings count, so that exposure was "
             "forced onto the nearest available factor. Parent 0003 reads 93% "
             "smallcap on three factors and <strong>58% microcap</strong> on "
             "four. Because Microcap 250 also compounded fastest of the four "
             "(+21.2% a year), omitting it understated every benchmark and so "
             "overstated selection alpha by 2&ndash;5 points a year.</li>")
    H.append("<li><strong>It is sensitive to the index series used.</strong> The "
             "same three-factor specification gives 0003 a 93% smallcap loading "
             "on the spliced series and 73% on the desk's own OHLCV workbook. "
             "With R&sup2; of 0.71&ndash;0.76 and highly collinear factors, the "
             "split between adjacent buckets is weakly identified. Everything now "
             "uses one source.</li>")
    H.append("</ul>")
    H.append(details("Three-factor against four-factor, per parent", table(regspec, [
        ("parent", "Parent", None), ("spec", "Specification", None),
        ("nifty100", "N100", lambda v: pct(v, 0)),
        ("midcap150", "MC150", lambda v: pct(v, 0)),
        ("smallcap250", "SC250", lambda v: pct(v, 0)),
        ("microcap250", "Micro250", lambda v: pct(v, 0)),
        ("r_squared", "R&sup2;", lambda v: num(v, 3)),
        ("top_factor", "Largest", None),
    ])))

    H.append("<h4>Why not classify the holdings directly</h4>")
    H.append("<p>The obvious alternative is to bucket each holding using the "
             "exchange's own index membership. Two findings decide against it "
             "here, and the first was the live worry.</p>")
    H.append("<p><strong>Monthly snapshots would not mis-tag stocks ahead of "
             "reconstitution.</strong> NSE reconstitutes its broad-market indices "
             "semi-annually, so a table refreshed monthly could in principle tag "
             "a stock into the Nifty 100 months before the index itself admits "
             "it. Testing month-over-month turnover settles it: Nifty 100 and "
             "Midcap 150 show <strong>zero</strong> churn across all five "
             "snapshots, and the smaller indices move by one or two names, which "
             "is the signature of ad-hoc changes such as delistings and mergers. "
             "A monthly re-ranking would shuffle dozens of names at the rank-250, "
             "500 and 750 boundaries every month. So the table holds real "
             "membership sampled monthly, and snapping to reconstitution dates "
             "would only add lag around legitimate mid-period changes.</p>")
    H.append(table(churn, [
        ("index_name", "Index", None), ("snapshot", "Snapshot", None),
        ("n", "Members", None),
        ("added", "Added", lambda v: "&mdash;" if not np.isfinite(v) else f"{int(v)}"),
        ("removed", "Removed", lambda v: "&mdash;" if not np.isfinite(v) else f"{int(v)}"),
    ]))
    H.append('<div class="callout warn"><p><strong>The disqualifying problem is '
             "coverage.</strong> The constituents table holds five snapshots, all "
             "between 2026-04-09 and 2026-08-01. There is no membership history "
             "for 2021&ndash;2025 at all, so a point-in-time classification of "
             "this study window is impossible from it. Any bucket applied to 2022 "
             "necessarily uses 2026 membership.</p>"
             "<p>That mis-tags every stock that changed bucket in between, and "
             "systematically: names that grew get recorded as larger than they "
             "were. It shows up directly in the unmapped share, which falls from "
             "36% of 0007's 2021 holdings to 5% of its 2026 holdings &mdash; "
             "older positions have simply dropped out of the indices by 2026 and "
             "cannot be classified at all. Worth noting that "
             "<code>cap_classifier_v2.py</code> queries "
             "<code>MAX(snapshot_date)</code>, so production cap distributions "
             "carry exactly this bias over a four-month reference history.</p></div>")
    H.append(details("Holdings bucketed by the 2026 snapshot, by year "
                     "(illustrative only &mdash; not point-in-time)",
                     table(hold, [
                         ("parent", "Parent", None),
                         ("period", "Period", None),
                         ("holdings", "Holdings", None),
                         ("unmapped_share", "Unmapped", lambda v: pct(v, 1)),
                         ("Large Cap", "Large", lambda v: pct(v, 0)),
                         ("Mid Cap", "Mid", lambda v: pct(v, 0)),
                         ("Small Cap", "Small", lambda v: pct(v, 0)),
                         ("Micro Cap", "Micro", lambda v: pct(v, 0)),
                     ])))

    H.append("<h4>Does the bias change any conclusion?</h4>")
    H.append("<p>Only one, and it strengthens it. The &ldquo;signal off the "
             "book's largest bucket&rdquo; policy from section 9 can be built on "
             "any of the three bases. All three land far below what is already "
             "running:</p>")
    hwb = hwbasis.pivot(index="basis", columns="parent", values="value_add_ann")
    hwb["mean"] = hwb.mean(axis=1)
    hwb = hwb.reset_index()
    H.append(table(hwb, [("basis", "Basis for &ldquo;largest bucket&rdquo;", None)] +
                   [(c, c, lambda v: pct(v, 2, True)) for c in
                    ["0003", "0007", "0010", "0029", "mean"]]))
    H.append("<p>Against +6.8% a year for the rule as it runs today and +10.6% for "
             "Nifty 100 AND Smallcap 100, the highest-weight policy delivers "
             "+3.0% to +4.9% depending on how the largest bucket is decided. The "
             "conclusion is therefore robust to the classification question "
             "entirely &mdash; and the recommended rule never uses market-cap "
             "weights in the first place.</p>")

    # ── 9. Gold prediction and improvements ───────────────────────────────
    H.append("<h2>9. Which signal predicts gold &mdash; and what would improve this</h2>")
    H.append("<p>Everything below runs on a replication of the desk's own "
             "supertrend, ported from <code>ST.py</code>: a linearly weighted "
             "ATR over five weekly bars with a multiplier of 2, bands centred "
             "on the bar's mid-range. The multiplier was not assumed &mdash; it "
             "is recovered exactly from the published files as "
             "<code>(BUB &minus; BLB) / (2 &times; EMA_TR)</code> = 2.0000 for "
             "every index. The port reproduces the published signal on "
             "<strong>100% of weeks for six of seven indices</strong> &mdash; "
             "Microcap 250 among them &mdash; and 99.5% for Nifty 100, with the "
             "weighted ATR matching to 4e-16.</p>")

    H.append("<h3>Gold prediction is monotonic in market cap &mdash; and Nifty 500 is not the answer</h3>")
    H.append("<p>Since gold turned out to be the engine, the question becomes "
             "which index's trend best tells you when to hold it. For each "
             "candidate, gold's annualised return over the weeks that signal "
             "says defensive:</p>")
    gp = gpred.copy()
    gp["lab"] = gp["signal"].map(SHORT).fillna(gp["signal"])
    gp = gp.sort_values("edge_pp", ascending=False)
    H.append('<div class="card">')
    H.append(grouped_bars(
        list(gp["lab"]),
        {"Edge over gold's own average": list(gp["edge_pp"] / 100.0)},
        fmt=lambda v: pct(v, 0, True), color_by_sign=True,
        ylab="Gold's excess return p.a. while that signal is defensive",
        width=820, height=300,
    ))
    H.append('<p class="cap">Ordered by edge, which turns out to be ordered by '
             "market cap. N500* is a synthetic Nifty 500, validated against the "
             "published index at 97.5% weekly signal agreement.</p>")
    H.append("</div>")
    H.append(table(gp, [
        ("lab", "Signal", None),
        ("pct_defensive", "% defensive", lambda v: pct(v, 1)),
        ("episodes", "Episodes", None),
        ("gold_ann_while_defensive", "Gold p.a. while held", lambda v: pct(v, 1)),
        ("edge_pp", "Edge", lambda v: f"{v:+.1f} pp"),
        ("percentile", "Percentile", lambda v: f"{v*100:.0f}th"),
        ("z_vs_null", "z", lambda v: num(v, 2)),
        ("mde_pp", "MDE", lambda v: f"{v:+.0f} pp"),
    ]))
    H.append("<p>The ordering is perfectly monotonic in market cap: Microcap 250 "
             "at +22.6 points, Smallcap 250 at +20.9, Smallcap 100 at +12.2, the "
             "midcaps at roughly nothing, Nifty 100 at &minus;2.5 and Nifty 50 at "
             "&minus;8.4. The smaller the companies whose trend you follow, the "
             "better it marks gold's good periods. That is a coherent mechanism "
             "rather than a coincidence &mdash; microcap trend is the most "
             "sensitive available read on domestic risk appetite, and gold is "
             "what bids when risk appetite fails.</p>")
    H.append('<div class="callout warn"><p><strong>So no &mdash; Nifty 500 is not '
             "the answer.</strong> The synthetic Nifty 500 lands at &minus;1.2 "
             "points and the 50th percentile: literally no better than placing "
             "the same episodes at random. The reason is structural. Nifty 500 "
             "<em>is</em> Nifty 100 + Midcap 150 + Smallcap 250, but cap-weighted "
             "that is about 76 / 16 / 8, so a broad index's trend is mostly a "
             "large-cap trend &mdash; and it lands, as you would then expect, "
             "right next to Nifty 100 (&minus;2.5). Going broader moves you "
             "toward the useless end of this table, not the useful end. If you "
             "want the gold read, go <em>smaller</em>, or equal-weight.</p></div>")
    H.append('<div class="callout warn"><p>One honest qualification on Microcap '
             "250, the only result in this whole study to clear conventional "
             "significance (98th percentile, z = 2.19): eight signals were "
             "tested and the best one selected, so the effective bar is higher "
             "than 95% &mdash; under a Bonferroni correction for eight tests it "
             "would not clear. Its edge of +22.6 points also sits below the "
             "study's own 28.8-point MDE. Treat it as the strongest lead here, "
             "worth testing out of sample, not as an established effect. Its "
             "history is also the shortest of the eight, starting only "
             "2022-02.</p>"
             "<p>The table above uses the replicated signal. Recomputed on the "
             "desk's own published Microcap 250 file &mdash; against which the "
             "replication matches on 100% of weeks &mdash; the edge is +21.5 "
             "points at the 96.5th percentile, z = 1.95. Same conclusion, and "
             "now just <em>below</em> conventional two-sigma, which only "
             "sharpens the caution.</p></div>")

    H.append("<h3>The four changes worth making</h3>")

    H.append("<h4>1. Require two indices to agree &mdash; and don't pick them by weight</h4>")
    H.append("<p>The natural instinct is to signal off whichever index the book "
             "is most exposed to. Tested against every alternative, that is the "
             "wrong principle. On the corrected four-factor blends the largest "
             "bucket is Microcap 250 for 0003, Smallcap 250 for 0007 and Midcap "
             "150 for both 0010 and 0029 &mdash; so &ldquo;use the highest-weight "
             "index&rdquo; sends the two midcap-tilted books to the single worst "
             "signal in the grid, and it is <em>worse than what is running "
             "today</em>. (An earlier version of this line said all four books "
             "were Smallcap-250-dominated; that was the three-factor fit, before "
             "Microcap 250 was added.)</p>")
    H.append('<div class="callout warn"><p><strong>Correction to the table below.</strong> The highest-weight row was stale: <code>phase10_policy.py</code> picked the largest bucket from three factors while the blend is fitted on four, so 0003 was read as Smallcap 250 at 0.93 &mdash; the pre-correction three-factor weight &mdash; when its actual largest bucket is Microcap 250 at 0.58. Fixed and re-run. The policy now scores <strong>+3.03% a year with a worst book of &minus;2.68%</strong>, against a stale +5.08% and +1.94%. The conclusion is unchanged and strengthened: choosing the signal by the book&rsquo;s own largest exposure is the worst policy tested, and it loses money on one book. Every other row depends only on signals and parents, so none of them was affected.</p></div>')
    pr = prank.copy()
    pr["label"] = pr["policy"].map(polname)
    H.append(table(pr, [
        ("label", "Signal rule", None),
        ("mean_value_add_ann", "Mean value-add p.a.", lambda v: pct(v, 2, True)),
        ("min_value_add_ann", "Worst book", lambda v: pct(v, 2, True)),
        ("books_beating_realized", "Books beating today", lambda v: f"{v} / 4"),
    ]))
    H.append('<div class="callout"><p><strong>Nifty 100 AND Smallcap 100</strong> '
             "&mdash; hold equity only when both a large-cap and a small-cap "
             "index are trending up &mdash; averages +10.6 points a year against "
             "+6.8 for the current setup, and it is the only rule that beats "
             "today's on <strong>all four</strong> books, with a worst case of "
             "+7.2. Signalling off each book's largest market-cap bucket averages "
             "+3.0 to +4.9 depending on how that bucket is decided (section "
             "8b), and beats today on at most one book.</p></div>")
    H.append("<p>Two things make this more than a lucky pairing. Every one of the "
             "top three rules pairs Nifty 100 with a smaller index, and Nifty 100 "
             "on its own is mediocre (+5.0) while Smallcap 100 on its own is "
             "+6.1 &mdash; so the pair beats the sum of its parts. The gain comes "
             "from <em>complementarity across the size spectrum</em>: the "
             "large-cap leg registers broad market breakdown, the small-cap leg "
             "registers risk appetite failing, and demanding both filters out the "
             "false alarms each generates alone.</p>")
    H.append("<p>Note too that <strong>0044 and 0045 were already running AND "
             "rules</strong> without it being described that way &mdash; with "
             "weights 0.4/0.6 and a 0.6 threshold, the score can only be 0, 0.4, "
             "0.6 or 1, and &ldquo;above 0.6&rdquo; happens only when both "
             "indices agree. So the structure was already right; the index "
             "<em>pair</em> was wrong. Swapping Midcap 150 for Nifty 100 takes "
             "0044 from +2.5 to +5.1.</p>")
    H.append(details("Every rule, per book", table(pbook, [
        ("aa", "AA", None), ("parent", "Parent", None),
        ("realized_rule", "Rule as run", None),
        ("realized", "As run", lambda v: pct(v, 2, True)),
        ("policy_highest_weight", "Highest-weight", lambda v: pct(v, 2, True)),
        ("and::nifty100+smallcap100", "N100 AND SC100", lambda v: pct(v, 2, True)),
        ("and::nifty100+smallcap250", "N100 AND SC250", lambda v: pct(v, 2, True)),
        ("single::smallcap100", "Only SC100", lambda v: pct(v, 2, True)),
        ("single::microcap250", "Only Micro250", lambda v: pct(v, 2, True)),
    ])))
    H.append("<h4>Does the recommendation survive a null?</h4>")
    H.append("<p>Every result this report declines to call significant is held to "
             "an episode-relocation null. The policy ranking above originally was "
             "not &mdash; which made the one number the report actually recommends "
             "the only one without a null. Corrected here: same test as section 5d, "
             "2,000 draws, seed 1729.</p>")
    H.append('<div class="tw"><table><thead><tr><th>Policy</th>'
             "<th>Mean value-add p.a.</th><th>Worst book</th>"
             "<th>Mean percentile</th><th>Mean z</th>"
             "<th>Books at 94th+</th></tr></thead><tbody>"
             "<tr><td><strong>N100 AND SC100</strong></td>"
             "<td><strong>+10.63%</strong></td><td><strong>+7.21%</strong></td>"
             "<td><strong>95.3rd</strong></td>"
             "<td><strong>1.67</strong></td><td><strong>4 / 4</strong></td></tr>"
             "<tr><td>N100 AND SC250</td><td>+8.59%</td><td>+5.06%</td>"
             "<td>90.2nd</td><td>1.31</td><td>0 / 4</td></tr>"
             "<tr><td>N100 AND Micro250</td><td>+7.52%</td><td>+4.15%</td>"
             "<td>86.5th</td><td>1.13</td><td>0 / 4</td></tr>"
             "<tr><td>The rule as run, cleanly re-implemented</td><td>+6.82%</td>"
             "<td>+2.52%</td><td>84.7th</td><td>1.04</td><td>0 / 4</td></tr>"
             "<tr><td>SC100 alone</td><td>+6.10%</td><td>+2.50%</td>"
             "<td>82.4th</td><td>0.94</td><td>0 / 4</td></tr>"
             "<tr><td><em>As the books actually traded</em></td><td>+3.77%</td>"
             "<td>&minus;1.34%</td><td>68.2nd</td><td>0.51</td><td>0 / 4</td></tr>"
             "<tr><td>Highest-weight index</td><td>+2.72%</td><td>&minus;2.68%</td>"
             "<td>60.8th</td><td>0.33</td><td>0 / 4</td></tr>"
             "</tbody></table></div>")
    H.append('<p class="cap">Two &ldquo;today&rdquo; rows, because they are '
             "different things. <strong>The rule as run</strong> is the identified "
             "rule re-implemented cleanly on the parent &mdash; no tracking drift, "
             "no half-weights, no missed reconstitutions. <strong>As the books "
             "actually traded</strong> uses the realized weight states from the "
             "weight files. The <strong>3.05-point gap between them is the "
             "execution cost</strong>, and it is larger than the gain from any "
             "single index swap in this table. The highest-weight row reads +2.72% "
             "here against +3.03% in the ranking table above because the two differ "
             "in how missing signal weeks are filled; immaterial to the ordering. "
             "Evidence: <code>policy_null.csv</code>, "
             "<code>policy_null_summary.csv</code>.</p>")
    H.append('<div class="callout"><p><strong>The percentile ordering tracks the '
             "return ordering exactly</strong>, and all four books move together. "
             "Per book, N100 AND SC100 sits at the 94.5th, 95.6th, 96.6th and "
             "94.7th percentile (z 1.60&ndash;1.76), against the realized rule's "
             "78th, 82nd, 60th and 47th. That structure is much harder to produce "
             "by chance than one lucky pick out of fifteen, and it is the "
             "strongest evidence in this study.</p>"
             "<p><strong>Two limits.</strong> The edge of roughly +53% cumulative "
             "is still only about half the minimum detectable effect (~+105%), so "
             "it does not clear conventional significance on any single book. And "
             "the four books are <em>not</em> four independent confirmations "
             "&mdash; 0042 and 0043 agree on 99.6% of sessions, so this is really "
             "two clusters: two observations at the 95th percentile, not four.</p>"
             "<p>Note also that the winning rule fires <strong>5 episodes rather "
             "than 6</strong> &mdash; the same direction as change 3 below. The gain "
             "comes with <em>less</em> switching, not more.</p></div>")
    H.append('<div class="callout warn"><p>Fifteen rules were tested and the best '
             "reported, so some of that +10.6 is selection. Confirm on parents "
             "outside these four before changing anything.</p></div>")
    H.append("<p>Worth separating from the gold question: <strong>Microcap 250 is "
             "the best gold predictor but the worst standalone equity "
             "signal</strong> (+4.5 average). Value-add is avoided-equity plus "
             "sleeve-earned, and those two objectives want different indices. "
             "Don't read the gold table as a signal recommendation.</p>")

    H.append("<h4>1b. Which index suits which book</h4>")
    srows2 = ["nifty50", "nifty100", "nifty500_synth", "midcap100", "midcap150",
              "smallcap100", "smallcap250", "microcap250"]
    scols2 = ["0003", "0007", "0010", "0029"]
    sv2 = [[sbp[(sbp.signal == r) & (sbp.parent == c)]["value_add_ann"].iloc[0]
            for c in scols2] for r in srows2]
    H.append('<div class="card">')
    H.append(heatmap([SHORT[r] for r in srows2], scols2, sv2,
                     rowlab="signal index", collab="applied to parent",
                     diag_ring=False, width=660))
    H.append('<p class="cap">Value-add per year, in percent, pricing the parent '
             "as the equity leg so no tracking drift is included.</p>")
    H.append("</div>")
    H.append("<p>Every book has a clearly better signal than the one it ran:</p>")
    H.append("<ul>")
    H.append("<li><strong>0010</strong> (0044's parent) &mdash; Nifty 100, "
             "+6.4%/yr, against +0.07 from its Midcap-150-heavy blend. Notably "
             "the one book where a large-cap signal wins, because it is the "
             "least smallcap-tilted of the four.</li>")
    H.append("<li><strong>0007</strong> (0043's parent) &mdash; Smallcap 250, "
             "+10.7%/yr, slightly ahead of the Smallcap 100 it actually used.</li>")
    H.append("<li><strong>0029</strong> (0045's parent) &mdash; Smallcap 100, "
             "+4.1%/yr, against &minus;1.7 for a Nifty 500 signal and &minus;5.8 "
             "for Nifty 50.</li>")
    H.append("</ul>")

    H.append("<h4>2. Put gold information into the sleeve &mdash; there is none today</h4>")
    H.append("<p>Gold is a fixed half of the sleeve and the rule never looks at "
             "it. Deciding gold-versus-cash inside the sleeve with a supertrend "
             "on gold itself, holding the equity decision fixed at each book's "
             "best signal:</p>")
    sr_order = ["fixed 50/50", "gold when gold trends, else cash", "all gold"]
    H.append('<div class="card">')
    H.append(legend([(a, s) for a, s in zip(cats, SERIES)]))
    H.append(grouped_bars(
        ["fixed 50/50", "gold on its own trend", "all gold"],
        {a: [stv[(stv.aa == a) & (stv.sleeve_rule == r)]["value_add_ann"].iloc[0]
             for r in sr_order] for a in cats},
        fmt=lambda v: pct(v, 0, True), ylab="Value-add p.a.", width=800, height=300,
    ))
    H.append("</div>")
    H.append("<p>Adding a gold trend filter beats the fixed 50/50 on three of the "
             "four books (0042: +10.5 vs +7.6; 0043: +15.2 vs +10.7; 0045: +7.0 "
             "vs +4.1). That is the concrete form of &ldquo;make the gold call "
             "deliberate rather than incidental&rdquo;.</p>")
    H.append('<div class="callout warn"><p><strong>But it makes drawdown worse on '
             "all four books, which the return figures alone hide.</strong></p>"
             '<div class="tw"><table><thead><tr><th>Book</th>'
             "<th>Value-add, fixed &rarr; gold-trend</th>"
             "<th>Max drawdown, fixed &rarr; gold-trend</th></tr></thead><tbody>"
             "<tr><td>0042</td><td>+7.61% &rarr; +10.52%</td>"
             "<td>&minus;17.81% &rarr; <strong>&minus;21.55%</strong></td></tr>"
             "<tr><td>0043</td><td>+10.67% &rarr; +15.20%</td>"
             "<td>&minus;22.65% &rarr; <strong>&minus;22.97%</strong></td></tr>"
             "<tr><td>0044</td><td>+6.40% &rarr; +5.82%</td>"
             "<td>&minus;13.21% &rarr; <strong>&minus;20.56%</strong></td></tr>"
             "<tr><td>0045</td><td>+4.14% &rarr; +6.96%</td>"
             "<td>&minus;17.61% &rarr; <strong>&minus;21.95%</strong></td></tr>"
             "</tbody></table></div>"
             "<p>The reason is in the data: <code>pct_gold_when_defensive</code> "
             "runs 0.65&ndash;0.77, so this &ldquo;filter&rdquo; is mostly "
             "all-gold. Section 10's first conclusion is that risk reduction is "
             "the overlay's one <em>proven</em> property, so this change trades "
             "the demonstrated benefit for an unproven return gain. Worth testing; "
             "not worth adopting on these numbers alone.</p></div>")
    H.append('<div class="callout warn"><p>Plain <strong>all-gold</strong> beats '
             "both, on every book. Resist reading that as a recommendation: this "
             "window contains one uninterrupted gold bull market, so "
             "&ldquo;always hold more gold&rdquo; is guaranteed to win in-sample "
             "and tells you nothing about the next regime. The gold-trend filter "
             "is the version that could in principle protect you when gold turns; "
             "the all-gold column is the in-sample ceiling, not a plan.</p></div>")

    H.append("<h4>3. Fewer, higher-conviction switches &mdash; not a faster filter</h4>")
    H.append("<p>The lag diagnostic in section 5 suggested the signal fires late, "
             "which invites speeding it up. Sweeping the multiplier and lookback "
             "on the Smallcap 100 signal says the opposite:</p>")
    pv = psw.pivot_table(index=["days", "mul"], columns="aa", values="value_add_ann")
    sw = psw.groupby(["days", "mul"])["switches"].first()
    pv = (pv * 100).round(2)
    pv["switches"] = sw
    pvr = pv.reset_index()
    H.append(table(pvr[pvr["days"] == 5], [
        ("mul", "Multiplier", lambda v: num(v, 1)),
        ("switches", "Switches", None),
    ] + [(c, c, lambda v: f"{v:+.2f}%") for c in cats]))
    H.append("<p>At a multiplier of 1.0 the filter makes 28 switches and adds "
             "+5.0/+7.8/+1.2/+0.8. At 2.5 it makes 9 and adds "
             "+9.2/+12.7/+4.5/+5.9 &mdash; better on every book. Sensitivity "
             "buys whipsaws, not earlier exits. The realized multiplier of 2 sits "
             "just below the better setting, and this holds across every lookback "
             "tested.</p>")
    H.append(details("Full multiplier and lookback sweep", table(pvr, [
        ("days", "Bars", None), ("mul", "Multiplier", lambda v: num(v, 1)),
        ("switches", "Switches", None),
    ] + [(c, c, lambda v: f"{v:+.2f}%") for c in cats])))
    H.append("<p>The reconciliation of the two findings is that the lag test "
             "shifted the <em>whole</em> realized state series earlier, which "
             "uses information that did not exist at the time. Made "
             "implementable, the gain comes from cutting false exits rather than "
             "from reacting sooner.</p>")

    H.append("<h4>4. Signal off the parent's own NAV where drawdown is the goal</h4>")
    H.append(table(onav, [
        ("aa", "AA", None), ("parent", "Parent", None),
        ("value_add_ann", "Value-add p.a.", lambda v: pct(v, 2, True)),
        ("cagr", "CAGR", lambda v: pct(v, 1)),
        ("max_drawdown", "Max DD", lambda v: pct(v, 1)),
        ("pct_defensive", "% defensive", lambda v: pct(v, 1)),
    ]))
    H.append("<p>Running the same supertrend on each parent's own index rather "
             "than a market index adds less return than the best market signal. "
             "On drawdown it helps <strong>two of the four books, not all "
             "four</strong> &mdash; an earlier version of this paragraph cited "
             "only the two that improved:</p>")
    H.append('<div class="tw"><table><thead><tr><th>Book</th>'
             "<th>Realized max DD</th><th>Own-NAV signal</th><th></th>"
             "</tr></thead><tbody>"
             "<tr><td>0042</td><td>&minus;20.05%</td><td>&minus;20.59%</td>"
             "<td>worse</td></tr>"
             "<tr><td>0043</td><td>&minus;23.46%</td>"
             "<td><strong>&minus;15.22%</strong></td><td>better</td></tr>"
             "<tr><td>0044</td><td>&minus;18.85%</td>"
             "<td><strong>&minus;14.67%</strong></td><td>better</td></tr>"
             "<tr><td>0045</td><td>&minus;19.64%</td>"
             "<td><strong>&minus;23.97%</strong></td><td>worse</td></tr>"
             "</tbody></table></div>")
    H.append("<p>So this is a per-book option worth checking, not a general "
             "property. It is a real improvement for 0043 and 0044 &mdash; 0044 "
             "reaches a 22.5% CAGR at &minus;14.7% drawdown &mdash; and a mild "
             "deterioration for the other two.</p>")

    # ── 10. Verdict ────────────────────────────────────────────────────────
    H.append("<h2>10. What this says about the strategy</h2>")
    H.append("<p>Pulling the evidence together:</p>")
    H.append("<ol>")
    H.append("<li><strong>The overlay is a risk reducer, and a good one.</strong> "
             "Every AA version cut its parent's drawdown (0042: &minus;20.1% vs "
             "&minus;31.9%) and every one has down-capture well below up-capture. "
             "That is a real, repeatable structural property, independent of any "
             "timing skill.</li>")
    H.append("<li><strong>The return gain came from the asset, not the timing.</strong> "
             "Gold supplied 84% of the sleeve's contribution and compounded at "
             "27.3% a year. Replace gold with cash and every positive result "
             "collapses.</li>")
    H.append("<li><strong>The signal fires late.</strong> Consistently, across all "
             "four portfolios, five weeks of earlier action would have been worth "
             "far more. In three of four the parent actually rose during the "
             "avoided windows.</li>")
    H.append("<li><strong>Timing skill is unproven, not disproven.</strong> Against "
             "a random-placement null, none of the four clears the noise. Six to "
             "nine episodes is too few &mdash; the MDE is about +100%.</li>")
    H.append("<li><strong>The overlay is only worth adding to a weak equity "
             "book.</strong> The relationship between parent selection alpha and "
             "overlay value is nearly perfectly inverse. On 0010 and 0029, whose "
             "stock selection adds 2.4&ndash;3.0 points a year, the overlay is a "
             "tax.</li>")
    H.append("<li><strong>There is an operational cost nobody was accounting "
             "for.</strong> The AA books intermittently missed their parents' "
             "quarterly reconstitutions &mdash; 0044 ran 40% of its book wrong "
             "for ten weeks from September 2022 &mdash; costing it 3.0 points a "
             "year. Nothing to do with the signal, and the cheapest item here to "
             "fix.</li>")
    H.append("<li><strong>The best available change is structural, not a "
             "reweighting.</strong> Holding equity only when Nifty 100 <em>and</em> "
             "Smallcap 100 are both trending averages +10.6 points a year against "
             "+6.8 today, and beats the current rule on all four books. Choosing "
             "the signal by the book's own largest exposure &mdash; the intuitive "
             "policy &mdash; averages +3.0 to +4.9 and is worse than today on every "
             "basis tested.</li>")
    H.append("<li><strong>Gold's timing is the best evidence available, and it "
             "still is not skill.</strong> 0042 and 0043 held gold while it "
             "compounded 11&ndash;12 points a year above its own average; 0044 "
             "and 0045 held it at average times. But the effect sits at the 84th "
             "and 87th percentile of a random-placement null, and no gold input "
             "exists in the rule at all.</li>")
    H.append("<li><strong>Two of the four ran a different rule than documented, "
             "and one of them sits on a cliff.</strong> 0042 and 0043 are pure "
             "Smallcap 100 supertrend, not a market-cap-weighted blend. 0044 and "
             "0045 do use blends at 60%, but their entire counterfactual benefit "
             "appears in the single step at 0.60 and vanishes at 0.55.</li>")
    H.append("<li><strong>0044's signal was the wrong index, not just late.</strong> "
             "A plain Nifty 100 supertrend on its parent would have added 6.4 "
             "points a year against the +0.07 its Midcap-150-heavy blend "
             "delivered.</li>")
    H.append("<li><strong>Gold prediction runs monotonically down the size "
             "curve.</strong> Microcap 250 trend marks gold's good periods by "
             "+22.6 points a year, Smallcap 250 by +20.9, Nifty 50 by "
             "&minus;8.4. A broad cap-weighted index &mdash; Nifty 500 included "
             "&mdash; is mostly a large-cap index and lands at zero.</li>")
    H.append("<li><strong>The filter should be less twitchy, not faster.</strong> "
             "Raising the multiplier from 2 to 2.5 cuts switches from 12 to 9 and "
             "improves every book; dropping it to 1 triples the switching and "
             "destroys the edge.</li>")
    H.append("</ol>")

    H.append('<div class="callout"><p><strong>On 0043 specifically.</strong> It '
             "looks like the best overlay because it is the best overlay &mdash; its "
             "signal beats the other three on every parent. But its headline "
             "return is the lowest of the four, its edge over its parent exists "
             "mainly because that parent gave up 6.7 points a year to its own "
             "market-cap blend, and 92% of its risk-off gain came from one "
             "eight-month window in which gold rallied. The right reading is that "
             "0043 rescued a poor stock-selection engine, not that it found a "
             "better way to time the market.</p></div>")

    # ── 9. Method & caveats ────────────────────────────────────────────────
    H.append("<hr>")
    H.append("<h2>Method, and what would change these conclusions</h2>")
    H.append('<p class="fine">The allocation state comes from the realized '
             "rebalance files, keyed on <code>availableDate</code> so nothing is "
             "used before it was live; <code>skipped=true</code> reviews are "
             "observations of unchanged holdings, not gaps. The defensive sleeve is "
             "reconstructed from actual per-instrument weights, which changed from "
             "gold/cash/bonds at a third each (to Apr-2023) to gold/cash at 50/50 "
             "(from Oct-2024).</p>")
    H.append('<p class="fine"><strong>Reconstruction check, restated precisely.</strong> '
             "On fully-defensive sessions the AA <em>is</em> the sleeve, so its "
             "published NAV is external ground truth. Excluding the three sessions "
             "either side of any state change, the reconstruction tracks it to "
             "<strong>&minus;0.52% to &minus;1.03% a year</strong>. Including those "
             "switch-adjacent sessions the gap is <strong>+1.30% to +4.82% a "
             "year</strong>, and essentially all of it sits in two days &mdash; "
             "2022-02-14 and 2025-01-13, the first sessions of episodes 2 and 5, "
             "where the book transacts at fill prices while this study marks at the "
             "close. That is an execution effect, not a reconstruction error, but "
             "an earlier version of this paragraph quoted only the interior figure "
             "without saying which sessions it covered.</p>")
    H.append('<p class="fine"><strong>One known understatement in the section 4 '
             "sleeve column.</strong> <code>build_panel.py:sleeve_return</code> "
             "prices every defensive instrument from raw closes, and LIQUIDBEES "
             "holds a constant NAV of 999.99 because it distributes its yield "
             "&mdash; so a third of the early sleeve's weight is credited 0%. "
             "Using the adjusted total-return series instead would raise the "
             "section 4 sleeve figures by <strong>+1.43 to +1.57 percentage "
             "points</strong> cumulative. The direction is conservative for this "
             "report's conclusion, and gold's 84% share is unaffected because "
             "<code>sleeve_leg_split</code> uses the total-return series. Measured "
             "by <code>validate_section4.py</code> &rarr; "
             "<code>validate_section4.csv</code>.</p>")
    H.append('<p class="fine">Counterfactual arms substitute the parent for the '
             "AA's equity leg, so they measure timing alone. They use a fixed "
             "50/50 Gold BeES / cash sleeve spanning the whole window. Cash is "
             "the <em>adjusted</em> LIQUIDBEES series (1000 &rarr; 2389 over "
             "2007&ndash;2026, +4.99% a year across this window, following a "
             "realistic rate path from 2.4% in 2021 to 5.9% in 2024): the raw "
             "price history returns exactly 0.00% because the fund holds a "
             "constant NAV and distributes its yield, so using it would credit "
             "the cash leg with nothing.</p>")
    H.append('<p class="fine">Signals come from the weekly per-index '
             "<code>W_allRebal.xlsx</code> files, read as "
             "<code>ST == FUB &rarr; defensive</code> / "
             "<code>ST == FLB &rarr; equity</code>, applied from the session "
             "after their date. Specifications were identified by searching all "
             "one-, two- and three-index combinations and thresholds against the "
             "realized states, reaching 99.6&ndash;100% agreement.</p>")
    H.append("<h3 class=\"fine\">Limitations</h3>")
    H.append('<ul class="fine">')
    H.append("<li><strong>The threshold sweep is a clean re-implementation</strong>, "
             "not the realized strategy: it prices the parent rather than the AA's "
             "equity leg and uses a fixed gold-cash sleeve, so its levels are "
             "internally comparable across thresholds but not against the "
             "attribution in section 2.</li>")
    H.append("<li><strong>Nifty 500 is synthetic, but validated.</strong> It is "
             "a 76 / 16 / 8 cap-weighted blend of Nifty 100, Midcap 150 and "
             "Smallcap 250 &mdash; exactly its constituents by rank &mdash; "
             "because the published series in the price database ends "
             "2025-09-15. Checked against the real index over their 1,643 "
             "overlapping sessions it tracks at 0.9998 daily return correlation "
             "and 0.39% annualised tracking error, and its weekly supertrend "
             "agrees with the real one on <strong>97.5%</strong> of weeks. Sound "
             "for this purpose.</li>")
    H.append("<li><strong>Market-cap buckets are estimated from returns, not "
             "holdings</strong> &mdash; unavoidably, since index membership "
             "history does not exist before 2026-04. See section 8b for the bias "
             "this carries and why no conclusion here rests on it.</li>")
    H.append("<li><strong>Microcap 250's history starts 2022-01</strong>, the "
             "shortest of the eight signals, and it is the selected best of "
             "eight tests. Its significance does not survive a multiple-testing "
             "correction.</li>")
    H.append("<li><strong>Identified specs are fits, not documentation.</strong> "
             "At 99.6% agreement roughly five sessions in 1,185 still disagree, "
             "and several weight combinations tie on the same score, so the "
             "index <em>sets</em> are established more firmly than the exact "
             "weights.</li>")
    H.append("<li><strong>Small sample.</strong> Six to nine episodes over 4.8 "
             "years. Every episode-level number carries that.</li>")
    H.append("<li><strong>One gold regime.</strong> The window contains a single, "
             "exceptional gold bull market. The conclusion that gold drove the "
             "result is well evidenced; any expectation that it repeats is not.</li>")
    H.append("<li><strong>Gross of costs and taxes</strong>, per scope; breakeven "
             "cost per round trip is given instead.</li>")
    H.append("<li>0042's weight history ends 2026-06-11 while its index runs to "
             "2026-08-21; the last 48 sessions hold its final known state.</li>")
    H.append("<li>Market-cap index levels are spliced at 2025-09-15 from a second "
             "source, chained on returns; the overlap disagreement is under 0.23%. "
             "This affects only the implied-blend fit, not the attribution.</li>")
    H.append("<li>Implied blends have R&sup2; of 0.71&ndash;0.77, so selection "
             "alpha carries residual factor exposure the three indices do not span.</li>")
    H.append("</ul>")
    H.append('<p class="fine">Reproduce with <code>build_panel.py</code> &rarr; '
             "<code>attribute.py</code> &rarr; <code>robustness.py</code> &rarr; "
             "<code>regime.py</code> &rarr; <code>report.py</code>. Evidence CSVs "
             f"and <code>audit.json</code> are in <code>AA/analysis/evidence/{run}/</code>. "
             "Metrics reuse <code>etf_selector.metrics</code>; Sharpe is "
             "CAGR/volatility with a zero risk-free rate throughout.</p>")

    H.append("</div>")
    return "\n".join(H)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="main")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    html = build(a.run)
    out = Path(a.out) if a.out else (EVIDENCE_DIR / a.run / "report.html")
    out.write_text(html, encoding="utf-8")
    print(f"wrote {out}  ({len(html):,} bytes)")


if __name__ == "__main__":
    main()
