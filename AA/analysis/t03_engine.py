# -*- coding: utf-8 -*-
"""T03 engine: the three-index switch on the four parents' own stocks, with a 50/50 GOLDBEES / cash sleeve.

Standalone: reads only raw files, imports nothing from other AA analysis modules. Pre-registration: tests/T03/T03.md
sections 1-3 (frozen; `python tests/T03/check_prereg.py`). Conventions below are the engine's readings of that text;
the ones the text leaves open are listed in READINGS and written to audit.json.

    python analysis/t03_engine.py [--run NAME] [--draws N] [--quick]      (from AA/)

Writes tests/T03/evidence/<run>/:
    inputs.csv         every input file with bytes and sha256
    decisions.csv      one row per weekly decision and book (signals, labels used, state, trade session)
    trades.csv         every trade of the strategy and the comparators
    positions.csv      units of every instrument after every strategy trade
    daily_nav.csv      daily NAV of the strategy (3 costs), the comparators and the published NAV
    stats.csv          statistics of every realisation that is not a null draw
    draws.csv          every null draw: N4.9 spell shuffle and circular shift (headline, R3 cash, R4 live window)
    draw_curves_20.8.npz  daily NAV (float32) of every headline draw at 20.8 bps
    draw_states_example.csv  real and shuffled in-or-out state of the first three N4.9 draws, per book (worked example)
    g_engine.csv       V4: always-in at 0 cost against the published NAV and the Step 1 rebuild
    audit.json         point-in-time counts, V3, readings

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
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
sys.dont_write_bytecode = True
AA = Path(__file__).resolve().parents[1]
HD = AA / "Historical Data"
HM = AA / "data" / "holdings_matrix"
T03 = AA / "tests" / "T03"
PARENTS = ["SCMO_0003", "SCMO_0007", "SCMO_0010", "SCMO_0029"]
END = pd.Timestamp("2026-08-21")
LIVE_START = pd.Timestamp("2021-11-01")
COSTS = (0.0, 20.8, 50.0)
PRIMARY = 20.8
N_DRAWS = 2000
SHIFT_MIN = 46            # weeks: the longest spell (AGENT.md N4.9, "beyond the longest spell")
DESPIKE_TOL = 0.005
LIQ_FROM = pd.Timestamp("2024-01-24")  # R3: LIQUIDCASE replaces LBES from this session
V4_END = pd.Timestamp("2026-10-22")    # the published NAVs' last date: the G0 scope

READINGS = {
    "E1": "calendar = D17's dates of the book from its first date to 2026-08-21; D18 prices on other dates are never read",
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
    "E10": "cash level: LBES as-of on sessions; after the file's last date (2026-08-09) it compounds at the trailing 90-session "
           "daily rate measured on the last 90 sessions up to 2026-08-07",
    "E11": "constant mix: stock share f = invested decision weeks / decision weeks, rebalanced at every decision date's next session "
           "(T0 included, as T03.md says) and at every basket change; initial stock holding = drifted basket scaled by f",
    "E12": "V3 is evaluated on the N4.9 draws; for the circular shift, invested weeks must be identical and the spell-count gap is reported",
    "E13": "R4 live window starts at the first D17 session on or after 2021-11-01 with its own spells, own draws (same seeds) and "
           "free initial position in the state decided then",
    "E14": "R3 cash = LBES to the session before 2024-01-24, then chained with the desk's LIQUIDCASE returns on sessions",
    "E15": "V4 runs the always-in book to 2026-10-22 (the G0 scope); every other run ends on 2026-08-21",
}


# ── raw inputs ────────────────────────────────────────────────────────────────
def sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


_RAW: dict = {}


def raw_parent(p: str) -> dict:
    """Stock prices (D18 with the price corrections), baskets (D19, skipped dropped), D17 dates and NAV."""
    if p in _RAW:
        return _RAW[p]
    wm = pd.read_csv(HM / f"{p}_holding_weight_matrix.csv", index_col=0)
    wm.index = pd.to_datetime(wm.index)
    src = pd.read_csv(HM / f"{p}_holding_weight_sources.csv")
    src["rebalance_date"] = pd.to_datetime(src["rebalance_date"])
    skipped = set(src.loc[src["source"] == "csv_only_skipped", "rebalance_date"])
    wm = wm[~wm.index.isin(skipped)]
    wm = wm.div(wm.sum(axis=1), axis=0)
    stocks = list(wm.columns)
    o = pd.read_csv(HM / f"{p}_ohlc.csv", parse_dates=["date"]).drop_duplicates(["date", "stock"])
    piv = {f: o.pivot(index="date", columns="stock", values=f).sort_index().reindex(columns=stocks)
           for f in ("open", "high", "low", "close")}
    cor = pd.read_csv(HM / "price_corrections.csv", parse_dates=["ex_date"])
    for r in cor.itertuples():
        if p in r.applies_to.split(";") and r.stock in stocks:
            for f in piv:
                piv[f].loc[piv[f].index < r.ex_date, r.stock] *= r.factor
    raw_close = piv["close"]
    close = raw_close.ffill()
    ohlc4 = ((piv["open"] + piv["high"] + piv["low"] + piv["close"]) / 4).fillna(raw_close)
    n = pd.read_csv(HD / "parent_nav_2026-10-22" / f"{p}.csv")
    pub = pd.Series(n["index"].values, index=pd.to_datetime(n["_id.date"], format="%Y/%m/%d")).sort_index()
    _RAW[p] = dict(W=wm, stocks=stocks, close=close, ohlc4=ohlc4, pub=pub, skipped=sorted(skipped))
    return _RAW[p]


_COMMON: dict = {}


def common() -> dict:
    """Gold (D09 + D12 de-spike), cash (D11), the three Master files (D03)."""
    if _COMMON:
        return _COMMON
    g = pd.read_parquet(AA / "analysis" / "cache" / "why_gold_ohlc_eikon.parquet").set_index("date").sort_index()
    g = g[~g.index.duplicated(keep="last")]
    m = pd.read_csv(AA / "analysis" / "evidence" / "final_strategy" / "mauc1" / "mauc1_daily_clean.csv", index_col=0, parse_dates=True)
    m.columns = [c.strip().lower() for c in m.columns]
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
    lb = pd.read_csv(HD / "LBES_Adjusted_Price_data_2026_08_10.csv")
    lb["date"] = pd.to_datetime(lb["date"], format="%d/%m/%y %H:%M")
    lb = lb.set_index("date")["price"].sort_index()
    lq = pd.read_csv(HD / "liquidEtfFinal_extended_2026-11-05.csv")
    lq["date"] = pd.to_datetime(lq["date"], format="mixed", dayfirst=True)
    lq = lq.set_index("date")["liquid_case"].sort_index()
    ms = {}
    for n in ("Nifty100", "MC100", "SC100"):
        d = pd.read_excel(HD / "frozen_2026-09-25" / "Master" / f"Master_{n}.xlsx", parse_dates=["Date"])
        s = d.dropna(subset=["SIGN"]).set_index("Date")["SIGN"].sort_index()
        ms[n] = s[~s.index.duplicated(keep="last")]
    _COMMON.update(gclose=g["close"], gfill=gfill, lbes=lb, liq=lq, master=ms)
    return _COMMON


def cash_levels(cal: pd.DatetimeIndex, kind: str = "lbes") -> tuple[np.ndarray, dict]:
    """E10, E14. Level on every session of cal."""
    c = common()
    lb = c["lbes"]
    union = cal.union(lb.index)
    lv = lb.reindex(union).ffill().reindex(cal)
    last_file = lb.index.max()
    info = {"file_last": str(last_file.date())}
    after = cal[cal > last_file]
    if len(after):
        sess_before = cal[cal <= last_file]
        a, b = lv.loc[sess_before[-1]], lv.loc[sess_before[-91]]
        r = (a / b) ** (1 / 90) - 1
        base = lb.loc[last_file]
        for k, d in enumerate(after, start=1):
            lv.loc[d] = base * (1 + r) ** k
        info.update(daily_rate=float(r), accrued_sessions=len(after))
    if kind == "liq":
        q = c["liq"]
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


# ── orchestration ─────────────────────────────────────────────────────────────
def window_label(live: bool) -> str:
    return "live" if live else "full"


def run_book(bk: Book, dec: pd.DataFrame, n_draws: int, costs, window: str, cash: str, headline: bool, out: dict, curves: dict, shifts_all: bool = True):
    idx = dec["decision_idx"].values
    s = dec["state"].values.astype(int)
    sig0 = spell_sig(s)
    n = len(s) - 1
    draws_states = [("N4.9", d, spell_shuffle(s, d)) for d in range(n_draws)]
    shifts = [("shift", k, np.roll(s, k)) for k in range(SHIFT_MIN, n - SHIFT_MIN + 1)] if shifts_all else []
    f = float(s.mean())
    for cost in costs:
        nav, tr, pos = simulate(bk, idx, s.astype(float), cost, record=True)
        st = stats(nav)
        out["rows"].append({"book": bk.parent, "window": window, "cash": cash, "cost_bps": cost, "kind": "strategy", **st,
                            "invested_weeks": int(s.sum()), "trades": len(tr), "cost_paid": sum(t["cost"] for t in tr)})
        if headline:
            out["nav"][(bk.parent, cost, "strategy")] = nav
            out["trades"] += [{"book": bk.parent, "cost_bps": cost, "run": "strategy", **t} for t in tr]
            out["positions"] += [{"book": bk.parent, "cost_bps": cost, "run": "strategy", **p} for p in pos]
        # comparators on the headline window only
        if headline:
            for name, e_arr, every in (("hold_parent", np.ones(len(s)), False), ("constant_mix", np.full(len(s), f), True),
                                       ("sleeve_only", np.zeros(len(s)), False)):
                nv, tr2, _ = simulate(bk, idx, e_arr, cost, every=every, record=True)
                out["rows"].append({"book": bk.parent, "window": window, "cash": cash, "cost_bps": cost, "kind": name, **stats(nv),
                                    "invested_weeks": float(e_arr.sum()), "trades": len(tr2), "cost_paid": sum(t["cost"] for t in tr2)})
                out["nav"][(bk.parent, cost, name)] = nv
                out["trades"] += [{"book": bk.parent, "cost_bps": cost, "run": name, **t} for t in tr2]
        for kind, key, st_arr in draws_states + shifts:
            nv = simulate(bk, idx, st_arr.astype(float), cost)
            ds = stats(nv)
            rs = spells(st_arr)
            out["draws"].append({"book": bk.parent, "window": window, "cash": cash, "cost_bps": cost, "draw_type": kind,
                                 "draw_id": key, **ds, "invested_weeks": int(st_arr.sum()), "n_in_spells": sum(1 for v, _ in rs if v == 1),
                                 "n_out_spells": sum(1 for v, _ in rs if v == 0), "spell_sig": spell_sig(st_arr), "strategy_sig": sig0})
            if headline and cost == PRIMARY:
                curves.setdefault(bk.parent, {})[f"{kind}_{key}"] = nv.astype(np.float32)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="headline")
    ap.add_argument("--draws", type=int, default=N_DRAWS)
    ap.add_argument("--quick", action="store_true", help="two books' worth of work: 1 book, 20 draws, for a smoke test")
    a = ap.parse_args()
    outdir = T03 / "evidence" / a.run
    outdir.mkdir(parents=True, exist_ok=True)
    t_start = time.time()
    books = PARENTS[:1] if a.quick else PARENTS
    n_draws = 20 if a.quick else a.draws
    out = {"rows": [], "draws": [], "nav": {}, "trades": [], "positions": []}
    curves: dict = {}
    dec_all, audit = [], {"readings": READINGS, "books": {}}

    # inputs
    files = [HD / "frozen_2026-09-25" / "Master" / f"Master_{n}.xlsx" for n in ("Nifty100", "MC100", "SC100")]
    files += [AA / "analysis" / "cache" / "why_gold_ohlc_eikon.parquet", AA / "analysis" / "evidence" / "final_strategy" / "mauc1" / "mauc1_daily_clean.csv",
              HD / "LBES_Adjusted_Price_data_2026_08_10.csv", HD / "liquidEtfFinal_extended_2026-11-05.csv", HM / "price_corrections.csv"]
    for p in PARENTS:
        files += [HM / f"{p}_{x}.csv" for x in ("ohlc", "holding_weight_matrix", "holding_weight_sources", "columns")] + [HD / "parent_nav_2026-10-22" / f"{p}.csv"]
    pd.DataFrame([{"file": str(f.relative_to(AA)), "bytes": f.stat().st_size, "sha256": sha(f)} for f in files]).to_csv(outdir / "inputs.csv", index=False)

    ex_states = []
    for p in books:
        t1 = time.time()
        bk = Book(p)
        dec = bk.decisions()
        dec_all.append(dec)
        s_real = dec["state"].values.astype(int)
        for did in range(3):   # the first three N4.9 draws' states, for the worked example (section 4.0a)
            sh = spell_shuffle(s_real, did)
            ex_states += [{"book": p, "draw_id": did, "j": j, "decision_date": dec["decision_date"].iloc[j], "real_state": int(s_real[j]),
                           "draw_state": int(sh[j])} for j in range(len(s_real))]
        # V2: point-in-time counts
        lab_ok = int((pd.to_datetime(dec["latest_label"]) <= pd.to_datetime(dec["decision_date"])).sum())
        trade_idx = dec["decision_idx"].values + 1
        traded_rows = int((trade_idx < bk.T).sum())
        s = dec["state"].values
        audit["books"][p] = {"t0": str(bk.t0.date()), "sessions": bk.T, "decisions": len(dec), "invested_weeks": int(s.sum()),
                             "in_spells": sum(1 for v, _ in spells(s) if v == 1), "out_spells": sum(1 for v, _ in spells(s) if v == 0),
                             "round_trips": min(sum(1 for v, _ in spells(s) if v == 1), sum(1 for v, _ in spells(s) if v == 0)),
                             "v2_decisions_checked": len(dec), "v2_label_after_decision": len(dec) - lab_ok,
                             "v2_trades_checked": traded_rows, "v2_trade_not_after_decision": 0,
                             "stale_label_weeks(age>=5d, excluding T0)": int((dec["label_age_days"].values[1:] >= 5).sum()), "initial_basket_switch_session": bk.initial_basket_switch_session,
                             "cash": bk.cash_info, "skipped_baskets_dropped": [str(x.date()) for x in raw_parent(p)["skipped"]]}
        bk.nobar_trades = 0
        run_book(bk, dec, n_draws, COSTS, "full", "lbes", True, out, curves)
        audit["books"][p]["stock_trades_priced_by_last_close_no_bar_that_session(all runs incl. draws)"] = bk.nobar_trades
        # R3: LIQUIDCASE cash, primary cost only, N4.9 + shift
        bk3 = Book(p, cash="liq")
        run_book(bk3, dec, n_draws, (PRIMARY,), "full", "liquidcase", False, out, curves)
        # R4: live window
        bk4 = Book(p, start=LIVE_START)
        dec4 = bk4.decisions()
        s4 = dec4["state"].values
        rt = min(sum(1 for v, _ in spells(s4) if v == 1), sum(1 for v, _ in spells(s4) if v == 0))
        audit["books"][p]["live_window"] = {"t0": str(bk4.t0.date()), "decisions": len(dec4), "round_trips": rt, "reportable": bool(rt >= 4)}
        if rt >= 4:
            run_book(bk4, dec4, n_draws, (PRIMARY,), "live", "lbes", False, out, curves, shifts_all=False)
        print(f"{p}: {time.time() - t1:.0f}s  decisions {len(dec)}  in-spells {audit['books'][p]['in_spells']}  round trips {audit['books'][p]['round_trips']}", flush=True)

    # V4: always-in at 0 cost against the published NAV (G0) and the Step 1 rebuild
    g4 = []
    rb = pd.read_csv(AA / "data" / "parent_rebuild_hm" / "daily.csv", parse_dates=["date"])
    rb = rb[rb["variant"] == "listed_weights_skip_dropped_corrected"]
    for p in books:
        bk = Book(p, end=V4_END)
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
        r = rb[rb["parent"] == p].set_index("date")["model"].reindex(c.index).dropna()
        rel = float(((c.m.reindex(r.index) / r) - 1).abs().max())
        g4.append({"book": p, "cagr_gap_pp_yr": gap, "overall": "PASS" if abs(gap) <= 0.25 else "FAIL", "worst_year": wy,
                   "worst_year_gap_pp": worst, "yearly": "PASS" if abs(worst) <= 0.5 else "FAIL",
                   "max_rel_diff_vs_step1_rebuild": rel, "rebuild_dates_compared": len(r)})
    pd.DataFrame(g4).to_csv(outdir / "g_engine.csv", index=False)

    # write
    pd.concat(dec_all).to_csv(outdir / "decisions.csv", index=False)
    pd.DataFrame(ex_states).to_csv(outdir / "draw_states_example.csv", index=False)
    rows = pd.DataFrame(out["rows"])
    rows.to_csv(outdir / "stats.csv", index=False)
    dr = pd.DataFrame(out["draws"])
    dr.to_csv(outdir / "draws.csv", index=False)
    pd.DataFrame(out["trades"]).to_csv(outdir / "trades.csv", index=False)
    pd.DataFrame(out["positions"]).to_csv(outdir / "positions.csv", index=False)
    daily = []
    for (p, cost, name), nv in out["nav"].items():
        bk = Book(p)
        daily.append(pd.DataFrame({"book": p, "date": bk.cal, "cost_bps": cost, "run": name, "nav": nv}))
    for p in books:
        bk = Book(p)
        pub = bk.pub / bk.pub[0]
        daily.append(pd.DataFrame({"book": p, "date": bk.cal, "cost_bps": np.nan, "run": "published_D17", "nav": pub}))
    pd.concat(daily).to_csv(outdir / "daily_nav.csv", index=False)
    np.savez_compressed(outdir / "draw_curves_20.8.npz", **{f"{p}|{k}": v for p, d in curves.items() for k, v in d.items()})

    # V3 and audit
    h = dr[(dr["window"] == "full") & (dr["cash"] == "lbes")]
    n49 = dr[dr["draw_type"] == "N4.9"]
    sh = dr[dr["draw_type"] == "shift"]
    first_inv = {(r["book"], r["window"], r["cash"]): r["invested_weeks"] for r in out["rows"] if r["kind"] == "strategy"}
    mism = lambda d: int(sum((g["invested_weeks"] != first_inv[k]).sum() for k, g in d.groupby(["book", "window", "cash"])))
    audit["v3"] = {"n49_draws": int(len(n49)), "n49_sig_mismatch": int((n49["spell_sig"] != n49["strategy_sig"]).sum()),
                   "n49_invested_weeks_mismatch": mism(n49), "shift_draws": int(len(sh)),
                   "shift_invested_weeks_mismatch": mism(sh),
                   "shift_spell_count_gap_max": int((sh[["n_in_spells", "n_out_spells"]].sum(axis=1) - 18).abs().max()) if len(sh) else None}
    audit["v4"] = g4
    audit["run"] = {"name": a.run, "draws": n_draws, "seconds": round(time.time() - t_start), "quick": a.quick,
                    "seed": "numpy default_rng([3, draw_id]); the same draw ids for every book, cost, window and cash variant",
                    "shift_range_weeks": [SHIFT_MIN, "n - 46"]}
    audit["prereg_sha256"] = (T03 / "T03.md").read_text(encoding="utf-8").split("§1–§3 sha256:** `")[1].split("`")[0]
    (outdir / "audit.json").write_text(json.dumps(audit, indent=1, default=str), encoding="utf-8")
    print(rows[rows["kind"] == "strategy"][["book", "cost_bps", "cagr", "max_dd", "end_nav", "trades"]].round(4).to_string(index=False))
    print(pd.DataFrame(g4).round(3).to_string(index=False))
    print("V3", audit["v3"])
    print(f"done in {time.time() - t_start:.0f}s -> {outdir}")


if __name__ == "__main__":
    main()
