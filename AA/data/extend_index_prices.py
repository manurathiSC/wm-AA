"""Extend the daily Nifty 100, Midcap 100 and Smallcap 100 prices (D25, which ends 2019-01-04) to the end of
T08's / T14's W2 window, as candidate data for T15's 2019-2026 window (Manu, chat 2026-11-25: "approved" to extract).

    python data/extend_index_prices.py --check                 # prints every check, writes nothing
    python data/extend_index_prices.py                         # writes the candidate folder
    <venv with pandas 2.2.3 / numpy 1.26.4> python data/extend_index_prices.py --signal-check
                                                               # recomputes the D03 signals from D25 + the candidate

Source: the same production file D25 was copied from (data/extract_index_prices.py), read only:
  Friday Rebalance Automation/Data/indices_ohlcv.xlsx, sheets Nifty100, MC100, SC100 (date, open, high, low, close, volume).
The production file has changed since D25 (sha 51a5af85...) and since the D03 recompute (sha c6c79a48...), so:
  (1) every D25 row is compared with the production row of the same date (all six columns, exact); any difference STOPS;
      Smallcap 100 rows before 2011-10-03 are dropped as soon as they are loaded and never compared (rule 7);
  (2) the new rows 2019-01-07 -> --last are checked on their own (calendar coverage against the D17-extended sessions of
      W2, gaps, NaN, non-positive, flat bars, closes outside the range, largest moves, daily SD against D25's);
  (3) the close on every weekly D03 row (column Index of the approved extended Master files) equals the candidate close;
  (4) --signal-check: the vendored production ST.py + analysis_master.py (W, multiplier 2, newRun) run on D25 up to
      2018-12-31 spliced with the candidate from 2019-01-01 (Smallcap 100 from 2011-10-03, as D03b) reproduce the
      approved D03 extended Master files (SIGN and every numeric column) on every shared week (Smallcap 100 from
      2011-11-25). Needs the production pins.
Output (a candidate, off-limits until Manu approves it and data/APPROVED_DATA.md lists it):
  Historical Data/extended_2026-11-25/index_daily_2019_2026/{Nifty100,MC100,SC100}_daily_ohlcv.csv
  rows dated 2019-01-01 -> --last only (W1 keeps reading D25; nothing restricted is copied), plus manifest.json.
Rows are copied verbatim (no cleaning, no fill, no adjustment). Price indices: no dividends.
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
PROD = Path(r"G:\.shortcut-targets-by-id\0B7f_UMMZHM_JNXljMVVXY2VPcHM\Investment Research_N\Shubham_Shreshtha"
            r"\Friday Rebalance Automation\Data")
D25 = AA / "Historical Data" / "extended_2026-11-12" / "index_daily_pre2019"
D03 = AA / "Historical Data" / "extended_2026-10-30" / "Master"
D17 = AA / "Historical Data" / "extended_2026-11-06" / "published_nav" / "SCMO_0003.csv"
OUT = AA / "Historical Data" / "extended_2026-11-25" / "index_daily_2019_2026"
NAMES = ["Nifty100", "MC100", "SC100"]
COLS = ["open", "high", "low", "close", "volume"]
NEW_FIRST = pd.Timestamp("2019-01-01")      # first row written (overlaps D25 on 2019-01-01 -> 2019-01-04)
EXT_FIRST = pd.Timestamp("2019-01-05")      # first row D25 does not have
W2 = (pd.Timestamp("2019-01-02"), pd.Timestamp("2026-10-30"))
SC100_FROM = pd.Timestamp("2011-10-03")     # rule 7: no Smallcap 100 price row before this is read or used
SC100_SIGNAL_FROM = pd.Timestamp("2011-11-25")
CMP = ["Index", "ST", "FUB", "FLB", "BUB", "BLB", "EMA_Close", "EMA_TR", "Long_Weight"]


def sha(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def restrict(name: str, d: pd.DataFrame) -> pd.DataFrame:
    return d[d["date"] >= SC100_FROM].reset_index(drop=True) if name == "SC100" else d


def load_prod() -> dict[str, pd.DataFrame]:
    out = {}
    for n in NAMES:
        d = pd.read_excel(PROD / "indices_ohlcv.xlsx", sheet_name=n, parse_dates=["date"])
        out[n] = restrict(n, d.sort_values("date", kind="stable").reset_index(drop=True))
    return out


def load_d25() -> dict[str, pd.DataFrame]:
    return {n: restrict(n, pd.read_csv(D25 / f"{n}_daily_ohlcv.csv", parse_dates=["date"])) for n in NAMES}


def overlap_check(prod: pd.DataFrame, old: pd.DataFrame) -> dict:
    p, o = prod.set_index("date"), old.set_index("date")
    both = o.index.intersection(p.index)
    diff = {c: float((p.loc[both, c].astype(float) - o.loc[both, c].astype(float)).abs().max()) for c in COLS}
    return {"d25_rows": len(o), "shared": len(both), "max_abs_diff": diff,
            "dates_only_in_d25": [str(x.date()) for x in o.index.difference(p.index)],
            "dates_only_in_production_up_to_d25_end": [str(x.date()) for x in p.index[p.index <= o.index.max()].difference(o.index)],
            "pass": all(v == 0.0 for v in diff.values()) and len(o.index.difference(p.index)) == 0}


def new_row_checks(d: pd.DataFrame, hist: pd.DataFrame, cal: pd.DatetimeIndex) -> dict:
    w = d[d["date"] >= EXT_FIRST]
    wi = pd.DatetimeIndex(w["date"])
    px = w[["open", "high", "low", "close"]]
    flat = (px["open"] == px["high"]) & (px["high"] == px["low"]) & (px["low"] == px["close"])
    mv = w.set_index("date")["close"].pct_change()
    top = mv.reindex(mv.abs().sort_values(ascending=False).index)[:5]
    gaps = wi.to_series().diff().dt.days
    w2cal = cal[(cal >= W2[0]) & (cal <= W2[1])]
    allw = pd.DatetimeIndex(d["date"])
    bad = (w["high"] < w["low"]) | (w["close"] > w["high"]) | (w["close"] < w["low"]) | (w["open"] > w["high"]) | (w["open"] < w["low"])
    h = hist.set_index("date")["close"].pct_change()
    return {"new_rows": len(w), "first_new": str(wi.min().date()), "last_new": str(wi.max().date()),
            "duplicate_dates": int(d["date"].duplicated().sum()), "nan_prices": int(px.isna().sum().sum()),
            "non_positive_prices": int((px <= 0).sum().sum()),
            "flat_bars_by_year": {int(y): int(v) for y, v in flat.groupby(w["date"].dt.year).sum().items() if v},
            "bars_open_or_close_outside_high_low": [str(x.date()) for x in w.loc[bad, "date"]],
            "gaps_over_5_calendar_days": [(str(a.date()), int(g)) for a, g in gaps[gaps > 5].items()],
            "w2_d17_sessions": len(w2cal),
            "w2_d17_sessions_without_a_bar": [str(x.date()) for x in w2cal.difference(allw)],
            "w2_bars_not_d17_sessions": [str(x.date()) for x in allw[(allw >= W2[0]) & (allw <= W2[1])].difference(w2cal)],
            "largest_one_day_close_moves": [(str(i.date()), round(float(v), 4)) for i, v in top.items()],
            "daily_close_sd_new_rows": round(float(mv.std()), 5),
            "daily_close_sd_d25_history": round(float(h.std()), 5),
            "volume_zero_share_new_rows": round(float((w["volume"] == 0).mean()), 3)}


def weekly_close_check(name: str, d: pd.DataFrame) -> dict:
    m = pd.read_excel(D03 / f"Master_{name}.xlsx", parse_dates=["Date"]).set_index("Date")
    m = m[m.index >= NEW_FIRST]
    c = d.set_index("date")["close"]
    both = m.index.intersection(c.index)
    diff = (m.loc[both, "Index"].astype(float) - c.loc[both].astype(float)).abs()
    return {"d03_weeks_from_2019": len(m), "weeks_with_a_bar": len(both),
            "d03_weeks_without_a_bar": [str(x.date()) for x in m.index.difference(c.index)],
            "max_abs_diff_index_vs_close": float(diff.max()), "weeks_differing": int((diff > 1e-9).sum()),
            "pass": len(both) == len(m) and float(diff.max()) <= 1e-9}


def signal_check(cand: dict[str, pd.DataFrame], d25: dict[str, pd.DataFrame]) -> list[dict]:
    """D25 (to 2018-12-31) + candidate (from 2019-01-01) through the vendored production supertrend, vs approved D03."""
    sys.path.insert(0, str(AA / "analysis"))
    import mauc1_st_production as mp
    for rel in mp.VENDORED:
        if sha(mp.PROD / rel) != sha(mp.VENDOR / rel):
            raise SystemExit(f"STOP: vendored {rel} differs from production")
    qd, run, build_master = mp.import_production()
    cal = mp.PROD / "Data" / "TradingDays.xlsx"
    master = {n: pd.concat([d25[n][d25[n]["date"] < NEW_FIRST], cand[n]], ignore_index=True) for n in NAMES}
    idx = mp._master_to_wide(master, NAMES)
    tmp = Path(tempfile.mkdtemp(prefix="idx_signal_check_"))
    out = []
    for n in NAMES:
        dd = tmp / n
        dd.mkdir()
        df, _ = mp.run_quiet(run, mp.scrip_for(qd, idx, n, cal), dd, "chk", cal)
        df.to_excel(dd / "W_allRebal.xlsx")
        build_master(str(dd / "W_allRebal.xlsx"), str(dd / f"Master_{n}.xlsx"), label=n)
        m = pd.read_excel(dd / f"Master_{n}.xlsx", parse_dates=["Date"]).set_index("Date")
        old = pd.read_excel(D03 / f"Master_{n}.xlsx", parse_dates=["Date"]).set_index("Date")
        if n == "SC100":
            old = old[old.index >= SC100_SIGNAL_FROM]
        both = old.index.intersection(m.index)
        both_w2 = both[both >= NEW_FIRST]
        r = {"index": n, "d03_rows_compared": len(old), "shared": len(both), "shared_from_2019": len(both_w2),
             "d03_dates_not_recomputed": [str(x.date()) for x in old.index.difference(m.index)],
             "sign_mismatches": int((old.loc[both, "SIGN"] != m.loc[both, "SIGN"]).sum()),
             "sign_mismatch_dates": [str(x.date()) for x in both[old.loc[both, "SIGN"].values != m.loc[both, "SIGN"].values]][:20],
             "max_abs_diff": {c: float((old.loc[both, c].astype(float) - m.loc[both, c].astype(float)).abs().max()) for c in CMP}}
        r["pass"] = r["sign_mismatches"] == 0 and not r["d03_dates_not_recomputed"] and max(r["max_abs_diff"].values()) < 1e-6
        out.append(r)
        print(json.dumps(r))
    return out


def main(mode: str, last: str) -> int:
    last = pd.Timestamp(last)
    src = PROD / "indices_ohlcv.xlsx"
    print(f"source {src}\n  sha256 {sha(src)}  (D25 was copied from 51a5af85..., D03 recomputed from c6c79a48...)")
    prod, d25 = load_prod(), load_d25()
    cal = pd.DatetimeIndex(pd.read_csv(D17, parse_dates=["_id.date"])["_id.date"]).sort_values()
    report, cand, ok = {}, {}, True
    for n in NAMES:
        ov = overlap_check(prod[n], d25[n])
        cand[n] = prod[n][(prod[n]["date"] >= NEW_FIRST) & (prod[n]["date"] <= last)].reset_index(drop=True)
        r = {"overlap_with_d25": ov, "new_rows": new_row_checks(cand[n], d25[n], cal),
             "weekly_close_vs_d03": weekly_close_check(n, cand[n])}
        ok &= ov["pass"] and r["weekly_close_vs_d03"]["pass"]
        report[n] = r
        print(f"\n{n}: " + json.dumps(r, indent=1))
    if not ok:
        print("\nSTOP: an overlap or weekly-close check failed; nothing written.")
        return 1
    if mode == "signal":
        res = signal_check(cand, d25)
        print("\nsignal check:", "PASS" if all(r["pass"] for r in res) else "FAIL")
        return 0 if all(r["pass"] for r in res) else 1
    if mode == "check":
        print("\n--check: nothing written.")
        return 0
    if OUT.exists():
        raise SystemExit(f"{OUT} exists; originals are never overwritten")
    OUT.mkdir(parents=True)
    for n in NAMES:
        cand[n].to_csv(OUT / f"{n}_daily_ohlcv.csv", index=False, date_format="%Y-%m-%d")
    manifest = {"what": "daily index prices copied verbatim from production (read only), 2019-01-01 to --last, extending D25",
                "source": str(src), "source_sha256": sha(src), "rows_from": str(NEW_FIRST.date()), "copied_to": str(last.date()),
                "d25_folder": str(D25.relative_to(AA)), "checks": report,
                "outputs": {p.name: sha(p) for p in sorted(OUT.iterdir()) if p.is_file()}}
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print("\nwrote", OUT)
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--check", action="store_true")
    g.add_argument("--signal-check", action="store_true")
    ap.add_argument("--last", default="2026-11-04")
    ap.add_argument("--out", default=None, help="output folder relative to AA/ (default: the D25c folder); refuses to overwrite")
    a = ap.parse_args()
    if a.out:
        OUT = AA / a.out
    sys.exit(main("check" if a.check else "signal" if a.signal_check else "write", a.last))
