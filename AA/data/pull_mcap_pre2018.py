"""Extend the market-cap tag source back to 2013-12 (Manu asked 2026-11-17: tags from January 2014). CANDIDATE only.

    python -I data/pull_mcap_pre2018.py --check    # reads the DB (read-only) and D20/D23, prints the checks, writes nothing
    python -I data/pull_mcap_pre2018.py            # writes Historical Data/extended_<today>/mcap_universe_from_2013-12/

What it does
    1. Pulls public.mcap_based_universe, instrument_class = 'ordinary', START <= date < 2018-01-01: the rows D20 left out
       (D20 = data/pull_tag_sources.py with date >= 2018-01-01). Same query shape, same column order, same CSV writing.
    2. Overlap check: re-pulls the D20 window (2018-01-01 .. D20's last date) and requires it to be byte-identical to the
       approved D20 file (same sha256). If the DB has changed, it prints how and STOPS without writing.
    3. Ranks the new rows with data/build_tag_panels.build_rank_panel (the D23 code, imported, not copied).
    4. Writes the combined rank panel = new rows, then D23's rows copied verbatim, so analysis/tag_lookup.py can read it in
       place of D23's mcap_rank_panel.csv. Ranking is per snapshot date, so the D23 rows are exactly what D23 already holds.
    5. Checks on the new rows only (APPROVED_DATA.md procedure step 2): snapshots per month, shares per snapshot, nulls,
       duplicates, mcap <= 0, total-mcap moves between snapshots, top-100 turnover, and the join at 2017-12 -> 2018-01.
Rules: read-only session; approved files are never edited; refuses to overwrite an existing folder; no credentials or host
in the manifest. The output is off-limits until Manu says "approved" and APPROVED_DATA.md is updated.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_tag_panels as btp  # noqa: E402  (ranking code of D23)
import pull_tag_sources as pts  # noqa: E402  (connect, fetch, iso of D20)

AA = Path(__file__).resolve().parents[1]
HD = AA / "Historical Data"
START = "2013-12-01"   # so a date in early January 2014 has a snapshot (2013-12-31) on or before it
END_EXCL = "2018-01-01"
D20 = HD / "extended_2026-11-12" / "mcap_universe" / "mcap_universe_ordinary.csv"
D23_RANK = HD / "extended_2026-11-12" / "tags" / "mcap_rank_panel.csv"
D20_SHA = "f0288a5b09a604ecebb148bae50c5baeaa743f7924adc8adc688c4718b7683ba"
D23_RANK_SHA = "e7c98ec5e0cc144c2986530f156b8a561f5c2df92d3ccc11a0ddce335f90cbf0"
D20_LAST = "2026-11-11"
SORT = ["date", "isin", "ticker", "quote_id", "mcap"]   # D20's sort order

Q_NEW = ("SELECT * FROM public.mcap_based_universe WHERE date >= %(start)s AND date < %(end)s "
         "AND instrument_class = 'ordinary'")
Q_OVERLAP = ("SELECT * FROM public.mcap_based_universe WHERE date >= '2018-01-01' AND date <= %(last)s "
             "AND instrument_class = 'ordinary'")
Q_CLASSES = ("SELECT instrument_class, COUNT(*) AS n, MIN(date) AS first, MAX(date) AS last FROM public.mcap_based_universe "
             "WHERE date >= %(start)s AND date < %(end)s GROUP BY instrument_class ORDER BY n DESC")


def csv_bytes(df: pd.DataFrame) -> bytes:
    """Exactly how pull_tag_sources writes a file: D20 sort order, ISO dates, utf-8, \\n."""
    df = pts.iso(df.sort_values([c for c in SORT if c in df.columns], kind="mergesort", na_position="last")
                 .reset_index(drop=True))
    buf = io.StringIO()
    df.to_csv(buf, index=False, lineterminator="\n")
    return buf.getvalue().encode("utf-8")


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def overlap_diff(db_bytes: bytes) -> list[str]:
    """Explain how the DB's D20 window differs from the approved D20 file."""
    rd = lambda src: pd.read_csv(src, dtype=str, keep_default_na=False)
    a, b = rd(D20), rd(io.BytesIO(db_bytes))
    L = [f"  D20 file rows {len(a):,}, DB rows {len(b):,}; columns equal: {list(a.columns) == list(b.columns)}"]
    key = ["date", "quote_id"]
    m = a.merge(b, on=key, how="outer", suffixes=("_f", "_db"), indicator=True)
    L.append(f"  only in D20: {int((m['_merge'] == 'left_only').sum()):,}; only in DB: {int((m['_merge'] == 'right_only').sum()):,}")
    both = m[m["_merge"] == "both"]
    for c in [c for c in a.columns if c not in key and c in b.columns]:
        n = int((both[f"{c}_f"] != both[f"{c}_db"]).sum())
        if n:
            L.append(f"  column {c}: {n:,} rows differ")
    return L


def checks(raw: pd.DataFrame, rp_new: pd.DataFrame, d23: pd.DataFrame) -> list[str]:
    L: list[str] = []
    d = pd.to_datetime(raw["date"])
    L.append(f"new rows: {len(raw):,}, {d.nunique()} snapshot dates, {d.min().date()} -> {d.max().date()}")
    months = d.dt.to_period("M")
    per_m = d.groupby(months).nunique()
    L.append(f"  months covered {per_m.size}; months with != 1 snapshot: {int((per_m != 1).sum())}")
    full = pd.period_range(months.min(), months.max(), freq="M")
    L.append(f"  missing months: {[str(x) for x in full.difference(per_m.index)] or 'none'}")
    off = sorted({str(x.date()) for x in d.unique() if (pd.Timestamp(x) + pd.offsets.BMonthEnd(0)) != pd.Timestamp(x)})
    L.append(f"  snapshots not on the last business day of the month: {off or 'none'}")
    n = raw.groupby("date").size()
    L.append(f"  shares per snapshot: min {int(n.min()):,}, median {int(n.median()):,}, max {int(n.max()):,}")
    for c in ("isin", "ticker", "mcap", "quote_id"):
        L.append(f"  empty {c}: {int(raw[c].isna().sum() + (raw[c].astype(str) == '').sum()):,}")
    L.append(f"  duplicate (date, quote_id): {int(raw.duplicated(['date', 'quote_id']).sum())}; "
             f"duplicate (date, isin) among non-null isin: {int(raw[raw['isin'].notna()].duplicated(['date', 'isin']).sum())}")
    L.append(f"  mcap <= 0: {int((pd.to_numeric(raw['mcap']) <= 0).sum())}")
    if "updated_at" in raw.columns:
        u = pd.to_datetime(raw["updated_at"], utc=True, errors="coerce")
        L.append(f"  updated_at (when the rows were written): {u.min()} -> {u.max()}; by day: "
                 + ", ".join(f"{k}: {v:,}" for k, v in u.dt.date.value_counts().sort_index().items()))

    # snapshot-to-snapshot stability, across the join with D23
    both = pd.concat([rp_new, d23[d23["date"] <= "2018-06-30"]], ignore_index=True)
    both["mcap"] = pd.to_numeric(both["mcap"])
    dates = sorted(both["date"].unique())
    tot = both.groupby("date")["mcap"].sum()
    top = {dt: set(both[(both["date"] == dt) & (both["rank"].astype(int) <= 100)]["quote_id"].astype(str)) for dt in dates}
    mid = {dt: set(both[(both["date"] == dt) & (both["rank"].astype(int) <= 250)]["quote_id"].astype(str)) for dt in dates}
    L.append("snapshot to snapshot (new rows, then the first D23 snapshots; * = the join 2017-12 -> 2018-01):")
    L.append("  date        shares  total mcap (lakh cr)  change   top-100 changed  top-250 changed")
    for i, dt in enumerate(dates):
        if i == 0:
            L.append(f"  {dt}  {int((both['date'] == dt).sum()):>6,}  {tot[dt] / 1e12:>10.2f}")
            continue
        p = dates[i - 1]
        flag = "*" if p < "2018-01-01" <= dt else " "
        L.append(f" {flag}{dt}  {int((both['date'] == dt).sum()):>6,}  {tot[dt] / 1e12:>10.2f}  {tot[dt] / tot[p] - 1:>+9.1%}"
                 f"  {len(top[dt] - top[p]):>15}  {len(mid[dt] - mid[p]):>15}")
    return L


def main(check_only: bool) -> int:
    assert sha(D20.read_bytes()) == D20_SHA, "D20 file is not the approved one"
    d23_bytes = D23_RANK.read_bytes()
    assert sha(d23_bytes) == D23_RANK_SHA, "D23 rank panel is not the approved one"

    conn = pts.connect()   # read-only session
    cur = conn.cursor()
    classes = pts.fetch(cur, Q_CLASSES, {"start": START, "end": END_EXCL})
    raw = pts.fetch(cur, Q_NEW, {"start": START, "end": END_EXCL})
    ov = pts.fetch(cur, Q_OVERLAP, {"last": D20_LAST})
    conn.close()

    print(f"== instrument_class, {START} <= date < {END_EXCL} (all classes; only 'ordinary' is kept) ==")
    for _, r in classes.iterrows():
        print(f"  {str(r.instrument_class):10s} {int(r.n):>8,}  {r['first']} -> {r['last']}")

    ov_bytes = csv_bytes(ov)
    ok = sha(ov_bytes) == D20_SHA
    print(f"\n== overlap: DB 2018-01-01 .. {D20_LAST} vs approved D20 ==\n  byte-identical: {ok}")
    if not ok:
        for ln in overlap_diff(ov_bytes):
            print(ln)
        sys.exit("STOP: the DB no longer matches the approved D20 rows. Nothing written; ask Manu.")

    new_bytes = csv_bytes(raw)
    raw_csv = pd.read_csv(io.BytesIO(new_bytes), dtype={"isin": str, "ticker": str, "ric": str}, keep_default_na=False,
                          na_values=[""], parse_dates=["date"], low_memory=False)   # read back exactly as D23 reads D20
    rp_new = btp.build_rank_panel(raw_csv)
    buf = io.StringIO()
    rp_new.to_csv(buf, index=False, encoding="utf-8", lineterminator="\n")
    rp_new_bytes = buf.getvalue().encode("utf-8")
    hdr, _, d23_body = d23_bytes.partition(b"\n")
    new_hdr, _, new_body = rp_new_bytes.partition(b"\n")
    assert hdr == new_hdr, "rank panel header differs from D23"
    combined = rp_new_bytes + d23_body
    assert combined.endswith(d23_body) and combined[len(rp_new_bytes):] == d23_body

    d23 = pd.read_csv(io.BytesIO(d23_bytes), dtype={"isin": str, "ticker": str, "date": str}, keep_default_na=False,
                      na_values=[""])
    rp_new_s = pd.read_csv(io.BytesIO(rp_new_bytes), dtype={"isin": str, "ticker": str, "date": str},
                           keep_default_na=False, na_values=[""])
    print()
    for ln in checks(raw_csv, rp_new_s, d23):
        print(ln)
    print(f"\nrank panel, new rows: {len(rp_new):,} ({len(raw_csv) - len(rp_new)} unranked, null mcap); "
          f"bands {rp_new['band'].value_counts().to_dict()}")
    print(f"combined rank panel: {len(rp_new) + len(d23):,} rows = {len(rp_new):,} new + {len(d23):,} D23 verbatim")

    if check_only:
        print("\ncheck only: nothing written.")
        return 0

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out = HD / f"extended_{today}" / "mcap_universe_from_2013-12"
    if out.exists():
        sys.exit(f"STOP: {out} already exists. Candidates are never overwritten; ask Manu.")
    out.mkdir(parents=True)
    files = {
        "mcap_universe_ordinary_2013-12_2017-12.csv": new_bytes,
        "mcap_rank_panel_2013-12_2017-12.csv": rp_new_bytes,
        "mcap_rank_panel_from_2013-12.csv": combined,
    }
    man = {"retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "source": "postgres windmill, read-only session", "script": "data/pull_mcap_pre2018.py",
           "script_sha256": sha(Path(__file__).read_bytes()),
           "query": Q_NEW + f" -- params: start={START}, end={END_EXCL}",
           "overlap_check": f"DB rows 2018-01-01..{D20_LAST} byte-identical to D20 (sha256 {D20_SHA})",
           "inputs": {"D20 mcap_universe_ordinary.csv": D20_SHA, "D23 mcap_rank_panel.csv": D23_RANK_SHA},
           "status": "CANDIDATE (PENDING): off-limits until Manu approves it and APPROVED_DATA.md is updated",
           "files": {}}
    for name, b in files.items():
        p = out / name
        p.write_bytes(b)
        man["files"][name] = {"rows": b.count(b"\n") - 1, "sha256": sha(b)}
        print(f"wrote {p.relative_to(AA)}  rows {man['files'][name]['rows']:,}  sha256 {man['files'][name]['sha256'][:16]}")
    man["files"]["mcap_rank_panel_from_2013-12.csv"]["note"] = (
        "rows 2013-12-31..2017-12-29 ranked here by build_tag_panels.build_rank_panel; rows from 2018-01-31 are D23's "
        "mcap_rank_panel.csv copied byte for byte. Read it with analysis/tag_lookup.py in place of D23's rank panel.")
    (out / "manifest.json").write_text(json.dumps(man, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="read the DB and print the checks; write nothing")
    sys.exit(main(ap.parse_args().check))
