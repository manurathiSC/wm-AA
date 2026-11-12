# -*- coding: utf-8 -*-
"""Refresh the published index series of the 8 portfolios from Redash query 2396 ("scid Historical Indices").

The 8 scids: SCMO_0003, 0007, 0010, 0029 (the parents) and SCMO_0042, 0043, 0044, 0045 (the AA books on those parents).
Procedure: AA/data/REFRESH_PUBLISHED_NAV.md. In short:

  1. Claude runs the Redash MCP tool `execute_query` with queryId 2396, parameters {"scids": "<the 8, comma separated>"},
     maxAge 0. The result is too big for the chat, so the tool saves it to a file and prints the path.
  2. python data/refresh_published_nav.py --rows <that path> --check     (writes nothing; prints every check)
  3. python data/refresh_published_nav.py --rows <that path>             (writes the candidate folder)
  4. The candidate is OFF-LIMITS until Manu approves it; then an agent updates APPROVED_DATA.md by its procedure.

    python data/refresh_published_nav.py --status        what the approved NAVs and the candidate folders cover (reads dates only)

Manner (the same as the other extenders, CLAUDE.md "Refreshing the data pool"): the originals are never edited; rows the
parent files already hold are copied byte for byte and only the new rows (newest first, CRLF) go on top; the script stops
when the overlap disagrees, and prints every date that is in one side only. The output goes to
Historical Data/extended_<last date>/published_nav/SCMO_<id>.csv, same columns as D17: _id.scid, _id.date (YYYY/MM/DD), index.

The AA books (0042-0045) have no approved file to overlap with (D15 `indices.csv` is not approved and is not read here), so
they are written whole from Redash and checked on their own (dates, gaps, spikes, same dates as the parents on the new rows).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

AA = Path(__file__).resolve().parents[1]
HD = AA / "Historical Data"
sys.path.insert(0, str(AA / "analysis"))
import approved_data as AD  # noqa: E402

QUERY_ID = 2396
PARENTS = ["SCMO_0003", "SCMO_0007", "SCMO_0010", "SCMO_0029"]
AA_BOOKS = ["SCMO_0042", "SCMO_0043", "SCMO_0044", "SCMO_0045"]
SCIDS = PARENTS + AA_BOOKS
BASE_DIR = HD / "parent_nav_2026-10-22"          # D17, the approved parent NAVs the overlap check runs against
HEADER = "_id.scid,_id.date,index"
TOL = 1e-9                                        # relative; the 2026-11-09 pull matched D17 to 0.0
MAX_DAY_MOVE = 0.10                               # a new-row daily move beyond this is listed as a spike
MAX_GAP_DAYS = 5


def sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def load_rows(path: Path):
    """Rows of a saved Redash MCP result (query_result.data.rows) or a bare JSON list. Returns (DataFrame, meta)."""
    j = json.loads(path.read_text(encoding="utf-8"))
    meta = {}
    if isinstance(j, dict) and "query_result" in j:
        qr = j["query_result"]
        meta = {"retrieved_at": qr.get("retrieved_at"), "data_source_id": qr.get("data_source_id"), "query_text_has_scids":
                [s for s in SCIDS if f'"{s}"' in qr.get("query", "") or s in qr.get("query", "")]}
        rows = qr["data"]["rows"]
    else:
        rows = j
    d = pd.DataFrame(rows)
    need = {"_id.scid", "_id.date", "index"}
    if not need <= set(d.columns):
        raise SystemExit(f"STOP: rows lack columns {need - set(d.columns)}")
    d["dt"] = pd.to_datetime(d["_id.date"], format="%Y/%m/%d")
    return d, meta


def old_lines(p: Path):
    """The approved parent file as (header, list of data lines without line end, dict date->index)."""
    raw = AD.require(p).read_bytes().decode("utf-8")
    ls = raw.splitlines()
    body = ls[1:]
    idx = {}
    for ln in body:
        s, dt, v = ln.split(",")
        idx[dt] = float(v)
    return ls[0], body, idx


def build(d: pd.DataFrame, meta: dict, out_root: Path | None, check_only: bool):
    problems, report, files = [], [], {}
    got = sorted(d["_id.scid"].unique())
    miss = [s for s in SCIDS if s not in got]
    extra = [s for s in got if s not in SCIDS]
    if miss:
        problems.append(f"scids missing from the result: {miss}")
    if extra:
        problems.append(f"scids in the result that were not asked for: {extra}")
    last = {s: d[d["_id.scid"] == s]["dt"].max() for s in got}
    if len(set(last.values())) != 1:
        problems.append(f"the 8 series end on different dates: { {s: str(v.date()) for s, v in last.items()} }")
    asof = max(last.values()) if last else None

    per = {}
    for s in SCIDS:
        x = d[d["_id.scid"] == s].sort_values("dt")
        if x.empty:
            continue
        r = {"first": str(x.dt.min().date()), "last": str(x.dt.max().date()), "rows": len(x)}
        if x["_id.date"].duplicated().any():
            problems.append(f"{s}: duplicate dates {x[x['_id.date'].duplicated()]['_id.date'].tolist()[:5]}")
        if not (x["index"] > 0).all() or x["index"].isna().any():
            problems.append(f"{s}: non-positive or blank index values")
        gaps = x.dt.diff().dt.days.dropna()
        r["max_gap_days"] = int(gaps.max())
        if gaps.max() > MAX_GAP_DAYS:
            problems.append(f"{s}: a gap of {int(gaps.max())} calendar days (limit {MAX_GAP_DAYS})")
        per[s] = (x, r)

    # parents: overlap with the approved D17 file, then new rows on top
    for s in PARENTS:
        if s not in per:
            continue
        x, r = per[s]
        hdr, body, old = old_lines(BASE_DIR / f"{s}.csv")
        new_idx = dict(zip(x["_id.date"], x["index"]))
        only_old = sorted(set(old) - set(new_idx))
        common = sorted(set(old) & set(new_idx))
        diff = max((abs(old[k] - new_idx[k]) / abs(old[k]) for k in common), default=0.0)
        r.update({"overlap_dates": len(common), "dates_only_in_approved": only_old, "max_rel_diff_overlap": diff})
        if only_old:
            problems.append(f"{s}: {len(only_old)} approved dates missing from Redash: {only_old[:5]}")
        if diff > TOL:
            problems.append(f"{s}: overlap disagrees, max relative difference {diff:.3e} (limit {TOL:g}); Redash history was restated, stop and ask Manu")
        newrows = x[~x["_id.date"].isin(set(old))].sort_values("dt", ascending=False)
        older_than = [k for k in newrows["_id.date"] if k < max(old)]
        if older_than:
            problems.append(f"{s}: Redash dates inside the approved span that the approved file lacks: {older_than[:5]}")
        r["new_rows"] = len(newrows)
        lines = [f"{s},{k},{repr(float(v))}" for k, v in zip(newrows["_id.date"], newrows["index"])] + body
        files[s] = (hdr, lines, newrows)

    # AA books: whole series from Redash
    for s in AA_BOOKS:
        if s not in per:
            continue
        x, r = per[s]
        n = x.sort_values("dt", ascending=False)
        files[s] = (HEADER, [f"{s},{k},{repr(float(v))}" for k, v in zip(n["_id.date"], n["index"])], None)
        r["note"] = "no approved file to overlap with; written whole"

    # new-row checks: same dates in all 8, spikes, the sessions of D18
    new_dates = None
    if PARENTS[0] in files and files[PARENTS[0]][2] is not None:
        new_dates = sorted(files[PARENTS[0]][2]["_id.date"])
    for s in PARENTS[1:]:
        if s in files and files[s][2] is not None and sorted(files[s][2]["_id.date"]) != new_dates:
            problems.append(f"{s}: new dates differ from SCMO_0003's")
    spikes = []
    for s in SCIDS:
        if s not in per or not new_dates:
            continue
        x = per[s][0].set_index("_id.date")["index"]
        ret = x.pct_change().dropna()
        for k in new_dates:
            if k in ret.index and abs(ret[k]) > MAX_DAY_MOVE:
                spikes.append((s, k, round(float(ret[k]), 4)))
        aa_new = sorted(k for k in x.index if k > "0000" and k >= min(new_dates))
        if aa_new != new_dates:
            problems.append(f"{s}: dates after the approved end are {aa_new}, SCMO_0003's are {new_dates}")
    if spikes:
        report.append(f"daily moves beyond {MAX_DAY_MOVE:.0%} in the new rows (look at them): {spikes}")
    sess = None
    try:
        o = pd.read_csv(AD.require("data/holdings_matrix/SCMO_0003_ohlc.csv"), usecols=["date"])
        sess = set(pd.to_datetime(o["date"]).dt.strftime("%Y/%m/%d"))
    except Exception as e:  # informational only
        report.append(f"D18 session cross-check skipped: {e}")
    if sess is not None and new_dates:
        inside = [k for k in new_dates if k <= max(sess)]
        report.append(f"new NAV dates up to D18's last session ({max(sess)}): {len(inside)}; of them absent from D18's sessions: "
                      f"{[k for k in inside if k not in sess]}; D18 sessions after the old NAV end and before {max(sess)} that the NAV lacks: "
                      f"{sorted(k for k in sess if '2026/10/22' < k <= max(new_dates) and k not in new_dates)}")

    out = {"query_id": QUERY_ID, "retrieved_at": meta.get("retrieved_at"), "as_of": str(asof.date()) if asof is not None else None,
           "series": {s: per[s][1] for s in per}, "problems": problems, "report": report}
    for s in SCIDS:
        if s in per:
            x, r = per[s]
            r["last_value"] = float(x.sort_values("dt").iloc[-1]["index"])
    print(f"Redash query {QUERY_ID}, retrieved {meta.get('retrieved_at')}, {len(d)} rows, ends {out['as_of']}")
    for s in SCIDS:
        if s in per:
            r = per[s][1]
            print(f"  {s}: {r['first']} -> {r['last']}  rows {r['rows']}  new {r.get('new_rows', '-')}  last {r['last_value']:.6f}  "
                  f"overlap {r.get('overlap_dates', '-')} (max rel diff {r.get('max_rel_diff_overlap', '-')})")
    for t in report:
        print("  note:", t)
    for p in problems:
        print("PROBLEM", p)
    if problems:
        print("STOP: do not write or approve this refresh; tell Manu.")
        return 1, out
    if check_only:
        print("check only: nothing written.")
        return 0, out
    folder = HD / f"extended_{out['as_of'].replace('/', '-')}" / "published_nav"
    folder.mkdir(parents=True, exist_ok=True)
    manifest = {**{k: out[k] for k in ("query_id", "retrieved_at", "as_of")}, "files": {}}
    for s, (hdr, lines, _) in files.items():
        p = folder / f"{s}.csv"
        p.write_bytes(("\r\n".join([hdr] + lines) + "\r\n").encode("utf-8"))
        manifest["files"][f"{s}.csv"] = {**out["series"][s], "sha256": sha(p)}
        print(f"  wrote {p.relative_to(AA).as_posix()}  sha256 {sha(p)[:16]}")
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    print(f"wrote {folder.relative_to(AA).as_posix()}/manifest.json. Candidate: off-limits until Manu approves.")
    return 0, out


def status():
    """Per scid: the newest APPROVED published-NAV file and its through-date, and any non-approved candidate."""
    print(f"As of (APPROVED_DATA.md): {AD.as_of()}")
    for s in SCIDS:
        rs = [r for r in AD.all_rows() if r["file"].endswith(f"/{s}.csv") and ("parent_nav_" in r["file"] or "published_nav/" in r["file"])]
        ok = sorted((r for r in rs if r["status"] == "APPROVED"), key=lambda r: r["through"])
        other = [r for r in rs if r["status"] != "APPROVED"]
        best = ok[-1] if ok else None
        print(f"  {s}: latest APPROVED through {best['through'] if best else '-'}  ({best['file'] if best else 'no approved file'})"
              + (f"; not usable: {[(r['status'], r['through']) for r in other]}" if other else ""))
    for m in sorted(HD.glob("extended_*/published_nav/manifest.json")):
        j = json.loads(m.read_text(encoding="utf-8"))
        unl = [s for s in SCIDS if AD.row_for(f"{m.parent.relative_to(AA).as_posix()}/{s}.csv") is None]
        print(f"  folder {m.parent.relative_to(AA).as_posix()}: ends {j['as_of']}, retrieved {j['retrieved_at']}"
              + (f"; NOT in the table (off-limits): {unl}" if unl else "; all 8 listed"))
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rows", help="path of the saved Redash MCP result (or a JSON list of rows)")
    ap.add_argument("--check", action="store_true", help="run every check, write nothing")
    ap.add_argument("--status", action="store_true")
    a = ap.parse_args()
    if a.status:
        return status()
    if not a.rows:
        ap.error("--rows is required (or --status)")
    d, meta = load_rows(Path(a.rows))
    rc, _ = build(d, meta, None, a.check)
    return rc


if __name__ == "__main__":
    sys.exit(main())
