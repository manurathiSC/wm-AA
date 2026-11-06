"""AA data review (AGENT.md task 0).

Reads the raw inputs only and imports nothing from AA/analysis. Every check and chart in
data/DATA_REVIEW.md and data_review.html comes from here. Human judgement (sources, verdicts,
explanations) lives in data/review_decisions.json and is merged in, never computed.

    python data/data_review.py --date 2026-10-22

Writes data/review/<date>/: inventory.csv, calendar.csv, calendar_diffs.csv, values.csv,
value_issues.csv, largest_moves.csv, signals.csv, baskets.csv, coverage.csv, coverage_missing.csv,
stock_moves.csv, reconciliation.csv, stock_source_diffs.csv, derived.csv, holdings_ohlc.csv (D18),
d17_d18_sessions.csv, holdings_weights.csv (D19), summary.json, charts/.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
AA = HERE.parent
HD = AA / "Historical Data"
FZ = HD / "frozen_2026-09-25"
CACHE = AA / "analysis" / "cache"
EV = AA / "analysis" / "evidence"
DOWNLOADS = Path(r"C:\Users\manur\Downloads")
sys.path.insert(0, str(HERE))
import review_lib as L  # noqa: E402

BOOKS = {"SCMO_0042": "SCMO_0003", "SCMO_0043": "SCMO_0007", "SCMO_0044": "SCMO_0010", "SCMO_0045": "SCMO_0029"}
PARENTS = list(BOOKS.values())
# the two backtest windows used by the final-strategy engine
WINDOWS = {"2014-21": ("2014-07-04", "2021-10-29"), "2021-26": ("2021-11-01", "2026-08-21")}
THRESH = {"stock": 0.20, "index": 0.05, "etf": 0.05, "future": 0.05, "cash": 0.005, "nav": 0.08}


def ddmmyy(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s, format="%d/%m/%y %H:%M")


# ── loaders: each returns {series name: DataFrame indexed by date} ────────────
def ref_calendar() -> tuple[pd.DatetimeIndex, pd.DatetimeIndex]:
    cal = pd.DatetimeIndex(pd.read_csv(FZ / "Data" / "calendar.csv", parse_dates=["date"])["date"])
    td = pd.DatetimeIndex(pd.to_datetime(pd.read_excel(HD / "FRA_MAUc1" / "Data" / "TradingDays.xlsx",
                                                       header=None, skiprows=3)[1]).dropna())
    return cal, td


def load_index_ohlcv() -> dict[str, pd.DataFrame]:
    x = pd.ExcelFile(FZ / "Data" / "indices_ohlcv.xlsx")
    out = {}
    for sh in x.sheet_names:
        d = pd.read_excel(x, sh, parse_dates=["date"]).set_index("date").sort_index()
        out[f"index {sh}"] = d
    return out


def load_masters() -> dict[str, pd.DataFrame]:
    out = {}
    for n in ["Nifty100", "MC100", "SC100", "NiftyMidcap150", "NiftySmallcap250", "NiftyMicrocap250"]:
        out[n] = pd.read_excel(FZ / "Master" / f"Master_{n}.xlsx", parse_dates=["Date"])
    out["MAUc1"] = pd.read_excel(HD / "FRA_MAUc1" / "RSI" / "Final" / "Analysis" / "Master_MAUc1.xlsx", parse_dates=["Date"])
    return out


def load_published(fn: str) -> dict[str, pd.DataFrame]:
    d = pd.read_csv(HD / fn)
    d["date"] = ddmmyy(d["date"])
    out = {}
    for s, g in d.groupby("scid"):
        out[s] = g.set_index("date").sort_index()[["index", "benchmarkIndex"]]
    return out


def load_parent_nav_2026() -> dict[str, pd.DataFrame]:
    """D17: Historical Data/parent_nav_2026-10-22/SCMO_<p>.csv (_id.scid, _id.date YYYY/MM/DD, index; newest first)."""
    out = {}
    for p in PARENTS:
        d = pd.read_csv(HD / "parent_nav_2026-10-22" / f"{p}.csv")
        out[p] = pd.DataFrame({"close": d["index"].values},
                              index=pd.to_datetime(d["_id.date"], format="%Y/%m/%d")).sort_index()
    return out


def holdings_matrix_checks(pub17, ref) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """D18 (per-parent OHLC), D19 (weight matrices) and the session comparison with D17.
    Returns (holdings_ohlc, d17_d18_sessions, holdings_weights)."""
    hm = AA / "data" / "holdings_matrix"
    summ, sess, wts = [], [], []
    for p in PARENTS:
        o = pd.read_csv(hm / f"{p}_ohlc.csv", parse_dates=["date"])
        av = pd.read_csv(hm / f"{p}_ohlc_availability.csv")
        fc = pd.read_csv(hm / f"{p}_ohlc_filled_cells.csv", parse_dates=["date"])
        d18 = pd.DatetimeIndex(sorted(o["date"].unique()))
        nav_d = pub17[p].index
        lo, hi = nav_d.min(), nav_d.max()
        d18_in = d18[(d18 >= lo) & (d18 <= hi)]
        extra = d18_in.difference(nav_d)
        absent = nav_d.difference(d18_in)
        counts = o.groupby("date").size()
        for t in extra:
            near = counts[(counts.index >= t - pd.Timedelta(days=7)) & (counts.index <= t + pd.Timedelta(days=7))
                          & (counts.index != t)]
            sess.append({"parent": p, "date": t.date(), "weekday": t.day_name(), "in_D17": False, "in_D18": True,
                         "in_reference_calendar": bool(t in ref), "D18_stocks_with_a_bar": int(counts[t]),
                         "typical_stocks_nearby": float(near.median()) if len(near) else np.nan})
        for t in absent:
            sess.append({"parent": p, "date": t.date(), "weekday": t.day_name(), "in_D17": True, "in_D18": False,
                         "in_reference_calendar": bool(t in ref), "D18_stocks_with_a_bar": 0, "typical_stocks_nearby": np.nan})
        o4 = o.drop_duplicates(["date", "stock"])
        viol = int(((o4["low"] > o4[["open", "close"]].min(axis=1) + 1e-9) | (o4["high"] < o4[["open", "close"]].max(axis=1) - 1e-9)).sum())
        on_nav = fc[fc["date"].isin(nav_d)]
        summ.append({"parent": p, "first": o["date"].min().date(), "last": o["date"].max().date(), "rows": len(o),
                     "stocks": o["stock"].nunique(), "sessions": len(d18),
                     "src_db": int((o["src"] == "db").sum()), "src_export": int((o["src"] == "export").sum()),
                     "src_carried": int((o["src"] == "carried").sum()),
                     "duplicates": int(o.duplicated(["date", "stock"]).sum()),
                     "blank_close": int(o["close"].isna().sum()), "blank_open_high_low": int(o[["open", "high", "low"]].isna().any(axis=1).sum()),
                     "nonpos_close": int((o["close"] <= 0).sum()), "ohlc_violations": viol,
                     "needed_stock_sessions": int(av["needed_sessions"].sum()), "missing": int(av["missing"].sum()),
                     "partial": int(av["partial_bars"].sum()), "carried": int(av["carried"].sum()),
                     "carried_on_D17_sessions": len(on_nav),
                     "carried_in_T03_window": int((on_nav["date"] <= "2026-08-21").sum()),
                     "d17_sessions_absent_from_d18": len(absent), "d18_sessions_not_in_d17": len(extra)})
        w = pd.read_csv(hm / f"{p}_holding_weight_matrix.csv", index_col=0)
        rs = w.sum(axis=1)
        wts.append({"parent": p, "baskets": len(w), "first": w.index.min(), "last": w.index.max(), "columns": w.shape[1],
                    "rowsum_min": float(rs.min()), "rowsum_max": float(rs.max()), "negative_weights": int((w < 0).sum().sum()),
                    "held_per_basket_min": int((w > 0).sum(axis=1).min()), "held_per_basket_max": int((w > 0).sum(axis=1).max())})
    return pd.DataFrame(summ), pd.DataFrame(sess), pd.DataFrame(wts)


def load_baskets() -> dict[str, pd.DataFrame]:
    out = {}
    for p in PARENTS:
        d = pd.read_csv(FZ / "Rebalance_history" / f"Rebalance_history_by_scid_{p}.csv")
        d["eff"] = ddmmyy(d["availableDate"])
        d["sig"] = pd.to_datetime(d["date"])
        d["isin"] = d["ISIN"].astype("string").str.strip().str.upper()
        out[p] = d
    return out


def load_goldbees() -> dict[str, pd.DataFrame]:
    e = pd.read_parquet(CACHE / "why_gold_ohlc_eikon.parquet").set_index("date").sort_index()
    k = pd.read_parquet(CACHE / "goldbees_kite_ohlcv.parquet")
    k["date"] = pd.to_datetime(k["date"])
    k = k.set_index("date").sort_index()
    db = pd.read_csv(CACHE / "defensive_etf_closes.csv", parse_dates=["date"]).set_index("date").sort_index()
    return {"GOLDBEES Eikon": e, "GOLDBEES Kite (parquet)": k,
            "GOLDBEES Kite (DB closes)": db[["GOLDBEES"]].rename(columns={"GOLDBEES": "close"}).dropna(),
            "LIQUIDBEES Kite (DB closes)": db[["LIQUIDBEES"]].rename(columns={"LIQUIDBEES": "close"}).dropna()}


def load_lbes() -> pd.DataFrame:
    d = pd.read_csv(HD / "LBES_Adjusted_Price_data_2026_08_10.csv")
    d["date"] = ddmmyy(d["date"])
    return d.set_index("date").sort_index().rename(columns={"price": "close"})


def load_mauc1() -> tuple[pd.DataFrame, pd.DataFrame]:
    raw = pd.read_csv(DOWNLOADS / "MAUc1_daily1.csv")
    raw.columns = [c.strip().lower() for c in raw.columns]
    raw["date"] = pd.to_datetime(raw["date"], dayfirst=False, errors="coerce")
    raw = raw.set_index("date").sort_index()
    clean = pd.read_csv(EV / "final_strategy" / "mauc1" / "mauc1_daily_clean.csv", index_col=0, parse_dates=True)
    clean.columns = [c.strip().lower() for c in clean.columns]
    return raw, clean


def load_stock_prices() -> dict[str, pd.DataFrame]:
    a = pd.read_parquet(CACHE / "eikon_ohlcv_2014_2021.parquet").rename(columns={"ticker": "isin"})
    b = pd.read_parquet(CACHE / "keyed_ohlcv_eikon_v2.parquet").rename(columns={"ticker": "isin"})
    k = pd.read_parquet(CACHE / "keyed_ohlcv_v2.parquet").rename(columns={"ticker": "isin"})
    return {"Eikon 2014-21": a, "Eikon 2021-26": b, "Kite 2021-26": k}


# ── checks ──────────────────────────────────────────────────────────────────
def series_checks(name, df, kind, ref, rows_cal, rows_cal_d, rows_val, rows_val_d, rows_moves, close="close"):
    s, dd = L.calendar_check(df.index, ref)
    rows_cal.append({"series": name, "kind": kind, **s})
    if len(dd):
        dd.insert(0, "series", name)
        rows_cal_d.append(dd)
    cols = [c for c in ["open", "high", "low", "close"] if c in df.columns] or [close]
    v, vd = L.value_check(df[~df.index.duplicated()], cols if close in cols else cols + [close],
                          stale_n=5 if kind != "cash" else 3)
    rows_val.append({"series": name, "kind": kind, **v})
    if len(vd):
        vd.insert(0, "series", name)
        rows_val_d.append(vd)
    m = L.largest_moves(df[close][~df.index.duplicated()], THRESH[kind])
    if len(m):
        m.insert(0, "series", name)
        m.insert(1, "threshold", THRESH[kind])
        rows_moves.append(m)


def signal_checks(name, m, ref, idx_close):
    """Weekly Master file: dates, ST on a band, SIGN agrees with the band, close matches the index file."""
    m = m.copy().sort_values("Date")
    d = pd.DatetimeIndex(m["Date"])
    refs = pd.Series(ref, index=ref)
    last_of_week = refs.groupby([ref.isocalendar().year, ref.isocalendar().week]).max()
    lw = pd.DatetimeIndex(last_of_week.values)
    not_last = d.difference(lw)
    has_sign = m["SIGN"].notna()
    first_sign = m.loc[has_sign, "Date"].min()
    sub = m[has_sign]
    tol = 1e-9 * sub["ST"].abs()
    on_flb = (sub["ST"] - sub["FLB"]).abs() <= tol
    on_fub = (sub["ST"] - sub["FUB"]).abs() <= tol
    sign_bad = ((sub["SIGN"] == "BUY") & ~on_flb) | ((sub["SIGN"] == "SELL") & ~on_fub) | ~sub["SIGN"].isin(["BUY", "SELL"])
    # weeks with an NSE session but no row, inside the file's span
    wk = pd.Series(1, index=lw[(lw >= d.min()) & (lw <= d.max())])
    missing_weeks = wk.index.difference(d)
    flips = int((sub["SIGN"] != sub["SIGN"].shift()).sum() - 1)
    out = {"signal": name, "first_row": d.min().date(), "last_row": d.max().date(), "rows": len(m),
           "first_sign": pd.Timestamp(first_sign).date(), "sign_rows": int(has_sign.sum()),
           "share_buy": float((sub["SIGN"] == "BUY").mean()), "flips": flips,
           "dates_not_last_session_of_week": len(not_last), "weeks_missing": len(missing_weeks),
           "sign_not_matching_band": int(sign_bad.sum()), "last_sign": sub["SIGN"].iloc[-1]}
    if idx_close is not None:
        c = idx_close.reindex(d)
        # Master `Index` holds the weekly close the supertrend was computed on
        diff = (m.set_index("Date")["Index"] / c - 1).abs()
        out["close_vs_index_file_max_rel_diff"] = float(diff.max())
        out["close_vs_index_file_rows_over_1e-6"] = int((diff > 1e-6).sum())
    return out, not_last, missing_weeks


def basket_checks(p, d):
    rows = []
    isin_ok = d["isin"].str.fullmatch(r"IN[EF][A-Z0-9]{8}[0-9]").fillna(False)
    for eff, g in d.groupby("eff"):
        rows.append({"parent": p, "effective": eff.date(), "signal_date": g["sig"].iloc[0].date(),
                     "lag_days": (eff - g["sig"].iloc[0]).days, "names": len(g),
                     "weight_sum": round(float(g["weight"].sum()), 6), "skipped_rows": int(g["skipped"].sum()),
                     "blank_ticker": int(g["ticker"].isna().sum()),
                     "ticker_with_star": int(g["ticker"].astype(str).str.endswith("*").sum()),
                     "bad_isin": int((~isin_ok[g.index]).sum()), "duplicate_isin": int(g["isin"].duplicated().sum())})
    return pd.DataFrame(rows)


def coverage(baskets, prices, ref, win, label):
    """Every (parent, session, held ISIN) inside the window: is there a close in the price file?"""
    lo, hi = map(pd.Timestamp, win)
    px = prices.set_index(["isin", "date"])["close"]
    have = set(zip(prices["isin"], prices["date"]))
    sess = ref[(ref >= lo) & (ref <= hi)]
    rows, miss = [], []
    present_maps = {}
    for p, d in baskets.items():
        effs = sorted(d["eff"].unique())
        held = []
        for i, e in enumerate(effs):
            nxt = effs[i + 1] if i + 1 < len(effs) else hi + pd.Timedelta(days=1)
            ss = sess[(sess >= e) & (sess < nxt)]
            if not len(ss):
                continue
            for isin in d.loc[d["eff"] == e, "isin"].dropna().unique():
                held.append(pd.DataFrame({"date": ss, "isin": isin}))
        h = pd.concat(held, ignore_index=True)
        h["present"] = [(i, t) in have for i, t in zip(h["isin"], h["date"])]
        names = d.drop_duplicates("isin").set_index("isin")[["ticker", "name"]]
        rows.append({"window": label, "parent": p, "first": h["date"].min().date(), "last": h["date"].max().date(),
                     "isins_held": h["isin"].nunique(), "held_stock_sessions": len(h),
                     "missing_stock_sessions": int((~h["present"]).sum()),
                     "isins_with_any_missing": int(h.loc[~h["present"], "isin"].nunique())})
        for isin, g in h[~h["present"]].groupby("isin"):
            miss.append({"window": label, "parent": p, "isin": isin,
                         "ticker": names.loc[isin, "ticker"] if isin in names.index else "",
                         "name": names.loc[isin, "name"] if isin in names.index else "",
                         "missing_sessions": len(g), "held_sessions": int((h["isin"] == isin).sum()),
                         "first_missing": g["date"].min().date(), "last_missing": g["date"].max().date()})
        present_maps[p] = h.pivot_table(index="date", columns="isin", values="present", aggfunc="first")
    return pd.DataFrame(rows), pd.DataFrame(miss), present_maps


def unpriced_weight(baskets, prices, ref, win, label, special):
    """Share of a parent's weight-sessions with no close in the price file.

    share = Σ_t Σ_i w_i,t × 1[no close for i on t] ÷ number of sessions, over the window's sessions t,
    with w the basket's listed weight (no drift). Special weekend/holiday sessions absent from every
    stock source are excluded (they are a calendar question, not a price gap).
    """
    lo, hi = map(pd.Timestamp, win)
    have = set(zip(prices["isin"], prices["date"]))
    sess = ref[(ref >= lo) & (ref <= hi)]
    sess = sess[~sess.isin(special)]
    out = []
    for p, d in baskets.items():
        effs = sorted(d["eff"].unique())
        tot, aff, worst, worst_day = 0, 0.0, 0.0, None
        for i, e in enumerate(effs):
            nxt = effs[i + 1] if i + 1 < len(effs) else hi + pd.Timedelta(days=1)
            g = d[d["eff"] == e]
            for t in sess[(sess >= e) & (sess < nxt)]:
                m = float(sum(w for isin, w in zip(g["isin"], g["weight"]) if (isin, t) not in have))
                aff += m
                tot += 1
                if m > worst:
                    worst, worst_day = m, t
        out.append({"window": label, "parent": p, "sessions": tot, "unpriced_weight_share": aff / tot if tot else np.nan,
                    "worst_day_unpriced_weight": worst, "worst_day": worst_day.date() if worst_day is not None else None})
    return pd.DataFrame(out)


def history_ends(prices, ref_last, label):
    """ISINs whose price history ends well before the file's last date.

    Eikon marks a delisted instrument's RIC with ^<month letter A-L><yy>, the month it stopped trading.
    A history that ends years before that month is a gap in the data, not a delisting.
    """
    g = prices.groupby("isin").agg(first=("date", "min"), last=("date", "max"), rows=("date", "size"),
                                   ric=("ric" if "ric" in prices.columns else "src", "first"))
    g = g[g["last"] < pd.Timestamp(ref_last)].reset_index()
    m = g["ric"].astype(str).str.extract(r"\^([A-L])(\d{2})$")
    g["delisted_per_ric"] = [pd.Timestamp(2000 + int(y), "ABCDEFGHIJKL".index(mo) + 1, 1).strftime("%Y-%m")
                             if isinstance(mo, str) else "" for mo, y in zip(m[0], m[1])]
    g["shares_end_date_with"] = g.groupby("last")["isin"].transform("size") - 1
    g["reading"] = np.where(g["shares_end_date_with"] >= 4, "GAP: many histories end on this same date",
                            np.where(g["delisted_per_ric"] == "", "check", "delisted or merged"))
    g.insert(0, "file", label)
    return g


def thin_sessions(prices, sess, frac=0.5):
    """Sessions where the price file has rows for fewer than `frac` of the names it has around that date."""
    n = prices.groupby("date")["isin"].size().reindex(sess, fill_value=0)
    typical = n.rolling(11, center=True, min_periods=3).median()
    return n[n < frac * typical].index, n, typical


def held_moves(baskets, prices, ref, win, label, thr):
    """Daily close moves beyond the threshold on stocks while a parent held them."""
    lo, hi = map(pd.Timestamp, win)
    px = prices.pivot_table(index="date", columns="isin", values="close").sort_index()
    r = px.pct_change(fill_method=None)
    out = []
    for p, d in baskets.items():
        effs = sorted(d["eff"].unique())
        for i, e in enumerate(effs):
            nxt = effs[i + 1] if i + 1 < len(effs) else hi + pd.Timedelta(days=1)
            a, b = max(e, lo), min(nxt - pd.Timedelta(days=1), hi)
            if a > b:
                continue
            for isin in d.loc[d["eff"] == e, "isin"].dropna().unique():
                if isin not in r.columns:
                    continue
                rr = r.loc[a:b, isin].dropna()
                for t, v in rr[rr.abs() >= thr].items():
                    nx = r[isin].shift(-1).get(t, np.nan)
                    out.append({"window": label, "parent": p, "isin": isin,
                                "ticker": d.loc[d["isin"] == isin, "ticker"].iloc[0], "date": t.date(), "move": v,
                                "next_day": nx, "reverses_next_day": bool(pd.notna(nx) and np.sign(nx) == -np.sign(v) and abs(nx) >= 0.15)})
    o = pd.DataFrame(out)
    return o.drop_duplicates(["isin", "date"]) if len(o) else o


def stock_source_diffs(e, k, thr=0.05):
    """Eikon vs Kite, same ISIN, same day: daily close returns that differ by more than thr."""
    pe = e.pivot_table(index="date", columns="isin", values="close").sort_index().pct_change(fill_method=None)
    pk = k.pivot_table(index="date", columns="isin", values="close").sort_index().pct_change(fill_method=None)
    cols = pe.columns.intersection(pk.columns)
    idx = pe.index.intersection(pk.index)
    dlt = (pe.loc[idx, cols] - pk.loc[idx, cols]).stack()
    big = dlt[dlt.abs() > thr]
    rows = [{"date": t.date(), "isin": i, "eikon_return": pe.at[t, i], "kite_return": pk.at[t, i], "difference": v}
            for (t, i), v in big.items()]
    return pd.DataFrame(rows), {"isins_compared": len(cols), "isin_days_compared": int(dlt.notna().sum()),
                                "days_over_5pct": int(len(big)), "isins_with_any": int(big.index.get_level_values(1).nunique()) if len(big) else 0}


# ── main ────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    a = ap.parse_args()
    out = HERE / "review" / a.date
    ch = out / "charts"
    ch.mkdir(parents=True, exist_ok=True)
    dec = json.loads((HERE / "review_decisions.json").read_text(encoding="utf-8"))

    cal, td = ref_calendar()
    ref = td  # the production TradingDays list (Refinitiv .NSEI), to 2026-09-25
    summary = {"review_date": a.date, "reference_calendar": {"source": "FRA_MAUc1/Data/TradingDays.xlsx",
               "first": str(ref.min().date()), "last": str(ref.max().date()), "sessions": len(ref)}}
    s_cal, d_cal = L.calendar_check(cal, ref)
    summary["calendar_csv_vs_tradingdays"] = {k: str(v) for k, v in s_cal.items()}

    rc, rcd, rv, rvd, rm = [], [], [], [], []
    charts = {}

    # indices behind the signals
    idx = load_index_ohlcv()
    for n, d in idx.items():
        series_checks(n, d, "index", ref, rc, rcd, rv, rvd, rm)
    for n in ["index Nifty100", "index MC100", "index SC100", "index NSEI"]:
        charts[n] = L.series_panel(idx[n]["close"], n, ch / f"{n.replace(' ', '_')}.png", THRESH["index"]).name

    # published NAVs
    pub_parent, pub_aa = load_published("parentIndices.csv"), load_published("indices.csv")
    for grp, pub in (("published parent", pub_parent), ("published AA", pub_aa)):
        for s, d in pub.items():
            n = f"{grp} {s}"
            series_checks(n, d.rename(columns={"index": "close"}), "nav", ref, rc, rcd, rv, rvd, rm)
            charts[n] = L.series_panel(d["index"], n, ch / f"{n.replace(' ', '_')}.png", THRESH["nav"]).name

    # D17: published parent NAVs, 2019-2026 (export of 2026-10-22)
    pub17 = load_parent_nav_2026()
    for p17, d17 in pub17.items():
        series_checks(f"D17 published parent {p17}", d17, "nav", ref, rc, rcd, rv, rvd, rm)

    # gold, cash
    gb = load_goldbees()
    for n, d in gb.items():
        series_checks(n, d, "cash" if "LIQUID" in n else "etf", ref, rc, rcd, rv, rvd, rm)
    charts["GOLDBEES Eikon"] = L.series_panel(gb["GOLDBEES Eikon"]["close"], "GOLDBEES Eikon", ch / "GOLDBEES_Eikon.png", THRESH["etf"]).name
    lb = load_lbes()
    series_checks("LBES adjusted (cash)", lb, "cash", ref, rc, rcd, rv, rvd, rm)
    charts["LBES adjusted (cash)"] = L.series_panel(lb["close"], "LBES adjusted (cash)", ch / "LBES.png", THRESH["cash"]).name
    raw, clean = load_mauc1()
    series_checks("MAUc1 raw export", raw, "future", ref, rc, rcd, rv, rvd, rm)
    series_checks("MAUc1 cleaned", clean, "future", ref, rc, rcd, rv, rvd, rm)
    charts["MAUc1 cleaned"] = L.series_panel(clean["close"], "MAUc1 cleaned", ch / "MAUc1.png", THRESH["future"]).name

    # signals
    masters = load_masters()
    sig_rows, sig_detail = [], []
    idx_for = {"Nifty100": "index Nifty100", "MC100": "index MC100", "SC100": "index SC100",
               "NiftyMidcap150": "index NiftyMidcap150", "NiftySmallcap250": "index NiftySmallcap250",
               "NiftyMicrocap250": "index NiftyMicrocap250"}
    for n, m in masters.items():
        ic = idx[idx_for[n]]["close"] if n in idx_for else None
        o, nl, mw = signal_checks(n, m, ref, ic)
        sig_rows.append(o)
        for t in nl:
            sig_detail.append({"signal": n, "date": t.date(), "issue": "row date is not the last NSE session of its week"})
        for t in mw:
            sig_detail.append({"signal": n, "date": t.date(), "issue": "week with an NSE session has no row"})

    # parent baskets and stock prices
    bk = load_baskets()
    baskets = pd.concat([basket_checks(p, d) for p, d in bk.items()], ignore_index=True)
    sp = load_stock_prices()
    for n in ("Eikon 2014-21", "Eikon 2021-26", "Kite 2021-26"):
        d = sp[n]
        v = {"series": f"stocks {n}", "kind": "stock", "rows": len(d), "isins": d["isin"].nunique(),
             "first": d["date"].min().date(), "last": d["date"].max().date(),
             "blank_close": int(d["close"].isna().sum()), "nonpos_close": int((d["close"] <= 0).sum()),
             "blank_open": int(d["open"].isna().sum()),
             "duplicates": int(d.duplicated(["isin", "date"]).sum()),
             "extra_dates": int(len(pd.DatetimeIndex(d["date"].unique()).difference(ref))),
             "ohlc_violations": int(((d["low"] > d[["open", "close"]].min(axis=1) + 1e-9) |
                                     (d["high"] < d[["open", "close"]].max(axis=1) - 1e-9)).sum())}
        rv.append(v)
    cov_rows, cov_miss, moves, unp, ends, absent = [], [], [], [], [], []
    for lab, pxn in (("2014-21", "Eikon 2014-21"), ("2021-26", "Eikon 2021-26")):
        c, mm, maps = coverage(bk, sp[pxn], ref, WINDOWS[lab], lab)
        cov_rows.append(c)
        cov_miss.append(mm)
        lo, hi = map(pd.Timestamp, WINDOWS[lab])
        sess = ref[(ref >= lo) & (ref <= hi)]
        special, n_rows, typical = thin_sessions(sp[pxn], sess)  # a calendar question, not a price gap
        absent += [{"window": lab, "date": t.date(), "weekday": t.day_name(), "stocks_with_a_row": int(n_rows[t]),
                    "typical_around_it": float(typical[t])} for t in special]
        unp.append(unpriced_weight(bk, sp[pxn], ref, WINDOWS[lab], lab, special))
        ends.append(history_ends(sp[pxn], sp[pxn]["date"].max() - pd.Timedelta(days=30), pxn))
        allmap = pd.concat(maps.values(), axis=1)
        allmap = allmap.T.groupby(level=0).max().T  # one column per ISIN, present if any parent's row present
        charts[f"coverage {lab}"] = L.coverage_map(allmap.astype(float), f"Stock prices over held sessions, {WINDOWS[lab][0]} → {WINDOWS[lab][1]} "
                                                   f"(blue present, red missing, blank not held)", ch / f"coverage_{lab}.png").name
        moves.append(held_moves(bk, sp[pxn], ref, WINDOWS[lab], lab, THRESH["stock"]))
    cov = pd.concat(cov_rows, ignore_index=True).merge(pd.concat(unp, ignore_index=True), on=["window", "parent"])
    covm = pd.concat(cov_miss, ignore_index=True)
    pd.concat(ends, ignore_index=True).to_csv(out / "price_history_ends_early.csv", index=False)
    pd.DataFrame(absent).to_csv(out / "sessions_absent_from_stock_file.csv", index=False)
    smoves = pd.concat(moves, ignore_index=True)
    sdiff, sdiff_sum = stock_source_diffs(sp["Eikon 2021-26"], sp["Kite 2021-26"])
    summary["stock_source_diffs"] = sdiff_sum

    # reconciliations (on returns)
    rec = []
    nav = pd.read_csv(EV / "final_strategy" / "nav_curves_daily.csv", index_col=0, parse_dates=True)
    for b, p in BOOKS.items():
        h = nav[f"live 2021-11 -> 2026-08|{b}|parent (no overlay)"].dropna()
        pp = pub_parent[p]["index"]
        rec.append({"pair": f"{p}: harness rebuild vs published NAV", **L.returns_gap(h, pp)})
        charts[f"harness vs published {p}"] = L.overlay_chart({"harness rebuild": h, "published NAV": pp},
                                                              f"{p} harness vs published", ch / f"harness_vs_published_{p}.png").name
    for p, d in pub17.items():
        rec.append({"pair": f"{p}: D17 (2019-26 export) vs D14 parentIndices.csv", **L.returns_gap(d["close"], pub_parent[p]["index"])})
    for p, d in pub_parent.items():
        rec.append({"pair": f"{p} file: benchmarkIndex vs Nifty 50 (index file)", **L.returns_gap(d["benchmarkIndex"], idx["index NSEI"]["close"])})
    e = gb["GOLDBEES Eikon"]["close"]
    rec.append({"pair": "GOLDBEES: Eikon vs Kite (parquet)", **L.returns_gap(e, gb["GOLDBEES Kite (parquet)"]["close"])})
    rec.append({"pair": "GOLDBEES: Eikon vs Kite (DB closes)", **L.returns_gap(e, gb["GOLDBEES Kite (DB closes)"]["close"])})
    charts["GOLDBEES sources"] = L.overlay_chart({"Eikon": e, "Kite parquet": gb["GOLDBEES Kite (parquet)"]["close"]},
                                                 "GOLDBEES, two sources", ch / "goldbees_sources.png").name
    rec.append({"pair": "Cash: LBES adjusted vs LIQUIDBEES price (Kite)", **L.returns_gap(lb["close"], gb["LIQUIDBEES Kite (DB closes)"]["close"])})
    charts["cash"] = L.overlay_chart({"LBES adjusted": lb["close"], "LIQUIDBEES price": gb["LIQUIDBEES Kite (DB closes)"]["close"]},
                                     "Cash leg vs the raw fund price", ch / "cash_vs_price.png", log=False).name
    gw = e.resample("W-FRI").last()
    mw = clean["close"].resample("W-FRI").last()
    rec.append({"pair": "MAUc1 cleaned vs GOLDBEES Eikon (weekly, Friday)", **L.returns_gap(mw, gw)})

    # derived series
    der = []
    mlog = EV / "final_strategy" / "mauc1" / "mauc1_cleaning_log.csv"
    der.append({"series": "MAUc1 cleaned", "rows_in": len(raw), "rows_out": len(clean),
                "changes": len(pd.read_csv(mlog)) if mlog.exists() else None, "log": str(mlog.relative_to(AA))})
    gf = pd.read_csv(EV / "final_strategy" / "goldbees_fill_despiked.csv", parse_dates=["date"])
    chg = (gf.loc[gf["changed"], "fill_ohlc4_clean"] / gf.loc[gf["changed"], "ohlc4_raw"] - 1)
    der.append({"series": "GOLDBEES fill (de-spiked OHLC4)", "rows_in": len(gf), "rows_out": len(gf),
                "changes": int(gf["changed"].sum()), "median_change": float(chg.median()),
                "p01_change": float(chg.quantile(0.01)), "p99_change": float(chg.quantile(0.99)),
                "max_abs_change": float(chg.abs().max()),
                "log": "analysis/evidence/final_strategy/goldbees_fill_despiked.csv"})
    yr = lb["close"].groupby(lb.index.year).last()  # year-end level; no resample alias, so any pandas version
    lbes_years = ((yr / yr.shift()) - 1).dropna()
    summary["lbes_calendar_year_returns"] = {str(k): round(float(v), 5) for k, v in lbes_years.items()}

    # large moves: a second series on the same day, and the human note for the date
    ret = lambda s: s[~s.index.duplicated()].pct_change()
    conf = {"Nifty 50": ret(idx["index NSEI"]["close"]), "Nifty 100": ret(idx["index Nifty100"]["close"]),
            "GOLDBEES Eikon": ret(e), "GOLDBEES Kite": ret(gb["GOLDBEES Kite (parquet)"]["close"]),
            "MAUc1": ret(clean["close"]), "Smallcap 100": ret(idx["index SC100"]["close"]),
            "Smallcap 250": ret(idx["index NiftySmallcap250"]["close"]), "Microcap 250": ret(idx["index NiftyMicrocap250"]["close"]),
            "Midcap 100": ret(idx["index MC100"]["close"]), "Midcap 150": ret(idx["index NiftyMidcap150"]["close"])}
    for b, p in BOOKS.items():
        conf[f"harness {p}"] = ret(nav[f"live 2021-11 -> 2026-08|{b}|parent (no overlay)"].dropna())
    # D17's second source: the parent rebuilt from D18 and D19 (data/parent_rebuild_hm.py, listed weights, F-AA-D14 applied)
    rb_file = AA / "data" / "parent_rebuild_hm" / "daily.csv"
    if rb_file.exists():
        rb = pd.read_csv(rb_file, parse_dates=["date"])
        rb = rb[rb["variant"] == "listed_weights_skip_dropped_corrected"]
        for p, g in rb.groupby("parent"):
            conf[f"rebuild D18 {p}"] = ret(g.set_index("date")["model"])

    def second(series, t, move):
        """Text of the comparison series' moves, and whether any agrees: same sign, at least 0.3x the size."""
        t = pd.Timestamp(t)
        if series.startswith("D17"):
            ks = ([(f"rebuild D18 {series.split()[-1]}", t)] if f"rebuild D18 {series.split()[-1]}" in conf else []) + [("Nifty 50", t)]
        elif series.startswith("index NSEI"):
            ks = [("Nifty 100", t)]
        elif series in ("index SC100", "index NiftySmallcap250", "index NiftyMicrocap250", "index NiftyMidcap150", "index MC100"):
            peers = {"index SC100": ["Smallcap 250", "Midcap 100"], "index NiftySmallcap250": ["Smallcap 100", "Microcap 250"],
                     "index NiftyMicrocap250": ["Smallcap 250", "Smallcap 100"], "index NiftyMidcap150": ["Midcap 100", "Smallcap 250"],
                     "index MC100": ["Midcap 150", "Smallcap 100"]}[series]
            ks = [("Nifty 50", t)] + [(p, t) for p in peers]
        elif series.startswith("index"):
            ks = [("Nifty 50", t)]
        elif series.startswith("published parent"):
            ks = [(f"harness {series.split()[-1]}", t), ("Nifty 50", t)]
        elif series.startswith("published AA"):
            ks = [("Nifty 50", t)]
        elif series.startswith("GOLDBEES Eikon"):
            ks = [("GOLDBEES Kite", t), ("MAUc1", t)]
        elif series.startswith("GOLDBEES Kite"):
            ks = [("GOLDBEES Eikon", t)]
        elif series.startswith("MAUc1"):
            g = conf["GOLDBEES Eikon"]
            nxt = g.index[g.index > t]
            ks = [("GOLDBEES Eikon", t)] + ([("GOLDBEES Eikon", nxt[0])] if len(nxt) else [])
        else:
            return "", False
        parts, agree = [], False
        for k, when in ks:
            v = conf[k].get(when, np.nan)
            if pd.isna(v):
                continue
            parts.append(f"{k} {'same day' if when == t else 'next session ' + str(when.date())} {100*v:+.1f}%")
            agree |= bool(pd.notna(v) and np.sign(v) == np.sign(move) and abs(v) >= 0.3 * abs(move))
        return "; ".join(parts), agree
    lm = pd.concat(rm, ignore_index=True) if rm else pd.DataFrame()
    notes = dec.get("move_notes", {})
    if len(lm):
        sec = [second(s, t, mv) for s, t, mv in zip(lm["series"], lm["date"], lm["move"])]
        lm["second_source"] = [x[0] for x in sec]
        lm["second_source_agrees"] = [x[1] for x in sec]
        lm["explanation"] = [notes.get(str(pd.Timestamp(t).date()),
                                       "real move: a second source agrees" if ok else ("no second source" if not txt else "UNCONFIRMED: check"))
                             for t, (txt, ok) in zip(lm["date"], sec)]

    # spot checks: our value on dates a person checks against a public source
    look = {"index Nifty100": idx["index Nifty100"]["close"], "index MC100": idx["index MC100"]["close"],
            "index SC100": idx["index SC100"]["close"], "GOLDBEES Eikon": e, "LBES adjusted (cash)": lb["close"],
            "MAUc1 cleaned": clean["close"], "published parent SCMO_0003": pub_parent["SCMO_0003"]["index"]}
    spot = []
    for item in dec.get("spot_checks", []):
        s = look[item["series"]]
        t = pd.Timestamp(item["date"])
        spot.append({"series": item["series"], "date": t.date(), "value_here": s.get(t, np.nan),
                     "value_found": item.get("value_found", ""), "source": item.get("source", ""),
                     "status": item.get("status", "not yet checked")})

    # D18 / D19 and the session comparison with D17
    h_ohlc, h_sess, h_wts = holdings_matrix_checks(pub17, ref)

    # inventory: fingerprints + human metadata
    inv = []
    for item in dec["inputs"]:
        paths = item["paths"]
        for pth in paths:
            fp = (AA / pth) if not pth.startswith("C:") else Path(pth)
            row = {"id": item["id"], "input": item["name"], "file": pth, **{k: item.get(k, "") for k in
                   ("role", "source", "fetched_by", "fetched_on", "basis", "used_by", "verdict")}}
            if fp.exists():
                f = L.fingerprint(fp)
                row.update({"bytes": f["bytes"], "sha256": f["sha256"], "file_modified": f["modified"]})
            else:
                row.update({"bytes": None, "sha256": "MISSING", "file_modified": None})
            inv.append(row)

    # write (an empty table is written with its header, so a reader can tell "checked, none" from "missing")
    def save(df, name, cols=None):
        if df is None or not len(df):
            df = pd.DataFrame(columns=cols or ["none"])
        df.to_csv(out / name, index=False)

    h_ohlc.to_csv(out / "holdings_ohlc.csv", index=False)
    save(h_sess, "d17_d18_sessions.csv", ["parent", "date", "weekday", "in_D17", "in_D18"])
    h_wts.to_csv(out / "holdings_weights.csv", index=False)
    pd.DataFrame(inv).to_csv(out / "inventory.csv", index=False)
    pd.DataFrame(rc).to_csv(out / "calendar.csv", index=False)
    save(pd.concat(rcd, ignore_index=True) if rcd else None, "calendar_diffs.csv", ["series", "date", "kind", "weekday"])
    save(d_cal, "calendar_csv_vs_tradingdays.csv", ["date", "kind", "weekday"])
    pd.DataFrame(rv).to_csv(out / "values.csv", index=False)
    save(pd.concat(rvd, ignore_index=True) if rvd else None, "value_issues.csv", ["series", "date", "kind", "detail"])
    save(lm, "largest_moves.csv")
    pd.DataFrame(sig_rows).to_csv(out / "signals.csv", index=False)
    save(pd.DataFrame(sig_detail), "signal_issues.csv", ["signal", "date", "issue"])
    save(pd.DataFrame(spot), "spot_checks.csv", ["series", "date", "value_here", "value_found", "source", "status"])
    save(pd.DataFrame(dec.get("issues", [])), "issues.csv", ["id", "input", "issue", "effect", "handling", "status"])
    baskets.to_csv(out / "baskets.csv", index=False)
    cov.to_csv(out / "coverage.csv", index=False)
    covm.to_csv(out / "coverage_missing.csv", index=False)
    smoves.to_csv(out / "stock_moves.csv", index=False)
    sdiff.to_csv(out / "stock_source_diffs.csv", index=False)
    pd.DataFrame(rec).to_csv(out / "reconciliation.csv", index=False)
    pd.DataFrame(der).to_csv(out / "derived.csv", index=False)
    summary["charts"] = charts
    (out / "summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
