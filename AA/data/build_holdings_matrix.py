"""Holdings matrix for one parent smallcase: rows = rebalance dates, columns = stocks, 1 = held, 0 = not held.

    python data/build_holdings_matrix.py [SCMO_0003]

Input : Historical Data/frozen_2026-09-25/Rebalance_history/Rebalance_history_by_scid_<parent>.csv
Output: data/holdings_matrix/<parent>_holdings_matrix.csv   (the matrix)
        data/holdings_matrix/<parent>_columns.csv           (column -> ISIN, name, first/last held)

Rules
- Index = availableDate, the date the new basket takes effect (the file's `date` is the signal date, 2-5 days earlier).
- One column per ISIN (a stock). Column label = the file's ticker + ".NS". Where the file's ticker is blank
  (delisted names), the platform sid + ".NS" is used (DISH.NS, GEOM.NS, OSCM.NS).
- The file stamps each stock's current ticker on every historical row, so a ticker change does not split a column.
- Held = the stock is listed in the basket that takes effect that day (weight > 0). Weights are not kept here.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

AA = Path(__file__).resolve().parents[1]
SRC = AA / "Historical Data" / "frozen_2026-09-25" / "Rebalance_history"
OUT = AA / "data" / "holdings_matrix"


def build(parent: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    d = pd.read_csv(SRC / f"Rebalance_history_by_scid_{parent}.csv")
    d["rebalance_date"] = pd.to_datetime(d["availableDate"], format="%d/%m/%y %H:%M").dt.normalize()
    d["ticker"] = d["ticker"].astype("string").str.strip().str.rstrip("*")
    d["stock"] = d["ticker"].fillna(d["sid"]).str.upper() + ".NS"
    d = d[d["weight"] > 0]

    # one ISIN must map to one label and one label to one ISIN, or columns would silently merge or split
    assert d.groupby("ISIN")["stock"].nunique().max() == 1
    assert d.groupby("stock")["ISIN"].nunique().max() == 1
    assert not d.duplicated(["rebalance_date", "ISIN"]).any()

    m = pd.crosstab(d["rebalance_date"], d["stock"]).clip(upper=1).astype(int)
    first = d.groupby("stock")["rebalance_date"].min().sort_values()
    m = m[first.sort_values(kind="stable").index.tolist()]  # columns ordered by first date held
    m.columns.name = None

    cols = (d.groupby("stock")
              .agg(ISIN=("ISIN", "first"), name=("name", "first"), sid=("sid", "first"),
                   first_held=("rebalance_date", "min"), last_held=("rebalance_date", "max"),
                   rebalances_held=("rebalance_date", "nunique"))
              .loc[m.columns].reset_index())
    return m, cols


def main(parent: str) -> None:
    m, cols = build(parent)
    OUT.mkdir(parents=True, exist_ok=True)
    m.to_csv(OUT / f"{parent}_holdings_matrix.csv", index_label="rebalance_date", date_format="%Y-%m-%d")
    cols.to_csv(OUT / f"{parent}_columns.csv", index=False, date_format="%Y-%m-%d")
    print(f"{parent}: {m.shape[0]} rebalance dates x {m.shape[1]} stocks, "
          f"{m.index.min().date()} -> {m.index.max().date()}")
    print("stocks held per rebalance: min", int(m.sum(axis=1).min()), "max", int(m.sum(axis=1).max()))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "SCMO_0003")
