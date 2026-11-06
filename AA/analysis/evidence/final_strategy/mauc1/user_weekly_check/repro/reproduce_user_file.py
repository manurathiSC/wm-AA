# -*- coding: utf-8 -*-
"""
Rebuild the user's MAUc1_weekly_supertrend1.csv.csv from the raw daily export
and compare every column of every row.

Read-only on all inputs. Writes only into this folder:
  repro_user_weekly.csv       - the rebuilt file (same columns, same rounding)
  repro_row_diffs.csv         - row-by-row user vs rebuilt, per column, with diffs
  repro_variant_scores.csv    - how alternative constructions score against the user file
  repro_vs_stpy_signals.csv   - user signal vs ST.py SIGN per week (Friday-mapped), with the
                                decomposition runs (same formula on ST.py candles, start shift)
Run from C:\\Users\\manur\\Repos\\wm-research\\AA\\analysis:
  python evidence/final_strategy/mauc1/user_weekly_check/repro/reproduce_user_file.py
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path(__file__).resolve().parent
USER = Path(r"C:\Users\manur\Downloads\MAUc1_weekly_supertrend1.csv.csv")
RAW = Path(r"C:\Users\manur\Downloads\MAUc1_daily1.csv")
CLEAN = Path(r"C:\Users\manur\Repos\wm-research\AA\analysis\evidence\final_strategy\mauc1\mauc1_daily_clean.csv")
FRA = Path(r"C:\Users\manur\Repos\wm-research\AA\Historical Data\FRA_MAUc1")
MASTER = FRA / r"RSI\Final\Analysis\Master_MAUc1.xlsx"
STPY_WEEKS = FRA / r"RSI\Final\MAUc1\weekIndexDf_250926_W.xlsx"

MUL = 2.0
N = 5
INT_COLS = ["Open", "High", "Low", "Close", "Volume", "TR"]
DP1_COLS = ["LW_ATR5", "HL2", "UpperBand", "LowerBand", "Supertrend"]
COLS = INT_COLS + DP1_COLS


# ----------------------------------------------------------------------------- inputs
def load_user() -> pd.DataFrame:
    return pd.read_csv(USER, parse_dates=["WeekEnding"]).set_index("WeekEnding")


def load_raw() -> pd.DataFrame:
    d = pd.read_csv(RAW, parse_dates=["Date"]).set_index("Date").sort_index()
    d.columns = [c.lower() for c in d.columns]
    return d


def load_clean() -> pd.DataFrame:
    return pd.read_csv(CLEAN, parse_dates=["date"]).set_index("date").sort_index()


# ----------------------------------------------------------------------------- candles
def fill_hl_from_prices(d: pd.DataFrame) -> pd.DataFrame:
    """Daily high/low = max/min over whatever of O/H/L/C the day has.
    Only changes the close-only sessions (2021-10-04, 2025-01-02, 2026-02-04),
    2020-04-14 (no high) and 2023-10-16 (close above high). Open is NOT filled."""
    d = d.copy()
    px = d[["open", "high", "low", "close"]]
    d["high"] = px.max(axis=1)
    d["low"] = px.min(axis=1)
    return d


def weekly_resample(d: pd.DataFrame, rule: str = "W-FRI") -> pd.DataFrame:
    """Calendar-week candles over every MCX session (weekend sessions included).
    pandas skips NaN: Open = first non-missing open, Close = last non-missing close,
    Volume = sum of available volumes (rows without a close still count)."""
    r = d.resample(rule)
    w = pd.DataFrame({
        "Open": r["open"].first(), "High": r["high"].max(), "Low": r["low"].min(),
        "Close": r["close"].last(), "Volume": r["volume"].sum(min_count=1),
    }).dropna(how="all")
    if rule != "W-FRI":  # relabel to the Friday of that week for comparison
        w.index = w.index - pd.to_timedelta((w.index.dayofweek - 4) % 7, unit="D")
    w.index.name = "WeekEnding"
    return w


# ----------------------------------------------------------------------------- indicator
def supertrend(w: pd.DataFrame, start_candle: int = 5, round_atr: bool = False,
               round_bands: bool = False) -> pd.DataFrame:
    """start_candle is 1-based: 5 = first ATR window (user file), 6 = ST.py."""
    w = w.copy()
    pc = w["Close"].shift()
    hl = w["High"] - w["Low"]
    tr = pd.concat([hl, (w["High"] - pc).abs(), (w["Low"] - pc).abs()], axis=1).max(axis=1)
    tr.iloc[0] = hl.iloc[0]
    wts = np.arange(1, N + 1) / (N * (N + 1) / 2)  # 1/15 .. 5/15, newest heaviest
    atr = tr.rolling(N).apply(lambda s: float((s * wts).sum()), raw=True)
    if round_atr:
        atr = atr.round(1)
    hl2 = (w["High"] + w["Low"]) / 2
    bub = (hl2 + MUL * atr).to_numpy()
    blb = (hl2 - MUL * atr).to_numpy()
    if round_bands:
        bub, blb = np.round(bub, 1), np.round(blb, 1)
    n = len(w)
    fub = np.full(n, np.nan); flb = np.full(n, np.nan); st = np.full(n, np.nan)
    sig = np.array([np.nan] * n, dtype=object)
    close = w["Close"].to_numpy(); pcl = pc.to_numpy()
    s0 = start_candle - 1
    for i in range(s0, n):
        if i == s0:
            fub[i], flb[i], st[i] = bub[i], blb[i], bub[i]          # starts SELL on the upper band
        else:
            fub[i] = bub[i] if (bub[i] < fub[i - 1] or pcl[i] > fub[i - 1]) else fub[i - 1]
            flb[i] = blb[i] if (blb[i] > flb[i - 1] or pcl[i] < flb[i - 1]) else flb[i - 1]
            if st[i - 1] == fub[i - 1]:                              # was SELL
                st[i] = fub[i] if close[i] <= fub[i] else flb[i]
            else:                                                    # was BUY
                st[i] = flb[i] if close[i] >= flb[i] else fub[i]
        sig[i] = "BUY" if st[i] == flb[i] else "SELL"
    out = w[["Open", "High", "Low", "Close", "Volume"]].copy() if "Open" in w else w[["High", "Low", "Close"]].copy()
    out["TR"] = tr
    out["LW_ATR5"] = atr
    out["HL2"] = hl2
    out["UpperBand"] = fub
    out["LowerBand"] = flb
    out["Supertrend"] = st
    out["Signal"] = sig
    # before start the user file leaves ATR blank too (first 4 rows)
    return out


def to_user_format(o: pd.DataFrame) -> pd.DataFrame:
    f = o.copy()
    for c in INT_COLS:
        if c in f:
            f[c] = f[c].round(0).astype("Int64")
    for c in DP1_COLS:
        f[c] = f[c].round(1)
    return f


# ----------------------------------------------------------------------------- scoring
def score(model: pd.DataFrame, user: pd.DataFrame, rounded: bool = True) -> dict:
    """rows beyond tolerance per column; tolerance 0 for integer cols on rounded output,
    0.05 for 1-dp columns (on full-precision) / exact equality on rounded output."""
    idx = user.index.intersection(model.index)
    res = {"rows_common": len(idx), "rows_user_only": len(user.index.difference(model.index)),
           "rows_model_only": len(model.index.difference(user.index))}
    for c in COLS:
        if c not in model:
            res[f"{c}_bad"] = None
            continue
        a = pd.to_numeric(model.loc[idx, c], errors="coerce").astype(float)
        b = user.loc[idx, c].astype(float)
        nanmis = int((a.isna() ^ b.isna()).sum())
        diff = (a - b).abs()
        tol = 0.0 if c in INT_COLS else (0.0 if rounded else 0.05)
        res[f"{c}_bad"] = int((diff > tol + 1e-9).sum()) + nanmis
        res[f"{c}_maxdiff"] = float(diff.max()) if diff.notna().any() else 0.0
    s = model.loc[idx, "Signal"].fillna("").astype(str) != user.loc[idx, "Signal"].fillna("").astype(str)
    res["Signal_bad"] = int(s.sum())
    res["Signal_bad_dates"] = ";".join(idx[s].strftime("%Y-%m-%d"))
    return res


def main() -> None:
    user = load_user()
    raw = load_raw()

    # ---------------- the reproduction
    full = supertrend(weekly_resample(fill_hl_from_prices(raw)))
    rep = to_user_format(full)
    rep.reset_index().to_csv(OUT / "repro_user_weekly.csv", index=False)

    # row-by-row diffs
    rows = pd.DataFrame(index=user.index)
    for c in COLS + ["Signal"]:
        rows[f"{c}_user"] = user[c]
        rows[f"{c}_repro"] = rep[c].reindex(user.index)
        if c != "Signal":
            rows[f"{c}_full"] = full[c].reindex(user.index)
            rows[f"{c}_absdiff_full"] = (full[c].reindex(user.index).astype(float) - user[c].astype(float)).abs()
            rows[f"{c}_absdiff_rounded"] = (rep[c].reindex(user.index).astype(float) - user[c].astype(float)).abs()
    rows["Signal_match"] = rows["Signal_user"].fillna("") == rows["Signal_repro"].fillna("")
    rows.reset_index().to_csv(OUT / "repro_row_diffs.csv", index=False)

    print("=== REPRODUCTION (raw daily, H/L filled from prices, W-FRI, start 5th candle) ===")
    s_full = score(full, user, rounded=False)
    s_rnd = score(rep, user, rounded=True)
    print("full precision:", {k: v for k, v in s_full.items() if not k.endswith("dates")})
    print("rounded output:", {k: v for k, v in s_rnd.items() if not k.endswith("dates")})
    # identical file text?
    ut = pd.read_csv(USER, dtype=str)
    rt = rep.reset_index().copy()
    rt["WeekEnding"] = rt["WeekEnding"].dt.strftime("%Y-%m-%d")
    same_cells = 0; total = 0; bad_cells = []
    for c in ut.columns:
        for i in range(len(ut)):
            a = ut.at[i, c]; b = rt.at[i, c]
            total += 1
            if (pd.isna(a) and pd.isna(b)) or (not pd.isna(a) and not pd.isna(b) and
                                                (a == str(b) or (c not in ("WeekEnding", "Signal") and float(a) == float(b)))):
                same_cells += 1
            else:
                bad_cells.append((ut.at[i, "WeekEnding"], c, a, b))
    print(f"cell-by-cell: {same_cells}/{total} equal; mismatches: {bad_cells[:10]}")

    # ---------------- variants
    clean = load_clean()
    variants = {
        "A_repro_raw_HLfill_WFRI_start5": full,
        "B_raw_noHLfill_WFRI_start5": supertrend(weekly_resample(raw)),
        "C_clean_file_WFRI_start5": supertrend(weekly_resample(clean)),
        "D_raw_HLfill_ISOweek(W-SUN)_start5": supertrend(weekly_resample(fill_hl_from_prices(raw), "W-SUN")),
        "E_raw_HLfill_WFRI_start6(ST.py start)": supertrend(weekly_resample(fill_hl_from_prices(raw)), start_candle=6),
        "F_repro_but_ATR_rounded_1dp_before_bands": supertrend(weekly_resample(fill_hl_from_prices(raw)), round_atr=True),
        "G_repro_but_bands_rounded_1dp_in_ratchet": supertrend(weekly_resample(fill_hl_from_prices(raw)), round_bands=True),
    }
    # NSE-calendar candles as ST.py built them (no Open column available)
    sw = pd.read_excel(STPY_WEEKS).set_index("Date")
    sw.index = pd.to_datetime(sw.index)
    stpy_lab = sw.index
    sw_f = sw[["High", "Low", "Close", "Volume"]].copy()
    sw_f.index = stpy_lab + pd.to_timedelta(4 - stpy_lab.dayofweek, unit="D")
    sw_f.index.name = "WeekEnding"
    variants["H_STpy_NSEcalendar_candles_start5"] = supertrend(sw_f, start_candle=5)
    variants["I_STpy_NSEcalendar_candles_start6"] = supertrend(sw_f, start_candle=6)

    recs = []
    for k, m in variants.items():
        r = score(to_user_format(m), user, rounded=True)
        r["variant"] = k
        recs.append(r)
    vs = pd.DataFrame(recs).set_index("variant")
    vs.to_csv(OUT / "repro_variant_scores.csv")
    pd.set_option("display.width", 250); pd.set_option("display.max_columns", 50)
    print("\n=== VARIANT SCORES (rows beyond tolerance per column, on rounded output) ===")
    print(vs[[c for c in vs.columns if c.endswith("_bad") or c.startswith("rows")]].to_string())
    for k in vs.index:
        if vs.at[k, "Signal_bad"]:
            print(f"  {k} signal mismatch dates: {vs.at[k, 'Signal_bad_dates']}")

    # ---------------- decomposition vs ST.py Master
    mst = pd.read_excel(MASTER)
    mst["Date"] = pd.to_datetime(mst["Date"])
    mst = mst.set_index("Date")
    # 1) our formula on ST.py's own candles, ST.py start (6th candle), labels kept
    sw_lab = sw[["High", "Low", "Close"]].copy()
    ours_on_stpy = supertrend(sw_lab, start_candle=6)
    j = mst[["ST", "FUB", "FLB", "BUB", "BLB", "EMA_TR", "SIGN"]].join(
        ours_on_stpy[["Supertrend", "UpperBand", "LowerBand", "LW_ATR5", "Signal"]], how="left")
    print("\n=== OUR FORMULA ON ST.py CANDLES (start 6th) vs Master_MAUc1 ===")
    print("rows", len(j), "max|ST diff|", float((j.ST - j.Supertrend).abs().max()),
          "max|FUB diff|", float((j.FUB - j.UpperBand).abs().max()),
          "max|FLB diff|", float((j.FLB - j.LowerBand).abs().max()),
          "max|EMA_TR - LW_ATR5|", float((j.EMA_TR - j.LW_ATR5).abs().max()),
          "SIGN mismatches", int((j.SIGN != j.Signal).sum()))

    # 2) user signal vs ST.py SIGN, Friday-mapped
    mf = mst.copy()
    mf["stpy_label"] = mf.index
    mf.index = mf.index + pd.to_timedelta(4 - mf.index.dayofweek, unit="D")
    mf.index.name = "WeekEnding"
    cmp = user[["Close", "Supertrend", "Signal"]].rename(columns=lambda c: f"user_{c}").join(
        mf[["stpy_label", "Index", "ST", "SIGN"]].rename(columns={"Index": "stpy_Close", "ST": "stpy_ST", "SIGN": "stpy_SIGN"}),
        how="outer")
    cmp["repro_start6_Signal"] = variants["E_raw_HLfill_WFRI_start6(ST.py start)"]["Signal"].reindex(cmp.index)
    cmp["stpy_candles_start5_Signal"] = variants["H_STpy_NSEcalendar_candles_start5"]["Signal"].reindex(cmp.index)
    both = cmp.dropna(subset=["user_Signal", "stpy_SIGN"])
    dif = both[both.user_Signal != both.stpy_SIGN]
    cmp["signal_agree"] = np.where(cmp.user_Signal.notna() & cmp.stpy_SIGN.notna(),
                                   cmp.user_Signal == cmp.stpy_SIGN, np.nan)
    cmp.reset_index().to_csv(OUT / "repro_vs_stpy_signals.csv", index=False)
    print("\n=== USER vs ST.py SIGN (Friday-mapped) ===")
    print("user rows", user.Signal.notna().sum(), "stpy rows", len(mst), "common", len(both),
          "agree", int((both.user_Signal == both.stpy_SIGN).sum()), "differ", len(dif))
    print(dif[["stpy_label", "user_Close", "stpy_Close", "user_Supertrend", "stpy_ST", "user_Signal", "stpy_SIGN",
               "repro_start6_Signal", "stpy_candles_start5_Signal"]].to_string())
    print("user rows not in ST.py:", list(cmp.index[cmp.stpy_SIGN.isna() & cmp.user_Signal.notna()].strftime("%Y-%m-%d")))
    print("ST.py rows not in user:", list(cmp.index[cmp.stpy_SIGN.notna() & cmp.user_Signal.isna()].strftime("%Y-%m-%d")))


if __name__ == "__main__":
    main()
