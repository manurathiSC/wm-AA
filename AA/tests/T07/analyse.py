"""T07 analysis: reads only the shipped evidence in evidence/<run>/ and prints section 4 of the write-up.

    python tests/T07/analyse.py [--run headline]            prints to stdout and writes tests/T07/analysis.log
    python tests/T07/analyse.py --evidence DIR [--out DIR]  point at another evidence directory (e.g. a synthetic one);
                                                            analysis.log then goes to --out (default: DIR itself), never to tests/T07

Imports nothing from the engine, the verifier or tag_lookup.py. Percentile = (worse + 0.5 * tied) / draws * 100; p-value = (1 + at least as good) / (draws + 1);
ties are equal within a relative 1e-12 (T07.md section 2). N4.6 decides C1, C2; N4.8 is shown beside it; C3 is the rule minus the whole-book switch.
Exits non-zero if a validity gate (V1-V7) failed or if nothing was compared.

Gates V3, V4, V5 and V6/V7 are re-derived here from the evidence files themselves (draw_drops.npz, draw_labels.npz, event_stocks.csv, events.csv, decisions.csv,
daily_nav.csv, the T06 evidence, controls_*.csv/json); the engine's own json files are printed and, where a clear verdict key exists, must agree.
The sampler is replayed from its seed ([7, draw_id, book_no], one rng.random() per event, allowed subsets by increasing bitmask over the held stocks in
increasing ISIN order, bit i = stock i) for the first --replay draws of every book and window, as an independent check of V3.
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
from statistics import NormalDist

import numpy as np
import pandas as pd

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
AA = HERE.parents[1]
BOOKS = ["SCMO_0003", "SCMO_0007", "SCMO_0010", "SCMO_0029"]
AABOOK = {"SCMO_0003": "SCMO_0042", "SCMO_0007": "SCMO_0043", "SCMO_0010": "SCMO_0044", "SCMO_0029": "SCMO_0045"}
PRIMARY = 20.8
COSTS = (0.0, PRIMARY, 50.0)
PASS_PCT = 90.0


def v6_xmax(K: int, p: float = 0.10, alpha: float = 0.05 / 4) -> int:
    """AMENDMENT 2026-11-12: largest X with P(Binomial(K, p) >= X) >= alpha (one-sided, 4 books). K = 100: 17."""
    tail = 0.0
    for X in range(K, -1, -1):
        tail += math.comb(K, X) * p ** X * (1 - p) ** (K - X)
        if tail >= alpha:
            return X
    return K
NULLS = (("N46", "N4.6"), ("N48", "N4.8"))  # the deciding null first
HIGHER_BETTER = {"cagr": True, "max_dd": True, "calmar": True, "vol": False, "ulcer": False, "days_below_10pct": False, "longest_underwater": False}
LIVE_START = "2021-11-01"
V4_NAV_END = pd.Timestamp("2026-10-22")
BANDS = ["Large", "Mid", "Small and below"]
SIGS = ["Nifty100", "MC100", "SC100"]
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


def asbool(s: pd.Series) -> np.ndarray:
    return s.astype(str).str.strip().str.lower().isin(["true", "1", "1.0"]).values


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
    """First scalar whose key (lower case) is in `names`, searching dicts and lists recursively; None if absent."""
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


def per_book(obj, book):
    """The dict of one book from {book: {...}}, {'books': {book: {...}}} or [{'book': book, ...}] (the engine's json files do not fix a shape)."""
    if isinstance(obj, dict):
        if book in obj and isinstance(obj[book], dict):
            return obj[book]
        for v in obj.values():
            if isinstance(v, (dict, list)):
                r = per_book(v, book)
                if r is not None:
                    return r
        if obj.get("book") == book:
            return obj
    elif isinstance(obj, list):
        for v in obj:
            r = per_book(v, book)
            if r is not None:
                return r
    return None


def bitsums(w: np.ndarray) -> np.ndarray:
    """Total weight of every subset, index = bitmask, bit i = stock i."""
    s = np.zeros(1)
    for x in w:
        s = np.concatenate([s, s + x])
    return s


def allowed_set(w_sorted: np.ndarray, D: float, tau: float) -> np.ndarray:
    """Bitmasks (increasing) of the subsets whose weight is within tau of D (inclusive, with 1e-12 slack for float dust)."""
    return np.flatnonzero(np.abs(bitsums(w_sorted) - D) <= tau + 1e-12)


def mbb_se(nav_a: np.ndarray, nav_b: np.ndarray, seed, nboot=1000, blk=20) -> float:
    """SD over `nboot` moving-block resamples (blocks of `blk` sessions, drawn in pairs) of CAGR(a) - CAGR(b)."""
    ra, rb = np.log(nav_a[1:] / nav_a[:-1]), np.log(nav_b[1:] / nav_b[:-1])
    n = len(ra)
    nb = int(math.ceil(n / blk))
    rg = np.random.default_rng(seed)
    st = rg.integers(0, n - blk + 1, size=(nboot, nb))
    ix = (st[:, :, None] + np.arange(blk)[None, None, :]).reshape(nboot, -1)[:, :n]
    yrs = n / 252
    d = np.expm1(ra[ix].sum(1) / yrs) - np.expm1(rb[ix].sum(1) / yrs)
    return float(d.std(ddof=1))


def approved_rows():
    txt = (AA / "data" / "APPROVED_DATA.md").read_text(encoding="utf-8")
    tab = txt[txt.index("<!-- approved-table:start -->"):txt.index("<!-- approved-table:end -->")]
    rows = []
    for l in tab.splitlines():
        if l.startswith("|") and not l.startswith("|---") and not l.startswith("| Status"):
            c = [x.strip() for x in l.strip().strip("|").split("|")]
            rows.append({"status": c[0], "id": c[1], "file": c[2], "through": c[3], "sha": c[4]})
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="headline")
    ap.add_argument("--evidence", default=None, help="explicit evidence directory (overrides --run)")
    ap.add_argument("--out", default=None, help="where analysis.log goes (default tests/T07 for --run, the evidence directory for --evidence)")
    ap.add_argument("--t06", default=str(AA / "tests" / "T06" / "evidence" / "headline"), help="T06's evidence (V4)")
    ap.add_argument("--doc", default=str(HERE / "T07.md"), help="T07.md, read only, for the pre-registration hash")
    ap.add_argument("--books", default=None, help="comma list; for engine smoke runs that hold fewer than the four books (the verdict counts then mean nothing)")
    ap.add_argument("--expect-draws", type=int, default=2000, help="draws per book, cost and null the pre-registration requires (2,000); V3 fails if different")
    ap.add_argument("--replay", type=int, default=100, help="N4.6 draws per book and window replayed from their seeds (V3)")
    a = ap.parse_args()
    if a.books:
        BOOKS[:] = a.books.split(",")
    ev_dir = Path(a.evidence) if a.evidence else HERE / "evidence" / a.run
    outdir = Path(a.out) if a.out else (ev_dir if a.evidence else HERE)
    t06 = Path(a.t06)
    BNO = {"SCMO_0003": 0, "SCMO_0007": 1, "SCMO_0010": 2, "SCMO_0029": 3}

    dec = pd.read_csv(ev_dir / "decisions.csv")
    ev = pd.read_csv(ev_dir / "events.csv")
    es = pd.read_csv(ev_dir / "event_stocks.csv", keep_default_na=False, na_values=[""], dtype={"isin": str, "tag_detail": str})
    st = pd.read_csv(ev_dir / "stats.csv")
    dr = pd.read_csv(ev_dir / "draws.csv")
    nav = pd.read_csv(ev_dir / "daily_nav.csv", parse_dates=["date"])
    g4 = pd.read_csv(ev_dir / "g_engine.csv")
    au = json.loads((ev_dir / "audit.json").read_text(encoding="utf-8"))
    ct = json.loads((ev_dir / "count_table.json").read_text(encoding="utf-8"))
    zdrops = np.load(ev_dir / "draw_drops.npz")
    zlab = np.load(ev_dir / "draw_labels.npz")
    inp = pd.read_csv(ev_dir / "inputs.csv", comment="#", dtype=str, keep_default_na=False)
    doc = Path(a.doc).read_text(encoding="utf-8")
    region = doc[doc.index("\n## 1. Idea and references") + 1:doc.index("\n## 4. Results") + 1]
    region = "\n".join(l.rstrip() for l in region.replace("\r\n", "\n").split("\n"))
    sha = hashlib.sha256(region.encode("utf-8")).hexdigest()
    m_sha = re.search(r"§1–§3 sha256:\*\* `([^`]*)`", doc)
    sha_hdr = m_sha.group(1) if m_sha else "?"
    B7 = "SCMO_0007" if "SCMO_0007" in BOOKS else BOOKS[-1]

    ev["partial_b"] = asbool(ev["partial"])
    es["kept_b"] = asbool(es["kept"])
    ev = ev.sort_values(["book", "window", "event_no"]).reset_index(drop=True)
    EV = {(b, w): g.reset_index(drop=True) for (b, w), g in ev.groupby(["book", "window"])}
    ES = {(b, w): es[(es.book == b) & (es.window == w)].reset_index(drop=True) for b in BOOKS for w in ("full", "live")}  # file order = the order of the drops columns
    S = lambda b, kind="segment", cost=PRIMARY, win="full", cash="lbes": st[(st.book == b) & (st.window == win) & (st.cash == cash) & (st.cost_bps == cost) & (st.kind == kind)].iloc[0]
    D = lambda b, typ, cost=PRIMARY, win="full", cash="lbes": dr[(dr.book == b) & (dr.window == win) & (dr.cash == cash) & (dr.cost_bps == cost) & (dr.draw_type == typ)].sort_values("draw_id")
    ndraws = int(len(D(BOOKS[0], "N4.6")))
    rule_state = {b: dec[dec.book == b].sort_values("j").reset_index(drop=True) for b in BOOKS}
    weeks = {b: len(rule_state[b]) for b in BOOKS}
    cal = {b: nav[(nav.book == b) & (nav.cost_bps == PRIMARY) & (nav.run == "segment")].sort_values("date").date.reset_index(drop=True) for b in BOOKS}
    nses = {b: len(cal[b]) for b in BOOKS}
    live_i = {b: int(np.searchsorted(cal[b].values, np.datetime64(pd.Timestamp(LIVE_START)))) for b in BOOKS}

    P("T07 analysis. Run:", ev_dir.name, "| draws per book, cost and null:", f"{ndraws:,}", "| deciding null: N4.6; N4.8 beside it; C3 = rule minus the whole-book switch")
    P("Window: %s -> %s (%s from %s), %d weekly decisions (%s %d); live window from %s (first session %s)" % (
        rule_state[BOOKS[0]].decision_date.iloc[0], rule_state[BOOKS[0]].decision_date.iloc[-1], B7, rule_state[B7].decision_date.iloc[0], weeks[BOOKS[0]], B7, weeks[B7], LIVE_START,
        str(cal[BOOKS[0]].iloc[live_i[BOOKS[0]]].date())))
    P("Pre-registration sha256 in the header:", sha_hdr[:16], "| recomputed now:", sha[:16], "| match:", sha_hdr == sha)
    P("Evidence read:", ", ".join(sorted(p.name for p in ev_dir.iterdir())))

    # row <-> event index maps, per (book, window)
    ROWMAP = {}
    for key, rows in ES.items():
        e = EV.get(key)
        if e is None or not len(rows):
            continue
        pos = {int(n): i for i, n in enumerate(e.event_no.values)}
        ROWMAP[key] = np.array([pos[int(n)] for n in rows.event_no.values])

    # ══ 4.0b gates ═══════════════════════════════════════════════════════════
    head("4.0b  GATES, THE NULLS' TABLES AND REPORTABILITY\n(V1 independent check, V2 point in time, V3 the nulls hold their tables, V4 regression to T06 and always-in, V5 the sampler is exact, V6 negative control, V7 oracle)")
    gates = GATES
    vj = ev_dir / "verify_t07.json"
    if vj.exists():
        v = json.loads(vj.read_text(encoding="utf-8"))
        if "exit_ok" in v:
            comp, bad_, exit_ok = v.get("gate_compared", 0), v.get("gate_failures_and_missing", 1), bool(v.get("exit_ok"))
        else:
            comp = bad_ = 0

            def walk(o):
                nonlocal comp, bad_
                if isinstance(o, dict):
                    c_ = next((o[k] for k in ("compared", "rows_compared", "n_compared", "rows") if k in o and isinstance(o[k], (int, float))), None)
                    f_ = next((o[k] for k in ("failures", "failed", "n_failed", "mismatches", "fail") if k in o and isinstance(o[k], (int, float))), None)
                    if c_ is not None and f_ is not None:
                        comp += c_
                        bad_ += f_
                    for x in o.values():
                        walk(x)
                elif isinstance(o, list):
                    for x in o:
                        walk(x)
            walk(v)
            exit_ok = bool(find_key(v, {"exit_ok", "ok", "passed"}) is not False)
        det = find_key(v, {"detected", "corrupt_detected", "selftest_detected", "corrupted_copy_detected"})
        ok = exit_ok and bad_ == 0 and comp > 0 and det is True
        P("V1 independent check (verify_t07.py): ", "PASS" if ok else "FAIL", f"| comparisons {comp:,}, failures and missing {bad_}, corrupted copy detected: {det}")
        gates["V1"] = ok
    else:
        P("V1 independent check: NOT RUN (%s missing)" % vj)
        gates["V1"] = False

    viol = cnt = 0
    v2 = au.get("v2")
    if isinstance(v2, dict) and "violations" in v2 and "checked" in v2:
        viol, cnt = v2["violations"], v2["checked"]  # the engine's own totals (its per-kind counters are summed into them)
        if v2.get("pass") is False:
            viol += 1
    else:
        def walk2(o, path=()):
            nonlocal viol, cnt
            if isinstance(o, dict):
                for k, val in o.items():
                    walk2(val, path + (str(k).lower(),))
            elif isinstance(o, (int, float)) and not isinstance(o, bool) and any(p.startswith("v2") for p in path):
                if "violation" in path[-1] or "bad" in path[-1]:
                    viol += o
                elif "checked" in path[-1] or "count" in path[-1] or path[-1].startswith("n_"):
                    cnt += o
        walk2(au)
    P(f"V2 point in time: violations {viol} of {cnt:,} checks (decisions on Master rows dated on or before them; tags from snapshots on or before the information date; trades after their decisions; 0 required out of > 0)")
    ag = au.get("gates")
    if isinstance(ag, dict) and ag.get("V2") is False:
        P("   audit.json's own gates say V2 failed")
        viol += 1
    gates["V2"] = viol == 0 and cnt > 0

    # V3: every draw, from draw_drops.npz / draw_labels.npz, event_stocks.csv, events.csv
    v3 = {"keys": 0, "draws": 0, "bad": 0, "n_bad_count": 0, "rows": 0, "rows_bad": 0, "tau_worst": 0.0, "gap_mean": {}, "replayed": 0, "replay_bad": 0, "notes": []}
    GAP = {}
    for b in BOOKS:
        for win in ("full", "live"):
            rows, e = ES[(b, win)], EV.get((b, win))
            if e is None or not len(rows):
                v3["notes"].append(f"no events for {b}|{win}")
                v3["bad"] += 1
                continue
            R, E = len(rows), len(e)
            ri = ROWMAP[(b, win)]
            M = np.zeros((R, E))
            M[np.arange(R), ri] = 1.0
            w = rows.listed_weight.values.astype(float)
            Wm = M * w[:, None]
            Dr, tau = e.dropped_weight.values.astype(float), e.tau.values.astype(float)
            n_held, n_drop = e.n_held.values.astype(int), e.n_dropped.values.astype(int)
            # the evidence's own consistency: rule's rows against events.csv
            if "row" in rows.columns and not (rows["row"].values == np.arange(R)).all():
                v3["rows_bad"] += 1
                v3["notes"].append(f"{b}|{win}: the 'row' column of event_stocks.csv is not 0..R-1 in file order")
            kept = rows.kept_b.values
            Drow = (~kept).astype(float) @ Wm
            v3["rows"] += E
            v3["rows_bad"] += int((np.abs(Drow - Dr) > 1e-9).sum()) + int(((~kept).astype(float) @ M != n_drop).sum()) + int((M.sum(0) != n_held).sum())
            tmin = np.array([w[ri == q].min() / 2 for q in range(E)])
            v3["rows_bad"] += int((np.abs(tmin - tau) > 1e-9).sum())
            for typ in ("N4.6", "N4.8"):
                key = f"{b}|{win}|{typ}"
                if key not in zdrops.files:
                    v3["notes"].append(f"missing {key}")
                    v3["bad"] += 1
                    continue
                A = zdrops[key].astype(np.int8)
                v3["keys"] += 1
                nd = A.shape[0]
                bad = A.shape[1] != R
                if bad:
                    v3["bad"] += nd
                    v3["notes"].append(f"{key} has {A.shape[1]} columns, event_stocks.csv {R} rows")
                    continue
                Dd = A.astype(float) @ Wm
                cn = A.astype(float) @ M
                if typ == "N4.6":
                    badm = (np.abs(Dd - Dr[None, :]) > tau[None, :] + 1e-9).any(1)
                    badm |= ((n_drop == 0)[None, :] & (cn != 0)).any(1)
                    badm |= ((n_drop == n_held)[None, :] & (cn != n_held[None, :])).any(1)
                    v3["tau_worst"] = max(v3["tau_worst"], float((np.abs(Dd - Dr[None, :]) / tau[None, :]).max()))
                else:
                    if key not in zlab.files:
                        v3["notes"].append(f"missing labels {key}")
                        v3["bad"] += nd
                        continue
                    L = zlab[key].astype(int)
                    badm = np.zeros(nd, bool)
                    for li, col in enumerate(("n_large", "n_mid", "n_small")):
                        badm |= (((L == li).astype(float) @ M) != e[col].values[None, :]).any(1)
                    sell = np.stack([(e[f"state_{s_}"].values == "SELL")[ri] for s_ in SIGS], axis=1)  # (R, 3)
                    expect = sell[np.arange(R)[None, :], L]
                    badm |= (expect != (A == 1)).any(1)
                    badm |= (L > 2).any(1)
                v3["draws"] += nd
                v3["bad"] += int(badm.sum())
                v3["n_bad_count"] += int(nd != a.expect_draws)
                gap = np.abs(Dd - Dr[None, :])
                GAP[(b, win, typ)] = {"mean_abs_gap": float(gap.mean()), "max_abs_gap": float(gap.max()), "max_gap_over_tau": float((gap / tau[None, :]).max()), "mean_D": float(Dd.mean()), "rule_mean_D": float(Dr.mean()),
                                      "sd_of_mean_D": float(Dd.mean(1).std(ddof=1)) if nd > 1 else 0.0}
                # draws.csv rows of this (book, window, type): ids and n_events
                for (cash, cost), g in dr[(dr.book == b) & (dr.window == win) & (dr.draw_type == typ)].groupby(["cash", "cost_bps"]):
                    ids = np.sort(g.draw_id.values)
                    v3["bad"] += int(len(g) != nd or (ids != np.arange(nd)).any() or (g.n_events != E).any())
                # seeded replay of N4.6 (the frozen sampler)
                if typ == "N4.6" and a.replay > 0:
                    isin = rows["isin"].values
                    prep = []
                    for q in range(E):
                        idx = np.flatnonzero(ri == q)
                        order = idx[np.argsort(isin[idx], kind="stable")]
                        prep.append((order, allowed_set(w[order], Dr[q], tau[q])))
                    for d_ in range(min(a.replay, nd)):
                        rg = np.random.default_rng([7, d_, BNO[b]])
                        u = rg.random(E)
                        got = np.zeros(R, np.int8)
                        for q, (order, al) in enumerate(prep):
                            m = int(al[int(math.floor(u[q] * len(al)))])
                            got[order] = [(m >> i) & 1 for i in range(len(order))]
                        v3["replayed"] += 1
                        v3["replay_bad"] += int((got != A[d_]).any())
    P(f"V3 the nulls hold their tables: {v3['draws']:,} saved draws checked over {v3['keys']} drop arrays (N4.6: dropped subset inside the held set, its listed weight within tau of the rule's, drop nothing / everything when the rule does; "
      f"N4.8: stocks per label equal the rule's n_large, n_mid, n_small at every event, and a stock is dropped iff its label's signal is SELL), bad {v3['bad']}; draws per array differing from the required {a.expect_draws:,}: {v3['n_bad_count']}; "
      f"events.csv against event_stocks.csv: {v3['rows']:,} events, {v3['rows_bad']} inconsistent {v3['notes'] or ''}")
    P(f"   worst |dropped weight - rule's| over every N4.6 draw and event, in units of tau: {v3['tau_worst']:.3f} (must be <= 1)")
    P(f"   N4.6 replayed from the seed [7, draw_id, book_no] (frozen sampler; bit i = stock i, ISIN order): {v3['replayed']:,} draws x events, {v3['replay_bad']} differ from draw_drops.npz")
    au_v3 = au.get("v3")
    eng_v3 = flags(au_v3) if au_v3 is not None else []
    if au_v3 is not None:
        bd_ = find_key(au_v3, {"bad", "violations"})
        P(f"   audit.json v3 block (the engine's own check): {len(eng_v3)} pass flags, all true: {all(eng_v3) and len(eng_v3) > 0}; its bad count: {bd_}")
        if bd_ not in (None, 0):
            v3["bad"] += 1
    gates["V3"] = v3["bad"] == 0 and v3["rows_bad"] == 0 and v3["n_bad_count"] == 0 and v3["draws"] > 0 and v3["replay_bad"] == 0 and (all(eng_v3) if eng_v3 else True)

    # V4
    P("V4 always-in at 0 cost vs the published NAV (G0: +-0.25 pp/yr overall, +-0.5 pp every calendar year):")
    table(g4, {"cagr_gap_pp_yr": lambda x: f"{x:+.3f}", "worst_year_gap_pp": lambda x: f"{x:+.3f}"})
    if "window_first" in g4:
        P("   (the always-in book runs over %s -> %s)" % (g4.window_first.iloc[0], g4.window_last.iloc[0]))
    g0_ok = bool((g4["overall"] == "PASS").all() and (g4["yearly"] == "PASS").all() and len(g4) >= len(BOOKS))
    reg = {"dec_compared": 0, "dec_bad": 0, "nav_compared": 0, "nav_bad": 0, "worst": 0.0, "ok": False}
    if (t06 / "decisions.csv").exists() and (t06 / "daily_nav.csv").exists():
        d6 = pd.read_csv(t06 / "decisions.csv")
        d6 = d6[d6.book.isin(BOOKS)]
        d6 = d6[d6.j < d6.groupby("book").j.transform("max")]  # the last decision of T06 (2026-10-22) is a truncated week; T07's calendar goes on
        d7 = dec[["book", "decision_date", "all_three_buy"]].copy()
        d7["all_three_buy"] = asbool(d7["all_three_buy"]).astype(int)
        mm = d6.merge(d7, on=["book", "decision_date"], how="left")
        reg["dec_compared"] = len(mm)
        reg["dec_bad"] = int(mm.all_three_buy_y.isna().sum() + (mm.state != mm.all_three_buy_y).sum())
        n6 = pd.read_csv(t06 / "daily_nav.csv", parse_dates=["date"])
        n6 = n6[n6.run.isin(["strategy", "hold_parent", "sleeve_only"]) & (n6.date <= V4_NAV_END) & n6.book.isin(BOOKS)].copy()
        n6["run"] = n6.run.map({"strategy": "whole_book", "hold_parent": "parent", "sleeve_only": "sleeve100"})
        mn = n6.merge(nav, on=["book", "date", "cost_bps", "run"], how="left", suffixes=("_t06", ""))
        rel = (mn.nav / mn.nav_t06 - 1).abs()
        reg["nav_compared"] = len(mn)
        reg["nav_bad"] = int((rel.isna() | (rel > 1e-12)).sum())
        reg["worst"] = float(rel.max())
        reg["ok"] = reg["dec_compared"] > 0 and reg["nav_compared"] > 0 and reg["dec_bad"] == 0 and reg["nav_bad"] == 0
        P(f"   regression to T06 on the overlap: decisions {reg['dec_compared']:,} compared (T06's all-three-BUY state against this run's), {reg['dec_bad']} differ; NAVs (whole-book switch = T06 strategy, parent = hold the parent, 100% sleeve; every cost; "
          f"up to {V4_NAV_END.date()}) {reg['nav_compared']:,} compared, {reg['nav_bad']} differ, worst relative difference {reg['worst']:.1e} (limit 1e-12)")
    else:
        P("   regression to T06: NOT RUN (T06's decisions.csv or daily_nav.csv not found in %s)" % t06)
    rj = ev_dir / "regression_t06.json"
    eng_v4 = []
    if rj.exists():
        rjd = json.loads(rj.read_text(encoding="utf-8"))
        eng_v4 = flags(rjd) + flags(rjd, "g0_pass")
        P(f"   regression_t06.json (the engine's own check): {len(eng_v4)} pass flags, all true: {all(eng_v4) and len(eng_v4) > 0}")
    gates["V4"] = g0_ok and reg["ok"] and (all(eng_v4) if eng_v4 else True)

    # V5: (a) the engine's chi-square, (b) brute-force count of allowed subsets at every event, (c) the rule's own subset is allowed
    sj = ev_dir / "sampler_selftest.json"
    chi_p, st_ok, chi_n = None, None, None
    if sj.exists():
        sjd = json.loads(sj.read_text(encoding="utf-8"))
        chi_p = find_key(sjd, {"p", "p_value", "pvalue", "chi2_p", "chi_p", "chi_square_p", "chi2_pvalue", "chisq_p", "p_chi2"})
        chi_n = find_key(sjd, {"draws", "n_draws", "samples", "n_samples"})
        fl = flags(sjd) + flags(sjd, "ok") + flags(sjd, "passed")
        st_ok = (all(fl) if fl else None)
        P(f"   sampler_selftest.json (the engine's own check): {len(fl)} pass flags, all true: {st_ok}; samples {chi_n}")
    cnt_bad = cnt_n = own_bad = 0
    ct_cmp = ct_bad = 0
    cnt_stats = {}
    for b in BOOKS:
        for win in ("full", "live"):
            rows, e = ES[(b, win)], EV[(b, win)]
            ri = ROWMAP[(b, win)]
            w = rows.listed_weight.values.astype(float)
            isin = rows["isin"].values
            kept = rows.kept_b.values
            al_counts = []
            for q in range(len(e)):
                idx = np.flatnonzero(ri == q)
                order = idx[np.argsort(isin[idx], kind="stable")]
                al = allowed_set(w[order], float(e.dropped_weight.iloc[q]), float(e.tau.iloc[q]))
                al_counts.append(len(al))
                cnt_n += 1
                cnt_bad += int(len(al) != int(e.n_allowed_subsets.iloc[q]))
                mask = int(sum(1 << i for i, r_ in enumerate(order) if not kept[r_]))
                own_bad += int(mask not in set(al.tolist()))
            cnt_stats[(b, win)] = np.array(al_counts)
            # count_table.json, if its shape is recognisable: a list of dicts with n_allowed_subsets under book/window
            ctb = ct.get("books") if isinstance(ct.get("books"), dict) else ct
            cb = ctb.get(b, {}).get(win) if isinstance(ctb.get(b), dict) else None
            lst = None
            if isinstance(cb, dict):
                lst = next((x for x in cb.values() if isinstance(x, list) and x and isinstance(x[0], dict) and "n_allowed_subsets" in x[0]), None)
            elif isinstance(cb, list) and cb and isinstance(cb[0], dict):
                lst = cb
            if lst is not None:
                ct_cmp += len(lst)
                if len(lst) != len(al_counts):
                    ct_bad += abs(len(lst) - len(al_counts))
                ct_bad += sum(int(str(x.get("n_allowed_subsets")) != str(al_counts[i])) for i, x in enumerate(lst[:len(al_counts)]))
    worstp = chi_p is not None and float(chi_p) > 0.001 and (st_ok is None or bool(st_ok)) and (chi_n is None or float(chi_n) >= 200000)
    P(f"V5 the sampler is exact: (a) chi-square on the small unequal-weight basket: p = {chi_p} (need > 0.001, 200,000 samples; from sampler_selftest.json, which this script cannot recompute); "
      f"(b) brute-force count of the allowed subsets (all 2^n, n <= 16, within tau of the rule's dropped weight) at {cnt_n} events against events.csv: {cnt_bad} differ; against count_table.json: "
      f"{ct_cmp} entries compared, {ct_bad} differ{'' if ct_cmp else ' (count_table.json shape not recognised, not compared)'}; (c) the rule's own drop set is among the allowed subsets at every event: {own_bad} are not")
    gates["V5"] = bool(worstp) and cnt_bad == 0 and own_bad == 0 and ct_bad == 0 and cnt_n > 0

    # V6 negative control
    nc = pd.read_csv(ev_dir / "controls_negative.csv") if (ev_dir / "controls_negative.csv").exists() else None
    v6rows, v6ok = [], nc is not None
    if nc is not None:
        for b in BOOKS:
            g = nc[nc.book == b]
            K = len(g)
            sh = float((g.percentile >= PASS_PCT).mean()) if K else float("nan")
            lo, hi = 0.0, v6_xmax(K) / max(K, 1)     # AMENDMENT 2026-11-12: one-sided, fail at xmax + 1 or more (K = 100: 18)
            agree = (not "pass90" in g) or bool((asbool(g["pass90"]) == (g.percentile.values >= PASS_PCT)).all())
            ok_b = K >= 100 and round(sh * K) <= v6_xmax(K) and agree
            v6rows.append({"book": b, "shifts": K, "share_pct>=90": f"{100 * sh:.1f}%", "allowed": f"[{100 * lo:.1f}%, {100 * hi:.1f}%]", "pass90 column agrees": agree, "within": ok_b})
            v6ok &= ok_b
    P("V6 negative control (100 circular shifts of the joint three-signal matrix, each judged against its own N4.6 null, 200 draws, 20.8 bps; AMENDED 2026-11-12 (T07.md 'Amendments before the run'): a book passes V6 if at most x_max of its K shifts reach CAGR percentile >= 90, x_max = the largest X with P(Binomial(K, 0.10) >= X) >= 0.05 / 4 (K = 100: 17; the frozen two-sided band [4%, 16%] is replaced):")
    if v6rows:
        table(pd.DataFrame(v6rows))
    else:
        P("   controls_negative.csv missing")
    gates["V6"] = bool(v6ok)
    if not v6ok:
        P("V6 FAILED (too many information-free signals reach the 90th percentile, or too few shifts were run, for: %s): by T07.md section 2 nothing below may be read; fix and rerun as a new run directory" % ([r_["book"] for r_ in v6rows if not r_["within"]] or "all books (file missing)"))

    # V7 oracle
    oj = ev_dir / "controls_oracle.json"
    v7rows, v7ok = [], oj.exists()
    if oj.exists():
        o = json.loads(oj.read_text(encoding="utf-8"))
        for b in BOOKS:
            d_ = per_book(o, b)
            cg = find_key(d_, {"cagr", "oracle_cagr", "after_cost_cagr"}) if d_ else None
            pc_ = find_key(d_, {"percentile", "pct", "oracle_percentile", "percentile_vs_n46", "pct_n46"}) if d_ else None
            own = rank(float(cg), D(b, "N4.6").cagr.values, True)["percentile"] if cg is not None else None
            use = own if own is not None else (float(pc_) if pc_ is not None else None)
            ok_b = use is not None and use >= 99.0 and (pc_ is None or own is None or abs(float(pc_) - own) < 1e-6)
            v7rows.append({"book": b, "oracle CAGR%": "" if cg is None else f"{100 * float(cg):.2f}", "percentile (stated)": pc_, "percentile (recomputed here)": None if own is None else round(own, 3), "need >= 99": ok_b})
            v7ok &= ok_b
    P("V7 positive control, the oracle (at each event the allowed subset with the lowest weight-times-realised-log-return; its CAGR percentile against N4.6, full window, 20.8 bps; at least 99 in every book):")
    if v7rows:
        table(pd.DataFrame(v7rows))
    else:
        P("   controls_oracle.json missing")
    gates["V7"] = bool(v7ok)
    P("Gates:", {k: ("PASS" if v else "FAIL") for k, v in gates.items()}, "->", "ALL PASS" if all(gates.values()) else "A GATE FAILED: NOTHING BELOW MAY BE READ")

    # reportability
    rep = {}
    for b in BOOKS:
        for win in ("full", "live"):
            d_ = rule_state[b]
            if win == "live":
                d_ = d_[pd.to_datetime(d_.decision_date) >= cal[b].iloc[live_i[b]]]
            x = asbool(d_["disagree"]).astype(int)
            n_st = int(((x[1:] == 1) & (x[:-1] == 0)).sum()) + int(len(x) and x[0] == 1)
            n_part = int(EV[(b, win)].partial_b.sum())
            rep[(b, win)] = {"weeks": len(x), "disagree_weeks": int(x.sum()), "stretches": n_st, "partial_events": n_part, "events": len(EV[(b, win)]), "ok": n_st >= 5 and n_part >= 6}
    P("Reportability (a realisation needs >= 5 separate disagreement stretches and >= 6 events with 0 < equity share < 1; frozen counts: 16 stretches full, 11 live; coarse upper bounds 26-27 and 16-17 events in disagreement weeks):")
    table(pd.DataFrame([{"book": b, "window": w, **v, "REPORTABLE": "yes" if v["ok"] else "NO: NOT REPORTABLE"} for (b, w), v in rep.items()]))
    notrep = [b for b in BOOKS if not rep[(b, "full")]["ok"]]
    P("NOT REPORTABLE (full window):", notrep or "none", "| NOT REPORTABLE (live window):", [b for b in BOOKS if not rep[(b, "live")]["ok"]] or "none")
    P("Allowed N4.6 subsets per event (brute force here; the null's spread is limited by them), full window:")
    cs = []
    for b in BOOKS:
        c_ = cnt_stats[(b, "full")]
        cs.append({"book": b, "events": len(c_), "events with 1 allowed subset": int((c_ == 1).sum()), "min": int(c_.min()), "median": float(np.median(c_)), "max": int(c_.max()), "log10(distinct draws)": float(np.log10(c_.astype(float)).sum())})
    table(pd.DataFrame(cs), {"median": lambda x: f"{x:.1f}", "log10(distinct draws)": lambda x: f"{x:.1f}"})
    one_ev = {b: int((cnt_stats[(b, "full")] == 1).sum()) for b in BOOKS}
    P("Events with exactly one allowed subset (the rule drops nothing or everything, or only one subset fits; N4.6 is random only at the other events), full window:", {b: f"{one_ev[b]} of {len(cnt_stats[(b, 'full')])}" for b in BOOKS})
    P("Dropped weight per event, null against rule (listed weights; N4.6 must lie within tau, N4.8 is not matched exactly; means over draws and events, full window):")
    P(pd.DataFrame([{"book": b, "null": t_, "rule mean D": GAP[(b, "full", t_)]["rule_mean_D"], "null mean D": GAP[(b, "full", t_)]["mean_D"], "mean |gap|": GAP[(b, "full", t_)]["mean_abs_gap"],
                     "max |gap|": GAP[(b, "full", t_)]["max_abs_gap"], "max gap / tau": GAP[(b, "full", t_)]["max_gap_over_tau"]} for b in BOOKS for t_ in ("N4.6", "N4.8") if (b, "full", t_) in GAP]).to_string(index=False, float_format=lambda x: f"{x:.4f}"))
    cashsrc = au.get("cash") or au.get("books", {}).get(BOOKS[0], {}).get("cash") if isinstance(au, dict) else None
    P("Cash:", cashsrc if cashsrc else "(not recorded in audit.json)")
    P("Readings recorded by the engine (audit.json 'readings'):")
    rd_ = au.get("readings") or []
    for r_ in (rd_.items() if isinstance(rd_, dict) else rd_):
        P("  -", (f"{r_[0]}: {r_[1]}" if isinstance(r_, tuple) else (r_ if isinstance(r_, str) else json.dumps(r_))))

    # ══ 4.0a the worked example ═══════════════════════════════════════════════
    head("4.0a  THE WORKED EXAMPLE (one rule: one real event of %s and one N4.6 draw, 20.8 bps)" % BOOKS[0])
    b = BOOKS[0]
    e = EV[(b, "full")]
    rows = ES[(b, "full")]
    cand = e[(e.event_no > 0) & e.partial_b]
    qx = int(cand.index[0]) if len(cand) else 0
    r = e.iloc[qx]
    P(f"One event: {b}, event {qx + 1} of {len(e)} (event_no {int(r.event_no)}, kind {r.kind}), trade session {r.trade_date} (index {int(r.trade_idx)}), information date {r.info_date} (the session before), basket in force: availableDate {r.basket_eff}.")
    dsel = rule_state[b][pd.to_datetime(rule_state[b].decision_date) <= pd.Timestamp(r.info_date)].iloc[-1]
    P(f"Its signals: the latest decision made before the trade session is week {int(dsel.j)}, decision date {dsel.decision_date}: Nifty100 {dsel.sign_Nifty100} (Master row {dsel.label_Nifty100}), MC100 {dsel.sign_MC100} ({dsel.label_MC100}), "
      f"SC100 {dsel.sign_SC100} ({dsel.label_SC100}); the event's states: {r.state_Nifty100}, {r.state_MC100}, {r.state_SC100}; agree: {[dsel.sign_Nifty100, dsel.sign_MC100, dsel.sign_SC100] == [r.state_Nifty100, r.state_MC100, r.state_SC100]}.")
    qr = rows[rows.event_no == r.event_no].reset_index(drop=True)
    tbl = qr[["stock", "isin", "listed_weight", "band", "tag_source", "tag_snapshot", "tag_detail", "tag_via", "band_signal", "kept_b"]].rename(columns={"kept_b": "kept"})
    P("The tag of every held stock as of the information date (band of the stock's index signal on or off):")
    table(tbl, {"listed_weight": lambda x: f"{x:.5f}"})
    sw, Dd0 = float(qr.listed_weight.sum()), float(qr.listed_weight[~qr.kept_b].sum())
    s_ = Dd0 / sw
    P(f"Targets (T07.md section 3 step 6): sum of listed weights {sw:.6f}; dropped weight D = {Dd0:.6f}; s = D / sum = {s_:.6f}; kept stock i gets V x w_i; GOLDBEES and cash units each get V x s / 2 = V x {s_ / 2:.6f}; "
      f"V (before cost) {r.V_before:.6f}, traded {r.traded:.6f}, cost = traded x 20.8 / 2 / 10,000 = {r.cost:.6f} (recomputed {r.traded * PRIMARY / 2 / 10000:.6f}); events.csv: D {r.dropped_weight:.6f}, s {r.sleeve_share_s:.6f}, "
      f"n_held {int(r.n_held)}, n_dropped {int(r.n_dropped)}, partial {bool(r.partial_b)}.")
    P(f"N4.6 for this event: tau = half the smallest listed weight = {r.tau:.6f}; the allowed subsets are those whose listed weight is within tau of D: {int(r.n_allowed_subsets)} of 2^{int(r.n_held)} = {2 ** int(r.n_held)}.")
    A0 = zdrops[f"{b}|full|N4.6"].astype(int)
    ri0 = ROWMAP[(b, "full")]
    idx = np.flatnonzero(ri0 == qx)
    isin_ = rows["isin"].values
    order = idx[np.argsort(isin_[idx], kind="stable")]
    al = allowed_set(rows.listed_weight.values[order].astype(float), float(r.dropped_weight), float(r.tau))
    rg = np.random.default_rng([7, 0, BNO[b]])
    u = float(rg.random(len(e))[qx])
    m = int(al[int(math.floor(u * len(al)))])
    got = np.array([(m >> i) & 1 for i in range(len(order))])
    stored = A0[0, order]
    P(f"One N4.6 draw (draw_id 0, seed numpy default_rng([7, 0, {BNO[b]}]), uniform number {qx + 1} of {len(e)} since there is one per event): u = {u:.6f}; index floor(u x {len(al)}) = {int(math.floor(u * len(al)))}; bitmask {m} "
      f"(bit i = stock i in ISIN order); it drops {[rows.stock.values[order[i]] for i in range(len(order)) if got[i]]} with listed weight {float(rows.listed_weight.values[order] @ got):.6f} "
      f"(the rule drops {[rows.stock.values[order[i]] for i in range(len(order)) if not rows.kept_b.values[order[i]]]}, weight {Dd0:.6f}; gap within tau: {abs(float(rows.listed_weight.values[order] @ got) - Dd0) <= float(r.tau) + 1e-12}); "
      f"stored draw 0 equals this replay: {bool((got == stored).all())}")
    s0 = S(b)
    nv = nav[(nav.book == b) & (nav.cost_bps == PRIMARY) & (nav.run == "segment")].sort_values("date").reset_index(drop=True)
    k = int(nv.index[nv.date == pd.Timestamp(r.trade_date)][0])
    P("NAV around the trade (rule, 20.8 bps; whole-book switch beside it):")
    nw = nav[(nav.book == b) & (nav.cost_bps == PRIMARY) & (nav.run == "whole_book")].sort_values("date").reset_index(drop=True)
    table(pd.DataFrame({"date": nv.date.dt.date.iloc[k - 2:k + 3], "rule": nv.nav.iloc[k - 2:k + 3], "whole_book": nw.nav.iloc[k - 2:k + 3]}), {"rule": lambda x: f"{x:.6f}", "whole_book": lambda x: f"{x:.6f}"})
    P(f"One path: start 1.000000 on {nv.date.iloc[0].date()}, end {s0.end_nav:.6f} on {nv.date.iloc[-1].date()}, {int(s0.sessions)} sessions -> years {(s0.sessions - 1) / 252:.4f}, CAGR {100 * s0.cagr:.3f}%, max drawdown {100 * s0.max_dd:.2f}%")
    for nm, typ in NULLS:
        n_ = D(b, typ)
        x0 = n_[n_.draw_id == 0].iloc[0]
        rk = rank(s0.cagr, n_.cagr.values, True)
        P(f"  {typ} draw 0: CAGR {100 * x0.cagr:.3f}%, max drawdown {100 * x0.max_dd:.2f}%, trades {int(x0.trades)} (rule {int(s0.trades)}), cost paid {x0.cost_paid:.4f} (rule {s0.cost_paid:.4f})")
        P(f"  One ranking against {typ} (CAGR, {rk['draws']} draws): below {rk['worse']}, equal {rk['tied']}, above {rk['better']} -> percentile {rk['percentile']:.2f}, p-value {rk['p']:.5f}; "
          f"null median {100 * n_.cagr.median():.2f}%, edge {100 * (s0.cagr - n_.cagr.median()):+.2f} pp")

    # ══ 4.1 headline ═════════════════════════════════════════════════════════
    head(f"4.1  HEADLINE: the rule against N4.6 (deciding) and N4.8 (full window 2019 -> 2026-10-30, LBES cash; {ndraws:,} draws each) and against the whole-book switch")
    rows_ = []
    for cost in COSTS:
        for b in BOOKS:
            s = S(b, cost=cost)
            row = {"cost": cost, "book": b, "CAGR%": 100 * s.cagr, "maxDD%": 100 * s.max_dd}
            for nm, typ in NULLS:
                n = D(b, typ, cost)
                rc, rd = rank(s.cagr, n.cagr.values, True), rank(s.max_dd, n.max_dd.values, True)
                row.update({f"{nm}_med%": 100 * n.cagr.median(), f"{nm}_edge_pp": 100 * (s.cagr - n.cagr.median()), f"{nm}_pct": rc["percentile"], f"{nm}_p": rc["p"],
                            f"{nm}_medDD%": 100 * n.max_dd.median(), f"{nm}_DD_pct": rd["percentile"], f"{nm}_DD_p": rd["p"]})
            rows_.append(row)
    H = pd.DataFrame(rows_)
    f2 = lambda x: f"{x:.2f}"
    P("CAGR (C1): the rule's after-cost CAGR, each null's median, the edge over it, the rule's percentile and p-value")
    table(H[["cost", "book", "CAGR%", "N46_med%", "N46_edge_pp", "N46_pct", "N46_p", "N48_med%", "N48_edge_pp", "N48_pct", "N48_p"]],
          {"CAGR%": f2, "N46_med%": f2, "N46_edge_pp": lambda x: f"{x:+.2f}", "N46_pct": f2, "N46_p": lambda x: f"{x:.5f}", "N48_med%": f2, "N48_edge_pp": lambda x: f"{x:+.2f}", "N48_pct": f2, "N48_p": lambda x: f"{x:.5f}"})
    P("Maximum drawdown (C2): the rule's worst fall, each null's median, the rule's percentile (shallower is better) and p-value")
    table(H[["cost", "book", "maxDD%", "N46_medDD%", "N46_DD_pct", "N46_DD_p", "N48_medDD%", "N48_DD_pct", "N48_DD_p"]],
          {"maxDD%": f2, "N46_medDD%": f2, "N46_DD_pct": f2, "N46_DD_p": lambda x: f"{x:.5f}", "N48_medDD%": f2, "N48_DD_pct": f2, "N48_DD_p": lambda x: f"{x:.5f}"})
    P("N46 = N4.6 size-matched random exclusion (decides); N48 = N4.8 persistent label permutation (beside it). pct = percentile of the rule among the draws; DD = maximum drawdown.")
    P("\nSecondary statistics at 20.8 bps, percentile against each null's draws (each statistic's better direction: higher for CAGR, maximum drawdown and Calmar; lower for volatility, Ulcer index, days >= 10% below the peak, longest time under water):")
    for nm, typ in NULLS:
        sec = []
        for b in BOOKS:
            s, n = S(b), D(b, typ)
            sec.append({"book": b, **{k_: rank(s[k_], n[k_].values, hb)["percentile"] for k_, hb in HIGHER_BETTER.items()}})
        P(f"  against {typ}:")
        table(pd.DataFrame(sec), {k_: (lambda x: f"{x:.1f}") for k_ in HIGHER_BETTER})
    # C3
    P("\nC3: the rule minus the whole-book switch, after cost, full window (percentage points a year); SE from a moving-block bootstrap (blocks of 20 sessions, 1,000 resamples, seed default_rng([10, book_no])) of the paired daily returns:")
    c3 = []
    SE = {}
    for cost in COSTS:
        for b in BOOKS:
            sr, sw_ = S(b, cost=cost), S(b, "whole_book", cost)
            row = {"cost": cost, "book": b, "rule CAGR%": 100 * sr.cagr, "whole-book CAGR%": 100 * sw_.cagr, "diff pp": 100 * (sr.cagr - sw_.cagr)}
            if cost == PRIMARY:
                vr = nav[(nav.book == b) & (nav.cost_bps == cost) & (nav.run == "segment")].sort_values("date").nav.values
                vw = nav[(nav.book == b) & (nav.cost_bps == cost) & (nav.run == "whole_book")].sort_values("date").nav.values
                SE[b] = mbb_se(vr, vw, [10, BNO.get(b, BOOKS.index(b))])
                row.update({"SE pp": 100 * SE[b], "diff / SE": (sr.cagr - sw_.cagr) / SE[b]})
            c3.append(row)
    C3 = pd.DataFrame(c3)
    table(C3, {c: (lambda x: f"{x:.2f}") for c in C3.columns if c not in ("cost", "book")})

    # ══ 4.2 comparators ══════════════════════════════════════════════════════
    head("4.2  COMPARATORS (benchmarks, not nulls), same window, T0 = 1.000; weight by band; tag sources")
    comp = []
    for cost in COSTS:
        for b in BOOKS:
            row = {"cost": cost, "book": b}
            for kind in ("segment", "whole_book", "parent", "constant_mix", "sleeve100"):
                s = S(b, kind, cost)
                row[f"{kind}_CAGR%"], row[f"{kind}_DD%"] = 100 * s.cagr, 100 * s.max_dd
            if cost == PRIMARY:
                s = S(b, "published_parent", 0.0) if len(st[(st.book == b) & (st.kind == "published_parent") & (st.cost_bps == 0.0)]) else st[(st.book == b) & (st.kind == "published_parent")].iloc[0]
                row["published_CAGR%"], row["published_DD%"] = 100 * s.cagr, 100 * s.max_dd
            comp.append(row)
    Cm = pd.DataFrame(comp)
    table(Cm, {c: (lambda x: f"{x:.2f}") for c in Cm.columns if c.endswith("%")})
    P("whole_book = every stock follows the single state IN iff all three signals are BUY (T06's strategy); parent = hold every stock (the engine); constant_mix = the rule's average share of NAV in the parent's stocks held all the time, rebalanced at each event; "
      "sleeve100 = 50/50 GOLDBEES and cash; published = the published NAV (D17) rebased to 1.000 (no cost).")
    P("\nTrades, events and cost paid (full window, LBES cash; the null's median draw beside the rule; the null redraws at every event so its turnover can differ):")
    tr_rows = []
    for cost in COSTS:
        for b in BOOKS:
            sr, sw_ = S(b, cost=cost), S(b, "whole_book", cost)
            row = {"cost": cost, "book": b, "rule trades": int(sr.trades), "rule cost paid": sr.cost_paid, "whole-book trades": int(sw_.trades), "whole-book cost paid": sw_.cost_paid}
            for nm, typ in NULLS:
                n = D(b, typ, cost)
                row.update({f"{nm} median trades": float(n.trades.median()), f"{nm} median cost paid": float(n.cost_paid.median()), f"{nm} trades / rule": float(n.trades.median()) / max(float(sr.trades), 1)})
            tr_rows.append(row)
    table(pd.DataFrame(tr_rows), {c: (lambda x: f"{x:.4f}") for c in ("rule cost paid", "whole-book cost paid", "N46 median cost paid", "N48 median cost paid")} | {c: (lambda x: f"{x:.2f}") for c in ("N46 median trades", "N48 median trades", "N46 trades / rule", "N48 trades / rule")})

    P("\nWeight by band, full window: mean listed weight of each band over the events (event-weighted) and over sessions (each event's weights held until the next event; the last until the last session); "
      "mean share of the book kept (not sent to the sleeve) and mean share dropped from each band, session-weighted:")
    wb = []
    for b in BOOKS:
        e, rows = EV[(b, "full")], ES[(b, "full")]
        ri = ROWMAP[(b, "full")]
        tidx = e.trade_idx.values.astype(int)
        span = np.diff(np.append(tidx, nses[b] - 1)).astype(float)
        span = np.where(span <= 0, 0.0, span)
        w = rows.listed_weight.values.astype(float)
        bandw = np.zeros((len(e), 3))
        dropw = np.zeros((len(e), 3))
        for bi, bn in enumerate(BANDS):
            sel = (rows.band.values == bn)
            bandw[:, bi] = np.bincount(ri[sel], weights=w[sel], minlength=len(e))
            seld = sel & ~rows.kept_b.values
            dropw[:, bi] = np.bincount(ri[seld], weights=w[seld], minlength=len(e))
        tot = bandw.sum(1, keepdims=True)
        ew, sw2 = (bandw / tot).mean(0), ((bandw / tot) * span[:, None]).sum(0) / span.sum()
        dsh = ((dropw / tot) * span[:, None]).sum(0) / span.sum()
        row = {"book": b}
        for bi, bn in enumerate(BANDS):
            row[f"{bn} event-wtd %"], row[f"{bn} session-wtd %"], row[f"{bn} dropped %"] = 100 * ew[bi], 100 * sw2[bi], 100 * dsh[bi]
        row["kept %"] = 100 * (1 - dsh.sum())
        wb.append(row)
    table(pd.DataFrame(wb), {c: (lambda x: f"{x:.1f}") for c in pd.DataFrame(wb).columns if c != "book"})
    P("\nTag source of the exposure (share of listed weight x sessions by the source of the tag; rank = market-cap rank before 2026-04-09, membership = real index membership from then, nonmember_rank = rank fallback for a stock in none of the four indices, unranked = Small and below by default):")
    ts = []
    for b in BOOKS:
        e, rows = EV[(b, "full")], ES[(b, "full")]
        ri = ROWMAP[(b, "full")]
        span = np.diff(np.append(e.trade_idx.values.astype(int), nses[b] - 1)).astype(float)
        wt = rows.listed_weight.values * span[ri]
        row = {"book": b}
        for src in ("rank", "membership", "nonmember_rank", "unranked"):
            row[src + " %"] = 100 * wt[rows.tag_source.values == src].sum() / wt.sum()
        row["event-rows"] = len(rows)
        ts.append(row)
    table(pd.DataFrame(ts), {c: (lambda x: f"{x:.1f}") for c in ("rank %", "membership %", "nonmember_rank %", "unranked %")})

    # ══ 4.3 power ════════════════════════════════════════════════════════════
    head("4.3  POWER: the minimum detectable edge (MDE = 2.8 x null SD; 80% power, two-sided 5%) per null, the calibration ratio, the null spreads and the trades")
    mde, spread, calib = [], [], []
    for b in BOOKS:
        row = {"book": b, "stretches": rep[(b, "full")]["stretches"], "partial events": rep[(b, "full")]["partial_events"]}
        for nm, typ in NULLS:
            n = D(b, typ)
            row.update({f"{nm}_sd_CAGR_pp": 100 * n.cagr.std(), f"{nm}_MDE_CAGR_pp": 280 * n.cagr.std(), f"{nm}_sd_DD_pp": 100 * n.max_dd.std(), f"{nm}_MDE_DD_pp": 280 * n.max_dd.std()})
            q = np.percentile(n.cagr.values, [5, 95])
            sr = S(b)
            ratio = float(n.cagr.std()) / SE[b]
            zz = NormalDist().inv_cdf(min(max(rank(sr.cagr, n.cagr.values, True)["percentile"] / 100, 1e-6), 1 - 1e-6)) * ratio
            calib.append({"book": b, "null": typ, "null SD CAGR pp": 100 * n.cagr.std(), "SE of rule - whole-book pp": 100 * SE[b], "calibration ratio": ratio, "percentile": rank(sr.cagr, n.cagr.values, True)["percentile"],
                          "percentile at the ratio (z x ratio)": 100 * NormalDist().cdf(zz)})
            spread.append({"book": b, "null": typ, "min%": 100 * n.cagr.min(), "p5%": 100 * q[0], "median%": 100 * n.cagr.median(), "p95%": 100 * q[1], "max%": 100 * n.cagr.max(), "SD pp": 100 * n.cagr.std(),
                           "DD p5%": 100 * np.percentile(n.max_dd.values, 5), "DD median%": 100 * n.max_dd.median(), "DD p95%": 100 * np.percentile(n.max_dd.values, 95), "DD SD pp": 100 * n.max_dd.std()})
        mde.append(row)
    M_ = pd.DataFrame(mde)
    table(M_, {c: (lambda x: f"{x:.2f}") for c in M_.columns if c.endswith("_pp")})
    P("Null spreads of after-cost CAGR and maximum drawdown (20.8 bps, full window):")
    table(pd.DataFrame(spread), {c: (lambda x: f"{x:.2f}") for c in pd.DataFrame(spread).columns if c not in ("book", "null")})
    P("Calibration ratio (T07.md section 2; diagnostic, no pass mark): SD of the null's after-cost CAGR / SE of the rule's CAGR minus the whole-book switch's (moving-block bootstrap). "
      "Below 1 the null is calmer than reality's own noise about the increment, and the percentile overstates the distance from the null (z x ratio, AGENT.md N6.6):")
    table(pd.DataFrame(calib), {c: (lambda x: f"{x:.2f}") for c in ("null SD CAGR pp", "SE of rule - whole-book pp", "calibration ratio", "percentile", "percentile at the ratio (z x ratio)")})
    P("T07.md section 3 step 13: the thresholds in section 2 do not depend on these numbers, which did not exist when it was written. The planted-effect control is not run (section 2).")

    # ══ 4.4 verdict ══════════════════════════════════════════════════════════
    head("4.4  VERDICT against the pre-registered criteria (after cost, 20.8 bps; N4.6 decides; a NOT REPORTABLE book cannot pass)")
    hp = H[H.cost == PRIMARY].set_index("book")
    okb = {b: rep[(b, "full")]["ok"] for b in BOOKS}
    c1n = {nm: int(sum(hp.loc[b, f"{nm}_pct"] >= PASS_PCT and okb[b] for b in BOOKS)) for nm, _ in NULLS}
    c2n = {nm: int(sum(hp.loc[b, f"{nm}_DD_pct"] >= PASS_PCT and okb[b] for b in BOOKS)) for nm, _ in NULLS}
    c3b = {b: float(S(b).cagr - S(b, "whole_book").cagr) for b in BOOKS}
    c3n = int(sum(c3b[b] > 0 and okb[b] for b in BOOKS))
    mdeb = M_.set_index("book")

    def mdetxt(col):
        return "; ".join(f"{b}: undetectable below {mdeb.loc[b, col]:.1f} pp" for b in BOOKS)

    def lst(nm, col):
        return ", ".join("%s %.1f" % (b[-4:], hp.loc[b, f"{nm}_{col}"]) for b in BOOKS)

    for nm, typ in (("N46", "N4.6 (decides)"), ("N48", "N4.8 (beside, not a criterion)")):
        P(f"Against {typ}:")
        for name, n_, col, mc in (("C1 selection (H1)", c1n[nm], "pct", f"{nm}_MDE_CAGR_pp"), ("C2 protection (H2)", c2n[nm], "DD_pct", f"{nm}_MDE_DD_pp")):
            ok = n_ >= 3
            P(f"  {name:20s} {'PASS' if ok else 'FAIL'}   percentile >= {PASS_PCT:.0f} in >= 3 of 4 books: {n_} of 4 ({lst(nm, col)})   {('MDE: ' + mdetxt(mc)) if not ok else ''}")
    P(f"C3 increment (H3)    {'PASS' if c3n >= 3 else 'FAIL'}   rule minus whole-book switch > 0 in >= 3 of 4 books: {c3n} of 4 ({', '.join('%s %+.2f pp' % (b[-4:], 100 * c3b[b]) for b in BOOKS)})")
    c1, c2, c3p = c1n["N46"] >= 3, c2n["N46"] >= 3, c3n >= 3
    agree48 = (c1n["N48"] >= 3) == c1
    P("\nOutcome map (T07.md section 2), rows that apply:")
    hits = []
    if c1 and c2 and c3p and c1n["N48"] >= 3:
        hits.append("C1, C2 and C3 PASS and N4.8 agrees: segment tagging chooses what to drop better than chance and improves on the whole-book switch")
    elif c1 and c2 and c3p:
        hits.append("C1, C2 and C3 PASS under N4.6 but N4.8 does not pass C1 (not a row of the map): the nulls disagree; report both (AGENT.md N6.8)")
    if c3p and not c1:
        hits.append("C3 PASS, C1 FAIL: the gain over the whole-book switch is not specific to which stocks were dropped (a random drop of the same weight does as well): the benefit is partial de-risking, not the tag")
    if c1 and not c3p:
        hits.append("C1 PASS, C3 FAIL: the tag picks better than chance but not enough to beat the whole-book switch")
    if not c1 and not c3p:
        hits.append("C1 and C3 FAIL: Study 3's rejection stands on a matched null")
    if c1 and c3p and not c2:
        hits.append("C1 and C3 PASS, C2 FAIL (not a row of the map): selection and increment without the worst fall being shallower than the null's")
    if not agree48:
        hits.append("N4.6 and N4.8 disagree on C1: both are reported in the verdict and the finding's status note says so (T07.md section 2)")
    if notrep:
        hits.append(f"a realisation is NOT REPORTABLE ({notrep}): stated; the other books are read on their own")
    if not all(gates.values()):
        hits = ["a V gate fails: nothing is read. Fix and rerun as a new run directory"]
    for h_ in hits:
        P("  -", h_)

    # ══ 4.5 robustness ═══════════════════════════════════════════════════════
    head("4.5  ROBUSTNESS R1-R6 (decide a finding's status, not the verdicts)")
    for cost in (0.0, 50.0):
        hc = H[H.cost == cost]
        for nm, typ in NULLS:
            n1 = int((hc[f"{nm}_pct"] >= PASS_PCT).sum())
            n2 = int((hc[f"{nm}_DD_pct"] >= PASS_PCT).sum())
            P(f"R1 at {cost:g} bps against {typ}: C1 {n1} of 4 -> {'PASS' if n1 >= 3 else 'FAIL'} ({', '.join('%s %.1f' % (bb[-4:], x) for bb, x in zip(hc.book, hc[f'{nm}_pct']))}); "
              f"C2 {n2} of 4 -> {'PASS' if n2 >= 3 else 'FAIL'} ({', '.join('%s %.1f' % (bb[-4:], x) for bb, x in zip(hc.book, hc[f'{nm}_DD_pct']))})")
    P("R1 trades and cost paid are in the table of section 4.2 (rule, whole-book switch, and each null's median draw, at 0, 20.8 and 50 bps).")
    # R2 live
    for nm, typ in NULLS:
        pc_, pd_, c3l, extra = [], [], [], []
        for b in BOOKS:
            s = st[(st.book == b) & (st.window == "live") & (st.cash == "lbes") & (st.cost_bps == PRIMARY) & (st.kind == "segment")]
            sw_ = st[(st.book == b) & (st.window == "live") & (st.cash == "lbes") & (st.cost_bps == PRIMARY) & (st.kind == "whole_book")]
            n = D(b, typ, win="live")
            if len(s) and len(n):
                pc_.append(float(rank(s.iloc[0].cagr, n.cagr.values, True)["percentile"]) if rep[(b, "live")]["ok"] else float("nan"))
                pd_.append(float(rank(s.iloc[0].max_dd, n.max_dd.values, True)["percentile"]) if rep[(b, "live")]["ok"] else float("nan"))
                c3l.append(float(s.iloc[0].cagr - sw_.iloc[0].cagr) if len(sw_) else float("nan"))
                extra.append(f"{100 * s.iloc[0].cagr:.1f}%")
        n1, n2 = sum(x >= PASS_PCT for x in pc_), sum(x >= PASS_PCT for x in pd_)
        n3 = sum(x > 0 for x in c3l)
        P(f"R2 live window {LIVE_START} -> 2026-10-30 (own events and null, 20.8 bps), {typ}: C1 percentiles {[round(x, 1) for x in pc_]} (rule's CAGR {extra}) -> {n1} of {len(pc_)} >= {PASS_PCT:.0f} -> {'PASS' if n1 >= 3 else 'FAIL'}; "
          f"C2 percentiles {[round(x, 1) for x in pd_]} -> {n2} of {len(pd_)} -> {'PASS' if n2 >= 3 else 'FAIL'}"
          + (f"; C3 (rule minus whole-book, pp) {[round(100 * x, 2) for x in c3l]} -> {n3} of {len(c3l)} > 0 -> {'PASS' if n3 >= 3 else 'FAIL'}" if nm == "N46" else ""))
    P("   (a book whose live realisation is NOT REPORTABLE shows nan: %s)" % ([b for b in BOOKS if not rep[(b, 'live')]['ok']] or "none"))
    # R3 liq
    for nm, typ in NULLS:
        pcts, extra = [], []
        for b in BOOKS:
            s = st[(st.book == b) & (st.window == "full") & (st.cash == "liq") & (st.cost_bps == PRIMARY) & (st.kind == "segment")]
            n = D(b, typ, cash="liq")
            if len(s) and len(n):
                pcts.append(float(rank(s.iloc[0].cagr, n.cagr.values, True)["percentile"]))
                extra.append(f"{100 * s.iloc[0].cagr:.1f}%")
        n_ = sum(x >= PASS_PCT for x in pcts)
        P(f"R3 LIQUIDCASE as the cash leg (full window, 20.8 bps), {typ}: C1 percentiles {[round(x, 1) for x in pcts]} (rule's CAGR {extra}) -> {n_} of {len(pcts)} >= {PASS_PCT:.0f} -> {'PASS' if n_ >= 3 else 'FAIL'}")
    # R4
    P("\nR4 agreement of the two nulls (20.8 bps, full window; no pass mark). Per book: the rule's percentile under each null, each null's median, SD, 5th and 95th percentile of after-cost CAGR, and the ratio of the null's median trades to the rule's:")
    r4 = []
    for b in BOOKS:
        s = S(b)
        row = {"book": b, "CAGR%": 100 * s.cagr}
        for nm, typ in NULLS:
            n = D(b, typ)
            q = np.percentile(n.cagr.values, [5, 95])
            row.update({f"{nm}_pct": rank(s.cagr, n.cagr.values, True)["percentile"], f"{nm}_DD_pct": rank(s.max_dd, n.max_dd.values, True)["percentile"], f"{nm}_median%": 100 * n.cagr.median(),
                        f"{nm}_sd_pp": 100 * n.cagr.std(), f"{nm}_p5%": 100 * q[0], f"{nm}_p95%": 100 * q[1], f"{nm}_trades/rule": float(n.trades.median()) / max(float(s.trades), 1)})
        row["pct_gap(N48-N46)"] = row["N48_pct"] - row["N46_pct"]
        r4.append(row)
    R4 = pd.DataFrame(r4)
    table(R4, {c: (lambda x: f"{x:.2f}") for c in R4.columns if c != "book"})
    # R5
    P("\nR5 tag error (500 draws per book, 20.8 bps; each rank-rule tag replaced with probability 7.93% at every event, membership tags untouched; no pass mark): the rule's CAGR minus the whole-book switch's:")
    r5 = pd.read_csv(ev_dir / "r5_tag_error.csv") if (ev_dir / "r5_tag_error.csv").exists() else None
    if r5 is not None:
        r5rows = []
        for b in BOOKS:
            g = r5[r5.book == b].diff_vs_whole_book.values
            r5rows.append({"book": b, "draws": len(g), "unperturbed diff pp": 100 * c3b[b], "mean pp": 100 * g.mean(), "p5 pp": 100 * np.percentile(g, 5), "median pp": 100 * np.median(g), "p95 pp": 100 * np.percentile(g, 95),
                           "share of draws > 0": float((g > 0).mean())})
        table(pd.DataFrame(r5rows), {c: (lambda x: f"{x:.2f}") for c in ("unperturbed diff pp", "mean pp", "p5 pp", "median pp", "p95 pp", "share of draws > 0")})
    else:
        P("  r5_tag_error.csv missing")
    # R6
    P("\nR6 context (descriptive, no test): the published AA books (D15; they run other rules) against the rule and the whole-book switch on the live window (same sessions, 20.8 bps, CAGR = (end / start)^(252 / (sessions - 1)) - 1):")
    appr = [r_ for r_ in approved_rows() if r_["status"] == "APPROVED"]
    r6 = []
    for b in BOOKS:
        fil = [r_ for r_ in appr if r_["id"] == "D15" and r_["file"].replace("\\", "/").endswith(f"/{AABOOK.get(b, '')}.csv")]
        row = {"parent": b, "AA book": AABOOK.get(b)}
        sr, sw_ = (st[(st.book == b) & (st.window == "live") & (st.cash == "lbes") & (st.cost_bps == PRIMARY) & (st.kind == k_)] for k_ in ("segment", "whole_book"))
        row["rule live CAGR%"] = 100 * sr.iloc[0].cagr if len(sr) else float("nan")
        row["whole-book live CAGR%"] = 100 * sw_.iloc[0].cagr if len(sw_) else float("nan")
        if len(fil):
            raw = pd.read_csv(AA / fil[0]["file"])
            raw["d"] = pd.to_datetime(raw["_id.date"], format="%Y/%m/%d")
            raw = raw.sort_values("d")
            lo, hi = cal[b].iloc[live_i[b]], cal[b].iloc[-1]
            sub = raw[(raw.d >= lo) & (raw.d <= hi)]
            row["AA book live CAGR%"] = 100 * stats_from_nav(sub["index"].values / sub["index"].values[0])["cagr"]
            row["AA sessions"] = len(sub)
            row["rule sessions"] = int(sr.iloc[0].sessions) if len(sr) else None
            row["AA through"] = str(sub.d.iloc[-1].date())
        r6.append(row)
    table(pd.DataFrame(r6), {c: (lambda x: f"{x:.2f}") for c in ("rule live CAGR%", "whole-book live CAGR%", "AA book live CAGR%")})
    P("\nHypotheses: H1 (selection)", "SUPPORTED in-sample against N4.6 (PROVISIONAL: nothing is unseen)" if c1 else "FALSIFIED against N4.6",
      "| H2 (protection)", "SUPPORTED in-sample against N4.6 (PROVISIONAL)" if c2 else "FALSIFIED against N4.6", "| H3 (increment)", "SUPPORTED in-sample (PROVISIONAL)" if c3p else "FALSIFIED")
    P("Gates:", "all pass" if all(gates.values()) else "A GATE FAILED")
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "analysis.log").write_text(out.getvalue(), encoding="utf-8")
    print("wrote", outdir / "analysis.log")
    sys.exit(0 if (all(gates.values()) and v3["draws"] > 0) else 1)


if __name__ == "__main__":
    main()
