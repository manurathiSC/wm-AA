"""One OHLC file for every stock a parent smallcase has ever held.

    python data/build_ohlc_file.py [SCMO_0003 ...]        (default: all four parents)

Input : data/holdings_matrix/<parent>_holdings_matrix.csv   (rows = basket dates, columns = stocks)
        data/holdings_matrix/<parent>_columns.csv           (column -> ISIN, sid)   [build_holdings_matrix.py]
        Postgres windmill.public.ohlcv_eikon  via symbology_changes (read-only; needs wm-aiReports/.env)
        data/missing_rics/*.csv                              (manual Eikon exports for delisted names)
Output: data/holdings_matrix/<parent>_ohlc.csv               long: date, stock, open, high, low, close, src
        data/holdings_matrix/<parent>_ohlc_availability.csv  per stock: sessions needed vs priced
        data/holdings_matrix/<parent>_ohlc_filled_cells.csv  every carried-forward bar

Rules
- OHLC = Eikon, adjusted for splits, bonuses and demergers, not for dividends (price return). Stock labels are the
  holdings matrix's. A stock's quote_ids are found from its ISINs: the ISIN in the columns file plus the ISIN the
  rebalance table carries for the same sid (they differ for TD Power).
- One row per stock per session on which it has a bar. `src` = db (ohlcv_eikon), export (missing_rics file) or
  carried (see below). Where one stock has several quote_ids on a date the lowest quote_id wins; disagreements on
  the close are counted and printed.
- The DB starts on 2014-07-01 and stops 13 ISINs on 2016-06-30 or has no rows for them. The files in missing_rics
  fill those; only files for stocks this parent held are used. Where both exist the DB wins and the overlap is compared.
- Sessions = DB dates from 2014-07-01 on which at least THIN (50%) of the stocks that are alive around that date have
  a close. 'Alive' = has a close on the previous or the next DB date. Thin special sessions (Budget Saturdays, some
  Muhurat evenings) drop out; Sunday sessions where almost everything traded stay.
- A stock is NEEDED on session t if it is in the basket in force on t (a basket takes effect on its own
  availableDate), or t is a switch date and it is in the basket being replaced (it is sold at t).
- A needed stock-session with no bar on a real session gets a flat bar (open = high = low = close = last close, at most
  FILL_LIMIT sessions old; the project's carry-forward convention), src = carried, listed in the filled-cells file.
  Nothing else is ever filled. A bar that exists but lacks an open, high or low is kept as it is and counted as
  `partial` in the availability file.
- Availability = needed stock-sessions with a complete bar (db/export) / needed stock-sessions, reported raw and
  with the carried bars.
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

import pandas as pd

warnings.filterwarnings("ignore")

AA = Path(__file__).resolve().parents[1]
OUT = AA / "data" / "holdings_matrix"
MISS = AA / "data" / "missing_rics"
ENV = AA.parents[1] / "wm-aiReports" / ".env"
THIN = 0.5
FILL_LIMIT = 5
FIELDS = ["open", "high", "low", "close"]
PARENTS = ["SCMO_0003", "SCMO_0007", "SCMO_0010", "SCMO_0029"]
# manual exports -> the ISIN they belong to (RIC suffix = delisting month)
FILE_ISIN = {
    "DISH_NS_F18": "INE353G01020", "GEOM_NS_K22": "INE797A01021", "JMCP_NS_A23": "INE890A01024",
    "LVLS_NS_L20": "INE694C01018", "MEGH_NS": "INE974H01013", "OSCM_NS_D19": "INE00R701017",
    "HEXT_NS_K20": "INE093A01041", "DWNH_NS_I21": "INE202B01038", "PIRA_NS_I25": "INE140A01024",
}


def connect():
    import psycopg2
    env = {}
    for line in ENV.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.strip().split("=", 1)
            env[k] = v.strip("\"'")
    c = psycopg2.connect(host=env["PG_PRICE_HOST"], port=env["PG_PRICE_PORT"], dbname=env["PG_PRICE_DBNAME"],
                         user=env["PG_PRICE_USER"], password=env["PG_PRICE_PASSWORD"], connect_timeout=20)
    c.set_session(readonly=True)
    return c


def build(parent: str, conn) -> None:
    print(f"\n===== {parent} =====")
    mat = pd.read_csv(OUT / f"{parent}_holdings_matrix.csv", parse_dates=["rebalance_date"]).set_index("rebalance_date")
    cols = pd.read_csv(OUT / f"{parent}_columns.csv")
    assert list(cols["stock"]) == list(mat.columns)

    rb = pd.read_sql("select distinct sid, isin from smallcase_rebal_historical where scid=%(s)s",
                     conn, params={"s": parent})
    isins = pd.concat([cols[["stock", "ISIN"]].rename(columns={"ISIN": "isin"}),
                       cols[["stock", "sid"]].merge(rb, on="sid")[["stock", "isin"]]]).drop_duplicates()
    isin2stock = {}
    for s, i in zip(isins["stock"], isins["isin"]):
        assert isin2stock.setdefault(i, s) == s, f"ISIN {i} maps to two stocks"
    qm = pd.read_sql("select distinct quote_id, isin, new_isin from symbology_changes "
                     "where isin = any(%(i)s) or new_isin = any(%(i)s)", conn, params={"i": list(isin2stock)})
    pairs = {(isin2stock[i], int(r.quote_id)) for r in qm.itertuples() for i in {r.isin, r.new_isin} & set(isin2stock)}
    q2s = pd.DataFrame(sorted(pairs), columns=["stock", "quote_id"])
    print(f"{len(cols)} stocks, {q2s['quote_id'].nunique()} quote_ids, "
          f"stocks without a quote_id: {sorted(set(cols['stock']) - set(q2s['stock']))}")

    q = [int(x) for x in q2s["quote_id"].unique()]
    db = pd.concat([pd.read_sql("select quote_id, date, open, high, low, close from ohlcv_eikon "
                                "where quote_id = any(%(q)s)", conn, params={"q": q[i:i + 150]})
                    for i in range(0, len(q), 150)], ignore_index=True)
    db["date"] = pd.to_datetime(db["date"])
    for f in FIELDS:
        db[f] = pd.to_numeric(db[f], errors="coerce").astype(float)
    db = db.merge(q2s, on="quote_id")
    g = db.groupby(["stock", "date"])["close"].agg(["count", "min", "max"])
    g = g[g["count"] > 1]
    print(f"stock-dates with >1 quote_id: {len(g)}; closes differ by >1e-6 relative on {int(((g['max'] / g['min'] - 1) > 1e-6).sum())}")
    db = db.sort_values(["stock", "date", "quote_id"]).drop_duplicates(["stock", "date"])
    bars = {f: db.pivot(index="date", columns="stock", values=f) for f in FIELDS}
    src = pd.DataFrame("db", index=bars["close"].index, columns=bars["close"].columns)

    for name, isin in FILE_ISIN.items():
        if isin not in isin2stock:
            print(f"  {name:12s} skipped: {isin} was never held by {parent}")
            continue
        stock = isin2stock[isin]
        x = pd.read_csv(MISS / f"{name}.csv", parse_dates=["Date"]).set_index("Date")
        x.columns = [c.lower() for c in x.columns]
        have = bars["close"][stock].dropna() if stock in bars["close"] else pd.Series(dtype=float)
        ov = x.index.intersection(have.index)
        rel = max((bars[f].loc[ov, stock] / x.loc[ov, f] - 1).abs().max() for f in FIELDS) if len(ov) else float("nan")
        print(f"  {name:12s} -> {stock:14s} file {x.index.min().date()}..{x.index.max().date()}  overlap {len(ov):4d} "
              f"max rel diff (OHLC) {rel:.1e}  rows added {len(x.index.difference(have.index))}")
        ix = bars["close"].index.union(x.index)
        src = src.reindex(ix)
        for f in FIELDS:
            bars[f] = bars[f].reindex(ix)
            if stock not in bars[f]:
                bars[f][stock] = float("nan")
        if stock not in src:
            src[stock] = None
        newrows = x.index.difference(have.index)
        for f in FIELDS:
            bars[f].loc[newrows, stock] = x.loc[newrows, f]
        src.loc[newrows, stock] = "export"
    close = bars["close"].sort_index()

    alive = close.notna().shift(1, fill_value=False) | close.notna().shift(-1, fill_value=False) | close.notna()
    share = close.notna().sum(axis=1) / alive.sum(axis=1)
    cal = close.loc["2014-07-01":].index
    thin = share.loc[cal][share.loc[cal] < THIN]
    sessions = cal.difference(thin.index)
    print(f"sessions {sessions.min().date()} -> {sessions.max().date()}: {len(sessions)}; thin dates dropped: "
          f"{[d.date().isoformat() for d in thin.index]} (share traded {[round(x, 2) for x in thin]})")

    P = {f: bars[f].reindex(index=sessions, columns=list(mat.columns)) for f in FIELDS}
    S = src.reindex(index=sessions, columns=list(mat.columns))
    complete = P["open"].notna() & P["high"].notna() & P["low"].notna() & P["close"].notna()
    has = P["close"].notna()

    bdates = list(mat.index)
    need = pd.DataFrame(False, index=sessions, columns=mat.columns)
    for k, d0 in enumerate(bdates):
        d1 = bdates[k + 1] if k + 1 < len(bdates) else sessions.max() + pd.Timedelta(days=1)
        need.loc[(sessions >= d0) & (sessions < d1), mat.columns[mat.loc[d0] == 1]] = True
        if k > 0 and (sessions == d0).any():
            need.loc[d0, mat.columns[mat.loc[bdates[k - 1]] == 1]] = True

    last = P["close"].ffill(limit=FILL_LIMIT)
    fill = need & ~has & last.notna()
    for f in FIELDS:
        P[f] = P[f].where(~fill, last)
    S = S.where(~fill, "carried")

    long = pd.DataFrame({f: P[f].stack().dropna() if f == "close" else P[f].stack() for f in FIELDS})
    long = long[long["close"].notna()]
    long["src"] = S.stack().reindex(long.index)
    long = long.reset_index()
    long.columns = ["date", "stock"] + FIELDS + ["src"]
    stock_order = {s: i for i, s in enumerate(mat.columns)}
    long = long.sort_values(["stock", "date"], key=lambda c: c.map(stock_order) if c.name == "stock" else c)
    long.round(6).to_csv(OUT / f"{parent}_ohlc.csv", index=False, date_format="%Y-%m-%d")
    fc = long[long["src"] == "carried"][["date", "stock", "close"]].rename(columns={"close": "carried_close"})
    fc.to_csv(OUT / f"{parent}_ohlc_filled_cells.csv", index=False, date_format="%Y-%m-%d")

    rows = []
    for s_ in mat.columns:
        n = need[s_]
        full = int((complete[s_] & n).sum())
        part = int((has[s_] & ~complete[s_] & n).sum())
        car = int((fill[s_]).sum())
        rows.append({"stock": s_, "needed_sessions": int(n.sum()), "complete_bars": full, "partial_bars": part,
                     "carried": car, "missing": int(n.sum()) - full - part - car,
                     "first_bar": P["close"][s_].first_valid_index(), "last_bar": P["close"][s_].last_valid_index()})
    av = pd.DataFrame(rows)
    av.to_csv(OUT / f"{parent}_ohlc_availability.csv", index=False, date_format="%Y-%m-%d")
    tot = int(av["needed_sessions"].sum())
    raw = int(av["complete_bars"].sum())
    allv = tot - int(av["missing"].sum()) - int(av["partial_bars"].sum())
    print(f"AVAILABILITY complete OHLC bars {raw}/{tot} = {raw / tot:.4%}; partial bars {int(av['partial_bars'].sum())}; "
          f"carried {int(av['carried'].sum())}; with carried {allv}/{tot} = {allv / tot:.4%}; missing {int(av['missing'].sum())}")
    print(f"baskets effective before the first session: {[d.date().isoformat() for d in mat.index[mat.index < sessions.min()]]}")
    print(f"last bar in file {P['close'].index.max().date()}; last basket date {mat.index.max().date()}; "
          f"rows {len(long)}; stocks {long['stock'].nunique()}")
    bad = av[(av["missing"] > 0) | (av["partial_bars"] > 0)]
    if len(bad):
        print(bad.to_string())
    print("carried:", fc.to_dict("records"))


def main(parents: list[str]) -> None:
    conn = connect()
    for p in parents:
        build(p, conn)


if __name__ == "__main__":
    main(sys.argv[1:] or PARENTS)
