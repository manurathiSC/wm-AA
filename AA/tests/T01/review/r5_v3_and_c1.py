"""T01 adversarial review, step 5: V3 over every null row of both runs, and C1/C2/C3/R4/R5/R6/R7
re-scored from realisations.csv with code that shares nothing with analyse.py."""
import json
from pathlib import Path

import numpy as np
import pandas as pd

EV = Path(__file__).resolve().parents[1] / "evidence"
K = ["config", "book", "window", "cost_bps"]
for run in ("headline", "cash_sleeve"):
    rz = pd.read_csv(EV / run / "realisations.csv", keep_default_na=False, na_values=[""], dtype={"target_level_counts": str})
    s = rz[rz.kind == "strategy"].set_index(K)
    n = rz[rz.kind == "null"].copy()
    m = n.join(s[["n_switches", "target_level_counts", "share_sleeve_weeks", "avg_equity_weight", "n_decisions"]], on=K, rsuffix="_s")
    lev_bad = (m.target_level_counts.map(json.loads) != m.target_level_counts_s.map(json.loads)).sum()
    gap = (m.n_switches - m.n_switches_s).abs()
    share_bad = (np.abs(m.share_sleeve_weeks - m.share_sleeve_weeks_s) > 1e-12).sum()
    grid_bad = 0
    for key, g in m.groupby(K):
        kmin = 40 if key[0] == "pct_w65_q25_daily" else 8
        n1 = int(g.n_decisions_s.iloc[0])
        if sorted(g.shift_k.astype(int)) != list(range(kmin, n1 - kmin + 1)):
            grid_bad += 1
    print(f"{run}: null rows {len(n)}; level multiset differs {lev_bad}; share differs {share_bad}; "
          f"max |switch gap| {int(gap.max())}; >2 in {(gap > 2).sum()}; incomplete k grid {grid_bad} of {m.groupby(K).ngroups}")

    def pct(cfg, cost):
        out = {}
        for (b, w), g in n[(n.config == cfg) & (n.cost_bps == cost)].groupby(["book", "window"]):
            x = s.loc[(cfg, b, w, cost), "cagr"]
            out[(b, w)] = (np.sum(g.cagr < x) + 0.5 * np.sum(g.cagr == x)) / len(g) * 100
        return out

    bh = rz[rz.kind == "bh"].set_index(["book", "window"])
    books = sorted(s.index.get_level_values("book").unique())
    tests = [("C1 R", "pct_w65_q25", 20.8, 90)] if run == "headline" else [("R4 R", "pct_w65_q25", 20.8, 90)]
    if run == "headline":
        tests += [("R5 R 0bps", "pct_w65_q25", 0.0, 90), ("R7 daily", "pct_w65_q25_daily", 20.8, 90)] + \
                 [(f"R6 {c}", c, 20.8, 75) for c in ("pct_w40_q25", "pct_w130_q25", "pct_w65_q10", "pct_w65_q40")]
    for lab, cfg, cost, thr in tests:
        p = pct(cfg, cost)
        cnt = {w: sum(p[(b, w)] >= thr for b in books) for w in ("W1", "W2")}
        v = "PASS" if cnt["W1"] >= 3 and cnt["W2"] >= 3 else ("FAIL - passes W1 only" if cnt["W1"] >= 3 else ("FAIL - passes W2 only" if cnt["W2"] >= 3 else "FAIL"))
        print(f"  {lab:22s} W1 {cnt['W1']}/4 W2 {cnt['W2']}/4 -> {v}; " + " ".join(f"{b[-2:]}{w}:{p[(b, w)]:.1f}" for w in ("W1", "W2") for b in books))
    if run == "headline":
        for cfg in ("pct_w65_q25", "pct_w65_q25_daily"):
            for w in ("W1", "W2"):
                c2 = [(s.loc[(cfg, b, w, 20.8), "max_dd"] - bh.loc[(b, w), "max_dd"]) * 100 for b in books]
                c3 = [s.loc[(cfg, b, w, 20.8), "calmar"] > bh.loc[(b, w), "calmar"] for b in books]
                print(f"  {cfg} {w}: C2 {sum(x >= 5 for x in c2)}/4 ({', '.join(f'{x:+.2f}' for x in c2)}); C3 {sum(c3)}/4")
        # reportability of R and neighbours
        for cfg in ("pct_w65_q25", "pct_w40_q25", "pct_w130_q25", "pct_w65_q10", "pct_w65_q40", "pct_w65_q25_daily"):
            r = s.loc[cfg]
            bad = r[(r.n_switches < 4) | (r.share_sleeve_weeks < 0.05) | (r.share_sleeve_weeks > 0.95)]
            print(f"  reportability {cfg}: NOT REPORTABLE rows {len(bad)}; min switches {int(r.n_switches.min())}; share {r.share_sleeve_weeks.min():.3f}-{r.share_sleeve_weeks.max():.3f}")
