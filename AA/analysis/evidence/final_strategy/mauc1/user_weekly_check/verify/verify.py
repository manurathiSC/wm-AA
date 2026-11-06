"""
Independent adversarial check of the user's MAUc1 weekly supertrend file vs production ST.py (Master_MAUc1).
Written from scratch (no reuse of the investigators' code). Read-only on every input; writes only to this folder.
Run from C:\\Users\\manur\\Repos\\wm-research\\AA\\analysis
"""
from pathlib import Path
import json
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
AA = Path(r"C:\Users\manur\Repos\wm-research\AA")
FRA = AA / "Historical Data" / "FRA_MAUc1"
USER = Path(r"C:\Users\manur\Downloads\MAUc1_weekly_supertrend1.csv.csv")
RAW = Path(r"C:\Users\manur\Downloads\MAUc1_daily1.csv")
CLEAN = AA / "analysis" / "evidence" / "final_strategy" / "mauc1" / "mauc1_daily_clean.csv"
out = {}

# ---------------------------------------------------------------- inputs
U = pd.read_csv(USER, parse_dates=["WeekEnding"]).set_index("WeekEnding")
M = pd.read_excel(FRA / "RSI/Final/Analysis/Master_MAUc1.xlsx")
M["Date"] = pd.to_datetime(M["Date"])
M = M.set_index("Date")
W = pd.read_excel(FRA / "RSI/Final/MAUc1/weekIndexDf_250926_W.xlsx", index_col=0)
W.index = pd.to_datetime(W.index)
TD = pd.read_excel(FRA / "Data/TradingDays.xlsx", header=None, skiprows=3)
nse = pd.DatetimeIndex(pd.to_datetime(TD[1]))
R = pd.read_csv(RAW, parse_dates=["Date"]).set_index("Date")
R.columns = [c.lower() for c in R.columns]
C = pd.read_csv(CLEAN, index_col=0, parse_dates=True)

out["user_rows"] = len(U)
out["user_all_friday"] = bool((U.index.dayofweek == 4).all())
out["user_dup_labels"] = int(U.index.duplicated().sum())
out["master_rows"] = len(M)
out["master_dup_labels"] = int(M.index.duplicated().sum())
out["master_label_weekday_counts"] = M.index.day_name().value_counts().to_dict()
out["weekIndex_rows"] = len(W)
out["raw_rows"] = len(R)
out["raw_dup_dates"] = int(R.index.duplicated().sum())
out["master_sign_values"] = M["SIGN"].value_counts(dropna=False).to_dict()
out["user_signal_values"] = U["Signal"].value_counts(dropna=False).to_dict()


# ---------------------------------------------------------------- my own supertrend (ST.py literal rules)
def supertrend(high, low, close, start, mult=2.0, n=5):
    """start = 0-based candle position of the first ratchet row (ST.py rebalStartIndex=5 -> 6th candle)."""
    h, l, c = map(lambda x: np.asarray(x, float), (high, low, close))
    k = len(c)
    pc = np.r_[np.nan, c[:-1]]
    tr = np.nanmax(np.vstack([h - l, np.abs(h - pc), np.abs(l - pc)]), axis=0)
    wts = np.arange(1, n + 1) / (n * (n + 1) / 2)
    atr = np.full(k, np.nan)
    for i in range(n - 1, k):
        atr[i] = (tr[i - n + 1:i + 1] * wts).sum()
    hl2 = 0.5 * h + 0.5 * l
    bub, blb = hl2 + mult * atr, hl2 - mult * atr
    fub, flb, st = (np.full(k, np.nan) for _ in range(3))
    for i in range(start, k):
        if i == start:
            fub[i], flb[i], st[i] = bub[i], blb[i], bub[i]
            continue
        fub[i] = bub[i] if (bub[i] < fub[i - 1] or pc[i] > fub[i - 1]) else fub[i - 1]
        flb[i] = blb[i] if (blb[i] > flb[i - 1] or pc[i] < flb[i - 1]) else flb[i - 1]
        ps = st[i - 1]
        if ps == fub[i - 1] and c[i] <= fub[i]:
            st[i] = fub[i]
        elif ps == fub[i - 1] and c[i] > fub[i]:
            st[i] = flb[i]
        elif ps == flb[i - 1] and c[i] >= flb[i]:
            st[i] = flb[i]
        elif ps == flb[i - 1] and c[i] < fub[i]:
            st[i] = fub[i]
        else:
            st[i] = 0.0
    sig = np.where(np.isnan(st), None, np.where(st == flb, "BUY", "SELL"))
    return pd.DataFrame({"TR": tr, "ATR": atr, "HL2": hl2, "BUB": bub, "BLB": blb, "FUB": fub, "FLB": flb, "ST": st,
                         "SIG": sig, "ST0": st == 0})


# ---------------------------------------------------------------- 1. my supertrend on ST.py's own candles reproduces Master
s6 = supertrend(W["High"], W["Low"], W["Close"], start=5).set_index(W.index)
j = s6.join(M[["ST", "FUB", "FLB", "EMA_TR", "SIGN"]], rsuffix="_m", how="inner")
out["stpy_candles_myST_vs_master"] = {
    "rows": len(j), "max_abs_ST": float((j.ST - j.ST_m).abs().max()), "max_abs_FUB": float((j.FUB - j.FUB_m).abs().max()),
    "max_abs_FLB": float((j.FLB - j.FLB_m).abs().max()), "max_abs_ATR": float((j.ATR - j.EMA_TR).abs().max()),
    "sign_mismatch": int((j.SIG != j.SIGN).sum()), "ST0_rows": int(j.ST0.sum()),
    "master_label_equals_first_sig_row": str(s6.dropna(subset=["ST"]).index[0].date())}
s5_st = supertrend(W["High"], W["Low"], W["Close"], start=4).set_index(W.index)
cmp56 = s5_st.join(s6, rsuffix="_6").loc[M.index]
out["stpy_candles_start5_vs_start6"] = {
    "sign_diff": int((cmp56.SIG != cmp56.SIG_6).sum()),
    "ST_diff_rows": int(((cmp56.ST - cmp56.ST_6).abs() > 1e-9).sum()),
    "FUB_diff_rows": int(((cmp56.FUB - cmp56.FUB_6).abs() > 1e-9).sum()),
    "FLB_diff_rows": int(((cmp56.FLB - cmp56.FLB_6).abs() > 1e-9).sum()),
    "FLB_diff_dates": [str(d.date()) for d in cmp56.index[(cmp56.FLB - cmp56.FLB_6).abs() > 1e-9]],
    "start5_first_signal": str(s5_st.dropna(subset=["ST"]).index[0].date()) + " " + str(s5_st.dropna(subset=["ST"]).SIG.iloc[0])}

# ---------------------------------------------------------------- 2. my supertrend on the user's own printed candles
for nm, stt in (("start5", 4), ("start6", 5)):
    su = supertrend(U["High"], U["Low"], U["Close"], start=stt).set_index(U.index)
    msk = U["Signal"].notna()
    both = msk & su["SIG"].notna()
    out[f"user_candles_myST_{nm}"] = {
        "user_signal_rows": int(msk.sum()), "my_signal_rows": int(su.SIG.notna().sum()),
        "signal_match_on_both": int((su.SIG[both] == U.Signal[both]).sum()), "both": int(both.sum()),
        "max_abs_TR": float((su.TR - U.TR).abs().max()),
        "max_abs_ATR": float((su.ATR - U.LW_ATR5).abs().max()),
        "max_abs_UB": float((su.FUB - U.UpperBand)[both].abs().max()),
        "max_abs_LB": float((su.FLB - U.LowerBand)[both].abs().max()),
        "LB_rows_gt_0p05": [str(d.date()) for d in U.index[both & ((su.FLB - U.LowerBand).abs() > 0.05)]],
        "max_abs_ST": float((su.ST - U.Supertrend)[both].abs().max()),
        "ST0_rows": int(su.ST0.sum()),
        "round1_equal_ST": int((np.round(su.ST[both].astype(float), 1) == U.Supertrend[both]).sum())}
    if nm == "start5":
        su5 = su
    else:
        su6 = su
# min margin of close to active/flip band on user candles
cl = U["Close"].values
marg = []
for i in range(5, len(U)):
    prev = su5.SIG.iloc[i - 1]
    band = su5.FUB.iloc[i] if prev == "SELL" else su5.FLB.iloc[i]
    marg.append(abs(cl[i] - band))
out["user_min_flip_margin"] = float(np.min(marg))

# ---------------------------------------------------------------- 3. my W-FRI candles from the raw export
r = R.copy()
r["hi"] = r[["open", "high", "low", "close"]].max(axis=1, skipna=True)
r["lo"] = r[["open", "high", "low", "close"]].min(axis=1, skipna=True)
key = r.index + pd.to_timedelta((4 - r.index.dayofweek) % 7, unit="D")  # next Friday (Friday itself if Friday)
g = r.groupby(key)
myW = pd.DataFrame({"Open": g["open"].apply(lambda x: x.dropna().iloc[0] if x.notna().any() else np.nan),
                    "High": g["hi"].max(), "Low": g["lo"].min(),
                    "Close": g["close"].apply(lambda x: x.dropna().iloc[-1]), "Volume": g["volume"].sum()})
myW.index.name = "WeekEnding"
cc = myW.join(U[["Open", "High", "Low", "Close", "Volume"]], rsuffix="_u", how="outer")
out["myWFRI_vs_user"] = {"weeks_mine": len(myW), "weeks_user": len(U),
                         "only_mine": [str(d.date()) for d in myW.index.difference(U.index)],
                         "only_user": [str(d.date()) for d in U.index.difference(myW.index)]}
for col in ["Open", "High", "Low", "Close", "Volume"]:
    bad = cc.index[(cc[col] - cc[col + "_u"]).abs() > 1e-9]
    out["myWFRI_vs_user"][col + "_mismatch"] = [str(d.date()) for d in bad]
# plain high/low (no close-only fill)
g2 = r.groupby(key)
out["myWFRI_plainHL_Low_mismatch"] = [str(d.date()) for d in U.index[(g2["low"].min().reindex(U.index) - U.Low).abs() > 1e-9]]
out["myWFRI_plainHL_High_mismatch"] = [str(d.date()) for d in U.index[(g2["high"].max().reindex(U.index) - U.High).abs() > 1e-9]]

# ---------------------------------------------------------------- 4. calendars: which MCX sessions are not NSE days
mcx = R.index[R["close"].notna() | R["high"].notna() | R["low"].notna() | R["open"].notna()]
non_nse = R.index.difference(nse)
nse_win = nse[(nse >= R.index.min()) & (nse <= pd.Timestamp("2026-09-25"))]
out["mcx_sessions_not_nse_days"] = len(non_nse)
out["mcx_not_nse_weekend"] = [str(d.date()) + " " + d.day_name()[:3] for d in non_nse if d.dayofweek >= 5]
out["mcx_not_nse_weekday_count"] = int((non_nse.dayofweek < 5).sum())
out["nse_days_without_mcx_row"] = [str(d.date()) for d in nse_win.difference(R.index)]
out["nse_days_where_raw_has_no_close"] = [str(d.date()) for d in nse_win.intersection(R.index[R.close.isna()])]
out["nse_weekend_days_in_window"] = [str(d.date()) + " " + d.day_name()[:3] for d in nse_win if d.dayofweek >= 5]
pd.DataFrame({"date": non_nse, "dow": non_nse.day_name(), "close": R.loc[non_nse, "close"].values}).to_csv(HERE / "mcx_sessions_not_on_nse_calendar.csv", index=False)


# ---------------------------------------------------------------- 5. ST.py-style candles built my way (NSE calendar + ffill, ISO-week-number change)
def stpy_candles(daily, cal):
    """daily: DataFrame high/low/close indexed by date. cal: calendar to reindex to. ST.py logic: reindex, ffill,
    new week when the ISO week NUMBER changes between consecutive rows; label = last row of the group."""
    d = daily[["high", "low", "close"]].reindex(cal).ffill()
    wk = d.index.isocalendar().week.values.astype(int)
    grp = np.r_[0, np.cumsum(wk[1:] != wk[:-1])]
    d["g"] = grp
    gg = d.groupby("g")
    w = pd.DataFrame({"High": gg["high"].max().values, "Low": gg["low"].min().values, "Close": gg["close"].last().values},
                     index=pd.DatetimeIndex(gg.apply(lambda x: x.index[-1]).values))
    return w


cal0 = nse[(nse >= pd.Timestamp("2015-02-02")) & (nse <= pd.Timestamp("2026-09-25"))]
clean_daily = C[["high", "low", "close"]]
w_mine = stpy_candles(clean_daily, cal0)
out["my_stpy_candles_vs_weekIndexDf"] = {
    "rows_mine": len(w_mine), "rows_W": len(W), "same_index": bool(w_mine.index.equals(W.index)),
    "max_abs_HLC": float(max((w_mine[c] - W[c]).abs().max() for c in ["High", "Low", "Close"]))}

# raw daily with close-only fill for the ST.py-style counterfactuals (matches the user file's treatment)
raw_daily = pd.DataFrame({"high": r["hi"], "low": r["lo"], "close": r["close"]})


def iso_friday(d):
    return d + pd.Timedelta(days=4 - d.dayofweek)


def sig_series_on_friday(w, start):
    s = supertrend(w["High"], w["Low"], w["Close"], start=start).set_index(w.index)
    s["fri"] = [iso_friday(d) for d in s.index]
    return s


# ---------------------------------------------------------------- 6. user vs Master SIGN, two mappings
Mf = M.copy()
Mf["fri_iso"] = [iso_friday(d) for d in Mf.index]
Mf["fri_wfri"] = [d + pd.Timedelta(days=(4 - d.dayofweek) % 7) for d in Mf.index]  # W-FRI bucket of the label date
res_map = {}
for mp in ("fri_iso", "fri_wfri"):
    dup = int(Mf[mp].duplicated().sum())
    x = Mf.reset_index().set_index(mp).join(U[["Signal", "Close", "Supertrend"]], how="inner")
    x = x[~x.index.duplicated(keep=False)]
    diff = x[x.SIGN != x.Signal]
    res_map[mp] = {"dup_after_map": dup, "common": len(x), "agree": int((x.SIGN == x.Signal).sum()),
                   "diff": [f"{d.date()} (ST.py label {row.Date.date()}): user {row.Signal}, ST.py {row.SIGN}" for d, row in diff.iterrows()],
                   "close_diff_weeks": int(((x.Index - x.Close).abs() > 1e-9).sum()),
                   "st_line_diff_gt_0p05": int(((x.ST - x.Supertrend).abs() > 0.05).sum())}
out["user_vs_master"] = res_map
x = Mf.reset_index().set_index("fri_iso").join(U[["Signal", "Close", "Supertrend", "UpperBand", "LowerBand"]], how="outer")
x.index.name = "friday"
x["label_dow"] = pd.to_datetime(x["Date"]).dt.day_name()
x["sign_differs"] = x.SIGN.notna() & x.Signal.notna() & (x.SIGN != x.Signal)
x[["Date", "label_dow", "SIGN", "Signal", "Index", "Close", "ST", "Supertrend", "FUB", "UpperBand", "FLB", "LowerBand", "sign_differs"]].to_csv(HERE / "user_vs_master_by_friday.csv")
out["user_only_weeks"] = [f"{d.date()} {x.loc[d,'Signal']}" for d in x.index[x.Date.isna()]]
out["master_only_weeks"] = [str(d.date()) for d in x.index[x.Signal.isna() & x.Date.notna()]]
out["non_friday_labels_sign_check"] = [f"{row.Date.date()} {row.label_dow}: ST.py {row.SIGN} user {row.Signal}"
                                       for d, row in x[x.Date.notna() & (x.label_dow != "Friday")].iterrows() if row.label_dow in ("Saturday", "Sunday", "Wednesday")]

# ---------------------------------------------------------------- 7. counterfactuals with my own code
def compare(sig_fri, ref, name):
    """sig_fri: DataFrame with 'fri' and 'SIG'. ref: Series of signals indexed by Friday."""
    s = sig_fri.dropna(subset=["ST"]).set_index("fri")["SIG"]
    s = s[~s.index.duplicated(keep="last")]
    k = s.index.intersection(ref.dropna().index).intersection(Mf.fri_iso)  # the 603 shared weeks
    d = k[s.loc[k].values != ref.loc[k].values]
    return {"name": name, "shared": len(k), "mismatch": len(d), "dates": [str(z.date()) for z in d]}


uref = U["Signal"]
mref = Mf.reset_index().set_index("fri_iso")["SIGN"]
cf = []
# (a) ST.py construction on raw daily, NSE calendar only
cal_nse = nse[(nse >= R.index.min()) & (nse <= pd.Timestamp("2026-09-25"))]
wa = stpy_candles(raw_daily, cal_nse)
for st_ in (4, 5):
    s = sig_series_on_friday(wa, st_)
    cf.append({**compare(s, uref, f"ST.py-style, raw data, NSE cal, start{st_+1} vs USER")})
    cf.append({**compare(s, mref, f"ST.py-style, raw data, NSE cal, start{st_+1} vs MASTER")})
# (b) ST.py construction + all MCX sessions on non-NSE WEEKDAYS (holidays), ISO grouping
hol = non_nse[non_nse.dayofweek < 5]
cal_b = cal_nse.union(hol)
wb = stpy_candles(raw_daily, cal_b)
for st_ in (4, 5):
    s = sig_series_on_friday(wb, st_)
    cf.append(compare(s, uref, f"NSE cal + MCX holiday sessions (ISO weeks), start{st_+1} vs USER"))
    cf.append(compare(s, mref, f"NSE cal + MCX holiday sessions (ISO weeks), start{st_+1} vs MASTER"))
# (c) + weekend MCX sessions too
cal_c = cal_nse.union(non_nse)
wc = stpy_candles(raw_daily, cal_c)
s = sig_series_on_friday(wc, 5)
cf.append(compare(s, uref, "NSE cal + all non-NSE MCX sessions (ISO weeks), start6 vs USER"))
# (d) user W-FRI but only NSE-day MCX sessions (drop MCX on NSE holidays + weekends not in NSE cal)
rd = raw_daily[raw_daily.index.isin(nse)]
kd = rd.index + pd.to_timedelta((4 - rd.index.dayofweek) % 7, unit="D")
gd = rd.groupby(kd)
wd = pd.DataFrame({"High": gd.high.max(), "Low": gd.low.min(), "Close": gd.close.apply(lambda z: z.dropna().iloc[-1])})
sd = supertrend(wd.High, wd.Low, wd.Close, start=4).set_index(wd.index)
sd["fri"] = sd.index
cf.append(compare(sd, uref, "W-FRI, NSE-day sessions only, start5 vs USER"))
cf.append(compare(sd, mref, "W-FRI, NSE-day sessions only, start5 vs MASTER"))
# (e) user W-FRI all sessions from my own candles (should = user)
sm = supertrend(myW.High, myW.Low, myW.Close, start=4).set_index(myW.index)
sm["fri"] = sm.index
cf.append(compare(sm, uref, "my W-FRI all sessions, start5 vs USER"))
cf.append(compare(sm, mref, "my W-FRI all sessions, start5 vs MASTER"))
# (f) only the two named holiday sessions added to ST.py; and removed from user construction
for add in ([pd.Timestamp("2018-11-23")], [pd.Timestamp("2023-04-14")], [pd.Timestamp("2018-11-23"), pd.Timestamp("2023-04-14")],
            [pd.Timestamp("2021-11-05")], [pd.Timestamp("2021-11-19")], [pd.Timestamp("2021-11-05"), pd.Timestamp("2021-11-19")],
            [pd.Timestamp("2023-04-04")]):
    wf = stpy_candles(raw_daily, cal_nse.union(pd.DatetimeIndex(add)))
    s = sig_series_on_friday(wf, 5)
    cf.append(compare(s, mref, f"ST.py-style + {[str(a.date()) for a in add]} vs MASTER"))
    cf.append(compare(s, uref, f"ST.py-style + {[str(a.date()) for a in add]} vs USER"))
    rr = raw_daily.drop(index=add)
    kk = rr.index + pd.to_timedelta((4 - rr.index.dayofweek) % 7, unit="D")
    gq = rr.groupby(kk)
    wq = pd.DataFrame({"High": gq.high.max(), "Low": gq.low.min(), "Close": gq.close.apply(lambda z: z.dropna().iloc[-1])})
    sq = supertrend(wq.High, wq.Low, wq.Close, start=4).set_index(wq.index)
    sq["fri"] = sq.index
    cf.append(compare(sq, uref, f"user W-FRI minus {[str(a.date()) for a in add]} vs USER"))
    cf.append(compare(sq, mref, f"user W-FRI minus {[str(a.date()) for a in add]} vs MASTER"))
out["counterfactuals"] = cf

# single-session toggle scan, independent: add each non-NSE weekday MCX session to ST.py-style frame
tog = []
base = sig_series_on_friday(wa, 5).dropna(subset=["ST"]).set_index("fri")["SIG"]
for d0 in non_nse:
    wf = stpy_candles(raw_daily, cal_nse.union(pd.DatetimeIndex([d0])))
    s = sig_series_on_friday(wf, 5).dropna(subset=["ST"]).set_index("fri")["SIG"]
    s = s[~s.index.duplicated(keep="last")]
    k = s.index.intersection(base.index)
    n = int((s.loc[k] != base.loc[k]).sum())
    if n:
        tog.append({"session": str(d0.date()), "dow": d0.day_name()[:3], "weeks_flipped": n,
                    "first": str(k[(s.loc[k] != base.loc[k]).values][0].date())})
out["single_add_toggles_nonzero"] = tog
out["single_add_toggles_tested"] = len(non_nse)

json.dump(out, open(HERE / "verify_summary.json", "w"), indent=1, default=str)
print(json.dumps(out, indent=1, default=str))
