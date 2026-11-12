"""Independent check of the T07 results page. Imports nothing from the engine, verify_t07.py, tag_lookup.py, analyse.py or report.py.

    python tests/T07/check_page.py [--run headline]                     exit 0 = every check passed; non-zero on any failure or if nothing was compared
    python tests/T07/check_page.py --evidence DIR [--out DIR] [--expect-draws N] [--replay N]

1. Raw files -> decisions: re-derives every weekly decision (T0, then the last session of each ISO week; the latest Master row on or before the date) from the approved
   Master files and the approved extended published NAVs (both located through its own parse of data/APPROVED_DATA.md, so a SUPERSEDED row is never read), and compares
   dates, the three SIGN cells and the disagree flag with decisions.csv; the published parent NAV's CAGR and worst fall; the window end.
2. Inputs: every input the page lists is an APPROVED row (path, through-date, sha256 prefix, covering the window end) and the page's 'As of' date is the file's.
3. The whole page-data block is recomputed from the evidence by its own code and compared key for key (a key it does not recompute is a failure): the rule's, the
   comparators' and the nulls' statistics, the percentiles and p-values against both nulls, C3 and its bootstrap SE, R1-R6, the MDE, the calibration ratio, the null
   spreads, weight by band, the tag sources, the allowed-subset counts, reportability, the stretches, the verdict counts.
4. The worked example from the raw files: the tag of every held stock re-derived from the D23 panels with its own lookup; the targets; the cost; the allowed
   subsets by brute force; the N4.6 draw replayed from its seed against draw_drops.npz.
5. Every draw of both nulls in draw_drops.npz / draw_labels.npz holds its table (inside the held set, within tau of the rule's weight, labels per band equal the
   rule's counts); the first --replay N4.6 draws of every book are replayed from their seeds.
6. Page text carries the headline numbers as printed; the verifier's result and the gates in analysis.log.
7. Hover data: lines-data (every plotted session of every curve), bars-data (every bin), band-data (every event), regime-data (every plotted session, every week, every event,
   every stretch text), and the rectangles drawn in the SVGs against those arrays.
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

HERE = Path(__file__).resolve().parent
AA = HERE.parents[1]
BOOKS = ["SCMO_0003", "SCMO_0007", "SCMO_0010", "SCMO_0029"]


def v6_xmax(K: int, p: float = 0.10, alpha: float = 0.05 / 4) -> int:
    """AMENDMENT 2026-11-12: largest X with P(Binomial(K, p) >= X) >= alpha (one-sided, 4 books). K = 100: 17. Own copy: this check is independent."""
    tail = 0.0
    for X in range(K, -1, -1):
        tail += math.comb(K, X) * p ** X * (1 - p) ** (K - X)
        if tail >= alpha:
            return X
    return K
SIGN3 = ["Nifty100", "MC100", "SC100"]
BANDN = ["Large", "Mid", "Small and below"]
AA_OF = {"SCMO_0003": "SCMO_0042", "SCMO_0007": "SCMO_0043", "SCMO_0010": "SCMO_0044", "SCMO_0029": "SCMO_0045"}
fails, n = [], 0


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
    """Recursive comparison; returns the list of differences (also records one check per leaf)."""
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
            rows.append({"status": c[0], "id": c[1], "file": c[2], "through": c[3], "sha": c[4]})
    return asof, rows


def norm_detail(x):
    x = "" if x is None or (isinstance(x, float) and math.isnan(x)) else str(x).strip()
    return str(int(float(x))) if re.fullmatch(r"\d+(\.0+)?", x) else x


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="headline")
    ap.add_argument("--evidence", default=None)
    ap.add_argument("--out", default=None, help="directory of report.html and analysis.log")
    ap.add_argument("--expect-draws", type=int, default=2000)
    ap.add_argument("--doc", default=str(HERE / "T07.md"))
    ap.add_argument("--books", default=None, help="comma list; for engine smoke runs that hold fewer than the four books")
    ap.add_argument("--replay", type=int, default=200, help="N4.6 draws per book and window replayed from their seeds")
    a = ap.parse_args()
    if a.books:
        BOOKS[:] = a.books.split(",")
    B7 = "SCMO_0007" if "SCMO_0007" in BOOKS else BOOKS[-1]
    BNO = {"SCMO_0003": 0, "SCMO_0007": 1, "SCMO_0010": 2, "SCMO_0029": 3}
    ev_dir = Path(a.evidence) if a.evidence else HERE / "evidence" / a.run
    if a.out:
        logdir = outdir = Path(a.out)
    elif a.evidence:
        logdir = outdir = ev_dir
    else:
        logdir, outdir = HERE, ev_dir.parent
    ND = a.expect_draws
    html = (outdir / "report.html").read_text(encoding="utf-8")

    def block(i):
        return json.loads(re.search(rf'<script type="application/json" id="{i}">(.*?)</script>', html, re.S).group(1))

    page, lh, bd, bnd, rgd = block("page-data"), block("lines-data"), block("bars-data"), block("band-data"), block("regime-data")
    dec = pd.read_csv(ev_dir / "decisions.csv")
    evt = pd.read_csv(ev_dir / "events.csv")
    esk = pd.read_csv(ev_dir / "event_stocks.csv", keep_default_na=False, na_values=[""], dtype={"isin": str, "tag_detail": str})
    st = pd.read_csv(ev_dir / "stats.csv")
    dr = pd.read_csv(ev_dir / "draws.csv")
    nav = pd.read_csv(ev_dir / "daily_nav.csv", parse_dates=["date"])
    DR = np.load(ev_dir / "draw_drops.npz")
    DROP = {k: DR[k] for k in DR.files}
    LB = np.load(ev_dir / "draw_labels.npz")
    curves = np.load(ev_dir / "draw_curves_20.8.npz")
    asof, arows = approved_rows()
    appr = [r for r in arows if r["status"] == "APPROVED"]
    doc = Path(a.doc).read_text(encoding="utf-8")

    evt["pb"] = tf(evt["partial"])
    esk["kb"] = tf(esk["kept"])
    evt = evt.sort_values(["book", "window", "event_no"]).reset_index(drop=True)
    EV = {(b, w): g.reset_index(drop=True) for (b, w), g in evt.groupby(["book", "window"])}
    ESK = {(b, w): esk[(esk.book == b) & (esk.window == w)].reset_index(drop=True) for b in BOOKS for w in ("full", "live")}
    RI = {}
    for k, rows in ESK.items():
        pos = {int(x): i for i, x in enumerate(EV[k].event_no.values)}
        RI[k] = np.array([pos[int(x)] for x in rows.event_no.values])

    # ── 1. raw files -> decisions, calendar, published NAV ────────────────────
    ms = {}
    for nme in ("Nifty100", "MC100", "SC100"):
        rr = [r for r in appr if r["file"].endswith(f"Master_{nme}.xlsx")]
        chk(f"one APPROVED Master row for {nme}", len(rr) == 1, str(len(rr)))
        d = pd.read_excel(AA / rr[0]["file"], parse_dates=["Date"])
        ms[nme] = d.dropna(subset=["SIGN"]).set_index("Date")["SIGN"].sort_index()
    window_end = min(s.index[-1] for s in ms.values())
    chk("the window end is the last Master date (the earliest end of the three)", str(window_end.date()) == page["end"], f"{window_end.date()} vs {page['end']}")
    cal, dates_of, sg_of, pub = {}, {}, {}, {}
    for b in BOOKS:
        rr = [r for r in appr if r["id"] == "D17" and "extended_2026-11-06" in r["file"] and r["file"].replace("\\", "/").endswith(f"/{b}.csv")]
        chk(f"one APPROVED extended published-NAV row for {b}", len(rr) == 1, str(len(rr)))
        raw = pd.read_csv(AA / rr[0]["file"])
        raw["d"] = pd.to_datetime(raw["_id.date"], format="%Y/%m/%d")
        raw = raw.sort_values("d")
        raw = raw[raw.d <= window_end]
        c = pd.DatetimeIndex(raw.d.values)
        cal[b] = c
        iso = c.isocalendar()
        last = sorted(pd.Series(c, index=c).groupby([iso.year.values, iso.week.values]).max().values)
        dates = [c[0]] + [pd.Timestamp(x) for x in last if pd.Timestamp(x) > c[0]]
        dates_of[b] = dates
        trip = []
        for d_ in dates:
            trip.append([str(s.iloc[s.index.searchsorted(d_, side="right") - 1]) for s in ms.values()])
        sg_of[b] = trip
        e = dec[dec.book == b].sort_values("j").reset_index(drop=True)
        chk(f"{b} number of decisions", len(e) == len(dates) == page["weeks"][b], f"{len(e)} vs {len(dates)}")
        chk(f"{b} decision dates", list(pd.to_datetime(e.decision_date)) == dates)
        chk(f"{b} sign cells", [[e.loc[j, f"sign_{s}"] for s in SIGN3] for j in range(len(e))] == trip, "differ")
        chk(f"{b} disagree and all_three_buy flags", list(tf(e["disagree"])) == [len(set(t)) > 1 for t in trip] and list(tf(e["all_three_buy"])) == [all(x == "BUY" for x in t) for t in trip])
        nvs = nav[(nav.book == b) & (nav.cost_bps == 20.8) & (nav.run == "segment")].sort_values("date")
        chk(f"{b} NAV calendar is the published calendar up to the window end", list(nvs.date) == list(c))
        r_ = raw["index"].values / raw["index"].values[0]
        pub[b] = (cagr(r_), mdd(r_))
        pr = st[(st.book == b) & (st.kind == "published_parent")].iloc[0]
        chk(f"{b} published CAGR and worst fall equal stats.csv's published_parent row", close(float(pr.cagr), pub[b][0]) and close(float(pr.max_dd), pub[b][1]), f"{pr.cagr} {pub[b]}")
    chk("start dates", page["start"] == str(cal[BOOKS[0]][0].date()) and page["start_0007"] == str(cal[B7][0].date()))
    live_i = {b: int(np.searchsorted(cal[b].values, np.datetime64(pd.Timestamp("2021-11-01")))) for b in BOOKS}
    chk("live window first session", page["live_first"] == str(cal[BOOKS[0]][live_i[BOOKS[0]]].date()))

    # ── 2. inputs ─────────────────────────────────────────────────────────────
    chk("page's As-of date is APPROVED_DATA.md's", page["as_of_file"] == asof and asof in html, f"{page['as_of_file']} vs {asof}")
    rec_ = None
    for l in (ev_dir / "inputs.csv").read_text(encoding="utf-8").splitlines():
        if l.startswith("#") and re.search(r"\d{4}-\d{2}-\d{2}", l):
            rec_ = re.search(r"\d{4}-\d{2}-\d{2}", l).group(0)
    if rec_ is None:
        au = json.loads((ev_dir / "audit.json").read_text(encoding="utf-8"))
        rec_ = au.get("approved_data_as_of") or (au.get("data") or {}).get("approved_data_as_of")
    chk("the run recorded the same As-of date and the page prints it", page["as_of_inputs"] == rec_ == asof and rec_ in html, f"{page['as_of_inputs']} / {rec_} vs {asof}")
    byfile = {r["file"].replace("\\", "/"): r for r in arows}
    chk("inputs listed", len(page["inputs"]) > 10, str(len(page["inputs"])))
    inp_csv = pd.read_csv(ev_dir / "inputs.csv", comment="#", dtype=str, keep_default_na=False)
    chk("the page lists exactly the rows of inputs.csv (file, through, approved row, sha256 prefix)", page["inputs"] == [{"file": r.file, "through": r.through, "approved_row": r.approved_row, "sha16": r.sha256[:16]} for r in inp_csv.itertuples()])
    for r in page["inputs"]:
        ar = byfile.get(r["file"].replace("\\", "/"))
        chk(f"input {r['file']} is a row of APPROVED_DATA.md", ar is not None)
        if ar is not None:
            chk(f"input {r['file']} is APPROVED, not superseded or pending", ar["status"] == "APPROVED", ar["status"])
            chk(f"input {r['file']} through-date", r["through"] == ar["through"], f"{r['through']} vs {ar['through']}")
            chk(f"input {r['file']} sha256 prefix", ar["sha"].startswith(r["sha16"][:len(ar["sha"])]) or r["sha16"].startswith(ar["sha"]), f"{r['sha16']} vs {ar['sha']}")
            full_sha = inp_csv[inp_csv.file == r["file"]].sha256.iloc[0]
            chk(f"input {r['file']} sha256 of the file on disk equals the run's record", hashlib.sha256((AA / r["file"]).read_bytes()).hexdigest() == full_sha)
            if re.match(r"\d{4}-\d{2}-\d{2}$", ar["through"]) and all(w_ not in ar["file"] for w_ in ("holding_weight", "Rebalance_history", "mauc1", "_columns", "_sources")):
                chk(f"input {r['file']} covers the window end", ar["through"] >= page["end"], ar["through"])
            chk(f"page's table row for {r['file']} shows its through-date, row and sha256 prefix",
                f"<tr><td>{_html.escape(r['file'])}</td><td>{_html.escape(ar['through'])}</td><td>{_html.escape(r['approved_row'])}</td><td>{_html.escape(r['sha16'])}</td></tr>" in html)
    # the caveats paragraph of T07.md section 3, verbatim (plain text)
    i0 = doc.index("**Caveats of the tag data, to be stated on the page**")
    para = doc[i0:doc.index("\n", i0)].replace("\r", "").replace("**", "").replace("`", "").split("):", 1)[1]
    cav = [x.strip() for x in re.split(r"\s*\(\d\)\s*", para)[1:]]
    chk("the page's caveats are the five of T07.md section 3", page["caveats"] == cav and len(cav) == 5, str(len(cav)))
    for c_ in cav:
        chk("page prints a caveat", _html.escape(c_) in html)

    # ── 3. page-data recomputed ───────────────────────────────────────────────
    S = lambda b, kind="segment", cost=20.8, win="full", cash="lbes": st[(st.book == b) & (st.window == win) & (st.cash == cash) & (st.cost_bps == cost) & (st.kind == kind)].iloc[0]
    DD = lambda b, typ, cost=20.8, win="full", cash="lbes": dr[(dr.book == b) & (dr.window == win) & (dr.cash == cash) & (dr.cost_bps == cost) & (dr.draw_type == typ)].sort_values("draw_id")
    NV = lambda b, run, cost=20.8: nav[(nav.book == b) & (nav.cost_bps == cost) & (nav.run == run)].sort_values("date").nav.values
    nses = {b: len(cal[b]) for b in BOOKS}
    chk("page's draws", page["draws"] == ND == len(DD(BOOKS[0], "N4.6")), f"{page['draws']} {ND}")
    chk("page's run name", page["run"] == ev_dir.name)
    chk("page's hash is T07.md's header", page["prereg_sha256"] in doc and page["prereg_sha256"][:12] in html)
    chk("page's weeks", page["weeks"] == {b: len(sg_of[b]) for b in BOOKS})
    chk("page's end", page["end"] == str(cal[BOOKS[0]][-1].date()))
    EXP = {}
    for b in BOOKS:
        s = S(b)
        vr, vw = NV(b, "segment"), NV(b, "whole_book")
        # moving-block bootstrap of CAGR(rule) - CAGR(whole-book), resample by resample
        lr, lw_ = np.log(vr[1:] / vr[:-1]), np.log(vw[1:] / vw[:-1])
        T = len(lr)
        rg = np.random.default_rng([10, BNO[b]])
        starts = rg.integers(0, T - 20 + 1, size=(1000, int(math.ceil(T / 20))))
        diffs = []
        for row in starts:
            ix = np.concatenate([np.arange(x, x + 20) for x in row])[:T]
            diffs.append(math.expm1(lr[ix].sum() / (T / 252)) - math.expm1(lw_[ix].sum() / (T / 252)))
        se = float(np.std(diffs, ddof=1))
        sw = S(b, "whole_book")
        bb = {"cagr": cagr(vr), "max_dd": mdd(vr), "end_nav": float(vr[-1]), "trades": int(s.trades), "cost_paid": float(s.cost_paid), "sessions_total": nses[b] - 1, "events": len(EV[(b, "full")]),
              "whole_cagr": cagr(vw), "whole_dd": mdd(vw), "whole_trades": int(sw.trades), "whole_cost": float(sw.cost_paid), "c3_diff": cagr(vr) - cagr(vw), "c3_se": se}
        for run, kk in (("parent", "parent"), ("constant_mix", "mix"), ("sleeve100", "sleeve")):
            v = NV(b, run)
            bb[f"{kk}_cagr"], bb[f"{kk}_dd"] = cagr(v), mdd(v)
        bb["pub_cagr"], bb["pub_dd"] = pub[b]
        for c in (0.0, 50.0):
            bb[f"c3_diff_{c:g}"] = cagr(NV(b, "segment", c)) - cagr(NV(b, "whole_book", c))
        for win in ("full", "live"):
            d_ = dec[dec.book == b].sort_values("j")
            dis = tf(d_["disagree"])
            if win == "live":
                dis = dis[(pd.to_datetime(d_.decision_date) >= cal[b][live_i[b]]).values]
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
            for c in (0.0, 50.0):
                vv = NV(b, "segment", c)
                nc = DD(b, typ, c)
                bb[f"{nm}_pct_cagr_{c:g}"] = pctl(cagr(vv), nc.cagr.values)["percentile"]
                bb[f"{nm}_pct_dd_{c:g}"] = pctl(mdd(vv), nc.max_dd.values)["percentile"]
                bb[f"{nm}_med_trades_{c:g}"], bb[f"{nm}_med_cost_{c:g}"] = float(np.median(nc.trades.values)), float(np.median(nc.cost_paid.values))
            sl = S(b, win="live")
            nl = DD(b, typ, win="live")
            bb[f"{nm}_live_pct_cagr"] = pctl(float(sl.cagr), nl.cagr.values)["percentile"] if bb["live_reportable"] else None
            bb[f"{nm}_live_pct_dd"] = pctl(float(sl.max_dd), nl.max_dd.values)["percentile"] if bb["live_reportable"] else None
            bb[f"{nm}_liq_pct"] = pctl(float(S(b, cash="liq").cagr), DD(b, typ, cash="liq").cagr.values)["percentile"]
        sl, slw = S(b, win="live"), S(b, "whole_book", win="live")
        bb.update({"live_cagr": float(sl.cagr), "live_whole_cagr": float(slw.cagr), "live_c3": float(sl.cagr - slw.cagr), "live_sessions": int(sl.sessions), "liq_cagr": float(S(b, cash="liq").cagr)})
        fil = [r for r in appr if r["id"] == "D15" and r["file"].replace("\\", "/").endswith(f"/{AA_OF[b]}.csv")]
        chk(f"one APPROVED D15 row for {AA_OF[b]}", len(fil) == 1)
        raw = pd.read_csv(AA / fil[0]["file"])
        raw["d"] = pd.to_datetime(raw["_id.date"], format="%Y/%m/%d")
        raw = raw.sort_values("d")
        sub = raw[(raw.d >= cal[b][live_i[b]]) & (raw.d <= cal[b][-1])]["index"].values
        bb["aa_live_cagr"], bb["aa_sessions"], bb["aa_book"] = cagr(sub / sub[0]), int(len(sub)), AA_OF[b]
        # weight by band, tag sources, allowed subsets, gaps (loops, not the report's vectorisation)
        e, rows = EV[(b, "full")], ESK[(b, "full")]
        span = [max(int(e.trade_idx.iloc[q + 1]) - int(e.trade_idx.iloc[q]), 0) if q + 1 < len(e) else max(nses[b] - 1 - int(e.trade_idx.iloc[q]), 0) for q in range(len(e))]
        ew, sw2, dsh, tagw = np.zeros(3), np.zeros(3), np.zeros(3), {"rank": 0.0, "membership": 0.0, "nonmember_rank": 0.0, "unranked": 0.0}
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
        # allowed subsets by brute force; compare with events.csv
        al = []
        for q in range(len(e)):
            g = rows[RI[(b, "full")] == q].sort_values("isin", kind="stable")
            sums = subset_sums(g.listed_weight.values.astype(float))
            cnt_ = int((np.abs(sums - float(e.dropped_weight.iloc[q])) <= float(e.tau.iloc[q]) + 1e-12).sum())
            al.append(cnt_)
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
    # verdict counts
    cn = lambda key: sum(bool((EXP[b][key] or 0) >= 90) and EXP[b]["full_reportable"] for b in BOOKS)
    cl = lambda key: sum(bool((EXP[b][key] or 0) >= 90) for b in BOOKS)
    deep("page-data verdict", page["verdict"], {"C1_N46": cn("n46_pct_cagr"), "C2_N46": cn("n46_pct_dd"), "C1_N48": cn("n48_pct_cagr"), "C2_N48": cn("n48_pct_dd"),
                                                "C3": sum(EXP[b]["c3_diff"] > 0 and EXP[b]["full_reportable"] for b in BOOKS), "R2_C1_N46": cl("n46_live_pct_cagr"), "R2_C2_N46": cl("n46_live_pct_dd"),
                                                "R2_C1_N48": cl("n48_live_pct_cagr"), "R2_C3": sum(EXP[b]["live_c3"] > 0 for b in BOOKS), "R3_N46": cl("n46_liq_pct"), "R3_N48": cl("n48_liq_pct")})
    cs = pd.read_csv(ev_dir / "controls_negative.csv") if (ev_dir / "controls_negative.csv").exists() else None
    exp6 = None
    if cs is not None:
        exp6 = {}
        for b in BOOKS:
            K = int((cs.book == b).sum())
            sh = float((cs[cs.book == b].percentile >= 90).mean())
            exp6[b] = {"K": K, "share": sh, "lo": 0.0, "hi": v6_xmax(K) / K, "within": bool(K >= 100 and round(sh * K) <= v6_xmax(K))}
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

        def fk(o, names):
            if isinstance(o, dict):
                for k_, v_ in o.items():
                    if str(k_).lower() in names and not isinstance(v_, (dict, list)):
                        return v_
                for v_ in o.values():
                    r_ = fk(v_, names)
                    if r_ is not None:
                        return r_
            if isinstance(o, list):
                for v_ in o:
                    r_ = fk(v_, names)
                    if r_ is not None:
                        return r_
            return None
        exp7 = {}
        for b in BOOKS:
            d_ = pb_(oo, b)
            cg = fk(d_, {"cagr", "oracle_cagr", "after_cost_cagr"}) if d_ else None
            st_ = fk(d_, {"percentile", "pct", "oracle_percentile", "percentile_vs_n46", "pct_n46"}) if d_ else None
            own = pctl(float(cg), DD(b, "N4.6").cagr.values)["percentile"] if cg is not None else None
            exp7[b] = {"cagr": None if cg is None else float(cg), "stated": None if st_ is None else float(st_), "pct": own if own is not None else (None if st_ is None else float(st_))}
    deep("page-data v7", page["v7"], exp7)
    chk("page-data has exactly the expected top-level keys", set(page) == {"run", "prereg_sha256", "draws", "as_of_file", "as_of_inputs", "end", "start", "start_0007", "live_first", "weeks", "books", "gates", "verdict", "v6", "v7", "stretches",
                                                                      "stretch_ahead", "stretch_n", "example", "inputs", "caveats"}, str(sorted(page)))

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
        wstr, strs, j = [-1] * nw, [], 0
        while j < nw:
            if dis[j]:
                k = j
                while k + 1 < nw and dis[k + 1]:
                    k += 1
                pats = []
                for q in range(j, k + 1):
                    p_ = "".join("B" if x else "S" for x in sgm[q])
                    if p_ not in pats:
                        pats.append(p_)
                strs.append({"s": wk0[j], "e": wend[k], "from": str(d_.decision_date.iloc[j]), "to": str(d_.decision_date.iloc[k]), "weeks": k - j + 1, "patterns": "→".join(pats)})
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
        row = {"from": s0["from"], "to": s0["to"], "weeks": s0["weeks"], "patterns": s0["patterns"], "diff": {}, "rule": {}, "whole": {}}
        for b in BOOKS:
            m = [x for x in WKB[b]["strs"] if x["from"] == s0["from"] and x["to"] == s0["to"]]
            if m:
                rr = NV(b, "segment")[m[0]["e"]] / NV(b, "segment")[m[0]["s"]] - 1
                ww = NV(b, "whole_book")[m[0]["e"]] / NV(b, "whole_book")[m[0]["s"]] - 1
                row["diff"][b], row["rule"][b], row["whole"][b] = float(rr - ww), float(rr), float(ww)
                nn[b] += 1
                ahead[b] += int(rr - ww > 0)
            else:
                row["diff"][b] = row["rule"][b] = row["whole"][b] = None
        exp_st.append(row)
    deep("page-data stretches", page["stretches"], exp_st)
    deep("page-data stretch counts", {"a": page["stretch_ahead"], "n": page["stretch_n"]}, {"a": ahead, "n": nn})

    # ── 4. the worked example from raw files ──────────────────────────────────
    ex = page["example"]
    b = BOOKS[0]
    e0, r0 = EV[(b, "full")], ESK[(b, "full")]
    cand = [q for q in range(len(e0)) if e0.event_no.iloc[q] > 0 and e0.pb.iloc[q]]
    qx = cand[0] if cand else 0
    chk("example is the first partial event after the initial one of the first book", ex["book"] == b and ex["pos"] == qx + 1 and ex["event_no"] == int(e0.event_no.iloc[qx]))
    rowe = e0.iloc[qx]
    g = r0[RI[(b, "full")] == qx].reset_index(drop=True)
    info = pd.Timestamp(rowe.info_date)
    chk("example: info date is the session before the trade session", cal[b][list(cal[b]).index(pd.Timestamp(rowe.trade_date)) - 1] == info and int(rowe.trade_idx) == list(cal[b]).index(pd.Timestamp(rowe.trade_date)))
    jd = max(j for j, d_ in enumerate(dates_of[b]) if d_ < pd.Timestamp(rowe.trade_date))
    chk("example: decision week and date", ex["decision_week"] == jd and ex["decision_date"] == str(dates_of[b][jd].date()))
    chk("example: the signals", ex["signs"] == sg_of[b][jd] and ex["states"] == [str(rowe.state_Nifty100), str(rowe.state_MC100), str(rowe.state_SC100)] == sg_of[b][jd])
    chk("example: labels are Master row dates on or before the decision", all(pd.Timestamp(x) <= dates_of[b][jd] for x in ex["labels"]) and ex["labels"] == [str(x) for x in dec[(dec.book == b) & (dec.j == jd)][[f"label_{s}" for s in SIGN3]].iloc[0]])
    # tags from the D23 panels with an own lookup
    rank_f = [r for r in appr if r["file"].endswith("tags/mcap_rank_panel.csv")]
    mem_f = [r for r in appr if r["file"].endswith("tags/membership_panel.csv")]
    sym_f = [r for r in appr if r["file"].endswith("symbology/symbology_changes.csv")]
    chk("one APPROVED row for each D23 panel and D22", len(rank_f) == len(mem_f) == len(sym_f) == 1)
    rk = pd.read_csv(AA / rank_f[0]["file"], usecols=["date", "quote_id", "isin", "rank", "band"], dtype={"isin": str}, keep_default_na=False, na_values=[""])
    rk["date"] = pd.to_datetime(rk["date"])
    mp = pd.read_csv(AA / mem_f[0]["file"], dtype=str, keep_default_na=False, na_values=[""])
    mp["snapshot_date"] = pd.to_datetime(mp["snapshot_date"])
    sy = pd.read_csv(AA / sym_f[0]["file"], usecols=["quote_id", "isin", "new_isin"], dtype=str, keep_default_na=False, na_values=[""])
    cutoff = mp.snapshot_date.min()
    tag_ok, tag_n = True, 0
    for x in g.itertuples():
        ids = {x.isin}
        qids = set(sy[(sy["isin"] == x.isin) | (sy["new_isin"] == x.isin)].quote_id.dropna()) | set(rk[rk["isin"] == x.isin].quote_id.dropna())
        for q_ in qids:
            ids |= set(sy[sy.quote_id == q_]["isin"].dropna()) | set(sy[sy.quote_id == q_].new_isin.dropna()) | set(rk[rk.quote_id == q_]["isin"].dropna())
        band = src = snap = det = None
        if info >= cutoff:
            sd = mp[mp.snapshot_date <= info].snapshot_date.max()
            m_ = mp[(mp.snapshot_date == sd) & mp["isin"].isin(ids)]
            if len(m_):
                band, src, snap, det = m_.iloc[0].band, "membership", str(sd.date()), m_.iloc[0].index_name
        if band is None:
            sd = rk[rk.date <= info].date.max()
            m_ = rk[(rk.date == sd) & rk["isin"].isin(ids)]
            if len(m_):
                band, src, snap, det = m_.iloc[0].band, ("nonmember_rank" if info >= cutoff else "rank"), str(sd.date()), str(int(m_.iloc[0]["rank"]))
            else:
                band, src, snap, det = "Small and below", "unranked", str(sd.date()), ""
        tag_n += 1
        ok_ = (x.band == band and x.tag_source == src and str(x.tag_snapshot)[:10] == snap and norm_detail(x.tag_detail) == norm_detail(det))
        tag_ok &= ok_
        if not ok_:
            fails.append(f"example tag differs for {x.isin}: engine {x.band}/{x.tag_source}/{x.tag_snapshot}/{x.tag_detail} vs {band}/{src}/{snap}/{det}")
        chk(f"example tag of {x.isin} equals the D23 panels' (band, source, snapshot, rank or index)", ok_)
        chk(f"example kept flag of {x.isin} is its band's signal BUY", bool(x.kb) == (sg_of[b][jd][BANDN.index(x.band)] == "BUY"))
        chk(f"example band signal of {x.isin} is the SIGN of its band's index", str(x.band_signal) == sg_of[b][jd][BANDN.index(x.band)], f"{x.band_signal}")
    chk("example tags were compared", tag_n == ex["n_held"] == len(ex["rows"]) == len(g), f"{tag_n}")
    deep("example rows", ex["rows"], [{"stock": str(x.stock), "isin": str(x.isin), "w": float(x.listed_weight), "band": str(x.band), "src": str(x.tag_source), "snap": str(x.tag_snapshot), "detail": "" if pd.isna(x.tag_detail) else str(x.tag_detail),
                                      "via": str(x.tag_via), "sig": str(x.band_signal), "kept": bool(x.kb)} for x in g.itertuples()])
    sw_, D_ = float(g.listed_weight.sum()), float(g.listed_weight[~g.kb].sum())
    chk("example: sum of weights, D, s and the events.csv row", close(ex["sum_w"], sw_) and close(ex["D"], D_) and close(ex["s"], D_ / sw_) and close(ex["ev_D"], D_) and close(ex["ev_s"], D_ / sw_) and ex["n_held"] == len(g) == int(rowe.n_held) and ex["n_dropped"] == int((~g.kb).sum()) == int(rowe.n_dropped), f"{ex['D']} {D_}")
    chk("example: tau is half the smallest listed weight", close(ex["tau"], float(g.listed_weight.min()) / 2))
    chk("example: cost on the page is traded x 20.8 / 2 / 10,000 (events.csv's cost equals it)", close(ex["cost"], ex["traded"] * 20.8 / 2 / 10000, 1e-9) and close(ex["traded"], float(rowe.traded)) and close(ex["V"], float(rowe.V_before)))
    gs = g.sort_values("isin", kind="stable").reset_index(drop=True)
    sums = subset_sums(gs.listed_weight.values.astype(float))
    allowed = np.flatnonzero(np.abs(sums - D_) <= ex["tau"] + 1e-12)
    chk("example: allowed subsets by brute force", ex["n_allowed"] == len(allowed) == int(rowe.n_allowed_subsets), f"{ex['n_allowed']} {len(allowed)}")
    u = float(np.random.default_rng([7, 0, BNO[b]]).random(len(e0))[qx])
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
    chk("example: the NAV rows around the trade", ex["nav_around"] == [{"date": str(nvs.date.iloc[i].date()), "rule": float(nvs.nav.iloc[i]), "whole": float(nvw.nav.iloc[i])} for i in range(k0 - 2, k0 + 3)])
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

    # ── 5. every draw of both nulls, and replays ──────────────────────────────
    nd_, nbad_, nrep, nrep_bad = 0, 0, 0, 0
    for b in BOOKS:
        for win in ("full", "live"):
            e, rows = EV[(b, win)], ESK[(b, win)]
            ri = RI[(b, win)]
            E_, R_ = len(e), len(rows)
            w = rows.listed_weight.values.astype(float)
            Dq, tau = e.dropped_weight.values.astype(float), e.tau.values.astype(float)
            for typ in ("N4.6", "N4.8"):
                A = DROP[f"{b}|{win}|{typ}"].astype(np.int8)
                chk(f"drops {b}|{win}|{typ} shape (draws, rows of event_stocks.csv)", A.shape == (ND, R_), str(A.shape))
                nd_ += A.shape[0]
                if typ == "N4.6":
                    bad = np.zeros(A.shape[0], bool)
                    for q in range(E_):
                        cols = np.flatnonzero(ri == q)
                        dw = A[:, cols].astype(float) @ w[cols]
                        bad |= np.abs(dw - Dq[q]) > tau[q] + 1e-9
                        if int(e.n_dropped.iloc[q]) == 0:
                            bad |= A[:, cols].sum(1) != 0
                        if int(e.n_dropped.iloc[q]) == int(e.n_held.iloc[q]):
                            bad |= A[:, cols].sum(1) != len(cols)
                else:
                    L = LB[f"{b}|{win}|{typ}"].astype(int)
                    bad = np.zeros(A.shape[0], bool)
                    for q in range(E_):
                        cols = np.flatnonzero(ri == q)
                        for li, cn_ in enumerate(("n_large", "n_mid", "n_small")):
                            bad |= (L[:, cols] == li).sum(1) != int(e[cn_].iloc[q])
                        sig = [str(e[f"state_{s}"].iloc[q]) for s in SIGN3]
                        for d_ in range(A.shape[0]):
                            pass
                        exp_drop = np.array([[1 if sig[l_] == "SELL" else 0 for l_ in row] for row in L[:, cols]])
                        bad |= (exp_drop != A[:, cols]).any(1)
                nbad_ += int(bad.sum())
                if typ == "N4.6":
                    for d_ in range(min(a.replay, A.shape[0])):
                        rg = np.random.default_rng([7, d_, BNO[b]])
                        uu = rg.random(E_)
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

    # ── 6. page text, verifier, gates ─────────────────────────────────────────
    for b in BOOKS:
        pb = EXP[b]
        for txt in (f"{pb['n46_pct_cagr']:.1f}", f"{pb['n46_pct_dd']:.1f}", f"{pb['n48_pct_cagr']:.1f}", f"{pb['n48_pct_dd']:.1f}", f"{100 * pb['cagr']:.1f}%", f"{100 * pb['max_dd']:.1f}%", f"{pb['n46_p_cagr']:.3f}",
                    f"{100 * pb['c3_diff']:+.2f}", f"{100 * pb['whole_cagr']:.1f}%", f"{100 * pb['c3_se']:.2f}"):
            chk(f"{b} page prints {txt}", txt in html)
        chk(f"{b} page prints its live-only CAGR and C3", f"{100 * pb['live_cagr']:.1f}%" in html and f"{100 * pb['live_c3']:+.2f}" in html)
    chk("page prints the window and the draws count", page["start"] in html and page["end"] in html and page["start_0007"] in html and f"{ND:,}" in html)
    vj = ev_dir / "verify_t07.json"
    chk("verify_t07.json exists", vj.exists())
    if vj.exists():
        v = json.loads(vj.read_text(encoding="utf-8"))
        chk("verifier passed", bool(v.get("exit_ok", True)) and v.get("gate_failures_and_missing", 0) == 0, "verify_t07.json does not say passed")
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

    # ── 7. hover data ─────────────────────────────────────────────────────────
    chk("line hover: one entry per book and kind", sorted(lh) == sorted([f"{k}|{b}" for k in ("eq", "dd") for b in BOOKS]))
    chk("line charts: one hover overlay and one tooltip each", html.count('class="lc-ov"') == 2 * len(BOOKS) and html.count('<div class="tip" hidden></div>') >= 2 * len(BOOKS))
    for b in BOOKS:
        cur = {k: NV(b, k) for k in ("segment", "whole_book", "parent", "constant_mix")}
        cl = cal[b]
        sel = np.unique(np.append(np.arange(0, len(cl), 5), len(cl) - 1))
        for kind in ("eq", "dd"):
            h = lh[f"{kind}|{b}"]
            vals = {k: (v if kind == "eq" else v / np.maximum.accumulate(v) - 1) for k, v in cur.items()}
            chk(f"line hover {kind}|{b}: series in legend order", [s["k"] for s in h["series"]] == list(cur))
            chk(f"line hover {kind}|{b}: plotted sessions and dates", h["n"] == len(sel) == len(h["dates"]) and h["dates"] == [cl[i].strftime("%Y-%m-%d (%a)") for i in sel])
            for s in h["series"]:
                chk(f"line hover {kind}|{b}: {s['k']} values", len(s["v"]) == len(sel) and np.abs(np.array(s["v"]) - vals[s["k"]][sel]).max() < 6e-5)
            allv = np.concatenate([v[sel] for v in vals.values()])
            lo, hi = (math.log(allv.min() * 0.97), math.log(allv.max() * 1.03)) if kind == "eq" else (float(allv.min()) * 1.04, 0.0)
            chk(f"line hover {kind}|{b}: axis range", close(h["lo"], lo, 1e-9) and close(h["hi"], hi, 1e-9) and h["log"] == (kind == "eq") and h["fmt"] == ("x" if kind == "eq" else "pct"))
    want = {f"hist|{b}|{w}" for b in BOOKS for w in ("cagr", "dd")}
    chk("bars-data holds exactly the expected charts", set(bd) == want, f"{sorted(set(bd) ^ want)}")
    chk("bar charts: one hover overlay and one tooltip each", html.count('class="bc-ov"') == len(want) and html.count('<div class="tip wrap" hidden></div>') == len(want))
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
        v_, last = 0.0, 0.0
        while v_ <= hi + 1e-9:
            last = v_
            v_ += stp
        return last
    for did, h in bd.items():
        m = re.search(r'<svg[^>]*data-id="' + re.escape(did) + r'"[^>]*>(.*?)</svg>', html, re.S)
        chk(f"svg for {did} exists", m is not None)
        if not m:
            continue
        rects = re.findall(r'<rect x="([\d.]+)" y="([\d.]+)" width="([\d.]+)" height="([\d.]+)" fill="(#[0-9a-f]{6})" opacity="([\d.]+)"/>', m.group(1))
        ytop = max(max(s_["v"]) for s_ in h["series"])
        chk(f"{did}: y axis maximum", close(h["ymax"], max(nice_top(ytop), ytop), 1e-9), f"{h['ymax']} vs {ytop}")
        exp = [(s_["col"], i, c) for s_ in h["series"] for i, c in enumerate(s_["v"]) if c > 0]
        chk(f"{did}: one bar rectangle per non-empty bin and series ({len(exp)})", len(rects) == len(exp), f"{len(rects)} vs {len(exp)}")
        pw, ph = h["w"] - h["L"] - h["R"], h["h"] - h["T"] - h["B"]
        okb = True
        for (col, i, c), (rx, ry, rw, rh, rc, ro) in zip(exp, rects):
            xl = h["L"] + pw * (h["edges"][i] - h["x0"]) / (h["x1"] - h["x0"]) + 0.4
            hh = ph * c / h["ymax"]
            okb &= (rc == col and abs(float(rx) - xl) < 0.06 and abs(float(rh) - hh) < 0.06 and abs(float(ry) + float(rh) - (h["h"] - h["B"])) < 0.12)
        chk(f"{did}: every bar's position and height follow the arrays", okb)

    chk("band-data: one entry per book", sorted(bnd) == sorted(f"band|{b}" for b in BOOKS))
    chk("band charts: one hover overlay and one tooltip each", html.count('class="bd-ov"') == len(BOOKS))
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
        # disagreement shading: one rectangle per week of a stretch (fill #c9811a opacity 0.16)
        shade = re.findall(r'<rect x="([\d.]+)" y="8" width="([\d.]+)" height="[\d.]+" fill="#c9811a" opacity="0.16"/>', body)
        exp_sh = [(wk, w2) for wk, w2, s_ in zip(w_["wk0"], w_["wk0"][1:] + [nn_ - 1], w_["wstr"]) if s_ >= 0 and w2 > wk]
        okb = len(shade) == len(exp_sh)
        Lx, Rx = h["L"], h["R"]
        xx = lambda i: Lx + (h["w"] - Lx - Rx) * i / (nn_ - 1)
        for (sx, sw_a), (a_, b_) in zip(shade, exp_sh):
            okb &= abs(float(sx) - xx(a_)) < 0.06 and abs(float(sw_a) - max(xx(b_) - xx(a_), 0.6)) < 0.08
        chk(f"regime {b}: one shaded rectangle per week of a disagreement stretch", okb, f"{len(shade)} vs {len(exp_sh)}")
        # signal strips: filled weeks, per colour
        for r_, colr in enumerate(("#6b4fbb", "#c9811a", "#2f9e6e")):
            rr_ = re.findall(r'<rect x="([\d.]+)" y="([\d.]+)" width="([\d.]+)" height="11" fill="' + colr + r'"/>', body)
            exp_r = [(wk, w2) for wk, w2, sgv in zip(w_["wk0"], w_["wk0"][1:] + [nn_ - 1], w_["sg"]) if sgv[r_] == 1 and w2 > wk]
            ok2 = len(rr_) == len(exp_r)
            for (sx, _, sw_a), (a_, b_) in zip(rr_, exp_r):
                ok2 &= abs(float(sx) - xx(a_)) < 0.06 and abs(float(sw_a) - max(xx(b_) - xx(a_), 0.6)) < 0.08
            chk(f"regime {b}: strip of {SIGN3[r_]} has one rectangle per BUY week", ok2, f"{len(rr_)} vs {len(exp_r)}")
        # the kept-share bars and the whole-book strip
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
