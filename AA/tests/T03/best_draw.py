"""Save the weekly in-or-out states of the highest-CAGR random timing (N4.9) of one book, for the results page.

    python best_draw.py [--book SCMO_0003] [--cost 20.8] [--run headline]

Finds the draw with the highest CAGR in evidence/<run>/draws.csv (window full, cash lbes), rebuilds its states from the seed
(numpy default_rng([3, id]), as rerun_draw.py does), re-runs the engine, and exits non-zero unless the end NAV and CAGR equal the
stored row to 1e-12. Writes evidence/<run>/draw_<id>_states.csv: j, decision_date, real_state, draw_state (1 = parent, 0 = sleeve).
"""
import argparse, sys
from pathlib import Path

import numpy as np
import pandas as pd

AA = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(AA / "analysis"))
import t03_engine as E  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--book", default="SCMO_0003")
ap.add_argument("--cost", type=float, default=20.8)
ap.add_argument("--run", default="headline")
a = ap.parse_args()
ev = AA / "tests" / "T03" / "evidence" / a.run
d = pd.read_csv(ev / "draws.csv")
d = d[(d.book == a.book) & (d.window == "full") & (d.cash == "lbes") & (d.cost_bps == a.cost) & (d.draw_type == "N4.9")]
best = d.loc[d.cagr.idxmax()]
i = int(best.draw_id)
bk = E.Book(a.book)
dec = bk.decisions()
s = dec["state"].values.astype(int)
st = E.spell_shuffle(s, i)
res = E.stats(E.simulate(bk, dec["decision_idx"].values, st.astype(float), a.cost))
diff = max(abs(res["end_nav"] / best.end_nav - 1), abs(res["cagr"] - best.cagr))
print(f"{a.book} best draw id {i}: CAGR {res['cagr']:.6f} (stored {best.cagr:.6f}), max difference {diff:.1e}")
if diff >= 1e-12:
    sys.exit("rebuilt draw does not reproduce the stored row")
out = pd.DataFrame({"j": dec["j"].values, "decision_date": dec["decision_date"].values, "real_state": s, "draw_state": st})
out.to_csv(ev / f"draw_{i}_states.csv", index=False)
print("wrote", ev / f"draw_{i}_states.csv")
