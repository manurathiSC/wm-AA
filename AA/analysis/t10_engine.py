# -*- coding: utf-8 -*-
"""T10 engine: the production FS rule (segment_v2.build_production) -- every week tag the parent's stocks, FS = share of held stocks (by count)
whose band's index is BUY; hold the WHOLE parent at its listed weights iff FS >= 0.60 (decided in integers, 5k >= 3n), else 50/50 GOLDBEES and
cash -- compared with hold-the-parent and the three-index switch. NO NULL (Manu's waiver, 2026-11-12).

A FORK of analysis/t07_engine.py (copied, not imported), which is itself a fork of t06_engine.py: the data layer (calendar, prices, baskets, GOLDBEES
fill, cash level), `sim()`'s arithmetic, `stats()` and the per-stock event builder (used only for the descriptive T07 comparator) are copied
unchanged, so that the three-index switch reproduces T06's NAV (gate V3). What is new: the weekly tag read, the FS decision, the whole-book
state events, the R4-R8 reports. Pre-registration: tests/T10/T10.md sections 1-3 (frozen; `python tests/T10/check_prereg.py`); evidence
contract: tests/T10/logs/evidence_contract.md. Every data file is opened through `approved_data.require()`.

    python -I analysis/t10_engine.py --run NAME [--quick] [--r4 N] [--jobs J] [--books B1,B2] [--out-root DIR]      (from AA/)
    python -I analysis/t10_engine.py --rerun --book B --id N --out f.json

Writes tests/T10/evidence/<run>/. Exit code 0 only if every gate that ran passed.
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
from fractions import Fraction
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
T10 = AA / "tests" / "T10"
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
N_R4 = 500
R5_RATE = 0.0793
V6_SHIFTS, V6_DRAWS = 100, 200
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


# ══ T10 starts here: everything above is copied from t07_engine.py without change ═══════════════════════════════════════
N_R4 = 500
R4_RATE = 0.0793
N_BOOT = 1000
THR = {"thr_2/5": Fraction(2, 5), "thr_1/2": Fraction(1, 2), "thr_7/10": Fraction(7, 10), "thr_4/5": Fraction(4, 5)}
FS_THRESHOLD = Fraction(3, 5)
FKINDS_MAIN = ["rule", "switch", "parent", "constant_mix", "sleeve100", "t07_rule"]

READINGS = {
    "T1": "decision at d (every weekly decision, T0 included): basket in force at d = the latest non-skipped basket that has taken effect on or before d (bk.basket_at[decision_idx]); every stock with listed weight > 0 is tagged with tag_lookup.tag(ISIN, d) "
          "(as of the decision date itself); n = stocks held, k = stocks whose band's SIGN is BUY at d; state IN iff 5k >= 3n (integers). Weights are RENORMALISED to 1 per basket as in T06 (T06 E5; T10.md 3 step 6)",
    "T2": "events: T0 (free; state of decision 0); a state event on the session after decision j >= 1 if state[j] differs from the state held; a basket event on the first session on or after a non-skipped basket's availableDate "
          "(Book.basket_events) if the state of the latest decision made before that session is IN; if it is OUT (and no state event) nothing is traded and the basket in force changes (skipped_baskets.csv). The targets at an event use the basket in force at the trade session "
          "(bk.basket_at[session]) and the state of the latest decision made before it; two events on one session are one event",
    "T3": "the three-index switch = the same code with state = all three SIGN BUY; hold the parent = state 1 always; the 100% sleeve = state 0 always (T0 only); the constant mix: f = mean over sessions of (stock value / NAV) of the rule's path at the SAME cost and cash, "
          "stocks f x w_i, half of (1-f) in GOLDBEES and half in cash, rebalanced at every event of the rule (T0 free)",
    "T4": "R5 thresholds: state IN iff k/n >= t as exact fractions (k*den >= num*n); R6 weight_fs: IN iff the listed weight of the stocks on is >= 0.60 - 1e-12; t07_rule (descriptive): T07.md 3 steps 4-7 with the copied event builder (per-stock tags read at events only)",
    "T5": "float_fs_LMS / float_fs_SML: production's float formula, sum over the bands present of (count/n) * (1.0 if SIGN is BUY else 0.0), bands added in the order Large, Mid, Small and in the reverse order; float_differs if either >= 0.60 disagrees with the integer state",
    "T6": "R4 tag error: default_rng([10, draw_id, book_no]); for each weekly decision in order, for each held stock in increasing ISIN string order whose tag source is 'rank' or 'nonmember_rank', two uniforms u1,u2; replace the band iff u1 < 0.0793, by the first of the other two bands (order Large, Mid, Small) if u2 < 0.5 else the second; "
          "membership and unranked tags are not perturbed; events and NAV are rebuilt from the perturbed states; full window, LBES, 20.8 bps",
    "T7": "bootstrap: n = sessions-1 daily log returns; default_rng([11, resample_id, book_no]); starts = rng.integers(0, n-19, size=ceil(n/20)); blocks of 20 consecutive returns, concatenated and cut to n, the same indices for both series; CAGR = exp(sum log r / (n/252)) - 1; "
          "interval = numpy.percentile 2.5 and 97.5 (linear) of 1,000 CAGR differences (rule minus comparator); full window, LBES, 20.8 bps",
    "T8": "R7 stretches: maximal runs of decisions with extra = (rule IN, switch OUT); span from the close of the first decision date to the close of the first decision date after the run (or the window's last session); log returns of the rule and the switch NAVs "
          "(20.8 bps, LBES) over the span; 'without the largest' drops the daily log returns of the span's sessions (start+1 .. end) of the stretch with the largest |diff| from both series and recomputes exp(sum/(n/252))-1",
    "T9": "V5 sample seed default_rng([12, book_no]) over the book's full-window decision_stocks rows is drawn by the verifier; the engine reports tag reads = sum of stocks held over the decisions, per book and window",
    "V2": "V2 counts: decisions with a Master label dated after the decision date; tags with a snapshot after the decision date; events whose decision used is not before the trade session (T0 excepted, counted separately); decision trade dates not after their decision",
    "V3": "V3 compares the switch, parent and 100%-sleeve NAVs with T06's strategy, hold_parent and sleeve_only on every shared session to 2026-10-22 at 0, 20.8 and 50 bps (relative difference < 1e-12), the decisions' state on every shared date, and always-in at 0 cost against the published NAV (G0)",
}


def thr_state(ns: np.ndarray, ks: np.ndarray, t: Fraction) -> np.ndarray:
    return (ks * t.denominator >= t.numerator * ns).astype(np.int8)


class Reads:
    """The weekly tag reads of one window of one book (unperturbed): per decision the basket in force, the held columns (ISIN order), bands, sources, tags."""

    def __init__(self, bk: Book, tagger: Tagger, idx: np.ndarray):
        self.items = []
        for j, i in enumerate(idx):
            b = int(bk.basket_at[i])
            cols = bk.held(b)
            d = bk.cal[i]
            tags = [tagger.get(bk.isin[c], d) for c in cols]
            self.items.append({"b": b, "cols": cols, "w": bk.W[b][cols], "tags": tags,
                               "bands": np.array([BAND_IDX[t["band"]] for t in tags], dtype=np.int8), "src": [t["source"] for t in tags]})

    def arrays(self, S: np.ndarray, perturb: Perturb | None = None):
        """n, k (stocks on), wfs (listed weight on), per-band counts; with a perturbation the bands are the perturbed ones."""
        J = len(self.items)
        n, k, wfs = np.zeros(J, int), np.zeros(J, int), np.zeros(J)
        cnt = np.zeros((J, 3), int)
        bands_out = []
        for j, it in enumerate(self.items):
            bands = it["bands"] if perturb is None else perturb.apply(it["bands"], it["src"])
            bands_out.append(bands)
            on = S[j][bands] == 1
            n[j], k[j], wfs[j] = len(bands), int(on.sum()), float(it["w"][on].sum())
            cnt[j] = np.bincount(bands, minlength=3)
        return n, k, wfs, cnt, bands_out


class Perturb4(Perturb):
    def __init__(self, draw_id: int, book_no: int, rate: float = R4_RATE):
        super().__init__(draw_id, book_no, rate)
        self.rng = np.random.default_rng([10, draw_id, book_no])


def build_state_events(bk: Book, idx: np.ndarray, state: np.ndarray) -> Events:
    """T10.md 3 step 5 / READINGS T2. state[j] in {0, 1} for decision j."""
    T, J = bk.T, len(idx)
    sig_at = {int(idx[j]) + 1: j for j in range(1, J) if int(idx[j]) + 1 < T}

    def mk(k, kind, s, jst, b, st):
        cols = bk.held(b)
        return {"k": k, "kind": kind, "t": s, "jst": jst, "b": b, "cols": cols, "w": bk.W[b][cols], "wraw": bk.Wraw[b][cols],
                "drop": np.full(len(cols), st == 0), "state": int(st)}

    evs = [mk(0, "initial", 0, 0, bk.b0, state[0])]
    cur = int(state[0])
    skipped = []
    for s in sorted(set(sig_at) | bk.basket_events):
        isb = s in bk.basket_events
        jst = int(np.searchsorted(idx, s - 1, side="right") - 1)
        st = int(state[jst])
        trig = st != cur
        if not trig and not isb:
            continue
        b = int(bk.basket_at[s])
        if not trig and st == 0:
            skipped.append({"trade_date": str(bk.cal[s].date()), "basket_eff": str(bk.eff[b].date())})
            continue
        evs.append(mk(len(evs), "state+basket" if (trig and isb) else ("state" if trig else "basket"), s, jst, b, st))
        cur = st
    return Events(evs, skipped, state.astype(float), {}, "state")


def kind_row(book, window, cash, cost, kind, nav, events, trades, cost_paid, invested, extra=None) -> dict:
    return {"book": book, "window": window, "cash": cash, "cost_bps": cost, "kind": kind, **stats(nav), "invested_weeks": invested,
            "trades": trades, "cost_paid": cost_paid, "events": events, **(extra or {})}


def runs_of(flags) -> list:
    """(first, last) index pairs of maximal runs of True."""
    out, a = [], None
    for i, f in enumerate(flags):
        if f and a is None:
            a = i
        if not f and a is not None:
            out.append((a, i - 1)); a = None
    if a is not None:
        out.append((a, len(flags) - 1))
    return out


def cagr_logs(lr: np.ndarray) -> float:
    return float(math.exp(lr.sum() / (len(lr) / 252)) - 1)


def process_book(p: str, cfg: dict) -> dict:
    global CHECK_SHA
    CHECK_SHA = cfg.get("check_sha", False)
    t_start = time.time()
    book_no = PARENTS.index(p)
    tagger = Tagger()
    res = {"book": p, "stats": [], "nav": {}, "trades": [], "dec_rows": [], "dec_stock_rows": [], "events": [], "skipped": [], "stretches": [], "boot": [],
           "r4": [], "audit": {"windows": {}}, "v4x": {}, "v2": {"decisions_checked": 0, "decision_label_after_decision": 0, "tags_checked": 0, "tag_snapshot_after_decision": 0,
                                                              "events_checked": 0, "event_decision_not_before_trade": 0, "t0_events": 0, "decision_trades_checked": 0,
                                                              "decision_trade_not_after_decision": 0}, "v5": {}}
    navs20 = {}
    for window in ("full", "live"):
        bk = Book(p, start=None if window == "full" else LIVE_START)
        dec, S, idx = bk.decisions()
        J = len(idx)
        R = Reads(bk, tagger, idx)
        n, k, wfs, cnt, _ = R.arrays(S)
        rule = np.array([Fraction(int(kk), int(nn)) >= FS_THRESHOLD for kk, nn in zip(k, n)], dtype=np.int8)
        assert ((5 * k >= 3 * n).astype(np.int8) == rule).all()
        switch = S.all(axis=1).astype(np.int8)
        assert (switch == dec["state"].values).all()
        extra = (rule == 1) & (switch == 0)
        tie = 5 * k == 3 * n
        f1, f2 = np.zeros(J), np.zeros(J)
        for j in range(J):
            for order, arr in (((0, 1, 2), f1), ((2, 1, 0), f2)):
                v = 0.0
                for b in order:
                    if cnt[j, b] > 0:
                        v += (cnt[j, b] / n[j]) * (1.0 if S[j][b] == 1 else 0.0)
                arr[j] = v
        fdiff = ((f1 >= 0.60) != (rule == 1)) | ((f2 >= 0.60) != (rule == 1))
        wst = (wfs >= 0.60 - 1e-12).astype(np.int8)
        states = {"rule": rule, "switch": switch, "parent": np.ones(J, np.int8), "sleeve100": np.zeros(J, np.int8), "weight_fs": wst,
                  **{kd: thr_state(n, k, t) for kd, t in THR.items()}}
        Ev = {kd: build_state_events(bk, idx, st) for kd, st in states.items()}
        Ev["t07_rule"] = build_events(bk, idx, S, "seg", tagger)
        # ── tables: decisions, decision_stocks
        for j in range(J):
            r_ = dec.iloc[j]
            it = R.items[j]
            res["dec_rows"].append({
                "book": p, "window": window, "j": j, "decision_date": r_["decision_date"], "decision_idx": int(idx[j]), "trade_date": r_["trade_date"],
                **{c: r_[c] for c in ("sign_Nifty100", "sign_MC100", "sign_SC100", "label_Nifty100", "label_MC100", "label_SC100", "pattern")},
                "basket_eff": bk.eff[it["b"]].date(), "n_held": int(n[j]), "n_large": int(cnt[j, 0]), "n_mid": int(cnt[j, 1]), "n_small": int(cnt[j, 2]),
                "k_on": int(k[j]), "fs": k[j] / n[j], "weight_fs": float(wfs[j]), "state_rule": int(rule[j]), "state_switch": int(switch[j]), "extra": bool(extra[j]),
                "tie": bool(tie[j]), "float_fs_LMS": float(f1[j]), "float_fs_SML": float(f2[j]), "float_differs": bool(fdiff[j]), "state_weight_fs": int(wst[j])})
            for i2, c in enumerate(it["cols"]):
                tg = it["tags"][i2]
                res["dec_stock_rows"].append({"book": p, "window": window, "j": j, "decision_date": r_["decision_date"], "isin": bk.isin[c], "stock": bk.stocks[c],
                                              "listed_weight": float(it["w"][i2]), "band": BANDS[int(it["bands"][i2])], "tag_source": tg["source"], "tag_snapshot": tg["snapshot"],
                                              "tag_detail": tg["detail"], "tag_via": tg["via"], "band_signal": "BUY" if S[j][int(it["bands"][i2])] else "SELL",
                                              "on": bool(S[j][int(it["bands"][i2])] == 1)})
                res["v2"]["tags_checked"] += 1
                if tg["snapshot"] is not None and pd.Timestamp(tg["snapshot"]) > bk.cal[idx[j]]:
                    res["v2"]["tag_snapshot_after_decision"] += 1
        res["v2"]["decisions_checked"] += J
        res["v2"]["decision_label_after_decision"] += int((pd.to_datetime(dec["latest_label"]) > pd.to_datetime(dec["decision_date"])).sum())
        td = pd.to_datetime(dec["trade_date"].dropna())
        dd = pd.to_datetime(dec.loc[dec["trade_date"].notna(), "decision_date"])
        res["v2"]["decision_trades_checked"] += int(len(td))
        res["v2"]["decision_trade_not_after_decision"] += int((td.values <= dd.values).sum())
        res["v5"][window] = {"tag_reads": int(n.sum()), "rows": int(sum(len(it["cols"]) for it in R.items))}
        # ── V4 exact facts
        res["v4x"][window] = {"weeks": J, "rule_out_while_switch_in": int(((rule == 0) & (switch == 1)).sum()),
                              "fs_identity_failures": int((np.abs((k / n) - (cnt * (S == 1)[:, [0, 1, 2]]).sum(axis=1) / n) > 1e-12).sum()),
                              "state_rule_failures": int((rule != np.array([Fraction(int(a), int(b)) >= FS_THRESHOLD for a, b in zip(k, n)], dtype=np.int8)).sum()),
                              "float_differs_weeks": [str(dec["decision_date"].iloc[j]) for j in np.flatnonzero(fdiff)], "tie_weeks": int(tie.sum()),
                              "extra_weeks": int(extra.sum()), "extra_stretches": [b - a + 1 for a, b in runs_of(extra)]}
        # ── events and realisations
        for kd, E in Ev.items():
            for e in E.evs[1:]:
                res["v2"]["events_checked"] += int(kd == "rule")
                res["v2"]["event_decision_not_before_trade"] += int(kd == "rule" and not (int(idx[e["jst"]]) < e["t"]))
            res["v2"]["t0_events"] += int(kd == "rule")
        reals = [("lbes", c) for c in COSTS] if window == "full" else [("lbes", PRIMARY)]
        if window == "full":
            reals.append(("liq", PRIMARY))
        bkc = {"lbes": bk, "liq": Book(p, cash="liq") if window == "full" else None}
        for cash, cost in reals:
            b2 = bkc[cash]
            headline = window == "full" and cash == "lbes"
            full_set = headline and cost == PRIMARY
            kinds = FKINDS_MAIN + (list(THR) + ["weight_fs"] if full_set else [])
            sims = {}
            for kd in kinds:
                if kd == "constant_mix":
                    continue
                E = Ev[kd]
                sims[kd] = sim(b2, E, E.dflat, cost, record=(kd == "rule" or (headline and kd in ("switch", "parent", "sleeve100"))), share=(kd == "rule"))
            f = float(sims["rule"]["share"].mean())
            sims["constant_mix"] = sim(b2, Ev["rule"], None, cost, mix_f=f, record=False)
            for kd in kinds:
                E = Ev["rule" if kd == "constant_mix" else kd]
                inv = float(E.kept_share.sum()) if kd != "constant_mix" else J * f
                res["stats"].append(kind_row(p, window, cash, cost, kd, sims[kd]["nav"], E.n if kd != "constant_mix" else Ev["rule"].n, sims[kd]["trades"],
                                             sims[kd]["cost_paid"], inv, {"mix_share_f": f} if kd == "constant_mix" else None))
            res["stats"].append(kind_row(p, window, cash, cost, "published_parent", b2.pub / b2.pub[0], np.nan, np.nan, np.nan, float(J)))
            if headline:
                for kd in FKINDS_MAIN:
                    res["nav"][(p, cost, kd)] = sims[kd]["nav"]
                for kd in ("rule", "switch", "parent", "sleeve100"):
                    res["trades"] += [{"book": p, "cost_bps": cost, "run": kd, **{a: b for a, b in t.items() if a not in ("stock_no_bar", "gold_raw", "k", "n_dropped")}, "event_no": t["k"]}
                                      for t in sims[kd]["trade_log"]]
            if cash == "lbes" and cost == PRIMARY:
                navs20[window] = {"rule": sims["rule"]["nav"], "switch": sims["switch"]["nav"], "parent": sims["parent"]["nav"], "bk": b2, "idx": idx, "extra": extra,
                                  "fs": k / n, "dec": dec}
                by_k = {t["k"]: t for t in sims["rule"]["trade_log"]}
                for kx, e in enumerate(Ev["rule"].evs):
                    tr = by_k.get(kx)
                    res["events"].append({"book": p, "window": window, "event_no": kx, "kind": e["kind"], "trade_date": bk.cal[e["t"]].date(), "trade_idx": e["t"],
                                          "decision_idx_used": int(idx[e["jst"]]), "decision_date_used": bk.cal[idx[e["jst"]]].date(), "state": "IN" if e["state"] else "OUT",
                                          "basket_eff": bk.eff[e["b"]].date(), "n_held": len(e["cols"]), "V_before": (tr["V"] if tr else 1.0),
                                          "traded": (tr["traded"] if tr else 0.0), "cost": (tr["cost"] if tr else 0.0), "sleeve_share": 0 if e["state"] else 1})
                res["skipped"] += [{"book": p, "window": window, **s} for s in Ev["rule"].skipped]
                if window == "full":
                    gap = {"book": p}
                    res["pub_full"], res["cal_full"] = b2.pub / b2.pub[0], b2.cal
                    res["bk_full"] = (b2, dec)
        if window == "live":
            a = pd.read_csv(ap(d17_path(AA_BOOK[p])))
            s_ = pd.Series(a["index"].values, index=pd.to_datetime(a["_id.date"], format="%Y/%m/%d")).sort_index()
            s_ = s_[(s_.index >= bk.cal[0]) & (s_.index <= bk.cal[-1])].reindex(bk.cal).ffill()
            res["stats"].append(kind_row(p, "live", "lbes", np.nan, "published_aa", s_.values / s_.values[0], np.nan, np.nan, np.nan, np.nan, {"aa_scid": AA_BOOK[p]}))
        # ── audit counts
        flags = dec["disagree"].values if "disagree" in dec else (dec["pattern"].isin(["BBB", "SSS"]) == False).values
        res["audit"]["windows"][window] = {"t0": str(bk.t0.date()), "last_session": str(bk.cal[-1].date()), "sessions": bk.T, "decisions": J,
                                           "initial_basket_switch_session": bk.initial_basket_switch_session, "events": {kd: Ev[kd].counts()["events"] for kd in Ev},
                                           "skipped_basket_events": Ev["rule"].skipped, "extra_stretches": len(runs_of(extra)), "extra_weeks": int(extra.sum()),
                                           "reportable_C3_C4": bool(len(runs_of(extra)) >= 5), "cash": bk.cash_info,
                                           "tag_source_holding_weeks": pd.Series([t["source"] for it in R.items for t in it["tags"]]).value_counts().to_dict()}
        # ── R7 stretches
        nv = navs20[window]
        cal = bk.cal
        lr_r, lr_s = np.diff(np.log(nv["rule"])), np.diff(np.log(nv["switch"]))
        rows7, best, best_abs = [], None, -1.0
        for sn, (a_, b_) in enumerate(runs_of(extra), 1):
            s0 = int(idx[a_])
            e0 = int(idx[b_ + 1]) if b_ + 1 < J else bk.T - 1
            rr, ss = float(np.log(nv["rule"][e0] / nv["rule"][s0])), float(np.log(nv["switch"][e0] / nv["switch"][s0]))
            row = {"book": p, "window": window, "stretch_no": sn, "first_decision_date": dec["decision_date"].iloc[a_], "last_decision_date": dec["decision_date"].iloc[b_],
                   "weeks": b_ - a_ + 1, "mean_fs": float((k / n)[a_:b_ + 1].mean()), "span_start_date": cal[s0].date(), "span_end_date": cal[e0].date(),
                   "rule_log_return": rr, "switch_log_return": ss, "diff_log_return": rr - ss, "_s0": s0, "_e0": e0}
            rows7.append(row)
            if abs(rr - ss) > best_abs:
                best_abs, best = abs(rr - ss), row
        keep = np.ones(len(lr_r), bool)
        if best is not None:
            keep[best["_s0"]:best["_e0"]] = False        # returns of sessions s0+1 .. e0
        res["stretches"] += [{a: b for a, b in r_.items() if not a.startswith("_")} for r_ in rows7]
        res["stretches"].append({"book": p, "window": window, "stretch_no": 0, "weeks": int(extra.sum()),
                                 "cagr_diff_all": cagr_logs(lr_r) - cagr_logs(lr_s),
                                 "cagr_diff_without_largest": (cagr_logs(lr_r[keep]) - cagr_logs(lr_s[keep])) if best is not None else None})
        if window == "full":
            # ── bootstrap
            lr_p = np.diff(np.log(nv["parent"]))
            nret = len(lr_r)
            yrs = nret / 252
            for comp, lr_c in (("switch", lr_s), ("parent", lr_p)):
                diffs = np.empty(N_BOOT)
                for rid in range(N_BOOT):
                    rg = np.random.default_rng([11, rid, book_no])
                    starts = rg.integers(0, nret - 19, size=math.ceil(nret / 20))
                    ix = (starts[:, None] + np.arange(20)).ravel()[:nret]
                    diffs[rid] = math.exp(lr_r[ix].sum() / yrs) - math.exp(lr_c[ix].sum() / yrs)
                res["boot"].append({"book": p, "comparator": comp, "point_cagr_diff": cagr_logs(lr_r) - cagr_logs(lr_c),
                                    "ci_low": float(np.percentile(diffs, 2.5)), "ci_high": float(np.percentile(diffs, 97.5))})
            # ── R4
            bkf = bk
            base_sw = stats(nv["switch"])["cagr"]
            for d in range(cfg["r4"]):
                pt = Perturb4(d, book_no)
                nn, kk, _, _, _ = R.arrays(S, pt)
                st = np.array([Fraction(int(a), int(b)) >= FS_THRESHOLD for a, b in zip(kk, nn)], dtype=np.int8)
                Ed = build_state_events(bkf, idx, st)
                c_ = stats(sim(bkf, Ed, Ed.dflat, PRIMARY)["nav"])["cagr"]
                res["r4"].append({"book": p, "draw_id": d, "cagr": c_, "diff_vs_switch": c_ - base_sw, "weeks_changed": int((st != rule).sum()), "n_decisions": J,
                                  "rank_tag_reads": pt.rank_reads, "flipped": pt.flipped})
    res["v3"] = v3_book(p, res["bk_full"][0], res["bk_full"][1], res)
    res["audit"]["seconds"] = round(time.time() - t_start)
    res["usedfiles"] = USED
    return res


def v3_book(p: str, bk: Book, dec: pd.DataFrame, res: dict) -> dict:
    """V3: the switch (T06's strategy), parent and sleeve100 against T06's evidence; always-in against the published NAV (G0)."""
    t6d = pd.read_csv(T06E / "decisions.csv")
    t6n = pd.read_csv(T06E / "daily_nav.csv")
    b = t6d[t6d["book"] == p]
    a = dec.assign(decision_date=dec["decision_date"].astype(str))[["decision_date", "decision_idx", "state"]]
    m = a.merge(b[["decision_date", "decision_idx", "state"]], on="decision_date", how="inner", suffixes=("", "_t06"))
    mism = int(((m["state"] != m["state_t06"]) | (m["decision_idx"] != m["decision_idx_t06"])).sum())
    out = {"decisions": {"t10_decisions": int(len(a)), "t06_decisions": int(len(b)), "shared": int(len(m)), "mismatches": mism}, "nav": []}
    ok = mism == 0 and len(m) > 0
    names = {"strategy": "switch", "hold_parent": "parent", "sleeve_only": "sleeve100"}
    for (run, cost), g in t6n[(t6n["book"] == p) & t6n["cost_bps"].notna()].groupby(["run", "cost_bps"]):
        if run not in names:
            continue
        g = g.assign(date=pd.to_datetime(g["date"])).set_index("date")["nav"]
        mine = pd.Series(res["nav"][(p, float(cost), names[run])], index=bk.cal)
        cd = g.index[g.index <= T06_NAV_END].intersection(mine.index)
        rel = float((mine.loc[cd] / g.loc[cd] - 1).abs().max())
        passed = bool(len(cd) > 0 and rel < REL_TOL_NAV)
        ok &= passed
        out["nav"].append({"book": p, "t06_run": run, "t10_run": names[run], "cost_bps": float(cost), "dates_compared": int(len(cd)), "max_rel_diff": rel, "pass": passed})
    nav0 = res["nav"][(p, 0.0, "parent")]
    c = pd.DataFrame({"m": nav0, "p": bk.pub}, index=bk.cal)
    c = c / c.iloc[0] * 100
    yrs = (c.index[-1] - c.index[0]).days / 365.25
    gap = ((c.m.iloc[-1] / c.m.iloc[0]) ** (1 / yrs) - (c.p.iloc[-1] / c.p.iloc[0]) ** (1 / yrs)) * 100
    worst, wy = 0.0, None
    for yr, gg in c.groupby(c.index.year):
        prev = c.loc[:gg.index[0]].iloc[-2] if len(c.loc[:gg.index[0]]) > 1 else gg.iloc[0]
        dd_ = (gg["m"].iloc[-1] / prev["m"] - gg["p"].iloc[-1] / prev["p"]) * 100
        if abs(dd_) > abs(worst):
            worst, wy = dd_, int(yr)
    g0 = {"book": p, "cagr_gap_pp_yr": float(gap), "overall": "PASS" if abs(gap) <= G0_OVERALL else "FAIL", "worst_year": wy, "worst_year_gap_pp": float(worst),
          "yearly": "PASS" if abs(worst) <= G0_YEARLY else "FAIL", "window_first": str(c.index[0].date()), "window_last": str(c.index[-1].date())}
    ok &= g0["overall"] == "PASS" and g0["yearly"] == "PASS"
    out["g0"], out["pass"] = g0, bool(ok)
    return out


def rerun(a) -> int:
    global CHECK_SHA
    CHECK_SHA = False
    p = a.book
    book_no = PARENTS.index(p)
    bk = Book(p)
    dec, S, idx = bk.decisions()
    R = Reads(bk, Tagger(), idx)
    n, k, _, _, _ = R.arrays(S)
    base = np.array([5 * kk >= 3 * nn for kk, nn in zip(k, n)], dtype=np.int8)
    sw = stats(sim(bk, (e := build_state_events(bk, idx, S.all(axis=1).astype(np.int8))), e.dflat, PRIMARY)["nav"])["cagr"]
    nn, kk, _, _, _ = R.arrays(S, Perturb4(a.id, book_no))
    st = np.array([5 * x >= 3 * y for x, y in zip(kk, nn)], dtype=np.int8)
    Ed = build_state_events(bk, idx, st)
    c_ = stats(sim(bk, Ed, Ed.dflat, PRIMARY)["nav"])["cagr"]
    Path(a.out).write_text(json.dumps({"cagr": c_, "diff_vs_switch": c_ - sw, "weeks_changed": int((st != base).sum())}), encoding="utf-8")
    print(f"rerun {p} R4 draw {a.id}: cagr {c_:.6f} diff vs switch {c_ - sw:+.6f} -> {a.out}")
    return 0


def main():
    global CHECK_SHA
    ap_ = argparse.ArgumentParser()
    ap_.add_argument("--run", default="headline")
    ap_.add_argument("--quick", action="store_true", help="smoke test: one book (SCMO_0003), R4 with 20 draws")
    ap_.add_argument("--r4", type=int, default=None)
    ap_.add_argument("--jobs", type=int, default=None)
    ap_.add_argument("--books", default=None)
    ap_.add_argument("--out-root", default=None)
    ap_.add_argument("--rerun", action="store_true")
    ap_.add_argument("--book")
    ap_.add_argument("--id", type=int)
    ap_.add_argument("--out")
    a = ap_.parse_args()
    if a.rerun:
        sys.exit(rerun(a))
    outdir = (Path(a.out_root) if a.out_root else T10 / "evidence") / a.run
    outdir.mkdir(parents=True, exist_ok=True)
    t_start = time.time()
    books = a.books.split(",") if a.books else (PARENTS[:1] if a.quick else PARENTS)
    assert all(b in PARENTS for b in books)
    r4 = a.r4 if a.r4 is not None else (20 if a.quick else N_R4)
    jobs = a.jobs if a.jobs is not None else (1 if len(books) == 1 else min(len(books), os.cpu_count() or 1))
    CHECK_SHA = True
    st, not_parsed = check_inputs()
    print(f"data: END = {END.date()}, approved data as of {AD.as_of()}, {len(USED)} inputs checked (sha256); non-approved open raises: {st['pass']}", flush=True)
    cfg = {"r4": r4, "check_sha": False}
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
            print(f"{p}: done in {results[p]['audit']['seconds']}s", flush=True)
    for r in results.values():
        for kx, v in r["usedfiles"].items():
            USED.setdefault(kx, v)
    R = [results[p] for p in books]
    pd.DataFrame([{kx: v[kx] for kx in ("file", "through", "bytes", "sha256", "approved_row")} for v in sorted(USED.values(), key=lambda x: x["file"])]).to_csv(outdir / "inputs.csv", index=False)
    pd.DataFrame([x for r in R for x in r["dec_rows"]]).to_csv(outdir / "decisions.csv", index=False)
    pd.DataFrame([x for r in R for x in r["dec_stock_rows"]]).to_csv(outdir / "decision_stocks.csv", index=False)
    pd.DataFrame([x for r in R for x in r["events"]]).to_csv(outdir / "events.csv", index=False)
    pd.DataFrame([x for r in R for x in r["skipped"]], columns=["book", "window", "trade_date", "basket_eff"]).to_csv(outdir / "skipped_baskets.csv", index=False)
    stats_df = pd.DataFrame([x for r in R for x in r["stats"]])
    stats_df.to_csv(outdir / "stats.csv", index=False)
    pd.DataFrame([x for r in R for x in r["trades"]]).to_csv(outdir / "trades.csv", index=False)
    pd.DataFrame([x for r in R for x in r["stretches"]]).to_csv(outdir / "stretches.csv", index=False)
    pd.DataFrame([x for r in R for x in r["boot"]]).to_csv(outdir / "bootstrap.csv", index=False)
    pd.DataFrame([x for r in R for x in r["r4"]]).to_csv(outdir / "r4_tag_error.csv", index=False)
    daily = []
    for r in R:
        for (b_, cost, name), nv in r["nav"].items():
            daily.append(pd.DataFrame({"book": b_, "date": r["cal_full"], "cost_bps": cost, "run": name, "nav": nv}))
        daily.append(pd.DataFrame({"book": r["book"], "date": r["cal_full"], "cost_bps": np.nan, "run": "published_parent", "nav": r["pub_full"]}))
    pd.concat(daily).to_csv(outdir / "daily_nav.csv", index=False)
    g4 = [r["v3"]["g0"] for r in R]
    pd.DataFrame(g4).to_csv(outdir / "g_engine.csv", index=False)
    reg = {"tolerance_rel": REL_TOL_NAV, "compared_to": str(T06_NAV_END.date()), "books": {r["book"]: r["v3"] for r in R},
           "nav_rows_compared": int(sum(len(r["v3"]["nav"]) for r in R)), "g0": g4, "pass": bool(all(r["v3"]["pass"] for r in R)),
           "max_rel_diff": float(max(x["max_rel_diff"] for r in R for x in r["v3"]["nav"]))}
    (outdir / "regression_t06.json").write_text(json.dumps(reg, indent=1, default=str), encoding="utf-8")
    v4 = {r["book"]: r["v4x"] for r in R}
    v4_ok = bool(all(w["rule_out_while_switch_in"] == 0 and w["fs_identity_failures"] == 0 and w["state_rule_failures"] == 0 for b_ in v4.values() for w in b_.values()))
    (outdir / "v4_exact.json").write_text(json.dumps({"books": v4, "pass": v4_ok}, indent=1, default=str), encoding="utf-8")
    v2 = {kx: int(sum(r["v2"][kx] for r in R)) for kx in R[0]["v2"]}
    v2["violations"] = int(v2["decision_label_after_decision"] + v2["tag_snapshot_after_decision"] + v2["event_decision_not_before_trade"] + v2["decision_trade_not_after_decision"])
    v2["checked"] = int(v2["decisions_checked"] + v2["tags_checked"] + v2["events_checked"] + v2["decision_trades_checked"])
    v2["pass"] = bool(v2["violations"] == 0 and v2["decisions_checked"] > 0 and v2["tags_checked"] > 0 and v2["events_checked"] > 0)
    v5 = {r["book"]: r["v5"] for r in R}
    v5_ok = bool(all(w["tag_reads"] == w["rows"] > 0 for b_ in v5.values() for w in b_.values()))
    c_ = common()
    audit = {"readings": READINGS, "books": {r["book"]: r["audit"] for r in R}, "v2": v2, "v3": {"pass": reg["pass"], "max_rel_diff": reg["max_rel_diff"], "g0": g4},
             "v4": {"pass": v4_ok}, "v5": {"per_book_window": v5, "pass": v5_ok},
             "data": {"approved_data_as_of": AD.as_of(), "window_end": str(END.date()), "inputs": int(len(USED)), "registered_not_parsed": not_parsed, "non_approved_open_raises": st,
                      "cash_first_appended_row": cash_note(), "goldbees": {"mcx_file_last": str(c_["mcx_last"].date()), "sessions_after_mcx_in_goldbees_file": c_["gold_raw_sessions_in_data"]}},
             "tag_error_r4": {"rate": R4_RATE, "draws_per_book": r4, "source": "data/review/2026-11-12_tag_sources/REVIEW.md check 6: 92.07% agreement"},
             "run": {"name": a.run, "quick": a.quick, "jobs": jobs, "seconds": round(time.time() - t_start),
                     "seeds": "R4 default_rng([10, draw_id, book_no]); bootstrap [11, resample_id, book_no]; V5 sample [12, book_no] (verifier)"}}
    audit["prereg_sha256"] = (T10 / "T10.md").read_text(encoding="utf-8").split("§1–§3 sha256:** `")[1].split("`")[0]
    gates = {"V2": v2["pass"], "V3": reg["pass"], "V4": v4_ok, "V5": v5_ok, "approved_data_selftest": st["pass"]}
    gates["all_that_ran"] = bool(all(gates.values()))
    audit["gates"] = gates
    (outdir / "audit.json").write_text(json.dumps(audit, indent=1, default=str), encoding="utf-8")
    sg = stats_df[(stats_df["window"] == "full") & (stats_df["cash"] == "lbes") & (stats_df["cost_bps"] == PRIMARY) & stats_df["kind"].isin(FKINDS_MAIN)]
    print(sg[["book", "kind", "cagr", "max_dd", "calmar", "end_nav", "trades", "events", "invested_weeks"]].round(4).to_string(index=False))
    print(pd.DataFrame(g4).round(3).to_string(index=False))
    print(f"V2 {v2['pass']} ({v2['checked']} checked, {v2['violations']} violations)  V3 {reg['pass']} (max rel diff {reg['max_rel_diff']:.2e}, {reg['nav_rows_compared']} series)  V4 {v4_ok}  V5 {v5_ok}")
    print(f"gates: {gates}")
    print(f"done in {time.time() - t_start:.0f}s -> {outdir}")
    sys.exit(0 if gates["all_that_ran"] else 1)


if __name__ == "__main__":
    main()
