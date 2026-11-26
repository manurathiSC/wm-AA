"""Extend the per-parent stock OHLC files (D18) to the latest Eikon session in Postgres, as a NEW candidate folder.

    python data/extend_stock_ohlc.py --check              # rebuild into a temp folder, run every check, write nothing
    python data/extend_stock_ohlc.py                      # same, then write Historical Data/extended_<last>/holdings_ohlc/
    python data/extend_stock_ohlc.py --last 2026-11-25    # cut the new rows at this date

How (F-AA-D13 manner, CLAUDE.md "Refreshing the data pool"):
- Rebuilds each parent with the unchanged D18 builder `data/build_ohlc_file.py` (same source: Postgres `ohlcv_eikon`
  via `symbology_changes`, same manual exports, same session and carry-forward rules) into a temporary folder.
  The approved files in data/holdings_matrix/ are never written.
- Gate: the rebuild's rows dated on or before the approved file's last date must equal the approved file's rows
  exactly (every column as text, same order). If Eikon re-adjusted a stock (a corporate action), the gate fails,
  the differing rows are printed and nothing is written.
- The candidate file is the rebuild cut at --last: so the approved rows are present verbatim and only the new
  sessions are added. The availability and filled-cells side files are written beside it for the record.
- --append (for when the DB's history has changed since the approved build, e.g. the 2026-11-08 rewrite after the
  2026-11-03 corporate-action backup, which dropped many stocks' bars on special sessions): the full-overlap gate is
  reported but does not block. Instead the SEAM gate must pass: on the approved file's last date every approved
  stock's bar (open, high, low, close, src) equals the rebuild's exactly, so the new rows are on the approved
  adjustment basis. The candidate is then the approved rows copied verbatim (as text) plus the rebuild's rows dated
  after the approved last date, in the approved order (stock order of the holdings matrix, then date). The side files
  are not written in this mode (they would describe the rebuilt history, not the candidate).
- Reports on the new rows: sessions, stocks per session, src counts (db/export/carried), largest daily close moves.
- Also reports whether Postgres `smallcase_rebal_historical` holds a basket newer than the holdings matrix
  (the D19 weights); the builder holds the last basket in force after its date.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_ohlc_file as B  # noqa: E402

AA = Path(__file__).resolve().parents[1]
HD = AA / "Historical Data"
APPROVED_DIR = AA / "data" / "holdings_matrix"


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def compare(parent: str, stage: Path, last: pd.Timestamp | None, append: bool = False) -> tuple[bool, dict]:
    old = pd.read_csv(APPROVED_DIR / f"{parent}_ohlc.csv", dtype=str, keep_default_na=False)
    new = pd.read_csv(stage / f"{parent}_ohlc.csv", dtype=str, keep_default_na=False)
    old_last = pd.Timestamp(old["date"].max())
    d = pd.to_datetime(new["date"])
    if last is not None:
        new = new[d <= last].reset_index(drop=True)
        d = pd.to_datetime(new["date"])
    ov = new[d <= old_last].reset_index(drop=True)
    ok = list(ov.columns) == list(old.columns) and len(ov) == len(old) and bool((ov.values == old.values).all())
    info = {"approved_rows": len(old), "approved_last": old_last.date().isoformat(), "overlap_identical": ok}
    if not ok and append:
        F = ["open", "high", "low", "close"]
        m = old.merge(ov, on=["date", "stock"], how="outer", suffixes=("_o", "_n"), indicator=True)
        b = m[m["_merge"] == "both"]
        num = lambda s: pd.to_numeric(s, errors="coerce")  # some bars have a blank open/high/low (kept as is)
        rel = pd.concat([(num(b[f + "_n"]) / num(b[f + "_o"]) - 1).abs() for f in F], axis=1).max(axis=1)
        lo = m[m["_merge"] == "left_only"]
        info["overlap_report"] = {
            "rows_only_in_approved": len(lo),
            "only_in_approved_by_date": {str(k): int(v) for k, v in lo["date"].value_counts().sort_index().items()},
            "rows_only_in_rebuild": int((m["_merge"] == "right_only").sum()),
            "only_in_rebuild": m[m["_merge"] == "right_only"][["date", "stock"]].values.tolist(),
            "rows_src_changed": int((b["src_o"] != b["src_n"]).sum()),
            "rows_rel_diff_over_1e-5": int((rel > 1e-5).sum()),
            "rows_rel_diff_1e-9_to_1e-5": int(((rel > 1e-9) & (rel <= 1e-5)).sum()),
            "max_rel_diff_below_1e-5_rows": float(rel[rel <= 1e-5].max()),
        }
        so = old[pd.to_datetime(old["date"]) == old_last].set_index("stock").drop(columns="date")
        sn = new[pd.to_datetime(new["date"]) == old_last].set_index("stock").drop(columns="date")
        assert len(so) > 0, "seam: no approved bars on the approved last date"
        seam_ok = bool(so.index.isin(sn.index).all()) and bool((sn.reindex(so.index).values == so.values).all())
        info["seam_identical"] = bool(seam_ok)
        r = info["overlap_report"]
        print(f"  {parent}: full overlap differs (reported, not blocking under --append): only-approved "
              f"{r['rows_only_in_approved']} {r['only_in_approved_by_date']}; only-rebuild {r['rows_only_in_rebuild']}; "
              f"src changed {r['rows_src_changed']}; rel diff > 1e-5 on {r['rows_rel_diff_over_1e-5']} rows; "
              f"1e-9..1e-5 on {r['rows_rel_diff_1e-9_to_1e-5']} rows")
        print(f"  {parent}: SEAM {old_last.date()}: {len(so)} approved bars, identical in the rebuild: {seam_ok}")
        if not seam_ok:
            print(f"  PROBLEM {parent}: seam differs; nothing can be appended")
            return False, info
    elif not ok:
        print(f"  PROBLEM {parent}: rebuild differs from the approved file on or before {old_last.date()}")
        print(f"    approved rows {len(old)}, rebuild rows to that date {len(ov)}")
        m = old.merge(ov, on=["date", "stock"], how="outer", suffixes=("_old", "_new"), indicator=True)
        print(f"    rows only in approved: {int((m['_merge'] == 'left_only').sum())}, "
              f"only in rebuild: {int((m['_merge'] == 'right_only').sum())}")
        both = m[m["_merge"] == "both"]
        diff = both[(both["close_old"] != both["close_new"]) | (both["open_old"] != both["open_new"])
                    | (both["high_old"] != both["high_new"]) | (both["low_old"] != both["low_new"])
                    | (both["src_old"] != both["src_new"])]
        print(f"    rows with a changed value: {len(diff)}; by stock: {diff['stock'].value_counts().head(15).to_dict()}")
        print(diff.head(20).to_string())
        return False, info

    add = new[pd.to_datetime(new["date"]) > old_last].copy()
    full = pd.concat([old, add]) if append else new.copy()
    full["date"] = pd.to_datetime(full["date"])
    full["close"] = full["close"].astype(float)
    full = full.sort_values(["stock", "date"])
    full["ret"] = full.groupby("stock")["close"].pct_change()
    hist = full[full["date"] <= old_last]["ret"].abs().dropna()
    newr = full[full["date"] > old_last]
    big = newr[newr["ret"].abs() > 0.15][["date", "stock", "close", "ret", "src"]]
    per_day = newr.groupby("date")["stock"].nunique()
    info.update({
        "new_rows": len(add), "new_sessions": sorted({x for x in add["date"]}),
        "new_last": add["date"].max() if len(add) else None,
        "new_src": add["src"].value_counts().to_dict(),
        "stocks_per_new_session": {k.date().isoformat(): int(v) for k, v in per_day.items()},
        "stocks_on_approved_last": int(full[full["date"] == old_last]["stock"].nunique()),
        "max_abs_new_move": float(newr["ret"].abs().max()) if len(newr) else None,
        "history_abs_move_p999": float(hist.quantile(0.999)),
        "new_moves_over_15pct": big.assign(date=big["date"].dt.date.astype(str)).to_dict("records"),
    })
    return True, info


def newer_baskets(conn) -> dict:
    out = {}
    for p in B.PARENTS:
        mat = pd.read_csv(APPROVED_DIR / f"{p}_holdings_matrix.csv", parse_dates=["rebalance_date"])
        db = pd.read_sql("select max(rebalance_date) as d from smallcase_rebal_historical where scid=%(s)s",
                         conn, params={"s": p})
        out[p] = {"matrix_last": mat["rebalance_date"].max().date().isoformat(), "db_last_rebalance": str(db["d"].iloc[0])}
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="run every check, write nothing")
    ap.add_argument("--last", help="last session to keep (YYYY-MM-DD); default: everything the DB has")
    ap.add_argument("--append", action="store_true",
                    help="approved rows verbatim + new rows, gated on the seam instead of the full overlap")
    a = ap.parse_args()
    last = pd.Timestamp(a.last) if a.last else None

    conn = B.connect()
    retrieved = datetime.now().isoformat(timespec="seconds")
    stage = Path(tempfile.mkdtemp(prefix="stock_ohlc_"))
    try:
        for p in B.PARENTS:
            B.build(p, conn, out_dir=stage)
        print("\n===== checks =====")
        baskets = newer_baskets(conn)
        for p, b in baskets.items():
            print(f"  {p}: holdings matrix last basket {b['matrix_last']}; DB newest rebalance_date {b['db_last_rebalance']}")
        results, all_ok = {}, True
        for p in B.PARENTS:
            ok, info = compare(p, stage, last, a.append)
            results[p] = info
            all_ok &= ok
            if ok:
                how = ("reproduced exactly" if info["overlap_identical"] else "kept verbatim (seam identical)")
                print(f"  {p}: approved {info['approved_rows']} rows to {info['approved_last']} {how}; "
                      f"+{info['new_rows']} rows, {len(info['new_sessions'])} sessions "
                      f"{info['new_sessions'][:1]}..{info['new_sessions'][-1:]}; src {info['new_src']}")
                print(f"      stocks per new session {info['stocks_per_new_session']} (on {info['approved_last']}: "
                      f"{info['stocks_on_approved_last']})")
                print(f"      largest new |daily move| {info['max_abs_new_move']:.2%} (history 99.9th pct "
                      f"{info['history_abs_move_p999']:.2%}); moves > 15%: {info['new_moves_over_15pct']}")
        if not all_ok:
            print("\nPROBLEM: overlap gate failed; nothing written.")
            return 2
        lasts = {results[p]["new_last"] for p in B.PARENTS}
        if len(lasts) != 1 or None in lasts:
            print(f"\nPROBLEM: parents end on different dates or have no new rows: {lasts}; nothing written.")
            return 2
        end = lasts.pop()
        if a.check:
            print(f"\ncheck only: nothing written (would write Historical Data/extended_{end}/holdings_ohlc/).")
            return 0
        dest = HD / f"extended_{end}" / "holdings_ohlc"
        if dest.exists():
            print(f"PROBLEM: {dest} already exists; nothing written.")
            return 2
        dest.mkdir(parents=True)
        man = {"retrieved_at": retrieved, "source": "Postgres ohlcv_eikon via symbology_changes + data/missing_rics "
               "(data/build_ohlc_file.py, unchanged rules)", "last": a.last, "append": a.append,
               "baskets": baskets, "files": {}}
        for p in B.PARENTS:
            if a.append:
                old = pd.read_csv(APPROVED_DIR / f"{p}_ohlc.csv", dtype=str, keep_default_na=False)
                new = pd.read_csv(stage / f"{p}_ohlc.csv", dtype=str, keep_default_na=False)
                nd = pd.to_datetime(new["date"])
                keep = nd > pd.Timestamp(results[p]["approved_last"])
                if last is not None:
                    keep &= nd <= last
                order = {s: i for i, s in enumerate(pd.read_csv(APPROVED_DIR / f"{p}_columns.csv")["stock"])}
                out = pd.concat([old, new[keep]], ignore_index=True)
                out = out.sort_values(["stock", "date"], key=lambda c: c.map(order) if c.name == "stock" else c,
                                      kind="stable")
                out.to_csv(dest / f"{p}_ohlc.csv", index=False)
                back = pd.read_csv(dest / f"{p}_ohlc.csv", dtype=str, keep_default_na=False)
                back = back[pd.to_datetime(back["date"]) <= pd.Timestamp(results[p]["approved_last"])].reset_index(drop=True)
                assert back.shape == old.shape and (back.values == old.values).all(), f"{p}: approved rows not verbatim"
                man["files"][p] = {**results[p], "sha256": sha(dest / f"{p}_ohlc.csv")}
                continue
            for suffix in ("_ohlc.csv", "_ohlc_availability.csv", "_ohlc_filled_cells.csv"):
                src = stage / f"{p}{suffix}"
                if suffix == "_ohlc.csv" and last is not None:
                    f = pd.read_csv(src, dtype=str, keep_default_na=False)
                    f[pd.to_datetime(f["date"]) <= last].to_csv(dest / src.name, index=False)
                else:
                    shutil.copyfile(src, dest / src.name)
            man["files"][p] = {**results[p], "sha256": sha(dest / f"{p}_ohlc.csv")}
        (dest / "manifest.json").write_text(json.dumps(man, indent=1, default=str))
        print(f"\nwrote {dest}")
        return 0
    finally:
        shutil.rmtree(stage, ignore_errors=True)
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
