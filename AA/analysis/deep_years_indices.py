# -*- coding: utf-8 -*-
"""
Deep dive, analyst "years": every calendar year, 2007 -> 2026, on the indices.

For each equity leg (N50, N100, MC100, SC100, blend; MC150, SC250, Micro250
where their signals exist), each rule (pair, triple, sc100, own, bh) and each
sleeve (cash from 2007-07-02; 50/50 gold/cash and all gold from 2014-07-07):

  * ONE continuous NAV per (leg, sleeve, rule) over the whole window, built
    with why_n100sc100.run_rs (20.8 bps per full switch, Friday decision
    traded at the next session's close, first earning the session after).
  * The NAV is sliced by calendar year. The position carries across year ends.
    2021 is sliced three ways: the whole year (sample = "mixed"), Jan -> Oct 29
    (out of sample) and Oct 29 close -> Dec 31 (in-sample stub; it includes
    2021-11-01/02, two sessions before the 2021-11-03 in-sample start, which
    are thereby kept out of the out-of-sample evidence).
  * Per slice: return, worst fall on daily closes and on Friday closes, share
    of sessions in equity, switches (exits / entries), and a decomposition:
    equity return while in, equity return while out (what bh earned while the
    rule sat in the sleeve), sleeve return while out, and cost paid.

Also: hindsight regime labels per slice from SC100 and N100 buy-and-hold,
the pair's signal path (every out-spell with trigger, dates and what the
index did while out), and a sanity check against triple_index_results.csv.

Writes evidence/why_n100sc100/deep/years_*.csv.
"""

from __future__ import annotations

import os

import numpy as np
import pandas as pd

from why_n100sc100 import COST, OUT, calendar, daily_weight, gold_cash, run_rs, weekly_signs, cagr, mdd
from triple_and_test import index_levels

DEEP = OUT / "deep"
os.makedirs(DEEP, exist_ok=True)

END = pd.Timestamp("2026-08-21")
CASH_START = pd.Timestamp("2007-07-02")
GOLD_START = pd.Timestamp("2014-07-07")
OOS_END = pd.Timestamp("2021-10-29")
IS_START = pd.Timestamp("2021-11-03")

CORE = ["N50", "N100", "MC100", "SC100", "blend"]
SHORT = ["MC150", "SC250", "Micro250"]
OWN = {"N50": "N50", "N100": "N100", "MC100": "MC100", "SC100": "SC100",
       "MC150": "MC150", "SC250": "SC250", "Micro250": "Micro250", "blend": None}
RULES = ["pair", "triple", "sc100", "own", "bh"]
SLEEVES = {"cash": CASH_START, "50/50": GOLD_START, "gold": GOLD_START}


def rule_decisions(ss: pd.DataFrame, own: str | None) -> dict:
    d = {"pair": ss["N100"] * ss["SC100"],
         "triple": ss["N100"] * ss["MC100"] * ss["SC100"],
         "sc100": ss["SC100"],
         "bh": pd.Series(1.0, index=ss.index)}
    if own is not None:
        d["own"] = ss[own]
    return d


def slices(c: pd.DatetimeIndex) -> list[dict]:
    """Calendar-year slices of window c: (label, base date, last date, sample, partial)."""
    out = []
    for y in range(c[0].year, c[-1].year + 1):
        in_y = c[c.year == y]
        if len(in_y) == 0:
            continue
        prev = c[c < in_y[0]]
        base = prev[-1] if len(prev) else in_y[0]
        last = in_y[-1]
        # partial if the window starts after the first session of the year, or ends before year end
        partial = (len(prev) == 0 and in_y[0] > pd.Timestamp(f"{y}-01-05")) or last < pd.Timestamp(f"{y}-12-24")
        if y < 2021:
            out.append(dict(period=str(y), year=y, base=base, last=last, sample="OOS", partial=partial))
        elif y > 2021:
            out.append(dict(period=str(y), year=y, base=base, last=last, sample="IS", partial=partial))
        else:
            out.append(dict(period="2021", year=y, base=base, last=last, sample="mixed", partial=partial))
            if base < OOS_END:
                out.append(dict(period="2021-OOS", year=y, base=base, last=OOS_END, sample="OOS", partial=True))
                out.append(dict(period="2021-IS", year=y, base=OOS_END, last=last, sample="IS", partial=True))
            else:
                out.append(dict(period="2021-IS", year=y, base=base, last=last, sample="IS", partial=True))
    return out


def seg_dd(nav_seg: pd.Series) -> float:
    return float((nav_seg / nav_seg.cummax() - 1).min())


def friday_seg(nav: pd.Series, base: pd.Timestamp, last: pd.Timestamp, wk: pd.Series) -> pd.Series:
    """Base close, the Friday closes strictly inside (base, last], and the last close."""
    f = wk[(wk.index > base) & (wk.index <= last)]
    pts = pd.concat([nav.loc[[base]], f, nav.loc[[last]]])
    return pts[~pts.index.duplicated(keep="last")].sort_index()


def main() -> None:
    cal = calendar()
    cal = cal[cal <= END]
    sg = weekly_signs()
    sg = sg[sg.index <= END]
    lv = index_levels(cal)
    gc = gold_cash(cal)

    first_sig = {k: sg[OWN[k]].first_valid_index() for k in SHORT}
    rows, spell_rows, checks, navs = [], [], [], {}
    for sl, s_start in SLEEVES.items():
        for leg in CORE + SHORT:
            a = s_start
            if leg in SHORT:
                a = max(a, first_sig[leg] + pd.Timedelta(days=3))
            c = cal[(cal >= a) & (cal <= END)]
            a = c[0]
            # equity leg returns
            if leg == "blend":
                r_eq = (lv["N100"].reindex(c).pct_change() + lv["MC100"].reindex(c).pct_change()
                        + lv["SC100"].reindex(c).pct_change()) / 3
            else:
                r_eq = lv[leg].reindex(c).pct_change()
            n_nan = int(r_eq.iloc[1:].isna().sum())
            r_eq = r_eq.fillna(0.0)
            # sleeve returns: pick the legs explicitly
            rc = gc["cash"].reindex(c).pct_change()
            rg = gc["gold"].reindex(c).pct_change()
            if sl == "cash":
                r_sl = rc.fillna(0.0)
            elif sl == "gold":
                r_sl = rg.fillna(0.0)
            else:
                r_sl = (0.5 * rg + 0.5 * rc).fillna(0.0)
            own = OWN[leg]
            need = list(dict.fromkeys(["N100", "MC100", "SC100"] + ([own] if own else [])))
            ss = sg.loc[(sg.index >= a - pd.Timedelta(days=7)) & (sg.index <= END), need].dropna()
            for rn, dec in rule_decisions(ss, own).items():
                nav = run_rs(dec, r_eq, r_sl, c, cost_bps=COST)
                w = daily_weight(dec, c).reindex(c).ffill().fillna(1.0)
                dw = w.diff().fillna(0.0)
                cost = dw.abs() * COST / 1e4
                navs[(leg, sl, rn)] = nav
                wk = nav.resample("W-FRI").last()
                for s in slices(c):
                    base, last = s["base"], s["last"]
                    seg = nav[(nav.index >= base) & (nav.index <= last)]
                    days = c[(c > base) & (c <= last)]          # sessions whose return the slice earns
                    wd, re_, rs_ = w.reindex(days), r_eq.reindex(days), r_sl.reindex(days)
                    fin, fout = wd == 1.0, wd == 0.0
                    rows.append({
                        "leg": leg, "sleeve": sl, "rule": rn, "period": s["period"], "year": s["year"],
                        "sample": s["sample"], "partial": s["partial"],
                        "start_close": base.date(), "end_close": last.date(), "sessions": len(days),
                        "ret": float(seg.iloc[-1] / seg.iloc[0] - 1),
                        "dd_daily": seg_dd(seg),
                        "dd_friday": seg_dd(friday_seg(nav, base, last, wk)),
                        "in_equity": float(wd.mean()),
                        "switches": int((dw.reindex(days).abs() > 0).sum()),
                        "exits": int((dw.reindex(days) < 0).sum()),
                        "entries": int((dw.reindex(days) > 0).sum()),
                        "eq_ret_in": float((1 + re_[fin]).prod() - 1),
                        "eq_ret_out": float((1 + re_[fout]).prod() - 1),
                        "sleeve_ret_out": float((1 + rs_[fout]).prod() - 1),
                        "cost_paid": float(cost.reindex(days).sum()),
                        "nan_eq_returns_in_window": n_nan,
                        # the regime yardsticks over the SAME dates as this slice
                        **{f"{k}_ret_slice": float(lv[k][last] / lv[k][base] - 1) for k in ("SC100", "N100")},
                        **{f"{k}_dd_slice": seg_dd(lv[k].loc[base:last].dropna()) for k in ("SC100", "N100")},
                    })
                # consistency check against the reference results
                for lab, e in (("2007-21, cash", OOS_END), ("2007-26 full, cash", END),
                               ("2014-26 full, gold+cash", END), ("2014-21, gold+cash", OOS_END)):
                    want_sl = "cash" if lab.endswith("cash") and "gold" not in lab else "50/50"
                    if want_sl != sl:
                        continue
                    n = nav[nav.index <= e]
                    if len(n) < 250:
                        continue
                    checks.append({"ref_period": lab, "leg": leg, "rule": rn, "sleeve": sl,
                                   "start": n.index[0].date(), "end": n.index[-1].date(),
                                   "cagr_mine": cagr(n), "max_dd_mine": mdd(n)})
                # the pair's (and every rule's) out-spells, from the weekly decision path
                if sl == "cash" and rn in ("pair", "triple", "sc100", "own") and leg in CORE + SHORT:
                    d = dec[dec.index >= a - pd.Timedelta(days=7)]
                    ch = d.diff()
                    first_v = d.iloc[0]
                    exits = list(d.index[ch == -1])
                    if first_v == 0:
                        exits = [d.index[0]] + exits
                    entries = list(d.index[ch == 1])
                    lvl = (1 + r_eq).cumprod()
                    slv = (1 + r_sl).cumprod()
                    for ex in exits:
                        en = next((x for x in entries if x > ex), None)
                        tx = c[min(c.searchsorted(ex, side="right"), len(c) - 1)]
                        tn = c[min(c.searchsorted(en, side="right"), len(c) - 1)] if en is not None else c[-1]
                        prev_sig = ss.loc[ss.index <= ex].iloc[-1]
                        if rn == "pair":
                            trig = "+".join([k for k in ("N100", "SC100") if prev_sig[k] == 0])
                        elif rn == "triple":
                            trig = "+".join([k for k in ("N100", "MC100", "SC100") if prev_sig[k] == 0])
                        else:
                            trig = rn
                        ent_trig = ""
                        if en is not None:
                            p0 = ss.loc[ss.index < en].iloc[-1]
                            p1 = ss.loc[en]
                            keys = ("N100", "SC100") if rn == "pair" else ("N100", "MC100", "SC100") if rn == "triple" else ()
                            ent_trig = "+".join([k for k in keys if p0[k] == 0 and p1[k] == 1]) or rn
                        spell_rows.append({
                            "leg": leg, "rule": rn, "exit_decision": ex.date(), "exit_trade_close": tx.date(),
                            "entry_decision": en.date() if en is not None else None,
                            "entry_trade_close": tn.date(), "open_at_end": en is None,
                            "exit_trigger_sell": trig, "entry_trigger_turned_buy": ent_trig,
                            "weeks_out": int(round((tn - tx).days / 7)),
                            "leg_ret_while_out": float(lvl[tn] / lvl[tx] - 1),
                            "cash_ret_while_out": float(slv[tn] / slv[tx] - 1),
                            "SC100_ret_while_out": float(lv["SC100"][tn] / lv["SC100"][tx] - 1),
                            "N100_ret_while_out": float(lv["N100"][tn] / lv["N100"][tx] - 1),
                        })
                print(leg, sl, rn, "done", flush=True)

    yr = pd.DataFrame(rows)
    yr.to_csv(DEEP / "years_index_yearly.csv", index=False)
    sp = pd.DataFrame(spell_rows)
    sp.to_csv(DEEP / "years_out_spells.csv", index=False)

    # sanity check vs triple_index_results.csv
    ref = pd.read_csv(OUT / "triple_index_results.csv")
    rmap = {"pair": "N100 AND SC100", "triple": "N100 AND MC100 AND SC100", "sc100": "SC100 only",
            "own": "own signal", "bh": "buy & hold"}
    emap = {"blend": "blend N100/MC100/SC100"}
    ck = pd.DataFrame(checks)
    ck["ref_rule"] = ck["rule"].map(rmap)
    ck["ref_equity"] = ck["leg"].map(lambda x: emap.get(x, x))
    ref = ref.drop_duplicates(["period", "equity", "rule"])
    ck = ck.merge(ref[["period", "equity", "rule", "start", "cagr", "max_dd"]].rename(
        columns={"period": "ref_period", "equity": "ref_equity", "rule": "ref_rule", "start": "ref_start",
                 "cagr": "cagr_ref", "max_dd": "max_dd_ref"}), on=["ref_period", "ref_equity", "ref_rule"], how="left")
    ck["cagr_diff_pp"] = (ck["cagr_mine"] - ck["cagr_ref"]) * 100
    ck["dd_diff_pp"] = (ck["max_dd_mine"] - ck["max_dd_ref"]) * 100
    ck.to_csv(DEEP / "years_check_vs_reference.csv", index=False)
    print("\nmax |CAGR diff| pp vs reference:", ck["cagr_diff_pp"].abs().max(),
          " max |DD diff| pp:", ck["dd_diff_pp"].abs().max())

    # wide diffs per (leg, sleeve, period)
    key = ["leg", "sleeve", "period", "year", "sample", "partial", "start_close", "end_close",
           "SC100_ret_slice", "SC100_dd_slice", "N100_ret_slice", "N100_dd_slice"]
    wide = yr.pivot_table(index=key, columns="rule", values=["ret", "dd_daily", "dd_friday", "in_equity", "switches"],
                          aggfunc="first")
    wide.columns = [f"{r}_{m}" for m, r in wide.columns]
    wide = wide.reset_index()
    wide["pair_minus_bh"] = wide["pair_ret"] - wide["bh_ret"]
    wide["pair_minus_sc100"] = wide["pair_ret"] - wide["sc100_ret"]
    wide["triple_minus_pair"] = wide["triple_ret"] - wide["pair_ret"]
    wide["pair_minus_own"] = wide["pair_ret"] - wide.get("own_ret")
    wide["pair_dd_minus_bh_dd_daily"] = wide["pair_dd_daily"] - wide["bh_dd_daily"]
    wide["pair_dd_minus_bh_dd_friday"] = wide["pair_dd_friday"] - wide["bh_dd_friday"]
    wide["pair_dd_minus_sc100_dd_daily"] = wide["pair_dd_daily"] - wide["sc100_dd_daily"]

    # hindsight regime labels per slice, from SC100 and N100 buy-and-hold (cash-sleeve NAV = the index)
    reg = yr[(yr["sleeve"] == "cash") & (yr["rule"] == "bh") & (yr["leg"].isin(["SC100", "N100"]))]
    lab = []
    for _, r in reg.iterrows():
        lbl = "bull" if r["ret"] > 0.15 else "bear" if r["ret"] < -0.10 else "flat"
        v = bool(r["dd_daily"] < -0.20 and r["ret"] > 0)
        v_fri = bool(r["dd_friday"] < -0.20 and r["ret"] > 0)
        lab.append({"period": r["period"], "sample": r["sample"], "partial": r["partial"], "src": r["leg"],
                    "ret": r["ret"], "dd_daily": r["dd_daily"], "dd_friday": r["dd_friday"],
                    "label": lbl, "V": v, "V_friday": v_fri})
    lab = pd.DataFrame(lab)
    regw = lab.pivot(index=["period", "sample", "partial"], columns="src",
                     values=["ret", "dd_daily", "dd_friday", "label", "V", "V_friday"])
    regw.columns = [f"{s}_{m}" for m, s in regw.columns]
    regw = regw.reset_index()
    regw["sort"] = regw["period"].map(lambda p: float(p[:4]) + (0.1 if p.endswith("OOS") else 0.2 if p.endswith("IS") else 0))
    regw = regw.sort_values("sort").drop(columns="sort")
    regw.to_csv(DEEP / "years_regimes.csv", index=False)

    # hindsight labels of each slice from SC100 / N100 over the slice's own dates
    # (identical to years_regimes.csv for the cash window; differs for the 2014-07-07 gold-sleeve stub
    # and the first slice of the short legs)
    for k in ("SC100", "N100"):
        rr, dd_ = wide[f"{k}_ret_slice"], wide[f"{k}_dd_slice"]
        wide[f"{k}_label"] = np.where(rr > 0.15, "bull", np.where(rr < -0.10, "bear", "flat"))
        wide[f"{k}_V"] = (dd_ < -0.20) & (rr > 0)
    wide["sort"] = wide["period"].map(lambda p: float(p[:4]) + (0.1 if p.endswith("OOS") else 0.2 if p.endswith("IS") else 0))
    wide = wide.sort_values(["leg", "sleeve", "sort"]).drop(columns="sort")
    wide.to_csv(DEEP / "years_index_diffs.csv", index=False)
    print("wrote", len(yr), "slice rows;", len(wide), "wide rows;", len(sp), "spells")


if __name__ == "__main__":
    main()
