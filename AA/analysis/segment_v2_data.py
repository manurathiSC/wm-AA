# -*- coding: utf-8 -*-
"""
Inputs for the segment-level v2 study, keyed on ISIN.

Why ISIN. The Sep-2026 re-export of the parent rebalance files writes each
holding's *current* ticker onto its historical rows, while
`merged_historical_data_with_rics` and `mcap_based_universe` keep the ticker
that was in use on each date. A ticker join therefore breaks on every rename.
Gujarat Gas (INE844O01030) is `GUJENERGY` in the parent file but `GUJGASLTD`
in both DB tables until 2026-06-30, so a ticker join called it unpriced and
unranked when it was neither. ISIN does not change on a rename, so everything
here resolves a holding to its ISIN first. Ticker is only a fallback.

Caches written (all under `cache/`, never overwriting the v1 files):

    mcap_universe_raw_isin.csv   date, ticker, isin, mcap (ordinary shares)
    mcap_ranks_monthly_v2.csv    snapshot_date, isin, ticker, mcap, rank, category
    mcap_ranks_semiannual_v2.csv the same on NSE's semi-annual calendar
    index_constituents_v2.csv    every membership snapshot, with ISIN
    universe_ohlcv_v2.parquet    daily OHLC per ticker for every ISIN held
"""

from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

from common import CACHE_DIR, DATA_DIR, PAIRS, PG_FETCH_DIR
from mcap_ranks import (
    EFFECTIVE_MONTH_ENDS,
    INDEX_NAME_TO_CAT,
    LOOKBACK_MONTHS,
    REFERENCE_MONTH_ENDS,
    band_of,
    reconstitution_dates,
)

FROZEN_DIR = DATA_DIR / "frozen_2026-09-25"
REBAL_DIR = FROZEN_DIR / "Rebalance_history"
MASTER_DIR = FROZEN_DIR / "Master"
CALENDAR_CSV = FROZEN_DIR / "Data" / "calendar.csv"
OVERRIDES_CSV = DATA_DIR / "bucket_overrides.csv"

WINDOW_START = pd.Timestamp("2021-11-01")
WINDOW_END = pd.Timestamp("2026-08-21")

MCAP_START = "2019-08-01"
MCAP_END = "2026-09-24"
PRICE_START = "2021-06-01"
PRICE_END = "2026-08-21"
CHUNK = 120


def _engine():
    p = str(PG_FETCH_DIR)
    if p not in sys.path:
        sys.path.insert(0, p)
    import pg_price_client  # noqa: PLC0415

    return pg_price_client._get_engine()


def _read_sql(sql: str, params: dict | None = None) -> pd.DataFrame:
    from sqlalchemy import text  # noqa: PLC0415

    with _engine().connect() as conn:
        conn.execute(text("SET TRANSACTION READ ONLY"))
        return pd.read_sql(text(sql), conn, params=params or {})


# ── Parent holdings ────────────────────────────────────────────────────────
def parent_history(parent_scid: str, version: str = "current") -> pd.DataFrame:
    """
    One parent's rebalance history from the frozen copy, cleaned.

    `version="v0"` reads the pre-Sep-18 export that Study 2 ran on, for the
    regression check. Tickers are upper-cased and stripped, including a
    trailing `*` that the new export appends to some names. Blank tickers
    (which pandas reads as NaN, and Study 2's cleanup turned into the string
    "NAN") are left blank here and resolved from ISIN downstream.
    """
    suffix = "" if version == "current" else f"_{version}"
    d = pd.read_csv(REBAL_DIR / f"Rebalance_history_by_scid_{parent_scid}{suffix}.csv")
    d["eff_date"] = pd.to_datetime(d["availableDate"], format="%d/%m/%y %H:%M")
    d["signal_date"] = pd.to_datetime(d["date"])
    t = d["ticker"].astype("string").str.strip().str.upper().str.rstrip("*")
    d["ticker_raw"] = d["ticker"]
    d["ticker"] = t.fillna("")
    d["isin"] = d["ISIN"].astype("string").str.strip().str.upper().fillna("")
    d["weight"] = pd.to_numeric(d["weight"], errors="coerce")
    return d.sort_values(["eff_date", "ticker"]).reset_index(drop=True)


def window_baskets(hist: pd.DataFrame) -> pd.DataFrame:
    """Every basket in effect at some point inside the window."""
    effs = sorted(hist["eff_date"].unique())
    first = max(e for e in effs if e <= WINDOW_START)
    keep = [e for e in effs if first <= e <= WINDOW_END]
    return hist[hist["eff_date"].isin(keep)]


# ── Market cap, with ISIN ──────────────────────────────────────────────────
def raw_mcap_isin(refresh: bool = False) -> pd.DataFrame:
    path = CACHE_DIR / "mcap_universe_raw_isin.csv"
    if path.exists() and not refresh:
        return pd.read_csv(path, parse_dates=["date"], dtype={"isin": "string"})
    df = _read_sql(
        "SELECT date, ticker, isin, mcap FROM public.mcap_based_universe "
        "WHERE date >= :s AND date <= :e AND instrument_class = 'ordinary' "
        "AND mcap IS NOT NULL AND ticker IS NOT NULL",
        {"s": MCAP_START, "e": MCAP_END},
    )
    df["date"] = pd.to_datetime(df["date"])
    df["ticker"] = df["ticker"].str.strip().str.upper()
    df["isin"] = df["isin"].astype("string").str.strip().str.upper()
    df["mcap"] = df["mcap"].astype(float)
    # Same de-duplication as `mcap_ranks.raw_mcap`, so ranks reproduce the v1
    # cache: one row per (date, ticker), the largest if a ticker doubles up.
    df = (df.sort_values("mcap", ascending=False)
            .drop_duplicates(subset=["date", "ticker"], keep="first")
            .sort_values(["date", "ticker"]).reset_index(drop=True))
    df.to_csv(path, index=False)
    return df


def _month_end_grid(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    d["month"] = d["date"].dt.to_period("M")
    last = d.groupby("month")["date"].transform("max")
    return d[d["date"] == last].drop(columns="month")


def monthly_ranks_v2(refresh: bool = False) -> pd.DataFrame:
    """
    Month-end point-in-time ranks, as `mcap_ranks.monthly_ranks` computes
    them, but keeping ISIN. Ranking is on the (date, ticker) rows exactly as
    v1 did, so ranks match the v1 cache wherever both exist (checked in
    `audit`).
    """
    path = CACHE_DIR / "mcap_ranks_monthly_v2.csv"
    if path.exists() and not refresh:
        return pd.read_csv(path, parse_dates=["snapshot_date"], dtype={"isin": "string"})
    d = _month_end_grid(raw_mcap_isin(refresh=refresh))
    d = d.sort_values(["date", "mcap"], ascending=[True, False])
    d["rank"] = d.groupby("date").cumcount() + 1
    d["category"] = d["rank"].map(band_of)
    out = d.rename(columns={"date": "snapshot_date"}).reset_index(drop=True)
    out = out[["snapshot_date", "isin", "ticker", "mcap", "rank", "category"]]
    out.to_csv(path, index=False)
    return out


def semiannual_ranks_v2(refresh: bool = False) -> pd.DataFrame:
    """
    NSE-calendar ranks on six-month mean market cap, averaged per ISIN so a
    rename inside the reference window does not split one company into two.
    Sensitivity only.
    """
    path = CACHE_DIR / "mcap_ranks_semiannual_v2.csv"
    if path.exists() and not refresh:
        return pd.read_csv(path, parse_dates=["snapshot_date"], dtype={"isin": "string"})
    raw = raw_mcap_isin(refresh=refresh)
    raw = raw[raw["isin"].notna() & (raw["isin"] != "")]
    frames = []
    for eff in reconstitution_dates(raw["date"]):
        ref_month = REFERENCE_MONTH_ENDS[EFFECTIVE_MONTH_ENDS.index(eff.month)]
        ref_end = pd.Timestamp(year=eff.year, month=ref_month, day=1) + pd.offsets.MonthEnd(0)
        ref_start = ref_end - pd.DateOffset(months=LOOKBACK_MONTHS) + pd.Timedelta(days=1)
        w = raw[(raw["date"] >= ref_start) & (raw["date"] <= ref_end)]
        if w.empty:
            continue
        last_tkr = w.sort_values("date").groupby("isin")["ticker"].last()
        avg = w.groupby("isin")["mcap"].mean().sort_values(ascending=False).reset_index()
        avg["ticker"] = avg["isin"].map(last_tkr)
        avg["rank"] = range(1, len(avg) + 1)
        avg["category"] = avg["rank"].map(band_of)
        avg["snapshot_date"] = eff
        frames.append(avg)
    out = pd.concat(frames, ignore_index=True)[
        ["snapshot_date", "isin", "ticker", "mcap", "rank", "category"]]
    out.to_csv(path, index=False)
    return out


def isin_ticker_spans(refresh: bool = False) -> pd.DataFrame:
    """For each ISIN, every ticker it carried and the dates it carried it."""
    raw = raw_mcap_isin(refresh=refresh)
    raw = raw[raw["isin"].notna() & (raw["isin"] != "")]
    return (raw.groupby(["isin", "ticker"])["date"].agg(first="min", last="max")
               .reset_index().sort_values(["isin", "first"]))


# ── Real index membership ──────────────────────────────────────────────────
def membership_v2(refresh: bool = False) -> pd.DataFrame:
    path = CACHE_DIR / "index_constituents_v2.csv"
    if path.exists() and not refresh:
        return pd.read_csv(path, parse_dates=["snapshot_date"], dtype={"isin": "string"})
    d = _read_sql("SELECT snapshot_date, index_name, symbol, isin, company_name "
                  "FROM public.index_constituents_monthly")
    d["snapshot_date"] = pd.to_datetime(d["snapshot_date"])
    d["symbol"] = d["symbol"].str.strip().str.upper()
    d["isin"] = d["isin"].astype("string").str.strip().str.upper()
    d["category"] = d["index_name"].map(INDEX_NAME_TO_CAT)
    d = d.dropna(subset=["category"]).sort_values(["snapshot_date", "index_name", "symbol"])
    d.to_csv(path, index=False)
    return d


# ── Canonical holding id ───────────────────────────────────────────────────
def resolve_holdings(refresh: bool = False) -> pd.DataFrame:
    """
    Every (parent, eff_date, row) in the window, with a canonical `key` for
    the security: its ISIN where the parent file has one, else the ticker.
    Blank tickers are filled from ISIN via the ticker the DB used on that
    date.
    """
    spans = isin_ticker_spans(refresh=refresh)
    rows = []
    for parent in PAIRS.values():
        h = window_baskets(parent_history(parent))
        rows.append(h.assign(parent=parent))
    h = pd.concat(rows, ignore_index=True)

    def ticker_on(isin: str, when: pd.Timestamp) -> str:
        s = spans[spans["isin"] == isin]
        if s.empty:
            return ""
        live = s[(s["first"] <= when) & (s["last"] >= when)]
        return str((live if len(live) else s).iloc[-1]["ticker"])

    blank = h["ticker"] == ""
    h.loc[blank, "ticker"] = [ticker_on(i, e) for i, e in zip(h.loc[blank, "isin"],
                                                               h.loc[blank, "eff_date"])]
    h["ticker_filled_from_isin"] = blank
    h["key"] = np.where(h["isin"] != "", h["isin"], h["ticker"])
    return h


# ── Prices, spliced across renames ─────────────────────────────────────────
def _fetch_ohlcv(tickers: list[str]) -> pd.DataFrame:
    frames = []
    for i in range(0, len(tickers), CHUNK):
        frames.append(_read_sql(
            "SELECT date, ticker, open, high, low, close FROM merged_historical_data_with_rics "
            "WHERE ticker = ANY(:t) AND date >= :s AND date <= :e",
            {"t": tickers[i:i + CHUNK], "s": PRICE_START, "e": PRICE_END}))
        print(f"  fetched {min(i + CHUNK, len(tickers)):>4}/{len(tickers)} tickers", flush=True)
    d = pd.concat(frames, ignore_index=True)
    d["date"] = pd.to_datetime(d["date"])
    d["ticker"] = d["ticker"].str.strip().str.upper()
    for c in ("open", "high", "low", "close"):
        d[c] = pd.to_numeric(d[c], errors="coerce")
    return d.drop_duplicates(subset=["date", "ticker"]).sort_values(["ticker", "date"])


def symbology_aliases(isins: list[str], refresh: bool = False) -> pd.DataFrame:
    """
    Every ticker `symbology_changes` links to each ISIN, old and new.

    Needed because `mcap_based_universe` back-fills a renamed stock's *new*
    ticker onto its whole history, so its spans cannot find the old ticker's
    prices. Example: Cemindia Projects (INE686A01026) is `CEMPRO` there from
    2019, but its prices before 2023-11-28 are under `ITDCEM` (ITD Cementation).
    """
    path = CACHE_DIR / "symbology_aliases_v2.csv"
    if path.exists() and not refresh:
        d = pd.read_csv(path, dtype=str).fillna("")
        if set(isins) <= set(d["isin"]):
            return d
    d = _read_sql(
        "SELECT DISTINCT isin, new_isin, ticker, new_ticker FROM symbology_changes "
        "WHERE isin = ANY(:i) OR new_isin = ANY(:i)", {"i": list(isins)})
    rows = []
    for _, r in d.iterrows():
        for isin in {r["isin"], r["new_isin"]} & set(isins):
            for t in (r["ticker"], r["new_ticker"]):
                if isinstance(t, str) and t.strip():
                    rows.append({"isin": isin, "ticker": t.strip().upper()})
    out = pd.DataFrame(rows, columns=["isin", "ticker"]).drop_duplicates()
    # Record ISINs with no aliases too, so the cache check does not refetch.
    missing = sorted(set(isins) - set(out["isin"]))
    out = pd.concat([out, pd.DataFrame({"isin": missing, "ticker": ""})], ignore_index=True)
    out.to_csv(path, index=False)
    return out


def keyed_ohlcv(holdings: pd.DataFrame, refresh: bool = False) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Daily OHLC per canonical key, plus a coverage report.

    For each key, fetch every ticker the ISIN ever carried: its tickers in the
    market-cap table, its aliases in `symbology_changes`, and the parent file's
    own ticker. Then on each date take the row of the ticker the market-cap
    table says was live that day. Where no span covers the date, fall back to
    any ticker with a bar, preferring the parent file's ticker.
    """
    path = CACHE_DIR / "universe_ohlcv_v2.parquet"
    spans = isin_ticker_spans()
    keys = holdings.drop_duplicates("key")[["key", "isin", "ticker", "name"]]
    alias = symbology_aliases(sorted(i for i in keys["isin"] if i), refresh=refresh)

    want: dict[str, list[str]] = {}
    for k, isin, tkr in zip(keys["key"], keys["isin"], keys["ticker"]):
        cands = list(spans.loc[spans["isin"] == isin, "ticker"]) if isin else []
        if isin:
            cands += [t for t in alias.loc[alias["isin"] == isin, "ticker"] if t and t not in cands]
        if tkr and tkr not in cands:
            cands.append(tkr)
        want[k] = cands
    all_t = sorted({t for v in want.values() for t in v if t})

    # The sidecar lists every ticker requested, so a ticker the DB has no rows
    # for does not force a re-fetch on every run.
    asked = path.with_suffix(".requested.txt")
    raw = None
    if path.exists() and asked.exists() and not refresh:
        if set(all_t) <= set(asked.read_text().split()):
            raw = pd.read_parquet(path)
    if raw is None:
        raw = _fetch_ohlcv(all_t)
        raw.to_parquet(path, index=False)
        asked.write_text("\n".join(all_t))

    by_t = {t: g.set_index("date") for t, g in raw.groupby("ticker")}
    out, cov = [], []
    for k, isin, tkr, name in keys.itertuples(index=False):
        cands = [t for t in want[k] if t in by_t]
        if not cands:
            cov.append({"key": k, "isin": isin, "parent_ticker": tkr, "name": name,
                        "tickers_tried": "|".join(want[k]), "tickers_priced": "",
                        "rows": 0, "status": "unpriced"})
            continue
        frame = pd.concat({t: by_t[t][["open", "high", "low", "close"]] for t in cands},
                          names=["src", "date"]).reset_index()
        sp = spans[spans["isin"] == isin] if isin else spans.iloc[0:0]

        def live_rank(row) -> int:
            s = sp[(sp["ticker"] == row["src"]) & (sp["first"] <= row["date"])
                   & (sp["last"] + pd.Timedelta(days=35) >= row["date"])]
            if len(s):
                return 0
            return 1 if row["src"] == tkr else 2

        frame["pref"] = frame.apply(live_rank, axis=1)
        frame = frame.sort_values(["date", "pref"]).drop_duplicates("date", keep="first")
        used = sorted(frame["src"].unique())
        frame["key"] = k
        out.append(frame[["date", "key", "open", "high", "low", "close", "src"]])
        cov.append({"key": k, "isin": isin, "parent_ticker": tkr, "name": name,
                    "tickers_tried": "|".join(want[k]), "tickers_priced": "|".join(used),
                    "rows": int(len(frame)),
                    "first": frame["date"].min().date(), "last": frame["date"].max().date(),
                    "status": "renamed" if len(used) > 1 or (tkr and used != [tkr]) else "ok"})
    px = pd.concat(out, ignore_index=True).rename(columns={"key": "ticker"})
    return px, pd.DataFrame(cov)


def quote_ids(isins: list[str], refresh: bool = False) -> pd.DataFrame:
    """
    ISIN -> every `quote_id` `symbology_changes` links to it. A quote_id is the
    DB's permanent instrument key: it survives ticker and RIC changes and
    delisting/relisting, which a ticker does not.
    """
    path = CACHE_DIR / "isin_quote_id_v2.csv"
    if path.exists() and not refresh:
        d = pd.read_csv(path, dtype={"isin": str})
        if set(isins) <= set(d["isin"]):
            return d
    q = _read_sql("SELECT DISTINCT quote_id, isin, new_isin FROM symbology_changes "
                  "WHERE isin = ANY(:i) OR new_isin = ANY(:i)", {"i": list(isins)})
    pairs = {(i, int(r["quote_id"])) for _, r in q.iterrows()
             for i in {r["isin"], r["new_isin"]} & set(isins)}
    d = pd.DataFrame(sorted(pairs), columns=["isin", "quote_id"])
    d.to_csv(path, index=False)
    return d


def eikon_ohlcv(holdings: pd.DataFrame, refresh: bool = False) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Daily OHLC per canonical key from `ohlcv_eikon`, joined on quote_id.

    `merged_historical_data_with_rics` is Kite data. It does not carry a stock
    across a ticker change or a delist/relist, and it is not adjusted for
    demergers or special dividends: Siemens −25% on 2025-04-07, NIIT −44% on
    2023-06-08, Aster DM −22% on 2024-04-23. It also has no rows at all for
    EQUITAS or SHRIRAMCIT, and none for Kirloskar Ferrous before 2026-04-20.
    `ohlcv_eikon` handles all of these. It is split, bonus and demerger
    adjusted, but not adjusted for ordinary dividends: the per-stock median
    Eikon−Kite drift is +0.006 pp/yr. So it is a price-return series, on the
    same basis as the Nifty price indices.
    """
    path = CACHE_DIR / "eikon_ohlcv_v2.parquet"
    keys = holdings.drop_duplicates("key")[["key", "isin", "ticker", "name"]]
    isins = sorted(i for i in keys["isin"] if i)
    qm = quote_ids(isins, refresh=refresh)
    if path.exists() and not refresh:
        ek = pd.read_parquet(path)
    else:
        ek = _read_sql(
            "SELECT quote_id, ric, date, open, high, low, close FROM ohlcv_eikon "
            "WHERE quote_id = ANY(:q) AND date >= :s AND date <= :e",
            {"q": [int(x) for x in qm["quote_id"].unique()], "s": PRICE_START, "e": PRICE_END})
        ek["date"] = pd.to_datetime(ek["date"])
        for c in ("open", "high", "low", "close"):
            ek[c] = pd.to_numeric(ek[c], errors="coerce").astype(float)
        ek.to_parquet(path, index=False)
    ek = ek.merge(qm, on="quote_id")
    # One row per (isin, date); no ISIN in this window has two live quote_ids.
    ek = ek.sort_values(["isin", "date", "quote_id"]).drop_duplicates(["isin", "date"])
    px = ek.rename(columns={"isin": "ticker"})
    px["src"] = px["ric"]
    px = px[["date", "ticker", "open", "high", "low", "close", "src"]]
    cov = []
    for k, isin, tkr, name in keys.itertuples(index=False):
        p = px[px["ticker"] == k]
        cov.append({"key": k, "isin": isin, "parent_ticker": tkr, "name": name,
                    "quote_ids": "|".join(map(str, qm.loc[qm["isin"] == isin, "quote_id"])),
                    "rics": "|".join(sorted(p["src"].dropna().unique())), "rows": int(len(p)),
                    "first": p["date"].min().date() if len(p) else None,
                    "last": p["date"].max().date() if len(p) else None,
                    "status": "ok" if len(p) else "unpriced"})
    return px.reset_index(drop=True), pd.DataFrame(cov)


PRICE_SOURCE = "eikon"


def load_prices(source: str = PRICE_SOURCE) -> pd.DataFrame:
    """The long price panel the v2 study runs on: `eikon` (primary) or `kite`."""
    name = {"eikon": "keyed_ohlcv_eikon_v2.parquet", "kite": "keyed_ohlcv_v2.parquet"}[source]
    return pd.read_parquet(CACHE_DIR / name)


def load_overrides() -> pd.DataFrame:
    if not OVERRIDES_CSV.exists():
        return pd.DataFrame(columns=["ticker", "isin", "bucket", "reason", "decided_by", "date"])
    return pd.read_csv(OVERRIDES_CSV, dtype=str).fillna("")


if __name__ == "__main__":
    print("mcap raw:", len(raw_mcap_isin(refresh=True)))
    print("monthly ranks:", len(monthly_ranks_v2(refresh=True)))
    print("semiannual ranks:", len(semiannual_ranks_v2(refresh=True)))
    print("membership:", len(membership_v2(refresh=True)))
