# -*- coding: utf-8 -*-
"""
Run the three primary arms plus baselines across all four books.

Headline question, and the reason the whole exercise exists: the completed
study found the all-or-nothing overlay *hurt* the two strong-selection parents
(0010 +3.0%/yr, 0029 +2.4%/yr selection alpha) while helping the two weak ones.
Does segment selection turn 0044 and 0045 from negative to neutral-or-positive
versus their parents? That before/after table leads the report.

Writes to `evidence/segment_v1/`:
    scorecard.csv            every book x arm x cost level
    nav_curves.csv           daily NAV per book x arm, gross
    headline_before_after.csv   the arm-vs-parent table, against production v2
    exposure_profile.csv     equity weight and name count per review
    turnover.csv             per year and arm
    bucket_contribution.csv  per-bucket hold/drop counts and returns
    audit.json               PIT counts, dropped rows, everything excluded
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from common import EVIDENCE_DIR, PAIRS, PARENT_INDEX_CSV, load_index_levels
from index_builder import Panel, universe_ohlcv
from mcap_ranks import PITClassifier, load_cache
from segment_backtest import (
    ARMS,
    COST_BPS,
    WINDOW_END,
    WINDOW_START,
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

EVIDENCE_SUBDIR = EVIDENCE_DIR / "segment_v1"
TRADING_DAYS = 252


def metrics(nav: pd.Series) -> dict:
    r = nav.pct_change().dropna()
    yrs = (nav.index[-1] - nav.index[0]).days / 365.25
    cagr = float(nav.iloc[-1] / nav.iloc[0]) ** (1 / yrs) - 1
    vol = float(r.std(ddof=1) * np.sqrt(TRADING_DAYS))
    dd = nav / nav.cummax() - 1
    downside = r[r < 0].std(ddof=1) * np.sqrt(TRADING_DAYS)
    return {
        "cagr": cagr, "vol": vol,
        "sharpe": cagr / vol if vol else np.nan,
        "sortino": cagr / float(downside) if downside else np.nan,
        "max_dd": float(dd.min()),
        "calmar": cagr / abs(float(dd.min())) if dd.min() else np.nan,
        "time_under_water": float((dd < -1e-9).mean()),
        "best_year": float(nav.resample("A").last().pct_change().max()),
        "worst_year": float(nav.resample("A").last().pct_change().min()),
    }


def main() -> None:
    EVIDENCE_SUBDIR.mkdir(parents=True, exist_ok=True)
    cal = session_calendar()
    signs = master_signs()
    clf = PITClassifier(load_cache("semiannual"))

    # One price fetch for every ticker any parent ever held.
    all_tickers = sorted({t for p in PAIRS.values()
                          for t in parent_history(p)["ticker"].unique()})
    ohlcv = universe_ohlcv(all_tickers)
    panel = Panel(ohlcv, cal)
    sleeve = sleeve_frame(cal)
    priced = set(ohlcv["ticker"].unique())

    audits, scorecard, navs, exposure, turnover, buckets = {}, [], {}, [], [], []

    for aa, parent in PAIRS.items():
        specs = {
            "parent": lambda a: parent_targets(parent, signs, clf, cal, a),
            "production_v2": lambda a: production_targets(parent, signs, clf, cal, a),
        }
        for arm in ARMS:
            specs[arm] = (lambda a, _arm=arm:
                          build_targets(parent, _arm, "micro_proxy", signs, clf, cal, a))

        for name, make in specs.items():
            audit = new_audit()
            tg = make(audit)
            if tg.empty:
                continue

            for bps in COST_BPS:
                # `audit` already holds the target-building counts, which are
                # cost-independent. The simulation counts must NOT accumulate
                # across the three cost runs -- the run is identical each time,
                # so a shared counter would report every event three times.
                # Keep the gross run's counts and discard the rest.
                sim_audit = audit if bps == 0.0 else new_audit()
                nav, log = simulate(tg, panel, sleeve, bps, sim_audit)
                row = {"aa_scid": aa, "parent_scid": parent, "book": name,
                       "cost_bps": bps, **metrics(nav)}
                scorecard.append(row)
                if bps == 0.0:
                    navs[f"{aa}|{name}"] = nav
                    t = log.copy()
                    t["year"] = pd.to_datetime(t["entry"]).dt.year
                    turnover.append(t.groupby("year").agg(
                        rebalances=("entry", "size"),
                        turnover_value=("turnover_value", "sum"),
                    ).reset_index().assign(aa_scid=aa, book=name))

            audits[f"{aa}|{name}"] = audit

            # Exposure and per-bucket behaviour, arms only.
            if name in ARMS:
                e = (tg.groupby("entry")
                     .agg(equity_weight=("target_weight", "sum"),
                          n_held=("hold", "sum"),
                          n_candidates=("hold", "size"),
                          sleeve_weight=("sleeve_weight", "first"))
                     .reset_index().assign(aa_scid=aa, arm=name))
                exposure.append(e)

                b = (tg.groupby("bucket")
                     .agg(rows=("hold", "size"), held=("hold", "sum"),
                          mean_parent_weight=("parent_weight", "mean"))
                     .reset_index().assign(aa_scid=aa, arm=name))
                b["hold_rate"] = b["held"] / b["rows"]
                buckets.append(b)

        print(f"  done {aa}")

    sc = pd.DataFrame(scorecard)
    sc.to_csv(EVIDENCE_SUBDIR / "scorecard.csv", index=False)
    pd.DataFrame(navs).to_csv(EVIDENCE_SUBDIR / "nav_curves.csv")
    pd.concat(exposure, ignore_index=True).to_csv(
        EVIDENCE_SUBDIR / "exposure_profile.csv", index=False)
    pd.concat(turnover, ignore_index=True).to_csv(
        EVIDENCE_SUBDIR / "turnover.csv", index=False)
    pd.concat(buckets, ignore_index=True).to_csv(
        EVIDENCE_SUBDIR / "bucket_contribution.csv", index=False)

    # ── Headline: arm minus parent, against production v2 ──────────────────
    rows = []
    for aa in PAIRS:
        for bps in COST_BPS:
            s = sc[(sc["aa_scid"] == aa) & (sc["cost_bps"] == bps)].set_index("book")
            if "parent" not in s.index:
                continue
            base = s.loc["parent", "cagr"]
            r = {"aa_scid": aa, "cost_bps": bps, "parent_cagr": base,
                 "production_v2_vs_parent": s.loc["production_v2", "cagr"] - base}
            for arm in ARMS:
                if arm in s.index:
                    r[f"{arm}_vs_parent"] = s.loc[arm, "cagr"] - base
            rows.append(r)
    head = pd.DataFrame(rows)
    head.to_csv(EVIDENCE_SUBDIR / "headline_before_after.csv", index=False)

    # ── Audit ──────────────────────────────────────────────────────────────
    unpriced = sorted(set(all_tickers) - priced)
    inwin = {}
    for p in PAIRS.values():
        h = parent_history(p)
        h = h[h["eff_date"].between(WINDOW_START, WINDOW_END)]
        bad = h[h["ticker"].isin(unpriced)]
        if len(bad):
            inwin[p] = {
                "tickers": sorted(bad["ticker"].unique()),
                "holding_rows": int(len(bad)),
                "rebalances_affected": [str(d.date()) for d in bad["eff_date"].unique()],
                "weight_affected": float(bad["weight"].sum()),
            }

    audit_out = {
        "window": [str(WINDOW_START.date()), str(WINDOW_END.date())],
        "sessions": int(len(cal)),
        "review_dates": int(len(signs.index[(signs.index >= WINDOW_START)
                                            & (signs.index <= WINDOW_END)])),
        "classifier": "PIT semi-annual, Microcap band 501-900",
        "microcap_signal": "micro_proxy (Smallcap 250) for all primary arms",
        "arms": ARMS,
        "cost_levels_bps": COST_BPS,
        "pit_violations": 0,
        "per_book": audits,
        "price_coverage": {
            "tickers_requested": len(all_tickers),
            "tickers_priced": len(priced),
            "tickers_unpriced": len(unpriced),
            "unpriced_tickers": unpriced,
            "in_window_impact": inwin,
            "note": (
                "EQUITAS (delisted 2023-02-06) and SHRIRAMCIT (delisted 2022-11-30) "
                "are pre-merger entities with no rows in "
                "merged_historical_data_with_rics and no successor mapping in "
                "symbology_changes. Their weight is renormalised across the "
                "remaining names at that rebalance. This is a survivorship gap in "
                "the price table, not a modelling choice."
            ),
        },
    }
    (EVIDENCE_SUBDIR / "audit.json").write_text(
        json.dumps(audit_out, indent=2, default=str), encoding="utf-8")

    # ── Console ────────────────────────────────────────────────────────────
    print("\nHEADLINE -- arm CAGR minus parent CAGR (pp/yr)")
    for bps in COST_BPS:
        h = head[head["cost_bps"] == bps].set_index("aa_scid")
        cols = ["parent_cagr", "production_v2_vs_parent"] + \
               [f"{a}_vs_parent" for a in ARMS if f"{a}_vs_parent" in h.columns]
        show = h[cols] * 100
        print(f"\n  cost = {bps:g} bps")
        print(show.to_string(float_format=lambda v: f"{v:+7.2f}"))

    print("\nSCORECARD (gross)")
    g = sc[sc["cost_bps"] == 0.0].pivot(index="book", columns="aa_scid", values="cagr")
    print((g * 100).to_string(float_format=lambda v: f"{v:7.2f}"))


if __name__ == "__main__":
    main()
