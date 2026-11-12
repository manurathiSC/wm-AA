"""T08 analysis: reads only the shipped evidence in evidence/<run>/ (and T06's, as a historical reference and for V4) and prints section 4 of the write-up.

    python tests/T08/analyse.py [--run headline]            prints to stdout and writes tests/T08/analysis.log
    python tests/T08/analyse.py --evidence DIR [--out DIR]  point at another evidence directory (e.g. a synthetic one);
                                                            analysis.log then goes to --out (default: DIR itself), never to tests/T08

Imports nothing from the engine. Percentile = (worse + 0.5 * tied) / draws * 100; p-value = (1 + at least as good) / (draws + 1); ties are equal within a
relative 1e-12 (T08.md section 2). Four criteria, each judged per book at 20.8 bps against its DECIDING null: C1 CAGR and C2 maximum drawdown against F1
(in-or-out N4.10, real gold signal), C3 CAGR and C4 maximum drawdown against F3 (gold N4.10-g, real in-or-out switch). F2 (N4.9) and F4 (N4.9-g) are
printed beside them, F5 (both random) is robustness R5. Holm-adjusted p-values (per book and cost, over the four criteria) are printed beside each.
Exits non-zero if a validity gate (V1-V6) failed or if nothing was compared.

Gates V2-V6 are re-derived here from the evidence files themselves (decisions.csv, gold_signal.csv, draw_states.npz, real_states.npz, draws.csv,
count_table.json, sleeve_trades.csv, daily_nav.csv, T06's own evidence); the engine's JSON files are printed and, where a clear verdict key exists, must agree.
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
CRIT = [("C1", "cagr", "F1", "F2"), ("C2", "max_dd", "F1", "F2"), ("C3", "cagr", "F3", "F4"), ("C4", "max_dd", "F3", "F4")]
FAM_DESC = {"F1": "in-or-out N4.10, real gold", "F2": "in-or-out N4.9, real gold", "F3": "gold N4.10-g, real in-or-out", "F4": "gold N4.9-g, real in-or-out", "F5": "both random (N4.10 and N4.10-g)"}
KINDS = ["strategy", "strategy_fixed50", "hold_parent", "constant_mix", "constant_mix_timed", "sleeve_only", "sleeve_only_timed"]
LIVE_START = "2021-11-01"
V4_NAV_END = pd.Timestamp("2026-10-22")
MCX_LAST = pd.Timestamp("2026-09-28")
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


def find_key(obj, names):
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="headline")
    ap.add_argument("--evidence", default=None, help="explicit evidence directory (overrides --run)")
    ap.add_argument("--out", default=None, help="where analysis.log goes (default tests/T08 for --run, the evidence directory for --evidence)")
    ap.add_argument("--t06", default=str(AA / "tests" / "T06" / "evidence" / "headline"), help="T06's evidence (historical reference and V4)")
    ap.add_argument("--doc", default=str(HERE / "T08.md"), help="T08.md, read only, for the pre-registration hash")
    ap.add_argument("--books", default=None, help="comma list; for engine smoke runs that hold fewer than the four books (the verdict counts then mean nothing)")
    a = ap.parse_args()
    if a.books:
        BOOKS[:] = a.books.split(",")
    B7 = "SCMO_0007" if "SCMO_0007" in BOOKS else BOOKS[-1]
    ev = Path(a.evidence) if a.evidence else HERE / "evidence" / a.run
    outdir = Path(a.out) if a.out else (ev if a.evidence else HERE)
    t06 = Path(a.t06)

    dec = pd.read_csv(ev / "decisions.csv")
    gsig = pd.read_csv(ev / "gold_signal.csv")
    st = pd.read_csv(ev / "stats.csv")
    dr = pd.read_csv(ev / "draws.csv")
    tr = pd.read_csv(ev / "trades.csv")
    sl = pd.read_csv(ev / "sleeve_trades.csv")
    pos = pd.read_csv(ev / "positions.csv")
    nav = pd.read_csv(ev / "daily_nav.csv", parse_dates=["date"])
    g4 = pd.read_csv(ev / "g_engine.csv")
    au = json.loads((ev / "audit.json").read_text(encoding="utf-8"))
    ct = json.loads((ev / "count_table.json").read_text(encoding="utf-8"))
    states = np.load(ev / "draw_states.npz")
    realz = np.load(ev / "real_states.npz")
    vj = ev / "verify_t08.json"
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
    HI = {("io", 1): max(max(rin[b]) for b in BOOKS), ("io", 0): max(max(rout[b]) for b in BOOKS), ("gold", 1): max(max(gbuy[b]) for b in BOOKS), ("gold", 0): max(max(gsell[b]) for b in BOOKS)}
    LO = min(2, min(min(rin[b] + rout[b] + gbuy[b] + gsell[b]) for b in BOOKS))
    SN = {("io", 1): "in", ("io", 0): "out", ("gold", 1): "buy", ("gold", 0): "sell"}

    S = lambda b, kind="strategy", cost=PRIMARY, win="full", cash="lbes": st[(st.book == b) & (st.window == win) & (st.cash == cash) & (st.cost_bps == cost) & (st.kind == kind)].iloc[0]
    D = lambda b, fam, cost=PRIMARY, win="full", cash="lbes", mode="timed": dr[(dr.book == b) & (dr.window == win) & (dr.cash == cash) & (dr.cost_bps == cost) & (dr.family == fam) & (dr.sleeve_mode == mode)].sort_values("draw_id")
    ndraws = int(len(D("SCMO_0003", "F1")))
    cal = {b: nav[(nav.book == b) & (nav.cost_bps == PRIMARY) & (nav.run == "strategy")].sort_values("date").date.values for b in BOOKS}
    wsess = {}
    for b in BOOKS:
        d_ = dec[dec.book == b].sort_values("j").reset_index(drop=True)
        nses = len(cal[b])
        wk0 = [0] + [nses - 1 if pd.isna(t) else int(np.searchsorted(cal[b], np.datetime64(pd.Timestamp(t)))) for t in d_.trade_date.iloc[1:]]
        wsess[b] = np.array(wk0[1:] + [nses - 1]) - np.array(wk0)
    rule_sessions = {b: int(rule[b] @ wsess[b]) for b in BOOKS}
    first_dec, last_dec = dec[dec.book == "SCMO_0003"].decision_date.iloc[0], dec[dec.book == "SCMO_0003"].decision_date.iloc[-1]
    end_date = str(pd.Timestamp(cal["SCMO_0003"][-1]).date())

    P("T08 analysis. Run:", ev.name, "| draws per book, cost and null:", f"{ndraws:,}", "| deciding nulls: F1 (C1, C2) and F3 (C3, C4); F2 and F4 beside them; F5 = robustness R5")
    P("Window: %s -> %s (SCMO_0007 from %s), %d weekly decisions (SCMO_0007 %d); live window from %s" % (
        first_dec, last_dec, dec[dec.book == B7].decision_date.iloc[0], weeks["SCMO_0003"], weeks[B7], LIVE_START))
    P("Pre-registration sha256 in the header:", sha_hdr[:16], "| recomputed now:", sha[:16], "| match:", sha_hdr == sha)
    P("Bounds: in-or-out lengths in [%d, %d] weeks (in-spells) and [%d, %d] (out-spells); gold lengths in [%d, %d] (BUY) and [%d, %d] (SELL); all from the rule's own and the real gold series' spells on the full window"
      % (LO, HI[("io", 1)], LO, HI[("io", 0)], LO, HI[("gold", 1)], LO, HI[("gold", 0)]))
    P("Evidence read:", ", ".join(sorted(p.name for p in ev.iterdir())))

    # ── count table ───────────────────────────────────────────────────────────
    ctab = {}
    for key, ent in (ct.get("tables") or {}).items():
        p_ = key.split("|")
        if len(p_) == 4:
            ctab[(p_[0], p_[1], p_[2], p_[3])] = {"k": int(ent.get("spells_k", ent.get("k"))), "S": int(ent.get("weeks_S", ent.get("S"))), "lo": int(ent["lo"]), "hi": int(ent["hi"]), "n_ways": int(ent["n_ways"])}
    want_ct = [(b, w, k_, s_) for b in BOOKS for w in ("full", "live") for k_, s_ in (("io", "in"), ("io", "out"), ("gold", "buy"), ("gold", "sell"))]
    missing_ct = [k_ for k_ in want_ct if k_ not in ctab]
    if missing_ct:
        P("count_table.json: MISSING entries", missing_ct)

    # ── 4.0b gates ────────────────────────────────────────────────────────────
    head("4.0b  GATES\n" + "(V1 independent check, V2 point in time, V3 the nulls hold their tables, V4 regression to T06 and always-in, V5 the samplers are exact, V6 the sleeve identity)")
    gates = GATES
    if vj.exists():
        v = json.loads(vj.read_text(encoding="utf-8"))
        ok = bool(v.get("exit_ok")) and v.get("gate_failures_and_missing", 1) == 0 and v.get("gate_compared", 0) > 0 and bool(v.get("selftest", {}).get("detected"))
        P("V1 independent check (verify_t08.py): ", "PASS" if ok else "FAIL", f"| gate comparisons {v.get('gate_compared', 0):,}, failures and missing {v.get('gate_failures_and_missing')}, "
          f"corrupted copy detected: {v.get('selftest', {}).get('detected')}")
        gates["V1"] = ok
    else:
        P("V1 independent check: NOT RUN (%s missing)" % vj)
        gates["V1"] = False

    # V2: the engine's counts, and the same thing re-derived from decisions.csv
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
    P(f"V2 point in time: engine counts: violations {viol} of {cnt:,} checks; re-derived from decisions.csv: {late} Master labels (three indices and MAUc1) dated after their decision of {len(dec) * 4:,}, "
      f"{tbad} trade dates not after their decision of {int(tdt.notna().sum()):,}")
    gates["V2"] = viol == 0 and cnt > 0 and late == 0 and tbad == 0

    # V3: every saved draw against the real series, both timings
    cases = [("io", "N4.9"), ("io", "N4.10"), ("gold", "N4.9-g"), ("gold", "N4.10-g")]
    real_of = lambda b, w, k_: realz[f"{b}|{w}|{k_}"].astype(int)
    v3 = {"keys": 0, "draws": 0, "bad": 0, "rows": 0, "rows_bad": 0, "str_bad": 0, "sess_checked": 0, "sess_bad": 0, "notes": []}
    pos_means, strs = [], {}
    sup_ok = {}
    for b in BOOKS:
        for win in ("full", "live"):
            for kind, typ in cases:
                key = f"{b}|{win}|{kind}|{typ}"
                if key not in states.files or f"{b}|{win}|{kind}" not in realz.files:
                    v3["notes"].append(f"missing {key}")
                    v3["bad"] += 1
                    continue
                A = states[key].astype(np.int8)
                r = real_of(b, win, kind)
                v3["keys"] += 1
                nd, nw = A.shape
                ka, kb = len(lens(r, 1)), len(lens(r, 0))
                ta, tb = int(r.sum()), int(len(r) - r.sum())
                ra, rb = sorted(lens(r, 1)), sorted(lens(r, 0))
                if win == "full" and kind == "io":
                    chk_ = (rin[b] == lens(r, 1) and rout[b] == lens(r, 0))
                    if not chk_:
                        v3["notes"].append(f"real_states {b} io differs from decisions.csv")
                        v3["bad"] += 1
                if win == "full" and kind == "gold" and not (gbuy[b] == lens(r, 1) and gsell[b] == lens(r, 0)):
                    v3["notes"].append(f"real_states {b} gold differs from decisions.csv")
                    v3["bad"] += 1
                sup_ok[(b, win, kind)] = (min(ra + rb) >= LO and max(ra) <= HI[(kind, 1)] and max(rb) <= HI[(kind, 0)])
                s_a, s_b = ([], [])
                for i in range(nd):
                    row = A[i]
                    la, lb = lens(row, 1), lens(row, 0)
                    bad = (nw != len(r) or int(row[0]) != int(r[0]) or len(la) != ka or len(lb) != kb or sum(la) != ta or sum(lb) != tb)
                    if typ.startswith("N4.9"):
                        bad |= sorted(la) != ra or sorted(lb) != rb
                    else:
                        bad |= (min(la) < LO or max(la) > HI[(kind, 1)] or min(lb) < LO or max(lb) > HI[(kind, 0)])
                    v3["draws"] += 1
                    v3["bad"] += int(bad)
                    s_a.append("|".join(map(str, la)))
                    s_b.append("|".join(map(str, lb)))
                strs[key] = (np.array(s_a, dtype=object), np.array(s_b, dtype=object))
                if typ.startswith("N4.10"):
                    Li = np.array([lens(A[i], 1) for i in range(nd)], dtype=float)
                    Lo = np.array([lens(A[i], 0) for i in range(nd)], dtype=float)
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
        sw = "full" if cash == LIQ else win
        ids = g_.draw_id.values
        bad = int((np.sort(ids) != np.arange(len(g_))).any())
        r_io, r_g = real_of(b, sw, "io"), real_of(b, sw, "gold")
        k_io, k_g = use[fam]
        for (cols, kind, kk, rr_) in ((("in_lengths", "out_lengths"), "io", k_io, r_io), (("g_buy_lengths", "g_sell_lengths"), "gold", k_g, r_g)):
            if kk is None:
                exp_a, exp_b = "|".join(map(str, lens(rr_, 1))), "|".join(map(str, lens(rr_, 0)))
                v3["str_bad"] += int((g_[cols[0]].astype(str) != exp_a).sum() + (g_[cols[1]].astype(str) != exp_b).sum())
            else:
                sa, sb = strs[f"{b}|{sw}|{kind}|{kk}"]
                v3["str_bad"] += int((g_[cols[0]].astype(str).values != sa[ids]).sum() + (g_[cols[1]].astype(str).values != sb[ids]).sum())
        bad += int(((g_.invested_weeks != int(r_io.sum())) & (k_io is None)).sum() + ((g_.g_buy_weeks != int(r_g.sum())) & (k_g is None)).sum())
        bad += int(((g_.invested_weeks != int(r_io.sum())) & (k_io is not None)).sum() + ((g_.g_buy_weeks != int(r_g.sum())) & (k_g is not None)).sum())
        bad += int(((g_.n_in_spells != len(lens(r_io, 1))) | (g_.n_out_spells != len(lens(r_io, 0))) | (g_.n_buy_spells != len(lens(r_g, 1))) | (g_.n_sell_spells != len(lens(r_g, 0)))).sum())
        v3["rows_bad"] += bad
    P(f"V3 the nulls hold their tables: {v3['draws']:,} saved draws checked over {v3['keys']} state arrays (in-or-out and gold; weeks, first state, spell counts, sums, N4.9 sorted lengths, N4.10 bounds), bad {v3['bad']}; "
      f"{v3['rows']:,} draws.csv rows checked (invested weeks, BUY weeks, spell counts, ids), bad {v3['rows_bad']}; in/out and BUY/SELL length strings against the states: {v3['str_bad']} differ {v3['notes'] or ''}")
    P(f"   sessions_invested recomputed from the states (full window, F1 and F2): {v3['sess_checked']:,} draws, {v3['sess_bad']} differ (a difference means the definition here and the engine's differ; the verifier owns the exact definition)")
    au_v3 = au.get("v3")
    eng_v3 = flags(au_v3) if au_v3 is not None else []
    if au_v3 is not None:
        P(f"   audit.json v3 block (the engine's own check): {len(eng_v3)} pass flags, all true: {all(eng_v3) and len(eng_v3) > 0}")
    P("   the real series' own lengths lie within the bounds (so every N4.9 draw is an allowed N4.10 configuration):", {f"{k[0][-4:]}/{k[1]}/{k[2]}": ok for k, ok in sup_ok.items() if not ok} or "all within")
    gates["V3"] = (all(eng_v3) if eng_v3 else True) and v3["bad"] == 0 and v3["rows_bad"] == 0 and v3["str_bad"] == 0 and v3["draws"] > 0 and all(sup_ok.values()) and not missing_ct and v3["sess_bad"] == 0

    # V4
    P("V4 always-in at 0 cost vs the published NAV (G0: +-0.25 pp/yr overall, +-0.5 pp every calendar year):")
    table(g4, {"cagr_gap_pp_yr": lambda x: f"{x:+.3f}", "worst_year_gap_pp": lambda x: f"{x:+.3f}"})
    if "window_first" in g4:
        P("   (the always-in book runs over %s -> %s, the whole window)" % (g4.window_first.iloc[0], g4.window_last.iloc[0]))
    g0_ok = bool((g4["overall"] == "PASS").all() and (g4["yearly"] == "PASS").all() and len(g4) >= len(BOOKS))
    reg = {"dec_compared": 0, "dec_bad": 0, "dec_shifted": 0, "nav_compared": 0, "nav_bad": 0, "worst": 0.0, "ok": False}
    if (t06 / "decisions.csv").exists() and (t06 / "daily_nav.csv").exists():
        d6 = pd.read_csv(t06 / "decisions.csv")
        d6 = d6[d6.book.isin(BOOKS)]
        for b in BOOKS:
            e8 = dec[dec.book == b].set_index("decision_date").state
            for r_ in d6[d6.book == b].itertuples():
                dt = r_.decision_date
                if dt not in e8.index:  # T06's last decision date (a Thursday, the last row of the old calendar) is read against the Friday of its ISO week
                    iso = pd.Timestamp(dt).isocalendar()
                    cand = [x for x in e8.index if pd.Timestamp(x).isocalendar()[:2] == iso[:2]]
                    reg["dec_shifted"] += 1
                    dt = cand[0] if cand else None
                reg["dec_compared"] += 1
                reg["dec_bad"] += int(dt is None or int(e8[dt]) != int(r_.state))
        n6 = pd.read_csv(t06 / "daily_nav.csv", parse_dates=["date"])
        n6 = n6[(n6.run.isin(["strategy", "hold_parent", "sleeve_only"])) & (n6.date <= V4_NAV_END) & (n6.book.isin(BOOKS))].copy()
        n6["run"] = n6.run.replace({"strategy": "strategy_fixed50"})  # T06's rule has the fixed 50/50 sleeve
        mn = n6.merge(nav, on=["book", "date", "cost_bps", "run"], how="left", suffixes=("_t06", ""))
        rel = (mn.nav / mn.nav_t06 - 1).abs()
        reg["nav_compared"] = len(mn)
        reg["nav_bad"] = int((rel.isna() | (rel > 1e-12)).sum())
        reg["worst"] = float(rel.max())
        reg["ok"] = reg["dec_compared"] > 0 and reg["nav_compared"] > 0 and reg["dec_bad"] == 0 and reg["nav_bad"] == 0
        P(f"   regression to T06 on the overlap: decisions {reg['dec_compared']:,} compared ({reg['dec_shifted']} read against the Friday of the same ISO week), {reg['dec_bad']} differ; NAVs (strategy_fixed50 vs T06's strategy, hold the parent, "
          f"100% sleeve 50/50; every cost; up to {V4_NAV_END.date()}) {reg['nav_compared']:,} compared, {reg['nav_bad']} differ, worst relative difference {reg['worst']:.1e} (limit 1e-12). The constant mixes are not compared: their average share f is the new window's own.")
    else:
        P("   regression to T06: NOT RUN (T06's decisions.csv or daily_nav.csv not found in %s)" % t06)
    rj = ev / "regression_t06.json"
    eng_v4 = []
    need_keys = ("decisions", "nav", "draws20", "g0", "d17_overlap", "gold_vs_d24")
    if rj.exists():
        rjd = json.loads(rj.read_text(encoding="utf-8"))
        eng_v4 = flags(rjd)
        miss = [k_ for k_ in need_keys if k_ not in rjd]
        P(f"   regression_t06.json (the engine's own check: T06's first 20 N4.10 draws replayed, the extended D17 against the old one, the gold signal against D24's weekly file): {len(eng_v4)} pass flags, all true: {all(eng_v4) and len(eng_v4) > 0}; keys missing: {miss or 'none'}")
        if miss:
            eng_v4 = eng_v4 + [False]
    else:
        P("   regression_t06.json: NOT FOUND")
        eng_v4 = [False]
    gates["V4"] = g0_ok and reg["ok"] and all(eng_v4)

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
    for (b, w, k_, s_), e in sorted(ctab.items()):
        ways_bad += int(n_ways(e["k"], e["S"], e["lo"], e["hi"]) != e["n_ways"])
        hi_exp = {"in": HI[("io", 1)], "out": HI[("io", 0)], "buy": HI[("gold", 1)], "sell": HI[("gold", 0)]}[s_]
        ways_bad += int(e["lo"] != LO or e["hi"] != hi_exp or not (e["k"] * e["lo"] <= e["S"] <= e["hi"] * e["k"]))
    worstz = max(m["worst_z"] for m in pos_means) if pos_means else float("inf")
    P(f"V5 the samplers are exact: (a) chi-square on k=3, S=12, bounds [2, 6]: p = {chi_p} (need > 0.001; from sampler_selftest.json, which this script cannot recompute"
      f"{'; its own pass flag: ' + str(st_ok) if st_ok is not None else ''}); (b) count_table.json against inclusion-exclusion: {len(ctab)} entries (in-or-out and gold), {ways_bad} differ or infeasible "
      f"(bounds {LO}/{HI[('io', 1)]}/{HI[('io', 0)]} and {LO}/{HI[('gold', 1)]}/{HI[('gold', 0)]}, feasibility 2k <= S <= hi k); (c) mean length at each spell position over the draws against S/k (F1 and F3 draws): worst |z| = {worstz:.2f} over {len(pos_means)} sets (need < 4)")
    gates["V5"] = (chi_p is not None and float(chi_p) > 0.001 and (st_ok is None or bool(st_ok))) and ways_bad == 0 and len(ctab) > 0 and worstz < 4

    # V6: the sleeve identity, from sleeve_trades.csv and decisions.csv
    v6 = {"rows": 0, "ratio_bad": 0, "cost_bad": 0, "cons_bad": 0, "raw_bad": 0, "n_reb": 0, "n_reb_exp": 0, "date_bad": 0, "n_exit": 0, "n_exit_exp": 0}
    for b in BOOKS:
        e = dec[dec.book == b].sort_values("j").reset_index(drop=True)
        s_, g_ = e.state.values.astype(int), e.g.values.astype(int)
        exp_reb = [j for j in range(1, len(e)) if s_[j - 1] == 0 and s_[j] == 0 and g_[j] != g_[j - 1] and not pd.isna(e.trade_date[j])]
        exp_exit = [j for j in range(1, len(e)) if s_[j - 1] == 1 and s_[j] == 0 and not pd.isna(e.trade_date[j])]
        for cost in COSTS:
            q = sl[(sl.book == b) & (sl.cost_bps == cost)]
            rb, ex_ = q[q.kind == "sleeve_rebalance"], q[q.kind == "switch_out"]
            v6["rows"] += len(q)
            v6["n_reb"] += len(rb)
            v6["n_reb_exp"] += len(exp_reb)
            v6["n_exit"] += len(ex_)
            v6["n_exit_exp"] += len(exp_exit)
            v6["date_bad"] += int(sorted(rb.date) != sorted(e.trade_date[exp_reb])) + int(sorted(ex_.date) != sorted(e.trade_date[exp_exit]))
            tot_a = q.gold_value_after + q.cash_value_after
            v6["ratio_bad"] += int(((q.gold_value_after / tot_a - q.gw_after).abs() > 1e-9).sum())
            v6["cost_bad"] += int(((q.cost - q.traded * q.cost_bps / 2 / 1e4).abs() > 1e-9 * np.maximum(1, q.traded)).sum())
            v6["cons_bad"] += int((((q.gold_value_before + q.cash_value_before - q.cost - tot_a).abs() > 1e-9) & (q.kind == "sleeve_rebalance")).sum())
            v6["raw_bad"] += int(((pd.to_datetime(q.date) > MCX_LAST) != q.gold_fill_raw.astype(bool)).sum())
        gwchk = int((np.abs(e.gw.values - np.where(g_ == 1, 0.8, 0.2)) > 1e-12).sum())
        v6["ratio_bad"] += gwchk
    gsm = 0
    for b in BOOKS:
        gg = gsig[gsig.book == b].sort_values("j")
        gsm += int((gg.g.values != gold[b]).sum() + (gg.decision_date.values != dec[dec.book == b].sort_values("j").decision_date.values).sum())
    eng_v6 = flags(au.get("v6")) if au.get("v6") is not None else []
    P(f"V6 the sleeve identity: {v6['rows']:,} sleeve-trade rows over the three costs; GOLDBEES / (GOLDBEES + cash) after the trade equals the target weight (0.8 or 0.2) and gw equals the signal's: {v6['ratio_bad']} differ; "
      f"cost = traded x cost_bps / 2 / 10,000: {v6['cost_bad']} differ; sleeve rebalance conserves value after cost: {v6['cons_bad']} differ; sleeve rebalances {v6['n_reb']} against {v6['n_reb_exp']} expected from the decisions "
      f"(OUT on both sides, signal changed), exits {v6['n_exit']} against {v6['n_exit_exp']}, trade dates differ {v6['date_bad']}; raw-fill flag disagrees with the MCX end date {MCX_LAST.date()}: {v6['raw_bad']}; gold_signal.csv differs from decisions.csv: {gsm}")
    P(f"   audit.json v6 block (the engine's own check: targets to 1e-12 of NAV, cost identity, continuity at 0 cost, no trade while OUT with the signal constant): {len(eng_v6)} pass flags, all true: {all(eng_v6) and len(eng_v6) > 0}")
    gates["V6"] = v6["rows"] > 0 and v6["ratio_bad"] == v6["cost_bad"] == v6["cons_bad"] == v6["raw_bad"] == v6["date_bad"] == gsm == 0 and v6["n_reb"] == v6["n_reb_exp"] and v6["n_exit"] == v6["n_exit_exp"] and (all(eng_v6) if eng_v6 else False)
    P("Gates:", {k: ("PASS" if v else "FAIL") for k, v in gates.items()}, "->", "ALL PASS" if all(gates.values()) else "A GATE FAILED: NOTHING BELOW MAY BE READ")

    # reportability
    def rt_of(a):
        a = np.asarray(a).astype(int)
        ent = int(((a[1:] == 1) & (a[:-1] == 0)).sum()) + int(a[0] == 1)
        ext = int(((a[1:] == 0) & (a[:-1] == 1)).sum())
        return min(ent, ext)

    def gold_with_out(g, s):
        """number of gold spells that contain at least one OUT week."""
        n_, i = 0, 0
        for v_, ln in runs(g):
            if (s[i:i + ln] == 0).any():
                n_ += 1
            i += ln
        return n_
    rt = {b: rt_of(rule[b]) for b in BOOKS}
    live_rt = {b: rt_of(real_of(b, "live", "io")) for b in BOOKS}
    gspell = {b: gold_with_out(gold[b], rule[b]) for b in BOOKS}
    gspell_live = {b: gold_with_out(real_of(b, "live", "gold"), real_of(b, "live", "io")) for b in BOOKS}
    feas = all(e["k"] * e["lo"] <= e["S"] <= e["hi"] * e["k"] for e in ctab.values())
    notrep = [b for b in BOOKS if rt[b] < 4 or gspell[b] < 4]
    notrep_live = [b for b in BOOKS if live_rt[b] < 4 or gspell_live[b] < 4]
    P("Reportability: in-or-out round trips per book, full window (need 4):", rt, "| live window:", live_rt, "| gold spells containing an OUT week, full:", gspell, "| live:", gspell_live,
      "| tables feasible (lo k <= S <= hi k):", feas, "| NOT REPORTABLE (full):", notrep or "none", "| NOT REPORTABLE (live):", notrep_live or "none")
    for b in (BOOKS[0], B7):
        P(f"Spell structure, {b}: in-or-out first state {'IN' if rule[b][0] else 'OUT'}, in-spells {rin[b]} (sum {sum(rin[b])}), out-spells {rout[b]} (sum {sum(rout[b])}); "
          f"gold first state {'BUY' if gold[b][0] else 'SELL'}, BUY spells {gbuy[b]} (sum {sum(gbuy[b])}), SELL spells {gsell[b]} (sum {sum(gsell[b])})")
    P("Number of allowed tuples (count_table.json, exact):")
    P(pd.DataFrame([{"book": b, "window": w, "timing": k_, "state": s_, "k": e["k"], "S": e["S"], "bounds": f"[{e['lo']}, {e['hi']}]", "n_ways": f"{e['n_ways']:,}"} for (b, w, k_, s_), e in sorted(ctab.items())]).to_string(index=False))
    P("Cash:", au["books"][BOOKS[0]].get("cash", "(not recorded in audit.json)"))

    # ── 4.0a the worked example ───────────────────────────────────────────────
    head("4.0a  THE WORKED EXAMPLE (SCMO_0003, 20.8 bps): a sleeve exit, a gold flip, one F1 draw and one F3 draw")
    b = "SCMO_0003"
    d = dec[dec.book == b].sort_values("j").reset_index(drop=True)
    slq = sl[(sl.book == b) & (sl.cost_bps == PRIMARY)].reset_index(drop=True)
    trq = tr[(tr.book == b) & (tr.run == "strategy") & (tr.cost_bps == PRIMARY)].reset_index(drop=True)
    pq = pos[(pos.book == b) & (pos.cost_bps == PRIMARY) & (pos.run == "strategy")]

    def units(date):
        q = pq[pq.date == date]
        return {r_.instrument: r_.units for r_ in q.itertuples() if not str(r_.instrument).endswith(".NS")}

    def prev_date(date):
        ds_ = sorted(set(pq.date))
        i = ds_.index(date)
        return ds_[i - 1] if i > 0 else None
    exit_row = slq[slq.kind == "switch_out"].iloc[0]
    # the first gold flip that has a positions snapshot before it (a flip right after the initial position at T0 has none: positions.csv starts at the first trade)
    flip_row = next(r_ for r_ in slq[slq.kind == "sleeve_rebalance"].itertuples() if prev_date(r_.date) is not None)
    flip_row = slq[(slq.kind == "sleeve_rebalance") & (slq.date == flip_row.date)].iloc[0]
    for lab, row in (("EXIT", exit_row), ("GOLD FLIP", flip_row)):
        j_ = int(d.index[d.trade_date == row.date][0])
        r = d.loc[j_]
        P(f"{lab}. One decision: week {j_}, decision date {r.decision_date}. Latest Master rows: Nifty100 {r.sign_Nifty100} ({r.label_Nifty100}), MC100 {r.sign_MC100} ({r.label_MC100}), SC100 {r.sign_SC100} ({r.label_SC100}); "
          f"MAUc1 {r.sign_MAUc1} ({r.label_MAUc1}). All three BUY: {r.all_three_buy} -> target {'parent' if r.state else 'sleeve: %.0f%% GOLDBEES / %.0f%% cash (gold signal %s)' % (100 * r.gw, 100 * (1 - r.gw), r.sign_MAUc1)}; "
          f"previous week: state {int(d.loc[j_ - 1, 'state'])}, gold signal {d.loc[j_ - 1, 'sign_MAUc1']}. Trade session: {r.trade_date}.")
        tt = trq[trq.date == row.date].iloc[0]
        ub, ua = (units(prev_date(row.date)) if prev_date(row.date) else {}), units(row.date)
        P(f"   Trade ({row['kind']}) on {row['date']} at OHLC4: value before {tt.V:.6f}, traded {row.traded:.6f}, cost {row.cost:.6f} = traded x 20.8/2/10,000; GOLDBEES value before {row.gold_value_before:.6f} -> after {row.gold_value_after:.6f}, "
          f"cash value before {row.cash_value_before:.6f} -> after {row.cash_value_after:.6f}; gold weight after {row.gw_after:.2f} (check: {row.gold_value_after / (row.gold_value_after + row.cash_value_after):.6f}); NAV at the close after: {tt.nav_close_after:.6f}")
        if lab == "GOLD FLIP":
            gk = next(k_ for k_ in ua if k_.upper().startswith("GOLD"))
            ck = next(k_ for k_ in ua if k_ != gk)
            P(f"   Units before (positions on {prev_date(row.date)}): " + ", ".join(f"{k_} {v_:.6f}" for k_, v_ in ub.items()) + f" | units after ({row.date}): " + ", ".join(f"{k_} {v_:.6f}" for k_, v_ in ua.items())
              + f" | implied GOLDBEES fill price before {row.gold_value_before / ub[gk]:.6f}, after {row.gold_value_after / ua[gk]:.6f}; cash level before {row.cash_value_before / ub[ck]:.6f}, after {row.cash_value_after / ua[ck]:.6f} (the same session, so equal)")
        else:
            P(f"   Units after the exit ({row.date}): " + ", ".join(f"{k_} {v_:.6f}" for k_, v_ in ua.items()) + f" (the basket is sold: value {tt.V:.6f} before cost)")
    nv = nav[(nav.book == b) & (nav.cost_bps == PRIMARY) & (nav.run == "strategy")].sort_values("date").reset_index(drop=True)
    k = int(nv.index[nv.date == pd.Timestamp(exit_row.date)][0])
    P("NAV around the exit (strategy, 20.8 bps):")
    table(nv.loc[k - 2:k + 2, ["date", "nav"]].assign(date=lambda x: x.date.dt.date), {"nav": lambda x: f"{x:.6f}"})
    s20 = S(b)
    P(f"One path: start 1.000000 on {nv.date.iloc[0].date()}, end {s20.end_nav:.6f} on {nv.date.iloc[-1].date()}, {int(s20.sessions)} sessions -> years {(s20.sessions - 1) / 252:.4f}, CAGR {100 * s20.cagr:.3f}%, max drawdown {100 * s20.max_dd:.2f}%; "
      f"{int(s20.trades)} trades of which {int(s20.sleeve_trades)} sleeve rebalances")
    for kind, state_, pair in (("io", "in", ("F1", "N4.10", "[6, 0]")), ("gold", "buy", ("F3", "N4.10-g", "[11, 6, 0]"))):
        e1, e2 = ctab[(b, "full", kind, state_)], ctab[(b, "full", kind, "out" if kind == "io" else "sell")]
        P(f"One {pair[0]} draw (draw_id 0; seed numpy default_rng({pair[2]}); {state_}-spell lengths first, then the other state's from the same generator):")
        P(f"  sampler: {state_}-spells k = {e1['k']}, total S = {e1['S']} weeks, each an integer in [{e1['lo']}, {e1['hi']}]; allowed ordered tuples c(k, S) = {e1['n_ways']:,} (inclusion-exclusion here: {n_ways(e1['k'], e1['S'], e1['lo'], e1['hi']):,})")
        P(f"           other state k = {e2['k']}, S = {e2['S']}, each in [{e2['lo']}, {e2['hi']}]; c(k, S) = {e2['n_ways']:,} (inclusion-exclusion here: {n_ways(e2['k'], e2['S'], e2['lo'], e2['hi']):,})")
    Z = {k_: states[f"{b}|full|{k_}"] for k_ in ("io|N4.9", "io|N4.10", "gold|N4.9-g", "gold|N4.10-g")}
    P(f"  the rule's in-spell lengths: {rin[b]}; F1 draw 0's: {lens(Z['io|N4.10'][0], 1)}; out-spells {rout[b]}; F1 draw 0's: {lens(Z['io|N4.10'][0], 0)}")
    P(f"  the real gold BUY lengths: {gbuy[b]}; F3 draw 0's: {lens(Z['gold|N4.10-g'][0], 1)}; SELL {gsell[b]}; F3 draw 0's: {lens(Z['gold|N4.10-g'][0], 0)}")
    e0 = pd.DataFrame({"j": np.arange(20), "decision_date": d.decision_date.iloc[:20].values, "real io": rule[b][:20], "F2 draw 0": Z["io|N4.9"][0, :20], "F1 draw 0": Z["io|N4.10"][0, :20],
                       "real gold": gold[b][:20], "F4 draw 0": Z["gold|N4.9-g"][0, :20], "F3 draw 0": Z["gold|N4.10-g"][0, :20]})
    P("The first 20 weekly states (in-or-out: 1 = parent, 0 = sleeve; gold: 1 = BUY, 0 = SELL): the real series, F2 (N4.9 draw 0, seed [3, 0]), F1 (N4.10 draw 0), F4 (N4.9-g draw 0, seed [11, 3, 0]) and F3 (N4.10-g draw 0):")
    table(e0)
    for fam in ("F1", "F2", "F3", "F4"):
        n_ = D(b, fam)
        x0 = n_[n_.draw_id == 0].iloc[0]
        rk = rank(s20.cagr, n_.cagr.values, True)
        P(f"  {fam} ({FAM_DESC[fam]}) draw 0: CAGR {100 * x0.cagr:.3f}%, max drawdown {100 * x0.max_dd:.2f}%, invested weeks {int(x0.invested_weeks)} (rule {int(s20.invested_weeks)}), BUY weeks {int(x0.g_buy_weeks)} (real {int(gold[b].sum())}), "
          f"spells {int(x0.n_in_spells)} in / {int(x0.n_out_spells)} out, {int(x0.n_buy_spells)} BUY / {int(x0.n_sell_spells)} SELL, sessions invested {int(x0.sessions_invested)} (rule {rule_sessions[b]}), sleeve trades {int(x0.sleeve_trades)} (rule {int(s20.sleeve_trades)})")
        P(f"  One ranking against {fam} (CAGR, {rk['draws']} draws): below {rk['worse']}, equal {rk['tied']}, above {rk['better']} -> percentile {rk['percentile']:.2f}, p-value {rk['p']:.5f}; "
          f"null median {100 * n_.cagr.median():.2f}%, edge {100 * (s20.cagr - n_.cagr.median()):+.2f} pp")

    # ── 4.1 headline ─────────────────────────────────────────────────────────
    head(f"4.1  HEADLINE: C1 to C4 per book and cost, rule against each null (full window {first_dec} -> {end_date}, LBES cash; {ndraws:,} draws each)")
    H = {}
    for cost in COSTS:
        for b in BOOKS:
            s = S(b, cost=cost)
            ent = {}
            for cr, stat, dec_f, bes_f in CRIT:
                nd_, nb_ = D(b, dec_f, cost), D(b, bes_f, cost)
                rd, rb = rank(s[stat], nd_[stat].values, True), rank(s[stat], nb_[stat].values, True)
                ent[cr] = {"rule": s[stat], "med": nd_[stat].median(), "pct": rd["percentile"], "p": rd["p"], "med_b": nb_[stat].median(), "pct_b": rb["percentile"], "p_b": rb["p"]}
            hp_ = holm([ent[cr]["p"] for cr, *_ in CRIT])
            for (cr, *_), h_ in zip(CRIT, hp_):
                ent[cr]["holm"] = h_
            H[(cost, b)] = ent
    f2 = lambda x: f"{x:.2f}"
    for cr, stat, dec_f, bes_f in CRIT:
        P(f"\n{cr} ({'CAGR' if stat == 'cagr' else 'maximum drawdown, shallower is better'}): rule against {dec_f} ({FAM_DESC[dec_f]}, deciding) and {bes_f} ({FAM_DESC[bes_f]}, beside); Holm = Holm-adjusted p over C1-C4, per book and cost")
        rows = [{"cost": c, "book": b, "rule%": 100 * H[(c, b)][cr]["rule"], f"{dec_f}_med%": 100 * H[(c, b)][cr]["med"],
                 f"{dec_f}_edge_pp": 100 * (H[(c, b)][cr]["rule"] - H[(c, b)][cr]["med"]), f"{dec_f}_pct": H[(c, b)][cr]["pct"], f"{dec_f}_p": H[(c, b)][cr]["p"], f"{dec_f}_Holm_p": H[(c, b)][cr]["holm"],
                 f"{bes_f}_med%": 100 * H[(c, b)][cr]["med_b"], f"{bes_f}_pct": H[(c, b)][cr]["pct_b"], f"{bes_f}_p": H[(c, b)][cr]["p_b"]} for c in COSTS for b in BOOKS]
        table(pd.DataFrame(rows), {k_: (lambda x: f"{x:.5f}") if k_.endswith("_p") else (lambda x: f"{x:+.2f}") if "edge" in k_ else f2 for k_ in rows[0] if k_ not in ("cost", "book")})
    P(f"pct = percentile of the rule among the draws; p = (1 + draws at least as good) / ({ndraws} + 1); Holm = Holm step-down over the four criteria of the same book and cost (unadjusted p decides at the pass mark; Holm is printed beside it).")
    P("\nSecondary statistics at 20.8 bps, percentile against each null's draws (each statistic's better direction):")
    for fam in ("F1", "F2", "F3", "F4"):
        sec = []
        for b in BOOKS:
            s = S(b)
            n = D(b, fam)
            sec.append({"book": b, **{k_: rank(s[k_], n[k_].values, hb)["percentile"] for k_, hb in HIGHER_BETTER.items()}})
        P(f"  against {fam} ({FAM_DESC[fam]}):")
        table(pd.DataFrame(sec), {k_: (lambda x: f"{x:.1f}") for k_ in HIGHER_BETTER})

    # ── 4.2 comparators ──────────────────────────────────────────────────────
    head("4.2  COMPARATORS (benchmarks, not nulls), same window, T0 = 1.000")
    comp = []
    for cost in COSTS:
        for b in BOOKS:
            row = {"cost": cost, "book": b}
            for kind in KINDS:
                s = S(b, kind, cost)
                row[f"{kind}_CAGR%"], row[f"{kind}_DD%"] = 100 * s.cagr, 100 * s.max_dd
            pn = nav[(nav.book == b) & (nav.run == "published_D17")].sort_values("date").nav.values
            ps = stats_from_nav(pn)
            row["published_CAGR%"], row["published_DD%"] = 100 * ps["cagr"], 100 * ps["max_dd"]
            comp.append(row)
    C = pd.DataFrame(comp)
    P("CAGR (%):")
    table(C[["cost", "book"] + [c for c in C.columns if c.endswith("CAGR%")]], {c: f2 for c in C.columns if c.endswith("%")})
    P("Maximum drawdown (%):")
    table(C[["cost", "book"] + [c for c in C.columns if c.endswith("DD%")]], {c: f2 for c in C.columns if c.endswith("%")})
    P("Trades and cost paid at 20.8 bps (sleeve rebalances in brackets):")
    table(pd.DataFrame([{"book": b, **{f"{k_}": f"{int(S(b, k_).trades)} ({int(S(b, k_).sleeve_trades)}) / {S(b, k_).cost_paid:.5f}" for k_ in KINDS}} for b in BOOKS]))
    f_ = int(rule["SCMO_0003"].sum()) / weeks["SCMO_0003"]
    P(f"The constant mixes hold {100 * f_:.1f}% in the parent (the rule's average); constant_mix has a 50/50 non-stock share, constant_mix_timed splits it by the MAUc1 weight; sleeve_only holds the sleeve alone (50/50), sleeve_only_timed "
      f"the sleeve alone split by the MAUc1 weight; strategy_fixed50 is T06's rule on this window; hold_parent is the engine with the decision fixed IN; published is D17 rebased to 1.000 on the same dates.")

    # ── 4.3 power ────────────────────────────────────────────────────────────
    head("4.3  POWER: round trips, the minimum detectable edge (MDE = 2.8 x null SD; 80% power, two-sided 5%) per null, sessions invested and sleeve trades per draw")
    mde = []
    for b in BOOKS:
        row = {"book": b, "round_trips": rt[b], "gold_spells_with_OUT": gspell[b]}
        for fam in ("F1", "F2", "F3", "F4", "F5"):
            n = D(b, fam)
            row.update({f"{fam}_sd_CAGR_pp": 100 * n.cagr.std(), f"{fam}_MDE_CAGR_pp": 280 * n.cagr.std(), f"{fam}_sd_DD_pp": 100 * n.max_dd.std(), f"{fam}_MDE_DD_pp": 280 * n.max_dd.std()})
        mde.append(row)
    M = pd.DataFrame(mde)
    table(M, {c: f2 for c in M.columns if c.endswith("_pp")})
    P("T08.md section 3 step 12: the thresholds in section 2 do not depend on these numbers, which did not exist when it was written. T06's N4.10 null SD of CAGR was 5.4 to 6.9 pp (MDE 15 to 19 pp), the prior for C1; "
      "for C3 and C4 there is no prior: the gold nulls move only the sleeve's split, so their spread is probably much narrower.")
    P(f"\nSessions invested per draw (full window, LBES, 20.8 bps; of {len(cal['SCMO_0003']) - 1:,} sessions for SCMO_0003; weeks are held exactly, sessions are not; F3 and F4 hold the real switch, so sessions equal the rule's):")
    ses_rows = []
    for b in BOOKS:
        row = {"book": b, "rule": rule_sessions[b], "of": len(cal[b]) - 1}
        for fam in ("F1", "F2", "F3", "F4"):
            x = D(b, fam).sessions_invested.values
            row.update({f"{fam}_min": int(x.min()), f"{fam}_median": float(np.median(x)), f"{fam}_max": int(x.max()), f"{fam}_equal_to_rule": int((x == rule_sessions[b]).sum())})
        ses_rows.append(row)
    table(pd.DataFrame(ses_rows), {c: (lambda x: f"{x:.1f}") for c in ("F1_median", "F2_median", "F3_median", "F4_median")})
    P(f"\nSleeve trades per gold draw (F3 and F4; the rule has {int(S('SCMO_0003').sleeve_trades)} on SCMO_0003; draws that flip in IN weeks never trade, so the count varies):")
    table(pd.DataFrame([{"book": b, "rule": int(S(b).sleeve_trades), **{f"{fam}_{k_}": v_ for fam in ("F3", "F4") for k_, v_ in (("min", int(D(b, fam).sleeve_trades.min())), ("median", float(D(b, fam).sleeve_trades.median())), ("max", int(D(b, fam).sleeve_trades.max())))}} for b in BOOKS]),
          {c: (lambda x: f"{x:.1f}") for c in ("F3_median", "F4_median")})

    # ── 4.4 verdict ──────────────────────────────────────────────────────────
    head("4.4  VERDICT against the pre-registered criteria (after cost, 20.8 bps; F1 decides C1 and C2, F3 decides C3 and C4; unadjusted, Holm beside)")
    hp = {b: H[(PRIMARY, b)] for b in BOOKS}
    cnt_ = {}
    for cr, stat, dec_f, bes_f in CRIT:
        cnt_[cr] = int(sum(hp[b][cr]["pct"] >= PASS_PCT and b not in notrep for b in BOOKS))
        cnt_[cr + "b"] = int(sum(hp[b][cr]["pct_b"] >= PASS_PCT and b not in notrep for b in BOOKS))
    mdeb = M.set_index("book")
    names = {"C1": "C1 equity timing (H1)", "C2": "C2 equity-switch protection (H2)", "C3": "C3 gold timing (H3)", "C4": "C4 gold-timing protection (H4)"}
    for cr, stat, dec_f, bes_f in CRIT:
        ok = cnt_[cr] >= 3
        lst = lambda key: ", ".join("%s %.1f" % (b[-4:], hp[b][cr][key]) for b in BOOKS)
        mc = f"{dec_f}_MDE_{'CAGR' if stat == 'cagr' else 'DD'}_pp"
        mdetxt = "; ".join(f"{b[-4:]}: undetectable below {mdeb.loc[b, mc]:.1f} pp" for b in BOOKS)
        P(f"  {names[cr]:34s} {'PASS' if ok else 'FAIL'}   percentile >= {PASS_PCT:.0f} in >= 3 of 4 books against {dec_f}: {cnt_[cr]} of 4 ({lst('pct')}); Holm-adjusted p: {', '.join('%s %.3f' % (b[-4:], hp[b][cr]['holm']) for b in BOOKS)}"
          f"   beside, against {bes_f}: {cnt_[cr + 'b']} of 4 ({lst('pct_b')})   {('MDE: ' + mdetxt) if not ok else ''}")
    A = cnt_["C1"] >= 3 and cnt_["C2"] >= 3
    Bg = cnt_["C3"] >= 3 and cnt_["C4"] >= 3
    A_b, B_b = cnt_["C1b"] >= 3 and cnt_["C2b"] >= 3, cnt_["C3b"] >= 3 and cnt_["C4b"] >= 3
    P("\nOutcome map (T08.md section 2), the row that applies:")
    if not all(gates.values()):
        P("  - a V gate fails: nothing is read. Fix and rerun as a new run directory")
    elif A and Bg:
        P("  - C1 and C2 PASS; C3 and C4 PASS: both timings beat chance on this window. The MAUc1 timing of the sleeve is supported as timing (PROVISIONAL: nothing is unseen)")
    elif A and not Bg:
        P("  - C1 and C2 PASS; C3 or C4 FAIL: the equity switch carries the result. The gold timing is not distinguishable from random gold timing on this window; any gain over the 50/50 sleeve shown in R6 is gold exposure or luck, not demonstrated timing skill")
    elif Bg and not A:
        P("  - C1 or C2 FAIL; C3 and C4 PASS: the gold timing does what random gold timing does not, while the equity switch no longer shows an edge against N4.10 with this sleeve")
    else:
        P("  - C1 or C2 FAIL; C3 or C4 FAIL: no timing edge over chance for the failing parts on this window")
    dis = []
    if A != A_b:
        dis.append("F1 and F2 disagree on C1 and C2")
    if Bg != B_b:
        dis.append("F3 and F4 disagree on C3 and C4")
    if any((cnt_[c_] >= 3) != (cnt_[c_ + "b"] >= 3) for c_ in ("C1", "C2", "C3", "C4")) and not dis:
        dis.append("a single criterion differs between the deciding and the beside null")
    P("  - agreement of the paired nulls:", "; ".join(dis) + ": both are reported in the verdict and the finding's status note says so (N6.8)" if dis else "F1 and F2 agree on C1 and C2, F3 and F4 agree on C3 and C4")
    P("Only C3 and C4 are the new claim; C1 and C2 replicate T06 under a different sleeve. Any new finding is PROVISIONAL whatever the outcome (the window is seen).")

    # ── 4.5 robustness ───────────────────────────────────────────────────────
    head("4.5  ROBUSTNESS R1-R7 (decide a finding's status, not the verdicts)")
    for cost in (0.0, 50.0):
        for cr, stat, dec_f, bes_f in CRIT:
            for fam, key in ((dec_f, "pct"), (bes_f, "pct_b")):
                v_ = [H[(cost, b)][cr][key] for b in BOOKS]
                n_ = sum(x >= PASS_PCT for x in v_)
                P(f"R1 at {cost:g} bps, {cr} against {fam}: {n_} of 4 -> {'PASS' if n_ >= 3 else 'FAIL'} ({', '.join('%s %.1f' % (bb[-4:], x) for bb, x in zip(BOOKS, v_))})")
    for label, win, cash, fams in (("R2 LIQUIDCASE as the cash leg (full window, 20.8 bps)", "full", LIQ, (("C1", "F1"), ("C3", "F3"))), ("R3 live window %s -> %s (own spells, totals and null, same bounds, 20.8 bps)" % (LIVE_START, end_date), "live", "lbes", (("C1", "F1"), ("C3", "F3")))):
        for cr, fam in fams:
            pcts, extra = [], []
            for b in BOOKS:
                s = st[(st.book == b) & (st.window == win) & (st.cash == cash) & (st.cost_bps == PRIMARY) & (st.kind == "strategy")]
                n = D(b, fam, win=win, cash=cash)
                if len(s) and len(n):
                    pcts.append(float(rank(s.iloc[0].cagr, n.cagr.values, True)["percentile"]))
                    extra.append(f"{100 * s.iloc[0].cagr:.1f}%")
            n_ = sum(x >= PASS_PCT for x in pcts)
            rep = "" if win == "full" or not notrep_live else f" NOT REPORTABLE for {notrep_live} (fewer than 4 round trips or gold spells with an OUT week): do not quote"
            P(f"{label}, {cr} against {fam}: CAGR percentiles {[round(x, 1) for x in pcts]} (rule's CAGR {extra}) -> {n_} of {len(pcts)} >= {PASS_PCT:.0f} -> {'PASS' if (n_ >= 3) else 'FAIL'}{rep}")
    P("\nR4 agreement of the paired nulls (20.8 bps; no pass mark). Per book: the rule's percentile under each null of a pair, and each null's spread of after-cost CAGR:")
    r4 = []
    for b in BOOKS:
        s = S(b)
        row = {"book": b, "CAGR%": 100 * s.cagr}
        for fam in ("F1", "F2", "F3", "F4"):
            n = D(b, fam)
            q = np.percentile(n.cagr.values, [5, 95])
            row.update({f"{fam}_pct": rank(s.cagr, n.cagr.values, True)["percentile"], f"{fam}_DD_pct": rank(s.max_dd, n.max_dd.values, True)["percentile"], f"{fam}_median%": 100 * n.cagr.median(),
                        f"{fam}_sd_pp": 100 * n.cagr.std(), f"{fam}_p5%": 100 * q[0], f"{fam}_p95%": 100 * q[1]})
        row["gap(F2-F1)"] = row["F2_pct"] - row["F1_pct"]
        row["gap(F4-F3)"] = row["F4_pct"] - row["F3_pct"]
        r4.append(row)
    R4 = pd.DataFrame(r4)
    table(R4, {c: f2 for c in R4.columns if c != "book"})
    P("Historical reference (T06, a different window 2019-01-02 -> 2026-10-22 and a fixed 50/50 sleeve; T06's stored N4.10 and N4.9 draws and its rule, 20.8 bps, LBES cash; NOT comparable draw for draw, and no pass mark):")
    if (t06 / "draws.csv").exists() and (t06 / "stats.csv").exists():
        s6, d6 = pd.read_csv(t06 / "stats.csv"), pd.read_csv(t06 / "draws.csv")
        hrow = []
        for b in BOOKS:
            sr = s6[(s6.book == b) & (s6.window == "full") & (s6.cash == "lbes") & (s6.cost_bps == PRIMARY) & (s6.kind == "strategy")].iloc[0]
            row = {"book": b, "T06_CAGR%": 100 * sr.cagr}
            for typ, nm in (("N4.10", "N10"), ("N4.9", "N9")):
                nd_ = d6[(d6.book == b) & (d6.window == "full") & (d6.cash == "lbes") & (d6.cost_bps == PRIMARY) & (d6.draw_type == typ)]
                row.update({f"T06_{nm}_pct": rank(sr.cagr, nd_.cagr.values, True)["percentile"], f"T06_{nm}_DD_pct": rank(sr.max_dd, nd_.max_dd.values, True)["percentile"], f"T06_{nm}_sd_pp": 100 * nd_.cagr.std()})
            row.update({"T08_F1_pct": R4.set_index("book").loc[b, "F1_pct"], "T08_F2_pct": R4.set_index("book").loc[b, "F2_pct"]})
            hrow.append(row)
        table(pd.DataFrame(hrow), {c: f2 for c in hrow[0] if c != "book"})
    else:
        P("  (T06's draws.csv / stats.csv not found in %s)" % t06)
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
    P("\nR7 raw-fill sensitivity (the rule re-run with the close in place of the raw OHLC4 on every session after 2026-09-28):")
    r7_file = next((p for p in (ev / "r7_raw_fill.csv", ev / "raw_fill_sensitivity.csv", ev / "r7.csv") if p.exists()), None)
    r7_kinds = [k_ for k_ in sorted(set(st.kind)) if re.search(r"raw|close_fill|r7", k_)]
    if r7_file is not None:
        P(f"  read from {r7_file.name}:")
        table(pd.read_csv(r7_file))
    elif r7_kinds:
        P(f"  read from stats.csv kinds {r7_kinds}:")
        for b in BOOKS:
            for k_ in r7_kinds:
                s_k = S(b, k_)
                P(f"  {b} {k_}: CAGR {100 * s_k.cagr:.3f}% (rule {100 * S(b).cagr:.3f}%, change {100 * (s_k.cagr - S(b).cagr):+.3f} pp), max drawdown {100 * s_k.max_dd:.2f}% (rule {100 * S(b).max_dd:.2f}%)")
    else:
        P("  not in evidence (the engine ships no raw-fill file; the sessions after 2026-09-28 and the sleeve trades among them are in audit.json and sleeve_trades.csv)")
    raw_tr = sl[(sl.cost_bps == PRIMARY) & (sl.gold_fill_raw.astype(bool))]
    P(f"  sleeve trades of the rule filled at the raw OHLC4 (20.8 bps): {len(raw_tr)}" + ("" if raw_tr.empty else " (" + ", ".join(f"{r_.book[-4:]} {r_.date} {r_.kind}" for r_ in raw_tr.itertuples()) + ")"))
    P("\nHypotheses: H1 (equity timing)", "SUPPORTED in-sample against F1 (PROVISIONAL: nothing is unseen)" if cnt_["C1"] >= 3 else "FALSIFIED against F1",
      "| H2 (equity-switch protection)", "SUPPORTED in-sample against F1 (PROVISIONAL)" if cnt_["C2"] >= 3 else "FALSIFIED against F1",
      "| H3 (gold timing)", "SUPPORTED in-sample against F3 (PROVISIONAL)" if cnt_["C3"] >= 3 else "FALSIFIED against F3",
      "| H4 (gold-timing protection)", "SUPPORTED in-sample against F3 (PROVISIONAL)" if cnt_["C4"] >= 3 else "FALSIFIED against F3")
    P("Gates:", "all pass" if all(gates.values()) else "A GATE FAILED")
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "analysis.log").write_text(out.getvalue(), encoding="utf-8")
    print("wrote", outdir / "analysis.log")
    sys.exit(0 if (all(gates.values()) and v3["draws"] > 0) else 1)


if __name__ == "__main__":
    main()
