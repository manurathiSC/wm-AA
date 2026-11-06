# -*- coding: utf-8 -*-
"""
Phase 9 - which signal best predicts gold, and what would actually improve the
overlay.

Built on a validated port of the desk's own supertrend (see supertrend.py):
weighted-ATR matches the published files to 4e-16 and the signal matches 100%
of weeks for five of six indices, 99.5% for Nifty 100.

Two questions:

  1. **Which index's trend best predicts gold?** For each candidate signal,
     gold's annualised return over the weeks that signal says "defensive",
     against gold's unconditional rate, with an episode-relocation null. A
     synthetic Nifty 500 is included to test the broad-market hypothesis
     directly.
  2. **What would improve it?** Four concrete changes, each measured: pick the
     right index per book, run the trend on gold itself to allocate inside the
     sleeve, speed the filter up to cut the ~5-week lag, and signal off the
     parent's own NAV.

Everything here prices the *parent* as the equity leg, so results isolate the
signal and carry no tracking drift.
"""

from __future__ import annotations

import argparse
import json

import numpy as np
import pandas as pd

import prices
import supertrend as ST
from common import (
    EVIDENCE_DIR,
    LABELS,
    PAIRS,
    cagr_from_returns,
    max_drawdown,
    wealth,
)

SEED = 1729
DRAWS = 4000

SHEETS = {
    "nifty50": "NSEI",
    "nifty100": "Nifty100",
    "midcap100": "MC100",
    "midcap150": "NiftyMidcap150",
    "smallcap100": "SC100",
    "smallcap250": "NiftySmallcap250",
    "microcap250": "NiftyMicrocap250",
}

# Nifty 500 is exactly Nifty 100 + Midcap 150 + Smallcap 250 by construction
# (ranks 1-100, 101-250, 251-500). Free-float cap weights are approximately
# 76 / 16 / 8, which is why a broad index's trend is mostly a large-cap trend.
N500_WEIGHTS = {"Nifty100": 0.76, "NiftyMidcap150": 0.16, "NiftySmallcap250": 0.08}


def synthetic_n500() -> pd.DataFrame:
    """
    Daily OHLC proxy for Nifty 500 as the cap-weighted blend of its three
    constituent index families.

    The close is exact up to the weights; the high and low are weighted sums of
    the components' highs and lows, which slightly overstates the blend's true
    range because the components do not peak on the same tick. The three are
    ~0.95 correlated so the bias is small, but this is a proxy and not the
    published index.
    """
    parts = {k: ST.load_index_ohlcv(k) for k in N500_WEIGHTS}
    idx = None
    for d in parts.values():
        idx = d.index if idx is None else idx.intersection(d.index)
    out = pd.DataFrame(index=idx.sort_values())
    for col in ("open", "high", "low", "close"):
        out[col] = sum(
            N500_WEIGHTS[k] * parts[k].loc[out.index, col] / parts[k].loc[out.index[0], "close"]
            for k in N500_WEIGHTS
        ) * 100.0
    out["volume"] = 0.0
    return out


def weekly_from_close(close: pd.Series) -> pd.DataFrame:
    """
    Weekly bars from a close-only series: high and low are the week's highest
    and lowest daily *closes*. Used where no intraday range exists (gold ETF
    cache, portfolio NAVs).
    """
    s = close.dropna().sort_index()
    key = s.index.to_period("W")
    g = s.groupby(key)
    w = pd.DataFrame({"high": g.max(), "low": g.min(), "close": g.last(), "volume": 0.0})
    w.index = g.apply(lambda x: x.index[-1])
    w["HML"] = w["high"] - w["low"]
    w["PClose"] = w["close"].shift()
    w["HMC"] = (w["high"] - w["PClose"]).abs()
    w["LMC"] = (w["low"] - w["PClose"]).abs()
    w["TR"] = w[["HML", "HMC", "LMC"]].max(axis=1)
    w["AHML"] = 0.5 * w["high"] + 0.5 * w["low"]
    return w


def to_daily(sig_weekly: pd.Series, calendar: pd.DatetimeIndex) -> pd.Series:
    """Weekly signal -> daily, effective the session after its bar closes."""
    s = sig_weekly.dropna()
    s = s.copy()
    s.index = s.index + pd.Timedelta(days=1)
    return s.reindex(s.index.union(calendar)).ffill().reindex(calendar)


def build_signals(calendar: pd.DatetimeIndex, mul=ST.MUL, days=ST.DAYS_TO_CONSIDER
                  ) -> pd.DataFrame:
    out = {}
    for key, sheet in SHEETS.items():
        w = ST.to_weekly(ST.load_index_ohlcv(sheet))
        out[key] = to_daily(ST.supertrend(w, mul, days)["signal"], calendar)
    w = ST.to_weekly(synthetic_n500())
    out["nifty500_synth"] = to_daily(ST.supertrend(w, mul, days)["signal"], calendar)
    return pd.DataFrame(out, index=calendar)


# ── helpers ────────────────────────────────────────────────────────────────
def synth_ret(w_def, r_parent, r_sleeve):
    w = w_def.reindex(r_parent.index).fillna(0.0)
    return (1 - w) * r_parent.fillna(0.0) + w * r_sleeve.reindex(r_parent.index).fillna(0.0)


def value_add(w_def, r_parent, r_sleeve) -> float:
    s = synth_ret(w_def, r_parent, r_sleeve)
    ok = r_parent.notna()
    return float((np.log1p(s[ok]) - np.log1p(r_parent[ok])).sum())


def blocks_of(w: pd.Series) -> list[np.ndarray]:
    v = (w.fillna(0.0) > 0).to_numpy()
    out, i = [], 0
    while i < len(v):
        if v[i]:
            j = i
            while j < len(v) and v[j]:
                j += 1
            out.append(np.ones(j - i))
            i = j
        else:
            i += 1
    return out


def place(blocks, n, rng) -> np.ndarray:
    out = np.zeros(n)
    occ = np.zeros(n, dtype=bool)
    for bi in rng.permutation(len(blocks)):
        L = len(blocks[bi])
        for _ in range(200):
            s = int(rng.integers(0, max(1, n - L + 1)))
            if not occ[s:s + L].any():
                out[s:s + L] = 1
                occ[s:s + L] = True
                break
        else:
            for s in range(n - L + 1):
                if not occ[s:s + L].any():
                    out[s:s + L] = 1
                    occ[s:s + L] = True
                    break
    return out


# ── Q2: which signal predicts gold? ────────────────────────────────────────
def gold_prediction(sig: pd.DataFrame, gold: pd.Series, draws: int) -> pd.DataFrame:
    rng = np.random.default_rng(SEED)
    lg = np.log1p(gold).fillna(0.0)
    arr = lg.to_numpy()
    n = len(sig)
    uncond = float(np.expm1(arr.mean() * 252))
    rows = []
    for k in sig.columns:
        w = (1.0 - sig[k].fillna(1.0)).clip(0, 1)
        off = (w > 0.5).to_numpy()
        if off.sum() < 30:
            continue
        obs = float(np.expm1(arr[off].mean() * 252))
        bl = blocks_of(w)
        d = np.empty(draws)
        for i in range(draws):
            m = place(bl, n, rng) > 0
            d[i] = np.expm1(arr[m].mean() * 252)
        sd = float(d.std(ddof=1))
        rows.append({
            "signal": k,
            "off_sessions": int(off.sum()),
            "pct_defensive": float(off.mean()),
            "gold_ann_while_defensive": obs,
            "gold_ann_unconditional": uncond,
            "edge_pp": (obs - uncond) * 100,
            "percentile": float((d < obs).mean()),
            "z_vs_null": (obs - d.mean()) / sd if sd else np.nan,
            "mde_pp": 2.80 * sd * 100,
            "episodes": len(bl),
        })
    return pd.DataFrame(rows).sort_values("edge_pp", ascending=False)


# ── Q1a: best index per book ───────────────────────────────────────────────
def signal_by_parent(sig: pd.DataFrame, panel: pd.DataFrame, sl: pd.Series) -> pd.DataFrame:
    yrs = (panel.index.max() - panel.index.min()).days / 365.25
    rows = []
    for k in sig.columns:
        w = (1.0 - sig[k].fillna(1.0)).clip(0, 1)
        for aa_id, p_id in PAIRS.items():
            r_p = panel[f"r_{p_id}"]
            v = value_add(w, r_p, sl)
            rr = synth_ret(w, r_p, sl)
            rows.append({
                "signal": k, "parent": LABELS[p_id],
                "value_add_ann": float(np.expm1(v / yrs)),
                "cagr": cagr_from_returns(rr),
                "max_drawdown": max_drawdown(wealth(rr)),
            })
    return pd.DataFrame(rows)


# ── Q1b: trend the sleeve, not just the equity ─────────────────────────────
def sleeve_trend_variant(sig: pd.DataFrame, panel: pd.DataFrame, gold: pd.Series,
                         cash: pd.Series, best: dict[str, str]) -> pd.DataFrame:
    """
    Keep the equity decision as-is, but decide gold-vs-cash *inside* the sleeve
    with a supertrend on gold itself, instead of holding a fixed 50/50.

    This is the direct answer to "is the skill in gold selection": at present
    no gold information enters the process at all, so this measures what adding
    it would have been worth.
    """
    gsig = to_daily(ST.supertrend(weekly_from_close(
        (1 + gold).cumprod()))["signal"], panel.index).fillna(1.0)
    yrs = (panel.index.max() - panel.index.min()).days / 365.25
    rows = []
    for aa_id, p_id in PAIRS.items():
        r_p = panel[f"r_{p_id}"]
        w = (1.0 - sig[best[aa_id]].fillna(1.0)).clip(0, 1)
        arms = {
            "fixed 50/50": 0.5 * gold + 0.5 * cash,
            "all gold": gold,
            "gold when gold trends, else cash": gsig * gold + (1 - gsig) * cash,
        }
        for name, s in arms.items():
            v = value_add(w, r_p, s)
            rr = synth_ret(w, r_p, s)
            rows.append({
                "aa": LABELS[aa_id], "signal_used": best[aa_id], "sleeve_rule": name,
                "value_add_ann": float(np.expm1(v / yrs)),
                "cagr": cagr_from_returns(rr),
                "max_drawdown": max_drawdown(wealth(rr)),
                "pct_gold_when_defensive": float(gsig[w > 0.5].mean()),
            })
    return pd.DataFrame(rows)


# ── Q1c: speed the filter up ───────────────────────────────────────────────
def parameter_sweep(panel: pd.DataFrame, sl: pd.Series, sheet: str = "SC100"
                    ) -> pd.DataFrame:
    yrs = (panel.index.max() - panel.index.min()).days / 365.25
    weekly = ST.to_weekly(ST.load_index_ohlcv(sheet))
    rows = []
    for days in (3, 5, 8, 10):
        for mul in (1.0, 1.5, 2.0, 2.5, 3.0):
            s = to_daily(ST.supertrend(weekly, mul, days)["signal"], panel.index)
            w = (1.0 - s.fillna(1.0)).clip(0, 1)
            flips = int((w != w.shift()).sum())
            for aa_id, p_id in PAIRS.items():
                r_p = panel[f"r_{p_id}"]
                rows.append({
                    "days": days, "mul": mul, "aa": LABELS[aa_id],
                    "value_add_ann": float(np.expm1(value_add(w, r_p, sl) / yrs)),
                    "pct_defensive": float((w > 0.5).mean()),
                    "switches": flips,
                })
    return pd.DataFrame(rows)


# ── Q1d: signal off the parent's own NAV ───────────────────────────────────
def own_nav_signal(panel: pd.DataFrame, sl: pd.Series) -> pd.DataFrame:
    yrs = (panel.index.max() - panel.index.min()).days / 365.25
    rows = []
    for aa_id, p_id in PAIRS.items():
        lvl = panel[f"lvl_{p_id}"]
        s = to_daily(ST.supertrend(weekly_from_close(lvl))["signal"], panel.index)
        w = (1.0 - s.fillna(1.0)).clip(0, 1)
        r_p = panel[f"r_{p_id}"]
        rr = synth_ret(w, r_p, sl)
        rows.append({
            "aa": LABELS[aa_id], "parent": LABELS[p_id],
            "value_add_ann": float(np.expm1(value_add(w, r_p, sl) / yrs)),
            "cagr": cagr_from_returns(rr),
            "max_drawdown": max_drawdown(wealth(rr)),
            "pct_defensive": float((w > 0.5).mean()),
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
    etf = prices.defensive_prices().reindex(cal).ffill()
    gold = etf["GOLDBEES"].pct_change().fillna(0.0)
    cash = prices.cash_total_return(cal).fillna(0.0)
    sl = 0.5 * gold + 0.5 * cash

    sig = build_signals(cal)
    sig.to_csv(out / "signals_replicated.csv")

    gp = gold_prediction(sig, gold, a.draws)
    sbp = signal_by_parent(sig, panel, sl)

    best = {}
    for aa_id, p_id in PAIRS.items():
        sub = sbp[sbp.parent == LABELS[p_id]].sort_values("value_add_ann", ascending=False)
        best[aa_id] = sub.iloc[0]["signal"]

    stv = sleeve_trend_variant(sig, panel, gold, cash, best)
    psw = parameter_sweep(panel, sl)
    onav = own_nav_signal(panel, sl)

    gp.to_csv(out / "gold_prediction_by_signal.csv", index=False)
    sbp.to_csv(out / "signal_by_parent_full.csv", index=False)
    stv.to_csv(out / "sleeve_trend_variant.csv", index=False)
    psw.to_csv(out / "supertrend_param_sweep.csv", index=False)
    onav.to_csv(out / "own_nav_signal.csv", index=False)

    pd.set_option("display.width", 250)
    print("=== Q2. WHICH SIGNAL PREDICTS GOLD? (gold ann. return while that signal is defensive) ===")
    print(gp[["signal", "pct_defensive", "gold_ann_while_defensive",
              "gold_ann_unconditional", "edge_pp", "percentile", "z_vs_null",
              "mde_pp"]].round(4).to_string(index=False))

    print("\n=== Q1a. SIGNAL x PARENT: value-add p.a. (%) ===")
    print((sbp.pivot(index="signal", columns="parent", values="value_add_ann") * 100)
          .round(2).to_string())
    print("\n  best signal per parent:", {LABELS[k]: v for k, v in best.items()})

    print("\n=== Q1b. TREND THE SLEEVE (gold vs cash decided by gold's own trend) ===")
    print((stv.pivot(index="sleeve_rule", columns="aa", values="value_add_ann") * 100)
          .round(2).to_string())

    print("\n=== Q1c. FASTER FILTER: value-add p.a. (%) on the SC100 signal ===")
    piv = psw.pivot_table(index=["days", "mul"], columns="aa", values="value_add_ann") * 100
    piv["switches"] = psw.groupby(["days", "mul"])["switches"].first()
    print(piv.round(2).to_string())

    print("\n=== Q1d. SIGNAL FROM THE PARENT'S OWN NAV ===")
    print(onav.round(4).to_string(index=False))

    with open(out / "phase9_summary.json", "w", encoding="utf-8") as f:
        json.dump({
            "gold_prediction": gp.to_dict(orient="records"),
            "signal_by_parent": sbp.to_dict(orient="records"),
            "sleeve_trend": stv.to_dict(orient="records"),
            "param_sweep": psw.to_dict(orient="records"),
            "own_nav": onav.to_dict(orient="records"),
            "best_signal_per_parent": {LABELS[k]: v for k, v in best.items()},
            "n500_weights": N500_WEIGHTS, "mul": ST.MUL, "days": ST.DAYS_TO_CONSIDER,
        }, f, indent=2, default=float)


if __name__ == "__main__":
    main()
