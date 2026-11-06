# -*- coding: utf-8 -*-
"""
Are GOLDBEES daily open/high/low clean enough for (a) a weekly supertrend and
(b) Monday OHLC4 fills? Or do opening-hour spikes distort them?

Compares every GOLDBEES daily bar (Eikon GBES.NS; Kite GOLDBEES as a second
source) with MCX gold futures MAUc1 on the same day: the same metal, but a
far deeper market trading ~14 hours. A GOLDBEES wick or range much larger
than MCX gold's on the same day is a spike in the ETF, not a move in gold.

Then measures the effect:
  - on weekly candles (true range) and on the weekly supertrend, with
    de-spiked variants (close-only candles; wicks clipped to MCX gold's range);
  - on Monday fills: OHLC4 against the close and against (O+C)/2.

Writes evidence/final_strategy/goldbees_spikes/.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from common import CACHE_DIR, EVIDENCE_DIR
from final_strategy import friday_weekly
from supertrend import supertrend

E = EVIDENCE_DIR / "final_strategy"
OUT = E / "goldbees_spikes"
OUT.mkdir(parents=True, exist_ok=True)


def bars():
    g = pd.read_parquet(CACHE_DIR / "why_gold_ohlc_eikon.parquet").set_index("date").sort_index()
    g = g[~g.index.duplicated(keep="last")][["open", "high", "low", "close"]].astype(float)
    k = pd.read_parquet(CACHE_DIR / "goldbees_kite_ohlcv.parquet")
    k["date"] = pd.to_datetime(k["date"])
    k = k.set_index("date").sort_index()[["open", "high", "low", "close"]].astype(float)
    # put Kite on Eikon's (split-adjusted) scale, date by date via the close ratio
    ratio = (g["close"] / k["close"]).reindex(k.index)
    k = k.mul(ratio.rolling(5, min_periods=1, center=True).median(), axis=0)
    m = pd.read_csv(E / "mauc1" / "mauc1_daily_clean.csv", index_col=0, parse_dates=True)[["open", "high", "low", "close"]]
    return g, k, m


def feats(b: pd.DataFrame) -> pd.DataFrame:
    f = pd.DataFrame(index=b.index)
    c = b["close"]
    f["range"] = (b["high"] - b["low"]) / c
    f["upper_wick"] = (b["high"] - b[["open", "close"]].max(axis=1)) / c
    f["lower_wick"] = (b[["open", "close"]].min(axis=1) - b["low"]) / c
    f["wick"] = f[["upper_wick", "lower_wick"]].max(axis=1)
    f["open_gap"] = b["open"] / c.shift() - 1
    f["ret"] = c.pct_change()
    f["open_is_extreme"] = (np.isclose(b["open"], b["high"]) | np.isclose(b["open"], b["low"]))
    return f


def main():
    g, k, m = bars()
    fg, fk, fm = feats(g), feats(k), feats(m)
    common = fg.index.intersection(fm.index)
    A = pd.concat({"gb": fg.loc[common], "mcx": fm.loc[common]}, axis=1).dropna()
    # 1. distributions
    rows = []
    for nm, f in (("GOLDBEES (Eikon)", fg.loc[common]), ("GOLDBEES (Kite)", fk.reindex(common)), ("MAUc1 (MCX gold)", fm.loc[common])):
        f = f.dropna()
        for col in ("range", "wick", "open_gap", "ret"):
            x = f[col].abs()
            rows.append({"series": nm, "measure": col, "days": len(x), "median": x.median(), "p90": x.quantile(0.9),
                         "p99": x.quantile(0.99), "max": x.max(), "days_over_2pct": int((x > 0.02).sum()), "days_over_5pct": int((x > 0.05).sum())})
    Dist = pd.DataFrame(rows)
    Dist.to_csv(OUT / "distributions.csv", index=False)

    # 2. spike days: GOLDBEES wick far beyond anything MCX gold did that day
    s = pd.DataFrame({"gb_open": g.open, "gb_high": g.high, "gb_low": g.low, "gb_close": g.close,
                      "gb_range": fg.range, "gb_wick": fg.wick, "gb_upper": fg.upper_wick, "gb_lower": fg.lower_wick,
                      "gb_open_gap": fg.open_gap, "gb_open_is_extreme": fg.open_is_extreme,
                      "mcx_range": fm.range, "mcx_wick": fm.wick, "mcx_ret": fm.ret, "gb_ret": fg.ret,
                      "kite_high": k.high, "kite_low": k.low, "kite_wick": fk.wick}).loc[common]
    s["excess_wick"] = s.gb_wick - s.mcx_range          # how far the ETF's wick went beyond MCX gold's whole day
    spike = s[(s.gb_wick > 0.015) & (s.excess_wick > 0.01)].copy()
    spike["kite_confirms"] = (s.kite_wick.reindex(spike.index) > 0.015)
    spike = spike.sort_values("excess_wick", ascending=False)
    spike.to_csv(OUT / "spike_days.csv")
    by_year = spike.groupby(spike.index.year).size().rename("spike_days").to_frame()
    by_year["days"] = s.groupby(s.index.year).size()
    by_year.to_csv(OUT / "spike_days_by_year.csv")

    # 3. weekly candles: true range as % of close, GOLDBEES vs MAUc1
    wg, wm = friday_weekly(g.assign(volume=0.0)), friday_weekly(m.assign(volume=0.0))
    tr = pd.DataFrame({"gb_tr_pct": wg.TR / wg.close, "mcx_tr_pct": wm.TR / wm.close}).dropna()
    tr.to_csv(OUT / "weekly_true_range.csv")

    # 4. supertrend variants on GOLDBEES, against MAUc1's
    def sig_of(b):
        return supertrend(friday_weekly(b.assign(volume=0.0)))["signal"].dropna()
    close_only = g.assign(high=g[["open", "close"]].max(axis=1) * 0 + g["close"], low=g["close"])
    # clip each daily wick to MCX gold's range that day (scaled to GOLDBEES price)
    mr = fm.range.reindex(g.index)
    body_hi, body_lo = g[["open", "close"]].max(axis=1), g[["open", "close"]].min(axis=1)
    clip = g.copy()
    ok = mr.notna()
    clip.loc[ok, "high"] = np.minimum(g.high[ok], body_hi[ok] * (1 + mr[ok]))
    clip.loc[ok, "low"] = np.maximum(g.low[ok], body_lo[ok] * (1 - mr[ok]))
    variants = {"GOLDBEES OHLC (current)": g, "GOLDBEES close-only candles": close_only,
                "GOLDBEES wicks clipped to MCX range": clip, "GOLDBEES (Kite) OHLC": k.dropna()}
    sm = sig_of(m)
    rv = pd.concat([pd.read_csv(E / f, parse_dates=["review"]) for f in ("weekly_signals_2014_2021.csv", "weekly_signals_live.csv")]).drop_duplicates("review")
    rv = rv[rv.review >= pd.Timestamp("2015-03-06")].review
    at = lambda sg: sg.reindex(rv.values.astype("datetime64[ns]").tolist() and pd.DatetimeIndex(rv).union(sg.index)).ffill().reindex(pd.DatetimeIndex(rv))
    ref = at(sm)
    vr = []
    for nm, b in variants.items():
        sgn = at(sig_of(b))
        both = pd.concat([sgn, ref], axis=1).dropna()
        vr.append({"signal built on": nm, "reviews": len(both), "agree_with_MAUc1": float((both.iloc[:, 0] == both.iloc[:, 1]).mean()),
                   "flips": int((sgn.diff().abs() > 0).sum()), "share_BUY": float(sgn.mean())})
    vr.append({"signal built on": "MAUc1 (MCX gold)", "reviews": int(ref.notna().sum()), "agree_with_MAUc1": 1.0,
               "flips": int((ref.diff().abs() > 0).sum()), "share_BUY": float(ref.mean())})
    V = pd.DataFrame(vr)
    V.to_csv(OUT / "signal_variants.csv", index=False)

    # 5. Monday fills: OHLC4 vs close vs (O+C)/2, on the final rule's GOLDBEES trade days
    tl = pd.read_csv(E / "trade_log.csv", parse_dates=["entry"])
    days = pd.DatetimeIndex(sorted(tl[tl.gold_share_of_sleeve.notna() & (tl.sleeve_weight > 0) | tl.kind.isin(["sleeve -> equity"])].entry.unique()))
    days = days[days.isin(g.index)]
    o4 = (g.open + g.high + g.low + g.close) / 4
    fl = pd.DataFrame({"ohlc4": o4, "close": g.close, "oc2": (g.open + g.close) / 2, "hlc3": (g.high + g.low + g.close) / 3}).loc[days]
    fl["ohlc4_vs_close_bps"] = (fl.ohlc4 / fl.close - 1) * 1e4
    fl["ohlc4_vs_oc2_bps"] = (fl.ohlc4 / fl.oc2 - 1) * 1e4
    fl["spike_day"] = fl.index.isin(spike.index)
    fl.to_csv(OUT / "gold_fill_days.csv")
    all_days = pd.DataFrame({"ohlc4_vs_close_bps": (o4 / g.close - 1) * 1e4, "ohlc4_vs_oc2_bps": (o4 / ((g.open + g.close) / 2) - 1) * 1e4})

    pd.set_option("display.width", 250); pd.set_option("display.max_columns", 30)
    print(Dist.round(4).to_string(index=False))
    print(f"\nspike days (GOLDBEES wick > 1.5% and > MCX gold's whole-day range + 1%): {len(spike)} of {len(s)}; Kite shows the same wick on {int(spike.kite_confirms.sum())}; open is the day's extreme on {int(spike.gb_open_is_extreme.sum())}")
    print(by_year.T.to_string())
    print(spike.head(15)[["gb_open", "gb_high", "gb_low", "gb_close", "gb_wick", "mcx_range", "gb_ret", "mcx_ret", "kite_confirms", "gb_open_is_extreme"]].round(4).to_string())
    print("\nweekly true range % of close: median GOLDBEES", round(tr.gb_tr_pct.median() * 100, 2), "MAUc1", round(tr.mcx_tr_pct.median() * 100, 2),
          "| weeks GOLDBEES TR > 1.5x MAUc1:", int((tr.gb_tr_pct > 1.5 * tr.mcx_tr_pct).sum()), "of", len(tr))
    print(V.round(3).to_string(index=False))
    print("\ntrade days", len(fl), "| OHLC4 vs close bps: mean", round(fl.ohlc4_vs_close_bps.mean(), 1), "mean abs", round(fl.ohlc4_vs_close_bps.abs().mean(), 1),
          "max abs", round(fl.ohlc4_vs_close_bps.abs().max(), 1), "| spike trade days", int(fl.spike_day.sum()))
    print("all days | OHLC4 vs close mean abs bps", round(all_days.ohlc4_vs_close_bps.abs().mean(), 1), "p99", round(all_days.ohlc4_vs_close_bps.abs().quantile(.99), 1))


if __name__ == "__main__":
    main()
