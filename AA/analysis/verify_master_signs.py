# -*- coding: utf-8 -*-
"""
Are the pre-2021 SIGN values in the production Master files what the
supertrend formula gives on the index prices?

Recomputes the weekly supertrend (`supertrend.py`, the port of the desk's
ST.py: 5-bar linearly weighted ATR, multiplier 2) from the frozen
`indices_ohlcv.xlsx` and compares it week by week with each frozen
`Master_*.xlsx` SIGN column, before and after the AA books went live
(2021-11). Also checks that the Master file's weekly `Index` close equals the
weekly close built from the index file.

Writes `evidence/why_n100sc100/master_sign_check.csv` and
`master_sign_mismatches.csv`.
"""

from __future__ import annotations

import pandas as pd

import segment_v2_data as D
from supertrend import supertrend, to_weekly
from why_n100sc100 import OUT

SHEETS = ["NSEI", "Nifty100", "MC100", "SC100", "NiftyMidcap150", "NiftySmallcap250", "NiftyMicrocap250"]
LIVE = pd.Timestamp("2021-11-01")


def main() -> None:
    xl = D.FROZEN_DIR / "Data" / "indices_ohlcv.xlsx"
    rows, bad = [], []
    for sh in SHEETS:
        d = pd.read_excel(xl, sheet_name=sh)
        d["date"] = pd.to_datetime(d["date"])
        d = d.set_index("date").sort_index()
        d = d[~d.index.duplicated()][["open", "high", "low", "close"]].astype(float)
        d["volume"] = 0.0
        wk = to_weekly(d)
        ours = supertrend(wk)["signal"].dropna()
        m = pd.read_excel(D.MASTER_DIR / f"Master_{sh}.xlsx")
        m["Date"] = pd.to_datetime(m["Date"])
        m = m[~m["Date"].duplicated(keep="last")].set_index("Date")
        ms = m["SIGN"].dropna().map({"BUY": 1.0, "SELL": 0.0})
        j = pd.concat([ours.rename("recomputed"), ms.rename("master")], axis=1, join="inner").dropna()
        k = pd.concat([m["Index"].rename("m"), wk["close"].rename("o")], axis=1, join="inner").dropna()
        for lab, x in (("before 2021-11", j[j.index < LIVE]), ("2021-11 on", j[j.index >= LIVE])):
            rows.append({"index": sh, "span": lab, "weeks": len(x),
                         "first": x.index.min().date() if len(x) else None,
                         "last": x.index.max().date() if len(x) else None,
                         "sign_match_share": float((x["recomputed"] == x["master"]).mean()) if len(x) else None,
                         "mismatched_weeks": int((x["recomputed"] != x["master"]).sum())})
        rows[-1]["weekly_close_match_share"] = rows[-2]["weekly_close_match_share"] = \
            float(((k["m"] / k["o"] - 1).abs() < 1e-4).mean())
        mm = j[j["recomputed"] != j["master"]]
        bad += [{"index": sh, "week": i.date(), "recomputed": r["recomputed"], "master": r["master"]}
                for i, r in mm.iterrows()]
    res = pd.DataFrame(rows)
    res.to_csv(OUT / "master_sign_check.csv", index=False)
    pd.DataFrame(bad, columns=["index", "week", "recomputed", "master"]).to_csv(
        OUT / "master_sign_mismatches.csv", index=False)
    pd.set_option("display.width", 200)
    print(res.to_string(index=False))
    print(pd.DataFrame(bad).to_string(index=False))


if __name__ == "__main__":
    main()
