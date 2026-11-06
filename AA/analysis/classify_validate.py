# -*- coding: utf-8 -*-
"""
Validate the point-in-time cap classifier before anything is built on it.

Three checks, in increasing order of what they actually prove:

  1. **Reproduce production exactly.** `cap_classifier_v2.py` reads the latest
     `index_constituents_monthly` snapshot at run time. Re-implementing that
     lookup and replaying it against the `mcat` column that production wrote
     into 22 weekly `rebalance_{DDMMYY}.xlsx` workbooks must return 100%. If
     it does not, the harness is wrong and nothing downstream can be trusted.

  2. **Score the PIT proxy on the population that matters.** The backtest
     classifies parent-basket holdings, not the whole 750-name index universe,
     so the proxy is scored on the same 1,076 holding-rows production labelled.

  3. **Score the PIT proxy against real index membership.** Harder and more
     honest: all 750 members of the four indices on each of the five snapshots.
     This is where the Microcap band's weakness shows up, and it is the number
     to quote when describing what the classifier cannot do.

`mcat` collapses Small + Micro + Unknown into `SCAP`, so checks 1 and 2 test
the three-bucket mapping only. The four-bucket split -- which the `micro_own`
arm depends on -- is testable only in check 3, and only over 2026.

Writes `evidence/segment_v1/classifier_validation.csv` and
`classifier_confusion.csv`.
"""

from __future__ import annotations

import glob
import os
import re
import sys

import pandas as pd

from common import EVIDENCE_DIR, PG_FETCH_DIR
from mcap_ranks import CAT_TO_MCAT, INDEX_NAME_TO_CAT, PITClassifier, load_cache

EVIDENCE_SUBDIR = EVIDENCE_DIR / "segment_v1"

FRIDAY_ROOT = (
    r"G:\.shortcut-targets-by-id\0B7f_UMMZHM_JNXljMVVXY2VPcHM\Investment Research_N"
    r"\Shubham_Shreshtha\Friday Rebalance Automation"
)
# Production ran RSI_v1 through Jul-2026 and RSI from Jul-2026; both wrote the
# same per-AA sheet schema, so both are usable ground truth.
WORKBOOK_DIRS = ["RSI_v1", "RSI"]

STOCK_MCATS = {"LCAP", "MCAP", "SCAP"}


def _engine():
    p = str(PG_FETCH_DIR)
    if p not in sys.path:
        sys.path.insert(0, p)
    import pg_price_client  # noqa: PLC0415

    return pg_price_client._get_engine()


# ── Ground truth ───────────────────────────────────────────────────────────
def production_mcat() -> pd.DataFrame:
    """
    Every (date, aa_scid, ticker, mcat) row production wrote into the weekly
    rebalance workbooks. `ETF` rows are the defensive sleeve and blank rows are
    reviews that held nothing classifiable; both are dropped.
    """
    rows = []
    for sub in WORKBOOK_DIRS:
        pattern = os.path.join(FRIDAY_ROOT, sub, "Final", "Analysis", "rebalance_*.xlsx")
        for path in sorted(glob.glob(pattern)):
            base = os.path.basename(path)
            m = re.search(r"rebalance_(\d{2})(\d{2})(\d{2})\.xlsx", base)
            if not m:
                continue
            dd, mm, yy = m.groups()
            date = pd.Timestamp(f"20{yy}-{mm}-{dd}")
            book = pd.ExcelFile(path)
            for sheet in book.sheet_names:
                if not sheet.startswith("SCMO_"):
                    continue
                d = book.parse(sheet)
                if "mcat" not in d.columns or "ticker" not in d.columns:
                    continue
                d = d.assign(source=sub, workbook=base, date=date, aa_scid=sheet)
                rows.append(d[["source", "workbook", "date", "aa_scid",
                               "ticker", "mcat", "weight"]])

    gt = pd.concat(rows, ignore_index=True)
    gt["ticker"] = gt["ticker"].astype(str).str.strip().str.upper()
    return gt[gt["mcat"].isin(STOCK_MCATS)].reset_index(drop=True)


def index_membership() -> pd.DataFrame:
    """The five real `index_constituents_monthly` snapshots, as categories."""
    from sqlalchemy import text  # noqa: PLC0415

    sql = text("SELECT snapshot_date, index_name, symbol "
               "FROM public.index_constituents_monthly")
    with _engine().connect() as conn:
        d = pd.read_sql(sql, conn)
    d["snapshot_date"] = pd.to_datetime(d["snapshot_date"])
    d["symbol"] = d["symbol"].str.strip().str.upper()
    d["category"] = d["index_name"].map(INDEX_NAME_TO_CAT)
    return d.dropna(subset=["category"])


class MembershipClassifier:
    """
    Production's classifier, re-implemented: latest membership snapshot on or
    before `asof`, anything unlisted is Unknown.
    """

    def __init__(self, membership: pd.DataFrame):
        self._snaps = sorted(membership["snapshot_date"].unique())
        self._by_snap = {
            d: dict(zip(g["symbol"], g["category"]))
            for d, g in membership.groupby("snapshot_date")
        }

    def snapshot_asof(self, asof):
        prior = [d for d in self._snaps if d <= pd.Timestamp(asof)]
        return prior[-1] if prior else None

    def classify(self, ticker: str, asof) -> str:
        snap = self.snapshot_asof(asof)
        if snap is None:
            return "Unknown"
        return self._by_snap[snap].get(str(ticker).strip().upper(), "Unknown")

    def mcat(self, ticker: str, asof) -> str:
        return CAT_TO_MCAT[self.classify(ticker, asof)]


# ── Checks ─────────────────────────────────────────────────────────────────
def check_against_production(gt: pd.DataFrame, classifiers: dict) -> pd.DataFrame:
    """Per review date, share of holdings whose `mcat` each classifier gets right."""
    out = []
    for date, g in gt.groupby("date"):
        row = {"date": date, "n_holdings": len(g),
               "n_books": g["aa_scid"].nunique()}
        for name, clf in classifiers.items():
            snap = clf.snapshot_asof(date)
            pred = g["ticker"].map(lambda t, c=clf: c.mcat(t, date))
            row[f"{name}_agree"] = float((pred == g["mcat"]).mean())
            row[f"{name}_snapshot"] = None if snap is None else pd.Timestamp(snap).date()
        out.append(row)
    return pd.DataFrame(out).sort_values("date").reset_index(drop=True)


def confusion_vs_production(gt: pd.DataFrame, clf, name: str) -> pd.DataFrame:
    pred = [clf.mcat(t, d) for t, d in zip(gt["ticker"], gt["date"])]
    tab = pd.crosstab(gt["mcat"], pd.Series(pred, index=gt.index, name="predicted"))
    return tab.reset_index().assign(classifier=name)


def check_against_membership(membership: pd.DataFrame, clf, name: str) -> pd.DataFrame:
    """
    Four-bucket agreement against real index membership, snapshot by snapshot.
    Scored on the 750 index members only -- the classifier's job on names
    outside every index is trivially `Unknown`.
    """
    out = []
    for snap, g in membership.groupby("snapshot_date"):
        pred = pd.Series([clf.classify(s, snap) for s in g["symbol"]], index=g.index)
        row = {"classifier": name, "snapshot_date": snap, "n": len(g),
               "agree_4bucket": float((pred == g["category"]).mean())}
        for cat in ["Largecap", "Midcap", "Smallcap", "Microcap"]:
            sel = g["category"] == cat
            row[f"recall_{cat}"] = float((pred[sel] == cat).mean()) if sel.any() else None
        # Three-bucket view: the mapping production actually consumes.
        row["agree_3bucket"] = float(
            (pred.map(CAT_TO_MCAT) == g["category"].map(CAT_TO_MCAT)).mean()
        )
        out.append(row)
    return pd.DataFrame(out)


def main() -> None:
    EVIDENCE_SUBDIR.mkdir(parents=True, exist_ok=True)

    gt = production_mcat()
    membership = index_membership()

    classifiers = {
        "production_membership": MembershipClassifier(membership),
        "pit_semiannual": PITClassifier(load_cache("semiannual")),
        "pit_monthly": PITClassifier(load_cache("monthly")),
    }

    per_date = check_against_production(gt, classifiers)
    per_date.to_csv(EVIDENCE_SUBDIR / "classifier_validation.csv", index=False)

    conf = pd.concat(
        [confusion_vs_production(gt, c, n) for n, c in classifiers.items()],
        ignore_index=True,
    )
    conf.to_csv(EVIDENCE_SUBDIR / "classifier_confusion.csv", index=False)

    memb = pd.concat(
        [check_against_membership(membership, c, n)
         for n, c in classifiers.items() if n != "production_membership"],
        ignore_index=True,
    )
    memb.to_csv(EVIDENCE_SUBDIR / "classifier_vs_membership.csv", index=False)

    # ── Console summary ────────────────────────────────────────────────────
    print(f"ground truth: {len(gt):,} holding-rows  "
          f"{gt['date'].nunique()} review dates  "
          f"{gt['date'].min().date()} -> {gt['date'].max().date()}")
    print(f"membership:   {len(membership):,} rows  "
          f"{membership['snapshot_date'].nunique()} snapshots\n")

    print("CHECK 1+2 -- agreement with production's own mcat, on parent holdings")
    for name in classifiers:
        col = f"{name}_agree"
        w = (per_date[col] * per_date["n_holdings"]).sum() / per_date["n_holdings"].sum()
        print(f"  {name:24s} {w:7.2%}   worst date {per_date[col].min():.2%}")

    print("\nCHECK 3 -- agreement with real index membership, all 750 members")
    for name, g in memb.groupby("classifier"):
        print(f"  {name:24s} 4-bucket {g['agree_4bucket'].mean():6.2%}   "
              f"3-bucket {g['agree_3bucket'].mean():6.2%}")
        for cat in ["Largecap", "Midcap", "Smallcap", "Microcap"]:
            print(f"      recall {cat:9s} {g[f'recall_{cat}'].mean():6.2%}")

    prod = (per_date["production_membership_agree"] * per_date["n_holdings"]).sum() \
        / per_date["n_holdings"].sum()
    if prod < 1.0:
        raise SystemExit(
            f"FAIL: production classifier reproduction is {prod:.4%}, not 100%. "
            "The harness does not reproduce production -- fix before proceeding."
        )
    print("\nOK: production classifier reproduced exactly (100%).")


if __name__ == "__main__":
    main()
