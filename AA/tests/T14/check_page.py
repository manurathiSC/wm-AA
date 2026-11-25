"""check_page.py: re-derives every number and every date on the T14 results page from the raw evidence and counts checks and failures (AGENT.md R10).

    python tests/T14/check_page.py [page.html] [--run headline | --evidence DIR]      exit 1 on any failure, or if nothing was checked

Shares no code with the engine, the verifier, analyse.py or report.py: it reads the evidence files (stats.csv, decisions*.csv, daily_nav.csv, draws.csv, trades.csv, regime_ledger.csv, constant_mix_params.csv,
inputs.csv, draw_states.npz, real_states.npz) with its own functions and re-implements the percentile, p, Holm, regime counts, ledger and histogram binning.

What is checked
  1. every  <span class="v" data-k KEY data-v RAW data-t UNIT data-d D>TEXT</span>:  RAW equals the value recomputed from the evidence (relative 1e-9) and TEXT is RAW formatted to D decimals in UNIT;
  2. every  <span class="s" data-k KEY data-s STRING>: STRING equals the string recomputed from the evidence (verdicts, outcome-map codes, signs, dates, input rows, in/out states);
  3. every  <span class="dt" data-dates "w|book|window">: its text is 'first date → last date' of that series in the evidence; every element of class needs-dates (each table, figure, example) contains one;
  4. every formula: each <a class="fref"> points at an existing formula box, each card lists the formulas it uses and links to all of them, and every formula the page needs exists and is not empty;
  5. every chart: lines-data (the arrays of the growth curves, every 5th session) equals the daily NAV of the evidence (rounded to 4 decimals) with the same dates; bars-data (histograms) equals the bins recomputed from
     draws.csv (40 bins between the extremes padded by 2%), with the marks at the real value and the null median; every svg has its data and its hover handles (crosshair, level chip, timestamp chip, tooltip);
  6. every date written anywhere in the text of the page is a date of the evidence or of T14.md; the pre-registration hash on the page equals the one recomputed from T14.md.

KEY grammar (w = w1|w2, b = book, window = full|r3, cash = lbes|liq, cost = 0.0|20.8|50.0):
  st:w|b|window|cash|cost|kind|field   dt:w|b|window|cash|cost|variant|field   rk:w|b|window|cash|cost|fam|rule|stat|what   hl:w|b|rule|crit   np:w|window|cash|cost|fam|rule|stat   npass:w ncrit:w nbooks:w ndraws:w
  r6:w|b|cost|variant|fam|stat|what   rc:w|b|field   led:w|b|spell|field   n:sessions|w|b   dc:/ds:w|b|j|col   tr:w|b|run|cost|idx|kind|field   tr2:...|vmc   nv:w|b|cost|run|date   nvd:w|b|cost|run|k
  dr:w|b|window|cash|cost|fam|rule|id|field   cm:w|b|rule|f|gw_bar   dt7:w|b|window|cash|cost|variant|tag|field   dm:w|b|window|cash|cost|fam|rule|field|mean|min|max   in:w|file|field
  vd:w|rule|crit   vdr:w|window|cash|cost|rule|crit   pt:w|variant|fam   stw:w|b|real|io|j  stw:w|b|real|gold|j  stw:w|b|io|N4.10|id|j  stw:w|b|gold|N4.10-g|id|j   h:... and d:... (histogram ids)
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

import numpy as np
import pandas as pd

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
RULES = ["50-orig", "50-half", "50-liq", "80-orig", "80-half", "80-liq"]
NEWR = ["50-half", "50-liq", "80-half", "80-liq"]
ORIG = {"50-half": "50-orig", "50-liq": "50-orig", "80-half": "80-orig", "80-liq": "80-orig"}
CRITS = [("E1", "F1", "cagr"), ("E2", "F1", "max_dd"), ("G1", "F3", "cagr"), ("G2", "F3", "max_dd")]
NEED_FORMULAS = ["nav", "cost", "e_gw", "cagr", "maxdd", "calmar", "vol", "cmix", "d", "pct", "pval", "mde", "holm", "r6", "ledger"]
DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
N_CHECKS = 0
FAILS: list[str] = []


def chk(name: str, ok: bool, detail: str = ""):
    global N_CHECKS
    N_CHECKS += 1
    if not ok:
        FAILS.append(f"{name}: {detail}")


def close(a: float, b: float, rel=1e-9, ab=1e-12) -> bool:
    return abs(a - b) <= max(ab, rel * max(abs(a), abs(b)))


# ── the page ──────────────────────────────────────────────────────────────────
class Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.spans, self.cards, self.frefs, self.fboxes, self.svgs, self.text, self.scripts = [], [], [], {}, [], [], {}
        self._span = None
        self._stack = []
        self._script = None
        self._fbox = None
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = a.get("class", "")
        if tag == "style":
            self._skip += 1
        if tag == "script":
            self._script = a.get("id", "?")
            self.scripts[self._script] = ""
        if tag == "span" and cls in ("v", "s", "dt"):
            self._span = {"cls": cls, "a": a, "t": ""}
        if tag in ("section", "figure") and "needs-dates" in cls.split():
            self._stack.append({"tag": tag, "formulas": [x for x in a.get("data-formulas", "").split(",") if x], "dt": 0, "fref": [], "title": a.get("data-formulas", "")})
        if tag == "a" and "fref" in cls.split():
            h = a.get("href", "")
            self.frefs.append(h)
            if self._stack:
                self._stack[-1]["fref"].append(h[3:] if h.startswith("#f-") else h)
        if tag == "div" and "formula" in cls.split():
            self._fbox = {"id": a.get("id", ""), "t": ""}
        if tag == "svg":
            self.svgs.append({"cls": cls, "id": a.get("data-id") or a.get("data-book") or a.get("data-rel") or ""})

    def handle_endtag(self, tag):
        if tag == "style":
            self._skip -= 1
        if tag == "script":
            self._script = None
        if tag == "span" and self._span is not None:
            sp = self._span
            self._span = None
            self.spans.append(sp)
            if sp["cls"] == "dt" and self._stack:
                self._stack[-1]["dt"] += 1
        if tag in ("section", "figure") and self._stack and self._stack[-1]["tag"] == tag:
            self.cards.append(self._stack.pop())
        if tag == "div" and self._fbox is not None:
            self.fboxes[self._fbox["id"][2:] if self._fbox["id"].startswith("f-") else self._fbox["id"]] = self._fbox["t"]
            self._fbox = None

    def handle_data(self, data):
        if self._script is not None:
            self.scripts[self._script] += data
            return
        if self._skip:
            return
        self.text.append(data)
        if self._span is not None:
            self._span["t"] += data
        if self._fbox is not None:
            self._fbox["t"] += data


# ── the evidence ──────────────────────────────────────────────────────────────
class Ev:
    def __init__(self, d: Path, w: str):
        self.d, self.w = d, w
        self.st = pd.read_csv(d / "stats.csv")
        self.books = list(dict.fromkeys(self.st.book))
        self.dec = pd.read_csv(d / "decisions.csv")
        self.dec3 = pd.read_csv(d / "decisions_r3.csv")
        self.led = pd.read_csv(d / "regime_ledger.csv")
        self.cm = pd.read_csv(d / "constant_mix_params.csv")
        self.tr = pd.read_csv(d / "trades.csv")
        self.inp = pd.read_csv(d / "inputs.csv", dtype=str, keep_default_na=False)
        self.nav = pd.read_csv(d / "daily_nav.csv", parse_dates=["date"])
        self._ng = {k: g.sort_values("date") for k, g in self.nav.groupby(["book", "cost_bps", "run"])}
        self.states = np.load(d / "draw_states.npz")
        self.real = np.load(d / "real_states.npz")
        self._dr = None
        self._D = {}
        self._S = {(r["book"], r["window"], r["cash"], float(r["cost_bps"]), r["kind"]): r for r in self.st.to_dict("records")}

    def S(self, b, window, cash, cost, kind, field):
        return float(self._S[(b, window, cash, float(cost), kind)][field])

    def draws(self, b, window, cash, cost, fam, rule, field):
        if self._dr is None:
            self._dr = pd.read_csv(self.d / "draws.csv", usecols=["book", "window", "cash", "cost_bps", "family", "rule", "draw_id", "cagr", "max_dd", "sessions_invested", "out_sell_weeks", "end_nav", "trades_due", "invested_weeks"])
            self._dr = self._dr.sort_values("draw_id", kind="stable")
            self._idx = {k: g for k, g in self._dr.groupby(["book", "window", "cash", "cost_bps", "family", "rule"])}
        return self._idx[(b, window, cash, float(cost), fam, rule)][field].to_numpy()

    def nv(self, b, cost, run):
        g = self._ng[(b, float(cost), run)]
        return g.date.to_numpy(), g.nav.to_numpy()

    def dbook(self, b, r3=False):
        d = self.dec3 if r3 else self.dec
        return d[d.book == b].sort_values("j").reset_index(drop=True)


def rank(x, draws, hb=True):
    tie = np.abs(draws - x) <= 1e-12 * abs(x)
    gt, lt = draws > x, draws < x
    better = (gt if hb else lt) & ~tie
    worse = (lt if hb else gt) & ~tie
    n = len(draws)
    sd = float(draws.std(ddof=1))
    return {"worse": int(worse.sum()), "tied": int(tie.sum()), "better": int(better.sum()), "percentile": (worse.sum() + 0.5 * tie.sum()) / n * 100, "p": (1 + better.sum() + tie.sum()) / (n + 1),
            "median": float(np.median(draws)), "sd": sd, "mde": 2.8 * sd, "p05": float(np.percentile(draws, 5)), "p95": float(np.percentile(draws, 95)), "real": float(x), "edge": float(x - np.median(draws))}


def holm(ps):
    m = len(ps)
    order = np.argsort(ps, kind="stable")
    out, run = [0.0] * m, 0.0
    for r, i in enumerate(order):
        run = max(run, min(1.0, (m - r) * ps[i]))
        out[i] = run
    return out


def regimes(dec: pd.DataFrame) -> np.ndarray:
    s, g = dec["state"].to_numpy().astype(int), dec["g"].to_numpy().astype(int)
    return np.where(s == 1, 0, np.where(g == 1, 1, 2))


def spells_of(reg):
    out, j = [], 0
    while j < len(reg):
        if reg[j] == 2:
            k = j
            while k + 1 < len(reg) and reg[k + 1] == 2:
                k += 1
            out.append((j, k))
            j = k + 1
        else:
            j += 1
    return out


def rt(s):
    s = np.asarray(s).astype(int)
    ent = int(((s[1:] == 1) & (s[:-1] == 0)).sum()) + int(s[0] == 1)
    ext = int(((s[1:] == 0) & (s[:-1] == 1)).sum())
    return min(ent, ext)


def rcount(E: Ev, b: str, field: str):
    d = E.dbook(b)
    reg = regimes(d)
    T = len(E.nv(b, 20.8, "50-orig")[0])
    t = np.array([0] + [int(i) + 1 for i in d.decision_idx.values[1:]] + [T - 1])
    t = np.minimum(t, T - 1)
    ws = np.diff(t)
    names = ("IN", "OUT-BUY", "OUT-SELL")
    if field == "decisions":
        return len(reg)
    if field == "sessions":
        return int(ws.sum())
    if field.startswith("weeks_"):
        return int((reg == names.index(field[6:])).sum())
    if field.startswith("sess_"):
        return int(ws[reg == names.index(field[5:])].sum())
    if field == "out_sell_spells":
        return len(spells_of(reg))
    if field == "round_trips":
        return rt(d.state.values)
    raise KeyError(field)


def window_dates(E: Ev, b: str, window: str):
    d, _ = E.nv(b, 20.8, "50-orig")
    z = str(pd.Timestamp(d[-1]).date())
    if window == "full":
        return str(pd.Timestamp(d[0]).date()), z
    return str(E.dbook(b, True).decision_date.iloc[0]), z


def hist_bins(draws, real, nb=40):
    lo, hi = float(min(draws.min(), real)), float(max(draws.max(), real))
    pad = 0.02 * (hi - lo) if hi > lo else 1e-6
    edges = np.linspace(lo - pad, hi + pad, nb + 1)
    counts, _ = np.histogram(draws, bins=edges)
    return edges, counts


def pattern_code(E: Ev, v: str, fam: str) -> str:
    dif = [E.S(b, "full", "lbes", 20.8, v, "cagr") - E.S(b, "full", "lbes", 20.8, ORIG[v], "cagr") for b in E.books]
    pos, neg = sum(1 for x in dif if x > 0), sum(1 for x in dif if x < 0)
    if pos >= 3:
        n = 0
        for b in E.books:
            dv = E.draws(b, "full", "lbes", 20.8, fam, v, "cagr") - E.draws(b, "full", "lbes", 20.8, fam, ORIG[v], "cagr")
            real = E.S(b, "full", "lbes", 20.8, v, "cagr") - E.S(b, "full", "lbes", 20.8, ORIG[v], "cagr")
            n += int(r6rank(real, dv)["percentile"] >= 90)
        return "P1" if n >= 3 else "P2"
    return "P3" if neg >= 3 else "none"


def r6rank(real, delta):
    if real != 0:
        return rank(real, delta)
    tie = delta == 0
    n = len(delta)
    w, bt = int((delta < 0).sum()), int((delta > 0).sum())
    sd = float(delta.std(ddof=1))
    return {"worse": w, "tied": int(tie.sum()), "better": bt, "percentile": (w + 0.5 * tie.sum()) / n * 100, "p": (1 + bt + tie.sum()) / (n + 1), "median": float(np.median(delta)), "sd": sd, "real": 0.0}


def fmt(raw: float, kind: str, d: int) -> str:
    if kind == "pct":
        return f"{100 * raw:.{d}f}%"
    if kind == "pp":
        return f"{100 * raw:+.{d}f}"
    if kind == "ppu":
        return f"{100 * raw:.{d}f}"
    if kind == "int":
        return f"{raw:,.0f}"
    if kind == "sgn":
        return f"{raw:+.{d}f}"
    return f"{raw:.{d}f}"


# ── resolvers ─────────────────────────────────────────────────────────────────
def num(EV: dict[str, Ev], key: str) -> float:
    kind, rest = key.split(":", 1)
    p = rest.split("|")
    if kind == "n":
        assert p[0] == "sessions"
        return float(len(EV[p[1]].nv(p[2], 20.8, "50-orig")[0]))
    if kind in ("npass", "ncrit", "nbooks", "ndraws"):
        E = EV[p[0]]
        if kind == "nbooks":
            return float(len(E.books))
        if kind == "ndraws":
            return float(len(E.draws(E.books[0], "full", "lbes", 20.8, "F1", "50-half", "cagr")))
        if kind == "ncrit":
            return 16.0
        n = 0
        for r in NEWR:
            for c, fam, stat in CRITS:
                k = sum(1 for b in E.books if rank(E.S(b, "full", "lbes", 20.8, r, stat), E.draws(b, "full", "lbes", 20.8, fam, r, stat))["percentile"] >= 90)
                n += int(k >= 3)
        return float(n)
    w = p[0]
    E = EV[w]
    if kind == "st":
        return E.S(p[1], p[2], p[3], float(p[4]), p[5], p[6])
    if kind == "dt":
        return E.S(p[1], p[2], p[3], float(p[4]), p[5], p[6]) - E.S(p[1], p[2], p[3], float(p[4]), ORIG[p[5]], p[6])
    if kind == "dt7":
        v, tag = p[5], p[6]
        return E.S(p[1], p[2], p[3], float(p[4]), v + tag, p[7]) - E.S(p[1], p[2], p[3], float(p[4]), ORIG[v] + tag, p[7])
    if kind == "rk":
        b, window, cash, cost, fam, rule, stat, what = p[1], p[2], p[3], float(p[4]), p[5], p[6], p[7], p[8]
        return float(rank(E.S(b, window, cash, cost, rule, stat), E.draws(b, window, cash, cost, fam, rule, stat))[what])
    if kind == "hl":
        b, rule, crit = p[1], p[2], p[3]
        ps = [rank(E.S(b, "full", "lbes", 20.8, r, stat), E.draws(b, "full", "lbes", 20.8, r2, r, stat))["p"] for r in NEWR for c, r2, stat in CRITS if True]
        # r2 above is the family of the criterion (F1 / F3)
        names = [(r, c) for r in NEWR for c, _f, _s in CRITS]
        return holm(ps)[names.index((rule, crit))]
    if kind == "np":
        window, cash, cost, fam, rule, stat = p[1], p[2], float(p[3]), p[4], p[5], p[6]
        return float(sum(1 for b in E.books if rank(E.S(b, window, cash, cost, rule, stat), E.draws(b, window, cash, cost, fam, rule, stat))["percentile"] >= 90))
    if kind == "r6":
        b, cost, v, fam, stat, what = p[1], float(p[2]), p[3], p[4], p[5], p[6]
        delta = E.draws(b, "full", "lbes", cost, fam, v, stat) - E.draws(b, "full", "lbes", cost, fam, ORIG[v], stat)
        real = E.S(b, "full", "lbes", cost, v, stat) - E.S(b, "full", "lbes", cost, ORIG[v], stat)
        if what == "real":
            return real
        return float(r6rank(real, delta)[what])
    if kind == "rc":
        return float(rcount(E, p[1], p[2]))
    if kind == "led":
        b, sp, f = p[1], int(p[2]), p[3]
        row = ledger_row(E, b, sp)
        return float(row[f])
    if kind == "dc":
        d = E.dbook(p[1])
        return float(d.loc[int(p[2]), p[3]]) if p[3] != "j" else float(int(p[2]))
    if kind == "tr":
        b, run, cost, idx, tk, f = p[1], p[2], float(p[3]), int(p[4]), p[5], p[6]
        t = E.tr[(E.tr.book == b) & (E.tr.run == run) & (E.tr.cost_bps == cost) & (E.tr.idx == idx) & (E.tr.kind == tk)]
        return float(t.iloc[0][f])
    if kind == "tr2":
        b, run, cost, idx, tk, f = p[1], p[2], float(p[3]), int(p[4]), p[5], p[6]
        t = E.tr[(E.tr.book == b) & (E.tr.run == run) & (E.tr.cost_bps == cost) & (E.tr.idx == idx) & (E.tr.kind == tk)].iloc[0]
        assert f == "vmc"
        return float(t.V - t.cost)
    if kind == "nv":
        d, v = E.nv(p[1], float(p[2]), p[3])
        i = int(np.flatnonzero(d == np.datetime64(p[4]))[0])
        return float(v[i])
    if kind == "dr":
        b, window, cash, cost, fam, rule, did, f = p[1], p[2], p[3], float(p[4]), p[5], p[6], int(p[7]), p[8]
        return float(E.draws(b, window, cash, cost, fam, rule, f)[did])
    if kind == "cm":
        r = E.cm[(E.cm.book == p[1]) & (E.cm.rule == p[2])].iloc[0]
        return float(r[p[3]])
    if kind == "dm":
        x = E.draws(p[1], p[2], p[3], float(p[4]), p[5], p[6], p[7])
        return float({"mean": x.mean(), "min": x.min(), "max": x.max()}[p[8]])
    raise KeyError(key)


def ledger_row(E: Ev, b: str, sp: int) -> dict:
    """one OUT-SELL spell of the ledger, recomputed from decisions and the daily NAVs (GOLDBEES and cash returns are read from the csv: their prices are not in the evidence)."""
    d = E.dbook(b)
    reg = regimes(d)
    j0, j1 = spells_of(reg)[sp - 1]
    idx = d.decision_idx.values
    dates, _ = E.nv(b, 20.8, "50-orig")
    T = len(dates)
    a = int(idx[j0])
    z = int(idx[j1 + 1]) if j1 + 1 < len(idx) else T - 1
    names = ("IN", "OUT-BUY", "OUT-SELL")
    row = {"first_decision": str(d.decision_date.iloc[j0]), "last_decision": str(d.decision_date.iloc[j1]), "weeks": j1 - j0 + 1, "span_from_close": str(pd.Timestamp(dates[a]).date()),
           "span_to_close": str(pd.Timestamp(dates[z]).date()), "entered_from": names[reg[j0 - 1]] if j0 > 0 else "start", "exited_to": names[reg[j1 + 1]] if j1 + 1 < len(reg) else "window end"}
    _, h0 = E.nv(b, 0.0, "hold_parent")
    row["parent_return"] = float(h0[z] / h0[a] - 1)
    for r in RULES:
        _, v = E.nv(b, 20.8, r)
        row[f"ret_{r}"] = float(v[z] / v[a] - 1)
    csv = E.led[(E.led.window == "full") & (E.led.book == b) & (E.led.spell_no == sp)].iloc[0]
    row["goldbees_return"], row["cash_return"] = float(csv.goldbees_return), float(csv.cash_return)
    return row


def string(EV: dict[str, Ev], key: str) -> str:
    kind, rest = key.split(":", 1)
    p = rest.split("|")
    E = EV[p[0]]
    if kind == "vd":
        rule, crit = p[1], p[2]
        _, fam, stat = next(c for c in CRITS if c[0] == crit)
        k = sum(1 for b in E.books if rank(E.S(b, "full", "lbes", 20.8, rule, stat), E.draws(b, "full", "lbes", 20.8, fam, rule, stat))["percentile"] >= 90)
        return "PASS" if k >= 3 else "FAIL"
    if kind == "vdr":
        window, cash, cost, rule, crit = p[1], p[2], float(p[3]), p[4], p[5]
        _, fam, stat = next(c for c in CRITS if c[0] == crit)
        k = sum(1 for b in E.books if rank(E.S(b, window, cash, cost, rule, stat), E.draws(b, window, cash, cost, fam, rule, stat))["percentile"] >= 90)
        return "PASS" if k >= 3 else "FAIL"
    if kind == "pt":
        return pattern_code(E, p[1], p[2])
    if kind == "ds":
        d = E.dbook(p[1])
        v = d.loc[int(p[2]), p[3]]
        return str(v)
    if kind == "tr":
        b, run, cost, idx, tk, f = p[1], p[2], float(p[3]), int(p[4]), p[5], p[6]
        t = E.tr[(E.tr.book == b) & (E.tr.run == run) & (E.tr.cost_bps == cost) & (E.tr.idx == idx) & (E.tr.kind == tk)]
        return str(t.iloc[0][f])
    if kind == "led":
        return str(ledger_row(E, p[1], int(p[2]))[p[3]])
    if kind == "nvd":
        d, _ = E.nv(p[1], float(p[2]), p[3])
        return str(pd.Timestamp(d[int(p[4])]).date())
    if kind == "in":
        r = E.inp[E.inp.file == p[1]].iloc[0]
        return {"through": r["through"], "approved_row": r["approved_row"], "sha": r["sha256"][:12]}[p[2]]
    if kind == "stw":
        nm = lambda v: "IN" if int(v) else "out"
        gm = lambda v: "BUY" if int(v) else "SELL"
        if p[2] == "real":
            return (nm if p[3] == "io" else gm)(E.real[f"{p[1]}|full|{p[3]}"][int(p[4])])
        key2 = f"{p[1]}|full|{p[2]}|{p[3]}"
        return (nm if p[2] == "io" else gm)(E.states[key2][int(p[4])][int(p[5])])
    raise KeyError(key)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("page", nargs="?", default=None)
    ap.add_argument("--run", default="headline")
    ap.add_argument("--evidence", default=None)
    ap.add_argument("--doc", default=str(HERE / "T14.md"))
    a = ap.parse_args()
    ev = Path(a.evidence) if a.evidence else HERE / "evidence" / a.run
    page_path = Path(a.page) if a.page else (ev if a.evidence else HERE / "evidence") / "report.html"
    raw = page_path.read_text(encoding="utf-8")
    pg = Page()
    pg.feed(raw)
    EV = {w: Ev(ev / w, w) for w in ("w1", "w2") if (ev / w / "audit.json").exists()}
    chk("evidence found", len(EV) > 0, "no window evidence")
    chk("page parsed", len(pg.spans) > 0, "no provenance spans on the page")
    # 1 and 2: numbers and strings
    nv = ns = 0
    for sp in pg.spans:
        a_ = sp["a"]
        if sp["cls"] == "v":
            nv += 1
            k = a_["data-k"]
            try:
                want = num(EV, k)
            except Exception as ex:  # noqa: BLE001
                chk(f"number {k}", False, f"cannot be resolved: {type(ex).__name__} {ex}")
                continue
            got = float(a_["data-v"])
            chk(f"number {k}", close(got, want), f"page {got!r} evidence {want!r}")
            want_txt = fmt(got, a_["data-t"], int(a_["data-d"]))
            chk(f"text of {k}", sp["t"].strip() == want_txt, f"shows {sp['t']!r}, should be {want_txt!r}")
        elif sp["cls"] == "s":
            ns += 1
            k = a_["data-k"]
            try:
                want = string(EV, k)
            except Exception as ex:  # noqa: BLE001
                chk(f"string {k}", False, f"cannot be resolved: {type(ex).__name__} {ex}")
                continue
            chk(f"string {k}", a_["data-s"] == want, f"page {a_['data-s']!r} evidence {want!r}")
            chk(f"text of {k}", sp["t"].strip() == a_["data-s"], f"shows {sp['t']!r}")
        else:
            w, b, window = a_["data-dates"].split("|")
            a0, z0 = window_dates(EV[w], b, window)
            chk(f"dates {a_['data-dates']}", sp["t"].strip() == f"{a0} → {z0}", f"page {sp['t']!r} evidence {a0} → {z0}")
    # 3: every card has its dates
    for c in pg.cards:
        chk("card has a start and end date", c["dt"] >= 1, f"card with formulas {c['formulas']}")
        for f in c["formulas"]:
            chk(f"card links formula {f}", f in c["fref"], f"links {c['fref']}")
    # 4: formulas
    for h in pg.frefs:
        chk(f"formula link {h}", h.startswith("#f-") and h[3:] in pg.fboxes, "no such formula box")
    for f in NEED_FORMULAS:
        chk(f"formula {f} on the page", f in pg.fboxes and len(pg.fboxes[f].strip()) > 20, "missing or empty")
    # 5: charts
    lines = json.loads(pg.scripts.get("lines-data", "{}") or "{}")
    bars = json.loads(pg.scripts.get("bars-data", "{}") or "{}")
    svg_l = [s["id"] for s in pg.svgs if "lc" in s["cls"].split()]
    svg_b = [s["id"] for s in pg.svgs if "bc" in s["cls"].split()]
    chk("every curve chart has its data and every data set its chart", sorted(svg_l) == sorted(lines), f"svg {sorted(svg_l)} data {sorted(lines)}")
    chk("every histogram has its data and every data set its histogram", sorted(svg_b) == sorted(bars), f"{len(svg_b)} svgs, {len(bars)} data sets")
    chk("charts exist", len(lines) > 0 and len(bars) > 0, "no charts")
    for key, dd in lines.items():
        w, b = key.split("|")
        E = EV[w]
        dts, _ = E.nv(b, 20.8, "50-orig")
        idx = np.arange(0, len(dts), 5)
        if idx[-1] != len(dts) - 1:
            idx = np.append(idx, len(dts) - 1)
        chk(f"curve dates {key}", dd["dates"] == [pd.Timestamp(dts[i]).strftime("%Y-%m-%d (%a)") for i in idx], "dates differ")
        for s in dd["series"]:
            _, v = E.nv(b, 20.8, s["k"])
            chk(f"curve {key} {s['k']}", s["v"] == [round(float(v[i]), 4) for i in idx], "values differ")
        chk(f"curve window {key}", dd["n"] == len(idx), "length")
    # the outperformance view (80-half over 80-liq): ratio of the two growth-of-1 curves, recomputed here from the evidence
    rel = json.loads(pg.scripts.get("rel-data", "{}") or "{}")
    chk("every curve chart has its outperformance overlay data and the overlay is on that chart", sorted(rel) == sorted(lines) and raw.count('class="rl"') == len(lines) and "select" in raw, f"overlay data {sorted(rel)}, overlays {raw.count('class=' + chr(34) + 'rl' + chr(34))}")
    for key, dd in rel.items():
        w, b = key.split("|")
        E = EV[w]
        dts, hv_ = E.nv(b, 20.8, dd["num"])
        _, lv_ = E.nv(b, 20.8, dd["den"])
        idx = np.arange(0, len(dts), 5)
        if idx[-1] != len(dts) - 1:
            idx = np.append(idx, len(dts) - 1)
        r_ = hv_ / lv_
        chk(f"outperformance pair {key}", (dd["num"], dd["den"]) == ("80-half", "80-liq"), f"{dd['num']} / {dd['den']}")
        chk(f"outperformance dates {key}", dd["dates"] == [pd.Timestamp(dts[i]).strftime("%Y-%m-%d (%a)") for i in idx], "dates differ")
        chk(f"outperformance values {key}", dd["v"] == [round(float(r_[i]), 5) for i in idx] and dd["n"] == len(idx), "values differ")
        chk(f"outperformance end {key}", dd["end"] == round(float(r_[-1]), 5), "end differs")
    for did, dd in bars.items():
        kind, rest = did.split(":", 1)
        p = rest.split("|")
        E = EV[p[0]]
        if kind == "h":
            b, window, cash, cost, fam, rule, stat = p[1], p[2], p[3], float(p[4]), p[5], p[6], p[7]
            draws = E.draws(b, window, cash, cost, fam, rule, stat)
            real = E.S(b, window, cash, cost, rule, stat)
        else:
            b, cost, v, fam, stat = p[1], float(p[2]), p[3], p[4], p[5]
            draws = E.draws(b, "full", "lbes", cost, fam, v, stat) - E.draws(b, "full", "lbes", cost, fam, ORIG[v], stat)
            real = E.S(b, "full", "lbes", cost, v, stat) - E.S(b, "full", "lbes", cost, ORIG[v], stat)
        edges, counts = hist_bins(draws, real)
        chk(f"histogram bins {did}", dd["series"][0]["v"] == [int(c) for c in counts] and np.allclose(dd["edges"], edges, rtol=0, atol=1e-9), "bin counts or edges differ")
        chk(f"histogram total {did}", dd["series"][0]["n"] == len(draws) == int(sum(dd["series"][0]["v"])), "draws")
        xs = {m["label"]: m["x"] for m in dd["marks"]}
        chk(f"histogram marks {did}", close(xs.get("the rule", xs.get("real Δ", float("nan"))), real, 1e-9, 1e-9) and close(xs["null median" if "null median" in xs else "median Δ"], float(np.median(draws)), 1e-9, 1e-9), f"{xs}")
    for needle, why in (("lc-ov", "curve hover overlay"), ("bc-ov", "histogram hover overlay"), ("lc-xt", "timestamp chip"), ("lc-yt", "level chip"), ("lc-h", "horizontal guide"), ("pointermove", "pointer handler"), ("tip", "tooltip")):
        chk(f"hover: {why}", needle in raw, "missing")
    # 6: every date in the text
    known = set()
    for E in EV.values():
        known |= {str(pd.Timestamp(d).date()) for d in E.nav.date.unique()}
        for c in ("decision_date", "trade_date", "label_Nifty100", "label_MC100", "label_SC100", "label_MAUc1", "latest_label"):
            known |= set(E.dec[c].dropna().astype(str)) | set(E.dec3[c].dropna().astype(str))
        known |= set(E.inp["through"]) | set(E.led.first_decision) | set(E.led.last_decision) | set(E.led.span_from_close) | set(E.led.span_to_close)
    doc = Path(a.doc).read_text(encoding="utf-8")
    known |= set(DATE_RE.findall(doc))
    text = " ".join(pg.text)
    unknown = sorted({d for d in DATE_RE.findall(text) if d not in known})
    chk("every date in the text is a date of the evidence or of T14.md", not unknown, f"{unknown[:10]}")
    # hash
    reg = doc[doc.index("\n## 1. Idea and references") + 1:doc.index("\n## 4. Results") + 1]
    reg = "\n".join(l.rstrip() for l in reg.replace("\r\n", "\n").split("\n"))
    h = hashlib.sha256(reg.encode("utf-8")).hexdigest()
    chk("pre-registration hash on the page", h[:16] in text, f"{h[:16]} not found")
    chk("the page states the answer first", raw.find('id="answer"') < raw.find('id="data"') < raw.find('id="example"') and 'id="answer"' in raw, "section order")
    methods = page_path.with_name("METHODS.md")
    print(f"note: METHODS.md beside the page: {'present' if methods.exists() else 'NOT YET WRITTEN (R8; the write-up step writes it)'}")
    print(f"{page_path}: {nv:,} numbers and {ns:,} strings traced to the evidence; {len(lines)} curve charts, {len(bars)} histograms; {len(pg.cards)} cards with dates; {N_CHECKS:,} checks, {len(FAILS)} failures")
    for f in FAILS[:40]:
        print("  FAIL", f)
    if len(FAILS) > 40:
        print(f"  ... {len(FAILS) - 40} more")
    return 1 if (FAILS or N_CHECKS == 0) else 0


if __name__ == "__main__":
    sys.exit(main())
