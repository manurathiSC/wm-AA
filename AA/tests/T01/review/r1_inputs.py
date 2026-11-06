"""T01 adversarial review, step 1: rebuild the spliced inputs from the raw files, independently.

Reads only raw files and evidence/<run>/spliced_inputs.csv. Writes nothing but stdout.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

AA = Path(__file__).resolve().parents[3]
EV = AA / "tests" / "T01" / "evidence"
BOOK2PAR = {"SCMO_0042": "SCMO_0003", "SCMO_0043": "SCMO_0007", "SCMO_0044": "SCMO_0010", "SCMO_0045": "SCMO_0029"}

nav = pd.read_csv(AA / "analysis/evidence/final_strategy/nav_curves_daily.csv", index_col=0)
nav.index = pd.to_datetime(nav.index)
pub = pd.read_csv(AA / "Historical Data/parentIndices.csv")
pub["date"] = pd.to_datetime(pub["date"], format="%d/%m/%y %H:%M")
print("published rows", len(pub), "scids", sorted(pub.scid.unique()))
print("published time-of-day values:", pub.date.dt.time.unique()[:5])

H, Pb = {}, {}
for b, p in BOOK2PAR.items():
    s = nav[f"before the books 2014-07 -> 2021-10|{b}|parent (no overlay)"].dropna()
    H[p] = s
    Pb[p] = pub[pub.scid == p].set_index("date")["index"].sort_index()
    print(b, p, "harness", s.index.min().date(), s.index.max().date(), len(s),
          "| published", Pb[p].index.min().date(), Pb[p].index.max().date(), len(Pb[p]),
          "pub first", Pb[p].iloc[0])
hs = [set(v.index) for v in H.values()]
ps = [set(v.index) for v in Pb.values()]
print("harness date sets identical across parents:", all(x == hs[0] for x in hs))
print("published date sets identical across parents:", all(x == ps[0] for x in ps))
cal = pd.DatetimeIndex(sorted(set().union(*hs, *ps)))
print("calendar", len(cal), cal[0].date(), cal[-1].date())
print("weekend sessions in calendar:", [d.date().isoformat() for d in cal if d.weekday() >= 5])
gap = cal[(cal > pd.Timestamp("2021-10-29")) & (cal < pd.Timestamp("2021-11-01"))]
print("sessions strictly between harness end and published start:", list(gap))
# dates in nav_curves index (non-null in any column) not in the calendar
extra = sorted(set(nav.index[nav.notna().any(axis=1)]) - set(cal))
print("nav_curves dates (any column non-null) not in calendar:", [d.date().isoformat() for d in extra][:20])

sp = pd.read_csv(EV / "headline" / "spliced_inputs.csv", parse_dates=["date"])
print("spliced_inputs rows", len(sp), "calendar equal:", pd.DatetimeIndex(sp.date).equals(cal))

mx = 0.0
for p in BOOK2PAR.values():
    h, q = H[p], Pb[p]
    anchor = h.loc["2021-10-29"]
    a = pd.Series(np.nan, index=cal)
    a.loc[cal <= "2021-10-29"] = h.reindex(cal[cal <= "2021-10-29"]).to_numpy()
    a.loc[cal >= "2021-11-01"] = (q.reindex(cal[cal >= "2021-11-01"]) / q.loc["2021-11-01"] * anchor).to_numpy()
    assert a.notna().all()
    d = np.abs(a.to_numpy() / sp[f"P_{p}"].to_numpy() - 1).max()
    mx = max(mx, d)
    r = a.pct_change()
    print(f"  {p}: max rel diff vs evidence {d:.2e}; splice-session return {r.loc['2021-11-01']:.3e}; "
          f"max |daily ret| {r.abs().max():.3f} on {r.abs().idxmax().date()}")
print("P max rel diff overall", mx)

# GOLDBEES
g = pd.read_csv(AA / "analysis/evidence/final_strategy/gold_daily_ohlc_eikon.csv", parse_dates=["date"]).set_index("date")["close"]
print("gold rows", len(g), g.index.min().date(), g.index.max().date(), "dups", g.index.duplicated().sum())
gr = g.pct_change()
print("gold largest |daily returns|:")
print(gr.abs().sort_values(ascending=False).head(6).to_string())
lb = pd.read_csv(AA / "Historical Data/LBES_Adjusted_Price_data_2026_08_10.csv")
lb["date"] = pd.to_datetime(lb["date"], format="%d/%m/%y %H:%M")
lb = lb.set_index("date")["price"]
print("lbes rows", len(lb), lb.index.min().date(), lb.index.max().date(), "dups", lb.index.duplicated().sum())
lr = lb.pct_change()
print("lbes largest |returns|:")
print(lr.abs().sort_values(ascending=False).head(6).to_string())


def asof(s, cal):
    s = s.sort_index()
    idx = np.searchsorted(s.index.values, cal.values, side="right") - 1
    assert (idx >= 0).all()
    return pd.Series(s.to_numpy()[idx], index=cal)


ga, la = asof(g, cal), asof(lb, cal)
gf = g.reindex(cal).ffill()
lf = lb.reindex(cal).ffill()
print("gold as-of vs evidence max rel diff", np.abs(ga.to_numpy() / sp.gold.to_numpy() - 1).max())
print("lbes as-of vs evidence max rel diff", np.abs(la.to_numpy() / sp.cash.to_numpy() - 1).max())
print("gold: sessions where calendar-ffill != as-of:", int((np.abs(gf - ga) > 1e-12).sum()),
      "first-session NaN in ffill:", int(gf.isna().sum()))
dl = (np.abs(lf - la) > 1e-12)
print("lbes: sessions where calendar-ffill != as-of:", int(dl.sum()), "max abs", float(np.abs(lf - la).max()))
print("sessions after LBES file end", int((cal > lb.index.max()).sum()), [d.date().isoformat() for d in cal[cal > lb.index.max()]])
print("gold sessions w/o own obs", int((~cal.isin(g.index)).sum()), "lbes sessions w/o own obs", int((~cal.isin(lb.index)).sum()))
# where is gold stale for more than 3 sessions in a row?
own = cal.isin(g.index)
runs, cur = [], 0
for i, o in enumerate(own):
    cur = 0 if o else cur + 1
    if cur >= 3:
        runs.append(cal[i].date().isoformat())
print("gold stale >= 3 consecutive sessions at:", runs[:20])
own = cal.isin(lb.index)
runs, cur = [], 0
for i, o in enumerate(own):
    cur = 0 if o else cur + 1
    if cur >= 3:
        runs.append(cal[i].date().isoformat())
print("lbes stale >= 3 consecutive sessions at:", runs[:30])
