# -*- coding: utf-8 -*-
"""
Phase 6 — regime behaviour, time-stability, and the economics of the risk-off
windows.

The central table here is `offwindow_economics`: for the sessions each
portfolio actually spent defensive, what did the parent do, and what did the
sleeve earn instead? That is the arithmetic behind every claim about whether
the switch "worked", and it separates two very different mechanisms:

  - avoiding an equity fall   (parent return negative while out)
  - earning a better asset    (sleeve return exceeded a *rising* parent)

Also produced: per-year attribution, rolling 12-month excess over the parent,
behaviour through each parent drawdown, and how concentrated the value-add is
in calendar time.
"""

from __future__ import annotations

import argparse
import json

import numpy as np
import pandas as pd

import prices
from common import (
    EVIDENCE_DIR,
    LABELS,
    PAIRS,
    add_metrics_to_path,
    cagr_from_returns,
    max_drawdown,
    wealth,
)

add_metrics_to_path()
from etf_selector.metrics.drawdown import drawdown_episodes  # noqa: E402


def load_panel(run: str) -> pd.DataFrame:
    return pd.read_csv(EVIDENCE_DIR / run / "panel_daily.csv", index_col=0, parse_dates=True)


def offwindow_economics(panel: pd.DataFrame) -> pd.DataFrame:
    """What the parent did, and what the sleeve earned, while out of equity."""
    etf = prices.defensive_prices().reindex(panel.index).ffill()
    gold = etf["GOLDBEES"].pct_change()
    cash = prices.cash_total_return(panel.index)

    rows = []
    for aa_id, p_id in PAIRS.items():
        w = panel[f"wdef_{aa_id}"].fillna(0.0)
        off = w > 0
        r_p = panel[f"r_{p_id}"]
        r_def = panel[f"rdef_{aa_id}"]

        def cum(s: pd.Series) -> float:
            return float(np.expm1(np.log1p(s[off].fillna(0.0)).sum()))

        yrs_off = float(off.sum()) / 252.0
        rows.append(
            {
                "aa": aa_id,
                "aa_label": LABELS[aa_id],
                "parent": LABELS[p_id],
                "off_sessions": int(off.sum()),
                "off_years_equivalent": round(yrs_off, 2),
                "parent_return_while_out": cum(r_p),
                "actual_sleeve_return_while_out": cum(r_def),
                "gold_return_while_out": cum(gold),
                "cash_return_while_out": cum(cash),
                "sleeve_minus_parent": cum(r_def) - cum(r_p),
                "mechanism": (
                    "avoided an equity fall"
                    if cum(r_p) < 0
                    else "earned more than a rising parent"
                ),
            }
        )
    return pd.DataFrame(rows)


def yearly_attribution(panel: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for aa_id, p_id in PAIRS.items():
        r_aa = panel[f"r_{aa_id}"]
        r_pa = panel[f"r_{p_id}"]
        w = panel[f"wdef_{aa_id}"].fillna(0.0)
        ex = (np.log1p(r_aa) - np.log1p(r_pa)).dropna()
        wd = w.reindex(ex.index).fillna(0.0)
        off = wd > 0
        for yr in sorted(set(ex.index.year)):
            m = ex.index.year == yr
            rows.append(
                {
                    "aa": aa_id,
                    "aa_label": LABELS[aa_id],
                    "year": int(yr),
                    "aa_return": float(np.expm1(np.log1p(r_aa[r_aa.index.year == yr]).sum())),
                    "parent_return": float(np.expm1(np.log1p(r_pa[r_pa.index.year == yr]).sum())),
                    "excess": float(np.expm1(ex[m].sum())),
                    "tracking": float(np.expm1(ex[m & ~off].sum())),
                    "timing": float(np.expm1(ex[m & off].sum())),
                    "pct_defensive": float(off[m].mean()),
                }
            )
    return pd.DataFrame(rows)


def rolling_excess(panel: pd.DataFrame, window: int = 252) -> pd.DataFrame:
    out = {}
    for aa_id, p_id in PAIRS.items():
        ex = (np.log1p(panel[f"r_{aa_id}"]) - np.log1p(panel[f"r_{p_id}"])).fillna(0.0)
        out[LABELS[aa_id]] = np.expm1(ex.rolling(window).sum())
    df = pd.DataFrame(out)
    df.index.name = "date"
    return df


def parent_drawdown_behaviour(panel: pd.DataFrame, min_depth: float = 0.10) -> pd.DataFrame:
    """
    For each material drawdown in the parent, what the AA did instead. Shows
    whether the overlay actually protected during the falls.
    """
    rows = []
    for aa_id, p_id in PAIRS.items():
        r_pa = panel[f"r_{p_id}"].fillna(0.0)
        eps = drawdown_episodes(r_pa)
        if eps.empty:
            continue
        depth_col = "depth" if "depth" in eps.columns else eps.columns[-1]
        for _, e in eps.iterrows():
            depth = abs(float(e[depth_col]))
            if depth < min_depth:
                continue
            start = pd.Timestamp(e.get("peak", e.get("start")))
            end = pd.Timestamp(e.get("trough", e.get("end")))
            if pd.isna(start) or pd.isna(end) or start >= end:
                continue
            win = panel.loc[start:end].index
            if len(win) < 5:
                continue
            w = panel.loc[win, f"wdef_{aa_id}"].fillna(0.0)
            rows.append(
                {
                    "aa": aa_id,
                    "aa_label": LABELS[aa_id],
                    "parent": LABELS[p_id],
                    "peak": start.date().isoformat(),
                    "trough": end.date().isoformat(),
                    "sessions": int(len(win)),
                    "parent_drawdown": float(
                        np.expm1(np.log1p(panel.loc[win, f"r_{p_id}"].fillna(0.0)).sum())
                    ),
                    "aa_return": float(
                        np.expm1(np.log1p(panel.loc[win, f"r_{aa_id}"].fillna(0.0)).sum())
                    ),
                    "pct_of_fall_spent_defensive": float((w > 0).mean()),
                }
            )
    return pd.DataFrame(rows)


def time_concentration(panel: pd.DataFrame) -> pd.DataFrame:
    """How much of the total excess was earned in its single best quarter."""
    rows = []
    for aa_id, p_id in PAIRS.items():
        ex = (np.log1p(panel[f"r_{aa_id}"]) - np.log1p(panel[f"r_{p_id}"])).dropna()
        q = ex.groupby([ex.index.year, ex.index.quarter]).sum()
        tot = float(ex.sum())
        best = float(q.max())
        rows.append(
            {
                "aa": aa_id,
                "aa_label": LABELS[aa_id],
                "total_excess_log": tot,
                "best_quarter_log": best,
                "best_quarter": f"{q.idxmax()[0]}Q{q.idxmax()[1]}",
                "best_quarter_share_of_total": float(best / tot) if tot else np.nan,
                "quarters_positive": float((q > 0).mean()),
                "quarters": int(len(q)),
            }
        )
    return pd.DataFrame(rows)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="main")
    a = ap.parse_args()
    out = EVIDENCE_DIR / a.run
    panel = load_panel(a.run)

    off = offwindow_economics(panel)
    yr = yearly_attribution(panel)
    roll = rolling_excess(panel)
    dd = parent_drawdown_behaviour(panel)
    conc = time_concentration(panel)

    off.to_csv(out / "offwindow_economics.csv", index=False)
    yr.to_csv(out / "yearly_attribution.csv", index=False)
    roll.to_csv(out / "rolling_12m_excess.csv")
    dd.to_csv(out / "parent_drawdown_behaviour.csv", index=False)
    conc.to_csv(out / "time_concentration.csv", index=False)

    pd.set_option("display.width", 250)
    print("=== WHAT HAPPENED WHILE OUT OF EQUITY ===")
    c = ["aa_label", "parent", "off_sessions", "off_years_equivalent",
         "parent_return_while_out", "actual_sleeve_return_while_out",
         "gold_return_while_out", "cash_return_while_out", "mechanism"]
    print(off[c].round(4).to_string(index=False))

    print("\n=== YEARLY ATTRIBUTION (excess = tracking + timing, in return terms) ===")
    piv = yr.pivot(index="year", columns="aa_label", values="excess")
    print((piv * 100).round(2).to_string())
    print("\n  of which timing:")
    print((yr.pivot(index="year", columns="aa_label", values="timing") * 100).round(2).to_string())
    print("\n  of which tracking:")
    print((yr.pivot(index="year", columns="aa_label", values="tracking") * 100).round(2).to_string())

    print("\n=== TIME CONCENTRATION OF EXCESS ===")
    print(conc[["aa_label", "best_quarter", "best_quarter_share_of_total",
                "quarters_positive", "quarters"]].round(3).to_string(index=False))

    if not dd.empty:
        print("\n=== BEHAVIOUR THROUGH PARENT DRAWDOWNS (>10%) ===")
        print(dd[["aa_label", "parent", "peak", "trough", "sessions", "parent_drawdown",
                  "aa_return", "pct_of_fall_spent_defensive"]].round(3).to_string(index=False))

    with open(out / "phase6_summary.json", "w", encoding="utf-8") as f:
        json.dump(
            {
                "offwindow_economics": off.to_dict(orient="records"),
                "yearly_attribution": yr.to_dict(orient="records"),
                "time_concentration": conc.to_dict(orient="records"),
                "parent_drawdown_behaviour": dd.to_dict(orient="records"),
            },
            f, indent=2, default=float,
        )


if __name__ == "__main__":
    main()
