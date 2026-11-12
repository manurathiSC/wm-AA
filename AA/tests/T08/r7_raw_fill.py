"""T08 robustness R7 (pre-registered, T08.md §2): the rule re-run with the close in place of the raw OHLC4 on every GOLDBEES session after the
MCX range file ends (2026-09-28), at 20.8 bps, per book. Writes evidence/<run>/r7_raw_fill.csv, which analyse.py, report.py and check_page.py read.

    python tests/T08/r7_raw_fill.py [--run headline]

Uses the engine's own Book and simulate (read only; nothing in the engine or its evidence is changed). The baseline row must reproduce stats.csv's
`strategy` at 20.8 bps to 1e-12, or the script stops. (The frozen text deferred the bar ranges on the raw-fill sessions to R7; they are not computed
here, only the effect of using the close.)
"""
import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

AA = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(AA / "analysis"))
import t08_engine as E  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--run", default="headline")
a = ap.parse_args()
ev = Path(__file__).resolve().parent / "evidence" / a.run
st = pd.read_csv(ev / "stats.csv")
rows, ranges = [], []
for p in ["SCMO_0003", "SCMO_0007", "SCMO_0010", "SCMO_0029"]:
    bk = E.Book(p)
    dec = bk.decisions()
    idx = dec["decision_idx"].values
    s = dec["state"].values.astype(float)
    g = dec["g"].values.astype(int)
    gw = np.where(g == 1, E.GW_BUY, E.GW_SELL)
    base_nav, tr, _ = E.simulate(bk, idx, s, E.PRIMARY, record=True, gw=gw)
    sb = E.stats(base_nav)
    ref = st[(st.book == p) & (st.window == "full") & (st.cash == "lbes") & (st.cost_bps == E.PRIMARY) & (st.kind == "strategy")].iloc[0]
    assert abs(sb["cagr"] - ref.cagr) < 1e-12 and abs(sb["max_dd"] - ref.max_dd) < 1e-12, f"{p}: baseline does not reproduce stats.csv"
    raw = bk.gold_raw.copy()
    n_raw_trades = sum(1 for t in tr if bk.gold_raw[t["idx"]] and t["kind"] != "basket_change")
    gf0 = bk.gf.copy()
    bk.gf[raw] = bk.g[raw]                       # the close in place of the raw OHLC4
    alt_nav = E.simulate(bk, idx, s, E.PRIMARY, gw=gw)
    sa = E.stats(alt_nav)
    bk.gf[:] = gf0
    rows.append({"book": p, "cost_bps": E.PRIMARY, "raw_fill_sessions_in_window": int(raw.sum()), "rule_trades_on_raw_fill_sessions": int(n_raw_trades),
                 "rule_cagr_pct": round(100 * sb["cagr"], 4), "close_fill_cagr_pct": round(100 * sa["cagr"], 4),
                 "change_cagr_pp": round(100 * (sa["cagr"] - sb["cagr"]), 4),
                 "rule_max_dd_pct": round(100 * sb["max_dd"], 4), "close_fill_max_dd_pct": round(100 * sa["max_dd"], 4),
                 "change_max_dd_pp": round(100 * (sa["max_dd"] - sb["max_dd"]), 4)})
    if p == "SCMO_0003":
        ranges = [str(d.date()) for d in bk.cal[raw]]
out = pd.DataFrame(rows)
out.to_csv(ev / "r7_raw_fill.csv", index=False)
print(out.to_string(index=False))
print("raw-fill sessions:", len(ranges), ranges[0], "->", ranges[-1])
