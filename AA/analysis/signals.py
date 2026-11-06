# -*- coding: utf-8 -*-
"""
Load the per-index supertrend signals and reconcile them against the realized
allocation states.

Each index folder holds a weekly `W_allRebal.xlsx` with a supertrend value
`ST` alongside its final upper and lower bands `FUB` / `FLB`. The convention
is that the trend is down (sell) when `ST` sits on the upper band and up (buy)
when it sits on the lower band:

    ST == FUB  ->  0 (defensive)
    ST == FLB  ->  1 (equity)

Having the signals themselves - rather than only the realized states from the
weight files - is what makes the 60% threshold testable.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from common import AA_SCIDS, CACHE_DIR, LABELS, PAIRS, daily_state

SIGNAL_ROOT = Path(
    r"G:\.shortcut-targets-by-id\0B7f_UMMZHM_JNXljMVVXY2VPcHM\Investment Research_N"
    r"\Shubham_Shreshtha\Friday Rebalance Automation\RSI\Final"
)

# Folder name -> short key used everywhere downstream.
INDEX_FOLDERS = {
    "Nifty100": "nifty100",
    "MC100": "midcap100",
    "SC100": "smallcap100",
    "NiftyMidcap150": "midcap150",
    "NiftySmallcap250": "smallcap250",
    "NiftyMicrocap250": "microcap250",
    "NSEI": "nifty50",
}

TOL = 1e-6


def load_index_signal(folder: str, refresh: bool = False) -> pd.DataFrame:
    """Weekly supertrend state for one index: 1 = equity, 0 = defensive."""
    path = SIGNAL_ROOT / folder / "W_allRebal.xlsx"
    d = pd.read_excel(path)
    d["Date"] = pd.to_datetime(d["Date"])
    d = d.dropna(subset=["ST", "FUB", "FLB"]).sort_values("Date")

    on_upper = (d["ST"] - d["FUB"]).abs() < TOL
    on_lower = (d["ST"] - d["FLB"]).abs() < TOL
    # Anything matching neither band would make the rule ambiguous; surface it
    # rather than silently defaulting.
    ambiguous = int((~on_upper & ~on_lower).sum())
    both = int((on_upper & on_lower).sum())

    sig = pd.Series(np.where(on_lower, 1.0, np.where(on_upper, 0.0, np.nan)),
                    index=d["Date"], name=INDEX_FOLDERS[folder])
    out = pd.DataFrame({"signal": sig, "index_level": d["Index"].values})
    out.attrs.update({"ambiguous": ambiguous, "both": both, "rows": len(d)})
    return out


def all_signals(refresh: bool = False) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Wide weekly signal panel plus a load report."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache = CACHE_DIR / "index_signals_weekly.csv"
    rep_path = CACHE_DIR / "index_signals_report.csv"
    if cache.exists() and rep_path.exists() and not refresh:
        return (pd.read_csv(cache, index_col=0, parse_dates=True),
                pd.read_csv(rep_path))

    cols, rows = {}, []
    for folder, key in INDEX_FOLDERS.items():
        df = load_index_signal(folder)
        cols[key] = df["signal"]
        s = df["signal"].dropna()
        rows.append({
            "index": key, "folder": folder, "weeks": df.attrs["rows"],
            "ambiguous_rows": df.attrs["ambiguous"],
            "on_both_bands": df.attrs["both"],
            "first": s.index.min().date().isoformat(),
            "last": s.index.max().date().isoformat(),
            "pct_equity": float(s.mean()),
            "flips": int((s != s.shift()).sum() - 1),
        })
    panel = pd.DataFrame(cols).sort_index()
    panel = panel[~panel.index.duplicated(keep="first")]
    rep = pd.DataFrame(rows)
    panel.to_csv(cache)
    rep.to_csv(rep_path, index=False)
    return panel, rep


def daily_signals(panel: pd.DataFrame, calendar: pd.DatetimeIndex) -> pd.DataFrame:
    """
    Project weekly signals onto the trading calendar.

    The files are dated for a Friday review; the smallcase went live the
    following week, so a signal is only used from the session *after* its
    date. Forward-filled thereafter.
    """
    idx = panel.index.union(calendar)
    out = panel.reindex(idx).ffill().reindex(calendar)
    shifted = panel.copy()
    shifted.index = shifted.index + pd.Timedelta(days=1)
    return shifted.reindex(shifted.index.union(calendar)).ffill().reindex(calendar)


def realized_states(calendar: pd.DatetimeIndex) -> pd.DataFrame:
    """Realized equity weight (1 - defensive weight) per AA smallcase."""
    return pd.DataFrame(
        {a: 1.0 - daily_state(a, calendar)["w_def"].fillna(0.0) for a in AA_SCIDS},
        index=calendar,
    )


def agreement_single(sig: pd.DataFrame, real: pd.DataFrame) -> pd.DataFrame:
    """How well each individual index signal alone matches each realized state."""
    rows = []
    for a in AA_SCIDS:
        r = (real[a] > 0.5).astype(int)
        for k in sig.columns:
            s = sig[k]
            m = s.notna()
            rows.append({
                "aa": LABELS[a], "index": k,
                "agreement": float(((s[m] > 0.5).astype(int) == r[m]).mean()),
                "sessions": int(m.sum()),
            })
    return pd.DataFrame(rows)


def fit_blend(
    sig: pd.DataFrame, target: pd.Series, keys: list[str], threshold: float = 0.6,
    grid: int = 21,
) -> dict:
    """
    Search simplex weights over `keys` maximising agreement between
    (weighted signal > threshold) and the realized state.

    A coarse grid rather than a gradient method: the objective is a step
    function of the weights, so it has no useful derivative.
    """
    S = sig[keys].dropna()
    y = (target.reindex(S.index) > 0.5).astype(int)
    best = {"agreement": -1.0}
    steps = np.linspace(0.0, 1.0, grid)

    if len(keys) == 2:
        combos = [(w, 1.0 - w) for w in steps]
    elif len(keys) == 3:
        combos = [(a, b, 1.0 - a - b) for a in steps for b in steps
                  if a + b <= 1.0 + 1e-9]
    else:
        combos = [tuple(1.0 / len(keys) for _ in keys)]

    A = S.to_numpy()
    yv = y.to_numpy()
    for w in combos:
        score = A @ np.array(w)
        pred = (score > threshold).astype(int)
        agr = float((pred == yv).mean())
        if agr > best["agreement"]:
            best = {"agreement": agr, "weights": dict(zip(keys, [float(x) for x in w])),
                    "threshold": threshold, "sessions": int(len(S))}
    return best
