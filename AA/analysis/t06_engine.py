# -*- coding: utf-8 -*-
"""T06 engine: the three-index switch (T03's rule) against two nulls on the latest approved data.

A FORK of analysis/t03_engine.py (copied, not imported): T03's engine hard-codes END = 2026-08-21 and the superseded frozen
files. Here every data file is opened through `approved_data.require()` (an APPROVED row of data/APPROVED_DATA.md), its sha256
prefix is checked against the row, and END is read from the approved D17 files. Pre-registration: tests/T06/T06.md sections
1-3 (frozen; `python tests/T06/check_prereg.py`); plan: tests/T06/PLAN_v2.md. Conventions below are the engine's readings of
that text; the ones the text leaves open are in READINGS and are written to audit.json.

    python analysis/t06_engine.py [--run NAME] [--draws N] [--quick]      (from AA/)

Nulls (2,000 draws per book, window and type):
    N4.9   spell shuffle (T03's function, unchanged, seed [3, draw_id])
    N4.10  random timing with free spell lengths: the k_in in-spell lengths are integers in [2, HI_in] summing to S_in, the
           k_out out-spell lengths integers in [2, HI_out] summing to S_out, uniform over all ordered tuples (exact sequential
           sampler on a dynamic-programming count table; seed [6, draw_id]); interleaved alternately from the rule's first state.

Writes tests/T06/evidence/<run>/:
    inputs.csv           file, through, bytes, sha256, approved_row (every input, from the approved rows; a sha mismatch stops the run)
    decisions.csv        one row per weekly decision and book
    trades.csv, positions.csv, daily_nav.csv     strategy and comparators (as T03)
    stats.csv            statistics of every realisation that is not a null draw
    draws.csv            every null draw (N4.9 and N4.10) + sessions_invested, in_lengths, out_lengths ('|'-joined, in order)
    draw_states.npz      key "<book>|<window>|<type>": uint8 (draws, weeks) weekly in-or-out state of every draw
    draw_curves_20.8.npz key "<book>|<type>_<id>": daily NAV (float32) of every headline draw at 20.8 bps
    g_engine.csv         V4(c): always-in at 0 cost against the published NAV (G0)
    count_table.json     per book, window and state: weeks S, spells k, bounds, number of allowed tuples (V3, V5)
    sampler_selftest.json  V5
    regression_t03.json  V4
    audit.json           point-in-time counts, data notes, readings, v3 block

Trade rule (one function, `trade`): at a trade session t, with fill prices (stocks OHLC4, GOLDBEES de-spiked OHLC4, cash at
its level), V = value of all holdings at those prices. Target values: stocks e*V*w_i, GOLDBEES and cash (1-e)/2*V each.
traded = sum |target - held| over every line; cost = traded * cost_bps/2/1e4; every target is then scaled by (V-cost)/V.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
import warnings
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
T03 = AA / "tests" / "T03" / "evidence" / "headline"      # read-only reference for V4
T06 = AA / "tests" / "T06"
PARENTS = ["SCMO_0003", "SCMO_0007", "SCMO_0010", "SCMO_0029"]
LIVE_START = pd.Timestamp("2021-11-01")
COSTS = (0.0, 20.8, 50.0)
PRIMARY = 20.8
N_DRAWS = 2000
LO = 2                       # shortest spell: 2 weeks = 14 days (T06.md section 2)
DESPIKE_TOL = 0.005
LIQ_FROM = pd.Timestamp("2024-01-24")        # R2: LIQUIDCASE replaces LBES from this session
T03_NAV_END = pd.Timestamp("2026-08-07")     # V4(b): T03's NAVs are compared up to here (after it T03 accrued cash at the 90-session rate)
LBES_VERBATIM_LAST = pd.Timestamp("2026-08-09")   # APPROVED_DATA.md, D11 note: rows to here are the supplied LBES file, later rows are appended
G0_OVERALL, G0_YEARLY = 0.25, 0.5            # pp / yr
REL_TOL_NAV = 1e-12

READINGS = {
    "E1": "calendar = D17's dates of the book from its first date to END (D17's last date, read from the approved D17 files); D18 prices on other dates are never read",
    "E2": "decision dates = T0 and the last D17 session of every later ISO week; the decision at the last session is not traded",
    "E3": "label = latest Master row dated <= decision date, per index; IN iff all three SIGN are BUY",
    "E4": "initial position at T0 close, no cost: OUT = 50% GOLDBEES, 50% cash; IN = the basket in force at T0 as drifted since its "
          "availableDate (OHLC4 of the first D18 session on or after it), scaled to NAV 1",
    "E5": "a basket takes effect on the first calendar session on or after its availableDate; baskets flagged csv_only_skipped are dropped; "
          "weights are renormalised to 1",
    "E6": "stock fill = OHLC4 of the Eikon bar (close if any of open/high/low is blank; last close if the stock has no bar that session)",
    "E7": "costs: one rule for every trade, see the module docstring (cost on the value traded, targets scaled by (V-cost)/V)",
    "E8": "a basket change while IN trades from the old holdings to the new basket (delta trades); while OUT nothing is traded",
    "E9": "a switch and a basket change on the same session: the switch trades into / out of the basket in force that session",
    "E10": "cash level: the extended LBES (D11) as-of on sessions; it covers the window, so the trailing-90-session accrual branch of T03 is removed "
           "and the engine asserts that no session of any window lies after the file's last date (0 accrued sessions)",
    "E11": "constant mix: stock share f = invested decision weeks / decision weeks, rebalanced at every decision date's next session "
           "(T0 included, as T03.md says) and at every basket change; initial stock holding = drifted basket scaled by f",
    "E13": "R3 live window starts at the first D17 session on or after 2021-11-01 with its own spells and totals, own draws (same seeds), "
           "the SAME bounds (HI_in, HI_out from the book's full-window series) and free initial position in the state decided then",
    "E14": "R2 cash = LBES to the session before 2024-01-24, then chained with the desk's LIQUIDCASE returns on sessions (liquidEtfFinal_extended)",
    "E15": "V4(c) always-in runs on the full window (END = D17's last date); G0 = +-0.25 pp/yr overall and +-0.5 pp every calendar year",
    "E16": "GOLDBEES fill: T03's de-spike (OHLC4 of open/high/low clipped to MCX gold's range that day + 0.5%) on every session up to the MCX file's last "
           "date (2026-09-28); on later sessions the raw OHLC4 of the Eikon bar, no clipping, no scaling, no tolerance band",
    "T06-1": "sessions_invested (draws.csv, audit.json) = number of daily returns t = 1..T-1 earned while the parent is held, i.e. sessions i = 0..T-2 whose "
             "closing position is the parent (a switch decided at decision j is traded at session decision_idx[j]+1 and held from that close); of T-1 = 1,884 "
             "on the old window. This reproduces the 945 (rule) and 941 (draw 445) of T03",
    "T06-2": "V4(b): the constant mix is compared after re-running it with T03's stock share f (invested weeks / weeks of T03's 400 decisions), because T06's own f "
             "uses the longer decision series; the other comparators and the strategy are compared as run. The published NAV is compared too",
    "T06-3": "V4(c) does not compare with the Step 1 rebuild (data/parent_rebuild_hm/daily.csv is not an APPROVED row): the columns "
             "max_rel_diff_vs_step1_rebuild and rebuild_dates_compared of g_engine.csv are therefore empty / 0",
    "T06-4": "the sampler draws one uniform per part, including the last part (whose length is forced), so a draw consumes k uniforms; cumulative "
             "probabilities are exact integer prefix sums divided by the exact total (Python int / int, correctly rounded), searchsorted side='right'",
    "T06-5": "V5(c): the sum of the lengths of a draw is fixed, so the draw's mean length has zero variance; the check is therefore made per spell position "
             "(the i-th in-spell and the i-th out-spell): the mean of its length over the draws within 4 standard errors (SD over draws / sqrt(draws)) of S/k",
    "T06-6": "inputs.csv is a plain csv with the five columns of PLAN_v2 (no comment line, so any csv reader opens it); the 'As of' date of APPROVED_DATA.md is in audit.json "
             "(data.approved_data_as_of). approved_row = '<STATUS> <ID>'. inputs.csv also lists the approved files the engine registers but does not parse "
             "(the _columns.csv files, the D05 rebalance history; skipped baskets come from the _holding_weight_sources.csv trace, as in T03), listed in audit.json data.registered_not_parsed",
    "T06-7": "window-coverage check: the through-date of every role the run reads must reach END, except D12 (the de-spike range, raw OHLC4 after it) and the basket files "
             "D19/D05, whose through-date is the newest basket (the last basket stays in force; APPROVED_DATA.md allows windows to mid-December 2026)",
    "T06-8": "the 'weeks' of draw_states.npz and of every V3/V5 statement are the weekly decision rows (409 for SCMO_0003, 408 for SCMO_0007 on the full window)",
    "T06-9": "bounds: HI_in and HI_out = the longest in-spell and out-spell of each book's own full-window series (all four books give the same 46 and 40, "
             "checked against logs/step_1_spell_counts.json); lo = 2",
}


# ── approved raw inputs ───────────────────────────────────────────────────────
USED: dict[str, dict] = {}


def ap(path) -> Path:
    """The only way the engine opens a data file: APPROVED row required, sha256 prefix checked once per file."""
    p = AD.require(path)
    rel = p.relative_to(AA).as_posix()
    if rel not in USED:
        USED[rel] = AD.check_sha(p)
    return p


def sha(p: Path) -> str:
    return AD.sha256_of(p)


def _d17_end() -> pd.Timestamp:
    ends = []
    for p in PARENTS:
        n = pd.read_csv(ap(HD / "parent_nav_2026-10-22" / f"{p}.csv"), usecols=["_id.date"])
        ends.append(pd.to_datetime(n["_id.date"], format="%Y/%m/%d").max())
    assert len(set(ends)) == 1, f"the four D17 files end on different dates: {ends}"
    for p in PARENTS:
        r = AD.row_for(HD / "parent_nav_2026-10-22" / f"{p}.csv")
        assert r["through"] == str(ends[0].date()), f"{p}: file ends {ends[0].date()}, APPROVED_DATA.md says {r['through']}"
    return ends[0]


END = _d17_end()          # D17's last date: the window's end (2026-10-22 on the 2026-11-06 data)
V4_END = END              # always-in (V4c) runs on the whole window


_RAW: dict = {}


def raw_parent(p: str) -> dict:
    """Stock prices (D18 with the price corrections), baskets (D19, skipped dropped), D17 dates and NAV."""
    if p in _RAW:
        return _RAW[p]
    wm = pd.read_csv(ap(HM / f"{p}_holding_weight_matrix.csv"), index_col=0)
    wm.index = pd.to_datetime(wm.index)
    src = pd.read_csv(ap(HM / f"{p}_holding_weight_sources.csv"))
    src["rebalance_date"] = pd.to_datetime(src["rebalance_date"])
    skipped = set(src.loc[src["source"] == "csv_only_skipped", "rebalance_date"])
    wm = wm[~wm.index.isin(skipped)]
    wm = wm.div(wm.sum(axis=1), axis=0)
    stocks = list(wm.columns)
    o = pd.read_csv(ap(HM / f"{p}_ohlc.csv"), parse_dates=["date"]).drop_duplicates(["date", "stock"])
    piv = {f: o.pivot(index="date", columns="stock", values=f).sort_index().reindex(columns=stocks)
           for f in ("open", "high", "low", "close")}
    cor = pd.read_csv(ap(HM / "price_corrections.csv"), parse_dates=["ex_date"])
    for r in cor.itertuples():
        if p in r.applies_to.split(";") and r.stock in stocks:
            for f in piv:
                piv[f].loc[piv[f].index < r.ex_date, r.stock] *= r.factor
    raw_close = piv["close"]
    close = raw_close.ffill()
    ohlc4 = ((piv["open"] + piv["high"] + piv["low"] + piv["close"]) / 4).fillna(raw_close)
    n = pd.read_csv(ap(HD / "parent_nav_2026-10-22" / f"{p}.csv"))
    pub = pd.Series(n["index"].values, index=pd.to_datetime(n["_id.date"], format="%Y/%m/%d")).sort_index()
    assert o["date"].max() >= END, f"{p}: D18 ends {o['date'].max().date()} before END"
    _RAW[p] = dict(W=wm, stocks=stocks, close=close, ohlc4=ohlc4, pub=pub, skipped=sorted(skipped))
    return _RAW[p]


_COMMON: dict = {}


def common() -> dict:
    """Gold (D09 extended + D12 de-spike), cash (D11 extended), the three extended Master files (D03)."""
    if _COMMON:
        return _COMMON
    g = pd.read_parquet(ap(AA / "analysis" / "cache" / "why_gold_ohlc_eikon_extended_2026-11-04.parquet")).set_index("date").sort_index()
    g = g[~g.index.duplicated(keep="last")]
    m = pd.read_csv(ap(AA / "analysis" / "evidence" / "final_strategy" / "mauc1" / "mauc1_daily_clean.csv"), index_col=0, parse_dates=True)
    m.columns = [c.strip().lower() for c in m.columns]
    mcx_last = m.index.max()
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
    raw4 = (g["open"] + g["high"] + g["low"] + g["close"]) / 4
    after = g.index > mcx_last                                  # E16: past the MCX file the fill is the raw OHLC4
    gfill = gfill.where(~after, raw4)
    lb = pd.read_csv(ap(HD / "LBES_Adjusted_Price_data_extended_2026-11-05.csv"))
    lb["date"] = pd.to_datetime(lb["date"], format="%d/%m/%y %H:%M")
    lb = lb.set_index("date")["price"].sort_index()
    lq = pd.read_csv(ap(HD / "liquidEtfFinal_extended_2026-11-05.csv"))
    lq["date"] = pd.to_datetime(lq["date"], format="mixed", dayfirst=True)
    lq = lq.set_index("date")["liquid_case"].sort_index()
    ms = {}
    for n in ("Nifty100", "MC100", "SC100"):
        d = pd.read_excel(ap(HD / "extended_2026-10-30" / "Master" / f"Master_{n}.xlsx"), parse_dates=["Date"])
        s = d.dropna(subset=["SIGN"]).set_index("Date")["SIGN"].sort_index()
        ms[n] = s[~s.index.duplicated(keep="last")]
        assert ms[n].index.max() >= END, f"Master_{n} ends {ms[n].index.max().date()} before END"
    assert g.index.max() >= END and lb.index.max() >= END and lq.index.max() >= END
    _COMMON.update(gclose=g["close"], gfill=gfill, lbes=lb, liq=lq, master=ms, mcx_last=mcx_last,
                   gold_data_last=g.index.max(), gold_raw_sessions_in_data=[str(d.date()) for d in g.index[after]])
    return _COMMON


def cash_levels(cal: pd.DatetimeIndex, kind: str = "lbes") -> tuple[np.ndarray, dict]:
    """E10, E14. Level on every session of cal. The extended LBES covers the window: nothing is accrued."""
    c = common()
    lb = c["lbes"]
    union = cal.union(lb.index)
    lv = lb.reindex(union).ffill().reindex(cal)
    last_file = lb.index.max()
    assert not (cal > last_file).any(), f"cash file ends {last_file.date()} before the window's last session {cal.max().date()}: stop and ask Manu"
    info = {"file_last": str(last_file.date()), "accrued_sessions": 0}
    if kind == "liq":
        q = c["liq"]
        assert not (cal > q.index.max()).any(), "LIQUIDCASE file ends before the window"
        qs = q.reindex(q.index.union(cal)).ffill().reindex(cal)
        out = lv.copy()
        pre = cal[cal < LIQ_FROM]
        if len(pre) and len(pre) < len(cal):
            base = lv.loc[pre[-1]]
            for d in cal[cal >= LIQ_FROM]:
                out.loc[d] = base * qs.loc[d] / qs.loc[pre[-1]]
            lv = out
        info["cash"] = "LBES to the session before 2024-01-24, then LIQUIDCASE returns"
    return lv.values.astype(float), info


def cash_note() -> dict:
    """The first appended LBES row chains from the Sunday level (D11 note, F-AA-D13): about two days of weekend accrual are counted twice."""
    lb = common()["lbes"]
    last_v = LBES_VERBATIM_LAST
    app = lb.index[lb.index > last_v]
    pre = lb.index[lb.index < last_v]
    first_app = app[0]
    fri = pre[-1]
    sunday_accrual = float(lb.loc[last_v] / lb.loc[fri] - 1)          # level(Sunday) / level(last session before it) - 1: the accrual counted twice
    first_ret = float(lb.loc[first_app] / lb.loc[last_v] - 1)
    app_daily = lb.loc[app].pct_change().dropna()
    return {"last_verbatim_row": str(last_v.date()), "weekday": last_v.day_name(), "last_session_before_it": str(fri.date()),
            "first_appended_row": str(first_app.date()), "appended_rows": int(len(app)),
            "level_last_verbatim": float(lb.loc[last_v]), "level_first_appended": float(lb.loc[first_app]),
            "first_appended_return_vs_sunday_level": first_ret,
            "weekend_accrual_counted_twice_(Sunday_level/last_session_level-1)": sunday_accrual,
            "claimed_bound_CLAUDE_md": 0.0002, "within_claimed_bound": bool(abs(sunday_accrual) <= 0.0002),
            "mean_daily_return_of_appended_rows": float(app_daily.mean()),
            "note": "level[first appended] = level[Sunday 2026-08-09] x (1 + r[2026-08-10]), r from LIQUIDCASE close 08-07 -> 08-10: the weekend accrual already in the Sunday level is "
                    "earned again; the extension also runs about 0.5 pp/yr rich against LIQUIDBEES (F-AA-D13); disclosed, not corrected"}


class Book:
    """Everything a run needs for one parent and one window, as plain arrays on the calendar."""

    def __init__(self, parent: str, start: pd.Timestamp | None = None, end: pd.Timestamp = END, cash: str = "lbes"):
        r = raw_parent(parent)
        c = common()
        cal_all = r["pub"].index
        t0 = cal_all[0] if start is None else cal_all[cal_all.searchsorted(start)]
        cal = cal_all[(cal_all >= t0) & (cal_all <= end)]
        self.parent, self.cal, self.T, self.t0 = parent, cal, len(cal), t0
        self.stocks, self.N = r["stocks"], len(r["stocks"])
        C = r["close"].reindex(cal)
        P = r["ohlc4"].reindex(cal)
        self.nobar = P.isna().values                      # stock has no bar that session: its last close stands in (E6)
        self.nobar_trades = 0                             # trades that used such a stand-in price (counted in trade())
        P = P.fillna(C)
        self.C = np.nan_to_num(C.values.astype(float), nan=0.0)
        self.P = np.nan_to_num(P.values.astype(float), nan=0.0)
        self.pub = r["pub"].reindex(cal).values.astype(float)
        union = cal.union(c["gclose"].index)
        gc = c["gclose"].reindex(union).ffill().reindex(cal)
        gf = c["gfill"].reindex(cal).fillna(gc)
        self.g, self.gf = gc.values.astype(float), gf.values.astype(float)
        self.gold_raw = np.asarray(cal > c["mcx_last"])    # E16: GOLDBEES fill = raw OHLC4 on these sessions
        self.raw_gold_trades = 0                           # trades (all runs) whose GOLDBEES leg was filled on such a session
        self.L, self.cash_info = cash_levels(cal, cash)
        # baskets
        W = r["W"]
        self.W = W.values.astype(float)
        self.eff = W.index
        bidx = np.searchsorted(cal.values, self.eff.values)          # first session on or after availableDate
        self.bidx = bidx
        self.b0 = int(np.flatnonzero(bidx <= 0)[-1])                 # basket in force at T0 (E4/E5)
        self.basket_events = {int(i) for i in bidx if 0 < i < self.T}
        self.basket_at = np.array([int(np.flatnonzero(bidx <= t)[-1]) if (bidx <= t).any() else 0 for t in range(self.T)])
        # initial IN holdings: basket b0 as drifted since its availableDate, scaled to NAV 1 at T0's close
        ax = r["close"].index
        s0 = ax[ax.searchsorted(self.eff[self.b0])]
        w = self.W[self.b0]
        nzs = np.flatnonzero(w > 0)
        p = r["ohlc4"].loc[s0].values[nzs]
        p = np.where(np.isnan(p), r["close"].loc[s0].values[nzs], p)
        u = np.zeros(self.N)
        u[nzs] = w[nzs] / p
        v0 = float((u * np.nan_to_num(r["close"].loc[t0].values)).sum())
        self.u0 = u / v0
        self.initial_basket_switch_session = str(s0.date())

    # decisions (E2, E3)
    def decisions(self) -> pd.DataFrame:
        cal = self.cal
        iso = cal.isocalendar()
        last = pd.Series(np.arange(self.T), index=cal).groupby([iso.year.values, iso.week.values]).max().values
        idx = np.array([0] + [int(i) for i in sorted(last) if i > 0])
        ms = common()["master"]
        rows = []
        for j, i in enumerate(idx):
            d = cal[i]
            lab, state = {}, 1
            for n, s in ms.items():
                k = s.index.searchsorted(d, side="right") - 1
                lab[n] = (s.index[k], s.iloc[k])
                state &= int(s.iloc[k] == "BUY")
            ld = max(v[0] for v in lab.values())
            rows.append({"book": self.parent, "j": j, "decision_date": d.date(), "decision_idx": int(i),
                         "trade_date": (cal[i + 1].date() if i + 1 < self.T else None),
                         **{f"sign_{n}": v[1] for n, v in lab.items()}, **{f"label_{n}": v[0].date() for n, v in lab.items()},
                         "latest_label": ld.date(), "label_age_days": (d - min(v[0] for v in lab.values())).days,
                         "all_three_buy": bool(state), "state": int(state)})
        return pd.DataFrame(rows)


# ── simulation ────────────────────────────────────────────────────────────────
def trade(bk: Book, t: int, e_new: float, u, gu, cu, ow: float):
    ps, gp, lv = bk.P[t], bk.gf[t], bk.L[t]
    held_s = u * ps
    V = held_s.sum() + gu * gp + cu * lv
    w = bk.W[bk.basket_at[t]]
    Te = e_new * V * w
    Tg = Tc = (1 - e_new) / 2 * V
    bk.nobar_trades += int((bk.nobar[t] & ((Te > 0) | (held_s > 0))).sum())
    if bk.gold_raw[t] and abs(Tg - gu * gp) > 0:
        bk.raw_gold_trades += 1
    traded = np.abs(Te - held_s).sum() + abs(Tg - gu * gp) + abs(Tc - cu * lv)
    cost = ow * traded
    k = (V - cost) / V
    new_u = np.zeros_like(u)
    pos = (Te > 0) & (ps > 0)
    assert not ((Te > 0) & (ps <= 0)).any(), f"no price for a stock to buy at session {bk.cal[t].date()}"
    new_u[pos] = k * Te[pos] / ps[pos]
    return new_u, k * Tg / gp, k * Tc / lv, dict(V=V, traded=traded, cost=cost)


def simulate(bk: Book, dec_idx: np.ndarray, e: np.ndarray, cost_bps: float, every: bool = False, record: bool = False):
    """e[j] = stock share decided at decision j. Returns daily NAV (length T) and, if record, the trade and position logs."""
    T, ow = bk.T, cost_bps / 2e4
    e_cur = float(e[0])
    u = bk.u0 * e_cur
    gu = (1 - e_cur) / 2 / bk.g[0]
    cu = (1 - e_cur) / 2 / bk.L[0]
    tgt = {}
    for j in range(0 if every else 1, len(dec_idx)):   # "every" (constant mix): T0 is a decision date too, so its next session rebalances
        tr = int(dec_idx[j]) + 1
        if tr < T and (every or e[j] != e[j - 1]):
            tgt[tr] = float(e[j])
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
            e_new = tgt.get(t, e_cur)
            kind = ("switch_in" if e_new > e_cur else "switch_out" if e_new < e_cur else
                    ("mix_rebalance" if t in tgt else "basket_change"))
            u, gu, cu, info = trade(bk, t, e_new, u, gu, cu, ow)
            e_cur = e_new
            nz = np.flatnonzero(u)
            if record:
                nav_close = float(bk.C[t][nz] @ u[nz] + gu * bk.g[t] + cu * bk.L[t]) if len(nz) else float(gu * bk.g[t] + cu * bk.L[t])
                trades.append({"date": bk.cal[t].date(), "idx": t, "kind": kind, "e_after": e_new, "basket_eff": bk.eff[bk.basket_at[t]].date(),
                               **info, "nav_close_after": nav_close})
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


def spell_shuffle(s: np.ndarray, draw_id: int) -> np.ndarray:
    """N4.9: shuffle the in-spells among themselves and the out-spells among themselves, interleave from the rule's first state."""
    rng = np.random.default_rng([3, draw_id])
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


# ── N4.10: free spell lengths ─────────────────────────────────────────────────
def rule_bounds(s_full: np.ndarray) -> tuple[int, int]:
    """HI_in, HI_out: the longest in-spell and out-spell of the rule's own full-window series (46 and 40 on the 2026-10-22 window)."""
    r = spells(s_full)
    return max(c for v, c in r if v == 1), max(c for v, c in r if v == 0)


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


def free_length_draw(s: np.ndarray, draw_id: int, hi_in: int, hi_out: int, lo: int = LO) -> np.ndarray:
    """N4.10: k_in, k_out, S_in, S_out and the first state come from `s`; lengths in [lo, hi] uniform over ordered tuples; alternate from s[0]."""
    s = np.asarray(s).astype(int)
    r = spells(s)
    k = {1: sum(1 for v, _ in r if v == 1), 0: sum(1 for v, _ in r if v == 0)}
    S = {1: sum(c for v, c in r if v == 1), 0: sum(c for v, c in r if v == 0)}
    hi = {1: hi_in, 0: hi_out}
    rng = np.random.default_rng([6, draw_id])
    lens = {}
    for st in (1, 0):                                   # in-spell lengths first, then out-spell lengths, one generator
        if k[st] == 0:
            assert S[st] == 0
            lens[st] = []
            continue
        tab = count_table(k[st], S[st], lo, hi[st])
        lens[st] = draw_lengths(rng, k[st], S[st], lo, hi[st], tab)
    out, state, ptr = [], int(s[0]), {1: 0, 0: 0}
    while ptr[1] < k[1] or ptr[0] < k[0]:
        out += [state] * lens[state][ptr[state]]
        ptr[state] += 1
        state = 1 - state
    out = np.array(out, dtype=int)
    assert len(out) == len(s) and int(out[0]) == int(s[0])
    assert sum(lens[1]) == S[1] and sum(lens[0]) == S[0] and int(out.sum()) == int(s.sum())
    assert all(lo <= x <= hi_in for x in lens[1]) and all(lo <= x <= hi_out for x in lens[0])
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
def make_states(s: np.ndarray, n: int, hi_in: int, hi_out: int) -> dict:
    """The weekly states of every draw of both nulls for one series: {type: uint8 (n, weeks)}."""
    return {"N4.9": np.array([spell_shuffle(s, d) for d in range(n)], dtype=np.uint8),
            "N4.10": np.array([free_length_draw(s, d, hi_in, hi_out) for d in range(n)], dtype=np.uint8)}


def v3_check(s: np.ndarray, states: dict, hi_in: int, hi_out: int) -> dict:
    """V3 on every draw of both nulls for one series (T06.md section 2, gate V3)."""
    s = np.asarray(s).astype(int)
    r0 = lens_of(s)
    ref = {"first": int(s[0]), "weeks": len(s), "k_in": len(r0[0]), "k_out": len(r0[1]), "S_in": sum(r0[0]), "S_out": sum(r0[1]),
           "invested": int(s.sum()), "sorted_in": sorted(r0[0]), "sorted_out": sorted(r0[1])}
    res = {"rule_in_support": bool(all(LO <= x <= hi_in for x in r0[0]) and all(LO <= x <= hi_out for x in r0[1])), "types": {}}
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
            if kind == "N4.9":
                bad["sorted_lengths"] += (sorted(li) != ref["sorted_in"]) or (sorted(lo_) != ref["sorted_out"])
            else:
                bad["bounds"] += (not all(LO <= x <= hi_in for x in li)) or (not all(LO <= x <= hi_out for x in lo_))
        bad = {k: int(v) for k, v in bad.items()}
        res["types"][kind] = {"draws": int(len(arr)), "failures": bad, "pass": bool(sum(bad.values()) == 0)}
    res["pass"] = bool(res["rule_in_support"] and all(v["pass"] for v in res["types"].values()))
    return res


def run_book(bk: Book, dec: pd.DataFrame, states: dict, costs, window: str, cash: str, headline: bool, out: dict, curves: dict):
    idx = dec["decision_idx"].values
    s = dec["state"].values.astype(int)
    sig0 = spell_sig(s)
    f = float(s.mean())
    meta = {kind: [(lens_of(st.astype(int))) + (spell_sig(st.astype(int)), sessions_invested(bk, idx, st)) for st in arr] for kind, arr in states.items()}
    for cost in costs:
        nav, tr, pos = simulate(bk, idx, s.astype(float), cost, record=True)
        st = stats(nav)
        out["rows"].append({"book": bk.parent, "window": window, "cash": cash, "cost_bps": cost, "kind": "strategy", **st,
                            "invested_weeks": int(s.sum()), "trades": len(tr), "cost_paid": sum(t["cost"] for t in tr)})
        out["strategy_raw_gold_trades"] += sum(1 for t in tr if bk.gold_raw[t["idx"]] and t["kind"] != "basket_change")
        if headline:
            out["nav"][(bk.parent, cost, "strategy")] = nav
            out["trades"] += [{"book": bk.parent, "cost_bps": cost, "run": "strategy", **t} for t in tr]
            out["positions"] += [{"book": bk.parent, "cost_bps": cost, "run": "strategy", **p} for p in pos]
            for name, e_arr, every in (("hold_parent", np.ones(len(s)), False), ("constant_mix", np.full(len(s), f), True),
                                       ("sleeve_only", np.zeros(len(s)), False)):
                nv, tr2, _ = simulate(bk, idx, e_arr, cost, every=every, record=True)
                out["rows"].append({"book": bk.parent, "window": window, "cash": cash, "cost_bps": cost, "kind": name, **stats(nv),
                                    "invested_weeks": float(e_arr.sum()), "trades": len(tr2), "cost_paid": sum(t["cost"] for t in tr2)})
                out["nav"][(bk.parent, cost, name)] = nv
                out["trades"] += [{"book": bk.parent, "cost_bps": cost, "run": name, **t} for t in tr2]
        for kind, arr in states.items():
            for d, st_arr in enumerate(arr):
                nv = simulate(bk, idx, st_arr.astype(float), cost)
                ds = stats(nv)
                li, lo_, sg, sess = meta[kind][d]
                out["draws"].append({"book": bk.parent, "window": window, "cash": cash, "cost_bps": cost, "draw_type": kind,
                                     "draw_id": d, **ds, "invested_weeks": int(st_arr.sum()), "n_in_spells": len(li),
                                     "n_out_spells": len(lo_), "spell_sig": sg, "strategy_sig": sig0,
                                     "sessions_invested": sess, "in_lengths": "|".join(map(str, li)), "out_lengths": "|".join(map(str, lo_))})
                if headline and cost == PRIMARY:
                    curves.setdefault(bk.parent, {})[f"{kind}_{d}"] = nv.astype(np.float32)


# ── V4 / V5 ───────────────────────────────────────────────────────────────────
def chi2_sf_even(x: float, df: int) -> float:
    """Survival function of chi-square with an even number of degrees of freedom (closed form)."""
    assert df % 2 == 0
    h, term, tot = x / 2, 1.0, 1.0
    for i in range(1, df // 2):
        term *= h / i
        tot += term
    return math.exp(-h) * tot


def sampler_selftest_small(k=3, S=12, lo=2, hi=6, n=200_000) -> dict:
    """V5(a): enumerate every tuple, draw n samples with the production sampler, chi-square against equal frequencies."""
    tuples = [t for t in np.ndindex(*([hi - lo + 1] * k)) if sum(x + lo for x in t) == S]
    tuples = [tuple(x + lo for x in t) for t in tuples]
    tab = count_table(k, S, lo, hi)
    assert len(tuples) == tab[k][S], (len(tuples), tab[k][S])
    rng = np.random.default_rng([6, 123456789])
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
            "min_count": min(cnt.values()), "max_count": max(cnt.values()), "chi2": chi, "df": df, "p": p, "pass": bool(len(tuples) == 19 and p > 0.001)}


def v4_regression(books, bks, out, dec_all, g4) -> dict:
    """V4: (a) decisions equal T03's on every shared date; (b) strategy, comparators and published NAV equal T03's up to 2026-08-07; (c) always-in G0."""
    t3d = pd.read_csv(T03 / "decisions.csv")
    t3n = pd.read_csv(T03 / "daily_nav.csv")
    res = {"decisions": {}, "nav": [], "g0": g4}
    ok = True
    for dec in dec_all:
        p = dec["book"].iloc[0]
        a = dec.assign(decision_date=dec["decision_date"].astype(str))[["decision_date", "decision_idx", "state"]]
        b = t3d[t3d["book"] == p][["decision_date", "decision_idx", "state"]]
        m = a.merge(b, on="decision_date", how="inner", suffixes=("", "_t03"))
        mism = int(((m["state"] != m["state_t03"]) | (m["decision_idx"] != m["decision_idx_t03"])).sum())
        missing = int((~b["decision_date"].isin(a["decision_date"])).sum())
        res["decisions"][p] = {"t06_decisions": int(len(a)), "t03_decisions": int(len(b)), "shared": int(len(m)), "mismatches": mism, "t03_dates_missing_in_t06": missing}
        ok &= mism == 0 and missing == 0 and len(m) > 0
    for p in books:
        bk, dec = bks[p], next(d for d in dec_all if d["book"].iloc[0] == p)
        d03 = t3n[t3n["book"] == p]
        dates = pd.to_datetime(d03["date"].drop_duplicates())
        cal = bk.cal
        mask = np.asarray(cal <= T03_NAV_END)
        t3_idx = t3d[t3d["book"] == p]
        f03 = float(t3_idx["state"].mean())
        for (run, cost), g in d03.groupby(["run", d03["cost_bps"].fillna(-1)]):
            g = g.assign(date=pd.to_datetime(g["date"])).set_index("date")["nav"]
            if run == "published_D17":
                mine = bk.pub / bk.pub[0]
            elif run == "constant_mix":     # T06-2: re-run with T03's f
                mine = simulate(bk, dec["decision_idx"].values, np.full(len(dec), f03), cost, every=True)
            else:
                mine = out["nav"][(p, cost, run)]
            mine = pd.Series(mine, index=cal)
            common_d = g.index[(g.index <= T03_NAV_END)].intersection(mine.index[mask])
            rel = float((mine.loc[common_d] / g.loc[common_d] - 1).abs().max()) if len(common_d) else float("nan")
            passed = bool(len(common_d) > 0 and rel < REL_TOL_NAV)
            ok &= passed
            res["nav"].append({"book": p, "run": run, "cost_bps": None if cost == -1 else float(cost), "dates_compared": int(len(common_d)),
                               "max_rel_diff": rel, "pass": passed, "stock_share_f_used": f03 if run == "constant_mix" else None})
    res["g0_pass"] = bool(all(r["overall"] == "PASS" and r["yearly"] == "PASS" for r in g4))
    ok &= res["g0_pass"]
    res["nav_rows_compared"] = int(len(res["nav"]))
    res["nav_compared_to"] = str(T03_NAV_END.date())
    res["tolerance_rel"] = REL_TOL_NAV
    res["pass"] = bool(ok)
    return res


def main():
    ap_ = argparse.ArgumentParser()
    ap_.add_argument("--run", default="headline")
    ap_.add_argument("--draws", type=int, default=N_DRAWS)
    ap_.add_argument("--quick", action="store_true", help="smoke test: 1 book, 20 draws")
    a = ap_.parse_args()
    outdir = T06 / "evidence" / a.run
    outdir.mkdir(parents=True, exist_ok=True)
    t_start = time.time()
    books = PARENTS[:1] if a.quick else PARENTS
    n_draws = 20 if a.quick else a.draws
    out = {"rows": [], "draws": [], "nav": {}, "trades": [], "positions": [], "strategy_raw_gold_trades": 0}
    curves: dict = {}
    dec_all, bks = [], {}
    audit = {"readings": READINGS, "books": {}}

    # the data boundary: every input through the approved table, sha256 checked, window covered
    inputs = [HD / "extended_2026-10-30" / "Master" / f"Master_{n}.xlsx" for n in ("Nifty100", "MC100", "SC100")]
    inputs += [AA / "analysis" / "cache" / "why_gold_ohlc_eikon_extended_2026-11-04.parquet",
               AA / "analysis" / "evidence" / "final_strategy" / "mauc1" / "mauc1_daily_clean.csv",
               HD / "LBES_Adjusted_Price_data_extended_2026-11-05.csv", HD / "liquidEtfFinal_extended_2026-11-05.csv", HM / "price_corrections.csv"]
    for p in PARENTS:
        inputs += [HM / f"{p}_{x}.csv" for x in ("ohlc", "holding_weight_matrix", "holding_weight_sources")] + [HD / "parent_nav_2026-10-22" / f"{p}.csv"]
    not_parsed = []
    for p in PARENTS:
        not_parsed += [HM / f"{p}_columns.csv", HD / "frozen_2026-09-25" / "Rebalance_history" / f"Rebalance_history_by_scid_{p}.csv"]
    for f in inputs + not_parsed:
        ap(f)
    for rel, r in USED.items():
        if r["id"] in ("D17", "D18", "D03", "D09", "D11"):
            assert r["through"] >= str(END.date()), f"{rel}: approved through {r['through']}, before the window's end {END.date()}: stop and ask Manu"
    pd.DataFrame([{k: v[k] for k in ("file", "through", "bytes", "sha256", "approved_row")} for v in USED.values()]).to_csv(outdir / "inputs.csv", index=False)
    selftest = {}
    for name, f in (("superseded_master", HD / "frozen_2026-09-25" / "Master" / "Master_Nifty100.xlsx"),
                    ("superseded_goldbees", AA / "analysis" / "cache" / "why_gold_ohlc_eikon.parquet"),
                    ("superseded_lbes", HD / "LBES_Adjusted_Price_data_2026_08_10.csv"),
                    ("not_in_table", HD / "no_such_file.csv")):
        try:
            ap(f)
            selftest[name] = {"raised": False}
        except NotApprovedError as e:
            selftest[name] = {"raised": True, "message": str(e)}
    selftest["pass"] = all(v["raised"] for v in selftest.values() if isinstance(v, dict))
    print(f"data: END = {END.date()} (D17), approved data as of {AD.as_of()}, {len(USED)} inputs checked; non-approved open raises: {selftest['pass']}", flush=True)

    ct, v3_res, v5c = {}, {}, {}
    states_all: dict = {}
    hb = None
    for p in books:
        t1 = time.time()
        bk = Book(p)
        bks[p] = bk
        dec = bk.decisions()
        dec_all.append(dec)
        s = dec["state"].values.astype(int)
        hi_in, hi_out = rule_bounds(s)
        if hb is None:
            hb = (hi_in, hi_out)
        assert (hi_in, hi_out) == hb, f"{p}: bounds {(hi_in, hi_out)} differ from the first book's {hb}"
        # V2: point-in-time counts
        lab_ok = int((pd.to_datetime(dec["latest_label"]) <= pd.to_datetime(dec["decision_date"])).sum())
        trade_idx = dec["decision_idx"].values + 1
        traded_rows = int((trade_idx < bk.T).sum())
        tdates = pd.to_datetime(dec["trade_date"].dropna())
        ddates = pd.to_datetime(dec.loc[dec["trade_date"].notna(), "decision_date"])
        assert (tdates.values > ddates.values).all()
        assert (pd.to_datetime(dec["latest_label"]).values <= pd.to_datetime(dec["decision_date"]).values).all()
        r0 = lens_of(s)
        audit["books"][p] = {"t0": str(bk.t0.date()), "last_session": str(bk.cal[-1].date()), "sessions": bk.T, "decisions": len(dec), "invested_weeks": int(s.sum()),
                             "first_state": int(s[0]), "in_lengths": r0[0], "out_lengths": r0[1], "bounds": {"lo": LO, "hi_in": hi_in, "hi_out": hi_out},
                             "in_spells": len(r0[0]), "out_spells": len(r0[1]), "round_trips": min(len(r0[0]), len(r0[1])),
                             "sessions_invested_rule": sessions_invested(bk, dec["decision_idx"].values, s),
                             "v2_decisions_checked": len(dec), "v2_label_after_decision": len(dec) - lab_ok,
                             "v2_trades_checked": traded_rows, "v2_trade_not_after_decision": int((tdates.values <= ddates.values).sum()),
                             "stale_label_weeks(age>=5d, excluding T0)": int((dec["label_age_days"].values[1:] >= 5).sum()),
                             "initial_basket_switch_session": bk.initial_basket_switch_session, "cash": bk.cash_info,
                             "skipped_baskets_dropped": [str(x.date()) for x in raw_parent(p)["skipped"]]}
        # tables, states, V3 for the full window
        st_full = make_states(s, n_draws, hi_in, hi_out)
        states_all[f"{p}|full|N4.9"], states_all[f"{p}|full|N4.10"] = st_full["N4.9"], st_full["N4.10"]
        v3_res[f"{p}|full"] = v3_check(s, st_full, hi_in, hi_out)
        bk.nobar_trades = 0
        bk.raw_gold_trades = 0
        run_book(bk, dec, st_full, COSTS, "full", "lbes", True, out, curves)
        audit["books"][p]["stock_trades_priced_by_last_close_no_bar_that_session(all runs incl. draws)"] = bk.nobar_trades
        audit["books"][p]["goldbees_trades_filled_at_raw_OHLC4_after_MCX_file(all runs incl. draws, headline LBES)"] = bk.raw_gold_trades
        # R2: LIQUIDCASE cash: the full-window states are reused
        bk3 = Book(p, cash="liq")
        run_book(bk3, dec, st_full, (PRIMARY,), "full", "liquidcase", False, out, curves)
        # R3: live window, its own spells and totals, the same bounds
        bk4 = Book(p, start=LIVE_START)
        dec4 = bk4.decisions()
        s4 = dec4["state"].values.astype(int)
        r4 = lens_of(s4)
        rt = min(len(r4[0]), len(r4[1]))
        audit["books"][p]["live_window"] = {"t0": str(bk4.t0.date()), "decisions": len(dec4), "round_trips": rt, "reportable": bool(rt >= 4),
                                            "first_state": int(s4[0]), "in_lengths": r4[0], "out_lengths": r4[1],
                                            "sessions_invested_rule": sessions_invested(bk4, dec4["decision_idx"].values, s4)}
        windows = [("full", s, hi_in, hi_out)]
        if rt >= 4:
            windows.append(("live", s4, hi_in, hi_out))
            st_live = make_states(s4, n_draws, hi_in, hi_out)
            states_all[f"{p}|live|N4.9"], states_all[f"{p}|live|N4.10"] = st_live["N4.9"], st_live["N4.10"]
            v3_res[f"{p}|live"] = v3_check(s4, st_live, hi_in, hi_out)
            run_book(bk4, dec4, st_live, (PRIMARY,), "live", "lbes", False, out, curves)
        # count table, inclusion-exclusion, per-position means (V5 b, c)
        for w, sw, hin, hout in windows:
            rr = lens_of(sw)
            for stn, ls, hi in (("in", rr[0], hin), ("out", rr[1], hout)):
                k, S = len(ls), sum(ls)
                tab = count_table(k, S, LO, hi)
                n_dp, n_ie = int(tab[k][S]), ie_count(k, S, LO, hi)
                ct[f"{p}|{w}|{stn}"] = {"book": p, "window": w, "state": stn, "weeks_S": S, "spells_k": k, "lo": LO, "hi": hi,
                                        "feasible_2k<=S<=hi*k": bool(2 * k <= S <= hi * k), "n_ways": str(n_dp), "n_ways_inclusion_exclusion": str(n_ie),
                                        "dp_equals_inclusion_exclusion": n_dp == n_ie, "rule_lengths_within_bounds": bool(all(LO <= x <= hi for x in ls))}
                arr = states_all[f"{p}|{w}|N4.10"]
                pos = [lens_of(st.astype(int))[0 if stn == "in" else 1] for st in arr]
                M = np.array(pos, dtype=float)                       # (draws, k)
                sd = M.std(axis=0, ddof=1) if len(M) > 1 else np.zeros(M.shape[1])
                se = sd / math.sqrt(len(M))
                dev = np.abs(M.mean(axis=0) - S / k)
                z = np.where(se > 0, dev / np.where(se > 0, se, 1), np.where(dev > 0, np.inf, 0.0))
                v5c[f"{p}|{w}|{stn}"] = {"draws": int(len(M)), "target_S_over_k": S / k, "mean_over_positions_and_draws": float(M.mean()),
                                         "max_abs_z_per_position": float(z.max()), "pass": bool(z.max() <= 4.0)}
        print(f"{p}: {time.time() - t1:.0f}s  decisions {len(dec)}  in-spells {audit['books'][p]['in_spells']}  round trips {audit['books'][p]['round_trips']}", flush=True)

    # V4(c): always-in at 0 cost against the published NAV (G0)
    g4 = []
    for p in books:
        bk = bks[p]
        nav = simulate(bk, np.array([0]), np.ones(1), 0.0)
        c = pd.DataFrame({"m": nav, "p": bk.pub}, index=bk.cal)
        c = c / c.iloc[0] * 100
        yrs = (c.index[-1] - c.index[0]).days / 365.25
        gap = ((c.m.iloc[-1] / c.m.iloc[0]) ** (1 / yrs) - (c.p.iloc[-1] / c.p.iloc[0]) ** (1 / yrs)) * 100
        worst, wy = 0.0, None
        for yr, g in c.groupby(c.index.year):
            prev = c.loc[:g.index[0]].iloc[-2] if len(c.loc[:g.index[0]]) > 1 else g.iloc[0]
            d = (g["m"].iloc[-1] / prev["m"] - g["p"].iloc[-1] / prev["p"]) * 100
            if abs(d) > abs(worst):
                worst, wy = d, int(yr)
        g4.append({"book": p, "cagr_gap_pp_yr": gap, "overall": "PASS" if abs(gap) <= G0_OVERALL else "FAIL", "worst_year": wy,
                   "worst_year_gap_pp": worst, "yearly": "PASS" if abs(worst) <= G0_YEARLY else "FAIL",
                   "max_rel_diff_vs_step1_rebuild": float("nan"), "rebuild_dates_compared": 0,
                   "window_first": str(c.index[0].date()), "window_last": str(c.index[-1].date())})
    pd.DataFrame(g4).to_csv(outdir / "g_engine.csv", index=False)

    # V4 regression, V5 sampler, V3 summary
    reg = v4_regression(books, bks, out, dec_all, g4)
    (outdir / "regression_t03.json").write_text(json.dumps(reg, indent=1, default=str), encoding="utf-8")
    small = sampler_selftest_small()
    v5b = all(v["dp_equals_inclusion_exclusion"] for v in ct.values())
    v5 = {"a_small_case": small, "b_dp_equals_inclusion_exclusion": {"all_equal": bool(v5b), "checked": int(len(ct))},
          "c_mean_length_within_4_se": v5c, "pass": bool(small["pass"] and v5b and all(v["pass"] for v in v5c.values()))}
    (outdir / "sampler_selftest.json").write_text(json.dumps(v5, indent=1, default=str), encoding="utf-8")
    (outdir / "count_table.json").write_text(json.dumps({"bounds": {"lo": LO, "hi_in": hb[0], "hi_out": hb[1]}, "tables": ct}, indent=1), encoding="utf-8")

    # step-1 spell counts reproduced from the data
    s1 = json.loads((T06 / "logs" / "step_1_spell_counts.json").read_text(encoding="utf-8"))
    s1_ok, s1_detail = True, {}
    for p in books:
        e = s1["books"][p]
        for w, key in (("full", "full"), ("live", "live_window")):
            mine = audit["books"][p] if w == "full" else audit["books"][p]["live_window"]
            exp = e[w]
            good = (mine["in_lengths"] == exp["in_lengths"] and mine["out_lengths"] == exp["out_lengths"] and mine["first_state"] == exp["first_state"]
                    and mine["decisions"] == exp["weeks"])
            s1_detail[f"{p}|{w}"] = bool(good)
            s1_ok &= good
    s1_ok &= (hb[0], hb[1]) == (s1["bounds"]["hi_in"], s1["bounds"]["hi_out"])

    # write
    pd.concat(dec_all).to_csv(outdir / "decisions.csv", index=False)
    rows = pd.DataFrame(out["rows"])
    rows.to_csv(outdir / "stats.csv", index=False)
    dr = pd.DataFrame(out["draws"])
    dr.to_csv(outdir / "draws.csv", index=False)
    pd.DataFrame(out["trades"]).to_csv(outdir / "trades.csv", index=False)
    pd.DataFrame(out["positions"]).to_csv(outdir / "positions.csv", index=False)
    daily = []
    for (p, cost, name), nv in out["nav"].items():
        daily.append(pd.DataFrame({"book": p, "date": bks[p].cal, "cost_bps": cost, "run": name, "nav": nv}))
    for p in books:
        daily.append(pd.DataFrame({"book": p, "date": bks[p].cal, "cost_bps": np.nan, "run": "published_D17", "nav": bks[p].pub / bks[p].pub[0]}))
    pd.concat(daily).to_csv(outdir / "daily_nav.csv", index=False)
    np.savez_compressed(outdir / "draw_curves_20.8.npz", **{f"{p}|{k}": v for p, d in curves.items() for k, v in d.items()})
    np.savez_compressed(outdir / "draw_states.npz", **states_all)

    # audit
    c_ = common()
    v3_ok = all(v["pass"] for v in v3_res.values())
    cashn = cash_note()
    audit["v3"] = {"per_book_window": v3_res, "pass": bool(v3_ok), "rule_in_support": {k: v["rule_in_support"] for k, v in v3_res.items()},
                   "draws_per_type": int(n_draws)}
    audit["v4"] = {"pass": reg["pass"], "g0": g4}
    audit["v5"] = {"pass": v5["pass"]}
    audit["data"] = {"approved_data_as_of": AD.as_of(), "end_from_D17": str(END.date()), "inputs": int(len(USED)),
                     "registered_not_parsed": [x.relative_to(AA).as_posix() for x in not_parsed],
                     "non_approved_open_raises": selftest, "cash_accrued_sessions": 0, "cash_first_appended_row": cashn,
                     "goldbees": {"mcx_file_last": str(c_["mcx_last"].date()), "goldbees_file_last": str(c_["gold_data_last"].date()),
                                  "sessions_after_mcx_in_goldbees_file": c_["gold_raw_sessions_in_data"],
                                  "sessions_after_mcx_in_window_calendar": [str(d.date()) for d in bks[books[0]].cal[bks[books[0]].gold_raw]],
                                  "strategy_trades_with_raw_OHLC4_gold_fill(all costs, full+live+liq windows)": out["strategy_raw_gold_trades"],
                                  "trades_with_raw_OHLC4_gold_fill_by_book(all runs, draws included, headline LBES run)":
                                      {p: audit["books"][p]["goldbees_trades_filled_at_raw_OHLC4_after_MCX_file(all runs incl. draws, headline LBES)"] for p in books}}}
    audit["step1_spell_counts_reproduced"] = {"pass": bool(s1_ok), "detail": s1_detail}
    audit["run"] = {"name": a.run, "draws": n_draws, "seconds": round(time.time() - t_start), "quick": a.quick,
                    "seeds": "N4.9 numpy default_rng([3, draw_id]); N4.10 numpy default_rng([6, draw_id]); the same draw ids for every cost, window and cash variant"}
    audit["prereg_sha256"] = (T06 / "T06.md").read_text(encoding="utf-8").split("§1–§3 sha256:** `")[1].split("`")[0]
    ok = bool(v3_ok and reg["pass"] and v5["pass"] and selftest["pass"] and s1_ok)
    audit["gates"] = {"V3": bool(v3_ok), "V4": reg["pass"], "V5": v5["pass"], "approved_data_selftest": selftest["pass"], "step1_counts": bool(s1_ok), "all": ok}
    (outdir / "audit.json").write_text(json.dumps(audit, indent=1, default=str), encoding="utf-8")

    print(rows[rows["kind"] == "strategy"][["book", "window", "cash", "cost_bps", "cagr", "max_dd", "end_nav", "trades"]].round(4).to_string(index=False))
    print(pd.DataFrame(g4).round(3).to_string(index=False))
    print("V3", {k: v["pass"] for k, v in v3_res.items()})
    print("V4", {"decisions": reg["decisions"], "nav_rows": reg["nav_rows_compared"], "max_rel_diff": max(r["max_rel_diff"] for r in reg["nav"]), "g0": reg["g0_pass"], "pass": reg["pass"]})
    print("V5", {"small_p": small["p"], "ie_equal": v5b, "mean_check": all(v["pass"] for v in v5c.values()), "pass": v5["pass"]})
    for k, v in ct.items():
        if v["window"] == "full":
            print(f"  n_ways {k}: {v['n_ways']}")
    print(f"gates: {audit['gates']}")
    print(f"done in {time.time() - t_start:.0f}s -> {outdir}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
