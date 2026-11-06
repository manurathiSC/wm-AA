# -*- coding: utf-8 -*-
"""
Why does timing gold with its own supertrend not pay?

`gold_sleeve_test.py` found that switching the sleeve between gold (gold
supertrend BUY) and cash (SELL) loses to a fixed sleeve holding the same
average gold share: -2.1 to -3.2 pp/yr in 2021-26, -0.1 to -1.0 pp/yr in
2014-18, a gain only in 2019-21. This script asks why, in six parts. Smallcap
100 is run alongside as the contrast case, since the same supertrend does add
value there.

  1. The signal on gold alone (gold vs cash), against buy-and-hold and
     against an exposure-matched static mix (constant gold weight equal to the
     signal's average). Timing value = timed CAGR - static CAGR.
  2. Return earned while the signal is BUY vs while it is SELL (annualised),
     and forward 4w / 13w returns by state.
  3. Episode anatomy: whipsaws, entry lag (rise from the prior low before the
     signal buys) and exit give-back (fall from the peak before it sells).
  4. Market structure: weekly autocorrelation, variance ratios, drawdowns.
     Trend rules earn when returns persist and drawdowns are deep.
  5. Is it the parameters? A grid of supertrend settings plus moving-average
     and momentum rules, all on gold alone.
  6. Inside the sleeve: gold's return while the equity rule is defensive,
     split by the gold signal's state.

Every signal is read on the Friday review grid (the production Master
dates), so a decision takes effect from the second session after the review.

Period: 2014-08 -> 2026-08 (Eikon GOLDBEES starts 2014-07-01; the signal
needs 5 weekly bars). Costs 20.8 bps per full switch. Price return for gold
and the index (no dividends); LBES total return for cash.

Writes `evidence/why_n100sc100/gold_why_*.csv`.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from common import CACHE_DIR
from supertrend import supertrend, to_weekly
from why_n100sc100 import (COST, OUT, calendar, cagr, daily_weight, gold_cash, index_closes,
                           mdd, run_rs, weekly_signs)

END = pd.Timestamp("2026-08-21")
PERIODS = [("2014-08 -> 2018-12", "2014-08-08", "2018-12-31"),
           ("2019-01 -> 2021-10", "2019-01-01", "2021-10-29"),
           ("2021-11 -> 2026-08", "2021-11-03", "2026-08-21"),
           ("2014-08 -> 2026-08", "2014-08-08", "2026-08-21")]


def gold_weekly() -> pd.DataFrame:
    g = pd.read_parquet(CACHE_DIR / "why_gold_ohlc_eikon.parquet")
    d = g.set_index("date").sort_index()
    d["volume"] = 0.0
    return to_weekly(d)


def index_weekly(sheet: str) -> pd.DataFrame:
    import segment_v2_data as D
    d = pd.read_excel(D.FROZEN_DIR / "Data" / "indices_ohlcv.xlsx", sheet_name=sheet)
    d["date"] = pd.to_datetime(d["date"])
    d = d.set_index("date").sort_index()
    d = d[~d.index.duplicated()][["open", "high", "low", "close"]].astype(float)
    d["volume"] = 0.0
    return to_weekly(d)


def signals(w: pd.DataFrame) -> dict[str, pd.Series]:
    """Candidate trend rules on weekly bars, each 1 (hold) / 0 (cash)."""
    out = {}
    for mul in (1.5, 2.0, 3.0, 4.0):
        for days in (5, 10, 20):
            out[f"supertrend x{mul:g}, {days} bars"] = supertrend(w, mul=mul, days=days)["signal"]
    c = w["close"]
    for n in (20, 40):
        sma = c.rolling(n).mean()
        out[f"close > {n}-week average"] = (c > sma).astype(float).where(sma.notna())
    for n in (13, 26, 52):
        m = c / c.shift(n) - 1
        out[f"{n}-week return > 0"] = (m > 0).astype(float).where(m.notna())
    return out


def on_reviews(sig: pd.Series, reviews: pd.DatetimeIndex) -> pd.Series:
    """
    A weekly-bar signal read at each Friday review: the latest bar whose last
    session is on or before the review. Weeks whose last session is a Saturday
    or Sunday special session (Budget day, muhurat) are acted on at the next
    review, as the index signals and the harness sleeve are.
    """
    s = sig.dropna()
    out = s.reindex(reviews.union(s.index)).ffill().reindex(reviews)
    return out[out.index >= s.index[0]]


def timing_row(name, sig, r_asset, r_cash, cal, label, a, b):
    """Timed vs buy-and-hold vs exposure-matched static, on one period."""
    c = cal[(cal >= pd.Timestamp(a)) & (cal <= pd.Timestamp(b))]
    nav = run_rs(sig, r_asset, r_cash, cal).reindex(c)
    nav = nav / nav.iloc[0]
    w = daily_weight(sig, cal).reindex(c).fillna(1.0)
    wbar = float(w.mean())
    r_st = (wbar * r_asset + (1 - wbar) * r_cash).reindex(c).fillna(0.0)
    r_st.iloc[0] = 0.0
    st = (1 + r_st).cumprod()
    bh = (1 + r_asset.reindex(c).fillna(0.0).where(lambda x: x.index != c[0], 0.0)).cumprod()
    s = sig.loc[a:b].dropna()
    return {"asset": name.split("|")[0], "rule": name.split("|")[1], "period": label,
            "avg_weight": wbar, "switches": int((s.diff().abs() > 0).sum()),
            "timed_cagr": cagr(nav), "static_cagr": cagr(st), "buy_hold_cagr": cagr(bh),
            "timing_value": cagr(nav) - cagr(st),
            "timed_max_dd": mdd(nav), "static_max_dd": mdd(st), "buy_hold_max_dd": mdd(bh)}


def state_returns(name, sig, px, cal, label, a, b):
    """Annualised return earned in each signal state, plus forward returns by state."""
    c = cal[(cal >= pd.Timestamp(a)) & (cal <= pd.Timestamp(b))]
    w = daily_weight(sig, cal).reindex(c)
    r = px.reindex(cal).pct_change().reindex(c)
    row = {"asset": name, "period": label}
    for st, lab in ((1.0, "buy"), (0.0, "sell")):
        m = (w == st) & r.notna()
        g = float(np.log1p(r[m]).sum())
        row[f"{lab}_days"] = int(m.sum())
        row[f"{lab}_ann_return"] = float(np.expm1(g * 252 / m.sum())) if m.sum() else np.nan
    # forward returns from each weekly decision's entry session
    s = sig.loc[a:b].dropna()
    p = px.reindex(cal)
    for k in (4, 13):
        fw = {1.0: [], 0.0: []}
        for r_, v in s.items():
            j = cal.searchsorted(r_, side="right")
            if j + 5 * k < len(cal) and cal[j + 5 * k] <= pd.Timestamp(b) + pd.Timedelta(days=100):
                fw[v].append(p.iloc[j + 5 * k] / p.iloc[j] - 1)
        for st, lab in ((1.0, "buy"), (0.0, "sell")):
            x = np.array([v for v in fw[st] if np.isfinite(v)])
            row[f"fwd{k}w_after_{lab}"] = float(x.mean()) if len(x) else np.nan
            row[f"fwd{k}w_rise_share_after_{lab}"] = float((x > 0).mean()) if len(x) else np.nan
            row[f"fwd{k}w_n_{lab}"] = int(len(x))
    return row


def episodes(name, sig, px, cal, a, b):
    """One row per signal episode: its return, the entry lag and the exit give-back."""
    s = sig.loc[a:b].dropna()
    sw = s[s.diff().fillna(1.0) != 0]
    p = px.reindex(cal).ffill()
    js = [cal.searchsorted(r_, side="right") for r_ in sw.index]
    rows = []
    for k in range(len(sw)):
        j0 = js[k]
        j1 = js[k + 1] if k + 1 < len(sw) else cal.searchsorted(pd.Timestamp(b), side="right")
        j1 = min(j1, len(cal) - 1)
        if j0 >= len(cal) or j1 <= j0:
            continue
        seg = p.iloc[j0:j1 + 1]
        prev = p.iloc[js[k - 1]:j0 + 1] if k > 0 else None
        state = "BUY" if sw.iloc[k] == 1.0 else "SELL"
        row = {"asset": name, "state": state, "signal_date": sw.index[k].date(), "start": cal[j0].date(),
               "end": cal[j1].date(), "weeks": round((j1 - j0) / 5, 1),
               "return": float(seg.iloc[-1] / seg.iloc[0] - 1), "complete": k + 1 < len(sw)}
        if state == "BUY":
            row["exit_give_back"] = float(seg.iloc[-1] / seg.max() - 1)
            row["peak_gain"] = float(seg.max() / seg.iloc[0] - 1)
            if prev is not None:
                row["entry_lag"] = float(seg.iloc[0] / prev.min() - 1)
        else:
            row["worst_fall_avoided"] = float(seg.min() / seg.iloc[0] - 1)
            if prev is not None:
                row["exit_from_peak"] = float(seg.iloc[0] / prev.max() - 1)
        rows.append(row)
    return rows


def structure(name, px, a, b):
    wk = px.loc[a:b].dropna().resample("W-FRI").last().dropna()
    r = np.log(wk).diff().dropna()
    row = {"asset": name, "weekly_vol": float(r.std()), "ann_vol": float(r.std() * np.sqrt(52)),
           "cagr": float(np.expm1(r.sum() * 52 / len(r)))}
    for L in (1, 2, 3, 4):
        row[f"autocorr_lag{L}"] = float(r.autocorr(L))
    for q in (4, 13, 26, 52):
        rq = np.log(wk).diff(q).dropna()
        row[f"variance_ratio_{q}w"] = float(rq.var() / (q * r.var()))
    nav = wk / wk.iloc[0]
    dd = nav / nav.cummax() - 1
    row["max_dd"] = float(dd.min())
    # count separate drawdowns that went deeper than 10% before a new high
    n10, inside, worst = 0, False, 0.0
    for v in dd:
        if v < 0:
            worst = min(worst, v)
            inside = True
        elif inside:
            n10 += worst <= -0.10
            inside, worst = False, 0.0
    n10 += inside and worst <= -0.10
    row["drawdowns_deeper_than_10pct"] = int(n10)
    row["weeks_under_water_share"] = float((dd < -0.0001).mean())
    return row


def main() -> None:
    cal_all = calendar()
    cal = cal_all[cal_all <= END]
    gc = gold_cash(cal)
    gold, cash = gc["gold"], gc["cash"]
    r_g, r_c = gold.pct_change(), cash.pct_change()
    idx = index_closes(cal)
    r_sc = idx["SC100"].pct_change()

    gw = gold_weekly()
    ws = weekly_signs()
    rv = ws.index
    gsig = on_reviews(supertrend(gw)["signal"], rv)
    scsig = ws["SC100"].dropna()
    eq_and = (ws["N100"] * ws["SC100"]).dropna()

    # ── 1 & 5: timing value, production rule plus the grid, gold alone ──────
    t_rows = []
    gold_rules = {k: on_reviews(v, rv) for k, v in signals(gw).items()}
    for rn, s in gold_rules.items():
        for lab, a, b in PERIODS:
            t_rows.append(timing_row(f"gold|{rn}", s, r_g, r_c, cal, lab, a, b))
    sc_w = index_weekly("SC100")
    for rn, s in {"production signal (Master file)": scsig,
                  "supertrend x2, 5 bars": on_reviews(supertrend(sc_w)["signal"], rv)}.items():
        for lab, a, b in PERIODS:
            t_rows.append(timing_row(f"SC100|{rn}", s, r_sc, r_c, cal, lab, a, b))
    tim = pd.DataFrame(t_rows)
    tim.to_csv(OUT / "gold_why_timing.csv", index=False)

    # ── 2: state returns ────────────────────────────────────────────────────
    s_rows = []
    for lab, a, b in PERIODS:
        s_rows.append(state_returns("gold", gsig, gold, cal, lab, a, b))
        s_rows.append(state_returns("SC100", scsig, idx["SC100"], cal, lab, a, b))
    st = pd.DataFrame(s_rows)
    st.to_csv(OUT / "gold_why_states.csv", index=False)

    # ── 3: episodes ─────────────────────────────────────────────────────────
    a0, b0 = "2014-08-08", "2026-08-21"
    ep = pd.DataFrame(episodes("gold", gsig, gold, cal, a0, b0) + episodes("SC100", scsig, idx["SC100"], cal, a0, b0))
    ep.to_csv(OUT / "gold_why_episodes.csv", index=False)
    e_sum = []
    for asset in ("gold", "SC100"):
        e = ep[(ep["asset"] == asset) & ep["complete"]]
        bu, se = e[e["state"] == "BUY"], e[e["state"] == "SELL"]
        e_sum.append({"asset": asset, "buy_episodes": len(bu), "sell_episodes": len(se),
                      "buy_median_weeks": float(bu["weeks"].median()),
                      "buy_short_le_8w": int((bu["weeks"] <= 8).sum()),
                      "buy_losing": int((bu["return"] < 0).sum()),
                      "buy_median_return": float(bu["return"].median()),
                      "median_entry_lag": float(bu["entry_lag"].median()),
                      "median_exit_give_back": float(bu["exit_give_back"].median()),
                      "median_peak_gain": float(bu["peak_gain"].median()),
                      "sell_rising": int((se["return"] > 0).sum()),
                      "sell_median_return": float(se["return"].median()),
                      "sell_median_worst_fall_avoided": float(se["worst_fall_avoided"].median()),
                      "sell_total_log_return": float(np.log1p(se["return"]).sum()),
                      "buy_total_log_return": float(np.log1p(bu["return"]).sum())})
    es = pd.DataFrame(e_sum)
    es.to_csv(OUT / "gold_why_episode_summary.csv", index=False)

    # ── 4: structure ────────────────────────────────────────────────────────
    stc = pd.DataFrame([structure("gold", gold, a0, b0), structure("SC100", idx["SC100"], a0, b0),
                        structure("N100", idx["N100"], a0, b0)])
    stc.to_csv(OUT / "gold_why_structure.csv", index=False)

    # ── 6: inside the sleeve ────────────────────────────────────────────────
    c = cal[(cal >= pd.Timestamp(a0)) & (cal <= END)]
    e_w = daily_weight(eq_and, cal).reindex(c)
    g_w = daily_weight(gsig, cal).reindex(c)
    rg = r_g.reindex(c)
    rc = r_c.reindex(c)
    i_rows = []
    for lab, a, b in PERIODS:
        m = (c >= pd.Timestamp(a)) & (c <= pd.Timestamp(b))
        for gs, glab in ((1.0, "gold BUY"), (0.0, "gold SELL")):
            mm = pd.Series(m, index=c) & (e_w == 0.0) & (g_w == gs) & rg.notna()
            n = int(mm.sum())
            i_rows.append({"period": lab, "equity_state": "defensive (N100 AND SC100 not both BUY)",
                           "gold_signal": glab, "days": n,
                           "gold_ann_return": float(np.expm1(np.log1p(rg[mm]).sum() * 252 / n)) if n else np.nan,
                           "cash_ann_return": float(np.expm1(np.log1p(rc[mm].fillna(0)).sum() * 252 / n)) if n else np.nan})
    ins = pd.DataFrame(i_rows)
    ins.to_csv(OUT / "gold_why_inside_sleeve.csv", index=False)

    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 40)
    print("\n1. production rule, gold alone vs SC100 (pp)")
    prod = tim[tim["rule"].isin(["supertrend x2, 5 bars", "production signal (Master file)"])]
    print((prod.set_index(["asset", "rule", "period"])[["avg_weight", "switches", "timed_cagr", "static_cagr", "buy_hold_cagr",
                                                        "timing_value", "timed_max_dd", "static_max_dd", "buy_hold_max_dd"]]
           .round(4)).to_string())
    print("\n2. state returns\n", st.round(4).T.to_string())
    print("\n3. episode summary\n", es.round(4).T.to_string())
    print("\n4. structure\n", stc.round(3).T.to_string())
    print("\n5. grid, gold, timing value (pp/yr)")
    g = tim[tim["asset"] == "gold"].pivot(index="rule", columns="period", values="timing_value") * 100
    print(g[[p[0] for p in PERIODS]].round(2).to_string())
    print("\n6. inside the sleeve\n", ins.round(4).to_string(index=False))
    print("\ngold episodes\n", ep[ep["asset"] == "gold"].round(3).to_string(index=False))


if __name__ == "__main__":
    main()
