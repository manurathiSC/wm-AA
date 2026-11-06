"""T06 independent verifier (Step 3).

Re-derives T06's decisions, NAVs, costs, trades, positions and null-draw results from the RAW files only
(plain numpy / pandas, its own loaders, its own cost, basket, counting and percentile code) and compares them
with the engine's evidence in tests/T06/evidence/<run>/.

It imports nothing from the engine or from any other module in analysis/ or data/. It never reads the engine's
source. The rules are those of tests/T06/logs/verifier_spec.md (T06.md sections 1-3 and PLAN_v2.md Step 3), which
keep T03's conventions (tests/T03/logs/verifier_spec.md) except where that spec lists a difference. Forked from
analysis/verify_t03.py.

Usage (from AA/):
    python analysis/verify_t06.py                                  # real run + self-test on a corrupted copy
    python analysis/verify_t06.py --evidence DIR --no-selftest     # compare against another evidence dir
    python analysis/verify_t06.py --out FILE

Exit code 0 only if rows were compared, none failed, none were missing, and (in the default run) the
deliberately corrupted copy was detected. A missing evidence file is reported as MISSING (a failure).
"""
import argparse
import hashlib
import json
import math
import re
import shutil
import sys
import time
import traceback
from fractions import Fraction
from pathlib import Path

import numpy as np
import pandas as pd

AA = Path(__file__).resolve().parents[1]
BOOKS = ["SCMO_0003", "SCMO_0007", "SCMO_0010", "SCMO_0029"]
COSTS = [0.0, 20.8, 50.0]
HEADLINE_COST = 20.8
TOL = 1e-9                  # relative tolerance on NAVs and statistics
TOL_REGRESSION = 1e-12      # T03 overlap, 0-cost path and costed paths (spec: 1e-12)
TOL_CURVE = 1e-5            # float32 draw curves
N_DRAWS = 2000
LIVE_START = pd.Timestamp("2021-11-01")
T03_NAV_CUTOFF = pd.Timestamp("2026-08-07")
G0_OVERALL_PP = 0.25
G0_YEAR_PP = 0.5
LO = 2                      # lower bound of every N4.10 spell, weeks
SCRATCH = Path(r"C:\Users\manur\AppData\Local\Temp\claude\d384933f9ddb0ecb\63ec6f8d-d6a9-4cf8-90aa-fe9e1e39fffc\scratchpad")
T03_EVIDENCE = AA / "tests" / "T03" / "evidence" / "headline"
STEP1_JSON = AA / "tests" / "T06" / "logs" / "step_1_spell_counts.json"
APPROVED_MD = AA / "data" / "APPROVED_DATA.md"
# approved rows whose through-date is deliberately earlier than the window's end (APPROVED_DATA.md "Latest usable date by role"):
# D12 de-spike range (later fills use the raw OHLC4), D19 / D05 basket weights and rebalance history (the newest baskets that exist;
# the last one stays in force to the window's end).
THROUGH_EXEMPT_IDS = {"D12", "D19", "D05"}


# ----------------------------------------------------------------------------------------
# APPROVED_DATA.md (own parser) and the registry of files this verifier reads
# ----------------------------------------------------------------------------------------
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
# raw loaders
# ----------------------------------------------------------------------------------------
def load_published_nav(p):
    d = pd.read_csv(rd(f"Historical Data/parent_nav_2026-10-22/{p}.csv"))
    d["date"] = pd.to_datetime(d["_id.date"], format="%Y/%m/%d")
    return d.set_index("date")["index"].sort_index()


def load_masters():
    out = {}
    for name in ["Nifty100", "MC100", "SC100"]:
        m = pd.read_excel(rd(f"Historical Data/extended_2026-10-30/Master/Master_{name}.xlsx"))
        m = m[["Date", "SIGN"]].copy()
        m["SIGN"] = m["SIGN"].astype("object")
        m = m[m["SIGN"].notna()]
        m["SIGN"] = m["SIGN"].astype(str).str.strip().str.upper()
        m = m[m["SIGN"] != ""]
        m["Date"] = pd.to_datetime(m["Date"])
        m = m.sort_values("Date").reset_index(drop=True)
        out[name] = (m["Date"].values, m["SIGN"].values)
    return out


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
def build_book(p, gold_fill, gold_close, mcx_last, lbes, liq, corr, end=None):
    nav = load_published_nav(p)
    t0 = nav.index[0]
    cal_full = nav.index[nav.index >= t0]              # D17 dates
    if end is not None:
        cal_full = cal_full[cal_full <= pd.Timestamp(end)]
    n_full = len(cal_full)
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
                raw_gold_sessions=raw_after_mcx, mcx_last=str(mcx_last.date()))


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
                init_fill=B["Ffl"].loc[first_d18].values, first_d18=first_d18)


def decisions_for_window(B, a, b, window, masters):
    """Decision dates: the window's T0, then the last session of each later ISO week. Evidence column layout."""
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
            pos = int(np.searchsorted(dates, np.datetime64(d), side="right") - 1)
            signs.append(sg[pos]); labels.append(pd.Timestamp(dates[pos]))
        latest = max(labels)
        buy = all(s == "BUY" for s in signs)
        trade = cal[ix + 1] if ix + 1 < len(cal) and j < len(dec_idx) - 1 else None
        rows.append(dict(book=B["p"], window=window, j=j, decision_date=str(d.date()), decision_idx=int(ix),
                         trade_date=None if trade is None else str(trade.date()),
                         sign_Nifty100=signs[0], sign_MC100=signs[1], sign_SC100=signs[2],
                         label_Nifty100=str(labels[0].date()), label_MC100=str(labels[1].date()), label_SC100=str(labels[2].date()),
                         latest_label=str(latest.date()), label_age_days=int((d - latest).days),
                         all_three_buy=bool(buy), state=int(buy)))
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------------------------
# the simulation
# ----------------------------------------------------------------------------------------
def simulate(V, states, bps, dec_idx, mix_f=None, e_fixed=None, closed_form=False, positions=False):
    """One realisation on view V (sessions 0..n-1).

    states : decision states s_0..s_(D-1); dec_idx : the decisions' session indices in V
    mix_f  : constant mix comparator (e = f, rebalance at every decision's next session and at every basket change)
    e_fixed: hold-the-parent (1) or sleeve only (0) at every decision"""
    n = V["n"]
    C, Cn, F = V["C"], V["Cn"], V["F"]
    gc, gf, L = V["gc"], V["gf"], V["L"]
    S = len(V["S"])
    b_idx = V["b_idx"]
    W = V["W"]
    basket_at = V["basket_at"]
    D = len(states)

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
    shares = sh0 * e if e > 0 else np.zeros(S)
    gu = (1 - e) / 2.0 / gc[0]
    cu = (1 - e) / 2.0 / L[0]

    sw = {}
    if mix_f is not None:
        for j in range(0, D - 1):
            sw[int(dec_idx[j]) + 1] = float(mix_f)
    elif e_fixed is not None:
        pass                                   # no switch; basket changes only
    else:
        for j in range(1, D - 1):
            if states[j] != states[j - 1]:
                sw[int(dec_idx[j]) + 1] = float(states[j])
    chg = [i for i in V["changes"] if i < n]
    events = sorted(set(k for k in sw if k < n) | set(chg))

    segs = [(0, shares.copy(), gu, cu)]
    trades = []
    for i in events:
        w = W[basket_at[basket_key(i)]]
        pf = F[i]
        if i in sw:
            e_new = sw[i]
            kind = "mix_rebalance" if mix_f is not None else ("switch_in" if e_new == 1.0 else "switch_out")
        else:
            e_new = e
            kind = "basket_change"
            if e <= 0.0:
                continue      # basket change while OUT: nothing traded
        held = shares != 0
        if np.isnan(pf[(w > 0) | held]).any():
            raise RuntimeError(f"missing fill price for a needed stock at {V['cal'][i]}")
        cur_stock = np.where(held, shares * np.where(np.isnan(pf), 0.0, pf), 0.0)
        cur_g = gu * gf[i]
        cur_c = cu * L[i]
        Vv = cur_stock.sum() + cur_g + cur_c
        tgt_stock = e_new * Vv * w
        tgt_g = (1 - e_new) / 2.0 * Vv
        tgt_c = (1 - e_new) / 2.0 * Vv
        traded = np.abs(tgt_stock - cur_stock).sum() + abs(tgt_g - cur_g) + abs(tgt_c - cur_c)
        cost = traded * bps / 2.0 / 10000.0
        f = (Vv - cost) / Vv
        shares = np.where(tgt_stock > 0, tgt_stock * f / np.where(np.isnan(pf), 1.0, pf), 0.0)
        gu = tgt_g * f / gf[i]
        cu = tgt_c * f / L[i]
        e = e_new
        segs.append((i, shares.copy(), gu, cu))
        trades.append(dict(idx=i, date=str(V["cal"][i].date()), kind=kind, e_after=e,
                           basket_eff=str(V["cal"][basket_key(i)].date()) if basket_key(i) >= 0 else None,
                           V=Vv, traded=traded, cost=cost))

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


# ----------------------------------------------------------------------------------------
# spells, nulls, counting
# ----------------------------------------------------------------------------------------
def runs_of(s):
    out = []
    start = 0
    for i in range(1, len(s) + 1):
        if i == len(s) or s[i] != s[start]:
            out.append((int(s[start]), i - start))
            start = i
    return out


def n49_states(s, draw_id):
    runs = runs_of(s)
    ins = [l for v, l in runs if v == 1]
    outs = [l for v, l in runs if v == 0]
    rng = np.random.default_rng([3, draw_id])
    pi = rng.permutation(len(ins))
    po = rng.permutation(len(outs))
    ins2 = [ins[k] for k in pi]
    outs2 = [outs[k] for k in po]
    cur = int(s[0])
    ii = oo = 0
    out = []
    for r in range(len(runs)):
        st = cur if r % 2 == 0 else 1 - cur
        if st == 1:
            out.extend([1] * ins2[ii]); ii += 1
        else:
            out.extend([0] * outs2[oo]); oo += 1
    return np.array(out, dtype=np.uint8)


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


# ----------------------------------------------------------------------------------------
# percentile and p-value
# ----------------------------------------------------------------------------------------
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


# ----------------------------------------------------------------------------------------
# comparison machinery
# ----------------------------------------------------------------------------------------
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


# ----------------------------------------------------------------------------------------
# derive everything that does not depend on the evidence
# ----------------------------------------------------------------------------------------
def derive(end=None, books=BOOKS, verbose=True):
    t = time.time()
    masters = load_masters()
    g, mcx = load_gold()
    gfill, gclose, mcx_last = despiked_goldbees_fill(g, mcx)
    lbes = load_lbes()
    liq = load_liquidcase()
    corr = load_corrections()
    D = {"books": {}, "dec": [], "nav": [], "stats": [], "trades": [], "positions": [], "always_in": [], "meta": {}, "rule": {}}
    for p in books:
        B = build_book(p, gfill, gclose, mcx_last, lbes, liq, corr, end=end)
        n = B["n_full"]
        cal = B["cal"]
        a_live = int(np.searchsorted(cal.values, np.datetime64(LIVE_START), side="left"))
        V = make_view(B, 0, n, "lbes")
        Vliq = make_view(B, 0, n, "liquidcase")
        Vlive = make_view(B, a_live, n, "lbes")
        dec = decisions_for_window(B, 0, n, "full", masters)
        dec_live = decisions_for_window(B, a_live, n, "live", masters)
        if verbose:
            print(f"[{time.time()-t:6.1f}s] {p}: built (sessions {n}, live from {cal[a_live].date()}, stocks {len(B['S'])}, baskets {len(B['basket_at_full'])})", flush=True)
        s = dec["state"].values.astype(int)
        s_live = dec_live["state"].values.astype(int)
        dec_idx = dec["decision_idx"].values
        dec_idx_live = dec_live["decision_idx"].values
        nd = len(s)
        f_mix = s.sum() / nd
        rule = {"full": rule_structure(s), "live": rule_structure(s_live)}
        for w, st_, di in (("full", s, dec_idx), ("live", s_live, dec_idx_live)):
            rule[w]["states"] = st_.astype(np.uint8)
            rule[w]["dec_idx"] = di
            rule[w]["sessions"] = n if w == "full" else n - a_live
            rule[w]["start"] = str((cal[0] if w == "full" else cal[a_live]).date())
            rule[w]["end"] = str(cal[-1].date())
            rule[w]["cover"] = week_cover(di)
        rule["hi_in"] = rule["full"]["longest_in"]
        rule["hi_out"] = rule["full"]["longest_out"]
        D["rule"][p] = rule
        D["meta"][p] = dict(sessions=n, decisions=nd, invested_weeks=int(s.sum()), t0=str(cal[0].date()), end=str(cal[-1].date()),
                            live_t0=str(cal[a_live].date()), live_sessions=n - a_live,
                            stale=int(((dec["label_age_days"] >= 5) & (dec["j"] > 0)).sum()),
                            initial_basket_switch_session=str(V["first_d18"].date()), dropped=B["dropped"],
                            in_spells=rule["full"]["in_spells"], out_spells=rule["full"]["out_spells"], f=f_mix,
                            raw_gold_sessions_after_mcx=B["raw_gold_sessions"], mcx_last=B["mcx_last"])
        D["dec"].extend([dec, dec_live])
        D["books"][p] = dict(B=B, V=V, Vliq=Vliq, Vlive=Vlive, dec_idx=dec_idx, dec_idx_live=dec_idx_live, s=s, s_live=s_live, f=f_mix, a_live=a_live)

        def add(window, cash, kind, bps, r, view):
            st = stats_of(r["nav"])
            st.update(book=p, window=window, cash=cash, cost_bps=bps, kind=kind, trades=len(r["trades"]),
                      cost_paid=float(sum(x["cost"] for x in r["trades"])), closed_rel=r["closed_rel"],
                      n_segments=r["n_segments"], end_from_segments=r["end_from_segments"],
                      invested_weeks=float(s.sum()) if kind == "strategy" else np.nan)
            D["stats"].append(st)

        for bps in COSTS:
            runs = {
                "strategy": simulate(V, s, bps, dec_idx, closed_form=True, positions=True),
                "hold_parent": simulate(V, np.ones(nd, dtype=int), bps, dec_idx, e_fixed=1.0),
                "sleeve_only": simulate(V, np.zeros(nd, dtype=int), bps, dec_idx, e_fixed=0.0),
                "constant_mix": simulate(V, s, bps, dec_idx, mix_f=f_mix),
            }
            if bps == 0.0:
                hold0 = runs["hold_parent"]
            for kind, r in runs.items():
                add("full", "lbes", kind, bps, r, V)
                D["nav"].append(pd.DataFrame(dict(book=p, date=[str(d.date()) for d in cal], cost_bps=bps, run=kind, nav=r["nav"])))
                for x in r["trades"]:
                    D["trades"].append(dict(book=p, cost_bps=bps, run=kind, **x))
                if kind == "strategy":
                    for dt, nm, u in r["positions"]:
                        D["positions"].append(dict(book=p, cost_bps=bps, run="strategy", date=dt, instrument=nm, units=u))
        # R2 (LIQUIDCASE cash) and R3 (live window), 20.8 bps, strategy
        add("full", "liquidcase", "strategy", HEADLINE_COST, simulate(Vliq, s, HEADLINE_COST, dec_idx), Vliq)
        add("live", "lbes", "strategy", HEADLINE_COST, simulate(Vlive, s_live, HEADLINE_COST, dec_idx_live), Vlive)
        # always-in against the published NAV, whole window, 0 cost (= hold_parent at 0 cost)
        nav_m = pd.Series(hold0["nav"], index=cal)
        rows_ai = always_in_rows(p, nav_m, B["pub"].loc[cal])
        D["always_in"].extend(rows_ai)
        if verbose:
            print(f"[{time.time()-t:6.1f}s] {p}: done (f={f_mix:.4f}, always-in CAGR gap {rows_ai[0]['gap_pp']:+.3f} pp)", flush=True)
    D["dec"] = pd.concat(D["dec"], ignore_index=True)
    D["nav"] = pd.concat(D["nav"], ignore_index=True)
    D["stats"] = pd.DataFrame(D["stats"])
    D["trades"] = pd.DataFrame(D["trades"])
    D["positions"] = pd.DataFrame(D["positions"])
    D["always_in"] = pd.DataFrame(D["always_in"])
    return D


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


# ----------------------------------------------------------------------------------------
# evidence loading (a missing file is None, never an exception)
# ----------------------------------------------------------------------------------------
EVIDENCE_FILES = ["inputs.csv", "decisions.csv", "stats.csv", "draws.csv", "draw_states.npz", "draw_curves_20.8.npz", "trades.csv",
                  "positions.csv", "daily_nav.csv", "g_engine.csv", "count_table.json", "audit.json"]


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
                        kw = {"dtype": {"in_lengths": str, "out_lengths": str}} if name == "draws.csv" else {}
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


# ----------------------------------------------------------------------------------------
# the checks
# ----------------------------------------------------------------------------------------
def guarded(C, name, gate=True):
    """Create a check and return (check, decorator) so that an unexpected exception becomes a failure, not a crash."""
    c = Check(name, gate=gate)
    C[name] = c
    return c


def run_check(C, name, fn, gate=True):
    c = Check(name, gate=gate)
    C[name] = c
    try:
        fn(c)
    except Exception as ex:
        c.failed += 1
        c.fail(f"verifier exception in {name}: {ex!r} | {traceback.format_exc(limit=3).strip().splitlines()[-1]}")
    return c


def sample_ids(book, typ, n_first=20, n_rand=20, pool=None, seed=20261106):
    pool = N_DRAWS if pool is None else pool
    rng = np.random.default_rng([seed, BOOKS.index(book), 0 if typ == "N4.9" else 1])
    rest = np.arange(n_first, pool)
    return list(range(n_first)) + sorted(rng.choice(rest, size=n_rand, replace=False).tolist())


def sample_ids_small(book, typ, window, pool=None, n=10, seed=20261107):
    pool = N_DRAWS if pool is None else pool
    rng = np.random.default_rng([seed, BOOKS.index(book), 0 if typ == "N4.9" else 1, 0 if window == "liquid" else 1])
    ids = set(rng.choice(np.arange(1, pool), size=n - 1, replace=False).tolist()); ids.add(0)
    return sorted(ids)


class SimCache:
    def __init__(self):
        self.d = {}

    def run(self, V, states, bps, dec_idx, tag):
        key = (tag, float(bps), np.asarray(states, dtype=np.uint8).tobytes())
        if key not in self.d:
            self.d[key] = simulate(V, np.asarray(states, dtype=int), bps, dec_idx)
        return self.d[key]


SIMS = SimCache()


def compare_all(D, E):
    C = {}

    # ------------------------------------------------------------------ C-data
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
                if ok and row["through"].lower() != "n/a" and row["id"] not in THROUGH_EXEMPT_IDS:
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
                if row["through"].lower() != "n/a" and row["id"] not in THROUGH_EXEMPT_IDS:
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
                    "latest_label", "decision_date", "all_three_buy"]
        compare_frames(c, mine, ev, ["book", "window", "j"], num_cols=["decision_idx", "label_age_days", "state"], str_cols=str_cols)
    run_check(C, "C-dec", c_dec)

    def c_pit(c):
        ev = E.get("decisions.csv", c)
        if ev is not None:
            for lc in ["label_Nifty100", "label_MC100", "label_SC100"]:
                ok = (ev[lc].astype(str) <= ev["decision_date"].astype(str)).values
                c.compared += len(ev); c.failed += int((~ok).sum())
                if (~ok).any(): c.fail("label after decision date: %s" % ev[~ok].iloc[0][["book", "j", "decision_date", lc]].to_dict())
            tdm = ev["trade_date"].notna()
            ok = (ev.loc[tdm, "trade_date"].astype(str) > ev.loc[tdm, "decision_date"].astype(str)).values
            c.compared += int(tdm.sum()); c.failed += int((~ok).sum())
            if (~ok).any(): c.fail("trade not after decision: %s" % ev.loc[tdm][~ok].iloc[0][["book", "j", "decision_date", "trade_date"]].to_dict())
            tr = E.get("trades.csv", c)
            if tr is not None:
                sw = tr[(tr["run"] == "strategy") & tr["kind"].isin(["switch_in", "switch_out"])]
                evf = ev[ev["window"] == "full"] if "window" in ev.columns else ev
                mm = sw.merge(evf[["book", "trade_date", "decision_date"]], left_on=["book", "date"], right_on=["book", "trade_date"], how="left")
                okk = mm["decision_date"].notna() & (mm["date"].astype(str) > mm["decision_date"].astype(str))
                c.compared += len(mm); c.failed += int((~okk).sum())
                if (~okk).any(): c.fail("switch trade without an earlier decision: %s" % mm[~okk].iloc[0][["book", "date"]].to_dict())
        md = dec_m
        for lc in ["label_Nifty100", "label_MC100", "label_SC100"]:
            ok = (md[lc] <= md["decision_date"]).values
            c.compared += len(md); c.failed += int((~ok).sum())
        mt = md["trade_date"].notna()
        ok = (md.loc[mt, "trade_date"] > md.loc[mt, "decision_date"]).values
        c.compared += int(mt.sum()); c.failed += int((~ok).sum())
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
        """Every statistic of every full-window LBES stats row (secondary statistics, trades, cost paid, invested weeks), all kinds, all costs."""
        if est_all is None:
            E.get("stats.csv", c); return
        keys = ["book", "cost_bps", "kind"]
        cols = NUMS_ALL + INTS + ["trades", "cost_paid"]
        compare_frames(c, stat_subset(mst, ["strategy", "hold_parent", "sleeve_only", "constant_mix"], COSTS)[keys + cols],
                       stat_subset(est(), ["strategy", "hold_parent", "sleeve_only", "constant_mix"], COSTS)[keys + cols], keys, num_cols=cols)
        s1 = stat_subset(mst, ["strategy"], COSTS)[keys + ["invested_weeks"]]
        e1 = stat_subset(est(), ["strategy"], COSTS)[keys + ["invested_weeks"]]
        compare_frames(c, s1, e1, keys, num_cols=["invested_weeks"], tol=0.0)
    run_check(C, "C-stats-all", c_stats_all)

    def published_rows():
        rows = []
        for p in BOOKS:
            pub = D["books"][p]["B"]["pub"]
            cal = D["books"][p]["B"]["cal"]
            pv = (pub.loc[cal] / pub.loc[cal].iloc[0]).values
            rows.append(pd.DataFrame(dict(book=p, date=[str(d.date()) for d in cal], cost_bps=-1.0, run="published", nav=pv)))
        return pd.concat(rows)

    def c_comp(c):
        if env_all is None or est_all is None:
            E.get("daily_nav.csv", c); E.get("stats.csv", c); return
        for kinds in (["hold_parent", "sleeve_only"], ["constant_mix"]):
            compare_frames(c, nav_subset(mnv, kinds, COSTS), nav_subset(env_all, kinds, COSTS), ["book", "date", "cost_bps", "run"], num_cols=["nav"])
        # published NAV rebased to 1.000 (hold-the-parent comparator), if the engine stores it as a run (T03 calls it published_D17, cost blank)
        pubruns = [r for r in env_all["run"].unique() if "publish" in str(r).lower()]
        if pubruns:
            ep = env_all[env_all["run"].isin(pubruns)].drop_duplicates(["book", "date"]).assign(run="published", cost_bps=-1.0)[["book", "date", "cost_bps", "run", "nav"]]
            compare_frames(c, published_rows(), ep, ["book", "date", "cost_bps", "run"], num_cols=["nav"])
        else:
            c.notes.append("no 'published' run in daily_nav.csv; the published-NAV comparator was not compared (always-in check covers it)")
    run_check(C, "C-comp", c_comp)

    # ------------------------------------------------------------------ trades and positions
    def c_trades(c):
        tr = E.get("trades.csv", c)
        if tr is None:
            return
        mt = D["trades"].copy(); mt["cost_bps"] = r4(mt["cost_bps"])
        et = tr.copy(); et["cost_bps"] = r4(et["cost_bps"])
        mt = mt[mt["run"] == "strategy"].copy(); et = et[et["run"] == "strategy"].copy()
        mt["seq"] = mt.groupby(["book", "cost_bps"]).cumcount(); et["seq"] = et.groupby(["book", "cost_bps"]).cumcount()
        et["date"] = et["date"].astype(str)
        num = ["idx", "e_after", "V", "traded", "cost"] + (["nav_close_after"] if "nav_close_after" in et.columns else [])
        compare_frames(c, mt, et, ["book", "cost_bps", "seq"], num_cols=num, str_cols=["date", "kind", "basket_eff"])
    run_check(C, "C-trades", c_trades)

    def c_trades_count(c):
        tr = E.get("trades.csv", c)
        if tr is None or est_all is None:
            E.get("stats.csv", c); return
        mt = D["trades"].copy(); mt["cost_bps"] = r4(mt["cost_bps"])
        et = tr.copy(); et["cost_bps"] = r4(et["cost_bps"])
        mt = mt[mt["run"] == "strategy"]; et = et[et["run"] == "strategy"]
        compare_frames(c, mt.groupby(["book", "cost_bps"]).size().rename("n").reset_index(),
                       et.groupby(["book", "cost_bps"]).size().rename("n").reset_index(), ["book", "cost_bps"], num_cols=["n"], tol=0.0)
        keys = ["book", "cost_bps", "kind"]
        compare_frames(c, stat_subset(mst, ["strategy"], COSTS)[keys + ["trades"]], stat_subset(est(), ["strategy"], COSTS)[keys + ["trades"]], keys, num_cols=["trades"], tol=0.0)
    run_check(C, "C-trades-count", c_trades_count)

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

    # ------------------------------------------------------------------ C-always-in
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
        for window, cash in (("full", "liquidcase"), ("live", "lbes")):
            m = mst[(mst["window"] == window) & (mst["cash"] == cash)][keys + cols]
            e = est_all[(est_all["window"] == window) & (est_all["cash"] == cash) & (est_all["kind"] == "strategy") & (est_all["cost_bps"] == HEADLINE_COST)][keys + cols]
            compare_frames(c, m, e, keys, num_cols=cols)
    run_check(C, "C-stats-liquidcase-live", c_r2r3)

    # ------------------------------------------------------------------ C-t03 (regression to T03 on the overlap)
    def c_t03(c):
        d3 = T03_EVIDENCE / "decisions.csv"
        n3 = T03_EVIDENCE / "daily_nav.csv"
        if not d3.exists() or not n3.exists():
            c.miss("tests/T03/evidence/headline/decisions.csv or daily_nav.csv"); return
        t3 = pd.read_csv(d3)
        t3["window"] = "full"
        last3 = t3.groupby("book")["j"].transform("max")
        t3_trade = t3["trade_date"].where(t3["j"] != last3)         # T03's last decision was not traded; T06's is
        mine = dec_m[dec_m["window"] == "full"].copy()
        a = t3.copy(); a["all_three_buy"] = a["all_three_buy"].astype(str); a["trade_date"] = t3_trade
        mm = mine.copy(); mm["all_three_buy"] = mm["all_three_buy"].astype(str)
        ma = a.merge(mm, on=["book", "decision_date"], how="left", suffixes=("_t3", "_v"))
        c.compared += len(ma)
        absent = ma["state_v"].isna()
        c.missing += int(absent.sum())
        if absent.any(): c.fail("T03 decision date absent from the verifier's decisions: %s" % ma[absent].iloc[0][["book", "decision_date"]].to_dict())
        ma = ma[~absent]
        bad = np.zeros(len(ma), dtype=bool)
        for col in ["state", "decision_idx", "label_age_days"]:
            bad |= (ma[col + "_t3"].astype(float).values != ma[col + "_v"].astype(float).values)
        for col in ["sign_Nifty100", "sign_MC100", "sign_SC100", "label_Nifty100", "label_MC100", "label_SC100", "latest_label", "all_three_buy"]:
            bad |= (ma[col + "_t3"].astype(str).values != ma[col + "_v"].astype(str).values)
        tt = ma["trade_date_t3"].notna()
        bad |= tt.values & (ma["trade_date_t3"].astype(str).values != ma["trade_date_v"].astype(str).values)
        c.failed += int(bad.sum())
        if bad.any(): c.fail("decision differs from T03: %s" % ma[bad].iloc[0][["book", "decision_date"]].to_dict())
        c.notes.append(f"{len(ma)} shared decision dates compared with T03 (state, signs, labels, session index, trade date)")
        # NAVs
        nv3 = pd.read_csv(n3)
        pub3 = nv3["run"].astype(str).str.contains("publish")
        nv3["cost_bps"] = r4(nv3["cost_bps"]); nv3["date"] = nv3["date"].astype(str)
        nv3.loc[pub3, "cost_bps"] = -1.0
        nv3.loc[pub3, "run"] = "published"
        nv3 = nv3[nv3["date"] <= str(T03_NAV_CUTOFF.date())]
        # constant mix: T03's own f (its window's invested weeks over decisions) so the two mixes are the same strategy
        f3 = {p: float(t3[t3.book == p]["state"].sum()) / float((t3.book == p).sum()) for p in BOOKS}
        mine_nav = nav_subset(mnv, ["strategy", "hold_parent", "sleeve_only"], COSTS)
        mix_rows = []
        for p in BOOKS:
            bk = D["books"][p]
            for bps in COSTS:
                r = simulate(bk["V"], bk["s"], bps, bk["dec_idx"], mix_f=f3[p])
                mix_rows.append(pd.DataFrame(dict(book=p, date=[str(d.date()) for d in bk["B"]["cal"]], cost_bps=r4(bps), run="constant_mix", nav=r["nav"])))
        mine_nav = pd.concat([mine_nav] + mix_rows + [published_rows()])
        mine_nav = mine_nav[mine_nav["date"] <= str(T03_NAV_CUTOFF.date())]
        compare_frames(c, mine_nav, nv3, ["book", "date", "cost_bps", "run"], num_cols=["nav"], tol=TOL_REGRESSION)
        # trades and positions on the overlap
        tr3 = pd.read_csv(T03_EVIDENCE / "trades.csv")
        tr3["cost_bps"] = r4(tr3["cost_bps"]); tr3["date"] = tr3["date"].astype(str)
        tr3 = tr3[(tr3["run"] == "strategy") & (tr3["date"] <= str(T03_NAV_CUTOFF.date()))].copy()
        mt = D["trades"].copy(); mt["cost_bps"] = r4(mt["cost_bps"])
        mt = mt[(mt["run"] == "strategy") & (mt["date"] <= str(T03_NAV_CUTOFF.date()))].copy()
        mt["seq"] = mt.groupby(["book", "cost_bps"]).cumcount(); tr3["seq"] = tr3.groupby(["book", "cost_bps"]).cumcount()
        compare_frames(c, mt, tr3, ["book", "cost_bps", "seq"], num_cols=["idx", "e_after", "V", "traded", "cost", "nav_close_after"], str_cols=["date", "kind", "basket_eff"], tol=1e-10)
        ps3 = pd.read_csv(T03_EVIDENCE / "positions.csv")
        ps3["cost_bps"] = r4(ps3["cost_bps"]); ps3["date"] = ps3["date"].astype(str)
        ps3 = ps3[(ps3["units"] != 0) & (ps3["date"] <= str(T03_NAV_CUTOFF.date()))]
        mp = D["positions"].copy(); mp["cost_bps"] = r4(mp["cost_bps"])
        mp = mp[(mp["units"] != 0) & (mp["date"] <= str(T03_NAV_CUTOFF.date()))]
        compare_frames(c, mp, ps3[["book", "cost_bps", "run", "date", "instrument", "units"]], ["book", "cost_bps", "run", "date", "instrument"], num_cols=["units"], tol=1e-10)
        c.notes.append(f"NAVs, trades and positions compared on dates <= {T03_NAV_CUTOFF.date()} (T03 accrued cash at a trailing rate after 2026-08-09; T06 reads the extended file)")
    run_check(C, "C-t03", c_t03)

    # ------------------------------------------------------------------ draws.csv / draw_states.npz
    draws = E.get("draws.csv")
    states_npz = E.get("draw_states.npz")
    curves_npz = E.get("draw_curves_20.8.npz")
    TYPES = ["N4.9", "N4.10"]
    WINDOWS = ["full", "live"]

    def states_of(book, window, typ):
        key = f"{book}|{window}|{typ}"
        if states_npz is None or key not in states_npz.files:
            return None
        return states_npz[key]

    def c_states_all(c_struct, c_len, c_csv, c_sess, c_regen, c_cover):
        if states_npz is None:
            for cc in (c_struct, c_len, c_csv, c_sess, c_regen, c_cover):
                E.get("draw_states.npz", cc)
            return
        drw = draws
        if drw is None:
            for cc in (c_csv, c_sess, c_cover):
                E.get("draws.csv", cc)
        for p in BOOKS:
            rule = D["rule"][p]
            for window in WINDOWS:
                R = rule[window]
                for typ in TYPES:
                    arr = states_of(p, window, typ)
                    if arr is None:
                        for cc in (c_struct, c_len):
                            cc.miss(f"draw_states.npz key {p}|{window}|{typ}")
                        continue
                    nd_, W_ = arr.shape
                    c_struct.compared += 1
                    if nd_ != N_DRAWS:
                        c_struct.failed += 1; c_struct.fail(f"{p}|{window}|{typ}: {nd_} draws, expected {N_DRAWS}")
                    c_struct.compared += 1
                    if W_ != R["weeks"] or arr.dtype != np.uint8 or not np.isin(arr, [0, 1]).all():
                        c_struct.failed += 1; c_struct.fail(f"{p}|{window}|{typ}: shape/dtype/values wrong: {arr.shape} {arr.dtype}")
                        continue
                    sp = spells_of_rows(arr)
                    inv = arr.sum(axis=1)
                    hi_in, hi_out = rule["hi_in"], rule["hi_out"]
                    in_str, out_str, sess = [], [], []
                    cover = R["cover"]
                    for i, (ins, outs, first) in enumerate(sp):
                        # structure (both types)
                        c_struct.compared += 4
                        bad = []
                        if first != R["first_state"]: bad.append("first state")
                        if len(ins) != R["in_spells"] or len(outs) != R["out_spells"]: bad.append("spell counts")
                        if int(inv[i]) != R["invested_weeks"]: bad.append("invested weeks")
                        if arr[i, -1] != R["last_state"]: bad.append("last state")
                        if bad:
                            c_struct.failed += len(bad); c_struct.fail(f"{p}|{window}|{typ} draw {i}: {', '.join(bad)} differ from the rule's")
                        # lengths
                        c_len.compared += 1
                        if typ == "N4.9":
                            ok = sorted(ins) == sorted(R["in_lengths"]) and sorted(outs) == sorted(R["out_lengths"])
                            why = "sorted spell lengths differ from the rule's"
                        else:
                            ok = (len(ins) > 0 and min(ins) >= LO and max(ins) <= hi_in and len(outs) > 0 and min(outs) >= LO and max(outs) <= hi_out
                                  and sum(ins) == R["S_in"] and sum(outs) == R["S_out"])
                            why = f"N4.10 bounds [{LO},{hi_in}]/[{LO},{hi_out}] or sums ({R['S_in']}, {R['S_out']}) violated"
                        if not ok:
                            c_len.failed += 1; c_len.fail(f"{p}|{window}|{typ} draw {i}: {why}: in {ins} out {outs}")
                        in_str.append("|".join(map(str, ins))); out_str.append("|".join(map(str, outs)))
                        sess.append(int((arr[i].astype(np.int64) * cover).sum()))
                    in_str = np.array(in_str, dtype=object); out_str = np.array(out_str, dtype=object); sess = np.array(sess)
                    # N4.9 regeneration from the seeds
                    if typ == "N4.9":
                        for i in range(nd_):
                            c_regen.compared += 1
                            if not np.array_equal(n49_states(R["states"], i), arr[i]):
                                c_regen.failed += 1; c_regen.fail(f"{p}|{window}|N4.9 draw {i}: states differ from numpy default_rng([3, {i}]) shuffle of the rule's spells")
                    # draws.csv rows for this book/window/type
                    if drw is not None:
                        d = drw[(drw["book"] == p) & (drw["window"] == window) & (drw["draw_type"] == typ)]
                        if len(d) == 0:
                            c_csv.miss(f"draws.csv has no rows for {p}|{window}|{typ}")
                            continue
                        ids = d["draw_id"].values.astype(int)
                        okid = (ids >= 0) & (ids < nd_)
                        c_csv.compared += len(d)
                        c_csv.failed += int((~okid).sum())
                        if (~okid).any(): c_csv.fail(f"{p}|{window}|{typ}: draw_id outside the saved states")
                        d = d[okid]; ids = ids[okid]
                        bad = np.zeros(len(d), dtype=bool)
                        first_msg = None
                        for col, vals in (("invested_weeks", inv), ("n_in_spells", np.array([len(s[0]) for s in sp])),
                                          ("n_out_spells", np.array([len(s[1]) for s in sp]))):
                            if col not in d.columns:
                                c_csv.miss(f"draws.csv column {col}"); continue
                            bc = d[col].astype(float).values != vals[ids].astype(float)
                            if bc.any() and first_msg is None:
                                i0 = int(np.argmax(bc)); first_msg = f"{p}|{window}|{typ} id {ids[i0]} col {col}: evidence {d[col].iloc[i0]!r} vs states {vals[ids][i0]!r}"
                            bad |= bc
                        for col, vals in (("in_lengths", in_str), ("out_lengths", out_str)):
                            if col not in d.columns:
                                c_csv.miss(f"draws.csv column {col}"); continue
                            bc = d[col].astype(str).str.strip().values != vals[ids]
                            if bc.any() and first_msg is None:
                                i0 = int(np.argmax(bc)); first_msg = f"{p}|{window}|{typ} id {ids[i0]} col {col}: evidence {d[col].iloc[i0]!r} vs states {vals[ids][i0]!r}"
                            bad |= bc
                        c_csv.compared += len(d) * 5 - len(d)
                        c_csv.failed += int(bad.sum())
                        if first_msg: c_csv.fail(first_msg)
                        # sessions_invested and sessions
                        if "sessions_invested" not in d.columns:
                            c_sess.miss("draws.csv column sessions_invested")
                        else:
                            bc = d["sessions_invested"].astype(float).values != sess[ids].astype(float)
                            c_sess.compared += len(d); c_sess.failed += int(bc.sum())
                            if bc.any():
                                i0 = int(np.argmax(bc)); c_sess.fail(f"{p}|{window}|{typ} id {ids[i0]}: sessions_invested evidence {d['sessions_invested'].iloc[i0]!r} vs verifier {sess[ids][i0]!r}")
                        if "sessions" in d.columns:
                            bc = d["sessions"].astype(float).values != float(R["sessions"])
                            c_sess.compared += len(d); c_sess.failed += int(bc.sum())
                            if bc.any(): c_sess.fail(f"{p}|{window}|{typ}: sessions column {d['sessions'].iloc[int(np.argmax(bc))]!r} vs window {R['sessions']}")
        # coverage of draws.csv: ids 0..1999 exactly once per group
        if drw is not None:
            exp_groups = []
            for p in BOOKS:
                for typ in TYPES:
                    for cst in COSTS:
                        exp_groups.append((p, "full", "lbes", cst, typ))
                    exp_groups.append((p, "full", "liquidcase", HEADLINE_COST, typ))
                    exp_groups.append((p, "live", "lbes", HEADLINE_COST, typ))
            dd = drw.copy(); dd["cost_bps"] = r4(dd["cost_bps"])
            gb = {k: v for k, v in dd.groupby(["book", "window", "cash", "cost_bps", "draw_type"])}
            for (p, w, ca, cst, typ) in exp_groups:
                c_cover.compared += 1
                g_ = gb.get((p, w, ca, round(cst, 4), typ))
                if g_ is None:
                    c_cover.miss(f"draws.csv group {p}|{w}|{ca}|{cst}|{typ}"); continue
                ids = g_["draw_id"].values
                if len(ids) != N_DRAWS or set(ids.tolist()) != set(range(N_DRAWS)):
                    c_cover.failed += 1; c_cover.fail(f"draws.csv group {p}|{w}|{ca}|{cst}|{typ}: {len(ids)} rows, ids not exactly 0..{N_DRAWS-1}")
            extra = set(gb) - {(p, w, ca, round(cst, 4), typ) for (p, w, ca, cst, typ) in exp_groups}
            c_cover.notes.append(f"{len(exp_groups)} expected (book, window, cash, cost, type) groups; unexpected groups present: {len(extra)}")

    cs = {n: Check(n) for n in ["C-states-struct", "C-states-lengths", "C-states-csv", "C-states-sessions", "C-n49-regen", "C-draws-coverage"]}
    C.update(cs)
    try:
        c_states_all(cs["C-states-struct"], cs["C-states-lengths"], cs["C-states-csv"], cs["C-states-sessions"], cs["C-n49-regen"], cs["C-draws-coverage"])
    except Exception as ex:
        cs["C-states-struct"].failed += 1
        cs["C-states-struct"].fail(f"verifier exception in C-states: {ex!r} | {traceback.format_exc(limit=3).strip().splitlines()[-1]}")

    # ------------------------------------------------------------------ C-draw-nav
    def c_draw_nav(c):
        if draws is None or states_npz is None:
            E.get("draws.csv", c); E.get("draw_states.npz", c); return
        dd = draws.copy(); dd["cost_bps"] = r4(dd["cost_bps"])
        idx = dd.set_index(["book", "window", "cash", "cost_bps", "draw_type", "draw_id"]).sort_index()
        cols = ["end_nav", "cagr", "max_dd", "vol", "ulcer", "days_below_10pct", "longest_underwater", "calmar", "sessions"]
        curve_chk = [0.0, 0]

        def compare_row(p, window, cash, bps, typ, i, r):
            key = (p, window, cash, round(bps, 4), typ, i)
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

        for p in BOOKS:
            bk = D["books"][p]
            for typ in TYPES:
                arr = states_of(p, "full", typ)
                if arr is None:
                    c.miss(f"states {p}|full|{typ}"); continue
                for i in [x for x in sample_ids(p, typ) if x < arr.shape[0]]:
                    for bps in COSTS:
                        r = SIMS.run(bk["V"], arr[i], bps, bk["dec_idx"], (p, "full", "lbes"))
                        compare_row(p, "full", "lbes", bps, typ, i, r)
                        if abs(bps - HEADLINE_COST) < 1e-9 and curves_npz is not None:
                            key = f"{p}|{typ}_{i}"
                            c.compared += 1
                            if key not in curves_npz.files:
                                c.missing += 1; c.fail(f"MISSING: curve {key} in draw_curves_20.8.npz")
                            else:
                                cv = curves_npz[key].astype(float)
                                if cv.shape != r["nav"].shape:
                                    c.failed += 1; c.fail(f"curve {key}: shape {cv.shape} vs {r['nav'].shape}")
                                else:
                                    rr = float(np.max(np.abs(cv - r["nav"]) / np.abs(r["nav"])))
                                    curve_chk[0] = max(curve_chk[0], rr); curve_chk[1] += 1
                                    if rr > TOL_CURVE:
                                        c.failed += 1; c.fail(f"curve {key}: max relative difference {rr:.2e} > {TOL_CURVE}")
                        elif abs(bps - HEADLINE_COST) < 1e-9 and curves_npz is None:
                            E.get("draw_curves_20.8.npz", c)
                # LIQUIDCASE (full states) and live window: 10 draws per book and type, 20.8 bps
                for i in [x for x in sample_ids_small(p, typ, "liquid") if x < arr.shape[0]]:
                    r = SIMS.run(bk["Vliq"], arr[i], HEADLINE_COST, bk["dec_idx"], (p, "full", "liquidcase"))
                    compare_row(p, "full", "liquidcase", HEADLINE_COST, typ, i, r)
                arr_l = states_of(p, "live", typ)
                if arr_l is None:
                    c.miss(f"states {p}|live|{typ}"); continue
                for i in [x for x in sample_ids_small(p, typ, "live") if x < arr_l.shape[0]]:
                    r = SIMS.run(bk["Vlive"], arr_l[i], HEADLINE_COST, bk["dec_idx_live"], (p, "live", "lbes"))
                    compare_row(p, "live", "lbes", HEADLINE_COST, typ, i, r)
        c.notes.append(f"{curve_chk[1]} draw curves compared at 20.8 bps; worst relative difference {curve_chk[0]:.2e} (float32 tolerance {TOL_CURVE})")
    run_check(C, "C-draw-nav", c_draw_nav)

    # ------------------------------------------------------------------ C-count, C-support, C-sampler
    def expected_count_rows():
        rows = []
        for p in BOOKS:
            rule = D["rule"][p]
            for window in WINDOWS:
                R = rule[window]
                rows.append(dict(book=p, window=window, state="in", k=R["in_spells"], S=R["S_in"], lo=LO, hi=rule["hi_in"]))
                rows.append(dict(book=p, window=window, state="out", k=R["out_spells"], S=R["S_out"], lo=LO, hi=rule["hi_out"]))
        for r in rows:
            r["n_ways"] = n_ways(r["k"], r["S"], r["lo"], r["hi"])
        return rows
    D["count_rows"] = expected_count_rows()

    def walk_count(obj, ctx, out):
        if isinstance(obj, dict):
            if "n_ways" in obj:
                leaf = dict(ctx); leaf.update(obj); out.append(leaf); return
            for k, v in obj.items():
                c2 = dict(ctx)
                ks = str(k)
                if ks in BOOKS: c2["book"] = ks
                elif ks in ("full", "live"): c2["window"] = ks
                elif ks in ("in", "out"): c2["state"] = ks
                walk_count(v, c2, out)
        elif isinstance(obj, list):
            for v in obj:
                walk_count(v, ctx, out)

    def c_count(c):
        ct = E.get("count_table.json", c)
        mine = D["count_rows"]
        if ct is not None:
            leaves = []
            walk_count(ct, {}, leaves)
            for r in mine:
                m = [l for l in leaves if l.get("book") == r["book"] and l.get("window") == r["window"] and l.get("state") == r["state"]]
                c.compared += 1
                if not m:
                    c.miss(f"count_table.json entry {r['book']}|{r['window']}|{r['state']}"); continue
                l = m[0]
                try:
                    kk = l["k"] if "k" in l else l["spells_k"]          # the engine may name them spells_k / weeks_S
                    SS = l["S"] if "S" in l else l["weeks_S"]
                    ok = (int(str(l["n_ways"])) == r["n_ways"] and int(kk) == r["k"] and int(SS) == r["S"]
                          and int(l["lo"]) == r["lo"] and int(l["hi"]) == r["hi"])
                except Exception:
                    ok = False
                if not ok:
                    c.failed += 1; c.fail(f"{r['book']}|{r['window']}|{r['state']}: count table {l} vs verifier k={r['k']} S={r['S']} lo={r['lo']} hi={r['hi']} n_ways={r['n_ways']}")
        # the pre-registered counts of Step 1 (T06.md section 2 / logs/step_1_spell_counts.json), if present
        if STEP1_JSON.exists():
            s1 = json.load(open(STEP1_JSON))
            for f in s1["feasibility"]:
                m = [r for r in mine if r["book"] == f["book"] and r["window"] == f["window"] and r["state"] == f["state"]]
                c.compared += 1
                if not m or str(m[0]["n_ways"]) != str(f["n_ways"]) or m[0]["k"] != f["k"] or m[0]["S"] != f["S"]:
                    c.failed += 1; c.fail(f"step_1_spell_counts.json {f} differs from the verifier's inclusion-exclusion count {m[:1]}")
        else:
            c.notes.append("logs/step_1_spell_counts.json not found; pre-registered counts not compared")
        # a plain DP as a second, independent confirmation of the formula on the small worked example of T06.md (k=3, S=12, [2,6] -> 19)
        c.compared += 1
        if n_ways(3, 12, 2, 6) != 19:
            c.failed += 1; c.fail(f"inclusion-exclusion gives {n_ways(3, 12, 2, 6)} for k=3,S=12,[2,6]; T06.md says 19")
    run_check(C, "C-count", c_count)

    def c_spells_step1(c):
        """The rule's spell structure (derived here from the raw files) equals the pre-registered Step 1 counts (T06.md section 2)."""
        if not STEP1_JSON.exists():
            c.notes.append("logs/step_1_spell_counts.json not found"); return
        s1 = json.load(open(STEP1_JSON))["books"]
        for p in BOOKS:
            for window in WINDOWS:
                R = D["rule"][p][window]
                e = s1[p][window]
                for k_ in ("weeks", "first_state", "last_state", "in_spells", "out_spells", "S_in", "S_out", "in_lengths", "out_lengths", "longest_in", "longest_out"):
                    c.compared += 1
                    if R[k_] != e[k_]:
                        c.failed += 1; c.fail(f"{p}|{window} {k_}: verifier {R[k_]!r} vs step_1_spell_counts.json {e[k_]!r}")
                for k_, mk in (("start", "start"), ("end", "end")):
                    c.compared += 1
                    if R[mk] != e[k_]:
                        c.failed += 1; c.fail(f"{p}|{window} {k_}: verifier {R[mk]!r} vs step_1_spell_counts.json {e[k_]!r}")
    run_check(C, "C-spells-step1", c_spells_step1)

    def c_support(c):
        for p in BOOKS:
            rule = D["rule"][p]
            for window in WINDOWS:
                R = rule[window]
                for nm, lens, hi in (("in", R["in_lengths"], rule["hi_in"]), ("out", R["out_lengths"], rule["hi_out"])):
                    c.compared += 1
                    ok = all(LO <= l <= hi for l in lens) and 2 * len(lens) <= sum(lens) <= hi * len(lens)
                    if not ok:
                        c.failed += 1; c.fail(f"{p}|{window}|{nm}: the rule's own lengths {lens} are outside [{LO}, {hi}] or the totals cannot be split within the bounds")
                    # reportability: at least 4 round trips (one exit plus one entry)
                    if nm == "in":
                        c.compared += 1
                        if min(R["in_spells"], R["out_spells"]) < 4:
                            c.failed += 1; c.fail(f"{p}|{window}: fewer than 4 round trips")
        # the draws' bounds themselves are checked per draw in C-states-lengths
    run_check(C, "C-support", c_support)

    def c_sampler(c):
        """Position means: over the saved N4.10 states the first and last in- and out-spell lengths have the exact mean of a uniform ordered tuple (within 5 standard errors)."""
        if states_npz is None:
            E.get("draw_states.npz", c); return
        for p in BOOKS:
            rule = D["rule"][p]
            for window in WINDOWS:
                R = rule[window]
                arr = states_of(p, window, "N4.10")
                if arr is None:
                    c.miss(f"states {p}|{window}|N4.10"); continue
                sp = spells_of_rows(arr)
                for nm, k, S, hi, idx_first, idx_last in (("in", R["in_spells"], R["S_in"], rule["hi_in"], 0, -1), ("out", R["out_spells"], R["S_out"], rule["hi_out"], 0, -1)):
                    mu, var = first_part_moments(k, S, LO, hi)
                    lens = np.array([(s[0] if nm == "in" else s[1]) for s in sp])
                    if lens.shape[1] != k:
                        c.failed += 1; c.fail(f"{p}|{window}|{nm}: draws do not all have {k} spells"); continue
                    for pos in (0, k - 1):
                        c.compared += 1
                        se = math.sqrt(var / len(lens))
                        z = abs(lens[:, pos].mean() - mu) / se
                        c.worst_rel = max(c.worst_rel, z)
                        if z > 5.0:
                            c.failed += 1; c.fail(f"{p}|{window}|{nm} part {pos}: sample mean {lens[:, pos].mean():.3f} vs exact {mu:.3f}, z = {z:.1f}")
        c.notes.append("worst_rel in this check is the largest |z| (standard errors)")
    run_check(C, "C-sampler", c_sampler)

    # ------------------------------------------------------------------ C-percentile
    D["percentiles"] = []

    def c_percentile(c):
        if draws is None:
            E.get("draws.csv", c); return
        dd = draws.copy(); dd["cost_bps"] = r4(dd["cost_bps"])
        groups = {k: v for k, v in dd.groupby(["book", "window", "cash", "cost_bps", "draw_type"])}
        rows = []
        for (p, w, ca, cst, typ), g_ in groups.items():
            m = mst[(mst["book"] == p) & (mst["window"] == w) & (mst["cash"] == ca) & (mst["cost_bps"] == cst) & (mst["kind"] == "strategy")]
            if not len(m):
                continue
            row = dict(book=p, window=w, cash=ca, cost_bps=float(cst), draw_type=typ, n_draws=len(g_))
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
                    c.failed += 1; c.fail(f"{p} {w} {ca} {cst} {typ} {stat}: vectorised percentile {pc!r}/{pv!r} vs loop {pc2!r}/{pv2!r}")
                row[f"{stat}_pctile"] = pc; row[f"{stat}_p"] = pv
            rows.append(row)
        D["percentiles"] = rows
        c.notes.append("worst_rel in this check is the largest difference between the two own implementations")
        # compare with the stats the analysis wrote, if it wrote percentiles into stats.csv
        if est_all is not None:
            pc_cols = [x for x in est_all.columns if "pctile" in x.lower() or "percentile" in x.lower()]
            if pc_cols:
                c.notes.append(f"stats.csv carries percentile columns {pc_cols}; compared below")
                for pcol in pc_cols:
                    stat = pcol.lower().replace("_pctile", "").replace("_percentile", "").replace("pctile_", "")
                    for r in rows:
                        e = est_all[(est_all["book"] == r["book"]) & (est_all["window"] == r["window"]) & (est_all["cash"] == r["cash"]) & (est_all["cost_bps"] == round(r["cost_bps"], 4))]
                        if len(e) and f"{stat}_pctile" in r and pcol in e.columns and e[pcol].notna().any():
                            c.compared += 1
                            if abs(float(e[pcol].dropna().iloc[0]) - r[f"{stat}_pctile"]) > 1e-9:
                                c.failed += 1; c.fail(f"stats.csv {pcol} differs for {r['book']} {r['window']} {r['cost_bps']}")
    run_check(C, "C-percentile", c_percentile)

    def c_percentile_log(c):
        """Informational: does analysis.log (if it exists) print each headline percentile (20.8 bps, LBES, full window)?"""
        cand = [E.dir / "analysis.log", E.dir.parent / "analysis.log", E.dir.parent.parent / "analysis.log"]
        logp = next((x for x in cand if x.exists()), None)
        if logp is None:
            c.notes.append("analysis.log not found beside the evidence (not required by the spec); nothing compared")
            return
        txt = logp.read_text(encoding="utf-8", errors="replace")
        nums = set(re.findall(r"\d+\.\d+", txt))
        for r in D["percentiles"]:
            if r["window"] == "full" and r["cash"] == "lbes" and abs(r["cost_bps"] - HEADLINE_COST) < 1e-9:
                for stat in ("cagr", "max_dd"):
                    v = r.get(f"{stat}_pctile")
                    if v is None:
                        continue
                    c.compared += 1
                    found = any(f"{v:.{nd}f}" in nums for nd in (1, 2))
                    if not found:
                        c.failed += 1; c.fail(f"{r['book']} {r['draw_type']} {stat} percentile {v:.2f} not printed in {logp.name}")
        c.notes.append(f"read {logp}")
    run_check(C, "C-percentile-log", c_percentile_log, gate=False)

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
def corrupt_copy(ev, dst, D):
    """Flip 5 decisions, scale a NAV column by 1.001, move one N4.10 draw's spell lengths out of bounds (states and draws.csv)."""
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
    if spath is not None:
        z = np.load(spath)
        data = {k: z[k] for k in z.files}
        key = "SCMO_0003|full|N4.10"
        if key in data:
            arr = data[key]
            row = arr[5].copy()
            sp = spells_of_rows(arr[5:6])[0]
            ins, outs = sp[0], sp[1]
            # lengthen the first in-spell to HI+1 by taking weeks from the following out-spell's neighbours: swap spell lengths
            # (state sequence out,in,out,in,...): make in-spell 0 = 47 (> 46) and in-spell 1 shorter by the same amount
            hi_in = D["rule"]["SCMO_0003"]["hi_in"]
            new_ins = list(ins)
            remaining = (hi_in + 1) - new_ins[0]
            new_ins[0] = hi_in + 1
            for jj in range(1, len(new_ins)):          # take the extra weeks from the following in-spells (the totals stay equal)
                take = min(remaining, new_ins[jj] - 1)
                new_ins[jj] -= take; remaining -= take
                if remaining == 0:
                    break
            seq, ii, oo = [], 0, 0
            for r in range(len(ins) + len(outs)):
                if r % 2 == 0:
                    seq.extend([0] * outs[oo]); oo += 1
                else:
                    seq.extend([1] * new_ins[ii]); ii += 1
            if len(seq) == arr.shape[1]:
                arr[5] = np.array(seq, dtype=np.uint8)
                data[key] = arr
                info["corrupted_n410_draw"] = dict(key=key, draw_id=5, in_lengths=new_ins, out_lengths=outs)
                if wpath is not None:
                    w = pd.read_csv(wpath, dtype={"in_lengths": str, "out_lengths": str})
                    msk = (w["book"] == "SCMO_0003") & (w["window"] == "full") & (w["draw_type"] == "N4.10") & (w["draw_id"] == 5)
                    w.loc[msk, "in_lengths"] = "|".join(map(str, new_ins))
                    w.loc[msk, "invested_weeks"] = int(arr[5].sum())
                    w.to_csv(dst / "draws.csv", index=False)
        np.savez(dst / "draw_states.npz", **data)
    return info


# ----------------------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--evidence", default=str(AA / "tests" / "T06" / "evidence" / "headline"))
    ap.add_argument("--no-selftest", action="store_true", help="skip the in-process corrupted-copy test")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    evdir = Path(args.evidence)
    out = Path(args.out) if args.out else evdir / "verify_t06.json"
    t = time.time()
    D = derive()
    print(f"[{time.time()-t:6.1f}s] derivation complete", flush=True)
    E = Evidence(evdir)
    C = compare_all(D, E)
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
        print("\n=== recomputed percentiles (20.8 bps, LBES, full window; pass mark 90) ===")
        for r in D["percentiles"]:
            if r["window"] == "full" and r["cash"] == "lbes" and abs(r["cost_bps"] - HEADLINE_COST) < 1e-9:
                print(f"{r['book']} {r['draw_type']:6s} C1 CAGR pctile {r['cagr_pctile']:7.2f} (p {r['cagr_p']:.4f})   C2 max-DD pctile {r['max_dd_pctile']:7.2f} (p {r['max_dd_p']:.4f})")

    pct_real, count_real = D["percentiles"], D["count_rows"]
    selftest = None
    if not args.no_selftest:
        cdir = SCRATCH / "corrupt_evidence_t06"
        info = corrupt_copy(E, cdir, D)
        Ec = Evidence(cdir, fallback=evdir)
        Cc = compare_all(D, Ec)
        print_table(Cc, f"SELF-TEST: corrupted copy in {cdir} ({info})")
        cc, cf = summarise(Cc)
        by = {k: (v.failed + v.missing) for k, v in Cc.items()}
        det_dec = by.get("C-dec", 0) > 0
        det_nav = by.get("C-nav0", 0) > 0
        det_len = by.get("C-states-lengths", 0) > 0
        have_dec = "flipped_decision_rows" in info
        have_nav = "scaled_nav" in info
        have_len = "corrupted_n410_draw" in info
        detected = cf > 0 and (det_dec or not have_dec) and (det_nav or not have_nav) and (det_len or not have_len) and (have_dec or have_nav or have_len)
        selftest = dict(dir=str(cdir), corruptions=info, gate_compared=cc, gate_failures=cf, detected=bool(detected),
                        detected_by=dict(decisions_flipped=det_dec, nav_scaled=det_nav, n410_lengths_out_of_bounds=det_len),
                        checks={k: v.to_dict() for k, v in Cc.items()})
        print(f"corrupted copy detected: {detected} (failures {cf}; decisions {det_dec}, NAV {det_nav}, N4.10 bounds {det_len})")

    D["percentiles"], D["count_rows"] = pct_real, count_real
    ok_real = gate_compared > 0 and gate_fail == 0 and not extra_missing
    ok = ok_real and (selftest is None or selftest["detected"])
    rep = dict(verifier="analysis/verify_t06.py", evidence=str(evdir), gate_compared=int(gate_compared), gate_failures_and_missing=int(gate_fail),
               missing_evidence_files=extra_missing,
               checks={k: v.to_dict() for k, v in C.items()}, always_in=ai.to_dict(orient="records"),
               meta={p: D["meta"][p] for p in BOOKS}, rule={p: {w: {k: v for k, v in D["rule"][p][w].items() if k not in ("states", "dec_idx", "cover")}
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
