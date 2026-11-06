# -*- coding: utf-8 -*-
"""
Pre-registered classification-noise treatment for the `micro_own` arm.

Written and fixed BEFORE the arm is run, so the decision rule cannot be chosen
after seeing the result.

Why this exists. `micro_own` is the only arm whose result depends on the
four-bucket split being right, and the split is not right: four-bucket
agreement against real index membership is 86.69% even after the band fix
(`band_sweep.py`), so roughly one holding in seven carries the wrong bucket
label. An arm whose edge is smaller than the wobble that mislabelling induces
has not demonstrated anything, and a footnote saying "classification is
imperfect" does not settle which case this is.

The test. Take the arm's realised bucket labels, resample each one from the
empirical distribution of what its true bucket turned out to be, re-run the
arm on the perturbed labels, and repeat. That traces out the distribution of
results the arm would produce under its own measured error rate.

The error model is P(truth | predicted), estimated from the five
`index_constituents_monthly` snapshots at the chosen band. That conditional --
not P(predicted | truth) -- is the right one: in the backtest we hold a label
the classifier emitted and need the distribution of what it might really have
been.

DECISION RULE, FIXED NOW:

    Let v = the arm's point-estimate value-add versus its comparator, and let
    D = the distribution of that same statistic over >= 500 perturbed re-runs.

    If v falls INSIDE the central 80% of D (i.e. strictly between the 10th and
    90th percentiles), the arm's edge is NOT DISTINGUISHABLE FROM
    CLASSIFICATION NOISE, and is reported as such.

    If v falls OUTSIDE that interval, the edge SURVIVES the classification
    error present in the labels.

    The verdict is written to evidence either way, including when it is
    unfavourable. No alternative statistic, percentile or draw count may be
    substituted after the fact.

Two honest limitations, stated now rather than after the result:

  * The error model is estimated on 2026 only, because real membership exists
    only from 2026-04-09. It is applied to the whole 2021-2026 window on the
    assumption the error rate is stationary. It probably is not -- the
    universe grew from 1,799 to 3,367 names -- and the direction of that bias
    is not known.
  * Resampling labels independently per holding ignores the fact that
    classification errors are correlated across names near a band boundary in
    the same snapshot. Independent draws understate the spread of D, which
    makes the test ANTI-conservative: it will call an edge real slightly more
    often than it should.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from classify_validate import index_membership
from common import EVIDENCE_DIR
from mcap_ranks import MICRO_CEILING, load_cache

EVIDENCE_SUBDIR = EVIDENCE_DIR / "segment_v1"

BUCKETS = ["Largecap", "Midcap", "Smallcap", "Microcap", "Unknown"]

N_DRAWS = 500          # the pre-registered minimum
CENTRAL = 0.80         # central mass defining "not distinguishable"
LO_Q, HI_Q = (1 - CENTRAL) / 2, 1 - (1 - CENTRAL) / 2   # 0.10, 0.90
SEED = 20260825


def _band_of(rank: int) -> str:
    if rank <= 100:
        return "Largecap"
    if rank <= 250:
        return "Midcap"
    if rank <= 500:
        return "Smallcap"
    if rank <= MICRO_CEILING:
        return "Microcap"
    return "Unknown"


def confusion(ranks: pd.DataFrame | None = None,
              membership: pd.DataFrame | None = None) -> pd.DataFrame:
    """
    Raw counts of (predicted, truth) pooled over the five membership
    snapshots, scored on the full ranked universe so that names in no index
    count as truly Unknown.
    """
    ranks = load_cache("semiannual") if ranks is None else ranks
    membership = index_membership() if membership is None else membership

    rank_snaps = sorted(ranks["snapshot_date"].unique())
    by_snap = {d: g for d, g in ranks.groupby("snapshot_date")}

    frames = []
    for snap in sorted(membership["snapshot_date"].unique()):
        prior = [d for d in rank_snaps if d <= snap]
        if not prior:
            continue
        g = by_snap[prior[-1]]
        pred = pd.Series([_band_of(r) for r in g["rank"]], index=g["ticker"].values)
        tmap = dict(zip(membership[membership["snapshot_date"] == snap]["symbol"],
                        membership[membership["snapshot_date"] == snap]["category"]))
        truth = pd.Series([tmap.get(t, "Unknown") for t in pred.index], index=pred.index)
        frames.append(pd.DataFrame({"predicted": pred.values, "truth": truth.values}))

    d = pd.concat(frames, ignore_index=True)
    tab = pd.crosstab(d["predicted"], d["truth"])
    return tab.reindex(index=BUCKETS, columns=BUCKETS).fillna(0.0)


def error_model(conf: pd.DataFrame | None = None) -> pd.DataFrame:
    """
    P(truth | predicted): rows are the label the classifier emits, columns the
    distribution of what it really was. Rows sum to 1.
    """
    conf = confusion() if conf is None else conf
    totals = conf.sum(axis=1).replace(0, np.nan)
    p = conf.div(totals, axis=0)
    # A label never emitted is left as an identity row rather than NaN, so the
    # resampler is total.
    for b in BUCKETS:
        if p.loc[b].isna().all():
            p.loc[b] = [1.0 if c == b else 0.0 for c in BUCKETS]
    return p


class LabelPerturber:
    """Resample assigned bucket labels from P(truth | predicted)."""

    def __init__(self, p: pd.DataFrame | None = None, seed: int = SEED):
        self.p = error_model() if p is None else p
        self.rng = np.random.default_rng(seed)
        self._cols = list(self.p.columns)
        self._probs = {b: self.p.loc[b].to_numpy(dtype=float) for b in self.p.index}

    def perturb(self, labels) -> np.ndarray:
        """One draw: each label independently resampled from its own row."""
        labels = np.asarray(labels, dtype=object)
        out = np.empty(len(labels), dtype=object)
        for b, probs in self._probs.items():
            sel = labels == b
            n = int(sel.sum())
            if n:
                out[sel] = self.rng.choice(self._cols, size=n, p=probs)
        # Any label outside the known set passes through untouched.
        missing = out == None  # noqa: E711
        out[missing] = labels[missing]
        return out


def verdict(observed: float, draws) -> dict:
    """
    Apply the pre-registered rule. `observed` is the arm's point-estimate
    value-add; `draws` the same statistic across perturbed re-runs.
    """
    d = np.asarray([x for x in draws if x == x], dtype=float)
    lo, hi = float(np.quantile(d, LO_Q)), float(np.quantile(d, HI_Q))
    inside = bool(lo < observed < hi)
    return {
        "observed": float(observed),
        "n_draws": int(len(d)),
        "central_mass": CENTRAL,
        "p10": lo,
        "p90": hi,
        "median": float(np.median(d)),
        "sd": float(d.std(ddof=1)) if len(d) > 1 else float("nan"),
        "percentile_of_observed": float((d < observed).mean()),
        "inside_central_80": inside,
        "verdict": ("NOT DISTINGUISHABLE FROM CLASSIFICATION NOISE" if inside
                    else "SURVIVES CLASSIFICATION NOISE"),
    }


def main() -> None:
    """Materialise and freeze the error model, before any arm is run."""
    EVIDENCE_SUBDIR.mkdir(parents=True, exist_ok=True)
    conf = confusion()
    p = error_model(conf)

    conf.to_csv(EVIDENCE_SUBDIR / "micro_noise_confusion.csv")
    p.to_csv(EVIDENCE_SUBDIR / "micro_noise_error_model.csv")

    print(f"Pooled confusion over 5 membership snapshots, band 501-{MICRO_CEILING}")
    print("(rows = predicted, cols = truth)\n")
    print(conf.astype(int).to_string())
    print("\nP(truth | predicted) -- the resampling model\n")
    print(p.round(4).to_string())
    print(f"\nPre-registered: {N_DRAWS} draws, central {CENTRAL:.0%} "
          f"(p{LO_Q:.0%}-p{HI_Q:.0%}), seed {SEED}.")
    print("Rule: observed inside the interval -> NOT DISTINGUISHABLE FROM "
          "CLASSIFICATION NOISE.")


if __name__ == "__main__":
    main()
