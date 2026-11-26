"""Extend the MAUc1 (MCX gold futures) weekly supertrend past the stored 2026-09-25 run.

    python data/extend_mauc1.py --check      # computes and compares, writes nothing
    python data/extend_mauc1.py              # writes Historical Data/extended_<last>/MAUc1/

Same manner as extend_supertrend.py (F-AA-D13), for the gold signal:
  * the stored run (Historical Data/FRA_MAUc1, evidence/final_strategy/mauc1/) is never edited, and neither is
    D12 (mauc1_daily_clean.csv): this script does NOT call mauc1_signal.load_clean (it would overwrite D12);
    the same cleaning rules are applied here in memory;
  * the signal is RECOMPUTED with the vendored production ST.py + analysis_master.py (sha256 checked against
    production, never overwritten), W frequency, multiplier 2, newRun=True, on production's current NSE calendar
    (Data/TradingDays.xlsx, read only);
  * the input is Manu's MAUc1 export (Eikon, five sheets Open/Close/Low/High/Volume), given on 2026-11-12;
    bars after --last (default 2026-11-06, the last complete week) are dropped before the run, because the week
    after it is unfinished and the last MCX bar is partial;
  * the run STOPS when any recomputed row on a date the stored Master_MAUc1 also has differs from it, and prints
    every date in one side only.

Run it with the production pins (pandas 2.2.3, numpy 1.26.4, openpyxl, xlsxwriter, scipy, scikit-learn): the
vendored ST.py uses fillna(method='ffill'), which pandas 3/4 removed.
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
import mauc1_st_production as mp  # noqa: E402  (importing it runs nothing)

SRC = Path(r"G:\.shortcut-targets-by-id\0B7f_UMMZHM_JNXljMVVXY2VPcHM\Investment Research_N\Manu\Universe\MAUC1TradingDays.xlsx")
STORED_MASTER = mp.ANALYSIS / "Master_MAUc1.xlsx"
D12 = AA / "analysis" / "evidence" / "final_strategy" / "mauc1" / "mauc1_daily_clean.csv"
FOLDER = mp.FOLDER
CMP = ["Index", "ST", "FUB", "FLB", "BUB", "BLB", "EMA_Close", "EMA_TR", "Long_Weight"]


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


def read_export() -> pd.DataFrame:
    cols = {}
    for s in ["Open", "High", "Low", "Close", "Volume"]:
        d = pd.read_excel(SRC, sheet_name=s, header=None, skiprows=3, usecols=[1, 2], names=["date", s.lower()])
        d["date"] = pd.to_datetime(d["date"], errors="coerce")
        d = d.dropna(subset=["date"]).set_index("date")
        cols[s.lower()] = pd.to_numeric(d[s.lower()], errors="coerce")
    return pd.DataFrame(cols).sort_index()


ENV = AA.parents[1] / "wm-aiReports" / ".env"


def read_db() -> pd.DataFrame:
    """MAUc1 daily bars from Postgres windmill.public.ohlcv_eikon_futures (ric 'MAUc1', the same Eikon continuation
    series as Manu's export), read-only session."""
    import psycopg2
    env = {}
    for line in ENV.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.strip().split("=", 1)
            env[k] = v.strip("\"'")
    c = psycopg2.connect(host=env["PG_PRICE_HOST"], port=env["PG_PRICE_PORT"], dbname=env["PG_PRICE_DBNAME"],
                         user=env["PG_PRICE_USER"], password=env["PG_PRICE_PASSWORD"], connect_timeout=20)
    c.set_session(readonly=True)
    cur = c.cursor()
    cur.execute("select date, open, high, low, close, volume from ohlcv_eikon_futures where ric = 'MAUc1' order by date")
    d = pd.DataFrame(cur.fetchall(), columns=["date", "open", "high", "low", "close", "volume"])
    c.close()
    d["date"] = pd.to_datetime(d["date"])
    for k in ["open", "high", "low", "close", "volume"]:
        d[k] = pd.to_numeric(d[k], errors="coerce").astype(float)
    return d.set_index("date").sort_index()


def splice_db(raw: pd.DataFrame, db_from: pd.Timestamp) -> tuple[pd.DataFrame, dict]:
    """Export rows before db_from, Postgres rows from db_from on. STOPS unless every export row the DB also has,
    before db_from, is identical in open/high/low/close (the DB starts 2005-01-01; the export starts 2003-11-10)."""
    db = read_db()
    pre = raw[raw.index < db_from]
    both = pre.index.intersection(db.index)
    diff = {k: float((pre.loc[both, k] - db.loc[both, k]).abs().max()) for k in ["open", "high", "low", "close"]}
    only_db = db.index[(db.index >= pre.index.min()) & (db.index < db_from)].difference(pre.index)
    rep = {"db_rows": len(db), "db_first": str(db.index.min().date()), "db_last": str(db.index.max().date()),
           "export_rows_before_db_from": len(pre), "shared_before_db_from": len(both), "max_abs_diff_before_db_from": diff,
           "dates_only_in_db_before_db_from": [str(x.date()) for x in only_db],
           "export_rows_replaced_from_db_from": [str(x.date()) for x in raw.index[raw.index >= db_from]],
           "db_rows_used": len(db[db.index >= db_from])}
    print("splice:", json.dumps(rep, indent=1))
    if max(diff.values()) > 0 or len(only_db):
        raise SystemExit("STOP: the export and ohlcv_eikon_futures disagree before --db-from; nothing written.")
    return pd.concat([pre, db[db.index >= db_from]]).sort_index(), rep


def clean(d: pd.DataFrame) -> tuple[pd.DataFrame, list]:
    """The rules of mauc1_signal.load_clean, in memory (nothing is written)."""
    d = d.copy()
    log = []
    for dt in d.index[d.close.isna()]:
        log.append({"date": str(dt.date()), "action": "dropped: no close"})
    d = d[d.close.notna()]
    m = d[["open", "high", "low"]].isna().any(axis=1)
    for dt in d.index[m]:
        log.append({"date": str(dt.date()), "action": "close only: open/high/low set to close"})
    for c in ("open", "high", "low"):
        d[c] = d[c].fillna(d.close)
    bad = (d.high < d[["open", "close"]].max(axis=1)) | (d.low > d[["open", "close"]].min(axis=1))
    for dt in d.index[bad]:
        log.append({"date": str(dt.date()), "action": "bar widened to span open/high/low/close"})
    d["high"] = d[["open", "high", "low", "close"]].max(axis=1)
    d["low"] = d[["open", "high", "low", "close"]].min(axis=1)
    d["volume"] = d["volume"].fillna(0.0)
    return d, log


def main(check_only: bool, last: str, first: str, out_dir_arg: str | None = None, db_from: str | None = None) -> int:
    hashes = check_vendor()
    qd, run, build_master = mp.import_production()
    cal = mp.PROD / "Data" / "TradingDays.xlsx"
    cal_last = pd.to_datetime(pd.read_excel(cal, header=None, skiprows=3)[1]).max()
    last, first = pd.Timestamp(last), pd.Timestamp(first)
    if last > cal_last:
        raise SystemExit(f"STOP: --last {last.date()} is after the NSE calendar's last day {cal_last.date()}")

    raw = read_export()
    splice_rep = None
    if db_from:
        raw, splice_rep = splice_db(raw, pd.Timestamp(db_from))
    d, log = clean(raw)
    d = d.loc[first:last]
    print(f"input {SRC.name} sha256 {sha(SRC)[:16]}; raw {raw.index.min().date()} -> {raw.index.max().date()} "
          f"({len(raw)} rows); after cleaning and cut to {first.date()} -> {last.date()}: {len(d)} rows, last {d.index.max().date()}; "
          f"calendar last {cal_last.date()}")

    # the same shape as mauc1_st_production.build_input_sheet, written to a temporary folder only
    tmp = Path(tempfile.mkdtemp(prefix="mauc1_extend_"))
    sheet = d.reset_index().rename(columns={"index": "date"})[["date", "open", "high", "low", "close", "volume"]]
    xlsx = tmp / "indices_ohlcv.xlsx"
    with pd.ExcelWriter(xlsx) as xw:
        sheet.to_excel(xw, sheet_name=FOLDER, index=False)
    idx = mp._master_to_wide(mp._load_index_master(xlsx), [FOLDER])
    scrip = mp.scrip_for(qd, idx, FOLDER, cal)

    out_dir = tmp / FOLDER
    out_dir.mkdir()
    df, ok = mp.run_quiet(run, scrip, out_dir, "ext", cal)
    df.to_excel(out_dir / "W_allRebal.xlsx")
    build_master(str(out_dir / "W_allRebal.xlsx"), str(out_dir / f"Master_{FOLDER}.xlsx"), label=FOLDER)
    m = pd.read_excel(out_dir / f"Master_{FOLDER}.xlsx", parse_dates=["Date"]).set_index("Date")

    old = pd.read_excel(STORED_MASTER, parse_dates=["Date"]).set_index("Date")
    both = old.index.intersection(m.index)
    diffs = {c: float((old.loc[both, c].astype(float) - m.loc[both, c].astype(float)).abs().max()) for c in CMP}
    sign_bad = int((old.loc[both, "SIGN"] != m.loc[both, "SIGN"]).sum())
    only_old, only_new = list(old.index.difference(m.index)), list(m.index.difference(old.index))
    # A run that starts earlier than the stored one (2015-02-02) seeds the bands differently. The final lower band
    # (FLB) is only read by ST while SIGN is BUY, so a difference in FLB on SELL weeks cannot move ST or SIGN; it is
    # tolerated (and listed), every other column and every SIGN must match exactly.
    flb_d = (old.loc[both, "FLB"].astype(float) - m.loc[both, "FLB"].astype(float)).abs()
    flb_bad = flb_d[flb_d > 1e-6].index
    flb_only_sell = bool((old.loc[flb_bad, "SIGN"] == "SELL").all()) if len(flb_bad) else True
    rest = max(v for c, v in diffs.items() if c != "FLB")
    passed = sign_bad == 0 and rest < 1e-6 and not only_old and (diffs["FLB"] < 1e-6 or (flb_only_sell and len(flb_bad) <= 10))
    rep = {"rows_stored": len(old), "rows_new": len(m), "overlap": len(both),
           "overlap_max_abs_diff": max(diffs.values()), "per_column_max_abs_diff": diffs,
           "flb_differing_dates": [str(x.date()) for x in flb_bad], "flb_differences_all_on_SELL_weeks": flb_only_sell,
           "overlap_sign_mismatches": sign_bad, "dates_only_in_stored": [str(x.date()) for x in only_old],
           "dates_added": [str(x.date()) for x in only_new], "pass": passed}
    print(json.dumps(rep, indent=1))
    show = [c for c in ["Index", "ST", "FUB", "FLB", "SIGN"] if c in m.columns]
    print(m.loc[only_new, show].to_string())
    print("cleaning log (rows touched in the whole export):", len(log))
    if not passed:
        print("STOP: the overlap with the stored MAUc1 run disagrees; nothing written.")
        return 1
    if check_only:
        print("--check: nothing written.")
        return 0

    last_row = m.index.max()
    out = Path(out_dir_arg) if out_dir_arg else AA / "Historical Data" / f"extended_{last_row.date()}" / "MAUc1"
    out.mkdir(parents=True, exist_ok=True)
    for name in (f"Master_{FOLDER}.xlsx", "W_allRebal.xlsx"):
        dst = out / name
        if dst.exists():
            raise SystemExit(f"{dst} exists; originals are never overwritten")
    (out_dir / f"Master_{FOLDER}.xlsx").replace(out / f"Master_{FOLDER}.xlsx")
    (out_dir / "W_allRebal.xlsx").replace(out / "W_allRebal.xlsx")
    for src_name, dst_name in (("weekIndexDf_ext_W.xlsx", "weekIndexDf_W.xlsx"), ("indexDf_ext_W.xlsx", "indexDf_W.xlsx")):
        if (out_dir / src_name).exists():
            (out_dir / src_name).replace(out / dst_name)
    sheet.to_csv(out / "mauc1_daily_clean_extended.csv", index=False)
    pd.DataFrame(log).to_csv(out / "mauc1_cleaning_log_extended.csv", index=False)

    # the weekly table in the layout of evidence/final_strategy/mauc1/mauc1_supertrend_weekly.csv
    w = pd.read_excel(out / "weekIndexDf_W.xlsx", index_col=0)
    w.index = pd.to_datetime(w.index)
    t = w.rename(columns={"High": "high", "Low": "low", "Close": "close"})[
        ["high", "low", "close", "PClose", "HML", "HMC", "LMC", "TR", "AHML"]].copy()
    t = t.join(m[["EMA_TR", "BUB", "BLB", "FUB", "FLB", "ST", "SIGN"]].rename(columns={"EMA_TR": "wATR"}))
    t["signal"] = t["SIGN"].map({"BUY": 1.0, "SELL": 0.0})
    t.index.name = "review"
    t.to_csv(out / "mauc1_supertrend_weekly_extended.csv")

    manifest = {"what": "MAUc1 weekly supertrend, recomputed with the vendored production code (F-AA-D13 manner)",
                "call": "ST.run(scrip, 'W', 2, True, ...) + analysis_master.build_analysis_master",
                "input": str(SRC), "input_sha256": sha(SRC), "cut_at": str(last.date()),
                "db_from": db_from, "db_source": "Postgres windmill.public.ohlcv_eikon_futures, ric MAUc1" if db_from else None,
                "splice_check": splice_rep,
                "first_bar": str(first.date()), "input_rows_after_cleaning": len(d), "calendar": str(cal), "calendar_sha256": sha(cal),
                "calendar_last": str(cal_last.date()), "code_sha256": hashes,
                "stored_master": str(STORED_MASTER), "stored_master_sha256": sha(STORED_MASTER),
                "d12_sha256_untouched": sha(D12),
                "outputs": {p.name: sha(p) for p in sorted(out.iterdir()) if p.is_file()},
                "pandas": pd.__version__, "numpy": np.__version__, "check": rep}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print("wrote", out)
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--last", default="2026-11-06")
    ap.add_argument("--first", default="2015-02-02", help="the stored run starts here; a different start changes the band seeding")
    ap.add_argument("--out", default=None, help="output folder (default Historical Data/extended_<last row>/MAUc1); refuses to overwrite")
    ap.add_argument("--db-from", default=None, help="take bars on/after this date from Postgres ohlcv_eikon_futures (ric MAUc1); "
                                                    "earlier export rows must equal the DB exactly, or the run stops")
    a = ap.parse_args()
    sys.exit(main(a.check, a.last, a.first, a.out, a.db_from))
