"""Reproduce one null draw from its id and compare it with the evidence.

    python tests/T07/rerun_draw.py --book SCMO_0003 --type N4.6 --id 17 --cost 20.8 [--window full|live] [--cash lbes|liq]
    python tests/T07/rerun_draw.py --book SCMO_0003 --type N4.8 --id 445 --cost 20.8
    options: --run headline | --evidence DIR   (the evidence directory to compare with)

Calls the engine's own command (AA/analysis/t07_engine.py --rerun ...), which rebuilds the draw from its seed (N4.6: default_rng([7, id, book_no]),
N4.8: default_rng([8, id, book_no])), runs it through the same simulator and writes {"end_nav", "cagr", "max_dd", "drops": [0/1 per row of event_stocks.csv]}.
This script compares that with

  * the row of evidence/<run>/draws.csv (end NAV, CAGR, maximum drawdown) to a relative 1e-12;
  * the row of draw_drops.npz (key "<book>|<window>|<type>"; LIQUIDCASE reuses the full-window drops): the 0/1 drops for every row of that book's and
    window's event_stocks.csv must be equal.

Exit code 0 only if everything that exists in the evidence is equal. No stored row for the arguments is an error (exit 2); the engine failing is exit 3.
It imports nothing from the engine (it runs it as a program).
"""
import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

AA = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", required=True)
    ap.add_argument("--type", choices=["N4.6", "N4.8"], required=True)
    ap.add_argument("--id", type=int, required=True)
    ap.add_argument("--cost", type=float, default=20.8)
    ap.add_argument("--window", choices=["full", "live"], default="full")
    ap.add_argument("--cash", choices=["lbes", "liq"], default="lbes")
    ap.add_argument("--run", default="headline")
    ap.add_argument("--evidence", default=None)
    ap.add_argument("--engine", default=str(AA / "analysis" / "t07_engine.py"), help="the engine program to call (default analysis/t07_engine.py)")
    a = ap.parse_args()
    ev = Path(a.evidence) if a.evidence else HERE / "evidence" / a.run

    with tempfile.TemporaryDirectory() as td:
        outp = Path(td) / "rerun.json"
        cmd = [sys.executable, "-I", a.engine, "--rerun", "--book", a.book, "--type", a.type, "--id", str(a.id), "--cost", f"{a.cost:g}", "--window", a.window, "--cash", a.cash, "--out", str(outp)]
        print("running:", " ".join(cmd))
        pr = subprocess.run(cmd, cwd=str(AA), capture_output=True, text=True)
        if pr.returncode != 0 or not outp.exists():
            print("the engine's --rerun failed (exit %s):" % pr.returncode)
            print((pr.stdout or "")[-1500:])
            print((pr.stderr or "")[-1500:])
            sys.exit(3)
        res = json.loads(outp.read_text(encoding="utf-8"))
    drops = np.asarray(res["drops"]).astype(int)
    print("rebuilt:", {k: (round(v, 10) if isinstance(v, float) else v) for k, v in res.items() if k != "drops"}, "| drops:", len(drops), "rows,", int(drops.sum()), "dropped")

    ok, found = True, False
    d = pd.read_csv(ev / "draws.csv")
    row = d[(d.book == a.book) & (d.window == a.window) & (d.cash == a.cash) & (d.cost_bps == a.cost) & (d.draw_type == a.type) & (d.draw_id == a.id)]
    if len(row):
        found = True
        r = row.iloc[0]
        diffs = {}
        for k in ("end_nav", "cagr", "max_dd"):
            diffs[k] = abs(float(res[k]) - float(r[k])) / max(1.0, abs(float(r[k])))
            ok &= diffs[k] <= 1e-12
        print("stored draws.csv row found; relative differences:", {k: f"{v:.1e}" for k, v in diffs.items()})
    else:
        print("no stored draws.csv row for these arguments")

    zp = ev / "draw_drops.npz"
    if zp.exists():
        z = np.load(zp)
        key = f"{a.book}|{'full' if a.cash == 'liq' else a.window}|{a.type}"
        if key in z.files and a.id < z[key].shape[0]:
            found = True
            stored = z[key][a.id].astype(int)
            eq = bool(len(stored) == len(drops) and (stored == drops).all())
            n_diff = int((stored != drops).sum()) if len(stored) == len(drops) else -1
            print(f"draw_drops.npz[{key!r}][{a.id}] equal to the rebuilt drops: {eq} (rows {len(stored)} vs {len(drops)}, differing {n_diff})")
            ok &= eq
        else:
            print(f"draw_drops.npz has no row for {key} id {a.id}")
    if not found:
        print("nothing in the evidence to compare with")
        sys.exit(2)
    print("EQUAL" if ok else "DIFFERENT")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
