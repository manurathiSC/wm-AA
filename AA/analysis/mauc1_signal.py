# -*- coding: utf-8 -*-
"""
Gold's weekly supertrend on MAUc1 (MCX gold futures, continuous first month,
Rs per 10 g), read at each Friday review, and compared with the GOLDBEES
signal used so far.

Input: C:/Users/manur/Downloads/MAUc1_daily1.csv (Eikon export, daily OHLC).
Cleaning (every change logged in mauc1_cleaning_log.csv):
  - rows with no close (stale holiday copies 2015-10-02, 2015-11-11,
    2020-04-14) are dropped;
  - close-only rows (2021-10-04, 2025-01-02, 2026-02-04) keep the close, with
    open/high/low set to it;
  - a bar whose close lies outside its high/low (2023-10-16) is widened to
    span open, high, low and close.
The weekly supertrend is the desk's production ST.py, run unmodified on this
data by mauc1_st_production.py (Historical Data/FRA_MAUc1, Master_MAUc1.xlsx):
NSE-calendar ISO-week candles, multiplier 2, 5-bar linearly weighted ATR, read
through final_strategy.mauc1_st(). The trade is the review's next session.
(Until 2026-09-29 this file built candles cut at each review with
final_strategy.review_weekly; mauc1_st_compare.py shows the two agree on all
603 weeks.)

Writes evidence/final_strategy/mauc1/.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from common import EVIDENCE_DIR
from final_strategy import mauc1_st

SRC = r"C:\Users\manur\Downloads\MAUc1_daily1.csv"
E = EVIDENCE_DIR / "final_strategy"
OUT = E / "mauc1"
OUT.mkdir(parents=True, exist_ok=True)


def load_clean():
    d = pd.read_csv(SRC, parse_dates=["Date"]).rename(columns=str.lower).rename(columns={"date": "date"})
    log = []
    for r in d[d.close.isna()].itertuples():
        log.append({"date": r.date.date(), "action": "dropped: no close", "open": r.open, "high": r.high, "low": r.low, "close": r.close})
    d = d[d.close.notna()].copy()
    m = d[["open", "high", "low"]].isna().any(axis=1)
    for r in d[m].itertuples():
        log.append({"date": r.date.date(), "action": "close only: open/high/low set to close", "open": r.open, "high": r.high, "low": r.low, "close": r.close})
    for c in ("open", "high", "low"):
        d[c] = d[c].fillna(d.close)
    bad = (d.high < d[["open", "close"]].max(axis=1)) | (d.low > d[["open", "close"]].min(axis=1))
    for r in d[bad].itertuples():
        log.append({"date": r.date.date(), "action": "bar widened to span open/high/low/close", "open": r.open, "high": r.high, "low": r.low, "close": r.close})
    d["high"] = d[["open", "high", "low", "close"]].max(axis=1)
    d["low"] = d[["open", "high", "low", "close"]].min(axis=1)
    d = d.set_index("date").sort_index()
    d["volume"] = d["volume"].fillna(0.0)
    pd.DataFrame(log).to_csv(OUT / "mauc1_cleaning_log.csv", index=False)
    d.to_csv(OUT / "mauc1_daily_clean.csv")
    return d, pd.DataFrame(log)


def main():
    d, log = load_clean()
    # the review grid and trade sessions used by the final-strategy runs
    rv = pd.concat([pd.read_csv(E / f, parse_dates=["review", "entry_session"]) for f in
                    ("weekly_signals_2014_2021.csv", "weekly_signals_live.csv")], ignore_index=True)
    rv = rv.drop_duplicates("review").sort_values("review")
    t, _, dc = mauc1_st()                       # production ST.py on MAUc1
    w = t
    t.to_csv(OUT / "mauc1_supertrend_weekly.csv")
    sig = t["signal"].dropna()
    rv = rv[rv.review >= sig.index[0]]
    at = lambda s, r: (s[s.index <= r].iloc[-1] if (s.index <= r).any() else np.nan)
    gb = pd.read_csv(E / "gold_supertrend_weekly_goldbees.csv", parse_dates=["week_end"]).set_index("week_end")["signal"].dropna()
    rows = []
    for r in rv.itertuples():
        rows.append({"review": r.review.date(), "trade_session": r.entry_session.date(),
                     "mauc1_signal": at(sig, r.review), "goldbees_signal": at(gb, r.review),
                     "mauc1_week_used": sig.index[sig.index <= r.review][-1].date()})
    R = pd.DataFrame(rows)
    R["agree"] = R.mauc1_signal == R.goldbees_signal
    R.to_csv(OUT / "mauc1_signal_on_reviews.csv", index=False)

    # disagreement stretches
    R["blk"] = (R.agree != R.agree.shift()).cumsum()
    dis = (R[~R.agree].groupby("blk").agg(first_review=("review", "first"), last_review=("review", "last"), weeks=("review", "size"),
                                         mauc1=("mauc1_signal", "first"), goldbees=("goldbees_signal", "first")).reset_index(drop=True))
    dis.to_csv(OUT / "mauc1_vs_goldbees_disagreements.csv", index=False)

    summ = {"daily rows used": len(d), "first date": str(d.index[0].date()), "last date": str(d.index[-1].date()),
            "weekly candles (ST.py, NSE weeks)": len(w), "ST.py run (dateCode)": dc, "first signal week": str(sig.index[0].date()),
            "reviews compared": len(R), "share of reviews BUY (MAUc1)": float(R.mauc1_signal.mean()),
            "share of reviews BUY (GOLDBEES)": float(R.goldbees_signal.mean()),
            "flips (MAUc1)": int((R.mauc1_signal.diff().abs() > 0).sum()), "flips (GOLDBEES)": int((R.goldbees_signal.diff().abs() > 0).sum()),
            "reviews where they agree": int(R.agree.sum()), "agreement share": float(R.agree.mean()),
            "disagreement stretches": len(dis)}
    pd.Series(summ).to_csv(OUT / "mauc1_summary.csv", header=["value"])
    print(pd.Series(summ).to_string())
    print(dis.to_string(index=False))
    print(log.to_string(index=False))


if __name__ == "__main__":
    main()
