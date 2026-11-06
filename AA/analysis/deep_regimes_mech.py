# -*- coding: utf-8 -*-
"""
Deep study, parts 3 and 4: regimes and mechanism.

Part 3 - regimes. Every session is labelled with the regime in force at the
review that governs it (a Friday-R decision earns from the second session
after R), so ex-ante labels use only data known at R. Labels:
  R1 phase (hindsight, from 10% zig-zag swings on SC100 Friday closes):
     bear (inside a fall of 20%+), correction (fall of 10-20%),
     recovery (rise, still below the prior swing high), bull (rise above it)
  R2 trend (ex-ante): SC100 above / below its 40-week average
  R3 volatility (ex-ante): SC100 13-week realised vol, tercile of all past values
  R4 leadership (ex-ante): SC100 minus N100 26-week return (> +5pp small-led,
     < -5pp large-led, else neutral)
  R5 signal state: both BUY / only N100 / only SC100 / both SELL
  R6 breadth (ex-ante): number of N50, N100, MC100, SC100 signals in BUY
  R7 co-movement (ex-ante): trailing 52-week correlation of weekly N100 and
     SC100 returns, tercile of all past values
Per bucket: the annualised return earned in it by each rule (cash sleeve),
pair minus bh and pair minus sc100, and the pair's time in equity.

Part 4 - mechanism.
  a. Decomposition of pair - bh, sc100 - bh and pair - sc100 into losses
     avoided, gains missed, sleeve earned and costs, per year and per period.
  b. Signal diagnostics on SC100 (spells, whipsaws, false exits and entries,
     entry lag, exit give-back).
  c. Disagreement states 2006-2026: frequency, run lengths, forward returns,
     forward 26-week max drawdown, and how many sit inside SC100 bear phases.
  d. Lead-lag at every SC100 fall of 20%+ (hindsight swing dates).

Writes evidence/why_n100sc100/deep/regime_*.csv and mech_*.csv.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from deep_core_common import DEEP, IS0, OOS_END, S0, build, friday, load, zigzag
from why_n100sc100 import daily_weight

COST = 20.8 / 1e4


def weekly_close(px, col):
    return friday(px[col].loc["2004-01-01":])


def phase_labels(p: pd.Series) -> pd.Series:
    """R1 on a weekly series: bear / correction / recovery / bull (hindsight)."""
    piv = zigzag(p, 0.10)
    lab = pd.Series("bull", index=p.index, dtype=object)
    prior_high = None
    for k in range(len(piv) - 1):
        (t0, a), (t1, b) = piv[k], piv[k + 1]
        seg = p.loc[a:b].index[1:]
        if t0.startswith("H"):
            depth = p[b] / p[a] - 1
            lab.loc[seg] = "bear" if depth <= -0.20 else "correction"
            prior_high = p[a]
        else:
            if prior_high is not None:
                lab.loc[seg] = np.where(p.loc[seg] < prior_high, "recovery", "bull")
    return lab


def expanding_tercile(x: pd.Series, min_n=52) -> pd.Series:
    out = pd.Series(index=x.index, dtype=object)
    vals = x.to_numpy()
    for i in range(len(x)):
        past = vals[:i]
        past = past[~np.isnan(past)]
        if len(past) < min_n or np.isnan(vals[i]):
            continue
        q1, q2 = np.quantile(past, [1 / 3, 2 / 3])
        out.iloc[i] = "low" if vals[i] <= q1 else "high" if vals[i] > q2 else "mid"
    return out


def review_labels(px, sg):
    rv = sg.index[(sg.index >= pd.Timestamp("2006-01-01"))]
    sc, n1 = weekly_close(px, "SC100"), weekly_close(px, "N100")
    sc_r, n1_r = np.log(sc).diff(), np.log(n1).diff()
    L = pd.DataFrame(index=rv)
    L["R1_phase"] = phase_labels(sc).reindex(rv, method="ffill").values
    sma40 = sc.rolling(40).mean()
    L["R2_trend"] = np.where(sc.reindex(rv, method="ffill") > sma40.reindex(rv, method="ffill"), "above 40w avg", "below 40w avg")
    L.loc[sma40.reindex(rv, method="ffill").isna().values, "R2_trend"] = np.nan
    vol = sc_r.rolling(13).std() * np.sqrt(52)
    L["R3_vol"] = expanding_tercile(vol).reindex(rv, method="ffill").values
    lead = (sc / sc.shift(26) - 1) - (n1 / n1.shift(26) - 1)
    ld = lead.reindex(rv, method="ffill")
    L["R4_leadership"] = np.where(ld > 0.05, "small-led", np.where(ld < -0.05, "large-led", "neutral"))
    L.loc[ld.isna().values, "R4_leadership"] = np.nan
    s = sg.reindex(rv)
    L["R5_state"] = np.select([(s.N100 == 1) & (s.SC100 == 1), (s.N100 == 1) & (s.SC100 == 0),
                               (s.N100 == 0) & (s.SC100 == 1)], ["both BUY", "only N100 BUY", "only SC100 BUY"], "both SELL")
    L.loc[s[["N100", "SC100"]].isna().any(axis=1).values, "R5_state"] = np.nan
    L["R6_breadth"] = s[["N50", "N100", "MC100", "SC100"]].sum(axis=1, min_count=4).map(
        lambda v: np.nan if pd.isna(v) else f"{int(v)} of 4 BUY")
    corr = sc_r.rolling(52).corr(n1_r)
    L["R7_comove"] = expanding_tercile(corr).reindex(rv, method="ffill").values
    return L


def session_labels(L: pd.DataFrame, cal: pd.DatetimeIndex) -> pd.DataFrame:
    """Each session gets the labels of the review whose decision governs it."""
    starts = []
    for r in L.index:
        j = cal.searchsorted(r, side="right")
        starts.append(cal[j + 1] if j + 1 < len(cal) else pd.NaT)
    X = L.copy()
    X.index = pd.DatetimeIndex(starts)
    X = X[X.index.notna()]
    X = X[~X.index.duplicated(keep="last")]
    return X.reindex(X.index.union(cal)).ffill().reindex(cal)


def ann(r: pd.Series) -> float:
    r = r.dropna()
    return float(np.expm1(np.log1p(r).sum() * 252 / len(r))) if len(r) else np.nan


def part_regimes(N, W, px, sg, cal):
    L = review_labels(px, sg)
    L.to_csv(DEEP / "regime_review_labels.csv")
    S = session_labels(L, cal)
    R = N.pct_change()
    rows = []
    for leg in ("SC100", "blend", "N100"):
        for sl in ("cash", "50/50"):
            cols = {ru: f"{leg}|{ru}|{sl}" for ru in ("pair", "triple", "sc100", "own", "bh") if f"{leg}|{ru}|{sl}" in N}
            for samp, a, b in (("oos", S0, OOS_END), ("in-sample", IS0, pd.Timestamp("2026-08-21"))):
                if sl == "50/50" and samp == "oos":
                    a = pd.Timestamp("2014-07-08")
                idx = R.loc[a:b].index[1:]
                for lab in L.columns:
                    lb = S[lab].reindex(idx)
                    for bucket in sorted(lb.dropna().unique()):
                        m = idx[(lb == bucket).to_numpy()]
                        rec = {"leg": leg, "sleeve": sl, "sample": samp, "labelling": lab, "bucket": bucket,
                               "weeks": round(len(m) / 5, 1), "share_of_time": len(m) / len(idx)}
                        for ru, c in cols.items():
                            rec[f"{ru}_ann"] = ann(R[c].reindex(m))
                        rec["pair_minus_bh"] = rec["pair_ann"] - rec["bh_ann"]
                        rec["pair_minus_sc100"] = rec["pair_ann"] - rec["sc100_ann"]
                        rec["pair_in_equity"] = float(W[cols["pair"]].reindex(m).mean())
                        # contribution to the whole-period log gap (log-points per year of the period)
                        rec["pair_minus_bh_logpts_per_yr_of_period"] = float(
                            (np.log1p(R[cols["pair"]].reindex(m)).sum() - np.log1p(R[cols["bh"]].reindex(m)).sum()) * 252 / len(idx))
                        rec["pair_minus_sc100_logpts_per_yr_of_period"] = float(
                            (np.log1p(R[cols["pair"]].reindex(m)).sum() - np.log1p(R[cols["sc100"]].reindex(m)).sum()) * 252 / len(idx))
                        rows.append(rec)
    T = pd.DataFrame(rows)
    T.to_csv(DEEP / "regime_table.csv", index=False)

    # forward returns by state x phase and state x trend, from each review's entry session
    lvl = px[["SC100", "N100"]]
    fw = []
    for r_, row in L.iterrows():
        j = cal.searchsorted(r_, side="right")
        if j + 65 >= len(cal):
            continue
        a = cal[j]
        rec = {"review": r_, "sample": "in-sample" if r_ >= IS0 else "oos", **row.to_dict()}
        for k, n in (("4w", 20), ("13w", 65)):
            for c in ("SC100", "N100"):
                rec[f"{c}_{k}"] = float(lvl[c].iloc[j + n] / lvl[c].iloc[j] - 1) if pd.notna(lvl[c].iloc[j]) else np.nan
        fw.append(rec)
    F = pd.DataFrame(fw)
    F.to_csv(DEEP / "regime_forward_by_review.csv", index=False)
    xt = []
    for other in ("R1_phase", "R2_trend"):
        for (samp, st, ob), g in F.groupby(["sample", "R5_state", other]):
            xt.append({"sample": samp, "cross": other, "state": st, "other": ob, "n": len(g),
                       "SC100_4w": g.SC100_4w.mean(), "SC100_13w": g.SC100_13w.mean(),
                       "SC100_13w_up": (g.SC100_13w > 0).mean(), "N100_13w": g.N100_13w.mean()})
    X = pd.DataFrame(xt)
    X.to_csv(DEEP / "regime_state_cross.csv", index=False)
    return L, T, X, F


def spells(w: pd.Series):
    """Runs of constant weight: (state, start, end_exclusive_index)."""
    v = w.to_numpy()
    out, s = [], 0
    for i in range(1, len(v) + 1):
        if i == len(v) or v[i] != v[s]:
            out.append((v[s], s, i))
            s = i
    return out


def part_mechanism(N, W, px, sg, cal, L):
    lv = px
    rows = []
    # a. decomposition (cash sleeve)
    from deep_core_common import load as _load
    _, _, r, gc, _ = _load()
    rc = gc["cash"].pct_change()
    for leg in ("SC100", "blend"):
        req = r[leg]
        segs = [("2007-07 -> 2021-10 (oos)", S0, OOS_END), ("2021-11 -> 2026-08 (in-sample)", IS0, pd.Timestamp("2026-08-21"))]
        segs += [(str(y), pd.Timestamp(f"{y}-01-01") if y > 2007 else S0, pd.Timestamp(f"{y}-12-31")) for y in range(2007, 2027)]
        for name, a, b in segs:
            idx = N.loc[a:b].index[1:]
            e = req.reindex(idx).fillna(0.0)
            c = rc.reindex(idx).fillna(0.0)
            yrs = len(idx) / 252
            for A_, B_ in (("pair", "bh"), ("sc100", "bh"), ("pair", "sc100")):
                wa = W[f"{leg}|{A_}|cash"].reindex(idx)
                wb = W[f"{leg}|{B_}|cash"].reindex(idx)
                wpa, wpb = W[f"{leg}|{A_}|cash"].shift(1).reindex(idx), W[f"{leg}|{B_}|cash"].shift(1).reindex(idx)
                d = wb - wa                      # >0: A is out where B is in
                out = d > 0
                back = d < 0
                avoided = float((-e[out & (e < 0)] * d[out & (e < 0)]).sum() + (e[back & (e > 0)] * -d[back & (e > 0)]).sum())
                missed = float((e[out & (e > 0)] * d[out & (e > 0)]).sum() + (-e[back & (e < 0)] * -d[back & (e < 0)]).sum())
                sleeve = float((c * d).sum())
                cost = float(((wa - wpa).abs() - (wb - wpb).abs()).sum() * COST)
                ra = N[f"{leg}|{A_}|cash"].pct_change().reindex(idx)
                rb = N[f"{leg}|{B_}|cash"].pct_change().reindex(idx)
                total = float((ra - rb).sum())
                rows.append({"leg": leg, "period": name, "a": A_, "b": B_, "years": yrs,
                             "losses_avoided_pp_yr": avoided / yrs * 100, "gains_missed_pp_yr": missed / yrs * 100,
                             "sleeve_earned_pp_yr": sleeve / yrs * 100, "extra_costs_pp_yr": cost / yrs * 100,
                             "total_pp_yr": total / yrs * 100,
                             "identity_residual_pp_yr": (total - (avoided - missed + sleeve - cost)) / yrs * 100,
                             "days_a_out_b_in": int(out.sum()), "days_a_in_b_out": int(back.sum())})
    D = pd.DataFrame(rows)
    D.to_csv(DEEP / "mech_decomposition.csv", index=False)

    # b. signal diagnostics on SC100
    lvl = lv["SC100"].reindex(N.index)
    cc = N.index
    w_n100 = daily_weight(sg["N100"].dropna()[lambda s: s.index >= S0 - pd.Timedelta(days=7)], cc).reindex(cc).ffill().fillna(1.0)
    diag = []
    for rule, w in (("pair", W["SC100|pair|cash"]), ("sc100", W["SC100|sc100|cash"]),
                    ("triple", W["SC100|triple|cash"]), ("N100 only", w_n100)):
        sp = spells(w)
        for samp, a, b in (("oos", S0, OOS_END), ("in-sample", IS0, pd.Timestamp("2026-08-21"))):
            ins, outs, fe, fen, lag, gb = [], [], [], [], [], []
            for k, (st, i0, i1) in enumerate(sp):
                d0 = cc[i0]
                if not (a <= d0 <= b) or k == 0:
                    continue
                lenw = (i1 - i0) / 5
                (ins if st == 1 else outs).append(lenw)
                lvl0 = lvl.iloc[i0 - 1]
                j13 = min(i0 - 1 + 65, len(lvl) - 1)
                prev = sp[k - 1]
                if st == 0:     # an exit
                    fe.append(lvl.iloc[j13] > lvl0)
                    hi = lvl.iloc[prev[1]:i0].max()
                    gb.append(lvl0 / hi - 1)
                else:           # an entry
                    fen.append(lvl.iloc[j13] < lvl0)
                    lo = lvl.iloc[prev[1]:i0].min()
                    lag.append(lvl0 / lo - 1)
            diag.append({"rule": rule, "sample": samp, "entries": len(ins), "exits": len(outs),
                         "median_in_spell_w": np.median(ins) if ins else np.nan, "mean_in_spell_w": np.mean(ins) if ins else np.nan,
                         "median_out_spell_w": np.median(outs) if outs else np.nan, "mean_out_spell_w": np.mean(outs) if outs else np.nan,
                         "whipsaw_in_spells_le4w": int(sum(x <= 4 for x in ins)),
                         "false_exit_share": np.mean(fe) if fe else np.nan, "false_entry_share": np.mean(fen) if fen else np.nan,
                         "median_entry_lag": np.median(lag) if lag else np.nan, "median_exit_give_back": np.median(gb) if gb else np.nan,
                         "time_in_equity": float(w.loc[a:b].mean())})
    G = pd.DataFrame(diag)
    G.to_csv(DEEP / "mech_signal_diagnostics.csv", index=False)

    # c. disagreement states, 2006-2026
    st = L["R5_state"].dropna()
    blend_lvl = lv["blend"]
    recs = []
    for r_, s in st.items():
        j = cal.searchsorted(r_, side="right")
        if j >= len(cal):
            continue
        rec = {"review": r_, "state": s, "phase": L.loc[r_, "R1_phase"]}
        for k, n in (("4w", 20), ("13w", 65), ("26w", 130)):
            ok = j + n < len(cal)
            for c, ser in (("SC100", lv["SC100"]), ("N100", lv["N100"]), ("blend", blend_lvl)):
                rec[f"{c}_{k}"] = float(ser.iloc[j + n] / ser.iloc[j] - 1) if ok and pd.notna(ser.iloc[j]) else np.nan
        if j + 130 < len(cal):
            path = lv["SC100"].iloc[j:j + 131]
            rec["SC100_maxdd_26w"] = float((path / path.cummax() - 1).min())
            rec["SC100_worst_26w"] = float(path.min() / path.iloc[0] - 1)
        recs.append(rec)
    Z = pd.DataFrame(recs)
    Z["sub"] = pd.cut(Z.review, [pd.Timestamp("2005-12-31"), pd.Timestamp("2010-12-31"), pd.Timestamp("2015-12-31"),
                                  OOS_END, pd.Timestamp("2026-12-31")], labels=["2006-10", "2011-15", "2016-21", "2021-26 (in-sample)"])
    Z.to_csv(DEEP / "mech_states_by_review.csv", index=False)
    agg = []
    for keys, g in list(Z.groupby(["sub", "state"], observed=True)) + [(("2006-21 (all oos)", s), g) for s, g in Z[Z.review <= OOS_END].groupby("state")]:
        rec = {"sub": keys[0], "state": keys[1], "weeks": len(g), "share_of_weeks": np.nan}
        for c in ("SC100", "N100", "blend"):
            for k in ("4w", "13w", "26w"):
                x = g[f"{c}_{k}"].dropna()
                rec[f"{c}_{k}_mean"] = x.mean(); rec[f"{c}_{k}_up"] = (x > 0).mean()
        rec["SC100_13w_median"] = g["SC100_13w"].median()
        rec["SC100_worst_26w_mean"] = g["SC100_worst_26w"].mean()
        rec["share_in_SC100_bear_phase"] = (g.phase == "bear").mean()
        rec["share_in_bear_or_correction"] = g.phase.isin(["bear", "correction"]).mean()
        agg.append(rec)
    A = pd.DataFrame(agg)
    tot = A.groupby("sub")["weeks"].transform("sum")
    A["share_of_weeks"] = A.weeks / tot
    A.to_csv(DEEP / "mech_states_summary.csv", index=False)
    # run lengths
    runs = []
    s = st.copy()
    blk = (s != s.shift()).cumsum()
    for _, g in s.groupby(blk):
        runs.append({"state": g.iloc[0], "start": g.index[0].date(), "weeks": len(g), "oos": g.index[0] <= OOS_END})
    RL = pd.DataFrame(runs)
    RL.to_csv(DEEP / "mech_state_runs.csv", index=False)
    rl = RL[RL.oos].groupby("state").weeks.agg(["count", "mean", "median", "max"]).reset_index()
    rl.to_csv(DEEP / "mech_state_run_lengths_oos.csv", index=False)

    # d. lead-lag at every SC100 fall of 20%+ (hindsight swing dates)
    sc = friday(lv["SC100"].loc["2005-01-01":])
    piv = zigzag(sc, 0.10)
    ll = []
    sgn = sg[["N100", "SC100"]].dropna()
    for k in range(len(piv) - 1):
        (t0, a), (t1, b) = piv[k], piv[k + 1]
        if not t0.startswith("H") or sc[b] / sc[a] - 1 > -0.20 or a < pd.Timestamp("2006-02-01"):
            continue
        rec = {"peak": a.date(), "trough": b.date(), "depth": float(sc[b] / sc[a] - 1)}
        after_pk = sgn[sgn.index >= a]
        for c in ("N100", "SC100"):
            at = sgn[c].asof(a)
            sells = after_pk[after_pk[c] == 0]
            if at == 0:
                d = sgn[sgn[c] == 1].index
                d = d[d <= a]
                rec[f"{c}_sell"] = "already SELL"
                rec[f"{c}_sell_weeks_after_peak"] = 0.0
                rec[f"{c}_sell_index_fall"] = 0.0
            elif len(sells):
                d0 = sells.index[0]
                rec[f"{c}_sell"] = str(d0.date())
                rec[f"{c}_sell_weeks_after_peak"] = (d0 - a).days / 7
                rec[f"{c}_sell_index_fall"] = float(sc.asof(d0) / sc[a] - 1)
        pexit = after_pk[(after_pk.N100 * after_pk.SC100) == 0]
        at_pair = sgn.N100.asof(a) * sgn.SC100.asof(a)
        d0 = a if at_pair == 0 else (pexit.index[0] if len(pexit) else None)
        rec["pair_exit_weeks_after_peak"] = (d0 - a).days / 7 if d0 is not None else np.nan
        rec["pair_exit_index_fall"] = float(sc.asof(d0) / sc[a] - 1) if d0 is not None else np.nan
        after_tr = sgn[sgn.index >= b]
        for c in ("N100", "SC100"):
            buys = after_tr[after_tr[c] == 1]
            if len(buys):
                d1 = buys.index[0]
                rec[f"{c}_buy_weeks_after_trough"] = (d1 - b).days / 7
                rec[f"{c}_buy_index_rise"] = float(sc.asof(d1) / sc[b] - 1)
        both = after_tr[(after_tr.N100 * after_tr.SC100) == 1]
        if len(both):
            d1 = both.index[0]
            rec["pair_entry_weeks_after_trough"] = (d1 - b).days / 7
            rec["pair_entry_index_rise"] = float(sc.asof(d1) / sc[b] - 1)
        ll.append(rec)
    LL = pd.DataFrame(ll)
    LL.to_csv(DEEP / "mech_lead_lag_sc100_20pct_falls.csv", index=False)
    return D, G, A, rl, LL


def main():
    N, W = build()
    cal, px, r, gc, sg = load()
    cal = cal[cal <= pd.Timestamp("2026-08-21")]
    L, T, X, F = part_regimes(N, W, px, sg, cal)
    D, G, A, rl, LL = part_mechanism(N, W, px, sg, cal, L)
    pd.set_option("display.width", 260); pd.set_option("display.max_columns", 40)
    t = T[(T.leg == "SC100") & (T.sleeve == "cash")][["sample", "labelling", "bucket", "weeks", "bh_ann", "pair_ann", "sc100_ann", "pair_minus_bh", "pair_minus_sc100", "pair_in_equity", "pair_minus_bh_logpts_per_yr_of_period", "pair_minus_sc100_logpts_per_yr_of_period"]]
    print(t.round(3).to_string(index=False))
    print(X[X["sample"] == "oos"].round(3).to_string(index=False))
    print(D[D.period.str.contains("oos|in-sample")].round(2).to_string(index=False))
    print(G.round(3).to_string(index=False))
    print(A[A["sub"].astype(str).str.contains("all oos|in-sample")].round(3).to_string(index=False))
    print(rl.to_string(index=False))
    print(LL.round(3).to_string(index=False))


if __name__ == "__main__":
    main()
