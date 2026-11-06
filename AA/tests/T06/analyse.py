"""T06 analysis: reads only the shipped evidence in evidence/<run>/ and prints section 4 of the write-up.

    python tests/T06/analyse.py [--run headline]            prints to stdout and writes tests/T06/analysis.log
    python tests/T06/analyse.py --evidence DIR [--out DIR]  point at another evidence directory (e.g. a synthetic one);
                                                            analysis.log then goes to --out (default: DIR itself), never to tests/T06

Imports nothing from the engine. Percentile = (worse + 0.5 * tied) / draws * 100; p-value = (1 + at least as good) / (draws + 1);
ties are equal within a relative 1e-12 (T06.md section 2). N4.10 decides C1 and C2; N4.9 (re-run on this window) is shown beside them.
Exits non-zero if a validity gate (V1-V5) failed or if nothing was compared.

Gates V3, V4 and V5(b, c) are re-derived here from the evidence files themselves (draw_states.npz, draws.csv, decisions.csv,
daily_nav.csv, count_table.json, T03's evidence), so this script does not depend on the key names inside audit.json's v3 block,
regression_t03.json or sampler_selftest.json; those files are printed and, where a clear verdict key exists, must agree.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import re
import sys
from math import comb
from pathlib import Path

import numpy as np
import pandas as pd

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
AA = HERE.parents[1]
BOOKS = ["SCMO_0003", "SCMO_0007", "SCMO_0010", "SCMO_0029"]
PRIMARY = 20.8
COSTS = (0.0, PRIMARY, 50.0)
PASS_PCT = 90.0
LO = 2
NULLS = ("N4.10", "N4.9")  # the deciding null first
HIGHER_BETTER = {"cagr": True, "max_dd": True, "calmar": True, "vol": False, "ulcer": False, "days_below_10pct": False, "longest_underwater": False}
LIVE_START = "2021-11-01"
V4_NAV_END = pd.Timestamp("2026-08-07")
out = io.StringIO()
GATES: dict[str, bool] = {}


def P(*a):
    s = " ".join(str(x) for x in a)
    print(s)
    out.write(s + "\n")


def table(df: pd.DataFrame, fmt: dict | None = None):
    fmt = fmt or {}
    d = df.copy()
    for c, f in fmt.items():
        if c in d:
            d[c] = d[c].map(lambda v: "" if (isinstance(v, float) and math.isnan(v)) else f(v))
    P(d.to_string(index=False))


def head(title: str):
    P("\n" + "=" * 100 + "\n" + title + "\n" + "=" * 100)


def rank(x: float, draws: np.ndarray, higher_better: bool) -> dict:
    tie = np.isclose(draws, x, rtol=1e-12, atol=0)
    better = ((draws > x) if higher_better else (draws < x)) & ~tie
    worse = ((draws < x) if higher_better else (draws > x)) & ~tie
    n = len(draws)
    return {"worse": int(worse.sum()), "tied": int(tie.sum()), "better": int(better.sum()), "draws": n,
            "percentile": (worse.sum() + 0.5 * tie.sum()) / n * 100, "p": (1 + better.sum() + tie.sum()) / (n + 1)}


def stats_from_nav(nav: np.ndarray) -> dict:
    yrs = (len(nav) - 1) / 252
    dd = nav / np.maximum.accumulate(nav) - 1
    return {"cagr": nav[-1] ** (1 / yrs) - 1, "max_dd": dd.min()}


def find_key(obj, names):
    """First value whose key (lower case) is in `names`, searching dicts and lists recursively; None if absent."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if str(k).lower() in names and not isinstance(v, (dict, list)):
                return v
        for v in obj.values():
            r = find_key(v, names)
            if r is not None:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = find_key(v, names)
            if r is not None:
                return r
    return None


def flags(obj, key="pass") -> list:
    """Every boolean stored under `key` anywhere in a JSON structure (the engine's own pass flags)."""
    out_ = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == key and isinstance(v, bool):
                out_.append(v)
            out_ += flags(v, key)
    elif isinstance(obj, list):
        for v in obj:
            out_ += flags(v, key)
    return out_


def runs(a) -> list[tuple[int, int]]:
    """Maximal spells of a 0/1 sequence as (state, length)."""
    a = np.asarray(a)
    if len(a) == 0:
        return []
    cut = np.flatnonzero(a[1:] != a[:-1]) + 1
    st = np.concatenate(([0], cut))
    en = np.concatenate((cut, [len(a)]))
    return [(int(a[i]), int(j - i)) for i, j in zip(st, en)]


def lens(a, v) -> list[int]:
    return [n for s, n in runs(a) if s == v]


def n_ways(k: int, S: int, lo: int, hi: int) -> int:
    """Inclusion-exclusion count of k integers in [lo, hi] summing to S (not the engine's DP)."""
    t = S - k * lo
    tot = 0
    for j in range(k + 1):
        top = t - j * (hi - lo + 1) + k - 1
        if top < k - 1:
            continue
        tot += (-1) ** j * comb(k, j) * comb(top, k - 1)
    return tot


def count_entries(obj, path=()):
    """Yield (path, dict) for every dict holding n_ways, wherever it sits in count_table.json."""
    if isinstance(obj, dict):
        if "n_ways" in obj:
            yield path, obj
            return
        for k, v in obj.items():
            yield from count_entries(v, path + (str(k),))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from count_entries(v, path + (str(i),))


def classify(path, ent):
    """(book, window, state) of a count_table entry from its nesting or its own fields; state in {'in', 'out'}."""
    toks = []
    for p in path:
        toks += re.split(r"[|/ ]", p)
    for f in ("book", "window", "state"):
        if f in ent:
            toks.append(str(ent[f]))
    book = next((t for t in toks if t.startswith("SCMO_")), None)
    win = next((t for t in toks if t in ("full", "live")), None)
    st = next(({"in": "in", "1": "in", "out": "out", "0": "out"}[t.lower()] for t in toks if t.lower() in ("in", "out", "1", "0")), None)
    return book, win, st


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="headline")
    ap.add_argument("--evidence", default=None, help="explicit evidence directory (overrides --run)")
    ap.add_argument("--out", default=None, help="where analysis.log goes (default tests/T06 for --run, the evidence directory for --evidence)")
    ap.add_argument("--t03", default=str(AA / "tests" / "T03" / "evidence" / "headline"), help="T03's evidence (historical reference and V4)")
    ap.add_argument("--doc", default=str(HERE / "T06.md"), help="T06.md, read only, for the pre-registration hash")
    ap.add_argument("--books", default=None, help="comma list; for engine smoke runs that hold fewer than the four books (the verdict counts then mean nothing)")
    a = ap.parse_args()
    if a.books:
        BOOKS[:] = a.books.split(",")
    B7 = "SCMO_0007" if "SCMO_0007" in BOOKS else BOOKS[-1]
    ev = Path(a.evidence) if a.evidence else HERE / "evidence" / a.run
    outdir = Path(a.out) if a.out else (ev if a.evidence else HERE)
    t03 = Path(a.t03)

    dec = pd.read_csv(ev / "decisions.csv")
    st = pd.read_csv(ev / "stats.csv")
    dr = pd.read_csv(ev / "draws.csv")
    tr = pd.read_csv(ev / "trades.csv")
    nav = pd.read_csv(ev / "daily_nav.csv", parse_dates=["date"])
    g4 = pd.read_csv(ev / "g_engine.csv")
    au = json.loads((ev / "audit.json").read_text(encoding="utf-8"))
    ct = json.loads((ev / "count_table.json").read_text(encoding="utf-8"))
    states = np.load(ev / "draw_states.npz")
    vj = ev / "verify_t06.json"
    doc = Path(a.doc).read_text(encoding="utf-8")
    region = doc[doc.index("\n## 1. Idea and references") + 1:doc.index("\n## 4. Results") + 1]
    region = "\n".join(l.rstrip() for l in region.replace("\r\n", "\n").split("\n"))
    sha = hashlib.sha256(region.encode("utf-8")).hexdigest()
    m_sha = re.search(r"§1–§3 sha256:\*\* `([^`]*)`", doc)
    sha_hdr = m_sha.group(1) if m_sha else "?"

    # ── the rule, from decisions.csv ──────────────────────────────────────────
    rule = {b: dec[dec.book == b].sort_values("j").state.values.astype(int) for b in BOOKS}
    weeks = {b: len(rule[b]) for b in BOOKS}
    rin = {b: lens(rule[b], 1) for b in BOOKS}
    rout = {b: lens(rule[b], 0) for b in BOOKS}
    HI_IN = max(max(rin[b]) for b in BOOKS)
    HI_OUT = max(max(rout[b]) for b in BOOKS)

    S = lambda b, kind="strategy", cost=PRIMARY, win="full", cash="lbes": st[(st.book == b) & (st.window == win) & (st.cash == cash) & (st.cost_bps == cost) & (st.kind == kind)].iloc[0]
    D = lambda b, typ, cost=PRIMARY, win="full", cash="lbes": dr[(dr.book == b) & (dr.window == win) & (dr.cash == cash) & (dr.cost_bps == cost) & (dr.draw_type == typ)].sort_values("draw_id")
    ndraws = int(len(D("SCMO_0003", "N4.10")))

    # sessions per week: from the strategy's calendar and trade dates (T03 convention: week j covers sessions wk0[j] -> wk0[j+1])
    cal = {b: nav[(nav.book == b) & (nav.cost_bps == PRIMARY) & (nav.run == "strategy")].sort_values("date").date.values for b in BOOKS}
    wsess = {}
    for b in BOOKS:
        d_ = dec[dec.book == b].sort_values("j").reset_index(drop=True)
        nses = len(cal[b])
        wk0 = [0] + [nses - 1 if pd.isna(t) else int(np.searchsorted(cal[b], np.datetime64(pd.Timestamp(t)))) for t in d_.trade_date.iloc[1:]]
        wsess[b] = np.array(wk0[1:] + [nses - 1]) - np.array(wk0)
    rule_sessions = {b: int(rule[b] @ wsess[b]) for b in BOOKS}

    P("T06 analysis. Run:", ev.name, "| draws per book, cost and null:", f"{ndraws:,}", "| deciding null: N4.10; N4.9 re-run on this window shown beside it")
    P("Window: %s -> %s (SCMO_0007 from %s), %d weekly decisions (SCMO_0007 %d); live window from %s" % (
        dec[dec.book == "SCMO_0003"].decision_date.iloc[0], dec[dec.book == "SCMO_0003"].decision_date.iloc[-1],
        dec[dec.book == B7].decision_date.iloc[0], weeks["SCMO_0003"], weeks[B7], LIVE_START))
    P("Pre-registration sha256 in the header:", sha_hdr[:16], "| recomputed now:", sha[:16], "| match:", sha_hdr == sha)
    P("Bounds: lengths in [%d, %d] weeks (in-spells) and [%d, %d] (out-spells), the rule's longest spells on the full window" % (LO, HI_IN, LO, HI_OUT))
    P("Evidence read:", ", ".join(sorted(p.name for p in ev.iterdir())))

    # ── 4.0b gates ────────────────────────────────────────────────────────────
    head("4.0b  GATES\n" + "(V1 independent check, V2 point in time, V3 the nulls hold their tables, V4 regression to T03 and always-in, V5 the sampler is exact)")
    gates = GATES
    if vj.exists():
        v = json.loads(vj.read_text(encoding="utf-8"))
        ok = bool(v.get("exit_ok")) and v.get("gate_failures_and_missing", 1) == 0 and v.get("gate_compared", 0) > 0 and bool(v.get("selftest", {}).get("detected"))
        P("V1 independent check (verify_t06.py): ", "PASS" if ok else "FAIL", f"| gate comparisons {v.get('gate_compared', 0):,}, failures and missing {v.get('gate_failures_and_missing')}, "
          f"corrupted copy detected: {v.get('selftest', {}).get('detected')}")
        gates["V1"] = ok
    else:
        P("V1 independent check: NOT RUN (%s missing)" % vj)
        gates["V1"] = False
    viol = cnt = 0
    for b in BOOKS:
        for k, val in au["books"][b].items():
            if k.startswith("v2_") and isinstance(val, (int, float)):
                if k.endswith("_checked"):
                    cnt += val
                else:
                    viol += val
    P(f"V2 point in time: violations {viol} of {cnt:,} checks (labels dated after the decision: 0 required; trade not after its decision: 0 required)")
    gates["V2"] = viol == 0 and cnt > 0

    # V3, derived here from draw_states.npz and draws.csv
    ctab = {}
    for path, ent in count_entries(ct):
        bk, win, stt = classify(path, ent)
        if bk and win and stt:
            ctab[(bk, win, stt)] = {"k": int(ent.get("k", ent.get("spells_k"))), "S": int(ent.get("S", ent.get("weeks_S"))), "lo": int(ent["lo"]), "hi": int(ent["hi"]), "n_ways": int(ent["n_ways"])}
    missing_ct = [(b, w, s_) for b in BOOKS for w in ("full", "live") for s_ in ("in", "out") if (b, w, s_) not in ctab]
    if missing_ct:
        P("count_table.json: MISSING entries", missing_ct)
    v3 = {"keys": 0, "draws": 0, "bad": 0, "rows": 0, "rows_bad": 0, "str_bad": 0, "sess_checked": 0, "sess_bad": 0, "notes": []}
    pos_means = []  # V5(c)
    live_rule = {}
    for b in BOOKS:
        for win in ("full", "live"):
            ref = {}
            for typ in ("N4.9", "N4.10"):  # N4.9 first: the live window's first state and lengths come from it
                key = f"{b}|{win}|{typ}"
                if key not in states.files:
                    v3["notes"].append(f"missing {key}")
                    v3["bad"] += 1
                    continue
                A = states[key].astype(np.int8)
                v3["keys"] += 1
                nd, nw = A.shape
                if win == "full":
                    s0, tin, tout, kin, kout, wk = rule[b][0], int(rule[b].sum()), int(len(rule[b]) - rule[b].sum()), len(rin[b]), len(rout[b]), weeks[b]
                    sin_sorted, sout_sorted = sorted(rin[b]), sorted(rout[b])
                else:
                    ci, co = ctab.get((b, "live", "in")), ctab.get((b, "live", "out"))
                    if not ci or not co:
                        v3["bad"] += 1
                        continue
                    kin, kout, tin, tout, wk = ci["k"], co["k"], ci["S"], co["S"], nw
                    s0 = int(A[0, 0]) if typ == "N4.9" else live_rule[b]["s0"]
                    sin_sorted = sout_sorted = None
                for i in range(nd):
                    row = A[i]
                    li, lo_ = lens(row, 1), lens(row, 0)
                    bad = (nw != wk or int(row[0]) != s0 or len(li) != kin or len(lo_) != kout or sum(li) != tin or sum(lo_) != tout)
                    if typ == "N4.9":
                        if win == "full":
                            bad |= sorted(li) != sin_sorted or sorted(lo_) != sout_sorted
                        else:
                            if i == 0:
                                ref = {"in": sorted(li), "out": sorted(lo_)}
                            bad |= sorted(li) != ref["in"] or sorted(lo_) != ref["out"]
                    else:
                        bad |= (min(li) < LO or max(li) > HI_IN or min(lo_) < LO or max(lo_) > HI_OUT)
                    v3["draws"] += 1
                    v3["bad"] += int(bad)
                if win == "live" and typ == "N4.9":
                    live_rule[b] = {"s0": int(A[0, 0]), "in": ref["in"], "out": ref["out"]}
                # V5(c): mean length at each spell position across draws
                if typ == "N4.10":
                    try:
                        Li = np.array([lens(A[i], 1) for i in range(nd)], dtype=float)
                        Lo = np.array([lens(A[i], 0) for i in range(nd)], dtype=float)
                    except ValueError:  # ragged: some draw has the wrong spell count, already counted as bad above
                        v3["notes"].append(f"ragged spell counts in {key}")
                        continue
                    for nm, M, k_, S_ in (("in", Li, kin, tin), ("out", Lo, kout, tout)):
                        se = M.std(axis=0, ddof=1) / math.sqrt(nd)
                        z_ = (M.mean(axis=0) - S_ / k_) / np.where(se > 0, se, np.nan)
                        pos_means.append({"book": b, "window": win, "state": nm, "k": k_, "S": S_, "mean_of_means": float(M.mean()), "target": S_ / k_,
                                          "worst_z": float(np.nanmax(np.abs(z_))) if np.isfinite(z_).any() else 0.0})
                    if win == "full":
                        sess = (A.astype(np.int64) @ wsess[b])
                        got = D(b, typ).sessions_invested.values if "sessions_invested" in dr else None
                        if got is not None and len(got) == nd:
                            v3["sess_checked"] += nd
                            v3["sess_bad"] += int((sess != got).sum())
                if typ == "N4.9" and win == "full":
                    sess = (A.astype(np.int64) @ wsess[b])
                    got = D(b, typ).sessions_invested.values if "sessions_invested" in dr else None
                    if got is not None and len(got) == nd:
                        v3["sess_checked"] += nd
                        v3["sess_bad"] += int((sess != got).sum())
    # draws.csv rows against the rule and the saved states
    string_of = {}
    for key in states.files:
        A = states[key]
        string_of[key] = (["|".join(map(str, lens(A[i], 1))) for i in range(A.shape[0])], ["|".join(map(str, lens(A[i], 0))) for i in range(A.shape[0])])
    for (b, win, cash, cost, typ), g in dr.groupby(["book", "window", "cash", "cost_bps", "draw_type"]):
        v3["rows"] += len(g)
        if win == "full":
            wk_, inv = weeks[b], int(rule[b].sum())
            kin, kout = len(rin[b]), len(rout[b])
        else:
            kin, kout, inv = ctab[(b, "live", "in")]["k"], ctab[(b, "live", "out")]["k"], ctab[(b, "live", "in")]["S"]
        bad = int(((g.invested_weeks != inv) | (g.n_in_spells != kin) | (g.n_out_spells != kout)).sum())
        ids = g.draw_id.values
        bad += int((np.sort(ids) != np.arange(len(g))).any())
        key = f"{b}|{'full' if cash == 'liquidcase' else win}|{typ}"
        if key in string_of and "in_lengths" in g and "out_lengths" in g:
            si, so = string_of[key]
            for i_, l_in, l_out in zip(ids, g.in_lengths.astype(str).values, g.out_lengths.astype(str).values):
                if i_ >= len(si) or l_in != si[i_] or l_out != so[i_]:
                    v3["str_bad"] += 1
        v3["rows_bad"] += bad
    P(f"V3 the nulls hold their tables: {v3['draws']:,} saved draws checked over {v3['keys']} state arrays (weeks, first state, spell counts, sums, N4.9 sorted lengths, N4.10 bounds), bad {v3['bad']}; "
      f"{v3['rows']:,} draws.csv rows checked (invested weeks, spell counts, ids), bad {v3['rows_bad']}; in_lengths/out_lengths strings against the states: {v3['str_bad']} differ {v3['notes'] or ''}")
    P(f"   sessions_invested recomputed from the states (full window): {v3['sess_checked']:,} draws, {v3['sess_bad']} differ (informational: a difference means the definition here and the engine's differ; the verifier owns the exact definition)")
    au_v3 = au.get("v3")
    eng_v3 = flags(au_v3) if au_v3 is not None else []
    if au_v3 is not None:
        P(f"   audit.json v3 block (the engine's own check): {len(eng_v3)} pass flags, all true: {all(eng_v3) and len(eng_v3) > 0}; draws per type {au_v3.get('draws_per_type') if isinstance(au_v3, dict) else '?'}")
    sup = {}
    for b in BOOKS:
        sup[(b, "full")] = (min(rin[b] + rout[b]) >= LO and max(rin[b]) <= HI_IN and max(rout[b]) <= HI_OUT)
        if b in live_rule:
            sup[(b, "live")] = (min(live_rule[b]["in"] + live_rule[b]["out"]) >= LO and max(live_rule[b]["in"]) <= HI_IN and max(live_rule[b]["out"]) <= HI_OUT)
    P("   the rule's own lengths lie within the bounds (so every N4.9 draw is an allowed N4.10 configuration):", {f"{b[-4:]}/{w}": ok for (b, w), ok in sup.items()})
    gates["V3"] = (all(eng_v3) if eng_v3 else True) and v3["bad"] == 0 and v3["rows_bad"] == 0 and v3["str_bad"] == 0 and v3["draws"] > 0 and all(sup.values()) and not missing_ct

    # V4
    P("V4 always-in at 0 cost vs the published NAV (G0: +-0.25 pp/yr overall, +-0.5 pp every calendar year) and vs the Step 1 rebuild:")
    table(g4, {"cagr_gap_pp_yr": lambda x: f"{x:+.3f}", "worst_year_gap_pp": lambda x: f"{x:+.3f}", "max_rel_diff_vs_step1_rebuild": lambda x: f"{x:.1e}"})
    if "window_first" in g4:
        P("   (the always-in book runs over %s -> %s, the whole window)" % (g4.window_first.iloc[0], g4.window_last.iloc[0]))
    rel_col = g4["max_rel_diff_vs_step1_rebuild"] if "max_rel_diff_vs_step1_rebuild" in g4 else pd.Series([float("nan")])  # T06 has no Step 1 rebuild: the column may be empty
    g0_ok = bool((g4["overall"] == "PASS").all() and (g4["yearly"] == "PASS").all() and (rel_col.isna().all() or (rel_col.dropna() < 1e-6).all()) and len(g4) >= len(BOOKS))
    reg = {"dec_compared": 0, "dec_bad": 0, "nav_compared": 0, "nav_bad": 0, "worst": 0.0, "ok": False}
    if (t03 / "decisions.csv").exists() and (t03 / "daily_nav.csv").exists():
        d3 = pd.read_csv(t03 / "decisions.csv")
        d3 = d3[d3.book.isin(BOOKS)]
        mm = d3.merge(dec, on=["book", "decision_date"], how="left", suffixes=("_t03", ""))
        reg["dec_compared"] = len(mm)
        reg["dec_bad"] = int(mm.state.isna().sum() + (mm.state_t03 != mm.state).sum())
        n3 = pd.read_csv(t03 / "daily_nav.csv", parse_dates=["date"])
        n3 = n3[(n3.run.isin(["strategy", "hold_parent", "sleeve_only"])) & (n3.date <= V4_NAV_END) & (n3.book.isin(BOOKS))]
        mn = n3.merge(nav, on=["book", "date", "cost_bps", "run"], how="left", suffixes=("_t03", ""))
        rel = (mn.nav / mn.nav_t03 - 1).abs()
        reg["nav_compared"] = len(mn)
        reg["nav_bad"] = int((rel.isna() | (rel > 1e-12)).sum())
        reg["worst"] = float(rel.max())
        reg["ok"] = reg["dec_compared"] > 0 and reg["nav_compared"] > 0 and reg["dec_bad"] == 0 and reg["nav_bad"] == 0
        P(f"   regression to T03 on the overlap: decisions {reg['dec_compared']:,} compared, {reg['dec_bad']} differ; NAVs (strategy, hold the parent, 100% sleeve; every cost; up to {V4_NAV_END.date()}) "
          f"{reg['nav_compared']:,} compared, {reg['nav_bad']} differ, worst relative difference {reg['worst']:.1e} (limit 1e-12). The constant mix is not compared: its average share f is the new series' own.")
    else:
        P("   regression to T03: NOT RUN (T03's decisions.csv or daily_nav.csv not found in %s)" % t03)
    rj = ev / "regression_t03.json"
    eng_v4 = []
    if rj.exists():
        rjd = json.loads(rj.read_text(encoding="utf-8"))
        eng_v4 = flags(rjd) + flags(rjd, "g0_pass")
        P(f"   regression_t03.json (the engine's own check): {len(eng_v4)} pass flags, all true: {all(eng_v4) and len(eng_v4) > 0}; rows compared: {rjd.get('nav_rows_compared')}")
    gates["V4"] = g0_ok and reg["ok"] and (all(eng_v4) if eng_v4 else True)

    # V5
    sj = ev / "sampler_selftest.json"
    chi_p, st_ok = None, None
    if sj.exists():
        sjd = json.loads(sj.read_text(encoding="utf-8"))
        chi_p = find_key(sjd, {"p", "p_value", "pvalue", "chi2_p", "chi_p", "chi_square_p", "chi2_pvalue", "chisq_p", "p_chi2"})
        fl = flags(sjd) + flags(sjd, "ok") + flags(sjd, "passed")
        st_ok = (all(fl) if fl else None)
        P(f"   sampler_selftest.json (the engine's own check): {len(fl)} pass flags, all true: {st_ok}")
    ways_bad = 0
    for (b, w, s_), e in sorted(ctab.items()):
        ways_bad += int(n_ways(e["k"], e["S"], e["lo"], e["hi"]) != e["n_ways"])
        ways_bad += int(e["lo"] != LO or (s_ == "in" and e["hi"] != HI_IN) or (s_ == "out" and e["hi"] != HI_OUT) or not (e["k"] * e["lo"] <= e["S"] <= e["hi"] * e["k"]))
    worstz = max(m["worst_z"] for m in pos_means) if pos_means else float("inf")
    P(f"V5 the sampler is exact: (a) chi-square on k=3, S=12, bounds [2, 6]: p = {chi_p} (need > 0.001; from sampler_selftest.json, which this script cannot recompute"
      f"{'; its own pass flag: ' + str(st_ok) if st_ok is not None else ''}); (b) count_table.json against inclusion-exclusion: {len(ctab)} entries, {ways_bad} differ or infeasible "
      f"(bounds {LO}/{HI_IN}/{HI_OUT}, feasibility 2k <= S <= hi k); (c) mean length at each spell position over the draws against S/k: worst |z| = {worstz:.2f} over {len(pos_means)} (book, window, state) sets (need < 4)")
    gates["V5"] = (chi_p is not None and float(chi_p) > 0.001 and (st_ok is None or bool(st_ok))) and ways_bad == 0 and len(ctab) > 0 and worstz < 4
    P("Gates:", {k: ("PASS" if v else "FAIL") for k, v in gates.items()}, "->", "ALL PASS" if all(gates.values()) else "A GATE FAILED: NOTHING BELOW MAY BE READ")

    # reportability
    rt = {}
    for b in BOOKS:
        ent = int(((rule[b][1:] == 1) & (rule[b][:-1] == 0)).sum()) + int(rule[b][0] == 1)
        ext = int(((rule[b][1:] == 0) & (rule[b][:-1] == 1)).sum())
        rt[b] = min(ent, ext)
    live_rt = {}
    for b in BOOKS:
        A = states[f"{b}|live|N4.9"].astype(int)[0]
        ent = int(((A[1:] == 1) & (A[:-1] == 0)).sum()) + int(A[0] == 1)
        ext = int(((A[1:] == 0) & (A[:-1] == 1)).sum())
        live_rt[b] = min(ent, ext)
    P("Reportability: round trips per book, full window (need 4):", rt, "| live window:", live_rt,
      "| feasible (2k <= S <= hi k):", all(e["k"] * e["lo"] <= e["S"] <= e["hi"] * e["k"] for e in ctab.values()), "| NOT REPORTABLE:", [b for b in BOOKS if rt[b] < 4 or live_rt[b] < 4] or "none")
    P(("Spell structure of the rule: SCMO_0003 first state %s, in-spells %s (sum %d), out-spells %s (sum %d); " + B7 + " in %s (sum %d), out %s (sum %d)") % (
        "IN" if rule["SCMO_0003"][0] else "OUT", rin["SCMO_0003"], sum(rin["SCMO_0003"]), rout["SCMO_0003"], sum(rout["SCMO_0003"]),
        rin[B7], sum(rin[B7]), rout[B7], sum(rout[B7])))
    P("Number of allowed N4.10 tuples (count_table.json, exact):")
    P(pd.DataFrame([{"book": b, "window": w, "state": s_, "k": e["k"], "S": e["S"], "bounds": f"[{e['lo']}, {e['hi']}]", "n_ways": f"{e['n_ways']:,}"} for (b, w, s_), e in sorted(ctab.items())]).to_string(index=False))
    P("Cash:", au["books"]["SCMO_0003"].get("cash", "(not recorded in audit.json)"))

    # ── 4.0a the worked example ───────────────────────────────────────────────
    head("4.0a  THE WORKED EXAMPLE (SCMO_0003, 20.8 bps), with one N4.10 draw")
    b = "SCMO_0003"
    d = dec[dec.book == b].sort_values("j").reset_index(drop=True)
    j1 = int(d.index[(d.state != d.state.shift()) & (d.index > 0)][0])
    r = d.loc[j1]
    P(f"One decision: week {j1}, decision date {r.decision_date}. Latest Master rows: Nifty100 {r.sign_Nifty100} ({r.label_Nifty100}), MC100 {r.sign_MC100} ({r.label_MC100}), "
      f"SC100 {r.sign_SC100} ({r.label_SC100}). All three BUY: {r.all_three_buy} -> target {'parent' if r.state else '50% GOLDBEES / 50% cash'}; previous week's state {int(d.loc[j1 - 1, 'state'])}. Trade session: {r.trade_date}.")
    t = tr[(tr.book == b) & (tr.run == "strategy") & (tr.cost_bps == PRIMARY)].reset_index(drop=True)
    tt = t[t.date == r.trade_date].iloc[0]
    P(f"One trade: {tt['kind']} on {tt['date']} at OHLC4: value before {tt.V:.6f}, traded {tt.traded:.6f} (both sides), cost {tt.cost:.6f} = traded x 20.8/2/10,000, NAV at the close after: {tt.nav_close_after:.6f}")
    nv = nav[(nav.book == b) & (nav.cost_bps == PRIMARY) & (nav.run == "strategy")].sort_values("date").reset_index(drop=True)
    k = int(nv.index[nv.date == pd.Timestamp(r.trade_date)][0])
    P("NAV around the trade (strategy, 20.8 bps):")
    table(nv.loc[k - 2:k + 2, ["date", "nav"]].assign(date=lambda x: x.date.dt.date), {"nav": lambda x: f"{x:.6f}"})
    s20 = S(b)
    P(f"One path: start 1.000000 on {nv.date.iloc[0].date()}, end {s20.end_nav:.6f} on {nv.date.iloc[-1].date()}, {int(s20.sessions)} sessions -> years {(s20.sessions - 1) / 252:.4f}, CAGR {100 * s20.cagr:.3f}%, max drawdown {100 * s20.max_dd:.2f}%")
    # one N4.10 draw
    ie, io_ = ctab[(b, "full", "in")], ctab[(b, "full", "out")]
    P(f"One N4.10 draw (draw_id 0; seed numpy default_rng([6, 0]); in-spell lengths first, then out-spell lengths from the same generator):")
    P(f"  sampler: in-spells k = {ie['k']}, total S = {ie['S']} weeks, each length an integer in [{ie['lo']}, {ie['hi']}]; allowed ordered tuples c(k, S) = {ie['n_ways']:,} (DP count in count_table.json; inclusion-exclusion here: {n_ways(ie['k'], ie['S'], ie['lo'], ie['hi']):,})")
    P(f"           out-spells k = {io_['k']}, total S = {io_['S']} weeks, each in [{io_['lo']}, {io_['hi']}]; c(k, S) = {io_['n_ways']:,} (inclusion-exclusion here: {n_ways(io_['k'], io_['S'], io_['lo'], io_['hi']):,})")
    Z10, Z9 = states[f"{b}|full|N4.10"], states[f"{b}|full|N4.9"]
    P(f"  the rule's in-spell lengths: {rin[b]}; draw 0's: {lens(Z10[0], 1)}")
    P(f"  the rule's out-spell lengths: {rout[b]}; draw 0's: {lens(Z10[0], 0)}")
    e0 = pd.DataFrame({"j": np.arange(20), "decision_date": d.decision_date.iloc[:20].values, "rule": rule[b][:20], "N4.9 draw 0": Z9[0, :20], "N4.10 draw 0": Z10[0, :20]})
    P("The first 20 weekly states (1 = parent, 0 = sleeve): the real rule, N4.9 draw 0 (seed default_rng([3, 0])) and N4.10 draw 0:")
    table(e0)
    for typ in NULLS:
        n_ = D(b, typ)
        x0 = n_[n_.draw_id == 0].iloc[0]
        rk = rank(s20.cagr, n_.cagr.values, True)
        extra = f", sessions invested {int(x0.sessions_invested)} (rule {rule_sessions[b]})" if "sessions_invested" in n_ else ""
        P(f"  {typ} draw 0: CAGR {100 * x0.cagr:.3f}%, max drawdown {100 * x0.max_dd:.2f}%, invested weeks {int(x0.invested_weeks)} (rule {int(s20.invested_weeks)}), spells {int(x0.n_in_spells)} in / {int(x0.n_out_spells)} out{extra}")
        P(f"  One ranking against {typ} (CAGR, {rk['draws']} draws): below {rk['worse']}, equal {rk['tied']}, above {rk['better']} -> percentile {rk['percentile']:.2f}, p-value {rk['p']:.5f}; "
          f"null median {100 * n_.cagr.median():.2f}%, edge {100 * (s20.cagr - n_.cagr.median()):+.2f} pp")

    # ── 4.1 headline ─────────────────────────────────────────────────────────
    head(f"4.1  HEADLINE: strategy against N4.10 (deciding) and N4.9 (full window 2019 -> 2026-10-22, LBES cash; {ndraws:,} draws each)")
    rows = []
    for cost in COSTS:
        for b in BOOKS:
            s = S(b, cost=cost)
            row = {"cost": cost, "book": b, "CAGR%": 100 * s.cagr, "maxDD%": 100 * s.max_dd}
            for nm, typ in (("N10", "N4.10"), ("N9", "N4.9")):
                n = D(b, typ, cost)
                rc, rd = rank(s.cagr, n.cagr.values, True), rank(s.max_dd, n.max_dd.values, True)
                row.update({f"{nm}_med%": 100 * n.cagr.median(), f"{nm}_edge_pp": 100 * (s.cagr - n.cagr.median()), f"{nm}_pct": rc["percentile"], f"{nm}_p": rc["p"],
                            f"{nm}_medDD%": 100 * n.max_dd.median(), f"{nm}_DD_pct": rd["percentile"], f"{nm}_DD_p": rd["p"]})
            rows.append(row)
    H = pd.DataFrame(rows)
    f2 = lambda x: f"{x:.2f}"
    P("CAGR (C1): rule's after-cost CAGR, each null's median, the edge over it, the rule's percentile and p-value")
    table(H[["cost", "book", "CAGR%", "N10_med%", "N10_edge_pp", "N10_pct", "N10_p", "N9_med%", "N9_edge_pp", "N9_pct", "N9_p"]],
          {"CAGR%": f2, "N10_med%": f2, "N10_edge_pp": lambda x: f"{x:+.2f}", "N10_pct": f2, "N10_p": lambda x: f"{x:.5f}", "N9_med%": f2, "N9_edge_pp": lambda x: f"{x:+.2f}", "N9_pct": f2, "N9_p": lambda x: f"{x:.5f}"})
    P("Maximum drawdown (C2): rule's worst fall, each null's median, the rule's percentile (shallower is better) and p-value")
    table(H[["cost", "book", "maxDD%", "N10_medDD%", "N10_DD_pct", "N10_DD_p", "N9_medDD%", "N9_DD_pct", "N9_DD_p"]],
          {"maxDD%": f2, "N10_medDD%": f2, "N10_DD_pct": f2, "N10_DD_p": lambda x: f"{x:.5f}", "N9_medDD%": f2, "N9_DD_pct": f2, "N9_DD_p": lambda x: f"{x:.5f}"})
    P("N10 = N4.10 free-length random timing (decides); N9 = N4.9 spell shuffle re-run on this window. pct = percentile of the rule among the draws; DD = maximum drawdown.")
    P("\nSecondary statistics at 20.8 bps, percentile against each null's draws (each statistic's better direction):")
    for typ in NULLS:
        sec = []
        for b in BOOKS:
            s = S(b)
            n = D(b, typ)
            sec.append({"book": b, **{k_: rank(s[k_], n[k_].values, hb)["percentile"] for k_, hb in HIGHER_BETTER.items()}})
        P(f"  against {typ}:")
        table(pd.DataFrame(sec), {k_: (lambda x: f"{x:.1f}") for k_ in HIGHER_BETTER})

    # ── 4.2 comparators ──────────────────────────────────────────────────────
    head("4.2  COMPARATORS (benchmarks, not nulls), same window, T0 = 1.000")
    comp = []
    for cost in COSTS:
        for b in BOOKS:
            row = {"cost": cost, "book": b}
            for kind in ("strategy", "hold_parent", "constant_mix", "sleeve_only"):
                s = S(b, kind, cost)
                row[f"{kind}_CAGR%"], row[f"{kind}_DD%"] = 100 * s.cagr, 100 * s.max_dd
            pn = nav[(nav.book == b) & (nav.run == "published_D17")].sort_values("date").nav.values
            ps = stats_from_nav(pn)
            row["published_CAGR%"], row["published_DD%"] = 100 * ps["cagr"], 100 * ps["max_dd"]
            comp.append(row)
    C = pd.DataFrame(comp)
    table(C, {c: (lambda x: f"{x:.2f}") for c in C.columns if c.endswith("%")})
    f_ = int(rule["SCMO_0003"].sum()) / weeks["SCMO_0003"]
    P(f"Constant mix holds {100 * f_:.1f}% in the parent (the strategy's average); hold_parent is the engine with the decision fixed IN; published_D17 is the published NAV rebased to 1.000 on the same dates.")

    # ── 4.3 power ────────────────────────────────────────────────────────────
    head("4.3  POWER: round trips, the minimum detectable edge (MDE = 2.8 x null SD; 80% power, two-sided 5%) per null, and sessions invested")
    mde = []
    for b in BOOKS:
        row = {"book": b, "round_trips": rt[b]}
        for nm, typ in (("N10", "N4.10"), ("N9", "N4.9")):
            n = D(b, typ)
            row.update({f"{nm}_sd_CAGR_pp": 100 * n.cagr.std(), f"{nm}_MDE_CAGR_pp": 280 * n.cagr.std(), f"{nm}_sd_DD_pp": 100 * n.max_dd.std(), f"{nm}_MDE_DD_pp": 280 * n.max_dd.std()})
        mde.append(row)
    M = pd.DataFrame(mde)
    table(M, {c: (lambda x: f"{x:.2f}") for c in M.columns if c.endswith("_pp")})
    P("T06.md section 3 step 12: the thresholds in section 2 do not depend on these numbers, which did not exist when it was written. T03's N4.9 null SD of CAGR was 5.5 to 6.9 pp (MDE 15 to 19 pp), the prior.")
    P(f"\nSessions invested per draw (headline: full window, LBES, 20.8 bps; of {len(cal['SCMO_0003']) - 1:,} sessions for SCMO_0003; weeks are held exactly, sessions are not):")
    ses_rows = []
    for b in BOOKS:
        row = {"book": b, "rule": rule_sessions[b], "of": len(cal[b]) - 1}
        for nm, typ in (("N9", "N4.9"), ("N10", "N4.10")):
            if "sessions_invested" in dr:
                x = D(b, typ).sessions_invested.values
                row.update({f"{nm}_min": int(x.min()), f"{nm}_median": float(np.median(x)), f"{nm}_max": int(x.max()), f"{nm}_sd": float(x.std(ddof=1)), f"{nm}_equal_to_rule": int((x == rule_sessions[b]).sum())})
        ses_rows.append(row)
    table(pd.DataFrame(ses_rows), {c: (lambda x: f"{x:.1f}") for c in ("N9_median", "N10_median", "N9_sd", "N10_sd")})

    # ── 4.4 verdict ──────────────────────────────────────────────────────────
    head("4.4  VERDICT against the pre-registered criteria (after cost, 20.8 bps; N4.10 decides)")
    hp = H[H.cost == PRIMARY].set_index("book")
    c1n = {nm: int((hp[f"{nm}_pct"] >= PASS_PCT).sum()) for nm in ("N10", "N9")}
    c2n = {nm: int((hp[f"{nm}_DD_pct"] >= PASS_PCT).sum()) for nm in ("N10", "N9")}
    mdeb = M.set_index("book")

    def mdetxt(col):
        return "; ".join(f"{b}: undetectable below {mdeb.loc[b, col]:.1f} pp" for b in BOOKS)

    def lst(nm, col):
        return ", ".join("%s %.1f" % (b[-4:], hp.loc[b, f"{nm}_{col}"]) for b in BOOKS)

    for nm, typ in (("N10", "N4.10 (decides)"), ("N9", "N4.9 (beside, not a criterion)")):
        P(f"Against {typ}:")
        for name, n_, col, mc in (("C1 timing (H1)", c1n[nm], "pct", "N10_MDE_CAGR_pp" if nm == "N10" else "N9_MDE_CAGR_pp"), ("C2 protection (H2)", c2n[nm], "DD_pct", "N10_MDE_DD_pp" if nm == "N10" else "N9_MDE_DD_pp")):
            ok = n_ >= 3
            P(f"  {name:20s} {'PASS' if ok else 'FAIL'}   percentile >= {PASS_PCT:.0f} in >= 3 of 4 books: {n_} of 4 ({lst(nm, col)})   {('MDE: ' + mdetxt(mc)) if not ok else ''}")
    p10 = c1n["N10"] >= 3 and c2n["N10"] >= 3
    p9 = c1n["N9"] >= 3 and c2n["N9"] >= 3
    P("\nOutcome map (T06.md section 2), rows that apply:")
    hits = []
    if p10 and p9:
        hits.append("C1 PASS, C2 PASS, and N4.9 also passes on this window: the result does not depend on the spell lengths. F-AA-S04 stays PROVISIONAL (nothing is unseen) but is better supported")
    if p10 and not p9:
        hits.append("C1 and C2 PASS under N4.10 but N4.9 does not pass both on this window (not a row of the map): the nulls disagree; report both")
    if (c1n["N10"] < 3 or c2n["N10"] < 3) and p9:
        hits.append("C1 or C2 FAIL under N4.10, PASS under N4.9: the edge depends on the rule's particular spell lengths and where they fall")
    if c1n["N10"] < 3 and c2n["N10"] >= 3:
        hits.append("C1 FAIL, C2 PASS (N4.10): protection without timing; judge it on the cost of the insurance (the constant mix shows it)")
    if c1n["N10"] >= 3 and c2n["N10"] < 3:
        hits.append("C1 PASS, C2 FAIL (N4.10): a return edge with no protection; check the comparators")
    if c1n["N10"] < 3 and c2n["N10"] < 3:
        hits.append("C1 FAIL, C2 FAIL (N4.10): no timing edge over chance for these books on this window")
    if not all(gates.values()):
        hits = ["a V gate fails: nothing is read. Fix and rerun as a new run directory"]
    for h_ in hits:
        P("  -", h_)
    P("If N4.9 and N4.10 disagree on this window, both are reported and F-AA-S04's status note says so (T06.md section 2).")

    # ── 4.5 robustness ───────────────────────────────────────────────────────
    head("4.5  ROBUSTNESS (decide a finding's status, not the verdicts)")
    for cost in (0.0, 50.0):
        hc = H[H.cost == cost]
        for nm, typ in (("N10", "N4.10"), ("N9", "N4.9")):
            n1 = int((hc[f"{nm}_pct"] >= PASS_PCT).sum())
            n2 = int((hc[f"{nm}_DD_pct"] >= PASS_PCT).sum())
            P(f"R1 at {cost:g} bps against {typ}: C1 {n1} of 4 -> {'PASS' if n1 >= 3 else 'FAIL'} ({', '.join('%s %.1f' % (bb[-4:], x) for bb, x in zip(hc.book, hc[f'{nm}_pct']))}); "
              f"C2 {n2} of 4 -> {'PASS' if n2 >= 3 else 'FAIL'} ({', '.join('%s %.1f' % (bb[-4:], x) for bb, x in zip(hc.book, hc[f'{nm}_DD_pct']))})")
    for label, win, cash in (("R2 LIQUIDCASE cash (full window, 20.8 bps)", "full", "liquidcase"), ("R3 live window 2021-11-01 -> 2026-10-22 (own spells, same bounds, 20.8 bps)", "live", "lbes")):
        for typ in NULLS:
            pcts, extra = [], []
            for b in BOOKS:
                s = st[(st.book == b) & (st.window == win) & (st.cash == cash) & (st.cost_bps == PRIMARY) & (st.kind == "strategy")]
                n = D(b, typ, win=win, cash=cash)
                if len(s) and len(n):
                    pcts.append(float(rank(s.iloc[0].cagr, n.cagr.values, True)["percentile"]))
                    extra.append(f"{100 * s.iloc[0].cagr:.1f}%")
            n_ = sum(x >= PASS_PCT for x in pcts)
            P(f"{label}, {typ}: C1 percentiles {[round(x, 1) for x in pcts]} (rule's CAGR {extra}) -> {n_} of {len(pcts)} >= {PASS_PCT:.0f} -> {'PASS' if (n_ >= 3) else 'FAIL'}")
    P("\nR4 agreement of the two nulls on this window (20.8 bps; no pass mark). Per book: the rule's percentile under each null, and each null's spread of after-cost CAGR:")
    r4 = []
    for b in BOOKS:
        s = S(b)
        row = {"book": b, "CAGR%": 100 * s.cagr}
        for nm, typ in (("N10", "N4.10"), ("N9", "N4.9")):
            n = D(b, typ)
            q = np.percentile(n.cagr.values, [5, 95])
            row.update({f"{nm}_pct": rank(s.cagr, n.cagr.values, True)["percentile"], f"{nm}_DD_pct": rank(s.max_dd, n.max_dd.values, True)["percentile"], f"{nm}_median%": 100 * n.cagr.median(),
                        f"{nm}_sd_pp": 100 * n.cagr.std(), f"{nm}_p5%": 100 * q[0], f"{nm}_p95%": 100 * q[1]})
        row["pct_gap(N9-N10)"] = row["N9_pct"] - row["N10_pct"]
        row["sd_ratio(N10/N9)"] = row["N10_sd_pp"] / row["N9_sd_pp"]
        r4.append(row)
    R4 = pd.DataFrame(r4)
    table(R4, {c: (lambda x: f"{x:.2f}") for c in R4.columns if c != "book"})
    P("Historical reference (a different window: 2019-01-02 -> 2026-08-21, T03's stored N4.9 draws, 20.8 bps, LBES cash; NOT comparable draw for draw, and no pass mark):")
    if (t03 / "draws.csv").exists() and (t03 / "stats.csv").exists():
        s3, d3 = pd.read_csv(t03 / "stats.csv"), pd.read_csv(t03 / "draws.csv")
        hrow = []
        for b in BOOKS:
            sr = s3[(s3.book == b) & (s3.window == "full") & (s3.cash == "lbes") & (s3.cost_bps == PRIMARY) & (s3.kind == "strategy")].iloc[0]
            nd_ = d3[(d3.book == b) & (d3.window == "full") & (d3.cash == "lbes") & (d3.cost_bps == PRIMARY) & (d3.draw_type == "N4.9")]
            hrow.append({"book": b, "T03_CAGR%": 100 * sr.cagr, "T03_N9_pct": rank(sr.cagr, nd_.cagr.values, True)["percentile"], "T03_N9_DD_pct": rank(sr.max_dd, nd_.max_dd.values, True)["percentile"],
                         "T03_N9_sd_pp": 100 * nd_.cagr.std(), "T06_N9_pct": R4.set_index("book").loc[b, "N9_pct"], "T06_N10_pct": R4.set_index("book").loc[b, "N10_pct"]})
        table(pd.DataFrame(hrow), {c: (lambda x: f"{x:.2f}") for c in ("T03_CAGR%", "T03_N9_pct", "T03_N9_DD_pct", "T03_N9_sd_pp", "T06_N9_pct", "T06_N10_pct")})
    else:
        P("  (T03's draws.csv / stats.csv not found in %s)" % t03)
    P("\nHypotheses: H1 (timing)", "SUPPORTED in-sample against N4.10 (PROVISIONAL: nothing is unseen)" if c1n["N10"] >= 3 else "FALSIFIED against N4.10",
      "| H2 (protection)", "SUPPORTED in-sample against N4.10 (PROVISIONAL)" if c2n["N10"] >= 3 else "FALSIFIED against N4.10")
    P("Gates:", "all pass" if all(gates.values()) else "A GATE FAILED")
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "analysis.log").write_text(out.getvalue(), encoding="utf-8")
    print("wrote", outdir / "analysis.log")
    sys.exit(0 if (all(gates.values()) and v3["draws"] > 0) else 1)


if __name__ == "__main__":
    main()
