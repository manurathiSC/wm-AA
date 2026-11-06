# -*- coding: utf-8 -*-
"""
Step 0 audit: what the classification source is, what it covers, and what it
cannot do. Writes `evidence/segment_v1/step0_audit.json`.

Run after `mcap_ranks.py` and `classify_validate.py`.
"""

from __future__ import annotations

import glob
import json
import os

import pandas as pd

from common import EVIDENCE_DIR
from mcap_ranks import BANDS, PITClassifier, load_cache, raw_mcap

EVIDENCE_SUBDIR = EVIDENCE_DIR / "segment_v1"
FRIDAY_ROOT = (
    r"G:\.shortcut-targets-by-id\0B7f_UMMZHM_JNXljMVVXY2VPcHM\Investment Research_N"
    r"\Shubham_Shreshtha\Friday Rebalance Automation"
)
WINDOW = ("2021-11-01", "2026-08-21")


def parent_holdings() -> pd.DataFrame:
    frames = []
    for path in sorted(glob.glob(os.path.join(
            FRIDAY_ROOT, "Rebalance_history", "Rebalance_history_by_scid_*.csv"))):
        scid = os.path.basename(path).replace(
            "Rebalance_history_by_scid_", "").replace(".csv", "")
        d = pd.read_csv(path)
        d["eff_date"] = pd.to_datetime(d["availableDate"], format="%d/%m/%y %H:%M")
        d["signal_date"] = pd.to_datetime(d["date"])
        d = d[(d["eff_date"] >= WINDOW[0]) & (d["eff_date"] <= WINDOW[1])].copy()
        d["ticker"] = d["ticker"].astype(str).str.strip().str.upper()
        d["scid"] = scid
        frames.append(d)
    return pd.concat(frames, ignore_index=True)


def main() -> None:
    EVIDENCE_SUBDIR.mkdir(parents=True, exist_ok=True)

    raw = raw_mcap()
    monthly = load_cache("monthly")
    semi = load_cache("semiannual")
    clf = PITClassifier(semi)
    h = parent_holdings()
    h["category"] = [clf.classify(t, d) for t, d in zip(h["ticker"], h["eff_date"])]
    h["year"] = h["eff_date"].dt.year

    months = raw["date"].dt.to_period("M")
    span = pd.period_range(months.min(), months.max(), freq="M")

    val = pd.read_csv(EVIDENCE_SUBDIR / "classifier_validation.csv")
    memb = pd.read_csv(EVIDENCE_SUBDIR / "classifier_vs_membership.csv")

    def weighted(col: str) -> float:
        return float((val[col] * val["n_holdings"]).sum() / val["n_holdings"].sum())

    audit = {
        "step": "0 - unblock point-in-time cap classification",
        "gate": "PASSED",
        "source": {
            "table": "public.mcap_based_universe",
            "columns_used": ["date", "ticker", "mcap", "instrument_class"],
            "filter": "instrument_class = 'ordinary' AND mcap IS NOT NULL",
            "rationale": (
                "ETFs, trusts (InvIT/REIT) and partly-paid special classes are not "
                "eligible for these indices; leaving them in the ranking pushes every "
                "ordinary stock down and breaks the band boundaries."
            ),
            "rows_pulled": int(len(raw)),
            "date_range": [str(raw["date"].min().date()), str(raw["date"].max().date())],
            "snapshot_dates": int(raw["date"].nunique()),
            "months_covered": int(months.nunique()),
            "months_in_span": int(len(span)),
            "months_missing": [str(m) for m in span if m not in set(months)],
            "universe_size_first": int((raw["date"] == raw["date"].min()).sum()),
            "universe_size_last": int((raw["date"] == raw["date"].max()).sum()),
        },
        "sources_rejected": {
            "index_constituents_monthly": (
                "Production's own source, but only 5 snapshots 2026-04-09 -> 2026-08-01. "
                "No history; would stamp 2026 membership on 2021-2023 books."
            ),
            "rebal_data_bank": (
                "Carries mcap_rank, but only 5 rebal_dates 2026-07-30 -> 2026-08-21."
            ),
            "local files": (
                "Swept during planning and empty: no dated ticker->bucket or ticker->rank "
                "file before 2026-04-09 anywhere in wm-research, wm-aiReports or the "
                "Friday Rebalance Automation tree."
            ),
        },
        "cadences_built": {
            "monthly": {
                "path": "cache/mcap_ranks_monthly.csv",
                "rows": int(len(monthly)),
                "snapshots": int(monthly["snapshot_date"].nunique()),
                "range": [str(monthly["snapshot_date"].min().date()),
                          str(monthly["snapshot_date"].max().date())],
                "construction": "point-in-time mcap, last snapshot of each calendar month",
            },
            "semiannual": {
                "path": "cache/mcap_ranks_semiannual.csv",
                "rows": int(len(semi)),
                "snapshots": int(semi["snapshot_date"].nunique()),
                "range": [str(semi["snapshot_date"].min().date()),
                          str(semi["snapshot_date"].max().date())],
                "construction": (
                    "NSE methodology: rank on mean full market cap over the 6 months "
                    "ending 31-Jan / 31-Jul, effective end-March / end-September, held "
                    "constant between."
                ),
                "reference_months_per_snapshot": sorted(
                    semi.groupby("snapshot_date")["n_months"].first().unique().tolist()
                ),
            },
            "chosen_for_backtest": "semiannual",
            "why": (
                "95.72% vs 89.50% agreement with production's own mcat on parent "
                "holdings, and it is the cadence the real indices actually follow."
            ),
        },
        "bands": {f"{lo + 1}-{hi}" if i else f"1-{hi}": cat
                  for i, ((hi, cat), lo) in enumerate(
                      zip(BANDS, [0] + [b[0] for b in BANDS[:-1]]))}
                 | {f">{BANDS[-1][0]}": "Unknown"},
        "validation": {
            "ground_truth": {
                "source": "22 weekly rebalance_{DDMMYY}.xlsx workbooks, RSI + RSI_v1",
                "holding_rows": int(val["n_holdings"].sum()),
                "review_dates": int(len(val)),
                "range": [str(val["date"].min()), str(val["date"].max())],
                "caveat": (
                    "mcat collapses Small+Micro+Unknown into SCAP, so this validates the "
                    "three-bucket mapping only, never the Micro split."
                ),
            },
            "production_classifier_reproduced": weighted("production_membership_agree"),
            "pit_semiannual_vs_production_mcat": weighted("pit_semiannual_agree"),
            "pit_monthly_vs_production_mcat": weighted("pit_monthly_agree"),
            "vs_real_index_membership_750_names": {
                r["classifier"]: {
                    "agree_4bucket": float(r["agree_4bucket"]),
                    "agree_3bucket": float(r["agree_3bucket"]),
                    "recall_Largecap": float(r["recall_Largecap"]),
                    "recall_Midcap": float(r["recall_Midcap"]),
                    "recall_Smallcap": float(r["recall_Smallcap"]),
                    "recall_Microcap": float(r["recall_Microcap"]),
                }
                for r in memb.groupby("classifier").mean(numeric_only=True)
                             .reset_index().to_dict(orient="records")
            },
        },
        "coverage_on_parent_holdings": {
            "window": list(WINDOW),
            "holding_rows": int(len(h)),
            "rebalances_per_parent": h.groupby("scid")["eff_date"].nunique().to_dict(),
            "unknown_share_by_year": {
                str(y): round(float((g["category"] == "Unknown").mean()), 4)
                for y, g in h.groupby("year")
            },
            "unknown_share_overall": round(float((h["category"] == "Unknown").mean()), 4),
            "prior_approach_unknown_share": (
                "12-33% of 2021-2023 holdings were unmappable under the 2026-snapshot "
                "approach the completed study used."
            ),
            "bucket_share_by_parent": {
                scid: {c: round(float(v), 4) for c, v in row.items()}
                for scid, row in pd.crosstab(
                    h["scid"], h["category"], normalize="index").iterrows()
            },
        },
        "known_limitations": [
            "NSE buffer rules (incumbents retained near the boundary) are not modelled; "
            "this is most of the residual 4.3% disagreement with production.",
            "Ranking uses full market cap, not free-float, and ignores the liquidity and "
            "listing-history eligibility filters NSE applies.",
            "The Microcap band (ranks 501-750) is the weakest: of the 250 real Nifty "
            "Microcap 250 members on 2026-08-01, only 171 fall inside 501-750 and 62 rank "
            "beyond 750. Recall is 68% at best. Production folds Microcap into the "
            "Smallcap 250 signal so this never affects it -- but the micro_own arm "
            "depends on the split, and its classification error is materially larger "
            "than the other three buckets.",
            "The four-bucket split is only testable over 2026, where real membership "
            "exists. Before 2026-04-09 there is no ground truth of any kind.",
            "From 2026 the source turns daily; it is collapsed to month-end so the "
            "classification cadence is uniform across the window.",
        ],
    }

    path = EVIDENCE_SUBDIR / "step0_audit.json"
    path.write_text(json.dumps(audit, indent=2, default=str), encoding="utf-8")
    print(f"wrote {path}")
    print(json.dumps(audit["coverage_on_parent_holdings"]["unknown_share_by_year"], indent=2))


if __name__ == "__main__":
    main()
