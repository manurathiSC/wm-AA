# -*- coding: utf-8 -*-
"""T14 engine: the three-index switch with a different holding in the OUT-SELL regime (switch OUT and MAUc1 SELL), six rules, two windows, against one null per timing.

A FORK of analysis/t11_engine.py (copied, not imported; the functions that are unchanged are copied verbatim and checked by `shared_code_diff`), with the W2 paths of
analysis/t08_engine.py (D17-extended calendar, D24 signal, D12 de-spike range, T08's seeds and R2/R3 conventions). Pre-registration: tests/T14/T14.md sections 1-3 (frozen;
`python tests/T14/check_prereg.py`); plan: tests/T14/PLAN.md; evidence contract: tests/T14/logs/evidence_contract.md.

    python analysis/t14_engine.py [--run NAME] [--window w1|w2|both] [--draws N] [--quick] [--books SCMO_0003 ...] [--workers N] [--outdir DIR]     (from AA/)

Six rules (T14.md 2.1): 50-orig, 50-half, 50-liq, 80-orig, 80-half, 80-liq. A target is (e, gw): e = parent share, gw = GOLDBEES share of the non-parent part. Regime at each
weekly decision: IN (all three index SIGN BUY), OUT-BUY (not IN, MAUc1 BUY), OUT-SELL (not IN, MAUc1 SELL). The `-orig` rules are T06/T11 Part A (50/50) and T08/T11 Part B
(80/20, 20/80 while gold SELL); `-half` holds e = 0.5, gw = 1.0 in OUT-SELL (D1: a parent rebalance inside the regime re-weights only the parent half at its current value,
GOLDBEES and cash units untouched, cost on the stock trades taken from the stock part); `-liq` holds e = 0, gw = 0 (100% cash leg).

Null families per window (2,000 draws per book; T11's seeds in W1 and T08's in W2, so the draw states equal their stored draw_states.npz: D2). Every draw runs all six rules:
    F1 in-or-out N4.10 + real gold   F2 in-or-out N4.9 + real gold   F3 real in-or-out + gold N4.10-g   F4 real in-or-out + gold N4.9-g   F5 F1's + F3's draw of the same id.
The trade rule is T08's `trade` unchanged: a trade is due on the session after decision j iff e changed or (e < 1 and gw changed); a basket change while e = 1 is T08's full
reset; while 0 < e < 1 it is the D1 partial trade (`trade_basket_partial`).

Writes <outdir>/<window>/ (see tests/T14/logs/evidence_contract.md). The engine prints gates and counts only, no performance figure.
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
from concurrent.futures import ProcessPoolExecutor
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
D24_DIR = HD / "extended_2026-11-06" / "MAUc1"
D12_FILE = AA / "analysis" / "evidence" / "final_strategy" / "mauc1" / "mauc1_daily_clean.csv"
MASTER_DIR = HD / "extended_2026-10-30" / "Master"
D17_DIR = HD / "extended_2026-11-06" / "published_nav"
GOLD_D09 = AA / "analysis" / "cache" / "why_gold_ohlc_eikon_extended_2026-11-04.parquet"
CAL_FILE = IDX_DIR / "nse_trading_days.csv"
T14 = AA / "tests" / "T14"
T06E = AA / "tests" / "T06" / "evidence" / "headline"      # read-only test evidence, V4(a) only
T08E = AA / "tests" / "T08" / "evidence" / "headline"
T11E = AA / "tests" / "T11" / "evidence" / "headline"
T11_ENGINE = Path(__file__).with_name("t11_engine.py")      # source text read by the V4(d) AST comparison only
T08_ENGINE = Path(__file__).with_name("t08_engine.py")
STEP1 = T14 / "logs" / "step_1_spell_counts.json"

PARENTS = ["SCMO_0003", "SCMO_0007", "SCMO_0010", "SCMO_0029"]
INDICES = ("Nifty100", "MC100", "SC100")
RULES = ["50-orig", "50-half", "50-liq", "80-orig", "80-half", "80-liq"]
NEW_RULES = [r for r in RULES if not r.endswith("orig")]
ORIG_OF = {"50-half": "50-orig", "50-liq": "50-orig", "80-half": "80-orig", "80-liq": "80-orig"}
FIRST_PRICE_DAY = pd.Timestamp("2014-07-01")
SC_USABLE_FROM = pd.Timestamp("2011-11-25")
COSTS = (0.0, 20.8, 50.0)
PRIMARY = 20.8
N_DRAWS = 2000
LO_CAP = 2
DESPIKE_TOL = 0.005
REL_TOL_NAV = 1e-12
G0_OVERALL, G0_YEARLY = 0.25, 0.5                      # pp / yr (T08 E15)
GW_BUY, GW_SELL, GW_FIX = 0.8, 0.2, 0.5
SEED_IO_49, SEED_IO_410 = (14, 3), (14, 6)             # W1 (T11's); W2's are in WINDOWS
SEED_G_49, SEED_G_410 = (14, 11, 3), (14, 11, 6)
R7_THRESHOLD = 0.20
CURVE_SEED = (17, 1)                                   # prefix 17: which 20 random draw ids get their NAV stored (the first 20 are always stored)
REG_NAMES = ("IN", "OUT-BUY", "OUT-SELL")
FROZEN_EXPORT = {"SCMO_0003": {"DISH": 164, "GEOM": 42, "MOL": 246, "OSCM": 122}, "SCMO_0007": {"HEXT": 62, "LAKSHVILAS": 61},
                 "SCMO_0010": {"DISH": 62, "GEOM": 42, "JMCPROJECT": 62, "LAKSHVILAS": 62, "MOL": 102, "OSCM": 60, "PEL": 42, "PIRAMALFIN": 124},
                 "SCMO_0029": {"GEOM": 122}}
FROZEN_EXPORT_TOTAL = {"SCMO_0003": 574, "SCMO_0007": 123, "SCMO_0010": 556, "SCMO_0029": 122}
FROZEN_CARRIED = {"SCMO_0003": 0, "SCMO_0007": 0, "SCMO_0010": 3, "SCMO_0029": 0}
NO_D18_SESSION = pd.Timestamp("2017-10-19")
NO_GOLD_SESSION = pd.Timestamp("2016-10-30")
IO_BOUNDS_W2 = {1: (2, 46), 0: (2, 40)}                # T08.md section 3 step 11, asserted
GOLD_BOUNDS_W2 = {1: (2, 68), 0: (2, 28)}              # BUY, SELL (T08.md section 2), asserted

WINDOWS = {
    "w1": dict(name="w1", cal="d26", t0=pd.Timestamp("2014-09-01"), end=pd.Timestamp("2019-01-02"), r3_start=pd.Timestamp("2015-01-02"), r3_key="r3", r3_bounds="own",
               gold_master=D24B_DIR / "Master_MAUc1.xlsx", gold_weekly=D24B_DIR / "mauc1_supertrend_weekly_extended.csv", mcx=D24B_DIR / "mauc1_daily_clean_extended.csv",
               seeds=dict(io49=SEED_IO_49, io410=SEED_IO_410, g49=SEED_G_49, g410=SEED_G_410), liq_from=None, ref="T11", ref_dir=T11E, stored_r3_key="r3"),
    "w2": dict(name="w2", cal="d17", t0=None, end=None, r3_start=pd.Timestamp("2021-11-01"), r3_key="r3", r3_bounds="full",
               gold_master=D24_DIR / "Master_MAUc1.xlsx", gold_weekly=D24_DIR / "mauc1_supertrend_weekly_extended.csv", mcx=D12_FILE,
               seeds=dict(io49=(3,), io410=(6,), g49=(11, 3), g410=(11, 6)), liq_from=pd.Timestamp("2024-01-24"), ref="T08", ref_dir=T08E, stored_r3_key="live"),
}

READINGS = {
    "E1": "calendar: W1 = D26's dates 2014-09-01 -> 2019-01-02 (1,070 sessions); W2 = each book's D17 dates of the EXTENDED published NAV from its first date (SCMO_0007: 2019-01-04) to END = the last row of the three "
          "D03 Master files (2026-10-30); rows after END are never used. As T11 E1 / T08 E1",
    "E2": "decision dates = T0 and the last session of every later ISO week; the decision at the last session is made and not traded (T08 E2, T11 E2)",
    "E3": "label = latest Master row dated <= decision date, per index and for MAUc1 (W1: D24b, W2: D24); regime IN / OUT-BUY / OUT-SELL from the three SIGNs and g; the Smallcap 100 rows are sliced to >= 2011-11-25",
    "E4": "targets (e, gw) per rule from T14.md 2.1; gw while IN is carried in the log and never traded on (the trigger needs e < 1); one function `rule_arrays` serves the real series and every draw",
    "E5": "initial position at T0's close, no cost, in every realisation: the target of the decision at T0 (IN: the basket in force, drifted from its availableDate, scaled to NAV 1; OUT: gw GOLDBEES, rest cash; "
          "e = 0.5: half the drifted basket and half GOLDBEES), T08/T11's convention",
    "E6": "stock fill = OHLC4 of the Eikon bar (close if open/high/low is blank; the last close if no bar); GOLDBEES fill = T03's de-spike with the MCX range of the window's file (W1: D24b daily, W2: D12), raw OHLC4 "
          "where the range is missing (W2: every session after D12's last date), as T11 E8 / T08 E16",
    "E7": "costs: T08's `trade` unchanged (cost = ow x value traded at the pre-cost targets, then every target scaled by (V-cost)/V)",
    "E8": "a basket takes effect on the first session on or after its availableDate; skipped baskets dropped; weights renormalised. While e = 1 a basket change is T08's full reset trade (kind basket_change); while "
          "0 < e < 1 (the -half regime) it is the D1 partial trade (kind basket_change, GOLDBEES and cash units unchanged, cost on the stock lines taken from the stock part); while e = 0 nothing is traded",
    "E9": "trade kinds: switch_in / switch_out (e crosses 0 or 1 between IN and OUT-BUY; for -orig rules also IN <-> OUT-SELL), sleeve_rebalance (e = 0 on both sides, gw changed), and for the -half / -liq rules regime_in "
          "(into OUT-SELL) and regime_out (out of OUT-SELL); basket_change",
    "E10": "cash level: the extended LBES (D11) as-of on sessions; R2 'liq': W1 liquidEtfFinal (LIQUIDCASE) over the whole window, W2 LBES to the session before 2024-01-24 then LIQUIDCASE returns (T08 E14); no accrual",
    "E11": "constant mix at each rule's own averages: f = mean of e over the decisions, gw_bar = sum((1-e)gw)/sum(1-e); rebalanced at every decision date's next session and at every basket change while f > 0 "
           "(T11 E10 generalised); initial stock holding = drifted basket scaled by f",
    "E12": "R3: W1 starts at the first D26 session on or after 2015-01-02 with its own spells, totals and bounds (T11 E11); W2 'live' starts at the first D17 session on or after 2021-11-01 with its own spells and totals "
           "but the book's FULL-window bounds (T08 E13); same seeds, free initial position in the state decided then",
    "E13": "R7 (W1 only): T11 E12 unchanged: |close return| >= 20% stock-days on held stocks and the manual-export stock-days set to zero return by a return-preserving splice; the six rules at 0 and 20.8 bps",
    "E14": "bounds of every series: lo = min(2, shortest spell of the state), hi = longest spell of the state, computed in the run; W2 asserted equal to T08's (in-or-out [2,46] in / [2,40] out, gold BUY [2,68] / SELL [2,28])",
    "E15": "the four books have identical decision and gold series and share the draws; the draw states of each window are regenerated from the seeds and asserted equal to the stored draw_states.npz of T11 (W1) and "
           "T08 (W2) (V3, decision D2)",
    "E16": "sessions_invested = daily returns earned while the parent is held; rules with e = 0.5 count as 'invested' only in the draws' IN weeks (the statistic is a property of the in-or-out series, as T11 E16)",
    "E17": "trades_due of a draw = decisions j >= 1 with a session after them and e[j] != e[j-1] or (e[j] < 1 and gw[j] != gw[j-1]) (draws.csv `trades_due`; the recorded trades of the real rules are checked against it, V6)",
    "E18": "V4(a): -orig rules reproduce the stored daily_nav.csv (relative 1e-12): W2 80-orig <- T08 strategy, 50-orig <- T08 strategy_fixed50 and T06 strategy (to 2026-10-22), hold_parent; W1 80-orig <- T11 strategy, "
           "50-orig <- T11 strategy_fixed50, hold_parent; and the -orig rows of draws.csv equal the stored draws.csv (cagr, max_dd, end_nav; W2 R3 'live' <-> 'r3')",
    "E19": "V4(f) seam / G0: the always-in 0-cost NAV on D17's dates against the published NAV, W2 from T0 (limits: +-0.25 pp/yr overall, +-0.5 pp each calendar year, T08 G0) and, for W1, over 2019-01-02 -> 2019-12-31 "
           "(+-0.5 pp, T11 V4(f)) from the W2 book's hold-parent path",
    "E20": "draw_curves: the NAV of the first 20 draws and of 20 further draw ids (default_rng([17, 1]).choice(2000, 20), disclosed) of F1 and F3 at 20.8 bps for the six rules; the full NAV of every draw is not stored",
    "E21": "regime ledger: OUT-SELL spell = maximal run of OUT-SELL decisions; returns from the close of the first spell decision's session to the close of the session of the decision that ends the spell "
           "(or the last session): parent = hold_parent 0-cost NAV, GOLDBEES = D09 close, cash = LBES level, each rule = its 20.8 bps NAV",
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


_END_W2 = None


def end_of(win: str) -> pd.Timestamp:
    """W1's END is fixed; W2's is the last row of the three D03 Master files (all three must agree), as T08."""
    global _END_W2
    if win == "w1":
        return WINDOWS["w1"]["end"]
    if _END_W2 is None:
        ends = {}
        for n in INDICES:
            d = pd.read_excel(ap(MASTER_DIR / f"Master_{n}.xlsx"), parse_dates=["Date"])
            ends[n] = d.dropna(subset=["SIGN"])["Date"].max()
        assert len(set(ends.values())) == 1, f"the three D03 Master files end on different dates: {ends}"
        _END_W2 = next(iter(ends.values()))
    return _END_W2


# ── regimes and targets (T14.md 2.1) ─────────────────────────────────────────
def targets(rule: str, st: int, g: int) -> tuple[float, float]:
    """(e, gw) for one decision. st = 1 IN, g = 1 gold BUY. gw while IN is carried and never traded on."""
    base, kind = rule.split("-")
    gw_out = 0.5 if base == "50" else (GW_BUY if g else GW_SELL)
    if st == 1:
        return 1.0, gw_out
    if g == 0 and kind == "half":
        return 0.5, 1.0
    if g == 0 and kind == "liq":
        return 0.0, 0.0
    return 0.0, gw_out


def regime_codes(s, g) -> np.ndarray:
    """0 IN, 1 OUT-BUY, 2 OUT-SELL."""
    s, g = np.asarray(s).astype(int), np.asarray(g).astype(int)
    return np.where(s == 1, 0, np.where(g == 1, 1, 2))


def trades_due(idx, T: int, e, gw) -> list[int]:
    """Decisions j >= 1 with a trade session inside the window and e changed or (e < 1 and gw changed)."""
    return [j for j in range(1, len(idx)) if int(idx[j]) + 1 < T and (e[j] != e[j - 1] or (e[j] < 1 and gw[j] != gw[j - 1]))]


def out_sell_spells(reg) -> list[tuple[int, int]]:
    """[(first decision j, last decision j)] of every maximal OUT-SELL run."""
    out, j, n = [], 0, len(reg)
    while j < n:
        if reg[j] == 2:
            k = j
            while k + 1 < n and reg[k + 1] == 2:
                k += 1
            out.append((j, k))
            j = k + 1
        else:
            j += 1
    return out


# ── approved raw inputs ───────────────────────────────────────────────────────
_COMMON: dict = {}


def common(win: str) -> dict:
    """Calendar (W1: D26), the three D03 Master files, the window's MAUc1 Master / weekly csv / daily range, GOLDBEES (D09) with the de-spike, cash (D11); everything cut at the window's END."""
    if win in _COMMON:
        return _COMMON[win]
    W = WINDOWS[win]
    key = end_of(win)
    cal_all = None
    if W["cal"] == "d26":
        cal_all = pd.DatetimeIndex(sorted(pd.to_datetime(pd.read_csv(ap(CAL_FILE))["date"])))
        assert cal_all.is_unique and cal_all.max() >= key, f"D26 ends {cal_all.max().date()} before {key.date()}"
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
    gd = pd.read_excel(ap(W["gold_master"]), parse_dates=["Date"])
    gs = gd.dropna(subset=["SIGN"]).set_index("Date")["SIGN"].sort_index()
    gs = gs[~gs.index.duplicated(keep="last")]
    assert gs.index.max() >= key and set(gs.unique()) <= {"BUY", "SELL"}
    gm_after = int((gs.index > key).sum())
    gs = gs[gs.index <= key]
    wk = pd.read_csv(ap(W["gold_weekly"]), parse_dates=["review"])
    wk = wk[wk["review"] <= key].sort_values("review").reset_index(drop=True)
    m = pd.read_csv(ap(W["mcx"]), index_col=0, parse_dates=True)
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
    _COMMON[win] = dict(cal_all=cal_all, master=ms, master_rows_after_end=rows_after, gold_master=gs, gold_master_rows_after_end=gm_after, gold_weekly=wk, mcx_daily=m,
                        gclose=g["close"][g.index <= key], gfill=gfill[gfill.index <= key], norange=norange[norange <= key], lbes=lb[lb.index <= key], liq=lq[lq.index <= key],
                        lbes_last=lb.index.max(), liq_last=lq.index.max(), gold_last=g.index.max(), mcx_last=m.index.max(), gold_first=g.index.min(), end=key)
    return _COMMON[win]


def read_pub(p: str, end: pd.Timestamp) -> pd.Series:
    """D17 (extended published NAV: columns _id.scid, _id.date, index; any row order), cut at `end`. W2's calendar and the G0 / seam gates."""
    n = pd.read_csv(ap(D17_DIR / f"{p}.csv"))
    assert (n["_id.scid"] == p).all()
    pub = pd.Series(n["index"].values, index=pd.to_datetime(n["_id.date"], format="%Y/%m/%d")).sort_index()
    assert not pub.index.duplicated().any() and pub.index.max() >= end
    return pub[pub.index <= end]


_RAW: dict = {}


def raw_parent(p: str, end: pd.Timestamp) -> dict:
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


def cash_levels(cal: pd.DatetimeIndex, kind: str, win: str) -> tuple[np.ndarray, dict]:
    """E10. Level on every session of cal (as-of); nothing is accrued past a file's end. 'liq': W1 LIQUIDCASE over the whole window; W2 LBES chained with LIQUIDCASE returns from LIQ_FROM (T08 E14)."""
    c = common(win)
    liq_from = WINDOWS[win]["liq_from"]
    lb = c["lbes"]
    assert not (cal > c["lbes_last"]).any(), f"cash file ends {c['lbes_last'].date()} before the window's last session: stop and ask Manu"
    lv = lb.reindex(lb.index.union(cal)).ffill().reindex(cal)
    info = {"file_last": str(c["lbes_last"].date()), "accrued_sessions": 0, "cash": kind}
    if kind == "liq":
        q = c["liq"]
        assert not (cal > c["liq_last"]).any(), "LIQUIDCASE file ends before the window"
        qs = q.reindex(q.index.union(cal)).ffill().reindex(cal)
        if liq_from is None:
            lv = qs
        else:
            pre = cal[cal < liq_from]
            if len(pre) and len(pre) < len(cal):
                base = lv.loc[pre[-1]]
                out = lv.copy()
                for d in cal[cal >= liq_from]:
                    out.loc[d] = base * qs.loc[d] / qs.loc[pre[-1]]
                lv = out
        info["cash"] = "liq" + ("" if liq_from is None else f" from {liq_from.date()}")
    assert lv.notna().all()
    return lv.values.astype(float), info


class Book:
    """Everything a run needs for one parent and one window, as plain arrays on the calendar (T11's Book, window-aware)."""

    def __init__(self, parent: str, win: str, start: pd.Timestamp | None = None, cash: str = "lbes"):
        W = WINDOWS[win]
        end = end_of(win)
        r = raw_parent(parent, end)
        c = common(win)
        self.win = win
        self.pub_full = None
        if W["cal"] == "d26":
            cal_all = c["cal_all"]
            t0 = W["t0"] if start is None else cal_all[cal_all.searchsorted(start)]
            assert t0 in cal_all
        else:
            self.pub_full = read_pub(parent, end)
            cal_all = self.pub_full.index
            t0 = cal_all[0] if start is None else cal_all[cal_all.searchsorted(start)]
        cal = cal_all[(cal_all >= t0) & (cal_all <= end)]
        assert cal[0] == t0 and cal[-1] == end, (cal[0], cal[-1], end)
        self.parent, self.cal, self.T, self.t0, self.end = parent, cal, len(cal), t0, pd.Timestamp(end)
        self.stocks, self.N = r["stocks"], len(r["stocks"])
        union = cal.union(r["close_raw"].index)
        Cf = r["close_raw"].reindex(union).ffill().reindex(cal)       # the last close stands in on a session without a bar
        P = r["o4"].reindex(cal)
        self.nobar = P.isna().values
        self.nobar_trades = 0
        self.gold_norange_trades = 0
        self.gold_nobar_trades = 0
        P = P.fillna(Cf)
        self.C = np.nan_to_num(Cf.values.astype(float), nan=0.0)
        self.P = np.nan_to_num(P.values.astype(float), nan=0.0)
        self.src = r["src"].reindex(index=cal, columns=self.stocks).values
        self.pub = self.pub_full.reindex(cal).values.astype(float) if self.pub_full is not None else None
        gunion = cal.union(c["gclose"].index)
        gc = c["gclose"].reindex(gunion).ffill().reindex(cal)
        assert gc.notna().all()
        gf = c["gfill"].reindex(cal).fillna(gc)
        self.g, self.gf = gc.values.astype(float), gf.values.astype(float)
        own = cal.isin(c["gclose"].index)
        self.gold_no_own_bar = [str(d.date()) for d in cal[~own]]
        self.gold_nobar = ~np.asarray(own)
        self.gold_norange = np.asarray(cal.isin(c["norange"]))
        self.L, self.cash_info = cash_levels(cal, cash, win)
        Wm = r["W"]
        self.W = Wm.values.astype(float)
        self.eff = Wm.index
        bidx = np.searchsorted(cal.values, self.eff.values)          # first session on or after availableDate
        self.bidx = bidx
        self.b0 = int(np.flatnonzero(bidx <= 0)[-1])                 # basket in force at T0
        self.basket_events = {int(i) for i in bidx if 0 < i < self.T}
        self.basket_at = np.array([int(np.flatnonzero(bidx <= t)[-1]) if (bidx <= t).any() else 0 for t in range(self.T)])
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

    def decisions(self) -> pd.DataFrame:
        cal = self.cal
        iso = cal.isocalendar()
        last = pd.Series(np.arange(self.T), index=cal).groupby([iso.year.values, iso.week.values]).max().values
        idx = np.array([0] + [int(i) for i in sorted(last) if i > 0])
        cm = common(self.win)
        ms, gm = cm["master"], cm["gold_master"]
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
            kg = gm.index.searchsorted(d, side="right") - 1          # latest MAUc1 row dated <= the decision date
            assert kg >= 0
            lab_g, sign_g = gm.index[kg], gm.iloc[kg]
            gg = int(sign_g == "BUY")
            row = {"book": self.parent, "window": self.win, "j": j, "decision_date": d.date(), "decision_idx": int(i),
                   "trade_date": (cal[i + 1].date() if i + 1 < self.T else None),
                   **{f"sign_{n}": v[1] for n, v in lab.items()}, **{f"label_{n}": v[0].date() for n, v in lab.items()},
                   "latest_label": ld.date(), "label_age_days": (d - min(v[0] for v in lab.values())).days,
                   "all_three_buy": bool(state), "state": int(state),
                   "sign_MAUc1": sign_g, "label_MAUc1": lab_g.date(), "g": gg, "regime": REG_NAMES[int(regime_codes([state], [gg])[0])]}
            for rule in RULES:
                e_, gw_ = targets(rule, state, gg)
                row[f"e_{rule}"], row[f"gw_{rule}"] = e_, gw_
            rows.append(row)
        return pd.DataFrame(rows)



# ── simulation, spells and nulls: copied verbatim from t11_engine.py (checked by shared_code_diff) ──
_TABLES: dict = {}


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


def flush_draws(out: dict, path: Path, first: bool):
    if out["draw_rows"]:
        pd.DataFrame(out["draw_rows"]).to_csv(path, mode="w" if first else "a", header=first, index=False)
        out["draw_rows_written"] += len(out["draw_rows"])
    out["draw_rows"] = []


def trade_basket_partial(bk: Book, t: int, u, gu, cu, ow: float):
    """D1 (T14.md 3 step 6): a parent rebalance while 0 < e < 1 (the -half regime). Only the stock part is re-weighted to the new basket at its current value S; GOLDBEES and cash units
    are unchanged; cost = ow x sum|S w_i - held_i| on the stock lines, taken from the stock part: units_i = (S - cost) w_i / p_i."""
    ps, gp, lv = bk.P[t], bk.gf[t], bk.L[t]
    held_s = u * ps
    S = float(held_s.sum())
    V = S + gu * gp + cu * lv
    w = bk.W[bk.basket_at[t]]
    Te = S * w
    nb = int((bk.nobar[t] & ((Te > 0) | (held_s > 0))).sum())
    bk.nobar_trades += nb
    traded = float(np.abs(Te - held_s).sum())
    cost = ow * traded
    k = (S - cost) / S
    new_u = np.zeros_like(u)
    pos = (Te > 0) & (ps > 0)
    assert not ((Te > 0) & (ps <= 0)).any(), f"no price for a stock to buy at session {bk.cal[t].date()}"
    new_u[pos] = k * Te[pos] / ps[pos]
    va = new_u * ps
    stock_after = float(va.sum())
    return new_u, gu, cu, dict(V=V, traded=traded, cost=cost, stock_before=S, gold_before=float(gu * gp), cash_before=float(cu * lv),
                               stock_after=stock_after, gold_after=float(gu * gp), cash_after=float(cu * lv), V_after=stock_after + float(gu * gp) + float(cu * lv),
                               weight_gap=float(np.abs(va / stock_after - w).max()) if stock_after > 0 else 0.0, held_before=held_s, val_after=va,
                               nobar_stocks=nb, gold_norange=False, gold_nobar=False)


def simulate(bk: Book, dec_idx: np.ndarray, e: np.ndarray, cost_bps: float, every: bool = False, record: bool = False, gw: np.ndarray | None = None, reg: np.ndarray | None = None):
    """e[j] = parent share decided at decision j; gw[j] = gold weight of the non-parent share decided at j (None = 0.5 always: T06's sleeve).
    A trade is due on the session after decision j iff e changed or (e < 1 and gw changed) [or `every`]. reg (per decision: 0 IN, 1 OUT-BUY, 2 OUT-SELL) is passed for the -half / -liq rules only:
    it labels regime_in / regime_out trades and switches on the D1 partial trade for a parent rebalance while 0 < e < 1. Returns daily NAV (length T) and, if record, the trade and position logs."""
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
            partial = bool(t not in tgt and reg is not None and 0 < e_cur < 1)
            e_new, gw_new, jd = tgt[t] if t in tgt else (e_cur, gw_cur, None)
            if partial:
                kind = "basket_change"
                u, gu, cu, info = trade_basket_partial(bk, t, u, gu, cu, ow)
            else:
                if t in tgt and reg is not None and (reg[jd] == 2) != (reg[jd - 1] == 2):
                    kind = "regime_in" if reg[jd] == 2 else "regime_out"
                else:
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


def make_states_io(s: np.ndarray, n: int, bounds: dict, seeds: dict) -> dict:
    """The weekly in-or-out states of every draw of F1/F2/F5: {type: uint8 (n, weeks)}."""
    return {"N4.9": np.array([spell_shuffle(s, d, seeds["io49"]) for d in range(n)], dtype=np.uint8),
            "N4.10": np.array([free_length_draw(s, d, bounds, seeds["io410"]) for d in range(n)], dtype=np.uint8)}


def make_states_gold(g: np.ndarray, n: int, bounds: dict, seeds: dict) -> dict:
    """The weekly gold states of every draw of F4/F3/F5 (the same samplers on the gold series, state 1 = BUY, gold seeds)."""
    return {"N4.9-g": np.array([spell_shuffle(g, d, seeds["g49"]) for d in range(n)], dtype=np.uint8),
            "N4.10-g": np.array([free_length_draw(g, d, bounds, seeds["g410"]) for d in range(n)], dtype=np.uint8)}


FAMILIES = {"F1": ("N4.10", "real"), "F2": ("N4.9", "real"), "F3": ("real", "N4.10-g"), "F4": ("real", "N4.9-g"), "F5": ("N4.10", "N4.10-g")}


def rule_arrays(rule: str, s, g) -> tuple[np.ndarray, np.ndarray]:
    """Vectorised `targets` (asserted equal to it in the self-test): (e, gw) per decision."""
    s, g = np.asarray(s).astype(int), np.asarray(g).astype(int)
    base, kind = rule.split("-")
    gw = np.full(len(s), 0.5) if base == "50" else np.where(g == 1, GW_BUY, GW_SELL).astype(float)
    e = np.where(s == 1, 1.0, 0.0)
    sell = (s == 0) & (g == 0)
    if kind == "half":
        e, gw = np.where(sell, 0.5, e), np.where(sell, 1.0, gw)
    elif kind == "liq":
        gw = np.where(sell, 0.0, gw)
    return e, gw


def reg_arg(rule: str, reg):
    return None if rule.endswith("orig") else reg


def e_held_before(idx, T: int, e, gw) -> tuple[np.ndarray, list[int]]:
    """Per session t, the parent share held when session t's trade is about to happen, and the sorted trade sessions due from the states."""
    due = trades_due(idx, T, e, gw)
    change = {int(idx[j]) + 1: float(e[j]) for j in due}
    cur, out = float(e[0]), np.zeros(T)
    for t in range(T):
        out[t] = cur
        if t in change:
            cur = change[t]
    return out, sorted(change)


# ── R7: flagged price days and the manual-export bars (W1) ───────────────────
def r7_runs(bk: Book, idx: np.ndarray, s: np.ndarray, g: np.ndarray, reg: np.ndarray, stat_row, out: dict):
    """R7 (full window, LBES): flagged stock-days and the manual-export stock-days with their return set to zero; the six rules and hold-the-parent at 0 and 20.8 bps."""
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
            for rule in RULES:
                e_, gw_ = rule_arrays(rule, s, g)
                nv = simulate(bkx, idx, e_, cost, gw=gw_, reg=reg_arg(rule, reg))
                out["rows"].append(stat_row(f"{rule}_{tag}", cost, nv, [], float(e_.sum())))
                out["nav"][(p, cost, f"{rule}_{tag}")] = nv
            nv = simulate(bkx, idx, np.ones(len(s)), cost)
            out["rows"].append(stat_row(f"hold_parent_{tag}", cost, nv, [], float(len(s))))
            out["nav"][(p, cost, f"hold_parent_{tag}")] = nv
    nav_real = simulate(bk, idx, np.ones(len(s)), 0.0)
    nav_x = simulate(variants[1][1], idx, np.ones(len(s)), 0.0)
    held = bk.W[bk.basket_at] > 0
    isexp = (bk.src == "export") & held
    per = {bk.stocks[i]: int(isexp[:, i].sum()) for i in range(bk.N) if isexp[:, i].any()}
    for st, n in per.items():
        out["r7_export"].append({"book": p, "stock": st, "held_sessions_export": n, "end_nav_hold_parent": float(nav_real[-1]), "end_nav_hold_parent_noexport": float(nav_x[-1])})
    out["r7_summary"][p] = {"flagged_stock_days": int(mask.sum()), "flagged_stocks": sorted({bk.stocks[i] for i in np.nonzero(mask)[1]}),
                            "held_export_stock_sessions": int(isexp.sum()), "export_stock_days_zeroed": int(exp_mask.sum()), "threshold": R7_THRESHOLD}


def regime_ledger(bk: Book, dec: pd.DataFrame, navs: dict, hold: np.ndarray, win: str) -> list[dict]:
    """E21: one row per OUT-SELL spell: dates, weeks, the parent / GOLDBEES / cash return over the spell's span and each rule's 20.8 bps return."""
    idx = dec["decision_idx"].values
    reg = regime_codes(dec["state"].values, dec["g"].values)
    rows = []
    for k, (j0, j1) in enumerate(out_sell_spells(reg)):
        a = int(idx[j0])
        b = int(idx[j1 + 1]) if j1 + 1 < len(idx) else bk.T - 1
        row = {"window": win, "book": bk.parent, "spell_no": k + 1, "first_decision": str(bk.cal[a].date()), "last_decision": str(bk.cal[int(idx[j1])].date()), "weeks": j1 - j0 + 1,
               "span_from_close": str(bk.cal[a].date()), "span_to_close": str(bk.cal[b].date()), "entered_from": REG_NAMES[reg[j0 - 1]] if j0 > 0 else "start",
               "exited_to": REG_NAMES[reg[j1 + 1]] if j1 + 1 < len(reg) else "window end",
               "parent_return": float(hold[b] / hold[a] - 1), "goldbees_return": float(bk.g[b] / bk.g[a] - 1), "cash_return": float(bk.L[b] / bk.L[a] - 1)}
        for rule in RULES:
            row[f"ret_{rule}"] = float(navs[rule][b] / navs[rule][a] - 1)
        rows.append(row)
    return rows


def run_book(bk: Book, dec: pd.DataFrame, sio: dict, sgo: dict, win: str, wname: str, cash: str, plan: dict, headline: bool, out: dict, curves: dict, curve_ids: set):
    """plan = {family: [costs]}. Real rules (all six) at every cost of `costs` (all three on the headline cell, else the primary only); comparators and R7 on the headline cell (R7: W1);
    every draw of every planned family, all six rules on each."""
    idx = dec["decision_idx"].values
    s = dec["state"].values.astype(int)
    g = dec["g"].values.astype(int)
    reg = regime_codes(s, g)
    ar = {r: rule_arrays(r, s, g) for r in RULES}
    sig_s, sig_g = spell_sig(s), spell_sig(g)
    dts = dec["decision_date"].astype(str).values
    costs = COSTS if headline else (PRIMARY,)

    def m_io(st):
        li, lo_ = lens_of(st.astype(int))
        return (len(li), len(lo_), spell_sig(st.astype(int)), sessions_invested(bk, idx, st), "|".join(map(str, li)), "|".join(map(str, lo_)))

    def m_g(st):
        bl, sl = lens_of(st.astype(int))
        return (int(st.sum()), len(bl), len(sl), spell_sig(st.astype(int)), "|".join(map(str, bl)), "|".join(map(str, sl)))

    need_io = {FAMILIES[fm][0] for fm in plan} - {"real"}
    need_g = {FAMILIES[fm][1] for fm in plan} - {"real"}
    mio = {"real": m_io(s)}
    mg = {"real": m_g(g)}
    for k in need_io:
        mio[k] = [m_io(x) for x in sio[k]]
    for k in need_g:
        mg[k] = [m_g(x) for x in sgo[k]]

    def stat_row(name, cost, nv, tr, inv):
        assert np.isfinite(nv).all() and (nv > 0).all(), f"{name}: a NAV is not finite and positive"
        return {"book": bk.parent, "window": wname, "cash": cash, "cost_bps": cost, "kind": name, **stats(nv), "invested_weeks": inv, "trades": len(tr),
                "cost_paid": sum(t["cost"] for t in tr), "sleeve_trades": sum(1 for t in tr if t["kind"] == "sleeve_rebalance"),
                "regime_trades": sum(1 for t in tr if t["kind"] in ("regime_in", "regime_out")), "basket_trades": sum(1 for t in tr if t["kind"] == "basket_change"),
                "switch_trades": sum(1 for t in tr if t["kind"] in ("switch_in", "switch_out"))}

    def keep(name, cost, tr, pos=None, nav=None):
        out["trades"] += [{"book": bk.parent, "window": wname, "cost_bps": cost, "run": name, **t} for t in tr]
        if pos is not None:
            out["positions"] += [{"book": bk.parent, "window": wname, "cost_bps": cost, "run": name, **p} for p in pos]
        if nav is not None:
            out["nav"][(bk.parent, cost, name)] = nav

    navs20 = {}
    for cost in costs:
        for rule in RULES:
            e_, gw_ = ar[rule]
            nav, tr, pos = simulate(bk, idx, e_, cost, record=True, gw=gw_, reg=reg_arg(rule, reg))
            out["rows"].append(stat_row(rule, cost, nav, tr, float((e_ > 0).sum())))
            if cost == PRIMARY:
                navs20[rule] = nav
            for t in tr:
                if t["dec_j"] is not None:
                    assert t["idx"] > idx[t["dec_j"]], "V2: a trade is not after its decision"
                    out["v2_trades"] += 1
                elif t["kind"] == "basket_change":
                    assert bk.cal[t["idx"]] == bk.cal[bk.bidx[bk.basket_at[t["idx"]]]] and bk.cal[t["idx"]] >= bk.eff[bk.basket_at[t["idx"]]], "V2: a basket change is not on its availableDate's session"
                    out["v2_basket_trades"] += 1
            if headline:
                keep(rule, cost, tr, pos if cost == PRIMARY else None, nav)
    if headline:
        f_of = {}
        for cost in costs:
            nvh, trh, _ = simulate(bk, idx, np.ones(len(s)), cost, record=True)
            out["rows"].append(stat_row("hold_parent", cost, nvh, trh, float(len(s))))
            keep("hold_parent", cost, trh, None, nvh)
            if cost == 0.0:
                hold0 = nvh
            f_state = float(s.mean())
            for name, e_arr, every, gwv in (("constant_mix", np.full(len(s), f_state), True, None), ("constant_mix_timed", np.full(len(s), f_state), True, np.where(g == 1, GW_BUY, GW_SELL)),
                                            ("sleeve_only", np.zeros(len(s)), False, None), ("sleeve_only_timed", np.zeros(len(s)), False, np.where(g == 1, GW_BUY, GW_SELL))):
                nv, tr2, _ = simulate(bk, idx, e_arr, cost, every=every, record=True, gw=gwv)
                out["rows"].append(stat_row(name, cost, nv, tr2, float(e_arr.sum())))
                keep(name, cost, tr2, None, nv)
            for rule in RULES:
                e_, gw_ = ar[rule]
                f_r = float(e_.mean())
                gw_bar = float(((1 - e_) * gw_).sum() / (1 - e_).sum()) if (1 - e_).sum() > 0 else 0.5
                f_of[rule] = {"f": f_r, "gw_bar": gw_bar}
                nv, tr2, _ = simulate(bk, idx, np.full(len(s), f_r), cost, every=True, record=True, gw=np.full(len(s), gw_bar))
                out["rows"].append(stat_row(f"cmix_{rule}", cost, nv, tr2, f_r * len(s)))
                keep(f"cmix_{rule}", cost, tr2, None, nv)
        out["cmix_params"][bk.parent] = f_of
        out["ledger"] += regime_ledger(bk, dec, navs20, out["nav"][(bk.parent, 0.0, "hold_parent")], wname)
        if win == "w1" and wname == "full":
            r7_runs(bk, idx, s, g, reg, stat_row, out)

    n = len(next(iter(sio.values())))
    for fam, fcosts in plan.items():
        io_k, g_k = FAMILIES[fam]
        for d in range(n):
            st_i = s if io_k == "real" else sio[io_k][d]
            g_i = g if g_k == "real" else sgo[g_k][d]
            reg_i = regime_codes(st_i, g_i)
            mi = mio["real"] if io_k == "real" else mio[io_k][d]
            mgd = mg["real"] if g_k == "real" else mg[g_k][d]
            for rule in RULES:
                e_i, gw_i = rule_arrays(rule, st_i, g_i)
                td = len(trades_due(idx, bk.T, e_i, gw_i))
                for cost in fcosts:
                    nv = simulate(bk, idx, e_i, cost, gw=gw_i, reg=reg_arg(rule, reg_i))
                    ds = stats(nv)
                    out["draw_rows"].append({
                        "book": bk.parent, "window": wname, "cash": cash, "cost_bps": cost, "family": fam, "io_null": io_k, "gold_null": g_k, "rule": rule, "draw_id": d, **ds,
                        "invested_weeks": int(np.asarray(st_i).sum()), "out_sell_weeks": int((reg_i == 2).sum()), "n_in_spells": mi[0], "n_out_spells": mi[1], "spell_sig": mi[2],
                        "strategy_sig": sig_s, "sessions_invested": mi[3], "in_lengths": mi[4], "out_lengths": mi[5], "g_buy_weeks": mgd[0], "n_buy_spells": mgd[1], "n_sell_spells": mgd[2],
                        "g_spell_sig": mgd[3], "real_g_spell_sig": sig_g, "g_buy_lengths": mgd[4], "g_sell_lengths": mgd[5], "trades_due": td})
                    if headline and cost == PRIMARY and fam in ("F1", "F3") and d in curve_ids:
                        curves[f"{bk.parent}|{fam}|{rule}|{d}"] = nv


# ── V3 / V4 / V5 / V6 ────────────────────────────────────────────────────────
def shared_code_diff() -> dict:
    """V4(d): functions shared with t11_engine.py (and t08_engine.py where it has them). Identical = the same AST (docstrings included); the changed ones must be the expected ones."""
    def fns(path):
        tree = ast.parse(Path(path).read_text(encoding="utf-8"))
        return {n.name: ast.dump(n) for n in tree.body if isinstance(n, ast.FunctionDef)}
    a, b, c8 = fns(T11_ENGINE), fns(Path(__file__)), fns(T08_ENGINE)
    must_equal = ["trade", "stats", "sessions_invested", "spells", "spell_sig", "spell_shuffle", "series_bounds", "count_table", "draw_lengths", "free_length_draw", "ie_count", "lens_of",
                  "v3_check", "n_sleeve_trades", "gold_spells_with_out", "flip_counts", "chi2_sf_even", "sampler_selftest_small", "flush_draws", "held_either", "flagged_days",
                  "zero_return_book", "one_instrument_identity", "baskets_table", "held_src_counts"]
    expected_changed = ["ap", "common", "read_pub", "raw_parent", "cash_levels", "simulate", "make_states_io", "make_states_gold", "run_book", "r7_runs", "main", "v6_check", "window_check",
                        "v4_identities", "shared_code_diff"]
    common_names = sorted(set(a) & set(b))
    changed = [n for n in common_names if a[n] != b[n]]
    unexpected = [n for n in changed if n not in expected_changed]
    not_equal_required = [n for n in must_equal if n not in a or n not in b or a[n] != b[n]]
    t8_equal = [n for n in ("trade", "stats", "sessions_invested", "spells", "spell_sig", "count_table", "draw_lengths", "ie_count", "lens_of", "chi2_sf_even") if n in c8 and c8[n] == b.get(n)]
    sleeve_lines = ["Tg = (1 - e_new) * gw_new * V", "Tc = (1 - e_new) * (1 - gw_new) * V", "traded = np.abs(Te - held_s).sum() + abs(Tg - gu * gp) + abs(Tc - cu * lv)",
                    "cost = ow * traded", "k = (V - cost) / V", "Te = e_new * V * w", "new_u[pos] = k * Te[pos] / ps[pos]"]
    t11, t14 = T11_ENGINE.read_text(encoding="utf-8"), Path(__file__).read_text(encoding="utf-8")
    lines_ok = {ln: bool(ln in t11 and ln in t14) for ln in sleeve_lines}
    return {"compared_with_t11": must_equal, "required_not_identical": not_equal_required, "changed_functions": changed, "unexpected_changes": unexpected, "expected_changes": expected_changed,
            "identical_to_t08_as_well": t8_equal, "dropped_from_t11": sorted(set(a) - set(b)), "new_in_t14": sorted(set(b) - set(a)), "sleeve_arithmetic_lines_in_both": lines_ok,
            "pass": bool(not not_equal_required and not unexpected and all(lines_ok.values()))}


def g0_check(bk: Book) -> dict:
    """V4(f) / G0: always-in 0-cost NAV on the book's D17 dates against the published NAV: the overall gap in pp / yr and every calendar year's gap in pp."""
    nav = simulate(bk, np.array([0]), np.ones(1), 0.0)
    c = pd.DataFrame({"m": nav, "p": bk.pub}, index=bk.cal)
    yrs = (len(c) - 1) / 252
    overall = float(((c.m.iloc[-1] / c.m.iloc[0]) ** (1 / yrs) - (c.p.iloc[-1] / c.p.iloc[0]) ** (1 / yrs)) * 100)
    yearly = {}
    prev = c.iloc[0]
    for y, grp in c.groupby(c.index.year):
        last = grp.iloc[-1]
        yearly[int(y)] = float((last.m / prev.m - 1 - (last.p / prev.p - 1)) * 100)
        prev = last
    y2019 = yearly.get(2019, float("nan"))
    ok = bool(abs(overall) <= G0_OVERALL and all(abs(v) <= G0_YEARLY for v in yearly.values()))
    return {"first": str(c.index[0].date()), "last": str(c.index[-1].date()), "overall_pp_per_year": overall, "yearly_pp": yearly, "year_2019_gap_pp": y2019,
            "limits": {"overall_pp_per_year": G0_OVERALL, "each_year_pp": G0_YEARLY}, "pass": ok}


def v3_vs_stored(win: str, states_all: dict) -> dict:
    """D2: every draw state array equals the stored draw_states.npz of the test the window extends (T11 for W1, T08 for W2)."""
    W = WINDOWS[win]
    z = np.load(W["ref_dir"] / "draw_states.npz")
    res, ok = {}, True
    for k, arr in states_all.items():
        p, w, ser, kind = k.split("|")
        sk = f"{p}|{W['stored_r3_key'] if w == 'r3' else w}|{ser}|{kind}"
        if sk not in z.files:
            res[k] = {"stored_key": sk, "found": False}
            ok = False
            continue
        eq = bool(z[sk].shape == arr.shape and (z[sk] == arr).all())
        res[k] = {"stored_key": sk, "found": True, "equal": eq, "draws": int(arr.shape[0])}
        ok &= eq
    return {"compared": len(res), "pass": bool(ok and len(res) > 0), "detail": res}


def regression_nav(win: str, books, out: dict, bks: dict, decs: dict) -> dict:
    """V4(a): the -orig rules (and hold-the-parent, the sleeve-only runs, the constant mixes) reproduce the stored daily_nav.csv to relative 1e-12; decisions equal the stored decisions.csv."""
    W = WINDOWS[win]
    res = {"reference": W["ref"], "rows": [], "decisions": {}, "tolerance_rel": REL_TOL_NAV}
    ref_nav = pd.read_csv(W["ref_dir"] / "daily_nav.csv")
    ref_dec = pd.read_csv(W["ref_dir"] / "decisions.csv")
    refs = [(W["ref"], ref_nav, {"80-orig": "strategy", "50-orig": "strategy_fixed50", "hold_parent": "hold_parent", "sleeve_only": "sleeve_only", "sleeve_only_timed": "sleeve_only_timed",
                                 "constant_mix": "constant_mix", "constant_mix_timed": "constant_mix_timed"}, None)]
    if win == "w2":
        refs.append(("T06", pd.read_csv(T06E / "daily_nav.csv"), {"50-orig": "strategy", "hold_parent": "hold_parent", "sleeve_only": "sleeve_only"}, pd.Timestamp("2026-10-22")))
    ok = True
    for p in books:
        d = decs[p]
        b = ref_dec[ref_dec["book"] == p]
        mine = d.assign(decision_date=d["decision_date"].astype(str))[["decision_date", "decision_idx", "state", "g"]]
        m = mine.merge(b[["decision_date", "decision_idx", "state"]], on="decision_date", how="left", suffixes=("", "_old"))
        hit = m["state_old"].notna()
        mism = int(((m["state"] != m["state_old"]) | (m["decision_idx"] != m["decision_idx_old"]))[hit].sum())
        unmatched = m.loc[~hit, "decision_date"].tolist()
        good = bool(mism == 0 and hit.sum() > 0 and unmatched in ([], [mine["decision_date"].iloc[-1]]))
        res["decisions"][p] = {"compared": int(hit.sum()), "mismatches": mism, "unmatched_dates_in_engine": unmatched, "pass": good}
        ok &= good
        for tag, st, mapping, cut in refs:
            for run_mine, run_ref in mapping.items():
                for cost in COSTS:
                    key = (p, cost, run_mine)
                    if key not in out["nav"]:
                        continue
                    sub = st[(st["book"] == p) & (st["run"] == run_ref) & (st["cost_bps"] == cost)]
                    if not len(sub):
                        continue
                    gs = sub.assign(date=pd.to_datetime(sub["date"])).set_index("date")["nav"]
                    if cut is not None:
                        gs = gs[gs.index <= cut]
                    mv = pd.Series(out["nav"][key], index=bks[p].cal)
                    cd = gs.index.intersection(mv.index)
                    rel = float((mv.loc[cd] / gs.loc[cd] - 1).abs().max()) if len(cd) else float("nan")
                    passed = bool(len(cd) == len(gs) and len(cd) > 0 and rel < REL_TOL_NAV)
                    ok &= passed
                    res["rows"].append({"book": p, "reference": tag, "mine": run_mine, "stored_run": run_ref, "cost_bps": cost, "dates_compared": int(len(cd)), "stored_dates": int(len(gs)),
                                        "max_rel_diff": rel, "pass": passed})
    res["rows_compared"] = len(res["rows"])
    res["worst_rel_diff"] = max([r["max_rel_diff"] for r in res["rows"] if r["max_rel_diff"] == r["max_rel_diff"]] or [float("inf")])
    res["pass"] = bool(ok and res["rows_compared"] > 0)
    return res


def regression_draws(win: str, draws_path: Path) -> dict:
    """V4(a): the -orig rows of draws.csv equal the stored draws.csv of the test the window extends: 80-orig <- stored 'timed', 50-orig <- stored 'fixed50' (F1, F2 only)."""
    W = WINDOWS[win]
    key = ["book", "window", "cash", "cost_bps", "family", "draw_id"]
    cols = key + ["cagr", "max_dd", "end_nav"]
    mine = pd.read_csv(draws_path, usecols=cols + ["rule"])
    mine = mine[mine["rule"].isin(["80-orig", "50-orig"])]
    ref = pd.read_csv(W["ref_dir"] / "draws.csv", usecols=cols + ["sleeve_mode"])
    if win == "w2":
        mine = mine.assign(window=mine["window"].replace({"r3": "live"}))
    res = {"rows": {}, "pass": True}
    for rule, mode in (("80-orig", "timed"), ("50-orig", "fixed50")):
        a = mine[mine["rule"] == rule].drop(columns="rule")
        b = ref[ref["sleeve_mode"] == mode].drop(columns="sleeve_mode")
        m = a.merge(b, on=key, suffixes=("", "_ref"))
        n_expected = len(b[b["book"].isin(a["book"].unique())])
        worst = 0.0
        for c in ("cagr", "max_dd", "end_nav"):
            worst = max(worst, float(((m[c] - m[c + "_ref"]).abs() / m[c + "_ref"].abs().clip(lower=1e-300)).max())) if len(m) else float("inf")
        good = bool(len(m) == n_expected and len(m) > 0 and worst < REL_TOL_NAV)
        res["rows"][rule] = {"stored_mode": mode, "rows_compared": int(len(m)), "stored_rows_for_these_books": int(n_expected), "max_rel_diff": worst, "pass": good}
        res["pass"] &= good
    return res


def v4_identities(win: str, books, bks: dict, decs: dict, out: dict, g0s: dict) -> dict:
    """V4 (a) NAV regression, (b) the one-instrument identity, (c) shared code, (d) signals equal the Master / weekly files, (f) seam / G0 (W2 books)."""
    c = common(win)
    res = {"a_nav_regression": regression_nav(win, books, out, bks, decs), "b_one_instrument": {}, "d_signals": {}, "f_g0": g0s}
    ok = bool(res["a_nav_regression"]["pass"])
    for p in books:
        res["b_one_instrument"][p] = one_instrument_identity(bks[p])
        ok &= res["b_one_instrument"][p]["pass"]
        dec = decs[p]
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
        # rule arrays = targets (vectorised vs scalar)
        tgt_bad = 0
        for rule in RULES:
            e_v, gw_v = rule_arrays(rule, dec["state"].values, dec["g"].values)
            for j, (st_, gg_) in enumerate(zip(dec["state"].values, dec["g"].values)):
                tgt_bad += (targets(rule, int(st_), int(gg_)) != (float(e_v[j]), float(gw_v[j])))
        bad["rule_arrays_vs_targets"] = int(tgt_bad)
        pd_ = bool(all(v == 0 for v in bad.values()) and len(dec) > 0)
        res["d_signals"][p] = {"decisions": int(len(dec)), **{k: int(v) for k, v in bad.items()}, "pass": pd_}
        ok &= pd_
    res["c_shared_code"] = shared_code_diff()
    ok &= res["c_shared_code"]["pass"]
    ok &= all(v["pass"] for v in g0s.values()) if g0s else True
    res["pass"] = bool(ok)
    return res


def v6_check(win: str, out: dict, books, bks: dict, decs: dict) -> dict:
    """V6 the trade, basket and cost identities on every recorded trade of every headline run, the half / liq / partial-basket identities, and the expected trades from the states."""
    TOL = 1e-12
    worst = {"cost_identity": 0.0, "value_conservation": 0.0, "stock_target_gap": 0.0, "gold_target_gap": 0.0, "cash_target_gap": 0.0, "traded_identity": 0.0,
             "continuity_0cost": 0.0, "stock_weight_gap_after_entry_or_full_basket_change": 0.0, "half_entry_stock_gap": 0.0, "half_entry_gold_gap": 0.0, "half_entry_cash_gap": 0.0,
             "partial_basket_gold_unchanged": 0.0, "partial_basket_cash_unchanged": 0.0, "partial_basket_stock_after_vs_before_minus_cost": 0.0, "partial_basket_weight_gap": 0.0,
             "liq_regime_gold_after": 0.0}
    kinds, n, n0, half_in, partial_n, liq_in = Counter(), 0, 0, 0, 0, 0
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
        partial = t["kind"] == "basket_change" and 0 < e < 1 and t["run"] in ("50-half", "80-half")
        if partial:
            partial_n += 1
            worst["partial_basket_gold_unchanged"] = max(worst["partial_basket_gold_unchanged"], abs(t["gold_after"] - t["gold_before"]) / V)
            worst["partial_basket_cash_unchanged"] = max(worst["partial_basket_cash_unchanged"], abs(t["cash_after"] - t["cash_before"]) / V)
            worst["partial_basket_stock_after_vs_before_minus_cost"] = max(worst["partial_basket_stock_after_vs_before_minus_cost"], abs(t["stock_after"] - (t["stock_before"] - cost)) / V)
            worst["partial_basket_weight_gap"] = max(worst["partial_basket_weight_gap"], t["weight_gap"])
            continue
        worst["stock_target_gap"] = max(worst["stock_target_gap"], abs(t["stock_after"] - e * (V - cost)) / V)
        worst["gold_target_gap"] = max(worst["gold_target_gap"], abs(t["gold_after"] - (1 - e) * gwv * (V - cost)) / V)
        worst["cash_target_gap"] = max(worst["cash_target_gap"], abs(t["cash_after"] - (1 - e) * (1 - gwv) * (V - cost)) / V)
        if t["kind"] in ("switch_in", "basket_change", "mix_rebalance", "regime_in", "regime_out") and e > 0:
            worst["stock_weight_gap_after_entry_or_full_basket_change"] = max(worst["stock_weight_gap_after_entry_or_full_basket_change"], t["weight_gap"])
        if e == 0:
            exp_tr = t["stock_before"] + abs(gwv * V - t["gold_before"]) + abs((1 - gwv) * V - t["cash_before"])
            worst["traded_identity"] = max(worst["traded_identity"], abs(t["traded"] - exp_tr) / V)
        if t["kind"] == "regime_in" and t["run"] in ("50-half", "80-half") and e == 0.5:
            half_in += 1
            worst["half_entry_stock_gap"] = max(worst["half_entry_stock_gap"], abs(t["stock_after"] - 0.5 * (V - cost)) / V)
            worst["half_entry_gold_gap"] = max(worst["half_entry_gold_gap"], abs(t["gold_after"] - 0.5 * (V - cost)) / V)
            worst["half_entry_cash_gap"] = max(worst["half_entry_cash_gap"], abs(t["cash_after"]) / V)
        if t["run"] in ("50-liq", "80-liq") and e == 0 and gwv == 0:
            liq_in += 1
            worst["liq_regime_gold_after"] = max(worst["liq_regime_gold_after"], abs(t["gold_after"]) / V)
    # the real rules' recorded trades equal the expectation from the states and the calendar alone, at every cost; basket changes likewise
    count_ok, basket_ok, listed = True, True, {}
    for p in books:
        d, bk = decs[p], bks[p]
        idx, s, g = d["decision_idx"].values, d["state"].values.astype(int), d["g"].values.astype(int)
        T = bk.T
        for rule in RULES:
            e_, gw_ = rule_arrays(rule, s, g)
            held_before, due = e_held_before(idx, T, e_, gw_)
            exp_b = sorted(t for t in bk.basket_events if held_before[t] > 0 and t not in set(due))
            for cost in COSTS:
                rec = [t for t in out["trades"] if t["book"] == p and t["run"] == rule and t["cost_bps"] == cost]
                got = sorted(t["idx"] for t in rec if t["kind"] != "basket_change")
                got_b = sorted(t["idx"] for t in rec if t["kind"] == "basket_change")
                count_ok &= got == due
                basket_ok &= got_b == exp_b
            listed[f"{p}|{rule}"] = {"regime_switch_sleeve_trades": len(due), "basket_changes": len(exp_b)}
        exp_hold = sorted(bk.basket_events)
        for cost in COSTS:
            got_h = sorted(t["idx"] for t in out["trades"] if t["book"] == p and t["run"] == "hold_parent" and t["cost_bps"] == cost and t["kind"] == "basket_change")
            basket_ok &= got_h == exp_hold
    # worked examples: the first book at 20.8 bps
    ex = {}
    p0 = books[0]
    for run, kind in (("50-half", "regime_in"), ("50-half", "regime_out"), ("50-half", "basket_change"), ("80-half", "regime_in"), ("80-half", "regime_out"), ("80-half", "basket_change"),
                      ("50-liq", "regime_in"), ("50-liq", "regime_out"), ("80-liq", "regime_in"), ("80-orig", "sleeve_rebalance")):
        for t in out["trades"]:
            if t["book"] == p0 and t["run"] == run and t["cost_bps"] == PRIMARY and t["kind"] == kind and (kind != "basket_change" or 0 < t["e_after"] < 1):
                j = t["dec_j"]
                d = decs[p0].iloc[j] if j is not None else None
                bk = bks[p0]
                nzb = np.flatnonzero((t["held_before"] > 0) | (t["val_after"] > 0))
                ex[f"{run}|{kind}"] = {"decision_date": str(d["decision_date"]) if d is not None else None, "trade_date": str(t["date"]), "idx": t["idx"], "regime": d["regime"] if d is not None else None,
                                       "e_after": t["e_after"], "gw_after": t["gw_after"], "V": t["V"], "stock_before": t["stock_before"], "gold_before": t["gold_before"], "cash_before": t["cash_before"],
                                       "traded": t["traded"], "cost": t["cost"], "stock_after": t["stock_after"], "gold_after": t["gold_after"], "cash_after": t["cash_after"],
                                       "basket_eff": str(bk.eff[bk.basket_at[t["idx"]]].date()),
                                       "stocks_before_after": {bk.stocks[i]: [float(t["held_before"][i]), float(t["val_after"][i])] for i in nzb[:60]} if kind in ("basket_change", "regime_in") else None}
                break
    ok = bool(n > 0 and all(v <= TOL for v in worst.values()) and count_ok and basket_ok and half_in > 0 and liq_in > 0)
    return {"trades_checked": int(n), "trades_checked_at_0_cost": int(n0), "kinds": {f"{a}|{b}": int(c_) for (a, b), c_ in sorted(kinds.items())}, "worst": worst, "tolerance": TOL,
            "half_regime_entries_checked": int(half_in), "liq_regime_trades_checked": int(liq_in), "partial_basket_changes_checked": int(partial_n),
            "recorded_trades_equal_expected_from_states_at_every_cost": bool(count_ok), "basket_changes_equal_expected_at_every_cost": bool(basket_ok), "expected_per_book_rule": listed,
            "worked_examples": ex, "not_checked_here": "weights drift between trades by construction (units are constant between trade sessions); the initial position at T0 is built without a trade record",
            "pass": ok}


def window_check(rec: dict, exp: dict) -> bool:
    """Step 1's counts (T14.md 2) reproduced by the engine's own series for one book and window."""
    keys = [("weeks", "decisions"), ("sessions", "sessions"), ("first_state", "first_state"), ("in_lengths", "in_lengths"), ("out_lengths", "out_lengths"), ("round_trips", "round_trips"),
            ("weeks_IN", "weeks_IN"), ("weeks_OUT_BUY", "weeks_OUT_BUY"), ("weeks_OUT_SELL", "weeks_OUT_SELL"), ("OUT_SELL_lengths", "out_sell_lengths"), ("OUT_BUY_lengths", "out_buy_lengths"),
            ("g_flips", "g_flips"), ("g_first_state", "g_first_state"), ("start", "start"), ("end", "end")]
    good = all(exp[a] == rec[b] for a, b in keys)
    for r in RULES:
        good &= exp["rules"][r]["trades_from_regime_and_gold_changes"] == rec["trades_due"][r]
    return bool(good)


def process_book(job: dict) -> dict:
    """One (window, book): everything the book needs, in its own process. Returns the accumulators and the per-book audit pieces."""
    win, p, n_draws, shared = job["win"], job["book"], job["n_draws"], job["shared"]
    W = WINDOWS[win]
    t1 = time.time()
    out = {"rows": [], "draw_rows": [], "nav": {}, "trades": [], "positions": [], "v2_trades": 0, "v2_basket_trades": 0, "r7_flagged": [], "r7_export": [], "r7_summary": {}, "ledger": [],
           "cmix_params": {}}
    curves: dict = {}
    curve_ids = set(range(20)) | set(int(x) for x in np.random.default_rng(list(CURVE_SEED)).choice(n_draws, size=min(20, n_draws), replace=False))
    bk = Book(p, win)
    dec = bk.decisions()
    bk.nobar_trades = bk.gold_norange_trades = bk.gold_nobar_trades = 0
    plan_full = {"F1": list(COSTS), "F2": list(COSTS), "F3": list(COSTS), "F4": list(COSTS), "F5": [PRIMARY]}
    st_io, st_g = shared["full"]["io"], shared["full"]["gold"]
    run_book(bk, dec, st_io, st_g, win, "full", "lbes", plan_full, True, out, curves, curve_ids)
    stand_in = {"stock_lines_priced_by_stand_in_in_trades": bk.nobar_trades, "goldbees_trades_filled_at_raw_OHLC4_no_MCX_range": bk.gold_norange_trades,
                "goldbees_trades_priced_at_previous_close_no_gold_bar": bk.gold_nobar_trades}
    g0 = g0_check(bk) if W["cal"] == "d17" else None
    # R2: LIQUIDCASE as the cash leg (the same states)
    bk3 = Book(p, win, cash="liq")
    run_book(bk3, dec, st_io, st_g, win, "full", "liq", {"F1": [PRIMARY], "F3": [PRIMARY]}, False, out, curves, curve_ids)
    # R3: its own window
    r3 = None
    bk4 = Book(p, win, start=W["r3_start"])
    dec4 = bk4.decisions()
    if shared.get("r3") is not None:
        run_book(bk4, dec4, shared["r3"]["io"], shared["r3"]["gold"], win, "r3", "lbes", {"F1": [PRIMARY], "F3": [PRIMARY]}, False, out, curves, curve_ids)
    # the seam (W1 needs the W2 book's 2019 path: done in the main process from W2's hold-parent NAV)
    hold20 = out["nav"][(p, PRIMARY, "hold_parent")]
    return {"book": p, "out": out, "curves": curves, "dec": dec, "dec4": dec4, "seconds": time.time() - t1, "stand_in": stand_in, "g0": g0, "cal": bk.cal, "cal4": bk4.cal,
            "bk_summary": {"t0": str(bk.t0.date()), "last": str(bk.cal[-1].date()), "T": bk.T, "T4": bk4.T, "basket_events": sorted(bk.basket_events), "bidx": [int(x) for x in bk.bidx],
                           "eff": [str(d.date()) for d in bk.eff], "b0": bk.b0, "initial_basket_switch_session": bk.initial_basket_switch_session, "gold_no_own_bar": bk.gold_no_own_bar,
                           "gold_norange_sessions": [str(d.date()) for d in bk.cal[bk.gold_norange]], "cash_info": bk.cash_info, "stocks": bk.stocks,
                           "nobar_any_held_sessions": int(((bk.W[bk.basket_at] > 0) & bk.nobar).any(axis=1).sum()), "src_counts": held_src_counts(bk),
                           "r3_t0": str(bk4.t0.date()), "r3_initial_basket_switch_session": bk4.initial_basket_switch_session, "hold20_end": float(hold20[-1])}}


def data_selftest(win: str) -> dict:
    """The data boundary: a non-approved, superseded, pending or unregistered file must raise; the Smallcap 100 guard must raise before its usable-from date."""
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
    return selftest


def seam_2019(p: str) -> dict:
    """W1's V4(f): the always-in 0-cost NAV on D17's dates 2019-01-02 -> 2019-12-31 against the published NAV (limit +-0.5 pp over the year), from the W2 book's path."""
    bk = Book(p, "w2")
    nav = simulate(bk, np.array([0]), np.ones(1), 0.0)
    c = pd.DataFrame({"m": nav, "p": bk.pub}, index=bk.cal)
    c = c[c.index <= pd.Timestamp("2019-12-31")]
    c = c / c.iloc[0] * 100
    gap = float((c.m.iloc[-1] / c.m.iloc[0] - c.p.iloc[-1] / c.p.iloc[0]) * 100)
    return {"first": str(c.index[0].date()), "last": str(c.index[-1].date()), "year_gap_pp": gap, "limit_pp": 0.5, "pass": bool(abs(gap) <= 0.5)}


def build_counts(bk: Book, dec: pd.DataFrame) -> dict:
    idx = dec["decision_idx"].values
    s, g = dec["state"].values.astype(int), dec["g"].values.astype(int)
    r0, rg = lens_of(s), lens_of(g)
    reg = regime_codes(s, g)
    sell = out_sell_spells(reg)
    buy_runs = []
    j = 0
    while j < len(reg):
        k = j
        while k + 1 < len(reg) and reg[k + 1] == reg[j]:
            k += 1
        if reg[j] == 1:
            buy_runs.append(k - j + 1)
        j = k + 1
    return {"decisions": len(dec), "sessions": bk.T, "first_state": int(s[0]), "in_lengths": r0[0], "out_lengths": r0[1], "round_trips": min(len(r0[0]), len(r0[1])),
            "weeks_IN": int((reg == 0).sum()), "weeks_OUT_BUY": int((reg == 1).sum()), "weeks_OUT_SELL": int((reg == 2).sum()), "out_sell_lengths": [b - a_ + 1 for a_, b in sell],
            "out_buy_lengths": buy_runs, "g_flips": int((g[1:] != g[:-1]).sum()), "g_first_state": int(g[0]), "start": str(bk.cal[0].date()), "end": str(bk.cal[-1].date()),
            "trades_due": {r: len(trades_due(idx, bk.T, *rule_arrays(r, s, g))) for r in RULES}, "g_buy_lengths": rg[0], "g_sell_lengths": rg[1]}


def run_window(win: str, a, outdir: Path) -> dict:
    W = WINDOWS[win]
    USED.clear()                         # inputs.csv and the window-coverage check list this window's files only
    t_start = time.time()
    outdir.mkdir(parents=True, exist_ok=True)
    end = end_of(win)
    books = a.books or (PARENTS[:1] if a.quick else PARENTS)
    assert all(b in PARENTS for b in books), books
    n_draws = a.draws if a.draws else (20 if a.quick else N_DRAWS)
    s1 = json.loads(STEP1.read_text(encoding="utf-8"))
    selftest = data_selftest(win)
    c0 = common(win)
    print(f"[{win}] data: window {'2014-09-01' if win == 'w1' else 'D17 first date'} -> {end.date()}, approved data as of {AD.as_of()}; non-approved open and the Smallcap 100 guard raise: {selftest['pass']}", flush=True)

    t11s1 = json.loads((AA / "tests" / "T11" / "logs" / "step_1_spell_counts.json").read_text(encoding="utf-8")) if win == "w1" else None
    bser, cache = {}, {}
    for p in books:                      # per book: a book's own series (W2: SCMO_0007 starts 2019-01-04 and has 409 weekly decisions, T06-8) and its own draw states, as T08
        bkp = Book(p, win)
        decp = bkp.decisions()
        sp, gp = decp["state"].values.astype(int), decp["g"].values.astype(int)
        bio, bg = series_bounds(sp), series_bounds(gp)
        if win == "w2":
            assert bio == IO_BOUNDS_W2 and bg == GOLD_BOUNDS_W2, (p, bio, bg)
        else:
            for st, nm in ((1, "in"), (0, "out")):
                assert bio[st] == (t11s1["full"]["io_tables"][nm]["lo"], t11s1["full"]["io_tables"][nm]["hi"]) and bg[st] == (t11s1["full"]["gold_tables"][nm]["lo"], t11s1["full"]["gold_tables"][nm]["hi"])
        bk4p = Book(p, win, start=W["r3_start"])
        dec4p = bk4p.decisions()
        s4p, g4p = dec4p["state"].values.astype(int), dec4p["g"].values.astype(int)
        b4io, b4g = (series_bounds(s4p), series_bounds(g4p)) if W["r3_bounds"] == "own" else (bio, bg)
        r4, rg4 = lens_of(s4p), lens_of(g4p)
        rt4 = min(len(r4[0]), len(r4[1]))
        sell4 = len(out_sell_spells(regime_codes(s4p, g4p)))
        feas = {"in": b4io[1][0] * len(r4[0]) <= sum(r4[0]) <= b4io[1][1] * len(r4[0]), "out": b4io[0][0] * len(r4[1]) <= sum(r4[1]) <= b4io[0][1] * len(r4[1]),
                "buy": b4g[1][0] * len(rg4[0]) <= sum(rg4[0]) <= b4g[1][1] * len(rg4[0]), "sell": b4g[0][0] * len(rg4[1]) <= sum(rg4[1]) <= b4g[0][1] * len(rg4[1])}
        r3ok = bool(rt4 >= 4 and sell4 >= 4 and all(feas.values()))
        nfull_p = int((regime_codes(sp, gp) == 2).sum())
        spells_p = len(out_sell_spells(regime_codes(sp, gp)))
        assert min(len(lens_of(sp)[0]), len(lens_of(sp)[1])) >= 4 and spells_p >= 4 and nfull_p > 0, f"{p}: NOT REPORTABLE: fewer than 4 round trips or 4 OUT-SELL spells; stop and ask Manu"
        key = (sp.tobytes(), gp.tobytes(), s4p.tobytes(), g4p.tobytes())
        if key not in cache:
            sh = {"full": {"s": sp, "g": gp, "io": make_states_io(sp, n_draws, bio, W["seeds"]), "gold": make_states_gold(gp, n_draws, bg, W["seeds"])}, "r3": None}
            if r3ok:
                sh["r3"] = {"s": s4p, "g": g4p, "io": make_states_io(s4p, n_draws, b4io, W["seeds"]), "gold": make_states_gold(g4p, n_draws, b4g, W["seeds"])}
            cache[key] = sh
        bser[p] = dict(s=sp, g=gp, s4=s4p, g4=g4p, b_io=bio, b_g=bg, b4_io=b4io, b4_g=b4g, shared=cache[key], r3_ok=r3ok, nfull=nfull_p, spells=spells_p,
                      r3_gate={"round_trips": rt4, "out_sell_spells": sell4, "feasible": feas, "reportable": r3ok})
    ref = bser[books[0]]
    s, g, b_io, b_g, s4, g4, b4_io, b4_g = ref["s"], ref["g"], ref["b_io"], ref["b_g"], ref["s4"], ref["g4"], ref["b4_io"], ref["b4_g"]
    r3_ok = bool(all(v["r3_ok"] for v in bser.values()))
    r3_gate = {p: v["r3_gate"] for p, v in bser.items()}
    nfull, spells_full = ref["nfull"], ref["spells"]

    jobs = [{"win": win, "book": p, "n_draws": n_draws, "shared": bser[p]["shared"]} for p in books]
    workers = min(a.workers, len(jobs))
    t_jobs = time.time()
    if workers > 1:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            results = list(ex.map(process_book, jobs))
    else:
        results = [process_book(j) for j in jobs]
    print(f"[{win}] books done in {time.time() - t_jobs:.0f}s: " + ", ".join(f"{r['book']} {r['seconds']:.0f}s" for r in results), flush=True)

    out = {"rows": [], "draw_rows": [], "nav": {}, "trades": [], "positions": [], "v2_trades": 0, "v2_basket_trades": 0, "r7_flagged": [], "r7_export": [], "r7_summary": {}, "ledger": [], "cmix_params": {}}
    curves, decs, decs4, bks_cal, g0s = {}, {}, {}, {}, {}
    for r in results:
        o = r["out"]
        for k in ("rows", "trades", "positions", "r7_flagged", "r7_export", "ledger"):
            out[k] += o[k]
        out["nav"].update(o["nav"])
        out["r7_summary"].update(o["r7_summary"])
        out["cmix_params"].update(o["cmix_params"])
        out["v2_trades"] += o["v2_trades"]
        out["v2_basket_trades"] += o["v2_basket_trades"]
        curves.update(r["curves"])
        decs[r["book"]], decs4[r["book"]], bks_cal[r["book"]] = r["dec"], r["dec4"], r["cal"]
        if r["g0"] is not None:
            g0s[r["book"]] = r["g0"]
    # the Book objects are not shipped between processes: rebuild light views in this process for the gates (cached raw data makes this cheap)
    bks = {p: Book(p, win) for p in books}
    # draws.csv (written by the workers' rows; the full set is written here)
    draws_path = outdir / "draws.csv"
    first = True
    for r in results:
        rows = r["out"]["draw_rows"]
        pd.DataFrame(rows).to_csv(draws_path, mode="w" if first else "a", header=first, index=False)
        first = False
    n_draw_rows = sum(len(r["out"]["draw_rows"]) for r in results)

    ct, v3_res, v5c, states_all, real_states = {}, {}, {}, {}, {}
    for p in books:
        sp_ = bser[p]
        windows = [("full", sp_["s"], sp_["g"], sp_["b_io"], sp_["b_g"], sp_["shared"]["full"])]
        if r3_ok:
            windows.append(("r3", sp_["s4"], sp_["g4"], sp_["b4_io"], sp_["b4_g"], sp_["shared"]["r3"]))
        real_states[f"{p}|full|io"], real_states[f"{p}|full|gold"] = decs[p]["state"].values.astype(np.uint8), decs[p]["g"].values.astype(np.uint8)
        real_states[f"{p}|r3|io"], real_states[f"{p}|r3|gold"] = decs4[p]["state"].values.astype(np.uint8), decs4[p]["g"].values.astype(np.uint8)
        assert (decs[p]["state"].values == sp_["s"]).all() and (decs[p]["g"].values == sp_["g"]).all() and (decs4[p]["state"].values == sp_["s4"]).all() and (decs4[p]["g"].values == sp_["g4"]).all(), "a book's decision series changed between the engine's two builds"
        for w, sw, gk, bio, bg, sh in windows:
            for k, v in sh["io"].items():
                states_all[f"{p}|{w}|io|{k}"] = v
            for k, v in sh["gold"].items():
                states_all[f"{p}|{w}|gold|{k}"] = v
            v3_res[f"{p}|{w}|io"] = v3_check(sw, sh["io"], bio)
            v3_res[f"{p}|{w}|gold"] = v3_check(gk, sh["gold"], bg)
            for ser, arr, bnd, names, nullkey in (("io", sw, bio, ("in", "out"), "N4.10"), ("gold", gk, bg, ("buy", "sell"), "N4.10-g")):
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
    v3_stored = v3_vs_stored(win, states_all) if n_draws == N_DRAWS else {"pass": None, "note": f"not compared: {n_draws} draws, the stored files hold {N_DRAWS}"}
    if n_draws != N_DRAWS:      # a smoke run: compare the first n_draws rows of each stored array
        z = np.load(W["ref_dir"] / "draw_states.npz")
        det, okk = {}, True
        for k, arr in states_all.items():
            p_, w_, ser_, kind_ = k.split("|")
            sk = f"{p_}|{W['stored_r3_key'] if w_ == 'r3' else w_}|{ser_}|{kind_}"
            eq = bool(sk in z.files and (z[sk][:n_draws] == arr).all())
            det[k] = {"stored_key": sk, "equal_first_n_draws": eq}
            okk &= eq
        v3_stored = {"compared": len(det), "pass": bool(okk), "detail": det, "note": f"smoke run: first {n_draws} draws compared"}

    # step 1 reproduction
    step1_detail = {}
    for p in books:
        rec = build_counts(bks[p], decs[p])
        exp = s1["w1"]["full"] if win == "w1" else s1["w2"][p]["full"]
        step1_detail[f"{p}|full"] = window_check(rec, exp)
        bk4_p = Book(p, win, start=W["r3_start"])
        rec4 = build_counts(bk4_p, decs4[p])
        exp4 = s1["w1"]["r3"] if win == "w1" else s1["w2"][p]["live"]
        step1_detail[f"{p}|r3"] = window_check(rec4, exp4)
    s1_ok = bool(all(step1_detail.values()))

    # V2
    audit = {"readings": READINGS, "books": {}}
    v2_viol, v2_cnt = 0, 0
    for p in books:
        dec, bk = decs[p], bks[p]
        lab_ok = int((pd.to_datetime(dec["latest_label"]) <= pd.to_datetime(dec["decision_date"])).sum())
        lab_g_ok = int((pd.to_datetime(dec["label_MAUc1"]) <= pd.to_datetime(dec["decision_date"])).sum())
        trade_idx = dec["decision_idx"].values + 1
        traded_rows = int((trade_idx < bk.T).sum())
        tdates = pd.to_datetime(dec["trade_date"].dropna())
        ddates = pd.to_datetime(dec.loc[dec["trade_date"].notna(), "decision_date"])
        sc_min_label = pd.to_datetime(dec["label_SC100"]).min()
        assert sc_min_label >= SC_USABLE_FROM, f"a Smallcap 100 signal row dated {sc_min_label.date()} (before the usable-from date) was read"
        viol = (len(dec) - lab_ok) + (len(dec) - lab_g_ok) + int((tdates.values <= ddates.values).sum())
        v2_viol += viol
        v2_cnt += len(dec) * 2 + traded_rows + 1
        rs = next(r for r in results if r["book"] == p)
        cnt = build_counts(bk, dec)
        audit["books"][p] = {**{k: v for k, v in cnt.items() if k != "trades_due"}, "trades_due_per_rule": cnt["trades_due"], "bounds": {"in": list(b_io[1]), "out": list(b_io[0]), "buy": list(b_g[1]), "sell": list(b_g[0])},
                             "v2_decisions_checked": len(dec), "v2_violations": viol, "v2_trades_checked": traded_rows, "v2_sc100_signal_first_label_date": str(sc_min_label.date()),
                             "stale_label_weeks(age>=5d, excluding T0)": int((dec["label_age_days"].values[1:] >= 5).sum()), "cash": rs["bk_summary"]["cash_info"], "stand_in": rs["stand_in"],
                             "baskets": {"effective_dates_in_window": [d for d in rs["bk_summary"]["eff"] if bk.t0 <= pd.Timestamp(d) <= bk.end], "basket_changes": len(rs["bk_summary"]["basket_events"]),
                                         "initial_basket_session": rs["bk_summary"]["initial_basket_switch_session"], "change_sessions": [str(bk.cal[i].date()) for i in rs["bk_summary"]["basket_events"]]},
                             "gold_sessions_without_own_bar": rs["bk_summary"]["gold_no_own_bar"], "gold_sessions_without_mcx_range": rs["bk_summary"]["gold_norange_sessions"],
                             "window_sessions_where_a_held_stock_has_no_bar": rs["bk_summary"]["nobar_any_held_sessions"], "src_counts": rs["bk_summary"]["src_counts"],
                             "regime_ledger": [r_ for r_ in out["ledger"] if r_["book"] == p and r_["window"] == "full"]}
    frozen_detail, frozen_ok = {}, True
    if win == "w1":
        for p in books:
            hs = audit["books"][p]["src_counts"]
            ok_p = bool(hs["export_by_stock"] == FROZEN_EXPORT[p] and hs["held_stock_sessions_by_src"]["export"] == FROZEN_EXPORT_TOTAL[p] and hs["carried_bars_in_window_all_stocks"] == FROZEN_CARRIED[p])
            frozen_detail[p] = {"pass": ok_p, "export_by_stock": hs["export_by_stock"], "export_total": hs["held_stock_sessions_by_src"]["export"], "carried_in_window": hs["carried_bars_in_window_all_stocks"]}
            frozen_ok &= ok_p
            assert audit["books"][p]["gold_sessions_without_own_bar"] == [str(NO_GOLD_SESSION.date())], audit["books"][p]["gold_sessions_without_own_bar"]
        no_d18 = [str(d.date()) for d in bks[books[0]].cal if d not in set(raw_parent(books[0], end)["d18_dates"])]
        assert no_d18 == [str(NO_D18_SESSION.date())], no_d18
    v2_cnt += out["v2_trades"] + out["v2_basket_trades"]
    v2_ok = bool(v2_viol == 0 and v2_cnt > 0)

    # V4, V5, V6
    if win == "w1":
        g0_for_v4 = {p: seam_2019(p) for p in books}
    else:
        g0_for_v4 = g0s
    # write evidence files first (V4 reads draws.csv)
    pd.concat(decs.values()).to_csv(outdir / "decisions.csv", index=False)
    pd.concat(decs4.values()).to_csv(outdir / "decisions_r3.csv", index=False)
    rows = pd.DataFrame(out["rows"])
    rows.to_csv(outdir / "stats.csv", index=False)
    tcols = ["book", "window", "cost_bps", "run", "date", "idx", "kind", "e_after", "gw_after", "basket_eff", "V", "traded", "cost", "stock_before", "gold_before", "cash_before",
             "stock_after", "gold_after", "cash_after", "nav_close_after", "dec_j"]
    tdf = pd.DataFrame([{k: t.get(k) for k in tcols} for t in out["trades"]]).reindex(columns=tcols)
    tdf.to_csv(outdir / "trades.csv", index=False)
    pd.DataFrame(out["positions"]).to_csv(outdir / "positions.csv", index=False)
    pd.DataFrame(out["ledger"]).to_csv(outdir / "regime_ledger.csv", index=False)
    pd.DataFrame([{"book": p, "rule": r_, **v} for p in books for r_, v in out["cmix_params"][p].items()]).to_csv(outdir / "constant_mix_params.csv", index=False)
    daily = [pd.DataFrame({"book": p, "date": bks[p].cal, "cost_bps": cost, "run": name, "nav": nv}) for (p, cost, name), nv in out["nav"].items()]
    pd.concat(daily).to_csv(outdir / "daily_nav.csv", index=False)
    if win == "w1":
        pn = [pd.DataFrame({"book": p, "date": bks[p].cal, "hold_parent_0bps": out["nav"][(p, 0.0, "hold_parent")], "hold_parent_20.8bps": out["nav"][(p, PRIMARY, "hold_parent")],
                            **{f"{r_}_20.8bps": out["nav"][(p, PRIMARY, r_)] for r_ in RULES}}) for p in books]
        pd.concat(pn).to_csv(outdir / "parent_nav_2014-09-01_2019-01-02.csv", index=False)
        (outdir / "parent_nav_2014-09-01_2019-01-02.md").write_text(
            "# Rebuilt parent NAV, 2014-09-01 to 2019-01-02\n\nrebuilt from the parent's baskets and Eikon prices, not validated against a published NAV before 2019-01-02.\n\n"
            "Columns: `hold_parent_*` (always IN) and the six rules at 20.8 bps, base 1.0 at 2014-09-01's close. Not approved data; no other test may read it.\n", encoding="utf-8")
    pd.DataFrame(out["r7_flagged"], columns=["book", "date", "stock", "prev_close", "close", "ret", "w_prev", "w_cur", "src"]).to_csv(outdir / "r7_flagged_days.csv", index=False)
    pd.DataFrame(out["r7_export"], columns=["book", "stock", "held_sessions_export", "end_nav_hold_parent", "end_nav_hold_parent_noexport"]).to_csv(outdir / "r7_export.csv", index=False)
    np.savez_compressed(outdir / "draw_curves_20.8.npz", **curves)
    np.savez_compressed(outdir / "draw_states.npz", **states_all)
    np.savez_compressed(outdir / "real_states.npz", **real_states)
    pd.concat([r["dec"][["book", "decision_date", "decision_idx", "regime"]] for r in results]).to_csv(outdir / "regimes.csv", index=False)

    reg = v4_identities(win, books, bks, decs, out, g0_for_v4)
    reg["a_draws_regression"] = regression_draws(win, draws_path) if n_draws == N_DRAWS else {"pass": True, "note": f"not compared: {n_draws} draws (smoke)"}
    if n_draws != N_DRAWS:      # smoke: compare the first n_draws draw ids only
        W_ = WINDOWS[win]
        key = ["book", "window", "cash", "cost_bps", "family", "draw_id"]
        cols = key + ["cagr", "max_dd", "end_nav"]
        mine = pd.read_csv(draws_path, usecols=cols + ["rule"])
        mine = mine[mine["rule"].isin(["80-orig", "50-orig"])]
        if win == "w2":
            mine = mine.assign(window=mine["window"].replace({"r3": "live"}))
        ref = pd.read_csv(W_["ref_dir"] / "draws.csv", usecols=cols + ["sleeve_mode"])
        ref = ref[ref["draw_id"] < n_draws]
        det, okk = {}, True
        for rule, mode in (("80-orig", "timed"), ("50-orig", "fixed50")):
            m = mine[mine["rule"] == rule].drop(columns="rule").merge(ref[ref["sleeve_mode"] == mode].drop(columns="sleeve_mode"), on=key, suffixes=("", "_ref"))
            worst = max(float(((m[c] - m[c + "_ref"]).abs() / m[c + "_ref"].abs().clip(lower=1e-300)).max()) for c in ("cagr", "max_dd", "end_nav")) if len(m) else float("inf")
            det[rule] = {"rows_compared": int(len(m)), "max_rel_diff": worst, "pass": bool(len(m) > 0 and worst < REL_TOL_NAV)}
            okk &= det[rule]["pass"]
        reg["a_draws_regression"] = {"pass": bool(okk), "rows": det, "note": f"smoke run: first {n_draws} draw ids compared"}
    reg["pass"] = bool(reg["pass"] and reg["a_draws_regression"]["pass"])
    if win == "w1":
        reg["f_seam_2019"] = g0_for_v4
    (outdir / "regression.json").write_text(json.dumps(reg, indent=1, default=str), encoding="utf-8")
    small = sampler_selftest_small()
    small14 = sampler_selftest_small(seed=(14, 6, 123456789))
    small["also_seed_14"] = {"p": small14["p"], "pass": small14["pass"], "seed": small14["seed"]}
    small["pass"] = bool(small["pass"] and small14["pass"])
    v5b = all(v["dp_equals_inclusion_exclusion"] for v in ct.values())
    v5 = {"a_small_case": small, "b_dp_equals_inclusion_exclusion": {"all_equal": bool(v5b), "checked": int(len(ct))}, "c_mean_length_within_4_se": v5c,
          "pass": bool(small["pass"] and v5b and all(v["pass"] for v in v5c.values()))}
    (outdir / "sampler_selftest.json").write_text(json.dumps(v5, indent=1, default=str), encoding="utf-8")
    b0 = audit["books"][books[0]]
    (outdir / "count_table.json").write_text(json.dumps({"bounds": {"full": {"io": b0["bounds"]}, "r3": {"io_in": list(b4_io[1]), "io_out": list(b4_io[0]), "gold_buy": list(b4_g[1]), "gold_sell": list(b4_g[0])}}, "tables": ct}, indent=1), encoding="utf-8")
    v6 = v6_check(win, out, books, bks, decs)
    v3_ok = bool(all(v["pass"] for v in v3_res.values()) and v3_stored["pass"])
    audit["v2"] = {"checks": int(v2_cnt), "violations": int(v2_viol), "recorded_trades_after_their_decision": int(out["v2_trades"]), "recorded_basket_changes_on_or_after_availableDate": int(out["v2_basket_trades"]),
                   "sc100_rule7_checks": len(books), "sc100_signal_rows_read_from": str(c0["master"]["SC100"].index.min().date()), "pass": v2_ok}
    audit["v3"] = {"per_book_window": v3_res, "vs_stored_draw_states": {k: v for k, v in v3_stored.items() if k != "detail"}, "pass": v3_ok, "draws_per_type": int(n_draws),
                   "reportability": {"r3_window": r3_gate, "out_sell_spells_full": spells_full, "out_sell_weeks_full": nfull}}
    audit["v4"] = {"pass": reg["pass"]}
    audit["v5"] = {"pass": v5["pass"]}
    audit["v6"] = v6
    write_inputs = pd.DataFrame([{k: v.get(k) for k in ("file", "through", "bytes", "sha256", "approved_row", "usable_from")} for v in USED.values()])
    write_inputs.to_csv(outdir / "inputs.csv", index=False)
    for rel, r_ in USED.items():
        if r_["id"] in ("D26", "D03", "D09", "D11", "D24b", "D24", "D18") and str(r_["through"])[:1].isdigit():
            assert str(r_["through"]) >= str(end.date()), f"{rel}: approved through {r_['through']}, before the window's end {end.date()}: stop and ask Manu"
    audit["data"] = {"approved_data_as_of": AD.as_of(), "window_end": str(end.date()), "inputs": int(len(USED)), "non_approved_open_and_guards": selftest,
                     "master_rows_after_END_dropped": c0["master_rows_after_end"], "mauc1_rows_after_END_dropped": int(c0["gold_master_rows_after_end"]),
                     "goldbees_first_bar": str(c0["gold_first"].date()), "goldbees_file_last": str(c0["gold_last"].date()), "mcx_file_last": str(c0["mcx_last"].date()),
                     "cash": {"lbes_last": str(c0["lbes_last"].date()), "liq_last": str(c0["liq_last"].date()), "accrued_sessions": 0}, "r7": out["r7_summary"],
                     "random_curve_ids_seed": list(CURVE_SEED)}
    audit["frozen_text_counts"] = {"pass": frozen_ok, "detail": frozen_detail, "applies": win == "w1"}
    audit["step1_counts_reproduced"] = {"pass": s1_ok, "detail": step1_detail, "file": STEP1.relative_to(AA).as_posix()}
    audit["run"] = {"window": win, "name": a.run, "command": " ".join(sys.argv), "draws": n_draws, "books": list(books), "seconds": round(time.time() - t_start), "quick": a.quick,
                    "python": sys.version.split()[0], "numpy": np.__version__, "pandas": pd.__version__, "draw_rows": n_draw_rows,
                    "seeds": {k: list(v) + ["draw_id"] for k, v in W["seeds"].items()}}
    audit["prereg_sha256"] = (T14 / "T14.md").read_text(encoding="utf-8").split("§1–§3 sha256:** `")[1].split("`")[0]
    ok = bool(v2_ok and v3_ok and reg["pass"] and v5["pass"] and v6["pass"] and selftest["pass"] and s1_ok and frozen_ok and r3_ok)
    audit["gates"] = {"V2": v2_ok, "V3": v3_ok, "V4": reg["pass"], "V5": v5["pass"], "V6": v6["pass"], "approved_data_selftest": selftest["pass"], "step1_counts": s1_ok, "frozen_text_counts": frozen_ok,
                      "r3_reportable": r3_ok, "all": ok}
    (outdir / "audit.json").write_text(json.dumps(audit, indent=1, default=str), encoding="utf-8")
    print(f"[{win}] V2 {audit['v2']['checks']} checks, {audit['v2']['violations']} violations; V3 {v3_ok} (stored: {v3_stored['pass']}); V4 {reg['pass']} (nav rows {reg['a_nav_regression']['rows_compared']}, "
          f"worst {reg['a_nav_regression']['worst_rel_diff']:.2e}; draws {reg['a_draws_regression']['pass']}; shared code {reg['c_shared_code']['pass']}); V5 {v5['pass']}; V6 {v6['pass']} "
          f"({v6['trades_checked']} trades, worst {max(v6['worst'].values()):.1e}); step1 {s1_ok}; frozen {frozen_ok}", flush=True)
    print(f"[{win}] gates: {audit['gates']}  done in {time.time() - t_start:.0f}s -> {outdir}", flush=True)
    return {"ok": ok, "gates": audit["gates"]}


def main():
    ap_ = argparse.ArgumentParser()
    ap_.add_argument("--run", default="headline")
    ap_.add_argument("--window", choices=["w1", "w2", "both"], default="both")
    ap_.add_argument("--draws", type=int, default=None)
    ap_.add_argument("--quick", action="store_true", help="smoke test: the first book only, 20 draws unless --draws is given")
    ap_.add_argument("--books", nargs="+", default=None)
    ap_.add_argument("--workers", type=int, default=4, help="processes: one per book")
    ap_.add_argument("--outdir", default=None, help="write here (<outdir>/<window>) instead of tests/T14/evidence/<run>/<window>")
    a = ap_.parse_args()
    base = Path(a.outdir) if a.outdir else T14 / "evidence" / a.run
    wins = ["w1", "w2"] if a.window == "both" else [a.window]
    ok = True
    for w in wins:
        r = run_window(w, a, base / w)
        ok &= r["ok"]
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
