# -*- coding: utf-8 -*-
"""
Deep dive: the defensive sleeve and gold, 2014-07 -> 2026-08, for the pair
rule (N100 AND SC100), with SC100-only and buy-and-hold alongside.

  1. Per calendar year (2021 split at the in-sample boundary): pair on SC100,
     the N100/MC100/SC100 blend and the 4-book average portfolio, with the
     cash, 50/50 and gold sleeves. Return, worst fall (daily and Friday closes),
     and sleeve contributions.
  2. Every defensive spell of the pair: dates, weeks, SC100 / blend / gold /
     cash over the spell; gold vs cash hit rate by sample.
  3. Gold as a crisis hedge: every SC100 decline >= 10% (Friday closes, a 10%
     zig-zag and, separately, peak-to-recovery episodes); weekly gold/SC100
     correlation in the pair's defensive vs equity weeks.
  4. Excess over buy-and-hold split into equity timing (pair(cash) - bh) and
     the sleeve (pair(50/50) - pair(cash)); per year and per period.
  5. Daily re-mixed 50/50 sleeve (the index engine) vs a drifting 50/50 sleeve.
  6. Gold-rally dependence: counterfactual sleeves (gold = cash, gold flat,
     gold at a steady drift, gold falling) and leave-the-best-spell-out.

Outputs: evidence/why_n100sc100/deep/sleeve_*.csv
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from deep_sleeve_common import (COST, DEEP, END, EQUITY_LEGS, IS_START, OOS_END, OWN, PERIODS, SEGMENTS, W14,
                                cagr, drift_sleeve, equity_returns, fri, load, mdd, mdd_fri, rules, run_rs,
                                seg_stats, sleeve_returns, spells, weight, window)
from why_n100sc100 import OUT

SLEEVES = ("cash", "5050", "gold")
BOOKS = ["SCMO_0042", "SCMO_0043", "SCMO_0044", "SCMO_0045"]
PORT_RULE = {"pair": "N100 AND SC100", "sc100": "SC100 only", "triple": "N100 AND MC100 AND SC100"}
PORT_SLEEVE = {"cash": "cash", "5050": "gold+cash", "gold": "gold"}
IS_SPELL_FROM = pd.Timestamp("2021-11-01")   # a spell starting on or after this is in-sample


def dd_dates(nav: pd.Series):
    n = nav.dropna()
    dd = n / n.cummax() - 1
    t = dd.idxmin()
    return n.loc[:t].idxmax().date(), t.date()


def sample_of(d: pd.Timestamp) -> str:
    return "IS" if d >= IS_SPELL_FROM else "OOS"


def main() -> None:
    cal, sg, lv, gc = load()

    # ── Continuous 2014-26 runs (for years, spells, declines) ──────────────
    cc, ss = window(cal, sg, W14, END)
    req = equity_returns(lv, cc)
    rsl = sleeve_returns(gc, cc)
    dec = rules(ss, "SC100")
    w_pair = weight(dec["pair"], cc)
    w_sc = weight(dec["sc100"], cc)
    navs = {}
    for leg in ("SC100", "blend"):
        for rn in ("pair", "sc100"):
            for sl in SLEEVES:
                navs[(leg, rn, sl)] = run_rs(dec[rn], req[leg], rsl[sl], cc)
        navs[(leg, "bh", "-")] = run_rs(dec["bh"], req[leg], rsl["cash"], cc)
    gold_nav = gc["gold"].reindex(cc) / gc["gold"].reindex(cc).iloc[0]
    cash_nav = gc["cash"].reindex(cc) / gc["cash"].reindex(cc).iloc[0]
    blend_lvl = (1 + req["blend"]).cumprod()

    # ── Portfolios (4 books), from triple_portfolio_curves.csv ─────────────
    pc = pd.read_csv(OUT / "triple_portfolio_curves.csv", index_col=0, parse_dates=True)
    pc = pc[pc.index <= END]

    def book_nav(sample: str, book: str, rn: str, sl: str) -> pd.Series:
        pre = "oos" if sample == "OOS" else "in-sample"
        col = f"{pre}|{book}|parent|gold+cash" if rn == "bh" else f"{pre}|{book}|{PORT_RULE[rn]}|{PORT_SLEEVE[sl]}"
        return pc[col].dropna()

    # ════════════════════════════════════════════════════════════════════════
    # 1. Per calendar year
    # ════════════════════════════════════════════════════════════════════════
    long = []
    for seg, smp, a, e in SEGMENTS:
        in_seg = (cc >= a) & (cc <= e)
        tis = float((w_pair[in_seg] == 0).mean()) if in_seg.any() else np.nan
        sw = int((dec["pair"].loc[(dec["pair"].index >= a - pd.Timedelta(days=3)) &
                                  (dec["pair"].index <= e)].diff().abs() > 0).sum())
        ctx = {"segment": seg, "sample": smp, "pair_time_in_sleeve": tis, "pair_switch_reviews": sw,
               "gold_ret": seg_stats(gold_nav, a, e)["ret"], "cash_ret": seg_stats(cash_nav, a, e)["ret"],
               "gold_dd_daily": seg_stats(gold_nav, a, e)["dd_daily"],
               "gold_dd_fri": seg_stats(gold_nav, a, e)["dd_fri"],
               "sc100_index_ret": seg_stats(navs[("SC100", "bh", "-")], a, e)["ret"]}
        for (leg, rn, sl), nv in navs.items():
            long.append({**ctx, "leg": leg, "rule": rn, "sleeve": sl, **seg_stats(nv, a, e)})
        # portfolios: per book, then the average of the 4 books
        for rn, sls in (("pair", SLEEVES), ("sc100", SLEEVES), ("bh", ("-",))):
            per = []
            for b in BOOKS:
                for sl in sls:
                    s_ = seg_stats(book_nav(smp, b, rn, "5050" if sl == "-" else sl), a, e)
                    long.append({**ctx, "leg": f"book {b}", "rule": rn, "sleeve": sl, **s_})
                    per.append({"sleeve": sl, **s_})
            pdf = pd.DataFrame(per).groupby("sleeve")[["ret", "dd_daily", "dd_fri"]].mean()
            for sl, r_ in pdf.iterrows():
                long.append({**ctx, "leg": "4-book avg", "rule": rn, "sleeve": sl, **r_.to_dict()})
    yl = pd.DataFrame(long)
    yl.to_csv(DEEP / "sleeve_yearly_long.csv", index=False)

    # wide table per leg and segment
    rows = []
    for (leg, seg), g in yl[yl["leg"].isin(["SC100", "blend", "4-book avg"])].groupby(["leg", "segment"], sort=False):
        k = {(r.rule, r.sleeve): r for r in g.itertuples()}
        f = g.iloc[0]
        row = {"leg": leg, "segment": seg, "sample": f["sample"], "pair_time_in_sleeve": f["pair_time_in_sleeve"],
               "pair_switch_reviews": f["pair_switch_reviews"], "gold_ret": f["gold_ret"], "cash_ret": f["cash_ret"],
               "sc100_index_ret": f["sc100_index_ret"], "gold_dd_daily": f["gold_dd_daily"],
               "gold_dd_fri": f["gold_dd_fri"],
               "bh_ret": k[("bh", "-")].ret, "bh_dd_daily": k[("bh", "-")].dd_daily, "bh_dd_fri": k[("bh", "-")].dd_fri}
        for sl in SLEEVES:
            row[f"pair_{sl}_ret"] = k[("pair", sl)].ret
            row[f"pair_{sl}_dd_daily"] = k[("pair", sl)].dd_daily
            row[f"pair_{sl}_dd_fri"] = k[("pair", sl)].dd_fri
            row[f"sc100_{sl}_ret"] = k[("sc100", sl)].ret
        row["lift_5050_minus_cash"] = row["pair_5050_ret"] - row["pair_cash_ret"]
        row["lift_gold_minus_5050"] = row["pair_gold_ret"] - row["pair_5050_ret"]
        row["timing_paircash_minus_bh"] = row["pair_cash_ret"] - row["bh_ret"]
        row["total_pair5050_minus_bh"] = row["pair_5050_ret"] - row["bh_ret"]
        row["dd_change_5050_vs_cash_daily"] = row["pair_5050_dd_daily"] - row["pair_cash_dd_daily"]
        row["dd_change_5050_vs_cash_fri"] = row["pair_5050_dd_fri"] - row["pair_cash_dd_fri"]
        rows.append(row)
    yw = pd.DataFrame(rows)
    yw.to_csv(DEEP / "sleeve_yearly_table.csv", index=False)

    # Ex-post regime summary of the per-year sleeve contribution (hindsight labels).
    reg = []
    for leg, g in yw.groupby("leg", sort=False):
        full = g[~g["segment"].isin(["2014", "2021 Jan-Oct", "2021 Nov-Dec", "2026 to Aug-21"])]  # whole calendar years only
        labels = {
            "all segments": g,
            "full calendar years only": full,
            "ex-post: gold beat cash": g[g["gold_ret"] > g["cash_ret"]],
            "ex-post: gold lagged cash": g[g["gold_ret"] <= g["cash_ret"]],
            "ex-post: SC100 index down": g[g["sc100_index_ret"] < 0],
            "ex-post: SC100 index up": g[g["sc100_index_ret"] >= 0],
            "OOS segments": g[g["sample"] == "OOS"],
            "IS segments": g[g["sample"] == "IS"],
        }
        for lab, x in labels.items():
            reg.append({"leg": leg, "group": lab, "n_segments": len(x),
                        "mean_lift_5050_minus_cash": x["lift_5050_minus_cash"].mean(),
                        "share_lift_positive": (x["lift_5050_minus_cash"] > 0).mean() if len(x) else np.nan,
                        "mean_lift_gold_minus_5050": x["lift_gold_minus_5050"].mean(),
                        "mean_timing_paircash_minus_bh": x["timing_paircash_minus_bh"].mean(),
                        "share_timing_positive": (x["timing_paircash_minus_bh"] > 0).mean() if len(x) else np.nan,
                        "mean_total_pair5050_minus_bh": x["total_pair5050_minus_bh"].mean(),
                        "share_total_positive": (x["total_pair5050_minus_bh"] > 0).mean() if len(x) else np.nan,
                        "mean_dd_change_5050_vs_cash_daily": x["dd_change_5050_vs_cash_daily"].mean(),
                        "share_dd_worse_5050_daily": (x["dd_change_5050_vs_cash_daily"] < -1e-9).mean() if len(x) else np.nan,
                        "mean_time_in_sleeve": x["pair_time_in_sleeve"].mean()})
    pd.DataFrame(reg).to_csv(DEEP / "sleeve_yearly_regimes.csv", index=False)
    print("1 done", flush=True)

    # ════════════════════════════════════════════════════════════════════════
    # 2. Defensive spells of the pair
    # ════════════════════════════════════════════════════════════════════════
    dp = dec["pair"].dropna()
    first_earn = {}                                 # first-earning session -> the review that set it
    for r_, v in dp.items():
        j = cc.searchsorted(r_, side="right")
        if j + 1 < len(cc):
            first_earn.setdefault(cc[j + 1], []).append((r_, v))
    lg = {k: np.log1p(v) for k, v in {"SC100": req["SC100"], "N100": req["N100"], "blend": req["blend"],
                                      "gold": rsl["gold"], "cash": rsl["cash"], "5050": rsl["5050"]}.items()}
    nav50, navc = navs[("SC100", "pair", "5050")], navs[("SC100", "pair", "cash")]
    lift_log = np.log(nav50).diff().fillna(0.0) - np.log(navc).diff().fillna(0.0)
    blend50, blendc = navs[("blend", "pair", "5050")], navs[("blend", "pair", "cash")]
    lift_log_b = np.log(blend50).diff().fillna(0.0) - np.log(blendc).diff().fillna(0.0)
    sp_rows = []
    for n_, (i, j) in enumerate(spells(w_pair), 1):
        sess = cc[i:j + 1]
        exit_rev = [r_ for r_, v in first_earn.get(cc[i], []) if v == 0]
        entry_rev = [r_ for r_, v in first_earn.get(cc[j + 1], []) if v == 1] if j + 1 < len(cc) else []
        wk = int(((dp.index >= exit_rev[-1]) & (dp.index < (entry_rev[-1] if entry_rev else END + pd.Timedelta(days=1)))).sum()) if exit_rev else np.nan
        tot = {k: float(np.expm1(v.loc[sess].sum())) for k, v in lg.items()}
        gdrift = 0.5 * (1 + tot["gold"]) + 0.5 * (1 + tot["cash"]) - 1
        sp_rows.append({"spell": n_, "sample": sample_of(cc[i]),
                        "exit_review": exit_rev[-1].date() if exit_rev else None,
                        "reentry_review": entry_rev[-1].date() if entry_rev else "open",
                        "first_sleeve_session": cc[i].date(), "last_sleeve_session": cc[j].date(),
                        "sessions": len(sess), "weeks": wk,
                        "SC100_ret": tot["SC100"], "N100_ret": tot["N100"], "blend_ret": tot["blend"],
                        "gold_ret": tot["gold"], "cash_ret": tot["cash"],
                        "sleeve5050_daily_remix_ret": tot["5050"], "sleeve5050_drift_ret": gdrift,
                        "gold_minus_cash": tot["gold"] - tot["cash"], "gold_beat_cash": bool(tot["gold"] > tot["cash"]),
                        "gold_positive": bool(tot["gold"] > 0),
                        "sleeve5050_minus_SC100": tot["5050"] - tot["SC100"],
                        "cash_minus_SC100": tot["cash"] - tot["SC100"],
                        "SC100_lift_log_5050_vs_cash": float(lift_log.loc[sess].sum()),
                        "blend_lift_log_5050_vs_cash": float(lift_log_b.loc[sess].sum()),
                        "straddles_boundary": bool(cc[i] < IS_SPELL_FROM <= cc[j])})
    spd = pd.DataFrame(sp_rows)
    spd.to_csv(DEEP / "sleeve_spells.csv", index=False)
    ssum = []
    for lab, x in (("OOS 2014-21", spd[spd["sample"] == "OOS"]), ("IS 2021-26", spd[spd["sample"] == "IS"]),
                   ("all 2014-26", spd)):
        ssum.append({"sample": lab, "spells": len(x), "sessions": int(x["sessions"].sum()),
                     "weeks": int(x["weeks"].sum()),
                     "gold_beat_cash_hits": int(x["gold_beat_cash"].sum()),
                     "gold_hit_rate_vs_cash": float(x["gold_beat_cash"].mean()),
                     "gold_positive_share": float(x["gold_positive"].mean()),
                     "mean_gold_minus_cash": float(x["gold_minus_cash"].mean()),
                     "median_gold_minus_cash": float(x["gold_minus_cash"].median()),
                     "best_gold_minus_cash": float(x["gold_minus_cash"].max()),
                     "worst_gold_minus_cash": float(x["gold_minus_cash"].min()),
                     "compounded_gold_all_spells": float(np.prod(1 + x["gold_ret"]) - 1),
                     "compounded_cash_all_spells": float(np.prod(1 + x["cash_ret"]) - 1),
                     "compounded_SC100_all_spells": float(np.prod(1 + x["SC100_ret"]) - 1),
                     "compounded_blend_all_spells": float(np.prod(1 + x["blend_ret"]) - 1),
                     "mean_SC100_in_spell": float(x["SC100_ret"].mean()),
                     "share_SC100_fell_in_spell": float((x["SC100_ret"] < 0).mean()),
                     "share_cash_beat_SC100": float((x["cash_minus_SC100"] > 0).mean()),
                     "share_5050_beat_SC100": float((x["sleeve5050_minus_SC100"] > 0).mean()),
                     "SC100_lift_log_sum": float(x["SC100_lift_log_5050_vs_cash"].sum()),
                     "top_spell_share_of_lift": float(x["SC100_lift_log_5050_vs_cash"].max() /
                                                      x["SC100_lift_log_5050_vs_cash"].sum())
                     if x["SC100_lift_log_5050_vs_cash"].sum() else np.nan})
    pd.DataFrame(ssum).to_csv(DEEP / "sleeve_spells_summary.csv", index=False)
    print("2 done", flush=True)

    # ════════════════════════════════════════════════════════════════════════
    # 3. Gold as a crisis hedge
    # ════════════════════════════════════════════════════════════════════════
    sc_w = lv["SC100"].loc["2014-07-01":END].resample("W-FRI").last().dropna()
    g_w = gc["gold"].loc["2014-07-01":END].resample("W-FRI").last().reindex(sc_w.index)
    c_w = gc["cash"].loc["2014-07-01":END].resample("W-FRI").last().reindex(sc_w.index)
    n100_w = lv["N100"].loc["2014-07-01":END].resample("W-FRI").last().reindex(sc_w.index)
    _lv = lv.loc["2014-07-01":END]
    _bl = (1 + ((_lv["N100"].pct_change() + _lv["MC100"].pct_change() + _lv["SC100"].pct_change()) / 3)
           .fillna(0.0)).cumprod()
    bl_w = _bl.resample("W-FRI").last().reindex(sc_w.index)
    # pair NAVs (daily); a peak before the first NAV date (2014-07-07) is clipped to that date
    n50w = {"pair5050": navs[("SC100", "pair", "5050")], "paircash": navs[("SC100", "pair", "cash")],
            "pairgold": navs[("SC100", "pair", "gold")]}

    def zigzag(px: pd.Series, th=0.10):
        v, out = px.to_numpy(), []
        mode, pk, tr = "up", 0, 0
        for k in range(1, len(v)):
            if mode == "up":
                if v[k] > v[pk]:
                    pk = k
                elif v[k] <= v[pk] * (1 - th):
                    mode, tr = "down", k
            else:
                if v[k] < v[tr]:
                    tr = k
                elif v[k] >= v[tr] * (1 + th):
                    out.append((pk, tr, "closed"))
                    mode, pk = "up", k
        if mode == "down":
            out.append((pk, tr, "open at 2026-08-21"))
        return out

    def underwater(px: pd.Series, th=0.10):
        v, out = px.to_numpy(), []
        pk, k = 0, 1
        while k < len(v):
            if v[k] >= v[pk]:
                pk = k
                k += 1
                continue
            j = k
            while j < len(v) and v[j] < v[pk]:
                j += 1
            seg = v[pk:j]
            tr = pk + int(np.argmin(seg))
            if 1 - v[tr] / v[pk] >= th:
                out.append((pk, tr, "recovered " + str(sc_w.index[j].date()) if j < len(v) else "not recovered"))
            pk, k = (j, j + 1) if j < len(v) else (pk, len(v))
        return out

    dec_rows = []
    for method, eps in (("zigzag 10%", zigzag(sc_w)), ("peak-to-recovery", underwater(sc_w))):
        for pk, tr, status in eps:
            p, t = sc_w.index[pk], sc_w.index[tr]
            span = (cc > p) & (cc <= t)
            p_nav = max(p, cc[0])
            dd = {k: float(n50w[k].asof(t) / n50w[k].asof(p_nav) - 1) for k in n50w}
            dec_rows.append({"method": method, "peak_fri": p.date(), "trough_fri": t.date(), "status": status,
                             "weeks": tr - pk, "sample": "straddle" if p < IS_SPELL_FROM <= t else sample_of(p),
                             "SC100_ret": float(sc_w.iloc[tr] / sc_w.iloc[pk] - 1),
                             "N100_ret": float(n100_w.iloc[tr] / n100_w.iloc[pk] - 1),
                             "blend_ret": float(bl_w.iloc[tr] / bl_w.iloc[pk] - 1),
                             "gold_ret": float(g_w.iloc[tr] / g_w.iloc[pk] - 1),
                             "cash_ret": float(c_w.iloc[tr] / c_w.iloc[pk] - 1),
                             "gold_minus_cash": float(g_w.iloc[tr] / g_w.iloc[pk] - c_w.iloc[tr] / c_w.iloc[pk]),
                             "gold_up": bool(g_w.iloc[tr] > g_w.iloc[pk]),
                             "pair_share_sessions_defensive": float((w_pair[span] == 0).mean()) if span.any() else np.nan,
                             "pair_nav_measured_from": p_nav.date(),
                             "pair_SC100_5050_ret": dd["pair5050"], "pair_SC100_cash_ret": dd["paircash"],
                             "pair_SC100_gold_ret": dd["pairgold"],
                             "sleeve_lift_5050_minus_cash": dd["pair5050"] - dd["paircash"]})
    dct = pd.DataFrame(dec_rows)
    dct.to_csv(DEEP / "sleeve_sc100_declines.csv", index=False)
    dsum = []
    for (m, s_), x in list(dct.groupby(["method", "sample"])) + [((m, "all"), x) for m, x in dct.groupby("method")]:
        dsum.append({"method": m, "sample": s_, "declines": len(x), "mean_SC100": x["SC100_ret"].mean(),
                     "gold_up_count": int(x["gold_up"].sum()), "gold_up_share": x["gold_up"].mean(),
                     "gold_beat_cash_share": (x["gold_minus_cash"] > 0).mean(),
                     "mean_gold": x["gold_ret"].mean(), "median_gold": x["gold_ret"].median(),
                     "mean_gold_minus_cash": x["gold_minus_cash"].mean(),
                     "mean_pair_defensive_share": x["pair_share_sessions_defensive"].mean(),
                     "mean_pair_5050": x["pair_SC100_5050_ret"].mean(), "mean_pair_cash": x["pair_SC100_cash_ret"].mean(),
                     "mean_sleeve_lift": x["sleeve_lift_5050_minus_cash"].mean(),
                     "share_sleeve_lift_positive": (x["sleeve_lift_5050_minus_cash"] > 0).mean()})
    pd.DataFrame(dsum).to_csv(DEEP / "sleeve_sc100_declines_summary.csv", index=False)

    # Weekly correlation, by the pair's state in that week.
    wk = pd.DataFrame({"SC100": sc_w.pct_change(), "gold": g_w.pct_change(), "cash": c_w.pct_change()}).iloc[1:]
    wz = (w_pair == 0).astype(float)
    wk_ix = pd.Series(sc_w.index, index=sc_w.index)
    share0 = []
    for k in range(1, len(sc_w)):
        seg_ = wz[(wz.index > sc_w.index[k - 1]) & (wz.index <= sc_w.index[k])]
        share0.append(float(seg_.mean()) if len(seg_) else np.nan)
    wk["def_share"] = share0
    wk["state"] = np.where(wk["def_share"] == 1, "defensive (all sessions w=0)",
                           np.where(wk["def_share"] == 0, "equity (all sessions w=1)", "mixed (switch week)"))
    wk["sample"] = [sample_of(d) for d in wk.index]
    wk.loc[wk["def_share"].isna(), "state"] = "outside run"
    wk.to_csv(DEEP / "sleeve_weekly_returns_states.csv")

    def fisher_p(r1, n1, r2, n2):
        from math import atanh, erf, sqrt
        z = (atanh(r1) - atanh(r2)) / sqrt(1 / (n1 - 3) + 1 / (n2 - 3))
        return 2 * (1 - 0.5 * (1 + erf(abs(z) / sqrt(2))))

    crow = []
    for smp in ("OOS", "IS", "all"):
        x0 = wk if smp == "all" else wk[wk["sample"] == smp]
        for st in ["defensive (all sessions w=0)", "equity (all sessions w=1)", "mixed (switch week)", "all weeks"]:
            x = x0 if st == "all weeks" else x0[x0["state"] == st]
            x = x.dropna(subset=["SC100", "gold"])
            if len(x) < 5:
                continue
            b = np.polyfit(x["SC100"], x["gold"], 1)[0]
            crow.append({"sample": smp, "state": st, "weeks": len(x), "corr_gold_SC100": x["gold"].corr(x["SC100"]),
                         "beta_gold_on_SC100": b, "mean_SC100_wk": x["SC100"].mean(), "mean_gold_wk": x["gold"].mean(),
                         "mean_cash_wk": x["cash"].mean(), "share_gold_up": (x["gold"] > 0).mean(),
                         "share_gold_beat_cash": (x["gold"] > x["cash"]).mean()})
        d_, e_ = [c for c in crow if c["sample"] == smp and c["state"].startswith("defensive")], \
                 [c for c in crow if c["sample"] == smp and c["state"].startswith("equity")]
        if d_ and e_:
            crow.append({"sample": smp, "state": "Fisher z p-value: defensive vs equity corr",
                         "weeks": d_[0]["weeks"] + e_[0]["weeks"],
                         "corr_gold_SC100": fisher_p(d_[0]["corr_gold_SC100"], d_[0]["weeks"],
                                                     e_[0]["corr_gold_SC100"], e_[0]["weeks"])})
    pd.DataFrame(crow).to_csv(DEEP / "sleeve_gold_sc100_corr.csv", index=False)

    # Gold in SC100's bad weeks (all weeks, not only the pair's).
    bins = [-1, -0.05, -0.02, 0, 0.02, 1]
    labs = ["SC100 wk < -5%", "-5% to -2%", "-2% to 0", "0 to +2%", "> +2%"]
    wk["sc_bucket"] = pd.cut(wk["SC100"], bins=bins, labels=labs)
    bk = []
    for smp in ("OOS", "IS", "all"):
        x0 = wk if smp == "all" else wk[wk["sample"] == smp]
        for b_, x in x0.groupby("sc_bucket", observed=False):
            bk.append({"sample": smp, "bucket": b_, "weeks": len(x), "mean_SC100": x["SC100"].mean(),
                       "mean_gold": x["gold"].mean(), "share_gold_up": (x["gold"] > 0).mean() if len(x) else np.nan,
                       "share_pair_defensive": (x["state"].str.startswith("defensive")).mean() if len(x) else np.nan})
    pd.DataFrame(bk).to_csv(DEEP / "sleeve_gold_in_sc100_buckets.csv", index=False)
    print("3 done", flush=True)

    # ════════════════════════════════════════════════════════════════════════
    # 4 + 5 + 6. Per period: decomposition, drifting sleeve, counterfactuals
    # ════════════════════════════════════════════════════════════════════════
    per_rows, drift_rows, cf_rows, loo_rows, gold_rows = [], [], [], [], []
    for plab, (a, b) in PERIODS.items():
        c2, s2 = window(cal, sg, a, b)
        r2 = equity_returns(lv, c2)
        sl2 = sleeve_returns(gc, c2)
        yrs = (c2[-1] - c2[0]).days / 365.25
        dpair = s2["N100"] * s2["SC100"]
        wp = weight(dpair, c2)
        # gold / cash themselves, and gold only while the pair is defensive
        g2, k2 = gc["gold"].reindex(c2), gc["cash"].reindex(c2)
        z = (wp == 0)
        gold_rows.append({"period": plab, "gold_cagr_held": cagr(g2), "cash_cagr_held": cagr(k2),
                          "gold_dd_daily": mdd(g2), "gold_dd_fri": mdd_fri(g2),
                          "pair_time_in_sleeve": float(z.mean()),
                          "gold_total_in_defensive_sessions": float(np.expm1(np.log1p(sl2["gold"][z]).sum())),
                          "cash_total_in_defensive_sessions": float(np.expm1(np.log1p(sl2["cash"][z]).sum())),
                          "gold_total_in_equity_sessions": float(np.expm1(np.log1p(sl2["gold"][~z]).sum())),
                          "gold_ann_in_defensive_time": float(np.expm1(np.log1p(sl2["gold"][z]).sum() / (z.sum() / 252))),
                          "cash_ann_in_defensive_time": float(np.expm1(np.log1p(sl2["cash"][z]).sum() / (z.sum() / 252))),
                          "gold_ann_in_equity_time": float(np.expm1(np.log1p(sl2["gold"][~z]).sum() / ((~z).sum() / 252)))})
        for leg in EQUITY_LEGS:
            rs_ = rules(s2, OWN.get(leg))
            res = {}
            for rn, dd_ in rs_.items():
                for sl in (SLEEVES if rn != "bh" else ("cash",)):
                    nv = run_rs(dd_, r2[leg], sl2[sl], c2)
                    res[(rn, sl)] = nv
                    pk_d, tr_d = dd_dates(nv)
                    pk_f, tr_f = dd_dates(fri(nv))
                    per_rows.append({"period": plab, "sample": "IS" if plab.endswith("IS") else
                                     ("OOS" if plab.endswith("OOS") else "mixed"), "leg": leg, "rule": rn,
                                     "sleeve": sl if rn != "bh" else "-", "cagr": cagr(nv), "dd_daily": mdd(nv),
                                     "dd_daily_peak": pk_d, "dd_daily_trough": tr_d,
                                     "dd_fri": mdd_fri(nv), "dd_fri_peak": pk_f, "dd_fri_trough": tr_f,
                                     "switch_reviews": int((dd_.diff().abs() > 0).sum())})
            if leg not in ("SC100", "blend"):
                continue
            # 5. drifting sleeve
            rdrift = drift_sleeve(wp, gc, c2)
            nd = run_rs(dpair, r2[leg], rdrift, c2)
            nr = res[("pair", "5050")]
            drift_rows.append({"period": plab, "leg": leg, "remix_cagr": cagr(nr), "drift_cagr": cagr(nd),
                               "drift_minus_remix_pp": (cagr(nd) - cagr(nr)) * 100,
                               "remix_dd_daily": mdd(nr), "drift_dd_daily": mdd(nd),
                               "remix_dd_fri": mdd_fri(nr), "drift_dd_fri": mdd_fri(nd)})
            # 6. counterfactual sleeves while defensive
            rg, rc = sl2["gold"], sl2["cash"]
            g_oos = cagr(gc["gold"].reindex(window(cal, sg, W14, OOS_END)[0]))
            g_full = cagr(gc["gold"].reindex(window(cal, sg, W14, END)[0]))
            flat = lambda ann: pd.Series((1 + ann) ** (1 / 252) - 1, index=c2)
            scen = {"actual 50/50 (daily re-mix)": sl2["5050"],
                    "actual 50/50 (drifting)": rdrift,
                    "gold = cash (the cash sleeve)": rc,
                    "gold flat 0% (sleeve = half cash)": 0.5 * rc,
                    f"gold at its 2014-21 CAGR {g_oos:.1%} steady": 0.5 * flat(g_oos) + 0.5 * rc,
                    f"gold at its 2014-26 CAGR {g_full:.1%} steady": 0.5 * flat(g_full) + 0.5 * rc,
                    "gold at -10%/yr steady (hypothetical bear)": 0.5 * flat(-0.10) + 0.5 * rc,
                    "actual all gold": rg}
            bh_c = cagr(res[("bh", "cash")])
            for sn, rsl_ in scen.items():
                nv = run_rs(dpair, r2[leg], rsl_.fillna(0.0), c2)
                cf_rows.append({"period": plab, "leg": leg, "scenario": sn, "pair_cagr": cagr(nv), "bh_cagr": bh_c,
                                "excess_vs_bh_pp": (cagr(nv) - bh_c) * 100, "dd_daily": mdd(nv), "dd_fri": mdd_fri(nv)})
            # leave-the-best-spell-out: replace gold by cash within the top-k gold-excess spells
            spl = spells(wp)
            ex = []
            for (i, j) in spl:
                s_ = c2[i:j + 1]
                ex.append((float(np.expm1(np.log1p(rg.loc[s_]).sum()) - np.expm1(np.log1p(rc.loc[s_]).sum())), i, j))
            ex.sort(reverse=True)
            base50 = cagr(nr)
            basec = cagr(res[("pair", "cash")])
            for kk in (1, 2, 3):
                r_mod = sl2["5050"].copy()
                for _, i, j in ex[:kk]:
                    r_mod.iloc[i:j + 1] = rc.iloc[i:j + 1]
                nv = run_rs(dpair, r2[leg], r_mod, c2)
                loo_rows.append({"period": plab, "leg": leg, "gold_replaced_by_cash_in_top_k_spells": kk,
                                 "spells_replaced": "; ".join(f"{c2[i].date()}..{c2[j].date()} (gold-cash {e_:+.1%})"
                                                              for e_, i, j in ex[:kk]),
                                 "pair5050_cagr": base50, "pair_modified_cagr": cagr(nv), "pair_cash_cagr": basec,
                                 "share_of_sleeve_lift_removed": (base50 - cagr(nv)) / (base50 - basec)
                                 if base50 != basec else np.nan})
    pr = pd.DataFrame(per_rows)
    pr.to_csv(DEEP / "sleeve_period_results.csv", index=False)
    # decomposition table
    dec_tab = []
    for (plab, leg), g in pr.groupby(["period", "leg"], sort=False):
        k = {(r.rule, r.sleeve): r.cagr for r in g.itertuples()}
        kd = {(r.rule, r.sleeve): (r.dd_daily, r.dd_fri) for r in g.itertuples()}
        dec_tab.append({"period": plab, "leg": leg, "bh_cagr": k[("bh", "-")],
                        "pair_cash_cagr": k[("pair", "cash")], "pair_5050_cagr": k[("pair", "5050")],
                        "pair_gold_cagr": k[("pair", "gold")],
                        "sc100_cash_cagr": k[("sc100", "cash")], "sc100_5050_cagr": k[("sc100", "5050")],
                        "timing_pp": (k[("pair", "cash")] - k[("bh", "-")]) * 100,
                        "sleeve_pp": (k[("pair", "5050")] - k[("pair", "cash")]) * 100,
                        "total_5050_vs_bh_pp": (k[("pair", "5050")] - k[("bh", "-")]) * 100,
                        "gold_vs_5050_pp": (k[("pair", "gold")] - k[("pair", "5050")]) * 100,
                        "bh_dd_daily": kd[("bh", "-")][0], "pair_cash_dd_daily": kd[("pair", "cash")][0],
                        "pair_5050_dd_daily": kd[("pair", "5050")][0], "pair_gold_dd_daily": kd[("pair", "gold")][0],
                        "bh_dd_fri": kd[("bh", "-")][1], "pair_cash_dd_fri": kd[("pair", "cash")][1],
                        "pair_5050_dd_fri": kd[("pair", "5050")][1], "pair_gold_dd_fri": kd[("pair", "gold")][1]})
    # 4-book portfolio decomposition (OOS parents 2014-21, IS books 2021-26; 2014-26 chained per book)
    for plab, smp in (("2014-21 OOS", "OOS"), ("2021-26 IS", "IS"), ("2014-26 full (chained books)", "chain")):
        acc = []
        for bk_ in BOOKS:
            def nv_(rn, sl):
                if smp != "chain":
                    return book_nav(smp, bk_, rn, sl)
                o, i_ = book_nav("OOS", bk_, rn, sl), book_nav("IS", bk_, rn, sl)
                return pd.concat([o, i_.iloc[1:] / i_.iloc[0] * o.iloc[-1]])
            m = {(rn, sl): nv_(rn, sl) for rn, sl in (("bh", "5050"), ("pair", "cash"), ("pair", "5050"),
                                                      ("pair", "gold"), ("sc100", "cash"), ("sc100", "5050"))}
            acc.append({f"{rn}_{sl}": cagr(v) for (rn, sl), v in m.items()} |
                       {f"{rn}_{sl}_dd_daily": mdd(v) for (rn, sl), v in m.items()} |
                       {f"{rn}_{sl}_dd_fri": mdd_fri(v) for (rn, sl), v in m.items()})
        a_ = pd.DataFrame(acc).mean()
        dec_tab.append({"period": plab, "leg": "4-book avg", "bh_cagr": a_["bh_5050"],
                        "pair_cash_cagr": a_["pair_cash"], "pair_5050_cagr": a_["pair_5050"],
                        "pair_gold_cagr": a_["pair_gold"], "sc100_cash_cagr": a_["sc100_cash"],
                        "sc100_5050_cagr": a_["sc100_5050"],
                        "timing_pp": (a_["pair_cash"] - a_["bh_5050"]) * 100,
                        "sleeve_pp": (a_["pair_5050"] - a_["pair_cash"]) * 100,
                        "total_5050_vs_bh_pp": (a_["pair_5050"] - a_["bh_5050"]) * 100,
                        "gold_vs_5050_pp": (a_["pair_gold"] - a_["pair_5050"]) * 100,
                        "bh_dd_daily": a_["bh_5050_dd_daily"], "pair_cash_dd_daily": a_["pair_cash_dd_daily"],
                        "pair_5050_dd_daily": a_["pair_5050_dd_daily"], "pair_gold_dd_daily": a_["pair_gold_dd_daily"],
                        "bh_dd_fri": a_["bh_5050_dd_fri"], "pair_cash_dd_fri": a_["pair_cash_dd_fri"],
                        "pair_5050_dd_fri": a_["pair_5050_dd_fri"], "pair_gold_dd_fri": a_["pair_gold_dd_fri"]})
    pd.DataFrame(dec_tab).to_csv(DEEP / "sleeve_excess_decomposition.csv", index=False)
    pd.DataFrame(drift_rows).to_csv(DEEP / "sleeve_drift_vs_remix.csv", index=False)
    pd.DataFrame(cf_rows).to_csv(DEEP / "sleeve_gold_counterfactual.csv", index=False)
    pd.DataFrame(loo_rows).to_csv(DEEP / "sleeve_gold_leave_spell_out.csv", index=False)
    pd.DataFrame(gold_rows).to_csv(DEEP / "sleeve_gold_itself.csv", index=False)

    # per-year decomposition summary (from part 1), counts of positive years
    ys = []
    for leg, g in yw.groupby("leg", sort=False):
        for smp in ("OOS", "IS"):
            x = g[g["sample"] == smp]
            ys.append({"leg": leg, "sample": smp, "segments": len(x),
                       "timing_positive": int((x["timing_paircash_minus_bh"] > 0).sum()),
                       "sleeve_positive": int((x["lift_5050_minus_cash"] > 0).sum()),
                       "total_positive": int((x["total_pair5050_minus_bh"] > 0).sum()),
                       "sum_timing_pp": x["timing_paircash_minus_bh"].sum() * 100,
                       "sum_sleeve_pp": x["lift_5050_minus_cash"].sum() * 100,
                       "sum_total_pp": x["total_pair5050_minus_bh"].sum() * 100,
                       "years_sleeve_rescues_negative_timing": int(((x["timing_paircash_minus_bh"] <= 0) &
                                                                    (x["total_pair5050_minus_bh"] > 0)).sum()),
                       "corr_timing_vs_sleeve_across_segments": x["timing_paircash_minus_bh"].corr(x["lift_5050_minus_cash"])})
        ys.append({"leg": leg, "sample": "all", "segments": len(g),
                   "timing_positive": int((g["timing_paircash_minus_bh"] > 0).sum()),
                   "sleeve_positive": int((g["lift_5050_minus_cash"] > 0).sum()),
                   "total_positive": int((g["total_pair5050_minus_bh"] > 0).sum()),
                   "sum_timing_pp": g["timing_paircash_minus_bh"].sum() * 100,
                   "sum_sleeve_pp": g["lift_5050_minus_cash"].sum() * 100,
                   "sum_total_pp": g["total_pair5050_minus_bh"].sum() * 100,
                   "years_sleeve_rescues_negative_timing": int(((g["timing_paircash_minus_bh"] <= 0) &
                                                                (g["total_pair5050_minus_bh"] > 0)).sum()),
                   "corr_timing_vs_sleeve_across_segments": g["timing_paircash_minus_bh"].corr(g["lift_5050_minus_cash"])})
    pd.DataFrame(ys).to_csv(DEEP / "sleeve_yearly_decomposition_summary.csv", index=False)

    # 6b. Gold-timing placebo: is gold better on the pair's defensive days than on
    # random days with the same spell structure? Circularly shift the pair's
    # defensive mask in steps of 5 sessions (keeps the weekly structure) and
    # measure the sleeve lift in log terms: sum over defensive days of
    # 0.5 * [log(1 + r_gold) - log(1 + r_cash)] (the 50/50 sleeve vs cash,
    # daily re-mix, cost-free), annualised over the window.
    plc = []
    for plab, (a, b) in PERIODS.items():
        c2, s2 = window(cal, sg, a, b)
        sl2 = sleeve_returns(gc, c2)
        wp = weight(s2["N100"] * s2["SC100"], c2).to_numpy()
        yrs = (c2[-1] - c2[0]).days / 365.25
        dl = (np.log1p(sl2["5050"]) - np.log1p(sl2["cash"])).to_numpy()
        act = float(dl[wp == 0].sum() / yrs)
        sh = np.array([dl[np.roll(wp, k) == 0].sum() / yrs for k in range(5, len(wp) - 4, 5)])
        uncond = float(dl.mean() * (wp == 0).mean() * len(dl) / yrs)
        plc.append({"period": plab, "sessions": len(wp), "share_defensive": float((wp == 0).mean()),
                    "actual_lift_log_per_yr": act, "shifts": len(sh),
                    "placebo_median_lift_log_per_yr": float(np.median(sh)),
                    "placebo_p05": float(np.percentile(sh, 5)), "placebo_p95": float(np.percentile(sh, 95)),
                    "actual_percentile_in_placebo": float((sh < act).mean()),
                    "unconditional_expected_lift_log_per_yr": uncond,
                    "timing_part_log_per_yr": act - uncond})
    pd.DataFrame(plc).to_csv(DEEP / "sleeve_gold_timing_placebo.csv", index=False)
    print("4-6 done", flush=True)


if __name__ == "__main__":
    main()
