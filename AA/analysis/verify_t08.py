"""T08 independent verifier (Step 3).

Re-derives T08's decisions (index and MAUc1 gold signal), NAVs, costs, trades, sleeve trades, positions and null-draw
results from the RAW files only (plain numpy / pandas, its own loaders, its own cost, basket, counting and percentile
code) and compares them with the engine's evidence in tests/T08/evidence/<run>/.

It imports nothing from the engine or from any other module in analysis/ or data/. It never reads the engine's source.
The rules are those of tests/T08/T08.md sections 1-3 (frozen), tests/T08/PLAN.md and tests/T08/logs/evidence_contract.md;
the conventions are T06's (tests/T06/logs/verifier_spec.md) except where the T08 spec differs. Forked from verify_t06.py.
Its own spec, in its own words: tests/T08/logs/verifier_spec.md.

Usage (from AA/):
    python analysis/verify_t08.py                                  # real run + self-test on a corrupted copy
    python analysis/verify_t08.py --evidence DIR --no-selftest     # compare against another evidence dir
    python analysis/verify_t08.py --evidence DIR --draws 30        # a short run (mock / smoke) with 30 draws per group
    python analysis/verify_t08.py --out FILE

Exit code 0 only if rows were compared, none failed, none were missing, and (in the default run) every deliberate
corruption of a copy of the evidence was detected. A missing evidence file is reported as MISSING (a failure).
"""
import argparse
import hashlib
import json
import math
import re
import shutil
import sys
import tempfile
import time
import traceback
import zlib
from fractions import Fraction
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

AA = Path(__file__).resolve().parents[1]
BOOKS = ["SCMO_0003", "SCMO_0007", "SCMO_0010", "SCMO_0029"]
COSTS = [0.0, 20.8, 50.0]
HEADLINE_COST = 20.8
TOL = 1e-9                  # relative tolerance on NAVs and statistics
TOL_REGRESSION = 1e-12      # T06 overlap (fixed 50/50 sleeve)
TOL_CURVE = 1e-5            # float32 draw curves
N_DRAWS = 2000              # draws per row group (--draws overrides, for short runs)
LIVE_START = pd.Timestamp("2021-11-01")
T06_CUTOFF = pd.Timestamp("2026-10-22")      # T06's last session
G0_OVERALL_PP = 0.25
G0_YEAR_PP = 0.5
LO = 2                      # lower bound of every N4.10 / N4.10-g spell, weeks
GW_BUY, GW_SELL, GW_FIX = 0.8, 0.2, 0.5
# bounds the spec fixes (T08.md section 2); the verifier derives its own from the raw series and requires equality
EXPECT_BOUNDS = dict(io=dict(lo=2, hi_in=46, hi_out=40), gold=dict(lo_buy=2, hi_buy=68, lo_sell=2, hi_sell=28))
SEEDS = dict(n49=[3], n410=[6], n49g=[11, 3], n410g=[11, 6])     # seed = list + [draw_id]
T06_EVIDENCE = AA / "tests" / "T06" / "evidence" / "headline"
STEP1_JSON = AA / "tests" / "T08" / "logs" / "step_1_spell_counts.json"
APPROVED_MD = AA / "data" / "APPROVED_DATA.md"
# approved rows whose through-date is deliberately earlier than the window's end (APPROVED_DATA.md "Latest usable date by role"):
# D12 de-spike range (later fills use the raw OHLC4), D19 / D05 basket weights and rebalance history (the newest baskets that exist;
# the last one stays in force to the window's end).
THROUGH_EXEMPT_IDS = {"D12", "D19", "D05"}
# null families (T08.md section 2): io null, gold null
FAMILY = {"F1": ("N4.10", "real"), "F2": ("N4.9", "real"), "F3": ("real", "N4.10-g"), "F4": ("real", "N4.9-g"), "F5": ("N4.10", "N4.10-g")}
STAT_COLS_ALL = ["end_nav", "cagr", "max_dd", "vol", "ulcer", "days_below_10pct", "longest_underwater", "calmar", "sessions"]
RUN_KINDS = ["strategy", "strategy_fixed50", "hold_parent", "constant_mix", "constant_mix_timed", "sleeve_only", "sleeve_only_timed"]


def norm_path(s):
    s = str(s).strip().replace("\\", "/")
    return s[2:] if s.startswith("./") else s


def parse_approved(md_path=APPROVED_MD):
    txt = Path(md_path).read_text(encoding="utf-8")
    a = txt.index("<!-- approved-table:start -->")
    b = txt.index("<!-- approved-table:end -->")
    rows = {}
    for line in txt[a:b].splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        parts = [p.strip() for p in line.strip("|").split("|")]
        if len(parts) < 5 or parts[0] not in ("APPROVED", "SUPERSEDED", "PENDING"):
            continue
        rows[norm_path(parts[2])] = dict(status=parts[0], id=parts[1], file=parts[2], through=parts[3], sha=parts[4].lower(),
                                         note="|".join(parts[5:]))
    return rows



APPROVED = parse_approved()
READS = {}          # relative path -> sha256 (full) of every file this verifier read
_SHA_CACHE = {}


def sha256_file(p):
    p = Path(p)
    key = str(p)
    if key not in _SHA_CACHE:
        h = hashlib.sha256()
        with open(p, "rb") as f:
            for blk in iter(lambda: f.read(1 << 20), b""):
                h.update(blk)
        _SHA_CACHE[key] = h.hexdigest()
    return _SHA_CACHE[key]

def rd(rel):
    """Register a read of an AA-relative path; refuse anything that is not an APPROVED row."""
    key = norm_path(rel)
    row = APPROVED.get(key)
    if row is None:
        raise RuntimeError(f"file not in APPROVED_DATA.md: {rel}")
    if row["status"] != "APPROVED":
        raise RuntimeError(f"file is {row['status']} in APPROVED_DATA.md: {rel}")
    READS[key] = None
    return AA / rel



# ----------------------------------------------------------------------------------------
# raw loaders (the T06 ones are copied below; these differ: extended published NAVs, the MAUc1 Master, END from D03)
# ----------------------------------------------------------------------------------------
def _read_nav(rel):
    d = pd.read_csv(rd(rel))
    d["date"] = pd.to_datetime(d["_id.date"], format="%Y/%m/%d")
    return d.set_index("date")["index"].sort_index()


def load_published_nav(p):
    """Extended D17 (columns _id.scid, _id.date, index; newest first on disk; sorted here)."""
    return _read_nav(f"Historical Data/extended_2026-11-06/published_nav/{p}.csv")


def load_published_nav_old(p):
    return _read_nav(f"Historical Data/parent_nav_2026-10-22/{p}.csv")


def _read_master(rel):
    m = pd.read_excel(rd(rel))
    m = m[["Date", "SIGN"]].copy()
    m["SIGN"] = m["SIGN"].astype("object")
    m = m[m["SIGN"].notna()]
    m["SIGN"] = m["SIGN"].astype(str).str.strip().str.upper()
    m = m[m["SIGN"] != ""]
    m["Date"] = pd.to_datetime(m["Date"])
    m = m.sort_values("Date").reset_index(drop=True)
    assert set(m["SIGN"]) <= {"BUY", "SELL"}, (rel, set(m["SIGN"]))
    return m["Date"].values, m["SIGN"].values


def load_masters():
    return {name: _read_master(f"Historical Data/extended_2026-10-30/Master/Master_{name}.xlsx") for name in ["Nifty100", "MC100", "SC100"]}


def load_mauc1_master():
    return _read_master("Historical Data/extended_2026-11-06/MAUc1/Master_MAUc1.xlsx")


def load_mauc1_weekly():
    w = pd.read_csv(rd("Historical Data/extended_2026-11-06/MAUc1/mauc1_supertrend_weekly_extended.csv"))
    w["review"] = pd.to_datetime(w["review"])
    w["SIGN"] = w["SIGN"].astype(str).str.strip().str.upper()
    return w.sort_values("review").reset_index(drop=True)


def window_end(masters):
    """END = the last row of the approved index signals (D03): the three Masters' last dates (they must agree)."""
    ends = {nm: pd.Timestamp(dates[-1]) for nm, (dates, _) in masters.items()}
    assert len(set(ends.values())) == 1, ends
    return list(ends.values())[0]


def load_gold():
    g = pd.read_parquet(rd("analysis/cache/why_gold_ohlc_eikon_extended_2026-11-04.parquet"))
    g = g[["date", "open", "high", "low", "close"]].copy()
    g["date"] = pd.to_datetime(g["date"]).dt.normalize()
    g = g.set_index("date").sort_index()
    m = pd.read_csv(rd("analysis/evidence/final_strategy/mauc1/mauc1_daily_clean.csv"))
    m = m.rename(columns={m.columns[0]: "date"})
    m["date"] = pd.to_datetime(m["date"]).dt.normalize()
    m = m.set_index("date").sort_index()
    return g, m


def despiked_goldbees_fill(g, m):
    """Fill = de-spiked OHLC4 where the MCX file has a bar (band = MCX range + 0.5%); the RAW OHLC4 where it has none
    (every session after the MCX file's last date): no clipping, no scaling, no +0.5%."""
    rng = ((m["high"] - m["low"]) / m["close"]).reindex(g.index)
    band = rng + 0.005
    lo = g["close"] * (1 - band)
    hi = g["close"] * (1 + band)
    o2 = g["open"].clip(lower=lo, upper=hi)
    h2 = np.minimum(g["high"], hi)
    l2 = np.maximum(g["low"], lo)
    h2 = np.maximum(np.maximum(h2, o2), g["close"])
    l2 = np.minimum(np.minimum(l2, o2), g["close"])
    have = rng.notna()
    o_ = g["open"].where(~have, o2)
    h_ = g["high"].where(~have, h2)
    l_ = g["low"].where(~have, l2)
    fill = (o_ + h_ + l_ + g["close"]) / 4.0
    return fill, g["close"], m.index[-1]

def load_lbes():
    d = pd.read_csv(rd("Historical Data/LBES_Adjusted_Price_data_extended_2026-11-05.csv"))
    d["date"] = pd.to_datetime(d["date"], format="%d/%m/%y %H:%M").dt.normalize()
    return d.set_index("date")["price"].sort_index()


def load_liquidcase():
    d = pd.read_csv(rd("Historical Data/liquidEtfFinal_extended_2026-11-05.csv"))
    d["date"] = pd.to_datetime(d["date"], format="%d-%m-%Y").dt.normalize()
    return d.set_index("date")[d.columns[1]].sort_index()


def asof_levels(cal, series, name):
    """As-of level on every session; the series must reach the last session (no accrual beyond the file)."""
    assert series.index[-1] >= cal[-1], f"{name}: the file ends {series.index[-1].date()} before the last session {cal[-1].date()}"
    assert series.index[0] <= cal[0], f"{name}: the file starts after the first session"
    lv = series.reindex(cal, method="ffill").values.astype(float)
    assert not np.isnan(lv).any(), f"{name}: NaN level on a session"
    return lv

def load_corrections():
    c = pd.read_csv(rd("data/holdings_matrix/price_corrections.csv"))
    c["ex_date"] = pd.to_datetime(c["ex_date"])
    return c


def load_book_prices(p, corr):
    o = pd.read_csv(rd(f"data/holdings_matrix/{p}_ohlc.csv"), usecols=["date", "stock", "open", "high", "low", "close"])
    o["date"] = pd.to_datetime(o["date"])
    for _, r in corr.iterrows():
        books = [x.strip() for x in str(r["applies_to"]).replace(";", ",").split(",")]
        if p in books:
            msk = (o["stock"] == r["stock"]) & (o["date"] < r["ex_date"])
            for c in ["open", "high", "low", "close"]:
                o.loc[msk, c] = o.loc[msk, c] * float(r["factor"])
    o = o[o["close"].notna()]
    d18 = pd.DatetimeIndex(sorted(o["date"].unique()))
    W = {c: o.pivot(index="date", columns="stock", values=c).reindex(d18) for c in ["open", "high", "low", "close"]}
    close_ff = W["close"].ffill()
    ohlc4 = (W["open"] + W["high"] + W["low"] + W["close"]) / 4.0
    all4 = W["open"].notna() & W["high"].notna() & W["low"].notna() & W["close"].notna()
    bar = W["close"].notna()
    fill = ohlc4.where(all4, W["close"])        # a blank open/high/low -> the close
    fill = fill.where(bar, close_ff)             # no bar that session -> the last close
    return d18, close_ff, fill


def load_baskets(p):
    m = pd.read_csv(rd(f"data/holdings_matrix/{p}_holding_weight_matrix.csv"))
    m = m.rename(columns={m.columns[0]: "avail"})
    m["avail"] = pd.to_datetime(m["avail"])
    s = pd.read_csv(rd(f"data/holdings_matrix/{p}_holding_weight_sources.csv"))
    s["rebalance_date"] = pd.to_datetime(s["rebalance_date"])
    skipped = set(s.loc[s["source"] == "csv_only_skipped", "rebalance_date"])
    dropped = sorted(skipped)
    m = m[~m["avail"].isin(skipped)].sort_values("avail").reset_index(drop=True)
    cols = [c for c in m.columns if c != "avail"]
    W = m[cols].fillna(0.0).values.astype(float)
    W = W / W.sum(axis=1, keepdims=True)
    return m["avail"].values, cols, W, [str(pd.Timestamp(x).date()) for x in dropped]


def touch_other_approved_inputs(p):
    """Files the spec lists as unchanged inputs that carry no number used here (column map, rebalance history; the skipped
    baskets are read from the weight-sources file): register them so that C-data checks their approval, sha256 and through-date."""
    rd(f"data/holdings_matrix/{p}_columns.csv")
    rd(f"Historical Data/frozen_2026-09-25/Rebalance_history/Rebalance_history_by_scid_{p}.csv")



# ----------------------------------------------------------------------------------------
# book construction and windows
# ----------------------------------------------------------------------------------------
def build_book(p, gold_fill, gold_close, mcx_last, lbes, liq, corr, end):
    nav = load_published_nav(p)
    t0 = nav.index[0]
    cal_full = nav.index[(nav.index >= t0) & (nav.index <= pd.Timestamp(end))]     # D17 dates, nothing after END
    n_full = len(cal_full)
    assert cal_full[-1] == pd.Timestamp(end), (p, cal_full[-1], end)
    d18, close_ff, fill = load_book_prices(p, corr)
    avail, cols, Wm, dropped = load_baskets(p)
    touch_other_approved_inputs(p)
    S_cols = [c for c, any_ in zip(cols, (Wm > 0).any(axis=0)) if any_]
    ci = [cols.index(c) for c in S_cols]
    Wm = Wm[:, ci]
    missing_cols = [c for c in S_cols if c not in close_ff.columns]
    assert not missing_cols, (p, missing_cols)
    Cff = close_ff[S_cols]
    Ffl = fill[S_cols]
    miss_dates = [d for d in cal_full if d not in Cff.index]
    assert not miss_dates, (p, miss_dates[:3])
    C = Cff.reindex(cal_full).values
    F = Ffl.reindex(cal_full).values
    Cn = np.nan_to_num(C, nan=0.0)
    gclose = gold_close.reindex(cal_full, method="ffill").values
    gfill = gold_fill.reindex(cal_full).values
    gfill = np.where(np.isnan(gfill), gclose, gfill)
    L = asof_levels(cal_full, lbes, "LBES")
    L2 = asof_levels(cal_full, liq, "LIQUIDCASE")
    raw_after_mcx = int(np.sum(cal_full > mcx_last))
    eff = np.searchsorted(cal_full.values, avail, side="left")      # first session on or after availableDate
    basket_at = {}
    for k in range(len(avail)):
        if eff[k] < n_full:
            basket_at[int(eff[k])] = k           # a later availableDate with the same effect session overrides
    return dict(p=p, t0=t0, cal=cal_full, n_full=n_full, S=S_cols, C=C, Cn=Cn, F=F, gc=gclose, gf=gfill, L=L, L2=L2,
                W=Wm, basket_at_full=basket_at, avail=avail, d18=d18, Ffl=Ffl, dropped=dropped, pub=nav,
                raw_gold_sessions=raw_after_mcx, mcx_last=pd.Timestamp(mcx_last))


def make_view(B, a, b, cash="lbes"):
    """Slice of book B on sessions [a, b); session a is the window's T0 (NAV 1.000 at its close)."""
    full = B["basket_at_full"]
    rel = {k - a: v for k, v in full.items() if k < b}
    keys = sorted(rel)
    k_t0 = max(k for k in keys if k <= 0)
    k0 = rel[k_t0]
    first_d18 = B["d18"][np.searchsorted(B["d18"].values, B["avail"][k0], side="left")]
    return dict(p=B["p"], cal=B["cal"][a:b], n=b - a, a=a, S=B["S"], C=B["C"][a:b], Cn=B["Cn"][a:b], F=B["F"][a:b],
                gc=B["gc"][a:b], gf=B["gf"][a:b], L=(B["L"] if cash == "lbes" else B["L2"])[a:b], W=B["W"],
                basket_at=rel, b_idx=keys, changes=[k for k in keys if 0 < k < b - a], k0=k0,
                init_fill=B["Ffl"].loc[first_d18].values, first_d18=first_d18, mcx_last=B["mcx_last"])


def _asof(dates, sg, d):
    pos = int(np.searchsorted(dates, np.datetime64(d), side="right") - 1)
    assert pos >= 0, d
    return sg[pos], pd.Timestamp(dates[pos])


def decisions_for_window(B, a, b, window, masters, gmaster):
    """Decision dates: the window's T0, then the last session of each later ISO week. Evidence column layout, plus the MAUc1 columns.
    Every Master (the three indices and MAUc1) is read as-of: the latest row dated on or before the decision date."""
    cal = B["cal"][a:b]
    t0 = cal[0]
    iso = cal.isocalendar()
    key = iso["year"].astype(int).values * 100 + iso["week"].astype(int).values
    df = pd.DataFrame({"date": cal, "key": key, "idx": np.arange(len(cal))})
    last = df.groupby("key").tail(1)
    last = last[last["date"] > t0]
    dec_idx = np.array(sorted(set([0] + last["idx"].values.tolist())))
    rows = []
    names = ["Nifty100", "MC100", "SC100"]
    for j, ix in enumerate(dec_idx):
        d = cal[ix]
        signs, labels = [], []
        for nm in names:
            dates, sg = masters[nm]
            s_, l_ = _asof(dates, sg, d)
            signs.append(s_); labels.append(l_)
        gs, gl = _asof(gmaster[0], gmaster[1], d)
        latest = max(labels)
        buy = all(s == "BUY" for s in signs)
        trade = cal[ix + 1] if ix + 1 < len(cal) and j < len(dec_idx) - 1 else None
        g = 1 if gs == "BUY" else 0
        rows.append(dict(book=B["p"], window=window, j=j, decision_date=str(d.date()), decision_idx=int(ix),
                         trade_date=None if trade is None else str(trade.date()),
                         sign_Nifty100=signs[0], sign_MC100=signs[1], sign_SC100=signs[2],
                         label_Nifty100=str(labels[0].date()), label_MC100=str(labels[1].date()), label_SC100=str(labels[2].date()),
                         latest_label=str(latest.date()), label_age_days=int((d - latest).days),
                         all_three_buy=bool(buy), state=int(buy),
                         sign_MAUc1=gs, label_MAUc1=str(gl.date()), g=g, gw=GW_BUY if g == 1 else GW_SELL))
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------------------------
# the simulation
# ----------------------------------------------------------------------------------------
def build_switches(states, gws, dec_idx, mix_f, e_fixed):
    """Session index -> (e_new, gw_new, kind, decision j) for every scheduled trade.
    strategy : a trade exists at decision j (traded on the next session) iff the equity target changes, or the target stays 0 and the
               sleeve's gold weight changes; the last decision is made, not traded.  A change of g while IN is not a trade.
    mix      : every decision but the last (rebalance to e = f, gold weight gws[j] of the non-stock share).
    e_fixed=0: the 100% sleeve; trades only when the gold weight changes.  e_fixed=1: none."""
    D = len(states)
    sw = {}
    if mix_f is not None:
        for j in range(0, D - 1):
            sw[int(dec_idx[j]) + 1] = (float(mix_f), float(gws[j]), "mix_rebalance", j)
    elif e_fixed is not None:
        if float(e_fixed) == 0.0:
            gw_t = float(gws[0])
            for j in range(1, D - 1):
                if float(gws[j]) != gw_t:
                    sw[int(dec_idx[j]) + 1] = (0.0, float(gws[j]), "sleeve_rebalance", j)
                    gw_t = float(gws[j])
    else:
        e_t = int(states[0])
        gw_t = float(gws[0])
        for j in range(1, D - 1):
            if int(states[j]) != e_t:
                e_t = int(states[j])
                gw_t = float(gws[j])
                sw[int(dec_idx[j]) + 1] = (float(e_t), gw_t, "switch_in" if e_t == 1 else "switch_out", j)
            elif e_t == 0 and float(gws[j]) != gw_t:
                gw_t = float(gws[j])
                sw[int(dec_idx[j]) + 1] = (0.0, gw_t, "sleeve_rebalance", j)
    return sw


def simulate(V, states, bps, dec_idx, gws, mix_f=None, e_fixed=None, closed_form=False, positions=False):
    """One realisation on view V (sessions 0..n-1).

    states : decision states s_0..s_(D-1); dec_idx : the decisions' session indices in V; gws : the gold weight of the sleeve
             at every decision (0.8 / 0.2 from the MAUc1 signal, or 0.5 throughout for the fixed 50/50 sleeve)
    mix_f  : constant mix comparator (e = f, rebalance at every decision's next session and at every basket change)
    e_fixed: hold-the-parent (1) or sleeve only (0) at every decision"""
    n = V["n"]
    C, Cn, F = V["C"], V["Cn"], V["F"]
    gc, gf, L = V["gc"], V["gf"], V["L"]
    S = len(V["S"])
    b_idx = V["b_idx"]
    W = V["W"]
    basket_at = V["basket_at"]
    gws = np.asarray(gws, dtype=float)
    assert len(gws) == len(states)

    def basket_key(i):
        return b_idx[np.searchsorted(b_idx, i, side="right") - 1]

    w0 = W[V["k0"]]
    sh0 = np.where(w0 > 0, w0 / V["init_fill"], 0.0)
    sh0 = sh0 / float((sh0 * Cn[0]).sum())
    if mix_f is not None:
        e = float(mix_f)
    elif e_fixed is not None:
        e = float(e_fixed)
    else:
        e = float(states[0])
    gw_cur = float(gws[0])
    shares = sh0 * e if e > 0 else np.zeros(S)
    gu = (1 - e) * gw_cur / gc[0]                 # the initial position is free; the sleeve is split at gw_0
    cu = (1 - e) * (1 - gw_cur) / L[0]

    sw = build_switches(states, gws, dec_idx, mix_f, e_fixed)
    chg = [i for i in V["changes"] if i < n]
    events = sorted(set(k for k in sw if k < n) | set(chg))

    segs = [(0, shares.copy(), gu, cu)]
    trades = []
    for i in events:
        w = W[basket_at[basket_key(i)]]
        pf = F[i]
        if i in sw:
            e_new, gw_new, kind, jdec = sw[i]
        else:
            e_new, gw_new, kind, jdec = e, gw_cur, "basket_change", None
            if e <= 0.0:
                continue      # basket change while OUT: nothing traded
        held = shares != 0
        tgt_stock = e_new * 1.0 * w            # scaled by the value below
        need = (tgt_stock > 0) | held
        if np.isnan(pf[need]).any():
            raise RuntimeError(f"missing fill price for a needed stock at {V['cal'][i]}")
        cur_stock = np.where(held, shares * np.where(np.isnan(pf), 0.0, pf), 0.0)
        cur_g = gu * gf[i]
        cur_c = cu * L[i]
        Vv = cur_stock.sum() + cur_g + cur_c
        tgt_stock = e_new * Vv * w
        tgt_g = (1 - e_new) * gw_new * Vv
        tgt_c = (1 - e_new) * (1 - gw_new) * Vv
        traded = np.abs(tgt_stock - cur_stock).sum() + abs(tgt_g - cur_g) + abs(tgt_c - cur_c)
        cost = traded * bps / 2.0 / 10000.0
        f = (Vv - cost) / Vv
        shares = np.where(tgt_stock > 0, tgt_stock * f / np.where(np.isnan(pf), 1.0, pf), 0.0)
        gu = tgt_g * f / gf[i]
        cu = tgt_c * f / L[i]
        gw_before = gw_cur
        e = e_new
        gw_cur = gw_new
        segs.append((i, shares.copy(), gu, cu))
        trades.append(dict(idx=i, date=str(V["cal"][i].date()), kind=kind, e_after=e, gw_after=gw_new,
                           basket_eff=str(V["cal"][basket_key(i)].date()) if basket_key(i) >= 0 else None,
                           V=Vv, traded=traded, cost=cost, j=jdec, gw_before=gw_before,
                           gold_before=cur_g, cash_before=cur_c, gold_after=tgt_g * f, cash_after=tgt_c * f,
                           raw_fill=bool(V["cal"][i] > V["mcx_last"])))

    nav = np.empty(n)
    seg_end = [s[0] for s in segs[1:]] + [n]
    closed_max_rel = 0.0
    prod = 1.0
    prev_end_val = None
    for (i0, sh, gu_, cu_), i1 in zip(segs, seg_end):
        nz = sh != 0
        if np.isnan(C[i0:i1][:, nz]).any():
            raise RuntimeError("held stock without a close")
        v = Cn[i0:i1] @ sh + gc[i0:i1] * gu_ + L[i0:i1] * cu_
        nav[i0:i1] = v
        if closed_form:
            growth = np.empty(len(v)); growth[0] = 1.0
            if len(v) > 1:
                growth[1:] = v[1:] / v[:-1]
            recon = v[0] * np.cumprod(growth)
            closed_max_rel = max(closed_max_rel, float(np.max(np.abs(recon - v) / np.abs(v))))
            jump = 1.0 if prev_end_val is None else v[0] / prev_end_val
            prod *= jump * (v[-1] / v[0])
            prev_end_val = v[-1]
    for k, t in enumerate(trades):
        t["nav_close_after"] = float(nav[t["idx"]])
    out = dict(nav=nav, trades=trades, closed_rel=closed_max_rel, n_segments=len(segs), end_from_segments=prod if closed_form else np.nan)
    if positions:
        pos = []
        for (i0, sh, gu_, cu_), t in zip(segs[1:], trades):
            for nm, u in zip(V["S"], sh):
                if u != 0:
                    pos.append((t["date"], nm, float(u)))
            pos.append((t["date"], "GOLDBEES", float(gu_)))
            pos.append((t["date"], "LBES", float(cu_)))
        out["positions"] = pos
    return out


def stats_of(nav):
    n = len(nav)
    years = (n - 1) / 252.0
    cagr = nav[-1] ** (1.0 / years) - 1.0
    peak = np.maximum.accumulate(nav)
    dd = nav / peak - 1.0
    mdd = float(np.min(dd))
    ret = nav[1:] / nav[:-1] - 1.0
    vol = float(np.std(ret, ddof=1) * np.sqrt(252.0))
    ulcer = float(np.sqrt(np.mean((100.0 * dd) ** 2)))
    below10 = int(np.sum(dd <= -0.10))
    under = dd < 0
    longest, cur = 0, 0
    for u in under:
        cur = cur + 1 if u else 0
        longest = max(longest, cur)
    calmar = float(cagr / abs(mdd)) if mdd != 0 else float("nan")
    return dict(end_nav=float(nav[-1]), cagr=float(cagr), max_dd=mdd, vol=vol, ulcer=ulcer, days_below_10pct=below10,
                longest_underwater=int(longest), calmar=calmar, sessions=int(n))


STAT_COLS = ["end_nav", "cagr", "max_dd", "vol", "ulcer", "days_below_10pct", "longest_underwater", "calmar", "sessions"]

def runs_of(s):
    out = []
    start = 0
    for i in range(1, len(s) + 1):
        if i == len(s) or s[i] != s[start]:
            out.append((int(s[start]), i - start))
            start = i
    return out



# ----------------------------------------------------------------------------------------
# spells, nulls, counting
# ----------------------------------------------------------------------------------------
def n49_states(s, seed_base, draw_id):
    """N4.9 / N4.9-g: shuffle the spells of value 1 among themselves, then the spells of value 0 among themselves, with
    numpy.random.default_rng(seed_base + [draw_id]) (rng.permutation, 1-spells first), and interleave starting in s[0]'s state."""
    runs = runs_of(s)
    ones = [l for v, l in runs if v == 1]
    zeros = [l for v, l in runs if v == 0]
    rng = np.random.default_rng(list(seed_base) + [int(draw_id)])
    p1 = rng.permutation(len(ones))
    p0 = rng.permutation(len(zeros))
    ones2 = [ones[k] for k in p1]
    zeros2 = [zeros[k] for k in p0]
    cur = int(s[0])
    i1 = i0 = 0
    out = []
    for r in range(len(runs)):
        st = cur if r % 2 == 0 else 1 - cur
        if st == 1:
            out.extend([1] * ones2[i1]); i1 += 1
        else:
            out.extend([0] * zeros2[i0]); i0 += 1
    return np.array(out, dtype=np.uint8)


def ways_table(k, S, lo, hi):
    """c[m][t] = number of ways to write t as m integers in [lo, hi] (plain DP over Python integers; the cross-check of n_ways)."""
    c = [[0] * (S + 1) for _ in range(k + 1)]
    c[0][0] = 1
    for m in range(1, k + 1):
        for t in range(S + 1):
            tot = 0
            for x in range(lo, min(hi, t) + 1):
                tot += c[m - 1][t - x]
            c[m][t] = tot
    return c


def draw_lengths_own(rng, k, S, lo, hi, tab, skip_last=False):
    """One uniform ordered k-tuple in [lo, hi] summing to S, parts one at a time: P(x) proportional to c(m-1, t-x); rng.random() and a
    cumulative-sum search (T08.md section 3 step 11). skip_last: the last part is forced and consumes no random number (a variant, tried only
    to see which convention a saved draw uses)."""
    out = []
    t = S
    for m in range(k, 0, -1):
        hi_t = min(hi, t)
        if skip_last and m == 1:
            x = t
            assert lo <= x <= hi
        else:
            w = np.array([tab[m - 1][t - x] for x in range(lo, hi_t + 1)], dtype=float)
            cum = np.cumsum(w)
            u = rng.random()
            idx = int(np.searchsorted(cum, u * cum[-1], side="right"))
            x = lo + min(idx, len(w) - 1)
        out.append(x)
        t -= x
    return out


def states_from_lengths(first_state, ones, zeros):
    """Alternate spells starting in first_state; ones/zeros are the lengths of the 1- and 0-spells in order."""
    out = []
    i1 = i0 = 0
    for r in range(len(ones) + len(zeros)):
        st = first_state if r % 2 == 0 else 1 - first_state
        if st == 1:
            out.extend([1] * ones[i1]); i1 += 1
        else:
            out.extend([0] * zeros[i0]); i0 += 1
    return np.array(out, dtype=np.uint8)


def n410_states_own(first_state, k1, S1, hi1, k0, S0, hi0, seed_base, draw_id, tabs, skip_last=False):
    """Own N4.10 / N4.10-g draw: 1-spell lengths first, then 0-spell lengths, from one generator default_rng(seed_base + [id])."""
    rng = np.random.default_rng(list(seed_base) + [int(draw_id)])
    ones = draw_lengths_own(rng, k1, S1, LO, hi1, tabs[(k1, S1, hi1)], skip_last)
    zeros = draw_lengths_own(rng, k0, S0, LO, hi0, tabs[(k0, S0, hi0)], skip_last)
    return states_from_lengths(first_state, ones, zeros)


def n_ways(k, S, lo, hi):
    """Number of ordered k-tuples of integers in [lo, hi] summing to S, by inclusion-exclusion (no DP):
    sum_j (-1)^j C(k, j) C(S - k*lo - j*(hi-lo+1) + k - 1, k - 1); terms with a negative top argument are zero."""
    if k == 0:
        return 1 if S == 0 else 0
    tot = 0
    for j in range(0, k + 1):
        top = S - k * lo - j * (hi - lo + 1) + k - 1
        if top < 0 or top < k - 1:
            continue
        tot += (-1) ** j * math.comb(k, j) * math.comb(top, k - 1)
    return tot


def first_part_moments(k, S, lo, hi):
    """Exact mean and variance of one part of a uniform ordered k-tuple (parts are exchangeable)."""
    tot = n_ways(k, S, lo, hi)
    m1 = Fraction(0); m2 = Fraction(0)
    for x in range(lo, hi + 1):
        c = n_ways(k - 1, S - x, lo, hi)
        m1 += Fraction(x * c, tot)
        m2 += Fraction(x * x * c, tot)
    return float(m1), float(m2 - m1 * m1)

def rule_structure(states, hi_in=None, hi_out=None):
    runs = runs_of(states)
    ins = [l for v, l in runs if v == 1]
    outs = [l for v, l in runs if v == 0]
    return dict(weeks=len(states), first_state=int(states[0]), last_state=int(states[-1]), in_spells=len(ins), out_spells=len(outs),
                S_in=int(sum(ins)), S_out=int(sum(outs)), in_lengths=ins, out_lengths=outs,
                longest_in=max(ins) if ins else 0, longest_out=max(outs) if outs else 0, invested_weeks=int(np.sum(states)))


def week_cover(dec_idx):
    """Sessions between a week's trade session (decision session + 1) and the next week's trade session, as the engine
    counts them: cover_j = dec_idx[j+1] - dec_idx[j] for every week but the last (decided on the last session, never traded: 0).
    The first week starts at session 0 in the same count; no null can be IN in the first or last week (both are OUT)."""
    d = np.asarray(dec_idx, dtype=np.int64)
    cov = np.zeros(len(d), dtype=np.int64)
    cov[:-1] = d[1:] - d[:-1]
    return cov


def spells_of_rows(arr):
    """arr: (draws, weeks) uint8. Returns per row: in_lengths list, out_lengths list (in order), first state."""
    res = []
    for row in arr:
        ch = np.flatnonzero(np.diff(row.astype(np.int8)) != 0) + 1
        starts = np.concatenate([[0], ch])
        ends = np.concatenate([ch, [len(row)]])
        ins, outs = [], []
        for s_, e_ in zip(starts, ends):
            (ins if row[s_] == 1 else outs).append(int(e_ - s_))
        res.append((ins, outs, int(row[0])))
    return res

def pct_and_p(x, draws, higher_better, tol=1e-12):
    d = np.asarray(draws, dtype=float)
    tie = np.abs(d - x) <= tol * np.maximum(np.abs(d), abs(x))
    if higher_better:
        worse = (d < x) & ~tie
        better_eq = (d >= x) | tie
    else:
        worse = (d > x) & ~tie
        better_eq = (d <= x) | tie
    n = len(d)
    return float((worse.sum() + 0.5 * tie.sum()) / n * 100.0), float((1 + better_eq.sum()) / (n + 1))


def pct_and_p_loop(x, draws, higher_better, tol=1e-12):
    """A second, loop-based implementation of the same definition (cross-check)."""
    worse = tied = ge = 0
    for v in draws:
        v = float(v)
        t = abs(v - x) <= tol * max(abs(v), abs(x))
        if t:
            tied += 1; ge += 1
        elif (v < x) == higher_better:
            worse += 1
        else:
            ge += 1
    n = len(draws)
    return (worse + 0.5 * tied) / n * 100.0, (1 + ge) / (n + 1)


STAT_DIR = {"cagr": True, "max_dd": True, "vol": False, "ulcer": False, "days_below_10pct": False, "longest_underwater": False, "calmar": True}

class Check:
    def __init__(self, name, gate=True):
        self.name = name
        self.compared = 0
        self.failed = 0
        self.missing = 0
        self.worst_rel = 0.0
        self.first_fail = None
        self.gate = gate
        self.notes = []

    def fail(self, desc):
        if self.first_fail is None:
            self.first_fail = desc

    def miss(self, desc):
        self.missing += 1
        self.fail("MISSING: " + desc)

    def to_dict(self):
        return dict(compared=int(self.compared), failed=int(self.failed), missing=int(self.missing),
                    worst_rel=float(self.worst_rel), first_fail=self.first_fail, gate=self.gate, notes=self.notes)


def rel(a, b):
    a = np.asarray(a, dtype=float); b = np.asarray(b, dtype=float)
    return np.abs(a - b) / np.maximum(np.abs(b), 1e-12)


def compare_frames(chk, mine, ev, keys, num_cols=(), str_cols=(), tol=TOL):
    """Outer-join on keys; rows present on both sides are compared; others are missing."""
    mine = mine.copy(); ev = ev.copy()
    for k in keys:   # key columns must have one dtype on both sides
        if mine[k].dtype != ev[k].dtype:
            if pd.api.types.is_numeric_dtype(mine[k]) and pd.api.types.is_numeric_dtype(ev[k]):
                mine[k] = mine[k].astype(float); ev[k] = ev[k].astype(float)
            else:
                mine[k] = mine[k].astype(str); ev[k] = ev[k].astype(str)
    m = mine.merge(ev, on=keys, how="outer", suffixes=("_v", "_e"), indicator=True)
    both = m[m["_merge"] == "both"]
    miss = m[m["_merge"] != "both"]
    chk.missing += len(miss)
    if len(miss):
        r = miss.iloc[0]
        chk.fail("missing row (%s): %s" % ("verifier only" if r["_merge"] == "left_only" else "evidence only", {k: r[k] for k in keys}))
    bad = np.zeros(len(both), dtype=bool)
    first_desc = None
    for c in num_cols:
        a = both[c + "_v"].astype(float).values
        b = both[c + "_e"].astype(float).values
        nanmis = np.isnan(a) != np.isnan(b)
        r = np.where(np.isnan(a) & np.isnan(b), 0.0, rel(a, b))
        r = np.where(nanmis, np.inf, r)
        fin = r[np.isfinite(r)]
        if len(fin):
            chk.worst_rel = max(chk.worst_rel, float(fin.max()))
        bc = r > tol
        if bc.any() and first_desc is None:
            i = int(np.argmax(bc))
            first_desc = "first differing row %s col %s: verifier=%r evidence=%r" % ({k: both.iloc[i][k] for k in keys}, c, a[i], b[i])
        bad |= bc
    for c in str_cols:
        a = both[c + "_v"].astype(object).where(both[c + "_v"].notna(), "<NA>").astype(str).values
        b = both[c + "_e"].astype(object).where(both[c + "_e"].notna(), "<NA>").astype(str).values
        bc = a != b
        if bc.any() and first_desc is None:
            i = int(np.argmax(bc))
            first_desc = "first differing row %s col %s: verifier=%r evidence=%r" % ({k: both.iloc[i][k] for k in keys}, c, a[i], b[i])
        bad |= bc
    chk.compared += len(both)
    chk.failed += int(bad.sum())
    if first_desc:
        chk.fail(first_desc)


def r4(x):
    return np.round(np.asarray(x, dtype=float), 4)

def always_in_rows(p, nav_m, pub):
    pub = pub / pub.iloc[0]
    yrs = (len(nav_m) - 1) / 252.0
    cg_m = nav_m.iloc[-1] ** (1 / yrs) - 1
    cg_p = pub.iloc[-1] ** (1 / yrs) - 1
    rows = [dict(book=p, scope="overall", gap_pp=float((cg_m - cg_p) * 100), limit_pp=G0_OVERALL_PP)]
    yc = (nav_m.index[-1] - nav_m.index[0]).days / 365.25           # the same gap with calendar years (the G0 gate of the parent rebuild)
    rows.append(dict(book=p, scope="overall_calendar_years", gap_pp=float((nav_m.iloc[-1] ** (1 / yc) - pub.iloc[-1] ** (1 / yc)) * 100), limit_pp=G0_OVERALL_PP))
    ye_m = nav_m.groupby(nav_m.index.year).last()
    ye_p = pub.groupby(pub.index.year).last()
    ym = ye_m / ye_m.shift(1).fillna(1.0) - 1
    yp = ye_p / ye_p.shift(1).fillna(1.0) - 1
    for y in ym.index:
        rows.append(dict(book=p, scope=str(y), gap_pp=float((ym[y] - yp[y]) * 100), limit_pp=G0_YEAR_PP))
    return rows



def gws_of(g, mode="timed"):
    g = np.asarray(g)
    if mode == "fixed50":
        return np.full(len(g), GW_FIX)
    return np.where(g == 1, GW_BUY, GW_SELL).astype(float)


# ----------------------------------------------------------------------------------------
# derive everything that does not depend on the evidence
# ----------------------------------------------------------------------------------------
def derive(books=BOOKS, verbose=True):
    t = time.time()
    masters = load_masters()
    END = window_end(masters)
    gmaster = load_mauc1_master()
    g, mcx = load_gold()
    gfill, gclose, mcx_last = despiked_goldbees_fill(g, mcx)
    lbes = load_lbes()
    liq = load_liquidcase()
    corr = load_corrections()
    D = {"books": {}, "dec": [], "nav": [], "stats": [], "trades": [], "positions": [], "always_in": [], "meta": {}, "rule": {},
         "END": END, "masters": masters, "gmaster": gmaster}
    for p in books:
        B = build_book(p, gfill, gclose, mcx_last, lbes, liq, corr, END)
        n = B["n_full"]
        cal = B["cal"]
        a_live = int(np.searchsorted(cal.values, np.datetime64(LIVE_START), side="left"))
        V = make_view(B, 0, n, "lbes")
        Vliq = make_view(B, 0, n, "liquidcase")
        Vlive = make_view(B, a_live, n, "lbes")
        dec = decisions_for_window(B, 0, n, "full", masters, gmaster)
        dec_live = decisions_for_window(B, a_live, n, "live", masters, gmaster)
        if verbose:
            print(f"[{time.time()-t:6.1f}s] {p}: built (sessions {n}, live from {cal[a_live].date()}, stocks {len(B['S'])}, baskets {len(B['basket_at_full'])})", flush=True)
        s = dec["state"].values.astype(int)
        s_live = dec_live["state"].values.astype(int)
        gs = dec["g"].values.astype(int)
        gs_live = dec_live["g"].values.astype(int)
        dec_idx = dec["decision_idx"].values
        dec_idx_live = dec_live["decision_idx"].values
        nd = len(s)
        f_mix = s.sum() / nd
        rule = {"full": rule_structure(s), "live": rule_structure(s_live)}
        for w, st_, gg, di in (("full", s, gs, dec_idx), ("live", s_live, gs_live, dec_idx_live)):
            rule[w]["states"] = st_.astype(np.uint8)
            rule[w]["gstates"] = gg.astype(np.uint8)
            rule[w]["g"] = rule_structure(gg)
            rule[w]["dec_idx"] = di
            rule[w]["sessions"] = n if w == "full" else n - a_live
            rule[w]["start"] = str((cal[0] if w == "full" else cal[a_live]).date())
            rule[w]["end"] = str(cal[-1].date())
            rule[w]["cover"] = week_cover(di)
            # sleeve trades the rule makes = flips of g between two consecutive OUT decisions, none on the last (untraded) decision
            sl = sum(1 for j in range(1, len(st_) - 1) if st_[j] == 0 and st_[j - 1] == 0 and gg[j] != gg[j - 1])
            rule[w]["sleeve_trades"] = sl
        rule["hi_in"] = rule["full"]["longest_in"]
        rule["hi_out"] = rule["full"]["longest_out"]
        rule["hi_buy"] = rule["full"]["g"]["longest_in"]
        rule["hi_sell"] = rule["full"]["g"]["longest_out"]
        D["rule"][p] = rule
        D["meta"][p] = dict(sessions=n, decisions=nd, invested_weeks=int(s.sum()), t0=str(cal[0].date()), end=str(cal[-1].date()),
                            live_t0=str(cal[a_live].date()), live_sessions=n - a_live,
                            stale=int(((dec["label_age_days"] >= 5) & (dec["j"] > 0)).sum()),
                            initial_basket_switch_session=str(V["first_d18"].date()), dropped=B["dropped"],
                            in_spells=rule["full"]["in_spells"], out_spells=rule["full"]["out_spells"], f=f_mix,
                            buy_spells=rule["full"]["g"]["in_spells"], sell_spells=rule["full"]["g"]["out_spells"],
                            sleeve_trades=rule["full"]["sleeve_trades"], sleeve_trades_live=rule["live"]["sleeve_trades"],
                            raw_gold_sessions_after_mcx=B["raw_gold_sessions"], mcx_last=str(B["mcx_last"].date()))
        D["dec"].extend([dec, dec_live])
        gw_t, gw_5 = gws_of(gs), gws_of(gs, "fixed50")
        gw_t_live, gw_5_live = gws_of(gs_live), gws_of(gs_live, "fixed50")
        D["books"][p] = dict(B=B, V=V, Vliq=Vliq, Vlive=Vlive, dec_idx=dec_idx, dec_idx_live=dec_idx_live, s=s, s_live=s_live,
                             g=gs, g_live=gs_live, gw_t=gw_t, gw_5=gw_5, gw_t_live=gw_t_live, f=f_mix, a_live=a_live)

        def add(window, cash, kind, bps, r, states):
            st = stats_of(r["nav"])
            st.update(book=p, window=window, cash=cash, cost_bps=bps, kind=kind, trades=len(r["trades"]),
                      cost_paid=float(sum(x["cost"] for x in r["trades"])), closed_rel=r["closed_rel"],
                      n_segments=r["n_segments"], end_from_segments=r["end_from_segments"],
                      invested_weeks=float(np.sum(states)) if kind in ("strategy", "strategy_fixed50") else np.nan,
                      sleeve_trades=int(sum(1 for x in r["trades"] if x["kind"] == "sleeve_rebalance")))
            D["stats"].append(st)

        for bps in COSTS:
            ones, zeros = np.ones(nd, dtype=int), np.zeros(nd, dtype=int)
            runs = {
                "strategy": simulate(V, s, bps, dec_idx, gw_t, closed_form=True, positions=True),
                "strategy_fixed50": simulate(V, s, bps, dec_idx, gw_5),
                "hold_parent": simulate(V, ones, bps, dec_idx, gw_5, e_fixed=1.0),
                "constant_mix": simulate(V, s, bps, dec_idx, gw_5, mix_f=f_mix),
                "constant_mix_timed": simulate(V, s, bps, dec_idx, gw_t, mix_f=f_mix),
                "sleeve_only": simulate(V, zeros, bps, dec_idx, gw_5, e_fixed=0.0),
                "sleeve_only_timed": simulate(V, zeros, bps, dec_idx, gw_t, e_fixed=0.0),
            }
            if bps == 0.0:
                hold0 = runs["hold_parent"]
            for kind, r in runs.items():
                add("full", "lbes", kind, bps, r, s)
                D["nav"].append(pd.DataFrame(dict(book=p, date=[str(d.date()) for d in cal], cost_bps=bps, run=kind, nav=r["nav"])))
                for x in r["trades"]:
                    D["trades"].append(dict(book=p, cost_bps=bps, run=kind, **x))
                if kind == "strategy":
                    for dt, nm, u in r["positions"]:
                        D["positions"].append(dict(book=p, cost_bps=bps, run="strategy", date=dt, instrument=nm, units=u))
        # R2 (LIQUIDCASE cash) and R3 (live window), 20.8 bps, strategy
        add("full", "liq", "strategy", HEADLINE_COST, simulate(Vliq, s, HEADLINE_COST, dec_idx, gw_t), s)
        add("live", "lbes", "strategy", HEADLINE_COST, simulate(Vlive, s_live, HEADLINE_COST, dec_idx_live, gw_t_live), s_live)
        # always-in against the published NAV, whole window, 0 cost (= hold_parent at 0 cost)
        nav_m = pd.Series(hold0["nav"], index=cal)
        rows_ai = always_in_rows(p, nav_m, B["pub"].loc[cal])
        D["always_in"].extend(rows_ai)
        if verbose:
            print(f"[{time.time()-t:6.1f}s] {p}: done (f={f_mix:.4f}, always-in CAGR gap {rows_ai[0]['gap_pp']:+.3f} pp, sleeve trades {rule['full']['sleeve_trades']})", flush=True)
    D["dec"] = pd.concat(D["dec"], ignore_index=True)
    D["nav"] = pd.concat(D["nav"], ignore_index=True)
    D["stats"] = pd.DataFrame(D["stats"])
    D["trades"] = pd.DataFrame(D["trades"])
    D["positions"] = pd.DataFrame(D["positions"])
    D["always_in"] = pd.DataFrame(D["always_in"])
    return D


class Evidence:
    def __init__(self, evdir, fallback=None):
        self.dir = Path(evdir)
        self.fallback = Path(fallback) if fallback else None
        self.missing_files = []
        self._cache = {}

    def path(self, name):
        p = self.dir / name
        if p.exists():
            return p
        if self.fallback is not None and (self.fallback / name).exists():
            return self.fallback / name
        return None

    def get(self, name, chk=None):
        """Return the loaded object or None (and record MISSING on chk)."""
        if name in self._cache:
            obj = self._cache[name]
        else:
            p = self.path(name)
            obj = None
            if p is None:
                self.missing_files.append(name)
            else:
                try:
                    if name.endswith(".csv"):
                        kw = {"dtype": {c_: str for c_ in ("in_lengths", "out_lengths", "g_buy_lengths", "g_sell_lengths", "spell_sig", "strategy_sig", "g_spell_sig", "real_g_spell_sig")}} if name == "draws.csv" else {}
                        obj = pd.read_csv(p, **kw)
                    elif name.endswith(".json"):
                        obj = json.load(open(p))
                    elif name.endswith(".npz"):
                        obj = np.load(p)
                except Exception as ex:                        # unreadable == missing
                    self.missing_files.append(f"{name} (unreadable: {ex!r})")
                    obj = None
            self._cache[name] = obj
        if obj is None and chk is not None:
            chk.miss(f"evidence file {name}")
        return obj

def run_check(C, name, fn, gate=True):
    c = Check(name, gate=gate)
    C[name] = c
    try:
        fn(c)
    except Exception as ex:
        c.failed += 1
        c.fail(f"verifier exception in {name}: {ex!r} | {traceback.format_exc(limit=3).strip().splitlines()[-1]}")
    return c



# ----------------------------------------------------------------------------------------
# helpers for the checks
# ----------------------------------------------------------------------------------------
def sample_ids(book, key, n_first=20, n_rand=20, pool=None, seed=20261112):
    """The first n_first draw ids plus n_rand seeded random ids from the rest (per book and group key)."""
    pool = N_DRAWS if pool is None else pool
    rng = np.random.default_rng([seed, BOOKS.index(book), zlib.crc32(str(key).encode())])
    nf = min(n_first, pool)
    rest = np.arange(nf, pool)
    nr = min(n_rand, len(rest))
    return list(range(nf)) + (sorted(rng.choice(rest, size=nr, replace=False).tolist()) if nr > 0 else [])


class SimCache:
    def __init__(self):
        self.d = {}

    def run(self, V, states, bps, dec_idx, gws, tag):
        key = (tag, float(bps), np.asarray(states, dtype=np.uint8).tobytes(), np.asarray(gws, dtype=float).tobytes())
        if key not in self.d:
            self.d[key] = simulate(V, np.asarray(states, dtype=int), bps, dec_idx, gws)
        return self.d[key]


SIMS = SimCache()


def norm_g(x):
    """g in an evidence column -> 1 (BUY) / 0 (SELL) / NaN, whatever the spelling (BUY, 1, 1.0, True)."""
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return np.nan
    s = str(x).strip().upper()
    if s in ("BUY", "1", "1.0", "TRUE"):
        return 1.0
    if s in ("SELL", "0", "0.0", "FALSE"):
        return 0.0
    return np.nan


def norm_bool(x):
    return str(x).strip().lower() in ("true", "1", "1.0")


class Feat:
    """Spell features of every row of a (draws, weeks) uint8 array; value-1 spells are 'ones' (IN / BUY), value-0 spells 'zeros' (OUT / SELL)."""

    def __init__(self, arr, cover=None):
        arr = np.asarray(arr)
        sp = spells_of_rows(arr)
        self.arr = arr
        self.n = len(arr)
        self.first = np.array([s[2] for s in sp])
        self.last = arr[:, -1].astype(int)
        self.ones = [s[0] for s in sp]
        self.zeros = [s[1] for s in sp]
        self.n1 = np.array([len(x) for x in self.ones])
        self.n0 = np.array([len(x) for x in self.zeros])
        self.s1 = np.array(["|".join(map(str, x)) for x in self.ones], dtype=object)
        self.s0 = np.array(["|".join(map(str, x)) for x in self.zeros], dtype=object)
        self.w1 = arr.sum(axis=1).astype(int)
        self.sess = (arr.astype(np.int64) * cover).sum(axis=1) if cover is not None else None


def sleeve_trade_counts(S, G):
    """Per row: sleeve rebalances = decisions j = 1..D-2 that are OUT after an OUT decision with the gold state changed (the last decision is not traded)."""
    D = S.shape[1]
    if D < 3:
        return np.zeros(len(S), dtype=int)
    return ((S[:, 1:D - 1] == 0) & (S[:, 0:D - 2] == 0) & (G[:, 1:D - 1] != G[:, 0:D - 2])).sum(axis=1).astype(int)


def expected_groups():
    """(book, window, cash, cost, family, sleeve_mode) groups draws.csv must hold (contract 'rows in draws.csv')."""
    g = []
    for p in BOOKS:
        for fam in ("F1", "F2", "F3", "F4"):
            for cst in COSTS:
                g.append((p, "full", "lbes", cst, fam, "timed"))
        g.append((p, "full", "lbes", HEADLINE_COST, "F5", "timed"))
        for fam in ("F1", "F2"):
            g.append((p, "full", "lbes", HEADLINE_COST, fam, "fixed50"))
        for fam in ("F1", "F3"):
            g.append((p, "full", "liq", HEADLINE_COST, fam, "timed"))
            g.append((p, "live", "lbes", HEADLINE_COST, fam, "timed"))
    return g


def chi2_sf(x, df):
    try:
        from scipy.stats import chi2
        return float(chi2.sf(x, df))
    except Exception:
        return None


_SELFTEST_CACHE = {}


def sampler_selftest(n_samples=200000):
    """V5(a), the verifier's own sampler: k = 3, S = 12, bounds [2, 6] (19 tuples); every tuple enumerated, n_samples drawn, chi-square against equal frequencies."""
    if "r" in _SELFTEST_CACHE:
        return _SELFTEST_CACHE["r"]
    tuples = [t for t in product(range(2, 7), repeat=3) if sum(t) == 12]
    tab = ways_table(3, 12, 2, 6)
    rng = np.random.default_rng([20261112, 5])
    cnt = {t: 0 for t in tuples}
    for _ in range(n_samples):
        cnt[tuple(draw_lengths_own(rng, 3, 12, 2, 6, tab))] += 1
    exp = n_samples / len(tuples)
    chi = float(sum((v - exp) ** 2 / exp for v in cnt.values()))
    r = dict(n_tuples=len(tuples), n_ways_formula=n_ways(3, 12, 2, 6), n_ways_dp=tab[3][12], n_samples=n_samples, chi2=chi, df=len(tuples) - 1,
             p=chi2_sf(chi, len(tuples) - 1), all_seen=all(v > 0 for v in cnt.values()))
    _SELFTEST_CACHE["r"] = r
    return r


# ----------------------------------------------------------------------------------------
# the checks
# ----------------------------------------------------------------------------------------
def compare_all(D, E):
    C = {}
    nd_draws = N_DRAWS
    BOOKS_ = list(D["books"].keys())

    def c_data(c):
        inp = E.get("inputs.csv", c)
        # (1) the files THIS verifier read: approved, sha256 prefix matches the disk, through covers the window
        end = max(pd.Timestamp(m["end"]) for m in D["meta"].values())
        for key in sorted(READS):
            row = APPROVED.get(key)
            c.compared += 1
            ok = row is not None and row["status"] == "APPROVED"
            if ok:
                sha = sha256_file(AA / key)
                READS[key] = sha
                ok = sha.startswith(row["sha"])
                if ok and row["through"].lower() != "n/a" and (row["id"] not in THROUGH_EXEMPT_IDS and "parent_nav_2026-10-22" not in key):
                    ok = pd.Timestamp(row["through"]) >= end
            if not ok:
                c.failed += 1; c.fail(f"verifier-read file not an APPROVED, matching, covering row: {key}")
        if inp is None:
            return
        # (2) every file in inputs.csv
        cols = {x.lower(): x for x in inp.columns}
        fcol = cols.get("file")
        if fcol is None:
            c.failed += 1; c.fail("inputs.csv has no 'file' column"); return
        listed = set()
        for _, r in inp.iterrows():
            key = norm_path(r[fcol])
            listed.add(key)
            row = APPROVED.get(key)
            c.compared += 1
            if row is None:
                c.failed += 1; c.fail(f"inputs.csv lists a file that is not in APPROVED_DATA.md: {key}"); continue
            if row["status"] != "APPROVED":
                c.failed += 1; c.fail(f"inputs.csv lists a {row['status']} file: {key}"); continue
            sha = str(r[cols["sha256"]]).lower() if "sha256" in cols else ""
            c.compared += 1
            if not sha.startswith(row["sha"]):
                c.failed += 1; c.fail(f"sha256 of {key} in inputs.csv ({sha[:16]}) does not start with the approved prefix {row['sha']}")
            c.compared += 1
            disk = sha256_file(AA / key) if (AA / key).exists() else None
            if disk is None or (sha and disk != sha and not disk.startswith(sha)):
                c.failed += 1; c.fail(f"sha256 of {key} in inputs.csv differs from the file on disk")
            if "through" in cols:
                c.compared += 1
                th = str(r[cols["through"]]).strip()
                if row["through"].lower() != "n/a" and (row["id"] not in THROUGH_EXEMPT_IDS and "parent_nav_2026-10-22" not in key):
                    if pd.Timestamp(row["through"]) < end:
                        c.failed += 1; c.fail(f"approved through-date of {key} ({row['through']}) does not cover the window's end {end.date()}")
                if th.lower() not in ("n/a", "nan") and row["through"].lower() != "n/a" and th != row["through"]:
                    c.failed += 1; c.fail(f"through of {key} in inputs.csv ({th}) differs from APPROVED_DATA.md ({row['through']})")
        not_listed = sorted(set(READS) - listed)
        if not_listed:
            c.notes.append(f"{len(not_listed)} file(s) the verifier read are not in inputs.csv (not a failure under the spec): {not_listed[:4]}")
        c.notes.append(f"through-date exempt roles (earlier than the window by design): {sorted(THROUGH_EXEMPT_IDS)}")
    run_check(C, "C-data", c_data)



    # ------------------------------------------------------------------ C-dec, C-pit
    dec_m = D["dec"]

    def c_dec(c):
        ev = E.get("decisions.csv", c)
        if ev is None:
            return
        ev = ev.copy()
        if "window" not in ev.columns:
            ev["window"] = "full"
        ev["all_three_buy"] = ev["all_three_buy"].astype(str)
        mine = dec_m.copy()
        mine["all_three_buy"] = mine["all_three_buy"].astype(str)
        # the live window's decisions are compared when the evidence has them; full ones always
        full_only = not (ev["window"] == "live").any()
        if full_only:
            mine = mine[mine["window"] == "full"]
            c.notes.append("decisions.csv has no live rows; only the full window's decisions were compared")
        str_cols = ["trade_date", "sign_Nifty100", "sign_MC100", "sign_SC100", "label_Nifty100", "label_MC100", "label_SC100",
                    "latest_label", "decision_date", "all_three_buy", "sign_MAUc1", "label_MAUc1"]
        compare_frames(c, mine, ev, ["book", "window", "j"], num_cols=["decision_idx", "label_age_days", "state", "g", "gw"], str_cols=str_cols)
    run_check(C, "C-dec", c_dec)

    def c_pit(c):
        ev = E.get("decisions.csv", c)
        lcs = ["label_Nifty100", "label_MC100", "label_SC100", "label_MAUc1"]
        if ev is not None:
            for lc in lcs:
                if lc not in ev.columns:
                    c.miss(f"decisions.csv column {lc}"); continue
                ok = (ev[lc].astype(str) <= ev["decision_date"].astype(str)).values
                c.compared += len(ev); c.failed += int((~ok).sum())
                if (~ok).any(): c.fail("label after decision date: %s" % ev[~ok].iloc[0][["book", "j", "decision_date", lc]].to_dict())
            tdm = ev["trade_date"].notna()
            ok = (ev.loc[tdm, "trade_date"].astype(str) > ev.loc[tdm, "decision_date"].astype(str)).values
            c.compared += int(tdm.sum()); c.failed += int((~ok).sum())
            if (~ok).any(): c.fail("trade not after decision: %s" % ev.loc[tdm][~ok].iloc[0][["book", "j", "decision_date", "trade_date"]].to_dict())
            tr = E.get("trades.csv", c)
            if tr is not None:
                sw = tr[(tr["run"] == "strategy") & tr["kind"].isin(["switch_in", "switch_out", "sleeve_rebalance"])]
                evf = ev[ev["window"] == "full"] if "window" in ev.columns else ev
                mm = sw.merge(evf[["book", "trade_date", "decision_date"]], left_on=["book", "date"], right_on=["book", "trade_date"], how="left")
                okk = mm["decision_date"].notna() & (mm["date"].astype(str) > mm["decision_date"].astype(str))
                c.compared += len(mm); c.failed += int((~okk).sum())
                if (~okk).any(): c.fail("switch / sleeve trade without an earlier decision: %s" % mm[~okk].iloc[0][["book", "date"]].to_dict())
            stt = E.get("sleeve_trades.csv", c)
            if stt is not None:
                ok = (stt["date"].astype(str) > stt["decision_date"].astype(str)).values
                c.compared += len(stt); c.failed += int((~ok).sum())
                if (~ok).any(): c.fail("sleeve trade not after its decision: %s" % stt[~ok].iloc[0][["book", "decision_date", "date"]].to_dict())
        md = dec_m
        for lc in lcs:
            ok = (md[lc] <= md["decision_date"]).values
            c.compared += len(md); c.failed += int((~ok).sum())
        mt = md["trade_date"].notna()
        ok = (md.loc[mt, "trade_date"] > md.loc[mt, "decision_date"]).values
        c.compared += int(mt.sum()); c.failed += int((~ok).sum())
        # nothing after END is read: the last session of every book is END and no evidence trade or NAV row is later
        c.compared += 1
        if any(m["end"] != str(D["END"].date()) for m in D["meta"].values()):
            c.failed += 1; c.fail("a book's calendar does not end at END")
    run_check(C, "C-pit", c_pit)

    # ------------------------------------------------------------------ stats / NAV based checks
    est_all = E.get("stats.csv")
    env_all = E.get("daily_nav.csv")
    mst = D["stats"].copy()
    mst["cost_bps"] = r4(mst["cost_bps"])
    mnv = D["nav"].copy()
    mnv["cost_bps"] = r4(mnv["cost_bps"])
    if est_all is not None:
        est_all = est_all.copy()
        est_all["cost_bps"] = r4(est_all["cost_bps"])
        if "cash" in est_all.columns:
            est_all["cash"] = est_all["cash"].replace({"liquidcase": "liq"})
    if env_all is not None:
        env_all = env_all.copy()
        env_all["cost_bps"] = r4(env_all["cost_bps"])
        env_all["date"] = env_all["date"].astype(str)

    def est(window="full", cash="lbes"):
        return est_all[(est_all["window"] == window) & (est_all["cash"] == cash)]

    def nav_subset(df, kinds, costs):
        return df[df["run"].isin(kinds) & df["cost_bps"].isin(costs)]

    def stat_subset(df, kinds, costs, window="full", cash="lbes", col="kind"):
        m = df[df[col].isin(kinds) & df["cost_bps"].isin(costs)]
        if "window" in m.columns:
            m = m[(m["window"] == window) & (m["cash"] == cash)]
        return m

    NUMS = ["end_nav", "cagr", "max_dd", "vol"]
    NUMS_ALL = NUMS + ["ulcer", "calmar"]
    INTS = ["days_below_10pct", "longest_underwater", "sessions"]

    def c_nav0(c):
        if env_all is None or est_all is None:
            E.get("daily_nav.csv", c); E.get("stats.csv", c); return
        compare_frames(c, nav_subset(mnv, ["strategy"], [0.0]), nav_subset(env_all, ["strategy"], [0.0]), ["book", "date", "cost_bps", "run"], num_cols=["nav"])
        keys = ["book", "cost_bps", "kind"]
        compare_frames(c, stat_subset(mst, ["strategy"], [0.0])[keys + NUMS], stat_subset(est(), ["strategy"], [0.0])[keys + NUMS], keys, num_cols=NUMS)
    run_check(C, "C-nav0", c_nav0)

    def c_closed(c):
        for st in D["stats"].itertuples():
            if st.kind != "strategy" or st.window != "full" or st.cash != "lbes":
                continue
            r_ = abs(st.end_from_segments - st.end_nav) / st.end_nav
            c.compared += 1
            c.worst_rel = max(c.worst_rel, r_, st.closed_rel)
            if r_ > TOL or st.closed_rel > TOL:
                c.failed += 1; c.fail(f"{st.book} cost {st.cost_bps}: segment product {st.end_from_segments!r} vs NAV {st.end_nav!r}, within-segment rel {st.closed_rel:.2e}")
            if est_all is None:
                continue
            e_ = est()
            e_ = e_[(e_["book"] == st.book) & (e_["cost_bps"] == round(st.cost_bps, 4)) & (e_["kind"] == "strategy")]
            if len(e_):
                c.compared += 1
                rr = abs(st.end_from_segments - float(e_["end_nav"].iloc[0])) / float(e_["end_nav"].iloc[0])
                c.worst_rel = max(c.worst_rel, rr)
                if rr > TOL:
                    c.failed += 1; c.fail(f"{st.book} cost {st.cost_bps}: closed-form end NAV vs evidence end_nav rel {rr:.2e}")
            else:
                c.miss(f"evidence strategy stats row for {st.book} {st.cost_bps}")
        if est_all is None:
            E.get("stats.csv", c)
    run_check(C, "C-nav0-closed-form", c_closed)

    def c_cost(c):
        if env_all is None or est_all is None:
            E.get("daily_nav.csv", c); E.get("stats.csv", c); return
        keys = ["book", "cost_bps", "kind"]
        compare_frames(c, stat_subset(mst, ["strategy"], [20.8, 50.0])[keys + NUMS], stat_subset(est(), ["strategy"], [20.8, 50.0])[keys + NUMS], keys, num_cols=NUMS)
        compare_frames(c, nav_subset(mnv, ["strategy"], [20.8, 50.0]), nav_subset(env_all, ["strategy"], [20.8, 50.0]), ["book", "date", "cost_bps", "run"], num_cols=["nav"])
    run_check(C, "C-cost", c_cost)



    def c_stats_all(c):
        """Every statistic of every full-window LBES stats row (secondary statistics, trades, cost paid, invested weeks, sleeve trades), all seven runs, all costs."""
        if est_all is None:
            E.get("stats.csv", c); return
        keys = ["book", "cost_bps", "kind"]
        cols = NUMS_ALL + INTS + ["trades", "cost_paid"]
        compare_frames(c, stat_subset(mst, RUN_KINDS, COSTS)[keys + cols], stat_subset(est(), RUN_KINDS, COSTS)[keys + cols], keys, num_cols=cols)
        s1 = stat_subset(mst, ["strategy", "strategy_fixed50"], COSTS)[keys + ["invested_weeks"]]
        e1 = stat_subset(est(), ["strategy", "strategy_fixed50"], COSTS)[keys + ["invested_weeks"]]
        compare_frames(c, s1, e1, keys, num_cols=["invested_weeks"], tol=0.0)
        if "sleeve_trades" in est_all.columns:
            s2 = stat_subset(mst, ["strategy", "strategy_fixed50"], COSTS)[keys + ["sleeve_trades"]]
            e2 = stat_subset(est(), ["strategy", "strategy_fixed50"], COSTS)[keys + ["sleeve_trades"]]
            compare_frames(c, s2, e2, keys, num_cols=["sleeve_trades"], tol=0.0)
        else:
            c.miss("stats.csv column sleeve_trades")
    run_check(C, "C-stats-all", c_stats_all)

    def published_rows():
        rows = []
        for p in BOOKS_:
            pub = D["books"][p]["B"]["pub"]
            cal = D["books"][p]["B"]["cal"]
            pv = (pub.loc[cal] / pub.loc[cal].iloc[0]).values
            rows.append(pd.DataFrame(dict(book=p, date=[str(d.date()) for d in cal], cost_bps=-1.0, run="published", nav=pv)))
        return pd.concat(rows)

    def c_comp(c):
        if env_all is None or est_all is None:
            E.get("daily_nav.csv", c); E.get("stats.csv", c); return
        kinds = [k for k in RUN_KINDS if k != "strategy"]
        compare_frames(c, nav_subset(mnv, kinds, COSTS), nav_subset(env_all, kinds, COSTS), ["book", "date", "cost_bps", "run"], num_cols=["nav"])
        pubruns = [r for r in env_all["run"].unique() if "publish" in str(r).lower()]
        if pubruns:
            ep = env_all[env_all["run"].isin(pubruns)].drop_duplicates(["book", "date"]).assign(run="published", cost_bps=-1.0)[["book", "date", "cost_bps", "run", "nav"]]
            compare_frames(c, published_rows(), ep, ["book", "date", "cost_bps", "run"], num_cols=["nav"])
        else:
            c.notes.append("no 'published' run in daily_nav.csv; the published-NAV comparator was not compared (always-in check covers it)")
    run_check(C, "C-comp", c_comp)

    # ------------------------------------------------------------------ trades and positions
    def prep_tr(df, run):
        t = df[df["run"] == run].copy()
        t["cost_bps"] = r4(t["cost_bps"])
        t["seq"] = t.groupby(["book", "cost_bps"]).cumcount()
        return t

    def c_trades(c):
        tr = E.get("trades.csv", c)
        if tr is None:
            return
        mt = prep_tr(D["trades"], "strategy")
        et = prep_tr(tr, "strategy")
        et["date"] = et["date"].astype(str)
        # basket_eff is the date a basket took effect; a basket that took effect before T0 is shown by the verifier as T0 (its calendar position).
        # The first trade of the T08 rule can be a sleeve rebalance while OUT, when that pre-T0 basket is still in force; the evidence may show the true earlier date.
        t0 = et["book"].map(lambda b: "2019-01-04" if b == "SCMO_0007" else "2019-01-02")
        et["basket_eff"] = et["basket_eff"].astype(str).where(et["basket_eff"].astype(str) >= t0, t0)
        num = ["idx", "e_after", "V", "traded", "cost"] + (["nav_close_after"] if "nav_close_after" in et.columns else [])
        keys = ["book", "cost_bps", "seq"]
        compare_frames(c, mt, et, keys, num_cols=num, str_cols=["date", "kind", "basket_eff"])
        if "gw_after" not in et.columns:
            c.miss("trades.csv column gw_after")
        else:       # gw_after is compared on the trades that leave the book OUT (what an IN trade carries is not defined)
            compare_frames(c, mt[mt["e_after"] == 0][keys + ["gw_after"]], et[et["e_after"] == 0][keys + ["gw_after"]], keys, num_cols=["gw_after"], tol=0.0)
        compare_frames(c, mt.groupby(["book", "cost_bps"]).size().rename("n").reset_index(),
                       et.groupby(["book", "cost_bps"]).size().rename("n").reset_index(), ["book", "cost_bps"], num_cols=["n"], tol=0.0)
    run_check(C, "C-trades", c_trades)

    def c_trades_comp(c):
        """Informational: the other runs' trade lists (strategy_fixed50, hold_parent, constant mixes, sleeve_only_timed)."""
        tr = E.get("trades.csv", c)
        if tr is None:
            return
        keys = ["book", "cost_bps", "seq"]
        for run in [k for k in RUN_KINDS if k not in ("strategy", "sleeve_only")]:
            mt = prep_tr(D["trades"], run)
            et = prep_tr(tr, run)
            if not len(et):
                c.notes.append(f"trades.csv has no rows for run {run}"); continue
            et["date"] = et["date"].astype(str)
            compare_frames(c, mt, et, keys, num_cols=["idx", "traded", "cost"], str_cols=["date", "kind"])
    run_check(C, "C-trades-comparators", c_trades_comp, gate=False)

    def c_positions_unused(c):
        pass

    # ------------------------------------------------------------------ the sleeve: C-sleeve, C-sleeve-identity
    decd = {(r.book, r.j): r.decision_date for r in D["dec"][D["dec"]["window"] == "full"].itertuples()}
    decg = {(r.book, r.j): r.g for r in D["dec"][D["dec"]["window"] == "full"].itertuples()}

    def my_sleeve_rows():
        mt = D["trades"]
        mt = mt[(mt["run"] == "strategy") & mt["kind"].isin(["switch_out", "sleeve_rebalance"])].copy()
        mt["cost_bps"] = r4(mt["cost_bps"])
        mt["seq"] = mt.groupby(["book", "cost_bps"]).cumcount()
        mt["decision_date"] = [decd[(b, j)] for b, j in zip(mt["book"], mt["j"])]
        mt["g_after"] = [decg[(b, j)] for b, j in zip(mt["book"], mt["j"])]
        mt["gw_after"] = mt["gw_after"].astype(float)
        mt["g_before"] = np.where(mt["kind"] == "sleeve_rebalance", np.where(mt["gw_before"] == GW_BUY, 1.0, 0.0), np.nan)
        mt["gw_before"] = np.where(mt["kind"] == "sleeve_rebalance", mt["gw_before"], np.nan)
        mt["gold_value_before"] = np.where(mt["kind"] == "sleeve_rebalance", mt["gold_before"], np.nan)
        mt["cash_value_before"] = np.where(mt["kind"] == "sleeve_rebalance", mt["cash_before"], np.nan)
        mt = mt.rename(columns={"gold_after": "gold_value_after", "cash_after": "cash_value_after", "raw_fill": "gold_fill_raw"})
        mt["gold_fill_raw"] = mt["gold_fill_raw"].astype(int)
        return mt

    def c_sleeve(c):
        st = E.get("sleeve_trades.csv", c)
        if st is None:
            return
        st = st.copy()
        st["cost_bps"] = r4(st["cost_bps"])
        st["seq"] = st.groupby(["book", "cost_bps"]).cumcount()
        st["date"] = st["date"].astype(str)
        st["decision_date"] = st["decision_date"].astype(str)
        for col in ("g_before", "g_after"):
            st[col] = [norm_g(x) for x in st[col]]
        st["gold_fill_raw"] = [int(norm_bool(x)) for x in st["gold_fill_raw"]]
        mine = my_sleeve_rows()
        keys = ["book", "cost_bps", "seq"]
        compare_frames(c, mine[keys + ["date", "kind", "decision_date", "g_after", "gw_after", "gold_value_after", "cash_value_after", "traded", "cost", "gold_fill_raw"]],
                       st[keys + ["date", "kind", "decision_date", "g_after", "gw_after", "gold_value_after", "cash_value_after", "traded", "cost", "gold_fill_raw"]],
                       keys, num_cols=["g_after", "gw_after", "gold_value_after", "cash_value_after", "traded", "cost", "gold_fill_raw"], str_cols=["date", "kind", "decision_date"])
        bcols = ["g_before", "gw_before", "gold_value_before", "cash_value_before"]
        compare_frames(c, mine[mine["kind"] == "sleeve_rebalance"][keys + bcols], st[st["kind"] == "sleeve_rebalance"][keys + bcols], keys, num_cols=bcols)
        # the rebalance rows of trades.csv are the same trades
        tr = E.get("trades.csv", c)
        if tr is not None:
            a = mine[mine["kind"] == "sleeve_rebalance"].groupby(["book", "cost_bps"]).size().rename("n").reset_index()
            t2 = tr[(tr["run"] == "strategy") & (tr["kind"] == "sleeve_rebalance")].copy(); t2["cost_bps"] = r4(t2["cost_bps"])
            b = st[st["kind"] == "sleeve_rebalance"].groupby(["book", "cost_bps"]).size().rename("n").reset_index()
            compare_frames(c, b, t2.groupby(["book", "cost_bps"]).size().rename("n").reset_index(), ["book", "cost_bps"], num_cols=["n"], tol=0.0)
            compare_frames(c, a, b, ["book", "cost_bps"], num_cols=["n"], tol=0.0)
        c.notes.append(f"{len(mine)} exits and sleeve rebalances of the verifier's strategy; raw-fill (after {D['books'][BOOKS_[0]]['B']['mcx_last'].date()}) trades: {int(mine['gold_fill_raw'].sum())}")
    run_check(C, "C-sleeve", c_sleeve)

    def c_sleeve_identity(c):
        """V6 on the engine's own numbers: cost = traded x bps/2/1e4, value conservation, the post-trade split equals gw_after of the value after cost,
        a sleeve rebalance needs a change of g, the raw-fill flag follows the MCX range's end, and at 0 cost the value is continuous."""
        st = E.get("sleeve_trades.csv", c)
        if st is None:
            return
        mcx_last = D["books"][BOOKS_[0]]["B"]["mcx_last"]
        for r in st.itertuples():
            bps = float(r.cost_bps)
            gA, cA = float(r.gold_value_after), float(r.cash_value_after)
            reb = str(r.kind) == "sleeve_rebalance"
            c.compared += 1
            if abs(float(r.cost) - float(r.traded) * bps / 2.0 / 10000.0) > 1e-12 * max(1.0, abs(gA + cA)):
                c.failed += 1; c.fail(f"cost != traded x bps/2/1e4: {r}")
            c.compared += 1
            if abs(float(r.gw_after) - (gA / (gA + cA))) > 1e-12:
                c.failed += 1; c.fail(f"post-trade split {gA / (gA + cA)!r} != gw_after {r.gw_after!r}: {r}")
            c.compared += 1
            if bool(norm_bool(r.gold_fill_raw)) != bool(pd.Timestamp(str(r.date)) > mcx_last):
                c.failed += 1; c.fail(f"gold_fill_raw wrong: {r}")
            if reb:
                gB, cB = float(r.gold_value_before), float(r.cash_value_before)
                Vb = gB + cB
                tol = 1e-12 * max(1.0, Vb)
                c.compared += 3
                if abs((gA + cA) - (Vb - float(r.cost))) > tol:
                    c.failed += 1; c.fail(f"value not conserved (after = before - cost) at {r}")
                if abs(gA - float(r.gw_after) * (Vb - float(r.cost))) > tol:
                    c.failed += 1; c.fail(f"gold value after != gw_after x value after cost at {r}")
                tr_exp = abs(float(r.gw_after) * Vb - gB) + abs((1 - float(r.gw_after)) * Vb - cB)
                if abs(tr_exp - float(r.traded)) > 1e-9 * max(1.0, tr_exp):
                    c.failed += 1; c.fail(f"traded {r.traded!r} != |dGOLDBEES| + |dcash| {tr_exp!r} at {r}")
                c.compared += 1
                if norm_g(r.g_before) == norm_g(r.g_after) or float(r.gw_before) == float(r.gw_after):
                    c.failed += 1; c.fail(f"a sleeve rebalance without a change of g: {r}")
                if bps == 0.0:
                    c.compared += 1
                    if abs((gA + cA) - Vb) > tol:
                        c.failed += 1; c.fail(f"NAV not continuous through a 0-cost sleeve rebalance: {r}")
        # no sleeve trade while g is constant: every rebalance the engine lists is one of the verifier's (C-sleeve compares both ways); count it here too
        mine = my_sleeve_rows()
        n_mine = int((mine["kind"] == "sleeve_rebalance").sum())
        n_ev = int((st["kind"] == "sleeve_rebalance").sum())
        c.compared += 1
        if n_mine != n_ev:
            c.failed += 1; c.fail(f"sleeve rebalances: verifier {n_mine}, engine {n_ev}")
    run_check(C, "C-sleeve-identity", c_sleeve_identity)

    # ------------------------------------------------------------------ the gold signal
    def c_gold(c):
        wk = load_mauc1_weekly()
        gd, gsg = D["gmaster"]
        mm = pd.DataFrame({"review": pd.to_datetime(gd), "msign": gsg})
        j = mm.merge(wk[["review", "SIGN", "signal"]], on="review", how="inner")
        c.compared += len(j)
        bad = (j["msign"] != j["SIGN"]) | ((j["signal"] == 1.0) != (j["SIGN"] == "BUY"))
        c.failed += int(bad.sum())
        if bad.any(): c.fail("Master_MAUc1 SIGN / weekly csv SIGN / signal disagree: %s" % j[bad].iloc[0].to_dict())
        c.notes.append(f"Master_MAUc1 rows {len(mm)}, weekly csv rows {len(wk)}, shared dates {len(j)}")
        # the verifier's own g series (from the raw Master, as-of) against the weekly csv's signal (as-of), every decision
        wd = wk["review"].values
        for r in D["dec"].itertuples():
            pos = int(np.searchsorted(wd, np.datetime64(pd.Timestamp(r.decision_date)), side="right") - 1)
            c.compared += 1
            if pos < 0 or int(wk["signal"].iloc[pos]) != r.g or wk["SIGN"].iloc[pos] != r.sign_MAUc1 or str(wk["review"].iloc[pos].date()) != r.label_MAUc1:
                c.failed += 1; c.fail(f"g at {r.book} {r.window} j={r.j} {r.decision_date}: Master {r.sign_MAUc1} (row {r.label_MAUc1}) vs weekly csv row {wk['review'].iloc[pos].date() if pos >= 0 else None}")
        gs_ev = E.get("gold_signal.csv", c)
        if gs_ev is not None:
            mine = D["dec"][D["dec"]["window"] == "full"][["book", "j", "decision_date", "label_MAUc1", "sign_MAUc1", "g", "gw"]]
            compare_frames(c, mine, gs_ev[["book", "j", "decision_date", "label_MAUc1", "sign_MAUc1", "g", "gw"]], ["book", "j"],
                           num_cols=["g", "gw"], str_cols=["decision_date", "label_MAUc1", "sign_MAUc1"])
    run_check(C, "C-gold", c_gold)

    real_npz = E.get("real_states.npz")

    def c_real_states(c):
        if real_npz is None:
            E.get("real_states.npz", c); return
        for p in BOOKS_:
            for w in ("full", "live"):
                for dom, k in (("io", "states"), ("gold", "gstates")):
                    key = f"{p}|{w}|{dom}"
                    c.compared += 1
                    if key not in real_npz.files:
                        c.missing += 1; c.fail(f"MISSING: real_states.npz key {key}"); continue
                    if not np.array_equal(real_npz[key].astype(np.uint8), D["rule"][p][w][k]):
                        c.failed += 1; c.fail(f"real_states.npz {key} differs from the verifier's series")
    run_check(C, "C-real-states", c_real_states)

    def c_positions(c):
        ps = E.get("positions.csv", c)
        if ps is None:
            return
        ev = ps[ps["units"] != 0].copy(); ev["cost_bps"] = r4(ev["cost_bps"]); ev["date"] = ev["date"].astype(str)
        ev = ev[ev["run"] == "strategy"]
        mine = D["positions"].copy(); mine["cost_bps"] = r4(mine["cost_bps"])
        mine = mine[mine["units"] != 0]
        compare_frames(c, mine, ev[["book", "cost_bps", "run", "date", "instrument", "units"]], ["book", "cost_bps", "run", "date", "instrument"], num_cols=["units"])
    run_check(C, "C-positions", c_positions)

    def c_always(c):
        ai = D["always_in"]
        c.compared = len(ai)
        badm = ai["gap_pp"].abs() > ai["limit_pp"]
        c.failed = int(badm.sum())
        if badm.any():
            c.fail("G0 exceeded (verifier's own always-in NAV): %s" % ai[badm].iloc[0].to_dict())
        # the engine's always-in NAV (hold_parent, 0 cost) against the published NAV, within G0
        if env_all is None:
            E.get("daily_nav.csv", c); return
        hp = env_all[(env_all["run"] == "hold_parent") & (env_all["cost_bps"] == 0.0)]
        if not len(hp):
            c.miss("hold_parent run at 0 cost in daily_nav.csv"); return
        for p in BOOKS:
            h = hp[hp["book"] == p]
            if not len(h):
                c.miss(f"always-in NAV of {p}"); continue
            cal = D["books"][p]["B"]["cal"]
            nav_e = pd.Series(h["nav"].values, index=pd.to_datetime(h["date"].values))
            nav_e = nav_e.reindex(cal)
            if nav_e.isna().any():
                c.miss(f"{p}: always-in NAV lacks {int(nav_e.isna().sum())} sessions"); continue
            rows = always_in_rows(p, nav_e, D["books"][p]["B"]["pub"].loc[cal])
            for r in rows:
                c.compared += 1
                if abs(r["gap_pp"]) > r["limit_pp"]:
                    c.failed += 1; c.fail(f"G0 exceeded (engine's always-in NAV): {r}")
    run_check(C, "C-always-in", c_always)

    def c_g_engine(c):
        g = E.get("g_engine.csv", c)
        if g is None:
            return
        ai = D["always_in"]
        for _, r in g.iterrows():
            a = ai[(ai["book"] == r["book"]) & (ai["scope"].isin(["overall", "overall_calendar_years"]))]
            if not len(a):
                c.miss(f"g_engine row for unknown book {r['book']}"); continue
            c.compared += 1
            d_ = min(abs(float(r["cagr_gap_pp_yr"]) - float(x)) for x in a["gap_pp"])      # T03's engine used calendar years; either reading is accepted
            c.worst_rel = max(c.worst_rel, d_)
            if d_ > 1e-6:
                c.failed += 1; c.fail(f"{r['book']}: engine G0 CAGR gap {r['cagr_gap_pp_yr']!r} vs verifier {a['gap_pp'].tolist()!r} pp/yr (session years, calendar years)")
            y = ai[(ai["book"] == r["book"]) & (~ai["scope"].isin(["overall", "overall_calendar_years"]))]
            w = y.iloc[int(y["gap_pp"].abs().values.argmax())]
            c.compared += 1
            d2 = abs(abs(float(r["worst_year_gap_pp"])) - abs(float(w["gap_pp"])))
            c.worst_rel = max(c.worst_rel, d2)
            if d2 > 1e-6:
                c.failed += 1; c.fail(f"{r['book']}: engine worst-year gap {r['worst_year_gap_pp']!r} vs verifier {w['scope']} {w['gap_pp']!r} pp")
        for p in BOOKS:
            if p not in set(g["book"]):
                c.miss(f"g_engine.csv row for {p}")
    run_check(C, "C-g-engine", c_g_engine, gate=True)



    # ------------------------------------------------------------------ R2 / R3 stats (LIQUIDCASE, live)
    def c_r2r3(c):
        if est_all is None:
            E.get("stats.csv", c); return
        keys = ["book", "window", "cash", "cost_bps", "kind"]
        cols = NUMS_ALL + INTS + ["trades", "cost_paid"]
        for window, cash in (("full", "liq"), ("live", "lbes")):
            m = mst[(mst["window"] == window) & (mst["cash"] == cash)][keys + cols]
            e = est_all[(est_all["window"] == window) & (est_all["cash"] == cash) & (est_all["kind"] == "strategy") & (est_all["cost_bps"] == HEADLINE_COST)][keys + cols]
            compare_frames(c, m, e, keys, num_cols=cols)
    run_check(C, "C-stats-liquidcase-live", c_r2r3)

    # ------------------------------------------------------------------ V4(e): extended D17 equals old D17 on its rows
    def c_d17_overlap(c):
        for p in BOOKS_:
            a = load_published_nav_old(p)
            b = load_published_nav(p)
            bb = b.reindex(a.index)
            c.compared += len(a)
            nmiss = int(bb.isna().sum())
            c.missing += nmiss
            if nmiss:
                c.fail(f"{p}: {nmiss} session(s) of the old D17 are absent from the extended file")
            r_ = (np.abs(a - bb) / np.abs(a)).dropna()
            c.worst_rel = max(c.worst_rel, float(r_.max()))
            nb = int((r_ > 1e-12).sum())
            c.failed += nb
            if nb:
                c.fail(f"{p}: the extended D17 differs from the old D17 on {nb} row(s), worst {r_.max():.2e}")
            c.compared += 1
            if b.index[0] != a.index[0] or not (b.index[:len(a)] == a.index).all():
                c.failed += 1; c.fail(f"{p}: the extended file does not begin with the old file's sessions")
            c.notes.append(f"{p}: old {len(a)} rows to {a.index[-1].date()}, extended {len(b)} rows to {b.index[-1].date()}")
    run_check(C, "C-d17-overlap", c_d17_overlap)

    # ------------------------------------------------------------------ V4: regression to T06 on the overlap
    t6_dec_p = T06_EVIDENCE / "decisions.csv"
    t6_nav_p = T06_EVIDENCE / "daily_nav.csv"
    t6_st_p = T06_EVIDENCE / "draw_states.npz"
    t6_cv_p = T06_EVIDENCE / "draw_curves_20.8.npz"

    def c_t06_dec(c):
        if not t6_dec_p.exists():
            c.miss("tests/T06/evidence/headline/decisions.csv"); return
        t6 = pd.read_csv(t6_dec_p)
        for p in BOOKS_:
            t = t6[t6["book"] == p].sort_values("j").reset_index(drop=True)
            m = dec_m[(dec_m["book"] == p) & (dec_m["window"] == "full")].sort_values("j").reset_index(drop=True)
            k = len(t) - 1       # T06's last decision (2026-10-22, the last session of its calendar) is read against the new window's 2026-10-23
            c.compared += 1
            if len(m) != len(t) + 1:
                c.failed += 1; c.fail(f"{p}: T06 has {len(t)} decisions, the new window {len(m)} (expected one more)")
                continue
            a, b = t.iloc[:k], m.iloc[:k]
            for col in ["decision_date", "decision_idx", "state", "sign_Nifty100", "sign_MC100", "sign_SC100", "label_Nifty100", "label_MC100",
                        "label_SC100", "latest_label", "label_age_days", "all_three_buy"]:
                x = a[col].astype(str).values
                y = b[col].astype(str).values
                bad = int((x != y).sum())
                c.compared += k; c.failed += bad
                if bad:
                    i0 = int(np.argmax(x != y)); c.fail(f"{p} j={i0} {col}: T06 {x[i0]!r} vs verifier {y[i0]!r}")
            tt = a["trade_date"].notna().values
            bad = int((a["trade_date"].astype(str).values[tt] != b["trade_date"].astype(str).values[tt]).sum())
            c.compared += int(tt.sum()); c.failed += bad
            if bad: c.fail(f"{p}: a trade date differs from T06")
            c.compared += 2
            if int(t["state"].iloc[k]) != int(m["state"].iloc[k]):
                c.failed += 1; c.fail(f"{p}: T06's last decision state {t['state'].iloc[k]} vs the verifier's decision of {m['decision_date'].iloc[k]}")
            if not (pd.Timestamp(m["decision_date"].iloc[k]) > pd.Timestamp(t["decision_date"].iloc[k]) and pd.Timestamp(m["decision_date"].iloc[k]) - pd.Timestamp(t["decision_date"].iloc[k]) <= pd.Timedelta(days=4)):
                c.failed += 1; c.fail(f"{p}: the last shared week's decision date {m['decision_date'].iloc[k]} is not the Friday after T06's {t['decision_date'].iloc[k]}")
        c.notes.append("T06's last decision date 2026-10-22 is read against 2026-10-23 (the window now holds that week's Friday); the extra decision is 2026-10-30")
    run_check(C, "C-t06-decisions", c_t06_dec)

    def c_t06_nav(c):
        """With the sleeve fixed at 50/50 the verifier's simulator reproduces T06's strategy, hold_parent, sleeve_only and constant mix NAVs on the overlap (1e-12)."""
        if not t6_nav_p.exists() or not t6_dec_p.exists():
            c.miss("T06 daily_nav.csv / decisions.csv"); return
        n6 = pd.read_csv(t6_nav_p)
        n6["cost_bps"] = r4(n6["cost_bps"]); n6["date"] = n6["date"].astype(str)
        pubm = n6["run"].astype(str).str.contains("publish")
        n6.loc[pubm, "cost_bps"] = -1.0
        n6.loc[pubm, "run"] = "published"
        n6 = n6[n6["date"] <= str(T06_CUTOFF.date())]
        t6 = pd.read_csv(t6_dec_p)
        f6 = {p: float(t6[t6["book"] == p]["state"].sum()) / float((t6["book"] == p).sum()) for p in BOOKS_}      # T06's own f (its window)
        rows = []
        ren = {"strategy_fixed50": "strategy", "hold_parent": "hold_parent", "sleeve_only": "sleeve_only"}
        sub = mnv[mnv["run"].isin(list(ren)) & mnv["cost_bps"].isin(COSTS)].copy()
        sub["run"] = sub["run"].map(ren)
        rows.append(sub)
        for p in BOOKS_:
            bk = D["books"][p]
            for bps in COSTS:
                r = simulate(bk["V"], bk["s"], bps, bk["dec_idx"], bk["gw_5"], mix_f=f6[p])
                rows.append(pd.DataFrame(dict(book=p, date=[str(d.date()) for d in bk["B"]["cal"]], cost_bps=r4(bps), run="constant_mix", nav=r["nav"])))
        rows.append(published_rows())
        mine = pd.concat(rows)
        mine = mine[mine["date"] <= str(T06_CUTOFF.date())]
        compare_frames(c, mine, n6, ["book", "date", "cost_bps", "run"], num_cols=["nav"], tol=TOL_REGRESSION)
        c.notes.append(f"NAVs compared on dates <= {T06_CUTOFF.date()}: strategy_fixed50 vs T06 strategy, hold_parent, sleeve_only, constant_mix (T06's f), published; relative tolerance {TOL_REGRESSION}")
    run_check(C, "C-t06-nav", c_t06_nav)

    def c_t06_draws(c):
        """T06's first 20 N4.10 draws, replayed from T06's saved states with the rule's states appended after T06's last week, reproduce T06's saved
        curves (20.8 bps, fixed 50/50 sleeve) on the overlap; and the verifier's own N4.10 sampler reproduces T06's saved draws."""
        if not (t6_st_p.exists() and t6_cv_p.exists() and t6_dec_p.exists()):
            c.miss("T06 draw_states.npz / draw_curves_20.8.npz / decisions.csv"); return
        z = np.load(t6_st_p)
        cv = np.load(t6_cv_p)
        t6 = pd.read_csv(t6_dec_p)
        for p in BOOKS_:
            bk = D["books"][p]
            key = f"{p}|full|N4.10"
            if key not in z.files:
                c.miss(f"T06 draw_states.npz key {key}"); continue
            arr = z[key]
            Wt = arr.shape[1]
            for i in range(20):
                st = np.concatenate([arr[i], bk["s"][Wt:]]).astype(int)
                r = SIMS.run(bk["V"], st, HEADLINE_COST, bk["dec_idx"], bk["gw_5"], (p, "full", "lbes"))
                ck = f"{p}|N4.10_{i}"
                c.compared += 1
                if ck not in cv.files:
                    c.missing += 1; c.fail(f"MISSING: T06 curve {ck}"); continue
                cu = cv[ck].astype(float)
                rr = float(np.max(np.abs(cu - r["nav"][:len(cu)]) / np.abs(cu)))
                c.worst_rel = max(c.worst_rel, rr)
                if rr > TOL_CURVE:
                    c.failed += 1; c.fail(f"{ck}: replayed curve differs from T06's by {rr:.2e}")
            # the verifier's sampler against T06's saved draws (T06's own totals, from its decisions)
            s6 = t6[t6["book"] == p].sort_values("j")["state"].values.astype(int)
            rs = rule_structure(s6)
            tabs = {(rs["in_spells"], rs["S_in"], rs["longest_in"]): ways_table(rs["in_spells"], rs["S_in"], LO, rs["longest_in"]),
                    (rs["out_spells"], rs["S_out"], rs["longest_out"]): ways_table(rs["out_spells"], rs["S_out"], LO, rs["longest_out"])}
            for i in range(min(100, arr.shape[0])):
                c.compared += 1
                own = n410_states_own(int(s6[0]), rs["in_spells"], rs["S_in"], rs["longest_in"], rs["out_spells"], rs["S_out"], rs["longest_out"], SEEDS["n410"], i, tabs)
                if not np.array_equal(own, arr[i]):
                    c.failed += 1; c.fail(f"{p}: the verifier's N4.10 sampler (seed [6, {i}]) does not reproduce T06's saved draw {i}")
        c.notes.append("worst_rel = largest relative difference between a replayed curve and T06's float32 curve")
    run_check(C, "C-t06-draws", c_t06_draws)



    # ------------------------------------------------------------------ draws.csv / draw_states.npz
    draws = E.get("draws.csv")
    if draws is not None:
        draws = draws.copy()
        draws["cost_bps"] = r4(draws["cost_bps"])
        draws["cash"] = draws["cash"].replace({"liquidcase": "liq"})
    states_npz = E.get("draw_states.npz")
    curves_npz = E.get("draw_curves_20.8.npz")
    WINDOWS = ["full", "live"]
    TYPES_IO = ["N4.9", "N4.10"]
    TYPES_GOLD = ["N4.9-g", "N4.10-g"]
    FEATS = {}

    def states_of(book, window, dom, typ):
        key = f"{book}|{window}|{dom}|{typ}"
        if states_npz is None or key not in states_npz.files:
            return None
        return states_npz[key]

    def feat(book, window, dom, typ):
        key = (book, window, dom, typ)
        if key not in FEATS:
            R = D["rule"][book][window]
            if typ == "real":
                arr = (R["states"] if dom == "io" else R["gstates"])[None, :]
            else:
                arr = states_of(book, window, dom, typ)
            FEATS[key] = None if arr is None else Feat(arr, cover=R["cover"] if dom == "io" else None)
        return FEATS[key]

    def c_states(c_struct, c_len, c_gold):
        """Structure of every saved draw: in-or-out arrays (V3 as T06, bounds [2, 46] / [2, 40]) and gold arrays (weeks, first state, spell counts,
        BUY weeks identical; N4.9-g sorted lengths identical; N4.10-g lengths within [2, 68] / [2, 28] and summing to the totals)."""
        if states_npz is None:
            for cc in (c_struct, c_len, c_gold):
                E.get("draw_states.npz", cc)
            return
        for p in BOOKS_:
            rule = D["rule"][p]
            for window in WINDOWS:
                R = rule[window]
                G = R["g"]
                for dom, typs, RR, hi1, hi0 in (("io", TYPES_IO, R, rule["hi_in"], rule["hi_out"]), ("gold", TYPES_GOLD, G, rule["hi_buy"], rule["hi_sell"])):
                    for typ in typs:
                        cs, cl = (c_struct, c_len) if dom == "io" else (c_gold, c_gold)
                        f = feat(p, window, dom, typ)
                        if f is None:
                            cs.miss(f"draw_states.npz key {p}|{window}|{dom}|{typ}")
                            continue
                        arr = f.arr
                        nd_, W_ = arr.shape
                        cs.compared += 2
                        if nd_ != nd_draws:
                            cs.failed += 1; cs.fail(f"{p}|{window}|{dom}|{typ}: {nd_} draws, expected {nd_draws}")
                        if W_ != RR["weeks"] or arr.dtype != np.uint8 or not np.isin(arr, [0, 1]).all():
                            cs.failed += 1; cs.fail(f"{p}|{window}|{dom}|{typ}: shape/dtype/values wrong: {arr.shape} {arr.dtype} (weeks expected {RR['weeks']})")
                            continue
                        for i in range(nd_):
                            cs.compared += 4
                            bad = []
                            if f.first[i] != RR["first_state"]: bad.append("first state")
                            if f.n1[i] != RR["in_spells"] or f.n0[i] != RR["out_spells"]: bad.append("spell counts")
                            if f.w1[i] != RR["invested_weeks"]: bad.append("in / BUY weeks")
                            if f.last[i] != RR["last_state"]: bad.append("last state")
                            if bad:
                                cs.failed += len(bad); cs.fail(f"{p}|{window}|{dom}|{typ} draw {i}: {', '.join(bad)} differ from the real series'")
                            cl.compared += 1
                            ins, outs = f.ones[i], f.zeros[i]
                            if typ in ("N4.9", "N4.9-g"):
                                ok = sorted(ins) == sorted(RR["in_lengths"]) and sorted(outs) == sorted(RR["out_lengths"])
                                why = "sorted spell lengths differ from the real series'"
                            else:
                                ok = (len(ins) > 0 and min(ins) >= LO and max(ins) <= hi1 and len(outs) > 0 and min(outs) >= LO and max(outs) <= hi0
                                      and sum(ins) == RR["S_in"] and sum(outs) == RR["S_out"])
                                why = f"{typ} bounds [{LO},{hi1}]/[{LO},{hi0}] or sums ({RR['S_in']}, {RR['S_out']}) violated"
                            if not ok:
                                cl.failed += 1; cl.fail(f"{p}|{window}|{dom}|{typ} draw {i}: {why}: ones {ins} zeros {outs}")

    cs = {n: Check(n) for n in ["C-states-struct", "C-states-lengths", "C-gold-states"]}
    C.update(cs)
    try:
        c_states(cs["C-states-struct"], cs["C-states-lengths"], cs["C-gold-states"])
    except Exception as ex:
        cs["C-states-struct"].failed += 1
        cs["C-states-struct"].fail(f"verifier exception in C-states: {ex!r} | {traceback.format_exc(limit=3).strip().splitlines()[-1]}")

    def c_rows(c_csv, c_sess, c_sig):
        """Every draws.csv row against the saved states: family tags, invested weeks, spell counts and lengths, sessions invested, gold BUY weeks and spells, sleeve trades."""
        if draws is None:
            for cc in (c_csv, c_sess):
                E.get("draws.csv", cc)
            return
        for key, g_ in draws.groupby(["book", "window", "cash", "cost_bps", "family", "sleeve_mode"]):
            p, w, ca, cst, fam, mode = key
            if fam not in FAMILY or w not in WINDOWS or p not in BOOKS_:
                c_csv.compared += 1; c_csv.failed += 1; c_csv.fail(f"unexpected row group {key}"); continue
            io_t, go_t = FAMILY[fam]
            fi, fg = feat(p, w, "io", io_t), feat(p, w, "gold", go_t)
            if fi is None or fg is None:
                c_csv.miss(f"draw_states.npz arrays for family {fam} of {p}|{w}"); continue
            R = D["rule"][p][w]
            ids = g_["draw_id"].values.astype(int)
            okid = (ids >= 0) & (ids < min(fi.n if io_t != "real" else 10 ** 9, fg.n if go_t != "real" else 10 ** 9))
            c_csv.compared += len(g_); c_csv.failed += int((~okid).sum())
            if (~okid).any():
                c_csv.fail(f"{key}: draw_id outside the saved states"); g_ = g_[okid]; ids = ids[okid]
            ii = ids if io_t != "real" else np.zeros(len(ids), dtype=int)
            ig = ids if go_t != "real" else np.zeros(len(ids), dtype=int)
            for col, want in (("io_null", io_t), ("gold_null", go_t)):
                if col not in g_.columns:
                    c_csv.miss(f"draws.csv column {col}"); continue
                bad = (g_[col].astype(str).values != want)
                c_csv.compared += len(g_); c_csv.failed += int(bad.sum())
                if bad.any(): c_csv.fail(f"{key}: {col} {g_[col].iloc[int(np.argmax(bad))]!r} != {want!r} for family {fam}")
            if mode == "fixed50":
                slt = np.zeros(len(ids), dtype=int)
            else:
                slt = sleeve_trade_counts(fi.arr[ii].astype(int), fg.arr[ig].astype(int))
            pairs = [("invested_weeks", fi.w1[ii], False), ("n_in_spells", fi.n1[ii], False), ("n_out_spells", fi.n0[ii], False),
                     ("in_lengths", fi.s1[ii], True), ("out_lengths", fi.s0[ii], True),
                     ("g_buy_weeks", fg.w1[ig], False), ("n_buy_spells", fg.n1[ig], False), ("n_sell_spells", fg.n0[ig], False),
                     ("g_buy_lengths", fg.s1[ig], True), ("g_sell_lengths", fg.s0[ig], True), ("sleeve_trades", slt, False)]
            bad_any = np.zeros(len(g_), dtype=bool)
            first_msg = None
            for col, want, isstr in pairs:
                if col not in g_.columns:
                    c_csv.miss(f"draws.csv column {col}"); continue
                if isstr:
                    bc = g_[col].astype(str).str.strip().values != want
                else:
                    bc = g_[col].astype(float).values != want.astype(float)
                c_csv.compared += len(g_)
                if bc.any() and first_msg is None:
                    i0 = int(np.argmax(bc)); first_msg = f"{key} id {ids[i0]} col {col}: evidence {g_[col].iloc[i0]!r} vs states {want[i0]!r}"
                bad_any |= bc
                c_csv.failed += int(bc.sum())
            if first_msg: c_csv.fail(first_msg)
            if fi.sess is None or "sessions_invested" not in g_.columns:
                c_sess.miss("draws.csv column sessions_invested")
            else:
                bc = g_["sessions_invested"].astype(float).values != fi.sess[ii].astype(float)
                c_sess.compared += len(g_); c_sess.failed += int(bc.sum())
                if bc.any():
                    i0 = int(np.argmax(bc)); c_sess.fail(f"{key} id {ids[i0]}: sessions_invested evidence {g_['sessions_invested'].iloc[i0]!r} vs verifier {fi.sess[ii][i0]!r}")
            if "sessions" in g_.columns:
                bc = g_["sessions"].astype(float).values != float(R["sessions"])
                c_sess.compared += len(g_); c_sess.failed += int(bc.sum())
                if bc.any(): c_sess.fail(f"{key}: sessions column {g_['sessions'].iloc[int(np.argmax(bc))]!r} vs window {R['sessions']}")
            # the signature columns: an N4.9 (or N4.9-g) draw has the real series' spell lengths, so the two signatures must agree (informational)
            if fam == "F2" and {"spell_sig", "strategy_sig"} <= set(g_.columns):
                bc = g_["spell_sig"].astype(str).values != g_["strategy_sig"].astype(str).values
                c_sig.compared += len(g_); c_sig.failed += int(bc.sum())
                if bc.any(): c_sig.fail(f"{key}: spell_sig != strategy_sig on an N4.9 draw")
            if fam == "F4" and {"g_spell_sig", "real_g_spell_sig"} <= set(g_.columns):
                bc = g_["g_spell_sig"].astype(str).values != g_["real_g_spell_sig"].astype(str).values
                c_sig.compared += len(g_); c_sig.failed += int(bc.sum())
                if bc.any(): c_sig.fail(f"{key}: g_spell_sig != real_g_spell_sig on an N4.9-g draw")

    cs2 = {n: Check(n, gate=g_) for n, g_ in [("C-states-csv", True), ("C-states-sessions", True), ("C-signatures", False)]}
    C.update(cs2)
    try:
        c_rows(cs2["C-states-csv"], cs2["C-states-sessions"], cs2["C-signatures"])
    except Exception as ex:
        cs2["C-states-csv"].failed += 1
        cs2["C-states-csv"].fail(f"verifier exception in C-states-csv: {ex!r} | {traceback.format_exc(limit=3).strip().splitlines()[-1]}")

    def c_cover(c):
        if draws is None:
            E.get("draws.csv", c); return
        gb = {k: v for k, v in draws.groupby(["book", "window", "cash", "cost_bps", "family", "sleeve_mode"])}
        exp = [(p, w, ca, round(cst, 4), fam, mode) for (p, w, ca, cst, fam, mode) in expected_groups() if p in BOOKS_]
        for k in exp:
            c.compared += 1
            g_ = gb.get(k)
            if g_ is None:
                c.miss(f"draws.csv group {k}"); continue
            ids = g_["draw_id"].values
            if len(ids) != nd_draws or set(ids.tolist()) != set(range(nd_draws)):
                c.failed += 1; c.fail(f"draws.csv group {k}: {len(ids)} rows, ids not exactly 0..{nd_draws - 1}")
        extra = set(gb) - set(exp)
        c.notes.append(f"{len(exp)} expected (book, window, cash, cost, family, mode) groups; unexpected groups present: {len(extra)}")
        if extra:
            c.compared += 1; c.failed += 1; c.fail(f"unexpected draws.csv groups: {sorted(extra)[:3]}")
        # the saved curves: one per F1 and F3 draw of every book (headline run)
        if curves_npz is not None:
            have = set(curves_npz.files)
            for p in BOOKS_:
                for fam in ("F1", "F3"):
                    for i in range(nd_draws):
                        c.compared += 1
                        if f"{p}|{fam}_{i}" not in have:
                            c.missing += 1
                            if c.first_fail is None: c.fail(f"MISSING: curve {p}|{fam}_{i}")
        else:
            E.get("draw_curves_20.8.npz", c)
    run_check(C, "C-draws-coverage", c_cover)

    # ------------------------------------------------------------------ regeneration from the seeds (N4.9 and N4.9-g gate; N4.10 / N4.10-g gate too: T06's own draws reproduced)
    REGEN = {}

    def regen_n49(p, window, dom, n):
        key = ("n49", p, window, dom, n)
        if key not in REGEN:
            R = D["rule"][p][window]
            s, sb = (R["states"], SEEDS["n49"]) if dom == "io" else (R["gstates"], SEEDS["n49g"])
            REGEN[key] = np.array([n49_states(s, sb, i) for i in range(n)])
        return REGEN[key]

    def regen_n410(p, window, dom, n):
        key = ("n410", p, window, dom, n)
        if key not in REGEN:
            R = D["rule"][p][window]
            rule = D["rule"][p]
            if dom == "io":
                k1, S1, h1, k0, S0, h0, fs, sb = R["in_spells"], R["S_in"], rule["hi_in"], R["out_spells"], R["S_out"], rule["hi_out"], R["first_state"], SEEDS["n410"]
            else:
                G = R["g"]
                k1, S1, h1, k0, S0, h0, fs, sb = G["in_spells"], G["S_in"], rule["hi_buy"], G["out_spells"], G["S_out"], rule["hi_sell"], G["first_state"], SEEDS["n410g"]
            tabs = {(k1, S1, h1): ways_table(k1, S1, LO, h1), (k0, S0, h0): ways_table(k0, S0, LO, h0)}
            REGEN[key] = np.array([n410_states_own(fs, k1, S1, h1, k0, S0, h0, sb, i, tabs) for i in range(n)])
        return REGEN[key]

    def c_regen(c, which):
        if states_npz is None:
            E.get("draw_states.npz", c); return
        for p in BOOKS_:
            for window in WINDOWS:
                for dom, typ in ((("io", "N4.9"), ("gold", "N4.9-g")) if which == "n49" else (("io", "N4.10"), ("gold", "N4.10-g"))):
                    arr = states_of(p, window, dom, typ)
                    if arr is None:
                        c.miss(f"draw_states.npz key {p}|{window}|{dom}|{typ}"); continue
                    mine_ = (regen_n49 if which == "n49" else regen_n410)(p, window, dom, arr.shape[0])
                    c.compared += arr.shape[0]
                    if mine_.shape != arr.shape:
                        c.failed += arr.shape[0]; c.fail(f"{p}|{window}|{dom}|{typ}: shape {arr.shape} vs regenerated {mine_.shape}"); continue
                    bad = np.flatnonzero((mine_ != arr).any(axis=1))
                    c.failed += len(bad)
                    if len(bad):
                        c.fail(f"{p}|{window}|{dom}|{typ} draw {int(bad[0])}: states differ from the verifier's own regeneration from the seed ({len(bad)} of {arr.shape[0]} draws)")
    run_check(C, "C-n49-regen", lambda c: c_regen(c, "n49"))
    run_check(C, "C-n410-regen", lambda c: c_regen(c, "n410"))

    # ------------------------------------------------------------------ C-draw-nav
    VIEW = {("full", "lbes"): ("V", "dec_idx"), ("full", "liq"): ("Vliq", "dec_idx"), ("live", "lbes"): ("Vlive", "dec_idx_live")}

    def c_draw_nav(c):
        if draws is None or states_npz is None:
            E.get("draws.csv", c); E.get("draw_states.npz", c); return
        idx = draws.set_index(["book", "window", "cash", "cost_bps", "family", "sleeve_mode", "draw_id"]).sort_index()
        cols = STAT_COLS_ALL
        curve_chk = [0.0, 0]
        nsim = 0

        def compare_row(key, r):
            if key not in idx.index:
                c.miss(f"draws.csv row {key}"); return
            row = idx.loc[key]
            if isinstance(row, pd.DataFrame):
                row = row.iloc[0]
            st = stats_of(r["nav"])
            for col in cols:
                if col not in row.index:
                    continue
                c.compared += 1
                dv = float(abs(st[col] - float(row[col])) / max(abs(float(row[col])), 1e-12))
                c.worst_rel = max(c.worst_rel, dv)
                if dv > TOL:
                    c.failed += 1; c.fail(f"{key} {col}: verifier {st[col]!r} vs draws.csv {row[col]!r}")

        for (p, w, ca, cst, fam, mode) in expected_groups():
            if p not in BOOKS_:
                continue
            io_t, go_t = FAMILY[fam]
            fi, fg = feat(p, w, "io", io_t), feat(p, w, "gold", go_t)
            if fi is None or fg is None:
                c.miss(f"states for family {fam} of {p}|{w}"); continue
            navail = min(fi.n if io_t != "real" else 10 ** 9, fg.n if go_t != "real" else 10 ** 9)
            bk = D["books"][p]
            vname, dname = VIEW[(w, ca)]
            R = D["rule"][p][w]
            for i in [x for x in sample_ids(p, (w, fam, mode), pool=nd_draws) if x < navail]:
                s_i = (fi.arr[i] if io_t != "real" else fi.arr[0]).astype(int)
                g_i = (fg.arr[i] if go_t != "real" else fg.arr[0]).astype(int)
                r = SIMS.run(bk[vname], s_i, cst, bk[dname], gws_of(g_i, mode), (p, w, ca))
                nsim += 1
                compare_row((p, w, ca, round(cst, 4), fam, mode, i), r)
                if (w, ca, mode, fam) == ("full", "lbes", "timed", fam) and fam in ("F1", "F3") and abs(cst - HEADLINE_COST) < 1e-9:
                    if curves_npz is None:
                        E.get("draw_curves_20.8.npz", c); continue
                    ck = f"{p}|{fam}_{i}"
                    c.compared += 1
                    if ck not in curves_npz.files:
                        c.missing += 1; c.fail(f"MISSING: curve {ck} in draw_curves_20.8.npz")
                    else:
                        cu = curves_npz[ck].astype(float)
                        if cu.shape != r["nav"].shape:
                            c.failed += 1; c.fail(f"curve {ck}: shape {cu.shape} vs {r['nav'].shape}")
                        else:
                            rr = float(np.max(np.abs(cu - r["nav"]) / np.abs(r["nav"])))
                            curve_chk[0] = max(curve_chk[0], rr); curve_chk[1] += 1
                            if rr > TOL_CURVE:
                                c.failed += 1; c.fail(f"curve {ck}: max relative difference {rr:.2e} > {TOL_CURVE}")
        c.notes.append(f"{nsim} draws re-simulated; {curve_chk[1]} draw curves compared at 20.8 bps; worst relative difference {curve_chk[0]:.2e} (float32 tolerance {TOL_CURVE})")
    run_check(C, "C-draw-nav", c_draw_nav)



    # ------------------------------------------------------------------ C-count, C-support, C-sampler
    def table_rows():
        rows = []
        for p in BOOKS_:
            rule = D["rule"][p]
            for window in WINDOWS:
                R = rule[window]
                G = R["g"]
                for series, state, k, S, hi in (("io", "in", R["in_spells"], R["S_in"], rule["hi_in"]), ("io", "out", R["out_spells"], R["S_out"], rule["hi_out"]),
                                               ("gold", "buy", G["in_spells"], G["S_in"], rule["hi_buy"]), ("gold", "sell", G["out_spells"], G["S_out"], rule["hi_sell"])):
                    rows.append(dict(book=p, window=window, series=series, state=state, k=k, S=S, lo=LO, hi=hi, n_ways=n_ways(k, S, LO, hi)))
        return rows
    D["count_rows"] = table_rows()

    def c_count(c):
        ct = E.get("count_table.json", c)
        mine = D["count_rows"]
        if ct is not None:
            tabs = ct.get("tables", {})
            for r in mine:
                key = f"{r['book']}|{r['window']}|{r['series']}|{r['state']}"
                c.compared += 1
                l = tabs.get(key)
                if l is None:
                    c.miss(f"count_table.json table {key}"); continue
                try:
                    kk = l["k"] if "k" in l else l["spells_k"]
                    SS = l["S"] if "S" in l else l["weeks_S"]
                    ok = (int(str(l["n_ways"])) == r["n_ways"] and int(kk) == r["k"] and int(SS) == r["S"] and int(l["lo"]) == r["lo"] and int(l["hi"]) == r["hi"])
                except Exception:
                    ok = False
                if not ok:
                    c.failed += 1; c.fail(f"{key}: count table {l} vs verifier k={r['k']} S={r['S']} lo={r['lo']} hi={r['hi']} n_ways={r['n_ways']}")
            extra = set(tabs) - {f"{r['book']}|{r['window']}|{r['series']}|{r['state']}" for r in mine}
            c.notes.append(f"count_table.json has {len(tabs)} tables; tables the verifier does not know: {len(extra)}")
            # the bounds block
            b = ct.get("bounds")
            c.compared += 1
            rule0 = D["rule"][BOOKS_[0]]
            want = dict(io=dict(lo=LO, hi_in=rule0["hi_in"], hi_out=rule0["hi_out"]), gold=dict(lo_buy=LO, hi_buy=rule0["hi_buy"], lo_sell=LO, hi_sell=rule0["hi_sell"]))
            if b is None:
                c.miss("count_table.json 'bounds'")
            elif {k_: {x: int(y) for x, y in v_.items()} for k_, v_ in b.items()} != want:
                c.failed += 1; c.fail(f"count_table.json bounds {b} vs verifier {want}")
        # V5(b): the formula against a plain DP, for every table
        for r in mine:
            c.compared += 1
            dp = ways_table(r["k"], r["S"], r["lo"], r["hi"])[r["k"]][r["S"]]
            if dp != r["n_ways"]:
                c.failed += 1; c.fail(f"{r['book']}|{r['window']}|{r['series']}|{r['state']}: inclusion-exclusion {r['n_ways']} vs DP {dp}")
        c.compared += 1
        if n_ways(3, 12, 2, 6) != 19:
            c.failed += 1; c.fail(f"inclusion-exclusion gives {n_ways(3, 12, 2, 6)} for k=3,S=12,[2,6]; T08.md says 19")
        # the pre-registered counts of Step 1 (T08.md section 2 / logs/step_1_spell_counts.json)
        if STEP1_JSON.exists():
            s1 = json.load(open(STEP1_JSON))
            for f in s1["feasibility"]:
                if f["book"] not in BOOKS_:
                    continue
                m = [r for r in mine if r["book"] == f["book"] and r["window"] == f["window"] and r["series"] == f["series"] and r["state"] == f["state"]]
                c.compared += 1
                if not m or str(m[0]["n_ways"]) != str(f["n_ways"]) or m[0]["k"] != f["k"] or m[0]["S"] != f["S"] or m[0]["hi"] != f["hi"]:
                    c.failed += 1; c.fail(f"step_1_spell_counts.json {f} differs from the verifier's inclusion-exclusion count {m[:1]}")
        else:
            c.notes.append("logs/step_1_spell_counts.json not found; pre-registered counts not compared")
    run_check(C, "C-count", c_count)

    def c_spells_step1(c):
        """The real series' structure (derived here from the raw files) equals the pre-registered Step 1 counts (T08.md section 2)."""
        if not STEP1_JSON.exists():
            c.notes.append("logs/step_1_spell_counts.json not found"); return
        s1 = json.load(open(STEP1_JSON))
        c.compared += 1
        if s1["window_end"] != str(D["END"].date()):
            c.failed += 1; c.fail(f"window end {D['END'].date()} vs step 1 {s1['window_end']}")
        for p in BOOKS_:
            for window in WINDOWS:
                R = D["rule"][p][window]
                G = R["g"]
                e = s1["books"][p][window]
                pairs = [("weeks", R["weeks"]), ("first_state", R["first_state"]), ("last_state", R["last_state"]), ("in_spells", R["in_spells"]),
                         ("out_spells", R["out_spells"]), ("S_in", R["S_in"]), ("S_out", R["S_out"]), ("in_lengths", R["in_lengths"]), ("out_lengths", R["out_lengths"]),
                         ("longest_in", R["longest_in"]), ("longest_out", R["longest_out"]), ("start", R["start"]), ("end", R["end"]),
                         ("g_first_state", G["first_state"]), ("g_last_state", G["last_state"]), ("g_buy_spells", G["in_spells"]), ("g_sell_spells", G["out_spells"]),
                         ("g_S_buy", G["S_in"]), ("g_S_sell", G["S_out"]), ("g_buy_lengths", G["in_lengths"]), ("g_sell_lengths", G["out_lengths"]),
                         ("g_weeks_buy_while_out", int(((R["gstates"] == 1) & (R["states"] == 0)).sum())),
                         ("g_weeks_sell_while_out", int(((R["gstates"] == 0) & (R["states"] == 0)).sum())),
                         ("g_flips_while_out_both_sides", R["sleeve_trades"]),
                         ("round_trips", min(R["in_spells"], R["out_spells"]))]
                # gold spells that contain at least one OUT week
                gr = runs_of(R["gstates"])
                pos, n_with = 0, 0
                for v_, l_ in gr:
                    if (R["states"][pos:pos + l_] == 0).any():
                        n_with += 1
                    pos += l_
                pairs.append(("g_spells_with_an_out_week", n_with))
                pairs.append(("g_shortest", min(l_ for _, l_ in gr)))
                pairs.append(("g_flips", len(gr) - 1))
                for k_, mv in pairs:
                    if k_ not in e:
                        continue
                    c.compared += 1
                    if mv != e[k_]:
                        c.failed += 1; c.fail(f"{p}|{window} {k_}: verifier {mv!r} vs step_1_spell_counts.json {e[k_]!r}")
        for p in BOOKS_:
            c.compared += 1
            if D["meta"][p]["raw_gold_sessions_after_mcx"] != s1["books"][p]["full"].get("sessions_after_mcx_range_end", D["meta"][p]["raw_gold_sessions_after_mcx"]):
                c.failed += 1; c.fail(f"{p}: raw-fill sessions {D['meta'][p]['raw_gold_sessions_after_mcx']} vs step 1 {s1['books'][p]['full'].get('sessions_after_mcx_range_end')}")
    run_check(C, "C-spells-step1", c_spells_step1)

    def c_support(c):
        """The rule's own lengths lie within the bounds (so every N4.9 / N4.9-g draw is an allowed N4.10 / N4.10-g configuration), the tables are feasible
        (lo*k <= S <= hi*k), the bounds are the spec's (46 / 40; BUY 68, SELL 28), and the reportability gate holds."""
        rule0 = D["rule"][BOOKS_[0]]
        for nm, got, want in (("hi_in", rule0["hi_in"], EXPECT_BOUNDS["io"]["hi_in"]), ("hi_out", rule0["hi_out"], EXPECT_BOUNDS["io"]["hi_out"]),
                              ("hi_buy", rule0["hi_buy"], EXPECT_BOUNDS["gold"]["hi_buy"]), ("hi_sell", rule0["hi_sell"], EXPECT_BOUNDS["gold"]["hi_sell"])):
            c.compared += 1
            if got != want:
                c.failed += 1; c.fail(f"derived bound {nm} = {got} but the spec fixes {want}")
        for p in BOOKS_:
            rule = D["rule"][p]
            for window in WINDOWS:
                R = rule[window]
                G = R["g"]
                shortest = min(min(R["in_lengths"]), min(R["out_lengths"]), min(G["in_lengths"]), min(G["out_lengths"]))
                for nm, lens, hi in (("in", R["in_lengths"], rule["hi_in"]), ("out", R["out_lengths"], rule["hi_out"]),
                                     ("buy", G["in_lengths"], rule["hi_buy"]), ("sell", G["out_lengths"], rule["hi_sell"])):
                    c.compared += 1
                    ok = all(LO <= l <= hi for l in lens) and LO * len(lens) <= sum(lens) <= hi * len(lens)
                    if not ok:
                        c.failed += 1; c.fail(f"{p}|{window}|{nm}: the real lengths {lens} are outside [{LO}, {hi}] or the totals cannot be split within the bounds")
                c.compared += 1
                if min(R["in_spells"], R["out_spells"]) < 4:
                    c.failed += 1; c.fail(f"{p}|{window}: fewer than 4 round trips of the in-or-out switch")
                gr = runs_of(R["gstates"])
                pos, n_with = 0, 0
                for v_, l_ in gr:
                    if (R["states"][pos:pos + l_] == 0).any():
                        n_with += 1
                    pos += l_
                c.compared += 1
                if n_with < 4:
                    c.failed += 1; c.fail(f"{p}|{window}: fewer than 4 gold spells containing an OUT week")
                c.compared += 1
                if shortest < LO:
                    c.failed += 1; c.fail(f"{p}|{window}: a real spell of length {shortest} is shorter than the lower bound {LO}")
    run_check(C, "C-support", c_support)

    def c_sampler(c):
        """V5: (a) the verifier's own sampler passes the chi-square on the 19-tuple case; (b) the DP equals the formula (C-count); (c) over the saved N4.10 / N4.10-g
        draws the mean length at every position is within 4 standard errors of S / k (the exact mean of an exchangeable uniform tuple)."""
        st = sampler_selftest()
        c.compared += 2
        if not st["all_seen"] or st["n_ways_formula"] != 19 or st["n_ways_dp"] != 19:
            c.failed += 1; c.fail(f"sampler self-test enumeration wrong: {st}")
        if st["p"] is not None and st["p"] <= 0.001:
            c.failed += 1; c.fail(f"the verifier's own sampler fails the chi-square (p = {st['p']:.4g})")
        c.notes.append(f"own-sampler chi-square on 19 tuples: chi2 = {st['chi2']:.2f} (df {st['df']}), p = {st['p']}; samples {st['n_samples']}")
        # the engine's own self-test file, if it holds a chi-square p-value
        stj = E.get("sampler_selftest.json")
        if stj is not None:
            ps = []

            def walk(o, k=""):
                if isinstance(o, dict):
                    for kk, vv in o.items():
                        walk(vv, kk)
                elif isinstance(o, (int, float)) and not isinstance(o, bool) and ("p" == k or "p_value" in k or k.endswith("_p") or "pvalue" in k):
                    ps.append((k, float(o)))
            walk(stj)
            for k, v in ps:
                c.compared += 1
                if v <= 0.001:
                    c.failed += 1; c.fail(f"sampler_selftest.json {k} = {v} <= 0.001")
            c.notes.append(f"sampler_selftest.json: {len(ps)} p-value(s) read")
        if states_npz is None:
            E.get("draw_states.npz", c); return
        worst = 0.0
        for p in BOOKS_:
            rule = D["rule"][p]
            for window in WINDOWS:
                R = rule[window]
                G = R["g"]
                for dom, typ, RR, hi1, hi0 in (("io", "N4.10", R, rule["hi_in"], rule["hi_out"]), ("gold", "N4.10-g", G, rule["hi_buy"], rule["hi_sell"])):
                    f = feat(p, window, dom, typ)
                    if f is None:
                        c.miss(f"states {p}|{window}|{dom}|{typ}"); continue
                    for nm, k, S, hi, lens_all in (("ones", RR["in_spells"], RR["S_in"], hi1, f.ones), ("zeros", RR["out_spells"], RR["S_out"], hi0, f.zeros)):
                        if any(len(x) != k for x in lens_all):
                            c.failed += 1; c.fail(f"{p}|{window}|{dom}|{typ}|{nm}: draws do not all have {k} spells"); continue
                        mu, var = first_part_moments(k, S, LO, hi)
                        lens = np.array(lens_all)
                        se = math.sqrt(var / len(lens))
                        for pos in range(k):
                            c.compared += 1
                            z = abs(lens[:, pos].mean() - S / k) / se
                            worst = max(worst, z)
                            if z > 4.0:
                                c.failed += 1; c.fail(f"{p}|{window}|{dom}|{typ}|{nm} part {pos}: sample mean {lens[:, pos].mean():.3f} vs exact {S / k:.3f}, z = {z:.1f}")
        c.worst_rel = max(c.worst_rel, worst)
        c.notes.append("worst_rel in this check is the largest |z| (standard errors) over the positions")
    run_check(C, "C-sampler", c_sampler)

    # ------------------------------------------------------------------ C-percentile
    D["percentiles"] = []

    def c_percentile(c):
        if draws is None:
            E.get("draws.csv", c); return
        rows = []
        for (p, w, ca, cst, fam, mode), g_ in draws.groupby(["book", "window", "cash", "cost_bps", "family", "sleeve_mode"]):
            kind = "strategy" if mode == "timed" else "strategy_fixed50"
            m = mst[(mst["book"] == p) & (mst["window"] == w) & (mst["cash"] == ca) & (mst["cost_bps"] == cst) & (mst["kind"] == kind)]
            if not len(m):
                continue
            row = dict(book=p, window=w, cash=ca, cost_bps=float(cst), family=fam, mode=mode, n_draws=len(g_))
            for stat, hb in STAT_DIR.items():
                if stat not in g_.columns:
                    continue
                x = float(m[stat].iloc[0])
                pc, pv = pct_and_p(x, g_[stat].values, hb)
                pc2, pv2 = pct_and_p_loop(x, g_[stat].values, hb)
                c.compared += 1
                d_ = max(abs(pc - pc2), abs(pv - pv2))
                c.worst_rel = max(c.worst_rel, d_)
                if d_ > 1e-9:
                    c.failed += 1; c.fail(f"{p} {w} {ca} {cst} {fam} {mode} {stat}: vectorised percentile {pc!r}/{pv!r} vs loop {pc2!r}/{pv2!r}")
                row[f"{stat}_pctile"] = pc; row[f"{stat}_p"] = pv
            rows.append(row)
        D["percentiles"] = rows
        c.notes.append("worst_rel in this check is the largest difference between the two own implementations")
    run_check(C, "C-percentile", c_percentile)

    def c_percentile_log(c):
        """Informational: does analysis.log (if it exists) print each headline percentile (20.8 bps, LBES, full window, timed sleeve)?"""
        cand = [E.dir / "analysis.log", E.dir.parent / "analysis.log", E.dir.parent.parent / "analysis.log"]
        logp = next((x for x in cand if x.exists()), None)
        if logp is None:
            c.notes.append("analysis.log not found beside the evidence (not required by the spec); nothing compared")
            return
        txt = logp.read_text(encoding="utf-8", errors="replace")
        nums = set(re.findall(r"\d+\.\d+", txt))
        for r in D["percentiles"]:
            if r["window"] == "full" and r["cash"] == "lbes" and r["mode"] == "timed" and abs(r["cost_bps"] - HEADLINE_COST) < 1e-9 and r["family"] in ("F1", "F2", "F3", "F4"):
                for stat in ("cagr", "max_dd"):
                    v = r.get(f"{stat}_pctile")
                    if v is None:
                        continue
                    c.compared += 1
                    if not any(f"{v:.{nd}f}" in nums for nd in (1, 2)):
                        c.failed += 1; c.fail(f"{r['book']} {r['family']} {stat} percentile {v:.2f} not printed in {logp.name}")
        c.notes.append(f"read {logp}")
    run_check(C, "C-percentile-log", c_percentile_log, gate=False)

    # ------------------------------------------------------------------ the engine's own gate files (read, not trusted: V2-V6 flags must not be False)
    def c_engine_files(c):
        reg = E.get("regression_t06.json", c)
        if reg is not None:
            c.compared += 1
            if reg.get("pass") is False:
                c.failed += 1; c.fail("regression_t06.json says pass = false")
        A = E.get("audit.json")
        if A is not None:
            gates = A.get("gates")
            if isinstance(gates, dict):
                for k, v in gates.items():
                    c.compared += 1
                    if v is False:
                        c.failed += 1; c.fail(f"audit.json gate {k} = false")
            else:
                c.notes.append("audit.json has no 'gates' dict")
            # sleeve trades / raw-fill sessions, wherever the audit keeps them
            hits = []

            def walk(o, path=""):
                if isinstance(o, dict):
                    for kk, vv in o.items():
                        walk(vv, path + "/" + str(kk))
                elif isinstance(o, (int, float)) and not isinstance(o, bool):
                    hits.append((path, o))
            walk(A)
            for path, v in hits:
                low = path.lower()
                if "raw" in low and "session" in low and "trade" not in low:
                    c.compared += 1
                    want = D["meta"][BOOKS_[0]]["raw_gold_sessions_after_mcx"]
                    if int(v) != want:
                        c.failed += 1; c.fail(f"audit.json {path} = {v} but the verifier counts {want} raw-fill sessions")
                for p in BOOKS_:
                    # constant_g* entries are the engine's own what-if (gold signal held constant, 0 sleeve trades by construction), not the real rule's count
                    if p in path and "sleeve_trades" in low and "live" not in low and "draw" not in low and "constant_g" not in low:
                        c.compared += 1
                        if int(v) != D["meta"][p]["sleeve_trades"]:
                            c.failed += 1; c.fail(f"audit.json {path} = {v} but the verifier counts {D['meta'][p]['sleeve_trades']} sleeve trades")
    run_check(C, "C-engine-files", c_engine_files)

    # ------------------------------------------------------------------ C-audit (tolerant: compares the keys it knows)
    def c_audit(c):
        A = E.get("audit.json", c)
        if A is None:
            return
        books = A.get("books", A)
        for p in BOOKS:
            if p not in books:
                c.miss(f"{p} in audit.json"); continue
            a = books[p]; m = D["meta"][p]
            pairs = [("t0", m["t0"]), ("sessions", m["sessions"]), ("decisions", m["decisions"]), ("invested_weeks", m["invested_weeks"]),
                     ("in_spells", m["in_spells"]), ("out_spells", m["out_spells"]), ("round_trips", min(m["in_spells"], m["out_spells"])),
                     ("initial_basket_switch_session", m["initial_basket_switch_session"]), ("skipped_baskets_dropped", m["dropped"])]
            for nm, mv in pairs:
                if nm in a:
                    c.compared += 1
                    if a[nm] != mv:
                        c.failed += 1; c.fail(f"{p} {nm}: verifier={mv!r} audit.json={a[nm]!r}")
            for k_, v_ in a.items():
                if k_.startswith("v2_") and k_.endswith("_checked"):
                    c.compared += 1
                    if not (isinstance(v_, (int, float)) and v_ > 0):
                        c.failed += 1; c.fail(f"{p} {k_} = {v_!r}: V2 needs a count > 0")
                if k_.startswith("v2_") and ("after_decision" in k_ or "not_after" in k_):
                    c.compared += 1
                    if v_ != 0:
                        c.failed += 1; c.fail(f"{p} {k_} = {v_!r}: V2 violations must be 0")
    run_check(C, "C-audit", c_audit)


    return C


def summarise(C):
    gate_fail = sum(c.failed + c.missing for c in C.values() if c.gate)
    gate_compared = sum(c.compared for c in C.values() if c.gate)
    return gate_compared, gate_fail


def print_table(C, title):
    print(f"\n=== {title} ===")
    print(f"{'check':28s} {'compared':>10s} {'failed':>8s} {'missing':>8s} {'worst':>10s}  gate")
    for c in C.values():
        print(f"{c.name:28s} {c.compared:10d} {c.failed:8d} {c.missing:8d} {c.worst_rel:10.2e}  {'yes' if c.gate else 'info'}")
        if c.first_fail:
            print(f"    first problem: {c.first_fail}")



# ----------------------------------------------------------------------------------------
# self-test: a corrupted copy must be detected
# ----------------------------------------------------------------------------------------
def _widen_first_spell(arr_row, first_state, hi_first_state_spell):
    """Return a state row whose first spell of the value 1 (counted among the 1-spells) is hi+1 weeks long, the extra weeks taken from the next
    1-spells (totals unchanged), keeping every other spell's length at least 2 where possible."""
    sp = spells_of_rows(arr_row[None, :])[0]
    ones, zeros = list(sp[0]), list(sp[1])
    remaining = (hi_first_state_spell + 1) - ones[0]
    ones[0] = hi_first_state_spell + 1
    for jj in range(1, len(ones)):
        take = min(remaining, ones[jj] - 1)
        ones[jj] -= take; remaining -= take
        if remaining == 0:
            break
    return states_from_lengths(first_state, ones, zeros), ones, zeros


def corrupt_copy(ev, dst, D):
    """Seven corruptions: 5 decisions flipped; a NAV column x 1.001; one N4.10 in-or-out draw out of bounds (states and draws.csv); one N4.10-g gold draw out of
    bounds; 3 gold-signal weeks flipped (gold_signal.csv); one sleeve rebalance removed (sleeve_trades.csv); one F3 draw's end NAV x 1.001 (draws.csv)."""
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True)
    info = {}
    dpath = ev.path("decisions.csv")
    if dpath is not None:
        dec = pd.read_csv(dpath)
        rows = np.linspace(10, len(dec) - 10, 5).astype(int)
        dec.loc[rows, "state"] = 1 - dec.loc[rows, "state"]
        dec.to_csv(dst / "decisions.csv", index=False)
        info["flipped_decision_rows"] = rows.tolist()
    npath = ev.path("daily_nav.csv")
    if npath is not None:
        nav = pd.read_csv(npath)
        m = (nav["run"] == "strategy") & (nav["cost_bps"] == 0.0)
        nav.loc[m, "nav"] = nav.loc[m, "nav"] * 1.001
        nav.to_csv(dst / "daily_nav.csv", index=False)
        info["scaled_nav"] = "strategy, cost 0, x 1.001"
    spath = ev.path("draw_states.npz")
    wpath = ev.path("draws.csv")
    w = pd.read_csv(wpath, dtype=str) if wpath is not None else None
    if spath is not None:
        z = np.load(spath)
        data = {k: z[k] for k in z.files}
        p0 = "SCMO_0003"
        rule = D["rule"][p0]
        key = f"{p0}|full|io|N4.10"
        if key in data and data[key].shape[0] > 5:
            arr = data[key]
            new_row, ins, outs = _widen_first_spell(arr[5], int(arr[5][0]), rule["hi_in"])
            if len(new_row) == arr.shape[1]:
                arr[5] = new_row
                data[key] = arr
                info["corrupted_n410_draw"] = dict(key=key, draw_id=5, in_lengths=ins, out_lengths=outs)
                if w is not None:
                    msk = (w["book"] == p0) & (w["window"] == "full") & (w["io_null"] == "N4.10") & (w["draw_id"] == "5")
                    w.loc[msk, "in_lengths"] = "|".join(map(str, ins))
        key = f"{p0}|full|gold|N4.10-g"
        if key in data and data[key].shape[0] > 7:
            arr = data[key]
            new_row, buys, sells = _widen_first_spell(arr[7], int(arr[7][0]), rule["hi_buy"])
            if len(new_row) == arr.shape[1]:
                arr[7] = new_row
                data[key] = arr
                info["corrupted_n410g_draw"] = dict(key=key, draw_id=7, buy_lengths=buys, sell_lengths=sells)
                if w is not None:
                    msk = (w["book"] == p0) & (w["window"] == "full") & (w["gold_null"] == "N4.10-g") & (w["draw_id"] == "7")
                    w.loc[msk, "g_buy_lengths"] = "|".join(map(str, buys))
        np.savez(dst / "draw_states.npz", **data)
    if w is not None:
        msk = (w["book"] == "SCMO_0003") & (w["window"] == "full") & (w["cash"] == "lbes") & (w["family"] == "F3") & (w["sleeve_mode"] == "timed") \
              & (w["draw_id"] == "3") & (w["cost_bps"].astype(float) == HEADLINE_COST)
        if msk.any():
            w.loc[msk, "end_nav"] = (w.loc[msk, "end_nav"].astype(float) * 1.001).astype(str)
            info["scaled_draw_end_nav"] = "SCMO_0003 F3 draw 3, 20.8 bps, end_nav x 1.001"
        w.to_csv(dst / "draws.csv", index=False)
    gpath = ev.path("gold_signal.csv")
    if gpath is not None:
        gs = pd.read_csv(gpath)
        rows = gs.index[(gs["book"] == "SCMO_0003")][[40, 150, 300]]
        gs.loc[rows, "g"] = 1 - gs.loc[rows, "g"]
        gs.loc[rows, "gw"] = np.where(gs.loc[rows, "g"] == 1, GW_BUY, GW_SELL)
        gs.loc[rows, "sign_MAUc1"] = np.where(gs.loc[rows, "g"] == 1, "BUY", "SELL")
        gs.to_csv(dst / "gold_signal.csv", index=False)
        info["flipped_gold_weeks"] = [int(x) for x in gs.loc[rows, "j"]]
    spp = ev.path("sleeve_trades.csv")
    if spp is not None:
        st = pd.read_csv(spp)
        cand = st.index[(st["kind"] == "sleeve_rebalance") & (st["book"] == "SCMO_0003") & (st["cost_bps"].astype(float) == HEADLINE_COST)]
        if len(cand):
            st = st.drop(index=cand[0])
            st.to_csv(dst / "sleeve_trades.csv", index=False)
            info["removed_sleeve_trade"] = "SCMO_0003, 20.8 bps, first sleeve_rebalance"
    return info


# ----------------------------------------------------------------------------------------
EVIDENCE_FILES = ["inputs.csv", "decisions.csv", "gold_signal.csv", "stats.csv", "draws.csv", "draw_states.npz", "real_states.npz", "draw_curves_20.8.npz",
                  "trades.csv", "sleeve_trades.csv", "positions.csv", "daily_nav.csv", "g_engine.csv", "count_table.json", "sampler_selftest.json",
                  "regression_t06.json", "audit.json"]


def main():
    global N_DRAWS
    ap = argparse.ArgumentParser()
    ap.add_argument("--evidence", default=str(AA / "tests" / "T08" / "evidence" / "headline"))
    ap.add_argument("--no-selftest", action="store_true", help="skip the in-process corrupted-copy test")
    ap.add_argument("--out", default=None)
    ap.add_argument("--draws", type=int, default=2000, help="draws per row group the evidence must hold (2000 for the headline run)")
    ap.add_argument("--scratch", default=None, help="directory for the corrupted copy (default: a fresh temporary directory)")
    args = ap.parse_args()
    N_DRAWS = int(args.draws)
    evdir = Path(args.evidence)
    out = Path(args.out) if args.out else evdir / "verify_t08.json"
    t = time.time()
    D = derive()
    print(f"[{time.time()-t:6.1f}s] derivation complete", flush=True)
    E = Evidence(evdir)
    C = compare_all(D, E)
    print(f"[{time.time()-t:6.1f}s] comparison complete", flush=True)
    if E.missing_files:
        print("\nMISSING EVIDENCE FILES: " + ", ".join(sorted(set(E.missing_files))))
    for nm in EVIDENCE_FILES:                       # an expected file that no check touched is still reported as missing
        if E.path(nm) is None and nm not in E.missing_files:
            E.missing_files.append(nm)
    print_table(C, f"verifier vs evidence in {evdir}")
    gate_compared, gate_fail = summarise(C)
    extra_missing = sorted(set(E.missing_files))

    ai = D["always_in"]
    print("\n=== C-always-in (0 cost, whole window, model minus published, pp) ===")
    for p in BOOKS:
        a = ai[ai.book == p]
        ov = a[a.scope == "overall"].gap_pp.iloc[0]
        yy = a[~a.scope.isin(["overall", "overall_calendar_years"])]
        w = yy.iloc[int(yy.gap_pp.abs().values.argmax())]
        print(f"{p}: CAGR gap {ov:+.4f} pp/yr (limit {G0_OVERALL_PP}); worst calendar year {w.scope} {w.gap_pp:+.4f} pp (limit {G0_YEAR_PP})")

    if D["percentiles"]:
        print("\n=== recomputed percentiles (20.8 bps, LBES, full window, timed sleeve; pass mark 90) ===")
        for r in D["percentiles"]:
            if r["window"] == "full" and r["cash"] == "lbes" and r["mode"] == "timed" and abs(r["cost_bps"] - HEADLINE_COST) < 1e-9 and r["family"] in ("F1", "F2", "F3", "F4"):
                print(f"{r['book']} {r['family']} CAGR pctile {r['cagr_pctile']:7.2f} (p {r['cagr_p']:.4f})   max-DD pctile {r['max_dd_pctile']:7.2f} (p {r['max_dd_p']:.4f})")

    pct_real, count_real = D["percentiles"], D["count_rows"]
    selftest = None
    if not args.no_selftest:
        scratch = Path(args.scratch) if args.scratch else Path(tempfile.mkdtemp(prefix="verify_t08_"))
        cdir = scratch / "corrupt_evidence_t08"
        info = corrupt_copy(E, cdir, D)
        Ec = Evidence(cdir, fallback=evdir)
        Cc = compare_all(D, Ec)
        print_table(Cc, f"SELF-TEST: corrupted copy in {cdir} ({info})")
        cc, cf = summarise(Cc)
        by = {k: (v.failed + v.missing) for k, v in Cc.items()}
        wants = [("flipped_decision_rows", "C-dec", "decisions_flipped"), ("scaled_nav", "C-nav0", "nav_scaled"),
                 ("corrupted_n410_draw", "C-states-lengths", "n410_lengths_out_of_bounds"), ("corrupted_n410g_draw", "C-gold-states", "n410g_lengths_out_of_bounds"),
                 ("flipped_gold_weeks", "C-gold", "gold_weeks_flipped"), ("removed_sleeve_trade", "C-sleeve", "sleeve_trade_removed"),
                 ("scaled_draw_end_nav", "C-draw-nav", "draw_nav_scaled")]
        detected_by, applied = {}, {}
        for ikey, chk, label in wants:
            applied[label] = ikey in info
            detected_by[label] = by.get(chk, 0) > 0
        # a corruption that could not be applied (the evidence lacks the file) counts as not tested, and the self-test then cannot be passed
        detected = cf > 0 and all(applied.values()) and all(detected_by.values())
        selftest = dict(dir=str(cdir), corruptions=info, applied=applied, gate_compared=cc, gate_failures=cf, detected=bool(detected),
                        detected_by=detected_by, checks={k: v.to_dict() for k, v in Cc.items()})
        print(f"corrupted copy detected: {detected} (failures {cf}; applied {applied}; detected by {detected_by})")
        shutil.rmtree(cdir, ignore_errors=True)

    D["percentiles"], D["count_rows"] = pct_real, count_real
    ok_real = gate_compared > 0 and gate_fail == 0 and not extra_missing
    ok = ok_real and (selftest is None or selftest["detected"])
    rep = dict(verifier="analysis/verify_t08.py", evidence=str(evdir), draws_expected=N_DRAWS, end=str(D["END"].date()),
               gate_compared=int(gate_compared), gate_failures_and_missing=int(gate_fail),
               missing_evidence_files=extra_missing,
               checks={k: v.to_dict() for k, v in C.items()}, always_in=ai.to_dict(orient="records"),
               meta={p: D["meta"][p] for p in BOOKS}, rule={p: {w: {k: v for k, v in D["rule"][p][w].items() if k not in ("states", "gstates", "dec_idx", "cover")}
                                                                for w in ("full", "live")} for p in BOOKS},
               count_rows=[{**r, "n_ways": str(r["n_ways"])} for r in D["count_rows"]], percentiles=D["percentiles"],
               approved_data_files_read={k: v for k, v in READS.items()}, selftest=selftest, exit_ok=bool(ok),
               closed_form="NAV_end = prod over segments of (trade-day jump x fixed-unit segment growth)")
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(rep, indent=1, default=str))
        print(f"wrote {out}")
    except Exception as ex:
        print(f"could not write {out}: {ex!r}")
    print(f"\nrows compared (gate checks): {gate_compared}; failures + missing: {gate_fail}; real run ok: {ok_real}; exit ok: {ok}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
