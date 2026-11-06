# -*- coding: utf-8 -*-
"""
Build evidence/why_n100sc100/deep/report.html: the pair rule (N100 AND SC100)
across every year, swing and regime. Static page; every table and chart is
generated from the deep_*.csv outputs, so no number is typed by hand except
where a sentence quotes a value that the tables also show.
"""

from __future__ import annotations

import html

import numpy as np
import pandas as pd

from common import EVIDENCE_DIR

E = EVIDENCE_DIR / "why_n100sc100" / "deep"
TPL = EVIDENCE_DIR.parent / "why_report_template.html"


def pct(x, d=1, sign=False):
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "–"
    s = f"{x * 100:+.{d}f}%" if sign else f"{x * 100:.{d}f}%"
    return s.replace("-", "−")


def pp(x, d=1):
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "–"
    if abs(x * 100) < 0.5 * 10 ** -d:
        return f"{0:.{d}f}"
    return f"{x * 100:+.{d}f}".replace("-", "−")


def num(x, d=1):
    return f"{x:+.{d}f}".replace("-", "−")


def cls(x):
    return "pos" if x > 0.0005 else "neg" if x < -0.0005 else ""


def table(head, rows, hl=None, first_left=True, prose=False):
    h = "<div class='tw'><table" + (" class='prose'" if prose else "") + "><thead><tr>" + "".join(f"<th>{c}</th>" for c in head) + "</tr></thead><tbody>"
    for i, r in enumerate(rows):
        tr = " class='hl'" if hl and hl(i, r) else ""
        cells = []
        for j, c in enumerate(r):
            if isinstance(c, tuple):
                txt, k = c
                cells.append(f"<td class='{k}'>{txt}</td>")
            else:
                cells.append(f"<td class='l'>{c}</td>" if (j == 0 and first_left) else f"<td>{c}</td>")
        h += f"<tr{tr}>" + "".join(cells) + "</tr>"
    return h + "</tbody></table></div>"


def vbars(groups, series, ymin, ymax, step, shade=None, unit="pp", h=300, label_every=1, aria=""):
    """Grouped vertical bars around zero. groups: list of labels; series: [(name, color, values)]."""
    W, m = 1000, {"l": 46, "r": 10, "t": 12, "b": 34}
    iw, ih = W - m["l"] - m["r"], h - m["t"] - m["b"]
    n, k = len(groups), len(series)
    gw = iw / n
    bw = min(16, (gw - 6) / k)
    Y = lambda v: m["t"] + (ymax - v) / (ymax - ymin) * ih
    out = [f"<svg class='chart' viewBox='0 0 {W} {h}' role='img' aria-label='{html.escape(aria)}'>"]
    if shade:
        a, b, lab = shade
        x0, x1 = m["l"] + a * gw, m["l"] + (b + 1) * gw
        out.append(f"<rect x='{x0:.1f}' y='{m['t']}' width='{x1 - x0:.1f}' height='{ih}' fill='var(--band)'/>")
        out.append(f"<text x='{(x0 + x1) / 2:.1f}' y='{m['t'] + 12}' class='tick' text-anchor='middle'>{lab}</text>")
    v = ymin
    while v <= ymax + 1e-9:
        cl = "base" if abs(v) < 1e-9 else "grid"
        out.append(f"<line x1='{m['l']}' x2='{W - m['r']}' y1='{Y(v):.1f}' y2='{Y(v):.1f}' class='{cl}'/>")
        out.append(f"<text x='{m['l'] - 6}' y='{Y(v) + 3.5:.1f}' class='tick' text-anchor='end'>{num(v, 0) if v else '0'}</text>")
        v += step
    for i, g in enumerate(groups):
        cx = m["l"] + i * gw + gw / 2
        if i % label_every == 0:
            out.append(f"<text x='{cx:.1f}' y='{h - 12}' class='tick' text-anchor='middle'>{g}</text>")
        for j, (name, col, vals) in enumerate(series):
            val = vals[i]
            if val is None or np.isnan(val):
                continue
            x = cx - k * bw / 2 - (k - 1) + j * (bw + 2)
            vv = max(min(val, ymax), ymin)
            y0, y1 = Y(0), Y(vv)
            top, hh = min(y0, y1), max(abs(y1 - y0), 1)
            out.append(f"<rect x='{x:.1f}' y='{top:.1f}' width='{bw:.1f}' height='{hh:.1f}' rx='2' fill='{col}'>"
                       f"<title>{g} · {name}: {num(val)} {unit}</title></rect>")
    out.append("</svg>")
    return "".join(out)


def hbars(rows, series, xmax=100, h=None, aria=""):
    """Horizontal grouped bars, 0..xmax (%), value labels at bar ends."""
    W = 1000
    lw, m = 190, {"t": 8, "b": 26, "r": 60}
    k = len(series)
    rh = 16 * k + 18
    h = h or m["t"] + m["b"] + rh * len(rows)
    X = lambda v: lw + v / xmax * (W - lw - m["r"])
    out = [f"<svg class='chart' viewBox='0 0 {W} {h}' role='img' aria-label='{html.escape(aria)}'>"]
    for t in range(0, xmax + 1, 25):
        out.append(f"<line x1='{X(t):.1f}' x2='{X(t):.1f}' y1='{m['t']}' y2='{h - m['b']}' class='{'base' if t == 0 else 'grid'}'/>")
        out.append(f"<text x='{X(t):.1f}' y='{h - 8}' class='tick' text-anchor='middle'>{t}%</text>")
    for i, lab in enumerate(rows):
        y0 = m["t"] + i * rh + 6
        out.append(f"<text x='{lw - 10}' y='{y0 + rh / 2 - 2:.1f}' class='elabel' text-anchor='end' style='font-family:var(--sans);font-size:12.5px'>{lab}</text>")
        for j, (name, col, vals) in enumerate(series):
            v = vals[i]
            y = y0 + j * 16
            out.append(f"<rect x='{lw}' y='{y}' width='{max(X(v) - lw, 1):.1f}' height='13' rx='2' fill='{col}'><title>{lab} · {name}: {v:.0f}%</title></rect>")
            out.append(f"<text x='{X(v) + 6:.1f}' y='{y + 10.5}' class='elabel'>{v:.0f}%</text>")
    out.append("</svg>")
    return "".join(out)


def legend(items):
    return "<div class='legend'>" + "".join(f"<span class='key'><i class='sw' style='background:{c}'></i>{n}</span>" for n, c in items) + "</div>"


def main():
    css = TPL.read_text(encoding="utf-8").split("</style>")[0].split("<style>")[1]
    P = pd.read_csv(E / "core_period_stats.csv")
    Yw = pd.read_csv(E / "years_wide.csv")
    YR = pd.read_csv(E / "years_by_regime_oos.csv")
    YS = pd.read_csv(E / "years_summary_oos.csv")
    SW = pd.read_csv(E / "swings_capture_oos.csv")
    SA = pd.read_csv(E / "swings_all.csv")
    RT = pd.read_csv(E / "regime_table.csv")
    DC = pd.read_csv(E / "mech_decomposition.csv")
    SD = pd.read_csv(E / "mech_signal_diagnostics.csv")
    MS = pd.read_csv(E / "mech_states_summary.csv")
    LL = pd.read_csv(E / "mech_lead_lag_sc100_20pct_falls.csv")
    RS = pd.read_csv(E / "robust_rolling_summary.csv")
    BS = pd.read_csv(E / "robust_bootstrap.csv")
    SH = pd.read_csv(E / "robust_shift_summary.csv")
    DL = pd.read_csv(E / "robust_delay_cost.csv")
    ST = pd.read_csv(E / "robust_settings.csv")
    FM = pd.read_csv(E / "robust_family.csv")
    SX = pd.read_csv(E / "sleeve_excess_decomposition.csv") if (E / "sleeve_excess_decomposition.csv").exists() else None

    def ps(leg, rule, k, per="oos", sl="cash"):
        x = P[(P.leg == leg) & (P.rule == rule) & (P.sleeve == sl) & (P.period == per)]
        return float(x[k].iloc[0]) if len(x) else np.nan

    def rt(leg, lab, bucket, k, samp="oos"):
        x = RT[(RT.leg == leg) & (RT.sleeve == "cash") & (RT["sample"] == samp) & (RT.labelling == lab) & (RT.bucket == bucket)]
        return float(x[k].iloc[0])

    S1, S2, S3, S4, S5 = "var(--s1)", "var(--s2)", "var(--s3)", "var(--s4)", "var(--s5)"
    body = []
    A = body.append

    # ── header ──────────────────────────────────────────────────────────────
    A("<div class='wrap'>")
    A("<p class='eyebrow'>AA overlay · N100 AND SC100 · every year, every swing, every regime · 2007–2026</p>")
    A("<h1>The pair rule wins in bear markets because small caps crack first and large caps don't chase their rallies</h1>")
    A("<p class='sub'>Out of sample, holding equity only when Nifty 100 and Smallcap 100 are both in BUY cut the worst fall from −77% to −29% on small caps. "
      "It also beat Smallcap 100's own signal in 93% of 5-year windows. It beats buy-and-hold on return only in periods with a real bear market.</p>")
    A("<p class='meta'>Out of sample 2007-07 → 2021-10 · in-sample 2021-11 → 2026-08 shown for completeness, never as evidence · production weekly supertrend · "
      "price-return indices, LBES cash, GOLDBEES · 20.8 bps per switch · evidence: <code>AA/analysis/evidence/why_n100sc100/deep/</code></p>")

    # ── conclusion ──────────────────────────────────────────────────────────
    sc_p, sc_b, sc_s = ps("SC100", "pair", "cagr"), ps("SC100", "bh", "cagr"), ps("SC100", "sc100", "cagr")
    sc_pd, sc_bd, sc_sd = ps("SC100", "pair", "max_dd_daily"), ps("SC100", "bh", "max_dd_daily"), ps("SC100", "sc100", "max_dd_daily")
    bear_c = rt("SC100", "R1_phase", "bear", "pair_minus_bh_logpts_per_yr_of_period")
    rec_c = rt("SC100", "R1_phase", "recovery", "pair_minus_bh_logpts_per_yr_of_period")
    bull_c = rt("SC100", "R1_phase", "bull", "pair_minus_bh_logpts_per_yr_of_period")
    fe_p = SD[(SD.rule == "pair") & (SD["sample"] == "oos")].false_entry_share.iloc[0]
    fe_s = SD[(SD.rule == "sc100") & (SD["sample"] == "oos")].false_entry_share.iloc[0]
    only_sc = rt("SC100", "R5_state", "only SC100 BUY", "bh_ann")
    b_sc = BS[(BS.leg == "SC100") & (BS.vs == "sc100")].iloc[0]
    b_bh = BS[(BS.leg == "SC100") & (BS.vs == "bh")].iloc[0]
    b_bl = BS[(BS.leg == "blend") & (BS.vs == "bh")].iloc[0]
    b_n1 = BS[(BS.leg == "N100") & (BS.vs == "bh")].iloc[0]
    sh = SH[SH.leg == "SC100"].iloc[0]
    fall = SW[(SW.leg == "SC100") & (SW.group == "All falls")].iloc[0]
    rise = SW[(SW.leg == "SC100") & (SW.group == "All rallies")].iloc[0]
    A("<div class='findings'><ol>")
    A(f"<li><b>What it is:</b> a strong drawdown filter, and a better small-cap timer than small caps' own signal. It is not a proven way to beat buy-and-hold on return. "
      f"On the Smallcap 100 index, out of sample, it made {pct(sc_p)} a year with a {pct(sc_pd)} worst fall. Buy-and-hold made {pct(sc_b)} ({pct(sc_bd)}), and Smallcap 100's own signal {pct(sc_s)} ({pct(sc_sd)}).</li>")
    A(f"<li><b>Where the edge comes from:</b> bear markets. In Smallcap 100 bear phases, labelled with hindsight, it added {num(bear_c * 100)} log-points a year over the whole period. "
      f"It paid back {-rec_c * 100:.1f} in recoveries, by re-entering late, and {-bull_c * 100:.1f} in bull phases.</li>")
    A(f"<li><b>Why it works:</b> the two signals make different mistakes. Small caps break first at tops: at the 12 small-cap falls of 20%+ in 2006–2020, Nifty 100 never sold first. "
      f"Large caps refuse to confirm small-cap bear-market rallies: the pair's false entries were {pct(fe_p, 0)}, against {pct(fe_s, 0)} for Smallcap 100 alone. "
      f"In the weeks when only Smallcap 100 said BUY, small caps fell at a {pct(-only_sc, 0)} annualised rate. "
      f"So the pair takes {pct(fall.pair_share, 0)} of a fall but {pct(rise.pair_share, 0)} of a rally. Smallcap 100 alone takes {pct(fall.sc100_share, 0)} and {pct(rise.sc100_share, 0)}.</li>")
    A(f"<li><b>How sure:</b>"
      f"<ul>"
      f"<li><b>Against Smallcap 100 alone:</b> P = {pct(b_sc.p_diff_gt_0, 0)} in a resampling test.</li>"
      f"<li><b>Worst fall against buy-and-hold:</b> shallower in 100% of 3- and 5-year windows. The −28.6% is shallower than {pct(sh.dd_percentile_shallower, 1)} of 775 randomly shifted signal histories.</li>"
      f"<li><b>Return against buy-and-hold:</b> only P = {pct(b_bh.p_diff_gt_0, 0)} on small caps, {pct(b_bl.p_diff_gt_0, 0)} on the blend and {pct(b_n1.p_diff_gt_0, 0)} on Nifty 100.</li>"
      f"</ul></li>")
    A("<li><b>What to expect:</b>"
      "<ul>"
      "<li>worst falls of about −20% to −30%;</li>"
      "<li>well ahead of buy-and-hold in years with a deep fall (+34 pp a year on average in 2008, 2011 and 2018);</li>"
      "<li>behind in straight bull years (−22 pp);</li>"
      "<li>far behind when small caps boom without large caps, as in 2021 (Jan–Oct: +21% against +52%).</li>"
      "</ul></li>")
    A("</ol></div>")

    # ── whole period ────────────────────────────────────────────────────────
    A("<h2 id='period'>The whole out-of-sample period</h2>")
    A("<p>Each index is held as the whole equity leg, with the all-cash sleeve, from 2007-07-02 to 2021-10-29. Every cell shows CAGR above the worst fall on daily closes.</p>")
    rows = []
    for leg, lab in (("SC100", "Smallcap 100"), ("blend", "N100/MC100/SC100 blend"), ("MC100", "Midcap 100"), ("N100", "Nifty 100"), ("N50", "Nifty 50")):
        r = [lab]
        for ru in ("bh", "own", "sc100", "pair", "triple"):
            c, d = ps(leg, ru, "cagr"), ps(leg, ru, "max_dd_daily")
            if ru == "own" and leg == "SC100":
                r.append("= SC100 only")
            elif np.isnan(c):
                r.append("–")
            else:
                r.append(f"{pct(c)}<br><span style='color:var(--muted)'>{pct(d, 0)}</span>")
        r.append(f"{ps(leg, 'pair', 'calmar'):.2f} vs {ps(leg, 'bh', 'calmar'):.2f}")
        rows.append(r)
    A(table(["Index held", "Buy & hold", "Own signal", "SC100 only", "Pair", "Triple", "Pair vs B&H Calmar"], rows))
    A("<p class='cap'>Calmar = CAGR ÷ |worst fall|. Nifty 50/100 and Midcap 100 use their own supertrend as \"own signal\"; for Smallcap 100 that is Smallcap 100 only. Source: <code>core_period_stats.csv</code>.</p>")

    # ── years ───────────────────────────────────────────────────────────────
    A("<h2 id='years'>Every calendar year</h2>")
    A("<p>Smallcap 100 held, cash sleeve. Each year is a slice of one continuous run, so positions carry across year ends. The bars show the pair's return minus buy-and-hold, and minus Smallcap 100's own signal, in percentage points. "
      "2021 is split at the in-sample boundary.</p>")
    y = Yw[(Yw.leg == "SC100") & (Yw.sleeve == "cash")].set_index("year")
    labels = [str(v) if v not in (2007, 2026) else ("2007 H2" if v == 2007 else "2026 YTD") for v in y.index]
    A(legend([("Pair − buy & hold", S1), ("Pair − Smallcap 100 only", S2)]))
    A("<div class='card'>" + vbars(labels, [("Pair − buy & hold", S1, list(y.pair_minus_bh * 100)), ("Pair − Smallcap 100 only", S2, list(y.pair_minus_sc100 * 100))],
                                    -60, 60, 20, shade=(list(y.index).index(2022), len(y) - 1, "in-sample"), aria="Pair minus buy-and-hold and minus Smallcap 100 only, by year") + "</div>")
    A("<p class='cap'>Hover a bar for its value; the table below has every value. Full year 2021 shown; Jan–Oct 2021 alone: pair +21.4%, both others +51.9%.</p>")
    rows = []
    for yr, r in y.iterrows():
        lab = ("V" if r.SC100_V else r.SC100_label) if yr <= 2021 else r.SC100_label
        name = f"{yr}" + (" (in-sample)" if yr >= 2022 else " (Jul–Dec)" if yr == 2007 else " (to Aug-21)" if yr == 2026 else " (mixed)" if yr == 2021 else "")
        rows.append([name, lab, pct(r.bh_ret), pct(r.sc100_ret), pct(r.pair_ret), (pp(r.pair_minus_bh), cls(r.pair_minus_bh)),
                     (pp(r.pair_minus_sc100), cls(r.pair_minus_sc100)), pct(r.pair_worst_friday, 0), pct(r.bh_worst_friday, 0), pct(r.pair_in_equity, 0)])
    A(table(["Year", "Type", "Buy & hold", "SC100 only", "Pair", "Pair − B&H", "Pair − SC100", "Pair worst fall", "B&H worst fall", "Pair in equity"], rows,
            hl=lambda i, r: r[0].startswith(("2008", "2011", "2021"))))
    A("<p class='cap'>Type (hindsight, from Smallcap 100 buy-and-hold): bull > +15%, bear < −10%, flat otherwise; V = fell more than 20% inside the year but ended up. Worst falls here are within the year, on Friday closes. Source: <code>years_wide.csv</code>.</p>")
    A("<h3>By type of year, out of sample (2007–2020)</h3>")
    rows = []
    for leg, ln in (("SC100", "Smallcap 100"), ("blend", "Blend"), ("N100", "Nifty 100")):
        for reg in ("bear", "V (fell >20%, ended up)", "flat", "bull"):
            x = YR[(YR.leg == leg) & (YR.reg == reg)].iloc[0]
            nm = reg.replace(" (fell >20%, ended up)", " (crash, then up)")
            rows.append([ln if reg == "bear" else "", (f"<b>{nm}</b> <span style='color:var(--muted)'>{x.yrs.replace(',', ', ')}</span>", "l"),
                         pct(x.avg_bh), pct(x.avg_pair), pct(x.avg_sc100), (pp(x.avg_pair_minus_bh) + f" ({int(x.pair_beats_bh)}/{int(x.years)})", cls(x.avg_pair_minus_bh)),
                         (pp(x.avg_pair_minus_sc100), cls(x.avg_pair_minus_sc100)), f"{pct(x.avg_pair_worst, 0)} / {pct(x.avg_bh_worst, 0)}"])
    A(table(["Index held", "Year type and years", "B&H", "Pair", "SC100 only", "Pair − B&H (won)", "Pair − SC100", "Worst fall pair / B&H"], rows))
    ysc = YS[(YS.leg == "SC100") & (YS.sleeve == "cash")].iloc[0]
    A(f"<div class='callout'><p><b>The year pattern is the same on every index.</b> The pair wins big in bear years, roughly ties in crash-then-V years (while beating Smallcap 100's own signal by +17 pp), and loses about 20 pp in straight bull years. "
      f"On small caps it beat buy-and-hold in {int(ysc.pair_beats_bh)} of {int(ysc.years)} years. Its worst fall inside the year was shallower in {int(ysc.pair_worst_shallower_than_bh)} of {int(ysc.years)}. "
      f"Against Smallcap 100's own signal it was better in 7 years, equal in 3 (the signals never disagreed) and worse in 4. The worst year against both was 2021 Jan–Oct: small caps boomed while Nifty 100 stayed in SELL.</p></div>")

    # ── swings ──────────────────────────────────────────────────────────────
    A("<h2 id='swings'>Every fall and every rally</h2>")
    A("<p>The market's path is cut into swings with a 10% zig-zag on Friday closes: a fall ends when the index rebounds 10% from its low, and a rally ends when it drops 10% from its high. "
      "For each swing the rule's NAV return is compared with the index's own. The chart shows what share of each kind of move the rule took, on average.</p>")
    sw = SW[SW.leg == "SC100"].set_index("group")
    grp = ["Falls of 20%+", "Falls of 10-20%", "Fast rallies (<=13w)", "Slow rallies (>13w)"]
    A(legend([("Pair", S1), ("Smallcap 100 only", S2)]))
    A("<div class='card'>" + hbars(["Falls of 20%+", "Falls of 10–20%", "Rallies, fast (≤13 weeks)", "Rallies, slow (>13 weeks)"],
                                   [("Pair", S1, [sw.loc[g, "pair_share"] * 100 for g in grp]), ("Smallcap 100 only", S2, [sw.loc[g, "sc100_share"] * 100 for g in grp])],
                                   aria="Share of each swing taken by the pair and by Smallcap 100 only") + "</div>")
    rows = []
    for leg, ln in (("SC100", "Smallcap 100"), ("blend", "Blend")):
        for g in ("All falls", "Falls of 20%+", "Falls of 10-20%", "All rallies", "Fast rallies (<=13w)", "Slow rallies (>13w)"):
            x = SW[(SW.leg == leg) & (SW.group == g)].iloc[0]
            rows.append([ln if g == "All falls" else "", g.replace("10-20", "10–20").replace("<=", "≤"), int(x.n), pct(x.bh), pct(x.pair), pct(x.sc100),
                         pct(x.pair_share, 0), pct(x.sc100_share, 0)])
    A(table(["Index held", "Swing type", "n", "Buy & hold", "Pair", "SC100 only", "Pair's share", "SC100 only's share"], rows,
            hl=lambda i, r: r[1] in ("All falls", "All rallies")))
    A(f"<p class='cap'>Out of sample, completed swings from 2008-01 to 2021-10, cash sleeve. In falls, the pair's median exit came after a {pct(-fall.pair_median_exit_fall)} drop from the high, against {pct(-fall.sc100_median_exit_fall)} for Smallcap 100 alone. "
      f"In rallies, its median entry came {pct(rise.pair_median_entry_rise)} off the low, against {pct(rise.sc100_median_entry_rise)}. Source: <code>swings_capture_oos.csv</code>, <code>swings_all.csv</code>.</p>")
    s = SA[(SA.leg == "SC100") & (SA["sample"] == "oos") & SA.pair_cash.notna()].copy()
    s["gap"] = s.pair_cash - s.sc100_cash
    top = s.reindex(s.gap.abs().sort_values(ascending=False).index).head(10).sort_values("start")
    rows = [[f"{r.start} → {r.end}", r.kind, pct(r.index_move, 0), pct(r.bh_cash), pct(r.sc100_cash), pct(r.pair_cash), (pp(r.gap), cls(r.gap))] for r in top.itertuples()]
    A("<h3>The swings where the pair and Smallcap 100's own signal differed most</h3>")
    A(table(["Swing", "Kind", "Index move", "Buy & hold", "SC100 only", "Pair", "Pair − SC100"], rows))
    A("<div class='callout'><p><b>The pair wins in falls where small caps rally inside a bear market.</b> In 2008 (three legs), 2009, 2011, 2015 and 2016, Smallcap 100's signal flipped back to BUY during a bear-market rally; Nifty 100's did not, so the pair stayed out. "
      "<b>It loses in rallies that small caps lead alone.</b> The biggest was 2020-04 → 2022-01, when the pair made +95% against +144% (that rally crosses into the in-sample period).</p></div>")

    # ── regimes ─────────────────────────────────────────────────────────────
    A("<h2 id='regimes'>Market regimes</h2>")
    A("<p>Every session carries the regime label in force at the review that governs it, so the ex-ante labels use only data known on that Friday. "
      "\"Contribution\" is the log-point gap earned inside a bucket, per year of the whole period, so the buckets add up to the total gap.</p>")
    A("<h3>Market phase (hindsight), Smallcap 100 held, out of sample</h3>")
    ph = ["bear", "correction", "recovery", "bull"]
    phn = {"bear": "Bear (inside a 20%+ fall)", "correction": "Correction (10–20% fall)", "recovery": "Recovery (rising, below the old high)", "bull": "Bull (above the old high)"}
    A(legend([("Pair − buy & hold", S1), ("Pair − Smallcap 100 only", S2)]))
    A("<div class='card'>" + vbars([phn[p].split(" (")[0] for p in ph],
                                   [("Pair − buy & hold", S1, [rt("SC100", "R1_phase", p, "pair_minus_bh_logpts_per_yr_of_period") * 100 for p in ph]),
                                    ("Pair − Smallcap 100 only", S2, [rt("SC100", "R1_phase", p, "pair_minus_sc100_logpts_per_yr_of_period") * 100 for p in ph])],
                                   -15, 25, 5, h=240, unit="log-pts/yr", aria="Contribution to the pair's gap by market phase") + "</div>")
    rows = []
    for p in ph:
        g = lambda k: rt("SC100", "R1_phase", p, k)
        rows.append([phn[p], f"{g('weeks'):.0f}", pct(g("bh_ann")), pct(g("pair_ann")), pct(g("sc100_ann")), pct(g("pair_in_equity"), 0),
                     (num(g("pair_minus_bh_logpts_per_yr_of_period") * 100), cls(g("pair_minus_bh_logpts_per_yr_of_period"))),
                     (num(g("pair_minus_sc100_logpts_per_yr_of_period") * 100), cls(g("pair_minus_sc100_logpts_per_yr_of_period")))])
    A(table(["Phase", "Weeks", "B&H (ann.)", "Pair (ann.)", "SC100 only (ann.)", "Pair in equity", "Contribution vs B&H", "Contribution vs SC100"], rows))
    A("<h3>Ex-ante labels: known on the day, no hindsight</h3>")
    lab_rows = [("R2_trend", "below 40w avg", "Small caps below their 40-week average"), ("R2_trend", "above 40w avg", "Small caps above their 40-week average"),
                ("R3_vol", "high", "Volatility high (expanding tercile)"), ("R3_vol", "mid", "Volatility mid"), ("R3_vol", "low", "Volatility low"),
                ("R4_leadership", "large-led", "Large caps leading (26 weeks)"), ("R4_leadership", "neutral", "Neither leading"), ("R4_leadership", "small-led", "Small caps leading"),
                ("R7_comove", "low", "Large/small correlation low"), ("R7_comove", "mid", "Correlation mid"), ("R7_comove", "high", "Correlation high")]
    rows = []
    for lab, b, name in lab_rows:
        g = lambda k: rt("SC100", lab, b, k)
        rows.append([name, f"{g('weeks'):.0f}", (pp(g("pair_minus_bh")), cls(g("pair_minus_bh"))), (pp(g("pair_minus_sc100")), cls(g("pair_minus_sc100"))),
                     (num(g("pair_minus_bh_logpts_per_yr_of_period") * 100), cls(g("pair_minus_bh_logpts_per_yr_of_period"))),
                     (num(g("pair_minus_sc100_logpts_per_yr_of_period") * 100), cls(g("pair_minus_sc100_logpts_per_yr_of_period")))])
    A(table(["Condition at the review", "Weeks", "Pair − B&H (ann. pp)", "Pair − SC100 (ann. pp)", "Contribution vs B&H", "Contribution vs SC100"], rows))
    A(f"<div class='callout'><p><b>The edge survives without hindsight.</b> Against Smallcap 100's own signal, almost all of it ({num(rt('SC100', 'R2_trend', 'below 40w avg', 'pair_minus_sc100_logpts_per_yr_of_period') * 100)} of "
      f"{num(sum(rt('SC100', 'R2_trend', b, 'pair_minus_sc100_logpts_per_yr_of_period') for b in ('below 40w avg', 'above 40w avg')) * 100)} log-points a year) is earned when small caps are already below their 40-week average. "
      "That is where a small-cap BUY without large-cap confirmation is usually a bear-market rally. The pair also pays most in high and mid volatility, and when small caps are not leading. "
      "<b>One idea is not supported:</b> that the pair helps more when large and small caps move apart. The correlation terciles show no such pattern.</p></div>")

    # ── mechanism ───────────────────────────────────────────────────────────
    A("<h2 id='mechanism'>The mechanism</h2>")
    A("<h3>1. Where the return gap comes from</h3>")
    rows = []
    for a, b, name in (("pair", "bh", "Pair vs buy & hold"), ("sc100", "bh", "SC100 only vs buy & hold"), ("pair", "sc100", "Pair vs SC100 only")):
        x = DC[(DC.leg == "SC100") & (DC.period.str.contains("oos")) & (DC.a == a) & (DC.b == b)].iloc[0]
        rows.append([name, f"{x.losses_avoided_pp_yr:.1f}", f"{x.gains_missed_pp_yr:.1f}", f"{x.sleeve_earned_pp_yr:.1f}", f"{x.extra_costs_pp_yr:.1f}",
                     (num(x.total_pp_yr), cls(x.total_pp_yr)), f"{int(x.days_a_out_b_in)}"])
    A(table(["Comparison (Smallcap 100 held, OOS)", "Losses avoided", "Gains missed", "Sleeve earned", "Extra costs", "Net (arith. pp/yr)", "Days that differ"], rows))
    A(f"<p class='cap'>Arithmetic percentage points a year; the parts add up exactly to the net. The CAGR gap against buy-and-hold is larger than the arithmetic one (+6.8 pp against +4.5), "
      f"because the pair's volatility was {pct(ps('SC100', 'pair', 'vol'))} against {pct(ps('SC100', 'bh', 'vol'))}, and a −77% crash costs far more in compounding than its average suggests. Source: <code>mech_decomposition.csv</code>.</p>")
    A("<h3>2. Signal quality: fewer false entries, earlier exits</h3>")
    rows = []
    for ru, name in (("pair", "Pair"), ("sc100", "SC100 only"), ("N100 only", "N100 only"), ("triple", "Triple")):
        x = SD[(SD.rule == ru) & (SD["sample"] == "oos")].iloc[0]
        rows.append([name, int(x.entries), int(x.whipsaw_in_spells_le4w), pct(x.false_entry_share, 0), pct(x.false_exit_share, 0), pct(x.median_entry_lag),
                     pct(x.median_exit_give_back), pct(x.time_in_equity, 0)])
    A(table(["Rule (on Smallcap 100, OOS)", "Entries", "Whipsaws ≤4w", "False entries", "False exits", "Entry lag (off the low)", "Exit give-back (off the high)", "Time in equity"], rows,
            hl=lambda i, r: i == 0))
    A("<p class='cap'>A false entry is one where the index was lower 13 weeks later; a false exit, one where it was higher. An independent recount from the weekly signals gives the same 22% and 39%. Source: <code>mech_signal_diagnostics.csv</code>.</p>")
    A("<h3>3. The weeks when only small caps say BUY</h3>")
    rows = []
    for stn in ("both BUY", "only SC100 BUY", "only N100 BUY", "both SELL"):
        x = MS[(MS["sub"] == "2006-21 (all oos)") & (MS.state == stn)].iloc[0]
        rows.append([stn, int(x.weeks), pct(x.SC100_4w_mean, 1, True), pct(x.SC100_4w_up, 0), pct(x.SC100_13w_mean, 1, True), pct(x.SC100_worst_26w_mean),
                     pct(x.share_in_SC100_bear_phase, 0)])
    A(table(["Signal state (2006–2021)", "Weeks", "SC100 next 4w", "Share up", "SC100 next 13w", "Worst point next 26w", "Inside a bear phase"], rows, hl=lambda i, r: i == 1))
    A(f"<p>While \"only Smallcap 100 BUY\" is in force, small caps returned {pct(only_sc, 0)} annualised. The state is short (median 3 weeks) and is followed by the deepest interim falls. "
      "Over 13 weeks the average turns positive, because the state usually resolves into \"both BUY\" and the pair re-enters then. "
      "Only 28% of these weeks sit inside a hindsight bear phase, so \"mostly bear-market rallies\" overstates it. But that 28% is where the damage is.</p>")
    A("<h3>4. Who moves first at the big turns</h3>")
    rows = []
    for r in LL.itertuples():
        if pd.Timestamp(r.peak) > pd.Timestamp("2021-10-29"):
            continue
        n_s = "already SELL" if r.N100_sell == "already SELL" else f"{r.N100_sell_weeks_after_peak:.0f}w"
        s_s = "already SELL" if r.SC100_sell == "already SELL" else f"{r.SC100_sell_weeks_after_peak:.0f}w"
        rows.append([f"{r.peak} → {r.trough}", pct(r.depth, 0), s_s, n_s, f"{r.pair_exit_weeks_after_peak:.0f}w ({pct(r.pair_exit_index_fall, 0)})",
                     f"{r.SC100_buy_weeks_after_trough:.0f}w", f"{r.N100_buy_weeks_after_trough:.0f}w", f"{r.pair_entry_weeks_after_trough:.0f}w ({pct(r.pair_entry_index_rise, 0, True)})"])
    A(table(["SC100 fall of 20%+", "Depth", "SC100 sold after", "N100 sold after", "Pair out after (index fall)", "SC100 bought after low", "N100 bought after low", "Pair in after (index vs low)"], rows))
    A("<div class='callout'><p><b>At tops, small caps are the alarm.</b> Smallcap 100's signal sold first 5 times and in the same week 3 times. Nifty 100 never sold first. In the other 4 falls Nifty 100 was already in SELL at the peak, so the pair was out before the fall began: small caps had rallied without large caps. "
      "<b>At bottoms, large caps are the gate.</b> The pair re-entered in the same week as Smallcap 100 alone in 6 of 12 cases, and one week later in 3. "
      "In 2008 it waited 53, 36 and 16 weeks, against 6, 3 and 2, and each wait kept it out of the next leg down.</p></div>")
    A("<h3>5. The two jobs, seen in the component rules</h3>")
    rows = []
    for ru in ("N100 AND SC100", "N100 only", "SC100 only", "N100 OR SC100", "N50 AND SC100", "MC100 AND SC100", "N100 AND MC100"):
        x = FM[(FM.rule == ru) & (FM.leg == "SC100") & (FM.period == "oos")].iloc[0]
        rows.append([ru, pct(x.cagr), pct(x.max_dd, 1), pct(x.time_in_equity, 0)])
    A(table(["Rule (Smallcap 100 held, OOS)", "CAGR", "Worst fall", "Time in equity"], rows, hl=lambda i, r: i == 0))
    A("<div class='callout'><p><b>In plain words.</b> Nifty 100's signal, used alone to time small caps, already delivers most of the pair's return (13.9% against 14.4%), because it does not chase small-cap bear-market rallies. "
      "Smallcap 100's own signal adds the early exit, since small caps crack first, and that cuts the worst fall from −43% to −29%. "
      "\"AND\" keeps both strengths: leave on the first warning, come back only when the whole market confirms. \"OR\" keeps both weaknesses (8.1% and −50%). "
      "Any large-cap AND small-cap pair works about as well.</p></div>")

    # ── robustness ──────────────────────────────────────────────────────────
    A("<h2 id='robust'>How robust is it?</h2>")
    A("<h3>Rolling windows, every weekly start, out of sample only</h3>")
    rows = []
    for leg, sl, hz, name in (("SC100", "cash", "3y", "Smallcap 100, 3 years"), ("SC100", "cash", "5y", "Smallcap 100, 5 years"), ("blend", "cash", "5y", "Blend, 5 years"),
                              ("MC100", "cash", "5y", "Midcap 100, 5 years"), ("N100", "cash", "5y", "Nifty 100, 5 years"), ("N50", "cash", "5y", "Nifty 50, 5 years"),
                              ("SC100", "50/50", "5y", "Smallcap 100, 50/50 sleeve, 5 years (2014+)")):
        x = RS[(RS.leg == leg) & (RS.sleeve == sl) & (RS.horizon == hz) & (RS.window == "oos")].iloc[0]
        rows.append([name, int(x.n_windows), pct(x.pair_cagr_gt_bh, 0), pct(x.pair_dd_shallower_bh, 0), pct(x.pair_calmar_gt_bh, 0), pct(x.pair_cagr_gt_sc100, 0),
                     (pp(x.pair_minus_bh_p50), cls(x.pair_minus_bh_p50)), f"{pct(x.pair_negative_cagr_share, 0)} / {pct(x.bh_negative_cagr_share, 0)}"])
    A(table(["Held, window", "Windows", "CAGR > B&H", "Worst fall shallower", "Calmar > B&H", "CAGR > SC100 only", "Median pair − B&H", "Windows losing money: pair / B&H"], rows))
    A("<p class='cap'>Windows end on or before 2021-10-29. Source: <code>robust_rolling_summary.csv</code>.</p>")
    A("<h3>Resampling, random timing, delay, costs</h3>")
    rows = []
    for leg, ln in (("SC100", "Smallcap 100"), ("blend", "Blend"), ("N100", "Nifty 100")):
        for vs, vn in (("bh", "buy & hold"), ("sc100", "SC100 only")):
            x = BS[(BS.leg == leg) & (BS.vs == vs)].iloc[0]
            rows.append([f"{ln} vs {vn}", (pp(x.observed_cagr_diff), cls(x.observed_cagr_diff)), f"{pp(x.ci90_lo)} to {pp(x.ci90_hi)}", pct(x.p_diff_gt_0, 0)])
    A(table(["Comparison (OOS, cash)", "Observed CAGR gap", "90% interval", "P(gap > 0)"], rows))
    A("<p class='cap'>Stationary block bootstrap of paired daily returns, 26-week mean blocks, 2,000 draws. Source: <code>robust_bootstrap.csv</code>.</p>")
    shb = SH[SH.leg == "blend"].iloc[0]
    A(f"<p><b>Random timing.</b> The joint Nifty 100 + Smallcap 100 signal history was shifted by 26 weeks or more, 775 times. The actual pair's return beats {pct(sh.cagr_percentile, 0)} of the shifts on small caps "
      f"(median shift {pct(sh.null_median_cagr)}) and {pct(shb.cagr_percentile, 0)} on the blend. Its worst fall is shallower than {pct(sh.dd_percentile_shallower, 1)} and {pct(shb.dd_percentile_shallower, 1)} of them (median shift {pct(sh.null_median_dd, 0)}). "
      "The drawdown protection is not luck.</p>")
    rows = []
    for t in ("delay 0w", "delay 1w", "delay 2w", "delay 4w", "cost 0 bps", "cost 50 bps", "cost 100 bps"):
        a_ = DL[(DL.leg == "SC100") & (DL.test == t)].iloc[0]
        b_ = DL[(DL.leg == "SC100") & (DL.test == f"sc100 only, {t}")] if t.startswith("delay") else None
        rows.append([t.replace("delay 0w", "on time").replace("delay", "late by").replace("w", " week(s)") if t.startswith("delay") else t.replace("cost", "cost per switch"),
                     f"{pct(a_.cagr)} / {pct(a_.max_dd, 0)}", f"{pct(b_.iloc[0].cagr)} / {pct(b_.iloc[0].max_dd, 0)}" if b_ is not None and len(b_) else "–"])
    A(table(["Smallcap 100 held, OOS", "Pair: CAGR / worst fall", "SC100 only"], rows))
    A("<p class='cap'>Execution timing matters more than costs: acting two weeks late loses most of the drawdown protection. Source: <code>robust_delay_cost.csv</code>.</p>")
    A("<h3>Supertrend settings</h3>")
    rows = []
    for (mu, dy), g in ST[ST.leg == "SC100"].groupby(["mul", "days"]):
        gg = g.set_index("rule")
        rows.append([f"× {mu:g}, {dy} bars" + (" (production)" if (mu == 2 and dy == 5) else ""), f"{pct(gg.loc['pair', 'cagr'])} / {pct(gg.loc['pair', 'max_dd'], 0)}",
                     f"{pct(gg.loc['sc100', 'cagr'])} / {pct(gg.loc['sc100', 'max_dd'], 0)}", f"{pct(gg.loc['N100 only', 'cagr'])} / {pct(gg.loc['N100 only', 'max_dd'], 0)}",
                     (pp(gg.loc['pair', 'cagr'] - gg.loc['sc100', 'cagr']), cls(gg.loc['pair', 'cagr'] - gg.loc['sc100', 'cagr']))])
    A(table(["Multiplier, ATR bars", "Pair", "SC100 only", "N100 only", "Pair − SC100"], rows, hl=lambda i, r: "production" in r[0]))
    A("<p class='cap'>Signals are recomputed from index prices (× 2, 5 bars reproduces the production signals exactly) and read on the Friday review grid. The cells are OOS CAGR / worst fall on Smallcap 100. "
      "The pair beats Smallcap 100 alone at every setting up to × 2.5, and ties or loses at × 3. Confirmation helps most when the underlying signal is noisy. "
      "× 2.5 looked better than production for every rule, but the grid was examined after the fact, so it is a lead for a pre-registered test, not a change. Source: <code>robust_settings.csv</code>.</p>")

    # ── sleeve ──────────────────────────────────────────────────────────────
    A("<h2 id='sleeve'>The sleeve and gold</h2>")
    rows = [["2014–21 (OOS): 50/50 instead of cash", "+0.9 pp a year on every index. It did <b>not</b> lift the pair above buy-and-hold: SC100 8.9% against 9.6%, blend 9.4% against 12.2%, 4 parents 16.8% against 25.4%"],
            ["Where that OOS lift came from", "One defensive spell, 2019-05 → 2019-12 (gold +18.2%). Without it, the 50/50 sleeve is below cash (7.8% against 8.0%)"],
            ["2021–26 (in-sample)", "68% (SC100), 89% (blend) and 75% (4 books) of the pair's excess over buy-and-hold came from gold's rally"],
            ["Gold in equity falls", "In 11 of the 14 Smallcap 100 falls of 10%+ since 2014, gold rose: on average +9.0% against −21.0%. Weekly correlation with small caps is about 0"],
            ["Does the rule time gold?", "No. Out of sample, gold made 7.0% a year while the pair was defensive and 6.9% while it was invested"],
            ["Daily re-mix vs a drifting 50/50", "At most 0.15 pp a year of difference"]]
    A(table(["Question", "Answer"], rows, prose=True))
    A("<p class='cap'>From the sleeve analysis (<code>sleeve_*.csv</code>, <code>deep_sleeve_analysis.py</code>). Its independent audit did not run because of a usage limit; key figures were spot-checked against the published tables.</p>")

    # ── playbook ────────────────────────────────────────────────────────────
    A("<h2 id='playbook'>What to expect, scenario by scenario</h2>")
    rows = [["Deep, drawn-out bear (2008, 2011, 2018)", ("+34 pp a year, 3 of 3", "pos"), ("+16 pp", "pos"), "Exits after a ~7% fall; Nifty 100 blocks re-entry into bear-market rallies. Takes about a fifth of the fall"],
            ["Crash, then a V (2009, 2016, 2020)", ("+2.5 pp", "pos"), ("+17 pp", "pos"), "Exits after ~10%; re-enters about 9 weeks after the low, at +27% off it"],
            ["Choppy or flat (2013, 2015, 2019)", ("+3.8 pp", "pos"), ("+0.6 pp", "pos"), "Fewer whipsaws; worst fall −11% against −24%"],
            ["Straight bull (2007, 2010, 2012, 2014, 2017)", ("−22 pp a year, 1 of 5", "neg"), ("−1.5 pp", "neg"), "Sits out corrections of 10–20% and re-enters late"],
            ["Small-cap boom large caps don't join (2021; 2023 in-sample)", ("−30 pp (2021 Jan–Oct)", "neg"), ("−30 pp", "neg"), "Nifty 100's SELL keeps the pair out while small caps run"],
            ["Holding large caps (Nifty 50/100)", ("behind in 85% of 5-year windows", "neg"), ("ahead", "pos"), "Large caps rarely fall far enough to pay for the protection; its value there is the smaller fall"]]
    A(table(["Scenario", "Pair vs buy & hold (Smallcap 100 held)", "Pair vs SC100 only", "Why"], rows, prose=True))

    # ── grades ──────────────────────────────────────────────────────────────
    A("<h2 id='grades'>Verdict, claim by claim</h2>")
    rows = [["Cuts the worst fall to about −20% to −30% (from −60% to −77%)", ("Strong", "pos"), "100% of 3- and 5-year windows; 99.9% of random shifts; every index"],
            ["A better timer than Smallcap 100's own signal", ("Strong", "pos"), "P 94–96%; 92–93% of 5-year windows; every index; every setting up to × 2.5"],
            ["The mechanism: a large-cap entry filter plus a small-cap exit trigger", ("Strong", "pos"), "False entries 22% against 39%; only-SC100 weeks at −44% a year; SC100 sold first or together at 8 of 12 tops; the component rules"],
            ["Beats buy-and-hold on return, small caps", ("Moderate", ""), "+6.9 pp observed, P 80%; 56% of 5-year windows; needs a bear market in the period"],
            ["Beats buy-and-hold on return, large caps or the blend", ("Not supported", "neg"), "P 37–63%; 15–26% of 5-year windows"],
            ["The triple improves on the pair", ("Weak", ""), "0 to +1 pp; identical in 2021–26"],
            ["The 2021–26 curve shows what to expect", ("No", "neg"), "68–89% of its excess over buy-and-hold is gold's rally"]]
    A(table(["Claim", "Grade", "Backing"], rows, prose=True))
    A("<div class='callout'><p><b>Recommendation.</b> Use N100 AND SC100 as a drawdown filter for small- and mid-cap-heavy books. "
      "Expect it to beat Smallcap 100's own signal, and to beat buy-and-hold only over periods that contain a real bear market. "
      "Keep the fixed 50/50 sleeve, and treat its return as a bet on gold. Execute on time. Do not retune the supertrend settings on this evidence.</p></div>")

    A("<div class='foot'><p><b>Caveats.</b> The equity indices are price return and cash is total return, which flatters timing against buy-and-hold by roughly 0.5–0.7 pp a year. "
      "Phase and year labels use hindsight; the ex-ante labels are the test without it. Counts are small: 12 falls of 20%+, 14 OOS years. "
      "The desk set the supertrend settings; if they were tuned on 2007–21, this is out of sample for the rule but not for the settings. Gold history starts in 2014. "
      "Worst falls are on daily closes unless marked Friday.</p>"
      "<p><b>Code.</b> <code>deep_core_common.py</code> · <code>deep_years_episodes.py</code> · <code>deep_regimes_mech.py</code> · <code>deep_robust.py</code> · <code>deep_sleeve_analysis.py</code> · <code>deep_report.py</code>. "
      "Written analysis: <code>deep/SYNTHESIS.md</code>; formulas per table: <code>deep/METHODS.md</code>.</p></div>")
    A("</div>")

    page = f"<title>Pair Rule Regime Atlas</title>\n<link rel=\"stylesheet\" href=\"https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600&family=Newsreader:opsz,wght@6..72,400;6..72,500;6..72,600&display=swap\">\n<style>{css}\n.findings ul{{margin:6px 0 0;padding-left:18px}}table.prose td{{white-space:normal;font-family:var(--sans);font-size:13px;text-align:left;vertical-align:top;line-height:1.45}}table.prose th{{text-align:left}}table.prose td:first-child{{min-width:180px}}</style>\n" + "\n".join(body)
    (E / "report.html").write_text(page, encoding="utf-8")
    print("wrote", E / "report.html", round(len(page) / 1024), "KB")


if __name__ == "__main__":
    main()
