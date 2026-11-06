# -*- coding: utf-8 -*-
"""
The two pre-registered nulls for the v2 study, then the final verdict.

G4 — timing luck. Roll the joint in-window weekly effective-SIGN matrix (all
four indices together, so their co-movement and episode lengths survive) by
k reviews, for every 8 <= k <= N-8. Recompute D = CAGR(sleeve) −
CAGR(production_v2) at 20.8 bps. Pass: D_k > 0 in >= 70% of shifts on >= 3
books.

G5 — classification noise. 500 draws, seed 20260924. Re-sample each
rank-sourced tag from P(true bucket | predicted bucket), drawn once per
(security, rank snapshot) and shared across books. A drawn truth of "not in
any index" keeps the original band. Membership tags are never perturbed.
Pass: 10th percentile of D > 0 on >= 3 books.

Exploratory, NOT pre-registered: the same G4 shifts for the `sleeve_n100gate`
sensitivity, which showed the largest D. They are labelled as such everywhere.

Writes `null_shift.csv`, `null_labels.csv` and `gates.json` (G0–G5 plus the
verdict).
"""

from __future__ import annotations

import json
import time

import numpy as np
import pandas as pd

import segment_v2 as V
import stats_v2 as S
from common import PAIRS
from run_segment_v2 import load_inputs, rebase

OUT = V.EVIDENCE_SUBDIR
N_LABEL_DRAWS = 500
SEED = 20260924
MIN_SHIFT = 8


def perturbed_tables(tables: dict, pmodel: pd.DataFrame, rng: np.random.Generator) -> dict:
    """One G5 draw across all books: a new bucket per (key, rank snapshot)."""
    cols = list(pmodel.columns)
    probs = {b: pmodel.loc[b].to_numpy(dtype=float) for b in pmodel.index}
    draw: dict = {}
    out = {}
    for aa, tags in tables.items():
        nt = {}
        for r, row in tags.items():
            nr = {}
            for k, t in row.items():
                if t.source not in ("rank", "rank>900"):
                    nr[k] = t
                    continue
                ck = (k, t.snapshot)
                if ck not in draw:
                    pred = t.bucket if t.source == "rank" else "Unknown"
                    truth = rng.choice(cols, p=probs[pred])
                    draw[ck] = t.bucket if truth == "Unknown" else truth
                b = draw[ck]
                nr[k] = t if b == t.bucket else V.Tag(b, t.source, t.snapshot, t.rank)
            nt[r] = nr
        out[aa] = nt
    return out


def main() -> None:
    t0 = time.time()
    inp = load_inputs()
    cal, eff, reviews, start, sim = (inp[k] for k in ("cal", "eff", "reviews", "start", "sim"))
    ctxs, tables, parent_cagr = {}, {}, {}
    for aa, parent in PAIRS.items():
        hist = inp["hold"][inp["hold"]["parent"] == parent]
        ctxs[aa] = V.parent_ctx(parent, hist, reviews, cal)
        tables[aa] = V.tag_table(ctxs[aa], inp["taggers"]["hybrid"])
        parent_cagr[aa] = S.cagr(rebase(sim.run(V.build_parent(ctxs[aa], eff),
                                                 V.PRIMARY_BPS)[0].loc[start:]))

    def run_book(aa, sig, tags, gate=False):
        s = S.cagr(rebase(sim.run(V.build_sleeve(ctxs[aa], sig, tags, "event", "micro_own", gate),
                                  V.PRIMARY_BPS)[0].loc[start:]))
        p = S.cagr(rebase(sim.run(V.build_production(ctxs[aa], sig, tags),
                                  V.PRIMARY_BPS)[0].loc[start:]))
        return s, p

    obs = {aa: run_book(aa, eff, tables[aa]) for aa in PAIRS}
    obs_gate = {aa: run_book(aa, eff, tables[aa], gate=True) for aa in PAIRS}

    # ── G4 ─────────────────────────────────────────────────────────────────
    n = len(reviews)
    rows = []
    for k in range(MIN_SHIFT, n - MIN_SHIFT + 1):
        sh = V.shift_signs(eff, reviews, k)
        for aa in PAIRS:
            s, p = run_book(aa, sh, tables[aa])
            sg, pg = run_book(aa, sh, tables[aa], gate=True)
            rows.append({"k": k, "aa": aa, "cagr_sleeve": s, "cagr_production_v2": p, "D": s - p,
                         "sleeve_minus_parent": s - parent_cagr[aa],
                         "n100gate_D_exploratory": sg - pg})
        if k % 40 == 0:
            print(f"  G4 shift {k}/{n - MIN_SHIFT}  ({time.time() - t0:.0f}s)", flush=True)
    g4 = pd.DataFrame(rows)
    g4.to_csv(OUT / "null_shift.csv", index=False)

    # ── G5 ─────────────────────────────────────────────────────────────────
    pmodel = pd.read_csv(OUT / "null_labels_error_model.csv", index_col=0)
    rng = np.random.default_rng(SEED)
    rows = []
    for d in range(N_LABEL_DRAWS):
        pt = perturbed_tables(tables, pmodel, rng)
        for aa in PAIRS:
            s, p = run_book(aa, eff, pt[aa])
            rows.append({"draw": d, "aa": aa, "cagr_sleeve": s, "cagr_production_v2": p, "D": s - p})
        if (d + 1) % 100 == 0:
            print(f"  G5 draw {d + 1}/{N_LABEL_DRAWS}  ({time.time() - t0:.0f}s)", flush=True)
    g5 = pd.DataFrame(rows)
    g5.to_csv(OUT / "null_labels.csv", index=False)

    # ── Gates and verdict ──────────────────────────────────────────────────
    g0 = json.loads((OUT / "gate_g0.json").read_text(encoding="utf-8"))
    g13 = json.loads((OUT / "gates_g1_g3.json").read_text(encoding="utf-8"))
    per4, per5 = {}, {}
    for aa in PAIRS:
        x = g4[g4["aa"] == aa]
        dobs = obs[aa][0] - obs[aa][1]
        tobs = obs[aa][0] - parent_cagr[aa]
        per4[aa] = {"D_observed": dobs, "share_D_positive": float((x["D"] > 0).mean()),
                    "D_percentile_of_observed": float((x["D"] < dobs).mean()),
                    "timing_percentile_vs_parent_info": float((x["sleeve_minus_parent"] < tobs).mean()),
                    "D_median": float(x["D"].median()), "draws": int(len(x)),
                    "n100gate_D_observed_exploratory": obs_gate[aa][0] - obs_gate[aa][1],
                    "n100gate_share_D_positive_exploratory":
                        float((x["n100gate_D_exploratory"] > 0).mean())}
        y = g5[g5["aa"] == aa]
        per5[aa] = {"D_observed": dobs, "D_p10": float(y["D"].quantile(0.10)),
                    "D_p50": float(y["D"].median()), "D_p90": float(y["D"].quantile(0.90)),
                    "share_D_positive": float((y["D"] > 0).mean()), "draws": int(len(y))}
    gates = {
        "G0": {"rule": g0["rule"], "per_book_gap_pp": g0["per_book_gap_pp"], "passed": g0["passed"]},
        "G1": {k: g13["G1"][k] for k in ("rule", "D_per_book", "books_positive", "passed")},
        "G2": {k: g13["G2"][k] for k in ("rule", "books_positive", "passed")},
        "G3": {k: g13["G3"][k] for k in ("rule", "books_positive", "passed")},
        "G4": {"rule": "share(D_k > 0) >= 0.70 on >= 3 books", "per_book": per4,
               "books_passing": int(sum(v["share_D_positive"] >= 0.70 for v in per4.values()))},
        "G5": {"rule": "p10 of D > 0 on >= 3 books", "per_book": per5,
               "books_passing": int(sum(v["D_p10"] > 0 for v in per5.values()))},
    }
    gates["G4"]["passed"] = gates["G4"]["books_passing"] >= 3
    gates["G5"]["passed"] = gates["G5"]["books_passing"] >= 3
    if not gates["G1"]["passed"]:
        verdict = "REJECTED"
    elif all(gates[g]["passed"] for g in ("G2", "G3", "G4", "G5")):
        verdict = "SUPPORTED"
    else:
        verdict = "NOT PROVEN (failing: " + ", ".join(
            g for g in ("G2", "G3", "G4", "G5") if not gates[g]["passed"]) + ")"
    gates["verdict"] = verdict
    gates["verdict_conditional_on_G0"] = not g0["passed"]
    gates["prereg_sha256"] = V.prereg_sha256()
    (OUT / "gates.json").write_text(json.dumps(gates, indent=2, default=str), encoding="utf-8")

    print(f"\nVERDICT: {verdict}{' (conditional on unresolved G0 gap)' if not g0['passed'] else ''}")
    for g in ("G0", "G1", "G2", "G3", "G4", "G5"):
        print(f"  {g}: {'PASS' if gates[g]['passed'] else 'FAIL'}")
    print(pd.DataFrame(per4).T.round(4).to_string())
    print(pd.DataFrame(per5).T.round(4).to_string())
    print(f"({time.time() - t0:.0f}s)")


if __name__ == "__main__":
    main()
