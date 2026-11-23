# -*- coding: utf-8 -*-
"""T11 engine: the three-index switch (T06's rule, Part A: fixed 50/50 sleeve; T08's rule, Part B: MAUc1-timed 80/20 sleeve) on the four REAL parents
(SCMO_0003, 0007, 0010, 0029: their own baskets and D18 stock prices), against one null per timing, on 2014-09-01 -> 2019-01-02, before the published NAVs.

A FORK of analysis/t08_engine.py (copied, not imported) with common(), series_bounds(), the spell-count assertions and the shared-code AST diff taken from
analysis/t09_engine.py (also copied). Changes against T08: the window is T0 = 2014-09-01 (the first basket effective on or after 2014-07-01) .. END = 2019-01-02;
the calendar is D26's (nse_trading_days.csv), not D17's; there is no published NAV in the run (no G0 gate, no g_engine.csv); the MAUc1 signal is D24b and the MCX
range for the GOLDBEES de-spike is D24b's daily file; GOLDBEES (D09) exists from 2014-07-01, so no proxy; the spell bounds of every series come from the series
itself (lo = min(2, shortest spell of the state), hi = longest spell of the state); the seeds start with 14; the four books share the draws. D17 (published NAV
dates) is kept in the engine only as the calendar of the V4(a) regression `--calendar d17` against T08's and T06's stored daily NAVs (T0 = the book's first D17
date, end 2019-12-31) and for the V4(f) seam check. Every data file is opened through `approved_data.require()` (an APPROVED row of data/APPROVED_DATA.md), its
sha256 prefix is checked against the row, and the Smallcap 100 Master goes through `approved_data.guard_window` (standing rule 7). Pre-registration:
tests/T11/T11.md sections 1-3 (frozen; `python tests/T11/check_prereg.py`); plan: tests/T11/PLAN.md; evidence contract: tests/T11/logs/evidence_contract.md.

    python analysis/t11_engine.py [--run NAME] [--draws N] [--quick] [--books SCMO_0003 ...] [--calendar d17]      (from AA/)

Null families (2,000 draws per book; the same draw id for every cost; the four books share the draws, their decision series are identical):
    F1  in-or-out N4.10 (seed [14, 6, id])  + the real gold signal         decides A1/A2 (run with the 50/50 sleeve) and C1/C2 (timed sleeve)
    F2  in-or-out N4.9  (seed [14, 3, id])  + the real gold signal         beside F1
    F3  the real in-or-out switch + gold N4.10-g (seed [14, 11, 6, id])    decides C3, C4
    F4  the real in-or-out switch + gold N4.9-g  (seed [14, 11, 3, id])    beside F3
    F5  F1's in-or-out draw + F3's gold draw, same id                      robustness (R5)
    (F1 and F2 are also run with the sleeve fixed at 50/50: Part A's null and R6.)

Trade rule (one function, `trade`, T08's arithmetic): at a trade session t, V = value of all holdings at the fill prices (stocks OHLC4, GOLDBEES de-spiked
OHLC4, cash level). Target values: stocks e*V*w_i, GOLDBEES (1-e)*gw*V, cash (1-e)*(1-gw)*V. traded = sum |target - held| over every line; cost =
traded*cost_bps/2/1e4; every target is then scaled by (V-cost)/V. A trade exists on the next session after decision j iff e changed or (e < 1 and gw changed):
switch_in, switch_out, sleeve_rebalance; plus basket_change (a basket's first D26 session on or after its availableDate, only while IN and not on an
entry/exit session).

Writes tests/T11/evidence/<run>/ (see tests/T11/logs/evidence_contract.md). The engine prints gates and counts only, no performance figure.
"""
from __future__ import annotations

import argparse
import ast
import copy
import hashlib
import json
import math
import sys
import time
import warnings
from collections import Counter
from itertools import accumulate
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import approved_data as AD  # noqa: E402
from approved_data import NotApprovedError  # noqa: E402

AA = Path(__file__).resolve().parents[1]
HD = AA / "Historical Data"
HM = AA / "data" / "holdings_matrix"
IDX_DIR = HD / "extended_2026-11-12" / "index_daily_pre2019"
D24B_DIR = HD / "extended_2026-11-12" / "MAUc1_from_2003"
MASTER_DIR = HD / "extended_2026-10-30" / "Master"
D17_DIR = HD / "extended_2026-11-06" / "published_nav"
GOLD_D09 = AA / "analysis" / "cache" / "why_gold_ohlc_eikon_extended_2026-11-04.parquet"
CAL_FILE = IDX_DIR / "nse_trading_days.csv"
T11 = AA / "tests" / "T11"
T06E = AA / "tests" / "T06" / "evidence" / "headline"      # read-only test evidence, V4(a) only
T08E = AA / "tests" / "T08" / "evidence" / "headline"      # read-only test evidence, V4(a) only
T08_ENGINE = Path(__file__).with_name("t08_engine.py")     # source text read by the V4(c) AST comparison only
STEP1 = T11 / "logs" / "step_1_spell_counts.json"

PARENTS = ["SCMO_0003", "SCMO_0007", "SCMO_0010", "SCMO_0029"]
INDICES = ("Nifty100", "MC100", "SC100")
T0 = pd.Timestamp("2014-09-01")                # the first basket effective on or after 2014-07-01, one date for all four parents (asserted)
END = pd.Timestamp("2019-01-02")               # the first date of the published NAVs
R3_START = pd.Timestamp("2015-01-02")
END_D17 = pd.Timestamp("2019-12-31")           # V4(a) regression window end (T0 = the book's first D17 date)
FIRST_PRICE_DAY = pd.Timestamp("2014-07-01")   # D18's and D09's first bar
SC_USABLE_FROM = pd.Timestamp("2011-11-25")    # rule 7: D03 Smallcap 100 Master rows
COSTS = (0.0, 20.8, 50.0)
PRIMARY = 20.8
N_DRAWS = 2000
LO_CAP = 2                                     # lo = min(LO_CAP, shortest spell of the state)
DESPIKE_TOL = 0.005
REL_TOL_NAV = 1e-12
G0_YEARLY = 0.5                                # pp: the seam limit for a calendar year (CLAUDE.md, F-AA-D14)
GW_BUY, GW_SELL, GW_FIX = 0.8, 0.2, 0.5
SEED_IO_49, SEED_IO_410 = (14, 3), (14, 6)
SEED_G_49, SEED_G_410 = (14, 11, 3), (14, 11, 6)
R7_THRESHOLD = 0.20
# T11.md section 3 contaminants (counted from D18's src column and the holdings matrix; the engine reproduces them)
FROZEN_EXPORT = {"SCMO_0003": {"DISH": 164, "GEOM": 42, "MOL": 246, "OSCM": 122}, "SCMO_0007": {"HEXT": 62, "LAKSHVILAS": 61},
                 "SCMO_0010": {"DISH": 62, "GEOM": 42, "JMCPROJECT": 62, "LAKSHVILAS": 62, "MOL": 102, "OSCM": 60, "PEL": 42, "PIRAMALFIN": 124},
                 "SCMO_0029": {"GEOM": 122}}
FROZEN_EXPORT_TOTAL = {"SCMO_0003": 574, "SCMO_0007": 123, "SCMO_0010": 556, "SCMO_0029": 122}
FROZEN_CARRIED = {"SCMO_0003": 0, "SCMO_0007": 0, "SCMO_0010": 3, "SCMO_0029": 0}
NO_D18_SESSION = pd.Timestamp("2017-10-19")    # Diwali Muhurat evening: in D26, no D18 bar
NO_GOLD_SESSION = pd.Timestamp("2016-10-30")   # Muhurat: in D26, no GOLDBEES bar

READINGS = {
    "E1": "calendar = D26's dates from T0 = 2014-09-01 to END = 2019-01-02 (1,070 sessions, asserted); D18 dates that are not D26 sessions (the 41 sessions between 2014-07-01 and T0) lie outside the window; "
          "the session 2017-10-19 is in D26 and has no D18 bar for any stock: every stock's previous close is its valuation and fill price there (T08's E6 stand-in, applied on the calendar, counted); "
          "no trade falls on it in any realisation (counted); the thin Muhurat sessions (2016-10-30, 2018-11-07) leave some held stocks without a bar: the same stand-in, counted",
    "E2": "decision dates = T0 and the last D26 session of every later ISO week; the decision at the last session (END) is made and not traded; T0 = 2014-09-01 is a Monday and its decision reads the last Master "
          "row of each index dated on or before it",
    "E3": "label = latest Master row dated <= decision date, per index and for MAUc1 (D24b); IN iff all three index SIGN are BUY; g = BUY iff the MAUc1 SIGN is BUY (a week whose row is dated after its last D26 "
          "session reads the previous week's row); the Smallcap 100 Master rows are sliced to >= 2011-11-25 on read (rule 7, guard_window called); the engine asserts that a row exists on or before every decision",
    "E4": "initial position at T0's close, no cost, in every realisation: IN = the basket effective on T0 at its listed weights renormalised to 1, BOUGHT AT T0's OHLC4 (T0 is the basket's availableDate session, "
          "so no drift) and the book scaled so NAV = 1.000 at T0's close (T08's convention, unchanged; T11.md step 5 says 'holds at that close', read as 'NAV 1.000 at that close': weights at T0's close are the listed "
          "weights moved by the OHLC4-to-close change of the day); OUT (R3 window) = gw GOLDBEES and (1-gw) cash of NAV 1 at the close with gw = 0.8 / 0.2 from T0's g, 0.5 in fixed50 mode",
    "E5": "baskets: D19's weight-matrix index is the availableDate (equals D05's availableDate for every non-skipped basket, asserted for T0..END); skipped baskets are dropped (none in the window); weights are "
          "renormalised to 1; the basket effective on T0 is the initial one; the basket in force on 2014-07-01 (effective 2014-06-02) is never used; a basket takes effect on the first D26 session on or "
          "after its availableDate; 19 baskets T0..END per parent, 18 changes",
    "E6": "stock fill = OHLC4 of the Eikon bar (close if any of open/high/low is blank; the last close if the stock has no bar that session); the Polyplex correction (price_corrections.csv) is applied to SCMO_0007 "
          "(a constant factor in this window)",
    "E7": "costs: one rule for every trade (cost = ow x value traded at the pre-cost targets, then every target scaled by (V-cost)/V; T06/T08's `trade`, unchanged in its arithmetic)",
    "E8": "GOLDBEES fill: T03's de-spike (OHLC4 of open/high/low clipped to MCX gold's range that day + 0.5% of the close) with the range read from D24b's daily file; a session with a GOLDBEES bar and no MCX bar is "
          "filled at the raw OHLC4 (listed and counted in audit.data); the session 2016-10-30 has no GOLDBEES bar (T11.md step 1 says the engine asserts one on every session): the previous close is its "
          "valuation AND its fill (T08's behaviour; no trade falls on that session in any realisation, counted); GOLDBEES exists from 2014-07-01, so no proxy",
    "E9": "cash level: the extended LBES (D11) as-of on sessions; R2 'liq' = liquidEtfFinal (LIQUIDCASE) as-of over the whole window (T11.md R2 'expected vacuous'; the daily-return difference is reported); "
          "no cash is accrued past a file's end (asserted)",
    "E10": "constant mix: stock share f = invested decision weeks / decision weeks, rebalanced at every decision date's next session (T0's decision included) and at every basket change while f > 0; constant_mix splits "
           "the non-stock share 50/50, constant_mix_timed by the decision's gw; initial stock holding = the drifted basket scaled by f",
    "E11": "R3 window starts at the first D26 session on or after 2015-01-02 (that day) with its own spells and totals (in-or-out and gold), its own bounds, own draws (same seeds), a free initial position in the state "
           "decided then (OUT, gold SELL: gw 0.2) and the basket in force then, drifted from its availableDate (2014-12-01)",
    "E12": "R7: a stock-day (i, t), t = 1..T-1, is listed iff the ffilled D18 close return close[t]/close[t-1]-1 has absolute value >= 0.20 and the stock has weight > 0 in the basket in force on session t-1 or t; "
           "'return set to zero (previous close carried)' is implemented as a return-preserving splice (every later price of that stock, closes and OHLC4 fills, multiplied by close[t-1]/close[t], cumulatively), so "
           "that day's return is 0 and no other return changes (carrying the previous close for one day only would put the jump on the next day); the manual-export contribution is the always-in 0-cost NAV with "
           "the returns of every held export-priced stock-day (src == 'export') set to zero the same way, against the real one; R7 re-runs are stats and NAVs at 0 and 20.8 bps, full window, LBES",
    "E13": "F1 and F2 are run with the 50/50 sleeve at all three costs (T11.md step 11 says 'also run with the sleeve fixed at 50/50' without naming the costs; R1 needs A1/A2 at 0 and 50 bps); the R2 and R3 cells "
           "also run strategy_fixed50 and F1 fixed50 (A1 is in R2 and R3)",
    "E14": "bounds of every series: lo = min(2, shortest spell of the state), hi = longest spell of the state, computed from the series in the run and asserted equal to tests/T11/logs/step_1_spell_counts.json "
           "(the frozen section 2 values), with k, S and the exact tuple counts",
    "E15": "the four books have identical decision and gold series and share the draws (the states are generated once and stored under each book's key; asserted equal across books)",
    "E16": "sessions_invested = number of daily returns t = 1..T-1 earned while the parent is held (state j is held from its trade session dec_idx[j]+1; T0 for j = 0) (T06-1, unchanged)",
    "E17": "the number of sleeve trades of a draw (draws.csv sleeve_trades) is counted from the states: decisions j >= 1 with a trade session inside the window, OUT at j-1 and j, g changed; 0 in fixed50 mode",
    "E18": "V4(a): `--calendar d17` = each book's own D17 dates as the calendar, T0 = its first date (SCMO_0007: 2019-01-04), end 2019-12-31, inputs cut at 2019-12-31, the decision at 2019-12-31 not traded; the stored "
           "T08 and T06 NAVs are compared on every session of that window to a relative 1e-12 (strategy <- strategy; T06's strategy <- strategy_fixed50; hold_parent; sleeve_only; T08's sleeve_only_timed; "
           "constant mixes with f = the book's mean state in the stored decisions.csv, since f depends on the whole stored window); the stored runs read D12's MCX file and D24 where this engine reads D24b "
           "(equal on 2019) and T06 read the pinned old D17 (same rows as the extended D17 on 2019)",
    "E19": "V4(e) 'D24b equals D24 on every shared decision date': T11.md section 3 lists D24 under 'Not read', and the engine opens no D24 file; the engine compares D24b's g with T08's stored gold_signal.csv "
           "(derived from D24) on the 2019 decision dates of the d17 run only (the 609-week equality of D24b and D24 is the approval check of D24b in APPROVED_DATA.md; the verifier may repeat it)",
    "E20": "V4(f) seam: the always-in 0-cost NAV on 2019-01-02 -> 2019-12-31 (D17 dates) against the published NAV; limit +-0.5 pp over the year; T11.md says the verifier computes it from D17 and the engine's NAV; "
           "the engine also computes it (reads D17 for this gate only)",
    "E21": "V5(a) self-test seed: T06/T08's [6, 123456789] (the test is of the sampler code, which is unchanged) and, beside it, [14, 6, 123456789]; both must exceed p = 0.001",
    "E22": "parent_nav_2014-09-01_2019-01-02.csv has no '#' header line (it breaks pandas readers); the caption sits in the sidecar parent_nav_2014-09-01_2019-01-02.md",
    "E23": "Step 1 'g flips while IN' (7) counts every flip at a decision whose state is IN, which includes any flip on an entry decision; the engine's flip_counts separates them and the check adds them",
    "E24": "held stock-sessions by D18 src: counted over the 1,070 sessions with the basket in force on the session (weight > 0); sessions without any bar are listed as 'none'; the export counts per stock and the "
           "three carried bars are asserted equal to T11.md section 3's numbers",
}

USED: dict[str, dict] = {}


def ap(path) -> Path:
    """The only way the engine opens a data file: APPROVED row required, sha256 prefix checked once per file."""
    p = AD.require(path)
    rel = p.relative_to(AA).as_posix()
    if rel not in USED:
        USED[rel] = {**AD.check_sha(p), "usable_from": AD.usable_from(p)}
    return p


def sha(p: Path) -> str:
    return AD.sha256_of(p)


# ── approved raw inputs ───────────────────────────────────────────────────────
_COMMON: dict = {}


def common(end: pd.Timestamp = END) -> dict:
    """Calendar (D26), the three D03 Master files, D24b (MAUc1 Master, weekly csv, daily range), GOLDBEES (D09) with the de-spike, cash (D11); everything cut at `end`."""
    key = pd.Timestamp(end)
    if key in _COMMON:
        return _COMMON[key]
    cal_all = pd.DatetimeIndex(sorted(pd.to_datetime(pd.read_csv(ap(CAL_FILE))["date"])))
    assert cal_all.is_unique and cal_all.max() >= min(key, END), f"D26 ends {cal_all.max().date()} before {key.date()}"
    ms, rows_after = {}, {}
    for n in INDICES:
        p = ap(MASTER_DIR / f"Master_{n}.xlsx")
        if n == "SC100":
            AD.guard_window(p, SC_USABLE_FROM)
        d = pd.read_excel(p, parse_dates=["Date"])
        s = d.dropna(subset=["SIGN"]).set_index("Date")["SIGN"].sort_index()
        s = s[~s.index.duplicated(keep="last")]
        assert s.index.max() >= key, f"{n}: Master ends {s.index.max().date()} before {key.date()}"
        rows_after[n] = int((s.index > key).sum())
        s = s[s.index <= key]
        if n == "SC100":
            s = s[s.index >= SC_USABLE_FROM]                   # rule 7: nothing before the usable-from date is kept
        assert set(s.unique()) <= {"BUY", "SELL"}
        ms[n] = s
    gd = pd.read_excel(ap(D24B_DIR / "Master_MAUc1.xlsx"), parse_dates=["Date"])
    gs = gd.dropna(subset=["SIGN"]).set_index("Date")["SIGN"].sort_index()
    gs = gs[~gs.index.duplicated(keep="last")]
    assert gs.index.max() >= key and set(gs.unique()) <= {"BUY", "SELL"}
    gm_after = int((gs.index > key).sum())
    gs = gs[gs.index <= key]
    wk = pd.read_csv(ap(D24B_DIR / "mauc1_supertrend_weekly_extended.csv"), parse_dates=["review"])
    wk = wk[wk["review"] <= key].sort_values("review").reset_index(drop=True)
    m = pd.read_csv(ap(D24B_DIR / "mauc1_daily_clean_extended.csv"), index_col=0, parse_dates=True)
    m.columns = [c.strip().lower() for c in m.columns]
    g = pd.read_parquet(ap(GOLD_D09))
    g["date"] = pd.to_datetime(g["date"])
    g = g.set_index("date").sort_index()
    g = g[~g.index.duplicated(keep="last")]
    assert g.index.min() <= FIRST_PRICE_DAY and g.index.max() >= key
    rng = ((m["high"] - m["low"]) / m["close"]).reindex(g.index)
    band = rng + DESPIKE_TOL
    lo, hi = g["close"] * (1 - band), g["close"] * (1 + band)
    has = rng.notna()
    o = g["open"].where(~has, g["open"].clip(lower=lo, upper=hi))
    h = g["high"].where(~has, g["high"].clip(upper=hi))
    l_ = g["low"].where(~has, g["low"].clip(lower=lo))
    h = np.maximum(h, np.maximum(o, g["close"]))
    l_ = np.minimum(l_, np.minimum(o, g["close"]))
    gfill = (o + h + l_ + g["close"]) / 4
    norange = pd.DatetimeIndex(g.index[~has.values])
    lb = pd.read_csv(ap(HD / "LBES_Adjusted_Price_data_extended_2026-11-05.csv"))
    lb["date"] = pd.to_datetime(lb["date"], format="%d/%m/%y %H:%M")
    lb = lb.set_index("date")["price"].sort_index()
    lq = pd.read_csv(ap(HD / "liquidEtfFinal_extended_2026-11-05.csv"))
    lq["date"] = pd.to_datetime(lq["date"], format="mixed", dayfirst=True)
    lq = lq.set_index("date")["liquid_case"].sort_index()
    assert lb.index.max() >= key and lq.index.max() >= key
    _COMMON[key] = dict(cal_all=cal_all, master=ms, master_rows_after_end=rows_after, gold_master=gs, gold_master_rows_after_end=gm_after, gold_weekly=wk, mcx_daily=m,
                        gclose=g["close"][g.index <= key], gfill=gfill[gfill.index <= key], norange=norange[norange <= key], lbes=lb[lb.index <= key], liq=lq[lq.index <= key],
                        lbes_last=lb.index.max(), liq_last=lq.index.max(), gold_last=g.index.max(), mcx_last=m.index.max(), gold_first=g.index.min())
    return _COMMON[key]


def read_pub(p: str, end: pd.Timestamp) -> pd.Series:
    """D17 (extended published NAV: columns _id.scid, _id.date, index; any row order), cut at `end`. Used for the V4(a) calendar and the V4(f) seam only."""
    n = pd.read_csv(ap(D17_DIR / f"{p}.csv"))
    assert (n["_id.scid"] == p).all()
    pub = pd.Series(n["index"].values, index=pd.to_datetime(n["_id.date"], format="%Y/%m/%d")).sort_index()
    assert not pub.index.duplicated().any() and pub.index.max() >= end
    return pub[pub.index <= end]


_RAW: dict = {}


def raw_parent(p: str, end: pd.Timestamp = END) -> dict:
    """Stock prices (D18 with the price corrections, cut at `end`), baskets (D19, skipped dropped), D05 availableDates."""
    key = (p, pd.Timestamp(end))
    if key in _RAW:
        return _RAW[key]
    wm = pd.read_csv(ap(HM / f"{p}_holding_weight_matrix.csv"), index_col=0)
    wm.index = pd.to_datetime(wm.index)
    src = pd.read_csv(ap(HM / f"{p}_holding_weight_sources.csv"))
    src["rebalance_date"] = pd.to_datetime(src["rebalance_date"])
    skipped = set(src.loc[src["source"] == "csv_only_skipped", "rebalance_date"])
    wm = wm[~wm.index.isin(skipped)]
    wsum = wm.sum(axis=1)
    wm = wm.div(wsum, axis=0)
    stocks = list(wm.columns)
    ap(HM / f"{p}_columns.csv")                                # registered, not parsed
    h = pd.read_csv(ap(HD / "frozen_2026-09-25" / "Rebalance_history" / f"Rebalance_history_by_scid_{p}.csv"), usecols=["skipped", "date", "availableDate"]).drop_duplicates(["date"])
    h["eff"] = pd.to_datetime(h["availableDate"], format="%d/%m/%y %H:%M").dt.normalize()
    d05 = pd.DatetimeIndex(sorted(h.loc[h["skipped"].astype(str).str.lower() != "true", "eff"].unique()))
    o = pd.read_csv(ap(HM / f"{p}_ohlc.csv"), parse_dates=["date"]).drop_duplicates(["date", "stock"])
    assert o["date"].max() >= end, f"{p}: D18 ends {o['date'].max().date()} before {pd.Timestamp(end).date()}"
    o = o[o["date"] <= end]                                    # nothing after the window's end is used
    piv = {f: o.pivot(index="date", columns="stock", values=f).sort_index().reindex(columns=stocks) for f in ("open", "high", "low", "close")}
    srcp = o.pivot(index="date", columns="stock", values="src").sort_index().reindex(columns=stocks)
    cor = pd.read_csv(ap(HM / "price_corrections.csv"), parse_dates=["ex_date"])
    for r in cor.itertuples():
        if p in r.applies_to.split(";") and r.stock in stocks:
            for f in piv:
                piv[f].loc[piv[f].index < r.ex_date, r.stock] *= r.factor
    close_raw = piv["close"]
    o4 = ((piv["open"] + piv["high"] + piv["low"] + piv["close"]) / 4).fillna(close_raw)       # NaN only where the stock has no bar that session
    _RAW[key] = dict(W=wm, wsum=wsum, stocks=stocks, close_raw=close_raw, o4=o4, src=srcp, skipped=sorted(skipped), d05=d05, d18_dates=close_raw.index, d18_last=o["date"].max())
    return _RAW[key]


def cash_levels(cal: pd.DatetimeIndex, kind: str = "lbes", end: pd.Timestamp = END) -> tuple[np.ndarray, dict]:
    """E9. Level on every session of cal (as-of); nothing is accrued past a file's end."""
    c = common(end)
    ser = c["lbes"] if kind == "lbes" else c["liq"]
    last_file = c["lbes_last"] if kind == "lbes" else c["liq_last"]
    assert not (cal > last_file).any(), f"cash file ends {last_file.date()} before the window's last session: stop and ask Manu"
    lv = ser.reindex(ser.index.union(cal)).ffill().reindex(cal)
    assert lv.notna().all()
    return lv.values.astype(float), {"file_last": str(last_file.date()), "accrued_sessions": 0, "cash": kind}


class Book:
    """Everything a run needs for one parent and one window, as plain arrays on the calendar. calendar 'd26' = the test's calendar; 'd17' = the V4(a) regression's (D17 dates)."""

    def __init__(self, parent: str, start: pd.Timestamp | None = None, end: pd.Timestamp = END, cash: str = "lbes", calendar: str = "d26"):
        r = raw_parent(parent, end)
        c = common(end)
        if calendar == "d26":
            cal_all, self.pub_full = c["cal_all"], None
            t0 = T0 if start is None else cal_all[cal_all.searchsorted(start)]
            assert t0 in cal_all
        else:
            assert calendar == "d17"
            self.pub_full = read_pub(parent, end)
            cal_all = self.pub_full.index
            t0 = cal_all[0] if start is None else cal_all[cal_all.searchsorted(start)]
        cal = cal_all[(cal_all >= t0) & (cal_all <= end)]
        assert cal[0] == t0 and cal[-1] == end, (cal[0], cal[-1], end)
        self.parent, self.cal, self.T, self.t0, self.calendar, self.end = parent, cal, len(cal), t0, calendar, pd.Timestamp(end)
        self.stocks, self.N = r["stocks"], len(r["stocks"])
        union = cal.union(r["close_raw"].index)
        Cf = r["close_raw"].reindex(union).ffill().reindex(cal)       # the last close stands in on a session without a bar (E1, E6)
        P = r["o4"].reindex(cal)
        self.nobar = P.isna().values                                  # stock has no bar that session
        self.nobar_trades = 0                                         # held or traded stock lines priced by the stand-in (counted in trade())
        self.gold_norange_trades = 0                                  # trades whose GOLDBEES leg was filled at the raw OHLC4 (no MCX range that session)
        self.gold_nobar_trades = 0                                    # trades whose GOLDBEES leg used the previous close (no GOLDBEES bar that session)
        P = P.fillna(Cf)
        self.C = np.nan_to_num(Cf.values.astype(float), nan=0.0)
        self.P = np.nan_to_num(P.values.astype(float), nan=0.0)
        self.src = r["src"].reindex(index=cal, columns=self.stocks).values        # D18 src of the bar on the session (NaN: no bar)
        self.pub = self.pub_full.reindex(cal).values.astype(float) if self.pub_full is not None else None
        gunion = cal.union(c["gclose"].index)
        gc = c["gclose"].reindex(gunion).ffill().reindex(cal)
        assert gc.notna().all()
        gf = c["gfill"].reindex(cal).fillna(gc)                       # no GOLDBEES bar that session: the previous close is the fill too (E8)
        self.g, self.gf = gc.values.astype(float), gf.values.astype(float)
        own = cal.isin(c["gclose"].index)
        self.gold_no_own_bar = [str(d.date()) for d in cal[~own]]
        self.gold_nobar = ~np.asarray(own)
        self.gold_norange = np.asarray(cal.isin(c["norange"]))        # GOLDBEES bar but no MCX range: raw OHLC4 fill
        self.L, self.cash_info = cash_levels(cal, cash, end)
        # baskets
        W = r["W"]
        self.W = W.values.astype(float)
        self.eff = W.index
        bidx = np.searchsorted(cal.values, self.eff.values)          # first session on or after availableDate
        self.bidx = bidx
        self.b0 = int(np.flatnonzero(bidx <= 0)[-1])                 # basket in force at T0 (E4/E5)
        self.basket_events = {int(i) for i in bidx if 0 < i < self.T}
        self.basket_at = np.array([int(np.flatnonzero(bidx <= t)[-1]) if (bidx <= t).any() else 0 for t in range(self.T)])
        # initial IN holdings: basket b0 bought at the OHLC4 of its first D18 session on or after its availableDate, scaled to NAV 1 at T0's close
        ax = r["d18_dates"]
        s0 = ax[ax.searchsorted(self.eff[self.b0])]
        w = self.W[self.b0]
        nzs = np.flatnonzero(w > 0)
        p = r["o4"].loc[s0].values[nzs]
        p = np.where(np.isnan(p), r["close_raw"].ffill().loc[s0].values[nzs], p)
        u = np.zeros(self.N)
        u[nzs] = w[nzs] / p
        v0 = float((u * self.C[0]).sum())
        self.u0 = u / v0
        self.initial_basket_switch_session = str(s0.date())

    # decisions (E2, E3)
    def decisions(self) -> pd.DataFrame:
        cal = self.cal
        iso = cal.isocalendar()
        last = pd.Series(np.arange(self.T), index=cal).groupby([iso.year.values, iso.week.values]).max().values
        idx = np.array([0] + [int(i) for i in sorted(last) if i > 0])
        ms = common(self.end)["master"]
        gm = common(self.end)["gold_master"]
        rows = []
        for j, i in enumerate(idx):
            d = cal[i]
            lab, state = {}, 1
            for n, s in ms.items():
                k = s.index.searchsorted(d, side="right") - 1
                assert k >= 0, f"{n}: no Master row on or before {d.date()}"
                lab[n] = (s.index[k], s.iloc[k])
                state &= int(s.iloc[k] == "BUY")
            ld = max(v[0] for v in lab.values())
            kg = gm.index.searchsorted(d, side="right") - 1          # E3: latest MAUc1 row dated <= the decision date
            assert kg >= 0
            lab_g, sign_g = gm.index[kg], gm.iloc[kg]
            rows.append({"book": self.parent, "j": j, "decision_date": d.date(), "decision_idx": int(i),
                         "trade_date": (cal[i + 1].date() if i + 1 < self.T else None),
                         **{f"sign_{n}": v[1] for n, v in lab.items()}, **{f"label_{n}": v[0].date() for n, v in lab.items()},
                         "latest_label": ld.date(), "label_age_days": (d - min(v[0] for v in lab.values())).days,
                         "all_three_buy": bool(state), "state": int(state),
                         "sign_MAUc1": sign_g, "label_MAUc1": lab_g.date(), "g": int(sign_g == "BUY"), "gw": GW_BUY if sign_g == "BUY" else GW_SELL})
        return pd.DataFrame(rows)


# ── simulation ────────────────────────────────────────────────────────────────
def trade(bk: Book, t: int, e_new: float, gw_new: float, u, gu, cu, ow: float):
    ps, gp, lv = bk.P[t], bk.gf[t], bk.L[t]
    held_s = u * ps
    V = held_s.sum() + gu * gp + cu * lv
    w = bk.W[bk.basket_at[t]]
    Te = e_new * V * w
    Tg = (1 - e_new) * gw_new * V                      # gw_new = 0.5 reproduces T06's (1 - e)/2 * V exactly
    Tc = (1 - e_new) * (1 - gw_new) * V
    nb = int((bk.nobar[t] & ((Te > 0) | (held_s > 0))).sum())
    bk.nobar_trades += nb
    gold_traded = abs(Tg - gu * gp) > 0
    if gold_traded and bk.gold_norange[t]:
        bk.gold_norange_trades += 1
    if gold_traded and bk.gold_nobar[t]:
        bk.gold_nobar_trades += 1
    traded = np.abs(Te - held_s).sum() + abs(Tg - gu * gp) + abs(Tc - cu * lv)
    cost = ow * traded
    k = (V - cost) / V
    new_u = np.zeros_like(u)
    pos = (Te > 0) & (ps > 0)
    assert not ((Te > 0) & (ps <= 0)).any(), f"no price for a stock to buy at session {bk.cal[t].date()}"
    new_u[pos] = k * Te[pos] / ps[pos]
    ngu, ncu = k * Tg / gp, k * Tc / lv
    va = new_u * ps
    stock_after = float(va.sum())
    return new_u, ngu, ncu, dict(V=V, traded=traded, cost=cost, stock_before=float(held_s.sum()), gold_before=float(gu * gp), cash_before=float(cu * lv),
                                 stock_after=stock_after, gold_after=float(ngu * gp), cash_after=float(ncu * lv), V_after=stock_after + float(ngu * gp) + float(ncu * lv),
                                 weight_gap=float(np.abs(va / stock_after - w).max()) if stock_after > 0 else 0.0, held_before=held_s, val_after=va,
                                 nobar_stocks=nb, gold_norange=bool(gold_traded and bk.gold_norange[t]), gold_nobar=bool(gold_traded and bk.gold_nobar[t]))


def simulate(bk: Book, dec_idx: np.ndarray, e: np.ndarray, cost_bps: float, every: bool = False, record: bool = False, gw: np.ndarray | None = None):
    """e[j] = stock share decided at decision j; gw[j] = gold weight of the non-stock share decided at j (None = 0.5 always: T06's sleeve).
    A trade is due on the session after decision j iff e changed or (e < 1 and gw changed) [or `every`]. Returns daily NAV (length T) and, if record, the trade and position logs."""
    T, ow = bk.T, cost_bps / 2e4
    gwa = np.full(len(e), GW_FIX) if gw is None else np.asarray(gw, dtype=float)
    e_cur, gw_cur = float(e[0]), float(gwa[0])
    u = bk.u0 * e_cur
    gu = (1 - e_cur) * gw_cur / bk.g[0]
    cu = (1 - e_cur) * (1 - gw_cur) / bk.L[0]
    tgt = {}
    for j in range(0 if every else 1, len(dec_idx)):   # "every" (constant mix): T0 is a decision date too, so its next session rebalances
        tr = int(dec_idx[j]) + 1
        if tr < T and (every or e[j] != e[j - 1] or (e[j] < 1 and gwa[j] != gwa[j - 1])):
            tgt[tr] = (float(e[j]), float(gwa[j]), j)
    ev = sorted(set(tgt) | bk.basket_events)
    nav = np.empty(T)
    nz = np.flatnonzero(u)
    a = 0
    trades, pos_log = [], []
    for t in ev:
        if t > a:
            nav[a:t] = bk.C[a:t][:, nz] @ u[nz] + bk.g[a:t] * gu + bk.L[a:t] * cu if len(nz) else bk.g[a:t] * gu + bk.L[a:t] * cu
        a = t
        if t in tgt or (t in bk.basket_events and e_cur > 0):
            e_new, gw_new, jd = tgt[t] if t in tgt else (e_cur, gw_cur, None)
            kind = ("switch_in" if e_new > e_cur else "switch_out" if e_new < e_cur else
                    (("mix_rebalance" if every else "sleeve_rebalance") if t in tgt else "basket_change"))
            u, gu, cu, info = trade(bk, t, e_new, gw_new, u, gu, cu, ow)
            e_cur, gw_cur = e_new, gw_new
            nz = np.flatnonzero(u)
            if record:
                nav_close = float(bk.C[t][nz] @ u[nz] + gu * bk.g[t] + cu * bk.L[t]) if len(nz) else float(gu * bk.g[t] + cu * bk.L[t])
                trades.append({"date": bk.cal[t].date(), "idx": t, "kind": kind, "e_after": e_new, "gw_after": gw_new, "basket_eff": bk.eff[bk.basket_at[t]].date(),
                               **info, "nav_close_after": nav_close, "dec_j": jd})
                for i in nz:
                    pos_log.append({"date": bk.cal[t].date(), "instrument": bk.stocks[i], "units": u[i]})
                if gu > 0:
                    pos_log.append({"date": bk.cal[t].date(), "instrument": "GOLDBEES", "units": gu})
                if cu > 0:
                    pos_log.append({"date": bk.cal[t].date(), "instrument": "LBES", "units": cu})
    nav[a:T] = (bk.C[a:T][:, nz] @ u[nz] if len(nz) else 0.0) + bk.g[a:T] * gu + bk.L[a:T] * cu
    return (nav, trades, pos_log) if record else nav


def stats(nav: np.ndarray) -> dict:
    T = len(nav)
    yrs = (T - 1) / 252
    r = nav[1:] / nav[:-1] - 1
    peak = np.maximum.accumulate(nav)
    dd = nav / peak - 1
    under = dd < 0
    longest, run = 0, 0
    for x in under:
        run = run + 1 if x else 0
        longest = max(longest, run)
    cagr = nav[-1] ** (1 / yrs) - 1
    mdd = float(dd.min())
    return {"end_nav": float(nav[-1]), "cagr": float(cagr), "max_dd": mdd, "vol": float(r.std(ddof=1) * math.sqrt(252)),
            "ulcer": float(math.sqrt(np.mean((100 * dd) ** 2))), "days_below_10pct": int((dd <= -0.10).sum()),
            "longest_underwater": int(longest), "calmar": float(cagr / abs(mdd)) if mdd < 0 else float("nan"), "sessions": T}


def sessions_invested(bk: Book, dec_idx: np.ndarray, st: np.ndarray) -> int:
    """T06-1: daily returns (t = 1..T-1) earned while the parent is held. State j is held from its trade session dec_idx[j]+1 (T0 for j = 0)."""
    T = bk.T
    a = np.concatenate([[0], np.minimum(np.asarray(dec_idx[1:]) + 1, T)]).astype(int)
    lens = np.append(a[1:], T) - a
    jl = int(np.flatnonzero(a < T)[-1])                     # state held at the last session's close (not a return day's start)
    st = np.asarray(st).astype(int)
    return int((st * lens).sum() - st[jl])


# ── spells and nulls ──────────────────────────────────────────────────────────
def spells(s: np.ndarray):
    runs, cur, c = [], int(s[0]), 0
    for v in s:
        if int(v) == cur:
            c += 1
        else:
            runs.append((cur, c))
            cur, c = int(v), 1
    runs.append((cur, c))
    return runs


def spell_sig(s: np.ndarray) -> str:
    r = spells(s)
    ins = sorted(c for v, c in r if v == 1)
    outs = sorted(c for v, c in r if v == 0)
    return hashlib.sha1(json.dumps([int(s[0]), ins, outs]).encode()).hexdigest()[:12]


def spell_shuffle(s: np.ndarray, draw_id: int, seed: tuple = SEED_IO_49) -> np.ndarray:
    """N4.9: shuffle the in-spells among themselves and the out-spells among themselves, interleave from the series' first state.
    Seed [14, 3, id] for the in-or-out series, [14, 11, 3, id] for the gold series (state 1 = BUY)."""
    rng = np.random.default_rng([*seed, draw_id])
    r = spells(s)
    ins = [c for v, c in r if v == 1]
    outs = [c for v, c in r if v == 0]
    ins = [ins[i] for i in rng.permutation(len(ins))]
    outs = [outs[i] for i in rng.permutation(len(outs))]
    out, state = [], int(s[0])
    pools = {1: ins, 0: outs}
    ptr = {1: 0, 0: 0}
    while ptr[1] < len(ins) or ptr[0] < len(outs):
        out += [state] * pools[state][ptr[state]]
        ptr[state] += 1
        state = 1 - state
    return np.array(out, dtype=int)


def series_bounds(s: np.ndarray) -> dict:
    """E14: per state (1 = in/BUY, 0 = out/SELL) lo = min(2, shortest spell of the state), hi = the longest spell of the state, from the series itself."""
    r = spells(np.asarray(s).astype(int))
    out = {}
    for st in (1, 0):
        ls = [c for v, c in r if v == st]
        out[st] = (min(LO_CAP, min(ls)), max(ls))
    return out


_TABLES: dict = {}


def count_table(k: int, S: int, lo: int, hi: int) -> list[list[int]]:
    """c[m][t] = number of ways to write t as m integers in [lo, hi] (Python ints): c(0,0) = 1, c(0,t>0) = 0, c(m,t) = sum_{x=lo..hi} c(m-1, t-x).
    Cached per argument tuple: do not mutate the result. The caller checks `c[k][S] > 0`."""
    key = (k, S, lo, hi)
    if key in _TABLES:
        return _TABLES[key]
    c = [[0] * (S + 1) for _ in range(k + 1)]
    c[0][0] = 1
    for m in range(1, k + 1):
        prev, cur = c[m - 1], c[m]
        for t in range(S + 1):
            cur[t] = sum(prev[t - x] for x in range(lo, min(hi, t) + 1))
    _TABLES[key] = c
    return c


def draw_lengths(rng, k: int, S: int, lo: int, hi: int, table: list[list[int]]) -> list[int]:
    """Exact sequential sampler (T06 Rule 7). With m parts and t weeks left, P(length = x) is proportional to c(m-1, t-x), x in [lo, hi].
    One uniform per part from rng.random() and a cumulative-sum search (never Generator.choice)."""
    assert table[k][S] > 0, f"no tuple of {k} integers in [{lo}, {hi}] sums to {S}"
    out, t = [], S
    for m in range(k, 0, -1):
        w = [table[m - 1][t - x] if t - x >= 0 else 0 for x in range(lo, hi + 1)]
        tot = table[m][t]
        assert sum(w) == tot and tot > 0
        cum = np.array([c / tot for c in accumulate(w)])      # exact integers, correctly rounded quotient; cum[-1] == 1.0
        u = rng.random()
        i = min(int(np.searchsorted(cum, u, side="right")), len(w) - 1)
        assert w[i] > 0
        x = lo + i
        out.append(x)
        t -= x
    assert t == 0 and len(out) == k
    return out


def free_length_draw(s: np.ndarray, draw_id: int, bounds: dict, seed: tuple = SEED_IO_410) -> np.ndarray:
    """N4.10: k, S and the first state come from `s`; lengths in [lo, hi] of the state uniform over ordered tuples; alternate from s[0].
    bounds = {1: (lo, hi), 0: (lo, hi)}. In-spell (BUY) lengths are drawn first, then out-spell (SELL) lengths, one generator."""
    s = np.asarray(s).astype(int)
    r = spells(s)
    k = {1: sum(1 for v, _ in r if v == 1), 0: sum(1 for v, _ in r if v == 0)}
    S = {1: sum(c for v, c in r if v == 1), 0: sum(c for v, c in r if v == 0)}
    rng = np.random.default_rng([*seed, draw_id])
    lens = {}
    for st in (1, 0):
        if k[st] == 0:
            assert S[st] == 0
            lens[st] = []
            continue
        lo, hi = bounds[st]
        tab = count_table(k[st], S[st], lo, hi)
        lens[st] = draw_lengths(rng, k[st], S[st], lo, hi, tab)
    out, state, ptr = [], int(s[0]), {1: 0, 0: 0}
    while ptr[1] < k[1] or ptr[0] < k[0]:
        out += [state] * lens[state][ptr[state]]
        ptr[state] += 1
        state = 1 - state
    out = np.array(out, dtype=int)
    assert len(out) == len(s) and int(out[0]) == int(s[0])
    assert sum(lens[1]) == S[1] and sum(lens[0]) == S[0] and int(out.sum()) == int(s.sum())
    assert all(bounds[1][0] <= x <= bounds[1][1] for x in lens[1]) and all(bounds[0][0] <= x <= bounds[0][1] for x in lens[0])
    return out


def ie_count(k: int, S: int, lo: int, hi: int) -> int:
    """Inclusion-exclusion count of k integers in [lo, hi] summing to S: sum_j (-1)^j C(k,j) C(S - k*lo - j*(hi-lo+1) + k - 1, k - 1)."""
    tot = 0
    for j in range(k + 1):
        n = S - k * lo - j * (hi - lo + 1)
        if n < 0:
            break
        tot += (-1) ** j * math.comb(k, j) * math.comb(n + k - 1, k - 1)
    return tot


def lens_of(st: np.ndarray) -> tuple[list[int], list[int]]:
    r = spells(st)
    return [c for v, c in r if v == 1], [c for v, c in r if v == 0]


# ── orchestration ─────────────────────────────────────────────────────────────
FAMILIES = {"F1": ("N4.10", "real"), "F2": ("N4.9", "real"), "F3": ("real", "N4.10-g"), "F4": ("real", "N4.9-g"), "F5": ("N4.10", "N4.10-g")}
SLEEVE_KINDS = ("switch_out", "sleeve_rebalance")


def make_states_io(s: np.ndarray, n: int, bounds: dict) -> dict:
    """The weekly in-or-out states of every draw of F1/F2/F5: {type: uint8 (n, weeks)}."""
    return {"N4.9": np.array([spell_shuffle(s, d, SEED_IO_49) for d in range(n)], dtype=np.uint8),
            "N4.10": np.array([free_length_draw(s, d, bounds, SEED_IO_410) for d in range(n)], dtype=np.uint8)}


def make_states_gold(g: np.ndarray, n: int, bounds: dict) -> dict:
    """The weekly gold states of every draw of F4/F3/F5 (the same samplers on the gold series, state 1 = BUY, gold seeds)."""
    return {"N4.9-g": np.array([spell_shuffle(g, d, SEED_G_49) for d in range(n)], dtype=np.uint8),
            "N4.10-g": np.array([free_length_draw(g, d, bounds, SEED_G_410) for d in range(n)], dtype=np.uint8)}


def v3_check(s: np.ndarray, states: dict, bounds: dict) -> dict:
    """V3 on every draw of both nulls for one series (T11.md section 2, gate V3). For a gold series 'in' = BUY and 'out' = SELL."""
    s = np.asarray(s).astype(int)
    r0 = lens_of(s)
    ref = {"first": int(s[0]), "weeks": len(s), "k_in": len(r0[0]), "k_out": len(r0[1]), "S_in": sum(r0[0]), "S_out": sum(r0[1]),
           "invested": int(s.sum()), "sorted_in": sorted(r0[0]), "sorted_out": sorted(r0[1])}
    (lo_i, hi_i), (lo_o, hi_o) = bounds[1], bounds[0]
    res = {"rule_in_support": bool(all(lo_i <= x <= hi_i for x in r0[0]) and all(lo_o <= x <= hi_o for x in r0[1])), "bounds": {"in": [lo_i, hi_i], "out": [lo_o, hi_o]}, "types": {}}
    for kind, arr in states.items():
        bad = {"weeks": 0, "first_state": 0, "k_in": 0, "k_out": 0, "S_in": 0, "S_out": 0, "invested_weeks": 0, "sorted_lengths": 0, "bounds": 0, "not_binary": 0}
        for st in arr:
            st = st.astype(int)
            li, lo_ = lens_of(st)
            bad["weeks"] += len(st) != ref["weeks"]
            bad["first_state"] += int(st[0]) != ref["first"]
            bad["k_in"] += len(li) != ref["k_in"]
            bad["k_out"] += len(lo_) != ref["k_out"]
            bad["S_in"] += sum(li) != ref["S_in"]
            bad["S_out"] += sum(lo_) != ref["S_out"]
            bad["invested_weeks"] += int(st.sum()) != ref["invested"]
            bad["not_binary"] += int(((st != 0) & (st != 1)).sum()) > 0
            if kind.startswith("N4.9"):
                bad["sorted_lengths"] += (sorted(li) != ref["sorted_in"]) or (sorted(lo_) != ref["sorted_out"])
            else:
                bad["bounds"] += (not all(lo_i <= x <= hi_i for x in li)) or (not all(lo_o <= x <= hi_o for x in lo_))
        bad = {k: int(v) for k, v in bad.items()}
        res["types"][kind] = {"draws": int(len(arr)), "failures": bad, "pass": bool(sum(bad.values()) == 0)}
    res["pass"] = bool(res["rule_in_support"] and all(v["pass"] for v in res["types"].values()))
    return res


def n_sleeve_trades(idx: np.ndarray, T: int, s: np.ndarray, g: np.ndarray) -> int:
    """T08-4: decisions j >= 1 with a trade session inside the window, OUT at j-1 and j, and g changed."""
    s = np.asarray(s).astype(int)
    g = np.asarray(g).astype(int)
    ok = (np.asarray(idx[1:]) + 1 < T) & (s[1:] == 0) & (s[:-1] == 0) & (g[1:] != g[:-1])
    return int(ok.sum())


def gold_spells_with_out(s: np.ndarray, g: np.ndarray) -> int:
    s, g = np.asarray(s).astype(int), np.asarray(g).astype(int)
    cnt, i, n = 0, 0, len(g)
    while i < n:
        j = i
        while j < n and g[j] == g[i]:
            j += 1
        cnt += int((s[i:j] == 0).any())
        i = j
    return cnt


def flip_counts(s: np.ndarray, g: np.ndarray) -> dict:
    s, g = np.asarray(s).astype(int), np.asarray(g).astype(int)
    fl = np.flatnonzero(g[1:] != g[:-1]) + 1
    return {"flips": int(len(fl)), "while_out_both_sides": int(sum(1 for j in fl if s[j] == 0 and s[j - 1] == 0)),
            "on_exit_decision": int(sum(1 for j in fl if s[j - 1] == 1 and s[j] == 0)),
            "on_entry_decision": int(sum(1 for j in fl if s[j - 1] == 0 and s[j] == 1)),
            "while_in": int(sum(1 for j in fl if s[j] == 1 and s[j - 1] == 1)),
            "weeks_buy_while_out": int(((g == 1) & (s == 0)).sum()), "weeks_sell_while_out": int(((g == 0) & (s == 0)).sum())}


# ── R7: flagged price days and the manual-export bars ─────────────────────────
def held_either(bk: Book) -> np.ndarray:
    """(T, N) bool: the stock has weight > 0 in the basket in force on session t-1 or on session t (t = 0: session 0 only)."""
    held = bk.W[bk.basket_at] > 0
    prev = np.vstack([held[:1], held[:-1]])
    return held | prev


def flagged_days(bk: Book, thr: float = R7_THRESHOLD) -> tuple[np.ndarray, np.ndarray]:
    """E12: (mask, ret). mask[t, i] iff t >= 1, both ffilled closes are positive, |close[t]/close[t-1] - 1| >= thr and the stock is held on t-1 or t."""
    C = bk.C
    prev = np.vstack([C[:1], C[:-1]])
    ok = (C > 0) & (prev > 0)
    ret = np.zeros_like(C)
    ret[ok] = C[ok] / prev[ok] - 1
    mask = ok & (np.abs(ret) >= thr) & held_either(bk)
    mask[0] = False
    return mask, ret


def zero_return_book(bk: Book, mask: np.ndarray) -> Book:
    """E12: a copy of the book whose prices carry the return-preserving splice: for every flagged (t, i), all prices of stock i from t on (closes and OHLC4 fills)
    are multiplied by close[t-1]/close[t], so the return of day t is exactly 0 and no other return changes."""
    C = bk.C
    prev = np.vstack([C[:1], C[:-1]])
    ok = mask & (C > 0) & (prev > 0)
    ratio = np.ones_like(C)
    ratio[ok] = prev[ok] / C[ok]
    s = np.cumprod(ratio, axis=0)
    new = copy.copy(bk)
    new.C, new.P = C * s, bk.P * s
    return new


def r7_runs(bk: Book, idx: np.ndarray, sf: np.ndarray, gw_real: np.ndarray, stat_row, out: dict):
    """R7 (full window, LBES): flagged stock-days and the manual-export stock-days with their return set to zero; rule (timed and 50/50) and hold-the-parent at 0 and 20.8 bps."""
    p = bk.parent
    mask, ret = flagged_days(bk)
    for t, i in zip(*np.nonzero(mask)):
        w = bk.W[bk.basket_at[[max(t - 1, 0), t]], i]
        out["r7_flagged"].append({"book": p, "date": str(bk.cal[t].date()), "stock": bk.stocks[i], "prev_close": float(bk.C[t - 1, i]), "close": float(bk.C[t, i]), "ret": float(ret[t, i]),
                                  "w_prev": float(w[0]), "w_cur": float(w[1]), "src": bk.src[t, i] if isinstance(bk.src[t, i], str) else "none"})
    exp_mask = (bk.src == "export") & held_either(bk)
    exp_mask[0] = False
    variants = [("r7_flagged", zero_return_book(bk, mask)), ("r7_noexport", zero_return_book(bk, exp_mask))]
    for tag, bkx in variants:
        for cost in (0.0, PRIMARY):
            for name, e_arr, gwv in (("strategy", sf, gw_real), ("strategy_fixed50", sf, None), ("hold_parent", np.ones(len(sf)), None)):
                nv = simulate(bkx, idx, e_arr, cost, gw=gwv)
                out["rows"].append(stat_row(f"{name}_{tag}", cost, nv, [], float(e_arr.sum())))
                out["nav"][(p, cost, f"{name}_{tag}")] = nv
    nav_real = simulate(bk, idx, np.ones(len(sf)), 0.0)
    nav_x = simulate(variants[1][1], idx, np.ones(len(sf)), 0.0)
    held = bk.W[bk.basket_at] > 0
    isexp = (bk.src == "export") & held
    per = {bk.stocks[i]: int(isexp[:, i].sum()) for i in range(bk.N) if isexp[:, i].any()}
    for st, n in per.items():
        out["r7_export"].append({"book": p, "stock": st, "held_sessions_export": n, "end_nav_hold_parent": float(nav_real[-1]), "end_nav_hold_parent_noexport": float(nav_x[-1])})
    out["r7_summary"][p] = {"flagged_stock_days": int(mask.sum()), "flagged_stocks": sorted({bk.stocks[i] for i in np.nonzero(mask)[1]}),
                            "held_export_stock_sessions": int(isexp.sum()), "export_stock_days_zeroed": int(exp_mask.sum()), "threshold": R7_THRESHOLD}


def run_book(bk: Book, dec: pd.DataFrame, sio: dict, sgo: dict, window: str, cash: str, plan: list, headline: bool, out: dict, curves: dict):
    """plan = [(family, cost, sleeve_mode)]. Strategy (and strategy_fixed50) at every cost of `costs` (all three on the headline cell, else the primary only);
    comparators and the R7 variants on the headline cell; every draw of every planned family."""
    idx = dec["decision_idx"].values
    s = dec["state"].values.astype(int)
    g = dec["g"].values.astype(int)
    gw_real = np.where(g == 1, GW_BUY, GW_SELL)
    sf = s.astype(float)
    sig_s, sig_g = spell_sig(s), spell_sig(g)
    dts = dec["decision_date"].astype(str).values
    f = float(s.mean())
    costs = COSTS if headline else (PRIMARY,)

    def m_io(st):
        li, lo_ = lens_of(st.astype(int))
        return (len(li), len(lo_), spell_sig(st.astype(int)), sessions_invested(bk, idx, st), "|".join(map(str, li)), "|".join(map(str, lo_)))

    def m_g(st):
        bl, sl = lens_of(st.astype(int))
        return (int(st.sum()), len(bl), len(sl), spell_sig(st.astype(int)), "|".join(map(str, bl)), "|".join(map(str, sl)))

    need_io = {FAMILIES[fm][0] for fm, _, _ in plan} - {"real"}
    need_g = {FAMILIES[fm][1] for fm, _, _ in plan} - {"real"}
    mio = {"real": m_io(s)}
    mg = {"real": m_g(g)}
    fio, fgw = {}, {}
    for k in need_io:
        mio[k] = [m_io(x) for x in sio[k]]
        fio[k] = sio[k].astype(float)
    for k in need_g:
        mg[k] = [m_g(x) for x in sgo[k]]
        fgw[k] = np.where(sgo[k] == 1, GW_BUY, GW_SELL)

    def stat_row(name, cost, nv, tr, inv):
        assert np.isfinite(nv).all() and (nv > 0).all(), f"{name}: a NAV is not finite and positive"
        return {"book": bk.parent, "window": window, "cash": cash, "cost_bps": cost, "kind": name, **stats(nv), "invested_weeks": inv, "trades": len(tr),
                "cost_paid": sum(t["cost"] for t in tr), "sleeve_trades": sum(1 for t in tr if t["kind"] == "sleeve_rebalance"),
                "basket_trades": sum(1 for t in tr if t["kind"] == "basket_change")}

    def keep(name, cost, tr, pos=None, nav=None):
        out["trades"] += [{"book": bk.parent, "cost_bps": cost, "run": name, **t} for t in tr]
        if pos is not None:
            out["positions"] += [{"book": bk.parent, "cost_bps": cost, "run": name, **p} for p in pos]
        if nav is not None:
            out["nav"][(bk.parent, cost, name)] = nav

    for cost in costs:
        nav, tr, pos = simulate(bk, idx, sf, cost, record=True, gw=gw_real)
        out["rows"].append(stat_row("strategy", cost, nav, tr, int(s.sum())))
        for t in tr:
            if t["dec_j"] is not None:
                assert t["idx"] > idx[t["dec_j"]], "V2: a trade is not after its decision"
                out["v2_trades"] += 1
            elif t["kind"] == "basket_change":
                assert bk.cal[t["idx"]] == bk.cal[bk.bidx[bk.basket_at[t["idx"]]]] and bk.cal[t["idx"]] >= bk.eff[bk.basket_at[t["idx"]]], "V2: a basket change is not on its availableDate's session"
                out["v2_basket_trades"] += 1
        if headline:
            keep("strategy", cost, tr, pos, nav)
            for t in tr:
                if t["kind"] in SLEEVE_KINDS:
                    j = t["dec_j"]
                    out["sleeve_trades"].append({
                        "book": bk.parent, "cost_bps": cost, "decision_date": dts[j], "date": str(t["date"]), "kind": t["kind"], "g_before": int(g[j - 1]), "g_after": int(g[j]),
                        "gw_before": float(gw_real[j - 1]), "gw_after": float(gw_real[j]), "gold_value_before": t["gold_before"], "cash_value_before": t["cash_before"],
                        "gold_value_after": t["gold_after"], "cash_value_after": t["cash_after"], "traded": t["traded"], "cost": t["cost"], "gold_fill_raw": bool(bk.gold_norange[t["idx"]])})
        # fixed 50/50 rule on every cell (A1/A2 judge it); the headline cell also keeps its trades
        nv50, tr50, _ = simulate(bk, idx, sf, cost, record=True, gw=None)
        out["rows"].append(stat_row("strategy_fixed50", cost, nv50, tr50, int(s.sum())))
        if headline:
            keep("strategy_fixed50", cost, tr50, None, nv50)
    if headline:
        for cost in costs:
            for name, e_arr, every, gwv in (("hold_parent", np.ones(len(s)), False, None), ("constant_mix", np.full(len(s), f), True, None),
                                            ("constant_mix_timed", np.full(len(s), f), True, gw_real), ("sleeve_only", np.zeros(len(s)), False, None),
                                            ("sleeve_only_timed", np.zeros(len(s)), False, gw_real)):
                nv, tr2, _ = simulate(bk, idx, e_arr, cost, every=every, record=True, gw=gwv)
                out["rows"].append(stat_row(name, cost, nv, tr2, float(e_arr.sum())))
                keep(name, cost, tr2, None, nv)
        r7_runs(bk, idx, sf, gw_real, stat_row, out)

    n = len(next(iter(sio.values())))
    for fam, cost, mode in plan:
        io_k, g_k = FAMILIES[fam]
        for d in range(n):
            st_i = s if io_k == "real" else sio[io_k][d]
            g_i = g if g_k == "real" else sgo[g_k][d]
            st_f = sf if io_k == "real" else fio[io_k][d]
            if mode == "fixed50":
                nv = simulate(bk, idx, st_f, cost, gw=None)
            else:
                nv = simulate(bk, idx, st_f, cost, gw=gw_real if g_k == "real" else fgw[g_k][d])
            ds = stats(nv)
            mi = mio["real"] if io_k == "real" else mio[io_k][d]
            mgd = mg["real"] if g_k == "real" else mg[g_k][d]
            out["draw_rows"].append({
                "book": bk.parent, "window": window, "cash": cash, "cost_bps": cost, "family": fam, "io_null": io_k, "gold_null": g_k, "sleeve_mode": mode, "draw_id": d, **ds,
                "invested_weeks": int(np.asarray(st_i).sum()), "n_in_spells": mi[0], "n_out_spells": mi[1], "spell_sig": mi[2], "strategy_sig": sig_s, "sessions_invested": mi[3],
                "in_lengths": mi[4], "out_lengths": mi[5], "g_buy_weeks": mgd[0], "n_buy_spells": mgd[1], "n_sell_spells": mgd[2], "g_spell_sig": mgd[3], "real_g_spell_sig": sig_g,
                "g_buy_lengths": mgd[4], "g_sell_lengths": mgd[5], "sleeve_trades": 0 if mode == "fixed50" else n_sleeve_trades(idx, bk.T, st_i, g_i)})
            if headline and cost == PRIMARY and mode == "timed" and fam in ("F1", "F3"):
                curves.setdefault(bk.parent, {})[f"{fam}_{d}"] = nv.astype(np.float32)


# ── V4 / V5 / V6 ──────────────────────────────────────────────────────────────
def chi2_sf_even(x: float, df: int) -> float:
    """Survival function of chi-square with an even number of degrees of freedom (closed form)."""
    assert df % 2 == 0
    h, term, tot = x / 2, 1.0, 1.0
    for i in range(1, df // 2):
        term *= h / i
        tot += term
    return math.exp(-h) * tot


def sampler_selftest_small(k=3, S=12, lo=2, hi=6, n=200_000, seed=(6, 123456789)) -> dict:
    """V5(a): enumerate every tuple, draw n samples with the production sampler, chi-square against equal frequencies."""
    tuples = [t for t in np.ndindex(*([hi - lo + 1] * k)) if sum(x + lo for x in t) == S]
    tuples = [tuple(x + lo for x in t) for t in tuples]
    tab = count_table(k, S, lo, hi)
    assert len(tuples) == tab[k][S], (len(tuples), tab[k][S])
    rng = np.random.default_rng(list(seed))
    cnt = {t: 0 for t in tuples}
    for _ in range(n):
        cnt[tuple(draw_lengths(rng, k, S, lo, hi, tab))] += 1
    exp = n / len(tuples)
    chi = float(sum((c - exp) ** 2 / exp for c in cnt.values()))
    df = len(tuples) - 1
    p = chi2_sf_even(chi, df) if df % 2 == 0 else None
    if p is None:
        from scipy.stats import chi2
        p = float(chi2.sf(chi, df))
    return {"k": k, "S": S, "lo": lo, "hi": hi, "n_tuples": len(tuples), "dp_count": int(tab[k][S]), "samples": n, "expected_each": exp,
            "min_count": min(cnt.values()), "max_count": max(cnt.values()), "chi2": chi, "df": df, "p": p, "seed": list(seed), "pass": bool(len(tuples) == 19 and p > 0.001)}


def shared_code_diff() -> dict:
    """V4(c): functions shared with t08_engine.py. Identical = the same AST (docstrings included); the changed ones must be the expected ones."""
    def fns(path):
        tree = ast.parse(Path(path).read_text(encoding="utf-8"))
        return {n.name: ast.dump(n) for n in tree.body if isinstance(n, ast.FunctionDef)}
    a, b = fns(T08_ENGINE), fns(Path(__file__))
    must_equal = ["simulate", "stats", "sessions_invested", "spells", "spell_sig", "count_table", "draw_lengths", "ie_count", "lens_of", "chi2_sf_even", "n_sleeve_trades",
                  "gold_spells_with_out", "flip_counts", "flush_draws"]
    expected_changed = ["ap", "trade", "spell_shuffle", "free_length_draw", "v3_check", "make_states_io", "make_states_gold", "sampler_selftest_small", "run_book", "common",
                        "cash_levels", "v6_check", "main", "raw_parent", "read_pub"]
    common_names = sorted(set(a) & set(b))
    changed = [n for n in common_names if a[n] != b[n]]
    unexpected = [n for n in changed if n not in expected_changed]
    not_equal_required = [n for n in must_equal if n not in a or n not in b or a[n] != b[n]]
    # the sleeve arithmetic lines of `trade` must be the same text in both files
    sleeve_lines = ["Tg = (1 - e_new) * gw_new * V", "Tc = (1 - e_new) * (1 - gw_new) * V", "traded = np.abs(Te - held_s).sum() + abs(Tg - gu * gp) + abs(Tc - cu * lv)",
                    "cost = ow * traded", "k = (V - cost) / V", "Te = e_new * V * w", "new_u[pos] = k * Te[pos] / ps[pos]"]
    t8, t11 = T08_ENGINE.read_text(encoding="utf-8"), Path(__file__).read_text(encoding="utf-8")
    lines_ok = {ln: bool(ln in t8 and ln in t11) for ln in sleeve_lines}
    return {"compared": must_equal, "identical_required": [n for n in must_equal if n not in not_equal_required], "required_not_identical": not_equal_required,
            "changed_functions": changed, "unexpected_changes": unexpected, "expected_changes": expected_changed, "dropped_from_t08": sorted(set(a) - set(b)),
            "new_in_t11": sorted(set(b) - set(a)), "sleeve_arithmetic_lines_in_both": lines_ok,
            "pass": bool(not not_equal_required and not unexpected and all(lines_ok.values()))}


def one_instrument_identity(bk: Book) -> dict:
    """V4(b): the engine on a one-instrument book (weight 1 on one stock in every basket, always in, 0 cost) reproduces that stock's close / first close, for every stock of the T0 basket."""
    r = raw_parent(bk.parent, bk.end)
    union = bk.cal.union(r["close_raw"].index)
    worst, n = {}, 0
    for i in np.flatnonzero(bk.W[bk.b0] > 0):
        ref = r["close_raw"][bk.stocks[i]].reindex(union).ffill().reindex(bk.cal).values.astype(float)
        if not (ref > 0).all():
            continue
        b1 = copy.copy(bk)
        b1.W = np.zeros_like(bk.W)
        b1.W[:, i] = 1.0
        u0 = np.zeros(bk.N)
        u0[i] = 1.0 / bk.C[0, i]
        b1.u0 = u0
        nv = simulate(b1, np.array([0]), np.ones(1), 0.0)
        worst[bk.stocks[i]] = float(np.abs(nv / (ref / ref[0]) - 1).max())
        n += 1
    mx = max(worst.values()) if worst else float("inf")
    return {"stocks_checked": n, "max_rel_diff": mx, "worst_stock": max(worst, key=worst.get) if worst else None, "pass": bool(n > 0 and mx < REL_TOL_NAV)}


def seam_check(bk: Book) -> dict:
    """V4(f): always-in 0-cost NAV on the book's D17 dates against the published NAV: the year's gap in pp (limit G0_YEARLY)."""
    nav = simulate(bk, np.array([0]), np.ones(1), 0.0)
    c = pd.DataFrame({"m": nav, "p": bk.pub}, index=bk.cal)
    c = c / c.iloc[0] * 100
    gap = float((c.m.iloc[-1] / c.m.iloc[0] - c.p.iloc[-1] / c.p.iloc[0]) * 100)
    return {"first": str(c.index[0].date()), "last": str(c.index[-1].date()), "year_gap_pp": gap, "limit_pp": G0_YEARLY, "pass": bool(abs(gap) <= G0_YEARLY)}


def d17_regression(books) -> dict:
    """V4(a), (e), (f): the engine on D17's dates (each book's first date to 2019-12-31) against the stored daily NAVs of T08 and T06, T08's stored gold signal, and the published NAV (seam)."""
    t8n, t6n = pd.read_csv(T08E / "daily_nav.csv"), pd.read_csv(T06E / "daily_nav.csv")
    t8d, t6d, t8g = pd.read_csv(T08E / "decisions.csv"), pd.read_csv(T06E / "decisions.csv"), pd.read_csv(T08E / "gold_signal.csv")
    res = {"t08": {"rows": []}, "t06": {"rows": []}, "b_decisions": {}, "e_d24b_vs_d24": {}, "f_seam": {}, "window": {}, "tolerance_rel": REL_TOL_NAV}
    ok = True
    worst = {"t08": {}, "t06": {}}
    for p in books:
        bk = Book(p, calendar="d17", end=END_D17)
        dec = bk.decisions()
        idx, s, g = dec["decision_idx"].values, dec["state"].values.astype(int), dec["g"].values.astype(int)
        sf, gw_real = s.astype(float), np.where(g == 1, GW_BUY, GW_SELL)
        res["window"][p] = {"t0": str(bk.t0.date()), "last": str(bk.cal[-1].date()), "sessions": bk.T, "decisions": len(dec)}
        mine_dec = dec.assign(decision_date=dec["decision_date"].astype(str))[["decision_date", "decision_idx", "state", "g"]]
        f_of = {}
        for name, d0 in (("t08", t8d), ("t06", t6d)):
            b = d0[d0["book"] == p]
            f_of[name] = float(b["state"].mean())
            cols = ["decision_date", "decision_idx", "state"]
            m = mine_dec.merge(b[cols], on="decision_date", how="left", suffixes=("", "_old"))
            hit = m["state_old"].notna()
            mism = int(((m["state"] != m["state_old"]) | (m["decision_idx"] != m["decision_idx_old"]))[hit].sum())
            unmatched = m.loc[~hit, "decision_date"].tolist()
            good = bool(mism == 0 and hit.sum() > 0 and unmatched in ([], [mine_dec["decision_date"].iloc[-1]]))
            res["b_decisions"][f"{p}|{name}"] = {"compared": int(hit.sum()), "mismatches": mism, "unmatched_dates_in_engine": unmatched, "pass": good}
            ok &= good
        gb = t8g[t8g["book"] == p][["decision_date", "g", "label_MAUc1"]].rename(columns={"g": "g_t08", "label_MAUc1": "label_t08"})
        mg = mine_dec.assign(label=dec["label_MAUc1"].astype(str).values).merge(gb, on="decision_date", how="inner")
        bad_e = int(((mg["g"] != mg["g_t08"]) | (mg["label"] != mg["label_t08"])).sum())
        res["e_d24b_vs_d24"][p] = {"decisions_compared": int(len(mg)), "mismatches": bad_e, "pass": bool(len(mg) > 0 and bad_e == 0)}
        ok &= res["e_d24b_vs_d24"][p]["pass"]
        res["f_seam"][p] = seam_check(bk)
        ok &= res["f_seam"][p]["pass"]
        n_ = len(dec)
        mine = {}
        for cost in COSTS:
            mine[("t08", "strategy", cost)] = simulate(bk, idx, sf, cost, gw=gw_real)
            mine[("t08", "strategy_fixed50", cost)] = simulate(bk, idx, sf, cost, gw=None)
            mine[("t08", "hold_parent", cost)] = simulate(bk, idx, np.ones(n_), cost)
            mine[("t08", "sleeve_only", cost)] = simulate(bk, idx, np.zeros(n_), cost)
            mine[("t08", "sleeve_only_timed", cost)] = simulate(bk, idx, np.zeros(n_), cost, gw=gw_real)
            mine[("t08", "constant_mix", cost)] = simulate(bk, idx, np.full(n_, f_of["t08"]), cost, every=True)
            mine[("t08", "constant_mix_timed", cost)] = simulate(bk, idx, np.full(n_, f_of["t08"]), cost, every=True, gw=gw_real)
            mine[("t06", "strategy", cost)] = mine[("t08", "strategy_fixed50", cost)]
            mine[("t06", "hold_parent", cost)] = mine[("t08", "hold_parent", cost)]
            mine[("t06", "sleeve_only", cost)] = mine[("t08", "sleeve_only", cost)]
            mine[("t06", "constant_mix", cost)] = simulate(bk, idx, np.full(n_, f_of["t06"]), cost, every=True)
        for tag, st in (("t08", t8n), ("t06", t6n)):
            d0 = st[(st["book"] == p) & st["cost_bps"].notna()]
            for (run, cost), gdf in d0.groupby(["run", "cost_bps"]):
                key = (tag, run, float(cost))
                if key not in mine:
                    continue
                gs = gdf.assign(date=pd.to_datetime(gdf["date"])).set_index("date")["nav"]
                mv = pd.Series(mine[key], index=bk.cal)
                cd = gs.index.intersection(mv.index)
                rel = float((mv.loc[cd] / gs.loc[cd] - 1).abs().max()) if len(cd) else float("nan")
                passed = bool(len(cd) == bk.T and rel < REL_TOL_NAV)
                ok &= passed
                worst[tag][run] = max(worst[tag].get(run, 0.0), rel if rel == rel else float("inf"))
                res[tag]["rows"].append({"book": p, "stored_run": run, "cost_bps": float(cost), "dates_compared": int(len(cd)), "sessions": bk.T, "max_rel_diff": rel, "pass": passed,
                                         "f_used": f_of[tag] if run.startswith("constant_mix") else None})
    for tag in ("t08", "t06"):
        res[tag]["rows_compared"] = len(res[tag]["rows"])
        res[tag]["worst_rel_diff_by_run"] = worst[tag]
        res[tag]["pass"] = bool(len(res[tag]["rows"]) > 0 and all(r["pass"] for r in res[tag]["rows"]))
        ok &= res[tag]["pass"]
    res["pass"] = bool(ok)
    return res


def v4_identities(books, bks, dec_all, d17: dict) -> dict:
    """V4 (a) the D17-calendar regression, (b) the one-instrument identity, (c) shared code, (d) signals equal the Master / weekly files, (e) D24b vs D24 (partial), (f) seam."""
    res = {"a_d17_regression": {k: v for k, v in d17.items() if k in ("t08", "t06", "b_decisions", "window", "tolerance_rel", "pass")}, "b_one_instrument": {}, "d_signals": {},
           "e_d24b_vs_d24": d17["e_d24b_vs_d24"], "f_seam": d17["f_seam"]}
    ok = bool(d17["pass"])
    c = common(END)
    for p in books:
        bk = bks[p]
        res["b_one_instrument"][p] = one_instrument_identity(bk)
        ok &= res["b_one_instrument"][p]["pass"]
        dec = next(d for d in dec_all if d["book"].iloc[0] == p)
        bad = {"index_sign": 0, "mauc1_sign": 0, "mauc1_weekly_signal": 0, "mauc1_weekly_label": 0, "index_label": 0}
        wk = c["gold_weekly"]
        for r in dec.itertuples():
            d = pd.Timestamp(r.decision_date)
            for n in INDICES:
                sr = c["master"][n]
                got = sr[sr.index <= d]
                bad["index_sign"] += got.iloc[-1] != getattr(r, f"sign_{n}")
                bad["index_label"] += str(got.index[-1].date()) != str(getattr(r, f"label_{n}"))
            gsr = c["gold_master"]
            bad["mauc1_sign"] += gsr[gsr.index <= d].iloc[-1] != r.sign_MAUc1
            k = wk["review"].searchsorted(d, side="right") - 1
            bad["mauc1_weekly_signal"] += int(round(float(wk["signal"].iloc[k]))) != int(r.g)
            bad["mauc1_weekly_label"] += str(wk["review"].iloc[k].date()) != str(r.label_MAUc1)
        pd_ = bool(all(v == 0 for v in bad.values()) and len(dec) > 0)
        res["d_signals"][p] = {"decisions": int(len(dec)), **{k: int(v) for k, v in bad.items()}, "pass": pd_}
        ok &= pd_
    res["c_shared_code"] = shared_code_diff()
    ok &= res["c_shared_code"]["pass"]
    ok &= all(v["pass"] for v in res["e_d24b_vs_d24"].values()) and all(v["pass"] for v in res["f_seam"].values())
    res["pass"] = bool(ok)
    return res


def v6_check(out: dict, books, bks: dict, dec_all: list) -> dict:
    """V6 the sleeve, basket and cost identities, on every trade of every headline run (full window, LBES) and on constant-g re-runs."""
    TOL = 1e-12
    worst = {"cost_identity": 0.0, "value_conservation": 0.0, "stock_target_gap": 0.0, "gold_target_gap": 0.0, "cash_target_gap": 0.0, "traded_identity": 0.0,
             "continuity_0cost": 0.0, "weight_gap_vs_table": 0.0, "stock_weight_gap_after_entry_or_basket_change": 0.0}
    kinds, n, n0 = Counter(), 0, 0
    decs = {d["book"].iloc[0]: d for d in dec_all}
    for t in out["trades"]:
        V, cost, ow = t["V"], t["cost"], t["cost_bps"] / 2e4
        e, gwv = t["e_after"], t["gw_after"]
        n += 1
        kinds[(t["run"], t["kind"])] += 1
        worst["cost_identity"] = max(worst["cost_identity"], abs(cost - ow * t["traded"]) / V)
        worst["value_conservation"] = max(worst["value_conservation"], abs(t["V_after"] - (V - cost)) / V)
        if t["cost_bps"] == 0:
            n0 += 1
            worst["continuity_0cost"] = max(worst["continuity_0cost"], abs(t["V_after"] - V) / V)
        worst["stock_target_gap"] = max(worst["stock_target_gap"], abs(t["stock_after"] - e * (V - cost)) / V)
        worst["gold_target_gap"] = max(worst["gold_target_gap"], abs(t["gold_after"] - (1 - e) * gwv * (V - cost)) / V)
        worst["cash_target_gap"] = max(worst["cash_target_gap"], abs(t["cash_after"] - (1 - e) * (1 - gwv) * (V - cost)) / V)
        if t["kind"] in ("switch_in", "basket_change", "mix_rebalance") and e > 0:
            worst["stock_weight_gap_after_entry_or_basket_change"] = max(worst["stock_weight_gap_after_entry_or_basket_change"], t["weight_gap"])
        if e == 0:      # sleeve only after the trade: traded = stock sold + |gold target - held| + |cash target - held|
            exp_tr = t["stock_before"] + abs(gwv * V - t["gold_before"]) + abs((1 - gwv) * V - t["cash_before"])
            worst["traded_identity"] = max(worst["traded_identity"], abs(t["traded"] - exp_tr) / V)
        if t["run"] == "strategy" and t["kind"] in SLEEVE_KINDS:
            j = t["dec_j"]
            d = decs[t["book"]]
            want = GW_BUY if int(d["g"].iloc[j]) == 1 else GW_SELL
            sh = t["gold_after"] / (t["gold_after"] + t["cash_after"])
            worst["weight_gap_vs_table"] = max(worst["weight_gap_vs_table"], abs(sh - want), abs(gwv - want))
            assert t["kind"] == "switch_out" or (t["stock_before"] == 0 and e == 0)
    # the real rule's sleeve trades and basket changes equal the independent expectation at every cost (from the states and the calendar alone)
    count_ok, basket_ok, listed, listed_b = True, True, {}, {}
    for p in books:
        d = decs[p]
        bk = bks[p]
        idx, s, g = d["decision_idx"].values, d["state"].values.astype(int), d["g"].values.astype(int)
        T = bk.T
        exp = sorted(int(idx[j]) + 1 for j in range(1, len(idx)) if int(idx[j]) + 1 < T and s[j] == 0 and s[j - 1] == 0 and g[j] != g[j - 1])
        change = {int(idx[j]) + 1: s[j] for j in range(1, len(idx)) if int(idx[j]) + 1 < T and s[j] != s[j - 1]}
        cur, held_before = int(s[0]), np.zeros(T, dtype=int)
        for t in range(T):
            held_before[t] = cur
            if t in change:
                cur = int(change[t])
        exp_b = sorted(t for t in bk.basket_events if held_before[t] == 1 and t not in change)
        exp_b_hold = sorted(bk.basket_events)
        for cost in COSTS:
            got = sorted(t["idx"] for t in out["trades"] if t["book"] == p and t["run"] == "strategy" and t["cost_bps"] == cost and t["kind"] == "sleeve_rebalance")
            count_ok &= got == exp
            for run, want in (("strategy", exp_b), ("strategy_fixed50", exp_b), ("hold_parent", exp_b_hold)):
                got_b = sorted(t["idx"] for t in out["trades"] if t["book"] == p and t["run"] == run and t["cost_bps"] == cost and t["kind"] == "basket_change")
                basket_ok &= got_b == want
        listed[p], listed_b[p] = len(exp), {"strategy": len(exp_b), "hold_parent": len(exp_b_hold), "basket_sessions_after_T0": len(bk.basket_events)}
    # constant g: with the gold signal held constant no sleeve trade occurs (both constants), at 0 and 20.8 bps
    const = {}
    for p in books:
        d = decs[p]
        idx, s = d["decision_idx"].values, d["state"].values.astype(float)
        for name, c_ in (("BUY", GW_BUY), ("SELL", GW_SELL)):
            for cost in (0.0, PRIMARY):
                _, tr, _ = simulate(bks[p], idx, s, cost, record=True, gw=np.full(len(s), c_))
                const[f"{p}|{name}|{cost}"] = {"sleeve_trades": sum(1 for t in tr if t["kind"] == "sleeve_rebalance"), "trades": len(tr)}
    const_ok = all(v["sleeve_trades"] == 0 for v in const.values())
    # worked examples (recorded values for the first book at 20.8 bps)
    ex = {}
    p0 = books[0]
    for kind in ("switch_out", "sleeve_rebalance", "switch_in", "basket_change"):
        for t in out["trades"]:
            if t["book"] == p0 and t["run"] == "strategy" and t["cost_bps"] == PRIMARY and t["kind"] == kind:
                j = t["dec_j"]
                d = decs[p0].iloc[j] if j is not None else None
                gwv, V, cost = t["gw_after"], t["V"], t["cost"]
                bk = bks[p0]
                nzb = np.flatnonzero((t["held_before"] > 0) | (t["val_after"] > 0))
                ex[kind] = {"decision_date": str(d["decision_date"]) if d is not None else None, "trade_date": str(t["date"]), "idx": t["idx"], "g_read": d["sign_MAUc1"] if d is not None else None,
                            "gw": gwv, "V": V, "stock_before": t["stock_before"], "gold_before": t["gold_before"], "cash_before": t["cash_before"], "traded": t["traded"], "cost": cost,
                            "stock_after": t["stock_after"], "gold_after": t["gold_after"], "cash_after": t["cash_after"], "basket_eff": str(bk.eff[bk.basket_at[t["idx"]]].date()),
                            "expected_stock_after": t["e_after"] * (V - cost), "expected_gold_after": (1 - t["e_after"]) * gwv * (V - cost),
                            "expected_cash_after": (1 - t["e_after"]) * (1 - gwv) * (V - cost),
                            "stocks_before_after": {bk.stocks[i]: [float(t["held_before"][i]), float(t["val_after"][i])] for i in nzb[:60]} if kind in ("basket_change", "switch_in") else None}
                break
    ok = bool(n > 0 and all(v <= TOL for v in worst.values()) and count_ok and basket_ok and const_ok)
    return {"trades_checked": int(n), "trades_checked_at_0_cost": int(n0), "kinds": {f"{a}|{b}": int(c) for (a, b), c in sorted(kinds.items())}, "worst": worst, "tolerance": TOL,
            "real_rule_sleeve_trades_equal_expected_at_every_cost": bool(count_ok), "expected_sleeve_trades_per_book": listed,
            "basket_changes_equal_expected_at_every_cost": bool(basket_ok), "expected_basket_changes_per_book": listed_b, "constant_g_no_sleeve_trade": const_ok, "constant_g_detail": const,
            "worked_examples": ex,
            "not_checked_here": "weights drift between trades by construction (units are constant between trade sessions); the initial position at T0 is built without a trade record", "pass": ok}


def flush_draws(out: dict, path: Path, first: bool):
    if out["draw_rows"]:
        pd.DataFrame(out["draw_rows"]).to_csv(path, mode="w" if first else "a", header=first, index=False)
        out["draw_rows_written"] += len(out["draw_rows"])
    out["draw_rows"] = []


def baskets_table(bk: Book, p: str) -> list[dict]:
    r = raw_parent(p, bk.end)
    rows, first = [], True
    for k, d in enumerate(bk.eff):
        if d < bk.t0 or d > bk.end:
            continue
        rows.append({"book": p, "basket_no": len(rows), "available_date": str(d.date()), "session_date": str(bk.cal[int(bk.bidx[k])].date()), "idx": int(bk.bidx[k]),
                     "n_held": int((bk.W[k] > 0).sum()), "raw_weight_sum": float(r["wsum"].iloc[k]), "role": "initial" if first else "change"})
        first = False
    return rows


def held_src_counts(bk: Book) -> dict:
    """E24: held stock-sessions by D18 src on the window's sessions (basket in force on the session), per stock for 'export'."""
    held = bk.W[bk.basket_at] > 0
    srcs = np.where(pd.isna(bk.src), "none", bk.src)
    out = {k: int(((srcs == k) & held).sum()) for k in ("db", "export", "carried", "none")}
    per_exp = {bk.stocks[i].replace(".NS", ""): int(((srcs[:, i] == "export") & held[:, i]).sum()) for i in range(bk.N) if ((srcs[:, i] == "export") & held[:, i]).any()}
    carried_all = int((srcs == "carried").sum())
    carried_dates = sorted({f"{bk.stocks[i].replace('.NS', '')} {bk.cal[t].date()}" for t, i in zip(*np.nonzero(srcs == "carried"))})
    none_by_session = {str(bk.cal[t].date()): int(n) for t, n in enumerate(((srcs == "none") & held).sum(axis=1)) if n > 0}
    return {"held_stock_sessions_by_src": out, "export_by_stock": per_exp, "carried_bars_in_window_all_stocks": carried_all, "carried_bars": carried_dates,
            "held_stock_sessions_without_a_bar_by_session": none_by_session}


def window_check(p: str, mine: dict, w: str, ct: dict, s1: dict) -> bool:
    """The Step 1 counts (spells, bounds, gold series, flips, tuple counts) reproduced by the engine's own series for one book and window ('full' or 'r3')."""
    exp = s1[w]
    gm = mine["gold"] if w == "full" else mine
    gl = (lambda k: gm[k]) if w == "full" else (lambda k: mine["gold_" + k])
    good = (mine["in_lengths"] == exp["in_lengths"] and mine["out_lengths"] == exp["out_lengths"] and mine["first_state"] == exp["first_state"] and mine["decisions"] == exp["weeks"]
            and mine["sessions"] == exp["sessions"]
            and (gm["buy_lengths"] if w == "full" else mine["g_buy_lengths"]) == exp["g_buy_lengths"]
            and (gm["sell_lengths"] if w == "full" else mine["g_sell_lengths"]) == exp["g_sell_lengths"]
            and (gm["first_state"] if w == "full" else mine["gold_first_state"]) == exp["g_first_state"]
            and gl("flips") == exp["g_flips"] and gl("while_out_both_sides") == exp["g_flips_while_out_both_sides"] and gl("on_exit_decision") == exp["g_flips_on_an_exit_decision"]
            and (gl("while_in") + gl("on_entry_decision")) == exp["g_flips_while_in"]            # E23: step 1 counts every flip at a decision whose state is IN
            and (gm["spells_with_an_out_week"] if w == "full" else mine["gold_spells_with_an_out_week"]) == exp["g_spells_with_an_out_week"]
            and gl("weeks_buy_while_out") == exp["g_weeks_buy_while_out"] and gl("weeks_sell_while_out") == exp["g_weeks_sell_while_out"]
            and mine["round_trips"] == exp["round_trips"])
    for ser, tkey, names in (("io", "io_tables", ("in", "out")), ("gold", "gold_tables", ("buy", "sell"))):
        for nm, enm in zip(names, ("in", "out")):
            c_ = ct[f"{p}|{w}|{ser}|{nm}"]
            t_ = exp[tkey][enm]
            good &= (c_["n_ways"] == t_["n_ways"] and c_["lo"] == t_["lo"] and c_["hi"] == t_["hi"] and c_["spells_k"] == t_["k"] and c_["weeks_S"] == t_["S"])
    return bool(good)


def main():
    ap_ = argparse.ArgumentParser()
    ap_.add_argument("--run", default="headline")
    ap_.add_argument("--draws", type=int, default=None)
    ap_.add_argument("--quick", action="store_true", help="smoke test: the first book only, 20 draws unless --draws is given")
    ap_.add_argument("--books", nargs="+", default=None)
    ap_.add_argument("--calendar", choices=["d26", "d17"], default="d26",
                     help="d17: run only the V4(a)/(e)/(f) regression on D17's dates (T0 = each book's first D17 date, end 2019-12-31) and write regression_d17.json")
    ap_.add_argument("--outdir", default=None, help="write here instead of tests/T11/evidence/<run> (scratch runs)")
    a = ap_.parse_args()
    outdir = Path(a.outdir) if a.outdir else T11 / "evidence" / a.run
    outdir.mkdir(parents=True, exist_ok=True)
    t_start = time.time()
    books = a.books or (PARENTS[:1] if a.quick else PARENTS)
    assert all(b in PARENTS for b in books), books
    n_draws = a.draws if a.draws else (20 if a.quick else N_DRAWS)

    def write_inputs():
        pd.DataFrame([{k: v.get(k) for k in ("file", "through", "bytes", "sha256", "approved_row", "usable_from")} for v in USED.values()]).to_csv(outdir / "inputs.csv", index=False)

    if a.calendar == "d17":
        reg = d17_regression(a.books or PARENTS)
        (outdir / "regression_d17.json").write_text(json.dumps(reg, indent=1, default=str), encoding="utf-8")
        write_inputs()
        print("V4(a)/(e)/(f) on D17's dates:", {"t08_rows": reg["t08"]["rows_compared"], "t06_rows": reg["t06"]["rows_compared"], "worst_t08": reg["t08"]["worst_rel_diff_by_run"],
                                              "worst_t06": reg["t06"]["worst_rel_diff_by_run"], "seam_pp": {k: round(v["year_gap_pp"], 4) for k, v in reg["f_seam"].items()}, "pass": reg["pass"]})
        sys.exit(0 if reg["pass"] else 1)

    s1 = json.loads(STEP1.read_text(encoding="utf-8"))
    assert s1["window"] == [str(T0.date()), str(END.date())] and s1["r3_start"] == str(R3_START.date()), f"step_1_spell_counts.json is for {s1['window']}, the engine has T0 {T0.date()}"
    out = {"rows": [], "draw_rows": [], "draw_rows_written": 0, "nav": {}, "trades": [], "positions": [], "sleeve_trades": [], "v2_trades": 0, "v2_basket_trades": 0,
           "r7_flagged": [], "r7_export": [], "r7_summary": {}}
    curves: dict = {}
    dec_all, bks = [], {}
    audit = {"readings": READINGS, "books": {}}

    # the data boundary: every input through the approved table, sha256 checked, window covered, rule 7 guard
    c0 = common(END)
    selftest = {}
    for name, f in (("superseded_master", HD / "frozen_2026-09-25" / "Master" / "Master_Nifty100.xlsx"),
                    ("superseded_goldbees", AA / "analysis" / "cache" / "why_gold_ohlc_eikon.parquet"),
                    ("superseded_lbes", HD / "LBES_Adjusted_Price_data_2026_08_10.csv"),
                    ("pending_candidate_d03b", HD / "extended_2026-11-12" / "SC100_signal_from_2011-10-03" / "Master_SC100.xlsx"),
                    ("not_in_table", HD / "no_such_file.csv")):
        try:
            ap(f)
            selftest[name] = {"raised": False}
        except NotApprovedError as e:
            selftest[name] = {"raised": True, "message": str(e)}
    uf_sig = pd.Timestamp(AD.usable_from(MASTER_DIR / "Master_SC100.xlsx"))
    assert uf_sig == SC_USABLE_FROM, uf_sig
    try:
        AD.guard_window(MASTER_DIR / "Master_SC100.xlsx", str((uf_sig - pd.Timedelta(days=1)).date()))
        selftest["guard_sc100_signal_before_usable_from"] = {"raised": False}
    except NotApprovedError as e:
        selftest["guard_sc100_signal_before_usable_from"] = {"raised": True, "message": str(e)}
    AD.guard_window(MASTER_DIR / "Master_SC100.xlsx", SC_USABLE_FROM)
    selftest["guard_sc100_at_usable_from_passes"] = {"raised": False, "ok": True}
    selftest["pass"] = all(v.get("raised", False) for k, v in selftest.items() if isinstance(v, dict) and k != "guard_sc100_at_usable_from_passes")
    print(f"data: window {T0.date()} -> {END.date()}, approved data as of {AD.as_of()}, {len(USED)} inputs checked; non-approved open and the Smallcap 100 guard raise: {selftest['pass']}", flush=True)

    ct, v3_res, v5c = {}, {}, {}
    states_all: dict = {}
    real_states: dict = {}
    first_draw_write = True
    shared: dict = {}
    r3_gate: dict = {}
    step1_detail: dict = {}
    frozen_detail: dict = {}
    bk_rows: list = []
    for p in books:
        t1 = time.time()
        bk = Book(p)
        bks[p] = bk
        dec = bk.decisions()
        dec_all.append(dec)
        r = raw_parent(p, END)
        s = dec["state"].values.astype(int)
        g = dec["g"].values.astype(int)
        b_io, b_g = series_bounds(s), series_bounds(g)
        exp_io, exp_g = s1["full"]["io_tables"], s1["full"]["gold_tables"]
        for st, nm in ((1, "in"), (0, "out")):
            assert b_io[st] == (exp_io[nm]["lo"], exp_io[nm]["hi"]), f"{p}: in/out bounds {b_io[st]} differ from step 1 {exp_io[nm]}"
            assert b_g[st] == (exp_g[nm]["lo"], exp_g[nm]["hi"]), f"{p}: gold bounds {b_g[st]} differ from step 1 {exp_g[nm]}"
        # baskets (E5): D19's effective dates T0..END = D05's non-skipped availableDates = step 1's list; the initial one is T0's
        eff_win = [str(d.date()) for d in bk.eff if T0 <= d <= END]
        d05_win = [str(d.date()) for d in r["d05"] if T0 <= d <= END]
        eb = s1["baskets"][p]
        assert eff_win == eb["effective_dates"] == d05_win, f"{p}: baskets {eff_win} / D05 {d05_win} / step 1 {eb['effective_dates']}"
        assert len(eff_win) == eb["baskets_effective_T0_to_END_inclusive"] == 19 and len(bk.basket_events) == eb["basket_changes_after_T0"] == 18
        assert str(bk.eff[bk.b0].date()) == str(T0.date()) and bk.initial_basket_switch_session == str(T0.date())
        assert not [d for d in r["skipped"] if T0 <= d <= END] and eb["skipped_in_window"] == 0
        assert str(bk.eff[bk.b0 - 1].date()) == eb["basket_in_force_on_2014-07-01"]["effective"], (bk.eff[bk.b0 - 1], eb["basket_in_force_on_2014-07-01"])
        bk_rows += baskets_table(bk, p)
        # calendar facts (E1)
        cal_all = c0["cal_all"]
        d26_from_first = int(((cal_all >= FIRST_PRICE_DAY) & (cal_all <= END)).sum())
        d18_from_first = int(((r["d18_dates"] >= FIRST_PRICE_DAY) & (r["d18_dates"] <= END)).sum())
        d18_in_window_not_d26 = [str(d.date()) for d in r["d18_dates"] if T0 <= d <= END and d not in set(bk.cal)]
        no_d18_session = [str(d.date()) for d in bk.cal if d not in set(r["d18_dates"])]
        sess_no_bar_any_held = int(((bk.W[bk.basket_at] > 0) & bk.nobar).any(axis=1).sum())
        # V2: point-in-time counts (index Masters and MAUc1)
        lab_ok = int((pd.to_datetime(dec["latest_label"]) <= pd.to_datetime(dec["decision_date"])).sum())
        lab_g_ok = int((pd.to_datetime(dec["label_MAUc1"]) <= pd.to_datetime(dec["decision_date"])).sum())
        trade_idx = dec["decision_idx"].values + 1
        traded_rows = int((trade_idx < bk.T).sum())
        tdates = pd.to_datetime(dec["trade_date"].dropna())
        ddates = pd.to_datetime(dec.loc[dec["trade_date"].notna(), "decision_date"])
        assert (tdates.values > ddates.values).all()
        assert (pd.to_datetime(dec["latest_label"]).values <= pd.to_datetime(dec["decision_date"]).values).all()
        assert (pd.to_datetime(dec["label_MAUc1"]).values <= pd.to_datetime(dec["decision_date"]).values).all()
        sc_min_label = pd.to_datetime(dec["label_SC100"]).min()
        assert sc_min_label >= SC_USABLE_FROM, f"a Smallcap 100 signal row dated {sc_min_label.date()} (before the usable-from date) was read"
        r0, rg = lens_of(s), lens_of(g)
        fl = flip_counts(s, g)
        hs = held_src_counts(bk)
        exp_ok = bool(hs["export_by_stock"] == FROZEN_EXPORT[p] and hs["held_stock_sessions_by_src"]["export"] == FROZEN_EXPORT_TOTAL[p] and hs["carried_bars_in_window_all_stocks"] == FROZEN_CARRIED[p])
        frozen_detail[p] = {"pass": exp_ok, "export_by_stock": hs["export_by_stock"], "expected_export_by_stock": FROZEN_EXPORT[p], "export_total": hs["held_stock_sessions_by_src"]["export"],
                            "expected_export_total": FROZEN_EXPORT_TOTAL[p], "carried_in_window": hs["carried_bars_in_window_all_stocks"], "expected_carried": FROZEN_CARRIED[p]}
        gold_in_window = c0["gold_first"] <= bk.t0
        audit["books"][p] = {"t0": str(bk.t0.date()), "last_session": str(bk.cal[-1].date()), "sessions": bk.T, "decisions": len(dec), "invested_weeks": int(s.sum()),
                             "first_state": int(s[0]), "in_lengths": r0[0], "out_lengths": r0[1], "bounds": {"in": list(b_io[1]), "out": list(b_io[0])},
                             "in_spells": len(r0[0]), "out_spells": len(r0[1]), "round_trips": min(len(r0[0]), len(r0[1])),
                             "sessions_invested_rule": sessions_invested(bk, dec["decision_idx"].values, s),
                             "gold": {"first_state": int(g[0]), "buy_lengths": rg[0], "sell_lengths": rg[1], "buy_weeks": int(g.sum()), "bounds": {"buy": list(b_g[1]), "sell": list(b_g[0])},
                                      "shortest_spell": min(rg[0] + rg[1]), "spells_with_an_out_week": gold_spells_with_out(s, g), **fl,
                                      "sleeve_trades_expected": n_sleeve_trades(dec["decision_idx"].values, bk.T, s, g)},
                             "baskets": {"effective_dates_T0_to_END": eff_win, "basket_changes": len(bk.basket_events), "initial_basket_session": bk.initial_basket_switch_session,
                                         "basket_not_used_in_force_on_2014-07-01": str(bk.eff[bk.b0 - 1].date()), "change_sessions": [str(bk.cal[i].date()) for i in sorted(bk.basket_events)]},
                             "v2_decisions_checked": len(dec), "v2_label_after_decision": len(dec) - lab_ok, "v2_mauc1_label_after_decision": len(dec) - lab_g_ok,
                             "v2_trades_checked": traded_rows, "v2_trade_not_after_decision": int((tdates.values <= ddates.values).sum()),
                             "v2_sc100_signal_first_label_date": str(sc_min_label.date()),
                             "stale_label_weeks(age>=5d, excluding T0)": int((dec["label_age_days"].values[1:] >= 5).sum()), "cash": bk.cash_info,
                             "calendar": {"d26_sessions_from_2014-07-01_to_END": d26_from_first, "d18_sessions_from_2014-07-01_to_END": d18_from_first, "window_sessions": bk.T,
                                          "d18_dates_in_window_not_in_d26": d18_in_window_not_d26, "d26_sessions_in_window_without_any_d18_bar": no_d18_session,
                                          "window_sessions_where_a_held_stock_has_no_bar": sess_no_bar_any_held},
                             "gold_sessions_without_own_bar": bk.gold_no_own_bar, "goldbees_first_bar_on_or_before_T0": bool(gold_in_window),
                             "gold_sessions_without_mcx_range_in_window": [str(d.date()) for d in bk.cal[bk.gold_norange]],
                             "src_counts": hs}
        assert audit["books"][p]["gold"]["shortest_spell"] >= LO_CAP and no_d18_session == [str(NO_D18_SESSION.date())] and bk.gold_no_own_bar == [str(NO_GOLD_SESSION.date())]
        real_states[f"{p}|full|io"], real_states[f"{p}|full|gold"] = s.astype(np.uint8), g.astype(np.uint8)
        if "full" not in shared:                                              # E15: one set of draws for the four books
            shared["full"] = {"s": s, "g": g, "io": make_states_io(s, n_draws, b_io), "gold": make_states_gold(g, n_draws, b_g)}
        else:
            assert (shared["full"]["s"] == s).all() and (shared["full"]["g"] == g).all(), "the books' decision series differ"
        st_io, st_g = shared["full"]["io"], shared["full"]["gold"]
        for k, v in st_io.items():
            states_all[f"{p}|full|io|{k}"] = v
        for k, v in st_g.items():
            states_all[f"{p}|full|gold|{k}"] = v
        v3_res[f"{p}|full|io"] = v3_check(s, st_io, b_io)
        v3_res[f"{p}|full|gold"] = v3_check(g, st_g, b_g)
        plan_full = ([(fm, c, "timed") for fm in ("F1", "F2", "F3", "F4") for c in COSTS] + [("F5", PRIMARY, "timed")]
                     + [(fm, c, "fixed50") for fm in ("F1", "F2") for c in COSTS])
        bk.nobar_trades = bk.gold_norange_trades = bk.gold_nobar_trades = 0
        run_book(bk, dec, st_io, st_g, "full", "lbes", plan_full, True, out, curves)
        audit["books"][p]["stock_lines_priced_by_stand_in_in_trades(all runs incl. draws)"] = bk.nobar_trades
        audit["books"][p]["goldbees_trades_filled_at_raw_OHLC4_no_MCX_range(all runs incl. draws)"] = bk.gold_norange_trades
        audit["books"][p]["goldbees_trades_priced_at_previous_close_no_gold_bar(all runs incl. draws)"] = bk.gold_nobar_trades
        # R2: LIQUIDCASE cash (the same states)
        bk3 = Book(p, cash="liq")
        run_book(bk3, dec, st_io, st_g, "full", "liq", [("F1", PRIMARY, "timed"), ("F3", PRIMARY, "timed"), ("F1", PRIMARY, "fixed50")], False, out, curves)
        # R3: window from 2015-01-02, its own spells, totals and bounds
        bk4 = Book(p, start=R3_START)
        dec4 = bk4.decisions()
        s4, g4_ = dec4["state"].values.astype(int), dec4["g"].values.astype(int)
        b4_io, b4_g = series_bounds(s4), series_bounds(g4_)
        for st, nm in ((1, "in"), (0, "out")):
            assert b4_io[st] == (s1["r3"]["io_tables"][nm]["lo"], s1["r3"]["io_tables"][nm]["hi"]) and b4_g[st] == (s1["r3"]["gold_tables"][nm]["lo"], s1["r3"]["gold_tables"][nm]["hi"])
        r4, rg4 = lens_of(s4), lens_of(g4_)
        rt = min(len(r4[0]), len(r4[1]))
        feas = {"in": b4_io[1][0] * len(r4[0]) <= sum(r4[0]) <= b4_io[1][1] * len(r4[0]), "out": b4_io[0][0] * len(r4[1]) <= sum(r4[1]) <= b4_io[0][1] * len(r4[1]),
                "buy": b4_g[1][0] * len(rg4[0]) <= sum(rg4[0]) <= b4_g[1][1] * len(rg4[0]), "sell": b4_g[0][0] * len(rg4[1]) <= sum(rg4[1]) <= b4_g[0][1] * len(rg4[1])}
        gout = gold_spells_with_out(s4, g4_)
        r3_ok = bool(rt >= 4 and gout >= 4 and all(feas.values()))
        r3_gate[p] = {"round_trips": rt, "gold_spells_with_an_out_week": gout, "feasible": feas, "reportable": r3_ok}
        audit["books"][p]["r3_window"] = {"t0": str(bk4.t0.date()), "sessions": bk4.T, "decisions": len(dec4), "round_trips": rt, "reportable": r3_ok, "first_state": int(s4[0]), "in_lengths": r4[0],
                                          "out_lengths": r4[1], "bounds": {"in": list(b4_io[1]), "out": list(b4_io[0]), "buy": list(b4_g[1]), "sell": list(b4_g[0])}, "gold_first_state": int(g4_[0]),
                                          "g_buy_lengths": rg4[0], "g_sell_lengths": rg4[1], "gold_spells_with_an_out_week": gout, "feasible": feas,
                                          **{f"gold_{k}": v for k, v in flip_counts(s4, g4_).items()}, "sessions_invested_rule": sessions_invested(bk4, dec4["decision_idx"].values, s4),
                                          "initial_basket_switch_session": bk4.initial_basket_switch_session}
        real_states[f"{p}|r3|io"], real_states[f"{p}|r3|gold"] = s4.astype(np.uint8), g4_.astype(np.uint8)
        windows = [("full", s, g, b_io, b_g)]
        if r3_ok:
            windows.append(("r3", s4, g4_, b4_io, b4_g))
            if "r3" not in shared:
                shared["r3"] = {"s": s4, "g": g4_, "io": make_states_io(s4, n_draws, b4_io), "gold": make_states_gold(g4_, n_draws, b4_g)}
            else:
                assert (shared["r3"]["s"] == s4).all() and (shared["r3"]["g"] == g4_).all()
            sl_io, sl_g = shared["r3"]["io"], shared["r3"]["gold"]
            for k, v in sl_io.items():
                states_all[f"{p}|r3|io|{k}"] = v
            for k, v in sl_g.items():
                states_all[f"{p}|r3|gold|{k}"] = v
            v3_res[f"{p}|r3|io"] = v3_check(s4, sl_io, b4_io)
            v3_res[f"{p}|r3|gold"] = v3_check(g4_, sl_g, b4_g)
            run_book(bk4, dec4, sl_io, sl_g, "r3", "lbes", [("F1", PRIMARY, "timed"), ("F3", PRIMARY, "timed"), ("F1", PRIMARY, "fixed50")], False, out, curves)
        for w, sw, gwk, bio, bg in windows:
            for ser, arr, bnd, names, nullkey in (("io", sw, bio, ("in", "out"), "N4.10"), ("gold", gwk, bg, ("buy", "sell"), "N4.10-g")):
                rr = lens_of(arr)
                for stn, ls, stt, ix in zip(names, rr, (1, 0), (0, 1)):
                    lo, hi = bnd[stt]
                    k, S = len(ls), sum(ls)
                    tab = count_table(k, S, lo, hi)
                    n_dp, n_ie = int(tab[k][S]), ie_count(k, S, lo, hi)
                    ct[f"{p}|{w}|{ser}|{stn}"] = {"book": p, "window": w, "series": ser, "state": stn, "weeks_S": S, "spells_k": k, "lo": lo, "hi": hi,
                                                  "feasible_lo*k<=S<=hi*k": bool(lo * k <= S <= hi * k), "n_ways": str(n_dp), "n_ways_inclusion_exclusion": str(n_ie),
                                                  "dp_equals_inclusion_exclusion": n_dp == n_ie, "rule_lengths_within_bounds": bool(all(lo <= x <= hi for x in ls))}
                    M = np.array([lens_of(st.astype(int))[ix] for st in states_all[f"{p}|{w}|{ser}|{nullkey}"]], dtype=float)
                    sd = M.std(axis=0, ddof=1) if len(M) > 1 else np.zeros(M.shape[1])
                    se = sd / math.sqrt(len(M))
                    dev = np.abs(M.mean(axis=0) - S / k)
                    z = np.where(se > 0, dev / np.where(se > 0, se, 1), np.where(dev > 0, np.inf, 0.0))
                    v5c[f"{p}|{w}|{ser}|{stn}"] = {"draws": int(len(M)), "target_S_over_k": S / k, "mean_over_positions_and_draws": float(M.mean()),
                                                   "max_abs_z_per_position": float(z.max()), "pass": bool(z.max() <= 4.0)}
        step1_detail[f"{p}|full"] = window_check(p, audit["books"][p], "full", ct, s1)
        if r3_ok:
            step1_detail[f"{p}|r3"] = window_check(p, {**audit["books"][p]["r3_window"], "sessions": bk4.T}, "r3", ct, s1)
        flush_draws(out, outdir / "draws.csv", first_draw_write)
        first_draw_write = False
        print(f"{p}: {time.time() - t1:.0f}s  decisions {len(dec)}  round trips {audit['books'][p]['round_trips']}  gold flips {fl['flips']} (sleeve trades {audit['books'][p]['gold']['sleeve_trades_expected']})", flush=True)

    # V4: the D17-calendar regression against T08 and T06, identities, V5 samplers, V6 identities, V3 summary
    d17 = d17_regression(PARENTS)
    (outdir / "regression_d17.json").write_text(json.dumps(d17, indent=1, default=str), encoding="utf-8")
    reg = v4_identities(books, bks, dec_all, d17)
    (outdir / "regression.json").write_text(json.dumps(reg, indent=1, default=str), encoding="utf-8")
    small = sampler_selftest_small()                                   # T06/T08's self-test seed [6, 123456789]: same sampler code, same k, S, bounds
    small14 = sampler_selftest_small(seed=(14, 6, 123456789))          # and a seed with T11's first element, reported beside it
    small["also_seed_14"] = {"p": small14["p"], "pass": small14["pass"], "seed": small14["seed"]}
    small["pass"] = bool(small["pass"] and small14["pass"])
    v5b = all(v["dp_equals_inclusion_exclusion"] for v in ct.values())
    v5 = {"a_small_case": small, "b_dp_equals_inclusion_exclusion": {"all_equal": bool(v5b), "checked": int(len(ct))},
          "c_mean_length_within_4_se": v5c, "pass": bool(small["pass"] and v5b and all(v["pass"] for v in v5c.values()))}
    (outdir / "sampler_selftest.json").write_text(json.dumps(v5, indent=1, default=str), encoding="utf-8")
    b0 = audit["books"][books[0]]
    (outdir / "count_table.json").write_text(json.dumps({"bounds": {"full": {"io": b0["bounds"], "gold": b0["gold"]["bounds"]}, "r3": b0["r3_window"]["bounds"]}, "tables": ct}, indent=1), encoding="utf-8")
    v6 = v6_check(out, books, bks, dec_all)
    s1_ok = bool(all(step1_detail.values()) and len(step1_detail) == 2 * len(books))
    frozen_ok = bool(all(v["pass"] for v in frozen_detail.values()))

    # write
    flush_draws(out, outdir / "draws.csv", first_draw_write)
    pd.concat(dec_all).to_csv(outdir / "decisions.csv", index=False)
    pd.concat(dec_all)[["book", "j", "decision_date", "label_MAUc1", "sign_MAUc1", "g", "gw"]].to_csv(outdir / "gold_signal.csv", index=False)
    pd.DataFrame(bk_rows).to_csv(outdir / "baskets.csv", index=False)
    rows = pd.DataFrame(out["rows"])
    rows.to_csv(outdir / "stats.csv", index=False)
    tcols = ["book", "cost_bps", "run", "date", "idx", "kind", "e_after", "basket_eff", "V", "traded", "cost", "nav_close_after", "gw_after"]
    tdf = pd.DataFrame([{k: t[k] for k in tcols if k in t} for t in out["trades"]]).reindex(columns=tcols)
    tdf.loc[tdf["run"] == "hold_parent", "gw_after"] = np.nan
    tdf.to_csv(outdir / "trades.csv", index=False)
    pd.DataFrame(out["sleeve_trades"]).to_csv(outdir / "sleeve_trades.csv", index=False)
    pd.DataFrame(out["positions"]).to_csv(outdir / "positions.csv", index=False)
    pd.DataFrame(out["r7_flagged"], columns=["book", "date", "stock", "prev_close", "close", "ret", "w_prev", "w_cur", "src"]).to_csv(outdir / "r7_flagged_days.csv", index=False)
    pd.DataFrame(out["r7_export"], columns=["book", "stock", "held_sessions_export", "end_nav_hold_parent", "end_nav_hold_parent_noexport"]).to_csv(outdir / "r7_export.csv", index=False)
    daily = []
    for (p, cost, name), nv in out["nav"].items():
        daily.append(pd.DataFrame({"book": p, "date": bks[p].cal, "cost_bps": cost, "run": name, "nav": nv}))
    pd.concat(daily).to_csv(outdir / "daily_nav.csv", index=False)
    pn = []
    for p in books:
        pn.append(pd.DataFrame({"book": p, "date": bks[p].cal, "hold_parent_0bps": out["nav"][(p, 0.0, "hold_parent")], "hold_parent_20.8bps": out["nav"][(p, PRIMARY, "hold_parent")],
                                "part_a_20.8bps": out["nav"][(p, PRIMARY, "strategy_fixed50")], "part_b_20.8bps": out["nav"][(p, PRIMARY, "strategy")]}))
    pd.concat(pn).to_csv(outdir / "parent_nav_2014-09-01_2019-01-02.csv", index=False)
    (outdir / "parent_nav_2014-09-01_2019-01-02.md").write_text(
        "# Rebuilt parent NAV, 2014-09-01 to 2019-01-02\n\nrebuilt from the parent's baskets and Eikon prices, not validated against a published NAV before 2019-01-02.\n\n"
        "Columns: `hold_parent_0bps`, `hold_parent_20.8bps` (always IN), `part_a_20.8bps` (the rule with the fixed 50/50 sleeve), `part_b_20.8bps` (the rule with the MAUc1-timed sleeve); "
        "base 1.0 at 2014-09-01's close. The file is not entered in data/APPROVED_DATA.md and no other test may read it; if Manu asks for it as data it is registered PENDING and goes through the "
        "review and approval procedure.\n", encoding="utf-8")
    np.savez_compressed(outdir / "draw_curves_20.8.npz", **{f"{p}|{k}": v for p, d in curves.items() for k, v in d.items()})
    np.savez_compressed(outdir / "draw_states.npz", **states_all)
    np.savez_compressed(outdir / "real_states.npz", **real_states)

    # audit
    for rel, r_ in USED.items():
        if r_["id"] in ("D26", "D03", "D09", "D11", "D24b", "D18") and r_["through"][:1].isdigit():
            assert r_["through"] >= str(END.date()), f"{rel}: approved through {r_['through']}, before the window's end {END.date()}: stop and ask Manu"
        if r_["id"] == "D17":
            assert r_["through"] >= str(END_D17.date()), f"{rel}: approved through {r_['through']}, before {END_D17.date()}"
    write_inputs()
    v3_ok = all(v["pass"] for v in v3_res.values())
    v2_viol = sum(b["v2_label_after_decision"] + b["v2_mauc1_label_after_decision"] + b["v2_trade_not_after_decision"] for b in audit["books"].values())
    v2_cnt = sum(b["v2_decisions_checked"] * 2 + b["v2_trades_checked"] + 2 for b in audit["books"].values()) + out["v2_trades"] + out["v2_basket_trades"]
    v2_ok = bool(v2_viol == 0 and v2_cnt > 0)
    audit["v2"] = {"checks": int(v2_cnt), "violations": int(v2_viol), "recorded_trades_after_their_decision": int(out["v2_trades"]), "recorded_basket_changes_on_or_after_availableDate": int(out["v2_basket_trades"]),
                   "sc100_rule7_checks": len(audit["books"]), "sc100_signal_rows_read_from": str(c0["master"]["SC100"].index.min().date()), "pass": v2_ok}
    audit["v3"] = {"per_book_window": v3_res, "pass": bool(v3_ok), "rule_in_support": {k: v["rule_in_support"] for k, v in v3_res.items()}, "draws_per_type": int(n_draws),
                   "reportability": {"r3_window": r3_gate, "gold_spells_with_an_out_week_full": {p: audit["books"][p]["gold"]["spells_with_an_out_week"] for p in books}}}
    audit["v4"] = {"pass": reg["pass"]}
    audit["v5"] = {"pass": v5["pass"]}
    audit["v6"] = v6
    lbr, lqr = c0["lbes"].pct_change(), c0["liq"].pct_change()
    jj = pd.concat([lbr, lqr], axis=1, keys=["lb", "lq"]).dropna().loc[str(T0.date()):str(END.date())]
    nb_strat = [{"book": t["book"], "date": str(t["date"]), "kind": t["kind"], "run": t["run"], "cost_bps": t["cost_bps"], "stock_lines_with_stand_in": t["nobar_stocks"],
                 "gold_raw_fill": t["gold_norange"], "gold_previous_close": t["gold_nobar"]}
                for t in out["trades"] if (t["nobar_stocks"] or t["gold_norange"] or t["gold_nobar"]) and t["cost_bps"] == PRIMARY]
    audit["data"] = {"approved_data_as_of": AD.as_of(), "window": [str(T0.date()), str(END.date())], "inputs": int(len(USED)), "non_approved_open_and_guards": selftest,
                     "master_rows_after_END_dropped": c0["master_rows_after_end"], "mauc1": {"rows_after_END_dropped": int(c0["gold_master_rows_after_end"])},
                     "goldbees": {"goldbees_first_bar": str(c0["gold_first"].date()), "goldbees_file_last": str(c0["gold_last"].date()), "mcx_file_last": str(c0["mcx_last"].date()),
                                  "sessions_without_mcx_range_(raw OHLC4 fill)_in_window": audit["books"][books[0]]["gold_sessions_without_mcx_range_in_window"],
                                  "sessions_without_own_gold_bar_(previous close used)": audit["books"][books[0]]["gold_sessions_without_own_bar"]},
                     "cash": {"lbes_last": str(c0["lbes_last"].date()), "liq_last": str(c0["liq_last"].date()), "accrued_sessions": 0,
                              "lbes_vs_liquidcase_max_abs_daily_return_diff_in_window": float((jj["lb"] - jj["lq"]).abs().max()), "rows_compared": int(len(jj))},
                     "trades_on_stand_in_sessions_20.8bps_all_runs": nb_strat, "r7": out["r7_summary"]}
    audit["frozen_text_counts"] = {"pass": frozen_ok, "detail": frozen_detail}
    audit["sleeve_trades_per_book_real_rule"] = {p: audit["books"][p]["gold"]["sleeve_trades_expected"] for p in books}
    audit["step1_spell_counts_reproduced"] = {"pass": bool(s1_ok), "detail": step1_detail, "file": STEP1.relative_to(AA).as_posix()}
    audit["run"] = {"name": a.run, "command": " ".join(sys.argv), "draws": n_draws, "books": list(books), "seconds": round(time.time() - t_start), "quick": a.quick,
                    "python": sys.version.split()[0], "numpy": np.__version__, "pandas": pd.__version__,
                    "seeds": "in-or-out N4.9 default_rng([14, 3, id]), N4.10 [14, 6, id]; gold N4.9-g [14, 11, 3, id], N4.10-g [14, 11, 6, id]; the same draw ids for every cost, window, cash variant and book; F5 pairs F1's and F3's draw of the same id"}
    audit["prereg_sha256"] = (T11 / "T11.md").read_text(encoding="utf-8").split("§1–§3 sha256:** `")[1].split("`")[0]
    ok = bool(v2_ok and v3_ok and reg["pass"] and v5["pass"] and v6["pass"] and selftest["pass"] and s1_ok and frozen_ok)
    audit["gates"] = {"V2": v2_ok, "V3": bool(v3_ok), "V4": reg["pass"], "V5": v5["pass"], "V6": v6["pass"], "approved_data_selftest": selftest["pass"], "step1_counts": bool(s1_ok),
                      "frozen_text_counts": frozen_ok, "all": ok}
    (outdir / "audit.json").write_text(json.dumps(audit, indent=1, default=str), encoding="utf-8")

    print("stats rows written:", len(rows), "; draw rows:", out["draw_rows_written"], "; trades:", {f'{a_}|{b_}': c for (a_, b_), c in sorted(Counter((t['run'], t['kind']) for t in out['trades'] if t['cost_bps'] == PRIMARY and t['book'] == books[0] and t['run'] in ('strategy', 'strategy_fixed50', 'hold_parent')).items())})
    print("V2", audit["v2"])
    print("V3", {k: v["pass"] for k, v in v3_res.items()})
    print("V4", {"a_t08": d17["t08"]["worst_rel_diff_by_run"], "a_t06": d17["t06"]["worst_rel_diff_by_run"], "b": {k: (v["stocks_checked"], v["max_rel_diff"]) for k, v in reg["b_one_instrument"].items()},
                 "c": reg["c_shared_code"]["pass"], "d": {k: v["pass"] for k, v in reg["d_signals"].items()}, "e": {k: v["pass"] for k, v in reg["e_d24b_vs_d24"].items()},
                 "f_pp": {k: round(v["year_gap_pp"], 4) for k, v in reg["f_seam"].items()}, "pass": reg["pass"]})
    print("V5", {"small_p": small["p"], "small_p14": small14["p"], "ie_equal": v5b, "mean_check": all(v["pass"] for v in v5c.values()), "pass": v5["pass"]})
    print("V6", {"trades": v6["trades_checked"], "worst": v6["worst"], "pass": v6["pass"]})
    print("frozen counts", {p: v["pass"] for p, v in frozen_detail.items()}, "step1", step1_detail)
    for k, v in ct.items():
        if v["window"] == "full" and k.startswith(books[0]):
            print(f"  n_ways {k}: {v['n_ways']}")
    print(f"gates: {audit['gates']}")
    print(f"done in {time.time() - t_start:.0f}s -> {outdir}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
