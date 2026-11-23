"""Independent check of the T12 results page. Imports nothing from the engine, verify_t12.py, tag_lookup.py, analyse.py or report.py.
Fork of tests/T07/check_page.py (copied and rewritten where T12 differs).

    python tests/T12/check_page.py [--run headline]                     exit 0 = every check passed; non-zero on any failure or if nothing was compared
    python tests/T12/check_page.py --evidence DIR [--out DIR] [--expect-draws N] [--replay N]

1. Raw files -> decisions: re-derives the calendar (D26 sessions from T0 = 2014-09-01 to END = 2019-01-02) and every weekly decision (T0, then the last session
   of each ISO week; the latest Master row on or before the date) from the approved files (located through its own parse of data/APPROVED_DATA.md, so a
   SUPERSEDED or PENDING row is never read), and compares dates, the three SIGN cells and the disagree flag with decisions.csv and the NAV calendar.
2. Inputs: every input the page lists is a row of inputs.csv and an APPROVED row (path, through-date, sha256 prefix, sha256 of the file on disk, covering END);
   the D23b combined rank panel and the D26 calendar are among them; the page's 'As of' date is the file's; the caveats are the six of T12.md section 3.
3. The whole page-data block is recomputed from the evidence by its own code and compared key for key (a key it does not recompute is a failure): the rule's,
   the comparators' and the nulls' statistics, percentiles and p-values against both nulls, C3 and its bootstrap SE, R1-R7, V4 from regression.json, V6, V7,
   the MDE, the calibration ratio, the null spreads, weight by band, the tag sources, the allowed-subset counts, reportability, the stretches and their log
   points, T07's percentiles from T07's shipped evidence, T11's context if it exists, the episodes attribution, the verdict counts.
4. Tags from the raw panels: the tag of EVERY held stock at EVERY event of every window re-derived with its own lookup on the D23b rank panel and D22
   (latest snapshot on or before the information date; by ISIN or any ISIN sharing its quote_id; no rank -> Small and below, unranked); the R6 rows
   ('rank_linked') re-derived from the linked quote_id's rank and compared with r6_links.csv. The membership cutoff is asserted to lie after END.
5. The worked example: the targets, the cost, the allowed subsets by brute force, the N4.6 draw replayed from its seed against draw_drops.npz.
6. Every draw of both nulls in draw_drops.npz / draw_labels.npz holds its table; the first --replay N4.6 draws of every book and window replay from their seeds.
7. R7: every held stock-day (in the basket in force on the session or the one before) with |close / previous close - 1| >= 0.20 on the D26 calendar of the
   window, from D18 with price_corrections.csv, equals r7_flagged_days.csv.
8. Page text: the headline numbers as printed; the verifier's result and the gates in analysis.log; the caveats up front (rank tags, the two unranked
   holdings, month-old tags, no published NAV); every figure that draws 'hold the parent' says it is a rebuild with no published NAV before 2019-01-02.
9. Hover data: lines-data (every plotted session of every curve, and the gap curve), bars-data (every bin), band-data (every event), regime-data (every
   plotted session, every week, every event, every stretch text), and the rectangles drawn in the SVGs against those arrays.
"""
import argparse
import ast
import hashlib
import html as _html
import itertools
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
R6_BOOKS = ["SCMO_0007", "SCMO_0010"]
T0, END, R2_START = pd.Timestamp("2014-09-01"), pd.Timestamp("2019-01-02"), pd.Timestamp("2015-01-02")
SEED = 15
PARENT_NOTE = "rebuilt from the parent's baskets and Eikon prices; no published NAV exists before 2019-01-02"
SIGN3 = ["Nifty100", "MC100", "SC100"]
BANDN = ["Large", "Mid", "Small and below"]
fails, n = [], 0


def v6_xmax(K: int, p: float = 0.10, alpha: float = 0.05 / 4) -> int:
    """T12.md section 2, V6: largest X with P(Binomial(K, p) >= X) >= alpha (one-sided, 4 books). K = 100: 17. Own copy: this check is independent."""
    tail = 0.0
    for X in range(K, -1, -1):
        tail += math.comb(K, X) * p ** X * (1 - p) ** (K - X)
        if tail >= alpha:
            return X
    return K


def chk(name, ok, detail=""):
    global n
    n += 1
    if not ok:
        fails.append(f"{name}: {str(detail)[:300]}")


def close(a, b, tol=1e-9):
    if a is None or b is None:
        return a is None and b is None
    return abs(a - b) <= tol * max(1.0, abs(b))


def deep(name, got, exp, tol=1e-9):
    """Recursive comparison; one check per call, the differences listed."""
    bad = []

    def rec(p, g, e):
        if isinstance(e, dict):
            if not isinstance(g, dict) or set(g) != set(e):
                bad.append(f"{p}: keys differ {sorted(set(g) ^ set(e)) if isinstance(g, dict) else type(g)}")
                return
            for k in e:
                rec(f"{p}.{k}", g[k], e[k])
        elif isinstance(e, (list, tuple)):
            if not isinstance(g, (list, tuple)) or len(g) != len(e):
                bad.append(f"{p}: length {len(g) if hasattr(g, '__len__') else g} vs {len(e)}")
                return
            for i, (x, y) in enumerate(zip(g, e)):
                rec(f"{p}[{i}]", x, y)
        elif e is None or g is None:
            if not (e is None and g is None):
                bad.append(f"{p}: {g} vs {e}")
        elif isinstance(e, bool) or isinstance(g, bool):
            if bool(g) != bool(e):
                bad.append(f"{p}: {g} vs {e}")
        elif isinstance(e, str):
            if g != e:
                bad.append(f"{p}: {g!r} vs {e!r}")
        elif isinstance(e, (int, np.integer)) and isinstance(g, (int, np.integer)):
            if int(g) != int(e):
                bad.append(f"{p}: {g} vs {e}")
        else:
            if not close(float(g), float(e), tol):
                bad.append(f"{p}: {g} vs {e}")
    rec(name, got, exp)
    chk(name, not bad, "; ".join(bad[:4]) + (f" (+{len(bad) - 4} more)" if len(bad) > 4 else ""))
    return bad


def cagr(nv):
    return float(nv[-1] ** (252 / (len(nv) - 1)) - 1)


def mdd(nv):
    return float((nv / np.maximum.accumulate(nv) - 1).min())


def pctl(x, d, hb=True):
    tie = np.abs(d - x) <= 1e-12 * max(1.0, abs(x))
    worse = (d < x if hb else d > x) & ~tie
    better = (d > x if hb else d < x) & ~tie
    return {"percentile": float((worse.sum() + 0.5 * tie.sum()) / len(d) * 100), "p": float((1 + better.sum() + tie.sum()) / (len(d) + 1)), "worse": int(worse.sum()), "tied": int(tie.sum()),
            "better": int(better.sum()), "draws": int(len(d))}


def tf(s):
    return np.array([str(x).strip().lower() in ("true", "1", "1.0") for x in s])


def subset_sums(w):
    out = np.zeros(1)
    for x in w:
        out = np.concatenate([out, out + x])
    return out


def approved_rows():
    txt = (AA / "data" / "APPROVED_DATA.md").read_text(encoding="utf-8")
    asof = re.search(r"\*\*As of: (\d{4}-\d{2}-\d{2})", txt).group(1)
    tab = txt[txt.index("<!-- approved-table:start -->"):txt.index("<!-- approved-table:end -->")]
    rows = []
    for l in tab.splitlines():
        if l.startswith("|") and not l.startswith("|---") and not l.startswith("| Status"):
            c = [x.strip() for x in l.strip().strip("|").split("|")]
            rows.append({"status": c[0], "id": c[1], "file": c[2].replace("\\", "/"), "through": c[3], "sha": c[4]})
    return asof, rows


def norm_detail(x):
    x = "" if x is None or (isinstance(x, float) and math.isnan(x)) else str(x).strip()
    return str(int(float(x))) if re.fullmatch(r"\d+(\.0+)?", x) else x


def kind_of(before, after):
    if before == "SSS" and after == "BBB":
        return "Recovery"
    if before == "SSS" and after == "SSS":
        return "False start"
    if before == "BBB" and after == "SSS":
        return "Decline"
    if before == "BBB" and after == "BBB":
        return "Shake-out"
    return "Open at the window's edge"


def walk_dicts(o):
    if isinstance(o, dict):
        yield o
        for v in o.values():
            yield from walk_dicts(v)
    elif isinstance(o, list):
        for v in o:
            yield from walk_dicts(v)


def fkey(o, names):
    if isinstance(o, dict):
        for k_, v_ in o.items():
            if str(k_).lower() in names and not isinstance(v_, (dict, list)):
                return v_
        for v_ in o.values():
            r_ = fkey(v_, names)
            if r_ is not None:
                return r_
    if isinstance(o, list):
        for v_ in o:
            r_ = fkey(v_, names)
            if r_ is not None:
                return r_
    return None


def pass_flags(o):
    return [d["pass"] for d in walk_dicts(o) if isinstance(d.get("pass"), bool)]


def v4_own(reg):
    """Own reading of regression.json (evidence contract point 7), written independently of report.py's."""
    REL = ("max_rel_diff", "max_rel", "rel_diff", "max_relative_difference", "max_rel_difference", "worst_rel_diff")
    CNT = ("sessions", "dates_compared", "compared", "n_compared", "rows", "n", "sessions_compared")
    res = {}
    for part in ("v4a", "v4b"):
        blk = reg.get(part)
        r = {"present": blk is not None, "not_run": False, "reason": "", "comparisons": 0, "sessions": 0, "worst": 0.0, "bad": 0}
        if blk is not None:
            stt = fkey(blk, {"status"})
            if isinstance(stt, str) and "not run" in stt.lower():
                r["not_run"], r["reason"] = True, str(fkey(blk, {"reason"}) or "")
            for d in walk_dicts(blk):
                rel = [d[k] for k in REL if k in d and isinstance(d[k], (int, float)) and not isinstance(d[k], bool)]
                if not rel:
                    continue
                r["comparisons"] += 1
                r["worst"] = max(r["worst"], float(rel[0]))
                cn = [d[k] for k in CNT if k in d and isinstance(d[k], (int, float)) and not isinstance(d[k], bool)]
                if cn:
                    r["sessions"] += int(cn[0])
                    r["bad"] += int(cn[0] <= 0)
                r["bad"] += int(not (float(rel[0]) <= 1e-12))
            r["bad"] += sum(1 for x in pass_flags(blk) if not x)
        res[part] = r
    blk = reg.get("v4c")
    r = {"present": blk is not None, "functions": 0, "changed": 0, "unexpected": 0}
    if blk is not None:
        for d in walk_dicts(blk):
            if isinstance(d.get("expected"), bool):
                r["functions"] += 1
                r["changed"] += int(bool(d.get("changed", False)))
                r["unexpected"] += int(not d["expected"])
            for k in ("unexpected", "n_unexpected", "unexpected_changes"):
                if k in d and isinstance(d[k], (int, float)) and not isinstance(d[k], bool):
                    r["unexpected"] += int(d[k])
        r["unexpected"] += sum(1 for x in pass_flags(blk) if not x)
    if blk is not None:
        fn = blk.get("functions") if isinstance(blk, dict) else None
        if isinstance(fn, dict) and fn and all(isinstance(x, str) for x in fn.values()):
            r["functions"] += len(fn)
            r["changed"] += sum(1 for x in fn.values() if x.lower() == "changed")
        for k_ in ("unexpected_changes", "required_not_identical"):
            if isinstance(blk, dict) and isinstance(blk.get(k_), list):
                r["unexpected"] += len(blk[k_])
    res["v4c"] = r
    blk = reg.get("v4d")
    r = {"present": blk is not None, "compared": 0, "mismatches": 0}
    if blk is not None:
        r["compared"] = int(fkey(blk, {"compared", "checked", "n_compared", "tags_compared", "rows_checked", "rows", "n"}) or 0)
        r["mismatches"] = int(fkey(blk, {"mismatches", "n_mismatches", "differ", "failures"}) or 0) + sum(1 for x in pass_flags(blk) if not x)
    res["v4d"] = r
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="headline")
    ap.add_argument("--evidence", default=None)
    ap.add_argument("--out", default=None, help="directory of report.html and analysis.log")
    ap.add_argument("--expect-draws", type=int, default=2000)
    ap.add_argument("--doc", default=str(HERE / "T12.md"))
    ap.add_argument("--episodes", default=None)
    ap.add_argument("--t07", default=str(AA / "tests" / "T07" / "evidence" / "headline"))
    ap.add_argument("--t11", default=str(AA / "tests" / "T11" / "evidence" / "headline"))
    ap.add_argument("--books", default=None, help="comma list; for engine smoke runs that hold fewer than the four books")
    ap.add_argument("--replay", type=int, default=200, help="N4.6 draws per book and window replayed from their seeds")
    a = ap.parse_args()
    if a.books:
        BOOKS[:] = a.books.split(",")
    R6B = [b for b in R6_BOOKS if b in BOOKS]
    BNO = {"SCMO_0003": 0, "SCMO_0007": 1, "SCMO_0010": 2, "SCMO_0029": 3}
    ev_dir = Path(a.evidence) if a.evidence else HERE / "evidence" / a.run
    if a.out:
        logdir = outdir = Path(a.out)
    elif a.evidence:
        logdir = outdir = ev_dir
    else:
        logdir, outdir = HERE, ev_dir.parent
    ep_dir = Path(a.episodes) if a.episodes else ((ev_dir / "episodes") if a.evidence else HERE / "evidence" / "episodes")
    ND = a.expect_draws
    html = (outdir / "report.html").read_text(encoding="utf-8")

    def block(i):
        return json.loads(re.search(rf'<script type="application/json" id="{i}">(.*?)</script>', html, re.S).group(1))

    page, lh, bd, bnd, rgd = block("page-data"), block("lines-data"), block("bars-data"), block("band-data"), block("regime-data")
    dec = pd.read_csv(ev_dir / "decisions.csv", keep_default_na=False, na_values=[""])
    evt = pd.read_csv(ev_dir / "events.csv")
    esk = pd.read_csv(ev_dir / "event_stocks.csv", keep_default_na=False, na_values=[""], dtype={"isin": str, "tag_detail": str})
    st = pd.read_csv(ev_dir / "stats.csv")
    dr = pd.read_csv(ev_dir / "draws.csv")
    nav = pd.read_csv(ev_dir / "daily_nav.csv", parse_dates=["date"])
    DR = np.load(ev_dir / "draw_drops.npz")
    DROP = {k: DR[k] for k in DR.files}
    LB = np.load(ev_dir / "draw_labels.npz")
    asof, arows = approved_rows()
    appr = [r for r in arows if r["status"] == "APPROVED"]
    doc = Path(a.doc).read_text(encoding="utf-8")

    evt["pb"] = tf(evt["partial"])
    esk["kb"] = tf(esk["kept"])
    evt = evt.sort_values(["book", "window", "event_no"]).reset_index(drop=True)
    EV = {(b, w): g.reset_index(drop=True) for (b, w), g in evt.groupby(["book", "window"])}
    KEYS = [(b, w) for b in BOOKS for w in ("full", "r2")] + [(b, "full_r6") for b in R6B]
    for k in KEYS:
        chk(f"events exist for {k[0]}|{k[1]}", k in EV)
    ESK = {k: esk[(esk.book == k[0]) & (esk.window == k[1])].reset_index(drop=True) for k in KEYS}
    RI = {}
    for k, rows in ESK.items():
        pos = {int(x): i for i, x in enumerate(EV[k].event_no.values)}
        RI[k] = np.array([pos[int(x)] for x in rows.event_no.values])

    # ── 1. raw files -> calendar and decisions ────────────────────────────────
    ms = {}
    for nme in SIGN3:
        rr = [r for r in appr if r["file"].endswith(f"Master_{nme}.xlsx") and r["id"] == "D03"]
        chk(f"one APPROVED D03 Master row for {nme}", len(rr) == 1, str(len(rr)))
        d = pd.read_excel(AA / rr[0]["file"], parse_dates=["Date"])
        ms[nme] = d.dropna(subset=["SIGN"]).set_index("Date")["SIGN"].sort_index()
    rr = [r for r in appr if r["id"] == "D26" and r["file"].endswith("nse_trading_days.csv")]
    chk("one APPROVED D26 calendar row", len(rr) == 1, str(len(rr)))
    c_all = pd.to_datetime(pd.read_csv(AA / rr[0]["file"])["date"])
    c = pd.DatetimeIndex(c_all[(c_all >= T0) & (c_all <= END)].values)
    chk("the calendar starts at T0 and ends at END", c[0] == T0 and c[-1] == END, f"{c[0]} {c[-1]}")
    iso = c.isocalendar()
    last = sorted(pd.Series(c, index=c).groupby([iso.year.values, iso.week.values]).max().values)
    dates = [c[0]] + [pd.Timestamp(x) for x in last if pd.Timestamp(x) > c[0]]
    trip = [[str(s.iloc[s.index.searchsorted(d_, side="right") - 1]) for s in ms.values()] for d_ in dates]
    chk("the SC100 rows read are dated 2011-11-25 or later (rule 7)", all(ms["SC100"].index[ms["SC100"].index.searchsorted(d_, side="right") - 1] >= pd.Timestamp("2011-11-25") for d_ in dates))
    cal, dates_of, sg_of = {}, {}, {}
    for b in BOOKS:
        cal[b], dates_of[b], sg_of[b] = c, dates, trip
        e = dec[dec.book == b].sort_values("j").reset_index(drop=True)
        chk(f"{b} number of decisions", len(e) == len(dates) == page["weeks"][b], f"{len(e)} vs {len(dates)}")
        chk(f"{b} decision dates", list(pd.to_datetime(e.decision_date)) == dates)
        chk(f"{b} sign cells", [[e.loc[j, f"sign_{s}"] for s in SIGN3] for j in range(len(e))] == trip, "differ")
        chk(f"{b} disagree and all_three_buy flags", list(tf(e["disagree"])) == [len(set(t)) > 1 for t in trip] and list(tf(e["all_three_buy"])) == [all(x == "BUY" for x in t) for t in trip])
        chk(f"{b} trade dates are the next session (none after END)", [str(x) if not pd.isna(x) else "" for x in e.trade_date] == [str(c[c.get_loc(d_) + 1].date()) if c.get_loc(d_) + 1 < len(c) else "" for d_ in dates])
        nvs = nav[(nav.book == b) & (nav.cost_bps == 20.8) & (nav.run == "segment")].sort_values("date")
        chk(f"{b} NAV calendar is D26 from T0 to END", list(nvs.date) == list(c))
    r2f = c[c >= R2_START][0]
    chk("page's start, end and R2 first session", page["start"] == str(T0.date()) and page["end"] == str(END.date()) and page["r2_first"] == str(r2f.date()))
    for b in BOOKS:
        chk(f"{b} R2's first event is on the first session on or after 2015-01-02", str(EV[(b, "r2")].trade_date.iloc[0]) == str(r2f.date()) and str(EV[(b, "full")].trade_date.iloc[0]) == str(T0.date()))

    # ── 2. inputs and caveats ─────────────────────────────────────────────────
    chk("page's As-of date is APPROVED_DATA.md's", page["as_of_file"] == asof and asof in html, f"{page['as_of_file']} vs {asof}")
    au = json.loads((ev_dir / "audit.json").read_text(encoding="utf-8"))
    rec_ = None
    for l in (ev_dir / "inputs.csv").read_text(encoding="utf-8").splitlines():
        if l.startswith("#") and re.search(r"\d{4}-\d{2}-\d{2}", l):
            rec_ = re.search(r"\d{4}-\d{2}-\d{2}", l).group(0)
    if rec_ is None:
        rec_ = au.get("approved_data_as_of") or (au.get("data") or {}).get("approved_data_as_of")
    chk("the run recorded the same As-of date and the page prints it", page["as_of_inputs"] == rec_ == asof and rec_ in html, f"{page['as_of_inputs']} / {rec_} vs {asof}")
    byfile = {r["file"]: r for r in arows}
    inp_csv = pd.read_csv(ev_dir / "inputs.csv", comment="#", dtype=str, keep_default_na=False)
    chk("inputs listed", len(page["inputs"]) > 10, str(len(page["inputs"])))
    chk("the page lists exactly the rows of inputs.csv (file, through, approved row, sha256 prefix)", page["inputs"] == [{"file": r.file, "through": r.through, "approved_row": r.approved_row, "sha16": r.sha256[:16]} for r in inp_csv.itertuples()])
    files_ = {r["file"].replace("\\", "/") for r in page["inputs"]}
    chk("the D23b combined rank panel is an input", "Historical Data/extended_2026-11-17/mcap_universe_from_2013-12/mcap_rank_panel_from_2013-12.csv" in files_)
    chk("the D26 calendar is an input", "Historical Data/extended_2026-11-12/index_daily_pre2019/nse_trading_days.csv" in files_)
    chk("D23's own rank panel is not an input (the window needs D23b)", "Historical Data/extended_2026-11-12/tags/mcap_rank_panel.csv" not in files_)
    for r in page["inputs"]:
        f_ = r["file"].replace("\\", "/")
        full_sha = inp_csv[inp_csv.file == r["file"]].sha256.iloc[0]
        chk(f"input {f_} sha256 of the file on disk equals the run's record", (AA / f_).exists() and hashlib.sha256((AA / f_).read_bytes()).hexdigest() == full_sha)
        if f_.startswith("tests/"):
            continue   # stored evidence of a completed test (V4(a)); not a data row
        ar = byfile.get(f_)
        chk(f"input {f_} is a row of APPROVED_DATA.md", ar is not None)
        if ar is not None:
            chk(f"input {f_} is APPROVED, not superseded or pending", ar["status"] == "APPROVED", ar["status"])
            chk(f"input {f_} through-date", r["through"] == ar["through"], f"{r['through']} vs {ar['through']}")
            chk(f"input {f_} sha256 prefix", ar["sha"].startswith(r["sha16"][:len(ar["sha"])]) or r["sha16"].startswith(ar["sha"]), f"{r['sha16']} vs {ar['sha']}")
            if re.match(r"\d{4}-\d{2}-\d{2}$", ar["through"]) and all(w_ not in f_ for w_ in ("holding_weight", "Rebalance_history", "_columns", "_sources")):
                chk(f"input {f_} covers END", ar["through"] >= str(END.date()), ar["through"])
            chk(f"page's table row for {f_} shows its through-date, row and sha256 prefix",
                f"<tr><td>{_html.escape(r['file'])}</td><td>{_html.escape(ar['through'])}</td><td>{_html.escape(r['approved_row'])}</td><td>{_html.escape(r['sha16'])}</td></tr>" in html)
    i0 = doc.index("**Caveats of the tag data, to be stated on the page**")
    para = doc[i0:doc.index("\n", i0)].replace("\r", "").replace("**", "").replace("`", "").split("):", 1)[1]
    cav = [x.strip() for x in re.split(r"\s*\(\d\)\s*", para)[1:]]
    chk("the page's caveats are the six of T12.md section 3", page["caveats"] == cav and len(cav) == 6, str(len(cav)))
    for c_ in cav:
        chk("page prints a caveat", _html.escape(c_) in html)

    # ── 3. page-data recomputed ───────────────────────────────────────────────
    S = lambda b, kind="segment", cost=20.8, win="full", cash="lbes": st[(st.book == b) & (st.window == win) & (st.cash == cash) & (st.cost_bps == cost) & (st.kind == kind)].iloc[0]
    DD = lambda b, typ, cost=20.8, win="full", cash="lbes": dr[(dr.book == b) & (dr.window == win) & (dr.cash == cash) & (dr.cost_bps == cost) & (dr.draw_type == typ)].sort_values("draw_id")
    NV = lambda b, run, cost=20.8: nav[(nav.book == b) & (nav.cost_bps == cost) & (nav.run == run)].sort_values("date").nav.values
    nses = {b: len(cal[b]) for b in BOOKS}
    chk("page's draws", page["draws"] == ND == len(DD(BOOKS[0], "N4.6")), f"{page['draws']} {ND}")
    chk("page's run name", page["run"] == ev_dir.name)
    chk("page's hash is T12.md's header", page["prereg_sha256"] in doc and page["prereg_sha256"][:12] in html)
    chk("page's weeks", page["weeks"] == {b: len(sg_of[b]) for b in BOOKS})
    r7d = pd.read_csv(ev_dir / "r7_flagged_days.csv", dtype={"isin": str}) if (ev_dir / "r7_flagged_days.csv").exists() else None
    chk("r7_flagged_days.csv exists", r7d is not None)
    EXP = {}
    for b in BOOKS:
        s = S(b)
        vr, vw = NV(b, "segment"), NV(b, "whole_book")
        lr, lw_ = np.log(vr[1:] / vr[:-1]), np.log(vw[1:] / vw[:-1])
        T = len(lr)
        rg = np.random.default_rng([SEED, 20, BNO[b]])
        starts = rg.integers(0, T - 20 + 1, size=(1000, int(math.ceil(T / 20))))
        diffs = []
        for row in starts:
            ix = np.concatenate([np.arange(x, x + 20) for x in row])[:T]
            diffs.append(math.expm1(lr[ix].sum() / (T / 252)) - math.expm1(lw_[ix].sum() / (T / 252)))
        se = float(np.std(diffs, ddof=1))
        sw = S(b, "whole_book")
        bb = {"cagr": cagr(vr), "max_dd": mdd(vr), "end_nav": float(vr[-1]), "trades": int(s.trades), "cost_paid": float(s.cost_paid), "sessions_total": nses[b] - 1, "events": len(EV[(b, "full")]),
              "whole_cagr": cagr(vw), "whole_dd": mdd(vw), "whole_trades": int(sw.trades), "whole_cost": float(sw.cost_paid), "c3_diff": cagr(vr) - cagr(vw), "c3_se": se}
        chk(f"{b} stats.csv's rule and whole-book CAGR equal the daily NAV's", close(float(s.cagr), cagr(vr)) and close(float(sw.cagr), cagr(vw)) and close(float(s.max_dd), mdd(vr)))
        for run, kk in (("parent", "parent"), ("constant_mix", "mix"), ("sleeve100", "sleeve")):
            v = NV(b, run)
            bb[f"{kk}_cagr"], bb[f"{kk}_dd"] = cagr(v), mdd(v)
        for cc in (0.0, 50.0):
            bb[f"c3_diff_{cc:g}"] = cagr(NV(b, "segment", cc)) - cagr(NV(b, "whole_book", cc))
        for win in ("full", "r2"):
            d_ = dec[dec.book == b].sort_values("j")
            dis = tf(d_["disagree"])
            if win == "r2":
                dis = dis[(pd.to_datetime(d_.decision_date) >= r2f).values]
            runs_ = [(k, len(list(g))) for k, g in itertools.groupby(dis)]
            nst = sum(1 for k, _ in runs_ if k)
            npart = int(EV[(b, win)].pb.sum())
            bb[f"{win}_stretches"], bb[f"{win}_partial"], bb[f"{win}_events"], bb[f"{win}_weeks"], bb[f"{win}_dis_weeks"] = nst, npart, len(EV[(b, win)]), len(dis), int(dis.sum())
            bb[f"{win}_reportable"] = nst >= 5 and npart >= 6
        for nm, typ in (("n46", "N4.6"), ("n48", "N4.8")):
            nd = DD(b, typ)
            chk(f"{b} {typ} draws count and ids", len(nd) == ND and list(nd.draw_id) == list(range(ND)), str(len(nd)))
            rc, rd = pctl(cagr(vr), nd.cagr.values), pctl(mdd(vr), nd.max_dd.values)
            bb.update({f"{nm}_median_cagr": float(nd.cagr.median()), f"{nm}_median_dd": float(nd.max_dd.median()), f"{nm}_pct_cagr": rc["percentile"], f"{nm}_p_cagr": rc["p"], f"{nm}_pct_dd": rd["percentile"], f"{nm}_p_dd": rd["p"],
                       f"{nm}_worse": rc["worse"], f"{nm}_tied": rc["tied"], f"{nm}_better": rc["better"], f"{nm}_sd_cagr": float(np.std(nd.cagr.values, ddof=1)), f"{nm}_sd_dd": float(np.std(nd.max_dd.values, ddof=1)),
                       f"{nm}_mde_cagr_pp": 280 * float(np.std(nd.cagr.values, ddof=1)), f"{nm}_mde_dd_pp": 280 * float(np.std(nd.max_dd.values, ddof=1)),
                       f"{nm}_p5_cagr": float(np.percentile(nd.cagr.values, 5)), f"{nm}_p95_cagr": float(np.percentile(nd.cagr.values, 95)), f"{nm}_min_cagr": float(nd.cagr.min()), f"{nm}_max_cagr": float(nd.cagr.max()),
                       f"{nm}_med_trades": float(np.median(nd.trades.values)), f"{nm}_med_cost": float(np.median(nd.cost_paid.values)), f"{nm}_calib": float(np.std(nd.cagr.values, ddof=1)) / se,
                       f"{nm}_sec": {k: pctl(float(s[k]), nd[k].values, hb)["percentile"] for k, hb in (("cagr", True), ("max_dd", True), ("calmar", True), ("vol", False), ("ulcer", False), ("days_below_10pct", False), ("longest_underwater", False))}})
            for cc in (0.0, 50.0):
                vv = NV(b, "segment", cc)
                nc = DD(b, typ, cc)
                bb[f"{nm}_pct_cagr_{cc:g}"] = pctl(cagr(vv), nc.cagr.values)["percentile"]
                bb[f"{nm}_pct_dd_{cc:g}"] = pctl(mdd(vv), nc.max_dd.values)["percentile"]
                bb[f"{nm}_med_trades_{cc:g}"], bb[f"{nm}_med_cost_{cc:g}"] = float(np.median(nc.trades.values)), float(np.median(nc.cost_paid.values))
            sl = S(b, win="r2")
            nl = DD(b, typ, win="r2")
            chk(f"{b} {typ} R2 draws count", len(nl) == ND, str(len(nl)))
            bb[f"{nm}_r2_pct_cagr"] = pctl(float(sl.cagr), nl.cagr.values)["percentile"] if bb["r2_reportable"] else None
            bb[f"{nm}_r2_pct_dd"] = pctl(float(sl.max_dd), nl.max_dd.values)["percentile"] if bb["r2_reportable"] else None
            bb[f"{nm}_liq_pct"] = pctl(float(S(b, cash="liq").cagr), DD(b, typ, cash="liq").cagr.values)["percentile"]
        sl, slw = S(b, win="r2"), S(b, "whole_book", win="r2")
        bb.update({"r2_cagr": float(sl.cagr), "r2_whole_cagr": float(slw.cagr), "r2_c3": float(sl.cagr - slw.cagr) if bb["r2_reportable"] else None, "r2_sessions": int(sl.sessions), "liq_cagr": float(S(b, cash="liq").cagr)})
        if b in R6B:
            s6, w6, n6 = S(b, win="full_r6"), S(b, "whole_book", win="full_r6"), DD(b, "N4.6", win="full_r6")
            chk(f"{b} R6 draws count", len(n6) == ND, str(len(n6)))
            bb["r6"] = {"cagr": float(s6.cagr), "pct": pctl(float(s6.cagr), n6.cagr.values)["percentile"], "draws": int(len(n6)), "c3": float(s6.cagr - w6.cagr), "events": len(EV[(b, "full_r6")]),
                        "retagged": int((ESK[(b, "full_r6")].tag_source == "rank_linked").sum())}
        else:
            bb["r6"] = None
        r7_ = {}
        for cc in (0.0, 20.8):
            sv7, wv7 = NV(b, "segment_r7", cc), NV(b, "whole_book_r7", cc)
            chk(f"{b} R7 runs in daily_nav.csv at {cc:g} bps", len(sv7) == nses[b] and len(wv7) == nses[b], f"{len(sv7)} {len(wv7)}")
            r7_[f"seg_{cc:g}"], r7_[f"whole_{cc:g}"] = cagr(sv7), cagr(wv7)
            r7_[f"c3_{cc:g}"] = r7_[f"seg_{cc:g}"] - r7_[f"whole_{cc:g}"]
            chk(f"{b} R7 stats.csv rows equal the daily NAV at {cc:g} bps", close(float(S(b, "segment_r7", cc).cagr), r7_[f"seg_{cc:g}"]) and close(float(S(b, "whole_book_r7", cc).cagr), r7_[f"whole_{cc:g}"]))
        r7_["n_days"] = int((r7d.book == b).sum()) if r7d is not None else None
        bb["r7"] = r7_
        # weight by band, tag sources, allowed subsets, gaps (loops, not the report's vectorisation)
        e, rows = EV[(b, "full")], ESK[(b, "full")]
        span = [max(int(e.trade_idx.iloc[q + 1]) - int(e.trade_idx.iloc[q]), 0) if q + 1 < len(e) else max(nses[b] - 1 - int(e.trade_idx.iloc[q]), 0) for q in range(len(e))]
        ew, sw2, dsh, tagw = np.zeros(3), np.zeros(3), np.zeros(3), {"rank": 0.0, "unranked": 0.0, "membership": 0.0, "nonmember_rank": 0.0}
        tot_sp = float(sum(span))
        for q in range(len(e)):
            g = rows[RI[(b, "full")] == q]
            tw = float(g.listed_weight.sum())
            for bi, bn in enumerate(BANDN):
                gb = g[g.band == bn]
                share = float(gb.listed_weight.sum()) / tw
                ew[bi] += share / len(e)
                sw2[bi] += share * span[q] / tot_sp
                dsh[bi] += float(gb[~gb.kb].listed_weight.sum()) / tw * span[q] / tot_sp
            for src in tagw:
                tagw[src] += float(g[g.tag_source == src].listed_weight.sum()) * span[q]
        tt = sum(tagw.values())
        bb["band_ew"], bb["band_sw"], bb["band_dropped"], bb["kept_share"] = [float(x) for x in ew], [float(x) for x in sw2], [float(x) for x in dsh], float(1 - dsh.sum())
        bb["tagsrc"] = {k: v / tt for k, v in tagw.items()}
        bb["unranked_rows"] = int((rows.tag_source == "unranked").sum())
        bb["unranked_stocks"] = sorted(set(rows[rows.tag_source == "unranked"].stock))
        al = []
        for q in range(len(e)):
            g = rows[RI[(b, "full")] == q].sort_values("isin", kind="stable")
            sums = subset_sums(g.listed_weight.values.astype(float))
            al.append(int((np.abs(sums - float(e.dropped_weight.iloc[q])) <= float(e.tau.iloc[q]) + 1e-12).sum()))
        chk(f"{b} allowed subsets at every event equal events.csv's n_allowed_subsets (brute force)", al == [int(x) for x in e.n_allowed_subsets])
        al = np.array(al, float)
        bb["allowed"] = {"events": len(al), "ones": int((al == 1).sum()), "min": int(al.min()), "median": float(np.median(al)), "max": int(al.max()), "log10": float(np.log10(al).sum())}
        gap = {}
        for nm, typ in (("n46", "N4.6"), ("n48", "N4.8")):
            A = DROP[f"{b}|full|{typ}"].astype(float)
            w = rows.listed_weight.values.astype(float)
            Dd = np.zeros((A.shape[0], len(e)))
            for q in range(len(e)):
                Dd[:, q] = A[:, RI[(b, "full")] == q] @ w[RI[(b, "full")] == q]
            g_ = np.abs(Dd - e.dropped_weight.values[None, :])
            gap[nm] = {"rule_mean_D": float(e.dropped_weight.mean()), "null_mean_D": float(Dd.mean()), "mean_abs_gap": float(g_.mean()), "max_gap_over_tau": float((g_ / e.tau.values[None, :]).max())}
        bb["gap"] = gap
        r5f = ev_dir / "r5_tag_error.csv"
        if r5f.exists():
            g = pd.read_csv(r5f)
            g = g[g.book == b].diff_vs_whole_book.values
            bb["r5"] = {"n": int(len(g)), "mean": float(g.mean()), "p5": float(np.percentile(g, 5)), "median": float(np.median(g)), "p95": float(np.percentile(g, 95)), "share_pos": float((g > 0).mean())}
        else:
            bb["r5"] = None
        EXP[b] = bb
    for b in BOOKS:
        deep(f"page-data books {b}", page["books"][b], EXP[b])
    chk("page-data has exactly the books", set(page["books"]) == set(BOOKS))
    cn = lambda key: sum(bool((EXP[b][key] or 0) >= 90) and EXP[b]["full_reportable"] for b in BOOKS)
    cl = lambda key: sum(bool((EXP[b][key] or 0) >= 90) for b in BOOKS)
    deep("page-data verdict", page["verdict"], {"C1_N46": cn("n46_pct_cagr"), "C2_N46": cn("n46_pct_dd"), "C1_N48": cn("n48_pct_cagr"), "C2_N48": cn("n48_pct_dd"),
                                                "C3": sum(EXP[b]["c3_diff"] > 0 and EXP[b]["full_reportable"] for b in BOOKS), "R2_C1_N46": cl("n46_r2_pct_cagr"), "R2_C2_N46": cl("n46_r2_pct_dd"),
                                                "R2_C1_N48": cl("n48_r2_pct_cagr"), "R2_C3": sum((EXP[b]["r2_c3"] or 0) > 0 for b in BOOKS), "R3_N46": cl("n46_liq_pct"), "R3_N48": cl("n48_liq_pct")})
    cs = pd.read_csv(ev_dir / "controls_negative.csv") if (ev_dir / "controls_negative.csv").exists() else None
    exp6 = None
    if cs is not None:
        exp6 = {}
        for b in BOOKS:
            g6 = cs[cs.book == b]
            K = int(len(g6))
            npass = int((g6.percentile >= 90).sum())
            exp6[b] = {"K": K, "n_pass90": npass, "x_max": v6_xmax(K), "within": bool(K >= 100 and npass <= v6_xmax(K))}
            chk(f"V6 {b}: x_max for 100 shifts is the frozen 17", K != 100 or v6_xmax(K) == 17)
    deep("page-data v6", page["v6"], exp6)
    oj = ev_dir / "controls_oracle.json"
    exp7 = None
    if oj.exists():
        oo = json.loads(oj.read_text(encoding="utf-8"))

        def pb_(o, bk_):
            if isinstance(o, dict):
                if bk_ in o and isinstance(o[bk_], dict):
                    return o[bk_]
                for v_ in o.values():
                    r_ = pb_(v_, bk_) if isinstance(v_, (dict, list)) else None
                    if r_ is not None:
                        return r_
                return o if o.get("book") == bk_ else None
            if isinstance(o, list):
                for v_ in o:
                    r_ = pb_(v_, bk_)
                    if r_ is not None:
                        return r_
            return None
        exp7 = {}
        for b in BOOKS:
            d_ = pb_(oo, b)
            cg = fkey(d_, {"cagr", "oracle_cagr", "after_cost_cagr"}) if d_ else None
            st_ = fkey(d_, {"percentile", "pct", "oracle_percentile", "percentile_vs_n46", "percentile_vs_n4.6", "pct_n46"}) if d_ else None
            own = pctl(float(cg), DD(b, "N4.6").cagr.values)["percentile"] if cg is not None else None
            exp7[b] = {"cagr": None if cg is None else float(cg), "stated": None if st_ is None else float(st_), "pct": own if own is not None else (None if st_ is None else float(st_))}
    deep("page-data v7", page["v7"], exp7)
    rj = ev_dir / "regression.json"
    chk("regression.json exists", rj.exists())
    deep("page-data v4 (own reading of regression.json)", page["v4"], v4_own(json.loads(rj.read_text(encoding="utf-8"))) if rj.exists() else None)
    if rj.exists():
        v4o = v4_own(json.loads(rj.read_text(encoding="utf-8")))
        chk("V4(a) compared sessions and found every difference within 1e-12", v4o["v4a"]["comparisons"] > 0 and v4o["v4a"]["sessions"] > 0 and v4o["v4a"]["bad"] == 0 and not v4o["v4a"]["not_run"], str(v4o["v4a"]))
        t11_exists = Path(a.t11).exists()
        chk("V4(b) is run iff T11's headline existed when the run started (or says why not)", (not v4o["v4b"]["not_run"] and v4o["v4b"]["bad"] == 0 and v4o["v4b"]["comparisons"] > 0) or (v4o["v4b"]["not_run"] and au.get("t11_headline_seen") is not True),
            f"not_run={v4o['v4b']['not_run']}, t11_headline_seen={au.get('t11_headline_seen')}, T11 headline on disk now: {t11_exists}")
    # T07 beside T12, T11 context
    t07, t11 = Path(a.t07), Path(a.t11)
    exp_t07 = None
    if (t07 / "stats.csv").exists() and (t07 / "draws.csv").exists():
        s7_, d7_ = pd.read_csv(t07 / "stats.csv"), pd.read_csv(t07 / "draws.csv")
        exp_t07 = {}
        for b in BOOKS:
            x7 = s7_[(s7_.book == b) & (s7_.window == "full") & (s7_.cash == "lbes") & (s7_.cost_bps == 20.8) & (s7_.kind == "segment")].iloc[0]
            w7 = s7_[(s7_.book == b) & (s7_.window == "full") & (s7_.cash == "lbes") & (s7_.cost_bps == 20.8) & (s7_.kind == "whole_book")].iloc[0]
            d46 = d7_[(d7_.book == b) & (d7_.window == "full") & (d7_.cash == "lbes") & (d7_.cost_bps == 20.8) & (d7_.draw_type == "N4.6")]
            d48 = d7_[(d7_.book == b) & (d7_.window == "full") & (d7_.cash == "lbes") & (d7_.cost_bps == 20.8) & (d7_.draw_type == "N4.8")]
            exp_t07[b] = {"cagr": float(x7.cagr), "n46_pct": pctl(float(x7.cagr), d46.cagr.values)["percentile"], "n48_pct": pctl(float(x7.cagr), d48.cagr.values)["percentile"],
                          "n46_dd_pct": pctl(float(x7.max_dd), d46.max_dd.values)["percentile"], "c3": float(x7.cagr - w7.cagr), "draws": int(len(d46))}
        t7log = AA / "tests" / "T07" / "analysis.log"
        if t7log.exists():
            mt = re.search(r"C1 selection \(H1\)\s+\w+\s+percentile >= 90 in >= 3 of 4 books: \d of 4 \(([^)]*)\)", t7log.read_text(encoding="utf-8"))
            if mt:
                logged = {p_.split()[0]: float(p_.split()[1]) for p_ in mt.group(1).split(", ")}
                chk("T07's N4.6 C1 percentiles recomputed from its evidence equal its analysis.log", all(abs(logged[b[-4:]] - exp_t07[b]["n46_pct"]) <= 0.0500001 for b in BOOKS if b[-4:] in logged), str(logged))
    deep("page-data t07", page["t07"], exp_t07)
    exp_t11 = None
    if (t11 / "stats.csv").exists():
        s11 = pd.read_csv(t11 / "stats.csv")
        exp_t11 = {}
        for b in BOOKS:
            g = s11[(s11.book == b) & (s11.window == "full") & (s11.cash == "lbes") & (s11.cost_bps == 20.8)]
            pa, hp_ = g[g.kind == "strategy_fixed50"], g[g.kind == "hold_parent"]
            exp_t11[b] = {"parta_cagr": float(pa.iloc[0].cagr) if len(pa) else None, "parta_dd": float(pa.iloc[0].max_dd) if len(pa) else None,
                          "parent_cagr": float(hp_.iloc[0].cagr) if len(hp_) else None, "parent_dd": float(hp_.iloc[0].max_dd) if len(hp_) else None}
    deep("page-data t11", page["t11"], exp_t11)
    chk("page-data t11_seen_at_run is audit.json's", page["t11_seen_at_run"] == au.get("t11_headline_seen"))
    r6a = au.get("r6") if isinstance(au.get("r6"), dict) else {}
    deep("page-data r6_info", page["r6_info"], {"ids": r6a.get("ids"), "links": r6a.get("links"), "re_tagged_event_rows": r6a.get("re_tagged_event_rows"),
                                                "retagged_rows_in_evidence": int(sum((EXP[b]["r6"] or {}).get("retagged", 0) for b in R6B))})
    r6l = pd.read_csv(ev_dir / "r6_links.csv", dtype={"linked_quote_id": str, "isin": str}, keep_default_na=False) if (ev_dir / "r6_links.csv").exists() else None
    chk("r6_links.csv exists", r6l is not None)
    deep("page-data r6_links", page["r6_links"], [] if r6l is None else [{k_: (str(v_) if k_ in ("linked_quote_id", "isin", "stock", "book", "info_date", "original_source", "linked_band") else (int(v_) if str(v_).lstrip("-").isdigit() else str(v_)))
                                                                      for k_, v_ in r_.items()} for r_ in r6l.to_dict("records")])
    deep("page-data r7_days", page["r7_days"], [] if r7d is None else [{"book": str(r_["book"]), "isin": str(r_["isin"]), "stock": str(r_["stock"]), "date": str(r_["date"]), "move": float(r_["move"])} for r_ in r7d.to_dict("records")])

    # ── stretches (own derivation) ─────────────────────────────────────────────
    WKB = {}
    for b in BOOKS:
        d_ = dec[dec.book == b].sort_values("j").reset_index(drop=True)
        wk0 = [0]
        for t in d_.trade_date.iloc[1:]:
            if pd.isna(t):
                break
            wk0.append(int(np.searchsorted(cal[b].values, np.datetime64(pd.Timestamp(t)))))
        nw = len(wk0)
        sgm = [[1 if d_.loc[j, f"sign_{s}"] == "BUY" else 0 for s in SIGN3] for j in range(nw)]
        dis = [len(set(t)) > 1 for t in sg_of[b][:nw]]
        wend = wk0[1:] + [nses[b] - 1]
        pat = ["".join("B" if x else "S" for x in sgm[q]) for q in range(nw)]
        wstr, strs, j = [-1] * nw, [], 0
        while j < nw:
            if dis[j]:
                k = j
                while k + 1 < nw and dis[k + 1]:
                    k += 1
                pats = []
                for q in range(j, k + 1):
                    if pat[q] not in pats:
                        pats.append(pat[q])
                strs.append({"s": wk0[j], "e": wend[k], "from": str(d_.decision_date.iloc[j]), "to": str(d_.decision_date.iloc[k]), "weeks": k - j + 1, "patterns": "→".join(pats),
                             "kind": kind_of(pat[j - 1] if j > 0 else None, pat[k + 1] if k + 1 < nw else None)})
                for q in range(j, k + 1):
                    wstr[q] = len(strs) - 1
                j = k + 1
            else:
                j += 1
        nvv = {k: NV(b, k) for k in ("segment", "whole_book")}
        tips = []
        for x in strs:
            rr = nvv["segment"][x["e"]] / nvv["segment"][x["s"]] - 1
            ww = nvv["whole_book"][x["e"]] / nvv["whole_book"][x["s"]] - 1
            tips.append(f"Stretch {len(tips) + 1} of {len(strs)}: decisions {x['from']} to {x['to']}, {x['weeks']} week(s), patterns {x['patterns']} (B = BUY, S = SELL; Nifty 100, Midcap 100, Smallcap 100); "
                        f"sessions {cal[b][x['s']].date()} to {cal[b][x['e']].date()}: rule {100 * rr:+.1f}%, whole-book switch {100 * ww:+.1f}%")
        WKB[b] = {"wk0": wk0, "sg": sgm, "wst": [int(all(x == "BUY" for x in t)) for t in sg_of[b][:nw]], "wstr": wstr, "tips": tips, "strs": strs}
    st0 = WKB[BOOKS[0]]["strs"]
    exp_st, ahead, nn = [], {b: 0 for b in BOOKS}, {b: 0 for b in BOOKS}
    for s0 in st0:
        row = {"from": s0["from"], "to": s0["to"], "weeks": s0["weeks"], "patterns": s0["patterns"], "kind": s0["kind"], "diff": {}, "rule": {}, "whole": {}, "lp": {}}
        for b in BOOKS:
            m = [x for x in WKB[b]["strs"] if x["from"] == s0["from"] and x["to"] == s0["to"]]
            if m:
                sv, wv = NV(b, "segment"), NV(b, "whole_book")
                a_, e_ = m[0]["s"], m[0]["e"]
                rr, ww = sv[e_] / sv[a_] - 1, wv[e_] / wv[a_] - 1
                row["diff"][b], row["rule"][b], row["whole"][b] = float(rr - ww), float(rr), float(ww)
                row["lp"][b] = float(100 * (math.log(sv[e_]) - math.log(wv[e_]) - math.log(sv[a_]) + math.log(wv[a_])))
                nn[b] += 1
                ahead[b] += int(rr - ww > 0)
            else:
                row["diff"][b] = row["rule"][b] = row["whole"][b] = row["lp"][b] = None
        exp_st.append(row)
    deep("page-data stretches", page["stretches"], exp_st)
    deep("page-data stretch counts", {"a": page["stretch_ahead"], "n": page["stretch_n"]}, {"a": ahead, "n": nn})
    deep("page-data gap totals (log points)", page["gap_total_lp"], {b: float(100 * (math.log(NV(b, "segment")[-1] / NV(b, "whole_book")[-1]) - math.log(NV(b, "segment")[0] / NV(b, "whole_book")[0]))) for b in BOOKS})
    chk(f"the first book has {len(st0)} disagreement stretches, as frozen in T12.md (11)", len(st0) == 11 or len(BOOKS) < 4, str(len(st0)))
    # episodes
    exp_ep = None
    if (ep_dir / "summary.json").exists() and (ep_dir / "stretches.csv").exists():
        es_sum = json.loads((ep_dir / "summary.json").read_text(encoding="utf-8"))
        if es_sum.get("run") == ev_dir.name:
            esx = pd.read_csv(ep_dir / "stretches.csv")
            exp_ep = {"recon": {b: es_sum["books"][b]["recon_max_rel_err"] for b in BOOKS if b in es_sum["books"]},
                      "first_logged": {b: es_sum["books"][b]["first_logged_position"] for b in BOOKS if b in es_sum["books"]},
                      "rows": [{"stretch": int(r_["stretch"]), "book": str(r_["book"]), "kept": None if pd.isna(r_["kept_share_mean"]) else float(r_["kept_share_mean"]),
                                "sleeve": None if pd.isna(r_["sleeve_ret"]) else float(r_["sleeve_ret"]), "ex": [None if pd.isna(r_[c_]) else float(r_[c_]) for c_ in ("excess_large_pp", "excess_mid_pp", "excess_small_pp")]}
                               for r_ in esx.to_dict("records") if r_["book"] in BOOKS]}
            for b in BOOKS:
                g = esx[esx.book == b].sort_values("stretch")
                chk(f"episodes {b}: stretches and their log gaps equal the page's", len(g) == len(st0) and all(close(100 * float(x), exp_st[i]["lp"][b], 1e-7) for i, x in enumerate(g.gap_log_rule_over_whole.values)))
                chk(f"episodes {b}: its holdings reproduce the rule's NAV (relative 1e-6)", (es_sum["books"][b]["recon_max_rel_err"] or 0) < 1e-6, es_sum["books"][b]["recon_max_rel_err"])
    deep("page-data episodes", page["episodes"], exp_ep)
    chk("page-data has exactly the expected top-level keys", set(page) == {"run", "prereg_sha256", "draws", "as_of_file", "as_of_inputs", "end", "start", "r2_first", "weeks", "books", "gates", "verdict", "v4", "v6", "v7",
                                                                      "r6_links", "r6_info", "r7_days", "t07", "t11", "t11_seen_at_run", "stretches", "stretch_ahead", "stretch_n", "gap_total_lp", "episodes", "example", "inputs", "caveats"}, str(sorted(page)))

    # ── 4. every tag from the raw panels ──────────────────────────────────────
    rank_f = [r for r in appr if r["id"] == "D23b" and r["file"].endswith("mcap_rank_panel_from_2013-12.csv")]
    mem_f = [r for r in appr if r["file"].endswith("tags/membership_panel.csv")]
    sym_f = [r for r in appr if r["file"].endswith("symbology/symbology_changes.csv")]
    chk("one APPROVED row for the D23b panel, the D23 membership panel and D22", len(rank_f) == len(mem_f) == len(sym_f) == 1)
    rk = pd.read_csv(AA / rank_f[0]["file"], usecols=["date", "quote_id", "isin", "rank", "band"], dtype={"isin": str, "quote_id": str}, keep_default_na=False, na_values=[""])
    rk["date"] = pd.to_datetime(rk["date"])
    mp = pd.read_csv(AA / mem_f[0]["file"], usecols=["snapshot_date"])
    sy = pd.read_csv(AA / sym_f[0]["file"], usecols=["quote_id", "isin", "new_isin"], dtype=str, keep_default_na=False, na_values=[""])
    chk("the membership cutoff lies after END, so every tag in the window is a rank tag", pd.to_datetime(mp.snapshot_date).min() > END, str(pd.to_datetime(mp.snapshot_date).min()))
    snaps = np.array(sorted(rk.date.unique()))
    by_snap = {d: g for d, g in rk[rk.date <= END + pd.Timedelta(days=1)].groupby("date")}
    q_of_isin = {}
    for x in sy.itertuples():
        for i_ in (x.isin, x.new_isin):
            if isinstance(i_, str):
                q_of_isin.setdefault(i_, set()).add(x.quote_id)
    for x in rk[["isin", "quote_id"]].drop_duplicates().itertuples():
        q_of_isin.setdefault(x.isin, set()).add(x.quote_id)
    isins_of_q = {}
    for i_, qs in q_of_isin.items():
        for q_ in qs:
            isins_of_q.setdefault(q_, set()).add(i_)
    cache = {}

    def own_tag(isin, info):
        key = (isin, info)
        if key in cache:
            return cache[key]
        k_ = int(np.searchsorted(snaps, np.datetime64(info), side="right")) - 1
        sd = pd.Timestamp(snaps[k_])
        g = by_snap[sd]
        ids = {isin}
        for q_ in q_of_isin.get(isin, set()):
            ids |= isins_of_q.get(q_, set())
        m_ = g[g["isin"] == isin]
        if not len(m_):
            m_ = g[g["isin"].isin(ids)]
        if len(m_):
            out_ = (m_.iloc[0].band, "rank", str(sd.date()), str(int(m_.iloc[0]["rank"])))
        else:
            out_ = ("Small and below", "unranked", str(sd.date()), "")
        cache[key] = out_
        return out_
    tag_n = tag_bad = 0
    bad_ex = []
    for k in KEYS:
        rows = ESK[k]
        for x in rows.itertuples():
            info = pd.Timestamp(x.info_date)
            band, src, snap, det = own_tag(x.isin, info)
            if k[1] == "full_r6" and x.tag_source == "rank_linked":
                continue
            ok_ = x.band == band and x.tag_source == src and str(x.tag_snapshot)[:10] == snap and norm_detail(x.tag_detail) == norm_detail(det)
            tag_n += 1
            if not ok_:
                tag_bad += 1
                bad_ex.append(f"{k}: {x.stock} {x.isin} {x.info_date}: engine {x.band}/{x.tag_source}/{x.tag_snapshot}/{x.tag_detail} vs {band}/{src}/{snap}/{det}")
        e = EV[k]
        sig = {int(r_.event_no): [str(r_.state_Nifty100), str(r_.state_MC100), str(r_.state_SC100)] for r_ in e.itertuples()}
        okk = all(bool(x.kb) == (sig[int(x.event_no)][BANDN.index(x.band)] == "BUY") and str(x.band_signal) == sig[int(x.event_no)][BANDN.index(x.band)] for x in rows.itertuples())
        chk(f"{k[0]}|{k[1]}: every row is kept iff its band's signal is BUY", okk)
        for r_ in e.itertuples():
            ds = [d_ for d_ in dates if d_ < pd.Timestamp(r_.trade_date)]
            if ds:
                jd = len(ds) - 1
                chk(f"{k[0]}|{k[1]} event {int(r_.event_no)}: its states are the latest decision before the trade session", sig[int(r_.event_no)] == trip[jd] or r_.kind == "initial", f"{sig[int(r_.event_no)]} vs {trip[jd]}")
            chk(f"{k[0]}|{k[1]} event {int(r_.event_no)}: the information date is the session before the trade session (T0's own date for T0)",
                str(r_.info_date) == (str(r_.trade_date) if r_.kind == "initial" else str(c[c.get_loc(pd.Timestamp(r_.trade_date)) - 1].date())))
    chk(f"the tag of every held stock at every event equals the D23b panel's ({tag_n:,} rows: band, source, snapshot, rank)", tag_n > 0 and tag_bad == 0, f"{tag_bad} differ; " + "; ".join(bad_ex[:3]))
    # R6: rank_linked rows and r6_links.csv
    nl_ = 0
    for b in R6B:
        rows = ESK[(b, "full_r6")]
        lk = rows[rows.tag_source == "rank_linked"]
        base = ESK[(b, "full")]
        got_r6, want_r6 = sorted(set(lk["isin"])), sorted(set(base[base.tag_source == "unranked"]["isin"]))
        if len(lk):
            chk(f"{b} R6 re-tags exactly the stocks that read unranked on the full window", got_r6 == want_r6, f"{got_r6} vs {want_r6}")
        else:   # the frozen quote_ids never rank in the window (Step 2 log, contract change 1): then full_r6 must be the full window unchanged
            chk(f"{b} R6 re-tagged nothing: full_r6's tags, events and rule equal the full window's",
                rows[["event_no", "isin", "band", "tag_source", "kept"]].astype(str).values.tolist() == base[["event_no", "isin", "band", "tag_source", "kept"]].astype(str).values.tolist()
                and close(float(S(b, win="full_r6").cagr), float(S(b).cagr), 1e-12) and (au.get("r6") or {}).get("re_tagged_event_rows") == 0)
        sub = r6l[r6l.book == b] if r6l is not None else pd.DataFrame()
        chk(f"{b} r6_links.csv has one row per re-tagged event row", len(sub) == len(lk), f"{len(sub)} vs {len(lk)}")
        for x in lk.itertuples():
            m_ = sub[(sub["isin"] == x.isin) & (sub.info_date == str(x.info_date))] if len(sub) else sub
            chk(f"{b} R6 {x.stock} {x.info_date} has its r6_links.csv row", len(m_) == 1)
            if len(m_) != 1:
                continue
            qid = str(m_.iloc[0].linked_quote_id)
            g = rk[(rk.quote_id == qid) & (rk.date <= pd.Timestamp(x.info_date))]
            if not len(g):
                chk(f"{b} R6 {x.stock}: the linked quote_id {qid} has a rank on or before {x.info_date} in D23b", False, "no rank row: the linked quote_id does not rank in the window")
                continue
            g = g[g.date == g.date.max()].iloc[0]
            nl_ += 1
            chk(f"{b} R6 {x.stock} {x.info_date}: rank and band of quote_id {qid} on {g.date.date()} equal the row and r6_links.csv",
                norm_detail(x.tag_detail) == str(int(g["rank"])) == str(m_.iloc[0].linked_rank) and x.band == g.band == m_.iloc[0].linked_band and str(x.tag_via) == "r6_link", f"{x.tag_detail}/{x.band} vs {g['rank']}/{g.band}")

    # ── 5. the worked example ─────────────────────────────────────────────────
    ex = page["example"]
    b = BOOKS[0]
    e0, r0 = EV[(b, "full")], ESK[(b, "full")]
    cand = [q for q in range(len(e0)) if e0.event_no.iloc[q] > 0 and e0.pb.iloc[q]]
    qx = cand[0] if cand else 0
    chk("example is the first partial event after the initial one of the first book", ex["book"] == b and ex["pos"] == qx + 1 and ex["event_no"] == int(e0.event_no.iloc[qx]))
    rowe = e0.iloc[qx]
    g = r0[RI[(b, "full")] == qx].reset_index(drop=True)
    jd = max(j for j, d_ in enumerate(dates_of[b]) if d_ < pd.Timestamp(rowe.trade_date))
    chk("example: decision week and date", ex["decision_week"] == jd and ex["decision_date"] == str(dates_of[b][jd].date()))
    chk("example: the signals", ex["signs"] == sg_of[b][jd] and ex["states"] == [str(rowe.state_Nifty100), str(rowe.state_MC100), str(rowe.state_SC100)] == sg_of[b][jd])
    chk("example: labels are Master row dates on or before the decision", all(pd.Timestamp(x) <= dates_of[b][jd] for x in ex["labels"]) and ex["labels"] == [str(x) for x in dec[(dec.book == b) & (dec.j == jd)][[f"label_{s}" for s in SIGN3]].iloc[0]])
    for x in g.itertuples():
        band, src, snap, det = own_tag(x.isin, pd.Timestamp(x.info_date))
        chk(f"example tag of {x.isin} equals the D23b panel's (band, source, snapshot, rank)", x.band == band and x.tag_source == src and str(x.tag_snapshot)[:10] == snap and norm_detail(x.tag_detail) == norm_detail(det))
    deep("example rows", ex["rows"], [{"stock": str(x.stock), "isin": str(x.isin), "w": float(x.listed_weight), "band": str(x.band), "src": str(x.tag_source), "snap": str(x.tag_snapshot), "detail": "" if pd.isna(x.tag_detail) else str(x.tag_detail),
                                      "via": "" if pd.isna(x.tag_via) else str(x.tag_via), "sig": str(x.band_signal), "kept": bool(x.kb)} for x in g.itertuples()])
    sw_, D_ = float(g.listed_weight.sum()), float(g.listed_weight[~g.kb].sum())
    chk("example: sum of weights, D, s and the events.csv row", close(ex["sum_w"], sw_) and close(ex["D"], D_) and close(ex["s"], D_ / sw_) and close(ex["ev_D"], D_) and close(ex["ev_s"], D_ / sw_) and ex["n_held"] == len(g) == int(rowe.n_held) and ex["n_dropped"] == int((~g.kb).sum()) == int(rowe.n_dropped), f"{ex['D']} {D_}")
    chk("example: tau is half the smallest listed weight", close(ex["tau"], float(g.listed_weight.min()) / 2))
    chk("example: cost on the page is traded x 20.8 / 2 / 10,000 (events.csv's cost equals it)", close(ex["cost"], ex["traded"] * 20.8 / 2 / 10000, 1e-9) and close(ex["traded"], float(rowe.traded)) and close(ex["V"], float(rowe.V_before)))
    gs = g.sort_values("isin", kind="stable").reset_index(drop=True)
    sums = subset_sums(gs.listed_weight.values.astype(float))
    allowed = np.flatnonzero(np.abs(sums - D_) <= ex["tau"] + 1e-12)
    chk("example: allowed subsets by brute force", ex["n_allowed"] == len(allowed) == int(rowe.n_allowed_subsets), f"{ex['n_allowed']} {len(allowed)}")
    u = float(np.random.default_rng([SEED, 7, 0, BNO[b]]).random(len(e0))[qx])
    pick = int(math.floor(u * len(allowed)))
    mask = int(allowed[pick])
    dropped = [gs.stock.iloc[i] for i in range(len(gs)) if (mask >> i) & 1]
    chk("example: u, index and bitmask of the N4.6 draw", close(ex["u"], u, 1e-12) and ex["pick"] == pick and ex["mask"] == mask, f"{ex['u']} {u} {ex['pick']} {pick}")
    chk("example: the draw's dropped stocks and weight", ex["draw_drops"] == dropped and close(ex["draw_weight"], float(sums[mask])) and abs(float(sums[mask]) - D_) <= ex["tau"] + 1e-12)
    rowsel = np.flatnonzero(RI[(b, "full")] == qx)
    sorted_rows = rowsel[np.argsort(r0["isin"].values[rowsel], kind="stable")]
    chk("example: the stored draw 0 equals the replay", ex["stored_equal"] is True and list(DROP[f"{b}|full|N4.6"][0][sorted_rows]) == [(mask >> i) & 1 for i in range(len(gs))])
    chk("example: the rule's dropped stocks", ex["rule_drops"] == [gs.stock.iloc[i] for i in range(len(gs)) if not gs.kb.iloc[i]])
    nvs = nav[(nav.book == b) & (nav.cost_bps == 20.8) & (nav.run == "segment")].sort_values("date").reset_index(drop=True)
    nvw = nav[(nav.book == b) & (nav.cost_bps == 20.8) & (nav.run == "whole_book")].sort_values("date").reset_index(drop=True)
    k0 = int(rowe.trade_idx)
    chk("example: trade_idx is the trade session's index in the calendar", cal[b][k0] == pd.Timestamp(rowe.trade_date))
    chk("example: the NAV rows around the trade", ex["nav_around"] == [{"date": str(nvs.date.iloc[i].date()), "rule": float(nvs.nav.iloc[i]), "whole": float(nvw.nav.iloc[i])} for i in range(max(k0 - 2, 0), min(k0 + 3, len(nvs)))])
    sv = nvs.nav.values
    chk("example: path start, end, sessions, CAGR, worst fall", ex["path_start"] == str(nvs.date.iloc[0].date()) and ex["path_end"] == str(nvs.date.iloc[-1].date()) and ex["sessions"] == len(sv) and close(ex["end_nav"], float(sv[-1])) and close(ex["cagr"], cagr(sv)) and close(ex["max_dd"], mdd(sv)))
    for nm, typ in (("n46", "N4.6"), ("n48", "N4.8")):
        nd = DD(b, typ)
        x0 = nd[nd.draw_id == 0].iloc[0]
        chk(f"example: {typ} draw 0 numbers", close(ex["d0"][nm]["cagr"], float(x0.cagr)) and close(ex["d0"][nm]["max_dd"], float(x0.max_dd)) and ex["d0"][nm]["trades"] == int(x0.trades) and close(ex["d0"][nm]["cost_paid"], float(x0.cost_paid)))
        rk_ = ex["rank"][nm]
        pp = pctl(cagr(sv), nd.cagr.values)
        chk(f"example: ranking against {typ} adds up and equals the table's percentile", rk_["worse"] + rk_["tied"] + rk_["better"] == rk_["draws"] == ND and close(rk_["percentile"], (rk_["worse"] + 0.5 * rk_["tied"]) / ND * 100)
            and close(rk_["p"], (1 + rk_["better"] + rk_["tied"]) / (ND + 1)) and close(rk_["percentile"], pp["percentile"]) and close(rk_["percentile"], EXP[b][f"{nm}_pct_cagr"]), str(rk_))
    chk("example: rule's trades and cost paid", ex["rule_trades"] == int(S(b).trades) and close(ex["rule_cost_paid"], float(S(b).cost_paid)))

    # ── 6. every draw of both nulls, and replays ──────────────────────────────
    nd_, nbad_, nrep, nrep_bad = 0, 0, 0, 0
    for k in KEYS:
        bk_, win = k
        e, rows = EV[k], ESK[k]
        ri = RI[k]
        E_, R_ = len(e), len(rows)
        w = rows.listed_weight.values.astype(float)
        Dq, tau = e.dropped_weight.values.astype(float), e.tau.values.astype(float)
        for typ in (("N4.6",) if win == "full_r6" else ("N4.6", "N4.8")):
            key = f"{bk_}|{win}|{typ}"
            chk(f"drops {key} exist", key in DROP)
            if key not in DROP:
                continue
            A = DROP[key].astype(np.int8)
            chk(f"drops {key} shape (draws, rows of event_stocks.csv)", A.shape == (ND, R_), str(A.shape))
            nd_ += A.shape[0]
            bad = np.zeros(A.shape[0], bool)
            if typ == "N4.6":
                for q in range(E_):
                    cols = np.flatnonzero(ri == q)
                    dw = A[:, cols].astype(float) @ w[cols]
                    bad |= np.abs(dw - Dq[q]) > tau[q] + 1e-9
                    if int(e.n_dropped.iloc[q]) == 0:
                        bad |= A[:, cols].sum(1) != 0
                    if int(e.n_dropped.iloc[q]) == int(e.n_held.iloc[q]):
                        bad |= A[:, cols].sum(1) != len(cols)
            else:
                L = LB[key].astype(int)
                for q in range(E_):
                    cols = np.flatnonzero(ri == q)
                    for li, cn_ in enumerate(("n_large", "n_mid", "n_small")):
                        bad |= (L[:, cols] == li).sum(1) != int(e[cn_].iloc[q])
                    sig = [str(e[f"state_{s}"].iloc[q]) for s in SIGN3]
                    exp_drop = np.array([[1 if sig[min(l_, 2)] == "SELL" else 0 for l_ in row] for row in L[:, cols]])
                    bad |= (exp_drop != A[:, cols]).any(1)
            nbad_ += int(bad.sum())
            if typ == "N4.6":
                for d_ in range(min(a.replay, A.shape[0])):
                    uu = np.random.default_rng([SEED, 7, d_, BNO[bk_]]).random(E_)
                    got = np.zeros(R_, np.int8)
                    for q in range(E_):
                        cols = np.flatnonzero(ri == q)
                        cols = cols[np.argsort(rows["isin"].values[cols], kind="stable")]
                        sm = subset_sums(w[cols])
                        alw = np.flatnonzero(np.abs(sm - Dq[q]) <= tau[q] + 1e-12)
                        m = int(alw[int(math.floor(uu[q] * len(alw)))])
                        got[cols] = [(m >> i) & 1 for i in range(len(cols))]
                    nrep += 1
                    nrep_bad += int((got != A[d_]).any())
    chk(f"every draw of both nulls holds its table ({nd_} draws)", nd_ > 0 and nbad_ == 0, f"{nbad_} bad")
    chk(f"the first {a.replay} N4.6 draws of every book and window replay from their seeds ({nrep} replays)", nrep > 0 and nrep_bad == 0, f"{nrep_bad} differ")

    # ── 7. R7 flagged days from D18 ───────────────────────────────────────────
    pcor = [r for r in appr if r["file"].endswith("holdings_matrix/price_corrections.csv")]
    pcd = pd.read_csv(AA / pcor[0]["file"]) if pcor else pd.DataFrame(columns=["stock", "ex_date", "factor", "applies_to"])
    own7 = []
    for b in BOOKS:
        of = [r for r in appr if r["id"] == "D18" and r["file"].endswith(f"{b}_ohlc.csv")]
        chk(f"one APPROVED D18 row for {b}", len(of) == 1)
        rows = ESK[(b, "full")]
        e = EV[(b, "full")]
        # the parent's basket in force (D19, own read): a basket holds from the first D26 session on or after its rebalance_date (= availableDate; no basket in
        # the window is skipped, D05) until the next one, whether or not the rule traded on that session (a basket that arrives while the rule holds no stock
        # is in force without an event)
        wf = [r for r in appr if r["id"] == "D19" and r["file"].endswith(f"{b}_holding_weight_matrix.csv")]
        chk(f"one APPROVED D19 weight matrix for {b}", len(wf) == 1)
        wm = pd.read_csv(AA / wf[0]["file"], parse_dates=["rebalance_date"]).sort_values("rebalance_date").reset_index(drop=True)
        wm = wm[wm.rebalance_date <= END].reset_index(drop=True)
        eff = [int(np.searchsorted(c.values, np.datetime64(d_))) for d_ in wm.rebalance_date]   # 0 for every basket effective on or before T0
        spans = [(eff[i_], eff[i_ + 1] if i_ + 1 < len(eff) else len(c)) for i_ in range(len(eff))]
        live = [i_ for i_, (a_, z_) in enumerate(spans) if z_ > a_]
        stocks = sorted({s_ for i_ in live for s_ in wm.columns[1:] if wm.loc[i_, s_] > 0})
        oh = pd.read_csv(AA / of[0]["file"], usecols=["date", "stock", "close"], parse_dates=["date"])
        oh = oh[oh.stock.isin(stocks) & (oh.date <= END)]
        for r_ in pcd.itertuples():
            if str(r_.applies_to) == b:
                mm = (oh.stock == r_.stock) & (oh.date < pd.Timestamp(r_.ex_date))
                oh.loc[mm, "close"] = oh.loc[mm, "close"] * float(r_.factor)
        C = oh.pivot_table(index="date", columns="stock", values="close").reindex(columns=stocks)
        C = C.reindex(C.index.union(c)).ffill().reindex(c)
        held = pd.DataFrame(False, index=c, columns=stocks)
        for i_ in live:
            ss = [s_ for s_ in wm.columns[1:] if wm.loc[i_, s_] > 0]
            held.iloc[spans[i_][0]:spans[i_][1], [stocks.index(s_) for s_ in ss]] = True
        bad_ev = [int(e.event_no.iloc[q]) for q in range(len(e)) if set(rows[RI[(b, "full")] == q].stock) != set(held.columns[held.iloc[int(e.trade_idx.iloc[q])].values])]
        chk(f"{b}: at every event the stocks of event_stocks.csv are the D19 basket in force on the trade session", not bad_ev, f"events {bad_ev[:5]}")
        mv = C / C.shift(1) - 1
        hh = held | held.shift(1, fill_value=False)
        flag = (mv.abs() >= 0.20) & hh
        for t_, s_ in zip(*np.nonzero(flag.values)):
            own7.append((b, stocks[s_], str(c[t_].date()), round(float(mv.values[t_, s_]), 9)))
    got7 = [] if r7d is None else [(str(r_.book), str(r_.stock), str(r_.date)[:10], round(float(r_.move), 9)) for r_ in r7d.itertuples()]
    chk(f"R7: the flagged held stock-days equal a re-derivation from D18 ({len(own7)} found)", sorted(x[:3] for x in own7) == sorted(x[:3] for x in got7), f"own {sorted(own7)[:4]} vs file {sorted(got7)[:4]}")
    chk("R7: the moves equal D18's", all(abs(x[3] - y[3]) < 1e-6 for x, y in zip(sorted(own7), sorted(got7))) if len(own7) == len(got7) else False)

    # ── 8. page text, verifier, gates, caveats up front, parent captions ──────
    for b in BOOKS:
        pb = EXP[b]
        for txt in (f"{pb['n46_pct_cagr']:.1f}", f"{pb['n46_pct_dd']:.1f}", f"{pb['n48_pct_cagr']:.1f}", f"{pb['n48_pct_dd']:.1f}", f"{100 * pb['cagr']:.1f}%", f"{100 * pb['max_dd']:.1f}%", f"{pb['n46_p_cagr']:.3f}",
                    f"{100 * pb['c3_diff']:+.2f}", f"{100 * pb['whole_cagr']:.1f}%", f"{100 * pb['c3_se']:.2f}", f"{100 * pb['parent_cagr']:.1f}%"):
            chk(f"{b} page prints {txt}", txt in html)
        chk(f"{b} page prints its R2 CAGR", f"{100 * pb['r2_cagr']:.1f}%" in html)
        if pb["r6"]:
            chk(f"{b} page prints its R6 percentile and C3", f"{pb['r6']['pct']:.1f}" in html and f"{100 * pb['r6']['c3']:+.2f}" in html)
    # the four key tables, row by row, rebuilt from the recomputed numbers (a number printed elsewhere on the page cannot mask a wrong cell)
    pcf = lambda x: f"{100 * x:.1f}%"
    trow = lambda cells: "<tr>" + "".join(f"<td>{c_}</td>" for c_ in cells) + "</tr>"
    chipf = lambda ok: ('<span class="chip ok">PASS</span>' if ok else '<span class="chip bad">FAIL</span>')
    for b in BOOKS:
        x = EXP[b]
        rows_exp = {
            "summary": [b, pcf(x["cagr"]), f"{x['n46_pct_cagr']:.1f}", f"{x['n46_p_cagr']:.3f}", f"{x['n48_pct_cagr']:.1f}", pcf(x["max_dd"]), f"{x['n46_pct_dd']:.1f}", f"{x['n48_pct_dd']:.1f}",
                        f"{100 * x['c3_diff']:+.2f}", pcf(x["r2_cagr"]), "" if x["n46_r2_pct_cagr"] is None else f"{x['n46_r2_pct_cagr']:.1f}"],
            "headline CAGR": [b, pcf(x["parent_cagr"]), pcf(x["whole_cagr"]), pcf(x["cagr"]), pcf(x["n46_median_cagr"]), f"{100 * (x['cagr'] - x['n46_median_cagr']):+.2f} pp", f"<b>{x['n46_pct_cagr']:.1f}</b>",
                              f"{x['n46_p_cagr']:.3f}", pcf(x["n48_median_cagr"]), f"<b>{x['n48_pct_cagr']:.1f}</b>", f"{x['n48_p_cagr']:.3f}"],
            "headline drawdown": [b, pcf(x["parent_dd"]), pcf(x["whole_dd"]), pcf(x["max_dd"]), pcf(x["n46_median_dd"]), f"<b>{x['n46_pct_dd']:.1f}</b>", f"{x['n46_p_dd']:.3f}", pcf(x["n48_median_dd"]),
                                  f"<b>{x['n48_pct_dd']:.1f}</b>", f"{x['n48_p_dd']:.3f}"],
            "C3": [b, pcf(x["whole_cagr"]), pcf(x["cagr"]), f"<b>{100 * x['c3_diff']:+.2f}</b>", f"{100 * x['c3_se']:.2f}", f"{x['c3_diff'] / x['c3_se']:+.2f}", chipf(x["c3_diff"] > 0),
                   f"{100 * x['c3_diff_0']:+.2f}", f"{100 * x['c3_diff_50']:+.2f}"]}
        for nm_, cells in rows_exp.items():
            chk(f"{b}: the {nm_} table row is exactly the recomputed numbers", trow(cells) in html, trow(cells)[:200])
    chk("page prints the window, R2's first session and the draws count", page["start"] in html and page["end"] in html and page["r2_first"] in html and f"{ND:,}" in html)
    vj = ev_dir / "verify_t12.json"
    chk("verify_t12.json exists", vj.exists())
    if vj.exists():
        v = json.loads(vj.read_text(encoding="utf-8"))
        chk("verifier passed", bool(v.get("exit_ok", True)) and v.get("gate_failures_and_missing", 0) == 0, "verify_t12.json does not say passed")
        chk("verifier compared rows", v.get("gate_compared", 1) > 0)
    lp = logdir / "analysis.log"
    chk("analysis.log exists", lp.exists())
    if lp.exists():
        mg = re.search(r"^Gates: (\{.*\}) ->(.*)$", lp.read_text(encoding="utf-8"), re.M)
        chk("analysis.log has a Gates line", mg is not None)
        if mg:
            gg = ast.literal_eval(mg.group(1))
            chk("all seven gates pass in analysis.log", sorted(gg) == ["V1", "V2", "V3", "V4", "V5", "V6", "V7"] and all(x == "PASS" for x in gg.values()) and "ALL PASS" in mg.group(2), mg.group(0))
            chk("page's gates equal analysis.log's", page["gates"] == gg)
    chk("page table of the validity gates lists V1 to V7", all(f"V{i} " in html for i in range(1, 8)))
    ia, idata = html.find("What to be careful about"), html.find('<h2 id="data">')
    up = html[ia:idata] if 0 <= ia < idata else ""
    chk("the caveats come before the data section", bool(up))
    for phrase, why in (("Every tag in this window is a market-cap rank tag", "rank tags"), ("Two holdings have no rank", "two unranked holdings"), ("Tags are up to about a month old", "month-old tags"),
                        ("There is no published NAV before 2019-01-02", "no published NAV"), (_html.escape(cav[0][1:].rstrip(";").rstrip()) if len(cav) > 0 else "?", "back-filled 2026-01-03"), (_html.escape(cav[1][1:].rstrip(";").rstrip()) if len(cav) > 1 else "?", "untested before 2026"),
                        (_html.escape(cav[2][1:].rstrip(";").rstrip()) if len(cav) > 2 else "?", "today's identifiers"), (_html.escape(cav[3][1:].rstrip(";").rstrip()) if len(cav) > 3 else "?", "the unranked holdings named")):
        chk(f"caveats up front: {why}", phrase in up)
    figs = re.findall(r'<figure class="card hv"><figcaption>(.*?)</figcaption>(<svg[^>]*data-id="([^"]+)")', html, re.S)
    par_figs = [f_ for f_ in figs if f_[2].split("|")[0] in ("eq", "dd", "regime")]
    chk("every figure that draws hold the parent was found (eq, dd, regime per book)", len(par_figs) == 3 * len(BOOKS), str(len(par_figs)))
    for cap, _, did in par_figs:
        chk(f"figure {did}: its caption says the parent is rebuilt and that no published NAV exists before 2019-01-02", _html.escape(PARENT_NOTE) in cap or PARENT_NOTE in cap)
    for did in [f"eq|{b}" for b in BOOKS] + [f"dd|{b}" for b in BOOKS]:
        chk(f"hover labels of {did} say the parent is rebuilt", any(s_["k"] == "parent" and "rebuilt" in s_["label"] for s_ in lh.get(did, {}).get("series", [])))
    chk("the regime hover script labels the parent as rebuilt", "'Hold the parent (rebuilt, no published NAV)'" in html)

    # ── 9. hover data ─────────────────────────────────────────────────────────
    chk("line hover: one entry per book and kind, and the gap curve", sorted(lh) == sorted([f"{k}|{b}" for k in ("eq", "dd") for b in BOOKS] + ["gap|all"]))
    chk("line charts: one hover overlay and one tooltip each", html.count('class="lc-ov"') == 2 * len(BOOKS) + 1 and html.count('<div class="tip" hidden></div>') >= 2 * len(BOOKS) + 1)
    for b in BOOKS:
        cur = {k: NV(b, k) for k in ("segment", "whole_book", "parent", "constant_mix")}
        cl_ = cal[b]
        sel = np.unique(np.append(np.arange(0, len(cl_), 5), len(cl_) - 1))
        for kind in ("eq", "dd"):
            h = lh[f"{kind}|{b}"]
            vals = {k: (v if kind == "eq" else v / np.maximum.accumulate(v) - 1) for k, v in cur.items()}
            chk(f"line hover {kind}|{b}: series in legend order", [s["k"] for s in h["series"]] == list(cur))
            chk(f"line hover {kind}|{b}: plotted sessions and dates", h["n"] == len(sel) == len(h["dates"]) and h["dates"] == [cl_[i].strftime("%Y-%m-%d (%a)") for i in sel])
            for s in h["series"]:
                chk(f"line hover {kind}|{b}: {s['k']} values", len(s["v"]) == len(sel) and np.abs(np.array(s["v"]) - vals[s["k"]][sel]).max() < 6e-5)
            allv = np.concatenate([v[sel] for v in vals.values()])
            lo, hi = (math.log(allv.min() * 0.97), math.log(allv.max() * 1.03)) if kind == "eq" else (float(allv.min()) * 1.04, 0.0)
            chk(f"line hover {kind}|{b}: axis range", close(h["lo"], lo, 1e-9) and close(h["hi"], hi, 1e-9) and h["log"] == (kind == "eq") and h["fmt"] == ("x" if kind == "eq" else "pct"))
    h = lh["gap|all"]
    sel = np.unique(np.append(np.arange(0, len(c), 5), len(c) - 1))
    chk("gap curve: one series per book, plotted sessions and dates", [s["k"] for s in h["series"]] == BOOKS and h["n"] == len(sel) and h["dates"] == [c[i].strftime("%Y-%m-%d (%a)") for i in sel] and h["fmt"] == "lp")
    gv = {b: 100 * np.log(NV(b, "segment") / NV(b, "whole_book")) for b in BOOKS}
    for s in h["series"]:
        chk(f"gap curve {s['k']}: values are 100 x ln(rule / whole-book)", np.abs(np.array(s["v"]) - gv[s["k"]][sel]).max() < 6e-5)
    allg = np.concatenate([gv[b][sel] for b in BOOKS])
    chk("gap curve: axis range", close(h["lo"], math.floor(min(allg.min(), 0) / 5) * 5 - 5) and close(h["hi"], math.ceil(max(allg.max(), 0) / 5) * 5 + 5))
    for did, h in lh.items():
        m = re.search(r'<svg[^>]*data-id="' + re.escape(did) + r'"[^>]*>(.*?)</svg>', html, re.S)
        if not m:
            chk(f"svg for {did} exists", False)
            continue
        pls = re.findall(r'<polyline points="([^"]+)"', m.group(1))
        chk(f"{did}: one polyline per series", len(pls) == len(h["series"]))
        pw, ph = h["w"] - h["L"] - h["R"], h["h"] - h["T"] - h["B"]
        okp = True
        for pl, s in zip(pls, h["series"]):
            pts = [tuple(map(float, p_.split(","))) for p_ in pl.split()]
            okp &= len(pts) == h["n"]
            for j in (0, len(pts) // 2, len(pts) - 1):
                v = s["v"][j]
                yv = math.log(v) if h["log"] else v
                okp &= abs(pts[j][0] - (h["L"] + pw * j / (h["n"] - 1))) < 0.06 and abs(pts[j][1] - (h["T"] + ph * (1 - (yv - h["lo"]) / (h["hi"] - h["lo"])))) < 0.2
        chk(f"{did}: the polylines follow the hover arrays", okp)
    want = {f"hist|{b}|{w}" for b in BOOKS for w in ("cagr", "dd")}
    chk("bars-data holds exactly the expected charts", set(bd) == want, f"{sorted(set(bd) ^ want)}")
    chk("bar, band and regime charts: one hover overlay and one wrapping tooltip each", html.count('class="bc-ov"') == len(want) and html.count('<div class="tip wrap" hidden></div>') == len(want) + 2 * len(BOOKS))
    for b in BOOKS:
        s = S(b)
        d6, d8 = DD(b, "N4.6"), DD(b, "N4.8")
        for what, col, mark in (("cagr", "cagr", float(s.cagr)), ("dd", "max_dd", float(s.max_dd))):
            h = bd[f"hist|{b}|{what}"]
            a6, a8 = d6[col].values, d8[col].values
            lo_, hi_ = float(min(a6.min(), a8.min(), mark)), float(max(a6.max(), a8.max(), mark))
            pad = max((hi_ - lo_) * 0.04, 1e-9)
            edges = np.linspace(lo_ - pad, hi_ + pad, 33)
            c6, c8 = np.histogram(a6, bins=edges)[0], np.histogram(a8, bins=edges)[0]
            nm_ = f"hist {b} {what}"
            chk(f"{nm_}: edges", len(h["edges"]) == 33 and np.abs(np.array(h["edges"]) - edges).max() < 1e-7)
            sv_ = {x["k"]: x for x in h["series"]}
            chk(f"{nm_}: counts of both nulls", sv_["n46"]["v"] == [int(x) for x in c6] and sv_["n48"]["v"] == [int(x) for x in c8] and sv_["n46"]["n"] == sv_["n48"]["n"] == ND and sum(sv_["n46"]["v"]) == ND == sum(sv_["n48"]["v"]))
            mk = {m["label"]: m for m in h["marks"]}
            chk(f"{nm_}: marks are the rule and each null's median", close(mk["The rule"]["x"], mark, 1e-7) and close(mk["N4.6 median"]["x"], float(np.median(a6)), 1e-7) and close(mk["N4.8 median"]["x"], float(np.median(a8)), 1e-7))
            chk(f"{nm_}: the rule's percentiles in the tooltip", mk["The rule"]["txt"] == f"percentile {pctl(mark, a6)['percentile']:.1f} vs N4.6, {pctl(mark, a8)['percentile']:.1f} vs N4.8")
            fm = lambda v: f"{100 * v:.1f}%"
            chk(f"{nm_}: bin labels", h["binlab"] == [f"{fm(edges[i])} to {fm(edges[i + 1])}" for i in range(32)])

    def nice_top(hi, k=4):
        s_ = hi / k
        m = 10 ** math.floor(math.log10(s_))
        r = s_ / m
        stp = (1 if r < 1.5 else 2 if r < 3 else 5 if r < 7 else 10) * m
        v_, last_ = 0.0, 0.0
        while v_ <= hi + 1e-9:
            last_ = v_
            v_ += stp
        return last_
    for did, h in bd.items():
        m = re.search(r'<svg[^>]*data-id="' + re.escape(did) + r'"[^>]*>(.*?)</svg>', html, re.S)
        chk(f"svg for {did} exists", m is not None)
        if not m:
            continue
        rects = re.findall(r'<rect x="([\d.]+)" y="([\d.]+)" width="([\d.]+)" height="([\d.]+)" fill="(#[0-9a-f]{6})" opacity="([\d.]+)"/>', m.group(1))
        ytop = max(max(s_["v"]) for s_ in h["series"])
        chk(f"{did}: y axis maximum", close(h["ymax"], max(nice_top(ytop), ytop), 1e-9), f"{h['ymax']} vs {ytop}")
        exp = [(s_["col"], i, cc) for s_ in h["series"] for i, cc in enumerate(s_["v"]) if cc > 0]
        chk(f"{did}: one bar rectangle per non-empty bin and series ({len(exp)})", len(rects) == len(exp), f"{len(rects)} vs {len(exp)}")
        pw, ph = h["w"] - h["L"] - h["R"], h["h"] - h["T"] - h["B"]
        okb = True
        for (col, i, cc), (rx, ry, rw, rh, rc, ro) in zip(exp, rects):
            xl = h["L"] + pw * (h["edges"][i] - h["x0"]) / (h["x1"] - h["x0"]) + 0.4
            hh = ph * cc / h["ymax"]
            okb &= (rc == col and abs(float(rx) - xl) < 0.06 and abs(float(rh) - hh) < 0.06 and abs(float(ry) + float(rh) - (h["h"] - h["B"])) < 0.12)
        chk(f"{did}: every bar's position and height follow the arrays", okb)

    chk("band-data: one entry per book", sorted(bnd) == sorted(f"band|{b}" for b in BOOKS))
    chk("band charts: one hover overlay each", html.count('class="bd-ov"') == len(BOOKS))
    for b in BOOKS:
        h = bnd[f"band|{b}"]
        e, rows = EV[(b, "full")], ESK[(b, "full")]
        starts = [int(x) for x in e.trade_idx.values]
        nsb = nses[b]
        chk(f"band {b}: sessions, dates and event spans", h["n"] == nsb and h["dates"] == [d_.strftime("%Y-%m-%d (%a)") for d_ in cal[b]] and h["start"] == starts and h["end"] == starts[1:] + [nsb - 1])
        wt, nst_, on = [], [], []
        for q in range(len(e)):
            gq = rows[RI[(b, "full")] == q]
            tw = float(gq.listed_weight.sum())
            wt.append([round(float(gq[gq.band == bn].listed_weight.sum()) / tw, 5) for bn in BANDN])
            nst_.append([int((gq.band == bn).sum()) for bn in BANDN])
            on.append([str(e[f"state_{s}"].iloc[q]) == "BUY" for s in SIGN3])
        chk(f"band {b}: weights, stock counts and signals per event", np.abs(np.array(h["wt"]) - np.array(wt)).max() < 1.1e-5 and h["nst"] == nst_ and h["on"] == on)
        chk(f"band {b}: event labels, sleeve share, drops", h["no"] == [int(x) for x in e.event_no] and h["kind"] == [str(x) for x in e.kind] and h["tdate"] == [str(x) for x in e.trade_date] and h["beff"] == [str(x) for x in e.basket_eff]
            and np.abs(np.array(h["s"]) - e.sleeve_share_s.values).max() < 1.1e-5 and h["ndrop"] == [int(x) for x in e.n_dropped] and h["nheld"] == [int(x) for x in e.n_held])
        m = re.search(r'<svg[^>]*data-id="band\|' + b + r'"[^>]*>(.*?)</svg>', html, re.S)
        rects = re.findall(r'<rect x="([\d.]+)" y="([\d.]+)" width="([\d.]+)" height="([\d.]+)" fill="(#[0-9a-f]{6})" opacity="([\d.]+)"/>', m.group(1))
        exp = [(i, bi) for i in range(len(starts)) for bi in range(3) if h["wt"][i][bi] > 0]
        chk(f"band {b}: one rectangle per event and non-empty band ({len(exp)})", len(rects) == len(exp), f"{len(rects)}")
        pw, ph = h["w"] - h["L"] - h["R"], h["h"] - h["T"] - h["B"]
        okb = True
        for (i, bi), (rx, ry, rw, rh, rc, ro) in zip(exp, rects):
            acc_i = sum(h["wt"][i][:bi])
            x0 = h["L"] + pw * h["start"][i] / (h["n"] - 1)
            x1 = h["L"] + pw * h["end"][i] / (h["n"] - 1)
            okb &= abs(float(rx) - x0) < 0.02 and abs(float(rw) - max(x1 - x0, 0.4)) < 0.03 and abs(float(rh) - ph * h["wt"][i][bi]) < 0.03
            okb &= abs(float(ry) - (h["T"] + ph * (1 - (acc_i + h["wt"][i][bi])))) < 0.03 and rc == ["#6b4fbb", "#c9811a", "#2f9e6e"][bi] and abs(float(ro) - (0.95 if h["on"][i][bi] else 0.28)) < 1e-9
        chk(f"band {b}: every rectangle's position, height, colour and opacity follow the arrays", okb)

    chk("regime-data: one entry per book", sorted(rgd) == sorted(f"regime|{b}" for b in BOOKS))
    chk("regime charts: one hover overlay each", html.count('class="rg-ov"') == len(BOOKS))
    for b in BOOKS:
        h = rgd[f"regime|{b}"]
        w_ = WKB[b]
        nn_ = nses[b]
        idx = np.unique(np.append(np.arange(0, nn_, 3), nn_ - 1))
        sr, sw3, sp = NV(b, "segment"), NV(b, "whole_book"), NV(b, "parent")
        e = EV[(b, "full")]
        chk(f"regime {b}: sessions plotted and their dates", h["N"] == nn_ and h["idx"] == [int(i) for i in idx] and h["dates"] == [cal[b][i].strftime("%Y-%m-%d (%a)") for i in idx] and h["alldates"] == [d_.strftime("%Y-%m-%d") for d_ in cal[b]])
        chk(f"regime {b}: the three curves", all(np.abs(np.array(h[k]) - v[idx]).max() < 6e-5 for k, v in (("rule", sr), ("whole", sw3), ("parent", sp))))
        allv = np.concatenate([sr[idx], sw3[idx], sp[idx]])
        chk(f"regime {b}: axis range", close(h["lo"], math.log(allv.min() * 0.97)) and close(h["hi"], math.log(allv.max() * 1.03)))
        chk(f"regime {b}: weekly arrays (starts, signals, whole-book state, stretch index, stretch texts)", h["wk0"] == w_["wk0"] and h["sg"] == w_["sg"] and h["wst"] == w_["wst"] and h["wstr"] == w_["wstr"] and h["tips"] == w_["tips"])
        chk(f"regime {b}: event arrays (starts, share kept)", h["es"] == [int(x) for x in e.trade_idx] and np.abs(np.array(h["ek"]) - (1 - e.sleeve_share_s.values)).max() < 1.1e-5)
        m = re.search(r'<svg[^>]*data-id="regime\|' + b + r'"[^>]*>(.*?)</svg>', html, re.S)
        body = m.group(1)
        shade = re.findall(r'<rect x="([\d.]+)" y="8" width="([\d.]+)" height="[\d.]+" fill="#c9811a" opacity="0.16"/>', body)
        exp_sh = [(wk, w2) for wk, w2, s_ in zip(w_["wk0"], w_["wk0"][1:] + [nn_ - 1], w_["wstr"]) if s_ >= 0 and w2 > wk]
        okb = len(shade) == len(exp_sh)
        Lx, Rx = h["L"], h["R"]
        xx = lambda i: Lx + (h["w"] - Lx - Rx) * i / (nn_ - 1)
        for (sx, sw_a), (a_, b_) in zip(shade, exp_sh):
            okb &= abs(float(sx) - xx(a_)) < 0.06 and abs(float(sw_a) - max(xx(b_) - xx(a_), 0.6)) < 0.08
        chk(f"regime {b}: one shaded rectangle per week of a disagreement stretch", okb, f"{len(shade)} vs {len(exp_sh)}")
        for r_, colr in enumerate(("#6b4fbb", "#c9811a", "#2f9e6e")):
            rr_ = re.findall(r'<rect x="([\d.]+)" y="([\d.]+)" width="([\d.]+)" height="11" fill="' + colr + r'"/>', body)
            exp_r = [(wk, w2) for wk, w2, sgv in zip(w_["wk0"], w_["wk0"][1:] + [nn_ - 1], w_["sg"]) if sgv[r_] == 1 and w2 > wk]
            ok2 = len(rr_) == len(exp_r)
            for (sx, _, sw_a), (a_, b_) in zip(rr_, exp_r):
                ok2 &= abs(float(sx) - xx(a_)) < 0.06 and abs(float(sw_a) - max(xx(b_) - xx(a_), 0.6)) < 0.08
            chk(f"regime {b}: strip of {SIGN3[r_]} has one rectangle per BUY week", ok2, f"{len(rr_)} vs {len(exp_r)}")
        kb_ = re.findall(r'<rect x="([\d.]+)" y="([\d.]+)" width="([\d.]+)" height="([\d.]+)" fill="#2a6fdb"/>', body)
        exp_k = []
        for i in range(len(h["es"])):
            a_, b_ = h["es"][i], (h["es"][i + 1] if i + 1 < len(h["es"]) else nn_ - 1)
            if b_ > a_ and 11 * h["ek"][i] > 0:
                exp_k.append((a_, b_, 11 * h["ek"][i]))
        ok3 = len(kb_) == len(exp_k)
        for (sx, _, sw_a, shh), (a_, b_, hh) in zip(kb_, exp_k):
            ok3 &= abs(float(sx) - xx(a_)) < 0.06 and abs(float(sw_a) - max(xx(b_) - xx(a_), 0.6)) < 0.08 and abs(float(shh) - hh) < 0.02
        chk(f"regime {b}: one bar per event with its share kept", ok3, f"{len(kb_)} vs {len(exp_k)}")
        wb_ = re.findall(r'<rect x="([\d.]+)" y="([\d.]+)" width="([\d.]+)" height="11" fill="#1c1f24"/>', body)
        exp_w = [(wk, w2) for wk, w2, v_ in zip(w_["wk0"], w_["wk0"][1:] + [nn_ - 1], w_["wst"]) if v_ == 1 and w2 > wk]
        ok4 = len(wb_) == len(exp_w)
        for (sx, _, sw_a), (a_, b_) in zip(wb_, exp_w):
            ok4 &= abs(float(sx) - xx(a_)) < 0.06 and abs(float(sw_a) - max(xx(b_) - xx(a_), 0.6)) < 0.08
        chk(f"regime {b}: whole-book strip has one rectangle per IN week", ok4, f"{len(wb_)} vs {len(exp_w)}")

    print(f"check_page: {n} checks, {len(fails)} failures")
    for f in fails[:40]:
        print("FAIL", f)
    sys.exit(0 if (n > 0 and not fails) else 1)


if __name__ == "__main__":
    main()
