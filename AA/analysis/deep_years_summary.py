# -*- coding: utf-8 -*-
"""
Deep dive, analyst "years": summaries over the calendar-year slices written by
deep_years_indices.py.

  years_summary_wins.csv        per leg x sleeve x sample: how often the pair
                                beats bh / sc100 / own, and triple vs pair
                                (ties = |diff| < 0.1 pp), with sign-test p.
  years_summary_regime.csv      average pair - bh (and pair - sc100) by the
                                hindsight regime label of the slice
                                (from SC100 bh and from N100 bh).
  years_capture.csv             up/down capture: pair return / bh return summed
                                over bull and over bear slices.
  years_leg_breadth.csv         per slice: on how many of the 5 core legs the
                                pair beat bh (cash sleeve).
  years_best_worst.csv          SC100 and blend, cash sleeve: the 3 best and
                                3 worst slices for pair - bh, OOS and IS ranked
                                separately, with the in/out decomposition.
  years_best_worst_path.csv     the pair's out-spells that overlap those slices:
                                decision and trade dates, trigger, and what the
                                leg did while out (inside the slice and over the
                                whole spell).
"""

from __future__ import annotations

from math import comb

import numpy as np
import pandas as pd

from why_n100sc100 import OUT, calendar, gold_cash
from triple_and_test import index_levels

DEEP = OUT / "deep"
TIE = 0.001
END = pd.Timestamp("2026-08-21")


def sign_p(w: int, l: int) -> float:
    """Two-sided binomial sign test, ties dropped."""
    n = w + l
    if n == 0:
        return np.nan
    k = min(w, l)
    p = sum(comb(n, i) for i in range(0, k + 1)) / 2 ** n * 2
    return float(min(1.0, p))


def wlt(x: pd.Series):
    x = x.dropna()
    return int((x > TIE).sum()), int((x.abs() <= TIE).sum()), int((x < -TIE).sum())


def main() -> None:
    w = pd.read_csv(DEEP / "years_index_diffs.csv")
    yr = pd.read_csv(DEEP / "years_index_yearly.csv")
    sp = pd.read_csv(DEEP / "years_out_spells.csv", parse_dates=["exit_decision", "exit_trade_close",
                                                                   "entry_decision", "entry_trade_close"])
    w = w[w["sample"].isin(["OOS", "IS"])].copy()        # the split 2021 slices; the whole-2021 "mixed" row is dropped
    rg = pd.read_csv(DEEP / "years_regimes.csv")[["period", "SC100_ret", "N100_ret"]]
    w = w.merge(rg, on="period", how="left")

    # ── wins ────────────────────────────────────────────────────────────────
    rows = []
    for (leg, sl, smp), g in w.groupby(["leg", "sleeve", "sample"]):
        for scope, gg in (("all slices", g), ("full years only", g[~g["partial"]])):
            if len(gg) == 0:
                continue
            r = {"leg": leg, "sleeve": sl, "sample": smp, "scope": scope, "n": len(gg),
                 "first": gg["period"].iloc[0], "last": gg["period"].iloc[-1]}
            for lab, col in (("vs_bh", "pair_minus_bh"), ("vs_sc100", "pair_minus_sc100"),
                             ("vs_own", "pair_minus_own"), ("triple_vs_pair", "triple_minus_pair")):
                if gg[col].notna().sum() == 0:
                    continue
                a, t, b = wlt(gg[col])
                r[f"{lab}_wins"], r[f"{lab}_ties"], r[f"{lab}_losses"] = a, t, b
                r[f"{lab}_sign_p"] = sign_p(a, b)
                r[f"{lab}_mean_pp"] = gg[col].mean() * 100
                r[f"{lab}_median_pp"] = gg[col].median() * 100
            lg = np.log1p(gg["pair_ret"]) - np.log1p(gg["bh_ret"])
            r["vs_bh_mean_log_gap_pp"] = lg.mean() * 100
            r["vs_bh_wealth_ratio"] = float(np.exp(lg.sum()))
            r["pair_compound_pct"] = float(np.prod(1 + gg["pair_ret"]) - 1) * 100
            r["bh_compound_pct"] = float(np.prod(1 + gg["bh_ret"]) - 1) * 100
            r["sc100_compound_pct"] = float(np.prod(1 + gg["sc100_ret"]) - 1) * 100
            r["vs_sc100_wealth_ratio"] = float(np.exp((np.log1p(gg["pair_ret"]) - np.log1p(gg["sc100_ret"])).sum()))
            dd = gg["pair_dd_minus_bh_dd_daily"]
            r["dd_shallower_than_bh_daily"] = int((dd > TIE).sum())
            r["dd_shallower_than_bh_friday"] = int((gg["pair_dd_minus_bh_dd_friday"] > TIE).sum())
            r["mean_dd_pair_daily_pct"] = gg["pair_dd_daily"].mean() * 100
            r["mean_dd_bh_daily_pct"] = gg["bh_dd_daily"].mean() * 100
            r["worst_dd_pair_daily_pct"] = gg["pair_dd_daily"].min() * 100
            r["worst_dd_bh_daily_pct"] = gg["bh_dd_daily"].min() * 100
            r["worst_dd_pair_friday_pct"] = gg["pair_dd_friday"].min() * 100
            r["worst_dd_bh_friday_pct"] = gg["bh_dd_friday"].min() * 100
            r["years_pair_negative"] = int((gg["pair_ret"] < 0).sum())
            r["years_bh_negative"] = int((gg["bh_ret"] < 0).sum())
            r["worst_year_pair_pct"] = gg["pair_ret"].min() * 100
            r["worst_year_bh_pct"] = gg["bh_ret"].min() * 100
            r["best_year_pair_pct"] = gg["pair_ret"].max() * 100
            r["best_year_bh_pct"] = gg["bh_ret"].max() * 100
            r["mean_in_equity_pair"] = gg["pair_in_equity"].mean()
            r["corr_bh_ret_vs_gap"] = gg["bh_ret"].corr(gg["pair_minus_bh"]) if len(gg) > 2 else np.nan
            rows.append(r)
    wins = pd.DataFrame(rows)
    wins.to_csv(DEEP / "years_summary_wins.csv", index=False)

    # ── by regime ───────────────────────────────────────────────────────────
    rows = []
    for src in ("SC100", "N100"):
        grp = {
            "bull": w[f"{src}_label"] == "bull",
            "bear": w[f"{src}_label"] == "bear",
            "flat": w[f"{src}_label"] == "flat",
            "V (fell >20% intra-year, ended up)": w[f"{src}_V"] == True,
            "bull, not V": (w[f"{src}_label"] == "bull") & (w[f"{src}_V"] != True),
            "positive, no >20% fall (bull or flat, not V)": (w[f"{src}_V"] != True) & (w[f"{src}_ret"] > 0),
        }
        for gname, m in grp.items():
            if m is None:
                continue
            for (leg, sl, smp), g in w[m].groupby(["leg", "sleeve", "sample"]):
                for scope, gg in (("all slices", g), ("full years only", g[~g["partial"]])):
                    if len(gg) == 0:
                        continue
                    a, t, b = wlt(gg["pair_minus_bh"])
                    rows.append({"regime_source": src, "regime": gname, "leg": leg, "sleeve": sl, "sample": smp,
                                 "scope": scope, "n": len(gg), "periods": " ".join(gg["period"].astype(str)),
                                 "mean_pair_minus_bh_pp": gg["pair_minus_bh"].mean() * 100,
                                 "median_pair_minus_bh_pp": gg["pair_minus_bh"].median() * 100,
                                 "pair_beats_bh": a, "ties": t, "pair_loses": b,
                                 "mean_log_gap_vs_bh_pp": (np.log1p(gg["pair_ret"]) - np.log1p(gg["bh_ret"])).mean() * 100,
                                 "sum_log_gap_vs_bh": (np.log1p(gg["pair_ret"]) - np.log1p(gg["bh_ret"])).sum(),
                                 "mean_pair_minus_sc100_pp": gg["pair_minus_sc100"].mean() * 100,
                                 "mean_triple_minus_pair_pp": gg["triple_minus_pair"].mean() * 100,
                                 "mean_bh_ret_pct": gg["bh_ret"].mean() * 100,
                                 "mean_pair_ret_pct": gg["pair_ret"].mean() * 100,
                                 "mean_pair_in_equity": gg["pair_in_equity"].mean(),
                                 "mean_dd_improvement_daily_pp": gg["pair_dd_minus_bh_dd_daily"].mean() * 100})
    reg = pd.DataFrame(rows)
    reg.to_csv(DEEP / "years_summary_regime.csv", index=False)

    # ── capture ratios over bull and bear slices (SC100 label) ─────────────
    rows = []
    for (leg, sl, smp), g in w.groupby(["leg", "sleeve", "sample"]):
        for gname in ("bull", "bear", "flat"):
            gg = g[g["SC100_label"] == gname]
            if len(gg) == 0:
                continue
            rows.append({"leg": leg, "sleeve": sl, "sample": smp, "SC100_regime": gname, "n": len(gg),
                         "sum_bh_ret_pct": gg["bh_ret"].sum() * 100, "sum_pair_ret_pct": gg["pair_ret"].sum() * 100,
                         "capture_pair_over_bh": gg["pair_ret"].sum() / gg["bh_ret"].sum() if gg["bh_ret"].sum() else np.nan,
                         "geo_bh_pct": (np.prod(1 + gg["bh_ret"]) - 1) * 100,
                         "geo_pair_pct": (np.prod(1 + gg["pair_ret"]) - 1) * 100})
    pd.DataFrame(rows).to_csv(DEEP / "years_capture.csv", index=False)

    # ── breadth across the 5 core legs ─────────────────────────────────────
    core = w[w["leg"].isin(["N50", "N100", "MC100", "SC100", "blend"])]
    br = core.groupby(["sleeve", "period", "sample", "partial"]).agg(
        legs=("leg", "size"),
        pair_beats_bh=("pair_minus_bh", lambda x: int((x > TIE).sum())),
        pair_beats_sc100=("pair_minus_sc100", lambda x: int((x > TIE).sum())),
        pair_ties_sc100=("pair_minus_sc100", lambda x: int((x.abs() <= TIE).sum())),
        mean_pair_minus_bh_pp=("pair_minus_bh", lambda x: x.mean() * 100),
        pair_in_equity=("pair_in_equity", "first")).reset_index()
    br["sort"] = br["period"].map(lambda p: float(p[:4]) + (0.1 if p.endswith("OOS") else 0.2 if p.endswith("IS") else 0))
    br = br.sort_values(["sleeve", "sort"]).drop(columns="sort")
    br.to_csv(DEEP / "years_leg_breadth.csv", index=False)

    # ── best / worst slices with the signal path ───────────────────────────
    cal = calendar()
    cal = cal[cal <= END]
    lv = index_levels(cal)
    gc = gold_cash(cal)
    rb = (lv["N100"].pct_change() + lv["MC100"].pct_change() + lv["SC100"].pct_change()) / 3
    lvl = {"SC100": lv["SC100"], "blend": (1 + rb.fillna(0)).cumprod(), "N100": lv["N100"]}
    cash = gc["cash"]
    ydet = yr[(yr["sleeve"] == "cash") & (yr["rule"] == "pair")].set_index(["leg", "period"])
    rows, path = [], []
    for leg in ("SC100", "blend"):
        g = w[(w["leg"] == leg) & (w["sleeve"] == "cash")]
        for smp in ("OOS", "IS"):
            gs = g[g["sample"] == smp].sort_values("pair_minus_bh")
            picks = [("worst", i + 1, r) for i, (_, r) in enumerate(gs.head(3).iterrows())] + \
                    [("best", i + 1, r) for i, (_, r) in enumerate(gs.iloc[::-1].head(3).iterrows())]
            for kind, rank, r in picks:
                d = ydet.loc[(leg, r["period"])]
                base, last = pd.Timestamp(r["start_close"]), pd.Timestamp(r["end_close"])
                ss = sp[(sp["leg"] == leg) & (sp["rule"] == "pair") & (sp["exit_trade_close"] < last)
                        & (sp["entry_trade_close"] > base)]
                bits = []
                for _, s in ss.iterrows():
                    x0 = max(s["exit_trade_close"], base)
                    x1 = min(s["entry_trade_close"], last)
                    in_y = float(lvl[leg][x1] / lvl[leg][x0] - 1)
                    c_y = float(cash[x1] / cash[x0] - 1)
                    path.append({"leg": leg, "sample": smp, "kind": kind, "rank": rank, "period": r["period"],
                                 "exit_decision": s["exit_decision"].date(), "exit_trade_close": s["exit_trade_close"].date(),
                                 "exit_trigger_sell": s["exit_trigger_sell"],
                                 "entry_decision": s["entry_decision"].date() if pd.notna(s["entry_decision"]) else None,
                                 "entry_trade_close": s["entry_trade_close"].date(),
                                 "entry_trigger_turned_buy": s["entry_trigger_turned_buy"],
                                 "weeks_out_full_spell": s["weeks_out"],
                                 "leg_ret_while_out_in_slice": in_y, "cash_ret_while_out_in_slice": c_y,
                                 "leg_ret_while_out_full_spell": s["leg_ret_while_out"],
                                 "N100_ret_while_out_full_spell": s["N100_ret_while_out"],
                                 "SC100_ret_while_out_full_spell": s["SC100_ret_while_out"]})
                    carried = s["exit_trade_close"] < base
                    ended = pd.notna(s["entry_decision"]) and s["entry_trade_close"] <= last
                    bits.append(
                        (f"out since {s['exit_trade_close'].date()} (carried in; exit on {s['exit_trigger_sell']} SELL)"
                         if carried else
                         f"exit {s['exit_trade_close'].date()} (decision {s['exit_decision'].date()}, {s['exit_trigger_sell']} SELL)")
                        + (f", re-entry {s['entry_trade_close'].date()} ({s['entry_trigger_turned_buy']} turned BUY)"
                           if ended else ", still out at slice end")
                        + f": {leg} {in_y * 100:+.1f}% in-slice while out"
                        + (f" ({s['leg_ret_while_out'] * 100:+.1f}% over the whole {s['weeks_out']}-week spell)"
                           if carried or not ended else ""))
                rows.append({"leg": leg, "sample": smp, "kind": kind, "rank": rank, "period": r["period"],
                             "partial": r["partial"], "SC100_label": r["SC100_label"], "SC100_V": r["SC100_V"],
                             "bh_ret": r["bh_ret"], "pair_ret": r["pair_ret"], "sc100_ret": r["sc100_ret"],
                             "pair_minus_bh": r["pair_minus_bh"], "pair_minus_sc100": r["pair_minus_sc100"],
                             "bh_dd_daily": r["bh_dd_daily"], "pair_dd_daily": r["pair_dd_daily"],
                             "pair_in_equity": d["in_equity"], "pair_switches": d["switches"],
                             "leg_ret_while_in": d["eq_ret_in"], "leg_ret_while_out": d["eq_ret_out"],
                             "cash_ret_while_out": d["sleeve_ret_out"], "cost_paid": d["cost_paid"],
                             "path": "; ".join(bits) if bits else "in equity the whole slice"})
    pd.DataFrame(rows).to_csv(DEEP / "years_best_worst.csv", index=False)
    pd.DataFrame(path).to_csv(DEEP / "years_best_worst_path.csv", index=False)

    pd.set_option("display.width", 250)
    pd.set_option("display.max_colwidth", 400)
    x = wins[(wins["scope"] == "all slices")][["leg", "sleeve", "sample", "n", "vs_bh_wins", "vs_bh_ties", "vs_bh_losses",
                                              "vs_bh_sign_p", "vs_bh_mean_pp", "vs_sc100_wins", "vs_sc100_ties",
                                              "vs_sc100_losses", "vs_sc100_mean_pp", "triple_vs_pair_wins",
                                              "triple_vs_pair_ties", "triple_vs_pair_losses", "dd_shallower_than_bh_daily"]]
    print(x.round(2).to_string(index=False))
    print(pd.DataFrame(rows)[["leg", "sample", "kind", "rank", "period", "bh_ret", "pair_ret", "pair_minus_bh",
                              "pair_in_equity", "leg_ret_while_out", "path"]].round(3).to_string(index=False))


if __name__ == "__main__":
    main()
