"""Gold proxy for the sessions before GOLDBEES's first approved bar (2014-07-01), built from MAUc1.

    python data/build_gold_proxy.py --check     # prints the diagnostics, writes nothing
    python data/build_gold_proxy.py             # writes analysis/cache/why_gold_ohlc_proxy_mauc1_<first>_<last>.parquet

What it does (Manu, chat 2026-11-12: "extend the GOLDBEES data using the returns of MAUc1 ... create another file for the
gold proxy before 2014-07"):
  * reads two APPROVED files only: D09 (GOLDBEES OHLC, to get its first bar) and D24b's cleaned MAUc1 daily bars
    (MCX gold futures, 2003-11-10 ->);
  * proxy bar[t] = k x MAUc1 bar[t] for every MAUc1 bar before GOLDBEES's first date, open, high, low and close alike,
    with k = GOLDBEES close / MAUc1 close on GOLDBEES's first date, so the proxy's last close chains into GOLDBEES's first
    close with exactly MAUc1's return on that day. The proxy's day-to-day returns ARE MAUc1's returns; nothing is
    fitted, smoothed or drift-adjusted;
  * the proxy starts after the last invalid MAUc1 bar (a non-positive price or a one-day close move over 30%): 2004-04-24
    and 2005-05-07 are such bars (a lone 9,207 print and a zero close), so the proxy starts 2005-05-10;
  * the output has the columns of the D09 file (date, open, high, low, close), is a NEW file, and D09 is never edited;
  * --check compares MAUc1 with the real GOLDBEES over the overlap (2014-07-01 ->) so the proxy's quality is on record.
Known limits are printed and written to the sidecar .md: the MCX session ends after the NSE close, MAUc1 is a futures
series (roll gaps, basis) and GOLDBEES nets a fund expense, so the proxy is a gold price series, not GOLDBEES.
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

import numpy as np
import pandas as pd

AA = Path(__file__).resolve().parents[1]
GOLD = AA / "analysis" / "cache" / "why_gold_ohlc_eikon_extended_2026-11-04.parquet"          # D09
MAU = AA / "Historical Data" / "extended_2026-11-12" / "MAUc1_from_2003" / "mauc1_daily_clean_extended.csv"  # D24b
OUT_DIR = AA / "analysis" / "cache"


def sha(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def load():
    g = pd.read_parquet(GOLD)
    g["date"] = pd.to_datetime(g["date"])
    g = g.set_index("date").sort_index()
    m = pd.read_csv(MAU, parse_dates=["date"]).set_index("date").sort_index()
    return g, m


def diagnostics(g: pd.DataFrame, m: pd.DataFrame) -> dict:
    """MAUc1 against the real GOLDBEES on the dates both exist (2014-07-01 ->)."""
    d0 = g.index[0]
    mm = m.loc[d0:, "close"]
    both = g.index.intersection(mm.index)
    gc, mc = g.loc[both, "close"], mm.loc[both]
    gr, mr = gc.pct_change().dropna(), mc.pct_change().dropna()
    out = {"overlap_first": str(both[0].date()), "overlap_last": str(both[-1].date()), "overlap_days": len(both),
           "g_dates_without_mauc1_bar": int(len(g.index.difference(m.index)))}
    # same-day and lagged correlation: MCX closes after NSE, so MAUc1's day t also holds the evening after GOLDBEES's close
    for lag in (-1, 0, 1):
        out[f"corr_daily_lag{lag}"] = float(gr.corr(mr.shift(lag)))
    out["beta_daily_g_on_m"] = float(np.polyfit(mr.loc[gr.index.intersection(mr.index)], gr.loc[gr.index.intersection(mr.index)], 1)[0])
    wk = lambda s: s.resample("W-FRI").last().dropna().pct_change().dropna()
    gw_, mw_ = wk(gc), wk(mc)
    dd = pd.concat([gr, mr, mr.shift(1)], axis=1, keys=["g", "m", "m1"]).dropna()
    X = np.c_[np.ones(len(dd)), dd["m"], dd["m1"]]
    bb = np.linalg.lstsq(X, dd["g"], rcond=None)[0]
    out["daily_g_on_m_and_m_lag1_coefs"] = [round(float(v), 3) for v in bb[1:]]
    out["daily_g_on_m_and_m_lag1_R2"] = round(float(1 - ((dd["g"] - X @ bb) ** 2).sum() / ((dd["g"] - dd["g"].mean()) ** 2).sum()), 3)
    out["corr_weekly"] = float(gw_.corr(mw_))
    yrs = (both[-1] - both[0]).days / 365.25
    out["years"] = round(yrs, 2)
    out["cagr_goldbees"] = float((gc.iloc[-1] / gc.iloc[0]) ** (1 / yrs) - 1)
    out["cagr_mauc1"] = float((mc.iloc[-1] / mc.iloc[0]) ** (1 / yrs) - 1)
    out["cagr_gap_pp_per_year_(G minus M)"] = round(100 * (out["cagr_goldbees"] - out["cagr_mauc1"]), 3)
    ann = lambda s: float(s.std() * np.sqrt(252))
    out["vol_goldbees"], out["vol_mauc1"] = ann(gr), ann(mr)
    diff = (gr - mr.reindex(gr.index)).dropna()
    out["daily_return_gap_sd"] = float(diff.std())
    out["days_gap_over_1pct"] = int((diff.abs() > 0.01).sum())
    out["days_gap_over_2pct"] = int((diff.abs() > 0.02).sum())
    out["worst_gaps"] = [(str(i.date()), round(float(v), 4)) for i, v in diff.reindex(diff.abs().sort_values(ascending=False).index)[:5].items()]
    # by year, so a drift that changes over time shows
    by = pd.DataFrame({"g": gc, "m": mc}).groupby(lambda x: x.year).agg(["first", "last"])
    out["yearly_return_pct"] = {int(y): (round(100 * (r[("g", "last")] / r[("g", "first")] - 1), 1), round(100 * (r[("m", "last")] / r[("m", "first")] - 1), 1))
                                for y, r in by.iterrows()}
    return out


def invalid_bars(m: pd.DataFrame) -> pd.DatetimeIndex:
    """Bars that cannot be prices: a non-positive open/high/low/close, or a one-day close move over 30% (either side of it)."""
    px = m[["open", "high", "low", "close"]]
    r = m["close"].pct_change()
    bad = (px <= 0).any(axis=1) | (r.abs() > 0.30) | r.isna() & False
    bad |= bad.shift(-1, fill_value=False)           # the bar before a broken bar is not trusted either
    bad |= (r.replace([np.inf, -np.inf], np.nan).isna() & m["close"].shift(1).le(0))   # the return off a zero close
    return m.index[bad]


def build(g: pd.DataFrame, m: pd.DataFrame):
    d0 = g.index[0]
    if d0 not in m.index:
        raise SystemExit(f"STOP: MAUc1 has no bar on GOLDBEES's first date {d0.date()}")
    k = float(g.loc[d0, "close"] / m.loc[d0, "close"])
    bad = invalid_bars(m.loc[: d0 - pd.Timedelta(days=1)])
    first = m.index[m.index > bad.max()][0] if len(bad) else m.index[0]
    pre = m.loc[first: d0 - pd.Timedelta(days=1), ["open", "high", "low", "close"]] * k
    pre = pre.reset_index().rename(columns={"index": "date"})
    pre["date"] = pd.to_datetime(pre["date"])
    # continuity: the proxy's last close chained into GOLDBEES's first close has MAUc1's return on that day
    ret_splice = float(g.loc[d0, "close"] / pre["close"].iloc[-1] - 1)
    ret_mau = float(m.loc[d0, "close"] / m.loc[:d0 - pd.Timedelta(days=1), "close"].iloc[-1] - 1)
    return pre, k, d0, ret_splice, ret_mau


def main(check_only: bool) -> int:
    g, m = load()
    print(f"GOLDBEES (D09) {g.index.min().date()} -> {g.index.max().date()}, {len(g)} rows, sha256 {sha(GOLD)[:16]}")
    print(f"MAUc1 daily (D24b) {m.index.min().date()} -> {m.index.max().date()}, {len(m)} rows, sha256 {sha(MAU)[:16]}")
    dg = diagnostics(g, m)
    print("\nMAUc1 against the real GOLDBEES on the overlap:")
    for k_, v in dg.items():
        print(f"  {k_}: {v}")
    pre, k, d0, rs, rm = build(g, m)
    big = pre.assign(ret=pre["close"].pct_change()).dropna()
    big = big[big["ret"].abs() > 0.04]
    print(f"\nproxy: {len(pre)} bars {pre['date'].min().date()} -> {pre['date'].max().date()}; k = {k:.8f} (GOLDBEES {d0.date()} close / MAUc1 close); "
          f"splice-day return {rs:.6f} vs MAUc1's own {rm:.6f} (must be equal: {abs(rs - rm) < 1e-12})")
    print(f"invalid MAUc1 bars before {d0.date()} (flagged, not used): {[str(x.date()) for x in invalid_bars(m.loc[: d0 - pd.Timedelta(days=1)])]}")
    print(f"proxy bars per year: {pre.groupby(pre['date'].dt.year).size().to_dict()}")
    print(f"proxy daily close moves over 4%: {len(big)}  {[(str(r.date.date()), round(float(r.ret), 4)) for r in big.itertuples()]}")
    print(f"proxy close first {pre['close'].iloc[0]:.4f}, last {pre['close'].iloc[-1]:.4f}; GOLDBEES first close {g['close'].iloc[0]:.4f}")
    if check_only:
        print("--check: nothing written.")
        return 0
    name = f"why_gold_ohlc_proxy_mauc1_{pre['date'].min().date()}_{pre['date'].max().date()}"
    out = OUT_DIR / f"{name}.parquet"
    if out.exists():
        raise SystemExit(f"{out} exists; originals are never overwritten")
    pre[["date", "open", "high", "low", "close"]].to_parquet(out, index=False)
    side = OUT_DIR / f"{name}.md"
    side.write_text(
        f"# {name}\n\nGold proxy for the sessions before GOLDBEES's first approved bar ({d0.date()}), built by `data/build_gold_proxy.py`.\n\n"
        f"- bars: {len(pre)}, {pre['date'].min().date()} -> {pre['date'].max().date()}; columns date, open, high, low, close (the layout of D09)\n"
        f"- proxy bar = k x MAUc1 bar, k = {k:.10f} = GOLDBEES close / MAUc1 close on {d0.date()}; the proxy's returns are MAUc1's returns, "
        f"nothing fitted or drift-adjusted; the splice day's return equals MAUc1's ({rm:.6f})\n"
        f"- MAUc1 input: `{MAU.relative_to(AA)}` (D24b, sha256 {sha(MAU)[:16]}); GOLDBEES: `{GOLD.relative_to(AA)}` (D09, sha256 {sha(GOLD)[:16]})\n"
        f"- tracking against the real GOLDBEES on {dg['overlap_first']} -> {dg['overlap_last']}: daily correlation {dg['corr_daily_lag0']:.3f} "
        f"(lag -1 {dg['corr_daily_lag-1']:.3f}, lag +1 {dg['corr_daily_lag1']:.3f}), weekly correlation {dg['corr_weekly']:.3f}, "
        f"CAGR GOLDBEES {100*dg['cagr_goldbees']:.2f}% vs MAUc1 {100*dg['cagr_mauc1']:.2f}% (gap {dg['cagr_gap_pp_per_year_(G minus M)']} pp/yr)\n"
        f"- daily relation on the overlap: GOLDBEES return ~ {dg['daily_g_on_m_and_m_lag1_coefs'][0]} x MAUc1 return on the day + {dg['daily_g_on_m_and_m_lag1_coefs'][1]} x MAUc1 return the day before (R2 {dg['daily_g_on_m_and_m_lag1_R2']}): the MCX evening session after the NSE close puts part of a GOLDBEES day's move into MAUc1's next bar\n"
        f"- the proxy starts {pre['date'].min().date()}, after the last invalid MAUc1 bar (2004-04-24: a lone 9,207 print on a Saturday; 2005-05-07: a zero close); other odd bars are kept as they are, for example 2014-02-05 (+5.7%, volume 267, reversed the next day, a contract-roll artifact that D24's weekly signal also reads)\n"
        f"- limits: the MCX session ends after the NSE close, so a daily proxy return mixes two NSE days; MAUc1 is a futures series (roll gaps, basis); "
        f"GOLDBEES nets a fund expense; the proxy is a gold price series, not GOLDBEES\n")
    print("wrote", out, "and", side)
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    sys.exit(main(a.check))
