"""Holding-weight matrix for a parent smallcase: the holdings matrix with the actual weight instead of 1.

    python data/build_holding_weight_matrix.py [SCMO_0003 ...]     (default: all four parents)

Input : data/holdings_matrix/<parent>_holdings_matrix.csv   rows = rebalance_date (= availableDate), columns = stocks, 0/1
        data/holdings_matrix/<parent>_columns.csv           stock -> ISIN
        Postgres public.smallcase_rebal_historical          (read-only; needs wm-aiReports/.env)  PRIMARY source of weights
        Historical Data/frozen_2026-09-25/Rebalance_history/Rebalance_history_by_scid_<parent>.csv   fallback + cross-check
Output: data/holdings_matrix/<parent>_holding_weight_matrix.csv   same rows and columns; cell = weight (0 = not held)
        data/holdings_matrix/<parent>_holding_weight_sources.csv  one row per matrix row: where its weights came from, checks

Rules
- Stocks are matched by platform sid (a stock can carry two ISINs, e.g. TD Power), ISIN as fallback.
- A matrix row (effective date R) takes its weights from the DB rows whose available_date = R.
- The DB's `rebalance_date` is NOT the signal date of the frozen CSV (it differs by days for many baskets), so it is never used to join.
- The newest basket of each parent has available_date NULL in the DB (version 42 / 39). It is matched to the one uncovered matrix
  row whose ISIN set is identical, and the match is asserted to be unique.
- Baskets the DB does not hold (the CSV's skipped=true baskets: 0007 2020-03-16 and 2021-09-16, 0029 2020-03-16) take their
  weights from the CSV, which lists them (drifted, not target weights). Source column says 'csv_only_skipped'.
- Weights are as stored: not renormalised. Row sums run 0.9996-1.0005 (F-AA-D05 note); renormalise before use.
- Every row is cross-checked against the CSV on (effective date, ISIN); the max difference is in the sources file.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_ohlc_file import connect  # read-only Postgres connection used across the project

AA = Path(__file__).resolve().parents[1]
HM = AA / "data" / "holdings_matrix"
CSV = AA / "Historical Data" / "frozen_2026-09-25" / "Rebalance_history"
PARENTS = ["SCMO_0003", "SCMO_0007", "SCMO_0010", "SCMO_0029"]


def build(parent: str, conn) -> None:
    m = pd.read_csv(HM / f"{parent}_holdings_matrix.csv", index_col=0)
    m.index = pd.to_datetime(m.index)
    cc = pd.read_csv(HM / f"{parent}_columns.csv")
    isin2stock = cc.set_index("ISIN")["stock"].to_dict()
    sid2stock = cc.set_index("sid")["stock"].to_dict()

    db = pd.read_sql("select * from smallcase_rebal_historical where scid=%(s)s", conn, params={"s": parent})
    db["isin"] = db["isin"].str.strip().str.upper()
    db["stock"] = db["sid"].map(sid2stock).fillna(db["isin"].map(isin2stock))
    db["R"] = pd.to_datetime(db["available_date"]).dt.tz_localize(None).dt.normalize()

    # newest basket(s) with no available_date: match to the uncovered matrix row with the same ISIN set
    for rd, g in db[db["R"].isna()].groupby("rebalance_date"):
        hit = [r for r in m.index if r not in set(db["R"].dropna()) and
               {c for c in m.columns[m.loc[r] > 0]} == set(g["stock"])]
        assert len(hit) == 1, (parent, rd, hit)
        db.loc[g.index, "R"] = hit[0]

    csv = pd.read_csv(CSV / f"Rebalance_history_by_scid_{parent}.csv")
    csv["R"] = pd.to_datetime(csv["availableDate"], format="%d/%m/%y %H:%M").dt.normalize()
    csv["isin"] = csv["ISIN"].astype(str).str.strip().str.upper()
    csv["skipped"] = csv["skipped"].astype(str).str.lower().eq("true")

    W = pd.DataFrame(0.0, index=m.index, columns=m.columns)
    src = []
    for R in m.index:
        held = {isin2stock_inv: 1 for isin2stock_inv in m.columns[m.loc[R] > 0]}
        d = db[db["R"] == R]
        c = csv[csv["R"] == R]
        if len(d):
            assert not d.duplicated("stock").any() and d["version"].nunique() == 1, (parent, R)
            assert d["stock"].notna().all(), (parent, R, d.loc[d["stock"].isna(), ["sid", "isin"]].values.tolist())
            use, source = d.set_index("stock")["weight"], "db"
        else:
            c = c.assign(stock=c["sid"].map(sid2stock).fillna(c["isin"].map(isin2stock)))
            assert c["stock"].notna().all(), (parent, R)
            use, source = c.set_index("stock")["weight"], "csv_only_skipped" if c["skipped"].any() else "csv_only"
        w = pd.Series(use.values.astype(float), index=use.index)
        w = w[w > 0]
        assert set(w.index) == set(held), (parent, R, set(w.index) ^ set(held))
        W.loc[R, w.index] = w.values
        c = c.assign(stock=c["sid"].map(sid2stock).fillna(c["isin"].map(isin2stock)))
        cw = c.set_index("stock")["weight"].astype(float)
        cw = cw[cw > 0]
        both = w.index.intersection(cw.index)
        src.append({"rebalance_date": R.date(), "source": source, "n_held": len(w), "weight_sum": w.sum(),
                    "min_w": w.min(), "max_w": w.max(),
                    "csv_same_holdings": set(w.index) == set(cw.index),
                    "csv_max_abs_diff": float((w[both] - cw[both]).abs().max()) if len(both) else np.nan,
                    "csv_skipped_flag": bool(c["skipped"].all()) if len(c) else None,
                    "db_version": int(d["version"].iloc[0]) if len(d) else None,
                    "db_rebalance_date": d["rebalance_date"].iloc[0] if len(d) else None})
    W.to_csv(HM / f"{parent}_holding_weight_matrix.csv", index_label="rebalance_date", date_format="%Y-%m-%d",
             float_format="%.10g")
    s = pd.DataFrame(src)
    s.to_csv(HM / f"{parent}_holding_weight_sources.csv", index=False)
    assert ((W > 0) == (m > 0)).all().all()
    print(f"{parent}: {W.shape[0]} rows x {W.shape[1]} stocks | source {s['source'].value_counts().to_dict()} | "
          f"sum {s.weight_sum.min():.4f}-{s.weight_sum.max():.4f} | max |db-csv| {s.csv_max_abs_diff.max():.2e} | "
          f"rows whose holdings differ from csv {int((~s.csv_same_holdings).sum())}")


if __name__ == "__main__":
    conn = connect()
    for p in (sys.argv[1:] or PARENTS):
        build(p, conn)
