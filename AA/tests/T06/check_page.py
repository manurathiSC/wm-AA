"""Independent check of the T06 results page. Imports nothing from the engine, verify_t06.py, analyse.py or report.py.

    python tests/T06/check_page.py [--run headline]                     exit 0 = every check passed; non-zero on any failure or if nothing was compared
    python tests/T06/check_page.py --evidence DIR [--out DIR] [--expect-draws N] [--t03 DIR]

1. Raw files -> decisions: re-derives every weekly decision (Friday reviews, the latest Master row on or before the date, all three BUY)
   from the approved Master files and the approved published NAVs' calendars (both located through its own parse of data/APPROVED_DATA.md,
   so a SUPERSEDED row is never read), and compares states, dates, spells, weeks and invested weeks with decisions.csv and the page.
2. Raw files -> published NAV: the page's published-NAV CAGR and worst fall for each book.
3. Inputs: every input the page lists is an APPROVED row (path, through-date, sha256 prefix) and the page's 'As of' date is the file's.
4. Page data -> evidence: every number in the page's embedded JSON (id="page-data"): the NAV curves in daily_nav.csv (CAGR, worst fall of the
   rule and each comparator), draws.csv (percentiles and p-values against BOTH nulls, medians, SDs, spreads, MDE, sessions invested, R1-R3,
   R4), stats.csv, T03's stored draws (the historical reference) and the verdict counts.
5. The sampler, from scratch: the number of allowed N4.10 tuples by an own DP and by inclusion-exclusion against count_table.json; the draw-0
   replay from default_rng([6, 0]) against the page's steps and against draw_states.npz.
6. Every draw of both nulls in draw_states.npz: weeks, first state, spell counts, sums, N4.9 sorted lengths, N4.10 bounds.
7. Page text carries the headline numbers as printed.
8. The verifier's result (verify_t06.json) and the gates in analysis.log.
9. Hover data: regime-data (every session's values and states, from draw_states.npz and the NAV files), lines-data (every plotted session
   of the five curves), bars-data (every bin of every histogram, spell-length chart and the sampler chart, from draws.csv and draw_states.npz,
   and the bar rectangles in the SVG against those arrays).
"""
import argparse
import ast
import itertools
import json
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


def spells(a):
    a = list(map(int, a))
    out = []
    for k, g in itertools.groupby(a):
        out.append((k, len(list(g))))
    return out


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


def replay(rid, k_in, S_in, hi_in, k_out, S_out, hi_out):
    rg = np.random.default_rng([6, rid])
    out = {}
    for nm, k, S, hi in (("in", k_in, S_in, hi_in), ("out", k_out, S_out, hi_out)):
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
    import math
    s = hi / k
    m = 10 ** math.floor(math.log10(s))
    r = s / m
    st = (1 if r < 1.5 else 2 if r < 3 else 5 if r < 7 else 10) * m
    v, last = 0.0, 0.0
    while v <= hi + 1e-9:
        last = v
        v += st
    return last


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="headline")
    ap.add_argument("--evidence", default=None)
    ap.add_argument("--out", default=None, help="directory of report.html and analysis.log")
    ap.add_argument("--expect-draws", type=int, default=2000)
    ap.add_argument("--t03", default=str(AA / "tests" / "T03" / "evidence" / "headline"))
    ap.add_argument("--doc", default=str(HERE / "T06.md"))
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
    t03 = Path(a.t03)
    ND = a.expect_draws
    html = (outdir / "report.html").read_text(encoding="utf-8")

    def block(i):
        return json.loads(re.search(rf'<script type="application/json" id="{i}">(.*?)</script>', html, re.S).group(1))

    page, hv, lh, bd = block("page-data"), block("regime-data"), block("lines-data"), block("bars-data")
    dec = pd.read_csv(ev / "decisions.csv")
    nav = pd.read_csv(ev / "daily_nav.csv", parse_dates=["date"])
    dr = pd.read_csv(ev / "draws.csv")
    st = pd.read_csv(ev / "stats.csv")
    z = np.load(ev / "draw_states.npz")
    ST = {k: z[k] for k in z.files}
    curves = np.load(ev / "draw_curves_20.8.npz")
    ct = json.loads((ev / "count_table.json").read_text(encoding="utf-8"))
    asof, arows = approved_rows()
    appr = [r for r in arows if r["status"] == "APPROVED"]

    # 1-2. raw files -> decisions and published NAV (files found through the APPROVED rows only)
    ms = {}
    for nme in ("Nifty100", "MC100", "SC100"):
        rr = [r for r in appr if r["file"].endswith(f"Master_{nme}.xlsx")]
        chk(f"one APPROVED Master row for {nme}", len(rr) == 1, str(len(rr)))
        d = pd.read_excel(AA / rr[0]["file"], parse_dates=["Date"])
        ms[nme] = d.dropna(subset=["SIGN"]).set_index("Date")["SIGN"].sort_index()
    cal, rule, rin, rout, ends = {}, {}, {}, {}, set()
    for b in BOOKS:
        rr = [r for r in appr if "parent_nav" in r["file"] and r["file"].replace("\\", "/").endswith(f"/{b}.csv")]
        chk(f"one APPROVED published-NAV row for {b}", len(rr) == 1, str(len(rr)))
        raw = pd.read_csv(AA / rr[0]["file"])
        raw["d"] = pd.to_datetime(raw["_id.date"], format="%Y/%m/%d")
        raw = raw.sort_values("d")
        c = pd.DatetimeIndex(raw.d.values)
        cal[b] = c
        ends.add(c[-1])
        iso = c.isocalendar()
        last = sorted(pd.Series(c, index=c).groupby([iso.year.values, iso.week.values]).max().values)
        dates = [c[0]] + [pd.Timestamp(x) for x in last if pd.Timestamp(x) > c[0]]
        sr = []
        for d_ in dates:
            ok = 1
            for s in ms.values():
                ok &= int(s.iloc[s.index.searchsorted(d_, side="right") - 1] == "BUY")
            sr.append(ok)
        rule[b] = np.array(sr)
        rin[b], rout[b] = lens(sr, 1), lens(sr, 0)
        e = dec[dec.book == b].sort_values("j")
        chk(f"{b} number of decisions", len(e) == len(dates) == page["weeks"][b], f"{len(e)} vs {len(dates)}")
        chk(f"{b} decision dates", list(pd.to_datetime(e.decision_date)) == dates)
        chk(f"{b} states", list(e.state) == sr, "state sequences differ")
        chk(f"{b} spells on the page", page["books"][b]["rule_in"] == rin[b] and page["books"][b]["rule_out"] == rout[b], f"{rin[b]} {rout[b]}")
        nvs = nav[(nav.book == b) & (nav.cost_bps == 20.8) & (nav.run == "strategy")].sort_values("date")
        chk(f"{b} NAV calendar is the published calendar", list(nvs.date) == list(c))
        r_ = raw["index"].values / raw["index"].values[0]
        chk(f"{b} published CAGR", close(page["books"][b]["pub_cagr"], cagr(r_)), f"{page['books'][b]['pub_cagr']} vs {cagr(r_)}")
        chk(f"{b} published worst fall", close(page["books"][b]["pub_dd"], mdd(r_)))
    chk("every book ends on the same published date, the page's end date", len(ends) == 1 and str(list(ends)[0].date()) == page["end"], f"{ends} {page['end']}")
    chk("start dates", page["start"] == str(cal["SCMO_0003"][0].date()) and page["start_0007"] == str(cal[B7][0].date()))
    HI_IN, HI_OUT = max(max(rin[b]) for b in BOOKS), max(max(rout[b]) for b in BOOKS)
    chk("bounds on the page are the rule's longest spells", page["bounds"] == {"lo": LO, "hi_in": HI_IN, "hi_out": HI_OUT}, str(page["bounds"]))

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
    for r in page["inputs"]:
        ar = byfile.get(r["file"].replace("\\", "/"))
        chk(f"input {r['file']} is a row of APPROVED_DATA.md", ar is not None)
        if ar is not None:
            chk(f"input {r['file']} is APPROVED, not superseded or pending", ar["status"] == "APPROVED", ar["status"])
            chk(f"input {r['file']} through-date", r["through"] == ar["through"], f"{r['through']} vs {ar['through']}")
            chk(f"input {r['file']} sha256 prefix", ar["sha"].startswith(r["sha16"][:len(ar["sha"])]) or r["sha16"].startswith(ar["sha"]), f"{r['sha16']} vs {ar['sha']}")
            if re.match(r"\d{4}-\d{2}-\d{2}$", ar["through"]) and all(w_ not in ar["file"] for w_ in ("holding_weight", "Rebalance_history", "mauc1")):
                chk(f"input {r['file']} covers the window end", ar["through"] >= page["end"], ar["through"])
            import html as _h
            chk(f"page's table row for {r['file']} shows its through-date, row and sha256 prefix", f"<tr><td>{_h.escape(r['file'])}</td><td>{_h.escape(ar['through'])}</td><td>{_h.escape(r['approved_row'])}</td><td>{_h.escape(r['sha16'])}</td></tr>" in html)

    # 4. page data -> evidence
    t03draws = None
    for b in BOOKS:
        pb = page["books"][b]
        cur = {}
        for kind, ck, dk in (("strategy", "cagr", "max_dd"), ("hold_parent", "hold_cagr", "hold_dd"), ("constant_mix", "mix_cagr", "mix_dd"), ("sleeve_only", "sleeve_cagr", "sleeve_dd")):
            v = nav[(nav.book == b) & (nav.cost_bps == 20.8) & (nav.run == kind)].sort_values("date").nav.values
            cur[kind] = v
            chk(f"{b} {kind} NAV starts at 1", close(v[0], 1.0, 1e-12))
            chk(f"{b} {kind} CAGR from NAV", close(pb[ck], cagr(v)), f"{pb[ck]} vs {cagr(v)}")
            chk(f"{b} {kind} worst fall from NAV", close(pb[dk], mdd(v)))
        sv = cur["strategy"]
        chk(f"{b} end NAV", close(pb["end_nav"], float(sv[-1])))

        def dd(win="full", cash="lbes", cost=20.8, typ="N4.10"):
            return dr[(dr.book == b) & (dr.window == win) & (dr.cash == cash) & (dr.cost_bps == cost) & (dr.draw_type == typ)].sort_values("draw_id")
        for nm, typ in (("n10", "N4.10"), ("n9", "N4.9")):
            nd = dd(typ=typ)
            chk(f"{b} {typ} draws count", len(nd) == ND and list(nd.draw_id) == list(range(ND)), str(len(nd)))
            p1, q1, w1, t1, b1 = pctl(cagr(sv), nd.cagr.values)
            p2, q2, *_ = pctl(mdd(sv), nd.max_dd.values)
            chk(f"{b} {typ} CAGR percentile and p", close(pb[f"{nm}_pct_cagr"], p1) and close(pb[f"{nm}_p_cagr"], q1) and (pb[f"{nm}_worse"], pb[f"{nm}_tied"], pb[f"{nm}_better"]) == (w1, t1, b1))
            chk(f"{b} {typ} drawdown percentile and p", close(pb[f"{nm}_pct_dd"], p2) and close(pb[f"{nm}_p_dd"], q2))
            chk(f"{b} {typ} medians", close(pb[f"{nm}_median_cagr"], float(nd.cagr.median())) and close(pb[f"{nm}_median_dd"], float(nd.max_dd.median())))
            chk(f"{b} {typ} SD and MDE", close(pb[f"{nm}_sd_cagr"], float(nd.cagr.std())) and close(pb[f"{nm}_mde_cagr_pp"], 280 * float(nd.cagr.std())) and close(pb[f"{nm}_mde_dd_pp"], 280 * float(nd.max_dd.std())) and close(pb[f"{nm}_sd_dd"], float(nd.max_dd.std())))
            q5, q95 = np.percentile(nd.cagr.values, [5, 95])
            chk(f"{b} {typ} 5th and 95th percentile of CAGR", close(pb[f"{nm}_p5_cagr"], float(q5)) and close(pb[f"{nm}_p95_cagr"], float(q95)))
            chk(f"{b} {typ} sessions invested summary", (pb[f"{nm}_sess_min"], pb[f"{nm}_sess_max"]) == (int(nd.sessions_invested.min()), int(nd.sessions_invested.max())) and close(pb[f"{nm}_sess_median"], float(nd.sessions_invested.median())))
            for c in (0.0, 50.0):
                vv = nav[(nav.book == b) & (nav.cost_bps == c) & (nav.run == "strategy")].sort_values("date").nav.values
                chk(f"{b} {typ} C1 percentile at {c}", close(pb[f"{nm}_pct_cagr_{c:g}"], pctl(cagr(vv), dd(cost=c, typ=typ).cagr.values)[0]))
                chk(f"{b} {typ} C2 percentile at {c}", close(pb[f"{nm}_pct_dd_{c:g}"], pctl(mdd(vv), dd(cost=c, typ=typ).max_dd.values)[0]))
            s_live = st[(st.book == b) & (st.window == "live") & (st.kind == "strategy")].iloc[0]
            chk(f"{b} {typ} live percentile", close(pb[f"{nm}_live_pct"], pctl(s_live.cagr, dd(win="live", typ=typ).cagr.values)[0]) and close(pb["live_cagr"], float(s_live.cagr)))
            s_liq = st[(st.book == b) & (st.cash == "liquidcase") & (st.kind == "strategy")].iloc[0]
            chk(f"{b} {typ} LIQUIDCASE percentile", close(pb[f"{nm}_liq_pct"], pctl(s_liq.cagr, dd(cash="liquidcase", typ=typ).cagr.values)[0]) and close(pb["liq_cagr"], float(s_liq.cagr)))
        # sessions invested of the rule, from the decisions and the calendar
        e = dec[dec.book == b].sort_values("j").reset_index(drop=True)
        cl = nav[(nav.book == b) & (nav.cost_bps == 20.8) & (nav.run == "strategy")].sort_values("date").date.values
        w0 = [0] + [len(cl) - 1 if pd.isna(t) else int(np.searchsorted(cl, np.datetime64(pd.Timestamp(t)))) for t in e.trade_date.iloc[1:]]
        ws = np.array(w0[1:] + [len(cl) - 1]) - np.array(w0)
        chk(f"{b} rule sessions invested and total", pb["rule_sessions"] == int(rule[b] @ ws) and pb["sessions_total"] == len(cl) - 1)
        # sessions_invested column recomputed from the saved states, every draw, both nulls
        for typ in ("N4.10", "N4.9"):
            chk(f"{b} {typ} sessions_invested column equals states @ sessions per week", bool((ST[f"{b}|full|{typ}"].astype(np.int64) @ ws == dd(typ=typ).sessions_invested.values).all()))
        s_row = st[(st.book == b) & (st.window == "full") & (st.cash == "lbes") & (st.cost_bps == 20.8) & (st.kind == "strategy")].iloc[0]
        chk(f"{b} cost paid and trades", close(pb["cost_paid"], float(s_row.cost_paid)) and pb["trades"] == int(s_row.trades))
        chk(f"{b} invested weeks equal the decisions'", int(s_row.invested_weeks) == int(rule[b].sum()))
    V = page["verdict"]
    cnt = lambda key: sum(page["books"][b][key] >= 90 for b in BOOKS)
    chk("verdict counts", (V["C1_N10"], V["C2_N10"], V["C1_N9"], V["C2_N9"], V["R3_live_N10"], V["R3_live_N9"], V["R2_liq_N10"], V["R2_liq_N9"]) ==
        (cnt("n10_pct_cagr"), cnt("n10_pct_dd"), cnt("n9_pct_cagr"), cnt("n9_pct_dd"), cnt("n10_live_pct"), cnt("n9_live_pct"), cnt("n10_liq_pct"), cnt("n9_liq_pct")))
    # historical reference: T03's stored N4.9 draws
    if (t03 / "draws.csv").exists():
        s3, d3 = pd.read_csv(t03 / "stats.csv"), pd.read_csv(t03 / "draws.csv")
        for b in BOOKS:
            sr = s3[(s3.book == b) & (s3.window == "full") & (s3.cash == "lbes") & (s3.cost_bps == 20.8) & (s3.kind == "strategy")].iloc[0]
            nd_ = d3[(d3.book == b) & (d3.window == "full") & (d3.cash == "lbes") & (d3.cost_bps == 20.8) & (d3.draw_type == "N4.9")]
            tr_ = page["t03_reference"].get(b)
            chk(f"{b} T03 historical reference", tr_ is not None and close(tr_["pct_cagr"], pctl(sr.cagr, nd_.cagr.values)[0]) and close(tr_["pct_dd"], pctl(sr.max_dd, nd_.max_dd.values)[0]) and close(tr_["cagr"], float(sr.cagr)))
    else:
        chk("T03 reference not checked (evidence not found); page must then carry none", page["t03_reference"] == {})

    # 5. the sampler from scratch
    cte = {}

    def walk(o, path=()):
        if isinstance(o, dict):
            if "n_ways" in o:
                toks = []
                for p_ in path:
                    toks += re.split(r"[|/ ]", p_)
                for f in ("book", "window", "state"):
                    if f in o:
                        toks.append(str(o[f]))
                bk = next((t for t in toks if t.startswith("SCMO_")), None)
                wn = next((t for t in toks if t in ("full", "live")), None)
                sx = next(({"in": "in", "1": "in", "out": "out", "0": "out"}[t.lower()] for t in toks if t.lower() in ("in", "out", "1", "0")), None)
                cte[(bk, wn, sx)] = {**o, "k": o.get("k", o.get("spells_k")), "S": o.get("S", o.get("weeks_S"))}
                return
            for k, v in o.items():
                walk(v, path + (str(k),))
        elif isinstance(o, list):
            for i, v in enumerate(o):
                walk(v, path + (str(i),))
    walk(ct)
    for b in BOOKS:
        for win in ("full", "live"):
            for sx, hi in (("in", HI_IN), ("out", HI_OUT)):
                e = cte.get((b, win, sx))
                chk(f"count_table entry {b}/{win}/{sx}", e is not None)
                if e:
                    chk(f"count_table {b}/{win}/{sx}: bounds", (int(e["lo"]), int(e["hi"])) == (LO, hi) and 2 * int(e["k"]) <= int(e["S"]) <= hi * int(e["k"]))
                    chk(f"count_table {b}/{win}/{sx}: n_ways = inclusion-exclusion = own DP", int(e["n_ways"]) == ways_ie(int(e["k"]), int(e["S"]), LO, hi) == dp(int(e["k"]), int(e["S"]), LO, hi)[int(e["k"])][int(e["S"])], str(e["n_ways"]))
                if win == "full" and e:
                    chk(f"count_table {b}/full/{sx}: k and S are the rule's", (int(e["k"]), int(e["S"])) == ((len(rin[b]), sum(rin[b])) if sx == "in" else (len(rout[b]), sum(rout[b]))))
    ex = page["example"]
    b = "SCMO_0003"
    k_in, S_in, k_out, S_out = len(rin[b]), sum(rin[b]), len(rout[b]), sum(rout[b])
    chk("example sampler parameters", (ex["k_in"], ex["S_in"], ex["hi_in"], ex["k_out"], ex["S_out"], ex["hi_out"]) == (k_in, S_in, HI_IN, k_out, S_out, HI_OUT))
    chk("example allowed-tuple counts", int(ex["ways_in"]) == int(ex["ways_in_table"]) == ways_ie(k_in, S_in, LO, HI_IN) and int(ex["ways_out"]) == int(ex["ways_out_table"]) == ways_ie(k_out, S_out, LO, HI_OUT))
    rp = replay(0, k_in, S_in, HI_IN, k_out, S_out, HI_OUT)
    mine = [(s_, p_) for s_, parts in (("in", rp["in"]), ("out", rp["out"])) for p_ in parts]
    chk("example replay: same number of steps", len(ex["steps"]) == len(mine) == k_in + k_out)
    for stp, (sp, (x, u, tot, wx)) in zip(ex["steps"], mine):
        chk("example replay step", stp["spell"] == sp and stp["x"] == x and close(stp["u"], u, 1e-12) and stp["total"] == tot and stp["ways_x"] == wx and close(stp["p"], wx / tot, 1e-9), str(stp))
    mine_in, mine_out = [p_[0] for p_ in rp["in"]], [p_[0] for p_ in rp["out"]]
    Z10 = ST[f"{b}|full|N4.10"]
    chk("example replay equals the stored draw 0 (states file)", mine_in == lens(Z10[0], 1) and mine_out == lens(Z10[0], 0), f"{mine_in} {mine_out} vs {lens(Z10[0], 1)} {lens(Z10[0], 0)}")
    chk("page says the replay equals the stored draw", ex["replay_ok"] is True and "replay equals the stored draw" in html)
    chk("first-step weights", page["sampler_first"]["weights"] == [dp(k_in, S_in, LO, HI_IN)[k_in - 1][S_in - x] if S_in - x >= 0 else 0 for x in range(LO, HI_IN + 1)] and sum(page["sampler_first"]["weights"]) == int(ex["ways_in"]))
    x10 = dr[(dr.book == b) & (dr.window == "full") & (dr.cash == "lbes") & (dr.cost_bps == 20.8) & (dr.draw_type == "N4.10") & (dr.draw_id == 0)].iloc[0]
    x9 = dr[(dr.book == b) & (dr.window == "full") & (dr.cash == "lbes") & (dr.cost_bps == 20.8) & (dr.draw_type == "N4.9") & (dr.draw_id == 0)].iloc[0]
    chk("example draw 0 numbers", close(ex["d0_n10_cagr"], float(x10.cagr)) and close(ex["d0_n10_dd"], float(x10.max_dd)) and ex["d0_n10_sessions"] == int(x10.sessions_invested) and close(ex["d0_n9_cagr"], float(x9.cagr)) and ex["d0_n9_sessions"] == int(x9.sessions_invested))
    chk("example draw 0 lengths in draws.csv equal the replay", str(x10.in_lengths) == "|".join(map(str, mine_in)) and str(x10.out_lengths) == "|".join(map(str, mine_out)))
    for key, nm, typ in (("rank10", "n10", "N4.10"), ("rank9", "n9", "N4.9")):
        rk = ex[key]
        nd = dr[(dr.book == b) & (dr.window == "full") & (dr.cash == "lbes") & (dr.cost_bps == 20.8) & (dr.draw_type == typ)]
        chk(f"example ranking against {typ} adds up", rk["worse"] + rk["tied"] + rk["better"] == rk["draws"] == ND == len(nd))
        chk(f"example percentile and p against {typ}", close(rk["percentile"], (rk["worse"] + 0.5 * rk["tied"]) / ND * 100) and close(rk["p"], (1 + rk["better"] + rk["tied"]) / (ND + 1)) and close(rk["percentile"], page["books"][b][f"{nm}_pct_cagr"]))
    chk("example cost = traded x 20.8/2/10000", close(ex["cost"], ex["traded"] * 20.8 / 2 / 10000, 1e-9))
    e0 = dec[dec.book == b].sort_values("j").reset_index(drop=True)
    j1 = int(e0.index[(e0.state != e0.state.shift()) & (e0.index > 0)][0])
    chk("example decision week and dates", ex["decision_week"] == j1 and ex["decision_date"] == str(e0.decision_date[j1]) and ex["trade_date"] == str(e0.trade_date[j1]))
    tr = pd.read_csv(ev / "trades.csv")
    tt = tr[(tr.book == b) & (tr.run == "strategy") & (tr.cost_bps == 20.8) & (tr.date == ex["trade_date"])].iloc[0]
    chk("example trade numbers", close(ex["V"], float(tt.V)) and close(ex["traded"], float(tt.traded)) and close(ex["cost"], float(tt.cost)) and close(ex["nav_after"], float(tt.nav_close_after)))

    # 6. every draw of both nulls, from the states
    nstate = nbad = 0
    for bk in BOOKS:
        for win in ("full", "live"):
            ref = None
            for typ in ("N4.9", "N4.10"):
                A = ST.get(f"{bk}|{win}|{typ}")
                chk(f"states {bk}|{win}|{typ} present", A is not None)
                if A is None:
                    continue
                chk(f"states {bk}|{win}|{typ} shape (draws, weeks)", A.shape[0] == ND and (win != "full" or A.shape[1] == len(rule[bk])), str(A.shape))
                kin, kout = int(cte[(bk, win, "in")]["k"]), int(cte[(bk, win, "out")]["k"])
                sin, sout = int(cte[(bk, win, "in")]["S"]), int(cte[(bk, win, "out")]["S"])
                for i in range(A.shape[0]):
                    li, lo_ = lens(A[i], 1), lens(A[i], 0)
                    ok = len(li) == kin and len(lo_) == kout and sum(li) == sin and sum(lo_) == sout and A[i, 0] == A[0, 0]
                    if win == "full":
                        ok &= int(A[i, 0]) == int(rule[bk][0])
                    if typ == "N4.9":
                        if ref is None:
                            ref = (sorted(li), sorted(lo_))
                        ok &= (sorted(li), sorted(lo_)) == ref
                        if win == "full":
                            ok &= ref == (sorted(rin[bk]), sorted(rout[bk]))
                    else:
                        ok &= min(li) >= LO and max(li) <= HI_IN and min(lo_) >= LO and max(lo_) <= HI_OUT
                    nstate += 1
                    nbad += int(not ok)
    chk(f"every draw of both nulls holds its table ({nstate} draws)", nstate > 0 and nbad == 0, f"{nbad} bad")

    # 7. page text carries the numbers as printed
    for b in BOOKS:
        pb = page["books"][b]
        for txt in (f"{pb['n10_pct_cagr']:.1f}", f"{pb['n10_pct_dd']:.1f}", f"{pb['n9_pct_cagr']:.1f}", f"{pb['n9_pct_dd']:.1f}", f"{100 * pb['cagr']:.1f}%", f"{100 * pb['max_dd']:.1f}%", f"{pb['n10_p_cagr']:.3f}", f"{pb['n10_live_pct']:.1f}"):
            chk(f"{b} page prints {txt}", txt in html)
    chk("page names the pre-registration hash", page["prereg_sha256"][:12] in html)
    chk("page hash equals T06.md header", page["prereg_sha256"] in Path(a.doc).read_text(encoding="utf-8"))
    chk("page prints the window", page["start"] in html and page["end"] in html and page["start_0007"] in html)
    chk("page prints the draws count", f"{ND:,}" in html)

    # 8. the verifier and the gates
    vj = ev / "verify_t06.json"
    chk("verify_t06.json exists", vj.exists())
    if vj.exists():
        v = json.loads(vj.read_text(encoding="utf-8"))
        chk("verifier passed", bool(v.get("exit_ok")) and v.get("gate_failures_and_missing", 1) == 0, "verify_t06.json does not say passed")
        chk("verifier compared rows", v.get("gate_compared", 0) > 100000, str(v.get("gate_compared")))
        chk("verifier caught the corrupted copy", bool(v.get("selftest", {}).get("detected")))
    lp = logdir / "analysis.log"
    chk("analysis.log exists", lp.exists())
    if lp.exists():
        mg = re.search(r"^Gates: (\{.*\}) ->(.*)$", lp.read_text(encoding="utf-8"), re.M)
        chk("analysis.log has a Gates line", mg is not None)
        if mg:
            g = ast.literal_eval(mg.group(1))
            chk("all five gates pass in analysis.log", sorted(g) == ["V1", "V2", "V3", "V4", "V5"] and all(x == "PASS" for x in g.values()) and "ALL PASS" in mg.group(2), mg.group(0))
            chk("page's gates equal analysis.log's", page["gates"] == g)

    # 9a. regime chart hover
    bdd = page["best_draw"]
    bk = bdd["book"]
    q = lambda kind, c: nav[(nav.book == bk) & (nav.cost_bps == c) & (nav.run == kind)].sort_values("date").reset_index(drop=True)
    rq, pq = q("strategy", 20.8), q("hold_parent", 0.0)
    n10 = dr[(dr.book == bk) & (dr.window == "full") & (dr.cash == "lbes") & (dr.cost_bps == 20.8) & (dr.draw_type == "N4.10")]
    chk("regime section: draw is the highest-CAGR N4.10 draw of the book", close(float(n10[n10.draw_id == bdd["draw_id"]].cagr.iloc[0]), float(n10.cagr.max()), 1e-15) and close(bdd["cagr"], float(n10.cagr.max())))
    curve = curves[f"{bk}|N4.10_{bdd['draw_id']}"].astype(float)
    nses = len(rq)
    chk("hover: one entry per session", all(len(hv[k]) == nses for k in ("dates", "rule", "draw", "parent", "rs", "ds", "tip")))
    chk("hover: dates are the NAV calendar", hv["dates"] == [d.strftime("%Y-%m-%d (%a)") for d in rq.date])
    chk("hover: rule NAV", np.abs(np.array(hv["rule"]) - rq.nav.values).max() < 6e-5)
    chk("hover: parent NAV (hold, 0 bps)", np.abs(np.array(hv["parent"]) - pq.nav.values).max() < 6e-5)
    chk("hover: draw NAV is the stored curve of the page's draw", np.abs(np.array(hv["draw"]) - curve).max() < 6e-5)
    chk("curve ends at the draw's end NAV", close(float(curve[-1]), bdd["end_nav"], 1e-5))
    dcb = dec[dec.book == bk].sort_values("j").reset_index(drop=True)
    r_, d_ = rule[bk], ST[f"{bk}|full|N4.10"][bdd["draw_id"]].astype(int)
    first = np.array([0] + [nses - 1 if pd.isna(t) else int(rq.index[rq.date == pd.Timestamp(t)][0]) for t in dcb.trade_date.iloc[1:]])
    exp_r, exp_d = np.zeros(nses, int), np.zeros(nses, int)
    for j in range(len(d_)):
        end = first[j + 1] if j + 1 < len(d_) else nses - 1
        exp_r[first[j]:end], exp_d[first[j]:end] = r_[j], d_[j]
    exp_r[-1], exp_d[-1] = exp_r[-2], exp_d[-2]
    chk("hover: the rule's state each session", (np.array(hv["rs"]) == exp_r).all())
    chk("hover: the draw's state each session", (np.array(hv["ds"]) == exp_d).all())
    chk("hover: every session points at a stretch text", all(0 <= i < len(hv["tips"]) for i in hv["tip"]) and all(isinstance(t, str) and t for t in hv["tips"]))
    chk("regime chart has one overlay and one tooltip", html.count('id="regime-ov"') == 1 and html.count('id="regime-tip"') == 1)
    chk("regime table: weeks by what the two did", (bdd["weeks_both_in"], bdd["weeks_both_out"], bdd["weeks_draw_only"], bdd["weeks_rule_only"]) ==
        (int(((r_ == 1) & (d_ == 1)).sum()), int(((r_ == 0) & (d_ == 0)).sum()), int(((r_ == 0) & (d_ == 1)).sum()), int(((r_ == 1) & (d_ == 0)).sum())))
    chk("held: weeks invested equal and as printed", int(r_.sum()) == int(d_.sum()) == bdd["weeks_invested_rule"] == bdd["weeks_invested_draw"])
    chk("held: spell counts", (len(lens(r_, 1)), len(lens(r_, 0))) == (len(lens(d_, 1)), len(lens(d_, 0))) == (bdd["in_spells"], bdd["out_spells"]))
    chk("N4.10 draw: lengths within the bounds and as printed", bdd["draw_in"] == lens(d_, 1) and bdd["draw_out"] == lens(d_, 0) and min(lens(d_, 1)) >= LO and max(lens(d_, 1)) <= HI_IN and min(lens(d_, 0)) >= LO and max(lens(d_, 0)) <= HI_OUT)
    chk("held: entries and exits", (int(((r_[1:] == 1) & (r_[:-1] == 0)).sum()) + int(r_[0] == 1), int(((r_[1:] == 0) & (r_[:-1] == 1)).sum())) == (int(((d_[1:] == 1) & (d_[:-1] == 0)).sum()) + int(d_[0] == 1), int(((d_[1:] == 0) & (d_[:-1] == 1)).sum())) == (bdd["entries"], bdd["exits"]))
    chk("held: first state", r_[0] == d_[0])
    chk("sessions invested, rule and draw, as printed", (int(exp_r[:-1].sum()), int(exp_d[:-1].sum()), nses - 1) == (bdd["sessions_invested_rule"], bdd["sessions_invested_draw"], bdd["sessions_span"]))

    # 9b. per-book growth-of-1 charts
    chk("line hover: one entry per book", sorted(lh) == sorted(BOOKS))
    chk("line charts: one hover overlay and one tooltip per book", html.count('class="lc-ov"') == len(BOOKS) and html.count('<div class="tip" hidden></div>') == len(BOOKS))
    for b in BOOKS:
        pick = lambda kind, c=20.8: nav[(nav.book == b) & (nav.cost_bps == c) & (nav.run == kind)].sort_values("date").reset_index(drop=True)
        cur = {"strategy": pick("strategy"), "hold_parent": pick("hold_parent"), "constant_mix": pick("constant_mix"), "sleeve_only": pick("sleeve_only"),
               "published_D17": nav[(nav.book == b) & (nav.run == "published_D17")].sort_values("date").reset_index(drop=True)}
        cl = cur["strategy"].date
        sel = np.unique(np.append(np.arange(0, len(cl), 5), len(cl) - 1))
        h = lh[b]
        chk(f"line hover {b}: series are the five curves, in legend order", [s["k"] for s in h["series"]] == list(cur))
        chk(f"line hover {b}: plotted sessions", h["n"] == len(sel) and len(h["dates"]) == len(sel))
        chk(f"line hover {b}: dates are the NAV calendar", h["dates"] == [cl[i].strftime("%Y-%m-%d (%a)") for i in sel])
        for s in h["series"]:
            chk(f"line hover {b}: {s['k']} values", len(s["v"]) == len(sel) and np.abs(np.array(s["v"]) - cur[s["k"]].nav.values[sel]).max() < 6e-5)

    # 9c. bar charts: histograms (both nulls), spell lengths, the sampler's first step
    want = {f"hist|{b}|{w}" for b in BOOKS for w in ("cagr", "dd")} | {f"len|{b}|{s}" for b in BOOKS for s in ("in", "out")} | {"sampler|first"}
    chk("bars-data holds exactly the expected charts", set(bd) == want, f"{sorted(set(bd) ^ want)}")
    chk("bar charts: one hover overlay and one tooltip each", html.count('class="bc-ov"') == len(want) and html.count('<div class="tip wrap" hidden></div>') == len(want))
    for b in BOOKS:
        pb = page["books"][b]
        s = st[(st.book == b) & (st.window == "full") & (st.cash == "lbes") & (st.cost_bps == 20.8) & (st.kind == "strategy")].iloc[0]
        d10 = dr[(dr.book == b) & (dr.window == "full") & (dr.cash == "lbes") & (dr.cost_bps == 20.8) & (dr.draw_type == "N4.10")].sort_values("draw_id")
        d9 = dr[(dr.book == b) & (dr.window == "full") & (dr.cash == "lbes") & (dr.cost_bps == 20.8) & (dr.draw_type == "N4.9")].sort_values("draw_id")
        for what, col, mark in (("cagr", "cagr", float(s.cagr)), ("dd", "max_dd", float(s.max_dd))):
            h = bd[f"hist|{b}|{what}"]
            a10, a9 = d10[col].values, d9[col].values
            lo_, hi_ = float(min(a10.min(), a9.min(), mark)), float(max(a10.max(), a9.max(), mark))
            edges = np.linspace(lo_ - (hi_ - lo_) * 0.04, hi_ + (hi_ - lo_) * 0.04, 33)
            c10, c9 = np.histogram(a10, bins=edges)[0], np.histogram(a9, bins=edges)[0]
            nm_ = f"hist {b} {what}"
            chk(f"{nm_}: edges", len(h["edges"]) == 33 and np.abs(np.array(h["edges"]) - edges).max() < 1e-7)
            sv = {x["k"]: x for x in h["series"]}
            chk(f"{nm_}: counts of both nulls", sv["n10"]["v"] == [int(x) for x in c10] and sv["n9"]["v"] == [int(x) for x in c9] and sv["n10"]["n"] == sv["n9"]["n"] == ND and sum(sv["n10"]["v"]) == ND == sum(sv["n9"]["v"]))
            mk = {m["label"]: m for m in h["marks"]}
            chk(f"{nm_}: marks are the rule and each null's median", close(mk["The rule"]["x"], mark, 1e-7) and close(mk["N4.10 median"]["x"], float(np.median(a10)), 1e-7) and close(mk["N4.9 median"]["x"], float(np.median(a9)), 1e-7))
            chk(f"{nm_}: the rule's percentiles in the tooltip", mk["The rule"]["txt"] == f"percentile {pctl(mark, a10)[0]:.1f} vs N4.10, {pctl(mark, a9)[0]:.1f} vs N4.9")
            fm = lambda v: f"{100 * v:.1f}%"
            chk(f"{nm_}: bin labels", h["binlab"] == [f"{fm(edges[i])} to {fm(edges[i + 1])}" for i in range(32)])
        for sx, v_, hi in (("in", 1, HI_IN), ("out", 0, HI_OUT)):
            h = bd[f"len|{b}|{sx}"]
            A10, A9 = ST[f"{b}|full|N4.10"], ST[f"{b}|full|N4.9"]
            l10 = np.array([x for i in range(A10.shape[0]) for x in lens(A10[i], v_)])
            l9 = np.array([x for i in range(A9.shape[0]) for x in lens(A9[i], v_)])
            e_ = np.arange(LO, hi + 2) - 0.5
            sv = {x["k"]: x for x in h["series"]}
            nm_ = f"length chart {b} {sx}"
            chk(f"{nm_}: edges", np.abs(np.array(h["edges"]) - e_).max() < 1e-9)
            chk(f"{nm_}: counts", sv["n10"]["v"] == [int(x) for x in np.histogram(l10, bins=e_)[0]] and sv["n9"]["v"] == [int(x) for x in np.histogram(l9, bins=e_)[0]] and sv["n10"]["n"] == len(l10) and sv["n9"]["n"] == len(l9))
            rl = rin[b] if sx == "in" else rout[b]
            chk(f"{nm_}: N4.9 spikes are the rule's own lengths", sv["n9"]["v"] == [ND * rl.count(x) for x in range(LO, hi + 1)])
            chk(f"{nm_}: tooltip notes the rule's spells", h["extra"] == [(f"The rule has {rl.count(x)} {sx}-spell(s) of exactly this length" if rl.count(x) else None) for x in range(LO, hi + 1)])
            chk(f"{nm_}: bin labels", h["binlab"] == [f"{x} weeks" for x in range(LO, hi + 1)])
    h = bd["sampler|first"]
    chk("sampler chart: bars are the first-step weights", h["series"][0]["v"] == page["sampler_first"]["weights"] and h["series"][0]["n"] == sum(page["sampler_first"]["weights"]) and h["marks"][0]["x"] == float(ex["steps"][0]["x"]))
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
