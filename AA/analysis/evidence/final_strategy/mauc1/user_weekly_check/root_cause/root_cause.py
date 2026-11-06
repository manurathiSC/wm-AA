"""
Root cause of every signal difference between the user's weekly MAUc1 supertrend file
(C:\\Users\\manur\\Downloads\\MAUc1_weekly_supertrend1.csv.csv) and production ST.py's
Master_MAUc1.xlsx.

Read-only on every input. Writes only into this folder.

    cd C:\\Users\\manur\\Repos\\wm-research\\AA\\analysis
    python evidence\\final_strategy\\mauc1\\user_weekly_check\\root_cause\\root_cause.py
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path(__file__).resolve().parent
AA = Path(r"C:\Users\manur\Repos\wm-research\AA")
FRA = AA / "Historical Data" / "FRA_MAUc1"
USER_CSV = Path(r"C:\Users\manur\Downloads\MAUc1_weekly_supertrend1.csv.csv")
RAW_CSV = Path(r"C:\Users\manur\Downloads\MAUc1_daily1.csv")
CLEAN_CSV = AA / "analysis" / "evidence" / "final_strategy" / "mauc1" / "mauc1_daily_clean.csv"
MASTER = FRA / "RSI" / "Final" / "Analysis" / "Master_MAUc1.xlsx"
WEEK_ST = FRA / "RSI" / "Final" / "MAUc1" / "weekIndexDf_250926_W.xlsx"
DAY_ST = FRA / "RSI" / "Final" / "MAUc1" / "indexDf_250926_W.xlsx"
TDAYS = FRA / "Data" / "TradingDays.xlsx"

MUL, DAYS = 2.0, 5
ST_START = 5      # ST.py run(): rebalStartIndex = 5 -> 6th weekly candle, window = candles 2..6
USER_START = 4    # user's file: first signal on the 5th candle, window = candles 1..5
RTOL = 0.051      # user's file is rounded to 1 decimal (TR/OHLC integer)


# ── loaders ────────────────────────────────────────────────────────────────
def load_user() -> pd.DataFrame:
    u = pd.read_csv(USER_CSV, parse_dates=["WeekEnding"]).set_index("WeekEnding")
    u.index.name = "fri"
    return u


def load_raw() -> pd.DataFrame:
    r = pd.read_csv(RAW_CSV, parse_dates=["Date"]).set_index("Date").sort_index()
    r.columns = [c.capitalize() for c in r.columns]
    return r


def load_clean() -> pd.DataFrame:
    c = pd.read_csv(CLEAN_CSV, parse_dates=["date"]).set_index("date").sort_index()
    c.columns = [x.capitalize() for x in c.columns]
    return c


def load_master() -> pd.DataFrame:
    m = pd.read_excel(MASTER)
    m["Date"] = pd.to_datetime(m["Date"])
    return m.set_index("Date")


def load_st_weeks() -> pd.DataFrame:
    w = pd.read_excel(WEEK_ST)
    w["Date"] = pd.to_datetime(w["Date"])
    return w.set_index("Date")


def load_st_days() -> pd.DataFrame:
    d = pd.read_excel(DAY_ST)
    d["Date"] = pd.to_datetime(d["Date"])
    return d.set_index("Date")


def load_nse_days() -> pd.DatetimeIndex:
    td = pd.read_excel(TDAYS, header=None, skiprows=3)[1]
    return pd.DatetimeIndex(pd.to_datetime(td)).sort_values()


def friday_of(ts: pd.Timestamp) -> pd.Timestamp:
    """Friday of the ISO (Mon-Sun) week that contains ts."""
    return (ts - pd.Timedelta(days=ts.weekday()) + pd.Timedelta(days=4)).normalize()


# ── candles ────────────────────────────────────────────────────────────────
def finish(w: pd.DataFrame) -> pd.DataFrame:
    """ST.py setData derived columns: PClose, HML, HMC, LMC, TR (NaN-skipping max), AHML."""
    w = w.copy()
    w["HML"] = w["High"] - w["Low"]
    w["PClose"] = w["Close"].shift()
    w["HMC"] = (w["High"] - w["PClose"]).abs()
    w["LMC"] = (w["Low"] - w["PClose"]).abs()
    w["TR"] = w[["HML", "HMC", "LMC"]].max(axis=1)
    w["AHML"] = 0.5 * w["High"] + 0.5 * w["Low"]
    return w


def user_daily(raw: pd.DataFrame) -> pd.DataFrame:
    """
    The daily treatment the user's candles imply (verified in main): every row of the raw
    export is kept (no NSE calendar); per row High = max(O,H,L,C) and Low = min(O,H,L,C),
    NaN-skipping, so a close-only row counts as H = L = C with no open; a row with no
    close still contributes its open/high/low/volume.
    """
    d = raw.copy()
    px = d[["Open", "High", "Low", "Close"]]
    d["High"] = px.max(axis=1)      # NaN-skipping: a close-only row gets H = L = C
    d["Low"] = px.min(axis=1)       # and a close outside [L, H] widens the bar
    return d


def wfri_candles(daily: pd.DataFrame) -> pd.DataFrame:
    """pandas resample('W-FRI'): Saturday..Friday buckets, labelled by the Friday."""
    g = daily.resample("W-FRI")
    w = pd.DataFrame({"Open": g["Open"].first(), "High": g["High"].max(), "Low": g["Low"].min(),
                      "Close": g["Close"].last(), "Volume": g["Volume"].sum(),
                      "n": g["High"].count()})
    w["last_day"] = pd.Series(daily.index, index=daily.index).resample("W-FRI").max()
    w = w[w["n"] > 0]
    w.index.name = "fri"
    return finish(w)


def iso_candles(daily: pd.DataFrame, label: str = "friday") -> pd.DataFrame:
    """ISO Mon..Sun buckets over whatever days `daily` has (ST.py's grouping)."""
    key = daily.index.map(friday_of)
    g = daily.groupby(key)
    w = pd.DataFrame({"High": g["High"].max(), "Low": g["Low"].min(), "Close": g["Close"].last(),
                      "Volume": g["Volume"].sum(), "n": g["High"].count()})
    w["last_day"] = pd.Series(daily.index, index=daily.index).groupby(key).max()
    w.index.name = "fri"
    return finish(w)


def nse_frame(daily: pd.DataFrame, nse: pd.DatetimeIndex) -> pd.DataFrame:
    """ST.py getRequiredDf: reindex to NSE trading days from the first MCX day, ffill."""
    idx = nse[(nse >= daily.index.min()) & (nse <= daily.index.max())]
    f = daily.reindex(idx).ffill()
    return f


# ── supertrend, ST.py getSupertrend replicated ─────────────────────────────
def supertrend(w: pd.DataFrame, start: int, mul: float = MUL, days: int = DAYS) -> pd.DataFrame:
    wts = np.arange(1, days + 1) / np.sum(np.arange(1, days + 1))
    tr, ahml = w["TR"].to_numpy(float), w["AHML"].to_numpy(float)
    close, pclose = w["Close"].to_numpy(float), w["PClose"].to_numpy(float)
    n = len(w)
    out = {k: np.full(n, np.nan) for k in ["ATR", "BUB", "BLB", "FUB", "FLB", "ST"]}
    for i in range(start, n):
        eatr = float((tr[i - days + 1:i + 1] * wts).sum())
        bub, blb = ahml[i] + mul * eatr, ahml[i] - mul * eatr
        if i == start:
            fub, flb = bub, blb
            st = fub
        else:
            pfub, pflb, pst = out["FUB"][i - 1], out["FLB"][i - 1], out["ST"][i - 1]
            fub = bub if (bub < pfub or pclose[i] > pfub) else pfub
            flb = blb if (blb > pflb or pclose[i] < pflb) else pflb
            if pst == pfub and close[i] <= fub:
                st = fub
            elif pst == pfub and close[i] > fub:
                st = flb
            elif pst == pflb and close[i] >= flb:
                st = flb
            elif pst == pflb and close[i] < fub:
                st = fub
            else:
                st = 0.0
        for k, v in zip(["ATR", "BUB", "BLB", "FUB", "FLB", "ST"], [eatr, bub, blb, fub, flb, st]):
            out[k][i] = v
    o = pd.DataFrame(out, index=w.index)
    o["SIGN"] = np.where(o["ST"].isna(), None, np.where(o["ST"] == o["FLB"], "BUY", "SELL"))
    return o


# ── production ST.py, run from a hash-checked copy in this folder ──────────
VENDOR_PS = AA / "analysis" / "vendor_fra" / "Python_Scripts"
PROD_COPY = OUT / "prod_code"


def sha(p: Path) -> str:
    import hashlib
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def import_st():
    """
    Copy vendor_fra/Python_Scripts/{ST,QuantBacktester,ProspectTheory}.py (byte-identical to
    production, per mauc1_st_production.py) into ./prod_code and import them from there, so
    QuantBacktester's log files and any bytecode land in this folder, not in the repo.
    """
    import os, shutil, sys, types
    dst = PROD_COPY / "Python_Scripts"
    dst.mkdir(parents=True, exist_ok=True)
    hashes = {}
    for f in ["ST.py", "QuantBacktester.py", "ProspectTheory.py"]:
        shutil.copyfile(VENDOR_PS / f, dst / f)
        assert sha(dst / f) == sha(VENDOR_PS / f)
        hashes[f] = sha(dst / f)
    sys.dont_write_bytecode = True
    sys.modules.setdefault("eikon", types.ModuleType("eikon"))
    sys.path.insert(0, str(PROD_COPY))
    cwd = os.getcwd()
    os.chdir(PROD_COPY)
    try:
        import Python_Scripts.ST as ST
    finally:
        os.chdir(cwd)
    assert Path(ST.__file__).resolve().parent == dst.resolve()
    return ST, hashes


def st_run_on_buckets(ST, daily: pd.DataFrame, bucket: pd.Series, tag: str) -> pd.DataFrame:
    """
    Production ST.run() on candles built by production ST.setData() from `daily`, grouped by
    `bucket` (one id per daily row). Only getRequiredDf's calendar step is replaced: it is
    the variable under test. Returns allRebalDf indexed by the bucket's last daily date.
    """
    import contextlib, io
    orig = ST.getRequiredDf

    def patched(scripDf, sD, scipID, universeFilePath, mondayClose, lastDate=None):
        ivd = daily[["Close", "Volume", "High", "Low"]].copy()
        # setData takes the last row's close even if NaN; resample().last() skips NaN.
        # Carrying the previous close into the export's 3 no-close rows gives resample's week close.
        ivd["Close"] = ivd["Close"].ffill()
        ivd["Week_Con"] = bucket.to_numpy()
        ivd["Month_Con"] = ivd.index.year * 12 + ivd.index.month
        ivd["HML"] = ivd["High"] - ivd["Low"]
        ivd["Ret"] = ivd["Close"].pct_change()
        ivd["PClose"] = ivd["Close"].shift()
        ivd["HMC"] = (ivd["High"] - ivd["PClose"]).abs()
        ivd["LMC"] = (ivd["Low"] - ivd["PClose"]).abs()
        ivd["TR"] = ivd[["HML", "HMC", "LMC"]].max(axis=1)
        ivd["AHML"] = 0.5 * ivd["High"] + 0.5 * ivd["Low"]
        wk = ST.setData(ivd, "Week_Con")
        mo = ST.setData(ivd, "Month_Con")
        for df in (ivd, wk, mo):
            for attr in ["Close", "Volume", "High", "Low", "HML", "HMC", "LMC", "TR"]:
                ST.getRequiredIndex(df, attr)
        atd = pd.DataFrame({"Date": wk.index})
        return ivd, wk, mo, atd

    ST.getRequiredDf = patched
    run_dir = OUT / "prod_run"
    run_dir.mkdir(exist_ok=True)
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            df, ok = ST.run([None, None, "MAUc1"], "W", 2, True,
                            str(run_dir / f"{tag}_indexDf.xlsx"), str(run_dir / f"{tag}_weekIndexDf.xlsx"),
                            str(run_dir / f"{tag}_monthIndexDf.xlsx"), str(run_dir / "unused.xlsx"), "unused")
    finally:
        ST.getRequiredDf = orig
    df = df.astype({c: float for c in ["ST", "FUB", "FLB", "BUB", "BLB", "EMA_TR", "Index"]})
    df["SIGN"] = np.where(df["ST"].isna(), None, np.where(df["ST"] == df["FLB"], "BUY", "SELL"))
    return df


def st_run_nse(ST, daily: pd.DataFrame, tag: str) -> pd.DataFrame:
    """Unpatched production ST.run() (NSE TradingDays calendar) on `daily`, harness-style scrip."""
    import contextlib, io
    one = lambda c: daily[[c]].rename(columns={c: "MAUc1"}).astype(float)
    close, vol, high, low = one("Close"), one("Volume").fillna(0.0), one("High"), one("Low")
    td = pd.read_excel(TDAYS, sheet_name="Sheet1", skiprows=2)
    sd = max(pd.to_datetime(td["Date"]).iloc[0], close["MAUc1"].first_valid_index())
    run_dir = OUT / "prod_run"
    run_dir.mkdir(exist_ok=True)
    with contextlib.redirect_stdout(io.StringIO()):
        df, ok = ST.run([[close, vol, high, low], sd, "MAUc1"], "W", 2, True,
                        str(run_dir / f"{tag}_indexDf.xlsx"), str(run_dir / f"{tag}_weekIndexDf.xlsx"),
                        str(run_dir / f"{tag}_monthIndexDf.xlsx"), str(run_dir / "unused.xlsx"), str(TDAYS))
    df = df.astype({c: float for c in ["ST", "FUB", "FLB", "BUB", "BLB", "EMA_TR", "Index"]})
    df["SIGN"] = np.where(df["ST"].isna(), None, np.where(df["ST"] == df["FLB"], "BUY", "SELL"))
    return df


# ── analysis helpers ───────────────────────────────────────────────────────
def st_py_by_friday(m: pd.DataFrame, w: pd.DataFrame) -> pd.DataFrame:
    """ST.py Master + its weekly candles, re-keyed from the week label to that ISO week's Friday."""
    s = m[["EMA_TR", "BUB", "BLB", "FUB", "FLB", "ST", "Index", "SIGN"]].astype(
        {c: float for c in ["EMA_TR", "BUB", "BLB", "FUB", "FLB", "ST", "Index"]})
    s = s.join(w[["High", "Low", "Close", "PClose", "TR", "AHML"]], how="right")
    s["label"] = s.index
    s.index = pd.DatetimeIndex([friday_of(x) for x in s.index], name="fri")
    assert s.index.is_unique
    return s


def signs_vs(a: pd.Series, b: pd.Series, weeks: pd.DatetimeIndex) -> list[str]:
    a, b = a.reindex(weeks), b.reindex(weeks)
    return [d.strftime("%Y-%m-%d") for d in weeks[(a != b).to_numpy()]]


def rekey(o: pd.DataFrame, label_to_fri) -> pd.DataFrame:
    o = o.copy()
    o.index = pd.DatetimeIndex([label_to_fri(x) for x in o.index], name="fri")
    assert o.index.is_unique
    return o


def stretches(weeks: list[pd.Timestamp], allweeks: pd.DatetimeIndex) -> list[list[pd.Timestamp]]:
    pos = {d: i for i, d in enumerate(allweeks)}
    out = []
    for d in sorted(weeks):
        if out and pos[d] == pos[out[-1][-1]] + 1:
            out[-1].append(d)
        else:
            out.append([d])
    return out


def wfri_of(d: pd.Timestamp) -> pd.Timestamp:
    """The Friday that closes the Saturday..Friday bucket containing d (pandas W-FRI label)."""
    return (d + pd.Timedelta(days=(4 - d.weekday()) % 7)).normalize()


def main():
    pd.set_option("display.width", 250)
    res: dict = {}
    u, m, w, raw, clean, nse = load_user(), load_master(), load_st_weeks(), load_raw(), load_clean(), load_nse_days()
    D = load_st_days()
    ud = user_daily(raw)
    nse_set = set(nse)

    # ── 0. reproduce both files ────────────────────────────────────────────
    uw = wfri_candles(ud)
    rep = {"user_candles_rebuilt_mismatch": {c: int((~np.isclose(u[c], uw[c].reindex(u.index))).sum())
                                             for c in ["Open", "High", "Low", "Close", "Volume", "TR"]},
           "user_weeks": len(u), "rebuilt_weeks": len(uw)}
    r_u4 = supertrend(finish(u[["Open", "High", "Low", "Close", "Volume"]]), USER_START)
    rep["user_file_vs_ST.py_formula_from_5th_candle"] = {
        "max_abs_diff": {a: float((u[a] - r_u4[b]).abs().max())
                         for a, b in [("LW_ATR5", "ATR"), ("UpperBand", "FUB"), ("LowerBand", "FLB"), ("Supertrend", "ST")]},
        "signal_mismatches": int((u["Signal"].fillna("") != r_u4["SIGN"].fillna("")).sum())}
    r_s5 = supertrend(w, ST_START)
    mm = m.join(r_s5, rsuffix="_r")
    rep["master_vs_replica_on_st_py_candles"] = {
        "max_abs_diff": {c: float((mm[c].astype(float) - mm[c + "_r"]).abs().max()) for c in ["ST", "FUB", "FLB", "BUB", "BLB"]},
        "sign_mismatches": int((mm["SIGN"] != mm["SIGN_r"]).sum()), "weeks": len(mm)}
    stc = iso_candles(nse_frame(clean, nse))
    wf = w.copy()
    wf.index = pd.DatetimeIndex([friday_of(x) for x in w.index])
    rep["st_py_candles_rebuilt_mismatch"] = {c: int((~np.isclose(stc[c], wf[c].reindex(stc.index), equal_nan=True)).sum())
                                             for c in ["High", "Low", "Close", "TR"]}
    res["reproduction"] = rep
    print(json.dumps(rep, indent=1))

    # ── 1. week-by-week comparison ─────────────────────────────────────────
    s = st_py_by_friday(m, w)
    common = u.index.intersection(s.index[s["SIGN"].notna()])
    res["weeks"] = {"user": len(u), "st_py_master": int(s["SIGN"].notna().sum()), "common": len(common),
                    "user_only": [d.strftime("%Y-%m-%d") for d in u.index.difference(common)],
                    "st_only": [d.strftime("%Y-%m-%d") for d in s.index[s["SIGN"].notna()].difference(u.index)]}
    J = u.join(s, how="left", lsuffix="_u")
    J["st_label"] = J["label"].dt.strftime("%Y-%m-%d")
    J["st_label_dow"] = J["label"].dt.day_name().str[:3]
    diffs = signs_vs(u["Signal"], s["SIGN"], common)
    res["sign_differences"] = [{"week": d, "user": u.loc[d, "Signal"], "st_py": s.loc[d, "SIGN"],
                                "close": float(u.loc[d, "Close"]),
                                "user_ST": float(u.loc[d, "Supertrend"]), "st_py_ST": round(float(s.loc[d, "ST"]), 2),
                                "user_Upper": float(u.loc[d, "UpperBand"]), "st_py_FUB": round(float(s.loc[d, "FUB"]), 2),
                                "user_Lower": float(u.loc[d, "LowerBand"]), "st_py_FLB": round(float(s.loc[d, "FLB"]), 2)}
                               for d in diffs]
    pd.DataFrame(res["sign_differences"]).to_csv(OUT / "sign_differences.csv", index=False)
    print("SIGN differences:", diffs)

    # bucket composition: which daily sessions sit in each Friday-week, per source
    user_bucket = pd.Series(list(raw.index), index=raw.index).groupby([wfri_of(d) for d in raw.index]).apply(list)
    ffilled = set(D.index[~D.index.isin(clean.index)])
    st_bucket = pd.Series(list(D.index), index=D.index).groupby([friday_of(x) for x in D.index]).apply(list)

    def kind_user_only(d):
        if d.weekday() >= 5:
            if d in nse_set:
                return f"weekend MCX session ({d:%a}) on an NSE day: ST.py puts it in the previous ISO week"
            return f"weekend MCX session ({d:%a}), not an NSE day: dropped by ST.py"
        return f"MCX session on an NSE holiday ({d:%a}): dropped by ST.py"

    def kind_st_only(d):
        if d in ffilled:
            return f"NSE day without an MCX bar ({d:%a}): ST.py repeats the previous bar"
        if d.weekday() >= 5:
            return f"weekend session ({d:%a}) ST.py keeps in this ISO week; user's W-FRI puts it in the next week"
        return "other"

    comp = []
    for fri in J.index:
        us, ss = set(user_bucket.get(fri, [])), set(st_bucket.get(fri, []))
        only_u, only_s = sorted(us - ss), sorted(ss - us)
        # same day in both buckets but ST.py's (ffilled / cleaned) bar differs from the export row
        clean_diff = [d for d in sorted(us & ss) if
                      not np.allclose(ud.loc[d, ["High", "Low"]].astype(float).to_numpy(),
                                      D.loc[d, ["High", "Low"]].astype(float).to_numpy(), equal_nan=True)
                      or (pd.notna(ud.loc[d, "Close"]) and ud.loc[d, "Close"] != D.loc[d, "Close"])]
        comp.append({"fri": fri,
                     "sessions_only_user": ";".join(f"{d:%Y-%m-%d}" for d in only_u),
                     "sessions_only_st_py": ";".join(f"{d:%Y-%m-%d}" for d in only_s),
                     "kinds": " | ".join([f"{d:%Y-%m-%d} {kind_user_only(d)}" for d in only_u] +
                                         [f"{d:%Y-%m-%d} {kind_st_only(d)}" for d in only_s] +
                                         [f"{d:%Y-%m-%d} same day, ST.py bar (cleaned/ffilled) differs from the export row" for d in clean_diff])})
    J = J.join(pd.DataFrame(comp).set_index("fri"))

    tol = 0.05 + 1e-9
    for a, b, n in [("High_u", "High", "high"), ("Low_u", "Low", "low"), ("Close_u", "Close", "close"),
                    ("TR_u", "TR", "tr"), ("LW_ATR5", "EMA_TR", "atr"), ("UpperBand", "FUB", "fub"),
                    ("LowerBand", "FLB", "flb"), ("Supertrend", "ST", "st")]:
        J["d_" + n] = J[a] - J[b]
        J["x_" + n] = (J["d_" + n].abs() > tol) & J.index.isin(common)
    J["candle_differs"] = J[["x_high", "x_low", "x_close"]].any(axis=1)
    J["sign_differs"] = J.index.isin(pd.DatetimeIndex(diffs))

    # ── 2. stretches: first divergence and the sessions responsible ────────
    anyx = J.loc[common, ["x_high", "x_low", "x_close", "x_tr", "x_atr", "x_fub", "x_flb", "x_st"]].any(axis=1)
    res["stretches"] = []
    for grp in stretches([pd.Timestamp(d) for d in diffs], common):
        first = grp[0]
        before = anyx.loc[:first]
        last_agree = before[~before].index[-1]
        first_div = before.loc[last_agree:].index[1]
        end = J.index[min(J.index.get_loc(grp[-1]) + 2, len(J) - 1)]
        tr = J.loc[last_agree:end, ["st_label", "st_label_dow", "High_u", "High", "Low_u", "Low", "Close_u", "Close",
                                    "TR_u", "TR", "LW_ATR5", "EMA_TR", "UpperBand", "FUB", "LowerBand", "FLB",
                                    "Supertrend", "ST", "Signal", "SIGN", "kinds"]].copy()
        for c in ["EMA_TR", "FUB", "FLB", "ST"]:
            tr[c] = tr[c].round(2)
        tr.to_csv(OUT / f"stretch_{first:%Y-%m-%d}_trace.csv")
        res["stretches"].append({"weeks": [f"{d:%Y-%m-%d}" for d in grp],
                                 "last_week_all_paths_equal": f"{last_agree:%Y-%m-%d}",
                                 "first_divergent_week": f"{first_div:%Y-%m-%d}",
                                 "first_divergent_st_label": J.loc[first_div, "st_label"],
                                 "composition_differences_last_agree_to_stretch_end":
                                     {f"{k:%Y-%m-%d}": v for k, v in J.loc[last_agree:grp[-1], "kinds"].items() if v}})
        print(tr.drop(columns=["kinds"]).to_string())

    # ── 3. counterfactuals ─────────────────────────────────────────────────
    ST, hashes = import_st()
    res["prod_code_sha256"] = hashes
    fri_key = pd.Series([wfri_of(d) for d in ud.index], index=ud.index)
    b_wfri = fri_key.rank(method="dense").astype(int)
    last_to_fri = pd.Series(ud.index, index=ud.index).groupby(fri_key).max()
    last_to_fri = dict(zip(pd.DatetimeIndex(last_to_fri.to_numpy()), last_to_fri.index))
    p_user = rekey(st_run_on_buckets(ST, ud, b_wfri, "userWFRI"), lambda x: last_to_fri[pd.Timestamp(x)])
    r_u5 = supertrend(uw, ST_START)
    p_clean = rekey(st_run_nse(ST, clean, "nseClean"), friday_of)
    p_nse_user = rekey(st_run_nse(ST, ud, "nseUserDaily"), friday_of)
    res["prod_engine_checks"] = {
        "prod_ST.run_user_WFRI_vs_replica_start6th_max_abs_ST": float((p_user["ST"] - r_u5["ST"].reindex(p_user.index)).abs().max()),
        "prod_ST.run_NSE_cleaned_vs_Master_max_abs_ST": float((p_clean["ST"] - s["ST"].reindex(p_clean.index)).abs().max()),
        "prod_ST.run_NSE_cleaned_vs_Master_sign_mismatch": len(signs_vs(p_clean["SIGN"], s["SIGN"], common))}
    print(res["prod_engine_checks"])

    variants = {
        "A user W-FRI, all MCX sessions": uw,
        "B ST.py: NSE calendar + ffill, ISO weeks, cleaned daily": stc,
        "C ISO Mon-Sun weeks, all MCX sessions": iso_candles(ud),
        "D W-FRI, only MCX sessions on NSE days": wfri_candles(ud[ud.index.isin(nse)]),
        "E NSE calendar + ffill, ISO weeks, user's daily rows": iso_candles(nse_frame(ud, nse)),
    }
    grid = []
    for name, cdl in variants.items():
        for start in (USER_START, ST_START):
            o = supertrend(cdl, start)
            vu, vs = signs_vs(o["SIGN"], u["Signal"], common), signs_vs(o["SIGN"], s["SIGN"], common)
            grid.append({"candles": name, "start": "5th candle (user)" if start == USER_START else "6th candle (ST.py)",
                         "engine": "replica", "n_vs_user": len(vu), "n_vs_st_py": len(vs),
                         "weeks_vs_user": ";".join(vu), "weeks_vs_st_py": ";".join(vs)})
    for name, o in [("A user W-FRI, all MCX sessions", p_user),
                    ("B ST.py: NSE calendar + ffill, ISO weeks, cleaned daily", p_clean),
                    ("E NSE calendar + ffill, ISO weeks, user's daily rows", p_nse_user)]:
        vu, vs = signs_vs(o["SIGN"], u["Signal"], common), signs_vs(o["SIGN"], s["SIGN"], common)
        grid.append({"candles": name, "start": "6th candle (ST.py)", "engine": "production ST.run",
                     "n_vs_user": len(vu), "n_vs_st_py": len(vs), "weeks_vs_user": ";".join(vu), "weeks_vs_st_py": ";".join(vs)})
    grid = pd.DataFrame(grid)
    grid.to_csv(OUT / "counterfactual_grid.csv", index=False)
    print(grid.to_string())
    res["counterfactual_grid"] = grid.to_dict(orient="records")

    # single-session toggles, both directions, for every MCX session that is not an NSE day
    base_st = nse_frame(clean, nse)
    extra = [d for d in raw.index if d not in nse_set and d <= base_st.index.max()]
    base_st_sign = supertrend(iso_candles(base_st), ST_START)["SIGN"]
    base_u_sign = supertrend(uw, USER_START)["SIGN"]
    tog = []
    for d in extra:
        row = ud.loc[[d], ["Open", "High", "Low", "Close", "Volume"]]
        add = pd.concat([base_st, row]).sort_index()
        sa = supertrend(iso_candles(add), ST_START)["SIGN"]
        sb = supertrend(wfri_candles(ud.drop(index=d)), USER_START)["SIGN"]
        ch_a, ch_b = signs_vs(sa, base_st_sign, common), signs_vs(sb, base_u_sign, common)
        tog.append({"session": f"{d:%Y-%m-%d}", "dow": f"{d:%a}", "high": row["High"].iloc[0],
                    "low": row["Low"].iloc[0], "close": row["Close"].iloc[0],
                    "n_st_py_weeks_flipped_when_added": len(ch_a), "st_py_weeks_flipped": ";".join(ch_a),
                    "n_user_weeks_flipped_when_dropped": len(ch_b), "user_weeks_flipped": ";".join(ch_b)})
    tog = pd.DataFrame(tog)
    tog.to_csv(OUT / "session_toggles.csv", index=False)
    hit = tog[(tog["n_st_py_weeks_flipped_when_added"] > 0) | (tog["n_user_weeks_flipped_when_dropped"] > 0)]
    print(f"{len(tog)} sessions toggled; {len(hit)} flip any week"); print(hit.to_string())
    res["session_toggles"] = {"sessions_tested": len(tog), "sessions_that_flip_any_week": hit.to_dict(orient="records")}

    resp = pd.DatetimeIndex(hit["session"])
    add = pd.concat([base_st, ud.loc[resp, ["Open", "High", "Low", "Close", "Volume"]]]).sort_index()
    sa = supertrend(iso_candles(add), ST_START)["SIGN"]
    sb = supertrend(wfri_candles(ud.drop(index=resp)), USER_START)["SIGN"]
    res["minimal_set"] = {"sessions": [f"{d:%Y-%m-%d}" for d in resp],
                          "st_py_plus_these_sessions_vs_user_mismatch": signs_vs(sa, u["Signal"], common),
                          "user_minus_these_sessions_vs_st_py_mismatch": signs_vs(sb, s["SIGN"], common)}
    for name, ss in [("2018-11-23 + 2023-04-14 only", ["2018-11-23", "2023-04-14"]),
                     ("2021-11-05 + 2021-11-19 together", ["2021-11-05", "2021-11-19"])]:
        ss = pd.DatetimeIndex(ss)
        add = pd.concat([base_st, ud.loc[ss, ["Open", "High", "Low", "Close", "Volume"]]]).sort_index()
        sa = supertrend(iso_candles(add), ST_START)["SIGN"]
        sb = supertrend(wfri_candles(ud.drop(index=ss)), USER_START)["SIGN"]
        res["minimal_set"][name] = {"st_py_plus_vs_user": signs_vs(sa, u["Signal"], common),
                                    "st_py_plus_vs_st_py": signs_vs(sa, s["SIGN"], common),
                                    "user_minus_vs_st_py": signs_vs(sb, s["SIGN"], common),
                                    "user_minus_vs_user": signs_vs(sb, u["Signal"], common)}
    print(json.dumps(res["minimal_set"], indent=1))

    # ── 4. non-signal differences ─────────────────────────────────────────
    r_u4f = supertrend(uw, USER_START)
    for c in ["ST", "FUB", "FLB", "BUB", "BLB", "ATR", "SIGN"]:
        J[c + "_u4"] = r_u4f[c]
        J[c + "_u5"] = r_u5[c]
    eps = 1e-6
    Jc = J.loc[common].copy()
    Jc["start_effect"] = (Jc["ST_u4"] - Jc["ST_u5"]).abs() > eps
    Jc["candle_effect"] = (Jc["ST_u5"] - Jc["ST"]).abs() > eps
    Jc["tr_window_diff"] = Jc["x_tr"].astype(int).rolling(5, min_periods=1).max().astype(bool)
    Jc["file_rounding"] = (Jc["Supertrend"] - Jc["ST_u4"]).abs()

    def st_cat(r):
        """Why the ST line differs, read off the band ST sits on (same band in both when signals agree)."""
        if not r["x_st"]:
            return "equal" if abs(r["d_st"]) < 1e-9 else "rounding only (0 < |diff| <= 0.05)"
        if r["sign_differs"]:
            return "signal differs (ST on opposite bands)"
        if r["start_effect"]:
            return "start offset"
        band, basic = ("FUB", "BUB") if r["SIGN"] == "SELL" else ("FLB", "BLB")
        reset_u = abs(r[band + "_u4"] - r[basic + "_u4"]) < eps
        reset_s = abs(r[band] - r[basic]) < eps
        if not (reset_u and reset_s):
            return "composition: band held by the ratchet from an earlier week"
        if r["x_high"] or r["x_low"]:
            return "composition: band reset this week, this week's high/low differ"
        return "composition: band reset this week, ATR differs (a TR in the 5-week window)"

    Jc["st_category"] = Jc.apply(st_cat, axis=1)
    res["st_line_categories"] = Jc["st_category"].value_counts().to_dict()
    # episodes: contiguous runs of ST-line differences, with the composition differences that start them
    pos = pd.Series(np.arange(len(Jc)), index=Jc.index)
    runs, cur = [], []
    for d in Jc.index[Jc["x_st"]]:
        if cur and pos[d] != pos[cur[-1]] + 1:
            runs.append(cur); cur = []
        cur.append(d)
    if cur:
        runs.append(cur)
    ep = []
    for rr in runs:
        a = Jc.index[max(pos[rr[0]] - 6, 0)]
        trig = Jc.loc[a:rr[-1]]
        trig = trig[trig["candle_differs"] | trig["x_tr"]]
        pre = [f"{d:%Y-%m-%d}" for d in trig.index if d < rr[0]]
        ep.append({"start": f"{rr[0]:%Y-%m-%d}", "end": f"{rr[-1]:%Y-%m-%d}", "weeks": len(rr),
                   "max_abs_d_st": round(float(Jc.loc[rr, "d_st"].abs().max()), 1),
                   "sign_weeks": ";".join(f"{d:%Y-%m-%d}" for d in rr if Jc.loc[d, "sign_differs"]),
                   "differing_candle_weeks_from_6wk_before": ";".join(f"{d:%Y-%m-%d}" for d in trig.index),
                   "sessions": " | ".join(k for k in trig["kinds"].tolist() if k),
                   "first_trigger_before_start": pre[0] if pre else "",
                   "categories": "; ".join(f"{k}: {v}" for k, v in Jc.loc[rr, "st_category"].value_counts().items())})
    ep = pd.DataFrame(ep)
    ep.to_csv(OUT / "st_line_episodes.csv", index=False)
    res["st_line_episodes"] = {"n": len(ep), "weeks": int(ep["weeks"].sum()),
                               "episodes_without_a_differing_candle_in_or_6wk_before":
                                   int((ep["differing_candle_weeks_from_6wk_before"] == "").sum())}
    res["st_line_weeks_diff_gt_0.05"] = int(Jc["x_st"].sum())
    res["st_line_max_file_rounding"] = float(Jc["file_rounding"].max())
    print(res["st_line_categories"])
    se = Jc["start_effect"]
    res["start_offset"] = {
        "weeks_ST_differs_user_candles_start5th_vs_6th": int(se.sum()),
        "first": f"{se[se].index.min():%Y-%m-%d}" if se.any() else None,
        "last": f"{se[se].index.max():%Y-%m-%d}" if se.any() else None,
        "sign_changes_user_candles": signs_vs(r_u4f["SIGN"], r_u5["SIGN"], common),
        "sign_changes_st_py_candles": signs_vs(rekey(supertrend(w, USER_START), friday_of)["SIGN"], s["SIGN"], common)}
    for c in ["ST", "FUB", "FLB", "ATR"]:
        x = (J.loc[common, c + "_u4"] - J.loc[common, c + "_u5"]).abs() > eps
        res["start_offset"][f"{c}_weeks_differ"] = int(x.sum())
        res["start_offset"][f"{c}_last_week_differs"] = f"{x[x].index.max():%Y-%m-%d}" if x.any() else None
        y = (rekey(supertrend(w, USER_START), friday_of)[c].reindex(common) - r_s5.rename(index=friday_of)[c].reindex(common)).abs() > eps
        res["start_offset"][f"{c}_weeks_differ_on_st_py_candles"] = int(y.sum())
        res["start_offset"][f"{c}_last_week_differs_on_st_py_candles"] = f"{y[y].index.max():%Y-%m-%d}" if y.any() else None

    def candle_cause(r):
        k = r["kinds"] or ""
        c = []
        if "NSE holiday" in k:
            c.append("MCX session on an NSE holiday")
        if "weekend" in k:
            c.append("weekend session")
        if "repeats the previous bar" in k:
            c.append("NSE day without MCX bar ffilled")
        if "same day, ST.py bar" in k:
            c.append("ST.py cleaned/ffilled bar differs from export row")
        return "; ".join(c) if c else "none this week: previous week's close differs"

    cd = Jc[Jc[["x_high", "x_low", "x_close", "x_tr"]].any(axis=1)].copy()
    cd["cause"] = cd.apply(candle_cause, axis=1)
    cd[["st_label", "st_label_dow", "High_u", "High", "Low_u", "Low", "Close_u", "Close", "TR_u", "TR", "PClose",
        "x_high", "x_low", "x_close", "x_tr", "cause", "kinds"]].to_csv(OUT / "candle_differences.csv")
    comp_weeks = Jc["kinds"].fillna("") != ""
    res["candle_differences"] = {
        "weeks_close_differs": int(Jc["x_close"].sum()), "weeks_high_differs": int(Jc["x_high"].sum()),
        "weeks_low_differs": int(Jc["x_low"].sum()), "weeks_tr_differs": int(Jc["x_tr"].sum()),
        "weeks_any_of_hlc_differs": int(Jc["candle_differs"].sum()),
        "weeks_tr_differs_via_prev_close_only": int((Jc["x_tr"] & ~Jc["candle_differs"]).sum()),
        "close_differs_by_cause": cd[cd["x_close"]]["cause"].value_counts().to_dict(),
        "hlc_differs_by_cause": cd[cd["candle_differs"]]["cause"].value_counts().to_dict(),
        "weeks_with_a_composition_difference": int(comp_weeks.sum()),
        "of_which_candle_identical": int((comp_weeks & ~Jc["candle_differs"]).sum()),
        "candle_differs_without_composition_difference": int((~comp_weeks & Jc["candle_differs"]).sum()),
    }
    print(json.dumps(res["candle_differences"], indent=1))
    J.to_csv(OUT / "weekly_compare.csv")
    Jc[["st_label", "Supertrend", "ST", "d_st", "x_st", "ST_u4", "ST_u5", "start_effect", "candle_effect",
        "candle_differs", "tr_window_diff", "sign_differs", "st_category"]].to_csv(OUT / "st_line_categories.csv")
    (OUT / "summary.json").write_text(json.dumps(res, indent=1, default=str))
    return res


if __name__ == "__main__":
    main()
