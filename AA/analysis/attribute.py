# -*- coding: utf-8 -*-
"""
Phases 1-3 — scorecard, exact attribution, and the risk-off episode ledger.

Attribution partition (exact, in log space):

    log(AA) - log(parent)  =  RISK-ON excess  +  RISK-OFF excess

The risk-on part is tracking: what the AA's equity leg gained or lost against
the parent while both were in equities, which should be zero and is not. The
risk-off part is timing: what the defensive sleeve earned instead of the
parent. Risk-off episodes partition the second term exactly, so the ledger
adds up rather than approximating.

Switch sessions are reported as an overlay diagnostic, not a third additive
bucket, since each already falls into one of the two by its own state.

Selection alpha is measured against each parent's *implied* market-cap blend:
a non-negative, sum-to-one fit of the parent's daily returns on Nifty 100 /
Midcap 150 / Smallcap 250 / **Microcap 250**.

Microcap is in that list deliberately. An earlier version of this study omitted
it, which forced genuine microcap exposure onto the nearest available factor
and badly misstated the blends - parent 0003 read 93% smallcap without it and
58% microcap with it. Because Microcap 250 also compounded fastest of the four
(+21.2% a year), omitting it understated every benchmark and so overstated
selection alpha by 2-5 points a year. See phase11_classification.py for the
comparison and for why a holdings-based classification is not available over
this window.
"""

from __future__ import annotations

import argparse
import json

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from common import (
    AA_SCIDS,
    EVIDENCE_DIR,
    LABELS,
    MCAP_INDEX_SHEETS,
    MCAP_INDICES,
    PAIRS,
    TRADING_DAYS,
    add_metrics_to_path,
    ann_vol,
    cagr_from_returns,
    max_drawdown,
    wealth,
)

add_metrics_to_path()
from etf_selector.metrics.captures import capture_statistics  # noqa: E402
from etf_selector.metrics.drawdown import ulcer_index  # noqa: E402
from etf_selector.metrics.risk_adjusted import calmar_ratio, sortino_ratio  # noqa: E402


def load_panel(run: str) -> pd.DataFrame:
    p = EVIDENCE_DIR / run / "panel_daily.csv"
    return pd.read_csv(p, index_col=0, parse_dates=True)


# ── Phase 1: scorecard ─────────────────────────────────────────────────────
def describe(returns: pd.Series, bench: pd.Series, label: str, kind: str) -> dict:
    r = returns.dropna()
    lv = wealth(r)
    cg = cagr_from_returns(r)
    vol = ann_vol(r)
    cap = capture_statistics(r, bench.reindex(r.index))
    yearly = r.groupby(r.index.year).apply(lambda s: (1 + s).prod() - 1)
    return {
        "portfolio": label,
        "kind": kind,
        "sessions": int(len(r)),
        "cagr": cg,
        "ann_vol": vol,
        "sharpe_cagr_over_vol": cg / vol if vol else np.nan,
        "sortino": sortino_ratio(r),
        "calmar": calmar_ratio(r),
        "max_drawdown": max_drawdown(lv),
        "ulcer_index": ulcer_index(r),
        "up_capture": cap.get("upside_capture"),
        "down_capture": cap.get("downside_capture"),
        "upside_beta": cap.get("upside_beta"),
        "downside_beta": cap.get("downside_beta"),
        "beta": cap.get("beta"),
        "best_year": float(yearly.max()),
        "worst_year": float(yearly.min()),
        "pct_positive_sessions": float((r > 0).mean()),
    }


def scorecard(panel: pd.DataFrame) -> pd.DataFrame:
    bench = panel["lvl_nifty50"].pct_change()
    rows = []
    for aa_id, p_id in PAIRS.items():
        rows.append(describe(panel[f"r_{aa_id}"], bench, LABELS[aa_id], "AA"))
        rows.append(describe(panel[f"r_{p_id}"], bench, LABELS[p_id], "parent"))
    rows.append(describe(bench, bench, "Nifty 50", "benchmark"))
    # Index rows come from the desk's own OHLCV workbook rather than the
    # spliced series, so the scorecard and the blend fit share one source.
    import supertrend as _st

    for k, sheet in MCAP_INDEX_SHEETS.items():
        lvl = _st.load_index_ohlcv(sheet)["close"].reindex(panel.index).ffill()
        rows.append(describe(lvl.pct_change(), bench, k, "index"))
    return pd.DataFrame(rows)


def ranking_table(sc: pd.DataFrame, attr: pd.DataFrame) -> pd.DataFrame:
    """
    The four AA versions ranked on three yardsticks side by side, because they
    disagree and the disagreement is part of the answer.
    """
    aa = sc[sc["kind"] == "AA"].set_index("portfolio")
    at = attr.set_index("aa_label")
    out = pd.DataFrame(
        {
            "cagr": aa["cagr"],
            "sharpe": aa["sharpe_cagr_over_vol"],
            "excess_vs_parent": at["total_excess_return"],
        }
    )
    for c in list(out.columns):
        out[f"rank_{c}"] = out[c].rank(ascending=False).astype(int)
    return out.sort_values("rank_cagr")


# ── Phase 2: exact attribution ─────────────────────────────────────────────
def attribution(panel: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for aa_id, p_id in PAIRS.items():
        r_aa = panel[f"r_{aa_id}"]
        r_pa = panel[f"r_{p_id}"]
        w = panel[f"wdef_{aa_id}"].fillna(0.0)
        r_def = panel[f"rdef_{aa_id}"]

        ex = (np.log1p(r_aa) - np.log1p(r_pa)).dropna()
        wd = w.reindex(ex.index).fillna(0.0)
        off = wd > 0

        risk_on = float(ex[~off].sum())
        risk_off = float(ex[off].sum())
        total = float(ex.sum())
        assert abs(total - (risk_on + risk_off)) < 1e-9

        # Inside the risk-off term: what was given up vs what was earned.
        lp = np.log1p(r_pa).reindex(ex.index)
        ld = np.log1p(r_def).reindex(ex.index)
        avoided = float(-(wd[off] * lp[off]).sum())
        carry = float((wd[off] * ld[off]).sum())

        sw = wd != wd.shift(1)
        sw.iloc[0] = False

        yrs = (ex.index.max() - ex.index.min()).days / 365.25
        rows.append(
            {
                "aa": aa_id,
                "aa_label": LABELS[aa_id],
                "parent": p_id,
                "parent_label": LABELS[p_id],
                "aa_cagr": cagr_from_returns(r_aa.dropna()),
                "parent_cagr": cagr_from_returns(r_pa.dropna()),
                "total_excess_log": total,
                "total_excess_return": np.expm1(total),
                "total_excess_ann": np.expm1(total / yrs),
                "tracking_log": risk_on,
                "tracking_return": np.expm1(risk_on),
                "tracking_ann": np.expm1(risk_on / yrs),
                "timing_log": risk_off,
                "timing_return": np.expm1(risk_off),
                "timing_ann": np.expm1(risk_off / yrs),
                "timing_avoided_equity_log": avoided,
                "timing_sleeve_carry_log": carry,
                "switch_sessions": int(sw.sum()),
                "switch_excess_log": float(ex[sw.reindex(ex.index).fillna(False)].sum()),
                "pct_sessions_defensive": float(off.mean()),
                "avg_defensive_weight": float(wd.mean()),
            }
        )
    return pd.DataFrame(rows)


def sleeve_leg_split(panel: pd.DataFrame, etf_returns: pd.DataFrame) -> pd.DataFrame:
    """
    How much of the sleeve's contribution came from gold versus cash-like
    versus bonds. Gold ran hard over 2024-26, so this separates timing skill
    from gold beta.
    """
    rows = []
    for aa_id in AA_SCIDS:
        w = panel[f"wdef_{aa_id}"].fillna(0.0)
        off = w > 0
        rec = {"aa": aa_id, "aa_label": LABELS[aa_id]}
        import prices as _prices

        for leg, cols in (
            ("gold", ["GOLDCASE", "GOLDBEES"]),
            ("liquid", None),
            ("bond", ["EBBETF0431"]),
        ):
            wl = panel[f"w{leg}_{aa_id}"].fillna(0.0)
            if leg == "liquid":
                # LIQUIDBEES distributes its yield rather than accruing it, so
                # its price return is zero; use a total-return cash series.
                rl = _prices.cash_total_return(panel.index)
            else:
                rl = etf_returns[cols].reindex(panel.index).bfill(axis=1).iloc[:, 0]
            contrib = float((wl[off] * np.log1p(rl[off].fillna(0.0))).sum())
            rec[f"{leg}_contrib_log"] = contrib
            rec[f"{leg}_contrib_return"] = float(np.expm1(contrib))
            rec[f"{leg}_avg_weight_when_off"] = float(wl[off].mean())
        rows.append(rec)
    return pd.DataFrame(rows)


def implied_mcap_blend(panel: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Fit each parent's daily returns to a non-negative, sum-to-one blend of the
    three market-cap indices. This is the market-cap distribution the
    switching signal is weighted by, recovered from returns rather than from
    membership lists (which do not exist here for midcap/smallcap).

    The parent is always fully invested in equities, so the whole history is
    usable, not just the risk-on windows.
    """
    import supertrend as _st

    X = pd.DataFrame({
        k: _st.load_index_ohlcv(s)["close"].reindex(panel.index).ffill().pct_change()
        for k, s in MCAP_INDEX_SHEETS.items()
    })[MCAP_INDICES]
    rows, blends = [], {}
    for aa_id, p_id in PAIRS.items():
        y = panel[f"r_{p_id}"]
        d = pd.concat([y.rename("y"), X], axis=1).dropna()
        A = d[MCAP_INDICES].to_numpy()
        b = d["y"].to_numpy()

        def sse(w: np.ndarray) -> float:
            return float(((A @ w - b) ** 2).sum())

        w0 = np.full(len(MCAP_INDICES), 1.0 / len(MCAP_INDICES))
        res = minimize(
            sse, w0, method="SLSQP",
            bounds=[(0.0, 1.0)] * len(MCAP_INDICES),
            constraints=[{"type": "eq", "fun": lambda w: w.sum() - 1.0}],
            options={"maxiter": 500, "ftol": 1e-14},
        )
        w = res.x
        fit = A @ w
        ss_res = float(((b - fit) ** 2).sum())
        ss_tot = float(((b - b.mean()) ** 2).sum())

        blend = pd.Series(fit, index=d.index, name=p_id)
        blends[p_id] = blend

        # Stability: refit on thirds of the sample.
        thirds = np.array_split(np.arange(len(d)), 3)
        sub = []
        for t in thirds:
            r2 = minimize(
                lambda w, A=A[t], b=b[t]: float(((A @ w - b) ** 2).sum()),
                w0, method="SLSQP", bounds=[(0.0, 1.0)] * len(MCAP_INDICES),
                constraints=[{"type": "eq", "fun": lambda w: w.sum() - 1.0}],
                options={"maxiter": 500, "ftol": 1e-14},
            )
            sub.append(r2.x)
        sub = np.array(sub)

        rec = {
            "aa": aa_id, "aa_label": LABELS[aa_id],
            "parent": p_id, "parent_label": LABELS[p_id],
            "r_squared": 1.0 - ss_res / ss_tot,
            "sessions": int(len(d)),
            "parent_cagr": cagr_from_returns(d["y"]),
            "blend_cagr": cagr_from_returns(blend),
        }
        rec["selection_alpha_ann"] = rec["parent_cagr"] - rec["blend_cagr"]
        for i, k in enumerate(MCAP_INDICES):
            rec[f"w_{k}"] = float(w[i])
            rec[f"w_{k}_range"] = float(sub[:, i].max() - sub[:, i].min())
        rows.append(rec)
    return pd.DataFrame(rows), pd.DataFrame(blends)


# ── Phase 3: risk-off episode ledger ───────────────────────────────────────
def episodes(panel: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for aa_id, p_id in PAIRS.items():
        r_aa = panel[f"r_{aa_id}"]
        r_pa = panel[f"r_{p_id}"]
        w = panel[f"wdef_{aa_id}"].fillna(0.0)
        ex = (np.log1p(r_aa) - np.log1p(r_pa)).dropna()
        wd = w.reindex(ex.index).fillna(0.0)
        off = wd > 0
        grp = (off != off.shift()).cumsum()

        n = 0
        for _, g in off.groupby(grp):
            if not g.iloc[0]:
                continue
            n += 1
            win = g.index
            rows.append(
                {
                    "aa": aa_id,
                    "aa_label": LABELS[aa_id],
                    "episode": n,
                    "start": win.min().date().isoformat(),
                    "end": win.max().date().isoformat(),
                    "sessions": int(len(win)),
                    "weeks": round(len(win) / 5.0, 1),
                    "avg_defensive_weight": float(wd.loc[win].mean()),
                    "parent_return": float(np.expm1(np.log1p(r_pa.loc[win]).sum())),
                    "aa_return": float(np.expm1(np.log1p(r_aa.loc[win]).sum())),
                    "sleeve_return": float(
                        np.expm1(np.log1p(panel[f"rdef_{aa_id}"].loc[win].fillna(0.0)).sum())
                    ),
                    "value_add_log": float(ex.loc[win].sum()),
                    "value_add_return": float(np.expm1(ex.loc[win].sum())),
                }
            )
    return pd.DataFrame(rows)


def episode_summary(ep: pd.DataFrame, attr: pd.DataFrame) -> pd.DataFrame:
    rows = []
    at = attr.set_index("aa")
    for aa_id, g in ep.groupby("aa"):
        v = g["value_add_log"]
        tot = float(v.sum())
        srt = v.abs().sort_values(ascending=False)
        top1 = float(v.loc[srt.index[0]]) if len(srt) else np.nan
        top3 = float(v.loc[srt.index[:3]].sum()) if len(srt) else np.nan
        wins = v[v > 0]
        losses = v[v < 0]
        # Cost at which the round trips would have consumed the timing gain.
        trips = len(g)
        rows.append(
            {
                "aa": aa_id,
                "aa_label": LABELS[aa_id],
                "episodes": trips,
                "median_weeks": float(g["weeks"].median()),
                "total_value_add_log": tot,
                "total_value_add_return": float(np.expm1(tot)),
                "hit_rate": float((v > 0).mean()),
                "avg_win": float(wins.mean()) if len(wins) else np.nan,
                "avg_loss": float(losses.mean()) if len(losses) else np.nan,
                "payoff_ratio": float(wins.mean() / abs(losses.mean()))
                if len(wins) and len(losses)
                else np.nan,
                "top1_share_of_total": float(top1 / tot) if tot else np.nan,
                "top3_share_of_total": float(top3 / tot) if tot else np.nan,
                "round_trips": trips,
                "breakeven_roundtrip_bps": float(1e4 * tot / trips) if trips else np.nan,
            }
        )
    return pd.DataFrame(rows)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="main")
    a = ap.parse_args()
    out = EVIDENCE_DIR / a.run
    panel = load_panel(a.run)

    import prices

    etf = prices.defensive_prices()
    etf_ret = etf.reindex(panel.index).ffill().pct_change()

    attr = attribution(panel)
    sc = scorecard(panel)
    rank = ranking_table(sc, attr)
    legs = sleeve_leg_split(panel, etf_ret)
    mcap, blends = implied_mcap_blend(panel)
    ep = episodes(panel)
    eps = episode_summary(ep, attr)

    sc.to_csv(out / "scorecard.csv", index=False)
    rank.to_csv(out / "ranking.csv")
    attr.to_csv(out / "attribution.csv", index=False)
    legs.to_csv(out / "sleeve_legs.csv", index=False)
    mcap.to_csv(out / "mcap_exposure.csv", index=False)
    blends.to_csv(out / "mcap_blend_returns.csv")
    ep.to_csv(out / "episode_ledger.csv", index=False)
    eps.to_csv(out / "episode_summary.csv", index=False)

    pd.set_option("display.width", 220)
    print("=== ATTRIBUTION: AA vs parent, exact split (annualised) ===")
    show = attr[["aa_label", "parent_label", "aa_cagr", "parent_cagr",
                 "total_excess_ann", "tracking_ann", "timing_ann"]].copy()
    for c in show.columns[2:]:
        show[c] = (show[c] * 100).round(2)
    print(show.to_string(index=False))

    print("\n=== EPISODE SUMMARY ===")
    e = eps[["aa_label", "episodes", "median_weeks", "total_value_add_return",
             "hit_rate", "payoff_ratio", "top1_share_of_total", "breakeven_roundtrip_bps"]].copy()
    e["total_value_add_return"] = (e["total_value_add_return"] * 100).round(2)
    print(e.round(3).to_string(index=False))

    print("\n=== IMPLIED MARKET-CAP BLEND (from returns) ===")
    m = mcap[["parent_label"] + [f"w_{k}" for k in MCAP_INDICES] +
             ["r_squared", "parent_cagr", "blend_cagr", "selection_alpha_ann"]].copy()
    print(m.round(4).to_string(index=False))

    print("\n=== RANKING, three lenses ===")
    print(rank.round(4).to_string())

    with open(out / "phase123_summary.json", "w", encoding="utf-8") as f:
        json.dump(
            {
                "attribution": attr.to_dict(orient="records"),
                "episode_summary": eps.to_dict(orient="records"),
                "mcap_exposure": mcap.to_dict(orient="records"),
                "sleeve_legs": legs.to_dict(orient="records"),
            },
            f, indent=2, default=float,
        )


if __name__ == "__main__":
    main()
