"""Check data/APPROVED_DATA.md against the files on disk.

    python data/check_approved_data.py            exit 0 only if every APPROVED row's file exists, its sha256 starts with the
                                                  recorded prefix and, where the format is known, its last date equals "Through"
    python data/check_approved_data.py --sha PATH print PATH's sha256 prefix and last date (to record an approval)

Also lists files named *extended* or *candidate* that are not in the table: they are off-limits until Manu approves them.
Run it from anywhere; paths in the table are relative to AA/. Writes nothing.
"""
import argparse
import hashlib
import re
import sys
from pathlib import Path

import pandas as pd

AA = Path(__file__).resolve().parents[1]
MD = AA / "data" / "APPROVED_DATA.md"
DATE_CHECKED = {"D17", "D18", "D03", "D09", "D12", "D20", "D21", "D23"}   # D20/D21/D23 added 2026-11-12 (last_date reads their date / first column)


def sha16(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()[:16]


def last_date(p: Path):
    """Last date in the file, or None when the format is not one this script knows."""
    try:
        if p.suffix == ".xlsx":
            d = pd.read_excel(p, parse_dates=["Date"])
            d = d.dropna(subset=["SIGN"]) if "SIGN" in d.columns else d
            return str(d["Date"].max().date())
        if p.suffix == ".parquet":
            return str(pd.to_datetime(pd.read_parquet(p)["date"]).max().date())
        d = pd.read_csv(p)
        if "_id.date" in d.columns:
            return str(pd.to_datetime(d["_id.date"], format="%Y/%m/%d").max().date())
        if "date" in d.columns:
            return str(pd.to_datetime(d["date"]).max().date())
        return str(pd.to_datetime(d.iloc[:, 0]).max().date())
    except Exception:
        return None


def rows():
    txt = MD.read_text(encoding="utf-8")
    block = txt.split("<!-- approved-table:start -->")[1].split("<!-- approved-table:end -->")[0]
    out = []
    for line in block.splitlines():
        c = [x.strip() for x in line.strip().strip("|").split("|")]
        if len(c) >= 5 and c[0] in ("APPROVED", "SUPERSEDED", "PENDING"):
            out.append({"status": c[0], "id": c[1], "file": c[2], "through": c[3], "sha": c[4], "note": " | ".join(c[5:])})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sha", help="print the sha256 prefix and last date of this path (relative to AA/ or absolute)")
    a = ap.parse_args()
    if a.sha:
        p = Path(a.sha) if Path(a.sha).is_absolute() else AA / a.sha
        print(f"{p}\n  sha256 prefix: {sha16(p)}\n  last date: {last_date(p)}")
        return 0
    rs = rows()
    bad, n_ok = [], 0
    for r in rs:
        if r["status"] != "APPROVED":
            continue
        p = AA / r["file"]
        if not p.exists():
            bad.append(f"MISSING  {r['id']} {r['file']}")
            continue
        s = sha16(p)
        if s != r["sha"]:
            bad.append(f"CHANGED  {r['id']} {r['file']}: sha256 {s} on disk, {r['sha']} approved")
            continue
        if r["id"] in DATE_CHECKED and r["through"] != "n/a":
            ld = last_date(p)
            if ld != r["through"]:
                bad.append(f"DATE     {r['id']} {r['file']}: last date {ld} on disk, {r['through']} approved")
                continue
        n_ok += 1
    listed = {r["file"].replace("\\", "/") for r in rs}
    cand = []
    for pat in ("Historical Data/**/*extended*", "analysis/cache/*extended*", "data/holdings_matrix/*extended*", "Historical Data/extended_*/**/*", "**/*candidate*"):
        for f in AA.glob(pat):
            rel = f.relative_to(AA).as_posix()
            if f.is_file() and f.name != "manifest.json" and rel not in listed and "/tests/" not in "/" + rel and not rel.startswith("tests/"):
                cand.append(rel)
    pend = [r for r in rs if r["status"] == "PENDING"]
    print(f"approved rows checked OK: {n_ok}; problems: {len(bad)}; PENDING rows (not usable): {len(pend)}; superseded rows: {sum(r['status'] == 'SUPERSEDED' for r in rs)}")
    for b in bad:
        print("PROBLEM", b)
    for r in rs:   # rule 7 of APPROVED_DATA.md: rows that may only be read from a given date
        m = re.search(r"\[usable-from:\s*([0-9]{4}-[0-9]{2}-[0-9]{2})\]", r.get("note", ""))
        if m and r["status"] == "APPROVED":
            print(f"RESTRICTION {r['id']} {r['file']}: read rows dated {m.group(1)} or later ONLY (Smallcap 100 OHLCV before 2011-10-03 is corrupt: open=high=low=close)")
    for c in sorted(set(cand)):
        print("OFF-LIMITS (not in the table):", c)
    if bad:
        print("STOP: the data on disk no longer matches APPROVED_DATA.md. Ask Manu before going on.")
    return 1 if (bad or n_ok == 0) else 0


if __name__ == "__main__":
    sys.exit(main())
