# -*- coding: utf-8 -*-
"""
Backtest impact of the user's MAUc1 weekly supertrend file on the final strategy.

    python run_impact.py stpy   # ST.py signal (unpatched mauc1_st), outputs -> impact/stpy/   (reproduction check)
    python run_impact.py user   # user's file as the gold signal,     outputs -> impact/user/

Run from AA/analysis so the repo imports resolve. Imports final_strategy as F,
redirects F.OUT (the only write location in F.main) to a subfolder here, and
installs a write guard that raises on any file write outside this folder.

User mode: F.mauc1_st is wrapped. The ST.py table it returns is kept (same
index = ST.py week labels, same columns) but 'SIGN'/'signal' are replaced by the
user's Signal. Each user row (always a Friday) is relabelled to the ST.py week
label of the SAME ISO week (Mon-Sun), which is the last NSE session of that
week, i.e. the review date the backtest uses. So gold_at(gs, review) - latest
label <= review - reads the user's row of the review's own week, including
weeks whose review is a Thursday/Wednesday (NSE-holiday Friday) or a Sat/Sun
special session. User weeks with no ST.py label (the partial 2026-10-02 week)
are labelled by the last NSE trading day of their ISO week (TradingDays.xlsx).
"""
from __future__ import annotations

import builtins
import os
import pathlib
import sys

import numpy as np
import pandas as pd

HERE = pathlib.Path(__file__).resolve().parent
USER_CSV = pathlib.Path(r"C:\Users\manur\Downloads\MAUc1_weekly_supertrend1.csv.csv")
TRADING_DAYS = pathlib.Path(r"C:\Users\manur\Repos\wm-research\AA\Historical Data\FRA_MAUc1\Data\TradingDays.xlsx")


# ── write guard: nothing outside HERE may be written ───────────────────────
def _inside(p) -> bool:
    try:
        rp = pathlib.Path(os.fsdecode(p)).resolve()
    except TypeError:
        return True                      # buffers / file objects
    return str(rp).lower().startswith(str(HERE).lower())


_open = builtins.open


def _guarded_open(file, mode="r", *a, **k):
    if isinstance(file, (str, bytes, os.PathLike)) and any(c in mode for c in "wax+") and not _inside(file):
        raise PermissionError(f"write blocked outside impact folder: {file}")
    return _open(file, mode, *a, **k)


def _guard_method(cls, name):
    orig = getattr(cls, name)

    def f(self, path=None, *a, **k):
        if path is not None and isinstance(path, (str, bytes, os.PathLike)) and not _inside(path):
            raise PermissionError(f"{name} blocked outside impact folder: {path}")
        return orig(self, path, *a, **k)
    setattr(cls, name, f)


def install_guard():
    builtins.open = _guarded_open
    for cls in (pd.DataFrame, pd.Series):
        for nm in ("to_csv", "to_excel", "to_parquet", "to_pickle", "to_json"):
            if nm in cls.__dict__ or hasattr(cls, nm):
                _guard_method(cls, nm)
    for nm in ("write_text", "write_bytes"):
        orig = getattr(pathlib.Path, nm)

        def f(self, *a, _orig=orig, _nm=nm, **k):
            if not _inside(self):
                raise PermissionError(f"{_nm} blocked outside impact folder: {self}")
            return _orig(self, *a, **k)
        setattr(pathlib.Path, nm, f)


# ── the user's signal, relabelled to ST.py week labels ─────────────────────
def iso_key(ix) -> pd.Index:
    ic = pd.DatetimeIndex(ix).isocalendar()
    return pd.Index(list(zip(ic["year"].astype(int), ic["week"].astype(int))))


def user_table(st_labels: pd.DatetimeIndex) -> pd.DataFrame:
    u = pd.read_csv(USER_CSV, parse_dates=["WeekEnding"])
    assert (u["WeekEnding"].dt.dayofweek == 4).all(), "user labels are not all Fridays"
    assert u["WeekEnding"].is_unique
    lab_by_iso = pd.Series(st_labels, index=iso_key(st_labels))
    assert lab_by_iso.index.is_unique, "two ST.py labels in one ISO week"
    td = pd.read_excel(TRADING_DAYS, header=None, skiprows=3)[1]
    td = pd.DatetimeIndex(pd.to_datetime(td, errors="coerce").dropna()).sort_values()
    nse_by_iso = pd.Series(td, index=iso_key(td)).groupby(level=[0, 1]).max()
    k = iso_key(u["WeekEnding"])
    lab = []
    src = []
    for key, fri in zip(k, u["WeekEnding"]):
        if key in lab_by_iso.index:
            lab.append(lab_by_iso.loc[key]); src.append("st_py_label")
        elif key in nse_by_iso.index:
            lab.append(nse_by_iso.loc[key]); src.append("nse_last_day")
        else:
            lab.append(fri); src.append("friday")
    u["label"] = pd.DatetimeIndex(lab)
    u["label_source"] = src
    u["label_minus_friday_days"] = (u["label"] - u["WeekEnding"]).dt.days
    assert u["label"].is_unique
    return u.set_index("label").sort_index()


def patched_mauc1_st_factory(F):
    orig = F.mauc1_st

    def mauc1_st_user():
        t, daily, dc = orig()
        u = user_table(t.index)
        idx = t.index.union(u.index)
        t = t.reindex(idx)
        t.index.name = "review"
        t["stpy_SIGN"] = t["SIGN"]
        t["stpy_signal"] = t["signal"]
        ren = {"WeekEnding": "user_week_ending", "Open": "user_open", "High": "user_high", "Low": "user_low",
               "Close": "user_close", "Volume": "user_volume", "TR": "user_TR", "LW_ATR5": "user_LW_ATR5",
               "HL2": "user_HL2", "UpperBand": "user_UpperBand", "LowerBand": "user_LowerBand",
               "Supertrend": "user_Supertrend", "Signal": "user_Signal", "label_source": "user_label_source",
               "label_minus_friday_days": "user_label_minus_friday_days"}
        uu = u.rename(columns=ren)
        for c in ren.values():
            t[c] = uu[c].reindex(idx)
        t["SIGN"] = t["user_Signal"]
        t["signal"] = t["user_Signal"].map({"BUY": 1.0, "SELL": 0.0})
        uu.to_csv(F.OUT / "user_signal_relabelled.csv")
        return t, daily, dc
    return mauc1_st_user


def main(mode: str, sub: str | None = None):
    assert mode in ("stpy", "user")
    out = HERE / (sub or mode)
    out.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(pathlib.Path.cwd()))
    import final_strategy as F                      # module import: OUT.mkdir on the existing folder only
    install_guard()
    F.OUT = out                                     # every write in F.main goes through OUT
    # MAUC1_CSV (an input) was bound at import to the real evidence file - left as is.
    if mode == "user":
        F.mauc1_st = patched_mauc1_st_factory(F)
    F.main()
    print("done", mode, "->", out)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
