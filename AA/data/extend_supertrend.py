"""Extend the three-index supertrend signals (D03) past the frozen 2026-09-18 copy.

    python data/extend_supertrend.py --check          # computes and compares, writes nothing
    python data/extend_supertrend.py                  # writes Historical Data/extended_<last>/Master/

Same manner as extend_liquid.py / extend_goldbees.py (F-AA-D13):
  * the frozen D03 files (Historical Data/frozen_2026-09-25/Master) are never edited;
  * the output is a new directory named after the last weekly row;
  * the signals are RECOMPUTED, not copied: the vendored production ST.py + analysis_master.py
    (analysis/vendor_fra/, sha256 checked against production, never overwritten here) are run on
    production's own indices_ohlcv.xlsx and TradingDays.xlsx (read only), exactly as
    analysis/mauc1_st_production.reproduce() does, W frequency, multiplier 2, newRun=True;
  * the run STOPS when any recomputed row on a date the frozen file also has differs from it
    (a restated price history would make the splice inconsistent), and prints every date that is
    in one side only;
  * as a second check the recomputed Master is compared with production's own
    RSI/Final/Analysis/Master_<index>.xlsx (informational; reported, not required).

Run it with the production pins (pandas 2.2.3, numpy 1.26.4, openpyxl, xlsxwriter, scipy, scikit-learn):
the vendored ST.py uses fillna(method='ffill'), which pandas 3/4 removed.

Source of the prices: Refinitiv rd.get_history, fetched by the production Friday job (D02), not Postgres;
Postgres windmill holds no copy of these index series that is on the same basis, so there is no
database comparison for this file.
"""
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

AA = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AA / "analysis"))
import mauc1_st_production as mp  # noqa: E402  (PROD, VENDOR, loaders; importing it runs nothing)

FOLDERS = ["Nifty100", "MC100", "SC100"]
FROZEN = AA / "Historical Data" / "frozen_2026-09-25" / "Master"
PROD = mp.PROD
CMP = ["Index", "ST", "FUB", "FLB", "BUB", "BLB", "EMA_Close", "EMA_TR", "Long_Weight"]


def sha(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def check_vendor() -> dict:
    out = {}
    for rel in mp.VENDORED:
        a, b = PROD / rel, mp.VENDOR / rel
        if sha(a) != sha(b):
            raise SystemExit(f"STOP: vendored {rel} differs from production; not overwriting. "
                             f"Review the change before extending.")
        out[rel] = sha(a)
    return out


def main(check_only: bool) -> int:
    hashes = check_vendor()
    qd, run, build_master = mp.import_production()
    src = PROD / "Data" / "indices_ohlcv.xlsx"
    cal = PROD / "Data" / "TradingDays.xlsx"
    cal_last = pd.to_datetime(pd.read_excel(cal, header=None, skiprows=3)[1]).max()
    idx = mp._master_to_wide(mp._load_index_master(src), FOLDERS)
    print(f"input {src.name}  sha256 {sha(src)[:16]}  last bar {idx[0].dropna(how='all').index.max().date()}; "
          f"calendar last {cal_last.date()}")

    tmp = Path(tempfile.mkdtemp(prefix="st_extend_"))
    new, report, ok_all = {}, [], True
    for f in FOLDERS:
        d = tmp / f
        d.mkdir()
        df, _ = mp.run_quiet(run, mp.scrip_for(qd, idx, f, cal), d, "ext", cal)
        df.to_excel(d / "W_allRebal.xlsx")
        m = build_master(str(d / "W_allRebal.xlsx"), str(d / f"Master_{f}.xlsx"), label=f)
        m = pd.read_excel(d / f"Master_{f}.xlsx", parse_dates=["Date"]).set_index("Date")
        new[f] = m

        old = pd.read_excel(FROZEN / f"Master_{f}.xlsx", parse_dates=["Date"]).set_index("Date")
        both = old.index.intersection(m.index)
        diffs = {c: float((old.loc[both, c].astype(float) - m.loc[both, c].astype(float)).abs().max())
                 for c in CMP}
        sign_bad = int((old.loc[both, "SIGN"] != m.loc[both, "SIGN"]).sum())
        only_old, only_new = list(old.index.difference(m.index)), list(m.index.difference(old.index))
        ok = sign_bad == 0 and max(diffs.values()) < 1e-6 and not only_old
        ok_all &= ok

        pm = pd.read_excel(PROD / "RSI" / "Final" / "Analysis" / f"Master_{f}.xlsx",
                           parse_dates=["Date"]).set_index("Date")
        pboth = pm.index.intersection(m.index)
        p_sign = int((pm.loc[pboth, "SIGN"] != m.loc[pboth, "SIGN"]).sum())
        p_num = max(float((pm.loc[pboth, c].astype(float) - m.loc[pboth, c].astype(float)).abs().max()) for c in CMP)
        report.append({"index": f, "rows_frozen": len(old), "rows_new": len(m), "overlap": len(both),
                       "overlap_max_abs_diff": max(diffs.values()), "overlap_sign_mismatches": sign_bad,
                       "dates_only_in_frozen": [str(x.date()) for x in only_old],
                       "dates_added": [str(x.date()) for x in only_new],
                       "vs_production_master": {"rows": len(pm), "sign_mismatches": p_sign, "max_abs_diff": p_num,
                                                "dates_only_in_production": [str(x.date()) for x in pm.index.difference(m.index)],
                                                "dates_only_here": [str(x.date()) for x in m.index.difference(pm.index)]},
                       "pass": ok})
        print(json.dumps(report[-1]))
        print(m.loc[only_new, ["Index", "ST", "FUB", "FLB", "SIGN"]].to_string())

    if not ok_all:
        print("STOP: the overlap with the frozen D03 disagrees; nothing written.")
        return 1
    last = max(m.index.max() for m in new.values())
    if check_only:
        print("--check: nothing written.")
        return 0
    out = AA / "Historical Data" / f"extended_{last.date()}" / "Master"
    out.mkdir(parents=True, exist_ok=True)
    for f in FOLDERS:
        dst = out / f"Master_{f}.xlsx"
        if dst.exists():
            raise SystemExit(f"{dst} exists; originals are never overwritten")
        (tmp / f / f"Master_{f}.xlsx").replace(dst)
    manifest = {"what": "D03 three-index supertrend, recomputed with the vendored production code",
                "call": "ST.run(scrip, 'W', 2, True, ...) + analysis_master.build_analysis_master",
                "input": str(src), "input_sha256": sha(src), "calendar": str(cal), "calendar_sha256": sha(cal),
                "calendar_last": str(cal_last.date()), "code_sha256": hashes,
                "frozen_inputs": {f: sha(FROZEN / f"Master_{f}.xlsx") for f in FOLDERS},
                "outputs": {f: sha(out / f"Master_{f}.xlsx") for f in FOLDERS},
                "pandas": pd.__version__, "numpy": np.__version__, "checks": report}
    (out.parent / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print("wrote", out)
    return 0


if __name__ == "__main__":
    sys.exit(main("--check" in sys.argv))
