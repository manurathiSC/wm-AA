# -*- coding: utf-8 -*-
"""
Phase 11 - how holdings are assigned to market-cap buckets, and what that
assignment is worth.

This exists because the market-cap distributions reported earlier were derived
by regressing each parent's returns on index returns, and that method turned
out to be both mis-specified and unstable:

  * **Mis-specified.** Only Nifty 100 / Midcap 150 / Smallcap 250 were offered
    as factors. The parents hold a great deal of *microcap*, so that exposure
    was forced onto the nearest available factor. Adding Nifty Microcap 250
    moves parent 0003 from "93% smallcap" to 58% microcap.
  * **Unstable.** The same three-factor specification gives 0003 a 93%
    smallcap loading on one version of the index series and 73% on another.
    With R-squared of only 0.71-0.76 and highly collinear factors, the split
    between adjacent buckets is weakly identified.

The holdings-based alternative has a different and more serious limitation:
`index_constituents_monthly` holds only five snapshots, all between 2026-04-09
and 2026-08-01. There is no membership history for 2021-2025, so a
point-in-time classification of the study window is impossible from it. Any
holdings-based tag applied to 2022 uses 2026 membership, which mis-tags every
stock that changed bucket in between - and systematically so, since names that
graduated upward get recorded as larger than they were.

The churn test does clear one worry: across those five monthly snapshots Nifty
100 and Midcap 150 show *zero* turnover and the smaller indices change by one
or two names. That is real membership sampled monthly, not a monthly
re-ranking, so monthly sampling would not tag a stock into an index ahead of
the index's own semi-annual reconstitution. The concern was well founded; it
just does not apply to this table.
"""

from __future__ import annotations

import argparse
import json
import sys

import numpy as np
import pandas as pd
from scipy.optimize import minimize

import supertrend as ST
from common import CACHE_DIR, EVIDENCE_DIR, LABELS, PAIRS

sys.path.insert(0, r"c:/Users/manur/Repos/wm-aiReports/chartist-breakout-screen/fetch")

REBAL_HISTORY = (
    r"G:\.shortcut-targets-by-id\0B7f_UMMZHM_JNXljMVVXY2VPcHM\Investment Research_N"
    r"\Shubham_Shreshtha\Friday Rebalance Automation\Rebalance_history"
)

BUCKET_ORDER = ["Large Cap", "Mid Cap", "Small Cap", "Micro Cap"]
# Bucket -> the index whose supertrend represents it.
BUCKET_INDEX = {
    "Large Cap": "nifty100", "Mid Cap": "midcap150",
    "Small Cap": "smallcap250", "Micro Cap": "microcap250",
}
FACTOR_SHEETS = {
    "nifty100": "Nifty100", "midcap150": "NiftyMidcap150",
    "smallcap250": "NiftySmallcap250", "microcap250": "NiftyMicrocap250",
}


def fetch_reference(refresh: bool = False) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Index constituents and Nifty 500 prices, cached so re-runs stay offline."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cpath, npath = CACHE_DIR / "index_constituents.csv", CACHE_DIR / "nifty500_ohlcv.csv"
    if cpath.exists() and npath.exists() and not refresh:
        c = pd.read_csv(cpath, parse_dates=["snapshot_date"])
        n = pd.read_csv(npath, parse_dates=["date"])
        return c, n
    from sqlalchemy import text
    import pg_price_client as pg
    with pg._get_engine().connect() as conn:
        c = pd.read_sql(text(
            "select snapshot_date,index_name,symbol,market_cap_bucket "
            "from index_constituents_monthly"), conn)
        n = pd.read_sql(text(
            "select date,open,high,low,close,volume from "
            "merged_historical_data_with_rics where ticker='NIFTY 500' order by date"),
            conn)
    c["snapshot_date"] = pd.to_datetime(c["snapshot_date"])
    n["date"] = pd.to_datetime(n["date"])
    c.to_csv(cpath, index=False)
    n.to_csv(npath, index=False)
    return c, n


def churn_report(cons: pd.DataFrame) -> pd.DataFrame:
    """Month-over-month membership turnover: the test for re-ranking vs membership."""
    rows = []
    for idx, g in cons.groupby("index_name"):
        prev = None
        for s in sorted(g["snapshot_date"].unique()):
            cur = set(g[g["snapshot_date"] == s]["symbol"])
            rows.append({
                "index_name": idx, "snapshot": pd.Timestamp(s).date().isoformat(),
                "n": len(cur),
                "added": np.nan if prev is None else len(cur - prev),
                "removed": np.nan if prev is None else len(prev - cur),
            })
            prev = cur
    return pd.DataFrame(rows)


def holdings_classification(cons: pd.DataFrame) -> pd.DataFrame:
    """
    Parent baskets bucketed by the latest snapshot, reported per calendar year
    with the unmapped share made explicit - it is the honest measure of how far
    a 2026 snapshot can reach back.
    """
    latest = cons[cons["snapshot_date"] == cons["snapshot_date"].max()]
    bucket = dict(zip(latest["symbol"], latest["market_cap_bucket"]))
    rows = []
    for aa_id, p_id in PAIRS.items():
        p = pd.read_csv(f"{REBAL_HISTORY}\\Rebalance_history_by_scid_{p_id}.csv")
        p["eff"] = pd.to_datetime(p["availableDate"], format="%d/%m/%y %H:%M",
                                  errors="coerce")
        p = p[p["eff"].notna() & (p["eff"] >= "2021-11-01")]
        p["bucket"] = p["ticker"].map(bucket)
        for yr, g in p.groupby(p["eff"].dt.year):
            mapped = g["bucket"].dropna()
            rec = {"parent": LABELS[p_id], "year": int(yr), "holdings": len(g),
                   "unmapped_share": float(g["bucket"].isna().mean())}
            vc = mapped.value_counts(normalize=True)
            for b in BUCKET_ORDER:
                rec[b] = float(vc.get(b, 0.0))
            rows.append(rec)
        mapped = p["bucket"].dropna()
        vc = mapped.value_counts(normalize=True)
        rec = {"parent": LABELS[p_id], "year": 0, "holdings": len(p),
               "unmapped_share": float(p["bucket"].isna().mean())}
        for b in BUCKET_ORDER:
            rec[b] = float(vc.get(b, 0.0))
        rows.append(rec)
    return pd.DataFrame(rows)


def _fit(y: pd.Series, X: pd.DataFrame, keys: list[str]) -> tuple[np.ndarray, float, int]:
    d = pd.concat([y.rename("y"), X[keys]], axis=1).dropna()
    A, b = d[keys].to_numpy(), d["y"].to_numpy()
    r = minimize(lambda w: float(((A @ w - b) ** 2).sum()),
                 np.full(len(keys), 1.0 / len(keys)), method="SLSQP",
                 bounds=[(0.0, 1.0)] * len(keys),
                 constraints=[{"type": "eq", "fun": lambda w: w.sum() - 1.0}],
                 options={"maxiter": 800, "ftol": 1e-14})
    fit = A @ r.x
    ssr = float(((b - fit) ** 2).sum())
    sst = float(((b - b.mean()) ** 2).sum())
    return r.x, 1.0 - ssr / sst, int(len(d))


def regression_comparison(panel: pd.DataFrame) -> pd.DataFrame:
    """Three-factor (as published) against four-factor (adding microcap)."""
    cal = panel.index
    X = pd.DataFrame({k: ST.load_index_ohlcv(v)["close"].reindex(cal).ffill().pct_change()
                      for k, v in FACTOR_SHEETS.items()})
    K3 = ["nifty100", "midcap150", "smallcap250"]
    K4 = K3 + ["microcap250"]
    rows = []
    for aa_id, p_id in PAIRS.items():
        y = panel[f"r_{p_id}"]
        for spec, keys in (("3-factor", K3), ("4-factor", K4)):
            w, r2, n = _fit(y, X, keys)
            rec = {"parent": LABELS[p_id], "spec": spec, "r_squared": r2, "sessions": n}
            for k in K4:
                rec[k] = float(w[keys.index(k)]) if k in keys else np.nan
            rec["top_factor"] = keys[int(np.argmax(w))]
            rows.append(rec)
    return pd.DataFrame(rows)


def highest_weight_policy(regc: pd.DataFrame, hold: pd.DataFrame,
                          sgrid: pd.DataFrame) -> pd.DataFrame:
    """
    What "signal off the book's largest bucket" delivers, under each of the
    three ways of deciding what the largest bucket is.
    """
    g = sgrid.set_index(["signal", "parent"])["value_add_ann"]
    rows = []
    for aa_id, p_id in PAIRS.items():
        lab = LABELS[p_id]
        r3 = regc[(regc.parent == lab) & (regc.spec == "3-factor")].iloc[0]
        r4 = regc[(regc.parent == lab) & (regc.spec == "4-factor")].iloc[0]
        h = hold[(hold.parent == lab) & (hold.year == 0)].iloc[0]
        top_h = max(BUCKET_ORDER, key=lambda b: h[b])
        picks = {
            "3-factor regression (published)": r3["top_factor"],
            "4-factor regression (corrected)": r4["top_factor"],
            "holdings, 2026 snapshot": BUCKET_INDEX[top_h],
        }
        for how, sig in picks.items():
            rows.append({"parent": lab, "basis": how, "index_picked": sig,
                         "value_add_ann": float(g.get((sig, lab), np.nan))})
    return pd.DataFrame(rows)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="main")
    ap.add_argument("--refresh", action="store_true")
    a = ap.parse_args()
    out = EVIDENCE_DIR / a.run

    cons, n500 = fetch_reference(refresh=a.refresh)
    panel = pd.read_csv(out / "panel_daily.csv", index_col=0, parse_dates=True)
    sgrid = pd.read_csv(out / "signal_by_parent_full.csv")
    sgrid["parent"] = sgrid["parent"].astype(str).str.zfill(4)

    churn = churn_report(cons)
    hold = holdings_classification(cons)
    regc = regression_comparison(panel)
    hw = highest_weight_policy(regc, hold, sgrid)

    churn.to_csv(out / "constituent_churn.csv", index=False)
    hold.to_csv(out / "holdings_classification.csv", index=False)
    regc.to_csv(out / "regression_spec_comparison.csv", index=False)
    hw.to_csv(out / "highest_weight_policy_by_basis.csv", index=False)

    pd.set_option("display.width", 250)
    print("=== CHURN TEST: membership or monthly re-ranking? ===")
    print(churn.to_string(index=False))
    print("\n  Zero turnover in Nifty 100 / Midcap 150 across five monthly snapshots,")
    print("  one or two names in the smaller indices: real membership, not a re-ranking.")

    print("\n=== SNAPSHOT COVERAGE ===")
    print(f"  snapshots: {cons.snapshot_date.min().date()} .. "
          f"{cons.snapshot_date.max().date()}  ({cons.snapshot_date.nunique()} dates)")
    print("  no membership history before 2026-04 -> point-in-time tagging of the "
          "study window is not possible from this table")
    print(f"  NIFTY 500 prices: {n500.date.min().date()} .. {n500.date.max().date()} "
          f"({len(n500)} rows)")

    print("\n=== HOLDINGS-BASED BUCKETS (2026 snapshot applied backwards) ===")
    h = hold.copy()
    h["period"] = np.where(h.year == 0, "all", h.year.astype(str))
    print(h[["parent", "period", "holdings", "unmapped_share"] + BUCKET_ORDER]
          .round(3).to_string(index=False))

    print("\n=== REGRESSION SPEC: 3-factor vs 4-factor ===")
    print(regc[["parent", "spec", "nifty100", "midcap150", "smallcap250",
                "microcap250", "r_squared", "top_factor"]].round(3).to_string(index=False))

    print("\n=== 'USE THE HIGHEST-WEIGHT INDEX' UNDER EACH BASIS (value-add p.a.) ===")
    p = hw.pivot(index="basis", columns="parent", values="value_add_ann") * 100
    p["mean"] = p.mean(axis=1)
    print(p.round(2).to_string())

    with open(out / "phase11_summary.json", "w", encoding="utf-8") as f:
        json.dump({"churn": churn.to_dict(orient="records"),
                   "holdings": hold.to_dict(orient="records"),
                   "regression": regc.to_dict(orient="records"),
                   "highest_weight_by_basis": hw.to_dict(orient="records"),
                   "snapshot_dates": [str(x.date()) for x in
                                      sorted(cons.snapshot_date.unique())]},
                  f, indent=2, default=float)


if __name__ == "__main__":
    main()
