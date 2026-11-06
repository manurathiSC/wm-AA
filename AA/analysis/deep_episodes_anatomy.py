# -*- coding: utf-8 -*-
"""
Drawdown-episode anatomy, 2007-07 -> 2026-08 (analyst "episodes").

For SC100, N100, MC100, N50 and the equal-weight N100/MC100/SC100 blend:

  1. Every peak-to-trough decline of 10%+ on Friday closes.
     - "strict": the running (all-time-in-window) peak. The trough is the lowest
       close before a new peak; the episode ends at recovery to that peak.
       Non-overlapping. This is the task's definition.
     - "local" (supplementary, hindsight): the same, but the peak is reset
       once the index rallies 20%+ off the running trough without regaining
       the peak. This splits one long underwater stretch (SC100 was below its
       Jan-2008 peak until Jul-2016) into its separate bear phases (2010-11,
       2013, 2015-16, ...). A local episode's rebound leg ends at recovery to
       ITS peak, or at the next local episode's peak if that comes first
       (then marked not recovered), so local cycles never overlap.
     Speed class (hindsight): "V" = trough within 13 weeks of the peak AND
     recovery within 26 weeks of the trough; else "grinding"; an unrecovered
     episode whose trough is < 26 weeks before the data end and came within
     13 weeks of the peak is "undetermined".
  2. Per episode x rule (pair, triple, sc100, own, bh) x sleeve (cash over
     2007-07-02 -> 2026-08-21; 50/50 gold/cash over 2014-07-07 -> 2026-08-21):
     NAV return peak->trough, trough->recovery, peak->recovery, first exit
     after the peak, first re-entry after the trough, out-at-peak flag,
     in-at-trough flag, worst NAV fall inside the episode (daily and Friday).
  3. Aggregates by speed class x depth band x sample.
  4. False exits: every 1->0 switch, and whether a further 10%+ fall followed
     within 26 weeks.
  5. A narrative row per 20%+ SC100 episode.

Weekly signals only (production SIGN via why_n100sc100.weekly_signs), timing
and costs from why_n100sc100.run_rs. Outputs: evidence/why_n100sc100/deep/episodes_*.csv
"""

from __future__ import annotations

import os

import numpy as np
import pandas as pd

from why_n100sc100 import COST, calendar, cagr, daily_weight, gold_cash, mdd, run_rs, weekly_signs
from triple_and_test import index_levels

OUTD = os.path.join("evidence", "why_n100sc100", "deep")
os.makedirs(OUTD, exist_ok=True)

END = pd.Timestamp("2026-08-21")
FULL0 = pd.Timestamp("2007-07-02")
GOLD0 = pd.Timestamp("2014-07-07")
IS0 = pd.Timestamp("2021-11-03")          # in-sample window start
OOS_CUT = pd.Timestamp("2021-11-01")      # peak before this = out of sample (unless the trough is in-sample)
THR = 0.10
RESET = 0.20
LEGS = ["SC100", "N100", "MC100", "N50", "blend"]
OWN = {"N50": "N50", "N100": "N100", "MC100": "MC100", "SC100": "SC100"}
RULES = ["pair", "triple", "sc100", "own", "bh"]
SIG_RULES = ["pair", "triple", "sc100", "own"]


def out(name):
    return os.path.join(OUTD, f"episodes_{name}.csv")


# ── data ───────────────────────────────────────────────────────────────────
cal_all = calendar()
cal_all = cal_all[cal_all <= END]
sg = weekly_signs()
sg = sg[sg.index <= END]
lv = index_levels(cal_all)
gc = gold_cash(cal_all)


def window(start):
    return cal_all[(cal_all >= start) & (cal_all <= END)]


def leg_returns(c):
    r = {k: lv[k].reindex(c).pct_change() for k in ["SC100", "N100", "MC100", "N50"]}
    r["blend"] = (r["N100"] + r["MC100"] + r["SC100"]) / 3
    return r


def sleeve_returns(c, sleeve):
    rc = gc["cash"].reindex(c).pct_change()
    if sleeve == "cash":
        return rc.fillna(0.0)
    rg = gc["gold"].reindex(c).pct_change()
    return (0.5 * rg + 0.5 * rc).fillna(0.0)       # 50/50, only used from 2014-07-07


def decisions(start, leg):
    s = sg.loc[(sg.index >= start - pd.Timedelta(days=7)) & (sg.index <= END)]
    need = ["N100", "MC100", "SC100"] + ([OWN[leg]] if leg in OWN else [])
    ss = s[list(dict.fromkeys(need))].dropna()
    d = {"pair": ss["N100"] * ss["SC100"],
         "triple": ss["N100"] * ss["MC100"] * ss["SC100"],
         "sc100": ss["SC100"],
         "bh": pd.Series(1.0, index=ss.index)}
    if leg in OWN:
        d["own"] = ss[OWN[leg]]
    return d


# Daily index levels over the full window (blend = daily-rebalanced equal weight).
C_FULL = window(FULL0)
R_FULL = leg_returns(C_FULL)
LVL = {k: lv[k].reindex(C_FULL) for k in ["SC100", "N100", "MC100", "N50"]}
LVL["blend"] = (1 + R_FULL["blend"].fillna(0.0)).cumprod()
LVL_W = {k: v.resample("W-FRI").last().dropna() for k, v in LVL.items()}
CASH_D = gc["cash"].reindex(C_FULL)

# NAVs and weights per (leg, rule, sleeve)
NAV, WGT, DEC = {}, {}, {}
for sleeve, start in (("cash", FULL0), ("5050", GOLD0)):
    c = window(start)
    rs = sleeve_returns(c, sleeve)
    re_ = leg_returns(c)
    for leg in LEGS:
        for rn, dec in decisions(start, leg).items():
            NAV[(leg, rn, sleeve)] = run_rs(dec, re_[leg].fillna(0.0), rs, c, cost_bps=COST)
            WGT[(leg, rn, sleeve)] = daily_weight(dec, c).reindex(c).ffill().fillna(1.0)
            DEC[(leg, rn, sleeve)] = dec

# ── sanity check against the reference results ─────────────────────────────
chk = []
c = cal_all[(cal_all >= FULL0) & (cal_all <= pd.Timestamp("2021-10-29"))]
rs = sleeve_returns(c, "cash")
re_ = leg_returns(c)
for leg in ["SC100", "blend"]:
    for rn, dec in decisions(FULL0, leg).items():
        if rn not in ("pair", "bh", "triple", "sc100"):
            continue
        n = run_rs(dec, re_[leg].fillna(0.0), rs, c)
        chk.append({"leg": leg, "rule": rn, "window": "2007-07-02..2021-10-29 cash",
                    "cagr": cagr(n), "max_dd_daily": mdd(n), "max_dd_friday": mdd(n.resample("W-FRI").last())})
for (leg, rn, sl), n in NAV.items():
    if leg in ("SC100", "blend") and rn in ("pair", "bh", "triple", "sc100"):
        chk.append({"leg": leg, "rule": rn, "window": f"{n.index[0].date()}..{n.index[-1].date()} {sl}",
                    "cagr": cagr(n), "max_dd_daily": mdd(n), "max_dd_friday": mdd(n.resample("W-FRI").last())})
pd.DataFrame(chk).to_csv(out("sanity_check"), index=False)


# ── 1. episode detection on Friday closes ──────────────────────────────────
def find_episodes(x: pd.Series, reset: float | None):
    """x: Friday closes. Returns list of dicts with integer positions."""
    v = x.to_numpy()
    eps = []
    P, state, T, ep_peak = 0, "up", None, None
    for i in range(1, len(v)):
        if state == "up":
            if v[i] >= v[P]:
                P = i
            elif v[i] <= v[P] * (1 - THR):
                state, T, ep_peak = "down", i, P
        else:
            if v[i] < v[T]:
                T = i
            if v[i] >= v[ep_peak]:
                eps.append({"p": ep_peak, "t": T, "r": i, "ended_by": "recovery"})
                state, P = "up", i
            elif reset is not None and v[i] >= v[T] * (1 + reset):
                eps.append({"p": ep_peak, "t": T, "r": None, "ended_by": f"rally {int(reset * 100)}%"})
                state, P = "up", i
    if state == "down":
        eps.append({"p": ep_peak, "t": T, "r": None, "ended_by": "open at data end"})
    # For legs closed by a rally: the first later close >= the peak ("full" recovery).
    # The rebound leg ends at that recovery if it comes before the next episode's
    # peak; otherwise at the next episode's peak (not recovered). Cycles never overlap.
    for k, e in enumerate(eps):
        rf = e["r"]
        if rf is None:
            later = np.where(v[e["t"] + 1:] >= v[e["p"]])[0]
            rf = int(e["t"] + 1 + later[0]) if len(later) else None
        e["r_full"] = rf
        nxt = eps[k + 1]["p"] if k + 1 < len(eps) else None
        if rf is not None and (nxt is None or rf <= nxt):
            e["r"], e["end"] = rf, rf
        else:
            e["r"], e["end"] = None, (nxt if nxt is not None else len(v) - 1)
    return eps


def label(p, t):
    return f"{p.year}" if p.year == t.year else f"{p.year}-{str(t.year)[2:]}"


EP = []
for leg in LEGS:
    x = LVL_W[leg]
    x = x[x.index >= pd.Timestamp("2007-07-06")]
    for dfn, reset in (("strict", None), ("local", RESET)):
        for k, e in enumerate(find_episodes(x, reset)):
            p, t = x.index[e["p"]], x.index[e["t"]]
            r = x.index[e["r"]] if e["r"] is not None else None
            endd = x.index[e["end"]]
            rfull = x.index[e["r_full"]] if e["r_full"] is not None else None
            depth = x.iloc[e["t"]] / x.iloc[e["p"]] - 1
            wp2t = e["t"] - e["p"]
            wt2r = (e["r"] - e["t"]) if e["r"] is not None else None
            wt2end = len(x) - 1 - e["t"]
            if wp2t <= 13 and wt2r is not None and wt2r <= 26:
                speed = "V"
            elif wp2t <= 13 and wt2r is None and e["end"] == len(x) - 1 and wt2end < 26:
                speed = "undetermined"
            else:
                speed = "grinding"
            fall_speed = "fast fall (<=13w)" if wp2t <= 13 else "slow fall (>13w)"
            rec_speed = ("recovered <=26w" if wt2r is not None and wt2r <= 26 else
                         "recovered >26w" if wt2r is not None else "not recovered")
            speed_loose = "V (loose)" if wp2t <= 13 and wt2r is not None and wt2r <= 52 else "not V (loose)"
            dl = LVL[leg].loc[p:endd]
            depth_d = float((dl / dl.cummax() - 1).min())
            if p < OOS_CUT and t < IS0:
                sample = "oos"
            elif p < OOS_CUT:
                sample = "straddle"
            else:
                sample = "in-sample"
            EP.append({"leg": leg, "definition": dfn, "episode": f"{leg}|{dfn}|{k + 1:02d}",
                       "label": label(p, t), "peak_date": p.date(), "trough_date": t.date(),
                       "recovery_date": r.date() if r is not None else None, "recovered": r is not None,
                       "rebound_end_date": endd.date(),
                       "rebound_end_is": ("recovery" if r is not None else
                                          "data end" if e["end"] == len(x) - 1 else "next episode peak"),
                       "full_recovery_date": rfull.date() if rfull is not None else None,
                       "rebound_end_close": float(x.iloc[e["end"]]),
                       "share_of_fall_regained": float((x.iloc[e["end"]] - x.iloc[e["t"]]) /
                                                       (x.iloc[e["p"]] - x.iloc[e["t"]])),
                       "peak_close": float(x.iloc[e["p"]]), "trough_close": float(x.iloc[e["t"]]),
                       "depth_friday": float(depth), "depth_daily_worst": depth_d,
                       "weeks_peak_to_trough": int(wp2t),
                       "weeks_trough_to_recovery": int(wt2r) if wt2r is not None else None,
                       "weeks_trough_to_data_end": int(wt2end), "weeks_trough_to_rebound_end": int(e["end"] - e["t"]),
                       "speed": speed, "fall_speed": fall_speed, "recovery_speed": rec_speed,
                       "speed_loose": speed_loose, "band": "20%+" if depth <= -0.20 else "10-20%",
                       "is_20plus": bool(depth <= -0.20), "sample": sample,
                       "in_gold_window": bool(p >= pd.Timestamp("2014-07-11")),
                       "decline_leg_ended_by": e["ended_by"]})
ep = pd.DataFrame(EP)
ep.to_csv(out("list"), index=False)


# ── 2. per episode x rule x sleeve ─────────────────────────────────────────
def at(s: pd.Series, d):
    """Last value on or before d."""
    s2 = s.loc[:d]
    return float(s2.iloc[-1]) if len(s2) else np.nan


def session_after(c, d):
    j = c.searchsorted(pd.Timestamp(d), side="right")
    return c[j] if j < len(c) else None


def switches(dec, c, kind):
    """kind 'exit' (1->0) or 'entry' (0->1): list of (decision date, fill session)."""
    d = dec.dropna()
    ch = d.diff()
    dates = d.index[(ch == (-1 if kind == "exit" else 1))]
    res = []
    for R in dates:
        j = c.searchsorted(R, side="right")
        if j + 1 < len(c):
            res.append((R, c[j]))
    return res


ROWS = []
for _, e in ep.iterrows():
    p, t = pd.Timestamp(e["peak_date"]), pd.Timestamp(e["trough_date"])
    r = pd.Timestamp(e["recovery_date"]) if e["recovered"] else None
    endd = pd.Timestamp(e["rebound_end_date"])
    lvd = LVL[e["leg"]]
    pk, tr = e["peak_close"], e["trough_close"]
    for sleeve in ("cash", "5050"):
        if sleeve == "5050" and not e["in_gold_window"]:
            continue
        for rn in RULES:
            key = (e["leg"], rn, sleeve)
            if key not in NAV:
                continue
            nav, w, dec = NAV[key], WGT[key], DEC[key]
            c = nav.index
            nw = nav.resample("W-FRI").last()
            n_p, n_t, n_r = at(nw, p), at(nw, t), at(nw, endd)
            seg = nav.loc[p:endd]
            segw = nw.loc[p:endd]
            s_after_p, s_after_t = session_after(c, p), session_after(c, t)
            row = {"episode": e["episode"], "leg": e["leg"], "definition": e["definition"], "label": e["label"],
                   "sleeve": sleeve, "rule": rn, "speed": e["speed"], "fall_speed": e["fall_speed"],
                   "recovery_speed": e["recovery_speed"], "speed_loose": e["speed_loose"],
                   "band": e["band"], "sample": e["sample"], "peak_date": e["peak_date"],
                   "depth_friday": e["depth_friday"], "recovered": e["recovered"],
                   "ret_peak_to_trough": n_t / n_p - 1, "ret_trough_to_recovery": n_r / n_t - 1,
                   "ret_peak_to_recovery": n_r / n_p - 1,
                   "worst_fall_in_episode_daily": float((seg / seg.cummax() - 1).min()),
                   "worst_fall_in_episode_friday": float((segw / segw.cummax() - 1).min()),
                   "out_at_peak": bool(s_after_p is not None and w.loc[s_after_p] == 0),
                   "in_at_trough": bool(s_after_t is not None and w.loc[s_after_t] == 1),
                   "avg_weight_decline_leg": float(w.loc[(w.index > p) & (w.index <= t)].mean()),
                   "avg_weight_rebound_leg": float(w.loc[(w.index > t) & (w.index <= endd)].mean())
                   if endd > t else np.nan}
            ex = [(R, f) for R, f in switches(dec, c, "exit") if p <= R <= endd]
            if ex:
                R, f = ex[0]
                row.update({"first_exit_decision": R.date(), "first_exit_fill": f.date(),
                            "exit_weeks_after_peak": (R - p).days / 7,
                            "exit_index_fall_at_decision": at(lvd, R) / pk - 1,
                            "exit_index_fall_at_fill": float(lvd.loc[f]) / pk - 1,
                            "exit_before_trough": bool(f < t)})
            en = [(R, f) for R, f in switches(dec, c, "entry") if t <= R <= endd]
            if en:
                R, f = en[0]
                row.update({"first_entry_decision": R.date(), "first_entry_fill": f.date(),
                            "entry_weeks_after_trough": (R - t).days / 7,
                            "entry_index_rise_at_decision": at(lvd, R) / tr - 1,
                            "entry_index_rise_at_fill": float(lvd.loc[f]) / tr - 1})
            ROWS.append(row)
er = pd.DataFrame(ROWS)

# vs buy-and-hold on the same leg, sleeve and episode
bh = er[er["rule"] == "bh"].set_index(["episode", "sleeve"])
for col, new in (("ret_peak_to_trough", "bh_p2t"), ("ret_trough_to_recovery", "bh_t2r"),
                 ("ret_peak_to_recovery", "bh_p2r"), ("worst_fall_in_episode_friday", "bh_worst_friday"),
                 ("worst_fall_in_episode_daily", "bh_worst_daily")):
    er[new] = [bh.loc[(a, b), col] for a, b in zip(er["episode"], er["sleeve"])]
er["loss_avoided_vs_bh"] = er["ret_peak_to_trough"] - er["bh_p2t"]
er["rebound_missed_vs_bh"] = er["bh_t2r"] - er["ret_trough_to_recovery"]
er["net_vs_bh"] = er["ret_peak_to_recovery"] - er["bh_p2r"]
# exact log decomposition: net_log = avoided_log - missed_log
er["loss_avoided_log"] = np.log1p(er["ret_peak_to_trough"]) - np.log1p(er["bh_p2t"])
er["rebound_missed_log"] = np.log1p(er["bh_t2r"]) - np.log1p(er["ret_trough_to_recovery"])
er["net_log"] = er["loss_avoided_log"] - er["rebound_missed_log"]
sc = er[er["rule"] == "sc100"].set_index(["episode", "sleeve"])
er["net_vs_sc100"] = er["ret_peak_to_recovery"] - [sc.loc[(a, b), "ret_peak_to_recovery"]
                                                   for a, b in zip(er["episode"], er["sleeve"])]
er.to_csv(out("rule_outcomes"), index=False)


# ── 3. aggregates ──────────────────────────────────────────────────────────
def agg(df, keys):
    g = df.groupby(keys, dropna=False)
    o = g.agg(n=("episode", "size"),
              bh_loss_mean=("bh_p2t", "mean"), rule_loss_mean=("ret_peak_to_trough", "mean"),
              loss_avoided_mean=("loss_avoided_vs_bh", "mean"),
              bh_rebound_mean=("bh_t2r", "mean"), rule_rebound_mean=("ret_trough_to_recovery", "mean"),
              rebound_missed_mean=("rebound_missed_vs_bh", "mean"),
              net_mean=("net_vs_bh", "mean"), net_median=("net_vs_bh", "median"),
              net_positive_share=("net_vs_bh", lambda s: float((s > 0).mean())),
              loss_avoided_log_mean=("loss_avoided_log", "mean"),
              rebound_missed_log_mean=("rebound_missed_log", "mean"), net_log_mean=("net_log", "mean"),
              worst_fall_friday_mean=("worst_fall_in_episode_friday", "mean"),
              bh_worst_fall_friday_mean=("bh_worst_friday", "mean"),
              out_at_peak_share=("out_at_peak", "mean"),
              exit_fall_at_fill_mean=("exit_index_fall_at_fill", "mean"),
              entry_rise_at_fill_mean=("entry_index_rise_at_fill", "mean"),
              net_vs_sc100_mean=("net_vs_sc100", "mean")).reset_index()
    return o


a = er[er["rule"] != "bh"].copy()
a["sample2"] = np.where(a["sample"] == "oos", "oos", "in-sample (incl. straddle)")
# classification: which hindsight class column(s) the row is grouped by
CLASSES = [("speed x band", ["speed", "band"]), ("speed", ["speed"]), ("band", ["band"]),
           ("fall_speed", ["fall_speed"]), ("fall_speed x band", ["fall_speed", "band"]),
           ("recovery_speed", ["recovery_speed"]), ("speed_loose", ["speed_loose"]), ("all", [])]
BASE = ["definition", "sleeve", "sample2"]
parts = []
for cname, cols in CLASSES:
    for pooled in (False, True):
        src = a[a["rule"] != "own"] if pooled else a
        keys = BASE + ([] if pooled else ["leg"]) + ["rule"] + cols
        x = agg(src, keys)
        if pooled:
            x["leg"] = "pooled 5 legs"
        x["class"] = cname
        x["class_value"] = x[cols].astype(str).agg(" | ".join, axis=1) if cols else "all"
        parts.append(x.drop(columns=cols))
ag = pd.concat(parts, ignore_index=True)
lead = BASE + ["leg", "rule", "class", "class_value"]
ag = ag[lead + [c for c in ag.columns if c not in lead]]
ag.to_csv(out("aggregates"), index=False)


# ── 3b. where the edge comes from: phase decomposition of daily log excess ──
# Each session is tagged (hindsight) as in a decline leg (peak < d <= trough),
# a rebound leg (trough < d <= rebound end) or outside any episode; and as out
# of sample (d < 2021-11-03) or in-sample. Log excess = log(1+r_rule) - log(1+r_bh),
# summed per bucket; *_log_per_year = bucket sum / years in the period (0.05 = 5 log-pp a year).
PH = []
for dfn in ("strict", "local"):
    for leg in LEGS:
        eps_ = ep[(ep["leg"] == leg) & (ep["definition"] == dfn)]
        for sleeve in ("cash", "5050"):
            nb = NAV[(leg, "bh", sleeve)]
            c = nb.index
            tag = pd.Series("outside episodes", index=c)
            for _, e in eps_.iterrows():
                p, t, z = (pd.Timestamp(e[k]) for k in ("peak_date", "trough_date", "rebound_end_date"))
                tag[(c > p) & (c <= t)] = "decline leg"
                tag[(c > t) & (c <= z)] = "rebound leg"
            per = pd.Series(np.where(c < IS0, "oos", "in-sample"), index=c)
            lb = np.log(nb / nb.shift(1)).fillna(0.0)
            for rn in RULES:
                if rn == "bh" or (leg, rn, sleeve) not in NAV:
                    continue
                nr_ = NAV[(leg, rn, sleeve)]
                ex_ = np.log(nr_ / nr_.shift(1)).fillna(0.0) - lb
                for pr in ("oos", "in-sample", "all"):
                    m = (per == pr) if pr != "all" else pd.Series(True, index=c)
                    if not m.any():
                        continue
                    yrs = (c[m][-1] - c[m][0]).days / 365.25
                    row = {"definition": dfn, "leg": leg, "sleeve": sleeve, "rule": rn, "period": pr,
                           "from": c[m][0].date(), "to": c[m][-1].date(), "years": yrs,
                           "total_log_excess": float(ex_[m].sum()),
                           "total_log_per_year": float(ex_[m].sum() / yrs)}
                    for ph in ("decline leg", "rebound leg", "outside episodes"):
                        mm = m & (tag == ph)
                        row[f"{ph}_log_excess"] = float(ex_[mm].sum())
                        row[f"{ph}_log_per_year"] = float(ex_[mm].sum() / yrs)
                        row[f"{ph}_share_of_sessions"] = float(mm.sum() / m.sum())
                        row[f"{ph}_avg_weight"] = float(WGT[(leg, rn, sleeve)][mm].mean()) if mm.any() else np.nan
                    PH.append(row)
pd.DataFrame(PH).to_csv(out("phase_decomposition"), index=False)


# ── 3c. concentration: how much of the edge is one or two episodes? ───────
# Daily log excess vs bh, summed over each episode's cycle (peak, rebound end]
# inside a time period; the period total minus the largest one or two cycles.
CC = []
PERIODS = {"oos": (None, IS0), "in-sample": (IS0, None), "all": (None, None)}
for dfn in ("strict", "local"):
    for leg in LEGS:
        eps_ = ep[(ep["leg"] == leg) & (ep["definition"] == dfn)]
        for sleeve in ("cash", "5050"):
            nb = NAV[(leg, "bh", sleeve)]
            c = nb.index
            lb = np.log(nb / nb.shift(1)).fillna(0.0)
            for rn in RULES:
                if rn == "bh" or (leg, rn, sleeve) not in NAV:
                    continue
                nr_ = NAV[(leg, rn, sleeve)]
                ex_ = np.log(nr_ / nr_.shift(1)).fillna(0.0) - lb
                for pr, (lo, hi) in PERIODS.items():
                    m = pd.Series(True, index=c)
                    if lo is not None:
                        m &= c >= lo
                    if hi is not None:
                        m &= c < hi
                    if not m.any():
                        continue
                    yrs = (c[m][-1] - c[m][0]).days / 365.25
                    tot = float(ex_[m].sum())
                    contrib = []
                    for _, e in eps_.iterrows():
                        pk_, z_ = pd.Timestamp(e["peak_date"]), pd.Timestamp(e["rebound_end_date"])
                        mm = m & (c > pk_) & (c <= z_)
                        if mm.any():
                            contrib.append((e["label"], float(ex_[mm].sum())))
                    contrib.sort(key=lambda t: -t[1])
                    top1 = contrib[0] if contrib else ("", 0.0)
                    top2 = contrib[1] if len(contrib) > 1 else ("", 0.0)
                    worst = contrib[-1] if contrib else ("", 0.0)
                    CC.append({"definition": dfn, "leg": leg, "sleeve": sleeve, "rule": rn, "period": pr,
                               "years": yrs, "total_log_excess": tot, "total_log_per_year": tot / yrs,
                               "episodes_in_period": len(contrib),
                               "episodes_positive": sum(1 for _, v in contrib if v > 0),
                               "best_episode": top1[0], "best_episode_log": top1[1],
                               "second_episode": top2[0], "second_episode_log": top2[1],
                               "worst_episode": worst[0], "worst_episode_log": worst[1],
                               "ex_best_log_per_year": (tot - top1[1]) / yrs,
                               "ex_best2_log_per_year": (tot - top1[1] - top2[1]) / yrs})
pd.DataFrame(CC).to_csv(out("concentration"), index=False)


# ── 4. false exits ─────────────────────────────────────────────────────────
# Every 1->0 switch. "True" = the index (Friday closes, from the exit fill close)
# fell a further 10%+ within 26 weeks; otherwise "false". Undetermined if the
# 26 weeks run past 2026-08-21. Costs: 13-week index minus cash return from the
# fill, the 13-week rule-minus-bh NAV difference (includes any re-entry), and the
# whole out-period (exit fill -> next entry fill) as log(NAV_rule/NAV_bh).
FX = []
for (leg, rn, sleeve), dec in DEC.items():
    if rn == "bh":
        continue
    nav = NAV[(leg, rn, sleeve)]
    navbh = NAV[(leg, "bh", sleeve)]
    c = nav.index
    lvd = LVL[leg]
    exits = switches(dec, c, "exit")
    entries = switches(dec, c, "entry")
    for R, f in exits:
        if R < c[0]:
            continue
        x0 = float(lvd.loc[f])
        h26, h13 = f + pd.Timedelta(days=182), f + pd.Timedelta(days=91)
        fwd = lvd.loc[(lvd.index > f) & (lvd.index <= h26)]
        determined = h26 <= END
        fri_min = float(fwd.resample("W-FRI").last().min() / x0 - 1) if len(fwd) else np.nan
        day_min = float(fwd.min() / x0 - 1) if len(fwd) else np.nan
        i13 = at(lvd, h13) / x0 - 1
        i26 = at(lvd, h26) / x0 - 1
        c13 = at(CASH_D, h13) / float(CASH_D.loc[f]) - 1
        n13 = at(nav, h13) / float(nav.loc[f]) - 1
        b13 = at(navbh, h13) / float(navbh.loc[f]) - 1
        nxt = [(E, fe_) for E, fe_ in entries if E > R]
        fe_ = nxt[0][1] if nxt else c[-1]
        FX.append({"leg": leg, "rule": rn, "sleeve": sleeve, "exit_decision": R.date(), "exit_fill": f.date(),
                   "sample": "oos" if R < IS0 else "in-sample",
                   "determined_26w": bool(determined),
                   "index_fall_from_52w_high_at_fill": float(x0 / lvd.loc[f - pd.Timedelta(days=364):f].max() - 1),
                   "further_fall_26w_friday": fri_min, "further_fall_26w_daily": day_min,
                   "true_exit_friday": bool(fri_min <= -THR) if determined else None,
                   "true_exit_daily": bool(day_min <= -THR) if determined else None,
                   "index_ret_13w": i13, "index_ret_26w": i26, "cash_ret_13w": c13,
                   "missed_13w_index_minus_cash": i13 - c13,
                   "rule_minus_bh_nav_13w": n13 - b13,
                   "reentry_decision": nxt[0][0].date() if nxt else None,
                   "weeks_out": (nxt[0][0] - R).days / 7 if nxt else None,
                   "index_ret_out_period": float(lvd.loc[fe_]) / x0 - 1,
                   "out_period_log_rule_vs_bh": float(np.log(nav.loc[fe_] / nav.loc[f]) -
                                                      np.log(navbh.loc[fe_] / navbh.loc[f]))})
fx = pd.DataFrame(FX)
fx.to_csv(out("exits"), index=False)

fs = []
groups = list(fx.groupby(["sleeve", "leg", "rule", "sample"])) +     [((s_, l, r, "all"), g) for (s_, l, r), g in fx.groupby(["sleeve", "leg", "rule"])]
for (sleeve, leg, rn, smp), g in groups:
    d = g[g["determined_26w"]]
    fe = d[d["true_exit_friday"] == False]   # noqa: E712
    te = d[d["true_exit_friday"] == True]    # noqa: E712
    fs.append({"sleeve": sleeve, "leg": leg, "rule": rn, "sample": smp, "exits": len(g), "determined": len(d),
               "false_exits": len(fe), "false_share_friday": len(fe) / len(d) if len(d) else np.nan,
               "false_share_daily": float((d["true_exit_daily"] == False).mean()) if len(d) else np.nan,  # noqa: E712
               "false_cost_13w_mean": fe["missed_13w_index_minus_cash"].mean(),
               "false_cost_13w_median": fe["missed_13w_index_minus_cash"].median(),
               "false_rule_minus_bh_13w_mean": fe["rule_minus_bh_nav_13w"].mean(),
               "false_weeks_out_median": fe["weeks_out"].median(),
               "false_out_period_log_sum": fe["out_period_log_rule_vs_bh"].sum(),
               "false_out_period_log_mean": fe["out_period_log_rule_vs_bh"].mean(),
               "true_exits": len(te),
               "true_benefit_13w_mean": -te["missed_13w_index_minus_cash"].mean(),
               "true_further_fall_26w_mean": te["further_fall_26w_friday"].mean(),
               "true_rule_minus_bh_13w_mean": te["rule_minus_bh_nav_13w"].mean(),
               "true_weeks_out_median": te["weeks_out"].median(),
               "true_out_period_log_sum": te["out_period_log_rule_vs_bh"].sum(),
               "true_out_period_log_mean": te["out_period_log_rule_vs_bh"].mean(),
               "all_exits_index_minus_cash_13w_mean": d["missed_13w_index_minus_cash"].mean(),
               "all_exits_rule_minus_bh_13w_mean": d["rule_minus_bh_nav_13w"].mean(),
               "all_out_periods_log_sum_incl_undetermined": g["out_period_log_rule_vs_bh"].sum(),
               "best_out_period_exit": g.loc[g["out_period_log_rule_vs_bh"].idxmax(), "exit_decision"],
               "best_out_period_log": g["out_period_log_rule_vs_bh"].max(),
               "all_out_periods_ex_best_log": g["out_period_log_rule_vs_bh"].sum() - g["out_period_log_rule_vs_bh"].max()})
fxs = pd.DataFrame(fs)
fxs.to_csv(out("false_exit_summary"), index=False)


# ── 5. narrative, 20%+ SC100 episodes ──────────────────────────────────────
NR = []
e20 = ep[(ep["leg"] == "SC100") & ep["is_20plus"]]
for _, e in e20.iterrows():
    for sleeve in ("cash", "5050"):
        x = er[(er["episode"] == e["episode"]) & (er["sleeve"] == sleeve)].set_index("rule")
        if x.empty:
            continue
        fills = {rn: x.loc[rn, "first_exit_fill"] for rn in ("pair", "triple", "sc100")
                 if rn in x.index and pd.notna(x.loc[rn].get("first_exit_fill"))}
        outp = {rn: bool(x.loc[rn, "out_at_peak"]) for rn in ("pair", "triple", "sc100")}
        pre_out = [rn for rn, v in outp.items() if v]
        if fills:
            first_d = min(pd.Timestamp(v) for v in fills.values())
            first = [rn for rn, v in fills.items() if pd.Timestamp(v) == first_d]
        else:
            first_d, first = None, []
        pk_ = pd.Timestamp(e["peak_date"])
        sig_pk = sg.loc[:pk_ - pd.Timedelta(days=1), ["N100", "MC100", "SC100"]].dropna().iloc[-1]
        row = {"episode": e["episode"], "definition": e["definition"], "label": e["label"], "sleeve": sleeve,
               "signals_in_force_at_peak": " ".join(f"{k}={'BUY' if v == 1 else 'SELL'}" for k, v in sig_pk.items()),
               "peak": e["peak_date"], "trough": e["trough_date"], "recovery": e["recovery_date"],
               "depth_friday": e["depth_friday"], "depth_daily_worst": e["depth_daily_worst"],
               "speed": e["speed"], "sample": e["sample"],
               "already_out_at_peak": "+".join(pre_out) if pre_out else "none",
               "first_exit_rule": "+".join(first) if first else "none",
               "first_exit_fill": first_d.date() if first_d is not None else None}
        for rn in ("pair", "triple", "sc100", "bh"):
            row[f"{rn}_exit_fill"] = x.loc[rn].get("first_exit_fill") if rn != "bh" else None
            row[f"{rn}_exit_fall"] = x.loc[rn].get("exit_index_fall_at_fill") if rn != "bh" else None
            row[f"{rn}_entry_fill"] = x.loc[rn].get("first_entry_fill") if rn != "bh" else None
            row[f"{rn}_entry_rise"] = x.loc[rn].get("entry_index_rise_at_fill") if rn != "bh" else None
            row[f"{rn}_p2t"] = x.loc[rn, "ret_peak_to_trough"]
            row[f"{rn}_t2r"] = x.loc[rn, "ret_trough_to_recovery"]
            row[f"{rn}_p2r"] = x.loc[rn, "ret_peak_to_recovery"]
            row[f"{rn}_worst_friday"] = x.loc[rn, "worst_fall_in_episode_friday"]
        row["pair_minus_sc100_p2r"] = row["pair_p2r"] - row["sc100_p2r"]
        row["pair_minus_bh_p2r"] = row["pair_p2r"] - row["bh_p2r"]
        row["pair_minus_triple_p2r"] = row["pair_p2r"] - row["triple_p2r"]
        pct = lambda v: f"{v * 100:+.1f}%"
        def ex_txt(rn):
            if outp[rn]:
                return f"{rn} out at peak"
            if pd.notna(row[f"{rn}_exit_fill"]):
                return f"{rn} exit {row[f'{rn}_exit_fill']} at {pct(row[f'{rn}_exit_fall'])}"
            return f"{rn} no exit"
        end_txt = f"recovered {e['recovery_date']}" if e["recovered"] else f"rebound leg to {e['rebound_end_date']} ({e['rebound_end_is']})"
        row["narrative"] = (f"{e['label']} ({e['definition']}, {sleeve}): SC100 {pct(e['depth_friday'])} from {e['peak_date']} "
                            f"to {e['trough_date']}, {end_txt}; {e['speed']}, {e['sample']}. Signals at peak: "
                            f"{row['signals_in_force_at_peak']}. {ex_txt('pair')}; {ex_txt('sc100')}. Peak to end: pair "
                            f"{pct(row['pair_p2r'])}, sc100 {pct(row['sc100_p2r'])}, bh {pct(row['bh_p2r'])}; pair minus sc100 "
                            f"{row['pair_minus_sc100_p2r'] * 100:+.1f} pp, pair minus bh {row['pair_minus_bh_p2r'] * 100:+.1f} pp. "
                            f"Worst Friday fall inside: pair {pct(row['pair_worst_friday'])}, bh {pct(row['bh_worst_friday'])}.")
        NR.append(row)
nr = pd.DataFrame(NR)
nr.to_csv(out("sc100_20plus_narrative"), index=False)

print("episodes:", len(ep), "rule rows:", len(er), "exits:", len(fx))
print(ep.groupby(["leg", "definition"]).size())
