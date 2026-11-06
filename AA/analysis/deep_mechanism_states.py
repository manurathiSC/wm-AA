# -*- coding: utf-8 -*-
"""
Part 3: the four weekly signal states of (N100, SC100), 2006-01 -> 2026-08.

  both BUY | SC-only = SC100 BUY, N100 SELL | N-only = N100 BUY, SC100 SELL | both SELL

Per review R, forward returns run from the close of the trade session
(next session after R, where a decision dated R would trade) to the last
close <= trade + 28 / 91 / 182 days, for SC100, N100 and the equal-weight
N100/MC100/SC100 blend. Plus the SC100 max drawdown and worst point over
the 26 weeks after. Windows running past 2026-08-21 are dropped.

Overlapping forward windows: the weekly n is not independent; n_runs (the
number of distinct runs of the state) is reported as the effective count,
and a run-level mean (mean of per-run means) is given too.

Bear-rally test (HINDSIGHT classifications, from SC100 daily closes):
  A. drawdown episodes of >= 20%: peak -> trough -> recovery to the peak;
     a week is 'in episode' if peak <= R < recovery, split into the falling
     phase (R <= trough) and the recovery phase (R > trough);
  B. zigzag 20% swing legs: a week is in a 'down leg' if it lies between a
     swing peak and the next swing trough (the index goes on to fall >= 20%
     from that peak, and makes its low after R).

Outputs: mechanism_states_weekly.csv, mechanism_states_summary.csv,
         mechanism_states_runs.csv, mechanism_states_transitions.csv,
         mechanism_sc100_dd_episodes.csv, mechanism_sc100_zigzag.csv,
         mechanism_sc100_zigzag_20down_30up.csv, mechanism_states_disagree_runs.csv,
         mechanism_states_disagree_resolution.csv
"""

from __future__ import annotations

import numpy as np
import pandas as pd

import deep_mechanism_data as M

cal, sg, lv, gc = M.load()
s = sg.loc[(sg.index >= M.SIG_START) & (sg.index <= M.END), ["N100", "SC100"]].dropna()
LV = {"SC100": lv["SC100"].dropna(), "N100": lv["N100"].dropna(), "blend": M.blend_level(lv)}
px = LV["SC100"]

STATE = np.select([(s.N100 == 1) & (s.SC100 == 1), (s.N100 == 0) & (s.SC100 == 1),
                   (s.N100 == 1) & (s.SC100 == 0)], ["both BUY", "SC-only BUY", "N-only BUY"], "both SELL")
st = pd.Series(STATE, index=s.index)
SUBS = [("2006-10", M.SIG_START, pd.Timestamp("2010-12-31"), "OOS"),
        ("2011-15", pd.Timestamp("2011-01-01"), pd.Timestamp("2015-12-31"), "OOS"),
        ("2016-21", pd.Timestamp("2016-01-01"), M.OOS_END, "OOS"),
        ("2021-26 IS", M.IS_START, M.END, "IS"),
        ("OOS 2006-01..2021-10", M.SIG_START, M.OOS_END, "OOS"),
        ("ALL 2006-26", M.SIG_START, M.END, "mixed")]
H = {"1w": 7, "4w": 28, "13w": 91, "26w": 182}

# ── hindsight turn structure ────────────────────────────────────────────────
ep = M.dd_episodes(px[px.index >= pd.Timestamp("2005-01-01")], 0.20)
ep.to_csv(M.OUT / "mechanism_sc100_dd_episodes.csv", index=False)
zz = M.zigzag(px[px.index >= pd.Timestamp("2005-01-01")], 0.20)
zz.to_csv(M.OUT / "mechanism_sc100_zigzag.csv", index=False)
down_legs = [(zz.date[i], zz.date[i + 1]) for i in range(len(zz) - 1) if zz.kind[i] == "peak"]
zz2 = M.zigzag(px[px.index >= pd.Timestamp("2005-01-01")], 0.20, up=0.30)
zz2.to_csv(M.OUT / "mechanism_sc100_zigzag_20down_30up.csv", index=False)
down_legs2 = [(zz2.date[i], zz2.date[i + 1]) for i in range(len(zz2) - 1) if zz2.kind[i] == "peak"]
up_legs = [(zz.date[i], zz.date[i + 1], zz.level[i + 1] / zz.level[i] - 1) for i in range(len(zz) - 1)
           if zz.kind[i] == "trough"]

rows = []
for r in s.index:
    t0 = M.trade_session(cal, r)
    row = {"review": r, "state": st[r], "trade_session": t0}
    for k, L in LV.items():
        p0 = L.get(t0)
        for h, dd in H.items():
            e = t0 + pd.Timedelta(days=dd)
            row[f"{k}_{h}"] = float(L.loc[:e].iloc[-1] / p0 - 1) if (e <= M.END and pd.notna(p0)) else np.nan
    e = t0 + pd.Timedelta(days=182)
    if e <= M.END:
        path = px.loc[t0:e]
        row["SC100_26w_maxdd"] = float((path / path.cummax() - 1).min())
        row["SC100_26w_worst"] = float(path.min() / path.iloc[0] - 1)
        pn = LV["N100"].loc[t0:e]
        row["N100_26w_maxdd"] = float((pn / pn.cummax() - 1).min())
    # hindsight labels
    inside = ep[(ep.peak <= r) & (ep.recovery > r)]
    row["in_dd20_episode"] = len(inside) > 0
    row["in_dd20_falling"] = bool(((inside.trough >= r)).any())
    row["in_dd20_recovery"] = bool(((inside.trough < r)).any())
    row["in_zz_down_leg"] = any(a_ <= r < b_ for a_, b_ in down_legs)
    row["in_zz_up_leg30"] = any(a_ <= r < b_ and g >= 0.30 for a_, b_, g in up_legs)
    row["in_zz2030_down_leg"] = any(a_ <= r < b_ for a_, b_ in down_legs2)
    rows.append(row)
wk = pd.DataFrame(rows).set_index("review")
wk["run_id"] = wk["state"].ne(wk["state"].shift()).cumsum()
# governed return: from this review's trade session to the next review's trade session
nxt_ts = wk["trade_session"].shift(-1)
for k, L in LV.items():
    a_ = wk["trade_session"].map(L)
    b_ = nxt_ts.map(L)
    wk[f"{k}_gov"] = (b_ / a_ - 1).where(nxt_ts.notna() & (nxt_ts <= M.END))
wk["SC100_26w_fell10"] = (wk["SC100_26w_worst"] <= -0.10).where(wk["SC100_26w_worst"].notna())
wk.to_csv(M.OUT / "mechanism_states_weekly.csv")

# ── summary per sub-period x state ──────────────────────────────────────────
ORDER = ["both BUY", "SC-only BUY", "N-only BUY", "both SELL"]
srows, rrows, trows, brows = [], [], [], []
runs_all = wk.reset_index().groupby("run_id").agg(start=("review", "min"), end=("review", "max"),
                                                  state=("state", "first"), weeks=("state", "size"))
runs_all["next_state"] = runs_all["state"].shift(-1)
runs_all["prev_state"] = runs_all["state"].shift(1)
for lab, a, b, samp in SUBS:
    w = wk[(wk.index >= a) & (wk.index <= b)]
    for stt in ORDER:
        g = w[w.state == stt]
        row = {"period": lab, "sample": samp, "state": stt, "weeks": len(g), "share_of_weeks": len(g) / len(w),
               "n_runs": int(g["run_id"].nunique())}
        for k in LV:
            for h in H:
                x = g[f"{k}_{h}"].dropna()
                row[f"{k}_{h}_mean"] = float(x.mean()) if len(x) else np.nan
                row[f"{k}_{h}_median"] = float(x.median()) if len(x) else np.nan
                row[f"{k}_{h}_pos"] = float((x > 0).mean()) if len(x) else np.nan
                row[f"{k}_{h}_n"] = len(x)
                # run-level mean: each run counts once
                rm = g.groupby("run_id")[f"{k}_{h}"].mean().dropna()
                row[f"{k}_{h}_runmean"] = float(rm.mean()) if len(rm) else np.nan
        for k in LV:
            x = np.log1p(g[f"{k}_gov"].dropna())
            row[f"{k}_instate_ann"] = float(np.expm1(x.mean() * 52.18)) if len(x) else np.nan
            row[f"{k}_instate_logsum"] = float(x.sum())
            row[f"{k}_instate_logsum_pp_yr"] = float(100 * x.sum() / ((b - a).days / 365.25)) if len(x) else np.nan
        row["SC100_26w_fell10_share"] = float(g["SC100_26w_fell10"].dropna().mean()) if g["SC100_26w_fell10"].notna().any() else np.nan
        for c in ("SC100_26w_maxdd", "SC100_26w_worst", "N100_26w_maxdd"):
            x = g[c].dropna()
            row[c + "_mean"] = float(x.mean()) if len(x) else np.nan
            row[c + "_median"] = float(x.median()) if len(x) else np.nan
        x = g["SC100_26w_maxdd"].dropna()
        row["SC100_26w_maxdd_worse10_share"] = float((x <= -0.10).mean()) if len(x) else np.nan
        row["SC100_26w_maxdd_worse20_share"] = float((x <= -0.20).mean()) if len(x) else np.nan
        row["SC100_26w_maxdd_n"] = len(x)
        for c in ("in_dd20_episode", "in_dd20_falling", "in_dd20_recovery", "in_zz_down_leg", "in_zz_up_leg30", "in_zz2030_down_leg"):
            row["share_" + c] = float(g[c].mean()) if len(g) else np.nan
        srows.append(row)
        # run lengths (runs assigned by start date)
        ru = runs_all[(runs_all.state == stt) & (runs_all.start >= a) & (runs_all.start <= b)]
        nx = ru["next_state"].value_counts()
        rrows.append({"period": lab, "sample": samp, "state": stt, "n_runs": len(ru),
                      "median_run_wk": float(ru.weeks.median()) if len(ru) else np.nan,
                      "mean_run_wk": float(ru.weeks.mean()) if len(ru) else np.nan,
                      "max_run_wk": int(ru.weeks.max()) if len(ru) else np.nan,
                      "share_runs_1wk": float((ru.weeks == 1).mean()) if len(ru) else np.nan,
                      "share_runs_le4wk": float((ru.weeks <= 4).mean()) if len(ru) else np.nan,
                      **{f"next_{k}": int(nx.get(k, 0)) for k in ORDER}})
    # all-weeks base rate
    row = {"period": lab, "sample": samp, "state": "ALL weeks", "weeks": len(w), "share_of_weeks": 1.0,
           "n_runs": int(w["run_id"].nunique())}
    for k in LV:
        for h in H:
            x = w[f"{k}_{h}"].dropna()
            row[f"{k}_{h}_mean"] = float(x.mean())
            row[f"{k}_{h}_median"] = float(x.median())
            row[f"{k}_{h}_pos"] = float((x > 0).mean())
            row[f"{k}_{h}_n"] = len(x)
    for k in LV:
        x = np.log1p(w[f"{k}_gov"].dropna())
        row[f"{k}_instate_ann"] = float(np.expm1(x.mean() * 52.18))
        row[f"{k}_instate_logsum"] = float(x.sum())
        row[f"{k}_instate_logsum_pp_yr"] = float(100 * x.sum() / ((b - a).days / 365.25))
    row["SC100_26w_fell10_share"] = float(w["SC100_26w_fell10"].dropna().mean())
    for c in ("SC100_26w_maxdd", "SC100_26w_worst", "N100_26w_maxdd"):
        row[c + "_mean"] = float(w[c].mean())
        row[c + "_median"] = float(w[c].median())
    x = w["SC100_26w_maxdd"].dropna()
    row["SC100_26w_maxdd_worse10_share"] = float((x <= -0.10).mean())
    row["SC100_26w_maxdd_worse20_share"] = float((x <= -0.20).mean())
    row["SC100_26w_maxdd_n"] = len(x)
    for c in ("in_dd20_episode", "in_dd20_falling", "in_dd20_recovery", "in_zz_down_leg", "in_zz_up_leg30", "in_zz2030_down_leg"):
        row["share_" + c] = float(w[c].mean())
    srows.append(row)

summ = pd.DataFrame(srows)
summ.to_csv(M.OUT / "mechanism_states_summary.csv", index=False)
pd.DataFrame(rrows).to_csv(M.OUT / "mechanism_states_runs.csv", index=False)

# transition matrix (week to next week), whole history and OOS
for lab, a, b, samp in SUBS[4:]:
    w = wk[(wk.index >= a) & (wk.index <= b)]
    tm = pd.crosstab(w["state"], w["state"].shift(-1), normalize="index")
    for fr in tm.index:
        for to in tm.columns:
            trows.append({"period": lab, "from": fr, "to": to, "prob": float(tm.loc[fr, to])})
pd.DataFrame(trows).to_csv(M.OUT / "mechanism_states_transitions.csv", index=False)

# SC-only runs, one row each: how did they end, and was it a bear rally?
sc_runs = runs_all[runs_all.state.isin(["SC-only BUY", "N-only BUY"])].copy()
out = []
for _, ru in sc_runs.iterrows():
    g = wk.loc[ru.start:ru.end]
    run_ret = {f"run_{k}_ret": float(np.expm1(np.log1p(g[f"{k}_gov"]).sum())) if g[f"{k}_gov"].notna().all() else np.nan
               for k in LV}
    t0 = g["trade_session"].iloc[0]
    e = t0 + pd.Timedelta(days=182)
    out.append({"state": ru.state, "start": ru.start.date(), "end": ru.end.date(), "weeks": ru.weeks,
                "prev_state": ru.prev_state, "next_state": ru.next_state, **run_ret,
                "sample": "IS" if ru.start >= M.IS_START else "OOS",
                "SC100_13w_from_start": g["SC100_13w"].iloc[0], "N100_13w_from_start": g["N100_13w"].iloc[0],
                "SC100_26w_from_start": g["SC100_26w"].iloc[0],
                "SC100_26w_maxdd_from_start": g["SC100_26w_maxdd"].iloc[0],
                "in_dd20_falling_at_start": bool(g["in_dd20_falling"].iloc[0]),
                "in_zz_down_leg_at_start": bool(g["in_zz_down_leg"].iloc[0]),
                "in_zz2030_down_leg_at_start": bool(g["in_zz2030_down_leg"].iloc[0]),
                "in_dd20_episode_at_start": bool(g["in_dd20_episode"].iloc[0])})
scr = pd.DataFrame(out)
scr.to_csv(M.OUT / "mechanism_states_disagree_runs.csv", index=False)
# how the disagreement runs resolve, and what they cost/earn while they last
rs = []
for (stt, samp), g in scr.groupby(["state", "sample"]):
    for nx, h in list(g.groupby("next_state")) + [("any", g)]:
        rs.append({"state": stt, "sample": samp, "resolves_to": nx, "runs": len(h), "weeks": int(h.weeks.sum()),
                   "median_run_wk": float(h.weeks.median()),
                   "run_SC100_logsum": float(np.log1p(h.run_SC100_ret.dropna()).sum()),
                   "run_SC100_median": float(h.run_SC100_ret.median()),
                   "run_SC100_share_neg": float((h.run_SC100_ret.dropna() < 0).mean()),
                   "run_blend_logsum": float(np.log1p(h.run_blend_ret.dropna()).sum()),
                   "run_N100_logsum": float(np.log1p(h.run_N100_ret.dropna()).sum()),
                   "SC100_13w_from_start_median": float(h.SC100_13w_from_start.median()),
                   "SC100_26w_maxdd_from_start_median": float(h.SC100_26w_maxdd_from_start.median())})
for (stt, samp), g in scr.groupby(["state", "sample"]):
    for (pv, nx), h in g.groupby(["prev_state", "next_state"]):
        rs.append({"state": stt, "sample": samp, "entered_from": pv, "resolves_to": nx, "runs": len(h),
                   "weeks": int(h.weeks.sum()), "median_run_wk": float(h.weeks.median()),
                   "run_SC100_logsum": float(np.log1p(h.run_SC100_ret.dropna()).sum()),
                   "run_SC100_median": float(h.run_SC100_ret.median()),
                   "run_SC100_share_neg": float((h.run_SC100_ret.dropna() < 0).mean()),
                   "run_blend_logsum": float(np.log1p(h.run_blend_ret.dropna()).sum()),
                   "run_N100_logsum": float(np.log1p(h.run_N100_ret.dropna()).sum())})
pd.DataFrame(rs).to_csv(M.OUT / "mechanism_states_disagree_resolution.csv", index=False)
print(pd.DataFrame(rs).round(3).to_string(index=False))

pd.set_option("display.width", 260)
pd.set_option("display.max_columns", 80)
cols = ["period", "state", "weeks", "share_of_weeks", "n_runs", "SC100_instate_ann", "N100_instate_ann", "blend_instate_ann",
        "SC100_instate_logsum_pp_yr", "SC100_1w_mean", "SC100_4w_mean", "SC100_13w_mean", "SC100_13w_median",
        "SC100_13w_pos", "SC100_26w_mean", "N100_13w_mean", "blend_13w_mean", "SC100_13w_runmean",
        "SC100_26w_maxdd_mean", "SC100_26w_maxdd_worse20_share", "SC100_26w_fell10_share",
        "share_in_dd20_episode", "share_in_dd20_falling", "share_in_zz_down_leg", "share_in_zz2030_down_leg"]
print(summ[cols].round(3).to_string(index=False))
print(pd.DataFrame(rrows).round(2).to_string(index=False))
print(scr.round(3).to_string(index=False))
print(ep.to_string())
print(zz.to_string())
print(zz2.to_string())
