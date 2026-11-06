"""Reproduce one null draw from its id.

    python rerun_draw.py --book SCMO_0003 --type N4.9 --id 17 --cost 20.8 [--window full|live] [--cash lbes|liquidcase]
    python rerun_draw.py --book SCMO_0003 --type shift --id 100 --cost 20.8

Uses the engine (analysis/t03_engine.py), rebuilds the draw's in-or-out series from its seed (numpy default_rng([3, id]); for the
circular shift, np.roll by id weeks), runs it, prints the statistics and compares them with the row in evidence/<run>/draws.csv.
"""
import argparse, sys
from pathlib import Path

import numpy as np
import pandas as pd

AA = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(AA / "analysis"))
import t03_engine as E  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--book", required=True)
ap.add_argument("--type", choices=["N4.9", "shift"], required=True)
ap.add_argument("--id", type=int, required=True)
ap.add_argument("--cost", type=float, default=20.8)
ap.add_argument("--window", default="full")
ap.add_argument("--cash", default="lbes")
ap.add_argument("--run", default="headline")
a = ap.parse_args()
bk = E.Book(a.book, start=(E.LIVE_START if a.window == "live" else None), cash=("liq" if a.cash == "liquidcase" else "lbes"))
dec = bk.decisions()
s = dec["state"].values.astype(int)
st = E.spell_shuffle(s, a.id) if a.type == "N4.9" else np.roll(s, a.id)
res = E.stats(E.simulate(bk, dec["decision_idx"].values, st.astype(float), a.cost))
print({k: (round(v, 10) if isinstance(v, float) else v) for k, v in res.items()})
d = pd.read_csv(AA / "tests" / "T03" / "evidence" / a.run / "draws.csv")
row = d[(d.book == a.book) & (d.window == a.window) & (d.cash == a.cash) & (d.cost_bps == a.cost) & (d.draw_type == a.type) & (d.draw_id == a.id)]
if len(row):
    r = row.iloc[0]
    diff = max(abs(res["end_nav"] / r.end_nav - 1), abs(res["cagr"] - r.cagr))
    print("stored row found; max difference in end NAV (relative) and CAGR:", diff)
    sys.exit(0 if diff < 1e-12 else 1)
print("no stored row for these arguments")
