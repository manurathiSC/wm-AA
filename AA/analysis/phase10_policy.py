# -*- coding: utf-8 -*-
"""
Phase 10 - how the signal index should be chosen, and where the equity-leg
tracking drift actually comes from.

Two things this settles.

**Should the signal just come from the portfolio's highest-weight index?**
No. All four parents are Smallcap-250-dominated (55-93%), so that policy
collapses to "use Smallcap 250 everywhere", which is worse than what was
actually run. The better structure is to require *two* indices to agree, and
the best pair mixes a large-cap with a small-cap rather than matching the
book's own composition.

Note the two blended portfolios were already doing this without it being
described that way: with weights 0.4/0.6 and a 0.6 threshold, the weighted
score can only be 0, 0.4, 0.6 or 1, and "> 0.6" is satisfied only when both
indices are trending. Those are AND rules, not weighted averages.

**Where does the tracking drift come from?** Not from the AA rebalancing less
often than the parent - their cadences are similar and the baskets are 97-98%
identical by name. It comes from specific missed reconstitutions: the parents
reconstitute quarterly (median gap 91 days) and the AA versions intermittently
failed to adopt one, running up to 6 of 15 names different for weeks.
"""

from __future__ import annotations

import argparse
import json

import numpy as np
import pandas as pd

import phase9_improve as P9
import prices
from common import DEFENSIVE_TICKERS, EVIDENCE_DIR, LABELS, PAIRS, weight_csv

REBAL_HISTORY = (
    r"G:\.shortcut-targets-by-id\0B7f_UMMZHM_JNXljMVVXY2VPcHM\Investment Research_N"
    r"\Shubham_Shreshtha\Friday Rebalance Automation\Rebalance_history"
)

# Specification recovered in phase 8, expressed structurally: 0042/0043 run one
# index; 0044/0045 require two to agree.
REALIZED = {
    "SCMO_0042": ("single", ("smallcap100",)),
    "SCMO_0043": ("single", ("smallcap100",)),
    "SCMO_0044": ("and", ("smallcap100", "midcap150")),
    "SCMO_0045": ("and", ("midcap100", "smallcap100")),
}

SINGLES = ["nifty50", "nifty100", "nifty500_synth", "midcap100", "midcap150",
           "smallcap100", "smallcap250", "microcap250"]
PAIRS_TO_TEST = [
    ("nifty100", "smallcap250"), ("smallcap100", "smallcap250"),
    ("microcap250", "smallcap250"), ("nifty100", "smallcap100"),
    ("nifty100", "microcap250"), ("midcap150", "smallcap250"),
    ("nifty500_synth", "smallcap250"),
]


def defensive_weight(s: pd.Series) -> pd.Series:
    return (1.0 - s.fillna(1.0)).clip(0, 1)


def and_rule(sig: pd.DataFrame, keys: tuple[str, ...]) -> pd.Series:
    """Equity only if every named index is trending up."""
    out = None
    for k in keys:
        v = sig[k].fillna(1.0)
        out = v if out is None else out * v
    return defensive_weight(out)


def policy_table(sig: pd.DataFrame, panel: pd.DataFrame, sl: pd.Series) -> pd.DataFrame:
    yrs = (panel.index.max() - panel.index.min()).days / 365.25

    def va(w: pd.Series, r_p: pd.Series) -> float:
        return float(np.expm1(P9.value_add(w, r_p, sl) / yrs))

    mcap = pd.read_csv(EVIDENCE_DIR / "main" / "mcap_exposure.csv")
    top_by_aa = {}
    # Microcap 250 must be in here. Omitting it was a real bug: the "largest
    # bucket" was being picked from three factors while the blend itself is
    # fitted on four, so 0003 read smallcap250 (0.215) when its actual largest
    # bucket is microcap250 (0.583). It also left this table stale relative to
    # mcap_exposure.csv after the four-factor correction.
    cols = {"nifty100": "w_nifty100", "midcap150": "w_midcap150",
            "smallcap250": "w_smallcap250", "microcap250": "w_microcap250"}
    for _, r in mcap.iterrows():
        w = {k: r[v] for k, v in cols.items()}
        top_by_aa[r["aa"]] = (max(w, key=w.get), float(max(w.values())))

    rows = []
    for aa_id, p_id in PAIRS.items():
        r_p = panel[f"r_{p_id}"]
        kind, spec = REALIZED[aa_id]
        w_real = defensive_weight(sig[spec[0]]) if kind == "single" else and_rule(sig, spec)
        top, topw = top_by_aa[aa_id]

        rec = {
            "aa": LABELS[aa_id], "parent": LABELS[p_id],
            "realized_rule": ("single " + spec[0]) if kind == "single"
                             else "AND " + "+".join(spec),
            "realized": va(w_real, r_p),
            "highest_weight_index": top,
            "highest_weight": topw,
            "policy_highest_weight": va(defensive_weight(sig[top]), r_p),
        }
        for k in SINGLES:
            rec[f"single::{k}"] = va(defensive_weight(sig[k]), r_p)
        for a, b in PAIRS_TO_TEST:
            rec[f"and::{a}+{b}"] = va(and_rule(sig, (a, b)), r_p)
        rows.append(rec)
    return pd.DataFrame(rows)


def policy_ranking(pt: pd.DataFrame) -> pd.DataFrame:
    cols = [c for c in pt.columns
            if c.startswith(("single::", "and::")) or c in ("realized", "policy_highest_weight")]
    r = pd.DataFrame({
        "policy": cols,
        "mean_value_add_ann": [pt[c].mean() for c in cols],
        "min_value_add_ann": [pt[c].min() for c in cols],
        "books_beating_realized": [int((pt[c] > pt["realized"]).sum()) for c in cols],
    })
    return r.sort_values("mean_value_add_ann", ascending=False).reset_index(drop=True)


def basket_sync(window_start="2021-11-01", window_end="2026-08-21") -> pd.DataFrame:
    """
    How closely each AA version's equity book matched its parent's, and how
    often it missed a reconstitution.
    """
    rows = []
    for aa_id, p_id in PAIRS.items():
        p = pd.read_csv(f"{REBAL_HISTORY}\\Rebalance_history_by_scid_{p_id}.csv")
        p["eff"] = pd.to_datetime(p["availableDate"], format="%d/%m/%y %H:%M",
                                  errors="coerce")
        pb = p[p["eff"].notna()].groupby("eff")["ticker"].apply(frozenset)

        w = pd.read_csv(weight_csv(aa_id))
        w["eff"] = pd.to_datetime(w["availableDate"], format="%d/%m/%y %H:%M")
        eq = w[~w["ticker"].isin(DEFENSIVE_TICKERS)]
        ab = eq.groupby("eff")["ticker"].apply(frozenset)
        ab = ab[(ab.index >= window_start) & (ab.index <= window_end)]

        recs = []
        for d, s in ab.items():
            prior = pb[pb.index <= d]
            if len(prior) == 0 or len(s) == 0:
                continue
            cur = prior.iloc[-1]
            recs.append({"date": d, "ndiff": len(s - cur), "n": len(s)})
        r = pd.DataFrame(recs)
        pw = pb[(pb.index >= window_start) & (pb.index <= window_end)]
        gaps = (np.diff(pw.index.values).astype("timedelta64[D]").astype(int)
                if len(pw) > 1 else [0])
        off = r[r["ndiff"] >= 2]
        rows.append({
            "aa": LABELS[aa_id], "parent": LABELS[p_id],
            "parent_rebalances": int(len(pw)),
            "parent_median_gap_days": int(np.median(gaps)),
            "reviews_in_equity": int(len(r)),
            "reviews_2plus_names_off": int(len(off)),
            "pct_reviews_off": float(len(off) / len(r)) if len(r) else np.nan,
            "max_names_off": int(r["ndiff"].max()) if len(r) else 0,
            "typical_basket_size": float(r["n"].median()) if len(r) else np.nan,
            "name_match_pct": float(1 - r["ndiff"].sum() / r["n"].sum()) if len(r) else np.nan,
            "first_desync": off["date"].min().date().isoformat() if len(off) else "-",
        })
    return pd.DataFrame(rows)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="main")
    a = ap.parse_args()
    out = EVIDENCE_DIR / a.run

    panel = pd.read_csv(out / "panel_daily.csv", index_col=0, parse_dates=True)
    cal = panel.index
    etf = prices.defensive_prices().reindex(cal).ffill()
    gold = etf["GOLDBEES"].pct_change().fillna(0.0)
    cash = prices.cash_total_return(cal).fillna(0.0)
    sl = 0.5 * gold + 0.5 * cash
    sig = P9.build_signals(cal)

    pt = policy_table(sig, panel, sl)
    pr = policy_ranking(pt)
    bs = basket_sync()

    pt.to_csv(out / "signal_policy_by_book.csv", index=False)
    pr.to_csv(out / "signal_policy_ranking.csv", index=False)
    bs.to_csv(out / "basket_sync.csv", index=False)

    pd.set_option("display.width", 260)
    print("=== POLICY RANKING (mean value-add p.a. across the four books) ===")
    p = pr.copy()
    for c in ("mean_value_add_ann", "min_value_add_ann"):
        p[c] = (p[c] * 100).round(2)
    print(p.to_string(index=False))

    print("\n=== PER-BOOK: realized vs highest-weight vs best pair ===")
    show = pt[["aa", "parent", "realized_rule", "realized", "highest_weight_index",
               "policy_highest_weight", "and::nifty100+smallcap250"]].copy()
    for c in ("realized", "policy_highest_weight", "and::nifty100+smallcap250"):
        show[c] = (show[c] * 100).round(2)
    print(show.to_string(index=False))

    print("\n=== BASKET SYNC vs PARENT ===")
    print(bs.to_string(index=False))

    with open(out / "phase10_summary.json", "w", encoding="utf-8") as f:
        json.dump({"policy_by_book": pt.to_dict(orient="records"),
                   "policy_ranking": pr.to_dict(orient="records"),
                   "basket_sync": bs.to_dict(orient="records")},
                  f, indent=2, default=float)


if __name__ == "__main__":
    main()
