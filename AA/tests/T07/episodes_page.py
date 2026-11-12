"""HTML fragment for the results page: why the whole-book switch beats the segment rule, and when. Called by episodes.py; included by report.py."""
from __future__ import annotations

import html
import math

import numpy as np
import pandas as pd

E = html.escape
BOOKS = ["SCMO_0003", "SCMO_0007", "SCMO_0010", "SCMO_0029"]
BCOL = {"SCMO_0003": "#2a6fdb", "SCMO_0007": "#c9811a", "SCMO_0010": "#2f9e6e", "SCMO_0029": "#6b4fbb"}
KCOL = {"False start": "#c23131", "Shake-out": "#2a6fdb", "Decline": "#c9811a", "Recovery": "#2f9e6e"}
SIGN = ["Nifty 100", "Midcap 100", "Smallcap 100"]
KIND_TXT = {
    "False start": "all SELL before and after: one or two indices turned BUY, the third never confirmed, and the market fell back",
    "Shake-out": "all BUY before and after: one index turned SELL, the whole-book switch left, the other two stayed BUY and the market rose",
    "Decline": "all BUY before, all SELL after: the first index to turn SELL started the whole-book exit, the rule left more slowly",
    "Recovery": "all SELL before, all BUY after: the rule bought the first index to turn BUY, the whole-book switch waited for the third",
}


def tbl(rows, cols, cls=""):
    th = "".join(f"<th>{c}</th>" for c in cols)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f'<div class="tw"><table class="{cls}"><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table></div>'


def rnd0(x: float) -> str:
    v = round(x)
    return "0%" if v == 0 else f"{v:+d}%"


def short(kind: str) -> str:
    return kind.split(":")[0]


def buys(pat: str) -> str:
    b = [SIGN[i] for i, c in enumerate(pat) if c == "B"]
    return " + ".join(b) if b else "none"


def sg(x, d=1):
    return "" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:+.{d}f}"


def cls_num(x):
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return ""
    return "pos" if x > 0 else "neg" if x < 0 else ""


def colored(x, d=1, flip=False):
    """Positive = rule ahead (blue), negative = whole-book ahead (dark)."""
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return ""
    return f'<span style="color:{"#2a6fdb" if x > 0 else "#c23131" if x < 0 else "inherit"}">{x:+.{d}f}</span>'


def fig_gap(cv: pd.DataFrame, st0: pd.DataFrame, w=900, h=300):
    L, R, T, B = 54, 12, 26, 26
    cv = cv.copy()
    cv["date"] = pd.to_datetime(cv["date"])
    d0, d1 = cv["date"].min(), cv["date"].max()
    xs = lambda d: L + (w - L - R) * ((d - d0).days / (d1 - d0).days)
    series = {}
    for b in BOOKS:
        g = cv[cv.book == b].iloc[::3]
        series[b] = (g["date"].values, 100 * g["gap_log"].values)
    lo = min(v.min() for _, v in series.values())
    hi = max(v.max() for _, v in series.values())
    lo, hi = math.floor(lo / 10) * 10 - 0, math.ceil(hi / 10) * 10
    y = lambda v: T + (h - T - B) * (1 - (v - lo) / (hi - lo))
    o = [f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="Segment rule against the whole-book switch through time, log points" class="chart">']
    for _, s in st0.iterrows():
        a, e = pd.Timestamp(s["start"]), pd.Timestamp(s["end"])
        col = KCOL[short(s["kind"])]
        o.append(f'<rect x="{xs(a):.1f}" y="{T}" width="{max(xs(e) - xs(a), 1.2):.1f}" height="{h - T - B}" fill="{col}" opacity="0.16"/>')
        o.append(f'<text x="{(xs(a) + xs(e)) / 2:.1f}" y="{T - 8}" text-anchor="middle" class="ax" font-size="9">{int(s["stretch"])}</text>')
    t = lo
    while t <= hi + 1e-9:
        zero = ' stroke="var(--fg)" stroke-width="1"' if t == 0 else ""
        o.append(f'<line x1="{L}" x2="{w - R}" y1="{y(t):.1f}" y2="{y(t):.1f}" class="grid"{zero}/>'
                 f'<text x="{L - 5}" y="{y(t) + 3:.1f}" text-anchor="end" class="ax">{t:+.0f}</text>')
        t += 10
    for yr in range(d0.year, d1.year + 1):
        dd = pd.Timestamp(f"{yr}-01-01")
        if d0 <= dd <= d1:
            o.append(f'<text x="{xs(dd):.1f}" y="{h - 8}" text-anchor="middle" class="ax">{yr}</text>')
    for b in BOOKS:
        dts, v = series[b]
        pts = " ".join(f"{xs(pd.Timestamp(d)):.1f},{y(val):.1f}" for d, val in zip(dts, v))
        o.append(f'<polyline points="{pts}" fill="none" stroke="{BCOL[b]}" stroke-width="1.8" stroke-linejoin="round"/>')
    o.append("</svg>")
    return "".join(o)


def fig_bars(g: pd.DataFrame, w=900, h=300):
    """g: rows = stretch, columns = books, values = 100 x ln(rule value / whole-book value) over the stretch, log points."""
    L, R, T, B = 54, 12, 12, 44
    lo = math.floor(min(g.values.min(), 0) / 10) * 10
    hi = math.ceil(max(g.values.max(), 0) / 10) * 10
    y = lambda v: T + (h - T - B) * (1 - (v - lo) / (hi - lo))
    n = len(g)
    gw = (w - L - R) / n
    bw = gw * 0.8 / 4
    o = [f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="Rule against the whole-book switch in each disagreement stretch, log points" class="chart">']
    t = lo
    while t <= hi + 1e-9:
        o.append(f'<line x1="{L}" x2="{w - R}" y1="{y(t):.1f}" y2="{y(t):.1f}" class="grid"/><text x="{L - 5}" y="{y(t) + 3:.1f}" text-anchor="end" class="ax">{t:+.0f}</text>')
        t += 10
    o.append(f'<line x1="{L}" x2="{w - R}" y1="{y(0):.1f}" y2="{y(0):.1f}" stroke="var(--fg)" stroke-width="1"/>')
    for i, (k, row) in enumerate(g.iterrows()):
        x0 = L + i * gw + gw * 0.1
        for j, b in enumerate(BOOKS):
            v = row[b]
            if v is None or (isinstance(v, float) and math.isnan(v)):
                continue
            y0, y1 = y(0), y(v)
            o.append(f'<rect x="{x0 + j * bw:.1f}" y="{min(y0, y1):.1f}" width="{bw - 0.8:.1f}" height="{max(abs(y1 - y0), 0.6):.1f}" fill="{BCOL[b]}"/>')
        kind = row.name if False else None
        o.append(f'<text x="{L + i * gw + gw / 2:.1f}" y="{h - 26}" text-anchor="middle" class="ax">{int(k)}</text>')
    return "".join(o) + "</svg>"


def build_fragment(df: pd.DataFrame, cv: pd.DataFrame, summ: dict) -> str:
    df = df.copy()
    df["kind_s"] = df["kind"].map(short)
    st0 = df[df.book == "SCMO_0003"].sort_values("stretch")
    # the same 16 stretches in every book: the kind must not depend on the book
    kinds = df.groupby("stretch").kind_s.nunique()
    assert (kinds == 1).all(), "a stretch has a different kind in different books"
    nst = int(df.stretch.max())
    piv = 100 * df.pivot(index="stretch", columns="book", values="gap_log_rule_over_whole")[BOOKS]
    ahead = (df.assign(w=df.rule_minus_whole < 0).groupby("stretch").w.sum())
    pooled = df.groupby("stretch").agg(kind=("kind_s", "first"), avg_pp=("rule_minus_whole_pp", "mean"), kept=("kept_share_mean", "mean"), sleeve=("sleeve_ret", "mean"),
                                       ex_l=("excess_large_pp", "mean"), ex_m=("excess_mid_pp", "mean"), ex_s=("excess_small_pp", "mean"), ex_t=("excess_total_pp", "mean"))
    tot = {b: summ["books"][b]["total_gap_log"] for b in BOOKS}
    outside = {b: summ["books"][b]["outside_log"] for b in BOOKS}
    lg = df.pivot(index="stretch", columns="book", values="gap_log_rule_over_whole")[BOOKS]

    # ── by kind ──
    kind_rows = []
    order = ["False start", "Decline", "Recovery", "Shake-out"]
    for k in order:
        ids = pooled.index[pooled.kind == k]
        pairs = len(ids) * 4
        wa = int(ahead.loc[ids].sum())
        kind_rows.append([f"<div style='white-space:normal;min-width:240px;max-width:420px'><b>{k}</b><br><span class='cap'>{KIND_TXT[k]}</span></div>", ", ".join(str(int(i)) for i in ids), f"{wa} of {pairs}"]
                         + [colored(100 * lg.loc[ids, b].sum(), 0) for b in BOOKS])
    kind_rows.append(["<div style='white-space:normal;min-width:240px;max-width:420px'>Outside the stretches (all SELL or all BUY: both rules hold the same weights; costs and drift only)</div>", "", ""] + [colored(100 * outside[b], 1) for b in BOOKS])
    kind_rows.append(["<b>Total: rule against the whole-book switch</b>", "", f"{int(ahead.sum())} of {4 * nst}"] + [f"<b>{100 * tot[b]:+.0f}</b>" for b in BOOKS])
    # every figure below is 100 x ln(rule / whole-book): positive = the rule is ahead (blue), negative = the whole-book switch is ahead (red)
    # leave-out table
    fs = pooled.index[pooled.kind == "False start"]
    sk = pooled.index[pooled.kind == "Shake-out"]
    big = int(df[df.book == "SCMO_0003"].sort_values("weeks").stretch.iloc[-1])
    assert big in set(fs), "the longest stretch is not a false start: the reading text must be revised"
    lo_rows = []
    for lab, drop in (("All 16 stretches (the result)", []),
                      (f"Without stretch {big} (the longest, {int(st0[st0.stretch == big].weeks.iloc[0])} weeks)", [big]),
                      ("Without the two shake-outs (the rule's best stretches)", list(sk)),
                      ("Without the false starts (the whole-book switch's best stretches)", list(fs))):
        lo_rows.append([lab] + [colored(100 * (tot[b] - lg.loc[drop, b].sum() if drop else tot[b]), 0) for b in BOOKS])
    # ── per-stretch table ──
    srows = []
    for _, s in st0.iterrows():
        i = int(s["stretch"])
        p = pooled.loc[i]
        pats = s["patterns"].split("→")
        buy_txt = " → ".join(buys(q) for q in pats)
        # who the rule kept, in words
        parts = []
        for nm, v in (("Large", p.ex_l), ("Mid", p.ex_m), ("Small and below", p.ex_s)):
            if abs(v) >= 0.5:
                parts.append(f"{nm} {v:+.1f}")
        reason = (f"kept {100 * p.kept:.0f}% of the book on average; kept stocks against the sleeve (pp of the book): " + (", ".join(parts) if parts else "about 0")
                  + f"; sleeve {rnd0(100 * p.sleeve)} over the window") if not math.isnan(p.kept) else "kept share not available (before the first logged trade)"
        srows.append([str(i), f"{s['start']} → {s['end']}", str(int(s["weeks"])), E(buy_txt), f"<span style='color:{KCOL[short(s['kind'])]}'><b>{short(s['kind'])}</b></span>",
                      f"{int(ahead.loc[i])} of 4"] + [colored(piv.loc[i, b], 1) for b in BOOKS] + [f"<div style='white-space:normal;min-width:300px'>{reason}</div>"])
    stretch_tab = tbl(srows, ["#", "Sessions", "Weeks", "BUY signals (Nifty 100, Midcap 100, Smallcap 100)", "Kind", "Whole-book switch ahead in", "0003", "0007", "0010", "0029", "Why (average of the four books)"], "ep")
    # ── band attribution by kind ──
    brow = []
    for k in order:
        d = df[df.kind_s == k]
        for nm, col in (("Large", "excess_large_pp"), ("Mid", "excess_mid_pp"), ("Small and below", "excess_small_pp")):
            vals = [d[d.book == b][col].sum() for b in BOOKS]
            if max(abs(v) for v in vals) < 0.05:
                continue
            brow.append([k, nm] + [colored(v, 1) for v in vals])
    band_tab = tbl(brow, ["Kind", "Band the rule kept", "SCMO_0003", "SCMO_0007", "SCMO_0010", "SCMO_0029"], "ep")
    # ── per-book detail ──
    det = []
    for b in BOOKS:
        d = df[df.book == b].sort_values("stretch")
        rows = [[str(int(r.stretch)), r.kind_s, f"{r.start} → {r.end}", f"{100 * r.rule_ret:+.1f}", f"{100 * r.whole_ret:+.1f}", colored(100 * r.gap_log_rule_over_whole, 1),
                 "" if math.isnan(r.kept_share_mean) else f"{100 * r.kept_share_mean:.0f}", "" if math.isnan(r.sleeve_ret) else f"{100 * r.sleeve_ret:+.1f}",
                 sg(r.excess_large_pp), sg(r.excess_mid_pp), sg(r.excess_small_pp), sg(r.other_pp)] for r in d.itertuples()]
        det.append(f"<details><summary><b>{b}</b>: every stretch, rule against whole-book switch</summary>"
                   + tbl(rows, ["#", "Kind", "Sessions", "Rule return %", "Whole-book return %", "Rule against whole-book (log pts)", "Kept % of book", "Sleeve %", "Large vs sleeve (pp)", "Mid", "Small and below", "Other (pp)"], "ep")
                   + "</details>")
    n_fs = len(fs)
    fs_rule = {b: 100 * lg.loc[fs, b].sum() for b in BOOKS}
    sk_rule = {b: 100 * lg.loc[sk, b].sum() for b in BOOKS}
    tot_pp = {b: 100 * tot[b] for b in BOOKS}
    s15 = df[(df.stretch == big) & (df.book == "SCMO_0003")].iloc[0]
    fsb = df[df.stretch.isin(fs)]
    fs_band = {nm: float(np.mean([fsb[fsb.book == b][col].sum() for b in BOOKS])) for nm, col in (("Large", "excess_large_pp"), ("Mid", "excess_mid_pp"), ("Small and below", "excess_small_pp"))}
    noshake = {b: 100 * (tot[b] - lg.loc[list(sk), b].sum()) for b in BOOKS}
    no_big = {b: 100 * (tot[b] - lg.loc[[big], b].sum()) for b in BOOKS}
    nofs = {b: 100 * (tot[b] - lg.loc[list(fs), b].sum()) for b in BOOKS}
    flips = [b for b in BOOKS if no_big[b] > 0]
    nofs_ahead = all(v > 0 for v in nofs.values())
    recon = max(summ["books"][b]["recon_max_rel_err"] for b in BOOKS)
    fig1 = fig_gap(cv, st0)
    fig2 = fig_bars(piv)
    leg = "".join(f'<span style="display:inline-flex;align-items:center;gap:5px;margin-right:14px"><i style="width:14px;height:3px;background:{BCOL[b]};display:inline-block"></i>{b}</span>' for b in BOOKS)
    kleg = "".join(f'<span style="display:inline-flex;align-items:center;gap:5px;margin-right:14px"><i style="width:12px;height:12px;background:{c};opacity:.35;display:inline-block"></i>{k}</span>' for k, c in KCOL.items())
    first = summ["books"][BOOKS[0]]["start"]
    last = summ["books"][BOOKS[0]]["end"]
    out = f"""
<h2 id="whywhole">Why the whole-book switch beats the segment rule, and when</h2>
<p class="cap">Post hoc and descriptive: it is not part of the pre-registered test and changes no verdict. Window {first} → {last}, 20.8 bps, the same runs as everything above. The whole-book switch holds the parent only while Nifty 100, Midcap 100 and Smallcap 100 are all BUY, and sits in the 50/50 gold and cash sleeve otherwise. The segment rule keeps each stock whose own index is BUY.</p>
<p><b>The two rules hold the same weights whenever the three signals agree</b> (all BUY: both fully invested; all SELL: both in the sleeve). So the gap between them can only open in the {nst} disagreement stretches, and it does: the stretches carry all of it, and what happens outside them is {100 * min(outside.values()):+.1f} to {100 * max(outside.values()):+.1f} log points in the four books against a total of {min(tot_pp.values()):+.0f} to {max(tot_pp.values()):+.0f}. Every figure in this section is in log points: 100 x ln(rule value / whole-book switch value). Positive = the rule is ahead (blue), negative = the whole-book switch is ahead (red).</p>
<h3>The rule against the whole-book switch, through time</h3>
<div class="card"><div class="legend">{leg}<br>{kleg}</div>{fig1}</div>
<p class="cap">100 x the natural log of the rule's value divided by the whole-book switch's value, for each book, from {first} (both start at 1). Above zero the rule is ahead, below zero the whole-book switch is. The shaded bands are the {nst} disagreement stretches (numbered), coloured by kind and drawn on SCMO_0003's sessions; the other books' stretches differ by a session or two. Almost every move of the curve happens inside a band.</p>
<h3>What the stretches were</h3>
{tbl(kind_rows, ["Kind of stretch", "Stretches", "Whole-book switch ahead in", "SCMO_0003", "SCMO_0007", "SCMO_0010", "SCMO_0029"], "ep")}
<p class="cap">Entries are 100 x ln(rule value / whole-book value) summed over the stretches of each kind; they add up exactly across stretches. Positive = the rule gained on the whole-book switch, negative = the whole-book switch gained on the rule. A stretch's kind is read from the signals just before it and just after it.</p>
<h3>The reading</h3>
<ul>
<li><b>The whole-book switch wins mainly on false starts.</b> In {n_fs} stretches ({", ".join(str(int(i)) for i in fs)}) one or two indices turned BUY, the third never joined, and the market fell back to all SELL. The rule had bought the stocks of the BUY indices; the whole-book switch waited in the sleeve. That costs the rule {-max(fs_rule.values()):.0f} to {-min(fs_rule.values()):.0f} log points in the four books (shown as {min(fs_rule.values()):+.0f} to {max(fs_rule.values()):+.0f} above), more than its total deficit of {-max(tot_pp.values()):.0f} to {-min(tot_pp.values()):.0f}.</li>
<li><b>The rule wins on shake-outs, but only twice.</b> In stretches {", ".join(str(int(i)) for i in sk)} all three signals were BUY, one index turned SELL, the whole-book switch left, the other two stayed BUY and the market kept rising. The rule's gain is {min(sk_rule.values()):+.0f} to {max(sk_rule.values()):+.0f} log points. Without those two stretches the rule's total would be {min(noshake.values()):+.0f} to {max(noshake.values()):+.0f} instead of {min(tot_pp.values()):+.0f} to {max(tot_pp.values()):+.0f} (table below).</li>
<li><b>What the rule loses in a false start is the gap between the stocks it buys and the sleeve it gives up.</b> Across the {n_fs} false starts the kept stocks earned, on average over the four books, {fs_band['Large']:+.1f} (Large), {fs_band['Mid']:+.1f} (Mid) and {fs_band['Small and below']:+.1f} (Small and below) percentage points of the book against the sleeve. The longest false start, stretch {big} ({s15['start']} → {s15['end']}, {int(s15['weeks'])} weeks), is the one where the sleeve itself returned {100 * s15['sleeve_ret']:+.0f}% (half of it GOLDBEES) while the rule's kept stocks lagged it.</li>
<li><b>This is {nst} stretches, not {nst * 4} observations.</b> The four books share the signals and differ only in which stocks they hold, so a stretch is one piece of evidence; "{int(ahead.sum())} of {4 * nst}" counts it four times.</li>
</ul>
<h3>Without the best stretches</h3>
{tbl(lo_rows, ["Rule against the whole-book switch, total in log points x 100 (negative = the whole-book switch is ahead)", "SCMO_0003", "SCMO_0007", "SCMO_0010", "SCMO_0029"], "ep")}
<p class="cap">Total less the named stretches. The deficit is the small sum of two large opposite sets, the false starts ({min(fs_rule.values()):+.0f} to {max(fs_rule.values()):+.0f}) and the shake-outs ({min(sk_rule.values()):+.0f} to {max(sk_rule.values()):+.0f}). {"Without the false starts the rule is ahead in every book" if nofs_ahead else "Without the false starts the rule is not ahead in every book"} ({min(nofs.values()):+.0f} to {max(nofs.values()):+.0f}); without the shake-outs the whole-book switch is far ahead ({min(noshake.values()):+.0f} to {max(noshake.values()):+.0f}). {"Without stretch " + str(big) + " alone the rule is ahead in " + ", ".join(flips) + "." if flips else "Without stretch " + str(big) + " alone the whole-book switch is still ahead in all four books."} The sign of the result therefore rests on a handful of stretches.</p>
<h3>Every stretch</h3>
<div class="card"><div class="legend">{leg}</div>{fig2}</div>
<p class="cap">100 x ln(rule value / whole-book value) over each stretch's sessions (negative = the whole-book switch won). x axis: stretch number. The plain returns of both rules are in the per-book tables at the bottom.</p>
{stretch_tab}
<p class="cap">"Kept stocks against the sleeve" = for every stock the rule holds, its daily return minus the rule's own sleeve return, times its value the day before, summed over the stretch and divided by the rule's value at its start (percentage points of the book). This is a different quantity from the log points above: it is in percentage points of the book, and "Other (pp)" in the per-book tables is the rule's return minus the whole-book switch's return minus the kept-stocks figure (trading costs, fills against closes, the whole-book switch's own sleeve). The positions reproduce the rule's value to {recon:.0e} (relative), so the attribution rests on the exact holdings; before the first logged trade ({summ['books'][BOOKS[0]]['first_logged_position']}) the book holds only the sleeve.</p>
<h3>Where the rule's kept stocks gained or lost against the sleeve</h3>
{band_tab}
<p class="cap">Summed over the stretches of each kind, percentage points of the book's starting value (not additive across stretches in strict terms, indicative). Negative = those kept stocks earned less than the sleeve would have.</p>
{"".join(det)}
"""
    return out
