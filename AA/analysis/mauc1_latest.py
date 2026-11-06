# -*- coding: utf-8 -*-
"""
The final rule's latest weekly read-out. All four signals come from production
ST.py Master files: Nifty100 / MC100 / SC100 from the Friday job's
RSI/Final/Analysis, and MAUc1 from Historical Data/FRA_MAUc1/RSI/Final/Analysis
(the same ST.py run on MAUc1 by mauc1_st_production.py). Weeks: ST.py's week
labels, i.e. each week's last NSE session.
Writes evidence/final_strategy/mauc1/mauc1_signal_latest.csv (every supertrend
step) and final_rule_latest_decisions.csv.
"""
from pathlib import Path
import numpy as np
import pandas as pd
from common import EVIDENCE_DIR
from final_strategy import mauc1_st

PROD = Path(r"G:\.shortcut-targets-by-id\0B7f_UMMZHM_JNXljMVVXY2VPcHM\Investment Research_N\Shubham_Shreshtha\Friday Rebalance Automation\RSI\Final\Analysis")
M = EVIDENCE_DIR / "final_strategy" / "mauc1"


def sign(n):
    d = pd.read_excel(PROD / f"Master_{n}.xlsx"); d["Date"] = pd.to_datetime(d["Date"])
    return d.dropna(subset=["SIGN"]).drop_duplicates("Date", keep="last").set_index("Date").sort_index()["SIGN"]


def main():
    s = {"N100": sign("Nifty100"), "MC100": sign("MC100"), "SC100": sign("SC100")}
    t, _, dc = mauc1_st()
    t = t[["last_session", "sessions", "high", "low", "close", "PClose", "TR", "AHML", "wATR", "BUB", "BLB", "FUB", "FLB", "ST", "signal", "SIGN"]]
    t = t.rename(columns={"SIGN": "MAUc1_signal"})
    t.to_csv(M / "mauc1_signal_latest.csv")
    D = pd.DataFrame(s).reindex(t.index).ffill(limit=1)
    D["all_three_BUY"] = (D[["N100", "MC100", "SC100"]] == "BUY").all(axis=1)
    D["MAUc1_gold_signal"] = t["MAUc1_signal"]
    D["final_rule_holds"] = np.where(D.all_three_BUY, "100% parent basket",
                                     np.where(D.MAUc1_gold_signal == "BUY", "80% GOLDBEES / 20% cash",
                                              np.where(D.MAUc1_gold_signal == "SELL", "20% GOLDBEES / 80% cash", "50/50 (no gold signal yet)")))
    D["MAUc1_close"] = t["close"]; D["MAUc1_supertrend_line"] = t["ST"]
    D["MAUc1_gap_to_line"] = t["close"] / t["ST"] - 1
    D.index.name = "review"
    D.to_csv(M / "final_rule_latest_decisions.csv")
    print(D.tail(8).round(4).to_string())
    print("\nMAUc1 from ST.py run", dc, "| last week:", t.index.max().date(), "| index Masters last:", {k: str(v.index.max().date()) for k, v in s.items()})


if __name__ == "__main__":
    main()
