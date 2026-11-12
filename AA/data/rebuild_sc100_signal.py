"""Recompute the Smallcap 100 weekly supertrend signal from NON-corrupted data only (rule 7 of APPROVED_DATA.md).

    python data/rebuild_sc100_signal.py --check     # computes and compares with D03, writes nothing
    python data/rebuild_sc100_signal.py             # writes Historical Data/extended_2026-11-12/SC100_signal_from_2011-10-03/

Why (Manu, chat 2026-11-12): the Smallcap 100 prices before 2011-10-03 have no real open/high/low, and the D03 Smallcap 100
signal was computed on them. This script reruns the same production code on the real bars only:
  * input: the APPROVED Smallcap 100 daily file (D25) from 2011-10-03 (the first real-range bar) to its last date, and the
    APPROVED NSE calendar (D26) written to a temporary xlsx in production's layout; nothing else is read except the
    D03 Master_SC100 rows dated on or after 2011-10-03 (for the comparison);
  * code: the vendored production ST.py + analysis_master.py (sha256 checked against production, never overwritten),
    W frequency, multiplier 2, newRun=True, exactly as data/extend_supertrend.py and data/extend_mauc1.py;
  * a fresh start seeds the bands differently from D03's run, which carried the flat-bar history; the comparison below
    shows how many weeks it takes the two to agree. The output is a candidate: it stays off-limits until Manu approves.

Run it with the production pins (pandas 2.2.3, numpy 1.26.4, openpyxl, xlsxwriter, scipy, scikit-learn).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

AA = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AA / "analysis"))
import approved_data as ad  # noqa: E402
import mauc1_st_production as mp  # noqa: E402

FIRST = pd.Timestamp("2011-10-03")
SC = AA / "Historical Data" / "extended_2026-11-12" / "index_daily_pre2019" / "SC100_daily_ohlcv.csv"      # D25
CAL = AA / "Historical Data" / "extended_2026-11-12" / "index_daily_pre2019" / "nse_trading_days.csv"       # D26
D03 = AA / "Historical Data" / "extended_2026-10-30" / "Master" / "Master_SC100.xlsx"                       # D03
OUT = AA / "Historical Data" / "extended_2026-11-12" / "SC100_signal_from_2011-10-03"
CMP = ["Index", "ST", "FUB", "FLB", "BUB", "BLB", "EMA_Close", "EMA_TR", "Long_Weight"]
FOLDER = "SC100"


def sha(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def check_vendor() -> dict:
    out = {}
    for rel in mp.VENDORED:
        a, b = mp.PROD / rel, mp.VENDOR / rel
        if sha(a) != sha(b):
            raise SystemExit(f"STOP: vendored {rel} differs from production; not overwriting.")
        out[rel] = sha(a)
    return out


def main(check_only: bool) -> int:
    for p in (SC, CAL, D03):
        ad.check_sha(p)
    ad.guard_window(SC, FIRST)
    # D03's Smallcap 100 rows from 2011-10-03 are read HERE ONLY to compare them with the clean recompute, which is what establishes the
    # restriction (rule 7, usable-from 2011-11-18). This audit script is the one place allowed to do it; no test may. No D03 row before
    # 2011-10-03 is read (the slice below).
    hashes = check_vendor()
    qd, run, build_master = mp.import_production()

    d = pd.read_csv(SC, parse_dates=["date"])
    d = d[d["date"] >= FIRST].sort_values("date").reset_index(drop=True)      # nothing before the first real bar is kept
    flat = ((d["open"] == d["high"]) & (d["high"] == d["low"]) & (d["low"] == d["close"]))
    print(f"input {SC.name} sha256 {sha(SC)[:16]}: {len(d)} rows {d['date'].min().date()} -> {d['date'].max().date()}; "
          f"flat (open=high=low=close) bars in it: {int(flat.sum())} ({[str(x.date()) for x in d.loc[flat, 'date']]})")
    cal = pd.to_datetime(pd.read_csv(CAL)["date"])
    cal = cal[cal <= d["date"].max()]

    tmp = Path(tempfile.mkdtemp(prefix="sc100_signal_"))
    xlsx = tmp / "indices_ohlcv.xlsx"
    with pd.ExcelWriter(xlsx) as xw:
        d[["date", "open", "high", "low", "close", "volume"]].to_excel(xw, sheet_name=FOLDER, index=False)
    cal_xlsx = tmp / "TradingDays.xlsx"                                        # production's layout: two header rows, then 'Date'
    rows = [["Start", pd.Timestamp("1990-12-31")], ["End", cal.max()], [np.nan, "Date"]] + [[np.nan, x] for x in cal]
    with pd.ExcelWriter(cal_xlsx) as xw:
        pd.DataFrame(rows).to_excel(xw, sheet_name="Sheet1", header=False, index=False)

    idx = mp._master_to_wide(mp._load_index_master(xlsx), [FOLDER])
    scrip = mp.scrip_for(qd, idx, FOLDER, cal_xlsx)
    out_dir = tmp / FOLDER
    out_dir.mkdir()
    df, ok = mp.run_quiet(run, scrip, out_dir, "sc", cal_xlsx)
    df.to_excel(out_dir / "W_allRebal.xlsx")
    build_master(str(out_dir / "W_allRebal.xlsx"), str(out_dir / f"Master_{FOLDER}.xlsx"), label=FOLDER)
    m = pd.read_excel(out_dir / f"Master_{FOLDER}.xlsx", parse_dates=["Date"]).set_index("Date")
    print(f"recomputed Master: {len(m)} weekly rows {m.index.min().date()} -> {m.index.max().date()}; first SIGN {m['SIGN'].dropna().index.min().date()}")

    old = pd.read_excel(D03, parse_dates=["Date"]).set_index("Date")
    old = old.loc[old.index >= FIRST]                                           # rule 7: rows before the first real bar are not used
    both = old.index.intersection(m.index)
    sg = (old.loc[both, "SIGN"] != m.loc[both, "SIGN"])
    diff = {c: (old.loc[both, c].astype(float) - m.loc[both, c].astype(float)).abs() for c in CMP}
    # the first date from which SIGN agrees on every later week
    bad_dates = both[sg.values]
    last_bad = bad_dates.max() if len(bad_dates) else None
    agree_from = (both[both > last_bad][0] if last_bad is not None and (both > last_bad).any() else (both[0] if last_bad is None else None))
    rep = {"rows_new": len(m), "rows_d03_from_first_bar": len(old), "overlap": len(both),
           "sign_mismatch_weeks": int(sg.sum()), "sign_mismatch_dates": [str(x.date()) for x in bad_dates],
           "sign_agrees_on_every_week_from": str(agree_from.date()) if agree_from is not None else None,
           "max_abs_diff_by_column_all_overlap": {c: float(v.max()) for c, v in diff.items()},
           "weeks_with_any_column_diff_over_1e-6": int((pd.concat(diff, axis=1).max(axis=1) > 1e-6).sum()),
           "last_week_with_any_column_diff_over_1e-6": (lambda s: str(s.index[s > 1e-6].max().date()) if (s > 1e-6).any() else None)(pd.concat(diff, axis=1).max(axis=1)),
           "ST_abs_diff_by_half_year": {str(k): round(float(v), 3) for k, v in diff["ST"].groupby([diff["ST"].index.year, (diff["ST"].index.month > 6).astype(int)]).max().items()}}
    dd_all = pd.concat(diff, axis=1)
    detail = dd_all[dd_all.max(axis=1) > 1e-6]
    rep["weeks_with_diff_detail"] = {str(i.date()): {c: round(float(v), 4) for c, v in r.items() if v > 1e-6} for i, r in detail.iterrows()}
    rep["sign_on_those_weeks"] = {str(i.date()): {"d03": str(old.loc[i, "SIGN"]), "new": str(m.loc[i, "SIGN"])} for i in detail.index}
    print(json.dumps(rep, indent=1))
    if len(bad_dates):
        show = pd.DataFrame({"SIGN_d03": old.loc[bad_dates, "SIGN"], "SIGN_new": m.loc[bad_dates, "SIGN"], "ST_d03": old.loc[bad_dates, "ST"].round(1), "ST_new": m.loc[bad_dates, "ST"].round(1)})
        print(show.to_string())
    if check_only:
        print("--check: nothing written.")
        return 0
    if OUT.exists():
        raise SystemExit(f"{OUT} exists; originals are never overwritten")
    OUT.mkdir(parents=True)
    (out_dir / f"Master_{FOLDER}.xlsx").replace(OUT / f"Master_{FOLDER}.xlsx")
    (out_dir / "W_allRebal.xlsx").replace(OUT / "W_allRebal.xlsx")
    for src_name, dst_name in (("weekIndexDf_sc_W.xlsx", "weekIndexDf_W.xlsx"), ("indexDf_sc_W.xlsx", "indexDf_W.xlsx")):
        if (out_dir / src_name).exists():
            (out_dir / src_name).replace(OUT / dst_name)
    w = pd.read_excel(OUT / "weekIndexDf_W.xlsx", index_col=0)
    w.index = pd.to_datetime(w.index)
    t = w.rename(columns={"High": "high", "Low": "low", "Close": "close"})[["high", "low", "close", "PClose", "HML", "HMC", "LMC", "TR", "AHML"]].copy()
    t = t.join(m[["EMA_TR", "BUB", "BLB", "FUB", "FLB", "ST", "SIGN"]].rename(columns={"EMA_TR": "wATR"}))
    t["signal"] = t["SIGN"].map({"BUY": 1.0, "SELL": 0.0})
    t.index.name = "review"
    t.to_csv(OUT / "sc100_supertrend_weekly_from_2011-10-03.csv")
    manifest = {"what": "Smallcap 100 weekly supertrend recomputed from the first real-range bar (2011-10-03), vendored production code",
                "call": "ST.run(scrip, 'W', 2, True, ...) + analysis_master.build_analysis_master",
                "inputs": {"D25 SC100": {"path": str(SC.relative_to(AA)), "sha256": sha(SC), "rows_used": len(d), "first": str(d['date'].min().date()), "last": str(d['date'].max().date())},
                           "D26 calendar": {"path": str(CAL.relative_to(AA)), "sha256": sha(CAL)},
                           "D03 SC100 (comparison, rows from 2011-10-03 only)": {"path": str(D03.relative_to(AA)), "sha256": sha(D03)}},
                "code_sha256": hashes, "pandas": pd.__version__, "numpy": np.__version__, "comparison_with_d03": rep,
                "outputs": {p.name: sha(p) for p in sorted(OUT.iterdir()) if p.is_file()}}
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print("wrote", OUT)
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    sys.exit(main(a.check))
