#!/usr/bin/env python
"""
own_momentum.py -- T01 engine: can a smallcase's own index momentum tell when to
move its weight into gold and cash?

Spec (frozen, never edited by this script): AA/tests/T01/T01.md, sections 1-3.
Framework: wm-research/AGENT.md section 8 (backtest convention) and section 11
(evidence). The one departure from section 8 is the one T01.md section 3 states:
every trade fills at the NEXT session's CLOSE (the parent index has closes only).

What it does, in the order of T01.md section 3 "Construction":
  1. splices each parent: harness rebuild up to 2021-10-29, then the published
     NAV rescaled so that P(2021-11-01) = P(2021-10-29) (a zero-return session);
  2. puts GOLDBEES close and the LBES level on the same session calendar, carrying
     gaps forward (as-of: the latest observation dated on or before the session);
  3. builds the weekly decision sessions (last session of each ISO week, plus T0);
  4. computes every config's signal at every decision session from P up to and
     including that session only (and asserts it, see "point in time" below);
  5. turns signals into targets (equity e, GOLDBEES and LBES split the rest);
  6. runs the units-based book: trims first, then top-ups in the order equity,
     GOLDBEES, LBES, each capped by the cash account, cost (1 - ow) on both sides,
     a trade only when the target changes, filled at the next session's close;
     build on T0's next session from cash; liquidate at the last session's close;
  7. NAV = cash account + sum(units x close), 1.0 at T0's close;
  8. statistics; B&H = P_t / P_T0;
  9. circular-shift null: every rotation k of the target series, through the
     identical engine at the same cost and sleeve;
 12. observed_se (Newey-West, 4 lags, weekly return difference vs a static mix).

It computes no percentile and no verdict: that is analyse.py's job.

Point in time (asserted, counted into audit.json):
  - every decision value is computed from the truncated array P[:i+1] (data up to
    and including the decision session d only) and must equal an independent
    full-history vectorised computation at d (a look-ahead detector);
  - the last input date used is <= d; the Master SIGN label used is <= d;
  - every trade session is strictly later than its decision session.

Usage (from the wm-research repo root):
  python AA/analysis/own_momentum.py --run headline    --sleeve gold_cash --out-dir AA/tests/T01/evidence/headline
  python AA/analysis/own_momentum.py --run cash_sleeve --sleeve cash      --out-dir AA/tests/T01/evidence/cash_sleeve

Exit code 0 only if the run completed, every self-check passed and the
point-in-time violation count is 0.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view

HERE = Path(__file__).resolve()
AA_DIR = HERE.parents[1]
REPO = HERE.parents[2]

INPUTS = {
    "published_parents": AA_DIR / "Historical Data" / "parentIndices.csv",
    "harness_parents": AA_DIR / "analysis" / "evidence" / "final_strategy" / "nav_curves_daily.csv",
    "goldbees": AA_DIR / "analysis" / "evidence" / "final_strategy" / "gold_daily_ohlc_eikon.csv",
    "lbes": AA_DIR / "Historical Data" / "LBES_Adjusted_Price_data_2026_08_10.csv",
    "master_nifty100": AA_DIR / "Historical Data" / "frozen_2026-09-25" / "Master" / "Master_Nifty100.xlsx",
    "master_mc100": AA_DIR / "Historical Data" / "frozen_2026-09-25" / "Master" / "Master_MC100.xlsx",
    "master_sc100": AA_DIR / "Historical Data" / "frozen_2026-09-25" / "Master" / "Master_SC100.xlsx",
}
MASTER_KEYS = ("master_nifty100", "master_mc100", "master_sc100")

BOOKS = {"SCMO_0042": "SCMO_0003", "SCMO_0043": "SCMO_0007",
         "SCMO_0044": "SCMO_0010", "SCMO_0045": "SCMO_0029"}
PARENTS = list(BOOKS.values())
HARNESS_COL = "before the books 2014-07 -> 2021-10|{book}|parent (no overlay)"
HARNESS_LAST = pd.Timestamp("2021-10-29")
PUB_FIRST = pd.Timestamp("2021-11-01")
PUB_FMT = "%d/%m/%y %H:%M"

WINDOWS = {
    "W1": {"t0_rule": "last session on or before 2015-07-31", "t0_on_or_before": pd.Timestamp("2015-07-31"),
           "end": pd.Timestamp("2021-10-29"), "source": "harness rebuild"},
    "W2": {"t0_rule": "2021-11-01", "t0_on_or_before": pd.Timestamp("2021-11-01"),
           "end": pd.Timestamp("2026-08-21"), "source": "published parent NAV"},
}
COSTS = (0.0, 20.8)
SLEEVES = {"gold_cash": 0.5, "cash": 0.0}     # GOLDBEES share of the non-equity part
WEEKLY_MIN_K = 8
DAILY_MIN_K = 40
NW_LAGS = 4
SQ252 = math.sqrt(252.0)
REF_CONFIG = "pct_w65_q25"


# ─────────────────────────────────────────────────────────────────── configs ──
def build_configs() -> dict:
    """The 28 pre-registered sweep configs and the 2 descriptive rows, in T01 order."""
    c = {}
    for W in (20, 40, 65, 130, 250):
        for q in (10, 25, 40):
            c[f"pct_w{W}_q{q}"] = {"kind": "pct", "W": W, "q": q, "freq": "W"}
    c["pct_w65_hyst"] = {"kind": "hyst", "W": 65, "lo": 25, "hi": 50, "freq": "W"}
    c["pct_w65_step"] = {"kind": "step", "W": 65, "lo": 25, "hi": 50, "freq": "W"}
    c["pct_w65_q25_daily"] = {"kind": "pct", "W": 65, "q": 25, "freq": "D"}
    for n in (50, 100, 200):
        c[f"sma_{n}"] = {"kind": "sma", "n": n, "freq": "W"}
    for L in (65, 130, 250):
        c[f"tsmom_{L}"] = {"kind": "tsmom", "L": L, "freq": "W"}
    for lab, X in (("x7p5", 7.5), ("x10", 10.0), ("x15", 15.0)):
        c[f"ddhigh_250_{lab}"] = {"kind": "ddhigh", "N": 250, "X": X, "freq": "W"}
    c["st_weekly"] = {"kind": "st", "mult": 2.0, "atr_n": 5, "freq": "W"}
    c["triple"] = {"kind": "triple", "freq": "W", "descriptive": True}
    c["triple_and_pct25"] = {"kind": "triple_pct", "W": 65, "q": 25, "freq": "W", "descriptive": True}
    assert len(c) == 30
    return c


CONFIG_PROSE = {
    "pct": "p_d = 100 x (count of the W previous closes P[d-W..d-1] strictly below P_d) / W; equity 0 if p_d < q else 1",
    "hyst": "p_d with W=65; exit to the sleeve when p_d < 25; re-enter equity only when p_d >= 50; otherwise keep the previous state (starts as equity at the window's T0)",
    "step": "p_d with W=65; equity 1 if p_d >= 50, 0.5 if 25 <= p_d < 50, 0 if p_d < 25",
    "sma": "equity 0 if P_d < mean(P[d-n+1..d]) else 1; value = P_d / SMA - 1",
    "tsmom": "value = P_d / P[d-L] - 1; equity 0 if value < 0 else 1",
    "ddhigh": "value = P_d / max(P[d-249..d]) - 1; equity 0 if value < -X/100 else 1",
    "st": "production ST.py getSupertrend on ISO-week candles of the spliced closes (H = max close, L = min close, C = last close; TR = max(H-L,|H-PC|,|L-PC|), first week H-L; 5-candle linear weights 1..5/15; multiplier 2; bands (H+L)/2 +- 2 ATR; production ratchet; starts on the 6th candle); equity 0 when the line is on the upper band (SELL), else 1; value = weekly close - line; a decision at d reads the latest completed week with label <= d",
    "triple": "equity 1 if Nifty100, MC100 and SC100 Master SIGN are all BUY on each file's latest week label <= d, else 0; value = number of the 3 that are BUY",
    "triple_pct": "triple AND p_d >= 25 (W = 65); value = p_d",
}


# ─────────────────────────────────────────────────────────────────── helpers ──
def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO).as_posix()
    except ValueError:
        return str(path)


def asof_on_calendar(s: pd.Series, cal: pd.DatetimeIndex) -> pd.Series:
    """Level at each session = latest observation dated on or before it (gaps carried forward)."""
    s = s.sort_index()
    s = s[~s.index.duplicated(keep="last")]
    return s.reindex(s.index.union(cal)).ffill().reindex(cal)


def iso_keys(dates: pd.DatetimeIndex) -> np.ndarray:
    iso = dates.isocalendar()
    return iso["year"].to_numpy().astype(np.int64) * 100 + iso["week"].to_numpy().astype(np.int64)


def fmt_date(ts) -> str:
    return "" if ts is None or (isinstance(ts, float) and np.isnan(ts)) else pd.Timestamp(ts).strftime("%Y-%m-%d")


def level_counts_json(eq: np.ndarray) -> str:
    lv, ct = np.unique(eq, return_counts=True)
    return json.dumps({f"{float(a):.4f}": int(b) for a, b in zip(lv, ct)})


def n_spells_of(eq: np.ndarray) -> int:
    s = eq < 1.0
    return int(s[0]) + int(np.count_nonzero(s[1:] & ~s[:-1]))


# ─────────────────────────────────────────────────────────────── data / splice ──
def load_inputs():
    """Steps 1 and 2: the spliced parents, the calendar and the sleeve prices."""
    nav = pd.read_csv(INPUTS["harness_parents"], index_col=0)
    nav.index = pd.to_datetime(nav.index)
    harness = {}
    for book, parent in BOOKS.items():
        col = HARNESS_COL.format(book=book)
        if col not in nav.columns:
            raise KeyError(f"harness column missing: {col}")
        s = nav[col].dropna().astype(float).sort_index()
        if s.index.duplicated().any():
            raise ValueError(f"duplicate harness dates in {col}")
        if s.index.max() != HARNESS_LAST:
            raise ValueError(f"harness {book} ends {s.index.max().date()}, expected {HARNESS_LAST.date()}")
        harness[parent] = s

    pub_raw = pd.read_csv(INPUTS["published_parents"])
    pub_raw["date"] = pd.to_datetime(pub_raw["date"], format=PUB_FMT)
    published = {}
    for parent in PARENTS:
        s = pub_raw.loc[pub_raw["scid"] == parent].set_index("date")["index"].astype(float).sort_index()
        if s.index.duplicated().any():
            raise ValueError(f"duplicate published dates for {parent}")
        if s.index.min() != PUB_FIRST:
            raise ValueError(f"published {parent} starts {s.index.min().date()}, expected {PUB_FIRST.date()}")
        published[parent] = s

    # the session calendar: the union of the two sources' dates
    cal = pd.DatetimeIndex(sorted(set().union(*[set(s.index) for s in harness.values()],
                                             *[set(s.index) for s in published.values()])))
    if (cal[(cal > HARNESS_LAST) & (cal < PUB_FIRST)]).size:
        raise ValueError("calendar has sessions between the harness end and the published start")

    P = {}
    for parent in PARENTS:
        h, p = harness[parent], published[parent]
        hpart = h.reindex(cal[cal <= HARNESS_LAST])
        ppart = p.reindex(cal[cal >= PUB_FIRST])
        if hpart.isna().any() or ppart.isna().any():
            raise ValueError(f"{parent}: missing a source value on a calendar session "
                             f"(harness {int(hpart.isna().sum())}, published {int(ppart.isna().sum())})")
        anchor = float(h.loc[HARNESS_LAST])
        spliced = pd.concat([hpart, anchor * ppart / float(p.loc[PUB_FIRST])])
        if not spliced.index.equals(cal):
            raise AssertionError("splice is not on the calendar")
        if not np.all(np.isfinite(spliced.to_numpy())) or (spliced <= 0).any():
            raise ValueError(f"{parent}: non-finite or non-positive spliced level")
        P[parent] = spliced

    g = pd.read_csv(INPUTS["goldbees"], parse_dates=["date"]).set_index("date")["close"].astype(float)
    lb = pd.read_csv(INPUTS["lbes"])
    lb["date"] = pd.to_datetime(lb["date"], format=PUB_FMT)
    lb = lb.set_index("date")["price"].astype(float)
    gold = asof_on_calendar(g, cal)
    cash = asof_on_calendar(lb, cal)
    for name, s in (("gold", gold), ("cash", cash)):
        if s.isna().any() or (s <= 0).any():
            raise ValueError(f"{name}: missing or non-positive level on the calendar")
    sleeve_info = {
        "gold_first_date": fmt_date(g.index.min()), "gold_last_date": fmt_date(g.index.max()),
        "lbes_first_date": fmt_date(lb.index.min()), "lbes_last_date": fmt_date(lb.index.max()),
        "lbes_sessions_forward_filled_past_file_end": int((cal > lb.index.max()).sum()),
        "gold_sessions_without_own_obs": int((~cal.isin(g.index)).sum()),
        "lbes_sessions_without_own_obs": int((~cal.isin(lb.index)).sum()),
    }
    return cal, P, gold, cash, harness, published, sleeve_info


def splice_check(cal, P, harness, published) -> dict:
    """V4: spliced daily returns equal the source returns on each side of the splice."""
    max_h, max_p, n = 0.0, 0.0, 0
    zero_ret = {}
    for parent in PARENTS:
        sp = P[parent]
        r_sp = sp.pct_change()
        h = harness[parent]
        r_h = h.pct_change().dropna()
        d_h = (r_sp.reindex(r_h.index) - r_h).abs()
        max_h = max(max_h, float(d_h.max()))
        n += int(d_h.size)
        pb = published[parent]
        r_p = pb.pct_change().dropna()
        r_p = r_p[r_p.index >= pd.Timestamp("2021-11-02")]
        d_p = (r_sp.reindex(r_p.index) - r_p).abs()
        max_p = max(max_p, float(d_p.max()))
        n += int(d_p.size)
        zero_ret[parent] = float(r_sp.loc[PUB_FIRST])
    return {"max_abs_diff_harness_side": max_h, "max_abs_diff_published_side": max_p, "n_compared": n,
            "splice_session_return_2021_11_01": zero_ret,
            "rule": "harness rebuild returns up to and including 2021-10-29; published returns from 2021-11-02; "
                    "the 2021-10-29 -> 2021-11-01 session return is 0 by construction",
            "pass_threshold": 1e-12,
            "pass": bool(max_h < 1e-12 and max_p < 1e-12)}


def load_master(cal) -> dict:
    out = {}
    for key in MASTER_KEYS:
        m = pd.read_excel(INPUTS[key], usecols=["Date", "SIGN"])
        m["Date"] = pd.to_datetime(m["Date"])
        m = m.dropna(subset=["Date"]).sort_values("Date")
        if m["Date"].duplicated().any():
            raise ValueError(f"{key}: duplicate week labels")
        bad = set(m["SIGN"].dropna().unique()) - {"BUY", "SELL"}
        if bad:
            raise ValueError(f"{key}: unexpected SIGN values {bad}")
        out[key] = (m["Date"].to_numpy(dtype="datetime64[ns]"), m["SIGN"].to_numpy())
    return out


# ─────────────────────────────────────────────────────────────── supertrend ──
def weekly_candles(keys: np.ndarray, closes: np.ndarray):
    starts = np.flatnonzero(np.r_[True, keys[1:] != keys[:-1]])
    ends = np.r_[starts[1:], len(keys)] - 1
    H = np.maximum.reduceat(closes, starts)
    L = np.minimum.reduceat(closes, starts)
    C = closes[ends]
    return starts, ends, H, L, C


def supertrend(H, L, C, mult=2.0, n=5):
    """Production ST.py getSupertrend, on candles; returns FUB, FLB, ST (NaN before candle index n)."""
    m = len(C)
    PC = np.r_[np.nan, C[:-1]]
    HML = H - L
    TR = HML.copy()
    if m > 1:
        TR[1:] = np.maximum(HML[1:], np.maximum(np.abs(H[1:] - PC[1:]), np.abs(L[1:] - PC[1:])))
    AHML = 0.5 * H + 0.5 * L
    wts = np.arange(1, n + 1, dtype=float) / float(np.sum(np.arange(1, n + 1)))
    FUB = np.full(m, np.nan)
    FLB = np.full(m, np.nan)
    ST = np.full(m, np.nan)
    for r in range(n, m):
        eatr = float(np.sum(wts * TR[r - n + 1:r + 1]))
        bub = AHML[r] + mult * eatr
        blb = AHML[r] - mult * eatr
        if r == n:
            fub, flb, st = bub, blb, bub
        else:
            pfub, pflb, pst = FUB[r - 1], FLB[r - 1], ST[r - 1]
            pclose, close = PC[r], C[r]
            fub = bub if (bub < pfub or pclose > pfub) else pfub
            flb = blb if (blb > pflb or pclose < pflb) else pflb
            if pst == pfub and close <= fub:
                st = fub
            elif pst == pfub and close > fub:
                st = flb
            elif pst == pflb and close >= flb:
                st = flb
            elif pst == pflb and close < fub:
                st = fub
            else:
                st = 0.0
        FUB[r], FLB[r], ST[r] = fub, flb, st
    return FUB, FLB, ST


# ───────────────────────────────────────────────────────────────── signals ──
class History(Exception):
    pass


def master_buy_count(master, d: np.datetime64):
    """Number of the 3 Master files that are BUY on their latest label <= d, and the labels used."""
    buys, labels = 0, []
    for key in MASTER_KEYS:
        dates, signs = master[key]
        j = int(np.searchsorted(dates, d, side="right")) - 1
        if j < 0:
            raise History(f"{key}: no Master label on or before {d}")
        labels.append(dates[j])
        buys += int(signs[j] == "BUY")
    return buys, labels


def signal_truncated(cfg, h: np.ndarray, i: int, d: pd.Timestamp, ctx) -> dict:
    """
    One decision's driving value and raw target, computed from h = P[:i+1] only
    (closes up to and including the decision session d). Raises History if the
    config is undefined at d.
    """
    if len(h) != i + 1:
        raise AssertionError("history is not truncated at d")
    k = cfg["kind"]
    out = {"last_idx": i, "label": None}
    if k in ("pct", "hyst", "step", "triple_pct"):
        W = cfg["W"]
        if i < W:
            raise History(f"{W} previous closes needed, {i} available")
        cnt = int(np.count_nonzero(h[i - W:i] < h[i]))
        out["value"] = 100.0 * cnt / W
        out["cnt"] = cnt
        if k == "pct":
            out["target"] = 0.0 if 100 * cnt < cfg["q"] * W else 1.0
        elif k == "step":
            out["target"] = 1.0 if 100 * cnt >= cfg["hi"] * W else (0.5 if 100 * cnt >= cfg["lo"] * W else 0.0)
        elif k == "hyst":
            out["target"] = None          # path dependent, set by the caller
        else:
            buys, labels = master_buy_count(ctx["master"], np.datetime64(d))
            out["master_labels"] = labels
            out["target"] = 1.0 if (buys == 3 and 100 * cnt >= cfg["q"] * W) else 0.0
    elif k == "sma":
        n = cfg["n"]
        if i < n:
            raise History(f"{n} previous closes needed, {i} available")
        m = float(np.mean(h[i - n + 1:i + 1]))
        out["value"] = h[i] / m - 1.0
        out["target"] = 0.0 if h[i] < m else 1.0
    elif k == "tsmom":
        L = cfg["L"]
        if i < L:
            raise History(f"{L} previous closes needed, {i} available")
        v = h[i] / h[i - L] - 1.0
        out["value"] = v
        out["target"] = 0.0 if v < 0.0 else 1.0
    elif k == "ddhigh":
        N = cfg["N"]
        if i < 250:
            raise History(f"250 previous closes needed, {i} available")
        v = h[i] / float(np.max(h[i - N + 1:i + 1])) - 1.0
        out["value"] = v
        out["target"] = 0.0 if v < -cfg["X"] / 100.0 else 1.0
    elif k == "st":
        keys = ctx["keys"][:i + 1]
        starts, ends, H, L, C = weekly_candles(keys, h)
        # keep only completed weeks: label (the week's last session in the calendar) <= d
        last_key = keys[ends[-1]]
        if ctx["week_label"][last_key] > d:
            starts, ends, H, L, C = starts[:-1], ends[:-1], H[:-1], L[:-1], C[:-1]
        if len(C) < cfg["atr_n"] + 1:
            raise History("no supertrend value yet (fewer than 6 completed weekly candles)")
        FUB, FLB, ST = supertrend(H, L, C, cfg["mult"], cfg["atr_n"])
        st, fub = ST[-1], FUB[-1]
        out["value"] = float(C[-1] - st)
        out["target"] = 0.0 if st == fub else 1.0
        out["st_zero"] = bool(st == 0.0)
        out["last_idx"] = int(ends[-1])
        out["label"] = ctx["cal"][int(ends[-1])]
    elif k == "triple":
        buys, labels = master_buy_count(ctx["master"], np.datetime64(d))
        out["value"] = float(buys)
        out["target"] = 1.0 if buys == 3 else 0.0
        out["master_labels"] = labels
    else:
        raise ValueError(k)
    return out


def full_history_values(cfg, P: np.ndarray, ctx) -> np.ndarray:
    """Independent vectorised computation over the whole series (for the look-ahead check)."""
    k = cfg["kind"]
    n = len(P)
    v = np.full(n, np.nan)
    if k in ("pct", "hyst", "step", "triple_pct"):
        W = cfg["W"]
        win = sliding_window_view(P, W + 1)
        cnt = (win[:, :W] < win[:, W:W + 1]).sum(axis=1)
        v[W:] = 100.0 * cnt / W
    elif k == "sma":
        sma = pd.Series(P).rolling(cfg["n"]).mean().to_numpy()
        v = P / sma - 1.0
        v[:cfg["n"]] = np.nan
    elif k == "tsmom":
        L = cfg["L"]
        v[L:] = P[L:] / P[:-L] - 1.0
    elif k == "ddhigh":
        mx = pd.Series(P).rolling(cfg["N"]).max().to_numpy()
        v = P / mx - 1.0
        v[:250] = np.nan
    elif k == "st":
        starts, ends, H, L, C = weekly_candles(ctx["keys"], P)
        FUB, FLB, ST = supertrend(H, L, C, cfg["mult"], cfg["atr_n"])
        val_w = C - ST
        # value at session i = latest completed week with label <= cal[i]
        labels = ctx["cal"][ends].to_numpy()
        j = np.searchsorted(labels, ctx["cal"].to_numpy(), side="right") - 1
        ok = j >= 0
        v[ok] = val_w[j[ok]]
    elif k == "triple":
        for i, d in enumerate(ctx["cal"].to_numpy()):
            try:
                v[i] = float(master_buy_count(ctx["master"], d)[0])
            except History:
                pass
    return v


# ──────────────────────────────────────────────────────────────── calendar ──
def window_sessions(cal: pd.DatetimeIndex, wname: str):
    w = WINDOWS[wname]
    t0 = cal[cal <= w["t0_on_or_before"]][-1]
    end = w["end"]
    if end not in cal:
        raise ValueError(f"{wname}: end {end.date()} not a session")
    i0, iE = int(cal.get_loc(t0)), int(cal.get_loc(end))
    return i0, iE


def weekly_decisions(cal: pd.DatetimeIndex, keys: np.ndarray, i0: int, iE: int) -> np.ndarray:
    """Global indices: T0 plus the last session of each ISO week (whole calendar) in (T0, end]."""
    is_we = np.r_[keys[1:] != keys[:-1], True]
    we = np.flatnonzero(is_we)
    d = we[(we > i0) & (we <= iE)]
    out = np.r_[i0, d].astype(np.int64)
    if out[-1] != iE:
        raise AssertionError("the window's last session is not a weekly decision session")
    return out


# ────────────────────────────────────────────────────────────────── engine ──
def simulate(eq: np.ndarray, dec_pos: np.ndarray, Cl: list, Carr: np.ndarray, ow: float, gs: float,
             detail: bool = False):
    """
    The units-based book for one target series.
    eq       equity targets at the n+1 decision sessions (eq[0] at T0, eq[-1] at the last session)
    dec_pos  window-relative session index of each decision (dec_pos[0] = 0, dec_pos[-1] = S-1)
    Cl/Carr  closes (equity, GOLDBEES, LBES) on the window's sessions, as a list of tuples and an array
    ow       one-way cost; gs = GOLDBEES share of the non-equity part
    Returns nav (S,), n_trades_excl_build_and_liquidation, and (if detail) the trade records
    and the post-trade units/cash per period.
    """
    S = Carr.shape[0]
    w = eq[:-1]                                   # a target decided on the last session is not traded
    chg = np.empty(len(w), dtype=bool)
    chg[0] = True
    np.not_equal(w[1:], w[:-1], out=chg[1:])
    tj = np.flatnonzero(chg)
    tpos = dec_pos[tj] + 1                        # the next session after the decision
    ttg = w[tj]
    K = len(tj)
    U = np.empty((K, 3))
    cash_arr = np.empty(K)
    one = 1.0 - ow
    gsh, csh = gs, 1.0 - gs
    u0 = u1 = u2 = 0.0
    cash = 1.0
    recs = [] if detail else None
    for idx, (p, e) in enumerate(zip(tpos.tolist(), ttg.tolist())):
        c0, c1, c2 = Cl[p]
        v0, v1, v2 = u0 * c0, u1 * c1, u2 * c2
        nav_now = cash + v0 + v1 + v2
        ne = 1.0 - e
        d0 = e * nav_now - v0
        d1 = ne * gsh * nav_now - v1
        d2 = ne * csh * nav_now - v2
        traded = 0.0
        # every trim first
        if d0 < 0.0:
            u0 -= -d0 / c0
            cash += -d0 * one
            traded += -d0
        if d1 < 0.0:
            u1 -= -d1 / c1
            cash += -d1 * one
            traded += -d1
        if d2 < 0.0:
            u2 -= -d2 / c2
            cash += -d2 * one
            traded += -d2
        # then top-ups in the order equity, GOLDBEES, LBES, capped by the cash account
        if d0 > 0.0:
            vv = d0 if d0 < cash else cash
            u0 += vv * one / c0
            cash -= vv
            traded += vv
        if d1 > 0.0:
            vv = d1 if d1 < cash else cash
            u1 += vv * one / c1
            cash -= vv
            traded += vv
        if d2 > 0.0:
            vv = d2 if d2 < cash else cash
            u2 += vv * one / c2
            cash -= vv
            traded += vv
        U[idx, 0], U[idx, 1], U[idx, 2] = u0, u1, u2
        cash_arr[idx] = cash
        if detail:
            recs.append({"trade_pos": p, "decision_pos": int(dec_pos[tj[idx]]), "to_equity": e,
                         "from_equity": (None if idx == 0 else float(ttg[idx - 1])),
                         "kind": "build" if idx == 0 else "switch",
                         "nav_before": nav_now, "nav_after": cash + u0 * c0 + u1 * c1 + u2 * c2,
                         "value_traded_frac": traded / nav_now})
    lengths = np.diff(np.append(tpos, S))
    nav = np.empty(S)
    nav[:tpos[0]] = 1.0
    Urep = np.repeat(U, lengths, axis=0)
    seg = Carr[tpos[0]:]
    held = np.einsum("ij,ij->i", Urep, seg)
    nav[tpos[0]:] = np.repeat(cash_arr, lengths) + held
    # the last session: everything is sold at its close, paying the sell-side cost
    held_end = float(held[-1])
    pre = float(cash_arr[-1]) + held_end
    nav[-1] = float(cash_arr[-1]) + held_end * one
    if detail:
        recs.append({"trade_pos": S - 1, "decision_pos": None, "to_equity": None,
                     "from_equity": float(ttg[-1]), "kind": "liquidate",
                     "nav_before": pre, "nav_after": float(nav[-1]),
                     "value_traded_frac": held_end / pre})
        return nav, K - 1, recs, (tpos, U, cash_arr, Urep, seg, held)
    return nav, K - 1


def closed_form_end(eq, dec_pos, Carr, gs) -> float:
    """Zero-cost closed form (T01.md step 10) for the engine's own self-check."""
    w = eq[:-1]
    chg = np.r_[True, w[1:] != w[:-1]]
    tj = np.flatnonzero(chg)
    tpos = np.r_[dec_pos[tj] + 1, Carr.shape[0] - 1]
    V = 1.0
    for j in range(len(tj)):
        e = float(w[tj[j]])
        wts = np.array([e, (1 - e) * gs, (1 - e) * (1 - gs)])
        V *= float(np.sum(wts * Carr[tpos[j + 1]] / Carr[tpos[j]]))
    return V


def path_stats(nav: np.ndarray, years: float) -> dict:
    if not np.all(np.isfinite(nav)) or np.any(nav <= 0):
        raise ValueError("non-finite or non-positive NAV")
    r = nav[1:] / nav[:-1] - 1.0
    vol = float(r.std(ddof=1)) * SQ252
    peak = np.maximum.accumulate(nav)
    mdd = float(np.min(nav / peak - 1.0))
    end = float(nav[-1])
    cagr = end ** (1.0 / years) - 1.0
    return {"cagr": cagr, "total_return": end - 1.0, "nav_end": end, "max_dd": mdd, "vol": vol,
            "sharpe": cagr / vol if vol > 0 else np.nan,
            "calmar": cagr / abs(mdd) if mdd < 0 else np.nan}


def newey_west_se(x: np.ndarray, lags: int) -> float:
    N = len(x)
    e = x - x.mean()
    s = float(np.dot(e, e)) / N
    for l in range(1, lags + 1):
        s += 2.0 * (1.0 - l / (lags + 1.0)) * float(np.dot(e[l:], e[:-l])) / N
    return math.sqrt(max(s, 0.0) / N)


# ───────────────────────────────────────────────────────────────────── main ──
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--run", required=True, help="run name (headline | cash_sleeve)")
    ap.add_argument("--sleeve", required=True, choices=sorted(SLEEVES))
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--configs", default=None, help="DEV ONLY: comma list of configs (marks the run partial)")
    ap.add_argument("--skip-null", action="store_true", help="DEV ONLY: no null draws (marks the run partial)")
    args = ap.parse_args(argv)

    t_start = time.time()
    timing = {}
    out = Path(args.out_dir)
    if not out.is_absolute():
        out = Path.cwd() / out
    out = out.resolve()
    for forbidden in (AA_DIR / "analysis" / "evidence", AA_DIR / "Historical Data"):
        if forbidden.resolve() in [out, *out.parents]:
            raise SystemExit(f"refusing to write under {forbidden}")
    if str(out).upper().startswith("G:"):
        raise SystemExit("refusing to write to the G: drive")
    out.mkdir(parents=True, exist_ok=True)

    gs = SLEEVES[args.sleeve]
    configs = build_configs()
    partial = False
    if args.configs:
        keep = [c.strip() for c in args.configs.split(",") if c.strip()]
        unknown = set(keep) - set(configs)
        if unknown:
            raise SystemExit(f"unknown configs {unknown}")
        configs = {k: v for k, v in configs.items() if k in keep}
        partial = True
    if args.skip_null:
        partial = True

    print(f"[own_momentum] run={args.run} sleeve={args.sleeve} (GOLDBEES share of sleeve {gs}) out={rel(out)}", flush=True)

    # ── steps 1-2 ──
    t = time.time()
    cal, P, gold, cash, harness, published, sleeve_info = load_inputs()
    sc = splice_check(cal, P, harness, published)
    master = load_master(cal)
    keys = iso_keys(cal)
    # week label = the week's last session in the whole calendar
    is_we = np.r_[keys[1:] != keys[:-1], True]
    week_label = {int(keys[i]): cal[i] for i in np.flatnonzero(is_we)}
    ctx = {"cal": cal, "keys": keys, "week_label": week_label, "master": master}
    sp = pd.DataFrame({"date": cal.strftime("%Y-%m-%d")})
    for parent in PARENTS:
        sp[f"P_{parent}"] = P[parent].to_numpy()
    sp["gold"] = gold.to_numpy()
    sp["cash"] = cash.to_numpy()
    sp.to_csv(out / "spliced_inputs.csv", index=False, float_format="%.17g")
    timing["load_and_splice_s"] = round(time.time() - t, 2)
    print(f"  calendar {len(cal)} sessions {cal[0].date()} .. {cal[-1].date()}; splice V4 "
          f"harness {sc['max_abs_diff_harness_side']:.3e} published {sc['max_abs_diff_published_side']:.3e} "
          f"(n={sc['n_compared']})", flush=True)

    # ── windows and decision calendars ──
    wins = {}
    for wname in WINDOWS:
        i0, iE = window_sessions(cal, wname)
        wk = weekly_decisions(cal, keys, i0, iE)
        dy = np.arange(i0, iE + 1, dtype=np.int64)
        S = iE - i0 + 1
        wins[wname] = {"i0": i0, "iE": iE, "S": S, "weekly": wk, "daily": dy,
                       "years": (S - 1) / 252.0}
        print(f"  {wname}: T0 {cal[i0].date()} end {cal[iE].date()} sessions {S} weekly decisions {len(wk)}", flush=True)

    # ── step 4-5: signals and targets, with point-in-time assertions ──
    t = time.time()
    pit = {"inputs_end_at_or_before_d": [0, 0], "truncated_equals_full_history": [0, 0],
           "master_label_at_or_before_d": [0, 0], "trade_session_after_d": [0, 0],
           "trade_session_after_d_in_ledgers": [0, 0]}
    st_zero_count = 0
    targets = {}       # (config, book, window) -> (eq array, dec global idx array)
    dec_rows = []
    for book, parent in BOOKS.items():
        Pv = P[parent].to_numpy()
        for cname, cfg in configs.items():
            full = full_history_values(cfg, Pv, ctx)
            for wname, W_ in wins.items():
                didx = W_["daily"] if cfg["freq"] == "D" else W_["weekly"]
                vals, eqs, last_dates = [], [], []
                prev_state = 1.0
                for i in didx.tolist():
                    d = cal[i]
                    try:
                        s = signal_truncated(cfg, Pv[:i + 1], i, d, ctx)
                    except History as ex:
                        raise SystemExit(f"history assertion failed: {cname} {book} {wname} at {d.date()}: {ex}")
                    # point in time: inputs end at or before d
                    last_used = cal[s["last_idx"]]
                    pit["inputs_end_at_or_before_d"][0] += 1
                    if not (last_used <= d):
                        pit["inputs_end_at_or_before_d"][1] += 1
                    if "master_labels" in s:
                        for lab in s["master_labels"]:
                            pit["master_label_at_or_before_d"][0] += 1
                            if not (pd.Timestamp(lab) <= d):
                                pit["master_label_at_or_before_d"][1] += 1
                    # look-ahead detector: the truncated value equals the full-history value
                    fv = full[i]
                    pit["truncated_equals_full_history"][0] += 1
                    if not (np.isfinite(fv) and abs(fv - s["value"]) <= 1e-12 * max(1.0, abs(fv))):
                        pit["truncated_equals_full_history"][1] += 1
                    if cfg["kind"] == "hyst":
                        cnt, Wn = s["cnt"], cfg["W"]
                        if 100 * cnt < cfg["lo"] * Wn:
                            prev_state = 0.0
                        elif 100 * cnt >= cfg["hi"] * Wn:
                            prev_state = 1.0
                        tgt = prev_state
                    else:
                        tgt = s["target"]
                    st_zero_count += int(s.get("st_zero", False))
                    if cfg["kind"] == "triple":
                        last_used = max(pd.Timestamp(x) for x in s["master_labels"])
                    vals.append(s["value"])
                    eqs.append(tgt)
                    last_dates.append(last_used)
                eq = np.asarray(eqs, dtype=float)
                targets[(cname, book, wname)] = (eq, didx)
                # decision rows (cost and sleeve independent)
                w = eq[:-1]
                chg = np.r_[True, w[1:] != w[:-1]]
                for j, i in enumerate(didx.tolist()):
                    traded = bool(j < len(didx) - 1 and chg[j])
                    tsess = cal[i + 1] if traded else None
                    if traded:
                        pit["trade_session_after_d"][0] += 1
                        if not (tsess > cal[i]):
                            pit["trade_session_after_d"][1] += 1
                    dec_rows.append((cname, book, wname, cal[i].strftime("%Y-%m-%d"), vals[j], eqs[j],
                                     last_dates[j].strftime("%Y-%m-%d"), fmt_date(tsess) if traded else "", traded))
        print(f"  signals {book} done ({time.time() - t:.1f}s)", flush=True)
    timing["signals_s"] = round(time.time() - t, 2)
    dec_df = pd.DataFrame(dec_rows, columns=["config", "book", "window", "decision_date", "value", "equity_target",
                                             "data_last_date", "trade_session", "traded"])
    dec_df.to_csv(out / "decisions_all_configs.csv", index=False, float_format="%.17g")
    dec_df[dec_df["config"] == REF_CONFIG].to_csv(out / "decisions_reference.csv", index=False, float_format="%.17g")
    print(f"  decisions: {len(dec_df)} rows; PIT so far {pit}", flush=True)

    # ── steps 6-9, 12: books, B&H, null draws ──
    t = time.time()
    real_rows, trade_rows, daily_rows = [], [], []
    bh_tie = {}
    cf_check = {"n": 0, "max_rel_diff": 0.0}
    n_null = 0
    for book, parent in BOOKS.items():
        for wname, W_ in wins.items():
            i0, iE, S, years = W_["i0"], W_["iE"], W_["S"], W_["years"]
            Carr = np.column_stack([P[parent].to_numpy()[i0:iE + 1], gold.to_numpy()[i0:iE + 1],
                                    cash.to_numpy()[i0:iE + 1]]).astype(float)
            Cl = [tuple(r) for r in Carr.tolist()]
            wk_pos = W_["weekly"] - i0
            # B&H
            nav_bh = Carr[:, 0] / Carr[0, 0]
            bst = path_stats(nav_bh, years)
            n_wk = len(wk_pos)
            real_rows.append(dict(config="bh", book=book, parent=parent, window=wname, cost_bps=0.0,
                                  sleeve=args.sleeve, kind="bh", shift_k=None, **bst,
                                  share_sleeve_weeks=0.0, avg_equity_weight=1.0, n_switches=0, n_spells=0,
                                  n_decisions=n_wk, target_level_counts=json.dumps({"1.0000": n_wk}),
                                  observed_se=None))
            if wname == "W2":
                pub = published[parent]
                pr = float(pub.loc[cal[iE]] / pub.loc[cal[i0]] - 1.0)
                bh_tie[book] = {"parent": parent, "engine_bh_total_return": bst["total_return"],
                                "published_parent_return": pr,
                                "from": fmt_date(cal[i0]), "to": fmt_date(cal[iE]),
                                "abs_diff": abs(bst["total_return"] - pr)}
            # weekly price returns for the static mix (observed_se)
            rP = Carr[wk_pos[1:], :] / Carr[wk_pos[:-1], :] - 1.0
            for cname, cfg in configs.items():
                eq, didx = targets[(cname, book, wname)]
                dec_pos = (didx - i0).astype(np.int64)
                if dec_pos[0] != 0 or dec_pos[-1] != S - 1:
                    raise AssertionError("decision calendar does not span the window")
                n1 = len(eq)
                avg_eq = float(eq.mean())
                share = float(np.mean(eq < 1.0))
                lvl = level_counts_json(eq)
                spells = n_spells_of(eq)
                for cost in COSTS:
                    ow = cost / 2.0 / 10000.0
                    nav, nsw, recs, det = simulate(eq, dec_pos, Cl, Carr, ow, gs, detail=True)
                    st_ = path_stats(nav, years)
                    # observed_se: weekly after-cost return difference vs a static mix at avg equity weight
                    r_s = nav[wk_pos[1:]] / nav[wk_pos[:-1]] - 1.0
                    wmix = np.array([avg_eq, (1 - avg_eq) * gs, (1 - avg_eq) * (1 - gs)])
                    r_m = rP @ wmix
                    ose = newey_west_se(r_s - r_m, NW_LAGS) * 52.0
                    real_rows.append(dict(config=cname, book=book, parent=parent, window=wname, cost_bps=cost,
                                          sleeve=args.sleeve, kind="strategy", shift_k=None, **st_,
                                          share_sleeve_weeks=share, avg_equity_weight=avg_eq, n_switches=nsw,
                                          n_spells=spells, n_decisions=n1, target_level_counts=lvl,
                                          observed_se=ose))
                    if cost == 0.0:
                        cf = closed_form_end(eq, dec_pos, Carr, gs)
                        cf_check["n"] += 1
                        cf_check["max_rel_diff"] = max(cf_check["max_rel_diff"], abs(cf / nav[-1] - 1.0))
                    for r in recs:
                        dpos = r["decision_pos"]
                        tp = r["trade_pos"]
                        if dpos is not None:
                            pit["trade_session_after_d_in_ledgers"][0] += 1
                            if not (tp > dpos):
                                pit["trade_session_after_d_in_ledgers"][1] += 1
                        trade_rows.append((cname, book, wname, cost, args.sleeve,
                                           fmt_date(cal[i0 + dpos]) if dpos is not None else "",
                                           fmt_date(cal[i0 + tp]), r["kind"], r["from_equity"], r["to_equity"],
                                           r["nav_before"], r["nav_after"], r["value_traded_frac"]))
                    if cname == REF_CONFIG:
                        tpos, U, cash_arr, Urep, seg, held = det
                        lengths = np.diff(np.append(tpos, S))
                        crep = np.repeat(cash_arr, lengths)
                        wv = np.zeros((S, 3))
                        cacc = np.ones(S)
                        wv[tpos[0]:] = Urep * seg
                        cacc[tpos[0]:] = crep
                        # the last session is stamped after liquidation: all in the cash account
                        wv[-1] = 0.0
                        cacc[-1] = nav[-1]
                        wts = wv / nav[:, None]
                        wcash = wts[:, 2] + cacc / nav
                        for s_ in range(S):
                            daily_rows.append((fmt_date(cal[i0 + s_]), book, wname, cost, nav[s_], nav_bh[s_],
                                               wts[s_, 0], wts[s_, 1], wcash[s_]))
                    # null draws
                    if args.skip_null:
                        continue
                    kmin = DAILY_MIN_K if cfg["freq"] == "D" else WEEKLY_MIN_K
                    for k in range(kmin, n1 - kmin + 1):
                        eqk = np.roll(eq, k)            # w'_j = w_{(j-k) mod (n+1)}
                        navk, nswk = simulate(eqk, dec_pos, Cl, Carr, ow, gs)
                        sk = path_stats(navk, years)
                        real_rows.append(dict(config=cname, book=book, parent=parent, window=wname, cost_bps=cost,
                                              sleeve=args.sleeve, kind="null", shift_k=k, **sk,
                                              share_sleeve_weeks=float(np.mean(eqk < 1.0)),
                                              avg_equity_weight=float(eqk.mean()), n_switches=nswk,
                                              n_spells=n_spells_of(eqk), n_decisions=n1,
                                              target_level_counts=level_counts_json(eqk), observed_se=None))
                        n_null += 1
            print(f"  books {book} {wname} done ({time.time() - t:.1f}s, null draws so far {n_null})", flush=True)
    timing["books_and_nulls_s"] = round(time.time() - t, 2)

    # ── write evidence ──
    t = time.time()
    rcols = ["config", "book", "parent", "window", "cost_bps", "sleeve", "kind", "shift_k", "cagr", "total_return",
             "nav_end", "max_dd", "vol", "sharpe", "calmar", "share_sleeve_weeks", "avg_equity_weight", "n_switches",
             "n_spells", "n_decisions", "target_level_counts", "observed_se"]
    rdf = pd.DataFrame(real_rows, columns=rcols)
    rdf["shift_k"] = rdf["shift_k"].astype("Int64")
    rdf.to_csv(out / "realisations.csv", index=False, float_format="%.17g")
    tdf = pd.DataFrame(trade_rows, columns=["config", "book", "window", "cost_bps", "sleeve", "decision_date",
                                            "trade_session", "kind", "from_equity", "to_equity", "nav_before",
                                            "nav_after", "value_traded_frac"])
    tdf.to_csv(out / "trades.csv", index=False, float_format="%.17g")
    ddf = pd.DataFrame(daily_rows, columns=["date", "book", "window", "cost_bps", "nav", "nav_bh", "w_equity",
                                            "w_gold", "w_cash"])
    ddf.to_csv(out / "daily_reference.csv", index=False, float_format="%.17g")
    timing["write_s"] = round(time.time() - t, 2)

    # ── audit ──
    checks = sum(v[0] for v in pit.values())
    violations = sum(v[1] for v in pit.values())
    self_ok = cf_check["max_rel_diff"] < 1e-9 and sc["pass"] and all(v["abs_diff"] < 1e-9 for v in bh_tie.values())
    audit = {
        "test": "T01", "run": args.run, "sleeve": args.sleeve, "partial_dev_run": partial,
        "purpose": ("T01 engine run: does a smallcase's own index momentum (percentile of its own 65-day range and "
                    "the sweep of 28 rules on the parent's own index path) time a move of the book's weight into "
                    "a GOLDBEES/LBES sleeve better than circularly shifted exits with the same exposure? "
                    + ("Headline sleeve: 50/50 GOLDBEES/LBES of the non-equity part." if gs == 0.5
                       else "Robustness R4: 100% LBES sleeve of the non-equity part.")),
        "spec": "AA/tests/T01/T01.md sections 1-3 (frozen)",
        "engine": rel(HERE), "engine_sha256": sha256(HERE),
        "inputs": {k: {"path": rel(p), "size_bytes": p.stat().st_size, "sha256": sha256(p)} for k, p in INPUTS.items()},
        "rules": {
            "splice": ("P_t = harness rebuild for t <= 2021-10-29; for t >= 2021-11-01 P_t = P_2021-10-29 x "
                       "published_t / published_2021-11-01 (the 2021-10-29 -> 2021-11-01 return is 0). The "
                       "session calendar is the union of the two sources' dates."),
            "sleeve_prices": ("GOLDBEES close and LBES level on the same calendar, gaps carried forward as-of "
                              "(the latest observation dated on or before the session)."),
            "decision_sessions": ("weekly: the last session of each ISO week of the whole calendar in (T0, end], "
                                  "plus T0; daily config: every session T0..end."),
            "signals": {k: v for k, v in CONFIG_PROSE.items()},
            "targets": ("equity e_d; GOLDBEES (1 - e_d)/2 and LBES (1 - e_d)/2 (gold_cash sleeve) or GOLDBEES 0 and "
                        "LBES 1 - e_d (cash sleeve)."),
            "execution": ("a trade only when the new target differs from the target last traded; filled at the "
                          "close of the session after the decision; nav_now = cash + sum units x close; every trim "
                          "first (units -= |D|/px, cash += |D|(1-ow)); then top-ups in the order equity, GOLDBEES, "
                          "LBES: v = min(D, cash), units += v(1-ow)/px, cash -= v; ow = cost_bps/2/10000. The "
                          "first trade is the build on T0's next session from cash; at the last session everything "
                          "is sold at its close paying the sell-side cost; a target decided on the last session "
                          "is not traded. Weights drift between trades."),
            "nav": "NAV = cash account + sum units x close; 1.0 at T0's close; a trade session is stamped after trading",
            "statistics": ("years = (sessions - 1)/252; CAGR = NAV_end^(1/years) - 1; vol = sample SD (ddof=1) of "
                           "daily NAV returns x sqrt(252); Sharpe = CAGR/vol (r_f = 0); max_dd on daily NAV; "
                           "Calmar = CAGR/|max_dd|; B&H = P_t/P_T0 close to close, no cost."),
            "null": ("the target series w_0 (T0) .. w_n is rotated: w'_j = w_{(j-k) mod (n+1)} (numpy.roll by k), "
                     "for every 8 <= k <= n+1-8 (weekly) and 40 <= k <= n+1-40 sessions (pct_w65_q25_daily), and "
                     "run through the identical engine at the same cost and sleeve. Every config, including the "
                     "descriptive ones, at both cost levels."),
            "observed_se": ("Newey-West (Bartlett, 4 lags) SE of the mean weekly after-cost return difference "
                            "between the strategy NAV and a static mix (equity = the strategy's avg_equity_weight "
                            "across its decision sessions, the rest split as the sleeve), rebalanced weekly at no "
                            "cost, on the window's weekly decision sessions (also for the daily config); x 52."),
            "realisation_fields": ("share_sleeve_weeks = fraction of decision sessions (all n+1, T0 and the last "
                                   "included) with equity target < 1; avg_equity_weight = their mean equity target; "
                                   "n_switches = trades excluding build and final liquidation; n_spells = maximal "
                                   "runs of decision sessions with target < 1 (not circular); target_level_counts = "
                                   "counts of each target level over the n+1 decision sessions."),
        },
        "parameters": {"configs": {k: v for k, v in configs.items()}, "reference_config": REF_CONFIG,
                       "books": BOOKS,
                       "windows": {k: {"T0": fmt_date(cal[w_["i0"]]), "end": fmt_date(cal[w_["iE"]]),
                                       "sessions": w_["S"], "weekly_decisions": int(len(w_["weekly"])),
                                       "years": w_["years"], "parent_source": WINDOWS[k]["source"]}
                                   for k, w_ in wins.items()},
                       "sleeve_gold_share": gs, "null_min_k_weekly": WEEKLY_MIN_K, "null_min_k_daily": DAILY_MIN_K,
                       "nw_lags": NW_LAGS},
        "cost_levels_bps_round_trip": list(COSTS),
        "seeds": "none: every rotation offset is run; deterministic",
        "point_in_time": {
            "rule": ("a decision at d reads P only up to and including d (each value is computed from the "
                     "truncated array P[:i+1] and must equal an independent full-history computation at d), and "
                     "the Master SIGN only up to the latest label <= d; the supertrend reads the latest completed "
                     "week with label <= d; the trade is on d's next session."),
            "checks": int(checks), "violations": int(violations),
            "by_check": {k: {"checks": int(v[0]), "violations": int(v[1])} for k, v in pit.items()},
        },
        "splice_check": sc,
        "bh_tieout_W2": bh_tie,
        "engine_self_checks": {
            "zero_cost_closed_form_vs_engine_end_nav": cf_check,
            "supertrend_line_zero_count": st_zero_count,
            "pass": bool(self_ok),
        },
        "sleeve_price_info": sleeve_info,
        "row_counts": {"realisations": int(len(rdf)), "strategy_rows": int((rdf.kind == "strategy").sum()),
                       "null_rows": int((rdf.kind == "null").sum()), "bh_rows": int((rdf.kind == "bh").sum()),
                       "decisions_all_configs": int(len(dec_df)),
                       "decisions_reference": int((dec_df.config == REF_CONFIG).sum()),
                       "trades": int(len(tdf)), "daily_reference": int(len(ddf)),
                       "spliced_inputs": int(len(sp))},
        "interpretations": INTERPRETATIONS,
        "caveats": CAVEATS,
        "run_timing": {"started": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t_start)),
                       "finished": time.strftime("%Y-%m-%d %H:%M:%S"),
                       "total_s": round(time.time() - t_start, 2), **timing,
                       "python": platform.python_version(), "pandas": pd.__version__, "numpy": np.__version__},
    }
    (out / "audit.json").write_text(json.dumps(audit, indent=2, default=str), encoding="utf-8")
    print(f"  realisations {len(rdf)} (null {int((rdf.kind == 'null').sum())}), decisions {len(dec_df)}, "
          f"trades {len(tdf)}, daily_reference {len(ddf)}", flush=True)
    print(f"  PIT checks {checks} violations {violations}; closed-form self-check max rel diff "
          f"{cf_check['max_rel_diff']:.3e} on {cf_check['n']}; B&H tie-out W2 max abs diff "
          f"{max(v['abs_diff'] for v in bh_tie.values()):.3e}; supertrend line zero {st_zero_count}", flush=True)
    print(f"[own_momentum] done in {time.time() - t_start:.1f}s", flush=True)
    if violations or not self_ok:
        print("FAILED: point-in-time violations or a self-check failed", file=sys.stderr)
        return 2
    return 0


INTERPRETATIONS = [
    "Reference config R 'pct_w65_q25_weekly' in T01.md is written as config 'pct_w65_q25' (weekly) in every file.",
    "Sleeve prices: 'gaps carried forward' is read as as-of alignment (level at a session = the latest observation dated on or before it, including observations on non-calendar dates), the repo convention in final_strategy.py / prices.py / why_n100sc100.py. For LBES this differs from reindex(calendar).ffill() on 31 sessions inside the windows (max level difference 0.84 on ~2000, 0.04%). The LBES tail after 2026-08-09 is a plain forward fill (no accrual).",
    "Calendar = union of the harness dates (non-null rows of the four parent columns) and the published parentIndices.csv dates. Five dates present in nav_curves_daily.csv but absent from parentIndices.csv (2021-11-04, 2022-10-24, 2024-05-18, 2024-11-01, 2025-10-21) are therefore not sessions.",
    "Weekly decision sessions: the last session of each ISO (year, week) of the whole calendar falling in (T0, end], plus T0. Weekend special sessions (e.g. Sunday muhurat 2016-10-30, Saturday 2020-11-14, 2024-01-20) are sessions and can be a week's last session.",
    "History requirement read literally: pct needs W previous closes, sma_n needs n previous closes (one more than its mean uses), tsmom_L needs L, ddhigh needs 250 previous closes, st needs >= 6 completed weekly candles, triple needs a Master label <= d. All are met at every decision in both windows (W1 T0 = global session index 262).",
    "Rotation direction: w'_j = w_{(j-k) mod (n+1)} (numpy.roll(w, k)). The set of k (8..n+1-8; daily 40..n+1-40) is symmetric, so the set of draws does not depend on the direction, only the shift_k label does.",
    "If a target is decided on the session before the last (possible only for the daily config), it is traded at the last session's close and then everything is liquidated at the same close (both legs pay cost), because T01 only exempts a target decided on the last session itself.",
    "n_decisions, share_sleeve_weeks, avg_equity_weight, n_spells and target_level_counts are computed over all n+1 decision sessions, T0 and the (untraded) last session included; n_spells is not circular.",
    "observed_se uses the window's weekly decision sessions as the weekly grid for every config, including pct_w65_q25_daily; the static mix's equity weight is the config's avg_equity_weight; annualised by multiplying the weekly SE by 52 (the SE of an annual arithmetic mean difference).",
    "Volatility uses the sample SD (ddof = 1) of daily NAV returns.",
    "data_last_date is the last input date actually used: the decision date for every P-based config; for st_weekly the label of the weekly candle read (= the decision date on every weekly decision, 2021-10-29 at W2's T0 2021-11-01, whose own week is not complete); for triple the latest Master week label used (it reads no P).",
    "triple / triple_and_pct25 read each Master file's latest week label <= d. On three of our week-end sessions the Master label is a later date (2021-11-03 vs label 2021-11-04, 2024-05-17 vs 2024-05-18, 2024-10-31 vs 2024-11-01), so those decisions read the previous week's SIGN (point-in-time safe, one week stale).",
    "st_weekly: candles run over the whole spliced history from 2014-07-04; the supertrend starts on candle index 5 (the 6th), with the production branch order kept verbatim including its 'pst == pflb and close < fub' sell branch and its st = 0 fallback (the fallback never fired: see engine_self_checks.supertrend_line_zero_count). SELL = line equal to the upper band (FUB).",
    "B&H realisation rows: config 'bh', cost 0, n_decisions = weekly decision count, share_sleeve_weeks 0, avg_equity_weight 1, n_switches 0, n_spells 0.",
    "trades.csv: from_equity is empty for the build (the book is all cash) and to_equity is empty for the final liquidation; value_traded_frac = (sum of trims at pre-cost value + sum of cash committed to top-ups) / nav_before (for the liquidation, the gross value sold / nav_before).",
    "daily_reference.csv: weights are fractions of NAV at the close, after that session's trading; w_cash = LBES plus the cash account, so the three sum to 1 (w_cash = 1 at T0, before the build, and at the last session, after the liquidation).",
    "The hysteresis state starts as equity at each window's T0 (the state machine is run over that window's decision sessions only).",
]

CAVEATS = [
    "W1 parents are the harness rebuild (price return, no dividends); B&H is understated by roughly the dividend yield there (T01.md section 3, known contaminants).",
    "W2 signals in its first year read simulated (pre-2021-11) closes; every lookback is at most 250 sessions.",
    "The 2021-10-29 -> 2021-11-01 splice session has a return of 0 by construction.",
    "LBES ends 2026-08-09 and is forward-filled for the last sessions of W2 (cash earns 0 there).",
    "The null does not match which weeks the sleeve is held (gold's 2024-26 rally); the cash_sleeve run (R4) removes gold's path.",
    "The four books share one market; '3 of 4' is a consistency requirement, not four independent tests.",
]


if __name__ == "__main__":
    sys.exit(main())
