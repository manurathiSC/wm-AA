# -*- coding: utf-8 -*-
"""
Shared paths, constants and loaders for the AA attribution study.

The four asset-allocation smallcases overlay a risk-on/risk-off switch on a
pure-equity parent. Because the AA version holds *exactly* the parent when
risk-on, the AA-minus-parent spread is earned entirely on risk-off days and
decomposes exactly. Everything downstream leans on that identity, so the
state series this module derives is the single most load-bearing artifact in
the study.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

# ── Paths ──────────────────────────────────────────────────────────────────
ANALYSIS_DIR = Path(__file__).resolve().parent
AA_DIR = ANALYSIS_DIR.parent
DATA_DIR = AA_DIR / "Historical Data"
REPO_ROOT = AA_DIR.parent

EVIDENCE_DIR = ANALYSIS_DIR / "evidence"
CACHE_DIR = ANALYSIS_DIR / "cache"

AA_INDEX_CSV = DATA_DIR / "indices.csv"
PARENT_INDEX_CSV = DATA_DIR / "parentIndices.csv"


def weight_csv(scid: str) -> Path:
    return DATA_DIR / f"{scid}_Weight.csv"


# Reuse the existing metrics library rather than re-deriving CAGR/Sharpe/etc.
# Lives in the sibling wm-research repo (AA was moved out of it).
METRICS_SRC = REPO_ROOT.parent / "wm-research" / "US_ETF" / "selection_engine" / "src"

# Price database lives in the sibling wm-aiReports repo.
WM_AIREPORTS = REPO_ROOT.parent / "wm-aiReports"
PG_FETCH_DIR = WM_AIREPORTS / "chartist-breakout-screen" / "fetch"
BENCHMARK_CLOSES = WM_AIREPORTS / "reports" / "benchmarks" / "benchmark_closes.csv"
NIFTY100_TICKERS = WM_AIREPORTS / "nifty100_tickers.txt"


def add_metrics_to_path() -> None:
    """Make `etf_selector.metrics` importable."""
    p = str(METRICS_SRC)
    if p not in sys.path:
        sys.path.insert(0, p)


# ── Portfolio identities ───────────────────────────────────────────────────
# AA version -> pure-equity parent
PAIRS: dict[str, str] = {
    "SCMO_0042": "SCMO_0003",
    "SCMO_0043": "SCMO_0007",
    "SCMO_0044": "SCMO_0010",
    "SCMO_0045": "SCMO_0029",
}
AA_SCIDS = list(PAIRS)
PARENT_SCIDS = list(PAIRS.values())

# Short labels for charts / tables.
LABELS = {
    "SCMO_0042": "0042", "SCMO_0043": "0043",
    "SCMO_0044": "0044", "SCMO_0045": "0045",
    "SCMO_0003": "0003", "SCMO_0007": "0007",
    "SCMO_0010": "0010", "SCMO_0029": "0029",
}

# ── The defensive sleeve ───────────────────────────────────────────────────
# The sleeve changed composition over the history: a 3-leg gold/liquid/bond
# mix until Apr-2023, then a 2-leg gold/liquid mix from Oct-2024. Attribution
# must therefore use the actual per-date weights, never an assumed 50/50.
GOLD_TICKERS = {"GOLDBEES", "GOLDCASE"}
LIQUID_TICKERS = {"LIQUIDBEES", "LIQUIDCASE"}
BOND_TICKERS = {"EBBETF0431"}
DEFENSIVE_TICKERS = GOLD_TICKERS | LIQUID_TICKERS | BOND_TICKERS

SLEEVE_OF = {t: "gold" for t in GOLD_TICKERS}
SLEEVE_OF.update({t: "liquid" for t in LIQUID_TICKERS})
SLEEVE_OF.update({t: "bond" for t in BOND_TICKERS})

# ── Market-cap indices (note the DB's "SMLCAP" spelling) ───────────────────
INDEX_DB_TICKERS = {
    "nifty100": "NIFTY 100",
    "midcap150": "NIFTY MIDCAP 150",
    "smallcap250": "NIFTY SMLCAP 250",
    "nifty50": "NIFTY 50",
}
# Matching columns in benchmark_closes.csv, used to extend past the DB's end.
INDEX_CSV_COLUMNS = {
    "nifty100": "Nifty 100",
    "midcap150": "Nifty Midcap 150",
    "smallcap250": "Nifty Smallcap 250",
    "nifty50": "Nifty 50",
}
# Microcap 250 is included deliberately. Omitting it forces genuine microcap
# exposure onto the nearest available factor, which materially misstated the
# blends: parent 0003 reads 73-93% smallcap on three factors and 58% microcap
# on four. The parents hold 10-34% microcap by holdings count.
MCAP_INDICES = ["nifty100", "midcap150", "smallcap250", "microcap250"]

# Sheet names in the desk's indices_ohlcv.xlsx, used as the single source for
# index levels so the blend fit does not depend on a spliced series.
MCAP_INDEX_SHEETS = {
    "nifty100": "Nifty100",
    "midcap150": "NiftyMidcap150",
    "smallcap250": "NiftySmallcap250",
    "microcap250": "NiftyMicrocap250",
}

# The DB's index series stop here; beyond it we splice on returns.
INDEX_DB_LAST = pd.Timestamp("2025-09-15")

TRADING_DAYS = 252

# Identity tolerance: on a fully risk-on day the AA and parent returns must
# agree to rounding. Measured median divergence is ~1e-5.
IDENTITY_TOL = 1e-4


# ── Loaders ────────────────────────────────────────────────────────────────
def load_index_levels(path: Path) -> pd.DataFrame:
    """
    Long-format index history -> wide frame of levels, one column per scid.

    Both indices.csv and parentIndices.csv share the schema
    `scid,benchmark,date,index,benchmarkIndex` with dates as `%d/%m/%y %H:%M`
    and levels rebased to 100 on the first session.
    """
    df = pd.read_csv(path)
    df["date"] = pd.to_datetime(df["date"], format="%d/%m/%y %H:%M")
    dup = df.duplicated(subset=["scid", "date"]).sum()
    if dup:
        raise ValueError(f"{path.name}: {dup} duplicate (scid, date) rows")
    wide = df.pivot(index="date", columns="scid", values="index").sort_index()
    wide.columns.name = None
    return wide


def load_nifty50_from_index_csv(path: Path) -> pd.Series:
    """The `benchmarkIndex` column (Nifty 50, rebased to 100) is identical
    across scids; return it once."""
    df = pd.read_csv(path)
    df["date"] = pd.to_datetime(df["date"], format="%d/%m/%y %H:%M")
    piv = df.pivot(index="date", columns="scid", values="benchmarkIndex").sort_index()
    spread = (piv.max(axis=1) - piv.min(axis=1)).abs().max()
    if spread > 1e-6:
        raise ValueError(f"{path.name}: benchmarkIndex differs across scids by {spread:.2e}")
    return piv.iloc[:, 0].rename("nifty50")


def load_state(scid: str) -> pd.DataFrame:
    """
    Derive the realized allocation state for one AA smallcase from its
    rebalance history.

    Rows are (review date, holding). `skipped == "true"` marks a review that
    produced no change — the holdings are still listed, so those dates are
    valid observations of what was held, not gaps.

    Keyed on `availableDate` (the point-in-time effective date, +2..5 days
    after the signal `date`) rather than `date`, so nothing is used before it
    was actually live.

    Returns one row per effective date with the defensive weight overall and
    split by sleeve leg. Weights are renormalised: some dates sum to
    1.000005 from rounding 1/15 in the source file.
    """
    w = pd.read_csv(weight_csv(scid))
    w["signal_date"] = pd.to_datetime(w["date"])
    w["eff_date"] = pd.to_datetime(w["availableDate"], format="%d/%m/%y %H:%M")

    # Point-in-time assertion: a signal must precede the date it goes live.
    bad = (w["signal_date"] >= w["eff_date"]).sum()
    if bad:
        raise ValueError(f"{scid}: {bad} rows where signal_date >= availableDate")

    w["leg"] = w["ticker"].map(SLEEVE_OF).fillna("equity")

    tot = w.groupby("eff_date")["weight"].transform("sum")
    w["w"] = w["weight"] / tot

    by_leg = (
        w.pivot_table(index="eff_date", columns="leg", values="w", aggfunc="sum")
        .fillna(0.0)
        .sort_index()
    )
    for leg in ("gold", "liquid", "bond", "equity"):
        if leg not in by_leg:
            by_leg[leg] = 0.0

    out = pd.DataFrame(
        {
            "w_def": by_leg[["gold", "liquid", "bond"]].sum(axis=1),
            "w_gold": by_leg["gold"],
            "w_liquid": by_leg["liquid"],
            "w_bond": by_leg["bond"],
            "w_equity": by_leg["equity"],
        }
    )

    # Per-instrument defensive weights. The sleeve used the Nippon BeES pair
    # early and the Zerodha pair later; carrying the actual instrument (rather
    # than a "gold leg" abstraction) keeps the sleeve return exact.
    per_ticker = (
        w[w["leg"] != "equity"]
        .pivot_table(index="eff_date", columns="ticker", values="w", aggfunc="sum")
        .reindex(out.index)
        .fillna(0.0)
    )
    for t in sorted(DEFENSIVE_TICKERS):
        out[f"wi_{t}"] = per_ticker[t] if t in per_ticker else 0.0

    out["n_holdings"] = w.groupby("eff_date").size()
    out["n_equity"] = (
        w[w["leg"] == "equity"].groupby("eff_date").size().reindex(out.index).fillna(0).astype(int)
    )
    out["executed"] = (
        w.assign(ex=w["skipped"].astype(str).str.lower() == "false")
        .groupby("eff_date")["ex"].max()
    )
    return out


STATE_WEIGHT_COLS = ["w_def", "w_gold", "w_liquid", "w_bond", "w_equity"] + [
    f"wi_{t}" for t in sorted(DEFENSIVE_TICKERS)
]


def daily_state(scid: str, calendar: pd.DatetimeIndex) -> pd.DataFrame:
    """
    Project the weekly state onto the daily trading calendar.

    Forward-filled: a state persists until the next effective date. The tail
    beyond the last effective date is held at the last known value and
    flagged via `stale` so it can be reported separately (SCMO_0042's weight
    history ends ~10 weeks before its NAV does).
    """
    st = load_state(scid)
    out = st[STATE_WEIGHT_COLS].reindex(st.index.union(calendar)).ffill().reindex(calendar)
    out["stale"] = calendar > st.index.max()
    out["is_rebal"] = calendar.isin(st.index)
    return out


def to_returns(levels: pd.DataFrame | pd.Series) -> pd.DataFrame | pd.Series:
    """Simple daily returns. Missing sessions are never treated as zero."""
    return levels.pct_change()


def wealth(returns: pd.Series, base: float = 100.0) -> pd.Series:
    return base * (1.0 + returns.fillna(0.0)).cumprod()


def cagr_from_levels(levels: pd.Series) -> float:
    lv = levels.dropna()
    years = (lv.index[-1] - lv.index[0]).days / 365.25
    return float((lv.iloc[-1] / lv.iloc[0]) ** (1.0 / years) - 1.0)


def cagr_from_returns(returns: pd.Series) -> float:
    """
    Annualised on *calendar* time, so it matches the dated span of the index
    files. Session-count annualisation (252/n) would shift these by ~0.5pp
    and disagree with the window shown in the report.
    """
    r = returns.dropna()
    if len(r) == 0:
        return float("nan")
    years = (r.index.max() - r.index.min()).days / 365.25
    if years <= 0:
        return float("nan")
    return float(float((1.0 + r).prod()) ** (1.0 / years) - 1.0)


def ann_vol(returns: pd.Series, periods_per_year: int = TRADING_DAYS) -> float:
    r = returns.dropna()
    return float(r.std(ddof=1) * np.sqrt(periods_per_year))


def max_drawdown(levels: pd.Series) -> float:
    lv = levels.dropna()
    return float((lv / lv.cummax() - 1.0).min())
