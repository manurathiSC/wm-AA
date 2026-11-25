"""T15 analysis: reads ONLY the shipped evidence in evidence/<run>/{w1,w2}/ and prints section 4 of the write-up.

    python tests/T15/analyse.py [--run headline]              prints to stdout and writes tests/T15/evidence/analysis.log
    python tests/T15/analyse.py --evidence DIR [--out DIR]    DIR holds w1/ and w2/ (e.g. a smoke run); analysis.log then goes to --out (default DIR), never to tests/T15
    options: --books SCMO_0003   restrict to some books (for evidence that holds fewer than the four; the 3-of-4 verdicts then mean nothing)
             --require-v1        fail if verify_t15.json is missing in a window folder (default: required only when the evidence directory is called 'headline')

Exit code 1 if ANY validity gate failed (the engine's audit.json gates and pass flags, regression.json, the verifier's verify_t15.json, and the checks derived here from the evidence),
or if nothing was compared. If a gate failed nothing about results is printed (only the gate block) and analysis.log is not written.

T15 has NO null and no chance claim (Manu's waiver, 2026-11-25): there are no percentiles or p-values here. A pass of C1-C4 (T15.md 2.3) is a count of books (>= 3 of 4) in which the stated
difference has the stated sign, a description of seen weeks. Imports nothing from the engine. No performance figure is typed in this file: every number comes from the evidence.

The module is also imported by report.py (class Win and the compute_* functions) so that the page and the log use one set of numbers; check_page.py shares no code with it.
"""
from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
AA = HERE.parents[1]
PRIMARY = 20.8
COSTS = (0.0, PRIMARY, 50.0)
PASS_BOOKS = 3
TIE = 1e-12      # two statistics within this are the same number up to float noise (reported; the frozen rule is unrounded)
BOOKS = ["SCMO_0003", "SCMO_0007", "SCMO_0010", "SCMO_0029"]
RULES = ["50-orig", "50-half", "50-liq", "50-idx", "80-orig", "80-half", "80-liq", "80-idx"]
BASES = ["50", "80"]
INDICES = ("Nifty100", "MC100", "SC100")
WIN_TXT = {"w1": "W1 (T11's / T14's inputs)", "w2": "W2 (T08's / T14's inputs)"}
COMPS = [("C1", "cagr", "orig", "earns more than the original rule (CAGR higher)"),
         ("C2", "max_dd", "orig", "worst fall no deeper than the original's (max drawdown shallower or equal)"),
         ("C3", "cagr", "liq", "holding the BUY indices adds to holding only cash (CAGR higher than -liq)"),
         ("C4", "cagr", "half", "does better than half parent + half GOLDBEES (CAGR higher than -half)")]
CAPTION_W1 = "rebuilt from the parent's baskets and Eikon prices, not validated against a published NAV before 2019-01-02"
TITLES = {"4.0a": "4.0a The worked example: a regime entry with k = 2, a change of the BUY set, an exit, one decision, the series",
          "4.0b": "4.0b Gates, regime counts and reportability", "4.1": "4.1 Headline: the sixteen comparisons C1-C4 and the verdict table",
          "4.2": "4.2 The descriptive headline: the D-table, trades and cost, weeks and sessions in each regime",
          "4.3": "4.3 The regime ledger and the comparators", "4.4": "4.4 Robustness R1-R5", "4.5": "4.5 Outcome map (T15.md 2.5), applied mechanically"}


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
        self.verify = json.loads((d / "verify_t15.json").read_text(encoding="utf-8")) if (d / "verify_t15.json").exists() else None
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
        n = self.nav[(self.nav["book"] == book) & (self.nav["run"] == "50-idx") & (self.nav["cost_bps"] == PRIMARY)]
        return n["date"].iloc[0].date(), n["date"].iloc[-1].date(), int(len(n))


# ── the comparisons ───────────────────────────────────────────────────────────
def compare(W: Win, variant, window, cost, base, idx_get=None, comp_get=None) -> list[dict]:
    """C1-C4 for one base: per book the -idx value, the comparator value, the difference and whether it passes; the count and the verdict."""
    ig = idx_get or (lambda b, run: W.get(variant, window, cost, b, run))
    cg = comp_get or (lambda b, run: W.get(variant, window, cost, b, run))
    out = []
    for cid, stat, kind, desc in COMPS:
        per = []
        for b in W.books:
            a, c = float(ig(b, f"{base}-idx")[stat]), float(cg(b, f"{base}-{kind}")[stat])
            ok = (a > c) if cid != "C2" else (a >= c)          # the frozen rule: unrounded
            ok_tol = (a > c + TIE) if cid != "C2" else (a >= c - TIE)
            per.append({"book": b, "idx": a, "comp": c, "diff": a - c, "ok": bool(ok), "tie": bool(abs(a - c) <= TIE), "ok_tol": bool(ok_tol)})
        n = sum(p["ok"] for p in per)
        n_tol = sum(p["ok_tol"] for p in per)
        out.append({"id": cid, "stat": stat, "kind": kind, "desc": desc, "per": per, "n_ok": n, "pass": bool(n >= PASS_BOOKS), "n_ties": sum(p["tie"] for p in per), "pass_tol": bool(n_tol >= PASS_BOOKS)})
    return out


def comp_line(c: dict) -> str:
    cells = "  ".join(f"{p['book'][-4:]} {pp(p['diff'])}{'*' if p['ok'] else ' '}" for p in c["per"])
    return f"{c['id']}  vs {c['kind']:<4} {c['stat']:<6} diff pp (idx - comparator; * = counts toward pass): {cells}   -> {c['n_ok']} of {len(c['per'])}  {'PASS' if c['pass'] else 'FAIL'}"


# ── gates ─────────────────────────────────────────────────────────────────────
def gate_rows(W: Win, need_v1: bool) -> list[tuple[str, bool, str]]:
    a, r = W.audit, W.reg
    g = a["gates"]
    rows = [("engine gates (audit.json)", bool(g["all"]), " ".join(f"{k} {v}" for k, v in g.items())),
            ("V2 point in time", bool(a["v2"]["pass"]), f"{a['v2']['checks']} checks, {a['v2']['violations']} violations"),
            ("V3 index tie (Master Index = D25/D25c close)", bool(a["v3"]["pass"]), f"{a['v3']['labels_checked']} labels, {a['v3']['violations']} violations, worst rel {a['v3']['worst_rel_diff']:.1e}"),
            ("V4(a) six T14 rules reproduce T14", bool(r["a_nav_regression"]["pass"]),
             f"nav rows {r['a_nav_regression']['rows_compared']} (worst {r['a_nav_regression']['worst_rel_diff']:.1e}), trade rows {r['a_nav_regression']['trade_rows_compared']} (worst {r['a_nav_regression']['worst_trade_rel_diff']:.1e})"),
            ("V4(b) -idx on cash equals -liq", all(v["pass"] for v in r["b_index_priced_as_cash"].values()), f"worst {max(v['max_rel_diff'] for v in r['b_index_priced_as_cash'].values()):.1e}"),
            ("V4(c) -idx equals -liq before the first index trade", all(v["pass"] for v in r["c_idx_equals_liq_before_first_index_trade"].values()),
             f"worst {max(v['max_rel_diff'] for v in r['c_idx_equals_liq_before_first_index_trade'].values()):.1e}"),
            ("V4(d) shared code", bool(r["d_shared_code"]["pass"]), f"changed: {', '.join(r['d_shared_code']['changed_functions'])}"),
            ("V4(e) signals and B equal the Master / weekly files", all(v["pass"] for v in r["e_signals"].values()), f"{sum(v['decisions'] for v in r['e_signals'].values())} decisions"),
            ("V4(f) one-instrument identity, G0 / seam", all(v["pass"] for v in r["f_one_instrument"].values()) and all(v["pass"] for v in (r.get("f_g0") or r.get("f_seam_2019") or {}).values()), ""),
            ("V5 trade and cost identities", bool(a["v5"]["pass"]), f"{a['v5']['trades_checked']} trades, {a['v5']['idx_trades_into_or_inside_OUT_SELL_checked']} -idx trades into or inside OUT-SELL, worst {max(a['v5']['worst'].values()):.1e}"),
            ("step 1 counts reproduced", bool(a["step1_counts_reproduced"]["pass"]), f"{len(a['step1_counts_reproduced']['detail'])} book-windows"),
            ("prereg sha256 in audit equals T15.md header", False, "")]
    t15 = (HERE / "T15.md").read_text(encoding="utf-8")
    hdr = t15.split("§1–§3 sha256:** `")[1].split("`")[0]
    rows[-1] = ("prereg sha256 in audit equals T15.md header", a["prereg_sha256"] == hdr, hdr[:16])
    # evidence self-consistency: stats end NAV equals the daily NAV's last value
    bad = 0
    for b in W.books:
        for run in RULES:
            for cost in COSTS:
                n = W.nav[(W.nav["book"] == b) & (W.nav["run"] == run) & (W.nav["cost_bps"] == cost)]["nav"].values
                s = float(W.get("headline", "full", cost, b, run)["end_nav"])
                bad += abs(n[-1] / s - 1) > 1e-12
    rows.append(("stats.csv end NAV equals daily_nav.csv", bad == 0, f"{len(W.books) * len(RULES) * len(COSTS)} runs, {bad} differ"))
    if W.verify is None:
        rows.append(("V1 independent verifier", not need_v1, "verify_t15.json missing" + (" (required)" if need_v1 else " (not required for this evidence)")))
    else:
        v = W.verify
        st = v.get("selftest")
        good = bool(v.get("exit_ok") and v.get("gate_compared", 0) > 0 and v.get("gate_failures_and_missing", 1) == 0 and (st is None or st.get("detected")))
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


def sec_counts(Ws: dict) -> list[str]:
    L = []
    for w, W in Ws.items():
        L.append(f"-- {WIN_TXT[w]}: regime counts from the engine's own series (equal to logs/step_1_spell_counts.json)")
        rows = []
        for b in W.books:
            x = W.audit["books"][b]
            first, last, n = W.dates(b)
            rows.append({"book": b, "start": first, "end": last, "sessions": n, "decisions": x["weeks"], "IN": x["weeks_IN"], "OUT-BUY": x["weeks_OUT_BUY"], "OUT-SELL": x["weeks_OUT_SELL"],
                         "OS spells": len(x["OUT_SELL_lengths"]), "k0": x["k0"], "k1": x["k1"], "k2": x["k2"], "index weeks": x["index_weeks"], "index spells": x["index_spells"], "B changes": x["B_changes"]})
        L.append(tab(pd.DataFrame(rows)))
        b0 = W.books[0]
        L.append(f"   trades from regime, gold and B changes per rule ({b0}): " + ", ".join(f"{r} {W.audit['books'][b0]['trades_due_per_rule'][r]}" for r in RULES))
        L.append(f"   OUT-SELL spells and their B sequences ({b0}; B x weeks):")
        for sp, seq in zip(W.audit["books"][b0]["OUT_SELL_lengths"], W.audit["books"][b0]["B_sequences"]):
            L.append(f"     {sp:>2} weeks: " + ", ".join(f"{n} {k}" for n, k in seq))
        L.append("   sessions held in each state (the decision's target is held from the session after the decision): " +
                 "; ".join(f"{b}: " + ", ".join(f"{k} {v}" for k, v in W.audit["books"][b]["sessions_by_state"].items()) for b in W.books[:1]))
        ns = W.audit["books"][b0]["index_sessions_without_a_bar"]
        L.append("   calendar sessions without an index bar (last close carried; decision sessions only): " + ", ".join(f"{n}: {v}" for n, v in ns.items()))
        L.append("")
    return L


def sec_worked(Ws: dict) -> list[str]:
    L = []
    for w, W in Ws.items():
        b0 = W.books[0]
        a = W.audit["v5"]["worked_examples"]
        L.append(f"-- {WIN_TXT[w]}, book {b0}, 20.8 bps, rule `50-idx`: three real trades (values at the fill prices; shares of the value after cost)")
        if w == "w1":
            L.append(f"   (W1's parent is {CAPTION_W1})")
        for key in ("50-idx|regime_in", "50-idx|regime_in_k1", "50-idx|index_set_change", "50-idx|regime_out"):
            x = a.get(key)
            if not x:
                continue
            V = x["V_after"]
            L.append(f"   {key}: decided {x['decision_date']} (regime {x['regime']}, B = {x['B']}, k = {x['k']}), traded {x['trade_date']} (session idx {x['idx']}); V = {x['V']:.6f}, traded {x['traded']:.6f}, cost {x['cost']:.8f}")
            L.append(f"      before: stocks {x['stock_before']:.6f}  GOLDBEES {x['gold_before']:.6f}  cash {x['cash_before']:.6f}  " + "  ".join(f"{n} {x[n + '_before']:.6f}" for n in INDICES))
            L.append(f"      after : stocks {x['stock_after']:.6f}  GOLDBEES {x['gold_after']:.6f}  cash {x['cash_after']:.6f}  " + "  ".join(f"{n} {x[n + '_after']:.6f}" for n in INDICES) + f"   (V after {V:.6f})")
            L.append("      shares after cost: " + "  ".join(f"{n} {x[n + '_after'] / V:.6f}" for n in INDICES) + f"  cash {x['cash_after'] / V:.6f}")
            L.append("      index fill prices (OHLC4): " + "  ".join(f"{n} {x['index_fill_prices'][n]:.2f}" for n in INDICES))
        d = W.dec[(W.dec["book"] == b0) & (W.dec["k"] == 2) & (W.dec["regime"] == "OUT-SELL")].head(1)
        if len(d):
            r = d.iloc[0]
            L.append(f"   one decision row (first k = 2 OUT-SELL week): j {int(r['j'])}, decided {r['decision_date']}, signs N100 {r['sign_Nifty100']}, MC100 {r['sign_MC100']}, SC100 {r['sign_SC100']}, MAUc1 {r['sign_MAUc1']}; "
                     f"regime {r['regime']}, B = {r['B']}, k = {int(r['k'])}; target of 50-idx: parent {r['e_50-idx']:.4f}, GOLDBEES {r['gold_50-idx']:.4f}, cash {r['cash_50-idx']:.4f}, "
                     f"N100 {r['w_Nifty100_50-idx']:.4f}, MC100 {r['w_MC100_50-idx']:.4f}, SC100 {r['w_SC100_50-idx']:.4f}; traded {r['trade_date']}")
        first, last, n = W.dates(b0)
        navs = W.nav[(W.nav["book"] == b0) & (W.nav["cost_bps"] == PRIMARY)]
        L.append(f"   the path: {n} sessions {first} -> {last}; 50-idx NAV {float(navs[navs['run'] == '50-idx']['nav'].iloc[0]):.6f} -> {float(navs[navs['run'] == '50-idx']['nav'].iloc[-1]):.6f}; "
                 f"index closes first -> last are in the engine's index files (inputs.csv lists them: " + ", ".join(Path(f).name for f in W.inputs['file'] if 'daily_ohlcv' in f) + ")")
        L.append("")
    return L


def sec_headline(Ws: dict) -> tuple[list[str], dict]:
    L, res = [], {}
    L.append("Pass mark per comparison: the stated difference has the stated sign in at least 3 of the 4 books (T15.md 2.3). A description of seen weeks; no null, no percentile, no p-value, no claim about chance.")
    L.append("The four books share one market; in OUT-SELL weeks `-idx` holds the same indices and cash in every book, so '3 of 4' is weaker here than in earlier tests.")
    L.append("")
    for w, W in Ws.items():
        L.append(f"== {WIN_TXT[w]}, after {PRIMARY} bps, whole window {W.dates(W.books[0])[0]} -> {W.dates(W.books[0])[1]}")
        for base in BASES:
            cs = compare(W, "headline", "full", PRIMARY, base)
            res[(w, base)] = cs
            L.append(f"   {base}/{100 - int(base)} base (`{base}-idx` against `{base}-orig`, `{base}-liq`, `{base}-half`):")
            for c in cs:
                L.append("     " + comp_line(c))
        L.append("")
    L.append("Verdict table (16 comparisons): " + "; ".join(f"{w} {b}: " + " ".join(f"{c['id']} {'PASS' if c['pass'] else 'FAIL'}" for c in res[(w, b)]) for (w, b) in res))
    ties = [(w, b, c["id"], p["book"], p["diff"]) for (w, b), cs in res.items() for c in cs for p in c["per"] if p["tie"]]
    flips_tol = [(w, b, c["id"]) for (w, b), cs in res.items() for c in cs if c["pass"] != c["pass_tol"]]
    L.append("Ties (|difference| <= 1e-12, the same number up to float noise; the frozen rule compares the unrounded values): " + ("none" if not ties else "; ".join(f"{w} {b}-idx {cid} {bk} (diff {d:+.2e})" for w, b, cid, bk, d in ties)) +
             f". Verdicts that would change if ties were counted as equal: {'none' if not flips_tol else flips_tol}.")
    npass = sum(c["pass"] for cs in res.values() for c in cs)
    L.append(f"{npass} of 16 comparisons pass. Choosing the best of the eight rules from these tables is a selection on seen data. Findings are PROVISIONAL at most.")
    return L, res


def sec_dtable(Ws: dict) -> list[str]:
    L = []
    for w, W in Ws.items():
        L.append(f"== {WIN_TXT[w]}" + (f" (W1's parent is {CAPTION_W1})" if w == "w1" else ""))
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
                for k in ("orig", "liq", "half"):
                    a, c = W.get("headline", "full", PRIMARY, b, f"{base}-idx"), W.get("headline", "full", PRIMARY, b, f"{base}-{k}")
                    L.append(f"   {base}-idx minus {base}-{k}: CAGR {pp(a['cagr'] - c['cagr'])} pp, max drawdown {pp(a['max_dd'] - c['max_dd'])} pp, Calmar {a['calmar'] - c['calmar']:+.3f}, vol {pp(a['vol'] - c['vol'])} pp, "
                             f"trades {int(a['trades'] - c['trades']):+d}, cost paid {a['cost_paid'] - c['cost_paid']:+.5f}")
            L.append("")
    return L


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
        L.append(f"-- instruments over each span (identical in every book) and the parent per book (hold-the-parent, 0 cost)")
        t["parent " + b0[-4:]] = inst["parent_return"].map(pct).values
        for b in W.books[1:]:
            t["parent " + b[-4:]] = lg[(lg["book"] == b) & (lg["window"] == "full")]["parent_return"].map(pct).values
        L.append(tab(t))
        for b in W.books:
            x = lg[(lg["book"] == b) & (lg["window"] == "full")]
            r = x[["level", "spell_no", "stretch_no", "B", "weeks"]].copy()
            for rule in RULES:
                r[rule] = x[f"ret_{rule}"].map(pct).values
            L.append(f"-- {b}: each rule's return over each span (20.8 bps)")
            L.append(tab(r))
        L.append("")
    L.append("== Comparators (benchmarks, not nulls), 20.8 bps")
    for w, W in Ws.items():
        L.append(f"-- {WIN_TXT[w]}")
        rows = []
        for b in W.books:
            for run in ["hold_parent", "hold_Nifty100", "hold_MC100", "hold_SC100", "cmix_50-idx", "cmix_80-idx", "50-idx", "80-idx"]:
                x = W.get("headline", "full", PRIMARY, b, run)
                rows.append({"book": b, "run": run, "CAGR": pct(x["cagr"]), "max drawdown": pct(x["max_dd"]), "Calmar": f"{x['calmar']:.3f}", "vol": pct(x["vol"])})
        L.append(tab(pd.DataFrame(rows)))
        L.append("   constant-mix parameters (mean of the weekly target shares) per book and rule:")
        cm = W.cmix[W.cmix["rule"].isin(["50-idx", "80-idx"])].copy()
        for c in cm.columns[2:]:
            cm[c] = cm[c].map(lambda v: f"{v:.4f}")
        L.append(tab(cm))
        L.append("")
    return L


def sec_robust(Ws: dict) -> tuple[list[str], dict]:
    L, flips, allc = [], [], {}
    for w, W in Ws.items():
        L.append(f"== {WIN_TXT[w]}")
        head = {base: compare(W, "headline", "full", PRIMARY, base) for base in BASES}

        def line(tag, cs):
            return f"   {tag}: " + "; ".join(f"{b}: " + " ".join(f"{c['id']} {'PASS' if c['pass'] else 'FAIL'} ({c['n_ok']}/{len(c['per'])})" for c in cs[b]) for b in BASES)
        # R1
        for cost in (0.0, 50.0):
            cs = {base: compare(W, "headline", "full", cost, base) for base in BASES}
            L.append(line(f"R1 {cost} bps", cs))
            allc[(w, f"R1_{cost}")] = cs
        # R2, R3, R5 (all eight rules run in the variant)
        for tag, var, win in (("R2 LIQUIDCASE cash leg", "r2_liq", "full"), ("R3 own window", "r3", "r3"), ("R5 index leg minus 0.5 pp a year", "r5_drag", "full")):
            cs = {base: compare(W, var, win, PRIMARY, base) for base in BASES}
            first = W.rob[(W.rob["variant"] == var)]["sessions"].min() if (W.rob["variant"] == var).any() else None
            L.append(line(f"{tag} ({var})", cs))
            allc[(w, var)] = cs
        # the differences in pp per variant, per book (the -idx minus comparator CAGR), for reading size
        L.append("   CAGR differences (pp, idx - comparator), per book, 20.8 bps:")
        rows = []
        for tag, var, win in (("headline", "headline", "full"), ("R2", "r2_liq", "full"), ("R3", "r3", "r3"), ("R5", "r5_drag", "full")):
            for base in BASES:
                for k in ("orig", "liq", "half"):
                    rows.append({"variant": tag, "base": base, "vs": k, **{b[-4:]: pp(float(W.get(var, win, PRIMARY, b, f"{base}-idx")["cagr"]) - float(W.get(var, win, PRIMARY, b, f"{base}-{k}")["cagr"])) for b in W.books}})
        L.append(tab(pd.DataFrame(rows)))
        # R4
        spells = sorted({int(v.split("_s")[1]) for v in W.rob["variant"].unique() if v.startswith("r4_s")})
        L.append(f"   R4 leave one spell out (`-idx` holds cash only on that spell's decisions; the comparators are the headline's); {len(spells)} OUT-SELL spells:")
        b0 = W.books[0]
        spell_rows = W.ledger[(W.ledger["book"] == b0) & (W.ledger["level"] == "spell") & (W.ledger["window"] == "full")].reset_index(drop=True)
        rows = []
        for s in spells:
            var = f"r4_s{s}"
            sr = spell_rows.iloc[s - 1]
            for base in BASES:
                cs = compare(W, var, "full", PRIMARY, base, comp_get=lambda b, run: W.get("headline", "full", PRIMARY, b, run))
                changed = [c["id"] for c, h in zip(cs, head[base]) if c["pass"] != h["pass"]]
                for c, h in zip(cs, head[base]):
                    if c["pass"] != h["pass"]:
                        flips.append((w, base, s, c["id"], h["pass"], c["pass"]))
                rows.append({"spell": s, "first decision": sr["first_decision"], "weeks": int(sr["weeks"]), "index weeks": int(W.dec[(W.dec["book"] == b0)].pipe(
                    lambda d: ((d["regime"] == "OUT-SELL") & (d["decision_date"] >= sr["first_decision"]) & (d["decision_date"] <= sr["last_decision"]) & (d["k"] > 0)).sum())), "base": base,
                    **{c["id"]: f"{'PASS' if c['pass'] else 'FAIL'} {c['n_ok']}/{len(c['per'])}" for c in cs},
                    **{f"idx CAGR {b[-4:]}": pct(float(W.get(var, 'full', PRIMARY, b, f'{base}-idx')['cagr'])) for b in W.books}, "flips vs headline": ",".join(changed) or "-"})
        L.append(tab(pd.DataFrame(rows)))
        L.append("")
    L.append("R4/R1/R2/R3/R5 comparisons whose pass status differs from the headline's: " + ("none" if not [1 for k, cs in allc.items() for b in BASES for c, h in zip(cs[b], compare(Ws[k[0]], 'headline', 'full', PRIMARY, b)) if c['pass'] != h['pass']] and not flips else
             "see the PASS / FAIL pairs above; R4 flips: " + (", ".join(f"{w} {b}-idx spell {s} {cid}: {'PASS' if h else 'FAIL'} -> {'PASS' if n else 'FAIL'}" for w, b, s, cid, h, n in flips) or "none")))
    return L, {"flips": flips, "all": allc}


def sec_outcome(Ws: dict, res: dict, rob: dict) -> list[str]:
    L = ["T15.md 2.5 applied mechanically to the headline (20.8 bps, whole window) per window and base:"]
    for w, W in Ws.items():
        for base in BASES:
            c = {x["id"]: x for x in res[(w, base)]}
            c1, c2, c3, c4 = c["C1"]["pass"], c["C2"]["pass"], c["C3"]["pass"], c["C4"]["pass"]
            if c1 and c3:
                s = "C1 and C3 pass: holding the BUY indices with cash earned more than the original sleeve and more than cash alone on this window; PROVISIONAL (seen, post-hoc, no null)"
            elif c3 and not c1:
                s = "C3 passes, C1 fails: the indices beat cash but giving up GOLDBEES cost more than they added"
            elif not c3:
                s = "C3 fails: holding the BUY indices did not beat cash in the regime on this window" + (" (C1 passes)" if c1 else "")
            else:
                s = "mixed"
            s += f"; C4 {'passes: -idx did better than T14 half-parent + GOLDBEES' if c4 else 'fails: -idx did not do better than T14 half-parent + GOLDBEES'}; C2 {'passes' if c2 else 'fails'}"
            fl = [f for f in rob["flips"] if f[0] == w and f[1] == base]
            s += "; R4: " + ("no comparison flips when one spell is left out" if not fl else "; ".join(f"leaving out spell {x[2]} flips {x[3]} ({'PASS' if x[4] else 'FAIL'} -> {'PASS' if x[5] else 'FAIL'}): the result rests on that spell" for x in fl))
            L.append(f"   {w} {base}-idx: {s}")
    ag = []
    for base in BASES:
        a, b = [tuple(c["pass"] for c in res[(w, base)]) for w in Ws]
        ag.append(f"{base}-idx: the two windows {'agree' if a == b else 'DISAGREE'} on C1-C4 ({a} vs {b})")
    L.append("   " + "; ".join(ag) + ". If they disagree: report both; no general statement; the 2019-2026 window is the one the live product traded.")
    live = []
    for w, W in Ws.items():
        for base in BASES:
            cs = rob["all"][(w, "r3")][base]
            hs = res[(w, base)]
            live.append(f"{w} {base}: R3 " + " ".join(f"{c['id']} {'PASS' if c['pass'] else 'FAIL'}" for c in cs) + (" (agrees with the whole window)" if [c["pass"] for c in cs] == [c["pass"] for c in hs] else " (DISAGREES with the whole window: say so in the verdict)"))
    L.append("   " + "; ".join(live))
    return L


def build(Ws: dict, need_v1: bool):
    """Returns (log text, gates_ok)."""
    glines, ok = sec_gates(Ws, need_v1)
    head = ["T15 analysis (generated by tests/T15/analyse.py from the shipped evidence; nothing typed). " + ", ".join(f"{WIN_TXT[w]} {W.dates(W.books[0])[0]} -> {W.dates(W.books[0])[1]}" for w, W in Ws.items()),
            f"Books: {', '.join(next(iter(Ws.values())).books)}. Costs {', '.join(map(str, COSTS))} bps round trip (primary {PRIMARY}). No null, no chance claim (waiver).", ""]
    if not ok:
        return "\n".join(head + ["GATE FAILURE: nothing about results is printed.", *glines]), False
    out = list(head)
    blocks = {}
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
    Ws = {w: Win(evdir, w, a.books) for w in ("w1", "w2")}
    text, ok = build(Ws, need_v1)
    print(text)
    if not ok:
        return 1
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "analysis.log").write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
