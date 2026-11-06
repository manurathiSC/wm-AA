# -*- coding: utf-8 -*-
"""
Rebuild each parent smallcase's index from `data/holdings_matrix/` (holdings + OHLC),
and compare it with the published parent NAV.

Standalone. Inputs
    data/holdings_matrix/SCMO_<p>_holdings_matrix.csv   rows = rebalance_date (= availableDate), cols = ticker, value 0/1
    data/holdings_matrix/SCMO_<p>_columns.csv           ticker -> ISIN, name
    data/holdings_matrix/SCMO_<p>_ohlc.csv              date, stock, open, high, low, close, src  (2014-07-01 -> 2026-11-04)
    Historical Data/parent_nav_2026-10-22/SCMO_<p>.csv  published NAV, 2019-01-02 -> 2026-10-22
    Historical Data/frozen_2026-09-25/Rebalance_history/...   ONLY for the "listed weights" variant and the holdings cross-check
    Historical Data/frozen_2026-09-25/Data/calendar.csv       sessions

The matrix is 0/1, so it carries holdings, not weights. Main variant: equal weight across the held stocks.
Diagnostic variant: the rebalance history's listed weights on the same holdings.

Conventions (same as data/parent_rebuild.py, best one only unless --all):
    switch day R = rebalance_date; switch price = (O+H+L+C)/4 of R; old basket valued at that price;
    shares_i = V * w_i / P_i; other days level = sum shares_i * close_i; last close carried; no costs; price return.

Run: python data/parent_rebuild_hm.py   (from AA/)      Writes data/parent_rebuild_hm/
"""
from __future__ import annotations

import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
AA = Path(__file__).resolve().parents[1]
HM = AA / "data" / "holdings_matrix"
HD = AA / "Historical Data"
REBAL = HD / "frozen_2026-09-25" / "Rebalance_history"
CAL_CSV = HD / "frozen_2026-09-25" / "Data" / "calendar.csv"
PUBDIR = HD / "parent_nav_2026-10-22"
OUT = AA / "data" / "parent_rebuild_hm"
PARENTS = ["SCMO_0003", "SCMO_0007", "SCMO_0010", "SCMO_0029"]
CONVS = ["prev_close", "avail_open", "avail_ohlc4", "avail_close", "next_open", "next_ohlc4", "next_close"]
BEST = "avail_ohlc4"
WINDOWS = {"W_old 2021-11-01 -> 2026-08-21 (same as parent_rebuild.py)": ("2021-11-01", "2026-08-21"),
           "W_full 2019-01-02 -> 2026-10-22 (all published)": ("2019-01-02", "2026-10-22")}


def load_pub(p):
    d = pd.read_csv(PUBDIR / f"{p}.csv")
    s = pd.Series(d["index"].values, index=pd.to_datetime(d["_id.date"], format="%Y/%m/%d")).sort_index()
    return s


def load_hm(p):
    m = pd.read_csv(HM / f"{p}_holdings_matrix.csv", index_col=0)
    m.index = pd.to_datetime(m.index)
    cols = pd.read_csv(HM / f"{p}_columns.csv").set_index("stock")
    o = pd.read_csv(HM / f"{p}_ohlc.csv", parse_dates=["date"]).drop_duplicates(["date", "stock"])
    px = {f: o.pivot(index="date", columns="stock", values=f).sort_index() for f in ("open", "high", "low", "close")}
    return m, cols, px


def apply_corrections(px, p):
    """Return a copy of px with data/holdings_matrix/price_corrections.csv applied: prices dated BEFORE ex_date
    are multiplied by factor (undoes an Eikon back-adjustment the published price-return index does not make)."""
    out = {f: v.copy() for f, v in px.items()}
    c = pd.read_csv(HM / "price_corrections.csv", parse_dates=["ex_date"])
    for r in c.itertuples():
        if p in r.applies_to.split(";") and r.stock in out["close"].columns:
            for f in out:
                out[f].loc[out[f].index < r.ex_date, r.stock] *= r.factor
    return out


def g0_gate(model, pub, tol_total=0.25, tol_year=0.5):
    """G0: CAGR gap over 2019-01-02 -> 2026-10-22 within +-tol_total pp/yr, every calendar-year return gap within +-tol_year pp."""
    c = pd.DataFrame({"m": model, "p": pub}).dropna(); c = c / c.iloc[0] * 100
    st = stats(model, pub, "2019-01-02", "2026-10-22")
    yrs = {}
    for yr, g in c.groupby(c.index.year):
        prev = c.loc[:g.index[0]].iloc[-2] if len(c.loc[:g.index[0]]) > 1 else g.iloc[0]
        yrs[yr] = (g["m"].iloc[-1] / prev["m"] - g["p"].iloc[-1] / prev["p"]) * 100
    worst = max(yrs, key=lambda y: abs(yrs[y]))
    return {"cagr_gap_pp_yr": st["gap_pp_yr"], "overall": "PASS" if abs(st["gap_pp_yr"]) <= tol_total else "FAIL",
            "worst_year": worst, "worst_year_gap_pp": yrs[worst], "yearly": "PASS" if abs(yrs[worst]) <= tol_year else "FAIL"}


def history_weights(p, cols):
    """listed weights from the rebalance history, keyed (eff, ticker); and a holdings cross-check vs the matrix."""
    h = pd.read_csv(REBAL / f"Rebalance_history_by_scid_{p}.csv")
    h["eff"] = pd.to_datetime(h["availableDate"], format="%d/%m/%y %H:%M")
    h["skipped"] = h["skipped"].astype(str).str.lower().eq("true")
    h = h[~h["skipped"]]
    isin2t = {v: k for k, v in cols["ISIN"].items()}
    h["t"] = h["ISIN"].astype(str).str.strip().str.upper().map(isin2t)
    return h


def build(m, px, cal, conv, weights):
    """weights: DataFrame like m (rows=eff, cols=ticker) of target weights (rows sum to 1)."""
    keys = list(m.columns)
    raw_close = px["close"].reindex(index=cal, columns=keys)
    close = raw_close.ffill()
    opn = px["open"].reindex(index=cal, columns=keys).fillna(raw_close)
    ohlc4 = ((px["open"] + px["high"] + px["low"] + px["close"]).reindex(index=cal, columns=keys) / 4).fillna(raw_close)
    field = {"close": close, "open": opn, "ohlc4": ohlc4}
    effs = list(m.index)
    pos = {e: cal.searchsorted(e) for e in effs}

    def sw(e):
        i = pos[e]
        if conv == "prev_close": return i - 1, "close"
        if conv == "avail_close": return i, "close"
        if conv == "next_close": return i + 1, "close"
        return (i, conv.split("_")[1]) if conv.startswith("avail_") else (i + 1, conv.split("_")[1])

    swm = {sw(e)[0]: (e, sw(e)[1]) for e in effs}
    nav = pd.Series(np.nan, index=cal)
    shares, V, rows, nomiss = None, 100.0, [], 0
    for i in range(min(swm), len(cal)):
        d = cal[i]
        if shares is not None:
            V = float((shares * close.loc[d, shares.index]).sum())
        if i in swm:
            e, f = swm[i]
            w = weights.loc[e]; w = w[w > 0]
            p_sw = field[f].loc[d, w.index]
            if shares is not None and f != "close":
                p_old = field[f].loc[d, shares.index].fillna(close.loc[d, shares.index])
                V_sw = float((shares * p_old).sum())
            else:
                V_sw = V
            bad = p_sw.isna() | (p_sw <= 0)
            if bad.any():
                rows.append({"eff": e.date(), "tickers_no_price": ",".join(p_sw.index[bad])})
            ok = ~bad
            w = w[ok] / w[ok].sum()
            shares = V_sw * w / p_sw[ok]
            V = float((shares * close.loc[d, shares.index]).sum())
        nav.iloc[i] = V
    return nav, rows


def stats(model, pub, a, b):
    d = pd.DataFrame({"m": model, "p": pub}).dropna().loc[a:b]
    d = d / d.iloc[0] * 100
    r = d.pct_change().dropna(); diff = r["m"] - r["p"]
    yrs = (d.index[-1] - d.index[0]).days / 365.25
    cg = (d.iloc[-1] / d.iloc[0]) ** (1 / yrs) - 1
    return {"days": len(d), "cagr_pub_%": cg["p"] * 100, "cagr_model_%": cg["m"] * 100,
            "gap_pp_yr": (cg["m"] - cg["p"]) * 100, "end_ratio": d["m"].iloc[-1] / d["p"].iloc[-1],
            "te_%_yr": diff.std() * np.sqrt(252) * 100, "corr_daily": r["m"].corr(r["p"]),
            "days_lt_1bp": int((diff.abs() < 1e-4).sum()), "days_gt_25bp": int((diff.abs() > 25e-4).sum()),
            "max_abs_diff_bp": diff.abs().max() * 1e4}


def main():
    OUT.mkdir(exist_ok=True)
    cal0 = pd.to_datetime(pd.read_csv(CAL_CSV)["date"])
    S, D, Y, X, W, H, G = [], [], [], [], [], [], []
    for p in PARENTS:
        m, cols, px = load_hm(p)
        pub = load_pub(p)
        busy = px["close"].notna().sum(axis=1)
        extra = busy[busy >= 0.5 * busy.median()].index
        cal = pd.DatetimeIndex(sorted(set(cal0) | set(pub.index) | set(extra)))
        cal = cal[(cal >= pd.Timestamp("2014-07-01")) & (cal <= pub.index.max())]
        # first basket we can price on its own switch day: needs ohlc, which starts 2014-07-01
        mm = m[m.index >= pd.Timestamp("2014-07-01")]
        eq = mm.div(mm.sum(axis=1), axis=0)
        # listed-weights variant + holdings cross-check
        h = history_weights(p, cols)
        lw = pd.DataFrame(0.0, index=mm.index, columns=mm.columns)
        for e, g in h.groupby("eff"):
            if e in lw.index:
                gg = g.dropna(subset=["t"])
                lw.loc[e, gg["t"].values] = pd.to_numeric(gg["weight"]).values
        same = []
        for e in mm.index:
            a = set(mm.columns[mm.loc[e] > 0]); b = set(lw.columns[lw.loc[e] > 0])
            same.append({"parent": p, "eff": e.date(), "matrix_n": len(a), "history_n": len(b),
                         "only_matrix": ",".join(sorted(a - b)), "only_history": ",".join(sorted(b - a))})
        H += same
        lw = lw.div(lw.sum(axis=1).replace(0, np.nan), axis=0).fillna(0)
        hist_effs = set(h["eff"])                       # non-skipped baskets only
        keep = [e for e in mm.index if e in hist_effs]  # drops baskets the history flags skipped=true
        pxc = apply_corrections(px, p)                  # F-AA-D14 price corrections (no-op for parents without one)
        for variant, rows_, wts in (("equal_weight_as_given", list(mm.index), eq),
                                    ("equal_weight_skip_dropped", keep, eq.loc[keep]),
                                    ("listed_weights_skip_dropped", keep, lw.loc[keep]),
                                    ("listed_weights_skip_dropped_corrected", keep, lw.loc[keep])):
            for conv in (CONVS if variant == "equal_weight_skip_dropped" else [BEST]):
                nav, miss = build(mm.loc[rows_], pxc if variant.endswith("_corrected") else px, cal, conv, wts)
                if variant.startswith("listed") and conv == BEST:
                    G.append({"parent": p, "variant": variant, **g0_gate(nav, pub)})
                for r in miss: X.append({"parent": p, "variant": variant, "conv": conv, **r})
                for wname, (a, b) in WINDOWS.items():
                    st = stats(nav, pub, a, b)
                    S.append({"parent": p, "variant": variant, "conv": conv, "window": wname, **st})
                if conv == BEST:
                    # daily levels, each rebased to the published level on 2019-01-02 (or first common day)
                    c = pd.DataFrame({"model": nav, "pub": pub}).dropna()
                    c = c / c.iloc[0] * 100
                    c["parent"], c["variant"] = p, variant
                    D.append(c.reset_index().rename(columns={"index": "date"}))
                    # calendar-year return gap
                    for yr, g in c.groupby(c.index.year):
                        prev = c.loc[:g.index[0]].iloc[-2] if len(c.loc[:g.index[0]]) > 1 else g.iloc[0]
                        rm, rp = g["model"].iloc[-1] / prev["model"] - 1, g["pub"].iloc[-1] / prev["pub"] - 1
                        Y.append({"parent": p, "variant": variant, "year": yr, "model_%": rm * 100,
                                  "pub_%": rp * 100, "gap_pp": (rm - rp) * 100})
            # coverage
        av = pd.read_csv(HM / f"{p}_ohlc_availability.csv")
        W.append({"parent": p, **{k: int(av[k].sum()) for k in ("needed_sessions", "complete_bars", "partial_bars", "carried", "missing")}})
    S = pd.DataFrame(S); S.to_csv(OUT / "summary.csv", index=False)
    pd.concat(D).to_csv(OUT / "daily.csv", index=False)
    pd.DataFrame(Y).to_csv(OUT / "yearly.csv", index=False)
    pd.DataFrame(X).to_csv(OUT / "switch_prices_missing.csv", index=False)
    pd.DataFrame(H).to_csv(OUT / "holdings_vs_history.csv", index=False)
    pd.DataFrame(W).to_csv(OUT / "ohlc_coverage.csv", index=False)
    G = pd.DataFrame(G); G.to_csv(OUT / "g0_gate.csv", index=False)
    print(G.round(3).to_string(index=False))
    print("done ->", OUT)


if __name__ == "__main__":
    main()
