"""T16 analysis: reads ONLY the shipped evidence in evidence/<run>/{w1,w2}/ and prints section 4 of the write-up.

    python tests/T16/analyse.py [--run headline]              prints to stdout and writes tests/T16/evidence/analysis.log
    python tests/T16/analyse.py --evidence DIR [--out DIR]    DIR holds w1/ and w2/ (e.g. a smoke run); analysis.log then goes to --out (default DIR), never to tests/T16
    options: --books SCMO_0003   restrict to some books (for evidence that holds fewer than the four; the 3-of-4 verdicts then mean nothing)
             --require-v1        fail if verify_t16.json is missing in a window folder (default: required only when the evidence directory is called 'headline')

Exit code 1 if ANY validity gate failed (the engine's audit.json gates and pass flags, regression.json, the verifier's verify_t16.json, and the checks derived here from the evidence),
or if nothing was compared. If a gate failed nothing about results is printed (only the gate block) and analysis.log is not written. A missing verify_t16.json under --require-v1
(or for a run called 'headline') is a failed gate V1: the script says so and exits 1.

T16 has NO null and no chance claim (Manu's waiver, 2026-11-26): there are no percentiles or p-values here. A pass of C1-C6 (T16.md 2.3) is a count of books (>= 3 of 4) in which the stated
difference has the stated sign, a description of seen weeks. Imports nothing from the engine. No performance figure is typed in this file: every number comes from the evidence.

The module is also imported by report.py (class Win, the compute_* functions and the rules-and-runs table data) so that the page and the log use one set of numbers and one set of definitions;
check_page.py shares no code with it.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.dont_write_bytecode = True
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass
HERE = Path(__file__).resolve().parent
AA = HERE.parents[1]
PRIMARY = 20.8
COSTS = (0.0, PRIMARY, 50.0)
PASS_BOOKS = 3
TIE = 1e-12      # two statistics within this are the same number up to float noise (reported; the frozen rule is unrounded)
BOOKS = ["SCMO_0003", "SCMO_0007", "SCMO_0010", "SCMO_0029"]
RULES = ["50-orig", "50-half", "50-liq", "50-idx", "50-all", "80-orig", "80-half", "80-liq", "80-idx", "80-all"]
OLD_RULES = [r for r in RULES if not r.endswith("-all")]          # T15's eight (the V4(a) regression set)
BASES = ["50", "80"]
INDICES = ("Nifty100", "MC100", "SC100")
EXPECT_END = {"w1": "2019-01-02", "w2": "2026-11-20"}              # T16.md 3: the pre-registered window ends (a gate, not a result)
WIN_TXT = {"w1": "W1 (T11's / T14's / T15's inputs)", "w2": "W2 (T08's inputs, extended)"}
# (id, statistic, comparator kind, description). C2 and C6 are 'shallower or equal'; the others 'higher'.
COMPS = [("C1", "cagr", "orig", "-all earns more than the original rule (CAGR higher than -orig)"),
         ("C2", "max_dd", "orig", "-all's worst fall no deeper than the original's (max drawdown shallower or equal to -orig)"),
         ("C3", "cagr", "liq", "holding the three indices adds to holding only cash in the regime (CAGR higher than -liq)"),
         ("C4", "cagr", "half", "-all does better than half parent + half GOLDBEES in the regime (CAGR higher than -half)"),
         ("C5", "cagr", "idx", "ignoring the index signals in the regime earns more than following them (CAGR higher than -idx)"),
         ("C6", "max_dd", "idx", "ignoring the signals does not deepen the worst fall (max drawdown shallower or equal to -idx)")]
DD_IDS = ("C2", "C6")
CAPTION_W1 = "rebuilt from the parent's baskets and Eikon prices, not validated against a published NAV before 2019-01-02"
TITLES = {"4.0": "4.0 The rules and the runs in words (read this first)",
          "4.0a": "4.0a The worked example: one -all entry, one exit, one decision row, the series, and an index SIGN change that -all does not trade",
          "4.0b": "4.0b Gates, regime counts and reportability", "4.1": "4.1 Headline: the twenty-four comparisons C1-C6 and the verdict table",
          "4.2": "4.2 The descriptive headline: the D-table, trades and cost, weeks and sessions in each regime and k",
          "4.3": "4.3 The regime ledger (with -all minus -idx by k) and the comparators", "4.4": "4.4 Robustness R1-R5 (R4: leave one spell out)",
          "4.5": "4.5 Outcome map (T16.md 2.5), applied mechanically"}

# ── the rules and runs in words (T16.md 2.0 and 2.1; shared with report.py, which renders them as the page's first table) ──
RULE_WORDS = {  # id -> (base, IN, OUT-BUY, OUT-SELL, role, origin)
    "50-orig": ("50/50", "the parent's own basket", "50% GOLDBEES, 50% liquid ETF (cash)", "50% GOLDBEES, 50% cash (the same sleeve)", "comparator; regression", "T06 / T11 Part A"),
    "50-half": ("50/50", "the parent's own basket", "50% GOLDBEES, 50% cash", "50% the parent's basket, 50% GOLDBEES", "comparator; regression", "T14"),
    "50-liq": ("50/50", "the parent's own basket", "50% GOLDBEES, 50% cash", "100% liquid ETF", "comparator; regression", "T14"),
    "50-idx": ("50/50", "the parent's own basket", "50% GOLDBEES, 50% cash", "liquid ETF plus each index whose own SIGN is BUY, in equal parts 1 / (k + 1) (k = how many are BUY), rebalanced when that set changes", "comparator; regression", "T15"),
    "50-all": ("50/50", "the parent's own basket", "50% GOLDBEES, 50% cash", "25% each of Nifty 100, Midcap 100, Smallcap 100 and the liquid ETF, whatever each index's own SIGN is; set on entry, left to drift, traded only when the book leaves OUT-SELL", "NEW", "T16 (Manu, 2026-11-26)"),
    "80-orig": ("80/20", "the parent's own basket", "80% GOLDBEES, 20% cash", "20% GOLDBEES, 80% cash", "comparator; regression", "T08 / T11 Part B"),
    "80-half": ("80/20", "the parent's own basket", "80% GOLDBEES, 20% cash", "50% the parent's basket, 50% GOLDBEES", "comparator; regression", "T14"),
    "80-liq": ("80/20", "the parent's own basket", "80% GOLDBEES, 20% cash", "100% liquid ETF", "comparator; regression", "T14"),
    "80-idx": ("80/20", "the parent's own basket", "80% GOLDBEES, 20% cash", "liquid ETF plus each index whose own SIGN is BUY, in equal parts 1 / (k + 1), rebalanced when that set changes", "comparator; regression", "T15"),
    "80-all": ("80/20", "the parent's own basket", "80% GOLDBEES, 20% cash", "25% each of Nifty 100, Midcap 100, Smallcap 100 and the liquid ETF, whatever each index's own SIGN is; set on entry, left to drift, traded only when the book leaves OUT-SELL", "NEW", "T16 (Manu, 2026-11-26)"),
}
COMPARATOR_WORDS = [  # (label, words, role)
    ("hold_parent", "hold the book's own parent from the first session (no timing; the parent's rebalances only)", "comparator (benchmark)"),
    ("hold_Nifty100, hold_MC100, hold_SC100", "buy that price index at the first session's close and hold it, no trades (hold each index alone)", "comparator (benchmark)"),
    ("eq3_index_basket", "one third each of Nifty 100, Midcap 100 and Smallcap 100, rebalanced at every weekly decision, 20.8 bps", "comparator (benchmark)"),
    ("cmix_<rule>  (cmix_50-all, cmix_80-all, ...)", "the constant mix at that rule's own average shares of parent, GOLDBEES, cash and each index (the mean over the weekly decisions of the rule's target shares), rebalanced at every decision", "comparator (benchmark)")]
STATE_WORDS = ("States, read every Friday: IN = the Nifty 100, Midcap 100 and Smallcap 100 weekly supertrend SIGNs are all BUY (the book holds the parent's basket); otherwise the switch is OUT and the book holds a sleeve: "
               "OUT-BUY = OUT and the weekly MAUc1 gold SIGN is BUY; OUT-SELL = OUT and MAUc1 is SELL. B = the indices whose own SIGN is BUY in an OUT week and k = how many (0, 1 or 2; 3 would be IN). "
               "Base sleeve: 50 = 50% GOLDBEES / 50% cash; 80 = 80% GOLDBEES / 20% cash when gold is BUY and 20% / 80% when gold is SELL. Cash = the LBES liquid-ETF level. "
               "The ten rules differ only in what they hold in OUT-SELL. A rule id is <base>-<its OUT-SELL holding>, such as 50-all; a bare suffix (-orig, -half, -liq, -idx, -all) means that holding on both bases.")
RUN_WORDS = [  # (label, words, role); the window dates are filled in from the evidence
    ("W1", "the parent rebuilt from its baskets and stock prices (no published NAV exists before 2019-01-02)", "window", "T11's / T14's / T15's inputs, pinned"),
    ("W2", "the published NAVs' calendar (SCMO_0007 starts two days later)", "window", "T08's inputs, extended from T15's 2026-10-30"),
    ("live", "W2's decisions from 2021-11-01, the AA books' live period (R3 on W2)", "robustness", "T14"),
    ("R1", "round-trip cost 0 and 50 bps instead of 20.8", "robustness", "T14"),
    ("R2", "LIQUIDCASE as the cash leg instead of the LBES level (W1 the whole window; W2 from 2024-01-24)", "robustness", "T14"),
    ("R3", "a later start: W1 from 2015-01-02, W2 live from 2021-11-01, each with its own first state (both start in OUT-SELL)", "robustness", "T14"),
    ("R4", "leave one OUT-SELL spell out: the two -all rules hold 100% cash in that spell only (as -liq), everything else unchanged", "robustness", "T14 / T15, here applied to -all"),
    ("R5", "a fund-cost drag of 0.5 pp a year on each index leg (index prices times (1 - 0.005 / 252) per session)", "robustness", "T15")]
COMP_WORDS = [(cid, desc) for cid, _s, _k, desc in COMPS]


def pct(x, d=2):
    return "n/a" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x * 100:.{d}f}%"


def pp(x, d=2):
    return "n/a" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x * 100:+.{d}f}"


def tab(df: pd.DataFrame, **kw) -> str:
    return df.to_string(index=False, **kw)


class Win:
    """The evidence of one window, loaded once."""

    def __init__(self, evdir: Path, win: str, books=None):
        self.win, self.dir = win, evdir / win
        d = self.dir
        self.audit = json.loads((d / "audit.json").read_text(encoding="utf-8"))
        self.reg = json.loads((d / "regression.json").read_text(encoding="utf-8"))
        self.verify = json.loads((d / "verify_t16.json").read_text(encoding="utf-8")) if (d / "verify_t16.json").exists() else None
        self.stats = pd.read_csv(d / "stats.csv")
        self.rob = pd.read_csv(d / "robustness.csv")
        self.dec = pd.read_csv(d / "decisions.csv")
        self.dec3 = pd.read_csv(d / "decisions_r3.csv")
        self.trades = pd.read_csv(d / "trades.csv")
        self.ledger = pd.read_csv(d / "regime_ledger.csv")
        self.cmix = pd.read_csv(d / "constant_mix_params.csv")
        self.nav = pd.read_csv(d / "daily_nav.csv", parse_dates=["date"])
        self.inputs = pd.read_csv(d / "inputs.csv")
        self.books = [b for b in BOOKS if (books is None or b in books) and b in set(self.stats["book"])]
        assert self.books, f"no book in {d}"

    def row(self, variant, window, cost, book, run, frame=None):
        f = self.stats if frame is None else frame
        r = f[(f["variant"] == variant) & (f["window"] == window) & (f["cost_bps"] == cost) & (f["book"] == book) & (f["run"] == run)]
        assert len(r) == 1, (variant, window, cost, book, run, len(r))
        return r.iloc[0]

    def get(self, variant, window, cost, book, run):
        return self.row(variant, window, cost, book, run, self.stats if variant == "headline" else self.rob)

    def dates(self, book):
        n = self.nav[(self.nav["book"] == book) & (self.nav["run"] == "50-all") & (self.nav["cost_bps"] == PRIMARY)]
        return n["date"].iloc[0].date(), n["date"].iloc[-1].date(), int(len(n))

    def spell_ids(self) -> list[int]:
        return sorted({int(v.split("_s")[1]) for v in self.rob["variant"].unique() if v.startswith("r4_s")})


# ── the comparisons ───────────────────────────────────────────────────────────
def compare(W: Win, variant, window, cost, base, all_get=None, comp_get=None) -> list[dict]:
    """C1-C6 for one base: per book the -all value, the comparator value, the difference and whether it passes; the count and the verdict."""
    ig = all_get or (lambda b, run: W.get(variant, window, cost, b, run))
    cg = comp_get or (lambda b, run: W.get(variant, window, cost, b, run))
    out = []
    for cid, stat, kind, desc in COMPS:
        per = []
        for b in W.books:
            a, c = float(ig(b, f"{base}-all")[stat]), float(cg(b, f"{base}-{kind}")[stat])
            dd = cid in DD_IDS
            ok = (a >= c) if dd else (a > c)           # the frozen rule: unrounded
            ok_tol = (a >= c - TIE) if dd else (a > c + TIE)
            per.append({"book": b, "all": a, "comp": c, "diff": a - c, "ok": bool(ok), "tie": bool(abs(a - c) <= TIE), "ok_tol": bool(ok_tol)})
        n = sum(p["ok"] for p in per)
        n_tol = sum(p["ok_tol"] for p in per)
        out.append({"id": cid, "stat": stat, "kind": kind, "desc": desc, "per": per, "n_ok": n, "pass": bool(n >= PASS_BOOKS), "n_ties": sum(p["tie"] for p in per), "pass_tol": bool(n_tol >= PASS_BOOKS)})
    return out


def comp_line(c: dict) -> str:
    cells = "  ".join(f"{p['book'][-4:]} {pp(p['diff'])}{'*' if p['ok'] else ' '}" for p in c["per"])
    return f"{c['id']}  vs {c['kind']:<4} {c['stat']:<6} diff pp (all - comparator; * = counts toward pass): {cells}   -> {c['n_ok']} of {len(c['per'])}  {'PASS' if c['pass'] else 'FAIL'}"


# ── gates ─────────────────────────────────────────────────────────────────────
def gate_rows(W: Win, need_v1: bool) -> list[tuple[str, bool, str]]:
    a, r = W.audit, W.reg
    g = a["gates"]
    ra = r["a_nav_regression"]
    rows = [("engine gates (audit.json)", bool(g["all"]), " ".join(f"{k} {v}" for k, v in g.items())),
            ("V2 point in time", bool(a["v2"]["pass"]), f"{a['v2']['checks']} checks, {a['v2']['violations']} violations"),
            ("V3 index tie (Master Index = D25/D25d close)", bool(a["v3"]["pass"]), f"{a['v3']['labels_checked']} labels, {a['v3']['violations']} violations, worst rel {a['v3']['worst_rel_diff']:.1e}"),
            ("V4(a) the eight T15 rules reproduce T15", bool(ra["pass"]),
             f"nav rows {ra['rows_compared']} (worst {ra['worst_rel_diff']:.1e}), trade rows {ra['trade_rows_compared']} (worst {ra['worst_trade_rel_diff']:.1e}), boundary {ra.get('boundary')}"),
            ("V4(b) -idx and -all on cash equal -liq", all(v["pass"] for v in r["b_index_priced_as_cash"].values()),
             f"{len(r['b_index_priced_as_cash'])} book-base-rule entries, worst {max(v['max_rel_diff'] for v in r['b_index_priced_as_cash'].values()):.1e}"),
            ("V4(c) -idx and -all equal -liq before the first index trade", all(v["pass"] for v in r["c_idx_equals_liq_before_first_index_trade"].values()),
             f"{len(r['c_idx_equals_liq_before_first_index_trade'])} entries, worst {max(v['max_rel_diff'] for v in r['c_idx_equals_liq_before_first_index_trade'].values()):.1e}"),
            ("V4(d) shared code", bool(r["d_shared_code"]["pass"]), f"changed: {', '.join(r['d_shared_code']['changed_functions'])}"),
            ("V4(e) signals and B equal the Master / weekly files", all(v["pass"] for v in r["e_signals"].values()), f"{sum(v['decisions'] for v in r['e_signals'].values())} decisions"),
            ("V4(f) one-instrument identity, G0 / seam", all(v["pass"] for v in r["f_one_instrument"].values()) and all(v["pass"] for v in (r.get("f_g0") or r.get("f_seam_2019") or {}).values()), ""),
            ("V5 trade and cost identities (incl. the all_* identities)", bool(a["v5"]["pass"]) and all(k in a["v5"]["worst"] for k in ("all_os_equal_quarters_gap", "all_os_parent_gold_after", "all_outside_os_index_after", "all_trades_inside_a_spell")),
             f"{a['v5']['trades_checked']} trades, {a['v5']['all_trades_into_OUT_SELL_checked']} -all trades into OUT-SELL (quarters to {a['v5']['worst']['all_os_equal_quarters_gap']:.1e}), "
             f"{a['v5']['worst']['all_trades_inside_a_spell']:.0f} -all trades inside a spell, worst {max(a['v5']['worst'].values()):.1e}"),
            ("step 1 counts reproduced", bool(a["step1_counts_reproduced"]["pass"]), f"{len(a['step1_counts_reproduced']['detail'])} book-windows"),
            ("prereg sha256 in audit equals T16.md header", False, "")]
    t16 = (HERE / "T16.md").read_text(encoding="utf-8")
    hdr = t16.split("§1–§3 sha256:** `")[1].split("`")[0]
    rows[-1] = ("prereg sha256 in audit equals T16.md header", a["prereg_sha256"] == hdr, hdr[:16])
    ends = {b: a["books"][b]["end"] for b in W.books}
    rows.append((f"window end equals the pre-registered {EXPECT_END[W.win]}", all(e == EXPECT_END[W.win] for e in ends.values()), ", ".join(f"{b[-4:]} {e}" for b, e in ends.items())))
    # the engine's own gates cover the other books: check the evidence's calendar ends on that date too
    bad_cal = [b for b in W.books if str(W.dates(b)[1]) != EXPECT_END[W.win]]
    rows.append(("daily_nav.csv ends on the window end", not bad_cal, f"{len(W.books)} books, {len(bad_cal)} differ"))
    # evidence self-consistency: stats end NAV equals the daily NAV's last value
    bad = 0
    for b in W.books:
        for run in RULES:
            for cost in COSTS:
                n = W.nav[(W.nav["book"] == b) & (W.nav["run"] == run) & (W.nav["cost_bps"] == cost)]["nav"].values
                s = float(W.get("headline", "full", cost, b, run)["end_nav"])
                bad += abs(n[-1] / s - 1) > 1e-12
    rows.append(("stats.csv end NAV equals daily_nav.csv", bad == 0, f"{len(W.books) * len(RULES) * len(COSTS)} runs, {bad} differ"))
    # the R4 rows exist for every OUT-SELL spell and hold only the two -all rules
    sp = W.audit["books"][W.books[0]]["OUT_SELL_lengths"]
    r4 = W.rob[W.rob["variant"].str.startswith("r4_s")]
    ok_r4 = sorted(W.spell_ids()) == list(range(1, len(sp) + 1)) and set(r4["run"]) == {"50-all", "80-all"}
    rows.append(("R4 rows: one run per OUT-SELL spell, only the two -all rules", ok_r4, f"{len(W.spell_ids())} spells, runs {sorted(set(r4['run']))}"))
    # the -all index weeks equal the OUT-SELL weeks; the ledger's weeks per k equal the audit's
    lg = W.ledger[(W.ledger["level"] == "stretch") & (W.ledger["window"] == "full")]
    bad_k = []
    for b in W.books:
        x = lg[lg["book"] == b]
        for k in (0, 1, 2):
            if int(x[x["k"] == k]["weeks"].sum()) != int(W.audit["books"][b][f"k{k}"]):
                bad_k.append((b, k))
    rows.append(("ledger weeks per k equal the audit's k counts (the k split of -all minus -idx covers every OUT-SELL week)", not bad_k, f"{len(W.books)} books, {len(bad_k)} differ"))
    if W.verify is None:
        rows.append(("V1 independent verifier", not need_v1, "verify_t16.json missing" + (" (REQUIRED: run `python analysis/verify_t16.py --run <run>` first)" if need_v1 else " (not required for this evidence)")))
    else:
        v = W.verify
        st = v.get("selftest")
        good = bool(v.get("exit_ok") and v.get("gate_compared", 0) > 0 and v.get("gate_failures_and_missing", 1) == 0 and ((st is None and not need_v1) or (st is not None and st.get("detected"))))
        rows.append(("V1 independent verifier", good, f"{v.get('gate_compared', 'n/a'):,} comparisons, {v.get('gate_failures_and_missing', 'n/a')} failures or missing, "
                     f"corruptions {'all detected' if st and st.get('detected') else ('not run' if st is None else 'NOT all detected')}"))
    return rows


# ── sections ──────────────────────────────────────────────────────────────────
def sec_gates(Ws: dict, need_v1: bool) -> tuple[list[str], bool]:
    L, ok = [], True
    for w, W in Ws.items():
        L.append(f"-- {WIN_TXT[w]}: evidence {W.dir.relative_to(AA).as_posix() if str(W.dir).startswith(str(AA)) else W.dir}")
        for name, good, det in gate_rows(W, need_v1):
            ok &= good
            L.append(f"   {'PASS' if good else 'FAIL'}  {name}  {det}")
    return L, ok


def sec_rules(Ws: dict) -> list[str]:
    """4.0: the rules-and-runs table in words, before any other table or number that names a rule or a run."""
    L = [STATE_WORDS, ""]
    L.append("Rules (what each book holds in each state; they differ only in OUT-SELL):")
    for r in RULES:
        base, i_, ob, os_, role, origin = RULE_WORDS[r]
        L.append(f"  {r:<8} base {base}.  IN: {i_}.  OUT-BUY: {ob}.  OUT-SELL: {os_}.  Role: {role}.  From: {origin}.")
    L.append("")
    L.append("Benchmarks printed beside the rules:")
    for lab, words, role in COMPARATOR_WORDS:
        L.append(f"  {lab}: {words}. Role: {role}.")
    L.append("")
    L.append("Runs and windows (dates from the evidence):")
    for lab, words, role, origin in RUN_WORDS:
        extra = ""
        if lab in ("W1", "W2"):
            W = Ws.get(lab.lower())
            if W is not None:
                a, z, _ = W.dates(W.books[0])
                n = W.audit["books"][W.books[0]]["weeks"]
                extra = f" {a} -> {z}, {n} weekly decisions."
        L.append(f"  {lab:<5} {words}.{extra} Role: {role}. From: {origin}.")
    L.append("")
    L.append("The six comparisons (each about the -all rule of a base b against the comparator of the same base and book; passes when the stated sign holds in at least 3 of the 4 books; unrounded statistics, 20.8 bps, whole window):")
    for cid, desc in COMP_WORDS:
        L.append(f"  {cid}: {desc}.")
    return L


def sec_counts(Ws: dict) -> list[str]:
    L = []
    for w, W in Ws.items():
        L.append(f"-- {WIN_TXT[w]}: regime counts from the engine's own series (equal to logs/step_1_spell_counts.json); -all holds the three indices in every OUT-SELL week")
        rows = []
        for b in W.books:
            x = W.audit["books"][b]
            first, last, n = W.dates(b)
            rows.append({"book": b, "start": first, "end": last, "sessions": n, "decisions": x["weeks"], "IN": x["weeks_IN"], "OUT-BUY": x["weeks_OUT_BUY"], "OUT-SELL (-all weeks)": x["weeks_OUT_SELL"],
                         "OS spells": len(x["OUT_SELL_lengths"]), "k0": x["k0"], "k1": x["k1"], "k2": x["k2"], "-idx index weeks": x["index_weeks"], "-idx index spells": x["index_spells"], "B changes": x["B_changes"]})
        L.append(tab(pd.DataFrame(rows)))
        b0 = W.books[0]
        L.append(f"   trades from regime, gold and B changes per rule ({b0}): " + ", ".join(f"{r} {W.audit['books'][b0]['trades_due_per_rule'][r]}" for r in RULES))
        L.append(f"   OUT-SELL spells and their B sequences ({b0}; B x weeks; -all holds the same four lines through all of them):")
        for i, (sp, seq) in enumerate(zip(W.audit["books"][b0]["OUT_SELL_lengths"], W.audit["books"][b0]["B_sequences"]), 1):
            L.append(f"     spell {i:>2}, {sp:>2} weeks: " + ", ".join(f"{n} {k}" for n, k in seq))
        L.append("   sessions held in each state (the decision's target is held from the session after the decision), per book: " +
                 "; ".join(f"{b[-4:]}: " + ", ".join(f"{k} {v}" for k, v in W.audit["books"][b]["sessions_by_state"].items()) for b in W.books))
        ns = W.audit["books"][b0]["index_sessions_without_a_bar"]
        L.append("   calendar sessions without an index bar (last close carried; decision sessions only): " + ", ".join(f"{n}: {v}" for n, v in ns.items()))
        L.append("")
    return L


def sec_worked(Ws: dict) -> list[str]:
    L = []
    for w, W in Ws.items():
        b0 = W.books[0]
        a = W.audit["v5"]["worked_examples"]
        L.append(f"-- {WIN_TXT[w]}, book {b0}, 20.8 bps, rule `50-all`: real trades (values at the fill prices; shares of the value after cost)")
        if w == "w1":
            L.append(f"   (W1's parent is {CAPTION_W1})")
        for key in ("50-all|regime_in", "50-all|regime_in_k0", "50-all|regime_in_k1", "50-all|regime_out"):
            x = a.get(key)
            if not x:
                continue
            V = x["V_after"]
            L.append(f"   {key}: decided {x['decision_date']} (regime {x['regime']}, B = {x['B']}, k = {x['k']}), traded {x['trade_date']} (session idx {x['idx']}); V = {x['V']:.6f}, traded {x['traded']:.6f}, cost {x['cost']:.8f}")
            L.append(f"      before: stocks {x['stock_before']:.6f}  GOLDBEES {x['gold_before']:.6f}  cash {x['cash_before']:.6f}  " + "  ".join(f"{n} {x[n + '_before']:.6f}" for n in INDICES))
            L.append(f"      after : stocks {x['stock_after']:.6f}  GOLDBEES {x['gold_after']:.6f}  cash {x['cash_after']:.6f}  " + "  ".join(f"{n} {x[n + '_after']:.6f}" for n in INDICES) + f"   (V after {V:.6f})")
            note = ("   (the exit: the whole book moves to the parent's basket or the base sleeve, whichever the decision that ends OUT-SELL sets)" if key.endswith("regime_out")
                    else "   (every line a quarter, whatever the index SIGNs; no parent, no GOLDBEES)")
            L.append("      shares after cost: " + "  ".join(f"{n} {x[n + '_after'] / V:.6f}" for n in INDICES) + f"  cash {x['cash_after'] / V:.6f}" + note)
            L.append("      index fill prices (OHLC4): " + "  ".join(f"{n} {x['index_fill_prices'][n]:.2f}" for n in INDICES))
        x = a.get("50-all|B_change_not_traded")
        if x:
            L.append(f"   50-all|B_change_not_traded: decided {x['decision_date']}: the set of BUY indices changed from B = {x['B_before']} to B = {x['B_after']} inside OUT-SELL; on the next session {x['next_session']} "
                     f"-all made {x['50-all_trades_on_that_session']} trades (it holds all three indices whatever B), -idx made {x['50-idx_trades_on_that_session']} (it rebalances when B changes)")
        d = W.dec[(W.dec["book"] == b0) & (W.dec["regime"] == "OUT-SELL")]
        for lab, sel in (("first OUT-SELL week with at least one index on SELL (k = 2)", d[d["k"] == 2]), ("first OUT-SELL week with all three indices on SELL (k = 0)", d[d["k"] == 0])):
            if len(sel):
                r = sel.iloc[0]
                L.append(f"   one decision row ({lab}): j {int(r['j'])}, decided {r['decision_date']}, signs N100 {r['sign_Nifty100']}, MC100 {r['sign_MC100']}, SC100 {r['sign_SC100']}, MAUc1 {r['sign_MAUc1']}; "
                         f"regime {r['regime']}, B = {r['B']}, k = {int(r['k'])}; target of 50-all: parent {r['e_50-all']:.4f}, GOLDBEES {r['gold_50-all']:.4f}, cash {r['cash_50-all']:.4f}, "
                         f"N100 {r['w_Nifty100_50-all']:.4f}, MC100 {r['w_MC100_50-all']:.4f}, SC100 {r['w_SC100_50-all']:.4f}; target of 50-idx: cash {r['cash_50-idx']:.4f}, "
                         f"N100 {r['w_Nifty100_50-idx']:.4f}, MC100 {r['w_MC100_50-idx']:.4f}, SC100 {r['w_SC100_50-idx']:.4f}; traded {r['trade_date']}")
        first, last, n = W.dates(b0)
        navs = W.nav[(W.nav["book"] == b0) & (W.nav["cost_bps"] == PRIMARY)]
        L.append(f"   the path: {n} sessions {first} -> {last}; 50-all NAV {float(navs[navs['run'] == '50-all']['nav'].iloc[0]):.6f} -> {float(navs[navs['run'] == '50-all']['nav'].iloc[-1]):.6f}; "
                 f"index closes first -> last are in the engine's index files (inputs.csv lists them: " + ", ".join("/".join(Path(f).parts[-2:]) for f in W.inputs['file'] if 'daily_ohlcv' in f) + ")")
        L.append("")
    return L


def per_comparator_table(W: Win, cs_by_base: dict, variant="headline", window="full", cost=PRIMARY) -> list[str]:
    """beside each comparison: the pp difference per book, Calmar, volatility, trades and cost paid, -all next to the comparator."""
    L = []
    for base in BASES:
        for kind in ("orig", "liq", "half", "idx"):
            rows = []
            for b in W.books:
                x, c = W.get(variant, window, cost, b, f"{base}-all"), W.get(variant, window, cost, b, f"{base}-{kind}")
                rows.append({"book": b, "CAGR all | comp": f"{pct(x['cagr'])} | {pct(c['cagr'])}", "CAGR diff pp": pp(x["cagr"] - c["cagr"]), "max DD all | comp": f"{pct(x['max_dd'])} | {pct(c['max_dd'])}",
                             "max DD diff pp": pp(x["max_dd"] - c["max_dd"]), "Calmar all | comp": f"{x['calmar']:.3f} | {c['calmar']:.3f}", "vol all | comp": f"{pct(x['vol'])} | {pct(c['vol'])}",
                             "trades all | comp": f"{int(x['trades'])} | {int(c['trades'])}", "cost paid all | comp": f"{x['cost_paid']:.5f} | {c['cost_paid']:.5f}"})
            L.append(f"   {base}-all against {base}-{kind}:")
            L.append("   " + tab(pd.DataFrame(rows)).replace("\n", "\n   "))
    return L


def sec_headline(Ws: dict) -> tuple[list[str], dict]:
    L, res = [], {}
    L.append("Pass mark per comparison: the stated difference has the stated sign in at least 3 of the 4 books (T16.md 2.3). A description of seen weeks; no null, no percentile, no p-value, no claim about chance.")
    L.append("The four books share one market; in OUT-SELL weeks -all holds the same four lines in every book, so '3 of 4' is weaker here than in earlier tests.")
    L.append("")
    for w, W in Ws.items():
        a0, z0, _ = W.dates(W.books[0])
        L.append(f"== {WIN_TXT[w]}, after {PRIMARY} bps, whole window {a0} -> {z0}")
        for base in BASES:
            cs = compare(W, "headline", "full", PRIMARY, base)
            res[(w, base)] = cs
            L.append(f"   {base}/{100 - int(base)} base (`{base}-all` against `{base}-orig`, `{base}-liq`, `{base}-half`, `{base}-idx`):")
            for c in cs:
                L.append("     " + comp_line(c))
        L.append(f"   beside each comparison: CAGR, max drawdown, Calmar, volatility, trades and cost paid (cost as a share of the starting NAV), -all next to the comparator, {PRIMARY} bps, {a0} -> {z0}:")
        L += per_comparator_table(W, res)
        L.append("")
    L.append("Verdict table (24 comparisons): " + "; ".join(f"{w} {b}: " + " ".join(f"{c['id']} {'PASS' if c['pass'] else 'FAIL'}" for c in res[(w, b)]) for (w, b) in res))
    ties = [(w, b, c["id"], p["book"], p["diff"]) for (w, b), cs in res.items() for c in cs for p in c["per"] if p["tie"]]
    flips_tol = [(w, b, c["id"]) for (w, b), cs in res.items() for c in cs if c["pass"] != c["pass_tol"]]
    L.append("Ties (|difference| <= 1e-12, the same number up to float noise; the frozen rule compares the unrounded values): " + ("none" if not ties else "; ".join(f"{w} {b}-all {cid} {bk} (diff {d:+.2e})" for w, b, cid, bk, d in ties)) +
             f". Verdicts that would change if ties were counted as equal: {'none' if not flips_tol else flips_tol}.")
    npass = sum(c["pass"] for cs in res.values() for c in cs)
    ncomp = sum(len(cs) for cs in res.values())
    L.append(f"{npass} of {ncomp} comparisons pass. Choosing the best of the ten rules from these tables is a selection on seen data. Findings are PROVISIONAL at most.")
    return L, res


def weeks_sessions_table(W: Win) -> list[str]:
    """weeks (weekly decisions) and sessions held in each regime and, in OUT-SELL, each k, per book."""
    rows = []
    for b in W.books:
        x = W.audit["books"][b]
        s = x["sessions_by_state"]
        first, last, n = W.dates(b)
        rows.append({"book": b, "start": first, "end": last, "sessions": n, "wk IN": x["weeks_IN"], "wk OUT-BUY": x["weeks_OUT_BUY"], "wk OUT-SELL": x["weeks_OUT_SELL"], "wk k0": x["k0"], "wk k1": x["k1"], "wk k2": x["k2"],
                     "sess IN": s["IN"], "sess OUT-BUY": s["OUT-BUY"], "sess OUT-SELL": s["OUT-SELL"], "sess k0": s["OUT-SELL_k0"], "sess k1": s["OUT-SELL_k1"], "sess k2": s["OUT-SELL_k2"]})
    return [tab(pd.DataFrame(rows))]


def sec_dtable(Ws: dict) -> list[str]:
    L = []
    for w, W in Ws.items():
        L.append(f"== {WIN_TXT[w]}" + (f" (W1's parent is {CAPTION_W1})" if w == "w1" else ""))
        L.append("-- weeks (weekly decisions) and sessions in each regime and in each k (k = number of BUY indices in OUT-SELL)")
        L += weeks_sessions_table(W)
        for b in W.books:
            first, last, n = W.dates(b)
            L.append(f"-- {b}, {PRIMARY} bps, {first} -> {last}, {n} sessions")
            rows = []
            for run in RULES + ["hold_parent"]:
                x = W.get("headline", "full", PRIMARY, b, run)
                rows.append({"run": run, "CAGR": pct(x["cagr"]), "max drawdown": pct(x["max_dd"]), "Calmar": f"{x['calmar']:.3f}", "vol": pct(x["vol"]), "trades": int(x["trades"]),
                             "cost paid": f"{x['cost_paid']:.5f}", "regime": int(x["regime_trades"]), "B change": int(x["index_set_trades"]), "basket": int(x["basket_trades"]), "switch": int(x["switch_trades"])})
            L.append(tab(pd.DataFrame(rows)))
            for base in BASES:
                for k in ("orig", "liq", "half", "idx"):
                    a, c = W.get("headline", "full", PRIMARY, b, f"{base}-all"), W.get("headline", "full", PRIMARY, b, f"{base}-{k}")
                    L.append(f"   {base}-all minus {base}-{k}: CAGR {pp(a['cagr'] - c['cagr'])} pp, max drawdown {pp(a['max_dd'] - c['max_dd'])} pp, Calmar {a['calmar'] - c['calmar']:+.3f}, vol {pp(a['vol'] - c['vol'])} pp, "
                             f"trades {int(a['trades'] - c['trades']):+d}, cost paid {a['cost_paid'] - c['cost_paid']:+.5f}")
            L.append("")
    return L


def k_split(W: Win, b: str) -> pd.DataFrame:
    """-all minus -idx summed over the stretches of each k (and over k >= 1), per base, from the ledger's all_minus_idx_50 / _80 columns."""
    lg = W.ledger[(W.ledger["book"] == b) & (W.ledger["window"] == "full") & (W.ledger["level"] == "stretch")]
    rows = []
    for lab, sel in (("k = 0", lg[lg["k"] == 0]), ("k = 1", lg[lg["k"] == 1]), ("k = 2", lg[lg["k"] == 2]), ("k >= 1", lg[lg["k"] >= 1]), ("all OUT-SELL weeks", lg)):
        rows.append({"stretches of": lab, "n stretches": int(len(sel)), "weeks": int(sel["weeks"].sum()), "sum 50-all - 50-idx (pp, summed over stretches)": pp(float(sel["all_minus_idx_50"].sum())),
                     "sum 80-all - 80-idx (pp)": pp(float(sel["all_minus_idx_80"].sum()))})
    return pd.DataFrame(rows)


def sec_ledger(Ws: dict) -> list[str]:
    L = []
    for w, W in Ws.items():
        L.append(f"== {WIN_TXT[w]}: regime ledger (span: close of the session on which the span's first decision is traded -> close of the session on which the decision that ends it is traded; see evidence_contract.md)")
        lg = W.ledger
        b0 = W.books[0]
        inst = lg[(lg["book"] == b0) & (lg["window"] == "full")].copy()
        cols = ["level", "spell_no", "stretch_no", "B", "k", "first_decision", "last_decision", "weeks", "entered_from", "exited_to", "goldbees_return", "cash_return"] + [f"{n}_return" for n in INDICES]
        t = inst[cols].copy()
        for c in cols[-5:]:
            t[c] = t[c].map(pct)
        L.append("-- instruments over each span (identical in every book) and the parent per book (hold-the-parent, 0 cost)")
        t["parent " + b0[-4:]] = inst["parent_return"].map(pct).values
        for b in W.books[1:]:
            t["parent " + b[-4:]] = lg[(lg["book"] == b) & (lg["window"] == "full")]["parent_return"].map(pct).values
        L.append(tab(t))
        for b in W.books:
            x = lg[(lg["book"] == b) & (lg["window"] == "full")]
            r = x[["level", "spell_no", "stretch_no", "B", "k", "weeks"]].copy()
            for rule in RULES:
                r[rule] = x[f"ret_{rule}"].map(pct).values
            r["all-idx 50 pp"] = x["all_minus_idx_50"].map(pp).values
            r["all-idx 80 pp"] = x["all_minus_idx_80"].map(pp).values
            L.append(f"-- {b}: each rule's return over each span (20.8 bps); the last two columns = ret_<base>-all minus ret_<base>-idx")
            L.append(tab(r))
        L.append(f"-- -all minus -idx by k (sum over the B stretches of each k of ret_<base>-all minus ret_<base>-idx, a simple sum of period returns; weeks = OUT-SELL decisions in those stretches), {PRIMARY} bps:")
        for b in W.books:
            first, last, n = W.dates(b)
            L.append(f"   {b}, {first} -> {last}:")
            L.append("   " + tab(k_split(W, b)).replace("\n", "\n   "))
        L.append("")
    L.append("== Comparators (benchmarks, not nulls), 20.8 bps, from the first session of each window to its last")
    for w, W in Ws.items():
        a0, z0, _ = W.dates(W.books[0])
        L.append(f"-- {WIN_TXT[w]}, {a0} -> {z0}")
        rows = []
        for b in W.books:
            for run in ["hold_parent", "hold_Nifty100", "hold_MC100", "hold_SC100", "eq3_index_basket", "cmix_50-all", "50-all", "cmix_80-all", "80-all"]:
                x = W.get("headline", "full", PRIMARY, b, run)
                rows.append({"book": b, "run": run, "CAGR": pct(x["cagr"]), "max drawdown": pct(x["max_dd"]), "Calmar": f"{x['calmar']:.3f}", "vol": pct(x["vol"])})
        L.append(tab(pd.DataFrame(rows)))
        rows = []
        for b in W.books:
            for base in BASES:
                x, c = W.get("headline", "full", PRIMARY, b, f"{base}-all"), W.get("headline", "full", PRIMARY, b, f"cmix_{base}-all")
                rows.append({"book": b, "rule": f"{base}-all", "CAGR minus its constant mix (pp)": pp(x["cagr"] - c["cagr"]), "max DD minus its constant mix (pp)": pp(x["max_dd"] - c["max_dd"]), "Calmar diff": f"{x['calmar'] - c['calmar']:+.3f}"})
        L.append("   the rule against the constant mix at its own average shares (a different average exposure explains how much?):")
        L.append(tab(pd.DataFrame(rows)))
        L.append("   constant-mix parameters (mean of the weekly target shares) per book and rule (-all rules):")
        cm = W.cmix[W.cmix["rule"].isin(["50-all", "80-all"])].copy()
        for c in cm.columns[2:]:
            cm[c] = cm[c].map(lambda v: f"{v:.4f}")
        L.append(tab(cm))
        L.append("")
    return L


def r4_flip_text(s, cid, h, n) -> str:
    """the outcome-map sentence for one R4 flip (shared with report.py): h = the headline's verdict, n = the verdict with spell s left out."""
    return (f"leaving out spell {s} flips {cid} ({'PASS' if h else 'FAIL'} -> {'PASS' if n else 'FAIL'}): "
            + ("the result rests on that spell" if h else "the failure rests on that spell"))


def sec_robust(Ws: dict) -> tuple[list[str], dict]:
    L, flips, allc = [], [], {}
    for w, W in Ws.items():
        a0, z0, _ = W.dates(W.books[0])
        L.append(f"== {WIN_TXT[w]}, headline window {a0} -> {z0}")
        head = {base: compare(W, "headline", "full", PRIMARY, base) for base in BASES}

        def line(tag, cs):
            return f"   {tag}: " + "; ".join(f"{b}: " + " ".join(f"{c['id']} {'PASS' if c['pass'] else 'FAIL'} ({c['n_ok']}/{len(c['per'])})" for c in cs[b]) for b in BASES)
        for cost in (0.0, 50.0):
            cs = {base: compare(W, "headline", "full", cost, base) for base in BASES}
            L.append(line(f"R1 {cost} bps", cs))
            allc[(w, f"R1_{cost}")] = cs
        for tag, var, win in (("R2 LIQUIDCASE cash leg", "r2_liq", "full"), ("R3 own window", "r3", "r3"), ("R5 index leg minus 0.5 pp a year", "r5_drag", "full")):
            cs = {base: compare(W, var, win, PRIMARY, base) for base in BASES}
            sub = W.rob[(W.rob["variant"] == var) & (W.rob["book"] == W.books[0]) & (W.rob["run"] == "50-all") & (W.rob["cost_bps"] == PRIMARY)]
            L.append(line(f"{tag} ({var}; {int(sub['sessions'].iloc[0]) if len(sub) else 'n/a'} sessions)", cs))
            allc[(w, var)] = cs
        L.append("   CAGR differences (pp, all - comparator), per book, 20.8 bps:")
        rows = []
        for tag, var, win in (("headline", "headline", "full"), ("R2", "r2_liq", "full"), ("R3", "r3", "r3"), ("R5", "r5_drag", "full")):
            for base in BASES:
                for k in ("orig", "liq", "half", "idx"):
                    rows.append({"variant": tag, "base": base, "vs": k, **{b[-4:]: pp(float(W.get(var, win, PRIMARY, b, f"{base}-all")["cagr"]) - float(W.get(var, win, PRIMARY, b, f"{base}-{k}")["cagr"])) for b in W.books}})
        L.append(tab(pd.DataFrame(rows)))
        # R4
        spells = W.spell_ids()
        L.append(f"   R4 leave one spell out (`-all` holds 100% cash only on that spell's decisions, `-liq`'s target; the comparators are the headline's); {len(spells)} OUT-SELL spells; "
                 "the last spell is marked when it ends at the window end:")
        b0 = W.books[0]
        spell_rows = W.ledger[(W.ledger["book"] == b0) & (W.ledger["level"] == "spell") & (W.ledger["window"] == "full")].reset_index(drop=True)
        d0 = W.dec[W.dec["book"] == b0]
        rows = []
        for s in spells:
            var = f"r4_s{s}"
            sr = spell_rows.iloc[s - 1]
            k0w = int(((d0["regime"] == "OUT-SELL") & (d0["decision_date"] >= sr["first_decision"]) & (d0["decision_date"] <= sr["last_decision"]) & (d0["k"] == 0)).sum())
            for base in BASES:
                cs = compare(W, var, "full", PRIMARY, base, comp_get=lambda b, run: W.get("headline", "full", PRIMARY, b, run))
                changed = [c["id"] for c, h in zip(cs, head[base]) if c["pass"] != h["pass"]]
                for c, h in zip(cs, head[base]):
                    if c["pass"] != h["pass"]:
                        flips.append((w, base, s, c["id"], h["pass"], c["pass"]))
                rows.append({"spell": s, "first decision": sr["first_decision"], "last decision": sr["last_decision"], "weeks": int(sr["weeks"]), "k0 weeks": k0w, "entered from": sr["entered_from"],
                             "exited to": sr["exited_to"] + (" (open at the window end)" if sr["exited_to"] == "window end" else ""), "base": base,
                             **{c["id"]: f"{'PASS' if c['pass'] else 'FAIL'} {c['n_ok']}/{len(c['per'])}" for c in cs},
                             **{f"all CAGR {b[-4:]}": pct(float(W.get(var, 'full', PRIMARY, b, f'{base}-all')['cagr'])) for b in W.books}, "flips vs headline": ",".join(changed) or "-"})
        L.append(tab(pd.DataFrame(rows)))
        fl_w = [f for f in flips if f[0] == w]
        L.append("   R4 flips in this window: " + ("none" if not fl_w else "; ".join(f"{b}-all, leaving out spell {s} (first decision {spell_rows.iloc[s - 1]['first_decision']}, {int(spell_rows.iloc[s - 1]['weeks'])} weeks) flips {cid}: {'PASS' if h else 'FAIL'} -> {'PASS' if n else 'FAIL'}" for _w, b, s, cid, h, n in fl_w)))
        L.append("")
    diff = [(k, b, c["id"]) for k, cs in allc.items() for b in BASES for c, h in zip(cs[b], compare(Ws[k[0]], "headline", "full", PRIMARY, b)) if c["pass"] != h["pass"]]
    L.append("R1/R2/R3/R5 comparisons whose pass status differs from the headline's: " + ("none" if not diff else "; ".join(f"{k[0]} {k[1]} {b}-all {cid}" for k, b, cid in diff)))
    L.append("R4 flips (a passing comparison that fails, or a failing one that passes, when one spell is left out): " + ("none" if not flips else "; ".join(f"{w} {b}-all spell {s} {cid}: {'PASS' if h else 'FAIL'} -> {'PASS' if n else 'FAIL'}" for w, b, s, cid, h, n in flips)))
    return L, {"flips": flips, "all": allc}


def sec_outcome(Ws: dict, res: dict, rob: dict) -> list[str]:
    L = ["T16.md 2.5 applied mechanically to the headline (20.8 bps, whole window) per window and base (all V gates passed or nothing would be printed):"]
    for w, W in Ws.items():
        for base in BASES:
            c = {x["id"]: x for x in res[(w, base)]}
            ps = {k: v["pass"] for k, v in c.items()}
            if ps["C1"] and ps["C3"]:
                s = "C1 and C3 pass: holding the three indices with cash earned more than the original sleeve and more than cash alone on this window; PROVISIONAL (seen, post-hoc, no null)"
            elif ps["C3"] and not ps["C1"]:
                s = "C3 passes, C1 fails: the indices beat cash but giving up GOLDBEES cost more than they added"
            else:
                s = "C3 fails: holding the three indices did not beat cash in the regime on this window" + (" (C1 passes)" if ps["C1"] else "")
            s += "; C5 " + ("passes: ignoring the index signals in the regime earned more than following them (-idx) on this window; the ledger's k = 0 / k >= 1 split says where" if ps["C5"] else
                            "fails: ignoring the index signals in the regime did not earn more than following them (-idx) on this window; the ledger's k = 0 / k >= 1 split says where")
            s += "; C6 " + ("passes: ignoring the signals did not deepen the worst fall against -idx" if ps["C6"] else "fails: ignoring the signals deepened the worst fall against -idx")
            s += f"; C4 {'passes: -all did better than T14 half-parent + GOLDBEES' if ps['C4'] else 'fails: -all did not do better than T14 half-parent + GOLDBEES'}; C2 {'passes' if ps['C2'] else 'fails'}"
            fl = [f for f in rob["flips"] if f[0] == w and f[1] == base]
            s += "; R4: " + ("no comparison flips when one spell is left out" if not fl else "; ".join(r4_flip_text(x[2], x[3], x[4], x[5]) for x in fl))
            r3 = rob["all"][(w, "r3")][base]
            agree = [x["pass"] for x in r3] == [x["pass"] for x in res[(w, base)]]
            s += "; R3 (live): " + ("agrees with the whole window" if agree else "DISAGREES with the whole window: say so in the verdict and status note")
            L.append(f"   {w} {base}-all: {s}")
    ag = []
    for base in BASES:
        a, b = [tuple(c["pass"] for c in res[(w, base)]) for w in Ws]
        ag.append(f"{base}-all: the two windows {'agree' if a == b else 'DISAGREE'} on C1-C6 ({a} vs {b})")
    L.append("   " + "; ".join(ag) + ". If they disagree: report both; no general statement; the 2019-2026 window is the one the live product traded.")
    L.append("   a V gate fails: no (the gate block above lists V1-V5 and every derived check as PASS).")
    return L


def build(Ws: dict, need_v1: bool):
    """Returns (log text, gates_ok)."""
    glines, ok = sec_gates(Ws, need_v1)
    head = ["T16 analysis (generated by tests/T16/analyse.py from the shipped evidence; nothing typed). " + ", ".join(f"{WIN_TXT[w]} {W.dates(W.books[0])[0]} -> {W.dates(W.books[0])[1]}" for w, W in Ws.items()),
            f"Books: {', '.join(next(iter(Ws.values())).books)}. Costs {', '.join(map(str, COSTS))} bps round trip (primary {PRIMARY}). No null, no chance claim (waiver).", ""]
    if not ok:
        return "\n".join(head + ["GATE FAILURE: nothing about results is printed.", *glines]), False
    out = list(head)
    blocks = {}
    blocks["4.0"] = sec_rules(Ws)
    blocks["4.0a"] = sec_worked(Ws)
    blocks["4.0b"] = glines + [""] + sec_counts(Ws)
    h, res = sec_headline(Ws)
    blocks["4.1"] = h
    blocks["4.2"] = sec_dtable(Ws)
    blocks["4.3"] = sec_ledger(Ws)
    r, rob = sec_robust(Ws)
    blocks["4.4"] = r
    blocks["4.5"] = sec_outcome(Ws, res, rob)
    for k, v in blocks.items():
        out += ["=" * 100, TITLES[k], "=" * 100, *v, ""]
    return "\n".join(out), True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="headline")
    ap.add_argument("--evidence", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--books", nargs="+", default=None)
    ap.add_argument("--require-v1", action="store_true")
    a = ap.parse_args()
    evdir = Path(a.evidence) if a.evidence else HERE / "evidence" / a.run
    out_dir = Path(a.out) if a.out else (evdir if a.evidence else HERE / "evidence")
    need_v1 = bool(a.require_v1 or (not a.evidence and evdir.name == "headline"))
    missing = [w for w in ("w1", "w2") if not (evdir / w / "audit.json").exists()]
    if missing:
        print(f"analyse.py: no evidence for {', '.join(missing)} under {evdir} (run the engine first: python analysis/t16_engine.py --window both --run {a.run}); nothing printed; exit 1")
        return 1
    Ws = {w: Win(evdir, w, a.books) for w in ("w1", "w2")}
    text, ok = build(Ws, need_v1)
    print(text)
    if not ok:
        print("analyse.py: a validity gate failed (see FAIL above); no result printed, analysis.log not written; exit 1")
        return 1
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "analysis.log").write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
