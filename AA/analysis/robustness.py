# -*- coding: utf-8 -*-
"""
Phases 4-5 — was the timing skilled, and where do the four versions differ?

Phase 4 asks whether the switching added anything beyond simply holding less
equity, via four controls:

  1. Random-timing null   - relocate the real risk-off episodes at random,
                            preserving their count, durations and weight
                            profiles. Answers "was being out of equity good on
                            average in this window?" rather than "was the
                            timing good?".
  2. Static-mix control   - a constant equity weight equal to the realized
                            average exposure. If static matches the overlay,
                            the overlay only de-risked.
  3. Lag shift            - move the realized state +/- 1..5 weeks. An edge
                            that dies at one week was entry luck.
  4. Sleeve swap          - all-gold vs all-cash vs the 50/50 design. Gold ran
                            hard over 2024-26; this separates timing from gold
                            beta.

Phase 5 separates stock-selection edge from timing edge by applying each
portfolio's realized state series to every parent (a 4x4 grid), which needs no
re-derivation of supertrend, plus a signal-agreement matrix and a
skill-vs-opportunity breakdown.

All counterfactuals substitute the *parent* for the AA's equity leg, so they
isolate timing and are unaffected by the tracking drift measured in Phase 0.
They also use one fixed sleeve definition (50/50 Gold BeES / Liquid BeES,
which spans the whole window) so that every arm is comparable.
"""

from __future__ import annotations

import argparse
import json

import numpy as np
import pandas as pd

import prices
from common import (
    AA_SCIDS,
    EVIDENCE_DIR,
    LABELS,
    PAIRS,
    cagr_from_returns,
    max_drawdown,
    wealth,
)

SEED = 1729
DRAWS = 10_000
SESSIONS_PER_WEEK = 5


def load_panel(run: str) -> pd.DataFrame:
    return pd.read_csv(EVIDENCE_DIR / run / "panel_daily.csv", index_col=0, parse_dates=True)


def reference_sleeves(panel: pd.DataFrame) -> dict[str, pd.Series]:
    """
    Continuous sleeve return series for counterfactual arms.

    The realized sleeve is only defined while held, and its composition
    changed mid-history, so counterfactuals use the Nippon BeES pair, which
    covers the whole window, in three configurations.
    """
    etf = prices.defensive_prices().reindex(panel.index).ffill()
    gold = etf["GOLDBEES"].pct_change().fillna(0.0)
    cash = prices.cash_total_return(panel.index).fillna(0.0)
    return {
        "50/50 gold+cash": 0.5 * gold + 0.5 * cash,
        "all gold": gold,
        "all cash": cash,
    }


def synth(w: pd.Series, r_parent: pd.Series, r_sleeve: pd.Series) -> pd.Series:
    """Return of a portfolio holding the parent when risk-on and the sleeve
    when risk-off, at the given (possibly fractional) defensive weight."""
    w = w.reindex(r_parent.index).fillna(0.0)
    return (1.0 - w) * r_parent.fillna(0.0) + w * r_sleeve.reindex(r_parent.index).fillna(0.0)


def value_add_log(w: pd.Series, r_parent: pd.Series, r_sleeve: pd.Series) -> float:
    """Log outperformance of the overlaid portfolio over the naked parent."""
    s = synth(w, r_parent, r_sleeve)
    ok = r_parent.notna()
    return float((np.log1p(s[ok]) - np.log1p(r_parent[ok])).sum())


# ── Episode geometry, used by the null ─────────────────────────────────────
def episode_blocks(w: pd.Series) -> list[np.ndarray]:
    """The realized risk-off episodes as arrays of daily defensive weights,
    so a relocated episode keeps its exact duration and weight profile."""
    v = w.fillna(0.0).to_numpy()
    off = v > 0
    blocks, i = [], 0
    while i < len(off):
        if off[i]:
            j = i
            while j < len(off) and off[j]:
                j += 1
            blocks.append(v[i:j].copy())
            i = j
        else:
            i += 1
    return blocks


def random_state(blocks: list[np.ndarray], n: int, rng: np.random.Generator) -> np.ndarray:
    """
    Place the given episode blocks at random non-overlapping positions.

    Rejection-samples starts; falls back to sequential packing in the rare
    case a draw cannot be placed, which keeps the duration distribution intact
    rather than silently dropping an episode.
    """
    out = np.zeros(n)
    occupied = np.zeros(n, dtype=bool)
    order = rng.permutation(len(blocks))
    for bi in order:
        b = blocks[bi]
        L = len(b)
        placed = False
        for _ in range(200):
            s = int(rng.integers(0, n - L + 1))
            if not occupied[s : s + L].any():
                out[s : s + L] = b
                occupied[s : s + L] = True
                placed = True
                break
        if not placed:
            for s in range(n - L + 1):
                if not occupied[s : s + L].any():
                    out[s : s + L] = b
                    occupied[s : s + L] = True
                    placed = True
                    break
    return out


def random_timing_null(panel: pd.DataFrame, sleeve: pd.Series) -> pd.DataFrame:
    rng = np.random.default_rng(SEED)
    rows = []
    for aa_id, p_id in PAIRS.items():
        r_p = panel[f"r_{p_id}"]
        w = panel[f"wdef_{aa_id}"]
        blocks = episode_blocks(w)
        n = len(panel)

        observed = value_add_log(w, r_p, sleeve)

        draws = np.empty(DRAWS)
        for k in range(DRAWS):
            wr = pd.Series(random_state(blocks, n, rng), index=panel.index)
            draws[k] = value_add_log(wr, r_p, sleeve)

        # Episode-level bootstrap gives the observed statistic's own spread,
        # which is what the null sd should be judged against.
        ep_vals = np.array([value_add_log(_only(w, b), r_p, sleeve) for b in _blocks_masks(w)])
        boot = np.array(
            [rng.choice(ep_vals, size=len(ep_vals), replace=True).sum() for _ in range(2000)]
        )

        null_sd = float(draws.std(ddof=1))
        obs_sd = float(boot.std(ddof=1))
        pct = float((draws < observed).mean())
        rows.append(
            {
                "aa": aa_id,
                "aa_label": LABELS[aa_id],
                "observed_value_add_log": observed,
                "observed_value_add_return": float(np.expm1(observed)),
                "null_mean_log": float(draws.mean()),
                "null_mean_return": float(np.expm1(draws.mean())),
                "null_sd_log": null_sd,
                "percentile": pct,
                "z_vs_null": (observed - draws.mean()) / null_sd if null_sd else np.nan,
                "observed_sd_log_bootstrap": obs_sd,
                "null_sd_over_observed_sd": null_sd / obs_sd if obs_sd else np.nan,
                # Effect detectable at 5% two-sided, 80% power, given null sd.
                "mde_log": 2.80 * null_sd,
                "mde_return": float(np.expm1(2.80 * null_sd)),
                "episodes": len(blocks),
                "draws": DRAWS,
            }
        )
    return pd.DataFrame(rows)


def _blocks_masks(w: pd.Series) -> list[pd.Series]:
    v = w.fillna(0.0)
    off = v > 0
    grp = (off != off.shift()).cumsum()
    return [g for _, g in v.groupby(grp) if (g > 0).all() and len(g) > 0]


def _only(w: pd.Series, block: pd.Series) -> pd.Series:
    """The state series with just one episode active."""
    out = pd.Series(0.0, index=w.index)
    out.loc[block.index] = block.values
    return out


# ── Static-mix control ─────────────────────────────────────────────────────
def static_mix(panel: pd.DataFrame, sleeve: pd.Series) -> pd.DataFrame:
    rows = []
    for aa_id, p_id in PAIRS.items():
        r_p = panel[f"r_{p_id}"]
        w = panel[f"wdef_{aa_id}"].fillna(0.0)
        avg = float(w.mean())
        overlay = value_add_log(w, r_p, sleeve)
        static = value_add_log(pd.Series(avg, index=panel.index), r_p, sleeve)
        rows.append(
            {
                "aa": aa_id,
                "aa_label": LABELS[aa_id],
                "avg_defensive_weight": avg,
                "overlay_value_add_return": float(np.expm1(overlay)),
                "static_same_exposure_value_add_return": float(np.expm1(static)),
                "timing_premium_over_static_return": float(np.expm1(overlay - static)),
                "static_cagr": cagr_from_returns(
                    synth(pd.Series(avg, index=panel.index), r_p, sleeve)
                ),
                "overlay_cagr": cagr_from_returns(synth(w, r_p, sleeve)),
                "parent_cagr": cagr_from_returns(r_p),
            }
        )
    return pd.DataFrame(rows)


# ── Lag shift ──────────────────────────────────────────────────────────────
def lag_shift(panel: pd.DataFrame, sleeve: pd.Series, weeks=(-5, -4, -3, -2, -1, 0, 1, 2, 3, 4, 5)) -> pd.DataFrame:
    rows = []
    for aa_id, p_id in PAIRS.items():
        r_p = panel[f"r_{p_id}"]
        w = panel[f"wdef_{aa_id}"].fillna(0.0)
        for wk in weeks:
            ws = w.shift(wk * SESSIONS_PER_WEEK).fillna(0.0)
            v = value_add_log(ws, r_p, sleeve)
            rows.append(
                {
                    "aa": aa_id,
                    "aa_label": LABELS[aa_id],
                    "shift_weeks": wk,
                    "value_add_return": float(np.expm1(v)),
                    "cagr": cagr_from_returns(synth(ws, r_p, sleeve)),
                }
            )
    return pd.DataFrame(rows)


# ── Sleeve swap ────────────────────────────────────────────────────────────
def sleeve_swap(panel: pd.DataFrame, sleeves: dict[str, pd.Series]) -> pd.DataFrame:
    rows = []
    for aa_id, p_id in PAIRS.items():
        r_p = panel[f"r_{p_id}"]
        w = panel[f"wdef_{aa_id}"].fillna(0.0)
        for name, s in sleeves.items():
            v = value_add_log(w, r_p, s)
            rows.append(
                {
                    "aa": aa_id,
                    "aa_label": LABELS[aa_id],
                    "sleeve": name,
                    "value_add_return": float(np.expm1(v)),
                    "cagr": cagr_from_returns(synth(w, r_p, s)),
                    "max_drawdown": max_drawdown(wealth(synth(w, r_p, s))),
                }
            )
    return pd.DataFrame(rows)


# ── Phase 5: cross-application grid ────────────────────────────────────────
def cross_grid(panel: pd.DataFrame, sleeve: pd.Series) -> pd.DataFrame:
    """
    Apply every portfolio's realized state series to every parent.

    Row effects isolate signal quality; column effects isolate how sensitive a
    given parent was to being overlaid at all. This is what separates "0043's
    stocks" from "0043's timing" without re-deriving the signal.
    """
    rows = []
    for sig_id in AA_SCIDS:
        w = panel[f"wdef_{sig_id}"].fillna(0.0)
        for aa_id, p_id in PAIRS.items():
            r_p = panel[f"r_{p_id}"]
            v = value_add_log(w, r_p, sleeve)
            rows.append(
                {
                    "signal_from": LABELS[sig_id],
                    "parent": LABELS[p_id],
                    "own_pairing": sig_id == aa_id,
                    "value_add_return": float(np.expm1(v)),
                    "value_add_ann": float(
                        np.expm1(v / ((panel.index.max() - panel.index.min()).days / 365.25))
                    ),
                    "cagr": cagr_from_returns(synth(w, r_p, sleeve)),
                }
            )
    return pd.DataFrame(rows)


def signal_agreement(panel: pd.DataFrame) -> pd.DataFrame:
    ws = {LABELS[a]: (panel[f"wdef_{a}"].fillna(0.0) > 0).astype(int) for a in AA_SCIDS}
    keys = list(ws)
    m = pd.DataFrame(index=keys, columns=keys, dtype=float)
    for i in keys:
        for j in keys:
            m.loc[i, j] = float((ws[i] == ws[j]).mean())
    return m


def skill_vs_opportunity(panel: pd.DataFrame, sleeve: pd.Series) -> pd.DataFrame:
    """
    Split each overlay's value-add into how *bad* the avoided days were
    (avoidance edge) and how much *room* the parent gave to add value
    (its volatility). A weak, volatile parent yields more overlay value from
    the same signal quality.
    """
    rows = []
    for aa_id, p_id in PAIRS.items():
        r_p = panel[f"r_{p_id}"]
        w = panel[f"wdef_{aa_id}"].fillna(0.0)
        off = w > 0
        lp = np.log1p(r_p)
        mean_all = float(lp.dropna().mean())
        mean_off = float(lp[off].dropna().mean())
        ls = np.log1p(sleeve)
        rows.append(
            {
                "aa": aa_id,
                "aa_label": LABELS[aa_id],
                "parent": LABELS[p_id],
                "off_sessions": int(off.sum()),
                "parent_daily_mean_all_bps": mean_all * 1e4,
                "parent_daily_mean_on_off_days_bps": mean_off * 1e4,
                "avoidance_edge_bps": (mean_all - mean_off) * 1e4,
                "sleeve_daily_mean_on_off_days_bps": float(ls[off].dropna().mean()) * 1e4,
                "parent_ann_vol": float(r_p.std(ddof=1) * np.sqrt(252)),
                "parent_downside_vol": float(r_p[r_p < 0].std(ddof=1) * np.sqrt(252)),
                "parent_cagr": cagr_from_returns(r_p),
            }
        )
    return pd.DataFrame(rows)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="main")
    ap.add_argument("--draws", type=int, default=DRAWS)
    a = ap.parse_args()

    globals()["DRAWS"] = a.draws

    out = EVIDENCE_DIR / a.run
    panel = load_panel(a.run)
    sleeves = reference_sleeves(panel)
    base = sleeves["50/50 gold+cash"]

    nul = random_timing_null(panel, base)
    stat = static_mix(panel, base)
    lag = lag_shift(panel, base)
    swap = sleeve_swap(panel, sleeves)
    grid = cross_grid(panel, base)
    agree = signal_agreement(panel)
    skill = skill_vs_opportunity(panel, base)

    nul.to_csv(out / "null_random_timing.csv", index=False)
    stat.to_csv(out / "static_mix_control.csv", index=False)
    lag.to_csv(out / "lag_shift.csv", index=False)
    swap.to_csv(out / "sleeve_swap.csv", index=False)
    grid.to_csv(out / "cross_grid.csv", index=False)
    agree.to_csv(out / "signal_agreement.csv")
    skill.to_csv(out / "skill_vs_opportunity.csv", index=False)

    pd.set_option("display.width", 240)
    print("=== RANDOM-TIMING NULL (episodes relocated, count/duration preserved) ===")
    c = ["aa_label", "observed_value_add_return", "null_mean_return", "percentile",
         "z_vs_null", "null_sd_over_observed_sd", "mde_return"]
    print(nul[c].round(4).to_string(index=False))

    print("\n=== STATIC-MIX CONTROL (same average exposure, no timing) ===")
    print(stat[["aa_label", "avg_defensive_weight", "overlay_value_add_return",
                "static_same_exposure_value_add_return",
                "timing_premium_over_static_return"]].round(4).to_string(index=False))

    print("\n=== LAG SHIFT (value-add by weeks shifted) ===")
    print(lag.pivot(index="shift_weeks", columns="aa_label",
                    values="value_add_return").round(3).to_string())

    print("\n=== SLEEVE SWAP ===")
    print(swap.pivot(index="sleeve", columns="aa_label",
                     values="value_add_return").round(3).to_string())

    print("\n=== CROSS GRID: value-add p.a. (rows = signal, cols = parent) ===")
    print((grid.pivot(index="signal_from", columns="parent",
                      values="value_add_ann") * 100).round(2).to_string())

    print("\n=== SIGNAL AGREEMENT (fraction of sessions in the same state) ===")
    print(agree.round(3).to_string())

    print("\n=== SKILL vs OPPORTUNITY ===")
    print(skill[["aa_label", "parent", "off_sessions", "parent_daily_mean_all_bps",
                 "parent_daily_mean_on_off_days_bps", "avoidance_edge_bps",
                 "parent_ann_vol"]].round(2).to_string(index=False))

    with open(out / "phase45_summary.json", "w", encoding="utf-8") as f:
        json.dump(
            {
                "null": nul.to_dict(orient="records"),
                "static_mix": stat.to_dict(orient="records"),
                "sleeve_swap": swap.to_dict(orient="records"),
                "cross_grid": grid.to_dict(orient="records"),
                "skill_vs_opportunity": skill.to_dict(orient="records"),
                "lag_shift": lag.to_dict(orient="records"),
                "seed": SEED,
                "draws": DRAWS,
            },
            f, indent=2, default=float,
        )


if __name__ == "__main__":
    main()
