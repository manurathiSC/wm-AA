"""Reproduce one R4 tag-error draw from its id and compare it with the evidence.

    python -I tests/T10/rerun_draw.py --book SCMO_0003 --id 17 [--run headline | --evidence DIR]

Calls the engine's own command (AA/analysis/t10_engine.py --rerun --book B --id N --out f.json), which rebuilds the draw from its seed
(R4: numpy.random.default_rng([10, draw_id, book_no]); per weekly decision in order and per rank-sourced stock in ISIN order, two uniforms; full window, LBES cash, 20.8 bps),
runs it through the same simulator and writes {"cagr", "diff_vs_switch", "weeks_changed"}. This script compares that with the row of evidence/<run>/r4_tag_error.csv
(book, draw_id): cagr and diff_vs_switch to a relative 1e-12, weeks_changed exactly.

Exit code 0 only if everything that exists in the evidence is equal; no stored row for the arguments is exit 2; the engine failing is exit 3.
It imports nothing from the engine (it runs it as a program).
"""
import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pandas as pd

AA = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", required=True)
    ap.add_argument("--id", type=int, required=True)
    ap.add_argument("--run", default="headline")
    ap.add_argument("--evidence", default=None, help="the evidence directory to compare with (overrides --run)")
    ap.add_argument("--engine", default=str(AA / "analysis" / "t10_engine.py"), help="the engine program to call (default analysis/t10_engine.py)")
    a = ap.parse_args()
    ev = Path(a.evidence) if a.evidence else HERE / "evidence" / a.run
    with tempfile.TemporaryDirectory() as td:
        outp = Path(td) / "rerun.json"
        cmd = [sys.executable, "-I", a.engine, "--rerun", "--book", a.book, "--id", str(a.id), "--out", str(outp)]
        print("running:", " ".join(cmd))
        pr = subprocess.run(cmd, cwd=str(AA), capture_output=True, text=True)
        if pr.returncode != 0 or not outp.exists():
            print("the engine's --rerun failed (exit %s):" % pr.returncode)
            print((pr.stdout or "")[-1500:])
            print((pr.stderr or "")[-1500:])
            sys.exit(3)
        res = json.loads(outp.read_text(encoding="utf-8"))
    print("rebuilt:", {k: (round(v, 12) if isinstance(v, float) else v) for k, v in res.items()})
    d = pd.read_csv(ev / "r4_tag_error.csv")
    row = d[(d.book == a.book) & (d.draw_id == a.id)]
    if not len(row):
        print("no stored r4_tag_error.csv row for these arguments")
        sys.exit(2)
    r = row.iloc[0]
    ok = True
    diffs = {}
    for k in ("cagr", "diff_vs_switch"):
        diffs[k] = abs(float(res[k]) - float(r[k])) / max(1.0, abs(float(r[k])))
        ok &= diffs[k] <= 1e-12
    wk_eq = int(res["weeks_changed"]) == int(r["weeks_changed"])
    ok &= wk_eq
    print(f"stored row (book {a.book}, draw {a.id}): cagr {float(r['cagr']):.12f}, diff_vs_switch {float(r['diff_vs_switch']):.12f}, weeks_changed {int(r['weeks_changed'])}")
    print("relative differences:", {k: f"{v:.1e}" for k, v in diffs.items()}, "| weeks_changed equal:", wk_eq)
    print("EQUAL" if ok else "DIFFERENT")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
