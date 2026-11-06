# -*- coding: utf-8 -*-
"""
Build the v2 report: `evidence/segment_v2/report.html`.

Everything on the page is read from the evidence files written by
`parent_gap_diagnosis.py`, `run_segment_v2.py` and `segment_v2_nulls.py`, and
embedded as JSON. Charts are drawn client-side in plain SVG. The page follows
Study 1's house style (`evidence/main/report.html`), so the series reads as one
set.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

import segment_v2 as V
from common import PAIRS

E = V.EVIDENCE_SUBDIR
TEMPLATE = Path(__file__).with_name("segment_v2_report_template.html")
OUT = E / "report.html"


def _clean(x):
    if isinstance(x, float):
        if math.isnan(x) or math.isinf(x):
            return None
        return float(f"{x:.6g}")
    if isinstance(x, (np.floating,)):
        return _clean(float(x))
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (np.bool_,)):
        return bool(x)
    if isinstance(x, dict):
        return {str(k): _clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_clean(v) for v in x]
    if isinstance(x, (pd.Timestamp,)):
        return x.strftime("%Y-%m-%d")
    return x


def records(df: pd.DataFrame) -> list[dict]:
    return [_clean(r) for r in df.to_dict(orient="records")]


def series(s: pd.Series, dp: int = 5) -> list:
    return [None if (v is None or (isinstance(v, float) and math.isnan(v))) else round(float(v), dp)
            for v in s.to_numpy()]


def main() -> None:
    nav = pd.read_csv(E / "nav_curves.csv", index_col=0, parse_dates=True)
    sc = pd.read_csv(E / "scorecard.csv")
    sp = pd.read_csv(E / "stats_panel.csv")
    hd = pd.read_csv(E / "headline.csv")
    yr = pd.read_csv(E / "yearly_returns.csv", index_col=0)
    sens = pd.read_csv(E / "sensitivities.csv")
    summ = pd.read_csv(E / "rebalance_summary.csv")
    det = pd.read_csv(E / "rebalance_history.csv")
    dist = pd.read_csv(E / "bucket_distribution.csv")
    exp = pd.read_csv(E / "exposure_daily.csv", index_col=0, parse_dates=True)
    g0 = pd.read_csv(E / "parent_gap_summary.csv")
    gates = json.loads((E / "gates.json").read_text(encoding="utf-8"))
    g13 = json.loads((E / "gates_g1_g3.json").read_text(encoding="utf-8"))
    audit = json.loads((E / "audit.json").read_text(encoding="utf-8"))
    verif = json.loads((E / "verification.json").read_text(encoding="utf-8"))
    reg = json.loads((E / "regression.json").read_text(encoding="utf-8"))
    tacc = pd.read_csv(E / "tag_accuracy_holdings.csv")
    g4 = pd.read_csv(E / "null_shift.csv")
    g5 = pd.read_csv(E / "null_labels.csv")
    em = pd.read_csv(E / "null_labels_error_model.csv", index_col=0)

    nav = nav.loc[nav.index >= pd.Timestamp(audit["window"][0])]
    dates = [d.strftime("%Y-%m-%d") for d in nav.index]
    exp = exp.reindex(nav.index).ffill().fillna(0.0)

    books = {}
    for aa, parent in PAIRS.items():
        cur = {k: series(nav[f"{aa}|{k}|20.8"]) for k in
               ("sleeve", "production_v2", "n100_and_sc100", "sc100_only", "sc250_only", "parent")}
        cur["published_parent"] = series(nav[f"{aa}|published_parent"])
        cur["published_aa"] = series(nav[f"{aa}|published_aa"])
        cur["style_blend"] = series(nav[f"{aa}|style_blend"])
        cur["n100_and_sc100_allcash"] = series(nav[f"{aa}|n100_and_sc100_allcash|20.8"])
        s = sc[sc["aa"] == aa]
        extra = {f"{r['strategy']}|{r['cost_bps']:g}": {
            "trades": r["trades"], "turnover_pa": r["turnover_pa"],
            "avg_equity_weight": r["avg_equity_weight"],
            "events": None if pd.isna(r["events"]) else r["events"]} for _, r in s.iterrows()}
        gross = {r["strategy"]: r["cagr"] for _, r in s[s["cost_bps"] == 0].iterrows()}
        for k, v in extra.items():
            st, b = k.split("|")
            v["cost_drag"] = gross[st] - s[(s["strategy"] == st) & (s["cost_bps"] == float(b))][
                "cagr"].iloc[0]
        dt = det[det["aa"] == aa]
        ev = []
        for _, r in summ[summ["aa"] == aa].iterrows():
            rows = dt[dt["review"] == r["review"]][[
                "ticker", "name", "bucket", "tag_source", "rank", "signal_index", "sign",
                "action", "parent_weight", "w_before", "w_after"]]
            ev.append({**_clean(r.to_dict()), "rows": records(rows)})
        dd = dist[dist["aa"] == aa]
        yk = [f"{aa}|{k}|20.8" for k in ("sleeve", "production_v2", "n100_and_sc100",
                                          "sc100_only", "sc250_only", "parent")] + \
             [f"{aa}|published_parent", f"{aa}|published_aa", f"{aa}|style_blend"]
        books[aa] = {
            "parent": parent,
            "series": cur,
            "exposure": {"sleeve": series(exp[f"{aa}|sleeve"], 4),
                         "production_v2": series(exp[f"{aa}|production_v2"], 4),
                         "n100_and_sc100": series(exp[f"{aa}|n100_and_sc100"], 4)},
            "stats": records(sp[sp["aa"] == aa]),
            "extra": _clean(extra),
            "yearly": {k.split("|", 1)[1]: _clean(yr.loc[k].to_dict()) for k in yk},
            "events": ev,
            "dist": records(dd.drop(columns=["aa"])),
            "tag_acc": records(tacc[tacc["parent"] == parent].groupby("snapshot").apply(
                lambda g: pd.Series({"agree": g["agree"].mean(),
                                     "weighted": (g["agree"] * g["weight"]).sum() / g["weight"].sum(),
                                     "n": len(g)})).reset_index()),
        }

    bench = {c.split("|", 1)[1]: series(nav[c]) for c in nav.columns if c.startswith("bench|")}
    nulls = {"g4": {aa: [round(float(x), 5) for x in g4[g4["aa"] == aa]["D"]] for aa in PAIRS},
             "g4_gate": {aa: [round(float(x), 5) for x in g4[g4["aa"] == aa]["n100gate_D_exploratory"]]
                         for aa in PAIRS},
             "g5": {aa: [round(float(x), 5) for x in g5[g5["aa"] == aa]["D"]] for aa in PAIRS}}

    payload = {
        "meta": {"start": audit["window"][0], "end": audit["window"][1], "reviews": audit["reviews"],
                 "sha": audit["prereg_sha256"], "fallback": audit["microcap_fallback_reviews"],
                 "tag_acc": audit["tag_accuracy"], "verification_ok": verif["all_ok"],
                 "regression": {"a": reg["passed_a_archive"], "b": reg["passed_b_engine"],
                                "nav": reg["max_nav_abs_diff"]},
                 "events": {aa: audit["per_book"][aa]["events"] for aa in PAIRS},
                 "triggers": audit["per_book"]["SCMO_0042"]["event_triggers"]},
        "gates": _clean(gates),
        "g23": _clean({"G2": g13["G2"]["per_book"], "G3": g13["G3"]["per_book"]}),
        "headline": records(hd),
        "g0": records(g0),
        "rules": records(sc[["aa", "strategy", "cost_bps", "cagr", "max_dd", "sharpe", "calmar",
                             "trades", "avg_equity_weight"]]),
        "n100_trades": records(pd.read_csv(E / "n100_sc100_trades.csv")),
        "allcash": {aa: {"n100_and_sc100": _clean(float(
            nav[f"{aa}|n100_and_sc100_allcash|20.8"].iloc[-1]))} for aa in PAIRS},
        "sens": records(sens),
        "error_model": _clean({i: em.loc[i].to_dict() for i in em.index}),
        "dates": dates, "bench": bench, "books": books, "nulls": nulls,
    }
    html = TEMPLATE.read_text(encoding="utf-8").replace(
        "__DATA__", json.dumps(payload, separators=(",", ":"), allow_nan=False))
    OUT.write_text(html, encoding="utf-8")
    print(f"wrote {OUT} ({OUT.stat().st_size / 1e6:.2f} MB)")


if __name__ == "__main__":
    main()
