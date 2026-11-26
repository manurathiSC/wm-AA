"""T16 results page: reads ONLY the evidence (evidence/<run>/{w1,w2}) through analyse.py's Win class and writes evidence/report.html (AGENT.md R10).

    python tests/T16/report.py [--run headline] [--evidence DIR] [--out DIR] [--books SCMO_0003]

No number on the page is typed: every number is an element  <span class="v" data-k="KEY" data-v="RAW" data-t="UNIT" data-d="DECIMALS">TEXT</span>  whose KEY names where in the evidence it comes
from, so that check_page.py (which shares no code with this file or analyse.py) can recompute RAW from the raw evidence files and check that TEXT is RAW formatted to DECIMALS.
Strings (verdicts, outcome-map wording, regimes, signs, dates) are  <span class="s" data-k="KEY" data-s="STRING">  checked the same way. The growth charts embed the arrays that draw them
(lines-data, rel-data) and read the hover from those arrays. The key grammar is listed at the top of check_page.py.

T16 has no null, no draws, no percentiles and no p-values (Manu's waiver, 2026-11-26): the page describes what each holding earned over the seen weeks and counts, per pre-registered comparison
C1-C6 (T16.md 2.3), the books in which the stated difference has the stated sign. Per AGENT.md R10 item 1 the first table on the page is the rules-and-runs table in words, and no rule id or run
label appears before it. Forked in layout from tests/T15/report.py (CSS, svg_lines, the hover script, the tables).
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
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import analyse as A  # noqa: E402

E = html.escape
PRIMARY = A.PRIMARY
RULES, BASES, INDICES, COMPS = A.RULES, A.BASES, A.INDICES, A.COMPS
LINES = ["stock", "gold", "cash"] + list(INDICES)
LINE_LAB = {"stock": "parent's stocks", "gold": "GOLDBEES", "cash": "cash (LBES)", "Nifty100": "Nifty 100", "MC100": "Midcap 100", "SC100": "Smallcap 100"}
CURVE_KINDS = ["hold_parent"] + RULES
COL = {"hold_parent": "#8a8f98", "50-orig": "#8fb1ea", "50-half": "#2a6fdb", "50-liq": "#17a2b8", "50-idx": "#6d28d9", "50-all": "#0f9d58",
       "80-orig": "#f0c27a", "80-half": "#c9811a", "80-liq": "#8fa31e", "80-idx": "#b02a2a", "80-all": "#e8590c"}
LAB = {k: k for k in CURVE_KINDS}
LAB["hold_parent"] = "Hold the parent"
DASH = {"50-orig": "4 3", "80-orig": "4 3"}
THICK = {"50-all": 3.0, "80-all": 3.0, "hold_parent": 1.4}
REL_PAIRS = [("50-all", "50-liq"), ("50-all", "50-orig"), ("50-all", "50-idx"), ("80-all", "80-liq"), ("80-all", "80-orig"), ("80-all", "80-idx")]
REL_COL = "#d6336c"
REG_NAMES = ("IN", "OUT-BUY", "OUT-SELL")
KS_LABELS = [("k0", "k = 0"), ("k1", "k = 1"), ("k2", "k = 2"), ("kge1", "k >= 1"), ("all", "all OUT-SELL weeks")]
VAR_TXT = {"headline": "headline", "r2_liq": "R2 (LIQUIDCASE cash leg)", "r3": "R3 (own window)", "r5_drag": "R5 (index leg minus 0.5 pp a year)"}


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


def Sx(key: str, s: str) -> str:
    return f'<span class="s" data-k="{E(key)}" data-s="{E(str(s))}">{E(str(s))}</span>'


def DT(w: str, book: str, window: str, a: str, z: str) -> str:
    """the window of a number or chart: first and last date, checked against the evidence."""
    return f'<span class="dt" data-dates="{w}|{book}|{window}">{a} → {z}</span>'


def fref(*ids) -> str:
    return " ".join(f'<a class="fref" href="#f-{i}">formula: {i}</a>' for i in ids)


def card(title: str, body: str, w: str, book: str, window: str, dates: tuple[str, str], fids=(), cls="") -> str:
    return (f'<section class="card needs-dates {cls}" data-formulas="{",".join(fids)}"><h3>{title} <span class="mini">{DT(w, book, window, *dates)}</span></h3>{body}'
            f'<p class="mini">{fref(*fids)}</p></section>')


def tbl(headers, rows, cls="", tid=""):
    th = "".join(f"<th>{h}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    idattr = f' id="{tid}"' if tid else ""
    return f'<div class="tw"><table class="{cls}"{idattr}><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table></div>'


def bkn(b):
    return b[-4:]


def okc(ok: bool, inner: str) -> str:
    return f'<span class="{"pos" if ok else "neg"}">{inner}</span>'


# ── evidence access (through analyse.Win, plus the few files it does not load) ─
def dbook(W, b, win="full") -> pd.DataFrame:
    d = W.dec if win == "full" else W.dec3
    return d[d["book"] == b].sort_values("j").reset_index(drop=True)


def dates_of(W, b, window="full") -> tuple[str, str]:
    if window == "full":
        a, z, _ = W.dates(b)
        return str(a), str(z)
    return W.r3_dates[b]


def load_r3_dates(W) -> dict:
    rn = pd.read_csv(W.dir / "robust_nav.csv", usecols=["book", "variant", "run", "date"])
    rn = rn[(rn["variant"] == "r3") & (rn["run"] == "50-all")]
    W.r3_cal = {b: [str(x) for x in g["date"]] for b, g in rn.groupby("book")}
    return {b: (str(g["date"].min()), str(g["date"].max())) for b, g in rn.groupby("book")}


def spells_of(reg: np.ndarray):
    out, j = [], 0
    while j < len(reg):
        if reg[j] == "OUT-SELL":
            k = j
            while k + 1 < len(reg) and reg[k + 1] == "OUT-SELL":
                k += 1
            out.append((j, k))
            j = k + 1
        else:
            j += 1
    return out


def state_arrays(W, b, win="full"):
    """for every session of the book's calendar: the regime, B and k of the decision whose target is held then (T0's target until the first later decision is traded)."""
    d = dbook(W, b, win)
    if win == "full":
        n = W.nav[(W.nav["book"] == b) & (W.nav["run"] == "50-all") & (W.nav["cost_bps"] == PRIMARY)]
        dates = [str(x.date()) for x in n["date"]]
    else:
        dates = W.r3_cal[b]
    tds = d["trade_date"].astype(str).to_numpy()
    jj, td = [], []
    for j in range(1, len(d)):
        if tds[j] not in ("nan", "None", ""):
            jj.append(j)
            td.append(tds[j])
    td = np.array(td)
    jj = np.array(jj)
    pos = np.searchsorted(td, np.array(dates), side="right")
    jsel = np.where(pos > 0, jj[np.maximum(pos - 1, 0)], 0)
    return dates, d, jsel


def rcount(W, b: str, win: str, field: str) -> float:
    d = dbook(W, b, win)
    reg, k, B = d["regime"].to_numpy(), d["k"].to_numpy().astype(int), d["B"].astype(str).to_numpy()
    sp = spells_of(reg)
    if field == "decisions":
        return len(d)
    if field.startswith("weeks_"):
        return int((reg == field[6:]).sum())
    if field in ("k0", "k1", "k2"):
        return int(((reg == "OUT-SELL") & (k == int(field[1]))).sum())
    if field == "index_weeks":
        return int(((reg == "OUT-SELL") & (k > 0)).sum())
    if field == "out_sell_spells":
        return len(sp)
    if field == "index_spells":
        return sum(1 for a, z in sp if (k[a:z + 1] > 0).any())
    if field == "B_changes":
        return sum(1 for j in range(1, len(d)) if reg[j] == "OUT-SELL" and reg[j - 1] == "OUT-SELL" and B[j] != B[j - 1])
    if field == "max_spell_index_weeks":
        return max((int((k[a:z + 1] > 0).sum()) for a, z in sp), default=0)
    if field.startswith("spellidx"):
        a, z = sp[int(field[8:]) - 1]
        return int((k[a:z + 1] > 0).sum())
    if field.startswith("spellk0_"):
        a, z = sp[int(field[8:]) - 1]
        return int((k[a:z + 1] == 0).sum())
    if field == "sessions":
        return len(state_arrays(W, b, win)[0])
    if field.startswith("sess_"):
        dates, d2, jsel = state_arrays(W, b, win)
        r2, k2 = d2["regime"].to_numpy()[jsel], d2["k"].to_numpy().astype(int)[jsel]
        nm = field[5:]
        if nm in ("k0", "k1", "k2"):
            return int(((r2 == "OUT-SELL") & (k2 == int(nm[1]))).sum())
        return int((r2 == nm).sum())
    raise KeyError(field)


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


def sampled(n: int):
    idx = np.arange(0, n, 5)
    if idx[-1] != n - 1:
        idx = np.append(idx, n - 1)
    return idx


def state_text(reg: str, B: str, k: int) -> str:
    return reg if reg != "OUT-SELL" else f"OUT-SELL, B = {B} (k = {k})"


def svg_lines(series: dict, dates, key: str, title: str, st_reg, st_k, st_B, w=760, h=300):
    """series: {kind: NAV array}; every 5th session plus the last; log scale; hover read from lines-data[key]; OUT-SELL stretches shaded (grey = k = 0: -all holds the three indices, -idx only cash;
    amber = k >= 1: -idx holds an index too); six hidden overlays (-all / -liq, -all / -orig and -all / -idx on each base, selected from the page's menu) on their own right-hand linear axis."""
    idx = sampled(len(dates))
    allv = np.concatenate([v[idx] for v in series.values()])
    ymin, ymax = math.log(allv.min() * 0.97), math.log(allv.max() * 1.03)
    L, R, T, B = 44, 46, 8, 24
    n = len(idx)
    x = lambda i: L + (w - L - R) * i / (n - 1)
    y = lambda v: T + (h - T - B) * (1 - (math.log(v) - ymin) / (ymax - ymin))
    dx = (w - L - R) / (n - 1)
    bot = h - B
    out = [f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="{E(title)}" class="chart lc" data-book="{E(key)}">']
    j = 0
    while j < n:
        if st_reg[j] == "OUT-SELL":
            cls = "bs1" if st_k[j] > 0 else "bs0"
            e = j
            while e + 1 < n and st_reg[e + 1] == "OUT-SELL" and ("bs1" if st_k[e + 1] > 0 else "bs0") == cls:
                e += 1
            x0, x1 = max(L, x(j) - dx / 2), min(w - R, x(e) + dx / 2)
            out.append(f'<rect x="{x0:.1f}" y="{T}" width="{x1 - x0:.1f}" height="{bot - T}" class="{cls}"/>')
            j = e + 1
        else:
            j += 1
    for t in (0.5, 1, 2, 4, 8, 16, 32, 64):
        if allv.min() * 0.97 <= t <= allv.max() * 1.03:
            out.append(f'<line x1="{L}" x2="{w - R}" y1="{y(t):.1f}" y2="{y(t):.1f}" class="grid"/><text x="{L - 4}" y="{y(t) + 3:.1f}" text-anchor="end" class="ax">{t:g}×</text>')
    years = sorted({pd.Timestamp(d).year for d in dates})
    for yr in years[::2]:
        i = int(np.argmax([pd.Timestamp(d).year == yr for d in dates]))
        jx = int(np.argmin(np.abs(idx - i)))
        out.append(f'<text x="{x(jx):.1f}" y="{h - 6}" text-anchor="middle" class="ax">{yr}</text>')
    for k, v in series.items():
        pts = " ".join(f"{x(j_):.1f},{y(v[i]):.1f}" for j_, i in enumerate(idx))
        dash = f' stroke-dasharray="{DASH[k]}"' if k in DASH else ""
        out.append(f'<polyline points="{pts}" fill="none" stroke="{COL[k]}" stroke-width="{THICK.get(k, 1.6)}"{dash} stroke-linejoin="round"/>')
    pairs = []
    for pi, (num, den) in enumerate(REL_PAIRS):
        r = series[num] / series[den]
        rv = r[idx]
        rlo, rhi = min(float(rv.min()), 1.0), max(float(rv.max()), 1.0)
        pad = 0.06 * (rhi - rlo) if rhi > rlo else 0.01
        rlo, rhi = rlo - pad, rhi + pad
        y2 = lambda t, rlo=rlo, rhi=rhi: T + (h - T - B) * (1 - (t - rlo) / (rhi - rlo))
        step = nice_ticks(rhi - rlo, 5)[1]
        g = [f'<g class="rl" data-pair="{pi}" style="display:none" pointer-events="none"><text x="{w - R + 4}" y="{T + 4}" class="ax" style="fill:{REL_COL}">ratio</text>']
        t = math.ceil(rlo / step) * step
        while t <= rhi:
            g.append(f'<text x="{w - R + 4}" y="{y2(t) + 3:.1f}" class="ax" style="fill:{REL_COL}">{t:.3g}×</text>')
            t += step
        g.append(f'<line x1="{L}" x2="{w - R}" y1="{y2(1.0):.1f}" y2="{y2(1.0):.1f}" stroke="{REL_COL}" stroke-width="1" stroke-dasharray="2 4"/>')
        g.append('<polyline points="' + " ".join(f"{x(j_):.1f},{y2(rv[j_]):.1f}" for j_ in range(n)) + f'" fill="none" stroke="{REL_COL}" stroke-width="2.2" stroke-linejoin="round"/>')
        g.append(f'<text x="{w - R - 4}" y="{y2(rv[-1]) - 6:.1f}" text-anchor="end" class="ax" style="fill:{REL_COL}">end {float(r[-1]):.3f}×</text></g>')
        out.append("".join(g))
        pairs.append({"num": num, "den": den, "lo": rlo, "hi": rhi, "v": [round(float(r[i]), 5) for i in idx], "end": round(float(r[-1]), 5)})
    out.append('<g class="lc-hv" style="display:none" pointer-events="none">'
               f'<line class="lc-v" y1="{T}" y2="{bot}" stroke="var(--muted)" stroke-width="1"/>'
               f'<circle class="lc-rc" r="3.2" fill="{REL_COL}" stroke="var(--card)" stroke-width="1.5" style="display:none"/>'
               f'<line class="lc-h" x1="{L}" x2="{w - R}" stroke="var(--muted)" stroke-width="1" stroke-dasharray="3 3"/>'
               + "".join(f'<circle class="lc-c" r="3.2" fill="{COL[k]}" stroke="var(--card)" stroke-width="1.5"/>' for k in series)
               + f'<g class="lc-yc"><rect x="0" y="-8" width="{L - 3}" height="16" rx="3" fill="var(--fg)"/><text x="{L - 7}" y="3.5" text-anchor="end" font-size="10" fill="var(--bg)" class="lc-yt"></text></g>'
               f'<g class="lc-xc"><rect y="{h - 19}" width="92" height="16" rx="3" fill="var(--fg)" class="lc-xr"/><text y="{h - 7.5}" text-anchor="middle" font-size="10" fill="var(--bg)" class="lc-xt"></text></g></g>')
    out.append(f'<rect class="lc-ov" x="{L}" y="{T}" width="{w - L - R}" height="{bot - T}" fill="transparent" style="cursor:crosshair;touch-action:none"/></svg>')
    dstr = [pd.Timestamp(dates[i]).strftime("%Y-%m-%d (%a)") for i in idx]
    data = {"w": w, "h": h, "L": L, "R": R, "T": T, "B": B, "lo": ymin, "hi": ymax, "log": True, "n": n, "dates": dstr,
            "state": [state_text(st_reg[j_], st_B[j_], int(st_k[j_])) for j_ in range(n)],
            "series": [{"k": k, "label": LAB[k], "col": COL[k], "v": [round(float(v[i]), 4) for i in idx]} for k, v in series.items()]}
    return "".join(out), data, {"col": REL_COL, "dates": dstr, "pairs": pairs}


LINES_JS = """(function(){
var all=JSON.parse(document.getElementById('lines-data').textContent);
var rels=JSON.parse((document.getElementById('rel-data')||{textContent:'{}'}).textContent);
function fx(v){return v.toFixed(2)+'\\u00d7'}
Array.prototype.forEach.call(document.querySelectorAll('svg.lc'),function(svg){
 var d=all[svg.getAttribute('data-book')],fig=svg.parentNode,tip=fig.querySelector('.tip'),g=svg.querySelector('.lc-hv'),ov=svg.querySelector('.lc-ov'),
 cs=svg.querySelectorAll('.lc-c'),q=function(c){return svg.querySelector(c)};
 var rd=rels[svg.getAttribute('data-book')],rgs=svg.querySelectorAll('.rl'),rc=svg.querySelector('.lc-rc'),sel=fig.querySelector('select.vsel'),on=-1;
 if(sel)sel.addEventListener('change',function(){on=(sel.value==='none')?-1:parseInt(sel.value,10);Array.prototype.forEach.call(rgs,function(r){r.style.display=(parseInt(r.getAttribute('data-pair'),10)===on)?'':'none'})});
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
  var s='<b>'+d.dates[j]+'</b><br>state held: <b>'+d.state[j]+'</b>';
  for(var n=0;n<d.series.length;n++)s+='<br><i style="background:'+d.series[n].col+'"></i>'+d.series[n].label+': <b>'+fx(d.series[n].v[j])+'</b>';
  if(on>=0&&rd){var p=rd.pairs[on],pc=(p.v[j]-1)*100,y2=d.T+(d.h-d.T-d.B)*(1-(p.v[j]-p.lo)/(p.hi-p.lo));rc.style.display='';rc.setAttribute('cx',x);rc.setAttribute('cy',y2);
   s+='<br><i style="background:'+rd.col+'"></i>'+p.num+' \\u00f7 '+p.den+': <b>'+p.v[j].toFixed(3)+'\\u00d7</b> ('+(pc>=0?'ahead ':'behind ')+Math.abs(pc).toFixed(1)+'%)'}
  else if(rc)rc.style.display='none';
  tip.innerHTML=s;tip.hidden=false;
  var fr=fig.getBoundingClientRect(),px=e.clientX-fr.left+14,py=e.clientY-fr.top+14;
  if(px+tip.offsetWidth>fr.width)px=e.clientX-fr.left-tip.offsetWidth-14;
  if(py+tip.offsetHeight>fr.height)py=Math.max(0,e.clientY-fr.top-tip.offsetHeight-14);
  px=Math.max(0,px);tip.style.left=px+'px';tip.style.top=py+'px';
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
main{max-width:1080px;margin:0 auto;padding:24px 16px 64px}h1{font-size:25px;line-height:1.25;margin:.2em 0}h2{margin-top:2.2em;font-size:20px;border-top:1px solid var(--line);padding-top:1em}h3{font-size:16px;margin:0 0 .5em}
.mini,.cap,.ax{color:var(--muted);font-size:12.5px}.tw{overflow-x:auto;margin:.6em 0}table{border-collapse:collapse;font-size:12.5px;min-width:100%}th,td{padding:4px 7px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}th{color:var(--muted);font-weight:500}td:first-child,th:first-child{text-align:left}
table.wrap td,table.wrap th{white-space:normal;text-align:left;vertical-align:top}
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:10px 12px;margin:10px 0}.chart{width:100%;height:auto}.grid{stroke:var(--line)}.ax{fill:var(--muted);font-size:10px}
.pass{color:var(--ok);font-weight:600}.fail{color:var(--bad);font-weight:600}.warn{color:var(--warn)}.pos{color:var(--ok)}.neg{color:var(--bad)}
.bs0{fill:#8a8f98;opacity:.16}.bs1{fill:#e8b45c;opacity:.34}
.formula{background:var(--card);border:1px solid var(--line);border-radius:6px;padding:8px 12px;font:12.5px/1.5 ui-monospace,Consolas,monospace;white-space:pre-wrap;overflow-x:auto;margin:6px 0}
[hidden]{display:none!important}.vsel{font:inherit;font-size:12.5px;margin-left:4px;max-width:100%}.hv{position:relative}.tip{position:absolute;z-index:5;pointer-events:none;background:var(--card);border:1px solid var(--line);border-radius:6px;padding:6px 9px;font-size:12px;line-height:1.5;white-space:nowrap;box-shadow:0 2px 8px rgba(0,0,0,.18);font-variant-numeric:tabular-nums}.tip i{display:inline-block;width:10px;height:3px;margin-right:6px;vertical-align:middle}
.legend{display:flex;flex-wrap:wrap;gap:6px 16px;font-size:12.5px;margin:6px 0}.legend i{display:inline-block;width:14px;height:3px;margin-right:6px;vertical-align:middle}.legend b.sw{display:inline-block;width:14px;height:10px;margin-right:6px;vertical-align:middle}
.answer{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--warn);border-radius:6px;padding:12px 16px}.grid2{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.caveat{border-left:3px solid var(--warn);padding:2px 12px;margin:8px 0;background:var(--card)}
details{margin:.4em 0}summary{cursor:pointer;color:var(--muted)}@media (max-width:700px){.grid2{grid-template-columns:1fr}h1{font-size:21px}}
"""

FORMULAS = {
    "nav": "NAV_t = cash_t + Σ_i units_i × close_i,t over the parent's stocks, GOLDBEES and each of the three indices (Nifty 100, Midcap 100, Smallcap 100: units × the index close; on a calendar session with no index bar the last close is carried);\n"
           "cash = LBES units × LBES level; base 1.0 at the close of the first session; daily marks on the book's sessions; units are constant between trades",
    "cost": "at a trade session (the session after the decision), at its fill prices (stocks OHLC4, GOLDBEES de-spiked OHLC4, cash at its level, each index at its own OHLC4):\n"
            "V = value of every line;  target value of line i = target share_i × V;  traded = Σ over every line (stocks, GOLDBEES, cash, each index) |target value_i − held value_i|;\n"
            "cost = traded × cost_bps ÷ 2 ÷ 10,000  (10.4 bps a side at 20.8 bps; 0 and 50 bps as robustness);  every target is then scaled by (V − cost) ÷ V,  so line i after the trade = target share_i × (V − cost)\n"
            "units_i = value after ÷ fill price_i;  shares after cost = value after ÷ (V − cost)",
    "regime": "at a weekly decision (the last session of each ISO week, and T0): the latest Master row of each index and of MAUc1 dated on or before the decision date;\n"
              "IN = all three index SIGNs BUY;  OUT-BUY = not IN and MAUc1 SIGN BUY;  OUT-SELL = not IN and MAUc1 SIGN SELL.\n"
              "B = the indices (Nifty 100, Midcap 100, Smallcap 100) whose own SIGN is BUY at the decision;  k = |B|  (at most 2 in OUT-SELL, since 3 BUY is IN).  Only the -idx rules read B; the -all rules ignore it",
    "targets": "target shares of the book at a decision (parent / GOLDBEES / cash / each index):\n"
               "all rules, IN: parent 1.   -orig, -liq, -half OUT: T14's (e, gw): parent e, GOLDBEES (1 − e) × gw, cash (1 − e) × (1 − gw);  50-orig OUT-BUY and OUT-SELL: GOLDBEES 0.5, cash 0.5;  80-orig: OUT-BUY GOLDBEES 0.8, cash 0.2, OUT-SELL GOLDBEES 0.2, cash 0.8;\n"
               "-liq OUT-SELL: cash 1;  -half OUT-SELL: parent 0.5, GOLDBEES 0.5;  -liq and -half OUT-BUY as the base sleeve.\n"
               "-idx (50-idx, 80-idx): IN parent 1;  OUT-BUY the base sleeve;  OUT-SELL: cash 1 ÷ (k + 1) and each index in B 1 ÷ (k + 1), no parent, no GOLDBEES.\n"
               "-all (50-all, 80-all): IN parent 1;  OUT-BUY the base sleeve;  OUT-SELL: cash 0.25, Nifty 100 0.25, Midcap 100 0.25, Smallcap 100 0.25 whatever B, no parent, no GOLDBEES.\n"
               "A trade is due on the session after decision j iff the target key differs from decision j − 1's; for -idx the key includes B (a change of B inside OUT-SELL is a trade); for -all the key is the regime alone, so only entries into and exits from OUT-SELL trade and the four lines drift in between",
    "cagr": "CAGR = NAV_end ^ (252 ÷ (sessions − 1)) − 1   (sessions = the book's trading sessions in the window; years = (sessions − 1) ÷ 252; arithmetic, price return, after the stated cost)",
    "maxdd": "max drawdown = min over t of ( NAV_t ÷ max(NAV_s, s ≤ t) − 1 )   (negative; 'shallower or equal' = closer to 0 or equal, by the unrounded value)",
    "calmar": "Calmar = CAGR ÷ |max drawdown|",
    "vol": "volatility = standard deviation (n − 1) of the daily NAV returns × √252",
    "diff": "difference = statistic(A) − statistic(B) on the same book, window, cost and cash leg;  CAGR, max drawdown, volatility and cost paid in pp (a positive max-drawdown difference = shallower);  Calmar as a number;  trades as a count;\n"
            "cost paid = Σ of the costs of the run's trades as a share of the starting NAV 1.0, shown in pp",
    "cmp": "C1: CAGR(b-all) > CAGR(b-orig);  C2: max drawdown(b-all) ≥ max drawdown(b-orig);  C3: CAGR(b-all) > CAGR(b-liq);  C4: CAGR(b-all) > CAGR(b-half);  C5: CAGR(b-all) > CAGR(b-idx);  C6: max drawdown(b-all) ≥ max drawdown(b-idx);\n"
           "by the unrounded statistics, per book, after 20.8 bps over the whole window.  n = the number of books in which the condition holds;  the comparison PASSES iff n ≥ 3 of the books.\n"
           "No null, no draws, no percentile, no p-value: a pass describes seen weeks and is not a claim about chance",
    "ledger": "ledger return of an instrument or rule over a span = value_end ÷ value_start − 1, from the close of the session on which the span's first decision is traded (T0 for decision 0) to the close of the session on which the decision that ends it is traded (or the last session);\n"
              "an OUT-SELL spell = a run of consecutive OUT-SELL decisions; a stretch = a run inside it with the same B (so the same k);  parent = hold the parent (0 bps);  Nifty 100, Midcap 100, Smallcap 100 = the hold-the-index NAV (index close ÷ index close);\n"
              "each rule = its own NAV at 20.8 bps;  GOLDBEES and cash = close ÷ close from the evidence's ledger",
    "ksplit": "-all minus -idx by k: for each B stretch, d_b = ret(b-all) − ret(b-idx) over the stretch's span (b = 50 or 80, the ledger's all_minus_idx_50 / _80);  the figure for k = 0 (or 1, 2) is the plain sum of d_b over the stretches whose B has that k;  k >= 1 = the sum over the k = 1 and k = 2 stretches;\n"
              "weeks = the OUT-SELL weekly decisions in those stretches;  a simple sum of period returns, not a compounded figure, and not a statement of which of the two differences between -all and -idx (holding indices that are on SELL, or the 1/4 weights) causes it",
    "cmix": "constant mix at a rule's own averages: each line's share = the mean over the weekly decisions of the rule's target share (f_parent, f_goldbees, f_cash, f_index), rebalanced at every decision and every basket change;  shows how much of a difference is only a different average exposure.  "
            "eq3_index_basket = one third each of Nifty 100, Midcap 100 and Smallcap 100, rebalanced at every weekly decision, 20.8 bps, nothing else",
    "state": "sessions held in a state = the sessions of the book's calendar whose held target is that regime (and, in OUT-SELL, that k): a decision's target is held from the close of its trade session (the next session after the decision), T0's target from the first session",
    "r4": "R4, leave one spell out: for OUT-SELL spell s, a run in which -all holds 100% cash (as -liq) on spell s's decisions and its own target everywhere else;  C1-C6 recomputed with the run's -all against the headline's comparators (-orig, -liq, -half, -idx);  'flips' = the comparisons whose PASS / FAIL differs from the headline's",
    "r5": "R5: every index OHLC4 and close of session i is multiplied by (1 − 0.005 ÷ 252)^i (i counted in sessions of the window's calendar from T0), a fund-cost drag of 0.5 pp a year on the index leg; dividends (the opposite side) are not run;  R2: LIQUIDCASE as the cash leg (W1 whole window; W2 from 2024-01-24);  R3: W1 from 2015-01-02, W2 live decisions from 2021-11-01, each starting in its own first state",
}
NEED_FORMULAS = list(FORMULAS)


def fbox(i: str) -> str:
    return f'<div class="formula" id="f-{i}">{E(FORMULAS[i])}</div>'


# ── small component helpers ──────────────────────────────────────────────────
def stk(w, b, var, cost, run, field):
    return f"st:{w}|{b}|{var}|{cost}|{run}|{field}"


def stV(W, b, run, field, d=2, var="headline", window="full", cost=PRIMARY, u="pct"):
    return V(stk(W.win, b, var, cost, run, field), W.get(var, window, cost, b, run)[field], u, d)


def dfk(w, b, varA, varB, cost, runA, runB, field):
    return f"df:{w}|{b}|{varA}|{varB}|{cost}|{runA}|{runB}|{field}"


DF_KIND = {"cagr": ("pp", 2), "max_dd": ("pp", 2), "vol": ("pp", 2), "calmar": ("sgn", 3), "trades": ("sgn", 0), "cost_paid": ("pp", 3), "end_nav": ("sgn", 3), "regime_trades": ("sgn", 0), "index_set_trades": ("sgn", 0), "basket_trades": ("sgn", 0)}


def dfV(W, b, runA, runB, field, varA="headline", varB=None, winA="full", winB=None, cost=PRIMARY, d=None):
    varB = varB or varA
    winB = winB or winA
    kind, dd = DF_KIND[field]
    raw = float(W.get(varA, winA, cost, b, runA)[field]) - float(W.get(varB, winB, cost, b, runB)[field])
    return V(dfk(W.win, b, varA, varB, cost, runA, runB, field), raw, kind, dd if d is None else d)


def comparison(W, var_all, var_cmp, win_all, win_cmp, cost, base):
    ig = lambda b, run: W.get(var_all, win_all, cost, b, run)
    cg = lambda b, run: W.get(var_cmp, win_cmp, cost, b, run)
    return A.compare(W, var_all, win_all, cost, base, all_get=ig, comp_get=cg)


def cmp_table(W, var_all, var_cmp, win_all, win_cmp, cost, title, dates, b0, window_key):
    """the C1-C6 rows of one variant: per base and comparison the per-book difference, n of books and PASS / FAIL."""
    w = W.win
    rows = []
    for base in BASES:
        cs = comparison(W, var_all, var_cmp, win_all, win_cmp, cost, base)
        for c in cs:
            kind = c["kind"]
            field = c["stat"]
            cells = [f"{base}-all", c["id"], f"{field.replace('max_dd', 'max drawdown').replace('cagr', 'CAGR')} vs {base}-{kind}"]
            for p in c["per"]:
                cells.append(okc(p["ok"], dfV(W, p["book"], f"{base}-all", f"{base}-{kind}", field, var_all, var_cmp, win_all, win_cmp, cost)))
            cells.append(V(f"nok:{w}|{var_all}|{var_cmp}|{cost}|{base}|{c['id']}", c["n_ok"], "int", 0) + f" of {len(W.books)}")
            cells.append(f'<span class="{"pass" if c["pass"] else "fail"}">' + Sx(f"vd:{w}|{var_all}|{var_cmp}|{cost}|{base}|{c['id']}", "PASS" if c["pass"] else "FAIL") + "</span>")
            rows.append(cells)
    return card(title, tbl(["rule", "#", "difference (pp), all − comparator"] + [bkn(b) for b in W.books] + ["books with the stated sign", "verdict"], rows), w, b0, window_key, dates, ("cmp", "diff", "cagr", "maxdd"))


# ── section 1: the answer ─────────────────────────────────────────────────────
OM_MAIN = {"C1+C3": "C1 and C3 pass: holding the three indices with cash earned more than the original sleeve and more than cash alone on this window; PROVISIONAL (seen, post-hoc, no null)",
           "C3 only": "C3 passes, C1 fails: the indices beat cash but giving up GOLDBEES cost more than they added",
           "no C3, C1 passes": "C3 fails: holding the three indices did not beat cash in the regime on this window (C1 passes)",
           "no C3, C1 fails": "C3 fails: holding the three indices did not beat cash in the regime on this window"}
OM_C5 = {True: "C5 passes: ignoring the index signals in the regime earned more than following them (-idx) on this window; the ledger's k = 0 / k >= 1 split says where",
         False: "C5 fails: ignoring the index signals in the regime did not earn more than following them (-idx) on this window; the ledger's k = 0 / k >= 1 split says where"}
OM_C6 = {True: "C6 passes: ignoring the signals did not deepen the worst fall against -idx", False: "C6 fails: ignoring the signals deepened the worst fall against -idx"}
OM_C4 = {True: "C4 passes: -all did better than T14's half-parent + GOLDBEES", False: "C4 fails: -all did not do better than T14's half-parent + GOLDBEES"}
OM_WIN = {True: "the two windows agree on C1-C6", False: "the two windows DISAGREE on C1-C6: report both, no general statement; the 2019-2026 window is the one the live product traded"}


def om_main(c1, c3):
    return "C1+C3" if (c1 and c3) else "C3 only" if c3 else "no C3, C1 passes" if c1 else "no C3, C1 fails"


def r4_flips(W, base, head):
    out = []
    for s in W.spell_ids():
        cs = comparison(W, f"r4_s{s}", "headline", "full", "full", PRIMARY, base)
        for c, h in zip(cs, head):
            if c["pass"] != h["pass"]:
                out.append((s, c["id"], h["pass"], c["pass"]))
    return out


def rules_runs_table(Ws) -> str:
    """the rules-and-runs table in words (AGENT.md R10 item 1): the first table of the page. One row per rule id, benchmark, window, run and comparison."""
    rows = []

    def row(label, kind, words, role, origin):
        rows.append([f"<code>{E(label)}</code>", kind, words, E(role), E(origin)])
    for r in A.RULES:
        base, i_, ob, os_, role, origin = A.RULE_WORDS[r]
        row(r, f"rule, base {base}", f"IN (the three index SIGNs all BUY): {E(i_)}. OUT-BUY (OUT and MAUc1 BUY): {E(ob)}. <b>OUT-SELL (OUT and MAUc1 SELL): {E(os_)}.</b>", role, origin)
    for lab, words, role in A.COMPARATOR_WORDS:
        row(lab, "benchmark", E(words), role, "T16 (descriptive comparators; nothing is tested against chance)")
    for lab, words, role, origin in A.RUN_WORDS:
        extra = ""
        if lab in ("W1", "W2"):
            W = Ws.get(lab.lower())
            if W is not None:
                b0 = W.books[0]
                a, z = dates_of(W, b0)
                extra = f" {DT(W.win, b0, 'full', a, z)}, " + V(f"rc:{W.win}|{b0}|full|decisions", rcount(W, b0, "full", "decisions"), "int", 0) + " weekly decisions."
        row(lab, "window" if lab in ("W1", "W2", "live") else "run", E(words) + "." + extra, role, origin)
    for cid, desc in A.COMP_WORDS:
        row(cid, "comparison", E(desc) + ". Passes when the stated sign holds in at least 3 of the 4 books, by the unrounded statistics, after 20.8 bps, over the whole window; C2 and C6 are about the worst fall, the others about CAGR.",
            "judged (descriptive)", "T16.md 2.3")
    states = ('<p class="mini">' + E(A.STATE_WORDS) + "</p>")
    return (f'<h3 id="rules-runs-h">The rules and the runs in words (read this first)</h3>{states}'
            + tbl(["id or label", "kind", "what it holds, or what it is, in words", "role", "originating test"], rows, "wrap", "rules-runs"))


def section_answer(Ws, head_by) -> str:
    h = ['<h2 id="answer">1. The answer</h2><div class="answer">']
    h.append("<p><b>Question.</b> In the weeks when the three-index switch (the weekly supertrends of Nifty 100, Midcap 100 and Smallcap 100) is OUT <i>and</i> the weekly MAUc1 gold signal is SELL (the OUT-SELL regime), "
             "does holding the three indices and the liquid ETF, 25% each, whatever the indices' own signals say, change what the switch earns, on both base sleeves (50/50 and 80/20) and on two windows? "
             "The comparisons are descriptive: the new holding against the original sleeve (CAGR and worst fall), against the liquid ETF alone, against half parent + half GOLDBEES and against T15's holding of only the indices that are still BUY "
             "(CAGR and worst fall), six comparisons per window and base, 24 in all (T16.md 2.3). Test T16, descriptive, no null.</p>")
    ntot = sum(c["pass"] for cs in head_by.values() for c in cs)
    nall = sum(len(cs) for cs in head_by.values())
    h.append(f"<p><b>{V('npass:all', ntot, 'int', 0)} of {V('ncomp:all', nall, 'int', 0)}</b> comparisons pass (a pass = the stated sign in at least {A.PASS_BOOKS} of the books), after {PRIMARY} bps, whole window; the verdict per window and base follows the table of rules and runs below.</p>")
    h.append("</div>")
    h.append(rules_runs_table(Ws))
    h.append('<div class="caveat"><p><b>What this page can and cannot say.</b> There is <b>no null, no random draw, no percentile and no p-value</b> in T16 (Manu\'s waiver, 2026-11-26), so <b>no claim about chance or skill</b> is made. '
             "A PASS means only that the stated difference had the stated sign in at least 3 of the 4 books over the seen weeks. <b>The four books are one market seen four times</b>: in OUT-SELL weeks <code>-all</code> holds the same four lines in every book, "
             "so their agreement is close to automatic. Both windows were seen before the variant was proposed (post-hoc), there is no hold-out, and choosing the best of the ten rules from these tables is a selection on seen data. "
             "<b>Findings are PROVISIONAL at most</b> (T16.md 2.2); the verdict wording below is the pre-registered outcome map (T16.md 2.5) applied mechanically.</p></div>")
    for w, W in Ws.items():
        a, z = dates_of(W, W.books[0])
        rows = []
        for (w2, base), cs in head_by.items():
            if w2 != w:
                continue
            for c in cs:
                field = c["stat"]
                cells = [f"{base}-all", f"{c['id']}: {c['desc']}"]
                for p in c["per"]:
                    cells.append(okc(p["ok"], dfV(W, p["book"], f"{base}-all", f"{base}-{c['kind']}", field)))
                cells.append(V(f"nok:{w}|headline|headline|{PRIMARY}|{base}|{c['id']}", c["n_ok"], "int", 0) + f" of {len(W.books)}")
                cells.append(f'<span class="{"pass" if c["pass"] else "fail"}">' + Sx(f"vd:{w}|headline|headline|{PRIMARY}|{base}|{c['id']}", "PASS" if c["pass"] else "FAIL") + "</span>")
                rows.append(cells)
        npw = sum(c["pass"] for (w2, _b), cs in head_by.items() if w2 == w for c in cs)
        h.append(f'<h3>{A.WIN_TXT[w]} <span class="mini">{DT(w, W.books[0], "full", a, z)}</span></h3>')
        nt = sum(1 for base in BASES for kind in ("orig", "idx") for b in W.books if abs(float(W.get("headline", "full", PRIMARY, b, f"{base}-all")["max_dd"]) - float(W.get("headline", "full", PRIMARY, b, f"{base}-{kind}")["max_dd"])) < 1e-12)
        h.append(f"<p>{V(f'npass:{w}', npw, 'int', 0)} of {V(f'ncomp:{w}', 12, 'int', 0)} comparisons pass in this window. {fref('cmp')}</p>"
                 f'<p class="mini">C2 and C6 book-comparisons (2 bases × 2 comparators × {len(W.books)} books) in which the two maximum drawdowns are equal to within 1e-12, i.e. tied to floating-point precision (the pre-registered rule, T16.md 2.3, still decides them by the unrounded values): '
                 f"{V(f'ntie:{w}', nt, 'int', 0)}.</p>")
        h.append(tbl(["rule", "comparison (difference in pp, CAGR; C2 and C6 max drawdown)"] + [bkn(b) for b in W.books] + ["books with the stated sign", "verdict"], rows))
        rows = []
        for base in BASES:
            for kind in ("orig", "liq", "half", "idx"):
                cells = [f"{base}-all − {base}-{kind}"]
                for b in W.books:
                    cells.append(dfV(W, b, f"{base}-all", f"{base}-{kind}", "cagr") + " / " + dfV(W, b, f"{base}-all", f"{base}-{kind}", "max_dd"))
                rows.append(cells)
        h.append(card("Headline differences at 20.8 bps: CAGR pp / max drawdown pp (positive = higher CAGR, shallower fall)", tbl(["difference"] + [bkn(b) for b in W.books], rows), w, W.books[0], "full", (a, z), ("diff", "cagr", "maxdd")))
    h.append("<h3>Outcome map (T16.md 2.5), applied mechanically to the headline, per window and base</h3>")
    h.append('<p class="mini">The wording is the frozen pre-registered map; the code that picks it is recomputed by check_page.py from the evidence. R4 and R3 are in section 6.</p>')
    for w, W in Ws.items():
        a, z = dates_of(W, W.books[0])
        items = []
        for base in BASES:
            cs = {c["id"]: c for c in head_by[(w, base)]}
            ps = {i: cs[i]["pass"] for i in cs}
            li = f"<li><b>{w} {base}-all</b>: " + Sx(f"omt:{w}|{base}|main", OM_MAIN[om_main(ps["C1"], ps["C3"])])
            li += "; " + Sx(f"omt:{w}|{base}|c5", OM_C5[ps["C5"]]) + "; " + Sx(f"omt:{w}|{base}|c6", OM_C6[ps["C6"]]) + "; " + Sx(f"omt:{w}|{base}|c4", OM_C4[ps["C4"]]) + "; " + Sx(f"omt:{w}|{base}|c2", "C2 passes" if ps["C2"] else "C2 fails")
            fl = r4_flips(W, base, head_by[(w, base)])
            li += "; " + Sx(f"omt:{w}|{base}|r4", "R4: no comparison flips when one spell is left out" if not fl else "R4: " + "; ".join(A.r4_flip_text(s, cid, hp, np_) for s, cid, hp, np_ in fl))
            r3 = comparison(W, "r3", "r3", "r3", "r3", PRIMARY, base)
            agree = [c["pass"] for c in r3] == [c["pass"] for c in head_by[(w, base)]]
            li += "; " + Sx(f"omt:{w}|{base}|r3", "R3 (live window) agrees with the whole window" if agree else "R3 (live window) DISAGREES with the whole window")
            items.append(li + "</li>")
        h.append(f'<section class="card needs-dates" data-formulas="cmp"><h3>{A.WIN_TXT[w]} <span class="mini">{DT(w, W.books[0], "full", a, z)}</span></h3><ul>' + "".join(items) + f'</ul><p class="mini">{fref("cmp")}</p></section>')
    ag = []
    for base in BASES:
        pats = [tuple(c["pass"] for c in head_by[(w, base)]) for w in Ws]
        ag.append(f"<li><b>{base}-all</b>: " + Sx(f"omt:{base}|windows", OM_WIN[len(set(pats)) == 1]) + "</li>")
    h.append("<ul>" + "".join(ag) + "</ul>")
    return "".join(h)


# ── section 2: the data and the windows ──────────────────────────────────────
def section_data(Ws, gates) -> str:
    h = ['<h2 id="data">2. The data and the windows</h2><p class="mini">Every file is an APPROVED row of data/APPROVED_DATA.md; the engine opens files only through the approved-data check and records them in inputs.csv '
         '(path, through-date, sha256, approved row, usable-from). Price returns only. W1 parent NAV: ' + E(A.CAPTION_W1) + ".</p>"]
    for w, W in Ws.items():
        rows = []
        for r in pd.read_csv(W.dir / "inputs.csv", dtype=str, keep_default_na=False).to_dict("records"):
            rows.append([E(r["file"]), Sx(f"in:{w}|{r['file']}|through", r["through"]), Sx(f"in:{w}|{r['file']}|approved_row", r["approved_row"]), Sx(f"in:{w}|{r['file']}|sha", r["sha256"][:12]), Sx(f"in:{w}|{r['file']}|usable_from", r["usable_from"])])
        h.append(f"<h3>{A.WIN_TXT[w]}: {len(rows)} input files</h3>" + tbl(["file", "through", "approved row", "sha256 (12)", "usable from"], rows, "wrap"))
    h.append("<h3>Windows, regimes and the index-holding weeks</h3>")
    for w, W in Ws.items():
        b0 = W.books[0]
        a, z = dates_of(W, b0)
        rows = []
        for b in W.books:
            aa, zz = dates_of(W, b)
            rows.append([bkn(b), DT(w, b, "full", aa, zz)] + [V(f"rc:{w}|{b}|full|{f}", rcount(W, b, "full", f), "int", 0) for f in
                         ("sessions", "decisions", "weeks_IN", "weeks_OUT-BUY", "weeks_OUT-SELL", "out_sell_spells", "k0", "k1", "k2", "index_weeks", "index_spells", "B_changes", "max_spell_index_weeks")])
        h.append(card(f"{A.WIN_TXT[w]}: weekly decisions in each regime; in OUT-SELL by k (the number of BUY indices); -idx's index-holding weeks and spells; B changes",
                      tbl(["book", "window", "sessions", "decisions", "IN wk", "OUT-BUY wk", "OUT-SELL wk (= -all index weeks)", "OUT-SELL spells", "k = 0 wk", "k = 1 wk", "k = 2 wk", "-idx index weeks", "-idx index spells", "B changes", "most -idx index weeks in one spell"], rows)
                      + '<p class="mini">weeks = weekly decisions (the first is T0); -all holds the three indices in every OUT-SELL week; -idx holds an index only in the OUT-SELL weeks with k ≥ 1; B change = two consecutive OUT-SELL weeks with different B (each is a trade of -idx, none of -all).</p>', w, b0, "full", (a, z), ("regime",)))
        rows = []
        for b in W.books:
            aa, zz = dates_of(W, b)
            rows.append([bkn(b), DT(w, b, "full", aa, zz)] + [V(f"rc:{w}|{b}|full|{f}", rcount(W, b, "full", f), "int", 0) for f in ("sess_IN", "sess_OUT-BUY", "sess_OUT-SELL", "sess_k0", "sess_k1", "sess_k2")])
        h.append(card(f"{A.WIN_TXT[w]}: sessions held in each state", tbl(["book", "window", "IN", "OUT-BUY", "OUT-SELL", "OUT-SELL, k = 0", "OUT-SELL, k = 1", "OUT-SELL, k = 2"], rows), w, b0, "full", (a, z), ("state",)))
        rows = []
        for b in W.books:
            aa, zz = dates_of(W, b, "r3")
            rows.append([bkn(b), DT(w, b, "r3", aa, zz)] + [V(f"rc:{w}|{b}|r3|{f}", rcount(W, b, "r3", f), "int", 0) for f in ("decisions", "weeks_IN", "weeks_OUT-BUY", "weeks_OUT-SELL", "k0", "k1", "k2", "index_weeks", "index_spells")])
        a3, z3 = dates_of(W, b0, "r3")
        h.append(card(f"{A.WIN_TXT[w]}: the R3 window (own start), same counts", tbl(["book", "window", "decisions", "IN wk", "OUT-BUY wk", "OUT-SELL wk", "k = 0 wk", "k = 1 wk", "k = 2 wk", "-idx index weeks", "-idx index spells"], rows), w, b0, "r3", (a3, z3), ("regime",)))
    cav = ['<div class="caveat"><p><b>The largest caveats</b> (T16.md 3, known contaminants):</p><ul>']
    cav.append("<li><b>The index leg is a price index with no dividends and no fund cost, not a tradable instrument</b>: a real index fund or ETF would differ by roughly the dividend yield minus its costs, and Smallcap 100 / Midcap 100 funds "
               "were thin or absent in 2014-2019. R5 tests the cost side only (0.5 pp a year); the dividend side is not run (no approved dividend series). <code>-all</code> puts 75% of the book in this leg in every OUT-SELL week.</li>")
    items = []
    for w, W in Ws.items():
        b0 = W.books[0]
        items.append(f"{A.WIN_TXT[w]}: " + V(f"rc:{w}|{b0}|full|out_sell_spells", rcount(W, b0, "full", "out_sell_spells"), "int", 0) + " OUT-SELL spells in " + V(f"rc:{w}|{b0}|full|weeks_OUT-SELL", rcount(W, b0, "full", "weeks_OUT-SELL"), "int", 0)
                     + " weeks (-idx holds an index in " + V(f"rc:{w}|{b0}|full|index_spells", rcount(W, b0, "full", "index_spells"), "int", 0) + " of those spells)")
    cav.append("<li><b>The effective sample is the OUT-SELL spells</b> (the independent unit for the change): " + "; ".join(items) + ".</li>")
    cav.append("<li><b>The four books are one market seen four times</b>, with one in-or-out series and one gold series; in OUT-SELL weeks <code>-all</code> holds identical indices and cash in all four, so \"3 of 4\" is a consistency check, not four tests.</li>")
    cav.append(f"<li><b>W1's parent is {E(A.CAPTION_W1)}</b> (no published series exists before 2019-01-02); nine manual Eikon exports for delisted stocks (provenance unrecorded) supply bars in W1; both windows are seen; "
               "the variant, the rule's weights and the MAUc1 signal were chosen after seeing 2014-2026 results; cash is a quarter of <code>-all</code>'s regime holding, and the cash file's source before 2026-08-10 is unrecorded (F-AA-D09).</li>")
    cav.append("<li><b>The extension of W2 to 2026-11-20</b>: the index signals, index prices, MAUc1 and the 2026-11-23 GOLDBEES file were auto-approved on Manu's instruction, not reviewed by him; the eight T15 rules reproduce T15's W2 to 2026-10-30 (gate V4(a)); the last OUT-SELL spell of W2 ends at the window end and its open position is marked at the last close.</li>")
    cav.append("</ul></div>")
    h.append("".join(cav))
    rows = []
    for w, W in Ws.items():
        rows.append([A.WIN_TXT[w], Sx(f"gt:{w}|engine", gates[w]["engine"]), Sx(f"gt:{w}|v5", gates[w]["v5"]), Sx(f"gt:{w}|v4a", gates[w]["v4a"]), Sx(f"gt:{w}|v1", gates[w]["v1"]), ("–" if gates[w]["v1n"] is None else V(f"gt:{w}|v1n", gates[w]["v1n"], "int", 0))])
    h.append("<h3>Validity gates recorded with the evidence</h3>" + tbl(["window", "engine gates incl. V2-V5 (audit.json)", "V5 trade and cost identities", "V4(a) the eight T15 rules reproduce T15", "V1 independent verifier (verify_t16.json)", "V1 comparisons"], rows)
             + '<p class="mini">A gate that failed would stop analyse.py before any result is printed. V1 shows NOT RUN when verify_t16.json is absent (a development run).</p>')
    return "".join(h)


# ── section 3: one backtest end to end ───────────────────────────────────────
def pick_trade(W, b, rule, kind, k=None):
    T = W.trades
    sel = T[(T["book"] == b) & (T["run"] == rule) & (T["cost_bps"] == PRIMARY) & (T["kind"] == kind)].sort_values("idx", kind="stable")
    d = dbook(W, b)
    for r in sel.itertuples():
        if k is None or (not pd.isna(r.dec_j) and int(d["k"].iloc[int(r.dec_j)]) == k):
            return r
    return None


def trade_table(W, w, b, rule, r, title_extra, fp):
    kname = r.kind
    tk = lambda f: f"tr:{w}|{b}|{rule}|{PRIMARY}|{int(r.idx)}|{kname}|{f}"
    lk = lambda ln, f: f"ln:{w}|{b}|{rule}|{PRIMARY}|{int(r.idx)}|{kname}|{ln}|{f}"
    Vv, Va = float(r.V), float(r.V_after)
    rows = []
    for ln in LINES:
        before, after = float(getattr(r, f"{ln}_before")), float(getattr(r, f"{ln}_after"))
        share = after / Va
        target = share * Vv
        row = [LINE_LAB[ln], V(lk(ln, "before"), before, "x", 6), V(lk(ln, "share"), share, "x", 6), V(lk(ln, "target"), target, "x", 6), V(lk(ln, "tradedl"), abs(target - before), "x", 6), V(lk(ln, "after"), after, "x", 6)]
        if fp and ln in INDICES:
            row += [V(f"fp:{w}|{rule}|{int(r.idx)}|{ln}", fp[ln], "x", 2), V(f"un:{w}|{b}|{rule}|{PRIMARY}|{int(r.idx)}|{kname}|{ln}", after / fp[ln], "x", 8)]
        else:
            row += ["", ""]
        rows.append(row)
    t = tbl(["line", "value before (at the fill prices)", "target share = after ÷ (V − cost)", "target value = share × V", "traded = |target − before|", "value after cost", "index fill price (OHLC4)", "units = value after ÷ fill price"], rows)
    d = dbook(W, b)
    j = int(r.dec_j)
    sm = (f"decision j = {V(f'dc:{w}|{b}|full|{j}|j', j, 'int', 0)} on " + Sx(f"ds:{w}|{b}|full|{j}|decision_date", d['decision_date'].iloc[j]) + ": regime " + Sx(f"ds:{w}|{b}|full|{j}|regime", d['regime'].iloc[j])
          + ", B = " + Sx(f"ds:{w}|{b}|full|{j}|B", d['B'].iloc[j]) + ", k = " + V(f"dc:{w}|{b}|full|{j}|k", d['k'].iloc[j], "int", 0) + "; previous week " + Sx(f"ds:{w}|{b}|full|{j - 1}|regime", d['regime'].iloc[j - 1])
          + ", B = " + Sx(f"ds:{w}|{b}|full|{j - 1}|B", d['B'].iloc[j - 1]) + "; traded on " + Sx(tk("date"), str(r.date)) + " (session " + V(tk("idx"), r.idx, "int", 0) + ")")
    sm += ("; V = " + V(tk("V"), Vv, "x", 6) + "; traded = Σ of the lines' traded = " + V(tk("traded"), r.traded, "x", 6) + "; cost = traded × " + f"{PRIMARY} ÷ 2 ÷ 10,000 = " + V(tk("cost"), r.cost, "x", 8)
           + "; V − cost = " + V(f"tr2:{w}|{b}|{rule}|{PRIMARY}|{int(r.idx)}|{kname}|vmc", Vv - float(r.cost), "x", 6) + " = V after " + V(tk("V_after"), Va, "x", 6)
           + "; NAV at that day's close " + V(tk("nav_close_after"), r.nav_close_after, "x", 6))
    if kname == "regime_in":
        sm += "; every line of the new holding (cash and the three indices) takes a quarter of V − cost, whatever B is (the shares column)"
    return f"<p>{title_extra}</p><p>{sm}</p>" + t


def worked(W, w) -> str:
    b = W.books[0]
    a, z = dates_of(W, b)
    d = dbook(W, b)
    pr = "50-all"
    h = [f'<h3>{A.WIN_TXT[w]}: book {b}, rule {pr}, {PRIMARY} bps <span class="mini">{DT(w, b, "full", a, z)}</span></h3>']
    nsess = int(W.get("headline", "full", PRIMARY, b, pr)["sessions"])
    st = []
    st.append(["Inputs", "Parent " + b + " rebuilt from its baskets and D18 prices" + (" (" + E(A.CAPTION_W1) + ")" if w == "w1" else "") + "; the three index SIGN files (D03 Master) and MAUc1 SIGN; GOLDBEES; LBES cash; the three indices' daily OHLC (D25 / D25d); the NSE calendar of the window",
               f"{DT(w, b, 'full', a, z)}; sessions " + V(f"n:sessions|{w}|{b}", nsess, "int", 0) + "; weekly decisions " + V(f"rc:{w}|{b}|full|decisions", rcount(W, b, "full", "decisions"), "int", 0)])
    firsts = []
    for lab, test in (("IN", lambda r: r["regime"] == "IN"), ("OUT-BUY", lambda r: r["regime"] == "OUT-BUY"), ("OUT-SELL k = 0", lambda r: r["regime"] == "OUT-SELL" and r["k"] == 0),
                      ("OUT-SELL k = 1", lambda r: r["regime"] == "OUT-SELL" and r["k"] == 1), ("OUT-SELL k = 2", lambda r: r["regime"] == "OUT-SELL" and r["k"] == 2)):
        jj = next((int(r["j"]) for _, r in d.iterrows() if test(r)), None)
        firsts.append((lab, jj))
    rows = []
    tgt_rules = ("50-all", "50-idx", "80-all")
    for lab, jj in firsts:
        if jj is None:
            rows.append([lab, "no such decision in this window"] + [""] * (6 * len(tgt_rules)))
            continue
        cells = [lab, Sx(f"pick:{w}|{b}|target|{lab}", str(jj)) + " " + Sx(f"ds:{w}|{b}|full|{jj}|decision_date", d["decision_date"].iloc[jj])]
        for rule in tgt_rules:
            cells += [V(f"dc:{w}|{b}|full|{jj}|{c}_{rule}", d[f"{c}_{rule}"].iloc[jj], "x", 4) for c in ("e", "gold", "cash")] + [V(f"dc:{w}|{b}|full|{jj}|w_{i}_{rule}", d[f"w_{i}_{rule}"].iloc[jj], "x", 4) for i in INDICES]
        rows.append(cells)
    tgt = tbl(["state", "first decision j / date"] + [f"{rule} {n}" for rule in tgt_rules for n in ("parent", "GOLDBEES", "cash", "N100", "MC100", "SC100")], rows)
    ent = pick_trade(W, b, pr, "regime_in", 2)
    ent0 = pick_trade(W, b, pr, "regime_in", 0)
    ent1 = pick_trade(W, b, pr, "regime_in", 1)
    ext = pick_trade(W, b, pr, "regime_out")
    if ent is not None:
        j = int(ent.dec_j)
        r = d.iloc[j]
        dk = lambda c: f"ds:{w}|{b}|full|{j}|{c}"
        st.append(["Signal", "label = latest Master row dated on or before the decision date; SIGN of each index and of MAUc1 (BUY / SELL)",
                   f"decision j = {V(f'dc:{w}|{b}|full|{j}|j', j, 'int', 0)} on " + Sx(dk("decision_date"), r["decision_date"]) + ": Nifty 100 " + Sx(dk("sign_Nifty100"), r["sign_Nifty100"]) + " (row " + Sx(dk("label_Nifty100"), r["label_Nifty100"])
                   + "), Midcap 100 " + Sx(dk("sign_MC100"), r["sign_MC100"]) + " (row " + Sx(dk("label_MC100"), r["label_MC100"]) + "), Smallcap 100 " + Sx(dk("sign_SC100"), r["sign_SC100"]) + " (row " + Sx(dk("label_SC100"), r["label_SC100"])
                   + "), MAUc1 " + Sx(dk("sign_MAUc1"), r["sign_MAUc1"]) + " (row " + Sx(dk("label_MAUc1"), r["label_MAUc1"]) + ")"])
        st.append(["Regime, B and k", f"IN iff all three SIGN are BUY; OUT-SELL iff not IN and MAUc1 SELL; B = the indices whose own SIGN is BUY (read by -idx only) {fref('regime')}",
                   "regime " + Sx(dk("regime"), r["regime"]) + " (previous week " + Sx(f"ds:{w}|{b}|full|{j - 1}|regime", d["regime"].iloc[j - 1]) + "); B = " + Sx(dk("B"), r["B"]) + "; k = " + V(f"dc:{w}|{b}|full|{j}|k", r["k"], "int", 0)
                   + ": at least one index is on SELL in every OUT-SELL week, yet the target of 50-all is the same four quarters (next row)"])
    st.append(["Decision: the target of 50-all, 50-idx and 80-all in each state", f"first decision of the window in each state; shares of the book; 50-all holds the same four quarters in k = 0, 1 and 2 weeks, 50-idx holds cash and the BUY indices {fref('targets')}", tgt])
    for pk, lab in ((ent, "Execution: a regime entry (k = 2: one index on SELL)"), (ent1, "Execution: a regime entry with k = 1"), (ent0, "Execution: a regime entry with k = 0 (all three indices on SELL)"), (ext, "Execution: a regime exit")):
        if pk is None:
            continue
        which = {"Execution: a regime entry": "entry_k2", "Execution: a regime entry with k = 1": "entry_k1", "Execution: a regime entry with k = 0": "entry_k0", "Execution: a regime exit": "regime_out"}.get(lab.split(" (")[0], "?")
        fp = None
        try:
            for key, x in W.audit["v5"]["worked_examples"].items():
                if key.startswith(pr + "|") and int(x["idx"]) == int(pk.idx) and abs(float(x["V"]) / float(pk.V) - 1) < 1e-9:
                    fp = x["index_fill_prices"]
        except Exception:  # noqa: BLE001
            fp = None
        body = trade_table(W, w, b, pr, pk, f"{fref('cost')}", fp)
        body = f"<p class=\"mini\">picked: the first such trade of the book, trade session " + Sx(f"pick:{w}|{b}|trade|{which}", f"{int(pk.idx)}") + "</p>" + body
        st.append([lab, "units are the value after cost ÷ the fill price; traded = Σ|target − held| over every line; shares after cost sum to 1", body])
    bn = W.audit["v5"]["worked_examples"].get("50-all|B_change_not_traded")
    if bn:
        st.append(["Not a trade: a change of the BUY set inside OUT-SELL", "-all trades only when the regime key changes; -idx rebalances when B changes (the engine's worked example, recomputed from trades.csv)",
                   "decided " + Sx(f"bn:{w}|decision_date", bn["decision_date"]) + ": B changed from " + Sx(f"bn:{w}|B_before", bn["B_before"]) + " to " + Sx(f"bn:{w}|B_after", bn["B_after"]) + " inside OUT-SELL; on the next session "
                   + Sx(f"bn:{w}|next_session", bn["next_session"]) + ": 50-all trades " + V(f"bn:{w}|all_trades", bn["50-all_trades_on_that_session"], "int", 0) + ", 50-idx trades " + V(f"bn:{w}|idx_trades", bn["50-idx_trades_on_that_session"], "int", 0)])
    dts, nvals = W.curve_for(b, PRIMARY, pr)
    if ent is not None:
        i = int(ent.idx)
        st.append(["Daily value", f"NAV_t = cash_t + Σ units × close_t {fref('nav')}", "; ".join(Sx(f"nvd:{w}|{b}|{PRIMARY}|{pr}|{k}", str(pd.Timestamp(dts[k]).date())) + " " + V(f"nv:{w}|{b}|{PRIMARY}|{pr}|{str(pd.Timestamp(dts[k]).date())}", nvals[k], "x", 6) for k in (i - 1, i, i + 1))
                   + " (the middle date is the trade session of the k = 2 entry above)"])
    s = W.get("headline", "full", PRIMARY, b, pr)
    st.append(["Equity curve", f"growth of 1 invested at the close of {pd.Timestamp(dts[0]).date()} (base 1.000), daily marks",
               "start " + V(f"nv:{w}|{b}|{PRIMARY}|{pr}|{pd.Timestamp(dts[0]).date()}", nvals[0], "x", 3) + " on " + DT(w, b, "full", a, z) + "; end " + V(stk(w, b, "headline", PRIMARY, pr, "end_nav"), s["end_nav"], "x", 4) + " after "
               + V(stk(w, b, "headline", PRIMARY, pr, "sessions"), s["sessions"], "int", 0) + " sessions"])
    st.append(["Statistics", f"{fref('cagr', 'maxdd', 'calmar', 'vol')}",
               "CAGR = " + V(stk(w, b, "headline", PRIMARY, pr, "end_nav"), s["end_nav"], "x", 4) + " ^ (252 ÷ (" + V(stk(w, b, "headline", PRIMARY, pr, "sessions"), s["sessions"], "int", 0) + " − 1)) − 1 = " + stV(W, b, pr, "cagr", 3)
               + "; max drawdown " + stV(W, b, pr, "max_dd", 3) + "; Calmar " + stV(W, b, pr, "calmar", 3, u="x") + "; volatility " + stV(W, b, pr, "vol", 3)])
    cm = W.cmix[(W.cmix["book"] == b) & (W.cmix["rule"] == pr)].iloc[0]
    st.append(["Comparators", f"hold the parent (0 cost rebalanced with the parent), each index alone from T0's close, the equal-weight three-index basket, the constant mix at {pr}'s own average shares {fref('cmix')}",
               "hold the parent CAGR " + stV(W, b, "hold_parent", "cagr", 2) + ", max drawdown " + stV(W, b, "hold_parent", "max_dd", 2) + "; " + "; ".join(f"hold {LINE_LAB[i]} CAGR " + stV(W, b, f"hold_{i}", "cagr", 2) for i in INDICES)
               + "; eq3_index_basket CAGR " + stV(W, b, "eq3_index_basket", "cagr", 2)
               + f"; constant mix cmix_{pr} CAGR " + stV(W, b, f"cmix_{pr}", "cagr", 2) + " with shares parent " + V(f"cm:{w}|{b}|{pr}|f_parent", cm["f_parent"], "x", 4) + ", GOLDBEES " + V(f"cm:{w}|{b}|{pr}|f_goldbees", cm["f_goldbees"], "x", 4)
               + ", cash " + V(f"cm:{w}|{b}|{pr}|f_cash", cm["f_cash"], "x", 4) + ", " + ", ".join(f"{i} " + V(f"cm:{w}|{b}|{pr}|f_{i}", cm[f"f_{i}"], "x", 4) for i in INDICES)])
    h.append(tbl(["Step", "What and formula", f"Real numbers ({b}, {a} → {z})"], st, "wrap"))
    return "".join(h)


def section_example(Ws) -> str:
    h = ['<h2 id="example">3. One backtest, end to end</h2><p>One book (the first), one window at a time, rule <code>50-all</code> at 20.8 bps, from the signals to the statistics, with the formulas and the real numbers from trades.csv: '
         'an entry into OUT-SELL, an exit, a week in which an index is on SELL and the rule holds it anyway, and a change of the BUY set that the rule does not trade. '
         'A reader with a calculator can redo every step. The trade rows are read from the evidence by a fixed rule (the first such trade of the book), and the page says which.</p>']
    for w, W in Ws.items():
        h.append(worked(W, w))
    return "".join(h)


# ── section 4: D-table, ledger, comparators ──────────────────────────────────
def section_dtable(W) -> str:
    w = W.win
    b0 = W.books[0]
    a, z = dates_of(W, b0)
    h = [f"<h3>{A.WIN_TXT[w]}</h3>"]
    h.append(card(f"Weeks and sessions in each regime and in each k (OUT-SELL), per book",
                  tbl(["book", "sessions", "wk IN", "wk OUT-BUY", "wk OUT-SELL", "wk k = 0", "wk k = 1", "wk k = 2", "sess IN", "sess OUT-BUY", "sess OUT-SELL", "sess k = 0", "sess k = 1", "sess k = 2"],
                      [[bkn(b)] + [V(f"rc:{w}|{b}|full|{f}", rcount(W, b, "full", f), "int", 0) for f in ("sessions", "weeks_IN", "weeks_OUT-BUY", "weeks_OUT-SELL", "k0", "k1", "k2", "sess_IN", "sess_OUT-BUY", "sess_OUT-SELL", "sess_k0", "sess_k1", "sess_k2")] for b in W.books]),
                  w, b0, "full", (a, z), ("state", "regime")))
    for b in W.books:
        aa, zz = dates_of(W, b)
        rows = []
        for run in RULES + ["hold_parent"]:
            rows.append([run, stV(W, b, run, "cagr", 2), stV(W, b, run, "max_dd", 2), stV(W, b, run, "calmar", 3, u="x"), stV(W, b, run, "vol", 2), stV(W, b, run, "end_nav", 4, u="x"),
                         stV(W, b, run, "trades", 0, u="int"), V(stk(w, b, "headline", PRIMARY, run, "cost_paid"), W.get("headline", "full", PRIMARY, b, run)["cost_paid"], "ppu", 3),
                         stV(W, b, run, "regime_trades", 0, u="int"), stV(W, b, run, "index_set_trades", 0, u="int"), stV(W, b, run, "basket_trades", 0, u="int")])
        for base in BASES:
            for kind in ("orig", "liq", "half", "idx"):
                ra, rb = f"{base}-all", f"{base}-{kind}"
                rows.append([f"<b>{ra} − {rb}</b>", dfV(W, b, ra, rb, "cagr"), dfV(W, b, ra, rb, "max_dd"), dfV(W, b, ra, rb, "calmar"), dfV(W, b, ra, rb, "vol"), dfV(W, b, ra, rb, "end_nav"),
                             dfV(W, b, ra, rb, "trades"), dfV(W, b, ra, rb, "cost_paid"), dfV(W, b, ra, rb, "regime_trades"), dfV(W, b, ra, rb, "index_set_trades"), dfV(W, b, ra, rb, "basket_trades")])
        h.append(card(f"D-table, book {b}: the ten rules and the parent at {PRIMARY} bps, and the differences all − orig / liq / half / idx (CAGR, max drawdown, vol, cost in pp)",
                      tbl(["rule", "CAGR", "max DD", "Calmar", "vol", "end NAV", "trades", "cost paid (% of start NAV)", "regime trades", "B-change trades", "basket trades"], rows), w, b, "full", (aa, zz), ("cagr", "maxdd", "calmar", "vol", "cost", "diff")))
    return "".join(h)


def ledger_rows(W, b):
    L = W.ledger
    return L[(L["book"] == b) & (L["window"] == "full")].reset_index(drop=True)


def ksplit_rows(W, b):
    """(label, n stretches, weeks, d50, d80) from the ledger's stretch rows."""
    lg = ledger_rows(W, b)
    lg = lg[lg["level"] == "stretch"]
    sels = {"k0": lg[lg["k"] == 0], "k1": lg[lg["k"] == 1], "k2": lg[lg["k"] == 2], "kge1": lg[lg["k"] >= 1], "all": lg}
    return sels


def section_ledger(W) -> str:
    w = W.win
    b0 = W.books[0]
    a, z = dates_of(W, b0)
    h = [f"<h3>{A.WIN_TXT[w]}: regime ledger</h3>"]
    lg = ledger_rows(W, b0)
    rows = []
    for r in lg.to_dict("records"):
        k = f"led:{w}|{b0}|{r['level']}|{int(r['spell_no'])}|{int(r['stretch_no'])}"
        sp = r["level"] == "spell"
        rows.append([("<b>spell</b>" if sp else "stretch"), str(int(r["spell_no"])) + ("" if sp else f".{int(r['stretch_no'])}"),
                     "–" if sp else Sx(f"{k}|B", r["B"]), "–" if sp else V(f"{k}|k", r["k"], "int", 0), Sx(f"{k}|first_decision", r["first_decision"]), Sx(f"{k}|last_decision", r["last_decision"]), V(f"{k}|weeks", r["weeks"], "int", 0),
                     Sx(f"{k}|a_session", r["a_session"]), Sx(f"{k}|b_session", r["b_session"]), Sx(f"{k}|entered_from", r["entered_from"]), Sx(f"{k}|exited_to", r["exited_to"]),
                     V(f"{k}|goldbees_return", r["goldbees_return"], "pct", 2), V(f"{k}|cash_return", r["cash_return"], "pct", 2)] + [V(f"{k}|{i}_return", r[f"{i}_return"], "pct", 2) for i in INDICES])
    h.append(card("Instruments over each OUT-SELL spell and each stretch (identical in every book; span = close of the first fill's session to the close of the ending decision's session)",
                  tbl(["level", "#", "B", "k", "first decision", "last decision", "weeks", "span from close", "span to close", "from", "to", "GOLDBEES", "cash", "Nifty 100", "Midcap 100", "Smallcap 100"], rows), w, b0, "full", (a, z), ("ledger", "regime")))
    for b in W.books:
        aa, zz = dates_of(W, b)
        lgb = ledger_rows(W, b)
        rows = []
        for r in lgb.to_dict("records"):
            k = f"led:{w}|{b}|{r['level']}|{int(r['spell_no'])}|{int(r['stretch_no'])}"
            sp = r["level"] == "spell"
            rows.append([("<b>spell</b>" if sp else "stretch"), str(int(r["spell_no"])) + ("" if sp else f".{int(r['stretch_no'])}"), "–" if sp else Sx(f"{k}|B", r["B"]), "–" if sp else V(f"{k}|k", r["k"], "int", 0),
                         V(f"{k}|weeks", r["weeks"], "int", 0), V(f"{k}|parent_return", r["parent_return"], "pct", 2)]
                        + [V(f"{k}|ret_{ru}", r[f"ret_{ru}"], "pct", 2) for ru in RULES]
                        + [V(f"{k}|all_minus_idx_50", r["all_minus_idx_50"], "pp", 2), V(f"{k}|all_minus_idx_80", r["all_minus_idx_80"], "pp", 2)])
        inner = card(f"{b}: the parent and each rule over each span, {PRIMARY} bps; last two columns = ret(b-all) − ret(b-idx) in pp", tbl(["level", "#", "B", "k", "weeks", "parent"] + RULES + ["50-all − 50-idx", "80-all − 80-idx"], rows), w, b, "full", (aa, zz), ("ledger",))
        h.append(f'<details {"open" if b == b0 else ""}><summary>{b}: the parent and each rule over each span</summary>{inner}</details>')
    # the k split
    rows = []
    for b in W.books:
        sels = ksplit_rows(W, b)
        for key, lab in KS_LABELS:
            sel = sels[key]
            kk = f"ks:{w}|{b}|{key}"
            rows.append([bkn(b), lab, V(f"{kk}|n", len(sel), "int", 0), V(f"{kk}|weeks", sel["weeks"].sum(), "int", 0), V(f"{kk}|d50", sel["all_minus_idx_50"].sum(), "pp", 2), V(f"{kk}|d80", sel["all_minus_idx_80"].sum(), "pp", 2)])
    h.append(card("-all minus -idx, summed separately over the k = 0 weeks and the k ≥ 1 weeks (sum over the B stretches of each k of ret(b-all) − ret(b-idx), pp; weeks = OUT-SELL decisions in those stretches)",
                  tbl(["book", "stretches with", "stretches", "weeks", "50-all − 50-idx (pp, summed)", "80-all − 80-idx (pp, summed)"], rows)
                  + '<p class="mini">k = 0: every index is on SELL, -idx holds only cash and -all holds the three indices (so the figure is what holding SELL indices did, with cash 1 against 1/4); k ≥ 1: -idx holds the BUY indices at 1/(k + 1) and cash, -all holds the three at 1/4 '
                    '(holding the SELL indices and the weight change together). The test cannot separate the two causes. A simple sum of period returns, not compounded.</p>', w, b0, "full", (a, z), ("ksplit", "ledger")))
    rows = []
    for b in W.books:
        for run in ["hold_parent", "hold_Nifty100", "hold_MC100", "hold_SC100", "eq3_index_basket"] + [f"cmix_{r}" for r in RULES]:
            rows.append([bkn(b), run, stV(W, b, run, "cagr", 2), stV(W, b, run, "max_dd", 2), stV(W, b, run, "calmar", 3, u="x"), stV(W, b, run, "vol", 2)])
    h.append(card(f"Comparators (benchmarks, not nulls), {PRIMARY} bps", tbl(["book", "comparator", "CAGR", "max DD", "Calmar", "vol"], rows)
                  + '<p class="mini">hold_&lt;index&gt;: the price index bought at T0\'s close and held, no trades; eq3_index_basket: one third each, rebalanced at every decision; cmix_&lt;rule&gt;: the rule\'s own average shares, rebalanced at every decision (parameters below).</p>', w, b0, "full", (a, z), ("cagr", "maxdd", "calmar", "vol", "cmix")))
    rows = []
    for b in W.books:
        for base in BASES:
            rows.append([bkn(b), f"{base}-all − cmix_{base}-all", dfV(W, b, f"{base}-all", f"cmix_{base}-all", "cagr"), dfV(W, b, f"{base}-all", f"cmix_{base}-all", "max_dd"), dfV(W, b, f"{base}-all", f"cmix_{base}-all", "calmar")])
    h.append(card(f"The rule against the constant mix at its own average shares ({PRIMARY} bps): how much is only a different average exposure", tbl(["book", "difference", "CAGR pp", "max DD pp", "Calmar"], rows), w, b0, "full", (a, z), ("cmix", "diff")))
    rows = []
    for b in W.books:
        for ru in RULES:
            c = W.cmix[(W.cmix["book"] == b) & (W.cmix["rule"] == ru)].iloc[0]
            rows.append([bkn(b), ru] + [V(f"cm:{w}|{b}|{ru}|{f}", c[f], "x", 4) for f in ("f_parent", "f_goldbees", "f_cash", "f_Nifty100", "f_MC100", "f_SC100")])
    h.append(f'<details><summary>Constant-mix parameters (mean of the weekly target shares) per book and rule, {DT(w, b0, "full", a, z)}</summary>' + tbl(["book", "rule", "parent", "GOLDBEES", "cash", "Nifty 100", "Midcap 100", "Smallcap 100"], rows) + f'<p class="mini">{fref("cmix")}</p></details>')
    return "".join(h)


def section_desc(Ws) -> str:
    h = ['<h2 id="desc">4. The D-table, the regime ledger and the comparators</h2><p class="mini">The D-table puts the ten rules and the parent side by side per book, with the differences that the comparisons judge; the ledger shows which spells and B stretches carry them, '
         'and splits -all minus -idx by k. Nothing here is tested against chance.</p>']
    for w, W in Ws.items():
        h.append(section_dtable(W))
        h.append(section_ledger(W))
    return "".join(h)


# ── section 5: curves ────────────────────────────────────────────────────────
def section_curves(Ws, lines_data, rel_data) -> str:
    h = ['<h2 id="curves">5. The curves: the ten rules and the parent, per book</h2><p class="mini">Growth of 1 invested at the close of the first session of the window, log scale, 20.8 bps, daily marks (every 5th session drawn; the hover reads the same arrays). '
         'The two originals are dashed; the two -all rules are thick. Shaded: OUT-SELL stretches held (grey = k = 0, every index on SELL: -all holds the three indices, -idx only cash; amber = k ≥ 1: -idx holds an index too). '
         'The overlay menu draws the growth ratio of an -all rule over its -liq, -orig or -idx rule on a right-hand axis (above the dotted 1.0× line the -all rule is ahead).</p>']
    for w, W in Ws.items():
        a, z = dates_of(W, W.books[0])
        h.append(f'<h3>{A.WIN_TXT[w]}</h3><div class="legend">' + "".join(f'<span><i style="background:{COL[k]}"></i>{E(LAB[k])}</span>' for k in CURVE_KINDS)
                 + '<span><b class="sw" style="background:#8a8f98;opacity:.4"></b>OUT-SELL, k = 0</span><span><b class="sw" style="background:#e8b45c;opacity:.6"></b>OUT-SELL, k ≥ 1</span></div>')
        for b in W.books:
            dts, _ = W.curve_for(b, PRIMARY, "50-all")
            ser = {k: W.curve_for(b, PRIMARY, k)[1] for k in CURVE_KINDS}
            dates_s, dd, jsel = state_arrays(W, b)
            idx = sampled(len(dts))
            st_reg = [dd["regime"].iloc[jsel[i]] for i in idx]
            st_k = [int(dd["k"].iloc[jsel[i]]) for i in idx]
            st_B = [str(dd["B"].iloc[jsel[i]]) for i in idx]
            aa, zz = dates_of(W, b)
            key = f"{w}|{b}"
            svg, data, rdata = svg_lines(ser, dts, key, f"{b} growth of 1", st_reg, st_k, st_B)
            lines_data[key] = data
            rel_data[key] = rdata
            opts = '<option value="none">none</option>' + "".join(f'<option value="{i}">{n} ÷ {d_}: outperformance (right axis)</option>' for i, (n, d_) in enumerate(REL_PAIRS))
            sel = f'<label class="mini">Overlay: <select class="vsel" aria-label="chart overlay for {b}">{opts}</select></label>'
            h.append(f'<figure class="card hv needs-dates" data-formulas="nav" style="margin:10px 0"><figcaption><b>{b}</b>: growth of 1 invested at the close of {aa}, log scale, {PRIMARY} bps '
                     f'<span class="mini">{DT(w, b, "full", aa, zz)}; end values ' + ", ".join(f"{LAB[k]} " + V(stk(w, b, "headline", PRIMARY, k, "end_nav"), W.get("headline", "full", PRIMARY, b, k)["end_nav"], "x", 2) + "×" for k in CURVE_KINDS)
                     + f'</span> {sel}</figcaption>{svg}<div class="tip" hidden></div><p class="mini">{fref("nav")}</p></figure>')
    return "".join(h)


# ── section 6: robustness ────────────────────────────────────────────────────
def section_robust(Ws, head_by) -> str:
    h = ['<h2 id="robust">6. Robustness R1-R5</h2><p class="mini">Each table repeats C1-C6 for one variant: per book the difference in pp, the number of books with the stated sign and PASS (at least 3) or FAIL. '
         'R1: 0 and 50 bps; R2: LIQUIDCASE as the cash leg; R3: the window from 2015-01-02 (W1) or the live decisions from 2021-11-01 (W2); R4: one spell left out; R5: a fund-cost drag of 0.5 pp a year on the index leg. No variant is tested against chance.</p>']
    for w, W in Ws.items():
        b0 = W.books[0]
        a, z = dates_of(W, b0)
        h.append(f"<h3>{A.WIN_TXT[w]}</h3>")
        for cost in (0.0, 50.0):
            h.append(cmp_table(W, "headline", "headline", "full", "full", cost, f"R1 at {cost} bps", (a, z), b0, "full"))
        h.append(cmp_table(W, "r2_liq", "r2_liq", "full", "full", PRIMARY, f"R2 LIQUIDCASE cash leg ({PRIMARY} bps)", (a, z), b0, "full"))
        a3, z3 = dates_of(W, b0, "r3")
        h.append(cmp_table(W, "r3", "r3", "r3", "r3", PRIMARY, f"R3 own window ({PRIMARY} bps)", (a3, z3), b0, "r3"))
        h.append(cmp_table(W, "r5_drag", "r5_drag", "full", "full", PRIMARY, f"R5 index leg minus 0.5 pp a year ({PRIMARY} bps)", (a, z), b0, "full"))
        spells = W.spell_ids()
        lg = W.ledger[(W.ledger["book"] == b0) & (W.ledger["level"] == "spell") & (W.ledger["window"] == "full")].reset_index(drop=True)
        rows = []
        for s in spells:
            sr = lg.iloc[s - 1]
            k = f"led:{w}|{b0}|spell|{s}|0"
            for base in BASES:
                var = f"r4_s{s}"
                cs = comparison(W, var, "headline", "full", "full", PRIMARY, base)
                flips = [c["id"] for c, hc in zip(cs, head_by[(w, base)]) if c["pass"] != hc["pass"]]
                cells = [str(s), Sx(f"{k}|first_decision", sr["first_decision"]), Sx(f"{k}|last_decision", sr["last_decision"]), V(f"{k}|weeks", sr["weeks"], "int", 0), V(f"rc:{w}|{b0}|full|spellk0_{s}", rcount(W, b0, "full", f"spellk0_{s}"), "int", 0),
                         Sx(f"{k}|exited_to", sr["exited_to"]) + " " + Sx(f"r4open:{w}|{s}", "open at the window end" if sr["exited_to"] == "window end" else "closed before the window end"), base]
                for c in cs:
                    cells.append(V(f"nok:{w}|{var}|headline|{PRIMARY}|{base}|{c['id']}", c["n_ok"], "int", 0) + " " + f'<span class="{"pass" if c["pass"] else "fail"}">' + Sx(f"vd:{w}|{var}|headline|{PRIMARY}|{base}|{c['id']}", "PASS" if c["pass"] else "FAIL") + "</span>")
                cells += [V(stk(w, b, var, PRIMARY, f"{base}-all", "cagr"), W.get(var, "full", PRIMARY, b, f"{base}-all")["cagr"], "pct", 2) for b in W.books]
                cells.append(Sx(f"r4f:{w}|{s}|{base}", ",".join(flips) or "-"))
                rows.append(cells)
        h.append(card(f"R4 leave one spell out: {A.WIN_TXT[w]}, {PRIMARY} bps (-all holds cash only on that spell's decisions; the comparators are the headline's); the last spell is the one open at the window end",
                      tbl(["spell", "first decision", "last decision", "weeks", "k = 0 weeks", "ends", "base", "C1", "C2", "C3", "C4", "C5", "C6"] + [f"-all CAGR {bkn(b)}" for b in W.books] + ["flips vs headline"], rows), w, b0, "full", (a, z), ("r4", "cmp", "cagr")))
    return "".join(h)


def section_defs(sha, sha_ok, runname) -> str:
    h = ['<h2 id="defs">7. Definitions, formulas and how to reproduce</h2>']
    h.append("".join(f"<p class='mini'><b>{n}</b></p>{fbox(n)}" for n in NEED_FORMULAS))
    h.append(f'<h3>Reproduce</h3><p>From <code>AA/</code>: <code>bash tests/T16/run.sh</code> regenerates the evidence, the gates, <a href="analysis.log">analysis.log</a>, this page and its check '
             f'(<code>python tests/T16/report.py --run {E(runname)}</code>, then <code>python tests/T16/check_page.py --run {E(runname)}</code>, which re-derives every number and every date on this page from the raw evidence files '
             f'and exits 1 on any failure). No draws are made and no seed is used.</p><p>Pre-registration: sha256 of T16.md §1-§3 <b>{sha[1][:16]}</b> (recomputed from T16.md; match with the header: {sha[0] == sha[1]}); '
             f'the audit.json of each window carries the same hash. <a href="METHODS.md">METHODS.md</a> beside this page.</p>')
    return "".join(h)


def prereg_hash(doc_path: Path):
    import hashlib
    import re
    doc = doc_path.read_text(encoding="utf-8")
    region = doc[doc.index("\n## 1. Idea and references") + 1:doc.index("\n## 4. Results") + 1]
    region = "\n".join(l.rstrip() for l in region.replace("\r\n", "\n").split("\n"))
    m = re.search(r"§1–§3 sha256:\*\* `([^`]*)`", doc)
    return (m.group(1) if m else "?"), hashlib.sha256(region.encode("utf-8")).hexdigest()


def gate_strings(W) -> dict:
    a = W.audit
    r = W.reg
    out = {"engine": "PASS" if a["gates"]["all"] else "FAIL", "v5": "PASS" if a["v5"]["pass"] else "FAIL", "v4a": "PASS" if r["a_nav_regression"]["pass"] else "FAIL"}
    v = W.verify
    out["v1"] = "NOT RUN" if v is None else ("PASS" if (v.get("pass") is True or v.get("exit_ok") is True) else "FAIL")
    out["v1n"] = None if v is None else v.get("gate_compared", v.get("comparisons"))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="headline")
    ap.add_argument("--evidence", default=None)
    ap.add_argument("--out", default=None, help="directory for report.html (default tests/T16/evidence)")
    ap.add_argument("--books", default=None)
    ap.add_argument("--doc", default=str(HERE / "T16.md"), help="the write-up whose frozen hash the page quotes")
    a = ap.parse_args()
    ev = Path(a.evidence) if a.evidence else HERE / "evidence" / a.run
    outdir = Path(a.out) if a.out else (ev if a.evidence else HERE / "evidence")
    books = a.books.split(",") if a.books else None
    if not any((ev / w / "audit.json").exists() for w in ("w1", "w2")):
        print(f"report.py: no evidence under {ev} (run the engine first); nothing written; exit 1")
        return 1
    Ws = {}
    for w in ("w1", "w2"):
        if (ev / w / "audit.json").exists():
            W = A.Win(ev, w, books)
            W.r3_dates = load_r3_dates(W)
            n = W.nav
            W.curve_for = lambda b, cost, run, n=n: (lambda g: (g["date"].to_numpy(), g["nav"].to_numpy()))(n[(n["book"] == b) & (n["cost_bps"] == cost) & (n["run"] == run)].sort_values("date"))
            Ws[w] = W
    head_by = {(w, base): A.compare(W, "headline", "full", PRIMARY, base) for w, W in Ws.items() for base in BASES}
    gates = {w: gate_strings(W) for w, W in Ws.items()}
    lines_data, rel_data = {}, {}
    sha = prereg_hash(Path(a.doc), )
    parts = [section_answer(Ws, head_by), section_data(Ws, gates), section_example(Ws), section_desc(Ws), section_curves(Ws, lines_data, rel_data), section_robust(Ws, head_by), section_defs(sha, True, ev.name)]
    W0 = next(iter(Ws.values()))
    n_books = len(W0.books)
    note = "" if n_books == 4 else f'<p class="warn"><b>Development run: {n_books} book(s); every count of books and every verdict on this page means nothing.</b></p>'
    # NOTE: no rule id and no run label may appear before the rules-and-runs table (AGENT.md R10 item 1): the heading and the contents line below name none.
    head = (f'<h1>T16: holding the three indices and the liquid ETF, a quarter each, when the three-index switch is OUT and the gold signal is SELL</h1><p class="mini">Test T16, run <b>{E(ev.name)}</b>; descriptive, no null, no chance claim (waiver); findings PROVISIONAL at most; '
            f'pre-registration sha256 {sha[1][:16]}; every table carries its own dates. Contents: '
            '<a href="#answer">answer</a>, <a href="#rules-runs-h">rules and runs in words</a>, <a href="#data">data</a>, <a href="#example">one backtest</a>, <a href="#desc">D-table and ledger</a>, <a href="#curves">curves</a>, <a href="#robust">robustness</a>, <a href="#defs">definitions</a>.</p>' + note)
    page = (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>T16 OUT-SELL all-index holding results</title><style>{CSS}</style></head>'
            f'<body><main>{head}{"".join(parts)}</main><script id="lines-data" type="application/json">{json.dumps(lines_data)}</script>'
            f'<script id="rel-data" type="application/json">{json.dumps(rel_data)}</script><script>{LINES_JS}</script></body></html>')
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "report.html").write_text(page, encoding="utf-8")
    print(f"wrote {outdir / 'report.html'} ({len(page):,} bytes; {page.count('class=' + chr(34) + 'v' + chr(34)):,} numbers with provenance, {len(lines_data)} curve charts)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
