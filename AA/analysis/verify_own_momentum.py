#!/usr/bin/env python
"""verify_own_momentum.py -- the independent check for T01 (validity gate V1).

WHY IT EXISTS
    T01 (AA/tests/T01/T01.md) asks whether a smallcase's own index momentum can tell when to move an
    AA book's weight from its parent into a GOLDBEES + LBES sleeve. Gate V1 (T01.md section 2) says no
    result in section 4 may be read unless a check that imports nothing from the engine
    (AA/analysis/own_momentum.py) re-derives the splice, every signal, every decision, every trade
    session and the end NAVs from the raw files, and agrees with the shipped evidence. This is that
    check. It never opens own_momentum.py and does not use AA/analysis/common.py: every raw file is
    parsed here, by this file's own code.

WHAT IT RE-DERIVES (from the raw files, never from the evidence)
    (a) the splice: the session calendar (union of the harness-rebuild dates and the published dates),
        P_t per parent (harness up to 2021-10-29; P_1029 x pub_t / pub_1101 from 2021-11-01), and the
        GOLDBEES / LBES prices carried forward onto that calendar. Compared with spliced_inputs.csv on
        every date and column (relative 1e-12).
    (b) for every config (30), book (4) and window (2): the decision sessions, the driving value, the
        equity target and the trade session each decision triggers. Compared row by row with
        decisions_all_configs.csv: same set of rows, equity_target exact, value within 1e-9 absolute,
        trade_session and traded exact, data_last_date present and not after decision_date (point in
        time). data_last_date's equality with decision_date, and with this file's own last-input date
        (the Master label for triple), is reported but not gated. decisions_reference.csv must equal
        the pct_w65_q25 rows.
    (c) every strategy realisation at cost 0: the closed-form end NAV of T01.md section 3 step 10,
        V_end = prod_j sum_a w_aj * close_a(e_j+1) / close_a(e_j), from this file's own targets and
        trade sessions and the raw prices. Compared with realisations.csv nav_end (relative 1e-9).
    (d) every strategy realisation at cost 20.8 bps: this file's own implementation of the section 3
        step 6 trading rules (trims first, then top-ups in the order equity, GOLDBEES, LBES, each
        capped by the cash account; build from cash at the buy-side cost; liquidation at the last
        close at the sell-side cost). Compared with nav_end (relative 1e-9).
    (e) every B&H row: nav_end = P_end / P_T0 (relative 1e-9), plus its CAGR and max drawdown.
    Extended checks (also gating; each is fully specified by T01.md section 3 or the evidence schema):
    (f) every null row: the strategy's target series rotated by k (the spec does not fix the sign of
        k, so both np.roll(w, +k) and np.roll(w, -k) are tried and the one that matches is reported),
        run through this file's own engine at the row's cost; nav_end relative 1e-9; the full set of
        k (8 <= k <= N-8, daily 40 <= k <= N-40) present; target_level_counts equal to the strategy's.
    (g) trades.csv: every build, switch and liquidation of every strategy realisation: same set of
        trades, decision_date, from/to equity, nav_before and nav_after (relative 1e-9).
    (h) strategy-row fields of realisations.csv: n_decisions, n_switches, n_spells, share_sleeve_weeks,
        avg_equity_weight, target_level_counts, total_return, CAGR, max_dd, calmar (1e-9), and vol /
        sharpe (sample SD or population SD of daily returns -- either is accepted, the one used is
        reported, because "SD" does not fix the divisor).
    (i) daily_reference.csv: daily strategy NAV and B&H NAV on every session of the 16 reference
        realisations (relative 1e-9). The drifted weights are compared but only reported (w_cash is
        taken as LBES plus the trading cash account).

THE RULE IT CHECKS
    T01.md section 3 "Construction", steps 1-10, read literally. Where the text admits two readings the
    choice is listed in INTERPRETATIONS below and written into the output JSON.

HOW TO RUN (from the repo root)
    python AA/analysis/verify_own_momentum.py --run-dir AA/tests/T01/evidence/headline --sleeve gold_cash \
        [--out AA/tests/T01/verify_headline.json]
    python AA/analysis/verify_own_momentum.py --run-dir AA/tests/T01/evidence/cash_sleeve --sleeve cash \
        [--out AA/tests/T01/verify_cash_sleeve.json]
    python AA/analysis/verify_own_momentum.py --run-dir AA/tests/T01/evidence/headline --sleeve gold_cash \
        --corrupt-test          # must exit 0: the corrupted copy must FAIL on every planted defect
    python AA/analysis/verify_own_momentum.py --self-test   # no evidence needed; checks this file's
                                                            # own pieces against each other
    Options: --skip-nulls (skip check f, for speed), --max-examples N (failure examples per check).
    Diagnostic switches (never part of the gate; the report records them as
    "diagnostic_reading_not_predeclared"): --st-midweek partial (st_weekly at a mid-week decision
    session read from a partial candle of that week instead of the last complete weekly candle) and
    --lbes-carry calendar (sleeve prices reindexed to the calendar and forward-filled along it instead
    of carried as of each session). They exist to show whether a failure is caused by that reading
    alone.
    st_weekly mid-week reading, CHANGED 2026-10-01 at integration (recorded in the JSON under
    readings_changed_after_evidence): this file first pre-declared 'partial'; T01.md section 3 does not
    say how a weekly candle is formed at a decision session that is not its week's last (only W2's T0,
    Monday 2021-11-01), so the integrator kept the engine's reading 'last_complete' and made it the
    default here. The equity targets are identical under both readings; only 3 `value` cells differ.

WHAT EXIT 0 MEANS
    Normal mode: rows were compared in every check, no row was missing or extra, and no comparison
    failed. Exit 1 on any failure, any missing or extra row, or if nothing was compared; exit 2 if an
    input file is missing or unreadable.
    --corrupt-test: the run dir was copied to a temp folder, 3 equity targets in
    decisions_all_configs.csv were flipped and 2 strategy nav_end values were scaled by 1.001, and the
    checks on that copy failed on every planted defect. Exit 1 if any planted defect went undetected.
    --self-test: the closed form and the cost engine at 0 bps agree on every config, book, window and
    sleeve (relative 1e-12); the vectorised null engine equals the scalar engine; every signal
    recomputed on P truncated at its decision session equals the full-series value (point in time).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
import pandas as pd

# ----------------------------------------------------------------------------------------------
# Constants
# ----------------------------------------------------------------------------------------------
REPO = Path(__file__).resolve().parents[2]
RAW = {
    "published_parents": REPO / "AA" / "Historical Data" / "parentIndices.csv",
    "harness_parents": REPO / "AA" / "analysis" / "evidence" / "final_strategy" / "nav_curves_daily.csv",
    "goldbees": REPO / "AA" / "analysis" / "evidence" / "final_strategy" / "gold_daily_ohlc_eikon.csv",
    "lbes": REPO / "AA" / "Historical Data" / "LBES_Adjusted_Price_data_2026_08_10.csv",
    "master_nifty100": REPO / "AA" / "Historical Data" / "frozen_2026-09-25" / "Master" / "Master_Nifty100.xlsx",
    "master_mc100": REPO / "AA" / "Historical Data" / "frozen_2026-09-25" / "Master" / "Master_MC100.xlsx",
    "master_sc100": REPO / "AA" / "Historical Data" / "frozen_2026-09-25" / "Master" / "Master_SC100.xlsx",
}
BOOK_PARENT = {"SCMO_0042": "SCMO_0003", "SCMO_0043": "SCMO_0007",
               "SCMO_0044": "SCMO_0010", "SCMO_0045": "SCMO_0029"}
PARENTS = list(BOOK_PARENT.values())
HARNESS_END = pd.Timestamp("2021-10-29")
PUBLISHED_START = pd.Timestamp("2021-11-01")
WINDOWS = {  # name: (base date, base rule, end date)
    "W1": (pd.Timestamp("2015-07-31"), "last_on_or_before", pd.Timestamp("2021-10-29")),
    "W2": (pd.Timestamp("2021-11-01"), "exact", pd.Timestamp("2026-08-21")),
}
COSTS = (0.0, 20.8)
SLEEVES = ("gold_cash", "cash")
REFERENCE = "pct_w65_q25"

SWEEP = ([f"pct_w{w}_q{q}" for w in (20, 40, 65, 130, 250) for q in (10, 25, 40)]
         + ["pct_w65_hyst", "pct_w65_step", "pct_w65_q25_daily",
            "sma_50", "sma_100", "sma_200", "tsmom_65", "tsmom_130", "tsmom_250",
            "ddhigh_250_x7p5", "ddhigh_250_x10", "ddhigh_250_x15", "st_weekly"])
DESCRIPTIVE = ["triple", "triple_and_pct25"]
CONFIGS = SWEEP + DESCRIPTIVE
assert len(SWEEP) == 28 and len(CONFIGS) == 30

TOL_SPLICE_REL = 1e-12
TOL_VALUE_ABS = 1e-9
TOL_NAV_REL = 1e-9
TOL_STAT = 1e-9          # |a-b| <= TOL_STAT * max(1, |b|)

# The adopted readings (the gate runs under these); anything else is a diagnostic run.
ST_MIDWEEK_DEFAULT = "last_complete"
LBES_CARRY_DEFAULT = "asof"
READINGS_CHANGED_AFTER_EVIDENCE = [{
    "reading": "st_weekly at a mid-week decision session (W2 T0, Monday 2021-11-01)",
    "predeclared_by_verifier": "partial",
    "adopted": "last_complete",
    "date": "2026-10-01",
    "by": "integrator",
    "reason": ("T01.md section 3 does not say how a weekly candle is formed at a decision session that is not "
               "its week's last; both readings respect 'P up to and including d only'. The integrator rule "
               "for a genuinely ambiguous spec is to keep the engine's reading and disclose it."),
    "effect": ("equity_target, trade_session, traded and every NAV identical under both readings; the "
               "decisions_all_configs.csv value differs on 3 rows (st_weekly, W2, 2021-11-01, SCMO_0043, "
               "SCMO_0044, SCMO_0045)"),
}]

INTERPRETATIONS = [
    "Sleeve prices are carried forward AS OF each session: the last GOLDBEES close / LBES level dated on or "
    "before the session, including rows dated off the session calendar (LBES has Sunday rows). Reason: the "
    "data table says LBES runs '2007-06-29 -> 2026-08-09; forward-filled to 2026-08-21', i.e. the 2026-08-09 "
    "level is the one carried. The other reading (reindex to the calendar, then forward-fill along it) "
    "differs on 36 sessions for LBES (max 0.84 points, 5.3e-4 relative) and on none for GOLDBEES; check (a) "
    "reports the evidence's cash column against both readings.",
    "Splice: P_t = P_2021-10-29 x (pub_t / pub_2021-11-01) for t >= 2021-11-01, so P_2021-11-01 equals "
    "P_2021-10-29 exactly (the zero-return session of step 1).",
    "Percentile thresholds are compared exactly in integers (p_d < q  <=>  100 x count < q x W), because ties "
    "at the threshold occur (e.g. 26 of 65 = 40.0). The value column is p_d = 100 x count / W as a float.",
    "Weekly decision sessions: the last calendar session of each ISO (year, week), including weekend special "
    "sessions (e.g. the Sunday 2016-10-30 Muhurat session is the last session of its ISO week), plus T0; "
    "only sessions in (T0, end] are added; the window's end is one of them.",
    "pct_w65_hyst: the state before each window's T0 is equity; the state machine runs over that window's "
    "decision sessions from T0.",
    "sma_n: weight 0 iff P_d < mean(P_d-n+1..P_d) (direct comparison); value = P_d / mean - 1. tsmom_L: value "
    "= P_d / P_d-L - 1, weight 0 iff value < 0. ddhigh_250_xX: value = P_d / max(P_d-249..P_d) - 1, weight "
    "0 iff value < -X / 100.",
    "st_weekly follows production ST.py: weekly candle H = max close, L = min close, C = last close of the "
    "ISO week; TR = max(H-L, |H-C_prev|, |L-C_prev|), and on the first candle TR = H-L (pandas max skips "
    "NaN); ATR = sum of weights 1..5/15 times TR on candles j-4..j; bands 0.5H + 0.5L +/- 2 ATR; the first "
    "value is on candle index 5 with ST = FUB; ratchet FUB = BUB if (BUB < FUB_prev or C_prev > FUB_prev) "
    "else FUB_prev, FLB = BLB if (BLB > FLB_prev or C_prev < FLB_prev) else FLB_prev; ST transitions as in "
    "ST.py, including its 'close < FUB' buy-to-sell test and ST = 0 otherwise. Weight 0 iff ST == FUB, else "
    "1. Value = C - ST.",
    "st_weekly at a decision session that is not the last session of its ISO week (only W2's T0, 2021-11-01, "
    "a Monday) reads the supertrend of the last COMPLETE weekly candle (the week ending 2021-10-29), whose "
    "last session is the last input used. T01.md section 3 defines each candle over a whole ISO week "
    "('close = last close') and does not say how a decision mid-week reads it; both this reading and a "
    "partial candle of the current week (closes up to d) respect 'P up to and including d only'. This "
    "file first pre-declared the partial-candle reading; on 2026-10-01, after the engine evidence existed, "
    "the integrator ruled the spec ambiguous and kept the engine's reading (the same 'latest completed "
    "week label <= d' rule T01 states for the triple rows). The partial reading remains as the diagnostic "
    "--st-midweek partial; note that production ST.py, run with data only through d, would build the "
    "partial candle. Equity targets are identical under both readings on all 4 books; the value differs "
    "on 3 rows (SCMO_0043/0044/0045, W2, 2021-11-01).",
    "triple: for each of Master_Nifty100 / MC100 / SC100, the SIGN on the row with the latest Date <= d; "
    "value = number of the three that are BUY; weight 1 iff all three are BUY. triple_and_pct25: triple "
    "AND p_d >= 25 with W = 65; value = p_d.",
    "Trades: a target decided on any decision session except the window's last is traded on the next "
    "session when it differs (exactly) from the target last traded; T0's target is always traded (the "
    "build). For the daily config the second-last session's target therefore trades at the last session's "
    "close and the final liquidation follows at that same close.",
    "Execution: at a trade every asset is reset to its target: delta_a = w_a x nav_now - units_a x close_a; "
    "delta < 0 trims (units -= |delta| / px, cash += |delta| (1 - ow)), then delta > 0 top-ups in the order "
    "equity, GOLDBEES, LBES (v = min(delta, cash), units += v (1 - ow) / px, cash -= v); delta == 0 does "
    "nothing. NAV is 1.0 in cash at T0's close and stays flat until the build session's close.",
    "Null draws: the target series w_0..w_n on the window's decision sessions is rotated by k and run through "
    "the same schedule (build at T0's next session, trades on the next session after each changed target, "
    "last decision not traded, liquidation at the last close). The sign of the rotation is not fixed by "
    "the spec; both np.roll(w, +k) and np.roll(w, -k) are tried and the matching one is reported.",
    "data_last_date is gated only as a point-in-time property (present and <= decision_date). The schema text "
    "says it equals decision_date; the gate does not require that, because for triple no P is read and the "
    "last input is the Master label (e.g. 2024-05-10 for d = 2024-05-17, whose week is labelled with the "
    "Saturday 2024-05-18 session). Equality counts are reported.",
    "Statistics: sessions = end - T0 + 1, years = (sessions - 1) / 252, CAGR = nav_end^(1/years) - 1, daily "
    "returns on the daily NAV from T0 (1.0) to the last session (after liquidation), max_dd = min(NAV / "
    "running max - 1), calmar = CAGR / |max_dd|, sharpe = CAGR / vol. vol accepts SD with divisor n-1 or n.",
]


# ----------------------------------------------------------------------------------------------
# Raw data
# ----------------------------------------------------------------------------------------------
def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_raw() -> dict:
    for k, p in RAW.items():
        if not p.exists():
            raise FileNotFoundError(f"raw input missing: {k}: {p}")
    pub = pd.read_csv(RAW["published_parents"])
    pub["date"] = pd.to_datetime(pub["date"], format="%d/%m/%y %H:%M")
    if pub.duplicated(["scid", "date"]).any():
        raise ValueError("duplicate (scid, date) in parentIndices.csv")
    pubw = pub.pivot(index="date", columns="scid", values="index").sort_index()
    missing = [p for p in PARENTS if p not in pubw.columns]
    if missing:
        raise ValueError(f"parents missing from parentIndices.csv: {missing}")

    nc = pd.read_csv(RAW["harness_parents"], index_col=0)
    nc.index = pd.to_datetime(nc.index, format="%Y-%m-%d")
    harness = {}
    for book, parent in BOOK_PARENT.items():
        col = f"before the books 2014-07 -> 2021-10|{book}|parent (no overlay)"
        if col not in nc.columns:
            raise ValueError(f"harness column missing: {col}")
        harness[parent] = nc[col].dropna().astype(float).sort_index()

    g = pd.read_csv(RAW["goldbees"])
    gold = pd.Series(g["close"].astype(float).values,
                     index=pd.to_datetime(g["date"], format="%Y-%m-%d")).sort_index()
    lb = pd.read_csv(RAW["lbes"])
    lbes = pd.Series(lb["price"].astype(float).values,
                     index=pd.to_datetime(lb["date"], format="%d/%m/%y %H:%M")).sort_index()
    for name, s in (("goldbees", gold), ("lbes", lbes)):
        if s.index.duplicated().any():
            raise ValueError(f"duplicate dates in {name}")

    masters = {}
    for key in ("master_nifty100", "master_mc100", "master_sc100"):
        df = pd.read_excel(RAW[key])
        d = pd.to_datetime(df["Date"]).dt.normalize()
        sign = df["SIGN"].astype(str).str.strip().str.upper()
        ok = d.notna() & sign.isin(["BUY", "SELL"])
        d, sign = d[ok].values, sign[ok].values
        order = np.argsort(d, kind="stable")
        d, sign = d[order], sign[order]
        if len(np.unique(d)) != len(d):
            raise ValueError(f"duplicate Date labels in {key}")
        masters[key] = (pd.DatetimeIndex(d), sign)
    return {"pubw": pubw, "harness": harness, "gold": gold, "lbes": lbes, "masters": masters}


def carry_asof(s: pd.Series, cal: pd.DatetimeIndex) -> np.ndarray:
    """Last observation dated on or before each session (off-calendar rows included)."""
    pos = np.searchsorted(s.index.values, cal.values, side="right") - 1
    if (pos < 0).any():
        raise ValueError(f"series {s.name} has no value on or before {cal[pos < 0][0].date()}")
    return s.values[pos].astype(float)


def carry_calendar(s: pd.Series, cal: pd.DatetimeIndex) -> np.ndarray:
    """The other reading: keep only rows dated on the calendar, then forward-fill along it."""
    return s.reindex(cal).ffill().values.astype(float)


def build_splice(raw: dict, carry: str = "asof") -> dict:
    hsets = [set(raw["harness"][p].index) for p in PARENTS]
    hdates = pd.DatetimeIndex(sorted(set().union(*hsets)))
    pdates = pd.DatetimeIndex(raw["pubw"].index)
    if hdates.max() != HARNESS_END:
        raise ValueError(f"harness ends {hdates.max()}, expected {HARNESS_END}")
    if pdates.min() != PUBLISHED_START:
        raise ValueError(f"published starts {pdates.min()}, expected {PUBLISHED_START}")
    cal = hdates.union(pdates)
    P = {}
    for parent in PARENTS:
        h = raw["harness"][parent]
        pub = raw["pubw"][parent]
        anchor = float(h.loc[HARNESS_END])
        base = float(pub.loc[PUBLISHED_START])
        hv = h.reindex(cal).values
        pv = pub.reindex(cal).values
        arr = np.where(cal <= HARNESS_END, hv, anchor * (pv / base))
        if not np.all(np.isfinite(arr)) or not np.all(arr > 0):
            bad = cal[~(np.isfinite(arr) & (arr > 0))]
            raise ValueError(f"spliced {parent} not finite/positive on {len(bad)} sessions, first {bad[0].date()}")
        i1101 = cal.get_loc(PUBLISHED_START)
        if arr[i1101] != arr[i1101 - 1]:
            raise AssertionError("spliced 2021-10-29 -> 2021-11-01 return is not exactly 0")
        P[parent] = arr.astype(float)
    main_fn, alt_fn = (carry_asof, carry_calendar) if carry == "asof" else (carry_calendar, carry_asof)
    gold = main_fn(raw["gold"].rename("goldbees"), cal)
    cash = main_fn(raw["lbes"].rename("lbes"), cal)
    alt = {"gold": alt_fn(raw["gold"].rename("goldbees"), cal), "cash": alt_fn(raw["lbes"].rename("lbes"), cal),
           "reading": "calendar_ffill" if carry == "asof" else "asof"}
    for nm, a in (("gold", gold), ("cash", cash)):
        if not np.all(np.isfinite(a)) or not np.all(a > 0):
            raise ValueError(f"{nm} not finite/positive on the calendar")
    iso = cal.isocalendar()
    wkey = (iso["year"].astype(np.int64).values * 100 + iso["week"].astype(np.int64).values)
    week_last = np.r_[wkey[1:] != wkey[:-1], True]
    week_id = np.r_[0, np.cumsum(wkey[1:] != wkey[:-1])]
    week_start = np.flatnonzero(np.r_[True, wkey[1:] != wkey[:-1]])
    return {"cal": cal, "P": P, "gold": gold, "cash": cash, "alt": alt, "carry": carry, "week_last": week_last,
            "week_id": week_id, "week_start": week_start}


def window_bounds(cal: pd.DatetimeIndex, window: str) -> tuple[int, int]:
    base, rule, end = WINDOWS[window]
    if rule == "exact":
        t0 = cal.get_loc(base)
    else:
        t0 = int(np.searchsorted(cal.values, base.to_datetime64(), side="right") - 1)
    e = cal.get_loc(end)
    return int(t0), int(e)


def decision_positions(sp: dict, window: str, daily: bool) -> np.ndarray:
    t0, end = window_bounds(sp["cal"], window)
    if daily:
        return np.arange(t0, end + 1)
    wl = np.flatnonzero(sp["week_last"])
    D = np.unique(np.r_[t0, wl[(wl > t0) & (wl <= end)]])
    if D[-1] != end:
        raise AssertionError(f"{window}: the window end is not a decision session")
    return D


# ----------------------------------------------------------------------------------------------
# Signals (vectorised over decision sessions; each reads P only up to its own session)
# ----------------------------------------------------------------------------------------------
def cfg_kind(cfg: str) -> dict:
    if cfg == "pct_w65_q25_daily":
        return {"kind": "pct", "W": 65, "q": 25, "daily": True}
    if cfg == "pct_w65_hyst":
        return {"kind": "hyst", "W": 65, "daily": False}
    if cfg == "pct_w65_step":
        return {"kind": "step", "W": 65, "daily": False}
    if cfg.startswith("pct_w"):
        w, q = cfg[5:].split("_q")
        return {"kind": "pct", "W": int(w), "q": int(q), "daily": False}
    if cfg.startswith("sma_"):
        return {"kind": "sma", "n": int(cfg[4:]), "daily": False}
    if cfg.startswith("tsmom_"):
        return {"kind": "tsmom", "L": int(cfg[6:]), "daily": False}
    if cfg.startswith("ddhigh_250_x"):
        x = {"x7p5": 7.5, "x10": 10.0, "x15": 15.0}[cfg[11:]]
        return {"kind": "ddhigh", "N": 250, "X": x, "daily": False}
    if cfg == "st_weekly":
        return {"kind": "st", "daily": False}
    if cfg == "triple":
        return {"kind": "triple", "daily": False}
    if cfg == "triple_and_pct25":
        return {"kind": "triple_pct", "W": 65, "daily": False}
    raise KeyError(cfg)


def pct_counts(P: np.ndarray, D: np.ndarray, W: int) -> np.ndarray:
    if D.min() < W:
        raise AssertionError(f"pct W={W}: fewer than W previous closes at a decision")
    out = np.empty(len(D), dtype=np.int64)
    for j, i in enumerate(D):
        out[j] = np.count_nonzero(P[i - W:i] < P[i])
    return out


def weekly_candles(P: np.ndarray, week_start: np.ndarray, upto: int | None = None):
    """Candles of each ISO week; if upto is given, the series is cut at session `upto` (inclusive)."""
    if upto is None:
        starts = week_start
        ends = np.r_[week_start[1:], len(P)]
    else:
        starts = week_start[week_start <= upto]
        ends = np.r_[starts[1:], upto + 1]
    H = np.array([P[a:b].max() for a, b in zip(starts, ends)])
    L = np.array([P[a:b].min() for a, b in zip(starts, ends)])
    C = np.array([P[b - 1] for b in ends])
    return H, L, C


def supertrend(H: np.ndarray, L: np.ndarray, C: np.ndarray, mult: float = 2.0, n: int = 5, start: int = 5):
    """Production ST.py weekly supertrend. Returns ST, FUB, FLB (NaN before `start`)."""
    m = len(C)
    TR = np.empty(m)
    TR[0] = H[0] - L[0]
    for j in range(1, m):
        TR[j] = max(H[j] - L[j], abs(H[j] - C[j - 1]), abs(L[j] - C[j - 1]))
    w = np.arange(1, n + 1) / np.sum(np.arange(1, n + 1))
    st = np.full(m, np.nan)
    fub = np.full(m, np.nan)
    flb = np.full(m, np.nan)
    for j in range(start, m):
        eatr = float(np.sum(w * TR[j - n + 1:j + 1]))
        ahml = 0.5 * H[j] + 0.5 * L[j]
        bub = ahml + mult * eatr
        blb = ahml - mult * eatr
        if j == start:
            fu, fl, s = bub, blb, bub
        else:
            pfu, pfl, ps, pc, c = fub[j - 1], flb[j - 1], st[j - 1], C[j - 1], C[j]
            fu = bub if (bub < pfu or pc > pfu) else pfu
            fl = blb if (blb > pfl or pc < pfl) else pfl
            if ps == pfu and c <= fu:
                s = fu
            elif ps == pfu and c > fu:
                s = fl
            elif ps == pfl and c >= fl:
                s = fl
            elif ps == pfl and c < fu:
                s = fu
            else:
                s = 0.0
        fub[j], flb[j], st[j] = fu, fl, s
    return st, fub, flb


def st_at(P: np.ndarray, sp: dict, i: int, full: tuple, mode: str | None = None):
    """(value, weight, last input position) of st_weekly at session i, using P up to i only.

    At a session that is not the last of its ISO week, mode 'last_complete' (the adopted reading, see
    INTERPRETATIONS) uses the last complete week's candle, whose last session is the last input used;
    mode 'partial' (diagnostic, the reading this file first pre-declared) builds that week's candle from
    the closes up to i."""
    mode = mode or sp.get("st_midweek", ST_MIDWEEK_DEFAULT)
    wid = sp["week_id"][i]
    st, fub, _flb, C = full
    if sp["week_last"][i]:
        s, fu, c, last = st[wid], fub[wid], C[wid], i
    elif mode == "last_complete":
        s, fu, c, last = st[wid - 1], fub[wid - 1], C[wid - 1], int(sp["week_start"][wid] - 1)
    else:
        H, L, Cp = weekly_candles(P, sp["week_start"], upto=i)
        stp, fubp, _ = supertrend(H, L, Cp)
        s, fu, c, last = stp[-1], fubp[-1], Cp[-1], i
    if not np.isfinite(s):
        raise AssertionError("st_weekly undefined at a decision session")
    return float(c - s), (0.0 if s == fu else 1.0), last


def triple_counts(raw: dict, dates: pd.DatetimeIndex, with_labels: bool = False):
    """Number of the three Master SIGNs that are BUY on the latest label <= each date (and that label)."""
    cnt = np.zeros(len(dates), dtype=np.int64)
    latest = np.full(len(dates), np.datetime64("NaT"), dtype="datetime64[ns]")
    for key, (md, sign) in raw["masters"].items():
        pos = np.searchsorted(md.values, dates.values, side="right") - 1
        if (pos < 0).any():
            raise AssertionError(f"{key}: no Master label on or before a decision session")
        cnt += (sign[pos] == "BUY").astype(np.int64)
        lab = md.values[pos]
        latest = np.where(np.isnat(latest) | (lab > latest), lab, latest)
    return (cnt, pd.DatetimeIndex(latest)) if with_labels else cnt


def signals(cfg: str, parent: str, window: str, sp: dict, raw: dict, st_full: dict) -> dict:
    """Decision positions, values and equity targets of one config on one parent and window."""
    k = cfg_kind(cfg)
    P = sp["P"][parent]
    D = decision_positions(sp, window, k["daily"])
    dates = sp["cal"][D]
    if k["kind"] in ("pct", "hyst", "step", "triple_pct"):
        W = k["W"]
        cnt = pct_counts(P, D, W)
        value = 100.0 * cnt / W
        if k["kind"] == "pct":
            e = np.where(100 * cnt < k["q"] * W, 0.0, 1.0)
        elif k["kind"] == "step":
            e = np.where(100 * cnt >= 50 * W, 1.0, np.where(100 * cnt >= 25 * W, 0.5, 0.0))
        elif k["kind"] == "hyst":
            e = np.empty(len(D))
            state = 1.0
            for j, c in enumerate(cnt):
                if 100 * c < 25 * W:
                    state = 0.0
                elif 100 * c >= 50 * W:
                    state = 1.0
                e[j] = state
        else:
            tri = triple_counts(raw, dates)
            e = np.where((tri == 3) & (100 * cnt >= 25 * W), 1.0, 0.0)
    elif k["kind"] == "sma":
        n = k["n"]
        if D.min() < n - 1:
            raise AssertionError("sma: too little history")
        sma = np.array([P[i - n + 1:i + 1].mean() for i in D])
        value = P[D] / sma - 1.0
        e = np.where(P[D] < sma, 0.0, 1.0)
    elif k["kind"] == "tsmom":
        L = k["L"]
        if D.min() < L:
            raise AssertionError("tsmom: too little history")
        value = P[D] / P[D - L] - 1.0
        e = np.where(value < 0, 0.0, 1.0)
    elif k["kind"] == "ddhigh":
        N = k["N"]
        if D.min() < N - 1:
            raise AssertionError("ddhigh: too little history")
        mx = np.array([P[i - N + 1:i + 1].max() for i in D])
        value = P[D] / mx - 1.0
        e = np.where(value < -k["X"] / 100.0, 0.0, 1.0)
    elif k["kind"] == "st":
        full = st_full[parent]
        mode = sp.get("st_midweek", ST_MIDWEEK_DEFAULT)
        other = "last_complete" if mode == "partial" else "partial"
        vw = [st_at(P, sp, i, full, mode) for i in D]
        value = np.array([v for v, _, _ in vw])
        e = np.array([w for _, w, _ in vw])
        last = sp["cal"][[x for _, _, x in vw]]
        # diagnostic only: the value under the other reading at mid-week decision sessions
        alt = np.array([st_at(P, sp, i, full, other)[0] if not sp["week_last"][i] else np.nan for i in D])
        return {"D": D, "dates": dates, "value": value, "e": e, "alt_value": alt, "last_input": last}
    elif k["kind"] == "triple":
        tri, labels = triple_counts(raw, dates, with_labels=True)
        value = tri.astype(float)
        e = np.where(tri == 3, 1.0, 0.0)
        return {"D": D, "dates": dates, "value": value, "e": e, "last_input": labels}
    else:
        raise KeyError(cfg)
    return {"D": D, "dates": dates, "value": np.asarray(value, dtype=float), "e": np.asarray(e, dtype=float)}


def st_full_cache(sp: dict) -> dict:
    out = {}
    for parent in PARENTS:
        H, L, C = weekly_candles(sp["P"][parent], sp["week_start"])
        st, fub, flb = supertrend(H, L, C)
        out[parent] = (st, fub, flb, C)
    return out


# ----------------------------------------------------------------------------------------------
# Execution
# ----------------------------------------------------------------------------------------------
def sleeve_weights(e: float, sleeve: str) -> np.ndarray:
    if sleeve == "gold_cash":
        return np.array([e, (1.0 - e) / 2.0, (1.0 - e) / 2.0])
    return np.array([e, 0.0, 1.0 - e])


def trade_schedule(D: np.ndarray, e: np.ndarray):
    """Trades (decision index j, trade position, target) for a target series on decision sessions D."""
    out = []
    last = None
    for j in range(len(D) - 1):          # the last decision session's target is never traded
        if j == 0 or e[j] != last:
            out.append((j, int(D[j] + 1), float(e[j])))
            last = float(e[j])
    return out


def closed_form_nav(trades, px: np.ndarray, end: int, sleeve: str) -> float:
    """T01.md section 3 step 10, zero cost: V_end = prod_j sum_a w_aj close_a(e_j+1) / close_a(e_j)."""
    V = 1.0
    for j, (_dj, s, e) in enumerate(trades):
        nxt = trades[j + 1][1] if j + 1 < len(trades) else end
        w = sleeve_weights(e, sleeve)
        V *= float(np.sum(w * px[:, nxt] / px[:, s]))
    return V


def simulate(trades, px: np.ndarray, t0: int, end: int, sleeve: str, cost_bps: float, want_path: bool = False):
    """T01.md section 3 steps 6-7, this file's own code. Returns nav_end, trade log, daily NAV path."""
    ow = cost_bps / 2.0 / 10000.0
    units = np.zeros(3)
    cash = 1.0
    log = []
    path = np.ones(end - t0 + 1) if want_path else None
    for j, (dj, s, e) in enumerate(trades):
        p = px[:, s]
        nav_before = cash + float(np.sum(units * p))
        delta = sleeve_weights(e, sleeve) * nav_before - units * p
        traded_value = 0.0
        for a in range(3):                         # every trim first
            if delta[a] < 0:
                units[a] -= (-delta[a]) / p[a]
                cash += (-delta[a]) * (1.0 - ow)
                traded_value += -delta[a]
        for a in range(3):                         # then top-ups: equity, GOLDBEES, LBES
            if delta[a] > 0:
                v = min(delta[a], cash)
                units[a] += v * (1.0 - ow) / p[a]
                cash -= v
                traded_value += v
        nav_after = cash + float(np.sum(units * p))
        log.append({"j": dj, "pos": s, "kind": "build" if j == 0 else "switch",
                    "from": None if j == 0 else trades[j - 1][2], "to": e,
                    "nav_before": nav_before, "nav_after": nav_after, "traded": traded_value})
        if want_path:
            nxt = trades[j + 1][1] if j + 1 < len(trades) else end
            path[s - t0] = nav_after
            if nxt > s + 1:
                seg = slice(s + 1, nxt)
                path[s + 1 - t0:nxt - t0] = cash + units @ px[:, seg]
    p = px[:, end]
    nav_before = cash + float(np.sum(units * p))
    traded_value = float(np.sum(units * p))
    cash += float(np.sum(units * p * (1.0 - ow)))
    units[:] = 0.0
    log.append({"j": None, "pos": end, "kind": "liquidate", "from": trades[-1][2], "to": None,
                "nav_before": nav_before, "nav_after": cash, "traded": traded_value})
    if want_path:
        path[end - t0] = cash
    return cash, log, path


def simulate_many(Wk: np.ndarray, D: np.ndarray, px: np.ndarray, end: int, sleeve: str, cost_bps: float) -> np.ndarray:
    """The same engine, vectorised over rows of Wk (rotated target series). Returns nav_end per row.

    At decision j (not the last) a row trades iff j == 0 or its target differs from its target at j-1,
    which is the target it last traded (every changed target before the last session is traded). Only
    the rows that trade at j are touched. Trims (delta < 0) first, then top-ups in the order equity,
    GOLDBEES, LBES, each capped by the cash account, as in simulate()."""
    ow = cost_bps / 2.0 / 10000.0
    nd, N = Wk.shape
    units = np.zeros((nd, 3))
    cash = np.ones(nd)
    for j in range(N - 1):
        if j == 0:
            idx = np.arange(nd)
        else:
            idx = np.flatnonzero(Wk[:, j] != Wk[:, j - 1])
            if idx.size == 0:
                continue
        s = int(D[j] + 1)
        p = px[:, s]
        u = units[idx]
        c = cash[idx]
        nav_now = c + u @ p
        ej = Wk[idx, j]
        if sleeve == "gold_cash":
            tw = np.column_stack([ej, (1.0 - ej) / 2.0, (1.0 - ej) / 2.0])
        else:
            tw = np.column_stack([ej, np.zeros(idx.size), 1.0 - ej])
        delta = tw * nav_now[:, None] - u * p
        trim = np.minimum(delta, 0.0)
        u = u + trim / p
        for a in range(3):
            c = c + (-trim[:, a]) * (1.0 - ow)
        top = np.maximum(delta, 0.0)
        for a in range(3):
            v = np.minimum(top[:, a], c)
            u[:, a] = u[:, a] + v * (1.0 - ow) / p[a]
            c = c - v
        units[idx] = u
        cash[idx] = c
    p = px[:, end]
    for a in range(3):
        cash += units[:, a] * p[a] * (1.0 - ow)
    return cash


def stats_from_path(path: np.ndarray) -> dict:
    sessions = len(path)
    years = (sessions - 1) / 252.0
    nav_end = float(path[-1])
    cagr = nav_end ** (1.0 / years) - 1.0
    r = path[1:] / path[:-1] - 1.0
    vol1 = float(np.std(r, ddof=1) * math.sqrt(252.0))
    vol0 = float(np.std(r, ddof=0) * math.sqrt(252.0))
    mdd = float(np.min(path / np.maximum.accumulate(path) - 1.0))
    return {"nav_end": nav_end, "total_return": nav_end - 1.0, "cagr": cagr, "vol_ddof1": vol1,
            "vol_ddof0": vol0, "max_dd": mdd, "calmar": (cagr / abs(mdd)) if mdd != 0 else float("nan")}


def target_counts(e: np.ndarray) -> dict:
    vals, cnts = np.unique(e, return_counts=True)
    return {f"{v:.4f}": int(c) for v, c in zip(vals, cnts)}


def n_spells(e: np.ndarray) -> int:
    s = (e < 1.0).astype(int)
    return int(np.sum((s[1:] == 1) & (s[:-1] == 0)) + s[0])


def null_ks(N: int, daily: bool) -> list[int]:
    m = 40 if daily else 8
    return list(range(m, N - m + 1))


# ----------------------------------------------------------------------------------------------
# Re-derivation of everything for one sleeve
# ----------------------------------------------------------------------------------------------
def rederive(sp: dict, raw: dict, sleeve: str, with_paths: bool = True) -> dict:
    stc = st_full_cache(sp)
    real = {}
    for window in WINDOWS:
        t0, end = window_bounds(sp["cal"], window)
        for book, parent in BOOK_PARENT.items():
            px = np.vstack([sp["P"][parent], sp["gold"], sp["cash"]])
            bh_path = sp["P"][parent][t0:end + 1] / sp["P"][parent][t0]
            real[("bh", book, window)] = {"stats": stats_from_path(bh_path), "path": bh_path,
                                           "nav_end": float(sp["P"][parent][end] / sp["P"][parent][t0])}
            for cfg in CONFIGS:
                sig = signals(cfg, parent, window, sp, raw, stc)
                tr = trade_schedule(sig["D"], sig["e"])
                rec = {"sig": sig, "trades": tr, "parent": parent, "t0": t0, "end": end, "sleeve": sleeve,
                       "closed_form0": closed_form_nav(tr, px, end, sleeve)}
                for c in COSTS:
                    nav, log, path = simulate(tr, px, t0, end, sleeve, c, want_path=with_paths)
                    rec[c] = {"nav_end": nav, "log": log, "path": path,
                              "stats": stats_from_path(path) if with_paths else None}
                real[(cfg, book, window)] = rec
    return real


# ----------------------------------------------------------------------------------------------
# Comparison helpers
# ----------------------------------------------------------------------------------------------
class Check:
    def __init__(self, name: str, max_examples: int):
        self.name = name
        self.compared = 0
        self.failures = 0
        self.missing = 0
        self.extra = 0
        self.examples = []
        self.info = {}
        self.max_examples = max_examples

    def fail(self, what: str, **detail):
        self.failures += 1
        if len(self.examples) < self.max_examples:
            self.examples.append({"what": what, **{k: _js(v) for k, v in detail.items()}})

    def to_json(self) -> dict:
        return {"compared": self.compared, "failures": self.failures, "missing_rows": self.missing,
                "extra_rows": self.extra, "passed": self.compared > 0 and self.failures == 0,
                "info": self.info, "examples": self.examples}


def _js(v):
    if isinstance(v, (np.floating,)):
        return float(v)
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, tuple):
        return [_js(x) for x in v]
    if isinstance(v, float) and not math.isfinite(v):
        return str(v)
    return v


def rel_ok(a: float, b: float, tol: float) -> bool:
    if not (math.isfinite(a) and math.isfinite(b)):
        return False
    return abs(a - b) <= tol * max(abs(b), 1e-300)


def stat_ok(a: float, b: float, tol: float = TOL_STAT) -> bool:
    if not (math.isfinite(a) and math.isfinite(b)):
        return (not math.isfinite(a)) and (not math.isfinite(b))
    return abs(a - b) <= tol * max(1.0, abs(b))


def norm_date(col: pd.Series) -> pd.Series:
    s = col.astype("string").fillna("").str.strip()
    out = pd.Series([""] * len(s), index=s.index, dtype=object)
    nz = s != ""
    if nz.any():
        out[nz] = pd.to_datetime(s[nz]).dt.strftime("%Y-%m-%d").values
    return out


def norm_cost(col: pd.Series) -> pd.Series:
    return pd.to_numeric(col, errors="coerce").round(6)


def norm_bool(col: pd.Series) -> pd.Series:
    return col.astype(str).str.strip().str.lower().isin(["true", "1", "1.0", "t", "yes"])


def read_csv(run_dir: Path, name: str) -> pd.DataFrame:
    p = run_dir / name
    if not p.exists():
        raise FileNotFoundError(f"evidence file missing: {p}")
    # pandas' default NA strings include "null", which is a legitimate value of realisations.kind;
    # so only these strings are read as missing.
    return pd.read_csv(p, dtype={"config": str, "book": str, "window": str, "parent": str, "kind": str,
                                 "sleeve": str},
                       keep_default_na=False, na_values=["", "nan", "NaN", "NA", "<NA>", "N/A"],
                       float_precision="round_trip")


# ----------------------------------------------------------------------------------------------
# The checks
# ----------------------------------------------------------------------------------------------
def check_splice(run_dir: Path, sp: dict, mx: int) -> Check:
    ck = Check("a_splice", mx)
    ev = read_csv(run_dir, "spliced_inputs.csv")
    ev["date"] = norm_date(ev["date"])
    mine_dates = [d.strftime("%Y-%m-%d") for d in sp["cal"]]
    ev_dates = ev["date"].tolist()
    set_m, set_e = set(mine_dates), set(ev_dates)
    for d in sorted(set_m - set_e):
        ck.missing += 1
        ck.fail("calendar session missing from spliced_inputs.csv", date=d)
    for d in sorted(set_e - set_m):
        ck.extra += 1
        ck.fail("extra session in spliced_inputs.csv", date=d)
    if ev["date"].duplicated().any():
        ck.fail("duplicate dates in spliced_inputs.csv", n=int(ev["date"].duplicated().sum()))
    ev = ev.drop_duplicates("date").set_index("date").reindex(mine_dates)
    cols = {f"P_{p}": sp["P"][p] for p in PARENTS}
    cols.update({"gold": sp["gold"], "cash": sp["cash"]})
    maxabs, maxrel = {}, {}
    for col, mine in cols.items():
        if col not in ev.columns:
            ck.fail("column missing from spliced_inputs.csv", column=col)
            continue
        theirs = pd.to_numeric(ev[col], errors="coerce").values
        ok_rows = np.isfinite(theirs)
        diff = np.abs(theirs - mine)
        rel = diff / np.abs(mine)
        maxabs[col] = float(np.nanmax(diff)) if ok_rows.any() else None
        maxrel[col] = float(np.nanmax(rel)) if ok_rows.any() else None
        bad = (~ok_rows) | (rel > TOL_SPLICE_REL)
        ck.compared += int(len(mine))
        for i in np.flatnonzero(bad):
            ck.fail("spliced value differs", column=col, date=mine_dates[i], mine=float(mine[i]),
                    theirs=float(theirs[i]) if np.isfinite(theirs[i]) else "NaN")
    ck.info["max_abs_diff"] = maxabs
    ck.info["max_rel_diff"] = maxrel
    ck.info["tolerance_rel"] = TOL_SPLICE_REL
    # diagnostics on readings
    for col, alt in (("gold", sp["alt"]["gold"]), ("cash", sp["alt"]["cash"])):
        if col in ev.columns:
            th = pd.to_numeric(ev[col], errors="coerce").values
            ck.info[f"{col}_vs_other_reading_{sp['alt']['reading']}"] = {
                "max_abs_diff": float(np.nanmax(np.abs(th - alt))),
                "n_sessions_differ": int(np.sum(np.abs(th - alt) > 1e-12 * np.abs(alt)))}
    pcols = [f"P_{p}" for p in PARENTS]
    if all(c in ev.columns for c in pcols) and "2021-11-01" in ev.index and "2021-10-29" in ev.index:
        ck.info["evidence_zero_return_2021_11_01_exact"] = {
            c: bool(float(ev.loc["2021-11-01", c]) == float(ev.loc["2021-10-29", c])) for c in pcols}
    return ck


def my_decision_rows(real: dict, sp: dict) -> pd.DataFrame:
    rows = []
    cal = sp["cal"]
    for (cfg, book, window), rec in real.items():
        if cfg == "bh":
            continue
        sig = rec["sig"]
        traded_j = {dj: s for dj, s, _e in rec["trades"]}
        alt = sig.get("alt_value", np.full(len(sig["D"]), np.nan))
        last = sig.get("last_input", sig["dates"])
        for j, (i, v, e) in enumerate(zip(sig["D"], sig["value"], sig["e"])):
            ts = cal[traded_j[j]].strftime("%Y-%m-%d") if j in traded_j else ""
            rows.append((cfg, book, window, cal[i].strftime("%Y-%m-%d"), float(v), float(e), ts, j in traded_j,
                         float(alt[j]), last[j].strftime("%Y-%m-%d")))
    return pd.DataFrame(rows, columns=["config", "book", "window", "decision_date", "value_m", "e_m",
                                       "ts_m", "traded_m", "alt_value_m", "last_input_m"])


def check_decisions(run_dir: Path, real: dict, sp: dict, mx: int) -> tuple[Check, Check]:
    ck = Check("b_decisions", mx)
    ev = read_csv(run_dir, "decisions_all_configs.csv")
    need = ["config", "book", "window", "decision_date", "value", "equity_target", "data_last_date",
            "trade_session", "traded"]
    for c in need:
        if c not in ev.columns:
            ck.fail("column missing from decisions_all_configs.csv", column=c)
    if ck.failures:
        return ck, Check("b2_decisions_reference", mx)
    ev = ev.copy()
    ev["decision_date"] = norm_date(ev["decision_date"])
    ev["data_last_date"] = norm_date(ev["data_last_date"])
    ev["trade_session"] = norm_date(ev["trade_session"])
    ev["traded_e"] = norm_bool(ev["traded"])
    ev["value_e"] = pd.to_numeric(ev["value"], errors="coerce")
    ev["e_e"] = pd.to_numeric(ev["equity_target"], errors="coerce")
    key = ["config", "book", "window", "decision_date"]
    dup = ev.duplicated(key)
    if dup.any():
        ck.extra += int(dup.sum())
        ck.fail("duplicate decision rows", n=int(dup.sum()))
    mine = my_decision_rows(real, sp)
    m = mine.merge(ev[~dup], on=key, how="outer", indicator=True)
    miss = m[m["_merge"] == "left_only"]
    extra = m[m["_merge"] == "right_only"]
    ck.missing += len(miss)
    ck.extra += len(extra)
    for _, r in miss.head(mx).iterrows():
        ck.fail("decision row missing from evidence", key=tuple(r[key]))
    ck.failures += max(0, len(miss) - min(len(miss), mx))
    for _, r in extra.head(mx).iterrows():
        ck.fail("extra decision row in evidence", key=tuple(r[key]))
    ck.failures += max(0, len(extra) - min(len(extra), mx))
    both = m[m["_merge"] == "both"]
    ck.compared = len(both)
    bad_e = both["e_m"].values != both["e_e"].values
    vdiff = np.abs(both["value_m"].values - both["value_e"].values)
    bad_v = ~(vdiff <= TOL_VALUE_ABS)
    bad_ts = both["ts_m"].values != both["trade_session"].values
    bad_tr = both["traded_m"].values != both["traded_e"].values
    # data_last_date gates on point in time only (present, and not after the decision session); its
    # equality with the decision date and with this file's own last-input date is reported, not gated
    dl = both["data_last_date"].values
    bad_dl = (dl == "") | (dl > both["decision_date"].values)
    ck.info["data_last_date_equals_decision_date"] = int(np.sum(dl == both["decision_date"].values))
    neq_last = dl != both["last_input_m"].values
    ck.info["data_last_date_equals_own_last_input_date"] = int(np.sum(~neq_last))
    ck.info["data_last_date_differs_from_own_last_input_date_by_config"] = \
        both[neq_last].groupby("config").size().astype(int).to_dict()
    ck.info["equity_target_mismatches"] = int(bad_e.sum())
    ck.info["value_mismatches"] = int(bad_v.sum())
    ck.info["trade_session_mismatches"] = int(bad_ts.sum())
    ck.info["traded_mismatches"] = int(bad_tr.sum())
    ck.info["data_last_date_point_in_time_violations"] = int(bad_dl.sum())
    ck.info["max_abs_value_diff"] = float(np.nanmax(vdiff)) if len(vdiff) else None
    bad_any = bad_e | bad_v | bad_ts | bad_tr | bad_dl
    ck.info["mismatched_rows_by_config"] = both[bad_any].groupby("config").size().astype(int).to_dict()
    alt_hit = bad_v & (np.abs(both["alt_value_m"].values - both["value_e"].values) <= TOL_VALUE_ABS)
    ck.info["st_weekly_midweek_reading_used"] = sp.get("st_midweek", ST_MIDWEEK_DEFAULT)
    ck.info["st_weekly_value_mismatches_matching_the_other_midweek_reading"] = int(alt_hit.sum())
    for idx in np.flatnonzero(bad_any):
        r = both.iloc[idx]
        what = ",".join(n for n, b in (("equity_target", bad_e[idx]), ("value", bad_v[idx]),
                                       ("trade_session", bad_ts[idx]), ("traded", bad_tr[idx]),
                                       ("data_last_date after decision_date or empty", bad_dl[idx])) if b)
        ck.fail(f"decision mismatch: {what}", key=tuple(r[key]), mine_e=float(r["e_m"]),
                theirs_e=float(r["e_e"]) if np.isfinite(r["e_e"]) else "NaN",
                mine_value=float(r["value_m"]),
                theirs_value=float(r["value_e"]) if np.isfinite(r["value_e"]) else "NaN",
                mine_ts=r["ts_m"], theirs_ts=r["trade_session"])
    ck.info["rows_expected"] = len(mine)

    # decisions_reference.csv == the pct_w65_q25 rows of decisions_all_configs.csv
    ck2 = Check("b2_decisions_reference", mx)
    ref = read_csv(run_dir, "decisions_reference.csv")
    sub = ev[ev["config"] == REFERENCE].copy()
    cols = [c for c in need]
    if set(need) - set(ref.columns):
        ck2.fail("decisions_reference.csv lacks columns", missing=sorted(set(need) - set(ref.columns)))
        return ck, ck2
    ref = ref.copy()
    for c in ("decision_date", "data_last_date", "trade_session"):
        ref[c] = norm_date(ref[c])
    if not (ref["config"] == REFERENCE).all():
        ck2.fail("decisions_reference.csv has rows for other configs",
                 n=int((ref["config"] != REFERENCE).sum()))
    def canon(df):
        out = df[cols].copy()
        for c in ("value", "equity_target"):
            out[c] = pd.to_numeric(out[c], errors="coerce").astype(float).map(repr)
        out["traded"] = norm_bool(out["traded"])
        return out.astype(str).sort_values(key).reset_index(drop=True)

    a = canon(sub)
    b = canon(ref)
    ck2.compared = len(b)
    if len(a) != len(b):
        ck2.fail("row count differs from the pct_w65_q25 rows of decisions_all_configs.csv",
                 reference=len(b), all_configs=len(a))
    else:
        neq = (a != b).any(axis=1)
        for i in np.flatnonzero(neq.values)[:mx]:
            ck2.fail("row differs", ref=b.iloc[i].to_dict(), all_configs=a.iloc[i].to_dict())
        ck2.failures += max(0, int(neq.sum()) - min(int(neq.sum()), mx))
    n_mine_ref = int((mine["config"] == REFERENCE).sum())
    if len(b) != n_mine_ref:
        ck2.fail("reference row count differs from the re-derived count", theirs=len(b), mine=n_mine_ref)
    return ck, ck2


def realisation_frame(run_dir: Path) -> pd.DataFrame:
    ev = read_csv(run_dir, "realisations.csv")
    ev = ev.copy()
    ev["cost"] = norm_cost(ev["cost_bps"])
    ev["k"] = pd.to_numeric(ev["shift_k"], errors="coerce")
    if ev["k"].notna().any():
        frac = (ev["k"].dropna() % 1 != 0)
        if frac.any():
            raise ValueError("non-integer shift_k values in realisations.csv")
    ev["k"] = ev["k"].fillna(-1).astype(np.int64)
    ev["nav_end_f"] = pd.to_numeric(ev["nav_end"], errors="coerce")
    return ev


def check_strategy_navs(ev: pd.DataFrame, real: dict, sleeve: str, mx: int):
    """(c) closed form at cost 0, (d) own cost engine at 20.8, (h) the other strategy-row fields."""
    ckc = Check("c_closed_form_cost0", mx)
    ckd = Check("d_cost_engine_20p8", mx)
    ckh = Check("h_strategy_fields", mx)
    strat = ev[ev["kind"] == "strategy"]
    key = ["config", "book", "window", "cost"]
    dup = strat.duplicated(key)
    if dup.any():
        ckc.fail("duplicate strategy rows", n=int(dup.sum()))
        ckc.extra += int(dup.sum())
    strat = strat[~dup].set_index(key)
    expected = [(cfg, book, w, c) for cfg in CONFIGS for book in BOOK_PARENT for w in WINDOWS for c in COSTS]
    exp_set = set(expected)
    for k in strat.index:
        if k not in exp_set:
            (ckc if k[3] == 0.0 else ckd).extra += 1
            (ckc if k[3] == 0.0 else ckd).fail("unexpected strategy row", key=k)
    vol_divisor = {"ddof1": 0, "ddof0": 0, "neither": 0}
    for (cfg, book, w, c) in expected:
        ck = ckc if c == 0.0 else ckd
        if (cfg, book, w, c) not in strat.index:
            ck.missing += 1
            ck.fail("strategy row missing", key=(cfg, book, w, c))
            continue
        r = strat.loc[(cfg, book, w, c)]
        rec = real[(cfg, book, w)]
        mine = rec["closed_form0"] if c == 0.0 else rec[c]["nav_end"]
        theirs = float(r["nav_end_f"])
        ck.compared += 1
        if not rel_ok(theirs, mine, TOL_NAV_REL):
            ck.fail("nav_end differs", key=(cfg, book, w, c), mine=mine, theirs=theirs,
                    rel=(theirs - mine) / mine if math.isfinite(theirs) else "NaN")
        if str(r.get("sleeve", sleeve)) != sleeve:
            ck.fail("sleeve column differs", key=(cfg, book, w, c), theirs=str(r.get("sleeve")))
        if str(r.get("parent", BOOK_PARENT[book])) != BOOK_PARENT[book]:
            ck.fail("parent column differs", key=(cfg, book, w, c), theirs=str(r.get("parent")))
        # (h) the other fields
        e = rec["sig"]["e"]
        st = rec[c]["stats"]
        n_sw = len(rec["trades"]) - 1
        exp_fields = {
            "n_decisions": float(len(e)), "n_switches": float(n_sw), "n_spells": float(n_spells(e)),
            "share_sleeve_weeks": float(np.mean(e < 1.0)), "avg_equity_weight": float(np.mean(e)),
            "total_return": st["total_return"], "cagr": st["cagr"], "max_dd": st["max_dd"],
            "calmar": st["calmar"]}
        for f, mv in exp_fields.items():
            ckh.compared += 1
            tv = pd.to_numeric(pd.Series([r.get(f)]), errors="coerce").iloc[0]
            if not stat_ok(float(tv), mv):
                ckh.fail(f"{f} differs", key=(cfg, book, w, c), mine=mv, theirs=float(tv))
        tv = float(pd.to_numeric(pd.Series([r.get("vol")]), errors="coerce").iloc[0])
        ts = float(pd.to_numeric(pd.Series([r.get("sharpe")]), errors="coerce").iloc[0])
        ckh.compared += 2
        if stat_ok(tv, st["vol_ddof1"]):
            vol_divisor["ddof1"] += 1
            sh = st["cagr"] / st["vol_ddof1"]
        elif stat_ok(tv, st["vol_ddof0"]):
            vol_divisor["ddof0"] += 1
            sh = st["cagr"] / st["vol_ddof0"]
        else:
            vol_divisor["neither"] += 1
            sh = float("nan")
            ckh.fail("vol differs (neither SD divisor)", key=(cfg, book, w, c), mine_ddof1=st["vol_ddof1"],
                     mine_ddof0=st["vol_ddof0"], theirs=tv)
        if math.isfinite(sh) and not stat_ok(ts, sh):
            ckh.fail("sharpe differs", key=(cfg, book, w, c), mine=sh, theirs=ts)
        ckh.compared += 1
        try:
            tl = json.loads(str(r.get("target_level_counts")))
            tl = {f"{float(k):.4f}": int(v) for k, v in tl.items()}
        except Exception:
            tl = None
        if tl != target_counts(e):
            ckh.fail("target_level_counts differs", key=(cfg, book, w, c), mine=target_counts(e),
                     theirs=str(r.get("target_level_counts")))
    ckh.info["vol_divisor_matched"] = vol_divisor
    return ckc, ckd, ckh


def check_bh(ev: pd.DataFrame, real: dict, mx: int) -> Check:
    ck = Check("e_bh", mx)
    bh = ev[ev["kind"] == "bh"]
    key = ["book", "window"]
    if bh.duplicated(key).any():
        ck.extra += int(bh.duplicated(key).sum())
        ck.fail("duplicate bh rows", n=int(bh.duplicated(key).sum()))
    bh = bh[~bh.duplicated(key)].set_index(key)
    for k in bh.index:
        if k not in {(b, w) for b in BOOK_PARENT for w in WINDOWS}:
            ck.extra += 1
            ck.fail("unexpected bh row", key=k)
    for book in BOOK_PARENT:
        for w in WINDOWS:
            if (book, w) not in bh.index:
                ck.missing += 1
                ck.fail("bh row missing", key=(book, w))
                continue
            r = bh.loc[(book, w)]
            rec = real[("bh", book, w)]
            ck.compared += 1
            if not rel_ok(float(r["nav_end_f"]), rec["nav_end"], TOL_NAV_REL):
                ck.fail("bh nav_end differs", key=(book, w), mine=rec["nav_end"], theirs=float(r["nav_end_f"]))
            if str(r.get("config")) != "bh" or float(r["cost"]) != 0.0:
                ck.fail("bh row config/cost not ('bh', 0)", key=(book, w), config=str(r.get("config")),
                        cost=float(r["cost"]))
            for f in ("cagr", "max_dd", "total_return"):
                ck.compared += 1
                tv = float(pd.to_numeric(pd.Series([r.get(f)]), errors="coerce").iloc[0])
                if not stat_ok(tv, rec["stats"][f]):
                    ck.fail(f"bh {f} differs", key=(book, w), mine=rec["stats"][f], theirs=tv)
    return ck


def _parse_tlc(x, cache: dict):
    if x not in cache:
        try:
            cache[x] = {f"{float(a):.4f}": int(b) for a, b in json.loads(str(x)).items()}
        except Exception:  # noqa: BLE001
            cache[x] = None
    return cache[x]


def check_nulls(ev: pd.DataFrame, real: dict, sp: dict, sleeve: str, mx: int) -> Check:
    """(f) every null draw: rotated targets through this file's engine; complete k set; V3 level counts."""
    ck = Check("f_null_rows", mx)
    nul = ev[ev["kind"] == "null"]
    key = ["config", "book", "window", "cost", "k"]
    dup = nul.duplicated(key)
    if dup.any():
        ck.extra += int(dup.sum())
        ck.fail("duplicate null rows", n=int(dup.sum()))
    nul = nul[~dup]
    groups = {k: g for k, g in nul.groupby(["config", "book", "window", "cost"])}
    expected_groups = set()
    direction = None
    other_dir_would_match = 0
    tlc_cache = {}
    n_tlc_bad = 0
    for (cfg, book, w), rec in real.items():
        if cfg == "bh":
            continue
        parent = rec["parent"]
        px = np.vstack([sp["P"][parent], sp["gold"], sp["cash"]])
        e = rec["sig"]["e"]
        D = rec["sig"]["D"]
        ks = null_ks(len(e), cfg_kind(cfg)["daily"])
        kset = set(ks)
        my_tlc = target_counts(e)
        for c in COSTS:
            expected_groups.add((cfg, book, w, c))
            g = groups.get((cfg, book, w, c))
            if g is None:
                ck.missing += len(ks)
                ck.fail("no null rows for realisation", key=(cfg, book, w, c), expected=len(ks))
                continue
            got = dict(zip(g["k"].astype(int), g["nav_end_f"].astype(float)))
            tl = dict(zip(g["k"].astype(int), g["target_level_counts"])) if "target_level_counts" in g.columns else {}
            miss = [k for k in ks if k not in got]
            extra = [k for k in got if k not in kset]
            if miss:
                ck.missing += len(miss)
                ck.fail("null draws missing", key=(cfg, book, w, c), n=len(miss), first=miss[:5])
            if extra:
                ck.extra += len(extra)
                ck.fail("unexpected null draws", key=(cfg, book, w, c), n=len(extra), first=extra[:5])
            kk = [k for k in ks if k in got]
            if not kk:
                continue
            th = np.array([got[k] for k in kk])

            def run(sign):
                nav = simulate_many(np.stack([np.roll(e, sign * k) for k in kk]), D, px, rec["end"], sleeve, c)
                return nav, np.abs(th - nav) <= TOL_NAV_REL * np.abs(nav)

            if direction is None:
                # both signs are tried until a group matches fully under one sign and not the other;
                # that sign is then fixed for every remaining group
                navp, okp = run(+1)
                navm, okm = run(-1)
                fp, fm = int((~okp).sum()), int((~okm).sum())
                tentative = +1 if fp <= fm else -1
                if min(fp, fm) == 0 and max(fp, fm) > 0:
                    direction = tentative
                    ck.info["rotation_decided_on"] = [cfg, book, w, c]
                    ck.info["deciding_group_mismatches_plus_minus"] = [fp, fm]
                else:
                    ck.info.setdefault("undecided_groups", 0)
                    ck.info["undecided_groups"] += 1
                mine, ok = (navp, okp) if tentative == +1 else (navm, okm)
            else:
                mine, ok = run(direction)
                if (~ok).any():
                    _nav_o, ok_o = run(-direction)
                    other_dir_would_match += int(((~ok) & ok_o).sum())
            ck.compared += 2 * len(kk)
            for i in np.flatnonzero(~ok):
                ck.fail("null nav_end differs", key=(cfg, book, w, c, kk[i]), mine=float(mine[i]), theirs=float(th[i]))
            for k in kk:
                if _parse_tlc(tl.get(k), tlc_cache) != my_tlc:
                    n_tlc_bad += 1
                    ck.fail("null target_level_counts differs from the strategy's (V3)", key=(cfg, book, w, c, k))
    for k, g in groups.items():
        if k not in expected_groups:
            ck.extra += len(g)
            ck.fail("null rows for an unexpected realisation", key=k, n=len(g))
    ck.info["rotation_matched"] = {+1: "np.roll(w, +k): w'_i = w_(i-k mod N)",
                                   -1: "np.roll(w, -k): w'_i = w_(i+k mod N)",
                                   None: "undecided: no group matched under exactly one sign"}[direction]
    ck.info["mismatches_that_the_other_direction_would_match"] = other_dir_would_match
    ck.info["target_level_count_mismatches"] = n_tlc_bad
    return ck


def check_trades(run_dir: Path, real: dict, sp: dict, sleeve: str, mx: int) -> Check:
    ck = Check("g_trades", mx)
    ev = read_csv(run_dir, "trades.csv").copy()
    ev["cost"] = norm_cost(ev["cost_bps"])
    ev["trade_session"] = norm_date(ev["trade_session"])
    ev["decision_date"] = norm_date(ev["decision_date"])
    key = ["config", "book", "window", "cost", "trade_session", "kind"]
    dup = ev.duplicated(key)
    if dup.any():
        ck.extra += int(dup.sum())
        ck.fail("duplicate trade rows", n=int(dup.sum()))
    ev = ev[~dup].set_index(key)
    cal = sp["cal"]
    seen = set()
    vt_ok = 0
    vt_n = 0
    for (cfg, book, w), rec in real.items():
        if cfg == "bh":
            continue
        D = rec["sig"]["D"]
        for c in COSTS:
            for t in rec[c]["log"]:
                k = (cfg, book, w, c, cal[t["pos"]].strftime("%Y-%m-%d"), t["kind"])
                seen.add(k)
                if k not in ev.index:
                    ck.missing += 1
                    ck.fail("trade missing", key=k)
                    continue
                r = ev.loc[k]
                ck.compared += 1
                dd = cal[D[t["j"]]].strftime("%Y-%m-%d") if t["j"] is not None else ""
                bad = []
                if r["decision_date"] != dd:
                    bad.append("decision_date")
                if t["to"] is not None and float(r["to_equity"]) != t["to"]:
                    bad.append("to_equity")
                if t["from"] is not None and float(r["from_equity"]) != t["from"]:
                    bad.append("from_equity")
                if not rel_ok(float(r["nav_before"]), t["nav_before"], TOL_NAV_REL):
                    bad.append("nav_before")
                if not rel_ok(float(r["nav_after"]), t["nav_after"], TOL_NAV_REL):
                    bad.append("nav_after")
                if str(r.get("sleeve", sleeve)) != sleeve:
                    bad.append("sleeve")
                if bad:
                    ck.fail("trade differs: " + ",".join(bad), key=k, mine={kk: t[kk] for kk in
                            ("from", "to", "nav_before", "nav_after")},
                            theirs={"decision_date": r["decision_date"], "from": r["from_equity"],
                                    "to": r["to_equity"], "nav_before": r["nav_before"],
                                    "nav_after": r["nav_after"]})
                if "value_traded_frac" in r.index:
                    vt_n += 1
                    if stat_ok(float(r["value_traded_frac"]), t["traded"] / t["nav_before"], 1e-9):
                        vt_ok += 1
    for k in ev.index:
        if k not in seen:
            ck.extra += 1
            ck.fail("extra trade in evidence", key=k)
    ck.info["value_traded_frac_matches_sum_abs_delta_over_nav_before"] = f"{vt_ok} of {vt_n} (report only)"
    return ck


def check_daily_reference(run_dir: Path, real: dict, sp: dict, mx: int) -> Check:
    ck = Check("i_daily_reference", mx)
    ev = read_csv(run_dir, "daily_reference.csv").copy()
    ev["cost"] = norm_cost(ev["cost_bps"])
    ev["date"] = norm_date(ev["date"])
    key = ["book", "window", "cost", "date"]
    dup = ev.duplicated(key)
    if dup.any():
        ck.extra += int(dup.sum())
        ck.fail("duplicate daily rows", n=int(dup.sum()))
    ev = ev[~dup].set_index(key).sort_index()
    cal = sp["cal"]
    wmatch, wn = 0, 0
    n_expected = 0
    for book, parent in BOOK_PARENT.items():
        for w in WINDOWS:
            rec = real[(REFERENCE, book, w)]
            t0, end = rec["t0"], rec["end"]
            dates = [d.strftime("%Y-%m-%d") for d in cal[t0:end + 1]]
            bh = real[("bh", book, w)]["path"]
            for c in COSTS:
                path = rec[c]["path"]
                n_expected += len(dates)
                try:
                    sub = ev.loc[(book, w, c)]
                except KeyError:
                    ck.missing += len(dates)
                    ck.fail("no daily rows for realisation", key=(book, w, c))
                    continue
                sub = sub.reindex(dates)
                nav = pd.to_numeric(sub["nav"], errors="coerce").values
                navbh = pd.to_numeric(sub["nav_bh"], errors="coerce").values
                miss = np.isnan(nav)
                ck.missing += int(miss.sum())
                if miss.any():
                    ck.fail("daily rows missing", key=(book, w, c), n=int(miss.sum()))
                ck.compared += 2 * len(dates)
                b1 = ~(np.abs(nav - path) <= TOL_NAV_REL * np.abs(path))
                b2 = ~(np.abs(navbh - bh) <= TOL_NAV_REL * np.abs(bh))
                for i in np.flatnonzero((b1 | b2) & ~miss)[:mx]:
                    ck.fail("daily nav differs", key=(book, w, c, dates[i]), mine=float(path[i]),
                            theirs=float(nav[i]), mine_bh=float(bh[i]), theirs_bh=float(navbh[i]))
                nb = int(((b1 | b2) & ~miss).sum())
                ck.failures += max(0, nb - min(nb, mx))
                # drifted weights at each close, report only (w_cash = LBES + the trading cash account)
                wts = daily_weights(rec, c, sp, parent)
                for col, j in (("w_equity", 0), ("w_gold", 1), ("w_cash", 2)):
                    if col in sub.columns:
                        tv = pd.to_numeric(sub[col], errors="coerce").values
                        mv = wts[:, j]
                        wn += len(tv)
                        wmatch += int(np.sum(np.abs(tv - mv) <= 1e-9))
    ck.info["rows_expected"] = n_expected
    extra = len(ev) - n_expected + ck.missing
    if extra > 0:
        ck.extra += extra
        ck.fail("extra rows in daily_reference.csv", n=int(extra))
    ck.info["drifted_weights_match_within_1e-9"] = f"{wmatch} of {wn} (report only; w_cash includes the cash account)"
    return ck


def daily_weights(rec: dict, c: float, sp: dict, parent: str) -> np.ndarray:
    """Actual drifted weights at each close, T0..end (re-runs the scalar engine with units recorded)."""
    t0, end = rec["t0"], rec["end"]
    px = np.vstack([sp["P"][parent], sp["gold"], sp["cash"]])
    ow = c / 2.0 / 10000.0
    out = np.zeros((end - t0 + 1, 3))
    units = np.zeros(3)
    cash = 1.0
    tr = rec["trades"]
    tpos = {s: e for _j, s, e in tr}
    for t in range(t0, end + 1):
        p = px[:, t]
        if t in tpos:
            nav_now = cash + float(np.sum(units * p))
            delta = sleeve_weights(tpos[t], rec["sleeve"]) * nav_now - units * p
            for a in range(3):
                if delta[a] < 0:
                    units[a] -= (-delta[a]) / p[a]
                    cash += (-delta[a]) * (1.0 - ow)
            for a in range(3):
                if delta[a] > 0:
                    v = min(delta[a], cash)
                    units[a] += v * (1.0 - ow) / p[a]
                    cash -= v
        if t == end:                                   # final liquidation at the last close
            cash += float(np.sum(units * p * (1.0 - ow)))
            units[:] = 0.0
        nav = cash + float(np.sum(units * p))
        out[t - t0] = units * p / nav
        out[t - t0, 2] += cash / nav                   # w_cash counts the trading cash account too
    return out



# ----------------------------------------------------------------------------------------------
# Driver
# ----------------------------------------------------------------------------------------------
def run_checks(run_dir: Path, sleeve: str, mx: int, skip_nulls: bool, ctx: dict) -> dict:
    t_start = time.time()
    sp, raw = ctx["sp"], ctx["raw"]
    if ctx.get("real_sleeve") != sleeve:
        ctx["real"] = rederive(sp, raw, sleeve)
        ctx["real_sleeve"] = sleeve
    real = ctx["real"]
    checks = []
    checks.append(check_splice(run_dir, sp, mx))
    b, b2 = check_decisions(run_dir, real, sp, mx)
    checks += [b, b2]
    ev = realisation_frame(run_dir)
    bad_sleeve = ev["sleeve"].astype(str) != sleeve if "sleeve" in ev.columns else pd.Series(False, index=ev.index)
    c, d, h = check_strategy_navs(ev, real, sleeve, mx)
    checks += [c, d]
    checks.append(check_bh(ev, real, mx))
    if not skip_nulls:
        checks.append(check_nulls(ev, real, sp, sleeve, mx))
    checks.append(check_trades(run_dir, real, sp, sleeve, mx))
    checks.append(h)
    checks.append(check_daily_reference(run_dir, real, sp, mx))
    if bad_sleeve.any():
        c.fail("rows in realisations.csv with another sleeve", n=int(bad_sleeve.sum()))
    known = {"strategy", "null", "bh"}
    unk = ~ev["kind"].isin(known)
    if unk.any():
        c.extra += int(unk.sum())
        c.fail("rows in realisations.csv with an unknown kind", n=int(unk.sum()))
    out = {c_.name: c_.to_json() for c_ in checks}
    total_cmp = sum(v["compared"] for v in out.values())
    total_fail = sum(v["failures"] for v in out.values())
    total_missing = sum(v["missing_rows"] for v in out.values())
    total_extra = sum(v["extra_rows"] for v in out.values())
    every_check_compared = all(v["compared"] > 0 for v in out.values())
    passed = total_cmp > 0 and every_check_compared and total_fail == 0 and total_missing == 0 and total_extra == 0
    return {"run_dir": str(run_dir), "sleeve": sleeve, "checks": out, "total_compared": total_cmp,
            "total_failures": total_fail, "total_missing_rows": total_missing, "total_extra_rows": total_extra,
            "every_check_compared_rows": every_check_compared, "nulls_checked": not skip_nulls,
            "verdict": "PASS" if passed else "FAIL", "elapsed_s": round(time.time() - t_start, 1)}


def provenance() -> dict:
    return {k: {"path": str(p), "size": p.stat().st_size, "sha256": sha256(p)} for k, p in RAW.items()}


def corrupt_copy(src: Path, dst_root: Path) -> tuple[Path, list]:
    dst = dst_root / src.name
    shutil.copytree(src, dst)
    planted = []
    dec_p = dst / "decisions_all_configs.csv"
    dec = pd.read_csv(dec_p, dtype=str, keep_default_na=False)
    e = pd.to_numeric(dec["equity_target"], errors="coerce")
    cand = np.flatnonzero(((e == 0.0) | (e == 1.0)).values)
    if len(cand) < 3:
        raise RuntimeError("corrupt test: fewer than 3 decision rows with target 0 or 1")
    for idx in (cand[len(cand) // 7], cand[len(cand) // 2], cand[(6 * len(cand)) // 7]):
        old = float(e.iloc[idx])
        dec.loc[dec.index[idx], "equity_target"] = repr(1.0 - old)
        r = dec.iloc[idx]
        planted.append({"file": "decisions_all_configs.csv", "check": "b_decisions",
                        "key": [r["config"], r["book"], r["window"],
                                pd.Timestamp(r["decision_date"]).strftime("%Y-%m-%d")],
                        "change": f"equity_target {old} -> {1.0 - old}"})
    dec.to_csv(dec_p, index=False)
    rea_p = dst / "realisations.csv"
    rea = pd.read_csv(rea_p, dtype=str, keep_default_na=False)
    cost = pd.to_numeric(rea["cost_bps"], errors="coerce").round(6)
    for cval, chk in ((0.0, "c_closed_form_cost0"), (20.8, "d_cost_engine_20p8")):
        idxs = np.flatnonzero(((rea["kind"] == "strategy") & (cost == cval)).values)
        if not len(idxs):
            raise RuntimeError(f"corrupt test: no strategy rows at cost {cval}")
        idx = idxs[len(idxs) // 3]
        old = float(rea.iloc[idx]["nav_end"])
        rea.loc[rea.index[idx], "nav_end"] = repr(old * 1.001)
        r = rea.iloc[idx]
        planted.append({"file": "realisations.csv", "check": chk,
                        "key": [r["config"], r["book"], r["window"], cval],
                        "change": f"nav_end x 1.001 ({old} -> {old * 1.001})"})
    rea.to_csv(rea_p, index=False)
    return dst, planted


def detected(result: dict, p: dict) -> bool:
    ex = result["checks"][p["check"]]["examples"]
    for x in ex:
        k = x.get("key")
        if k is None:
            continue
        k = list(k) if isinstance(k, (list, tuple)) else [k]
        if p["check"] == "b_decisions" and k[:4] == p["key"]:
            return True
        if p["check"] != "b_decisions" and k[:3] == p["key"][:3] and float(k[3]) == float(p["key"][3]):
            return True
    return False


def self_test(ctx: dict) -> int:
    sp, raw = ctx["sp"], ctx["raw"]
    cal = sp["cal"]
    ok = True
    print(f"calendar: {len(cal)} sessions {cal[0].date()} -> {cal[-1].date()}")
    for w in WINDOWS:
        t0, end = window_bounds(cal, w)
        Dw = decision_positions(sp, w, False)
        print(f"{w}: T0 {cal[t0].date()} (pos {t0}), end {cal[end].date()} (pos {end}), "
              f"{len(Dw)} weekly decision sessions incl. T0, {end - t0 + 1} sessions")
    print("LBES as-of vs calendar-ffill: differ on",
          int(np.sum(sp["cash"] != sp["alt"]["cash"])), "sessions; gold:", int(np.sum(sp["gold"] != sp["alt"]["gold"])))
    for sleeve in SLEEVES:
        real = rederive(sp, raw, sleeve)
        worst = 0.0
        for (cfg, book, w), rec in real.items():
            if cfg == "bh":
                continue
            r = abs(rec[0.0]["nav_end"] / rec["closed_form0"] - 1.0)
            worst = max(worst, r)
            # path end equals nav_end; path from the scalar engine at both costs
            for c in COSTS:
                if rec[c]["path"][-1] != rec[c]["nav_end"]:
                    ok = False
                    print("FAIL path end != nav_end", cfg, book, w, c)
        flag = worst <= 1e-12
        ok &= flag
        print(f"[{sleeve}] closed form vs cost engine at 0 bps, all 30 configs x 4 books x 2 windows: "
              f"max rel diff {worst:.2e} -> {'OK' if flag else 'FAIL'}")
        # vectorised vs scalar on k = 0 and a few rotations
        worst_v = 0.0
        for (cfg, book, w), rec in real.items():
            if cfg == "bh":
                continue
            parent = rec["parent"]
            px = np.vstack([sp["P"][parent], sp["gold"], sp["cash"]])
            e, D = rec["sig"]["e"], rec["sig"]["D"]
            ks = [0] + null_ks(len(e), cfg_kind(cfg)["daily"])[:: max(1, len(e) // 6)]
            for c in COSTS:
                vm = simulate_many(np.stack([np.roll(e, k) for k in ks]), D, px, rec["end"], sleeve, c)
                for k, v in zip(ks, vm):
                    ek = np.roll(e, k)
                    sv, _, _ = simulate(trade_schedule(D, ek), px, rec["t0"], rec["end"], sleeve, c)
                    worst_v = max(worst_v, abs(v / sv - 1.0))
                    if c == 0.0:
                        cf = closed_form_nav(trade_schedule(D, ek), px, rec["end"], sleeve)
                        worst_v = max(worst_v, abs(v / cf - 1.0))
        flag = worst_v <= 1e-12
        ok &= flag
        print(f"[{sleeve}] vectorised null engine vs scalar engine / closed form (k=0 and rotations): "
              f"max rel diff {worst_v:.2e} -> {'OK' if flag else 'FAIL'}")
        if sleeve == "gold_cash":
            print("\nReference config pct_w65_q25, sleeve gold_cash:")
            print(f"{'book':10s} {'win':3s} {'N':>4s} {'sleeve':>6s} {'sw':>3s} {'spells':>6s} "
                  f"{'closed@0':>10s} {'engine@0':>10s} {'engine@20.8':>11s} {'B&H':>9s} "
                  f"{'CAGR@20.8':>9s} {'DD@20.8':>8s} {'DD B&H':>8s}")
            for w in WINDOWS:
                for book in BOOK_PARENT:
                    rec = real[(REFERENCE, book, w)]
                    e = rec["sig"]["e"]
                    bh = real[("bh", book, w)]
                    s20 = rec[20.8]["stats"]
                    print(f"{book:10s} {w:3s} {len(e):4d} {np.mean(e < 1):6.3f} {len(rec['trades']) - 1:3d} "
                          f"{n_spells(e):6d} {rec['closed_form0']:10.6f} {rec[0.0]['nav_end']:10.6f} "
                          f"{rec[20.8]['nav_end']:11.6f} {bh['nav_end']:9.6f} {s20['cagr']:9.4f} "
                          f"{s20['max_dd']:8.4f} {bh['stats']['max_dd']:8.4f}")
            rec = real[(REFERENCE, "SCMO_0042", "W2")]
            print("\nFirst 8 decisions, pct_w65_q25, SCMO_0042, W2 (date, p_d, target, trade session):")
            tj = {j: s for j, s, _ in rec["trades"]}
            for j in range(8):
                i = rec["sig"]["D"][j]
                print(f"  {cal[i].date()}  p={rec['sig']['value'][j]:7.3f}  e={rec['sig']['e'][j]:.1f}  "
                      f"trade={cal[tj[j]].date() if j in tj else '-'}")
            print("\nPer-config summary, SCMO_0042 W1 / W2 (share of decisions in the sleeve, switches, "
                  "nav_end @20.8):")
            for cfg in CONFIGS:
                parts = []
                for w in WINDOWS:
                    rec = real[(cfg, "SCMO_0042", w)]
                    e = rec["sig"]["e"]
                    parts.append(f"{w} {np.mean(e < 1):5.3f} {len(rec['trades']) - 1:4d} {rec[20.8]['nav_end']:8.4f}")
                print(f"  {cfg:20s} " + " | ".join(parts))
            st_zero = sum(int(np.sum(ctx_st[0] == 0.0)) for ctx_st in st_full_cache(sp).values())
            print(f"\nst_weekly: candles with ST == 0 (production's degenerate branch): {st_zero}")
    # point-in-time self-check: every value recomputed on P truncated at d
    print("\nPoint-in-time self-check (signal recomputed on P[:d+1] only, triple on labels <= d):")
    stc = st_full_cache(sp)
    worst_pit = 0
    n_pit = 0
    for w in WINDOWS:
        for book, parent in BOOK_PARENT.items():
            for cfg in CONFIGS:
                sig = signals(cfg, parent, w, sp, raw, stc)
                step = 1 if cfg != "pct_w65_q25_daily" else 7
                for j in range(0, len(sig["D"]), step if cfg not in ("st_weekly",) else 9):
                    i = int(sig["D"][j])
                    v, e = truncated_signal(cfg, sp["P"][parent][:i + 1], sp, raw, i, w, j, sig)
                    n_pit += 1
                    if not (v == sig["value"][j] or abs(v - sig["value"][j]) <= 1e-12) or e != sig["e"][j]:
                        worst_pit += 1
                        if worst_pit <= 5:
                            print("  PIT mismatch", cfg, book, w, cal[i].date(), v, sig["value"][j], e, sig["e"][j])
    flag = worst_pit == 0 and n_pit > 0
    ok &= flag
    print(f"  {n_pit} decisions recomputed, {worst_pit} mismatches -> {'OK' if flag else 'FAIL'}")
    print("\nSELF-TEST", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def truncated_signal(cfg: str, Pt: np.ndarray, sp: dict, raw: dict, i: int, window: str, j: int, sig: dict):
    """Scalar recomputation of one decision from the truncated series (independent code path)."""
    k = cfg_kind(cfg)
    d = sp["cal"][i]
    x = Pt[-1]

    def pct(W):
        prev = Pt[-1 - W:-1]
        assert len(prev) == W
        return int(sum(1 for y in prev if y < x))

    def tri():
        n = 0
        for _key, (md, sign) in raw["masters"].items():
            m = md <= d
            n += int(sign[np.flatnonzero(m)[-1]] == "BUY")
        return n

    if k["kind"] == "pct":
        c = pct(k["W"])
        return 100.0 * c / k["W"], (0.0 if 100 * c < k["q"] * k["W"] else 1.0)
    if k["kind"] == "step":
        c = pct(65)
        return 100.0 * c / 65, (1.0 if 100 * c >= 50 * 65 else (0.5 if 100 * c >= 25 * 65 else 0.0))
    if k["kind"] == "hyst":
        D = sig["D"][:j + 1]
        state = 1.0
        for ii in D:
            prev = Pt[ii - 65:ii]
            c = int(np.sum(prev < Pt[ii]))
            if 100 * c < 25 * 65:
                state = 0.0
            elif 100 * c >= 50 * 65:
                state = 1.0
        return 100.0 * pct(65) / 65, state
    if k["kind"] == "triple_pct":
        c = pct(65)
        return 100.0 * c / 65, (1.0 if (tri() == 3 and 100 * c >= 25 * 65) else 0.0)
    if k["kind"] == "triple":
        n = tri()
        return float(n), (1.0 if n == 3 else 0.0)
    if k["kind"] == "sma":
        m = float(np.mean(Pt[-k["n"]:]))
        return x / m - 1.0, (0.0 if x < m else 1.0)
    if k["kind"] == "tsmom":
        v = x / Pt[-1 - k["L"]] - 1.0
        return v, (0.0 if v < 0 else 1.0)
    if k["kind"] == "ddhigh":
        v = x / float(np.max(Pt[-250:])) - 1.0
        return v, (0.0 if v < -k["X"] / 100.0 else 1.0)
    if k["kind"] == "st":
        ws = sp["week_start"][sp["week_start"] <= i]
        ends = np.r_[ws[1:], i + 1]
        H = np.array([Pt[a:b].max() for a, b in zip(ws, ends)])
        L = np.array([Pt[a:b].min() for a, b in zip(ws, ends)])
        C = np.array([Pt[b - 1] for b in ends])
        if not sp["week_last"][i] and sp.get("st_midweek", ST_MIDWEEK_DEFAULT) == "last_complete":
            H, L, C = H[:-1], L[:-1], C[:-1]       # drop the incomplete week
        st, fub, _ = supertrend(H, L, C)
        return float(C[-1] - st[-1]), (0.0 if st[-1] == fub[-1] else 1.0)
    raise KeyError(cfg)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--run-dir", type=str, help="evidence run directory (e.g. AA/tests/T01/evidence/headline)")
    ap.add_argument("--sleeve", choices=SLEEVES, help="gold_cash for headline, cash for cash_sleeve")
    ap.add_argument("--out", type=str, default=None, help="JSON report path (default AA/tests/T01/verify_<run>.json)")
    ap.add_argument("--corrupt-test", action="store_true", help="check the checker on a corrupted temp copy")
    ap.add_argument("--self-test", action="store_true", help="internal consistency checks, no evidence needed")
    ap.add_argument("--skip-nulls", action="store_true", help="skip check (f), the null rows")
    ap.add_argument("--max-examples", type=int, default=25)
    ap.add_argument("--st-midweek", choices=["partial", "last_complete"], default=ST_MIDWEEK_DEFAULT,
                    help="The adopted reading is last_complete (see INTERPRETATIONS; changed from partial "
                         "on 2026-10-01 at integration). DIAGNOSTIC ONLY: partial re-runs every check with "
                         "st_weekly at a mid-week decision read from a partial candle of that week")
    ap.add_argument("--lbes-carry", choices=["asof", "calendar"], default=LBES_CARRY_DEFAULT,
                    help="DIAGNOSTIC ONLY. The pre-declared reading is asof (see INTERPRETATIONS); "
                         "calendar re-runs every check under the other reading to isolate its effect")
    args = ap.parse_args(argv)

    t_all = time.time()
    try:
        raw = load_raw()
        sp = build_splice(raw, carry=args.lbes_carry)
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR loading raw inputs: {exc}", file=sys.stderr)
        return 2
    sp["st_midweek"] = args.st_midweek
    ctx = {"raw": raw, "sp": sp}
    if args.self_test:
        return self_test(ctx)

    if not args.run_dir or not args.sleeve:
        ap.error("--run-dir and --sleeve are required (or use --self-test)")
    run_dir = Path(args.run_dir)
    if not run_dir.is_absolute() and not run_dir.exists():
        run_dir = REPO / args.run_dir
    if not run_dir.is_dir():
        print(f"ERROR: run dir not found: {args.run_dir}", file=sys.stderr)
        return 2
    run_dir = run_dir.resolve()
    default_out = REPO / "AA" / "tests" / "T01" / (
        f"verify_{run_dir.name}" + ("_corrupt" if args.corrupt_test else "") + ".json")
    out_path = Path(args.out) if args.out else default_out

    report = {"script": str(Path(__file__).resolve()),
              "purpose": "T01 gate V1: independent re-derivation of splice, signals, decisions, trades and NAVs",
              "imports_from_engine": "none", "inputs": provenance(), "interpretations": INTERPRETATIONS,
              "tolerances": {"splice_rel": TOL_SPLICE_REL, "value_abs": TOL_VALUE_ABS, "nav_rel": TOL_NAV_REL,
                             "stats": TOL_STAT},
              "sleeve_price_carry_reading_used": args.lbes_carry,
              "st_weekly_midweek_reading_used": args.st_midweek,
              "readings_changed_after_evidence": READINGS_CHANGED_AFTER_EVIDENCE,
              "diagnostic_reading_not_predeclared": (args.lbes_carry != LBES_CARRY_DEFAULT
                                                     or args.st_midweek != ST_MIDWEEK_DEFAULT)}
    try:
        if args.corrupt_test:
            tmp_root = Path(tempfile.mkdtemp(prefix="t01_corrupt_"))
            try:
                dst, planted = corrupt_copy(run_dir, tmp_root)
                res = run_checks(dst, args.sleeve, 10 ** 6, args.skip_nulls, ctx)
            finally:
                shutil.rmtree(tmp_root, ignore_errors=True)
            det = [dict(p, detected=detected(res, p)) for p in planted]
            all_det = all(p["detected"] for p in det)
            ok = res["verdict"] == "FAIL" and all_det
            report.update({"mode": "corrupt-test", "source_run_dir": str(run_dir), "planted": det,
                           "corrupted_copy_verdict": res["verdict"],
                           "corrupted_copy_failures": {k: v["failures"] for k, v in res["checks"].items()},
                           "verdict": "PASS (corrupted copy failed on every planted defect)" if ok else
                           "FAIL (a planted defect was not detected)"})
            code = 0 if ok else 1
        else:
            res = run_checks(run_dir, args.sleeve, args.max_examples, args.skip_nulls, ctx)
            report.update({"mode": "verify", **res})
            code = 0 if res["verdict"] == "PASS" else 1
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        report.update({"mode": "error", "error": str(exc), "verdict": "FAIL"})
        code = 2
    report["elapsed_total_s"] = round(time.time() - t_all, 1)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=_js)
    # console summary
    print(f"verify_own_momentum: mode={report.get('mode')} run={run_dir} sleeve={args.sleeve}")
    if report.get("mode") == "verify":
        for name, v in report["checks"].items():
            print(f"  {name:24s} compared {v['compared']:>8d}  failures {v['failures']:>6d}  "
                  f"missing {v['missing_rows']:>5d}  extra {v['extra_rows']:>5d}  {'PASS' if v['passed'] else 'FAIL'}")
    elif report.get("mode") == "corrupt-test":
        for p in report["planted"]:
            print(f"  planted {p['check']:22s} {p['key']}  detected={p['detected']}")
    print(f"  verdict: {report.get('verdict')}  -> {out_path}  (exit {code})")
    return code


if __name__ == "__main__":
    sys.exit(main())
