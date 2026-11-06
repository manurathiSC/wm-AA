# -*- coding: utf-8 -*-
"""
Sweep the Microcap band's upper bound against real index membership.

The 501-750 band scored 68% recall on Nifty Microcap 250 -- weak enough that
it is mis-specification, not noise. NSE's published methodology says why.
Microcap 250 is "the top 250 companies beyond the Nifty 500", which would be
ranks 501-750, *but* a constituent must also rank inside the top 1000 on both
six-month average turnover and market cap and must have traded on at least 90%
of the last six months' sessions. Names inside 501-750 that fail those filters
are skipped and replaced by lower-ranked ones, so the realised membership
reaches deeper than 750 even though the nominal band does not. That is exactly
the 62-of-250 overflow observed on 2026-08-01.

So the fix is to widen the upper bound and let the data choose it. Only the
Microcap ceiling moves; 1-100 / 101-250 / 251-500 are pinned to Nifty 100 /
Midcap 150 / Nifty 500, which the methodology confirms. A consequence worth
stating up front: because the Smallcap band is untouched, **Smallcap recall is
invariant across this sweep by construction** -- the "Smallcap recall must not
drop more than 1 point" guard cannot bind. It is reported anyway, to show it.

Scoring population is the full ranked universe at each snapshot, not just the
750 index members. A name predicted Microcap that belongs to no index is a
false positive and has to count as one, otherwise precision is measured only
among names already known to be members and widening the band looks free.

Ground truth is the five `index_constituents_monthly` snapshots
(2026-04-09 -> 2026-08-01). Production's `mcat` cannot referee this: it folds
Micro into SCAP.

Writes `evidence/segment_v1/band_sweep.csv` and `band_sweep_confusion.csv`.
"""

from __future__ import annotations

import pandas as pd

from classify_validate import index_membership
from common import EVIDENCE_DIR
from mcap_ranks import load_cache

EVIDENCE_SUBDIR = EVIDENCE_DIR / "segment_v1"

# Fixed boundaries, confirmed against NSE methodology.
LARGE_HI, MID_HI, SMALL_HI = 100, 250, 500

# Candidate Microcap ceilings. 1000 is NSE's own eligibility ceiling for the
# index; `None` means unbounded (everything past 500 is Microcap).
CANDIDATE_CEILINGS: list[int | None] = [750, 900, 1000, 1250, None]

BUCKETS = ["Largecap", "Midcap", "Smallcap", "Microcap"]
UNKNOWN = "Unknown"


def label(ceiling: int | None) -> str:
    return f"501-{ceiling}" if ceiling is not None else "501+ (unbounded)"


def band_of(rank: int, micro_ceiling: int | None) -> str:
    if rank <= LARGE_HI:
        return "Largecap"
    if rank <= MID_HI:
        return "Midcap"
    if rank <= SMALL_HI:
        return "Smallcap"
    if micro_ceiling is None or rank <= micro_ceiling:
        return "Microcap"
    return UNKNOWN


def _truth_at(membership: pd.DataFrame, snap: pd.Timestamp) -> dict[str, str]:
    g = membership[membership["snapshot_date"] == snap]
    return dict(zip(g["symbol"], g["category"]))


def _snapshot_asof(snaps, asof):
    prior = [d for d in snaps if d <= asof]
    return prior[-1] if prior else None


def score(ranks: pd.DataFrame, membership: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Per-ceiling, per-bucket precision / recall / F1, averaged over snapshots."""
    rank_snaps = sorted(ranks["snapshot_date"].unique())
    by_snap = {d: g for d, g in ranks.groupby("snapshot_date")}

    rows, conf_rows = [], []
    for ceiling in CANDIDATE_CEILINGS:
        per_snap = []
        for snap in sorted(membership["snapshot_date"].unique()):
            rsnap = _snapshot_asof(rank_snaps, snap)
            if rsnap is None:
                continue
            g = by_snap[rsnap]
            pred = pd.Series(
                [band_of(r, ceiling) for r in g["rank"]], index=g["ticker"].values
            )
            truth_map = _truth_at(membership, snap)
            truth = pd.Series(
                [truth_map.get(t, UNKNOWN) for t in pred.index], index=pred.index
            )

            rec = {"snapshot_date": snap, "n_universe": len(pred)}
            for b in BUCKETS + [UNKNOWN]:
                tp = int(((pred == b) & (truth == b)).sum())
                fp = int(((pred == b) & (truth != b)).sum())
                fn = int(((pred != b) & (truth == b)).sum())
                prec = tp / (tp + fp) if tp + fp else float("nan")
                recl = tp / (tp + fn) if tp + fn else float("nan")
                f1 = (2 * prec * recl / (prec + recl)
                      if prec == prec and recl == recl and prec + recl else float("nan"))
                rec[f"precision_{b}"] = prec
                rec[f"recall_{b}"] = recl
                rec[f"f1_{b}"] = f1
                rec[f"n_pred_{b}"] = int((pred == b).sum())
            rec["accuracy_4bucket_members"] = float(
                (pred[truth != UNKNOWN] == truth[truth != UNKNOWN]).mean()
            )
            rec["unknown_share"] = float((pred == UNKNOWN).mean())
            per_snap.append(rec)

            if snap == max(membership["snapshot_date"]):
                c = pd.crosstab(truth, pred)
                c.index.name, c.columns.name = "truth", "predicted"
                conf_rows.append(c.reset_index().assign(band=label(ceiling)))

        d = pd.DataFrame(per_snap)
        agg = d.drop(columns=["snapshot_date"]).mean(numeric_only=True).to_dict()
        agg["band"] = label(ceiling)
        agg["micro_ceiling"] = ceiling if ceiling is not None else -1
        agg["n_snapshots"] = len(d)
        rows.append(agg)

    out = pd.DataFrame(rows)
    lead = ["band", "micro_ceiling", "n_snapshots"]
    return out[lead + [c for c in out.columns if c not in lead]], pd.concat(
        conf_rows, ignore_index=True
    )


def choose(sweep: pd.DataFrame, tol: float = 0.01) -> tuple[str, pd.DataFrame]:
    """
    Maximise Microcap F1 subject to Smallcap recall not falling more than
    `tol` below its best value across the sweep.
    """
    best_small = sweep["recall_Smallcap"].max()
    ok = sweep[sweep["recall_Smallcap"] >= best_small - tol].copy()
    winner = ok.loc[ok["f1_Microcap"].idxmax()]
    return winner["band"], ok


def main() -> None:
    EVIDENCE_SUBDIR.mkdir(parents=True, exist_ok=True)
    ranks = load_cache("semiannual")
    membership = index_membership()

    sweep, conf = score(ranks, membership)
    sweep.to_csv(EVIDENCE_SUBDIR / "band_sweep.csv", index=False)
    conf.to_csv(EVIDENCE_SUBDIR / "band_sweep_confusion.csv", index=False)

    cols = ["band", "precision_Microcap", "recall_Microcap", "f1_Microcap",
            "recall_Smallcap", "precision_Smallcap", "recall_Largecap",
            "recall_Midcap", "accuracy_4bucket_members", "unknown_share",
            "n_pred_Microcap"]
    show = sweep[cols].copy()
    for c in cols[1:]:
        show[c] = show[c].map(lambda v: f"{v:.3f}" if v == v else "n/a")
    print("Microcap band sweep -- averaged over 5 membership snapshots")
    print(show.to_string(index=False))

    winner, eligible = choose(sweep)
    print(f"\nSmallcap recall across sweep: "
          f"{sweep['recall_Smallcap'].min():.4f} .. {sweep['recall_Smallcap'].max():.4f} "
          f"(invariant by construction -- the guard cannot bind)")
    print(f"CHOSEN BAND: {winner}")
    return winner


if __name__ == "__main__":
    main()
