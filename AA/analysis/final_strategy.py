# -*- coding: utf-8 -*-
"""
Final strategy test, on all four AA portfolios.

Rule
  1. Hold the whole parent portfolio while Nifty 100, Nifty Midcap 100 and
     Nifty Smallcap 100 are all BUY on the weekly production supertrend.
     Otherwise hold the alternate (defensive) sleeve.
  2. The sleeve is gold (GOLDBEES) + cash (LBES). Its split is decided only
     while the book is in the sleeve, from gold's weekly supertrend computed
     on MAUc1 (MCX gold futures, continuous):
       MAUc1 supertrend BUY  -> 80% GOLDBEES / 20% cash
       MAUc1 supertrend SELL -> 20% GOLDBEES / 80% cash
     The MAUc1 signal is the desk's production ST.py, run unmodified on MAUc1
     exactly as the Friday job runs it for the indices (mauc1_st_production.py):
     NSE-calendar weekly candles, read from Master_MAUc1.xlsx like the index
     signals. Before its first signal (2015-03-13) a sleeve week holds 50/50.
     GOLDBEES is bought at the trade session's OHLC4 after its open, high and
     low are pulled into close +/- (MCX gold's range that day + 0.5%), which
     removes ETF-only spikes.

Reading of "decided only when we move into the alternate asset class":
  primary  - the split is checked at every weekly review while the book is
             in the sleeve (a gold flip mid-spell re-splits 80/20 <-> 20/80);
  variant  - the split is fixed at the review that moves the book into the
             sleeve, and held until the book goes back to equity.

Engine: the v2 harness (units, next-session fills, 20.8 bps round trip, Eikon
stock prices). Unchanged target -> no trade, so weights drift between trades.
Periods: live window 2021-11-03 -> 2026-08-21 (the four AA books) and
2014-07-07 -> 2021-10-29 (the four parents' real baskets, before the books
existed).

Writes evidence/final_strategy/: CSVs for every step and
final_strategy_workbook.xlsx (built by final_strategy_excel.py).
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

import segment_v2 as V
import segment_v2_data as D
from common import AA_DIR, AA_INDEX_CSV, EVIDENCE_DIR, PAIRS, PARENT_INDEX_CSV, load_index_levels
from gold_sleeve_test import gold_signal
from index_builder import Panel
from run_segment_v2 import load_inputs
from supertrend import supertrend, to_weekly
from why_n100sc100 import eikon_by_isin, gold_cash
from why_n100sc100 import calendar as full_calendar
from why_parents_oos import END as OOS_END
from why_parents_oos import START as OOS_START
from why_parents_oos import old_ranks

OUT = EVIDENCE_DIR / "final_strategy"
OUT.mkdir(parents=True, exist_ok=True)
KEYS = (V.N100, "MC100", V.SC100)
G_BUY, G_SELL, G_NONE = 0.8, 0.2, 0.5
IS_END = pd.Timestamp("2026-08-21")


# ── signals ────────────────────────────────────────────────────────────────
def master(n: str) -> pd.Series:
    d = pd.read_excel(D.MASTER_DIR / f"Master_{n}.xlsx")
    d["Date"] = pd.to_datetime(d["Date"])
    s = d.dropna(subset=["SIGN"]).set_index("Date")["SIGN"].sort_index()
    return s[~s.index.duplicated(keep="last")]


def friday_weekly(d: pd.DataFrame) -> pd.DataFrame:
    """
    Weekly candles that close on Friday: Monday-Friday sessions, labelled by
    the week's last session. A Saturday or Sunday special session (Budget day
    2025-02-01, 2026-02-01) rolls into the following week, so the candle a
    Friday review reads is complete at that Friday's close. Otherwise the same
    construction as supertrend.to_weekly: high = max, low = min, close = last.
    """
    d = d.sort_index().copy()
    key = (d.index + pd.Timedelta(days=2)).to_period("W")      # Sat/Sun -> next Mon-Sun week
    g = d.groupby(key)
    w = pd.DataFrame({"high": g["high"].max(), "low": g["low"].min(), "close": g["close"].last(),
                      "volume": 0.0})
    w.index = g.apply(lambda x: x.index[-1])
    w.index.name = "date"
    w["HML"] = w["high"] - w["low"]
    w["PClose"] = w["close"].shift()
    w["HMC"] = (w["high"] - w["PClose"]).abs()
    w["LMC"] = (w["low"] - w["PClose"]).abs()
    w["TR"] = w[["HML", "HMC", "LMC"]].max(axis=1)
    w["AHML"] = 0.5 * w["high"] + 0.5 * w["low"]
    return w


def gold_daily_eikon() -> pd.DataFrame:
    from common import CACHE_DIR
    g = pd.read_parquet(CACHE_DIR / "why_gold_ohlc_eikon.parquet")
    d = g.set_index("date").sort_index()
    d = d[~d.index.duplicated(keep="last")]
    d["volume"] = 0.0
    return d


def gold_weekly_table() -> pd.DataFrame:
    """Friday-close weekly GOLDBEES candles (Eikon daily OHLC) and the supertrend columns."""
    d = gold_daily_eikon()
    w = friday_weekly(d)
    st = supertrend(w)
    t = pd.concat([w[["high", "low", "close", "PClose", "HML", "HMC", "LMC", "TR", "AHML"]], st], axis=1)
    t.index.name = "week_end"
    return t, d


def gold_prices(cal: pd.DatetimeIndex, d: pd.DataFrame, fill: pd.Series):
    """GOLDBEES marking close (Eikon) and its trade-session fill price on a calendar."""
    close = d["close"].reindex(cal.union(d.index)).ffill().reindex(cal)
    return close, fill.reindex(cal)


MAUC1_CSV = OUT / "mauc1" / "mauc1_daily_clean.csv"
DESPIKE_TOL = 0.005
FRA_MAUC1 = AA_DIR / "Historical Data" / "FRA_MAUc1"      # mauc1_st_production.py output


def mauc1_st():
    """
    Gold's weekly supertrend as production ST.py computed it on MAUc1: its weekly
    candles (weekIndexDf), its supertrend and SIGN (Master_MAUc1.xlsx), and the daily
    frame it built them from (indexDf: NSE trading days, forward-filled). Indexed by
    the week label, which is the week's last NSE session, i.e. the review.
    """
    man = json.loads((FRA_MAUC1 / "run_manifest.json").read_text())
    dc = next(r["dateCode"] for r in man["runs"] if r["permanent_file_written"])
    fin = FRA_MAUC1 / "RSI" / "Final"
    w = pd.read_excel(fin / "MAUc1" / f"weekIndexDf_{dc}_W.xlsx", index_col=0)
    dd = pd.read_excel(fin / "MAUc1" / f"indexDf_{dc}_W.xlsx", index_col=0)
    m = pd.read_excel(fin / "Analysis" / "Master_MAUc1.xlsx")
    w.index, dd.index = pd.to_datetime(w.index), pd.to_datetime(dd.index)
    m = m.assign(Date=pd.to_datetime(m["Date"])).set_index("Date")
    t = w.rename(columns={"High": "high", "Low": "low", "Close": "close"})[
        ["high", "low", "close", "PClose", "HML", "HMC", "LMC", "TR", "AHML"]].copy()
    label = dd.groupby("Week_Con").apply(lambda x: x.index[-1])
    t["last_session"] = t.index
    t["sessions"] = dd.groupby("Week_Con").size().set_axis(label.values).reindex(t.index)
    t = t.join(m[["EMA_TR", "BUB", "BLB", "FUB", "FLB", "ST", "SIGN"]].rename(columns={"EMA_TR": "wATR"}))
    t["signal"] = t["SIGN"].map({"BUY": 1.0, "SELL": 0.0})
    t.index.name = "review"
    daily = dd[["High", "Low", "Close"]].rename(columns=str.lower)
    daily["candle_review"] = dd["Week_Con"].map(pd.Series(label.values, index=label.index))
    daily.index.name = "date"
    return t, daily, dc


def mauc1_daily() -> pd.DataFrame:
    """MAUc1 daily OHLC, cleaned by mauc1_signal.load_clean (see mauc1_cleaning_log.csv)."""
    d = pd.read_csv(MAUC1_CSV, index_col=0, parse_dates=True)
    return d[["open", "high", "low", "close"]].assign(volume=0.0)


def review_weekly(d: pd.DataFrame, reviews) -> pd.DataFrame:
    """
    Weekly candles cut at the review dates: each holds the sessions after the
    previous review up to and including this one, labelled by the review date.
    A review's candle is therefore exactly what was known at its close. MCX
    sessions after a mid-week review (an NSE-holiday Friday) fall into the next
    candle. Same columns as supertrend.to_weekly.
    """
    rv = pd.DatetimeIndex(sorted(set(reviews)))
    d = d[d.index <= rv[-1]].sort_index()
    key = rv[np.searchsorted(rv.values, d.index.values, side="left")]
    g = d.assign(key=key).groupby("key")
    w = pd.DataFrame({"high": g["high"].max(), "low": g["low"].min(), "close": g["close"].last(), "volume": 0.0,
                      "last_session": g.apply(lambda x: x.index[-1]), "sessions": g.size()})
    w.index.name = "date"
    w["HML"] = w["high"] - w["low"]
    w["PClose"] = w["close"].shift()
    w["HMC"] = (w["high"] - w["PClose"]).abs()
    w["LMC"] = (w["low"] - w["PClose"]).abs()
    w["TR"] = w[["HML", "HMC", "LMC"]].max(axis=1)
    w["AHML"] = 0.5 * w["high"] + 0.5 * w["low"]
    return w


def despiked_goldbees(g: pd.DataFrame, m: pd.DataFrame, tol: float = DESPIKE_TOL) -> pd.DataFrame:
    """
    GOLDBEES bars with ETF-only spikes removed, for fills: open, high and low
    are pulled into close x (1 +/- (MCX gold's high-low range that day as a
    share of its close + tol)). Days without an MCX bar keep the raw bar.
    fill = (open + high + low + close) / 4 of the cleaned bar.
    """
    rng = ((m["high"] - m["low"]) / m["close"]).reindex(g.index)
    band = rng + tol
    lo, hi = g["close"] * (1 - band), g["close"] * (1 + band)
    has = rng.notna()
    o = g["open"].where(~has, g["open"].clip(lower=lo, upper=hi))
    h = g["high"].where(~has, g["high"].clip(upper=hi))
    l_ = g["low"].where(~has, g["low"].clip(lower=lo))
    h = np.maximum(h, np.maximum(o, g["close"]))
    l_ = np.minimum(l_, np.minimum(o, g["close"]))
    f = pd.DataFrame({"open": g["open"], "high": g["high"], "low": g["low"], "close": g["close"], "mcx_range": rng, "band": band,
                      "open_clean": o, "high_clean": h, "low_clean": l_})
    f["ohlc4_raw"] = (g["open"] + g["high"] + g["low"] + g["close"]) / 4
    f["fill_ohlc4_clean"] = (o + h + l_ + g["close"]) / 4
    f["changed"] = (f["fill_ohlc4_clean"] - f["ohlc4_raw"]).abs() > 1e-9
    return f


def parent_fill_nav(sim, pos: pd.DataFrame, log: pd.DataFrame) -> pd.Series:
    """
    The parent portfolio valued at each session's fill prices (stocks at
    OHLC4, close fallback, last close if no bar), holding the units it had
    coming into the session: what the harness would get if it traded the
    parent at that session's fill.
    """
    cal = sim.cal
    n = len(cal)
    navs = log.set_index("entry")["nav_at_fill"]
    entries = sorted(pos.entry.unique())
    ent_idx = [cal.get_loc(e) for e in entries]
    out = np.full(n, np.nan)
    units = {}
    k = 0
    for i in range(n):
        if units:
            v = 0.0
            for t, u in units.items():
                p = sim._pf(t, i)
                v += u * (p if np.isfinite(p) else 0.0)
            out[i] = v
        while k < len(entries) and ent_idx[k] == i:
            e = entries[k]
            g = pos[pos.entry == e]
            units = {r.key: r.w_after * navs.loc[e] / r.fill_price for r in g.itertuples() if r.w_after > 0}
            k += 1
    return pd.Series(out, index=cal).fillna(1.0)


def gold_at(gs: pd.Series, r: pd.Timestamp) -> float:
    idx = gs.index[gs.index <= r]
    return float(gs.loc[idx[-1]]) if len(idx) else np.nan


def share_maps(steps, gs):
    """Gold share of the sleeve per review: weekly re-check (primary) and fixed at entry (variant)."""
    weekly, entry = {}, {}
    prev_in, cur = False, None
    for st in steps:
        g = gold_at(gs, st.review)
        share = G_NONE if np.isnan(g) else (G_BUY if g == 1.0 else G_SELL)
        weekly[st.review] = share
        in_sleeve = st.sleeve > 1e-9
        if in_sleeve and not prev_in:
            cur = share
        entry[st.review] = cur if in_sleeve else share
        prev_in = in_sleeve
    return weekly, entry


# ── stats ──────────────────────────────────────────────────────────────────
def stats(nav: pd.Series, cash_lvl: pd.Series) -> dict:
    n = nav.dropna()
    yrs = (n.index[-1] - n.index[0]).days / 365.25
    r = n.pct_change().dropna()
    rc = cash_lvl.reindex(n.index).pct_change().reindex(r.index).fillna(0.0)
    c = float((n.iloc[-1] / n.iloc[0]) ** (1 / yrs) - 1)
    dd = float((n / n.cummax() - 1).min())
    f = n.resample("W-FRI").last().dropna()
    ddf = float((f / f.cummax() - 1).min())
    ex = r - rc
    return {"start": n.index[0].date(), "end": n.index[-1].date(), "cagr": c, "vol": float(r.std() * np.sqrt(252)),
            "max_dd_daily": dd, "max_dd_friday": ddf, "calmar": c / abs(dd) if dd else np.nan,
            "sharpe_vs_cash": float(ex.mean() / ex.std() * np.sqrt(252)) if ex.std() > 0 else np.nan,
            "total_return": float(n.iloc[-1] / n.iloc[0] - 1)}


def yearly(nav: pd.Series) -> pd.Series:
    n = nav.dropna()
    ye = n.groupby(n.index.year).last()
    base = pd.concat([pd.Series([n.iloc[0]], index=[ye.index[0] - 1]), ye]).shift(1).iloc[1:]
    return ye / base - 1


def units_frame(pos: pd.DataFrame, log: pd.DataFrame, sim, keys=(V.GOLD, V.CASH)) -> pd.DataFrame:
    """Daily units of gold and cash held, from the harness position log."""
    cal = sim.cal
    u = pd.DataFrame(0.0, index=cal, columns=list(keys))
    navs = log.set_index("entry")["nav_at_fill"]
    rows = pos.copy()
    for e, g in rows.groupby("entry"):
        i = cal.get_loc(e)
        for k in keys:
            x = g[g.key == k]
            w = float(x.w_after.iloc[0]) if len(x) else 0.0
            fp = float(x.fill_price.iloc[0]) if len(x) else np.nan
            u.iloc[i:, u.columns.get_loc(k)] = (w * navs.loc[e] / fp) if w > 0 else 0.0
    return u


# ── one period ─────────────────────────────────────────────────────────────
def run_period(label, sim, cal, reviews, sig, ctxs, tags_by, gs, start, end, sleeve_px, gs_gb=None):
    res, curves, trades, positions, weekly_rows, daily = [], {}, [], [], None, {}
    for aa, ctx in ctxs.items():
        st_tri = V.build_whole_book_and(ctx, sig, keys=KEYS)
        st_par = V.build_parent(ctx, sig)
        st_cur = V.build_production(ctx, sig, tags_by[aa])
        w_map, e_map = share_maps(st_tri, gs)
        w_gb, _ = share_maps(st_tri, gs_gb) if gs_gb is not None else (None, None)
        sleeve_revs = [s.review for s in st_tri if s.sleeve > 1e-9]
        same = float(np.mean([w_map[r] for r in sleeve_revs])) if sleeve_revs else 0.5
        runs = {"FINAL: triple + 80/20 gold-timed sleeve (weekly re-check)": (st_tri, w_map),
                "variant: triple + 80/20 split fixed at sleeve entry": (st_tri, e_map),
                "variant: final rule with the GOLDBEES gold signal (previous)": (st_tri, w_gb),
                "triple + fixed 50/50 sleeve": (st_tri, 0.5),
                f"triple + fixed {same:.0%} gold sleeve (same average gold)": (st_tri, same),
                "triple + all-cash sleeve": (st_tri, 0.0),
                "current rule (FS>=0.60) + 50/50 sleeve": (st_cur, 0.5),
                "parent (no overlay)": (st_par, 0.5)}
        for name, (st, gsh) in runs.items():
            nav, log, pos = sim.run(st, V.PRIMARY_BPS, gold_share=gsh, positions=True, close_on_trade_day=True)
            full = nav.copy()
            nav = nav.loc[start:end]
            nav = nav / nav.iloc[0]
            s = stats(nav, sleeve_px[V.CASH])
            lg = log.copy()
            lg["gold_share_of_sleeve"] = [(gsh.get(r, np.nan) if isinstance(gsh, dict) else gsh) if sw > 0 else 0.0
                                          for r, sw in zip(lg.review, lg.sleeve_weight)]
            lg["kind"] = np.where(lg.sleeve_weight.shift(1).fillna(-1) != lg.sleeve_weight,
                                  np.where(lg.sleeve_weight > 0, "equity -> sleeve", "sleeve -> equity"),
                                  np.where(lg.sleeve_weight > 0, "sleeve re-split", "parent rebalance"))
            lg.loc[lg.index[0], "kind"] = "initial buy"
            in_win = lg[(lg.entry >= start) & (lg.entry <= end)]
            ex = V.exposure(st, cal).loc[start:end]
            s.update({"period": label, "aa": aa, "parent": ctx.parent, "strategy": name,
                      "avg_equity_weight": float(ex.mean()),
                      "switches_equity_sleeve": int(in_win.kind.isin(["equity -> sleeve", "sleeve -> equity"]).sum()),
                      "sleeve_resplits": int((in_win.kind == "sleeve re-split").sum()),
                      "trades": int(len(in_win)), "cost_paid_share_of_nav": float((in_win.cost / in_win.nav).sum())})
            res.append(s)
            curves[f"{label}|{aa}|{name}"] = nav
            if name.startswith(("FINAL", "variant", "parent", "triple + fixed 50/50")):
                lg.insert(0, "strategy", name); lg.insert(0, "aa", aa); lg.insert(0, "period", label)
                trades.append(lg)
                p = pos.copy()
                p.insert(0, "strategy", name); p.insert(0, "aa", aa); p.insert(0, "period", label)
                positions.append(p)
            if name.startswith("FINAL"):
                u = units_frame(pos, log, sim)
                dd = pd.DataFrame({"harness_nav": full, "gold_units": u[V.GOLD], "cash_units": u[V.CASH],
                                   "gold_price": sleeve_px[V.GOLD], "cash_level": sleeve_px[V.CASH],
                                   "gold_fill_ohlc4": pd.Series(sim.fill[:, sim.col[V.GOLD]], index=cal)}).loc[:end]
                dd["gold_value"] = dd.gold_units * dd.gold_price
                dd["cash_value"] = dd.cash_units * dd.cash_level
                dd["equity_value"] = dd.harness_nav - dd.gold_value - dd.cash_value
                daily[aa] = dd
                if weekly_rows is None:
                    wk = []
                    for stp in st_tri:
                        srow = sig.loc[stp.review]
                        wk.append({"review": stp.review.date(), "entry_session": cal[stp.entry_i].date(),
                                   "N100": srow[V.N100], "MC100": srow["MC100"], "SC100": srow[V.SC100],
                                   "all_three_buy": all(srow[k] == "BUY" for k in KEYS),
                                   "gold_signal": gold_at(gs, stp.review),
                                   "gold_signal_goldbees": gold_at(gs_gb, stp.review) if gs_gb is not None else np.nan,
                                   "decision": "EQUITY" if stp.sleeve == 0 else "SLEEVE",
                                   "equity_w": 1.0 - stp.sleeve,
                                   "gold_w": stp.sleeve * w_map[stp.review], "cash_w": stp.sleeve * (1 - w_map[stp.review]),
                                   "variant_gold_w": stp.sleeve * e_map[stp.review],
                                   "variant_cash_w": stp.sleeve * (1 - e_map[stp.review])})
                    weekly_rows = pd.DataFrame(wk)
            # parent daily NAV, at the close and at the fill, for the check model
            if name.startswith("parent"):
                daily.setdefault("_parent", {})[aa] = full
                daily.setdefault("_parent_fill", {})[aa] = parent_fill_nav(sim, pos, log)
    return res, curves, trades, positions, weekly_rows, daily


def main():
    inp = load_inputs()
    cal, eff, rv, start = inp["cal"], inp["eff"].copy(), inp["reviews"], inp["start"]
    # the 2014-21 review grid (SC100 Master dates), needed before the gold signal
    n100, mc100, sc100 = master("Nifty100"), master("MC100"), master("SC100")
    grid = sc100.index[(sc100.index >= OOS_START) & (sc100.index <= OOS_END)]
    al = lambda x: x.reindex(grid.union(x.index)).ffill(limit=1).reindex(grid)
    sig2 = pd.DataFrame({V.N100: al(n100), V.MC150: al(mc100), V.SC250: al(sc100), V.MICRO: al(sc100),
                         V.SC100: al(sc100), "MC100": al(mc100)}, index=grid).dropna()
    rv2 = sig2.index
    reviews_all = pd.DatetimeIndex(sorted(set(rv) | set(rv2)))

    # gold signal: production ST.py on MAUc1 (Master_MAUc1.xlsx), read like the index signals
    m_d = mauc1_daily()
    t_gold, st_daily, st_dc = mauc1_st()
    assert t_gold.index.max() >= reviews_all.max(), "ST.py MAUc1 run ends before the last review"
    gs = t_gold["signal"].dropna()
    # the previous signal (GOLDBEES Friday-close candles), kept as a comparator
    t_gb, gold_daily = gold_weekly_table()
    gs_gb = t_gb["signal"].dropna()
    fillf = despiked_goldbees(gold_daily, m_d)

    # ── live window: the four AA books ──────────────────────────────────────
    # GOLDBEES marks at the Eikon close and fills at the de-spiked OHLC4 of the trade session; cash at its level.
    g_close, g_o4 = gold_prices(cal, gold_daily, fillf["fill_ohlc4_clean"])
    sleeve_live = inp["sleeve"].copy()
    sleeve_live[V.GOLD] = g_close
    fill_live = pd.DataFrame({V.GOLD: g_o4, V.CASH: sleeve_live[V.CASH]}, index=cal)
    sim = V.Simulator(inp["panel"], sleeve_live, close=inp["close"], sleeve_fill=fill_live)
    inp["sleeve"] = sleeve_live
    mcs = master("MC100")
    eff["MC100"] = mcs.reindex(eff.index.union(mcs.index)).ffill(limit=1).reindex(eff.index)
    ctx_is, tag_is = {}, {}
    for aa, p in PAIRS.items():
        ctx_is[aa] = V.parent_ctx(p, inp["hold"][inp["hold"]["parent"] == p], rv, cal)
        tag_is[aa] = V.tag_table(ctx_is[aa], inp["taggers"]["hybrid"])
    r1 = run_period("live 2021-11 -> 2026-08", sim, cal, rv, eff, ctx_is, tag_is, gs, start, IS_END, inp["sleeve"], gs_gb)
    print("live window done", flush=True)

    # ── before the books: the four parents' real baskets ────────────────────
    cal_all = full_calendar()
    prior = cal_all[cal_all < OOS_START]
    cal2 = cal_all[(cal_all >= prior[-1]) & (cal_all <= OOS_END)]
    hist = {p: D.parent_history(p) for p in PAIRS.values()}
    for h in hist.values():
        h["key"] = h["isin"].where(h["isin"] != "", h["ticker"])
    isins = sorted({i for h in hist.values() for i in h[h["eff_date"] <= OOS_END]["isin"] if i})
    px = eikon_by_isin(isins, OOS_START - pd.Timedelta(days=40), OOS_END + pd.Timedelta(days=10), "eikon_ohlcv_2014_2021.parquet")
    gc2 = gold_cash(cal2)
    g2_close, g2_o4 = gold_prices(cal2, gold_daily, fillf["fill_ohlc4_clean"])
    sleeve2 = pd.DataFrame({V.GOLD: g2_close, V.CASH: gc2["cash"]}, index=cal2).ffill()
    fill2 = pd.DataFrame({V.GOLD: g2_o4, V.CASH: sleeve2[V.CASH]}, index=cal2)
    close = px.pivot(index="date", columns="ticker", values="close").reindex(cal2)
    sim2 = V.Simulator(Panel(px.drop(columns=["ric"]), cal2), sleeve2, close=close, sleeve_fill=fill2)
    tagger = V.HybridTagger(old_ranks(), None, D.load_overrides())
    ctx_o, tag_o = {}, {}
    for aa, p in PAIRS.items():
        h = hist[p]
        ctx_o[aa] = V.parent_ctx(p, h[h["eff_date"] <= OOS_END], rv2, cal2)
        tag_o[aa] = V.tag_table(ctx_o[aa], tagger)
    r2 = run_period("before the books 2014-07 -> 2021-10", sim2, cal2, rv2, sig2, ctx_o, tag_o, gs, cal2[0], OOS_END, sleeve2, gs_gb)
    print("2014-21 done", flush=True)

    # ── published NAVs for the live window and 2014-21 ──────────────────────
    par, aa_pub = load_index_levels(PARENT_INDEX_CSV), load_index_levels(AA_INDEX_CSV)
    pub_rows, pub_curves = [], {}
    for label, c_, a_, b_, sl in (("live 2021-11 -> 2026-08", cal, start, IS_END, inp["sleeve"]),
                                  ("before the books 2014-07 -> 2021-10", cal2, cal2[0], OOS_END, sleeve2)):
        for aa, p in PAIRS.items():
            for nm, ser in (("published parent NAV", par.get(p)), ("published AA NAV (as traded)", aa_pub.get(aa))):
                if ser is None:
                    continue
                s = ser.reindex(c_.union(ser.index)).ffill().reindex(c_).loc[a_:b_].dropna()
                if len(s) < 200 or s.index[0] > a_ + pd.Timedelta(days=10):
                    continue
                s = s / s.iloc[0]
                st_ = stats(s, sl[V.CASH])
                st_.update({"period": label, "aa": aa, "parent": p, "strategy": nm})
                pub_rows.append(st_)
                pub_curves[f"{label}|{aa}|{nm}"] = s

    res = pd.DataFrame(r1[0] + r2[0] + pub_rows)
    cols = ["period", "aa", "parent", "strategy", "start", "end", "cagr", "vol", "max_dd_daily", "max_dd_friday", "calmar",
            "sharpe_vs_cash", "total_return", "avg_equity_weight", "switches_equity_sleeve", "sleeve_resplits", "trades",
            "cost_paid_share_of_nav"]
    res = res[[c for c in cols if c in res]]
    res.to_csv(OUT / "summary_stats.csv", index=False)
    curves = {**r1[1], **r2[1], **pub_curves}
    C = pd.DataFrame(curves)
    C.to_csv(OUT / "nav_curves_daily.csv")
    yr = pd.DataFrame({k: yearly(v) for k, v in curves.items()}).T
    yr.index.name = "series"
    yr.to_csv(OUT / "yearly_returns.csv")
    pd.concat(r1[2] + r2[2]).to_csv(OUT / "trade_log.csv", index=False)
    pos = pd.concat(r1[3] + r2[3])
    # readable tickers / names for the stock keys
    names = {}
    for h in list(hist.values()) + [inp["hold"]]:
        for _, row in h.iterrows():
            k = row["isin"] if row.get("isin", "") else row["ticker"]
            names.setdefault(k, (row.get("ticker", ""), row.get("name", "") if "name" in row else ""))
    pos["ticker"] = pos.key.map(lambda k: names.get(k, (k, ""))[0] if k not in (V.GOLD, V.CASH) else k)
    pos["name"] = pos.key.map(lambda k: names.get(k, ("", ""))[1] if k not in (V.GOLD, V.CASH) else ("GOLDBEES" if k == V.GOLD else "LBES cash"))
    pos.to_csv(OUT / "position_log.csv", index=False)
    r1[4].to_csv(OUT / "weekly_signals_live.csv", index=False)
    r2[4].to_csv(OUT / "weekly_signals_2014_2021.csv", index=False)
    t_gold.to_csv(OUT / "gold_supertrend_weekly.csv")                     # MAUc1, production ST.py
    t_gb.to_csv(OUT / "gold_supertrend_weekly_goldbees.csv")                # previous signal, for comparison
    # the daily bars ST.py built its candles from (NSE days; a day with no MCX bar repeats the previous one)
    st_daily.assign(open=m_d["open"].reindex(st_daily.index), mcx_session=st_daily.index.isin(m_d.index))[
        ["open", "high", "low", "close", "candle_review", "mcx_session"]].to_csv(OUT / "gold_signal_daily_mauc1.csv")
    gold_daily[["open", "high", "low", "close"]].to_csv(OUT / "gold_daily_ohlc_eikon.csv")
    fillf.to_csv(OUT / "goldbees_fill_despiked.csv")
    for label, rr, sl in (("live", r1, inp["sleeve"]), ("2014_2021", r2, sleeve2)):
        par_navs = rr[5].pop("_parent")
        par_fill = rr[5].pop("_parent_fill")
        for aa, dd in rr[5].items():
            dd["parent_harness_nav"] = par_navs[aa].reindex(dd.index)
            dd["parent_fill_nav"] = par_fill[aa].reindex(dd.index)
            dd.to_csv(OUT / f"daily_{aa}_{label}.csv")
    at = lambda s_: s_.reindex(reviews_all.union(s_.index)).ffill().reindex(reviews_all)
    cmp_ = pd.DataFrame({"mauc1": at(gs), "goldbees": at(gs_gb)}, index=reviews_all).dropna()
    cmp_.to_csv(OUT / "gold_signal_mauc1_vs_goldbees.csv")
    print("gold signal: MAUc1 vs GOLDBEES agree on", int((cmp_.mauc1 == cmp_.goldbees).sum()), "of", len(cmp_), "reviews")
    print("GOLDBEES fills changed by de-spiking:", int(fillf.changed.sum()), "of", len(fillf), "days")
    json.dump({"primary_bps": V.PRIMARY_BPS, "gold_signal": "MAUc1 weekly supertrend from production ST.py (Master_MAUc1.xlsx, mauc1_st_production.py)",
               "gold_weekly_candle": "ST.py: NSE trading days (TradingDays.xlsx) grouped by ISO week, forward-filled",
               "gold_st_run": f"Historical Data/FRA_MAUc1, dateCode {st_dc}",
               "gold_fill": "GOLDBEES trade-session OHLC4 after pulling O/H/L into close +/- (MCX range + 0.5%)",
               "despike_tol": DESPIKE_TOL, "stock_fill": "entry-session OHLC4, close fallback", "gold_buy_share": G_BUY, "gold_sell_share": G_SELL,
               "gold_signal_missing_share": G_NONE, "live_start": str(start.date()), "live_end": str(IS_END.date()),
               "oos_start": str(cal2[0].date()), "oos_end": str(OOS_END.date())}, open(OUT / "run_config.json", "w"), indent=1)

    pd.set_option("display.width", 250); pd.set_option("display.max_columns", 30)
    show = res[["period", "aa", "strategy", "cagr", "max_dd_daily", "max_dd_friday", "calmar", "avg_equity_weight", "switches_equity_sleeve", "sleeve_resplits"]]
    print(show.round(4).to_string(index=False))


if __name__ == "__main__":
    main()
