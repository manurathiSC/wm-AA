"""Copy the daily Nifty 100, Midcap 100 and Smallcap 100 prices and the NSE calendar, up to the end of the pre-2019 window,
from the production folder (read only) into a new folder, as candidate data for the 2007-2019 proxy test.

    python data/extract_index_prices.py --check     # prints the checks, writes nothing
    python data/extract_index_prices.py             # writes Historical Data/extended_2026-11-12/index_daily_pre2019/

Source (Manu, chat 2026-11-12: "use production data"): the Friday Rebalance Automation folder on the shared Drive,
  Data/indices_ohlcv.xlsx  sheets Nifty100, MC100, SC100 (date, open, high, low, close, volume)
  Data/TradingDays.xlsx    Sheet1, the NSE session calendar the three-index signal was computed on.
Rows are copied verbatim (no cleaning, no fill, no adjustment) from each sheet's first row to --last (default 2019-01-04,
two sessions after the window's last decision so a next-session fill exists). The production files are never opened for
writing. The output is a candidate: it stays off-limits until Manu approves it and data/APPROVED_DATA.md lists it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import pandas as pd

AA = Path(__file__).resolve().parents[1]
PROD = Path(r"G:\.shortcut-targets-by-id\0B7f_UMMZHM_JNXljMVVXY2VPcHM\Investment Research_N\Shubham_Shreshtha\Friday Rebalance Automation\Data")
OUT = AA / "Historical Data" / "extended_2026-11-12" / "index_daily_pre2019"
SHEETS = {"Nifty100": "Nifty100", "MC100": "MC100", "SC100": "SC100"}
WIN_FIRST = pd.Timestamp("2007-06-29")   # the cash file's first date


def sha(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def main(check_only: bool, last: str) -> int:
    last = pd.Timestamp(last)
    src_i, src_c = PROD / "indices_ohlcv.xlsx", PROD / "TradingDays.xlsx"
    cal_raw = pd.read_excel(src_c, header=None, skiprows=3)[1]
    cal = pd.DatetimeIndex(pd.to_datetime(cal_raw, errors="coerce").dropna()).sort_values()
    cal_cut = cal[cal <= last]
    win = cal_cut[cal_cut >= WIN_FIRST]
    print(f"calendar {src_c.name}: {len(cal)} sessions {cal.min().date()} -> {cal.max().date()}; copied to {last.date()}: {len(cal_cut)}; "
          f"sessions {WIN_FIRST.date()} -> {last.date()}: {len(win)}; duplicates {int(cal.duplicated().sum())}")
    report, frames = {}, {}
    for name, sheet in SHEETS.items():
        d = pd.read_excel(src_i, sheet_name=sheet, parse_dates=["date"])
        d = d.sort_values("date").reset_index(drop=True)
        dd = d[d["date"] <= last]
        w = dd[dd["date"] >= WIN_FIRST]
        wi = pd.DatetimeIndex(w["date"])
        px = w[["open", "high", "low", "close"]]
        flat = (px["open"] == px["high"]) & (px["high"] == px["low"]) & (px["low"] == px["close"])
        mv = w.set_index("date")["close"].pct_change()
        top = mv.reindex(mv.abs().sort_values(ascending=False).index)[:5]
        r = {"first_row": str(d["date"].min().date()), "rows_copied": len(dd), "last_row": str(dd["date"].max().date()),
             "window_rows": len(w), "window_sessions_missing": [str(x.date()) for x in win.difference(wi)],
             "rows_not_on_calendar": [str(x.date()) for x in wi.difference(win)],
             "duplicate_dates": int(dd["date"].duplicated().sum()), "nan_prices_in_window": int(px.isna().sum().sum()),
             "non_positive_prices_in_window": int((px <= 0).sum().sum()),
             "bars_open_high_low_close_all_equal_by_year": {int(y): int(v) for y, v in flat.groupby(w["date"].dt.year).sum().items() if v},
             "bars_with_high_below_low_or_close_outside_range": int(((w["high"] < w["low"]) | (w["close"] > w["high"]) | (w["close"] < w["low"])).sum()),
             "largest_one_day_close_moves": [(str(i.date()), round(float(v), 4)) for i, v in top.items()]}
        report[name] = r
        frames[name] = dd
        print(f"\n{name}: " + json.dumps(r, indent=1))
    if check_only:
        print("\n--check: nothing written.")
        return 0
    if OUT.exists():
        raise SystemExit(f"{OUT} exists; originals are never overwritten")
    OUT.mkdir(parents=True)
    for name, dd in frames.items():
        dd.to_csv(OUT / f"{name}_daily_ohlcv.csv", index=False, date_format="%Y-%m-%d")
    pd.DataFrame({"date": cal_cut}).to_csv(OUT / "nse_trading_days.csv", index=False, date_format="%Y-%m-%d")
    manifest = {"what": "daily index prices and NSE calendar copied verbatim from production (read only), to the end of the pre-2019 window",
                "source_folder": str(PROD), "source_files": {"indices_ohlcv.xlsx": sha(src_i), "TradingDays.xlsx": sha(src_c)},
                "copied_to": str(last.date()), "window_first": str(WIN_FIRST.date()), "checks": report,
                "outputs": {p.name: sha(p) for p in sorted(OUT.iterdir()) if p.is_file()}}
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print("\nwrote", OUT)
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--last", default="2019-01-04")
    a = ap.parse_args()
    sys.exit(main(a.check, a.last))
