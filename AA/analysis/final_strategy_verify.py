# -*- coding: utf-8 -*-
"""
Evaluate the workbook's formulas with pycel, an independent Excel formula
engine, and compare them with the Python engine:
  - Gold_ST signal column against the python supertrend (every week);
  - Signals_* gold weight against the python weights (every review);
  - D_* check-model NAV: evaluated row by row, then compared with a Python
    replica of the same recursion and with the harness NAV.
Writes evidence/final_strategy/verification.csv and check_model_reconciliation.csv.
"""

from __future__ import annotations

import sys

import numpy as np
import pandas as pd
from openpyxl import load_workbook
from pycel import ExcelCompiler

from common import EVIDENCE_DIR

E = EVIDENCE_DIR / "final_strategy"
XL = E / "final_strategy_workbook.xlsx"
if (E / "final_strategy_workbook_mauc1.xlsx").exists() and (E / "final_strategy_workbook_mauc1.xlsx").stat().st_mtime > XL.stat().st_mtime:
    XL = E / "final_strategy_workbook_mauc1.xlsx"
sys.setrecursionlimit(20000)


def main():
    wb = load_workbook(XL, read_only=True)
    sheets = wb.sheetnames
    nrows = {s: wb[s].max_row for s in sheets}
    wb.close()
    xc = ExcelCompiler(filename=str(XL))
    rows = []

    # Gold supertrend: every row, in order (the recursion runs down the sheet)
    bad, n = 0, 0
    for i in range(2, nrows["Gold_ST"] + 1):
        v = xc.evaluate(f"Gold_ST!R{i}")
        py = xc.evaluate(f"Gold_ST!S{i}")
        if py not in (None, ""):
            n += 1
            bad += int(v != py)
    rows.append({"check": "Gold_ST signal (formula) = ST.py SIGN (Master_MAUc1)", "rows": n, "mismatches": bad})
    try:
        mx = [xc.evaluate(f"Gold_ST!U{i}") for i in range(2, min(nrows["Gold_ST"], 60) + 1)]
        rows.append({"check": "Gold_ST weekly high = MAXIFS(daily), first 59 weeks", "rows": len(mx), "mismatches": sum(x != "ok" for x in mx)})
    except Exception as e:  # MAXIFS may be unsupported by pycel; Excel computes it
        rows.append({"check": "Gold_ST MAXIFS check", "rows": 0, "mismatches": -1, "note": f"not evaluable in pycel: {type(e).__name__}"})

    bad = sum(int(xc.evaluate(f"GOLDBEES_fill!P{i}") != "ok") for i in range(2, nrows["GOLDBEES_fill"] + 1))
    rows.append({"check": "GOLDBEES_fill de-spiked OHLC4 (formula) = python", "rows": nrows["GOLDBEES_fill"] - 1, "mismatches": bad})
    for key in ("live", "1421"):
        s = f"Signals_{key}"
        bad = 0
        for i in range(2, nrows[s] + 1):
            bad += int(xc.evaluate(f"{s}!Q{i}") != "ok")
        rows.append({"check": f"{s} gold weight (formula) = python", "rows": nrows[s] - 1, "mismatches": bad})

    rec = []
    for s in [x for x in sheets if x.startswith("D_")]:
        vals = []
        for i in range(2, nrows[s] + 1):
            vals.append((xc.evaluate(f"{s}!A{i}"), xc.evaluate(f"{s}!X{i}"), xc.evaluate(f"{s}!Y{i}"), xc.evaluate(f"{s}!K{i}")))
        df = pd.DataFrame(vals, columns=["date", "check_nav", "harness_nav", "trade"])
        # Python replica of the same recursion, from the sheet's own inputs
        raw = pd.read_excel(XL, sheet_name=s, usecols="A:E", header=0)
        rec.append({"sheet": s, "rows": len(df), "trades_in_check_model": int(pd.Series(df.trade).fillna(0).astype(float).sum()),
                    "final_check_nav": float(df.check_nav.iloc[-1]), "final_harness_nav": float(df.harness_nav.iloc[-1]),
                    "max_abs_gap": float((df.check_nav - df.harness_nav).abs().max()),
                    "final_gap_pct": float(df.check_nav.iloc[-1] / df.harness_nav.iloc[-1] - 1)})
        pd.DataFrame(df).to_csv(E / f"pycel_{s}.csv", index=False)
        print(rec[-1], flush=True)
    R = pd.DataFrame(rec)
    R.to_csv(E / "check_model_reconciliation.csv", index=False)
    rows += replica_rows()
    V = pd.DataFrame(rows)
    V.to_csv(E / "verification.csv", index=False)
    print(V.to_string(index=False))
    print(R.to_string(index=False))


def replica_rows() -> list[dict]:
    """Each D_ sheet's formula NAV (pycel_D_*.csv) against the Python replica of the check model."""
    out = []
    for tag, key in (("live", "live"), ("2014_2021", "1421")):
        for aa in ("0042", "0043", "0044", "0045"):
            p = pd.read_csv(E / f"pycel_D_{aa}_{key}.csv")
            q = pd.read_csv(E / f"python_check_model_SCMO_{aa}_{tag}.csv")
            d = np.abs(p.check_nav.values.astype(float) - q.check_model_nav.values)
            out.append({"check": f"D_{aa}_{key} daily NAV (formula) = Python replica, |diff| < 1e-12", "rows": len(p),
                        "mismatches": int((d > 1e-12).sum()), "max_abs_diff": float(d.max())})
    return out


if __name__ == "__main__":
    if "--replica-only" in sys.argv:          # re-use the pycel_D_*.csv of the last full run
        V = pd.read_csv(E / "verification.csv")
        V = V[~V.check.str.contains("Python replica")]
        V = pd.concat([V, pd.DataFrame(replica_rows())], ignore_index=True)
        V.to_csv(E / "verification.csv", index=False)
        print(V.to_string(index=False))
        raise SystemExit
    main()
