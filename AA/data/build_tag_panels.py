"""Build the two rule-independent tag panels (D23) from the PENDING candidates D20 and D21 (T07 plan, step 0B).

    python -I data/build_tag_panels.py --check    # builds in memory, prints the summary, writes nothing
    python -I data/build_tag_panels.py            # writes Historical Data/extended_2026-11-12/tags/{mcap_rank_panel,membership_panel}.csv

Reads ONLY the three candidate files in Historical Data/extended_2026-11-12/ (read exception for steps 0B-0D, Manu 2026-11-12; see
data/APPROVED_DATA.md change log). Writes a candidate (PENDING) and never edits its inputs.

Rank panel  (one row per ranked ordinary share per snapshot date, no rule, parent, event or signal in it):
    rank   = position when the date's shares are sorted by mcap descending, ties by quote_id ascending (1 = largest)
    band   = Large (rank 1-100), Mid (101-250), Small and below (above 250)
    Rows with a null mcap are not ranked. Rows with a null isin or ticker ARE ranked (they hold a rank position).
Membership panel (one row per member per membership snapshot):
    band   = Large (NIFTY 100), Mid (NIFTY MIDCAP 150), Small and below (NIFTY SMALLCAP 250, NIFTY MICROCAP 250)
Files are read with only the empty string as null: pandas' default also turns real values such as "NA" into null.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

AA = Path(__file__).resolve().parents[1]
SRC = AA / "Historical Data" / "extended_2026-11-12"
OUT = SRC / "tags"
MCAP = SRC / "mcap_universe" / "mcap_universe_ordinary.csv"
MEMB = SRC / "membership" / "index_constituents_monthly.csv"
# Empty cells in the candidate CSV. The database holds, for the same rows, isin 536 NULL + 3 empty strings, ticker 410 NULL + 16 empty
# strings, mcap 45 NULL + 2 numeric NaN (counted in SQL 2026-11-12); the CSV writes all of them as an empty cell. All mean "no value".
EXPECT_NULLS = {"isin": 539, "ticker": 426, "mcap": 47}
EXPECT_ROWS = {"mcap": 788_112, "memb": 6_001}
INDEX_BAND = {"NIFTY 100": "Large", "NIFTY MIDCAP 150": "Mid",
              "NIFTY SMALLCAP 250": "Small and below", "NIFTY MICROCAP 250": "Small and below"}
LARGE_MAX, MID_MAX = 100, 250


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def read_mcap() -> pd.DataFrame:
    d = pd.read_csv(MCAP, dtype={"isin": str, "ticker": str, "ric": str}, keep_default_na=False, na_values=[""],
                    parse_dates=["date"], low_memory=False)
    assert len(d) == EXPECT_ROWS["mcap"], f"mcap rows {len(d)} != {EXPECT_ROWS['mcap']}"
    for c, n in EXPECT_NULLS.items():
        assert int(d[c].isna().sum()) == n, f"null {c}: {int(d[c].isna().sum())} != {n} (read of the CSV does not match the DB check)"
    return d


def build_rank_panel(mc: pd.DataFrame) -> pd.DataFrame:
    assert mc["quote_id"].notna().all(), "null quote_id"
    r = mc[mc["mcap"].notna()].copy()
    assert not r.duplicated(["date", "quote_id"]).any(), "duplicate (date, quote_id): stop and ask Manu"
    r = r.sort_values(["date", "mcap", "quote_id"], ascending=[True, False, True], kind="mergesort")
    r["rank"] = r.groupby("date").cumcount() + 1
    r["n_ranked"] = r.groupby("date")["rank"].transform("size")
    r["band"] = np.where(r["rank"] <= LARGE_MAX, "Large", np.where(r["rank"] <= MID_MAX, "Mid", "Small and below"))
    out = r[["date", "quote_id", "isin", "ticker", "mcap", "rank", "n_ranked", "band"]].reset_index(drop=True)
    out["date"] = out["date"].dt.strftime("%Y-%m-%d")
    return out


def build_membership_panel() -> pd.DataFrame:
    m = pd.read_csv(MEMB, dtype=str, keep_default_na=False, na_values=[""])
    assert len(m) == EXPECT_ROWS["memb"], f"membership rows {len(m)} != {EXPECT_ROWS['memb']}"
    unknown = set(m["index_name"]) - set(INDEX_BAND)
    assert not unknown, f"unmapped index names: {unknown}"
    assert m["isin"].notna().all(), "null isin in membership"
    assert not m.duplicated(["snapshot_date", "isin"]).any(), "ISIN in two indices on one snapshot"
    m["band"] = m["index_name"].map(INDEX_BAND)
    out = m[["snapshot_date", "index_name", "isin", "symbol", "band"]].sort_values(
        ["snapshot_date", "index_name", "isin"], kind="mergesort").reset_index(drop=True)
    return out


def main(check_only: bool) -> int:
    mc = read_mcap()
    rp = build_rank_panel(mc)
    mp = build_membership_panel()
    print(f"rank panel: {len(rp):,} rows, {rp['date'].nunique()} dates, {rp['date'].min()} -> {rp['date'].max()}; "
          f"{len(mc) - len(rp)} unranked (null mcap)")
    print("  band counts:", rp["band"].value_counts().to_dict())
    print(f"  ranked per date: min {int(rp['n_ranked'].min()):,} max {int(rp['n_ranked'].max()):,}")
    print(f"  rows with null isin: {int(rp['isin'].isna().sum())}, null ticker: {int(rp['ticker'].isna().sum())}")
    print(f"membership panel: {len(mp):,} rows, {mp['snapshot_date'].nunique()} snapshots; bands:", mp["band"].value_counts().to_dict())
    if check_only:
        print("check only: nothing written.")
        return 0
    if OUT.exists():
        sys.exit(f"STOP: {OUT} already exists. Candidates are never overwritten; ask Manu.")
    OUT.mkdir(parents=True)
    me = Path(__file__).resolve()
    man = {"built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "script": "data/build_tag_panels.py",
           "script_sha256": sha256(me), "status": "CANDIDATE (PENDING): off-limits to every test until Manu approves",
           "inputs": {p.name: sha256(p) for p in (MCAP, MEMB)}, "files": {}}
    for name, df in (("mcap_rank_panel.csv", rp), ("membership_panel.csv", mp)):
        p = OUT / name
        df.to_csv(p, index=False, encoding="utf-8", lineterminator="\n")
        man["files"][name] = {"rows": int(len(df)), "columns": list(df.columns), "sha256": sha256(p)}
        print(f"wrote {p.relative_to(AA)}  rows {len(df):,}  sha256 {man['files'][name]['sha256'][:16]}")
    (OUT / "manifest.json").write_text(json.dumps(man, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    sys.exit(main(ap.parse_args().check))
