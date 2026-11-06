# -*- coding: utf-8 -*-
"""
Part 2: signal diagnostics on Smallcap 100 for the weekly decision series
of pair (N100 AND SC100), sc100 (= SC100's own SIGN, so 'own' is identical
on SC100), triple (N100 AND MC100 AND SC100) and, for context, n100.

Each transition dated review R trades at the close of the next session
(the "trade session", as in the engine). Prices are SC100 daily closes.
Per transition:
  entry: lag % = close(trade) / min close since the previous exit's trade - 1
         lag weeks = weeks from that low to the trade session
         false entry = close 13 weeks (91 days) after the trade < close at trade
  exit : give-back % = close(trade) / max close since the previous entry's trade - 1
         false exit = close 13 weeks after the trade > close at trade
  spell: length in weekly reviews; SC100 return from the spell's trade
         session to the next transition's trade session. For an
         out-of-market spell a positive value means the rule bought back
         higher than it sold.
Transitions and spells are assigned to a window by the review date that
starts them. Spells still open at 2026-08-21 are censored (excluded from
length stats). Whipsaw = a completed spell of 4 weeks or less.

The *_inside log sums keep only spells that close inside the window (the
pair's 2021-10-29 exit, e.g., closes in 2022, in-sample).
Outputs: mechanism_signal_events.csv (one row per spell)
         mechanism_signal_diagnostics.csv (per rule x window)
"""

from __future__ import annotations

import numpy as np
import pandas as pd

import deep_mechanism_data as M

cal, sg, lv, gc = M.load()
s = sg.loc[(sg.index >= M.SIG_START) & (sg.index <= M.END), ["N100", "SC100", "MC100"]].dropna()
px = lv["SC100"].dropna()
cash = gc["cash"]
WINDOWS = [("OOS 2007-07..2021-10", M.OOS_START, M.OOS_END),
           ("OOS 2007-07..2013-12", M.OOS_START, pd.Timestamp("2013-12-31")),
           ("OOS 2014-01..2021-10", pd.Timestamp("2014-01-01"), M.OOS_END),
           ("IS 2021-11..2026-08", M.IS_START, M.IS_END),
           ("ALL 2006-01..2026-08", M.SIG_START, M.END)]
RULES = {"pair": s["N100"] * s["SC100"], "sc100": s["SC100"], "own": s["SC100"],
         "triple": s["N100"] * s["MC100"] * s["SC100"], "n100": s["N100"]}


def fwd_close(t, days):
    e = t + pd.Timedelta(days=days)
    if e > M.END:
        return np.nan
    return float(px.loc[:e].iloc[-1])


ev_rows = []
for rn, d in RULES.items():
    d = d.astype(int)
    rid = d.ne(d.shift()).cumsum()
    runs = [(g.index[0], g.index[-1], int(g.iloc[0]), len(g)) for _, g in d.groupby(rid)]
    for k, (r0, r_last, val, n) in enumerate(runs):
        if k == 0:
            continue                       # starts with history, not a transition
        t0 = M.trade_session(cal, r0)
        nxt = runs[k + 1][0] if k + 1 < len(runs) else None
        t1 = M.trade_session(cal, nxt) if nxt is not None else None
        prev_t = M.trade_session(cal, runs[k - 1][0]) if k - 1 >= 1 else px.index[px.index >= M.SIG_START][0]
        seg = px.loc[prev_t:t0]
        p0 = float(px.loc[t0])
        f13 = fwd_close(t0, 91)
        row = {"rule": rn, "review": r0, "trade_session": t0, "kind": "entry" if val == 1 else "exit",
               "spell_weeks": n, "complete": nxt is not None, "next_review": nxt,
               "close_at_trade": p0, "fwd13w_ret": f13 / p0 - 1 if pd.notna(f13) else np.nan}
        if val == 1:
            lo_d = seg.idxmin()
            row.update({"entry_lag_pct": p0 / float(seg.min()) - 1, "entry_lag_weeks": (t0 - lo_d).days / 7,
                        "false_entry": bool(f13 < p0) if pd.notna(f13) else np.nan})
        else:
            hi_d = seg.idxmax()
            row.update({"exit_giveback_pct": p0 / float(seg.max()) - 1, "exit_weeks_from_high": (t0 - hi_d).days / 7,
                        "false_exit": bool(f13 > p0) if pd.notna(f13) else np.nan})
        if t1 is not None:
            row["spell_sc100_ret"] = float(px.loc[t1]) / p0 - 1
            row["spell_cash_ret"] = float(cash.loc[t1] / cash.loc[t0] - 1) if pd.notna(cash.get(t0)) else np.nan
            seg2 = px.loc[t0:t1]
            row["spell_min_ret"] = float(seg2.min()) / p0 - 1
            row["spell_max_ret"] = float(seg2.max()) / p0 - 1
        ev_rows.append(row)
ev = pd.DataFrame(ev_rows)
ev.to_csv(M.OUT / "mechanism_signal_events.csv", index=False)


def med(x):
    x = pd.Series(x).dropna()
    return float(x.median()) if len(x) else np.nan


def mean(x):
    x = pd.Series(x).dropna()
    return float(x.mean()) if len(x) else np.nan


rows = []
for wl, a, b in WINDOWS:
    for rn, d in RULES.items():
        e = ev[(ev.rule == rn) & (ev.review >= a) & (ev.review <= b)]
        en, ex = e[e.kind == "entry"], e[e.kind == "exit"]
        enc, exc = en[en.complete], ex[ex.complete]
        dd = d[(d.index >= a) & (d.index <= b)]
        fe = en["false_entry"].dropna().astype(bool)
        fx = ex["false_exit"].dropna().astype(bool)
        ws_in, ws_out = enc[enc.spell_weeks <= 4], exc[exc.spell_weeks <= 4]
        rows.append({
            "window": wl, "rule": rn, "identical_to": "sc100" if rn == "own" else "",
            "weeks": len(dd), "time_in_market": float(dd.mean()),
            "entries": len(en), "exits": len(ex),
            "in_spells_complete": len(enc), "in_spell_median_wk": med(enc.spell_weeks), "in_spell_mean_wk": mean(enc.spell_weeks),
            "out_spells_complete": len(exc), "out_spell_median_wk": med(exc.spell_weeks), "out_spell_mean_wk": mean(exc.spell_weeks),
            "whipsaw_in_spells_le4w": len(ws_in), "whipsaw_in_share": len(ws_in) / len(enc) if len(enc) else np.nan,
            "whipsaw_out_spells_le4w": len(ws_out), "whipsaw_out_share": len(ws_out) / len(exc) if len(exc) else np.nan,
            "whipsaw_in_sc100_logret_sum": float(np.log1p(ws_in.spell_sc100_ret).sum()),
            "whipsaw_out_sc100_logret_sum": float(np.log1p(ws_out.spell_sc100_ret).sum()),
            "false_exits": int(fx.sum()), "false_exit_share": float(fx.mean()) if len(fx) else np.nan, "exits_with_fwd": len(fx),
            "false_entries": int(fe.sum()), "false_entry_share": float(fe.mean()) if len(fe) else np.nan, "entries_with_fwd": len(fe),
            "median_entry_lag_pct": med(en.entry_lag_pct), "mean_entry_lag_pct": mean(en.entry_lag_pct),
            "median_entry_lag_weeks": med(en.entry_lag_weeks),
            "median_exit_giveback_pct": med(ex.exit_giveback_pct), "mean_exit_giveback_pct": mean(ex.exit_giveback_pct),
            "median_exit_weeks_from_high": med(ex.exit_weeks_from_high),
            "median_fwd13w_after_exit": med(ex.fwd13w_ret), "mean_fwd13w_after_exit": mean(ex.fwd13w_ret),
            "median_fwd13w_after_entry": med(en.fwd13w_ret), "mean_fwd13w_after_entry": mean(en.fwd13w_ret),
            "out_spell_median_sc100_ret": med(exc.spell_sc100_ret),
            "out_spell_share_rebought_higher": float((exc.spell_sc100_ret > 0).mean()) if len(exc) else np.nan,
            "out_spell_sc100_logret_sum": float(np.log1p(exc.spell_sc100_ret).sum()),
            "out_spell_sc100_logret_sum_inside": float(np.log1p(exc[exc.next_review <= b].spell_sc100_ret).sum()),
            "in_spell_sc100_logret_sum_inside": float(np.log1p(enc[enc.next_review <= b].spell_sc100_ret).sum()),
            "spells_crossing_window_end": int(((e.next_review > b) & e.complete).sum()),
            "out_spell_median_min_ret": med(exc.spell_min_ret),
            "in_spell_median_sc100_ret": med(enc.spell_sc100_ret),
            "in_spell_share_losing": float((enc.spell_sc100_ret < 0).mean()) if len(enc) else np.nan,
            "in_spell_sc100_logret_sum": float(np.log1p(enc.spell_sc100_ret).sum()),
        })
diag = pd.DataFrame(rows)
diag.to_csv(M.OUT / "mechanism_signal_diagnostics.csv", index=False)

pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 60)
show = ["window", "rule", "time_in_market", "entries", "exits", "in_spell_median_wk", "in_spell_mean_wk",
        "out_spell_median_wk", "out_spell_mean_wk", "whipsaw_in_spells_le4w", "whipsaw_out_spells_le4w",
        "false_exits", "false_exit_share", "false_entries", "false_entry_share", "median_entry_lag_pct",
        "median_entry_lag_weeks", "median_exit_giveback_pct", "median_exit_weeks_from_high"]
print(diag[show].round(3).to_string(index=False))
show2 = ["window", "rule", "median_fwd13w_after_exit", "median_fwd13w_after_entry", "out_spell_median_sc100_ret",
         "out_spell_share_rebought_higher", "out_spell_sc100_logret_sum", "out_spell_sc100_logret_sum_inside", "in_spell_median_sc100_ret",
         "in_spell_share_losing", "in_spell_sc100_logret_sum", "in_spell_sc100_logret_sum_inside", "whipsaw_in_sc100_logret_sum", "whipsaw_out_sc100_logret_sum"]
print(diag[show2].round(3).to_string(index=False))
