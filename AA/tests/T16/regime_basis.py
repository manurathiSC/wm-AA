"""T16 ad-hoc analysis (Manu, chat 2026-11-26: "give analysis regime basis, what data discovers"): every instrument and every rule broken down by the regime held.

    python tests/T16/regime_basis.py [--run headline]      (from AA/)  ->  tests/T16/evidence/regime_basis.csv, regime_basis_spans.csv, regime_basis.md

DESCRIPTIVE ONLY, post-hoc, after the headline results were read; not part of the frozen design (T16.md sections 1-3); no null, no chance claim.
Reads the headline evidence (`daily_nav.csv`: the rules at 20.8 bps, hold_parent at 0 bps, the price indices) and, for GOLDBEES and cash (which the evidence holds only per ledger span), the
engine's own `Book` arrays built from the same approved files (`analysis/t16_engine.py`, imported for its data loading only; no simulation is re-run).

Attribution (the ledger's convention, evidence_contract.md E13): decision j governs the span from the close of the session on which it is traded (idx_j + 1; T0 for j = 0) to the close of the
session on which decision j+1 is traded (the last session for the last decision). The spans tile the window; a daily return on session s belongs to the decision whose span (a_j, a_j+1] holds s.
The regime of a span is its decision's: IN, OUT-BUY, OUT-SELL with k = 0 (every index on SELL) or k >= 1. Per regime and series: sessions, compounded growth G = prod(1 + r_s), annualised
G^(252 / sessions) - 1, log contribution sum(ln(1 + r_s)) (the regime's share of the whole window's log growth), spans (weeks) and the share of spans with a positive return.
"""
import argparse
import math
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
AA = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(AA / "analysis"))
import t16_engine as EN  # noqa: E402  (data loading only)

HERE = Path(__file__).resolve().parent
BOOKS = EN.PARENTS
RULES = EN.RULES
INDICES = EN.INDICES
REGS = ["IN", "OUT-BUY", "OUT-SELL k=0", "OUT-SELL k>=1"]
WIN_TXT = {"w1": "W1 2014-09-01 -> 2019-01-02 (rebuilt parents)", "w2": "W2 2019-01-02 -> 2026-11-20 (published-NAV calendar)"}


def spans(dec: pd.DataFrame, T: int):
    idx = dec["decision_idx"].to_numpy()
    a = [0] + [min(int(i) + 1, T - 1) for i in idx[1:]]
    out = []
    for j in range(len(idx)):
        lo, hi = a[j], (a[j + 1] if j + 1 < len(idx) else T - 1)
        r = dec["regime"].iloc[j]
        lab = r if r != "OUT-SELL" else ("OUT-SELL k=0" if int(dec["k"].iloc[j]) == 0 else "OUT-SELL k>=1")
        out.append((j, lo, hi, lab, str(dec["decision_date"].iloc[j])))
    return out


def per_regime(level: np.ndarray, sp) -> dict:
    lr = np.diff(np.log(level))                     # lr[s-1] = ln(level_s / level_{s-1})
    res = {}
    for reg in REGS:
        ss = [(lo, hi) for _, lo, hi, lab, _ in sp if lab == reg and hi > lo]
        n = sum(hi - lo for lo, hi in ss)
        L = float(sum(lr[lo:hi].sum() for lo, hi in ss))
        span_r = [math.exp(lr[lo:hi].sum()) - 1 for lo, hi in ss]
        res[reg] = {"sessions": n, "spans": len(ss), "log": L, "growth": math.exp(L) - 1,
                    "ann": (math.exp(L * 252 / n) - 1) if n else float("nan"), "up_spans": (float(np.mean([x > 0 for x in span_r])) if ss else float("nan"))}
    res["ALL"] = {"sessions": len(lr), "log": float(lr.sum()), "growth": float(level[-1] / level[0] - 1), "ann": math.exp(lr.sum() * 252 / len(lr)) - 1}
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="headline")
    a = ap.parse_args()
    ev = HERE / "evidence" / a.run
    rows, span_rows = [], []
    for w in ("w1", "w2"):
        nav = pd.read_csv(ev / w / "daily_nav.csv")
        for b in BOOKS:
            bk = EN.Book(b, w)
            dec = bk.decisions()
            sp = spans(dec, bk.T)
            nb = nav[nav["book"] == b]

            def series(run, cost):
                s = nb[(nb["run"] == run) & (nb["cost_bps"] == cost)].sort_values("date")
                assert len(s) == bk.T and list(pd.to_datetime(s["date"])) == list(bk.cal), (w, b, run)
                return s["nav"].to_numpy()
            ser = {"parent": series("hold_parent", 0.0), "GOLDBEES": bk.g, "cash": bk.L, **{n: bk.I[:, q] for q, n in enumerate(INDICES)},
                   "eq3_index_basket": series("eq3_index_basket", 20.8), **{r: series(r, 20.8) for r in RULES}}
            for name, lv in ser.items():
                res = per_regime(np.asarray(lv, dtype=float), sp)
                for reg, v in res.items():
                    rows.append({"window": w, "book": b, "series": name, "regime": reg, **v})
            if b == BOOKS[0]:
                for j, lo, hi, lab, dd in sp:
                    span_rows.append({"window": w, "decision_date": dd, "regime": lab, "a_session": str(bk.cal[lo].date()), "b_session": str(bk.cal[hi].date()),
                                      **{f"ret_{n}": float(ser[n][hi] / ser[n][lo] - 1) for n in ("GOLDBEES", "cash") + tuple(INDICES)}})
    df = pd.DataFrame(rows)
    df.to_csv(ev.parent / "regime_basis.csv", index=False)
    pd.DataFrame(span_rows).to_csv(ev.parent / "regime_basis_spans.csv", index=False)

    md = ["# T16: results by regime (ad hoc, descriptive, post-hoc)", "",
          "Generated by `python tests/T16/regime_basis.py` from `evidence/headline/` (nothing typed). **Not part of the frozen design; no null, no chance claim; read after the headline results.** "
          "Attribution: decision j governs the close-to-close span from its trade session to the next decision's trade session (the ledger's spans, E13); a regime's figures compound the daily "
          "returns of its spans. Annualised = growth^(252 / sessions) - 1. Rules at 20.8 bps; the parent is hold-the-parent at 0 bps; indices are price indices. Full table: `regime_basis.csv`.", ""]
    pct = lambda x: f"{100 * x:+.1f}%"
    for w in ("w1", "w2"):
        d = df[df["window"] == w]
        g = lambda s, reg, f, b="SCMO_0003": float(d[(d["series"] == s) & (d["regime"] == reg) & (d["book"] == b)][f].iloc[0])
        md += [f"## {WIN_TXT[w]}", "", "### A. Time in each regime and what each instrument did there (annualised return while the regime was held; growth over all its weeks in brackets)", "",
               "| regime | weeks | sessions | share of sessions | parent 0003 | parent 0007 | parent 0010 | parent 0029 | Nifty 100 | Midcap 100 | Smallcap 100 | GOLDBEES | cash |",
               "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        tot = g("cash", "ALL", "sessions")
        for reg in REGS:
            cells = [reg, f"{int(g('cash', reg, 'spans'))}", f"{int(g('cash', reg, 'sessions'))}", f"{100 * g('cash', reg, 'sessions') / tot:.0f}%"]
            cells += [f"{pct(g('parent', reg, 'ann', b))} ({pct(g('parent', reg, 'growth', b))})" for b in BOOKS]
            cells += [f"{pct(g(n, reg, 'ann'))} ({pct(g(n, reg, 'growth'))})" for n in ("Nifty100", "MC100", "SC100", "GOLDBEES", "cash")]
            md.append("| " + " | ".join(cells) + " |")
        md += ["", "Share of weeks (spans) in which the instrument rose, by regime:", "", "| regime | parent 0003 | Nifty 100 | Midcap 100 | Smallcap 100 | GOLDBEES |", "|---|---|---|---|---|---|"]
        for reg in REGS:
            md.append(f"| {reg} | " + " | ".join(f"{100 * g(n, reg, 'up_spans'):.0f}%" for n in ("parent", "Nifty100", "MC100", "SC100", "GOLDBEES")) + " |")
        md += ["", "### B. The rules inside OUT-SELL (the only weeks where they differ), annualised while held, mean of the four books", "",
               "| regime | " + " | ".join(RULES) + " |", "|---|" + "---|" * len(RULES)]
        for reg in REGS:
            md.append(f"| {reg} | " + " | ".join(pct(float(d[(d['series'] == r) & (d['regime'] == reg)]['ann'].mean())) for r in RULES) + " |")
        md += ["", "### C. Where `-all`'s lead comes from: log-growth difference by regime (pp of log growth, mean of the four books; the rows sum to the whole-window difference)", "",
               "| regime | 50-all − 50-orig | 50-all − 50-liq | 50-all − 50-half | 50-all − 50-idx | 80-all − 80-orig | 80-all − 80-half | 80-all − 80-idx |", "|---|---|---|---|---|---|---|---|"]
        pairs = [("50-all", "50-orig"), ("50-all", "50-liq"), ("50-all", "50-half"), ("50-all", "50-idx"), ("80-all", "80-orig"), ("80-all", "80-half"), ("80-all", "80-idx")]
        for reg in REGS + ["ALL"]:
            vals = []
            for x, y in pairs:
                dx = d[(d["series"] == x) & (d["regime"] == reg)].set_index("book")["log"]
                dy = d[(d["series"] == y) & (d["regime"] == reg)].set_index("book")["log"]
                vals.append(f"{100 * float((dx - dy).mean()):+.1f}")
            md.append(f"| {'whole window' if reg == 'ALL' else reg} | " + " | ".join(vals) + " |")
        md.append("")
    (ev.parent / "regime_basis.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    print("\n".join(md))


if __name__ == "__main__":
    main()
