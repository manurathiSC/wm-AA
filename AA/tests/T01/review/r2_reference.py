"""T01 adversarial review, step 2: R = pct_w65_q25 (weekly) recomputed from spliced_inputs.csv
with code written from T01.md section 3 (shares nothing with own_momentum.py / the verifier).

- weekly decision sessions, p_d, targets, trade sessions vs decisions_reference.csv
- 5 random decision dates for SCMO_0042 printed by hand
- my own units book (trims first, top-ups E->G->L capped by cash, cost on both sides, build,
  final liquidation) for every book x window x cost x sleeve; end NAV vs realisations.csv,
  daily NAV vs daily_reference.csv, trades vs trades.csv
- every null draw for R, my own percentile; C1 (8 cells), C2, C3, R4, R5
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

AA = Path(__file__).resolve().parents[3]
EV = AA / "tests" / "T01" / "evidence"
BOOK2PAR = {"SCMO_0042": "SCMO_0003", "SCMO_0043": "SCMO_0007", "SCMO_0044": "SCMO_0010", "SCMO_0045": "SCMO_0029"}
OW = 20.8 / 2 / 1e4

sp = pd.read_csv(EV / "headline" / "spliced_inputs.csv", parse_dates=["date"])
cal = pd.DatetimeIndex(sp.date)
iso = cal.isocalendar()
wk = (iso.year.astype(int) * 100 + iso.week.astype(int)).to_numpy()
last_of_week = np.r_[wk[1:] != wk[:-1], True]


def window(name):
    if name == "W1":
        i0 = int(np.flatnonzero(cal <= pd.Timestamp("2015-07-31"))[-1])
        iE = int(cal.get_loc(pd.Timestamp("2021-10-29")))
    else:
        i0 = int(cal.get_loc(pd.Timestamp("2021-11-01")))
        iE = int(cal.get_loc(pd.Timestamp("2026-08-21")))
    dec = [i0] + [i for i in range(i0 + 1, iE + 1) if last_of_week[i]]
    assert dec[-1] == iE
    return i0, iE, np.array(dec)


def pct(Pv, i, W=65):
    prev = Pv[i - W:i]
    assert len(prev) == W
    return 100.0 * np.sum(prev < Pv[i]) / W


def book_run(eq, dec, i0, iE, px, ow):
    """eq: target per decision (incl. last). px: (S,3) closes on window sessions. Returns daily NAV, trades."""
    S = iE - i0 + 1
    pos = dec - i0
    units = np.zeros(3)
    cash = 1.0
    nav = np.ones(S)
    # trade schedule: decision j (j < last) trades at pos[j]+1 if eq[j] != last traded
    sched = {}
    last = None
    for j in range(len(eq) - 1):
        if last is None or eq[j] != last:
            sched[pos[j] + 1] = (eq[j], pos[j], last)
            last = eq[j]
    trades = []
    for s in range(1, S):
        c = px[s]
        if s in sched:
            e, dpos, frm = sched[s]
            nv = cash + units @ c
            tgt = np.array([e, (1 - e) * GS, (1 - e) * (1 - GS)]) * nv
            delta = tgt - units * c
            for a in range(3):          # trims
                if delta[a] < 0:
                    units[a] -= -delta[a] / c[a]
                    cash += -delta[a] * (1 - ow)
            for a in range(3):          # top-ups in order E, G, L
                if delta[a] > 0:
                    v = min(delta[a], cash)
                    units[a] += v * (1 - ow) / c[a]
                    cash -= v
            trades.append((dpos, s, frm, e, nv, cash + units @ c))
        nav[s] = cash + units @ c
    # final liquidation at last close
    pre = nav[-1]
    held = units @ px[-1]
    nav[-1] = cash + held * (1 - ow)
    trades.append((None, S - 1, last, None, pre, nav[-1]))
    return nav, trades


def stats(nav, S):
    yrs = (S - 1) / 252
    r = nav[1:] / nav[:-1] - 1
    cagr = nav[-1] ** (1 / yrs) - 1
    pk = np.maximum.accumulate(nav)
    mdd = (nav / pk - 1).min()
    vol = r.std(ddof=1) * np.sqrt(252)
    return dict(cagr=cagr, nav_end=nav[-1], max_dd=mdd, vol=vol, sharpe=cagr / vol, calmar=cagr / abs(mdd))


ref = pd.read_csv(EV / "headline" / "decisions_reference.csv", keep_default_na=False, na_values=[""])
rz = {run: pd.read_csv(EV / run / "realisations.csv", keep_default_na=False, na_values=[""],
                       dtype={"target_level_counts": str}) for run in ("headline", "cash_sleeve")}
trd = pd.read_csv(EV / "headline" / "trades.csv", keep_default_na=False, na_values=[""])
dref = pd.read_csv(EV / "headline" / "daily_reference.csv", parse_dates=["date"])

rng = np.random.default_rng(20261001)
dec_mis = 0
results = {}
for b, p in BOOK2PAR.items():
    Pv = sp[f"P_{p}"].to_numpy()
    for wn in ("W1", "W2"):
        i0, iE, dec = window(wn)
        vals = np.array([pct(Pv, i) for i in dec])
        eq = np.where(vals < 25, 0.0, 1.0)
        r = ref[(ref.book == b) & (ref.window == wn)].sort_values("decision_date")
        assert list(r.decision_date) == [cal[i].strftime("%Y-%m-%d") for i in dec], (b, wn, "decision dates")
        m1 = int((np.abs(r.value.to_numpy() - vals) > 1e-12).sum())
        m2 = int((r.equity_target.to_numpy() != eq).sum())
        # trade sessions
        w = eq[:-1]
        chg = np.r_[True, w[1:] != w[:-1]]
        tsess = ["" if not (j < len(dec) - 1 and chg[j]) else cal[dec[j] + 1].strftime("%Y-%m-%d") for j in range(len(dec))]
        m3 = int((r.trade_session.fillna("").to_numpy() != np.array(tsess)).sum())
        # trade session strictly after decision, and data_last_date <= decision
        ts_ok = all(t == "" or t > d for t, d in zip(r.trade_session.fillna(""), r.decision_date))
        dl_ok = (r.data_last_date <= r.decision_date).all()
        dec_mis += m1 + m2 + m3
        print(f"{b} {wn}: decisions {len(dec)}, value mism {m1}, target mism {m2}, trade_session mism {m3}, "
              f"trade>decision {ts_ok}, data_last<=decision {dl_ok}, first {cal[dec[0]].date()} {cal[dec[1]].date()} last {cal[dec[-1]].date()}")
        if b == "SCMO_0042" and wn == "W1":
            for j in sorted(rng.choice(len(dec), 5, replace=False)):
                i = dec[j]
                prev = Pv[i - 65:i]
                print(f"   hand: d={cal[i].date()} P_d={Pv[i]:.4f}; previous 65 closes {cal[i-65].date()}..{cal[i-1].date()} "
                      f"(min {prev.min():.2f} max {prev.max():.2f}); strictly below = {int((prev < Pv[i]).sum())} -> p={100*(prev<Pv[i]).sum()/65:.2f} "
                      f"-> e={0 if 100*(prev<Pv[i]).sum()/65 < 25 else 1}; evidence value {r.value.iloc[j]:.4f} e={r.equity_target.iloc[j]} trade {r.trade_session.iloc[j]}")
        S = iE - i0 + 1
        bhn = Pv[i0:iE + 1] / Pv[i0]
        bh = stats(bhn, S)
        for run, gs in (("headline", 0.5), ("cash_sleeve", 0.0)):
            GS = gs
            px = np.column_stack([Pv[i0:iE + 1], sp.gold.to_numpy()[i0:iE + 1], sp.cash.to_numpy()[i0:iE + 1]])
            R_ = rz[run]
            for cost in (0.0, 20.8):
                ow = cost / 2 / 1e4
                nav, trades = book_run(eq, dec, i0, iE, px, ow)
                st = stats(nav, S)
                row = R_[(R_.config == "pct_w65_q25") & (R_.book == b) & (R_.window == wn) & (R_.cost_bps == cost) & (R_.kind == "strategy")].iloc[0]
                d_nav = abs(st["nav_end"] / row.nav_end - 1)
                d_dd = abs(st["max_dd"] - row.max_dd)
                d_cal = abs(st["calmar"] - row.calmar)
                if run == "headline":
                    dd = dref[(dref.book == b) & (dref.window == wn) & (dref.cost_bps == cost)].sort_values("date")
                    d_daily = np.abs(dd.nav.to_numpy() / nav - 1).max()
                    tt = trd[(trd.config == "pct_w65_q25") & (trd.book == b) & (trd.window == wn) & (trd.cost_bps == cost)]
                    my_ts = [cal[i0 + t[1]].strftime("%Y-%m-%d") for t in trades]
                    tr_ok = list(tt.trade_session) == my_ts and np.allclose(tt.nav_after.to_numpy(), [t[5] for t in trades], rtol=1e-11)
                    kinds = tt.kind.value_counts().to_dict()
                else:
                    d_daily, tr_ok, kinds = np.nan, None, None
                # null: every rotation
                n1 = len(eq)
                nul = R_[(R_.config == "pct_w65_q25") & (R_.book == b) & (R_.window == wn) & (R_.cost_bps == cost) & (R_.kind == "null")]
                ks = sorted(nul.shift_k.astype(int))
                assert ks == list(range(8, n1 - 8 + 1)), (b, wn, "k grid", ks[:3], ks[-3:], n1)
                my_c, my_dd = [], []
                for k in ks:
                    nk, _ = book_run(np.roll(eq, k), dec, i0, iE, px, ow)
                    sk = stats(nk, S)
                    my_c.append(sk["cagr"])
                    my_dd.append(sk["max_dd"])
                my_c = np.array(my_c)
                ev_c = nul.sort_values("shift_k").cagr.to_numpy()
                d_null = np.abs(my_c - ev_c).max()
                # also check: reverse rotation gives the same set of draws
                pctile = (np.sum(my_c < st["cagr"]) + 0.5 * np.sum(my_c == st["cagr"])) / len(my_c) * 100
                results[(run, b, wn, cost)] = dict(pct=pctile, cagr=st["cagr"], dd=st["max_dd"], calmar=st["calmar"],
                                                   bh_dd=bh["max_dd"], bh_calmar=bh["calmar"], bh_cagr=bh["cagr"],
                                                   null_sd=np.std(my_c, ddof=1), share=float(np.mean(eq < 1)),
                                                   nsw=len(trades) - 2)
                print(f"   {run:11s} {cost:4.1f}bps: my nav_end {st['nav_end']:.10f} rel diff {d_nav:.1e}; dd diff {d_dd:.1e}; "
                      f"calmar diff {d_cal:.1e}; daily nav max rel {d_daily:.1e}; trades match {tr_ok} {kinds}; "
                      f"null draws {len(ks)} max |cagr diff| {d_null:.1e}; my pct {pctile:.1f}")

print("\nTOTAL decision mismatches", dec_mis)
print("\nC1 / R4 / R5 / C2 / C3 from my own engine:")
for run, cost, lab in (("headline", 20.8, "C1"), ("cash_sleeve", 20.8, "R4"), ("headline", 0.0, "R5")):
    for wn in ("W1", "W2"):
        cells = [(b, results[(run, b, wn, cost)]["pct"]) for b in BOOK2PAR]
        n = sum(x >= 90 for _, x in cells)
        print(f"  {lab} {wn}: {n} of 4 -- " + ", ".join(f"{b[-2:]} {x:.1f}" for b, x in cells))
for wn in ("W1", "W2"):
    c2 = [(results[("headline", b, wn, 20.8)]["dd"] - results[("headline", b, wn, 20.8)]["bh_dd"]) * 100 for b in BOOK2PAR]
    c3 = [(results[("headline", b, wn, 20.8)]["calmar"], results[("headline", b, wn, 20.8)]["bh_calmar"]) for b in BOOK2PAR]
    print(f"  C2 {wn}: {sum(x >= 5 for x in c2)} of 4 -- " + ", ".join(f"{x:+.2f}" for x in c2))
    print(f"  C3 {wn}: {sum(a > b for a, b in c3)} of 4 -- " + ", ".join(f"{a:.3f} vs {b:.3f}" for a, b in c3))
    print(f"  B&H CAGR {wn}: " + ", ".join(f"{results[('headline', b, wn, 20.8)]['bh_cagr']*100:.2f}%" for b in BOOK2PAR))
