"""T14 analysis: reads ONLY the shipped evidence in evidence/<run>/{w1,w2}/ (and, as a historical reference for the -orig rules, the stored statistics and draws of T11 and T08)
and prints section 4 of the write-up.

    python tests/T14/analyse.py [--run headline]              prints to stdout and writes tests/T14/evidence/analysis.log
    python tests/T14/analyse.py --evidence DIR [--out DIR]    DIR holds w1/ and w2/ (e.g. the engine's smoke run); analysis.log then goes to --out (default DIR), never to tests/T14
    options: --books SCMO_0003   restrict to some books (for evidence that holds fewer than the four; the 3-of-4 verdict counts then mean nothing)
             --require-v1        fail if verify_t14.json is missing in a window folder (default: required only when the evidence directory is called 'headline')

Exit code 1 if ANY validity gate failed (the engine's audit.json gates and pass flags, regression.json, the verifier's verify_t14.json, and the checks derived here from the evidence),
or if nothing was compared. If a gate failed nothing about results is printed (only the gate block) and analysis.log is not written.

Percentile = (draws worse + 0.5 x ties) / draws x 100, ties equal within a relative 1e-12 (worse = lower CAGR, deeper drawdown); p = (1 + draws at least as good) / (draws + 1);
MDE = 2.8 x the null's SD; Holm-adjusted p per book and window over the 16 criteria (T14.md section 2.2). The outcome map is T14.md section 2.4 applied mechanically.
Imports nothing from the engine. No performance figure is typed in this file: every number comes from the evidence.

The module is also imported by report.py (class Win and the compute_* functions) so that the page and the log use one set of numbers; check_page.py shares no code with it.
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
PRIMARY = 20.8
COSTS = (0.0, PRIMARY, 50.0)
PASS_PCT = 90.0
RULES = ["50-orig", "50-half", "50-liq", "80-orig", "80-half", "80-liq"]
NEW = ["50-half", "50-liq", "80-half", "80-liq"]
ORIG_OF = {"50-half": "50-orig", "50-liq": "50-orig", "80-half": "80-orig", "80-liq": "80-orig"}
CRIT = [("E1", "cagr", "F1", "F2", "in-or-out timing, return"), ("E2", "max_dd", "F1", "F2", "in-or-out timing, worst fall"),
        ("G1", "cagr", "F3", "F4", "gold timing, return"), ("G2", "max_dd", "F3", "F4", "gold timing, worst fall")]
STAT_NAME = {"cagr": "CAGR", "max_dd": "max drawdown", "vol": "volatility", "ulcer": "Ulcer index", "days_below_10pct": "days >= 10% under peak", "longest_underwater": "longest under water", "calmar": "Calmar"}
HIGHER_BETTER = {"cagr": True, "max_dd": True, "calmar": True, "vol": False, "ulcer": False, "days_below_10pct": False, "longest_underwater": False}
SECONDARY = ["vol", "ulcer", "days_below_10pct", "longest_underwater", "calmar"]
FAM_DESC = {"F1": "in-or-out N4.10 (real gold)", "F2": "in-or-out N4.9 (real gold)", "F3": "gold N4.10-g (real in-or-out)", "F4": "gold N4.9-g (real in-or-out)", "F5": "both random"}
REG_NAMES = ("IN", "OUT-BUY", "OUT-SELL")
WIN_TXT = {"w1": "W1 (T11's inputs)", "w2": "W2 (T08's inputs)"}
STORED = {"w1": ("T11", AA / "tests" / "T11" / "evidence" / "headline"), "w2": ("T08", AA / "tests" / "T08" / "evidence" / "headline")}
STORED_KIND = {"50-orig": ("strategy_fixed50", "fixed50"), "80-orig": ("strategy", "timed")}
WORKED_DRAW = 0
DRAW_COLS = ["book", "window", "cash", "cost_bps", "family", "rule", "draw_id", "end_nav", "cagr", "max_dd", "vol", "ulcer", "days_below_10pct", "longest_underwater", "calmar",
             "sessions_invested", "invested_weeks", "out_sell_weeks", "trades_due"]
DRAW_STATS = ["cagr", "max_dd", "vol", "ulcer", "days_below_10pct", "longest_underwater", "calmar", "end_nav", "sessions_invested", "invested_weeks", "out_sell_weeks", "trades_due"]
CAPTION_W1 = "rebuilt from the parent's baskets and Eikon prices, not validated against a published NAV before 2019-01-02"


# ── small helpers ─────────────────────────────────────────────────────────────
def rank(x: float, draws: np.ndarray, higher_better: bool) -> dict:
    """worse / tied / better counts and percentile and p for one realisation among its draws (T14.md 2.2)."""
    tie = np.isclose(draws, x, rtol=1e-12, atol=0)
    better = ((draws > x) if higher_better else (draws < x)) & ~tie
    worse = ((draws < x) if higher_better else (draws > x)) & ~tie
    n = len(draws)
    return {"worse": int(worse.sum()), "tied": int(tie.sum()), "better": int(better.sum()), "draws": n, "percentile": (worse.sum() + 0.5 * tie.sum()) / n * 100,
            "p": (1 + better.sum() + tie.sum()) / (n + 1)}


def rank_full(x: float, draws: np.ndarray, higher_better: bool) -> dict:
    r = rank(x, draws, higher_better)
    sd = float(np.std(draws, ddof=1)) if len(draws) > 1 else float("nan")
    r.update({"median": float(np.median(draws)), "sd": sd, "mde": 2.8 * sd, "p05": float(np.percentile(draws, 5)), "p95": float(np.percentile(draws, 95)), "real": float(x),
              "edge": float(x - np.median(draws))})
    return r


def holm(ps) -> list[float]:
    ps = list(map(float, ps))
    m = len(ps)
    order = sorted(range(m), key=lambda i: ps[i])
    adj, run = [0.0] * m, 0.0
    for r, i in enumerate(order):
        run = max(run, min(1.0, (m - r) * ps[i]))
        adj[i] = run
    return adj


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


def rt_of(a) -> int:
    a = np.asarray(a).astype(int)
    ent = int(((a[1:] == 1) & (a[:-1] == 0)).sum()) + int(a[0] == 1)
    ext = int(((a[1:] == 0) & (a[:-1] == 1)).sum())
    return min(ent, ext)


def regime_codes(s, g) -> np.ndarray:
    s, g = np.asarray(s).astype(int), np.asarray(g).astype(int)
    return np.where(s == 1, 0, np.where(g == 1, 1, 2))


def pc(x, d=2):
    return f"{100 * x:.{d}f}%"


def pp(x, d=2):
    return f"{100 * x:+.{d}f}"


def n_pass(vals, thr=PASS_PCT) -> int:
    return int(sum(1 for v in vals if v >= thr))


def need(k: int) -> int:
    """books needed for a pass: 3 of 4 (T14.md 2.2); with fewer books than four the count is shown but means nothing."""
    return 3


# ── one window's evidence ─────────────────────────────────────────────────────
class Win:
    """Everything one window folder (evidence/<run>/w1 or w2) holds, indexed for the tables."""

    def __init__(self, ev: Path, name: str, books: list[str] | None = None):
        self.ev, self.name = Path(ev), name
        e = self.ev
        self.st = pd.read_csv(e / "stats.csv")
        self.books = [b for b in dict.fromkeys(self.st.book) if books is None or b in books]
        self.dec = pd.read_csv(e / "decisions.csv")
        self.dec3 = pd.read_csv(e / "decisions_r3.csv")
        self.ledger = pd.read_csv(e / "regime_ledger.csv")
        self.cmix = pd.read_csv(e / "constant_mix_params.csv")
        self.trades = pd.read_csv(e / "trades.csv")
        self.au = json.loads((e / "audit.json").read_text(encoding="utf-8"))
        self.rj = json.loads((e / "regression.json").read_text(encoding="utf-8"))
        self.inp = pd.read_csv(e / "inputs.csv", dtype=str, keep_default_na=False)
        self.states = np.load(e / "draw_states.npz")
        self.realz = np.load(e / "real_states.npz")
        self.r7f = pd.read_csv(e / "r7_flagged_days.csv") if (e / "r7_flagged_days.csv").exists() else pd.DataFrame()
        self.r7x = pd.read_csv(e / "r7_export.csv") if (e / "r7_export.csv").exists() else pd.DataFrame()
        self._nav = None
        self._S = {(r.book, r.window, r.cash, float(r.cost_bps), r.kind): r._asdict() for r in self.st.itertuples(index=False)}
        dr = pd.read_csv(e / "draws.csv", usecols=DRAW_COLS)
        self.D: dict[tuple, dict] = {}
        for k, g in dr.groupby(["book", "window", "cash", "cost_bps", "family", "rule"], sort=False):
            g = g.sort_values("draw_id")
            self.D[(k[0], k[1], k[2], float(k[3]), k[4], k[5])] = {c: g[c].to_numpy() for c in DRAW_STATS + ["draw_id"]}
        del dr
        self.ndraws = len(self.D[(self.books[0], "full", "lbes", PRIMARY, "F1", "50-half")]["cagr"])
        self.reg = {b: regime_codes(*self._sg(b)) for b in self.books}
        self.dates = {}

    # decisions of a book
    def dbook(self, b: str, r3: bool = False) -> pd.DataFrame:
        d = self.dec3 if r3 else self.dec
        return d[d.book == b].sort_values("j").reset_index(drop=True)

    def _sg(self, b):
        d = self.dbook(b)
        return d.state.values.astype(int), d.g.values.astype(int)

    @property
    def nav(self) -> pd.DataFrame:
        if self._nav is None:
            self._nav = pd.read_csv(self.ev / "daily_nav.csv", parse_dates=["date"])
            self._navg = {k: g.sort_values("date") for k, g in self._nav.groupby(["book", "cost_bps", "run"], sort=False)}
        return self._nav

    def curve(self, b: str, cost: float, run: str) -> tuple[np.ndarray, np.ndarray]:
        self.nav
        g = self._navg[(b, cost, run)]
        return g.date.values, g.nav.to_numpy()

    def S(self, b, kind, cost=PRIMARY, window="full", cash="lbes") -> dict:
        return self._S[(b, window, cash, float(cost), kind)]

    def draws(self, b, fam, rule, field, cost=PRIMARY, window="full", cash="lbes") -> np.ndarray:
        return self.D[(b, window, cash, float(cost), fam, rule)][field]

    def rk(self, b, fam, rule, stat, cost=PRIMARY, window="full", cash="lbes") -> dict:
        return rank_full(self.S(b, rule, cost, window, cash)[stat], self.draws(b, fam, rule, stat, cost, window, cash), HIGHER_BETTER[stat])

    def has_draws(self, b, fam, rule, cost=PRIMARY, window="full", cash="lbes") -> bool:
        return (b, window, cash, float(cost), fam, rule) in self.D

    def start_end(self, b: str) -> tuple[str, str]:
        d, _ = self.curve(b, PRIMARY, "50-orig")
        return str(pd.Timestamp(d[0]).date()), str(pd.Timestamp(d[-1]).date())

    def r3_dates(self, b: str) -> tuple[str, str]:
        d = self.dbook(b, True)
        return str(d.decision_date.iloc[0]), str(self.start_end(b)[1])

    # weekly sessions: decision j's target is in force from trade session t_j (j=0: session 0) to t_{j+1}; the last runs to the last session
    def wsess(self, b: str) -> np.ndarray:
        d = self.dbook(b)
        T = len(self.curve(b, PRIMARY, "50-orig")[0])
        t = np.array([0] + [int(i) + 1 for i in d.decision_idx.values[1:]] + [T - 1])
        t = np.minimum(t, T - 1)
        return np.diff(t)

    def regime_counts(self, b: str) -> dict:
        reg, ws = self.reg[b], self.wsess(b)
        spells_ = [n for v, n in runs(reg) if v == 2]
        s, g = self._sg(b)
        return {"decisions": len(reg), "sessions": int(ws.sum()), **{f"weeks_{REG_NAMES[c]}": int((reg == c).sum()) for c in range(3)},
                **{f"sess_{REG_NAMES[c]}": int(ws[reg == c].sum()) for c in range(3)}, "out_sell_spells": len(spells_), "out_sell_lengths": spells_, "round_trips": rt_of(s),
                "first_state": "IN" if s[0] else "OUT"}


# ── gates ─────────────────────────────────────────────────────────────────────
def prereg_hash(doc_path: Path) -> tuple[str, str]:
    doc = doc_path.read_text(encoding="utf-8")
    region = doc[doc.index("\n## 1. Idea and references") + 1:doc.index("\n## 4. Results") + 1]
    region = "\n".join(l.rstrip() for l in region.replace("\r\n", "\n").split("\n"))
    m = re.search(r"§1–§3 sha256:\*\* `([^`]*)`", doc)
    return (m.group(1) if m else "?"), hashlib.sha256(region.encode("utf-8")).hexdigest()


def check_gates(W: Win, require_v1: bool) -> tuple[bool, list[str]]:
    """The validity gates of one window; every line printed. Returns (all passed, lines)."""
    L, ok_all = [], True

    def line(name, ok, msg):
        nonlocal ok_all
        ok_all &= bool(ok)
        L.append(f"{W.name.upper()}  {name:<32} {'PASS' if ok else 'FAIL'}  {msg}")

    gates = W.au.get("gates", {})
    bad = [k for k, v in gates.items() if v is not True]
    line("engine gates (audit.json)", bool(gates) and not bad, f"{len(gates)} gates: " + ", ".join(f"{k}={'ok' if v is True else v}" for k, v in gates.items()))
    fl = flags(W.au)
    line("engine pass flags (audit.json)", bool(fl) and all(fl), f"{len(fl)} flags, {sum(1 for x in fl if not x)} false")
    fr = flags(W.rj)
    line("V4 regression (regression.json)", bool(fr) and all(fr), f"{len(fr)} flags, {sum(1 for x in fr if not x)} false; keys: {', '.join(W.rj.keys())}")
    v2 = W.au.get("v2", {})
    line("V2 point in time (audit.json)", v2.get("checks", 0) > 0 and v2.get("violations", 1) == 0 and bool(v2.get("pass")),
         f"{v2.get('violations')} violations of {v2.get('checks'):,} checks; trades after their decision {v2.get('recorded_trades_after_their_decision')}; basket changes on their availableDate session {v2.get('recorded_basket_changes_on_or_after_availableDate')}")
    vj = W.ev / "verify_t14.json"
    if vj.exists():
        v = json.loads(vj.read_text(encoding="utf-8"))
        st_ = v.get("selftest")
        ok = bool(v.get("exit_ok")) and v.get("gate_failures_and_missing", 0) == 0 and v.get("gate_compared", 1) > 0 and (st_ is None or bool(st_.get("detected")))
        line("V1 independent check", ok, f"verify_t14.py: exit_ok {v.get('exit_ok')}, comparisons {v.get('gate_compared', 'n/a'):,}" if isinstance(v.get("gate_compared"), int) else f"verify_t14.py: exit_ok {v.get('exit_ok')}")
        if ok and isinstance(st_, dict):
            L.append(f"{W.name.upper()}  {'':<32}       corrupted copy detected: {st_.get('detected')}")
    else:
        line("V1 independent check", not require_v1, f"{vj.name} NOT FOUND ({'required' if require_v1 else 'not required for this evidence directory'})")
    # derived here from the evidence files
    bad_nav = 0
    n_nav = 0
    for b in W.books:
        for cost in COSTS:
            for rule in RULES + ["hold_parent"]:
                _, nv = W.curve(b, cost, rule)
                n_nav += 1
                bad_nav += int(abs(nv[-1] / W.S(b, rule, cost)["end_nav"] - 1) > 1e-9 or abs(nv[0] - 1) > 1e-12)
    line("NAV file vs stats.csv", bad_nav == 0 and n_nav > 0, f"{n_nav} runs: start NAV 1 and end NAV equal to stats.csv, {bad_nav} differ")
    nd_bad, ngr = 0, 0
    for (b, w_, c_, cost, fam, rule), g in W.D.items():
        ngr += 1
        nd_bad += int(len(g["draw_id"]) != W.ndraws or (g["draw_id"] != np.arange(W.ndraws)).any())
    miss = [k for k in W.D if k[5] == "50-orig" and not all((k[0], k[1], k[2], k[3], k[4], r) in W.D for r in RULES)]
    line("draws.csv structure", nd_bad == 0 and not miss and ngr > 0, f"{ngr} (book, window, cash, cost, family, rule) groups of {W.ndraws:,} draws with ids 0..n-1; {nd_bad} irregular; groups lacking one of the six rules: {len(miss)}")
    dd, ncommon, extra = 0, 0, []
    d0 = W.dbook(W.books[0]).set_index("decision_date")
    for b in W.books[1:]:
        db = W.dbook(b).set_index("decision_date")
        com = d0.index.intersection(db.index)
        ncommon += len(com)
        dd += int((d0.loc[com, ["state", "g", "regime"]].values != db.loc[com, ["state", "g", "regime"]].values).any())
        if len(db) != len(d0):
            extra.append(f"{b} has {len(db)} decisions against {len(d0)} ({', '.join(sorted(set(map(str, d0.index)) ^ set(map(str, db.index))))} in one only)")
    line("the books' decision series agree", dd == 0, f"{len(W.books)} books; on the {ncommon} decision dates the others share with {W.books[0]}, {dd} book(s) differ" + (f"; {'; '.join(extra)}" if extra else ""))
    rc = {b: W.regime_counts(b) for b in W.books}
    rt_min, sp_min = min(r["round_trips"] for r in rc.values()), min(r["out_sell_spells"] for r in rc.values())
    d3 = [W.dbook(b, True) for b in W.books]
    line("reportability (T14.md 2.2)", rt_min >= 4 and sp_min >= 4,
         f"fewest over the books: {rt_min} in-or-out round trips (need >= 4), {sp_min} OUT-SELL spells (need >= 4); decisions per book {', '.join(str(r['decisions']) for r in rc.values())}; R3: round trips "
         f"{min(rt_of(d.state.values) for d in d3)}, OUT-SELL spells {min(len([1 for v, n in runs(regime_codes(d.state.values, d.g.values)) if v == 2]) for d in d3)}")
    return ok_all, L


def ref_check(W: Win) -> tuple[bool, list[str], list[dict]]:
    """The -orig rules against the stored statistics and draws of T11 (W1) / T08 (W2): the real statistic and the percentile among the first n draws, full window, LBES, 20.8 bps."""
    tag, d = STORED[W.name]
    rows, L = [], []
    if not (d / "stats.csv").exists() or not (d / "draws.csv").exists():
        return False, [f"{W.name.upper()}  {'REF -orig rules vs stored':<32} FAIL  stored {tag} evidence not found at {d}"], rows
    ss = pd.read_csv(d / "stats.csv")
    sd = pd.read_csv(d / "draws.csv", usecols=["book", "window", "cash", "cost_bps", "family", "sleeve_mode", "draw_id", "cagr", "max_dd"])
    sd = sd[(sd.window == "full") & (sd.cash == "lbes") & (sd.cost_bps == PRIMARY) & (sd.draw_id < W.ndraws)]
    for b in W.books:
        for rule, (kind, mode) in STORED_KIND.items():
            srow = ss[(ss.book == b) & (ss.window == "full") & (ss.cash == "lbes") & (ss.cost_bps == PRIMARY) & (ss.kind == kind)].iloc[0]
            for fam in ("F1", "F3"):
                g = sd[(sd.book == b) & (sd.family == fam) & (sd.sleeve_mode == mode)].sort_values("draw_id")
                if g.empty:
                    continue
                for stat in ("cagr", "max_dd"):
                    ours = rank(W.S(b, rule)[stat], W.draws(b, fam, rule, stat), True)
                    theirs = rank(float(srow[stat]), g[stat].to_numpy(), True)
                    rows.append({"window": W.name, "book": b, "rule": rule, "family": fam, "stat": stat, "ours": ours["percentile"], "stored": theirs["percentile"], "p_ours": ours["p"], "p_stored": theirs["p"],
                                 "real_rel_diff": abs(W.S(b, rule)[stat] - float(srow[stat])) / max(1e-300, abs(float(srow[stat]))), "n": len(g), "tag": tag})
    bad = [r for r in rows if abs(r["ours"] - r["stored"]) > 1e-9 or abs(r["p_ours"] - r["p_stored"]) > 1e-12 or r["real_rel_diff"] > 1e-9]
    ok = len(rows) > 0 and not bad
    L.append(f"{W.name.upper()}  {'REF -orig rules vs stored':<32} {'PASS' if ok else 'FAIL'}  the -orig rules against {tag}'s stored statistics and draws (first {W.ndraws:,} draws): {len(rows)} percentiles compared, "
             f"{len(bad)} differ; largest percentile difference {max((abs(r['ours'] - r['stored']) for r in rows), default=float('nan')):.2e}, largest real-statistic relative difference "
             f"{max((r['real_rel_diff'] for r in rows), default=float('nan')):.2e}")
    return ok, L, rows


# ── computations shared with report.py ────────────────────────────────────────
def compute_criteria(W: Win, cost=PRIMARY, window="full", cash="lbes", rules=NEW, crits=CRIT, with_holm=True) -> list[dict]:
    """One dict per (rule, criterion): per-book rank dicts against the deciding null (and the null beside it), pass count, verdict, Holm p per book (family: the window's 16 criteria)."""
    rows = []
    for r in rules:
        for cr, stat, fam, fam2, txt in crits:
            per = {b: W.rk(b, fam, r, stat, cost, window, cash) for b in W.books}
            per2 = {b: W.rk(b, fam2, r, stat, cost, window, cash) for b in W.books} if W.has_draws(W.books[0], fam2, r, cost, window, cash) else None
            npass = n_pass([per[b]["percentile"] for b in W.books])
            rows.append({"window": W.name, "rule": r, "crit": cr, "stat": stat, "fam": fam, "fam2": fam2, "txt": txt, "per": per, "per2": per2, "n_pass": npass, "pass": npass >= need(len(W.books)),
                         "n2_pass": n_pass([per2[b]["percentile"] for b in W.books]) if per2 else None})
    if with_holm and rules == NEW and crits == CRIT:
        for b in W.books:
            hp = holm([r["per"][b]["p"] for r in rows])
            for r, h in zip(rows, hp):
                r.setdefault("holm", {})[b] = h
    return rows


def compute_dtable(W: Win, cost=PRIMARY, window="full", cash="lbes") -> list[dict]:
    rows = []
    for b in W.books:
        for r in RULES:
            s = W.S(b, r, cost, window, cash)
            row = {"window": W.name, "book": b, "rule": r, **{k: s[k] for k in ("end_nav", "cagr", "max_dd", "calmar", "vol", "trades", "cost_paid", "sessions")}}
            if r in ORIG_OF:
                o = W.S(b, ORIG_OF[r], cost, window, cash)
                row.update({f"d_{k}": s[k] - o[k] for k in ("cagr", "max_dd", "calmar", "vol", "end_nav")})
            rows.append(row)
    return rows


def compute_r6(W: Win, cost=PRIMARY, window="full", cash="lbes") -> list[dict]:
    """The paired contrast: Delta_d = statistic(variant, draw d) - statistic(orig, draw d) over every F1 and every F3 draw; the real Delta ranked among them."""
    rows = []
    for v, o in ORIG_OF.items():
        for b in W.books:
            for fam in ("F1", "F3"):
                for stat in ("cagr", "max_dd"):
                    dv, do = W.D[(b, window, cash, float(cost), fam, v)], W.D[(b, window, cash, float(cost), fam, o)]
                    assert (dv["draw_id"] == do["draw_id"]).all()
                    delta = dv[stat] - do[stat]
                    real = W.S(b, v, cost, window, cash)[stat] - W.S(b, o, cost, window, cash)[stat]
                    # ties: relative tolerance of the rank function is relative to |real|; a real difference of exactly 0 ties every exactly-0 draw difference
                    r = rank_full(real, delta, True) if real != 0 else _rank_zero(delta)
                    rows.append({"window": W.name, "variant": v, "orig": o, "book": b, "fam": fam, "stat": stat, "cost": cost, **r})
    return rows


def _rank_zero(delta: np.ndarray) -> dict:
    tie = delta == 0
    n = len(delta)
    worse, better = int((delta < 0).sum()), int((delta > 0).sum())
    sd = float(np.std(delta, ddof=1))
    return {"worse": worse, "tied": int(tie.sum()), "better": better, "draws": n, "percentile": (worse + 0.5 * tie.sum()) / n * 100, "p": (1 + better + tie.sum()) / (n + 1), "median": float(np.median(delta)),
            "sd": sd, "mde": 2.8 * sd, "p05": float(np.percentile(delta, 5)), "p95": float(np.percentile(delta, 95)), "real": 0.0, "edge": 0.0 - float(np.median(delta))}


def outcome_rows(W: Win, crit_rows: list[dict], r6_rows: list[dict], orig_rows: list[dict]) -> list[dict]:
    """T14.md 2.4 applied mechanically to one window: per base sleeve (50, 80) and variant (half, liq)."""
    out = []
    for v in NEW:
        o = ORIG_OF[v]
        dc = {b: W.S(b, v)["cagr"] - W.S(b, o)["cagr"] for b in W.books}
        dd = {b: W.S(b, v)["max_dd"] - W.S(b, o)["max_dd"] for b in W.books}
        pos, neg = sum(1 for x in dc.values() if x > 0), sum(1 for x in dc.values() if x < 0)
        r6 = {fam: {b: next(r for r in r6_rows if r["variant"] == v and r["book"] == b and r["fam"] == fam and r["stat"] == "cagr")["percentile"] for b in W.books} for fam in ("F1", "F3")}
        r6n = {fam: n_pass(list(r6[fam].values())) for fam in r6}
        direction = "positive" if pos >= 3 else "negative" if neg >= 3 else "mixed"

        def pattern(fam):
            if direction == "positive":
                return "P1 improves, because of when the gold signal places it (PROVISIONAL)" if r6n[fam] >= 3 else "P2 improves, but not by timing: the holding earned it (exposure)"
            return "P3 makes the rule worse" if direction == "negative" else "no pattern: CAGR difference positive in %d and negative in %d of %d books" % (pos, neg, len(W.books))
        crit = {c: next(r for r in crit_rows if r["rule"] == v and r["crit"] == c) for c in ("E1", "E2", "G1", "G2")}
        ocrit = {c: next(r for r in orig_rows if r["rule"] == o and r["crit"] == c) for c in ("E1", "E2")}
        eq = {}
        for c in ("E1", "E2"):
            vp, op = crit[c]["pass"], ocrit[c]["pass"]
            dpct = np.mean([crit[c]["per"][b]["percentile"] - ocrit[c]["per"][b]["percentile"] for b in W.books])
            eq[c] = (vp, op, float(dpct))
        dis = [f"{r['crit']} {r['fam']}:{'pass' if r['pass'] else 'fail'} vs {r['fam2']}:{'pass' if r['n2_pass'] >= 3 else 'fail'}" for r in (crit[c] for c in crit)
               if r["n2_pass"] is not None and (r["pass"] != (r["n2_pass"] >= 3))]
        out.append({"window": W.name, "variant": v, "orig": o, "d_cagr": dc, "d_dd": dd, "pos": pos, "neg": neg, "direction": direction, "r6": r6, "r6n": r6n, "pattern_F1": pattern("F1"), "pattern_F3": pattern("F3"),
                    "eq": eq, "g": {c: crit[c]["pass"] for c in ("G1", "G2")}, "disagree": dis})
    return out


# ── printing ──────────────────────────────────────────────────────────────────
OUT: dict[str, list[str]] = {}
CUR = ["pre"]


def sec(name):
    CUR[0] = name
    OUT.setdefault(name, [])


def P(*a):
    OUT[CUR[0]].append(" ".join(str(x) for x in a))


def table(df: pd.DataFrame, fmt: dict | None = None):
    d = df.copy()
    for c, f in (fmt or {}).items():
        if c in d:
            d[c] = d[c].map(lambda v: "" if (isinstance(v, float) and math.isnan(v)) else f(v))
    P(d.to_string(index=False))


def head(title: str):
    OUT[CUR[0]] += ["", "=" * 100, title, "=" * 100]


def bk(b: str) -> str:
    return b[-4:]


def crit_df(rows, W: Win, cost=PRIMARY) -> pd.DataFrame:
    recs = []
    for r in rows:
        rec = {"rule": r["rule"], "crit": r["crit"], "null": r["fam"], "stat": STAT_NAME[r["stat"]]}
        for b in W.books:
            rec[bk(b)] = f"{r['per'][b]['percentile']:.1f}"
        rec["books>=90"] = f"{r['n_pass']}/{len(W.books)}"
        rec["verdict"] = "PASS" if r["pass"] else "FAIL"
        recs.append(rec)
    return pd.DataFrame(recs)


def sess_note(W: Win) -> str:
    return f"{W.name.upper()} ({', '.join(W.books)})"


def window_line(W: Win) -> str:
    b = W.books[0]
    a, z = W.start_end(b)
    return f"{WIN_TXT[W.name]}: NAV from {a} to {z}"


def print_header(Ws: dict[str, Win], run_name: str, ev: Path, doc_hash: tuple[str, str]):
    sec("pre")
    W0 = next(iter(Ws.values()))
    P("T14 analysis. Run:", run_name, "| draws per book, cost, rule and null:", f"{W0.ndraws:,}",
      "| deciding nulls: F1 (E1, E2: in-or-out N4.10, real gold) and F3 (G1, G2: gold N4.10-g, real in-or-out); F2 and F4 beside them; F5 = robustness R5")
    for n, W in Ws.items():
        b = W.books[0]
        a, z = W.start_end(b)
        rc = W.regime_counts(b)
        P(f"{WIN_TXT[n]}: {len(W.books)} book(s) ({', '.join(W.books)}); NAV {a} -> {z} ({rc['sessions'] + 1:,} sessions); first decision {W.dbook(b).decision_date.iloc[0]}, last decision {W.dbook(b).decision_date.iloc[-1]}; "
          f"{rc['decisions']} weekly decisions" + (f" (per book: {', '.join(bk(x) + ' ' + str(W.regime_counts(x)['decisions']) for x in W.books)}; the books' draws are per book)" if len({W.regime_counts(x)['decisions'] for x in W.books}) > 1 else "") + f"; first state {rc['first_state']}; IN {rc['weeks_IN']}, OUT-BUY {rc['weeks_OUT-BUY']}, OUT-SELL {rc['weeks_OUT-SELL']} weeks; "
          f"OUT-SELL spells {rc['out_sell_spells']} (lengths {', '.join(map(str, rc['out_sell_lengths']))}); in-or-out round trips {rc['round_trips']}; R3 window from {W.r3_dates(b)[0]}")
    P("Pre-registration sha256 in the T14.md header:", doc_hash[0][:16], "| recomputed now:", doc_hash[1][:16], "| match:", doc_hash[0] == doc_hash[1])
    P("Evidence read:", ", ".join(f"{n}/{p.name}" for n, W in Ws.items() for p in sorted(W.ev.iterdir()) if p.is_file()))
    if any(len(W.books) < 4 for W in Ws.values()):
        P("NOTE: fewer than four books in this evidence: every 'books >= 90 of k' count and every verdict below means nothing (a development run).")
    P("POWER NOTE: " + "; ".join(f"{n.upper()}: {W.regime_counts(W.books[0])['round_trips']} round trips and {W.regime_counts(W.books[0])['out_sell_spells']} OUT-SELL spells (shared by the books)" for n, W in Ws.items()) +
      ". The effective sample for the change is the OUT-SELL spells; LOW POWER: a FAIL mostly means 'not distinguishable from chance'. The minimum detectable edge (2.8 x null SD) is printed beside every FAIL.")
    P(f"DATA CAVEATS: W1: the rebuilt parent NAV is {CAPTION_W1}; manual Eikon exports for delisted stocks are held in W1 (R7); the sessions 2017-10-19 and the GOLDBEES gap use stand-ins; price returns only; "
      "the cash file's source before 2026-08-10 is unrecorded (F-AA-D09), which matters most in -liq (100% of the regime holding is cash); BOTH WINDOWS ARE SEEN: T06, T08, T11, T13 ran the original rules on these weeks before "
      "the variants were proposed, so any finding is PROVISIONAL at most and there is NO HOLD-OUT. Picking the best of the six rules from these tables is a selection on seen data.")
    P("CONVENTIONS: returns in %, differences in pp (percentage points of CAGR; drawdown differences in pp of drawdown, positive = shallower); CAGR = end NAV ^ (252 / (sessions - 1)) - 1; years = (sessions - 1) / 252; "
      "max drawdown = min over t of NAV_t / max(NAV_s, s <= t) - 1; Calmar = CAGR / |max drawdown|; volatility = SD of daily returns x sqrt(252); 20.8 bps = 10.4 bps a side on every value traded "
      "(0 and 50 as robustness); percentile = (draws worse + 0.5 ties) / draws x 100; p = (1 + draws at least as good) / (draws + 1); MDE = 2.8 x SD of the null's statistic.")


def print_gates(Ws, gate_lines, ref_lines, ok):
    sec("4.0b")
    head("4.0b  GATES\n(V1 independent check, V2 point in time, V3 the nulls hold their tables, V4 identities and regressions, V5 the samplers are exact, V6 trade and cost identities; reportability)")
    for l in gate_lines:
        P(l)
    for l in ref_lines:
        P(l)
    P("ALL VALIDITY GATES PASS: results below may be read." if ok else "A VALIDITY GATE FAILED: nothing below may be read; fix, new run directory.")


def pick_trades(W: Win, b: str, pick_rule: str = "50-half"):
    """The worked trades: the first OUT-SELL spell of pick_rule that holds an in-regime parent rebalance (else the first spell): its regime_in trade, its regime_out trade and the basket_change inside (20.8 bps)."""
    tr = W.trades
    tr = tr[(tr.book == b) & (tr.cost_bps == PRIMARY)]
    ent = ext = bch = None
    t_ = tr[tr.run == pick_rule].sort_values("idx")
    ins, outs = t_[t_.kind == "regime_in"], t_[t_.kind == "regime_out"]
    for _, i0 in ins.iterrows():
        o0 = outs[outs.idx > i0.idx]
        if o0.empty:
            continue
        o0 = o0.iloc[0]
        bc = t_[(t_.kind == "basket_change") & (t_.idx > i0.idx) & (t_.idx < o0.idx)]
        if ent is None:
            ent, ext = i0, o0
        if not bc.empty:
            ent, ext, bch = i0, o0, bc.iloc[0]
            break
    return ent, ext, bch, pick_rule


def print_worked(W: Win):
    b = W.books[0]
    a_, z_ = W.start_end(b)
    d = W.dbook(b)
    head(f"{WIN_TXT[W.name]}  book {b}  NAV {a_} -> {z_}")
    tr = W.trades
    tr = tr[(tr.book == b) & (tr.cost_bps == PRIMARY)]
    ent, ext, bch, pick_rule = pick_trades(W, b)
    # one decision: the decision that caused the entry shown below (the first OUT-SELL spell that holds an in-regime parent rebalance)
    reg = W.reg[b]
    j_in = int(ent.dec_j) if ent is not None else None
    P("\nOne decision (the decision behind the regime entry below): the latest Master row of each index and of MAUc1 dated on or before the decision date; IN iff all three SIGN BUY; g = MAUc1 SIGN BUY.")
    if j_in is not None:
        r = d.iloc[j_in]
        P(f"  decision j = {j_in}, date {r.decision_date}; signs: Nifty100 {r.sign_Nifty100} (row {r.label_Nifty100}), Midcap100 {r.sign_MC100} (row {r.label_MC100}), Smallcap100 {r.sign_SC100} (row {r.label_SC100}); "
          f"all three BUY: {bool(r.all_three_buy)}; MAUc1 {r.sign_MAUc1} (row {r.label_MAUc1}); regime {r.regime}; previous week's regime {d.regime.iloc[j_in - 1]}; trade on the next session {r.trade_date}")
        P("  targets (e = parent share, gw = GOLDBEES share of the rest): " + "; ".join(f"{ru} ({r[f'e_{ru}']:g}, {r[f'gw_{ru}']:g})" for ru in RULES))
        if ext is not None:
            r2 = d.iloc[int(ext.dec_j)]
            P(f"  the decision behind the regime exit: j = {int(ext.dec_j)}, date {r2.decision_date}: Nifty100 {r2.sign_Nifty100}, Midcap100 {r2.sign_MC100}, Smallcap100 {r2.sign_SC100}, MAUc1 {r2.sign_MAUc1}; regime {r2.regime}; trade on {r2.trade_date}")
    else:
        P("  no OUT-SELL entry in this window")
    cols = ["date", "kind", "e_after", "gw_after", "basket_eff", "V", "traded", "cost", "stock_before", "gold_before", "cash_before", "stock_after", "gold_after", "cash_after", "nav_close_after", "dec_j"]

    def show(title, row, run_):
        P(f"\n{title}: rule {run_}, cost {PRIMARY} bps")
        if row is None:
            P("  none in this window for this rule")
            return
        P("  " + "; ".join(f"{c} {row[c]:.8g}" if isinstance(row[c], (float, np.floating)) and not pd.isna(row[c]) else f"{c} {row[c]}" for c in cols))
        V, tra, cost = float(row.V), float(row.traded), float(row.cost)
        P(f"  cost = traded x {PRIMARY} / 2 / 1e4 = {tra:.8g} x {PRIMARY / 2e4:.6g} = {tra * PRIMARY / 2e4:.8g} (stored {cost:.8g}); value after cost = V - cost = {V - cost:.8g}; "
          f"stock_after + gold_after + cash_after = {row.stock_after + row.gold_after + row.cash_after:.8g}; the book's NAV at that session's close = {row.nav_close_after:.8g}")
        if row.kind in ("regime_in",):
            P(f"  half-regime identity: stock_after / (V - cost) = {row.stock_after / (V - cost):.12f}, gold_after / (V - cost) = {row.gold_after / (V - cost):.12f}, cash_after = {row.cash_after:.3g}")
        if row.kind == "basket_change":
            P(f"  D1 partial trade: stock_after = stock_before - cost = {row.stock_before:.8g} - {cost:.8g} = {row.stock_before - cost:.8g} (stored {row.stock_after:.8g}); GOLDBEES before and after {row.gold_before:.8g} / {row.gold_after:.8g}; cash {row.cash_before:.3g} / {row.cash_after:.3g}")
    show("One regime entry (a trade into OUT-SELL)", ent, pick_rule)
    if ent is not None:
        P("  the same entry in the other rules (same session): " + "; ".join(
            f"{ru}: {tr[(tr.run == ru) & (tr.idx == ent.idx)].kind.iloc[0] if ((tr.run == ru) & (tr.idx == ent.idx)).any() else 'no trade'}"
            + (f", gold_after {float(tr[(tr.run == ru) & (tr.idx == ent.idx)].gold_after.iloc[0]):.6g}, stock_after {float(tr[(tr.run == ru) & (tr.idx == ent.idx)].stock_after.iloc[0]):.6g}, cash_after {float(tr[(tr.run == ru) & (tr.idx == ent.idx)].cash_after.iloc[0]):.6g}"
               if ((tr.run == ru) & (tr.idx == ent.idx)).any() else "") for ru in RULES if ru != pick_rule))
    show("One regime exit (a trade out of OUT-SELL)", ext, pick_rule)
    show("One in-regime parent rebalance (basket change while the rule holds half the parent)", bch, pick_rule)
    if ent is not None:
        dts, nv = W.curve(b, PRIMARY, pick_rule)
        i = int(ent.idx)
        P(f"\n  the daily NAV of {pick_rule} around the entry (NAV_t = cash_t + sum of units x close_t; base 1.0 at the close of {pd.Timestamp(dts[0]).date()}): "
          + "; ".join(f"{pd.Timestamp(dts[k]).date()} {nv[k]:.6f}" for k in (i - 1, i, i + 1)))
    # one path
    ru = pick_rule or "50-half"
    dts, nv = W.curve(b, PRIMARY, ru)
    yrs = (len(nv) - 1) / 252
    dd = nv / np.maximum.accumulate(nv) - 1
    tr_i = int(np.argmin(dd))
    pk = int(np.argmax(nv[:tr_i + 1]))
    s = W.S(b, ru)
    P(f"\nThe result of one path ({ru}, {PRIMARY} bps, {pd.Timestamp(dts[0]).date()} -> {pd.Timestamp(dts[-1]).date()}): NAV starts at {nv[0]:.6f} on {pd.Timestamp(dts[0]).date()} and ends at {nv[-1]:.6f} on {pd.Timestamp(dts[-1]).date()}; "
      f"{len(nv):,} sessions, years = ({len(nv):,} - 1) / 252 = {yrs:.4f}; CAGR = {nv[-1]:.6f} ^ (1 / {yrs:.4f}) - 1 = {pc(nv[-1] ** (1 / yrs) - 1, 4)} (stats.csv {pc(s['cagr'], 4)}); "
      f"max drawdown = {pc(dd.min(), 4)} (peak {pd.Timestamp(dts[pk]).date()}, trough {pd.Timestamp(dts[tr_i]).date()}; stats.csv {pc(s['max_dd'], 4)}); trades {int(s['trades'])}, cost paid {s['cost_paid']:.6f} of the starting NAV")
    # F1 draw
    real_io = W.realz[f"{b}|full|io"].astype(int)
    real_g = W.realz[f"{b}|full|gold"].astype(int)
    nm = lambda v: "IN " if v else "out"
    gm = lambda v: "BUY " if v else "SELL"
    A = W.states[f"{b}|full|io|N4.10"][WORKED_DRAW].astype(int)
    P(f"\nOne F1 draw (N4.10 in-or-out, id {WORKED_DRAW}, seed {W.au['run']['seeds']['io410']}): the real in-or-out series and the draw over the first 20 weekly decisions "
      f"(the draw keeps the real series' {len(lens(real_io, 1))} in-spells and {len(lens(real_io, 0))} out-spells, its {int(real_io.sum())} IN weeks of {len(real_io)}, and redraws the lengths within the bounds); the real gold signal stays")
    rows = []
    for j in range(20):
        rows.append({"j": j, "decision": d.decision_date.iloc[j], "real": nm(real_io[j]), "draw": nm(A[j]), "MAUc1": gm(real_g[j]), "real regime": REG_NAMES[reg[j]],
                     "draw regime": REG_NAMES[int(regime_codes([A[j]], [real_g[j]])[0])], "50-half e (draw)": f"{rule_e('half', A[j], real_g[j]):g}"})
    table(pd.DataFrame(rows))
    for ru_ in ("50-half", "50-orig"):
        gr = {c: W.draws(b, "F1", ru_, c)[WORKED_DRAW] for c in ("end_nav", "cagr", "max_dd", "out_sell_weeks", "invested_weeks", "sessions_invested", "trades_due")}
        P(f"  F1 draw {WORKED_DRAW}, rule {ru_}: end NAV {gr['end_nav']:.6f}, CAGR {pc(gr['cagr'], 4)}, max drawdown {pc(gr['max_dd'], 4)}, IN weeks {int(gr['invested_weeks'])}, OUT-SELL weeks {int(gr['out_sell_weeks'])}, "
          f"sessions invested {int(gr['sessions_invested'])}, trades due {int(gr['trades_due'])}; the real rule's CAGR {pc(W.S(b, ru_)['cagr'], 4)}")
    P(f"  the draw's full in-spells {'|'.join(map(str, lens(A, 1)))} and out-spells {'|'.join(map(str, lens(A, 0)))} (real: {'|'.join(map(str, lens(real_io, 1)))} and {'|'.join(map(str, lens(real_io, 0)))})")
    G = W.states[f"{b}|full|gold|N4.10-g"][WORKED_DRAW].astype(int)
    P(f"\nOne F3 draw (N4.10-g gold, id {WORKED_DRAW}, seed {W.au['run']['seeds']['g410']}): the real in-or-out series stays, the MAUc1 BUY/SELL weeks are redrawn (the real signal has {len(lens(real_g, 1))} BUY spells, {len(lens(real_g, 0))} SELL spells, "
      f"{int(real_g.sum())} BUY weeks of {len(real_g)}); the first 20 weekly decisions")
    rows = []
    for j in range(20):
        rows.append({"j": j, "decision": d.decision_date.iloc[j], "in-or-out": nm(real_io[j]), "real MAUc1": gm(real_g[j]), "draw MAUc1": gm(G[j]), "real regime": REG_NAMES[reg[j]],
                     "draw regime": REG_NAMES[int(regime_codes([real_io[j]], [G[j]])[0])], "50-half e (draw)": f"{rule_e('half', real_io[j], G[j]):g}"})
    table(pd.DataFrame(rows))
    for ru_ in ("50-half", "80-half"):
        gr = {c: W.draws(b, "F3", ru_, c)[WORKED_DRAW] for c in ("end_nav", "cagr", "max_dd", "out_sell_weeks", "trades_due")}
        P(f"  F3 draw {WORKED_DRAW}, rule {ru_}: end NAV {gr['end_nav']:.6f}, CAGR {pc(gr['cagr'], 4)}, max drawdown {pc(gr['max_dd'], 4)}, OUT-SELL weeks {int(gr['out_sell_weeks'])}, trades due {int(gr['trades_due'])}; "
          f"the real rule's CAGR {pc(W.S(b, ru_)['cagr'], 4)}")
    # one ranking
    P(f"\nOne ranking (criterion E1, rule 80-half, book {b}, {PRIMARY} bps, {a_} -> {z_}): the rule's CAGR placed among the {W.ndraws:,} F1 draws' CAGRs of the same rule")
    for crn, stat, fam in (("E1", "cagr", "F1"), ("E2", "max_dd", "F1")):
        r = W.rk(b, fam, "80-half", stat)
        P(f"  {crn} {STAT_NAME[stat]}: real {pc(r['real'], 4)}; draws below {r['worse']:,}, equal {r['tied']}, above {r['better']:,} (of {r['draws']:,}); percentile = ({r['worse']:,} + 0.5 x {r['tied']}) / {r['draws']:,} x 100 = {r['percentile']:.2f}; "
          f"p = (1 + {r['better'] + r['tied']:,}) / ({r['draws']:,} + 1) = {r['p']:.4f}; null median {pc(r['median'], 4)}; edge = real - median = {pp(r['edge'], 3)} pp; null SD {100 * r['sd']:.3f} pp, MDE = 2.8 x SD = {100 * r['mde']:.3f} pp")
    # comparators
    P(f"\nThe comparators on the same path ({PRIMARY} bps, {a_} -> {z_}): hold the parent = the parent's basket bought at T0 and held through its rebalances (cost on those trades): CAGR "
      f"{pc(W.S(b, 'hold_parent')['cagr'], 2)}, max drawdown {pc(W.S(b, 'hold_parent')['max_dd'], 2)}; constant mix at the rule's own averages (cmix_{ru}): CAGR {pc(W.S(b, 'cmix_' + ru)['cagr'], 2)}, "
      f"parent share f = {float(W.cmix[(W.cmix.book == b) & (W.cmix.rule == ru)].f.iloc[0]):.4f} (mean of e over the decisions), GOLDBEES share of the rest = {float(W.cmix[(W.cmix.book == b) & (W.cmix.rule == ru)].gw_bar.iloc[0]):.4f}; "
      f"the rule's own CAGR {pc(W.S(b, ru)['cagr'], 2)}")


def rule_e(kind: str, s, g) -> float:
    return 1.0 if s else (0.5 if (kind == "half" and not g) else 0.0)


def print_headline(W: Win, crit_rows, orig_rows, ref_rows, sec_name="4.1"):
    n = W.ndraws
    a, z = W.start_end(W.books[0])
    head(f"{WIN_TXT[W.name]}  NAV {a} -> {z}, {PRIMARY} bps, {n:,} draws per book, rule and null")
    P("\nPercentile of each NEW rule's CAGR / max drawdown among its own rule's draws, per book (higher = better than more of the random placements); PASS = percentile >= 90 in at least 3 of the books.\n"
      "E1/E2 against F1 (in-or-out N4.10, real gold signal), G1/G2 against F3 (gold N4.10-g, real in-or-out).")
    table(crit_df(crit_rows, W))
    P("\np-value = (1 + draws at least as good) / (draws + 1), per book; Holm-adjusted p per book over this window's 16 criteria (family of 16, N6.8); both beside the percentile, not instead of it.")
    recs = []
    for r in crit_rows:
        rec = {"rule": r["rule"], "crit": r["crit"]}
        for b in W.books:
            rec[f"p {bk(b)}"] = f"{r['per'][b]['p']:.4f}"
        for b in W.books:
            rec[f"Holm {bk(b)}"] = f"{r['holm'][b]:.4f}"
        recs.append(rec)
    table(pd.DataFrame(recs))
    P("\nDetail per book: the real statistic, the null's median / SD / 5th / 95th percentile, the edge (real - median) and the minimum detectable edge MDE = 2.8 x null SD (pp of CAGR or of drawdown); draws below / equal / above.")
    recs = []
    for r in crit_rows:
        for b in W.books:
            x = r["per"][b]
            recs.append({"rule": r["rule"], "crit": r["crit"], "book": bk(b), "real": pc(x["real"]), "null median": pc(x["median"]), "SD pp": f"{100 * x['sd']:.2f}", "5th": pc(x["p05"]), "95th": pc(x["p95"]),
                         "edge pp": pp(x["edge"]), "MDE pp": f"{100 * x['mde']:.2f}", "below/eq/above": f"{x['worse']}/{x['tied']}/{x['better']}", "pctile": f"{x['percentile']:.1f}"})
    table(pd.DataFrame(recs))
    P(f"\nVERDICT TABLE ({a} -> {z}, {PRIMARY} bps): one row per criterion; a FAIL is read as 'undetectable below the MDE', never as 'no effect'.")
    recs = []
    for r in crit_rows:
        mdes = [100 * r["per"][b]["mde"] for b in W.books]
        recs.append({"window": W.name.upper(), "rule": r["rule"], "crit": r["crit"], "statistic": STAT_NAME[r["stat"]], "null": r["fam"], "books >= 90": f"{r['n_pass']} of {len(W.books)}",
                     "verdict": "PASS" if r["pass"] else "FAIL", "undetectable below (pp)": "" if r["pass"] else f"{min(mdes):.2f}-{max(mdes):.2f}",
                     "min Holm p": f"{min(r['holm'].values()):.4f}", "F2/F4 verdict": "" if r["n2_pass"] is None else ("PASS" if r["n2_pass"] >= 3 else "FAIL") + f" ({r['n2_pass']} of {len(W.books)})"})
    table(pd.DataFrame(recs))
    P(f"  window summary: {sum(1 for r in crit_rows if r['pass'])} of {len(crit_rows)} criteria PASS")
    P("\nSecondary statistics (each with its own percentile, deciding null, per book; volatility, Ulcer index, days >= 10% under peak and longest under water: LOWER is better):")
    recs = []
    for r in NEW:
        for fam in ("F1", "F3"):
            for stat in SECONDARY:
                rec = {"rule": r, "null": fam, "statistic": STAT_NAME[stat]}
                for b in W.books:
                    rec[bk(b)] = f"{W.rk(b, fam, r, stat)['percentile']:.1f}"
                recs.append(rec)
    table(pd.DataFrame(recs))
    P(f"\nThe -orig rules, REFERENCE ONLY (not judged; {a} -> {z}, {PRIMARY} bps): the same percentiles. 50-orig does not use the gold signal, so under F3 every draw equals the real rule (all tied, percentile 50).")
    table(crit_df(orig_rows, W))
    tag = STORED[W.name][0]
    rr = [r for r in ref_rows if r["window"] == W.name]
    P(f"\nCheck against {tag}'s stored percentiles (first {n:,} draws of the stored file; full window, LBES, {PRIMARY} bps): identical to the stored values")
    recs = [{"rule": r["rule"], "null": r["family"], "stat": STAT_NAME[r["stat"]], "book": bk(r["book"]), "T14": f"{r['ours']:.4f}", f"{tag} stored": f"{r['stored']:.4f}", "difference": f"{abs(r['ours'] - r['stored']):.1e}"} for r in rr]
    table(pd.DataFrame(recs))
    P("\nF2 beside F1 and F4 beside F3 (the same percentile against N4.9 / N4.9-g; agreement of the verdict is in the verdict table; R4 below prints the per-book pairs).")
    recs = []
    for r in crit_rows:
        if r["per2"] is None:
            continue
        rec = {"rule": r["rule"], "crit": r["crit"], "null beside": r["fam2"]}
        for b in W.books:
            rec[bk(b)] = f"{r['per2'][b]['percentile']:.1f}"
        rec["books>=90"] = f"{r['n2_pass']}/{len(W.books)}"
        rec["verdict"] = "PASS" if r["n2_pass"] >= 3 else "FAIL"
        recs.append(rec)
    table(pd.DataFrame(recs))


def dtable_df(rows, fmt_cost_note=True) -> pd.DataFrame:
    recs = []
    for r in rows:
        rec = {"book": bk(r["book"]), "rule": r["rule"], "CAGR": pc(r["cagr"]), "dCAGR pp": pp(r["d_cagr"]) if "d_cagr" in r else "", "max DD": pc(r["max_dd"]), "dMaxDD pp": pp(r["d_max_dd"]) if "d_max_dd" in r else "",
               "Calmar": f"{r['calmar']:.3f}", "dCalmar": f"{r['d_calmar']:+.3f}" if "d_calmar" in r else "", "vol": pc(r["vol"]), "dVol pp": pp(r["d_vol"]) if "d_vol" in r else "",
               "end NAV": f"{r['end_nav']:.4f}", "trades": int(r["trades"]), "cost paid %NAV0": f"{100 * r['cost_paid']:.3f}"}
        recs.append(rec)
    return pd.DataFrame(recs)


def print_dtable(W: Win, cost: float, window="full", cash="lbes", title=None):
    rows = compute_dtable(W, cost, window, cash)
    a, z = W.start_end(W.books[0]) if window == "full" else W.r3_dates(W.books[0])
    P(f"\n{title or 'D-table'}: {WIN_TXT[W.name]}, window {window}, cash {cash}, {cost} bps, {a} -> {z}. Each new rule beside its own original; d = new minus original (CAGR, volatility in pp; max drawdown in pp, positive = shallower; Calmar in units). "
      "Per-book dates in 4.2's regime table.")
    table(dtable_df(rows))


def print_regime_table(W: Win):
    recs = []
    for b in W.books:
        c = W.regime_counts(b)
        a, z = W.start_end(b)
        recs.append({"book": bk(b), "from": a, "to": z, "sessions": c["sessions"] + 1, "decisions": c["decisions"], "IN wk": c["weeks_IN"], "OUT-BUY wk": c["weeks_OUT-BUY"], "OUT-SELL wk": c["weeks_OUT-SELL"],
                     "IN sess": c["sess_IN"], "OUT-BUY sess": c["sess_OUT-BUY"], "OUT-SELL sess": c["sess_OUT-SELL"], "OUT-SELL spells": c["out_sell_spells"], "round trips": c["round_trips"]})
    P(f"\nWeeks and sessions in each regime ({WIN_TXT[W.name]}; weeks = weekly decisions; sessions = the sessions from each decision's trade session to the next one's, so a regime's sessions sum to the window's sessions - 1):")
    table(pd.DataFrame(recs))


def print_trades_table(W: Win):
    recs = []
    for b in W.books:
        for r in RULES:
            s = W.S(b, r)
            recs.append({"book": bk(b), "rule": r, "trades": int(s["trades"]), "switch": int(s["switch_trades"]), "sleeve": int(s["sleeve_trades"]), "regime": int(s["regime_trades"]), "basket": int(s["basket_trades"]),
                         "cost paid %NAV0": f"{100 * s['cost_paid']:.3f}", "weeks e>0": int(s["invested_weeks"])})
    P(f"\nTrades and cost paid by kind ({PRIMARY} bps, {WIN_TXT[W.name]}; cost paid = sum of traded x bps / 2 / 1e4 in units of the starting NAV 1):")
    table(pd.DataFrame(recs))


def print_comparators(W: Win):
    recs = []
    for b in W.books:
        kinds = ["hold_parent", "50-orig", "80-orig", "constant_mix", "constant_mix_timed", "sleeve_only", "sleeve_only_timed"] + [f"cmix_{r}" for r in RULES]
        for k in kinds:
            s = W.S(b, k)
            rec = {"book": bk(b), "comparator": k, "CAGR": pc(s["cagr"]), "max DD": pc(s["max_dd"]), "Calmar": f"{s['calmar']:.3f}", "vol": pc(s["vol"]), "end NAV": f"{s['end_nav']:.4f}"}
            if k.startswith("cmix_"):
                r_ = k[5:]
                p_ = W.cmix[(W.cmix.book == b) & (W.cmix.rule == r_)].iloc[0]
                rec.update({"parent share f": f"{p_.f:.4f}", "GOLDBEES of rest": f"{p_.gw_bar:.4f}", "rule - its mix (pp CAGR)": pp(W.S(b, r_)["cagr"] - s["cagr"])})
            recs.append(rec)
    a, z = W.start_end(W.books[0])
    P(f"\nComparators (benchmarks, not nulls; {WIN_TXT[W.name]}, {a} -> {z}, {PRIMARY} bps): hold the parent; the two -orig rules; constant_mix = f in the parent (f = share of IN weeks), the rest 50/50 GOLDBEES/cash, "
      "rebalanced every decision; constant_mix_timed = the same with the rest split by the gold signal (80/20 or 20/80); sleeve_only(_timed) = 100% sleeve (50/50, or timed 80/20 / 20/80); "
      "cmix_<rule> = f the rule's own mean parent share (mean of e over the decisions) and the rule's own GOLDBEES share of the non-parent part (sum of (1-e) gw / sum of (1-e)), rebalanced at every decision and basket change.")
    table(pd.DataFrame(recs).fillna(""))


def print_ledger(W: Win):
    L = W.ledger[(W.ledger.window == "full") & W.ledger.book.isin(W.books)]
    a, z = W.start_end(W.books[0])
    P(f"\nRegime ledger ({WIN_TXT[W.name]}, {a} -> {z}): one row per OUT-SELL spell per book. A spell runs from the close of its first decision's session to the close of the session of the decision that ends it "
      "(or the last session); parent = hold_parent (0 bps) NAV over the span, GOLDBEES = its close, cash = the LBES level; each rule's return over the span at 20.8 bps = NAV_end / NAV_start - 1 (not re-based: it includes the "
      "trade costs at entry and exit).")
    recs = []
    for r in L.to_dict("records"):
        rec = {"book": bk(r["book"]), "#": r["spell_no"], "first decision": r["first_decision"], "last decision": r["last_decision"], "weeks": r["weeks"], "span from close": r["span_from_close"],
               "span to close": r["span_to_close"], "from": r["entered_from"], "to": r["exited_to"], "parent": pc(r["parent_return"]), "GOLDBEES": pc(r["goldbees_return"]), "cash": pc(r["cash_return"])}
        for ru in RULES:
            rec[ru] = pc(r[f"ret_{ru}"])
        recs.append(rec)
    table(pd.DataFrame(recs))
    P("\nWhich spells carry the difference: per book and new rule, the spells in which the rule's return beat its original's, and the sum over the spells of (rule - original) in pp of spell return:")
    recs = []
    for b in W.books:
        lb = L[L.book == b]
        for v in NEW:
            d = lb[f"ret_{v}"].values - lb[f"ret_{ORIG_OF[v]}"].values
            recs.append({"book": bk(b), "rule": v, "spells": len(lb), "spells beating original": int((d > 0).sum()), "sum of differences pp": pp(d.sum()), "best spell": f"#{int(lb.spell_no.values[np.argmax(d)])} {pp(d.max())}",
                         "worst spell": f"#{int(lb.spell_no.values[np.argmin(d)])} {pp(d.min())}"})
    table(pd.DataFrame(recs))


def print_r6(W: Win, rows6, cost=PRIMARY):
    a, z = W.start_end(W.books[0])
    P(f"\nR6 paired contrast ({WIN_TXT[W.name]}, {a} -> {z}, {cost} bps, LBES): every F1 and every F3 draw is run with the original target and with the variant's (the engine stores all six rules for the same draw id); "
      "Delta_d = statistic(variant, draw d) - statistic(original, draw d), for CAGR and for max drawdown (positive = better); the real Delta (D-table difference) is placed among the Delta_d with the percentile formula. "
      "A difference that ranks near 50 is exposure, not timing.")
    recs = []
    for r in rows6:
        recs.append({"variant": r["variant"], "vs": r["orig"], "null": r["fam"], "stat": STAT_NAME[r["stat"]], "book": bk(r["book"]), "real Delta pp": pp(r["real"]), "median Delta pp": pp(r["median"]), "SD pp": f"{100 * r['sd']:.2f}",
                     "below/eq/above": f"{r['worse']}/{r['tied']}/{r['better']}", "pctile": f"{r['percentile']:.1f}", "p": f"{r['p']:.4f}"})
    table(pd.DataFrame(recs))
    P("\nR6 summary: books with paired percentile >= 90 (of the books):")
    recs = []
    for v in NEW:
        for fam in ("F1", "F3"):
            for stat in ("cagr", "max_dd"):
                x = [r for r in rows6 if r["variant"] == v and r["fam"] == fam and r["stat"] == stat]
                recs.append({"variant": v, "null": fam, "stat": STAT_NAME[stat], "books >= 90": f"{n_pass([r['percentile'] for r in x])} of {len(x)}", "percentiles": ", ".join(f"{r['percentile']:.1f}" for r in x)})
    table(pd.DataFrame(recs))


def print_outcome(W: Win, rows):
    a, z = W.start_end(W.books[0])
    P(f"\nOutcome map ({WIN_TXT[W.name]}, {a} -> {z}, {PRIMARY} bps), T14.md 2.4 applied mechanically. 'positive in >= 3 books' is read on the CAGR difference (variant - original) of the D-table; 'R6 paired percentile >= 90' is read "
      "as in >= 3 of the books on the CAGR contrast, printed against F1 and against F3 separately (the map names no null).")
    for r in rows:
        v, o = r["variant"], r["orig"]
        P(f"\n  {v} against {o}: CAGR difference by book " + ", ".join(f"{bk(b)} {pp(x)} pp" for b, x in r["d_cagr"].items()) + f"; max-drawdown difference " + ", ".join(f"{bk(b)} {pp(x)} pp" for b, x in r["d_dd"].items()))
        P(f"    positive in {r['pos']}, negative in {r['neg']} of {len(W.books)} books; R6 CAGR percentile vs F1: " + ", ".join(f"{bk(b)} {x:.1f}" for b, x in r["r6"]["F1"].items()) + f" ({r['r6n']['F1']} >= 90); vs F3: " +
          ", ".join(f"{bk(b)} {x:.1f}" for b, x in r["r6"]["F3"].items()) + f" ({r['r6n']['F3']} >= 90)")
        P(f"    pattern, R6 against F1: {r['pattern_F1']}")
        P(f"    pattern, R6 against F3: {r['pattern_F3']}")
        for c in ("E1", "E2"):
            vp, op, dp = r["eq"][c]
            concl = ("the change keeps the switch's result" if vp and op else "the change weakens the result" if op and not vp else "the original did not pass, the variant passes" if vp else "neither passes")
            P(f"    {c}: {v} {'PASS' if vp else 'FAIL'}, {o} {'PASS' if op else 'FAIL'} (reference); mean percentile change on the common draws {dp:+.1f} points -> {concl}")
        for c in ("G1", "G2"):
            P(f"    {c}: {v} {'PASS' if r['g'][c] else 'FAIL'}" + (" -> the gold signal picks the right weeks for this regime holding (per the map)" if r["g"][c] else ""))
        P(f"    F1/F2 or F3/F4 disagree: {'; '.join(r['disagree']) if r['disagree'] else 'no'}")


def print_windows_agree(rows_by_win):
    if len(rows_by_win) < 2:
        return
    P("\nThe two windows against each other (per variant; pattern = direction of the CAGR difference in >= 3 books and, if positive, whether the R6 paired percentile reached 90 in >= 3 books; "
      "the 2019-2026 window (W2) is the one the live product traded):")
    for v in NEW:
        cls = {}
        for w, rows in rows_by_win.items():
            r = next(x for x in rows if x["variant"] == v)
            cls[w] = (r["direction"], r["r6n"]["F1"] >= 3 if r["direction"] == "positive" else None, r["r6n"]["F3"] >= 3 if r["direction"] == "positive" else None)
        agree = len(set(cls.values())) == 1
        P(f"  {v}: " + "; ".join(f"{w.upper()} {c[0]}" + ("" if c[1] is None else f", R6>=90 vs F1 {'yes' if c[1] else 'no'}, vs F3 {'yes' if c[2] else 'no'}") for w, c in cls.items()) + f" -> windows {'agree' if agree else 'DISAGREE: report both, no general statement'}")


def print_robustness(Ws: dict[str, Win]):
    for n, W in Ws.items():
        a, z = W.start_end(W.books[0])
        head(f"{WIN_TXT[W.name]}: robustness R1-R7 (NAV {a} -> {z})")
        P("\nR1. All criteria at 0 and 50 bps (percentile per book; before cost = 0 bps; the primary 20.8 is in 4.1):")
        for cost in (0.0, 50.0):
            rows = compute_criteria(W, cost=cost, with_holm=False)
            P(f"\n  {cost} bps:")
            table(crit_df(rows, W))
        for cost in (0.0, 50.0):
            print_dtable(W, cost, title=f"R1 D-table at {cost} bps")
            rows6 = compute_r6(W, cost)
            P(f"\n  R6 at {cost} bps, CAGR percentile of the paired contrast (F1 | F3), per book:")
            recs = []
            for v in NEW:
                rec = {"variant": v}
                for fam in ("F1", "F3"):
                    for b in W.books:
                        rec[f"{fam} {bk(b)}"] = f"{next(r for r in rows6 if r['variant'] == v and r['fam'] == fam and r['stat'] == 'cagr' and r['book'] == b)['percentile']:.1f}"
                recs.append(rec)
            table(pd.DataFrame(recs))
        P(f"\nR2. LIQUIDCASE as the cash leg ({'whole window' if W.name == 'w1' else 'from 2024-01-24, LBES before'}): E1 and G1 and the D-table, {PRIMARY} bps. For -liq the whole regime holding is cash.")
        if (W.books[0], "full", "liq", PRIMARY, "F1", "50-half") in W.D:
            rows = compute_criteria(W, cash="liq", crits=[c for c in CRIT if c[0] in ("E1", "G1")], with_holm=False)
            table(crit_df(rows, W))
            print_dtable(W, PRIMARY, cash="liq", title="R2 D-table (LIQUIDCASE)")
        else:
            P("  no R2 draws in this evidence")
        a3, z3 = W.r3_dates(W.books[0])
        P(f"\nR3. Window {a3} -> {z3} ({'T11 R3, its own spells, bounds and nulls' if W.name == 'w1' else 'T08 live decisions: its own spells and totals, the full-window bounds'}): E1 and G1 and the D-table, {PRIMARY} bps.")
        d3 = W.dbook(W.books[0], True)
        P(f"  {len(d3)} decisions, first state {'IN' if d3.state.iloc[0] else 'OUT'}, OUT-SELL weeks {int((regime_codes(d3.state.values, d3.g.values) == 2).sum())}, in-or-out round trips {rt_of(d3.state.values)}, "
          f"OUT-SELL spells {len([1 for v, n_ in runs(regime_codes(d3.state.values, d3.g.values)) if v == 2])}")
        if (W.books[0], "r3", "lbes", PRIMARY, "F1", "50-half") in W.D:
            rows = compute_criteria(W, window="r3", crits=[c for c in CRIT if c[0] in ("E1", "G1")], with_holm=False)
            table(crit_df(rows, W))
            print_dtable(W, PRIMARY, window="r3", title="R3 D-table")
        P(f"\nR4. Agreement of F1 with F2 and of F3 with F4 per book ({PRIMARY} bps, full window): percentile against each, the verdict flag (>= 90 or not), and the null's median / SD / 5th / 95th of CAGR and of max drawdown.")
        recs = []
        for v in NEW:
            for cr, stat, fam, fam2, txt in CRIT:
                for b in W.books:
                    x1, x2 = W.rk(b, fam, v, stat), W.rk(b, fam2, v, stat)
                    recs.append({"rule": v, "crit": cr, "book": bk(b), f"pct {fam}": f"{x1['percentile']:.1f}", f"pct {fam2}": f"{x2['percentile']:.1f}", "verdicts agree": "yes" if (x1["percentile"] >= 90) == (x2["percentile"] >= 90) else "NO",
                                 f"{fam} median": pc(x1["median"]), f"{fam} SD pp": f"{100 * x1['sd']:.2f}", f"{fam} 5th": pc(x1["p05"]), f"{fam} 95th": pc(x1["p95"]), f"{fam2} median": pc(x2["median"]),
                                 f"{fam2} SD pp": f"{100 * x2['sd']:.2f}"})
        table(pd.DataFrame(recs))
        tag = STORED[W.name][0]
        P(f"  Reference: {tag}'s stored percentiles for the original rules are reproduced in 4.1 (identical to the stored values).")
        P(f"\nR5. Percentile against F5 (both timings random; one F1 and one F3 draw of the same id), {PRIMARY} bps: CAGR and max drawdown per book (pass mark 90 in >= 3 books is applied for information only).")
        recs = []
        for v in NEW + ["50-orig", "80-orig"]:
            for stat in ("cagr", "max_dd"):
                rec = {"rule": v, "stat": STAT_NAME[stat]}
                xs = [W.rk(b, "F5", v, stat) for b in W.books]
                for b, x in zip(W.books, xs):
                    rec[bk(b)] = f"{x['percentile']:.1f}"
                rec["books>=90"] = f"{n_pass([x['percentile'] for x in xs])}/{len(xs)}"
                recs.append(rec)
        table(pd.DataFrame(recs))
        P("\nR6. The paired contrast: see 4.3.")
        if n == "w1":
            print_r7(W)


def print_r7(W: Win):
    P("\nR7 (W1 only). Price-quality sensitivity (T11's): stock-days with a >= 20% one-day close move on held stocks set to zero return (r7_flagged) and the manual-export stocks' bars set to zero return (r7_noexport); "
      "0 and 20.8 bps; the variant's difference from its original under each:")
    recs = []
    for b in W.books:
        for cost in (0.0, PRIMARY):
            for tag in ("", "_r7_flagged", "_r7_noexport"):
                for v in NEW:
                    try:
                        s, o = W.S(b, v + tag, cost), W.S(b, ORIG_OF[v] + tag, cost)
                    except KeyError:
                        continue
                    recs.append({"book": bk(b), "cost": cost, "variant of the data": tag[1:] or "as run", "rule": v, "CAGR": pc(s["cagr"]), "orig CAGR": pc(o["cagr"]), "dCAGR pp": pp(s["cagr"] - o["cagr"]),
                                 "max DD": pc(s["max_dd"]), "dMaxDD pp": pp(s["max_dd"] - o["max_dd"])})
    table(pd.DataFrame(recs))
    P("  hold the parent, as run vs flagged vs no export (CAGR, 20.8 bps): " + "; ".join(f"{bk(b)} " + " / ".join(pc(W.S(b, 'hold_parent' + t)['cagr']) for t in ("", "_r7_flagged", "_r7_noexport")) for b in W.books))
    P(f"  flagged stock-days: {len(W.r7f)}" + (f" ({', '.join(sorted(set(W.r7f.book.astype(str) + ':' + W.r7f.stock.astype(str))))})" if len(W.r7f) else "") + f"; manual-export stock rows held: {len(W.r7x)}"
      + ("".join(f"; {r.book} {r.stock}: {int(r.held_sessions_export)} held sessions" for r in W.r7x.itertuples()) if len(W.r7x) else ""))


def print_power(Ws: dict[str, Win], rows_by_win):
    for n, W in Ws.items():
        a, z = W.start_end(W.books[0])
        rc = W.regime_counts(W.books[0])
        head(f"{WIN_TXT[W.name]}: power, MDE and sessions invested (NAV {a} -> {z})")
        P(f"\nEffective sample: {rc['out_sell_spells']} OUT-SELL spells (lengths {', '.join(map(str, rc['out_sell_lengths']))}); {rc['round_trips']} in-or-out round trips; {rc['decisions']} weekly decisions; "
          f"{len(W.books)} books sharing one market and one decision series (one sample seen {len(W.books)} times); {W.ndraws:,} draws per book, cost, rule and null.")
        P(f"MDE = 2.8 x SD of the null's statistic, {PRIMARY} bps, full window, pp (CAGR or max drawdown) per book:")
        recs = []
        for r in rows_by_win[n]:
            rec = {"rule": r["rule"], "crit": r["crit"], "stat": STAT_NAME[r["stat"]], "null": r["fam"]}
            for b in W.books:
                rec[f"SD {bk(b)}"] = f"{100 * r['per'][b]['sd']:.2f}"
            for b in W.books:
                rec[f"MDE {bk(b)}"] = f"{100 * r['per'][b]['mde']:.2f}"
            recs.append(rec)
        table(pd.DataFrame(recs))
        P("\nSessions invested (the parent held; weekly decisions held exactly in the in-or-out nulls, sessions only approximately, F-AA-M06). Real = sessions of the IN regime; F1 / F2 = the draws' sessions_invested "
          "(draws.csv; invested weeks are identical in every draw):")
        recs = []
        for b in W.books:
            s_ = W.regime_counts(b)
            row = {"book": bk(b), "real IN weeks": s_["weeks_IN"], "real IN sessions": s_["sess_IN"], "of (sessions - 1)": s_["sessions"]}
            for fam in ("F1", "F2"):
                x = W.draws(b, fam, "50-orig", "sessions_invested")
                row.update({f"{fam} mean": f"{x.mean():.1f}", f"{fam} min": int(x.min()), f"{fam} max": int(x.max())})
            ws = W.wsess(b)
            A = W.states[f"{b}|full|io|N4.10"].astype(np.int64)
            row["F1 recomputed from states (max |diff|)"] = int(np.abs(A @ ws - W.draws(b, "F1", "50-orig", "sessions_invested")).max())
            recs.append(row)
        table(pd.DataFrame(recs))
        P("\nOUT-SELL weeks in the draws (the regime the change acts on; not held by the nulls): real weeks and the draws' mean / min / max out_sell_weeks of the rule, F1 and F3:")
        recs = []
        for b in W.books:
            row = {"book": bk(b), "real OUT-SELL weeks": W.regime_counts(b)["weeks_OUT-SELL"]}
            for fam in ("F1", "F3"):
                x = W.draws(b, fam, "50-half", "out_sell_weeks")
                row.update({f"{fam} mean": f"{x.mean():.1f}", f"{fam} min": int(x.min()), f"{fam} max": int(x.max())})
            recs.append(row)
        table(pd.DataFrame(recs))
        P("\nTrades due per draw (F1 / F3, rule 50-half vs 50-orig; real rule's trades in the D-table): mean " + "; ".join(
            f"{bk(b)} F1 {W.draws(b, 'F1', '50-half', 'trades_due').mean():.1f} (50-orig {W.draws(b, 'F1', '50-orig', 'trades_due').mean():.1f}), F3 {W.draws(b, 'F3', '50-half', 'trades_due').mean():.1f} (50-orig {W.draws(b, 'F3', '50-orig', 'trades_due').mean():.1f})" for b in W.books))


# ── main ──────────────────────────────────────────────────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="headline")
    ap.add_argument("--evidence", default=None, help="evidence directory holding w1/ and w2/ (overrides --run)")
    ap.add_argument("--out", default=None, help="where analysis.log goes (default tests/T14/evidence for --run, the evidence directory for --evidence)")
    ap.add_argument("--doc", default=str(HERE / "T14.md"), help="T14.md, read only, for the pre-registration hash")
    ap.add_argument("--books", default=None)
    ap.add_argument("--require-v1", action="store_true")
    a = ap.parse_args()
    ev = Path(a.evidence) if a.evidence else HERE / "evidence" / a.run
    outdir = Path(a.out) if a.out else (ev if a.evidence else HERE / "evidence")
    books = a.books.split(",") if a.books else None
    require_v1 = a.require_v1 or ev.name == "headline"
    Ws = {}
    for w in ("w1", "w2"):
        if (ev / w / "audit.json").exists():
            Ws[w] = Win(ev / w, w, books)
    if not Ws:
        print(f"no window evidence under {ev} (w1/audit.json, w2/audit.json)")
        return 1
    doc_hash = prereg_hash(Path(a.doc))
    gate_lines, ok = [], True
    ref_rows, ref_lines = [], []
    for w, W in Ws.items():
        o, L = check_gates(W, require_v1)
        ok &= o
        gate_lines += L
        o2, L2, rows = ref_check(W)
        ok &= o2
        ref_lines += L2
        ref_rows += rows
    pre_ok = doc_hash[0] == doc_hash[1]
    ok &= pre_ok
    gate_lines.append(f"ALL   pre-registration hash               {'PASS' if pre_ok else 'FAIL'}  T14.md header {doc_hash[0][:16]} vs recomputed {doc_hash[1][:16]}")
    missing = [w for w in ("w1", "w2") if w not in Ws]
    if missing and a.evidence is None:
        ok = False
        gate_lines.append(f"ALL   both windows present                FAIL  missing {missing}")
    if not ok:
        sec("4.0b")
        head("4.0b  GATES")
        for l in gate_lines + ref_lines:
            P(l)
        P("A VALIDITY GATE FAILED: nothing below may be read; fix, new run directory. (No results are printed; analysis.log is not written.)")
        print("\n".join(OUT["4.0b"]))
        return 1
    # results
    print_header(Ws, ev.name if a.evidence is None else str(ev), ev, doc_hash)
    sec("4.0a")
    head("4.0a  THE WORKED EXAMPLE: a regime entry, a regime exit, an in-regime basket change, one F1 draw, one F3 draw, one ranking")
    for W in Ws.values():
        print_worked(W)
    print_gates(Ws, gate_lines, ref_lines, ok)
    crit_by, orig_by, r6_by, out_by = {}, {}, {}, {}
    for w, W in Ws.items():
        crit_by[w] = compute_criteria(W)
        orig_by[w] = compute_criteria(W, rules=["50-orig", "80-orig"], with_holm=False)
        r6_by[w] = compute_r6(W)
        out_by[w] = outcome_rows(W, crit_by[w], r6_by[w], orig_by[w])
    sec("4.1")
    head("4.1  HEADLINE: E1, E2 (against F1) and G1, G2 (against F3) for the four new rules, per window; verdict table")
    for w, W in Ws.items():
        print_headline(W, crit_by[w], orig_by[w], ref_rows)
    P("\nMultiplicity: 16 criteria per window, 32 in all, each judged at 90 unadjusted (continuity with T06/T08/T11); the Holm p above is per book over the window's 16. E1/E2 of the four rules share draws and are not independent, nor are "
      "-half on the two bases. Picking the best of the six rules from these tables is itself a selection on seen data.")
    sec("4.2")
    head("4.2  THE DESCRIPTIVE HEADLINE: the D-table, trades and cost, the regime ledger, the comparators")
    for w, W in Ws.items():
        head(f"{WIN_TXT[W.name]}")
        print_regime_table(W)
        print_dtable(W, PRIMARY, title="D-table (primary)")
        print_trades_table(W)
        print_ledger(W)
        print_comparators(W)
    sec("4.3")
    head("4.3  R6: THE PAIRED CONTRAST (the chance check on the difference from the original rule)")
    for w, W in Ws.items():
        head(f"{WIN_TXT[W.name]}")
        print_r6(W, r6_by[w])
    sec("4.4")
    head("4.4  ROBUSTNESS R1-R7")
    print_robustness(Ws)
    sec("4.5")
    head("4.5  OUTCOME MAP (T14.md 2.4), applied mechanically; no interpretation")
    for w, W in Ws.items():
        head(f"{WIN_TXT[W.name]}")
        print_outcome(W, out_by[w])
    print_windows_agree(out_by)
    sec("4.6")
    head("4.6  POWER, THE MINIMUM DETECTABLE EDGE AND SESSIONS INVESTED")
    print_power(Ws, crit_by)
    text = "\n".join(l for k in ("pre", "4.0a", "4.0b", "4.1", "4.2", "4.3", "4.4", "4.5", "4.6") for l in OUT.get(k, []))
    print(text)
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "analysis.log").write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
