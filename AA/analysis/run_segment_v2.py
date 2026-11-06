# -*- coding: utf-8 -*-
"""
Run the pre-registered v2 study: primary grid, gates G1-G3, sensitivities,
comparison series, rebalance history and the bucket distribution. The nulls
(G4, G5) are in `segment_v2_nulls.py`.

Writes to `evidence/segment_v2/`:
    nav_curves.csv            daily NAV, every simulated and published series, rebased
    scorecard.csv             book x strategy x cost: absolute stats
    stats_panel.csv           the same plus relative stats vs each reference
    headline.csv              D and the published-NAV comparisons, per book x cost
    gates_g1_g3.json          G1, G2, G3 statistics and pass/fail
    sensitivities.csv         each sensitivity's CAGR and D at 20.8 bps
    yearly_returns.csv        calendar-year returns, every series
    rebalance_summary.csv     one row per (book, event)
    rebalance_history.csv     one row per (book, event, holding)
    exposure_daily.csv        target equity weight in force, per book x strategy
    bucket_tags.csv           tag of every holding at every review
    bucket_distribution.csv   weight share by bucket and by tag source, per review
    tag_accuracy_holdings.csv rank-band tags vs real membership on the books' holdings
    audit.json
"""

from __future__ import annotations

import json
import time

import numpy as np
import pandas as pd

import segment_v2 as V
import segment_v2_data as D
import stats_v2 as S
from common import AA_INDEX_CSV, EVIDENCE_DIR, PAIRS, PARENT_INDEX_CSV, load_index_levels
from index_builder import Panel
from segment_backtest import sleeve_frame

OUT = V.EVIDENCE_SUBDIR
BENCH_SHEETS = {"Nifty 50": "NSEI", "Nifty 100": "Nifty100", "Nifty Midcap 150": "NiftyMidcap150",
                "Nifty Smallcap 250": "NiftySmallcap250", "Nifty Microcap 250": "NiftyMicrocap250"}
STRATS = ["sleeve", "production_v2", "n100_and_sc100", "sc100_only", "sc250_only", "parent"]
LABEL = {"sleeve": "New rule (segment sleeve)", "production_v2": "Current rule, re-simulated",
         "n100_and_sc100": "N100 AND SC100 (whole book)", "parent": "Harness parent",
         "sc100_only": "Smallcap 100 only (whole book)", "sc250_only": "Smallcap 250 only (whole book)",
         "published_parent": "Published parent NAV", "published_aa": "Published AA NAV",
         "style_blend": "Style blend (4-factor)"}


# ── Inputs ─────────────────────────────────────────────────────────────────
def make_sim(px: pd.DataFrame, cal: pd.DatetimeIndex, sleeve: pd.DataFrame) -> V.Simulator:
    close = px.pivot(index="date", columns="ticker", values="close").reindex(cal)
    return V.Simulator(Panel(px, cal), sleeve, close=close)


def load_inputs(source: str = D.PRICE_SOURCE):
    cal = V.session_calendar()
    signs = V.load_signs()
    eff, fb = V.effective_signs(signs)
    reviews = V.window_reviews(signs)
    start = V.common_start(cal, reviews)
    hold = D.resolve_holdings()
    px = D.load_prices(source)
    panel = Panel(px, cal)
    sleeve = sleeve_frame(cal)
    close = px.pivot(index="date", columns="ticker", values="close").reindex(cal)
    sim = V.Simulator(panel, sleeve, close=close)
    ranks_m, ranks_s = D.monthly_ranks_v2(), D.semiannual_ranks_v2()
    mem, ov = D.membership_v2(), D.load_overrides()
    taggers = {"hybrid": V.HybridTagger(ranks_m, mem, ov),
               "ranks_only": V.HybridTagger(ranks_m, None, ov),
               "semiannual": V.HybridTagger(ranks_s, mem, ov)}
    return dict(cal=cal, signs=signs, eff=eff, fb=fb, reviews=reviews, start=start,
                hold=hold, px=px, panel=panel, sleeve=sleeve, sim=sim, taggers=taggers,
                ranks_m=ranks_m, mem=mem, close=close)


def unfillable_holdings(inp) -> pd.DataFrame:
    """Every (book, review, holding) with no usable fill price at its entry session."""
    sim, cal, reviews = inp["sim"], inp["cal"], inp["reviews"]
    rows = []
    for aa, parent in PAIRS.items():
        ctx = V.parent_ctx(parent, inp["hold"][inp["hold"]["parent"] == parent], reviews, cal)
        for r, ei, eff in zip(ctx.reviews, ctx.entry_i, ctx.basket_eff):
            for k, t, nm, isin, w in ctx.baskets[eff]:
                if not np.isfinite(sim._p(k, ei, "fill")):
                    rows.append({"aa": aa, "parent": parent, "review": r.date(), "ticker": t,
                                 "isin": k, "name": nm, "parent_weight": w})
    return pd.DataFrame(rows, columns=["aa", "parent", "review", "ticker", "isin", "name",
                                       "parent_weight"])


def published_and_benchmarks(cal, start) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Published NAVs and benchmarks, on the calendar, rebased at `start`."""
    par, aa = load_index_levels(PARENT_INDEX_CSV), load_index_levels(AA_INDEX_CSV)
    pub = {}
    for a, p in PAIRS.items():
        pub[f"{a}|published_parent"] = par[p]
        pub[f"{a}|published_aa"] = aa[a]
    pub = pd.DataFrame(pub).reindex(cal.union(par.index)).ffill().reindex(cal).loc[start:]

    xl = D.FROZEN_DIR / "Data" / "indices_ohlcv.xlsx"
    bench = {}
    for lab, sheet in BENCH_SHEETS.items():
        d = pd.read_excel(xl, sheet_name=sheet)
        d["date"] = pd.to_datetime(d["date"])
        s = d.set_index("date")["close"].astype(float).sort_index()
        bench[lab] = s[~s.index.duplicated()]
    bench = pd.DataFrame(bench).reindex(cal.union(pd.DatetimeIndex(
        sorted(set().union(*[b.index for b in bench.values()]))))).ffill(limit=5).reindex(cal).loc[start:]

    blend = pd.read_csv(EVIDENCE_DIR / "main" / "mcap_blend_returns.csv", index_col=0,
                        parse_dates=True)
    for a, p in PAIRS.items():
        r = blend[p].reindex(cal).loc[start:]
        first = r.first_valid_index()
        lvl = (1 + r.loc[first:].fillna(0)).cumprod()
        # Level is 1.0 the session before the first blend return.
        prev = cal[cal < first][-1]
        lvl = pd.concat([pd.Series([1.0], index=[prev]), lvl])
        pub[f"{a}|style_blend"] = lvl.reindex(pub.index)
    return pub, bench


def rebase(s: pd.Series) -> pd.Series:
    fv = s.first_valid_index()
    return s / s.loc[fv]


# ── Rebalance history ──────────────────────────────────────────────────────
def rebalance_tables(aa, steps, log, pos, cal, names):
    """Per-event summary and per-holding detail for the new rule."""
    trades = {pd.Timestamp(r): row for r, row in log.set_index("review").iterrows()} \
        if len(log) else {}
    pos = pos.copy()
    pos["review"] = pd.to_datetime(pos["review"])
    by_rev = {r: g for r, g in pos.groupby("review")}
    summ, det = [], []
    last_after: dict = {}
    for st in steps:
        if not st.event:
            continue
        r = st.review
        traded = r in trades
        g = by_rev.get(r)
        before = dict(zip(g["key"], g["w_before"])) if g is not None else dict(last_after)
        after = dict(zip(g["key"], g["w_after"])) if g is not None else dict(last_after)
        price = dict(zip(g["key"], g["fill_price"])) if g is not None else {}
        eq_b = sum(v for k, v in before.items() if k not in (V.GOLD, V.CASH))
        eq_a = sum(v for k, v in after.items() if k not in (V.GOLD, V.CASH))
        held = [x for x in st.rows if x["hold"]]
        summ.append({"aa": aa, "review": r.date(), "entry": cal[st.entry_i].date(),
                     "trigger": st.trigger, "traded": traded,
                     "n_names": len(st.rows), "n_held": len(held),
                     "n_dropped": len(st.rows) - len(held),
                     "equity_before": eq_b, "equity_after": eq_a,
                     "gold_after": after.get(V.GOLD, 0.0), "cash_after": after.get(V.CASH, 0.0),
                     "turnover_frac": float(trades[r]["turnover_frac"]) if traded else 0.0,
                     "cost_frac": float(trades[r]["cost"] / (trades[r]["nav"] + trades[r]["cost"]))
                     if traded else 0.0,
                     "nav": float(trades[r]["nav"]) if traded else np.nan})
        for x in st.rows:
            k = x["key"]
            wb, wa = before.get(k, 0.0), after.get(k, 0.0)
            if x["hold"] and wa <= 1e-9 and wb <= 1e-9:
                act = "no price"          # rule says hold; no fill price, weight spread to the rest
            elif x["hold"]:
                act = "buy" if wb <= 1e-9 else ("rebalance" if traded and abs(wa - wb) > 5e-4 else "hold")
            else:
                act = "sell" if wb > 1e-9 else "stay out"
            det.append({"aa": aa, "review": r.date(), "entry": cal[st.entry_i].date(),
                        "trigger": st.trigger, **{kk: x[kk] for kk in (
                            "ticker", "name", "bucket", "tag_source", "rank",
                            "signal_index", "sign", "parent_weight")},
                        "isin": k, "tag_snapshot": x["tag_snapshot"].date()
                        if isinstance(x["tag_snapshot"], pd.Timestamp) else None,
                        "action": act, "w_before": wb, "w_after": wa,
                        "fill_price": price.get(k, np.nan)})
        for k in (V.GOLD, V.CASH):
            if before.get(k, 0) > 0 or after.get(k, 0) > 0:
                det.append({"aa": aa, "review": r.date(), "entry": cal[st.entry_i].date(),
                            "trigger": st.trigger, "ticker": k,
                            "name": "Gold (GOLDBEES)" if k == V.GOLD else "Cash (LBES TR)",
                            "bucket": "Sleeve", "tag_source": "", "rank": None,
                            "signal_index": "", "sign": "", "parent_weight": 0.0, "isin": k,
                            "tag_snapshot": None,
                            "action": "buy" if after.get(k, 0) > before.get(k, 0) + 5e-4 else (
                                "sell" if after.get(k, 0) < before.get(k, 0) - 5e-4 else "hold"),
                            "w_before": before.get(k, 0.0), "w_after": after.get(k, 0.0),
                            "fill_price": price.get(k, np.nan)})
        if g is not None:
            last_after = after
    return pd.DataFrame(summ), pd.DataFrame(det)


# ── Tag accuracy and error model ───────────────────────────────────────────
def tag_accuracy(inp) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    On each membership snapshot, compare the rank band monthly ranks would
    have given with real membership: (a) on the books' own holdings,
    (b) on the whole ranked universe (the G5 error model's basis).
    """
    ranks_only, mem, ranks = inp["taggers"]["ranks_only"], inp["mem"], inp["ranks_m"]
    hold = inp["hold"]
    rows_h, rows_u = [], []
    for snap, g in mem.groupby("snapshot_date"):
        truth_i = dict(zip(g["isin"], g["category"]))
        for parent in PAIRS.values():
            h = hold[hold["parent"] == parent]
            effs = h[h["eff_date"] <= snap]["eff_date"]
            if effs.empty:
                continue
            b = h[h["eff_date"] == effs.max()]
            for isin, tkr, w in zip(b["isin"], b["ticker"], b["weight"] / b["weight"].sum()):
                t = ranks_only.tag(isin, tkr, snap)
                rows_h.append({"snapshot": snap.date(), "parent": parent, "isin": isin,
                               "ticker": tkr, "weight": w, "rank": t.rank,
                               "rank_band": t.bucket,
                               "membership": truth_i.get(isin, "Unknown")})
        rs = [d for d in sorted(ranks["snapshot_date"].unique()) if d <= snap][-1]
        gr = ranks[ranks["snapshot_date"] == rs]
        pred = np.where(gr["rank"] <= 900, gr["category"], "Unknown")
        truth = [truth_i.get(i, "Unknown") for i in gr["isin"].fillna("")]
        rows_u.append(pd.DataFrame({"snapshot": snap.date(), "predicted": pred, "truth": truth}))
    th = pd.DataFrame(rows_h)
    th["agree"] = th["rank_band"] == th["membership"]
    uni = pd.concat(rows_u, ignore_index=True)
    return th, uni


def error_model(uni: pd.DataFrame) -> pd.DataFrame:
    b = ["Largecap", "Midcap", "Smallcap", "Microcap", "Unknown"]
    tab = pd.crosstab(uni["predicted"], uni["truth"]).reindex(index=b, columns=b).fillna(0.0)
    p = tab.div(tab.sum(axis=1).replace(0, np.nan), axis=0)
    for x in b:
        if p.loc[x].isna().all():
            p.loc[x] = [1.0 if c == x else 0.0 for c in b]
    return p


# ── Main ───────────────────────────────────────────────────────────────────
def main() -> None:
    t0 = time.time()
    OUT.mkdir(parents=True, exist_ok=True)
    inp = load_inputs()
    cal, eff, reviews, start, sim = (inp[k] for k in ("cal", "eff", "reviews", "start", "sim"))
    pub, bench = published_and_benchmarks(cal, start)
    sim_kite = make_sim(D.load_prices("kite"), cal, inp["sleeve"])
    cash_lvl = inp["sleeve"]["CASH"].loc[start:]
    sl_ret = inp["sleeve"].pct_change().fillna(0.0)
    sleeve_5050 = 0.5 * sl_ret[V.GOLD] + 0.5 * sl_ret[V.CASH]

    navs = {}
    score, logs_all, exp_all, tags_all, dist_all = [], [], [], [], []
    summ_all, det_all, sens = [], [], []
    g2, g3 = {}, {}
    audit = {"prereg_sha256": V.prereg_sha256(), "price_source": D.PRICE_SOURCE, "window": [str(start.date()), str(cal[-1].date())],
             "reviews": int(len(reviews)), "sessions_in_window": int(len(cal[cal >= start])),
             "microcap_fallback_reviews": int(inp["fb"].reindex(reviews).sum()),
             "per_book": {}}

    for aa, parent in PAIRS.items():
        hist = inp["hold"][inp["hold"]["parent"] == parent]
        ctx = V.parent_ctx(parent, hist, reviews, cal)
        tags = {k: V.tag_table(ctx, t) for k, t in inp["taggers"].items()}
        th = tags["hybrid"]
        steps = {
            "sleeve": V.build_sleeve(ctx, eff, th, "event", "micro_own", detail=True),
            "production_v2": V.build_production(ctx, eff, th),
            "n100_and_sc100": V.build_whole_book_and(ctx, eff),
            # Whole book to the sleeve whenever the one smallcap index is SELL,
            # whatever the book's market-cap mix. SC100 alone is what 0042 and
            # 0043 actually ran live, and it was Study 1's best single index.
            # Reference comparators only; they are not in any gate.
            "sc100_only": V.build_whole_book_and(ctx, eff, keys=(V.SC100,)),
            "sc250_only": V.build_whole_book_and(ctx, eff, keys=(V.SC250,)),
            "parent": V.build_parent(ctx, eff),
        }
        book_audit = {"ctx": ctx.audit, "events": int(sum(s.event for s in steps["sleeve"])),
                      "event_triggers": {}, "sim": {}}
        for s in steps["sleeve"]:
            if s.event:
                for part in s.trigger.split("; "):
                    key = part.split(" ")[0] if "→" in part else part
                    book_audit["event_triggers"][key] = book_audit["event_triggers"].get(key, 0) + 1

        for name, st in steps.items():
            for bps in V.COST_BPS:
                a = {}
                if name == "sleeve" and bps == V.PRIMARY_BPS:
                    nav, log, pos = sim.run(st, bps, audit=a, positions=True)
                    sm, dt = rebalance_tables(aa, st, log, pos, cal, None)
                    summ_all.append(sm); det_all.append(dt)
                else:
                    nav, log = sim.run(st, bps, audit=a)
                nav = rebase(nav.loc[start:])
                navs[f"{aa}|{name}|{bps:g}"] = nav
                row = {"aa": aa, "parent": parent, "strategy": name, "cost_bps": bps,
                       **S.absolute(nav, cash_lvl),
                       "trades": int(len(log)),
                       "turnover_pa": float(log["turnover_frac"].sum()
                                            / ((nav.index[-1] - nav.index[0]).days / 365.25))
                       if len(log) else 0.0,
                       "avg_equity_weight": float(V.exposure(st, cal).loc[start:].mean()),
                       "events": int(sum(s.event for s in st)) if name == "sleeve" else None}
                score.append(row)
                if bps == V.PRIMARY_BPS:
                    book_audit["sim"][name] = a
                    logs_all.append(log.assign(aa=aa, strategy=name))
            exp_all.append(V.exposure(st, cal).loc[start:].rename(f"{aa}|{name}"))

        # G2: static mix at the arm's own average equity weight, zero cost.
        e_bar = float(V.exposure(steps["sleeve"], cal).loc[start:].mean())
        rp = navs[f"{aa}|parent|0"].pct_change().fillna(0.0)
        static = rebase((1 + e_bar * rp + (1 - e_bar) * sleeve_5050.loc[start:]).cumprod())
        navs[f"{aa}|static_mix|0"] = static
        g2[aa] = {"avg_equity_weight": e_bar, "cagr_sleeve_20p8": S.cagr(navs[f"{aa}|sleeve|20.8"]),
                  "cagr_static": S.cagr(static)}
        g2[aa]["timing_part"] = g2[aa]["cagr_sleeve_20p8"] - g2[aa]["cagr_static"]

        # G3: all-cash sleeve for both the arm and the comparator.
        n_s, _ = sim.run(steps["sleeve"], V.PRIMARY_BPS, gold_share=0.0)
        n_p, _ = sim.run(steps["production_v2"], V.PRIMARY_BPS, gold_share=0.0)
        n_s, n_p = rebase(n_s.loc[start:]), rebase(n_p.loc[start:])
        navs[f"{aa}|sleeve_allcash|20.8"], navs[f"{aa}|production_v2_allcash|20.8"] = n_s, n_p
        # N100 AND SC100 with an all-cash sleeve: how much of its edge is gold.
        navs[f"{aa}|n100_and_sc100_allcash|20.8"] = rebase(
            sim.run(steps["n100_and_sc100"], V.PRIMARY_BPS, gold_share=0.0)[0].loc[start:])
        g3[aa] = {"cagr_sleeve": S.cagr(n_s), "cagr_production_v2": S.cagr(n_p),
                  "D": S.cagr(n_s) - S.cagr(n_p)}

        # Price source: the same primary rule and comparator on Kite prices.
        nk = rebase(sim_kite.run(steps["sleeve"], V.PRIMARY_BPS)[0].loc[start:])
        pk = rebase(sim_kite.run(steps["production_v2"], V.PRIMARY_BPS)[0].loc[start:])
        navs[f"{aa}|sens:kite_prices|20.8"] = nk
        sens.append({"aa": aa, "sensitivity": "kite_prices", "cagr": S.cagr(nk),
                     "cagr_production_v2_same_tags": S.cagr(pk), "D": S.cagr(nk) - S.cagr(pk),
                     "max_dd": S.drawdown(nk)["max_dd"]})

        # Sensitivities, each against production_v2 on matching tags.
        prod_by_tags = {k: rebase(sim.run(V.build_production(ctx, eff, tags[k]),
                                          V.PRIMARY_BPS)[0].loc[start:]) for k in tags}
        variants = {
            "primary": (th, "event", "micro_own", False, "hybrid"),
            "ranks_only_tags": (tags["ranks_only"], "event", "micro_own", False, "ranks_only"),
            "semiannual_ranks": (tags["semiannual"], "event", "micro_own", False, "semiannual"),
            "unknown_to_sleeve": (th, "event", "unknown_to_sleeve", False, "hybrid"),
            "unknown_to_sc250": (th, "event", "unknown_to_sc250", False, "hybrid"),
            "micro_proxy": (th, "event", "micro_proxy", False, "hybrid"),
            "weekly_retag": (th, "weekly", "micro_own", False, "hybrid"),
            "sleeve_n100gate": (th, "event", "micro_own", True, "hybrid"),
        }
        for vn, (tg, rt, var, gate, tk) in variants.items():
            nv = rebase(sim.run(V.build_sleeve(ctx, eff, tg, rt, var, gate),
                                V.PRIMARY_BPS)[0].loc[start:])
            navs[f"{aa}|sens:{vn}|20.8"] = nv
            sens.append({"aa": aa, "sensitivity": vn, "cagr": S.cagr(nv),
                         "cagr_production_v2_same_tags": S.cagr(prod_by_tags[tk]),
                         "D": S.cagr(nv) - S.cagr(prod_by_tags[tk]),
                         "max_dd": S.drawdown(nv)["max_dd"]})

        # Tags and bucket distribution at every review (hybrid).
        for r, eff_d in zip(ctx.reviews, ctx.basket_eff):
            for k, tkr, nm, isin, w in ctx.baskets[eff_d]:
                t = th[r][k]
                tags_all.append({"aa": aa, "review": r.date(), "basket_eff": eff_d.date(),
                                 "isin": k, "ticker": tkr, "name": nm, "parent_weight": w,
                                 "bucket": t.bucket, "tag_source": t.source, "rank": t.rank,
                                 "snapshot": t.snapshot.date() if t.snapshot is not None else None})
        audit["per_book"][aa] = book_audit
        print(f"  done {aa}  ({time.time() - t0:.0f}s)", flush=True)

    # ── Assemble ───────────────────────────────────────────────────────────
    nav_df = pd.DataFrame(navs)
    nav_df = pd.concat([nav_df, pub.apply(rebase), bench.add_prefix("bench|").apply(rebase)], axis=1)
    nav_df.to_csv(OUT / "nav_curves.csv")
    sc = pd.DataFrame(score)
    sc.to_csv(OUT / "scorecard.csv", index=False)
    pd.concat(exp_all, axis=1).to_csv(OUT / "exposure_daily.csv")
    pd.DataFrame(sens).to_csv(OUT / "sensitivities.csv", index=False)
    pd.concat(summ_all, ignore_index=True).to_csv(OUT / "rebalance_summary.csv", index=False)
    pd.concat(det_all, ignore_index=True).to_csv(OUT / "rebalance_history.csv", index=False)
    tl = pd.concat(logs_all, ignore_index=True)
    tl.to_csv(OUT / "trade_log.csv", index=False)
    # N100 AND SC100: every trade, with both signals and what triggered it.
    nt = tl[tl["strategy"] == "n100_and_sc100"].copy()
    nt["review"] = pd.to_datetime(nt["review"])
    sg = eff.loc[nt["review"], [V.N100, V.SC100]].reset_index(drop=True)
    nt = nt.reset_index(drop=True)
    nt["n100"], nt["sc100"] = sg[V.N100].values, sg[V.SC100].values
    nt["state"] = np.where(nt["sleeve_weight"] > 0.5, "sleeve", "equity")
    prev = nt.groupby("aa")["state"].shift()
    nt["trigger"] = np.where(prev.isna(), "first review",
                             np.where(prev != nt["state"], "signal switch", "parent rebalance"))
    nt[["aa", "review", "entry", "n100", "sc100", "state", "trigger", "turnover_frac", "cost",
        "nav"]].to_csv(OUT / "n100_sc100_trades.csv", index=False)
    tg = pd.DataFrame(tags_all)
    tg.to_csv(OUT / "bucket_tags.csv", index=False)
    dist = (tg.assign(bucket=np.where(tg["tag_source"].isin(["rank>900", "unranked"]),
                                      "Unknown", tg["bucket"]))
              .pivot_table(index=["aa", "review"], columns="bucket", values="parent_weight",
                           aggfunc="sum", fill_value=0.0))
    src = tg.pivot_table(index=["aa", "review"], columns="tag_source", values="parent_weight",
                         aggfunc="sum", fill_value=0.0).add_prefix("src:")
    pd.concat([dist, src], axis=1).reset_index().to_csv(OUT / "bucket_distribution.csv", index=False)

    th_acc, uni = tag_accuracy(inp)
    th_acc.to_csv(OUT / "tag_accuracy_holdings.csv", index=False)
    em = error_model(uni)
    em.to_csv(OUT / "null_labels_error_model.csv")
    audit["tag_accuracy"] = {
        "holdings_rows": int(len(th_acc)),
        "holdings_agree_share": float(th_acc["agree"].mean()),
        "holdings_agree_weighted": float((th_acc["agree"] * th_acc["weight"]).sum()
                                         / th_acc["weight"].sum()),
        "universe_rows": int(len(uni)),
        "universe_agree_share_members_only": float(
            (uni[uni["truth"] != "Unknown"]["predicted"]
             == uni[uni["truth"] != "Unknown"]["truth"]).mean()),
    }

    # Yearly returns and the stats panel.
    yearly = {c: S.yearly(nav_df[c]) for c in nav_df.columns}
    pd.DataFrame(yearly).T.to_csv(OUT / "yearly_returns.csv")

    panel_rows = []
    for aa in PAIRS:
        refs = {"published_parent": nav_df[f"{aa}|published_parent"],
                "published_aa": nav_df[f"{aa}|published_aa"],
                "style_blend": nav_df[f"{aa}|style_blend"]}
        series = {**{f"{s}|{b:g}": nav_df[f"{aa}|{s}|{b:g}"] for s in STRATS for b in V.COST_BPS},
                  "published_parent": refs["published_parent"],
                  "published_aa": refs["published_aa"],
                  "style_blend": refs["style_blend"],
                  "static_mix|0": nav_df[f"{aa}|static_mix|0"],
                  **{f"bench:{k}": nav_df[f"bench|{k}"] for k in BENCH_SHEETS}}
        for sname, lv in series.items():
            row = {"aa": aa, "series": sname, **S.absolute(lv, cash_lvl)}
            for rn, rl in refs.items():
                row.update({f"{k}__vs_{rn}": v for k, v in S.relative(lv, rl).items()})
            panel_rows.append(row)
    pd.DataFrame(panel_rows).to_csv(OUT / "stats_panel.csv", index=False)

    # Headline.
    head = []
    for aa in PAIRS:
        for bps in V.COST_BPS:
            c = {s: S.cagr(nav_df[f"{aa}|{s}|{bps:g}"]) for s in STRATS}
            pp, pa = S.cagr(nav_df[f"{aa}|published_parent"]), S.cagr(nav_df[f"{aa}|published_aa"])
            rel_blend = S.relative(nav_df[f"{aa}|sleeve|{bps:g}"], nav_df[f"{aa}|style_blend"])
            head.append({"aa": aa, "cost_bps": bps, "cagr_sleeve": c["sleeve"],
                         "cagr_production_v2": c["production_v2"],
                         "cagr_harness_parent": c["parent"],
                         "cagr_sc100_only": c["sc100_only"], "cagr_sc250_only": c["sc250_only"],
                         "sleeve_minus_sc100_only": c["sleeve"] - c["sc100_only"],
                         "sleeve_minus_sc250_only": c["sleeve"] - c["sc250_only"],
                         "cagr_published_parent": pp, "cagr_published_aa": pa,
                         "D": c["sleeve"] - c["production_v2"],
                         "sleeve_minus_published_parent": c["sleeve"] - pp,
                         "sleeve_minus_published_aa": c["sleeve"] - pa,
                         "sleeve_minus_harness_parent": c["sleeve"] - c["parent"],
                         "sleeve_minus_style_blend": rel_blend.get("excess_cagr", np.nan),
                         "style_blend_from": rel_blend.get("rel_start"),
                         "maxdd_sleeve": S.drawdown(nav_df[f"{aa}|sleeve|{bps:g}"])["max_dd"],
                         "maxdd_published_parent": S.drawdown(nav_df[f"{aa}|published_parent"])["max_dd"],
                         "maxdd_published_aa": S.drawdown(nav_df[f"{aa}|published_aa"])["max_dd"]})
    hd = pd.DataFrame(head)
    hd.to_csv(OUT / "headline.csv", index=False)

    p = hd[hd["cost_bps"] == V.PRIMARY_BPS].set_index("aa")
    g1_books = int((p["D"] > 0).sum())
    gates = {
        "G1": {"rule": "D > 0 on >= 3 of 4 books AND on both SCMO_0044 and SCMO_0045",
               "D_per_book": p["D"].to_dict(), "books_positive": g1_books,
               "passed": bool(g1_books >= 3 and p.loc["SCMO_0044", "D"] > 0
                              and p.loc["SCMO_0045", "D"] > 0)},
        "G2": {"rule": "CAGR(sleeve @20.8) - CAGR(static mix) > 0 on >= 3 books", "per_book": g2,
               "books_positive": int(sum(v["timing_part"] > 0 for v in g2.values()))},
        "G3": {"rule": "D with all-cash sleeve > 0 on >= 3 books", "per_book": g3,
               "books_positive": int(sum(v["D"] > 0 for v in g3.values()))},
    }
    gates["G2"]["passed"] = gates["G2"]["books_positive"] >= 3
    gates["G3"]["passed"] = gates["G3"]["books_positive"] >= 3
    (OUT / "gates_g1_g3.json").write_text(json.dumps(gates, indent=2, default=str), encoding="utf-8")

    uf = unfillable_holdings(inp)
    uf.to_csv(OUT / "unfillable_holdings.csv", index=False)
    audit["close_fallback_cells"] = inp["sim"].close_fallback_cells
    audit["unfillable_holdings"] = {
        "rows": int(len(uf)),
        "by_name": {f"{a}|{t}": {"reviews": int(len(g)), "first": str(g["review"].min()),
                                 "last": str(g["review"].max()),
                                 "mean_weight": float(g["parent_weight"].mean())}
                    for (a, t), g in uf.groupby(["aa", "ticker"])},
        "avg_book_share": {a: float(uf[uf["aa"] == a]["parent_weight"].sum() / len(inp["reviews"]))
                           for a in PAIRS},
    }
    audit["seconds"] = round(time.time() - t0, 1)
    (OUT / "audit.json").write_text(json.dumps(audit, indent=2, default=str), encoding="utf-8")

    pd.set_option("display.width", 220)
    print("\nHEADLINE @ 20.8 bps (pp/yr)")
    show = p[["cagr_sleeve", "cagr_production_v2", "cagr_published_parent", "cagr_published_aa",
              "D", "sleeve_minus_published_parent", "sleeve_minus_published_aa",
              "sleeve_minus_style_blend", "maxdd_sleeve", "maxdd_published_parent",
              "maxdd_published_aa"]] * 100
    print(show.round(2).to_string())
    for g, v in gates.items():
        print(f"{g}: passed={v['passed']}")
    print("\nSENSITIVITIES (D pp/yr)")
    print((pd.DataFrame(sens).pivot(index="sensitivity", columns="aa", values="D") * 100)
          .round(2).to_string())
    print("\n", json.dumps(audit["tag_accuracy"], indent=1))


if __name__ == "__main__":
    main()
