"""T10 analysis: reads only the shipped evidence in evidence/<run>/ (and, for the worked example only, the approved stock OHLC file) and prints section 4.

    python -I tests/T10/analyse.py [--run headline]            writes evidence/<run>/analysis.log and analysis.json (and prints the log)
    python -I tests/T10/analyse.py --evidence DIR              point at another evidence directory (e.g. the smoke run or a scratch copy)

There is NO NULL in T10 (Manu's waiver, 2026-11-12): nothing here is a percentile or a p-value and nothing may be read as 'beats chance'.
Imports nothing from the engine, the verifier or tag_lookup.py. Gates V1-V5 are read from the verifier's and the engine's json files and, where
the evidence allows, RE-DERIVED here from decisions.csv / decision_stocks.csv / events.csv / daily_nav.csv and T06's evidence (V2, V3, V4, V5).
Exit 1 if any gate (or an internal consistency check K1-K4) fails: analysis.log then holds only the gate block and says nothing below may be read.

Criteria (T10.md section 2), after cost at 20.8 bps, full window, LBES cash, per book:
  C1 rule CAGR > parent CAGR;  C2 rule max drawdown shallower than the parent's;  C3 rule CAGR > switch CAGR;  C4 rule Calmar >= switch Calmar;
  each passes at >= 3 of 4 books. C3 and C4 are quoted only where the rule differs from the switch in >= 5 separate stretches (reportability gate);
  a book that fails it counts as not passing C3 and C4 and is named.
"""
from __future__ import annotations

import argparse
import hashlib
import io
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
PRIMARY = 20.8
COSTS = (0.0, PRIMARY, 50.0)
LIVE_START = "2021-11-01"
BANDS = ["Large", "Mid", "Small and below"]
SIGS = ["Nifty100", "MC100", "SC100"]
SIGLAB = {"Nifty100": "Nifty 100", "MC100": "Midcap 100", "SC100": "Smallcap 100"}
BAND_SIG = dict(zip(BANDS, SIGS))
THR = ["thr_2/5", "thr_1/2", "rule", "thr_7/10", "thr_4/5"]
THR_LAB = {"thr_2/5": "2/5", "thr_1/2": "1/2", "rule": "3/5 (production's 0.60)", "thr_7/10": "7/10", "thr_4/5": "4/5"}
KINDS = ["rule", "switch", "parent", "constant_mix", "sleeve100", "published_parent", "t07_rule"]
KLAB = {"rule": "FS rule (this test)", "switch": "Three-index switch", "parent": "Hold the parent (rebuilt)", "constant_mix": "Constant mix (same average exposure)",
        "sleeve100": "100% sleeve", "published_parent": "Published parent (D17)", "t07_rule": "T07 per-stock rule (descriptive, unverified)"}
NOCHANCE = "no chance benchmark was run"
out = io.StringIO()
GATES: dict = {}
CONS: dict = {}


def P(*a):
    s = " ".join(str(x) for x in a)
    print(s)
    out.write(s + "\n")


def head(title: str):
    P("\n" + "=" * 100 + "\n" + title + "\n" + "=" * 100)


def pc(x, d=1):
    return "" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{100 * x:.{d}f}%"


def pp(x, d=1):
    return "" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{100 * x:+.{d}f}"


def num(x, d=3):
    return "" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:.{d}f}"


def tab(df: pd.DataFrame):
    P(df.to_string(index=False))


def asbool(s):
    return s.astype(str).str.strip().str.lower().isin(["true", "1", "1.0"]).values


def jsonable(o):
    if isinstance(o, dict):
        return {str(k): jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [jsonable(v) for v in o]
    if isinstance(o, (np.bool_, bool)):
        return bool(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating, float)):
        return None if math.isnan(float(o)) else float(o)
    if isinstance(o, pd.Timestamp):
        return str(o.date())
    return o


def runs_of(x):
    """Lengths of the maximal runs of True in a boolean array."""
    L, c = [], 0
    for v in x:
        if v:
            c += 1
        elif c:
            L.append(c)
            c = 0
    if c:
        L.append(c)
    return L


def nav_stat(nav):
    yrs = (len(nav) - 1) / 252
    dd = nav / np.maximum.accumulate(nav) - 1
    return float(nav[-1] ** (1 / yrs) - 1), float(dd.min())


def find_all(obj, names):
    r = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if str(k).lower() in names and not isinstance(v, (dict, list)):
                r.append(v)
            r += find_all(v, names)
    elif isinstance(obj, list):
        for v in obj:
            r += find_all(v, names)
    return r


# ── the data boundary, for the one raw file the worked example reads ─────────────────────────────
def approved_rows():
    txt = (AA / "data" / "APPROVED_DATA.md").read_text(encoding="utf-8")
    tabl = txt[txt.index("<!-- approved-table:start -->"):txt.index("<!-- approved-table:end -->")]
    rows = []
    for l in tabl.splitlines():
        c = [x.strip() for x in l.strip().strip("|").split("|")]
        if len(c) >= 5 and c[0] in ("APPROVED", "SUPERSEDED", "PENDING"):
            rows.append({"status": c[0], "id": c[1], "file": c[2], "through": c[3], "sha": c[4]})
    return rows


def approved_file(rel: str) -> Path:
    rows = [r for r in approved_rows() if r["file"].replace("\\", "/") == rel]
    if not rows or any(r["status"] != "APPROVED" for r in rows):
        raise SystemExit(f"{rel} is not an APPROVED row of data/APPROVED_DATA.md: stop and ask Manu")
    p = AA / rel
    h = hashlib.sha256(p.read_bytes()).hexdigest()
    if not h.startswith(rows[0]["sha"]):
        raise SystemExit(f"{rel}: sha256 {h[:16]} does not match the approved {rows[0]['sha']}")
    return p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="headline")
    ap.add_argument("--evidence", default=None, help="explicit evidence directory (overrides --run); analysis.log and analysis.json go there too")
    ap.add_argument("--t06", default=str(AA / "tests" / "T06" / "evidence" / "headline"), help="T06's evidence (V3)")
    ap.add_argument("--doc", default=str(HERE / "T10.md"), help="T10.md, read only, for the pre-registration hash")
    ap.add_argument("--counts", default=str(HERE / "logs" / "step_1_counts.json"), help="Step 1's counts (T10.md section 2), compared with the evidence")
    ap.add_argument("--books", default=None, help="comma list, for smoke runs that hold fewer than the four books (verdict counts then mean nothing)")
    ap.add_argument("--expect-r4", type=int, default=500, help="R4 draws per book the pre-registration requires (500); different = exit 1")
    ap.add_argument("--no-example-raw", action="store_true", help="skip reading the approved OHLC file for the worked example (testing only)")
    a = ap.parse_args()
    if a.books:
        BOOKS[:] = a.books.split(",")
    ev_dir = Path(a.evidence) if a.evidence else HERE / "evidence" / a.run
    BNO = {"SCMO_0003": 0, "SCMO_0007": 1, "SCMO_0010": 2, "SCMO_0029": 3}

    dec = pd.read_csv(ev_dir / "decisions.csv")
    ds = pd.read_csv(ev_dir / "decision_stocks.csv", keep_default_na=False, na_values=[""], dtype={"isin": str, "tag_detail": str, "tag_snapshot": str})
    evt = pd.read_csv(ev_dir / "events.csv")
    stt = pd.read_csv(ev_dir / "stats.csv")
    nav = pd.read_csv(ev_dir / "daily_nav.csv", parse_dates=["date"])
    trd = pd.read_csv(ev_dir / "trades.csv")
    stc = pd.read_csv(ev_dir / "stretches.csv")
    boot = pd.read_csv(ev_dir / "bootstrap.csv")
    r4 = pd.read_csv(ev_dir / "r4_tag_error.csv")
    g4 = pd.read_csv(ev_dir / "g_engine.csv")
    au = json.loads((ev_dir / "audit.json").read_text(encoding="utf-8"))
    reg = json.loads((ev_dir / "regression_t06.json").read_text(encoding="utf-8"))
    v4j = json.loads((ev_dir / "v4_exact.json").read_text(encoding="utf-8"))
    inp = pd.read_csv(ev_dir / "inputs.csv", comment="#", dtype=str, keep_default_na=False)
    doc = Path(a.doc).read_text(encoding="utf-8")
    region = doc[doc.index("\n## 1. Idea and references") + 1:doc.index("\n## 4. Results") + 1]
    region = "\n".join(l.rstrip() for l in region.replace("\r\n", "\n").split("\n"))
    sha = hashlib.sha256(region.encode("utf-8")).hexdigest()
    m_sha = re.search(r"§1–§3 sha256:\*\* `([^`]*)`", doc)
    sha_hdr = m_sha.group(1) if m_sha else "?"

    for c in ("extra", "tie", "float_differs"):
        dec[c + "_b"] = asbool(dec[c])
    ds["on_b"] = asbool(ds["on"])
    dec = dec.sort_values(["book", "window", "j"]).reset_index(drop=True)
    DEC = {(b, w): g.reset_index(drop=True) for (b, w), g in dec.groupby(["book", "window"])}
    EV = {(b, w): g.sort_values("event_no").reset_index(drop=True) for (b, w), g in evt.groupby(["book", "window"])}

    def S(b, kind, cost=PRIMARY, win="full", cash="lbes"):
        d = stt[(stt.book == b) & (stt.window == win) & (stt.cash == cash) & (stt.kind == kind)]
        d = d[np.isclose(d.cost_bps.astype(float), cost)] if d.cost_bps.notna().any() else d
        if not len(d):
            raise KeyError((b, kind, cost, win, cash))
        return d.iloc[0]

    def NAV(b, run, cost=PRIMARY):
        d = nav[(nav.book == b) & (nav.run == run)]
        d = d[np.isclose(d.cost_bps.astype(float), cost)] if run != "published_parent" else d
        return d.sort_values("date").reset_index(drop=True)

    cal = {b: NAV(b, "rule").date for b in BOOKS}
    live_first = {b: str(cal[b].iloc[int(np.searchsorted(cal[b].values, np.datetime64(pd.Timestamp(LIVE_START))))].date()) for b in BOOKS}
    start = {b: str(cal[b].iloc[0].date()) for b in BOOKS}
    end = str(cal[BOOKS[0]].iloc[-1].date())
    B7 = "SCMO_0007" if "SCMO_0007" in BOOKS else BOOKS[-1]
    nd = {(b, w): len(DEC[(b, w)]) for b in BOOKS for w in ("full", "live")}
    R: dict = {"meta": {"run": ev_dir.name, "books": list(BOOKS), "start": start, "end": end, "live_first": live_first, "prereg_header": sha_hdr, "prereg_recomputed": sha,
                        "prereg_match": sha_hdr == sha, "decisions": {b: {w: nd[(b, w)] for w in ("full", "live")} for b in BOOKS},
                        "sessions": {b: {w: int(S(b, "rule", win=w).sessions) for w in ("full", "live")} for b in BOOKS}, "expect_r4": a.expect_r4,
                        "n_r4": {b: int((r4.book == b).sum()) for b in BOOKS}}}

    P("T10 analysis. Run:", ev_dir.name, "| rule: hold the whole parent iff FS >= 0.60 (5k >= 3n), else 50% GOLDBEES + 50% cash | comparators: hold the parent, the three-index switch")
    P(f"NO NULL: Manu waived it (2026-11-12). No random draws enter C1-C4; {NOCHANCE}; no finding may say the rule beats chance; nothing here is stronger than PROVISIONAL.")
    P("Window (full): %s -> %s (%s from %s), %d weekly decisions (%s %d); live window from %s (first session %s) -> %s, %d decisions" % (
        start[BOOKS[0]], end, B7, start[B7], nd[(BOOKS[0], "full")], B7, nd[(B7, "full")], LIVE_START, live_first[BOOKS[0]], end, nd[(BOOKS[0], "live")]))
    P("Pre-registration sha256 in the header:", sha_hdr[:16], "| recomputed now:", sha[:16], "| match:", sha_hdr == sha)
    P("Evidence read:", ", ".join(sorted(p.name for p in ev_dir.iterdir() if p.name not in ("analysis.log", "analysis.json", "report.html"))))
    P("Conventions: CAGR = end NAV ^ (252 / (sessions - 1)) - 1; max drawdown = min over t of NAV_t / (max NAV up to t) - 1; Calmar = CAGR / |max drawdown|; all after cost, price return, LBES cash, unless a table says otherwise.")

    # ══ weeks and stretches per book and window (used by the gates, the reportability gate and the tables) ═══════════
    WK: dict = {}
    for b in BOOKS:
        WK[b] = {}
        for w in ("full", "live"):
            d = DEC[(b, w)]
            rs, ss, ex, ti = d.state_rule.values.astype(int), d.state_switch.values.astype(int), d.extra_b.values, d.tie_b.values
            pat = d.pattern.values
            flips_r = int((np.diff(rs) != 0).sum())
            flips_s = int((np.diff(ss) != 0).sum())
            tagonly = int(((np.diff(rs) != 0) & (pat[1:] == pat[:-1])).sum())
            L = runs_of(ex)
            WK[b][w] = {"decisions": len(d), "rule_in": int(rs.sum()), "switch_in": int(ss.sum()), "extra": int(ex.sum()), "stretches": len(L), "stretch_lengths": L,
                        "rule_out_switch_in": int(((rs == 0) & (ss == 1)).sum()), "ties": int(ti.sum()), "float_differs": int(d.float_differs_b.sum()), "flips_rule": flips_r, "flips_switch": flips_s,
                        "flips_rule_no_signal": tagonly, "partial_fs": int(((d.fs > 0) & (d.fs < 1)).sum()), "nheld_min": int(d.n_held.min()), "nheld_median": float(d.n_held.median()), "nheld_max": int(d.n_held.max()),
                        "share_in": float(rs.mean()), "reportable": bool(len(L) >= 5), "first": str(d.decision_date.iloc[0]), "last": str(d.decision_date.iloc[-1])}
    R["weeks"] = WK

    # ══ 4.0b gates ═══════════════════════════════════════════════════════════
    head("4.0b  GATES V1-V5, CONSISTENCY CHECKS AND REPORTABILITY\n(V1 independent check, V2 point in time, V3 regression to T06 and always-in, V4 the exact facts, V5 tags are read every week)")
    G = {}
    # V1
    vj = ev_dir / "verify_t10.json"
    v1 = {"present": vj.exists()}
    if vj.exists():
        v = json.loads(vj.read_text(encoding="utf-8"))
        if "exit_ok" in v:
            comp, bad_, exit_ok = v.get("gate_compared", 0), v.get("gate_failures_and_missing", 1), bool(v.get("exit_ok"))
        else:
            comp = bad_ = 0

            def walk(o):
                nonlocal comp, bad_
                if isinstance(o, dict):
                    c_ = next((o[k] for k in ("compared", "rows_compared", "n_compared") if k in o and isinstance(o[k], (int, float))), None)
                    f_ = next((o[k] for k in ("failures", "failed", "n_failed", "mismatches") if k in o and isinstance(o[k], (int, float))), None)
                    if c_ is not None and f_ is not None:
                        comp += c_
                        bad_ += f_
                    for x in o.values():
                        walk(x)
                elif isinstance(o, list):
                    for x in o:
                        walk(x)
            walk(v)
            ok_flags = find_all(v, {"exit_ok", "ok", "passed"})
            exit_ok = bool(ok_flags) and all(x is True for x in ok_flags)
        dets = [x for x in find_all(v, {"detected", "corrupt_detected", "selftest_detected", "corrupted_copy_detected"}) if isinstance(x, bool)]
        det_all = bool(dets) and all(dets)
        v1.update({"compared": int(comp), "failures": int(bad_), "exit_ok": exit_ok, "corruptions": len(dets), "all_detected": det_all})
        G["V1"] = bool(exit_ok and bad_ == 0 and comp > 0 and det_all)
        chk = v.get("checks") if isinstance(v.get("checks"), dict) else {}
        P(f"V1 independent check (verify_t10.py): {'PASS' if G['V1'] else 'FAIL'} | comparisons {int(comp):,}, failures and missing {int(bad_)}, deliberate corruptions detected {sum(dets)} of {len(dets)}, verifier exit_ok {exit_ok}")
        for k_, c_ in chk.items():
            if isinstance(c_, dict) and "compared" in c_:
                P(f"     {k_:14s} compared {int(c_.get('compared', 0)):>12,} failed {int(c_.get('failed', c_.get('failures', 0))):>3} gate {c_.get('gate')}")
        v1["checks"] = {k_: {"compared": int(c_.get("compared", 0)), "failed": int(c_.get("failed", c_.get("failures", 0)))} for k_, c_ in chk.items() if isinstance(c_, dict) and "compared" in c_}
    else:
        G["V1"] = False
        P(f"V1 independent check: NOT SATISFIED ({vj.name} is missing; a missing verifier result is a failed gate)")
    # V2: the engine's counts and our own
    v2a = au.get("v2", {})
    viol_a, chk_a = int(v2a.get("violations", 1)), int(v2a.get("checked", 0))
    own = {"labels": [0, 0], "tags": [0, 0], "trades": [0, 0], "events": [0, 0]}
    for j_ in SIGS:
        lab = pd.to_datetime(dec["label_" + j_])
        own["labels"][0] += int(len(dec))
        own["labels"][1] += int((lab > pd.to_datetime(dec.decision_date)).sum())
    t_ok = ds.tag_snapshot.notna()
    own["tags"] = [int(t_ok.sum()), int((pd.to_datetime(ds.tag_snapshot[t_ok]) > pd.to_datetime(ds.decision_date[t_ok])).sum())]
    tt = dec.trade_date.notna()
    own["trades"] = [int(tt.sum()), int((pd.to_datetime(dec.trade_date[tt]) <= pd.to_datetime(dec.decision_date[tt])).sum())]
    ne = evt[evt.kind != "initial"]
    own["events"] = [int(len(ne)), int((pd.to_datetime(ne.decision_date_used) >= pd.to_datetime(ne.trade_date)).sum())]
    viol_o, chk_o = sum(v_[1] for v_ in own.values()), sum(v_[0] for v_ in own.values())
    G["V2"] = bool(viol_a == 0 and chk_a > 0 and v2a.get("pass") is not False and viol_o == 0 and chk_o > 0)
    P(f"V2 point in time: {'PASS' if G['V2'] else 'FAIL'} | engine: violations {viol_a} of {chk_a:,} checks | re-derived here: violations {viol_o} of {chk_o:,} "
      f"(Master label dates {own['labels'][1]}/{own['labels'][0]:,}, tag snapshots {own['tags'][1]}/{own['tags'][0]:,}, trade after decision {own['trades'][1]}/{own['trades'][0]:,}, event decision before trade {own['events'][1]}/{own['events'][0]:,})")
    R["v2"] = {"engine_checked": chk_a, "engine_violations": viol_a, "own_checked": chk_o, "own_violations": viol_o, "own": own}
    # V3: regression to T06 (re-derived from the two daily_nav files) and always-in (G0)
    t06n = pd.read_csv(Path(a.t06) / "daily_nav.csv", parse_dates=["date"]) if (Path(a.t06) / "daily_nav.csv").exists() else None
    t06d = pd.read_csv(Path(a.t06) / "decisions.csv") if (Path(a.t06) / "decisions.csv").exists() else None
    pairs = (("strategy", "switch"), ("hold_parent", "parent"), ("sleeve_only", "sleeve100"))
    v3 = {"pairs": 0, "rows": 0, "max_rel": 0.0, "dec_shared": 0, "dec_mismatch": 0, "per_book": {}}
    if t06n is not None:
        for b in BOOKS:
            mr, rows_, dsh, dmm = 0.0, 0, 0, 0
            for c in COSTS:
                for t6, t10 in pairs:
                    x = t06n[(t06n.book == b) & (t06n.run == t6) & np.isclose(t06n.cost_bps.astype(float), c)].set_index("date").nav
                    y = nav[(nav.book == b) & (nav.run == t10) & np.isclose(nav.cost_bps.astype(float), c)].set_index("date").nav
                    sh = x.index.intersection(y.index)
                    sh = sh[sh <= pd.Timestamp("2026-10-22")]
                    if len(sh):
                        mr = max(mr, float((np.abs(x[sh] - y[sh]) / np.abs(x[sh])).max()))
                        rows_ += len(sh)
                        v3["pairs"] += 1
            d6 = t06d[t06d.book == b].set_index("decision_date") if t06d is not None else None
            if d6 is not None:
                dd_ = DEC[(b, "full")].set_index("decision_date")
                sh = d6.index.intersection(dd_.index)
                sh = [s_ for s_ in sh if s_ != d6.index[-1]]
                dsh = len(sh)
                dmm = int(sum(int(d6.loc[s_, "all_three_buy"]) != int(dd_.loc[s_, "state_switch"]) for s_ in sh))
            v3["per_book"][b] = {"nav_rows": rows_, "max_rel": mr, "dec_shared": dsh, "dec_mismatch": dmm}
            v3["rows"] += rows_
            v3["max_rel"] = max(v3["max_rel"], mr)
            v3["dec_shared"] += dsh
            v3["dec_mismatch"] += dmm
    g0 = g4[g4.book.isin(BOOKS)]
    g0_ok = bool(len(g0)) and bool((g0.cagr_gap_pp_yr.abs() <= 0.25).all() and (g0.worst_year_gap_pp.abs() <= 0.5).all())
    G["V3"] = bool(t06n is not None and v3["rows"] > 0 and v3["max_rel"] <= 1e-12 and v3["dec_shared"] > 0 and v3["dec_mismatch"] == 0 and reg.get("pass") is True and g0_ok)
    P(f"V3 regression to T06 and always-in: {'PASS' if G['V3'] else 'FAIL'} | switch, parent and 100% sleeve against T06's strategy, hold_parent, sleeve_only at 0 / 20.8 / 50 bps on every shared session to 2026-10-22: "
      f"{v3['rows']:,} NAV rows in {v3['pairs']} series, worst relative difference {v3['max_rel']:.1e} (limit 1e-12); decisions: {v3['dec_shared']} shared dates, {v3['dec_mismatch']} mismatches; engine's regression_t06.json pass = {reg.get('pass')}")
    P("   always-in at 0 cost against the published NAV (G0: +-0.25 pp/yr overall, +-0.5 pp in every calendar year), full window:")
    gg = g0.copy()
    gg["window"] = gg.window_first + " -> " + gg.window_last
    gg["gap pp/yr"] = gg.cagr_gap_pp_yr.map(lambda v_: f"{v_:.3f}")
    gg["worst year"] = gg.worst_year.astype(str) + " (" + gg.worst_year_gap_pp.map(lambda v_: f"{v_:.3f}") + " pp)"
    gg["G0"] = gg.overall.astype(str) + " / " + gg.yearly.astype(str)
    tab(gg[["book", "window", "gap pp/yr", "worst year", "G0"]])
    R["v3"] = v3
    R["g0"] = [{"book": r_.book, "gap": float(r_.cagr_gap_pp_yr), "worst_year": int(r_.worst_year), "worst_gap": float(r_.worst_year_gap_pp), "first": r_.window_first, "last": r_.window_last} for r_ in g0.itertuples()]
    # V4: recomputed from decisions.csv, then compared with v4_exact.json
    v4 = {}
    ok4 = True
    for b in BOOKS:
        for w in ("full", "live"):
            d = DEC[(b, w)]
            k, n_ = d.k_on.values.astype(int), d.n_held.values.astype(int)
            rs, ss = d.state_rule.values.astype(int), d.state_switch.values.astype(int)
            f_id = int((~((k >= 0) & (k <= n_) & (np.abs(d.fs.values - k / n_) < 1e-12))).sum())
            s_id = int((rs != (5 * k >= 3 * n_).astype(int)).sum())
            r_o = int(((rs == 0) & (ss == 1)).sum())
            fd = [str(x) for x in d.decision_date[d.float_differs_b]]
            tie_ = int(d.tie_b.sum())
            tie2 = int((5 * k == 3 * n_).sum())
            j_ = v4j["books"][b][w]
            agree = (j_["rule_out_while_switch_in"] == r_o and j_["fs_identity_failures"] == f_id and j_["state_rule_failures"] == s_id and list(j_["float_differs_weeks"]) == fd and j_["tie_weeks"] == tie_)
            v4[f"{b}|{w}"] = {"weeks": len(d), "rule_out_switch_in": r_o, "fs_identity_failures": f_id, "state_failures": s_id, "float_differs_weeks": fd, "ties": tie_, "ties_recount": tie2, "agree_with_engine": bool(agree),
                              "extra_weeks": int(d.extra_b.sum()), "extra_stretches": WK[b][w]["stretch_lengths"]}
            ok4 &= bool(agree and r_o == 0 and f_id == 0 and s_id == 0 and tie_ == tie2)
    G["V4"] = bool(ok4)
    P(f"V4 the exact facts: {'PASS' if G['V4'] else 'FAIL'} | (a) rule OUT while switch IN, (b) FS = k/n with 0 <= k <= n, (c) state IN iff 5k >= 3n, (d) weeks where production's float formula (either order) disagrees; re-derived from decisions.csv and compared with v4_exact.json")
    rows_ = [{"book": b, "window": w, "weeks": v_["weeks"], "(a) OUT while switch IN": v_["rule_out_switch_in"], "(b) FS identity failures": v_["fs_identity_failures"], "(c) state failures": v_["state_failures"],
              "(d) float differs": len(v_["float_differs_weeks"]), "ties FS=0.60": v_["ties"], "= engine json": v_["agree_with_engine"]} for key, v_ in v4.items() for b, w in [key.split("|")]]
    tab(pd.DataFrame(rows_))
    for key, v_ in v4.items():
        if v_["float_differs_weeks"]:
            P("   float formula differs from the integer rule on:", key, ", ".join(v_["float_differs_weeks"]))
    R["v4"] = v4
    # V5: tag reads every week
    v5 = {}
    ok5 = True
    for b in BOOKS:
        for w in ("full", "live"):
            rows_n = int(((ds.book == b) & (ds.window == w)).sum())
            exp_ = int(DEC[(b, w)].n_held.sum())
            eng_ = au.get("v5", {}).get("per_book_window", {}).get(b, {}).get(w, {})
            v5[f"{b}|{w}"] = {"rows": rows_n, "sum_n_held": exp_, "engine_tag_reads": eng_.get("tag_reads")}
            ok5 &= rows_n == exp_ and eng_.get("tag_reads") == exp_
    ver_v5 = (v1.get("checks") or {}).get("C-v5")
    G["V5"] = bool(ok5 and au.get("v5", {}).get("pass") is True and (ver_v5 is None or (ver_v5["failed"] == 0 and ver_v5["compared"] > 0)))
    P(f"V5 tags are read every week: {'PASS' if G['V5'] else 'FAIL'} | tag reads (rows of decision_stocks.csv) equal the sum of the stocks held over the weekly decisions in every book and window: "
      f"{sum(v_['rows'] for v_ in v5.values()):,} reads; the engine's own count agrees; the verifier's sample of 500 (stock, week) pairs per book against the D23 panels is in V1 (C-v5: "
      f"{'compared %d, failed %d' % (ver_v5['compared'], ver_v5['failed']) if ver_v5 else 'not in verify_t10.json'})")
    R["v5"] = v5
    # K1-K4: consistency of the evidence files with each other
    K = {}
    mx = 0.0
    for b in BOOKS:
        for kind in ("rule", "switch", "parent", "constant_mix", "sleeve100"):
            n_ = NAV(b, kind).nav.values
            c_, d_ = nav_stat(n_)
            s_ = S(b, kind)
            mx = max(mx, abs(c_ - s_.cagr), abs(d_ - s_.max_dd), abs(n_[-1] - s_.end_nav) / s_.end_nav)
    K["K1"] = mx < 1e-9
    P(f"K1 stats.csv against daily_nav.csv (full window, 20.8 bps, five series x books): largest absolute difference in CAGR, max drawdown, end NAV {mx:.1e} -> {'ok' if K['K1'] else 'FAIL'}")
    mx = 0.0
    for b in BOOKS:
        for comp_ in ("switch", "parent"):
            r_ = boot[(boot.book == b) & (boot.comparator == comp_)].iloc[0]
            mx = max(mx, abs(r_.point_cagr_diff - (S(b, "rule").cagr - S(b, comp_).cagr)))
        for w in ("full", "live"):
            sm = stc[(stc.book == b) & (stc.window == w) & (stc.stretch_no == 0)].iloc[0]
            mx = max(mx, abs(sm.cagr_diff_all - (S(b, "rule", win=w).cagr - S(b, "switch", win=w).cagr)))
    K["K2"] = mx < 1e-9
    P(f"K2 bootstrap.csv and stretches.csv point estimates against stats.csv (rule CAGR minus comparator CAGR): largest difference {mx:.1e} -> {'ok' if K['K2'] else 'FAIL'}")
    bad = [(b, w) for b in BOOKS for w in ("full", "live") if abs(S(b, "rule", win=w).invested_weeks - WK[b][w]["rule_in"]) > 1e-9 or abs(S(b, "switch", win=w).invested_weeks - WK[b][w]["switch_in"]) > 1e-9]
    K["K3"] = not bad
    P(f"K3 invested_weeks in stats.csv equal the IN decisions of decisions.csv (rule and switch, both windows): {'ok' if K['K3'] else 'FAIL ' + str(bad)}")
    bad = [b for b in BOOKS for w in ("full", "live") if WK[b][w]["stretches"] != len(stc[(stc.book == b) & (stc.window == w) & (stc.stretch_no > 0)]) or v4[f"{b}|{w}"]["extra_stretches"] != WK[b][w]["stretch_lengths"]]
    K["K4"] = not bad and all(au["books"][b]["windows"][w]["extra_stretches"] == WK[b][w]["stretches"] for b in BOOKS for w in ("full", "live"))
    P(f"K4 the stretches counted from decisions.csv equal the rows of stretches.csv and audit.json: {'ok' if K['K4'] else 'FAIL ' + str(bad)}")
    n_r4 = R["meta"]["n_r4"]
    K["K5"] = all(n_r4[b] == a.expect_r4 for b in BOOKS)
    P(f"K5 R4 draws per book in r4_tag_error.csv: {[n_r4[b] for b in BOOKS]} (the pre-registration requires {a.expect_r4}) -> {'ok' if K['K5'] else 'FAIL'}")
    R["consistency"] = K
    # reportability
    P(f"\nReportability gate (C3 and C4 are quoted only if the rule is IN while the switch is OUT in >= 5 separate stretches of weeks, per book and window). Extra weeks = rule IN, switch OUT; windows: full {start[BOOKS[0]]} -> {end}, live {live_first[BOOKS[0]]} -> {end}:")
    rows_ = []
    for b in BOOKS:
        for w in ("full", "live"):
            x = WK[b][w]
            rows_.append({"book": b, "window": w, "decisions": x["decisions"], "extra weeks": x["extra"], "stretches": x["stretches"], "lengths": ",".join(map(str, x["stretch_lengths"])), ">= 5": "REPORTABLE" if x["reportable"] else "NOT REPORTABLE"})
    tab(pd.DataFrame(rows_))
    # the counts of T10.md section 2 (Step 1) against the evidence
    cnt = json.loads(Path(a.counts).read_text(encoding="utf-8")) if Path(a.counts).exists() else None
    if cnt:
        diffs = []
        for b in BOOKS:
            for w in ("full", "live"):
                c_, x = cnt["books"][b][w], WK[b][w]
                for name, mine, theirs in (("weeks", x["decisions"], c_["weeks"]), ("rule IN weeks", x["rule_in"], c_["rule_IN_weeks"]), ("switch IN weeks", x["switch_in"], c_["switch_IN_weeks"]),
                                           ("extra weeks", x["extra"], c_["extra_IN_weeks_rule_in_switch_out"]), ("stretches", x["stretches"], c_["extra_IN_stretches"]), ("stretch lengths", x["stretch_lengths"], c_["extra_IN_stretch_lengths"]),
                                           ("partial FS weeks", x["partial_fs"], c_["weeks_partial_FS_strictly_between_0_and_1"]), ("ties", x["ties"], c_["exact_tie_weeks_FS_eq_0.60"]), ("rule flips", x["flips_rule"], c_["rule_decision_flips"]),
                                           ("switch flips", x["flips_switch"], c_["switch_decision_flips"]), ("rule flips with no signal flip", x["flips_rule_no_signal"], c_["rule_flips_with_no_signal_flip"])):
                    if mine != theirs:
                        diffs.append(f"{b} {w}: {name} evidence {mine} vs frozen {theirs}")
        P(f"\nCounts frozen in T10.md section 2 (Step 1, no return read) against the evidence's decisions: {'all agree' if not diffs else str(len(diffs)) + ' DIFFER'} (rule IN and switch IN weeks, extra weeks, stretches and lengths, partial-FS weeks, ties, flips, both windows, four books)")
        for d_ in diffs:
            P("   DIFFERS:", d_)
        R["frozen_counts"] = {"differs": diffs}
    R["gates"] = {**G, "all": all(G.values()) and all(K.values())}
    gl = {k_: ("PASS" if v_ else "FAIL") for k_, v_ in G.items()}
    P("\nGates:", gl, "->", "ALL PASS" if R["gates"]["all"] else "A GATE FAILED")
    outdir = ev_dir
    if not R["gates"]["all"]:
        P("\nA validity gate or consistency check FAILED: nothing below may be read, quoted or summarised. Fix it and rerun as a new run directory.")
        (outdir / "analysis.log").write_text(out.getvalue(), encoding="utf-8")
        (outdir / "analysis.json").write_text(json.dumps(jsonable(R), indent=1), encoding="utf-8")
        sys.exit(1)

    # ══ 4.0a the worked example ═════════════════════════════════════════════
    b = BOOKS[0]
    dfull = DEC[(b, "full")]
    ev0 = EV[(b, "full")]
    pick = None
    for r_ in dfull[dfull.extra_b].itertuples():
        e_ = ev0[(ev0.decision_date_used == r_.decision_date) & ev0.kind.str.startswith("state") & (ev0.state == "IN")]
        if len(e_):
            pick = (r_, e_.iloc[0])
            break
    if pick is None:
        raise SystemExit("no extra week with a state event to use as the worked example")
    dx, ex_ = pick
    ei = int(ex_.event_no)
    prev_ev = ev0[ev0.event_no == ei - 1].iloc[0]
    stk = ds[(ds.book == b) & (ds.window == "full") & (ds.j == dx.j)].reset_index(drop=True)
    td = str(ex_.trade_date)
    trow = trd[(trd.book == b) & (trd.run == "rule") & np.isclose(trd.cost_bps, PRIMARY) & (trd.event_no == ei)].iloc[0]
    srow = trd[(trd.book == b) & (trd.run == "switch") & np.isclose(trd.cost_bps, PRIMARY)]
    nr, nsw, npar = NAV(b, "rule"), NAV(b, "switch"), NAV(b, "parent")
    k0 = int(nr.index[nr.date == pd.Timestamp(td)][0])
    V, traded, cost_ = float(ex_.V_before), float(ex_.traded), float(ex_.cost)
    kc = (V - cost_) / V
    fills = []
    if not a.no_example_raw:
        o = pd.read_csv(approved_file(f"data/holdings_matrix/{b}_ohlc.csv"), parse_dates=["date"]).drop_duplicates(["date", "stock"])
        cor = pd.read_csv(approved_file("data/holdings_matrix/price_corrections.csv"), parse_dates=["ex_date"])
        sumclose = 0.0
        for r_ in stk.itertuples():
            s_ = o[(o.stock == r_.stock) & (o.date <= pd.Timestamp(td))].sort_values("date")
            for c_ in cor.itertuples():
                if b in c_.applies_to.split(";") and c_.stock == r_.stock:
                    s_.loc[s_.date < c_.ex_date, ["open", "high", "low", "close"]] *= c_.factor
            bar = s_[s_.date == pd.Timestamp(td)]
            if not len(bar):
                raise SystemExit(f"no bar for {r_.stock} on {td}")
            bar = bar.iloc[0]
            o4 = float((bar.open + bar.high + bar.low + bar.close) / 4) if bar[["open", "high", "low"]].notna().all() else float(bar.close)
            close = float(s_.close.ffill().iloc[-1])
            units = V * r_.listed_weight * kc / o4
            sumclose += units * close
            fills.append({"stock": r_.stock, "w": float(r_.listed_weight), "open": float(bar.open), "high": float(bar.high), "low": float(bar.low), "close_bar": float(bar.close), "ohlc4": o4, "target": V * float(r_.listed_weight), "units": units, "close": close, "value_close": units * close})
        ex_chk = abs(sumclose - float(trow.nav_close_after))
    else:
        ex_chk = float("nan")
    sw_dec = {"pattern": dx.pattern, "state": int(dx.state_switch)}
    sw_next = srow[pd.to_datetime(srow.date) >= pd.Timestamp(td)]
    sw_next_ev = None if not len(sw_next) else {"date": str(sw_next.iloc[0].date), "kind": str(sw_next.iloc[0].kind), "state_after": "IN" if sw_next.iloc[0].e_after >= 0.5 else "OUT"}
    # path statistics
    nvr = nr.nav.values
    dd = nvr / np.maximum.accumulate(nvr) - 1
    tr_i = int(dd.argmin())
    pk_i = int(np.argmax(nvr[:tr_i + 1]))
    s0 = S(b, "rule")
    EXM = {"book": b, "decision_no": int(dx.j), "n_decisions": int(len(dfull)), "decision_date": str(dx.decision_date), "weekday": pd.Timestamp(dx.decision_date).strftime("%A"), "trade_date": td, "trade_idx": int(ex_.trade_idx),
           "basket_eff": str(dx.basket_eff), "pattern": dx.pattern, "signs": [dx.sign_Nifty100, dx.sign_MC100, dx.sign_SC100], "labels": [dx.label_Nifty100, dx.label_MC100, dx.label_SC100],
           "n": int(dx.n_held), "n_band": [int(dx.n_large), int(dx.n_mid), int(dx.n_small)], "k": int(dx.k_on), "fs": float(dx.fs), "lhs": int(5 * dx.k_on), "rhs": int(3 * dx.n_held), "state_rule": "IN" if dx.state_rule else "OUT", "state_switch": "IN" if dx.state_switch else "OUT",
           "weight_fs": float(dx.weight_fs), "event_kind": str(ex_.kind), "state_before": str(prev_ev.state), "event_no": ei, "V": V, "traded": traded, "cost": cost_, "kc": kc, "cost_bps": PRIMARY, "stocks": fills,
           "stk": [{"stock": r_.stock, "isin": r_.isin, "w": float(r_.listed_weight), "band": r_.band, "src": r_.tag_source, "snap": r_.tag_snapshot, "detail": None if pd.isna(r_.tag_detail) else str(r_.tag_detail), "via": r_.tag_via, "sig": r_.band_signal, "on": bool(r_.on_b)} for r_ in stk.itertuples()],
           "nav_after_close": float(trow.nav_close_after), "sum_units_close_diff": ex_chk, "e_after": float(trow.e_after),
           "around": [{"date": str(nr.date.iloc[i].date()), "rule": float(nr.nav.iloc[i]), "switch": float(nsw.nav.iloc[i]), "parent": float(npar.nav.iloc[i])} for i in range(k0 - 2, k0 + 3)],
           "switch_next": sw_next_ev, "start": str(nr.date.iloc[0].date()), "end": str(nr.date.iloc[-1].date()), "sessions": int(s0.sessions), "end_nav": float(s0.end_nav), "cagr": float(s0.cagr), "max_dd": float(s0.max_dd),
           "dd_peak_date": str(nr.date.iloc[pk_i].date()), "dd_peak": float(nvr[pk_i]), "dd_trough_date": str(nr.date.iloc[tr_i].date()), "dd_trough": float(nvr[tr_i]),
           "switch": {"cagr": float(S(b, "switch").cagr), "max_dd": float(S(b, "switch").max_dd), "end_nav": float(S(b, "switch").end_nav)}, "parent": {"cagr": float(S(b, "parent").cagr), "max_dd": float(S(b, "parent").max_dd), "end_nav": float(S(b, "parent").end_nav)},
           "sleeve_before_value": V}
    R["example"] = EXM
    head("4.0a  THE WORKED EXAMPLE: ONE REAL WEEKLY DECISION, FROM THE BASKET TO THE TRADE AND THE NAV")
    P(f"Book {b}, decision no. {dx.j} of {len(dfull)} (full window {start[b]} -> {end}), made at the close of {EXM['decision_date']} ({EXM['weekday']}). Chosen by a stated rule and not for its result: the first week of the full window in which the rule is IN,")
    P("the three-index switch is OUT and the rule trades (a state event), read from decisions.csv in decision order. Everything below is printed from the evidence files; the stock prices come from the approved OHLC file (D18).")
    P(f"\nStep 1. The basket in force on {EXM['decision_date']}: the latest non-skipped basket with availableDate on or before it = the basket of {EXM['basket_eff']}; {EXM['n']} stocks with listed weight > 0 (weights renormalised to sum to 1, as in T06).")
    P(f"Step 2. Tag every stock as of {EXM['decision_date']} (the shared tag rule, latest snapshot on or before the date; 'rank' = rank on the market-cap snapshot, 1-100 Large, 101-250 Mid, above 250 Small and below; before 2026-04-09 only the rank rule exists):")
    t = pd.DataFrame([{"stock": s["stock"], "weight": f"{s['w']:.4f}", "band": s["band"], "source": s["src"], "snapshot": s["snap"], "rank": s["detail"] or "", "band's index": SIGLAB[BAND_SIG[s["band"]]], "SIGN": s["sig"], "on": "yes" if s["on"] else "no"} for s in EXM["stk"]])
    tab(t)
    P(f"Step 3. The three signals at {EXM['decision_date']} (latest Master row of each index on or before it): Nifty 100 {EXM['signs'][0]} (row dated {EXM['labels'][0]}), Midcap 100 {EXM['signs'][1]} (row dated {EXM['labels'][1]}), "
      f"Smallcap 100 {EXM['signs'][2]} (row dated {EXM['labels'][2]}) -> pattern {EXM['pattern']}.")
    P(f"Step 4. n = {EXM['n']} stocks held (Large {EXM['n_band'][0]}, Mid {EXM['n_band'][1]}, Small and below {EXM['n_band'][2]}); k = {EXM['k']} of them sit in a band whose index is BUY. FS = k / n = {EXM['k']} / {EXM['n']} = {EXM['fs']:.3f}.")
    P(f"        The rule decides in integers: IN iff 5k >= 3n: 5 x {EXM['k']} = {EXM['lhs']} against 3 x {EXM['n']} = {EXM['rhs']} -> {EXM['state_rule']}. (FS weighted by listed weights, {EXM['weight_fs']:.3f}, is R6 only.)")
    P(f"        The three-index switch looks at the pattern only: {EXM['pattern']} is not BBB -> {EXM['state_switch']}. So this is an 'extra' week: the rule is IN while the switch is OUT.")
    P(f"Step 5. The trade: decided at the close of {EXM['decision_date']}, made on the next session, {td} (session no. {EXM['trade_idx']} of {EXM['sessions']}), at each instrument's OHLC4 = (open + high + low + close) / 4 of that session. The book held {EXM['state_before']} (50% GOLDBEES, 50% cash).")
    P(f"        V = the book's value at that session's fill prices before cost = {V:.6f} (NAV starts at 1.000 on {start[b]}). Target for stock i = V x w_i (GOLDBEES and cash 0). Sold: the whole sleeve, {V:.6f}; bought: {V:.6f} of stocks; traded = sum of |target - current| = {traded:.6f}.")
    P(f"        cost = traded x {PRIMARY:g} / 2 / 10,000 = {traded:.6f} x {PRIMARY / 2 / 1e4:.6f} = {cost_:.6f}; every new position is scaled by (V - cost) / V = {kc:.8f}; units_i = V x w_i x {kc:.6f} / OHLC4_i.")
    if fills:
        t = pd.DataFrame([{"stock": f["stock"], "weight": f"{f['w']:.4f}", "open": f"{f['open']:.2f}", "high": f"{f['high']:.2f}", "low": f"{f['low']:.2f}", "close": f"{f['close_bar']:.2f}", "OHLC4 fill": f"{f['ohlc4']:.4f}", "target value": f"{f['target']:.6f}",
                          "units bought": f"{f['units']:.6f}", f"value at close {td}": f"{f['value_close']:.6f}"} for f in fills])
        tab(t)
        P(f"        Sum of units x close on {td} = {sum(f['value_close'] for f in fills):.6f}; trades.csv records the NAV after the trade as {EXM['nav_after_close']:.6f} (difference {EXM['sum_units_close_diff']:.1e}). events.csv: V {V:.6f}, traded {traded:.6f}, cost {cost_:.6f} (the same).")
    P(f"Step 6. The daily NAV (rule, switch and parent side by side, 20.8 bps, 1.000 at the close of {start[b]}); the rule's trade is on {td}; the switch stays OUT"
      + (f" until its own event on {sw_next_ev['date']} ({sw_next_ev['kind']}, state after: {sw_next_ev['state_after']})." if sw_next_ev else "."))
    tab(pd.DataFrame([{"date": x["date"], "rule": f"{x['rule']:.6f}", "switch": f"{x['switch']:.6f}", "parent": f"{x['parent']:.6f}"} for x in EXM["around"]]))
    P(f"Step 7. The path: NAV_t = sum of units x close (stocks) + GOLDBEES units x close + cash units x level. The rule's path runs {EXM['start']} -> {EXM['end']}, {EXM['sessions']:,} sessions, end NAV {EXM['end_nav']:.4f}.")
    P(f"        CAGR = {EXM['end_nav']:.4f} ^ (252 / {EXM['sessions'] - 1}) - 1 = {pc(EXM['cagr'], 2)}. Max drawdown = min over t of NAV_t / (max NAV up to t) - 1 = {pc(EXM['max_dd'], 2)} "
      f"(peak {EXM['dd_peak']:.4f} on {EXM['dd_peak_date']}, trough {EXM['dd_trough']:.4f} on {EXM['dd_trough_date']}); Calmar = {pc(EXM['cagr'], 2)} / {pc(abs(EXM['max_dd']), 2)} = {EXM['cagr'] / abs(EXM['max_dd']):.3f}.")
    P(f"Step 8. The comparators on the same path ({EXM['start']} -> {EXM['end']}, 20.8 bps): three-index switch CAGR {pc(EXM['switch']['cagr'], 2)}, max drawdown {pc(EXM['switch']['max_dd'], 2)}; hold the parent CAGR {pc(EXM['parent']['cagr'], 2)}, max drawdown {pc(EXM['parent']['max_dd'], 2)}. {NOCHANCE.capitalize()}.")

    # ══ criteria ════════════════════════════════════════════════════════════
    def crit(win, cash, cost):
        o_ = {"books": {}, "count": {"C1": 0, "C2": 0, "C3": 0, "C4": 0}}
        for b in BOOKS:
            r_, s_, p_ = S(b, "rule", cost, win, cash), S(b, "switch", cost, win, cash), S(b, "parent", cost, win, cash)
            rep = WK[b][win]["reportable"]
            c1, c2 = bool(r_.cagr > p_.cagr), bool(r_.max_dd > p_.max_dd)
            c3r, c4r = bool(r_.cagr > s_.cagr), bool(r_.calmar >= s_.calmar - 1e-12)
            c3, c4 = c3r and rep, c4r and rep
            o_["books"][b] = {"rule_cagr": float(r_.cagr), "rule_dd": float(r_.max_dd), "rule_calmar": float(r_.calmar), "switch_cagr": float(s_.cagr), "switch_dd": float(s_.max_dd), "switch_calmar": float(s_.calmar),
                              "parent_cagr": float(p_.cagr), "parent_dd": float(p_.max_dd), "parent_calmar": float(p_.calmar), "reportable": rep, "stretches": WK[b][win]["stretches"], "C1": c1, "C2": c2, "C3": c3, "C4": c4, "C3_raw": c3r, "C4_raw": c4r,
                              "trades": {k_: float(S(b, k_, cost, win, cash).trades) for k_ in ("rule", "switch", "constant_mix")}, "cost_paid": {k_: float(S(b, k_, cost, win, cash).cost_paid) for k_ in ("rule", "switch", "constant_mix")}}
            for c_ in ("C1", "C2", "C3", "C4"):
                o_["count"][c_] += int(o_["books"][b][c_])
        o_["pass"] = {c_: o_["count"][c_] >= 3 for c_ in o_["count"]}
        o_["n_books"] = len(BOOKS)
        return o_

    def crit_tables(cr, cost, win, cash, label):
        rows1, rows2 = [], []
        for b in BOOKS:
            x = cr["books"][b]
            rows1.append({"book": b, "rule CAGR": pc(x["rule_cagr"]), "parent CAGR": pc(x["parent_cagr"]), "diff pp": pp(x["rule_cagr"] - x["parent_cagr"]), "C1": "PASS" if x["C1"] else "FAIL",
                          "rule max DD": pc(x["rule_dd"]), "parent max DD": pc(x["parent_dd"]), "diff pp ": pp(x["rule_dd"] - x["parent_dd"]), "C2": "PASS" if x["C2"] else "FAIL"})
            rep = "" if x["reportable"] else " (NOT REPORTABLE)"
            rows2.append({"book": b, "stretches": x["stretches"], "rule CAGR": pc(x["rule_cagr"]), "switch CAGR": pc(x["switch_cagr"]), "diff pp": pp(x["rule_cagr"] - x["switch_cagr"]), "C3": ("PASS" if x["C3"] else "FAIL") + rep,
                          "rule Calmar": num(x["rule_calmar"]), "switch Calmar": num(x["switch_calmar"]), "C4": ("PASS" if x["C4"] else "FAIL") + rep})
        tab(pd.DataFrame(rows1))
        P(f"   C1 passes in {cr['count']['C1']} of {len(BOOKS)} books, C2 in {cr['count']['C2']} of {len(BOOKS)} (rule against the parent; no reportability gate)")
        tab(pd.DataFrame(rows2))
        P(f"   C3 passes in {cr['count']['C3']} of {len(BOOKS)} books, C4 in {cr['count']['C4']} of {len(BOOKS)} (rule against the switch; a book with < 5 stretches counts as not passing)")

    R["crit"] = {}
    for win, cash, cost in [("full", "lbes", c) for c in COSTS] + [("live", "lbes", PRIMARY), ("full", "liq", PRIMARY)]:
        R["crit"][f"{win}|{cash}|{cost:g}"] = crit(win, cash, cost)
    CH = R["crit"][f"full|lbes|{PRIMARY:g}"]
    V = CH["pass"]

    # ══ 4.1 headline ═════════════════════════════════════════════════════════
    head(f"4.1  HEADLINE: C1-C4 PER BOOK AND THE 3-OF-4 VERDICT\n(after cost at {PRIMARY:g} bps round trip; full window {start[BOOKS[0]]} -> {end}, {B7} from {start[B7]}; LBES cash; {NOCHANCE})")
    crit_tables(CH, PRIMARY, "full", "lbes", "headline")
    P("\nVerdict per criterion (>= 3 of 4 books; one rule, no grid, none adjusted; the four books share one market, one set of signals and the same weeks of difference, so '3 of 4' is a consistency check; "
      + NOCHANCE + "):")
    HY = {"C1": "H1 return against the parent", "C2": "H2 protection against the parent", "C3": "H3 increment against the switch", "C4": "H4 risk-adjusted against the switch"}
    tab(pd.DataFrame([{"criterion": c_, "hypothesis": HY[c_], "books passing": f"{CH['count'][c_]} of {len(BOOKS)}", "verdict": "PASS" if CH["pass"][c_] else "FAIL"} for c_ in ("C1", "C2", "C3", "C4")]))
    R["verdict"] = {"pass": CH["pass"], "count": CH["count"]}

    # headline stats by kind
    HS = {}
    P(f"\nAll series, full window {start[BOOKS[0]]} -> {end} ({B7} from {start[B7]}), {PRIMARY:g} bps, LBES cash (days >= 10% below = sessions with NAV at least 10% under its running peak; longest underwater in sessions; share IN = IN decisions / weekly decisions):")
    for b in BOOKS:
        rows_ = []
        HS[b] = {}
        for k_ in KINDS:
            s_ = S(b, k_)
            mixf = s_.mix_share_f
            share = float(s_.invested_weeks) / nd[(b, "full")] if k_ in ("rule", "switch", "parent", "t07_rule") and not pd.isna(s_.invested_weeks) else (float(mixf) if k_ == "constant_mix" else (0.0 if k_ == "sleeve100" else None))
            HS[b][k_] = {"end_nav": float(s_.end_nav), "cagr": float(s_.cagr), "max_dd": float(s_.max_dd), "calmar": float(s_.calmar), "vol": float(s_.vol), "ulcer": float(s_.ulcer), "days_below_10pct": int(s_.days_below_10pct), "longest_underwater": int(s_.longest_underwater),
                         "trades": None if pd.isna(s_.trades) else float(s_.trades), "cost_paid": None if pd.isna(s_.cost_paid) else float(s_.cost_paid), "events": None if pd.isna(s_.events) else float(s_.events), "share_in": share, "mix_f": None if pd.isna(mixf) else float(mixf)}
            h = HS[b][k_]
            rows_.append({"series": KLAB[k_], "CAGR": pc(h["cagr"]), "max DD": pc(h["max_dd"]), "Calmar": num(h["calmar"]), "vol": pc(h["vol"]), "Ulcer": num(h["ulcer"], 2), "days>=10% below": h["days_below_10pct"], "longest uw": h["longest_underwater"],
                          "trades": "" if h["trades"] is None else int(h["trades"]), "cost paid": "" if h["cost_paid"] is None else num(h["cost_paid"], 4), "share IN": pc(h["share_in"]) if h["share_in"] is not None else ""})
        P(f"\n{b} ({start[b]} -> {end}):")
        tab(pd.DataFrame(rows_))
    P("   (the constant mix holds the rule's average share of NAV in the parent's stocks, f, all the time; its 'share IN' is f. The 100% sleeve is half GOLDBEES, half cash. T07's rule is run by the same engine, is NOT covered by the verifier and is not part of any gate or criterion.)")
    R["headline"] = HS

    # ══ 4.2 intervals, per-year ═════════════════════════════════════════════
    head(f"4.2  BOOTSTRAP INTERVALS, PER-YEAR RETURNS AND TRADES\n(descriptive, no pass mark; {NOCHANCE})")
    P(f"Bootstrap (reported, no pass mark): the difference of daily log returns of the rule and the comparator over {start[BOOKS[0]]} -> {end}, {PRIMARY:g} bps, resampled in moving blocks of 20 sessions, 1,000 resamples, "
      "default_rng([11, resample_id, book_no]); interval = 2.5th and 97.5th percentile of the resampled CAGR difference (rule minus comparator). It is the uncertainty of this window's difference, not a test against chance.")
    rows_, BT = [], {}
    for b in BOOKS:
        BT[b] = {}
        for comp_ in ("switch", "parent"):
            r_ = boot[(boot.book == b) & (boot.comparator == comp_)].iloc[0]
            BT[b][comp_] = {"point": float(r_.point_cagr_diff), "lo": float(r_.ci_low), "hi": float(r_.ci_high), "contains0": bool(r_.ci_low <= 0 <= r_.ci_high)}
        rows_.append({"book": b, "rule - switch pp": pp(BT[b]["switch"]["point"]), "95% interval pp": f"{pp(BT[b]['switch']['lo'])} to {pp(BT[b]['switch']['hi'])}", "includes 0": "yes" if BT[b]["switch"]["contains0"] else "no",
                      "rule - parent pp": pp(BT[b]["parent"]["point"]), "95% interval pp ": f"{pp(BT[b]['parent']['lo'])} to {pp(BT[b]['parent']['hi'])}", "includes 0 ": "yes" if BT[b]["parent"]["contains0"] else "no"})
    tab(pd.DataFrame(rows_))
    R["boot"] = BT
    # per-year returns
    yrs = {}
    for b in BOOKS:
        yrs[b] = {}
        for run in ("rule", "switch", "parent", "constant_mix", "published_parent"):
            n_ = NAV(b, run)
            ser = pd.Series(n_.nav.values, index=n_.date)
            ye = ser.groupby(ser.index.year).last()
            prev = pd.concat([pd.Series([1.0], index=[ye.index[0] - 1]), ye]).shift(1).iloc[1:]
            yrs[b][run] = {int(y): float(ye[y] / prev[y] - 1) for y in ye.index}
    R["years"] = yrs
    yl = sorted(yrs[BOOKS[0]]["rule"])
    P(f"\nPer-calendar-year return of each series, {PRIMARY:g} bps (first year from the base 1.000 at the close of {start[BOOKS[0]]} ({B7}: {start[B7]}), last year to {end}; year return = NAV at the last session of the year / NAV at the last session of the year before - 1):")
    for b in BOOKS:
        rows_ = [{"series": KLAB[run].split(" (")[0], **{str(y): pp(yrs[b][run].get(y)) for y in yl}} for run in ("rule", "switch", "parent", "constant_mix", "published_parent")]
        P(f"\n{b} (% per year):")
        tab(pd.DataFrame(rows_))

    # ══ 4.3 stretches, patterns ═════════════════════════════════════════════
    head("4.3  THE EXTRA WEEKS: STRETCH TABLE (R7), SIGNAL PATTERNS AND FS\n(an extra week = the rule is IN and the three-index switch is OUT; a stretch = a maximal run of extra weeks)")
    R7 = {}
    for win in ("full", "live"):
        for b in BOOKS:
            sg = stc[(stc.book == b) & (stc.window == win) & (stc.stretch_no > 0)].reset_index(drop=True)
            sm = stc[(stc.book == b) & (stc.window == win) & (stc.stretch_no == 0)].iloc[0]
            lg = int(sg.diff_log_return.abs().values.argmax()) if len(sg) else None
            R7.setdefault(b, {})[win] = {"stretches": [{"no": int(r_.stretch_no), "first": r_.first_decision_date, "last": r_.last_decision_date, "weeks": int(r_.weeks), "mean_fs": float(r_.mean_fs), "span_start": r_.span_start_date, "span_end": r_.span_end_date,
                                                        "rule": float(r_.rule_log_return), "switch": float(r_.switch_log_return), "diff": float(r_.diff_log_return)} for r_ in sg.itertuples()],
                                         "cagr_diff_all": float(sm.cagr_diff_all), "cagr_diff_wo": float(sm.cagr_diff_without_largest), "largest_no": None if lg is None else int(sg.stretch_no.iloc[lg]),
                                         "n_ahead": int((sg.diff_log_return > 0).sum()), "n": len(sg), "sign_change": bool(np.sign(sm.cagr_diff_all) != np.sign(sm.cagr_diff_without_largest)),
                                         "sum_diff": float(sg.diff_log_return.sum()), "largest_diff": None if lg is None else float(sg.diff_log_return.iloc[lg])}
    R["r7"] = R7
    for win in ("full", "live"):
        w0 = start[BOOKS[0]] if win == "full" else live_first[BOOKS[0]]
        P(f"\nR7 stretch table, {win} window ({w0} -> {end}), {PRIMARY:g} bps, LBES: dates of the first and last extra decision; span = close of the first extra decision date to the close of the first decision date after the run (or the window's last session); "
          "rule and switch are log returns of the two NAVs over the span, 'diff' = rule - switch (percentage points of log return):")
        for b in BOOKS:
            x = R7[b][win]
            rows_ = [{"no": s_["no"], "first": s_["first"], "last": s_["last"], "weeks": s_["weeks"], "k/n": f"{s_['mean_fs']:.3f}", "span": f"{s_['span_start']} -> {s_['span_end']}", "rule": pp(s_["rule"]), "switch": pp(s_["switch"]), "diff": pp(s_["diff"])} for s_ in x["stretches"]]
            P(f"\n{b}, {win}: {x['n']} stretches, {WK[b][win]['extra']} extra weeks; the rule is ahead of the switch over {x['n_ahead']} of {x['n']} spans")
            tab(pd.DataFrame(rows_))
            P(f"   CAGR difference rule - switch, all stretches in the path: {pp(x['cagr_diff_all'], 2)} pp; with the stretch of largest |diff| (no. {x['largest_no']}, {pp(x['largest_diff'])} pp of log return) removed from both series: {pp(x['cagr_diff_wo'], 2)} pp"
              f"; sign {'CHANGES' if x['sign_change'] else 'does not change'} when it is removed")
    # patterns
    PT = {}
    P(f"\nWeeks by signal pattern (Nifty 100, Midcap 100, Smallcap 100; B = BUY, S = SELL), full window {start[BOOKS[0]]} -> {end}: weeks, weeks the rule is IN, weeks the switch is IN, mean FS in those weeks:")
    for b in BOOKS:
        d = DEC[(b, "full")]
        rows_ = []
        PT[b] = {"patterns": {}, "fs": {}}
        for pat, g in sorted(d.groupby("pattern"), key=lambda kv: kv[0], reverse=True):
            PT[b]["patterns"][pat] = {"weeks": len(g), "rule_in": int(g.state_rule.sum()), "switch_in": int(g.state_switch.sum()), "mean_fs": float(g.fs.mean())}
            rows_.append({"pattern": pat, "weeks": len(g), "rule IN": int(g.state_rule.sum()), "switch IN": int(g.state_switch.sum()), "mean FS": num(g.fs.mean())})
        P(f"\n{b} ({d.decision_date.iloc[0]} -> {d.decision_date.iloc[-1]}, {len(d)} weeks):")
        tab(pd.DataFrame(rows_))
        bins = [("FS = 0", d.fs == 0), ("0 < FS < 0.60", (d.fs > 0) & (d.state_rule == 0)), ("0.60 <= FS < 1", (d.state_rule == 1) & (d.fs < 1)), ("FS = 1", d.fs == 1)]
        rows_ = []
        for nm, mk in bins:
            g = d[mk]
            PT[b]["fs"][nm] = {"weeks": len(g), "rule_in": int(g.state_rule.sum()), "switch_in": int(g.state_switch.sum())}
            rows_.append({"FS": nm, "weeks": len(g), "rule IN": int(g.state_rule.sum()), "switch IN": int(g.state_switch.sum())})
        tab(pd.DataFrame(rows_))
        x = WK[b]["full"]
        P(f"   stocks held n: min {x['nheld_min']}, median {x['nheld_median']:g}, max {x['nheld_max']}; weeks with 0 < FS < 1: {x['partial_fs']}; exact ties FS = 0.60: {x['ties']} (float formula differs in {x['float_differs']}); decision flips rule / switch: {x['flips_rule']} / {x['flips_switch']}; "
          f"rule flips with no signal flip (a tag change): {x['flips_rule_no_signal']}; events (rule / switch): {len(EV[(b, 'full')])} / {int(S(b, 'switch').events)}")
    R["patterns"] = PT
    # tag sources
    P(f"\nTag source of the weekly reads (stock-weeks of decision_stocks.csv, full window {start[BOOKS[0]]} -> {end}; 'membership' = real index membership, only from 2026-04-09; the rest is the rank rule):")
    rows_, TS = [], {}
    for b in BOOKS:
        g = ds[(ds.book == b) & (ds.window == "full")]
        vc = g.tag_source.value_counts()
        TS[b] = {s_: int(vc.get(s_, 0)) for s_ in ("rank", "membership", "nonmember_rank", "unranked")}
        TS[b]["total"] = int(len(g))
        TS[b]["rank_share"] = float((TS[b]["rank"] + TS[b]["nonmember_rank"]) / len(g))
        rows_.append({"book": b, "reads": len(g), "rank": TS[b]["rank"], "membership": TS[b]["membership"], "non-member rank": TS[b]["nonmember_rank"], "unranked": TS[b]["unranked"], "rank-rule share": pc(TS[b]["rank_share"])})
    tab(pd.DataFrame(rows_))
    R["tag_sources"] = TS

    # ══ 4.4 verdict ═════════════════════════════════════════════════════════
    head(f"4.4  VERDICT AGAINST EACH PRE-REGISTERED CRITERION AND THE OUTCOME MAP\n(after cost at {PRIMARY:g} bps, full window; {NOCHANCE}; no finding stronger than PROVISIONAL)")
    tab(pd.DataFrame([{"criterion": c_, "hypothesis": HY[c_], "books passing": f"{CH['count'][c_]} of {len(BOOKS)}", "books": ", ".join(f"{b}:{'P' if CH['books'][b][c_] else 'F'}" for b in BOOKS), "verdict": "PASS" if CH["pass"][c_] else "FAIL"} for c_ in ("C1", "C2", "C3", "C4")]))
    nrep = [b for b in BOOKS if not CH["books"][b]["reportable"]]
    P("Reportability: " + (f"NOT REPORTABLE for C3 and C4: {', '.join(nrep)} (counted as not passing)." if nrep else f"all {len(BOOKS)} books clear the 5-stretch gate on the full window (stretches {[CH['books'][b]['stretches'] for b in BOOKS]})."))
    nsc = sum(R7[b]["full"]["sign_change"] for b in BOOKS)
    P(f"R7: removing the single stretch of largest |diff| changes the sign of the CAGR difference rule - switch in {nsc} of {len(BOOKS)} books (full window). The frozen text gives no number for 'one stretch carries the difference'; this is this script's operational reading, "
      "the stretch table above is the evidence to read.")
    ap_ = []
    if all(V.values()):
        ap_.append("C1, C2, C3, C4 PASS: on this window the FS rule beat the parent and the switch on return and on return per unit of fall (descriptive; " + NOCHANCE + ")")
    if V["C3"] and not V["C4"]:
        ap_.append("C3 PASS, C4 FAIL: more return than the switch, but a worse fall: the gain came with exposure; read the constant-mix control")
    if not V["C3"]:
        ap_.append("C3 FAIL: the switch earned as much or more: the extra weeks the FS rule holds did not pay")
    if not V["C1"] or not V["C2"]:
        ap_.append("C1 or C2 FAIL: the rule did not beat holding the parent on that measure in at least 2 books")
    if nsc >= 2:
        ap_.append(f"R7 reading: the CAGR difference changes sign when the largest stretch is removed in {nsc} books: the comparison may be one episode, whatever C3 says")
    if nrep:
        ap_.append(f"a realisation is NOT REPORTABLE ({', '.join(nrep)}): state it; the other books are read on their own")
    P("\nOutcome map rows that apply (T10.md section 2; descriptive; " + NOCHANCE + "):")
    for x in ap_ or ["(none of the listed patterns: read the tables)"]:
        P("  -", x)
    R["outcome_map"] = ap_
    P("\nWhat this does not say: there is no null, so none of this shows the rule beats chance or picks better than chance; the negative control and the oracle were not run, so the pipeline's ability to detect an edge is untested.")

    # ══ 4.5 robustness ═════════════════════════════════════════════════════
    head(f"4.5  ROBUSTNESS AND DESCRIPTIVE CHECKS R1-R8\n(reported; they decide a finding's status note, not the verdicts; {NOCHANCE})")
    for key, nm in ((f"full|lbes|0", "R1a, 0 bps (before cost)"), (f"full|lbes|50", "R1b, 50 bps"), ("live|lbes|20.8", "R2, live window"), ("full|liq|20.8", "R3, LIQUIDCASE cash leg")):
        win, cash, cost = key.split("|")
        cost = float(cost)
        w0 = start[BOOKS[0]] if win == "full" else live_first[BOOKS[0]]
        P(f"\n{nm}: C1-C4 at {cost:g} bps, {win} window {w0} -> {end}, {'LBES' if cash == 'lbes' else 'LIQUIDCASE (from 2024-01-24)'} cash")
        crit_tables(R["crit"][key], cost, win, cash, nm)
    P(f"\nR1c, trades and cost paid (full window {start[BOOKS[0]]} -> {end}, cost in NAV units on a base of 1.000): the rule, the switch and the constant mix at 0, {PRIMARY:g} and 50 bps")
    rows_ = []
    TC = {}
    for b in BOOKS:
        TC[b] = {}
        for k_ in ("rule", "switch", "constant_mix"):
            TC[b][k_] = {f"{c:g}": {"trades": float(S(b, k_, c).trades), "cost_paid": float(S(b, k_, c).cost_paid)} for c in COSTS}
            rows_.append({"book": b, "series": KLAB[k_].split(" (")[0], **{f"trades@{c:g}": int(TC[b][k_][f'{c:g}']['trades']) for c in COSTS}, **{f"cost@{c:g}": num(TC[b][k_][f'{c:g}']['cost_paid'], 4) for c in COSTS}})
    tab(pd.DataFrame(rows_))
    R["tc"] = TC
    # R4
    P(f"\nR4, tag error (a sensitivity of the data, not a null of the claim; no pass mark): {a.expect_r4} draws per book. At every weekly tag read each rank-sourced stock has its band replaced with probability 7.93% (1 - the 92.07% agreement of REVIEW.md check 6) by one of the "
      f"other two bands; membership tags are not perturbed. default_rng([10, draw_id, book_no]). Full window {start[BOOKS[0]]} -> {end}, {PRIMARY:g} bps, LBES. Rule CAGR minus switch CAGR across the draws, against the unperturbed point:")
    rows_, R4 = [], {}
    for b in BOOKS:
        g = r4[r4.book == b]
        dv = g.diff_vs_switch.values
        pt = S(b, "rule").cagr - S(b, "switch").cagr
        wc = g.weeks_changed.values / g.n_decisions.values
        R4[b] = {"n": int(len(g)), "point": float(pt), "mean": float(dv.mean()), "p5": float(np.percentile(dv, 5)), "median": float(np.median(dv)), "p95": float(np.percentile(dv, 95)), "min": float(dv.min()), "max": float(dv.max()),
                 "share_pos": float((dv > 0).mean()), "n_pos": int((dv > 0).sum()), "wk_mean": float(wc.mean()), "wk_min": float(wc.min()), "wk_max": float(wc.max()), "cagr_mean": float(g.cagr.mean()), "rank_reads": int(g.rank_tag_reads.iloc[0]), "n_dec": int(g.n_decisions.iloc[0])}
        x = R4[b]
        rows_.append({"book": b, "draws": x["n"], "unperturbed pp": pp(x["point"]), "mean pp": pp(x["mean"]), "5th pp": pp(x["p5"]), "median pp": pp(x["median"]), "95th pp": pp(x["p95"]), "min pp": pp(x["min"]), "max pp": pp(x["max"]),
                      "share > 0": f"{x['n_pos']}/{x['n']} = {pc(x['share_pos'])}", "weeks changed mean (min-max)": f"{pc(x['wk_mean'], 2)} ({pc(x['wk_min'], 2)}-{pc(x['wk_max'], 2)})"})
    tab(pd.DataFrame(rows_))
    P("   (weeks changed = decisions whose IN or OUT state differs from the unperturbed rule's, as a share of the weekly decisions.)")
    R["r4"] = R4
    # R5
    P(f"\nR5, threshold curve (descriptive; five settings shown, none selected, no claim comes from this table; 0.60 is production's value and the only reference setting). Full window {start[BOOKS[0]]} -> {end}, {PRIMARY:g} bps, LBES; IN iff k/n >= t, decided in integers:")
    R5 = {}
    for b in BOOKS:
        R5[b] = {}
        rows_ = []
        for k_ in THR:
            s_ = S(b, k_)
            R5[b][k_] = {"cagr": float(s_.cagr), "max_dd": float(s_.max_dd), "calmar": float(s_.calmar), "share_in": float(s_.invested_weeks) / nd[(b, "full")], "events": float(s_.events)}
            rows_.append({"threshold t": THR_LAB[k_], "CAGR": pc(s_.cagr), "max DD": pc(s_.max_dd), "Calmar": num(s_.calmar), "share IN": pc(R5[b][k_]["share_in"]), "events": int(s_.events)})
        P(f"\n{b}:")
        tab(pd.DataFrame(rows_))
    R["r5"] = R5
    # R6
    P(f"\nR6, weight-weighted FS (descriptive): FS computed on the stocks' listed weights, IN iff >= 0.60. Full window {start[BOOKS[0]]} -> {end}, {PRIMARY:g} bps, LBES:")
    rows_, R6 = [], {}
    for b in BOOKS:
        s_, r_ = S(b, "weight_fs"), S(b, "rule")
        d = DEC[(b, "full")]
        R6[b] = {"cagr": float(s_.cagr), "max_dd": float(s_.max_dd), "calmar": float(s_.calmar), "share_in": float(s_.invested_weeks) / nd[(b, "full")], "weeks_differ": int((d.state_weight_fs != d.state_rule).sum()), "rule_cagr": float(r_.cagr), "rule_dd": float(r_.max_dd), "rule_calmar": float(r_.calmar),
                 "switch_cagr": float(S(b, "switch").cagr), "parent_cagr": float(S(b, "parent").cagr), "parent_dd": float(S(b, "parent").max_dd), "switch_calmar": float(S(b, "switch").calmar)}
        x = R6[b]
        rows_.append({"book": b, "weight-FS CAGR": pc(x["cagr"]), "count-FS CAGR": pc(x["rule_cagr"]), "weight-FS max DD": pc(x["max_dd"]), "count-FS max DD": pc(x["rule_dd"]), "weight-FS Calmar": num(x["calmar"]), "share IN": pc(x["share_in"]), "weeks decision differs": x["weeks_differ"],
                      "> parent CAGR": "yes" if x["cagr"] > x["parent_cagr"] else "no", "> switch CAGR": "yes" if x["cagr"] > x["switch_cagr"] else "no"})
    tab(pd.DataFrame(rows_))
    R["r6"] = R6
    # R7 summary was printed in 4.3
    P("\nR7: the stretch tables and the 'without the largest stretch' CAGR differences are in section 4.3.")
    # R8
    P(f"\nR8, context only (the AA books run other rules): live window {live_first[BOOKS[0]]} -> {end}, CAGR of the published AA book (D15, rebased, same sessions) beside the rule's and the switch's at {PRIMARY:g} bps and the parent's:")
    rows_, R8 = [], {}
    for b in BOOKS:
        aa = stt[(stt.book == b) & (stt.window == "live") & (stt.kind == "published_aa")]
        r_, s_, p_, pp_ = S(b, "rule", win="live"), S(b, "switch", win="live"), S(b, "parent", win="live"), S(b, "published_parent", win="live")
        R8[b] = {"aa_scid": None if not len(aa) else str(aa.iloc[0].aa_scid), "aa_cagr": None if not len(aa) else float(aa.iloc[0].cagr), "aa_dd": None if not len(aa) else float(aa.iloc[0].max_dd), "rule": float(r_.cagr), "switch": float(s_.cagr), "parent": float(p_.cagr), "pub_parent": float(pp_.cagr),
                 "rule_dd": float(r_.max_dd), "switch_dd": float(s_.max_dd)}
        x = R8[b]
        rows_.append({"book": b, "published AA book": x["aa_scid"] or "", "AA CAGR": pc(x["aa_cagr"]), "AA max DD": pc(x["aa_dd"]), "rule CAGR": pc(x["rule"]), "switch CAGR": pc(x["switch"]), "parent (rebuilt)": pc(x["parent"]), "published parent": pc(x["pub_parent"])})
    tab(pd.DataFrame(rows_))
    R["r8"] = R8
    # headline in other words
    P("\nR2 live-window weeks: " + "; ".join(f"{b}: {WK[b]['live']['extra']} extra weeks in {WK[b]['live']['stretches']} stretches ({'REPORTABLE' if WK[b]['live']['reportable'] else 'NOT REPORTABLE'})" for b in BOOKS))

    (outdir / "analysis.log").write_text(out.getvalue(), encoding="utf-8")
    (outdir / "analysis.json").write_text(json.dumps(jsonable(R), indent=1), encoding="utf-8")
    print(f"\nwrote {outdir / 'analysis.log'} and analysis.json")


if __name__ == "__main__":
    main()
