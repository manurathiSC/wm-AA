"""T01 adversarial review, step 3: every config's equity targets recomputed from spliced_inputs.csv
(and the Master files for triple), with code written from T01.md section 3, vs
decisions_all_configs.csv. Also a look-ahead probe: the value at d recomputed after DELETING every
close after d (and, for st_weekly, every close after d in the calendar).
"""
from pathlib import Path

import numpy as np
import pandas as pd

AA = Path(__file__).resolve().parents[3]
EV = AA / "tests" / "T01" / "evidence"
BOOK2PAR = {"SCMO_0042": "SCMO_0003", "SCMO_0043": "SCMO_0007", "SCMO_0044": "SCMO_0010", "SCMO_0045": "SCMO_0029"}

sp = pd.read_csv(EV / "headline" / "spliced_inputs.csv", parse_dates=["date"])
cal = pd.DatetimeIndex(sp.date)
iso = cal.isocalendar()
wk = (iso.year.astype(int) * 100 + iso.week.astype(int)).to_numpy()
low = np.r_[wk[1:] != wk[:-1], True]


def window(name):
    if name == "W1":
        i0 = int(np.flatnonzero(cal <= pd.Timestamp("2015-07-31"))[-1]); iE = int(cal.get_loc(pd.Timestamp("2021-10-29")))
    else:
        i0 = int(cal.get_loc(pd.Timestamp("2021-11-01"))); iE = int(cal.get_loc(pd.Timestamp("2026-08-21")))
    return i0, iE, np.array([i0] + [i for i in range(i0 + 1, iE + 1) if low[i]])


def st_series(closes, keys):
    """production getSupertrend on weekly candles of closes (H=max, L=min, C=last); returns per candle (C-ST, sell)."""
    df = pd.DataFrame({"c": closes, "k": keys})
    g = df.groupby("k", sort=False)["c"]
    Hh, Ll, Cc = g.max().to_numpy(), g.min().to_numpy(), g.last().to_numpy()
    n = len(Cc)
    PC = np.r_[np.nan, Cc[:-1]]
    TR = np.nanmax(np.vstack([Hh - Ll, np.abs(Hh - PC), np.abs(Ll - PC)]), axis=0)
    w = np.arange(1, 6) / 15.0
    FUB = np.full(n, np.nan); FLB = np.full(n, np.nan); ST = np.full(n, np.nan)
    for r in range(5, n):
        eatr = np.dot(w, TR[r - 4:r + 1])
        ah = 0.5 * Hh[r] + 0.5 * Ll[r]
        bub, blb = ah + 2 * eatr, ah - 2 * eatr
        if r == 5:
            fub, flb, st = bub, blb, bub
        else:
            pfub, pflb, pst = FUB[r - 1], FLB[r - 1], ST[r - 1]
            fub = bub if (bub < pfub or PC[r] > pfub) else pfub
            flb = blb if (blb > pflb or PC[r] < pflb) else pflb
            c = Cc[r]
            if pst == pfub and c <= fub: st = fub
            elif pst == pfub and c > fub: st = flb
            elif pst == pflb and c >= flb: st = flb
            elif pst == pflb and c < fub: st = fub
            else: st = 0
        FUB[r], FLB[r], ST[r] = fub, flb, st
    return Cc - ST, (ST == FUB), FUB


# Master files
master = {}
for nm in ("Nifty100", "MC100", "SC100"):
    m = pd.read_excel(AA / "Historical Data/frozen_2026-09-25/Master" / f"Master_{nm}.xlsx")
    m["Date"] = pd.to_datetime(m["Date"])
    m = m.dropna(subset=["Date"]).sort_values("Date")
    master[nm] = m
    wd = m.Date.dt.weekday.value_counts().sort_index().to_dict()
    print(f"Master_{nm}: rows {len(m)} {m.Date.min().date()}..{m.Date.max().date()} weekday counts {wd}; columns {list(m.columns)[:12]}")
    # is each label the last calendar session of its ISO week (within our calendar span)?
    lab_in_cal = m.Date[(m.Date >= cal[0]) & (m.Date <= cal[-1])]
    lw = set(cal[low])
    notlast = [d.date().isoformat() for d in lab_in_cal if d not in lw]
    print(f"   labels inside our calendar that are NOT our week-last session: {len(notlast)} {notlast[:10]}")


def buys_at(d):
    n = 0
    labs = []
    for nm, m in master.items():
        s = m[m.Date <= d]
        labs.append(s.Date.iloc[-1])
        n += int(s.SIGN.iloc[-1] == "BUY")
    return n, max(labs)


dec = pd.read_csv(EV / "headline" / "decisions_all_configs.csv", keep_default_na=False, na_values=[""])
print("decisions rows", len(dec), "configs", dec.config.nunique())
dec["key"] = dec.config + "|" + dec.book + "|" + dec.window + "|" + dec.decision_date
E = dec.set_index("key")

mism = {}
look = {}
rows_cmp = 0
for b, p in BOOK2PAR.items():
    Pv = sp[f"P_{p}"].to_numpy()
    st_full_val, st_full_sell, _ = st_series(Pv, wk)
    # candle index of each session
    cand = np.cumsum(np.r_[True, wk[1:] != wk[:-1]]) - 1
    for wn in ("W1", "W2"):
        i0, iE, D = window(wn)
        out = {}
        hy = 1.0
        for i in D:
            pc65 = 100 * np.sum(Pv[i - 65:i] < Pv[i]) / 65
            for W in (20, 40, 65, 130, 250):
                pw = 100 * np.sum(Pv[i - W:i] < Pv[i]) / W
                for q in (10, 25, 40):
                    out.setdefault(f"pct_w{W}_q{q}", []).append((i, pw, 0.0 if pw < q else 1.0))
            if pc65 < 25: hy = 0.0
            elif pc65 >= 50: hy = 1.0
            out.setdefault("pct_w65_hyst", []).append((i, pc65, hy))
            out.setdefault("pct_w65_step", []).append((i, pc65, 1.0 if pc65 >= 50 else (0.5 if pc65 >= 25 else 0.0)))
            for n in (50, 100, 200):
                sma = Pv[i - n + 1:i + 1].mean()
                out.setdefault(f"sma_{n}", []).append((i, Pv[i] / sma - 1, 0.0 if Pv[i] < sma else 1.0))
            for L in (65, 130, 250):
                v = Pv[i] / Pv[i - L] - 1
                out.setdefault(f"tsmom_{L}", []).append((i, v, 0.0 if v < 0 else 1.0))
            mx = Pv[i - 249:i + 1].max()
            for lab, X in (("x7p5", 7.5), ("x10", 10), ("x15", 15)):
                v = Pv[i] / mx - 1
                out.setdefault(f"ddhigh_250_{lab}", []).append((i, v, 0.0 if v < -X / 100 else 1.0))
            # st: completed weeks only. Look-ahead probe: rebuild candles from closes[:i+1] ONLY.
            vtr, strunc, _ = st_series(Pv[:i + 1], wk[:i + 1])
            if low[i]:
                cv, cs = vtr[-1], strunc[-1]          # d's own week is complete
                assert abs(st_full_val[cand[i]] - cv) <= 1e-9 * max(1, abs(cv)), ("st look-ahead", b, wn, cal[i])
            else:
                cv, cs = vtr[-2], strunc[-2]          # last complete week
                look.setdefault("st_partial_candle_alt", []).append((b, wn, cal[i].date(), vtr[-1], bool(strunc[-1]), cv, bool(cs)))
            out.setdefault("st_weekly", []).append((i, cv, 0.0 if cs else 1.0))
            nb, _ = buys_at(cal[i])
            out.setdefault("triple", []).append((i, float(nb), 1.0 if nb == 3 else 0.0))
            out.setdefault("triple_and_pct25", []).append((i, pc65, 1.0 if (nb == 3 and pc65 >= 25) else 0.0))
        # daily
        hy = None
        for i in range(i0, iE + 1):
            pc65 = 100 * np.sum(Pv[i - 65:i] < Pv[i]) / 65
            out.setdefault("pct_w65_q25_daily", []).append((i, pc65, 0.0 if pc65 < 25 else 1.0))
        for c, lst in out.items():
            eq = np.array([x[2] for x in lst])
            w = eq[:-1]
            chg = np.r_[True, w[1:] != w[:-1]]
            for j, (i, v, e) in enumerate(lst):
                key = f"{c}|{b}|{wn}|{cal[i].strftime('%Y-%m-%d')}"
                r = E.loc[key]
                rows_cmp += 1
                tsess = cal[i + 1].strftime("%Y-%m-%d") if (j < len(lst) - 1 and chg[j]) else ""
                bad = []
                if r.equity_target != e: bad.append("target")
                if abs(r.value - v) > 1e-9 * max(1, abs(v)): bad.append("value")
                if (r.trade_session if isinstance(r.trade_session, str) else "") != tsess: bad.append("tsess")
                if bad:
                    mism.setdefault(c, []).append((b, wn, cal[i].date(), bad, r.value, v, r.equity_target, e))

print("rows compared", rows_cmp, "of", len(dec))
for c, lst in mism.items():
    print(f"MISMATCH {c}: {len(lst)}; e.g. {lst[:4]}")
if not mism:
    print("no mismatches in equity_target / value / trade_session for any config")
print("st_weekly at non-week-end decisions (only W2 T0): (book, win, d, partial-candle value, partial sell, adopted value, adopted sell)")
for x in look.get("st_partial_candle_alt", []):
    print("  ", x)

# triple: Master label convention -- is SIGN at label L computable from data <= L? (labels on Fridays/last session)
# list Master labels that fall on non-last-of-week sessions inside the windows, and stale cases
for nm, m in master.items():
    m2 = m[(m.Date >= "2015-07-31") & (m.Date <= "2026-08-21")]
    later = []
    for d in cal[low][(cal[low] >= "2015-07-31") & (cal[low] <= "2026-08-21")]:
        # next master label after the latest label <= d is within the same ISO week -> stale read
        s = m.Date[m.Date <= d]
        nxt = m.Date[m.Date > d]
        if len(nxt) and nxt.iloc[0].isocalendar()[:2] == d.isocalendar()[:2]:
            later.append((d.date().isoformat(), nxt.iloc[0].date().isoformat()))
    print(f"Master_{nm}: week-end sessions whose same-ISO-week Master label is AFTER d: {later}")
