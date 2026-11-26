"""check_page.py: re-derives every number and every date on the T16 results page from the raw evidence and counts checks and failures (AGENT.md R10).

    python tests/T16/check_page.py [page.html] [--run headline | --evidence DIR] [--doc T16.md]      exit 1 on any failure, or if nothing was checked

Shares no code with the engine, the verifier, analyse.py or report.py: it reads the evidence files (stats.csv, robustness.csv, decisions*.csv, daily_nav.csv, robust_nav.csv, trades.csv, regime_ledger.csv,
constant_mix_params.csv, inputs.csv, audit.json, regression.json, verify_t16.json) with its own functions and re-implements the regime and B derivation (from the SIGN columns), the session-by-state counts,
the spell and stretch ledger (and the -all minus -idx split by k), the comparisons C1-C6, the outcome-map codes and the line-by-line trade arithmetic. T16 has no null, no draws, no percentile and no
p-value, so none is checked.

What is checked
  1. every  <span class="v" data-k KEY data-v RAW data-t UNIT data-d D>TEXT</span>:  RAW equals the value recomputed from the evidence (relative 1e-9) and TEXT is RAW formatted to D decimals in UNIT;
  2. every  <span class="s" data-k KEY data-s STRING>: STRING equals the string recomputed from the evidence (verdicts, outcome-map wording, regimes, signs, dates, input rows, gate results, which trade was picked);
  3. every  <span class="dt" data-dates "w|book|window">: its text is 'first date -> last date' of that series in the evidence; every element of class needs-dates (each table, figure, example) contains one;
  4. every formula: each <a class="fref"> points at an existing formula box, each card lists the formulas it uses and links to all of them, and every formula the page needs exists and is not empty;
  5. every chart: lines-data (the arrays of the growth curves, every 5th session, the held state per point) equals the daily NAV of the evidence (rounded to 4 decimals) with the same dates and the state
     recomputed from the decisions; rel-data (the six outperformance overlays) equals the ratio of the two NAVs (5 decimals); every svg has its data and its hover handles (crosshair, level chip,
     timestamp chip, tooltip, overlay menu);
  6. extra identities on the worked trades: sum of the lines' traded = traded, value after cost = V - cost, shares after cost sum to 1, NAV at the close equals the daily NAV; after a -all entry cash and each
     index are 1/4 of the value after cost and the parent and GOLDBEES are 0, after a -all exit every index is 0; the 'B change is not traded by -all' example is recounted from trades.csv;
  7. every date written anywhere in the text of the page is a date of the evidence or of T16.md; the pre-registration hash on the page equals the one recomputed from T16.md (and audit.json's);
     the fixed statements (no null, no chance claim, PROVISIONAL, best-of-ten selection) are on the page;
  8. T16-specific: the rules-and-runs table is the first table of the page, defines every rule id, benchmark, window, run and comparison, and no id or label appears on the page before it or without a row in it
     (AGENT.md R10 item 1); the page carries all 24 comparisons (C1-C6 x 2 bases x 2 windows) and R4 rows for every OUT-SELL spell of every window for both -all rules; the k split sums to the
     OUT-SELL weeks and to the whole-spell sum; the window ends (W1 2019-01-02, W2 2026-11-20) are in the evidence's calendars and audit and the W2 end is on the page.

KEY grammar (w = w1|w2, b = book, win = full|r3, var = headline|r2_liq|r3|r4_s<n>|r5_drag, cost = 0.0|20.8|50.0, run = a rule, hold_parent, hold_<index>, eq3_index_basket, cmix_<rule>)
  st:w|b|var|cost|run|field              a column of stats.csv (var headline) or robustness.csv
  df:w|b|varA|varB|cost|runA|runB|field  stat(varA, runA) - stat(varB, runB)
  nok:w|varAll|varCmp|cost|base|cid      books in which comparison cid (C1-C6) of base-all (from varAll) against its comparator (from varCmp) has the stated sign;  vd:... the PASS / FAIL string (n >= 3)
  ntie:w  C2 and C6 book-comparisons whose two max drawdowns differ by < 1e-12
  npass:w  ncomp:w  npass:all  ncomp:all passing comparisons (headline, 20.8) of a window / of both, and their number (12 per window)
  omt:w|base|main|c5|c6|c4|c2|r4|r3  and  omt:base|windows       outcome-map wording (T16.md 2.5);   r4f:w|s|base   the comparisons that flip when spell s is left out;  r4open:w|s  whether spell s is open at the window end
  rc:w|b|win|field                       counts from decisions.csv / decisions_r3.csv (regime from the SIGN columns): decisions, weeks_IN, weeks_OUT-BUY, weeks_OUT-SELL, k0, k1, k2, index_weeks,
                                         out_sell_spells, index_spells, B_changes, max_spell_index_weeks, spellidx<n>, spellk0_<n>, sessions, sess_IN, sess_OUT-BUY, sess_OUT-SELL, sess_k0, sess_k1, sess_k2
  n:sessions|w|b                         sessions of the book's calendar
  dc:w|b|win|j|col  ds:w|b|win|j|col      a numeric / string column of decisions row j;  pick:w|b|target|<state>  and  pick:w|b|trade|<which>  which row the page picked
  tr:w|b|run|cost|idx|kind|field          a column of trades.csv;  tr2:...|vmc  V - cost;  ln:...|line|field  (before, after, share, target, tradedl);  fp:w|rule|idx|index  fill price from audit.json;  un:...|index  units
  bn:w|field                             the 'B change inside OUT-SELL is not traded by -all' example: strings decision_date, B_before, B_after, next_session; numbers all_trades, idx_trades (recounted from trades.csv)
  nv:w|b|cost|run|date  nvd:w|b|cost|run|k  daily NAV on a date / the date of the k-th session
  led:w|b|level|spell|stretch|field       the OUT-SELL spell / stretch ledger, re-derived from the decisions and the NAVs (GOLDBEES and cash returns are read from the csv: their prices are not in the evidence);
                                         all_minus_idx_50 / _80 = ret(b-all) - ret(b-idx)
  ks:w|b|label|field                     -all minus -idx summed over the stretches of label (k0 k1 k2 kge1 all): n stretches, weeks, d50, d80
  cm:w|b|rule|field                      constant_mix_params.csv
  in:w|file|field                        inputs.csv (through, approved_row, sha, usable_from)
  gt:w|engine|v5|v4a|v1                  gate results recorded in audit.json, regression.json, verify_t16.json
"""
from __future__ import annotations

import argparse
import bisect
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
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass
HERE = Path(__file__).resolve().parent
RULES = ["50-orig", "50-half", "50-liq", "50-idx", "50-all", "80-orig", "80-half", "80-liq", "80-idx", "80-all"]
BASES = ["50", "80"]
INDS = ["Nifty100", "MC100", "SC100"]
CIDS = [("C1", "cagr", "orig"), ("C2", "max_dd", "orig"), ("C3", "cagr", "liq"), ("C4", "cagr", "half"), ("C5", "cagr", "idx"), ("C6", "max_dd", "idx")]
DD_IDS = ("C2", "C6")
EXPECT_END = {"w1": "2019-01-02", "w2": "2026-11-20"}
CURVE_KINDS = ["hold_parent"] + RULES
REL_PAIRS = [("50-all", "50-liq"), ("50-all", "50-orig"), ("50-all", "50-idx"), ("80-all", "80-liq"), ("80-all", "80-orig"), ("80-all", "80-idx")]
NEED_FORMULAS = ["nav", "cost", "regime", "targets", "cagr", "maxdd", "calmar", "vol", "diff", "cmp", "ledger", "ksplit", "cmix", "state", "r4", "r5"]
RULE_IDS = list(RULES)
BENCH_IDS = ["hold_parent", "hold_Nifty100", "hold_MC100", "hold_SC100", "eq3_index_basket", "cmix_"]
RUN_LABELS = ["W1", "W2", "live", "R1", "R2", "R3", "R4", "R5", "C1", "C2", "C3", "C4", "C5", "C6"]
ID_RE = re.compile(r"(?<![\w-])(?:50|80)-(?:orig|half|liq|idx|all)\b|(?<![\w])-(?:orig|half|liq|idx|all)\b|\bhold_(?:parent|Nifty100|MC100|SC100)\b|\beq3_index_basket\b|\bcmix_|\bR[1-5]\b|\bC[1-6]\b|\bW[12]\b")
DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
OM_MAIN = {"C1+C3": "C1 and C3 pass: holding the three indices with cash earned more than the original sleeve and more than cash alone on this window; PROVISIONAL (seen, post-hoc, no null)",
           "C3 only": "C3 passes, C1 fails: the indices beat cash but giving up GOLDBEES cost more than they added",
           "no C3, C1 passes": "C3 fails: holding the three indices did not beat cash in the regime on this window (C1 passes)",
           "no C3, C1 fails": "C3 fails: holding the three indices did not beat cash in the regime on this window"}
OM_C5 = {True: "C5 passes: ignoring the index signals in the regime earned more than following them (-idx) on this window; the ledger's k = 0 / k >= 1 split says where",
         False: "C5 fails: ignoring the index signals in the regime did not earn more than following them (-idx) on this window; the ledger's k = 0 / k >= 1 split says where"}
OM_C6 = {True: "C6 passes: ignoring the signals did not deepen the worst fall against -idx", False: "C6 fails: ignoring the signals deepened the worst fall against -idx"}
OM_C4 = {True: "C4 passes: -all did better than T14's half-parent + GOLDBEES", False: "C4 fails: -all did not do better than T14's half-parent + GOLDBEES"}
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
        self.tables = []          # {"id", "t"} in order of appearance
        self._tab = []
        self.rr_start = self.rr_end = None

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
            self._stack.append({"tag": tag, "formulas": [x for x in a.get("data-formulas", "").split(",") if x], "dt": 0, "fref": []})
        if tag == "a" and "fref" in cls.split():
            h = a.get("href", "")
            self.frefs.append(h)
            if self._stack:
                self._stack[-1]["fref"].append(h[3:] if h.startswith("#f-") else h)
        if tag == "div" and "formula" in cls.split():
            self._fbox = {"id": a.get("id", ""), "t": ""}
        if tag == "svg":
            self.svgs.append({"cls": cls, "id": a.get("data-book", "")})
        if tag == "h3" and a.get("id") == "rules-runs-h":
            self.rr_start = len(self.text)
        if tag == "table":
            tb = {"id": a.get("id", ""), "t": ""}
            self.tables.append(tb)
            self._tab.append(tb)

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
        if tag == "table" and self._tab:
            tb = self._tab.pop()
            if tb["id"] == "rules-runs":
                self.rr_end = len(self.text)

    def handle_data(self, data):
        if self._script is not None:
            self.scripts[self._script] += data
            return
        if self._skip:
            return
        self.text.append(data)
        for tb in self._tab:
            tb["t"] += data
        if self._span is not None:
            self._span["t"] += data
        if self._fbox is not None:
            self._fbox["t"] += data


# ── the evidence ──────────────────────────────────────────────────────────────
class Ev:
    def __init__(self, d: Path, w: str):
        self.d, self.w = d, w
        self.st = pd.read_csv(d / "stats.csv")
        self.rob = pd.read_csv(d / "robustness.csv")
        self.books = list(dict.fromkeys(self.st.book))
        self.dec = pd.read_csv(d / "decisions.csv")
        self.dec3 = pd.read_csv(d / "decisions_r3.csv")
        self.led = pd.read_csv(d / "regime_ledger.csv")
        self.cm = pd.read_csv(d / "constant_mix_params.csv")
        self.tr = pd.read_csv(d / "trades.csv")
        self.inp = pd.read_csv(d / "inputs.csv", dtype=str, keep_default_na=False)
        self.nav = pd.read_csv(d / "daily_nav.csv", parse_dates=["date"])
        self.audit = json.loads((d / "audit.json").read_text(encoding="utf-8"))
        self.regr = json.loads((d / "regression.json").read_text(encoding="utf-8"))
        self.verify = json.loads((d / "verify_t16.json").read_text(encoding="utf-8")) if (d / "verify_t16.json").exists() else None
        self._ng = {k: g.sort_values("date") for k, g in self.nav.groupby(["book", "cost_bps", "run"])}
        self._S = {}
        for r in self.st.to_dict("records"):
            self._S[(r["book"], "headline", float(r["cost_bps"]), r["run"])] = r
        for r in self.rob.to_dict("records"):
            self._S[(r["book"], r["variant"], float(r["cost_bps"]), r["run"])] = r
        self._rn = None
        self._dcache = {}

    def S(self, b, var, cost, run, field):
        return float(self._S[(b, var, float(cost), run)][field])

    def nv(self, b, cost, run):
        g = self._ng[(b, float(cost), run)]
        return g.date.to_numpy(), g.nav.to_numpy()

    def r3cal(self, b) -> list[str]:
        if self._rn is None:
            rn = pd.read_csv(self.d / "robust_nav.csv", usecols=["book", "variant", "run", "date"])
            rn = rn[(rn["variant"] == "r3") & (rn["run"] == "50-all")]
            self._rn = {k: [str(x) for x in g["date"]] for k, g in rn.groupby("book")}
        return self._rn[b]

    def cal(self, b, win) -> list[str]:
        if win == "full":
            return [str(pd.Timestamp(x).date()) for x in self.nv(b, 20.8, "50-all")[0]]
        return self.r3cal(b)

    def dbook(self, b, win="full") -> pd.DataFrame:
        k = (b, win)
        if k not in self._dcache:
            d = self.dec if win == "full" else self.dec3
            d = d[d.book == b].sort_values("j").reset_index(drop=True).copy()
            # regime and B derived here from the SIGN columns, not read from the regime / B / k columns
            for i in INDS:
                d["buy_" + i + "_d"] = (d["sign_" + i] == "BUY").astype(int)
            d["k_d"] = d[["buy_" + i + "_d" for i in INDS]].sum(axis=1)
            d["reg_d"] = np.where(d["k_d"] == 3, "IN", np.where(d["sign_MAUc1"] == "BUY", "OUT-BUY", "OUT-SELL"))
            d["B_d"] = ["+".join(i for i in INDS if r["buy_" + i + "_d"]) or "cash" for _, r in d.iterrows()]
            self._dcache[k] = d
        return self._dcache[k]


def window_dates(E: Ev, b: str, window: str):
    cal = E.cal(b, window)
    return cal[0], cal[-1]


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


# ── derivations ───────────────────────────────────────────────────────────────
def spells_of(reg):
    out, j = [], 0
    while j < len(reg):
        if reg[j] == "OUT-SELL":
            k = j
            while k + 1 < len(reg) and reg[k + 1] == "OUT-SELL":
                k += 1
            out.append((j, k))
            j = k + 1
        else:
            j += 1
    return out


def stretches_of(B, a, z):
    out, j = [], a
    while j <= z:
        k = j
        while k + 1 <= z and B[k + 1] == B[j]:
            k += 1
        out.append((j, k))
        j = k + 1
    return out


def valid_td(x) -> bool:
    return str(x) not in ("nan", "None", "")


def held_j(E: Ev, b: str, win: str):
    """for every session of the calendar: the index of the decision whose target is held (the last decision traded on or before that session; decision 0 until then)."""
    d = E.dbook(b, win)
    cal = E.cal(b, win)
    tds = [(str(d["trade_date"].iloc[j]), j) for j in range(1, len(d)) if valid_td(d["trade_date"].iloc[j])]
    tl = [t for t, _ in tds]
    out = []
    for dt in cal:
        p = bisect.bisect_right(tl, dt)
        out.append(tds[p - 1][1] if p > 0 else 0)
    return cal, d, out


def rc(E: Ev, b: str, win: str, field: str) -> float:
    d = E.dbook(b, win)
    reg, k, B = d["reg_d"].to_numpy(), d["k_d"].to_numpy(), d["B_d"].to_numpy()
    sp = spells_of(reg)
    if field == "decisions":
        return float(len(d))
    if field.startswith("weeks_"):
        return float((reg == field[6:]).sum())
    if field in ("k0", "k1", "k2"):
        return float(((reg == "OUT-SELL") & (k == int(field[1]))).sum())
    if field == "index_weeks":
        return float(((reg == "OUT-SELL") & (k > 0)).sum())
    if field == "out_sell_spells":
        return float(len(sp))
    if field == "index_spells":
        return float(sum(1 for a, z in sp if (k[a:z + 1] > 0).any()))
    if field == "B_changes":
        return float(sum(1 for j in range(1, len(d)) if reg[j] == "OUT-SELL" and reg[j - 1] == "OUT-SELL" and B[j] != B[j - 1]))
    if field == "max_spell_index_weeks":
        return float(max((int((k[a:z + 1] > 0).sum()) for a, z in sp), default=0))
    if field.startswith("spellidx"):
        a, z = sp[int(field[8:]) - 1]
        return float((k[a:z + 1] > 0).sum())
    if field.startswith("spellk0_"):
        a, z = sp[int(field[8:]) - 1]
        return float((k[a:z + 1] == 0).sum())
    if field == "sessions":
        return float(len(E.cal(b, win)))
    if field.startswith("sess_"):
        cal, d2, js = held_j(E, b, win)
        r2 = np.array([d2["reg_d"].iloc[j] for j in js])
        k2 = np.array([d2["k_d"].iloc[j] for j in js])
        nm = field[5:]
        if nm in ("k0", "k1", "k2"):
            return float(((r2 == "OUT-SELL") & (k2 == int(nm[1]))).sum())
        return float((r2 == nm).sum())
    raise KeyError(field)


def passes(E: Ev, cid: str, varI: str, varC: str, cost: float, base: str, b: str) -> bool:
    _, stat, kind = next(c for c in CIDS if c[0] == cid)
    a, c = E.S(b, varI, cost, f"{base}-all", stat), E.S(b, varC, cost, f"{base}-{kind}", stat)
    return (a >= c) if cid in DD_IDS else (a > c)


def nok(E: Ev, cid, varI, varC, cost, base) -> int:
    return sum(passes(E, cid, varI, varC, cost, base, b) for b in E.books)


def verdict(E: Ev, cid, varI, varC, cost, base) -> bool:
    return nok(E, cid, varI, varC, cost, base) >= 3


def spell_ids(E: Ev) -> list[int]:
    return sorted({int(v.split("_s")[1]) for v in E.rob["variant"].unique() if v.startswith("r4_s")})


def r4_flips(E: Ev, base: str):
    out = []
    for s in spell_ids(E):
        for cid, _, _ in CIDS:
            h, n = verdict(E, cid, "headline", "headline", 20.8, base), verdict(E, cid, f"r4_s{s}", "headline", 20.8, base)
            if h != n:
                out.append((s, cid, h, n))
    return out


def ledger_row(E: Ev, b: str, level: str, sp_no: int, st_no: int) -> dict:
    d = E.dbook(b)
    reg, B, k = d["reg_d"].to_numpy(), d["B_d"].to_numpy(), d["k_d"].to_numpy()
    spl = spells_of(reg)
    j0s, j1s = spl[sp_no - 1]
    if level == "spell":
        j0, j1 = j0s, j1s
    else:
        j0, j1 = stretches_of(B, j0s, j1s)[st_no - 1]
    cal = E.cal(b, "full")
    tds = [str(x) for x in d["trade_date"]]
    row = {"first_decision": str(d["decision_date"].iloc[j0]), "last_decision": str(d["decision_date"].iloc[j1]), "weeks": j1 - j0 + 1, "B": B[j0], "k": int(k[j0])}
    row["a_session"] = cal[0] if j0 == 0 else tds[j0]
    row["b_session"] = tds[j1 + 1] if (j1 + 1 < len(d) and valid_td(tds[j1 + 1])) else cal[-1]
    first_in_spell = (j0 == j0s)
    last_in_spell = (j1 == j1s)
    row["entered_from"] = ("start" if j0 == 0 else reg[j0 - 1]) if (level == "spell" or first_in_spell) else "OUT-SELL"
    row["exited_to"] = (reg[j1 + 1] if j1 + 1 < len(d) else "window end") if (level == "spell" or last_in_spell) else "OUT-SELL"
    ia, ib = cal.index(row["a_session"]), cal.index(row["b_session"])
    _, hp = E.nv(b, 0.0, "hold_parent")
    row["parent_return"] = float(hp[ib] / hp[ia] - 1)
    for r in RULES:
        _, v = E.nv(b, 20.8, r)
        row[f"ret_{r}"] = float(v[ib] / v[ia] - 1)
    row["all_minus_idx_50"] = row["ret_50-all"] - row["ret_50-idx"]
    row["all_minus_idx_80"] = row["ret_80-all"] - row["ret_80-idx"]
    for i in INDS:
        _, v = E.nv(b, 20.8, f"hold_{i}")
        row[f"{i}_return"] = float(v[ib] / v[ia] - 1)
    csv = E.led[(E.led.book == b) & (E.led.window == "full") & (E.led.level == level) & (E.led.spell_no == sp_no) & (E.led.stretch_no == st_no)]
    assert len(csv) == 1, "ledger row not unique"
    row["goldbees_return"], row["cash_return"] = float(csv.iloc[0].goldbees_return), float(csv.iloc[0].cash_return)
    row["_csv_all_minus_idx_50"], row["_csv_all_minus_idx_80"] = float(csv.iloc[0].all_minus_idx_50), float(csv.iloc[0].all_minus_idx_80)
    row["_csv_k"] = int(csv.iloc[0].k)
    return row


_KS_CACHE: dict = {}


def ks_rows(E: Ev, b: str) -> dict:
    """the B stretches of every OUT-SELL spell with their weeks, k and -all minus -idx, grouped by label (k0 k1 k2 kge1 all)."""
    key = (id(E), b)
    if key not in _KS_CACHE:
        d = E.dbook(b)
        reg, B, k = d["reg_d"].to_numpy(), d["B_d"].to_numpy(), d["k_d"].to_numpy()
        rows = []
        for sp_no, (a, z) in enumerate(spells_of(reg), 1):
            for st_no, (j0, j1) in enumerate(stretches_of(B, a, z), 1):
                r = ledger_row(E, b, "stretch", sp_no, st_no)
                r["k"] = int(k[j0])
                rows.append(r)
        _KS_CACHE[key] = {"k0": [r for r in rows if r["k"] == 0], "k1": [r for r in rows if r["k"] == 1], "k2": [r for r in rows if r["k"] == 2], "kge1": [r for r in rows if r["k"] >= 1], "all": rows}
    return _KS_CACHE[key]


def bn_example(E: Ev, b: str) -> dict:
    """the 'B changes inside OUT-SELL' example of audit.json, re-derived from the decisions: decision date from the audit, the rest from decisions.csv."""
    x = E.audit["v5"]["worked_examples"]["50-all|B_change_not_traded"]
    d = E.dbook(b)
    j = int(np.flatnonzero(d["decision_date"].astype(str).to_numpy() == x["decision_date"])[0])
    return {"decision_date": x["decision_date"], "j": j, "B_before": str(d["B_d"].iloc[j - 1]), "B_after": str(d["B_d"].iloc[j]), "next_session": str(d["trade_date"].iloc[j]),
            "both_out_sell": bool(d["reg_d"].iloc[j] == "OUT-SELL" and d["reg_d"].iloc[j - 1] == "OUT-SELL")}


def trade_row(E: Ev, b, run, cost, idx, kind):
    t = E.tr[(E.tr.book == b) & (E.tr.run == run) & (E.tr.cost_bps == float(cost)) & (E.tr.idx == int(idx)) & (E.tr.kind == kind)]
    assert len(t) == 1, f"trade not unique: {b} {run} {cost} {idx} {kind} ({len(t)})"
    return t.iloc[0]


def pick_trade_idx(E: Ev, b: str, which: str):
    kind, k = {"entry_k2": ("regime_in", 2), "entry_k1": ("regime_in", 1), "entry_k0": ("regime_in", 0), "regime_out": ("regime_out", None)}[which]
    sel = E.tr[(E.tr.book == b) & (E.tr.run == "50-all") & (E.tr.cost_bps == 20.8) & (E.tr.kind == kind)].sort_values("idx", kind="stable")
    d = E.dbook(b)
    for r in sel.itertuples():
        if k is None or (not pd.isna(r.dec_j) and int(d["k_d"].iloc[int(r.dec_j)]) == k):
            return str(int(r.idx))
    return None


def audit_fill(E: Ev, rule: str, idx: int):
    for key, x in E.audit["v5"]["worked_examples"].items():
        if key.startswith(rule + "|") and int(x["idx"]) == int(idx):
            return x["index_fill_prices"]
    raise KeyError(f"no worked example {rule} {idx}")


def state_str(reg, B, k) -> str:
    return reg if reg != "OUT-SELL" else f"OUT-SELL, B = {B} (k = {k})"


# ── resolvers ─────────────────────────────────────────────────────────────────
def num(EV: dict, key: str) -> float:
    kind, rest = key.split(":", 1)
    p = rest.split("|")
    if kind == "gt":
        v = EV[p[0]].verify
        return float(v.get("gate_compared", v.get("comparisons")))
    if kind == "n":
        assert p[0] == "sessions"
        return float(len(EV[p[1]].nv(p[2], 20.8, "50-all")[0]))
    if kind == "ncomp":
        return float(12 * (len(EV) if p[0] == "all" else 1))
    if kind == "ntie":
        E = EV[p[0]]
        return float(sum(1 for base in BASES for kind in ("orig", "idx") for b in E.books if abs(E.S(b, "headline", 20.8, f"{base}-all", "max_dd") - E.S(b, "headline", 20.8, f"{base}-{kind}", "max_dd")) < 1e-12))
    if kind == "npass":
        ws = list(EV) if p[0] == "all" else [p[0]]
        return float(sum(verdict(EV[w], cid, "headline", "headline", 20.8, base) for w in ws for base in BASES for cid, _, _ in CIDS))
    w = p[0]
    E = EV[w]
    if kind == "st":
        return E.S(p[1], p[2], float(p[3]), p[4], p[5])
    if kind == "df":
        b, vA, vB, cost, rA, rB, f = p[1], p[2], p[3], float(p[4]), p[5], p[6], p[7]
        return E.S(b, vA, cost, rA, f) - E.S(b, vB, cost, rB, f)
    if kind == "nok":
        return float(nok(E, p[5], p[1], p[2], float(p[3]), p[4]))
    if kind == "rc":
        return rc(E, p[1], p[2], p[3])
    if kind == "dc":
        d = E.dbook(p[1], p[2])
        j = int(p[3])
        col = p[4]
        if col == "j":
            return float(j)
        if col == "k":
            return float(d["k_d"].iloc[j])
        return float(d.loc[j, col])
    if kind == "kk":
        return 1.0 / (float(E.dbook(p[1], p[2])["k_d"].iloc[int(p[3])]) + 1.0)
    if kind in ("tr", "tr2"):
        b, run, cost, idx, tk, f = p[1], p[2], float(p[3]), int(p[4]), p[5], p[6]
        t = trade_row(E, b, run, cost, idx, tk)
        if kind == "tr2":
            assert f == "vmc"
            return float(t.V - t.cost)
        if f == "traded":
            parts = []
            for ln in ("stock", "gold", "cash") + tuple(INDS):
                share = float(t[f"{ln}_after"]) / float(t.V_after)
                parts.append(abs(share * float(t.V) - float(t[f"{ln}_before"])))
            chk(f"lines' traded sum to traded {key}", close(sum(parts), float(t.traded), 1e-9, 1e-12), f"{sum(parts)} vs {float(t.traded)}")
            chk(f"V - cost equals V after {key}", close(float(t.V) - float(t.cost), float(t.V_after), 1e-12, 1e-14), "")
            chk(f"cost = traded x bps / 2e4 {key}", close(float(t.traded) * cost / 2e4, float(t.cost), 1e-9, 1e-14), "")
            chk(f"shares after cost sum to 1 {key}", close(sum(float(t[f"{ln}_after"]) for ln in ("stock", "gold", "cash") + tuple(INDS)) / float(t.V_after), 1.0, 1e-12, 1e-12), "")
        if f == "nav_close_after":
            dts, v = E.nv(b, cost, run)
            chk(f"NAV at the close equals the daily NAV {key}", close(float(t.nav_close_after), float(v[idx]), 1e-12, 1e-14), "")
        if f == "idx" and run.endswith("-all") and tk == "regime_in" and not pd.isna(t.dec_j):
            d = E.dbook(b)
            Va = float(t.V_after)
            chk(f"-all entry: the decision is OUT-SELL {key}", d["reg_d"].iloc[int(t.dec_j)] == "OUT-SELL", "")
            chk(f"-all entry: cash at 1/4 {key}", close(float(t.cash_after) / Va, 0.25, 1e-9, 1e-12), "")
            for i in INDS:
                chk(f"-all entry: index {i} at 1/4 whatever B {key}", close(float(t[f"{i}_after"]) / Va, 0.25, 1e-9, 1e-12), "")
            chk(f"-all entry: no parent, no GOLDBEES {key}", float(t.stock_after) == 0.0 and float(t.gold_after) == 0.0, "")
        if f == "idx" and run.endswith("-all") and tk == "regime_out":
            chk(f"-all exit: every index is 0 after {key}", all(float(t[f"{i}_after"]) == 0.0 for i in INDS) and all(float(t[f"{i}_before"]) > 0.0 for i in INDS), "")
        if f == "idx" and run.endswith("-idx") and tk in ("regime_in", "index_set_change") and not pd.isna(t.dec_j):
            d = E.dbook(b)
            kk = int(d["k_d"].iloc[int(t.dec_j)])
            Va = float(t.V_after)
            chk(f"cash at 1/(k+1) {key}", close(float(t.cash_after) / Va, 1.0 / (kk + 1), 1e-9, 1e-12), "")
            for i in INDS:
                want = 1.0 / (kk + 1) if d[f"buy_{i}_d"].iloc[int(t.dec_j)] else 0.0
                chk(f"index {i} at 1/(k+1) {key}", close(float(t[f"{i}_after"]) / Va, want, 1e-9, 1e-12), "")
            chk(f"no parent, no GOLDBEES {key}", float(t.stock_after) == 0.0 and float(t.gold_after) == 0.0, "")
        return float(t[f])
    if kind == "ln":
        b, run, cost, idx, tk, ln, f = p[1], p[2], float(p[3]), int(p[4]), p[5], p[6], p[7]
        t = trade_row(E, b, run, cost, idx, tk)
        before, after, V_, Va = float(t[f"{ln}_before"]), float(t[f"{ln}_after"]), float(t.V), float(t.V_after)
        share = after / Va
        return {"before": before, "after": after, "share": share, "target": share * V_, "tradedl": abs(share * V_ - before)}[f]
    if kind == "fp":
        return float(audit_fill(E, p[1], int(p[2]))[p[3]])
    if kind == "un":
        b, run, cost, idx, tk, ln = p[1], p[2], float(p[3]), int(p[4]), p[5], p[6]
        t = trade_row(E, b, run, cost, idx, tk)
        return float(t[f"{ln}_after"]) / float(audit_fill(E, run, idx)[ln])
    if kind == "nv":
        d, v = E.nv(p[1], float(p[2]), p[3])
        i = int(np.flatnonzero(d == np.datetime64(p[4]))[0])
        return float(v[i])
    if kind == "led":
        b, level, sp, stn, f = p[1], p[2], int(p[3]), int(p[4]), p[5]
        return float(ledger_row(E, b, level, sp, stn)[f])
    if kind == "ks":
        b, label, f = p[1], p[2], p[3]
        sel = ks_rows(E, b)[label]
        if f == "n":
            return float(len(sel))
        if f == "weeks":
            return float(sum(r["weeks"] for r in sel))
        return float(sum(r["all_minus_idx_" + f[1:]] for r in sel))
    if kind == "bn":
        b = E.books[0]
        if p[1] in ("all_trades", "idx_trades"):
            run = "50-all" if p[1] == "all_trades" else "50-idx"
            nxt = bn_example(E, b)["next_session"]
            return float(((E.tr.book == b) & (E.tr.run == run) & (E.tr.cost_bps == 20.8) & (E.tr.date == nxt)).sum())
        raise KeyError(key)
    if kind == "cm":
        r = E.cm[(E.cm.book == p[1]) & (E.cm.rule == p[2])]
        assert len(r) == 1
        return float(r.iloc[0][p[3]])
    raise KeyError(key)


def string(EV: dict, key: str) -> str:
    kind, rest = key.split(":", 1)
    p = rest.split("|")
    if kind == "omt" and p[1] == "windows":
        base = p[0]
        pats = [tuple(verdict(E, cid, "headline", "headline", 20.8, base) for cid, _, _ in CIDS) for E in EV.values()]
        return "the two windows agree on C1-C6" if len(set(pats)) == 1 else "the two windows DISAGREE on C1-C6: report both, no general statement; the 2019-2026 window is the one the live product traded"
    E = EV[p[0]]
    if kind == "vd":
        return "PASS" if verdict(E, p[5], p[1], p[2], float(p[3]), p[4]) else "FAIL"
    if kind == "omt":
        base, which = p[1], p[2]
        v = lambda cid: verdict(E, cid, "headline", "headline", 20.8, base)
        if which == "main":
            c1, c3 = v("C1"), v("C3")
            return OM_MAIN["C1+C3" if (c1 and c3) else "C3 only" if c3 else "no C3, C1 passes" if c1 else "no C3, C1 fails"]
        if which == "c4":
            return OM_C4[v("C4")]
        if which == "c5":
            return OM_C5[v("C5")]
        if which == "c6":
            return OM_C6[v("C6")]
        if which == "c2":
            return "C2 passes" if v("C2") else "C2 fails"
        if which == "r4":
            fl = r4_flips(E, base)
            return "R4: no comparison flips when one spell is left out" if not fl else "R4: " + "; ".join(
                f"leaving out spell {s} flips {cid} ({'PASS' if h else 'FAIL'} -> {'PASS' if n else 'FAIL'}): " + ("the result rests on that spell" if h else "the failure rests on that spell") for s, cid, h, n in fl)
        if which == "r3":
            agree = [verdict(E, cid, "r3", "r3", 20.8, base) for cid, _, _ in CIDS] == [v(cid) for cid, _, _ in CIDS]
            return "R3 (live window) agrees with the whole window" if agree else "R3 (live window) DISAGREES with the whole window"
    if kind == "r4f":
        s, base = int(p[1]), p[2]
        fl = [cid for cid, _, _ in CIDS if verdict(E, cid, f"r4_s{s}", "headline", 20.8, base) != verdict(E, cid, "headline", "headline", 20.8, base)]
        return ",".join(fl) or "-"
    if kind == "r4open":
        b = E.books[0]
        d = E.dbook(b)
        sp = spells_of(d["reg_d"].to_numpy())
        return "open at the window end" if sp[int(p[1]) - 1][1] + 1 >= len(d) else "closed before the window end"
    if kind == "bn":
        return str(bn_example(E, E.books[0])[p[1]])
    if kind == "ds":
        d = E.dbook(p[1], p[2])
        j, col = int(p[3]), p[4]
        if col == "regime":
            return str(d["reg_d"].iloc[j])
        if col == "B":
            return str(d["B_d"].iloc[j])
        return str(d.loc[j, col])
    if kind == "tr":
        b, run, cost, idx, tk, f = p[1], p[2], float(p[3]), int(p[4]), p[5], p[6]
        return str(trade_row(E, b, run, cost, idx, tk)[f])
    if kind == "led":
        return str(ledger_row(E, p[1], p[2], int(p[3]), int(p[4]))[p[5]])
    if kind == "nvd":
        d, _ = E.nv(p[1], float(p[2]), p[3])
        return str(pd.Timestamp(d[int(p[4])]).date())
    if kind == "in":
        r = E.inp[E.inp.file == p[1]]
        assert len(r) == 1
        r = r.iloc[0]
        return {"through": r["through"], "approved_row": r["approved_row"], "sha": r["sha256"][:12], "usable_from": r["usable_from"]}[p[2]]
    if kind == "gt":
        if p[1] == "engine":
            return "PASS" if E.audit["gates"]["all"] else "FAIL"
        if p[1] == "v5":
            return "PASS" if E.audit["v5"]["pass"] else "FAIL"
        if p[1] == "v4a":
            return "PASS" if E.regr["a_nav_regression"]["pass"] else "FAIL"
        if p[1] == "v1":
            return "NOT RUN" if E.verify is None else ("PASS" if (E.verify.get("pass") is True or E.verify.get("exit_ok") is True) else "FAIL")
    if kind == "pick":
        b = p[1]
        if p[2] == "trade":
            r = pick_trade_idx(E, b, p[3])
            assert r is not None, "no such trade"
            return r
        if p[2] == "target":
            d = E.dbook(b)
            lab = p[3]
            test = {"IN": lambda r: r.reg_d == "IN", "OUT-BUY": lambda r: r.reg_d == "OUT-BUY", "OUT-SELL k = 0": lambda r: r.reg_d == "OUT-SELL" and r.k_d == 0,
                    "OUT-SELL k = 1": lambda r: r.reg_d == "OUT-SELL" and r.k_d == 1, "OUT-SELL k = 2": lambda r: r.reg_d == "OUT-SELL" and r.k_d == 2}[lab]
            for j, r in enumerate(d.itertuples()):
                if test(r):
                    return str(j)
            raise AssertionError("no such decision")
    raise KeyError(key)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("page", nargs="?", default=None)
    ap.add_argument("--run", default="headline")
    ap.add_argument("--evidence", default=None)
    ap.add_argument("--doc", default=str(HERE / "T16.md"))
    a = ap.parse_args()
    ev = Path(a.evidence) if a.evidence else HERE / "evidence" / a.run
    page_path = Path(a.page) if a.page else (ev if a.evidence else HERE / "evidence") / "report.html"
    raw = page_path.read_text(encoding="utf-8")
    pg = Page()
    pg.feed(raw)
    EV = {w: Ev(ev / w, w) for w in ("w1", "w2") if (ev / w / "audit.json").exists()}
    chk("evidence found", len(EV) > 0, "no window evidence")
    chk("page parsed", len(pg.spans) > 0, "no provenance spans on the page")
    # 1 and 2: numbers, strings and dates
    nv = ns = nd = 0
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
            chk(f"number {k}", close(got, want, 1e-9, 1e-12), f"page {got!r} evidence {want!r}")
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
            nd += 1
            w, b, window = a_["data-dates"].split("|")
            a0, z0 = window_dates(EV[w], b, window)
            chk(f"dates {a_['data-dates']}", sp["t"].strip() == f"{a0} → {z0}", f"page {sp['t']!r} evidence {a0} → {z0}")
    # 3: every card has its dates; 4: formulas
    for c in pg.cards:
        chk("card has a start and end date", c["dt"] >= 1, f"card with formulas {c['formulas']}")
        for f in c["formulas"]:
            chk(f"card links formula {f}", f in c["fref"], f"links {c['fref']}")
    for h in pg.frefs:
        chk(f"formula link {h}", h.startswith("#f-") and h[3:] in pg.fboxes, "no such formula box")
    for f in NEED_FORMULAS:
        chk(f"formula {f} on the page", f in pg.fboxes and len(pg.fboxes[f].strip()) > 20, "missing or empty")
    # 5: charts
    lines = json.loads(pg.scripts.get("lines-data", "{}") or "{}")
    rel = json.loads(pg.scripts.get("rel-data", "{}") or "{}")
    svg_l = [s["id"] for s in pg.svgs if "lc" in s["cls"].split()]
    chk("every curve chart has its data and every data set its chart", sorted(svg_l) == sorted(lines), f"svg {sorted(svg_l)} data {sorted(lines)}")
    chk("charts exist", len(lines) > 0, "no charts")
    chk("every curve chart has its overlay data and six overlay groups", sorted(rel) == sorted(lines) and raw.count('class="rl"') == 6 * len(lines), f"overlay data {sorted(rel)}")
    # the chip bars: one per window, a chip for each of the eleven curves, each of the six ratio overlays, the shading, the presets; some curve pressed when the page opens
    import re as _re
    for w_ in sorted({k.split("|")[0] for k in lines}):
        m_ = _re.search(r'<div class="chips" data-win="' + w_ + r'".*?</div>', raw, _re.S)
        chk(f"chip bar {w_} exists", m_ is not None, "no chip bar")
        if m_ is None:
            continue
        blk = m_.group(0)
        chk(f"chip bar {w_}: a chip for each of the eleven curves", sorted(_re.findall(r'data-k="([^"]+)"', blk)) == sorted(CURVE_KINDS), "the curve chips differ from the eleven curves")
        chk(f"chip bar {w_}: a chip for each of the six ratio overlays", sorted(int(x) for x in _re.findall(r'data-pair="(\d+)"', blk)) == list(range(len(REL_PAIRS))), "overlay chips")
        chk(f"chip bar {w_}: shading chip and the four presets", "data-sh" in blk and all(f'data-pre="{x}"' in blk for x in ("reset", "all", "alls", "none")), "shading or presets missing")
        chk(f"chip bar {w_}: every chip is a button with aria-pressed", blk.count("<button") == blk.count("aria-pressed=") == blk.count("</button>") and blk.count("<button") >= len(CURVE_KINDS) + len(REL_PAIRS) + 1 + 4, "chip markup")
        chk(f"chip bar {w_}: at least one curve is drawn when the page opens", bool(_re.search(r'data-k="[^"]+"[^>]*aria-pressed="true"', blk)), "no curve pressed")
    for w_ in sorted({k.split("|")[0] for k in lines}):
        chk(f"every {w_} chart is tied to its chip bar (data-win)", all(f'data-win="{w_}"' in raw[raw.find(f'data-book="{k}"'):raw.find(f'data-book="{k}"') + 200] for k in lines if k.startswith(w_ + "|")), "data-win")
    for key, dd in lines.items():
        w, b = key.split("|")
        E = EV[w]
        dts, _ = E.nv(b, 20.8, "50-all")
        n = len(dts)
        idx = np.arange(0, n, 5)
        if idx[-1] != n - 1:
            idx = np.append(idx, n - 1)
        chk(f"curve dates {key}", dd["dates"] == [pd.Timestamp(dts[i]).strftime("%Y-%m-%d (%a)") for i in idx], "dates differ")
        chk(f"curve series {key}", [s["k"] for s in dd["series"]] == CURVE_KINDS, "series list")
        for s in dd["series"]:
            _, v = E.nv(b, 20.8, s["k"])
            chk(f"curve {key} {s['k']}", s["v"] == [round(float(v[i]), 4) for i in idx], "values differ")
        chk(f"curve window {key}", dd["n"] == len(idx), "length")
        cal, d, js = held_j(E, b, "full")
        want = [state_str(d["reg_d"].iloc[js[i]], d["B_d"].iloc[js[i]], int(d["k_d"].iloc[js[i]])) for i in idx]
        chk(f"curve state per point {key}", dd["state"] == want, "held state differs")
        rd = rel[key]
        chk(f"overlay dates {key}", rd["dates"] == dd["dates"], "dates differ")
        chk(f"overlay pairs {key}", [(x["num"], x["den"]) for x in rd["pairs"]] == REL_PAIRS, "pairs")
        for x in rd["pairs"]:
            _, nu = E.nv(b, 20.8, x["num"])
            _, de = E.nv(b, 20.8, x["den"])
            r_ = nu / de
            chk(f"overlay values {key} {x['num']}/{x['den']}", x["v"] == [round(float(r_[i]), 5) for i in idx] and x["end"] == round(float(r_[-1]), 5), "values differ")
            chk(f"overlay axis {key} {x['num']}/{x['den']}", x["lo"] <= min(x["v"] + [1.0]) and x["hi"] >= max(x["v"] + [1.0]), "axis does not cover the data")
    for needle, why in (("lc-ov", "curve hover overlay"), ("lc-xt", "timestamp chip"), ("lc-yt", "level chip"), ("lc-h", "horizontal guide"), ("pointermove", "pointer handler"), ("tip", "tooltip"), ("button.chip", "chip styling"), ("aria-pressed", "chip state"), ("rescale", "y-axis rescale note")):
        chk(f"hover: {why}", needle in raw, "missing")
    for w, E in EV.items():
        for b in E.books:
            for win in ("full", "r3"):
                d = E.dbook(b, win)
                chk(f"regime, B and k columns equal the ones derived from the SIGN columns {w} {b} {win}", bool((d["regime"] == d["reg_d"]).all() and (d["B"].astype(str) == d["B_d"]).all() and (d["k"] == d["k_d"]).all()), "decisions.csv disagrees with its own signs")
    # 7: dates in the text, hash, fixed statements
    known = set()
    for E in EV.values():
        known |= {str(pd.Timestamp(d).date()) for d in E.nav.date.unique()}
        for c in ("decision_date", "trade_date", "label_Nifty100", "label_MC100", "label_SC100", "label_MAUc1", "latest_label"):
            known |= set(E.dec[c].dropna().astype(str)) | set(E.dec3[c].dropna().astype(str))
        known |= set(E.inp["through"]) | set(E.led.first_decision) | set(E.led.last_decision) | set(E.led.a_session) | set(E.led.b_session)
    doc = Path(a.doc).read_text(encoding="utf-8")
    known |= set(DATE_RE.findall(doc))
    text = " ".join(pg.text)
    unknown = sorted({d for d in DATE_RE.findall(text) if d not in known})
    chk("every date in the text is a date of the evidence or of T16.md", not unknown, f"{unknown[:10]}")
    reg = doc[doc.index("\n## 1. Idea and references") + 1:doc.index("\n## 4. Results") + 1]
    reg = "\n".join(l.rstrip() for l in reg.replace("\r\n", "\n").split("\n"))
    h = hashlib.sha256(reg.encode("utf-8")).hexdigest()
    chk("pre-registration hash on the page", h[:16] in text, f"{h[:16]} not found")
    hdr = re.search(r"§1–§3 sha256:\*\* `([^`]*)`", doc)
    chk("T16.md header hash equals the recomputed hash", hdr is not None and hdr.group(1) == h, "frozen text changed")
    for w, E in EV.items():
        chk(f"audit.json of {w} carries the same pre-registration hash", E.audit.get("prereg_sha256") == h, "")
    low = text.lower()
    for s in ("no null", "no claim about chance", "provisional", "best of the ten rules", "four books are one market seen four times", "price index with no dividends and no fund cost"):
        chk(f"fixed statement on the page: {s}", s in low, "missing")
    chk("no null-based statistic on the page", "percentile" not in low.replace("no percentile", "") and "p-value" not in low.replace("no p-value", "").replace("no percentile and no p-value", ""), "a percentile or p-value is mentioned")
    chk("the page states the answer first", 'id="answer"' in raw and raw.find('id="answer"') < raw.find('id="rules-runs"') < raw.find('id="data"') < raw.find('id="example"') < raw.find('id="desc"') < raw.find('id="curves"') < raw.find('id="robust"') < raw.find('id="defs"'), "section order")
    # 8: T16-specific checks
    unesc = html.unescape
    # 8a the rules-and-runs table: first table, first block, every id defined in words, nothing used before or without it
    chk("the rules-and-runs table is the first table on the page", len(pg.tables) > 0 and pg.tables[0]["id"] == "rules-runs", f"first table id {pg.tables[0]['id'] if pg.tables else None!r}")
    rr_pos = raw.find('id="rules-runs"')
    chk("the rules-and-runs table comes before every chart and every other table", rr_pos > 0 and (raw.find("<svg") < 0 or raw.find("<svg") > rr_pos) and raw.find("<table") < rr_pos, "order")
    chk("the answer's count of passing comparisons comes before the rules-and-runs table", 0 < raw.find('data-k="npass:all"') < rr_pos, "npass:all")
    ok_blk = pg.rr_start is not None and pg.rr_end is not None and pg.rr_start < pg.rr_end
    chk("the rules-and-runs block was found", ok_blk, "no heading or table")
    if ok_blk:
        before = " ".join(pg.text[:pg.rr_start])
        block = " ".join(pg.text[pg.rr_start:pg.rr_end])
        used_before = sorted(set(ID_RE.findall(before)))
        chk("no rule id, benchmark, window, run or comparison label appears before the rules-and-runs table", not used_before, f"{used_before}")
        used_all = set(ID_RE.findall(text))
        undefined = sorted(x for x in used_all if x not in set(ID_RE.findall(block)))
        chk("every rule id, benchmark, window, run and comparison label on the page is defined in the rules-and-runs table", not undefined, f"{undefined}")
        m = re.search(r'<table class="wrap" id="rules-runs">.*?</table>', raw, re.S)
        chk("the rules-and-runs table is in the page's html", m is not None, "")
        if m:
            rows = re.findall(r"<tr><td>(.*?)</td><td>(.*?)</td><td>(.*?)</td><td>(.*?)</td><td>(.*?)</td></tr>", m.group(0), re.S)
            labels = {unesc(re.sub(r"<[^>]+>", "", r[0])).strip(): [unesc(re.sub(r"<[^>]+>", "", c)) for c in r] for r in rows}
            tr_count = m.group(0).count("<tr>") - 1
            chk("every row of the rules-and-runs table has five cells (label, kind, words, role, origin)", len(rows) == tr_count and tr_count > 0, f"{len(rows)} of {tr_count} rows")
            for lab in RULE_IDS + RUN_LABELS + ["hold_parent", "eq3_index_basket"]:
                keys = [k for k in labels if k == lab or k.startswith(lab + ",") or k.startswith(lab + " ")]
                chk(f"rules-and-runs table has a row for {lab}", len(keys) >= 1, "missing")
                if keys:
                    cells = labels[keys[0]]
                    chk(f"row {lab} has words, a role and an origin", all(len(c.strip()) >= 2 for c in cells[2:5]) , f"{cells[2:5]}")
            chk("rules-and-runs table has a row for each of the three indices held alone and for the constant mixes", any(k.startswith("hold_Nifty100") for k in labels) and any(k.startswith("cmix_") for k in labels), "")
            for r_ in ("50-all", "80-all"):
                chk(f"row {r_} says 25% each of the three indices and the liquid ETF in OUT-SELL and that it is new", "25% each of Nifty 100, Midcap 100, Smallcap 100 and the liquid ETF" in labels[r_][2] and labels[r_][3].strip() == "NEW", labels[r_][2][:80])
            for r_ in ("50-idx", "80-idx"):
                chk(f"row {r_} says 1 / (k + 1) of the BUY indices and cash", "1 / (k + 1)" in labels[r_][2], "")
            for r_ in ("50-orig", "50-half", "50-liq", "80-orig", "80-half", "80-liq"):
                chk(f"row {r_} is a comparator and a regression", labels[r_][3].strip() == "comparator; regression", labels[r_][3])
    # 8b the table's words for the new rules against the evidence's targets (every decision of every book and window, headline and R3)
    for w, E in EV.items():
        for b in E.books:
            for win in ("full", "r3"):
                d = E.dbook(b, win)
                for base, gold_ob in (("50", 0.5), ("80", 0.8)):
                    r_ = f"{base}-all"
                    z = lambda c: d[f"{c}_{r_}"].to_numpy(dtype=float)
                    reg_ = d["reg_d"].to_numpy()
                    os_, ob_, in_ = reg_ == "OUT-SELL", reg_ == "OUT-BUY", reg_ == "IN"
                    ok_os = bool(np.allclose(z("e")[os_], 0) and np.allclose(z("gold")[os_], 0) and np.allclose(z("cash")[os_], 0.25) and all(np.allclose(d[f"w_{i}_{r_}"].to_numpy(dtype=float)[os_], 0.25) for i in INDS))
                    ok_ob = bool(np.allclose(z("e")[ob_], 0) and np.allclose(z("gold")[ob_], gold_ob) and np.allclose(z("cash")[ob_], 1 - gold_ob) and all(np.allclose(d[f"w_{i}_{r_}"].to_numpy(dtype=float)[ob_], 0) for i in INDS))
                    ok_in = bool(np.allclose(z("e")[in_], 1) and np.allclose(z("gold")[in_], 0) and np.allclose(z("cash")[in_], 0))
                    chk(f"decisions of {r_} {w} {b} {win}: OUT-SELL = 25% each of cash and the three indices whatever B, OUT-BUY the base sleeve, IN the parent", ok_os and ok_ob and ok_in, f"os {ok_os} ob {ok_ob} in {ok_in}")
    # 8c the 24 comparisons are on the page, with R4 rows for every spell and both -all rules
    seen = set()
    for sp in pg.spans:
        if sp["cls"] == "s" and sp["a"]["data-k"].startswith("vd:"):
            seen.add(sp["a"]["data-k"])
    for w, E in EV.items():
        want = {f"vd:{w}|headline|headline|20.8|{base}|{cid}" for base in BASES for cid, _, _ in CIDS}
        chk(f"all 12 comparisons of {w} (C1-C6 x 2 bases) are on the page with a verdict", want <= seen, f"missing {sorted(want - seen)[:3]}")
        d0 = E.dbook(E.books[0])
        n_sp = len(spells_of(d0["reg_d"].to_numpy()))
        chk(f"R4 has one run per OUT-SELL spell in {w}", spell_ids(E) == list(range(1, n_sp + 1)) and n_sp > 0, f"{spell_ids(E)} vs {n_sp} spells")
        want_r4 = {f"vd:{w}|r4_s{s}|headline|20.8|{base}|{cid}" for s in range(1, n_sp + 1) for base in BASES for cid, _, _ in CIDS}
        chk(f"R4 rows for every spell, both bases and C1-C6 are on the page in {w}", want_r4 <= seen, f"missing {sorted(want_r4 - seen)[:3]}")
        r4 = E.rob[E.rob["variant"].str.startswith("r4_s")]
        chk(f"R4 evidence of {w} holds only the two -all rules", set(r4["run"]) == {"50-all", "80-all"}, f"{sorted(set(r4['run']))}")
        sp = spells_of(d0["reg_d"].to_numpy())
        chk(f"the last OUT-SELL spell of {w} {'ends at the window end (open position marked at the last close)' if w == 'w2' else 'is listed'}", (sp[-1][1] + 1 >= len(d0)) if w == "w2" else True, f"last spell decisions {sp[-1]} of {len(d0)}")
    chk("the page carries all 24 comparisons (12 per window, two windows)", len(EV) == 2 and sum(1 for k in seen if k.startswith("vd:") and "|headline|headline|20.8|" in k) == 24, f"{sum(1 for k in seen if '|headline|headline|20.8|' in k)} found")
    # 8d the k split sums
    for w, E in EV.items():
        for b in E.books:
            sel = ks_rows(E, b)
            wk = {k: sum(r["weeks"] for r in v) for k, v in sel.items()}
            chk(f"k split weeks sum to the OUT-SELL weeks {w} {b}", wk["k0"] + wk["k1"] + wk["k2"] == wk["all"] == int(rc(E, b, "full", "weeks_OUT-SELL")) and wk["kge1"] == wk["k1"] + wk["k2"], f"{wk}")
            chk(f"k split weeks equal the k counts of the decisions {w} {b}", (wk["k0"], wk["k1"], wk["k2"]) == (int(rc(E, b, "full", "k0")), int(rc(E, b, "full", "k1")), int(rc(E, b, "full", "k2"))), f"{wk}")
            for base in ("50", "80"):
                col = f"all_minus_idx_{base}"
                s = {k: sum(r[col] for r in v) for k, v in sel.items()}
                chk(f"k split -all minus -idx ({base}) sums: k0 + k1 + k2 = all and k>=1 = k1 + k2 {w} {b}", close(s["k0"] + s["k1"] + s["k2"], s["all"], 1e-9, 1e-12) and close(s["k1"] + s["k2"], s["kge1"], 1e-9, 1e-12), f"{s}")
            # the ledger rows written by the engine carry the same difference and the same k as the recomputation
            for k_, rows_ in sel.items():
                if k_ == "all":
                    for r in rows_:
                        chk(f"ledger all_minus_idx columns equal the recomputed ret(-all) - ret(-idx) {w} {b}", close(r["_csv_all_minus_idx_50"], r["all_minus_idx_50"], 1e-9, 1e-12) and close(r["_csv_all_minus_idx_80"], r["all_minus_idx_80"], 1e-9, 1e-12) and r["_csv_k"] == r["k"], f"{r['first_decision']}")
    # 8e the window ends
    for w, E in EV.items():
        for b in E.books:
            chk(f"daily NAV of {w} {b} ends on the window end {EXPECT_END[w]}", E.cal(b, "full")[-1] == EXPECT_END[w], E.cal(b, "full")[-1])
            chk(f"audit.json of {w} {b} ends on {EXPECT_END[w]}", E.audit["books"][b]["end"] == EXPECT_END[w], E.audit["books"][b]["end"])
    if "w2" in EV:
        chk("the W2 end date 2026-11-20 is on the page", "2026-11-20" in text, "not found")
    if "w1" in EV:
        chk("the W1 end date 2019-01-02 is on the page", "2019-01-02" in text, "not found")
    methods = page_path.with_name("METHODS.md")
    print(f"note: METHODS.md beside the page: {'present' if methods.exists() else 'NOT YET WRITTEN (R8; the write-up step writes it)'}")
    print(f"{page_path}: {nv:,} numbers, {ns:,} strings and {nd:,} date spans traced to the evidence; {len(lines)} curve charts with 6 overlays each; {len(pg.cards)} cards with dates; {N_CHECKS:,} checks, {len(FAILS)} failures")
    for f in FAILS[:40]:
        print("  FAIL", f)
    if len(FAILS) > 40:
        print(f"  ... {len(FAILS) - 40} more")
    return 1 if (FAILS or N_CHECKS == 0) else 0


if __name__ == "__main__":
    sys.exit(main())
