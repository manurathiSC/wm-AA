"""Extend the GOLDBEES Eikon OHLC file (D09) with the sessions Postgres has after its last row.

    python data/extend_goldbees.py            # writes the extended file, prints a summary
    python data/extend_goldbees.py --check    # prints the summary only, writes nothing

Same manner as extend_liquid.py (F-AA-D13): rows already in the input are copied verbatim,
the original is never edited, and each run writes a new file named after the last session
added. Rows are appended as stored, with no transformation (no de-spiking, no rescaling).

Source is the SAME table as D09, so the series stays consistent with the file it extends:
    Postgres windmill.public.ohlcv_eikon WHERE quote_id = 55837402194 (RIC GBES.NS)
    split adjusted, price return. NOT the Kite table merged_historical_data_with_rics
    (unadjusted; it sits 0.0-0.2 off Eikon's close, e.g. 123.47 vs 123.43 on 2026-09-24).
Input  (read-only):  analysis/cache/why_gold_ohlc_eikon.parquet   cols date, open, high, low, close
Output:              analysis/cache/why_gold_ohlc_eikon_extended_<last session>.parquet
Credentials:         wm-aiReports/.env  (PG_PRICE_*, read-only session)

Guard: the Eikon table is re-adjusted for corporate actions from time to time (the DB holds
*_bkp_ca_<date> backup tables). If history has been restated, appending would splice two
adjustment bases, so the run stops when any close in the overlap differs by more than 1e-6.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import psycopg2

AA = Path(__file__).resolve().parents[1]
CACHE = AA / "analysis" / "cache"
ENV = AA.parents[1] / "wm-aiReports" / ".env"
SRC = CACHE / "why_gold_ohlc_eikon.parquet"
QUOTE_ID = 55837402194  # GBES.NS
COLS = ["date", "open", "high", "low", "close"]


def db_rows() -> pd.DataFrame:
    env = {}
    for line in ENV.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.strip().split("=", 1)
            env[k] = v.strip("\"'")
    c = psycopg2.connect(host=env["PG_PRICE_HOST"], port=env["PG_PRICE_PORT"], dbname=env["PG_PRICE_DBNAME"],
                         user=env["PG_PRICE_USER"], password=env["PG_PRICE_PASSWORD"], connect_timeout=20)
    c.set_session(readonly=True)
    cur = c.cursor()
    cur.execute("select date, open, high, low, close from ohlcv_eikon where quote_id = %s order by date",
                (QUOTE_ID,))
    df = pd.DataFrame(cur.fetchall(), columns=COLS)
    c.close()
    df["date"] = pd.to_datetime(df["date"])
    for k in COLS[1:]:
        df[k] = pd.to_numeric(df[k], errors="coerce").astype(float)
    return df


def main(check_only: bool) -> int:
    old = pd.read_parquet(SRC)[COLS]
    db = db_rows()
    last = old["date"].max()
    print(f"file: {old['date'].min().date()} -> {last.date()}, {len(old)} rows")
    print(f"DB  : {db['date'].min().date()} -> {db['date'].max().date()}, {len(db)} rows")

    both = old.merge(db, on="date", suffixes=("_f", "_db"))
    drift = (both["close_f"] - both["close_db"]).abs().max()
    print(f"overlap: {len(both)} dates, max |close diff| = {drift:.2e}")
    assert drift <= 1e-6, "Eikon history has been restated; do not splice (see docstring)"
    odd = both[((both["open_f"] - both["open_db"]).abs() > 1e-6) | ((both["low_f"] - both["low_db"]).abs() > 1e-6)
               | ((both["high_f"] - both["high_db"]).abs() > 1e-6)]
    if len(odd):
        print(f"note: open/high/low differ on {len(odd)} overlapping date(s): {[d.date().isoformat() for d in odd['date']]}")
    print(f"note: in file, not in DB: {[d.date().isoformat() for d in sorted(set(old['date']) - set(db['date']))]}")

    new = db[db["date"] > last].dropna(subset=["close"])
    if new.empty:
        print(f"already up to date at {last.date()}")
        return 0
    assert new["date"].is_unique and (new[COLS[1:]] > 0).all().all()
    out = pd.concat([old, new], ignore_index=True)
    path = CACHE / f"why_gold_ohlc_eikon_extended_{new['date'].iloc[-1].date()}.parquet"
    print(f"+{len(new)} sessions {new['date'].iloc[0].date()} -> {new['date'].iloc[-1].date()}; "
          f"close {old['close'].iloc[-1]:.2f} -> {new['close'].iloc[-1]:.2f}")
    if not check_only:
        out.to_parquet(path, index=False)
        print(f"wrote {path} ({len(out)} rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main("--check" in sys.argv))
