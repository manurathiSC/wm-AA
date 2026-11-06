# -*- coding: utf-8 -*-
"""Targeted re-check after the warm-up fix: Signals_1421 and the four D_*_1421 sheets."""
import sys
import numpy as np
import pandas as pd
from openpyxl import load_workbook
from pycel import ExcelCompiler
from common import EVIDENCE_DIR
E = EVIDENCE_DIR / "final_strategy"
XL = E / "final_strategy_workbook_mauc1.xlsx"
sys.setrecursionlimit(20000)
wb = load_workbook(XL, read_only=True); nrows = {s: wb[s].max_row for s in wb.sheetnames}; wb.close()
xc = ExcelCompiler(filename=str(XL))
rows = []
for i in range(2, 8):
    print("Gold_ST R", i, repr(xc.evaluate(f"Gold_ST!R{i}")))
bad = sum(int(xc.evaluate(f"Signals_1421!Q{i}") != "ok") for i in range(2, nrows["Signals_1421"] + 1))
rows.append({"check": "Signals_1421 gold weight (formula) = python", "rows": nrows["Signals_1421"] - 1, "mismatches": bad})
for aa in ("0042", "0043", "0044", "0045"):
    s = f"D_{aa}_1421"
    v = np.array([xc.evaluate(f"{s}!X{i}") for i in range(2, nrows[s] + 1)], dtype=float)
    q = pd.read_csv(E / f"python_check_model_SCMO_{aa}_2014_2021.csv").check_model_nav.values
    d = np.abs(v - q)
    pd.DataFrame({"check_nav": v}).to_csv(E / f"pycel_{s}.csv", index=False)
    rows.append({"check": f"{s} daily NAV (formula) = Python replica, |diff| < 1e-12", "rows": len(v), "mismatches": int((d > 1e-12).sum()), "max_abs_diff": float(d.max())})
    print(rows[-1], flush=True)
R = pd.DataFrame(rows)
V = pd.read_csv(E / "verification.csv")
V = V[~V.check.isin(R.check)]
out = pd.concat([V, R], ignore_index=True)
order = ["Gold_ST", "GOLDBEES_fill", "Signals_live", "Signals_1421", "D_0042_live", "D_0043_live", "D_0044_live", "D_0045_live", "D_0042_1421", "D_0043_1421", "D_0044_1421", "D_0045_1421"]
out["o"] = out.check.map(lambda c: next((k for k, p in enumerate(order) if c.startswith(p)), 99))
out.sort_values("o", kind="stable").drop(columns="o").to_csv(E / "verification.csv", index=False)
print(pd.read_csv(E / "verification.csv").to_string(index=False))
