# -*- coding: utf-8 -*-
"""The data boundary in code (AA/CLAUDE.md, "Data boundary"; AA/data/APPROVED_DATA.md).

Stdlib and pathlib only. Parses the table of AA/data/APPROVED_DATA.md (between `<!-- approved-table:start -->` and
`<!-- approved-table:end -->`; columns Status | ID | File | Through | sha256 prefix | Note; the same table
data/check_approved_data.py parses).

    require(path)   -> the absolute Path if `path` is an APPROVED row; otherwise raises NotApprovedError naming the row's
                       status (SUPERSEDED / PENDING) or "not in the table"
    rows()          -> the APPROVED rows: dicts with status, id, file, through, sha, note
    all_rows()      -> every row of the table
    row_for(path)   -> the table row of `path` (any status) or None
    check_sha(path) -> require(path), then hash the file: raises ShaMismatchError if the sha256 does not start with the
                       approved prefix; returns {"file", "through", "bytes", "sha256", "approved_row", "id"}
    as_of()         -> the "As of" date written at the top of APPROVED_DATA.md
    usable_from(path)         -> the `[usable-from: date]` restriction of a row (rule 7: Smallcap 100 before 2011-10-03), or None
    guard_window(path, first) -> raises NotApprovedError if a window reads that row from a date before its usable-from date
    restrictions()            -> every APPROVED row that carries such a marker

Nothing here reads a data file's contents except to hash it.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

AA = Path(__file__).resolve().parents[1]
MD = AA / "data" / "APPROVED_DATA.md"
STATUSES = ("APPROVED", "SUPERSEDED", "PENDING")


class NotApprovedError(RuntimeError):
    """A file that is not an APPROVED row of data/APPROVED_DATA.md was requested."""


class ShaMismatchError(RuntimeError):
    """A file's sha256 does not start with the prefix recorded in data/APPROVED_DATA.md."""


def _text() -> str:
    return MD.read_text(encoding="utf-8")


def all_rows() -> list[dict]:
    block = _text().split("<!-- approved-table:start -->")[1].split("<!-- approved-table:end -->")[0]
    out = []
    for line in block.splitlines():
        c = [x.strip() for x in line.strip().strip("|").split("|")]
        if len(c) >= 5 and c[0] in STATUSES:
            out.append({"status": c[0], "id": c[1], "file": c[2], "through": c[3], "sha": c[4], "note": " | ".join(c[5:])})
    return out


def rows() -> list[dict]:
    return [r for r in all_rows() if r["status"] == "APPROVED"]


def as_of() -> str:
    m = re.search(r"\*\*As of:\s*([0-9]{4}-[0-9]{2}-[0-9]{2})", _text())
    if not m:
        raise RuntimeError("APPROVED_DATA.md has no 'As of' date")
    return m.group(1)


def _rel(path) -> str | None:
    p = Path(path)
    p = p if p.is_absolute() else AA / p
    try:
        return p.resolve().relative_to(AA.resolve()).as_posix()
    except ValueError:
        return None


def row_for(path) -> dict | None:
    rel = _rel(path)
    if rel is None:
        return None
    for r in all_rows():
        if r["file"].casefold() == rel.casefold():
            return r
    return None


def require(path) -> Path:
    """Return the absolute Path of `path` if it is an APPROVED row, else raise NotApprovedError."""
    rel = _rel(path)
    if rel is None:
        raise NotApprovedError(f"{path}: not in the table (outside AA/)")
    r = row_for(path)
    if r is None:
        raise NotApprovedError(f"{rel}: not in the table of data/APPROVED_DATA.md, so not approved")
    if r["status"] != "APPROVED":
        raise NotApprovedError(f"{rel}: row {r['id']} is {r['status']}, not APPROVED; do not read it")
    return AA / rel


_USABLE = re.compile(r"\[usable-from:\s*([0-9]{4}-[0-9]{2}-[0-9]{2})\]")


def usable_from(path) -> str | None:
    """The first date a restricted row may be read from (the `[usable-from: YYYY-MM-DD]` marker in its note), else None.

    Rule 7 of APPROVED_DATA.md: Smallcap 100 prices before 2011-10-03 have no real open/high/low and must never be read.
    """
    r = row_for(path)
    if r is None:
        return None
    m = _USABLE.search(r["note"])
    return m.group(1) if m else None


def guard_window(path, first_date) -> None:
    """Raise NotApprovedError if a window starting at `first_date` would read rows of `path` before its usable-from date.

    Call it with the earliest date any row of the window (including warm-up and look-back) is read from.
    """
    uf = usable_from(path)
    if uf is not None and str(first_date)[:10] < uf:
        raise NotApprovedError(f"{_rel(path)}: usable from {uf} only (APPROVED_DATA.md rule 7); the window reads it from {str(first_date)[:10]}")


def restrictions() -> list[dict]:
    """Every APPROVED row that carries a usable-from marker."""
    out = []
    for r in rows():
        m = _USABLE.search(r["note"])
        if m:
            out.append({"file": r["file"], "id": r["id"], "usable_from": m.group(1)})
    return out


def sha256_of(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def check_sha(path) -> dict:
    p = require(path)
    r = row_for(path)
    if not p.exists():
        raise FileNotFoundError(f"{r['file']}: APPROVED but missing on disk")
    s = sha256_of(p)
    if not s.startswith(r["sha"]):
        raise ShaMismatchError(f"{r['file']}: sha256 {s[:16]} on disk, {r['sha']} approved")
    return {"file": r["file"], "through": r["through"], "bytes": p.stat().st_size, "sha256": s,
            "approved_row": f"{r['status']} {r['id']}", "id": r["id"], "usable_from": usable_from(path)}
