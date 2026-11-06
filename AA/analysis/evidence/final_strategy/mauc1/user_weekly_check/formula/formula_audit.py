"""
Formula audit: is the supertrend in the user's MAUc1_weekly_supertrend1.csv.csv the
same FORMULA as production ST.py, with candle construction held fixed?

Method
  1. Take the user's own weekly candles (High, Low, Close, Volume) as given.
  2. Run the ACTUAL vendored production code (vendor_fra/Python_Scripts/ST.py run(),
     sha256-checked against the production manifest) on those candles:
       A "start6": the user's weeks as-is -> ST.py's own start (6th candle, window 2..6)
       B "start5": one dummy week (H=L=C=HL2 of week 1) prepended, so ST.py's 6th candle
                   is the user's 5th; the dummy close lies inside week 1's range, so week 1's
                   TR stays H-L, exactly as in the user's file.
     ST.run gets a synthetic TradingDays.xlsx listing only the user's Fridays, so its
     ISO-week grouping reproduces the user's candles one-to-one (checked cell by cell).
  3. An independent numpy port (literal ST.py rules) for both starts, plus variants
     (rounding fed into the recursion, textbook flip rule, other ATR weightings,
     current-close band reset) to show the test can tell formulas apart.
  4. Compare every column of the user's file; count signal matches.
  5. Rounding: margins |close - band| and ratchet comparisons within 0.1.
  6. Attribution: the same ST.py code on ST.py's own candles (weekIndexDf_250926_W)
     reproduces Master_MAUc1; list the candle differences at the 6 weeks where the
     user's signal and Master's SIGN differ.

Read-only everywhere except this folder. Run from AA/analysis:
    python evidence/final_strategy/mauc1/user_weekly_check/formula/formula_audit.py
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import logging
import os
import sys
import types
from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path(__file__).resolve().parent
ANALYSIS_DIR = OUT.parents[4]                      # .../AA/analysis
AA_DIR = ANALYSIS_DIR.parent
VENDOR = ANALYSIS_DIR / "vendor_fra"
MIRROR = AA_DIR / "Historical Data" / "FRA_MAUc1"
USER_CSV = Path(r"C:\Users\manur\Downloads\MAUc1_weekly_supertrend1.csv.csv")
MASTER = MIRROR / "RSI" / "Final" / "Analysis" / "Master_MAUc1.xlsx"
ST_WEEKS = MIRROR / "RSI" / "Final" / "MAUc1" / "weekIndexDf_250926_W.xlsx"
MANIFEST = MIRROR / "run_manifest.json"
RAW_DAILY = Path(r"C:\Users\manur\Downloads\MAUc1_daily1.csv")
CLEAN_DAILY = ANALYSIS_DIR / "evidence" / "final_strategy" / "mauc1" / "mauc1_daily_clean.csv"
NSE_TD = MIRROR / "Data" / "TradingDays.xlsx"
MUL = 2
TOL = 0.05 + 1e-9                                   # half a unit of the file's 1-dp rounding


def sha(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


# ── import the real production code without writing into the repo ─────────────
def import_production():
    man = json.loads(MANIFEST.read_text())["code_sha256"]
    hashes = {}
    for rel in ["Python_Scripts/ST.py", "Python_Scripts/QuantBacktester.py",
                "Python_Scripts/ProspectTheory.py", "analysis_master.py"]:
        h = sha(VENDOR / rel)
        assert h == man[rel], f"{rel} differs from the production manifest"
        hashes[rel] = h
    sys.dont_write_bytecode = True                  # no __pycache__ inside vendor_fra
    sys.modules.setdefault("eikon", types.ModuleType("eikon"))
    sys.path.insert(0, str(VENDOR))
    logdir = OUT / "logs"
    logdir.mkdir(exist_ok=True)
    orig_fh = logging.FileHandler

    class RedirectFH(orig_fh):                      # QuantBacktester opens two log files at import
        def __init__(self, filename, *a, **k):
            super().__init__(str(logdir / Path(filename).name), *a, **k)

    logging.FileHandler = RedirectFH
    cwd = os.getcwd()
    os.chdir(logdir)
    try:
        import Python_Scripts.QuantBacktester as qd
        import Python_Scripts.ST as ST
        from analysis_master import build_analysis_master
    finally:
        os.chdir(cwd)
        logging.FileHandler = orig_fh
    assert Path(ST.__file__).resolve() == (VENDOR / "Python_Scripts" / "ST.py").resolve()
    return qd, ST, build_analysis_master, hashes


# ── inputs ────────────────────────────────────────────────────────────────────
def load_user() -> pd.DataFrame:
    u = pd.read_csv(USER_CSV, parse_dates=["WeekEnding"]).set_index("WeekEnding")
    assert (u.index.dayofweek == 4).all() and u.index.is_monotonic_increasing
    return u


def write_trading_days(dates: pd.DatetimeIndex, fp: Path):
    """Same layout as production Data/TradingDays.xlsx: 2 banner rows, header _dummy|Date|X."""
    rows = [["Generated", "formula_audit.py", None], ["Source", "user weekly candles (Fridays)", None],
            ["_dummy", "Date", "X"]] + [[0, d.to_pydatetime(), 0] for d in dates]
    pd.DataFrame(rows).to_excel(fp, sheet_name="Sheet1", header=False, index=False)


def run_st_on_candles(ST, build_master, candles: pd.DataFrame, tag: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Real ST.run(scrip,'W',2,True,...) on a one-bar-per-week daily frame whose ISO weeks are the candles."""
    d = OUT / f"st_run_{tag}"
    d.mkdir(exist_ok=True)
    td = d / "TradingDays_synthetic.xlsx"
    write_trading_days(candles.index, td)
    f = "USER"
    mk = lambda col: candles[[col]].rename(columns={col: f}).rename_axis("Date").astype(float)
    scrip = [[mk("Close"), mk("Volume"), mk("High"), mk("Low")], candles.index[0], f]
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        allRebalDf, ok = ST.run(scrip, "W", MUL, True, str(d / "indexDf_W.xlsx"), str(d / "weekIndexDf_W.xlsx"),
                                str(d / "monthIndexDf_W.xlsx"), str(d / "W_allRebal_prev_unused.xlsx"), str(td))
    assert ok
    allRebalDf.to_excel(d / "W_allRebal.xlsx")
    with contextlib.redirect_stdout(buf):
        m = build_master(str(d / "W_allRebal.xlsx"), str(d / "Master_USER.xlsx"), label=tag)
    m = m.set_index(pd.to_datetime(m["Date"]))
    wk = pd.read_excel(d / "weekIndexDf_W.xlsx").set_index("Date")
    return m, wk


# ── independent port (literal ST.py rules) + variants ─────────────────────────
def port(H, L, C, start, *, mul=MUL, n=5, weights="linear", flip="stpy", reset="prev",
         round_atr=None, round_band=None):
    H, L, C = (np.asarray(x, float) for x in (H, L, C))
    N = len(C)
    PC = np.r_[np.nan, C[:-1]]
    TR = np.nanmax(np.vstack([H - L, np.abs(H - PC), np.abs(L - PC)]), axis=0)
    if weights == "linear":
        w = np.arange(1, n + 1) / np.arange(1, n + 1).sum()
    elif weights == "sma":
        w = np.ones(n) / n
    atr = np.full(N, np.nan)
    if weights == "wilder":                            # RMA seeded with SMA of first n
        atr[n - 1] = TR[:n].mean()
        for i in range(n, N):
            atr[i] = (atr[i - 1] * (n - 1) + TR[i]) / n
    elif weights == "ema":                             # alpha 2/(n+1), seeded with SMA
        a = 2 / (n + 1)
        atr[n - 1] = TR[:n].mean()
        for i in range(n, N):
            atr[i] = a * TR[i] + (1 - a) * atr[i - 1]
    else:
        for i in range(n - 1, N):
            atr[i] = (w * TR[i - n + 1:i + 1]).sum()
    if round_atr is not None:
        atr = np.round(atr, round_atr)
    hl2 = 0.5 * H + 0.5 * L
    bub, blb = hl2 + mul * atr, hl2 - mul * atr
    if round_band is not None:
        bub, blb = np.round(bub, round_band), np.round(blb, round_band)
    fub, flb, st = (np.full(N, np.nan) for _ in range(3))
    sig = np.array([None] * N, dtype=object)
    for i in range(start, N):
        if i == start:
            fub[i], flb[i] = bub[i], blb[i]
            st[i] = fub[i]
        else:
            ref = PC[i] if reset == "prev" else C[i]
            fub[i] = bub[i] if (bub[i] < fub[i - 1] or ref > fub[i - 1]) else fub[i - 1]
            flb[i] = blb[i] if (blb[i] > flb[i - 1] or ref < flb[i - 1]) else flb[i - 1]
            if round_band is not None:
                fub[i], flb[i] = round(fub[i], round_band), round(flb[i], round_band)
            pst, pfub, pflb = st[i - 1], fub[i - 1], flb[i - 1]
            c = C[i]
            if pst == pfub and c <= fub[i]:
                st[i] = fub[i]
            elif pst == pfub and c > fub[i]:
                st[i] = flb[i]
            elif pst == pflb and c >= flb[i]:
                st[i] = flb[i]
            elif pst == pflb and (c < fub[i] if flip == "stpy" else c < flb[i]):
                st[i] = fub[i]
            else:
                st[i] = 0.0
        sig[i] = "SELL" if st[i] == fub[i] else "BUY"
    return pd.DataFrame({"TR": TR, "ATR": atr, "HL2": hl2, "BUB": bub, "BLB": blb,
                         "FUB": fub, "FLB": flb, "ST": st, "SIGN": sig})


def compare(u: pd.DataFrame, r: pd.DataFrame) -> dict:
    """u: user file; r: recompute indexed by the same Fridays with TR, ATR, HL2, FUB, FLB, ST, SIGN."""
    r = r.reindex(u.index)
    pairs = {"TR": "TR", "LW_ATR5": "ATR", "HL2": "HL2", "UpperBand": "FUB", "LowerBand": "FLB", "Supertrend": "ST"}
    out = {}
    for uc, rc in pairs.items():
        both = u[uc].notna() & r[rc].notna()
        d = (u.loc[both, uc] - r.loc[both, rc].astype(float)).abs()
        out[uc] = {"rows": int(both.sum()), "max_abs_diff": round(float(d.max()), 6),
                   "rows_gt_0.05": int((d > TOL).sum()),
                   "first_row_gt_0.05": (str(d[d > TOL].index[0].date()) if (d > TOL).any() else None)}
    both = u["Signal"].notna() & r["SIGN"].notna()
    mism = u.index[both & (u["Signal"] != r["SIGN"])]
    out["Signal"] = {"rows": int(both.sum()), "matches": int(both.sum() - len(mism)),
                     "mismatch_weeks": [str(x.date()) for x in mism]}
    return out


def friday(ix: pd.DatetimeIndex) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(ix - pd.to_timedelta(ix.dayofweek - 4, unit="D"))


def main():
    qd, ST, build_master, hashes = import_production()
    vendor_state = {p.name: (p.stat().st_size, p.stat().st_mtime_ns) for p in VENDOR.rglob("*") if p.is_file()}

    u = load_user()
    candles = u[["High", "Low", "Close", "Volume"]].copy()
    res = {"inputs": {"user_csv": str(USER_CSV), "user_csv_sha256": sha(USER_CSV), "user_rows": len(u),
                      "user_first": str(u.index[0].date()), "user_last": str(u.index[-1].date()),
                      "first_user_signal": str(u["Signal"].first_valid_index().date()),
                      "production_code_sha256": hashes, "pandas": pd.__version__, "numpy": np.__version__}}

    # A: ST.py's own start (6th candle)
    mA, wkA = run_st_on_candles(ST, build_master, candles, "start6")
    # B: dummy week in front -> ST.py's 6th candle = user's 5th candle
    hl2_1 = 0.5 * (u["High"].iloc[0] + u["Low"].iloc[0])
    dummy = pd.DataFrame({"High": hl2_1, "Low": hl2_1, "Close": hl2_1, "Volume": 0.0},
                         index=[u.index[0] - pd.Timedelta(days=7)])
    mB, wkB = run_st_on_candles(ST, build_master, pd.concat([dummy, candles]), "start5_dummy")

    # candle passthrough: ST.run's weekly frame must equal the user's candles exactly
    pt = {}
    for tag, wk in (("start6", wkA), ("start5_dummy", wkB)):
        wk = wk.reindex(u.index)
        pt[tag] = {c: float((wk[c] - u[c]).abs().max()) for c in ["High", "Low", "Close", "TR", "AHML"]
                   if c in wk and c in u} | {"TR_vs_user_TR": float((wk["TR"] - u["TR"]).abs().max()),
                                            "AHML_vs_user_HL2": float((wk["AHML"] - u["HL2"]).abs().max())}
    res["st_run_candles_equal_user_candles"] = pt

    def st_frame(m, wk):
        f = pd.DataFrame(index=m.index)
        f["TR"] = wk["TR"].reindex(m.index)
        f["ATR"] = m["EMA_TR"].astype(float)
        f["HL2"] = wk["AHML"].reindex(m.index)
        for c in ["FUB", "FLB", "ST", "BUB", "BLB", "Index"]:
            f[c] = m[c].astype(float)
        f["SIGN"] = m["SIGN"]
        return f

    def full_frame(f, wk):
        g = f.reindex(u.index)
        g["TR"] = wk["TR"].reindex(u.index)          # TR/HL2 exist on every week, signal rows or not
        g["HL2"] = wk["AHML"].reindex(u.index)
        return g

    fA, fB = st_frame(mA, wkA), st_frame(mB, wkB)
    # TR / HL2 compared on every user week, from the ST.run weekly frame
    res["real_ST_run"] = {"start6_ST.py_convention": compare(u, full_frame(fA, wkA)),
                          "start5_user_convention": compare(u, full_frame(fB, wkB))}
    res["real_ST_run"]["start6_ST.py_convention"]["ST_zero_rows"] = int((fA["ST"] == 0).sum())
    res["real_ST_run"]["start5_user_convention"]["ST_zero_rows"] = int((fB["ST"] == 0).sum())
    # start 5 vs start 6 on the same candles: where do they first agree for good?
    j = fA.index.intersection(fB.index)
    d56 = pd.concat([(fA.loc[j, c] - fB.loc[j, c]).abs() for c in ["FUB", "FLB", "ST"]], axis=1).max(axis=1)
    last_diff = d56[d56 > 1e-9].index.max()
    res["start5_vs_start6_same_candles"] = {
        "weeks_compared": len(j), "weeks_any_band_differs": int((d56 > 1e-9).sum()),
        "last_week_band_differs": (str(last_diff.date()) if pd.notna(last_diff) else None),
        "signal_mismatches": int((fA.loc[j, "SIGN"] != fB.loc[j, "SIGN"]).sum())}

    # per-week table
    t = u.copy()
    for tag, f in (("st5", fB), ("st6", fA)):
        f = f.reindex(u.index)
        for c in ["ATR", "BUB", "BLB", "FUB", "FLB", "ST", "SIGN"]:
            t[f"{tag}_{c}"] = f[c]
    t["d5_ATR"] = (t["LW_ATR5"] - t["st5_ATR"].astype(float)).abs()
    t["d5_Upper"] = (t["UpperBand"] - t["st5_FUB"].astype(float)).abs()
    t["d5_Lower"] = (t["LowerBand"] - t["st5_FLB"].astype(float)).abs()
    t["d5_ST"] = (t["Supertrend"] - t["st5_ST"].astype(float)).abs()
    t["sig5_match"] = np.where(t["Signal"].notna(), t["Signal"] == t["st5_SIGN"], np.nan)
    t["sig6_match"] = np.where(t["Signal"].notna() & t["st6_SIGN"].notna(), t["Signal"] == t["st6_SIGN"], np.nan)
    t.to_csv(OUT / "user_candles_real_STpy_recompute.csv", float_format="%.6f")

    # ── port + variants on the user candles ──────────────────────────────────
    H, L, C = u["High"].values, u["Low"].values, u["Close"].values
    variants = {
        "port_stpy_start5": dict(start=4),
        "port_stpy_start6": dict(start=5),
        "port_textbook_flip_close<flb_start5": dict(start=4, flip="textbook"),
        "port_round_ATR_1dp_into_recursion_start5": dict(start=4, round_atr=1),
        "port_round_bands_1dp_into_recursion_start5": dict(start=4, round_band=1),
        "port_round_ATR_and_bands_1dp_start5": dict(start=4, round_atr=1, round_band=1),
        "alt_SMA5_ATR_start5": dict(start=4, weights="sma"),
        "alt_Wilder5_ATR_start5": dict(start=4, weights="wilder"),
        "alt_EMA5_ATR_start5": dict(start=4, weights="ema"),
        "alt_reset_on_current_close_start5": dict(start=4, reset="curr"),
        "alt_multiplier_3_start5": dict(start=4, mul=3),
    }
    vrows = []
    for name, kw in variants.items():
        p = port(H, L, C, **kw).set_index(u.index)
        c = compare(u, p)
        # vs the real ST.run start5 (full precision)
        jj = fB.index.intersection(p.index)
        vrows.append({"variant": name,
                      **{f"{k}_max_abs_diff": v["max_abs_diff"] for k, v in c.items() if k != "Signal"},
                      **{f"{k}_rows_gt_0.05": v["rows_gt_0.05"] for k, v in c.items() if k != "Signal"},
                      "signal_rows": c["Signal"]["rows"], "signal_matches": c["Signal"]["matches"],
                      "signal_mismatch_weeks": ";".join(c["Signal"]["mismatch_weeks"]),
                      "sig_mismatch_vs_real_ST_start5": int((p.loc[jj, "SIGN"] != fB.loc[jj, "SIGN"]).sum()),
                      "max_abs_ST_vs_real_ST_start5": float((p.loc[jj, "ST"] - fB.loc[jj, "ST"]).abs().max())})
    vt = pd.DataFrame(vrows)
    vt.to_csv(OUT / "variant_tests_user_candles.csv", index=False)
    res["port_and_variants"] = vt.set_index("variant")[["signal_matches", "signal_rows", "Supertrend_max_abs_diff",
                                                        "UpperBand_max_abs_diff", "LowerBand_max_abs_diff",
                                                        "LW_ATR5_max_abs_diff", "sig_mismatch_vs_real_ST_start5"]].to_dict("index")

    # textbook flip vs ST.py's literal flip: weeks where the branch outcome could differ
    f = fB
    pst, pfub, pflb = f["ST"].shift(), f["FUB"].shift(), f["FLB"].shift()
    buy_prev = pst == pflb
    brk = buy_prev & (f["Index"] < f["FLB"])
    res["flip_rule"] = {"weeks_prev_BUY_and_close_below_FLB": int(brk.sum()),
                        "of_which_close_not_below_FUB (literal ST.py != textbook)": int((brk & ~(f["Index"] < f["FUB"])).sum()),
                        "weeks_FLB_above_FUB_any_state": int((f["FLB"] > f["FUB"]).sum())}

    # ── rounding: how close do comparisons get? ──────────────────────────────
    close = f["Index"]
    prev_close = close.shift()
    rows = []
    for i, dt in enumerate(f.index):
        if i == 0:
            continue
        pv = f.index[i - 1]
        state_prev = "SELL" if f.at[pv, "ST"] == f.at[pv, "FUB"] else "BUY"
        checks = {
            "flip_test close-FUB (prev SELL)": close[dt] - f.at[dt, "FUB"] if state_prev == "SELL" else np.nan,
            "flip_test close-FLB (prev BUY)": close[dt] - f.at[dt, "FLB"] if state_prev == "BUY" else np.nan,
            "ratchet BUB-pFUB": f.at[dt, "BUB"] - f.at[pv, "FUB"],
            "ratchet pclose-pFUB": prev_close[dt] - f.at[pv, "FUB"],
            "ratchet BLB-pFLB": f.at[dt, "BLB"] - f.at[pv, "FLB"],
            "ratchet pclose-pFLB": prev_close[dt] - f.at[pv, "FLB"],
        }
        for k, v in checks.items():
            if pd.notna(v):
                rows.append({"week": dt.date(), "state_prev": state_prev, "comparison": k, "margin": v})
    mg = pd.DataFrame(rows)
    mg["abs"] = mg["margin"].abs()
    near = mg[mg["abs"] < 0.1 + 1e-9].sort_values("abs")
    near.to_csv(OUT / "rounding_near_ties_user_candles.csv", index=False, float_format="%.6f")
    flip_m = mg[mg["comparison"].str.startswith("flip_test")]
    res["rounding"] = {
        "comparisons_checked": len(mg),
        "min_abs_flip_margin": round(float(flip_m["abs"].min()), 6),
        "flip_margin_week": str(flip_m.loc[flip_m["abs"].idxmin(), "week"]),
        "flip_margins_below_0.1": int((flip_m["abs"] < 0.1).sum()),
        "flip_margins_below_1.0": int((flip_m["abs"] < 1.0).sum()),
        "ratchet_margins_below_0.1": int(((~mg["comparison"].str.startswith("flip_test")) & (mg["abs"] < 0.1)).sum()),
        "exact_ties_(<1e-6)": int((mg["abs"] < 1e-6).sum()),
    }
    # The printed Supertrend vs printed Close (someone re-deriving from the file)
    printed = u.dropna(subset=["Signal"])
    res["printed_file_consistency"] = {
        "Signal==BUY iff Supertrend==LowerBand": int(((printed["Supertrend"] == printed["LowerBand"]) == (printed["Signal"] == "BUY")).sum()),
        "rows": len(printed),
        "min_abs_Close_minus_printed_Supertrend": float((printed["Close"] - printed["Supertrend"]).abs().min()),
    }

    # ── same code on ST.py's own candles -> Master, and the 6 signal differences ──
    sw = pd.read_excel(ST_WEEKS).set_index("Date")
    master = pd.read_excel(MASTER)
    master["Date"] = pd.to_datetime(master["Date"])
    master = master.set_index("Date")
    p6 = port(sw["High"].values, sw["Low"].values, sw["Close"].values, start=5).set_index(sw.index)
    jm = master.index
    res["port_on_STpy_candles_vs_Master"] = {
        "rows": len(jm),
        "max_abs_ST": float((p6.loc[jm, "ST"] - master["ST"]).abs().max()),
        "max_abs_EMA_TR": float((p6.loc[jm, "ATR"] - master["EMA_TR"]).abs().max()),
        "sign_mismatches": int((p6.loc[jm, "SIGN"] != master["SIGN"]).sum())}

    mf = master.copy()
    mf.index = friday(mf.index)
    swf = sw.copy()
    swf["label"] = swf.index
    swf.index = friday(swf.index)
    common = u.index.intersection(mf.index)
    sd = common[(u.loc[common, "Signal"] != mf.loc[common, "SIGN"])]
    res["user_vs_Master"] = {"common_weeks": len(common), "sign_matches": int(len(common) - len(sd)),
                             "diff_weeks": [str(x.date()) for x in sd],
                             "user_weeks_not_in_Master": [str(x.date()) for x in u.index.difference(mf.index)],
                             "weeks_close_differs": int((u.loc[common, "Close"] != swf.loc[common, "Close"]).sum()),
                             "weeks_high_differs": int((u.loc[common, "High"] != swf.loc[common, "High"]).sum()),
                             "weeks_low_differs": int((u.loc[common, "Low"] != swf.loc[common, "Low"]).sum())}
    # candle deltas in the run-up to each divergent episode (the 8 weeks before and during)
    cw = u.index.intersection(swf.index)
    cand = pd.DataFrame({"user_High": u.loc[cw, "High"], "st_High": swf.loc[cw, "High"],
                         "user_Low": u.loc[cw, "Low"], "st_Low": swf.loc[cw, "Low"],
                         "user_Close": u.loc[cw, "Close"], "st_Close": swf.loc[cw, "Close"],
                         "st_label": swf.loc[cw, "label"],
                         "user_ATR": u.loc[cw, "LW_ATR5"], "st_ATR": mf["EMA_TR"].reindex(cw),
                         "user_Upper": u.loc[cw, "UpperBand"], "st_FUB": mf["FUB"].reindex(cw),
                         "user_Lower": u.loc[cw, "LowerBand"], "st_FLB": mf["FLB"].reindex(cw),
                         "user_ST": u.loc[cw, "Supertrend"], "st_ST": mf["ST"].reindex(cw),
                         "user_Signal": u.loc[cw, "Signal"], "st_SIGN": mf["SIGN"].reindex(cw)})
    cand["candle_differs"] = (cand["user_High"] != cand["st_High"]) | (cand["user_Low"] != cand["st_Low"]) | (cand["user_Close"] != cand["st_Close"])
    win = pd.Series(False, index=cand.index)
    for w in sd:
        k = cand.index.get_loc(w)
        win.iloc[max(0, k - 8):k + 1] = True
    cand[win].to_csv(OUT / "signal_diff_weeks_candle_context.csv", float_format="%.4f")
    cand[cand["candle_differs"]].to_csv(OUT / "all_weeks_candle_differs_user_vs_STpy.csv", float_format="%.4f")
    res["candle_context"] = {str(w.date()): {"candle_differs_this_week": bool(cand.at[w, "candle_differs"]),
                                             "user_close": float(cand.at[w, "user_Close"]),
                                             "user_upper": float(cand.at[w, "user_Upper"]), "user_lower": float(cand.at[w, "user_Lower"]),
                                             "st_close": float(cand.at[w, "st_Close"]), "st_FUB": round(float(cand.at[w, "st_FUB"]), 4),
                                             "st_FLB": round(float(cand.at[w, "st_FLB"]), 4)} for w in sd}

    # ── secondary: is the user's candle = all MCX sessions bucketed W-FRI? ──────
    raw = pd.read_csv(RAW_DAILY, parse_dates=["Date"]).set_index("Date").sort_index()
    raw.columns = [c.lower() for c in raw.columns]
    hyp = {}
    for nm, dd in (("raw_export", raw), ("cleaned", pd.read_csv(CLEAN_DAILY, parse_dates=["date"]).set_index("date").sort_index())):
        dd = dd.dropna(subset=["close"])
        r = dd.resample("W-FRI").agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna(subset=["close"])
        k = u.index.intersection(r.index)
        hyp[nm] = {"weeks_compared": len(k), "user_weeks_missing": len(u.index.difference(r.index)),
                   **{f"{c}_mismatch_weeks": int((u.loc[k, c.capitalize()] != r.loc[k, c]).sum())
                      for c in ["open", "high", "low", "close", "volume"]}}
        mis = k[(u.loc[k, "High"] != r.loc[k, "high"]) | (u.loc[k, "Low"] != r.loc[k, "low"]) |
                (u.loc[k, "Close"] != r.loc[k, "close"])]
        hyp[nm]["HLC_mismatch_weeks_list"] = [str(x.date()) for x in mis][:20]
    res["candle_hypothesis_WFRI_all_MCX_sessions"] = hyp

    # vendor_fra untouched
    after = {p.name: (p.stat().st_size, p.stat().st_mtime_ns) for p in VENDOR.rglob("*") if p.is_file()}
    res["vendor_fra_unchanged"] = after == vendor_state
    (OUT / "summary.json").write_text(json.dumps(res, indent=2, default=str))
    print(json.dumps(res, indent=2, default=str))


if __name__ == "__main__":
    main()
