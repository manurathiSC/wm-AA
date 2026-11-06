"""Independent check of the backtest-impact claims (read-only; writes only to this folder)."""
from pathlib import Path
import json
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
EV = Path(r"C:\Users\manur\Repos\wm-research\AA\analysis\evidence\final_strategy")
IMP = EV / "mauc1" / "user_weekly_check" / "impact"
FRA = Path(r"C:\Users\manur\Repos\wm-research\AA\Historical Data\FRA_MAUc1")
U = pd.read_csv(r"C:\Users\manur\Downloads\MAUc1_weekly_supertrend1.csv.csv", parse_dates=["WeekEnding"]).set_index("WeekEnding")
M = pd.read_excel(FRA / "RSI/Final/Analysis/Master_MAUc1.xlsx")
M["Date"] = pd.to_datetime(M["Date"])
M = M.set_index("Date")
W = pd.read_excel(FRA / "RSI/Final/MAUc1/weekIndexDf_250926_W.xlsx", index_col=0)
W.index = pd.to_datetime(W.index)
out = {"weekIndex_label_dow": W.index.day_name().value_counts().to_dict()}

iso_fri = lambda d: d + pd.Timedelta(days=4 - d.dayofweek)
usig = U["Signal"].map({"BUY": 1.0, "SELL": 0.0})
msig = M["SIGN"].map({"BUY": 1.0, "SELL": 0.0})
share = lambda g: 0.5 if np.isnan(g) else (0.8 if g == 1.0 else 0.2)

rows = []
for win, f in (("2014_2021", "weekly_signals_2014_2021.csv"), ("live", "weekly_signals_live.csv")):
    b = pd.read_csv(EV / f, parse_dates=["review", "entry_session"])
    u = pd.read_csv(IMP / "user" / f, parse_dates=["review", "entry_session"])
    assert (b.review.values == u.review.values).all()
    for i, rb in b.iterrows():
        r = rb.review
        # what gold_at would return from Master (latest label <= r)
        idx = msig.index[msig.index <= r]
        g_m = msig.loc[idx[-1]] if len(idx) else np.nan
        lab = idx[-1] if len(idx) else pd.NaT
        # user signal for the review's own ISO week (Friday of the review's Mon-Sun week)
        fr = iso_fri(r)
        g_u = usig.get(fr, np.nan)
        # stale check: is the Master label read in the same ISO week as the review?
        same_wk = (not pd.isna(lab)) and (iso_fri(lab) == fr)
        sleeve = 1.0 - rb.equity_w
        rows.append({"window": win, "review": r.date(), "dow": r.day_name()[:3], "decision": rb.decision, "sleeve": sleeve,
                     "master_label_read": None if pd.isna(lab) else lab.date(), "same_iso_week": same_wk,
                     "baseline_gold_signal": rb.gold_signal, "my_master_read": g_m, "my_user_read": g_u,
                     "impact_user_gold_signal": u.loc[i, "gold_signal"],
                     "baseline_gold_w": rb.gold_w, "my_user_gold_w": sleeve * share(g_u), "impact_user_gold_w": u.loc[i, "gold_w"],
                     "impact_user_decision": u.loc[i, "decision"]})
df = pd.DataFrame(rows)
df.to_csv(HERE / "impact_review_check.csv", index=False)
eqn = lambda a, b: (a == b) | (pd.isna(a) & pd.isna(b))
out["reviews"] = len(df)
out["reviews_by_window"] = df.window.value_counts().to_dict()
out["baseline_signal_equals_my_master_read"] = int(eqn(df.baseline_gold_signal, df.my_master_read).sum())
out["reviews_reading_other_iso_week"] = df.loc[~df.same_iso_week, ["window", "review", "master_label_read", "baseline_gold_signal"]].astype(str).values.tolist()
out["impact_user_signal_equals_my_user_read"] = int(eqn(df.impact_user_gold_signal, df.my_user_read).sum())
out["impact_user_signal_mismatch_rows"] = df.loc[~eqn(df.impact_user_gold_signal, df.my_user_read), ["window", "review", "impact_user_gold_signal", "my_user_read"]].astype(str).values.tolist()
out["decision_changed_in_user_run"] = int((df.decision != df.impact_user_decision).sum())
sd = df[~eqn(df.my_master_read, df.my_user_read)]
out["reviews_where_signal_differs"] = sd[["window", "review", "dow", "decision", "my_master_read", "my_user_read"]].astype(str).values.tolist()
gw = df[(df.baseline_gold_w - df.my_user_gold_w).abs() > 1e-12]
out["reviews_where_gold_w_differs_mine"] = gw[["window", "review", "decision", "baseline_gold_w", "my_user_gold_w"]].astype(str).values.tolist()
out["my_user_gold_w_equals_impact_user_gold_w"] = int(((df.my_user_gold_w - df.impact_user_gold_w).abs() < 1e-12).sum())
nonfri = df[df.dow != "Fri"]
out["nonfriday_reviews"] = {"n": len(nonfri), "dows": nonfri.dow.value_counts().to_dict(),
                            "in_sleeve": nonfri.loc[nonfri.sleeve > 0, ["window", "review", "dow", "my_master_read", "my_user_read"]].astype(str).values.tolist()}
# alternative (stale) mapping: user row keyed by its Friday date and read with gold_at (latest <= review)
stale = []
for _, r0 in df.iterrows():
    r = pd.Timestamp(r0.review)
    idx = usig.index[usig.index <= r]
    g = usig.loc[idx[-1]] if len(idx) else np.nan
    if not eqn(pd.Series([g]), pd.Series([r0.my_user_read])).iloc[0]:
        stale.append([r0.window, str(r0.review), r0.dow, r0.decision, g, r0.my_user_read])
out["naive_friday_key_would_differ_at"] = stale

# summary stats: baseline vs impact/stpy vs impact/user for the FINAL rule
bs = pd.read_csv(EV / "summary_stats.csv")
ss = pd.read_csv(IMP / "stpy" / "summary_stats.csv")
us = pd.read_csv(IMP / "user" / "summary_stats.csv")
key = ["period", "aa", "strategy"]
num = [c for c in bs.columns if bs[c].dtype.kind == "f"]
m1 = bs.merge(ss, on=key, suffixes=("", "_s"))
out["baseline_vs_impact_stpy_rows"] = [len(bs), len(ss), len(m1)]
out["baseline_vs_impact_stpy_maxabs"] = float(max((m1[c] - m1[c + "_s"]).abs().max() for c in num))
fin = "FINAL: triple + 80/20 gold-timed sleeve (weekly re-check)"
m2 = bs.merge(us, on=key, suffixes=("_b", "_u"))
f2 = m2[m2.strategy == fin][["period", "aa", "cagr_b", "cagr_u", "max_dd_daily_b", "max_dd_daily_u", "max_dd_friday_b", "max_dd_friday_u", "total_return_b", "total_return_u"]]
f2 = f2.assign(d_cagr_pp=100 * (f2.cagr_u - f2.cagr_b), d_dd_pp=100 * (f2.max_dd_daily_u - f2.max_dd_daily_b),
               d_ddf_pp=100 * (f2.max_dd_friday_u - f2.max_dd_friday_b), endnav_ratio=(1 + f2.total_return_u) / (1 + f2.total_return_b))
f2.to_csv(HERE / "final_rule_impact_check.csv", index=False)
out["final_rule"] = f2.round(6).astype(str).values.tolist()
changed = m2[[any(abs(r[c + "_b"] - r[c + "_u"]) > 1e-12 for c in ["cagr", "max_dd_daily", "total_return"]) for _, r in m2.iterrows()]]
out["strategies_changed"] = sorted(set(changed.strategy))
out["strategies_only_in_one"] = sorted(set(bs.strategy) ^ set(us.strategy))

# rough independent NAV check: 60% of NAV in cash vs GOLDBEES from 2018-12-10 to 2019-01-14 fills
gf = pd.read_csv(EV / "goldbees_fill_despiked.csv", index_col=0, parse_dates=True)
out["goldbees_fill_2018-12-10_to_2019-01-14"] = [float(gf.loc["2018-12-10", "fill_ohlc4_clean"]), float(gf.loc["2019-01-14", "fill_ohlc4_clean"])]
json.dump(out, open(HERE / "verify_impact_summary.json", "w"), indent=1, default=str)
print(json.dumps(out, indent=1, default=str))
