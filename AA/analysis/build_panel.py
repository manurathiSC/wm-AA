# -*- coding: utf-8 -*-
"""
Phase 0 — assemble and validate the analysis panel.

The study began from the assumption that an AA smallcase holds *exactly* its
parent when risk-on, which would make the AA-minus-parent spread purely a
timing effect. Testing that against the data showed it is only mostly true:
on fully risk-on sessions the median |r_AA - r_parent| is ~4e-5 (rounding),
but the tail is heavy, and the residual *compounds*. Over the window the AA
equity leg lost 3.37%/yr to its parent for SCMO_0044 and 0.82%/yr for
SCMO_0043, while SCMO_0042 gained 0.12%/yr.

So the spread has three sources, not one:

    log(AA) - log(parent)
        = SUM over risk-on  sessions of (log r_AA - log r_parent)   [TRACKING]
        + SUM over risk-off sessions of (log r_AA - log r_parent)   [TIMING]

which is additive by construction and therefore exact. This script builds the
panel those sums are taken over, measures the tracking term explicitly rather
than assuming it away, and gates on the decomposition reconciling.

Outputs (evidence/<run>/):
    panel_daily.csv     aligned levels, returns, state, sleeve weights
    identity_check.csv  tracking diagnostics per portfolio and alignment
    tracking_by_year.csv risk-on-only drift, by calendar year
    audit.json          spans, gaps, splice error, tracking, what was dropped
"""

from __future__ import annotations

import argparse
import json

import numpy as np
import pandas as pd

import prices
from common import (
    AA_INDEX_CSV,
    DEFENSIVE_TICKERS,
    EVIDENCE_DIR,
    IDENTITY_TOL,
    PAIRS,
    PARENT_INDEX_CSV,
    daily_state,
    load_index_levels,
    load_nifty50_from_index_csv,
    load_state,
)

# `availableDate` is documented as the effective/live date, so a state that
# goes live on date d governs date d's return. The alternative (governing the
# next session) is also tested and reported; it moves nothing material.
STATE_SHIFT = 0


def sleeve_return(etf: pd.DataFrame, state: pd.DataFrame, calendar: pd.DatetimeIndex) -> pd.Series:
    """
    Daily return of the defensive sleeve as actually held.

    Built from the per-instrument weights recorded in the weight files, so it
    follows the sleeve's real composition changes (gold+liquid+bond at a third
    each until Apr-2023, gold+liquid at 50/50 from Oct-2024) rather than
    assuming a fixed 50/50. Weights are renormalised within the defensive
    portion, since they sum to `w_def` and not to 1.
    """
    px = etf.reindex(calendar).ffill()
    rets = {t: px[t].pct_change() for t in sorted(DEFENSIVE_TICKERS)}

    wcols = [f"wi_{t}" for t in sorted(DEFENSIVE_TICKERS)]
    w = state[wcols].fillna(0.0)
    tot = w.sum(axis=1)

    num = sum(w[f"wi_{t}"] * rets[t].fillna(0.0) for t in sorted(DEFENSIVE_TICKERS))
    out = num.div(tot.where(tot > 0))

    # A held instrument with no price would silently bias the sleeve; catch it.
    # The first session has no prior close, so its return is legitimately NaN;
    # only gaps after that would bias the sleeve.
    missing = []
    for t in sorted(DEFENSIVE_TICKERS):
        held = w[f"wi_{t}"] > 0
        gap = int((held & rets[t].isna() & (w.index > calendar[0])).sum())
        if gap:
            missing.append({"ticker": t, "sessions_held_without_price": gap})
    out.attrs["missing_prices"] = missing
    return out


def tracking_diagnostics(r_aa: pd.Series, r_parent: pd.Series, w_def: pd.Series) -> dict:
    """
    How closely the AA's equity leg tracked its parent on fully risk-on
    sessions. Sessions adjacent to a switch are excluded, where a one-day
    execution blend is expected.
    """
    switching = (w_def != w_def.shift(1)) | (w_def != w_def.shift(-1))
    on = (w_def == 0.0) & r_aa.notna() & r_parent.notna() & ~switching
    d = (r_aa[on] - r_parent[on]).abs()
    rel = ((1.0 + r_aa[on]) / (1.0 + r_parent[on])).prod()
    years = (on.index.max() - on.index.min()).days / 365.25
    return {
        "risk_on_sessions_tested": int(on.sum()),
        "median_abs_diff": float(d.median()) if len(d) else float("nan"),
        "p95_abs_diff": float(d.quantile(0.95)) if len(d) else float("nan"),
        "max_abs_diff": float(d.max()) if len(d) else float("nan"),
        "sessions_over_tol": int((d > IDENTITY_TOL).sum()),
        "cum_tracking_drift": float(rel - 1.0),
        "ann_tracking_drift": float(rel ** (1.0 / years) - 1.0),
    }


def build(run: str, refresh: bool = False) -> tuple[pd.DataFrame, dict]:
    out_dir = EVIDENCE_DIR / run
    out_dir.mkdir(parents=True, exist_ok=True)

    aa = load_index_levels(AA_INDEX_CSV)
    parent = load_index_levels(PARENT_INDEX_CSV)
    nifty50 = load_nifty50_from_index_csv(AA_INDEX_CSV)
    if not aa.index.equals(parent.index):
        raise ValueError("AA and parent calendars differ")
    calendar = aa.index

    etf = prices.defensive_prices(refresh=refresh)
    idx = prices.mcap_indices(refresh=refresh)
    splice = prices.splice_report_cached()

    frames: dict[str, pd.Series] = {}
    diag_rows: list[dict] = []
    year_rows: list[dict] = []
    state_meta: dict[str, dict] = {}
    recon: dict[str, dict] = {}

    for aa_id, p_id in PAIRS.items():
        st_raw = daily_state(aa_id, calendar)
        st = st_raw.shift(STATE_SHIFT) if STATE_SHIFT else st_raw
        w_def = st["w_def"].fillna(0.0)

        r_aa = aa[aa_id].pct_change()
        r_pa = parent[p_id].pct_change()
        r_def = sleeve_return(etf, st.fillna(0.0), calendar)

        # Report both alignments; use STATE_SHIFT for the panel itself.
        for s in (0, 1):
            row = tracking_diagnostics(r_aa, r_pa, st_raw["w_def"].shift(s).fillna(0.0))
            row.update({"aa": aa_id, "state_shift": s, "used": s == STATE_SHIFT})
            diag_rows.append(row)

        # Exact additive split of the total log spread into three buckets.
        # Switch sessions are separated out because the AA is mid-transition
        # on them, so their excess is an execution effect rather than either
        # a tracking or a timing effect.
        la = np.log1p(r_aa)
        lp = np.log1p(r_pa)
        excess = (la - lp).dropna()
        wd = w_def.reindex(excess.index).fillna(0.0)
        switch = wd != wd.shift(1)
        switch.iloc[0] = False

        b_switch = float(excess[switch].sum())
        b_track = float(excess[~switch & (wd == 0.0)].sum())
        b_timing = float(excess[~switch & (wd > 0.0)].sum())
        total = float(excess.sum())
        recon[aa_id] = {
            "total_log_spread": total,
            "tracking_log": b_track,
            "timing_log": b_timing,
            "switch_log": b_switch,
            "switch_sessions": int(switch.sum()),
            "reconciliation_error": float(total - (b_track + b_timing + b_switch)),
        }

        drift = ((1.0 + r_aa) / (1.0 + r_pa)).where(wd.reindex(calendar) == 0.0)
        for yr, g in drift.groupby(drift.index.year):
            gg = g.dropna()
            if len(gg) == 0:
                continue
            year_rows.append(
                {"aa": aa_id, "year": int(yr), "sessions": int(len(gg)),
                 "tracking_drift": float(gg.prod() - 1.0)}
            )

        frames[f"lvl_{aa_id}"] = aa[aa_id]
        frames[f"lvl_{p_id}"] = parent[p_id]
        frames[f"r_{aa_id}"] = r_aa
        frames[f"r_{p_id}"] = r_pa
        frames[f"rdef_{aa_id}"] = r_def
        frames[f"wdef_{aa_id}"] = w_def
        for leg in ("gold", "liquid", "bond"):
            frames[f"w{leg}_{aa_id}"] = st[f"w_{leg}"].fillna(0.0)
        frames[f"stale_{aa_id}"] = st_raw["stale"].astype(int)
        frames[f"rebal_{aa_id}"] = st_raw["is_rebal"].astype(int)

        raw = load_state(aa_id)
        state_meta[aa_id] = {
            "review_dates": int(len(raw)),
            "executed_rebalances": int(raw["executed"].sum()),
            "first_effective": raw.index.min().date().isoformat(),
            "last_effective": raw.index.max().date().isoformat(),
            "sessions_state_stale": int(st_raw["stale"].sum()),
            "pct_sessions_defensive": float((w_def > 0).mean()),
            "avg_defensive_weight": float(w_def.mean()),
            "reviews_at_partial_defensive": int(((raw["w_def"] > 0.01) & (raw["w_def"] < 0.99)).sum()),
            "equity_basket_changes": int(
                _basket_changes(aa_id)
            ),
            "missing_sleeve_prices": r_def.attrs.get("missing_prices", []),
        }

    frames["lvl_nifty50"] = nifty50
    for k in idx.columns:
        frames[f"lvl_idx_{k}"] = idx[k].reindex(calendar).ffill()

    panel = pd.DataFrame(frames, index=calendar)
    panel.index.name = "date"
    panel.to_csv(out_dir / "panel_daily.csv")

    diag = pd.DataFrame(diag_rows)
    diag.to_csv(out_dir / "identity_check.csv", index=False)
    ydf = pd.DataFrame(year_rows)
    ydf.to_csv(out_dir / "tracking_by_year.csv", index=False)

    used = diag[diag["used"]].set_index("aa")
    audit = {
        "run": run,
        "window": {
            "start": calendar.min().date().isoformat(),
            "end": calendar.max().date().isoformat(),
            "sessions": int(len(calendar)),
            "years": round((calendar.max() - calendar.min()).days / 365.25, 3),
        },
        "pairs": PAIRS,
        "state_shift_used": STATE_SHIFT,
        "state": state_meta,
        "tracking": {
            "finding": (
                "The AA equity leg does not exactly replicate its parent. The "
                "residual is ~0 at the median but heavy-tailed and it "
                "compounds, so it is carried as its own attribution term "
                "rather than treated as noise."
            ),
            "per_portfolio": {
                aa_id: {
                    "ann_tracking_drift": float(used.loc[aa_id, "ann_tracking_drift"]),
                    "cum_tracking_drift": float(used.loc[aa_id, "cum_tracking_drift"]),
                    "median_abs_diff": float(used.loc[aa_id, "median_abs_diff"]),
                    "risk_on_sessions": int(used.loc[aa_id, "risk_on_sessions_tested"]),
                }
                for aa_id in PAIRS
            },
        },
        "log_reconciliation": recon,
        "index_splice": {
            "db_last_session": "2025-09-15",
            "method": "chained on returns, not levels",
            "per_index": splice.to_dict(orient="records"),
        },
        "defensive_sleeve": {
            "note": (
                "Composition changed across the history; per-instrument "
                "realized weights are used, not an assumed 50/50."
            ),
            "coverage": {
                c: {
                    "first": etf[c].first_valid_index().date().isoformat(),
                    "last": etf[c].last_valid_index().date().isoformat(),
                }
                for c in etf.columns
            },
        },
        "dropped_and_caveats": [
            "SCMO_0042's weight history ends before its NAV does; trailing "
            "sessions hold the last known state, flagged by stale_SCMO_0042.",
            "Market-cap index levels are spliced at 2025-09-15 from a second source.",
            "Gross of costs and taxes, per study scope.",
            "The 60% signal threshold is untested: the realized weight files "
            "are the only state source, so supertrend is never re-derived.",
            "On partially-defensive sessions the tracking and timing terms "
            "cannot be separated; the whole excess is booked to timing. This "
            "affects 6 reviews for SCMO_0044 and 13 for SCMO_0045, none elsewhere.",
        ],
    }
    with open(out_dir / "audit.json", "w", encoding="utf-8") as f:
        json.dump(audit, f, indent=2)
    return panel, audit


def _basket_changes(scid: str) -> int:
    w = pd.read_csv(__import__("common").weight_csv(scid))
    w["eff"] = pd.to_datetime(w["availableDate"], format="%d/%m/%y %H:%M")
    eq = w[~w["ticker"].isin(DEFENSIVE_TICKERS)]
    baskets = eq.groupby("eff")["ticker"].apply(frozenset)
    return int((baskets != baskets.shift()).sum() - 1)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="main")
    ap.add_argument("--refresh", action="store_true", help="re-fetch prices from the DB")
    a = ap.parse_args()

    panel, audit = build(a.run, refresh=a.refresh)

    print(f"panel: {panel.shape[0]} sessions x {panel.shape[1]} columns")
    w = audit["window"]
    print(f"window: {w['start']} -> {w['end']} ({w['years']}y, {w['sessions']} sessions)\n")

    print(f"{'AA':10s} {'defensive':>10s} {'reviews':>8s} {'exec':>5s} {'baskets':>8s}")
    for aa_id, m in audit["state"].items():
        print(f"{aa_id:10s} {m['pct_sessions_defensive']:9.1%} {m['review_dates']:8d} "
              f"{m['executed_rebalances']:5d} {m['equity_basket_changes']:8d}")

    print("\nAA-minus-parent log spread, split three ways (exact):")
    print(f"{'AA':10s} {'total':>9s} {'tracking':>9s} {'timing':>9s} {'switch':>9s} {'err':>10s}")
    worst = 0.0
    for aa_id, r in audit["log_reconciliation"].items():
        worst = max(worst, abs(r["reconciliation_error"]))
        print(f"{aa_id:10s} {r['total_log_spread']:+9.4f} {r['tracking_log']:+9.4f} "
              f"{r['timing_log']:+9.4f} {r['switch_log']:+9.4f} "
              f"{r['reconciliation_error']:+10.1e}")

    gaps = [g for m in audit["state"].values() for g in m["missing_sleeve_prices"]]
    if gaps:
        print(f"\nWARNING: sleeve instruments held without prices: {gaps}")

    if worst > 1e-9:
        raise SystemExit(f"GATE FAILED: log decomposition does not reconcile ({worst:.2e})")
    print("\nGATE PASSED: decomposition is exact")


if __name__ == "__main__":
    main()
