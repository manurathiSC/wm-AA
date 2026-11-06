"""Candle-difference counts and the two mechanism traces, recomputed independently (read-only)."""
from pathlib import Path
import json
import numpy as np
import pandas as pd
import importlib.util

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("v", HERE / "verify.py")
FRA = Path(r"C:\Users\manur\Repos\wm-research\AA\Historical Data\FRA_MAUc1")
U = pd.read_csv(r"C:\Users\manur\Downloads\MAUc1_weekly_supertrend1.csv.csv", parse_dates=["WeekEnding"]).set_index("WeekEnding")
M = pd.read_excel(FRA / "RSI/Final/Analysis/Master_MAUc1.xlsx")
M["Date"] = pd.to_datetime(M["Date"]); M = M.set_index("Date")
W = pd.read_excel(FRA / "RSI/Final/MAUc1/weekIndexDf_250926_W.xlsx", index_col=0); W.index = pd.to_datetime(W.index)
TD = pd.read_excel(FRA / "Data/TradingDays.xlsx", header=None, skiprows=3); nse = pd.DatetimeIndex(pd.to_datetime(TD[1]))
R = pd.read_csv(r"C:\Users\manur\Downloads\MAUc1_daily1.csv", parse_dates=["Date"]).set_index("Date")
iso_fri = lambda d: d + pd.Timedelta(days=4 - d.dayofweek)
out = {}
Wf = W.copy(); Wf["label"] = Wf.index; Wf["dow"] = Wf.index.day_name().str[:3]; Wf.index = [iso_fri(d) for d in W.index]
j = Wf.join(U[["High", "Low", "Close", "TR"]], rsuffix="_u", how="inner")
for base, idx in (("608_common", j.index), ("603_master", j.index[j.label.isin(M.index)])):
    k = j.loc[idx]
    dh, dl, dc, dt = [(k[c] - k[c + "_u"]).abs() > 1e-9 for c in ("High", "Low", "Close", "TR")]
    out[base] = {"n": len(k), "High": int(dh.sum()), "Low": int(dl.sum()), "Close": int(dc.sum()), "TR": int(dt.sum()),
                 "any_HLC": int((dh | dl | dc).sum()), "TR_only_via_prevclose": int((dt & ~(dh | dl)).sum())}
k = j.loc[j.label.isin(M.index)]
cd = k[(k.Close - k.Close_u).abs() > 1e-9]
# classify: user's last MCX session in that W-FRI week vs ST.py label
rows = []
for fr, r in cd.iterrows():
    sess = R.index[(R.index > fr - pd.Timedelta(days=7)) & (R.index <= fr) & R.CLOSE.notna()]
    last_user = sess[-1]
    rows.append({"friday": fr.date(), "stpy_label": r.label.date(), "label_dow": r.dow, "user_last_close_session": last_user.date(),
                 "user_last_is_nse_day": last_user in nse, "close_stpy": r.Close, "close_user": r.Close_u})
cdf = pd.DataFrame(rows); cdf.to_csv(HERE / "close_diff_weeks.csv", index=False)
out["close_diff"] = {"n": len(cdf), "label_dow": cdf.label_dow.value_counts().to_dict(),
                     "user_ends_on_non_nse_session": int((~cdf.user_last_is_nse_day).sum()),
                     "wed_label_weeks": [str(x) for x in cdf.loc[cdf.label_dow == "Wed", "friday"]],
                     "weekend_label_weeks": [f"{a} ({b})" for a, b in cdf.loc[cdf.label_dow.isin(["Sat", "Sun"]), ["friday", "stpy_label"]].values]}
# traces
t = pd.read_csv(HERE / "user_vs_master_by_friday.csv", index_col=0, parse_dates=True)
for a, b in (("2018-11-16", "2019-01-18"), ("2023-04-07", "2023-07-07")):
    x = t.loc[a:b, ["Date", "SIGN", "Signal", "Index", "Close", "FUB", "UpperBand", "FLB", "LowerBand"]]
    x = x.join(M[["EMA_TR"]].rename(index=iso_fri)).join(U[["LW_ATR5", "TR"]]).join(Wf[["TR"]].rename(columns={"TR": "TR_st"}))
    out[f"trace_{a}"] = x.round(2).astype(str).reset_index().values.tolist()
json.dump(out, open(HERE / "verify_candles_summary.json", "w"), indent=1, default=str)
print(json.dumps({k: v for k, v in out.items() if not k.startswith("trace")}, indent=1, default=str))
for kk in [k for k in out if k.startswith("trace")]:
    print(kk)
    for row in out[kk]:
        print("  ", row)
