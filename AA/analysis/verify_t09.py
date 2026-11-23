"""T09 independent verifier (Step 3).

Re-derives T09's decisions (three index signals and the MAUc1 gold signal), the three-index proxy portfolio's NAVs with its quarterly
resets, costs, trades, sleeve trades, positions and null-draw results from the RAW files only (plain numpy / pandas, its own loaders, its
own cost, trade, counting and percentile code) and compares them with the engine's evidence in tests/T09/evidence/<run>/.

It imports nothing from the engine or from any other module in analysis/ or data/ (numpy, pandas, scipy for one chi-square p-value, and the
standard library). It never reads the engine's source and parses data/APPROVED_DATA.md itself. The rules are those of tests/T09/T09.md
sections 1-3 (frozen) and its amendment block, tests/T09/PLAN.md / PLAN_v2.md and tests/T09/logs/evidence_contract.md; the conventions are
T06's and T08's (tests/T08/logs/verifier_spec.md) except where the T09 spec (tests/T09/logs/verifier_spec.md) differs. Forked from
verify_t08.py (read as a model, not imported).

Usage (from AA/):
    python analysis/verify_t09.py                                  # headline evidence (tests/T09/evidence/headline) + self-test on corrupted copies
    python analysis/verify_t09.py --run smoke                      # tests/T09/evidence/smoke (20 draws; books found in the evidence)
    python analysis/verify_t09.py --evidence DIR --draws 30        # any evidence directory, 30 draws per group
    python analysis/verify_t09.py --no-selftest --out FILE

Exit code 0 only if rows were compared, none failed, none were missing, and (in the default run) every deliberate corruption of a copy of
the evidence was detected by its own check. A missing evidence file is reported as MISSING (a failure).
"""
import argparse
import hashlib
import io
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
# typed in T09.md section 3 ("Band mixes"); weights on (Nifty 100, Midcap 100, Smallcap 100)
WEIGHTS = {"SCMO_0003": (0.09626177, 0.19679459, 0.70694364), "SCMO_0007": (0.04799800, 0.17801859, 0.77398341),
           "SCMO_0010": (0.26590767, 0.21230665, 0.52178568), "SCMO_0029": (0.31294405, 0.28378774, 0.40326821)}
INDICES = ["Nifty100", "MC100", "SC100"]
INSTR = INDICES + ["GOLDBEES", "LBES"]
COSTS = [0.0, 20.8, 50.0]
HEADLINE_COST = 20.8
TOL = 1e-9                  # relative tolerance on NAVs and statistics
TOL_ID = 1e-12              # identities
TOL_CURVE = 1e-5            # float32 draw curves
N_DRAWS = 2000              # draws per row group (--draws overrides, for short runs)
T0_FULL = pd.Timestamp("2011-11-25")
END = pd.Timestamp("2019-01-02")
R3_START = pd.Timestamp("2012-01-02")
GOLDBEES_START = pd.Timestamp("2014-07-01")
PROXY_LAST = pd.Timestamp("2014-06-30")
SC100_PRICE_FROM = pd.Timestamp("2011-10-03")
SC100_SIGNAL_FROM = pd.Timestamp("2011-11-25")
MCX_NO_BAR_EXPECTED = ["2014-10-23", "2015-01-01", "2015-11-11"]
NO_GOLD_BAR_EXPECTED = ["2016-10-30"]
GW_BUY, GW_SELL, GW_FIX = 0.8, 0.2, 0.5
SEEDS = dict(n49=[12, 3], n410=[12, 6], n49g=[12, 11, 3], n410g=[12, 11, 6])     # seed = list + [draw_id]
STEP1_JSON = AA / "tests" / "T09" / "logs" / "step_1_spell_counts.json"
APPROVED_MD = AA / "data" / "APPROVED_DATA.md"
# null families (T09.md section 2): io null, gold null
FAMILY = {"F1": ("N4.10", "real"), "F2": ("N4.9", "real"), "F3": ("real", "N4.10-g"), "F4": ("real", "N4.9-g"), "F5": ("N4.10", "N4.10-g")}
STAT_COLS_ALL = ["end_nav", "cagr", "max_dd", "vol", "ulcer", "days_below_10pct", "longest_underwater", "calmar", "sessions"]
RUN_KINDS = ["strategy", "strategy_fixed50", "hold_proxy", "constant_mix", "constant_mix_timed", "sleeve_only", "sleeve_only_timed",
             "index_Nifty100", "index_MC100", "index_SC100"]
R7A = "strategy_r7a_proxy_fill_at_close"
R7B = "strategy_r7b_gold_weight_50_before_2014-07-01"
R7_KINDS = [R7A, R7B]
ALL_KINDS = RUN_KINDS + R7_KINDS

F_CAL = "Historical Data/extended_2026-11-12/index_daily_pre2019/nse_trading_days.csv"
F_IDX = {n: f"Historical Data/extended_2026-11-12/index_daily_pre2019/{n}_daily_ohlcv.csv" for n in INDICES}
F_MASTER = {n: f"Historical Data/extended_2026-10-30/Master/Master_{n}.xlsx" for n in INDICES}
F_GMASTER = "Historical Data/extended_2026-11-12/MAUc1_from_2003/Master_MAUc1.xlsx"
F_GWEEKLY = "Historical Data/extended_2026-11-12/MAUc1_from_2003/mauc1_supertrend_weekly_extended.csv"
F_GDAILY = "Historical Data/extended_2026-11-12/MAUc1_from_2003/mauc1_daily_clean_extended.csv"
F_D09B = "analysis/cache/why_gold_ohlc_proxy_mauc1_2005-05-10_2014-06-30.parquet"
F_D09 = "analysis/cache/why_gold_ohlc_eikon_extended_2026-11-04.parquet"
F_LBES = "Historical Data/LBES_Adjusted_Price_data_extended_2026-11-05.csv"
F_LIQ = "Historical Data/liquidEtfFinal_extended_2026-11-05.csv"


def norm_path(s):
    s = str(s).strip().replace("\\", "/")
    return s[2:] if s.startswith("./") else s


def parse_approved(md_path=APPROVED_MD):
    """The APPROVED_DATA.md table (between the approved-table markers): status, id, file, through, sha256 prefix, note, usable-from marker."""
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
        note = "|".join(parts[5:])
        m = re.search(r"\[usable-from:\s*(\d{4}-\d{2}-\d{2})\]", note)
        rows[norm_path(parts[2])] = dict(status=parts[0], id=parts[1], file=parts[2], through=parts[3], sha=parts[4].lower(), note=note,
                                         usable_from=m.group(1) if m else None)
    return rows


APPROVED = parse_approved()
READS = {}          # relative path -> dict(first_date=..., sha=...) of every file this verifier read
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


def rd(rel, first_date=None):
    """Register a read of an AA-relative path; refuse anything that is not an APPROVED row. A restricted row (`[usable-from: d]` in its
    registry note: standing rule 7, the Smallcap 100 files) needs the first date the read will use, and raises if that date is earlier."""
    key = norm_path(rel)
    row = APPROVED.get(key)
    if row is None:
        raise RuntimeError(f"file not in APPROVED_DATA.md: {rel}")
    if row["status"] != "APPROVED":
        raise RuntimeError(f"file is {row['status']} in APPROVED_DATA.md: {rel}")
    uf = row["usable_from"]
    if uf is not None:
        if first_date is None:
            raise RuntimeError(f"{rel} is restricted (usable from {uf}); a first read date is required")
        if pd.Timestamp(first_date) < pd.Timestamp(uf):
            raise RuntimeError(f"refusing to read {rel} from {pd.Timestamp(first_date).date()}: usable from {uf} (standing rule 7)")
    READS[key] = dict(first_date=None if first_date is None else str(pd.Timestamp(first_date).date()), sha=None)
    return AA / rel


# ----------------------------------------------------------------------------------------
# raw loaders
# ----------------------------------------------------------------------------------------
def load_calendar():
    d = pd.read_csv(rd(F_CAL))
    dates = pd.DatetimeIndex(pd.to_datetime(d["date"])).sort_values()
    assert dates.is_unique
    return dates[(dates >= T0_FULL) & (dates <= END)]


def load_index_csv(name, first_date):
    """date, open, high, low, close, volume. The file is read as TEXT and only the lines dated on or after first_date are parsed (the Smallcap 100
    rows before 2011-10-03 are corrupt and restricted; nothing earlier than first_date is ever held in memory as data)."""
    p = rd(F_IDX[name], first_date)
    lines = p.read_text(encoding="utf-8").splitlines()
    cut = pd.Timestamp(first_date).strftime("%Y-%m-%d")
    keep = [lines[0]] + [ln for ln in lines[1:] if ln[:10] >= cut]
    d = pd.read_csv(io.StringIO("\n".join(keep)))
    d["date"] = pd.to_datetime(d["date"]).dt.normalize()
    d = d.set_index("date").sort_index()
    assert d.index.is_unique, name
    return d[["open", "high", "low", "close"]].astype(float)


def _read_master(rel, first_date=None):
    """Weekly Master file -> (dates, SIGN) arrays, sorted. Rows dated before first_date (a restriction) are dropped at load and never used."""
    m = pd.read_excel(rd(rel, first_date))
    m = m[["Date", "SIGN"]].copy()
    m["SIGN"] = m["SIGN"].astype("object")
    m = m[m["SIGN"].notna()]
    m["SIGN"] = m["SIGN"].astype(str).str.strip().str.upper()
    m = m[m["SIGN"] != ""]
    m["Date"] = pd.to_datetime(m["Date"])
    if first_date is not None:
        m = m[m["Date"] >= pd.Timestamp(first_date)]
    m = m.sort_values("Date").reset_index(drop=True)
    assert set(m["SIGN"]) <= {"BUY", "SELL"}, (rel, set(m["SIGN"]))
    return m["Date"].values, m["SIGN"].values


def load_masters():
    out = {}
    for nm in INDICES:
        out[nm] = _read_master(F_MASTER[nm], SC100_SIGNAL_FROM if nm == "SC100" else None)
    return out


def load_mauc1_master():
    return _read_master(F_GMASTER)


def load_mauc1_weekly():
    w = pd.read_csv(rd(F_GWEEKLY))
    w["review"] = pd.to_datetime(w["review"])
    w["SIGN"] = w["SIGN"].astype(str).str.strip().str.upper()
    return w.sort_values("review").reset_index(drop=True)


def load_gold_files():
    b = pd.read_parquet(rd(F_D09B))
    g = pd.read_parquet(rd(F_D09))
    m = pd.read_csv(rd(F_GDAILY))
    for d in (b, g):
        d["date"] = pd.to_datetime(d["date"]).dt.normalize()
    b = b[["date", "open", "high", "low", "close"]].set_index("date").sort_index()
    g = g[["date", "open", "high", "low", "close"]].set_index("date").sort_index()
    m = m.rename(columns={m.columns[0]: "date"})
    m["date"] = pd.to_datetime(m["date"]).dt.normalize()
    m = m.set_index("date").sort_index()
    return b, g, m


def despiked_goldbees_fill(g, m):
    """GOLDBEES fill from 2014-07-01 (T03's de-spike, as T06/T08): OHLC4 of the open, high and low clipped to MCX gold's range that day
    (band = (high - low) / close of the MCX bar + 0.5%, around the GOLDBEES close); the RAW OHLC4 on a session the MCX file has no bar for."""
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
    return fill, ~have


def load_lbes():
    d = pd.read_csv(rd(F_LBES))
    d["date"] = pd.to_datetime(d["date"], format="%d/%m/%y %H:%M").dt.normalize()
    return d.set_index("date")["price"].sort_index()


def load_liquidcase():
    d = pd.read_csv(rd(F_LIQ))
    d["date"] = pd.to_datetime(d["date"], format="%d-%m-%Y").dt.normalize()
    return d.set_index("date")[d.columns[1]].sort_index()


def asof_levels(cal, series, name):
    """As-of level on every session; the series must reach the last session (no accrual beyond the file)."""
    assert series.index[-1] >= cal[-1], f"{name}: the file ends {series.index[-1].date()} before the last session {cal[-1].date()}"
    assert series.index[0] <= cal[0], f"{name}: the file starts after the first session"
    lv = series.reindex(cal, method="ffill").values.astype(float)
    assert not np.isnan(lv).any(), f"{name}: NaN level on a session"
    return lv


def load_market():
    """Everything that does not depend on the book: calendar, index closes and OHLC4 fills, the GOLDBEES chain, cash, the signal files."""
    cal = load_calendar()
    n = len(cal)
    C = np.empty((n, 3))
    F = np.empty((n, 3))
    raw_rows = {}
    for k, nm in enumerate(INDICES):
        d = load_index_csv(nm, T0_FULL)
        miss = cal.difference(d.index)
        assert len(miss) == 0, f"{nm}: {len(miss)} sessions of the calendar have no bar, first {miss[:3]}"
        d = d.reindex(cal)
        C[:, k] = d["close"].values
        F[:, k] = ((d["open"] + d["high"] + d["low"] + d["close"]) / 4.0).values
        raw_rows[nm] = len(d)
    b, g, m = load_gold_files()
    assert b.index[-1] == PROXY_LAST and g.index[0] == GOLDBEES_START, (b.index[-1], g.index[0])
    fill_g, no_mcx = despiked_goldbees_fill(g, m)
    close_own = pd.concat([b["close"], g["close"]])
    fill_own = pd.concat([(b["open"] + b["high"] + b["low"] + b["close"]) / 4.0, fill_g])
    assert close_own.index.is_unique and (close_own > 0).all() and not fill_own.isna().any()
    gc = close_own.reindex(cal, method="ffill").values.astype(float)
    gf = fill_own.reindex(cal, method="ffill").values.astype(float)
    assert not np.isnan(gc).any() and not np.isnan(gf).any()
    no_own = [str(d.date()) for d in cal if d not in close_own.index]
    in_g = cal[cal >= GOLDBEES_START]
    no_mcx_dates = [str(d.date()) for d in in_g if d in no_mcx.index and bool(no_mcx.loc[d])]
    proxy_period = (cal < GOLDBEES_START)
    gf7a = np.where(proxy_period, gc, gf)                  # R7a: the proxy period's fills at the proxy's close
    lbes = asof_levels(cal, load_lbes(), "LBES")
    liq = asof_levels(cal, load_liquidcase(), "LIQUIDCASE")
    months = cal.month.values
    prev = np.r_[0, months[:-1]]
    isq = np.isin(months, [1, 4, 7, 10]) & (months != prev)
    isq[0] = False
    resets = [int(i) for i in np.flatnonzero(isq)]
    return dict(cal=cal, n=n, C=C, F=F, gc=gc, gf=gf, gf7a=gf7a, L=lbes, L2=liq, masters=load_masters(), gmaster=load_mauc1_master(),
                resets=resets, no_own_gold_bar=no_own, no_mcx_range=no_mcx_dates, proxy_period=proxy_period, index_rows=raw_rows,
                gold_chain=dict(b=b, g=g, m=m), gweekly=load_mauc1_weekly())


def make_view(P, a, w, cash="lbes", fills="norm"):
    """Slice of the market from session a (the window's T0: NAV 1.000 at its close) for the weight vector w."""
    return dict(cal=P["cal"][a:], n=P["n"] - a, a=a, C=P["C"][a:], F=P["F"][a:], gc=P["gc"][a:],
                gf=(P["gf"] if fills == "norm" else P["gf7a"])[a:], L=(P["L"] if cash == "lbes" else P["L2"])[a:],
                w=np.asarray(w, dtype=float), resets=[i - a for i in P["resets"] if i > a], proxy_period=P["proxy_period"][a:])


def _asof(dates, sg, d):
    pos = int(np.searchsorted(dates, np.datetime64(d), side="right") - 1)
    assert pos >= 0, f"no Master row on or before {d}"
    return sg[pos], pd.Timestamp(dates[pos])


def decisions_for_window(P, a):
    """Decision dates: the window's T0, then the last session of each later ISO week. Evidence column layout (without `book`) plus the MAUc1
    columns. Every Master (the three indices and MAUc1) is read as-of: the latest row dated on or before the decision date."""
    cal = P["cal"][a:]
    t0 = cal[0]
    iso = cal.isocalendar()
    key = iso["year"].astype(int).values * 100 + iso["week"].astype(int).values
    df = pd.DataFrame({"date": cal, "key": key, "idx": np.arange(len(cal))})
    last = df.groupby("key").tail(1)
    last = last[last["date"] > t0]
    dec_idx = np.array(sorted(set([0] + last["idx"].values.tolist())))
    rows = []
    for j, ix in enumerate(dec_idx):
        d = cal[ix]
        signs, labels = [], []
        for nm in INDICES:
            dates, sg = P["masters"][nm]
            s_, l_ = _asof(dates, sg, d)
            signs.append(s_); labels.append(l_)
        gs, gl = _asof(P["gmaster"][0], P["gmaster"][1], d)
        latest = max(labels)
        buy = all(s == "BUY" for s in signs)
        trade = cal[ix + 1] if ix + 1 < len(cal) and j < len(dec_idx) - 1 else None
        g = 1 if gs == "BUY" else 0
        rows.append(dict(j=j, decision_date=str(d.date()), decision_idx=int(ix), trade_date=None if trade is None else str(trade.date()),
                         sign_Nifty100=signs[0], sign_MC100=signs[1], sign_SC100=signs[2],
                         label_Nifty100=str(labels[0].date()), label_MC100=str(labels[1].date()), label_SC100=str(labels[2].date()),
                         latest_label=str(latest.date()), label_age_days=int((d - latest).days), all_three_buy=bool(buy), state=int(buy),
                         sign_MAUc1=gs, label_MAUc1=str(gl.date()), g=g, gw=GW_BUY if g == 1 else GW_SELL))
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------------------------
# the simulation
# ----------------------------------------------------------------------------------------
def build_switches(mode, states, gws, dec_idx, mix_f):
    """Session index -> (e_new, gw_new, kind, decision j) for every scheduled decision trade.
    rule  : a trade exists at decision j (traded on the next session) iff the equity target changes, or the target stays 0 and the sleeve's
            gold weight changes; the last decision is made, not traded. A change of g while IN is not a trade.
    mix   : every decision but the last (rebalance to e = f, gold weight gws[j] of the non-proxy share), including after T0's decision.
    sleeve: the 100% sleeve; trades only when the gold weight changes. hold / index: none."""
    D = len(states)
    sw = {}
    if mode == "mix":
        for j in range(0, D - 1):
            sw[int(dec_idx[j]) + 1] = (float(mix_f), float(gws[j]), "mix_rebalance", j)
    elif mode == "sleeve":
        gw_t = float(gws[0])
        for j in range(1, D - 1):
            if float(gws[j]) != gw_t:
                gw_t = float(gws[j])
                sw[int(dec_idx[j]) + 1] = (0.0, gw_t, "sleeve_rebalance", j)
    elif mode == "rule":
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


def simulate(V, states, bps, dec_idx, gws, mode="rule", mix_f=None, w=None, closed_form=False, positions=False):
    """One realisation on view V (sessions 0..n-1).

    mode  : 'rule' (the switch), 'mix' (constant mix at e = mix_f), 'hold' (the proxy always, quarterly resets), 'sleeve' (100% sleeve),
            'index' (one index at weight 1, no resets: pass w as a unit vector)
    states: decision states s_0..s_(D-1); dec_idx: the decisions' session indices in V; gws: the gold weight of the sleeve at every decision
    Trade arithmetic (T06 / T08 trade(), amendment 1): V = value of every holding at the fill; targets e*V*w_i, (1-e)*gw*V, (1-e)*(1-gw)*V;
    traded = sum of absolute changes (indices, GOLDBEES, cash); cost = traded * bps/2/1e4; every target scaled by (V - cost)/V."""
    n = V["n"]
    C, F = V["C"], V["F"]
    gc, gf, L = V["gc"], V["gf"], V["L"]
    w = V["w"] if w is None else np.asarray(w, dtype=float)
    gws = np.asarray(gws, dtype=float)
    assert len(gws) == len(states)
    ow = bps / 2.0 / 10000.0
    if mode == "rule":
        e = float(states[0])
    elif mode == "mix":
        e = float(mix_f)
    elif mode in ("hold", "index"):
        e = 1.0
    else:
        e = 0.0
    gw_cur = float(gws[0])
    uidx = e * w / C[0]                              # the initial position is free, at T0's close (NAV 1.000)
    gu = (1.0 - e) * gw_cur / gc[0]
    cu = (1.0 - e) * (1.0 - gw_cur) / L[0]
    sw = build_switches(mode, states, gws, dec_idx, mix_f)
    resets = V["resets"] if mode in ("rule", "hold") else []
    events = sorted(set(k for k in sw if k < n) | set(resets))
    segs = [(0, uidx.copy(), gu, cu)]
    trades = []
    for i in events:
        if i in sw:
            e_new, gw_new, kind, jdec = sw[i]
        else:
            if e != 1.0:
                continue                      # quarterly reset: only if the book holds the proxy at the start of the session
            e_new, gw_new, kind, jdec = 1.0, gw_cur, "quarterly_reset", None
        fi = F[i]
        cur_i = uidx * fi
        cur_g = gu * gf[i]
        cur_c = cu * L[i]
        Vv = float(cur_i.sum() + cur_g + cur_c)
        tgt_i = e_new * Vv * w
        tgt_g = (1.0 - e_new) * gw_new * Vv
        tgt_c = (1.0 - e_new) * (1.0 - gw_new) * Vv
        traded = float(np.abs(tgt_i - cur_i).sum() + abs(tgt_g - cur_g) + abs(tgt_c - cur_c))
        cost = traded * ow
        fac = (Vv - cost) / Vv
        uidx = tgt_i * fac / fi
        gu = tgt_g * fac / gf[i]
        cu = tgt_c * fac / L[i]
        gw_before = gw_cur
        e = e_new
        gw_cur = gw_new
        segs.append((i, uidx.copy(), gu, cu))
        trades.append(dict(idx=i, date=str(V["cal"][i].date()), kind=kind, e_after=e, gw_after=(np.nan if mode in ("hold", "index") else gw_new),
                           V=Vv, traded=traded, cost=cost, j=jdec, gw_before=gw_before, gold_before=cur_g, cash_before=cur_c,
                           gold_after=tgt_g * fac, cash_after=tgt_c * fac, idx_before=cur_i.copy(), idx_after=tgt_i * fac,
                           proxy_period=bool(V["proxy_period"][i]), units=(uidx.copy(), gu, cu)))
    nav = np.empty(n)
    seg_end = [s[0] for s in segs[1:]] + [n]
    closed_max_rel = 0.0
    prod = 1.0
    prev_end_val = None
    for (i0, ui, gu_, cu_), i1 in zip(segs, seg_end):
        v = C[i0:i1] @ ui + gc[i0:i1] * gu_ + L[i0:i1] * cu_
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
    for t in trades:
        t["nav_close_after"] = float(nav[t["idx"]])
    out = dict(nav=nav, trades=trades, closed_rel=closed_max_rel, n_segments=len(segs), end_from_segments=prod if closed_form else np.nan)
    if positions:
        pos = []
        for t in trades:
            ui, gu_, cu_ = t["units"]
            for nm, u in zip(INDICES, ui):
                pos.append((t["date"], nm, float(u)))
            pos.append((t["date"], "GOLDBEES", float(gu_)))
            pos.append((t["date"], "LBES", float(cu_)))
        out["positions"] = pos
    return out


def hand_hold_proxy(V, w):
    """V4(b): the 0-cost always-in proxy built by a plain day-by-day loop (no segments, no trade function): units set at T0's close; at the first
    session of each calendar quarter (after T0) the three positions are set back to the weights at that session's OHLC4 fill."""
    C, F = V["C"], V["F"]
    n = V["n"]
    units = np.asarray(w, dtype=float) / C[0]
    resets = set(V["resets"])
    nav = np.empty(n)
    for i in range(n):
        if i in resets:
            val = float(sum(units[k] * F[i][k] for k in range(3)))
            units = np.array([w[k] * val / F[i][k] for k in range(3)])
        nav[i] = float(sum(units[k] * C[i][k] for k in range(3)))
    return nav


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


def draw_lengths_own(rng, k, S, lo, hi, tab):
    """One uniform ordered k-tuple in [lo, hi] summing to S, parts one at a time: P(x) proportional to c(m-1, t-x); rng.random() and a
    cumulative-sum search (T09.md section 3 step 11), one random number per part including the last."""
    out = []
    t = S
    for m in range(k, 0, -1):
        hi_t = min(hi, t)
        w = np.array([tab[m - 1][t - x] for x in range(lo, hi_t + 1)], dtype=float)
        cum = np.cumsum(w)
        u = rng.random()
        idx = int(np.searchsorted(cum, u * cum[-1], side="right"))
        out.append(lo + min(idx, len(w) - 1))
        t -= out[-1]
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


def n410_states_own(first_state, tb1, tb0, seed_base, draw_id, tabs):
    """Own N4.10 / N4.10-g draw: 1-spell lengths first, then 0-spell lengths, from one generator default_rng(seed_base + [id]).
    tb1 / tb0 = (k, S, lo, hi) of the 1-spells and the 0-spells."""
    rng = np.random.default_rng(list(seed_base) + [int(draw_id)])
    ones = draw_lengths_own(rng, tb1[0], tb1[1], tb1[2], tb1[3], tabs[tb1])
    zeros = draw_lengths_own(rng, tb0[0], tb0[1], tb0[2], tb0[3], tabs[tb0])
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


def rule_structure(states):
    runs = runs_of(states)
    ins = [l for v, l in runs if v == 1]
    outs = [l for v, l in runs if v == 0]
    return dict(weeks=len(states), first_state=int(states[0]), last_state=int(states[-1]), in_spells=len(ins), out_spells=len(outs),
                S_in=int(sum(ins)), S_out=int(sum(outs)), in_lengths=ins, out_lengths=outs,
                longest_in=max(ins) if ins else 0, longest_out=max(outs) if outs else 0,
                shortest_in=min(ins) if ins else 0, shortest_out=min(outs) if outs else 0, invested_weeks=int(np.sum(states)))


def week_cover(dec_idx):
    """Sessions between a decision and the next, as the engine counts them: cover_j = dec_idx[j+1] - dec_idx[j] for every week but the last
    (decided on the last session, never traded: 0)."""
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


def need_cols(chk, df, cols, fname):
    """True if every column is present; otherwise record MISSING for each absent one (a clear message instead of a KeyError)."""
    absent = [c for c in cols if c not in df.columns]
    for c in absent:
        chk.miss(f"{fname} column {c}")
    return not absent


def gws_of(g, mode="timed"):
    g = np.asarray(g)
    if mode == "fixed50":
        return np.full(len(g), GW_FIX)
    return np.where(g == 1, GW_BUY, GW_SELL).astype(float)


def bounds_of(Rs):
    """Per state of a series, lo = min(2, shortest spell), hi = longest spell (T09.md section 2 / step 11)."""
    return dict(in_=(min(2, Rs["shortest_in"]), Rs["longest_in"]), out=(min(2, Rs["shortest_out"]), Rs["longest_out"]))


# ----------------------------------------------------------------------------------------
# derive everything that does not depend on the evidence
# ----------------------------------------------------------------------------------------
def derive(books=BOOKS, verbose=True):
    t = time.time()
    P = load_market()
    n = P["n"]
    cal = P["cal"]
    a_r3 = int(np.searchsorted(cal.values, np.datetime64(R3_START), side="left"))
    D = {"P": P, "a_r3": a_r3, "books": {}, "nav": [], "stats": [], "trades": [], "positions": [], "units": [], "resets": [], "rule": {}, "meta": {},
         "dec_all": {}}
    if verbose:
        print(f"[{time.time()-t:6.1f}s] market loaded: {n} sessions {cal[0].date()} -> {cal[-1].date()}; R3 starts {cal[a_r3].date()} (session {a_r3}); "
              f"quarter starts {len(P['resets'])}; sessions without an own gold bar {P['no_own_gold_bar']}; without an MCX range {P['no_mcx_range']}", flush=True)
    # decisions and the real series: shared by the four books (the signals do not depend on the book)
    for window, a in (("full", 0), ("r3", a_r3)):
        dec = decisions_for_window(P, a)
        s = dec["state"].values.astype(int)
        gg = dec["g"].values.astype(int)
        di = dec["decision_idx"].values
        R = dict(dec=dec, states=s.astype(np.uint8), gstates=gg.astype(np.uint8), dec_idx=di, cover=week_cover(di), a=a,
                 io=rule_structure(s), g=rule_structure(gg), sessions=n - a, start=str(cal[a].date()), end=str(cal[-1].date()))
        R["sleeve_trades"] = int(sum(1 for j in range(1, len(s) - 1) if s[j] == 0 and s[j - 1] == 0 and gg[j] != gg[j - 1]))
        bi, bg = bounds_of(R["io"]), bounds_of(R["g"])
        R["bnd"] = {("io", "in"): bi["in_"], ("io", "out"): bi["out"], ("gold", "buy"): bg["in_"], ("gold", "sell"): bg["out"]}
        D["rule"][window] = R
        D["dec_all"][window] = dec
    dates_str = [str(d.date()) for d in cal]
    for p in books:
        w = WEIGHTS[p]
        V = make_view(P, 0, w)
        Vliq = make_view(P, 0, w, "liq")
        Vr3 = make_view(P, a_r3, w)
        V7a = make_view(P, 0, w, "lbes", "7a")
        Rf, Rr = D["rule"]["full"], D["rule"]["r3"]
        s, gs, di = Rf["states"].astype(int), Rf["gstates"].astype(int), Rf["dec_idx"]
        s3, gs3, di3 = Rr["states"].astype(int), Rr["gstates"].astype(int), Rr["dec_idx"]
        nd = len(s)
        f_mix = s.sum() / nd
        gw_t, gw_5 = gws_of(gs), gws_of(gs, "fixed50")
        gw_t3, gw_53 = gws_of(gs3), gws_of(gs3, "fixed50")
        gw_7b = np.where(Rf["dec"]["decision_date"].values < str(GOLDBEES_START.date()), GW_FIX, gw_t)
        ones, zeros = np.ones(nd, dtype=int), np.zeros(nd, dtype=int)
        D["books"][p] = dict(V=V, Vliq=Vliq, Vr3=Vr3, s=s, g=gs, gw_t=gw_t, gw_5=gw_5, dec_idx=di, s_r3=s3, g_r3=gs3, gw_t_r3=gw_t3, gw_5_r3=gw_53,
                             dec_idx_r3=di3, f=f_mix, w=np.array(w))
        D["meta"][p] = dict(sessions=n, decisions=nd, invested_weeks=int(s.sum()), f=f_mix, t0=str(cal[0].date()), end=str(cal[-1].date()),
                            r3_sessions=n - a_r3, sleeve_trades=Rf["sleeve_trades"], sleeve_trades_r3=Rr["sleeve_trades"])

        def add(window, cash, kind, bps, r, states):
            st = stats_of(r["nav"])
            tr = r["trades"]
            st.update(book=p, window=window, cash=cash, cost_bps=bps, kind=kind, trades=len(tr), cost_paid=float(sum(x["cost"] for x in tr)),
                      closed_rel=r["closed_rel"], n_segments=r["n_segments"], end_from_segments=r["end_from_segments"],
                      invested_weeks=float(np.sum(states)) if kind.startswith("strategy") else np.nan,
                      sleeve_trades=int(sum(1 for x in tr if x["kind"] == "sleeve_rebalance")),
                      quarterly_resets=int(sum(1 for x in tr if x["kind"] == "quarterly_reset")))
            D["stats"].append(st)

        def store(kind, bps, r, positions=False):
            D["nav"].append(pd.DataFrame(dict(book=p, date=dates_str, cost_bps=bps, run=kind, nav=r["nav"])))
            for x in r["trades"]:
                D["trades"].append(dict(book=p, cost_bps=bps, run=kind, idx=x["idx"], date=x["date"], kind=x["kind"], e_after=x["e_after"],
                                        gw_after=x["gw_after"], V=x["V"], traded=x["traded"], cost=x["cost"], nav_close_after=x["nav_close_after"],
                                        j=x["j"], gw_before=x["gw_before"], gold_before=x["gold_before"], cash_before=x["cash_before"],
                                        gold_after=x["gold_after"], cash_after=x["cash_after"], proxy_period=x["proxy_period"]))
                if kind in ("strategy", "strategy_fixed50", "hold_proxy"):
                    ui, gu_, cu_ = x["units"]
                    D["units"].append(dict(book=p, cost_bps=bps, run=kind, date=x["date"], idx=x["idx"], kind=x["kind"], units_Nifty100=ui[0],
                                           units_MC100=ui[1], units_SC100=ui[2], units_GOLDBEES=gu_, units_LBES=cu_))
                if kind == "strategy" and x["kind"] == "quarterly_reset":
                    D["resets"].append(dict(book=p, cost_bps=bps, date=x["date"], idx=x["idx"], V=x["V"], traded=x["traded"], cost=x["cost"],
                                            **{f"value_before_{nm}": x["idx_before"][k] for k, nm in enumerate(INDICES)},
                                            **{f"value_after_{nm}": x["idx_after"][k] for k, nm in enumerate(INDICES)}))
            if positions:
                for dt, nm, u in r["positions"]:
                    D["positions"].append(dict(book=p, cost_bps=bps, run="strategy", date=dt, instrument=nm, units=u))

        hold0 = None
        index0 = {}
        for bps in COSTS:
            runs = {
                "strategy": simulate(V, s, bps, di, gw_t, "rule", closed_form=True, positions=True),
                "strategy_fixed50": simulate(V, s, bps, di, gw_5, "rule"),
                "hold_proxy": simulate(V, ones, bps, di, gw_5, "hold"),
                "constant_mix": simulate(V, s, bps, di, gw_5, "mix", mix_f=f_mix),
                "constant_mix_timed": simulate(V, s, bps, di, gw_t, "mix", mix_f=f_mix),
                "sleeve_only": simulate(V, zeros, bps, di, gw_5, "sleeve"),
                "sleeve_only_timed": simulate(V, zeros, bps, di, gw_t, "sleeve"),
            }
            for k, nm in enumerate(INDICES):
                runs[f"index_{nm}"] = simulate(V, ones, bps, di, gw_5, "index", w=np.eye(3)[k])
            if bps == 0.0:
                hold0 = runs["hold_proxy"]["nav"]
                index0 = {nm: runs[f"index_{nm}"]["nav"] for nm in INDICES}
            if abs(bps - HEADLINE_COST) < 1e-9:
                runs[R7A] = simulate(V7a, s, bps, di, gw_t, "rule")
                runs[R7B] = simulate(V, s, bps, di, gw_7b, "rule")
            for kind, r in runs.items():
                add("full", "lbes", kind, bps, r, s)
                store(kind, bps, r, positions=(kind == "strategy"))
        # R2 (LIQUIDCASE cash) and R3 (the window from 2012-01-02), 20.8 bps, the rule with the timed and with the fixed sleeve
        for mode, gw_, gw3_, kind in (("timed", gw_t, gw_t3, "strategy"), ("fixed50", gw_5, gw_53, "strategy_fixed50")):
            add("full", "liq", kind, HEADLINE_COST, simulate(Vliq, s, HEADLINE_COST, di, gw_, "rule"), s)
            add("r3", "lbes", kind, HEADLINE_COST, simulate(Vr3, s3, HEADLINE_COST, di3, gw3_, "rule"), s3)
        D["books"][p]["hold0"] = hold0
        D["books"][p]["index0"] = index0
        if verbose:
            print(f"[{time.time()-t:6.1f}s] {p}: simulated (f={f_mix:.4f}, sleeve trades {Rf['sleeve_trades']}, hold-proxy 0-cost CAGR "
                  f"{(hold0[-1] ** (252.0 / (n - 1)) - 1) * 100:.2f}%)", flush=True)
    D["nav"] = pd.concat(D["nav"], ignore_index=True)
    D["stats"] = pd.DataFrame(D["stats"])
    D["trades"] = pd.DataFrame(D["trades"])
    D["positions"] = pd.DataFrame(D["positions"])
    D["units"] = pd.DataFrame(D["units"])
    D["resets"] = pd.DataFrame(D["resets"])
    D["dec"] = pd.concat([D["dec_all"]["full"].assign(book=p) for p in books], ignore_index=True)
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
                        kw = {"dtype": {c_: str for c_ in ("in_lengths", "out_lengths", "g_buy_lengths", "g_sell_lengths", "spell_sig", "strategy_sig",
                                                          "g_spell_sig", "real_g_spell_sig")}} if name == "draws.csv" else {}
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
            self.d[key] = simulate(V, np.asarray(states, dtype=int), bps, dec_idx, gws, "rule")
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
    Dn = S.shape[1]
    if Dn < 3:
        return np.zeros(len(S), dtype=int)
    return ((S[:, 1:Dn - 1] == 0) & (S[:, 0:Dn - 2] == 0) & (G[:, 1:Dn - 1] != G[:, 0:Dn - 2])).sum(axis=1).astype(int)


def expected_groups(books):
    """(book, window, cash, cost, family, sleeve_mode) groups draws.csv must hold (contract 'rows in draws.csv')."""
    g = []
    for p in books:
        for fam in ("F1", "F2", "F3", "F4"):
            for cst in COSTS:
                g.append((p, "full", "lbes", cst, fam, "timed"))
        g.append((p, "full", "lbes", HEADLINE_COST, "F5", "timed"))
        for fam in ("F1", "F2"):
            for cst in COSTS:
                g.append((p, "full", "lbes", cst, fam, "fixed50"))
        g.append((p, "full", "liq", HEADLINE_COST, "F1", "timed"))
        g.append((p, "full", "liq", HEADLINE_COST, "F3", "timed"))
        g.append((p, "full", "liq", HEADLINE_COST, "F1", "fixed50"))
        g.append((p, "r3", "lbes", HEADLINE_COST, "F1", "timed"))
        g.append((p, "r3", "lbes", HEADLINE_COST, "F3", "timed"))
        g.append((p, "r3", "lbes", HEADLINE_COST, "F1", "fixed50"))
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


def required_through(row):
    """Latest date an approved row must reach: the window's end, except D09b (the proxy ends 2014-06-30 by design; D09 takes over)."""
    return PROXY_LAST if row["id"] == "D09b" else END


# ----------------------------------------------------------------------------------------
# the checks
# ----------------------------------------------------------------------------------------
def compare_all(D, E, BK):
    C = {}
    nd_draws = N_DRAWS
    P = D["P"]
    cal = P["cal"]
    dates_str = [str(d.date()) for d in cal]
    RULE = D["rule"]
    WINDOWS = ["full", "r3"]

    # ------------------------------------------------------------------ C-data
    def c_data(c):
        inp = E.get("inputs.csv", c)
        for key in sorted(READS):
            row = APPROVED.get(key)
            c.compared += 1
            ok = row is not None and row["status"] == "APPROVED"
            if ok:
                sha = sha256_file(AA / key)
                ok = sha.startswith(row["sha"])
                if ok and row["through"].lower() != "n/a":
                    ok = pd.Timestamp(row["through"]) >= required_through(row)
                uf = row["usable_from"]
                if ok and uf is not None:
                    fd = READS[key]["first_date"]
                    c.compared += 1
                    ok = fd is not None and pd.Timestamp(fd) >= pd.Timestamp(uf)
            if not ok:
                c.failed += 1; c.fail(f"verifier-read file not an APPROVED, matching, covering, unrestricted row: {key}")
        if inp is None:
            return
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
            c.compared += 2
            if not sha.startswith(row["sha"]):
                c.failed += 1; c.fail(f"sha256 of {key} in inputs.csv ({sha[:16]}) does not start with the approved prefix {row['sha']}")
            disk = sha256_file(AA / key) if (AA / key).exists() else None
            if disk is None or (sha and disk != sha and not disk.startswith(sha)):
                c.failed += 1; c.fail(f"sha256 of {key} in inputs.csv differs from the file on disk")
            if "through" in cols:
                c.compared += 1
                th = str(r[cols["through"]]).strip()
                if row["through"].lower() != "n/a" and pd.Timestamp(row["through"]) < required_through(row):
                    c.failed += 1; c.fail(f"approved through-date of {key} ({row['through']}) does not cover the window's end")
                if th.lower() not in ("n/a", "nan") and row["through"].lower() != "n/a" and th != row["through"]:
                    c.failed += 1; c.fail(f"through of {key} in inputs.csv ({th}) differs from APPROVED_DATA.md ({row['through']})")
            # standing rule 7: the usable_from of a restricted file in inputs.csv is the registry's marker
            if "usable_from" in cols:
                c.compared += 1
                uv = r[cols["usable_from"]]
                uv = None if (uv is None or (isinstance(uv, float) and np.isnan(uv)) or str(uv).strip() in ("", "nan", "None")) else str(uv).strip()
                if uv != row["usable_from"]:
                    c.failed += 1; c.fail(f"usable_from of {key} in inputs.csv ({uv}) differs from the registry's marker ({row['usable_from']})")
            else:
                c.miss("inputs.csv column usable_from")
        not_listed = sorted(set(READS) - listed)
        extra_listed = sorted(listed - set(READS))
        for key in not_listed:               # a file the verifier needed to rebuild the run but the engine does not list
            c.compared += 1; c.failed += 1; c.fail(f"a file needed to rebuild the run is not in inputs.csv: {key}")
        if extra_listed:
            c.notes.append(f"inputs.csv lists {len(extra_listed)} file(s) the verifier did not read: {extra_listed[:4]}")
        c.notes.append(f"{len(READS)} files read by the verifier, {len(listed)} listed in inputs.csv")
    run_check(C, "C-data", c_data)

    # ------------------------------------------------------------------ standing rule 7 (V2, V4e)
    def c_sc100(c):
        for first, fn in (("2011-10-02", lambda f: rd(F_IDX["SC100"], f)), ("2011-11-24", lambda f: rd(F_MASTER["SC100"], f)),
                          ("2004-01-01", lambda f: load_index_csv("SC100", f))):
            c.compared += 1
            try:
                fn(first)
                c.failed += 1; c.fail(f"the verifier did not refuse a Smallcap 100 read from {first}")
            except RuntimeError:
                pass
        c.compared += 1
        try:
            rd(F_IDX["SC100"])
            c.failed += 1; c.fail("a restricted file was registered without a first read date")
        except RuntimeError:
            pass
        for nm, f in (("SC100 prices", F_IDX["SC100"]), ("SC100 signal", F_MASTER["SC100"])):
            c.compared += 1
            if APPROVED[f]["usable_from"] is None:
                c.failed += 1; c.fail(f"{nm}: the registry row carries no usable-from marker")
        dec = D["dec_all"]["full"]
        c.compared += 1
        if (dec["label_SC100"] < str(SC100_SIGNAL_FROM.date())).any():
            c.failed += 1; c.fail("a Smallcap 100 decision reads a Master row dated before 2011-11-25")
        d0 = E.get("decisions.csv")
        if d0 is not None and "label_SC100" in d0.columns:
            c.compared += 1
            if (d0["label_SC100"].astype(str) < str(SC100_SIGNAL_FROM.date())).any():
                c.failed += 1; c.fail("the engine's decisions read a Smallcap 100 Master row dated before 2011-11-25")
        c.compared += 1
        if cal[0] < SC100_PRICE_FROM:
            c.failed += 1; c.fail("the window starts before the Smallcap 100 prices are usable")
    run_check(C, "C-sc100-restriction", c_sc100)

    # ------------------------------------------------------------------ C-dec, C-pit
    dec_m = D["dec"]

    def c_dec(c):
        ev = E.get("decisions.csv", c)
        if ev is None:
            return
        ev = ev[ev["book"].isin(BK)].copy()
        ev["all_three_buy"] = ev["all_three_buy"].astype(str)
        mine = dec_m[dec_m["book"].isin(BK)].copy()
        mine["all_three_buy"] = mine["all_three_buy"].astype(str)
        str_cols = ["trade_date", "sign_Nifty100", "sign_MC100", "sign_SC100", "label_Nifty100", "label_MC100", "label_SC100",
                    "latest_label", "decision_date", "all_three_buy", "sign_MAUc1", "label_MAUc1"]
        if not need_cols(c, ev, ["book", "j", "decision_idx", "label_age_days", "state", "g", "gw"] + str_cols, "decisions.csv"):
            return
        compare_frames(c, mine, ev, ["book", "j"], num_cols=["decision_idx", "label_age_days", "state", "g", "gw"], str_cols=str_cols)
    run_check(C, "C-dec", c_dec)

    def c_pit(c):
        ev = E.get("decisions.csv", c)
        lcs = ["label_Nifty100", "label_MC100", "label_SC100", "label_MAUc1"]
        qstarts = set(dates_str[i] for i in P["resets"])
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
                mm = sw.merge(ev[["book", "trade_date", "decision_date"]], left_on=["book", "date"], right_on=["book", "trade_date"], how="left")
                okk = mm["decision_date"].notna() & (mm["date"].astype(str) > mm["decision_date"].astype(str))
                c.compared += len(mm); c.failed += int((~okk).sum())
                if (~okk).any(): c.fail("switch / sleeve trade without an earlier decision: %s" % mm[~okk].iloc[0][["book", "date"]].to_dict())
                rs = tr[(tr["run"] == "strategy") & (tr["kind"] == "quarterly_reset")]
                okr = rs["date"].astype(str).isin(qstarts)
                c.compared += len(rs); c.failed += int((~okr).sum())
                if (~okr).any(): c.fail("a quarterly reset not on a calendar-defined quarter start: %s" % rs[~okr].iloc[0][["book", "date"]].to_dict())
                c.compared += len(tr)
                bad = ((tr["date"].astype(str) <= str(cal[0].date())) | (tr["date"].astype(str) > str(cal[-1].date())))
                c.failed += int(bad.sum())
                if bad.any(): c.fail("a trade outside (T0, END]")
        md = dec_m
        for lc in lcs:
            ok = (md[lc] <= md["decision_date"]).values
            c.compared += len(md); c.failed += int((~ok).sum())
        mt = md["trade_date"].notna()
        ok = (md.loc[mt, "trade_date"] > md.loc[mt, "decision_date"]).values
        c.compared += int(mt.sum()); c.failed += int((~ok).sum())
        c.compared += 1
        if cal[-1] != END:
            c.failed += 1; c.fail("the calendar does not end at END")
    run_check(C, "C-pit", c_pit)

    # ------------------------------------------------------------------ stats / NAV based checks
    est_all = E.get("stats.csv")
    env_all = E.get("daily_nav.csv")
    mst = D["stats"].copy()
    mst["cost_bps"] = r4(mst["cost_bps"])
    mnv = D["nav"].copy()
    mnv["cost_bps"] = r4(mnv["cost_bps"])
    if est_all is not None:
        est_all = est_all[est_all["book"].isin(BK)].copy()
        est_all["cost_bps"] = r4(est_all["cost_bps"])
        if "cash" in est_all.columns:
            est_all["cash"] = est_all["cash"].replace({"liquidcase": "liq"})
    if env_all is not None:
        env_all = env_all[env_all["book"].isin(BK)].copy()
        env_all["cost_bps"] = r4(env_all["cost_bps"])
        env_all["date"] = env_all["date"].astype(str)

    NUMS = ["end_nav", "cagr", "max_dd", "vol"]
    NUMS_ALL = NUMS + ["ulcer", "calmar"]
    INTS = ["days_below_10pct", "longest_underwater", "sessions"]

    def est(window="full", cash="lbes"):
        return est_all[(est_all["window"] == window) & (est_all["cash"] == cash)]

    def nav_subset(df, kinds, costs):
        return df[df["run"].isin(kinds) & df["cost_bps"].isin(costs)]

    def stat_subset(df, kinds, costs, window="full", cash="lbes"):
        m = df[df["kind"].isin(kinds) & df["cost_bps"].isin(costs)]
        if "window" in m.columns:
            m = m[(m["window"] == window) & (m["cash"] == cash)]
        return m

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
        """Every statistic of every stats.csv row of every cell (full/lbes: all runs at all costs, R7 at 20.8; full/liq and r3/lbes: the rule at 20.8)."""
        if est_all is None:
            E.get("stats.csv", c); return
        keys = ["book", "window", "cash", "cost_bps", "kind"]
        cols = NUMS_ALL + INTS + ["trades", "cost_paid", "quarterly_resets", "sleeve_trades", "invested_weeks"]
        if not need_cols(c, est_all, keys + cols, "stats.csv"):
            return
        m = mst[keys + cols].copy()
        e = est_all[keys + cols].copy()
        m.loc[~m["kind"].str.startswith("strategy"), "invested_weeks"] = np.nan        # defined for the rule's two parts and R7 only
        e.loc[~e["kind"].str.startswith("strategy"), "invested_weeks"] = np.nan
        compare_frames(c, m, e, keys, num_cols=cols)
    run_check(C, "C-stats-all", c_stats_all)

    def c_comp(c):
        if env_all is None or est_all is None:
            E.get("daily_nav.csv", c); E.get("stats.csv", c); return
        kinds = [k for k in ALL_KINDS if k != "strategy"]
        absent = [k for k in R7_KINDS if k not in set(env_all["run"])]
        if absent:     # reading: the contract lists R7 among daily_nav.csv's run values, but R7 is a 20.8-bps sensitivity run; if the evidence omits its curve, its statistics (stats.csv, C-stats-all) are what is compared
            c.notes.append(f"daily_nav.csv has no curve for {absent} (listed in the contract's run values); compared through stats.csv only")
            kinds = [k for k in kinds if k not in absent]
        compare_frames(c, nav_subset(mnv, kinds, COSTS), nav_subset(env_all, kinds, COSTS), ["book", "date", "cost_bps", "run"], num_cols=["nav"])
    run_check(C, "C-comp", c_comp)

    # ------------------------------------------------------------------ trades, units, positions
    def prep_tr(df, run):
        t = df[df["run"] == run].copy()
        t["cost_bps"] = r4(t["cost_bps"])
        t["seq"] = t.groupby(["book", "cost_bps"]).cumcount()
        return t

    def c_trades(c):
        tr = E.get("trades.csv", c)
        if tr is None:
            return
        tr = tr[tr["book"].isin(BK)]
        keys = ["book", "cost_bps", "seq"]
        if not need_cols(c, tr, ["book", "cost_bps", "run", "date", "idx", "kind", "e_after", "V", "traded", "cost", "nav_close_after", "gw_after"], "trades.csv"):
            return
        for run in ALL_KINDS:
            mt = prep_tr(D["trades"], run)
            et = prep_tr(tr, run)
            if not len(et) and not len(mt):
                continue
            if not len(et):
                if run in R7_KINDS:
                    c.notes.append(f"trades.csv has no rows for {run} (the contract lists it among the run values); its trade count is compared through stats.csv"); continue
                c.miss(f"trades.csv has no rows for run {run}"); continue
            et["date"] = et["date"].astype(str)
            num = ["idx", "e_after", "V", "traded", "cost", "nav_close_after"]
            compare_frames(c, mt, et, keys, num_cols=num, str_cols=["date", "kind"])
            if run.startswith("strategy"):          # gw_after is compared on the trades that leave the book OUT (what an IN trade carries is undefined)
                compare_frames(c, mt[mt["e_after"] == 0][keys + ["gw_after"]], et[et["e_after"] == 0][keys + ["gw_after"]], keys, num_cols=["gw_after"], tol=0.0)
        c.notes.append("all runs of trades.csv compared, strategy and strategy_fixed50 (switches, sleeve rebalances, quarterly resets), hold_proxy (resets), constant mixes, sleeve-only, index_*, R7")
    run_check(C, "C-trades", c_trades)

    def c_units(c):
        pu = E.get("proxy_units.csv", c)
        if pu is None:
            return
        pu = pu[pu["book"].isin(BK)].copy()
        pu["cost_bps"] = r4(pu["cost_bps"])
        pu["seq"] = pu.groupby(["book", "cost_bps", "run"]).cumcount()
        pu["date"] = pu["date"].astype(str)
        mine = D["units"].copy()
        mine["cost_bps"] = r4(mine["cost_bps"])
        mine["seq"] = mine.groupby(["book", "cost_bps", "run"]).cumcount()
        ucols = [f"units_{x}" for x in INSTR]
        if not need_cols(c, pu, ["run", "date", "idx", "kind"] + ucols, "proxy_units.csv"):
            return
        compare_frames(c, mine, pu, ["book", "cost_bps", "run", "seq"], num_cols=["idx"] + ucols, str_cols=["date", "kind"])
    run_check(C, "C-proxy-units", c_units)

    def c_positions(c):
        ps = E.get("positions.csv", c)
        if ps is None:
            return
        ev = ps[ps["book"].isin(BK) & (ps["units"] != 0)].copy(); ev["cost_bps"] = r4(ev["cost_bps"]); ev["date"] = ev["date"].astype(str)
        ev = ev[ev["run"] == "strategy"]
        mine = D["positions"].copy(); mine["cost_bps"] = r4(mine["cost_bps"])
        mine = mine[mine["units"] != 0]
        compare_frames(c, mine, ev[["book", "cost_bps", "run", "date", "instrument", "units"]], ["book", "cost_bps", "run", "date", "instrument"], num_cols=["units"])
    run_check(C, "C-positions", c_positions)

    # ------------------------------------------------------------------ the sleeve: C-sleeve, C-sleeve-identity
    decd = {(r.book, r.j): r.decision_date for r in dec_m.itertuples()}
    decg = {(r.book, r.j): r.g for r in dec_m.itertuples()}

    def my_sleeve_rows():
        mt = D["trades"]
        mt = mt[(mt["run"] == "strategy") & mt["kind"].isin(["switch_out", "sleeve_rebalance"])].copy()
        mt["cost_bps"] = r4(mt["cost_bps"])
        mt["seq"] = mt.groupby(["book", "cost_bps"]).cumcount()
        mt["decision_date"] = [decd[(b, int(j))] for b, j in zip(mt["book"], mt["j"])]
        mt["g_after"] = [decg[(b, int(j))] for b, j in zip(mt["book"], mt["j"])]
        mt["gw_after"] = mt["gw_after"].astype(float)
        reb = mt["kind"] == "sleeve_rebalance"
        mt["g_before"] = np.where(reb, np.where(mt["gw_before"] == GW_BUY, 1.0, 0.0), np.nan)
        mt["gw_before"] = np.where(reb, mt["gw_before"], np.nan)
        mt["gold_value_before"] = np.where(reb, mt["gold_before"], np.nan)
        mt["cash_value_before"] = np.where(reb, mt["cash_before"], np.nan)
        mt = mt.rename(columns={"gold_after": "gold_value_after", "cash_after": "cash_value_after", "proxy_period": "gold_fill_proxy_period"})
        mt["gold_fill_proxy_period"] = mt["gold_fill_proxy_period"].astype(int)
        return mt

    def c_sleeve(c):
        st = E.get("sleeve_trades.csv", c)
        if st is None:
            return
        st = st[st["book"].isin(BK)].copy()
        acols = ["date", "kind", "decision_date", "g_after", "gw_after", "gold_value_after", "cash_value_after", "traded", "cost", "gold_fill_proxy_period"]
        bcols = ["g_before", "gw_before", "gold_value_before", "cash_value_before"]
        if not need_cols(c, st, ["book", "cost_bps", "g_before"] + acols + bcols, "sleeve_trades.csv"):
            return
        st["cost_bps"] = r4(st["cost_bps"])
        st["seq"] = st.groupby(["book", "cost_bps"]).cumcount()
        st["date"] = st["date"].astype(str)
        st["decision_date"] = st["decision_date"].astype(str)
        for col in ("g_before", "g_after"):
            st[col] = [norm_g(x) for x in st[col]]
        st["gold_fill_proxy_period"] = [int(norm_bool(x)) for x in st["gold_fill_proxy_period"]]
        mine = my_sleeve_rows()
        keys = ["book", "cost_bps", "seq"]
        compare_frames(c, mine[keys + acols], st[keys + acols], keys,
                       num_cols=["g_after", "gw_after", "gold_value_after", "cash_value_after", "traded", "cost", "gold_fill_proxy_period"],
                       str_cols=["date", "kind", "decision_date"])
        compare_frames(c, mine[mine["kind"] == "sleeve_rebalance"][keys + bcols], st[st["kind"] == "sleeve_rebalance"][keys + bcols], keys, num_cols=bcols)
        tr = E.get("trades.csv", c)
        if tr is not None:
            a = mine[mine["kind"] == "sleeve_rebalance"].groupby(["book", "cost_bps"]).size().rename("n").reset_index()
            t2 = tr[tr["book"].isin(BK) & (tr["run"] == "strategy") & (tr["kind"] == "sleeve_rebalance")].copy(); t2["cost_bps"] = r4(t2["cost_bps"])
            b = st[st["kind"] == "sleeve_rebalance"].groupby(["book", "cost_bps"]).size().rename("n").reset_index()
            compare_frames(c, b, t2.groupby(["book", "cost_bps"]).size().rename("n").reset_index(), ["book", "cost_bps"], num_cols=["n"], tol=0.0)
            compare_frames(c, a, b, ["book", "cost_bps"], num_cols=["n"], tol=0.0)
        c.notes.append(f"{len(mine)} exits and sleeve rebalances of the verifier's strategy; trades in the proxy period (before 2014-07-01): {int(mine['gold_fill_proxy_period'].sum())}")
    run_check(C, "C-sleeve", c_sleeve)

    def c_sleeve_identity(c):
        """V6 on the engine's own numbers: cost = traded x bps/2/1e4; value conserved (after = before - cost); the post-trade split equals gw_after of the value
        after cost (1e-12 of the value); traded = |dGOLDBEES| + |dcash| on a rebalance; a rebalance needs a change of g; the proxy-period flag is exactly
        'trade session before 2014-07-01'; at 0 cost the value is continuous; an exit's sleeve plus its proceeds equals V - cost."""
        st = E.get("sleeve_trades.csv", c)
        if st is None:
            return
        st = st[st["book"].isin(BK)]
        tr = E.get("trades.csv")
        trk = None
        if tr is not None:
            t_ = tr[tr["book"].isin(BK) & (tr["run"] == "strategy")].copy(); t_["cost_bps"] = r4(t_["cost_bps"]); t_["date"] = t_["date"].astype(str)
            trk = t_.set_index(["book", "cost_bps", "date"])
        for r in st.itertuples():
            bps = float(r.cost_bps)
            gA, cA = float(r.gold_value_after), float(r.cash_value_after)
            reb = str(r.kind) == "sleeve_rebalance"
            sc = max(1.0, abs(gA + cA))
            c.compared += 3
            if abs(float(r.cost) - float(r.traded) * bps / 2.0 / 10000.0) > TOL_ID * sc:
                c.failed += 1; c.fail(f"cost != traded x bps/2/1e4: {r}")
            if abs(float(r.gw_after) - (gA / (gA + cA))) > TOL_ID * (1.0 if reb else 1e3):
                c.failed += 1; c.fail(f"post-trade split {gA / (gA + cA)!r} != gw_after {r.gw_after!r}: {r}")
            if bool(norm_bool(r.gold_fill_proxy_period)) != bool(pd.Timestamp(str(r.date)) < GOLDBEES_START):
                c.failed += 1; c.fail(f"gold_fill_proxy_period wrong: {r}")
            if reb:
                gB, cB = float(r.gold_value_before), float(r.cash_value_before)
                Vb = gB + cB
                tol = TOL_ID * max(1.0, Vb)
                c.compared += 4
                if abs((gA + cA) - (Vb - float(r.cost))) > tol:
                    c.failed += 1; c.fail(f"value not conserved (after = before - cost) at {r}")
                if abs(gA - float(r.gw_after) * (Vb - float(r.cost))) > tol:
                    c.failed += 1; c.fail(f"gold value after != gw_after x value after cost at {r}")
                tr_exp = abs(float(r.gw_after) * Vb - gB) + abs((1 - float(r.gw_after)) * Vb - cB)
                if abs(tr_exp - float(r.traded)) > 1e-9 * max(1.0, tr_exp):
                    c.failed += 1; c.fail(f"traded {r.traded!r} != |dGOLDBEES| + |dcash| {tr_exp!r} at {r}")
                if norm_g(r.g_before) == norm_g(r.g_after) or float(r.gw_before) == float(r.gw_after):
                    c.failed += 1; c.fail(f"a sleeve rebalance without a change of g: {r}")
                if bps == 0.0:
                    c.compared += 1
                    if abs((gA + cA) - Vb) > tol:
                        c.failed += 1; c.fail(f"NAV not continuous through a 0-cost sleeve rebalance: {r}")
            elif trk is not None:
                key = (r.book, round(bps, 4), str(r.date))
                c.compared += 1
                if key not in trk.index:
                    c.miss(f"trades.csv row for the exit {key}"); continue
                row = trk.loc[key]
                row = row.iloc[0] if isinstance(row, pd.DataFrame) else row
                if abs((gA + cA) - (float(row["V"]) - float(row["cost"]))) > TOL_ID * max(1.0, float(row["V"])) * 1e3:
                    c.failed += 1; c.fail(f"an exit's sleeve ({gA + cA!r}) != V - cost ({float(row['V']) - float(row['cost'])!r}) at {r}")
        mine = my_sleeve_rows()
        n_mine = int((mine["kind"] == "sleeve_rebalance").sum())
        n_ev = int((st["kind"] == "sleeve_rebalance").sum())
        c.compared += 1
        if n_mine != n_ev:
            c.failed += 1; c.fail(f"sleeve rebalances: verifier {n_mine}, engine {n_ev}")
    run_check(C, "C-sleeve-identity", c_sleeve_identity)

    # ------------------------------------------------------------------ the quarterly resets: C-reset, C-reset-identity
    def c_reset(c):
        qr = E.get("quarterly_resets.csv", c)
        if qr is None:
            return
        qr = qr[qr["book"].isin(BK)].copy()
        bcol = {nm: next((x for x in qr.columns if x.startswith("value_before") and nm in x), None) for nm in INDICES}
        acol = {nm: next((x for x in qr.columns if x.startswith("value_after") and nm in x), None) for nm in INDICES}
        if not need_cols(c, qr, ["cost_bps", "date", "idx", "V", "traded", "cost"], "quarterly_resets.csv") or None in list(bcol.values()) + list(acol.values()):
            c.miss("quarterly_resets.csv value_before_<index> / value_after_<index> columns"); return
        qr["cost_bps"] = r4(qr["cost_bps"]); qr["date"] = qr["date"].astype(str)
        qr["seq"] = qr.groupby(["book", "cost_bps"]).cumcount()
        ren = {bcol[nm]: f"vb_{nm}" for nm in INDICES}
        ren.update({acol[nm]: f"va_{nm}" for nm in INDICES})
        qr = qr.rename(columns=ren)
        mine = D["resets"].copy()
        mine["cost_bps"] = r4(mine["cost_bps"])
        mine["seq"] = mine.groupby(["book", "cost_bps"]).cumcount()
        mine = mine.rename(columns={f"value_before_{nm}": f"vb_{nm}" for nm in INDICES} | {f"value_after_{nm}": f"va_{nm}" for nm in INDICES})
        cols = ["idx", "V", "traded", "cost"] + [f"vb_{nm}" for nm in INDICES] + [f"va_{nm}" for nm in INDICES]
        keys = ["book", "cost_bps", "seq"]
        compare_frames(c, mine[keys + ["date"] + cols], qr[keys + ["date"] + cols], keys, num_cols=cols, str_cols=["date"])
        c.notes.append(f"{len(mine)} quarterly resets of the verifier's strategy (all books and costs)")
        # identities on the file's own numbers
        for r in qr.itertuples(index=False):
            d = r._asdict()
            bps = float(d["cost_bps"]); Vv = float(d["V"]); cost = float(d["cost"]); trd = float(d["traded"])
            w = WEIGHTS[d["book"]]
            vb = np.array([float(d[f"vb_{nm}"]) for nm in INDICES]); va = np.array([float(d[f"va_{nm}"]) for nm in INDICES])
            c.compared += 5
            tol = TOL_ID * max(1.0, Vv)
            if abs(cost - trd * bps / 2.0 / 10000.0) > tol: c.failed += 1; c.fail(f"reset cost != traded x bps/2/1e4: {d}")
            if abs(vb.sum() - Vv) > tol: c.failed += 1; c.fail(f"reset: values before do not sum to V: {d}")
            if abs(va.sum() - (Vv - cost)) > tol: c.failed += 1; c.fail(f"reset: values after != V - cost: {d}")
            if np.abs(va - np.array(w) * (Vv - cost)).max() > tol: c.failed += 1; c.fail(f"reset: post-reset values != weights x (V - cost): {d}")
            if abs(trd - np.abs(np.array(w) * Vv - vb).sum()) > 1e-9 * max(1.0, trd): c.failed += 1; c.fail(f"reset: traded != sum |target - held|: {d}")
            if bps == 0.0:
                c.compared += 1
                if abs(va.sum() - Vv) > tol: c.failed += 1; c.fail(f"NAV not continuous through a 0-cost reset: {d}")
    run_check(C, "C-reset", c_reset)

    # ------------------------------------------------------------------ the gold signal and the real series
    def c_gold(c):
        wk = D["P"]["gweekly"]
        gd, gsg = P["gmaster"]
        mm = pd.DataFrame({"review": pd.to_datetime(gd), "msign": gsg})
        j = mm.merge(wk[["review", "SIGN", "signal"]], on="review", how="inner")
        c.compared += len(j)
        bad = (j["msign"] != j["SIGN"]) | ((j["signal"] == 1.0) != (j["SIGN"] == "BUY"))
        c.failed += int(bad.sum())
        if bad.any(): c.fail("Master_MAUc1 SIGN / weekly csv SIGN / signal disagree: %s" % j[bad].iloc[0].to_dict())
        c.notes.append(f"Master_MAUc1 rows {len(mm)}, weekly csv rows {len(wk)}, shared dates {len(j)}")
        wd = wk["review"].values
        for r in D["dec_all"]["full"].itertuples():
            pos = int(np.searchsorted(wd, np.datetime64(pd.Timestamp(r.decision_date)), side="right") - 1)
            c.compared += 1
            if pos < 0 or int(wk["signal"].iloc[pos]) != r.g or wk["SIGN"].iloc[pos] != r.sign_MAUc1 or str(wk["review"].iloc[pos].date()) != r.label_MAUc1:
                c.failed += 1; c.fail(f"g at j={r.j} {r.decision_date}: Master {r.sign_MAUc1} (row {r.label_MAUc1}) vs weekly csv row {wk['review'].iloc[pos].date() if pos >= 0 else None}")
        gs_ev = E.get("gold_signal.csv", c)
        if gs_ev is not None:
            gs_ev = gs_ev[gs_ev["book"].isin(BK)]
            mine = dec_m[["book", "j", "decision_date", "label_MAUc1", "sign_MAUc1", "g", "gw"]]
            if need_cols(c, gs_ev, ["book", "j", "decision_date", "label_MAUc1", "sign_MAUc1", "g", "gw"], "gold_signal.csv"):
                compare_frames(c, mine[mine["book"].isin(BK)], gs_ev[["book", "j", "decision_date", "label_MAUc1", "sign_MAUc1", "g", "gw"]], ["book", "j"],
                               num_cols=["g", "gw"], str_cols=["decision_date", "label_MAUc1", "sign_MAUc1"])
    run_check(C, "C-gold", c_gold)

    real_npz = E.get("real_states.npz")

    def c_real_states(c):
        if real_npz is None:
            E.get("real_states.npz", c); return
        for p in BK:
            for w in WINDOWS:
                for dom, k in (("io", "states"), ("gold", "gstates")):
                    key = f"{p}|{w}|{dom}"
                    c.compared += 1
                    if key not in real_npz.files:
                        c.missing += 1; c.fail(f"MISSING: real_states.npz key {key}"); continue
                    if not np.array_equal(real_npz[key].astype(np.uint8), RULE[w][k]):
                        c.failed += 1; c.fail(f"real_states.npz {key} differs from the verifier's series")
    run_check(C, "C-real-states", c_real_states)

    # ------------------------------------------------------------------ V4 identities
    def c_v4(c):
        """(a) one-index books at weight 1, 0 cost, no resets = close / first close (1e-12); (b) hold-the-proxy at 0 cost = a plain day-by-day loop with the
        quarterly resets; the engine's own NAVs of both against the same; (c) the signals (C-dec, C-gold); (d) D09b chained into D09; (e) rule 7 (C-sc100)."""
        for p in BK:
            b = D["books"][p]
            for k, nm in enumerate(INDICES):
                ref = P["C"][:, k] / P["C"][0, k]
                c.compared += 1
                r_ = float(np.max(np.abs(b["index0"][nm] - ref) / ref))
                c.worst_rel = max(c.worst_rel, r_)
                if r_ > TOL_ID:
                    c.failed += 1; c.fail(f"{p}: verifier's one-index book {nm} differs from close / first close by {r_:.2e}")
                if env_all is not None:
                    e = env_all[(env_all["book"] == p) & (env_all["run"] == f"index_{nm}") & (env_all["cost_bps"] == 0.0)]
                    c.compared += 1
                    if len(e) != len(ref):
                        c.missing += 1; c.fail(f"MISSING: engine one-index NAV {p} {nm} ({len(e)} rows)")
                    else:
                        r2 = float(np.max(np.abs(e["nav"].values - ref) / ref))
                        c.worst_rel = max(c.worst_rel, r2)
                        if r2 > TOL_ID:
                            c.failed += 1; c.fail(f"{p}: engine one-index NAV {nm} differs from close / first close by {r2:.2e}")
            hand = hand_hold_proxy(b["V"], b["w"])
            c.compared += 1
            r3_ = float(np.max(np.abs(b["hold0"] - hand) / hand))
            c.worst_rel = max(c.worst_rel, r3_)
            if r3_ > TOL_ID:
                c.failed += 1; c.fail(f"{p}: simulated hold-the-proxy differs from the plain loop by {r3_:.2e}")
            if env_all is not None:
                e = env_all[(env_all["book"] == p) & (env_all["run"] == "hold_proxy") & (env_all["cost_bps"] == 0.0)]
                c.compared += 1
                if len(e) != len(hand):
                    c.missing += 1; c.fail(f"MISSING: engine hold_proxy NAV {p}")
                else:
                    r4_ = float(np.max(np.abs(e["nav"].values - hand) / hand))
                    c.worst_rel = max(c.worst_rel, r4_)
                    if r4_ > TOL:
                        c.failed += 1; c.fail(f"{p}: engine hold_proxy NAV differs from the plain loop by {r4_:.2e}")
        c.notes.append("worst_rel = largest relative difference over the one-index and hold-the-proxy comparisons")
    run_check(C, "C-v4-identities", c_v4)

    def c_splice(c):
        ch = P["gold_chain"]
        b, g, m = ch["b"], ch["g"], ch["m"]
        c.compared += 4
        if b.index[-1] != PROXY_LAST or g.index[0] != GOLDBEES_START:
            c.failed += 1; c.fail(f"proxy ends {b.index[-1].date()}, GOLDBEES starts {g.index[0].date()}")
        for nm, d in (("D09b", b), ("D09", g)):
            if (d[["open", "high", "low", "close"]] <= 0).any().any() or d.isna().any().any():
                c.failed += 1; c.fail(f"{nm}: a non-positive or missing price")
        ret_splice = g["close"].iloc[0] / b["close"].iloc[-1] - 1.0
        mret = m["close"].loc[GOLDBEES_START] / m["close"].loc[PROXY_LAST] - 1.0
        c.compared += 1
        rr = abs(ret_splice - mret) / abs(mret)
        c.worst_rel = max(c.worst_rel, rr)
        if rr > 1e-9:
            c.failed += 1; c.fail(f"splice-day return {ret_splice!r} != MAUc1's own {mret!r}")
        mi = m.index[(m.index >= b.index[0]) & (m.index <= PROXY_LAST)]
        c.compared += 1
        if not mi.equals(b.index):
            c.failed += 1; c.fail(f"the proxy's dates are not MAUc1's consecutive rows ({len(b)} vs {len(mi)})")
        else:
            pr = b["close"].values[1:] / b["close"].values[:-1]
            mr = m["close"].loc[b.index].values[1:] / m["close"].loc[b.index].values[:-1]
            r_ = float(np.max(np.abs(pr - mr) / mr))
            c.compared += 1
            c.worst_rel = max(c.worst_rel, r_)
            if r_ > 1e-9:
                c.failed += 1; c.fail(f"the proxy's daily returns differ from MAUc1's by {r_:.2e}")
        c.compared += 2
        if P["no_own_gold_bar"] != NO_GOLD_BAR_EXPECTED:
            c.failed += 1; c.fail(f"sessions without a gold bar of their own: {P['no_own_gold_bar']} (expected {NO_GOLD_BAR_EXPECTED})")
        if P["no_mcx_range"] != MCX_NO_BAR_EXPECTED:
            c.failed += 1; c.fail(f"GOLDBEES sessions without an MCX range: {P['no_mcx_range']} (expected {MCX_NO_BAR_EXPECTED})")
    run_check(C, "C-v4-splice", c_splice)

    # ------------------------------------------------------------------ draws.csv / draw_states.npz
    draws = E.get("draws.csv")
    if draws is not None:
        draws = draws[draws["book"].isin(BK)].copy()
        draws["cost_bps"] = r4(draws["cost_bps"])
        draws["cash"] = draws["cash"].replace({"liquidcase": "liq"})
    states_npz = E.get("draw_states.npz")
    curves_npz = E.get("draw_curves_20.8.npz")
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
            R = RULE[window]
            if typ == "real":
                arr = (R["states"] if dom == "io" else R["gstates"])[None, :]
            else:
                arr = states_of(book, window, dom, typ)
            FEATS[key] = None if arr is None else Feat(arr, cover=R["cover"] if dom == "io" else None)
        return FEATS[key]

    def c_states(c_struct, c_len, c_gold):
        """Structure of every saved draw (T09.md section 3 step 11, V3): weeks, first and last state, spell counts, in / BUY weeks equal the real series';
        N4.9 / N4.9-g sorted lengths identical; N4.10 / N4.10-g lengths within the series' own bounds and summing to the totals."""
        if states_npz is None:
            for cc in (c_struct, c_len, c_gold):
                E.get("draw_states.npz", cc)
            return
        for p in BK:
            for window in WINDOWS:
                R = RULE[window]
                for dom, typs, RR in (("io", TYPES_IO, R["io"]), ("gold", TYPES_GOLD, R["g"])):
                    for typ in typs:
                        cs, cl = (c_struct, c_len) if dom == "io" else (c_gold, c_gold)
                        f = feat(p, window, dom, typ)
                        if f is None:
                            cs.miss(f"draw_states.npz key {p}|{window}|{dom}|{typ}")
                            continue
                        lo1, hi1 = R["bnd"][(dom, "in" if dom == "io" else "buy")]
                        lo0, hi0 = R["bnd"][(dom, "out" if dom == "io" else "sell")]
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
                                ok = (len(ins) > 0 and min(ins) >= lo1 and max(ins) <= hi1 and len(outs) > 0 and min(outs) >= lo0 and max(outs) <= hi0
                                      and sum(ins) == RR["S_in"] and sum(outs) == RR["S_out"])
                                why = f"{typ} bounds [{lo1},{hi1}]/[{lo0},{hi0}] or sums ({RR['S_in']}, {RR['S_out']}) violated"
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
            if fam not in FAMILY or w not in WINDOWS or p not in BK:
                c_csv.compared += 1; c_csv.failed += 1; c_csv.fail(f"unexpected row group {key}"); continue
            io_t, go_t = FAMILY[fam]
            fi, fg = feat(p, w, "io", io_t), feat(p, w, "gold", go_t)
            if fi is None or fg is None:
                c_csv.miss(f"draw_states.npz arrays for family {fam} of {p}|{w}"); continue
            R = RULE[w]
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
            if "family" in g_.columns and "sleeve_mode" in g_.columns:
                pass
            slt = np.zeros(len(ids), dtype=int) if mode == "fixed50" else sleeve_trade_counts(fi.arr[ii].astype(int), fg.arr[ig].astype(int))
            pairs = [("invested_weeks", fi.w1[ii], False), ("n_in_spells", fi.n1[ii], False), ("n_out_spells", fi.n0[ii], False),
                     ("in_lengths", fi.s1[ii], True), ("out_lengths", fi.s0[ii], True),
                     ("g_buy_weeks", fg.w1[ig], False), ("n_buy_spells", fg.n1[ig], False), ("n_sell_spells", fg.n0[ig], False),
                     ("g_buy_lengths", fg.s1[ig], True), ("g_sell_lengths", fg.s0[ig], True), ("sleeve_trades", slt, False)]
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
        exp = [(p, w, ca, round(cst, 4), fam, mode) for (p, w, ca, cst, fam, mode) in expected_groups(BK)]
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
        if curves_npz is not None:
            have = set(curves_npz.files)
            for p in BK:
                for fam in ("F1", "F3"):
                    for i in range(nd_draws):
                        c.compared += 1
                        if f"{p}|{fam}_{i}" not in have:
                            c.missing += 1
                            if c.first_fail is None: c.fail(f"MISSING: curve {p}|{fam}_{i}")
        else:
            E.get("draw_curves_20.8.npz", c)
    run_check(C, "C-draws-coverage", c_cover)

    # ------------------------------------------------------------------ regeneration from the seeds
    REGEN = {}

    def tabs_for(R, dom):
        RR = R["io"] if dom == "io" else R["g"]
        a, b = ("in", "out") if dom == "io" else ("buy", "sell")
        tb1 = (RR["in_spells"], RR["S_in"]) + R["bnd"][(dom, a)]
        tb0 = (RR["out_spells"], RR["S_out"]) + R["bnd"][(dom, b)]
        return tb1, tb0, {tb1: ways_table(*tb1), tb0: ways_table(*tb0)}, RR["first_state"]

    def regen(kind, window, dom, n):
        key = (kind, window, dom, n)
        if key not in REGEN:
            R = RULE[window]
            if kind == "n49":
                s, sb = (R["states"], SEEDS["n49"]) if dom == "io" else (R["gstates"], SEEDS["n49g"])
                REGEN[key] = np.array([n49_states(s, sb, i) for i in range(n)])
            else:
                tb1, tb0, tabs, fs = tabs_for(R, dom)
                sb = SEEDS["n410"] if dom == "io" else SEEDS["n410g"]
                REGEN[key] = np.array([n410_states_own(fs, tb1, tb0, sb, i, tabs) for i in range(n)])
        return REGEN[key]

    def c_regen(c, which):
        if states_npz is None:
            E.get("draw_states.npz", c); return
        for p in BK:
            for window in WINDOWS:
                for dom, typ in ((("io", "N4.9"), ("gold", "N4.9-g")) if which == "n49" else (("io", "N4.10"), ("gold", "N4.10-g"))):
                    arr = states_of(p, window, dom, typ)
                    if arr is None:
                        c.miss(f"draw_states.npz key {p}|{window}|{dom}|{typ}"); continue
                    mine_ = regen(which, window, dom, arr.shape[0])
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
    def vsel(p, w, ca):
        b = D["books"][p]
        return {("full", "lbes"): (b["V"], b["dec_idx"], "gw_t", "gw_5"), ("full", "liq"): (b["Vliq"], b["dec_idx"], "gw_t", "gw_5"),
                ("r3", "lbes"): (b["Vr3"], b["dec_idx_r3"], "gw_t_r3", "gw_5_r3")}[(w, ca)]

    def c_draw_nav(c):
        if draws is None or states_npz is None:
            E.get("draws.csv", c); E.get("draw_states.npz", c); return
        idx = draws.set_index(["book", "window", "cash", "cost_bps", "family", "sleeve_mode", "draw_id"]).sort_index()
        curve_chk = [0.0, 0]
        nsim = 0

        def compare_row(key, r):
            if key not in idx.index:
                c.miss(f"draws.csv row {key}"); return
            row = idx.loc[key]
            if isinstance(row, pd.DataFrame):
                row = row.iloc[0]
            st = stats_of(r["nav"])
            for col in STAT_COLS_ALL:
                if col not in row.index:
                    c.miss(f"draws.csv column {col}"); continue
                c.compared += 1
                dv = float(abs(st[col] - float(row[col])) / max(abs(float(row[col])), 1e-12))
                c.worst_rel = max(c.worst_rel, dv)
                if dv > TOL:
                    c.failed += 1; c.fail(f"{key} {col}: verifier {st[col]!r} vs draws.csv {row[col]!r}")

        for (p, w, ca, cst, fam, mode) in expected_groups(BK):
            io_t, go_t = FAMILY[fam]
            fi, fg = feat(p, w, "io", io_t), feat(p, w, "gold", go_t)
            if fi is None or fg is None:
                c.miss(f"states for family {fam} of {p}|{w}"); continue
            navail = min(fi.n if io_t != "real" else 10 ** 9, fg.n if go_t != "real" else 10 ** 9)
            V, dix, gwt, gw5 = vsel(p, w, ca)
            for i in [x for x in sample_ids(p, (w, ca, fam, mode, cst), pool=nd_draws) if x < navail]:
                s_i = (fi.arr[i] if io_t != "real" else fi.arr[0]).astype(int)
                g_i = (fg.arr[i] if go_t != "real" else fg.arr[0]).astype(int)
                r = SIMS.run(V, s_i, cst, dix, gws_of(g_i, mode), (p, w, ca))
                nsim += 1
                compare_row((p, w, ca, round(cst, 4), fam, mode, i), r)
                if (w, ca, mode) == ("full", "lbes", "timed") and fam in ("F1", "F3") and abs(cst - HEADLINE_COST) < 1e-9:
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
        for window in WINDOWS:
            R = RULE[window]
            for dom, RR, names in (("io", R["io"], ("in", "out")), ("gold", R["g"], ("buy", "sell"))):
                for state, k, S in ((names[0], RR["in_spells"], RR["S_in"]), (names[1], RR["out_spells"], RR["S_out"])):
                    lo, hi = R["bnd"][(dom, state)]
                    rows.append(dict(window=window, series=dom, state=state, k=k, S=S, lo=lo, hi=hi, n_ways=n_ways(k, S, lo, hi)))
        return rows
    D["count_rows"] = table_rows()
    FULL_COUNTS = {("io", "in"): 10354725991095786, ("io", "out"): 480915680540493952, ("gold", "buy"): 76727187438249573981, ("gold", "sell"): 693114838376918505}

    def c_count(c):
        ct = E.get("count_table.json", c)
        mine = D["count_rows"]
        if ct is not None:
            tabs = ct.get("tables", {})
            for p in BK:
                for r in mine:
                    key = f"{p}|{r['window']}|{r['series']}|{r['state']}"
                    c.compared += 1
                    l = tabs.get(key)
                    if l is None:
                        c.miss(f"count_table.json table {key}"); continue
                    try:
                        kk = l["k"] if "k" in l else l["spells_k"]
                        SS = l["S"] if "S" in l else l["weeks_S"]
                        ok = (int(str(l["n_ways"])) == r["n_ways"] and int(kk) == r["k"] and int(SS) == r["S"] and int(l["lo"]) == r["lo"] and int(l["hi"]) == r["hi"])
                        if "n_ways_inclusion_exclusion" in l:
                            ok = ok and int(str(l["n_ways_inclusion_exclusion"])) == r["n_ways"]
                        if "dp_equals_inclusion_exclusion" in l:
                            ok = ok and bool(l["dp_equals_inclusion_exclusion"]) is True
                        if "rule_lengths_within_bounds" in l:
                            ok = ok and bool(l["rule_lengths_within_bounds"]) is True
                    except Exception:
                        ok = False
                    if not ok:
                        c.failed += 1; c.fail(f"{key}: count table {l} vs verifier k={r['k']} S={r['S']} lo={r['lo']} hi={r['hi']} n_ways={r['n_ways']}")
            b = ct.get("bounds")
            for window in WINDOWS:
                for dom, names in (("io", ("in", "out")), ("gold", ("buy", "sell"))):
                    for state in names:
                        c.compared += 1
                        try:
                            blk = b[window]
                            if dom in blk:
                                got = [int(x) for x in blk[dom][state]]
                            else:                  # reading: a window block without the io / gold level ("r3": {"in": .., "buy": ..}) is accepted and noted
                                got = [int(x) for x in blk[state]]
                                if f"flat bounds block for {window}" not in c.notes:
                                    c.notes.append(f"flat bounds block for {window} (the contract nests it under io / gold)")
                        except Exception:
                            c.miss(f"count_table.json bounds {window}/{dom}/{state}"); continue
                        if got != list(RULE[window]["bnd"][(dom, state)]):
                            c.failed += 1; c.fail(f"count_table.json bounds {window}/{dom}/{state} = {got} vs verifier {RULE[window]['bnd'][(dom, state)]}")
        for r in mine:
            c.compared += 1
            dp = ways_table(r["k"], r["S"], r["lo"], r["hi"])[r["k"]][r["S"]]
            if dp != r["n_ways"]:
                c.failed += 1; c.fail(f"{r['window']}|{r['series']}|{r['state']}: inclusion-exclusion {r['n_ways']} vs DP {dp}")
            if r["window"] == "full":
                c.compared += 1
                if r["n_ways"] != FULL_COUNTS[(r["series"], r["state"])]:
                    c.failed += 1; c.fail(f"full window {r['series']} {r['state']}: {r['n_ways']} vs the count frozen in T09.md {FULL_COUNTS[(r['series'], r['state'])]}")
        c.compared += 1
        if n_ways(3, 12, 2, 6) != 19:
            c.failed += 1; c.fail(f"inclusion-exclusion gives {n_ways(3, 12, 2, 6)} for k=3,S=12,[2,6]; T09.md says 19")
        if STEP1_JSON.exists():
            s1 = json.load(open(STEP1_JSON))
            for window in WINDOWS:
                for tkey, dom, mp in (("io_tables", "io", {"in": "in", "out": "out"}), ("gold_tables", "gold", {"in": "buy", "out": "sell"})):
                    for st1, st in mp.items():
                        f = s1[window][tkey][st1]
                        m = [r for r in mine if r["window"] == window and r["series"] == dom and r["state"] == st][0]
                        c.compared += 1
                        if str(m["n_ways"]) != str(f["n_ways"]) or m["k"] != f["k"] or m["S"] != f["S"] or m["hi"] != f["hi"] or m["lo"] != f["lo"]:
                            c.failed += 1; c.fail(f"step_1_spell_counts.json {window} {tkey} {st1} {f} differs from the verifier's count {m}")
        else:
            c.notes.append("logs/step_1_spell_counts.json not found; pre-registered counts not compared")
    run_check(C, "C-count", c_count)

    def c_spells_step1(c):
        """The real series' structure, derived here from the raw files, equals the pre-registered Step 1 counts (T09.md section 2)."""
        if not STEP1_JSON.exists():
            c.notes.append("logs/step_1_spell_counts.json not found"); return
        s1 = json.load(open(STEP1_JSON))
        for window in WINDOWS:
            R = RULE[window]
            io, G = R["io"], R["g"]
            e = s1[window]
            s, g = R["states"], R["gstates"]
            flips = [j for j in range(1, len(g)) if g[j] != g[j - 1]]
            both_out = [j for j in flips if s[j] == 0 and s[j - 1] == 0 and j <= len(g) - 2]
            n_exit = sum(1 for j in flips if s[j - 1] == 1 and s[j] == 0)
            n_in = sum(1 for j in flips if s[j] == 1)
            gr = runs_of(g)
            pos, n_with = 0, 0
            for v_, l_ in gr:
                if (s[pos:pos + l_] == 0).any():
                    n_with += 1
                pos += l_
            dts = R["dec"]["decision_date"].values
            a = R["a"]
            pairs = [("start", R["start"]), ("end", R["end"]), ("sessions", R["sessions"]), ("weeks", io["weeks"]), ("first_state", io["first_state"]),
                     ("last_state", io["last_state"]), ("in_spells", io["in_spells"]), ("out_spells", io["out_spells"]), ("S_in", io["S_in"]), ("S_out", io["S_out"]),
                     ("in_lengths", io["in_lengths"]), ("out_lengths", io["out_lengths"]), ("weeks_in", io["S_in"]), ("weeks_out", io["S_out"]),
                     ("round_trips", min(io["in_spells"], io["out_spells"])), ("g_first_state", G["first_state"]), ("g_last_state", G["last_state"]),
                     ("g_buy_spells", G["in_spells"]), ("g_sell_spells", G["out_spells"]), ("g_S_buy", G["S_in"]), ("g_S_sell", G["S_out"]),
                     ("g_buy_lengths", G["in_lengths"]), ("g_sell_lengths", G["out_lengths"]), ("g_shortest", min(G["shortest_in"], G["shortest_out"])),
                     ("g_flips", len(flips)), ("g_flips_while_out_both_sides", len(both_out)), ("g_flips_on_an_exit_decision", n_exit), ("g_flips_while_in", n_in),
                     ("g_flip_dates_while_out", [str(dts[j]) for j in both_out]), ("g_spells_with_an_out_week", n_with),
                     ("g_weeks_buy_while_out", int(((g == 1) & (s == 0)).sum())), ("g_weeks_sell_while_out", int(((g == 0) & (s == 0)).sum())),
                     ("quarter_start_sessions_in_window", sum(1 for i in P["resets"] if i > a))]
            for k_, mv in pairs:
                if k_ not in e:
                    continue
                c.compared += 1
                if mv != e[k_]:
                    c.failed += 1; c.fail(f"{window} {k_}: verifier {mv!r} vs step_1_spell_counts.json {e[k_]!r}")
            c.compared += 1
            if R["sleeve_trades"] != e["g_flips_while_out_both_sides"]:
                c.failed += 1; c.fail(f"{window}: sleeve trades {R['sleeve_trades']} vs step 1 {e['g_flips_while_out_both_sides']}")
        c.compared += 1
        if s1["window"] != [str(cal[0].date()), str(cal[-1].date())]:
            c.failed += 1; c.fail(f"window {s1['window']} vs {cal[0].date()} -> {cal[-1].date()}")
        for nm, key in (("n49", "N4.9"), ("n410", "N4.10"), ("n49g", "N4.9-g"), ("n410g", "N4.10-g")):
            c.compared += 1
            if [str(x) for x in SEEDS[nm]] + ["draw_id"] != [str(x) for x in s1["seeds"][key]]:
                c.failed += 1; c.fail(f"seed {key}: {SEEDS[nm]} vs step 1 {s1['seeds'][key]}")
    run_check(C, "C-spells-step1", c_spells_step1)

    def c_support(c):
        """The rule's own lengths lie within the bounds (so every N4.9 / N4.9-g draw is an allowed N4.10 / N4.10-g configuration), the tables are
        feasible (lo*k <= S <= hi*k), the bounds are the spec's, and the reportability gate holds."""
        exp_full = {("io", "in"): (1, 32), ("io", "out"): (2, 35), ("gold", "buy"): (2, 36), ("gold", "sell"): (2, 27)}
        for key, want in exp_full.items():
            c.compared += 1
            if RULE["full"]["bnd"][key] != want:
                c.failed += 1; c.fail(f"derived bound {key} = {RULE['full']['bnd'][key]} but the spec fixes {want}")
        for window in WINDOWS:
            R = RULE[window]
            for dom, RR, names in (("io", R["io"], ("in", "out")), ("gold", R["g"], ("buy", "sell"))):
                for state, lens in ((names[0], RR["in_lengths"]), (names[1], RR["out_lengths"])):
                    lo, hi = R["bnd"][(dom, state)]
                    c.compared += 1
                    if not (all(lo <= l <= hi for l in lens) and lo * len(lens) <= sum(lens) <= hi * len(lens)):
                        c.failed += 1; c.fail(f"{window}|{dom}|{state}: the real lengths {lens} are outside [{lo}, {hi}] or the totals cannot be split within the bounds")
            c.compared += 1
            if min(R["io"]["in_spells"], R["io"]["out_spells"]) < 4:
                c.failed += 1; c.fail(f"{window}: fewer than 4 round trips of the in-or-out switch")
            gr = runs_of(R["gstates"])
            pos, n_with = 0, 0
            for v_, l_ in gr:
                if (R["states"][pos:pos + l_] == 0).any():
                    n_with += 1
                pos += l_
            c.compared += 1
            if n_with < 4:
                c.failed += 1; c.fail(f"{window}: fewer than 4 gold spells containing an OUT week")
    run_check(C, "C-support", c_support)

    def c_sampler(c):
        """V5: (a) the verifier's own sampler passes the chi-square on the 19-tuple case; (b) the DP equals the formula (C-count); (c) over the saved
        N4.10 / N4.10-g draws the mean length at every position is within 4 standard errors of S / k."""
        st = sampler_selftest()
        c.compared += 2
        if not st["all_seen"] or st["n_ways_formula"] != 19 or st["n_ways_dp"] != 19:
            c.failed += 1; c.fail(f"sampler self-test enumeration wrong: {st}")
        if st["p"] is not None and st["p"] <= 0.001:
            c.failed += 1; c.fail(f"the verifier's own sampler fails the chi-square (p = {st['p']:.4g})")
        c.notes.append(f"own-sampler chi-square on 19 tuples: chi2 = {st['chi2']:.2f} (df {st['df']}), p = {st['p']}; samples {st['n_samples']}")
        stj = E.get("sampler_selftest.json")
        if stj is not None:
            ps = []

            def walk(o, k=""):
                if isinstance(o, dict):
                    for kk, vv in o.items():
                        walk(vv, kk)
                elif isinstance(o, (int, float)) and not isinstance(o, bool) and ("p" == k or "p_value" in k or k.endswith("_p") or "pvalue" in k or k.startswith("chi") and k.endswith("p")):
                    ps.append((k, float(o)))
            walk(stj)
            for k, v in ps:
                c.compared += 1
                if v <= 0.001:
                    c.failed += 1; c.fail(f"sampler_selftest.json {k} = {v} <= 0.001")
            c.notes.append(f"sampler_selftest.json: {len(ps)} p-value(s) read")
            c.compared += 1
            if stj.get("pass") is False:
                c.failed += 1; c.fail("sampler_selftest.json says pass = false")
        if states_npz is None:
            E.get("draw_states.npz", c); return
        worst = 0.0
        for p in BK:
            for window in WINDOWS:
                R = RULE[window]
                for dom, typ, RR in (("io", "N4.10", R["io"]), ("gold", "N4.10-g", R["g"])):
                    f = feat(p, window, dom, typ)
                    if f is None:
                        c.miss(f"states {p}|{window}|{dom}|{typ}"); continue
                    names = ("in", "out") if dom == "io" else ("buy", "sell")
                    for (nm, k, S, lens_all), stn in zip((("ones", RR["in_spells"], RR["S_in"], f.ones), ("zeros", RR["out_spells"], RR["S_out"], f.zeros)), names):
                        if any(len(x) != k for x in lens_all):
                            c.failed += 1; c.fail(f"{p}|{window}|{dom}|{typ}|{nm}: draws do not all have {k} spells"); continue
                        lo, hi = R["bnd"][(dom, stn)]
                        mu, var = first_part_moments(k, S, lo, hi)
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
        cand = [E.dir / "analysis.log", E.dir.parent / "analysis.log", E.dir.parent.parent / "analysis.log"]
        logp = next((x for x in cand if x.exists()), None)
        if logp is None:
            c.notes.append("analysis.log not found beside the evidence (written by Step 4/6); nothing compared")
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
                    if not any(f"{v:.{nd}f}" in nums for nd in (1, 2)):
                        c.failed += 1; c.fail(f"{r['book']} {r['family']} {r['mode']} {stat} percentile {v:.2f} not printed in {logp.name}")
        c.notes.append(f"read {logp}")
    run_check(C, "C-percentile-log", c_percentile_log, gate=False)

    # ------------------------------------------------------------------ the engine's own gate files (read, not trusted: no gate may be False)
    def c_engine_files(c):
        reg = E.get("regression.json", c)
        if reg is not None:
            c.compared += 1
            if reg.get("pass") is False:
                c.failed += 1; c.fail("regression.json says pass = false")
        A = E.get("audit.json", c)
        if A is not None:
            gates = A.get("gates")
            if isinstance(gates, dict):
                for k, v in gates.items():
                    c.compared += 1
                    if v is False:
                        c.failed += 1; c.fail(f"audit.json gate {k} = false")
            else:
                c.notes.append("audit.json has no 'gates' dict")
    run_check(C, "C-engine-files", c_engine_files)

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
    """Return a state row whose first spell of the value 1 is hi+1 weeks long, the extra weeks taken from the next 1-spells (totals unchanged)."""
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


def corrupt_copy(ev, dst, D, books):
    """Eight corruptions of a copy: 5 decisions flipped; a NAV column x 1.001; one N4.10 in-or-out draw out of bounds; one N4.10-g gold draw out of
    bounds; 3 gold-signal weeks flipped; one sleeve rebalance removed; one quarterly reset removed; a Smallcap 100 usable_from marker lowered in
    inputs.csv; and (extra) one F3 draw's end NAV x 1.001."""
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True)
    info = {}
    p0 = books[0]
    R = D["rule"]["full"]
    dpath = ev.path("decisions.csv")
    if dpath is not None:
        dec = pd.read_csv(dpath)
        rows = dec.index[dec["book"] == p0][np.linspace(10, int((dec["book"] == p0).sum()) - 10, 5).astype(int)]
        dec.loc[rows, "state"] = 1 - dec.loc[rows, "state"]
        dec.to_csv(dst / "decisions.csv", index=False)
        info["flipped_decision_rows"] = [int(x) for x in rows]
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
        key = f"{p0}|full|io|N4.10"
        if key in data and data[key].shape[0] > 5:
            arr = data[key]
            new_row, ins, outs = _widen_first_spell(arr[5], int(arr[5][0]), R["bnd"][("io", "in")][1])
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
            new_row, buys, sells = _widen_first_spell(arr[7], int(arr[7][0]), R["bnd"][("gold", "buy")][1])
            if len(new_row) == arr.shape[1]:
                arr[7] = new_row
                data[key] = arr
                info["corrupted_n410g_draw"] = dict(key=key, draw_id=7, buy_lengths=buys, sell_lengths=sells)
                if w is not None:
                    msk = (w["book"] == p0) & (w["window"] == "full") & (w["gold_null"] == "N4.10-g") & (w["draw_id"] == "7")
                    w.loc[msk, "g_buy_lengths"] = "|".join(map(str, buys))
        np.savez(dst / "draw_states.npz", **data)
    if w is not None:
        msk = (w["book"] == p0) & (w["window"] == "full") & (w["cash"] == "lbes") & (w["family"] == "F3") & (w["sleeve_mode"] == "timed") \
              & (w["draw_id"] == "3") & (w["cost_bps"].astype(float) == HEADLINE_COST)
        if msk.any():
            w.loc[msk, "end_nav"] = (w.loc[msk, "end_nav"].astype(float) * 1.001).astype(str)
            info["scaled_draw_end_nav"] = f"{p0} F3 draw 3, 20.8 bps, end_nav x 1.001"
        w.to_csv(dst / "draws.csv", index=False)
    gpath = ev.path("gold_signal.csv")
    if gpath is not None:
        gs = pd.read_csv(gpath)
        sel = gs.index[gs["book"] == p0]
        rows = sel[[40, 150, 300]]
        gs.loc[rows, "g"] = 1 - gs.loc[rows, "g"]
        gs.loc[rows, "gw"] = np.where(gs.loc[rows, "g"] == 1, GW_BUY, GW_SELL)
        gs.loc[rows, "sign_MAUc1"] = np.where(gs.loc[rows, "g"] == 1, "BUY", "SELL")
        gs.to_csv(dst / "gold_signal.csv", index=False)
        info["flipped_gold_weeks"] = [int(x) for x in gs.loc[rows, "j"]]
    spp = ev.path("sleeve_trades.csv")
    if spp is not None:
        st = pd.read_csv(spp)
        cand = st.index[(st["kind"] == "sleeve_rebalance") & (st["book"] == p0) & (st["cost_bps"].astype(float) == HEADLINE_COST)]
        if len(cand):
            st = st.drop(index=cand[0])
            st.to_csv(dst / "sleeve_trades.csv", index=False)
            info["removed_sleeve_trade"] = f"{p0}, 20.8 bps, first sleeve_rebalance"
    qpath = ev.path("quarterly_resets.csv")
    if qpath is not None:
        qr = pd.read_csv(qpath)
        cand = qr.index[(qr["book"] == p0) & (qr["cost_bps"].astype(float) == HEADLINE_COST)]
        if len(cand) > 3:
            qr = qr.drop(index=cand[3])
            qr.to_csv(dst / "quarterly_resets.csv", index=False)
            info["removed_quarterly_reset"] = f"{p0}, 20.8 bps, 4th reset"
    ipath = ev.path("inputs.csv")
    if ipath is not None:
        inp = pd.read_csv(ipath)
        msk = inp["file"].astype(str).str.replace("\\", "/", regex=False).str.contains("SC100_daily_ohlcv|Master_SC100")
        if msk.any() and "usable_from" in inp.columns:
            inp["usable_from"] = inp["usable_from"].astype(object)
            inp.loc[msk, "usable_from"] = "2004-01-01"
            inp.to_csv(dst / "inputs.csv", index=False)
            info["lowered_usable_from"] = "Smallcap 100 rows of inputs.csv set to 2004-01-01"
    return info


EVIDENCE_FILES = ["inputs.csv", "decisions.csv", "gold_signal.csv", "stats.csv", "draws.csv", "draw_states.npz", "real_states.npz", "draw_curves_20.8.npz",
                  "trades.csv", "sleeve_trades.csv", "quarterly_resets.csv", "proxy_units.csv", "positions.csv", "daily_nav.csv", "count_table.json",
                  "sampler_selftest.json", "regression.json", "audit.json"]
SELFTEST_WANTS = [("flipped_decision_rows", "C-dec", "decisions_flipped"), ("scaled_nav", "C-nav0", "nav_scaled"),
                  ("corrupted_n410_draw", "C-states-lengths", "n410_lengths_out_of_bounds"),
                  ("corrupted_n410g_draw", "C-gold-states", "n410g_lengths_out_of_bounds"), ("flipped_gold_weeks", "C-gold", "gold_weeks_flipped"),
                  ("removed_sleeve_trade", "C-sleeve", "sleeve_trade_removed"), ("removed_quarterly_reset", "C-reset", "quarterly_reset_removed"),
                  ("lowered_usable_from", "C-data", "sc100_usable_from_lowered"), ("scaled_draw_end_nav", "C-draw-nav", "draw_nav_scaled")]


def headline_table(D, books):
    """Print the six criteria of T09.md section 2 from the verifier's own percentiles (20.8 bps, LBES, full window), plus the companion nulls."""
    pc = {(r["book"], r["window"], r["cash"], round(r["cost_bps"], 4), r["family"], r["mode"]): r for r in D["percentiles"]}
    spec = [("A1", "F1", "fixed50", "cagr"), ("A2", "F1", "fixed50", "max_dd"), ("C1", "F1", "timed", "cagr"), ("C2", "F1", "timed", "max_dd"),
            ("C3", "F3", "timed", "cagr"), ("C4", "F3", "timed", "max_dd")]
    comp = {"F1": "F2", "F3": "F4"}
    print("\n=== recomputed percentiles (20.8 bps, LBES, full window; pass mark 90; the deciding null, then its companion) ===")
    out = {}
    for name, fam, mode, stat in spec:
        vals, cvals = [], []
        for p in books:
            r = pc.get((p, "full", "lbes", HEADLINE_COST, fam, mode))
            r2 = pc.get((p, "full", "lbes", HEADLINE_COST, comp[fam], mode))
            if r is None:
                continue
            vals.append(r[f"{stat}_pctile"]); cvals.append(None if r2 is None else r2[f"{stat}_pctile"])
        out[name] = dict(percentiles=vals, companion=cvals, passes=int(sum(v >= 90 for v in vals)), books=len(vals))
        print(f"{name} ({fam} {mode} {stat}): " + ", ".join(f"{v:.1f}" for v in vals) + f"   [{out[name]['passes']} of {len(vals)} >= 90]   companion: "
              + ", ".join("-" if v is None else f"{v:.1f}" for v in cvals))
    return out


def main():
    global N_DRAWS
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="headline", help="evidence run name under tests/T09/evidence/ (headline, smoke)")
    ap.add_argument("--evidence", default=None, help="evidence directory (overrides --run)")
    ap.add_argument("--no-selftest", action="store_true", help="skip the in-process corrupted-copy test")
    ap.add_argument("--out", default=None)
    ap.add_argument("--draws", type=int, default=None, help="draws per row group the evidence must hold (2000 for headline, 20 for smoke)")
    ap.add_argument("--books", default=None, help="comma-separated books (default: all four; for a smoke run, those found in the evidence)")
    ap.add_argument("--scratch", default=None, help="directory for the corrupted copy (default: a fresh temporary directory)")
    args = ap.parse_args()
    evdir = Path(args.evidence) if args.evidence else AA / "tests" / "T09" / "evidence" / args.run
    smoke = (args.run == "smoke") and not args.evidence
    N_DRAWS = int(args.draws) if args.draws else (20 if smoke else 2000)
    if args.books:
        books = [b.strip() for b in args.books.split(",")]
    elif smoke or args.evidence:
        dp = evdir / "decisions.csv"
        books = [b for b in BOOKS if dp.exists() and b in set(pd.read_csv(dp, usecols=["book"])["book"])] or list(BOOKS)
    else:
        books = list(BOOKS)
    out = Path(args.out) if args.out else evdir / "verify_t09.json"
    t = time.time()
    D = derive(books)
    print(f"[{time.time()-t:6.1f}s] derivation complete (books {books}, draws per group {N_DRAWS})", flush=True)
    E = Evidence(evdir)
    C = compare_all(D, E, books)
    print(f"[{time.time()-t:6.1f}s] comparison complete", flush=True)
    for nm in EVIDENCE_FILES:                       # an expected file that no check touched is still reported as missing
        if E.path(nm) is None and nm not in E.missing_files:
            E.missing_files.append(nm)
    if E.missing_files:
        print("\nMISSING EVIDENCE FILES: " + ", ".join(sorted(set(E.missing_files))))
    print_table(C, f"verifier vs evidence in {evdir}")
    gate_compared, gate_fail = summarise(C)
    extra_missing = sorted(set(E.missing_files))
    crit = headline_table(D, books) if D["percentiles"] else {}

    pct_real, count_real = D["percentiles"], D["count_rows"]
    selftest = None
    if not args.no_selftest:
        scratch = Path(args.scratch) if args.scratch else Path(tempfile.mkdtemp(prefix="verify_t09_"))
        cdir = scratch / "corrupt_evidence_t09"
        info = corrupt_copy(E, cdir, D, books)
        Ec = Evidence(cdir, fallback=evdir)
        Cc = compare_all(D, Ec, books)
        print_table(Cc, f"SELF-TEST: corrupted copy in {cdir} ({info})")
        cc, cf = summarise(Cc)
        by = {k: (v.failed + v.missing) for k, v in Cc.items()}
        detected_by, applied = {}, {}
        for ikey, chk, label in SELFTEST_WANTS:
            applied[label] = ikey in info
            detected_by[label] = by.get(chk, 0) > 0
        detected = cf > 0 and all(applied.values()) and all(detected_by.values())
        selftest = dict(dir=str(cdir), corruptions=info, applied=applied, gate_compared=cc, gate_failures=cf, detected=bool(detected),
                        detected_by=detected_by, checks={k: v.to_dict() for k, v in Cc.items()})
        print(f"corrupted copy detected: {detected} (failures {cf}; applied {applied}; detected by {detected_by})")
        shutil.rmtree(cdir, ignore_errors=True)

    D["percentiles"], D["count_rows"] = pct_real, count_real
    ok_real = gate_compared > 0 and gate_fail == 0 and not extra_missing
    ok = ok_real and (selftest is None or selftest["detected"])
    rep = dict(verifier="analysis/verify_t09.py", evidence=str(evdir), books=books, draws_expected=N_DRAWS, end=str(END.date()),
               gate_compared=int(gate_compared), gate_failures_and_missing=int(gate_fail), n_checks=len(C), n_gate_checks=sum(1 for c in C.values() if c.gate),
               missing_evidence_files=extra_missing, checks={k: v.to_dict() for k, v in C.items()},
               meta=D["meta"], rule={w: {k: v for k, v in D["rule"][w].items() if k in ("io", "g", "sessions", "start", "end", "sleeve_trades")} for w in ("full", "r3")},
               count_rows=[{**r, "n_ways": str(r["n_ways"])} for r in D["count_rows"]], percentiles=D["percentiles"], criteria=crit,
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
