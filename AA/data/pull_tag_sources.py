"""Pull the three tag-source tables from Postgres as CANDIDATE files (T07 plan, step 0A).

    python -I data/pull_tag_sources.py --check    # reads the DB (read-only), prints the summary, writes nothing
    python -I data/pull_tag_sources.py            # writes Historical Data/extended_<today>/{mcap_universe,membership,symbology}/

Tables (read-only session, creds PG_PRICE_* in wm-aiReports/.env):
    public.mcap_based_universe          rows with date >= START and instrument_class = 'ordinary' (class counts of ALL rows are
                                        printed, so the filter can be checked); every column the table has for those rows is kept
                                        as stored, duplicates included (de-duplication is a derivation step, not a pull step)
    public.index_constituents_monthly   every row, every column
    public.symbology_changes            every row, every column

Rules (same manner as data/extend_liquid.py, F-AA-D13, and CLAUDE.md "Refreshing the data pool"):
    * the output is a CANDIDATE: off-limits until Manu says "approved" and APPROVED_DATA.md is updated;
    * rows are written as stored, never edited; a run refuses to overwrite an existing folder;
    * deterministic: fixed sort order, ISO dates, so a re-pull of unchanged tables gives byte-identical files;
    * manifest.json records the retrieval time, query text, row counts, first/last date and sha256 per file, and this script's sha256;
      it never records credentials or the host.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import psycopg2

AA = Path(__file__).resolve().parents[1]
HD = AA / "Historical Data"
ENV = AA.parents[1] / "wm-aiReports" / ".env"
START = "2018-01-01"   # runway before the first 2019 event; the rank snapshot on or before a date is needed

Q_MCAP = ("SELECT * FROM public.mcap_based_universe WHERE date >= %(start)s AND instrument_class = 'ordinary'")
Q_MCAP_CLASSES = ("SELECT instrument_class, COUNT(*) AS n, MIN(date) AS first, MAX(date) AS last "
                  "FROM public.mcap_based_universe WHERE date >= %(start)s GROUP BY instrument_class ORDER BY n DESC")
Q_MEMB = "SELECT * FROM public.index_constituents_monthly"
# Symbology: identifiers, rename flags and status only (decided 2026-11-12). Left out on purpose: tt_raw_response (vendor JSON),
# the GICS/TRBC sector columns, tt_sid / fundamentals-segment columns, and ipo_date / listing_date (empty in all 9,231 rows).
SYMB_COLS = ("id, quote_id, instrument_id, ric, ticker, full_name, isin, new_ric, new_ticker, new_full_name, new_isin, "
             "ric_changed_flag, ticker_changed_flag, full_name_changed_flag, isin_changed_flag, "
             "instrument_type, instrument_class, is_active, delist_date, delist_date_source, updated_at")
Q_SYMB = f"SELECT {SYMB_COLS} FROM public.symbology_changes"
Q_COLS = ("SELECT table_name, column_name, data_type FROM information_schema.columns "
          "WHERE table_schema = 'public' AND table_name IN ('mcap_based_universe','index_constituents_monthly','symbology_changes') "
          "ORDER BY table_name, ordinal_position")


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def connect():
    env = {}
    for line in ENV.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.strip().split("=", 1)
            env[k] = v.strip("\"'")
    c = psycopg2.connect(host=env["PG_PRICE_HOST"], port=env["PG_PRICE_PORT"], dbname=env["PG_PRICE_DBNAME"],
                         user=env["PG_PRICE_USER"], password=env["PG_PRICE_PASSWORD"], connect_timeout=20)
    c.set_session(readonly=True)
    return c


def fetch(cur, sql: str, params: dict | None = None) -> pd.DataFrame:
    cur.execute(sql, params or {})
    cols = [d[0] for d in cur.description]
    return pd.DataFrame(cur.fetchall(), columns=cols)


def iso(df: pd.DataFrame) -> pd.DataFrame:
    """Dates as ISO strings; everything else untouched."""
    out = df.copy()
    for c in out.columns:
        if out[c].dtype == object and len(out) and hasattr(out[c].dropna().iloc[0] if out[c].notna().any() else None, "isoformat"):
            out[c] = out[c].map(lambda x: x.isoformat() if x is not None and hasattr(x, "isoformat") else x)
    return out


def summary(cols: pd.DataFrame, classes: pd.DataFrame, mc: pd.DataFrame, mb: pd.DataFrame, sy: pd.DataFrame) -> list[str]:
    L: list[str] = []
    L.append("== columns the tables have ==")
    for t, g in cols.groupby("table_name"):
        L.append(f"  {t}: " + ", ".join(f"{a} ({b})" for a, b in zip(g.column_name, g.data_type)))

    L.append("\n== mcap_based_universe (date >= %s) ==" % START)
    L.append("  instrument_class counts, all rows:")
    for _, r in classes.iterrows():
        L.append(f"    {str(r.instrument_class):22s} {int(r.n):>9,}  {r['first']} -> {r['last']}")
    d = pd.to_datetime(mc["date"])
    L.append(f"  ordinary rows pulled: {len(mc):,}   distinct dates: {d.nunique():,}   {d.min().date()} -> {d.max().date()}")
    per_year = d.groupby(d.dt.year).agg(["size", lambda s: s.nunique()])
    per_year.columns = ["rows", "dates"]
    L.append("  rows / distinct dates per year: " + "; ".join(f"{y}: {int(r.rows):,}/{int(r.dates)}" for y, r in per_year.iterrows()))
    for c in ("ticker", "isin", "mcap"):
        if c in mc.columns:
            L.append(f"  null {c}: {int(mc[c].isna().sum()):,}")
    if {"date", "isin"} <= set(mc.columns):
        L.append(f"  duplicate (date, isin): {int(mc.duplicated(['date', 'isin']).sum()):,}")
    if {"date", "ticker"} <= set(mc.columns):
        L.append(f"  duplicate (date, ticker): {int(mc.duplicated(['date', 'ticker']).sum()):,}")
    n_per = mc.groupby("date").size()
    L.append(f"  ordinary shares per date: min {int(n_per.min()):,}, median {int(n_per.median()):,}, max {int(n_per.max()):,}")
    y26 = d[d.dt.year == d.max().year].drop_duplicates()
    L.append(f"  latest year ({d.max().year}): {len(y26)} snapshot dates, first {y26.min().date()}, last {y26.max().date()}")
    L.append(f"  mcap <= 0: {int((mc['mcap'] <= 0).sum()):,}" if "mcap" in mc.columns else "")

    L.append("\n== index_constituents_monthly ==")
    L.append(f"  rows: {len(mb):,}")
    if "snapshot_date" in mb.columns:
        sd = sorted(pd.to_datetime(mb["snapshot_date"]).dt.date.unique())
        L.append(f"  snapshots: {len(sd)}  {sd[0]} -> {sd[-1]}")
        L.append("  dates: " + ", ".join(str(x) for x in sd))
    if "index_name" in mb.columns:
        L.append("  rows per index_name (all snapshots): " + "; ".join(f"{k}: {v}" for k, v in mb["index_name"].value_counts().items()))
        want = ["NIFTY 100", "NIFTY MIDCAP 150", "NIFTY SMALLCAP 250", "NIFTY MICROCAP 250"]
        for w in want:
            sub = mb[mb["index_name"].str.upper().str.strip() == w]
            per = sub.groupby("snapshot_date").size()
            L.append(f"    {w}: {len(per)} snapshots, members per snapshot min {int(per.min()) if len(per) else 0} max {int(per.max()) if len(per) else 0}")
    if "isin" in mb.columns:
        L.append(f"  null isin: {int(mb['isin'].isna().sum()):,}")

    L.append("\n== symbology_changes ==")
    L.append(f"  rows: {len(sy):,}   columns: {', '.join(sy.columns)}")
    for c in sy.columns:
        L.append(f"  null {c}: {int(sy[c].isna().sum()):,}")
    return [x for x in L if x != ""]


def main(check_only: bool) -> int:
    conn = connect()
    cur = conn.cursor()
    cols = fetch(cur, Q_COLS)
    classes = fetch(cur, Q_MCAP_CLASSES, {"start": START})
    mc = fetch(cur, Q_MCAP, {"start": START})
    mb = fetch(cur, Q_MEMB)
    sy = fetch(cur, Q_SYMB)
    conn.close()

    for ln in summary(cols, classes, mc, mb, sy):
        print(ln)

    if check_only:
        print("\ncheck only: nothing written.")
        return 0

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    root = HD / f"extended_{today}"
    if root.exists():
        sys.exit(f"STOP: {root} already exists. Candidates are never overwritten; ask Manu.")
    spec = {
        "mcap_universe": ("mcap_universe_ordinary.csv", mc, Q_MCAP, ["date", "isin", "ticker", "quote_id", "mcap"]),
        "membership": ("index_constituents_monthly.csv", mb, Q_MEMB, ["snapshot_date", "index_name", "isin", "symbol"]),
        "symbology": ("symbology_changes.csv", sy, Q_SYMB, ["id"]),
    }
    me = Path(__file__).resolve()
    for sub, (fn, df, q, sort_cols) in spec.items():
        d = root / sub
        d.mkdir(parents=True, exist_ok=False)
        sort_cols = [c for c in sort_cols if c in df.columns]
        df = iso(df.sort_values(sort_cols, kind="mergesort", na_position="last").reset_index(drop=True))
        p = d / fn
        df.to_csv(p, index=False, encoding="utf-8", lineterminator="\n")
        datecol = "date" if "date" in df.columns else ("snapshot_date" if "snapshot_date" in df.columns else None)
        man = {
            "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "source": "postgres windmill, read-only session",
            "query": q + ((" -- params: start=" + START) if "%(start)s" in q else ""),
            "script": "data/pull_tag_sources.py", "script_sha256": sha256(me),
            "file": fn, "rows": int(len(df)), "columns": list(df.columns),
            "first": None if datecol is None else str(df[datecol].min()),
            "last": None if datecol is None else str(df[datecol].max()),
            "sha256": sha256(p),
            "status": "CANDIDATE: off-limits until Manu approves it and APPROVED_DATA.md is updated",
        }
        (d / "manifest.json").write_text(json.dumps(man, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {p.relative_to(AA)}  rows {man['rows']:,}  sha256 {man['sha256'][:16]}")
    (root / "SOURCE.md").write_text(
        "# Candidate tag sources (T07 step 0A)\n\nPulled by `data/pull_tag_sources.py` from Postgres (read-only). "
        "Off-limits until Manu approves it. See each `manifest.json` for the query, row counts and sha256.\n",
        encoding="utf-8")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="read the DB and print the summary; write nothing")
    sys.exit(main(ap.parse_args().check))
