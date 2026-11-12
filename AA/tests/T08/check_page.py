"""Independent check of the T08 results page. Imports nothing from the engine, verify_t08.py, analyse.py or report.py.

    python tests/T08/check_page.py [--run headline]                     exit 0 = every check passed; non-zero on any failure or if nothing was compared
    python tests/T08/check_page.py --evidence DIR [--out DIR] [--expect-draws N] [--t06 DIR]

1. Raw files -> decisions: re-derives every weekly decision (Friday reviews, the latest Master row on or before the date: all three index SIGNs BUY, and the MAUc1 SIGN
   for the gold signal) from the approved Master files and the approved extended published NAVs' calendars (both located through its own parse of data/APPROVED_DATA.md,
   so a SUPERSEDED row is never read; the window ends at the last D03 Master row), for the full window and the live window, and compares states, gold states, sleeve weights,
   dates, trade dates, spells, weeks and invested weeks with decisions.csv, gold_signal.csv, real_states.npz and the page.
2. Raw files -> published NAV: the page's published-NAV CAGR and worst fall for each book (clipped at the window end).
3. Inputs: every input the page lists is an APPROVED row (path, through-date, sha256 prefix) and the page's 'As of' date is the file's.
4. Page data -> evidence: every number in the page's embedded JSON (id="page-data"): the NAV curves in daily_nav.csv (CAGR, worst fall of the rule and of each of the
   seven runs at three costs), draws.csv (percentiles, p-values, Holm p against F1 to F4, medians, SDs, spreads, MDE, sessions invested, sleeve trades per draw, R1 to R6),
   stats.csv, T06's stored draws (the historical reference) and the verdict counts.
5. The samplers, from scratch: the number of allowed tuples (in-or-out and gold, full and live) by an own DP and by inclusion-exclusion against count_table.json; the draw-0
   replays of F1 (seed [6, 0]) and F3 (seed [11, 6, 0]) against the page's steps and against draw_states.npz; the sleeve trades of the worked example (identity and units).
6. Every draw of every null in draw_states.npz: weeks, first state, spell counts, sums, N4.9 and N4.9-g sorted lengths, N4.10 and N4.10-g bounds; draws.csv columns
   (sessions invested, sleeve trades, length strings) recomputed from the states.
7. Page text carries the headline numbers as printed; the held/randomised tables are T08.md's.
8. The verifier's result (verify_t08.json) and the gates in analysis.log.
9. Hover data: regime-data (every session's values, states, MAUc1 and sleeve weight, from draw_states.npz and the NAV files), lines-data (every plotted session of the eight
   curves), bars-data (every bin of every histogram, spell-length chart and sampler chart, from draws.csv and draw_states.npz, and the bar rectangles in the SVG against those arrays).
"""
import argparse
import ast
import html as H
import itertools
import json
import math
import re
import sys
from math import comb
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
AA = HERE.parents[1]
BOOKS = ["SCMO_0003", "SCMO_0007", "SCMO_0010", "SCMO_0029"]
LO = 2
KINDS = ["strategy", "strategy_fixed50", "hold_parent", "constant_mix", "constant_mix_timed", "sleeve_only", "sleeve_only_timed"]
CRIT = [("C1", "cagr", "F1", "F2"), ("C2", "max_dd", "F1", "F2"), ("C3", "cagr", "F3", "F4"), ("C4", "max_dd", "F3", "F4")]
FAMS = ("F1", "F2", "F3", "F4")
fails, n = [], 0


def chk(name, ok, detail=""):
    global n
    n += 1
    if not ok:
        fails.append(f"{name}: {detail}")


def close(a, b, tol=1e-9):
    return abs(a - b) <= tol * max(1.0, abs(b))


def cagr(nv):
    return float(nv[-1] ** (252 / (len(nv) - 1)) - 1)


def mdd(nv):
    return float((nv / np.maximum.accumulate(nv) - 1).min())


def pctl(x, d, hb=True):
    tie = np.abs(d - x) <= 1e-12 * max(1.0, abs(x))
    worse = (d < x if hb else d > x) & ~tie
    better = (d > x if hb else d < x) & ~tie
    return float((worse.sum() + 0.5 * tie.sum()) / len(d) * 100), float((1 + better.sum() + tie.sum()) / (len(d) + 1)), int(worse.sum()), int(tie.sum()), int(better.sum())


def holm(ps):
    m = len(ps)
    order = np.argsort(ps)
    out, run = [0.0] * m, 0.0
    for r, i in enumerate(order):
        run = max(run, min(1.0, (m - r) * ps[i]))
        out[i] = run
    return out


def spells(a):
    return [(k, len(list(g))) for k, g in itertools.groupby(map(int, a))]


def lens(a, v):
    return [m for k, m in spells(a) if k == v]


def ways_ie(k, S, lo, hi):
    t = S - k * lo
    tot = 0
    for j in range(k + 1):
        top = t - j * (hi - lo + 1) + k - 1
        if top >= k - 1:
            tot += (-1) ** j * comb(k, j) * comb(top, k - 1)
    return tot


def dp(k, S, lo, hi):
    c = [[0] * (S + 1) for _ in range(k + 1)]
    c[0][0] = 1
    for m in range(1, k + 1):
        for t in range(S + 1):
            c[m][t] = sum(c[m - 1][t - x] for x in range(lo, hi + 1) if t - x >= 0)
    return c


def replay(seed, names, ks, Ss, his):
    rg = np.random.default_rng(seed)
    out = {}
    for nm in names:
        k, S, hi = ks[nm], Ss[nm], his[nm]
        c = dp(k, S, LO, hi)
        t, parts = S, []
        for m in range(k, 0, -1):
            cum = np.cumsum(np.array([c[m - 1][t - x] if t - x >= 0 else 0 for x in range(LO, hi + 1)], dtype=float))
            u = float(rg.random())
            x = LO + min(int(np.searchsorted(cum, u * cum[-1], side="right")), hi - LO)
            parts.append((x, u, int(c[m][t]), int(c[m - 1][t - x])))
            t -= x
        out[nm] = parts
    return out


def approved_rows():
    txt = (AA / "data" / "APPROVED_DATA.md").read_text(encoding="utf-8")
    asof = re.search(r"\*\*As of: (\d{4}-\d{2}-\d{2})", txt).group(1)
    tab = txt[txt.index("<!-- approved-table:start -->"):txt.index("<!-- approved-table:end -->")]
    rows = []
    for l in tab.splitlines():
        if l.startswith("|") and not l.startswith("|---") and not l.startswith("| Status"):
            c = [x.strip() for x in l.strip().strip("|").split("|")]
            rows.append({"status": c[0], "id": c[1], "file": c[2], "through": c[3], "sha": c[4]})
    return asof, rows


def nice_ticks_max(hi, k=4):
    s = hi / k
    m = 10 ** math.floor(math.log10(s))
    r = s / m
    st = (1 if r < 1.5 else 2 if r < 3 else 5 if r < 7 else 10) * m
    v, last = 0.0, 0.0
    while v <= hi + 1e-9:
        last = v
        v += st
    return last


def derive(c, ms, mg, s0=0):
    """Weekly decisions from raw Master rows: T0 = c[s0], then the last session of every later ISO week; returns dates, state, g, labels, trade dates."""
    cc = c[s0:]
    iso = cc.isocalendar()
    last = sorted(pd.Series(cc, index=cc).groupby([iso.year.values, iso.week.values]).max().values)
    dates = [cc[0]] + [pd.Timestamp(x) for x in last if pd.Timestamp(x) > cc[0]]
    st, g, lab, glab, trade = [], [], [], [], []
    for d_ in dates:
        ok = 1
        labs = []
        for s in ms.values():
            i = s.index.searchsorted(d_, side="right") - 1
            ok &= int(s.iloc[i] == "BUY")
            labs.append(s.index[i])
        st.append(ok)
        lab.append(labs)
        i = mg.index.searchsorted(d_, side="right") - 1
        g.append(int(mg.iloc[i] == "BUY"))
        glab.append(mg.index[i])
        k = int(c.get_loc(d_))
        trade.append(c[k + 1] if k + 1 < len(c) else pd.NaT)
    return dates, np.array(st), np.array(g), lab, glab, trade


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="headline")
    ap.add_argument("--evidence", default=None)
    ap.add_argument("--out", default=None, help="directory of report.html and analysis.log")
    ap.add_argument("--expect-draws", type=int, default=2000)
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
    ND = a.expect_draws
    html = (outdir / "report.html").read_text(encoding="utf-8")

    def block(i):
        return json.loads(re.search(rf'<script type="application/json" id="{i}">(.*?)</script>', html, re.S).group(1))

    page, hv, lh, bd = block("page-data"), block("regime-data"), block("lines-data"), block("bars-data")
    text = H.unescape(re.sub(r"<[^>]+>", "", re.sub(r"<script.*?</script>|<style.*?</style>", "", html, flags=re.S)))
    dec = pd.read_csv(ev / "decisions.csv")
    gsig = pd.read_csv(ev / "gold_signal.csv")
    nav = pd.read_csv(ev / "daily_nav.csv", parse_dates=["date"])
    dr = pd.read_csv(ev / "draws.csv")
    st = pd.read_csv(ev / "stats.csv")
    sl = pd.read_csv(ev / "sleeve_trades.csv")
    tr = pd.read_csv(ev / "trades.csv")
    pos = pd.read_csv(ev / "positions.csv")
    z = np.load(ev / "draw_states.npz")
    ST = {k: z[k] for k in z.files}
    rz = np.load(ev / "real_states.npz")
    RZ = {k: rz[k] for k in rz.files}
    curves = np.load(ev / "draw_curves_20.8.npz")
    ct = json.loads((ev / "count_table.json").read_text(encoding="utf-8"))
    asof, arows = approved_rows()
    appr = [r for r in arows if r["status"] == "APPROVED"]
    LIQ = "liq" if "liq" in set(st.cash) else "liquidcase"

    # 1-2. raw files -> decisions, gold signal and published NAV (files found through the APPROVED rows only)
    ms = {}
    for nme in ("Nifty100", "MC100", "SC100"):
        rr = [r for r in appr if r["file"].endswith(f"Master_{nme}.xlsx")]
        chk(f"one APPROVED Master row for {nme}", len(rr) == 1, str(len(rr)))
        d = pd.read_excel(AA / rr[0]["file"], parse_dates=["Date"])
        ms[nme] = d.dropna(subset=["SIGN"]).set_index("Date")["SIGN"].sort_index()
    END = min(s.index[-1] for s in ms.values())
    rr = [r for r in appr if r["file"].endswith("Master_MAUc1.xlsx")]
    chk("one APPROVED Master_MAUc1 row", len(rr) == 1, str(len(rr)))
    d = pd.read_excel(AA / rr[0]["file"], parse_dates=["Date"])
    mg = d.dropna(subset=["SIGN"]).set_index("Date")["SIGN"].sort_index()
    cal, rule, gold, rin, rout, gbuy, gsell, ends = {}, {}, {}, {}, {}, {}, {}, set()
    live_io, live_g = {}, {}
    rawpub = {}
    for b in BOOKS:
        rr = [r for r in appr if "extended_2026-11-06/published_nav" in r["file"].replace("\\", "/") and r["file"].replace("\\", "/").endswith(f"/{b}.csv")]
        chk(f"one APPROVED extended published-NAV row for {b}", len(rr) == 1, str(len(rr)))
        raw = pd.read_csv(AA / rr[0]["file"])
        raw["d"] = pd.to_datetime(raw["_id.date"], format="%Y/%m/%d")
        raw = raw.sort_values("d")
        raw = raw[raw.d <= END]
        c = pd.DatetimeIndex(raw.d.values)
        cal[b] = c
        rawpub[b] = raw["index"].values
        ends.add(c[-1])
        dates, sr, gr, lab, glab, trade = derive(c, ms, mg)
        rule[b], gold[b] = sr, gr
        rin[b], rout[b], gbuy[b], gsell[b] = lens(sr, 1), lens(sr, 0), lens(gr, 1), lens(gr, 0)
        e = dec[dec.book == b].sort_values("j").reset_index(drop=True)
        chk(f"{b} number of decisions", len(e) == len(dates) == page["weeks"][b], f"{len(e)} vs {len(dates)}")
        chk(f"{b} decision dates", list(pd.to_datetime(e.decision_date)) == dates)
        chk(f"{b} in-or-out states", list(e.state) == list(sr), "state sequences differ")
        chk(f"{b} gold states (g) and sleeve weights (gw)", list(e.g) == list(gr) and np.abs(e.gw.values - np.where(gr == 1, 0.8, 0.2)).max() < 1e-12)
        chk(f"{b} MAUc1 SIGN and label", list(e.sign_MAUc1) == ["BUY" if x else "SELL" for x in gr] and list(pd.to_datetime(e.label_MAUc1)) == glab)
        chk(f"{b} trade dates (next session; none after the last decision)", len(e) == len(trade) and all((pd.isna(x) and pd.isna(y)) or (not pd.isna(x) and not pd.isna(y) and pd.Timestamp(x) == pd.Timestamp(y)) for x, y in zip(e.trade_date, trade)))
        chk(f"{b} no Master label dated after its decision", all(max(l) <= d_ for l, d_ in zip(lab, dates)) and all(g_ <= d_ for g_, d_ in zip(glab, dates)))
        gg = gsig[gsig.book == b].sort_values("j")
        chk(f"{b} gold_signal.csv equals the derived gold series", list(gg.g) == list(gr) and list(pd.to_datetime(gg.decision_date)) == dates)
        chk(f"{b} real_states.npz (full) equal the derived series", (RZ[f"{b}|full|io"].astype(int) == sr).all() and (RZ[f"{b}|full|gold"].astype(int) == gr).all())
        dl, sl_, gl_, *_ = derive(c, ms, mg, int(c.get_loc(pd.Timestamp("2021-11-01"))))
        live_io[b], live_g[b] = sl_, gl_
        chk(f"{b} real_states.npz (live) equal the series derived from 2021-11-01", (RZ[f"{b}|live|io"].astype(int) == sl_).all() and (RZ[f"{b}|live|gold"].astype(int) == gl_).all())
        chk(f"{b} spells on the page", page["books"][b]["rule_in"] == rin[b] and page["books"][b]["rule_out"] == rout[b] and page["books"][b]["rule_buy"] == gbuy[b] and page["books"][b]["rule_sell"] == gsell[b], f"{rin[b]} {rout[b]}")
        nvs = nav[(nav.book == b) & (nav.cost_bps == 20.8) & (nav.run == "strategy")].sort_values("date")
        chk(f"{b} NAV calendar is the published calendar", list(nvs.date) == list(c))
        r_ = raw["index"].values / raw["index"].values[0]
        chk(f"{b} published CAGR", close(page["books"][b]["pub_cagr"], cagr(r_)), f"{page['books'][b]['pub_cagr']} vs {cagr(r_)}")
        chk(f"{b} published worst fall", close(page["books"][b]["pub_dd"], mdd(r_)))
        pn = nav[(nav.book == b) & (nav.run == "published_D17")].sort_values("date")
        chk(f"{b} published NAV curve is the rebased approved file", list(pn.date) == list(c) and np.abs(pn.nav.values - r_).max() < 1e-9)
    chk("every book ends on the same published date, the page's end date, the last D03 row", len(ends) == 1 and str(list(ends)[0].date()) == page["end"] == str(END.date()), f"{ends} {page['end']} {END}")
    chk("start dates", page["start"] == str(cal["SCMO_0003"][0].date()) and page["start_0007"] == str(cal[B7][0].date()))
    HI = {"in": max(max(rin[b]) for b in BOOKS), "out": max(max(rout[b]) for b in BOOKS), "buy": max(max(gbuy[b]) for b in BOOKS), "sell": max(max(gsell[b]) for b in BOOKS)}
    chk("bounds on the page are the real series' longest spells", page["bounds"] == {"lo": LO, "hi_in": HI["in"], "hi_out": HI["out"], "hi_buy": HI["buy"], "hi_sell": HI["sell"]}, str(page["bounds"]))
    chk("the real series' shortest spell is at least 2 (lo = min(2, shortest) = 2)", min(min(rin[b] + rout[b] + gbuy[b] + gsell[b]) for b in BOOKS) >= LO)

    # 3. inputs
    chk("page's As-of date is APPROVED_DATA.md's", page["as_of_file"] == asof and asof in html, f"{page['as_of_file']} vs {asof}")
    rec = None
    for l in (ev / "inputs.csv").read_text(encoding="utf-8").splitlines():
        if l.startswith("#") and re.search(r"\d{4}-\d{2}-\d{2}", l):
            rec = re.search(r"\d{4}-\d{2}-\d{2}", l).group(0)
    if rec is None:
        rec = ((json.loads((ev / "audit.json").read_text(encoding="utf-8")).get("data") or {}).get("approved_data_as_of"))
    chk("the run recorded the same As-of date (inputs.csv header or audit.json) and the page prints it", page["as_of_inputs"] == rec == asof and rec in html, f"{page['as_of_inputs']} / {rec} vs {asof}")
    byfile = {r["file"].replace("\\", "/"): r for r in arows}
    chk("inputs listed", len(page["inputs"]) > 10, str(len(page["inputs"])))
    chk("inputs include the MAUc1 Master (D24) and the extended published NAVs", any("Master_MAUc1" in r["file"] for r in page["inputs"]) and sum("extended_2026-11-06/published_nav" in r["file"].replace("\\", "/") for r in page["inputs"]) >= len(BOOKS))
    for r in page["inputs"]:
        ar = byfile.get(r["file"].replace("\\", "/"))
        chk(f"input {r['file']} is a row of APPROVED_DATA.md", ar is not None)
        if ar is not None:
            chk(f"input {r['file']} is APPROVED, not superseded or pending", ar["status"] == "APPROVED", ar["status"])
            chk(f"input {r['file']} through-date", r["through"] == ar["through"], f"{r['through']} vs {ar['through']}")
            chk(f"input {r['file']} sha256 prefix", ar["sha"].startswith(r["sha16"][:len(ar["sha"])]) or r["sha16"].startswith(ar["sha"]), f"{r['sha16']} vs {ar['sha']}")
            # exempt from 'through covers the window end': D19, D05, D12 (earlier than the window by design) and the old D17 files, which are read only for the regression to T06 (V4(e))
            if re.match(r"\d{4}-\d{2}-\d{2}$", ar["through"]) and all(w_ not in ar["file"] for w_ in ("holding_weight", "Rebalance_history", "mauc1", "parent_nav_2026-10-22")):
                chk(f"input {r['file']} covers the window end", ar["through"] >= page["end"], ar["through"])
            chk(f"page's table row for {r['file']} shows its through-date, row and sha256 prefix", f"<tr><td>{H.escape(r['file'])}</td><td>{H.escape(ar['through'])}</td><td>{H.escape(r['approved_row'])}</td><td>{H.escape(r['sha16'])}</td></tr>" in html)

    # 4. page data -> evidence
    dd = lambda b, fam, win="full", cash="lbes", cost=20.8, mode="timed": dr[(dr.book == b) & (dr.window == win) & (dr.cash == cash) & (dr.cost_bps == cost) & (dr.family == fam) & (dr.sleeve_mode == mode)].sort_values("draw_id")
    sv_of = lambda b, kind, c=20.8: nav[(nav.book == b) & (nav.cost_bps == c) & (nav.run == kind)].sort_values("date").nav.values
    for b in BOOKS:
        pb = page["books"][b]
        for kind in KINDS:
            for c in (0.0, 20.8, 50.0):
                v = sv_of(b, kind, c)
                if c == 20.8:
                    chk(f"{b} {kind} NAV starts at 1", close(v[0], 1.0, 1e-12))
                    chk(f"{b} {kind} CAGR and worst fall from NAV at 20.8", close(pb[f"{kind}_cagr"], cagr(v)) and close(pb[f"{kind}_dd"], mdd(v)), f"{pb[kind + '_cagr']} vs {cagr(v)}")
                chk(f"{b} {kind} CAGR and worst fall from NAV at {c}", close(pb[f"{kind}_cagr_{c:g}"], cagr(v)) and close(pb[f"{kind}_dd_{c:g}"], mdd(v)))
        sv = sv_of(b, "strategy")
        chk(f"{b} end NAV", close(pb["end_nav"], float(sv[-1])))
        pcs = {}
        for fam in FAMS:
            nd = dd(b, fam)
            chk(f"{b} {fam} draws count", len(nd) == ND and list(nd.draw_id) == list(range(ND)), str(len(nd)))
            p1, q1, w1, t1, b1 = pctl(cagr(sv), nd.cagr.values)
            p2, q2, *_ = pctl(mdd(sv), nd.max_dd.values)
            pcs[fam] = (q1, q2)
            chk(f"{b} {fam} CAGR percentile and p", close(pb[f"{fam}_pct_cagr"], p1) and close(pb[f"{fam}_p_cagr"], q1) and (pb[f"{fam}_worse"], pb[f"{fam}_tied"], pb[f"{fam}_better"]) == (w1, t1, b1))
            chk(f"{b} {fam} drawdown percentile and p", close(pb[f"{fam}_pct_dd"], p2) and close(pb[f"{fam}_p_dd"], q2))
            chk(f"{b} {fam} medians", close(pb[f"{fam}_median_cagr"], float(nd.cagr.median())) and close(pb[f"{fam}_median_dd"], float(nd.max_dd.median())))
            chk(f"{b} {fam} SD and MDE", close(pb[f"{fam}_sd_cagr"], float(nd.cagr.std())) and close(pb[f"{fam}_mde_cagr_pp"], 280 * float(nd.cagr.std())) and close(pb[f"{fam}_mde_dd_pp"], 280 * float(nd.max_dd.std())) and close(pb[f"{fam}_sd_dd"], float(nd.max_dd.std())))
            q5, q95 = np.percentile(nd.cagr.values, [5, 95])
            chk(f"{b} {fam} 5th and 95th percentile of CAGR", close(pb[f"{fam}_p5_cagr"], float(q5)) and close(pb[f"{fam}_p95_cagr"], float(q95)))
            chk(f"{b} {fam} sessions invested summary", (pb[f"{fam}_sess_min"], pb[f"{fam}_sess_max"]) == (int(nd.sessions_invested.min()), int(nd.sessions_invested.max())) and close(pb[f"{fam}_sess_median"], float(nd.sessions_invested.median())))
            chk(f"{b} {fam} sleeve trades summary", (pb[f"{fam}_strades_min"], pb[f"{fam}_strades_max"]) == (int(nd.sleeve_trades.min()), int(nd.sleeve_trades.max())) and close(pb[f"{fam}_strades_median"], float(nd.sleeve_trades.median())))
            for c in (0.0, 50.0):
                vv = sv_of(b, "strategy", c)
                chk(f"{b} {fam} CAGR percentile at {c}", close(pb[f"{fam}_pct_cagr_{c:g}"], pctl(cagr(vv), dd(b, fam, cost=c).cagr.values)[0]))
                chk(f"{b} {fam} drawdown percentile at {c}", close(pb[f"{fam}_pct_dd_{c:g}"], pctl(mdd(vv), dd(b, fam, cost=c).max_dd.values)[0]))
        h_ = holm([pcs["F1"][0], pcs["F1"][1], pcs["F3"][0], pcs["F3"][1]])
        chk(f"{b} Holm-adjusted p over C1 to C4", all(close(pb[f"holm_C{i + 1}"], h_[i]) for i in range(4)), str(h_))
        for fam in ("F1", "F3"):
            s_live = st[(st.book == b) & (st.window == "live") & (st.kind == "strategy")].iloc[0]
            chk(f"{b} {fam} live percentile", close(pb[f"{fam}_live_pct"], pctl(s_live.cagr, dd(b, fam, win="live").cagr.values)[0]) and close(pb["live_cagr"], float(s_live.cagr)))
            s_liq = st[(st.book == b) & (st.cash == LIQ) & (st.kind == "strategy")].iloc[0]
            chk(f"{b} {fam} LIQUIDCASE percentile", close(pb[f"{fam}_liq_pct"], pctl(s_liq.cagr, dd(b, fam, cash=LIQ).cagr.values)[0]) and close(pb["liq_cagr"], float(s_liq.cagr)))
        n5 = dd(b, "F5")
        chk(f"{b} F5 draws, median, SD and percentiles", len(n5) == ND and close(pb["F5_median_cagr"], float(n5.cagr.median())) and close(pb["F5_sd_cagr"], float(n5.cagr.std())) and close(pb["F5_pct_cagr"], pctl(cagr(sv), n5.cagr.values)[0])
            and close(pb["F5_p_cagr"], pctl(cagr(sv), n5.cagr.values)[1]) and close(pb["F5_pct_dd"], pctl(mdd(sv), n5.max_dd.values)[0]) and close(pb["F5_p_dd"], pctl(mdd(sv), n5.max_dd.values)[1]))
        sf = sv_of(b, "strategy_fixed50")
        dr_c, dr_d = cagr(sv) - cagr(sf), mdd(sv) - mdd(sf)
        chk(f"{b} R6 rule change from 50/50 to timed", close(pb["r6_rule_dcagr"], dr_c) and close(pb["r6_rule_ddd"], dr_d))
        for fam in ("F1", "F2"):
            t_, f_ = dd(b, fam), dd(b, fam, mode="fixed50")
            chk(f"{b} R6 {fam}: same draw ids timed and fixed50", list(t_.draw_id) == list(f_.draw_id) == list(range(ND)))
            dcs, dds = t_.cagr.values - f_.cagr.values, t_.max_dd.values - f_.max_dd.values
            chk(f"{b} R6 {fam} medians, percentiles, shares", close(pb[f"r6_{fam}_median_dcagr"], float(np.median(dcs))) and close(pb[f"r6_{fam}_pct_dcagr"], pctl(dr_c, dcs)[0]) and close(pb[f"r6_{fam}_share_dcagr"], float((dcs > 0).mean()))
                and close(pb[f"r6_{fam}_median_ddd"], float(np.median(dds))) and close(pb[f"r6_{fam}_pct_ddd"], pctl(dr_d, dds)[0]) and close(pb[f"r6_{fam}_share_ddd"], float((dds > 0).mean())))
        # rule sessions invested, from the decisions and the calendar
        e = dec[dec.book == b].sort_values("j").reset_index(drop=True)
        cl = nav[(nav.book == b) & (nav.cost_bps == 20.8) & (nav.run == "strategy")].sort_values("date").date.values
        w0 = [0] + [len(cl) - 1 if pd.isna(t) else int(np.searchsorted(cl, np.datetime64(pd.Timestamp(t)))) for t in e.trade_date.iloc[1:]]
        ws = np.array(w0[1:] + [len(cl) - 1]) - np.array(w0)
        chk(f"{b} rule sessions invested and total", pb["rule_sessions"] == int(rule[b] @ ws) and pb["sessions_total"] == len(cl) - 1)
        for fam, key in (("F1", "io|N4.10"), ("F2", "io|N4.9")):
            chk(f"{b} {fam} sessions_invested column equals states @ sessions per week", bool((ST[f"{b}|full|{key}"].astype(np.int64) @ ws == dd(b, fam).sessions_invested.values).all()))
        for fam in ("F3", "F4"):
            chk(f"{b} {fam} sessions_invested equal the rule's (the real switch)", bool((dd(b, fam).sessions_invested.values == int(rule[b] @ ws)).all()))
        s_row = st[(st.book == b) & (st.window == "full") & (st.cash == "lbes") & (st.cost_bps == 20.8) & (st.kind == "strategy")].iloc[0]
        chk(f"{b} cost paid, trades and sleeve trades", close(pb["cost_paid"], float(s_row.cost_paid)) and pb["trades"] == int(s_row.trades) and pb["sleeve_trades"] == int(s_row.sleeve_trades))
        chk(f"{b} invested weeks equal the decisions'", int(s_row.invested_weeks) == int(rule[b].sum()))
        rt = lambda a_: min(int(((a_[1:] == 1) & (a_[:-1] == 0)).sum()) + int(a_[0] == 1), int(((a_[1:] == 0) & (a_[:-1] == 1)).sum()))

        def gwo(g, s):
            k_, i_ = 0, 0
            for v_, ln in spells(g):
                k_ += int((s[i_:i_ + ln] == 0).any())
                i_ += ln
            return k_
        chk(f"{b} round trips and gold spells with an OUT week", pb["round_trips"] == rt(rule[b]) and pb["gold_spells_with_out"] == gwo(gold[b], rule[b]))
        # sleeve trades: the rule's number and dates from the decisions
        exp_reb = [j for j in range(1, len(e)) if rule[b][j - 1] == 0 and rule[b][j] == 0 and gold[b][j] != gold[b][j - 1] and not pd.isna(e.trade_date[j])]
        sq = sl[(sl.book == b) & (sl.cost_bps == 20.8) & (sl.kind == "sleeve_rebalance")]
        chk(f"{b} sleeve rebalances: number and dates from the decisions", len(sq) == len(exp_reb) == pb["sleeve_trades"] and sorted(sq.date) == sorted(e.trade_date[exp_reb]), f"{len(sq)} vs {len(exp_reb)}")
    nr = [b for b in BOOKS if page["books"][b]["round_trips"] < 4 or page["books"][b]["gold_spells_with_out"] < 4]
    nrl = [b for b in BOOKS if rt(live_io[b]) < 4 or gwo(live_g[b], live_io[b]) < 4]
    chk("reportability lists", page["not_reportable"] == nr and page["not_reportable_live"] == nrl, f"{page['not_reportable']} {nr} {page['not_reportable_live']} {nrl}")
    V = page["verdict"]
    cnt = lambda key, c_=None: sum(page["books"][b][key] >= 90 and b not in nr for b in BOOKS)
    chk("verdict counts", (V["C1"], V["C2"], V["C3"], V["C4"], V["C1_F2"], V["C2_F2"], V["C3_F4"], V["C4_F4"], V["R3_live_C1"], V["R3_live_C3"], V["R2_liq_C1"], V["R2_liq_C3"]) ==
        (cnt("F1_pct_cagr"), cnt("F1_pct_dd"), cnt("F3_pct_cagr"), cnt("F3_pct_dd"), cnt("F2_pct_cagr"), cnt("F2_pct_dd"), cnt("F4_pct_cagr"), cnt("F4_pct_dd"), cnt("F1_live_pct"), cnt("F3_live_pct"), cnt("F1_liq_pct"), cnt("F3_liq_pct")))
    A_ok, B_ok = V["C1"] >= 3 and V["C2"] >= 3, V["C3"] >= 3 and V["C4"] >= 3
    chk("outcome-map flags on the page", page["outcome"] == {"A": bool(A_ok), "B": bool(B_ok)})
    # historical reference: T06's stored draws
    if (t06 / "draws.csv").exists():
        s6, d6 = pd.read_csv(t06 / "stats.csv"), pd.read_csv(t06 / "draws.csv")
        for b in BOOKS:
            sr = s6[(s6.book == b) & (s6.window == "full") & (s6.cash == "lbes") & (s6.cost_bps == 20.8) & (s6.kind == "strategy")].iloc[0]
            tr_ = page["t06_reference"].get(b)
            ok = tr_ is not None and close(tr_["cagr"], float(sr.cagr))
            for typ, nm in (("N4.10", "n10"), ("N4.9", "n9")):
                nd_ = d6[(d6.book == b) & (d6.window == "full") & (d6.cash == "lbes") & (d6.cost_bps == 20.8) & (d6.draw_type == typ)]
                ok = ok and tr_ is not None and close(tr_[f"{nm}_pct_cagr"], pctl(sr.cagr, nd_.cagr.values)[0]) and close(tr_[f"{nm}_pct_dd"], pctl(sr.max_dd, nd_.max_dd.values)[0])
            chk(f"{b} T06 historical reference", ok)
    else:
        chk("T06 reference not checked (evidence not found); page must then carry none", page["t06_reference"] == {})
    r7 = [p for p in (ev / "r7_raw_fill.csv", ev / "raw_fill_sensitivity.csv", ev / "r7.csv") if p.exists()]
    if r7:
        chk("R7 file read as is", page["r7"] is not None and page["r7"]["rows"] == pd.read_csv(r7[0]).astype(str).values.tolist() and page["r7"]["columns"] == list(pd.read_csv(r7[0]).columns))
    else:
        chk("R7 not in evidence: the page says so", page["r7"] is None and "Not in evidence" in text)
    rawt = sl[(sl.cost_bps == 20.8) & (sl.gold_fill_raw.astype(bool))]
    chk("raw-fill sleeve trades listed on the page", page["raw_fill_sleeve_trades"] == [[r_.book, r_.date, r_.kind] for r_ in rawt.itertuples()])
    chk("raw-fill flag is exactly 'after 2026-09-28'", bool(((pd.to_datetime(sl.date) > pd.Timestamp("2026-09-28")) == sl.gold_fill_raw.astype(bool)).all()))

    # 5. the samplers from scratch
    cte = {}
    for key, o in ct["tables"].items():
        p_ = key.split("|")
        cte[tuple(p_)] = {"k": int(o.get("spells_k", o.get("k"))), "S": int(o.get("weeks_S", o.get("S"))), "lo": int(o["lo"]), "hi": int(o["hi"]), "n_ways": int(o["n_ways"])}
    real = {("full", "io"): rule, ("full", "gold"): gold, ("live", "io"): live_io, ("live", "gold"): live_g}
    hiof = {("io", "in"): HI["in"], ("io", "out"): HI["out"], ("gold", "buy"): HI["buy"], ("gold", "sell"): HI["sell"]}
    for b in BOOKS:
        for win in ("full", "live"):
            for kind, sts in (("io", (("in", 1), ("out", 0))), ("gold", (("buy", 1), ("sell", 0)))):
                for nm, v_ in sts:
                    e = cte.get((b, win, kind, nm))
                    chk(f"count_table entry {b}/{win}/{kind}/{nm}", e is not None)
                    if e:
                        hi = hiof[(kind, nm)]
                        ls = lens(real[(win, kind)][b], v_)
                        chk(f"count_table {b}/{win}/{kind}/{nm}: bounds and feasibility", (e["lo"], e["hi"]) == (LO, hi) and LO * e["k"] <= e["S"] <= hi * e["k"])
                        chk(f"count_table {b}/{win}/{kind}/{nm}: k and S are the real series'", (e["k"], e["S"]) == (len(ls), sum(ls)))
                        chk(f"count_table {b}/{win}/{kind}/{nm}: n_ways = inclusion-exclusion = own DP", e["n_ways"] == ways_ie(e["k"], e["S"], LO, hi) == dp(e["k"], e["S"], LO, hi)[e["k"]][e["S"]], str(e["n_ways"]))
    ex = page["example"]
    b = "SCMO_0003"
    kin, Sin, kout, Sout = len(rin[b]), sum(rin[b]), len(rout[b]), sum(rout[b])
    kb, Sb, ks_, Ss_ = len(gbuy[b]), sum(gbuy[b]), len(gsell[b]), sum(gsell[b])
    chk("example sampler parameters", (ex["k_in"], ex["S_in"], ex["hi_in"], ex["k_out"], ex["S_out"], ex["hi_out"], ex["k_buy"], ex["S_buy"], ex["hi_buy"], ex["k_sell"], ex["S_sell"], ex["hi_sell"]) ==
        (kin, Sin, HI["in"], kout, Sout, HI["out"], kb, Sb, HI["buy"], ks_, Ss_, HI["sell"]))
    chk("example allowed-tuple counts", int(ex["ways_in"]) == int(ex["ways_in_table"]) == ways_ie(kin, Sin, LO, HI["in"]) and int(ex["ways_out"]) == int(ex["ways_out_table"]) == ways_ie(kout, Sout, LO, HI["out"])
        and int(ex["ways_buy"]) == int(ex["ways_buy_table"]) == ways_ie(kb, Sb, LO, HI["buy"]) and int(ex["ways_sell"]) == int(ex["ways_sell_table"]) == ways_ie(ks_, Ss_, LO, HI["sell"]))
    for tag, seed, names, ks, Ss, his, stk, key in (("F1", [6, 0], ("in", "out"), {"in": kin, "out": kout}, {"in": Sin, "out": Sout}, {"in": HI["in"], "out": HI["out"]}, "steps", "io|N4.10"),
                                                    ("F3", [11, 6, 0], ("buy", "sell"), {"buy": kb, "sell": ks_}, {"buy": Sb, "sell": Ss_}, {"buy": HI["buy"], "sell": HI["sell"]}, "steps_g", "gold|N4.10-g")):
        rp = replay(seed, names, ks, Ss, his)
        mine = [(s_, p_) for s_ in names for p_ in rp[s_]]
        chk(f"{tag} example replay: same number of steps", len(ex[stk]) == len(mine) == sum(ks.values()))
        for stp, (sp, (x, u, tot, wx)) in zip(ex[stk], mine):
            chk(f"{tag} example replay step", stp["spell"] == sp and stp["x"] == x and close(stp["u"], u, 1e-12) and stp["total"] == tot and stp["ways_x"] == wx and close(stp["p"], wx / tot, 1e-9), str(stp))
        Zk = ST[f"{b}|full|{key}"]
        mine_a, mine_b = [p_[0] for p_ in rp[names[0]]], [p_[0] for p_ in rp[names[1]]]
        chk(f"{tag} example replay equals the stored draw 0 (states file)", mine_a == lens(Zk[0], 1) and mine_b == lens(Zk[0], 0), f"{mine_a} {mine_b} vs {lens(Zk[0], 1)} {lens(Zk[0], 0)}")
        chk(f"{tag} example replay flag on the page", (ex["replay_ok"] if tag == "F1" else ex["replay_ok_g"]) is True)
        x_ = dd(b, tag).query("draw_id == 0").iloc[0]
        s_a, s_b = ("in_lengths", "out_lengths") if tag == "F1" else ("g_buy_lengths", "g_sell_lengths")
        chk(f"{tag} example draw 0 lengths in draws.csv equal the replay", str(x_[s_a]) == "|".join(map(str, mine_a)) and str(x_[s_b]) == "|".join(map(str, mine_b)))
    chk("page says both replays equal the stored draws", html.count("replay equals the stored draw") == 2)
    chk("first-step weights (F1 and F3)", page["sampler_first"]["weights"] == [dp(kin, Sin, LO, HI["in"])[kin - 1][Sin - x] if Sin - x >= 0 else 0 for x in range(LO, HI["in"] + 1)] and sum(page["sampler_first"]["weights"]) == int(ex["ways_in"])
        and page["sampler_first_g"]["weights"] == [dp(kb, Sb, LO, HI["buy"])[kb - 1][Sb - x] if Sb - x >= 0 else 0 for x in range(LO, HI["buy"] + 1)] and sum(page["sampler_first_g"]["weights"]) == int(ex["ways_buy"]))
    for fam in FAMS:
        x_ = dd(b, fam).query("draw_id == 0").iloc[0]
        e_ = ex["d0"][fam]
        chk(f"example {fam} draw 0 numbers", close(e_["cagr"], float(x_.cagr)) and close(e_["max_dd"], float(x_.max_dd)) and e_["sessions"] == int(x_.sessions_invested) and e_["sleeve_trades"] == int(x_.sleeve_trades))
        rk = ex["rank"][fam]
        nd = dd(b, fam)
        chk(f"example ranking against {fam} adds up", rk["worse"] + rk["tied"] + rk["better"] == rk["draws"] == ND == len(nd))
        chk(f"example percentile and p against {fam}", close(rk["percentile"], (rk["worse"] + 0.5 * rk["tied"]) / ND * 100) and close(rk["p"], (1 + rk["better"] + rk["tied"]) / (ND + 1)) and close(rk["percentile"], page["books"][b][f"{fam}_pct_cagr"]))
    # the worked sleeve trades: identity, units, dates
    e0 = dec[dec.book == b].sort_values("j").reset_index(drop=True)
    exx, exf = ex["exit"], ex["flip"]
    slq = sl[(sl.book == b) & (sl.cost_bps == 20.8)]
    trq = tr[(tr.book == b) & (tr.run == "strategy") & (tr.cost_bps == 20.8)]
    pq = pos[(pos.book == b) & (pos.cost_bps == 20.8) & (pos.run == "strategy")]
    first_exit = slq[slq.kind == "switch_out"].iloc[0]
    jx = int(e0.index[e0.trade_date == first_exit.date][0])
    chk("example exit: the first IN to OUT decision of the book", jx == ex["exit"]["decision_week"] == min(j for j in range(1, len(rule[b])) if rule[b][j - 1] == 1 and rule[b][j] == 0))
    chk("example exit: dates, signal and weights", exx["decision_date"] == str(e0.decision_date[jx]) and exx["trade_date"] == str(e0.trade_date[jx]) and exx["g"] == int(gold[b][jx]) and close(exx["gw"], 0.8 if gold[b][jx] else 0.2) and exx["sign_MAUc1"] == ("BUY" if gold[b][jx] else "SELL"))
    ttx = trq[trq.date == exx["trade_date"]].iloc[0]
    chk("example exit: numbers equal trades.csv and sleeve_trades.csv", close(exx["V"], float(ttx.V)) and close(exx["traded"], float(first_exit.traded)) and close(exx["cost"], float(first_exit.cost)) and close(exx["nav_after"], float(ttx.nav_close_after))
        and close(exx["gold_after"], float(first_exit.gold_value_after)) and close(exx["cash_after"], float(first_exit.cash_value_after)))
    chk("example exit: cost = traded x 20.8/2/10000", close(exx["cost"], exx["traded"] * 20.8 / 2 / 10000, 1e-9))
    chk("example exit: GOLDBEES = w (V - cost), cash = (1 - w)(V - cost)", close(exx["gold_after"], exx["gw"] * (exx["V"] - exx["cost"]), 1e-9) and close(exx["cash_after"], (1 - exx["gw"]) * (exx["V"] - exx["cost"]), 1e-9))
    pd_ = sorted(set(pq.date))
    ua = {r_.instrument: float(r_.units) for r_ in pq[pq.date == exx["trade_date"]].itertuples() if not str(r_.instrument).endswith(".NS")}
    chk("example exit: units after", set(ua) == set(exx["units_after"]) and all(close(ua[k_], exx["units_after"][k_]) for k_ in ua))
    rebs = slq[slq.kind == "sleeve_rebalance"]
    cands = [r_ for r_ in rebs.itertuples() if pd_.index(r_.date) > 0] if all(r_.date in pd_ for r_ in rebs.itertuples()) else []
    chk("example flip: the first gold flip with a positions snapshot before it", len(cands) > 0 and cands[0].date == exf["trade_date"], str(exf["trade_date"]))
    fr = rebs[rebs.date == exf["trade_date"]].iloc[0]
    jf = int(e0.index[e0.trade_date == exf["trade_date"]][0])
    chk("example flip: OUT on both sides, signal changed, dates", rule[b][jf - 1] == 0 and rule[b][jf] == 0 and gold[b][jf] != gold[b][jf - 1] and exf["decision_week"] == jf and exf["decision_date"] == str(e0.decision_date[jf])
        and exf["g_before"] == int(gold[b][jf - 1]) and exf["g_after"] == int(gold[b][jf]) and close(exf["gw_after"], 0.8 if gold[b][jf] else 0.2))
    ttf = trq[trq.date == exf["trade_date"]].iloc[0]
    chk("example flip: numbers equal trades.csv and sleeve_trades.csv", close(exf["V"], float(ttf.V)) and close(exf["traded"], float(fr.traded)) and close(exf["cost"], float(fr.cost)) and close(exf["nav_after"], float(ttf.nav_close_after))
        and close(exf["gold_before"], float(fr.gold_value_before)) and close(exf["cash_before"], float(fr.cash_value_before)) and close(exf["gold_after"], float(fr.gold_value_after)) and close(exf["cash_after"], float(fr.cash_value_after)))
    chk("example flip: cost = traded x 20.8/2/10000, value conserved after cost, split = target", close(exf["cost"], exf["traded"] * 20.8 / 2 / 10000, 1e-9)
        and close(exf["gold_before"] + exf["cash_before"] - exf["cost"], exf["gold_after"] + exf["cash_after"], 1e-9) and close(exf["gold_after"], exf["gw_after"] * (exf["gold_after"] + exf["cash_after"]), 1e-9))
    pdate = pd_[pd_.index(exf["trade_date"]) - 1]
    chk("example flip: units before are the positions of the previous trade, units after those of the trade", exf["prev_pos_date"] == pdate)
    ub = {r_.instrument: float(r_.units) for r_ in pq[pq.date == pdate].itertuples() if not str(r_.instrument).endswith(".NS")}
    ua2 = {r_.instrument: float(r_.units) for r_ in pq[pq.date == exf["trade_date"]].itertuples() if not str(r_.instrument).endswith(".NS")}
    chk("example flip: units", set(ub) == set(exf["units_before"]) and set(ua2) == set(exf["units_after"]) and all(close(ub[k_], exf["units_before"][k_]) for k_ in ub) and all(close(ua2[k_], exf["units_after"][k_]) for k_ in ua2))
    gk = next((k_ for k_ in ua2 if k_.upper().startswith("GOLD")), None)
    ck = next((k_ for k_ in ua2 if k_ != gk), None)
    chk("example flip: the fill price (value / units) is the same before and after, for GOLDBEES and for cash", gk is not None and ck is not None and gk in ub and ck in ub and
        close(exf["gold_before"] / ub[gk], exf["gold_after"] / ua2[gk], 1e-9) and close(exf["cash_before"] / ub[ck], exf["cash_after"] / ua2[ck], 1e-9))
    nvb = nav[(nav.book == b) & (nav.cost_bps == 20.8) & (nav.run == "strategy")].sort_values("date").reset_index(drop=True)
    k = int(nvb.index[nvb.date == pd.Timestamp(exx["trade_date"])][0])
    for r_ in nvb.loc[k - 2:k + 2].itertuples():
        chk(f"page prints NAV {r_.date.date()} {r_.nav:.6f}", f"<td>{r_.date.date()}</td><td>{r_.nav:.6f}</td>" in html)
    chk("example path numbers", ex["sessions"] == len(nvb) and close(ex["end_nav"], float(nvb.nav.iloc[-1])) and close(ex["cagr"], cagr(nvb.nav.values)) and close(ex["max_dd"], mdd(nvb.nav.values)))

    # every sleeve-trade row of the evidence (all books and costs): cost identity, split = target, value conservation for rebalances
    tot_a = sl.gold_value_after + sl.cash_value_after
    chk("sleeve_trades.csv: cost = traded x cost_bps / 2 / 10000 on every row", bool(((sl.cost - sl.traded * sl.cost_bps / 2 / 1e4).abs() <= 1e-9 * np.maximum(1, sl.traded)).all()))
    chk("sleeve_trades.csv: GOLDBEES share after the trade is the target weight on every row", bool(((sl.gold_value_after / tot_a - sl.gw_after).abs() < 1e-9).all()))
    chk("sleeve_trades.csv: a rebalance conserves value after cost on every row", bool((((sl.gold_value_before + sl.cash_value_before - sl.cost - tot_a).abs() < 1e-9) | (sl.kind != "sleeve_rebalance")).all()))
    # every stored F1 and F3 curve ends at its draw's end NAV
    cbad = 0
    for bk_ in BOOKS:
        for fam in ("F1", "F3"):
            en = dd(bk_, fam).end_nav.values
            for i_ in range(ND):
                cbad += int(abs(float(curves[f"{bk_}|{fam}_{i_}"][-1]) / en[i_] - 1) > 1e-5)
    chk("draw_curves_20.8.npz: every F1 and F3 curve ends at the end NAV of its draws.csv row", cbad == 0, f"{cbad} differ")

    # 6. every draw of every null, from the states; draws.csv columns recomputed
    nstate = nbad = 0
    for bk in BOOKS:
        for win in ("full", "live"):
            for kind, typ in (("io", "N4.9"), ("io", "N4.10"), ("gold", "N4.9-g"), ("gold", "N4.10-g")):
                A = ST.get(f"{bk}|{win}|{kind}|{typ}")
                chk(f"states {bk}|{win}|{kind}|{typ} present", A is not None)
                if A is None:
                    continue
                r_ = real[(win, kind)][bk]
                ka, kb_ = len(lens(r_, 1)), len(lens(r_, 0))
                sa, sb = int(r_.sum()), int(len(r_) - r_.sum())
                chk(f"states {bk}|{win}|{kind}|{typ} shape (draws, weeks)", A.shape[0] == ND and A.shape[1] == len(r_), str(A.shape))
                ha, hb = ((HI["in"], HI["out"]) if kind == "io" else (HI["buy"], HI["sell"]))
                ref = (sorted(lens(r_, 1)), sorted(lens(r_, 0)))
                for i in range(A.shape[0]):
                    la, lb = lens(A[i], 1), lens(A[i], 0)
                    ok = len(la) == ka and len(lb) == kb_ and sum(la) == sa and sum(lb) == sb and int(A[i, 0]) == int(r_[0])
                    if typ.startswith("N4.9"):
                        ok &= (sorted(la), sorted(lb)) == ref
                    else:
                        ok &= min(la) >= LO and max(la) <= ha and min(lb) >= LO and max(lb) <= hb
                    nstate += 1
                    nbad += int(not ok)
    chk(f"every draw of every null holds its table ({nstate} draws)", nstate > 0 and nbad == 0, f"{nbad} bad")
    # draws.csv: sleeve trades per draw, recomputed from the states (full window, LBES, 20.8, timed)
    for bk in BOOKS:
        e = dec[dec.book == bk].sort_values("j").reset_index(drop=True)
        tradable = [j for j in range(1, len(e)) if not pd.isna(e.trade_date[j])]

        def n_reb(s, g):
            return sum(1 for j in tradable if s[j - 1] == 0 and s[j] == 0 and g[j] != g[j - 1])
        for fam, kio, kg in (("F1", "io|N4.10", None), ("F2", "io|N4.9", None), ("F3", None, "gold|N4.10-g"), ("F4", None, "gold|N4.9-g")):
            A = ST[f"{bk}|full|{kio}"] if kio else None
            G = ST[f"{bk}|full|{kg}"] if kg else None
            exp = [n_reb(A[i].astype(int) if A is not None else rule[bk], G[i].astype(int) if G is not None else gold[bk]) for i in range(ND)]
            chk(f"{bk} {fam} sleeve_trades column equals the flips between OUT weeks, recomputed from the states", list(dd(bk, fam).sleeve_trades.values) == exp)

    # 7. page text carries the numbers as printed
    for b in BOOKS:
        pb = page["books"][b]
        for txt in (f"{pb['F1_pct_cagr']:.1f}", f"{pb['F1_pct_dd']:.1f}", f"{pb['F2_pct_cagr']:.1f}", f"{pb['F2_pct_dd']:.1f}", f"{pb['F3_pct_cagr']:.1f}", f"{pb['F3_pct_dd']:.1f}", f"{pb['F4_pct_cagr']:.1f}", f"{pb['F4_pct_dd']:.1f}",
                    f"{100 * pb['cagr']:.1f}%", f"{100 * pb['max_dd']:.1f}%", f"{pb['F1_p_cagr']:.3f}", f"{pb['F3_p_cagr']:.3f}", f"{pb['holm_C1']:.3f}", f"{pb['holm_C3']:.3f}", f"{pb['F1_live_pct']:.1f}", f"{pb['F3_live_pct']:.1f}"):
            chk(f"{b} page prints {txt}", txt in html)
    chk("page names the pre-registration hash", page["prereg_sha256"][:12] in html)
    chk("page hash equals T08.md header", page["prereg_sha256"] in Path(a.doc).read_text(encoding="utf-8"))
    chk("page prints the window", page["start"] in html and page["end"] in html and page["start_0007"] in html)
    chk("page prints the draws count", f"{ND:,}" in html)
    # the captions that changed with the rule (T06 hard-coded the 50/50 sleeve)
    for phr in ("80% when MAUc1 is BUY, 20% when SELL", "the first two are filled when the book holds the parent", "MAUc1-timed sleeve", "80/20 when the weekly MAUc1 gold supertrend is BUY", "Holm", "F3 and F4 keep the real switch",
                "T06's rule on this window", "plain 50/50 one", "Only C3 and C4 are the new claim", "GOLDBEES value ÷ units"):
        chk(f"page carries the caption '{phr}'", phr in text, phr)
    chk("page no longer says the rule's sleeve is 50/50 (T06's captions)", "in the 50/50 sleeve" not in text and "a 50/50 GOLDBEES and cash sleeve otherwise" not in text and "OUT → 50% GOLDBEES + 50% cash" not in text)
    # the held/randomised tables are T08.md's (parsed here on its own)
    docn = Path(a.doc).read_text(encoding="utf-8").replace("\r\n", "\n")
    for marker in ("**Null table, in-or-out nulls", "**Null table, gold nulls"):
        i = docn.index(marker)
        started, rows = False, []
        for l in docn[i:].split("\n")[1:]:
            if l.startswith("|"):
                started = True
                cells = [c.strip() for c in l.strip().strip("|").split("|")]
                if not all(set(c) <= set("-: ") for c in cells):
                    rows.append(cells)
            elif started:
                break
        chk(f"T08.md table '{marker}' parsed", len(rows) >= 8)
        for r_ in rows:
            for c in r_:
                chk(f"page carries the table cell '{c[:40]}'", re.sub(r"[*`]", "", c) in text, c[:60])

    # 8. the verifier and the gates
    vj = ev / "verify_t08.json"
    chk("verify_t08.json exists", vj.exists())
    if vj.exists():
        v = json.loads(vj.read_text(encoding="utf-8"))
        chk("verifier passed", bool(v.get("exit_ok")) and v.get("gate_failures_and_missing", 1) == 0, "verify_t08.json does not say passed")
        chk("verifier compared rows", v.get("gate_compared", 0) > 100000, str(v.get("gate_compared")))
        chk("verifier caught the corrupted copy", bool(v.get("selftest", {}).get("detected")))
    lp = logdir / "analysis.log"
    chk("analysis.log exists", lp.exists())
    if lp.exists():
        mg_ = re.search(r"^Gates: (\{.*\}) ->(.*)$", lp.read_text(encoding="utf-8"), re.M)
        chk("analysis.log has a Gates line", mg_ is not None)
        if mg_:
            g = ast.literal_eval(mg_.group(1))
            chk("all six gates pass in analysis.log", sorted(g) == ["V1", "V2", "V3", "V4", "V5", "V6"] and all(x == "PASS" for x in g.values()) and "ALL PASS" in mg_.group(2), mg_.group(0))
            chk("page's gates equal analysis.log's", page["gates"] == g)

    # 9a. regime chart hover
    bdd = page["best_draw"]
    bk = bdd["book"]
    q = lambda kind, c: nav[(nav.book == bk) & (nav.cost_bps == c) & (nav.run == kind)].sort_values("date").reset_index(drop=True)
    rq, pq_ = q("strategy", 20.8), q("hold_parent", 0.0)
    n10 = dd(bk, "F1")
    chk("regime section: draw is the highest-CAGR F1 draw of the book", close(float(n10[n10.draw_id == bdd["draw_id"]].cagr.iloc[0]), float(n10.cagr.max()), 1e-15) and close(bdd["cagr"], float(n10.cagr.max())))
    curve = curves[f"{bk}|F1_{bdd['draw_id']}"].astype(float)
    nses = len(rq)
    chk("hover: one entry per session", all(len(hv[k]) == nses for k in ("dates", "rule", "draw", "parent", "rs", "ds", "g", "gw", "tip")))
    chk("hover: dates are the NAV calendar", hv["dates"] == [d.strftime("%Y-%m-%d (%a)") for d in rq.date])
    chk("hover: rule NAV", np.abs(np.array(hv["rule"]) - rq.nav.values).max() < 6e-5)
    chk("hover: parent NAV (hold, 0 bps)", np.abs(np.array(hv["parent"]) - pq_.nav.values).max() < 6e-5)
    chk("hover: draw NAV is the stored curve of the page's draw", np.abs(np.array(hv["draw"]) - curve).max() < 6e-5)
    chk("curve ends at the draw's end NAV", close(float(curve[-1]), bdd["end_nav"], 1e-5))
    dcb = dec[dec.book == bk].sort_values("j").reset_index(drop=True)
    r_, d_ = rule[bk], ST[f"{bk}|full|io|N4.10"][bdd["draw_id"]].astype(int)
    first = np.array([0] + [nses - 1 if pd.isna(t) else int(rq.index[rq.date == pd.Timestamp(t)][0]) for t in dcb.trade_date.iloc[1:]])
    exp_r, exp_d, exp_g, exp_w = np.zeros(nses, int), np.zeros(nses, int), np.zeros(nses, int), np.zeros(nses)
    for j in range(len(d_)):
        end = first[j + 1] if j + 1 < len(d_) else nses - 1
        exp_r[first[j]:end], exp_d[first[j]:end] = r_[j], d_[j]
        exp_g[first[j]:end], exp_w[first[j]:end] = gold[bk][j], 0.8 if gold[bk][j] else 0.2
    exp_r[-1], exp_d[-1], exp_g[-1], exp_w[-1] = exp_r[-2], exp_d[-2], exp_g[-2], exp_w[-2]
    chk("hover: the rule's state each session", (np.array(hv["rs"]) == exp_r).all())
    chk("hover: the draw's state each session", (np.array(hv["ds"]) == exp_d).all())
    chk("hover: the MAUc1 signal each session (real, from the decisions)", (np.array(hv["g"]) == exp_g).all())
    chk("hover: the sleeve's GOLDBEES target weight each session", np.abs(np.array(hv["gw"]) - exp_w).max() < 1e-4)
    chk("hover: every session points at a stretch text", all(0 <= i < len(hv["tips"]) for i in hv["tip"]) and all(isinstance(t, str) and t for t in hv["tips"]))
    chk("regime chart has one overlay and one tooltip", html.count('id="regime-ov"') == 1 and html.count('id="regime-tip"') == 1)
    chk("regime chart has the six strips' labels", all(f">{lab}</text>" in html for lab in ("Rule", "They differ", "MAUc1 BUY", "Rule gold wt")))
    chk("regime table: weeks by what the two did", (bdd["weeks_both_in"], bdd["weeks_both_out"], bdd["weeks_draw_only"], bdd["weeks_rule_only"]) ==
        (int(((r_ == 1) & (d_ == 1)).sum()), int(((r_ == 0) & (d_ == 0)).sum()), int(((r_ == 0) & (d_ == 1)).sum()), int(((r_ == 1) & (d_ == 0)).sum())))
    chk("held: weeks invested equal and as printed", int(r_.sum()) == int(d_.sum()) == bdd["weeks_invested_rule"] == bdd["weeks_invested_draw"])
    chk("held: spell counts", (len(lens(r_, 1)), len(lens(r_, 0))) == (len(lens(d_, 1)), len(lens(d_, 0))) == (bdd["in_spells"], bdd["out_spells"]))
    chk("F1 draw: lengths within the bounds and as printed", bdd["draw_in"] == lens(d_, 1) and bdd["draw_out"] == lens(d_, 0) and min(lens(d_, 1)) >= LO and max(lens(d_, 1)) <= HI["in"] and min(lens(d_, 0)) >= LO and max(lens(d_, 0)) <= HI["out"])
    chk("held: entries and exits", (int(((r_[1:] == 1) & (r_[:-1] == 0)).sum()) + int(r_[0] == 1), int(((r_[1:] == 0) & (r_[:-1] == 1)).sum())) == (int(((d_[1:] == 1) & (d_[:-1] == 0)).sum()) + int(d_[0] == 1), int(((d_[1:] == 0) & (d_[:-1] == 1)).sum())) == (bdd["entries"], bdd["exits"]))
    chk("held: first state", r_[0] == d_[0])
    chk("sessions invested, rule and draw, as printed", (int(exp_r[:-1].sum()), int(exp_d[:-1].sum()), nses - 1) == (bdd["sessions_invested_rule"], bdd["sessions_invested_draw"], bdd["sessions_span"]))
    gdd = page["best_gold_draw"]
    ng = dd(bk, "F3")
    chk("best gold draw is the highest-CAGR F3 draw of the book", gdd["book"] == bk and close(float(ng[ng.draw_id == gdd["draw_id"]].cagr.iloc[0]), float(ng.cagr.max()), 1e-15) and close(gdd["cagr"], float(ng.cagr.max())) and close(gdd["end_nav"], float(ng[ng.draw_id == gdd["draw_id"]].end_nav.iloc[0])))
    gx = ST[f"{bk}|full|gold|N4.10-g"][gdd["draw_id"]].astype(int)
    tradable = [j for j in range(1, len(dcb)) if not pd.isna(dcb.trade_date[j])]
    fo = lambda g_: sum(1 for j in tradable if r_[j - 1] == 0 and r_[j] == 0 and g_[j] != g_[j - 1])
    chk("best gold draw: held and randomised dimensions as printed", (gdd["buy_weeks_real"], gdd["buy_weeks_draw"]) == (int(gold[bk].sum()), int(gx.sum())) and gdd["spells_real"] == [len(lens(gold[bk], 1)), len(lens(gold[bk], 0))]
        and gdd["spells_draw"] == [len(lens(gx, 1)), len(lens(gx, 0))] and gdd["draw_buy"] == lens(gx, 1) and gdd["draw_sell"] == lens(gx, 0) and gdd["flips_out_real"] == fo(gold[bk]) and gdd["flips_out_draw"] == fo(gx) == gdd["sleeve_trades_draw"]
        and min(lens(gx, 1)) >= LO and max(lens(gx, 1)) <= HI["buy"] and min(lens(gx, 0)) >= LO and max(lens(gx, 0)) <= HI["sell"] and gx[0] == gold[bk][0])

    # 9b. per-book growth-of-1 charts
    chk("line hover: one entry per book", sorted(lh) == sorted(BOOKS))
    chk("line charts: one hover overlay and one tooltip per book", html.count('class="lc-ov"') == len(BOOKS) and html.count('<div class="tip" hidden></div>') == len(BOOKS))
    for b in BOOKS:
        pick = lambda kind, c=20.8: nav[(nav.book == b) & (nav.cost_bps == c) & (nav.run == kind)].sort_values("date").reset_index(drop=True)
        cur = {k_: pick(k_) for k_ in KINDS}
        cur["published_D17"] = nav[(nav.book == b) & (nav.run == "published_D17")].sort_values("date").reset_index(drop=True)
        cl = cur["strategy"].date
        sel = np.unique(np.append(np.arange(0, len(cl), 5), len(cl) - 1))
        h = lh[b]
        chk(f"line hover {b}: series are the eight curves, in legend order", [s["k"] for s in h["series"]] == list(cur))
        chk(f"line hover {b}: plotted sessions", h["n"] == len(sel) and len(h["dates"]) == len(sel))
        chk(f"line hover {b}: dates are the NAV calendar", h["dates"] == [cl[i].strftime("%Y-%m-%d (%a)") for i in sel])
        for s in h["series"]:
            chk(f"line hover {b}: {s['k']} values", len(s["v"]) == len(sel) and np.abs(np.array(s["v"]) - cur[s["k"]].nav.values[sel]).max() < 6e-5)

    # 9c. bar charts
    want = {f"hist|{b}|{t}|{w}" for b in BOOKS for t in ("io", "gold") for w in ("cagr", "dd")} | {f"len|{b}|{s}" for b in BOOKS for s in ("in", "out", "buy", "sell")} | {"sampler|first", "sampler|first_g"}
    chk("bars-data holds exactly the expected charts", set(bd) == want, f"{sorted(set(bd) ^ want)}")
    chk("bar charts: one hover overlay and one tooltip each", html.count('class="bc-ov"') == len(want) and html.count('<div class="tip wrap" hidden></div>') == len(want))
    for b in BOOKS:
        pb = page["books"][b]
        s = st[(st.book == b) & (st.window == "full") & (st.cash == "lbes") & (st.cost_bps == 20.8) & (st.kind == "strategy")].iloc[0]
        for tim, fd, fb in (("io", "F1", "F2"), ("gold", "F3", "F4")):
            dd_d, dd_b = dd(b, fd), dd(b, fb)
            for what, col, mark in (("cagr", "cagr", float(s.cagr)), ("dd", "max_dd", float(s.max_dd))):
                h = bd[f"hist|{b}|{tim}|{what}"]
                ad, ab = dd_d[col].values, dd_b[col].values
                lo_, hi_ = float(min(ad.min(), ab.min(), mark)), float(max(ad.max(), ab.max(), mark))
                edges = np.linspace(lo_ - (hi_ - lo_) * 0.04, hi_ + (hi_ - lo_) * 0.04, 33)
                cd, cb = np.histogram(ad, bins=edges)[0], np.histogram(ab, bins=edges)[0]
                nm_ = f"hist {b} {tim} {what}"
                chk(f"{nm_}: edges", len(h["edges"]) == 33 and np.abs(np.array(h["edges"]) - edges).max() < 1e-7)
                sv = {x["k"]: x for x in h["series"]}
                chk(f"{nm_}: counts of both nulls", sv[fd]["v"] == [int(x) for x in cd] and sv[fb]["v"] == [int(x) for x in cb] and sv[fd]["n"] == sv[fb]["n"] == ND and sum(sv[fd]["v"]) == ND == sum(sv[fb]["v"]))
                mk = {m["label"]: m for m in h["marks"]}
                chk(f"{nm_}: marks are the rule and each null's median", close(mk["The rule"]["x"], mark, 1e-7) and close(mk[f"{fd} median"]["x"], float(np.median(ad)), 1e-7) and close(mk[f"{fb} median"]["x"], float(np.median(ab)), 1e-7))
                chk(f"{nm_}: the rule's percentiles in the tooltip", mk["The rule"]["txt"] == f"percentile {pctl(mark, ad)[0]:.1f} vs {fd}, {pctl(mark, ab)[0]:.1f} vs {fb}")
                fm = lambda v: f"{100 * v:.1f}%"
                chk(f"{nm_}: bin labels", h["binlab"] == [f"{fm(edges[i])} to {fm(edges[i + 1])}" for i in range(32)])
        for tim, fd, fb, kd, kb_, parts in (("io", "F1", "F2", "io|N4.10", "io|N4.9", (("in", 1, HI["in"], rin), ("out", 0, HI["out"], rout))), ("gold", "F3", "F4", "gold|N4.10-g", "gold|N4.9-g", (("buy", 1, HI["buy"], gbuy), ("sell", 0, HI["sell"], gsell)))):
            Ad, Ab = ST[f"{b}|full|{kd}"], ST[f"{b}|full|{kb_}"]
            for sx, v_, hi, rl_all in parts:
                h = bd[f"len|{b}|{sx}"]
                ld = np.array([x for i in range(Ad.shape[0]) for x in lens(Ad[i], v_)])
                lb = np.array([x for i in range(Ab.shape[0]) for x in lens(Ab[i], v_)])
                e_ = np.arange(LO, hi + 2) - 0.5
                sv = {x["k"]: x for x in h["series"]}
                nm_ = f"length chart {b} {sx}"
                chk(f"{nm_}: edges", np.abs(np.array(h["edges"]) - e_).max() < 1e-9)
                chk(f"{nm_}: counts", sv[fd]["v"] == [int(x) for x in np.histogram(ld, bins=e_)[0]] and sv[fb]["v"] == [int(x) for x in np.histogram(lb, bins=e_)[0]] and sv[fd]["n"] == len(ld) and sv[fb]["n"] == len(lb))
                rl = rl_all[b]
                chk(f"{nm_}: the shuffle's spikes are the real series' own lengths", sv[fb]["v"] == [ND * rl.count(x) for x in range(LO, hi + 1)])
                chk(f"{nm_}: tooltip notes the real series' spells", h["extra"] == [(f"The real series has {rl.count(x)} {sx}-spell(s) of exactly this length" if rl.count(x) else None) for x in range(LO, hi + 1)])
                chk(f"{nm_}: bin labels", h["binlab"] == [f"{x} weeks" for x in range(LO, hi + 1)])
    for did, kk, SSx, hi_, mark_x, key in (("sampler|first", kin, Sin, HI["in"], ex["steps"][0]["x"], "sampler_first"), ("sampler|first_g", kb, Sb, HI["buy"], ex["steps_g"][0]["x"], "sampler_first_g")):
        h = bd[did]
        chk(f"{did}: bars are the first-step weights", h["series"][0]["v"] == page[key]["weights"] and h["series"][0]["n"] == sum(page[key]["weights"]) and h["marks"][0]["x"] == float(mark_x))
    # the bars drawn in each SVG against the arrays in bars-data
    for did, h in bd.items():
        m = re.search(r'<svg[^>]*data-id="' + re.escape(did) + r'"[^>]*>(.*?)</svg>', html, re.S)
        chk(f"svg for {did} exists", m is not None)
        if not m:
            continue
        rects = re.findall(r'<rect x="([\d.]+)" y="([\d.]+)" width="([\d.]+)" height="([\d.]+)" fill="(#[0-9a-f]{6})" opacity="([\d.]+)"/>', m.group(1))
        ymaxax = h["ymax"]
        ytop = max(max(s["v"]) for s in h["series"])
        chk(f"{did}: y axis maximum is the top tick (or the tallest bar)", close(ymaxax, max(nice_ticks_max(ytop), ytop), 1e-9), f"{ymaxax} vs {ytop}")
        exp = [(s["col"], i, c) for s in h["series"] for i, c in enumerate(s["v"]) if c > 0]
        chk(f"{did}: one bar rectangle per non-empty bin and series ({len(exp)})", len(rects) == len(exp), f"{len(rects)} vs {len(exp)}")
        pw, ph = h["w"] - h["L"] - h["R"], h["h"] - h["T"] - h["B"]
        okb = True
        for (col, i, c), (rx, ry, rw, rh, rc, ro) in zip(exp, rects):
            xl = h["L"] + pw * (h["edges"][i] - h["x0"]) / (h["x1"] - h["x0"]) + 0.4
            hh = ph * c / ymaxax
            okb &= (rc == col and abs(float(rx) - xl) < 0.06 and abs(float(rh) - hh) < 0.06 and abs(float(ry) + float(rh) - (h["h"] - h["B"])) < 0.12)
        chk(f"{did}: every bar's position and height follow the arrays", okb)

    print(f"check_page: {n} checks, {len(fails)} failures")
    for f in fails[:40]:
        print("FAIL", f)
    sys.exit(0 if (n > 0 and not fails) else 1)


if __name__ == "__main__":
    main()
