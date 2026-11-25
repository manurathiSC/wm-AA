# -*- coding: utf-8 -*-
"""T15 engine: the three-index switch holding, in the OUT-SELL regime (switch OUT and MAUc1 SELL), the liquid ETF plus each index whose own SIGN is BUY, in equal parts.

A FORK of analysis/t14_engine.py (copied, not imported; unchanged functions are copied verbatim and checked by `shared_code_diff`). The null machinery (draws, samplers, seeds,
draws.csv) is removed: T15 has no null (Manu's waiver, 2026-11-25). Index lines (the three price indices, filled at their own OHLC4, marked at the close) are added to `Book`, `trade`
and `simulate`. Pre-registration: tests/T15/T15.md sections 1-3 (frozen; `python tests/T15/check_prereg.py`); plan: tests/T15/PLAN.md; evidence contract: tests/T15/logs/evidence_contract.md.

    python analysis/t15_engine.py [--run NAME] [--window w1|w2|both] [--quick] [--books SCMO_0003 ...] [--workers N] [--outdir DIR]     (from AA/)

Eight rules (T15.md 2.1): 50-orig, 50-half, 50-liq, 50-idx, 80-orig, 80-half, 80-liq, 80-idx. A target is the book's split: parent share e, GOLDBEES share, cash share and one share per index
(absolute shares of the book's value). The six T14 rules map T14's (e, gw) to e, (1-e)*gw, (1-e)*(1-gw), 0, so their path is exactly T14's. Regime at each weekly decision: IN (all three index
SIGN BUY), OUT-BUY (not IN, MAUc1 BUY), OUT-SELL (not IN, MAUc1 SELL). `-idx` in OUT-SELL: cash 1/(k+1) and each index of B 1/(k+1) (B = the indices whose own SIGN is BUY, k = |B|),
no parent, no GOLDBEES; a change of the target vector (B included) is a trade on the next session.

Runs per book: headline (full window, LBES cash, 8 rules at 0 / 20.8 / 50 bps, comparators, constant mixes, ledger); R2 (LIQUIDCASE cash leg); R3 (own window); R4 (`-idx` holds cash only
during one OUT-SELL spell); R5 (index leg minus 0.5 pp a year); V4(b) (index priced as cash, 0 cost). Writes <outdir>/<window>/ (see tests/T15/logs/evidence_contract.md).
The engine prints gates and counts only, no performance figure.
"""
from __future__ import annotations

import argparse
import ast
import copy
import json
import math
import sys
import time
import warnings
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
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
IDX_DIR = HD / "extended_2026-11-12" / "index_daily_pre2019"           # D25 (also the D26 calendar)
IDX_DIR_W2 = HD / "extended_2026-11-25" / "index_daily_2019_2026"      # D25c
D24B_DIR = HD / "extended_2026-11-12" / "MAUc1_from_2003"
D24_DIR = HD / "extended_2026-11-06" / "MAUc1"
D12_FILE = AA / "analysis" / "evidence" / "final_strategy" / "mauc1" / "mauc1_daily_clean.csv"
MASTER_DIR = HD / "extended_2026-10-30" / "Master"
D17_DIR = HD / "extended_2026-11-06" / "published_nav"
GOLD_D09 = AA / "analysis" / "cache" / "why_gold_ohlc_eikon_extended_2026-11-04.parquet"
CAL_FILE = IDX_DIR / "nse_trading_days.csv"
T15 = AA / "tests" / "T15"
T14E = AA / "tests" / "T14" / "evidence" / "headline"      # read-only test evidence, V4(a) only
T14_ENGINE = Path(__file__).with_name("t14_engine.py")      # source text read by the V4(d) AST comparison only
STEP1 = T15 / "logs" / "step_1_spell_counts.json"

PARENTS = ["SCMO_0003", "SCMO_0007", "SCMO_0010", "SCMO_0029"]
INDICES = ("Nifty100", "MC100", "SC100")
RULES = ["50-orig", "50-half", "50-liq", "50-idx", "80-orig", "80-half", "80-liq", "80-idx"]
T14_RULES = [r for r in RULES if not r.endswith("idx")]
IDX_RULES = ["50-idx", "80-idx"]
FIRST_PRICE_DAY = pd.Timestamp("2014-07-01")
SC_USABLE_FROM = pd.Timestamp("2011-11-25")
COSTS = (0.0, 20.8, 50.0)
PRIMARY = 20.8
DESPIKE_TOL = 0.005
REL_TOL_NAV = 1e-12
G0_OVERALL, G0_YEARLY = 0.25, 0.5                      # pp / yr (T08 E15)
GW_BUY, GW_SELL, GW_FIX = 0.8, 0.2, 0.5
DRAG_PER_YEAR = 0.005                                  # R5: index leg minus 0.5 pp a year, accrued per session as (1 - 0.005/252)^i
REG_NAMES = ("IN", "OUT-BUY", "OUT-SELL")
NO_D18_SESSION = pd.Timestamp("2017-10-19")
NO_GOLD_SESSION = pd.Timestamp("2016-10-30")

WINDOWS = {
    "w1": dict(name="w1", cal="d26", t0=pd.Timestamp("2014-09-01"), end=pd.Timestamp("2019-01-02"), r3_start=pd.Timestamp("2015-01-02"),
               gold_master=D24B_DIR / "Master_MAUc1.xlsx", gold_weekly=D24B_DIR / "mauc1_supertrend_weekly_extended.csv", mcx=D24B_DIR / "mauc1_daily_clean_extended.csv",
               liq_from=None, t14_dir=T14E / "w1", idx_dir=IDX_DIR),
    "w2": dict(name="w2", cal="d17", t0=None, end=None, r3_start=pd.Timestamp("2021-11-01"),
               gold_master=D24_DIR / "Master_MAUc1.xlsx", gold_weekly=D24_DIR / "mauc1_supertrend_weekly_extended.csv", mcx=D12_FILE,
               liq_from=pd.Timestamp("2024-01-24"), t14_dir=T14E / "w2", idx_dir=IDX_DIR_W2),
}

READINGS = {
    "E1": "calendar: W1 = D26's dates 2014-09-01 -> 2019-01-02 (1,070 sessions); W2 = each book's D17 dates of the EXTENDED published NAV from its first date (SCMO_0007: 2019-01-04) to END = the last row of the three "
          "D03 Master files (2026-10-30); rows after END are never used. As T14 E1",
    "E2": "decision dates = T0 and the last session of every later ISO week; the decision at the last session is made and not traded (T14 E2)",
    "E3": "label = latest Master row dated <= decision date, per index and for MAUc1 (W1: D24b, W2: D24); regime IN / OUT-BUY / OUT-SELL from the three SIGNs and g; B = the indices whose own SIGN is BUY, k = |B|; "
          "the Smallcap 100 rows are sliced to >= 2011-11-25",
    "E4": "targets per rule from T15.md 2.1: absolute shares (parent e, GOLDBEES, cash, one per index); the six T14 rules map (e, gw) to e, (1-e)gw, (1-e)(1-gw), 0 so their path is T14's; -idx in OUT-SELL = cash and each "
          "index of B at 1/(k+1); one function `rule_targets` serves every run",
    "E5": "initial position at T0's close, no cost: the target of the decision at T0 (IN: the basket in force, drifted from its availableDate, scaled to NAV 1; OUT: the sleeve; e = 0.5: half the drifted basket and half "
          "GOLDBEES; -idx in OUT-SELL: cash and each index of B at its T0 close)",
    "E6": "stock fill = OHLC4 of the Eikon bar (close if open/high/low is blank; the last close if no bar); GOLDBEES fill = T03's de-spike with the MCX range of the window's file (W1: D24b daily, W2: D12), raw OHLC4 where "
          "the range is missing; index fill = OHLC4 of the index's own bar (D25 in W1, D25c in W2); an index trade on a session without a bar stops the run",
    "E7": "costs: T14's `trade` generalised to index lines (cost = ow x value traded over every line, stocks, GOLDBEES, cash and each index, then every target scaled by (V-cost)/V)",
    "E8": "a basket takes effect on the first session on or after its availableDate; skipped baskets dropped; weights renormalised. While e = 1 a basket change is the full reset trade; while 0 < e < 1 (the -half "
          "comparators) it is T14's D1 partial trade; while e = 0 (-idx in OUT-SELL included) nothing is traded",
    "E9": "trade kinds: switch_in / switch_out (e crosses 0 or 1 between IN and OUT-BUY; for -orig also IN <-> OUT-SELL), sleeve_rebalance, regime_in / regime_out (into / out of OUT-SELL, rules other than -orig), "
          "index_set_change (-idx: B changed while OUT-SELL on both sides), basket_change",
    "E10": "cash level: the extended LBES (D11) as-of on sessions; R2 'liq': W1 liquidEtfFinal (LIQUIDCASE) over the whole window, W2 LBES to the session before 2024-01-24 then LIQUIDCASE returns; no accrual",
    "E11": "constant mix at each rule's own average shares: parent f_p = mean of e over the weekly decisions, GOLDBEES f_g, cash f_c and each index f_i = the means of the rule's target shares; rebalanced at every decision "
           "date's next session and at every basket change while f_p > 0 (T14 E11 generalised); initial stock holding = drifted basket scaled by f_p",
    "E12": "R3: W1 starts at the first D26 session on or after 2015-01-02, W2 'live' at the first D17 session on or after 2021-11-01, each with its own first state (both start in OUT-SELL, so -idx starts holding cash and "
           "the indices of B at their closes)",
    "E13": "ledger span (T15.md 2.4, 'first fill to last fill'): a = the session on which the first decision of the span is traded (the session after it; T0 for the window's first decision), b = the session on which the "
           "decision that ends the span is traded (or the last session); returns are close[b] / close[a] - 1 of each instrument and of each rule's 20.8 bps NAV (parent = hold-parent 0-cost NAV)",
    "E14": "R4: for each OUT-SELL spell s, -idx runs with B = empty (its target is -liq's) on the decisions of spell s only; every other week is the real rule; 20.8 bps, full window, LBES",
    "E15": "R5: every index's OHLC4 and close of session i (i = 0 at T0 on the book's calendar) multiplied by (1 - 0.005 / 252)^i, for -idx and every other rule (the others hold no index); 20.8 bps",
    "E16": "index bars: a calendar session with no bar carries the last close (marking only); counted per index; a trade that involves an index line on such a session stops the run",
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


# ── regimes and targets (T15.md 2.1) ─────────────────────────────────────────
def targets(rule: str, st: int, g: int) -> tuple[float, float]:
    """(e, gw) for one decision of a T14 rule (the six -orig / -half / -liq rules). st = 1 IN, g = 1 gold BUY. gw while IN is carried and never traded on."""
    base, kind = rule.split("-")
    assert kind in ("orig", "half", "liq"), rule
    gw_out = 0.5 if base == "50" else (GW_BUY if g else GW_SELL)
    if st == 1:
        return 1.0, gw_out
    if g == 0 and kind == "half":
        return 0.5, 1.0
    if g == 0 and kind == "liq":
        return 0.0, 0.0
    return 0.0, gw_out


def targets_idx(rule: str, st: int, g: int, B: tuple) -> dict:
    """Scalar target of a -idx rule for one decision: shares of parent / GOLDBEES / cash and a dict of index shares. B = tuple of the indices whose own SIGN is BUY."""
    base, kind = rule.split("-")
    assert kind == "idx", rule
    if st == 1:
        return {"e": 1.0, "gold": 0.0, "cash": 0.0, "idx": {n: 0.0 for n in INDICES}}
    if g == 1:
        gw = 0.5 if base == "50" else GW_BUY
        return {"e": 0.0, "gold": (1 - 0.0) * gw, "cash": (1 - 0.0) * (1 - gw), "idx": {n: 0.0 for n in INDICES}}
    sh = 1.0 / (len(B) + 1)
    return {"e": 0.0, "gold": 0.0, "cash": sh, "idx": {n: (sh if n in B else 0.0) for n in INDICES}}


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


def rule_targets(rule: str, s, g, Bm) -> dict:
    """Vectorised targets per decision: e, gw (T14's, for the trigger), gold, cash (absolute shares), iw (J, 3) absolute index shares. Bm (J, 3) bool = the indices whose own SIGN is BUY.
    The six T14 rules: gold = (1-e)*gw, cash = (1-e)*(1-gw), iw = 0 (so `trade` does T14's arithmetic exactly). -idx: IN parent; OUT-BUY the base sleeve; OUT-SELL cash and each index of B at 1/(k+1)."""
    s, g = np.asarray(s).astype(int), np.asarray(g).astype(int)
    Bm = np.asarray(Bm).astype(bool)
    J = len(s)
    base, kind = rule.split("-")
    gw = np.full(J, 0.5) if base == "50" else np.where(g == 1, GW_BUY, GW_SELL).astype(float)
    e = np.where(s == 1, 1.0, 0.0)
    sell = (s == 0) & (g == 0)
    if kind == "half":
        e, gw = np.where(sell, 0.5, e), np.where(sell, 1.0, gw)
    elif kind == "liq":
        gw = np.where(sell, 0.0, gw)
    gold, cash = (1 - e) * gw, (1 - e) * (1 - gw)
    iw = np.zeros((J, 3))
    if kind == "idx":
        sh = 1.0 / (Bm.sum(axis=1) + 1)
        gold = np.where(sell, 0.0, gold)
        cash = np.where(sell, sh, cash)
        iw = np.where(sell[:, None], Bm * sh[:, None], 0.0)
    return {"e": e, "gw": gw, "gold": gold, "cash": cash, "iw": iw}


def due_list(rule: str, idx, T: int, tg: dict, s, g, Bm) -> list[int]:
    """Decisions j >= 1 whose trade session exists and whose target differs from j-1's. T14's trigger for the six T14 rules; for -idx the target key (IN / OUT-BUY / OUT-SELL with B)."""
    if not rule.endswith("-idx"):
        return trades_due(idx, T, tg["e"], tg["gw"])
    reg = regime_codes(s, g)
    key = [("IN",) if r == 0 else (("OB",) if r == 1 else ("OS",) + tuple(int(x) for x in np.flatnonzero(Bm[j]))) for j, r in enumerate(reg)]
    return [j for j in range(1, len(idx)) if int(idx[j]) + 1 < T and key[j] != key[j - 1]]


# ── approved raw inputs ───────────────────────────────────────────────────────
_COMMON: dict = {}


def common(win: str) -> dict:
    """Calendar (W1: D26), the three D03 Master files (SIGN and Index), the window's MAUc1 Master / weekly csv / daily range, GOLDBEES (D09) with the de-spike, cash (D11); everything cut at the window's END."""
    if win in _COMMON:
        return _COMMON[win]
    W = WINDOWS[win]
    key = end_of(win)
    cal_all = None
    if W["cal"] == "d26":
        cal_all = pd.DatetimeIndex(sorted(pd.to_datetime(pd.read_csv(ap(CAL_FILE))["date"])))
        assert cal_all.is_unique and cal_all.max() >= key, f"D26 ends {cal_all.max().date()} before {key.date()}"
    ms, mi, rows_after = {}, {}, {}
    for n in INDICES:
        p = ap(MASTER_DIR / f"Master_{n}.xlsx")
        if n == "SC100":
            AD.guard_window(p, SC_USABLE_FROM)
        d = pd.read_excel(p, parse_dates=["Date"])
        d = d.dropna(subset=["SIGN"]).set_index("Date").sort_index()
        d = d[~d.index.duplicated(keep="last")]
        assert d.index.max() >= key, f"{n}: Master ends {d.index.max().date()} before {key.date()}"
        rows_after[n] = int((d.index > key).sum())
        d = d[d.index <= key]
        if n == "SC100":
            d = d[d.index >= SC_USABLE_FROM]                   # rule 7: nothing before the usable-from date is kept
        s = d["SIGN"]
        assert set(s.unique()) <= {"BUY", "SELL"}
        ms[n] = s
        mi[n] = d["Index"].astype(float)
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
    _COMMON[win] = dict(cal_all=cal_all, master=ms, master_index=mi, master_rows_after_end=rows_after, gold_master=gs, gold_master_rows_after_end=gm_after, gold_weekly=wk, mcx_daily=m,
                        gclose=g["close"][g.index <= key], gfill=gfill[gfill.index <= key], norange=norange[norange <= key], lbes=lb[lb.index <= key], liq=lq[lq.index <= key],
                        lbes_last=lb.index.max(), liq_last=lq.index.max(), gold_last=g.index.max(), mcx_last=m.index.max(), gold_first=g.index.min(), end=key)
    return _COMMON[win]


_IBARS: dict = {}


def index_bars(win: str) -> dict:
    """The three indices' daily bars (open, high, low, close) from the window's own approved file (W1 D25, W2 D25c), cut at END, plus `tie` = the same closes from D25 (+ D25c in W2) over the whole
    history, used only by the V3 tie to the Master `Index` column (a label can fall before the window's first session). Every bar must be finite and positive."""
    if win in _IBARS:
        return _IBARS[win]
    W, end = WINDOWS[win], end_of(win)
    t0 = W["t0"] if W["t0"] is not None else pd.Timestamp("2019-01-02")
    bars, tie = {}, {}
    for n in INDICES:
        p = ap(W["idx_dir"] / f"{n}_daily_ohlcv.csv")
        if n == "SC100":
            AD.guard_window(p, t0 if win == "w1" else pd.Timestamp("2019-01-01"))
        d = pd.read_csv(p, parse_dates=["date"]).set_index("date").sort_index()
        assert d.index.is_unique and set(["open", "high", "low", "close"]) <= set(d.columns)
        d = d[["open", "high", "low", "close"]].astype(float)
        assert np.isfinite(d.values).all() and (d.values > 0).all(), f"{n}: a non-finite or non-positive index price"
        if win == "w2":
            assert d.index.max() >= end, f"{n}: D25c ends {d.index.max().date()} before {end.date()}"
        d = d[d.index <= end]
        bars[n] = d
        if win == "w1":
            tie[n] = d["close"]
        else:
            p0 = ap(IDX_DIR / f"{n}_daily_ohlcv.csv")
            if n == "SC100":
                AD.guard_window(p0, SC_USABLE_FROM)
            d0 = pd.read_csv(p0, parse_dates=["date"]).set_index("date").sort_index()["close"].astype(float)
            d0 = d0[d0.index < d.index.min()]
            tie[n] = pd.concat([d0, d["close"]])
    _IBARS[win] = {"bars": bars, "tie": tie}
    return _IBARS[win]


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
    """Everything a run needs for one parent and one window, as plain arrays on the calendar (T14's Book plus the three index lines).
    idx_mode: 'real' = the index prices; 'cash' = every index priced as the cash level (V4(b)); 'drag' = R5, every index price times (1 - 0.005/252)^i."""

    def __init__(self, parent: str, win: str, start: pd.Timestamp | None = None, cash: str = "lbes", idx_mode: str = "real"):
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
        # index lines (E6, E16): marking at the close (the last close carried on a session without a bar), fills at the bar's OHLC4
        ib = index_bars(win)["bars"]
        self.I, self.IP = np.zeros((self.T, 3)), np.zeros((self.T, 3))
        self.i_nobar = np.zeros((self.T, 3), dtype=bool)
        for k, n in enumerate(INDICES):
            d = ib[n]
            iu = cal.union(d.index)
            cl = d["close"].reindex(iu).ffill().reindex(cal)
            assert cl.notna().all(), f"{n}: no index bar on or before {cal[0].date()}"
            o4 = ((d["open"] + d["high"] + d["low"] + d["close"]) / 4).reindex(cal)
            self.i_nobar[:, k] = ~np.asarray(cal.isin(d.index))
            self.I[:, k] = cl.values
            self.IP[:, k] = o4.fillna(cl).values
        self.index_nobar_sessions = {n: [str(d.date()) for d in cal[self.i_nobar[:, k]]] for k, n in enumerate(INDICES)}
        self.idx_mode = idx_mode
        if idx_mode == "cash":
            self.I = np.repeat(self.L[:, None], 3, axis=1)
            self.IP = self.I.copy()
            self.i_nobar = np.zeros((self.T, 3), dtype=bool)
        elif idx_mode == "drag":
            f = (1 - DRAG_PER_YEAR / 252) ** np.arange(self.T)
            self.I = self.I * f[:, None]
            self.IP = self.IP * f[:, None]
        else:
            assert idx_mode == "real"
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
            Bt = tuple(n for n in INDICES if lab[n][1] == "BUY")
            row = {"book": self.parent, "window": self.win, "j": j, "decision_date": d.date(), "decision_idx": int(i),
                   "trade_date": (cal[i + 1].date() if i + 1 < self.T else None),
                   **{f"sign_{n}": v[1] for n, v in lab.items()}, **{f"label_{n}": v[0].date() for n, v in lab.items()},
                   "latest_label": ld.date(), "label_age_days": (d - min(v[0] for v in lab.values())).days,
                   "all_three_buy": bool(state), "state": int(state),
                   "sign_MAUc1": sign_g, "label_MAUc1": lab_g.date(), "g": gg, "regime": REG_NAMES[int(regime_codes([state], [gg])[0])],
                   **{f"buy_{n}": int(n in Bt) for n in INDICES}, "B": ("+".join(Bt) if Bt else "cash"), "k": len(Bt)}
            for rule in T14_RULES:
                e_, gw_ = targets(rule, state, gg)
                row[f"e_{rule}"], row[f"gw_{rule}"] = e_, gw_
            for rule in IDX_RULES:
                t = targets_idx(rule, state, gg, Bt)
                row[f"e_{rule}"], row[f"gold_{rule}"], row[f"cash_{rule}"] = t["e"], t["gold"], t["cash"]
                for n in INDICES:
                    row[f"w_{n}_{rule}"] = t["idx"][n]
            rows.append(row)
        return pd.DataFrame(rows)


def arrays_of(dec: pd.DataFrame):
    return dec["state"].values.astype(int), dec["g"].values.astype(int), dec[[f"buy_{n}" for n in INDICES]].values.astype(bool)


# ── simulation ────────────────────────────────────────────────────────────────
def trade(bk: Book, t: int, tgt, u, gu, cu, iu, ow: float):
    """T14's `trade` generalised to index lines. tgt = (e, gold share, cash share, index shares (3,)). At the session's fill prices (stocks OHLC4, GOLDBEES de-spiked OHLC4, cash at its level, each
    index at its own OHLC4) V = value of every line; target value of each line = share x V; traded = sum |target - held| over every line; cost = ow x traded; every target scaled by (V - cost) / V."""
    e_new, gold_new, cash_new, iw_new = tgt
    ps, gp, lv, ip = bk.P[t], bk.gf[t], bk.L[t], bk.IP[t]
    held_s = u * ps
    held_i = iu * ip
    V = held_s.sum() + gu * gp + cu * lv + held_i.sum()
    w = bk.W[bk.basket_at[t]]
    Te = e_new * V * w
    Tg = gold_new * V
    Tc = cash_new * V
    Ti = iw_new * V
    involved = (Ti > 0) | (held_i > 0)
    assert not (involved & bk.i_nobar[t]).any(), f"an index line is traded on session {bk.cal[t].date()} without an index bar"
    nb = int((bk.nobar[t] & ((Te > 0) | (held_s > 0))).sum())
    bk.nobar_trades += nb
    gold_traded = abs(Tg - gu * gp) > 0
    if gold_traded and bk.gold_norange[t]:
        bk.gold_norange_trades += 1
    if gold_traded and bk.gold_nobar[t]:
        bk.gold_nobar_trades += 1
    traded = np.abs(Te - held_s).sum() + abs(Tg - gu * gp) + abs(Tc - cu * lv) + np.abs(Ti - held_i).sum()
    cost = ow * traded
    k = (V - cost) / V
    new_u = np.zeros_like(u)
    pos = (Te > 0) & (ps > 0)
    assert not ((Te > 0) & (ps <= 0)).any(), f"no price for a stock to buy at session {bk.cal[t].date()}"
    new_u[pos] = k * Te[pos] / ps[pos]
    ngu, ncu = k * Tg / gp, k * Tc / lv
    new_iu = np.where(Ti > 0, k * Ti / ip, 0.0)
    va = new_u * ps
    stock_after = float(va.sum())
    idx_after = new_iu * ip
    return new_u, ngu, ncu, new_iu, dict(V=V, traded=traded, cost=cost, stock_before=float(held_s.sum()), gold_before=float(gu * gp), cash_before=float(cu * lv),
                                         idx_before=held_i.copy(), stock_after=stock_after, gold_after=float(ngu * gp), cash_after=float(ncu * lv), idx_after=idx_after.copy(),
                                         V_after=stock_after + float(ngu * gp) + float(ncu * lv) + float(idx_after.sum()),
                                         weight_gap=float(np.abs(va / stock_after - w).max()) if stock_after > 0 else 0.0, held_before=held_s, val_after=va,
                                         nobar_stocks=nb, gold_norange=bool(gold_traded and bk.gold_norange[t]), gold_nobar=bool(gold_traded and bk.gold_nobar[t]))


def trade_basket_partial(bk: Book, t: int, u, gu, cu, iu, ow: float):
    """D1 (T14.md 3 step 6): a parent rebalance while 0 < e < 1 (the -half comparators). Only the stock part is re-weighted to the new basket at its current value S; GOLDBEES, cash and index units
    are unchanged; cost = ow x sum|S w_i - held_i| on the stock lines, taken from the stock part: units_i = (S - cost) w_i / p_i."""
    ps, gp, lv, ip = bk.P[t], bk.gf[t], bk.L[t], bk.IP[t]
    held_s = u * ps
    S = float(held_s.sum())
    held_i = iu * ip
    V = S + gu * gp + cu * lv + float(held_i.sum())
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
    return new_u, gu, cu, iu, dict(V=V, traded=traded, cost=cost, stock_before=S, gold_before=float(gu * gp), cash_before=float(cu * lv), idx_before=held_i.copy(),
                                   stock_after=stock_after, gold_after=float(gu * gp), cash_after=float(cu * lv), idx_after=held_i.copy(),
                                   V_after=stock_after + float(gu * gp) + float(cu * lv) + float(held_i.sum()),
                                   weight_gap=float(np.abs(va / stock_after - w).max()) if stock_after > 0 else 0.0, held_before=held_s, val_after=va,
                                   nobar_stocks=nb, gold_norange=False, gold_nobar=False)


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


def simulate(bk: Book, idx: np.ndarray, tg: dict, cost_bps: float, due, record: bool = False, reg: np.ndarray | None = None, every: bool = False):
    """tg = rule_targets(...) (or a constant mix): per decision j the shares e, gold, cash, iw. A trade is due on the session after decision j for j in `due` (every decision from j = 0 if `every`).
    reg (per decision: 0 IN, 1 OUT-BUY, 2 OUT-SELL) is passed for every rule except -orig and the constant mixes: it labels regime_in / regime_out / index_set_change trades and switches on the D1
    partial trade for a parent rebalance while 0 < e < 1. Returns daily NAV (length T) and, if record, the trade and position logs."""
    T, ow = bk.T, cost_bps / 2e4
    E, GO, CA, IW = tg["e"], tg["gold"], tg["cash"], tg["iw"]
    cur = (float(E[0]), float(GO[0]), float(CA[0]), np.array(IW[0], dtype=float))
    u = bk.u0 * cur[0]
    gu = cur[1] / bk.g[0]
    cu = cur[2] / bk.L[0]
    iu = cur[3] / bk.I[0]
    tgt = {}
    for j in (range(0, len(idx)) if every else due):
        tr = int(idx[j]) + 1
        if tr < T:
            tgt[tr] = j
    ev = sorted(set(tgt) | bk.basket_events)
    nav = np.empty(T)
    nz = np.flatnonzero(u)
    a = 0
    trades, pos_log = [], []

    def seg(x, y):
        v = bk.C[x:y][:, nz] @ u[nz] + bk.g[x:y] * gu + bk.L[x:y] * cu if len(nz) else bk.g[x:y] * gu + bk.L[x:y] * cu
        return v + bk.I[x:y] @ iu

    for t in ev:
        if t > a:
            nav[a:t] = seg(a, t)
        a = t
        if t in tgt or (t in bk.basket_events and cur[0] > 0):
            jd = tgt.get(t)
            partial = bool(jd is None and reg is not None and 0 < cur[0] < 1)
            new = (float(E[jd]), float(GO[jd]), float(CA[jd]), np.array(IW[jd], dtype=float)) if jd is not None else cur
            if partial:
                kind = "basket_change"
                u, gu, cu, iu, info = trade_basket_partial(bk, t, u, gu, cu, iu, ow)
            else:
                if jd is not None and reg is not None and jd >= 1 and (reg[jd] == 2) != (reg[jd - 1] == 2):
                    kind = "regime_in" if reg[jd] == 2 else "regime_out"
                elif jd is not None and reg is not None and jd >= 1 and reg[jd] == 2 and reg[jd - 1] == 2 and not np.array_equal(IW[jd], IW[jd - 1]):
                    kind = "index_set_change"
                else:
                    kind = ("switch_in" if new[0] > cur[0] else "switch_out" if new[0] < cur[0] else
                            (("mix_rebalance" if every else "sleeve_rebalance") if jd is not None else "basket_change"))
                u, gu, cu, iu, info = trade(bk, t, new, u, gu, cu, iu, ow)
            cur = new
            nz = np.flatnonzero(u)
            if record:
                nav_close = float((bk.C[t][nz] @ u[nz] if len(nz) else 0.0) + gu * bk.g[t] + cu * bk.L[t] + bk.I[t] @ iu)
                trades.append({"date": bk.cal[t].date(), "idx": t, "kind": kind, "e_after": cur[0], "gold_share": cur[1], "cash_share": cur[2],
                               **{f"w_{n}": float(cur[3][q]) for q, n in enumerate(INDICES)}, "basket_eff": bk.eff[bk.basket_at[t]].date(),
                               **{k_: v for k_, v in info.items() if k_ not in ("idx_before", "idx_after")},
                               **{f"{n}_before": float(info["idx_before"][q]) for q, n in enumerate(INDICES)}, **{f"{n}_after": float(info["idx_after"][q]) for q, n in enumerate(INDICES)},
                               "nav_close_after": nav_close, "dec_j": jd})
                for i in nz:
                    pos_log.append({"date": bk.cal[t].date(), "instrument": bk.stocks[i], "units": u[i]})
                if gu > 0:
                    pos_log.append({"date": bk.cal[t].date(), "instrument": "GOLDBEES", "units": gu})
                if cu > 0:
                    pos_log.append({"date": bk.cal[t].date(), "instrument": "LBES", "units": cu})
                for q, n in enumerate(INDICES):
                    if iu[q] > 0:
                        pos_log.append({"date": bk.cal[t].date(), "instrument": f"IDX_{n}", "units": iu[q]})
    nav[a:T] = seg(a, T)
    return (nav, trades, pos_log) if record else nav


def const_targets(e: float, gold: float, cash: float, iw, J: int) -> dict:
    return {"e": np.full(J, e), "gold": np.full(J, gold), "cash": np.full(J, cash), "iw": np.tile(np.asarray(iw, dtype=float), (J, 1)), "gw": np.full(J, 0.5)}


def held_either(bk: Book) -> np.ndarray:
    """(T, N) bool: the stock has weight > 0 in the basket in force on session t-1 or on session t (t = 0: session 0 only)."""
    held = bk.W[bk.basket_at] > 0
    prev = np.vstack([held[:1], held[:-1]])
    return held | prev


def one_instrument_identity(bk: Book) -> dict:
    """V4(f): the engine on a one-instrument book (weight 1 on one stock in every basket, always in, 0 cost) reproduces that stock's close / first close, for every stock of the T0 basket."""
    r = raw_parent(bk.parent, bk.end)
    union = bk.cal.union(r["close_raw"].index)
    worst, n = {}, 0
    tg = const_targets(1.0, 0.0, 0.0, [0, 0, 0], 1)
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
        nv = simulate(b1, np.array([0]), tg, 0.0, [])
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


# ── runs ──────────────────────────────────────────────────────────────────────
def stretches(Bm_slice) -> list[tuple[int, int]]:
    """[(first, last)] offsets of maximal runs of an unchanged B within a slice of decisions."""
    out, a = [], 0
    for q in range(1, len(Bm_slice) + 1):
        if q == len(Bm_slice) or not np.array_equal(Bm_slice[q], Bm_slice[a]):
            out.append((a, q - 1))
            a = q
    return out


def bname(row) -> str:
    n = [x for x, f in zip(INDICES, row) if f]
    return "+".join(n) if n else "cash"


def regime_ledger(bk: Book, dec: pd.DataFrame, navs: dict, hold: np.ndarray, win: str) -> list[dict]:
    """E13: one row per OUT-SELL spell and one per B stretch inside it. Span: a = the session on which the first decision of the span is traded (T0 for decision 0), b = the session on which the decision
    that ends the span is traded (the last session if none)."""
    idx = dec["decision_idx"].values
    s, g, Bm = arrays_of(dec)
    reg = regime_codes(s, g)
    J = len(idx)

    def span(j0, j1):
        a = 0 if j0 == 0 else min(int(idx[j0]) + 1, bk.T - 1)
        b = min(int(idx[j1 + 1]) + 1, bk.T - 1) if j1 + 1 < J else bk.T - 1
        return a, b

    def row(level, spell_no, stretch_no, j0, j1):
        a, b = span(j0, j1)
        Bj = Bm[j0]
        r = {"window": win, "book": bk.parent, "level": level, "spell_no": spell_no, "stretch_no": stretch_no, "B": bname(Bj), "k": int(Bj.sum()),
             "first_decision": str(bk.cal[int(idx[j0])].date()), "last_decision": str(bk.cal[int(idx[j1])].date()), "weeks": j1 - j0 + 1,
             "a_session": str(bk.cal[a].date()), "b_session": str(bk.cal[b].date()),
             "entered_from": REG_NAMES[reg[j0 - 1]] if j0 > 0 else "start", "exited_to": REG_NAMES[reg[j1 + 1]] if j1 + 1 < J else "window end",
             "parent_return": float(hold[b] / hold[a] - 1), "goldbees_return": float(bk.g[b] / bk.g[a] - 1), "cash_return": float(bk.L[b] / bk.L[a] - 1),
             **{f"{n}_return": float(bk.I[b, q] / bk.I[a, q] - 1) for q, n in enumerate(INDICES)}}
        for rule in RULES:
            r[f"ret_{rule}"] = float(navs[rule][b] / navs[rule][a] - 1)
        return r

    rows = []
    for k, (j0, j1) in enumerate(out_sell_spells(reg)):
        rows.append(row("spell", k + 1, 0, j0, j1))
        for m, (x, y) in enumerate(stretches(Bm[j0:j1 + 1])):
            rows.append(row("stretch", k + 1, m + 1, j0 + x, j0 + y))
    return rows


def sessions_by_state(bk: Book, dec: pd.DataFrame) -> dict:
    """Sessions in each regime and, in OUT-SELL, in each k, counted from the session on which the decision's target is held (decision j from the session after it; decision 0 from T0) to the decision
    session of j+1 inclusive."""
    idx = dec["decision_idx"].values
    s, g, Bm = arrays_of(dec)
    reg = regime_codes(s, g)
    k = Bm.sum(axis=1)
    out = {"IN": 0, "OUT-BUY": 0, "OUT-SELL": 0, "OUT-SELL_k0": 0, "OUT-SELL_k1": 0, "OUT-SELL_k2": 0}
    for j in range(len(idx)):
        a = 0 if j == 0 else int(idx[j]) + 1
        b = int(idx[j + 1]) if j + 1 < len(idx) else bk.T - 1
        n = max(0, b - a + 1)
        out[REG_NAMES[reg[j]]] += n
        if reg[j] == 2:
            out[f"OUT-SELL_k{int(k[j])}"] += n
    return out


def run_book(bk: Book, dec: pd.DataFrame, window: str, variant: str, costs: tuple, out: dict, headline: bool, spell_cash=None):
    """Real rules (all eight) at each cost; with `headline`: records trades / positions / NAVs, comparators, constant mixes and the ledger. `spell_cash` = (j0, j1): -idx holds B = empty on those decisions
    (R4)."""
    idx = dec["decision_idx"].values
    s, g, Bm = arrays_of(dec)
    reg = regime_codes(s, g)
    Bu = Bm.copy()
    if spell_cash is not None:
        Bu[spell_cash[0]:spell_cash[1] + 1] = False
    T = bk.T

    def stat_row(name, cost, nv, tr):
        assert np.isfinite(nv).all() and (nv > 0).all(), f"{name}: a NAV is not finite and positive"
        return {"book": bk.parent, "window": window, "variant": variant, "cash": bk.cash_info["cash"], "cost_bps": cost, "run": name, **stats(nv), "trades": len(tr),
                "cost_paid": sum(t["cost"] for t in tr), "regime_trades": sum(1 for t in tr if t["kind"] in ("regime_in", "regime_out")),
                "index_set_trades": sum(1 for t in tr if t["kind"] == "index_set_change"), "basket_trades": sum(1 for t in tr if t["kind"] == "basket_change"),
                "switch_trades": sum(1 for t in tr if t["kind"] in ("switch_in", "switch_out")), "sleeve_trades": sum(1 for t in tr if t["kind"] == "sleeve_rebalance")}

    def keep(name, cost, tr, pos, nav):
        if headline:
            out["trades"] += [{"book": bk.parent, "window": window, "cost_bps": cost, "run": name, **t} for t in tr]
            if pos is not None:
                out["positions"] += [{"book": bk.parent, "window": window, "cost_bps": cost, "run": name, **p} for p in pos]
            out["nav"][(bk.parent, cost, name)] = nav
        else:
            out["vnav"][(bk.parent, window, variant, cost, name)] = nav

    rules = IDX_RULES if variant.startswith("r4") else RULES
    navs20, tgs = {}, {}
    for cost in costs:
        for rule in rules:
            tg = rule_targets(rule, s, g, Bu if rule.endswith("idx") else Bm)
            due = due_list(rule, idx, T, tg, s, g, Bu if rule.endswith("idx") else Bm)
            nav, tr, pos = simulate(bk, idx, tg, cost, due, record=True, reg=(None if rule.endswith("orig") else reg))
            out["rows" if headline else "vrows"].append(stat_row(rule, cost, nav, tr))
            if cost == PRIMARY:
                navs20[rule] = nav
                tgs[rule] = (tg, due)
            for t in tr:
                if t["dec_j"] is not None:
                    assert t["idx"] > idx[t["dec_j"]], "V2: a trade is not after its decision"
                    out["v2_trades"] += 1
                else:
                    assert bk.cal[t["idx"]] == bk.cal[bk.bidx[bk.basket_at[t["idx"]]]] and bk.cal[t["idx"]] >= bk.eff[bk.basket_at[t["idx"]]], "V2: a basket change is not on its availableDate's session"
                    out["v2_basket_trades"] += 1
            keep(rule, cost, tr, pos if cost == PRIMARY else None, nav)
    if not headline:
        return navs20
    onetg = const_targets(1.0, 0.0, 0.0, [0, 0, 0], len(idx))
    for cost in costs:
        nvh, trh, _ = simulate(bk, idx, onetg, cost, [], record=True)
        out["rows"].append(stat_row("hold_parent", cost, nvh, trh))
        keep("hold_parent", cost, trh, None, nvh)
        if cost == 0.0:
            hold0 = nvh
    for q, n in enumerate(INDICES):
        nv = bk.I[:, q] / bk.I[0, q]
        out["rows"].append(stat_row(f"hold_{n}", PRIMARY, nv, []))
        out["nav"][(bk.parent, PRIMARY, f"hold_{n}")] = nv
    f_of = {}
    for rule in RULES:
        tg, _ = tgs[rule]
        fp, fg, fc, fi = float(tg["e"].mean()), float(tg["gold"].mean()), float(tg["cash"].mean()), tg["iw"].mean(axis=0)
        f_of[rule] = {"f_parent": fp, "f_goldbees": fg, "f_cash": fc, **{f"f_{n}": float(fi[q]) for q, n in enumerate(INDICES)}}
        ct = const_targets(fp, fg, fc, fi, len(idx))
        nv, tr2, _ = simulate(bk, idx, ct, PRIMARY, [], record=True, every=True)
        out["rows"].append(stat_row(f"cmix_{rule}", PRIMARY, nv, tr2))
        out["nav"][(bk.parent, PRIMARY, f"cmix_{rule}")] = nv
    out["cmix_params"][bk.parent] = f_of
    out["ledger"] += regime_ledger(bk, dec, navs20, out["nav"][(bk.parent, 0.0, "hold_parent")], window)
    return navs20


# ── gates ─────────────────────────────────────────────────────────────────────
def shared_code_diff() -> dict:
    """V4(d): functions shared with t14_engine.py. Identical = the same AST (docstrings included); the changed ones must be the expected ones."""
    def fns(path):
        tree = ast.parse(Path(path).read_text(encoding="utf-8"))
        return {n.name: ast.dump(n) for n in tree.body if isinstance(n, ast.FunctionDef)}
    a, b = fns(T14_ENGINE), fns(Path(__file__))
    must_equal = ["sha", "regime_codes", "trades_due", "out_sell_spells", "read_pub", "raw_parent", "cash_levels", "stats", "held_either", "baskets_table", "held_src_counts"]
    expected_changed = ["ap", "targets", "common", "simulate", "trade", "trade_basket_partial", "one_instrument_identity", "run_book", "regime_ledger", "main", "shared_code_diff", "g0_check", "seam_2019",
                        "regression_nav", "v4_identities", "window_check", "process_book", "run_window", "data_selftest", "build_counts", "end_of"]
    changed = [n for n in sorted(set(a) & set(b)) if a[n] != b[n]]
    unexpected = [n for n in changed if n not in expected_changed]
    not_equal_required = [n for n in must_equal if n not in a or n not in b or a[n] != b[n]]
    return {"compared_with_t14": must_equal, "required_not_identical": not_equal_required, "changed_functions": changed, "unexpected_changes": unexpected, "expected_changes": expected_changed,
            "dropped_from_t14": sorted(set(a) - set(b)), "new_in_t15": sorted(set(b) - set(a)), "pass": bool(not not_equal_required and not unexpected)}


def g0_check(bk: Book) -> dict:
    """V4(f) / G0: always-in 0-cost NAV on the book's D17 dates against the published NAV: the overall gap in pp / yr and every calendar year's gap in pp."""
    nav = simulate(bk, np.array([0]), const_targets(1.0, 0.0, 0.0, [0, 0, 0], 1), 0.0, [])
    c = pd.DataFrame({"m": nav, "p": bk.pub}, index=bk.cal)
    yrs = (len(c) - 1) / 252
    overall = float(((c.m.iloc[-1] / c.m.iloc[0]) ** (1 / yrs) - (c.p.iloc[-1] / c.p.iloc[0]) ** (1 / yrs)) * 100)
    yearly = {}
    prev = c.iloc[0]
    for y, grp in c.groupby(c.index.year):
        last = grp.iloc[-1]
        yearly[int(y)] = float((last.m / prev.m - 1 - (last.p / prev.p - 1)) * 100)
        prev = last
    ok = bool(abs(overall) <= G0_OVERALL and all(abs(v) <= G0_YEARLY for v in yearly.values()))
    return {"first": str(c.index[0].date()), "last": str(c.index[-1].date()), "overall_pp_per_year": overall, "yearly_pp": yearly, "year_2019_gap_pp": yearly.get(2019, float("nan")),
            "limits": {"overall_pp_per_year": G0_OVERALL, "each_year_pp": G0_YEARLY}, "pass": ok}


def seam_2019(p: str) -> dict:
    """W1's V4(f): the always-in 0-cost NAV on D17's dates 2019-01-02 -> 2019-12-31 against the published NAV (limit +-0.5 pp over the year), from the W2 book's path."""
    bk = Book(p, "w2")
    nav = simulate(bk, np.array([0]), const_targets(1.0, 0.0, 0.0, [0, 0, 0], 1), 0.0, [])
    c = pd.DataFrame({"m": nav, "p": bk.pub}, index=bk.cal)
    c = c[c.index <= pd.Timestamp("2019-12-31")]
    c = c / c.iloc[0] * 100
    gap = float((c.m.iloc[-1] / c.m.iloc[0] - c.p.iloc[-1] / c.p.iloc[0]) * 100)
    return {"first": str(c.index[0].date()), "last": str(c.index[-1].date()), "year_gap_pp": gap, "limit_pp": 0.5, "pass": bool(abs(gap) <= 0.5)}


def regression_nav(win: str, books, out: dict, bks: dict, decs: dict) -> dict:
    """V4(a): the six T14 rules (and hold-the-parent) reproduce T14's stored daily_nav.csv to relative 1e-12 at every cost, every trade of theirs equals T14's stored trades.csv (date, kind, V, traded,
    cost, stock / gold / cash before and after), and the decisions equal T14's stored decisions.csv (state, g, decision_idx, the three signs)."""
    W = WINDOWS[win]
    res = {"reference": "T14", "rows": [], "trades": [], "decisions": {}, "tolerance_rel": REL_TOL_NAV}
    ref_nav = pd.read_csv(W["t14_dir"] / "daily_nav.csv")
    ref_dec = pd.read_csv(W["t14_dir"] / "decisions.csv")
    ref_tr = pd.read_csv(W["t14_dir"] / "trades.csv")
    ok = True
    names = T14_RULES + ["hold_parent"]
    for p in books:
        d = decs[p]
        b = ref_dec[ref_dec["book"] == p]
        mine = d.assign(decision_date=d["decision_date"].astype(str))
        cols = ["decision_idx", "state", "g", "sign_Nifty100", "sign_MC100", "sign_SC100", "sign_MAUc1"]
        m = mine[["decision_date"] + cols].merge(b[["decision_date"] + cols], on="decision_date", how="left", suffixes=("", "_old"))
        hit = m["state_old"].notna()
        mism = int(sum(int((m[c] != m[c + "_old"])[hit].sum()) for c in cols))
        unmatched = m.loc[~hit, "decision_date"].tolist()
        good = bool(mism == 0 and hit.sum() > 0 and unmatched in ([], [mine["decision_date"].iloc[-1]]))
        res["decisions"][p] = {"compared": int(hit.sum()), "mismatches": mism, "unmatched_dates_in_engine": unmatched, "pass": good}
        ok &= good
        for run in names:
            for cost in COSTS:
                key = (p, cost, run)
                sub = ref_nav[(ref_nav["book"] == p) & (ref_nav["run"] == run) & (ref_nav["cost_bps"] == cost)]
                if key not in out["nav"] or not len(sub):
                    ok = False
                    res["rows"].append({"book": p, "mine": run, "cost_bps": cost, "pass": False, "note": "missing"})
                    continue
                gs = sub.assign(date=pd.to_datetime(sub["date"])).set_index("date")["nav"]
                mv = pd.Series(out["nav"][key], index=bks[p].cal)
                cd = gs.index.intersection(mv.index)
                rel = float((mv.loc[cd] / gs.loc[cd] - 1).abs().max()) if len(cd) else float("nan")
                passed = bool(len(cd) == len(gs) == len(mv) and rel < REL_TOL_NAV)
                ok &= passed
                res["rows"].append({"book": p, "mine": run, "cost_bps": cost, "dates_compared": int(len(cd)), "stored_dates": int(len(gs)), "max_rel_diff": rel, "pass": passed})
                # trades
                st = ref_tr[(ref_tr["book"] == p) & (ref_tr["run"] == run) & (ref_tr["cost_bps"] == cost) & (ref_tr["window"] == "full")].reset_index(drop=True)
                mt = [t for t in out["trades"] if t["book"] == p and t["run"] == run and t["cost_bps"] == cost]
                same_n = len(st) == len(mt)
                worst = 0.0
                kinds_ok = dates_ok = True
                if same_n:
                    for q, t in enumerate(mt):
                        r_ = st.iloc[q]
                        kinds_ok &= (r_["kind"] == t["kind"])
                        dates_ok &= (str(r_["date"]) == str(t["date"]))
                        for c in ("V", "traded", "cost", "stock_before", "gold_before", "cash_before", "stock_after", "gold_after", "cash_after", "nav_close_after"):
                            den = max(abs(float(r_[c])), 1e-300)
                            worst = max(worst, abs(float(t[c]) - float(r_[c])) / den if abs(float(r_[c])) > 1e-12 else abs(float(t[c]) - float(r_[c])))
                tp = bool(same_n and kinds_ok and dates_ok and worst < REL_TOL_NAV)
                ok &= tp
                res["trades"].append({"book": p, "run": run, "cost_bps": cost, "stored_trades": int(len(st)), "mine": int(len(mt)), "kinds_equal": bool(kinds_ok), "dates_equal": bool(dates_ok),
                                      "max_rel_diff": worst, "pass": tp})
    res["rows_compared"] = len(res["rows"])
    res["trade_rows_compared"] = len(res["trades"])
    res["worst_rel_diff"] = max([r["max_rel_diff"] for r in res["rows"] if r.get("max_rel_diff", float("nan")) == r.get("max_rel_diff", float("nan"))] or [float("inf")])
    res["worst_trade_rel_diff"] = max([r["max_rel_diff"] for r in res["trades"]] or [float("inf")])
    res["pass"] = bool(ok and res["rows_compared"] > 0)
    return res


def v4_identities(win: str, books, bks: dict, decs: dict, out: dict, g0s: dict, vb: dict, vc: dict) -> dict:
    """V4 (a) regression against T14, (b) `-idx` equals `-liq` with every index priced as cash at 0 cost, (c) `-idx` equals `-liq` before the first index trade, (d) shared code, (e) signals equal the
    Master / weekly files, (f) one-instrument identity and the seam / G0."""
    c = common(win)
    res = {"a_nav_regression": regression_nav(win, books, out, bks, decs), "b_index_priced_as_cash": vb, "c_idx_equals_liq_before_first_index_trade": vc, "e_signals": {}, "f_one_instrument": {}, "f_g0": g0s}
    ok = bool(res["a_nav_regression"]["pass"]) and all(v["pass"] for v in vb.values()) and all(v["pass"] for v in vc.values())
    for p in books:
        res["f_one_instrument"][p] = one_instrument_identity(bks[p])
        ok &= res["f_one_instrument"][p]["pass"]
        dec = decs[p]
        bad = {"index_sign": 0, "mauc1_sign": 0, "mauc1_weekly_signal": 0, "mauc1_weekly_label": 0, "index_label": 0, "B_vs_signs": 0}
        wk = c["gold_weekly"]
        for r in dec.itertuples():
            d = pd.Timestamp(r.decision_date)
            for n in INDICES:
                sr = c["master"][n]
                got = sr[sr.index <= d]
                bad["index_sign"] += got.iloc[-1] != getattr(r, f"sign_{n}")
                bad["index_label"] += str(got.index[-1].date()) != str(getattr(r, f"label_{n}"))
                bad["B_vs_signs"] += int(getattr(r, f"buy_{n}")) != int(got.iloc[-1] == "BUY")
            gsr = c["gold_master"]
            bad["mauc1_sign"] += gsr[gsr.index <= d].iloc[-1] != r.sign_MAUc1
            k = wk["review"].searchsorted(d, side="right") - 1
            bad["mauc1_weekly_signal"] += int(round(float(wk["signal"].iloc[k]))) != int(r.g)
            bad["mauc1_weekly_label"] += str(wk["review"].iloc[k].date()) != str(r.label_MAUc1)
        tgt_bad = 0
        s_, g_, Bm_ = arrays_of(dec)
        for rule in RULES:
            tg = rule_targets(rule, s_, g_, Bm_)
            for j, (st_, gg_) in enumerate(zip(s_, g_)):
                Bt = tuple(n for q, n in enumerate(INDICES) if Bm_[j, q])
                if rule.endswith("idx"):
                    t = targets_idx(rule, int(st_), int(gg_), Bt)
                    exp = (t["e"], t["gold"], t["cash"], tuple(t["idx"][n] for n in INDICES))
                    got = (float(tg["e"][j]), float(tg["gold"][j]), float(tg["cash"][j]), tuple(float(x) for x in tg["iw"][j]))
                else:
                    e_, gw_ = targets(rule, int(st_), int(gg_))
                    exp = (e_, (1 - e_) * gw_, (1 - e_) * (1 - gw_), (0.0, 0.0, 0.0))
                    got = (float(tg["e"][j]), float(tg["gold"][j]), float(tg["cash"][j]), tuple(float(x) for x in tg["iw"][j]))
                tgt_bad += exp != got
        bad["rule_targets_vs_scalar_targets"] = int(tgt_bad)
        pd_ = bool(all(v == 0 for v in bad.values()) and len(dec) > 0)
        res["e_signals"][p] = {"decisions": int(len(dec)), **{k: int(v) for k, v in bad.items()}, "pass": pd_}
        ok &= pd_
    res["d_shared_code"] = shared_code_diff()
    ok &= res["d_shared_code"]["pass"]
    ok &= all(v["pass"] for v in g0s.values()) if g0s else True
    res["pass"] = bool(ok)
    return res


def v3_index_tie(win: str, books, decs: dict) -> dict:
    """V3: at every weekly decision, the Master row used (label date L) has `Index` equal to the index close of D25 / D25c on L, for all three indices (the tie between the traded prices and the signals)."""
    c = common(win)
    tie = index_bars(win)["tie"]
    checked, bad, nolabel_bar = 0, 0, 0
    seen = set()
    worst = 0.0
    for p in books:
        for r in decs[p].itertuples():
            for n in INDICES:
                L = pd.Timestamp(getattr(r, f"label_{n}"))
                if (n, L) in seen:
                    continue
                seen.add((n, L))
                mi = float(c["master_index"][n].loc[L])
                if L not in tie[n].index:
                    nolabel_bar += 1
                    bad += 1
                    continue
                dif = abs(mi - float(tie[n].loc[L])) / mi
                worst = max(worst, dif)
                checked += 1
                bad += dif > 1e-12
    return {"labels_checked": int(checked), "violations": int(bad), "labels_without_an_index_bar": int(nolabel_bar), "worst_rel_diff": float(worst), "pass": bool(checked > 0 and bad == 0)}


def v5_check(out: dict, books, bks: dict, decs: dict) -> dict:
    """V5 trade and cost identities on every recorded trade of every headline run, and for -idx: after a trade into or inside OUT-SELL each index of B and cash = 1/(k+1) of the value after cost, parent
    and GOLDBEES 0; index lines 0 outside OUT-SELL; the recorded trades equal the expectation from the states alone."""
    TOL = 1e-12
    worst = {"cost_identity": 0.0, "value_conservation": 0.0, "stock_target_gap": 0.0, "gold_target_gap": 0.0, "cash_target_gap": 0.0, "index_target_gap": 0.0, "traded_identity": 0.0,
             "continuity_0cost": 0.0, "stock_weight_gap_after_entry_or_full_basket_change": 0.0, "idx_os_equal_parts_gap": 0.0, "idx_os_parent_gold_after": 0.0, "idx_outside_os_index_after": 0.0}
    n, n0, n_os, n_out = 0, 0, 0, 0
    kinds = Counter()
    for t in out["trades"]:
        V, cost, ow = t["V"], t["cost"], t["cost_bps"] / 2e4
        n += 1
        kinds[(t["run"], t["kind"])] += 1
        worst["cost_identity"] = max(worst["cost_identity"], abs(cost - ow * t["traded"]) / V)
        worst["value_conservation"] = max(worst["value_conservation"], abs(t["V_after"] - (V - cost)) / V)
        if t["cost_bps"] == 0:
            n0 += 1
            worst["continuity_0cost"] = max(worst["continuity_0cost"], abs(t["V_after"] - V) / V)
        e = t["e_after"]
        iw = np.array([t[f"w_{q}"] for q in INDICES])
        idx_after = np.array([t[f"{q}_after"] for q in INDICES])
        partial = t["kind"] == "basket_change" and 0 < e < 1 and t["run"] in ("50-half", "80-half")
        if partial:
            continue
        worst["stock_target_gap"] = max(worst["stock_target_gap"], abs(t["stock_after"] - e * (V - cost)) / V)
        worst["gold_target_gap"] = max(worst["gold_target_gap"], abs(t["gold_after"] - t["gold_share"] * (V - cost)) / V)
        worst["cash_target_gap"] = max(worst["cash_target_gap"], abs(t["cash_after"] - t["cash_share"] * (V - cost)) / V)
        worst["index_target_gap"] = max(worst["index_target_gap"], float(np.abs(idx_after - iw * (V - cost)).max()) / V)
        if t["kind"] in ("switch_in", "basket_change", "mix_rebalance", "regime_in", "regime_out") and e > 0:
            worst["stock_weight_gap_after_entry_or_full_basket_change"] = max(worst["stock_weight_gap_after_entry_or_full_basket_change"], t["weight_gap"])
        if t["run"] in IDX_RULES:
            d = decs[t["book"]].iloc[t["dec_j"]] if t["dec_j"] is not None else None
            if d is not None and d["regime"] == "OUT-SELL":
                n_os += 1
                k = int(d["k"])
                sh = (V - cost) / (k + 1)
                parts = [t["cash_after"]] + [t[f"{q}_after"] for q in INDICES if d[f"buy_{q}"] == 1]
                worst["idx_os_equal_parts_gap"] = max(worst["idx_os_equal_parts_gap"], max(abs(x - sh) for x in parts) / V)
                worst["idx_os_equal_parts_gap"] = max(worst["idx_os_equal_parts_gap"], max([abs(t[f"{q}_after"]) for q in INDICES if d[f"buy_{q}"] == 0] or [0.0]) / V)
                worst["idx_os_parent_gold_after"] = max(worst["idx_os_parent_gold_after"], (abs(t["stock_after"]) + abs(t["gold_after"])) / V)
            else:
                n_out += 1
                worst["idx_outside_os_index_after"] = max(worst["idx_outside_os_index_after"], float(np.abs(idx_after).max()) / V)
    # the recorded trades of every rule equal the expectation from the states alone, at every cost
    count_ok, basket_ok, listed = True, True, {}
    for p in books:
        d, bk = decs[p], bks[p]
        idx = d["decision_idx"].values
        s, g, Bm = arrays_of(d)
        T = bk.T
        for rule in RULES:
            tg = rule_targets(rule, s, g, Bm)
            due = due_list(rule, idx, T, tg, s, g, Bm)
            change = {int(idx[j]) + 1: float(tg["e"][j]) for j in due}
            cur, held_before = float(tg["e"][0]), np.zeros(T)
            for t in range(T):
                held_before[t] = cur
                if t in change:
                    cur = change[t]
            exp_b = sorted(t for t in bk.basket_events if held_before[t] > 0 and t not in set(change))
            for cost in COSTS:
                rec = [t for t in out["trades"] if t["book"] == p and t["run"] == rule and t["cost_bps"] == cost]
                got = sorted(t["idx"] for t in rec if t["kind"] != "basket_change")
                got_b = sorted(t["idx"] for t in rec if t["kind"] == "basket_change")
                count_ok &= got == sorted(change)
                basket_ok &= got_b == exp_b
            listed[f"{p}|{rule}"] = {"regime_switch_sleeve_index_trades": len(due), "basket_changes": len(exp_b)}
    # worked examples: the first book at 20.8 bps
    ex = {}
    p0 = books[0]
    for run in IDX_RULES:
        for kind, cond in (("regime_in", lambda d: int(d["k"]) == 2), ("regime_in_k1", lambda d: int(d["k"]) == 1), ("index_set_change", lambda d: True), ("regime_out", lambda d: True)):
            kk = "regime_in" if kind == "regime_in_k1" else kind
            for t in out["trades"]:
                if t["book"] == p0 and t["run"] == run and t["cost_bps"] == PRIMARY and t["kind"] == kk and t["dec_j"] is not None and cond(decs[p0].iloc[t["dec_j"]]):
                    d = decs[p0].iloc[t["dec_j"]]
                    ex[f"{run}|{kind}"] = {"decision_date": str(d["decision_date"]), "trade_date": str(t["date"]), "idx": t["idx"], "regime": d["regime"], "B": d["B"], "k": int(d["k"]),
                                           "V": t["V"], "traded": t["traded"], "cost": t["cost"], "stock_before": t["stock_before"], "gold_before": t["gold_before"], "cash_before": t["cash_before"],
                                           **{f"{n}_before": t[f"{n}_before"] for n in INDICES}, "stock_after": t["stock_after"], "gold_after": t["gold_after"], "cash_after": t["cash_after"],
                                           **{f"{n}_after": t[f"{n}_after"] for n in INDICES}, "V_after": t["V_after"], "index_fill_prices": {n: float(bks[p0].IP[t["idx"], q]) for q, n in enumerate(INDICES)}}
                    break
    ok = bool(n > 0 and n_os > 0 and all(v <= TOL for v in worst.values()) and count_ok and basket_ok)
    return {"trades_checked": int(n), "trades_checked_at_0_cost": int(n0), "idx_trades_into_or_inside_OUT_SELL_checked": int(n_os), "idx_trades_outside_OUT_SELL_checked": int(n_out),
            "kinds": {f"{a}|{b}": int(c_) for (a, b), c_ in sorted(kinds.items())}, "worst": worst, "tolerance": TOL,
            "recorded_trades_equal_expected_from_states_at_every_cost": bool(count_ok), "basket_changes_equal_expected_at_every_cost": bool(basket_ok), "expected_per_book_rule": listed,
            "worked_examples": ex, "not_checked_here": "weights drift between trades by construction (units are constant between trade sessions); the initial position at T0 is built without a trade record",
            "pass": ok}


def build_counts(bk: Book, dec: pd.DataFrame) -> dict:
    idx = dec["decision_idx"].values
    s, g, Bm = arrays_of(dec)
    reg = regime_codes(s, g)
    sell = out_sell_spells(reg)
    k = Bm.sum(axis=1)
    sell_k = [int(k[j]) for j in range(len(reg)) if reg[j] == 2]
    bch = sum(len(stretches(Bm[a:b + 1])) - 1 for a, b in sell)
    idx_spells = sum(1 for a, b in sell if k[a:b + 1].sum() > 0)
    srl = []
    for a, b in sell:
        srl.append([[bname(Bm[a + x]), y - x + 1] for x, y in stretches(Bm[a:b + 1])])
    T = bk.T
    due = {}
    for r in RULES:
        tg = rule_targets(r, s, g, Bm)
        due[r] = len(due_list(r, idx, T, tg, s, g, Bm))
    return {"weeks": len(dec), "sessions": bk.T, "first_state": int(s[0]), "weeks_IN": int((reg == 0).sum()), "weeks_OUT_BUY": int((reg == 1).sum()), "weeks_OUT_SELL": int((reg == 2).sum()),
            "OUT_SELL_lengths": [b - a_ + 1 for a_, b in sell], "k0": sell_k.count(0), "k1": sell_k.count(1), "k2": sell_k.count(2), "index_weeks": int(sum(1 for x in sell_k if x > 0)),
            "index_spells": int(idx_spells), "B_changes": int(bch), "g_flips": int((g[1:] != g[:-1]).sum()), "g_first_state": int(g[0]), "start": str(bk.cal[0].date()), "end": str(bk.cal[-1].date()),
            "trades_due": due, "B_sequences": srl}


def window_check(rec: dict, exp: dict) -> bool:
    """Step 1's counts (T15.md 2) reproduced by the engine's own series for one book and window."""
    keys = [("weeks", "weeks"), ("sessions", "sessions"), ("first_state", "first_state"), ("weeks_IN", "weeks_IN"), ("weeks_OUT_BUY", "weeks_OUT_BUY"), ("weeks_OUT_SELL", "weeks_OUT_SELL"),
            ("OUT_SELL_lengths", "OUT_SELL_lengths"), ("k0", "OUT_SELL_weeks_k0"), ("k1", "OUT_SELL_weeks_k1"), ("k2", "OUT_SELL_weeks_k2"), ("index_weeks", "OUT_SELL_weeks_holding_an_index"),
            ("index_spells", "OUT_SELL_spells_holding_an_index"), ("B_changes", "B_changes_inside_OUT_SELL"), ("g_flips", "g_flips"), ("g_first_state", "g_first_state"), ("start", "start"), ("end", "end")]
    good = all(rec[a] == exp[b] for a, b in keys)
    for r in RULES:
        good &= exp["rules"][r]["trades_from_regime_gold_and_B_changes"] == rec["trades_due"][r]
    good &= rec["B_sequences"] == [s["B_sequence"] for s in exp["OUT_SELL_spell_table"]]
    return bool(good)


def process_book(job: dict) -> dict:
    """One (window, book): everything the book needs, in its own process. Returns the accumulators and the per-book audit pieces."""
    win, p = job["win"], job["book"]
    W = WINDOWS[win]
    t1 = time.time()
    out = {"rows": [], "vrows": [], "nav": {}, "vnav": {}, "trades": [], "positions": [], "v2_trades": 0, "v2_basket_trades": 0, "ledger": [], "cmix_params": {}}
    bk = Book(p, win)
    dec = bk.decisions()
    bk.nobar_trades = bk.gold_norange_trades = bk.gold_nobar_trades = 0
    navs20 = run_book(bk, dec, "full", "headline", COSTS, out, True)
    stand_in = {"stock_lines_priced_by_stand_in_in_trades": bk.nobar_trades, "goldbees_trades_filled_at_raw_OHLC4_no_MCX_range": bk.gold_norange_trades,
                "goldbees_trades_priced_at_previous_close_no_gold_bar": bk.gold_nobar_trades}
    g0 = g0_check(bk) if W["cal"] == "d17" else None
    sessions = sessions_by_state(bk, dec)
    s, g, Bm = arrays_of(dec)
    reg = regime_codes(s, g)
    # V4(b): every index priced as the cash level, 0 cost: -idx equals -liq on every session
    vb = {}
    bkc = Book(p, win, idx_mode="cash")
    for base in ("50", "80"):
        res = {}
        for rule in (f"{base}-idx", f"{base}-liq"):
            tg = rule_targets(rule, s, g, Bm)
            res[rule] = simulate(bkc, dec["decision_idx"].values, tg, 0.0, due_list(rule, dec["decision_idx"].values, bkc.T, tg, s, g, Bm), reg=reg)
        rel = float(np.abs(res[f"{base}-idx"] / res[f"{base}-liq"] - 1).max())
        vb[f"{p}|{base}"] = {"max_rel_diff": rel, "sessions": int(bkc.T), "pass": bool(rel < REL_TOL_NAV)}
    # V4(c): -idx equals -liq on every session before the first trade into an index (20.8 bps, headline)
    vc = {}
    for base in ("50", "80"):
        first = [t["idx"] for t in out["trades"] if t["run"] == f"{base}-idx" and t["cost_bps"] == PRIMARY and any(t[f"{n}_after"] > 0 for n in INDICES)]
        t_first = min(first) if first else bk.T
        a_, b_ = out["nav"][(p, PRIMARY, f"{base}-idx")], out["nav"][(p, PRIMARY, f"{base}-liq")]
        rel = float(np.abs(a_[:t_first] / b_[:t_first] - 1).max()) if t_first > 0 else float("nan")
        vc[f"{p}|{base}"] = {"first_index_trade_session": (str(bk.cal[t_first].date()) if first else None), "sessions_compared": int(t_first), "max_rel_diff": rel,
                             "pass": bool(t_first > 0 and rel < REL_TOL_NAV)}
    # R2, R3, R4, R5 (robustness, 20.8 bps)
    bk3 = Book(p, win, cash="liq")
    run_book(bk3, dec, "full", "r2_liq", (PRIMARY,), out, False)
    bk4 = Book(p, win, start=W["r3_start"])
    dec4 = bk4.decisions()
    run_book(bk4, dec4, "r3", "r3", (PRIMARY,), out, False)
    for k, (j0, j1) in enumerate(out_sell_spells(reg)):
        run_book(bk, dec, "full", f"r4_s{k + 1}", (PRIMARY,), out, False, spell_cash=(j0, j1))
    bk5 = Book(p, win, idx_mode="drag")
    run_book(bk5, dec, "full", "r5_drag", (PRIMARY,), out, False)
    return {"book": p, "out": out, "dec": dec, "dec4": dec4, "seconds": time.time() - t1, "stand_in": stand_in, "g0": g0, "sessions": sessions, "vb": vb, "vc": vc, "cal": bk.cal,
            "bk_summary": {"t0": str(bk.t0.date()), "last": str(bk.cal[-1].date()), "T": bk.T, "T4": bk4.T, "basket_events": sorted(bk.basket_events), "bidx": [int(x) for x in bk.bidx],
                           "eff": [str(d.date()) for d in bk.eff], "b0": bk.b0, "initial_basket_switch_session": bk.initial_basket_switch_session, "gold_no_own_bar": bk.gold_no_own_bar,
                           "gold_norange_sessions": [str(d.date()) for d in bk.cal[bk.gold_norange]], "cash_info": bk.cash_info, "stocks": bk.stocks,
                           "index_nobar_sessions": bk.index_nobar_sessions, "r3_index_nobar_sessions": bk4.index_nobar_sessions,
                           "nobar_any_held_sessions": int(((bk.W[bk.basket_at] > 0) & bk.nobar).any(axis=1).sum()), "src_counts": held_src_counts(bk),
                           "r3_t0": str(bk4.t0.date()), "r3_initial_basket_switch_session": bk4.initial_basket_switch_session}}


def data_selftest(win: str) -> dict:
    """The data boundary: a non-approved, superseded, pending or unregistered file must raise; the Smallcap 100 guards must raise before their usable-from dates."""
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
    uf_px = pd.Timestamp(AD.usable_from(IDX_DIR / "SC100_daily_ohlcv.csv"))
    try:
        AD.guard_window(IDX_DIR / "SC100_daily_ohlcv.csv", str((uf_px - pd.Timedelta(days=1)).date()))
        selftest["guard_sc100_prices_before_usable_from"] = {"raised": False}
    except NotApprovedError as e:
        selftest["guard_sc100_prices_before_usable_from"] = {"raised": True, "message": str(e)}
    AD.guard_window(MASTER_DIR / "Master_SC100.xlsx", SC_USABLE_FROM)
    AD.guard_window(IDX_DIR / "SC100_daily_ohlcv.csv", uf_px)
    selftest["guards_at_usable_from_pass"] = {"raised": False, "ok": True}
    selftest["pass"] = all(v.get("raised", False) for k, v in selftest.items() if isinstance(v, dict) and k != "guards_at_usable_from_pass")
    return selftest


def run_window(win: str, a, outdir: Path) -> dict:
    W = WINDOWS[win]
    USED.clear()                         # inputs.csv and the window-coverage check list this window's files only
    t_start = time.time()
    outdir.mkdir(parents=True, exist_ok=True)
    end = end_of(win)
    books = a.books or (PARENTS[:1] if a.quick else PARENTS)
    assert all(b in PARENTS for b in books), books
    s1 = json.loads(STEP1.read_text(encoding="utf-8"))
    selftest = data_selftest(win)
    c0 = common(win)
    ib = index_bars(win)
    print(f"[{win}] data: window {'2014-09-01' if win == 'w1' else 'D17 first date'} -> {end.date()}, approved data as of {AD.as_of()}; non-approved open and the Smallcap 100 guards raise: {selftest['pass']}", flush=True)

    jobs = [{"win": win, "book": p} for p in books]
    workers = min(a.workers, len(jobs))
    t_jobs = time.time()
    if workers > 1:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            results = list(ex.map(process_book, jobs))
    else:
        results = [process_book(j) for j in jobs]
    print(f"[{win}] books done in {time.time() - t_jobs:.0f}s: " + ", ".join(f"{r['book']} {r['seconds']:.0f}s" for r in results), flush=True)

    out = {"rows": [], "vrows": [], "nav": {}, "vnav": {}, "trades": [], "positions": [], "v2_trades": 0, "v2_basket_trades": 0, "ledger": [], "cmix_params": {}}
    decs, decs4, g0s, vb, vc, sess = {}, {}, {}, {}, {}, {}
    for r in results:
        o = r["out"]
        for k in ("rows", "vrows", "trades", "positions", "ledger"):
            out[k] += o[k]
        out["nav"].update(o["nav"])
        out["vnav"].update(o["vnav"])
        out["cmix_params"].update(o["cmix_params"])
        out["v2_trades"] += o["v2_trades"]
        out["v2_basket_trades"] += o["v2_basket_trades"]
        decs[r["book"]], decs4[r["book"]] = r["dec"], r["dec4"]
        sess[r["book"]] = r["sessions"]
        vb.update(r["vb"])
        vc.update(r["vc"])
        if r["g0"] is not None:
            g0s[r["book"]] = r["g0"]
    bks = {p: Book(p, win) for p in books}

    # step 1 reproduction
    step1_detail = {}
    for p in books:
        exp = s1["w1"]["full"] if win == "w1" else s1["w2"][p]["full"]
        step1_detail[f"{p}|full"] = window_check(build_counts(bks[p], decs[p]), exp)
        bk4_p = Book(p, win, start=W["r3_start"])
        exp4 = s1["w1"]["r3"] if win == "w1" else s1["w2"][p]["live"]
        step1_detail[f"{p}|r3"] = window_check(build_counts(bk4_p, decs4[p]), exp4)
    s1_ok = bool(all(step1_detail.values()))

    # V2 and the audit per book
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
        audit["books"][p] = {**{k: v for k, v in cnt.items() if k != "trades_due"}, "trades_due_per_rule": cnt["trades_due"], "sessions_by_state": rs["sessions"],
                             "v2_decisions_checked": len(dec), "v2_violations": viol, "v2_trades_checked": traded_rows, "v2_sc100_signal_first_label_date": str(sc_min_label.date()),
                             "stale_label_weeks(age>=5d, excluding T0)": int((dec["label_age_days"].values[1:] >= 5).sum()), "cash": rs["bk_summary"]["cash_info"], "stand_in": rs["stand_in"],
                             "index_sessions_without_a_bar": rs["bk_summary"]["index_nobar_sessions"], "r3_index_sessions_without_a_bar": rs["bk_summary"]["r3_index_nobar_sessions"],
                             "baskets": {"effective_dates_in_window": [d for d in rs["bk_summary"]["eff"] if bk.t0 <= pd.Timestamp(d) <= bk.end], "basket_changes": len(rs["bk_summary"]["basket_events"]),
                                         "initial_basket_session": rs["bk_summary"]["initial_basket_switch_session"], "change_sessions": [str(bk.cal[i].date()) for i in rs["bk_summary"]["basket_events"]]},
                             "gold_sessions_without_own_bar": rs["bk_summary"]["gold_no_own_bar"], "gold_sessions_without_mcx_range": rs["bk_summary"]["gold_norange_sessions"],
                             "window_sessions_where_a_held_stock_has_no_bar": rs["bk_summary"]["nobar_any_held_sessions"], "src_counts": rs["bk_summary"]["src_counts"]}
        # an index line is never traded on a session without a bar (asserted in `trade`); the sessions without a bar must all be decision sessions (T15.md 2.2 item 5)
        dsess = set(str(bk.cal[int(i)].date()) for i in dec["decision_idx"].values)
        for n, lst in rs["bk_summary"]["index_nobar_sessions"].items():
            audit["books"][p].setdefault("index_nobar_sessions_not_decision_sessions", {})[n] = [d for d in lst if d not in dsess]
    if win == "w1":
        for p in books:
            assert audit["books"][p]["gold_sessions_without_own_bar"] == [str(NO_GOLD_SESSION.date())], audit["books"][p]["gold_sessions_without_own_bar"]
        no_d18 = [str(d.date()) for d in bks[books[0]].cal if d not in set(raw_parent(books[0], end)["d18_dates"])]
        assert no_d18 == [str(NO_D18_SESSION.date())], no_d18
    v2_cnt += out["v2_trades"] + out["v2_basket_trades"]
    v2_ok = bool(v2_viol == 0 and v2_cnt > 0)
    v3 = v3_index_tie(win, books, decs)
    v3["index_trade_sessions_without_bar_in_trades"] = 0       # a trade on such a session raises in `trade`; reaching this line means none
    v3["index_sessions_without_a_bar_total"] = {p: {n: len(v) for n, v in audit["books"][p]["index_sessions_without_a_bar"].items()} for p in books}

    # evidence files (V4(a) reads the in-memory NAVs, not the files)
    pd.concat(decs.values()).to_csv(outdir / "decisions.csv", index=False)
    pd.concat(decs4.values()).to_csv(outdir / "decisions_r3.csv", index=False)
    pd.DataFrame(out["rows"]).to_csv(outdir / "stats.csv", index=False)
    pd.DataFrame(out["vrows"]).to_csv(outdir / "robustness.csv", index=False)
    tcols = ["book", "window", "cost_bps", "run", "date", "idx", "kind", "e_after", "gold_share", "cash_share"] + [f"w_{n}" for n in INDICES] + ["basket_eff", "V", "traded", "cost", "stock_before", "gold_before",
             "cash_before"] + [f"{n}_before" for n in INDICES] + ["stock_after", "gold_after", "cash_after"] + [f"{n}_after" for n in INDICES] + ["V_after", "nav_close_after", "dec_j"]
    pd.DataFrame([{k: t.get(k) for k in tcols} for t in out["trades"]]).reindex(columns=tcols).to_csv(outdir / "trades.csv", index=False)
    pd.DataFrame(out["positions"]).to_csv(outdir / "positions.csv", index=False)
    pd.DataFrame(out["ledger"]).to_csv(outdir / "regime_ledger.csv", index=False)
    pd.DataFrame([{"book": p, "rule": r_, **v} for p in books for r_, v in out["cmix_params"][p].items()]).to_csv(outdir / "constant_mix_params.csv", index=False)
    daily = [pd.DataFrame({"book": p, "date": bks[p].cal, "cost_bps": cost, "run": name, "nav": nv}) for (p, cost, name), nv in out["nav"].items()]
    pd.concat(daily).to_csv(outdir / "daily_nav.csv", index=False)
    # robustness NAVs on their own calendars (R3's is the book's R3 calendar)
    cal4 = {p: Book(p, win, start=W["r3_start"]).cal for p in books}
    vd = [pd.DataFrame({"book": p, "window": w_, "variant": var, "cost_bps": cost, "run": name, "date": (cal4[p] if w_ == "r3" else bks[p].cal), "nav": nv})
          for (p, w_, var, cost, name), nv in out["vnav"].items()]
    pd.concat(vd).to_csv(outdir / "robust_nav.csv", index=False)
    if win == "w1":
        pn = [pd.DataFrame({"book": p, "date": bks[p].cal, "hold_parent_0bps": out["nav"][(p, 0.0, "hold_parent")], "hold_parent_20.8bps": out["nav"][(p, PRIMARY, "hold_parent")],
                            **{f"{r_}_20.8bps": out["nav"][(p, PRIMARY, r_)] for r_ in RULES}}) for p in books]
        pd.concat(pn).to_csv(outdir / "parent_nav_2014-09-01_2019-01-02.csv", index=False)
        (outdir / "parent_nav_2014-09-01_2019-01-02.md").write_text(
            "# Rebuilt parent NAV, 2014-09-01 to 2019-01-02\n\nrebuilt from the parent's baskets and Eikon prices, not validated against a published NAV before 2019-01-02.\n\n"
            "Columns: `hold_parent_*` (always IN) and the eight rules at 20.8 bps, base 1.0 at 2014-09-01's close. Not approved data; no other test may read it.\n", encoding="utf-8")
    pd.concat([r["dec"][["book", "decision_date", "decision_idx", "regime", "B", "k"]] for r in results]).to_csv(outdir / "regimes.csv", index=False)

    g0_for_v4 = {p: seam_2019(p) for p in books} if win == "w1" else g0s
    reg4 = v4_identities(win, books, bks, decs, out, g0_for_v4, vb, vc)
    if win == "w1":
        reg4["f_seam_2019"] = g0_for_v4
    (outdir / "regression.json").write_text(json.dumps(reg4, indent=1, default=str), encoding="utf-8")
    v5 = v5_check(out, books, bks, decs)
    audit["v2"] = {"checks": int(v2_cnt), "violations": int(v2_viol), "recorded_trades_after_their_decision": int(out["v2_trades"]), "recorded_basket_changes_on_or_after_availableDate": int(out["v2_basket_trades"]),
                   "sc100_rule7_checks": len(books), "sc100_signal_rows_read_from": str(c0["master"]["SC100"].index.min().date()), "pass": v2_ok}
    audit["v3"] = v3
    audit["v4"] = {"pass": reg4["pass"]}
    audit["v5"] = v5
    write_inputs = pd.DataFrame([{k: v.get(k) for k in ("file", "through", "bytes", "sha256", "approved_row", "usable_from")} for v in USED.values()])
    write_inputs.to_csv(outdir / "inputs.csv", index=False)
    for rel, r_ in USED.items():
        if r_["id"] in ("D26", "D03", "D09", "D11", "D24b", "D24", "D18", "D25c") and str(r_["through"])[:1].isdigit():
            assert str(r_["through"]) >= str(end.date()), f"{rel}: approved through {r_['through']}, before the window's end {end.date()}: stop and ask Manu"
        if r_["id"] == "D25" and win == "w1":      # D25 is read by W2 only for the V3 tie on labels before 2019-01-01
            assert str(r_["through"]) >= str(end.date()), f"{rel}: approved through {r_['through']}, before the window's end {end.date()}: stop and ask Manu"
    audit["data"] = {"approved_data_as_of": AD.as_of(), "window_end": str(end.date()), "inputs": int(len(USED)), "non_approved_open_and_guards": selftest,
                     "master_rows_after_END_dropped": c0["master_rows_after_end"], "mauc1_rows_after_END_dropped": int(c0["gold_master_rows_after_end"]),
                     "goldbees_first_bar": str(c0["gold_first"].date()), "goldbees_file_last": str(c0["gold_last"].date()), "mcx_file_last": str(c0["mcx_last"].date()),
                     "cash": {"lbes_last": str(c0["lbes_last"].date()), "liq_last": str(c0["liq_last"].date()), "accrued_sessions": 0},
                     "index_files": {n: {"first_bar": str(ib["bars"][n].index.min().date()), "last_bar": str(ib["bars"][n].index.max().date()), "bars_to_end": int(len(ib["bars"][n]))} for n in INDICES}}
    audit["step1_counts_reproduced"] = {"pass": s1_ok, "detail": step1_detail, "file": STEP1.relative_to(AA).as_posix()}
    audit["run"] = {"window": win, "name": a.run, "command": " ".join(sys.argv), "books": list(books), "seconds": round(time.time() - t_start), "quick": a.quick,
                    "python": sys.version.split()[0], "numpy": np.__version__, "pandas": pd.__version__, "draws": 0, "seeds": "none"}
    audit["prereg_sha256"] = (T15 / "T15.md").read_text(encoding="utf-8").split("§1–§3 sha256:** `")[1].split("`")[0]
    ok = bool(v2_ok and v3["pass"] and reg4["pass"] and v5["pass"] and selftest["pass"] and s1_ok)
    audit["gates"] = {"V2": v2_ok, "V3": v3["pass"], "V4": reg4["pass"], "V5": v5["pass"], "approved_data_selftest": selftest["pass"], "step1_counts": s1_ok, "all": ok}
    (outdir / "audit.json").write_text(json.dumps(audit, indent=1, default=str), encoding="utf-8")
    ra = reg4["a_nav_regression"]
    print(f"[{win}] V2 {audit['v2']['checks']} checks, {audit['v2']['violations']} violations; V3 {v3['pass']} ({v3['labels_checked']} labels tied); V4 {reg4['pass']} (T14 nav rows {ra['rows_compared']}, worst "
          f"{ra['worst_rel_diff']:.2e}; T14 trade rows {ra['trade_rows_compared']}, worst {ra['worst_trade_rel_diff']:.2e}; shared code {reg4['d_shared_code']['pass']}); V5 {v5['pass']} "
          f"({v5['trades_checked']} trades, worst {max(v5['worst'].values()):.1e}); step1 {s1_ok}", flush=True)
    print(f"[{win}] gates: {audit['gates']}  done in {time.time() - t_start:.0f}s -> {outdir}", flush=True)
    return {"ok": ok, "gates": audit["gates"]}


def main():
    ap_ = argparse.ArgumentParser()
    ap_.add_argument("--run", default="headline")
    ap_.add_argument("--window", choices=["w1", "w2", "both"], default="both")
    ap_.add_argument("--quick", action="store_true", help="smoke test: the first book only")
    ap_.add_argument("--books", nargs="+", default=None)
    ap_.add_argument("--workers", type=int, default=4, help="processes: one per book")
    ap_.add_argument("--outdir", default=None, help="write here (<outdir>/<window>) instead of tests/T15/evidence/<run>/<window>")
    a = ap_.parse_args()
    base = Path(a.outdir) if a.outdir else T15 / "evidence" / a.run
    wins = ["w1", "w2"] if a.window == "both" else [a.window]
    ok = True
    for w in wins:
        r = run_window(w, a, base / w)
        ok &= r["ok"]
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
