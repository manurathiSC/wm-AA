"""
Check the MAUc1 signal from production ST.py (mauc1_st_production.py) against the
signal the final-strategy backtest used (final_strategy.review_weekly + supertrend.py).

1. Port check: supertrend.supertrend run on ST.py's own weekly candles must give
   ST.py's ST / FUB / FLB and SIGN.
2. Signal check: ST.py SIGN vs the backtest's MAUc1 signal on every review the
   backtest read, and on every week to 2026-09-25.
3. Where they differ, why: the candles. ST.py puts MAUc1 on the NSE trading
   calendar (TradingDays.xlsx) and forward-fills, so MCX sessions on NSE holidays
   drop out and NSE days without an MCX bar repeat the previous bar.

Outputs: evidence/final_strategy/mauc1/st_production/
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from common import EVIDENCE_DIR
from final_strategy import MAUC1_CSV, mauc1_daily, review_weekly
from mauc1_st_production import ANALYSIS, DATA, FINAL, FOLDER, PROD
from supertrend import supertrend

FS = EVIDENCE_DIR / "final_strategy"
OUT = FS / "mauc1" / "st_production"
OUT.mkdir(parents=True, exist_ok=True)
DC = "250926"


def st_weekly() -> pd.DataFrame:
    w = pd.read_excel(FINAL / FOLDER / f"weekIndexDf_{DC}_W.xlsx", index_col=0)
    w.index = pd.to_datetime(w.index)
    return w


def st_master() -> pd.DataFrame:
    m = pd.read_excel(ANALYSIS / f"Master_{FOLDER}.xlsx")
    m["Date"] = pd.to_datetime(m["Date"])
    return m.set_index("Date")


PREV = FS / "previous_review_cut_signal"     # backtest outputs from before the switch to ST.py


def backtest_signal() -> pd.DataFrame:
    """
    The previous MAUc1 signal, rebuilt from scratch: supertrend.py on candles cut at
    each review (final_strategy.review_weekly), reviews = the production SC100 Master
    dates, as the backtest and mauc1_latest.py used before the switch.
    """
    g = pd.read_excel(PROD / "RSI" / "Final" / "Analysis" / "Master_SC100.xlsx")
    rv = pd.DatetimeIndex(pd.to_datetime(g["Date"]).drop_duplicates().sort_values())
    m = mauc1_daily()
    rv = rv[(rv >= pd.Timestamp("2015-02-01")) & (rv <= m.index.max())]
    w = review_weekly(m, rv)
    return pd.concat([w[["high", "low", "close", "sessions"]], supertrend(w)[["ST", "signal"]]], axis=1)


def main():
    w, m = st_weekly(), st_master()
    # 1. port on ST.py's candles
    cand = w.rename(columns={"High": "high", "Low": "low", "Close": "close"})[
        ["high", "low", "close", "PClose", "HML", "HMC", "LMC", "TR", "AHML"]]
    port = supertrend(cand)
    j = m.index.intersection(port.dropna(subset=["ST"]).index)
    # ST.py starts its ratchet one week later (rebalStartIndex = 5 -> 6th candle); compare once both have converged
    same_state = pd.Series(np.isclose(port.loc[j, "FUB"], m.loc[j, "FUB"]) & np.isclose(port.loc[j, "FLB"], m.loc[j, "FLB"])
                  & np.isclose(port.loc[j, "ST"], m.loc[j, "ST"]), index=j)
    conv = j[same_state.values.argmax()] if same_state.any() else None
    jj = j[j >= conv] if conv is not None else j[:0]
    port_sign = np.where(port.loc[j, "signal"] == 1, "BUY", "SELL")
    port_chk = pd.DataFrame({"st_py_ST": m.loc[j, "ST"], "port_ST": port.loc[j, "ST"],
                             "st_py_SIGN": m.loc[j, "SIGN"], "port_SIGN": port_sign}, index=j)
    port_chk["abs_diff_ST"] = (port_chk["st_py_ST"] - port_chk["port_ST"]).abs()
    port_chk.index.name = "week"
    port_chk.to_csv(OUT / "port_check.csv")

    # 2. signal comparison, week by week
    bt = backtest_signal()
    sig = pd.DataFrame({"week": m.index, "st_py_SIGN": m["SIGN"].values, "st_py_ST": m["ST"].values,
                        "st_py_Index": m["Index"].values}).set_index("week")
    sig = sig.join(w[["High", "Low", "Close"]].rename(columns=lambda c: f"st_py_{c.lower()}"))
    sig = sig.join(bt.rename(columns=lambda c: f"backtest_{c}"), how="left")
    sig["backtest_SIGN"] = sig["backtest_signal"].map({1.0: "BUY", 0.0: "SELL"})
    sig["agree"] = sig["st_py_SIGN"] == sig["backtest_SIGN"]

    # 3. candle composition: NSE calendar vs MCX sessions
    mcx = pd.read_csv(MAUC1_CSV, index_col=0, parse_dates=True)
    td = pd.to_datetime(pd.read_excel(DATA / "TradingDays.xlsx", header=None, skiprows=3)[1])
    lo, hi = mcx.index.min(), td.max()
    nse = pd.DatetimeIndex(td[(td >= lo) & (td <= hi)])
    mcx_w = mcx.index[(mcx.index >= lo) & (mcx.index <= hi)]
    dropped = mcx_w.difference(nse)                 # MCX session on an NSE holiday / weekend
    filled = nse.difference(mcx_w)                  # NSE day, no MCX bar -> ST.py repeats the previous bar
    wk_of = lambda d: sig.index[np.searchsorted(sig.index.values, d.values, side="left").clip(max=len(sig) - 1)]
    cal = pd.concat([pd.DataFrame({"date": dropped, "kind": "MCX session on an NSE holiday (dropped by ST.py)"}),
                     pd.DataFrame({"date": filled, "kind": "NSE day with no MCX bar (ST.py repeats the previous bar)"})])
    cal = cal.sort_values("date").reset_index(drop=True)
    cal["week"] = wk_of(pd.DatetimeIndex(cal["date"]))
    cal["weekday"] = pd.DatetimeIndex(cal["date"]).day_name()
    cal.to_csv(OUT / "calendar_differences.csv", index=False)
    per_wk = cal.groupby(["week", "kind"]).size().unstack(fill_value=0)
    per_wk.columns = ["n_dropped" if "dropped" in c else "n_filled" for c in per_wk.columns]
    sig = sig.join(per_wk).fillna({"n_dropped": 0, "n_filled": 0})
    for c in ("high", "low", "close"):
        sig[f"candle_diff_{c}"] = sig[f"st_py_{c}"] - sig[f"backtest_{c}"]
    sig["candle_same"] = sig[[f"candle_diff_{c}" for c in ("high", "low", "close")]].abs().max(axis=1) < 1e-9
    sig.to_csv(OUT / "signal_compare_weekly.csv")

    # the reviews the backtest actually read, as it read them before the switch
    reads = []
    for f, per in (("weekly_signals_live.csv", "live 2021-26"), ("weekly_signals_2014_2021.csv", "2014-21")):
        s = pd.read_csv(PREV / f, parse_dates=["review"])
        s = s.drop_duplicates("review")[["review", "gold_signal"]].dropna()
        s["period"] = per
        reads.append(s)
    reads = pd.concat(reads).set_index("review").sort_index()
    reads = reads.join(sig[["st_py_SIGN", "st_py_ST", "backtest_ST"]])
    reads["backtest_SIGN"] = reads["gold_signal"].map({1.0: "BUY", 0.0: "SELL"})
    reads["agree"] = reads["st_py_SIGN"] == reads["backtest_SIGN"]
    reads.to_csv(OUT / "signal_compare_backtest_reviews.csv")
    dis = sig[sig["backtest_SIGN"].notna() & ~sig["agree"]]
    dis.to_csv(OUT / "disagreements.csv")

    both = sig.dropna(subset=["backtest_SIGN"])
    summ = {
        "st_py_weeks": int(len(m)), "st_py_first": str(m.index.min().date()), "st_py_last": str(m.index.max().date()),
        "port_check": {"weeks": int(len(j)), "converged_from": str(conv.date()) if conv is not None else None,
                       "weeks_after_convergence": int(len(jj)),
                       "max_abs_diff_ST_after": float(port_chk.loc[jj, "abs_diff_ST"].max()) if len(jj) else None,
                       "sign_mismatch_after": int((port_chk.loc[jj, "st_py_SIGN"] != port_chk.loc[jj, "port_SIGN"]).sum()),
                       "sign_mismatch_before": int((port_chk.loc[j[j < conv], "st_py_SIGN"] != port_chk.loc[j[j < conv], "port_SIGN"]).sum()) if conv is not None else None},
        "weekly": {"weeks_compared": int(len(both)), "agree": int(both["agree"].sum()),
                   "candles_identical": int(both["candle_same"].sum())},
        "backtest_reviews": {p: {"reviews": int(len(g)), "agree": int(g["agree"].sum())} for p, g in reads.groupby("period")},
        "calendar": {"mcx_sessions_dropped": int(len(dropped)), "nse_days_filled": int(len(filled)),
                     "window": [str(lo.date()), str(hi.date())]},
        "disagreeing_weeks": [str(d.date()) for d in dis.index],
        "latest": {"week": str(m.index.max().date()), "SIGN": m["SIGN"].iloc[-1], "ST": float(m["ST"].iloc[-1]),
                   "close": float(m["Index"].iloc[-1])},
    }
    (OUT / "summary.json").write_text(json.dumps(summ, indent=2))
    print(json.dumps(summ, indent=1))
    if len(dis):
        print(dis[["st_py_SIGN", "backtest_SIGN", "st_py_ST", "backtest_ST", "st_py_high", "backtest_high",
                   "st_py_low", "backtest_low", "st_py_close", "backtest_close", "n_dropped", "n_filled"]].to_string())


if __name__ == "__main__":
    main()
