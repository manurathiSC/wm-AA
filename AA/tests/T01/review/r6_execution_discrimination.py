"""T01 adversarial review, step 6: does matching the engine's NAV actually pin the execution details?
Re-run R (SCMO_0042, W1 and W2, 20.8 bps, 50/50) under deliberately WRONG variants and show each
moves nav_end by far more than the 1e-15 agreement seen in r2."""
from pathlib import Path

import numpy as np
import pandas as pd

EV = Path(__file__).resolve().parents[1] / "evidence"
sp = pd.read_csv(EV / "headline" / "spliced_inputs.csv", parse_dates=["date"])
cal = pd.DatetimeIndex(sp.date)
dec = pd.read_csv(EV / "headline" / "decisions_reference.csv")
rz = pd.read_csv(EV / "headline" / "realisations.csv", keep_default_na=False, na_values=[""], dtype={"target_level_counts": str})


def run(eq, pos, px, ow, order=(0, 1, 2), trims_first=True, build_cost=True, liq_cost=True, lag=1):
    S = px.shape[0]; u = np.zeros(3); cash = 1.0; nav = np.ones(S); sched = {}; last = None
    for j in range(len(eq) - 1):
        if last is None or eq[j] != last:
            sched[pos[j] + lag] = (eq[j], last is None); last = eq[j]
    for s in range(1, S):
        c = px[s]
        if s in sched:
            e, first = sched[s]
            o = 0.0 if (first and not build_cost) else ow
            nv = cash + u @ c
            dl = np.array([e, (1 - e) / 2, (1 - e) / 2]) * nv - u * c

            def trims():
                nonlocal cash
                for a in range(3):
                    if dl[a] < 0: u[a] += dl[a] / c[a]; cash += -dl[a] * (1 - o)

            def tops():
                nonlocal cash
                for a in order:
                    if dl[a] > 0: v = min(dl[a], cash); u[a] += v * (1 - o) / c[a]; cash -= v
            if trims_first: trims(); tops()
            else: tops(); trims()
        nav[s] = cash + u @ c
    nav[-1] = cash + (u @ px[-1]) * ((1 - ow) if liq_cost else 1.0)
    return nav[-1]


for wn in ("W1", "W2"):
    d = dec[(dec.book == "SCMO_0042") & (dec.window == wn)].sort_values("decision_date")
    idx = cal.get_indexer(pd.to_datetime(d.decision_date)); i0, iE = idx[0], idx[-1]
    px = np.column_stack([sp.P_SCMO_0003.to_numpy()[i0:iE + 1], sp.gold.to_numpy()[i0:iE + 1], sp.cash.to_numpy()[i0:iE + 1]])
    eq = d.equity_target.to_numpy(float); pos = idx - i0
    ev = rz[(rz.config == "pct_w65_q25") & (rz.book == "SCMO_0042") & (rz.window == wn) & (rz.cost_bps == 20.8) & (rz.kind == "strategy")].nav_end.iloc[0]
    ow = 20.8 / 2 / 1e4
    print(f"{wn}: evidence nav_end {ev:.10f}")
    for lab, kw in [("spec (trims first, E,G,L)", {}), ("top-ups L,G,E", {"order": (2, 1, 0)}), ("top-ups G,L,E", {"order": (1, 2, 0)}),
                    ("top-ups before trims", {"trims_first": False}), ("no build cost", {"build_cost": False}),
                    ("no liquidation cost", {"liq_cost": False}), ("trade ON decision session (lag 0)", {"lag": 0})]:
        try:
            v = run(eq, pos, px, ow, **kw)
            print(f"   {lab:36s} nav_end {v:.10f} rel diff vs evidence {abs(v / ev - 1):.2e}")
        except Exception as ex:
            print(f"   {lab:36s} error {ex}")
