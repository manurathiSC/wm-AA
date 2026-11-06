"""T01 adversarial review, step 4: R6 neighbours, R7 daily, and structurally different configs
(step 0.5 levels, hyst, st_weekly, triple, sma_200) through MY engine (written from T01.md
section 3) with every null draw at 20.8 bps, headline sleeve; targets read from
decisions_all_configs.csv (already verified row-for-row by r3). Then R6 / R7 verdicts and the
multiplicity table recomputed from realisations.csv directly.
"""
from pathlib import Path

import numpy as np
import pandas as pd

AA = Path(__file__).resolve().parents[3]
EV = AA / "tests" / "T01" / "evidence"
BOOK2PAR = {"SCMO_0042": "SCMO_0003", "SCMO_0043": "SCMO_0007", "SCMO_0044": "SCMO_0010", "SCMO_0045": "SCMO_0029"}
sp = pd.read_csv(EV / "headline" / "spliced_inputs.csv", parse_dates=["date"])
cal = pd.DatetimeIndex(sp.date)
dec = pd.read_csv(EV / "headline" / "decisions_all_configs.csv", keep_default_na=False, na_values=[""])
rz = pd.read_csv(EV / "headline" / "realisations.csv", keep_default_na=False, na_values=[""], dtype={"target_level_counts": str})
GS = 0.5
OW = 20.8 / 2 / 1e4


def book_nav(eq, pos, px, ow):
    S = px.shape[0]
    units = np.zeros(3); cash = 1.0; nav = np.ones(S)
    sched = {}; last = None
    for j in range(len(eq) - 1):
        if last is None or eq[j] != last:
            sched[pos[j] + 1] = eq[j]; last = eq[j]
    tr = 0
    for s in range(1, S):
        c = px[s]
        if s in sched:
            e = sched[s]; tr += 1
            nv = cash + units @ c
            delta = np.array([e, (1 - e) * GS, (1 - e) * (1 - GS)]) * nv - units * c
            for a in range(3):
                if delta[a] < 0:
                    units[a] += delta[a] / c[a]; cash += -delta[a] * (1 - ow)
            for a in range(3):
                if delta[a] > 0:
                    v = min(delta[a], cash); units[a] += v * (1 - ow) / c[a]; cash -= v
        nav[s] = cash + units @ c
    nav[-1] = cash + (units @ px[-1]) * (1 - ow)
    return nav, tr - 1


def cagr(nav):
    return nav[-1] ** (252 / (len(nav) - 1)) - 1


CFGS = ["pct_w40_q25", "pct_w130_q25", "pct_w65_q10", "pct_w65_q40", "pct_w65_q25_daily",
        "pct_w65_step", "pct_w65_hyst", "st_weekly", "triple", "sma_200"]
mine = {}
for b, p in BOOK2PAR.items():
    for wn in ("W1", "W2"):
        for c in CFGS:
            d = dec[(dec.config == c) & (dec.book == b) & (dec.window == wn)].sort_values("decision_date")
            idx = cal.get_indexer(pd.to_datetime(d.decision_date))
            i0, iE = idx[0], idx[-1]
            pos = idx - i0
            px = np.column_stack([sp[f"P_{p}"].to_numpy()[i0:iE + 1], sp.gold.to_numpy()[i0:iE + 1], sp.cash.to_numpy()[i0:iE + 1]])
            eq = d.equity_target.to_numpy(float)
            nav, nsw = book_nav(eq, pos, px, OW)
            s = rz[(rz.config == c) & (rz.book == b) & (rz.window == wn) & (rz.cost_bps == 20.8)]
            srow = s[s.kind == "strategy"].iloc[0]
            nul = s[s.kind == "null"].sort_values("shift_k")
            kmin = 40 if c.endswith("daily") else 8
            ks = list(range(kmin, len(eq) - kmin + 1))
            assert list(nul.shift_k.astype(int)) == ks, (c, b, wn)
            dr = np.array([cagr(book_nav(np.roll(eq, k), pos, px, OW)[0]) for k in ks])
            cg = cagr(nav)
            pc = (np.sum(dr < cg) + 0.5 * np.sum(dr == cg)) / len(dr) * 100
            mine[(c, b, wn)] = pc
            print(f"{c:18s} {b} {wn}: nav_end rel {abs(nav[-1]/srow.nav_end-1):.1e} nsw {nsw}/{int(srow.n_switches)}; "
                  f"draws {len(ks)} max|cagr diff| {np.abs(dr - nul.cagr.to_numpy()).max():.1e}; my pct {pc:.1f}", flush=True)

print("\nR6 / R7 from my engine:")
for c in CFGS[:5]:
    for wn in ("W1", "W2"):
        v = [mine[(c, b, wn)] for b in BOOK2PAR]
        thr = 90 if c.endswith("daily") else 75
        print(f"  {c} {wn}: >= {thr} in {sum(x >= thr for x in v)} of 4: " + ", ".join(f"{x:.1f}" for x in v))

# R7 C2 from realisations directly
print("\nR7 C2 (daily, after cost) from realisations.csv:")
for wn in ("W1", "W2"):
    out = []
    for b in BOOK2PAR:
        s = rz[(rz.config == "pct_w65_q25_daily") & (rz.book == b) & (rz.window == wn) & (rz.cost_bps == 20.8) & (rz.kind == "strategy")].iloc[0]
        bh = rz[(rz.kind == "bh") & (rz.book == b) & (rz.window == wn)].iloc[0]
        out.append((s.max_dd - bh.max_dd) * 100)
    print(f"  {wn}: {sum(x >= 5 for x in out)} of 4: " + ", ".join(f"{x:+.2f}" for x in out))

# multiplicity from realisations directly (27 weekly configs, and literal 28 at the same numeric k)
SWEEP = [f"pct_w{w}_q{q}" for w in (20, 40, 65, 130, 250) for q in (10, 25, 40)] + [
    "pct_w65_hyst", "pct_w65_step", "pct_w65_q25_daily", "sma_50", "sma_100", "sma_200", "tsmom_65", "tsmom_130",
    "tsmom_250", "ddhigh_250_x7p5", "ddhigh_250_x10", "ddhigh_250_x15", "st_weekly"]
assert len(SWEEP) == 28
W27 = [c for c in SWEEP if c != "pct_w65_q25_daily"]
print("\nMultiplicity (headline, 20.8 bps):")
for wn in ("W1", "W2"):
    for b in BOOK2PAR:
        s = rz[(rz.book == b) & (rz.window == wn) & (rz.cost_bps == 20.8)]
        st = s[(s.kind == "strategy") & s.config.isin(W27)].set_index("config").cagr
        nl = s[(s.kind == "null") & s.config.isin(W27)].pivot(index="shift_k", columns="config", values="cagr")
        assert nl.notna().all().all() and nl.shape[1] == 27
        bn = nl.max(axis=1).to_numpy()
        bv = st.max()
        p27 = (np.sum(bn < bv) + 0.5 * np.sum(bn == bv)) / len(bn) * 100
        st28 = s[(s.kind == "strategy") & s.config.isin(SWEEP)].set_index("config").cagr
        nl28 = s[(s.kind == "null") & s.config.isin(SWEEP)].pivot(index="shift_k", columns="config", values="cagr").dropna()
        bn28 = nl28.max(axis=1).to_numpy()
        bv28 = st28.max()
        p28 = (np.sum(bn28 < bv28) + 0.5 * np.sum(bn28 == bv28)) / len(bn28) * 100
        print(f"  {wn} {b}: best27 {st.idxmax()} {bv*100:.2f}% pct {p27:.1f} (n {len(bn)}); best28 {st28.idxmax()} pct {p28:.1f} "
              f"(k {nl28.index.min()}-{nl28.index.max()}, n {len(bn28)})")
