# -*- coding: utf-8 -*-
"""Export every number needed to back-calculate T11's NAV series by hand (hold the parent, Part A, Part B; 0 / 20.8 / 50 bps).

Reads the APPROVED inputs through the T11 engine's own loaders (analysis/t11_engine.py: `Book`, `simulate`), so the prices, fills, weights and
units written here are exactly the arrays the engine used. Writes tests/T11/evidence/backcalc/ (a new folder; nothing in evidence/headline is touched).
Then run tests/T11/backcalc_verify.py, which rebuilds every NAV from these files alone (no engine import) and compares with evidence/headline.

    python tests/T11/backcalc_export.py        (from AA/)
"""
from __future__ import annotations

import shutil
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
sys.dont_write_bytecode = True
AA = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(AA / "analysis"))
import t11_engine as E  # noqa: E402

OUT = AA / "tests" / "T11" / "evidence" / "backcalc"
HEAD = AA / "tests" / "T11" / "evidence" / "headline"
RUNS = ("hold_parent", "strategy_fixed50", "strategy")       # strategy_fixed50 = Part A, strategy = Part B
COSTS = (0.0, 20.8, 50.0)


def gold_table(bk: E.Book) -> pd.DataFrame:
    """GOLDBEES raw bars (D09), MCX range (D24b daily), the de-spike step by step, and the close / fill the engine used; LBES level."""
    c = E.common(E.END)
    g = pd.read_parquet(E.ap(E.GOLD_D09))
    g["date"] = pd.to_datetime(g["date"])
    g = g.set_index("date").sort_index()
    g = g[~g.index.duplicated(keep="last")]
    m = c["mcx_daily"]
    cal = bk.cal
    gr = g.reindex(cal)
    mr = m.reindex(cal)
    rng = (mr["high"] - mr["low"]) / mr["close"]
    band = rng + E.DESPIKE_TOL
    lo, hi = gr["close"] * (1 - band), gr["close"] * (1 + band)
    has = rng.notna()
    o = gr["open"].where(~has, gr["open"].clip(lower=lo, upper=hi))
    h = gr["high"].where(~has, gr["high"].clip(upper=hi))
    l_ = gr["low"].where(~has, gr["low"].clip(lower=lo))
    h = np.maximum(h, np.maximum(o, gr["close"]))
    l_ = np.minimum(l_, np.minimum(o, gr["close"]))
    fill = (o + h + l_ + gr["close"]) / 4
    df = pd.DataFrame({"idx": np.arange(bk.T), "date": cal.date,
                       "gb_open": gr["open"].values, "gb_high": gr["high"].values, "gb_low": gr["low"].values, "gb_close": gr["close"].values,
                       "mcx_high": mr["high"].values, "mcx_low": mr["low"].values, "mcx_close": mr["close"].values,
                       "mcx_range": rng.values, "band": band.values, "clip_lo": lo.values, "clip_hi": hi.values,
                       "gb_open_clipped": o.values, "gb_high_clipped": h.values, "gb_low_clipped": l_.values, "gb_ohlc4_despiked": fill.values,
                       "gb_has_own_bar": ~bk.gold_nobar, "gb_has_mcx_range": ~bk.gold_norange & ~bk.gold_nobar,
                       "goldbees_close_used": bk.g, "goldbees_fill_used": bk.gf, "lbes_level_used": bk.L})
    # the engine's arrays must equal the step-by-step columns wherever the session has its own bar
    own = df["gb_has_own_bar"].values
    assert np.allclose(df.loc[own, "gb_close"], df.loc[own, "goldbees_close_used"], rtol=0, atol=0)
    assert np.array_equal(df.loc[own, "gb_ohlc4_despiked"].values, df.loc[own, "goldbees_fill_used"].values)
    return df


def stock_tables(p: str, bk: E.Book, used: list[int]):
    """Long table of every stock that is ever in a basket in the window: raw D18 bar, the correction, OHLC4, the close and fill used."""
    o = pd.read_csv(E.ap(E.HM / f"{p}_ohlc.csv"), parse_dates=["date"]).drop_duplicates(["date", "stock"])
    o = o[o["date"] <= E.END]
    cor = pd.read_csv(E.ap(E.HM / "price_corrections.csv"), parse_dates=["ex_date"])
    rows = []
    cal = bk.cal
    for i in used:
        st = bk.stocks[i]
        d = o[o["stock"] == st].set_index("date").reindex(cal)
        fac = pd.Series(1.0, index=cal)
        for r in cor.itertuples():
            if p in r.applies_to.split(";") and r.stock == st:
                fac[cal < r.ex_date] *= r.factor
        oc, hc, lc, cc = (d[f] * fac for f in ("open", "high", "low", "close"))
        o4 = ((oc + hc + lc + cc) / 4).fillna(cc)
        rows.append(pd.DataFrame({"book": p, "idx": np.arange(bk.T), "date": cal.date, "stock": st,
                                  "open_raw": d["open"].values, "high_raw": d["high"].values, "low_raw": d["low"].values, "close_raw": d["close"].values,
                                  "src": d["src"].values, "has_bar": ~bk.nobar[:, i], "correction_factor": fac.values,
                                  "open": oc.values, "high": hc.values, "low": lc.values, "close": cc.values, "ohlc4": o4.values,
                                  "close_used": bk.C[:, i], "fill_used": bk.P[:, i]}))
        hb = ~bk.nobar[:, i]
        assert np.array_equal(o4.values[hb], bk.P[hb, i]), st
    return pd.concat(rows, ignore_index=True)


def main():
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    sessions, prices, wide_c, wide_p, weights, baskets, holdings, tsum, tlines, navs, decs = [], [], {}, {}, [], [], [], [], [], [], []
    for p in E.PARENTS:
        bk = E.Book(p)
        dec = bk.decisions()
        decs.append(dec)
        idx = dec["decision_idx"].values
        s = dec["state"].values.astype(float)
        gw_real = np.where(dec["g"].values == 1, E.GW_BUY, E.GW_SELL)
        r = E.raw_parent(p)
        # baskets in the window: b0 .. last basket whose session is inside the window
        bl = [b for b in range(len(bk.eff)) if b >= bk.b0 and bk.bidx[b] < bk.T]
        used = sorted({int(i) for b in bl for i in np.flatnonzero(bk.W[b] > 0)})
        for n, b in enumerate(bl):
            sess = bk.cal[max(int(bk.bidx[b]), 0)]
            baskets.append({"book": p, "basket_no": n, "available_date": bk.eff[b].date(), "session_date": sess.date(), "idx": max(int(bk.bidx[b]), 0),
                            "n_held": int((bk.W[b] > 0).sum()), "raw_weight_sum": float(r["wsum"].iloc[b]), "role": "initial" if b == bk.b0 else "change"})
            for i in np.flatnonzero(bk.W[b] > 0):
                weights.append({"book": p, "basket_no": n, "available_date": bk.eff[b].date(), "session_date": sess.date(), "stock": bk.stocks[i],
                                "raw_weight": float(bk.W[b, i] * r["wsum"].iloc[b]), "raw_weight_sum": float(r["wsum"].iloc[b]), "weight": float(bk.W[b, i])})
        gt = gold_table(bk)
        gt.insert(0, "book", p)
        sessions.append(gt)
        st = stock_tables(p, bk, used)
        prices.append(st)
        wide_c[p] = pd.DataFrame(bk.C[:, used], index=bk.cal.date, columns=[bk.stocks[i] for i in used]).rename_axis("date")
        wide_p[p] = pd.DataFrame(bk.P[:, used], index=bk.cal.date, columns=[bk.stocks[i] for i in used]).rename_axis("date")
        # initial units at T0 (before any e scaling): u0 = (w_i / OHLC4_i(T0)) / sum_i (w_i / OHLC4_i(T0)) * close_i(T0)
        for run in RUNS:
            for cost in COSTS:
                e = np.ones(len(s)) if run == "hold_parent" else s
                gw = gw_real if run == "strategy" else None
                nav, trs, pos = E.simulate(bk, idx, e, cost, record=True, gw=gw)
                gwa = np.full(len(e), E.GW_FIX) if gw is None else gw
                e0, g0 = float(e[0]), float(gwa[0])
                cur = {bk.stocks[i]: float(bk.u0[i] * e0) for i in np.flatnonzero(bk.u0 * e0)}
                if (1 - e0) * g0 > 0:
                    cur["GOLDBEES"] = (1 - e0) * g0 / bk.g[0]
                if (1 - e0) * (1 - g0) > 0:
                    cur["LBES"] = (1 - e0) * (1 - g0) / bk.L[0]
                after = {}
                for x in pos:
                    after.setdefault(x["date"], {})[x["instrument"]] = x["units"]
                events = [(0, "initial", None, dict(cur))]
                for t in trs:
                    events.append((t["idx"], t["kind"], t, after.get(t["date"], {})))
                stock_ix = {name: k for k, name in enumerate(bk.stocks)}
                prev = None
                comp = np.zeros((bk.T, 3))
                for k, (ti, kind, info, units) in enumerate(events):
                    to = events[k + 1][0] - 1 if k + 1 < len(events) else bk.T - 1
                    for inst, u in units.items():
                        pc = bk.g[ti] if inst == "GOLDBEES" else bk.L[ti] if inst == "LBES" else bk.C[ti, stock_ix[inst]]
                        holdings.append({"book": p, "run": run, "cost_bps": cost, "event_no": k, "kind": kind, "from_idx": ti, "from_date": bk.cal[ti].date(),
                                         "to_date": bk.cal[to].date(), "instrument": inst, "units": u, "close_on_from_date": pc, "value_at_close": u * pc})
                    sl = slice(ti, to + 1)
                    for inst, u in units.items():
                        if inst == "GOLDBEES":
                            comp[sl, 1] += u * bk.g[sl]
                        elif inst == "LBES":
                            comp[sl, 2] += u * bk.L[sl]
                        else:
                            comp[sl, 0] += u * bk.C[sl, stock_ix[inst]]
                    if info is not None:
                        ow = cost / 2e4
                        w = bk.W[bk.basket_at[ti]]
                        e_new, gw_new = info["e_after"], info["gw_after"]
                        tsum.append({"book": p, "run": run, "cost_bps": cost, "date": bk.cal[ti].date(), "idx": ti, "kind": kind, "basket_eff": info["basket_eff"],
                                     "e_after": e_new, "gw_after": gw_new if run != "hold_parent" else np.nan, "V_at_fill": info["V"], "traded": info["traded"],
                                     "ow_per_side": ow, "cost": info["cost"], "k_scale": (info["V"] - info["cost"]) / info["V"], "V_after_at_fill": info["V_after"],
                                     "nav_close_after": info["nav_close_after"]})
                        V = info["V"]
                        insts = sorted(set(prev) | set(units) | {bk.stocks[i] for i in np.flatnonzero(w > 0)} | ({"GOLDBEES", "LBES"} if e_new < 1 else set()))
                        for inst in insts:
                            if inst == "GOLDBEES":
                                px, tw = bk.gf[ti], (1 - e_new) * gw_new
                            elif inst == "LBES":
                                px, tw = bk.L[ti], (1 - e_new) * (1 - gw_new)
                            else:
                                px, tw = bk.P[ti, stock_ix[inst]], e_new * w[stock_ix[inst]]
                            ub, ua = prev.get(inst, 0.0), units.get(inst, 0.0)
                            tlines.append({"book": p, "run": run, "cost_bps": cost, "date": bk.cal[ti].date(), "idx": ti, "kind": kind, "instrument": inst,
                                           "fill_price": px, "units_before": ub, "value_before_at_fill": ub * px, "target_weight": tw,
                                           "target_value_precost": tw * V, "abs_traded": abs(tw * V - ub * px), "units_after": ua, "value_after_at_fill": ua * px})
                    prev = units
                assert np.allclose(comp.sum(axis=1), nav, rtol=1e-12, atol=0), (p, run, cost)
                navs.append(pd.DataFrame({"book": p, "idx": np.arange(bk.T), "date": bk.cal.date, "run": run, "cost_bps": cost,
                                          "stock_value": comp[:, 0], "goldbees_value": comp[:, 1], "lbes_value": comp[:, 2], "nav": nav}))
    pd.concat(sessions, ignore_index=True).to_csv(OUT / "sessions_gold_cash.csv", index=False)
    pd.concat(prices, ignore_index=True).to_csv(OUT / "stock_prices_long.csv", index=False)
    for p in E.PARENTS:
        wide_c[p].to_csv(OUT / f"close_used_{p}.csv")
        wide_p[p].to_csv(OUT / f"fill_used_{p}.csv")
    pd.DataFrame(baskets).to_csv(OUT / "baskets.csv", index=False)
    pd.DataFrame(weights).to_csv(OUT / "basket_weights.csv", index=False)
    pd.concat(decs, ignore_index=True).to_csv(OUT / "decisions.csv", index=False)
    pd.DataFrame(holdings).to_csv(OUT / "holdings_units.csv", index=False)
    pd.DataFrame(tsum).to_csv(OUT / "trades_summary.csv", index=False)
    pd.DataFrame(tlines).to_csv(OUT / "trade_lines.csv", index=False)
    nd = pd.concat(navs, ignore_index=True)
    nd.to_csv(OUT / "nav_daily.csv", index=False)
    # agreement with the stored headline evidence
    hd = pd.read_csv(HEAD / "daily_nav.csv")
    hd = hd[hd["run"].isin(RUNS)]
    hd["date"] = pd.to_datetime(hd["date"]).dt.date
    mm = nd.merge(hd, on=["book", "date", "run", "cost_bps"], suffixes=("", "_head"))
    assert len(mm) == len(nd), (len(mm), len(nd))
    rel = float((mm["nav"] / mm["nav_head"] - 1).abs().max())
    print(f"backcalc pack written to {OUT}; {len(nd):,} NAV rows; max relative gap to evidence/headline/daily_nav.csv: {rel:.2e}")
    assert rel < 1e-12


if __name__ == "__main__":
    main()
