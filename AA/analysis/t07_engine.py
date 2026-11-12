# -*- coding: utf-8 -*-
"""T07 engine: segment holding (each stock follows the signal of its own market-cap band) against a size-matched random
exclusion (N4.6) and a persistent label permutation (N4.8), on the latest approved data.

A FORK of analysis/t06_engine.py (copied, not imported): the data layer (calendar, prices, baskets, GOLDBEES fill, cash level),
`trade()`'s arithmetic and `stats()` are T06's, so that the whole-book mode (the three bands tied) reproduces T06's NAV. What is
new: per-stock targets, the event rule of T07.md section 3 step 4, tags through the reviewed analysis/tag_lookup.py, the two nulls,
the controls V6 (negative) and V7 (oracle), the tag-error draws R5. Pre-registration: tests/T07/T07.md sections 1-3 (frozen;
`python tests/T07/check_prereg.py`), evidence contract: tests/T07/logs/evidence_contract.md. Every data file is opened through
`approved_data.require()` (an APPROVED row of data/APPROVED_DATA.md) and its sha256 prefix is checked. Readings of the places the
frozen text is silent are in READINGS and are written to audit.json.

    python -I analysis/t07_engine.py --run NAME [--draws N] [--quick] [--controls] [--jobs J]       (from AA/)
    python -I analysis/t07_engine.py --rerun --book B --type N4.6|N4.8 --id N --cost C --window full|live [--cash lbes|liq] --out f.json

Writes tests/T07/evidence/<run>/ (see the contract). Exit code 0 only if every gate that ran passed.

Trade rule (one function, `sim`): at an event session t, with fill prices (stocks OHLC4, GOLDBEES de-spiked OHLC4, cash at its
level), V = value of all holdings at those prices. Targets: kept stock V*w_i (w_i its listed weight), GOLDBEES and cash V*s/2 each,
s = (listed weight dropped)/(sum of listed weights). traded = sum |target - held| over every line; cost = traded*cost_bps/2/1e4;
every target is then scaled by (V-cost)/V. T0 is the free initial position.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import approved_data as AD  # noqa: E402
from approved_data import NotApprovedError  # noqa: E402
from tag_lookup import TagLookup  # noqa: E402

AA = Path(__file__).resolve().parents[1]
HD = AA / "Historical Data"
HM = AA / "data" / "holdings_matrix"
T06E = AA / "tests" / "T06" / "evidence" / "headline"      # read-only reference for V4
T07 = AA / "tests" / "T07"
PARENTS = ["SCMO_0003", "SCMO_0007", "SCMO_0010", "SCMO_0029"]
AA_BOOK = {"SCMO_0003": "SCMO_0042", "SCMO_0007": "SCMO_0043", "SCMO_0010": "SCMO_0044", "SCMO_0029": "SCMO_0045"}
LIVE_START = pd.Timestamp("2021-11-01")
END = pd.Timestamp("2026-10-30")            # T07.md header: the last date of the signal files (D03); asserted against the files
COSTS = (0.0, 20.8, 50.0)
PRIMARY = 20.8
N_DRAWS = 2000
N_R5 = 500
R5_RATE = 0.0793
V6_SHIFTS, V6_DRAWS = 100, 200


def v6_xmax(K: int, p: float = 0.10, alpha: float = 0.05 / 4) -> int:
    """AMENDMENT 2026-11-12 (T07.md 'Amendments before the run'): the largest count X of information-free signals reaching the 90th
    percentile that still passes V6 for K shifts, i.e. the largest X with P(Binomial(K, p) >= X) >= alpha (one-sided, alpha = 0.05 / 4 books).
    K = 100: 17 (a book fails at 18 or more). Replaces the frozen two-sided band 10% +- 2 sqrt(0.1 x 0.9 / K) = [4%, 16%]."""
    tail = 0.0
    for X in range(K, -1, -1):
        tail += math.comb(K, X) * p ** X * (1 - p) ** (K - X)
        if tail >= alpha:
            return X
    return K
DESPIKE_TOL = 0.005
LIQ_FROM = pd.Timestamp("2024-01-24")        # R3: LIQUIDCASE replaces LBES from this session (as T06's R2)
T06_NAV_END = pd.Timestamp("2026-10-22")     # V4: T06's NAVs are compared up to here
LBES_VERBATIM_LAST = pd.Timestamp("2026-08-09")
G0_OVERALL, G0_YEARLY = 0.25, 0.5            # pp / yr
REL_TOL_NAV = 1e-12
SUBSET_TOL = 1e-12                           # tolerance on |sum - D| <= tau (floating point; ties count as allowed)
BANDS = ["Large", "Mid", "Small and below"]
BAND_IDX = {b: i for i, b in enumerate(BANDS)}
SIGNALS = ["Nifty100", "MC100", "SC100"]
RANK_SOURCES = ("rank", "nonmember_rank")
TAG_FILES = dict(rank=HD / "extended_2026-11-12" / "tags" / "mcap_rank_panel.csv",
                 memb=HD / "extended_2026-11-12" / "tags" / "membership_panel.csv",
                 symb=HD / "extended_2026-11-12" / "symbology" / "symbology_changes.csv")
RAW_TAG_FILES = [HD / "extended_2026-11-12" / "mcap_universe" / "mcap_universe_ordinary.csv",
                 HD / "extended_2026-11-12" / "membership" / "index_constituents_monthly.csv"]

READINGS = {
    "E1": "calendar = D17's dates (the extended published NAV files, Historical Data/extended_2026-11-06/published_nav) of the book from its first date to END = 2026-10-30; "
          "END is the frozen text's date and is asserted equal to the earliest last date of the three Master files and covered by every other role; D18 prices on other dates are never read",
    "E2": "decision dates = T0 and the last D17 session of every later ISO week; the decision at the last session is made but not traded (it has no later session)",
    "E3": "state of a decision = the triple of the latest Master SIGN row of each index dated <= the decision date (BUY/SELL); T06's 'state' (1 iff all three BUY) is kept in decisions.csv",
    "E4": "initial position at T0 (free): the basket in force at T0, as drifted since its availableDate (OHLC4 of the first D18 session on or after it) and scaled to NAV 1 at T0's close; "
          "the stocks dropped at T0 (tags and state read as of T0 itself) are kept at T0's closes in value and converted half to GOLDBEES, half to cash units at T0's closes. "
          "This is T06's initial position when all stocks are kept (IN) or all dropped (OUT)",
    "E5": "WEIGHTS ARE RENORMALISED TO 1, AS T06 DOES (T06 E5: wm.div(wm.sum(axis=1))). T07.md step 6 says listed weights are 'not renormalised' and that targets 'can sum to V x (1 +- 0.0005), as in T06'; "
          "that does not describe T06 (its targets sum to V) and cannot be combined with gate V4 (whole-book mode equals T06's NAV to 1e-12). V4 wins: every stock's listed weight is the matrix weight "
          "divided by its basket's row sum (raw weight in event_stocks.csv listed_weight_raw; sum_weights is therefore 1.0 and s = D). tau = half the smallest renormalised weight. AFFECTS STEPS 3 AND 4",
    "E6": "a basket takes effect on the first calendar session on or after its availableDate; baskets flagged csv_only_skipped are dropped (T06)",
    "E7": "stock fill = OHLC4 of the Eikon bar (close if any of open/high/low is blank; last close if the stock has no bar that session), Polyplex correction applied (T06)",
    "E8": "cash level: the extended LBES (D11) as-of on sessions; asserted to cover the window (0 accrued sessions). R3 'liq': LBES to the session before 2024-01-24, then chained with LIQUIDCASE returns (T06 E14)",
    "E9": "GOLDBEES fill: T06's de-spike (OHLC4 of open/high/low clipped to MCX gold's range that day + 0.5%) up to the MCX file's last date (2026-09-28), raw OHLC4 after it",
    "EV1": "event rule (step 4): candidates are the trade sessions of decisions j>=1 (decision_idx+1, if the session exists) and the sessions of non-skipped basket changes. At a decision candidate the set the CURRENT tags (those read at the last event) "
           "would drop under that decision's state is compared with the set the book currently drops; a difference makes a signal event. A basket candidate without a signal event is an event unless the book holds no stock (every held stock "
           "currently dropped); then nothing is traded. Two events on one session are one event ('signal+basket'). At an event the state is the triple of the latest decision made before the session (decision_idx < session), "
           "the tags of every held stock are read as of the previous session (info date). The T0 event reads tags and state at T0 itself (disclosed exception to 'tags before the trade session', counted in audit.json v2)",
    "EV2": "SKIPPED BASKET EVENT (no stock held): nothing is traded and no event is written, but the basket in force changes. Reading A, the smallest that keeps the next signal test defined: the tags of the new basket's stocks are read as of the "
           "previous session (a tag read without a trade) and become the 'current tags'; the book 'currently drops' all of them. Counted in audit.json (skipped_basket_events). AFFECTS STEP 3",
    "EV3": "the whole-book switch (bands tied) is the same event code with every stock following 'IN iff all three BUY'; its events equal T06's (a trade only when the stock share changes, basket events only while IN). "
           "hold the parent = mode 'parent' (nothing dropped, T0 and basket events only); the 100% sleeve = T0 with everything dropped",
    "N1": "N4.6: held stocks of an event in increasing ISIN string order (bit i of a subset mask = stock i, bit 0 the least significant); allowed set = masks with |sum w - D| <= tau (+1e-12, floating point; exact ties are allowed), listed in increasing mask order; "
          "u = rng.random() from default_rng([7, draw_id, book_no]), one per event in event order (T0 event first), index = min(floor(u*count), count-1); the same draw ids at every cost, cash and window",
    "N1b": "allowed sets are homogeneous in the weights (|sum w - D| <= tau scales with w), so the renormalisation of E5 does not change any set; exact ties |sum - D| = tau exist (SCMO_0010 full window: 35 such subsets at events with round weights) and are allowed, "
           "decided with the 1e-12 tolerance above and counted per event (count_table.json boundary_cases, audit tau_boundary_cases). ISIN order = Python string order of the ISIN codes (ASCII)",
    "N2": "N4.8: one score per ISIN of the realisation's universe (the sorted ISINs of its event_stocks rows, so the live window has its own) from default_rng([8, draw_id, book_no]).random(n); at an event the held stocks are ranked by "
          "score DESCENDING, the first n_L get label Large, the next n_M Mid, the rest Small and below (n_* = the rule's counts at that event); dropped iff the label's band signal is SELL under the event's state",
    "R5": "R5 tag error: default_rng([5, draw_id, book_no]); at every tag read (every event and every skipped-basket read) each held stock whose tag source is 'rank' or 'nonmember_rank' consumes two uniforms: the first < 0.0793 flips its band, "
          "the second picks one of the other two bands (in the order Large, Mid, Small, first if < 0.5). Membership and unranked tags are not perturbed. The events are rebuilt under the perturbed tags (the event rule reads them). "
          "Reported: the draw's after-cost CAGR (20.8 bps, full window) minus the whole-book switch's",
    "V6": "V6: the weekly joint state matrix (decisions x 3) is rolled by k decisions, k drawn without replacement (V6_SHIFTS of them) from the DISTINCT circular shifts 26 <= k <= n-26 (k and k-n are the same shift, so negative k adds none); "
          "the drawing generator is default_rng([9, 100000, book_no]); shift number i (0-based) uses default_rng([9, i, book_no]) for its null: one stream, draw d takes the next n_events uniforms. Full window, LBES, 20.8 bps, 200 draws; "
          "percentile of the shifted rule's CAGR against its own N4.6 draws",
    "V7": "V7 oracle: at each event pick, from that event's allowed N4.6 set, the subset with the lowest sum of listed weight x log(end price / start price), start = OHLC4 at the trade session (T0: the close), end = OHLC4 at the next event's trade "
          "session (the last event: the close of the last session); ties to the lowest mask. Run at 20.8 bps, full window; percentile of its CAGR against the headline N4.6 draws at 20.8",
    "S1": "constant mix: f = the average over all sessions of (value of stocks / NAV) of the rule's path at the SAME cost (so f depends on the cost); stocks f x w_i, half of (1-f) in GOLDBEES and half in cash, rebalanced at the rule's events "
          "(T0 initial position free, then every event of the rule, with the same cost)",
    "S2": "invested_weeks = sum over the weekly decisions of the share of listed weight the current tags keep under that decision's state (T06's sum of states when the bands are tied); constant mix J*f; sleeve100 0; parent J",
    "S3": "published_parent rows: the published NAV rebased to 1.0, written once per (window, cash, cost) block with identical values (so a filter on cost finds it); R6: kind published_aa (SCMO_0042-45, D15) on the live window, column aa_scid, cost_bps empty",
    "S4": "stats.events = the number of events including T0; trades = the number of trades after T0 (every event after T0 trades)",
    "V2": "V2 counts: decisions (Master label date <= decision date), tags (snapshot <= info date), events (info date < trade session and latest decision < trade session). The T0 event reads as of T0 itself and is counted separately, not as a violation",
    "V4": "V4 compares the engine's whole-book, parent and 100%-sleeve NAVs with T06's strategy, hold_parent and sleeve_only on every shared session to 2026-10-22 at 0, 20.8 and 50 bps (relative difference < 1e-12), the decisions on every shared date, "
          "and always-in at 0 cost against the published NAV (G0) over the whole window. The constant mix is defined differently in T07 and is not compared",
    "G1": "reportability: a (book, window) needs >= 5 separate disagreement stretches (runs of decisions where the three SIGN are neither all BUY nor all SELL) and >= 6 events with 0 < n_dropped < n_held; written to audit.json and count_table.json. "
          "Draws are run for every realisation whether reportable or not",
    "G3": "the oracle (V7), V6 and R5 are run per book inside its worker; V6 does not depend on --draws (100 shifts x 200 draws); a run without --controls (--quick) reports V6 and V7 as not run and exits 0 if V2-V5 pass",
    "G2": "events.csv, event_stocks.csv, count_table.json are written for the rule at the full and live windows; costs do not change events",
}

# ── approved raw inputs ───────────────────────────────────────────────────────
USED: dict[str, dict] = {}
CHECK_SHA = True


def ap(path) -> Path:
    """The only way the engine opens a data file: APPROVED row required, sha256 prefix checked once per file (main process)."""
    p = AD.require(path)
    rel = p.relative_to(AA).as_posix()
    if rel not in USED:
        USED[rel] = AD.check_sha(p) if CHECK_SHA else {"file": rel, "approved_row": "APPROVED " + AD.row_for(p)["id"], "id": AD.row_for(p)["id"],
                                                         "through": AD.row_for(p)["through"], "bytes": p.stat().st_size, "sha256": ""}
    return p


def d17_path(p: str) -> Path:
    return HD / "extended_2026-11-06" / "published_nav" / f"{p}.csv"


_RAW: dict = {}


def raw_parent(p: str) -> dict:
    """Stock prices (D18 with the price corrections), baskets (D19, skipped dropped, renormalised as T06), ISINs (D19 columns), D17 dates and NAV."""
    if p in _RAW:
        return _RAW[p]
    wm = pd.read_csv(ap(HM / f"{p}_holding_weight_matrix.csv"), index_col=0)
    wm.index = pd.to_datetime(wm.index)
    src = pd.read_csv(ap(HM / f"{p}_holding_weight_sources.csv"))
    src["rebalance_date"] = pd.to_datetime(src["rebalance_date"])
    skipped = set(src.loc[src["source"] == "csv_only_skipped", "rebalance_date"])
    wm = wm[~wm.index.isin(skipped)]
    wraw = wm.copy()
    wm = wm.div(wm.sum(axis=1), axis=0)
    stocks = list(wm.columns)
    cm = pd.read_csv(ap(HM / f"{p}_columns.csv")).set_index("stock")["ISIN"]
    assert set(stocks) <= set(cm.index) and cm.loc[stocks].notna().all() and not cm.loc[stocks].duplicated().any(), f"{p}: ISIN map incomplete"
    isin = np.array([cm.loc[s] for s in stocks], dtype=object)
    o = pd.read_csv(ap(HM / f"{p}_ohlc.csv"), parse_dates=["date"]).drop_duplicates(["date", "stock"])
    piv = {f: o.pivot(index="date", columns="stock", values=f).sort_index().reindex(columns=stocks) for f in ("open", "high", "low", "close")}
    cor = pd.read_csv(ap(HM / "price_corrections.csv"), parse_dates=["ex_date"])
    for r in cor.itertuples():
        if p in r.applies_to.split(";") and r.stock in stocks:
            for f in piv:
                piv[f].loc[piv[f].index < r.ex_date, r.stock] *= r.factor
    raw_close = piv["close"]
    close = raw_close.ffill()
    ohlc4 = ((piv["open"] + piv["high"] + piv["low"] + piv["close"]) / 4).fillna(raw_close)
    n = pd.read_csv(ap(d17_path(p)))
    pub = pd.Series(n["index"].values, index=pd.to_datetime(n["_id.date"], format="%Y/%m/%d")).sort_index()
    assert pub.index.max() >= END and o["date"].max() >= END, f"{p}: D17 or D18 ends before END"
    _RAW[p] = dict(W=wm, Wraw=wraw, stocks=stocks, isin=isin, close=close, ohlc4=ohlc4, pub=pub, skipped=sorted(skipped))
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
    after = g.index > mcx_last
    gfill = gfill.where(~after, raw4)
    lb = pd.read_csv(ap(HD / "LBES_Adjusted_Price_data_extended_2026-11-05.csv"))
    lb["date"] = pd.to_datetime(lb["date"], format="%d/%m/%y %H:%M")
    lb = lb.set_index("date")["price"].sort_index()
    lq = pd.read_csv(ap(HD / "liquidEtfFinal_extended_2026-11-05.csv"))
    lq["date"] = pd.to_datetime(lq["date"], format="mixed", dayfirst=True)
    lq = lq.set_index("date")["liquid_case"].sort_index()
    ms = {}
    for n in SIGNALS:
        d = pd.read_excel(ap(HD / "extended_2026-10-30" / "Master" / f"Master_{n}.xlsx"), parse_dates=["Date"])
        s = d.dropna(subset=["SIGN"]).set_index("Date")["SIGN"].sort_index()
        s = s[~s.index.duplicated(keep="last")]
        assert set(s.unique()) <= {"BUY", "SELL"}, f"Master_{n}: unexpected SIGN values {set(s.unique())}"
        ms[n] = s
    assert min(s.index.max() for s in ms.values()) == END, f"the Master files end {[str(s.index.max().date()) for s in ms.values()]}, the frozen window end is {END.date()}"
    assert g.index.max() >= END and lb.index.max() >= END and lq.index.max() >= END
    _COMMON.update(gclose=g["close"], gfill=gfill, lbes=lb, liq=lq, master=ms, mcx_last=mcx_last,
                   gold_data_last=g.index.max(), gold_raw_sessions_in_data=[str(d.date()) for d in g.index[after]])
    return _COMMON


def cash_levels(cal: pd.DatetimeIndex, kind: str = "lbes") -> tuple[np.ndarray, dict]:
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
    lb = common()["lbes"]
    last_v = LBES_VERBATIM_LAST
    app = lb.index[lb.index > last_v]
    pre = lb.index[lb.index < last_v]
    first_app, fri = app[0], pre[-1]
    sunday_accrual = float(lb.loc[last_v] / lb.loc[fri] - 1)
    return {"last_verbatim_row": str(last_v.date()), "last_session_before_it": str(fri.date()), "first_appended_row": str(first_app.date()),
            "appended_rows": int(len(app)), "weekend_accrual_counted_twice_(Sunday_level/last_session_level-1)": sunday_accrual,
            "within_claimed_bound_0.0002": bool(abs(sunday_accrual) <= 0.0002),
            "note": "level[first appended] chains from the Sunday 2026-08-09 level, so the weekend accrual is earned again; the extension runs about 0.5 pp/yr rich against LIQUIDBEES (F-AA-D13); disclosed, not corrected"}


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
        self.isin = r["isin"]
        C = r["close"].reindex(cal)
        P = r["ohlc4"].reindex(cal)
        self.nobar = P.isna().values
        P = P.fillna(C)
        self.C = np.nan_to_num(C.values.astype(float), nan=0.0)
        self.P = np.nan_to_num(P.values.astype(float), nan=0.0)
        self.pub = r["pub"].reindex(cal).values.astype(float)
        union = cal.union(c["gclose"].index)
        gc = c["gclose"].reindex(union).ffill().reindex(cal)
        gf = c["gfill"].reindex(cal).fillna(gc)
        self.g, self.gf = gc.values.astype(float), gf.values.astype(float)
        self.gold_raw = np.asarray(cal > c["mcx_last"])
        self.L, self.cash_info = cash_levels(cal, cash)
        W = r["W"]
        self.W = W.values.astype(float)
        self.Wraw = r["Wraw"].values.astype(float)
        self.eff = W.index
        bidx = np.searchsorted(cal.values, self.eff.values)
        self.bidx = bidx
        self.b0 = int(np.flatnonzero(bidx <= 0)[-1])
        self.basket_events = {int(i) for i in bidx if 0 < i < self.T}
        self.basket_at = np.array([int(np.flatnonzero(bidx <= t)[-1]) if (bidx <= t).any() else 0 for t in range(self.T)])
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
        self._held: dict = {}

    def held(self, b: int) -> np.ndarray:
        """Columns with listed weight > 0 in basket b, in increasing ISIN string order (the order of the subset bits)."""
        if b not in self._held:
            cols = np.flatnonzero(self.W[b] > 0)
            self._held[b] = cols[np.argsort(self.isin[cols], kind="stable")]
        return self._held[b]

    def decisions(self) -> tuple[pd.DataFrame, np.ndarray, np.ndarray]:
        """T06's decision table plus the state matrix S (decisions x 3, 1 = BUY, columns Nifty100, MC100, SC100) and decision_idx."""
        cal = self.cal
        iso = cal.isocalendar()
        last = pd.Series(np.arange(self.T), index=cal).groupby([iso.year.values, iso.week.values]).max().values
        idx = np.array([0] + [int(i) for i in sorted(last) if i > 0])
        ms = common()["master"]
        rows, S = [], []
        for j, i in enumerate(idx):
            d = cal[i]
            lab, state, trip = {}, 1, []
            for n, s in ms.items():
                k = s.index.searchsorted(d, side="right") - 1
                lab[n] = (s.index[k], s.iloc[k])
                state &= int(s.iloc[k] == "BUY")
                trip.append(int(s.iloc[k] == "BUY"))
            S.append(trip)
            ld = max(v[0] for v in lab.values())
            rows.append({"book": self.parent, "j": j, "decision_date": d.date(), "decision_idx": int(i),
                         "trade_date": (cal[i + 1].date() if i + 1 < self.T else None),
                         **{f"sign_{n}": v[1] for n, v in lab.items()}, **{f"label_{n}": v[0].date() for n, v in lab.items()},
                         "latest_label": ld.date(), "label_age_days": (d - min(v[0] for v in lab.values())).days,
                         "all_three_buy": bool(state), "state": int(state),
                         "disagree": bool(0 < sum(trip) < 3), "pattern": "".join("B" if x else "S" for x in trip)})
        return pd.DataFrame(rows), np.array(S, dtype=np.int8), idx


# ── tags ──────────────────────────────────────────────────────────────────────
class Tagger:
    """Tags through the reviewed tag_lookup.TagLookup (never our own ranking). Cached by (isin, date)."""

    def __init__(self):
        self.tl = TagLookup.from_files(ap(TAG_FILES["rank"]), ap(TAG_FILES["memb"]), ap(TAG_FILES["symb"]))
        self.cache: dict = {}

    def get(self, isin: str, d: pd.Timestamp) -> dict:
        k = (isin, d)
        r = self.cache.get(k)
        if r is None:
            r = self.tl.tag(isin, d)
            self.cache[k] = r
        return r


class Perturb:
    """R5: the tag-error draw (READINGS R5)."""

    def __init__(self, draw_id: int, book_no: int, rate: float = R5_RATE):
        self.rng = np.random.default_rng([5, draw_id, book_no])
        self.rate = rate
        self.flipped = 0
        self.rank_reads = 0

    def apply(self, bands: np.ndarray, src: list[str]) -> np.ndarray:
        out = bands.copy()
        for i, s in enumerate(src):
            if s in RANK_SOURCES:
                u1, u2 = self.rng.random(), self.rng.random()
                self.rank_reads += 1
                if u1 < self.rate:
                    others = [b for b in (0, 1, 2) if b != int(out[i])]
                    out[i] = others[0 if u2 < 0.5 else 1]
                    self.flipped += 1
        return out


# ── events (T07.md section 3 step 4-6) ────────────────────────────────────────
def dropped_of(mode: str, bands: np.ndarray, st: np.ndarray) -> np.ndarray:
    if mode == "seg":
        return st[bands] == 0
    if mode == "whole":
        return np.full(len(bands), not bool(st.all()))
    return np.zeros(len(bands), dtype=bool)


class Events:
    def __init__(self, evs: list, skipped: list, kept_share: np.ndarray, v2: dict, mode: str):
        self.evs, self.skipped, self.kept_share, self.v2, self.mode = evs, skipped, kept_share, v2, mode
        self.n = len(evs)
        self.off = np.concatenate([[0], np.cumsum([len(e["cols"]) for e in evs])]).astype(int)
        self.R = int(self.off[-1])
        self.dflat = np.concatenate([e["drop"] for e in evs]).astype(np.uint8)
        self.w_flat = np.concatenate([e["w"] for e in evs])
        self.universe = None
        self.allowed_done = False

    def counts(self) -> dict:
        kinds = [e["kind"] for e in self.evs]
        return {"events": self.n, **{k: kinds.count(k) for k in ("initial", "signal", "basket", "signal+basket")},
                "partial": int(sum(1 for e in self.evs if 0 < e["drop"].sum() < len(e["drop"])))}


def build_events(bk: Book, dec_idx: np.ndarray, S: np.ndarray, mode: str, tagger: Tagger | None = None, perturb: Perturb | None = None,
                 keep_tags: bool = False) -> Events:
    """The event list of one realisation. mode: 'seg' (each stock follows its band), 'whole' (every stock follows IN iff all three BUY), 'parent' (nothing dropped)."""
    T, J = bk.T, len(dec_idx)
    v2 = {"tags_checked": 0, "tag_snapshot_after_info": 0, "events_checked": 0, "event_info_not_before_trade": 0, "event_decision_not_before_trade": 0,
          "initial_position_tag_reads_asof_T0": 0}
    skipped: list = []

    def read(cols: np.ndarray, info_idx: int, initial: bool):
        n = len(cols)
        if mode != "seg":
            return np.zeros(n, dtype=np.int8), ["na"] * n, [None] * n
        d = bk.cal[info_idx]
        tags = [tagger.get(bk.isin[c], d) for c in cols]
        bands = np.array([BAND_IDX[t["band"]] for t in tags], dtype=np.int8)
        src = [t["source"] for t in tags]
        for t in tags:
            if initial:
                v2["initial_position_tag_reads_asof_T0"] += 1
            else:
                v2["tags_checked"] += 1
            if t["snapshot"] is not None and pd.Timestamp(t["snapshot"]) > d:
                v2["tag_snapshot_after_info"] += 1
        if perturb is not None:
            bands = perturb.apply(bands, src)
        return bands, src, tags

    def make(k: int, kind: str, s: int, info_idx: int, jst: int, b: int, cols, bands, src, tags) -> dict:
        w = bk.W[b][cols]
        drop = dropped_of(mode, bands, S[jst])
        return {"k": k, "kind": kind, "t": s, "info_idx": info_idx, "jst": jst, "b": b, "cols": cols, "w": w, "wraw": bk.Wraw[b][cols],
                "bands": bands, "src": src, "tags": tags if keep_tags else None, "drop": drop, "state": tuple(int(x) for x in S[jst])}

    cols0 = bk.held(bk.b0)
    bands0, src0, tags0 = read(cols0, 0, True)
    evs = [make(0, "initial", 0, 0, 0, bk.b0, cols0, bands0, src0, tags0)]
    cur_b, cur_cols, cur_bands, cur_drop = bk.b0, cols0, bands0, evs[0]["drop"]
    kept_share = np.full(J, np.nan)
    sig_at = {int(dec_idx[j]) + 1: j for j in range(1, J) if int(dec_idx[j]) + 1 < T}
    wcur = bk.W[cur_b][cur_cols]
    kept_share[0] = float(wcur[~cur_drop].sum() / wcur.sum())
    for s in sorted(set(sig_at) | bk.basket_events):
        j = sig_at.get(s)
        isb = s in bk.basket_events
        trig = False
        if j is not None:
            dn = dropped_of(mode, cur_bands, S[j])
            wc = bk.W[cur_b][cur_cols]
            kept_share[j] = float(wc[~dn].sum() / wc.sum())
            trig = mode != "parent" and not np.array_equal(dn, cur_drop)
        if not trig and not isb:
            continue
        b = int(bk.basket_at[s])
        cols = bk.held(b)
        if not trig and cur_drop.all():
            # a basket change while the book holds no stock: nothing is traded and no event is written (EV2); the new basket becomes the
            # one the next signal test looks at, its tags read as of the previous session, everything in it 'currently dropped'
            bands, src, tags = read(cols, s - 1, False)
            skipped.append({"session": s, "date": str(bk.cal[s].date()), "basket_eff": str(bk.eff[b].date()), "n_held_new_basket": int(len(cols))})
            cur_b, cur_cols, cur_bands, cur_drop = b, cols, bands, np.ones(len(cols), dtype=bool)
            continue
        jst = int(np.searchsorted(dec_idx, s - 1, side="right") - 1)
        bands, src, tags = read(cols, s - 1, False)
        kind = "signal+basket" if (trig and isb) else ("signal" if trig else "basket")
        ev = make(len(evs), kind, s, s - 1, jst, b, cols, bands, src, tags)
        v2["events_checked"] += 1
        v2["event_info_not_before_trade"] += int(not (ev["info_idx"] < s))
        v2["event_decision_not_before_trade"] += int(not (int(dec_idx[jst]) < s))
        evs.append(ev)
        cur_b, cur_cols, cur_bands, cur_drop = b, cols, bands, ev["drop"]
    # decisions without a candidate session (the last one has no later session): the share the current tags keep
    for j in range(J):
        if np.isnan(kept_share[j]):
            dn = dropped_of(mode, cur_bands, S[j])
            wc = bk.W[cur_b][cur_cols]
            kept_share[j] = float(wc[~dn].sum() / wc.sum())
    return Events(evs, skipped, kept_share, v2, mode)


# ── subsets and nulls ─────────────────────────────────────────────────────────
_BITS: dict = {}


def bits_matrix(n: int) -> np.ndarray:
    """(2^n, n) uint8: row m, column i = bit i of m."""
    if n not in _BITS:
        _BITS[n] = ((np.arange(1 << n)[:, None] >> np.arange(n)) & 1).astype(np.uint8)
    return _BITS[n]


def subset_sums(w: np.ndarray) -> np.ndarray:
    """Sum of w over every subset, indexed by bitmask (bit i = w[i]); built by doubling."""
    s = np.zeros(1)
    for x in w:
        s = np.concatenate([s, s + x])
    return s


_ACACHE: dict = {}


def prepare_allowed(E: Events, strict: bool = True) -> None:
    """For every event: D, tau, the allowed masks A (increasing), their bits, count. Asserts the rule's own set is in A."""
    if E.allowed_done:
        return
    for ev in E.evs:
        w, drop = ev["w"], ev["drop"]
        n = len(w)
        assert 1 <= n <= 16, f"{n} held stocks at an event: N4.6 enumerates at most 16"
        key = (w.tobytes(), drop.tobytes())
        if key not in _ACACHE:
            D = float(w[drop].sum())
            tau = 0.5 * float(w.min())
            sums = subset_sums(w)
            diff = np.abs(sums - D)
            A = np.flatnonzero(diff <= tau + SUBSET_TOL).astype(np.int64)
            boundary = int((np.abs(diff - tau) < 1e-9).sum())
            rule_mask = int((drop.astype(np.int64) << np.arange(n)).sum())
            assert rule_mask in set(A.tolist()), "the rule's own drop set is outside its allowed set"
            _ACACHE[key] = (D, tau, A, bits_matrix(n)[A], boundary)
        D, tau, A, Ab, boundary = _ACACHE[key]
        ev["D"], ev["tau"], ev["A"], ev["Abits"], ev["nA"], ev["boundary"] = D, tau, A, Ab, int(len(A)), boundary
    E.allowed_done = True


def pick_index(u: np.ndarray, count: int) -> np.ndarray:
    """floor(u * count), clamped to count-1 (u < 1 so the clamp only guards floating-point rounding)."""
    return np.minimum((np.asarray(u) * count).astype(np.int64), count - 1)


def draws_n46(E: Events, book_no: int, ids) -> np.ndarray:
    """(len(ids), R) uint8 drops of the N4.6 draws; one uniform per event in event order from default_rng([7, id, book_no])."""
    prepare_allowed(E)
    U = np.array([np.random.default_rng([7, int(i), book_no]).random(E.n) for i in ids])
    out = np.zeros((len(ids), E.R), dtype=np.uint8)
    for k, ev in enumerate(E.evs):
        out[:, E.off[k]:E.off[k + 1]] = ev["Abits"][pick_index(U[:, k], ev["nA"])]
    return out


def draws_n48(E: Events, book_no: int, ids, isin_of_col: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(drops, labels), both (len(ids), R) uint8. One score per ISIN of the universe, labels by descending score with the rule's counts per band."""
    uni = sorted({str(isin_of_col[c]) for ev in E.evs for c in ev["cols"]})
    pos = {x: i for i, x in enumerate(uni)}
    Sc = np.array([np.random.default_rng([8, int(i), book_no]).random(len(uni)) for i in ids])
    drops = np.zeros((len(ids), E.R), dtype=np.uint8)
    labels = np.zeros((len(ids), E.R), dtype=np.uint8)
    for k, ev in enumerate(E.evs):
        ui = np.array([pos[str(isin_of_col[c])] for c in ev["cols"]])
        sub = Sc[:, ui]
        order = np.argsort(-sub, axis=1, kind="stable")
        rank = np.argsort(order, axis=1, kind="stable")
        nL, nM = int((ev["bands"] == 0).sum()), int((ev["bands"] == 1).sum())
        lab = np.where(rank < nL, 0, np.where(rank < nL + nM, 1, 2)).astype(np.uint8)
        off = (np.array(ev["state"]) == 0)                       # label's band signal is SELL
        labels[:, E.off[k]:E.off[k + 1]] = lab
        drops[:, E.off[k]:E.off[k + 1]] = off[lab].astype(np.uint8)
    E.universe = uni
    return drops, labels


def v3_n46(E: Events, drops: np.ndarray) -> dict:
    """V3 for N4.6: every event of every draw: inside the held set (by construction of the array), weight within tau of the rule's,
    nothing/everything dropped where the rule drops nothing/everything, the event list equals the rule's (same R)."""
    bad = {"dropped_weight_outside_tau": 0, "empty_or_full_not_matched": 0, "event_list_differs": 0}
    checked = 0
    if drops.shape[1] != E.R:
        bad["event_list_differs"] += int(drops.shape[0])
    for k, ev in enumerate(E.evs):
        d = drops[:, E.off[k]:E.off[k + 1]].astype(float)
        dw = d @ ev["w"]
        bad["dropped_weight_outside_tau"] += int((np.abs(dw - ev["D"]) > ev["tau"] + SUBSET_TOL).sum())
        nd = int(ev["drop"].sum())
        n = len(ev["drop"])
        if nd == 0:
            bad["empty_or_full_not_matched"] += int((d.sum(axis=1) != 0).sum())
        elif nd == n:
            bad["empty_or_full_not_matched"] += int((d.sum(axis=1) != n).sum())
        checked += len(d)
    return {"draws_x_events_checked": int(checked), "failures": bad, "pass": bool(checked > 0 and sum(bad.values()) == 0)}


def v3_n48(E: Events, labels: np.ndarray) -> dict:
    bad = {"label_counts_differ": 0}
    checked = 0
    for k, ev in enumerate(E.evs):
        lab = labels[:, E.off[k]:E.off[k + 1]]
        for b in range(3):
            bad["label_counts_differ"] += int(((lab == b).sum(axis=1) != int((ev["bands"] == b).sum())).sum())
        checked += len(lab)
    return {"draws_x_events_checked": int(checked), "failures": bad, "pass": bool(checked > 0 and sum(bad.values()) == 0)}


# ── simulation ────────────────────────────────────────────────────────────────
def sim(bk: Book, E: Events, dflat, cost_bps: float, mix_f: float | None = None, record: bool = False, share: bool = False):
    """Run an event list. dflat: uint8 drops over E's rows (ignored when mix_f is given). Returns a dict: nav, trades (count), cost_paid,
    and with record: the trade and position logs; with share: the daily share of NAV held in stocks."""
    T, ow, N = bk.T, cost_bps / 2e4, bk.N
    C, P, g, gf, L = bk.C, bk.P, bk.g, bk.gf, bk.L
    ev0 = E.evs[0]
    u = np.zeros(N)
    if mix_f is not None:
        u = bk.u0 * mix_f
        gu = (1 - mix_f) / 2 / g[0]
        cu = (1 - mix_f) / 2 / L[0]
    else:
        d0 = dflat[E.off[0]:E.off[1]].astype(bool)
        kc, dc = ev0["cols"][~d0], ev0["cols"][d0]
        u[kc] = bk.u0[kc]
        val = float((bk.u0[dc] * C[0, dc]).sum())
        gu, cu = val / 2 / g[0], val / 2 / L[0]
    nav = np.empty(T)
    shr = np.empty(T) if share else None
    nz = np.flatnonzero(u)
    a = 0
    ntr, cpaid = 0, 0.0
    trades, pos_log = [], []

    def fill(a, t):
        sv = C[a:t][:, nz] @ u[nz] if len(nz) else np.zeros(t - a)
        nav[a:t] = sv + g[a:t] * gu + L[a:t] * cu
        if share:
            shr[a:t] = sv / nav[a:t]

    for k in range(1, E.n):
        ev = E.evs[k]
        t = ev["t"]
        fill(a, t)
        a = t
        ps, gp, lv = P[t], gf[t], L[t]
        held_s = u * ps
        V = held_s.sum() + gu * gp + cu * lv
        w = ev["w"]
        if mix_f is not None:
            wt, s = w * mix_f, 1.0 - mix_f
        else:
            d = dflat[E.off[k]:E.off[k + 1]].astype(bool)
            nd = int(d.sum())
            wt = np.where(d, 0.0, w)
            s = 0.0 if nd == 0 else (1.0 if nd == len(d) else float(w[d].sum() / w.sum()))
        Te = np.zeros(N)
        Te[ev["cols"]] = V * wt
        Tg = Tc = V * s / 2
        traded = np.abs(Te - held_s).sum() + abs(Tg - gu * gp) + abs(Tc - cu * lv)
        cost = ow * traded
        kk = (V - cost) / V
        pos = (Te > 0) & (ps > 0)
        assert not ((Te > 0) & (ps <= 0)).any(), f"no price for a stock to buy at session {bk.cal[t].date()}"
        if record:
            nobar_n = int((bk.nobar[t] & ((Te > 0) | (held_s > 0))).sum())
            gold_raw_trade = bool(bk.gold_raw[t] and abs(Tg - gu * gp) > 0)
        new_u = np.zeros(N)
        new_u[pos] = kk * Te[pos] / ps[pos]
        u, gu, cu = new_u, kk * Tg / gp, kk * Tc / lv
        nz = np.flatnonzero(u)
        ntr += 1
        cpaid += cost
        if record:
            nav_close = float(C[t][nz] @ u[nz] + gu * g[t] + cu * L[t]) if len(nz) else float(gu * g[t] + cu * L[t])
            trades.append({"k": k, "date": bk.cal[t].date(), "idx": t, "kind": ev["kind"], "e_after": 1.0 - s, "basket_eff": bk.eff[ev["b"]].date(),
                           "V": V, "traded": traded, "cost": cost, "nav_close_after": nav_close, "n_dropped": (int(d.sum()) if mix_f is None else 0),
                           "stock_no_bar": nobar_n, "gold_raw": gold_raw_trade})
            for i in nz:
                pos_log.append({"date": bk.cal[t].date(), "instrument": bk.stocks[i], "units": u[i]})
            if gu > 0:
                pos_log.append({"date": bk.cal[t].date(), "instrument": "GOLDBEES", "units": gu})
            if cu > 0:
                pos_log.append({"date": bk.cal[t].date(), "instrument": "LBES", "units": cu})
    fill(a, T)
    out = {"nav": nav, "trades": ntr, "cost_paid": cpaid}
    if share:
        out["share"] = shr
    if record:
        out["trade_log"], out["pos_log"] = trades, pos_log
    return out


def stats(nav: np.ndarray) -> dict:
    T = len(nav)
    yrs = (T - 1) / 252
    r = nav[1:] / nav[:-1] - 1
    peak = np.maximum.accumulate(nav)
    dd = nav / peak - 1
    under = (dd < 0).astype(np.int8)
    ch = np.flatnonzero(np.diff(np.concatenate([[0], under, [0]])))
    longest = int((ch[1::2] - ch[0::2]).max()) if len(ch) else 0
    cagr = nav[-1] ** (1 / yrs) - 1
    mdd = float(dd.min())
    return {"end_nav": float(nav[-1]), "cagr": float(cagr), "max_dd": mdd, "vol": float(r.std(ddof=1) * math.sqrt(252)),
            "ulcer": float(math.sqrt(np.mean((100 * dd) ** 2))), "days_below_10pct": int((dd <= -0.10).sum()),
            "longest_underwater": longest, "calmar": float(cagr / abs(mdd)) if mdd < 0 else float("nan"), "sessions": T}


def pctile(x: float, draws, higher_better: bool = True) -> float:
    """(draws worse + 0.5 x draws tied) / draws x 100; ties are equal within a relative 1e-12."""
    d = np.asarray(draws, dtype=float)
    tie = np.abs(d - x) <= 1e-12 * np.maximum(np.maximum(np.abs(d), abs(x)), 1e-300)
    worse = (d < x) if higher_better else (d > x)
    worse &= ~tie
    return float((worse.sum() + 0.5 * tie.sum()) / len(d) * 100)


# ── V5 (a) ────────────────────────────────────────────────────────────────────
def gammaincc(a: float, x: float) -> float:
    """Regularised upper incomplete gamma Q(a, x) (series / continued fraction)."""
    if x <= 0:
        return 1.0
    gln = math.lgamma(a)
    if x < a + 1:
        ap_, s, de = a, 1.0 / a, 1.0 / a
        for _ in range(10000):
            ap_ += 1
            de *= x / ap_
            s += de
            if abs(de) < abs(s) * 1e-16:
                break
        return 1.0 - s * math.exp(-x + a * math.log(x) - gln)
    b = x + 1 - a
    c = 1e300
    d = 1 / b
    h = d
    for i in range(1, 10000):
        an = -i * (i - a)
        b += 2
        d = an * d + b
        d = 1e-300 if abs(d) < 1e-300 else d
        c = b + an / c
        c = 1e-300 if abs(c) < 1e-300 else c
        d = 1 / d
        de = d * c
        h *= de
        if abs(de - 1) < 1e-16:
            break
    return math.exp(-x + a * math.log(x) - gln) * h


def sampler_selftest(n: int = 200_000) -> dict:
    """V5(a): a small unequal-weight basket; every allowed subset enumerated by brute force (itertools over index tuples, exact Fractions);
    n samples drawn with the production index rule floor(u x count) from the production subset enumeration; chi-square against equal frequencies."""
    from fractions import Fraction
    from itertools import combinations
    w_f = [Fraction(x, 100) for x in (22, 17, 14, 12, 10, 9, 8, 5, 3)]            # sums to 1, unequal
    w = np.array([float(x) for x in w_f])
    D_f = Fraction(30, 100)
    tau_f = min(w_f) / 2
    brute = []
    for r in range(len(w_f) + 1):
        for cmb in combinations(range(len(w_f)), r):
            if abs(sum(w_f[i] for i in cmb) - D_f) <= tau_f:
                brute.append(sum(1 << i for i in cmb))
    brute.sort()
    sums = subset_sums(w)
    A = np.flatnonzero(np.abs(sums - float(D_f)) <= 0.5 * w.min() + SUBSET_TOL)
    rng = np.random.default_rng([7, 123456789, 99])
    idx = pick_index(rng.random(n), len(A))
    cnt = np.bincount(idx, minlength=len(A))
    exp = n / len(A)
    chi = float(((cnt - exp) ** 2 / exp).sum())
    df = len(A) - 1
    p = gammaincc(df / 2, chi / 2)
    return {"weights": [str(x) for x in w_f], "D": str(D_f), "tau": str(tau_f), "n_allowed_brute_force": len(brute), "n_allowed_engine": int(len(A)),
            "sets_equal": bool(list(A) == brute), "samples": n, "expected_each": exp, "min_count": int(cnt.min()), "max_count": int(cnt.max()),
            "chi2": chi, "df": df, "p": p, "pass": bool(list(A) == brute and len(A) >= 10 and p > 0.001)}


# ── per-book processing ───────────────────────────────────────────────────────
def kind_row(book, window, cash, cost, kind, nav, events, trades, cost_paid, invested, extra=None) -> dict:
    return {"book": book, "window": window, "cash": cash, "cost_bps": cost, "kind": kind, **stats(nav), "invested_weeks": invested,
            "trades": trades, "cost_paid": cost_paid, "events": events, **(extra or {})}


def run_variants(bk: Book, E: Events, Ew: Events, Ep: Events, Es: Events, cost: float, window: str, cash: str, record_all: bool, p: str, rows: list, extra_out: dict):
    """Rule + comparators at one cost on one calendar/cash. Returns the rule's record dict (trade log, nav, share)."""
    J = len(E.kept_share)
    rule = sim(bk, E, E.dflat, cost, record=True, share=True)
    f = float(rule["share"].mean())
    whole = sim(bk, Ew, Ew.dflat, cost, record=record_all)
    par = sim(bk, Ep, Ep.dflat, cost, record=record_all)
    mix = sim(bk, E, None, cost, mix_f=f, record=record_all)
    slp = sim(bk, Es, Es.dflat, cost, record=record_all)
    rows += [kind_row(p, window, cash, cost, "segment", rule["nav"], E.n, rule["trades"], rule["cost_paid"], float(E.kept_share.sum())),
             kind_row(p, window, cash, cost, "whole_book", whole["nav"], Ew.n, whole["trades"], whole["cost_paid"], float(Ew.kept_share.sum())),
             kind_row(p, window, cash, cost, "parent", par["nav"], Ep.n, par["trades"], par["cost_paid"], float(J)),
             kind_row(p, window, cash, cost, "constant_mix", mix["nav"], E.n, mix["trades"], mix["cost_paid"], J * f, {"mix_share_f": f}),
             kind_row(p, window, cash, cost, "sleeve100", slp["nav"], Es.n, slp["trades"], slp["cost_paid"], 0.0),
             kind_row(p, window, cash, cost, "published_parent", bk.pub / bk.pub[0], np.nan, np.nan, np.nan, float(J))]
    return {"segment": rule, "whole_book": whole, "parent": par, "constant_mix": mix, "sleeve100": slp, "f": f}


def draw_rows(bk: Book, E: Events, drops: np.ndarray, dtype: str, window: str, cash: str, cost: float, w_flat: np.ndarray, curves: dict | None, book: str) -> list:
    dw = np.add.reduceat(drops.astype(float) * w_flat[None, :], E.off[:-1], axis=1).mean(axis=1)
    rows = []
    for d in range(len(drops)):
        r = sim(bk, E, drops[d], cost)
        rows.append({"book": book, "window": window, "cash": cash, "cost_bps": cost, "draw_type": dtype, "draw_id": d, **stats(r["nav"]),
                     "trades": r["trades"], "cost_paid": r["cost_paid"], "mean_dropped_weight": float(dw[d]), "n_events": E.n})
        if curves is not None:
            curves[f"{book}|{dtype}_{d}"] = r["nav"].astype(np.float32)
    return rows


def event_tables(p: str, window: str, E: Events, bk: Book, rec_trades: list, dec: pd.DataFrame, nA_ok: bool = True):
    """events.csv rows, event_stocks.csv rows of the rule."""
    by_k = {t["k"]: t for t in rec_trades}
    ev_rows, st_rows = [], []
    row0 = 0
    for k, ev in enumerate(E.evs):
        t = ev["t"]
        n = len(ev["cols"])
        nd = int(ev["drop"].sum())
        sw = float(ev["w"].sum())
        D = float(ev["w"][ev["drop"]].sum())
        tr = by_k.get(k)
        ev_rows.append({"book": p, "window": window, "event_no": k, "kind": ev["kind"], "trade_date": bk.cal[t].date(), "trade_idx": t,
                        "info_date": bk.cal[ev["info_idx"]].date(), "decision_date": dec["decision_date"].iloc[ev["jst"]],
                        **{f"state_{SIGNALS[i]}": ("BUY" if ev["state"][i] else "SELL") for i in range(3)},
                        "basket_eff": bk.eff[ev["b"]].date(), "n_held": n, "n_large": int((ev["bands"] == 0).sum()), "n_mid": int((ev["bands"] == 1).sum()),
                        "n_small": int((ev["bands"] == 2).sum()), "n_dropped": nd, "dropped_weight": D, "sum_weights": sw,
                        "sum_weights_raw": float(ev["wraw"].sum()), "sleeve_share_s": (0.0 if nd == 0 else 1.0 if nd == n else D / sw),
                        "partial": bool(0 < nd < n), "n_allowed_subsets": ev["nA"], "tau": ev["tau"],
                        "V_before": (tr["V"] if tr else 1.0), "traded": (tr["traded"] if tr else 0.0), "cost": (tr["cost"] if tr else 0.0)})
        for i, c in enumerate(ev["cols"]):
            tg = ev["tags"][i]
            st_rows.append({"book": p, "window": window, "event_no": k, "row": row0 + i, "trade_date": bk.cal[t].date(), "info_date": bk.cal[ev["info_idx"]].date(),
                            "isin": bk.isin[c], "stock": bk.stocks[c], "listed_weight": float(ev["w"][i]), "listed_weight_raw": float(ev["wraw"][i]),
                            "band": BANDS[int(ev["bands"][i])], "tag_source": tg["source"], "tag_snapshot": tg["snapshot"], "tag_detail": tg["detail"],
                            "tag_via": tg["via"], "band_signal": "BUY" if ev["state"][int(ev["bands"][i])] else "SELL", "kept": bool(not ev["drop"][i])})
        row0 += n
    return ev_rows, st_rows


def stretches(flags) -> list:
    out, c = [], 0
    for f in flags:
        if f:
            c += 1
        elif c:
            out.append(c)
            c = 0
    if c:
        out.append(c)
    return out


def oracle_drops(bk: Book, E: Events) -> np.ndarray:
    """V7: per event the subset of the allowed set with the lowest sum of w x log return from the trade session to the next event's trade session."""
    prepare_allowed(E)
    out = np.zeros(E.R, dtype=np.uint8)
    for k, ev in enumerate(E.evs):
        cols = ev["cols"]
        start = bk.C[0, cols] if k == 0 else bk.P[ev["t"], cols]
        end = bk.C[bk.T - 1, cols] if k == E.n - 1 else bk.P[E.evs[k + 1]["t"], cols]
        with np.errstate(divide="ignore", invalid="ignore"):
            lr = np.where((start > 0) & (end > 0), np.log(end / start), 0.0)
        score = ev["Abits"].astype(float) @ (ev["w"] * lr)
        out[E.off[k]:E.off[k + 1]] = ev["Abits"][int(np.argmin(score))]
    return out


def process_book(p: str, cfg: dict) -> dict:
    """Everything for one parent: both windows, all costs, cash variants, comparators, draws, self-check inputs, controls, R5. Returns picklable results."""
    global CHECK_SHA
    CHECK_SHA = cfg.get("check_sha", False)
    t_start = time.time()
    book_no = PARENTS.index(p)
    nd = cfg["draws"]
    ids = np.arange(nd)
    tagger = Tagger()
    res = {"book": p, "stats": [], "draws": [], "nav": {}, "trades": [], "positions": [], "events": [], "event_stocks": [], "drops": {}, "labels": {}, "curves": {},
           "audit": {}, "count_table": {}, "v3": {}, "v5": {"count_equal": 0, "count_unequal": 0, "rule_in_allowed": 0, "events": 0}, "controls": {}, "r5": []}
    a_book = res["audit"]
    aa_nav = None
    realisations = {}
    for window in ("full", "live"):
        bk = Book(p, start=None if window == "full" else LIVE_START)
        dec, S, idx = bk.decisions()
        if window == "full":
            res["decisions"] = dec
            bk_full, dec_full, S_full, idx_full = bk, dec, S, idx
        E = build_events(bk, idx, S, "seg", tagger, keep_tags=True)
        prepare_allowed(E)
        Ew = build_events(bk, idx, S, "whole")
        Ep = build_events(bk, idx, S, "parent")
        Es = build_events(bk, idx, np.zeros_like(S), "whole")
        # V5(b)/(c)
        for ev in E.evs:
            w = ev["w"]
            alt = bits_matrix(len(w)).astype(float) @ w
            cnt_alt = int((np.abs(alt - ev["D"]) <= ev["tau"] + SUBSET_TOL).sum())
            res["v5"]["events"] += 1
            res["v5"]["count_equal" if cnt_alt == ev["nA"] else "count_unequal"] += 1
            res["v5"]["rule_in_allowed"] += int(int((ev["drop"].astype(np.int64) << np.arange(len(w))).sum()) in set(ev["A"].tolist()))
        # draws (the same for every cost and cash)
        n46 = draws_n46(E, book_no, ids)
        n48, lab48 = draws_n48(E, book_no, ids, bk.isin)
        res["drops"][f"{p}|{window}|N4.6"], res["drops"][f"{p}|{window}|N4.8"], res["labels"][f"{p}|{window}|N4.8"] = n46, n48, lab48
        res["v3"][f"{p}|{window}"] = {"N4.6": v3_n46(E, n46), "N4.8": v3_n48(E, lab48)}
        # tables
        reals = [("lbes", c) for c in COSTS] if window == "full" else [("lbes", PRIMARY)]
        if window == "full":
            reals.append(("liq", PRIMARY))
        bkc = {"lbes": bk, "liq": Book(p, cash="liq") if window == "full" else None}
        for cash, cost in reals:
            b2 = bkc[cash]
            headline = (window == "full" and cash == "lbes")
            rows = res["stats"]
            vr = run_variants(b2, E, Ew, Ep, Es, cost, window, cash, headline, p, rows, res)
            if cash == "lbes" and cost == PRIMARY:
                rule = vr["segment"]
                ev_rows, st_rows = event_tables(p, window, E, b2, rule["trade_log"], dec)
                res["events"] += ev_rows
                res["event_stocks"] += st_rows
                realisations[window] = {"E": E, "bk": b2, "dec": dec, "S": S, "idx": idx, "rule_cagr": stats(rule["nav"])["cagr"], "whole_cagr": stats(vr["whole_book"]["nav"])["cagr"]}
                a_book.setdefault("rule_counters", {})[window] = {
                    "stock_trades_priced_by_last_close_no_bar": int(sum(t["stock_no_bar"] for t in rule["trade_log"])),
                    "goldbees_trades_filled_at_raw_OHLC4_after_MCX_file": int(sum(t["gold_raw"] for t in rule["trade_log"]))}
            if headline:
                for name, rr in (("segment", vr["segment"]), ("whole_book", vr["whole_book"]), ("parent", vr["parent"]), ("constant_mix", vr["constant_mix"]), ("sleeve100", vr["sleeve100"])):
                    res["nav"][(p, cost, name)] = rr["nav"]
                    res["trades"] += [{"book": p, "cost_bps": cost, "run": name, **{k: v for k, v in t.items() if k not in ("stock_no_bar", "gold_raw", "k")}, "event_no": t["k"]}
                                      for t in rr["trade_log"]]
                    res["positions"] += [{"book": p, "cost_bps": cost, "run": name, **q} for q in rr["pos_log"]]
            # draws
            for dtype, dr in (("N4.6", n46), ("N4.8", n48)):
                res["draws"] += draw_rows(b2, E, dr, dtype, window, cash, cost, E.w_flat,
                                          res["curves"] if (headline and cost == PRIMARY) else None, p)
        if window == "full":
            res["pub_full"] = bk.pub / bk.pub[0]
            res["cal_full"] = bk.cal
        else:
            # R6: the AA book's published NAV on the live window
            a = pd.read_csv(ap(d17_path(AA_BOOK[p])))
            s = pd.Series(a["index"].values, index=pd.to_datetime(a["_id.date"], format="%Y/%m/%d")).sort_index()
            s = s[(s.index >= bk.cal[0]) & (s.index <= bk.cal[-1])]
            same = bool(len(s) == bk.T and (s.index == bk.cal).all())
            s = s.reindex(bk.cal).ffill()
            res["stats"].append(kind_row(p, "live", "lbes", np.nan, "published_aa", s.values / s.values[0], np.nan, np.nan, np.nan, np.nan, {"aa_scid": AA_BOOK[p]}))
            a_book["aa_published_calendar_equals_live_calendar"] = same
        # counts, reportability
        flags = dec["disagree"].values
        stch = stretches(flags)
        cnt = E.counts()
        res["count_table"][window] = {
            "events": [{"event_no": k, "trade_date": str(bk.cal[ev["t"]].date()), "n_allowed_subsets": str(ev["nA"]), "tau": ev["tau"], "n_held": len(ev["cols"]),
                        "n_dropped": int(ev["drop"].sum()), "dropped_weight": ev["D"], "weights": [float(x) for x in ev["w"]], "boundary_cases": ev["boundary"]}
                       for k, ev in enumerate(E.evs)],
            "events_with_partial": cnt["partial"], "disagreement_stretches": stch, "n_disagreement_stretches": len(stch)}
        in_dis = int(sum(1 for ev in E.evs[1:] if dec["disagree"].iloc[ev["jst"]]))
        ws = []
        for ev in E.evs:
            ws.append(ev["nA"])
        src_cnt = pd.Series([r["tag_source"] for r in res["event_stocks"] if r["window"] == window]).value_counts().to_dict()
        a_book.setdefault("windows", {})[window] = {
            "t0": str(bk.t0.date()), "last_session": str(bk.cal[-1].date()), "sessions": bk.T, "decisions": len(dec),
            "initial_basket_switch_session": bk.initial_basket_switch_session, "cash": bk.cash_info,
            "disagreement_weeks": int(flags.sum()), "disagreement_stretches": len(stch), "stretch_lengths": stch,
            "events": cnt, "events_in_disagreement_weeks": in_dis, "n_allowed_subsets_min_median_max": [int(min(ws)), int(np.median(ws)), int(max(ws))],
            "events_with_one_allowed_subset": int(sum(1 for x in ws if x == 1)), "tau_boundary_cases": int(sum(ev["boundary"] for ev in E.evs)),
            "skipped_basket_events": E.skipped, "whole_book_events": Ew.counts(), "whole_book_skipped_basket_events": len(Ew.skipped),
            "tag_source_event_rows": src_cnt, "v2": E.v2,
            "reportable": bool(len(stch) >= 5 and cnt["partial"] >= 6),
            "skipped_basket_events_where_new_basket_would_keep_a_stock": None,
            "mean_dropped_weight_rule": float(np.mean([ev["D"] for ev in E.evs])),
            "n_universe_N4.8": len(E.universe)}
        a_book["windows"][window]["v2"]["decisions_checked"] = int(len(dec))
        a_book["windows"][window]["v2"]["decisions_label_after_decision"] = int((pd.to_datetime(dec["latest_label"]) > pd.to_datetime(dec["decision_date"])).sum())
        td = pd.to_datetime(dec["trade_date"].dropna())
        dd = pd.to_datetime(dec.loc[dec["trade_date"].notna(), "decision_date"])
        a_book["windows"][window]["v2"]["decision_trades_checked"] = int(len(td))
        a_book["windows"][window]["v2"]["decision_trade_not_after_decision"] = int((td.values <= dd.values).sum())
    # V4 against T06 and G0 (full window)
    res["v4"] = v4_book(p, bk_full, dec_full, res)
    a_book["seconds_core"] = round(time.time() - t_start)
    # draws at the primary cost for the controls
    full = realisations["full"]
    if cfg["controls"]:
        res["controls"] = controls_book(p, book_no, full, res, tagger, cfg)
    if cfg["r5"] > 0:
        res["r5"] = r5_book(p, book_no, full, tagger, cfg["r5"])
    a_book["seconds"] = round(time.time() - t_start)
    res["usedfiles"] = USED
    res["tag_cache_size"] = len(tagger.cache)
    return res


def v4_book(p: str, bk: Book, dec: pd.DataFrame, res: dict) -> dict:
    t6d = pd.read_csv(T06E / "decisions.csv")
    t6n = pd.read_csv(T06E / "daily_nav.csv")
    b = t6d[t6d["book"] == p]
    a = dec.assign(decision_date=dec["decision_date"].astype(str))[["decision_date", "decision_idx", "state"]]
    m = a.merge(b[["decision_date", "decision_idx", "state"]], on="decision_date", how="inner", suffixes=("", "_t06"))
    mism = int(((m["state"] != m["state_t06"]) | (m["decision_idx"] != m["decision_idx_t06"])).sum())
    out = {"decisions": {"t07_decisions": int(len(a)), "t06_decisions": int(len(b)), "shared": int(len(m)), "mismatches": mism,
                         "t06_dates_not_in_t07": [d for d in b["decision_date"] if d not in set(a["decision_date"])]}, "nav": []}
    ok = mism == 0 and len(m) > 0
    cal = bk.cal
    names = {"strategy": "whole_book", "hold_parent": "parent", "sleeve_only": "sleeve100"}
    for (run, cost), g in t6n[(t6n["book"] == p) & t6n["cost_bps"].notna()].groupby(["run", "cost_bps"]):
        if run not in names:
            continue
        g = g.assign(date=pd.to_datetime(g["date"])).set_index("date")["nav"]
        mine = pd.Series(res["nav"][(p, float(cost), names[run])], index=cal)
        cd = g.index[g.index <= T06_NAV_END].intersection(mine.index)
        rel = float((mine.loc[cd] / g.loc[cd] - 1).abs().max())
        passed = bool(len(cd) > 0 and rel < REL_TOL_NAV)
        ok &= passed
        out["nav"].append({"book": p, "t06_run": run, "t07_run": names[run], "cost_bps": float(cost), "dates_compared": int(len(cd)), "max_rel_diff": rel, "pass": passed})
    # always-in against the published NAV (G0): parent at 0 cost
    nav0 = res["nav"][(p, 0.0, "parent")]
    c = pd.DataFrame({"m": nav0, "p": bk.pub}, index=bk.cal)
    c = c / c.iloc[0] * 100
    yrs = (c.index[-1] - c.index[0]).days / 365.25
    gap = ((c.m.iloc[-1] / c.m.iloc[0]) ** (1 / yrs) - (c.p.iloc[-1] / c.p.iloc[0]) ** (1 / yrs)) * 100
    worst, wy = 0.0, None
    for yr, gg in c.groupby(c.index.year):
        prev = c.loc[:gg.index[0]].iloc[-2] if len(c.loc[:gg.index[0]]) > 1 else gg.iloc[0]
        d = (gg["m"].iloc[-1] / prev["m"] - gg["p"].iloc[-1] / prev["p"]) * 100
        if abs(d) > abs(worst):
            worst, wy = d, int(yr)
    g0 = {"book": p, "cagr_gap_pp_yr": float(gap), "overall": "PASS" if abs(gap) <= G0_OVERALL else "FAIL", "worst_year": wy, "worst_year_gap_pp": float(worst),
          "yearly": "PASS" if abs(worst) <= G0_YEARLY else "FAIL", "window_first": str(c.index[0].date()), "window_last": str(c.index[-1].date())}
    ok &= g0["overall"] == "PASS" and g0["yearly"] == "PASS"
    out["g0"], out["pass"] = g0, bool(ok)
    return out


def controls_book(p: str, book_no: int, full: dict, res: dict, tagger: Tagger, cfg: dict) -> dict:
    """V6 (negative control) and V7 (oracle) for one book, full window, LBES, 20.8 bps."""
    bk, dec, S, idx, E = full["bk"], full["dec"], full["S"], full["idx"], full["E"]
    J = len(idx)
    out = {}
    # V7
    od = oracle_drops(bk, E)
    ro = sim(bk, E, od, PRIMARY)
    so = stats(ro["nav"])
    n46_c = np.array([r["cagr"] for r in res["draws"] if r["draw_type"] == "N4.6" and r["window"] == "full" and r["cash"] == "lbes" and r["cost_bps"] == PRIMARY])
    pc = pctile(so["cagr"], n46_c)
    out["v7"] = {"book": p, "oracle_cagr": so["cagr"], "oracle_max_dd": so["max_dd"], "rule_cagr": full["rule_cagr"], "percentile_vs_N4.6": pc,
                 "n46_draws": int(len(n46_c)), "events_with_a_choice": int(sum(1 for ev in E.evs if ev["nA"] > 1)), "pass_ge_99": bool(pc >= 99)}
    # V6
    n = J
    shifts = np.arange(26, n - 26 + 1)
    chosen = np.random.default_rng([9, 100000, book_no]).choice(shifts, size=cfg["v6_shifts"], replace=False)
    rows = []
    v3_bad, v3_checked = 0, 0
    for i, k in enumerate(chosen):
        Ssh = np.roll(S, int(k), axis=0)
        Esh = build_events(bk, idx, Ssh, "seg", tagger)
        prepare_allowed(Esh)
        rng = np.random.default_rng([9, i, book_no])
        U = rng.random((cfg["v6_draws"], Esh.n))
        drops = np.zeros((cfg["v6_draws"], Esh.R), dtype=np.uint8)
        for kk, ev in enumerate(Esh.evs):
            drops[:, Esh.off[kk]:Esh.off[kk + 1]] = ev["Abits"][pick_index(U[:, kk], ev["nA"])]
        v = v3_n46(Esh, drops)
        v3_bad += sum(v["failures"].values())
        v3_checked += v["draws_x_events_checked"]
        rr = stats(sim(bk, Esh, Esh.dflat, PRIMARY)["nav"])
        dcagr = np.array([stats(sim(bk, Esh, drops[d], PRIMARY)["nav"])["cagr"] for d in range(len(drops))])
        pc_i = pctile(rr["cagr"], dcagr)
        rows.append({"book": p, "shift_index": i, "shift_k": int(k), "n_events": Esh.n, "cagr": rr["cagr"], "percentile": pc_i, "pass90": bool(pc_i >= 90)})
    share = float(np.mean([r["pass90"] for r in rows])) if rows else float("nan")
    n6 = len(rows)
    x6 = v6_xmax(n6) if n6 else 0                      # amended rule: one-sided, a book fails at x6 + 1 or more passes
    lo_, hi_ = 0.0, x6 / max(n6, 1)
    out["v6"] = {"book": p, "shifts": n6, "draws_per_shift": cfg["v6_draws"], "share_pass90": share, "band": [lo_, hi_], "x_max": x6,
                 "n_pass90": int(sum(r["pass90"] for r in rows)), "within_band": bool(n6 > 0 and sum(r["pass90"] for r in rows) <= x6),
                 "v3_failures": int(v3_bad), "v3_draws_x_events_checked": int(v3_checked)}
    out["v6_rows"] = rows
    return out


def r5_book(p: str, book_no: int, full: dict, tagger: Tagger, n: int) -> list:
    bk, S, idx = full["bk"], full["S"], full["idx"]
    out = []
    for d in range(n):
        pt = Perturb(d, book_no)
        Ed = build_events(bk, idx, S, "seg", tagger, perturb=pt)
        r = stats(sim(bk, Ed, Ed.dflat, PRIMARY)["nav"])
        out.append({"book": p, "draw_id": d, "cagr": r["cagr"], "diff_vs_whole_book": r["cagr"] - full["whole_cagr"], "n_events": Ed.n,
                    "rank_tag_reads": pt.rank_reads, "flipped": pt.flipped, "error_rate": R5_RATE})
    return out


# ── main ──────────────────────────────────────────────────────────────────────
def input_list() -> tuple[list, list]:
    inputs = [HD / "extended_2026-10-30" / "Master" / f"Master_{n}.xlsx" for n in SIGNALS]
    inputs += [AA / "analysis" / "cache" / "why_gold_ohlc_eikon_extended_2026-11-04.parquet",
               AA / "analysis" / "evidence" / "final_strategy" / "mauc1" / "mauc1_daily_clean.csv",
               HD / "LBES_Adjusted_Price_data_extended_2026-11-05.csv", HD / "liquidEtfFinal_extended_2026-11-05.csv", HM / "price_corrections.csv"]
    for p in PARENTS:
        inputs += [HM / f"{p}_{x}.csv" for x in ("ohlc", "holding_weight_matrix", "holding_weight_sources", "columns")] + [d17_path(p), d17_path(AA_BOOK[p])]
    inputs += list(TAG_FILES.values())
    not_parsed = []
    for p in PARENTS:
        not_parsed += [HD / "frozen_2026-09-25" / "Rebalance_history" / f"Rebalance_history_by_scid_{p}.csv"]
    not_parsed += RAW_TAG_FILES
    return inputs, not_parsed


def check_inputs() -> tuple[dict, list]:
    """Open every input through the approved table (sha256 checked), assert the window is covered, and run the non-approved-open self-test."""
    inputs, not_parsed = input_list()
    for f in inputs + not_parsed:
        ap(f)
    for rel, r in USED.items():
        if r["id"] in ("D17", "D18", "D03", "D09", "D11", "D15", "D20", "D21", "D22", "D23"):
            if r["through"] in ("n/a",):
                continue
            assert r["through"] >= str(END.date()), f"{rel}: approved through {r['through']}, before the window's end {END.date()}: stop and ask Manu"
    st = {}
    for name, f in (("superseded_master", HD / "frozen_2026-09-25" / "Master" / "Master_Nifty100.xlsx"),
                    ("superseded_goldbees", AA / "analysis" / "cache" / "why_gold_ohlc_eikon.parquet"),
                    ("superseded_lbes", HD / "LBES_Adjusted_Price_data_2026_08_10.csv"),
                    ("not_in_table", HD / "no_such_file.csv"),
                    ("off_limits_SOURCE_md", HD / "extended_2026-11-12" / "SOURCE.md")):
        try:
            AD.require(f)
            st[name] = {"raised": False}
        except NotApprovedError as e:
            st[name] = {"raised": True, "message": str(e)}
    st["pass"] = all(v["raised"] for v in st.values() if isinstance(v, dict))
    return st, [x.relative_to(AA).as_posix() for x in not_parsed]


def rerun(a) -> int:
    """Rebuild one draw from its id (evidence_contract CLI)."""
    global CHECK_SHA
    CHECK_SHA = False
    cash, cost, p = a.cash, a.cost, a.book
    assert p in PARENTS and a.type in ("N4.6", "N4.8") and a.window in ("full", "live")
    book_no = PARENTS.index(p)
    bk = Book(p, start=None if a.window == "full" else LIVE_START, cash=cash)
    dec, S, idx = bk.decisions()
    tagger = Tagger()
    E = build_events(bk, idx, S, "seg", tagger)
    if a.type == "N4.6":
        d = draws_n46(E, book_no, [a.id])
    else:
        d, _ = draws_n48(E, book_no, [a.id], bk.isin)
    r = sim(bk, E, d[0], cost)
    s = stats(r["nav"])
    Path(a.out).write_text(json.dumps({"end_nav": s["end_nav"], "cagr": s["cagr"], "max_dd": s["max_dd"], "drops": [int(x) for x in d[0]]}), encoding="utf-8")
    print(f"rerun {p} {a.window} {a.type} id {a.id} cost {cost} cash {cash}: cagr {s['cagr']:.6f} max_dd {s['max_dd']:.6f} -> {a.out}")
    return 0


def main():
    global CHECK_SHA
    ap_ = argparse.ArgumentParser()
    ap_.add_argument("--run", default="headline")
    ap_.add_argument("--draws", type=int, default=N_DRAWS)
    ap_.add_argument("--quick", action="store_true", help="smoke test: one book (SCMO_0003), no controls unless --controls, R5 with --r5 draws")
    ap_.add_argument("--controls", action="store_true", help="run V6 and V7 (always on in a full run)")
    ap_.add_argument("--v6-shifts", type=int, default=V6_SHIFTS)
    ap_.add_argument("--v6-draws", type=int, default=V6_DRAWS)
    ap_.add_argument("--r5", type=int, default=None, help="R5 draws per book (default 500; 20 with --quick)")
    ap_.add_argument("--jobs", type=int, default=None)
    ap_.add_argument("--books", default=None, help="comma-separated parents (default: SCMO_0003 with --quick, else all four); for tests")
    ap_.add_argument("--out-root", default=None, help="evidence root (default tests/T07/evidence); for scratch tests")
    ap_.add_argument("--rerun", action="store_true")
    ap_.add_argument("--book")
    ap_.add_argument("--type")
    ap_.add_argument("--id", type=int)
    ap_.add_argument("--cost", type=float)
    ap_.add_argument("--window", default="full")
    ap_.add_argument("--cash", default="lbes")
    ap_.add_argument("--out")
    a = ap_.parse_args()
    if a.rerun:
        sys.exit(rerun(a))
    outdir = (Path(a.out_root) if a.out_root else T07 / "evidence") / a.run
    outdir.mkdir(parents=True, exist_ok=True)
    t_start = time.time()
    books = a.books.split(",") if a.books else (PARENTS[:1] if a.quick else PARENTS)
    assert all(b in PARENTS for b in books)
    controls = (not a.quick) or a.controls
    r5 = a.r5 if a.r5 is not None else (20 if a.quick else N_R5)
    jobs = a.jobs if a.jobs is not None else (1 if len(books) == 1 else min(len(books), os.cpu_count() or 1))
    CHECK_SHA = True
    st, not_parsed = check_inputs()
    print(f"data: END = {END.date()}, approved data as of {AD.as_of()}, {len(USED)} inputs checked (sha256); non-approved open raises: {st['pass']}", flush=True)
    cfg = {"draws": a.draws, "controls": controls, "r5": r5, "v6_shifts": a.v6_shifts, "v6_draws": a.v6_draws, "check_sha": False}
    small = sampler_selftest()
    print(f"V5(a): {small['n_allowed_brute_force']} allowed subsets, chi2 {small['chi2']:.1f} df {small['df']} p {small['p']:.3f} pass {small['pass']}", flush=True)

    results = {}
    if jobs > 1:
        from concurrent.futures import ProcessPoolExecutor
        with ProcessPoolExecutor(max_workers=jobs) as ex:
            futs = {p: ex.submit(process_book, p, cfg) for p in books}
            for p, f in futs.items():
                results[p] = f.result()
                print(f"{p}: done in {results[p]['audit']['seconds']}s", flush=True)
    else:
        for p in books:
            results[p] = process_book(p, cfg)
            print(f"{p}: done in {results[p]['audit']['seconds']}s (core {results[p]['audit']['seconds_core']}s)", flush=True)
    for r in results.values():
        for k, v in r["usedfiles"].items():
            USED.setdefault(k, v)

    # ── write ──
    R = [results[p] for p in books]
    pd.DataFrame([{k: v[k] for k in ("file", "through", "bytes", "sha256", "approved_row")} for v in sorted(USED.values(), key=lambda x: x["file"])]).to_csv(outdir / "inputs.csv", index=False)
    pd.concat([r["decisions"] for r in R]).to_csv(outdir / "decisions.csv", index=False)
    pd.DataFrame([x for r in R for x in r["events"]]).to_csv(outdir / "events.csv", index=False)
    pd.DataFrame([x for r in R for x in r["event_stocks"]]).to_csv(outdir / "event_stocks.csv", index=False)
    stats_df = pd.DataFrame([x for r in R for x in r["stats"]])
    stats_df.to_csv(outdir / "stats.csv", index=False)
    pd.DataFrame([x for r in R for x in r["draws"]]).to_csv(outdir / "draws.csv", index=False)
    pd.DataFrame([x for r in R for x in r["trades"]]).to_csv(outdir / "trades.csv", index=False)
    pd.DataFrame([x for r in R for x in r["positions"]]).to_csv(outdir / "positions.csv", index=False)
    daily = []
    for r in R:
        p = r["book"]
        for (b_, cost, name), nv in r["nav"].items():
            daily.append(pd.DataFrame({"book": b_, "date": r["cal_full"], "cost_bps": cost, "run": name, "nav": nv}))
        daily.append(pd.DataFrame({"book": p, "date": r["cal_full"], "cost_bps": np.nan, "run": "published_parent", "nav": r["pub_full"]}))
    pd.concat(daily).to_csv(outdir / "daily_nav.csv", index=False)
    np.savez_compressed(outdir / "draw_drops.npz", **{k: v for r in R for k, v in r["drops"].items()})
    np.savez_compressed(outdir / "draw_labels.npz", **{k: v for r in R for k, v in r["labels"].items()})
    np.savez_compressed(outdir / "draw_curves_20.8.npz", **{k: v for r in R for k, v in r["curves"].items()})
    g4 = [r["v4"]["g0"] for r in R]
    pd.DataFrame(g4).assign(max_rel_diff_vs_step1_rebuild=np.nan, rebuild_dates_compared=0).to_csv(outdir / "g_engine.csv", index=False)
    ct = {r["book"]: {**r["count_table"], "events_with_partial": {w: r["count_table"][w]["events_with_partial"] for w in ("full", "live")}} for r in R}
    (outdir / "count_table.json").write_text(json.dumps({"books": ct, "note": "n_allowed_subsets is the exact count of N4.6 subsets per event (string); weights are the renormalised listed weights in increasing ISIN order"}, indent=1), encoding="utf-8")
    (outdir / "sampler_selftest.json").write_text(json.dumps(small, indent=1, default=str), encoding="utf-8")
    reg = {"tolerance_rel": REL_TOL_NAV, "compared_to": str(T06_NAV_END.date()), "books": {r["book"]: r["v4"] for r in R},
           "nav_rows_compared": int(sum(len(r["v4"]["nav"]) for r in R)), "g0": g4, "pass": bool(all(r["v4"]["pass"] for r in R)),
           "max_rel_diff": float(max(x["max_rel_diff"] for r in R for x in r["v4"]["nav"]))}
    (outdir / "regression_t06.json").write_text(json.dumps(reg, indent=1, default=str), encoding="utf-8")

    # controls
    v6_ok = v7_ok = None
    if controls:
        cr = [r["controls"] for r in R]
        pd.DataFrame([x for c in cr for x in c["v6_rows"]]).to_csv(outdir / "controls_negative.csv", index=False)
        v6 = {c["v6"]["book"]: c["v6"] for c in cr}
        v6_ok = bool(all(v["within_band"] and v["v3_failures"] == 0 for v in v6.values()))
        (outdir / "controls_negative.json").write_text(json.dumps({"books": v6, "pass": v6_ok}, indent=1, default=str), encoding="utf-8")
        v7 = {c["v7"]["book"]: c["v7"] for c in cr}
        v7_ok = bool(all(v["pass_ge_99"] for v in v7.values()))
        (outdir / "controls_oracle.json").write_text(json.dumps({"books": v7, "pass": v7_ok}, indent=1, default=str), encoding="utf-8")
    if r5 > 0:
        pd.DataFrame([x for r in R for x in r["r5"]]).to_csv(outdir / "r5_tag_error.csv", index=False)

    # V2, V3, V5 summaries
    v2 = {"decisions_checked": 0, "decision_label_after_decision": 0, "tags_checked": 0, "tag_snapshot_after_info": 0, "events_checked": 0,
          "event_info_not_before_trade": 0, "event_decision_not_before_trade": 0, "decision_trades_checked": 0, "decision_trade_not_after_decision": 0,
          "initial_position_tag_reads_asof_T0": 0}
    for r in R:
        for w, wa in r["audit"]["windows"].items():
            x = wa["v2"]
            v2["decisions_checked"] += x["decisions_checked"]
            v2["decision_label_after_decision"] += x["decisions_label_after_decision"]
            v2["decision_trades_checked"] += x["decision_trades_checked"]
            v2["decision_trade_not_after_decision"] += x["decision_trade_not_after_decision"]
            for k in ("tags_checked", "tag_snapshot_after_info", "events_checked", "event_info_not_before_trade", "event_decision_not_before_trade", "initial_position_tag_reads_asof_T0"):
                v2[k] += x[k]
    v2["violations"] = int(v2["decision_label_after_decision"] + v2["tag_snapshot_after_info"] + v2["event_info_not_before_trade"] + v2["event_decision_not_before_trade"] + v2["decision_trade_not_after_decision"])
    v2["checked"] = int(v2["decisions_checked"] + v2["tags_checked"] + v2["events_checked"] + v2["decision_trades_checked"])
    v2["pass"] = bool(v2["violations"] == 0 and v2["decisions_checked"] > 0 and v2["tags_checked"] > 0 and v2["events_checked"] > 0)
    v3 = {k: v for r in R for k, v in r["v3"].items()}
    v3_ok = bool(all(x["pass"] for w in v3.values() for x in w.values()))
    v5 = {"a_small_case": small, "b_count_equal": int(sum(r["v5"]["count_equal"] for r in R)), "b_count_unequal": int(sum(r["v5"]["count_unequal"] for r in R)),
          "c_rule_in_allowed": int(sum(r["v5"]["rule_in_allowed"] for r in R)), "events_checked": int(sum(r["v5"]["events"] for r in R))}
    v5["pass"] = bool(small["pass"] and v5["b_count_unequal"] == 0 and v5["c_rule_in_allowed"] == v5["events_checked"] > 0)
    (outdir / "v5_counts.json").write_text(json.dumps(v5, indent=1, default=str), encoding="utf-8")

    # audit
    c_ = common()
    s1 = json.loads((T07 / "logs" / "step_1_counts.json").read_text(encoding="utf-8"))
    cmp_ = {}
    for r in R:
        for w, key in (("full", "full"), ("live", "live")):
            mine = r["audit"]["windows"][w]
            coarse = s1["books"][r["book"]][key]
            cmp_[f"{r['book']}|{w}"] = {"engine_events": mine["events"]["events"], "coarse_events_section2": coarse["events"], "engine_le_coarse": bool(mine["events"]["events"] <= coarse["events"]),
                                        "engine_events_in_disagreement_weeks": mine["events_in_disagreement_weeks"], "coarse_in_mixed_weeks": coarse["events_in_mixed_weeks"],
                                        "engine_partial_events": mine["events"]["partial"], "disagreement_stretches": mine["disagreement_stretches"], "coarse_mixed_spells": coarse["mixed_spells"],
                                        "decisions_equal_step1": bool(mine["decisions"] == coarse["weeks"])}
    audit = {"readings": READINGS, "books": {r["book"]: r["audit"] for r in R}, "v2": v2, "v3": {"per_book_window": v3, "pass": v3_ok},
             "v4": {"pass": reg["pass"], "max_rel_diff": reg["max_rel_diff"], "g0": g4}, "v5": {"pass": v5["pass"]},
             "events_vs_section2_coarse_counts": cmp_,
             "data": {"approved_data_as_of": AD.as_of(), "window_end": str(END.date()), "inputs": int(len(USED)), "registered_not_parsed": not_parsed, "non_approved_open_raises": st,
                      "cash_accrued_sessions": 0, "cash_first_appended_row": cash_note(),
                      "goldbees": {"mcx_file_last": str(c_["mcx_last"].date()), "goldbees_file_last": str(c_["gold_data_last"].date()),
                                   "sessions_after_mcx_in_goldbees_file": c_["gold_raw_sessions_in_data"]}},
             "tag_error_r5": {"rate": R5_RATE, "draws_per_book": r5, "source": "data/review/2026-11-12_tag_sources/REVIEW.md check 6: 92.07% agreement"},
             "run": {"name": a.run, "draws": a.draws, "quick": a.quick, "controls": controls, "jobs": jobs, "seconds": round(time.time() - t_start),
                     "seeds": "N4.6 default_rng([7, draw_id, book_no]); N4.8 default_rng([8, draw_id, book_no]); V6 [9, shift_index, book_no]; R5 [5, draw_id, book_no]"}}
    audit["prereg_sha256"] = (T07 / "T07.md").read_text(encoding="utf-8").split("§1–§3 sha256:** `")[1].split("`")[0]
    gates = {"V2": v2["pass"], "V3": v3_ok, "V4": reg["pass"], "V5": v5["pass"], "V6": v6_ok, "V7": v7_ok, "approved_data_selftest": st["pass"]}
    ran = [v for v in gates.values() if v is not None]
    gates["all_that_ran"] = bool(all(ran))
    gates["V6_V7_ran"] = bool(controls)
    audit["gates"] = gates
    (outdir / "audit.json").write_text(json.dumps(audit, indent=1, default=str), encoding="utf-8")

    sg = stats_df[(stats_df["window"] == "full") & (stats_df["cash"] == "lbes") & (stats_df["cost_bps"] == PRIMARY)]
    print(sg[["book", "kind", "cagr", "max_dd", "end_nav", "trades", "events"]].round(4).to_string(index=False))
    print(pd.DataFrame(g4).round(3).to_string(index=False))
    print("events vs coarse:", {k: (v["engine_events"], v["coarse_events_section2"]) for k, v in cmp_.items()})
    print(f"V2 {v2['pass']} ({v2['checked']} checked, {v2['violations']} violations)  V3 {v3_ok}  V4 {reg['pass']} (max rel diff {reg['max_rel_diff']:.2e}, {reg['nav_rows_compared']} series)  V5 {v5['pass']}  V6 {v6_ok}  V7 {v7_ok}")
    print(f"gates: {gates}")
    print(f"done in {time.time() - t_start:.0f}s -> {outdir}")
    sys.exit(0 if gates["all_that_ran"] else 1)


if __name__ == "__main__":
    main()
