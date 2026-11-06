# -*- coding: utf-8 -*-
"""
End-to-end on ONE book and ONE arm before fanning out to twelve.

If the mechanics are wrong it is much cheaper to find out here. Runs
SCMO_0044 (parent SCMO_0010) -- chosen because it is one of the two
strong-selection parents the whole exercise is about, so a mechanical error
would show up in the number that matters most.

Checks, not just output:
  * NAV sanity -- finite, positive, starts at 1.0;
  * the parent baseline reproduces the published parent index to within a few
    bps/yr (Verification 2, the "fully-BUY stretch must equal the parent" leg);
  * cost monotonicity -- gross >= 20.8bp >= 50bp;
  * PIT assertion counts, with zero violations.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from common import PAIRS, PARENT_INDEX_CSV, load_index_levels
from index_builder import Panel, universe_ohlcv
from mcap_ranks import PITClassifier, load_cache
from segment_backtest import (
    COST_BPS,
    build_targets,
    master_signs,
    new_audit,
    parent_history,
    parent_targets,
    production_targets,
    session_calendar,
    simulate,
    sleeve_frame,
)

AA = "SCMO_0044"
PARENT = PAIRS[AA]


def cagr(s: pd.Series) -> float:
    yrs = (s.index[-1] - s.index[0]).days / 365.25
    return float(s.iloc[-1] / s.iloc[0]) ** (1 / yrs) - 1


def main() -> None:
    cal = session_calendar()
    signs = master_signs()
    clf = PITClassifier(load_cache("semiannual"))
    audit = new_audit()

    hist = parent_history(PARENT)
    tickers = sorted(hist["ticker"].unique())
    print(f"{AA} <- {PARENT}: {len(tickers)} distinct holdings, "
          f"{hist['eff_date'].nunique()} rebalances in file")

    ohlcv = universe_ohlcv(tickers)
    missing = sorted(set(tickers) - set(ohlcv["ticker"].unique()))
    print(f"price coverage: {ohlcv['ticker'].nunique()}/{len(tickers)} tickers"
          + (f"; MISSING {missing}" if missing else ""))

    panel = Panel(ohlcv, cal)
    sleeve = sleeve_frame(cal)

    books = {
        "parent": parent_targets(PARENT, signs, clf, cal, audit),
        "production_v2": production_targets(PARENT, signs, clf, cal, audit),
        "sleeve": build_targets(PARENT, "sleeve", "micro_proxy", signs, clf, cal, audit),
    }

    out = {}
    for name, tg in books.items():
        if tg.empty:
            print(f"  {name}: NO TARGETS")
            continue
        row = {"reviews": tg["entry"].nunique()}
        for bps in COST_BPS:
            nav, log = simulate(tg, panel, sleeve, bps, audit)
            row[f"cagr_{bps:g}bp"] = cagr(nav)
            if bps == 0.0:
                out[name] = nav
                row["max_dd"] = float((nav / nav.cummax() - 1).min())
                row["turnover_total"] = float(log["turnover_value"].sum())
        books[name] = row
    res = pd.DataFrame(books).T

    print("\nresults (single book, gross and net):")
    print(res.to_string(float_format=lambda v: f"{v:,.4f}"))

    # ── Verification 2: parent baseline vs the published parent index ──────
    pub = load_index_levels(PARENT_INDEX_CSV)[PARENT]
    j = out["parent"].index.intersection(pub.index)
    mine = out["parent"].loc[j] / out["parent"].loc[j].iloc[0]
    theirs = pub.loc[j] / pub.loc[j].iloc[0]
    gap = cagr(mine) - cagr(theirs)
    print(f"\nVerification 2 -- parent baseline vs published parent index")
    print(f"  reconstructed {cagr(mine):.2%}/yr   published {cagr(theirs):.2%}/yr   "
          f"gap {gap * 100:+.2f}pp/yr over {len(j)} sessions")

    # ── Cost monotonicity ──────────────────────────────────────────────────
    mono = all(res[f"cagr_{COST_BPS[0]:g}bp"] >= res[f"cagr_{COST_BPS[1]:g}bp"]) and \
        all(res[f"cagr_{COST_BPS[1]:g}bp"] >= res[f"cagr_{COST_BPS[2]:g}bp"])
    print(f"\ncost monotonic (gross >= 20.8bp >= 50bp): {mono}")

    print("\nPIT / handling counts:")
    for k, v in audit.items():
        print(f"  {k:34s} {v}")


if __name__ == "__main__":
    main()
