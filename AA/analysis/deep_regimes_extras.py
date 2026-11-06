# -*- coding: utf-8 -*-
"""
Deep regimes, part 3: timelines, years, state stretches, edge ledger and the
ex-ante consistency test. Reads the daily frames and bucket stats written by
deep_regimes_buckets.py (run that first).

  regimes_timeline_segments.csv   every contiguous run of one hindsight SC100
                                  (and N100) phase label, 2007-07 -> 2026-08:
                                  what each rule earned in it (cash sleeve,
                                  and 50/50 where gold exists).
  regimes_by_year.csv             calendar-year returns per leg and rule, with
                                  the share of weeks in each hindsight phase
                                  and below the 40w MA.
  regimes_state_stretches.csv     every contiguous run of one R5 signal state,
                                  with the equity and cash returns over the
                                  sessions its decisions governed.
  regimes_edge_ledger.csv         the pair's total log gap vs bh and vs sc100,
                                  split by R1 phase and by R5 state, per period.
  regimes_exante_consistency.csv  sign of each ex-ante bucket's contribution
                                  across 2007-14, 2014-21 and 2021-26, 3 legs.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

import why_n100sc100 as W

DEEP = W.OUT / "deep"
OOS_END = pd.Timestamp("2021-10-29")
IS_START = pd.Timestamp("2021-11-03")
END = pd.Timestamp("2026-08-21")
LEGS = ["SC100", "blend", "N100"]
RULES = ["bh", "pair", "triple", "sc100", "own"]


def load_daily(sl: str) -> pd.DataFrame:
    d = pd.read_csv(DEEP / f"regimes_daily_{sl}.csv", index_col=0, parse_dates=True)
    d["gov_review"] = pd.to_datetime(d["gov_review"])
    d["week_review"] = pd.to_datetime(d["week_review"])
    return d


def seg_stats(seg: pd.DataFrame, leg: str) -> dict:
    out = {}
    for rn in RULES:
        c = f"{leg}|{rn}|r"
        if c not in seg:
            continue
        nav = (1 + seg[c]).cumprod()
        nav0 = pd.concat([pd.Series([1.0], index=[seg.index[0] - pd.Timedelta(days=1)]), nav])
        out[f"ret_{rn}"] = float(nav.iloc[-1] - 1)
        out[f"dd_daily_{rn}"] = float((nav0 / nav0.cummax() - 1).min())
        w = nav0.resample("W-FRI").last().dropna()
        out[f"dd_friday_{rn}"] = float((w / w.cummax() - 1).min())
        out[f"tin_{rn}"] = float(seg[f"{leg}|{rn}|w"].mean())
    out["ret_sleeve"] = float((1 + seg["sleeve_r"]).prod() - 1)
    return out


def sample_tag(a, b) -> str:
    if b <= OOS_END:
        return "OOS"
    if a >= IS_START - pd.Timedelta(days=3):
        return "IS"
    return "straddles"


def main() -> None:
    lab = pd.read_csv(DEEP / "regimes_weekly_labels.csv", index_col=0, parse_dates=True)
    dly = {sl: load_daily(sl) for sl in ("cash", "5050")}
    grid = lab.index

    # ── 1. timeline segments of hindsight phases ───────────────────────────
    trows = []
    for ph in ("R1_phase_SC100", "R1_phase_N100", "R1d_phase_SC100"):
        L = lab.loc[(lab.index >= "2007-07-06") & (lab.index <= END), ph]
        run_id = (L != L.shift()).cumsum()
        for _, g in L.groupby(run_id):
            revs = g.index
            for sl, d in dly.items():
                seg = d[d["week_review"].isin(revs)]
                if len(seg) < 2:
                    continue
                for leg in LEGS:
                    row = {"phase_labelling": ph, "sleeve": sl, "leg": leg, "phase": g.iloc[0],
                           "first_week": revs[0].date(), "last_week": revs[-1].date(), "weeks": len(revs),
                           "from": seg.index[0].date(), "to": seg.index[-1].date(),
                           "sample": sample_tag(seg.index[0], seg.index[-1]),
                           "clipped": bool(sl == "5050" and revs[0] < pd.Timestamp("2014-07-11"))}
                    row.update(seg_stats(seg, leg))
                    trows.append(row)
    tl = pd.DataFrame(trows)
    tl["pair_minus_bh_pp"] = 100 * (tl["ret_pair"] - tl["ret_bh"])
    tl["pair_minus_sc100_pp"] = 100 * (tl["ret_pair"] - tl["ret_sc100"])
    tl.to_csv(DEEP / "regimes_timeline_segments.csv", index=False)

    # ── 2. calendar years ──────────────────────────────────────────────────
    yrows = []
    for sl, d in dly.items():
        for y, seg in d.groupby(d.index.year):
            if y > 2026:
                continue
            # the year's return starts from the previous year's last close
            wk = lab.loc[(lab.index.year == y) & (lab.index >= d.index[0]) & (lab.index <= END)]
            for leg in LEGS:
                row = {"sleeve": sl, "year": int(y), "leg": leg, "from": seg.index[0].date(), "to": seg.index[-1].date(),
                       "partial": bool(seg.index[0].month > 1 or seg.index[0].day > 7 or y == 2026),
                       "sample": sample_tag(seg.index[0], seg.index[-1])}
                row.update(seg_stats(seg, leg))
                for ph in ("bear", "correction", "recovery", "bull"):
                    row[f"share_weeks_SC100_{ph}"] = float((wk["R1_phase_SC100"] == ph).mean()) if len(wk) else np.nan
                row["share_weeks_below_40wMA"] = float((wk["R2_trend"] == "below 40w MA").mean()) if len(wk) else np.nan
                row["share_weeks_high_vol"] = float((wk["R3_vol"] == "high vol").mean()) if len(wk) else np.nan
                yrows.append(row)
    yr = pd.DataFrame(yrows)
    yr["pair_minus_bh_pp"] = 100 * (yr["ret_pair"] - yr["ret_bh"])
    yr["pair_minus_sc100_pp"] = 100 * (yr["ret_pair"] - yr["ret_sc100"])
    yr["pair_minus_triple_pp"] = 100 * (yr["ret_pair"] - yr["ret_triple"])
    yr.to_csv(DEEP / "regimes_by_year.csv", index=False)

    # ── 3. R5 state stretches ──────────────────────────────────────────────
    d = dly["cash"]
    S = lab.loc[(lab.index >= "2007-06-29") & (lab.index <= END), "R5_state"]
    run_id = (S != S.shift()).cumsum()
    srows = []
    prev_state = S.shift()
    next_state = S.shift(-1)
    for _, g in S.groupby(run_id):
        revs = g.index
        seg = d[d["gov_review"].isin(revs)]
        if len(seg) == 0:
            continue
        r0 = revs[0]
        row = {"state": g.iloc[0], "first_review": r0.date(), "last_review": revs[-1].date(), "weeks": len(revs),
               "from_state": prev_state.loc[r0], "to_state": next_state.loc[revs[-1]],
               "phase_SC100_at_start (hindsight)": lab.loc[r0, "R1_phase_SC100"],
               "phase_N100_at_start (hindsight)": lab.loc[r0, "R1_phase_N100"],
               "trend_at_start": lab.loc[r0, "R2_trend"], "vol_at_start": lab.loc[r0, "R3_vol"],
               "lead_at_start": lab.loc[r0, "R4_lead"],
               "earn_from": seg.index[0].date(), "earn_to": seg.index[-1].date(),
               "sample": sample_tag(seg.index[0], seg.index[-1])}
        for leg in LEGS:
            row[f"{leg}_return"] = float((1 + seg[f"{leg}|eq_r"]).prod() - 1)
        row["cash_return"] = float((1 + seg["sleeve_r"]).prod() - 1)
        # log contribution of the stretch to pair - bh and pair - sc100 (SC100 leg, cash), in log pp
        for leg in LEGS:
            row[f"{leg}_logpp_pair_minus_bh"] = 100 * float((np.log1p(seg[f"{leg}|pair|r"]) - np.log1p(seg[f"{leg}|bh|r"])).sum())
            row[f"{leg}_logpp_pair_minus_sc100"] = 100 * float((np.log1p(seg[f"{leg}|pair|r"]) - np.log1p(seg[f"{leg}|sc100|r"])).sum())
        srows.append(row)
    st = pd.DataFrame(srows)
    st.to_csv(DEEP / "regimes_state_stretches.csv", index=False)

    # ── 4. edge ledger ─────────────────────────────────────────────────────
    bk = pd.read_csv(DEEP / "regimes_bucket_stats.csv")
    led = bk[bk.leg.isin(LEGS) & bk.labelling.isin(["R1_phase_SC100", "R1d_phase_SC100", "R1_phase_N100", "R5_state", "ALL"])]
    led = led[["period", "sleeve", "leg", "labelling", "bucket", "weeks", "tin_pair", "ann_bh", "ann_pair", "ann_sc100",
               "contrib_pair_bh_logpp_yr", "contrib_pair_sc100_logpp_yr", "total_pair_bh_logpp_yr",
               "total_pair_sc100_logpp_yr", "t_pair_bh", "t_pair_sc100"]]
    led.to_csv(DEEP / "regimes_edge_ledger.csv", index=False)

    # ── 5. ex-ante consistency across sub-periods and legs ─────────────────
    per = [("OOS 2007-07..2014-06", "cash"), ("OOS 2014-07..2021-10", "cash"), ("IS 2021-11..2026-08", "cash"),
           ("OOS 2014-07..2021-10", "5050"), ("IS 2021-11..2026-08", "5050")]
    crows = []
    for labn in ["R2_trend", "R3_vol", "R4_lead", "R5_state", "R6_breadth", "R1_phase_SC100", "R1_phase_N100"]:
        x = bk[(bk.labelling == labn) & bk.leg.isin(LEGS)]
        for b in sorted(x.bucket.unique()):
            row = {"labelling": labn, "bucket": b, "hindsight": labn.startswith("R1")}
            oos_signs, all_signs = [], []
            for p, sl in per:
                for leg in LEGS:
                    y = x[(x.period == p) & (x.sleeve == sl) & (x.leg == leg) & (x.bucket == b)]
                    v = float(y.contrib_pair_bh_logpp_yr.iloc[0]) if len(y) else np.nan
                    dv = float(y.pair_minus_bh_pp.iloc[0]) if len(y) else np.nan
                    wk = int(y.weeks.iloc[0]) if len(y) else 0
                    row[f"{p}|{sl}|{leg}|contrib_bh"] = v
                    row[f"{p}|{sl}|{leg}|ann_diff_bh"] = dv
                    row[f"{p}|{sl}|{leg}|weeks"] = wk
                    if sl == "cash" and not np.isnan(v):
                        all_signs.append(np.sign(v))
                        if p.startswith("OOS"):
                            oos_signs.append(np.sign(v))
            row["cash_cells"] = len(all_signs)
            row["cash_cells_positive"] = int(sum(s > 0 for s in all_signs))
            row["cash_oos_cells_positive"] = int(sum(s > 0 for s in oos_signs))
            row["cash_oos_cells"] = len(oos_signs)
            crows.append(row)
    pd.DataFrame(crows).to_csv(DEEP / "regimes_exante_consistency.csv", index=False)

    # ── 6. scorecards: phase segments and calendar years ───────────────────
    TIE = 0.5                                                 # |pair - bh| <= 0.5 pp counts as a tie
    sc_rows = []
    for (phl, sl, leg), g0 in tl[tl.phase_labelling.isin(["R1_phase_SC100", "R1_phase_N100"])].groupby(
            ["phase_labelling", "sleeve", "leg"]):
        for grp, g1 in (("OOS", g0[g0["sample"] == "OOS"]), ("IS", g0[g0["sample"] == "IS"]), ("all (incl. straddles)", g0)):
            for ph, g in g1.groupby("phase"):
                d_ = g["pair_minus_bh_pp"]
                e_ = g["pair_minus_sc100_pp"]
                sc_rows.append({"phase_labelling": phl, "sleeve": sl, "leg": leg, "sample": grp, "phase": ph,
                                "segments": len(g), "weeks": int(g["weeks"].sum()),
                                "pair_beats_bh": int((d_ > TIE).sum()), "ties_bh": int((d_.abs() <= TIE).sum()),
                                "pair_behind_bh": int((d_ < -TIE).sum()),
                                "median_pair_minus_bh_pp": float(d_.median()), "mean_pair_minus_bh_pp": float(d_.mean()),
                                "pair_beats_sc100": int((e_ > TIE).sum()), "pair_behind_sc100": int((e_ < -TIE).sum()),
                                "sum_pair_minus_sc100_pp": float(e_.sum()),
                                "median_tin_pair": float(g["tin_pair"].median()),
                                "worst_dd_daily_pair": float(g["dd_daily_pair"].min()),
                                "worst_dd_daily_bh": float(g["dd_daily_bh"].min()),
                                "worst_dd_friday_pair": float(g["dd_friday_pair"].min()),
                                "worst_dd_friday_bh": float(g["dd_friday_bh"].min())})
    pd.DataFrame(sc_rows).to_csv(DEEP / "regimes_timeline_scorecard.csv", index=False)

    y2 = yr.copy()
    y2["bh_bucket"] = pd.cut(y2["ret_bh"], [-10, 0, 0.30, 10], labels=["bh < 0", "bh 0 to +30%", "bh > +30%"])
    yrows2 = []
    for (sl, leg), g0 in y2.groupby(["sleeve", "leg"]):
        for scope, g1 in (("all years", g0), ("full years only", g0[~g0["partial"]])):
            for bb, g in g1.groupby("bh_bucket", observed=True):
                d_ = g["pair_minus_bh_pp"]
                yrows2.append({"sleeve": sl, "leg": leg, "scope": scope, "bh_bucket": bb, "years": len(g),
                               "year_list": " ".join(str(v) for v in g["year"]),
                               "pair_beats_bh": int((d_ > TIE).sum()), "pair_behind_bh": int((d_ < -TIE).sum()),
                               "mean_pair_minus_bh_pp": float(d_.mean()), "min_pair_minus_bh_pp": float(d_.min()),
                               "max_pair_minus_bh_pp": float(d_.max()),
                               "mean_ret_bh": float(g["ret_bh"].mean()), "mean_ret_pair": float(g["ret_pair"].mean()),
                               "mean_pair_minus_sc100_pp": float(g["pair_minus_sc100_pp"].mean())})
    pd.DataFrame(yrows2).to_csv(DEEP / "regimes_year_scorecard.csv", index=False)

    # ── 7. weekly up / down capture (no regime labels needed) ──────────────
    cap = []
    per2 = [("OOS 2007-07..2014-06", "cash", "2007-07-02", "2014-06-30"),
            ("OOS 2014-07..2021-10", "cash", "2014-07-07", "2021-10-29"),
            ("OOS 2007-07..2021-10", "cash", "2007-07-02", "2021-10-29"),
            ("IS 2021-11..2026-08", "cash", "2021-11-03", "2026-08-21"),
            ("OOS 2014-07..2021-10", "5050", "2014-07-07", "2021-10-29"),
            ("IS 2021-11..2026-08", "5050", "2021-11-03", "2026-08-21")]
    for plab, sl, a, b in per2:
        d = dly[sl].loc[a:b]
        for leg in LEGS:
            wk = {rn: (1 + d[f"{leg}|{rn}|r"]).groupby(d["week_review"]).prod() - 1
                  for rn in RULES if f"{leg}|{rn}|r" in d}
            bh = wk["bh"]
            up, dn = bh > 0, bh < 0
            big_dn = bh <= bh.quantile(0.10)
            for rn in [r for r in RULES if r in wk and r != "bh"]:
                x = wk[rn]
                cap.append({"period": plab, "sleeve": sl, "leg": leg, "rule": rn, "weeks": len(bh),
                            "up_weeks": int(up.sum()), "down_weeks": int(dn.sum()),
                            "up_capture": float(x[up].mean() / bh[up].mean()),
                            "down_capture": float(x[dn].mean() / bh[dn].mean()),
                            "worst10pct_weeks": int(big_dn.sum()),
                            "worst10pct_bh_mean": float(bh[big_dn].mean()),
                            "worst10pct_rule_mean": float(x[big_dn].mean()),
                            "worst10pct_capture": float(x[big_dn].mean() / bh[big_dn].mean())})
    pd.DataFrame(cap).to_csv(DEEP / "regimes_capture.csv", index=False)

    # ── 8. full cycles: each top-level 10%+ decline plus its whole recovery,
    #       and the "bull" stretches between cycles (hindsight partition) ──
    ep = pd.read_csv(DEEP / "regimes_phase_episodes.csv", parse_dates=["peak", "trough", "recovered"])
    cyc = []
    for idx in ("SC100", "N100"):
        e0 = ep[(ep["index"] == idx) & (ep["level"] == 0)].sort_values("peak")
        wins = []
        for _, e in e0.iterrows():
            b = e.recovered if pd.notna(e.recovered) else END
            wins.append(("cycle: " + e.kind, e.peak, e.trough, b, e.depth))
        # bull stretches = gaps between cycles
        allw = []
        start = pd.Timestamp("2007-06-29")
        for w in wins:
            if w[3] <= start:
                continue
            if w[1] > start:
                allw.append(("bull stretch", start, None, w[1], np.nan))
            allw.append(w)
            start = max(start, w[3])
        if start < END:
            allw.append(("bull stretch", start, None, END, np.nan))
        for sl, d in dly.items():
            for kind, a, t, b, depth in allw:
                seg = d[(d["week_review"] > a) & (d["week_review"] <= b)]
                if len(seg) < 3:
                    continue
                for leg in LEGS:
                    row = {"phase_index": idx, "sleeve": sl, "leg": leg, "kind": kind, "start_after": a.date(),
                           "trough": t.date() if t is not None else None, "end": b.date(), "depth": depth,
                           "from": seg.index[0].date(), "to": seg.index[-1].date(),
                           "clipped": bool(seg.index[0] > a + pd.Timedelta(days=10)),
                           "sample": sample_tag(seg.index[0], seg.index[-1]), "sessions": len(seg)}
                    row.update(seg_stats(seg, leg))
                    cyc.append(row)
    cy = pd.DataFrame(cyc)
    cy["pair_minus_bh_pp"] = 100 * (cy["ret_pair"] - cy["ret_bh"])
    cy["pair_minus_sc100_pp"] = 100 * (cy["ret_pair"] - cy["ret_sc100"])
    cy.to_csv(DEEP / "regimes_cycles.csv", index=False)
    print("extras done")


if __name__ == "__main__":
    main()
