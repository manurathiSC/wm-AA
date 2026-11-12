# -*- coding: utf-8 -*-
"""T09 engine: the three-index switch (T06's rule, Part A: fixed 50/50 sleeve; T08's rule, Part B: MAUc1-timed 80/20 sleeve) on a THREE-INDEX PROXY
portfolio (Nifty 100, Midcap 100, Smallcap 100 at each book's fixed band mix), against one null per timing, on 2011-11-25 -> 2019-01-02.

A FORK of analysis/t08_engine.py (copied, not imported). Changes against T08: the parent's stocks (D18, D19, D05, D17) are replaced by three index instruments
(D25 prices, fixed weights per book, reset on entry and at the first session of each calendar quarter while IN); the calendar is D26's; the window is
T0 = 2011-11-25 .. END = 2019-01-02; the gold leg is GOLDBEES (D09) from 2014-07-01 and the MAUc1 proxy (D09b) before; the MAUc1 signal is D24b; the spell
bounds of every series come from the series itself (lo = min(2, shortest spell of the state), hi = longest spell of the state); the seeds start with 12. Every data
file is opened through `approved_data.require()` (an APPROVED row of data/APPROVED_DATA.md), its sha256 prefix is checked against the row, and Smallcap 100 files
go through `approved_data.guard_window` (standing rule 7). Pre-registration: tests/T09/T09.md sections 1-3 (frozen; `python tests/T09/check_prereg.py`);
plan: tests/T09/PLAN.md; evidence contract: tests/T09/logs/evidence_contract.md.

    python analysis/t09_engine.py [--run NAME] [--draws N] [--quick] [--books SCMO_0003 ...]      (from AA/)

Null families (2,000 draws per book; the same draw id for every cost; the four books share the draws, their decision series are identical):
    F1  in-or-out N4.10 (seed [12, 6, id])  + the real gold signal         decides A1/A2 (run with the 50/50 sleeve) and C1/C2 (timed sleeve)
    F2  in-or-out N4.9  (seed [12, 3, id])  + the real gold signal         beside F1
    F3  the real in-or-out switch + gold N4.10-g (seed [12, 11, 6, id])    decides C3, C4
    F4  the real in-or-out switch + gold N4.9-g  (seed [12, 11, 3, id])    beside F3
    F5  F1's in-or-out draw + F3's gold draw, same id                      robustness (R5)
    (F1 and F2 are also run with the sleeve fixed at 50/50: Part A's null and R6.)

Trade rule (one function, `trade`, T08's arithmetic): at a trade session t, V = value of all holdings at the fill prices (index OHLC4, GOLDBEES fill, cash level).
Target values: indices e*V*w_i, GOLDBEES (1-e)*gw*V, cash (1-e)*(1-gw)*V. traded = sum |target - held| over every line; cost = traded*cost_bps/2/1e4;
every target is then scaled by (V-cost)/V. A trade exists on the next session after decision j iff e changed or (e < 1 and gw changed): switch_in, switch_out,
sleeve_rebalance; plus the calendar-defined quarterly_reset (first session of Jan/Apr/Jul/Oct after T0, only when the book holds the proxy at the start of that
session and the session is not an exit/entry trade session).

Writes tests/T09/evidence/<run>/ (see tests/T09/logs/evidence_contract.md).
"""
from __future__ import annotations

import argparse
import ast
import copy
import hashlib
import io
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
IDX_DIR = HD / "extended_2026-11-12" / "index_daily_pre2019"
D24B_DIR = HD / "extended_2026-11-12" / "MAUc1_from_2003"
MASTER_DIR = HD / "extended_2026-10-30" / "Master"
GOLD_D09 = AA / "analysis" / "cache" / "why_gold_ohlc_eikon_extended_2026-11-04.parquet"
GOLD_D09B = AA / "analysis" / "cache" / "why_gold_ohlc_proxy_mauc1_2005-05-10_2014-06-30.parquet"
T09 = AA / "tests" / "T09"
T08_ENGINE = Path(__file__).with_name("t08_engine.py")
STEP1 = T09 / "logs" / "step_1_spell_counts.json"

BOOKS = ["SCMO_0003", "SCMO_0007", "SCMO_0010", "SCMO_0029"]
INDICES = ("Nifty100", "MC100", "SC100")
# Band mixes on (Nifty 100, Midcap 100, Smallcap 100): T09.md section 3 (typed constants; provenance tests/T07/logs/step_1_counts.json)
WEIGHTS = {"SCMO_0003": (0.09626177, 0.19679459, 0.70694364), "SCMO_0007": (0.04799800, 0.17801859, 0.77398341),
           "SCMO_0010": (0.26590767, 0.21230665, 0.52178568), "SCMO_0029": (0.31294405, 0.28378774, 0.40326821)}
T0 = pd.Timestamp("2011-11-25")                  # the single constant for the window start (Manu, 2026-11-12); everything else derives from it
END = pd.Timestamp("2019-01-02")
R3_START = pd.Timestamp("2012-01-02")
SC_PRICE_USABLE_FROM = pd.Timestamp("2011-10-03")     # rule 7: D25 Smallcap 100 prices
GB_FIRST = pd.Timestamp("2014-07-01")                 # GOLDBEES's first bar; the proxy D09b ends the day before
COSTS = (0.0, 20.8, 50.0)
PRIMARY = 20.8
N_DRAWS = 2000
LO_CAP = 2                                            # lo = min(LO_CAP, shortest spell of the state)
DESPIKE_TOL = 0.005
REL_TOL_NAV = 1e-12
GW_BUY, GW_SELL, GW_FIX = 0.8, 0.2, 0.5
SEED_IO_49, SEED_IO_410 = (12, 3), (12, 6)
SEED_G_49, SEED_G_410 = (12, 11, 3), (12, 11, 6)
QUARTER_MONTHS = (1, 4, 7, 10)

READINGS = {
    "E1": "calendar = D26's dates from T0 to END; the three D25 index files are sliced to [T0, END] on read (Smallcap 100 as text lines, so no earlier row is parsed); rows on dates D26 lacks (Saturday "
          "special sessions) are dropped and counted; every session must have a bar in all three files (asserted)",
    "E2": "decision dates = T0 and the last D26 session of every later ISO week; the decision at the last session (END) is made and not traded",
    "E3": "label = latest Master row dated <= decision date, per index and for MAUc1 (D24b); IN iff all three index SIGN are BUY; g = BUY iff the MAUc1 SIGN is BUY (a week whose row is dated after its "
          "last D26 session reads the previous week's row); the Smallcap 100 Master rows are sliced to >= T0 on read (the whole xlsx is parsed, rows before T0 are dropped at once and never used)",
    "E4": "initial position at T0's close, no cost: IN = the three index positions at the book's weights of NAV 1 (units w_i / close_i); OUT = gw GOLDBEES and (1-gw) cash of NAV 1 with gw = 0.8 (g BUY at T0) "
          "or 0.2 (SELL), 0.5 in fixed50 mode",
    "E5": "index fill = OHLC4 of the D25 bar (close if any of open/high/low is blank; none is); valuation = close",
    "E6": "quarterly reset: a session t > 0 whose month is Jan/Apr/Jul/Oct and whose previous session is in another month; it trades iff the book holds the proxy at the START of the session (the position "
          "left by the previous trade) and no decision trade falls on t (an exit or entry session does that trade only); no reset while OUT, none in `every` (constant mix) runs because their weekly "
          "rebalance already resets; END's session is a reset session when it opens a quarter (2019-01-02) and is traded: only DECISIONS at END are not traded",
    "E7": "costs: one rule for every trade, see the module docstring (cost = ow x value traded at the pre-cost targets, then every target scaled by (V-cost)/V; T06/T08's `trade`, unchanged in its arithmetic). "
          "T09.md section 3 step 6 says the post-cost targets 'solve the fixed point exactly'; the engine does what T06 and T08 do (this reading is reported)",
    "E8": "GOLDBEES leg: close = D09b's close before 2014-07-01 chained with D09's from 2014-07-01; fill = D09b's OHLC4 before 2014-07-01 (the proxy is MAUc1 itself); from 2014-07-01 T03's de-spike "
          "(OHLC4 of open/high/low clipped to MCX gold's range that day + 0.5% of the close) with the MCX range read from D24b's daily file; a session with no MCX bar is filled at the raw OHLC4 (counted); "
          "a session with no gold bar of its own uses the previous close and fill (counted)",
    "E9": "cash level: the extended LBES (D11) as-of on sessions; R2 'liq' = the desk's liquidEtfFinal (LIQUIDCASE) levels as-of on sessions over the whole window (LBES equals LIQUIDCASE until 2024-01-24, "
          "so the daily-return difference is reported and should be about zero); no cash is accrued past a file's end (asserted)",
    "E10": "constant mix: index share f = invested decision weeks / decision weeks, rebalanced at every decision date's next session (T0 included); constant_mix splits the non-index share 50/50, "
           "constant_mix_timed by the decision's gw; initial holding = the proxy scaled by f",
    "E11": "single-index comparators: the book with weight 1 on one index, always in, no resets, entry free, so cost never matters",
    "E12": "R3 window starts at the first D26 session on or after 2012-01-02 with its own spells and totals (in-or-out and gold), its own bounds, own draws (same seeds) and a free initial position in the state "
           "decided then",
    "E13": "R7(a): the rule with the GOLDBEES fill on sessions before 2014-07-01 replaced by the proxy's close; R7(b): the rule with the sleeve's gold weight 0.5 for decisions dated before 2014-07-01 and the "
           "timed weight from then on (the first decision after 2014-07-01 that sees a different weight trades the sleeve if OUT)",
    "E14": "F1 and F2 are run with the 50/50 sleeve at all three costs (R1 needs A1/A2 at 0 and 50 bps; T09.md section 3 step 11 says 'also run with the sleeve fixed at 50/50' without naming the costs); "
           "the R2 and R3 cells also run the fixed50 rule and F1 fixed50",
    "E15": "bounds of every series: lo = min(2, shortest spell of the state), hi = longest spell of the state, computed from the series in the run and asserted equal to the numbers of "
           "tests/T09/logs/step_1_spell_counts.json (the frozen section 2 values)",
    "E16": "the four books have identical decision and gold series and share the draws (states are generated once and stored under each book's key)",
    "E17": "sessions_invested = number of daily returns t = 1..T-1 earned while the proxy is held (state j is held from its trade session dec_idx[j]+1; T0 for j = 0) (T06-1, unchanged)",
    "E18": "the number of sleeve trades of a draw (draws.csv sleeve_trades) is counted from the states: decisions j >= 1 with a trade session inside the window, OUT at j-1 and j, g changed; 0 in fixed50 mode",
    "E19": "trades.csv drops T08's basket_eff column (no baskets); `quarterly_reset` is a trade kind; positions.csv and proxy_units.csv hold the unit counts after each trade",
    "E21": "V5(a) self-test seed: T06/T08's [6, 123456789] (the test is of the sampler code, which is unchanged; its result there was p = 0.83); a second run with seed [12, 6, 123456789] is reported beside it "
           "(p = 0.0031 in the first smoke run: above the 0.001 line, low but ordinary for one test); both must exceed 0.001",
    "E20": "no published-NAV file is read (R8 was declined): there is no g_engine.csv and the V4(d) always-in check against a published NAV does not exist; V4 is the identities of T09.md section 2",
}

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


_COMMON: dict = {}


def _read_sc100_prices(p: Path) -> pd.DataFrame:
    """Rule 7: the Smallcap 100 file is read as text and only lines dated T0 or later are parsed."""
    lines = p.read_text(encoding="utf-8").splitlines()
    keep = [lines[0]] + [ln for ln in lines[1:] if ln[:10] >= str(T0.date())]
    d = pd.read_csv(io.StringIO("\n".join(keep)), parse_dates=["date"]).set_index("date").sort_index()
    assert d.index.min() >= SC_PRICE_USABLE_FROM
    return d


def common() -> dict:
    """Calendar (D26), index prices (D25), the three D03 Master files, D24b (MAUc1 Master, weekly csv, daily range), gold (D09b + D09), cash (D11)."""
    if _COMMON:
        return _COMMON
    cal_p = ap(IDX_DIR / "nse_trading_days.csv")
    cal_all = pd.DatetimeIndex(sorted(pd.to_datetime(pd.read_csv(cal_p)["date"])))
    assert cal_all.is_unique and cal_all.max() >= END
    cal = cal_all[(cal_all >= T0) & (cal_all <= END)]
    assert cal[0] == T0 and cal[-1] == END, (cal[0], cal[-1])
    # D25 index prices, guard_window on the Smallcap 100 file
    px, dropped = {}, {}
    for n in INDICES:
        p = ap(IDX_DIR / f"{n}_daily_ohlcv.csv")
        if n == "SC100":
            AD.guard_window(p, T0)
            d = _read_sc100_prices(p)
        else:
            d = pd.read_csv(p, parse_dates=["date"]).set_index("date").sort_index()
        assert not d.index.duplicated().any()
        d = d[(d.index >= T0) & (d.index <= END)]
        dropped[n] = int((~d.index.isin(cal)).sum())
        d = d.reindex(cal)
        assert not d[["open", "high", "low", "close"]].isna().any().any(), f"{n}: a session of the window has no bar"
        assert (d[["open", "high", "low", "close"]] > 0).all().all()
        px[n] = d
    C = np.column_stack([px[n]["close"].values for n in INDICES]).astype(float)
    P = np.column_stack([((px[n]["open"] + px[n]["high"] + px[n]["low"] + px[n]["close"]) / 4).fillna(px[n]["close"]).values for n in INDICES]).astype(float)
    # the three Master files (D03): slice at once
    ms, rows_after = {}, {}
    for n in INDICES:
        p = ap(MASTER_DIR / f"Master_{n}.xlsx")
        if n == "SC100":
            AD.guard_window(p, T0)
        d = pd.read_excel(p, parse_dates=["Date"])
        s = d.dropna(subset=["SIGN"]).set_index("Date")["SIGN"].sort_index()
        s = s[~s.index.duplicated(keep="last")]
        rows_after[n] = int((s.index > END).sum())
        s = s[s.index <= END]
        if n == "SC100":
            s = s[s.index >= T0]                        # rule 7: nothing before T0 is kept
        assert s.index.min() <= T0, f"{n}: no Master row on or before T0"
        assert set(s.unique()) <= {"BUY", "SELL"}
        ms[n] = s
    # D24b: MAUc1 signal, weekly csv (cross-check), daily range
    gd = pd.read_excel(ap(D24B_DIR / "Master_MAUc1.xlsx"), parse_dates=["Date"])
    gs = gd.dropna(subset=["SIGN"]).set_index("Date")["SIGN"].sort_index()
    gs = gs[~gs.index.duplicated(keep="last")]
    gm_after = int((gs.index > END).sum())
    gs = gs[gs.index <= END]
    assert set(gs.unique()) <= {"BUY", "SELL"} and gs.index.min() <= T0
    wk = pd.read_csv(ap(D24B_DIR / "mauc1_supertrend_weekly_extended.csv"), parse_dates=["review"])
    wk = wk[wk["review"] <= END].sort_values("review").reset_index(drop=True)
    m = pd.read_csv(ap(D24B_DIR / "mauc1_daily_clean_extended.csv"), index_col=0, parse_dates=True)
    m.columns = [c.strip().lower() for c in m.columns]
    # gold: D09 (GOLDBEES) with T03's de-spike on the D24b range, D09b (proxy) before it
    g = pd.read_parquet(ap(GOLD_D09))
    g["date"] = pd.to_datetime(g["date"])
    g = g.set_index("date").sort_index()
    g = g[~g.index.duplicated(keep="last")]
    gb = pd.read_parquet(ap(GOLD_D09B))
    gb["date"] = pd.to_datetime(gb["date"])
    gb = gb.set_index("date").sort_index()
    assert gb.index.max() < g.index.min() and g.index.min() == GB_FIRST and gb.index.max() == GB_FIRST - pd.Timedelta(days=1), (gb.index.max(), g.index.min())
    rng = ((m["high"] - m["low"]) / m["close"]).reindex(g.index)
    band = rng + DESPIKE_TOL
    lo, hi = g["close"] * (1 - band), g["close"] * (1 + band)
    has = rng.notna()
    o = g["open"].where(~has, g["open"].clip(lower=lo, upper=hi))
    h = g["high"].where(~has, g["high"].clip(upper=hi))
    l_ = g["low"].where(~has, g["low"].clip(lower=lo))
    h = np.maximum(h, np.maximum(o, g["close"]))
    l_ = np.minimum(l_, np.minimum(o, g["close"]))
    gfill_g = (o + h + l_ + g["close"]) / 4
    gfill_b = (gb["open"] + gb["high"] + gb["low"] + gb["close"]) / 4
    gclose = pd.concat([gb["close"], g["close"]])
    gfill = pd.concat([gfill_b, gfill_g])
    gfill_alt = pd.concat([gb["close"], gfill_g])                       # R7(a): the proxy period filled at the close
    sess_g = cal[cal >= GB_FIRST]
    norange = [str(d.date()) for d in sess_g if d in g.index and not has.loc[d]]
    # cash
    lb = pd.read_csv(ap(HD / "LBES_Adjusted_Price_data_extended_2026-11-05.csv"))
    lb["date"] = pd.to_datetime(lb["date"], format="%d/%m/%y %H:%M")
    lb = lb.set_index("date")["price"].sort_index()
    lq = pd.read_csv(ap(HD / "liquidEtfFinal_extended_2026-11-05.csv"))
    lq["date"] = pd.to_datetime(lq["date"], format="mixed", dayfirst=True)
    lq = lq.set_index("date")["liquid_case"].sort_index()
    assert lb.index.max() >= END and lq.index.max() >= END and g.index.max() >= END
    _COMMON.update(cal=cal, px=px, C=C, P=P, dropped_not_in_cal=dropped, master=ms, master_rows_after_end=rows_after, gold_master=gs, gold_master_rows_after_end=gm_after, gold_weekly=wk,
                   gclose=gclose, gfill=gfill, gfill_alt=gfill_alt, gb=gb, g=g, mcx_daily=m, no_range_sessions=norange, lbes=lb, liq=lq)
    return _COMMON


def cash_levels(cal: pd.DatetimeIndex, kind: str = "lbes") -> tuple[np.ndarray, dict]:
    """E9. Level on every session of cal (as-of); nothing is accrued past a file's end."""
    c = common()
    ser = c["lbes"] if kind == "lbes" else c["liq"]
    assert not (cal > ser.index.max()).any(), f"cash file ends {ser.index.max().date()} before the window's last session: stop and ask Manu"
    lv = ser.reindex(ser.index.union(cal)).ffill().reindex(cal)
    assert lv.notna().all()
    return lv.values.astype(float), {"file_last": str(ser.index.max().date()), "accrued_sessions": 0, "cash": kind}


class Book:
    """Everything a run needs for one proxy book and one window, as plain arrays on the calendar."""

    def __init__(self, parent: str, start: pd.Timestamp | None = None, cash: str = "lbes", W=None, resets: bool = True):
        c = common()
        cal_all = c["cal"]
        k0 = 0 if start is None else int(cal_all.searchsorted(start))
        self.parent, self.k0 = parent, k0
        cal = cal_all[k0:]
        self.cal, self.T, self.t0 = cal, len(cal), cal[0]
        self.indices = INDICES
        self.C, self.P = c["C"][k0:].copy(), c["P"][k0:].copy()
        self.W = np.array(WEIGHTS[parent] if W is None else W, dtype=float)
        assert abs(self.W.sum() - 1) < 1e-7
        self.u0 = self.W / self.C[0]                       # E4: the proxy at the book's weights, NAV 1 at T0's close
        union = c["gclose"].index.union(cal)
        gc = c["gclose"].reindex(union).ffill().reindex(cal)
        assert gc.notna().all()
        own = cal.isin(c["gclose"].index)
        self.gold_no_own_bar = [str(d.date()) for d in cal[~own]]
        self.g = gc.values.astype(float)
        self.gf = c["gfill"].reindex(cal).fillna(gc).values.astype(float)
        self.gf_alt = c["gfill_alt"].reindex(cal).fillna(gc).values.astype(float)
        self.L, self.cash_info = cash_levels(cal, cash)
        mo = np.array([d.month for d in cal])
        prev = np.concatenate([[0], mo[:-1]])
        self.reset_events = {int(t) for t in range(1, self.T) if mo[t] in QUARTER_MONTHS and mo[t] != prev[t]} if resets else set()

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
            kg = gm.index.searchsorted(d, side="right") - 1
            lab_g, sign_g = gm.index[kg], gm.iloc[kg]
            rows.append({"book": self.parent, "j": j, "decision_date": d.date(), "decision_idx": int(i),
                         "trade_date": (cal[i + 1].date() if i + 1 < self.T else None),
                         **{f"sign_{n}": v[1] for n, v in lab.items()}, **{f"label_{n}": v[0].date() for n, v in lab.items()},
                         "latest_label": ld.date(), "label_age_days": (d - min(v[0] for v in lab.values())).days,
                         "all_three_buy": bool(state), "state": int(state),
                         "sign_MAUc1": sign_g, "label_MAUc1": lab_g.date(), "g": int(sign_g == "BUY"), "gw": GW_BUY if sign_g == "BUY" else GW_SELL})
        return pd.DataFrame(rows)


# ── simulation ────────────────────────────────────────────────────────────────
def trade(bk: Book, t: int, e_new: float, gw_new: float, u, gu, cu, ow: float, gf=None):
    ps, gp, lv = bk.P[t], (bk.gf if gf is None else gf)[t], bk.L[t]
    held_s = u * ps
    V = held_s.sum() + gu * gp + cu * lv
    Te = e_new * V * bk.W
    Tg = (1 - e_new) * gw_new * V                      # gw_new = 0.5 is the fixed 50/50 sleeve (T06's (1 - e)/2 * V)
    Tc = (1 - e_new) * (1 - gw_new) * V
    traded = np.abs(Te - held_s).sum() + abs(Tg - gu * gp) + abs(Tc - cu * lv)
    cost = ow * traded
    k = (V - cost) / V
    assert (ps > 0).all() and gp > 0 and lv > 0
    new_u = k * Te / ps
    ngu, ncu = k * Tg / gp, k * Tc / lv
    stock_after = float((new_u * ps).sum())
    w_after = (new_u * ps / stock_after) if stock_after > 0 else np.zeros(len(ps))
    return new_u, ngu, ncu, dict(V=V, traded=traded, cost=cost, stock_before=float(held_s.sum()), gold_before=float(gu * gp), cash_before=float(cu * lv),
                                 stock_after=stock_after, gold_after=float(ngu * gp), cash_after=float(ncu * lv), V_after=stock_after + float(ngu * gp) + float(ncu * lv),
                                 index_gap=float(np.abs(new_u * ps - k * Te).max() / V), weight_gap=float(np.abs(w_after - bk.W).max()) if stock_after > 0 else 0.0,
                                 held_before=held_s.copy(), idx_after=(new_u * ps).copy())


def simulate(bk: Book, dec_idx: np.ndarray, e: np.ndarray, cost_bps: float, every: bool = False, record: bool = False, gw: np.ndarray | None = None, gf=None):
    """e[j] = proxy share decided at decision j; gw[j] = gold weight of the non-proxy share decided at j (None = 0.5 always: the 50/50 sleeve).
    A trade is due on the session after decision j iff e changed or (e < 1 and gw changed) [or `every`]; quarterly resets while IN. Returns daily NAV and, if record, the trade and position logs."""
    T, ow = bk.T, cost_bps / 2e4
    gwa = np.full(len(e), GW_FIX) if gw is None else np.asarray(gw, dtype=float)
    gfv = bk.gf if gf is None else gf
    e_cur, gw_cur = float(e[0]), float(gwa[0])
    u = bk.u0 * e_cur
    gu = (1 - e_cur) * gw_cur / bk.g[0]
    cu = (1 - e_cur) * (1 - gw_cur) / bk.L[0]
    tgt = {}
    for j in range(0 if every else 1, len(dec_idx)):
        tr = int(dec_idx[j]) + 1
        if tr < T and (every or e[j] != e[j - 1] or (e[j] < 1 and gwa[j] != gwa[j - 1])):
            tgt[tr] = (float(e[j]), float(gwa[j]), j)
    ev = sorted(set(tgt) | bk.reset_events)
    nav = np.empty(T)
    nz = np.flatnonzero(u)
    a = 0
    trades, pos_log = [], []
    for t in ev:
        if t > a:
            nav[a:t] = bk.C[a:t][:, nz] @ u[nz] + bk.g[a:t] * gu + bk.L[a:t] * cu if len(nz) else bk.g[a:t] * gu + bk.L[a:t] * cu
        a = t
        if t in tgt or (t in bk.reset_events and e_cur > 0 and not every):
            e_new, gw_new, jd = tgt[t] if t in tgt else (e_cur, gw_cur, None)
            kind = ("switch_in" if e_new > e_cur else "switch_out" if e_new < e_cur else
                    (("mix_rebalance" if every else "sleeve_rebalance") if t in tgt else "quarterly_reset"))
            u, gu, cu, info = trade(bk, t, e_new, gw_new, u, gu, cu, ow, gf=gfv)
            e_cur, gw_cur = e_new, gw_new
            nz = np.flatnonzero(u)
            if record:
                nav_close = float(bk.C[t][nz] @ u[nz] + gu * bk.g[t] + cu * bk.L[t]) if len(nz) else float(gu * bk.g[t] + cu * bk.L[t])
                trades.append({"date": bk.cal[t].date(), "idx": t, "kind": kind, "e_after": e_new, "gw_after": gw_new, **info, "nav_close_after": nav_close, "dec_j": jd,
                               "u_after": u.copy(), "gu_after": gu, "cu_after": cu})
                for i in nz:
                    pos_log.append({"date": bk.cal[t].date(), "instrument": INDICES[i], "units": u[i]})
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
    Seed [12, 3, id] for the in-or-out series, [12, 11, 3, id] for the gold series (state 1 = BUY)."""
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
    """E15: per state (1 = in/BUY, 0 = out/SELL) lo = min(2, shortest spell of the state), hi = the longest spell of the state, from the series itself."""
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
    """V3 on every draw of both nulls for one series (T09.md section 2, gate V3). For a gold series 'in' = BUY and 'out' = SELL."""
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
                "quarterly_resets": sum(1 for t in tr if t["kind"] == "quarterly_reset")}

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
        if headline:
            keep("strategy", cost, tr, pos, nav)
            for t in tr:
                if t["kind"] in SLEEVE_KINDS:
                    j = t["dec_j"]
                    out["sleeve_trades"].append({
                        "book": bk.parent, "cost_bps": cost, "decision_date": dts[j], "date": str(t["date"]), "kind": t["kind"], "g_before": int(g[j - 1]), "g_after": int(g[j]),
                        "gw_before": float(gw_real[j - 1]), "gw_after": float(gw_real[j]), "gold_value_before": t["gold_before"], "cash_value_before": t["cash_before"],
                        "gold_value_after": t["gold_after"], "cash_value_after": t["cash_after"], "traded": t["traded"], "cost": t["cost"],
                        "gold_fill_proxy_period": bool(bk.cal[t["idx"]] < GB_FIRST)})
                if t["kind"] == "quarterly_reset":
                    out["resets"].append({"book": bk.parent, "cost_bps": cost, "date": str(t["date"]), "idx": t["idx"], "V": t["V"], "traded": t["traded"], "cost": t["cost"],
                                          **{f"value_before_{n}": float(t["held_before"][i]) for i, n in enumerate(INDICES)},
                                          **{f"value_after_{n}": float(t["idx_after"][i]) for i, n in enumerate(INDICES)}})
        # fixed 50/50 rule on every cell (A1/A2 judge it); the headline cell also keeps its trades
        nv50, tr50, _ = simulate(bk, idx, sf, cost, record=True, gw=None)
        out["rows"].append(stat_row("strategy_fixed50", cost, nv50, tr50, int(s.sum())))
        if headline:
            keep("strategy_fixed50", cost, tr50, None, nv50)
    if headline:
        one_hot = {n: np.eye(3)[i] for i, n in enumerate(INDICES)}
        for cost in costs:
            variants = [("hold_proxy", np.ones(len(s)), False, None, bk, None), ("constant_mix", np.full(len(s), f), True, None, bk, None),
                        ("constant_mix_timed", np.full(len(s), f), True, gw_real, bk, None), ("sleeve_only", np.zeros(len(s)), False, None, bk, None),
                        ("sleeve_only_timed", np.zeros(len(s)), False, gw_real, bk, None)]
            for n_i, w_i in one_hot.items():
                b1 = copy.copy(bk)
                b1.W, b1.u0, b1.reset_events = w_i, w_i / bk.C[0], set()
                variants.append((f"index_{n_i}", np.ones(len(s)), False, None, b1, None))
            for name, e_arr, every, gwv, bkx, gfx in variants:
                nv, tr2, _ = simulate(bkx, idx, e_arr, cost, every=every, record=True, gw=gwv)
                out["rows"].append(stat_row(name, cost, nv, tr2, float(e_arr.sum())))
                keep(name, cost, tr2, None, nv)
        # R7 variants of the rule at the primary cost, full window, headline cell
        b7a = copy.copy(bk)
        nv7a, tr7a, _ = simulate(b7a, idx, sf, PRIMARY, record=True, gw=gw_real, gf=bk.gf_alt)
        out["rows"].append(stat_row("strategy_r7a_proxy_fill_at_close", PRIMARY, nv7a, tr7a, int(s.sum())))
        gw7b = np.where(pd.to_datetime(dec["decision_date"]).values < np.datetime64(GB_FIRST), GW_FIX, gw_real)
        nv7b, tr7b, _ = simulate(bk, idx, sf, PRIMARY, record=True, gw=gw7b)
        out["rows"].append(stat_row("strategy_r7b_gold_weight_50_before_2014-07-01", PRIMARY, nv7b, tr7b, int(s.sum())))

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


def hand_hold_proxy(bk: Book) -> np.ndarray:
    """V4(b): the always-in proxy at 0 cost built by a plain loop: units at the weights, reset at the OHLC4 of every quarterly reset session."""
    u = bk.W / bk.C[0]
    nav = np.empty(bk.T)
    for t in range(bk.T):
        if t in bk.reset_events:
            V = float((u * bk.P[t]).sum())
            u = bk.W * V / bk.P[t]
        nav[t] = float((u * bk.C[t]).sum())
    return nav


def shared_code_diff() -> dict:
    """V4(c): functions shared with t08_engine.py. Identical = the same AST (docstrings included); the changed ones must be the expected ones."""
    def fns(path):
        tree = ast.parse(Path(path).read_text(encoding="utf-8"))
        return {n.name: ast.dump(n) for n in tree.body if isinstance(n, ast.FunctionDef)}
    a, b = fns(T08_ENGINE), fns(Path(__file__))
    must_equal = ["stats", "sessions_invested", "spells", "spell_sig", "count_table", "draw_lengths", "ie_count", "lens_of", "chi2_sf_even", "n_sleeve_trades", "gold_spells_with_out",
                  "flip_counts"]
    expected_changed = ["trade", "simulate", "spell_shuffle", "free_length_draw", "v3_check", "make_states_io", "make_states_gold", "sampler_selftest_small", "run_book",
                        "common", "cash_levels", "v6_check", "main"]
    common_names = sorted(set(a) & set(b))
    changed = [n for n in common_names if a[n] != b[n]]
    unexpected = [n for n in changed if n not in expected_changed]
    not_equal_required = [n for n in must_equal if n not in a or n not in b or a[n] != b[n]]
    # the sleeve arithmetic lines of `trade` must be the same text in both files
    sleeve_lines = ["Tg = (1 - e_new) * gw_new * V", "Tc = (1 - e_new) * (1 - gw_new) * V", "traded = np.abs(Te - held_s).sum() + abs(Tg - gu * gp) + abs(Tc - cu * lv)",
                    "cost = ow * traded", "k = (V - cost) / V"]
    t8, t9 = T08_ENGINE.read_text(encoding="utf-8"), Path(__file__).read_text(encoding="utf-8")
    lines_ok = {ln: bool(ln in t8 and ln in t9) for ln in sleeve_lines}
    return {"compared": must_equal, "identical_required": [n for n in must_equal if n not in not_equal_required], "required_not_identical": not_equal_required,
            "changed_functions": changed, "unexpected_changes": unexpected, "expected_changes": expected_changed, "sleeve_arithmetic_lines_in_both": lines_ok,
            "pass": bool(not not_equal_required and not unexpected and all(lines_ok.values()))}


def v4_identities(books, bks, out, dec_all) -> dict:
    """V4 (a) one-index book reproduces the index; (b) hold-the-proxy equals the hand-built NAV; (c) shared code; (d) signals equal the Master / weekly files; (e) the gold splice."""
    res = {"a_one_index_book": {}, "b_hold_proxy_vs_hand": {}, "d_signals": {}, "e_splice": {}}
    ok = True
    c = common()
    for p in books:
        bk = bks[p]
        worst = {}
        for i, n in enumerate(INDICES):
            b1 = copy.copy(bk)
            b1.W, b1.u0 = np.eye(3)[i], np.eye(3)[i] / bk.C[0]          # keeps the reset code path
            nv = simulate(b1, np.array([0]), np.ones(1), 0.0)
            worst[n] = float(np.abs(nv / (bk.C[:, i] / bk.C[0, i]) - 1).max())
        pa = bool(all(v < REL_TOL_NAV for v in worst.values()))
        res["a_one_index_book"][p] = {"max_rel_diff": worst, "pass": pa}
        nv_e = simulate(bk, np.array([0]), np.ones(1), 0.0)
        hand = hand_hold_proxy(bk)
        rel = float(np.abs(nv_e / hand - 1).max())
        pb = bool(rel < REL_TOL_NAV)
        res["b_hold_proxy_vs_hand"][p] = {"max_rel_diff": rel, "resets": len(bk.reset_events), "pass": pb}
        ok &= pa and pb
        dec = next(d for d in dec_all if d["book"].iloc[0] == p)
        bad = {"index_sign": 0, "mauc1_sign": 0, "mauc1_weekly_signal": 0, "mauc1_weekly_label": 0}
        wk = c["gold_weekly"]
        for r in dec.itertuples():
            d = pd.Timestamp(r.decision_date)
            for n in INDICES:
                sr = c["master"][n]
                got = sr[sr.index <= d].iloc[-1]
                bad["index_sign"] += got != getattr(r, f"sign_{n}")
            gsr = c["gold_master"]
            bad["mauc1_sign"] += gsr[gsr.index <= d].iloc[-1] != r.sign_MAUc1
            k = wk["review"].searchsorted(d, side="right") - 1
            bad["mauc1_weekly_signal"] += int(round(float(wk["signal"].iloc[k]))) != int(r.g)
            bad["mauc1_weekly_label"] += str(wk["review"].iloc[k].date()) != str(r.label_MAUc1)
        pd_ = bool(all(v == 0 for v in bad.values()) and len(dec) > 0)
        res["d_signals"][p] = {"decisions": int(len(dec)), **{k: int(v) for k, v in bad.items()}, "pass": pd_}
        ok &= pd_
    # (e) splice D09b -> D09
    gb, g, m = c["gb"], c["g"], c["mcx_daily"]
    d0 = g.index[0]
    last_b = gb.index[-1]
    ret_splice = float(g["close"].iloc[0] / gb["close"].iloc[-1] - 1)
    ret_mau = float(m["close"].loc[d0] / m["close"].loc[:last_b].iloc[-1] - 1)
    consecutive = bool(m.index[m.index.get_loc(d0) - 1] == last_b)
    cl = c["gclose"]
    gaps = int((cl.index.to_series().diff().dt.days > 7).sum())
    pe = bool(abs(ret_splice - ret_mau) < 1e-9 and consecutive and gaps == 0)
    res["e_splice"] = {"splice_day": str(d0.date()), "proxy_last": str(last_b.date()), "return_on_splice_day": ret_splice, "mauc1_own_return": ret_mau, "difference": ret_splice - ret_mau,
                       "mauc1_rows_consecutive": consecutive, "gold_close_gaps_over_7_days": gaps, "sessions_without_own_gold_bar": next(iter(bks.values())).gold_no_own_bar, "pass": pe}
    ok &= pe
    res["c_shared_code"] = shared_code_diff()
    ok &= res["c_shared_code"]["pass"]
    res["pass"] = bool(ok)
    return res


def v6_check(out: dict, books, bks: dict, dec_all: list) -> dict:
    """V6 the sleeve and reset identities, on every trade of every headline run (full window, LBES) and on constant-g re-runs."""
    TOL = 1e-12
    worst = {"cost_identity": 0.0, "value_conservation": 0.0, "index_target_gap": 0.0, "gold_target_gap": 0.0, "cash_target_gap": 0.0, "traded_identity": 0.0,
             "continuity_0cost": 0.0, "weight_gap_vs_table": 0.0, "index_weight_gap_after_entry_or_reset": 0.0, "per_index_value_gap": 0.0}
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
        worst["index_target_gap"] = max(worst["index_target_gap"], abs(t["stock_after"] - e * (V - cost)) / V)
        worst["gold_target_gap"] = max(worst["gold_target_gap"], abs(t["gold_after"] - (1 - e) * gwv * (V - cost)) / V)
        worst["cash_target_gap"] = max(worst["cash_target_gap"], abs(t["cash_after"] - (1 - e) * (1 - gwv) * (V - cost)) / V)
        worst["per_index_value_gap"] = max(worst["per_index_value_gap"], t["index_gap"])
        if t["kind"] in ("switch_in", "quarterly_reset", "mix_rebalance") and e > 0 and not t["run"].startswith("index_"):
            worst["index_weight_gap_after_entry_or_reset"] = max(worst["index_weight_gap_after_entry_or_reset"], t["weight_gap"])
        if e == 0:
            exp_tr = t["stock_before"] + abs(gwv * V - t["gold_before"]) + abs((1 - gwv) * V - t["cash_before"])
            worst["traded_identity"] = max(worst["traded_identity"], abs(t["traded"] - exp_tr) / V)
        if t["run"] == "strategy" and t["kind"] in SLEEVE_KINDS:
            j = t["dec_j"]
            d = decs[t["book"]]
            want = GW_BUY if int(d["g"].iloc[j]) == 1 else GW_SELL
            sh = t["gold_after"] / (t["gold_after"] + t["cash_after"])
            worst["weight_gap_vs_table"] = max(worst["weight_gap_vs_table"], abs(sh - want), abs(gwv - want))
            assert t["kind"] == "switch_out" or (t["stock_before"] == 0 and e == 0)
    # the real rule's sleeve trades and quarterly resets equal the independent expectation at every cost
    sleeve_ok, reset_ok, listed, listed_r = True, True, {}, {}
    for p in books:
        d = decs[p]
        bk = bks[p]
        idx, s, g = d["decision_idx"].values, d["state"].values.astype(int), d["g"].values.astype(int)
        T = bk.T
        exp = sorted(int(idx[j]) + 1 for j in range(1, len(idx)) if int(idx[j]) + 1 < T and s[j] == 0 and s[j - 1] == 0 and g[j] != g[j - 1])
        # position held at the start of every session, from the real states alone
        change = {int(idx[j]) + 1: s[j] for j in range(1, len(idx)) if int(idx[j]) + 1 < T and s[j] != s[j - 1]}
        pos, cur, held_before = np.zeros(T, dtype=int), int(s[0]), np.zeros(T, dtype=int)
        for t in range(T):
            held_before[t] = cur
            if t in change:
                cur = int(change[t])
        exp_r = sorted(t for t in bk.reset_events if held_before[t] == 1 and t not in change)
        exp_r_hold = sorted(bk.reset_events)
        for cost in COSTS:
            got = sorted(t["idx"] for t in out["trades"] if t["book"] == p and t["run"] == "strategy" and t["cost_bps"] == cost and t["kind"] == "sleeve_rebalance")
            sleeve_ok &= got == exp
            got_r = sorted(t["idx"] for t in out["trades"] if t["book"] == p and t["run"] == "strategy" and t["cost_bps"] == cost and t["kind"] == "quarterly_reset")
            reset_ok &= got_r == exp_r
            got_h = sorted(t["idx"] for t in out["trades"] if t["book"] == p and t["run"] == "hold_proxy" and t["cost_bps"] == cost and t["kind"] == "quarterly_reset")
            reset_ok &= got_h == exp_r_hold
        listed[p], listed_r[p] = len(exp), len(exp_r)
    const = {}
    for p in books:
        d = decs[p]
        idx, s = d["decision_idx"].values, d["state"].values.astype(float)
        for name, c_ in (("BUY", GW_BUY), ("SELL", GW_SELL)):
            for cost in (0.0, PRIMARY):
                _, tr, _ = simulate(bks[p], idx, s, cost, record=True, gw=np.full(len(s), c_))
                const[f"{p}|{name}|{cost}"] = {"sleeve_trades": sum(1 for t in tr if t["kind"] == "sleeve_rebalance"), "trades": len(tr)}
    const_ok = all(v["sleeve_trades"] == 0 for v in const.values())
    ex = {}
    p0 = books[0]
    for kind in ("switch_out", "sleeve_rebalance", "quarterly_reset", "switch_in"):
        for t in out["trades"]:
            if t["book"] == p0 and t["run"] == "strategy" and t["cost_bps"] == PRIMARY and t["kind"] == kind:
                j = t["dec_j"]
                d = decs[p0].iloc[j] if j is not None else None
                gwv, V, cost = t["gw_after"], t["V"], t["cost"]
                ex[kind] = {"decision_date": str(d["decision_date"]) if d is not None else None, "trade_date": str(t["date"]), "g_read": d["sign_MAUc1"] if d is not None else None, "gw": gwv, "V": V,
                            "index_value_before": t["stock_before"], "gold_before": t["gold_before"], "cash_before": t["cash_before"], "traded": t["traded"], "cost": cost,
                            "index_values_after": [float(x) for x in t["idx_after"]], "weights_after": [float(x / t["stock_after"]) for x in t["idx_after"]] if t["stock_after"] > 0 else None,
                            "gold_after": t["gold_after"], "cash_after": t["cash_after"], "expected_gold_after": (1 - t["e_after"]) * gwv * (V - cost),
                            "expected_cash_after": (1 - t["e_after"]) * (1 - gwv) * (V - cost), "expected_index_total_after": t["e_after"] * (V - cost)}
                break
    ok = bool(n > 0 and all(v <= TOL for v in worst.values()) and sleeve_ok and reset_ok and const_ok)
    return {"trades_checked": int(n), "trades_checked_at_0_cost": int(n0), "kinds": {f"{a}|{b}": int(c) for (a, b), c in sorted(kinds.items())}, "worst": worst, "tolerance": TOL,
            "real_rule_sleeve_trades_equal_expected_at_every_cost": bool(sleeve_ok), "expected_sleeve_trades_per_book": listed,
            "real_rule_resets_and_hold_proxy_resets_equal_expected_at_every_cost": bool(reset_ok), "expected_strategy_resets_per_book": listed_r,
            "quarter_start_sessions": len(bks[books[0]].reset_events), "constant_g_no_sleeve_trade": const_ok, "constant_g_detail": const, "worked_examples": ex,
            "not_checked_here": "weights drift between trades by construction (units are constant between trade sessions); the initial position at T0 is built from gw[0] without a trade record", "pass": ok}


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
    outdir = T09 / "evidence" / a.run
    outdir.mkdir(parents=True, exist_ok=True)
    t_start = time.time()
    books = a.books or (BOOKS[:1] if a.quick else BOOKS)
    assert all(b in BOOKS for b in books), books
    n_draws = a.draws if a.draws else (20 if a.quick else N_DRAWS)
    s1 = json.loads(STEP1.read_text(encoding="utf-8"))
    assert s1["window"] == [str(T0.date()), str(END.date())] and s1["r3_start"] == str(R3_START.date()), f"step_1_spell_counts.json is for {s1['window']}, the engine has T0 {T0.date()}"
    out = {"rows": [], "draw_rows": [], "draw_rows_written": 0, "nav": {}, "trades": [], "positions": [], "sleeve_trades": [], "resets": [], "v2_trades": 0}
    curves: dict = {}
    dec_all, bks = [], {}
    audit = {"readings": READINGS, "books": {}}

    # the data boundary: every input through the approved table, sha256 checked, window covered, rule 7 guard
    common()
    registered_not_parsed = []
    for rel, r in USED.items():
        if r["id"] in ("D25", "D26", "D03", "D09", "D11", "D24b"):
            assert r["through"] >= str(END.date()), f"{rel}: approved through {r['through']}, before the window's end {END.date()}: stop and ask Manu"
        if r["id"] == "D09b":
            assert r["through"] == str((GB_FIRST - pd.Timedelta(days=1)).date())
    pd.DataFrame([{k: v.get(k) for k in ("file", "through", "bytes", "sha256", "approved_row", "usable_from")} for v in USED.values()]).to_csv(outdir / "inputs.csv", index=False)
    selftest = {}
    for name, f in (("superseded_master", HD / "frozen_2026-09-25" / "Master" / "Master_Nifty100.xlsx"),
                    ("superseded_goldbees", AA / "analysis" / "cache" / "why_gold_ohlc_eikon.parquet"),
                    ("pending_candidate_d03b", HD / "extended_2026-11-12" / "SC100_signal_from_2011-10-03" / "Master_SC100.xlsx"),
                    ("not_in_table", HD / "no_such_file.csv")):
        try:
            ap(f)
            selftest[name] = {"raised": False}
        except NotApprovedError as e:
            selftest[name] = {"raised": True, "message": str(e)}
    uf_sig = pd.Timestamp(AD.usable_from(MASTER_DIR / "Master_SC100.xlsx"))
    uf_px = pd.Timestamp(AD.usable_from(IDX_DIR / "SC100_daily_ohlcv.csv"))
    assert uf_px == SC_PRICE_USABLE_FROM and uf_sig <= T0, (uf_px, uf_sig)
    for name, f, first in (("guard_sc100_prices_before_usable_from", IDX_DIR / "SC100_daily_ohlcv.csv", str((uf_px - pd.Timedelta(days=1)).date())),
                           ("guard_sc100_signal_before_usable_from", MASTER_DIR / "Master_SC100.xlsx", str((uf_sig - pd.Timedelta(days=1)).date()))):
        try:
            AD.guard_window(f, first)
            selftest[name] = {"raised": False}
        except NotApprovedError as e:
            selftest[name] = {"raised": True, "message": str(e)}
    selftest["guard_sc100_at_T0_passes"] = {"raised": False, "ok": True}
    AD.guard_window(IDX_DIR / "SC100_daily_ohlcv.csv", T0)
    AD.guard_window(MASTER_DIR / "Master_SC100.xlsx", T0)
    selftest["pass"] = all(v.get("raised", False) for k, v in selftest.items() if isinstance(v, dict) and k != "guard_sc100_at_T0_passes")
    print(f"data: window {T0.date()} -> {END.date()}, approved data as of {AD.as_of()}, {len(USED)} inputs checked; non-approved open and Smallcap 100 guards raise: {selftest['pass']}", flush=True)

    ct, v3_res, v5c = {}, {}, {}
    states_all: dict = {}
    real_states: dict = {}
    first_draw_write = True
    shared = {}
    live_gate: dict = {}
    for p in books:
        t1 = time.time()
        bk = Book(p)
        bks[p] = bk
        dec = bk.decisions()
        dec_all.append(dec)
        s = dec["state"].values.astype(int)
        g = dec["g"].values.astype(int)
        b_io, b_g = series_bounds(s), series_bounds(g)
        exp_io, exp_g = s1["full"]["io_tables"], s1["full"]["gold_tables"]
        for st, nm in ((1, "in"), (0, "out")):
            assert b_io[st] == (exp_io[nm]["lo"], exp_io[nm]["hi"]), f"{p}: in/out bounds {b_io[st]} differ from step 1 {exp_io[nm]}"
            assert b_g[st] == (exp_g[nm]["lo"], exp_g[nm]["hi"]), f"{p}: gold bounds {b_g[st]} differ from step 1 {exp_g[nm]}"
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
        assert sc_min_label >= T0, f"a Smallcap 100 signal row dated {sc_min_label.date()} (before T0) was read"
        sc_min_price = bk.cal[0]
        assert sc_min_price >= SC_PRICE_USABLE_FROM
        r0, rg = lens_of(s), lens_of(g)
        fl = flip_counts(s, g)
        audit["books"][p] = {"t0": str(bk.t0.date()), "last_session": str(bk.cal[-1].date()), "sessions": bk.T, "decisions": len(dec), "invested_weeks": int(s.sum()),
                             "weights": dict(zip(INDICES, WEIGHTS[p])), "first_state": int(s[0]), "in_lengths": r0[0], "out_lengths": r0[1],
                             "bounds": {"in": list(b_io[1]), "out": list(b_io[0])}, "in_spells": len(r0[0]), "out_spells": len(r0[1]), "round_trips": min(len(r0[0]), len(r0[1])),
                             "sessions_invested_rule": sessions_invested(bk, dec["decision_idx"].values, s),
                             "gold": {"first_state": int(g[0]), "buy_lengths": rg[0], "sell_lengths": rg[1], "buy_weeks": int(g.sum()), "bounds": {"buy": list(b_g[1]), "sell": list(b_g[0])},
                                      "shortest_spell": min(rg[0] + rg[1]), "spells_with_an_out_week": gold_spells_with_out(s, g), **fl,
                                      "sleeve_trades_expected": n_sleeve_trades(dec["decision_idx"].values, bk.T, s, g)},
                             "v2_decisions_checked": len(dec), "v2_label_after_decision": len(dec) - lab_ok, "v2_mauc1_label_after_decision": len(dec) - lab_g_ok,
                             "v2_trades_checked": traded_rows, "v2_trade_not_after_decision": int((tdates.values <= ddates.values).sum()),
                             "v2_sc100_signal_first_label_date": str(sc_min_label.date()), "v2_sc100_price_first_session_read": str(sc_min_price.date()),
                             "stale_label_weeks(age>=5d, excluding T0)": int((dec["label_age_days"].values[1:] >= 5).sum()), "cash": bk.cash_info,
                             "quarter_start_reset_sessions": len(bk.reset_events), "gold_sessions_without_own_bar": bk.gold_no_own_bar}
        real_states[f"{p}|full|io"], real_states[f"{p}|full|gold"] = s.astype(np.uint8), g.astype(np.uint8)
        if "full" not in shared:                                              # E16: one set of draws for the four books
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
        run_book(bk, dec, st_io, st_g, "full", "lbes", plan_full, True, out, curves)
        # R2: LIQUIDCASE cash (the same states)
        bk3 = Book(p, cash="liq")
        run_book(bk3, dec, st_io, st_g, "full", "liq", [("F1", PRIMARY, "timed"), ("F3", PRIMARY, "timed"), ("F1", PRIMARY, "fixed50")], False, out, curves)
        # R3: window from 2012-01-02, its own spells, totals and bounds
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
        live_ok = bool(rt >= 4 and gout >= 4 and all(feas.values()))
        live_gate[p] = {"round_trips": rt, "gold_spells_with_an_out_week": gout, "feasible": feas, "reportable": live_ok}
        audit["books"][p]["r3_window"] = {"t0": str(bk4.t0.date()), "decisions": len(dec4), "round_trips": rt, "reportable": live_ok, "first_state": int(s4[0]), "in_lengths": r4[0], "out_lengths": r4[1],
                                          "bounds": {"in": list(b4_io[1]), "out": list(b4_io[0]), "buy": list(b4_g[1]), "sell": list(b4_g[0])}, "gold_first_state": int(g4_[0]),
                                          "g_buy_lengths": rg4[0], "g_sell_lengths": rg4[1], "gold_spells_with_an_out_week": gout, "feasible": feas,
                                          **{f"gold_{k}": v for k, v in flip_counts(s4, g4_).items()}, "sessions_invested_rule": sessions_invested(bk4, dec4["decision_idx"].values, s4)}
        real_states[f"{p}|r3|io"], real_states[f"{p}|r3|gold"] = s4.astype(np.uint8), g4_.astype(np.uint8)
        windows = [("full", s, g, b_io, b_g)]
        if live_ok:
            windows.append(("r3", s4, g4_, b4_io, b4_g))
            if "r3" not in shared:
                shared["r3"] = {"s": s4, "g": g4_, "io": make_states_io(s4, n_draws, b4_io), "gold": make_states_gold(g4_, n_draws, b4_g)}
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
        flush_draws(out, outdir / "draws.csv", first_draw_write)
        first_draw_write = False
        print(f"{p}: {time.time() - t1:.0f}s  decisions {len(dec)}  round trips {audit['books'][p]['round_trips']}  gold flips {fl['flips']} (sleeve trades {audit['books'][p]['gold']['sleeve_trades_expected']})", flush=True)

    # V4 identities, V5 samplers, V6 identities, V3 summary
    reg = v4_identities(books, bks, out, dec_all)
    (outdir / "regression.json").write_text(json.dumps(reg, indent=1, default=str), encoding="utf-8")
    small = sampler_selftest_small()                                   # T06/T08's self-test seed [6, 123456789]: same sampler code, same k, S, bounds
    small12 = sampler_selftest_small(seed=(12, 6, 123456789))          # and a seed with T09's first element, reported beside it
    small["also_seed_12"] = {"p": small12["p"], "pass": small12["pass"], "seed": small12["seed"]}
    small["pass"] = bool(small["pass"] and small12["pass"])
    v5b = all(v["dp_equals_inclusion_exclusion"] for v in ct.values())
    v5 = {"a_small_case": small, "b_dp_equals_inclusion_exclusion": {"all_equal": bool(v5b), "checked": int(len(ct))},
          "c_mean_length_within_4_se": v5c, "pass": bool(small["pass"] and v5b and all(v["pass"] for v in v5c.values()))}
    (outdir / "sampler_selftest.json").write_text(json.dumps(v5, indent=1, default=str), encoding="utf-8")
    b0 = audit["books"][books[0]]
    (outdir / "count_table.json").write_text(json.dumps({"bounds": {"full": {"io": b0["bounds"], "gold": b0["gold"]["bounds"]}, "r3": {k: v for k, v in b0["r3_window"]["bounds"].items()}},
                                                         "tables": ct}, indent=1), encoding="utf-8")
    v6 = v6_check(out, books, bks, dec_all)

    # step-1 spell counts reproduced from the data (full and R3)
    s1_ok, s1_detail = True, {}
    for p in books:
        for w, key in (("full", "full"), ("r3", "r3")):
            exp = s1[key]
            mine = audit["books"][p] if w == "full" else audit["books"][p]["r3_window"]
            gm = mine["gold"] if w == "full" else mine
            gl = (lambda k: gm[k]) if w == "full" else (lambda k: mine[k])
            good = (mine["in_lengths"] == exp["in_lengths"] and mine["out_lengths"] == exp["out_lengths"] and mine["first_state"] == exp["first_state"]
                    and (mine["decisions"] == exp["weeks"])
                    and (gm["buy_lengths"] if w == "full" else mine["g_buy_lengths"]) == exp["g_buy_lengths"]
                    and (gm["sell_lengths"] if w == "full" else mine["g_sell_lengths"]) == exp["g_sell_lengths"]
                    and (gm["first_state"] if w == "full" else mine["gold_first_state"]) == exp["g_first_state"]
                    and (gm["flips"] if w == "full" else mine["gold_flips"]) == exp["g_flips"]
                    and (gm["while_out_both_sides"] if w == "full" else mine["gold_while_out_both_sides"]) == exp["g_flips_while_out_both_sides"]
                    and (gm["on_exit_decision"] if w == "full" else mine["gold_on_exit_decision"]) == exp["g_flips_on_an_exit_decision"]
                    and ((gm["while_in"] + gm["on_entry_decision"]) if w == "full" else (mine["gold_while_in"] + mine["gold_on_entry_decision"])) == exp["g_flips_while_in"]   # step 1 counts every flip at a decision whose state is IN
                    and (gm["spells_with_an_out_week"] if w == "full" else mine["gold_spells_with_an_out_week"]) == exp["g_spells_with_an_out_week"]
                    and (gm["weeks_buy_while_out"] if w == "full" else mine["gold_weeks_buy_while_out"]) == exp["g_weeks_buy_while_out"])
            for ser, tkey, names in (("io", "io_tables", ("in", "out")), ("gold", "gold_tables", ("buy", "sell"))):
                for nm, enm in zip(names, ("in", "out")):
                    c_ = ct[f"{p}|{w}|{ser}|{nm}"]
                    t_ = exp[tkey][enm]
                    good &= (c_["n_ways"] == t_["n_ways"] and c_["lo"] == t_["lo"] and c_["hi"] == t_["hi"] and c_["spells_k"] == t_["k"] and c_["weeks_S"] == t_["S"])
            s1_detail[f"{p}|{w}"] = bool(good)
            s1_ok &= good
        s1_ok &= (tuple(audit["books"][p]["weights"].values()) == tuple(s1["weights"]["typed"][p]))
        s1_ok &= (audit["books"][p]["quarter_start_reset_sessions"] == s1["full"]["quarter_start_sessions_in_window"])

    # write
    flush_draws(out, outdir / "draws.csv", first_draw_write)
    pd.concat(dec_all).to_csv(outdir / "decisions.csv", index=False)
    pd.concat(dec_all)[["book", "j", "decision_date", "label_MAUc1", "sign_MAUc1", "g", "gw"]].to_csv(outdir / "gold_signal.csv", index=False)
    rows = pd.DataFrame(out["rows"])
    rows.to_csv(outdir / "stats.csv", index=False)
    tcols = ["book", "cost_bps", "run", "date", "idx", "kind", "e_after", "V", "traded", "cost", "nav_close_after", "gw_after"]
    tdf = pd.DataFrame(out["trades"])[tcols]
    tdf.loc[tdf["run"].isin(["hold_proxy"]) | tdf["run"].str.startswith("index_"), "gw_after"] = np.nan
    tdf.to_csv(outdir / "trades.csv", index=False)
    pd.DataFrame(out["sleeve_trades"]).to_csv(outdir / "sleeve_trades.csv", index=False)
    pd.DataFrame(out["resets"]).to_csv(outdir / "quarterly_resets.csv", index=False)
    pd.DataFrame(out["positions"]).to_csv(outdir / "positions.csv", index=False)
    pu = [{"book": t["book"], "cost_bps": t["cost_bps"], "run": t["run"], "date": str(t["date"]), "idx": t["idx"], "kind": t["kind"],
           **{f"units_{n}": float(t["u_after"][i]) for i, n in enumerate(INDICES)}, "units_GOLDBEES": float(t["gu_after"]), "units_LBES": float(t["cu_after"])}
          for t in out["trades"] if t["run"] in ("strategy", "strategy_fixed50", "hold_proxy")]
    pd.DataFrame(pu).to_csv(outdir / "proxy_units.csv", index=False)
    daily = []
    for (p, cost, name), nv in out["nav"].items():
        daily.append(pd.DataFrame({"book": p, "date": bks[p].cal, "cost_bps": cost, "run": name, "nav": nv}))
    pd.concat(daily).to_csv(outdir / "daily_nav.csv", index=False)
    np.savez_compressed(outdir / "draw_curves_20.8.npz", **{f"{p}|{k}": v for p, d in curves.items() for k, v in d.items()})
    np.savez_compressed(outdir / "draw_states.npz", **states_all)
    np.savez_compressed(outdir / "real_states.npz", **real_states)

    # audit
    c_ = common()
    v3_ok = all(v["pass"] for v in v3_res.values())
    v2_viol = sum(b["v2_label_after_decision"] + b["v2_mauc1_label_after_decision"] + b["v2_trade_not_after_decision"] for b in audit["books"].values())
    v2_cnt = sum(b["v2_decisions_checked"] * 2 + b["v2_trades_checked"] + 2 for b in audit["books"].values()) + out["v2_trades"]
    v2_ok = bool(v2_viol == 0 and v2_cnt > 0)
    audit["v2"] = {"checks": int(v2_cnt), "violations": int(v2_viol), "recorded_trades_after_their_decision": int(out["v2_trades"]), "sc100_rule7_checks": 2 * len(audit["books"]),
                   "sc100_signal_rows_read_from": str(c_["master"]["SC100"].index.min().date()), "pass": v2_ok}
    audit["v3"] = {"per_book_window": v3_res, "pass": bool(v3_ok), "rule_in_support": {k: v["rule_in_support"] for k, v in v3_res.items()}, "draws_per_type": int(n_draws),
                   "reportability": {"r3_window": live_gate, "gold_spells_with_an_out_week_full": {p: audit["books"][p]["gold"]["spells_with_an_out_week"] for p in books}}}
    audit["v4"] = {"pass": reg["pass"]}
    audit["v5"] = {"pass": v5["pass"]}
    audit["v6"] = v6
    lbr, lqr = c_["lbes"].pct_change(), c_["liq"].pct_change()
    jj = pd.concat([lbr, lqr], axis=1, keys=["lb", "lq"]).dropna().loc[str(T0.date()):str(END.date())]
    audit["data"] = {"approved_data_as_of": AD.as_of(), "window": [str(T0.date()), str(END.date())], "inputs": int(len(USED)), "non_approved_open_and_guards": selftest,
                     "index_rows_dropped_not_on_D26_calendar": c_["dropped_not_in_cal"], "index_files_through": {n: str(c_["px"][n].index.max().date()) for n in INDICES},
                     "master_rows_after_END_dropped": c_["master_rows_after_end"], "mauc1": {"rows_after_END_dropped": int(c_["gold_master_rows_after_end"])},
                     "goldbees": {"proxy_last": str(c_["gb"].index.max().date()), "goldbees_first": str(c_["g"].index.min().date()), "sessions_in_window_before_goldbees": int((c_["cal"] < GB_FIRST).sum()),
                                  "sessions_in_window_from_goldbees": int((c_["cal"] >= GB_FIRST).sum()), "sessions_without_mcx_range_(raw OHLC4 fill)": c_["no_range_sessions"],
                                  "sessions_without_own_gold_bar_(previous close used)": next(iter(bks.values())).gold_no_own_bar},
                     "cash": {"lbes_last": str(c_["lbes"].index.max().date()), "liq_last": str(c_["liq"].index.max().date()), "accrued_sessions": 0,
                              "lbes_vs_liquidcase_max_abs_daily_return_diff_in_window": float((jj["lb"] - jj["lq"]).abs().max()), "rows_compared": int(len(jj))}}
    audit["sleeve_trades_per_book_real_rule"] = {p: audit["books"][p]["gold"]["sleeve_trades_expected"] for p in books}
    audit["step1_spell_counts_reproduced"] = {"pass": bool(s1_ok), "detail": s1_detail, "file": STEP1.relative_to(AA).as_posix()}
    audit["run"] = {"name": a.run, "command": " ".join(sys.argv), "draws": n_draws, "books": list(books), "seconds": round(time.time() - t_start), "quick": a.quick,
                    "python": sys.version.split()[0], "numpy": np.__version__, "pandas": pd.__version__,
                    "seeds": "in-or-out N4.9 default_rng([12, 3, id]), N4.10 [12, 6, id]; gold N4.9-g [12, 11, 3, id], N4.10-g [12, 11, 6, id]; the same draw ids for every cost, window, cash variant and book; F5 pairs F1's and F3's draw of the same id"}
    audit["prereg_sha256"] = (T09 / "T09.md").read_text(encoding="utf-8").split("§1–§3 sha256:** `")[1].split("`")[0]
    ok = bool(v2_ok and v3_ok and reg["pass"] and v5["pass"] and v6["pass"] and selftest["pass"] and s1_ok)
    audit["gates"] = {"V2": v2_ok, "V3": bool(v3_ok), "V4": reg["pass"], "V5": v5["pass"], "V6": v6["pass"], "approved_data_selftest": selftest["pass"], "step1_counts": bool(s1_ok), "all": ok}
    (outdir / "audit.json").write_text(json.dumps(audit, indent=1, default=str), encoding="utf-8")

    print("runs written:", rows.groupby(["window", "cash", "kind"]).size().to_dict() if len(rows) < 80 else f"{len(rows)} stats rows")
    print("trades:", {f'{a}|{b}': c for (a, b), c in sorted(Counter((t['run'], t['kind']) for t in out['trades'] if t['cost_bps'] == PRIMARY and t['book'] == books[0]).items())})
    print("V2", audit["v2"])
    print("V3", {k: v["pass"] for k, v in v3_res.items()})
    print("V4", {"a": {k: v["pass"] for k, v in reg["a_one_index_book"].items()}, "b": {k: v["pass"] for k, v in reg["b_hold_proxy_vs_hand"].items()}, "c": reg["c_shared_code"]["pass"],
                 "d": {k: v["pass"] for k, v in reg["d_signals"].items()}, "e": reg["e_splice"]["pass"], "pass": reg["pass"]})
    print("V5", {"small_p": small["p"], "ie_equal": v5b, "mean_check": all(v["pass"] for v in v5c.values()), "pass": v5["pass"]})
    print("V6", {"trades": v6["trades_checked"], "worst": v6["worst"], "pass": v6["pass"]})
    for k, v in ct.items():
        if v["window"] == "full" and k.startswith(books[0]):
            print(f"  n_ways {k}: {v['n_ways']}")
    print(f"gates: {audit['gates']}")
    print(f"done in {time.time() - t_start:.0f}s -> {outdir}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
