"""T15 independent verifier (Step 3, gate V1 of tests/T15/T15.md section 2.6).

Re-derives, for both windows (W1 = 2014-09-01 -> 2019-01-02, W2 = 2019-01-02 -> 2026-10-30; T14's inputs plus the daily index prices D25 / D25c) and all
four books, from the RAW approved files only (plain numpy / pandas, its own loaders, its own cost, basket, regime, B and counting code):

  * the weekly decisions, the regime of each (IN / OUT-BUY / OUT-SELL), B (the indices whose own SIGN is BUY) and k = |B|, and the targets of the eight
    rules (50-orig 50-half 50-liq 50-idx 80-orig 80-half 80-liq 80-idx), for the full window and R3's window; decisions.csv, decisions_r3.csv, regimes.csv;
  * the NAV of every rule at 0 / 20.8 / 50 bps, hold_parent, hold_<index>, the constant mix at each rule's own average shares, R2 (LIQUIDCASE cash),
    R3, R4 (-idx holding cash only in spell n) and R5 (index prices times (1 - 0.005/252)^i); every statistic of stats.csv and robustness.csv; every trade of
    trades.csv (index fills at each index's own OHLC4, index_set_change, the D1 partial basket trade of -half); positions.csv; the regime ledger;
  * the index marking (units x the index close, the last close carried on a session with no bar), V2 (point in time), V3 (the Master `Index` column
    against the daily index close), V4 (regression against T14's stored NAVs and trades, -idx priced as cash, -idx = -liq before the first index trade,
    signals, one-instrument identity, G0 / the 2019 seam), V5 (trade and cost identities), the counts of logs/step_1_spell_counts.json, and the engine's
    own gate files.

It imports nothing from the engine or from any other module in analysis/ or data/, and it never reads the engine's source. The rules are those of
tests/T15/T15.md sections 1-3 (frozen) and tests/T15/logs/evidence_contract.md; the loaders, the six-rule simulator and the corrupted-copy machinery are
forked from verify_t14.py. Its own spec: tests/T15/logs/verifier_spec.md.

Usage (from AA/):
    python analysis/verify_t15.py                                    # headline run (both windows) + self-test on corrupted copies
    python analysis/verify_t15.py --evidence DIR --window both       # DIR holds w1/ and w2/
Exit code 0 only if rows were compared, none failed, none were missing, and (default) every deliberate corruption of a copy of the evidence was
detected by its own check. A missing evidence file is reported as MISSING (a failure).
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
from pathlib import Path

import numpy as np
import pandas as pd

AA = Path(__file__).resolve().parents[1]
BOOKS = ["SCMO_0003", "SCMO_0007", "SCMO_0010", "SCMO_0029"]
COSTS = [0.0, 20.8, 50.0]
HEADLINE_COST = 20.8
TOL = 1e-9                  # relative tolerance on NAVs and statistics (T15.md V1)
TOL_REG = 1e-12             # V4 regression against T14's stored results
TOL_ID = 1e-12              # identities (V5)
SC100_SIGNAL_FROM = pd.Timestamp("2011-11-25")   # standing rule 7 (signal rows)
SC100_PRICE_FROM = pd.Timestamp("2011-10-03")    # standing rule 7 (price rows)
G0_OVERALL_PP = 0.25
G0_YEAR_PP = 0.5
SEAM_PP = 0.5
LIVE_START = pd.Timestamp("2021-11-01")
R3_START_W1 = pd.Timestamp("2015-01-02")
END_D17 = pd.Timestamp("2019-12-31")
DRAG = 0.005 / 252.0
Q_DRAG = 1.0 - DRAG

INDICES = ["Nifty100", "MC100", "SC100"]
RULES6 = ["50-orig", "50-half", "50-liq", "80-orig", "80-half", "80-liq"]
RULES = ["50-orig", "50-half", "50-liq", "50-idx", "80-orig", "80-half", "80-liq", "80-idx"]
IDX_RULES = ["50-idx", "80-idx"]
REG_NAMES = ["IN", "OUT-BUY", "OUT-SELL"]          # codes 0, 1, 2
STAT_COLS_ALL = ["end_nav", "cagr", "max_dd", "vol", "ulcer", "days_below_10pct", "longest_underwater", "calmar", "sessions"]
APPROVED_MD = AA / "data" / "APPROVED_DATA.md"
T14_EVIDENCE = AA / "tests" / "T14" / "evidence" / "headline"
STEP1_JSON = AA / "tests" / "T15" / "logs" / "step_1_spell_counts.json"
# registry ids that T15.md section 3 lists as 'Not read' by the test
NOT_READ_IDS = {"D20", "D21", "D22", "D23", "D20b", "D23b", "D09b", "D03b", "D15"}
THROUGH_EXEMPT_IDS = {"D12", "D19", "D05"}          # through-dates earlier than W2's end by design (D12 de-spike range, D19 / D05 baskets)

F_CAL = "Historical Data/extended_2026-11-12/index_daily_pre2019/nse_trading_days.csv"
F_MASTER = {n: f"Historical Data/extended_2026-10-30/Master/Master_{n}.xlsx" for n in INDICES}
F_G = {"w1": dict(master="Historical Data/extended_2026-11-12/MAUc1_from_2003/Master_MAUc1.xlsx",
                  weekly="Historical Data/extended_2026-11-12/MAUc1_from_2003/mauc1_supertrend_weekly_extended.csv",
                  daily="Historical Data/extended_2026-11-12/MAUc1_from_2003/mauc1_daily_clean_extended.csv"),
       "w2": dict(master="Historical Data/extended_2026-11-06/MAUc1/Master_MAUc1.xlsx",
                  weekly="Historical Data/extended_2026-11-06/MAUc1/mauc1_supertrend_weekly_extended.csv",
                  daily="analysis/evidence/final_strategy/mauc1/mauc1_daily_clean.csv")}
F_IDX_D25 = {n: f"Historical Data/extended_2026-11-12/index_daily_pre2019/{n}_daily_ohlcv.csv" for n in INDICES}
F_IDX_D25C = {n: f"Historical Data/extended_2026-11-25/index_daily_2019_2026/{n}_daily_ohlcv.csv" for n in INDICES}
F_IDX = {"w1": F_IDX_D25, "w2": F_IDX_D25C}
F_D09 = "analysis/cache/why_gold_ohlc_eikon_extended_2026-11-04.parquet"
F_LBES = "Historical Data/LBES_Adjusted_Price_data_extended_2026-11-05.csv"
F_LIQ = "Historical Data/liquidEtfFinal_extended_2026-11-05.csv"
F_CORR = "data/holdings_matrix/price_corrections.csv"
# first date each index price read may use: SC100 prices are restricted to 2011-10-03 (standing rule 7); the windows start far later
IDX_READ_FROM = {"w1": pd.Timestamp("2014-08-01"), "w2": pd.Timestamp("2019-01-01")}
IDX_PRE_READ_FROM = pd.Timestamp("2018-12-01")        # W2's V3 tie: Master labels dated before 2019-01-01 read D25
N_BASKETS_W1 = 19
# the frozen text's own numbers (T15.md section 2, 'what was already known'): an oracle for the verifier's re-derivation
FROZEN = {
    "w1": dict(weeks=228, first_state=1, weeks_IN=93, weeks_OUT_BUY=81, weeks_OUT_SELL=54, OUT_SELL_spells=8, k0=21, k1=18, k2=15, index_weeks=33,
               index_spells=6, B_changes=8, trades={"50-orig": 15, "50-half": 24, "50-liq": 24, "50-idx": 32, "80-orig": 24, "80-half": 24, "80-liq": 24, "80-idx": 32},
               r3=dict(weeks_OUT_SELL=44, index_weeks=23, k0=21, k1=14, k2=9)),
    "w2": dict(weeks=410, weeks_0007=409, first_state=0, weeks_IN=201, weeks_OUT_BUY=163, weeks_OUT_SELL=46, OUT_SELL_spells=8, k0=24, k1=2, k2=20, index_weeks=22,
               index_spells=6, B_changes=6, trades={"50-orig": 18, "50-half": 27, "50-liq": 27, "50-idx": 33, "80-orig": 27, "80-half": 27, "80-liq": 27, "80-idx": 33},
               r3=dict(weeks_OUT_SELL=31, index_weeks=9, k0=22, k1=1, k2=8)),
}


# ======================================================================================
# helpers forked from verify_t14.py (approved-data parser and loaders)
# ======================================================================================
def norm_path(s):
    s = str(s).strip().replace("\\", "/")
    return s[2:] if s.startswith("./") else s


def parse_approved(md_path=APPROVED_MD):
    """data/APPROVED_DATA.md table (between the approved-table markers): status, id, file, through, sha256 prefix, note, usable-from marker."""
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
READS = {}          # relative path -> dict(first_date, gate_only) of every file this verifier read
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


def rd(rel, first_date=None, gate_only=False):
    """Register a read of an AA-relative path; refuse anything that is not an APPROVED row. A restricted row (`[usable-from: d]` in its registry
    note: standing rule 7, the Smallcap 100 files) needs the first date the read will use, and raises if that date is earlier."""
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
    prev = READS.get(key)
    READS[key] = dict(first_date=None if first_date is None else str(pd.Timestamp(first_date).date()),
                      gate_only=bool(gate_only) and (prev is None or prev["gate_only"]))
    return AA / rel


def f_published(p):
    return f"Historical Data/extended_2026-11-06/published_nav/{p}.csv"


def f_ohlc(p):
    return f"data/holdings_matrix/{p}_ohlc.csv"


def f_matrix(p):
    return f"data/holdings_matrix/{p}_holding_weight_matrix.csv"


def f_sources(p):
    return f"data/holdings_matrix/{p}_holding_weight_sources.csv"


def f_columns(p):
    return f"data/holdings_matrix/{p}_columns.csv"


def f_d05(p):
    return f"Historical Data/frozen_2026-09-25/Rebalance_history/Rebalance_history_by_scid_{p}.csv"

def despiked_goldbees_fill(g, m):
    """GOLDBEES fill (T03's de-spike, as T06/T08/T09): OHLC4 of the open, high and low clipped to MCX gold's range that day (band = (high - low) /
    close of the MCX bar + 0.5%, around the GOLDBEES close; the high and low re-bounded by the open and close); the RAW OHLC4 on a session the MCX
    file has no bar for. Also returns the MCX range itself (NaN where there is none)."""
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
    return fill, rng


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


def load_published_nav(p):
    d = pd.read_csv(rd(f_published(p)))
    d["date"] = pd.to_datetime(d["_id.date"], format="%Y/%m/%d")
    return d.set_index("date")["index"].sort_index()


def load_corrections():
    c = pd.read_csv(rd(F_CORR))
    c["ex_date"] = pd.to_datetime(c["ex_date"])
    return c


_PRICES = {}


def load_book_prices(p, corr):
    """D18 stock bars of book p as pivots on D18's own dates (open, high, low, close, src), price_corrections applied (Polyplex, SCMO_0007)."""
    if p in _PRICES:
        return _PRICES[p]
    o = pd.read_csv(rd(f_ohlc(p)), usecols=["date", "stock", "open", "high", "low", "close", "src"])
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
    src = o.pivot(index="date", columns="stock", values="src").reindex(d18)
    close_ff = W["close"].ffill()
    ohlc4 = (W["open"] + W["high"] + W["low"] + W["close"]) / 4.0
    all4 = W["open"].notna() & W["high"].notna() & W["low"].notna() & W["close"].notna()
    bar = W["close"].notna()
    fill = ohlc4.where(all4, W["close"])        # a blank open/high/low -> the close
    fill = fill.where(bar, close_ff)             # no bar that session -> the last close
    _PRICES[p] = dict(d18=d18, W=W, src=src, fill_all=fill)
    return _PRICES[p]


_BASKETS = {}


def load_baskets(p):
    """D19 weight matrix (rows = availableDate), skipped baskets dropped using D05's `skipped` flag; weights renormalised to sum 1 (T06/T08)."""
    if p in _BASKETS:
        return _BASKETS[p]
    m = pd.read_csv(rd(f_matrix(p)))
    m = m.rename(columns={m.columns[0]: "avail"})
    m["avail"] = pd.to_datetime(m["avail"])
    d5 = pd.read_csv(rd(f_d05(p)), usecols=["skipped", "availableDate"])
    d5["avail"] = pd.to_datetime(d5["availableDate"], format="%d/%m/%y %H:%M").dt.normalize()
    sk = d5.groupby("avail")["skipped"].apply(lambda s: bool(s.astype(str).str.strip().str.lower().eq("true").any()))
    skipped = set(sk[sk].index)
    s = pd.read_csv(rd(f_sources(p)))                  # the trace of where each basket's weights came from (cross-check of D05's flag)
    s["rebalance_date"] = pd.to_datetime(s["rebalance_date"])
    src_skipped = set(s.loc[s["source"] == "csv_only_skipped", "rebalance_date"])
    pd.read_csv(rd(f_columns(p)), nrows=1)             # registered (column-to-ISIN map), not otherwise used
    m = m[~m["avail"].isin(skipped)].sort_values("avail").reset_index(drop=True)
    cols = [c for c in m.columns if c != "avail"]
    Wraw = m[cols].fillna(0.0).values.astype(float)
    raw_sum = Wraw.sum(axis=1)
    _BASKETS[p] = dict(avail=m["avail"].values, cols=cols, Wraw=Wraw, raw_sum=raw_sum, W=Wraw / raw_sum[:, None],
                       skipped=sorted(skipped), src_skipped=sorted(src_skipped))
    return _BASKETS[p]

def market_arrays(cal, gold, mcx, lbes, liq):
    gfill_s, rng = despiked_goldbees_fill(gold, mcx)
    gclose = gold["close"].reindex(cal, method="ffill").values.astype(float)
    gf = gfill_s.reindex(cal).values.astype(float)
    gf = np.where(np.isnan(gf), gclose, gf)            # no own GOLDBEES bar that session: the previous close, valuation and fill
    own_bar = np.array([d in gold.index for d in cal])
    raw = np.isnan(rng.reindex(cal).values.astype(float))           # no MCX range that session: the fill is the raw OHLC4
    return dict(cal=cal, gc=gclose, gf=gf, L=asof_levels(cal, lbes, "LBES"), L2=asof_levels(cal, liq, "LIQUIDCASE"), raw=raw, own_gold_bar=own_bar)


def build_book(p, cal, MK, corr):
    """Book p on the calendar `cal` (T0 = cal[0]); stock closes and fills reindexed on the calendar (D18 dates off the calendar are ignored) and
    forward-filled (a session without a D18 bar: the last close, valuation and fill)."""
    PR = load_book_prices(p, corr)
    BS = load_baskets(p)
    n = len(cal)
    use = BS["avail"] <= np.datetime64(cal[-1])
    S_cols = [c for c, any_ in zip(BS["cols"], (BS["Wraw"][use] > 0).any(axis=0)) if any_]
    ci = [BS["cols"].index(c) for c in S_cols]
    Wm = BS["W"][:, ci]
    miss = [c for c in S_cols if c not in PR["W"]["close"].columns]
    assert not miss, (p, miss)
    Cr = PR["W"]["close"][S_cols].reindex(cal)
    nobar_closes = Cr.isna()                         # (session, stock) without an own bar
    Cff = Cr.ffill()
    fillr = PR["fill_all"][S_cols].where(PR["W"]["close"][S_cols].notna(), np.nan).reindex(cal)   # own-bar fills only
    Ffl = fillr.where(~nobar_closes, Cff)            # no bar: the last close
    Ffl = Ffl.ffill()
    C = Cff.values
    F = Ffl.values
    avail = BS["avail"]
    eff = np.searchsorted(cal.values, avail, side="left")      # first session on or after availableDate
    basket_at = {}
    for k in range(len(avail)):
        if eff[k] < n:
            basket_at[int(eff[k])] = k           # a later availableDate with the same effect session overrides
    mask_all_no_bar = nobar_closes.values.all(axis=1)
    return dict(p=p, cal=cal, n=n, S=S_cols, C=C, Cn=np.nan_to_num(C, nan=0.0), F=F, W=Wm, Wraw=BS["Wraw"][:, ci], raw_sum=BS["raw_sum"],
                avail=avail, eff=eff, basket_at_full=basket_at, d18=PR["d18"], fill_all=PR["fill_all"][S_cols], nobar=nobar_closes.values,
                sessions_all_stocks_no_bar=[str(cal[i].date()) for i in np.flatnonzero(mask_all_no_bar)],
                gc=MK["gc"], gf=MK["gf"], L=MK["L"], L2=MK["L2"], raw=MK["raw"], skipped=BS["skipped"], src_skipped=BS["src_skipped"])


def make_view(B, a, b, cash="lbes"):
    """Slice of book B on sessions [a, b); session a is the window's T0 (NAV 1.000 at its close)."""
    rel = {k - a: v for k, v in B["basket_at_full"].items() if k < b}
    keys = sorted(rel)
    k_t0 = max(k for k in keys if k <= 0)
    k0 = rel[k_t0]
    pos = np.searchsorted(B["d18"].values, B["avail"][k0], side="left")
    first_d18 = B["d18"][pos]
    return dict(p=B["p"], cal=B["cal"][a:b], n=b - a, a=a, S=B["S"], C=B["C"][a:b], Cn=B["Cn"][a:b], F=B["F"][a:b],
                gc=B["gc"][a:b], gf=B["gf"][a:b], L=(B["L"] if cash == "lbes" else B["L2"])[a:b], raw=B["raw"][a:b], W=B["W"],
                avail=B["avail"], basket_at=rel, b_idx=keys, changes=[k for k in keys if 0 < k < b - a], k0=k0,
                init_fill=B["fill_all"].loc[first_d18].values, first_d18=first_d18)

def _asof(dates, sg, d):
    pos = int(np.searchsorted(dates, np.datetime64(d), side="right") - 1)
    assert pos >= 0, f"no Master row on or before {d}"
    return sg[pos], pd.Timestamp(dates[pos])

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
    longest, cur = 0, 0
    for u in dd < 0:
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
class Evidence:
    partner_dirs = []

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
                    elif name.endswith(".md"):
                        obj = p.read_text(encoding="utf-8")
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
def touch_book_files(p):
    """Register (so that C-data checks approval, sha256 and through-date of) every file of book p, even when a loader answers from its cache."""
    for rel in (f_ohlc(p), f_matrix(p), f_sources(p), f_columns(p), f_d05(p), F_CORR):
        rd(rel)


def load_w1_calendar(t0, end):
    d = pd.read_csv(rd(F_CAL))
    dates = pd.DatetimeIndex(pd.to_datetime(d["date"])).sort_values()
    assert dates.is_unique
    return dates[(dates >= t0) & (dates <= end)]


def load_gold_files(win):
    g = pd.read_parquet(rd(F_D09))
    g = g[["date", "open", "high", "low", "close"]].copy()
    g["date"] = pd.to_datetime(g["date"]).dt.normalize()
    g = g.set_index("date").sort_index()
    m = pd.read_csv(rd(F_G[win]["daily"]))
    m = m.rename(columns={m.columns[0]: "date"})
    m["date"] = pd.to_datetime(m["date"]).dt.normalize()
    m = m.set_index("date").sort_index()
    return g, m


def load_mauc1_weekly(win):
    w = pd.read_csv(rd(F_G[win]["weekly"]))
    w["review"] = pd.to_datetime(w["review"])
    w["SIGN"] = w["SIGN"].astype(str).str.strip().str.upper()
    return w.sort_values("review").reset_index(drop=True)


def window_end_of(masters):
    """END of W2 = the last row of the approved index signals (D03): the three Masters' last dates (they must agree)."""
    ends = {nm: pd.Timestamp(dates[-1]) for nm, (dates, _) in masters.items()}
    assert len(set(ends.values())) == 1, ends
    return list(ends.values())[0]


LIQ_FROM = pd.Timestamp("2024-01-24")


def chain_liquidcase(cal, L_lbes, L_liq_asof):
    """R2 cash leg on W2 (T14.md section 3, T08's LIQ_FROM): the LBES level as-of on the sessions before 2024-01-24; from the first session on or after it the level
    is chained with the LIQUIDCASE (liquidEtfFinal) session returns, L2[t] = L2[t-1] x liq[t] / liq[t-1]."""
    i0 = int(np.searchsorted(cal.values, np.datetime64(LIQ_FROM), side="left"))
    L2 = np.array(L_lbes, dtype=float).copy()
    for i in range(max(i0, 1), len(cal)):
        L2[i] = L2[i - 1] * L_liq_asof[i] / L_liq_asof[i - 1]
    return L2
def rule_arrays(rule, s, g):
    """Target (e, gw) of `rule` at every decision from the in-or-out state s (1 = all three index SIGNs BUY) and the gold state g (1 = MAUc1 BUY), T14.md 2.1:
    50-*: gw = 0.5 outside OUT-SELL; 80-*: gw = 0.8 / 0.2 by g; -half in OUT-SELL (s = 0, g = 0): e = 0.5, gw = 1.0; -liq in OUT-SELL: e = 0, gw = 0."""
    s = np.asarray(s).astype(int)
    g = np.asarray(g).astype(int)
    base, var = rule[:2], rule[3:]
    gw = np.full(s.shape, 0.5) if base == "50" else np.where(g == 1, 0.8, 0.2)
    e = np.where(s == 1, 1.0, 0.0)
    if var != "orig":
        sell = (s == 0) & (g == 0)
        if var == "half":
            e = np.where(sell, 0.5, e)
            gw = np.where(sell, 1.0, gw)
        else:
            gw = np.where(sell, 0.0, gw)
    return e.astype(float), gw.astype(float)


def regime_codes(s, g):
    s = np.asarray(s).astype(int)
    g = np.asarray(g).astype(int)
    return np.where(s == 1, 0, np.where(g == 1, 1, 2)).astype(int)
def basket_table(B):
    """The baskets effective from T0 to the window's end (availableDate on or after T0, effect session inside the window; skipped ones already dropped)."""
    rows = []
    no = 0
    for k in range(len(B["avail"])):
        if B["avail"][k] >= np.datetime64(B["cal"][0]) and B["eff"][k] < B["n"]:
            rows.append(dict(book=B["p"], basket_no=no, available_date=str(pd.Timestamp(B["avail"][k]).date()),
                             session_date=str(B["cal"][B["eff"][k]].date()), idx=int(B["eff"][k])))
            no += 1
    return pd.DataFrame(rows)
def always_in_rows(p, nav_m, pub):
    """G0 (W2): the always-in (hold-the-parent, 0 cost) NAV against the published NAV, as verify_t08.py: CAGR gap over session years and over calendar years
    (limit 0.25 pp), and each calendar year's gap (limit 0.5 pp)."""
    pub = pub / pub.iloc[0]
    yrs = (len(nav_m) - 1) / 252.0
    cg_m = nav_m.iloc[-1] ** (1 / yrs) - 1
    cg_p = pub.iloc[-1] ** (1 / yrs) - 1
    rows = [dict(book=p, scope="overall", gap_pp=float((cg_m - cg_p) * 100), limit_pp=G0_OVERALL_PP)]
    yc = (nav_m.index[-1] - nav_m.index[0]).days / 365.25
    rows.append(dict(book=p, scope="overall_calendar_years", gap_pp=float((nav_m.iloc[-1] ** (1 / yc) - pub.iloc[-1] ** (1 / yc)) * 100), limit_pp=G0_OVERALL_PP))
    ye_m = nav_m.groupby(nav_m.index.year).last()
    ye_p = pub.groupby(pub.index.year).last()
    ym = ye_m / ye_m.shift(1).fillna(1.0) - 1
    yp = ye_p / ye_p.shift(1).fillna(1.0) - 1
    for y in ym.index:
        rows.append(dict(book=p, scope=str(y), gap_pp=float((ym[y] - yp[y]) * 100), limit_pp=G0_YEAR_PP))
    return rows


# ======================================================================================
# T15 loaders: Master files (with the Index column), the daily index prices, the index lines on a calendar
# ======================================================================================
APPROVED = parse_approved()
READS = {}          # relative path -> dict(first_date, gate_only) of every file this verifier read
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


def _read_master(rel, first_date=None, gate_only=False):
    """Weekly Master file -> (dates, SIGN, Index) arrays, sorted. Rows dated before first_date (a restriction) are dropped at load and never used."""
    m = pd.read_excel(rd(rel, first_date, gate_only))
    cols = ["Date", "SIGN"] + (["Index"] if "Index" in m.columns else [])
    m = m[cols].copy()
    m["SIGN"] = m["SIGN"].astype("object")
    m = m[m["SIGN"].notna()]
    m["SIGN"] = m["SIGN"].astype(str).str.strip().str.upper()
    m = m[m["SIGN"] != ""]
    m["Date"] = pd.to_datetime(m["Date"])
    if first_date is not None:
        m = m[m["Date"] >= pd.Timestamp(first_date)]
    m = m.sort_values("Date").reset_index(drop=True)
    assert set(m["SIGN"]) <= {"BUY", "SELL"}, (rel, set(m["SIGN"]))
    ix = m["Index"].astype(float).values if "Index" in m.columns else None
    return m["Date"].values, m["SIGN"].values, ix


def load_masters():
    return {nm: _read_master(F_MASTER[nm], SC100_SIGNAL_FROM if nm == "SC100" else None) for nm in INDICES}


def window_end_of(masters):
    """END of W2 = the last row of the approved index signals (D03): the three Masters' last dates (they must agree)."""
    ends = {nm: pd.Timestamp(v[0][-1]) for nm, v in masters.items()}
    assert len(set(ends.values())) == 1, ends
    return list(ends.values())[0]


def load_index_prices(rel, first_date):
    """Daily index bars (date, open, high, low, close) from rows dated on or after first_date; the read is registered with that first date (a restricted
    Smallcap 100 file refuses an earlier one)."""
    d = pd.read_csv(rd(rel, first_date))
    d["date"] = pd.to_datetime(d["date"])
    d = d[d["date"] >= pd.Timestamp(first_date)].sort_values("date")
    assert d["date"].is_unique, rel
    assert d[["open", "high", "low", "close"]].notna().all().all(), f"{rel}: a bar with a missing price"
    return d.set_index("date")[["open", "high", "low", "close"]].astype(float)


def index_arrays(cal, px):
    """Index lines on the calendar: F = OHLC4 of the session's own bar (NaN where the index has no bar), C = the close, the last close carried on a session
    with no bar, Cbar = the close of the session's own bar (NaN where none), bar = has a bar."""
    n = len(cal)
    F = np.full((n, 3), np.nan)
    C = np.full((n, 3), np.nan)
    Cbar = np.full((n, 3), np.nan)
    for k, nm in enumerate(INDICES):
        s = px[nm]
        o4 = (s["open"] + s["high"] + s["low"] + s["close"]) / 4.0
        F[:, k] = o4.reindex(cal).values
        Cbar[:, k] = s["close"].reindex(cal).values
        C[:, k] = s["close"].reindex(cal, method="ffill").values
    assert not np.isnan(C[0]).any(), "an index has no bar on or before the first session"
    return dict(F=F, C=C, Cbar=Cbar, bar=~np.isnan(F))


def drag_arrays(F, Cbar):
    """R5 (T15.md 2.7): every index OHLC4 and close of session i multiplied by (1 - 0.005 / 252)^i, i the session's position on the window's calendar from T0;
    the series is adjusted first and the last adjusted close is then carried (reading 7 in logs/step_3_log.md)."""
    n = len(F)
    qp = Q_DRAG ** np.arange(n, dtype=float)
    Fd = F * qp[:, None]
    Cd = pd.DataFrame(Cbar * qp[:, None]).ffill().values
    return Fd, Cd


def _asof(dates, sg, d):
    pos = int(np.searchsorted(dates, np.datetime64(d), side="right") - 1)
    assert pos >= 0, f"no Master row on or before {d}"
    return sg[pos], pd.Timestamp(dates[pos])


def required_through(wname, key, row, end):
    """Latest date an approved row must reach (None: exempt by design). W1: the window's end (published NAVs: 2019-12-31, V4 seam); W2: END, except the
    D12 de-spike range and the D19 / D05 basket rows, and the pre-2019 index prices (read only for the V3 tie of Master labels before 2019-01-01)."""
    if "published_nav" in key and wname == "w1":
        return END_D17
    if wname == "w2" and row["id"] in THROUGH_EXEMPT_IDS:
        return None
    if wname == "w2" and "index_daily_pre2019" in key:
        return pd.Timestamp("2018-12-31")
    return end


# ----------------------------------------------------------------------------------------
# decisions, regimes, B and the targets of the eight rules (T15.md 2.1, 3 steps 2-3)
# ----------------------------------------------------------------------------------------
def b_label(buy):
    nm = [INDICES[k] for k in range(3) if buy[k]]
    return "+".join(nm) if nm else "cash"


def rule_targets(rule, reg, g, buy, empty_mask=None):
    """Targets of `rule` at every decision (absolute shares of the book): parent e, GOLDBEES gsh, cash csh, each index w (nd x 3), plus T14's gw for the six
    T14 rules and the trade key of -idx (regime, and B inside OUT-SELL). The six T14 rules: (e, gw) as T14, gsh = (1-e) gw, csh = (1-e)(1-gw). -idx: IN
    parent 1; OUT-BUY the base sleeve (GOLDBEES 0.5 / 0.8, cash the rest); OUT-SELL cash 1/(k+1) and each index of B 1/(k+1), no parent, no GOLDBEES.
    empty_mask (R4): decisions on which B is taken as empty."""
    reg = np.asarray(reg).astype(int)
    g = np.asarray(g).astype(int)
    nd = len(reg)
    var = rule[3:]
    if var != "idx":
        e, gw = rule_arrays(rule, (reg == 0).astype(int), g)
        return dict(e=e, gw=gw, gsh=(1 - e) * gw, csh=(1 - e) * (1 - gw), w=np.zeros((nd, 3)), key=None)
    gb = 0.5 if rule[:2] == "50" else 0.8
    e = np.zeros(nd)
    gsh = np.zeros(nd)
    csh = np.zeros(nd)
    w = np.zeros((nd, 3))
    key = []
    for j in range(nd):
        if reg[j] == 0:
            e[j] = 1.0
            key.append((0,))
        elif reg[j] == 1:
            gsh[j] = gb
            csh[j] = 1 - gb
            key.append((1,))
        else:
            bj = np.array(buy[j], dtype=bool).copy()
            if empty_mask is not None and empty_mask[j]:
                bj[:] = False
            share = 1.0 / (int(bj.sum()) + 1)
            csh[j] = share
            w[j] = np.where(bj, share, 0.0)
            key.append((2,) + tuple(bool(x) for x in bj))
    return dict(e=e, gw=np.full(nd, np.nan), gsh=gsh, csh=csh, w=w, key=key)


def decisions_for_window(p, cal, a, b, wname, masters, gmaster):
    """Decision dates: the window's T0, then the last session of each later ISO week. Every Master (the three indices and MAUc1) is read as-of: the latest
    row dated on or before the decision date. Evidence column layout plus regime, B, k and the targets of the eight rules."""
    cal = cal[a:b]
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
            dates, sg, _ = masters[nm]
            s_, l_ = _asof(dates, sg, d)
            signs.append(s_)
            labels.append(l_)
        gs, gl = _asof(gmaster[0], gmaster[1], d)
        latest = max(labels)
        buy = all(s == "BUY" for s in signs)
        trade = cal[ix + 1] if ix + 1 < len(cal) and j < len(dec_idx) - 1 else None
        g = 1 if gs == "BUY" else 0
        bf = [s == "BUY" for s in signs]
        rows.append(dict(book=p, window=wname, j=j, decision_date=str(d.date()), decision_idx=int(ix),
                         trade_date=None if trade is None else str(trade.date()),
                         sign_Nifty100=signs[0], sign_MC100=signs[1], sign_SC100=signs[2],
                         label_Nifty100=str(labels[0].date()), label_MC100=str(labels[1].date()), label_SC100=str(labels[2].date()),
                         latest_label=str(latest.date()), label_age_days=int((d - latest).days),
                         all_three_buy=bool(buy), state=int(buy),
                         sign_MAUc1=gs, label_MAUc1=str(gl.date()), g=g,
                         buy_Nifty100=int(bf[0]), buy_MC100=int(bf[1]), buy_SC100=int(bf[2]), B=b_label(bf), k=int(sum(bf))))
    df = pd.DataFrame(rows)
    reg = regime_codes(df["state"].values, df["g"].values)
    df["regime"] = [REG_NAMES[c] for c in reg]
    buyarr = df[["buy_Nifty100", "buy_MC100", "buy_SC100"]].values.astype(bool)
    for r in RULES:
        tg = rule_targets(r, reg, df["g"].values, buyarr)
        if r[3:] == "idx":
            df[f"e_{r}"] = tg["e"]
            df[f"gold_{r}"] = tg["gsh"]
            df[f"cash_{r}"] = tg["csh"]
            for k, nm in enumerate(INDICES):
                df[f"w_{nm}_{r}"] = tg["w"][:, k]
        else:
            df[f"e_{r}"] = tg["e"]
            df[f"gw_{r}"] = tg["gw"]
    return df


def mk_T(rule, dec, empty_mask=None):
    reg = regime_codes(dec["state"].values, dec["g"].values)
    buyarr = dec[["buy_Nifty100", "buy_MC100", "buy_SC100"]].values.astype(bool)
    tg = rule_targets(rule, reg, dec["g"].values, buyarr, empty_mask)
    return dict(e=tg["e"], gw=tg["gw"], gsh=tg["gsh"], csh=tg["csh"], w=tg["w"], key=tg["key"], dec_idx=dec["decision_idx"].values.astype(int),
                regime=reg, variant=rule[3:], rule=rule)


def T_hold(di):
    nd = len(di)
    return dict(e=np.ones(nd), gw=np.full(nd, 0.5), gsh=np.zeros(nd), csh=np.zeros(nd), w=np.zeros((nd, 3)), key=None, dec_idx=np.asarray(di),
                regime=np.zeros(nd, dtype=int), variant="orig", rule="hold")


def T_mix(di, f_parent, f_gold, f_cash, f_ix):
    nd = len(di)
    return dict(e=np.full(nd, f_parent), gw=np.full(nd, np.nan), gsh=np.full(nd, f_gold), csh=np.full(nd, f_cash), w=np.tile(np.asarray(f_ix, dtype=float), (nd, 1)),
                key=None, dec_idx=np.asarray(di), regime=None, variant="mix", rule="mix")


# ----------------------------------------------------------------------------------------
# the simulation (own implementation, T15.md 2.2 and 3 steps 3-8)
# ----------------------------------------------------------------------------------------
def build_sched(T, mode):
    """Session index -> (target (e, gsh, csh, w), kind, decision j) for every scheduled trade.
    rule : a trade is due on the session after decision j (1 <= j <= D-2). The six T14 rules: e[j] != e[j-1] or (e[j] < 1 and gw[j] != gw[j-1]); -idx: the key
           (IN / OUT-BUY / OUT-SELL with the set B) differs from decision j-1's. Kind: regime_in / regime_out (not -orig) when the decision changes OUT-SELL
           membership; index_set_change (-idx) with OUT-SELL on both sides and a different B; else switch_in (e[j] = 1), switch_out (e[j-1] = 1), sleeve_rebalance.
    mix  : every decision but the last (rebalance to the constant mix), including after T0's decision."""
    di = T["dec_idx"]
    D = len(T["e"])
    sw = {}

    def tgt(j):
        return (float(T["e"][j]), float(T["gsh"][j]), float(T["csh"][j]), np.array(T["w"][j], dtype=float))
    if mode == "mix":
        for j in range(0, D - 1):
            sw[int(di[j]) + 1] = (tgt(j), "mix_rebalance", j)
    elif mode == "rule":
        reg, var, e, gw = T["regime"], T["variant"], T["e"], T["gw"]
        for j in range(1, D - 1):
            if var == "idx":
                due = T["key"][j] != T["key"][j - 1]
            else:
                due = bool(e[j] != e[j - 1] or (e[j] < 1 and gw[j] != gw[j - 1]))
            if not due:
                continue
            if var in ("half", "liq", "idx") and ((reg[j] == 2) != (reg[j - 1] == 2)):
                kind = "regime_in" if reg[j] == 2 else "regime_out"
            elif var == "idx" and reg[j] == 2 and reg[j - 1] == 2:
                kind = "index_set_change"
            elif e[j] == 1:
                kind = "switch_in"
            elif e[j - 1] == 1:
                kind = "switch_out"
            else:
                kind = "sleeve_rebalance"
            sw[int(di[j]) + 1] = (tgt(j), kind, j)
    return sw


def simulate(V, T, bps, mode="rule", positions=False, W_override=None, Cn_override=None, F_override=None, C_override=None, ixF=None, ixC=None):
    """One realisation on view V (sessions 0..n-1). T: dict(e, gsh, csh, w, gw, dec_idx, regime, variant, key): the target shares at every decision.
    Lines: the stocks of the basket in force, GOLDBEES, cash, the three indices (each filled at its own OHLC4, marked at its close)."""
    n = V["n"]
    C = V["C"] if C_override is None else C_override
    Cn = V["Cn"] if Cn_override is None else Cn_override
    F = V["F"] if F_override is None else F_override
    IXF = V["ixF"] if ixF is None else ixF
    IXC = V["ixC"] if ixC is None else ixC
    gc, gf, L = V["gc"], V["gf"], V["L"]
    W = V["W"] if W_override is None else W_override
    S = len(V["S"])
    b_idx = V["b_idx"]
    basket_at = V["basket_at"]

    def basket_key(i):
        return b_idx[np.searchsorted(b_idx, i, side="right") - 1]

    w0 = W[V["k0"]]
    sh0 = np.where(w0 > 0, w0 / V["init_fill"], 0.0)       # the initial position, bought at the fills of the basket's first session; free of cost
    sh0 = sh0 / float((sh0 * Cn[0]).sum())                  # NAV = 1.000 at T0's close
    e = float(T["e"][0])
    gsh = float(T["gsh"][0])
    csh = float(T["csh"][0])
    wv = np.array(T["w"][0], dtype=float)
    shares = sh0 * e if e > 0 else np.zeros(S)
    gu = gsh / gc[0]
    cu = csh / L[0]
    iu = np.where(wv > 0, wv / np.where(np.isnan(IXC[0]) | (IXC[0] == 0), 1.0, IXC[0]), 0.0)    # the index lines at T0's closes (an OUT-SELL start of -idx)

    sw = build_sched(T, mode)
    chg = [i for i in V["changes"] if i < n]
    events = sorted(set(k for k in sw if k < n) | set(chg))

    segs = [(0, shares.copy(), gu, cu, iu.copy())]
    trades = []
    for i in events:
        bk = basket_key(i)
        w = W[basket_at[bk]]
        pf = F[i]
        ixf = IXF[i]
        held = shares != 0
        partial = False
        if i in sw:
            (e_new, gsh_new, csh_new, w_new), kind, jdec = sw[i]
        else:
            kind, jdec = "basket_change", None
            if e <= 0.0:
                continue                      # basket change while OUT (e = 0): nothing traded
            e_new, gsh_new, csh_new, w_new = e, gsh, csh, wv
            partial = (mode == "rule" and e < 1.0)       # D1: while 0 < e < 1 only the stock part is re-weighted
        tgt_w = w if partial else e_new * w
        need = (tgt_w > 0) | held
        if np.isnan(pf[need]).any():
            raise RuntimeError(f"missing fill price for a needed stock at {V['cal'][i]}")
        need_x = (np.asarray(w_new) > 0) | (iu != 0)
        if np.isnan(ixf[need_x]).any():
            raise RuntimeError(f"an index line is traded on {V['cal'][i]} but the index has no bar that session")
        pfz = np.where(np.isnan(pf), 0.0, pf)
        ixfz = np.where(np.isnan(ixf), 0.0, ixf)
        cur_stock = np.where(held, shares * pfz, 0.0)
        cur_g = gu * gf[i]
        cur_c = cu * L[i]
        cur_x = np.where(iu != 0, iu * ixfz, 0.0)
        S_cur = float(cur_stock.sum())
        Vv = S_cur + cur_g + cur_c + float(cur_x.sum())
        if partial:
            tgt_stock = S_cur * w
            traded = float(np.abs(tgt_stock - cur_stock).sum())
            cost = traded * bps / 2.0 / 10000.0
            shares = np.where(tgt_stock > 0, (S_cur - cost) * w / np.where(np.isnan(pf), 1.0, pf), 0.0)
            stock_after, gold_after, cash_after, ix_after = S_cur - cost, cur_g, cur_c, cur_x.copy()
        else:
            tgt_stock = e_new * Vv * w
            tgt_g = gsh_new * Vv
            tgt_c = csh_new * Vv
            tgt_x = np.asarray(w_new) * Vv
            traded = float(np.abs(tgt_stock - cur_stock).sum() + abs(tgt_g - cur_g) + abs(tgt_c - cur_c) + np.abs(tgt_x - cur_x).sum())
            cost = traded * bps / 2.0 / 10000.0
            f = (Vv - cost) / Vv
            shares = np.where(tgt_stock > 0, tgt_stock * f / np.where(np.isnan(pf), 1.0, pf), 0.0)
            gu = tgt_g * f / gf[i]
            cu = tgt_c * f / L[i]
            iu = np.where(tgt_x > 0, tgt_x * f / np.where(np.isnan(ixf), 1.0, ixf), 0.0)
            stock_after, gold_after, cash_after, ix_after = float(tgt_stock.sum() * f), tgt_g * f, tgt_c * f, tgt_x * f
            e, gsh, csh, wv = e_new, gsh_new, csh_new, np.array(w_new, dtype=float)
        segs.append((i, shares.copy(), gu, cu, iu.copy()))
        tr = dict(idx=i, date=str(V["cal"][i].date()), kind=kind, e_after=e, gold_share=gsh, cash_share=csh,
                  w_Nifty100=float(wv[0]), w_MC100=float(wv[1]), w_SC100=float(wv[2]),
                  basket_eff=str(pd.Timestamp(V["avail"][basket_at[bk]]).date()), V=Vv, traded=traded, cost=cost, dec_j=jdec,
                  stock_before=S_cur, gold_before=cur_g, cash_before=cur_c, Nifty100_before=float(cur_x[0]), MC100_before=float(cur_x[1]), SC100_before=float(cur_x[2]),
                  stock_after=stock_after, gold_after=gold_after, cash_after=cash_after,
                  Nifty100_after=float(ix_after[0]), MC100_after=float(ix_after[1]), SC100_after=float(ix_after[2]), V_after=Vv - cost, partial=partial)
        trades.append(tr)

    nav = np.empty(n)
    seg_end = [s[0] for s in segs[1:]] + [n]
    for (i0, sh, gu_, cu_, iu_), i1 in zip(segs, seg_end):
        nz = sh != 0
        if np.isnan(C[i0:i1][:, nz]).any():
            raise RuntimeError("held stock without a close")
        nav[i0:i1] = Cn[i0:i1] @ sh + gc[i0:i1] * gu_ + L[i0:i1] * cu_ + IXC[i0:i1] @ iu_
    for t in trades:
        t["nav_close_after"] = float(nav[t["idx"]])
    out = dict(nav=nav, trades=trades)
    if positions:
        pos = []
        for (i0, sh, gu_, cu_, iu_), t in zip(segs[1:], trades):
            for nm, u in zip(V["S"], sh):
                if u != 0:
                    pos.append((t["date"], nm, float(u)))
            pos.append((t["date"], "GOLDBEES", float(gu_)))
            pos.append((t["date"], "LBES", float(cu_)))
            for nm, u in zip(INDICES, iu_):
                if u != 0:
                    pos.append((t["date"], "IDX_" + nm, float(u)))
        out["positions"] = pos
    return out


def attach_index(V, IX, a, b, F=None, C=None):
    V["ixF"] = (IX["F"] if F is None else F)[a:b]
    V["ixC"] = (IX["C"] if C is None else C)[a:b]
    return V


def make_view_n(B, a, b, cash="lbes"):
    V = make_view(B, a, b, cash)
    V["ixF"] = np.full((V["n"], 3), np.nan)
    V["ixC"] = np.zeros((V["n"], 3))
    return V


# ----------------------------------------------------------------------------------------
# regimes, spells, ledger and counts
# ----------------------------------------------------------------------------------------
def sell_spells(reg):
    sp = []
    j = 0
    D_ = len(reg)
    while j < D_:
        if reg[j] == 2:
            k = j
            while k + 1 < D_ and reg[k + 1] == 2:
                k += 1
            sp.append((j, k))
            j = k + 1
        else:
            j += 1
    return sp


def b_stretches(Bl, a, b):
    """Maximal runs of the same B label over decisions a..b: [(first, last)]."""
    out = []
    s = a
    for j in range(a + 1, b + 2):
        if j == b + 1 or Bl[j] != Bl[s]:
            out.append((s, j - 1))
            s = j
    return out


def runs_of(s):
    out = []
    start = 0
    for i in range(1, len(s) + 1):
        if i == len(s) or s[i] != s[start]:
            out.append((int(s[start]), i - start))
            start = i
    return out


def series_facts(dec, n_sessions, cal, due):
    """Counts of one decision series (a book's full window or R3 window), the keys of logs/step_1_spell_counts.json."""
    s = dec["state"].values.astype(int)
    g = dec["g"].values.astype(int)
    reg = regime_codes(s, g)
    kk = dec["k"].values.astype(int)
    Bl = dec["B"].tolist()
    D_ = len(s)
    runs = runs_of(s)
    f = dict(start=str(cal[0].date()), end=str(cal[-1].date()), sessions=int(n_sessions), weeks=int(D_), first_state=int(s[0]), last_state=int(s[-1]),
             weeks_in=int(s.sum()), weeks_out=int(D_ - s.sum()), in_spells=sum(1 for v, _ in runs if v == 1), out_spells=sum(1 for v, _ in runs if v == 0))
    f["round_trips"] = min(f["in_spells"], f["out_spells"])
    f["weeks_IN"], f["weeks_OUT_BUY"], f["weeks_OUT_SELL"] = int((reg == 0).sum()), int((reg == 1).sum()), int((reg == 2).sum())
    sp = sell_spells(reg)
    f["OUT_SELL_spells"] = len(sp)
    f["OUT_SELL_lengths"] = [b - a + 1 for a, b in sp]
    for kv in (0, 1, 2):
        f[f"OUT_SELL_weeks_k{kv}"] = int(((reg == 2) & (kk == kv)).sum())
    f["OUT_SELL_weeks_holding_an_index"] = int(((reg == 2) & (kk > 0)).sum())
    f["OUT_SELL_spells_holding_an_index"] = sum(1 for a, b in sp if (kk[a:b + 1] > 0).any())
    f["B_changes_inside_OUT_SELL"] = int(sum(1 for j in range(1, D_) if reg[j] == 2 and reg[j - 1] == 2 and Bl[j] != Bl[j - 1]))
    f["idx_trades_from_B_change_alone"] = int(sum(1 for j in range(1, D_ - 1) if reg[j] == 2 and reg[j - 1] == 2 and Bl[j] != Bl[j - 1]))
    tab = []
    for a, b in sp:
        seq = [[Bl[x], y - x + 1] for x, y in b_stretches(Bl, a, b)]
        tab.append(dict(first_decision=dec["decision_date"].iloc[a], last_decision=dec["decision_date"].iloc[b], weeks=b - a + 1,
                        entered_from="start" if a == 0 else REG_NAMES[reg[a - 1]], exited_to="window end" if b + 1 >= D_ else REG_NAMES[reg[b + 1]],
                        B_sequence=seq, weeks_holding_an_index=int((kk[a:b + 1] > 0).sum())))
    f["OUT_SELL_spell_table"] = tab
    gr = runs_of(g)
    f["g_flips"] = len(gr) - 1
    f["g_first_state"] = int(g[0])
    f["trades_due"] = dict(due)
    return f


def trades_due_of(T):
    return len(build_sched(T, "rule"))


def ledger_rows(window, p, dec, V, navs20, hold0):
    """One row per OUT-SELL spell and per B stretch inside it (evidence_contract.md). Span of a run of decisions a..b: from the close of the session on which
    decision a is traded (T0 for decision 0) to the close of the session on which the decision b+1 that ends it is traded (the last session when the run
    reaches the end, or the ending decision is the last one and never traded). Returns the parent (hold-the-parent, 0 bps), GOLDBEES, cash and index
    returns over the span (closes) and each rule's 20.8 bps NAV return."""
    reg = regime_codes(dec["state"].values, dec["g"].values)
    kk = dec["k"].values.astype(int)
    Bl = dec["B"].tolist()
    di = dec["decision_idx"].values.astype(int)
    dd = dec["decision_date"].tolist()
    D_ = len(reg)
    n = V["n"]
    cal = V["cal"]

    def sess_of(j):
        return 0 if j == 0 else (di[j] + 1 if (j <= D_ - 2 and di[j] + 1 < n) else n - 1)

    def one(level, spell_no, stretch_no, a, b, Bv, kv):
        i0 = sess_of(a)
        i1 = sess_of(b + 1) if b + 1 <= D_ - 2 else n - 1
        row = dict(window=window, book=p, level=level, spell_no=spell_no, stretch_no=stretch_no, B=Bv, k=int(kv), first_decision=dd[a], last_decision=dd[b],
                   weeks=b - a + 1, a_session=str(cal[i0].date()), b_session=str(cal[i1].date()),
                   entered_from="start" if a == 0 else REG_NAMES[reg[a - 1]], exited_to="window end" if b + 1 >= D_ else REG_NAMES[reg[b + 1]],
                   parent_return=float(hold0[i1] / hold0[i0] - 1), goldbees_return=float(V["gc"][i1] / V["gc"][i0] - 1),
                   cash_return=float(V["L"][i1] / V["L"][i0] - 1))
        for k_, nm in enumerate(INDICES):
            row[f"{nm}_return"] = float(V["ixC"][i1, k_] / V["ixC"][i0, k_] - 1)
        for r in RULES:
            row[f"ret_{r}"] = float(navs20[r][i1] / navs20[r][i0] - 1)
        return row
    rows = []
    for no, (a, b) in enumerate(sell_spells(reg), start=1):
        st = b_stretches(Bl, a, b)
        rows.append(one("spell", no, 0, a, b, Bl[a], kk[a]))
        for sn, (x, y) in enumerate(st, start=1):
            rows.append(one("stretch", no, sn, x, y, Bl[x], kk[x]))
    return rows


# ----------------------------------------------------------------------------------------
# derive everything of one window that does not depend on the evidence
# ----------------------------------------------------------------------------------------
def stat_row(p, window, variant, cash, bps, run, nav, trades):
    st = stats_of(nav)
    kinds = [x["kind"] for x in trades]
    st.update(book=p, window=window, variant=variant, cash=cash, cost_bps=bps, run=run, trades=len(trades), cost_paid=float(sum(x["cost"] for x in trades)),
              regime_trades=sum(1 for k in kinds if k in ("regime_in", "regime_out")), index_set_trades=sum(1 for k in kinds if k == "index_set_change"),
              basket_trades=sum(1 for k in kinds if k == "basket_change"), switch_trades=sum(1 for k in kinds if k in ("switch_in", "switch_out")),
              sleeve_trades=sum(1 for k in kinds if k == "sleeve_rebalance"))
    return st


def derive(wname, books, verbose=True, idx_shift=0):
    t = time.time()
    READS.clear()
    masters = load_masters()
    gmaster = _read_master(F_G[wname]["master"])[:2]
    gold, mcx = load_gold_files(wname)
    lbes, liq = load_lbes(), load_liquidcase()
    corr = load_corrections()
    px = {nm: load_index_prices(F_IDX[wname][nm], IDX_READ_FROM[wname]) for nm in INDICES}
    px_pre = {nm: load_index_prices(F_IDX_D25[nm], IDX_PRE_READ_FROM) for nm in INDICES} if wname == "w2" else None
    if wname == "w1":
        T0, END = pd.Timestamp("2014-09-01"), pd.Timestamp("2019-01-02")
        cal_shared = load_w1_calendar(T0, END)
    else:
        END = window_end_of(masters)
        cal_shared = None
    D = {"wname": wname, "books": {}, "dec": [], "nav": [], "stats": [], "trades": [], "positions": [], "meta": {}, "facts": {}, "baskets": [],
         "masters": masters, "gmaster": gmaster, "END": END, "one_instrument": {}, "hold0": {}, "ledger": [], "mix_params": {}, "g0": [], "seam": [],
         "robust_stats": [], "robust_nav": [], "v4b": [], "v4c": [], "nobar": {}, "tie": [], "px": px, "px_pre": px_pre, "spells": {}, "idx_first_trade": {}}
    nav_frames, rnav_frames = [], []
    for p in books:
        touch_book_files(p)
        if wname == "w1":
            cal = cal_shared
            pub = None
        else:
            pub = load_published_nav(p)
            cal = pub.index[pub.index <= END]
            assert cal[-1] == END, (p, cal[-1], END)
        dstr = [str(d.date()) for d in cal]
        MK = market_arrays(cal, gold, mcx, lbes, liq)
        if wname == "w2":
            MK["L2"] = chain_liquidcase(cal, MK["L"], MK["L2"])       # R2 on W2: LBES, then LIQUIDCASE returns chained from 2024-01-24 (T08's LIQ_FROM)
        n = len(cal)
        B = build_book(p, cal, MK, corr)
        if idx_shift:       # self-test only: the verifier's own copy of the index bars shifted by `idx_shift` bars (each bar date carries the earlier bar's prices)
            pxs = {}
            for nm, s_ in px.items():
                s2 = s_.copy()
                s2.iloc[:, :] = s_.shift(idx_shift).bfill().values
                pxs[nm] = s2
            IX = index_arrays(cal, pxs)
        else:
            IX = index_arrays(cal, px)
        a_r3 = int(np.searchsorted(cal.values, np.datetime64(R3_START_W1 if wname == "w1" else LIVE_START), side="left"))
        V = attach_index(make_view(B, 0, n, "lbes"), IX, 0, n)
        Vliq = attach_index(make_view(B, 0, n, "liq"), IX, 0, n)
        Vr3 = attach_index(make_view(B, a_r3, n, "lbes"), IX, a_r3, n)
        dec = decisions_for_window(p, cal, 0, n, wname, masters, gmaster)
        dec3 = decisions_for_window(p, cal, a_r3, n, wname, masters, gmaster)
        di, di3 = dec["decision_idx"].values.astype(int), dec3["decision_idx"].values.astype(int)
        nd = len(dec)
        bt = basket_table(B)
        D["baskets"].append(bt)
        D["dec"].extend([dec.assign(_win="full"), dec3.assign(_win="r3")])
        T8 = {r: mk_T(r, dec) for r in RULES}
        T8_3 = {r: mk_T(r, dec3) for r in RULES}
        D["books"][p] = dict(B=B, V=V, Vr3=Vr3, dec=dec, dec3=dec3, di=di, di3=di3, T8=T8, T8_3=T8_3, pub=pub, a_r3=a_r3, IX=IX)
        D["meta"][p] = dict(sessions=n, decisions=nd, t0=str(cal[0].date()), end=str(cal[-1].date()), r3_t0=str(cal[a_r3].date()), baskets=len(bt),
                            sessions_without_any_d18_bar=B["sessions_all_stocks_no_bar"], skipped_dropped=[str(pd.Timestamp(x).date()) for x in B["skipped"]],
                            stale=int(((dec["label_age_days"] >= 5) & (dec["j"] > 0)).sum()))
        D["nobar"][p] = {"full": {nm: [dstr[i] for i in np.flatnonzero(~IX["bar"][:, k])] for k, nm in enumerate(INDICES)},
                         "r3": {nm: [dstr[i] for i in np.flatnonzero(~IX["bar"][a_r3:, k]) + a_r3] for k, nm in enumerate(INDICES)}}
        # --- the Master `Index` column against the daily index close on the label date (V3)
        for nm_k, nm in enumerate(INDICES):
            dates, sg, mix = masters[nm]
            labs = sorted(set(dec[f"label_{nm}"]))
            for lab in labs:
                pos = int(np.searchsorted(dates, np.datetime64(pd.Timestamp(lab))))
                assert pd.Timestamp(dates[pos]) == pd.Timestamp(lab)
                src = px_pre if (wname == "w2" and pd.Timestamp(lab) < pd.Timestamp("2019-01-01")) else px
                cl = float(src[nm]["close"].get(pd.Timestamp(lab), np.nan))
                D["tie"].append(dict(book=p, index=nm, label=lab, master_index=float(mix[pos]), close=cl,
                                     rel=float(abs(mix[pos] - cl) / abs(cl)) if not np.isnan(cl) else np.nan))
        # --- mixes and runs
        mixp = {}
        for r in RULES:
            tg = T8[r]
            fi = tg["w"].mean(axis=0)
            mixp[r] = (float(tg["e"].mean()), float(tg["gsh"].mean()), float(tg["csh"].mean()), [float(x) for x in fi])
            D["mix_params"][(p, r)] = mixp[r]
        runs20 = {}
        trade_rows, pos_rows = [], []
        navs = {}                                                   # (run, bps) -> nav
        for bps in COSTS:
            for r in RULES:
                res = simulate(V, T8[r], bps, "rule", positions=(bps == HEADLINE_COST))
                navs[(r, bps)] = res["nav"]
                for x in res["trades"]:
                    trade_rows.append(dict(book=p, window="full", cost_bps=bps, run=r, **x))
                if bps == HEADLINE_COST:
                    for dt, nm, u in res["positions"]:
                        pos_rows.append(dict(book=p, window="full", cost_bps=bps, run=r, date=dt, instrument=nm, units=u))
                D["stats"].append(stat_row(p, "full", "headline", "lbes", bps, r, res["nav"], res["trades"]))
                if r in IDX_RULES and bps == HEADLINE_COST:
                    fi_ = [x["idx"] for x in res["trades"] if x["w_Nifty100"] > 0 or x["w_MC100"] > 0 or x["w_SC100"] > 0]
                    D["idx_first_trade"][(p, r)] = min(fi_) if fi_ else n
            res = simulate(V, T_hold(di), bps, "hold")
            navs[("hold_parent", bps)] = res["nav"]
            for x in res["trades"]:
                trade_rows.append(dict(book=p, window="full", cost_bps=bps, run="hold_parent", **x))
            D["stats"].append(stat_row(p, "full", "headline", "lbes", bps, "hold_parent", res["nav"], res["trades"]))
            if bps == 0.0:
                D["hold0"][p] = res["nav"]
        for k, nm in enumerate(INDICES):
            navs[(f"hold_{nm}", HEADLINE_COST)] = V["ixC"][:, k] / V["ixC"][0, k]
            D["stats"].append(stat_row(p, "full", "headline", "lbes", HEADLINE_COST, f"hold_{nm}", navs[(f"hold_{nm}", HEADLINE_COST)], []))
        for r in RULES:
            f_ = mixp[r]
            res = simulate(V, T_mix(di, f_[0], f_[1], f_[2], f_[3]), HEADLINE_COST, "mix")
            navs[(f"cmix_{r}", HEADLINE_COST)] = res["nav"]
            D["stats"].append(stat_row(p, "full", "headline", "lbes", HEADLINE_COST, f"cmix_{r}", res["nav"], res["trades"]))
        for (run, bps), nv in navs.items():
            nav_frames.append(pd.DataFrame(dict(book=p, date=dstr, cost_bps=bps, run=run, nav=nv)))
        D["trades"].extend(trade_rows)
        D["positions"].extend(pos_rows)
        # --- R2 (LIQUIDCASE cash), R3, R4, R5 at 20.8 bps
        rdstr3 = dstr[a_r3:]

        def add_robust(variant, window, cash, run, res, dates):
            D["robust_stats"].append(stat_row(p, window, variant, cash, HEADLINE_COST, run, res["nav"], res["trades"]))
            rnav_frames.append(pd.DataFrame(dict(book=p, window=window, variant=variant, cost_bps=HEADLINE_COST, run=run, date=dates, nav=res["nav"])))
        for r in RULES:
            add_robust("r2_liq", "full", "liq", r, simulate(Vliq, T8[r], HEADLINE_COST, "rule"), dstr)
        for r in RULES:
            add_robust("r3", "r3", "lbes", r, simulate(Vr3, T8_3[r], HEADLINE_COST, "rule"), rdstr3)
        reg_full = regime_codes(dec["state"].values, dec["g"].values)
        sp = sell_spells(reg_full)
        D["spells"][p] = sp
        for sn, (a, b) in enumerate(sp, start=1):
            mask = np.zeros(nd, dtype=bool)
            mask[a:b + 1] = True
            for r in IDX_RULES:
                add_robust(f"r4_s{sn}", "full", "lbes", r, simulate(V, mk_T(r, dec, empty_mask=mask), HEADLINE_COST, "rule"), dstr)
        Fd, Cd = drag_arrays(IX["F"], IX["Cbar"])
        Vd = attach_index(dict(V), IX, 0, n, F=Fd, C=Cd)
        for r in RULES:
            add_robust("r5_drag", "full", "lbes", r, simulate(Vd, T8[r], HEADLINE_COST, "rule"), dstr)
        # --- the regime ledger (full window; R3's window beside it)
        navs20 = {r: navs[(r, HEADLINE_COST)] for r in RULES}
        D["ledger"] += ledger_rows("full", p, dec, V, navs20, D["hold0"][p])
        # --- facts (counts) of the full and R3 series
        due = {r: trades_due_of(T8[r]) for r in RULES}
        due3 = {r: trades_due_of(T8_3[r]) for r in RULES}
        D["facts"][(p, "full")] = series_facts(dec, n, cal, due)
        D["facts"][(p, "r3")] = series_facts(dec3, n - a_r3, cal[a_r3:], due3)
        # --- V4(b): every index priced at the cash level, cost 0: -idx equals -liq on every session
        Vc = attach_index(dict(V), IX, 0, n, F=np.repeat(MK["L"][:, None], 3, axis=1), C=np.repeat(MK["L"][:, None], 3, axis=1))
        for r in IDX_RULES:
            nv = simulate(Vc, T8[r], 0.0, "rule")["nav"]
            ref = navs[(r[:2] + "-liq", 0.0)]
            D["v4b"].append(dict(book=p, rule=r, max_rel=float(np.max(np.abs(nv - ref) / np.abs(ref))), sessions=n))
        # --- V4(c): -idx equals -liq at 20.8 bps on every session before the first trade into an index
        for r in IDX_RULES:
            i1 = D["idx_first_trade"][(p, r)]
            a_, b_ = navs[(r, HEADLINE_COST)], navs[(r[:2] + "-liq", HEADLINE_COST)]
            D["v4c"].append(dict(book=p, rule=r, first_index_trade_session=int(i1), sessions=int(i1),
                                 max_rel=float(np.max(np.abs(a_[:i1] - b_[:i1]) / np.abs(b_[:i1]))) if i1 > 0 else 0.0))
        # --- V4(f): one instrument at weight 1, 0 cost, always in = close / first close
        W0 = B["W"][V["k0"]]
        res_ = []
        for i in np.flatnonzero(W0 > 0):
            W1 = np.zeros_like(B["W"])
            W1[:, i] = 1.0
            r = simulate(V, T_hold(di), 0.0, "hold", W_override=W1)
            tgt = V["C"][:, i] / V["C"][0, i]
            res_.append((B["S"][i], float(np.max(np.abs(r["nav"] - tgt) / np.abs(tgt)))))
        D["one_instrument"][p] = res_
        # --- G0 (W2) / seam (W1)
        if wname == "w2":
            D["g0"].extend(always_in_rows(p, pd.Series(D["hold0"][p], index=cal), pub.loc[cal]))
        else:
            pubn = load_published_nav(p)
            cal17 = pubn.index[pubn.index <= END_D17]
            MK17 = market_arrays(cal17, gold, mcx, lbes, liq)
            B17 = build_book(p, cal17, MK17, corr)
            V17 = make_view_n(B17, 0, len(cal17))
            nv = simulate(V17, T_hold(np.arange(1)), 0.0, "hold")["nav"]
            pv = pubn.loc[cal17].values
            D["seam"].append(dict(book=p, first=str(cal17[0].date()), last=str(cal17[-1].date()), year_gap_pp=float((nv[-1] / nv[0] - pv[-1] / pv[0]) * 100.0),
                                  limit_pp=SEAM_PP))
        if verbose:
            f_ = D["facts"][(p, "full")]
            print(f"[{wname} {time.time()-t:6.1f}s] {p}: derived (sessions {n}, decisions {nd}, stocks {len(B['S'])}, baskets {len(bt)}, "
                  f"OUT-SELL weeks {f_['weeks_OUT_SELL']} in {f_['OUT_SELL_spells']} spells, index weeks {f_['OUT_SELL_weeks_holding_an_index']})", flush=True)
    D["dec"] = pd.concat(D["dec"], ignore_index=True)
    D["nav"] = pd.concat(nav_frames, ignore_index=True)
    D["robust_nav"] = pd.concat(rnav_frames, ignore_index=True)
    D["stats"] = pd.DataFrame(D["stats"])
    D["robust_stats"] = pd.DataFrame(D["robust_stats"])
    D["trades"] = pd.DataFrame(D["trades"])
    D["positions"] = pd.DataFrame(D["positions"])
    D["baskets"] = pd.concat(D["baskets"], ignore_index=True)
    D["ledger"] = pd.DataFrame(D["ledger"])
    D["tie"] = pd.DataFrame(D["tie"])
    D["reads"] = {k: dict(v) for k, v in READS.items()}
    # R3's regime ledger from the R3 NAVs
    r3n = D["robust_nav"]
    r3n = r3n[r3n["variant"] == "r3"]
    led3 = []
    for p in books:
        bk = D["books"][p]
        navs20_r3 = {r: r3n[(r3n["book"] == p) & (r3n["run"] == r)]["nav"].values for r in RULES}
        hold_r3 = simulate(bk["Vr3"], T_hold(bk["di3"]), 0.0, "hold")["nav"]
        led3 += ledger_rows("r3", p, bk["dec3"], bk["Vr3"], navs20_r3, hold_r3)
    D["ledger"] = pd.concat([D["ledger"], pd.DataFrame(led3)], ignore_index=True)
    return D


# ======================================================================================
# the checks
# ======================================================================================
_ONLY = None            # when a set: only the checks named in it are run (the isolated self-test)


def run_check(C, name, fn, gate=True):
    c = Check(name, gate=gate)
    if _ONLY is not None and name not in _ONLY:
        return c
    C[name] = c
    try:
        fn(c)
    except Exception as ex:
        c.failed += 1
        c.fail(f"verifier exception in {name}: {ex!r} | {traceback.format_exc(limit=3).strip().splitlines()[-1]}")
    return c


STEP1 = json.load(open(STEP1_JSON)) if STEP1_JSON.exists() else None
TRADE_NUM = ["idx", "e_after", "gold_share", "cash_share", "w_Nifty100", "w_MC100", "w_SC100", "V", "traded", "cost", "stock_before", "gold_before", "cash_before",
             "Nifty100_before", "MC100_before", "SC100_before", "stock_after", "gold_after", "cash_after", "Nifty100_after", "MC100_after", "SC100_after", "V_after",
             "nav_close_after", "dec_j"]
TRADE_STR = ["date", "kind", "basket_eff"]
TRADE_RUNS = RULES + ["hold_parent"]
NUMS = ["end_nav", "cagr", "max_dd", "vol", "ulcer", "calmar"]
INTS = ["days_below_10pct", "longest_underwater", "sessions"]
CNT = ["trades", "cost_paid", "regime_trades", "index_set_trades", "basket_trades", "switch_trades", "sleeve_trades"]
GB = {"50": 0.5, "80": 0.8}


def dec_columns():
    n_cols = ["decision_idx", "label_age_days", "state", "g", "buy_Nifty100", "buy_MC100", "buy_SC100", "k"]
    for r in RULES:
        if r[3:] == "idx":
            n_cols += [f"e_{r}", f"gold_{r}", f"cash_{r}"] + [f"w_{nm}_{r}" for nm in INDICES]
        else:
            n_cols += [f"e_{r}", f"gw_{r}"]
    s_cols = ["trade_date", "sign_Nifty100", "sign_MC100", "sign_SC100", "label_Nifty100", "label_MC100", "label_SC100", "latest_label", "decision_date",
              "all_three_buy", "sign_MAUc1", "label_MAUc1", "regime", "window", "B"]
    return n_cols, s_cols


def compare_all(wname, D, E, BK):
    C = {}
    cal_end = D["END"]
    dec_m = D["dec"]
    dec_full = dec_m[dec_m["_win"] == "full"].drop(columns=["_win"])
    dec_r3 = dec_m[dec_m["_win"] == "r3"].drop(columns=["_win"])
    n_cols, s_cols = dec_columns()
    date_idx = {p: {str(d.date()): i for i, d in enumerate(D["books"][p]["V"]["cal"])} for p in D["books"]}
    est_all = E.get("stats.csv")
    env_all = E.get("daily_nav.csv")
    mst = D["stats"].copy()
    mst["cost_bps"] = r4(mst["cost_bps"])
    mnv = D["nav"].copy()
    mnv["cost_bps"] = r4(mnv["cost_bps"])
    if est_all is not None:
        est_all = est_all[est_all["book"].isin(BK)].copy()
        est_all["cost_bps"] = r4(est_all["cost_bps"])
    if env_all is not None:
        env_all = env_all[env_all["book"].isin(BK)].copy()
        env_all["cost_bps"] = r4(env_all["cost_bps"])
        env_all["date"] = env_all["date"].astype(str)
    tr_ev = E.get("trades.csv")
    if tr_ev is not None:
        tr_ev = tr_ev[tr_ev["book"].isin(BK)].copy()
        tr_ev["cost_bps"] = r4(tr_ev["cost_bps"])
        tr_ev["date"] = tr_ev["date"].astype(str)

    # ------------------------------------------------------------------ C-data (gate V1: every input APPROVED, sha256, through-date, usable-from)
    def c_data(c):
        own = E.get("inputs.csv", c)
        frames = [("this window", own)]
        for d_ in E.partner_dirs:
            p_ = Path(d_) / "inputs.csv"
            if p_.exists():
                frames.append((Path(d_).name, pd.read_csv(p_)))
        for key in sorted(READS):
            row = APPROVED.get(key)
            c.compared += 1
            ok = row is not None and row["status"] == "APPROVED"
            if ok:
                sha = sha256_file(AA / key)
                ok = sha.startswith(row["sha"])
                rt = required_through(wname, key, row, cal_end)
                if ok and rt is not None and row["through"].lower() != "n/a":
                    ok = pd.Timestamp(row["through"]) >= rt
                uf = row["usable_from"]
                if ok and uf is not None:
                    fd = READS[key]["first_date"]
                    c.compared += 1
                    ok = fd is not None and pd.Timestamp(fd) >= pd.Timestamp(uf)
            if not ok:
                c.failed += 1
                c.fail(f"verifier-read file not an APPROVED, matching, covering, unrestricted row: {key}")
        listed = set()
        for tag, inp in frames:
            if inp is None:
                continue
            cols = {x.lower(): x for x in inp.columns}
            fcol = cols.get("file")
            if fcol is None:
                c.failed += 1
                c.fail("inputs.csv has no 'file' column")
                continue
            for need in ("through", "bytes", "sha256", "approved_row", "usable_from"):
                if need not in cols:
                    c.miss(f"inputs.csv column {need}")
            for _, r in inp.iterrows():
                key = norm_path(r[fcol])
                listed.add(key)
                row = APPROVED.get(key)
                c.compared += 1
                if row is None:
                    c.failed += 1
                    c.fail(f"inputs.csv ({tag}) lists a file that is not in APPROVED_DATA.md: {key}")
                    continue
                if row["status"] != "APPROVED":
                    c.failed += 1
                    c.fail(f"inputs.csv ({tag}) lists a {row['status']} file: {key}")
                    continue
                c.compared += 1
                if row["id"] in NOT_READ_IDS:
                    c.failed += 1
                    c.fail(f"inputs.csv ({tag}) lists {key} (row {row['id']}), which T15.md section 3 lists under 'Not read'")
                sha = str(r[cols["sha256"]]).lower() if "sha256" in cols else ""
                c.compared += 2
                if not sha.startswith(row["sha"]):
                    c.failed += 1
                    c.fail(f"sha256 of {key} in inputs.csv ({sha[:16]}) does not start with the approved prefix {row['sha']}")
                disk = sha256_file(AA / key) if (AA / key).exists() else None
                if disk is None or (sha and disk != sha and not disk.startswith(sha)):
                    c.failed += 1
                    c.fail(f"sha256 of {key} in inputs.csv differs from the file on disk")
                if "bytes" in cols and (AA / key).exists():
                    c.compared += 1
                    if int(r[cols["bytes"]]) != (AA / key).stat().st_size:
                        c.failed += 1
                        c.fail(f"bytes of {key} in inputs.csv ({r[cols['bytes']]}) differ from the file on disk")
                if "approved_row" in cols:
                    c.compared += 1
                    if str(r[cols["approved_row"]]).strip() != f"APPROVED {row['id']}":
                        c.failed += 1
                        c.fail(f"approved_row of {key} in inputs.csv ({r[cols['approved_row']]!r}) is not 'APPROVED {row['id']}'")
                if "through" in cols:
                    c.compared += 1
                    th = str(r[cols["through"]]).strip()
                    if th.lower() not in ("n/a", "nan") and row["through"].lower() != "n/a" and th != row["through"]:
                        c.failed += 1
                        c.fail(f"through of {key} in inputs.csv ({th}) differs from APPROVED_DATA.md ({row['through']})")
                if "usable_from" in cols:
                    c.compared += 1
                    uv = r[cols["usable_from"]]
                    uv = None if (uv is None or (isinstance(uv, float) and np.isnan(uv)) or str(uv).strip() in ("", "nan", "None")) else str(uv).strip()
                    if uv != row["usable_from"]:
                        c.failed += 1
                        c.fail(f"usable_from of {key} in inputs.csv ({uv}) differs from the registry's marker ({row['usable_from']})")
        for key in sorted(set(READS) - listed):
            c.compared += 1
            c.failed += 1
            c.fail(f"a file needed to rebuild the run is not in any inputs.csv of the evidence: {key}")
        c.notes.append(f"{len(READS)} files read by the verifier; {len(listed)} distinct files listed in inputs.csv of the evidence folders")
    run_check(C, "C-data", c_data)

    def c_inputs_window(c):
        """Informational: does this window's own inputs.csv list every file this window's rebuild needs?"""
        own = E.get("inputs.csv")
        if own is None:
            return
        have = {norm_path(x) for x in own["file"]}
        miss = sorted(set(READS) - have)
        c.compared += len(READS)
        c.failed += len(miss)
        if miss:
            c.fail(f"this window's inputs.csv lacks {len(miss)} of the {len(READS)} files its rebuild reads (they are listed in the other window's inputs.csv); e.g. {miss[:3]}")
    run_check(C, "C-inputs-per-window(info)", c_inputs_window, gate=False)

    def c_sc100(c):
        saved = {k: dict(v) for k, v in READS.items()}
        for key, first in ((F_MASTER["SC100"], "2011-11-24"), (F_MASTER["SC100"], "2004-01-01"), (F_IDX_D25["SC100"], "2011-10-02"), (F_IDX_D25["SC100"], "2004-01-01")):
            c.compared += 1
            try:
                rd(key, first)
                c.failed += 1
                c.fail(f"the verifier did not refuse a Smallcap 100 read of {key} from {first}")
            except RuntimeError:
                pass
        for key in (F_MASTER["SC100"], F_IDX_D25["SC100"]):
            c.compared += 1
            try:
                rd(key)
                c.failed += 1
                c.fail("a restricted file was registered without a first read date")
            except RuntimeError:
                pass
        READS.clear()
        READS.update(saved)
        for key, want in ((F_MASTER["SC100"], "2011-11-25"), (F_IDX_D25["SC100"], "2011-10-03")):
            c.compared += 1
            if APPROVED[key]["usable_from"] != want:
                c.failed += 1
                c.fail(f"the registry row of {key} carries no usable-from {want}")
        c.compared += 1
        if READS[F_MASTER["SC100"]]["first_date"] != "2011-11-25":
            c.failed += 1
            c.fail(f"the verifier read the Smallcap 100 Master from {READS[F_MASTER['SC100']]['first_date']}")
        for key in (F_IDX_D25["SC100"], F_IDX_D25C["SC100"]):
            if key in READS:
                c.compared += 1
                fd = READS[key]["first_date"]
                if fd is None or pd.Timestamp(fd) < SC100_PRICE_FROM:
                    c.failed += 1
                    c.fail(f"the verifier read the Smallcap 100 prices {key} from {fd}")
        c.compared += 1
        if (dec_m["label_SC100"] < "2011-11-25").any():
            c.failed += 1
            c.fail("a Smallcap 100 decision reads a Master row dated before 2011-11-25")
        for nm in ("decisions.csv", "decisions_r3.csv"):
            d0 = E.get(nm)
            if d0 is not None and "label_SC100" in d0.columns:
                c.compared += 1
                if (d0["label_SC100"].astype(str) < "2011-11-25").any():
                    c.failed += 1
                    c.fail(f"the engine's {nm} reads a Smallcap 100 Master row dated before 2011-11-25")
        for p in BK:
            c.compared += 1
            if min(D["books"][p]["V"]["cal"]) < SC100_PRICE_FROM:
                c.failed += 1
                c.fail(f"{p}: the calendar starts before the Smallcap 100 price restriction")
    run_check(C, "C-sc100-restriction", c_sc100)

    # ------------------------------------------------------------------ the frozen text's numbers and Step 1's file against the verifier's own derivation
    def c_frozen(c):
        fz = FROZEN[wname]
        for p in BK:
            f = D["facts"][(p, "full")]
            f3 = D["facts"][(p, "r3")]
            is7 = (wname == "w2" and p == "SCMO_0007")
            pairs = [("weeks", f["weeks"], fz["weeks_0007"] if is7 else fz["weeks"])]
            if not is7:
                pairs += [("first_state", f["first_state"], fz["first_state"]), ("weeks_IN", f["weeks_IN"], fz["weeks_IN"]),
                          ("weeks_OUT_BUY", f["weeks_OUT_BUY"], fz["weeks_OUT_BUY"]), ("weeks_OUT_SELL", f["weeks_OUT_SELL"], fz["weeks_OUT_SELL"]),
                          ("OUT_SELL_spells", f["OUT_SELL_spells"], fz["OUT_SELL_spells"]), ("k0", f["OUT_SELL_weeks_k0"], fz["k0"]),
                          ("k1", f["OUT_SELL_weeks_k1"], fz["k1"]), ("k2", f["OUT_SELL_weeks_k2"], fz["k2"]),
                          ("index_weeks", f["OUT_SELL_weeks_holding_an_index"], fz["index_weeks"]),
                          ("index_spells", f["OUT_SELL_spells_holding_an_index"], fz["index_spells"]), ("B_changes", f["B_changes_inside_OUT_SELL"], fz["B_changes"])]
                for r_, v_ in fz["trades"].items():
                    pairs.append((f"trades_due[{r_}]", f["trades_due"][r_], v_))
            r3 = fz["r3"]
            pairs += [("r3 weeks_OUT_SELL", f3["weeks_OUT_SELL"], r3["weeks_OUT_SELL"]), ("r3 index_weeks", f3["OUT_SELL_weeks_holding_an_index"], r3["index_weeks"]),
                      ("r3 k0", f3["OUT_SELL_weeks_k0"], r3["k0"]), ("r3 k1", f3["OUT_SELL_weeks_k1"], r3["k1"]), ("r3 k2", f3["OUT_SELL_weeks_k2"], r3["k2"])]
            for nm, mine, want in pairs:
                c.compared += 1
                if mine != want:
                    c.failed += 1
                    c.fail(f"{p} {nm}: verifier {mine!r} vs T15.md {want!r}")
            if wname == "w1":
                bt = D["baskets"][D["baskets"]["book"] == p]
                c.compared += 3
                if len(bt) != N_BASKETS_W1 or bt["session_date"].iloc[0] != "2014-09-01":
                    c.failed += 1
                    c.fail(f"{p}: {len(bt)} baskets T0 to END (T11 / Step 1: 19, the first on 2014-09-01)")
                if bt["available_date"].iloc[-1] != "2018-12-17":
                    c.failed += 1
                    c.fail(f"{p}: last basket effective {bt['available_date'].iloc[-1]} (T11: 2018-12-17)")
                if "2017-10-19" not in D["meta"][p]["sessions_without_any_d18_bar"]:
                    c.failed += 1
                    c.fail(f"{p}: 2017-10-19 has D18 bars for some stock (T11: none)")
        if STEP1 is None:
            c.notes.append("logs/step_1_spell_counts.json not found; not compared")
            return
        for p in BK:
            for window in ("full", "r3"):
                e = (STEP1["w1"]["full" if window == "full" else "r3"] if wname == "w1" else STEP1["w2"][p]["full" if window == "full" else "live"])
                f = D["facts"][(p, window)]
                for k_, v_ in e.items():
                    if k_ in ("rules", "reportable"):
                        continue
                    if k_ not in f:
                        continue
                    c.compared += 1
                    if f[k_] != v_:
                        c.failed += 1
                        c.fail(f"{p}|{window} {k_}: verifier {f[k_]!r} vs logs/step_1_spell_counts.json {v_!r}")
                for r_, v_ in e.get("rules", {}).items():
                    c.compared += 1
                    if f["trades_due"][r_] != v_["trades_from_regime_gold_and_B_changes"]:
                        c.failed += 1
                        c.fail(f"{p}|{window} rule {r_}: verifier {f['trades_due'][r_]} trades due vs Step 1 {v_}")
                c.compared += 1
                if not (f["round_trips"] >= 4 and f["OUT_SELL_spells"] >= 4):
                    c.failed += 1
                    c.fail(f"{p}|{window}: not reportable (fewer than 4 round trips or OUT-SELL spells)")
            if wname == "w1":
                eb = STEP1["baskets_w1"][p]
                bt = D["baskets"][D["baskets"]["book"] == p]
                c.compared += 2
                if eb["baskets_T0_to_END"] != len(bt):
                    c.failed += 1
                    c.fail(f"{p}: Step 1 counts {eb['baskets_T0_to_END']} baskets, verifier {len(bt)}")
                if eb["effective_dates"] not in (bt["available_date"].tolist(), bt["session_date"].tolist()):
                    c.failed += 1
                    c.fail(f"{p}: Step 1's effective basket dates differ from the verifier's")
    run_check(C, "C-frozen-counts", c_frozen)

    # ------------------------------------------------------------------ decisions, regimes, B, point-in-time
    def c_dec(c):
        for fn, mine_df in (("decisions.csv", dec_full), ("decisions_r3.csv", dec_r3)):
            ev = E.get(fn, c)
            if ev is None:
                continue
            ev = ev[ev["book"].isin(BK)].copy()
            ev["all_three_buy"] = ev["all_three_buy"].astype(str)
            mine = mine_df[mine_df["book"].isin(BK)].copy()
            mine["all_three_buy"] = mine["all_three_buy"].astype(str)
            compare_frames(c, mine, ev, ["book", "j"], num_cols=n_cols, str_cols=s_cols, tol=0.0)
    run_check(C, "C-dec", c_dec)

    def c_regimes(c):
        ev = E.get("regimes.csv", c)
        if ev is None:
            return
        ev = ev[ev["book"].isin(BK)]
        mine = dec_full[dec_full["book"].isin(BK)][["book", "decision_date", "decision_idx", "regime", "B", "k"]]
        compare_frames(c, mine, ev[["book", "decision_date", "decision_idx", "regime", "B", "k"]], ["book", "decision_date"], num_cols=["decision_idx", "k"],
                       str_cols=["regime", "B"], tol=0.0)
    run_check(C, "C-regimes", c_regimes)

    def c_pit(c):
        """V2: labels <= decision date, every trade after its decision (the next session), a basket change on a basket's availableDate session."""
        lcs = ["label_Nifty100", "label_MC100", "label_SC100", "label_MAUc1"]
        for fn in ("decisions.csv", "decisions_r3.csv"):
            ev = E.get(fn, c)
            if ev is None:
                continue
            for lc in lcs:
                if lc not in ev.columns:
                    c.miss(f"{fn} column {lc}")
                    continue
                ok = (ev[lc].astype(str) <= ev["decision_date"].astype(str)).values
                c.compared += len(ev)
                c.failed += int((~ok).sum())
                if (~ok).any():
                    c.fail("label after decision date: %s" % ev[~ok].iloc[0][["book", "j", "decision_date", lc]].to_dict())
            tdm = ev["trade_date"].notna()
            ok = (ev.loc[tdm, "trade_date"].astype(str) > ev.loc[tdm, "decision_date"].astype(str)).values
            c.compared += int(tdm.sum())
            c.failed += int((~ok).sum())
            if (~ok).any():
                c.fail("trade not after decision: %s" % ev.loc[tdm][~ok].iloc[0][["book", "j", "decision_date", "trade_date"]].to_dict())
        evd = E.get("decisions.csv")
        if tr_ev is not None and evd is not None:
            tr = tr_ev
            dd = tr[tr["dec_j"].notna()].copy()
            dd["dec_j"] = dd["dec_j"].astype(int)
            m = dd.merge(evd[["book", "j", "decision_date", "trade_date"]], left_on=["book", "dec_j"], right_on=["book", "j"], how="left")
            okk = m["decision_date"].notna() & (m["date"].astype(str) > m["decision_date"].astype(str)) & (m["date"].astype(str) == m["trade_date"].astype(str))
            c.compared += len(m)
            c.failed += int((~okk).sum())
            if (~okk).any():
                c.fail("a decision-driven trade is not on the session after its decision: %s" % m[~okk].iloc[0][["book", "run", "date", "dec_j"]].to_dict())
            keyset = set(zip(D["baskets"]["book"], D["baskets"]["session_date"].astype(str)))
            bc = tr[tr["kind"] == "basket_change"]
            okb = np.array([(b, str(d)) in keyset for b, d in zip(bc["book"], bc["date"])], dtype=bool)
            c.compared += len(bc)
            c.failed += int((~okb).sum())
            if (~okb).any():
                c.fail("basket change not on a basket's availableDate session: %s" % bc[~okb].iloc[0][["book", "run", "date"]].to_dict())
        for lc in lcs:
            ok = (dec_m[lc] <= dec_m["decision_date"]).values
            c.compared += len(dec_m)
            c.failed += int((~ok).sum())
        mt = dec_m["trade_date"].notna()
        ok = (dec_m.loc[mt, "trade_date"] > dec_m.loc[mt, "decision_date"]).values
        c.compared += int(mt.sum())
        c.failed += int((~ok).sum())
        for _, r in D["baskets"].iterrows():
            c.compared += 1
            cal_ = D["books"][r["book"]]["V"]["cal"]
            i = int(r["idx"])
            if cal_[i] < pd.Timestamp(r["available_date"]) or (i > 0 and cal_[i - 1] >= pd.Timestamp(r["available_date"])):
                c.failed += 1
                c.fail(f"basket {r.to_dict()}: effect session is not the first session on or after availableDate")
        c.compared += 1
        if any(m_["end"] != str(cal_end.date()) for m_ in D["meta"].values()):
            c.failed += 1
            c.fail(f"a book's calendar does not end at {cal_end.date()}")
    run_check(C, "C-pit", c_pit)

    def c_gold(c):
        """V4(e): the MAUc1 signal of every decision equals the SIGN of the weekly file D24 / D24b (and of the Master); the three index signs of every decision
        are those of the Master rows read as-of (D03), and decisions.csv carries them (C-dec)."""
        wk = load_mauc1_weekly(wname)
        gd, gsg = D["gmaster"]
        mm = pd.DataFrame({"review": pd.to_datetime(gd), "msign": gsg})
        j = mm.merge(wk[["review", "SIGN", "signal"]], on="review", how="inner")
        c.compared += len(j)
        bad = (j["msign"] != j["SIGN"]) | ((j["signal"] == 1.0) != (j["SIGN"] == "BUY"))
        c.failed += int(bad.sum())
        if bad.any():
            c.fail("Master_MAUc1 SIGN / weekly csv SIGN / signal disagree: %s" % j[bad].iloc[0].to_dict())
        c.notes.append(f"Master_MAUc1 rows {len(mm)}, weekly csv rows {len(wk)}, shared dates {len(j)}")
        wd = wk["review"].values
        for r in dec_full.itertuples():
            pos = int(np.searchsorted(wd, np.datetime64(pd.Timestamp(r.decision_date)), side="right") - 1)
            c.compared += 1
            if pos < 0 or int(wk["signal"].iloc[pos]) != r.g or wk["SIGN"].iloc[pos] != r.sign_MAUc1 or str(wk["review"].iloc[pos].date()) != r.label_MAUc1:
                c.failed += 1
                c.fail(f"g at {r.book} j={r.j} {r.decision_date}: Master {r.sign_MAUc1} (row {r.label_MAUc1}) vs weekly csv row {wk['review'].iloc[pos].date() if pos >= 0 else None}")
        for nm in INDICES:
            dates, sg, _ = D["masters"][nm]
            for r in dec_full.itertuples():
                lab = getattr(r, f"label_{nm}")
                pos = int(np.searchsorted(dates, np.datetime64(pd.Timestamp(r.decision_date)), side="right") - 1)
                c.compared += 1
                if str(pd.Timestamp(dates[pos]).date()) != lab or sg[pos] != getattr(r, f"sign_{nm}"):
                    c.failed += 1
                    c.fail(f"{nm} sign at {r.book} j={r.j}: Master row {pd.Timestamp(dates[pos]).date()} {sg[pos]} vs decision {lab} {getattr(r, f'sign_{nm}')}")
    run_check(C, "C-signals-D03-D24", c_gold)

    # ------------------------------------------------------------------ V3 and the index bars
    def c_tie(c):
        """V3: at every Master row a decision uses, the Index column equals the daily index close (D25 before 2019-01-01 in W2, else the window's file) on the
        label date, all three indices; no label falls on a date without a bar."""
        tie = D["tie"][D["tie"]["book"].isin(BK)]
        c.compared += len(tie)
        nob = tie["close"].isna()
        bad = nob | (tie["rel"].fillna(np.inf) > TOL)
        c.failed += int(bad.sum())
        if bad.any():
            c.fail("Master Index differs from the daily index close: %s" % tie[bad].iloc[0].to_dict())
        c.worst_rel = float(tie["rel"].replace([np.inf], np.nan).max(skipna=True)) if len(tie) else 0.0
        A = E.get("audit.json", c)
        if A is not None:
            v3 = A.get("v3", {})
            c.compared += 3
            if v3.get("pass") is not True:
                c.failed += 1
                c.fail(f"audit.json v3.pass = {v3.get('pass')!r}")
            if v3.get("violations") != 0:
                c.failed += 1
                c.fail(f"audit.json v3.violations = {v3.get('violations')!r}")
            if v3.get("labels_without_an_index_bar") != 0:
                c.failed += 1
                c.fail(f"audit.json v3.labels_without_an_index_bar = {v3.get('labels_without_an_index_bar')!r}")
        c.notes.append(f"{len(tie)} (book, label, index) ties; {tie['label'].nunique() if len(tie) else 0} distinct label dates per index set")
    run_check(C, "C-v3-index-tie", c_tie)

    def c_bars(c):
        """Index sessions with no bar (reported), the engine's lists of them, and every recorded trade that holds or buys an index has a bar for it."""
        A = E.get("audit.json", c)
        for p in BK:
            nb = D["nobar"][p]
            c.notes.append(f"{p}: sessions without an index bar " + "; ".join(f"{nm} {nb['full'][nm]}" for nm in INDICES))
            if A is not None:
                a = A.get("books", {}).get(p)
                if a is None:
                    c.miss(f"{p} in audit.json")
                    continue
                for key, mine in (("index_sessions_without_a_bar", nb["full"]), ("r3_index_sessions_without_a_bar", nb["r3"])):
                    if key in a:
                        c.compared += 1
                        if a[key] != mine:
                            c.failed += 1
                            c.fail(f"{p} {key}: verifier {mine} vs audit.json {a[key]}")
        if tr_ev is not None:
            n_idx = 0
            for p in BK:
                bar = D["books"][p]["IX"]["bar"]
                t = tr_ev[tr_ev["book"] == p]
                for k, nm in enumerate(INDICES):
                    inv = t[(t[f"{nm}_before"].abs() > 0) | (t[f"{nm}_after"].abs() > 0)]
                    n_idx += len(inv)
                    c.compared += len(inv)
                    ii = np.array([date_idx[p][d] for d in inv["date"]], dtype=int)
                    nb_ = ~bar[ii, k] if len(ii) else np.zeros(0, dtype=bool)
                    c.failed += int(nb_.sum())
                    if nb_.any():
                        c.fail(f"{p}: a trade holds / buys {nm} on {inv['date'].iloc[int(np.argmax(nb_))]}, a session with no bar")
            c.notes.append(f"{n_idx} (trade, index) legs checked for a bar on the trade session")
        else:
            E.get("trades.csv", c)
    run_check(C, "C-index-bars", c_bars)

    # ------------------------------------------------------------------ NAVs and statistics
    def c_stats(c):
        if est_all is None:
            E.get("stats.csv", c)
            return
        for col in NUMS + INTS + CNT + ["window", "variant", "cash"]:
            if col not in est_all.columns:
                c.miss(f"stats.csv column {col}")
        keys = ["book", "window", "variant", "cash", "cost_bps", "run"]
        compare_frames(c, mst[keys + NUMS + INTS + CNT], est_all[keys + NUMS + INTS + CNT], keys, num_cols=NUMS + INTS + CNT)
    run_check(C, "C-stats", c_stats)

    def c_nav(c):
        if env_all is None:
            E.get("daily_nav.csv", c)
            return
        compare_frames(c, mnv, env_all, ["book", "date", "cost_bps", "run"], num_cols=["nav"])
    run_check(C, "C-nav", c_nav)

    rb_ev = E.get("robustness.csv")
    rn_ev = E.get("robust_nav.csv")

    def c_robust_stats(c):
        if rb_ev is None:
            E.get("robustness.csv", c)
            return
        ev = rb_ev[rb_ev["book"].isin(BK)].copy()
        ev["cost_bps"] = r4(ev["cost_bps"])
        mine = D["robust_stats"].copy()
        mine["cost_bps"] = r4(mine["cost_bps"])
        keys = ["book", "window", "variant", "cost_bps", "run"]
        compare_frames(c, mine[keys + NUMS + INTS + CNT], ev[keys + NUMS + INTS + CNT], keys, num_cols=NUMS + INTS + CNT)
        c.compared += 1
        r2 = ev[ev["variant"] == "r2_liq"]
        if len(r2) == 0 or not r2["cash"].astype(str).str.startswith("liq").all() or not (ev[ev["variant"] != "r2_liq"]["cash"].astype(str) == "lbes").all():
            c.failed += 1
            c.fail("robustness.csv cash labels: r2_liq must be a LIQUIDCASE row and every other variant lbes")
        c.notes.append("variants: " + ", ".join(sorted(set(mine["variant"]))))
    run_check(C, "C-robust-stats", c_robust_stats)

    def c_robust_nav(c):
        if rn_ev is None:
            E.get("robust_nav.csv", c)
            return
        ev = rn_ev[rn_ev["book"].isin(BK)].copy()
        ev["cost_bps"] = r4(ev["cost_bps"])
        ev["date"] = ev["date"].astype(str)
        mine = D["robust_nav"].copy()
        mine["cost_bps"] = r4(mine["cost_bps"])
        compare_frames(c, mine, ev, ["book", "window", "variant", "cost_bps", "run", "date"], num_cols=["nav"])
    run_check(C, "C-robust-nav", c_robust_nav)

    def c_parent_nav(c):
        """W1: the rebuilt parent NAV file: base 1.0 at T0 in every column, no '#' line, the caption in its sidecar, numbers equal the verifier's."""
        if wname != "w1":
            c.notes.append("W1 only")
            return
        pn = E.get("parent_nav_2014-09-01_2019-01-02.csv", c)
        side = E.get("parent_nav_2014-09-01_2019-01-02.md", c)
        if side is not None:
            c.compared += 1
            if "not validated against a published NAV before 2019-01-02" not in side or "rebuilt from the parent's baskets and Eikon prices" not in side:
                c.failed += 1
                c.fail("the sidecar caption of the rebuilt parent NAV is missing or altered")
        p_ = E.path("parent_nav_2014-09-01_2019-01-02.csv")
        if p_ is not None:
            c.compared += 1
            if p_.read_text(encoding="utf-8").lstrip().startswith("#"):
                c.failed += 1
                c.fail("the parent NAV csv starts with a '#' comment line")
        if pn is None:
            return
        pn = pn[pn["book"].isin(BK)].copy()
        pn["date"] = pn["date"].astype(str)
        cmap = {"hold_parent_0bps": ("hold_parent", 0.0), "hold_parent_20.8bps": ("hold_parent", 20.8)}
        cmap.update({f"{r}_20.8bps": (r, 20.8) for r in RULES})
        first = pn.sort_values("date").groupby("book").head(1)
        for col in cmap:
            if col not in pn.columns:
                c.miss(f"parent NAV column {col}")
                continue
            c.compared += len(first)
            bad = ((first[col].astype(float) - 1.0).abs() > 1e-12)
            c.failed += int(bad.sum())
            if bad.any():
                c.fail(f"parent NAV {col}: first row is not 1.0")
            run, bps = cmap[col]
            m = mnv[(mnv["run"] == run) & (mnv["cost_bps"] == bps)][["book", "date", "nav"]].rename(columns={"nav": col})
            compare_frames(c, m, pn[["book", "date", col]], ["book", "date"], num_cols=[col])
    run_check(C, "C-parent-nav", c_parent_nav)

    def c_cmix(c):
        ev = E.get("constant_mix_params.csv", c)
        if ev is None:
            return
        ev = ev[ev["book"].isin(BK)]
        rows = []
        for p in BK:
            for r in RULES:
                f_ = D["mix_params"][(p, r)]
                rows.append(dict(book=p, rule=r, f_parent=f_[0], f_goldbees=f_[1], f_cash=f_[2], **{f"f_{nm}": f_[3][k] for k, nm in enumerate(INDICES)}))
        cols = ["f_parent", "f_goldbees", "f_cash"] + [f"f_{nm}" for nm in INDICES]
        compare_frames(c, pd.DataFrame(rows), ev[["book", "rule"] + cols], ["book", "rule"], num_cols=cols, tol=1e-12)
        c.compared += len(rows)
        for rw in rows:
            if abs(rw["f_parent"] + rw["f_goldbees"] + rw["f_cash"] + sum(rw[f"f_{nm}"] for nm in INDICES) - 1.0) > 1e-12:
                c.failed += 1
                c.fail(f"constant-mix shares of {rw['book']} {rw['rule']} do not sum to 1")
    run_check(C, "C-cmix-params", c_cmix)

    def c_ledger(c):
        ev = E.get("regime_ledger.csv", c)
        if ev is None:
            return
        ev = ev[ev["book"].isin(BK)]
        led = D["ledger"]
        r3_present = (ev["window"] == "r3").any()
        led_cmp = led if r3_present else led[led["window"] == "full"]
        num = ["k", "weeks", "parent_return", "goldbees_return", "cash_return"] + [f"{nm}_return" for nm in INDICES] + [f"ret_{r}" for r in RULES]
        s_ = ["B", "first_decision", "last_decision", "a_session", "b_session", "entered_from", "exited_to"]
        compare_frames(c, led_cmp[led_cmp["book"].isin(BK)], ev, ["window", "book", "level", "spell_no", "stretch_no"], num_cols=num, str_cols=s_)
        if not r3_present:
            c.notes.append("regime_ledger.csv has no r3 rows (evidence_contract.md does not promise them for T15); only the full window's ledger was compared")
    run_check(C, "C-ledger", c_ledger)

    # ------------------------------------------------------------------ trades and positions
    def c_trades(c):
        """Every recorded trade of the eight rules and hold_parent at the three costs: date, kind, the target shares, V, traded, cost, the before and after
        values of every line (stocks, GOLDBEES, cash, each index), V_after, NAV after, basket in force, the decision that caused it; the counts per (book, cost,
        run); the decision-driven trades of each rule against the due trades counted from the states alone."""
        if tr_ev is None:
            E.get("trades.csv", c)
            return
        tr = tr_ev
        mt_all = D["trades"].copy()
        mt_all["cost_bps"] = r4(mt_all["cost_bps"])
        mt_all["seq"] = mt_all.groupby(["book", "cost_bps", "run"]).cumcount()
        tr = tr.copy()
        tr["seq"] = tr.groupby(["book", "cost_bps", "run"]).cumcount()
        keys = ["book", "cost_bps", "run", "seq"]
        mt_all["dec_j"] = mt_all["dec_j"].astype(float)
        tr["basket_eff"] = tr["basket_eff"].astype(str)
        compare_frames(c, mt_all[keys + TRADE_NUM + TRADE_STR], tr[keys + TRADE_NUM + TRADE_STR], keys, num_cols=TRADE_NUM, str_cols=TRADE_STR)
        mc = mt_all.groupby(["book", "cost_bps", "run"]).size().rename("n").reset_index()
        full_idx = pd.MultiIndex.from_product([BK, [round(x, 4) for x in COSTS], TRADE_RUNS], names=["book", "cost_bps", "run"])
        mc = mc.set_index(["book", "cost_bps", "run"]).reindex(full_idx, fill_value=0).reset_index()
        ec = tr.groupby(["book", "cost_bps", "run"]).size().rename("n").reset_index()
        ec = ec.set_index(["book", "cost_bps", "run"]).reindex(full_idx, fill_value=0).reset_index()
        compare_frames(c, mc, ec, ["book", "cost_bps", "run"], num_cols=["n"], tol=0.0)
        extra = sorted(set(tr["run"].unique()) - set(TRADE_RUNS))
        c.compared += 1
        if extra:
            c.failed += 1
            c.fail(f"runs in trades.csv the verifier does not know: {extra}")
        for p in BK:
            for r in RULES:
                for cst in COSTS:
                    c.compared += 1
                    n_dec = int(((tr["book"] == p) & (tr["run"] == r) & (tr["cost_bps"] == round(cst, 4)) & tr["dec_j"].notna()).sum())
                    if n_dec != D["facts"][(p, "full")]["trades_due"][r]:
                        c.failed += 1
                        c.fail(f"{p} {r} {cst}: {n_dec} decision-driven trades recorded, {D['facts'][(p, 'full')]['trades_due'][r]} due from the states")
    run_check(C, "C-trades", c_trades)

    ps_ev = E.get("positions.csv")

    def c_positions(c):
        if ps_ev is None:
            E.get("positions.csv", c)
            return
        ev = ps_ev[(ps_ev["units"] != 0) & ps_ev["book"].isin(BK)].copy()
        ev["cost_bps"] = r4(ev["cost_bps"])
        ev["date"] = ev["date"].astype(str)
        mine = D["positions"].copy()
        mine["cost_bps"] = r4(mine["cost_bps"])
        mine = mine[mine["units"] != 0]
        compare_frames(c, mine, ev[["book", "window", "cost_bps", "run", "date", "instrument", "units"]], ["book", "cost_bps", "run", "date", "instrument"], num_cols=["units"],
                       str_cols=["window"])
    run_check(C, "C-positions", c_positions)

    # ------------------------------------------------------------------ V5: identities on the evidence's own numbers
    def c_v5_identities(c):
        """cost = traded x bps / 2 / 1e4; value conservation (the lines before sum to V, after to V - cost); a full trade leaves every line at the trade's
        target share of the value after cost; a D1 partial basket trade (0 < e < 1, -half) leaves GOLDBEES, cash and the indices untouched and the stock part
        at stock_before - cost; after every entry into OUT-SELL in -half stock = GOLDBEES = 0.5 of the value after cost; a 0-cost trade leaves the value unchanged."""
        if tr_ev is None:
            E.get("trades.csv", c)
            return
        tr = tr_ev
        bps = tr["cost_bps"].astype(float).values
        Vv = tr["V"].astype(float).values
        cost = tr["cost"].astype(float).values
        traded = tr["traded"].astype(float).values
        before = sum(tr[x].astype(float).values for x in ["stock_before", "gold_before", "cash_before"] + [f"{nm}_before" for nm in INDICES])
        after = sum(tr[x].astype(float).values for x in ["stock_after", "gold_after", "cash_after"] + [f"{nm}_after" for nm in INDICES])
        aft = Vv - cost
        n = len(tr)
        c.compared += 5 * n
        worst = 0.0

        def flag(mask, what):
            nonlocal worst
            if mask.any():
                c.failed += int(mask.sum())
                c.fail(f"{what}: first at {tr[mask].iloc[0][['book', 'run', 'cost_bps', 'date', 'kind']].to_dict()}")
        flag(np.abs(cost - traded * bps / 2.0 / 10000.0) > TOL_ID * np.maximum(1.0, Vv), "cost != traded x bps/2/1e4")
        d1 = np.abs(after - aft) / Vv
        d2 = np.abs(before - Vv) / Vv
        d3 = np.abs(tr["V_after"].astype(float).values - aft) / Vv
        worst = max(worst, float(d1.max()), float(d2.max()), float(d3.max()))
        flag(d1 > TOL_ID, "value not conserved (lines after != V - cost)")
        flag(d2 > TOL_ID, "lines before != V")
        flag(d3 > TOL_ID, "V_after != V - cost")
        flag((bps == 0.0) & ((cost != 0) | (np.abs(after - Vv) > TOL_ID * Vv)), "a 0-cost trade with a cost or a value jump")
        e_a = tr["e_after"].astype(float).values
        partial = (tr["kind"].values == "basket_change") & (e_a > 0) & (e_a < 1) & tr["run"].isin(RULES).values
        full = ~partial
        legs = [("stock", e_a), ("gold", tr["gold_share"].astype(float).values), ("cash", tr["cash_share"].astype(float).values)] + \
               [(nm, tr[f"w_{nm}"].astype(float).values) for nm in INDICES]
        c.compared += len(legs) * n
        for nm, share in legs:
            dev = np.abs(tr[f"{nm}_after"].astype(float).values - share * aft) / Vv
            dev = np.where(full, dev, 0.0)
            worst = max(worst, float(dev.max()))
            flag(dev > TOL_ID, f"post-trade {nm} leg differs from the trade's target share x (V - cost)")
        if partial.any():
            dd = np.zeros(n)
            for nm in ["gold", "cash"] + INDICES:
                dd = np.maximum(dd, np.abs(tr[f"{nm}_after"].astype(float).values - tr[f"{nm}_before"].astype(float).values) / Vv)
            dd = np.maximum(dd, np.abs(tr["stock_after"].astype(float).values - (tr["stock_before"].astype(float).values - cost)) / Vv)
            dd = np.where(partial, dd, 0.0)
            worst = max(worst, float(dd.max()))
            flag(dd > TOL_ID, "D1 basket change inside the half regime changes GOLDBEES / cash / an index or the stock part is not stock_before - cost")
        hin = tr["run"].str.endswith("-half").values & (tr["kind"].values == "regime_in")
        c.compared += int(hin.sum())
        dd = np.maximum.reduce([np.abs(tr["stock_after"].astype(float).values - 0.5 * aft), np.abs(tr["gold_after"].astype(float).values - 0.5 * aft),
                                np.abs(tr["cash_after"].astype(float).values)]) / Vv
        dd = np.where(hin, dd, 0.0)
        worst = max(worst, float(dd.max()))
        flag(dd > TOL_ID, "entry into OUT-SELL in a -half rule: stock / GOLDBEES / cash are not 0.5 / 0.5 / 0 of the value after cost")
        c.worst_rel = max(c.worst_rel, worst)
        c.compared += 2
        if int(partial.sum()) == 0 or int(hin.sum()) == 0:
            c.failed += 1
            c.fail("no D1 basket change / no -half entry found in the evidence (the check compared nothing)")
        c.notes.append(f"{int(partial.sum())} D1 partial basket trades and {int(hin.sum())} -half entries checked; worst_rel = largest deviation (of V)")
    run_check(C, "C-v5-identities", c_v5_identities)

    def c_v5_idx(c):
        """V5 for -idx: after every trade into or inside OUT-SELL each index of B and cash = 1/(k+1) of the value after cost, parent and GOLDBEES 0 (B and k from
        the verifier's own decisions at the trade's decision j); outside OUT-SELL no index; IN holds the parent only, OUT-BUY the base sleeve; the decisions
        that carry a trade are exactly those the states call for (regime change, or a B change inside OUT-SELL), with the kind the change calls for."""
        if tr_ev is None:
            E.get("trades.csv", c)
            return
        t = tr_ev[tr_ev["run"].isin(IDX_RULES)].copy()
        dm = dec_full[["book", "j", "regime", "k", "buy_Nifty100", "buy_MC100", "buy_SC100", "trade_date"]].rename(columns={"trade_date": "tdate"})
        m = t.merge(dm, left_on=["book", "dec_j"], right_on=["book", "j"], how="left")
        V_ = m["V"].astype(float).values
        aft = V_ - m["cost"].astype(float).values
        hasj = m["dec_j"].notna().values
        c.compared += len(m)
        unmatched = hasj & m["regime"].isna().values
        if unmatched.any():
            c.failed += int(unmatched.sum())
            c.fail("an -idx trade carries a decision index with no decision")
        reg = m["regime"].fillna("IN").values
        k = m["k"].fillna(0).astype(int).values
        gb = np.where(m["run"].str.startswith("50").values, 0.5, 0.8)
        n_sell = 0
        worst = 0.0
        bad_rows = []
        for i in range(len(m)):
            r = m.iloc[i]
            a = float(aft[i])
            stock, gold, cash = float(r["stock_after"]), float(r["gold_after"]), float(r["cash_after"])
            ixv = [float(r[f"{nm}_after"]) for nm in INDICES]
            buy = [int(r["buy_Nifty100"]) if hasj[i] else 0, int(r["buy_MC100"]) if hasj[i] else 0, int(r["buy_SC100"]) if hasj[i] else 0]
            if reg[i] == "OUT-SELL" and hasj[i]:
                n_sell += 1
                share = a / (k[i] + 1)
                exp = [0.0, 0.0, share] + [share if buy[q] else 0.0 for q in range(3)]
                got = [stock, gold, cash] + ixv
                dev = max(abs(x - y) for x, y in zip(got, exp)) / V_[i]
            elif reg[i] == "OUT-BUY" and hasj[i]:
                exp = [0.0, gb[i] * a, (1 - gb[i]) * a, 0.0, 0.0, 0.0]
                dev = max(abs(x - y) for x, y in zip([stock, gold, cash] + ixv, exp)) / V_[i]
            else:
                exp = [a, 0.0, 0.0, 0.0, 0.0, 0.0]
                dev = max(abs(x - y) for x, y in zip([stock, gold, cash] + ixv, exp)) / V_[i]
            worst = max(worst, dev)
            if dev > TOL_ID:
                bad_rows.append((i, dev))
        c.worst_rel = max(c.worst_rel, worst)
        if bad_rows:
            c.failed += len(bad_rows)
            r = m.iloc[bad_rows[0][0]]
            c.fail(f"-idx post-trade legs differ from the regime's split by {bad_rows[0][1]:.2e} of V at {r['book']} {r['run']} {r['cost_bps']} {r['date']} {r['kind']} ({r['regime']}, k={r['k']})")
        c.compared += 1
        if n_sell == 0:
            c.failed += 1
            c.fail("no -idx trade into or inside OUT-SELL found (the check compared nothing)")
        # trades expected from the states alone
        n_exp = 0
        for p in BK:
            d_ = dec_full[dec_full["book"] == p].reset_index(drop=True)
            D_ = len(d_)
            regs = d_["regime"].tolist()
            Bs = d_["B"].tolist()
            exp = {}
            for j in range(1, D_ - 1):
                if (regs[j] == "OUT-SELL") != (regs[j - 1] == "OUT-SELL"):
                    kind = "regime_in" if regs[j] == "OUT-SELL" else "regime_out"
                elif regs[j] == "OUT-SELL" and Bs[j] != Bs[j - 1]:
                    kind = "index_set_change"
                elif regs[j] != regs[j - 1]:
                    kind = "switch_in" if regs[j] == "IN" else "switch_out"
                else:
                    continue
                exp[j] = (kind, d_["trade_date"].iloc[j])
            for r in IDX_RULES:
                for cst in COSTS:
                    tt = t[(t["book"] == p) & (t["run"] == r) & (t["cost_bps"] == round(cst, 4)) & t["dec_j"].notna()]
                    got = {int(a): (b, str(d)) for a, b, d in zip(tt["dec_j"], tt["kind"], tt["date"])}
                    c.compared += max(len(exp), len(got))
                    n_exp += len(exp)
                    if got != exp:
                        c.failed += len(set(got.items()) ^ set(exp.items()))
                        miss = sorted(set(exp) - set(got))
                        extra = sorted(set(got) - set(exp))
                        c.fail(f"{p} {r} {cst}: the recorded decision-driven trades differ from those the states call for (not recorded: j={miss[:4]}, unexpected: j={extra[:4]}, "
                               f"or a kind / date differs)")
        c.notes.append(f"{n_sell} -idx trades into or inside OUT-SELL checked; {n_exp} trades expected from the states")
    run_check(C, "C-v5-idx", c_v5_idx)

    def c_v5_units(c):
        """Units: no index line outside the -idx rules or outside OUT-SELL; no GOLDBEES, parent stock or non-B index in -idx's OUT-SELL; and the units of
        positions.csv held constant between trades reproduce the evidence NAV on every session (units x the verifier's own closes)."""
        if ps_ev is None or tr_ev is None or env_all is None:
            for nm_, o_ in (("positions.csv", ps_ev), ("trades.csv", tr_ev), ("daily_nav.csv", env_all)):
                if o_ is None:
                    E.get(nm_, c)
            return
        ps = ps_ev[ps_ev["book"].isin(BK) & (ps_ev["units"] != 0) & (r4(ps_ev["cost_bps"]) == HEADLINE_COST)].copy()
        ps["date"] = ps["date"].astype(str)
        c.compared += len(ps)
        bad = ps["instrument"].str.startswith("IDX_") & ~ps["run"].isin(IDX_RULES)
        c.failed += int(bad.sum())
        if bad.any():
            c.fail(f"an index line held by a rule that has none: {ps[bad].iloc[0].to_dict()}")
        pos_by = {}
        for (b, run, d), g_ in ps.groupby(["book", "run", "date"]):
            pos_by[(b, run, d)] = dict(zip(g_["instrument"], g_["units"].astype(float)))
        dm = dec_full.set_index(["book", "j"])
        n_chk = 0
        for p in BK:
            V = D["books"][p]["V"]
            S_idx = {nm: i for i, nm in enumerate(V["S"])}
            cal_n = len(V["cal"])
            nv_p = env_all[(env_all["book"] == p) & (env_all["cost_bps"] == HEADLINE_COST)]
            for r in RULES:
                tt = tr_ev[(tr_ev["book"] == p) & (tr_ev["run"] == r) & (tr_ev["cost_bps"] == HEADLINE_COST)].sort_values("idx")
                ev_nav = nv_p[nv_p["run"] == r].set_index("date")["nav"].reindex([str(d.date()) for d in V["cal"]]).values.astype(float)
                if np.isnan(ev_nav).any():
                    c.miss(f"{p} {r}: evidence NAV does not cover the calendar")
                    continue
                cur_reg, cur_dr = "IN", None
                idxs = [int(x) for x in tt["idx"]]
                for q, (row, i0) in enumerate(zip(tt.itertuples(), idxs)):
                    pos = pos_by.get((p, r, row.date))
                    c.compared += 1
                    if pos is None:
                        c.miss(f"positions after the trade {p} {r} {row.date}")
                        continue
                    i1 = idxs[q + 1] if q + 1 < len(idxs) else cal_n
                    sh = np.zeros(len(V["S"]))
                    gu = cu = 0.0
                    iu = np.zeros(3)
                    unknown = []
                    for nm, u in pos.items():
                        if nm in S_idx:
                            sh[S_idx[nm]] = u
                        elif nm == "GOLDBEES":
                            gu = u
                        elif nm == "LBES":
                            cu = u
                        elif nm.startswith("IDX_") and nm[4:] in INDICES:
                            iu[INDICES.index(nm[4:])] = u
                        else:
                            unknown.append(nm)
                    if unknown:
                        c.failed += 1
                        c.fail(f"positions.csv holds an unknown instrument {unknown[:3]} for {p} {r} {row.date}")
                        continue
                    # (a) the regime after the trade from the verifier's own decisions (basket trades keep the regime of the last decision-driven trade)
                    if r in IDX_RULES:
                        if not np.isnan(row.dec_j):
                            cur_reg, cur_dr = dm.loc[(p, int(row.dec_j)), "regime"], dm.loc[(p, int(row.dec_j))]
                        c.compared += 1
                        if cur_reg == "OUT-SELL":
                            want = {f"IDX_{nm}" for nm in INDICES if cur_dr[f"buy_{nm}"]}
                            gotx = {nm for nm in pos if nm.startswith("IDX_")}
                            if pos.get("GOLDBEES", 0.0) != 0 or (sh != 0).any() or gotx != want:
                                c.failed += 1
                                c.fail(f"-idx {p} {r} {row.date}: in OUT-SELL the book holds GOLDBEES / stocks or the index set {sorted(gotx)} is not B {sorted(want)}")
                        else:
                            if any(nm.startswith("IDX_") for nm in pos):
                                c.failed += 1
                                c.fail(f"-idx {p} {r} {row.date}: an index line outside OUT-SELL ({cur_reg})")
                    # (b) units constant between trades: units x the verifier's closes equal the evidence NAV on [i0, i1)
                    seg = V["Cn"][i0:i1] @ sh + V["gc"][i0:i1] * gu + V["L"][i0:i1] * cu + V["ixC"][i0:i1] @ iu
                    rr = np.abs(seg - ev_nav[i0:i1]) / np.abs(ev_nav[i0:i1])
                    c.compared += len(seg)
                    n_chk += len(seg)
                    c.worst_rel = max(c.worst_rel, float(rr.max()))
                    if (rr > TOL).any():
                        c.failed += int((rr > TOL).sum())
                        c.fail(f"units held after the trade {p} {r} {row.date} do not reproduce the evidence NAV (rel {rr.max():.2e} at session {i0 + int(np.argmax(rr))})")
        c.notes.append(f"{n_chk} session NAVs rebuilt from positions.csv units x closes")
    run_check(C, "C-v5-units", c_v5_units)

    # ------------------------------------------------------------------ V4
    def c_v4a(c):
        """V4(a): the six T14 rules and hold_parent (3 costs) against T14's stored daily_nav.csv, trades.csv and decisions.csv, relative 1e-12."""
        base = T14_EVIDENCE / wname
        runs = RULES6 + ["hold_parent"]
        p_nav, p_tr, p_dec = base / "daily_nav.csv", base / "trades.csv", base / "decisions.csv"
        for pth in (p_nav, p_tr, p_dec):
            if not pth.exists():
                c.miss(str(pth))
        if p_nav.exists():
            st = pd.read_csv(p_nav, usecols=["book", "date", "cost_bps", "run", "nav"])
            st = st[st["book"].isin(BK) & st["run"].isin(runs)].copy()
            st["cost_bps"] = r4(st["cost_bps"])
            st["date"] = st["date"].astype(str)
            mine = mnv[mnv["run"].isin(runs) & mnv["book"].isin(BK)]
            compare_frames(c, mine, st[["book", "date", "cost_bps", "run", "nav"]], ["book", "date", "cost_bps", "run"], num_cols=["nav"], tol=TOL_REG)
            c.notes.append(f"{len(st)} stored NAV rows of T14 ({', '.join(runs)}) at 3 costs; relative tolerance {TOL_REG}")
        if p_tr.exists():
            st = pd.read_csv(p_tr)
            st = st[st["book"].isin(BK) & st["run"].isin(runs)].copy()
            st["cost_bps"] = r4(st["cost_bps"])
            st["seq"] = st.groupby(["book", "cost_bps", "run"]).cumcount()
            st["basket_eff"] = st["basket_eff"].astype(str)
            mt = D["trades"][D["trades"]["run"].isin(runs) & D["trades"]["book"].isin(BK)].copy()
            mt["cost_bps"] = r4(mt["cost_bps"])
            mt["seq"] = mt.groupby(["book", "cost_bps", "run"]).cumcount()
            mt["dec_j"] = mt["dec_j"].astype(float)
            num = ["idx", "e_after", "V", "traded", "cost", "stock_before", "gold_before", "cash_before", "stock_after", "gold_after", "cash_after", "nav_close_after", "dec_j"]
            keys = ["book", "cost_bps", "run", "seq"]
            compare_frames(c, mt[keys + num + TRADE_STR], st[keys + num + TRADE_STR], keys, num_cols=num, str_cols=TRADE_STR, tol=TOL_REG)
            c.notes.append(f"{len(st)} stored trades of T14 compared")
        if p_dec.exists():
            st = pd.read_csv(p_dec)
            st = st[st["book"].isin(BK)].copy()
            cols = ["decision_date", "decision_idx", "state", "sign_Nifty100", "sign_MC100", "sign_SC100", "label_Nifty100", "label_MC100", "label_SC100",
                    "sign_MAUc1", "label_MAUc1", "g", "trade_date", "regime"] + [f"{a}_{r}" for r in RULES6 for a in ("e", "gw")]
            a = dec_full[dec_full["book"].isin(BK)][["book", "j"] + cols].copy()
            b = st[["book", "j"] + cols].copy()
            for df_ in (a, b):
                df_["trade_date"] = df_["trade_date"].astype(object).where(df_["trade_date"].notna(), "<NA>").astype(str)
            numc = ["decision_idx", "state", "g"] + [f"{x}_{r}" for r in RULES6 for x in ("e", "gw")]
            compare_frames(c, a, b, ["book", "j"], num_cols=numc, str_cols=[x for x in cols if x not in numc], tol=0.0)
    run_check(C, "C-v4a-regression-T14", c_v4a)

    def c_v4b(c):
        for r in D["v4b"]:
            if r["book"] not in BK:
                continue
            c.compared += r["sessions"]
            c.worst_rel = max(c.worst_rel, r["max_rel"])
            if r["max_rel"] > TOL_ID:
                c.failed += 1
                c.fail(f"{r['book']} {r['rule']}: with every index priced at the cash level and cost 0, -idx differs from -liq by {r['max_rel']:.2e}")
    run_check(C, "C-v4b-idx-priced-as-cash", c_v4b)

    def c_v4c(c):
        """V4(c): -idx equals -liq at 20.8 bps on every session before the first trade into an index (the verifier's own runs, and the evidence's NAVs with the
        evidence's own first index trade)."""
        for r in D["v4c"]:
            if r["book"] not in BK:
                continue
            c.compared += r["sessions"]
            c.worst_rel = max(c.worst_rel, r["max_rel"])
            if r["max_rel"] > TOL_ID:
                c.failed += 1
                c.fail(f"{r['book']} {r['rule']}: -idx differs from -liq by {r['max_rel']:.2e} before its first index trade")
        if env_all is None or tr_ev is None:
            return
        for p in BK:
            cal_ = [str(d.date()) for d in D["books"][p]["V"]["cal"]]
            nv = env_all[(env_all["book"] == p) & (env_all["cost_bps"] == HEADLINE_COST)]
            for r in IDX_RULES:
                tt = tr_ev[(tr_ev["book"] == p) & (tr_ev["run"] == r) & (tr_ev["cost_bps"] == HEADLINE_COST)]
                held = tt[(tt["Nifty100_after"] > 0) | (tt["MC100_after"] > 0) | (tt["SC100_after"] > 0)]
                i1 = int(held["idx"].min()) if len(held) else len(cal_)
                c.compared += 1
                if i1 != D["idx_first_trade"][(p, r)]:
                    c.failed += 1
                    c.fail(f"{p} {r}: the evidence's first index trade is on session {i1}, the verifier's on {D['idx_first_trade'][(p, r)]}")
                a_ = nv[nv["run"] == r].set_index("date")["nav"].reindex(cal_).values.astype(float)[:i1]
                b_ = nv[nv["run"] == r[:2] + "-liq"].set_index("date")["nav"].reindex(cal_).values.astype(float)[:i1]
                c.compared += len(a_)
                rr = np.abs(a_ - b_) / np.abs(b_) if len(a_) else np.zeros(1)
                c.worst_rel = max(c.worst_rel, float(np.nanmax(rr)))
                if np.isnan(rr).any() or (rr > TOL_ID).any():
                    c.failed += 1
                    c.fail(f"{p} {r}: the evidence's -idx and -liq NAVs differ before the first index trade (max rel {np.nanmax(rr):.2e})")
    run_check(C, "C-v4c-idx-equals-liq", c_v4c)

    def c_one_instrument(c):
        for p in BK:
            for nm, d_ in D["one_instrument"][p]:
                c.compared += 1
                c.worst_rel = max(c.worst_rel, d_)
                if d_ > TOL_ID:
                    c.failed += 1
                    c.fail(f"{p} {nm}: always-in 0-cost one-instrument NAV differs from close / first close by {d_:.2e}")
    run_check(C, "C-v4f-one-instrument", c_one_instrument)

    def c_g0(c):
        """W2: G0 (hold-the-parent 0-cost NAV against the published NAV: +-0.25 pp a year overall, +-0.5 pp each calendar year) and its agreement with the
        engine's f_g0; W1: the 2019 seam (+-0.5 pp) and the engine's f_seam_2019."""
        reg = E.get("regression.json")
        if wname == "w2":
            ai = pd.DataFrame(D["g0"])
            for r in ai.itertuples():
                c.compared += 1
                c.worst_rel = max(c.worst_rel, abs(r.gap_pp))
                if abs(r.gap_pp) > r.limit_pp:
                    c.failed += 1
                    c.fail(f"G0 exceeded: {r}")
            if reg is not None and "f_g0" in reg:
                for p in BK:
                    e = reg["f_g0"].get(p)
                    if e is None:
                        c.miss(f"regression.json f_g0 {p}")
                        continue
                    a = ai[ai["book"] == p]
                    ov = float(a[a["scope"] == "overall"]["gap_pp"].iloc[0])
                    c.compared += 1
                    if abs(float(e["overall_pp_per_year"]) - ov) > 1e-6:
                        c.failed += 1
                        c.fail(f"G0 overall of {p}: engine {e['overall_pp_per_year']!r} vs verifier {ov!r}")
                    for y, v in e["yearly_pp"].items():
                        mv = a[a["scope"] == str(y)]["gap_pp"]
                        c.compared += 1
                        if not len(mv) or abs(float(v) - float(mv.iloc[0])) > 1e-6:
                            c.failed += 1
                            c.fail(f"G0 {y} of {p}: engine {v!r} vs verifier {mv.tolist()!r}")
            c.notes.append("; ".join(f"{p} overall {float(ai[(ai['book'] == p) & (ai['scope'] == 'overall')]['gap_pp'].iloc[0]):+.4f}" for p in BK))
        else:
            for r in D["seam"]:
                c.compared += 1
                c.worst_rel = max(c.worst_rel, abs(r["year_gap_pp"]))
                if abs(r["year_gap_pp"]) > r["limit_pp"]:
                    c.failed += 1
                    c.fail(f"seam gap {r['year_gap_pp']:+.4f} pp for {r['book']} exceeds {r['limit_pp']}")
                if reg is not None and r["book"] in reg.get("f_seam_2019", {}):
                    c.compared += 1
                    e = reg["f_seam_2019"][r["book"]]
                    if abs(float(e["year_gap_pp"]) - r["year_gap_pp"]) > 1e-6:
                        c.failed += 1
                        c.fail(f"seam gap of {r['book']}: engine {e['year_gap_pp']!r} vs verifier {r['year_gap_pp']!r} pp")
            c.notes.append("; ".join(f"{r['book']} {r['year_gap_pp']:+.4f}" for r in D["seam"]))
        if reg is None:
            E.get("regression.json", c)
    run_check(C, "C-v4f-g0-or-seam", c_g0)

    # ------------------------------------------------------------------ the engine's own gate files
    def c_engine_files(c):
        reg = E.get("regression.json", c)
        if reg is not None:
            def walk_pass(o, path=""):
                if isinstance(o, dict):
                    for kk, vv in o.items():
                        if kk == "pass":
                            c.compared += 1
                            if vv is False:
                                c.failed += 1
                                c.fail(f"regression.json {path}/pass = false")
                        else:
                            walk_pass(vv, path + "/" + str(kk))
                elif isinstance(o, list):
                    for q, vv in enumerate(o):
                        walk_pass(vv, path + f"[{q}]")
            walk_pass(reg)
            for need in ("a_nav_regression", "b_index_priced_as_cash", "c_idx_equals_liq_before_first_index_trade", "d_shared_code", "e_signals", "f_one_instrument"):
                c.compared += 1
                if need not in reg:
                    c.miss(f"regression.json key {need}")
            sc = reg.get("d_shared_code", {})
            c.compared += 1
            if isinstance(sc, dict) and (sc.get("unexpected_changes") or sc.get("required_not_identical")):
                c.failed += 1
                c.fail(f"regression.json d_shared_code lists unexpected changes: {sc.get('unexpected_changes')} {sc.get('required_not_identical')}")
            c.notes.append("V4(d) (AST diff of shared functions against t14_engine.py) is the engine's own gate: the verifier may not open the engines; its recorded "
                           "result (regression.json d_shared_code) is read here")
        A = E.get("audit.json", c)
        if A is not None:
            gates = A.get("gates")
            if isinstance(gates, dict):
                for k, v in gates.items():
                    c.compared += 1
                    if v is False:
                        c.failed += 1
                        c.fail(f"audit.json gate {k} = false")
            v2 = A.get("v2", {})
            c.compared += 2
            if not (isinstance(v2.get("checks"), (int, float)) and v2["checks"] > 0):
                c.failed += 1
                c.fail(f"audit.json v2.checks = {v2.get('checks')!r}: V2 needs a count > 0")
            if v2.get("violations") != 0:
                c.failed += 1
                c.fail(f"audit.json v2.violations = {v2.get('violations')!r}: must be 0")
            books = A.get("books", {})
            for p in BK:
                a = books.get(p)
                if a is None:
                    c.miss(f"{p} in audit.json")
                    continue
                f = D["facts"][(p, "full")]
                pairs = [("weeks", f["weeks"]), ("sessions", f["sessions"]), ("first_state", f["first_state"]), ("weeks_IN", f["weeks_IN"]),
                         ("weeks_OUT_BUY", f["weeks_OUT_BUY"]), ("weeks_OUT_SELL", f["weeks_OUT_SELL"]), ("OUT_SELL_lengths", f["OUT_SELL_lengths"]),
                         ("k0", f["OUT_SELL_weeks_k0"]), ("k1", f["OUT_SELL_weeks_k1"]), ("k2", f["OUT_SELL_weeks_k2"]),
                         ("index_weeks", f["OUT_SELL_weeks_holding_an_index"]), ("index_spells", f["OUT_SELL_spells_holding_an_index"]),
                         ("B_changes", f["B_changes_inside_OUT_SELL"]), ("g_flips", f["g_flips"]), ("g_first_state", f["g_first_state"]),
                         ("start", f["start"]), ("end", f["end"]), ("trades_due_per_rule", f["trades_due"]),
                         ("B_sequences", [t["B_sequence"] for t in f["OUT_SELL_spell_table"]])]
                for nm, mv in pairs:
                    if nm in a:
                        c.compared += 1
                        if a[nm] != mv:
                            c.failed += 1
                            c.fail(f"{p} {nm}: verifier={mv!r} audit.json={a[nm]!r}")
    run_check(C, "C-engine-files", c_engine_files)
    return C


# ======================================================================================
# self-test: a corrupted copy of the evidence must be detected, each corruption by its own check
# ======================================================================================
EVIDENCE_FILES = ["inputs.csv", "decisions.csv", "decisions_r3.csv", "regimes.csv", "stats.csv", "daily_nav.csv", "trades.csv", "positions.csv", "robustness.csv",
                  "robust_nav.csv", "regime_ledger.csv", "constant_mix_params.csv", "regression.json", "audit.json"]
EVIDENCE_FILES_W1 = ["parent_nav_2014-09-01_2019-01-02.csv", "parent_nav_2014-09-01_2019-01-02.md"]
# (key in the info dict, the check that must catch it, label)
SELFTEST_WANTS = [("flipped_B_week", "C-dec", "B_week_flipped"),
                  ("flipped_regime_row", "C-regimes", "regime_changed"),
                  ("b_change_not_traded", "C-trades", "B_change_not_traded"),
                  ("idx_leg_half", "C-v5-idx", "index_leg_at_half_where_k2"),
                  ("idx_trade_gold_after", "C-v5-idx", "idx_regime_trade_holds_goldbees"),
                  ("idx_positions_goldbees", "C-v5-units", "idx_regime_week_goldbees_units"),
                  ("scaled_nav", "C-nav", "nav_scaled"),
                  ("removed_trade", "C-trades", "trade_removed"),
                  ("d1_full_reset_trade", "C-v5-identities", "half_basket_trade_as_full_reset"),
                  ("altered_ledger_return", "C-ledger", "ledger_return_altered"),
                  ("altered_stats_cagr", "C-stats", "stats_cagr_altered"),
                  ("altered_robust_stat", "C-robust-stats", "robustness_stat_altered"),
                  ("altered_r4_nav", "C-robust-nav", "r4_nav_altered"),
                  ("shifted_index_price", "C-nav", "index_price_shifted_one_session")]
OPTIONAL_WANTS = [("lowered_usable_from", "C-data", "sc100_usable_from_lowered")]


def corrupt_copy(ev, dst, books, only=None):
    """Write a copy of the evidence files that carry a corruption (the other files are read from the original through Evidence.fallback). Returns the info dict
    of the corruptions applied. `only` applies one corruption alone."""
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True)
    info = {}
    p0 = books[0]

    def on(label):
        return only is None or only == label

    def csv_ops(name, ops):
        if not any(on(lbl) for lbl, _ in ops):
            return
        pth = ev.path(name)
        if pth is None:
            return
        df = pd.read_csv(pth)
        for lbl, fn in ops:
            if on(lbl):
                res = fn(df)
                if isinstance(res, tuple):
                    res, drops = res
                    df = df.drop(index=drops)
                if res:
                    info[lbl] = res
        df.to_csv(dst / name, index=False)

    def f_B(df):
        cand = df.index[(df["book"] == p0) & (df["regime"] == "OUT-SELL") & (df["buy_MC100"] == 0)]
        if len(cand):
            i = cand[len(cand) // 2]
            df.loc[i, "buy_MC100"] = 1
            df.loc[i, "w_MC100_50-idx"] = 0.25
            return f"{p0} decision j={int(df.loc[i, 'j'])}: buy_MC100 0 -> 1 and w_MC100_50-idx 0.25"

    csv_ops("decisions.csv", [("flipped_B_week", f_B)])

    def f_reg(df):
        cand = df.index[(df["book"] == p0) & (df["regime"] == "OUT-SELL")]
        if len(cand):
            df.loc[cand[0], "regime"] = "OUT-BUY"
            return f"row {int(cand[0])} OUT-SELL -> OUT-BUY"
    csv_ops("regimes.csv", [("flipped_regime_row", f_reg)])

    def f_scale(df):
        m = (df["book"] == p0) & (df["run"] == "80-idx") & (df["cost_bps"] == 0.0)
        if m.any():
            df.loc[m, "nav"] = df.loc[m, "nav"] * 1.001
            return f"{p0} 80-idx cost 0, x 1.001"
    csv_ops("daily_nav.csv", [("scaled_nav", f_scale)])

    def base_of(df, run, kind=None):
        m = (df["book"] == p0) & (df["cost_bps"].astype(float) == HEADLINE_COST) & (df["run"] == run)
        if kind is not None:
            m = m & (df["kind"] == kind)
        return df.index[m]

    def f_bchg(df):
        cand = base_of(df, "50-idx", "index_set_change")
        if len(cand):
            i = cand[0]
            return f"{p0} 50-idx index_set_change {df.loc[i, 'date']} removed", [i]

    def f_half(df):
        nidx = (df["Nifty100_after"] > 0).astype(int) + (df["MC100_after"] > 0).astype(int) + (df["SC100_after"] > 0).astype(int)
        cand = df.index[(df["book"] == p0) & (df["cost_bps"].astype(float) == HEADLINE_COST) & (df["run"] == "50-idx") & (nidx == 2)]
        if len(cand):
            i = cand[0]
            col = next(f"{nm}_after" for nm in INDICES if df.loc[i, f"{nm}_after"] > 0)
            df.loc[i, col] = 0.5 * df.loc[i, "V_after"]
            return f"{p0} 50-idx {df.loc[i, 'kind']} {df.loc[i, 'date']} (k = 2): {col} set to V_after / 2"

    def f_gold(df):
        cand = base_of(df, "50-idx", "regime_in")
        if len(cand):
            i = cand[0]
            df.loc[i, "gold_after"] = 0.05 * df.loc[i, "V_after"]
            return f"{p0} 50-idx regime_in {df.loc[i, 'date']}: gold_after = 0.05 V_after"

    def f_rm(df):
        cand = base_of(df, "80-orig", "basket_change")
        if len(cand) > 2:
            return f"{p0}, 20.8 bps, 3rd basket_change of 80-orig removed", [cand[2]]

    def f_d1(df):
        cand = df.index[(df["book"] == p0) & (df["cost_bps"].astype(float) == HEADLINE_COST) & (df["run"] == "50-half") & (df["kind"] == "basket_change")
                        & (df["e_after"].astype(float) == 0.5)]
        if len(cand):
            i = cand[0]
            aft = float(df.loc[i, "V"]) - float(df.loc[i, "cost"])
            df.loc[i, ["stock_after", "gold_after", "cash_after"]] = [0.5 * aft, 0.5 * aft, 0.0]
            return f"{p0} 50-half basket_change {df.loc[i, 'date']} replaced by a full reset to 50/50"
    csv_ops("trades.csv", [("b_change_not_traded", f_bchg), ("idx_leg_half", f_half), ("idx_trade_gold_after", f_gold), ("removed_trade", f_rm),
                           ("d1_full_reset_trade", f_d1)])

    if on("idx_positions_goldbees") and ev.path("trades.csv") is not None and ev.path("positions.csv") is not None:
        tr0 = pd.read_csv(ev.path("trades.csv"), usecols=["book", "cost_bps", "run", "kind", "date"])
        c4 = tr0.index[(tr0["book"] == p0) & (tr0["cost_bps"].astype(float) == HEADLINE_COST) & (tr0["run"] == "50-idx") & (tr0["kind"] == "regime_in")]
        if len(c4):
            dt = tr0.loc[c4[0], "date"]

            def f_pos(df):
                msk = (df["book"] == p0) & (df["run"] == "50-idx") & (df["date"] == dt) & (df["instrument"] == "GOLDBEES")
                if msk.any():
                    df.loc[msk, "units"] = 0.01
                else:
                    df.loc[len(df)] = dict(book=p0, window="full", cost_bps=HEADLINE_COST, run="50-idx", date=dt, instrument="GOLDBEES", units=0.01)
                return f"{p0} 50-idx regime_in {dt}: a GOLDBEES row of 0.01 units in positions.csv"
            csv_ops("positions.csv", [("idx_positions_goldbees", f_pos)])

    def f_stat(df):
        m = (df["book"] == p0) & (df["run"] == "50-idx") & (df["window"] == "full") & (df["cost_bps"] == HEADLINE_COST)
        if m.any():
            df.loc[m, "cagr"] = df.loc[m, "cagr"] * 1.0001
            return f"{p0} 50-idx 20.8 bps cagr x 1.0001"
    csv_ops("stats.csv", [("altered_stats_cagr", f_stat)])

    def f_rstat(df):
        m = (df["book"] == p0) & (df["variant"] == "r5_drag") & (df["run"] == "50-idx")
        if m.any():
            df.loc[m, "cagr"] = df.loc[m, "cagr"] * 1.0001
            return f"{p0} r5_drag 50-idx cagr x 1.0001"
    csv_ops("robustness.csv", [("altered_robust_stat", f_rstat)])

    def f_r4(df):
        vs = sorted(v for v in df["variant"].unique() if str(v).startswith("r4_"))
        if vs:
            m = (df["book"] == p0) & (df["variant"] == vs[0]) & (df["run"] == "50-idx")
            if m.any():
                df.loc[m, "nav"] = df.loc[m, "nav"] * 1.0001
                return f"{p0} {vs[0]} 50-idx nav x 1.0001"
    csv_ops("robust_nav.csv", [("altered_r4_nav", f_r4)])

    def f_led(df):
        msk = df.index[df["book"] == p0]
        if len(msk):
            df.loc[msk[0], "parent_return"] = df.loc[msk[0], "parent_return"] * 1.01 + 0.001
            return f"{p0} first ledger row parent_return x 1.01 + 0.001"
    csv_ops("regime_ledger.csv", [("altered_ledger_return", f_led)])

    def f_uf(df):
        msk = df["file"].astype(str).str.replace("\\", "/", regex=False).str.contains("Master_SC100")
        if msk.any() and "usable_from" in df.columns:
            df["usable_from"] = df["usable_from"].astype(object)
            df.loc[msk, "usable_from"] = "2004-01-01"
            return "Smallcap 100 Master row of inputs.csv set to usable_from 2004-01-01"
    csv_ops("inputs.csv", [("lowered_usable_from", f_uf)])
    return info


def close_ev(E):
    for obj in E._cache.values():
        if hasattr(obj, "close"):
            try:
                obj.close()
            except Exception:
                pass


def summarise(C):
    gate_fail = sum(c.failed + c.missing for c in C.values() if c.gate)
    gate_compared = sum(c.compared for c in C.values() if c.gate)
    return gate_compared, gate_fail


def print_table(C, title):
    print(f"\n=== {title} ===")
    print(f"{'check':34s} {'compared':>10s} {'failed':>8s} {'missing':>8s} {'worst':>10s}  gate")
    for c in C.values():
        print(f"{c.name:34s} {c.compared:10d} {c.failed:8d} {c.missing:8d} {c.worst_rel:10.2e}  {'yes' if c.gate else 'info'}")
        if c.first_fail:
            print(f"    first problem: {c.first_fail}")


def _jsonable_facts(D):
    return {f"{p}|{w}": f for (p, w), f in D["facts"].items()}


def run_window(wname, evdir, books, selftest, scratch, isolated=True, partner_dirs=()):
    global _ONLY
    t = time.time()
    D = derive(wname, books)
    print(f"[{wname} {time.time()-t:6.1f}s] derivation complete (books {books})", flush=True)
    E = Evidence(evdir)
    E.partner_dirs = list(partner_dirs)
    C = compare_all(wname, D, E, books)
    print(f"[{wname} {time.time()-t:6.1f}s] comparison complete", flush=True)
    for nm in EVIDENCE_FILES + (EVIDENCE_FILES_W1 if wname == "w1" else []):
        if E.path(nm) is None and nm not in E.missing_files:
            E.missing_files.append(nm)
    if E.missing_files:
        print(f"\nMISSING EVIDENCE FILES ({wname}): " + ", ".join(sorted(set(E.missing_files))))
    print_table(C, f"{wname}: verifier vs evidence in {evdir}")
    gate_compared, gate_fail = summarise(C)
    extra_missing = sorted(set(E.missing_files))
    st_rep = None
    if selftest:
        p0 = books[0]
        cdir = scratch / f"corrupt_evidence_t15_{wname}"
        info = corrupt_copy(E, cdir, books)
        Ec = Evidence(cdir, fallback=evdir)
        Ec.partner_dirs = list(partner_dirs)
        Cc = compare_all(wname, D, Ec, books)
        close_ev(Ec)
        print_table(Cc, f"SELF-TEST {wname}: corrupted copy in {cdir}")
        cc, cf = summarise(Cc)
        by = {k: (v.failed + v.missing) for k, v in Cc.items()}
        wants = [w for w in SELFTEST_WANTS if w[0] != "shifted_index_price"] + [w for w in OPTIONAL_WANTS if w[0] in info]
        applied = {lbl: ikey in info for ikey, chk, lbl in wants}
        detected_by = {lbl: by.get(chk, 0) > 0 for ikey, chk, lbl in wants}
        shutil.rmtree(cdir, ignore_errors=True)
        iso = {}
        if isolated:
            for ikey, chk, lbl in wants:
                _ONLY = {chk}
                try:
                    i2 = corrupt_copy(E, cdir, books, only=ikey)
                    Ei = Evidence(cdir, fallback=evdir)
                    Ei.partner_dirs = list(partner_dirs)
                    Ci = compare_all(wname, D, Ei, books)
                    close_ev(Ei)
                finally:
                    _ONLY = None
                fired = (Ci[chk].failed + Ci[chk].missing) > 0 if chk in Ci else False
                iso[lbl] = dict(applied=ikey in i2, own_check=chk, own_check_fired=bool(fired), detail=i2.get(ikey))
                print(f"[{wname}] corruption alone, {lbl}: applied {ikey in i2}; caught by {chk}: {fired}", flush=True)
                shutil.rmtree(cdir, ignore_errors=True)
        # the verifier's own copy of the index prices shifted by one session (one book): the NAV (and statistics) checks must fail
        Ds = derive(wname, [p0], verbose=False, idx_shift=1)
        _ONLY = {"C-nav", "C-stats", "C-trades"}
        try:
            Cs = compare_all(wname, Ds, E, [p0])
        finally:
            _ONLY = None
        READS.clear()
        READS.update(D["reads"])
        shift_caught = {k: (v.failed + v.missing) for k, v in Cs.items()}
        shift_ok = shift_caught.get("C-nav", 0) > 0
        applied["index_price_shifted_one_session"] = True
        detected_by["index_price_shifted_one_session"] = shift_ok
        iso["index_price_shifted_one_session"] = dict(applied=True, own_check="C-nav", own_check_fired=bool(shift_ok), detail=f"{p0}: verifier's index closes and fills shifted by one session; checks failed {shift_caught}")
        print(f"[{wname}] index prices shifted by one session ({p0}): C-nav failures {shift_caught.get('C-nav')}; C-stats {shift_caught.get('C-stats')}; C-trades {shift_caught.get('C-trades')}", flush=True)
        detected = (cf > 0 and all(applied.values()) and all(detected_by.values())
                    and (not isolated or all(v["applied"] and v["own_check_fired"] for v in iso.values())))
        st_rep = dict(corruptions=info, applied=applied, gate_compared=cc, gate_failures=cf, detected=bool(detected), detected_by=detected_by, isolated=iso,
                      checks={k: v.to_dict() for k, v in Cc.items()})
        print(f"[{wname}] corrupted copy detected: {detected} (failures {cf}; applied {applied}; detected by {detected_by})", flush=True)
    ok_real = gate_compared > 0 and gate_fail == 0 and not extra_missing
    ok = ok_real and (st_rep is None or st_rep["detected"])
    reads = {}
    for k, v in D["reads"].items():
        try:
            sha = sha256_file(AA / k)
        except Exception:
            sha = None
        reads[k] = dict(v, sha256=sha)
    rep = dict(verifier="analysis/verify_t15.py", window=wname, evidence=str(evdir), books=books, end=str(D["END"].date()),
               gate_compared=int(gate_compared), gate_failures_and_missing=int(gate_fail), n_checks=len(C), n_gate_checks=sum(1 for c in C.values() if c.gate),
               missing_evidence_files=extra_missing, checks={k: v.to_dict() for k, v in C.items()}, meta=D["meta"], facts=_jsonable_facts(D),
               index_sessions_without_a_bar=D["nobar"], v4b=D["v4b"], v4c=D["v4c"], g0=D["g0"], seam=D["seam"],
               one_instrument={p: v for p, v in D["one_instrument"].items()}, approved_data_files_read=reads, selftest=st_rep, exit_ok=bool(ok),
               seconds=round(time.time() - t, 1))
    out = Path(evdir) / "verify_t15.json"
    try:
        out.write_text(json.dumps(rep, indent=1, default=str))
        print(f"wrote {out}")
    except Exception as ex:
        print(f"could not write {out}: {ex!r}")
    print(f"\n[{wname}] rows compared (gate checks): {gate_compared}; failures + missing: {gate_fail}; real run ok: {ok_real}; exit ok: {ok}; time {time.time()-t:.1f} s", flush=True)
    return ok, gate_compared, gate_fail


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="headline", help="evidence run name under tests/T15/evidence/ (holds w1/ and w2/)")
    ap.add_argument("--evidence", default=None, help="evidence directory holding w1/ and w2/ (overrides --run)")
    ap.add_argument("--window", default="both", choices=["w1", "w2", "both"])
    ap.add_argument("--no-selftest", action="store_true", help="skip the corrupted-copy self-test")
    ap.add_argument("--no-isolated", action="store_true", help="in the self-test, skip applying each corruption alone against its own check")
    ap.add_argument("--books", default=None, help="comma-separated books (default: those found in the evidence's decisions.csv)")
    ap.add_argument("--scratch", default=None, help="directory for the corrupted copies (default: a fresh temporary directory)")
    args = ap.parse_args()
    root = Path(args.evidence) if args.evidence else AA / "tests" / "T15" / "evidence" / args.run
    windows = ["w1", "w2"] if args.window == "both" else [args.window]
    scratch = Path(args.scratch) if args.scratch else Path(tempfile.mkdtemp(prefix="verify_t15_"))
    scratch.mkdir(parents=True, exist_ok=True)
    t = time.time()
    results = {}
    for wn in windows:
        evdir = root / wn
        if args.books:
            books = [b.strip() for b in args.books.split(",")]
        else:
            dp = evdir / "decisions.csv"
            books = [b for b in BOOKS if dp.exists() and b in set(pd.read_csv(dp, usecols=["book"])["book"])] or list(BOOKS)
        partners = [root / o for o in ("w1", "w2") if o != wn]
        results[wn] = run_window(wn, evdir, books, not args.no_selftest, scratch, not args.no_isolated, partners)
    ok = all(r[0] for r in results.values())
    print("\n==== summary ====")
    for wn, (o, gc, gf) in results.items():
        print(f"{wn}: rows compared (gate checks) {gc}; failures + missing {gf}; exit ok {o}")
    print(f"total time {time.time()-t:.1f} s; exit {'0' if ok else '1'}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
