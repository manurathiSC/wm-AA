"""
MAUc1 (MCX gold futures, continuous) through the desk's own supertrend pipeline.

Runs the production Friday-job code, unmodified, on MAUc1 and lays the outputs
out the way the job lays them out for its indices:

    <MIRROR>/Data/indices_ohlcv.xlsx            sheet MAUc1 (date, open, high, low, close, volume)
    <MIRROR>/Data/TradingDays.xlsx              copy of production's (NSE calendar)
    <MIRROR>/RSI/Final/MAUc1/W_allRebal.xlsx    permanent signal file (latest run)
    <MIRROR>/RSI/Final/MAUc1/W_allRebal_<ddmmyy>.xlsx, indexDf_/weekIndexDf_/monthIndexDf_<ddmmyy>_W.xlsx
    <MIRROR>/RSI/Final/Analysis/Master_MAUc1.xlsx   W_allRebal + SIGN + Long_Weight (analysis_master.py)
    <MIRROR>/run_manifest.json

Code path, identical to weekly_rebalance_nse_v2.py sections 4-7:
    _load_index_master  -> _master_to_wide  -> scrip = [[close, vol, high, low], sd, folder]
    -> Python_Scripts.ST.run(scrip, 'W', 2, True, out_d, out_w, out_m, exist, TradingDays.xlsx)
    -> allRebalDf.to_excel(W_allRebal_<dc>.xlsx) and W_allRebal.xlsx
    -> analysis_master.build_analysis_master(W_allRebal.xlsx, Master_MAUc1.xlsx)

ST.py, QuantBacktester.py, ProspectTheory.py and analysis_master.py are imported from
byte-identical copies in vendor_fra/ (sha256 checked against production on every run).
Importing QuantBacktester from the production folder would open that folder's
windmillcheck_ALL_2.log and write __pycache__ there; the copies keep production untouched.
The two loader functions live in weekly_rebalance_nse_v2.py, which runs the whole job
on import, so they are reproduced here verbatim.

Dated runs: production keeps W_allRebal_<ddmmyy>.xlsx for each Friday since 2026-07-03.
Each is re-created with ST.run's own lastDate argument, which cuts the trading calendar
at that Friday, as production's TradingDays.xlsx was on that day. Production runs at
~20:00 IST while MCX trades to 23:30, so a live Friday row would see a partial MCX bar;
these files use settled closes.

    python mauc1_st_production.py            # MAUc1 mirror
    python mauc1_st_production.py --repro    # also re-run Nifty100/MC100/SC100 and compare with production
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import shutil
import sys
import types
from pathlib import Path

import numpy as np
import pandas as pd

from common import AA_DIR, ANALYSIS_DIR

PROD = Path(r"G:\.shortcut-targets-by-id\0B7f_UMMZHM_JNXljMVVXY2VPcHM\Investment Research_N"
            r"\Shubham_Shreshtha\Friday Rebalance Automation")
VENDOR = ANALYSIS_DIR / "vendor_fra"
MIRROR = AA_DIR / "Historical Data" / "FRA_MAUc1"
DATA = MIRROR / "Data"
FINAL = MIRROR / "RSI" / "Final"
ANALYSIS = FINAL / "Analysis"
FOLDER = "MAUc1"
SRC_CSV = Path(r"C:\Users\manur\Downloads\MAUc1_daily1.csv")
FREQ, MUL, NEW_RUN = "W", 2, True          # production invariants (CLAUDE.md)
VENDORED = ["Python_Scripts/ST.py", "Python_Scripts/QuantBacktester.py",
            "Python_Scripts/ProspectTheory.py", "analysis_master.py"]


def sha(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


# ── production code, vendored byte for byte ────────────────────────────────
def vendor() -> dict:
    out = {}
    for rel in VENDORED:
        src, dst = PROD / rel, VENDOR / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if not dst.exists() or sha(dst) != sha(src):
            shutil.copyfile(src, dst)
        assert sha(dst) == sha(src), rel
        out[rel] = sha(src)
    return out


def import_production():
    sys.dont_write_bytecode = True
    sys.modules.setdefault("eikon", types.ModuleType("eikon"))   # used only by EikonApiReader, never by ST.py
    sys.path.insert(0, str(VENDOR))
    cwd = os.getcwd()
    os.chdir(VENDOR)                        # QuantBacktester's basicConfig log lands here
    try:
        import Python_Scripts.QuantBacktester as qd
        from Python_Scripts.ST import run
        from analysis_master import build_analysis_master
    finally:
        os.chdir(cwd)
    assert Path(qd.__file__).resolve().parent == (VENDOR / "Python_Scripts").resolve()
    return qd, run, build_analysis_master


# ── weekly_rebalance_nse_v2.py:269-295 and :312-345, verbatim logic ──────────
def _load_index_master(master_path):
    xl = pd.ExcelFile(master_path)
    result = {}
    for sheet in xl.sheet_names:
        df = xl.parse(sheet, parse_dates=['date'])
        df['date'] = pd.to_datetime(df['date'])
        df = (df.sort_values('date', kind='stable')
                .drop_duplicates(subset=['date'], keep='last')
                .dropna(subset=['open', 'high', 'low', 'close'], how='any')
                .reset_index(drop=True))
        result[sheet] = df
    return result


def _master_to_wide(master_data, folders):
    close_d, vol_d, high_d, low_d = {}, {}, {}, {}
    for folder in folders:
        df = master_data.get(folder)
        if df is None or df.empty:
            continue
        df = df.copy()
        df['date'] = pd.to_datetime(df['date'])
        df = (df.set_index('date')
                .pipe(lambda x: x[~x.index.duplicated(keep='last')])
                .sort_index())
        df.index.name = 'Date'
        close_d[folder] = df['close']
        high_d[folder] = df['high']
        low_d[folder] = df['low']
        vol_d[folder] = pd.to_numeric(df['volume'], errors='coerce').fillna(0.0)

    def _make(d):
        out = pd.DataFrame(d)
        out.index.name = 'Date'
        out = out[~out.index.duplicated(keep='last')].sort_index()
        return out.astype(float)

    return _make(close_d), _make(vol_d), _make(high_d), _make(low_d)


def scrip_for(qd, idx, folder, universe_fp):
    """weekly_rebalance_nse_v2.py section 7: idx_scripDict[folder]."""
    idx_close, idx_vol, idx_high, idx_low = (x.astype(float) for x in idx)
    idx_vol = idx_vol.fillna(0.0)
    tmpTradingDf = qd.ExcelInputReader().getDataFrame(str(universe_fp), sheetName='Sheet1')
    f_close = idx_close[[folder]].dropna().astype(float)
    f_vol = idx_vol[[folder]].dropna().astype(float)
    f_high = idx_high[[folder]].dropna().astype(float)
    f_low = idx_low[[folder]].dropna().astype(float)
    sd = np.maximum(tmpTradingDf['Date'].iloc[0], f_close[folder].first_valid_index())
    return [[f_close, f_vol, f_high, f_low], sd, folder]


def run_quiet(run, scrip, out_dir: Path, dc: str, universe_fp: Path, last_date=None):
    out_d = out_dir / f"indexDf_{dc}_{FREQ}.xlsx"
    out_w = out_dir / f"weekIndexDf_{dc}_{FREQ}.xlsx"
    out_m = out_dir / f"monthIndexDf_{dc}_{FREQ}.xlsx"
    exist = out_dir / f"{FREQ}_allRebal.xlsx"
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        allRebalDf, ok = run(scrip, FREQ, MUL, NEW_RUN, str(out_d), str(out_w), str(out_m), str(exist),
                             str(universe_fp), lastDate=last_date)
    return allRebalDf, ok


# ── inputs ─────────────────────────────────────────────────────────────────
def build_input_sheet() -> dict:
    """MAUc1 as a sheet of Data/indices_ohlcv.xlsx, from the cleaned export (mauc1_signal.load_clean)."""
    from mauc1_signal import load_clean
    raw = load_clean()
    d = raw[0] if isinstance(raw, tuple) else raw
    d = d.copy()
    d.columns = [c.lower() for c in d.columns]
    d = d.reset_index().rename(columns={d.index.name or "index": "date"})
    d["date"] = pd.to_datetime(d["date"])
    if "volume" not in d:
        d["volume"] = 0.0
    d = d[["date", "open", "high", "low", "close", "volume"]].sort_values("date")
    DATA.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(DATA / "indices_ohlcv.xlsx") as xw:
        d.to_excel(xw, sheet_name=FOLDER, index=False)
    shutil.copyfile(PROD / "Data" / "TradingDays.xlsx", DATA / "TradingDays.xlsx")
    return {"rows": len(d), "first": str(d["date"].iloc[0].date()), "last": str(d["date"].iloc[-1].date())}


def run_dates(universe_fp: Path) -> list[pd.Timestamp]:
    """The Fridays production keeps dated W_allRebal backups for, read off its SC100 folder."""
    codes = sorted({p.stem.split("_")[-1] for p in (PROD / "RSI" / "Final" / "SC100").glob("W_allRebal_*.xlsx")})
    days = sorted(pd.to_datetime(c, format="%d%m%y") for c in codes)
    td = pd.read_excel(universe_fp, header=None, skiprows=3)[1]
    td = set(pd.to_datetime(td))
    assert all(x in td for x in days), "a dated run is not an NSE trading day"
    return days


def main(repro: bool = False):
    hashes = vendor()
    qd, run, build_analysis_master = import_production()
    inp = build_input_sheet()
    universe_fp = DATA / "TradingDays.xlsx"
    idx = _master_to_wide(_load_index_master(DATA / "indices_ohlcv.xlsx"), [FOLDER])
    scrip = scrip_for(qd, idx, FOLDER, universe_fp)
    out_dir = FINAL / FOLDER
    out_dir.mkdir(parents=True, exist_ok=True)
    ANALYSIS.mkdir(parents=True, exist_ok=True)

    days = run_dates(universe_fp)
    td_last = pd.to_datetime(pd.read_excel(universe_fp, header=None, skiprows=3)[1]).max()
    runs = []
    for day in days:
        dc = day.strftime("%d%m%y")
        latest = day == td_last
        df, ok = run_quiet(run, scrip, out_dir, dc, universe_fp, None if latest else day)
        df.to_excel(out_dir / f"{FREQ}_allRebal_{dc}.xlsx")
        if latest and ok:
            df.to_excel(out_dir / f"{FREQ}_allRebal.xlsx")
        v = df.dropna(subset=["ST"]).iloc[-1]
        runs.append({"dateCode": dc, "last_week": str(df.dropna(subset=["ST"]).index[-1].date()),
                     "sign": "SELL" if v["FUB"] == v["ST"] else "BUY", "ST": float(v["ST"]), "Index": float(v["Index"]),
                     "permanent_file_written": bool(latest and ok)})
        print(runs[-1])
    assert (out_dir / f"{FREQ}_allRebal.xlsx").exists(), "latest production Friday not among the dated runs"
    m = build_analysis_master(str(out_dir / f"{FREQ}_allRebal.xlsx"), str(ANALYSIS / f"Master_{FOLDER}.xlsx"), label=FOLDER)

    manifest = {
        "what": "MAUc1 run through production ST.py + analysis_master.py, unmodified",
        "production_root": str(PROD),
        "code_sha256": hashes,
        "call": f"ST.run(scrip, freq='{FREQ}', mul={MUL}, newRun={NEW_RUN}, out_d, out_w, out_m, exist, TradingDays.xlsx[, lastDate])",
        "input_csv": str(SRC_CSV), "input_csv_sha256": sha(SRC_CSV),
        "input_sheet": {**inp, "cleaning": "mauc1_signal.load_clean (see evidence/final_strategy/mauc1/mauc1_cleaning_log.csv)"},
        "trading_days_sha256": sha(universe_fp), "trading_days_last": str(td_last.date()),
        "sd": str(pd.Timestamp(scrip[1]).date()),
        "runs": runs,
        "master_rows": int(len(m)), "master_first": str(pd.to_datetime(m["Date"]).min().date()),
        "master_last": str(pd.to_datetime(m["Date"]).max().date()),
        "pandas": pd.__version__, "numpy": np.__version__,
        "production_pins": "pandas 2.2.3, numpy 1.26.4 (requirements.txt)",
    }
    if repro:
        manifest["repro"] = reproduce(qd, run, build_analysis_master)
    (MIRROR / "run_manifest.json").write_text(json.dumps(manifest, indent=2))
    print(json.dumps({k: manifest[k] for k in ("sd", "master_rows", "master_first", "master_last")}, indent=1))


def reproduce(qd, run, build_analysis_master) -> list[dict]:
    """
    Proof the harness is the production pipeline: re-run the three equity indices from
    production's own indices_ohlcv.xlsx (read only; the input of its latest Friday run)
    and compare every cell with that run's W_allRebal.xlsx and every SIGN with its Master file.
    (frozen_2026-09-25/ was copied before that run and stops at 2026-09-18.)
    """
    src = PROD / "Data" / "indices_ohlcv.xlsx"
    universe_fp = DATA / "TradingDays.xlsx"
    tmp = ANALYSIS_DIR / "cache" / "fra_repro"
    folders = ["Nifty100", "MC100", "SC100"]
    idx = _master_to_wide(_load_index_master(src), folders)
    out = []
    for f in folders:
        (tmp / f).mkdir(parents=True, exist_ok=True)
        df, ok = run_quiet(run, scrip_for(qd, idx, f, universe_fp), tmp / f, "250926", universe_fp)
        df.to_excel(tmp / f / "W_allRebal.xlsx")
        mine = pd.read_excel(tmp / f / "W_allRebal.xlsx").set_index("Date")
        prod = pd.read_excel(PROD / "RSI" / "Final" / f / "W_allRebal.xlsx").set_index("Date")
        num = [c for c in prod.columns if c != "WGH_SRT"]
        a, b = mine[num].astype(float), prod[num].astype(float)
        both = a.notna() & b.notna()
        diff = (a - b).abs().where(both)
        nan_mismatch = int((a.isna() != b.isna()).sum().sum())
        wgh = (pd.to_datetime(mine["WGH_SRT"], errors="coerce").fillna(pd.Timestamp(0))
               != pd.to_datetime(prod["WGH_SRT"], errors="coerce").fillna(pd.Timestamp(0))).sum()
        mm = build_analysis_master(str(tmp / f / "W_allRebal.xlsx"), str(tmp / f / f"Master_{f}.xlsx"), label=f)
        pm = pd.read_excel(PROD / "RSI" / "Final" / "Analysis" / f"Master_{f}.xlsx")
        s1, s2 = mm.set_index("Date")["SIGN"], pm.set_index("Date")["SIGN"]
        out.append({"index": f, "input_sha256": sha(src), "rows_mine": len(mine), "rows_prod": len(prod),
                    "same_dates": bool(mine.index.equals(prod.index)),
                    "max_abs_diff": float(np.nanmax(diff.values)), "nan_pattern_mismatches": nan_mismatch,
                    "wgh_srt_mismatches": int(wgh),
                    "sign_rows": int(len(s2)), "sign_mismatches": int((s1.reindex(s2.index) != s2).sum())})
        print(out[-1])
    return out


if __name__ == "__main__":
    if "--repro-only" in sys.argv:
        vendor()
        res = reproduce(*import_production())
        mf = MIRROR / "run_manifest.json"
        man = json.loads(mf.read_text())
        man["repro"] = res
        mf.write_text(json.dumps(man, indent=2))
    else:
        main(repro="--repro" in sys.argv)
