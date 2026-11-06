# -*- coding: utf-8 -*-
"""
Deep regimes, part 2: rule performance conditional on regimes.

Continuous whole-history return-space runs (why_n100sc100.run_rs, 20.8 bps a
switch, weekly decisions, trade at the close of the session after the
review, first earn the session after that):
  cash sleeve   2007-07-02 -> 2026-08-21
  50/50 sleeve  2014-07-07 -> 2026-08-21   (0.5 gold + 0.5 cash daily returns)
Legs: SC100, blend (equal-weight daily N100/MC100/SC100), N100 (main) and
MC100, N50 (appendix). Rules: bh, pair, triple, sc100, own.

Each session's return is put in a regime bucket:
  * ex-ante labels (R2-R6): the label at the review whose decision governs
    that session's weight (the "holding block" of the review);
  * hindsight phases (R1): the label of the week the session belongs to
    (sessions after review k-1 up to and including review k).
Per bucket: weeks, annualised return of each rule while in the bucket
(exp(sessions_per_year * mean log return) - 1, sessions_per_year from the
period itself, so the ALL bucket equals the period CAGR), the pair's gaps,
the bucket's contribution to the period's total log gap (pp/yr; buckets add
up to the total), time in equity, and a t-stat of the weekly log excess.

Writes evidence/why_n100sc100/deep/regimes_*.csv.
"""

from __future__ import annotations

import os

import numpy as np
import pandas as pd

import why_n100sc100 as W
from triple_and_test import index_levels
from deep_regimes_labels import build as build_labels

DEEP = W.OUT / "deep"
os.makedirs(DEEP, exist_ok=True)
END = pd.Timestamp("2026-08-21")
OOS_END = pd.Timestamp("2021-10-29")
IS_START = pd.Timestamp("2021-11-03")
RULES = ["bh", "pair", "triple", "sc100", "own"]
OWN = {"SC100": "SC100", "N100": "N100", "MC100": "MC100", "N50": "N50", "blend": None}
LEGS = ["SC100", "blend", "N100", "MC100", "N50"]
MAIN_LEGS = ["SC100", "blend", "N100"]
EXANTE = ["R2_trend", "R3_vol", "R4_lead", "R5_state", "R6_breadth"]
HINDSIGHT = ["R1_phase_SC100", "R1_phase_N100", "R1d_phase_SC100", "R1d_phase_N100"]


def decisions(s: pd.DataFrame, own: str | None) -> dict:
    need = ["N100", "MC100", "SC100"] + ([own] if own and own not in ("N100", "MC100", "SC100") else [])
    ss = s[need].dropna()
    d = {"bh": pd.Series(1.0, index=ss.index),
         "pair": ss["N100"] * ss["SC100"],
         "triple": ss["N100"] * ss["MC100"] * ss["SC100"],
         "sc100": ss["SC100"]}
    if own:
        d["own"] = ss[own]
    return d


def wk_mdd(nav: pd.Series) -> float:
    w = nav.resample("W-FRI").last().dropna()
    return float((w / w.cummax() - 1).min())


def main() -> None:
    cal = W.calendar()
    cal = cal[cal <= END]
    sg = W.weekly_signs()
    sg = sg[sg.index <= END]
    lv = index_levels(cal)
    gc = W.gold_cash(cal)
    lab, _ = build_labels()
    lab.to_csv(DEEP / "regimes_weekly_labels.csv")
    grid = lab.index                                         # weekly review grid

    runs = {"cash": (pd.Timestamp("2007-07-02"), END), "5050": (pd.Timestamp("2014-07-07"), END)}
    daily = {}                                               # (sleeve) -> DataFrame of daily returns/weights
    summ_rows = []
    for sl, (a, b) in runs.items():
        c = cal[(cal >= a) & (cal <= b)]
        rc = gc["cash"].reindex(c).pct_change()
        rg = gc["gold"].reindex(c).pct_change()
        r_sl = (rc if sl == "cash" else 0.5 * rg + 0.5 * rc).fillna(0.0)
        eq = {k: lv[k].reindex(c).pct_change() for k in ("SC100", "N100", "MC100", "N50")}
        eq["blend"] = (eq["N100"] + eq["MC100"] + eq["SC100"]) / 3
        s = sg.loc[(sg.index >= a - pd.Timedelta(days=7)) & (sg.index <= b)]
        cols = {"sleeve_r": r_sl}
        for leg in LEGS:
            r_eq = eq[leg].fillna(0.0)
            cols[f"{leg}|eq_r"] = r_eq
            for rn, dec in decisions(s, OWN[leg]).items():
                nav = W.run_rs(dec, r_eq, r_sl, c)
                r = nav.pct_change()
                r.iloc[0] = nav.iloc[0] - 1
                w = W.daily_weight(dec, c).reindex(c).ffill().fillna(1.0)
                cols[f"{leg}|{rn}|r"] = r
                cols[f"{leg}|{rn}|w"] = w
        df = pd.DataFrame(cols, index=c)
        daily[sl] = df
    # session -> governing review (ex-ante block) and -> week-ending review (hindsight week)
    for sl, df in daily.items():
        c = df.index
        gov = pd.Series(pd.NaT, index=c)
        for r in grid:
            j = cal.searchsorted(r, side="right")
            if j + 1 < len(cal) and cal[j + 1] in gov.index:
                gov.loc[cal[j + 1]] = r
        df["gov_review"] = gov.ffill()
        pos = grid.searchsorted(c, side="left")
        df["week_review"] = [grid[p] if p < len(grid) else pd.NaT for p in pos]

    for sl, df in daily.items():
        df.to_csv(DEEP / f"regimes_daily_{sl}.csv")
    periods = [("OOS 2007-07..2021-10", "cash", pd.Timestamp("2007-07-02"), OOS_END),
               ("OOS 2007-07..2014-06", "cash", pd.Timestamp("2007-07-02"), pd.Timestamp("2014-06-30")),
               ("OOS 2014-07..2021-10", "cash", pd.Timestamp("2014-07-07"), OOS_END),
               ("IS 2021-11..2026-08", "cash", IS_START, END),
               ("FULL 2007-07..2026-08 (mixes IS)", "cash", pd.Timestamp("2007-07-02"), END),
               ("OOS 2014-07..2021-10", "5050", pd.Timestamp("2014-07-07"), OOS_END),
               ("IS 2021-11..2026-08", "5050", IS_START, END)]

    # ── run summaries (CAGR, worst fall on daily and Friday closes) ────────
    for plab, sl, a, b in periods:
        df = daily[sl].loc[a:b]
        yrs = (df.index[-1] - df.index[0]).days / 365.25
        for leg in LEGS:
            for rn in RULES:
                if f"{leg}|{rn}|r" not in df:
                    continue
                r = df[f"{leg}|{rn}|r"].copy()
                r.iloc[0] = 0.0                              # start the period's NAV at 1
                nav = (1 + r).cumprod()
                w = df[f"{leg}|{rn}|w"]
                summ_rows.append({"period": plab, "sleeve": sl, "leg": leg, "rule": rn,
                                  "start": df.index[0].date(), "end": df.index[-1].date(),
                                  "cagr": float(nav.iloc[-1] ** (1 / yrs) - 1),
                                  "max_dd_daily": float((nav / nav.cummax() - 1).min()),
                                  "max_dd_friday": wk_mdd(nav),
                                  "time_in_equity": float(w.mean()),
                                  "switches": int((w.diff().abs() > 0).sum())})
    summ = pd.DataFrame(summ_rows)
    summ.to_csv(DEEP / "regimes_run_summary.csv", index=False)

    # ── consistency check against the reference table ──────────────────────
    ref = pd.read_csv(W.OUT / "triple_index_results.csv")
    chk = []
    refmap = {("2007-21, cash", "cash", "2007-07-02", OOS_END), ("2014-21, gold+cash", "5050", "2014-07-07", OOS_END),
              ("2021-26, cash (in-sample)", "cash", "2021-11-03", END),
              ("2021-26, gold+cash (in-sample)", "5050", "2021-11-03", END), ("2007-26 full, cash", "cash", "2007-07-02", END)}
    rname = {"bh": "buy & hold", "pair": "N100 AND SC100", "triple": "N100 AND MC100 AND SC100",
             "sc100": "SC100 only", "own": "own signal"}
    lname = {"SC100": "SC100", "N100": "N100", "MC100": "MC100", "N50": "N50", "blend": "blend N100/MC100/SC100"}
    for pl, sl, a, b in refmap:
        c = cal[(cal >= pd.Timestamp(a)) & (cal <= b)]
        rc = gc["cash"].reindex(c).pct_change()
        rg = gc["gold"].reindex(c).pct_change()
        r_sl = (rc if sl == "cash" else 0.5 * rg + 0.5 * rc).fillna(0.0)
        s = sg.loc[(sg.index >= pd.Timestamp(a) - pd.Timedelta(days=7)) & (sg.index <= b)]
        for leg in MAIN_LEGS:
            r_eq = (lv[leg].reindex(c).pct_change() if leg != "blend" else
                    (lv["N100"].reindex(c).pct_change() + lv["MC100"].reindex(c).pct_change()
                     + lv["SC100"].reindex(c).pct_change()) / 3).fillna(0.0)
            for rn, dec in decisions(s, OWN[leg]).items():
                nav = W.run_rs(dec, r_eq, r_sl, c)
                rr = ref[(ref.period == pl) & (ref.equity == lname[leg]) & (ref.rule == rname[rn])]
                cont = summ[(summ.sleeve == sl) & (summ.leg == leg) & (summ.rule == rn)
                            & (summ.start == c[0].date()) & (summ.end == c[-1].date())]
                chk.append({"ref_period": pl, "leg": leg, "rule": rn, "standalone_cagr": W.cagr(nav),
                            "standalone_mdd": W.mdd(nav),
                            "reference_cagr": float(rr.cagr.iloc[0]) if len(rr) else np.nan,
                            "reference_mdd": float(rr.max_dd.iloc[0]) if len(rr) else np.nan,
                            "continuous_slice_cagr": float(cont.cagr.iloc[0]) if len(cont) else np.nan})
    pd.DataFrame(chk).to_csv(DEEP / "regimes_check_vs_reference.csv", index=False)

    # ── bucket statistics ──────────────────────────────────────────────────
    rows = []
    for plab, sl, a, b in periods:
        df = daily[sl].loc[a:b].copy()
        n_all = len(df)
        yrs = (df.index[-1] - df.index[0]).days / 365.25
        spy = (n_all - 1) / yrs                               # sessions per year in this period
        df.iloc[0, [df.columns.get_loc(x) for x in df.columns if x.endswith("|r")]] = 0.0
        for labname in HINDSIGHT + EXANTE + ["ALL"]:
            if labname == "ALL":
                key = pd.Series("ALL", index=df.index)
                unit = df["gov_review"]
            else:
                ucol = "week_review" if labname in HINDSIGHT else "gov_review"
                unit = df[ucol]
                key = unit.map(lab[labname])
            for leg in LEGS:
                lr = {rn: np.log1p(df[f"{leg}|{rn}|r"]) for rn in RULES if f"{leg}|{rn}|r" in df}
                tot_bh = float((lr["pair"] - lr["bh"]).sum()) / yrs
                tot_sc = float((lr["pair"] - lr["sc100"]).sum()) / yrs
                for bk, idx in key.groupby(key).groups.items():
                    if bk is None or (isinstance(bk, float) and np.isnan(bk)):
                        continue
                    n = len(idx)
                    row = {"period": plab, "sleeve": sl, "leg": leg, "labelling": labname, "bucket": bk,
                           "weeks": int(unit.loc[idx].nunique()), "sessions": n,
                           "share_of_sessions": n / n_all}
                    for rn, x in lr.items():
                        row[f"ann_{rn}"] = float(np.expm1(spy * x.loc[idx].mean()))
                    row["ann_sleeve"] = float(np.expm1(spy * np.log1p(df.loc[idx, "sleeve_r"]).mean()))
                    for o in ("bh", "sc100", "triple", "own"):
                        if f"ann_{o}" in row:
                            row[f"pair_minus_{o}_pp"] = 100 * (row["ann_pair"] - row[f"ann_{o}"])
                    cb = float((lr["pair"] - lr["bh"]).loc[idx].sum()) / yrs
                    cs = float((lr["pair"] - lr["sc100"]).loc[idx].sum()) / yrs
                    row["contrib_pair_bh_logpp_yr"] = 100 * cb
                    row["contrib_pair_sc100_logpp_yr"] = 100 * cs
                    row["total_pair_bh_logpp_yr"] = 100 * tot_bh
                    row["total_pair_sc100_logpp_yr"] = 100 * tot_sc
                    for rn in RULES:
                        if f"{leg}|{rn}|w" in df:
                            row[f"tin_{rn}"] = float(df.loc[idx, f"{leg}|{rn}|w"].mean())
                    # weekly log-excess t-stats (unit = the labelling's week)
                    u = unit.loc[idx]
                    for o in ("bh", "sc100"):
                        ex = (lr["pair"] - lr[o]).loc[idx].groupby(u).sum()
                        sd = ex.std()
                        row[f"t_pair_{o}"] = float(ex.mean() / (sd / np.sqrt(len(ex)))) if len(ex) > 2 and sd > 0 else np.nan
                        row[f"weeks_pair_beats_{o}"] = float((ex > 1e-12).mean())
                        row[f"weeks_differ_{o}"] = int((ex.abs() > 1e-12).sum())
                    rows.append(row)
    bk = pd.DataFrame(rows)
    bk.to_csv(DEEP / "regimes_bucket_stats.csv", index=False)
    print("buckets done", flush=True)

    # ── hindsight episodes: each rule through each decline and recovery ────
    ep = pd.read_csv(DEEP / "regimes_phase_episodes.csv", parse_dates=["peak", "trough", "recovered"])
    erows = []
    for sl in ("cash", "5050"):
        df = daily[sl]
        for _, e in ep.iterrows():
            for part, a, b in (("decline", e.peak, e.trough),
                               ("recovery", e.trough, e.recovered if pd.notna(e.recovered) else END)):
                seg = df[(df.index > a) & (df.index <= b)]
                if len(seg) < 3:
                    continue
                for leg in MAIN_LEGS:
                    row = {"sleeve": sl, "phase_index": e["index"], "level": e.level, "kind": e.kind,
                           "peak": e.peak.date(), "trough": e.trough.date(),
                           "recovered": e.recovered.date() if pd.notna(e.recovered) else None,
                           "depth": e.depth, "part": part, "from": seg.index[0].date(), "to": seg.index[-1].date(),
                           "clipped_start": bool(a < df.index[0]), "leg": leg, "sessions": len(seg),
                           "out_of_sample": bool(seg.index[-1] <= OOS_END),
                           "in_sample": bool(seg.index[0] >= IS_START)}
                    for rn in RULES:
                        if f"{leg}|{rn}|r" not in seg:
                            continue
                        nav = (1 + seg[f"{leg}|{rn}|r"]).cumprod()
                        nav0 = pd.concat([pd.Series([1.0], index=[seg.index[0] - pd.Timedelta(days=1)]), nav])
                        row[f"ret_{rn}"] = float(nav.iloc[-1] - 1)
                        row[f"dd_daily_{rn}"] = float((nav0 / nav0.cummax() - 1).min())
                        row[f"dd_friday_{rn}"] = wk_mdd(nav0)
                        row[f"tin_{rn}"] = float(seg[f"{leg}|{rn}|w"].mean())
                    row["ret_sleeve"] = float((1 + seg["sleeve_r"]).prod() - 1)
                    erows.append(row)
    epi = pd.DataFrame(erows)
    epi["pair_minus_bh_pp"] = 100 * (epi["ret_pair"] - epi["ret_bh"])
    epi["pair_minus_sc100_pp"] = 100 * (epi["ret_pair"] - epi["ret_sc100"])
    epi.to_csv(DEEP / "regimes_episode_rules.csv", index=False)
    print("episodes done", flush=True)

    # ── forward returns by state x regime ──────────────────────────────────
    close = lv[["SC100", "N100"]].copy()
    close["cash"] = gc["cash"]
    frows = []
    rv = grid[(grid >= pd.Timestamp("2007-06-29")) & (grid <= END)]
    last = cal.get_loc(cal[cal <= END][-1])
    for r in rv:
        j = cal.searchsorted(r, side="right")
        row = {"review": r, "entry": cal[j] if j <= last else pd.NaT}
        for h, hl in ((20, "4w"), (65, "13w")):
            for k in ("SC100", "N100", "cash"):
                row[f"{k}_{hl}"] = (float(close[k].iloc[j + h] / close[k].iloc[j] - 1)
                                    if j + h <= last and pd.notna(close[k].iloc[j]) else np.nan)
        frows.append(row)
    fw = pd.DataFrame(frows).set_index("review")
    fw = fw.join(lab[HINDSIGHT + EXANTE])
    fw["pos"] = np.arange(len(fw))
    fw["sample"] = np.where(fw.index <= OOS_END, "OOS", "IS")
    fw.to_csv(DEEP / "regimes_forward_weekly.csv")

    def nonoverlap(p: np.ndarray, h: int) -> int:
        cnt, lastp = 0, -10 ** 9
        for x in p:
            if x - lastp >= h:
                cnt += 1
                lastp = x
        return cnt

    crows = []
    for samp in ("OOS", "IS"):
        f = fw[fw["sample"] == samp]
        for other in ["R1_phase_SC100", "R1_phase_N100", "R1d_phase_SC100", "R2_trend", "R3_vol", "R4_lead", "R6_breadth", "ALL"]:
            o = pd.Series("ALL", index=f.index) if other == "ALL" else f[other]
            for (st, ob), g in f.groupby([f["R5_state"], o]):
                row = {"sample": samp, "cross": f"R5_state x {other}", "state": st, "regime": ob,
                       "weeks": len(g)}
                for hl, h in (("4w", 4), ("13w", 13)):
                    for k in ("SC100", "N100", "cash"):
                        x = g[f"{k}_{hl}"].dropna()
                        row[f"{k}_{hl}_mean"] = float(x.mean()) if len(x) else np.nan
                        if k != "cash":
                            row[f"{k}_{hl}_median"] = float(x.median()) if len(x) else np.nan
                            row[f"{k}_{hl}_pos"] = float((x > 0).mean()) if len(x) else np.nan
                            row[f"{k}_{hl}_beats_cash"] = float((x > g.loc[x.index, f"cash_{hl}"]).mean()) if len(x) else np.nan
                    row[f"n_{hl}"] = int(g[f"SC100_{hl}"].notna().sum())
                    row[f"n_nonoverlap_{hl}"] = nonoverlap(g.loc[g[f"SC100_{hl}"].notna(), "pos"].to_numpy(), h)
                crows.append(row)
            # the state alone, across all regimes of this cross, is the "ALL" cross
    ct = pd.DataFrame(crows)
    ct.to_csv(DEEP / "regimes_state_crosstab_forward.csv", index=False)
    print("crosstabs done", flush=True)

    # ── ex-ante gated diagnostic (NOT a proposed rule) ──────────────────────
    # The pair only when an ex-ante condition holds, otherwise buy-and-hold;
    # and the reverse. Shows whether the pair's cost in "calm" regimes is the
    # price of its protection.
    grows = []
    for sl, (a, b) in runs.items():
        c = cal[(cal >= a) & (cal <= b)]
        rc = gc["cash"].reindex(c).pct_change()
        rg = gc["gold"].reindex(c).pct_change()
        r_sl = (rc if sl == "cash" else 0.5 * rg + 0.5 * rc).fillna(0.0)
        s = sg.loc[(sg.index >= a - pd.Timedelta(days=7)) & (sg.index <= b)]
        L = lab.reindex(s.index)
        pair = (s["N100"] * s["SC100"]).dropna()
        gates = {"pair (reference)": pair,
                 "bh (reference)": pd.Series(1.0, index=pair.index),
                 "pair only when below 40w MA, else bh": pair.where(L.loc[pair.index, "R2_trend"] == "below 40w MA", 1.0),
                 "pair only when above 40w MA, else bh": pair.where(L.loc[pair.index, "R2_trend"] == "above 40w MA", 1.0),
                 "pair only when high vol, else bh": pair.where(L.loc[pair.index, "R3_vol"] == "high vol", 1.0),
                 "pair except when high vol (bh then)": pair.where(L.loc[pair.index, "R3_vol"] != "high vol", 1.0),
                 "pair only when large-led, else bh": pair.where(L.loc[pair.index, "R4_lead"] == "large-led", 1.0),
                 "pair except when small-led (bh then)": pair.where(L.loc[pair.index, "R4_lead"] != "small-led", 1.0)}
        for leg in MAIN_LEGS:
            r_eq = (lv[leg].reindex(c).pct_change() if leg != "blend" else
                    (lv["N100"].reindex(c).pct_change() + lv["MC100"].reindex(c).pct_change()
                     + lv["SC100"].reindex(c).pct_change()) / 3).fillna(0.0)
            for gname, dec in gates.items():
                nav = W.run_rs(dec, r_eq, r_sl, c)
                w = W.daily_weight(dec, c).reindex(c).ffill().fillna(1.0)
                for plab, pa, pb in (("OOS", a, OOS_END), ("IS", IS_START, END)):
                    n = nav.loc[pa:pb]
                    n = n / n.iloc[0]
                    grows.append({"sleeve": sl, "sample": plab, "start": n.index[0].date(), "end": n.index[-1].date(),
                                  "leg": leg, "variant": gname, "cagr": W.cagr(n), "max_dd_daily": W.mdd(n),
                                  "max_dd_friday": wk_mdd(n), "time_in_equity": float(w.loc[pa:pb].mean())})
    pd.DataFrame(grows).to_csv(DEEP / "regimes_gated_diagnostic.csv", index=False)
    print("gated done", flush=True)


if __name__ == "__main__":
    main()
