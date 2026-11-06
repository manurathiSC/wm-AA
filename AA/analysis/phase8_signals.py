# -*- coding: utf-8 -*-
"""
Phase 8 - what the per-index supertrend signals reveal.

Having the signals themselves (not just the realized states) makes three new
questions answerable:

  1. Which signal actually drove each portfolio? Reconciliation shows 0042 and
     0043 were driven by the Smallcap 100 supertrend alone, not a three-index
     blend, while 0044 and 0045 do use a two-index blend at a 0.6 threshold.
  2. Is 0.6 a plateau or a cliff? Sweeping the threshold on the identified
     blends tests whether the parameter was tuned or merely adequate.
  3. Is there gold-timing skill? Gold is a fixed half of the sleeve and no gold
     data enters the rule, so any concentration of gold exposure in gold's
     better periods is incidental to the equity signal. This measures the size
     of that effect and tests it against the episode-relocation null.
"""

from __future__ import annotations

import argparse
import itertools
import json

import numpy as np
import pandas as pd

import prices
import signals as S
from common import (
    AA_SCIDS,
    EVIDENCE_DIR,
    LABELS,
    PAIRS,
    cagr_from_returns,
    load_index_levels,
    max_drawdown,
    wealth,
    AA_INDEX_CSV,
)

SEED = 1729
DRAWS = 10_000
KEYS = ["nifty100", "midcap100", "smallcap100", "midcap150", "smallcap250",
        "microcap250"]

# Identified specification per portfolio, from the reconciliation search.
SPEC = {
    "SCMO_0042": {"weights": {"smallcap100": 0.55, "midcap150": 0.45}, "threshold": 0.5},
    "SCMO_0043": {"weights": {"smallcap100": 0.55, "midcap150": 0.45}, "threshold": 0.5},
    "SCMO_0044": {"weights": {"smallcap100": 0.40, "midcap150": 0.60}, "threshold": 0.6},
    "SCMO_0045": {"weights": {"midcap100": 0.60, "smallcap100": 0.40}, "threshold": 0.6},
}


def sleeve(panel_index: pd.DatetimeIndex) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Gold, cash and the 50/50 sleeve, all continuous over the window."""
    etf = prices.defensive_prices().reindex(panel_index).ffill()
    gold = etf["GOLDBEES"].pct_change().fillna(0.0)
    cash = prices.cash_total_return(panel_index).fillna(0.0)
    return gold, cash, 0.5 * gold + 0.5 * cash


def synth(w_def: pd.Series, r_parent: pd.Series, r_sleeve: pd.Series) -> pd.Series:
    w = w_def.reindex(r_parent.index).fillna(0.0)
    return (1 - w) * r_parent.fillna(0.0) + w * r_sleeve.reindex(r_parent.index).fillna(0.0)


def value_add(w_def, r_parent, r_sleeve) -> float:
    s = synth(w_def, r_parent, r_sleeve)
    ok = r_parent.notna()
    return float((np.log1p(s[ok]) - np.log1p(r_parent[ok])).sum())


# ── 1. Reconciliation ──────────────────────────────────────────────────────
def reconcile(sig: pd.DataFrame, real: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for a in AA_SCIDS:
        tgt = real[a]
        for r in (1, 2, 3):
            for combo in itertools.combinations(KEYS, r):
                for th in (0.3, 0.4, 0.5, 0.6, 0.7):
                    if r == 1:
                        Sx = sig[list(combo)].dropna()
                        y = (tgt.reindex(Sx.index) > 0.5).astype(int)
                        agr = float(((Sx.iloc[:, 0] > th).astype(int) == y).mean())
                        wts = {combo[0]: 1.0}
                        nsess = int(len(Sx))
                    else:
                        b = S.fit_blend(sig, tgt, list(combo), threshold=th, grid=21)
                        agr, wts, nsess = b["agreement"], b["weights"], b["sessions"]
                    rows.append({
                        "aa": LABELS[a], "n_indices": r, "combo": "+".join(combo),
                        "threshold": th, "agreement": agr, "sessions": nsess,
                        "weights": ", ".join(f"{k} {v:.2f}" for k, v in wts.items()
                                             if v > 0.005),
                    })
    d = pd.DataFrame(rows)
    return (d.sort_values(["aa", "agreement"], ascending=[True, False])
             .groupby("aa").head(5).reset_index(drop=True))


# ── 2. Single-signal grid: which index times best? ─────────────────────────
def signal_grid(sig: pd.DataFrame, panel: pd.DataFrame, sl: pd.Series) -> pd.DataFrame:
    yrs = (panel.index.max() - panel.index.min()).days / 365.25
    rows = []
    for k in KEYS + ["nifty50"]:
        s = sig[k]
        if s.isna().all():
            continue
        w = (1.0 - s.fillna(method="ffill").fillna(1.0)).clip(0, 1)
        for aa_id, p_id in PAIRS.items():
            r_p = panel[f"r_{p_id}"]
            v = value_add(w, r_p, sl)
            rr = synth(w, r_p, sl)
            rows.append({
                "signal": k, "parent": LABELS[p_id],
                "value_add_return": float(np.expm1(v)),
                "value_add_ann": float(np.expm1(v / yrs)),
                "cagr": cagr_from_returns(rr),
                "max_drawdown": max_drawdown(wealth(rr)),
                "pct_defensive": float((w > 0.5).mean()),
            })
    return pd.DataFrame(rows)


# ── 3. Threshold sweep ─────────────────────────────────────────────────────
def threshold_sweep(sig: pd.DataFrame, panel: pd.DataFrame, sl: pd.Series) -> pd.DataFrame:
    yrs = (panel.index.max() - panel.index.min()).days / 365.25
    rows = []
    for aa_id, p_id in PAIRS.items():
        spec = SPEC[aa_id]
        keys = list(spec["weights"])
        wts = np.array([spec["weights"][k] for k in keys])
        score = (sig[keys].ffill().fillna(1.0).to_numpy() @ wts)
        score = pd.Series(score, index=sig.index)
        r_p = panel[f"r_{p_id}"]
        for th in np.round(np.arange(0.05, 1.0, 0.05), 2):
            w = (score <= th).astype(float)
            v = value_add(w, r_p, sl)
            rr = synth(w, r_p, sl)
            rows.append({
                "aa": LABELS[aa_id], "threshold": float(th),
                "is_actual": bool(abs(th - spec["threshold"]) < 1e-9),
                "value_add_ann": float(np.expm1(v / yrs)),
                "cagr": cagr_from_returns(rr),
                "max_drawdown": max_drawdown(wealth(rr)),
                "pct_defensive": float((w > 0.5).mean()),
            })
    return pd.DataFrame(rows)


# ── 4. Gold-timing test ────────────────────────────────────────────────────
def _blocks(w: pd.Series) -> list[np.ndarray]:
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


def _place(blocks, n, rng) -> np.ndarray:
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


def gold_timing(panel: pd.DataFrame, gold: pd.Series, draws: int) -> pd.DataFrame:
    """
    Was gold exposure concentrated in gold's better periods beyond chance?

    Statistic: gold's annualised return over the sessions the portfolio was
    defensive. Null: the same episodes relocated at random, so episode count,
    durations and total time in gold are all held fixed and only the *placement*
    varies.
    """
    rng = np.random.default_rng(SEED)
    lg = np.log1p(gold).fillna(0.0)
    n = len(panel)
    uncond_ann = float(np.expm1(lg.mean() * 252))
    rows = []
    for aa_id in AA_SCIDS:
        w = panel[f"wdef_{aa_id}"].fillna(0.0)
        off = (w > 0).to_numpy()
        blocks = _blocks(w)
        k = int(off.sum())
        obs_ann = float(np.expm1(lg.to_numpy()[off].mean() * 252))

        d = np.empty(draws)
        arr = lg.to_numpy()
        for i in range(draws):
            m = _place(blocks, n, rng) > 0
            d[i] = np.expm1(arr[m].mean() * 252)

        sd = float(d.std(ddof=1))
        rows.append({
            "aa": LABELS[aa_id],
            "off_sessions": k,
            "gold_ann_while_defensive": obs_ann,
            "gold_ann_unconditional": uncond_ann,
            "edge_pp": (obs_ann - uncond_ann) * 100,
            "null_mean": float(d.mean()),
            "null_sd": sd,
            "percentile": float((d < obs_ann).mean()),
            "z_vs_null": (obs_ann - d.mean()) / sd if sd else np.nan,
            "mde_pp": 2.80 * sd * 100,
            "episodes": len(blocks),
            "draws": draws,
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
    sp, rep = S.all_signals()
    sig = S.daily_signals(sp, cal)
    real = S.realized_states(cal)
    gold, cash, sl = sleeve(cal)

    rec = reconcile(sig, real)
    grid = signal_grid(sig, panel, sl)
    sweep = threshold_sweep(sig, panel, sl)
    gt = gold_timing(panel, gold, a.draws)

    rep.to_csv(out / "signal_load_report.csv", index=False)
    rec.to_csv(out / "signal_reconciliation.csv", index=False)
    grid.to_csv(out / "signal_grid.csv", index=False)
    sweep.to_csv(out / "threshold_sweep.csv", index=False)
    gt.to_csv(out / "gold_timing.csv", index=False)
    S.agreement_single(sig, real).to_csv(out / "signal_agreement_single.csv", index=False)

    pd.set_option("display.width", 250)
    print("=== RECONCILIATION: best-fitting spec per portfolio ===")
    print(rec[["aa", "n_indices", "combo", "threshold", "agreement", "weights"]]
          .groupby("aa").head(2).to_string(index=False))

    print("\n=== SINGLE-SIGNAL GRID: value-add p.a. (rows signal, cols parent) ===")
    print((grid.pivot(index="signal", columns="parent", values="value_add_ann") * 100)
          .round(2).to_string())
    print("\n  time spent defensive by signal:")
    print(grid.groupby("signal")["pct_defensive"].first().round(3).to_string())

    print("\n=== THRESHOLD SWEEP: value-add p.a. by threshold ===")
    piv = sweep.pivot(index="threshold", columns="aa", values="value_add_ann") * 100
    print(piv.round(2).to_string())

    print("\n=== GOLD TIMING ===")
    print(gt[["aa", "off_sessions", "gold_ann_while_defensive", "gold_ann_unconditional",
              "edge_pp", "null_mean", "percentile", "z_vs_null", "mde_pp"]]
          .round(4).to_string(index=False))

    with open(out / "phase8_summary.json", "w", encoding="utf-8") as f:
        json.dump({
            "reconciliation": rec.to_dict(orient="records"),
            "signal_grid": grid.to_dict(orient="records"),
            "threshold_sweep": sweep.to_dict(orient="records"),
            "gold_timing": gt.to_dict(orient="records"),
            "spec": SPEC, "seed": SEED, "draws": a.draws,
        }, f, indent=2, default=float)


if __name__ == "__main__":
    main()
