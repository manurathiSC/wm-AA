"""Ad-hoc study (Manu, chat 2026-11-25): gold's 2026 sell-off while the AA rule is OUT of equity and gold is SELL.

    python analysis/gold_selloff.py          # writes analysis/evidence/gold_selloff/

Questions
  1. How large is the current fall, in % and in sigma units of gold's own volatility?
  2. When did falls like it happen before (2003-2026), and what did gold do next (4, 13, 26, 52 weeks)?
  3. What did the MAUc1 signal and Indian equities do after those falls?

Descriptive only: no null, no pre-registration, thresholds shown as a sweep, overlapping events de-clustered.
Every input is an APPROVED row of data/APPROVED_DATA.md (as of 2026-11-25):
  gold    D24c MAUc1 cleaned daily 2003-11-10 -> 2026-11-20 (MCX gold futures, continuous, Rs/10 g; Manu's export,
          then Postgres ohlcv_eikon_futures from 2026-11-12). Before D24c existed the last two weeks were chained from
          GOLDBEES (commit d6b3531); the chaining code stays and now adds nothing;
          GOLDBEES itself is not used for history: it traded ~6% rich to MCX gold at the January 2026 peak.
  signal  D24c MAUc1 weekly supertrend (SIGN) to 2026-11-20
  equity  D25 + D25d Nifty 100 / Midcap 100 / Smallcap 100 daily closes; D03 (2026-11-20) weekly SIGNs
          (Smallcap 100 signal used only from 2011-11-25, prices only from 2011-10-03: rule 7)
The last complete week is the one ending Friday 2026-11-20.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

AA = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AA / "analysis"))
from approved_data import require  # noqa: E402

OUT = AA / "analysis" / "evidence" / "gold_selloff"
LAST = pd.Timestamp("2026-11-20")
SC_PRICE_FROM, SC_SIGN_FROM = pd.Timestamp("2011-10-03"), pd.Timestamp("2011-11-25")
HD = AA / "Historical Data"
F = dict(
    mau=HD / "extended_2026-11-20/MAUc1_from_2003/mauc1_daily_clean_extended.csv",
    mau_w=HD / "extended_2026-11-20/MAUc1_from_2003/mauc1_supertrend_weekly_extended.csv",
    gb=AA / "analysis/cache/why_gold_ohlc_eikon_extended_2026-11-23.parquet",
    **{f"px_{n}_old": HD / f"extended_2026-11-12/index_daily_pre2019/{n}_daily_ohlcv.csv" for n in ("Nifty100", "MC100", "SC100")},
    **{f"px_{n}_new": HD / f"extended_2026-11-20/index_daily_2019_2026/{n}_daily_ohlcv.csv" for n in ("Nifty100", "MC100", "SC100")},
    **{f"sig_{n}": HD / f"extended_2026-11-20/Master/Master_{n}.xlsx" for n in ("Nifty100", "MC100", "SC100")},
)
HORIZONS = [4, 13, 26, 52]
COOLDOWN = 26


def load():
    for p in F.values():
        require(p)
    mau = pd.read_csv(F["mau"], parse_dates=["date"]).set_index("date")["close"].astype(float)
    gb = pd.read_parquet(F["gb"]).assign(date=lambda d: pd.to_datetime(d["date"])).set_index("date")["close"].astype(float)
    wk = mau.resample("W-FRI").last().dropna()
    gbw = gb[gb.index <= LAST].resample("W-FRI").last()
    tail = wk.iloc[-1] * gbw.loc[wk.index[-1]:] / gbw.loc[wk.index[-1]]
    gold = pd.concat([wk, tail.iloc[1:]])
    gold = gold[gold.index <= LAST]
    src = pd.Series("MAUc1", index=gold.index)
    src[src.index > wk.index[-1]] = "GOLDBEES-chained"
    sw = pd.read_csv(F["mau_w"], parse_dates=["review"]).set_index("review")["SIGN"]
    eq, sig = {}, {}
    for n in ("Nifty100", "MC100", "SC100"):
        a = pd.read_csv(F[f"px_{n}_old"], parse_dates=["date"]).set_index("date")["close"]
        b = pd.read_csv(F[f"px_{n}_new"], parse_dates=["date"]).set_index("date")["close"]
        s = pd.concat([a[a.index < b.index.min()], b]).astype(float)
        if n == "SC100":
            s = s[s.index >= SC_PRICE_FROM]
        eq[n] = s.resample("W-FRI").last().dropna()
        m = pd.read_excel(F[f"sig_{n}"], parse_dates=["Date"]).set_index("Date")["SIGN"]
        if n == "SC100":
            m = m[m.index >= SC_SIGN_FROM]
        sig[n] = m
    return gold, src, mau, gb, sw, eq, sig


def asof(s: pd.Series, t):
    x = s[s.index <= t]
    return x.iloc[-1] if len(x) else None


def zscores(p: pd.Series) -> pd.DataFrame:
    r = np.log(p).diff()
    out = pd.DataFrame(index=p.index)
    for k in (1, 2, 4, 8, 13, 26):
        sig = r.shift(k).rolling(52).std()             # volatility of the 52 weeks BEFORE the k-week move
        out[f"z{k}"] = r.rolling(k).sum() / (sig * np.sqrt(k))
        out[f"ret{k}"] = p / p.shift(k) - 1
    out["vol52_ann"] = r.rolling(52).std() * np.sqrt(52)
    out["dd_ath"] = p / p.cummax() - 1
    out["dd_52w"] = p / p.rolling(52, min_periods=1).max() - 1
    d = r.copy()
    up, dn = d.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean(), (-d.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    out["rsi14w"] = 100 - 100 / (1 + up / dn)
    ma = p.rolling(40).mean()
    out["below_ma40_pct"] = p / ma - 1
    return out


def triggers(cond: pd.Series) -> list[pd.Timestamp]:
    t, last = [], None
    for d, v in cond.items():
        if v and (last is None or (cond.index.get_loc(d) - cond.index.get_loc(last)) > COOLDOWN):
            t.append(d)
            last = d
        elif v:
            last = d if False else last
    return t


def forward(p: pd.Series, t) -> dict:
    i = p.index.get_loc(t)
    o = {}
    for h in HORIZONS:
        o[f"fwd{h}"] = float(p.iloc[i + h] / p.iloc[i] - 1) if i + h < len(p) else None
    nxt = p.iloc[i + 1:i + 27]
    o["further_fall_26w"] = float(nxt.min() / p.iloc[i] - 1) if len(nxt) else None
    o["low_week"] = str(nxt.idxmin().date()) if len(nxt) else None
    peak = p.iloc[max(0, i - 52):i + 1].max()
    after = p.iloc[i + 1:]
    rec = after[after >= peak]
    o["weeks_to_regain_52w_high"] = int(p.index.get_loc(rec.index[0]) - i) if len(rec) else None
    return o


def baseline(p: pd.Series) -> dict:
    out = {}
    for h in HORIZONS:
        f = (p.shift(-h) / p - 1).dropna()
        out[f"fwd{h}"] = {"mean": float(f.mean()), "median": float(f.median()), "share_up": float((f > 0).mean()), "n": int(len(f))}
    return out


def main() -> int:
    gold, src, mau, gb, sw, eq, sig = load()
    Z = zscores(gold)
    cur = Z.iloc[-1]
    OUT.mkdir(parents=True, exist_ok=True)

    # 1. current event
    daily_peak = mau.idxmax()
    cur_level = float(gold.iloc[-1])
    current = {
        "week": str(gold.index[-1].date()), "gold_level": cur_level, "source_of_last_weeks": src[src != "MAUc1"].index.strftime("%Y-%m-%d").tolist(),
        "weekly_close_peak": {"date": str(gold.idxmax().date()), "level": float(gold.max())},
        "daily_close_peak_mauc1": {"date": str(daily_peak.date()), "level": float(mau.max())},
        "fall_from_weekly_peak": float(cur_level / gold.max() - 1), "fall_from_daily_peak": float(cur_level / mau.max() - 1),
        **{c: float(cur[c]) for c in Z.columns},
        "pct_rank_of_z": {k: float((Z[k].dropna() <= cur[k]).mean()) for k in ("z1", "z2", "z4", "z8", "z13", "z26")},
        "weeks_with_dd_ath_at_least_current": int((Z["dd_ath"] <= cur["dd_ath"]).sum()),
        "worst_dd_ath": {"value": float(Z["dd_ath"].min()), "week": str(Z["dd_ath"].idxmin().date())},
        "vol52_ann_pct_rank": float((Z["vol52_ann"].dropna() <= cur["vol52_ann"]).mean()),
        "mauc1_sign_last": {"week": str(sw.index[-1].date()), "sign": sw.iloc[-1]},
        "goldbees": {"peak_date": str(gb.idxmax().date()), "peak": float(gb.max()), "last_date": str(gb.index[-1].date()), "last": float(gb.iloc[-1]),
                     "fall": float(gb.iloc[-1] / gb.max() - 1),
                     "premium_at_peak_vs_mauc1_typical": float((mau / gb).loc["2025-01-01":"2025-12-31"].median() / (mau / gb).loc[gb.idxmax()] - 1)},
        "equity_signs_last": {n: {"week": str(s.index[-1].date()), "sign": s.iloc[-1]} for n, s in sig.items()},
    }

    # 2. events: sweeps of two definitions
    defs = {}
    for thr in (-1.5, -1.75, -2.0, -2.5):
        defs[f"z8<={thr}"] = Z["z8"] <= thr
    for thr in (-0.12, -0.15, -0.20):
        defs[f"dd52w<={int(thr*100)}%"] = Z["dd_52w"] <= thr
    base = baseline(gold)
    ev_rows, sweep = [], []
    for name, cond in defs.items():
        ts = [t for t in triggers(cond.fillna(False)) if t < gold.index[-1]]
        rows = []
        for t in ts:
            i = gold.index.get_loc(t)
            r = {"definition": name, "trigger_week": str(t.date()), "gold": float(gold.iloc[i]),
                 "ret8_into": float(Z["ret8"].iloc[i]), "z8": float(Z["z8"].iloc[i]), "dd_52w": float(Z["dd_52w"].iloc[i]),
                 "vol52_ann": float(Z["vol52_ann"].iloc[i]), "rsi14w": float(Z["rsi14w"].iloc[i]),
                 "mauc1_sign": asof(sw, t)}
            r.update(forward(gold, t))
            later = sw[(sw.index > t)]
            flip = later[later == "BUY"]
            r["weeks_to_mauc1_buy"] = int(round((flip.index[0] - t).days / 7)) if len(flip) else None
            r["gold_until_mauc1_buy"] = float(asof(gold, flip.index[0]) / gold.iloc[i] - 1) if len(flip) else None
            ins = {n: asof(s, t) for n, s in sig.items()}
            r["equity_signs"] = ins
            r["switch"] = ("IN" if all(v == "BUY" for v in ins.values()) else "OUT") if all(v is not None for v in ins.values()) else "n/a (pre-2011)"
            for n, s in eq.items():
                j = s.index.searchsorted(t)
                for h in (13, 26):
                    r[f"{n}_fwd{h}"] = float(s.iloc[j + h] / s.iloc[j] - 1) if j < len(s) and s.index[j] - t <= pd.Timedelta(days=6) and j + h < len(s) else None
            rows.append(r)
        ev_rows += rows
        agg = {"definition": name, "n_events": len(rows)}
        for h in HORIZONS:
            v = [x[f"fwd{h}"] for x in rows if x[f"fwd{h}"] is not None]
            agg[f"fwd{h}_median"] = float(np.median(v)) if v else None
            agg[f"fwd{h}_mean"] = float(np.mean(v)) if v else None
            agg[f"fwd{h}_share_up"] = float(np.mean([x > 0 for x in v])) if v else None
            agg[f"fwd{h}_n"] = len(v)
        v = [x["further_fall_26w"] for x in rows if x["further_fall_26w"] is not None]
        agg["further_fall_26w_median"] = float(np.median(v)) if v else None
        agg["further_fall_26w_worst"] = float(np.min(v)) if v else None
        w = [x["weeks_to_regain_52w_high"] for x in rows]
        agg["regained_52w_high_within_52w"] = sum(1 for x in w if x is not None and x <= 52)
        agg["weeks_to_regain_median"] = float(np.median([x for x in w if x is not None])) if any(x is not None for x in w) else None
        sweep.append(agg)

    # 2b. all weeks, bucketed by the 8-week z (overlapping windows: descriptive only)
    fw = pd.DataFrame({f"fwd{h}": gold.shift(-h) / gold - 1 for h in HORIZONS})
    edges = [-np.inf, -2, -1.5, -1, 0, 1, 2, np.inf]
    labels = ["<= -2", "-2 to -1.5", "-1.5 to -1", "-1 to 0", "0 to 1", "1 to 2", "> 2"]
    bkt = pd.cut(Z["z8"], edges, labels=labels)
    buckets = []
    for lab in labels:
        sel = fw[bkt == lab]
        row = {"z8_bucket": lab, "weeks": int((bkt == lab).sum())}
        for h in HORIZONS:
            v = sel[f"fwd{h}"].dropna()
            row[f"fwd{h}_mean"] = float(v.mean()) if len(v) else None
            row[f"fwd{h}_share_up"] = float((v > 0).mean()) if len(v) else None
            row[f"fwd{h}_n"] = int(len(v))
        buckets.append(row)

    # 2c. every drawdown from an all-time high of 10% or more (weekly closes)
    dd = Z["dd_ath"]
    episodes, i, n = [], 0, len(gold)
    while i < n:
        if dd.iloc[i] < 0:
            j = i
            while j < n and dd.iloc[j] < 0:
                j += 1
            seg = dd.iloc[i:j]
            if seg.min() <= -0.10:
                tr = seg.idxmin()
                peak_i = i - 1
                episodes.append({"peak_week": str(gold.index[peak_i].date()), "peak": float(gold.iloc[peak_i]),
                                 "trough_week": str(tr.date()), "trough": float(gold.loc[tr]), "depth": float(seg.min()),
                                 "weeks_peak_to_trough": int(gold.index.get_loc(tr) - peak_i),
                                 "recovered_week": str(gold.index[j].date()) if j < n else None,
                                 "weeks_trough_to_recovery": int(j - gold.index.get_loc(tr)) if j < n else None,
                                 "first_week_down_15": str(seg[seg <= -0.15].index[0].date()) if (seg <= -0.15).any() else None,
                                 "after_first_15_fall_further": float(seg.min() - seg[seg <= -0.15].iloc[0]) if (seg <= -0.15).any() else None,
                                 "ongoing": j >= n})
            i = j
        else:
            i += 1

    # 2d. what the MAUc1 SELL did in this episode
    flip = sw[(sw == "SELL") & (sw.shift() == "BUY")].index[-1]
    g_flip = float(asof(gold, flip))
    current["mauc1_sell_since"] = {"week": str(flip.date()), "gold_at_flip": g_flip, "gold_change_since": float(gold.iloc[-1] / g_flip - 1),
                                   "st_band_last": float(pd.read_csv(F["mau_w"], parse_dates=["review"]).set_index("review")["ST"].iloc[-1])}

    # 2e. indicative MAUc1 band for the weeks after the export ends: GOLDBEES weekly high/low/close scaled to MAUc1 on
    #     2026-11-06, run through the desk rule (TR, 5-week linearly weighted ATR, bands (H+L)/2 +/- 2 ATR, FUB ratchet).
    wt = pd.read_csv(F["mau_w"], parse_dates=["review"]).set_index("review")
    scale = float(wt["close"].iloc[-1]) / float(gb.loc[:wt.index[-1]].iloc[-1])
    g_d = pd.read_parquet(F["gb"]).assign(date=lambda d: pd.to_datetime(d["date"])).set_index("date")
    g_d = g_d[(g_d.index > wt.index[-1]) & (g_d.index <= LAST)]
    ext_w = g_d.resample("W-FRI").agg({"high": "max", "low": "min", "close": "last"}).dropna() * scale
    tr = list(wt["TR"].astype(float).iloc[-4:])
    fub, close_prev, prev_sign = float(wt["FUB"].iloc[-1]), float(wt["close"].iloc[-1]), wt["SIGN"].iloc[-1]
    band = []
    for d, row in ext_w.iterrows():
        t = max(row.high - row.low, abs(row.high - close_prev), abs(row.low - close_prev))
        tr = (tr + [t])[-5:]
        watr = sum((k + 1) * x for k, x in enumerate(tr)) / 15
        bub = (row.high + row.low) / 2 + 2 * watr
        fub = bub if (bub < fub or close_prev > fub) else fub
        band.append({"week": str(d.date()), "high": float(row.high), "low": float(row.low), "close": float(row.close), "TR": float(t),
                     "wATR": float(watr), "BUB": float(bub), "FUB": float(fub), "rise_needed_to_flip_buy": float(fub / row.close - 1)})
        close_prev = row.close
    if not band:      # MAUc1 itself reaches LAST: report the real band, not an estimate
        last = wt.iloc[-1]
        band = [{"week": str(wt.index[-1].date()), "high": float(last["high"]), "low": float(last["low"]), "close": float(last["close"]),
                 "TR": float(last["TR"]), "wATR": float(last["wATR"]), "BUB": float(last["BUB"]), "FUB": float(last["FUB"]),
                 "ST": float(last["ST"]), "rise_needed_to_flip_buy": float(last["ST"] / last["close"] - 1), "actual": True}]
    current["mauc1_band_indicative"] = band
    sc = pd.read_excel(F["sig_SC100"], parse_dates=["Date"]).set_index("Date")
    current["sc100_band"] = {"week": str(sc.index[-1].date()), "close": float(sc["Index"].iloc[-1]), "ST": float(sc["ST"].iloc[-1]),
                             "rise_needed_to_flip_buy": float(sc["ST"].iloc[-1] / sc["Index"].iloc[-1] - 1)}

    # 3. analog paths (main definition) indexed to trigger = 100, t-26..t+52
    MAIN = "z8<=-1.75"
    paths = {}
    for r in [x for x in ev_rows if x["definition"] == MAIN]:
        t = pd.Timestamp(r["trigger_week"])
        i = gold.index.get_loc(t)
        seg = gold.iloc[max(0, i - 26): i + 53]
        paths[r["trigger_week"]] = {"k": [int(gold.index.get_loc(d) - i) for d in seg.index], "v": [round(float(x / gold.iloc[i] * 100), 2) for x in seg.values]}
    i = len(gold) - 1
    seg = gold.iloc[i - 26:]
    paths["current"] = {"k": [int(gold.index.get_loc(d) - i) for d in seg.index], "v": [round(float(x / gold.iloc[i] * 100), 2) for x in seg.values]}

    # weekly series for charts
    weekly = pd.DataFrame({"gold": gold, "source": src}).join(Z)
    weekly["mauc1_sign"] = [asof(sw, t) for t in weekly.index]
    weekly.to_csv(OUT / "weekly.csv", index_label="week")
    pd.DataFrame(ev_rows).to_csv(OUT / "events.csv", index=False)
    summary = {"as_of": str(LAST.date()), "inputs": {k: str(v.relative_to(AA)) for k, v in F.items()}, "current": current,
               "baseline_all_weeks": base, "sweep": sweep, "z8_buckets": buckets, "drawdown_episodes": episodes, "main_definition": MAIN, "cooldown_weeks": COOLDOWN, "paths": paths}
    (OUT / "summary.json").write_text(json.dumps(summary, indent=1, default=str))
    print(json.dumps(current, indent=1, default=str)[:3000])
    print(pd.DataFrame(sweep).to_string())
    print(json.dumps(base, indent=0))
    print(pd.DataFrame(buckets).to_string())
    print(pd.DataFrame(episodes).to_string())
    print(current["mauc1_sell_since"]); print(json.dumps(current["mauc1_band_indicative"], indent=0)); print(current["sc100_band"])
    print(pd.DataFrame([x for x in ev_rows if x["definition"] == MAIN]).drop(columns=["equity_signs"]).to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main())
