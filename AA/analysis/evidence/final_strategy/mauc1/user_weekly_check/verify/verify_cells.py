"""Cell-by-cell rebuild of the user's file with my own code (W-FRI all sessions, close-only H/L fill, start at 5th candle)."""
import runpy, numpy as np, pandas as pd
from pathlib import Path
HERE = Path(__file__).resolve().parent
g = runpy.run_path(str(HERE / "verify.py"), run_name="not_main")
U, myW, st = g["U"], g["myW"], g["supertrend"]
s = st(myW.High, myW.Low, myW.Close, start=4).set_index(myW.index)
rb = pd.DataFrame({"Open": myW.Open, "High": myW.High, "Low": myW.Low, "Close": myW.Close, "Volume": myW.Volume,
                   "TR": s.TR.round(0), "LW_ATR5": s.ATR.round(1), "HL2": s.HL2.round(1), "UpperBand": s.FUB.round(1),
                   "LowerBand": s.FLB.round(1), "Supertrend": s.ST.round(1), "Signal": s.SIG})
tot = bad = 0
for c in U.columns:
    a, b = U[c], rb[c].reindex(U.index)
    eq = (a == b) | (a.isna() & b.isna()) if c == "Signal" else ((a - b).abs() < 1e-9) | (a.isna() & b.isna())
    tot += len(eq); bad += int((~eq).sum())
    if (~eq).any(): print(c, list(U.index[~eq].date)[:5])
print("cells", tot, "mismatched", bad)
