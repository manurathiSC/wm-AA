"""T12 analysis: reads only the shipped evidence in evidence/<run>/ and prints section 4 of the write-up.

    python tests/T12/analyse.py [--run headline]            prints to stdout and writes tests/T12/analysis.log
    python tests/T12/analyse.py --evidence DIR [--out DIR]  point at another evidence directory (e.g. a synthetic one);
                                                            analysis.log then goes to --out (default: DIR itself), never to tests/T12

Fork of tests/T07/analyse.py (copied, not imported). Imports nothing from the engine, the verifier or tag_lookup.py.
Percentile = (worse + 0.5 * tied) / draws * 100; p-value = (1 + at least as good) / (draws + 1); ties are equal within a relative 1e-12 (T12.md section 2).
N4.6 decides C1, C2; N4.8 is shown beside it; C3 is the rule minus the whole-book switch.
Windows (evidence contract point 1): full = 2014-09-01 -> 2019-01-02; r2 = the sub-window from the first D26 session on or after 2015-01-02 (R2);
full_r6 = the full window for SCMO_0007 and SCMO_0010 with the two unranked holdings tagged by their other listing (R6).
Exits non-zero if a validity gate (V1-V7) failed or if nothing was compared.

Gates V3, V5 and V6/V7 are re-derived here from the evidence files themselves (draw_drops.npz, draw_labels.npz, event_stocks.csv, events.csv,
controls_*.csv/json); V4 is read from regression.json (v4a, v4b, v4c, v4d; there is no published NAV before 2019, so there is no G0); the engine's own
json files are printed and, where a clear verdict key exists, must agree. The sampler is replayed from its seed ([15, 7, draw_id, book_no], one rng.random()
per event, allowed subsets by increasing bitmask over the held stocks in increasing ISIN order, bit i = stock i) for the first --replay draws of every book
and window, as an independent check of V3.
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
R6_BOOKS = ["SCMO_0007", "SCMO_0010"]
PRIMARY = 20.8
COSTS = (0.0, PRIMARY, 50.0)
PASS_PCT = 90.0
T0_DATE, END_DATE, R2_START = "2014-09-01", "2019-01-02", "2015-01-02"
SEED = 15          # first element of every seed in T12 (T12.md section 3 steps 11-12)
V6_XMAX_FROZEN = 17  # T12.md section 2, V6: at most 17 of 100


def v6_xmax(K: int, p: float = 0.10, alpha: float = 0.05 / 4) -> int:
    """Largest X with P(Binomial(K, p) >= X) >= alpha (one-sided, 4 books). K = 100: 17 (T12.md section 2, V6)."""
    tail = 0.0
    for X in range(K, -1, -1):
        tail += math.comb(K, X) * p ** X * (1 - p) ** (K - X)
        if tail >= alpha:
            return X
    return K


NULLS = (("N46", "N4.6"), ("N48", "N4.8"))  # the deciding null first
HIGHER_BETTER = {"cagr": True, "max_dd": True, "calmar": True, "vol": False, "ulcer": False, "days_below_10pct": False, "longest_underwater": False}
BANDS = ["Large", "Mid", "Small and below"]
SIGS = ["Nifty100", "MC100", "SC100"]
WINS = ("full", "r2")
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
            d[c] = d[c].map(lambda v: "" if (v is None or (isinstance(v, float) and math.isnan(v))) else f(v))
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


def leaves(obj, path=()):
    """Every (path, key, scalar) in a json tree."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from leaves(v, path + (str(k),))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from leaves(v, path + (str(i),))
    else:
        yield path, obj


def dicts(obj):
    """Every dict in a json tree (depth first)."""
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from dicts(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from dicts(v)


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


def v4_read(reg: dict) -> dict:
    """V4 from regression.json (evidence contract point 7). Its shape is not fixed, so it is read generically:
    v4a / v4b: every dict holding a relative difference (max_rel_diff, max_rel, rel_diff, max_relative_difference) must be <= 1e-12 and, where it
               states a count of sessions (sessions, dates_compared, compared, n), compare more than 0; every 'pass' flag must be true; v4a must
               hold at least one comparison. v4b may instead say status 'not run' (T11's headline did not exist when the run started).
    v4c:       no function changed unexpectedly ('expected' false, or a non-zero 'unexpected' count) and every 'pass' flag true.
    v4d:       mismatches == 0 and something was compared."""
    REL = ("max_rel_diff", "max_rel", "rel_diff", "max_relative_difference", "max_rel_difference", "worst_rel_diff")
    CNT = ("sessions", "dates_compared", "compared", "n_compared", "rows", "n", "sessions_compared")
    res = {}
    for part, lim in (("v4a", 1e-12), ("v4b", 1e-12)):
        blk = reg.get(part)
        r = {"present": blk is not None, "not_run": False, "comparisons": 0, "sessions": 0, "worst": 0.0, "bad": 0, "flags": 0, "flags_false": 0, "reason": ""}
        if blk is None:
            res[part] = r
            continue
        st_ = find_key(blk, {"status"})
        if isinstance(st_, str) and "not run" in st_.lower():
            r["not_run"] = True
            r["reason"] = str(find_key(blk, {"reason"}) or "")
        for d in dicts(blk):
            rel = next((d[k] for k in REL if k in d and isinstance(d[k], (int, float)) and not isinstance(d[k], bool)), None)
            if rel is None:
                continue
            r["comparisons"] += 1
            r["worst"] = max(r["worst"], float(rel))
            cnt = next((d[k] for k in CNT if k in d and isinstance(d[k], (int, float)) and not isinstance(d[k], bool)), None)
            if cnt is not None:
                r["sessions"] += int(cnt)
                r["bad"] += int(cnt <= 0)
            r["bad"] += int(not (float(rel) <= lim))
        fl = flags(blk)
        r["flags"], r["flags_false"] = len(fl), sum(1 for x in fl if not x)
        res[part] = r
    blk = reg.get("v4c")
    r = {"present": blk is not None, "functions": 0, "changed": 0, "unexpected": 0, "flags_false": 0}
    if blk is not None:
        for d in dicts(blk):
            if "expected" in d and isinstance(d["expected"], bool):
                r["functions"] += 1
                r["changed"] += int(bool(d.get("changed", False)))
                r["unexpected"] += int(not d["expected"])
        for path, v in leaves(blk):
            if path and path[-1].lower() in ("unexpected", "n_unexpected", "unexpected_changes") and isinstance(v, (int, float)) and not isinstance(v, bool):
                r["unexpected"] += int(v)
        fn = blk.get("functions") if isinstance(blk, dict) else None
        if isinstance(fn, dict) and fn and all(isinstance(x, str) for x in fn.values()):   # the engine's shape: {name: "changed" | "unchanged"}
            r["functions"] += len(fn)
            r["changed"] += sum(1 for x in fn.values() if x.lower() == "changed")
        for k_ in ("unexpected_changes", "required_not_identical"):                          # lists of names that must be empty
            if isinstance(blk, dict) and isinstance(blk.get(k_), list):
                r["unexpected"] += len(blk[k_])
        r["flags_false"] = sum(1 for x in flags(blk) if not x)
    res["v4c"] = r
    blk = reg.get("v4d")
    r = {"present": blk is not None, "compared": 0, "mismatches": 0, "flags_false": 0}
    if blk is not None:
        r["compared"] = int(find_key(blk, {"compared", "checked", "n_compared", "tags_compared", "rows_checked", "rows", "n"}) or 0)
        r["mismatches"] = int(find_key(blk, {"mismatches", "n_mismatches", "differ", "failures"}) or 0)
        r["flags_false"] = sum(1 for x in flags(blk) if not x)
    res["v4d"] = r
    a_, b_, c_, d_ = res["v4a"], res["v4b"], res["v4c"], res["v4d"]
    ok_a = a_["present"] and not a_["not_run"] and a_["comparisons"] > 0 and a_["bad"] == 0 and a_["flags_false"] == 0
    ok_b = b_["present"] and (b_["not_run"] or (b_["comparisons"] > 0 and b_["bad"] == 0 and b_["flags_false"] == 0))
    ok_c = c_["present"] and c_["unexpected"] == 0 and c_["flags_false"] == 0
    ok_d = d_["present"] and d_["compared"] > 0 and d_["mismatches"] == 0 and d_["flags_false"] == 0
    res["ok"] = {"v4a": ok_a, "v4b": ok_b, "v4c": ok_c, "v4d": ok_d, "top-level pass flag": reg.get("pass") is not False}
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="headline")
    ap.add_argument("--evidence", default=None, help="explicit evidence directory (overrides --run)")
    ap.add_argument("--out", default=None, help="where analysis.log goes (default tests/T12 for --run, the evidence directory for --evidence)")
    ap.add_argument("--doc", default=str(HERE / "T12.md"), help="T12.md, read only, for the pre-registration hash")
    ap.add_argument("--t07", default=str(AA / "tests" / "T07" / "evidence" / "headline"), help="T07's evidence (the comparison block)")
    ap.add_argument("--t07-log", default=str(AA / "tests" / "T07" / "analysis.log"))
    ap.add_argument("--t11", default=str(AA / "tests" / "T11" / "evidence" / "headline"), help="T11's evidence (context, if it exists)")
    ap.add_argument("--t11-log", default=str(AA / "tests" / "T11" / "analysis.log"))
    ap.add_argument("--books", default=None, help="comma list; for engine smoke runs that hold fewer than the four books (the verdict counts then mean nothing)")
    ap.add_argument("--expect-draws", type=int, default=2000, help="draws per book, cost and null the pre-registration requires (2,000); V3 fails if different")
    ap.add_argument("--replay", type=int, default=100, help="N4.6 draws per book and window replayed from their seeds (V3)")
    a = ap.parse_args()
    if a.books:
        BOOKS[:] = a.books.split(",")
    R6B = [b for b in R6_BOOKS if b in BOOKS]
    ev_dir = Path(a.evidence) if a.evidence else HERE / "evidence" / a.run
    outdir = Path(a.out) if a.out else (ev_dir if a.evidence else HERE)
    BNO = {"SCMO_0003": 0, "SCMO_0007": 1, "SCMO_0010": 2, "SCMO_0029": 3}

    dec = pd.read_csv(ev_dir / "decisions.csv")
    ev = pd.read_csv(ev_dir / "events.csv")
    es = pd.read_csv(ev_dir / "event_stocks.csv", keep_default_na=False, na_values=[""], dtype={"isin": str, "tag_detail": str})
    st = pd.read_csv(ev_dir / "stats.csv")
    dr = pd.read_csv(ev_dir / "draws.csv")
    nav = pd.read_csv(ev_dir / "daily_nav.csv", parse_dates=["date"])
    au = json.loads((ev_dir / "audit.json").read_text(encoding="utf-8"))
    ct = json.loads((ev_dir / "count_table.json").read_text(encoding="utf-8"))
    zdrops = np.load(ev_dir / "draw_drops.npz")
    zlab = np.load(ev_dir / "draw_labels.npz")
    doc = Path(a.doc).read_text(encoding="utf-8")
    region = doc[doc.index("\n## 1. Idea and references") + 1:doc.index("\n## 4. Results") + 1]
    region = "\n".join(l.rstrip() for l in region.replace("\r\n", "\n").split("\n"))
    sha = hashlib.sha256(region.encode("utf-8")).hexdigest()
    m_sha = re.search(r"§1–§3 sha256:\*\* `([^`]*)`", doc)
    sha_hdr = m_sha.group(1) if m_sha else "?"

    ev["partial_b"] = asbool(ev["partial"])
    es["kept_b"] = asbool(es["kept"])
    ev = ev.sort_values(["book", "window", "event_no"]).reset_index(drop=True)
    EV = {(b, w): g.reset_index(drop=True) for (b, w), g in ev.groupby(["book", "window"])}
    KEYS = [(b, w) for b in BOOKS for w in WINS] + [(b, "full_r6") for b in R6B]
    ES = {(b, w): es[(es.book == b) & (es.window == w)].reset_index(drop=True) for (b, w) in KEYS}  # file order = the order of the drops columns
    S = lambda b, kind="segment", cost=PRIMARY, win="full", cash="lbes": st[(st.book == b) & (st.window == win) & (st.cash == cash) & (st.cost_bps == cost) & (st.kind == kind)].iloc[0]
    D = lambda b, typ, cost=PRIMARY, win="full", cash="lbes": dr[(dr.book == b) & (dr.window == win) & (dr.cash == cash) & (dr.cost_bps == cost) & (dr.draw_type == typ)].sort_values("draw_id")
    ndraws = int(len(D(BOOKS[0], "N4.6")))
    rule_state = {b: dec[dec.book == b].sort_values("j").reset_index(drop=True) for b in BOOKS}
    weeks = {b: len(rule_state[b]) for b in BOOKS}
    cal = {b: nav[(nav.book == b) & (nav.cost_bps == PRIMARY) & (nav.run == "segment")].sort_values("date").date.reset_index(drop=True) for b in BOOKS}
    nses = {b: len(cal[b]) for b in BOOKS}
    r2_first = {b: str(EV[(b, "r2")].trade_date.iloc[0]) if (b, "r2") in EV else None for b in BOOKS}

    P("T12 analysis. Run:", ev_dir.name, "| draws per book, cost and null:", f"{ndraws:,}", "| deciding null: N4.6; N4.8 beside it; C3 = rule minus the whole-book switch")
    P("Window: %s -> %s (every book), %d weekly decisions; R2 sub-window from the first D26 session on or after %s (%s), %d decisions" % (
        rule_state[BOOKS[0]].decision_date.iloc[0], rule_state[BOOKS[0]].decision_date.iloc[-1], weeks[BOOKS[0]], R2_START, r2_first[BOOKS[0]],
        int((pd.to_datetime(rule_state[BOOKS[0]].decision_date) >= pd.Timestamp(r2_first[BOOKS[0]] or R2_START)).sum())))
    P("No published NAV exists before 2019-01-02: 'hold the parent' below is the engine's rebuild from the parent's baskets and Eikon prices, not validated against a published series in this window.")
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
    head("4.0b  GATES, THE NULLS' TABLES AND REPORTABILITY\n(V1 independent check, V2 point in time, V3 the nulls hold their tables, V4 regression and identities, V5 the sampler is exact, V6 negative control, V7 oracle)")
    gates = GATES
    vj = ev_dir / "verify_t12.json"
    if vj.exists():
        v = json.loads(vj.read_text(encoding="utf-8"))
        if "exit_ok" in v and "gate_compared" in v:
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
        det = find_key(v, {"detected", "corrupt_detected", "selftest_detected", "corrupted_copy_detected", "all_detected"})
        ok = exit_ok and bad_ == 0 and comp > 0 and det is True
        P("V1 independent check (verify_t12.py): ", "PASS" if ok else "FAIL", f"| comparisons {comp:,}, failures and missing {bad_}, corrupted copy detected: {det}")
        gates["V1"] = ok
    else:
        P("V1 independent check: NOT RUN (%s missing)" % vj)
        gates["V1"] = False

    viol = cnt = 0
    v2 = au.get("v2")
    if isinstance(v2, dict) and "violations" in v2 and "checked" in v2:
        viol, cnt = v2["violations"], v2["checked"]
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
    v3 = {"keys": 0, "draws": 0, "bad": 0, "n_bad_count": 0, "rows": 0, "rows_bad": 0, "tau_worst": 0.0, "replayed": 0, "replay_bad": 0, "notes": []}
    GAP = {}
    for (b, win) in KEYS:
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
        if "row" in rows.columns and not (rows["row"].values == np.arange(R)).all():
            v3["rows_bad"] += 1
            v3["notes"].append(f"{b}|{win}: the 'row' column of event_stocks.csv is not 0..R-1 in file order")
        kept = rows.kept_b.values
        Drow = (~kept).astype(float) @ Wm
        v3["rows"] += E
        v3["rows_bad"] += int((np.abs(Drow - Dr) > 1e-9).sum()) + int(((~kept).astype(float) @ M != n_drop).sum()) + int((M.sum(0) != n_held).sum())
        tmin = np.array([w[ri == q].min() / 2 for q in range(E)])
        v3["rows_bad"] += int((np.abs(tmin - tau) > 1e-9).sum())
        for typ in (("N4.6",) if win == "full_r6" else ("N4.6", "N4.8")):
            key = f"{b}|{win}|{typ}"
            if key not in zdrops.files:
                v3["notes"].append(f"missing {key}")
                v3["bad"] += 1
                continue
            A = zdrops[key].astype(np.int8)
            v3["keys"] += 1
            nd = A.shape[0]
            if A.shape[1] != R:
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
                expect = sell[np.arange(R)[None, :], np.clip(L, 0, 2)]
                badm |= (expect != (A == 1)).any(1)
                badm |= (L > 2).any(1)
            v3["draws"] += nd
            v3["bad"] += int(badm.sum())
            v3["n_bad_count"] += int(nd != a.expect_draws)
            gap = np.abs(Dd - Dr[None, :])
            GAP[(b, win, typ)] = {"mean_abs_gap": float(gap.mean()), "max_abs_gap": float(gap.max()), "max_gap_over_tau": float((gap / tau[None, :]).max()), "mean_D": float(Dd.mean()), "rule_mean_D": float(Dr.mean())}
            for (cash, cost), g in dr[(dr.book == b) & (dr.window == win) & (dr.draw_type == typ)].groupby(["cash", "cost_bps"]):
                ids = np.sort(g.draw_id.values)
                v3["bad"] += int(len(g) != nd or (ids != np.arange(nd)).any() or (g.n_events != E).any())
            if typ == "N4.6" and a.replay > 0:
                isin = rows["isin"].values
                prep = []
                for q in range(E):
                    idx = np.flatnonzero(ri == q)
                    order = idx[np.argsort(isin[idx], kind="stable")]
                    prep.append((order, allowed_set(w[order], Dr[q], tau[q])))
                for d_ in range(min(a.replay, nd)):
                    u = np.random.default_rng([SEED, 7, d_, BNO[b]]).random(E)
                    got = np.zeros(R, np.int8)
                    for q, (order, al) in enumerate(prep):
                        m = int(al[int(math.floor(u[q] * len(al)))])
                        got[order] = [(m >> i) & 1 for i in range(len(order))]
                    v3["replayed"] += 1
                    v3["replay_bad"] += int((got != A[d_]).any())
    P(f"V3 the nulls hold their tables: {v3['draws']:,} saved draws checked over {v3['keys']} drop arrays (windows full and r2 for both nulls, full_r6 for N4.6; N4.6: dropped subset inside the held set, its listed weight within tau of the rule's, drop nothing / everything when the rule does; "
      f"N4.8: stocks per label equal the rule's n_large, n_mid, n_small at every event, and a stock is dropped iff its label's signal is SELL), bad {v3['bad']}; draws per array differing from the required {a.expect_draws:,}: {v3['n_bad_count']}; "
      f"events.csv against event_stocks.csv: {v3['rows']:,} events, {v3['rows_bad']} inconsistent {v3['notes'] or ''}")
    P(f"   worst |dropped weight - rule's| over every N4.6 draw and event, in units of tau: {v3['tau_worst']:.3f} (must be <= 1)")
    P(f"   N4.6 replayed from the seed [{SEED}, 7, draw_id, book_no] (frozen sampler; bit i = stock i, ISIN order): {v3['replayed']:,} draws, {v3['replay_bad']} differ from draw_drops.npz")
    au_v3 = au.get("v3")
    eng_v3 = flags(au_v3) if au_v3 is not None else []
    if au_v3 is not None:
        bd_ = find_key(au_v3, {"bad", "violations"})
        P(f"   audit.json v3 block (the engine's own check): {len(eng_v3)} pass flags, all true: {all(eng_v3) and len(eng_v3) > 0}; its bad count: {bd_}")
        if bd_ not in (None, 0):
            v3["bad"] += 1
    gates["V3"] = v3["bad"] == 0 and v3["rows_bad"] == 0 and v3["n_bad_count"] == 0 and v3["draws"] > 0 and v3["replay_bad"] == 0 and (all(eng_v3) if eng_v3 else True)

    # V4 (regression.json; there is no published NAV before 2019-01-02, so T07's G0 cannot be made)
    rj = ev_dir / "regression.json"
    v4 = v4_read(json.loads(rj.read_text(encoding="utf-8"))) if rj.exists() else None
    if v4 is None:
        P("V4 regression and identities: regression.json MISSING")
        gates["V4"] = False
    else:
        A4, B4, C4, D4 = v4["v4a"], v4["v4b"], v4["v4c"], v4["v4d"]
        P(f"V4 regression and identities (regression.json; no published NAV before 2019-01-02, so no G0):")
        P(f"   (a) the engine on the D17 calendar of 2019 against T07's stored rule NAV and T06's stored whole-book NAV: {A4['comparisons']} comparisons over {A4['sessions']:,} sessions, worst relative difference {A4['worst']:.1e} (limit 1e-12), "
          f"bad {A4['bad']}, pass flags {A4['flags']} ({A4['flags_false']} false) -> {'PASS' if v4['ok']['v4a'] else 'FAIL'}")
        if B4["not_run"]:
            P(f"   (b) against T11's headline: NOT RUN ({B4['reason'] or 'status not run'}); allowed by T12.md section 2 when T11's headline did not exist")
        else:
            P(f"   (b) whole-book and always-in modes against T11's Part A and hold-the-parent NAVs: {B4['comparisons']} comparisons over {B4['sessions']:,} sessions, worst relative difference {B4['worst']:.1e} (limit 1e-12), bad {B4['bad']} -> {'PASS' if v4['ok']['v4b'] else 'FAIL'}")
        P(f"   (c) shared functions against t07_engine.py: {C4['functions']} listed, {C4['changed']} changed, {C4['unexpected']} unexpected -> {'PASS' if v4['ok']['v4c'] else 'FAIL'}")
        P(f"   (d) tags at every event against a direct read of the D23b rank panel: {D4['compared']:,} compared, {D4['mismatches']} mismatches -> {'PASS' if v4['ok']['v4d'] else 'FAIL'}")
        gates["V4"] = all(v4["ok"].values())

    # V5
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
    for (b, win) in KEYS:
        rows, e = ES[(b, win)], EV.get((b, win))
        if e is None:
            continue
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
      f"(b) brute-force count of the allowed subsets (all 2^n, n <= 16, within tau of the rule's dropped weight) at {cnt_n} events (windows full, r2, full_r6) against events.csv: {cnt_bad} differ; against count_table.json: "
      f"{ct_cmp} entries compared, {ct_bad} differ{'' if ct_cmp else ' (count_table.json shape not recognised, not compared)'}; (c) the rule's own drop set is among the allowed subsets at every event: {own_bad} are not")
    gates["V5"] = bool(worstp) and cnt_bad == 0 and own_bad == 0 and ct_bad == 0 and cnt_n > 0

    # V6 negative control
    nc = pd.read_csv(ev_dir / "controls_negative.csv") if (ev_dir / "controls_negative.csv").exists() else None
    ncj = json.loads((ev_dir / "controls_negative.json").read_text(encoding="utf-8")) if (ev_dir / "controls_negative.json").exists() else None
    v6rows, v6ok = [], nc is not None
    if nc is not None:
        for b in BOOKS:
            g = nc[nc.book == b]
            K = len(g)
            npass = int((g.percentile >= PASS_PCT).sum())
            xm = v6_xmax(K)
            agree = (not "pass90" in g) or bool((asbool(g["pass90"]) == (g.percentile.values >= PASS_PCT)).all())
            jb = per_book(ncj, b) if ncj is not None else None
            j_n = find_key(jb, {"n_pass90"}) if jb else None
            j_x = find_key(jb, {"x_max"}) if jb else None
            j_agree = (j_n is None or int(j_n) == npass) and (j_x is None or int(j_x) == V6_XMAX_FROZEN)
            ok_b = K >= 100 and npass <= V6_XMAX_FROZEN and xm == V6_XMAX_FROZEN if K == 100 else (K >= 100 and npass <= xm)
            ok_b = ok_b and agree and j_agree
            v6rows.append({"book": b, "shifts": K, "percentile >= 90": npass, "allowed (at most)": V6_XMAX_FROZEN if K == 100 else xm, "pass90 column agrees": agree,
                           "controls_negative.json agrees": j_agree, "within": ok_b})
            v6ok &= ok_b
    P(f"V6 negative control (100 circular shifts of the joint three-signal weekly matrix by k decisions, 26 <= k <= n - 26, each judged against its own N4.6 null, 200 draws, 20.8 bps; T12.md section 2: per book at most {V6_XMAX_FROZEN} of 100 reach CAGR percentile >= 90, "
      f"the largest X with P(Binomial(100, 0.10) >= X) >= 0.05 / 4; recomputed here: {v6_xmax(100)}):")
    if v6rows:
        table(pd.DataFrame(v6rows))
    else:
        P("   controls_negative.csv missing")
    gates["V6"] = bool(v6ok)
    if not v6ok:
        P("V6 FAILED (too many information-free signals reach the 90th percentile, or too few shifts were run, for: %s): by T12.md section 2 nothing below may be read; fix and rerun as a new run directory" % ([r_["book"] for r_ in v6rows if not r_["within"]] or "all books (file missing)"))

    # V7 oracle
    oj = ev_dir / "controls_oracle.json"
    v7rows, v7ok = [], oj.exists()
    if oj.exists():
        o = json.loads(oj.read_text(encoding="utf-8"))
        for b in BOOKS:
            d_ = per_book(o, b)
            cg = find_key(d_, {"cagr", "oracle_cagr", "after_cost_cagr"}) if d_ else None
            pc_ = find_key(d_, {"percentile", "pct", "oracle_percentile", "percentile_vs_n46", "percentile_vs_n4.6", "pct_n46"}) if d_ else None
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
        for win in WINS:
            d_ = rule_state[b]
            if win == "r2":
                d_ = d_[pd.to_datetime(d_.decision_date) >= pd.Timestamp(r2_first[b] or R2_START)]
            x = asbool(d_["disagree"]).astype(int)
            n_st = int(((x[1:] == 1) & (x[:-1] == 0)).sum()) + int(len(x) and x[0] == 1)
            n_part = int(EV[(b, win)].partial_b.sum()) if (b, win) in EV else 0
            rep[(b, win)] = {"weeks": len(x), "disagree_weeks": int(x.sum()), "stretches": n_st, "partial_events": n_part, "events": len(EV.get((b, win), [])), "ok": n_st >= 5 and n_part >= 6}
    P("Reportability (a realisation needs >= 5 separate disagreement stretches and >= 6 events with 0 < equity share < 1; frozen counts: 11 stretches full, 10 R2; coarse upper bounds 17 (full) and 14 (R2) events in disagreement weeks):")
    table(pd.DataFrame([{"book": b, "window": w, **v, "REPORTABLE": "yes" if v["ok"] else "NO: NOT REPORTABLE"} for (b, w), v in rep.items()]))
    cc_ = au.get("events_vs_section2_coarse_counts")
    if isinstance(cc_, dict) and cc_:
        P("Events against T12.md section 2's coarse upper bounds (audit.json; 'in disagreement weeks' under Step 1's attribution, which the bound uses, and under T07's, the state's decision):")
        table(pd.DataFrame([{"book|window": k_, "events (incl. T0)": x.get("engine_events_incl_T0"), "coarse bound": x.get("coarse_events_section2"),
                             "in disagreement weeks (Step 1)": x.get("engine_events_in_disagreement_weeks_step1_attribution"), "(T07's attribution)": x.get("engine_events_in_disagreement_weeks"),
                             "bound": x.get("coarse_in_mixed_weeks"), "within": x.get("engine_le_coarse") and x.get("engine_le_coarse_in_disagreement")} for k_, x in cc_.items() if isinstance(x, dict)]))
    notrep = [b for b in BOOKS if not rep[(b, "full")]["ok"]]
    P("NOT REPORTABLE (full window):", notrep or "none", "| NOT REPORTABLE (R2 window):", [b for b in BOOKS if not rep[(b, "r2")]["ok"]] or "none")
    if notrep:
        P("STOP RULE (TRACKER.md): a book is NOT REPORTABLE on the full window: stop and ask Manu before anything is read.")
    P("Allowed N4.6 subsets per event (brute force here; the null's spread is limited by them), full window:")
    cs = []
    for b in BOOKS:
        c_ = cnt_stats[(b, "full")]
        cs.append({"book": b, "events": len(c_), "events with 1 allowed subset": int((c_ == 1).sum()), "min": int(c_.min()), "median": float(np.median(c_)), "max": int(c_.max()), "log10(distinct draws)": float(np.log10(c_.astype(float)).sum())})
    table(pd.DataFrame(cs), {"median": lambda x: f"{x:.1f}", "log10(distinct draws)": lambda x: f"{x:.1f}"})
    P("Dropped weight per event, null against rule (listed weights; N4.6 must lie within tau, N4.8 is not matched exactly; means over draws and events, full window):")
    P(pd.DataFrame([{"book": b, "null": t_, "rule mean D": GAP[(b, "full", t_)]["rule_mean_D"], "null mean D": GAP[(b, "full", t_)]["mean_D"], "mean |gap|": GAP[(b, "full", t_)]["mean_abs_gap"],
                     "max |gap|": GAP[(b, "full", t_)]["max_abs_gap"], "max gap / tau": GAP[(b, "full", t_)]["max_gap_over_tau"]} for b in BOOKS for t_ in ("N4.6", "N4.8") if (b, "full", t_) in GAP]).to_string(index=False, float_format=lambda x: f"{x:.4f}"))
    P("Stand-ins (audit.json 'standins': previous close used where a session has no bar; GOLDBEES fills at the raw OHLC4 where MCX gold has no range):", json.dumps(au.get("standins"), default=str) if au.get("standins") is not None else "(not recorded)")
    P("Unranked holdings at events (audit.json 'unranked'; they read Small and below, R6 reads them by their other listing):", json.dumps(au.get("unranked"), default=str) if au.get("unranked") is not None else "(not recorded)")
    un = es[es.tag_source == "unranked"]
    P("   from event_stocks.csv, unranked rows per book and window:", {f"{b}|{w}": sorted(set(g.stock)) for (b, w), g in un.groupby(["book", "window"])} or "none")
    P("T11's headline evidence existed when the run started (audit.json 't11_headline_seen'):", au.get("t11_headline_seen"))
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
    cols_ = [c for c in ("stock", "isin", "listed_weight", "band", "tag_source", "tag_snapshot", "tag_detail", "tag_n_ranked", "tag_via", "band_signal", "kept_b") if c in qr.columns]
    tbl = qr[cols_].rename(columns={"kept_b": "kept"})
    P("The tag of every held stock as of the information date (every tag in this window is a market-cap rank tag; band of the stock's index signal on or off):")
    table(tbl, {"listed_weight": lambda x: f"{x:.5f}"})
    sw, Dd0 = float(qr.listed_weight.sum()), float(qr.listed_weight[~qr.kept_b].sum())
    s_ = Dd0 / sw
    P(f"Targets (T12.md section 3 step 6): sum of listed weights {sw:.6f}; dropped weight D = {Dd0:.6f}; s = D / sum = {s_:.6f}; kept stock i gets V x w_i; GOLDBEES and cash units each get V x s / 2 = V x {s_ / 2:.6f}; "
      f"V (before cost) {r.V_before:.6f}, traded {r.traded:.6f}, cost = traded x 20.8 / 2 / 10,000 = {r.cost:.6f} (recomputed {r.traded * PRIMARY / 2 / 10000:.6f}); events.csv: D {r.dropped_weight:.6f}, s {r.sleeve_share_s:.6f}, "
      f"n_held {int(r.n_held)}, n_dropped {int(r.n_dropped)}, partial {bool(r.partial_b)}.")
    P(f"N4.6 for this event: tau = half the smallest listed weight = {r.tau:.6f}; the allowed subsets are those whose listed weight is within tau of D: {int(r.n_allowed_subsets)} of 2^{int(r.n_held)} = {2 ** int(r.n_held)}.")
    A0 = zdrops[f"{b}|full|N4.6"].astype(int)
    ri0 = ROWMAP[(b, "full")]
    idx = np.flatnonzero(ri0 == qx)
    isin_ = rows["isin"].values
    order = idx[np.argsort(isin_[idx], kind="stable")]
    al = allowed_set(rows.listed_weight.values[order].astype(float), float(r.dropped_weight), float(r.tau))
    u = float(np.random.default_rng([SEED, 7, 0, BNO[b]]).random(len(e))[qx])
    m = int(al[int(math.floor(u * len(al)))])
    got = np.array([(m >> i) & 1 for i in range(len(order))])
    stored = A0[0, order]
    P(f"One N4.6 draw (draw_id 0, seed numpy default_rng([{SEED}, 7, 0, {BNO[b]}]), uniform number {qx + 1} of {len(e)} since there is one per event): u = {u:.6f}; index floor(u x {len(al)}) = {int(math.floor(u * len(al)))}; bitmask {m} "
      f"(bit i = stock i in ISIN order); it drops {[rows.stock.values[order[i]] for i in range(len(order)) if got[i]]} with listed weight {float(rows.listed_weight.values[order] @ got):.6f} "
      f"(the rule drops {[rows.stock.values[order[i]] for i in range(len(order)) if not rows.kept_b.values[order[i]]]}, weight {Dd0:.6f}; gap within tau: {abs(float(rows.listed_weight.values[order] @ got) - Dd0) <= float(r.tau) + 1e-12}); "
      f"stored draw 0 equals this replay: {bool((got == stored).all())}")
    s0 = S(b)
    nv = nav[(nav.book == b) & (nav.cost_bps == PRIMARY) & (nav.run == "segment")].sort_values("date").reset_index(drop=True)
    k = int(nv.index[nv.date == pd.Timestamp(r.trade_date)][0])
    P("NAV around the trade (rule, 20.8 bps; whole-book switch beside it):")
    nw = nav[(nav.book == b) & (nav.cost_bps == PRIMARY) & (nav.run == "whole_book")].sort_values("date").reset_index(drop=True)
    lo_, hi_ = max(k - 2, 0), min(k + 3, len(nv))
    table(pd.DataFrame({"date": nv.date.dt.date.iloc[lo_:hi_], "rule": nv.nav.iloc[lo_:hi_], "whole_book": nw.nav.iloc[lo_:hi_]}), {"rule": lambda x: f"{x:.6f}", "whole_book": lambda x: f"{x:.6f}"})
    P(f"One path: start 1.000000 on {nv.date.iloc[0].date()}, end {s0.end_nav:.6f} on {nv.date.iloc[-1].date()}, {int(s0.sessions)} sessions -> years {(s0.sessions - 1) / 252:.4f}, CAGR {100 * s0.cagr:.3f}%, max drawdown {100 * s0.max_dd:.2f}%")
    for nm, typ in NULLS:
        n_ = D(b, typ)
        x0 = n_[n_.draw_id == 0].iloc[0]
        rk = rank(s0.cagr, n_.cagr.values, True)
        P(f"  {typ} draw 0: CAGR {100 * x0.cagr:.3f}%, max drawdown {100 * x0.max_dd:.2f}%, trades {int(x0.trades)} (rule {int(s0.trades)}), cost paid {x0.cost_paid:.4f} (rule {s0.cost_paid:.4f})")
        P(f"  One ranking against {typ} (CAGR, {rk['draws']} draws): below {rk['worse']}, equal {rk['tied']}, above {rk['better']} -> percentile {rk['percentile']:.2f}, p-value {rk['p']:.5f}; "
          f"null median {100 * n_.cagr.median():.2f}%, edge {100 * (s0.cagr - n_.cagr.median()):+.2f} pp")

    # ══ 4.1 headline ═════════════════════════════════════════════════════════
    head(f"4.1  HEADLINE: the rule against N4.6 (deciding) and N4.8 (full window {T0_DATE} -> {END_DATE}, LBES cash; {ndraws:,} draws each) and against the whole-book switch")
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
    P(f"\nC3: the rule minus the whole-book switch, after cost, full window (percentage points a year); SE from a moving-block bootstrap (blocks of 20 sessions, 1,000 resamples, seed default_rng([{SEED}, 20, book_no])) of the paired daily returns:")
    c3 = []
    SE = {}
    for cost in COSTS:
        for b in BOOKS:
            sr, sw_ = S(b, cost=cost), S(b, "whole_book", cost)
            row = {"cost": cost, "book": b, "rule CAGR%": 100 * sr.cagr, "whole-book CAGR%": 100 * sw_.cagr, "diff pp": 100 * (sr.cagr - sw_.cagr)}
            if cost == PRIMARY:
                vr = nav[(nav.book == b) & (nav.cost_bps == cost) & (nav.run == "segment")].sort_values("date").nav.values
                vw = nav[(nav.book == b) & (nav.cost_bps == cost) & (nav.run == "whole_book")].sort_values("date").nav.values
                SE[b] = mbb_se(vr, vw, [SEED, 20, BNO.get(b, BOOKS.index(b))])
                row.update({"SE pp": 100 * SE[b], "diff / SE": (sr.cagr - sw_.cagr) / SE[b]})
            c3.append(row)
    C3 = pd.DataFrame(c3)
    table(C3, {c: (lambda x: f"{x:.2f}") for c in C3.columns if c not in ("cost", "book")})

    # ══ 4.2 comparators ══════════════════════════════════════════════════════
    head(f"4.2  COMPARATORS (benchmarks, not nulls), same window {T0_DATE} -> {END_DATE}, T0 = 1.000; weight by band; tag sources")
    comp = []
    for cost in COSTS:
        for b in BOOKS:
            row = {"cost": cost, "book": b}
            for kind in ("segment", "whole_book", "parent", "constant_mix", "sleeve100"):
                s = S(b, kind, cost)
                row[f"{kind}_CAGR%"], row[f"{kind}_DD%"] = 100 * s.cagr, 100 * s.max_dd
            comp.append(row)
    Cm = pd.DataFrame(comp)
    table(Cm, {c: (lambda x: f"{x:.2f}") for c in Cm.columns if c.endswith("%")})
    P("whole_book = every stock follows the single state IN iff all three signals are BUY (T06's rule; T11's Part A on this window); parent = hold every stock (the engine; REBUILT from the parent's baskets and Eikon prices, "
      "no published NAV exists before 2019-01-02); constant_mix = the rule's average share of NAV in the parent's stocks held all the time, rebalanced at each event; sleeve100 = 50/50 GOLDBEES and cash.")
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
    P("\nTag source of the exposure (share of listed weight x sessions by the source of the tag; in this window every tag is a market-cap rank tag (rank) or unranked (Small and below by default); "
      "membership tags start 2026-04-09 and cannot occur):")
    ts = []
    for b in BOOKS:
        e, rows = EV[(b, "full")], ES[(b, "full")]
        ri = ROWMAP[(b, "full")]
        span = np.diff(np.append(e.trade_idx.values.astype(int), nses[b] - 1)).astype(float)
        wt = rows.listed_weight.values * span[ri]
        row = {"book": b}
        for src in ("rank", "unranked", "membership", "nonmember_rank"):
            row[src + " %"] = 100 * wt[rows.tag_source.values == src].sum() / wt.sum()
        row["event-rows"] = len(rows)
        row["unranked rows"] = int((rows.tag_source.values == "unranked").sum())
        ts.append(row)
    table(pd.DataFrame(ts), {c: (lambda x: f"{x:.2f}") for c in ("rank %", "unranked %", "membership %", "nonmember_rank %")})

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
    P("Calibration ratio (T12.md section 2; diagnostic, no pass mark): SD of the null's after-cost CAGR / SE of the rule's CAGR minus the whole-book switch's (moving-block bootstrap). "
      "Below 1 the null is calmer than reality's own noise about the increment, and the percentile overstates the distance from the null (z x ratio, AGENT.md N6.6):")
    table(pd.DataFrame(calib), {c: (lambda x: f"{x:.2f}") for c in ("null SD CAGR pp", "SE of rule - whole-book pp", "calibration ratio", "percentile", "percentile at the ratio (z x ratio)")})
    P("T12.md section 3 step 13: the thresholds in section 2 do not depend on these numbers, which did not exist when it was written. The planted-effect control is not run (section 2).")

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
    P("\nOutcome map (T12.md section 2), rows that apply:")
    hits = []
    if c1 and c2 and c3p and c1n["N48"] >= 3:
        hits.append("C1, C2 and C3 PASS; N4.8 agrees: segment tagging chose what to drop better than chance and improved on the whole-book switch in 2014-19; with T07's failure in 2019-26, the effect is window-specific")
    elif c1 and c2 and c3p:
        hits.append("C1, C2 and C3 PASS under N4.6 but N4.8 does not pass C1 (not a row of the map): the nulls disagree; report both (AGENT.md N6.8)")
    if c3p and not c1:
        hits.append("C3 PASS, C1 FAIL: the gain over the whole-book switch is not specific to which stocks were dropped: the benefit is partial de-risking, not the tag")
    if c1 and not c3p:
        hits.append("C1 PASS, C3 FAIL: the tag picks better than chance but not enough to beat the whole-book switch")
    if not c1 and not c3p:
        hits.append("C1 and C3 FAIL: T07's rejection holds on 2014-19 too")
    if c1 and c3p and not c2:
        hits.append("C1 and C3 PASS, C2 FAIL (not a row of the map): selection and increment without the worst fall being shallower than the null's")
    if not agree48:
        hits.append("N4.6 and N4.8 disagree on C1: both are reported in the verdict and the finding's status note says so (T12.md section 2)")
    if notrep:
        hits.append(f"a realisation is NOT REPORTABLE ({notrep}): stated; the other books are read on their own")
    if not all(gates.values()):
        hits = ["a V gate fails: nothing is read. Fix and rerun as a new run directory"]
    for h_ in hits:
        P("  -", h_)

    # ══ 4.5 robustness ═══════════════════════════════════════════════════════
    head("4.5  ROBUSTNESS R1-R7 (decide a finding's status, not the verdicts)")
    for cost in (0.0, 50.0):
        hc = H[H.cost == cost]
        for nm, typ in NULLS:
            n1 = int((hc[f"{nm}_pct"] >= PASS_PCT).sum())
            n2 = int((hc[f"{nm}_DD_pct"] >= PASS_PCT).sum())
            P(f"R1 at {cost:g} bps against {typ}: C1 {n1} of 4 -> {'PASS' if n1 >= 3 else 'FAIL'} ({', '.join('%s %.1f' % (bb[-4:], x) for bb, x in zip(hc.book, hc[f'{nm}_pct']))}); "
              f"C2 {n2} of 4 -> {'PASS' if n2 >= 3 else 'FAIL'} ({', '.join('%s %.1f' % (bb[-4:], x) for bb, x in zip(hc.book, hc[f'{nm}_DD_pct']))})")
    P("R1 trades and cost paid are in the table of section 4.2 (rule, whole-book switch, and each null's median draw, at 0, 20.8 and 50 bps).")
    for nm, typ in NULLS:
        pc_, pd_, c3l, extra = [], [], [], []
        for b in BOOKS:
            s = st[(st.book == b) & (st.window == "r2") & (st.cash == "lbes") & (st.cost_bps == PRIMARY) & (st.kind == "segment")]
            sw_ = st[(st.book == b) & (st.window == "r2") & (st.cash == "lbes") & (st.cost_bps == PRIMARY) & (st.kind == "whole_book")]
            n = D(b, typ, win="r2")
            if len(s) and len(n):
                pc_.append(float(rank(s.iloc[0].cagr, n.cagr.values, True)["percentile"]) if rep[(b, "r2")]["ok"] else float("nan"))
                pd_.append(float(rank(s.iloc[0].max_dd, n.max_dd.values, True)["percentile"]) if rep[(b, "r2")]["ok"] else float("nan"))
                c3l.append(float(s.iloc[0].cagr - sw_.iloc[0].cagr) if len(sw_) and rep[(b, "r2")]["ok"] else float("nan"))
                extra.append(f"{100 * s.iloc[0].cagr:.1f}%")
        n1, n2 = sum(x >= PASS_PCT for x in pc_), sum(x >= PASS_PCT for x in pd_)
        n3 = sum(x > 0 for x in c3l)
        P(f"R2 sub-window {r2_first[BOOKS[0]]} -> {END_DATE} (own events and null, 20.8 bps), {typ}: C1 percentiles {[round(x, 1) for x in pc_]} (rule's CAGR {extra}) -> {n1} of {len(pc_)} >= {PASS_PCT:.0f} -> {'PASS' if n1 >= 3 else 'FAIL'}; "
          f"C2 percentiles {[round(x, 1) for x in pd_]} -> {n2} of {len(pd_)} -> {'PASS' if n2 >= 3 else 'FAIL'}"
          + (f"; C3 (rule minus whole-book, pp) {[round(100 * x, 2) for x in c3l]} -> {n3} of {len(c3l)} > 0 -> {'PASS' if n3 >= 3 else 'FAIL'}" if nm == "N46" else ""))
    P("   (a book whose R2 realisation is NOT REPORTABLE shows nan: %s)" % ([b for b in BOOKS if not rep[(b, 'r2')]['ok']] or "none"))
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
    P("\nR5 tag error (500 draws per book in the headline, 20.8 bps; each rank-rule tag replaced with probability 7.93% at every event by one of the other two bands; no pass mark): the rule's CAGR minus the whole-book switch's:")
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
    # R6: the unranked holdings read by their other listing (full_r6)
    P("\nR6 the two unranked holdings read by their other listing (window full_r6, books SCMO_0007 and SCMO_0010, 20.8 bps; C1 against the realisation's own N4.6 draws, C3 against the whole-book switch; no pass mark):")
    r6l = pd.read_csv(ev_dir / "r6_links.csv", dtype={"linked_quote_id": str, "isin": str}) if (ev_dir / "r6_links.csv").exists() else None
    r6rows = []
    for b in R6B:
        s6 = st[(st.book == b) & (st.window == "full_r6") & (st.cash == "lbes") & (st.cost_bps == PRIMARY) & (st.kind == "segment")]
        w6 = st[(st.book == b) & (st.window == "full_r6") & (st.cash == "lbes") & (st.cost_bps == PRIMARY) & (st.kind == "whole_book")]
        n6 = D(b, "N4.6", win="full_r6")
        row = {"book": b, "events": len(EV.get((b, "full_r6"), [])), "re-tagged event rows": int((ES[(b, "full_r6")].tag_source == "rank_linked").sum()) if (b, "full_r6") in ES else 0}
        if len(s6) and len(n6):
            row.update({"R6 rule CAGR%": 100 * s6.iloc[0].cagr, "R6 C1 pct vs own N4.6": rank(s6.iloc[0].cagr, n6.cagr.values, True)["percentile"], "headline C1 pct": hp.loc[b, "N46_pct"],
                        "R6 C3 pp": 100 * (s6.iloc[0].cagr - (w6.iloc[0].cagr if len(w6) else S(b, "whole_book").cagr)), "headline C3 pp": 100 * c3b[b], "draws": len(n6)})
        r6rows.append(row)
    if r6rows:
        table(pd.DataFrame(r6rows), {c: (lambda x: f"{x:.2f}") for c in ("R6 rule CAGR%", "R6 C1 pct vs own N4.6", "headline C1 pct", "R6 C3 pp", "headline C3 pp")})
    r6a = au.get("r6") if isinstance(au.get("r6"), dict) else {}
    P(f"   audit.json r6: quote_ids used {json.dumps(r6a.get('links'))} ({r6a.get('ids')}); re-tagged event rows {r6a.get('re_tagged_event_rows')}; linked quote_id absent on the snapshot {json.dumps(r6a.get('linked_quote_id_absent_on_snapshot'))}")
    if r6a.get("re_tagged_event_rows") == 0:
        P("   R6 RE-TAGGED NOTHING: the linked quote_ids have no rank in the window, so full_r6 equals the full window (the frozen T12.md names today's listings; Step 2 log, contract change 1).")
    if r6l is not None:
        P("   r6_links.csv (every event row R6 re-tags):")
        table(r6l)
    else:
        P("   r6_links.csv missing")
    # R7: flagged price days
    P("\nR7 price quality (descriptive, no pass mark): every held stock-day with an absolute one-day close move of 20% or more in D18 (r7_flagged_days.csv), and the rule and the whole-book switch re-run with each listed day's return set to zero:")
    r7 = pd.read_csv(ev_dir / "r7_flagged_days.csv", dtype={"isin": str}) if (ev_dir / "r7_flagged_days.csv").exists() else None
    if r7 is not None:
        P(f"   {len(r7)} flagged stock-days" + (":" if len(r7) else ""))
        if len(r7):
            table(r7, {"move": lambda x: f"{100 * x:+.1f}%", "close_prev": lambda x: f"{x:.2f}", "close": lambda x: f"{x:.2f}"})
    else:
        P("   r7_flagged_days.csv missing")
    r7rows = []
    for cost in (0.0, PRIMARY):
        for b in BOOKS:
            s7 = st[(st.book == b) & (st.window == "full") & (st.cash == "lbes") & (st.cost_bps == cost) & (st.kind == "segment_r7")]
            w7 = st[(st.book == b) & (st.window == "full") & (st.cash == "lbes") & (st.cost_bps == cost) & (st.kind == "whole_book_r7")]
            if len(s7) and len(w7):
                r7rows.append({"cost": cost, "book": b, "rule CAGR%": 100 * S(b, cost=cost).cagr, "rule R7 CAGR%": 100 * s7.iloc[0].cagr, "whole-book CAGR%": 100 * S(b, "whole_book", cost).cagr,
                               "whole-book R7 CAGR%": 100 * w7.iloc[0].cagr, "C3 pp": 100 * (S(b, cost=cost).cagr - S(b, "whole_book", cost).cagr), "C3 R7 pp": 100 * (s7.iloc[0].cagr - w7.iloc[0].cagr)})
    if r7rows:
        table(pd.DataFrame(r7rows), {c: (lambda x: f"{x:.2f}") for c in ("rule CAGR%", "rule R7 CAGR%", "whole-book CAGR%", "whole-book R7 CAGR%", "C3 pp", "C3 R7 pp")})
    else:
        P("   stats.csv has no segment_r7 / whole_book_r7 rows")
    P("\nHypotheses: H1 (selection)", "SUPPORTED in-sample against N4.6 (PROVISIONAL at most: T12 alone cannot reverse T07)" if c1 else "FALSIFIED against N4.6",
      "| H2 (protection)", "SUPPORTED in-sample against N4.6 (PROVISIONAL)" if c2 else "FALSIFIED against N4.6", "| H3 (increment)", "SUPPORTED in-sample (PROVISIONAL)" if c3p else "FALSIFIED")

    # ══ 4.6 beside T07 (and T11) ═══════════════════════════════════════════
    head("4.6  BESIDE T07 (same rule, nulls and criteria on 2019-01-02 -> 2026-10-30) AND T11 (context: the whole-book switch on this window); descriptive, no claim")
    t07 = Path(a.t07)
    if (t07 / "stats.csv").exists() and (t07 / "draws.csv").exists():
        s7_, d7_ = pd.read_csv(t07 / "stats.csv"), pd.read_csv(t07 / "draws.csv")
        S7 = lambda b, kind="segment": s7_[(s7_.book == b) & (s7_.window == "full") & (s7_.cash == "lbes") & (s7_.cost_bps == PRIMARY) & (s7_.kind == kind)].iloc[0]
        D7 = lambda b, typ: d7_[(d7_.book == b) & (d7_.window == "full") & (d7_.cash == "lbes") & (d7_.cost_bps == PRIMARY) & (d7_.draw_type == typ)]
        cmp_rows = []
        for b in BOOKS:
            x7, w7 = S7(b), S7(b, "whole_book")
            row = {"book": b, "T12 rule CAGR%": 100 * S(b).cagr, "T07 rule CAGR%": 100 * x7.cagr}
            for nm, typ in NULLS:
                row[f"T12 C1 {typ}"] = hp.loc[b, f"{nm}_pct"]
                row[f"T07 C1 {typ}"] = rank(x7.cagr, D7(b, typ).cagr.values, True)["percentile"]
            row["T12 C2 N4.6"], row["T07 C2 N4.6"] = hp.loc[b, "N46_DD_pct"], rank(x7.max_dd, D7(b, "N4.6").max_dd.values, True)["percentile"]
            row["T12 C3 pp"], row["T07 C3 pp"] = 100 * c3b[b], 100 * (x7.cagr - w7.cagr)
            cmp_rows.append(row)
        P(f"Percentiles recomputed here from T07's shipped evidence ({t07}), full window, LBES cash, 20.8 bps, {int(len(D7(BOOKS[0], 'N4.6'))):,} draws per null:")
        table(pd.DataFrame(cmp_rows), {c: (lambda x: f"{x:.1f}") for c in pd.DataFrame(cmp_rows).columns if c != "book" and "pp" not in c and "%" not in c} | {c: (lambda x: f"{x:+.2f}") for c in ("T12 C3 pp", "T07 C3 pp")} | {c: (lambda x: f"{x:.2f}") for c in ("T12 rule CAGR%", "T07 rule CAGR%")})
        t07log = Path(a.t07_log)
        if t07log.exists():
            lines = t07log.read_text(encoding="utf-8").splitlines()
            ver = [l for l in lines if re.match(r"^\s*C[123] (selection|protection|increment)", l)]
            P("T07's own verdict lines (tests/T07/analysis.log, verbatim; the first two are against N4.6, which decides):")
            for l in ver:
                P("   " + l.strip()[:200])
            mt = re.search(r"C1 selection \(H1\)\s+\w+\s+percentile >= 90 in >= 3 of 4 books: \d of 4 \(([^)]*)\)", "\n".join(lines))
            if mt:
                logged = {p.split()[0]: float(p.split()[1]) for p in mt.group(1).split(", ")}
                mine = {r_["book"][-4:]: float(r_["T07 C1 N4.6"]) for r_ in cmp_rows}  # unrounded: the log prints .1f
                same = all(abs(logged.get(k_, -1) - v_) <= 0.0500001 for k_, v_ in mine.items())
                P("   T07's logged N4.6 C1 percentiles equal the ones recomputed here:", same, "" if same else f"(logged {logged}, recomputed {mine})")
    else:
        P(f"T07's evidence not found at {t07}: the comparison is not shown")
    t11 = Path(a.t11)
    if (t11 / "stats.csv").exists():
        s11 = pd.read_csv(t11 / "stats.csv")
        rows11 = []
        for b in BOOKS:
            g = s11[(s11.book == b) & (s11.window == "full") & (s11.cash == "lbes") & (s11.cost_bps == PRIMARY)]
            pa, hpar = g[g.kind == "strategy_fixed50"], g[g.kind == "hold_parent"]
            rows11.append({"book": b, "T11 Part A CAGR%": 100 * pa.iloc[0].cagr if len(pa) else float("nan"), "T12 whole-book CAGR%": 100 * S(b, "whole_book").cagr,
                           "T11 hold-parent CAGR%": 100 * hpar.iloc[0].cagr if len(hpar) else float("nan"), "T12 parent CAGR%": 100 * S(b, "parent").cagr, "T12 rule CAGR%": 100 * S(b).cagr})
        P(f"T11's headline evidence exists ({t11}): its Part A (the whole-book switch with the fixed 50/50 sleeve) and hold-the-parent CAGRs beside T12's (20.8 bps, full window; V4(b) requires them equal):")
        table(pd.DataFrame(rows11), {c: (lambda x: f"{x:.2f}") for c in pd.DataFrame(rows11).columns if c != "book"})
        t11log = Path(a.t11_log)
        if t11log.exists():
            lines = [l for l in t11log.read_text(encoding="utf-8").splitlines() if re.match(r"^\s*(A[12]|C[1-4]) .*\s(PASS|FAIL)\s+percentile", l)]
            P("T11's own verdict lines (tests/T11/analysis.log, verbatim):")
            for l in lines[:12]:
                P("   " + l.strip()[:200])
    else:
        P(f"T11's headline evidence does not exist ({t11}): no T11 context is shown")
    P("Gates:", "all pass" if all(gates.values()) else "A GATE FAILED")
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "analysis.log").write_text(out.getvalue(), encoding="utf-8")
    print("wrote", outdir / "analysis.log")
    sys.exit(0 if (all(gates.values()) and v3["draws"] > 0) else 1)


if __name__ == "__main__":
    main()
