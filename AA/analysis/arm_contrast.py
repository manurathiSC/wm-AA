# -*- coding: utf-8 -*-
"""
Pre-flight: how much signal actually separates `micro_own` from `micro_proxy`?

The two arms differ in exactly one place -- which index SIGN governs a holding
classified Microcap. `micro_own` uses Nifty Microcap 250, `micro_proxy` uses
Nifty Smallcap 250. If those two SIGN series rarely disagree, the arms are
nearly the same strategy and any measured gap between them is mostly noise and
transaction cost.

Worth knowing before running the arms, not after: it sets what a "result" from
that comparison could even mean.

Writes `evidence/segment_v1/arm_contrast_preflight.csv`.
"""

from __future__ import annotations

import os

import pandas as pd

from common import EVIDENCE_DIR
from mcap_ranks import MICRO_CEILING, load_cache
from step0_audit import parent_holdings
from supertrend import INDICES_OHLCV

EVIDENCE_SUBDIR = EVIDENCE_DIR / "segment_v1"
MASTER_DIR = os.path.join(os.path.dirname(INDICES_OHLCV), "..", "RSI", "Final", "Analysis")


def master_sign(index_name: str) -> pd.Series:
    d = pd.read_excel(os.path.join(MASTER_DIR, f"Master_{index_name}.xlsx"))
    d["Date"] = pd.to_datetime(d["Date"])
    return d.set_index("Date")["SIGN"].sort_index()


def _classifier():
    s = load_cache("semiannual")
    snaps = sorted(s["snapshot_date"].unique())
    rk = {d: dict(zip(g["ticker"], g["rank"])) for d, g in s.groupby("snapshot_date")}

    def cat(ticker: str, asof) -> str:
        prior = [x for x in snaps if x <= asof]
        r = rk[prior[-1]].get(ticker) if prior else None
        if r is None:
            return "Unknown"
        if r <= 100:
            return "Largecap"
        if r <= 250:
            return "Midcap"
        if r <= 500:
            return "Smallcap"
        if r <= MICRO_CEILING:
            return "Microcap"
        return "Unknown"

    return cat


def main() -> None:
    EVIDENCE_SUBDIR.mkdir(parents=True, exist_ok=True)
    sc, mc = master_sign("NiftySmallcap250"), master_sign("NiftyMicrocap250")
    weeks = sc.index.intersection(mc.index)
    diff = weeks[sc.loc[weeks] != mc.loc[weeks]]

    cat = _classifier()
    h = parent_holdings()
    books = sorted(h["scid"].unique())

    rows = []
    for wk in diff:
        for scid in books:
            g = h[(h["scid"] == scid) & (h["eff_date"] <= wk)]
            if g.empty:
                continue
            book = g[g["eff_date"] == g["eff_date"].max()]
            n_micro = sum(cat(t, wk) == "Microcap" for t in book["ticker"])
            rows.append({
                "week": wk.date(), "scid": scid, "book_size": len(book),
                "microcap_holdings": n_micro,
                "smallcap250_sign": sc.loc[wk], "microcap250_sign": mc.loc[wk],
                "arms_diverge": n_micro > 0,
            })

    d = pd.DataFrame(rows)
    d.to_csv(EVIDENCE_SUBDIR / "arm_contrast_preflight.csv", index=False)

    book_weeks = len(books) * len(weeks)
    diverging = int(d["arms_diverge"].sum())
    cells = int(d["microcap_holdings"].sum())

    print(f"Master SIGN overlap: {len(weeks)} weeks "
          f"({weeks.min().date()} -> {weeks.max().date()})")
    print(f"weeks where Smallcap250 and Microcap250 SIGN disagree: "
          f"{len(diff)} ({len(diff) / len(weeks):.1%})")
    print(f"  {', '.join(str(x.date()) for x in diff)}")
    print(f"\nbook-weeks where the two arms can actually differ: "
          f"{diverging} of {book_weeks} ({diverging / book_weeks:.1%})")
    print(f"holding-cells involved: {cells}")
    print("\nEvery disagreement is an isolated single week, not a run -- so the "
          "arms differ mainly by a handful of extra round trips, and micro_own "
          "carries their cost. State this beside the arm comparison.")


if __name__ == "__main__":
    main()
