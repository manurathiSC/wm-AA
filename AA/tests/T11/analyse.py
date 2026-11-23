"""T11 analysis: reads only the shipped evidence in evidence/<run>/ (and, as a historical reference only, T06's, T08's and T09's) and prints section 4 of the write-up.

    python tests/T11/analyse.py [--run headline]            prints to stdout and writes tests/T11/analysis.log
    python tests/T11/analyse.py --evidence DIR [--out DIR]  point at another evidence directory (e.g. a synthetic one or the engine's smoke run);
                                                            analysis.log then goes to --out (default: DIR itself), never to tests/T11
    options: --books SCMO_0003      for an evidence directory that holds fewer than the four books (the verdict counts then mean nothing)

Forked from tests/T09/analyse.py (which is forked from T08's). Imports nothing from the engine. Percentile = (worse + 0.5 * tied) / draws * 100; p-value = (1 + at least as good) /
(draws + 1); ties are equal within a relative 1e-12 (T11.md section 2). Six criteria, each judged per book at 20.8 bps against its DECIDING null:
  A1 CAGR and A2 maximum drawdown of the rule with the fixed 50/50 sleeve (Part A) against F1 run with the 50/50 sleeve (sleeve_mode fixed50),
  C1 CAGR and C2 maximum drawdown of the rule with the MAUc1-timed sleeve (Part B) against F1 (timed, real gold signal),
  C3 CAGR and C4 maximum drawdown of the timed rule against F3 (gold N4.10-g, real in-or-out switch).
F2 (N4.9) beside F1 and F4 (N4.9-g) beside F3 are printed beside them, F5 (both random) is robustness R5. Holm-adjusted p-values (per book and cost, over the six
criteria, m = 6) are printed beside each. Exits non-zero if a validity gate (V1-V6) failed or if nothing was compared.

The books are the four REAL parents (SCMO_0003, 0007, 0010, 0029) run through their own baskets and stock prices: there is no proxy, no typed weight, no quarterly reset. Basket changes
(18 after T0) are trades of their own and are checked against baskets.csv and trades.csv. The rule starts IN.

Gates V2-V6 are re-derived here from the evidence files themselves (decisions.csv, gold_signal.csv, baskets.csv, draw_states.npz, real_states.npz, draws.csv, count_table.json,
sleeve_trades.csv, trades.csv, positions.csv, daily_nav.csv, parent_nav_*.csv); the engine's JSON files are printed and, where a clear verdict key exists, must agree.
No performance figure is typed in this file: every number printed comes from the evidence.
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
HIGHER_BETTER = {"cagr": True, "max_dd": True, "calmar": True, "vol": False, "ulcer": False, "days_below_10pct": False, "longest_underwater": False}
# criterion, statistic, deciding null, null beside it, sleeve mode of the null's draws, the rule's run (stats.csv kind)
CRIT = [("A1", "cagr", "F1", "F2", "fixed50", "strategy_fixed50"), ("A2", "max_dd", "F1", "F2", "fixed50", "strategy_fixed50"),
        ("C1", "cagr", "F1", "F2", "timed", "strategy"), ("C2", "max_dd", "F1", "F2", "timed", "strategy"),
        ("C3", "cagr", "F3", "F4", "timed", "strategy"), ("C4", "max_dd", "F3", "F4", "timed", "strategy")]
CRIT_NAME = {"A1": "A1 equity timing, fixed 50/50 sleeve (H-A1)", "A2": "A2 protection, fixed sleeve (H-A2)", "C1": "C1 equity timing, timed sleeve (H1)", "C2": "C2 protection, timed sleeve (H2)",
             "C3": "C3 gold timing (H3)", "C4": "C4 gold-timing protection (H4)"}
FAM_DESC = {"F1": "in-or-out N4.10", "F2": "in-or-out N4.9", "F3": "gold N4.10-g, real in-or-out", "F4": "gold N4.9-g, real in-or-out", "F5": "both random (N4.10 and N4.10-g)"}
KINDS = ["strategy", "strategy_fixed50", "hold_parent", "constant_mix", "constant_mix_timed", "sleeve_only", "sleeve_only_timed"]
R7_KINDS = ["strategy_r7_flagged", "strategy_fixed50_r7_flagged", "hold_parent_r7_flagged", "strategy_r7_noexport", "strategy_fixed50_r7_noexport", "hold_parent_r7_noexport"]
STAND_IN_FIELDS = ("d26_sessions_in_window_without_any_d18_bar", "window_sessions_where_a_held_stock_has_no_bar")
PARENT_NAV = "parent_nav_2014-09-01_2019-01-02"
CAPTION = "rebuilt from the parent's baskets and Eikon prices, not validated against a published NAV before 2019-01-02"
T0_EXPECT, END_EXPECT = "2014-09-01", "2019-01-02"
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


def holm(ps) -> list[float]:
    """Holm step-down adjusted p-values (family = the given p-values)."""
    ps = list(map(float, ps))
    m = len(ps)
    order = sorted(range(m), key=lambda i: ps[i])
    adj, run = [0.0] * m, 0.0
    for r, i in enumerate(order):
        run = max(run, min(1.0, (m - r) * ps[i]))
        adj[i] = run
    return adj


def stats_from_nav(nav: np.ndarray) -> dict:
    yrs = (len(nav) - 1) / 252
    dd = nav / np.maximum.accumulate(nav) - 1
    return {"cagr": nav[-1] ** (1 / yrs) - 1, "max_dd": dd.min()}


def flags(obj, key="pass") -> list:
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


def pc(x, d=2):
    return f"{100 * x:.{d}f}%"


def rt_of(a) -> int:
    a = np.asarray(a).astype(int)
    ent = int(((a[1:] == 1) & (a[:-1] == 0)).sum()) + int(a[0] == 1)
    ext = int(((a[1:] == 0) & (a[:-1] == 1)).sum())
    return min(ent, ext)


def gold_with_out(g, s) -> int:
    """number of gold spells that contain at least one OUT week."""
    n_, i = 0, 0
    for v_, ln in runs(g):
        if (np.asarray(s)[i:i + ln] == 0).any():
            n_ += 1
        i += ln
    return n_


def find_p(obj, *path):
    for k in path:
        if not isinstance(obj, dict) or k not in obj:
            return None
        obj = obj[k]
    return obj


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="headline")
    ap.add_argument("--evidence", default=None, help="explicit evidence directory (overrides --run)")
    ap.add_argument("--out", default=None, help="where analysis.log goes (default tests/T11 for --run, the evidence directory for --evidence)")
    ap.add_argument("--t06", default=str(AA / "tests" / "T06" / "evidence" / "headline"), help="T06's evidence (historical reference only)")
    ap.add_argument("--t08", default=str(AA / "tests" / "T08" / "evidence" / "headline"), help="T08's evidence (historical reference only)")
    ap.add_argument("--t09", default=str(AA / "tests" / "T09" / "evidence" / "headline"), help="T09's evidence (historical reference only)")
    ap.add_argument("--doc", default=str(HERE / "T11.md"), help="T11.md, read only, for the pre-registration hash")
    ap.add_argument("--books", default=None, help="comma list; for evidence directories that hold fewer than the four books (the verdict counts then mean nothing)")
    a = ap.parse_args()
    if a.books:
        BOOKS[:] = a.books.split(",")
    B7 = "SCMO_0007" if "SCMO_0007" in BOOKS else BOOKS[-1]
    B0 = BOOKS[0]
    ev = Path(a.evidence) if a.evidence else HERE / "evidence" / a.run
    outdir = Path(a.out) if a.out else (ev if a.evidence else HERE)
    t06, t08, t09 = Path(a.t06), Path(a.t08), Path(a.t09)

    dec = pd.read_csv(ev / "decisions.csv")
    gsig = pd.read_csv(ev / "gold_signal.csv")
    st = pd.read_csv(ev / "stats.csv")
    dr = pd.read_csv(ev / "draws.csv")
    tr = pd.read_csv(ev / "trades.csv")
    sl = pd.read_csv(ev / "sleeve_trades.csv")
    po = pd.read_csv(ev / "positions.csv")
    bsk = pd.read_csv(ev / "baskets.csv")
    r7f = pd.read_csv(ev / "r7_flagged_days.csv")
    r7x = pd.read_csv(ev / "r7_export.csv")
    pnav = pd.read_csv(ev / f"{PARENT_NAV}.csv", parse_dates=["date"])
    pcap = (ev / f"{PARENT_NAV}.md").read_text(encoding="utf-8")
    nav = pd.read_csv(ev / "daily_nav.csv", parse_dates=["date"])
    inp = pd.read_csv(ev / "inputs.csv", dtype=str, keep_default_na=False)
    au = json.loads((ev / "audit.json").read_text(encoding="utf-8"))
    ct = json.loads((ev / "count_table.json").read_text(encoding="utf-8"))
    states = np.load(ev / "draw_states.npz")
    realz = np.load(ev / "real_states.npz")
    vj = ev / "verify_t11.json"
    doc = Path(a.doc).read_text(encoding="utf-8")
    region = doc[doc.index("\n## 1. Idea and references") + 1:doc.index("\n## 4. Results") + 1]
    region = "\n".join(l.rstrip() for l in region.replace("\r\n", "\n").split("\n"))
    sha = hashlib.sha256(region.encode("utf-8")).hexdigest()
    m_sha = re.search(r"§1–§3 sha256:\*\* `([^`]*)`", doc)
    sha_hdr = m_sha.group(1) if m_sha else "?"
    LIQ = "liq" if "liq" in set(st.cash) else "liquidcase"

    # ── the rule and the gold signal, from decisions.csv ──────────────────────
    rule = {b: dec[dec.book == b].sort_values("j").state.values.astype(int) for b in BOOKS}
    gold = {b: dec[dec.book == b].sort_values("j").g.values.astype(int) for b in BOOKS}
    weeks = {b: len(rule[b]) for b in BOOKS}
    rin = {b: lens(rule[b], 1) for b in BOOKS}
    rout = {b: lens(rule[b], 0) for b in BOOKS}
    gbuy = {b: lens(gold[b], 1) for b in BOOKS}
    gsell = {b: lens(gold[b], 0) for b in BOOKS}
    SN = {("io", 1): "in", ("io", 0): "out", ("gold", 1): "buy", ("gold", 0): "sell"}

    def bounds_of(series, kind):
        """per state of a series: lo = min(2, shortest spell of the state), hi = longest spell of the state (T11.md section 2)."""
        return {s_: (min(2, min(lens(series, s_))), max(lens(series, s_))) for s_ in (1, 0)}
    BND = {}
    for b in BOOKS:
        for win in ("full", "r3"):
            if f"{b}|{win}|io" in realz.files:
                for kind in ("io", "gold"):
                    BND[(b, win, kind)] = bounds_of(realz[f"{b}|{win}|{kind}"].astype(int), kind)

    S = lambda b, kind="strategy", cost=PRIMARY, win="full", cash="lbes": st[(st.book == b) & (st.window == win) & (st.cash == cash) & (st.cost_bps == cost) & (st.kind == kind)].iloc[0]
    D = lambda b, fam, cost=PRIMARY, win="full", cash="lbes", mode="timed": dr[(dr.book == b) & (dr.window == win) & (dr.cash == cash) & (dr.cost_bps == cost) & (dr.family == fam) & (dr.sleeve_mode == mode)].sort_values("draw_id")
    ndraws = int(len(D(B0, "F1")))
    cal = {b: nav[(nav.book == b) & (nav.cost_bps == PRIMARY) & (nav.run == "strategy")].sort_values("date").date.values for b in BOOKS}
    wsess = {}
    for b in BOOKS:
        d_ = dec[dec.book == b].sort_values("j").reset_index(drop=True)
        nses = len(cal[b])
        wk0 = [0] + [nses - 1 if pd.isna(t) else int(np.searchsorted(cal[b], np.datetime64(pd.Timestamp(t)))) for t in d_.trade_date.iloc[1:]]
        wsess[b] = np.array(wk0[1:] + [nses - 1]) - np.array(wk0)
    rule_sessions = {b: int(rule[b] @ wsess[b]) for b in BOOKS}
    first_dec, last_dec = dec[dec.book == B0].decision_date.iloc[0], dec[dec.book == B0].decision_date.iloc[-1]
    start_date = str(pd.Timestamp(cal[B0][0]).date())
    end_date = str(pd.Timestamp(cal[B0][-1]).date())
    r3_start = (au["books"][B0].get("r3_window") or {}).get("t0", "2015-01-02")

    P("T11 analysis. Run:", ev.name, "| draws per book, cost and null:", f"{ndraws:,}", "| deciding nulls: F1 (A1, A2 with the 50/50 sleeve; C1, C2 timed) and F3 (C3, C4); F2 and F4 beside them; F5 = robustness R5")
    P("Window: %s -> %s (NAV from %s to %s), %d weekly decisions; R3 window from %s" % (first_dec, last_dec, start_date, end_date, weeks[B0], r3_start))
    P("Pre-registration sha256 in the header:", sha_hdr[:16], "| recomputed now:", sha[:16], "| match:", sha_hdr == sha)
    b_full = {k: BND[(B0, "full", k)] for k in ("io", "gold")}
    P("Bounds (per state, from each series' own spells; full window): in-spells [%d, %d] weeks, out-spells [%d, %d]; BUY [%d, %d], SELL [%d, %d]"
      % (*b_full["io"][1], *b_full["io"][0], *b_full["gold"][1], *b_full["gold"][0]))
    P("Evidence read:", ", ".join(sorted(p.name for p in ev.iterdir())))
    P("Books: the four real parents, each through its own baskets (%d baskets effective from T0 to the end, %d changes after T0) and Eikon stock prices (D18); the rule starts %s."
      % (int((bsk.book == B0).sum()), int(((bsk.book == B0) & (bsk.role == "change")).sum()), "IN" if rule[B0][0] else "OUT"))
    P("POWER NOTE: %d round trips of the in-or-out switch and %d sleeve trades per book (shared by the four books) give LOW POWER; a FAIL will mostly mean 'not distinguishable from chance'. "
      "The minimum detectable edge (2.8 x null SD) is printed beside every FAIL in 4.4." % (rt_of(rule[B0]), int(S(B0).sleeve_trades)))
    P("DATA CAVEATS: the rebuilt parent NAV is %s; the manual Eikon exports (nine stocks) and carried bars are held inside the window; the Muhurat sessions use stand-in bars; "
      "stock-days with a one-day move of 20%% or more were never checked against a second source (R7); NO HOLD-OUT EXISTS and T09's result on the same weeks was seen before the design was frozen." % CAPTION)

    # ── count table ───────────────────────────────────────────────────────────
    ctab = {}
    for key, ent in (ct.get("tables") or {}).items():
        p_ = key.split("|")
        if len(p_) == 4:
            ctab[(p_[0], p_[1], p_[2], p_[3])] = {"k": int(ent.get("spells_k", ent.get("k"))), "S": int(ent.get("weeks_S", ent.get("S"))), "lo": int(ent["lo"]), "hi": int(ent["hi"]), "n_ways": int(ent["n_ways"])}
    want_ct = [(b, w, k_, s_) for b in BOOKS for w in ("full", "r3") for k_, s_ in (("io", "in"), ("io", "out"), ("gold", "buy"), ("gold", "sell"))]
    missing_ct = [k_ for k_ in want_ct if k_ not in ctab]
    if missing_ct:
        P("count_table.json: MISSING entries", missing_ct)

    # ── 4.0b gates ────────────────────────────────────────────────────────────
    head("4.0b  GATES\n" + "(V1 independent check, V2 point in time, V3 the nulls hold their tables, V4 identities and regressions, V5 the samplers are exact, V6 the sleeve, basket and cost identities)")
    gates = GATES
    if vj.exists():
        v = json.loads(vj.read_text(encoding="utf-8"))
        ok = bool(v.get("exit_ok")) and v.get("gate_failures_and_missing", 1) == 0 and v.get("gate_compared", 0) > 0 and bool(v.get("selftest", {}).get("detected"))
        P("V1 independent check (verify_t11.py): ", "PASS" if ok else "FAIL", f"| gate comparisons {v.get('gate_compared', 0):,}, failures and missing {v.get('gate_failures_and_missing')}, "
          f"corrupted copy detected: {v.get('selftest', {}).get('detected')}")
        gates["V1"] = ok
    else:
        P("V1 independent check: NOT RUN (%s missing)" % vj)
        gates["V1"] = False

    # V2: the engine's counts, and the same thing re-derived from decisions.csv, plus the Smallcap 100 rule 7
    viol = cnt = 0
    for b in BOOKS:
        for k, val in au["books"][b].items():
            if k.startswith("v2_") and isinstance(val, (int, float)) and not isinstance(val, bool):
                if k.endswith("_checked"):
                    cnt += val
                else:
                    viol += val
    lab_cols = ["label_Nifty100", "label_MC100", "label_SC100", "label_MAUc1"]
    dd_ = pd.to_datetime(dec.decision_date)
    late = sum(int((pd.to_datetime(dec[c]) > dd_).sum()) for c in lab_cols)
    tdt = pd.to_datetime(dec.trade_date)
    tbad = int((tdt.notna() & (tdt <= dd_)).sum())
    sc_first = str(pd.to_datetime(dec.label_SC100).min().date())
    sc_bad = int((pd.to_datetime(dec.label_SC100) < pd.Timestamp("2011-11-25")).sum())
    restr = inp[inp.usable_from != ""]
    restr_bad = int(sum(pd.Timestamp(r_.usable_from) > pd.Timestamp(first_dec) for r_ in restr.itertuples()))
    v2 = au.get("v2") or {}
    P(f"V2 point in time: engine counts: violations {viol} of {cnt:,} checks; re-derived from decisions.csv: {late} Master labels (three indices and MAUc1) dated after their decision of {len(dec) * 4:,}, "
      f"{tbad} trade dates not after their decision of {int(tdt.notna().sum()):,}; Smallcap 100 signal rows read from {sc_first} (rule 7: not before 2011-11-25), {sc_bad} earlier; "
      f"restricted input files ({len(restr)}: {', '.join(Path(f).name + ' usable from ' + u for f, u in zip(restr.file, restr.usable_from))}) read from {first_dec}: {restr_bad} too early; "
      f"audit.json v2 block: pass {v2.get('pass')}, {v2.get('violations')} violations of {v2.get('checks')}")
    gates["V2"] = viol == 0 and cnt > 0 and late == 0 and tbad == 0 and sc_bad == 0 and restr_bad == 0 and bool(v2.get("pass", False)) and len(restr) > 0

    # V3: every saved draw against the real series, both timings, both windows
    cases = [("io", "N4.9"), ("io", "N4.10"), ("gold", "N4.9-g"), ("gold", "N4.10-g")]
    real_of = lambda b, w, k_: realz[f"{b}|{w}|{k_}"].astype(int)
    v3 = {"keys": 0, "draws": 0, "bad": 0, "rows": 0, "rows_bad": 0, "str_bad": 0, "sess_checked": 0, "sess_bad": 0, "notes": []}
    pos_means, strs, sup_ok = [], {}, {}
    for b in BOOKS:
        for win in ("full", "r3"):
            for kind, typ in cases:
                key = f"{b}|{win}|{kind}|{typ}"
                if key not in states.files or f"{b}|{win}|{kind}" not in realz.files:
                    v3["notes"].append(f"missing {key}")
                    v3["bad"] += 1
                    continue
                A = states[key].astype(np.int8)
                r = real_of(b, win, kind)
                bn = BND[(b, win, kind)]
                v3["keys"] += 1
                nd, nw = A.shape
                ka, kb = len(lens(r, 1)), len(lens(r, 0))
                ta, tb = int(r.sum()), int(len(r) - r.sum())
                ra, rb = sorted(lens(r, 1)), sorted(lens(r, 0))
                if win == "full" and kind == "io" and not (rin[b] == lens(r, 1) and rout[b] == lens(r, 0)):
                    v3["notes"].append(f"real_states {b} io differs from decisions.csv")
                    v3["bad"] += 1
                if win == "full" and kind == "gold" and not (gbuy[b] == lens(r, 1) and gsell[b] == lens(r, 0)):
                    v3["notes"].append(f"real_states {b} gold differs from decisions.csv")
                    v3["bad"] += 1
                sup_ok[(b, win, kind)] = (bn[1][0] <= min(ra) and max(ra) <= bn[1][1] and bn[0][0] <= min(rb) and max(rb) <= bn[0][1])
                s_a, s_b = [], []
                for i in range(nd):
                    row = A[i]
                    la, lb = lens(row, 1), lens(row, 0)
                    bad = (nw != len(r) or int(row[0]) != int(r[0]) or len(la) != ka or len(lb) != kb or sum(la) != ta or sum(lb) != tb)
                    if typ.startswith("N4.9"):
                        bad |= sorted(la) != ra or sorted(lb) != rb
                    else:
                        bad |= (min(la) < bn[1][0] or max(la) > bn[1][1] or min(lb) < bn[0][0] or max(lb) > bn[0][1])
                    v3["draws"] += 1
                    v3["bad"] += int(bad)
                    s_a.append("|".join(map(str, la)))
                    s_b.append("|".join(map(str, lb)))
                strs[key] = (np.array(s_a, dtype=object), np.array(s_b, dtype=object))
                if typ.startswith("N4.10"):
                    li_, lo_l = [lens(A[i], 1) for i in range(nd)], [lens(A[i], 0) for i in range(nd)]
                    if len({len(x_) for x_ in li_}) != 1 or len({len(x_) for x_ in lo_l}) != 1:
                        v3["bad"] += 1
                        v3["notes"].append(f"{key}: the draws do not all have the same number of spells")
                        continue
                    Li = np.array(li_, dtype=float)
                    Lo = np.array(lo_l, dtype=float)
                    for nm, M, k_, S_ in (("a", Li, ka, ta), ("b", Lo, kb, tb)):
                        se = M.std(axis=0, ddof=1) / math.sqrt(nd)
                        z_ = (M.mean(axis=0) - S_ / k_) / np.where(se > 0, se, np.nan)
                        pos_means.append({"set": f"{b}|{win}|{kind}|{nm}", "worst_z": float(np.nanmax(np.abs(z_))) if np.isfinite(z_).any() else 0.0})
                if win == "full" and kind == "io":
                    sess = (A.astype(np.int64) @ wsess[b])
                    fam = "F2" if typ == "N4.9" else "F1"
                    got = D(b, fam).sessions_invested.values
                    if len(got) == nd:
                        v3["sess_checked"] += nd
                        v3["sess_bad"] += int((sess != got).sum())
    # draws.csv rows against the rule, the real gold series and the saved states
    use = {"F1": ("N4.10", None), "F2": ("N4.9", None), "F3": (None, "N4.10-g"), "F4": (None, "N4.9-g"), "F5": ("N4.10", "N4.10-g")}
    for (b, win, cash, cost, fam, mode), g_ in dr.groupby(["book", "window", "cash", "cost_bps", "family", "sleeve_mode"]):
        if b not in BOOKS:
            continue
        v3["rows"] += len(g_)
        ids = g_.draw_id.values
        bad = int((np.sort(ids) != np.arange(len(g_))).any())
        r_io, r_g = real_of(b, win, "io"), real_of(b, win, "gold")
        k_io, k_g = use[fam]
        for (cols, kind, kk, rr_) in ((("in_lengths", "out_lengths"), "io", k_io, r_io), (("g_buy_lengths", "g_sell_lengths"), "gold", k_g, r_g)):
            if kk is None:
                exp_a, exp_b = "|".join(map(str, lens(rr_, 1))), "|".join(map(str, lens(rr_, 0)))
                v3["str_bad"] += int((g_[cols[0]].astype(str) != exp_a).sum() + (g_[cols[1]].astype(str) != exp_b).sum())
            else:
                sa, sb = strs[f"{b}|{win}|{kind}|{kk}"]
                v3["str_bad"] += int((g_[cols[0]].astype(str).values != sa[ids]).sum() + (g_[cols[1]].astype(str).values != sb[ids]).sum())
        bad += int((g_.invested_weeks != int(r_io.sum())).sum() + (g_.g_buy_weeks != int(r_g.sum())).sum())
        bad += int(((g_.n_in_spells != len(lens(r_io, 1))) | (g_.n_out_spells != len(lens(r_io, 0))) | (g_.n_buy_spells != len(lens(r_g, 1))) | (g_.n_sell_spells != len(lens(r_g, 0)))).sum())
        bad += int((g_.sleeve_trades != 0).sum()) if mode == "fixed50" else 0
        v3["rows_bad"] += bad
    P(f"V3 the nulls hold their tables: {v3['draws']:,} saved draws checked over {v3['keys']} state arrays (in-or-out and gold, full and R3 windows; weeks, first state, spell counts, sums, N4.9 sorted lengths, N4.10 per-state bounds), bad {v3['bad']}; "
      f"{v3['rows']:,} draws.csv rows checked (invested weeks, BUY weeks, spell counts, ids, no sleeve trades in fixed50 rows), bad {v3['rows_bad']}; in/out and BUY/SELL length strings against the states: {v3['str_bad']} differ {v3['notes'] or ''}")
    P(f"   sessions_invested recomputed from the states (full window, F1 and F2): {v3['sess_checked']:,} draws, {v3['sess_bad']} differ")
    au_v3 = au.get("v3")
    eng_v3 = flags(au_v3) if au_v3 is not None else []
    if au_v3 is not None:
        P(f"   audit.json v3 block (the engine's own check): {len(eng_v3)} pass flags, all true: {all(eng_v3) and len(eng_v3) > 0}")
    P("   the real series' own lengths lie within the bounds (so every N4.9 draw is an allowed N4.10 configuration):", {f"{k[0][-4:]}/{k[1]}/{k[2]}": ok for k, ok in sup_ok.items() if not ok} or "all within")
    gates["V3"] = (all(eng_v3) if eng_v3 else True) and v3["bad"] == 0 and v3["rows_bad"] == 0 and v3["str_bad"] == 0 and v3["draws"] > 0 and all(sup_ok.values()) and not missing_ct and v3["sess_bad"] == 0

    # V4: identities and regressions (the T06/T08 regression on 2019 is the engine's; the rest is re-derived here from the evidence)
    rj = ev / "regression.json"
    eng_v4, rjd = [False], {}
    if rj.exists():
        rjd = json.loads(rj.read_text(encoding="utf-8"))
        eng_v4 = flags(rjd)
        miss = [k_ for k_ in ("a_d17_regression", "b_one_instrument", "c_shared_code", "d_signals", "e_d24b_vs_d24", "f_seam") if k_ not in rjd]
        a17 = rjd.get("a_d17_regression", {})
        worst_a = max((max(v_.get("worst_rel_diff_by_run", {}).values(), default=float("nan")) for v_ in (a17.get("t08", {}), a17.get("t06", {})) if isinstance(v_, dict)), default=float("nan"))
        rows_a = sum(int(v_.get("rows_compared", 0)) for v_ in (a17.get("t08", {}), a17.get("t06", {})) if isinstance(v_, dict))
        worst_b = max((v_["max_rel_diff"] for v_ in rjd.get("b_one_instrument", {}).values() if isinstance(v_, dict) and "max_rel_diff" in v_), default=float("nan"))
        sig_bad = sum(int(v_.get(k_, 0)) for v_ in rjd.get("d_signals", {}).values() if isinstance(v_, dict) for k_ in ("index_sign", "mauc1_sign", "mauc1_weekly_signal", "mauc1_weekly_label", "index_label"))
        e_cmp = sum(int(v_.get("decisions_compared", 0)) for v_ in rjd.get("e_d24b_vs_d24", {}).values() if isinstance(v_, dict))
        e_bad = sum(int(v_.get("mismatches", 0)) for v_ in rjd.get("e_d24b_vs_d24", {}).values() if isinstance(v_, dict))
        seam = {k_: round(float(v_["year_gap_pp"]), 3) for k_, v_ in rjd.get("f_seam", {}).items() if isinstance(v_, dict) and "year_gap_pp" in v_}
        P(f"V4 identities and regressions. regression.json (the engine's own check): {len(eng_v4)} pass flags, all true: {all(eng_v4) and len(eng_v4) > 0}; keys missing: {miss or 'none'}; "
          f"(a) with D17's dates, 2019-01-02 to 2019-12-31, the engine reproduces the stored daily NAVs of T08 and T06 ({rows_a} book-run-cost rows): worst relative difference {worst_a:.1e}; "
          f"(b) a one-instrument always-in book against the stock's close / first close: worst relative difference {worst_b:.1e}; "
          f"(c) functions shared with t08_engine.py: {len(find_p(rjd, 'c_shared_code', 'identical_required') or [])} required identical, not identical {find_p(rjd, 'c_shared_code', 'required_not_identical')}, "
          f"unexpected changes {find_p(rjd, 'c_shared_code', 'unexpected_changes')}; (d) decision signals against the Master SIGN files and D24b's weekly csv: {sig_bad} mismatches; "
          f"(e) D24b against T08's stored gold signal (D24) on {e_cmp} shared 2019 decision dates: {e_bad} mismatches (partial by design: D24 is not opened by this test); "
          f"(f) seam, hold-the-parent 0-cost NAV against the published D17 NAV over 2019, year gap in pp (limit 0.5): {seam}")
        if miss:
            eng_v4 = eng_v4 + [False]
    else:
        P("V4: regression.json NOT FOUND")
    # re-derived from the evidence files
    v4 = {"nav_start_bad": 0, "runs": 0, "end_bad": 0, "trade_nav_bad": 0, "trade_nav_n": 0, "dec_diff": 0, "pn_bad": 0, "pn_n": 0, "pn_cap": 0, "hold_cost_bad": 0, "cost_mono_bad": 0}
    for (b, c, r_), g_ in nav.groupby(["book", "cost_bps", "run"]):
        if b not in BOOKS:
            continue
        v4["runs"] += 1
        v4["nav_start_bad"] += int(abs(float(g_.sort_values("date").nav.iloc[0]) - 1.0) > 1e-12)
    for b in BOOKS:
        for c in COSTS:
            for k_ in KINDS:
                last = nav[(nav.book == b) & (nav.cost_bps == c) & (nav.run == k_)].sort_values("date").nav.iloc[-1]
                v4["end_bad"] += int(abs(float(last) / float(S(b, k_, c).end_nav) - 1) > 1e-9)
        nv_idx = nav.set_index(["book", "cost_bps", "run", "date"]).nav
        for r_ in tr[(tr.book == b)].itertuples():
            v4["trade_nav_n"] += 1
            v4["trade_nav_bad"] += int(abs(float(nv_idx[(b, r_.cost_bps, r_.run, pd.Timestamp(r_.date))]) / float(r_.nav_close_after) - 1) > 1e-9)
        # the rebuilt parent NAV file is the daily_nav.csv runs, row for row
        pn = pnav[pnav.book == b].sort_values("date").reset_index(drop=True)
        for col, run_, c in (("hold_parent_0bps", "hold_parent", 0.0), ("hold_parent_20.8bps", "hold_parent", PRIMARY), ("part_a_20.8bps", "strategy_fixed50", PRIMARY), ("part_b_20.8bps", "strategy", PRIMARY)):
            ref_ = nav[(nav.book == b) & (nav.cost_bps == c) & (nav.run == run_)].sort_values("date").reset_index(drop=True)
            v4["pn_n"] += len(pn)
            v4["pn_bad"] += int(len(pn) != len(ref_) or (pn.date != ref_.date).any() or (np.abs(pn[col].values / ref_.nav.values - 1) > 1e-12).any() or abs(float(pn[col].iloc[0]) - 1.0) > 1e-12)
        # a cost can only lower the always-in NAV (nothing else differs between the cost levels of hold_parent)
        hp0, hp1, hp2 = (nav[(nav.book == b) & (nav.cost_bps == c) & (nav.run == "hold_parent")].sort_values("date").nav.values for c in COSTS)
        v4["cost_mono_bad"] += int(not (hp0[-1] >= hp1[-1] >= hp2[-1]))
    for b in BOOKS[1:]:
        v4["dec_diff"] += int((rule[b] != rule[B0]).sum() + (gold[b] != gold[B0]).sum())
    v4["pn_cap"] = int(CAPTION in pcap)
    P(f"   re-derived here from the evidence: all {v4['runs']} NAV series start at 1 ({v4['nav_start_bad']} do not); end NAV of every run and cost equals stats.csv ({v4['end_bad']} differ); "
      f"NAV on the date of every recorded trade equals nav_close_after ({v4['trade_nav_n']:,} trades, {v4['trade_nav_bad']} differ); the four books have the same in-or-out and gold decisions ({v4['dec_diff']} differ); "
      f"{PARENT_NAV}.csv equals the hold_parent (0 and 20.8 bps), strategy_fixed50 and strategy runs of daily_nav.csv ({v4['pn_n']:,} values compared, {v4['pn_bad']} series differ); "
      f"its sidecar caption is the pre-registered one: {bool(v4['pn_cap'])}; the always-in end NAV falls as the cost rises: {v4['cost_mono_bad']} books violate it")
    gates["V4"] = (all(eng_v4)) and v4["nav_start_bad"] == 0 and v4["end_bad"] == 0 and v4["trade_nav_bad"] == 0 and v4["trade_nav_n"] > 0 and v4["dec_diff"] == 0 and v4["pn_bad"] == 0 and v4["pn_cap"] == 1 and v4["cost_mono_bad"] == 0

    # V5
    sj = ev / "sampler_selftest.json"
    chi_p, chi_p12, st_ok = None, None, None
    if sj.exists():
        sjd = json.loads(sj.read_text(encoding="utf-8"))
        chi_p = find_p(sjd, "a_small_case", "p")
        chi_p12 = find_p(sjd, "a_small_case", "also_seed_14", "p")
        fl = flags(sjd)
        st_ok = (all(fl) if fl else None)
        P(f"   sampler_selftest.json (the engine's own check): {len(fl)} pass flags, all true: {st_ok}")
    ways_bad = 0
    for (b, w, k_, s_), e in sorted(ctab.items()):
        ways_bad += int(n_ways(e["k"], e["S"], e["lo"], e["hi"]) != e["n_ways"])
        sv_ = {"in": 1, "out": 0, "buy": 1, "sell": 0}[s_]
        lo_exp, hi_exp = BND[(b, w, k_)][sv_]
        ways_bad += int(e["lo"] != lo_exp or e["hi"] != hi_exp or not (e["k"] * e["lo"] <= e["S"] <= e["hi"] * e["k"]))
    worstz = max(m["worst_z"] for m in pos_means) if pos_means else float("inf")
    P(f"V5 the samplers are exact: (a) chi-square on k=3, S=12, bounds [2, 6]: p = {chi_p} with the seed of T06 and T08 and {chi_p12} with a first element 14 (both need > 0.001; from sampler_selftest.json, which this script cannot recompute"
      f"{'; its own pass flag: ' + str(st_ok) if st_ok is not None else ''}); (b) count_table.json against inclusion-exclusion: {len(ctab)} entries (in-or-out and gold, full and R3 windows), {ways_bad} differ or infeasible "
      f"(per-state bounds from each window's own series, feasibility lo k <= S <= hi k); (c) mean length at each spell position over the draws against S/k (F1 and F3 draws): worst |z| = {worstz:.2f} over {len(pos_means)} sets (need < 4)")
    gates["V5"] = (chi_p is not None and float(chi_p) > 0.001 and chi_p12 is not None and float(chi_p12) > 0.001 and (st_ok is None or bool(st_ok))) and ways_bad == 0 and len(ctab) > 0 and worstz < 4

    # V6: the sleeve, basket and cost identities, from sleeve_trades.csv, trades.csv, baskets.csv, positions.csv and decisions.csv
    v6 = {"rows": 0, "ratio_bad": 0, "cost_bad": 0, "cons_bad": 0, "raw_bad": 0, "n_reb": 0, "n_reb_exp": 0, "date_bad": 0, "n_exit": 0, "n_exit_exp": 0, "n_in": 0, "n_in_exp": 0,
          "b_rows": 0, "b_sess_bad": 0, "b_cost_bad": 0, "b_date_bad": 0, "b_eff_bad": 0, "b_n": 0, "b_exp": 0, "b_e_bad": 0, "b_hold_n": 0, "b_hold_exp": 0, "b_pos_bad": 0, "b_pos_n": 0, "tr_cost_bad": 0, "tr_rows": 0, "stand_in_trades": 0}
    stand_in = set()
    for bkx in BOOKS:
        cal_au = (au["books"].get(bkx) or {}).get("calendar") or {}
        stand_in |= set(cal_au.get("d26_sessions_in_window_without_any_d18_bar", []))
        stand_in |= set((au["books"].get(bkx) or {}).get("gold_sessions_without_own_bar", []))
    norange = set((au["books"].get(B0) or {}).get("gold_sessions_without_mcx_range_in_window", []))
    for b in BOOKS:
        e = dec[dec.book == b].sort_values("j").reset_index(drop=True)
        s_, g_ = e.state.values.astype(int), e.g.values.astype(int)
        trad = [j for j in range(1, len(e)) if not pd.isna(e.trade_date[j])]
        exp_reb = [j for j in trad if s_[j - 1] == 0 and s_[j] == 0 and g_[j] != g_[j - 1]]
        exp_exit = [j for j in trad if s_[j - 1] == 1 and s_[j] == 0]
        exp_in = [j for j in trad if s_[j - 1] == 0 and s_[j] == 1]
        bb_ = bsk[bsk.book == b].sort_values("basket_no").reset_index(drop=True)
        cal_idx0 = pd.DatetimeIndex(cal[b])
        sess_exp = [int(cal_idx0.searchsorted(pd.Timestamp(x_))) for x_ in bb_.available_date]
        v6["b_sess_bad"] += int(list(bb_.idx) != sess_exp or [str(cal_idx0[i_].date()) for i_ in sess_exp] != list(bb_.session_date.astype(str)) or bb_.role.iloc[0] != "initial" or (bb_.role.iloc[1:] != "change").any())
        bchg = bb_[bb_.role == "change"]
        bidx = {int(r_.idx): str(r_.available_date) for r_ in bchg.itertuples()}
        cal_b = pd.DatetimeIndex(cal[b])
        for cost in COSTS:
            q = sl[(sl.book == b) & (sl.cost_bps == cost)]
            rb, ex_ = q[q.kind == "sleeve_rebalance"], q[q.kind == "switch_out"]
            tq = tr[(tr.book == b) & (tr.cost_bps == cost) & (tr.run == "strategy")].sort_values("idx")
            v6["rows"] += len(q)
            v6["n_reb"] += len(rb)
            v6["n_reb_exp"] += len(exp_reb)
            v6["n_exit"] += len(ex_)
            v6["n_exit_exp"] += len(exp_exit)
            v6["n_in"] += int((tq.kind == "switch_in").sum())
            v6["n_in_exp"] += len(exp_in)
            v6["date_bad"] += int(sorted(rb.date) != sorted(e.trade_date[exp_reb])) + int(sorted(ex_.date) != sorted(e.trade_date[exp_exit])) + int(sorted(tq[tq.kind == "switch_in"].date) != sorted(e.trade_date[exp_in]))
            tot_a = q.gold_value_after + q.cash_value_after
            v6["ratio_bad"] += int(((q.gold_value_after / tot_a - q.gw_after).abs() > 1e-9).sum())
            v6["cost_bad"] += int(((q.cost - q.traded * q.cost_bps / 2 / 1e4).abs() > 1e-9 * np.maximum(1, q.traded)).sum())
            v6["cons_bad"] += int((((q.gold_value_before + q.cash_value_before - q.cost - tot_a).abs() > 1e-9) & (q.kind == "sleeve_rebalance")).sum())
            v6["raw_bad"] += int((q.gold_fill_raw.astype(bool) != q.date.astype(str).isin(norange)).sum()) if norange or q.gold_fill_raw.astype(bool).any() else 0
            # every trade row of every run at this cost: the cost identity, and no trade on a stand-in session
            ta = tr[(tr.book == b) & (tr.cost_bps == cost)]
            v6["tr_rows"] += len(ta)
            v6["tr_cost_bad"] += int(((ta.cost - ta.traded * cost / 2 / 1e4).abs() > 1e-9 * np.maximum(1, ta.traded)).sum())
            v6["stand_in_trades"] += int(ta.date.astype(str).isin(stand_in).sum())
            # basket changes: the dates are the baskets.csv sessions at which the book holds the parent and no decision trade falls
            dtr = set(int(i_) for i_ in tq[tq.kind.isin(["switch_in", "switch_out", "sleeve_rebalance"])].idx)
            ev_tr = [(int(r_.idx), float(r_.e_after)) for r_ in tq.itertuples() if r_.kind in ("switch_in", "switch_out", "sleeve_rebalance")]
            exp_b = []
            for t_ in sorted(bidx):
                held = float(s_[0])
                for ti, ea in ev_tr:
                    if ti < t_:
                        held = ea
                if held > 0 and t_ not in dtr:
                    exp_b.append(t_)
            bt = tq[tq.kind == "basket_change"]
            v6["b_rows"] += len(bt)
            v6["b_n"] += len(bt)
            v6["b_exp"] += len(exp_b)
            v6["b_date_bad"] += int(sorted(int(i_) for i_ in bt.idx) != sorted(exp_b))
            v6["b_eff_bad"] += int(sum(str(r_.basket_eff) != bidx.get(int(r_.idx), "?") for r_ in bt.itertuples()))
            v6["b_e_bad"] += int((bt.e_after != 1.0).sum())
            v6["b_cost_bad"] += int(((bt.cost - bt.traded * cost / 2 / 1e4).abs() > 1e-9 * np.maximum(1, bt.traded)).sum())
            # hold_parent has every change as a trade of its own
            hp = tr[(tr.book == b) & (tr.cost_bps == cost) & (tr.run == "hold_parent")]
            v6["b_hold_n"] += int((hp.kind == "basket_change").sum())
            v6["b_hold_exp"] += len(bidx)
            v6["b_date_bad"] += int(sorted(int(i_) for i_ in hp.idx) != sorted(bidx))
            # every trade's basket in force is the latest basket whose session is on or before the trade session
            sess = np.array(sorted(list(bidx) + [int(bb_.idx.iloc[0])]))
            for r_ in tq.itertuples():
                k_ = int(sess[sess <= int(r_.idx)].max())
                want = str(bb_[bb_.idx == k_].available_date.iloc[0])
                v6["b_eff_bad"] += int(str(r_.basket_eff) != want)
        # positions: after an entry or a basket change the book holds as many stock lines as the basket lists; after an exit no stock
        pq = po[(po.book == b) & (po.cost_bps == PRIMARY) & (po.run == "strategy")]
        tq = tr[(tr.book == b) & (tr.cost_bps == PRIMARY) & (tr.run == "strategy")]
        nheld = {str(r_.available_date): int(r_.n_held) for r_ in bb_.itertuples()}
        for r_ in tq.itertuples():
            lines = pq[pq.date.astype(str) == str(r_.date)]
            n_stock = int((~lines.instrument.isin(["GOLDBEES", "LBES"])).sum())
            v6["b_pos_n"] += 1
            if r_.kind in ("switch_in", "basket_change"):
                v6["b_pos_bad"] += int(n_stock != nheld.get(str(r_.basket_eff), -1))
            elif r_.kind in ("switch_out", "sleeve_rebalance"):
                v6["b_pos_bad"] += int(n_stock != 0 or not (r_.gw_after > 0) == bool((lines.instrument == "GOLDBEES").any()))
        v6["ratio_bad"] += int((np.abs(e.gw.values - np.where(g_ == 1, 0.8, 0.2)) > 1e-12).sum())
    gsm = 0
    for b in BOOKS:
        gg = gsig[gsig.book == b].sort_values("j")
        gsm += int((gg.g.values != gold[b]).sum() + (gg.decision_date.values != dec[dec.book == b].sort_values("j").decision_date.values).sum())
    eng_v6 = flags(au.get("v6")) if au.get("v6") is not None else []
    P(f"V6 the sleeve, basket and cost identities: {v6['rows']:,} sleeve-trade rows over the three costs; GOLDBEES / (GOLDBEES + cash) after the trade equals the target weight (0.8 or 0.2) and gw equals the signal's: {v6['ratio_bad']} differ; "
      f"cost = traded x cost_bps / 2 / 10,000 on the sleeve rows: {v6['cost_bad']} differ, on all {v6['tr_rows']:,} trade rows of every run: {v6['tr_cost_bad']} differ; a sleeve rebalance conserves value after cost: {v6['cons_bad']} differ; "
      f"sleeve rebalances {v6['n_reb']} against {v6['n_reb_exp']} expected from the decisions (OUT on both sides, signal changed), exits {v6['n_exit']} against {v6['n_exit_exp']}, entries {v6['n_in']} against {v6['n_in_exp']}, "
      f"trade dates differ {v6['date_bad']}; the raw-GOLDBEES-fill flag disagrees with the sessions without an MCX range: {v6['raw_bad']}; gold_signal.csv differs from decisions.csv: {gsm}; trades on a stand-in session "
      f"({', '.join(sorted(stand_in)) or 'none listed'}): {v6['stand_in_trades']}")
    P(f"   basket changes: {v6['b_rows']} basket-change trades of the rule over the three costs against {v6['b_exp']} expected (the baskets.csv sessions after T0 at which the book holds the parent and no decision trade falls); "
      f"dates differ {v6['b_date_bad']} (the rule's and hold_parent's), baskets.csv session and idx differ from the calendar on {v6['b_sess_bad']} books, basket in force (basket_eff) differs from baskets.csv on {v6['b_eff_bad']} trades, stock share after a change not 1: {v6['b_e_bad']}, cost identity {v6['b_cost_bad']} differ; "
      f"hold_parent: {v6['b_hold_n']} basket changes against {v6['b_hold_exp']} expected; positions.csv: stock lines after each entry and basket change equal the basket's n_held, none after an exit or sleeve trade, GOLDBEES present iff its weight is positive: "
      f"{v6['b_pos_bad']} of {v6['b_pos_n']} trades differ (20.8 bps)")
    P(f"   audit.json v6 block (the engine's own check: targets to 1e-12 of NAV, cost identity, continuity at 0 cost, no trade while OUT with the signal constant, weights equal the basket's after an entry and a change): {len(eng_v6)} pass flags, all true: {all(eng_v6) and len(eng_v6) > 0}")
    gates["V6"] = (v6["rows"] > 0 and v6["b_rows"] > 0 and v6["ratio_bad"] == v6["cost_bad"] == v6["cons_bad"] == v6["raw_bad"] == v6["date_bad"] == gsm == v6["tr_cost_bad"] == v6["stand_in_trades"] == 0 and v6["n_reb"] == v6["n_reb_exp"]
                   and v6["n_exit"] == v6["n_exit_exp"] and v6["n_in"] == v6["n_in_exp"] and v6["b_date_bad"] == v6["b_eff_bad"] == v6["b_e_bad"] == v6["b_cost_bad"] == v6["b_pos_bad"] == v6["b_sess_bad"] == 0 and v6["b_n"] == v6["b_exp"]
                   and v6["b_hold_n"] == v6["b_hold_exp"] and (all(eng_v6) if eng_v6 else False))
    P("Gates:", {k: ("PASS" if v else "FAIL") for k, v in gates.items()}, "->", "ALL PASS" if all(gates.values()) else "A GATE FAILED: NOTHING BELOW MAY BE READ")

    # reportability
    rt = {b: rt_of(rule[b]) for b in BOOKS}
    r3_io = {b: real_of(b, "r3", "io") for b in BOOKS}
    r3_g = {b: real_of(b, "r3", "gold") for b in BOOKS}
    r3_rt = {b: rt_of(r3_io[b]) for b in BOOKS}
    gspell = {b: gold_with_out(gold[b], rule[b]) for b in BOOKS}
    gspell_r3 = {b: gold_with_out(r3_g[b], r3_io[b]) for b in BOOKS}
    feas = {w: all(e["k"] * e["lo"] <= e["S"] <= e["hi"] * e["k"] for (b, w_, k_, s_), e in ctab.items() if w_ == w) for w in ("full", "r3")}
    nr_io = [b for b in BOOKS if rt[b] < 4 or not feas["full"]]
    nr_gold = [b for b in BOOKS if gspell[b] < 4]
    nr_io_r3 = [b for b in BOOKS if r3_rt[b] < 4 or not feas["r3"]]
    nr_gold_r3 = [b for b in BOOKS if gspell_r3[b] < 4]
    notrep = lambda cr, win="full": (nr_io if win == "full" else nr_io_r3) + ((nr_gold if win == "full" else nr_gold_r3) if cr in ("C3", "C4") else [])
    P("Reportability: in-or-out round trips per book, full window (need 4):", rt, "| R3 window:", r3_rt, "| gold spells containing an OUT week, full:", gspell, "| R3:", gspell_r3,
      "| tables feasible (lo k <= S <= hi k), full / R3:", feas["full"], "/", feas["r3"], "| NOT REPORTABLE (in-or-out, full):", nr_io or "none", "| (gold, full):", nr_gold or "none",
      "| (R3, in-or-out):", nr_io_r3 or "none", "| (R3, gold):", nr_gold_r3 or "none")
    for b in dict.fromkeys((B0, B7)):
        P(f"Spell structure, {b}: in-or-out first state {'IN' if rule[b][0] else 'OUT'}, in-spells {rin[b]} (sum {sum(rin[b])}), out-spells {rout[b]} (sum {sum(rout[b])}); "
          f"gold first state {'BUY' if gold[b][0] else 'SELL'}, BUY spells {gbuy[b]} (sum {sum(gbuy[b])}), SELL spells {gsell[b]} (sum {sum(gsell[b])})")
    P("Number of allowed tuples (count_table.json, exact):")
    P(pd.DataFrame([{"book": b, "window": w, "timing": k_, "state": s_, "k": e["k"], "S": e["S"], "bounds": f"[{e['lo']}, {e['hi']}]", "n_ways": f"{e['n_ways']:,}"} for (b, w, k_, s_), e in sorted(ctab.items())]).to_string(index=False))
    P("Cash:", au["books"][B0].get("cash", "(not recorded in audit.json)"), "| data:", {k_: v_ for k_, v_ in (au.get("data") or {}).items() if k_ in ("window", "sessions_without_own_gold_bar_(previous close used)", "goldbees")})

    # ── 4.0a the worked example ───────────────────────────────────────────────
    head(f"4.0a  THE WORKED EXAMPLE ({B0}, 20.8 bps): an exit, a gold flip (sleeve rebalance), an entry, a basket change, one F1 draw and one F3 draw")
    b = B0
    d = dec[dec.book == b].sort_values("j").reset_index(drop=True)
    slq = sl[(sl.book == b) & (sl.cost_bps == PRIMARY)].reset_index(drop=True)
    trq = tr[(tr.book == b) & (tr.run == "strategy") & (tr.cost_bps == PRIMARY)].sort_values("idx").reset_index(drop=True)
    poq = po[(po.book == b) & (po.cost_bps == PRIMARY) & (po.run == "strategy")]
    bkq = bsk[bsk.book == b].sort_values("basket_no").reset_index(drop=True)

    def snap(date):
        """units held after the trade of `date` (positions.csv lists only non-zero lines)."""
        x = poq[poq.date.astype(str) == str(date)]
        return {r_.instrument: float(r_.units) for r_ in x.itertuples()}

    def before_after(date):
        i = int(trq.index[trq.date.astype(str) == str(date)][0])
        return (snap(trq.date[i - 1]) if i > 0 else None), snap(date), (str(trq.date[i - 1]) if i > 0 else None)

    def fu(u):
        if u is None:
            return "none (the initial position at T0 is not in positions.csv)"
        stocks = {k_: v_ for k_, v_ in u.items() if k_ not in ("GOLDBEES", "LBES")}
        first3 = ", ".join(f"{k_} {v_:.6f}" for k_, v_ in list(stocks.items())[:3])
        return f"{len(stocks)} stock lines" + (f" (first three: {first3})" if stocks else "") + f", GOLDBEES {u.get('GOLDBEES', 0.0):.8f}, LBES {u.get('LBES', 0.0):.8f}"
    first_i = lambda kind_: next(i_ for i_ in range(len(trq)) if trq.kind[i_] == kind_ and i_ > 0)
    ex_rows_ = {"EXIT": trq.iloc[first_i("switch_out")], "GOLD FLIP": trq.iloc[first_i("sleeve_rebalance")], "ENTRY": trq.iloc[first_i("switch_in")], "BASKET CHANGE": trq.iloc[first_i("basket_change")]}
    for lab, tt in ex_rows_.items():
        ub, ua, pdate = before_after(tt.date)
        if lab == "BASKET CHANGE":
            nb_ = bkq[bkq.available_date.astype(str) == str(tt.basket_eff)].iloc[0]
            lost = sorted(k_ for k_ in (ub or {}) if k_ not in ua and k_ not in ("GOLDBEES", "LBES"))
            gain = sorted(k_ for k_ in ua if k_ not in (ub or {}) and k_ not in ("GOLDBEES", "LBES"))
            kept = [k_ for k_ in ua if k_ in (ub or {}) and k_ not in ("GOLDBEES", "LBES")]
            resized = sum(abs(ua[k_] / ub[k_] - 1) > 1e-9 for k_ in kept) if ub else 0
            P(f"{lab}. While the book holds the parent a basket takes effect on the first session on or after its availableDate. Basket {int(nb_.basket_no)} (availableDate {nb_.available_date}, session {nb_.session_date}, {int(nb_.n_held)} stocks, listed weight sum {nb_.raw_weight_sum}) "
              f"replaces the one in force; on {tt.date} (no decision trade on it) at OHLC4 the old basket is sold and the new one bought: value before {tt.V:.6f}, traded {tt.traded:.6f}, cost {tt.cost:.6f} = traded x 20.8/2/10,000, NAV at the close after: {tt.nav_close_after:.6f}")
            P(f"   Units before ({pdate}): {fu(ub)} | units after: {fu(ua)} | stocks sold out: {lost or 'none'}; stocks newly bought: {gain or 'none'}; stocks kept and resized: {int(resized)} of {len(kept)}")
            continue
        j_ = int(d.index[d.trade_date == tt.date][0])
        r = d.loc[j_]
        P(f"{lab}. One decision: week {j_}, decision date {r.decision_date}. Latest Master rows: Nifty100 {r.sign_Nifty100} ({r.label_Nifty100}), MC100 {r.sign_MC100} ({r.label_MC100}), SC100 {r.sign_SC100} ({r.label_SC100}); "
          f"MAUc1 {r.sign_MAUc1} ({r.label_MAUc1}). All three BUY: {r.all_three_buy} -> target {'the parent basket in force' if r.state else 'sleeve: %.0f%% GOLDBEES / %.0f%% cash (gold signal %s)' % (100 * r.gw, 100 * (1 - r.gw), r.sign_MAUc1)}; "
          f"previous week: state {int(d.loc[j_ - 1, 'state'])}, gold signal {d.loc[j_ - 1, 'sign_MAUc1']}. Trade session: {r.trade_date}.")
        if lab == "ENTRY":
            P(f"   Trade ({tt.kind}) on {tt.date} at OHLC4: value before {tt.V:.6f}, traded {tt.traded:.6f}, cost {tt.cost:.6f} = traded x 20.8/2/10,000; value after cost {tt.V - tt.cost:.6f} split at the basket's listed weights (basket in force: availableDate {tt.basket_eff}); "
              f"NAV at the close after: {tt.nav_close_after:.6f}")
        else:
            q_ = slq[(slq.date.astype(str) == str(tt.date))].iloc[0]
            P(f"   Trade ({q_['kind']}) on {q_['date']} at OHLC4: value before {tt.V:.6f}, traded {q_.traded:.6f}, cost {q_.cost:.6f} = traded x 20.8/2/10,000; GOLDBEES value before {q_.gold_value_before:.6f} -> after {q_.gold_value_after:.6f}, "
              f"cash value before {q_.cash_value_before:.6f} -> after {q_.cash_value_after:.6f}; gold weight after {q_.gw_after:.2f} (check: {q_.gold_value_after / (q_.gold_value_after + q_.cash_value_after):.6f}); NAV at the close after: {tt.nav_close_after:.6f}; "
              f"GOLDBEES filled at the raw OHLC4 (no MCX range that session): {bool(q_.gold_fill_raw)}")
        extra = ""
        if lab == "GOLD FLIP" and ub is not None:
            extra = (f" | implied GOLDBEES fill price before {q_.gold_value_before / ub['GOLDBEES']:.6f}, after {q_.gold_value_after / ua['GOLDBEES']:.6f}; "
                     f"cash level before {q_.cash_value_before / ub['LBES']:.6f}, after {q_.cash_value_after / ua['LBES']:.6f} (the same session, so equal)")
        P(f"   Units before ({pdate or 'T0'}): {fu(ub)} | units after ({tt.date}): {fu(ua)}{extra}")
    nv = nav[(nav.book == b) & (nav.cost_bps == PRIMARY) & (nav.run == "strategy")].sort_values("date").reset_index(drop=True)
    exit_date = ex_rows_["EXIT"].date
    k = int(nv.index[nv.date == pd.Timestamp(exit_date)][0])
    P("NAV around the exit (strategy, 20.8 bps):")
    table(nv.loc[k - 2:k + 2, ["date", "nav"]].assign(date=lambda x: x.date.dt.date), {"nav": lambda x: f"{x:.6f}"})
    s20, s50 = S(b), S(b, "strategy_fixed50")
    P(f"One path: start 1.000000 on {nv.date.iloc[0].date()}, end {s20.end_nav:.6f} on {nv.date.iloc[-1].date()}, {int(s20.sessions)} sessions -> years {(s20.sessions - 1) / 252:.4f}, CAGR {100 * s20.cagr:.3f}%, max drawdown {100 * s20.max_dd:.2f}%; "
      f"{int(s20.trades)} trades of which {int(s20.sleeve_trades)} sleeve rebalances and {int(s20.basket_trades)} basket changes. The rule with the fixed 50/50 sleeve (Part A): end {s50.end_nav:.6f}, CAGR {100 * s50.cagr:.3f}%, "
      f"max drawdown {100 * s50.max_dd:.2f}%, {int(s50.trades)} trades ({int(s50.basket_trades)} basket changes)")
    for kind, state_, pair in (("io", "in", ("F1", "N4.10", "[14, 6, 0]")), ("gold", "buy", ("F3", "N4.10-g", "[14, 11, 6, 0]"))):
        e1, e2 = ctab[(b, "full", kind, state_)], ctab[(b, "full", kind, "out" if kind == "io" else "sell")]
        P(f"One {pair[0]} draw (draw_id 0; seed numpy default_rng({pair[2]}); {state_}-spell lengths first, then the other state's from the same generator):")
        P(f"  sampler: {state_}-spells k = {e1['k']}, total S = {e1['S']} weeks, each an integer in [{e1['lo']}, {e1['hi']}]; allowed ordered tuples c(k, S) = {e1['n_ways']:,} (inclusion-exclusion here: {n_ways(e1['k'], e1['S'], e1['lo'], e1['hi']):,})")
        P(f"           other state k = {e2['k']}, S = {e2['S']}, each in [{e2['lo']}, {e2['hi']}]; c(k, S) = {e2['n_ways']:,} (inclusion-exclusion here: {n_ways(e2['k'], e2['S'], e2['lo'], e2['hi']):,})")
    Z = {k_: states[f"{b}|full|{k_}"] for k_ in ("io|N4.9", "io|N4.10", "gold|N4.9-g", "gold|N4.10-g")}
    P(f"  the rule's in-spell lengths: {rin[b]}; F1 draw 0's: {lens(Z['io|N4.10'][0], 1)}; out-spells {rout[b]}; F1 draw 0's: {lens(Z['io|N4.10'][0], 0)}")
    P(f"  the real gold BUY lengths: {gbuy[b]}; F3 draw 0's: {lens(Z['gold|N4.10-g'][0], 1)}; SELL {gsell[b]}; F3 draw 0's: {lens(Z['gold|N4.10-g'][0], 0)}")
    e0 = pd.DataFrame({"j": np.arange(20), "decision_date": d.decision_date.iloc[:20].values, "real io": rule[b][:20], "F2 draw 0": Z["io|N4.9"][0, :20], "F1 draw 0": Z["io|N4.10"][0, :20],
                       "real gold": gold[b][:20], "F4 draw 0": Z["gold|N4.9-g"][0, :20], "F3 draw 0": Z["gold|N4.10-g"][0, :20]})
    P("The first 20 weekly states (in-or-out: 1 = the parent's basket, 0 = sleeve; gold: 1 = BUY, 0 = SELL): the real series, F2 (N4.9 draw 0, seed [14, 3, 0]), F1 (N4.10 draw 0), F4 (N4.9-g draw 0, seed [14, 11, 3, 0]) and F3 (N4.10-g draw 0):")
    table(e0)
    for fam, mode, rk_kind in (("F1", "fixed50", "strategy_fixed50"), ("F2", "fixed50", "strategy_fixed50"), ("F1", "timed", "strategy"), ("F2", "timed", "strategy"), ("F3", "timed", "strategy"), ("F4", "timed", "strategy")):
        n_ = D(b, fam, mode=mode)
        x0 = n_[n_.draw_id == 0].iloc[0]
        sr = S(b, rk_kind)
        rk = rank(sr.cagr, n_.cagr.values, True)
        lab_m = "50/50 sleeve" if mode == "fixed50" else "timed sleeve"
        P(f"  {fam} ({FAM_DESC[fam]}; {lab_m}) draw 0: CAGR {100 * x0.cagr:.3f}%, max drawdown {100 * x0.max_dd:.2f}%, invested weeks {int(x0.invested_weeks)} (rule {int(sr.invested_weeks)}), BUY weeks {int(x0.g_buy_weeks)} (real {int(gold[b].sum())}), "
          f"spells {int(x0.n_in_spells)} in / {int(x0.n_out_spells)} out, {int(x0.n_buy_spells)} BUY / {int(x0.n_sell_spells)} SELL, sessions invested {int(x0.sessions_invested)} (rule {rule_sessions[b]}), sleeve trades {int(x0.sleeve_trades)} (rule {int(sr.sleeve_trades)})")
        P(f"  One ranking against {fam} ({lab_m}; CAGR, {rk['draws']} draws): below {rk['worse']}, equal {rk['tied']}, above {rk['better']} -> percentile {rk['percentile']:.2f}, p-value {rk['p']:.5f}; "
          f"null median {100 * n_.cagr.median():.2f}%, edge {100 * (sr.cagr - n_.cagr.median()):+.2f} pp")

    # ── 4.1 headline ─────────────────────────────────────────────────────────
    head(f"4.1  HEADLINE: A1, A2, C1 to C4 per book and cost, rule against each null (full window {first_dec} -> {end_date}, LBES cash; {ndraws:,} draws each)")
    H = {}
    for cost in COSTS:
        for b in BOOKS:
            ent = {}
            for cr, stat, dec_f, bes_f, mode, rk_kind in CRIT:
                s = S(b, rk_kind, cost)
                nd_, nb_ = D(b, dec_f, cost, mode=mode), D(b, bes_f, cost, mode=mode)
                rd, rb = rank(s[stat], nd_[stat].values, True), rank(s[stat], nb_[stat].values, True)
                ent[cr] = {"rule": s[stat], "med": nd_[stat].median(), "pct": rd["percentile"], "p": rd["p"], "med_b": nb_[stat].median(), "pct_b": rb["percentile"], "p_b": rb["p"]}
            hp_ = holm([ent[cr]["p"] for cr, *_ in CRIT])
            for (cr, *_), h_ in zip(CRIT, hp_):
                ent[cr]["holm"] = h_
            H[(cost, b)] = ent
    f2 = lambda x: f"{x:.2f}"
    for cr, stat, dec_f, bes_f, mode, rk_kind in CRIT:
        lab_m = "run with the 50/50 sleeve, the rule's sleeve fixed 50/50" if mode == "fixed50" else "the rule's sleeve timed by MAUc1" + (", real gold signal" if dec_f in ("F1", "F2") else "")
        P(f"\n{cr} ({'CAGR' if stat == 'cagr' else 'maximum drawdown, shallower is better'}): {rk_kind} against {dec_f} ({FAM_DESC[dec_f]}, deciding; {lab_m}) and {bes_f} ({FAM_DESC[bes_f]}, beside); Holm = Holm-adjusted p over the six criteria, per book and cost")
        rows = [{"cost": c, "book": b, "rule%": 100 * H[(c, b)][cr]["rule"], f"{dec_f}_med%": 100 * H[(c, b)][cr]["med"],
                 f"{dec_f}_edge_pp": 100 * (H[(c, b)][cr]["rule"] - H[(c, b)][cr]["med"]), f"{dec_f}_pct": H[(c, b)][cr]["pct"], f"{dec_f}_p": H[(c, b)][cr]["p"], f"{dec_f}_Holm_p": H[(c, b)][cr]["holm"],
                 f"{bes_f}_med%": 100 * H[(c, b)][cr]["med_b"], f"{bes_f}_pct": H[(c, b)][cr]["pct_b"], f"{bes_f}_p": H[(c, b)][cr]["p_b"]} for c in COSTS for b in BOOKS]
        table(pd.DataFrame(rows), {k_: (lambda x: f"{x:.5f}") if k_.endswith("_p") else (lambda x: f"{x:+.2f}") if "edge" in k_ else f2 for k_ in rows[0] if k_ not in ("cost", "book")})
    P(f"pct = percentile of the rule among the draws; p = (1 + draws at least as good) / ({ndraws} + 1); Holm = Holm step-down over the six criteria (m = 6) of the same book and cost (unadjusted p decides at the pass mark; Holm is printed beside it).")
    P("\nSecondary statistics at 20.8 bps, percentile against each null's draws (each statistic's better direction):")
    for fam, mode, rk_kind in (("F1", "fixed50", "strategy_fixed50"), ("F2", "fixed50", "strategy_fixed50"), ("F1", "timed", "strategy"), ("F2", "timed", "strategy"), ("F3", "timed", "strategy"), ("F4", "timed", "strategy")):
        sec = []
        for b in BOOKS:
            s = S(b, rk_kind)
            n = D(b, fam, mode=mode)
            sec.append({"book": b, **{k_: rank(s[k_], n[k_].values, hb)["percentile"] for k_, hb in HIGHER_BETTER.items()}})
        P(f"  {rk_kind} against {fam} ({FAM_DESC[fam]}; {'50/50 sleeve' if mode == 'fixed50' else 'timed sleeve'}):")
        table(pd.DataFrame(sec), {k_: (lambda x: f"{x:.1f}") for k_ in HIGHER_BETTER})

    # ── 4.2 comparators ──────────────────────────────────────────────────────
    head("4.2  COMPARATORS (benchmarks, not nulls), same window, T0 = 1.000; every NAV here is REBUILT from the parent's baskets and Eikon prices, not validated against a published NAV before 2019-01-02")
    comp = []
    for cost in COSTS:
        for b in BOOKS:
            row = {"cost": cost, "book": b}
            for kind in KINDS:
                s = S(b, kind, cost)
                row[f"{kind}_CAGR%"], row[f"{kind}_DD%"] = 100 * s.cagr, 100 * s.max_dd
            comp.append(row)
    C = pd.DataFrame(comp)
    P(f"CAGR (%), {start_date} -> {end_date}:")
    table(C[["cost", "book"] + [c for c in C.columns if c.endswith("CAGR%")]], {c: f2 for c in C.columns if c.endswith("%")})
    P(f"Maximum drawdown (%), {start_date} -> {end_date}:")
    table(C[["cost", "book"] + [c for c in C.columns if c.endswith("DD%")]], {c: f2 for c in C.columns if c.endswith("%")})
    P("Trades (sleeve rebalances / basket changes in brackets) and cost paid at 20.8 bps:")
    table(pd.DataFrame([{"book": b, **{f"{k_}": f"{int(S(b, k_).trades)} ({int(S(b, k_).sleeve_trades)}/{int(S(b, k_).basket_trades)}) / {S(b, k_).cost_paid:.5f}" for k_ in KINDS}} for b in BOOKS]))
    f_ = int(rule[B0].sum()) / weeks[B0]
    P(f"The constant mixes hold {100 * f_:.1f}% in the parent's basket (the rule's average share: invested weeks / weeks) all the time; constant_mix has a 50/50 non-stock share, constant_mix_timed splits it by the MAUc1 weight, both rebalanced at each decision's next session "
      f"and at each basket change; sleeve_only holds the sleeve alone (50/50), sleeve_only_timed the sleeve alone split by the MAUc1 weight; strategy_fixed50 is Part A's rule (T06's rule on the real parents); hold_parent is the engine with the decision fixed IN (it follows every basket change). "
      f"There is no published-NAV comparator in this test (the parents' published NAVs start on 2019-01-02).")
    P("\nPer-year returns at 20.8 bps (calendar years; the first and last years are partial: the window runs from the first date to the last):")
    yrows = []
    ser_y = {k_: nav[(nav.book == B0) & (nav.cost_bps == PRIMARY) & (nav.run == k_)].sort_values("date").set_index("date").nav for k_ in ("strategy", "strategy_fixed50", "hold_parent")}
    yrs_ = sorted({d_.year for d_ in ser_y["strategy"].index})
    for y in yrs_:
        row = {"year": y}
        idx_y = ser_y["strategy"].index
        i1 = int(np.flatnonzero(idx_y.year == y).max())
        i0 = int(np.flatnonzero(idx_y.year == y).min())
        row["from"], row["to"] = str(idx_y[i0 - 1].date() if i0 > 0 else idx_y[0].date()), str(idx_y[i1].date())
        for k_, s_ in ser_y.items():
            row[k_ + "%"] = 100 * (float(s_.iloc[i1]) / float(s_.iloc[i0 - 1 if i0 > 0 else 0]) - 1)
        yrows.append(row)
    table(pd.DataFrame(yrows), {c: f2 for c in yrows[0] if c.endswith("%")})
    P(f"  ({B0}; every book has the same signals, so the per-year pattern differs between books only through the baskets and the stock prices)")

    # ── 4.3 power ────────────────────────────────────────────────────────────
    head("4.3  POWER: round trips, the minimum detectable edge (MDE = 2.8 x null SD; 80% power, two-sided 5%) per null, sessions invested and sleeve trades per draw")
    mde = []
    NULLS = [("F1", "timed"), ("F2", "timed"), ("F3", "timed"), ("F4", "timed"), ("F5", "timed"), ("F1", "fixed50"), ("F2", "fixed50")]
    nm_of = lambda f, m: f if m == "timed" else f + "f"
    for b in BOOKS:
        row = {"book": b, "round_trips": rt[b], "gold_spells_with_OUT": gspell[b]}
        for fam, mode in NULLS:
            n = D(b, fam, mode=mode)
            row.update({f"{nm_of(fam, mode)}_sd_CAGR_pp": 100 * n.cagr.std(), f"{nm_of(fam, mode)}_MDE_CAGR_pp": 280 * n.cagr.std(), f"{nm_of(fam, mode)}_sd_DD_pp": 100 * n.max_dd.std(), f"{nm_of(fam, mode)}_MDE_DD_pp": 280 * n.max_dd.std()})
        mde.append(row)
    M = pd.DataFrame(mde)
    table(M, {c: f2 for c in M.columns if c.endswith("_pp")})
    P("(F1f and F2f are the in-or-out nulls run with the sleeve fixed at 50/50, the nulls of A1 and A2.) T11.md section 3 step 12: the thresholds in section 2 do not depend on these numbers, which did not exist when it was written. "
      "T06's N4.10 null SD of CAGR was 5.4 to 6.9 pp (MDE 15 to 19 pp), the prior for A1; for C3 and C4 there is no prior: the gold nulls move only the sleeve's split.")
    P(f"\nSessions invested per draw (full window, LBES, 20.8 bps; of {len(cal[B0]) - 1:,} sessions; weeks are held exactly, sessions are not; F3 and F4 hold the real switch, so sessions equal the rule's; the fixed-50/50 draws use the same states):")
    ses_rows = []
    for b in BOOKS:
        row = {"book": b, "rule": rule_sessions[b], "of": len(cal[b]) - 1}
        for fam in ("F1", "F2", "F3", "F4"):
            x = D(b, fam).sessions_invested.values
            row.update({f"{fam}_min": int(x.min()), f"{fam}_median": float(np.median(x)), f"{fam}_max": int(x.max()), f"{fam}_equal_to_rule": int((x == rule_sessions[b]).sum())})
        ses_rows.append(row)
    table(pd.DataFrame(ses_rows), {c: (lambda x: f"{x:.1f}") for c in ("F1_median", "F2_median", "F3_median", "F4_median")})
    P(f"\nSleeve trades per gold draw (F3 and F4; the rule has {int(S(B0).sleeve_trades)} on {B0}; draws that flip in IN weeks never trade, so the count varies):")
    table(pd.DataFrame([{"book": b, "rule": int(S(b).sleeve_trades), **{f"{fam}_{k_}": v_ for fam in ("F3", "F4") for k_, v_ in (("min", int(D(b, fam).sleeve_trades.min())), ("median", float(D(b, fam).sleeve_trades.median())), ("max", int(D(b, fam).sleeve_trades.max())))}} for b in BOOKS]),
          {c: (lambda x: f"{x:.1f}") for c in ("F3_median", "F4_median")})

    # ── 4.4 verdict ──────────────────────────────────────────────────────────
    head("4.4  VERDICT against the pre-registered criteria (after cost, 20.8 bps; F1 decides A1, A2, C1, C2, F3 decides C3, C4; unadjusted, Holm beside)")
    hp = {b: H[(PRIMARY, b)] for b in BOOKS}
    cnt_ = {}
    for cr, stat, dec_f, bes_f, mode, rk_kind in CRIT:
        nr = notrep(cr)
        cnt_[cr] = int(sum(hp[b][cr]["pct"] >= PASS_PCT and b not in nr for b in BOOKS))
        cnt_[cr + "b"] = int(sum(hp[b][cr]["pct_b"] >= PASS_PCT and b not in nr for b in BOOKS))
    mdeb = M.set_index("book")
    for cr, stat, dec_f, bes_f, mode, rk_kind in CRIT:
        ok = cnt_[cr] >= 3
        lst = lambda key: ", ".join("%s %.1f" % (b[-4:], hp[b][cr][key]) for b in BOOKS)
        mc = f"{nm_of(dec_f, mode)}_MDE_{'CAGR' if stat == 'cagr' else 'DD'}_pp"
        mdetxt = "; ".join(f"{b[-4:]}: undetectable below {mdeb.loc[b, mc]:.1f} pp" for b in BOOKS)
        P(f"  {CRIT_NAME[cr]:46s} {'PASS' if ok else 'FAIL'}   percentile >= {PASS_PCT:.0f} in >= 3 of 4 books against {dec_f}: {cnt_[cr]} of 4 ({lst('pct')}); Holm-adjusted p: {', '.join('%s %.3f' % (b[-4:], hp[b][cr]['holm']) for b in BOOKS)}"
          f"   beside, against {bes_f}: {cnt_[cr + 'b']} of 4 ({lst('pct_b')})   {('MDE: ' + mdetxt) if not ok else ''}" + (f"   NOT REPORTABLE for {notrep(cr)}" if notrep(cr) else ""))
    A = cnt_["A1"] >= 3 and cnt_["A2"] >= 3
    Cc = cnt_["C1"] >= 3 and cnt_["C2"] >= 3
    Gg = cnt_["C3"] >= 3 and cnt_["C4"] >= 3
    A_b, C_b, G_b = cnt_["A1b"] >= 3 and cnt_["A2b"] >= 3, cnt_["C1b"] >= 3 and cnt_["C2b"] >= 3, cnt_["C3b"] >= 3 and cnt_["C4b"] >= 3
    # T09's verdict on the same weeks (proxy; reference only: the stored percentiles of T09's rule against its own F1 and F3 draws, same criteria; no pass mark of its own here)
    t09_cnt = None
    if (t09 / "draws.csv").exists() and (t09 / "stats.csv").exists():
        s9 = pd.read_csv(t09 / "stats.csv")
        d9 = pd.read_csv(t09 / "draws.csv", usecols=["book", "window", "cash", "cost_bps", "family", "sleeve_mode", "cagr", "max_dd"])
        t09_cnt = {}
        for cr, stat, dec_f, bes_f, mode, rk_kind in CRIT:
            n9 = 0
            for b in BOOKS:
                sr9 = s9[(s9.book == b) & (s9.window == "full") & (s9.cash == "lbes") & (s9.cost_bps == PRIMARY) & (s9.kind == rk_kind)]
                nd9 = d9[(d9.book == b) & (d9.window == "full") & (d9.cash == "lbes") & (d9.cost_bps == PRIMARY) & (d9.family == dec_f) & (d9.sleeve_mode == mode)]
                if len(sr9) and len(nd9):
                    n9 += int(rank(float(sr9.iloc[0][stat]), nd9[stat].values, True)["percentile"] >= PASS_PCT)
            t09_cnt[cr] = n9
        P(f"\nT09 on the same weeks (a three-index proxy, 2011-11-25 -> 2019-01-02; stored evidence {t09}; reference only): books at the 90th percentile against F1/F3: " + ", ".join(f"{cr} {t09_cnt[cr]} of {len(BOOKS)}" for cr, *_ in CRIT))
    else:
        P("\nT09 reference: omitted (its evidence files draws.csv and stats.csv were not found); the outcome-map rows that read the result beside T09's cannot be completed")
    t09_A = None if t09_cnt is None else (t09_cnt["A1"] >= 3 and t09_cnt["A2"] >= 3)
    t09_C = None if t09_cnt is None else (t09_cnt["C1"] >= 3 and t09_cnt["C2"] >= 3)
    P("\nOutcome map (T11.md section 2), every row that applies (a pattern can match more than one row; the pre-registered text does not rank them):")
    rows_ = []
    if not all(gates.values()):
        rows_.append("a V gate fails: nothing is read. Fix and rerun as a new run directory")
    else:
        if A and Cc and Gg:
            rows_.append("A1, A2, C1, C2 PASS; C3, C4 PASS: both timings beat chance on this stretch with the real parents. The MAUc1 timing of the sleeve is supported as timing (PROVISIONAL)")
        if A and Cc and not Gg:
            rows_.append("A1, A2, C1, C2 PASS; C3 or C4 FAIL: the equity switch carries the result. The gold timing is not distinguishable from random gold timing on this window; any gain over the 50/50 sleeve shown in R6 is gold exposure or luck, not demonstrated timing skill")
        if A != Cc:
            rows_.append(f"{'A1 or A2 FAIL; C1 and C2 PASS' if Cc else 'C1 or C2 FAIL; A1 and A2 PASS'}: the fixed and timed sleeves disagree on the equity switch: report both, judge on R6 which sleeve drives it")
        if not Cc and Gg:
            rows_.append("C1 or C2 FAIL; C3 and C4 PASS: the gold timing does what random gold timing does not, while the equity switch shows no edge on this stretch")
        if not A and not Cc and not Gg:
            rows_.append("all FAIL: no timing edge over chance on this stretch for the real parents; READ BESIDE T09'S PROXY RESULT (same weeks)" + ("" if t09_cnt is None else (": T09's proxy " + ("also failed all three pairs, so the failure is not due to the proxy" if not (t09_A or t09_C or t09_cnt["C3"] >= 3 and t09_cnt["C4"] >= 3) else "did not fail every pair"))) + ", subject to the power note")
        if t09_cnt is not None and ((A and not t09_A) or (Cc and not t09_C)):
            rows_.append("equity criteria PASS here where T09's proxy failed: the difference between the real parents and the proxy is stock selection, not timing (a statement about this window, PROVISIONAL)")
        if t09_cnt is None and (A or Cc):
            rows_.append("equity criteria PASS here: the row 'where T09's proxy failed' cannot be completed because T09's evidence was not found")
        if not rows_:
            rows_.append("A1 or A2 FAIL, C1 or C2 FAIL, C3 and C4 PASS... (no pre-registered row matches this pattern; report the six verdicts as printed)")
    dis = []
    if A != A_b:
        dis.append("F1 and F2 disagree on A1 and A2 (50/50 sleeve)")
    if Cc != C_b:
        dis.append("F1 and F2 disagree on C1 and C2 (timed sleeve)")
    if Gg != G_b:
        dis.append("F3 and F4 disagree on C3 and C4")
    if any((cnt_[c_] >= 3) != (cnt_[c_ + "b"] >= 3) for c_ in ("A1", "A2", "C1", "C2", "C3", "C4")) and not dis:
        dis.append("a single criterion differs between the deciding and the beside null")
    if dis:
        rows_.append("F1 and F2 (or F3 and F4) disagree: both are reported in the verdict and the finding's status note (" + "; ".join(dis) + ")")
    for r_ in rows_:
        P("  - " + r_)
    P("  - agreement of the paired nulls:", "; ".join(dis) + ": both are reported in the verdict and the finding's status note says so (N6.8)" if dis else "F1 and F2 agree on A1, A2, C1 and C2, F3 and F4 agree on C3 and C4")
    P("A1/A2 replicate T06 and C1/C2 replicate T08 on an earlier stretch; only C3 and C4 bear on the gold timing. T11 alone cannot upgrade F-AA-S04 or F-AA-S07, and any new finding is PROVISIONAL whatever the outcome (the whole window is seen; there is no hold-out).")

    # ── 4.5 robustness ───────────────────────────────────────────────────────
    head("4.5  ROBUSTNESS R1-R7 (decide a finding's status, not the verdicts)")
    for cost in (0.0, 50.0):
        for cr, stat, dec_f, bes_f, mode, rk_kind in CRIT:
            for fam, key in ((dec_f, "pct"), (bes_f, "pct_b")):
                v_ = [H[(cost, b)][cr][key] for b in BOOKS]
                n_ = sum(x >= PASS_PCT for x in v_)
                P(f"R1 at {cost:g} bps, {cr} against {fam}{' (50/50 sleeve)' if mode == 'fixed50' else ''}: {n_} of 4 -> {'PASS' if n_ >= 3 else 'FAIL'} ({', '.join('%s %.1f' % (bb[-4:], x) for bb, x in zip(BOOKS, v_))})")
    P(f"\nR2 LIQUIDCASE as the cash leg (full window, 20.8 bps; A1 against F1 run with the 50/50 sleeve, C1 against F1, C3 against F3):")
    r2_diffs = []
    for lab, cr, fam, mode, rk_kind in (("A1", "A1", "F1", "fixed50", "strategy_fixed50"), ("C1", "C1", "F1", "timed", "strategy"), ("C3", "C3", "F3", "timed", "strategy")):
        pcts, extra = [], []
        for b in BOOKS:
            s = st[(st.book == b) & (st.window == "full") & (st.cash == LIQ) & (st.cost_bps == PRIMARY) & (st.kind == rk_kind)]
            n = D(b, fam, cash=LIQ, mode=mode)
            if len(s) and len(n):
                pcts.append(float(rank(s.iloc[0].cagr, n.cagr.values, True)["percentile"]))
                extra.append(f"{100 * s.iloc[0].cagr:.2f}%")
                nl = D(b, fam, cash="lbes", mode=mode)
                r2_diffs.append((float(abs(s.iloc[0].cagr - S(b, rk_kind).cagr)), float(np.abs(n.cagr.values - nl.cagr.values).max())))
        n_ = sum(x >= PASS_PCT for x in pcts)
        P(f"  {lab} against {fam}{' (50/50 sleeve)' if mode == 'fixed50' else ''}: CAGR percentiles {[round(x, 1) for x in pcts]} (rule's CAGR {extra}) -> {n_} of {len(pcts)} >= {PASS_PCT:.0f} -> {'PASS' if n_ >= 3 else 'FAIL'}")
    P(f"  R2 is a null result by construction: LIQUIDCASE's daily returns equal LBES's in this window to the maximum daily-return difference printed here (audit.json: {(au.get('data') or {}).get('cash', {}).get('lbes_vs_liquidcase_max_abs_daily_return_diff_in_window')}), "
      f"so the cash leg cannot change a number. Largest |CAGR(LIQ) - CAGR(LBES)| over the rule's two runs and over every draw of F1 (both sleeves) and F3 on the same ids: "
      f"{max(x for x, _ in r2_diffs) if r2_diffs else float('nan'):.2e} (rule), {max(y for _, y in r2_diffs) if r2_diffs else float('nan'):.2e} (draws).")
    P(f"\nR3 window {r3_start} -> {end_date} (own spells, totals and nulls, bounds from that window's series, 20.8 bps; A1 against F1 run with the 50/50 sleeve, C1 against F1, C3 against F3):")
    for lab, cr, fam, mode, rk_kind in (("A1", "A1", "F1", "fixed50", "strategy_fixed50"), ("C1", "C1", "F1", "timed", "strategy"), ("C3", "C3", "F3", "timed", "strategy")):
        pcts, extra = [], []
        for b in BOOKS:
            s = st[(st.book == b) & (st.window == "r3") & (st.cash == "lbes") & (st.cost_bps == PRIMARY) & (st.kind == rk_kind)]
            n = D(b, fam, win="r3", mode=mode)
            if len(s) and len(n):
                pcts.append(float(rank(s.iloc[0].cagr, n.cagr.values, True)["percentile"]))
                extra.append(f"{100 * s.iloc[0].cagr:.2f}%")
        n_ = sum(x >= PASS_PCT for x in pcts)
        nrw = notrep(cr, "r3")
        rep = "" if not nrw else f" NOT REPORTABLE for {nrw} (fewer than 4 round trips or gold spells with an OUT week): do not quote"
        P(f"  {lab} against {fam}{' (50/50 sleeve)' if mode == 'fixed50' else ''}: CAGR percentiles {[round(x, 1) for x in pcts]} (rule's CAGR {extra}) -> {n_} of {len(pcts)} >= {PASS_PCT:.0f} -> {'PASS' if (n_ >= 3) else 'FAIL'}{rep}")
    P("\nR4 agreement of the paired nulls (20.8 bps; no pass mark). Per book: the rule's percentile under each null of a pair, and each null's spread of after-cost CAGR:")
    r4 = []
    for b in BOOKS:
        row = {"book": b}
        for fam, mode, rk_kind, tag in (("F1", "fixed50", "strategy_fixed50", "A_F1"), ("F2", "fixed50", "strategy_fixed50", "A_F2"), ("F1", "timed", "strategy", "F1"), ("F2", "timed", "strategy", "F2"), ("F3", "timed", "strategy", "F3"), ("F4", "timed", "strategy", "F4")):
            s = S(b, rk_kind)
            n = D(b, fam, mode=mode)
            q = np.percentile(n.cagr.values, [5, 95])
            row.update({f"{tag}_pct": rank(s.cagr, n.cagr.values, True)["percentile"], f"{tag}_DD_pct": rank(s.max_dd, n.max_dd.values, True)["percentile"], f"{tag}_median%": 100 * n.cagr.median(),
                        f"{tag}_sd_pp": 100 * n.cagr.std(), f"{tag}_p5%": 100 * q[0], f"{tag}_p95%": 100 * q[1]})
        row["gap(A_F2-A_F1)"] = row["A_F2_pct"] - row["A_F1_pct"]
        row["gap(F2-F1)"] = row["F2_pct"] - row["F1_pct"]
        row["gap(F4-F3)"] = row["F4_pct"] - row["F3_pct"]
        r4.append(row)
    R4 = pd.DataFrame(r4)
    P("  (A_F1 and A_F2: the 50/50-sleeve rule against F1 and F2 run with the 50/50 sleeve; F1 to F4: the timed rule against the timed nulls)")
    table(R4, {c: f2 for c in R4.columns if c != "book"})
    P("Historical reference (a different window and real parents; stored percentiles of the rules' own draws; NOT comparable draw for draw, and no pass mark). Omitted below if the evidence files do not exist:")
    ref = {}
    if (t06 / "draws.csv").exists() and (t06 / "stats.csv").exists():
        s6 = pd.read_csv(t06 / "stats.csv")
        d6 = pd.read_csv(t06 / "draws.csv", usecols=["book", "window", "cash", "cost_bps", "draw_type", "cagr", "max_dd"])
        for b in BOOKS:
            sr = s6[(s6.book == b) & (s6.window == "full") & (s6.cash == "lbes") & (s6.cost_bps == PRIMARY) & (s6.kind == "strategy")]
            if sr.empty:
                continue
            sr = sr.iloc[0]
            row = {"book": b, "T06_CAGR%": 100 * sr.cagr}
            for typ, nm in (("N4.10", "N10"), ("N4.9", "N9")):
                nd_ = d6[(d6.book == b) & (d6.window == "full") & (d6.cash == "lbes") & (d6.cost_bps == PRIMARY) & (d6.draw_type == typ)]
                row.update({f"T06_{nm}_pct": rank(sr.cagr, nd_.cagr.values, True)["percentile"], f"T06_{nm}_DD_pct": rank(sr.max_dd, nd_.max_dd.values, True)["percentile"]})
            ref.setdefault("T06", []).append(row)
    if (t08 / "draws.csv").exists() and (t08 / "stats.csv").exists():
        s8 = pd.read_csv(t08 / "stats.csv")
        d8 = pd.read_csv(t08 / "draws.csv", usecols=["book", "window", "cash", "cost_bps", "family", "sleeve_mode", "cagr", "max_dd"])
        for b in BOOKS:
            sr = s8[(s8.book == b) & (s8.window == "full") & (s8.cash == "lbes") & (s8.cost_bps == PRIMARY) & (s8.kind == "strategy")]
            if sr.empty:
                continue
            sr = sr.iloc[0]
            row = {"book": b, "T08_CAGR%": 100 * sr.cagr}
            for fam in ("F1", "F2", "F3", "F4"):
                nd_ = d8[(d8.book == b) & (d8.window == "full") & (d8.cash == "lbes") & (d8.cost_bps == PRIMARY) & (d8.family == fam) & (d8.sleeve_mode == "timed")]
                if len(nd_):
                    row.update({f"T08_{fam}_pct": rank(sr.cagr, nd_.cagr.values, True)["percentile"], f"T08_{fam}_DD_pct": rank(sr.max_dd, nd_.max_dd.values, True)["percentile"]})
            ref.setdefault("T08", []).append(row)
    for nm_, rows_h in ref.items():
        P(f"  {nm_} (stored evidence {'tests/T06/evidence/headline' if nm_ == 'T06' else 'tests/T08/evidence/headline'}; 2019-01-02 -> 2026 on the real parents):")
        table(pd.DataFrame(rows_h), {c: f2 for c in rows_h[0] if c != "book"})
    for nm_ in ("T06", "T08"):
        if nm_ not in ref:
            P(f"  {nm_}: omitted (its evidence files draws.csv and stats.csv were not found)")
    if (t09 / "draws.csv").exists() and (t09 / "stats.csv").exists():
        s9r = pd.read_csv(t09 / "stats.csv")
        d9r = pd.read_csv(t09 / "draws.csv", usecols=["book", "window", "cash", "cost_bps", "family", "sleeve_mode", "cagr", "max_dd"])
        rows9 = []
        for b in BOOKS:
            row = {"book": b}
            for tag, fam, mode, rk_kind in (("A_F1", "F1", "fixed50", "strategy_fixed50"), ("F1", "F1", "timed", "strategy"), ("F2", "F2", "timed", "strategy"), ("F3", "F3", "timed", "strategy"), ("F4", "F4", "timed", "strategy")):
                sr9 = s9r[(s9r.book == b) & (s9r.window == "full") & (s9r.cash == "lbes") & (s9r.cost_bps == PRIMARY) & (s9r.kind == rk_kind)]
                nd9 = d9r[(d9r.book == b) & (d9r.window == "full") & (d9r.cash == "lbes") & (d9r.cost_bps == PRIMARY) & (d9r.family == fam) & (d9r.sleeve_mode == mode)]
                if len(sr9) and len(nd9):
                    row.update({f"T09_{tag}_pct": rank(float(sr9.iloc[0].cagr), nd9.cagr.values, True)["percentile"], f"T09_{tag}_DD_pct": rank(float(sr9.iloc[0].max_dd), nd9.max_dd.values, True)["percentile"]})
                    if tag == "F1":
                        row["T09_timed_rule_CAGR%"] = 100 * float(sr9.iloc[0].cagr)
            rows9.append(row)
        P("  T09 (stored evidence tests/T09/evidence/headline; 2011-11-25 -> 2019-01-02 on a three-index PROXY, the same weekly series from 2014-09-01; the rule's percentile against T09's own draws; A_F1 = the 50/50 rule against F1 with the 50/50 sleeve):")
        table(pd.DataFrame(rows9), {c: f2 for c in rows9[0] if c != "book"})
    else:
        P("  T09: omitted (its evidence files draws.csv and stats.csv were not found)")
    P("\nR5 both timings random (F5: an F1 draw and an F3 draw of the same id; 20.8 bps; reported only):")
    r5 = []
    for b in BOOKS:
        s, n = S(b), D(b, "F5")
        r5.append({"book": b, "CAGR%": 100 * s.cagr, "F5_med%": 100 * n.cagr.median(), "F5_sd_pp": 100 * n.cagr.std(), "CAGR_pct": rank(s.cagr, n.cagr.values, True)["percentile"], "CAGR_p": rank(s.cagr, n.cagr.values, True)["p"],
                   "DD_pct": rank(s.max_dd, n.max_dd.values, True)["percentile"], "DD_p": rank(s.max_dd, n.max_dd.values, True)["p"]})
    table(pd.DataFrame(r5), {c: (lambda x: f"{x:.5f}") if c.endswith("_p") else f2 for c in r5[0] if c != "book"})
    P("\nR6 paired contrast (descriptive, no pass mark): every F1 and F2 draw also run with the sleeve fixed at 50/50; the change from 50/50 to the timed sleeve, in the rule and in the draws (full window, 20.8 bps):")
    r6 = []
    for b in BOOKS:
        sr, sf = S(b), S(b, "strategy_fixed50")
        row = {"book": b, "rule_dCAGR_pp": 100 * (sr.cagr - sf.cagr), "rule_dDD_pp": 100 * (sr.max_dd - sf.max_dd)}
        for fam in ("F1", "F2"):
            t_, f_x = D(b, fam, mode="timed"), D(b, fam, mode="fixed50")
            m = t_.merge(f_x, on="draw_id", suffixes=("_t", "_f"))
            dc, ddn = (m.cagr_t - m.cagr_f).values, (m.max_dd_t - m.max_dd_f).values
            rc, rd = rank(sr.cagr - sf.cagr, dc, True), rank(sr.max_dd - sf.max_dd, ddn, True)
            row.update({f"{fam}_med_dCAGR_pp": 100 * np.median(dc), f"{fam}_dCAGR_pct": rc["percentile"], f"{fam}_share_dCAGR>0": float((dc > 0).mean()),
                        f"{fam}_med_dDD_pp": 100 * np.median(ddn), f"{fam}_dDD_pct": rd["percentile"], f"{fam}_share_dDD>0": float((ddn > 0).mean())})
        r6.append(row)
    table(pd.DataFrame(r6), {c: f2 for c in r6[0] if c != "book"})
    P("  dCAGR = CAGR(timed sleeve) - CAGR(50/50) on the same states; dDD = max drawdown (timed) - max drawdown (50/50), positive = shallower with timing. The percentile ranks the rule's change among the draws' changes (higher = the rule gains more from timing than the draws do).")
    P(f"\nR7 price-quality sensitivity (descriptive, no pass mark; {start_date} -> {end_date}, LBES cash): the rule (Part B), the 50/50 rule (Part A) and hold-the-parent re-run (a) with the return of every listed stock-day set to zero (flagged: a held stock with an absolute one-day close-to-close return "
      f"of 20% or more in D18, listed in r7_flagged_days.csv) and (b) with the return of every held stock-day priced from a manual Eikon export set to zero (noexport):")
    if len(r7f):
        P(f"  flagged stock-days ({len(r7f)}): ")
        table(r7f[["book", "date", "stock", "prev_close", "close", "ret", "w_prev", "w_cur", "src"]], {"ret": lambda x: f"{x:+.4f}", "w_prev": lambda x: f"{x:.4f}", "w_cur": lambda x: f"{x:.4f}"})
    else:
        P("  no stock-day in the window reaches the 20% threshold for the books in this evidence (r7_flagged_days.csv is empty)")
    r7 = []
    for b in BOOKS:
        for cost in (0.0, PRIMARY):
            for base, tag in (("strategy", "B"), ("strategy_fixed50", "A"), ("hold_parent", "H")):
                row = {"book": b, "cost": cost, "run": {"B": "rule, timed (Part B)", "A": "rule, 50/50 (Part A)", "H": "hold the parent"}[tag], "CAGR%": 100 * S(b, base, cost).cagr, "DD%": 100 * S(b, base, cost).max_dd}
                for var, vt in (("flagged", "flag"), ("noexport", "noexp")):
                    k_ = f"{base}_r7_{var}"
                    if ((st.book == b) & (st.kind == k_) & (st.cost_bps == cost)).any():
                        s_k = S(b, k_, cost)
                        row.update({f"{vt}_CAGR%": 100 * s_k.cagr, f"{vt}_dCAGR_pp": 100 * (s_k.cagr - S(b, base, cost).cagr), f"{vt}_DD%": 100 * s_k.max_dd, f"{vt}_dDD_pp": 100 * (s_k.max_dd - S(b, base, cost).max_dd)})
                r7.append(row)
    table(pd.DataFrame(r7), {c: (lambda x: f"{x:+.3f}") if "_d" in c else f2 for c in r7[0] if c not in ("book", "cost", "run")})
    P("  dCAGR / dDD = the re-run's value minus the baseline's, in percentage points (a negative dDD = a deeper worst fall).")
    P("Contribution of the manual-export stocks (r7_export.csv): held stock-sessions priced from an export, and the always-in 0-cost end NAV with and without the returns of every export-priced held stock-day:")
    exr_rows = []
    for b in BOOKS:
        x = r7x[r7x.book == b]
        if not len(x):
            continue
        yrs_b = (len(cal[b]) - 1) / 252
        e1, e0 = float(x.end_nav_hold_parent.iloc[0]), float(x.end_nav_hold_parent_noexport.iloc[0])
        exr_rows.append({"book": b, "export_stocks": ", ".join(f"{r_.stock} {int(r_.held_sessions_export)}" for r_ in x.itertuples()), "held_export_sessions": int(x.held_sessions_export.sum()),
                         "hold_end_nav": e1, "hold_end_nav_noexport": e0, "hold_CAGR%": 100 * (e1 ** (1 / yrs_b) - 1), "noexport_CAGR%": 100 * (e0 ** (1 / yrs_b) - 1), "change_pp": 100 * (e0 ** (1 / yrs_b) - e1 ** (1 / yrs_b))})
    table(pd.DataFrame(exr_rows), {c: (lambda x: f"{x:.4f}") if "nav" in c else (lambda x: f"{x:+.3f}") if c == "change_pp" else f2 for c in exr_rows[0] if c in ("hold_end_nav", "hold_end_nav_noexport", "hold_CAGR%", "noexport_CAGR%", "change_pp")} if exr_rows else None)
    pr_ = sl[(sl.cost_bps == PRIMARY) & (sl.book == B0)]
    P(f"  the rule's {len(pr_)} exits and sleeve rebalances at 20.8 bps ({B0}): {int(pr_.gold_fill_raw.astype(bool).sum())} have a GOLDBEES fill at the raw OHLC4 (no MCX range that session), {int((~pr_.gold_fill_raw.astype(bool)).sum())} at the de-spiked OHLC4.")
    # ── 4.6 the rebuilt parent NAV and the data caveats (descriptive) ─────────
    head(f"4.6  THE REBUILT PARENT NAV AND THE DATA CAVEATS (descriptive; {start_date} -> {end_date})")
    P(f"Caption of {PARENT_NAV}.csv (its sidecar .md, quoted): \"{CAPTION}\"")
    P(f"The file holds, per parent and session ({int((pnav.book == B0).sum())} sessions per book, {pd.Timestamp(pnav.date.min()).date()} -> {pd.Timestamp(pnav.date.max()).date()}, base 1.000 at {start_date}'s close): the hold-the-parent NAV (always IN) at 0 and 20.8 bps and the Part A (50/50 sleeve) and Part B (timed sleeve) NAV at 20.8 bps. "
      f"It is NOT approved data and no other test may read it. Every value equals the corresponding run of daily_nav.csv (gate V4).")
    rows46 = []
    for b in BOOKS:
        q = pnav[pnav.book == b].sort_values("date")
        row = {"book": b, "from": str(q.date.iloc[0].date()), "to": str(q.date.iloc[-1].date())}
        for col, nm in (("hold_parent_0bps", "hold 0bps"), ("hold_parent_20.8bps", "hold 20.8"), ("part_a_20.8bps", "Part A 20.8"), ("part_b_20.8bps", "Part B 20.8")):
            v = q[col].values.astype(float)
            row[f"{nm} end"] = v[-1]
            row[f"{nm} CAGR%"] = 100 * stats_from_nav(v)["cagr"]
            row[f"{nm} DD%"] = 100 * stats_from_nav(v)["max_dd"]
        rows46.append(row)
    table(pd.DataFrame(rows46), {c: (lambda x: f"{x:.4f}") if c.endswith(" end") else f2 for c in rows46[0] if c not in ("book", "from", "to")})
    P("\nData caveats, counted from the evidence (the same counts are in T11.md section 3; this is a check, not a result):")
    cav = []
    for b in BOOKS:
        ab = au["books"].get(b) or {}
        sc = ab.get("src_counts") or {}
        x = r7x[r7x.book == b]
        cav.append({"book": b, "held_export_stock_sessions": int(x.held_sessions_export.sum()) if len(x) else "n/a", "export_stocks": ", ".join(f"{r_.stock} {int(r_.held_sessions_export)}" for r_ in x.itertuples()),
                    "carried_bars": sc.get("carried_bars_in_window_all_stocks", "n/a"), "held_stock_sessions_without_a_bar": (sc.get("held_stock_sessions_by_src") or {}).get("none", "n/a"),
                    "stock_days_|ret|>=20%": int((r7f.book == b).sum())})
    table(pd.DataFrame(cav))
    cal0 = (au["books"].get(B0) or {}).get("calendar") or {}
    P(f"Sessions without any D18 bar in the window ({B0}): {cal0.get('d26_sessions_in_window_without_any_d18_bar', 'n/a')} (the previous close stands in; no trade falls on it: {v6['stand_in_trades']} trades on stand-in sessions); "
      f"sessions with a held stock lacking a bar: {cal0.get('window_sessions_where_a_held_stock_has_no_bar', 'n/a')}; GOLDBEES sessions without an own bar: {(au['books'].get(B0) or {}).get('gold_sessions_without_own_bar', 'n/a')}; "
      f"sessions without an MCX range (raw OHLC4 fill): {(au['books'].get(B0) or {}).get('gold_sessions_without_mcx_range_in_window', 'n/a')}")
    P("\nHypotheses: H-A1 (equity timing, fixed sleeve)", "SUPPORTED in-sample against F1 (PROVISIONAL: the whole window is seen, no hold-out)" if cnt_["A1"] >= 3 else "FALSIFIED against F1",
      "| H-A2 (protection, fixed sleeve)", "SUPPORTED in-sample against F1 (PROVISIONAL)" if cnt_["A2"] >= 3 else "FALSIFIED against F1",
      "| H1 (equity timing, timed sleeve)", "SUPPORTED in-sample against F1 (PROVISIONAL)" if cnt_["C1"] >= 3 else "FALSIFIED against F1",
      "| H2 (protection, timed sleeve)", "SUPPORTED in-sample against F1 (PROVISIONAL)" if cnt_["C2"] >= 3 else "FALSIFIED against F1",
      "| H3 (gold timing)", "SUPPORTED in-sample against F3 (PROVISIONAL)" if cnt_["C3"] >= 3 else "FALSIFIED against F3",
      "| H4 (gold-timing protection)", "SUPPORTED in-sample against F3 (PROVISIONAL)" if cnt_["C4"] >= 3 else "FALSIFIED against F3")
    P("Gates:", "all pass" if all(gates.values()) else "A GATE FAILED")
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "analysis.log").write_text(out.getvalue(), encoding="utf-8")
    print("wrote", outdir / "analysis.log")
    sys.exit(0 if (all(gates.values()) and v3["draws"] > 0) else 1)


if __name__ == "__main__":
    main()
