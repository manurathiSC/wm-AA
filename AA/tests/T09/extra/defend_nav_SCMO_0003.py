"""Hand re-derivation of SCMO_0003's T09 'strategy' NAV for a window, from raw price files only.

Not the engine: plain pandas/numpy, written from the rules of tests/T09/T09.md section 3 (steps 4-7) and read against analysis/t09_engine.py only for
the rule text. It replays the book from T0 (2011-11-25) with the engine's decisions (tests/T09/evidence/headline/decisions.csv, the signals in the
Excel sheet), then writes three CSVs for the window and compares every NAV, V, traded and cost with the engine's own evidence.

Run from AA/:  python tests/T09/extra/defend_nav_SCMO_0003.py [--start 2014-09-12] [--end 2015-07-17]
Outputs (tests/T09/extra/): defend_nav_daily.csv, defend_nav_weekly.csv, defend_nav_trades.csv
"""
import argparse
import io
from pathlib import Path

import numpy as np
import pandas as pd

AA = Path(__file__).resolve().parents[3]
HD = AA / "Historical Data"
EV = AA / "tests" / "T09" / "evidence" / "headline"
OUT = Path(__file__).resolve().parent
BOOK = "SCMO_0003"
W = np.array([0.09626177, 0.19679459, 0.70694364])          # Nifty 100, Midcap 100, Smallcap 100 (T09.md section 3)
IDX = ["Nifty100", "MC100", "SC100"]
NAMES = IDX + ["GOLDBEES", "LBES"]
T0, END, GB_FIRST, DESPIKE = pd.Timestamp("2011-11-25"), pd.Timestamp("2019-01-02"), pd.Timestamp("2014-07-01"), 0.005
GW_BUY, GW_SELL = 0.8, 0.2
HEAD_COST = 20.8

ap = argparse.ArgumentParser()
ap.add_argument("--start", default="2014-09-12")
ap.add_argument("--end", default="2015-07-17")
a = ap.parse_args()
WS, WE = pd.Timestamp(a.start), pd.Timestamp(a.end)

# ── raw inputs ────────────────────────────────────────────────────────────────
cal_all = pd.DatetimeIndex(sorted(pd.to_datetime(pd.read_csv(HD / "extended_2026-11-12/index_daily_pre2019/nse_trading_days.csv")["date"])))
cal = cal_all[(cal_all >= T0) & (cal_all <= END)]
T = len(cal)
bars = {}
for n in IDX:
    p = HD / f"extended_2026-11-12/index_daily_pre2019/{n}_daily_ohlcv.csv"
    lines = p.read_text(encoding="utf-8").splitlines()
    keep = [lines[0]] + [ln for ln in lines[1:] if ln[:10] >= str(T0.date())]       # SC100 before 2011-10-03 is corrupt: never parsed
    d = pd.read_csv(io.StringIO("\n".join(keep)), parse_dates=["date"]).set_index("date").sort_index().reindex(cal)
    bars[n] = d
C = np.column_stack([bars[n]["close"].values for n in IDX])                                          # valuation
P = np.column_stack([((bars[n]["open"] + bars[n]["high"] + bars[n]["low"] + bars[n]["close"]) / 4).values for n in IDX])   # fills: OHLC4

g = pd.read_parquet(AA / "analysis/cache/why_gold_ohlc_eikon_extended_2026-11-04.parquet")
g["date"] = pd.to_datetime(g["date"]); g = g.set_index("date").sort_index()
g = g[~g.index.duplicated(keep="last")]
gb = pd.read_parquet(AA / "analysis/cache/why_gold_ohlc_proxy_mauc1_2005-05-10_2014-06-30.parquet")
gb["date"] = pd.to_datetime(gb["date"]); gb = gb.set_index("date").sort_index()
m = pd.read_csv(HD / "extended_2026-11-12/MAUc1_from_2003/mauc1_daily_clean_extended.csv", index_col=0, parse_dates=True)
m.columns = [c.strip().lower() for c in m.columns]
rng = ((m["high"] - m["low"]) / m["close"]).reindex(g.index)                  # MCX gold's range that day (de-spike band)
band = rng + DESPIKE
lo, hi = g["close"] * (1 - band), g["close"] * (1 + band)
has = rng.notna()
o = g["open"].where(~has, g["open"].clip(lower=lo, upper=hi))
h = g["high"].where(~has, g["high"].clip(upper=hi))
l_ = g["low"].where(~has, g["low"].clip(lower=lo))
h = np.maximum(h, np.maximum(o, g["close"])); l_ = np.minimum(l_, np.minimum(o, g["close"]))
gfill = pd.concat([(gb["open"] + gb["high"] + gb["low"] + gb["close"]) / 4, (o + h + l_ + g["close"]) / 4])
gclose = pd.concat([gb["close"], g["close"]])
G_C = gclose.reindex(gclose.index.union(cal)).ffill().reindex(cal).values
G_F = gfill.reindex(cal).fillna(pd.Series(G_C, index=cal)).values
lb = pd.read_csv(HD / "LBES_Adjusted_Price_data_extended_2026-11-05.csv")
lb["date"] = pd.to_datetime(lb["date"], format="%d/%m/%y %H:%M")
lb = lb.set_index("date")["price"].sort_index()
L = lb.reindex(lb.index.union(cal)).ffill().reindex(cal).values

# ── decisions (the sheet) ─────────────────────────────────────────────────────
dec = pd.read_csv(EV / "decisions.csv"); dec = dec[dec["book"] == BOOK].reset_index(drop=True)
dec_idx = dec["decision_idx"].values
assert (cal[dec_idx] == pd.to_datetime(dec["decision_date"])).all()
e = dec["state"].values.astype(float)
gw = np.where(dec["g"].values == 1, GW_BUY, GW_SELL)
mo = np.array([d.month for d in cal]); prev = np.concatenate([[0], mo[:-1]])
resets = {t for t in range(1, T) if mo[t] in (1, 4, 7, 10) and mo[t] != prev[t]}


def replay(cost_bps):
    """Returns daily NAV (close), per-day units after any trade, and one record per trade."""
    ow = cost_bps / 2e4
    e_cur, gw_cur = e[0], gw[0]
    u = (W / C[0]) * e_cur                                  # T0: the proxy at the book's weights, NAV 1 at T0's close, no cost
    gu, cu = (1 - e_cur) * gw_cur / G_C[0], (1 - e_cur) * (1 - gw_cur) / L[0]
    tgt = {}
    for j in range(1, len(dec_idx)):
        t = dec_idx[j] + 1
        if t < T and (e[j] != e[j - 1] or (e[j] < 1 and gw[j] != gw[j - 1])):
            tgt[t] = (e[j], gw[j], j)
    nav = np.empty(T); units = np.empty((T, 5)); events = {}
    for t in range(T):
        if t in tgt or (t in resets and e_cur > 0):
            e_new, gw_new, jd = tgt[t] if t in tgt else (e_cur, gw_cur, None)
            kind = ("switch_in" if e_new > e_cur else "switch_out" if e_new < e_cur else "sleeve_rebalance" if t in tgt else "quarterly_reset")
            held = u * P[t]
            V = held.sum() + gu * G_F[t] + cu * L[t]
            Te, Tg, Tc = e_new * V * W, (1 - e_new) * gw_new * V, (1 - e_new) * (1 - gw_new) * V
            traded = np.abs(Te - held).sum() + abs(Tg - gu * G_F[t]) + abs(Tc - cu * L[t])
            cost = ow * traded
            k = (V - cost) / V
            events[t] = dict(kind=kind, dec_j=jd, e_before=e_cur, gw_before=gw_cur, e_after=e_new, gw_after=gw_new,
                             units_before=np.concatenate([u, [gu, cu]]), fills=np.concatenate([P[t], [G_F[t], L[t]]]),
                             values_before=np.concatenate([held, [gu * G_F[t], cu * L[t]]]), V=V,
                             targets=np.concatenate([Te, [Tg, Tc]]), traded=traded, cost=cost, k=k)
            u, gu, cu = k * Te / P[t], k * Tg / G_F[t], k * Tc / L[t]
            events[t]["units_after"] = np.concatenate([u, [gu, cu]])
            e_cur, gw_cur = e_new, gw_new
        nav[t] = float(C[t] @ u + gu * G_C[t] + cu * L[t])
        units[t] = np.concatenate([u, [gu, cu]])
    return nav, units, events


nav_h, un_h, ev_h = replay(HEAD_COST)
nav_0, un_0, ev_0 = replay(0.0)
CL = np.column_stack([C, G_C, L])                                       # closes used for valuation
eng = pd.read_csv(EV / "daily_nav.csv"); eng = eng[(eng["book"] == BOOK) & (eng["run"] == "strategy")]
eng_h = eng[eng["cost_bps"] == HEAD_COST].set_index("date")["nav"]; eng_0 = eng[eng["cost_bps"] == 0.0].set_index("date")["nav"]
eng_h.index = pd.to_datetime(eng_h.index); eng_0.index = pd.to_datetime(eng_0.index)
tr = pd.read_csv(EV / "trades.csv"); tr = tr[(tr["book"] == BOOK) & (tr["run"] == "strategy") & (tr["cost_bps"] == HEAD_COST)]
tr["date"] = pd.to_datetime(tr["date"]); tr = tr.set_index("date")

# whole-history check (every session, both costs), not just the window
full = dict(max_abs_diff_20_8=float(np.abs(nav_h - eng_h.reindex(cal).values).max()), max_abs_diff_0=float(np.abs(nav_0 - eng_0.reindex(cal).values).max()))
print("whole window T0..END, my NAV vs engine daily_nav.csv:", full, "| sessions", T, "| trades @20.8", len(ev_h), "engine trades", len(tr))
vcheck = max(abs(ev_h[t]["V"] - tr.loc[cal[t], "V"]) for t in ev_h if cal[t] in tr.index)
ccheck = max(abs(ev_h[t]["cost"] - tr.loc[cal[t], "cost"]) for t in ev_h if cal[t] in tr.index)
print("max |V - engine V| =", vcheck, " max |cost - engine cost| =", ccheck, " all trade dates in engine:", set(cal[t] for t in ev_h) == set(tr.index))

# ── daily CSV ─────────────────────────────────────────────────────────────────
win = np.flatnonzero((cal >= WS) & (cal <= WE))
dsgn = dec.assign(d=pd.to_datetime(dec["decision_date"]))
rows = []
for t in win:
    held_j = int(np.searchsorted(dec_idx + 1, t, side="right") - 1)      # the decision whose trade session has passed (in force)
    ev = ev_h.get(t)
    r = {"date": cal[t].date(), "weekday": cal[t].strftime("%a"), "decision_in_force": str(dsgn.loc[held_j, "d"].date()),
         "state_in_force(1=IN)": int(e[held_j]), "gold_gw_in_force": gw[held_j], "event_today": ev["kind"] if ev else ""}
    for i, n in enumerate(NAMES):
        r[f"close_{n}"] = CL[t, i]
    for i, n in enumerate(NAMES):
        r[f"fill_{n}"] = ev["fills"][i] if ev else np.nan
    for i, n in enumerate(NAMES):
        r[f"units_{n}"] = un_h[t, i]
    vals = un_h[t] * CL[t]
    for i, n in enumerate(NAMES):
        r[f"value_{n}"] = vals[i]
    r["NAV_hand_20.8bps"] = nav_h[t]; r["NAV_engine_20.8bps"] = eng_h[cal[t]]; r["diff_20.8"] = nav_h[t] - eng_h[cal[t]]
    r["NAV_hand_0bps"] = nav_0[t]; r["NAV_engine_0bps"] = eng_0[cal[t]]; r["diff_0"] = nav_0[t] - eng_0[cal[t]]
    r["daily_ret_20.8"] = nav_h[t] / nav_h[t - 1] - 1
    rows.append(r)
pd.DataFrame(rows).to_csv(OUT / "defend_nav_daily.csv", index=False, float_format="%.12g")

# ── trades CSV (window) ───────────────────────────────────────────────────────
rows = []
for t, ev in ev_h.items():
    if not (WS <= cal[t] <= WE):
        continue
    r = {"trade_date": cal[t].date(), "kind": ev["kind"], "decision_date": cal[dec_idx[ev["dec_j"]]].date() if ev["dec_j"] is not None else "(quarter start)",
         "e_before": ev["e_before"], "e_after": ev["e_after"], "gw_before": ev["gw_before"], "gw_after": ev["gw_after"]}
    for key in ("fills", "units_before", "values_before", "targets", "units_after"):
        for i, n in enumerate(NAMES):
            r[f"{key}_{n}"] = ev[key][i]
    r.update(V_pretrade=ev["V"], value_traded=ev["traded"], cost_paid=ev["cost"], scale_k=ev["k"], V_after_cost=ev["V"] - ev["cost"],
             engine_V=tr.loc[cal[t], "V"], engine_traded=tr.loc[cal[t], "traded"], engine_cost=tr.loc[cal[t], "cost"],
             diff_V=ev["V"] - tr.loc[cal[t], "V"], diff_traded=ev["traded"] - tr.loc[cal[t], "traded"], diff_cost=ev["cost"] - tr.loc[cal[t], "cost"])
    rows.append(r)
pd.DataFrame(rows).to_csv(OUT / "defend_nav_trades.csv", index=False, float_format="%.12g")

# ── weekly CSV: one row per decision in the window; the week is (decision close, next decision close] ──
rows = []
for j in range(len(dec_idx) - 1):
    t0, t1 = dec_idx[j], dec_idx[j + 1]
    if not (WS <= cal[t0] <= WE):
        continue
    t1 = win[-1] if cal[t1] > WE else t1
    if t1 <= t0:
        continue
    r = {"decision_date": cal[t0].date(), "trade_date": cal[t0 + 1].date(), "period_end": cal[t1].date(),
         "sign_Nifty100": dec.loc[j, "sign_Nifty100"], "sign_MC100": dec.loc[j, "sign_MC100"], "sign_SC100": dec.loc[j, "sign_SC100"],
         "all_three_buy": bool(e[j]), "sign_MAUc1": dec.loc[j, "sign_MAUc1"], "gw": gw[j],
         "holding": "Nifty100/MC100/SC100 at 9.6/19.7/70.7 (reset each quarter)" if e[j] else f"GOLDBEES {gw[j]:.0%} / LBES cash {1 - gw[j]:.0%}"}
    ev = ev_h.get(t0 + 1)
    r["trade_that_week"] = ev["kind"] if ev else ""
    r["quarterly_reset_that_week"] = ",".join(ev_h[t]["kind"] for t in range(t0 + 2, t1 + 1) if t in ev_h) if t0 + 2 <= t1 else ""
    for i, n in enumerate(NAMES):
        r[f"{n}_close_start"], r[f"{n}_close_end"] = CL[t0, i], CL[t1, i]
        r[f"{n}_ret_close_to_close"] = CL[t1, i] / CL[t0, i] - 1
    for i, n in enumerate(NAMES):
        r[f"{n}_ret_fill_to_close"] = (CL[t1, i] / ev["fills"][i] - 1) if ev else np.nan       # return actually earned on a position opened at the fill
    v1 = un_h[t1] * CL[t1]
    for i, n in enumerate(NAMES):
        r[f"{n}_weight_end"] = v1[i] / v1.sum()
    r.update({"NAV_start_hand": nav_h[t0], "NAV_end_hand": nav_h[t1], "NAV_end_engine": eng_h[cal[t1]], "diff": nav_h[t1] - eng_h[cal[t1]],
              "portfolio_ret_20.8": nav_h[t1] / nav_h[t0] - 1, "portfolio_ret_0bps": nav_0[t1] / nav_0[t0] - 1,
              "cost_paid_in_week(NAV units)": sum(ev_h[t]["cost"] for t in range(t0 + 1, t1 + 1) if t in ev_h)})
    rows.append(r)
pd.DataFrame(rows).to_csv(OUT / "defend_nav_weekly.csv", index=False, float_format="%.12g")
dd = pd.read_csv(OUT / "defend_nav_daily.csv")
print("window", WS.date(), "->", WE.date(), "| weeks", len(rows), "| trades", sum(1 for t in ev_h if WS <= cal[t] <= WE),
      "| max |NAV diff| in window (20.8):", float(dd["diff_20.8"].abs().max()), "(0 bps):", float(dd["diff_0"].abs().max()))
