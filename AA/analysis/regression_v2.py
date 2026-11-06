# -*- coding: utf-8 -*-
"""
Regression gate for the v2 engine, run before any v2 result is produced.

  (a) **Study 2 still reproduces.** Study 2's own code, on its own inputs
      (the `_v0` parent exports, the v1 price cache, semi-annual ranks,
      `micro_proxy`), must reproduce `evidence/segment_v1/scorecard.csv`.
      This separates code changes from input drift: the Master workbooks
      have been appended to since, and this confirms the in-window history
      did not move.

  (b) **v2 equals v1 on identical inputs.** The v2 builders plus the
      vectorised `Simulator` are fed exactly what (a) fed Study 2's code. At
      every review the targets must match, and every daily NAV must match to
      1e-12.

Writes `evidence/segment_v2/regression.json`.
"""

from __future__ import annotations

import json
import time

import numpy as np
import pandas as pd

import segment_backtest as SB
import segment_v2 as V
from common import CACHE_DIR, EVIDENCE_DIR, PAIRS
from index_builder import Panel
from mcap_ranks import PITClassifier, load_cache
from run_arms import metrics

OUT = V.EVIDENCE_SUBDIR / "regression.json"


def v1_steps_from_targets(tg: pd.DataFrame) -> dict:
    out = {}
    for e, g in tg.groupby("entry"):
        w = {}
        for t, x in zip(g["ticker"], g["target_weight"]):
            if x > 0:
                w[t] = w.get(t, 0.0) + float(x)
        out[pd.Timestamp(e)] = (w, float(g["sleeve_weight"].iloc[0]))
    return out


def main() -> None:
    t0 = time.time()
    cal = SB.session_calendar()
    signs = SB.master_signs()
    clf = PITClassifier(load_cache("semiannual"))
    ohlcv = pd.read_parquet(CACHE_DIR / "universe_ohlcv.parquet")   # v1 cache, read-only
    panel = Panel(ohlcv, cal)
    sleeve = SB.sleeve_frame(cal)
    sim = V.Simulator(panel, sleeve)
    eff, _ = V.effective_signs(signs)
    reviews = V.window_reviews(signs)

    archived = pd.read_csv(EVIDENCE_DIR / "segment_v1" / "scorecard.csv")
    res = {"cases": [], "max_nav_abs_diff": 0.0, "max_cagr_vs_archive_abs_diff": 0.0,
           "target_mismatches": 0}

    builders = {
        "parent": (lambda pv, a: SB.parent_targets(pv, signs, clf, cal, a),
                   lambda ctx, tags: V.build_parent(ctx, eff, tags)),
        "production_v2": (lambda pv, a: SB.production_targets(pv, signs, clf, cal, a),
                          lambda ctx, tags: V.build_production(ctx, eff, tags)),
        "sleeve": (lambda pv, a: SB.build_targets(pv, "sleeve", "micro_proxy", signs, clf, cal, a),
                   lambda ctx, tags: V.build_sleeve(ctx, eff, tags, retag="weekly",
                                                    variant="micro_proxy")),
    }

    for aa, parent in PAIRS.items():
        pv = f"{parent}_v0"
        hist = SB.parent_history(pv)
        ctx = V.parent_ctx(parent, hist, reviews, cal, key_col="ticker")
        tags = V.tag_table(ctx, V.V1Tagger(clf))
        for book, (v1_make, v2_make) in builders.items():
            tg = v1_make(pv, SB.new_audit())
            v1_nav, _ = SB.simulate(tg, panel, sleeve, 0.0, SB.new_audit())
            v1_cagr = metrics(v1_nav)["cagr"]
            arch = archived[(archived["aa_scid"] == aa) & (archived["book"] == book)
                            & (archived["cost_bps"] == 0.0)]["cagr"]
            arch_cagr = float(arch.iloc[0]) if len(arch) else np.nan

            steps = v2_make(ctx, tags)
            v1t = v1_steps_from_targets(tg)
            mism = 0
            for st in steps:
                e = cal[st.entry_i]
                w1, s1 = v1t.get(e, ({}, np.nan))
                if set(w1) != set(st.weights) or abs(s1 - st.sleeve) > 1e-12 or any(
                        abs(w1[k] - st.weights[k]) > 1e-12 for k in w1):
                    mism += 1
            mism += abs(len(v1t) - len(steps))
            v2_nav, _ = sim.run(steps, 0.0)
            d = float(np.nanmax(np.abs(v2_nav.to_numpy() - v1_nav.to_numpy())))

            # Cost path too: 20.8 bps on the sleeve arm.
            d_cost = np.nan
            if book == "sleeve":
                n1, _ = SB.simulate(tg, panel, sleeve, 20.8, SB.new_audit())
                n2, _ = sim.run(steps, 20.8)
                d_cost = float(np.nanmax(np.abs(n2.to_numpy() - n1.to_numpy())))

            case = {"aa": aa, "book": book, "v1_cagr_today": v1_cagr,
                    "v1_cagr_archived": arch_cagr,
                    "cagr_vs_archive_diff": v1_cagr - arch_cagr,
                    "target_mismatches": mism, "nav_max_abs_diff": d,
                    "nav_max_abs_diff_20p8bps": d_cost}
            res["cases"].append(case)
            res["max_nav_abs_diff"] = max(res["max_nav_abs_diff"], d,
                                          0.0 if np.isnan(d_cost) else d_cost)
            res["max_cagr_vs_archive_abs_diff"] = max(res["max_cagr_vs_archive_abs_diff"],
                                                      abs(v1_cagr - arch_cagr))
            res["target_mismatches"] += mism
            print(f"  {aa} {book:<14} v1 today {v1_cagr:+.6f}  archived {arch_cagr:+.6f}  "
                  f"targets≠ {mism}  |ΔNAV| {d:.2e}  |ΔNAV@20.8| {d_cost:.2e}", flush=True)

    res["passed_a_archive"] = res["max_cagr_vs_archive_abs_diff"] < 1e-9
    res["passed_b_engine"] = res["max_nav_abs_diff"] < 1e-12 and res["target_mismatches"] == 0
    res["seconds"] = round(time.time() - t0, 1)
    V.EVIDENCE_SUBDIR.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(res, indent=2, default=str), encoding="utf-8")
    print(f"\n(a) Study 2 reproduces from archive: {res['passed_a_archive']}  "
          f"max |ΔCAGR| {res['max_cagr_vs_archive_abs_diff']:.2e}")
    print(f"(b) v2 engine == v1 on identical inputs: {res['passed_b_engine']}  "
          f"max |ΔNAV| {res['max_nav_abs_diff']:.2e}, target mismatches {res['target_mismatches']}")


if __name__ == "__main__":
    main()
