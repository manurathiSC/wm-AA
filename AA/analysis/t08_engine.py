# -*- coding: utf-8 -*-
"""T08 engine: the three-index switch (T06's rule) with a MAUc1-timed GOLDBEES / cash sleeve, against one null per timing.

A FORK of analysis/t06_engine.py (copied, not imported). The only change to the rule is the sleeve while OUT: 80% GOLDBEES / 20% cash
when the weekly MAUc1 supertrend (D24) is BUY, 20% / 80% when it is SELL, changed only when the signal changes. Every data file is opened
through `approved_data.require()` (an APPROVED row of data/APPROVED_DATA.md), its sha256 prefix is checked against the row, and the window's
end is the last row of the D03 Master files (2026-10-30). Pre-registration: tests/T08/T08.md sections 1-3 (frozen;
`python tests/T08/check_prereg.py`); plan: tests/T08/PLAN.md; evidence contract: tests/T08/logs/evidence_contract.md.

    python analysis/t08_engine.py [--run NAME] [--draws N] [--quick] [--books SCMO_0003 ...]      (from AA/)

Null families (2,000 draws per book; the same draw id for every cost):
    F1  in-or-out N4.10 (seed [6, id]) + the real gold signal          decides C1, C2
    F2  in-or-out N4.9  (seed [3, id]) + the real gold signal          beside F1
    F3  the real in-or-out switch + gold N4.10-g (seed [11, 6, id])    decides C3, C4
    F4  the real in-or-out switch + gold N4.9-g  (seed [11, 3, id])    beside F3
    F5  F1's in-or-out draw + F3's gold draw, same id                  robustness (R5)
    (F1 and F2 are also run with the sleeve fixed at 50/50 for R6.)
The in-or-out samplers are T06's functions unchanged; the gold samplers are the same functions applied to the gold series (state 1 = BUY)
with the series' own (k, S, bounds).

Trade rule (one function, `trade`): at a trade session t, with fill prices (stocks OHLC4, GOLDBEES de-spiked OHLC4, cash at its level),
V = value of all holdings at those prices. Target values: stocks e*V*w_i, GOLDBEES (1-e)*gw*V, cash (1-e)*(1-gw)*V. traded = sum |target - held|
over every line; cost = traded * cost_bps/2/1e4; every target is then scaled by (V-cost)/V. gw is the decision's gold weight (0.8 BUY, 0.2
SELL; 0.5 in `fixed50` mode, which reproduces T06 exactly). A trade exists on the next session after decision j iff e changed or (e < 1 and
gw changed): switch_in, switch_out, or sleeve_rebalance (OUT on both sides, gold signal changed); a flip while IN is not a trade.

Writes tests/T08/evidence/<run>/ (see tests/T08/logs/evidence_contract.md): inputs.csv, decisions.csv, gold_signal.csv, stats.csv, draws.csv,
draw_states.npz, real_states.npz, draw_curves_20.8.npz, trades.csv, sleeve_trades.csv, positions.csv, daily_nav.csv, g_engine.csv,
count_table.json, sampler_selftest.json, regression_t06.json, audit.json.
"""
from __future__ import annotations

import argparse
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
T06 = AA / "tests" / "T06"
T06E = T06 / "evidence" / "headline"      # read-only reference for V4
T08 = AA / "tests" / "T08"
PARENTS = ["SCMO_0003", "SCMO_0007", "SCMO_0010", "SCMO_0029"]
LIVE_START = pd.Timestamp("2021-11-01")
COSTS = (0.0, 20.8, 50.0)
PRIMARY = 20.8
N_DRAWS = 2000
LO = 2                       # shortest spell: 2 weeks = 14 days (T08.md section 2)
DESPIKE_TOL = 0.005
LIQ_FROM = pd.Timestamp("2024-01-24")        # R2: LIQUIDCASE replaces LBES from this session
T06_NAV_END = pd.Timestamp("2026-10-22")     # V4(b): T06's NAVs are compared up to here (T06's window ended on this session)
LBES_VERBATIM_LAST = pd.Timestamp("2026-08-09")   # APPROVED_DATA.md, D11 note: rows to here are the supplied LBES file, later rows are appended
G0_OVERALL, G0_YEARLY = 0.25, 0.5            # pp / yr
REL_TOL_NAV = 1e-12
REL_TOL_F32 = 1e-6                           # V4(c): T06's draw curves are stored as float32
GW_BUY, GW_SELL, GW_FIX = 0.8, 0.2, 0.5      # gold weight of the sleeve: BUY, SELL, fixed50 mode
IO_BOUNDS_EXPECTED = (46, 40)                # T08.md section 3 step 11
GOLD_BOUNDS_EXPECTED = (68, 28)              # BUY, SELL: the real gold series' longest spells (T08.md section 2)
SEED_IO_49, SEED_IO_410 = (3,), (6,)         # T06's seeds: [3, id], [6, id]
SEED_G_49, SEED_G_410 = (11, 3), (11, 6)     # gold seeds: [11, 3, id], [11, 6, id]
OLD_D17_DIR = HD / "parent_nav_2026-10-22"
NEW_D17_DIR = HD / "extended_2026-11-06" / "published_nav"
D24_DIR = HD / "extended_2026-11-06" / "MAUc1"

READINGS = {
    "E1": "calendar = D17's dates (the EXTENDED published NAVs) of the book from its first date to END; END = the last row of the three D03 Master files (2026-10-30), not D17's last date; "
          "rows after END are dropped on read and never used; D18 prices on other dates are never read",
    "E2": "decision dates = T0 and the last D17 session of every later ISO week; the decision at the last session is not traded",
    "E3": "label = latest Master row dated <= decision date, per index and for MAUc1 (D24); IN iff all three index SIGN are BUY; g = BUY iff the MAUc1 SIGN is BUY (a week whose row is dated after "
          "its last D17 session reads the previous week's row)",
    "E4": "initial position at T0 close, no cost: OUT = gw GOLDBEES and (1-gw) cash of NAV 1 with gw = 0.8 (g BUY at T0) or 0.2 (SELL), 0.5 in fixed50 mode; IN = the basket in force at T0 as drifted since its "
          "availableDate (OHLC4 of the first D18 session on or after it), scaled to NAV 1",
    "E5": "a basket takes effect on the first calendar session on or after its availableDate; baskets flagged csv_only_skipped are dropped; "
          "weights are renormalised to 1",
    "E6": "stock fill = OHLC4 of the Eikon bar (close if any of open/high/low is blank; last close if the stock has no bar that session)",
    "E7": "costs: one rule for every trade, see the module docstring (cost on the value traded, targets scaled by (V-cost)/V)",
    "E8": "a basket change while IN trades from the old holdings to the new basket (delta trades); while OUT nothing is traded; a flip of g while IN is not a trade",
    "E9": "a switch and a basket change on the same session: the switch trades into / out of the basket in force that session",
    "E10": "cash level: the extended LBES (D11) as-of on sessions; it covers the window and the engine asserts that no session of any window lies after the file's last date (0 accrued sessions)",
    "E11": "constant mix: stock share f = invested decision weeks / decision weeks, rebalanced at every decision date's next session (T0 included) and at every basket change; "
           "constant_mix splits the non-stock share 50/50, constant_mix_timed by the decision's gw; initial stock holding = drifted basket scaled by f",
    "E13": "R3 live window starts at the first D17 session on or after 2021-11-01 with its own spells and totals (in-or-out and gold), own draws (same seeds), the SAME bounds (the book's full-window "
           "HI_in, HI_out, HI_buy, HI_sell) and free initial position in the state decided then",
    "E14": "R2 cash = LBES to the session before 2024-01-24, then chained with the desk's LIQUIDCASE returns on sessions (liquidEtfFinal_extended)",
    "E15": "V4(d) always-in runs on the whole window (to END = 2026-10-30); G0 = +-0.25 pp/yr overall and +-0.5 pp every calendar year",
    "E16": "GOLDBEES fill: T03's de-spike (OHLC4 of open/high/low clipped to MCX gold's range that day + 0.5%) on every session up to the MCX file's last date (2026-09-28); on later sessions the raw OHLC4 of the "
           "Eikon bar, no clipping, no scaling, no tolerance band",
    "T06-1": "sessions_invested = number of daily returns t = 1..T-1 earned while the parent is held (state j is held from its trade session dec_idx[j]+1; T0 for j = 0)",
    "T06-4": "the sampler draws one uniform per part, including the last part (whose length is forced), so a draw consumes k uniforms; cumulative probabilities are exact integer prefix sums divided by the "
             "exact total, searchsorted side='right' (T06's functions, unchanged; the gold draws call them with the gold seed and the gold (k, S, bounds))",
    "T06-5": "V5(c): the sum of the lengths of a draw is fixed, so the check is made per spell position: the mean of its length over the draws within 4 standard errors of S/k (in-or-out and gold)",
    "T06-7": "window-coverage check: the through-date of every approved file the run reads must reach END, except D12 (the de-spike range, raw OHLC4 after it), the basket files D19/D05 (through the newest "
             "basket) and the OLD D17 files (pinned, read only for V4(e)); D17/D24 files are read only up to END",
    "T06-8": "the 'weeks' of draw_states.npz and of every V3/V5 statement are the weekly decision rows (410 for SCMO_0003/0010/0029, 409 for SCMO_0007 on the full window)",
    "T08-1": "gold bounds: lo = LO = 2 (= the shortest actual gold spell), hi_buy and hi_sell = the longest BUY and SELL spell of each book's own full-window gold series, asserted to be 68 and 28 "
             "(the in-or-out bounds are asserted to be 46 and 40); the live window uses the same bounds",
    "T08-2": "trade log columns: gw_after = the sleeve's gold weight target after the trade (0.8 / 0.2 / 0.5) on every row of every run except hold_parent, where it is empty; on a switch_in row it is the "
             "gold weight of that decision (irrelevant to the position, which holds no sleeve)",
    "T08-3": "V4: T06's last decision (2026-10-22, a Thursday, the last session of its calendar) is compared with T08's decision of 2026-10-23 (the same week); T08's j-th decision equals T06's for j <= 408 and "
             "T06's draw states get T08's real state of the extra last week appended (the decision of 2026-10-30, not traded)",
    "T08-4": "the number of sleeve trades of a draw (draws.csv sleeve_trades) is counted from the states: decisions j >= 1 with a trade session inside the window, OUT at j-1 and j, and g[j] != g[j-1]; it is 0 in "
             "fixed50 mode. The engine checks this count against the recorded trades of the real rule (V6)",
    "T08-5": "V4(c): T06's draw curves are float32, so they are compared after casting the replayed NAV to float32 (relative tolerance 1e-6); T06's states are 409 weeks, replayed with T08's decision of that week "
             "(2026-10-23), the NAV compared on the sessions up to 2026-10-22",
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


def _read_index_masters() -> tuple[dict, pd.Timestamp]:
    """The three extended D03 Master files (SIGN per weekly review). END = their last row (all three must agree)."""
    ms = {}
    for n in ("Nifty100", "MC100", "SC100"):
        d = pd.read_excel(ap(HD / "extended_2026-10-30" / "Master" / f"Master_{n}.xlsx"), parse_dates=["Date"])
        s = d.dropna(subset=["SIGN"]).set_index("Date")["SIGN"].sort_index()
        ms[n] = s[~s.index.duplicated(keep="last")]
    ends = {n: s.index.max() for n, s in ms.items()}
    assert len(set(ends.values())) == 1, f"the three D03 Master files end on different dates: {ends}"
    return ms, next(iter(ends.values()))


_INDEX_MASTERS, END = _read_index_masters()      # END = the last D03 row (2026-10-30), not D17's last date
V4_END = END                                     # always-in (V4d) runs on the whole window


def read_pub(path, cut: bool = True) -> pd.Series:
    """A published-NAV file (D17, extended or old format: columns _id.scid, _id.date, index; any row order). cut=True drops rows after END."""
    n = pd.read_csv(ap(path))
    pub = pd.Series(n["index"].values, index=pd.to_datetime(n["_id.date"], format="%Y/%m/%d")).sort_index()
    assert (n["_id.scid"] == Path(path).stem).all(), f"{path}: scid column is not {Path(path).stem}"
    assert not pub.index.duplicated().any()
    return pub[pub.index <= END] if cut else pub


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
    assert o["date"].max() >= END, f"{p}: D18 ends {o['date'].max().date()} before END"
    o = o[o["date"] <= END]                                  # nothing after END is used
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
    pub_full = read_pub(NEW_D17_DIR / f"{p}.csv", cut=False)
    assert pub_full.index.max() >= END, f"{p}: the extended D17 ends {pub_full.index.max().date()} before END {END.date()}"
    pub = pub_full[pub_full.index <= END]                    # nothing after END is used
    assert o["date"].max() >= END, f"{p}: D18 ends {o['date'].max().date()} before END"
    _RAW[p] = dict(W=wm, stocks=stocks, close=close, ohlc4=ohlc4, pub=pub, skipped=sorted(skipped), d17_last=pub_full.index.max())
    return _RAW[p]


_COMMON: dict = {}


def common() -> dict:
    """Gold (D09 extended + D12 de-spike), cash (D11 extended), the three extended Master files (D03), the MAUc1 Master (D24)."""
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
    ms = {n: s[s.index <= END] for n, s in _INDEX_MASTERS.items()}
    gd = pd.read_excel(ap(D24_DIR / "Master_MAUc1.xlsx"), parse_dates=["Date"])           # D24: the weekly MAUc1 supertrend (SIGN)
    gs = gd.dropna(subset=["SIGN"]).set_index("Date")["SIGN"].sort_index()
    gs = gs[~gs.index.duplicated(keep="last")]
    assert gs.index.max() >= END, f"Master_MAUc1 ends {gs.index.max().date()} before END"
    assert set(gs.unique()) <= {"BUY", "SELL"}, gs.unique()
    gm_after = int((gs.index > END).sum())
    gm_last = gs.index.max()
    gs = gs[gs.index <= END]                                                               # nothing after END is used
    assert g.index.max() >= END and lb.index.max() >= END and lq.index.max() >= END
    _COMMON.update(gclose=g["close"], gfill=gfill, lbes=lb, liq=lq, master=ms, gold_master=gs, gold_master_last=gm_last, gold_master_rows_after_end=gm_after, mcx_last=mcx_last,
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
        gm = common()["gold_master"]
        rows = []
        for j, i in enumerate(idx):
            d = cal[i]
            lab, state = {}, 1
            for n, s in ms.items():
                k = s.index.searchsorted(d, side="right") - 1
                lab[n] = (s.index[k], s.iloc[k])
                state &= int(s.iloc[k] == "BUY")
            ld = max(v[0] for v in lab.values())
            kg = gm.index.searchsorted(d, side="right") - 1          # E3: latest MAUc1 row dated <= the decision date
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
    ngu, ncu = k * Tg / gp, k * Tc / lv
    stock_after = float((new_u * ps).sum())
    return new_u, ngu, ncu, dict(V=V, traded=traded, cost=cost, stock_before=float(held_s.sum()), gold_before=float(gu * gp), cash_before=float(cu * lv),
                                 stock_after=stock_after, gold_after=float(ngu * gp), cash_after=float(ncu * lv), V_after=stock_after + float(ngu * gp) + float(ncu * lv))


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
    T06's function; seed [3, id] for the in-or-out series, [11, 3, id] for the gold series (state 1 = BUY)."""
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


# ── N4.10: free spell lengths ─────────────────────────────────────────────────
def rule_bounds(s_full: np.ndarray) -> tuple[int, int]:
    """HI_in, HI_out: the longest in-spell and out-spell of the rule's own full-window series (46 and 40); for the gold series the longest BUY and SELL spell (68 and 28)."""
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


def free_length_draw(s: np.ndarray, draw_id: int, hi_in: int, hi_out: int, lo: int = LO, seed: tuple = SEED_IO_410) -> np.ndarray:
    """N4.10: k_in, k_out, S_in, S_out and the first state come from `s`; lengths in [lo, hi] uniform over ordered tuples; alternate from s[0]."""
    s = np.asarray(s).astype(int)
    r = spells(s)
    k = {1: sum(1 for v, _ in r if v == 1), 0: sum(1 for v, _ in r if v == 0)}
    S = {1: sum(c for v, c in r if v == 1), 0: sum(c for v, c in r if v == 0)}
    hi = {1: hi_in, 0: hi_out}
    rng = np.random.default_rng([*seed, draw_id])      # [6, id] in-or-out (T06), [11, 6, id] gold (BUY lengths first, then SELL)
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
FAMILIES = {"F1": ("N4.10", "real"), "F2": ("N4.9", "real"), "F3": ("real", "N4.10-g"), "F4": ("real", "N4.9-g"), "F5": ("N4.10", "N4.10-g")}
SLEEVE_KINDS = ("switch_out", "sleeve_rebalance")


def make_states_io(s: np.ndarray, n: int, hi_in: int, hi_out: int) -> dict:
    """The weekly in-or-out states of every draw of F1/F2/F5 (T06's samplers, unchanged): {type: uint8 (n, weeks)}."""
    return {"N4.9": np.array([spell_shuffle(s, d, SEED_IO_49) for d in range(n)], dtype=np.uint8),
            "N4.10": np.array([free_length_draw(s, d, hi_in, hi_out, LO, SEED_IO_410) for d in range(n)], dtype=np.uint8)}


def make_states_gold(g: np.ndarray, n: int, hi_buy: int, hi_sell: int) -> dict:
    """The weekly gold states of every draw of F4/F3/F5 (the same samplers on the gold series, state 1 = BUY, gold seeds)."""
    return {"N4.9-g": np.array([spell_shuffle(g, d, SEED_G_49) for d in range(n)], dtype=np.uint8),
            "N4.10-g": np.array([free_length_draw(g, d, hi_buy, hi_sell, LO, SEED_G_410) for d in range(n)], dtype=np.uint8)}


def v3_check(s: np.ndarray, states: dict, hi_in: int, hi_out: int) -> dict:
    """V3 on every draw of both nulls for one series (T08.md section 2, gate V3). For a gold series 'in' = BUY and 'out' = SELL."""
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
            if kind.startswith("N4.9"):
                bad["sorted_lengths"] += (sorted(li) != ref["sorted_in"]) or (sorted(lo_) != ref["sorted_out"])
            else:
                bad["bounds"] += (not all(LO <= x <= hi_in for x in li)) or (not all(LO <= x <= hi_out for x in lo_))
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


def run_book(bk: Book, dec: pd.DataFrame, sio: dict, sgo: dict, window: str, cash: str, plan: list, headline: bool, out: dict, curves: dict):
    """plan = [(family, cost, sleeve_mode)]. Strategy at every cost of `costs` (all three on the headline cell, else the primary only);
    comparators on the headline cell; every draw of every planned family."""
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
        return {"book": bk.parent, "window": window, "cash": cash, "cost_bps": cost, "kind": name, **stats(nv), "invested_weeks": inv, "trades": len(tr),
                "cost_paid": sum(t["cost"] for t in tr), "sleeve_trades": sum(1 for t in tr if t["kind"] == "sleeve_rebalance")}

    for cost in costs:
        nav, tr, pos = simulate(bk, idx, sf, cost, record=True, gw=gw_real)
        out["rows"].append(stat_row("strategy", cost, nav, tr, int(s.sum())))
        out["strategy_raw_gold_trades"] += sum(1 for t in tr if bk.gold_raw[t["idx"]] and t["kind"] != "basket_change")
        for t in tr:
            if t["dec_j"] is not None:
                assert t["idx"] > idx[t["dec_j"]], "V2: a trade is not after its decision"
                out["v2_trades"] += 1
        if headline:
            out["nav"][(bk.parent, cost, "strategy")] = nav
            out["trades"] += [{"book": bk.parent, "cost_bps": cost, "run": "strategy", **t} for t in tr]
            out["positions"] += [{"book": bk.parent, "cost_bps": cost, "run": "strategy", **p} for p in pos]
            for t in tr:
                if t["kind"] in SLEEVE_KINDS:
                    j = t["dec_j"]
                    out["sleeve_trades"].append({
                        "book": bk.parent, "cost_bps": cost, "decision_date": dts[j], "date": str(t["date"]), "kind": t["kind"], "g_before": int(g[j - 1]), "g_after": int(g[j]),
                        "gw_before": float(gw_real[j - 1]), "gw_after": float(gw_real[j]), "gold_value_before": t["gold_before"], "cash_value_before": t["cash_before"],
                        "gold_value_after": t["gold_after"], "cash_value_after": t["cash_after"], "traded": t["traded"], "cost": t["cost"], "gold_fill_raw": bool(bk.gold_raw[t["idx"]])})
            for name, e_arr, every, gwv in (("strategy_fixed50", sf, False, None), ("hold_parent", np.ones(len(s)), False, None), ("constant_mix", np.full(len(s), f), True, None),
                                            ("constant_mix_timed", np.full(len(s), f), True, gw_real), ("sleeve_only", np.zeros(len(s)), False, None),
                                            ("sleeve_only_timed", np.zeros(len(s)), False, gw_real)):
                nv, tr2, _ = simulate(bk, idx, e_arr, cost, every=every, record=True, gw=gwv)
                out["rows"].append(stat_row(name, cost, nv, tr2, float(e_arr.sum())))
                out["nav"][(bk.parent, cost, name)] = nv
                out["trades"] += [{"book": bk.parent, "cost_bps": cost, "run": name, **t} for t in tr2]

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


def d24_weekly() -> pd.DataFrame:
    w = pd.read_csv(ap(D24_DIR / "mauc1_supertrend_weekly_extended.csv"), parse_dates=["review"])
    w = w[w["review"] <= END].sort_values("review").reset_index(drop=True)
    return w


def v6_check(out: dict, books, bks: dict, dec_all: list) -> dict:
    """V6 the sleeve identity, on every trade of every headline run (full window, LBES) and on constant-g re-runs."""
    TOL = 1e-12
    worst = {"cost_identity": 0.0, "value_conservation": 0.0, "stock_target_gap": 0.0, "gold_target_gap": 0.0, "cash_target_gap": 0.0, "traded_identity": 0.0,
             "continuity_0cost": 0.0, "weight_gap_vs_table": 0.0}
    kinds, n = Counter(), 0
    n0 = 0
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
    # the real rule's sleeve trades are exactly the OUT-OUT g changes, at every cost
    count_ok, listed = True, {}
    for p in books:
        d = decs[p]
        idx, s, g = d["decision_idx"].values, d["state"].values.astype(int), d["g"].values.astype(int)
        T = bks[p].T
        exp = sorted(int(idx[j]) + 1 for j in range(1, len(idx)) if int(idx[j]) + 1 < T and s[j] == 0 and s[j - 1] == 0 and g[j] != g[j - 1])
        for cost in COSTS:
            got = sorted(t["idx"] for t in out["trades"] if t["book"] == p and t["run"] == "strategy" and t["cost_bps"] == cost and t["kind"] == "sleeve_rebalance")
            count_ok &= got == exp
        listed[p] = len(exp)
    # constant g: with the gold signal held constant no sleeve trade occurs (both constants), at 0 and 20.8 bps
    const = {}
    for p in books:
        d = decs[p]
        idx, s = d["decision_idx"].values, d["state"].values.astype(float)
        for name, c in (("BUY", GW_BUY), ("SELL", GW_SELL)):
            for cost in (0.0, PRIMARY):
                _, tr, _ = simulate(bks[p], idx, s, cost, record=True, gw=np.full(len(s), c))
                const[f"{p}|{name}|{cost}"] = {"sleeve_trades": sum(1 for t in tr if t["kind"] == "sleeve_rebalance"), "trades": len(tr)}
    const_ok = all(v["sleeve_trades"] == 0 for v in const.values())
    # worked examples (recorded values of the first exit and the first sleeve rebalance of the first book at 20.8 bps)
    ex = {}
    p0 = books[0]
    for kind in ("switch_out", "sleeve_rebalance"):
        for t in out["trades"]:
            if t["book"] == p0 and t["run"] == "strategy" and t["cost_bps"] == PRIMARY and t["kind"] == kind:
                j = t["dec_j"]
                d = decs[p0].iloc[j]
                gwv, V, cost = t["gw_after"], t["V"], t["cost"]
                ex[kind] = {"decision_date": str(d["decision_date"]), "trade_date": str(t["date"]), "g_read": d["sign_MAUc1"], "gw": gwv, "V": V, "stock_before": t["stock_before"],
                            "gold_before": t["gold_before"], "cash_before": t["cash_before"], "target_gold": gwv * V, "target_cash": (1 - gwv) * V, "traded": t["traded"], "cost": cost,
                            "gold_after": t["gold_after"], "cash_after": t["cash_after"], "expected_gold_after": gwv * (V - cost), "expected_cash_after": (1 - gwv) * (V - cost)}
                break
    ok = bool(n > 0 and all(v <= TOL for v in worst.values()) and count_ok and const_ok)
    return {"trades_checked": int(n), "trades_checked_at_0_cost": int(n0), "kinds": {f"{a}|{b}": int(c) for (a, b), c in sorted(kinds.items())}, "worst": worst, "tolerance": TOL,
            "real_rule_sleeve_trades_equal_expected_at_every_cost": bool(count_ok), "expected_sleeve_trades_per_book": listed, "constant_g_no_sleeve_trade": const_ok,
            "constant_g_detail": const, "worked_examples": ex,
            "not_checked_here": "weights drift between trades by construction (units are constant between trade sessions); the initial position at T0 is built from gw[0] without a trade record", "pass": ok}


def v4_regression(books, bks, out, dec_all, g4) -> dict:
    """V4: (a) decisions equal T06's on every shared date; (b) strategy_fixed50, hold_parent, sleeve_only, constant_mix (T06's f) and the published NAV equal T06's up to 2026-10-22;
    (c) T06's first 20 N4.10 draws replayed; (d) always-in G0; (e) extended D17 = old D17; (f) the gold series equals D24's weekly file."""
    t6d = pd.read_csv(T06E / "decisions.csv")
    t6n = pd.read_csv(T06E / "daily_nav.csv")
    z6 = np.load(T06E / "draw_states.npz")
    c6 = np.load(T06E / "draw_curves_20.8.npz")
    res = {"decisions": {}, "nav": {"rows": []}, "draws20": {"books": {}}, "d17_overlap": {}, "gold_vs_d24": {}, "g0": g4}
    ok = True
    for dec in dec_all:
        p = dec["book"].iloc[0]
        a = dec.assign(decision_date=dec["decision_date"].astype(str))[["decision_date", "decision_idx", "state"]]
        b = t6d[t6d["book"] == p][["decision_date", "decision_idx", "state"]]
        m = b.merge(a, on="decision_date", how="left", suffixes=("_t06", "_t08"))
        hit = m["state_t08"].notna()
        mism = int(((m.loc[hit, "state_t06"] != m.loc[hit, "state_t08"]) | (m.loc[hit, "decision_idx_t06"] != m.loc[hit, "decision_idx_t08"])).sum())
        shifted = []
        for _, r in m.loc[~hit].iterrows():          # T06's last decision date (2026-10-22) read against 2026-10-23 (T08-3)
            nd = str((pd.Timestamp(r["decision_date"]) + pd.Timedelta(days=1)).date())
            q = a[a["decision_date"] == nd]
            good = bool(len(q) == 1 and int(q["state"].iloc[0]) == int(r["state_t06"]) and int(q["decision_idx"].iloc[0]) == int(r["decision_idx_t06"]) + 1
                        and r["decision_date"] == b["decision_date"].iloc[-1])
            shifted.append({"t06_date": r["decision_date"], "t08_date": nd, "match": good})
        shift_ok = all(x["match"] for x in shifted) and len(shifted) <= 1
        res["decisions"][p] = {"t06_decisions": int(len(b)), "t08_decisions": int(len(a)), "compared_on_same_date": int(hit.sum()), "mismatches": mism, "shifted_dates": shifted,
                               "compared_total": int(hit.sum() + len(shifted)), "pass": bool(mism == 0 and shift_ok and hit.sum() > 0)}
        ok &= res["decisions"][p]["pass"]
    worst_by_run: dict = {}
    for p in books:
        bk, dec = bks[p], next(d for d in dec_all if d["book"].iloc[0] == p)
        d06 = t6n[t6n["book"] == p]
        f06 = float(t6d[t6d["book"] == p]["state"].mean())
        mask = np.asarray(bk.cal <= T06_NAV_END)
        for (run, cost), gdf in d06.groupby(["run", d06["cost_bps"].fillna(-1)]):
            gs = gdf.assign(date=pd.to_datetime(gdf["date"])).set_index("date")["nav"]
            if run == "published_D17":
                mine, name = bk.pub / bk.pub[0], "published_D17"
            elif run == "constant_mix":        # T06's own stock share f (T06's 409 decisions), as T06 did against T03
                mine, name = simulate(bk, dec["decision_idx"].values, np.full(len(dec), f06), cost, every=True), "constant_mix"
            elif run == "strategy":
                mine, name = out["nav"][(p, cost, "strategy_fixed50")], "strategy_fixed50"
            else:
                mine, name = out["nav"][(p, cost, run)], run
            mine = pd.Series(mine, index=bk.cal)
            cd = gs.index.intersection(mine.index[mask])
            rel = float((mine.loc[cd] / gs.loc[cd] - 1).abs().max()) if len(cd) else float("nan")
            passed = bool(len(cd) > 0 and rel < REL_TOL_NAV)
            ok &= passed
            worst_by_run[name] = max(worst_by_run.get(name, 0.0), rel if rel == rel else float("inf"))
            res["nav"]["rows"].append({"book": p, "t06_run": run, "t08_run": name, "cost_bps": None if cost == -1 else float(cost), "dates_compared": int(len(cd)), "max_rel_diff": rel,
                                       "pass": passed, "stock_share_f_used": f06 if run == "constant_mix" else None})
        # (c) T06's first 20 N4.10 draws, replayed with T08's last week appended
        zs = z6[f"{p}|full|N4.10"]
        n06 = zs.shape[1]
        s08 = dec["state"].values.astype(int)
        assert len(s08) >= n06
        worst, nd, cmp_sess = 0.0, 0, 0
        for d in range(min(20, zs.shape[0])):
            st = np.concatenate([zs[d].astype(int), s08[n06:]])
            nv = simulate(bk, dec["decision_idx"].values, st.astype(float), PRIMARY, gw=None)
            cv = c6[f"{p}|N4.10_{d}"]
            L = len(cv)
            assert bk.cal[L - 1] == T06_NAV_END, f"T06's curve has {L} sessions; T08 calendar session {L - 1} is {bk.cal[L - 1].date()}"
            rel = float(np.abs(nv[:L].astype(np.float32).astype(float) / cv.astype(float) - 1).max())
            worst, nd, cmp_sess = max(worst, rel), nd + 1, L
        pass_c = bool(nd > 0 and worst < REL_TOL_F32)
        ok &= pass_c
        res["draws20"]["books"][p] = {"draws": nd, "sessions_compared": cmp_sess, "weeks_t06": int(n06), "weeks_t08": int(len(s08)), "max_rel_diff": worst, "pass": pass_c}
        # (e) extended D17 = old D17 on its rows
        old = read_pub(OLD_D17_DIR / f"{p}.csv", cut=False)
        ext = read_pub(NEW_D17_DIR / f"{p}.csv", cut=False)
        both = old.index.intersection(ext.index)
        mx = float((ext.loc[both] / old.loc[both] - 1).abs().max())
        sub = bool(old.index.isin(ext.index).all())
        pass_e = bool(sub and mx == 0.0 and len(both) == len(old))
        ok &= pass_e
        res["d17_overlap"][p] = {"old_rows": int(len(old)), "extended_rows": int(len(ext)), "old_rows_in_extended": sub, "max_rel_diff": mx, "extra_rows_in_extended": int(len(ext) - len(old)),
                                 "extended_last": str(ext.index.max().date()), "pass": pass_e}
        # (f) the gold series equals D24's weekly file at every decision date
        w = d24_weekly()
        bad_sig, bad_lab, bad_sign = 0, 0, 0
        for r in dec.itertuples():
            k = w["review"].searchsorted(pd.Timestamp(r.decision_date), side="right") - 1
            bad_sig += int(round(float(w["signal"].iloc[k]))) != int(r.g)
            bad_sign += (w["SIGN"].iloc[k] == "BUY") != (r.g == 1)
            bad_lab += str(w["review"].iloc[k].date()) != str(r.label_MAUc1)
        pass_f = bool(bad_sig == 0 and bad_sign == 0 and bad_lab == 0 and len(dec) > 0)
        ok &= pass_f
        res["gold_vs_d24"][p] = {"decisions": int(len(dec)), "signal_mismatches": int(bad_sig), "SIGN_mismatches": int(bad_sign), "label_mismatches": int(bad_lab), "pass": pass_f}
    res["nav"]["rows_compared"] = int(len(res["nav"]["rows"]))
    res["nav"]["worst_rel_diff_by_run"] = worst_by_run
    res["draws20"]["max_rel_diff"] = max(v["max_rel_diff"] for v in res["draws20"]["books"].values())
    res["draws20"]["tolerance_rel_float32"] = REL_TOL_F32
    res["g0_pass"] = bool(all(r["overall"] == "PASS" and r["yearly"] == "PASS" for r in g4))
    ok &= res["g0_pass"]
    res["nav_compared_to"] = str(T06_NAV_END.date())
    res["tolerance_rel"] = REL_TOL_NAV
    res["pass"] = bool(ok)
    return res


def flush_draws(out: dict, path: Path, first: bool):
    if out["draw_rows"]:
        pd.DataFrame(out["draw_rows"]).to_csv(path, mode="w" if first else "a", header=first, index=False)
        out["draw_rows_written"] += len(out["draw_rows"])
    out["draw_rows"] = []


def main():
    ap_ = argparse.ArgumentParser()
    ap_.add_argument("--run", default="headline")
    ap_.add_argument("--draws", type=int, default=None)
    ap_.add_argument("--quick", action="store_true", help="smoke test: the first book only, 20 draws unless --draws is given")
    ap_.add_argument("--books", nargs="+", default=None)
    a = ap_.parse_args()
    outdir = T08 / "evidence" / a.run
    outdir.mkdir(parents=True, exist_ok=True)
    t_start = time.time()
    books = a.books or (PARENTS[:1] if a.quick else PARENTS)
    assert all(b in PARENTS for b in books), books
    n_draws = a.draws if a.draws else (20 if a.quick else N_DRAWS)
    out = {"rows": [], "draw_rows": [], "draw_rows_written": 0, "nav": {}, "trades": [], "positions": [], "sleeve_trades": [], "strategy_raw_gold_trades": 0, "v2_trades": 0}
    curves: dict = {}
    dec_all, bks = [], {}
    audit = {"readings": READINGS, "books": {}}

    # the data boundary: every input through the approved table, sha256 checked, window covered
    inputs = [HD / "extended_2026-10-30" / "Master" / f"Master_{n}.xlsx" for n in ("Nifty100", "MC100", "SC100")]
    inputs += [D24_DIR / "Master_MAUc1.xlsx", D24_DIR / "mauc1_supertrend_weekly_extended.csv",
               AA / "analysis" / "cache" / "why_gold_ohlc_eikon_extended_2026-11-04.parquet",
               AA / "analysis" / "evidence" / "final_strategy" / "mauc1" / "mauc1_daily_clean.csv",
               HD / "LBES_Adjusted_Price_data_extended_2026-11-05.csv", HD / "liquidEtfFinal_extended_2026-11-05.csv", HM / "price_corrections.csv"]
    for p in PARENTS:
        inputs += [HM / f"{p}_{x}.csv" for x in ("ohlc", "holding_weight_matrix", "holding_weight_sources")] + [NEW_D17_DIR / f"{p}.csv", OLD_D17_DIR / f"{p}.csv"]
    not_parsed = []
    for p in PARENTS:
        not_parsed += [HM / f"{p}_columns.csv", HD / "frozen_2026-09-25" / "Rebalance_history" / f"Rebalance_history_by_scid_{p}.csv"]
    for f in inputs + not_parsed:
        ap(f)
    for rel, r in USED.items():
        if rel.startswith("Historical Data/parent_nav_2026-10-22/"):
            continue                                    # pinned old D17, read only for V4(e)
        if r["id"] in ("D17", "D18", "D03", "D09", "D11", "D24"):
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
    print(f"data: END = {END.date()} (last D03 Master row), approved data as of {AD.as_of()}, {len(USED)} inputs checked; non-approved open raises: {selftest['pass']}", flush=True)

    ct, v3_res, v5c = {}, {}, {}
    states_all: dict = {}
    real_states: dict = {}
    hb_io = hb_g = None
    live_gate: dict = {}
    first_draw_write = True
    for p in books:
        t1 = time.time()
        bk = Book(p)
        bks[p] = bk
        dec = bk.decisions()
        dec_all.append(dec)
        s = dec["state"].values.astype(int)
        g = dec["g"].values.astype(int)
        hi_in, hi_out = rule_bounds(s)
        hi_buy, hi_sell = rule_bounds(g)
        assert (hi_in, hi_out) == IO_BOUNDS_EXPECTED, f"{p}: in-or-out bounds {(hi_in, hi_out)} differ from the registered {IO_BOUNDS_EXPECTED}"
        assert (hi_buy, hi_sell) == GOLD_BOUNDS_EXPECTED, f"{p}: gold bounds {(hi_buy, hi_sell)} differ from the registered {GOLD_BOUNDS_EXPECTED}"
        hb_io, hb_g = (hi_in, hi_out), (hi_buy, hi_sell)
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
        r0, rg = lens_of(s), lens_of(g)
        fl = flip_counts(s, g)
        audit["books"][p] = {"t0": str(bk.t0.date()), "last_session": str(bk.cal[-1].date()), "sessions": bk.T, "decisions": len(dec), "invested_weeks": int(s.sum()),
                             "first_state": int(s[0]), "in_lengths": r0[0], "out_lengths": r0[1], "bounds": {"lo": LO, "hi_in": hi_in, "hi_out": hi_out},
                             "in_spells": len(r0[0]), "out_spells": len(r0[1]), "round_trips": min(len(r0[0]), len(r0[1])),
                             "sessions_invested_rule": sessions_invested(bk, dec["decision_idx"].values, s),
                             "gold": {"first_state": int(g[0]), "buy_lengths": rg[0], "sell_lengths": rg[1], "buy_weeks": int(g.sum()), "bounds": {"lo": LO, "hi_buy": hi_buy, "hi_sell": hi_sell},
                                      "shortest_spell": min(rg[0] + rg[1]), "spells_with_an_out_week": gold_spells_with_out(s, g), **fl,
                                      "sleeve_trades_expected": n_sleeve_trades(dec["decision_idx"].values, bk.T, s, g)},
                             "v2_decisions_checked": len(dec), "v2_label_after_decision": len(dec) - lab_ok, "v2_mauc1_label_after_decision": len(dec) - lab_g_ok,
                             "v2_trades_checked": traded_rows, "v2_trade_not_after_decision": int((tdates.values <= ddates.values).sum()),
                             "stale_label_weeks(age>=5d, excluding T0)": int((dec["label_age_days"].values[1:] >= 5).sum()),
                             "initial_basket_switch_session": bk.initial_basket_switch_session, "cash": bk.cash_info,
                             "raw_fill_sessions_in_window": int(bk.gold_raw.sum()),
                             "skipped_baskets_dropped": [str(x.date()) for x in raw_parent(p)["skipped"]]}
        assert audit["books"][p]["gold"]["shortest_spell"] >= LO
        real_states[f"{p}|full|io"], real_states[f"{p}|full|gold"] = s.astype(np.uint8), g.astype(np.uint8)
        # states, V3 for the full window
        st_io = make_states_io(s, n_draws, hi_in, hi_out)
        st_g = make_states_gold(g, n_draws, hi_buy, hi_sell)
        for k, v in st_io.items():
            states_all[f"{p}|full|io|{k}"] = v
        for k, v in st_g.items():
            states_all[f"{p}|full|gold|{k}"] = v
        v3_res[f"{p}|full|io"] = v3_check(s, st_io, hi_in, hi_out)
        v3_res[f"{p}|full|gold"] = v3_check(g, st_g, hi_buy, hi_sell)
        plan_full = [(fm, c, "timed") for fm in ("F1", "F2", "F3", "F4") for c in COSTS] + [("F5", PRIMARY, "timed"), ("F1", PRIMARY, "fixed50"), ("F2", PRIMARY, "fixed50")]
        bk.nobar_trades = 0
        bk.raw_gold_trades = 0
        run_book(bk, dec, st_io, st_g, "full", "lbes", plan_full, True, out, curves)
        audit["books"][p]["stock_trades_priced_by_last_close_no_bar_that_session(all runs incl. draws)"] = bk.nobar_trades
        audit["books"][p]["goldbees_trades_filled_at_raw_OHLC4_after_MCX_file(all runs incl. draws, headline LBES)"] = bk.raw_gold_trades
        # R2: LIQUIDCASE cash: the full-window states are reused
        bk3 = Book(p, cash="liq")
        run_book(bk3, dec, st_io, st_g, "full", "liq", [("F1", PRIMARY, "timed"), ("F3", PRIMARY, "timed")], False, out, curves)
        # R3: live window, its own spells and totals (in-or-out and gold), the same bounds
        bk4 = Book(p, start=LIVE_START)
        dec4 = bk4.decisions()
        s4, g4_ = dec4["state"].values.astype(int), dec4["g"].values.astype(int)
        r4, rg4 = lens_of(s4), lens_of(g4_)
        rt = min(len(r4[0]), len(r4[1]))
        feas = {"in": 2 * len(r4[0]) <= sum(r4[0]) <= hi_in * len(r4[0]), "out": 2 * len(r4[1]) <= sum(r4[1]) <= hi_out * len(r4[1]),
                "buy": 2 * len(rg4[0]) <= sum(rg4[0]) <= hi_buy * len(rg4[0]), "sell": 2 * len(rg4[1]) <= sum(rg4[1]) <= hi_sell * len(rg4[1])}
        gout = gold_spells_with_out(s4, g4_)
        live_ok = bool(rt >= 4 and gout >= 4 and all(feas.values()))
        live_gate[p] = {"round_trips": rt, "gold_spells_with_an_out_week": gout, "feasible": feas, "reportable": live_ok}
        audit["books"][p]["live_window"] = {"t0": str(bk4.t0.date()), "decisions": len(dec4), "round_trips": rt, "reportable": live_ok, "first_state": int(s4[0]), "in_lengths": r4[0],
                                            "out_lengths": r4[1], "gold_first_state": int(g4_[0]), "g_buy_lengths": rg4[0], "g_sell_lengths": rg4[1], "gold_spells_with_an_out_week": gout,
                                            "feasible": feas, **{f"gold_{k}": v for k, v in flip_counts(s4, g4_).items()},
                                            "sessions_invested_rule": sessions_invested(bk4, dec4["decision_idx"].values, s4)}
        real_states[f"{p}|live|io"], real_states[f"{p}|live|gold"] = s4.astype(np.uint8), g4_.astype(np.uint8)
        windows = [("full", s, g, hi_in, hi_out, hi_buy, hi_sell)]
        if live_ok:
            windows.append(("live", s4, g4_, hi_in, hi_out, hi_buy, hi_sell))
            sl_io = make_states_io(s4, n_draws, hi_in, hi_out)
            sl_g = make_states_gold(g4_, n_draws, hi_buy, hi_sell)
            for k, v in sl_io.items():
                states_all[f"{p}|live|io|{k}"] = v
            for k, v in sl_g.items():
                states_all[f"{p}|live|gold|{k}"] = v
            v3_res[f"{p}|live|io"] = v3_check(s4, sl_io, hi_in, hi_out)
            v3_res[f"{p}|live|gold"] = v3_check(g4_, sl_g, hi_buy, hi_sell)
            run_book(bk4, dec4, sl_io, sl_g, "live", "lbes", [("F1", PRIMARY, "timed"), ("F3", PRIMARY, "timed")], False, out, curves)
        # count tables, inclusion-exclusion, per-position means (V5 b, c)
        for w, sw, gwk, hin, hout, hbu, hse in windows:
            for ser, arr, his, names, nullkey in (("io", sw, (hin, hout), ("in", "out"), "N4.10"), ("gold", gwk, (hbu, hse), ("buy", "sell"), "N4.10-g")):
                rr = lens_of(arr)
                for stn, ls, hi, ix in zip(names, rr, his, (0, 1)):
                    k, S = len(ls), sum(ls)
                    tab = count_table(k, S, LO, hi)
                    n_dp, n_ie = int(tab[k][S]), ie_count(k, S, LO, hi)
                    ct[f"{p}|{w}|{ser}|{stn}"] = {"book": p, "window": w, "series": ser, "state": stn, "weeks_S": S, "spells_k": k, "lo": LO, "hi": hi,
                                                  "feasible_2k<=S<=hi*k": bool(2 * k <= S <= hi * k), "n_ways": str(n_dp), "n_ways_inclusion_exclusion": str(n_ie),
                                                  "dp_equals_inclusion_exclusion": n_dp == n_ie, "rule_lengths_within_bounds": bool(all(LO <= x <= hi for x in ls))}
                    M = np.array([lens_of(st.astype(int))[ix] for st in states_all[f"{p}|{w}|{ser}|{nullkey}"]], dtype=float)
                    sd = M.std(axis=0, ddof=1) if len(M) > 1 else np.zeros(M.shape[1])
                    se = sd / math.sqrt(len(M))
                    dev = np.abs(M.mean(axis=0) - S / k)
                    z = np.where(se > 0, dev / np.where(se > 0, se, 1), np.where(dev > 0, np.inf, 0.0))
                    v5c[f"{p}|{w}|{ser}|{stn}"] = {"draws": int(len(M)), "target_S_over_k": S / k, "mean_over_positions_and_draws": float(M.mean()),
                                                   "max_abs_z_per_position": float(z.max()), "pass": bool(z.max() <= 4.0)}
        flush_draws(out, outdir / "draws.csv", first_draw_write)
        first_draw_write = False
        print(f"{p}: {time.time() - t1:.0f}s  decisions {len(dec)}  round trips {audit['books'][p]['round_trips']}  gold flips {fl['flips']} (sleeve trades {audit['books'][p]['gold']['sleeve_trades_expected']})", flush=True)

    # V4(d): always-in at 0 cost against the published NAV (G0)
    g4 = []
    for p in books:
        bk = bks[p]
        nav = simulate(bk, np.array([0]), np.ones(1), 0.0)
        c = pd.DataFrame({"m": nav, "p": bk.pub}, index=bk.cal)
        c = c / c.iloc[0] * 100
        yrs = (c.index[-1] - c.index[0]).days / 365.25
        gap = ((c.m.iloc[-1] / c.m.iloc[0]) ** (1 / yrs) - (c.p.iloc[-1] / c.p.iloc[0]) ** (1 / yrs)) * 100
        worst, wy = 0.0, None
        for yr, gg in c.groupby(c.index.year):
            prev = c.loc[:gg.index[0]].iloc[-2] if len(c.loc[:gg.index[0]]) > 1 else gg.iloc[0]
            d = (gg["m"].iloc[-1] / prev["m"] - gg["p"].iloc[-1] / prev["p"]) * 100
            if abs(d) > abs(worst):
                worst, wy = d, int(yr)
        g4.append({"book": p, "cagr_gap_pp_yr": gap, "overall": "PASS" if abs(gap) <= G0_OVERALL else "FAIL", "worst_year": wy,
                   "worst_year_gap_pp": worst, "yearly": "PASS" if abs(worst) <= G0_YEARLY else "FAIL",
                   "window_first": str(c.index[0].date()), "window_last": str(c.index[-1].date())})
    pd.DataFrame(g4).to_csv(outdir / "g_engine.csv", index=False)

    # V4 regression to T06, V5 samplers, V6 sleeve identity, V3 summary
    reg = v4_regression(books, bks, out, dec_all, g4)
    (outdir / "regression_t06.json").write_text(json.dumps(reg, indent=1, default=str), encoding="utf-8")
    small = sampler_selftest_small()
    v5b = all(v["dp_equals_inclusion_exclusion"] for v in ct.values())
    v5 = {"a_small_case": small, "b_dp_equals_inclusion_exclusion": {"all_equal": bool(v5b), "checked": int(len(ct))},
          "c_mean_length_within_4_se": v5c, "pass": bool(small["pass"] and v5b and all(v["pass"] for v in v5c.values()))}
    (outdir / "sampler_selftest.json").write_text(json.dumps(v5, indent=1, default=str), encoding="utf-8")
    (outdir / "count_table.json").write_text(json.dumps({"bounds": {"io": {"lo": LO, "hi_in": hb_io[0], "hi_out": hb_io[1]},
                                                                    "gold": {"lo_buy": LO, "hi_buy": hb_g[0], "lo_sell": LO, "hi_sell": hb_g[1]}}, "tables": ct}, indent=1), encoding="utf-8")
    v6 = v6_check(out, books, bks, dec_all)

    # step-1 spell counts reproduced from the data
    s1 = json.loads((T08 / "logs" / "step_1_spell_counts.json").read_text(encoding="utf-8"))
    s1_ok, s1_detail = True, {}
    for p in books:
        e = s1["books"][p]
        for w, key in (("full", "full"), ("live", "live_window")):
            mine = audit["books"][p] if w == "full" else audit["books"][p]["live_window"]
            exp = e[w]
            if w == "full":
                gm = mine["gold"]
                good = (mine["in_lengths"] == exp["in_lengths"] and mine["out_lengths"] == exp["out_lengths"] and mine["first_state"] == exp["first_state"] and mine["decisions"] == exp["weeks"]
                        and gm["buy_lengths"] == exp["g_buy_lengths"] and gm["sell_lengths"] == exp["g_sell_lengths"] and gm["first_state"] == exp["g_first_state"]
                        and gm["flips"] == exp["g_flips"] and gm["while_out_both_sides"] == exp["g_flips_while_out_both_sides"] and gm["on_exit_decision"] == exp["g_flips_on_an_exit_decision"]
                        and gm["spells_with_an_out_week"] == exp["g_spells_with_an_out_week"] and gm["weeks_buy_while_out"] == exp["g_weeks_buy_while_out"]
                        and int(audit["books"][p]["raw_fill_sessions_in_window"]) == exp["sessions_after_mcx_range_end"])
            else:
                good = (mine["in_lengths"] == exp["in_lengths"] and mine["out_lengths"] == exp["out_lengths"] and mine["first_state"] == exp["first_state"] and mine["decisions"] == exp["weeks"]
                        and mine["g_buy_lengths"] == exp["g_buy_lengths"] and mine["g_sell_lengths"] == exp["g_sell_lengths"] and mine["gold_first_state"] == exp["g_first_state"]
                        and mine["gold_flips"] == exp["g_flips"] and mine["gold_while_out_both_sides"] == exp["g_flips_while_out_both_sides"])
            s1_detail[f"{p}|{w}"] = bool(good)
            s1_ok &= good
    s1_ok &= (hb_io, hb_g) == ((s1["bounds"]["io"]["hi_in"], s1["bounds"]["io"]["hi_out"]), (s1["bounds"]["gold"]["hi_buy"], s1["bounds"]["gold"]["hi_sell"]))

    # write
    flush_draws(out, outdir / "draws.csv", first_draw_write)
    pd.concat(dec_all).to_csv(outdir / "decisions.csv", index=False)
    pd.concat(dec_all)[["book", "j", "decision_date", "label_MAUc1", "sign_MAUc1", "g", "gw"]].to_csv(outdir / "gold_signal.csv", index=False)
    rows = pd.DataFrame(out["rows"])
    rows.to_csv(outdir / "stats.csv", index=False)
    tcols = ["book", "cost_bps", "run", "date", "idx", "kind", "e_after", "basket_eff", "V", "traded", "cost", "nav_close_after", "gw_after"]
    tdf = pd.DataFrame(out["trades"])[tcols]
    tdf.loc[tdf["run"] == "hold_parent", "gw_after"] = np.nan
    tdf.to_csv(outdir / "trades.csv", index=False)
    pd.DataFrame(out["sleeve_trades"]).to_csv(outdir / "sleeve_trades.csv", index=False)
    pd.DataFrame(out["positions"]).to_csv(outdir / "positions.csv", index=False)
    daily = []
    for (p, cost, name), nv in out["nav"].items():
        daily.append(pd.DataFrame({"book": p, "date": bks[p].cal, "cost_bps": cost, "run": name, "nav": nv}))
    for p in books:
        daily.append(pd.DataFrame({"book": p, "date": bks[p].cal, "cost_bps": np.nan, "run": "published_D17", "nav": bks[p].pub / bks[p].pub[0]}))
    pd.concat(daily).to_csv(outdir / "daily_nav.csv", index=False)
    np.savez_compressed(outdir / "draw_curves_20.8.npz", **{f"{p}|{k}": v for p, d in curves.items() for k, v in d.items()})
    np.savez_compressed(outdir / "draw_states.npz", **states_all)
    np.savez_compressed(outdir / "real_states.npz", **real_states)

    # audit
    c_ = common()
    v3_ok = all(v["pass"] for v in v3_res.values())
    cashn = cash_note()
    v2_viol = sum(b["v2_label_after_decision"] + b["v2_mauc1_label_after_decision"] + b["v2_trade_not_after_decision"] for b in audit["books"].values())
    v2_cnt = sum(b["v2_decisions_checked"] * 2 + b["v2_trades_checked"] for b in audit["books"].values()) + out["v2_trades"]
    v2_ok = bool(v2_viol == 0 and v2_cnt > 0)
    audit["v2"] = {"checks": int(v2_cnt), "violations": int(v2_viol), "recorded_trades_after_their_decision": int(out["v2_trades"]), "pass": v2_ok}
    audit["v3"] = {"per_book_window": v3_res, "pass": bool(v3_ok), "rule_in_support": {k: v["rule_in_support"] for k, v in v3_res.items()}, "draws_per_type": int(n_draws),
                   "reportability": {"live_window": live_gate, "gold_spells_with_an_out_week_full": {p: audit["books"][p]["gold"]["spells_with_an_out_week"] for p in books}}}
    audit["v4"] = {"pass": reg["pass"], "g0": g4}
    audit["v5"] = {"pass": v5["pass"]}
    audit["v6"] = v6
    raw_trades_by_book = {p: audit["books"][p]["goldbees_trades_filled_at_raw_OHLC4_after_MCX_file(all runs incl. draws, headline LBES)"] for p in books}
    strat_raw = [{"book": t["book"], "date": str(t["date"]), "kind": t["kind"], "cost_bps": t["cost_bps"]} for t in out["trades"]
                 if t["run"] == "strategy" and t["cost_bps"] == PRIMARY and bks[t["book"]].gold_raw[t["idx"]] and t["kind"] != "basket_change"]
    audit["data"] = {"approved_data_as_of": AD.as_of(), "end_from_D03": str(END.date()), "inputs": int(len(USED)),
                     "registered_not_parsed": [x.relative_to(AA).as_posix() for x in not_parsed],
                     "non_approved_open_raises": selftest, "cash_accrued_sessions": 0, "cash_first_appended_row": cashn,
                     "d17_extended_last_date": {p: str(raw_parent(p)["d17_last"].date()) for p in books},
                     "mauc1": {"master_last_row": str(c_["gold_master_last"].date()), "rows_after_END_dropped": int(c_["gold_master_rows_after_end"])},
                     "goldbees": {"mcx_file_last": str(c_["mcx_last"].date()), "goldbees_file_last": str(c_["gold_data_last"].date()),
                                  "sessions_after_mcx_in_goldbees_file": c_["gold_raw_sessions_in_data"],
                                  "sessions_after_mcx_in_window_calendar": [str(d.date()) for d in bks[books[0]].cal[bks[books[0]].gold_raw]],
                                  "raw_fill_sessions_in_window": int(bks[books[0]].gold_raw.sum()),
                                  "strategy_trades_with_raw_OHLC4_gold_fill(all costs, full+live+liq windows)": out["strategy_raw_gold_trades"],
                                  "strategy_raw_fill_trades_at_20.8_full_window": strat_raw,
                                  "trades_with_raw_OHLC4_gold_fill_by_book(all runs, draws included, headline LBES run)": raw_trades_by_book}}
    audit["sleeve_trades_per_book_real_rule"] = {p: audit["books"][p]["gold"]["sleeve_trades_expected"] for p in books}
    audit["step1_spell_counts_reproduced"] = {"pass": bool(s1_ok), "detail": s1_detail}
    audit["run"] = {"name": a.run, "command": " ".join(sys.argv), "draws": n_draws, "books": list(books), "seconds": round(time.time() - t_start), "quick": a.quick,
                    "python": sys.version.split()[0], "numpy": np.__version__, "pandas": pd.__version__,
                    "seeds": "in-or-out N4.9 default_rng([3, id]), N4.10 [6, id]; gold N4.9-g [11, 3, id], N4.10-g [11, 6, id]; the same draw ids for every cost, window and cash variant; F5 pairs F1's and F3's draw of the same id"}
    audit["prereg_sha256"] = (T08 / "T08.md").read_text(encoding="utf-8").split("§1–§3 sha256:** `")[1].split("`")[0]
    ok = bool(v2_ok and v3_ok and reg["pass"] and v5["pass"] and v6["pass"] and selftest["pass"] and s1_ok)
    audit["gates"] = {"V2": v2_ok, "V3": bool(v3_ok), "V4": reg["pass"], "V5": v5["pass"], "V6": v6["pass"], "approved_data_selftest": selftest["pass"], "step1_counts": bool(s1_ok), "all": ok}
    (outdir / "audit.json").write_text(json.dumps(audit, indent=1, default=str), encoding="utf-8")

    print(rows[rows["kind"].isin(["strategy", "strategy_fixed50"])][["book", "window", "cash", "cost_bps", "kind", "cagr", "max_dd", "end_nav", "trades", "sleeve_trades"]].round(4).to_string(index=False))
    print(pd.DataFrame(g4).round(3).to_string(index=False))
    print("V2", audit["v2"])
    print("V3", {k: v["pass"] for k, v in v3_res.items()})
    print("V4", {"decisions": {k: v["pass"] for k, v in reg["decisions"].items()}, "nav_rows": reg["nav"]["rows_compared"], "worst_rel_diff_by_run": reg["nav"]["worst_rel_diff_by_run"],
                 "draws20_max_rel": reg["draws20"]["max_rel_diff"], "g0": reg["g0_pass"], "pass": reg["pass"]})
    print("V5", {"small_p": small["p"], "ie_equal": v5b, "mean_check": all(v["pass"] for v in v5c.values()), "pass": v5["pass"]})
    print("V6", {"trades": v6["trades_checked"], "worst": v6["worst"], "pass": v6["pass"]})
    for k, v in ct.items():
        if v["window"] == "full":
            print(f"  n_ways {k}: {v['n_ways']}")
    print(f"gates: {audit['gates']}")
    print(f"done in {time.time() - t_start:.0f}s -> {outdir}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
