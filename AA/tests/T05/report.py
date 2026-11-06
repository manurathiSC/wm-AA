# -*- coding: utf-8 -*-
"""Build evidence/<run>/report.html for T05 from the shipped evidence only (AGENT.md R10).

    python tests/T05/report.py [--run headline] [--root DIR]            (from AA/)

Every number on the page comes from evidence/<run>/*.csv, audit.json, analysis_summary.json and analysis.log (the tables are the analyse.py output, rendered).
T04's counts for the "Reviews vs T04 decisions" comparison are read as data from tests/T04/evidence/headline/.
Every chart has a crosshair, an x chip and a y chip, and a tooltip listing every value drawn at that x (a global rule).
--root (default: this folder) is where evidence/<run>/ and analysis.log are read; it exists to exercise the script on a scratch copy.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import analyse as AN  # noqa: E402  (same folder: evidence loaders and the review-schedule rule)

IND = AN.IND
NAME = AN.NAME
COL = {"I1": "#2a6fdb", "I2": "#2f9e6e", "I3": "#c9811a", "I4": "#b04a9b", "I5": "#d6453d", "full_aa_switch": "#111111", "hold_parent": "#8a8f98", "published": "#7a5cff",
       "t05": "#111111", "monthly": "#2a6fdb", "forced": "#d6453d", "t04": "#8a8f98"}
PRIMARY = AN.PRIMARY
E = html.escape


def inline(t: str) -> str:
    t = E(t)
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"`(.+?)`", r"<code>\1</code>", t)
    t = re.sub(r"(?<![\w*])\*([^*\n]+?)\*(?![\w*])", r"<i>\1</i>", t)
    return t


def md_to_html(text: str) -> str:
    out, lines, i = [], text.split("\n"), 0
    while i < len(lines):
        ln = lines[i]
        if ln.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            head, body = rows[0], rows[2:]
            out.append('<div class="tw"><table><thead><tr>' + "".join(f"<th>{inline(c)}</th>" for c in head) + "</tr></thead><tbody>")
            for r in body:
                cls = ""
                joined = " ".join(r)
                out.append(f"<tr{cls}>" + "".join(f'<td class="{ "pass" if c == "PASS" else "fail" if c in ("FAIL", "NO") else ""}">{inline(c)}</td>' for c in r) + "</tr>")
            out.append("</tbody></table></div>")
            continue
        if ln.startswith("### "):
            out.append(f"<h4>{inline(ln[4:])}</h4>")
        elif ln.startswith("## "):
            out.append(f"<h3>{inline(ln[3:])}</h3>")
        elif ln.startswith("# "):
            pass
        elif ln.startswith("- "):
            items = []
            while i < len(lines) and lines[i].startswith("- "):
                items.append(f"<li>{inline(lines[i][2:])}</li>")
                i += 1
            out.append("<ul>" + "".join(items) + "</ul>")
            continue
        elif ln.strip():
            out.append(f"<p>{inline(ln)}</p>")
        i += 1
    return "\n".join(out)


def hist_data(x: np.ndarray, mark: float, bins: int = 36):
    lo, hi = float(min(x.min(), mark)), float(max(x.max(), mark))
    pad = (hi - lo) * 0.03
    cnt, edges = np.histogram(x, bins=bins, range=(lo - pad, hi + pad))
    return {"edges": [round(float(e), 6) for e in edges], "counts": [int(c) for c in cnt], "mark": float(mark), "n": int(len(x)),
            "sorted": [round(float(v), 6) for v in np.sort(x)[:: max(1, len(x) // 400)]], "all_sorted_min": float(x.min()), "all_sorted_max": float(x.max())}


JS = r"""
const NS='http://www.w3.org/2000/svg';
function el(n,a,p){const e=document.createElementNS(NS,n);for(const k in a)e.setAttribute(k,a[k]);if(p)p.appendChild(e);return e}
function nice(a,b,k){const s=(b-a)/k,m=Math.pow(10,Math.floor(Math.log10(s))),r=s/m,st=(r<1.5?1:r<3?2:r<7?5:10)*m;const o=[];for(let v=Math.ceil(a/st)*st;v<=b+1e-9;v+=st)o.push(+v.toFixed(10));return o}
function mk(host){const box=document.getElementById(host);const tip=document.createElement('div');tip.className='tip';tip.hidden=true;box.appendChild(tip);return {box,tip}}
function place(box,tip,e){const r=box.getBoundingClientRect();let x=e.clientX-r.left+14,y=e.clientY-r.top+10;tip.hidden=false;const w=tip.offsetWidth,h=tip.offsetHeight;if(x+w>r.width-4)x=e.clientX-r.left-w-14;if(y+h>r.height-4)y=Math.max(4,r.height-h-4);tip.style.left=x+'px';tip.style.top=y+'px'}
function lineChart(host,c){
 const {box,tip}=mk(host),W=900,H=c.h||330,L=58,R=12,T=10,B=26,n=c.x.length;
 const svg=el('svg',{viewBox:`0 0 ${W} ${H}`,class:'chart',role:'img','aria-label':c.label},box);
 let vals=[];c.series.forEach(s=>s.y.forEach(v=>{if(v!=null&&isFinite(v))vals.push(v)}));
 let lo=Math.min(...vals),hi=Math.max(...vals);if(c.log){lo=Math.log(lo);hi=Math.log(hi)}
 const pad=(hi-lo)*0.05;lo-=pad;hi+=pad;
 const X=i=>L+(W-L-R)*i/(n-1),Y=v=>{const t=c.log?Math.log(v):v;return T+(H-T-B)*(1-(t-lo)/(hi-lo))};
 const ticks=nice(c.log?Math.exp(lo):lo,c.log?Math.exp(hi):hi,5);
 ticks.forEach(v=>{if(c.log&&v<=0)return;const y=Y(v);el('line',{x1:L,x2:W-R,y1:y,y2:y,class:'grid'},svg);const t=el('text',{x:L-6,y:y+3,class:'ax','text-anchor':'end'},svg);t.textContent=c.yfmt(v)});
 let lastY='';c.x.forEach((d,i)=>{const y=d.slice(0,4);if(y!==lastY&&(+y%1===0)){lastY=y;const x=X(i);el('line',{x1:x,x2:x,y1:T,y2:H-B,class:'grid'},svg);const t=el('text',{x:x+2,y:H-8,class:'ax'},svg);t.textContent=y}});
 (c.shade||[]).forEach(r=>el('rect',{x:X(r[0]),y:T,width:Math.max(1,X(r[1])-X(r[0])),height:H-T-B,fill:'var(--shade)'},svg));
 c.series.forEach(s=>{let d='',on=false;s.y.forEach((v,i)=>{if(v==null||!isFinite(v)){on=false;return}d+=(on?'L':'M')+X(i).toFixed(1)+' '+Y(v).toFixed(1);on=true});el('path',{d,fill:'none',stroke:s.color,'stroke-width':s.w||1.5,'stroke-dasharray':s.dash||''},svg)});
 const cross=el('line',{y1:T,y2:H-B,class:'cross',visibility:'hidden'},svg),dots=c.series.map(s=>el('circle',{r:3,fill:s.color,visibility:'hidden'},svg));
 const xr=el('rect',{height:16,rx:3,class:'chip',visibility:'hidden'},svg),xt=el('text',{class:'chipt','text-anchor':'middle',visibility:'hidden'},svg);
 const yr=el('rect',{height:16,rx:3,class:'chip',visibility:'hidden'},svg),yt=el('text',{class:'chipt','text-anchor':'end',visibility:'hidden'},svg);
 const ov=el('rect',{x:L,y:T,width:W-L-R,height:H-T-B,fill:'transparent',style:'cursor:crosshair;touch-action:none'},svg);
 function mv(e){const r=svg.getBoundingClientRect(),k=W/r.width,vx=(e.clientX-r.left)*k,vy=(e.clientY-r.top)*k;let i=Math.round((vx-L)/(W-L-R)*(n-1));i=Math.max(0,Math.min(n-1,i));
  const x=X(i);cross.setAttribute('x1',x);cross.setAttribute('x2',x);cross.setAttribute('visibility','visible');
  const lab=c.x[i];xt.textContent=lab;const w=lab.length*6.4+10;xr.setAttribute('width',w);xr.setAttribute('x',Math.min(W-R-w,Math.max(L,x-w/2)));xr.setAttribute('y',H-B+2);xt.setAttribute('x',+xr.getAttribute('x')+w/2);xt.setAttribute('y',H-B+14);
  [xr,xt].forEach(q=>q.setAttribute('visibility','visible'));
  const frac=Math.max(0,Math.min(1,(vy-T)/(H-T-B)));let yv=lo+(hi-lo)*(1-frac);yv=c.log?Math.exp(yv):yv;const ys=c.yfmt(yv);yt.textContent=ys;const yw=ys.length*6.4+10;yr.setAttribute('width',yw);yr.setAttribute('x',L-yw);yr.setAttribute('y',Math.max(T,Math.min(H-B-16,vy-8)));yt.setAttribute('x',L-5);yt.setAttribute('y',+yr.getAttribute('y')+12);[yr,yt].forEach(q=>q.setAttribute('visibility','visible'));
  const rows=[];c.series.forEach((s,k2)=>{const v=s.y[i];if(v==null||!isFinite(v)){dots[k2].setAttribute('visibility','hidden');return}dots[k2].setAttribute('cx',x);dots[k2].setAttribute('cy',Y(v));dots[k2].setAttribute('visibility','visible');rows.push([s,v])});
  rows.sort((a,b)=>b[1]-a[1]);tip.innerHTML='<b>'+lab+'</b>'+(c.note?'<div class="mut">'+c.note[i]+'</div>':'')+rows.map(r=>`<div><span class="sw" style="background:${r[0].color}"></span>${r[0].name}: <b>${c.vfmt(r[1])}</b></div>`).join('');place(box,tip,e)}
 function lv(){[cross,xr,xt,yr,yt,...dots].forEach(q=>q.setAttribute('visibility','hidden'));tip.hidden=true}
 ov.addEventListener('pointermove',mv);ov.addEventListener('pointerdown',mv);ov.addEventListener('pointerleave',lv);
 const lg=document.createElement('div');lg.className='legend';lg.innerHTML=c.series.map(s=>`<span><i style="background:${s.color}"></i>${s.name}</span>`).join('');box.appendChild(lg)}
function histChart(host,c){
 const {box,tip}=mk(host),W=440,H=190,L=40,R=10,T=10,B=28,e=c.edges,nb=c.counts.length,mx=Math.max(...c.counts);
 const svg=el('svg',{viewBox:`0 0 ${W} ${H}`,class:'chart',role:'img','aria-label':c.label},box);
 const X=v=>L+(W-L-R)*(v-e[0])/(e[nb]-e[0]),Y=v=>T+(H-T-B)*(1-v/mx);
 nice(0,mx,3).forEach(v=>{el('line',{x1:L,x2:W-R,y1:Y(v),y2:Y(v),class:'grid'},svg);const t=el('text',{x:L-4,y:Y(v)+3,class:'ax','text-anchor':'end'},svg);t.textContent=v});
 nice(e[0],e[nb],5).forEach(v=>{const t=el('text',{x:X(v),y:H-12,class:'ax','text-anchor':'middle'},svg);t.textContent=c.xfmt(v)});
 c.counts.forEach((v,i)=>el('rect',{x:X(e[i])+0.5,y:Y(v),width:Math.max(0.5,X(e[i+1])-X(e[i])-1),height:H-B-Y(v),class:'bar'},svg));
 el('line',{x1:X(c.mark),x2:X(c.mark),y1:T,y2:H-B,stroke:'var(--accent)','stroke-width':2},svg);
 const cross=el('line',{y1:T,y2:H-B,class:'cross',visibility:'hidden'},svg),xr=el('rect',{height:16,rx:3,class:'chip',visibility:'hidden'},svg),xt=el('text',{class:'chipt','text-anchor':'middle',visibility:'hidden'},svg),yr=el('rect',{height:16,rx:3,class:'chip',visibility:'hidden'},svg),yt=el('text',{class:'chipt','text-anchor':'end',visibility:'hidden'},svg);
 const ov=el('rect',{x:L,y:T,width:W-L-R,height:H-T-B,fill:'transparent',style:'cursor:crosshair;touch-action:none'},svg);
 function mv(ev){const r=svg.getBoundingClientRect(),k=W/r.width,vx=(ev.clientX-r.left)*k,vy=(ev.clientY-r.top)*k;const v=e[0]+(e[nb]-e[0])*(vx-L)/(W-L-R);let b=0;while(b<nb-1&&v>=e[b+1])b++;
  cross.setAttribute('x1',vx);cross.setAttribute('x2',vx);cross.setAttribute('visibility','visible');
  const lab=c.xfmt(v),w=lab.length*6.4+10;xr.setAttribute('width',w);xr.setAttribute('x',Math.min(W-R-w,Math.max(L,vx-w/2)));xr.setAttribute('y',H-B+2);xt.textContent=lab;xt.setAttribute('x',+xr.getAttribute('x')+w/2);xt.setAttribute('y',H-B+14);
  const frac=Math.max(0,Math.min(1,(vy-T)/(H-T-B)));const yv=Math.round(mx*(1-frac)),ys=String(yv),yw=ys.length*6.4+10;yr.setAttribute('width',yw);yr.setAttribute('x',L-yw);yr.setAttribute('y',Math.max(T,Math.min(H-B-16,vy-8)));yt.textContent=ys;yt.setAttribute('x',L-5);yt.setAttribute('y',+yr.getAttribute('y')+12);
  [xr,xt,yr,yt].forEach(q=>q.setAttribute('visibility','visible'));
  const below=c.counts.slice(0,b).reduce((a,x)=>a+x,0);
  tip.innerHTML=`<b>${c.xfmt(e[b])} to ${c.xfmt(e[b+1])}</b><div>draws in this bin: <b>${c.counts[b]}</b></div><div>draws below this bin: <b>${below}</b> of ${c.n}</div><div>the strategy: <b>${c.xfmt(c.mark)}</b></div><div>draws, min to max: ${c.xfmt(c.all_min)} to ${c.xfmt(c.all_max)}</div>`;place(box,tip,ev)}
 function lv(){[cross,xr,xt,yr,yt].forEach(q=>q.setAttribute('visibility','hidden'));tip.hidden=true}
 ov.addEventListener('pointermove',mv);ov.addEventListener('pointerdown',mv);ov.addEventListener('pointerleave',lv)}
const D=JSON.parse(document.getElementById('page-data').textContent);
const f1=v=>v.toFixed(2),pct=v=>(100*v).toFixed(1)+'%';
lineChart('c-nav',{x:D.nav.dates,series:D.nav.series,log:true,yfmt:v=>v.toFixed(v<10?1:0),vfmt:f1,label:'Growth of 1, after 20.8 bps',shade:D.nav.shade});
lineChart('c-dd',{x:D.dd.dates,series:D.dd.series,log:false,yfmt:v=>(100*v).toFixed(0)+'%',vfmt:pct,label:'Drawdown from the running peak'});
lineChart('c-rev',{x:D.rev.dates,series:D.rev.series,log:false,yfmt:v=>v.toFixed(0),vfmt:v=>v.toFixed(0),label:'Cumulative filter evaluations',h:280,note:D.rev.note,shade:D.rev.shade});
lineChart('c-share',{x:D.share.dates,series:D.share.series,log:false,yfmt:v=>(100*v).toFixed(0)+'%',vfmt:pct,label:'Share of the basket kept',h:280,note:D.share.note,shade:D.share.shade});
D.hist.forEach(h=>{histChart('h-c-'+h.ind,{...h.cagr,xfmt:v=>(100*v).toFixed(1)+'%',all_min:h.cagr.all_sorted_min,all_max:h.cagr.all_sorted_max,label:'null CAGR '+h.ind});histChart('h-d-'+h.ind,{...h.dd,xfmt:v=>(100*v).toFixed(1)+'%',all_min:h.dd.all_sorted_min,all_max:h.dd.all_sorted_max,label:'null max drawdown '+h.ind})});
"""

CSS = """
:root{--bg:#fff;--fg:#1c2026;--muted:#5d6672;--card:#f6f7f9;--line:#d9dde3;--bar:#aeb7c4;--accent:#d6453d;--ok:#1d7f55;--bad:#c0392b;--shade:rgba(214,69,61,.08)}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#14161a;--fg:#e6e8eb;--muted:#9aa1ab;--card:#1b1e23;--line:#2d3138;--bar:#4a5260;--accent:#ff7b72;--ok:#4cc38a;--bad:#ff7b72;--shade:rgba(255,123,114,.10)}}
:root[data-theme=dark]{--bg:#14161a;--fg:#e6e8eb;--muted:#9aa1ab;--card:#1b1e23;--line:#2d3138;--bar:#4a5260;--accent:#ff7b72;--ok:#4cc38a;--bad:#ff7b72;--shade:rgba(255,123,114,.10)}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,Segoe UI,Roboto,sans-serif}
main{max-width:980px;margin:0 auto;padding:16px}h1{font-size:22px;margin:8px 0}h3{font-size:18px;margin:26px 0 6px}h4{font-size:15px;margin:16px 0 4px}p,li{max-width:84ch}
.sub{color:var(--muted)}.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:10px 12px;margin:12px 0;position:relative}
.tw{overflow-x:auto;margin:8px 0}table{border-collapse:collapse;font-size:13px;min-width:100%}th,td{border-bottom:1px solid var(--line);padding:4px 8px;text-align:left;white-space:nowrap}th{color:var(--muted);font-weight:600}
td.pass{color:var(--ok);font-weight:600}td.fail{color:var(--bad);font-weight:600}code{font-size:12px;background:var(--card);padding:0 3px;border-radius:3px}
.chart{width:100%;height:auto;display:block}.grid{stroke:var(--line);stroke-width:1}.ax{fill:var(--muted);font-size:10px}.bar{fill:var(--bar)}.cross{stroke:var(--muted);stroke-width:1;stroke-dasharray:3 3}.chip{fill:var(--fg)}.chipt{fill:var(--bg);font-size:10px;font-weight:600}
.tip{position:absolute;z-index:5;pointer-events:none;background:var(--bg);color:var(--fg);border:1px solid var(--line);border-radius:6px;padding:6px 8px;font-size:12px;box-shadow:0 2px 8px rgba(0,0,0,.18);white-space:nowrap}.tip .mut{color:var(--muted)}
.sw{display:inline-block;width:9px;height:9px;border-radius:2px;margin-right:5px}.legend{display:flex;flex-wrap:wrap;gap:4px 14px;font-size:12px;margin-top:4px}.legend i{display:inline-block;width:14px;height:3px;margin-right:5px;vertical-align:middle}
.two{display:grid;grid-template-columns:1fr 1fr;gap:10px}@media (max-width:680px){.two{grid-template-columns:1fr}}.cap{font-size:13px;color:var(--muted);margin:0 0 4px}
.verdict{border-left:4px solid var(--accent)}
"""



def table_html(df: pd.DataFrame, fmt: dict | None = None) -> str:
    fmt = fmt or {}
    out = ['<div class="tw"><table><thead><tr>' + "".join(f"<th>{E(str(c))}</th>" for c in df.columns) + "</tr></thead><tbody>"]
    for _, r in df.iterrows():
        cells = []
        for c in df.columns:
            v = r[c]
            if isinstance(v, (float, np.floating)):
                v = "" if np.isnan(v) else fmt.get(c, "{:.2f}").format(v)
            cells.append(f"<td>{E(str(v))}</td>")
        out.append("<tr>" + "".join(cells) + "</tr>")
    out.append("</tbody></table></div>")
    return "".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="headline")
    ap.add_argument("--root", default=str(HERE))
    ap.add_argument("--t04", default=str(AN.T04_DIR))
    a = ap.parse_args()
    root, t04dir = Path(a.root), Path(a.t04)
    ev = root / "evidence" / a.run
    s = pd.read_csv(ev / "stats.csv")
    d = pd.read_csv(ev / "draws.csv")
    nav = pd.read_csv(ev / "daily_nav.csv").rename(columns={"session": "date"})
    nav["date"] = pd.to_datetime(nav["date"])
    dec = AN.load_decisions(ev)                      # decision_date stays a string
    sel = AN.load_selections(ev, dec)
    sch = AN.review_schedule(dec)                    # carries a datetime column `date`
    dec["decision_date"] = pd.to_datetime(dec["decision_date"])
    audit = json.loads((ev / "audit.json").read_text(encoding="utf-8"))
    summ = json.loads((ev / "analysis_summary.json").read_text(encoding="utf-8"))
    log = (root / "analysis.log").read_text(encoding="utf-8")
    res = summ["res"]
    rv_s = summ["reviews"]
    # T04's counts, as data
    t04ev = t04dir / "evidence" / "headline"
    t04_audit = json.loads((t04ev / "audit.json").read_text(encoding="utf-8"))
    t04_dec = pd.read_csv(t04ev / "decisions.csv", parse_dates=["decision_date"])
    t04_stats = pd.read_csv(t04ev / "stats.csv")

    # equity curves
    def ser(kind, ind="", cost=PRIMARY):
        return nav[(nav.kind == kind) & (nav.indicator.fillna("") == ind) & ((nav.cost_bps == cost) | nav.cost_bps.isna())].set_index("date")["nav"]
    base = ser("full_aa_switch")
    dates = base.index
    series, ddser = [], []
    items = [("Full AA switch (T03)", ser("full_aa_switch"), COL["full_aa_switch"], 2.2), ("Hold the parent", ser("hold_parent"), COL["hold_parent"], 1.5)]
    items += [(f"{n} {NAME[n]}", ser("strategy", n), COL[n], 1.4) for n in IND]
    items += [("Published NAV (to 2026-10-22)", ser("published_SCMO_0003", ""), COL["published"], 1.2)]
    for name, sr, col, w in items:
        sr = sr.reindex(dates)
        series.append({"name": name, "color": col, "w": w, "dash": "4 3" if name.startswith("Published") else "", "y": [None if np.isnan(v) else round(float(v), 5) for v in sr.values]})
        if not name.startswith("Published"):
            ddv = sr / sr.cummax() - 1
            ddser.append({"name": name, "color": col, "w": w, "dash": "", "y": [round(float(v), 5) for v in ddv.values]})
    # SELL shading on daily axis
    shade = []
    pos = {dt: i for i, dt in enumerate(dates)}
    dd_dates = list(dec["decision_date"])
    for j, dt in enumerate(dd_dates):
        if dec["state"].iloc[j] == 0:
            i0 = pos[dt]
            i1 = pos[dd_dates[j + 1]] if j + 1 < len(dd_dates) else len(dates) - 1
            if shade and shade[-1][1] == i0:
                shade[-1][1] = i1
            else:
                shade.append([i0, i1])
    # share kept (it changes only at reviews and basket changes)
    sh_series = []
    sdates = list(dec["decision_date"])
    sf = sel[sel["window"] == "full"]
    for n in IND:
        x = sf[sf["indicator"] == n].set_index("j").reindex(dec["j"])
        share = np.where(dec["state"].values == 1, 1.0, (x["k"] / x["n"]).values)
        sh_series.append({"name": f"{n} {NAME[n]}", "color": COL[n], "w": 1.3, "dash": "", "y": [round(float(v), 4) for v in share]})
    n1 = sf[sf["indicator"] == "I1"].set_index("j")["n"]
    notes = []
    for j in range(len(dec)):
        r = sch.iloc[j]
        tag = f"; REVIEW ({r['kind']})" if r["effective"] else ("; month-end flag in a BUY week, no effect" if r["review"] else ("; frozen kept set" if r["state"] == 0 else ""))
        jj = int(dec["j"].iloc[j])
        notes.append(f"regime {dec['regime'].iloc[j]}{tag}" + (f"; basket n = {int(n1.loc[jj])}" if jj in n1.index else ""))
    sshade = []
    for j in range(len(dec)):
        if dec["state"].iloc[j] == 0:
            if sshade and sshade[-1][1] == j:
                sshade[-1][1] = j + 1
            else:
                sshade.append([j, j + 1])
    # cumulative evaluations: T05 reviews vs T04 SELL decisions, on T05's decision dates
    cum_t05 = sch["effective"].astype(int).cumsum()
    cum_mon = (sch["effective"] & sch["is_monthly"] & ~sch["is_forced"]).astype(int).cumsum()
    cum_for = (sch["effective"] & sch["is_forced"]).astype(int).cumsum()
    t4c = (t04_dec.assign(sellc=(t04_dec["state"] == 0).astype(int)).set_index("decision_date")["sellc"].cumsum()).reindex(dec["decision_date"]).ffill().fillna(0)
    rev_series = [{"name": "T05 reviews in SELL (total)", "color": COL["t05"], "w": 2.2, "dash": "", "y": [int(v) for v in cum_t05]},
                  {"name": "T05 monthly reviews", "color": COL["monthly"], "w": 1.4, "dash": "", "y": [int(v) for v in cum_mon]},
                  {"name": "T05 forced reviews (first SELL decision of a spell)", "color": COL["forced"], "w": 1.4, "dash": "", "y": [int(v) for v in cum_for]},
                  {"name": "T04 SELL decisions filtered (weekly)", "color": COL["t04"], "w": 1.8, "dash": "4 3", "y": [int(v) for v in t4c]}]
    # histograms
    hist = []
    for n in IND:
        r = s[(s.kind == "strategy") & (s.indicator == n) & (s.window == "full") & (s.sleeve == "50_50") & (s.cash == "lbes") & (s.cost_bps == PRIMARY)].iloc[0]
        x = d[(d.indicator == n) & (d.window == "full") & (d.sleeve == "50_50") & (d.cash == "lbes") & (d.cost_bps == PRIMARY)]
        hist.append({"ind": n, "cagr": hist_data(x["cagr"].values, r["cagr"]), "dd": hist_data(x["max_dd"].values, r["max_dd"])})
    data = {"nav": {"dates": [str(x.date()) for x in dates], "series": series, "shade": shade},
            "dd": {"dates": [str(x.date()) for x in dates], "series": ddser},
            "share": {"dates": [str(x.date()) for x in sdates], "series": sh_series, "note": notes, "shade": sshade},
            "rev": {"dates": [str(x.date()) for x in sdates], "series": rev_series, "note": notes, "shade": sshade}, "hist": hist}

    c1p = [n for n in IND if res[n]["c1"]]
    c2p = [n for n in IND if res[n]["c2"]]
    r5 = summ["r5"]
    gates = "all five gates pass" if summ["gates_ok"] else "A VALIDITY GATE FAILED: do not read the results"
    fa = float(s[(s.kind == 'full_aa_switch') & (s.cost_bps == PRIMARY)].iloc[0]['cagr'])
    below = [n for n in IND if res[n]["cagr"] < fa]
    sel_c1 = [n for n in c1p if res[n]["cls"] == "selection"]
    to_c1 = [n for n in c1p if res[n]["cls"] == "turnover-driven"]
    headline = (f"<b>Verdict.</b> {gates}. {rv_s['n_all']} filter reviews in SELL ({rv_s['monthly']} monthly only, {rv_s['forced']} forced). "
                f"Indicators passing the pre-registered selection test C1 (CAGR percentile &ge; 98): <b>{', '.join(c1p) if c1p else 'none'}</b>"
                + (f" (classed selection: {', '.join(sel_c1) if sel_c1 else 'none'}; turnover-driven, 0 bps percentile below 98: {', '.join(to_c1) if to_c1 else 'none'})" if c1p else "")
                + f"; passing the protection test C2: <b>{', '.join(c2p) if c2p else 'none'}</b>. "
                f"Best-of-sweep null (R5): percentile {r5['pct']:.1f}, <b>{'PASS' if r5['pct'] >= 98 else 'FAIL'}</b>. "
                f"{'Every indicator' if len(below) == len(IND) else str(len(below)) + ' of 5 indicators'} earns less than the full AA switch ({100 * fa:.1f}% a year after cost).")
    nd = audit["run"]["draws"]
    hist_html = "".join(f'<div class="card"><b>{n} {NAME[n]}</b> '
                        f'<span class="sub">C1 percentile {res[n]["pc"]:.1f} (at 0 bps: {res[n]["pc0"]:.1f}; {res[n]["cls"]}), C2 percentile {res[n]["pm"]:.1f}</span><div class="two"><div><div class="cap">After-cost CAGR of {nd:,} random same-size monthly selections (red line = the indicator)</div><div id="h-c-{n}" class="rel"></div></div>'
                        f'<div><div class="cap">Maximum drawdown of the same draws (shallower is to the right)</div><div id="h-d-{n}" class="rel"></div></div></div></div>' for n in IND)

    # review dates section
    rv = sch[sch["effective"]].copy()
    sk = sf.pivot(index="j", columns="indicator", values="k")
    nb = sf[sf["indicator"] == "I1"].set_index("j")["n"]
    tcol = "trade_date" if "trade_date" in rv.columns else None
    tab = pd.DataFrame({"#": range(1, len(rv) + 1), "decision date": rv["decision_date"].values, "kind": rv["kind"].values, "SELL spell": rv["spell"].values,
                        "trade session": [(str(x)[:10] if str(x) not in ("nan", "NaT", "None") else "not traded") for x in (rv[tcol].values if tcol else [""] * len(rv))],
                        "n": [int(nb.loc[j]) if j in nb.index else "" for j in rv["j"]]})
    for nm in IND:
        tab[f"k {nm}"] = [int(sk.loc[j, nm]) if j in sk.index else "" for j in rv["j"]]
    buyflag = sch[sch["review"] & (sch["state"] == 1)]
    yrs = sorted(set(rv["date"].dt.year))
    month_tab = pd.DataFrame({"year": [str(y) for y in yrs],
                              "reviews in SELL": [int((rv["date"].dt.year == y).sum()) for y in yrs],
                              "of which forced": [int(((rv["date"].dt.year == y) & rv["is_forced"]).sum()) for y in yrs],
                              "SELL decisions (T04 filtered all of them)": [int(((sch["date"].dt.year == y) & (sch["state"] == 0)).sum()) for y in yrs]})
    review_html = (f"<p>The regime is read every week; the stock filter is evaluated only on <b>review</b> dates: the last weekly decision of each calendar month, and the first SELL decision of every SELL spell (a BUY to SELL flip, or decision 0). "
                   f"A flag only matters in SELL. <b>{rv_s['n_all']}</b> reviews fall in SELL ({rv_s['monthly']} monthly only, {rv_s['forced']} forced, of which {rv_s['both']} are also month-end); "
                   f"{rv_s['n_traded']} are traded (the last decision, {str(sch['decision_date'].iloc[-1])[:10]}, is flagged but not traded). {rv_s['flag_in_buy']} more month-end flags fall in BUY weeks and do nothing. "
                   f"The flag is set on {rv_s['flag_total']} of {len(sch)} decisions in all.</p>"
                   "<div class=\"cap\">Reviews in SELL by year</div>" + table_html(month_tab) +
                   "<div class=\"cap\">The schedule: every review in SELL (n = basket size in force, k = stocks each indicator keeps)</div>" + table_html(tab) +
                   (f"<p class=\"sub\">Flagged decisions in BUY weeks (no effect): {', '.join(str(x)[:10] for x in buyflag['decision_date'])}.</p>" if len(buyflag) else ""))

    # reviews vs T04 decisions (counts)
    t4d = t04_audit["decisions"]
    t4rep = t04_audit["reportability"]
    n_sell = int((dec["state"] == 0).sum())
    rows = [("weekly decisions in the window", t4d["n"], len(dec)),
            ("SELL decisions", t4d["sell"], n_sell),
            ("filter evaluations (T04: every SELL decision; T05: reviews in SELL)", t4d["sell"], rv_s["n_all"])]
    for nm in IND:
        rows.append((f"{nm} evaluations with 1 <= k < n (T05: traded reviews)", t4rep[f"full|{nm}"]["nontrivial"], summ["rep"][f"full|{nm}"]["nontrivial"]))
    for nm in IND:
        q = "kind == 'strategy' and indicator == @nm and window == 'full' and sleeve == '50_50' and cash == 'lbes' and cost_bps == @PRIMARY"
        rows.append((f"{nm} strategy trades at 20.8 bps", int(t04_stats.query(q)["trades"].iloc[0]), int(s.query(q)["trades"].iloc[0])))
    cmp_df = pd.DataFrame([{"item": i, "T04 (weekly filter)": a4, "T05 (monthly filter)": a5, "T05 / T04": f"{a5 / a4:.2f}" if a4 else ""} for i, a4, a5 in rows])
    cmp_html = ("<p>T04 evaluated the filter at every SELL week; T05 evaluates it at a review and reuses the stored pass set in between. The counts below are T04's, read as data from <code>tests/T04/evidence/headline/</code>, and T05's. "
                "The chart steps up once per evaluation: the T05 total rises by about one a month while in SELL, T04's by one a week.</p>" + table_html(cmp_df))

    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>T05 monthly stock filter in SELL</title><style>{CSS}.rel{{position:relative}}</style></head><body><main>
<h1>T05: during a SELL regime, does a monthly stock filter pick better than a random monthly pick?</h1>
<p class="sub">SCMO_0003 · {audit['decisions']['t0']} → {audit['decisions']['end']} · five indicators, {nd:,} random same-size selections each · after 20.8 bps · pre-registration sha256 <code>{audit['prereg_sha256'][:12]}</code></p>
<div class="card verdict">{headline}</div>
<h3>How to read this</h3>
<p>Each week the three-index supertrend says BUY or SELL. On BUY the book holds the parent's whole basket. On SELL, at the first SELL week of a spell and then at each month-end, the book keeps the stocks that pass an indicator (close above a moving average, or a weekly SuperTrend on BUY) and puts the rest into half GOLDBEES and half cash; between those reviews the list of passers is frozen. The null keeps the <i>same number</i> of stocks at each review, picked at random with that review's own random numbers, and freezes them until the next review. If an indicator's CAGR sits in the top 2% of those random picks it passes; a pass counts as selection only if it also holds at 0 bps. Shaded bands on the curves are SELL weeks. Hover or touch any chart: the crosshair shows the x and y at the pointer and the tooltip lists every value drawn at that x.</p>
<h3>Growth of 1 (log scale)</h3><div class="card"><div id="c-nav" class="rel"></div></div>
<h3>Drawdown from the running peak</h3><div class="card"><div id="c-dd" class="rel"></div></div>
<h3>Share of the basket kept, by week (BUY weeks are 100%; it moves only at reviews and basket changes)</h3><div class="card"><div id="c-share" class="rel"></div></div>
<h3>Review dates</h3>{review_html}
<h3>Reviews vs T04 decisions</h3><div class="card"><div class="cap">Cumulative filter evaluations by decision date (hover for the review kind on each date)</div><div id="c-rev" class="rel"></div></div>{cmp_html}
<h3>Each indicator against its random picks</h3>{hist_html}
<h3>Tables</h3>
{md_to_html(log)}
</main>
<script type="application/json" id="page-data">{json.dumps(data, separators=(",", ":"))}</script>
<script>{JS}</script></body></html>"""
    (ev / "report.html").write_text(page, encoding="utf-8")
    print("wrote", ev / "report.html", f"{len(page) / 1e6:.2f} MB")


if __name__ == "__main__":
    main()
