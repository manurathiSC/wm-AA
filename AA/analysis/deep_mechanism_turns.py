# -*- coding: utf-8 -*-
"""
Part 4: lead-lag at the major SC100 turns (HINDSIGHT turn dating).

Turns: a symmetric 20% zigzag on SC100 daily closes, 2006-01 -> 2026-08-21.
  tops    = every swing peak (each is followed by a fall of >= 20%);
  bottoms = every swing trough, classed 'major' if the rally that follows is
            >= 30% (the last rally, to 2026-08-21, is still open) and
            'bear-rally low' if it is 20-30%.
Flip dates, per signal (N100, SC100, MC100, pair, triple):
  at a top    the first review on/after the peak with the signal SELL, walked
              back to the start of that SELL run (so a flip before the peak
              gives negative weeks);
  at a bottom the same with BUY.
Weeks = (flip review - turn date) / 7. Levels are SC100 closes at the flip's
trade session (next session after the review).
Per leg (peak -> trough, trough -> next peak): the share of the leg's SC100
log move each rule actually took, from the engine's daily weights
(why_n100sc100.daily_weight), i.e. sum over in-market days of ln(1+r).

Outputs: mechanism_turns.csv (one row per turn), mechanism_turn_legs.csv
(one row per leg x rule), mechanism_turns_summary.csv, mechanism_turn_legs_summary.csv.
Tops are 'major' if the rally into them was >= 30%, else 'bear-rally top'.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

import deep_mechanism_data as M
from why_n100sc100 import daily_weight

cal, sg, lv, gc = M.load()
s = sg.loc[(sg.index >= M.SIG_START) & (sg.index <= M.END), ["N100", "SC100", "MC100"]].dropna()
px = lv["SC100"].dropna()
px = px[px.index <= M.END]
SIG = {"N100": s["N100"], "SC100": s["SC100"], "MC100": s["MC100"],
       "pair": s["N100"] * s["SC100"], "triple": s["N100"] * s["MC100"] * s["SC100"]}
c_all = cal[(cal >= M.SIG_START) & (cal <= M.END)]
WD = {k: daily_weight(v, c_all).reindex(c_all).ffill() for k, v in SIG.items()}
WD["bh"] = pd.Series(1.0, index=c_all)
lr = np.log1p(px.reindex(c_all).pct_change())

zz = M.zigzag(px[px.index >= pd.Timestamp("2005-01-01")], 0.20)
zz = zz.reset_index(drop=True)


def flip(d: pd.Series, t: pd.Timestamp, to: int):
    after = d[d.index >= t]
    hit = after[after == to]
    if hit.empty:
        return None
    R = hit.index[0]
    before = d[d.index <= R]
    other = before[before != to]
    if other.empty:
        return before.index[0]
    return before.index[before.index > other.index[-1]][0]


def lvl(r):
    ts = M.trade_session(cal, r)
    return float(px.loc[ts]) if ts is not None and ts in px.index else np.nan


rows, legs = [], []
for i in range(len(zz)):
    t, v, kind = zz.date[i], zz.level[i], zz.kind[i]
    if t < M.SIG_START + pd.Timedelta(days=60) or not zz.confirmed[i]:
        continue
    nxt = zz.iloc[i + 1] if i + 1 < len(zz) else None
    move = nxt.level / v - 1 if nxt is not None else np.nan
    if kind == "peak":
        prev_move = v / zz.level[i - 1] - 1 if i >= 1 else np.inf
        klass = "major top" if prev_move >= 0.30 else "bear-rally top"
    else:
        klass = "major bottom" if move >= 0.30 else "bear-rally low"
    to = 0 if kind == "peak" else 1
    row = {"turn": klass, "date": t.date(), "level": v, "next_turn": nxt.date.date() if nxt is not None else None,
           "next_turn_confirmed": bool(nxt.confirmed) if nxt is not None else None,
           "move_to_next_turn": move, "sample": "IS" if t >= M.IS_START else "OOS"}
    for k, d in SIG.items():
        f = flip(d, t, to)
        row[f"{k}_flip"] = f.date() if f is not None else None
        row[f"{k}_weeks"] = (f - t).days / 7 if f is not None else np.nan
        L = lvl(f) if f is not None else np.nan
        row[f"{k}_sc100_vs_turn"] = L / v - 1          # top: give-back (<0); bottom: rise missed (>0)
        if nxt is not None and pd.notna(L):
            row[f"{k}_sc100_to_next_turn"] = nxt.level / L - 1   # top: fall still ahead; bottom: rally still ahead
        row[f"{k}_after_next_turn"] = bool(f is not None and nxt is not None and f > nxt.date)
    # which flips first (N100 vs SC100)
    lead = row["SC100_weeks"] - row["N100_weeks"]      # > 0: N100 flipped first
    row["n100_lead_weeks"] = lead
    row["first"] = "N100" if lead > 0 else ("SC100" if lead < 0 else "same week")
    if kind == "peak":
        row["pair_saving_weeks"] = row["SC100_weeks"] - row["pair_weeks"]
        row["pair_saving_sc100_pct"] = (row["SC100_sc100_vs_turn"] + 1) / (row["pair_sc100_vs_turn"] + 1) - 1
        # SC100 move between the pair's exit and SC100's own exit (negative = the pair avoided it)
    else:
        row["pair_cost_weeks"] = row["pair_weeks"] - row["SC100_weeks"]
        row["pair_cost_sc100_pct"] = (row["pair_sc100_vs_turn"] + 1) / (row["SC100_sc100_vs_turn"] + 1) - 1
    rows.append(row)
    # legs: share of the SC100 log move taken while in the market
    if nxt is not None:
        a, b = t, nxt.date
        days = c_all[(c_all > a) & (c_all <= b)]
        tot = float(lr.reindex(days).sum())
        for k, w in WD.items():
            taken = float((lr.reindex(days) * w.reindex(days)).sum())
            n_entries = int(((SIG[k] if k in SIG else pd.Series(1.0, index=s.index)).loc[a:b].diff() > 0).sum())
            legs.append({"leg": "decline" if kind == "peak" else ("rally>=30%" if move >= 0.30 else "bear rally 20-30%"),
                         "from": a.date(), "to": b.date(), "to_confirmed": bool(nxt.confirmed),
                         "sample": "IS" if a >= M.IS_START else ("mixed" if b >= M.IS_START else "OOS"),
                         "sc100_move": float(nxt.level / v - 1), "sc100_log_move": tot, "rule": k,
                         "log_taken": taken, "share_taken": taken / tot if tot else np.nan,
                         "time_in_market": float(w.reindex(days).mean()), "entries_in_leg": n_entries})

tu = pd.DataFrame(rows)
tu.to_csv(M.OUT / "mechanism_turns.csv", index=False)
lg = pd.DataFrame(legs)
lg.to_csv(M.OUT / "mechanism_turn_legs.csv", index=False)

# ── summary ────────────────────────────────────────────────────────────────
srows = []
for samp in ("OOS", "IS", "ALL"):
    for klass in ("major top", "bear-rally top", "major bottom", "bear-rally low"):
        x = tu[(tu.turn == klass) & ((tu["sample"] == samp) | (samp == "ALL"))]
        if x.empty:
            continue
        r = {"sample": samp, "turn": klass, "n": len(x),
             "n100_first": int((x["first"] == "N100").sum()), "sc100_first": int((x["first"] == "SC100").sum()),
             "same_week": int((x["first"] == "same week").sum()),
             "median_n100_lead_weeks": float(x.n100_lead_weeks.median()),
             "mean_n100_lead_weeks": float(x.n100_lead_weeks.mean())}
        for k in SIG:
            r[f"median_{k}_weeks"] = float(x[f"{k}_weeks"].median())
            r[f"median_{k}_sc100_vs_turn"] = float(x[f"{k}_sc100_vs_turn"].median())
        if klass.endswith("top"):
            r["median_pair_saving_weeks"] = float(x.pair_saving_weeks.median())
            r["mean_pair_saving_weeks"] = float(x.pair_saving_weeks.mean())
            r["median_pair_saving_sc100_pct"] = float(x.pair_saving_sc100_pct.median())
            r["mean_pair_saving_sc100_pct"] = float(x.pair_saving_sc100_pct.mean())
            r["tops_pair_earlier"] = int((x.pair_saving_weeks > 0).sum())
        else:
            r["median_pair_cost_weeks"] = float(x.pair_cost_weeks.median())
            r["mean_pair_cost_weeks"] = float(x.pair_cost_weeks.mean())
            r["median_pair_cost_sc100_pct"] = float(x.pair_cost_sc100_pct.median())
            r["mean_pair_cost_sc100_pct"] = float(x.pair_cost_sc100_pct.mean())
            r["bottoms_pair_later"] = int((x.pair_cost_weeks > 0).sum())
        srows.append(r)
sm = pd.DataFrame(srows)
sm.to_csv(M.OUT / "mechanism_turns_summary.csv", index=False)
lrows = []
for samp in ("OOS", "IS", "ALL"):
    for leg in ("decline", "rally>=30%", "bear rally 20-30%"):
        y = lg[(lg.leg == leg) & ((lg["sample"] == samp) | (samp == "ALL"))]
        if y.empty:
            continue
        for k in list(SIG) + ["bh"]:
            z = y[y.rule == k]
            lrows.append({"sample": samp, "turn": f"LEG {leg}", "rule": k, "n": len(z),
                          "sum_log_move": float(z.sc100_log_move.sum()), "sum_log_taken": float(z.log_taken.sum()),
                          "share_taken_pooled": float(z.log_taken.sum() / z.sc100_log_move.sum()),
                          "median_share_taken": float(z.share_taken.median()),
                          "entries_in_legs": int(z.entries_in_leg.sum())})
ls_ = pd.DataFrame(lrows)
ls_.to_csv(M.OUT / "mechanism_turn_legs_summary.csv", index=False)

pd.set_option("display.width", 260)
pd.set_option("display.max_columns", 80)
print(tu[["turn", "date", "move_to_next_turn", "sample", "N100_flip", "N100_weeks", "SC100_flip", "SC100_weeks",
          "pair_weeks", "first", "n100_lead_weeks", "SC100_sc100_vs_turn", "pair_sc100_vs_turn",
          "pair_saving_weeks", "pair_saving_sc100_pct", "pair_cost_weeks", "pair_cost_sc100_pct",
          "SC100_after_next_turn", "N100_after_next_turn"]].round(3).to_string(index=False))
print(sm.round(3).T.to_string())
print(ls_.round(3).to_string(index=False))
print(lg[lg.rule.isin(["SC100", "pair", "N100", "bh"])].pivot_table(
    index=["leg", "from", "to", "sc100_move"], columns="rule", values="share_taken").round(2).to_string())
