"""Extend the cash-leg level files with LIQUIDCASE returns from Postgres.

    python data/extend_liquid.py            # writes both extended files, prints a summary
    python data/extend_liquid.py --check    # prints the summary only, writes nothing

Rule (user-specified, F-AA-D13):  level[t] = level[t-1] * (1 + r[t]),
r[t] = LIQUIDCASE close[t] / close[t-1] - 1, on NSE sessions, for every session after
the input file's last row. Rows already in the input are copied verbatim. The originals
are never edited; each run writes a new file named after the last session added.

Inputs  (read-only):
    Historical Data/LBES_Adjusted_Price_data_2026_08_10.csv   cols date (dd/mm/yy HH:MM), price
    <LIQUID_ETF_FINAL>  (desk's liquidEtfFinal.csv, supertrend-research copy)  cols date (dd-mm-YYYY), liquid_case
    Postgres merged_historical_data_with_rics, ticker = 'LIQUIDCASE'  (needs wm-aiReports/.env)
Outputs:
    Historical Data/LBES_Adjusted_Price_data_extended_<last session>.csv
    Historical Data/liquidEtfFinal_extended_<last session>.csv

Caveat: LIQUIDCASE is a different fund from LIQUIDBEES. Over 2024-01-24 -> 2026-08-07 it
compounded 5.72% a year against LBES's 5.17% (see CLAUDE.md), so the extension runs
slightly rich.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import psycopg2

AA = Path(__file__).resolve().parents[1]
HD = AA / "Historical Data"
ENV = AA.parents[1] / "wm-aiReports" / ".env"
LBES_IN = HD / "LBES_Adjusted_Price_data_2026_08_10.csv"
LIQUID_ETF_FINAL = (AA.parents[1] / "wm-supertrend-research" / "studies" / "e-equity-rotation"
                    / "data" / "liquidEtfFinal.csv")


def liquidcase_closes() -> pd.Series:
    env = {}
    for line in ENV.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.strip().split("=", 1)
            env[k] = v.strip("\"'")
    c = psycopg2.connect(host=env["PG_PRICE_HOST"], port=env["PG_PRICE_PORT"], dbname=env["PG_PRICE_DBNAME"],
                         user=env["PG_PRICE_USER"], password=env["PG_PRICE_PASSWORD"], connect_timeout=20)
    c.set_session(readonly=True)
    cur = c.cursor()
    cur.execute("select date, close from merged_historical_data_with_rics "
                "where ticker='LIQUIDCASE' and close is not null order by date")
    s = pd.Series({pd.Timestamp(d): float(x) for d, x in cur.fetchall()}).sort_index()
    c.close()
    assert s.index.is_unique and (s > 0).all()
    return s


def chain(last_date: pd.Timestamp, last_level: float, close: pd.Series) -> pd.Series:
    """level[t] = level[t-1] * (1 + r[t]) for every NSE session after last_date."""
    r = close.pct_change()
    r = r[r.index > last_date].dropna()
    if r.empty:
        return pd.Series(dtype=float)
    first = r.index[0]
    prev_session = close.index[close.index.get_loc(first) - 1]
    # the first return must start at a session close the file already covers or precedes
    assert prev_session <= last_date, f"gap: no LIQUIDCASE close between {last_date.date()} and {first.date()}"
    return last_level * (1 + r).cumprod()


def main(check_only: bool) -> int:
    close = liquidcase_closes()
    print(f"LIQUIDCASE in DB: {close.index[0].date()} -> {close.index[-1].date()}, {len(close)} closes")
    summary = []

    # --- LBES (wm-AA) -------------------------------------------------------------
    lb = pd.read_csv(LBES_IN)
    lb["d"] = pd.to_datetime(lb["date"], format="%d/%m/%y %H:%M")
    new = chain(lb["d"].iloc[-1], float(lb["price"].iloc[-1]), close)
    add = pd.DataFrame({"date": new.index.strftime("%d/%m/%y 00:00"), "price": new.round(8).values})
    out = pd.concat([lb[["date", "price"]], add], ignore_index=True)
    summary.append(("LBES", lb["d"].iloc[-1], float(lb["price"].iloc[-1]), new, HD /
                    f"LBES_Adjusted_Price_data_extended_{new.index[-1].date()}.csv" if len(new) else None, out))

    # --- liquidEtfFinal (desk file) -------------------------------------------------
    lf = pd.read_csv(LIQUID_ETF_FINAL)
    lf["d"] = pd.to_datetime(lf["date"], format="%d-%m-%Y")
    new2 = chain(lf["d"].iloc[-1], float(lf["liquid_case"].iloc[-1]), close)
    add2 = pd.DataFrame({"date": new2.index.strftime("%d-%m-%Y"), "liquid_case": new2.round(8).values})
    out2 = pd.concat([lf[["date", "liquid_case"]], add2], ignore_index=True)
    summary.append(("liquidEtfFinal", lf["d"].iloc[-1], float(lf["liquid_case"].iloc[-1]), new2, HD /
                    f"liquidEtfFinal_extended_{new2.index[-1].date()}.csv" if len(new2) else None, out2))

    for name, last_d, last_v, new_s, path, frame in summary:
        if new_s.empty:
            print(f"{name}: already up to date at {last_d.date()}")
            continue
        days = (new_s.index[-1] - last_d).days
        ann = (new_s.iloc[-1] / last_v) ** (365 / days) - 1
        print(f"{name}: last row {last_d.date()} = {last_v:.4f}; +{len(new_s)} sessions to "
              f"{new_s.index[-1].date()} = {new_s.iloc[-1]:.4f} ({new_s.iloc[-1] / last_v - 1:+.4%}, {ann:.2%} p.a. over {days} days)")
        if not check_only:
            frame.to_csv(path, index=False)
            print(f"   wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main("--check" in sys.argv))
