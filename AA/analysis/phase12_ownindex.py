# -*- coding: utf-8 -*-
"""
Phase 12 - the two gaps the reader found in the signal-grid section.

1. **The diagonal was missing.** `phase8_signals.signal_grid` applies every
   index's supertrend to every *parent basket*, but never to the index the
   signal is computed on. That diagonal is the cleanest reading of signal
   quality available, because it removes stock selection entirely: the only
   thing left is whether the trend rule beat buy-and-hold on its own underlying.

2. **The grid reported point-to-point returns with no dispersion.** A single
   cumulative value-add over 4.8 years cannot distinguish a rule that helped
   steadily from one that helped in a single quarter. This adds, for every cell:
   CAGR, annualised vol, Sharpe (cagr/vol, rf=0), max drawdown, per-calendar-year
   value-add, and the share of rolling 12-month windows in which the overlay beat
   the naked underlying - plus the episode-relocation null, so no return here
   ships without one.

Also emits the row/column spread decomposition of the 4x4 cross-application
grid, which the report asserted verbally ("the parent matters more") without
showing the arithmetic.

Everything uses the published weekly signals (`ST == FLB` -> BUY) exactly as
phase 8 does, applied from the session *after* the signal date, and the same
fixed 50/50 Gold BeES / cash reference sleeve so arms stay comparable.
"""

from __future__ import annotations

import argparse
import json

import numpy as np
import pandas as pd

import prices
import signals as S
import supertrend as ST
from common import (
    EVIDENCE_DIR,
    LABELS,
    PAIRS,
    ann_vol,
    cagr_from_returns,
    max_drawdown,
    wealth,
)

SEED = 1729
DRAWS = 2_000

# short key -> sheet name in the desk's indices_ohlcv.xlsx
SHEETS = {
    "nifty50": "NSEI",
    "nifty100": "Nifty100",
    "midcap100": "MC100",
    "midcap150": "NiftyMidcap150",
    "smallcap100": "SC100",
    "smallcap250": "NiftySmallcap250",
    "microcap250": "NiftyMicrocap250",
}
ORDER = ["nifty50", "nifty100", "midcap100", "midcap150",
         "smallcap100", "smallcap250", "microcap250"]


# ── shared mechanics (identical to robustness.py, restated to keep this file
#    runnable on its own) ────────────────────────────────────────────────────
def synth(w: pd.Series, r_base: pd.Series, r_sleeve: pd.Series) -> pd.Series:
    w = w.reindex(r_base.index).fillna(0.0)
    return (1.0 - w) * r_base.fillna(0.0) + w * r_sleeve.reindex(r_base.index).fillna(0.0)


def value_add_log(w, r_base, r_sleeve) -> float:
    s = synth(w, r_base, r_sleeve)
    ok = r_base.notna()
    return float((np.log1p(s[ok]) - np.log1p(r_base[ok])).sum())


def blocks_of(w: pd.Series) -> list[np.ndarray]:
    v = w.fillna(0.0).to_numpy()
    off = v > 0
    out, i = [], 0
    while i < len(off):
        if off[i]:
            j = i
            while j < len(off) and off[j]:
                j += 1
            out.append(v[i:j].copy())
            i = j
        else:
            i += 1
    return out


def place(blocks, n, rng) -> np.ndarray:
    out = np.zeros(n)
    occ = np.zeros(n, dtype=bool)
    for bi in rng.permutation(len(blocks)):
        b = blocks[bi]
        L = len(b)
        for _ in range(200):
            s = int(rng.integers(0, n - L + 1))
            if not occ[s:s + L].any():
                out[s:s + L] = b
                occ[s:s + L] = True
                break
        else:
            for s in range(n - L + 1):
                if not occ[s:s + L].any():
                    out[s:s + L] = b
                    occ[s:s + L] = True
                    break
    return out


def stats(r: pd.Series, prefix: str) -> dict:
    r = r.dropna()
    cg, vol = cagr_from_returns(r), ann_vol(r)
    return {
        f"{prefix}_cagr": cg,
        f"{prefix}_vol": vol,
        f"{prefix}_sharpe": cg / vol if vol else np.nan,
        f"{prefix}_max_dd": max_drawdown(wealth(r)),
    }


def yearly_value_add(w, r_base, r_sleeve) -> pd.Series:
    s = synth(w, r_base, r_sleeve)
    ok = r_base.notna()
    ex = (np.log1p(s[ok]) - np.log1p(r_base[ok]))
    return np.expm1(ex.groupby(ex.index.year).sum())


def rolling_hit_rate(w, r_base, r_sleeve, window: int = 252) -> tuple[float, float, float]:
    """Share of rolling 12-month windows the overlay won, and the worst/best."""
    s = synth(w, r_base, r_sleeve)
    ok = r_base.notna()
    ex = (np.log1p(s[ok]) - np.log1p(r_base[ok]))
    roll = ex.rolling(window).sum().dropna()
    if roll.empty:
        return np.nan, np.nan, np.nan
    return (float((roll > 0).mean()), float(np.expm1(roll.min())),
            float(np.expm1(roll.max())))


# ── 1. the diagonal: each index's own signal on its own level ──────────────
def own_index_test(cal, sig, sleeve, draws: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(SEED)
    yrs = (cal.max() - cal.min()).days / 365.25
    rows, curves = [], {}
    for k in ORDER:
        lvl = ST.load_index_ohlcv(SHEETS[k])["close"].reindex(cal).ffill()
        r_ix = lvl.pct_change()
        s = sig[k]
        if s.isna().all():
            continue
        # 1 = BUY (hold the index); defensive weight is the complement.
        w = (1.0 - s.ffill().fillna(1.0)).clip(0, 1)
        r_ov = synth(w, r_ix, sleeve)
        v = value_add_log(w, r_ix, sleeve)

        blocks = blocks_of(w)
        d = np.empty(draws)
        for i in range(draws):
            wr = pd.Series(place(blocks, len(cal), rng), index=cal)
            d[i] = value_add_log(wr, r_ix, sleeve)
        sd = float(d.std(ddof=1))
        hit, worst, best = rolling_hit_rate(w, r_ix, sleeve)

        rec = {"index": k, "sessions": int(r_ix.notna().sum()),
               "first_signal": s.dropna().index.min().date().isoformat(),
               "pct_defensive": float((w > 0.5).mean()),
               "episodes": len(blocks),
               "value_add_total": float(np.expm1(v)),
               "value_add_ann": float(np.expm1(v / yrs)),
               "roll12m_win_rate": hit, "roll12m_worst": worst, "roll12m_best": best}
        rec.update(stats(r_ix, "index"))
        rec.update(stats(r_ov, "overlay"))
        rec.update({
            "null_mean_return": float(np.expm1(d.mean())),
            "null_sd_log": sd,
            "percentile": float((d < v).mean()),
            "z_vs_null": (v - d.mean()) / sd if sd else np.nan,
            "mde_return": float(np.expm1(2.80 * sd)),
            "draws": draws,
        })
        rows.append(rec)

        curves[f"{k}_index"] = wealth(r_ix.fillna(0.0))
        curves[f"{k}_overlay"] = wealth(r_ov.fillna(0.0))

    return pd.DataFrame(rows), pd.DataFrame(curves, index=cal)


# ── 2. per-year and dispersion view of the existing signal x parent grid ───
def grid_time_resolved(panel, sig, sleeve) -> tuple[pd.DataFrame, pd.DataFrame]:
    yrs = (panel.index.max() - panel.index.min()).days / 365.25
    rows, yr_rows = [], []
    for k in ORDER:
        s = sig[k]
        if s.isna().all():
            continue
        w = (1.0 - s.ffill().fillna(1.0)).clip(0, 1)
        for aa_id, p_id in PAIRS.items():
            r_p = panel[f"r_{p_id}"]
            v = value_add_log(w, r_p, sleeve)
            r_ov = synth(w, r_p, sleeve)
            hit, worst, best = rolling_hit_rate(w, r_p, sleeve)
            rec = {"signal": k, "parent": LABELS[p_id],
                   "value_add_ann": float(np.expm1(v / yrs)),
                   "roll12m_win_rate": hit, "roll12m_worst": worst,
                   "roll12m_best": best}
            rec.update(stats(r_p, "parent"))
            rec.update(stats(r_ov, "overlay"))
            rows.append(rec)
            for y, val in yearly_value_add(w, r_p, sleeve).items():
                yr_rows.append({"signal": k, "parent": LABELS[p_id],
                                "year": int(y), "value_add": float(val)})
    return pd.DataFrame(rows), pd.DataFrame(yr_rows)


# ── 3. row vs column spread of the 4x4 cross-application grid ─────────────
def grid_spreads(run: str) -> pd.DataFrame:
    g = pd.read_csv(EVIDENCE_DIR / run / "cross_grid.csv")
    piv = g.pivot(index="signal_from", columns="parent", values="value_add_ann")
    rm, cm = piv.mean(axis=1), piv.mean(axis=0)
    rows = [{"axis": "signal (row)", "member": i, "mean_value_add_ann": float(v)}
            for i, v in rm.items()]
    rows += [{"axis": "parent (column)", "member": i, "mean_value_add_ann": float(v)}
             for i, v in cm.items()]
    rows += [
        {"axis": "SPREAD", "member": "row spread (best signal - worst signal)",
         "mean_value_add_ann": float(rm.max() - rm.min())},
        {"axis": "SPREAD", "member": "column spread (best parent - worst parent)",
         "mean_value_add_ann": float(cm.max() - cm.min())},
    ]
    return pd.DataFrame(rows)


# ── 4. what the fractional defensive weights cost ─────────────────────────
def fractional_weight_cost(panel, sleeves) -> pd.DataFrame:
    """
    0044 and 0045 spent 27 and 58 sessions at a *half* defensive weight rather
    than a full switch. Those sessions are not scattered: they sit inside the
    single best risk-off stretch either book had. Re-running the same signal on
    the same dates with the switch forced to complete prices the half-sizing.

    Also the cleanest demonstration that the section 4 / section 5 discrepancy
    is exactly this and nothing else: with `w` forced to 1 the value-add equals
    (1+sleeve)/(1+parent) - 1 to the decimal.
    """
    rows = []
    for aa_id, p_id in PAIRS.items():
        w = panel[f"wdef_{aa_id}"].fillna(0.0)
        r_p = panel[f"r_{p_id}"]
        off = w > 0
        half = off & (w < 0.99)
        hard = off.astype(float)
        for name, rs in sleeves.items():
            full = value_add_log(hard, r_p, rs)
            act = value_add_log(w, r_p, rs)
            ratio = ((1 + np.expm1(np.log1p(rs[off]).sum()))
                     / (1 + np.expm1(np.log1p(r_p[off]).sum())) - 1)
            rows.append({
                "aa": LABELS[aa_id], "parent": LABELS[p_id], "sleeve": name,
                "off_sessions": int(off.sum()),
                "half_weight_sessions": int(half.sum()),
                "half_window_start": half[half].index.min().date().isoformat()
                if half.any() else "",
                "half_window_end": half[half].index.max().date().isoformat()
                if half.any() else "",
                "parent_over_half_sessions": float(
                    np.expm1(np.log1p(r_p[half]).sum())) if half.any() else np.nan,
                "sleeve_over_half_sessions": float(
                    np.expm1(np.log1p(rs[half]).sum())) if half.any() else np.nan,
                "ratio_identity": float(ratio),
                "value_add_full_switch": float(np.expm1(full)),
                "value_add_actual": float(np.expm1(act)),
                "cost_of_half_sizing_pp": float(np.expm1(act) - np.expm1(full)) * 100,
            })
    return pd.DataFrame(rows)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="main")
    ap.add_argument("--draws", type=int, default=DRAWS)
    a = ap.parse_args()
    out = EVIDENCE_DIR / a.run

    panel = pd.read_csv(out / "panel_daily.csv", index_col=0, parse_dates=True)
    cal = panel.index
    sp, _ = S.all_signals()
    sig = S.daily_signals(sp, cal)

    etf = prices.defensive_prices().reindex(cal).ffill()
    gold = etf["GOLDBEES"].pct_change().fillna(0.0)
    cash = prices.cash_total_return(cal).fillna(0.0)
    sleeve = 0.5 * gold + 0.5 * cash

    sleeves = {"all cash": cash, "50/50 gold+cash": sleeve, "all gold": gold}
    own, curves = own_index_test(cal, sig, sleeve, a.draws)
    frac = fractional_weight_cost(panel, sleeves)
    gtr, gyr = grid_time_resolved(panel, sig, sleeve)
    spreads = grid_spreads(a.run)

    own.to_csv(out / "own_index_signal_test.csv", index=False)
    curves.to_csv(out / "own_index_curves.csv")
    gtr.to_csv(out / "signal_grid_dispersion.csv", index=False)
    gyr.to_csv(out / "signal_grid_yearly.csv", index=False)
    spreads.to_csv(out / "cross_grid_spreads.csv", index=False)
    frac.to_csv(out / "fractional_weight_cost.csv", index=False)

    pd.set_option("display.width", 260)
    print("=== OWN-INDEX TEST: each index's supertrend applied to itself ===")
    c = ["index", "index_cagr", "overlay_cagr", "value_add_ann", "index_sharpe",
         "overlay_sharpe", "index_max_dd", "overlay_max_dd", "pct_defensive",
         "roll12m_win_rate", "percentile", "z_vs_null", "mde_return"]
    print(own[c].round(4).to_string(index=False))

    print("=== COST OF THE HALF-WEIGHT SESSIONS ===")
    print(frac[frac.half_weight_sessions > 0][
        ["aa", "sleeve", "half_weight_sessions", "parent_over_half_sessions",
         "ratio_identity", "value_add_full_switch", "value_add_actual",
         "cost_of_half_sizing_pp"]].round(4).to_string(index=False))

    print("\n=== CROSS-GRID SPREADS ===")
    print(spreads.round(5).to_string(index=False))

    print("\n=== SIGNAL x PARENT: rolling-12m win rate ===")
    print(gtr.pivot(index="signal", columns="parent",
                    values="roll12m_win_rate").round(3).to_string())

    print("\n=== SIGNAL x PARENT value-add by calendar year (smallcap100) ===")
    print(gyr[gyr.signal == "smallcap100"]
          .pivot(index="year", columns="parent", values="value_add").round(4).to_string())

    with open(out / "phase12_summary.json", "w", encoding="utf-8") as f:
        json.dump({"own_index": own.to_dict(orient="records"),
                   "fractional_weight_cost": frac.to_dict(orient="records"),
                   "spreads": spreads.to_dict(orient="records"),
                   "grid_dispersion": gtr.to_dict(orient="records"),
                   "seed": SEED, "draws": a.draws}, f, indent=2, default=float)


if __name__ == "__main__":
    main()
