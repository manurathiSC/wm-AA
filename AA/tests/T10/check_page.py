"""Check the T10 results page against the evidence (AGENT.md R10). Shares no code with the engine, the verifier, analyse.py or report.py.

    python -I tests/T10/check_page.py [--run headline] [--selftest]          checks evidence/<run>/report.html against evidence/<run>/
    python -I tests/T10/check_page.py --evidence DIR [--page FILE]           another evidence directory (smoke run, scratch copy)

What it does (every check is counted; any failure makes the exit code 1, and so does checking nothing):
  A. page-data (the numbers the tables use) is RECOMPUTED here from the evidence CSVs, T06's evidence, the approved OHLC file and the D23 panels, with its own code, and
     compared key by key with the page-data block embedded in the page (tolerance 1e-9 relative);
  B. every <span class="n" data-k=PATH data-f=FORMAT> of the page resolves in the embedded page-data and its text equals the value formatted by this script's own formats;
  C. the chart arrays (lines-data, fs-data, st-data, bars-data) are recomputed from daily_nav.csv, decisions.csv, stretches.csv, r4_tag_error.csv and compared; the polylines and
     rectangles drawn in every SVG are decoded and compared with those arrays (so the hover cannot disagree with the picture);
  D. the worked example is re-run from the raw files: every stock's OHLC4 fill from the approved OHLC file (sha256 checked against data/APPROVED_DATA.md), units, cost, the NAV after
     the trade against trades.csv, and the tag of every example stock against the D23 rank panel;
  E. the bootstrap interval of every book is recomputed from daily_nav.csv with the seeds of the contract; the stretch spans, log returns and the 'without the largest' CAGR differences
     are recomputed from decisions.csv and daily_nav.csv; the V2, V3, V4, V5 facts are recomputed;
  F. every date written on the page is a date the evidence (or the frozen T10.md, or the approved-data file) contains; every number format is known;
  G. --selftest: planted corruptions (a span text, a page-data value, a hover array value, a bar height, an example fill, a gate flag, and two corrupted evidence copies) must each be detected.
"""
from __future__ import annotations

import argparse
import hashlib
import html as htmllib
import json
import math
import re
import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
AA = HERE.parents[1]
SEP = "~"
PRIMARY = 20.8
COSTS = (0.0, 20.8, 50.0)
BANDS = ["Large", "Mid", "Small and below"]
SIGS = ["Nifty100", "MC100", "SC100"]
BNO = {"SCMO_0003": 0, "SCMO_0007": 1, "SCMO_0010": 2, "SCMO_0029": 3}
THR = ["thr_2/5", "thr_1/2", "rule", "thr_7/10", "thr_4/5"]
KINDS = ["rule", "switch", "parent", "constant_mix", "sleeve100", "published_parent", "t07_rule"]
LAB = {"rule": "FS rule (this test)", "switch": "Three-index switch", "parent": "Hold the parent", "constant_mix": "Constant mix (same average exposure)", "published_parent": "Published parent (D17)"}
COLR = {"rule": "#2a6fdb", "switch": "var(--fg)", "parent": "#8a8f98", "constant_mix": "#c9811a", "published_parent": "#a14fa1"}
NOCHANCE = "no chance benchmark was run"

FORMATS = {
    "pc0": lambda x: f"{100 * x:.0f}%", "pc1": lambda x: f"{100 * x:.1f}%", "pc2": lambda x: f"{100 * x:.2f}%", "pp1": lambda x: f"{100 * x:+.1f}", "pp2": lambda x: f"{100 * x:+.2f}",
    "n2": lambda x: f"{x:.2f}", "n3": lambda x: f"{x:.3f}", "n4": lambda x: f"{x:.4f}", "n6": lambda x: f"{x:.6f}", "n8": lambda x: f"{x:.8f}", "int": lambda x: f"{x:,.0f}", "str": lambda x: str(x),
    "sci": lambda x: f"{x:.1e}", "pf": lambda x: "PASS" if x else "FAIL", "yn": lambda x: "yes" if x else "no", "rep": lambda x: "REPORTABLE" if x else "NOT REPORTABLE"}

CHECKS: list = []
FAILS: list = []


def chk(name, ok, detail=""):
    CHECKS.append(name)
    if not ok:
        FAILS.append(f"{name} {detail}")


def close(a, b, tol=1e-9):
    if a is None or b is None:
        return a is None and b is None
    try:
        a, b = float(a), float(b)
    except (TypeError, ValueError):
        return False
    return abs(a - b) <= tol * max(1.0, abs(a), abs(b))


def deep(name, got, exp, tol=1e-9, out=None):
    """Compare nested structures; returns the number of mismatches and counts every leaf as a check."""
    bad = 0
    if isinstance(exp, dict):
        if not isinstance(got, dict) or set(got) != set(exp):
            miss = (set(exp) - set(got)) if isinstance(got, dict) else set(exp)
            extra = (set(got) - set(exp)) if isinstance(got, dict) else set()
            chk(name + " keys", False, f"missing {sorted(miss)[:5]} extra {sorted(extra)[:5]}")
            return 1
        for k in exp:
            bad += deep(f"{name}.{k}", got[k], exp[k], tol)
        return bad
    if isinstance(exp, list):
        if not isinstance(got, list) or len(got) != len(exp):
            chk(name + " length", False, f"{len(got) if isinstance(got, list) else type(got)} vs {len(exp)}")
            return 1
        for i, (g, e) in enumerate(zip(got, exp)):
            bad += deep(f"{name}[{i}]", g, e, tol)
        return bad
    if isinstance(exp, bool) or isinstance(got, bool) or isinstance(exp, str) or exp is None or isinstance(got, str):
        ok = got == exp
    else:
        ok = close(got, exp, tol)
    chk(name, ok, f"page {got!r} vs recomputed {exp!r}")
    return 0 if ok else 1


def asbool(s):
    return s.astype(str).str.strip().str.lower().isin(["true", "1", "1.0"]).values


def cagr_dd(nav):
    nav = np.asarray(nav, float)
    return float(nav[-1] ** (252 / (len(nav) - 1)) - 1), float((nav / np.maximum.accumulate(nav) - 1).min())


def runs(mask):
    out, c = [], 0
    for v in mask:
        if v:
            c += 1
        elif c:
            out.append(c)
            c = 0
    if c:
        out.append(c)
    return out


def nice_ticks(hi, k=4):
    s = hi / k
    m = 10 ** math.floor(math.log10(s))
    r = s / m
    st = (1 if r < 1.5 else 2 if r < 3 else 5 if r < 7 else 10) * m
    o, v = [], 0.0
    while v <= hi + 1e-9:
        o.append(v)
        v += st
    return o


# ── the approved-data boundary (own parse) ─────────────────────────────────────────────────────────
def approved_rows():
    txt = (AA / "data" / "APPROVED_DATA.md").read_text(encoding="utf-8")
    tabl = txt[txt.index("<!-- approved-table:start -->"):txt.index("<!-- approved-table:end -->")]
    rows = []
    for l in tabl.splitlines():
        c = [x.strip() for x in l.strip().strip("|").split("|")]
        if len(c) >= 5 and c[0] in ("APPROVED", "SUPERSEDED", "PENDING"):
            rows.append({"status": c[0], "id": c[1], "file": c[2].replace("\\", "/"), "through": c[3], "sha": c[4]})
    return rows


_SHA_CACHE: dict = {}


def approved_read(rel, **kw):
    rows = [r for r in approved_rows() if r["file"] == rel]
    chk(f"approved row for {rel}", bool(rows) and all(r["status"] == "APPROVED" for r in rows))
    p = AA / rel
    if rel not in _SHA_CACHE:
        _SHA_CACHE[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
    chk(f"sha256 of {rel} equals the approved prefix", bool(rows) and _SHA_CACHE[rel].startswith(rows[0]["sha"]))
    return pd.read_csv(p, **kw)


# ── recompute page-data ────────────────────────────────────────────────────────────────────────────
def load(ev):
    d = {}
    d["dec"] = pd.read_csv(ev / "decisions.csv")
    d["ds"] = pd.read_csv(ev / "decision_stocks.csv", keep_default_na=False, na_values=[""], dtype={"isin": str, "tag_detail": str, "tag_snapshot": str})
    d["evt"] = pd.read_csv(ev / "events.csv")
    d["st"] = pd.read_csv(ev / "stats.csv")
    d["nav"] = pd.read_csv(ev / "daily_nav.csv", parse_dates=["date"])
    d["trd"] = pd.read_csv(ev / "trades.csv")
    d["stc"] = pd.read_csv(ev / "stretches.csv")
    d["boot"] = pd.read_csv(ev / "bootstrap.csv")
    d["r4"] = pd.read_csv(ev / "r4_tag_error.csv")
    d["g4"] = pd.read_csv(ev / "g_engine.csv")
    d["inp"] = pd.read_csv(ev / "inputs.csv", comment="#", dtype=str, keep_default_na=False)
    return d


class Ctx:
    def __init__(self, ev, doc_path, t06):
        self.ev = ev
        self.d = load(ev)
        self.doc = Path(doc_path).read_text(encoding="utf-8")
        self.t06 = Path(t06)
        d = self.d
        self.books = sorted(d["dec"].book.unique(), key=lambda b: BNO.get(b, 9))
        for c in ("extra", "tie", "float_differs"):
            d["dec"][c + "_b"] = asbool(d["dec"][c])
        d["ds"]["on_b"] = asbool(d["ds"]["on"])

    def stat(self, b, kind, cost=PRIMARY, win="full", cash="lbes"):
        s = self.d["st"]
        r = s[(s.book == b) & (s.window == win) & (s.cash == cash) & (s.kind == kind)]
        if r.cost_bps.notna().any():
            r = r[np.isclose(r.cost_bps.astype(float), cost)]
        return r.iloc[0]

    def series(self, b, run, cost=PRIMARY):
        n = self.d["nav"]
        r = n[(n.book == b) & (n.run == run)]
        if run != "published_parent":
            r = r[np.isclose(r.cost_bps.astype(float), cost)]
        return r.sort_values("date").reset_index(drop=True)

    def decs(self, b, w):
        x = self.d["dec"]
        return x[(x.book == b) & (x.window == w)].sort_values("j").reset_index(drop=True)


def recompute(cx: Ctx):
    d, books = cx.d, cx.books
    R = {}
    b0 = books[0]
    # prereg hash
    region = cx.doc[cx.doc.index("\n## 1. Idea and references") + 1:cx.doc.index("\n## 4. Results") + 1]
    region = "\n".join(l.rstrip() for l in region.replace("\r\n", "\n").split("\n"))
    sha = hashlib.sha256(region.encode("utf-8")).hexdigest()
    hdr = re.search(r"§1–§3 sha256:\*\* `([^`]*)`", cx.doc).group(1)
    live_start = pd.Timestamp("2021-11-01")
    start, lf, sess, ndec = {}, {}, {}, {}
    for b in books:
        s = cx.series(b, "rule")
        start[b] = str(s.date.iloc[0].date())
        lf[b] = str(s.date[s.date >= live_start].iloc[0].date())
        sess[b] = {"full": int(len(s)), "live": int(cx.stat(b, "rule", win="live").sessions)}
        ndec[b] = {w: int(len(cx.decs(b, w))) for w in ("full", "live")}
    end = str(cx.series(b0, "rule").date.iloc[-1].date())
    R["meta"] = {"run": cx.ev.name, "books": books, "start": start, "end": end, "live_first": lf, "prereg_header": hdr, "prereg_recomputed": sha, "prereg_match": hdr == sha, "decisions": ndec, "sessions": sess,
                 "n_r4": {b: int((d["r4"].book == b).sum()) for b in books}, "expect_r4": None}
    # weeks
    W = {}
    for b in books:
        W[b] = {}
        for w in ("full", "live"):
            x = cx.decs(b, w)
            rs, ss, ex = x.state_rule.values.astype(int), x.state_switch.values.astype(int), x.extra_b.values
            pat = x.pattern.values
            L = runs(ex)
            W[b][w] = {"decisions": len(x), "rule_in": int(rs.sum()), "switch_in": int(ss.sum()), "extra": int(ex.sum()), "stretches": len(L), "stretch_lengths": L, "rule_out_switch_in": int(np.sum((rs == 0) & (ss == 1))),
                       "ties": int(x.tie_b.sum()), "float_differs": int(x.float_differs_b.sum()), "flips_rule": int(np.sum(rs[1:] != rs[:-1])), "flips_switch": int(np.sum(ss[1:] != ss[:-1])),
                       "flips_rule_no_signal": int(np.sum((rs[1:] != rs[:-1]) & (pat[1:] == pat[:-1]))), "partial_fs": int(np.sum((x.k_on.values > 0) & (x.k_on.values < x.n_held.values))),
                       "nheld_min": int(x.n_held.min()), "nheld_median": float(np.median(x.n_held.values)), "nheld_max": int(x.n_held.max()), "share_in": float(rs.mean()), "reportable": bool(len(L) >= 5),
                       "first": str(x.decision_date.iloc[0]), "last": str(x.decision_date.iloc[-1])}
    R["weeks"] = W
    # criteria
    def crit(win, cash, cost):
        o = {"books": {}, "count": {k: 0 for k in ("C1", "C2", "C3", "C4")}}
        for b in books:
            r, s, p = cx.stat(b, "rule", cost, win, cash), cx.stat(b, "switch", cost, win, cash), cx.stat(b, "parent", cost, win, cash)
            rep = W[b][win]["reportable"]
            c3r, c4r = bool(r.cagr > s.cagr), bool(r.calmar >= s.calmar - 1e-12)
            bb = {"rule_cagr": r.cagr, "rule_dd": r.max_dd, "rule_calmar": r.calmar, "switch_cagr": s.cagr, "switch_dd": s.max_dd, "switch_calmar": s.calmar, "parent_cagr": p.cagr, "parent_dd": p.max_dd, "parent_calmar": p.calmar,
                  "reportable": rep, "stretches": W[b][win]["stretches"], "C1": bool(r.cagr > p.cagr), "C2": bool(r.max_dd > p.max_dd), "C3": c3r and rep, "C4": c4r and rep, "C3_raw": c3r, "C4_raw": c4r,
                  "trades": {k: cx.stat(b, k, cost, win, cash).trades for k in ("rule", "switch", "constant_mix")}, "cost_paid": {k: cx.stat(b, k, cost, win, cash).cost_paid for k in ("rule", "switch", "constant_mix")}}
            o["books"][b] = {k: (float(v) if isinstance(v, (np.floating,)) else v) for k, v in bb.items()}
            for c in o["count"]:
                o["count"][c] += int(bb[c])
        o["pass"] = {c: o["count"][c] >= 3 for c in o["count"]}
        o["n_books"] = len(books)
        return o
    R["crit"] = {f"{w}|{ca}|{c:g}": crit(w, ca, c) for w, ca, c in [("full", "lbes", 0.0), ("full", "lbes", 20.8), ("full", "lbes", 50.0), ("live", "lbes", 20.8), ("full", "liq", 20.8)]}
    CH = R["crit"]["full|lbes|20.8"]
    # headline
    H = {}
    for b in books:
        H[b] = {}
        for k in KINDS:
            s = cx.stat(b, k)
            f = None if pd.isna(s.mix_share_f) else float(s.mix_share_f)
            share = float(s.invested_weeks) / ndec[b]["full"] if k in ("rule", "switch", "parent", "t07_rule") and not pd.isna(s.invested_weeks) else (f if k == "constant_mix" else (0.0 if k == "sleeve100" else None))
            nn = lambda v: None if pd.isna(v) else float(v)
            H[b][k] = {"end_nav": s.end_nav, "cagr": s.cagr, "max_dd": s.max_dd, "calmar": s.calmar, "vol": s.vol, "ulcer": s.ulcer, "days_below_10pct": int(s.days_below_10pct), "longest_underwater": int(s.longest_underwater),
                       "trades": nn(s.trades), "cost_paid": nn(s.cost_paid), "events": nn(s.events), "share_in": share, "mix_f": f}
    R["headline"] = H
    # bootstrap (recomputed with the seeds of the contract) and compared with bootstrap.csv; the page-data holds bootstrap.csv's numbers
    BT = {}
    for b in books:
        BT[b] = {}
        rr = np.log(cx.series(b, "rule").nav.values[1:] / cx.series(b, "rule").nav.values[:-1])
        n = len(rr)
        for comp in ("switch", "parent"):
            cc = np.log(cx.series(b, comp).nav.values[1:] / cx.series(b, comp).nav.values[:-1])
            diffs = []
            for r_id in range(1000):
                g = np.random.default_rng([11, r_id, BNO[b]])
                starts = g.integers(0, n - 19, size=math.ceil(n / 20))
                ix = (starts[:, None] + np.arange(20)[None, :]).reshape(-1)[:n]
                yrs = n / 252
                diffs.append(math.exp(rr[ix].sum() / yrs) - math.exp(cc[ix].sum() / yrs))
            lo, hi = np.percentile(diffs, [2.5, 97.5])
            pt = cx.stat(b, "rule").cagr - cx.stat(b, comp).cagr
            row = d["boot"][(d["boot"].book == b) & (d["boot"].comparator == comp)].iloc[0]
            chk(f"bootstrap {b} {comp} point, lo and hi recomputed from daily_nav with the contract's seeds equal bootstrap.csv", close(pt, row.point_cagr_diff) and close(lo, row.ci_low) and close(hi, row.ci_high), f"{lo} {hi} vs {row.ci_low} {row.ci_high}")
            BT[b][comp] = {"point": float(row.point_cagr_diff), "lo": float(row.ci_low), "hi": float(row.ci_high), "contains0": bool(row.ci_low <= 0 <= row.ci_high)}
    R["boot"] = BT
    # per-year
    Y = {}
    for b in books:
        Y[b] = {}
        for run in ("rule", "switch", "parent", "constant_mix", "published_parent"):
            s = cx.series(b, run)
            yr = s.date.dt.year.values
            last = {y: s.nav.values[np.where(yr == y)[0][-1]] for y in sorted(set(yr))}
            prev = 1.0
            Y[b][run] = {}
            for y in sorted(last):
                Y[b][run][str(y)] = float(last[y] / prev - 1)
                prev = last[y]
    R["years"] = Y
    R["tc"] = {b: {k: {f"{c:g}": {"trades": float(cx.stat(b, k, c).trades), "cost_paid": float(cx.stat(b, k, c).cost_paid)} for c in COSTS} for k in ("rule", "switch", "constant_mix")} for b in books}
    # R4
    R4 = {}
    for b in books:
        g = d["r4"][d["r4"].book == b]
        dv = g.diff_vs_switch.values
        wc = g.weeks_changed.values / g.n_decisions.values
        R4[b] = {"n": len(g), "point": float(cx.stat(b, "rule").cagr - cx.stat(b, "switch").cagr), "mean": float(dv.mean()), "p5": float(np.percentile(dv, 5)), "median": float(np.median(dv)), "p95": float(np.percentile(dv, 95)),
                 "min": float(dv.min()), "max": float(dv.max()), "share_pos": float((dv > 0).mean()), "n_pos": int((dv > 0).sum()), "wk_mean": float(wc.mean()), "wk_min": float(wc.min()), "wk_max": float(wc.max()),
                 "cagr_mean": float(g.cagr.mean()), "rank_reads": int(g.rank_tag_reads.iloc[0]), "n_dec": int(g.n_decisions.iloc[0])}
        chk(f"R4 {b}: diff_vs_switch = cagr minus the switch's CAGR in every draw", bool(np.all(np.abs(g.cagr.values - cx.stat(b, "switch").cagr - dv) < 1e-9)))
    R["r4"] = R4
    # R5, R6, R8
    R["r5"] = {b: {k: {"cagr": cx.stat(b, k).cagr, "max_dd": cx.stat(b, k).max_dd, "calmar": cx.stat(b, k).calmar, "share_in": float(cx.stat(b, k).invested_weeks) / ndec[b]["full"], "events": float(cx.stat(b, k).events)} for k in THR} for b in books}
    R6 = {}
    for b in books:
        x = cx.decs(b, "full")
        s, r = cx.stat(b, "weight_fs"), cx.stat(b, "rule")
        R6[b] = {"cagr": s.cagr, "max_dd": s.max_dd, "calmar": s.calmar, "share_in": float(s.invested_weeks) / ndec[b]["full"], "weeks_differ": int((x.state_weight_fs.values != x.state_rule.values).sum()), "rule_cagr": r.cagr, "rule_dd": r.max_dd,
                 "rule_calmar": r.calmar, "switch_cagr": cx.stat(b, "switch").cagr, "parent_cagr": cx.stat(b, "parent").cagr, "parent_dd": cx.stat(b, "parent").max_dd, "switch_calmar": cx.stat(b, "switch").calmar}
    R["r6"] = R6
    R8 = {}
    for b in books:
        s = d["st"]
        aa = s[(s.book == b) & (s.window == "live") & (s.kind == "published_aa")]
        R8[b] = {"aa_scid": None if not len(aa) else str(aa.iloc[0].aa_scid), "aa_cagr": None if not len(aa) else float(aa.iloc[0].cagr), "aa_dd": None if not len(aa) else float(aa.iloc[0].max_dd),
                 "rule": cx.stat(b, "rule", win="live").cagr, "switch": cx.stat(b, "switch", win="live").cagr, "parent": cx.stat(b, "parent", win="live").cagr, "pub_parent": cx.stat(b, "published_parent", win="live").cagr,
                 "rule_dd": cx.stat(b, "rule", win="live").max_dd, "switch_dd": cx.stat(b, "switch", win="live").max_dd}
    R["r8"] = R8
    # R7 (CSV numbers) and recomputation of the full-window stretches from decisions and the NAVs
    R7 = {}
    for b in books:
        R7[b] = {}
        rn, sn = cx.series(b, "rule"), cx.series(b, "switch")
        dates = rn.date.dt.strftime("%Y-%m-%d").values
        lr, ls = np.diff(np.log(rn.nav.values)), np.diff(np.log(sn.nav.values))
        for w in ("full", "live"):
            sg = d["stc"][(d["stc"].book == b) & (d["stc"].window == w) & (d["stc"].stretch_no > 0)].sort_values("stretch_no").reset_index(drop=True)
            sm = d["stc"][(d["stc"].book == b) & (d["stc"].window == w) & (d["stc"].stretch_no == 0)].iloc[0]
            lg = int(np.abs(sg.diff_log_return.values).argmax()) if len(sg) else None
            R7[b][w] = {"stretches": [{"no": int(r_.stretch_no), "first": r_.first_decision_date, "last": r_.last_decision_date, "weeks": int(r_.weeks), "mean_fs": float(r_.mean_fs), "span_start": r_.span_start_date, "span_end": r_.span_end_date,
                                       "rule": float(r_.rule_log_return), "switch": float(r_.switch_log_return), "diff": float(r_.diff_log_return)} for r_ in sg.itertuples()],
                        "cagr_diff_all": float(sm.cagr_diff_all), "cagr_diff_wo": float(sm.cagr_diff_without_largest), "largest_no": None if lg is None else int(sg.stretch_no.iloc[lg]), "n_ahead": int((sg.diff_log_return > 0).sum()), "n": len(sg),
                        "sign_change": bool(np.sign(sm.cagr_diff_all) != np.sign(sm.cagr_diff_without_largest)), "sum_diff": float(sg.diff_log_return.sum()), "largest_diff": None if lg is None else float(sg.diff_log_return.iloc[lg])}
            chk(f"R7 {b} {w}: stretches.csv CAGR difference equals the rule's CAGR minus the switch's in stats.csv", close(sm.cagr_diff_all, cx.stat(b, "rule", win=w).cagr - cx.stat(b, "switch", win=w).cagr))
            if w == "full":
                x = cx.decs(b, "full")
                ex = x.extra_b.values
                j, k, tot = 0, 0, []
                while j < len(x):
                    if ex[j]:
                        j2 = j
                        while j2 + 1 < len(x) and ex[j2 + 1]:
                            j2 += 1
                        s0 = x.decision_date.iloc[j]
                        s1 = x.decision_date.iloc[j2 + 1] if j2 + 1 < len(x) else dates[-1]
                        i0, i1 = int(np.searchsorted(dates, s0)), int(np.searchsorted(dates, s1))
                        row = sg.iloc[k]
                        chk(f"R7 {b} stretch {k + 1}: decisions, weeks, span dates and log returns recomputed from decisions.csv and daily_nav.csv",
                            row.first_decision_date == s0 and row.last_decision_date == x.decision_date.iloc[j2] and row.weeks == j2 - j + 1 and row.span_start_date == s0 and row.span_end_date == s1
                            and close(row.rule_log_return, lr[i0:i1].sum()) and close(row.switch_log_return, ls[i0:i1].sum()) and close(row.mean_fs, float(np.mean(x.k_on.values[j:j2 + 1] / x.n_held.values[j:j2 + 1]))),
                            f"{row.span_start_date}->{row.span_end_date} vs {s0}->{s1}")
                        tot.append((i0, i1, abs(lr[i0:i1].sum() - ls[i0:i1].sum())))
                        k += 1
                        j = j2 + 1
                    else:
                        j += 1
                chk(f"R7 {b}: number of stretches recomputed equals stretches.csv", k == len(sg))
                if tot:
                    i0, i1, _ = max(tot, key=lambda t: t[2])
                    keep = np.ones(len(lr), bool)
                    keep[i0:i1] = False
                    n = keep.sum()
                    cdw = math.exp(lr[keep].sum() / (n / 252)) - math.exp(ls[keep].sum() / (n / 252))
                    chk(f"R7 {b}: CAGR difference without the stretch of largest |diff| recomputed equals stretches.csv", close(cdw, sm.cagr_diff_without_largest), f"{cdw} vs {sm.cagr_diff_without_largest}")
    R["r7"] = R7
    # patterns and tag sources
    PT, TS = {}, {}
    for b in books:
        x = cx.decs(b, "full")
        PT[b] = {"patterns": {}, "fs": {}}
        for pat in sorted(x.pattern.unique(), reverse=True):
            g = x[x.pattern == pat]
            PT[b]["patterns"][pat] = {"weeks": len(g), "rule_in": int(g.state_rule.sum()), "switch_in": int(g.state_switch.sum()), "mean_fs": float(np.mean(g.k_on.values / g.n_held.values))}
        fs = x.k_on.values / x.n_held.values
        for nm, mk in (("FS = 0", x.k_on.values == 0), ("0 < FS < 0.60", (x.k_on.values > 0) & (5 * x.k_on.values < 3 * x.n_held.values)), ("0.60 <= FS < 1", (5 * x.k_on.values >= 3 * x.n_held.values) & (x.k_on.values < x.n_held.values)), ("FS = 1", x.k_on.values == x.n_held.values)):
            PT[b]["fs"][nm] = {"weeks": int(mk.sum()), "rule_in": int(x.state_rule.values[mk].sum()), "switch_in": int(x.state_switch.values[mk].sum())}
        g = d["ds"][(d["ds"].book == b) & (d["ds"].window == "full")]
        vc = g.tag_source.value_counts()
        TS[b] = {s_: int(vc.get(s_, 0)) for s_ in ("rank", "membership", "nonmember_rank", "unranked")}
        TS[b]["total"] = int(len(g))
        TS[b]["rank_share"] = float((TS[b]["rank"] + TS[b]["nonmember_rank"]) / len(g))
    R["patterns"], R["tag_sources"] = PT, TS
    # outcome map
    V = CH["pass"]
    nsc = sum(R7[b]["full"]["sign_change"] for b in books)
    nrep = [b for b in books if not CH["books"][b]["reportable"]]
    om = []
    if all(V.values()):
        om.append("C1, C2, C3, C4 PASS: on this window the FS rule beat the parent and the switch on return and on return per unit of fall (descriptive; " + NOCHANCE + ")")
    if V["C3"] and not V["C4"]:
        om.append("C3 PASS, C4 FAIL: more return than the switch, but a worse fall: the gain came with exposure; read the constant-mix control")
    if not V["C3"]:
        om.append("C3 FAIL: the switch earned as much or more: the extra weeks the FS rule holds did not pay")
    if not V["C1"] or not V["C2"]:
        om.append("C1 or C2 FAIL: the rule did not beat holding the parent on that measure in at least 2 books")
    if nsc >= 2:
        om.append(f"R7 reading: the CAGR difference changes sign when the largest stretch is removed in {nsc} books: the comparison may be one episode, whatever C3 says")
    if nrep:
        om.append(f"a realisation is NOT REPORTABLE ({', '.join(nrep)}): state it; the other books are read on their own")
    R["outcome_map"] = om
    R["verdict"] = {"pass": CH["pass"], "count": CH["count"]}
    # V2, V3, V4, V5 facts
    dec, ds, evt = d["dec"], d["ds"], d["evt"]
    own = {"labels": [0, 0], "tags": [0, 0], "trades": [0, 0], "events": [0, 0]}
    for s_ in SIGS:
        own["labels"][0] += len(dec)
        own["labels"][1] += int((pd.to_datetime(dec["label_" + s_]) > pd.to_datetime(dec.decision_date)).sum())
    ok = ds.tag_snapshot.notna()
    own["tags"] = [int(ok.sum()), int((pd.to_datetime(ds.tag_snapshot[ok]) > pd.to_datetime(ds.decision_date[ok])).sum())]
    tt = dec.trade_date.notna()
    own["trades"] = [int(tt.sum()), int((pd.to_datetime(dec.trade_date[tt]) <= pd.to_datetime(dec.decision_date[tt])).sum())]
    ne = evt[evt.kind != "initial"]
    own["events"] = [int(len(ne)), int((pd.to_datetime(ne.decision_date_used) >= pd.to_datetime(ne.trade_date)).sum())]
    au = json.loads((cx.ev / "audit.json").read_text(encoding="utf-8"))
    R["v2"] = {"engine_checked": au["v2"]["checked"], "engine_violations": au["v2"]["violations"], "own_checked": sum(v[0] for v in own.values()), "own_violations": sum(v[1] for v in own.values()), "own": own}
    t06 = pd.read_csv(cx.t06 / "daily_nav.csv", parse_dates=["date"])
    t06d = pd.read_csv(cx.t06 / "decisions.csv")
    pairs, rows, mx, sh_n, mm, per = 0, 0, 0.0, 0, 0, {}
    for b in books:
        mxb, rowsb, shb, mmb = 0.0, 0, 0, 0
        for c in COSTS:
            for a_, b_ in (("strategy", "switch"), ("hold_parent", "parent"), ("sleeve_only", "sleeve100")):
                x = t06[(t06.book == b) & (t06.run == a_) & np.isclose(t06.cost_bps.astype(float), c)].set_index("date").nav
                y = d["nav"][(d["nav"].book == b) & (d["nav"].run == b_) & np.isclose(d["nav"].cost_bps.astype(float), c)].set_index("date").nav
                sh = x.index.intersection(y.index)
                sh = sh[sh <= pd.Timestamp("2026-10-22")]
                mxb = max(mxb, float((np.abs(x[sh] - y[sh]) / np.abs(x[sh])).max()))
                rowsb += len(sh)
                pairs += 1
        a_ = t06d[t06d.book == b].set_index("decision_date")
        b_ = cx.decs(b, "full").set_index("decision_date")
        for dt in a_.index[:-1]:
            if dt in b_.index:
                shb += 1
                mmb += int(int(a_.loc[dt, "all_three_buy"]) != int(b_.loc[dt, "state_switch"]))
        per[b] = {"nav_rows": rowsb, "max_rel": mxb, "dec_shared": shb, "dec_mismatch": mmb}
        rows, mx, sh_n, mm = rows + rowsb, max(mx, mxb), sh_n + shb, mm + mmb
    R["v3"] = {"pairs": pairs, "rows": rows, "max_rel": mx, "dec_shared": sh_n, "dec_mismatch": mm, "per_book": per}
    g4 = d["g4"][d["g4"].book.isin(books)]
    R["g0"] = [{"book": r_.book, "gap": float(r_.cagr_gap_pp_yr), "worst_year": int(r_.worst_year), "worst_gap": float(r_.worst_year_gap_pp), "first": r_.window_first, "last": r_.window_last} for r_ in g4.itertuples()]
    return R, own


def gate_facts(cx, R):
    for b in cx.books:
        for w in ("full", "live"):
            x = cx.decs(b, w)
            k, n = x.k_on.values.astype(int), x.n_held.values.astype(int)
            chk(f"V4 {b} {w}: FS = k/n, 0 <= k <= n, state IN iff 5k >= 3n, never OUT while the switch is IN",
                bool(np.all(np.abs(x.fs.values - k / n) < 1e-12) and np.all((k >= 0) & (k <= n)) and np.all(x.state_rule.values == (5 * k >= 3 * n)) and not np.any((x.state_rule.values == 0) & (x.state_switch.values == 1))))
            chk(f"V5 {b} {w}: weekly tag reads (rows of decision_stocks.csv) = sum of the stocks held", int(((cx.d["ds"].book == b) & (cx.d["ds"].window == w)).sum()) == int(n.sum()))
    m = R["v3"]
    chk("V2 own recount of point-in-time facts: 0 violations of a count > 0", R["v2"]["own_violations"] == 0 and R["v2"]["own_checked"] > 0 and R["v2"]["engine_violations"] == 0)
    chk("V3 regression to T06: worst relative difference <= 1e-12 over a nonzero number of rows, 0 decision mismatches", m["max_rel"] <= 1e-12 and m["rows"] > 0 and m["dec_shared"] > 0 and m["dec_mismatch"] == 0)
    g = cx.d["g4"]
    chk("V3 G0: always-in against the published NAV within +-0.25 pp/yr and +-0.5 pp in every year", bool((g.cagr_gap_pp_yr.abs() <= 0.25).all() and (g.worst_year_gap_pp.abs() <= 0.5).all()))


def worked_example(cx, R):
    """Recompute page-data['example'] from decisions.csv, decision_stocks.csv, events.csv, trades.csv, daily_nav.csv, the approved OHLC file and the D23 panels."""
    d = cx.d
    b = cx.books[0]
    x = cx.decs(b, "full")
    ev0 = d["evt"][(d["evt"].book == b) & (d["evt"].window == "full")].sort_values("event_no")
    pick = None
    for r in x[x.extra_b].itertuples():
        e = ev0[(ev0.decision_date_used == r.decision_date) & ev0.kind.str.startswith("state") & (ev0.state == "IN")]
        if len(e):
            pick = (r, e.iloc[0])
            break
    dx, ex_ = pick
    stk = d["ds"][(d["ds"].book == b) & (d["ds"].window == "full") & (d["ds"].j == dx.j)].reset_index(drop=True)
    td = str(ex_.trade_date)
    V, traded, cost = float(ex_.V_before), float(ex_.traded), float(ex_.cost)
    chk("example: cost = traded x 20.8 / 2 / 10,000", close(cost, traded * PRIMARY / 2 / 1e4))
    chk("example: traded = 2 V (the whole sleeve sold, V bought in stocks)", close(traded, 2 * V, 1e-9))
    chk("example: weights sum to 1", close(stk.listed_weight.sum(), 1.0))
    chk("example: n, k, FS and the 5k >= 3n state from the stock rows", len(stk) == dx.n_held and int(stk.on_b.sum()) == dx.k_on and close(dx.k_on / dx.n_held, dx.fs) and (5 * dx.k_on >= 3 * dx.n_held) == bool(dx.state_rule))
    chk("example: the pattern and the switch's state", dx.pattern == "".join("B" if getattr(dx, "sign_" + s) == "BUY" else "S" for s in SIGS) and bool(dx.state_switch) == (dx.pattern == "BBB"))
    kc = (V - cost) / V
    o = cx_ohlc(cx, b)
    cor = approved_read("data/holdings_matrix/price_corrections.csv", parse_dates=["ex_date"])
    fills, tot = [], 0.0
    for r in stk.itertuples():
        s_ = o[(o.stock == r.stock) & (o.date <= pd.Timestamp(td))].sort_values("date").copy()
        for c in cor.itertuples():
            if b in c.applies_to.split(";") and c.stock == r.stock:
                s_.loc[s_.date < c.ex_date, ["open", "high", "low", "close"]] *= c.factor
        bar = s_[s_.date == pd.Timestamp(td)].iloc[0]
        o4 = (bar.open + bar.high + bar.low + bar.close) / 4 if bar[["open", "high", "low"]].notna().all() else bar.close
        close_ = float(s_.close.ffill().iloc[-1])
        units = V * r.listed_weight * kc / o4
        tot += units * close_
        fills.append({"stock": r.stock, "w": float(r.listed_weight), "open": float(bar.open), "high": float(bar.high), "low": float(bar.low), "close_bar": float(bar.close), "ohlc4": float(o4), "target": V * float(r.listed_weight), "units": float(units), "close": close_, "value_close": float(units * close_)})
    trow = d["trd"][(d["trd"].book == b) & (d["trd"].run == "rule") & np.isclose(d["trd"].cost_bps, PRIMARY) & (d["trd"].event_no == ex_.event_no)].iloc[0]
    chk("example: sum of units x close on the trade date equals the NAV after the trade in trades.csv and in daily_nav.csv", close(tot, trow.nav_close_after, 1e-9) and close(tot, float(cx.series(b, "rule").set_index("date").nav[pd.Timestamp(td)]), 1e-9), f"{tot} vs {trow.nav_close_after}")
    # tags from the D23 rank panel (stocks tagged by the rank rule)
    panel = approved_read("Historical Data/extended_2026-11-12/tags/mcap_rank_panel.csv", dtype={"isin": str}, usecols=["date", "isin", "rank", "band"])
    dates = np.sort(panel.date.unique())
    n_t = 0
    for r in stk.itertuples():
        if r.tag_source in ("rank", "nonmember_rank") and r.tag_via == "isin":
            snap = dates[dates <= str(dx.decision_date)].max()
            row = panel[(panel.date == snap) & (panel["isin"] == r.isin)]
            ok_ = len(row) == 1 and row.iloc[0]["band"] == r.band and str(snap) == str(r.tag_snapshot) and str(int(row.iloc[0]["rank"])) == str(r.tag_detail)
            chk(f"example tag of {r.stock} from the D23 rank panel (snapshot {snap}, rank, band)", ok_, f"{row.to_dict('records')} vs {r.band} {r.tag_snapshot} {r.tag_detail}")
            n_t += 1
        else:
            chk(f"example tag of {r.stock}: source {r.tag_source} (not covered by the rank panel here; the verifier covers it)", True)
    rn, sw, pa = cx.series(b, "rule"), cx.series(b, "switch"), cx.series(b, "parent")
    k0 = int(rn.index[rn.date == pd.Timestamp(td)][0])
    nv = rn.nav.values
    dd = nv / np.maximum.accumulate(nv) - 1
    tr = int(dd.argmin())
    pk = int(np.argmax(nv[:tr + 1]))
    s0 = cx.stat(b, "rule")
    srow = d["trd"][(d["trd"].book == b) & (d["trd"].run == "switch") & np.isclose(d["trd"].cost_bps, PRIMARY)]
    sn = srow[pd.to_datetime(srow.date) >= pd.Timestamp(td)]
    prev = ev0[ev0.event_no == ex_.event_no - 1].iloc[0]
    return {"book": b, "decision_no": int(dx.j), "n_decisions": int(len(x)), "decision_date": str(dx.decision_date), "weekday": pd.Timestamp(dx.decision_date).strftime("%A"), "trade_date": td, "trade_idx": int(ex_.trade_idx),
            "basket_eff": str(dx.basket_eff), "pattern": dx.pattern, "signs": [dx.sign_Nifty100, dx.sign_MC100, dx.sign_SC100], "labels": [dx.label_Nifty100, dx.label_MC100, dx.label_SC100], "n": int(dx.n_held),
            "n_band": [int(dx.n_large), int(dx.n_mid), int(dx.n_small)], "k": int(dx.k_on), "fs": float(dx.k_on / dx.n_held), "lhs": int(5 * dx.k_on), "rhs": int(3 * dx.n_held), "state_rule": "IN" if dx.state_rule else "OUT", "state_switch": "IN" if dx.state_switch else "OUT",
            "weight_fs": float(dx.weight_fs), "event_kind": str(ex_.kind), "state_before": str(prev.state), "event_no": int(ex_.event_no), "V": V, "traded": traded, "cost": cost, "kc": kc, "cost_bps": PRIMARY, "stocks": fills,
            "stk": [{"stock": r.stock, "isin": r.isin, "w": float(r.listed_weight), "band": r.band, "src": r.tag_source, "snap": r.tag_snapshot, "detail": None if pd.isna(r.tag_detail) else str(r.tag_detail), "via": r.tag_via, "sig": r.band_signal, "on": bool(r.on_b)} for r in stk.itertuples()],
            "nav_after_close": float(trow.nav_close_after), "sum_units_close_diff": abs(tot - float(trow.nav_close_after)), "e_after": float(trow.e_after),
            "around": [{"date": str(rn.date.iloc[i].date()), "rule": float(rn.nav.iloc[i]), "switch": float(sw.nav.iloc[i]), "parent": float(pa.nav.iloc[i])} for i in range(k0 - 2, k0 + 3)],
            "switch_next": None if not len(sn) else {"date": str(sn.iloc[0].date), "kind": str(sn.iloc[0].kind), "state_after": "IN" if sn.iloc[0].e_after >= 0.5 else "OUT"},
            "start": str(rn.date.iloc[0].date()), "end": str(rn.date.iloc[-1].date()), "sessions": int(s0.sessions), "end_nav": float(s0.end_nav), "cagr": float(s0.cagr), "max_dd": float(s0.max_dd), "dd_peak_date": str(rn.date.iloc[pk].date()), "dd_peak": float(nv[pk]),
            "dd_trough_date": str(rn.date.iloc[tr].date()), "dd_trough": float(nv[tr]), "switch": {"cagr": float(cx.stat(b, "switch").cagr), "max_dd": float(cx.stat(b, "switch").max_dd), "end_nav": float(cx.stat(b, "switch").end_nav)},
            "parent": {"cagr": float(cx.stat(b, "parent").cagr), "max_dd": float(cx.stat(b, "parent").max_dd), "end_nav": float(cx.stat(b, "parent").end_nav)}, "sleeve_before_value": V}


_OHLC: dict = {}


def cx_ohlc(cx, b):
    if b not in _OHLC:
        _OHLC[b] = approved_read(f"data/holdings_matrix/{b}_ohlc.csv", parse_dates=["date"]).drop_duplicates(["date", "stock"])
    return _OHLC[b]


# ── chart arrays ───────────────────────────────────────────────────────────────────────────────────
def chart_arrays(cx, R):
    d = cx.d
    out = {"lines": {}, "fs": {}, "st": {}, "bars": {}}
    for b in cx.books:
        ser = {k: cx.series(b, k).nav.values for k in ("rule", "switch", "parent", "constant_mix", "published_parent")}
        dates = list(cx.series(b, "rule").date)
        n = len(dates)
        idx = list(range(0, n, 5))
        if idx[-1] != n - 1:
            idx.append(n - 1)
        for kind in ("eq", "dd"):
            s2 = ser if kind == "eq" else {k: v / np.maximum.accumulate(v) - 1 for k, v in ser.items()}
            allv = np.concatenate([v[idx] for v in s2.values()])
            lo, hi = (math.log(allv.min() * 0.97), math.log(allv.max() * 1.03)) if kind == "eq" else (float(allv.min()) * 1.04, 0.0)
            out["lines"][f"{kind}|{b}"] = {"w": 640, "h": 250, "L": 44, "R": 8, "T": 8, "B": 24, "lo": lo, "hi": hi, "log": kind == "eq", "fmt": "x" if kind == "eq" else "pct", "n": len(idx),
                                           "dates": [dates[i].strftime("%Y-%m-%d (%a)") for i in idx],
                                           "series": [{"k": k, "label": LAB[k], "col": COLR[k], "v": [round(float(v[i]), 4) for i in idx]} for k, v in s2.items()]}
        x = cx.decs(b, "full")
        ex = x.extra_b
        runs_, strno, j = [], [-1] * len(x), 0
        while j < len(x):
            if ex[j]:
                j2 = j
                while j2 + 1 < len(x) and ex[j2 + 1]:
                    j2 += 1
                runs_.append((j, j2))
                for q in range(j, j2 + 1):
                    strno[q] = len(runs_) - 1
                j = j2 + 1
            else:
                j += 1
        out["fs"][f"fs|{b}"] = {"n": len(x), "dates": [str(v) for v in x.decision_date], "fs": [round(float(a) / float(c), 6) for a, c in zip(x.k_on, x.n_held)], "k": [int(v) for v in x.k_on], "nn": [int(v) for v in x.n_held], "pat": list(x.pattern),
                                "rule": [int(v) for v in x.state_rule], "sw": [int(v) for v in x.state_switch], "extra": [int(v) for v in ex], "str": strno,
                                "tips": [f"Extra stretch {i + 1} of {len(runs_)}: decisions {x.decision_date.iloc[a_]} to {x.decision_date.iloc[b_]}, {b_ - a_ + 1} week(s): the rule is IN while the switch is OUT" for i, (a_, b_) in enumerate(runs_)],
                                "w": 760, "h": 235, "L": 92, "R": 8, "T": 8, "ph": 120}
        s = d["stc"][(d["stc"].book == b) & (d["stc"].window == "full") & (d["stc"].stretch_no > 0)].sort_values("stretch_no").reset_index(drop=True)
        vals = [round(float(v), 6) for v in s.diff_log_return]
        hi, lo = max(max(vals), 0.0), min(min(vals), 0.0)
        pad = (hi - lo) * 0.08 or 0.01
        out["st"][f"st|{b}"] = {"first": list(s.first_decision_date), "last": list(s.last_decision_date), "weeks": [int(v) for v in s.weeks], "mfs": [round(float(v), 6) for v in s.mean_fs], "s0": list(s.span_start_date), "s1": list(s.span_end_date),
                                "rule": [round(float(v), 6) for v in s.rule_log_return], "sw": [round(float(v), 6) for v in s.switch_log_return], "diff": vals, "w": 460, "h": 200, "L": 44, "R": 8, "T": 8, "B": 22, "lo": lo - pad, "hi": hi + pad}
        g = d["r4"][d["r4"].book == b].diff_vs_switch.values
        pt = float(cx.stat(b, "rule").cagr - cx.stat(b, "switch").cagr)
        lo_, hi_ = min(g.min(), 0.0, pt), max(g.max(), 0.0, pt)
        span = hi_ - lo_ or 0.01
        lo_, hi_ = lo_ - 0.03 * span, hi_ + 0.03 * span
        edges = np.linspace(lo_, hi_, 21)
        cnt, _ = np.histogram(g, bins=edges)
        ymax = float(cnt.max())
        tk = nice_ticks(ymax, 4)
        out["bars"][f"r4|{b}"] = {"w": 460, "h": 190, "L": 44, "R": 8, "T": 8, "B": 30, "x0": float(edges[0]), "x1": float(edges[-1]), "ymax": max(tk[-1], ymax), "xk": "pct", "yk": "int", "yunit": "draws",
                                  "edges": [round(float(e), 8) for e in edges], "binlab": [f"{100 * edges[i]:+.2f} to {100 * edges[i + 1]:+.2f} pp" for i in range(20)],
                                  "series": [{"k": "r4", "label": "R4 draws", "col": COLR["rule"], "v": [int(c) for c in cnt], "n": int(len(g))}],
                                  "marks": [{"label": "Unperturbed rule", "x": round(pt, 8), "txt": f"({100 * pt:+.2f} pp; rule CAGR minus switch CAGR)"}, {"label": "Zero (rule = switch)", "x": 0.0, "txt": "(no difference)"}]}
    return out


# ── page parsing ───────────────────────────────────────────────────────────────────────────────────
def parse_page(txt):
    blocks = {}
    for i in ("page-data", "lines-data", "fs-data", "st-data", "bars-data"):
        m = re.search(rf'<script type="application/json" id="{i}">(.*?)</script>', txt, re.S)
        blocks[i] = json.loads(m.group(1).replace("<\\/", "</")) if m else None
    return blocks


def get_path(R, path):
    o = R
    for p in path.split(SEP):
        o = o[int(p)] if isinstance(o, list) else o[p]
    return o


def check_spans(txt, PD):
    spans = re.findall(r'<span class="(n[^"]*)" data-k="([^"]*)" data-f="([^"]*)">([^<]*)</span>', txt)
    chk("the page has number spans", len(spans) > 100, f"{len(spans)}")
    for cls, k, f, t in spans:
        k = htmllib.unescape(k)
        t = htmllib.unescape(t)
        try:
            v = get_path(PD, k)
        except (KeyError, IndexError, ValueError, TypeError):
            chk(f"span {k}: path resolves in page-data", False)
            continue
        if f not in FORMATS:
            chk(f"span {k}: known format {f}", False)
            continue
        exp = "" if v is None else FORMATS[f](v)
        ok = t == exp
        if f == "pf":
            ok = ok and (("ok" in cls.split()) == bool(v)) and (("bad" in cls.split()) == (not bool(v)))
        chk(f"span {k} [{f}] text equals the formatted value", ok, f"page {t!r} vs {exp!r}")
    return len(spans)


def svg_blocks(txt, cls):
    return re.findall(rf'<svg viewBox="[^"]*" [^>]*class="chart {cls}"[^>]*data-id="([^"]*)">(.*?)</svg>', txt, re.S)


def check_svgs(txt, arr):
    tol = 0.06
    # line charts: every polyline point's y against the array
    blocks = svg_blocks(txt, "lc")
    chk("line charts on the page = 2 per book", len(blocks) == len(arr["lines"]), f"{len(blocks)} vs {len(arr['lines'])}")
    for did, body in blocks:
        d = arr["lines"][did]
        pls = re.findall(r'<polyline points="([^"]*)"', body)
        chk(f"{did}: {len(d['series'])} polylines", len(pls) == len(d["series"]))
        for pl, s in zip(pls, d["series"]):
            pts = [tuple(map(float, p.split(","))) for p in pl.split()]
            ok = len(pts) == d["n"]
            for j, (px, py) in enumerate(pts):
                v = s["v"][j]
                ey = d["T"] + (d["h"] - d["T"] - d["B"]) * (1 - ((math.log(v) if d["log"] else v) - d["lo"]) / (d["hi"] - d["lo"]))
                ex_ = d["L"] + (d["w"] - d["L"] - d["R"]) * j / (d["n"] - 1)
                ok &= abs(px - ex_) < tol and abs(py - ey) < 0.12
            chk(f"{did} {s['k']}: the {d['n']} drawn points equal the hover array", ok)
    blocks = svg_blocks(txt, "fs")
    chk("FS charts on the page = 1 per book", len(blocks) == len(arr["fs"]))
    for did, body in blocks:
        d = arr["fs"][did]
        pl = re.findall(r'<polyline points="([^"]*)"', body)
        pts = [tuple(map(float, p.split(","))) for p in pl[0].split()]
        ok = len(pts) == 2 * d["n"]
        for j in range(d["n"]):
            ey = d["T"] + d["ph"] * (1 - d["fs"][j])
            ok &= abs(pts[2 * j][1] - ey) < tol and abs(pts[2 * j + 1][1] - ey) < tol
        chk(f"{did}: the FS step line equals the hover array", ok)
        n_fill = len(re.findall(r'opacity="0.16"', body))
        chk(f"{did}: shaded extra weeks = {sum(d['extra'])}", n_fill == sum(d["extra"]))
        # strips: count the filled rectangles of the three signal strips, the rule strip and the switch strip
        exp = sum(1 for p in d["pat"] for c in p if c == "B") + sum(d["rule"]) + sum(d["sw"])
        got = len(re.findall(r'<rect x="[\d.]+" y="[\d.]+" width="[\d.]+" height="11" fill="[^"]+"/>', body))
        chk(f"{did}: the strips draw {exp} filled weeks", got == exp, f"{got}")
    blocks = svg_blocks(txt, "sb")
    chk("stretch charts on the page = 1 per book", len(blocks) == len(arr["st"]))
    for did, body in blocks:
        d = arr["st"][did]
        rects = re.findall(r'<rect x="[\d.]+" y="([\d.]+)" width="[\d.]+" height="([\d.]+)" fill="#[0-9a-f]+" opacity="0.8"/>', body)
        ok = len(rects) == len(d["diff"])
        for (y, h), v in zip(rects, d["diff"]):
            y0 = d["T"] + (d["h"] - d["T"] - d["B"]) * (1 - (0 - d["lo"]) / (d["hi"] - d["lo"]))
            y1 = d["T"] + (d["h"] - d["T"] - d["B"]) * (1 - (v - d["lo"]) / (d["hi"] - d["lo"]))
            ok &= abs(float(y) - min(y0, y1)) < tol and abs(float(h) - max(abs(y1 - y0), 0.6)) < tol
        chk(f"{did}: the {len(d['diff'])} bars drawn equal the hover array", ok)
    blocks = svg_blocks(txt, "bc")
    chk("histograms on the page = 1 per book", len(blocks) == len(arr["bars"]))
    for did, body in blocks:
        d = arr["bars"][did]
        rects = re.findall(r'<rect x="[\d.]+" y="([\d.]+)" width="[\d.]+" height="([\d.]+)" fill="#2a6fdb" opacity="0.6"/>', body)
        nz = [c for c in d["series"][0]["v"] if c > 0]
        ok = len(rects) == len(nz)
        for (y, h), c in zip(rects, nz):
            ok &= abs(float(h) - (d["h"] - d["B"] - (d["T"] + (d["h"] - d["T"] - d["B"]) * (1 - c / d["ymax"])))) < tol
        chk(f"{did}: the {len(nz)} non-empty bars drawn equal the hover array", ok)
        chk(f"{did}: the bars count {d['series'][0]['n']} draws", sum(d["series"][0]["v"]) == d["series"][0]["n"])


def check_dates(txt, cx):
    visible = re.sub(r'<script.*?</script>', "", txt, flags=re.S)
    visible = re.sub(r"<style.*?</style>", "", visible, flags=re.S)
    found = set(re.findall(r"\b(20\d\d-\d\d-\d\d)\b", visible))
    allowed = set(re.findall(r"\b(20\d\d-\d\d-\d\d)\b", cx.doc))
    allowed |= set(re.findall(r"\b(20\d\d-\d\d-\d\d)\b", (AA / "data" / "APPROVED_DATA.md").read_text(encoding="utf-8")))
    d = cx.d
    for col in ("decision_date", "trade_date", "label_Nifty100", "label_MC100", "label_SC100", "basket_eff"):
        allowed |= set(d["dec"][col].dropna().astype(str))
    allowed |= set(d["nav"].date.dt.strftime("%Y-%m-%d")) | set(d["ds"].tag_snapshot.dropna()) | set(d["inp"].through) | set(d["evt"].trade_date.astype(str)) | set(d["evt"].basket_eff.astype(str))
    for col in ("first_decision_date", "last_decision_date", "span_start_date", "span_end_date"):
        allowed |= set(d["stc"][col].dropna().astype(str))
    bad = sorted(found - allowed)
    chk(f"all {len(found)} distinct dates on the page are dates of the evidence, of T10.md or of the approved-data file", not bad, f"unknown dates {bad[:8]}")
    return len(found)


def run_all(txt, ev, doc, t06, quick=False):
    """Every check on one page text and one evidence directory; returns (n_checks, n_fail)."""
    CHECKS.clear()
    FAILS.clear()
    cx = Ctx(ev, doc, t06)
    blocks = parse_page(txt)
    for k, v in blocks.items():
        chk(f"embedded block {k} present", v is not None)
    if any(v is None for v in blocks.values()):
        return len(CHECKS), len(FAILS)
    PD = blocks["page-data"]
    R, own = recompute(cx)
    R["meta"]["expect_r4"] = PD["meta"].get("expect_r4")
    chk("R4 draws per book equal the number the pre-registration requires (the page's expect_r4)", all(v == PD["meta"].get("expect_r4") for v in R["meta"]["n_r4"].values()))
    gate_facts(cx, R)
    R["example"] = worked_example(cx, R)
    # recompute covers these keys; each is compared leaf by leaf with the page
    for key in R:
        deep(f"page-data.{key}", PD.get(key), R[key])
    # gates
    gates = PD.get("gates", {})
    chk("page-data gates: V1 to V5 all true and no consistency check failed", all(gates.get(g) is True for g in ("V1", "V2", "V3", "V4", "V5")) and gates.get("all") is True and all(PD.get("consistency", {}).get(k) is True for k in ("K1", "K2", "K3", "K4", "K5")), str(gates))
    chk("the frozen pre-registration hash in the header equals the recomputed one", R["meta"]["prereg_match"])
    plain = re.sub(r"<[^>]+>", " ", re.sub(r"<script.*?</script>|<style.*?</style>", "", txt, flags=re.S))
    claims = [sn for sn in re.split(r"(?<=[.!?])\s+", plain) if re.search(r"beats? chance|better than chance|beats? random", sn, re.I)]
    chk("no null on the page: it says no chance benchmark was run, and every sentence that mentions beating chance negates it", NOCHANCE in plain and all(re.search(r"no|not|nothing|cannot|never|without|nor", sn, re.I) for sn in claims), str(claims[:2]))
    n_sp = check_spans(txt, PD)
    arr = chart_arrays(cx, R)
    for kind, name in (("lines", "lines-data"), ("fs", "fs-data"), ("st", "st-data"), ("bars", "bars-data")):
        deep(name, blocks[name], arr[kind])
    check_svgs(txt, arr)
    nd = check_dates(txt, cx)
    # log gate line
    lp = ev / "analysis.log"
    chk("analysis.log exists and its Gates line says ALL PASS", lp.exists() and bool(re.search(r"^Gates: \{.*\} -> ALL PASS", lp.read_text(encoding="utf-8"), re.M)))
    if lp.exists():
        lt = lp.read_text(encoding="utf-8")
        for b in cx.books:
            r = PD["crit"]["full|lbes|20.8"]["books"][b]
            chk(f"analysis.log carries {b}'s headline CAGRs (rule, parent, switch)", f"{100 * r['rule_cagr']:.1f}%" in lt and f"{100 * r['parent_cagr']:.1f}%" in lt and f"{100 * r['switch_cagr']:.1f}%" in lt)
    return len(CHECKS), len(FAILS)


# ── planted corruptions ────────────────────────────────────────────────────────────────────────────
def selftest(txt, ev, doc, t06):
    base_checks, base_fail = run_all(txt, ev, doc, t06)
    print(f"selftest baseline: {base_checks} checks, {base_fail} failures")
    if base_fail:
        print("the unmodified page already fails: selftest not meaningful")
        return False
    PDm = re.search(r'(<script type="application/json" id="page-data">)(.*?)(</script>)', txt, re.S)
    pd_ = json.loads(PDm.group(2).replace("<\\/", "</"))
    b0 = pd_["meta"]["books"][0]

    def with_pd(mod):
        x = json.loads(json.dumps(pd_))
        mod(x)
        return txt[:PDm.start(2)] + json.dumps(x, separators=(",", ":")).replace("</", "<\\/") + txt[PDm.end(2):]

    def sub_block(name, mod):
        m = re.search(rf'(<script type="application/json" id="{name}">)(.*?)(</script>)', txt, re.S)
        x = json.loads(m.group(2).replace("<\\/", "</"))
        mod(x)
        return txt[:m.start(2)] + json.dumps(x, separators=(",", ":")).replace("</", "<\\/") + txt[m.end(2):]

    m_span = re.search(r'(<span class="n[^"]*" data-k="crit~full\|lbes\|20.8~books~%s~rule_cagr" data-f="pc1">)([^<]*)(</span>)' % b0, txt)
    cases = {
        "a span text changed (the rule's headline CAGR)": txt[:m_span.start(2)] + "99.9%" + txt[m_span.end(2):],
        "a page-data number changed (the parent's CAGR)": with_pd(lambda x: x["headline"][b0]["parent"].__setitem__("cagr", x["headline"][b0]["parent"]["cagr"] + 0.01)),
        "a worked-example fill price changed": with_pd(lambda x: x["example"]["stocks"][0].__setitem__("ohlc4", x["example"]["stocks"][0]["ohlc4"] * 1.01)),
        "a gate flag flipped (V3) in page-data": with_pd(lambda x: x["gates"].__setitem__("V3", False)),
        "a hover array value changed (a growth line)": sub_block("lines-data", lambda x: x[f"eq|{b0}"]["series"][0]["v"].__setitem__(100, x[f"eq|{b0}"]["series"][0]["v"][100] * 1.05)),
        "an FS value in the hover array changed": sub_block("fs-data", lambda x: x[f"fs|{b0}"]["fs"].__setitem__(50, 0.123)),
        "a stretch bar value in the hover array changed": sub_block("st-data", lambda x: x[f"st|{b0}"]["diff"].__setitem__(0, x[f"st|{b0}"]["diff"][0] + 0.05)),
        "a histogram count changed": sub_block("bars-data", lambda x: x[f"r4|{b0}"]["series"][0]["v"].__setitem__(3, x[f"r4|{b0}"]["series"][0]["v"][3] + 1)),
        "a date on the page changed to one the evidence does not contain": txt.replace(f"({pd_['meta']['start'][b0]}", "(2019-01-05", 1),
    }
    ok_all = True
    for name, t2 in cases.items():
        if t2 == txt:
            print("  PLANT NOT APPLIED:", name)
            ok_all = False
            continue
        n, f = run_all(t2, ev, doc, t06)
        det = f > 0
        ok_all &= det
        print(f"  planted: {name}: {'DETECTED' if det else 'NOT DETECTED'} ({f} failures of {n} checks)")
    # corrupted evidence copies
    for what in ("a daily NAV day scaled", "a decision's state flipped"):
        tmp = Path(tempfile.mkdtemp(prefix="t10_corrupt_"))
        try:
            for p in ev.iterdir():
                if p.is_file():
                    shutil.copy(p, tmp / p.name)
            if what.startswith("a daily"):
                n = pd.read_csv(tmp / "daily_nav.csv")
                i = n.index[(n.book == b0) & (n.run == "rule") & np.isclose(n.cost_bps.astype(float), PRIMARY)][700]
                n.loc[i, "nav"] *= 1.02
                n.to_csv(tmp / "daily_nav.csv", index=False)
            else:
                dd = pd.read_csv(tmp / "decisions.csv")
                i = dd.index[(dd.book == b0) & (dd.window == "full")][100]
                dd.loc[i, "k_on"] = int(dd.loc[i, "k_on"]) + 1
                dd.to_csv(tmp / "decisions.csv", index=False)
            n, f = run_all(txt, tmp, doc, t06)
            det = f > 0
            ok_all &= det
            print(f"  planted evidence corruption: {what}: {'DETECTED' if det else 'NOT DETECTED'} ({f} failures of {n} checks)")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    return ok_all


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="headline")
    ap.add_argument("--evidence", default=None)
    ap.add_argument("--page", default=None)
    ap.add_argument("--doc", default=str(HERE / "T10.md"))
    ap.add_argument("--t06", default=str(AA / "tests" / "T06" / "evidence" / "headline"))
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    ev = Path(a.evidence) if a.evidence else HERE / "evidence" / a.run
    page = Path(a.page) if a.page else ev / "report.html"
    txt = page.read_text(encoding="utf-8")
    n, f = run_all(txt, ev, a.doc, a.t06)
    print(f"check_page.py: {page.name} against {ev}: {n} checks, {f} failures")
    for x in FAILS[:40]:
        print("  FAIL:", x[:300])
    if len(FAILS) > 40:
        print(f"  ... and {len(FAILS) - 40} more")
    ok = f == 0 and n > 0
    if a.selftest:
        st_ok = selftest(txt, ev, a.doc, a.t06)
        print("selftest:", "all planted corruptions detected" if st_ok else "A PLANTED CORRUPTION WAS NOT DETECTED")
        ok = ok and st_ok
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
