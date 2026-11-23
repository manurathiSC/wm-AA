"""T14 independent verifier (Step 3, gate V1 of tests/T14/T14.md section 2.5).

Re-derives, for both windows (W1 = 2014-09-01 -> 2019-01-02, T11's inputs; W2 = 2019-01-02 -> 2026-10-30, T08's inputs) and all four books, from the
RAW approved files only (plain numpy / pandas / scipy, its own loaders, its own cost, basket, regime, counting and percentile code):

  * the weekly decisions, the regime of each (IN / OUT-BUY / OUT-SELL) and the target (e, gw) of the six rules (50-orig, 50-half, 50-liq, 80-orig,
    80-half, 80-liq), the R3 window's decisions, regimes.csv, real_states.npz;
  * the NAV of every rule and comparator (hold the parent, the constant mixes, the sleeve-only runs, the constant mix at each rule's own averages)
    at 0 / 20.8 / 50 bps, every statistic of stats.csv, every trade of trades.csv including the D1 partial basket trade inside the -half regime
    and the regime_in / regime_out trades, positions.csv, the rebuilt parent NAV file, R2 (LIQUIDCASE), R3, and (W1) the R7 variants;
  * every null draw state (regenerated from its seed and compared with the saved file AND with the stored draw_states.npz of T11 / T08), the
    structure of EVERY saved draw, every row of draws.csv against its states, the NAV of the first 20 and 20 random draws of every row group
    for all six rules, the stored draw curves, the percentile and p-value of each rule among its own draws (twice, vectorised and by loop);
  * the regime ledger, the counts of logs/step_1_spell_counts.json and of the frozen text, V2, V4 (regression against the stored T11 / T08 / T06
    results, one-instrument identity, signals, G0 / seam) and V6 (trade and cost identities, D1, the -half entry split, the -liq gold rule).

It imports nothing from the engine or from any other module in analysis/ or data/, and it never reads the engine's source. The rules are those of
tests/T14/T14.md sections 1-3 (frozen) and tests/T14/logs/evidence_contract.md; the loaders, simulator arithmetic, samplers, counting and
corrupted-copy machinery are forked from verify_t11.py (W1) and verify_t08.py (W2). Its own spec: tests/T14/logs/verifier_spec.md.

Usage (from AA/):
    python analysis/verify_t14.py                                    # headline run (both windows) + self-test on corrupted copies
    python analysis/verify_t14.py --run headline --window both
    python analysis/verify_t14.py --evidence DIR --draws 20 --books SCMO_0003      # DIR holds w1/ and w2/
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
TOL = 1e-9                  # relative tolerance on NAVs and statistics (T14.md V1)
TOL_REG = 1e-12             # V4 regression against the stored T11 / T08 / T06 results
TOL_ID = 1e-12              # identities (V6)
N_DRAWS = 2000              # draws per row group (--draws overrides, for short runs)
SC100_SIGNAL_FROM = pd.Timestamp("2011-11-25")   # standing rule 7
LIQ_NOTE = "R2 reads the whole liquidEtfFinal file as-of (as verify_t08.py; see step_3_log.md reading 6)"
G0_OVERALL_PP = 0.25
G0_YEAR_PP = 0.5
SEAM_PP = 0.5
T06_CUTOFF = pd.Timestamp("2026-10-22")
LIVE_START = pd.Timestamp("2021-11-01")
R3_START_W1 = pd.Timestamp("2015-01-02")
END_D17 = pd.Timestamp("2019-12-31")

RULES = ["50-orig", "50-half", "50-liq", "80-orig", "80-half", "80-liq"]
NEW_RULES = [r for r in RULES if not r.endswith("-orig")]
ORIG_OF = {r: r[:2] + "-orig" for r in RULES}
REG_NAMES = ["IN", "OUT-BUY", "OUT-SELL"]          # codes 0, 1, 2
COMP_KINDS = ["hold_parent", "constant_mix", "constant_mix_timed", "sleeve_only", "sleeve_only_timed"] + [f"cmix_{r}" for r in RULES]
BASE_KINDS = RULES + COMP_KINDS
R7_BASE = RULES + ["hold_parent"]
R7_KINDS = [f"{k}_r7_{v}" for v in ("flagged", "noexport") for k in R7_BASE]
FAMILY = {"F1": ("N4.10", "real"), "F2": ("N4.9", "real"), "F3": ("real", "N4.10-g"), "F4": ("real", "N4.9-g"), "F5": ("N4.10", "N4.10-g")}
STAT_COLS_ALL = ["end_nav", "cagr", "max_dd", "vol", "ulcer", "days_below_10pct", "longest_underwater", "calmar", "sessions"]
SEEDS = {"w1": dict(n49=[14, 3], n410=[14, 6], n49g=[14, 11, 3], n410g=[14, 11, 6]),     # seed = list + [draw_id]
         "w2": dict(n49=[3], n410=[6], n49g=[11, 3], n410g=[11, 6])}
EXPECT_BOUNDS_W2 = dict(io=dict(lo=2, hi_in=46, hi_out=40), gold=dict(lo_buy=2, hi_buy=68, lo_sell=2, hi_sell=28))
APPROVED_MD = AA / "data" / "APPROVED_DATA.md"
T06_EVIDENCE = AA / "tests" / "T06" / "evidence" / "headline"
T08_EVIDENCE = AA / "tests" / "T08" / "evidence" / "headline"
T11_EVIDENCE = AA / "tests" / "T11" / "evidence" / "headline"
STEP1_JSON = AA / "tests" / "T14" / "logs" / "step_1_spell_counts.json"
# registry ids that T14.md section 3 lists as 'Not read' by the test
NOT_READ_IDS = {"D25", "D20", "D21", "D22", "D23", "D20b", "D23b", "D09b", "D03b", "D15"}
THROUGH_EXEMPT_IDS = {"D12", "D19", "D05"}          # through-dates earlier than W2's end by design (D12 de-spike range, D19 / D05 baskets)

F_CAL = "Historical Data/extended_2026-11-12/index_daily_pre2019/nse_trading_days.csv"
F_MASTER = {n: f"Historical Data/extended_2026-10-30/Master/Master_{n}.xlsx" for n in ["Nifty100", "MC100", "SC100"]}
F_G = {"w1": dict(master="Historical Data/extended_2026-11-12/MAUc1_from_2003/Master_MAUc1.xlsx",
                  weekly="Historical Data/extended_2026-11-12/MAUc1_from_2003/mauc1_supertrend_weekly_extended.csv",
                  daily="Historical Data/extended_2026-11-12/MAUc1_from_2003/mauc1_daily_clean_extended.csv"),
       "w2": dict(master="Historical Data/extended_2026-11-06/MAUc1/Master_MAUc1.xlsx",
                  weekly="Historical Data/extended_2026-11-06/MAUc1/mauc1_supertrend_weekly_extended.csv",
                  daily="analysis/evidence/final_strategy/mauc1/mauc1_daily_clean.csv")}
F_D09 = "analysis/cache/why_gold_ohlc_eikon_extended_2026-11-04.parquet"
F_LBES = "Historical Data/LBES_Adjusted_Price_data_extended_2026-11-05.csv"
F_LIQ = "Historical Data/liquidEtfFinal_extended_2026-11-05.csv"
F_CORR = "data/holdings_matrix/price_corrections.csv"

# ---- the frozen text's own numbers (T14.md section 2, 'what was already known'), the oracle for the verifier's re-derivation ----
FROZEN = {
    "w1": dict(full=dict(weeks=228, first_state=1, in_=93, out_buy=81, out_sell=54, sell_spells=8, sell_lengths=[7, 6, 7, 1, 11, 11, 9, 2], round_trips=8,
                         trades={"50-orig": 15, "50-half": 24, "50-liq": 24, "80-orig": 24, "80-half": 24, "80-liq": 24},
                         tuples=dict(in_=4024559144, out=19406343528, buy=6835192844305, sell=4976743356)),
               r3=dict(weeks=210, first_state=0, out_sell=44, sell_spells=7, round_trips=6,
                       tuples=dict(in_=7654290, out=659773128, buy=426468399525, sell=644288463))),
    "w2": dict(full=dict(weeks=410, weeks_0007=409, first_state=0, in_=201, out_buy=163, out_sell=46, sell_spells=8, sell_lengths=[1, 4, 10, 2, 12, 11, 4, 2],
                         round_trips=9, trades={"50-orig": 18, "50-half": 27, "50-liq": 27, "80-orig": 27, "80-half": 27, "80-liq": 27}),
               r3=dict(weeks=262, out_sell=31, sell_spells=5, round_trips=5)),
}
N_BASKETS_W1 = 19


# ======================================================================================
# helpers forked from verify_t11.py (loaders, spells, samplers, counting, percentiles, Check machinery)
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


def _read_master(rel, first_date=None, gate_only=False):
    """Weekly Master file -> (dates, SIGN) arrays, sorted. Rows dated before first_date (a restriction) are dropped at load and never used."""
    m = pd.read_excel(rd(rel, first_date, gate_only))
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
    return {nm: _read_master(F_MASTER[nm], SC100_SIGNAL_FROM if nm == "SC100" else None) for nm in ["Nifty100", "MC100", "SC100"]}

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
    cumulative-sum search (T11.md section 3 step 11; never Generator.choice)."""
    out = []
    t = S
    for m in range(k, 0, -1):
        hi_t = min(hi, t)
        w = np.array([tab[m - 1][t - x] for x in range(lo, hi_t + 1)], dtype=float)
        cum = np.cumsum(w)
        u = rng.random()
        idx = int(np.searchsorted(cum, u * cum[-1], side="right"))
        x = lo + min(idx, len(w) - 1)
        out.append(x)
        t -= x
    return out


def states_from_lengths(first_state, ones, zeros):
    out = []
    i1 = i0 = 0
    for r in range(len(ones) + len(zeros)):
        st = first_state if r % 2 == 0 else 1 - first_state
        if st == 1:
            out.extend([1] * ones[i1]); i1 += 1
        else:
            out.extend([0] * zeros[i0]); i0 += 1
    return np.array(out, dtype=np.uint8)


def n410_states_own(first_state, par1, par0, seed_base, draw_id, tabs):
    """Own N4.10 / N4.10-g draw: 1-spell lengths first, then 0-spell lengths, from one generator default_rng(seed_base + [id]).
    par1 / par0 = (k, S, lo, hi) of the 1- and 0-spells."""
    rng = np.random.default_rng(list(seed_base) + [int(draw_id)])
    ones = draw_lengths_own(rng, par1[0], par1[1], par1[2], par1[3], tabs[par1])
    zeros = draw_lengths_own(rng, par0[0], par0[1], par0[2], par0[3], tabs[par0])
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
                shortest_in=min(ins) if ins else 0, shortest_out=min(outs) if outs else 0,
                longest_in=max(ins) if ins else 0, longest_out=max(outs) if outs else 0, invested_weeks=int(np.sum(states)))


def bounds_of(rs):
    """lo = min(2, shortest spell of the state), hi = longest spell of the state (T11.md section 2, computed from the series)."""
    return dict(lo_in=min(2, rs["shortest_in"]), hi_in=rs["longest_in"], lo_out=min(2, rs["shortest_out"]), hi_out=rs["longest_out"])


def week_cover(dec_idx):
    """Sessions of week j from its trade session (decision session + 1) to the next decision session: cover_j = dec_idx[j+1] - dec_idx[j] for every
    week but the last (decided on the last session, never traded: 0); week 0 starts at T0 itself (+1). T06-1's 'sessions held'."""
    d = np.asarray(dec_idx, dtype=np.int64)
    cov = np.zeros(len(d), dtype=np.int64)
    cov[:-1] = d[1:] - d[:-1]
    if len(d) > 1:
        cov[0] += 1       # week 0's trade session is T0 itself (the initial position is struck at T0): its sessions run from session 0 (reading, see verifier_spec.md)
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


def sample_ids(book, key, n_first=20, n_rand=20, pool=None, seed=20261117):
    """The first n_first draw ids plus n_rand seeded random ids from the rest (per book and group key)."""
    pool = N_DRAWS if pool is None else pool
    rng = np.random.default_rng([seed, BOOKS.index(book), zlib.crc32(str(key).encode())])
    nf = min(n_first, pool)
    rest = np.arange(nf, pool)
    nr = min(n_rand, len(rest))
    return list(range(nf)) + (sorted(rng.choice(rest, size=nr, replace=False).tolist()) if nr > 0 else [])


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
    rng = np.random.default_rng([20261117, 5])
    cnt = {t: 0 for t in tuples}
    for _ in range(n_samples):
        cnt[tuple(draw_lengths_own(rng, 3, 12, 2, 6, tab))] += 1
    exp = n_samples / len(tuples)
    chi = float(sum((v - exp) ** 2 / exp for v in cnt.values()))
    r = dict(n_tuples=len(tuples), n_ways_formula=n_ways(3, 12, 2, 6), n_ways_dp=tab[3][12], n_samples=n_samples, chi2=chi, df=len(tuples) - 1,
             p=chi2_sf(chi, len(tuples) - 1), all_seen=all(v > 0 for v in cnt.values()))
    _SELFTEST_CACHE["r"] = r
    return r

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



# ----------------------------------------------------------------------------------------
# T14-specific loaders (windows), rules, regimes
# ----------------------------------------------------------------------------------------
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


def mk_T(rule, s, g, dec_idx):
    e, gw = rule_arrays(rule, s, g)
    return dict(e=e, gw=gw, dec_idx=np.asarray(dec_idx), regime=regime_codes(s, g), variant=rule[3:])


def decisions_for_window(p, cal, a, b, wname, masters, gmaster):
    """Decision dates: the window's T0, then the last session of each later ISO week. Every Master (the three indices and MAUc1) is read as-of: the latest
    row dated on or before the decision date. Evidence column layout plus regime and the (e, gw) of the six rules."""
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
        for nm in ["Nifty100", "MC100", "SC100"]:
            dates, sg = masters[nm]
            s_, l_ = _asof(dates, sg, d)
            signs.append(s_); labels.append(l_)
        gs, gl = _asof(gmaster[0], gmaster[1], d)
        latest = max(labels)
        buy = all(s == "BUY" for s in signs)
        trade = cal[ix + 1] if ix + 1 < len(cal) and j < len(dec_idx) - 1 else None
        g = 1 if gs == "BUY" else 0
        rows.append(dict(book=p, window=wname, j=j, decision_date=str(d.date()), decision_idx=int(ix),
                         trade_date=None if trade is None else str(trade.date()),
                         sign_Nifty100=signs[0], sign_MC100=signs[1], sign_SC100=signs[2],
                         label_Nifty100=str(labels[0].date()), label_MC100=str(labels[1].date()), label_SC100=str(labels[2].date()),
                         latest_label=str(latest.date()), label_age_days=int((d - latest).days),
                         all_three_buy=bool(buy), state=int(buy),
                         sign_MAUc1=gs, label_MAUc1=str(gl.date()), g=g))
    df = pd.DataFrame(rows)
    df["regime"] = [REG_NAMES[c] for c in regime_codes(df["state"].values, df["g"].values)]
    for r in RULES:
        e, gw = rule_arrays(r, df["state"].values, df["g"].values)
        df[f"e_{r}"] = e
        df[f"gw_{r}"] = gw
    return df


# ----------------------------------------------------------------------------------------
# the simulation (own implementation, T14.md section 3 steps 3-8)
# ----------------------------------------------------------------------------------------
def build_sched(T, mode):
    """Session index -> (e_new, gw_new, kind, decision j) for every scheduled trade.
    rule   : a trade is due on the session after decision j (1 <= j <= D-2) iff e[j] != e[j-1] or (e[j] < 1 and gw[j] != gw[j-1]); kind regime_in / regime_out
             (-half and -liq only) when the decision changes OUT-SELL membership, else switch_in (e[j] = 1), switch_out (e[j-1] = 1), sleeve_rebalance.
    mix    : every decision but the last (rebalance to e = f, gold weight gw[j] of the non-stock share), including after T0's decision.
    sleeve0: the 100% sleeve; trades only when the gold weight changes.   hold: none."""
    e, gw, di = T["e"], T["gw"], T["dec_idx"]
    D = len(e)
    sw = {}
    if mode == "mix":
        for j in range(0, D - 1):
            sw[int(di[j]) + 1] = (float(e[j]), float(gw[j]), "mix_rebalance", j)
    elif mode == "sleeve0":
        gw_t = float(gw[0])
        for j in range(1, D - 1):
            if float(gw[j]) != gw_t:
                sw[int(di[j]) + 1] = (0.0, float(gw[j]), "sleeve_rebalance", j)
                gw_t = float(gw[j])
    elif mode == "rule":
        reg, var = T["regime"], T["variant"]
        for j in range(1, D - 1):
            if e[j] != e[j - 1] or (e[j] < 1 and gw[j] != gw[j - 1]):
                if var in ("half", "liq") and ((reg[j] == 2) != (reg[j - 1] == 2)):
                    kind = "regime_in" if reg[j] == 2 else "regime_out"
                elif e[j] == 1:
                    kind = "switch_in"
                elif e[j - 1] == 1:
                    kind = "switch_out"
                else:
                    kind = "sleeve_rebalance"
                sw[int(di[j]) + 1] = (float(e[j]), float(gw[j]), kind, j)
    return sw


def simulate(V, T, bps, mode="rule", closed_form=False, positions=False, W_override=None, Cn_override=None, F_override=None, C_override=None):
    """One realisation on view V (sessions 0..n-1). T: dict(e, gw, dec_idx, regime, variant): the target (e, gw) at every decision."""
    n = V["n"]
    C = V["C"] if C_override is None else C_override
    Cn = V["Cn"] if Cn_override is None else Cn_override
    F = V["F"] if F_override is None else F_override
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
    gw_cur = float(T["gw"][0])
    shares = sh0 * e if e > 0 else np.zeros(S)
    gu = (1 - e) * gw_cur / gc[0]
    cu = (1 - e) * (1 - gw_cur) / L[0]

    sw = build_sched(T, mode)
    chg = [i for i in V["changes"] if i < n]
    events = sorted(set(k for k in sw if k < n) | set(chg))

    segs = [(0, shares.copy(), gu, cu)]
    trades = []
    for i in events:
        bk = basket_key(i)
        w = W[basket_at[bk]]
        pf = F[i]
        held = shares != 0
        partial = False
        if i in sw:
            e_new, gw_new, kind, jdec = sw[i]
        else:
            kind, jdec, e_new, gw_new = "basket_change", None, e, gw_cur
            if e <= 0.0:
                continue                      # basket change while OUT (e = 0): nothing traded
            partial = (mode == "rule" and e < 1.0)       # D1: while 0 < e < 1 only the stock part is re-weighted
        tgt_w = w if partial else e_new * w
        need = (tgt_w > 0) | held
        if np.isnan(pf[need]).any():
            raise RuntimeError(f"missing fill price for a needed stock at {V['cal'][i]}")
        pfz = np.where(np.isnan(pf), 0.0, pf)
        cur_stock = np.where(held, shares * pfz, 0.0)
        cur_g = gu * gf[i]
        cur_c = cu * L[i]
        S_cur = float(cur_stock.sum())
        Vv = S_cur + cur_g + cur_c
        if partial:
            tgt_stock = S_cur * w
            traded = float(np.abs(tgt_stock - cur_stock).sum())
            cost = traded * bps / 2.0 / 10000.0
            shares = np.where(tgt_stock > 0, (S_cur - cost) * w / np.where(np.isnan(pf), 1.0, pf), 0.0)
            stock_after, gold_after, cash_after = S_cur - cost, cur_g, cur_c
        else:
            tgt_stock = e_new * Vv * w
            tgt_g = (1 - e_new) * gw_new * Vv
            tgt_c = (1 - e_new) * (1 - gw_new) * Vv
            traded = float(np.abs(tgt_stock - cur_stock).sum() + abs(tgt_g - cur_g) + abs(tgt_c - cur_c))
            cost = traded * bps / 2.0 / 10000.0
            f = (Vv - cost) / Vv
            shares = np.where(tgt_stock > 0, tgt_stock * f / np.where(np.isnan(pf), 1.0, pf), 0.0)
            gu = tgt_g * f / gf[i]
            cu = tgt_c * f / L[i]
            stock_after, gold_after, cash_after = float(tgt_stock.sum() * f), tgt_g * f, tgt_c * f
            e = e_new
            gw_cur = gw_new
        segs.append((i, shares.copy(), gu, cu))
        trades.append(dict(idx=i, date=str(V["cal"][i].date()), kind=kind, e_after=e, gw_after=gw_cur,
                           basket_eff=str(pd.Timestamp(V["avail"][basket_at[bk]]).date()), V=Vv, traded=traded, cost=cost, dec_j=jdec,
                           stock_before=S_cur, gold_before=cur_g, cash_before=cur_c, stock_after=stock_after, gold_after=gold_after,
                           cash_after=cash_after, partial=partial))

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
    for t in trades:
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


def T_hold(nd):
    return dict(e=np.ones(nd), gw=np.full(nd, 0.5), dec_idx=np.arange(nd), regime=np.zeros(nd, dtype=int), variant="orig")


# ----------------------------------------------------------------------------------------
# structure of the real series
# ----------------------------------------------------------------------------------------
def rule_for(states, gstates, dec_idx, n_sessions, start, end, bounds_from=None):
    R = rule_structure(states)
    R["g"] = rule_structure(gstates)
    R["states"] = states.astype(np.uint8)
    R["gstates"] = gstates.astype(np.uint8)
    R["dec_idx"] = dec_idx
    R["cover"] = week_cover(dec_idx)
    R["sessions"] = int(n_sessions)
    R["start"] = start
    R["end"] = end
    G = R["g"]
    R["bounds"] = bounds_of(R)
    R["g_bounds"] = dict(lo_buy=min(2, G["shortest_in"]), hi_buy=G["longest_in"], lo_sell=min(2, G["shortest_out"]), hi_sell=G["longest_out"])
    if bounds_from is not None:          # W2's live window: the book's FULL-window bounds (T08 E13)
        R["bounds"] = dict(bounds_from["bounds"])
        R["g_bounds"] = dict(bounds_from["g_bounds"])
    D_ = len(states)
    R["sleeve_trades"] = sum(1 for j in range(1, D_ - 1) if states[j] == 0 and states[j - 1] == 0 and gstates[j] != gstates[j - 1])
    R["sessions_invested"] = int((states.astype(np.int64) * R["cover"]).sum())
    reg = regime_codes(states, gstates)
    R["regime"] = reg
    R["weeks_IN"] = int((reg == 0).sum())
    R["weeks_OUT_BUY"] = int((reg == 1).sum())
    R["weeks_OUT_SELL"] = int((reg == 2).sum())
    sp = []
    j = 0
    while j < D_:
        if reg[j] == 2:
            k = j
            while k + 1 < D_ and reg[k + 1] == 2:
                k += 1
            sp.append((j, k)); j = k + 1
        else:
            j += 1
    R["sell_spells_idx"] = sp
    R["OUT_SELL_spells"] = len(sp)
    R["OUT_SELL_lengths"] = [b - a + 1 for a, b in sp]
    bsp = []
    j = 0
    while j < D_:
        if reg[j] == 1:
            k = j
            while k + 1 < D_ and reg[k + 1] == 1:
                k += 1
            bsp.append(k - j + 1); j = k + 1
        else:
            j += 1
    R["OUT_BUY_spells"] = len(bsp)
    R["OUT_BUY_lengths"] = bsp
    R["trades_due"] = {r: int(sum(1 for jj in range(1, D_ - 1) if (lambda e, gw: e[jj] != e[jj - 1] or (e[jj] < 1 and gw[jj] != gw[jj - 1]))(*rule_arrays(r, states, gstates)))) for r in RULES}
    R["weeks_e_half"] = {r: int((rule_arrays(r, states, gstates)[0] == 0.5).sum()) for r in RULES}
    R["weeks_no_parent_no_gold"] = {r: int(((rule_arrays(r, states, gstates)[0] == 0) & (rule_arrays(r, states, gstates)[1] == 0)).sum()) for r in RULES}
    gr = runs_of(gstates)
    pos, n_with = 0, 0
    for v_, l_ in gr:
        if (states[pos:pos + l_] == 0).any():
            n_with += 1
        pos += l_
    R["g_spells_with_an_out_week"] = n_with
    R["g_flips"] = len(gr) - 1
    R["g_weeks_buy_while_out"] = int(((gstates == 1) & (states == 0)).sum())
    R["g_weeks_sell_while_out"] = int(((gstates == 0) & (states == 0)).sum())
    return R


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


def n_in_comp(states):
    return int(np.sum(states))


def ledger_rows(window, p, R, V, di, navs, hold0):
    """One row per OUT-SELL spell. Span: from the close of the session of the spell's first decision to the close of the session of the decision that ends
    the spell (the window's last session if the spell runs to the end). parent = hold-the-parent at 0 bps; the rules at 20.8 bps."""
    reg = R["regime"]
    D_ = len(reg)
    rows = []
    for no, (a, b) in enumerate(R["sell_spells_idx"], start=1):
        i0 = int(di[a])
        i1 = int(di[b + 1]) if b + 1 < D_ else V["n"] - 1
        row = dict(window=window, book=p, spell_no=no, first_decision=str(V["cal"][di[a]].date()), last_decision=str(V["cal"][di[b]].date()),
                   weeks=b - a + 1, span_from_close=str(V["cal"][i0].date()), span_to_close=str(V["cal"][i1].date()),
                   entered_from="start" if a == 0 else REG_NAMES[reg[a - 1]], exited_to="window end" if b + 1 >= D_ else REG_NAMES[reg[b + 1]],
                   parent_return=float(hold0[i1] / hold0[i0] - 1), goldbees_return=float(V["gc"][i1] / V["gc"][i0] - 1),
                   cash_return=float(V["L"][i1] / V["L"][i0] - 1))
        for r in RULES:
            row[f"ret_{r}"] = float(navs[r][i1] / navs[r][i0] - 1)
        rows.append(row)
    return rows


def r7_derive(B, V, T6, di, cal):
    """R7 (W1 only): flagged stock-days (|ffilled close return| >= 20% of a stock with weight > 0 in the basket in force on t-1 or t), the return-preserving
    splice, and the six rules and hold-the-parent at 0 and 20.8 bps with the flagged days (and with every export-priced held stock-day) set to a zero return."""
    n = V["n"]
    C = V["C"]
    b_idx, basket_at, W = V["b_idx"], V["basket_at"], V["W"]
    Wraw = B["Wraw"]
    wrow = np.array([basket_at[b_idx[np.searchsorted(b_idx, i, side="right") - 1]] for i in range(n)])
    Wr = W[wrow]
    Wraw_s = Wraw[wrow]
    with np.errstate(divide="ignore", invalid="ignore"):
        ret = C[1:] / C[:-1] - 1.0
    held = (Wr[:-1] > 0) | (Wr[1:] > 0)
    flag = np.zeros((n, len(V["S"])), dtype=bool)
    flag[1:] = (np.abs(ret) >= 0.20) & held & ~np.isnan(ret)
    PR = load_book_prices(B["p"], load_corrections())
    srcm = PR["src"][V["S"]].reindex(cal).values
    exp = np.zeros_like(flag)
    exp[1:] = (srcm[1:] == "export") & held
    rows = []
    for t, i in zip(*np.nonzero(flag)):
        rows.append(dict(book=B["p"], date=str(cal[t].date()), stock=V["S"][i], prev_close=float(C[t - 1, i]), close=float(C[t, i]), ret=float(ret[t - 1, i]),
                         w_prev=float(Wraw_s[t - 1, i]), w_cur=float(Wraw_s[t, i]), w_prev_n=float(Wr[t - 1, i]), w_cur_n=float(Wr[t, i]), src=str(srcm[t, i])))
    exp_held = (srcm == "export") & (Wr > 0)
    by_stock = {V["S"][i].replace(".NS", ""): int(exp_held[:, i].sum()) for i in range(len(V["S"])) if exp_held[:, i].any()}
    out = dict(flagged=rows, export_by_stock=by_stock, export_total=int(exp_held.sum()), sims=[])
    for tag, msk in (("flagged", flag), ("noexport", exp)):
        M = np.ones((n, len(V["S"])))
        for t, i in zip(*np.nonzero(msk)):
            M[t:, i] *= C[t - 1, i] / C[t, i]
        C2 = C * M
        F2 = V["F"] * M
        Cn2 = np.nan_to_num(C2, nan=0.0)
        for bps in (0.0, HEADLINE_COST):
            for kind in R7_BASE:
                if kind == "hold_parent":
                    r = simulate(V, T_hold(len(di)), bps, "hold", Cn_override=Cn2, F_override=F2, C_override=C2)
                else:
                    r = simulate(V, T6[kind], bps, "rule", Cn_override=Cn2, F_override=F2, C_override=C2)
                out["sims"].append((f"{kind}_r7_{tag}", bps, r))
    return out


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


# ----------------------------------------------------------------------------------------
# derive everything of one window that does not depend on the evidence
# ----------------------------------------------------------------------------------------
def derive(wname, books, verbose=True):
    t = time.time()
    READS.clear()
    masters = load_masters()
    gmaster = _read_master(F_G[wname]["master"])
    gold, mcx = load_gold_files(wname)
    lbes, liq = load_lbes(), load_liquidcase()
    corr = load_corrections()
    if wname == "w1":
        T0, END = pd.Timestamp("2014-09-01"), pd.Timestamp("2019-01-02")
        cal_shared = load_w1_calendar(T0, END)
    else:
        END = window_end_of(masters)
        cal_shared = None
    D = {"wname": wname, "books": {}, "dec": [], "nav": [], "stats": [], "trades": [], "positions": [], "meta": {}, "rule": {}, "baskets": [], "r7": {},
         "masters": masters, "gmaster": gmaster, "corr": corr, "END": END, "one_instrument": {}, "hold0": {}, "ledger": [], "cmix": [], "mix_params": {},
         "g0": [], "seam": [], "navs_by_run": {}}
    for p in books:
        touch_book_files(p)
        if wname == "w1":
            cal = cal_shared
            pub = None
        else:
            pub = load_published_nav(p)
            cal = pub.index[pub.index <= END]
            assert cal[-1] == END, (p, cal[-1], END)
        MK = market_arrays(cal, gold, mcx, lbes, liq)
        if wname == "w2":
            MK["L2"] = chain_liquidcase(cal, MK["L"], MK["L2"])       # R2 on W2: LBES, then LIQUIDCASE returns chained from 2024-01-24 (T08's LIQ_FROM)
        n = len(cal)
        B = build_book(p, cal, MK, corr)
        a_r3 = int(np.searchsorted(cal.values, np.datetime64(R3_START_W1 if wname == "w1" else LIVE_START), side="left"))
        V = make_view(B, 0, n, "lbes")
        Vliq = make_view(B, 0, n, "liq")
        Vr3 = make_view(B, a_r3, n, "lbes")
        dec = decisions_for_window(p, cal, 0, n, wname, masters, gmaster)
        dec3 = decisions_for_window(p, cal, a_r3, n, wname, masters, gmaster)
        s, gs, di = dec["state"].values.astype(int), dec["g"].values.astype(int), dec["decision_idx"].values
        s3, gs3, di3 = dec3["state"].values.astype(int), dec3["g"].values.astype(int), dec3["decision_idx"].values
        nd = len(s)
        full = rule_for(s, gs, di, n, str(cal[0].date()), str(cal[-1].date()))
        r3 = rule_for(s3, gs3, di3, n - a_r3, str(cal[a_r3].date()), str(cal[-1].date()), bounds_from=None if wname == "w1" else full)
        D["rule"][p] = {"full": full, "r3": r3}
        bt = basket_table(B)
        D["baskets"].append(bt)
        D["meta"][p] = dict(sessions=n, decisions=nd, t0=str(cal[0].date()), end=str(cal[-1].date()), r3_t0=str(cal[a_r3].date()), baskets=len(bt),
                            sessions_without_any_d18_bar=B["sessions_all_stocks_no_bar"], skipped_dropped=[str(pd.Timestamp(x).date()) for x in B["skipped"]],
                            stale=int(((dec["label_age_days"] >= 5) & (dec["j"] > 0)).sum()))
        D["dec"].extend([dec.assign(_win="full"), dec3.assign(_win="r3")])
        T6 = {r: mk_T(r, s, gs, di) for r in RULES}
        T6_3 = {r: mk_T(r, s3, gs3, di3) for r in RULES}
        # constant mixes
        f_state = s.sum() / nd
        gw_t = np.where(gs == 1, 0.8, 0.2).astype(float)
        mixT = {"constant_mix": (dict(e=np.full(nd, f_state), gw=np.full(nd, 0.5), dec_idx=di, regime=None, variant=None), "mix", f_state * nd),
                "constant_mix_timed": (dict(e=np.full(nd, f_state), gw=gw_t, dec_idx=di, regime=None, variant=None), "mix", f_state * nd),
                "sleeve_only": (dict(e=np.zeros(nd), gw=np.full(nd, 0.5), dec_idx=di, regime=None, variant=None), "sleeve0", 0.0),
                "sleeve_only_timed": (dict(e=np.zeros(nd), gw=gw_t, dec_idx=di, regime=None, variant=None), "sleeve0", 0.0),
                "hold_parent": (T_hold(nd) | dict(dec_idx=di), "hold", float(nd))}
        for r in RULES:
            e_, gw_ = T6[r]["e"], T6[r]["gw"]
            f_r = float(e_.mean())
            gwb = float(((1 - e_) * gw_).sum() / (1 - e_).sum())
            D["mix_params"][(p, r)] = (f_r, gwb)
            mixT[f"cmix_{r}"] = (dict(e=np.full(nd, f_r), gw=np.full(nd, gwb), dec_idx=di, regime=None, variant=None), "mix", f_r * nd)
        D["books"][p] = dict(B=B, V=V, Vliq=Vliq, Vr3=Vr3, dec_idx=di, dec_idx_r3=di3, s=s, s_r3=s3, g=gs, g_r3=gs3, T6=T6, T6_3=T6_3, pub=pub, a_r3=a_r3)

        def add(window, cash, kind, bps, r, wk):
            st = stats_of(r["nav"])
            kinds = [x["kind"] for x in r["trades"]]
            st.update(book=p, window=window, cash=cash, cost_bps=bps, kind=kind, trades=len(r["trades"]),
                      cost_paid=float(sum(x["cost"] for x in r["trades"])), closed_rel=r["closed_rel"], n_segments=r["n_segments"],
                      end_from_segments=r["end_from_segments"], invested_weeks=float(wk),
                      sleeve_trades=sum(1 for k in kinds if k == "sleeve_rebalance"), regime_trades=sum(1 for k in kinds if k in ("regime_in", "regime_out")),
                      basket_trades=sum(1 for k in kinds if k == "basket_change"), switch_trades=sum(1 for k in kinds if k in ("switch_in", "switch_out")))
            D["stats"].append(st)

        navs_full20 = {}
        for bps in COSTS:
            runs = {}
            for r in RULES:
                runs[r] = (simulate(V, T6[r], bps, "rule", closed_form=True, positions=True), float((T6[r]["e"] > 0).sum()))
            for kind, (T_, mode, wk) in mixT.items():
                runs[kind] = (simulate(V, T_, bps, mode), wk)
            for kind, (r, wk) in runs.items():
                add("full", "lbes", kind, bps, r, wk)
                D["nav"].append(pd.DataFrame(dict(book=p, date=[str(d.date()) for d in cal], cost_bps=bps, run=kind, nav=r["nav"])))
                for x in r["trades"]:
                    D["trades"].append(dict(book=p, window="full", cost_bps=bps, run=kind, **x))
                if kind in RULES and bps == HEADLINE_COST:
                    navs_full20[kind] = r["nav"]
                    for dt, nm, u in r["positions"]:
                        D["positions"].append(dict(book=p, cost_bps=bps, run=kind, date=dt, instrument=nm, units=u))
                if kind == "hold_parent" and bps == 0.0:
                    D["hold0"][p] = r["nav"]
        # R2 (LIQUIDCASE cash) and R3, 20.8 bps, the six rules
        for r in RULES:
            add("full", "liq", r, HEADLINE_COST, simulate(Vliq, T6[r], HEADLINE_COST, "rule"), float((T6[r]["e"] > 0).sum()))
        navs_r3 = {}
        for r in RULES:
            rr = simulate(Vr3, T6_3[r], HEADLINE_COST, "rule")
            navs_r3[r] = rr["nav"]
            add("r3", "lbes", r, HEADLINE_COST, rr, float((T6_3[r]["e"] > 0).sum()))
        hold_r3 = simulate(Vr3, dict(T_hold(len(di3)), dec_idx=di3), 0.0, "hold")["nav"]
        # regime ledger
        D["ledger"] += ledger_rows("full", p, full, V, di, navs_full20, D["hold0"][p])
        D["ledger"] += ledger_rows("r3", p, r3, Vr3, di3, navs_r3, hold_r3)
        # R7 (W1 only)
        if wname == "w1":
            r7 = r7_derive(B, V, T6, di, cal)
            D["r7"][p] = r7
            for kind, bps, r in r7["sims"]:
                wk = float(nd) if kind.startswith("hold_parent") else (float(T6[kind.split("_r7_")[0]]["e"].sum()))
                add("full", "lbes", kind, bps, r, wk)
                D["nav"].append(pd.DataFrame(dict(book=p, date=[str(d.date()) for d in cal], cost_bps=bps, run=kind, nav=r["nav"])))
        # V4(b): one instrument at weight 1, 0 cost, always in = close / first close
        W0 = B["W"][V["k0"]]
        res = []
        for i in np.flatnonzero(W0 > 0):
            W1 = np.zeros_like(B["W"]); W1[:, i] = 1.0
            r = simulate(V, T_hold(nd) | dict(dec_idx=di), 0.0, "hold", W_override=W1)
            tgt = V["C"][:, i] / V["C"][0, i]
            res.append((B["S"][i], float(np.max(np.abs(r["nav"] - tgt) / np.abs(tgt)))))
        D["one_instrument"][p] = res
        # G0 (W2) / seam (W1)
        if wname == "w2":
            D["g0"].extend(always_in_rows(p, pd.Series(D["hold0"][p], index=cal), pub.loc[cal]))
        else:
            pubn = load_published_nav(p)
            cal17 = pubn.index[pubn.index <= END_D17]
            MK17 = market_arrays(cal17, gold, mcx, lbes, liq)
            B17 = build_book(p, cal17, MK17, corr)
            V17 = make_view(B17, 0, len(cal17))
            nv = simulate(V17, T_hold(1), 0.0, "hold")["nav"]
            pv = pubn.loc[cal17].values
            D["seam"].append(dict(book=p, first=str(cal17[0].date()), last=str(cal17[-1].date()), year_gap_pp=float((nv[-1] / nv[0] - pv[-1] / pv[0]) * 100.0),
                                  limit_pp=SEAM_PP))
        if verbose:
            print(f"[{wname} {time.time()-t:6.1f}s] {p}: derived (sessions {n}, decisions {nd}, stocks {len(B['S'])}, baskets {len(bt)}, "
                  f"OUT-SELL weeks {full['weeks_OUT_SELL']} in {full['OUT_SELL_spells']} spells)", flush=True)
    D["dec"] = pd.concat(D["dec"], ignore_index=True)
    D["nav"] = pd.concat(D["nav"], ignore_index=True)
    D["stats"] = pd.DataFrame(D["stats"])
    D["trades"] = pd.DataFrame(D["trades"])
    D["positions"] = pd.DataFrame(D["positions"])
    D["baskets"] = pd.concat(D["baskets"], ignore_index=True)
    D["ledger"] = pd.DataFrame(D["ledger"])
    D["reads"] = {k: dict(v) for k, v in READS.items()}
    return D


# ----------------------------------------------------------------------------------------
# the checks, part 1 (data, signals, regimes, NAVs, trades, ledger, regression, identities)
# ----------------------------------------------------------------------------------------
STEP1 = json.load(open(STEP1_JSON)) if STEP1_JSON.exists() else None
STORED_NAV_MAP = {"strategy": "80-orig", "strategy_fixed50": "50-orig", "hold_parent": "hold_parent", "constant_mix": "constant_mix",
                  "constant_mix_timed": "constant_mix_timed", "sleeve_only": "sleeve_only", "sleeve_only_timed": "sleeve_only_timed"}
STORED_R7_MAP = {f"{a}_r7_{v}": f"{b}_r7_{v}" for v in ("flagged", "noexport") for a, b in (("strategy", "80-orig"), ("strategy_fixed50", "50-orig"), ("hold_parent", "hold_parent"))}
T06_NAV_MAP = {"strategy": "50-orig", "hold_parent": "hold_parent", "sleeve_only": "sleeve_only"}
DRAW_STAT_NUM = ["end_nav", "cagr", "max_dd", "vol", "ulcer", "days_below_10pct", "longest_underwater", "calmar", "sessions", "invested_weeks", "n_in_spells",
                 "n_out_spells", "sessions_invested", "g_buy_weeks", "n_buy_spells", "n_sell_spells"]
DRAW_STAT_STR = ["in_lengths", "out_lengths", "g_buy_lengths", "g_sell_lengths", "spell_sig", "strategy_sig", "g_spell_sig", "real_g_spell_sig"]
STR_COLS_DRAWS = {c_: str for c_ in ("in_lengths", "out_lengths", "g_buy_lengths", "g_sell_lengths", "spell_sig", "strategy_sig", "g_spell_sig", "real_g_spell_sig")}


def required_through(wname, key, row, end):
    """Latest date an approved row must reach (None: exempt by design). W1: the window's end (published NAVs: 2019-12-31, V4 seam); W2: END, except the
    D12 de-spike range and the D19 / D05 basket rows (their newest rows are earlier than the window's end by design)."""
    if "published_nav" in key and wname == "w1":
        return END_D17
    if wname == "w2" and row["id"] in THROUGH_EXEMPT_IDS:
        return None
    return end


def read_stored_nav(path, run_map, books, cutoff=None):
    d = pd.read_csv(path)
    d = d[d["book"].isin(books) & d["run"].isin(list(run_map))].copy()
    if cutoff is not None:
        d = d[d["date"] <= str(cutoff.date())]
    d["run"] = d["run"].map(run_map)
    d["cost_bps"] = r4(d["cost_bps"])
    d["date"] = d["date"].astype(str)
    return d[["book", "date", "cost_bps", "run", "nav"]]


def compare_part1(wname, D, E, BK):
    C = {}
    cal_end = D["END"]
    RULE = D["rule"]
    WINDOWS = ["full", "r3"]
    NUMS = ["end_nav", "cagr", "max_dd", "vol"]
    NUMS_ALL = NUMS + ["ulcer", "calmar"]
    INTS = ["days_below_10pct", "longest_underwater", "sessions"]
    CNT = ["trades", "cost_paid", "invested_weeks", "sleeve_trades", "regime_trades", "basket_trades", "switch_trades"]
    dec_m = D["dec"]
    dec_full = dec_m[dec_m["_win"] == "full"].drop(columns=["_win"])
    dec_r3 = dec_m[dec_m["_win"] == "r3"].drop(columns=["_win"])
    ENAMES = [f"e_{r}" for r in RULES] + [f"gw_{r}" for r in RULES]
    wlabel_e = "w1" if wname == "w1" else "w2"
    first_book_dec = dec_full[dec_full["book"] == dec_full["book"].iloc[0]]

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
                rt = required_through(wname, key, row, cal_end)
                if ok and rt is not None and row["through"].lower() != "n/a":
                    ok = pd.Timestamp(row["through"]) >= rt
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
        for need in ("through", "bytes", "sha256", "approved_row", "usable_from"):
            if need not in cols:
                c.miss(f"inputs.csv column {need}")
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
            c.compared += 1
            if row["id"] in NOT_READ_IDS:
                c.failed += 1; c.fail(f"inputs.csv lists {key} (row {row['id']}), which T14.md section 3 lists under 'Not read'")
            sha = str(r[cols["sha256"]]).lower() if "sha256" in cols else ""
            c.compared += 2
            if not sha.startswith(row["sha"]):
                c.failed += 1; c.fail(f"sha256 of {key} in inputs.csv ({sha[:16]}) does not start with the approved prefix {row['sha']}")
            disk = sha256_file(AA / key) if (AA / key).exists() else None
            if disk is None or (sha and disk != sha and not disk.startswith(sha)):
                c.failed += 1; c.fail(f"sha256 of {key} in inputs.csv differs from the file on disk")
            if "bytes" in cols and (AA / key).exists():
                c.compared += 1
                if int(r[cols["bytes"]]) != (AA / key).stat().st_size:
                    c.failed += 1; c.fail(f"bytes of {key} in inputs.csv ({r[cols['bytes']]}) differ from the file on disk")
            if "approved_row" in cols:
                c.compared += 1
                if str(r[cols["approved_row"]]).strip() != f"APPROVED {row['id']}":
                    c.failed += 1; c.fail(f"approved_row of {key} in inputs.csv ({r[cols['approved_row']]!r}) is not 'APPROVED {row['id']}'")
            if "through" in cols:
                c.compared += 1
                th = str(r[cols["through"]]).strip()
                rt = required_through(wname, key, row, cal_end)
                if rt is not None and row["through"].lower() != "n/a" and pd.Timestamp(row["through"]) < rt:
                    c.failed += 1; c.fail(f"approved through-date of {key} ({row['through']}) does not cover the window's end")
                if th.lower() not in ("n/a", "nan") and row["through"].lower() != "n/a" and th != row["through"]:
                    c.failed += 1; c.fail(f"through of {key} in inputs.csv ({th}) differs from APPROVED_DATA.md ({row['through']})")
            if "usable_from" in cols:
                c.compared += 1
                uv = r[cols["usable_from"]]
                uv = None if (uv is None or (isinstance(uv, float) and np.isnan(uv)) or str(uv).strip() in ("", "nan", "None")) else str(uv).strip()
                if uv != row["usable_from"]:
                    c.failed += 1; c.fail(f"usable_from of {key} in inputs.csv ({uv}) differs from the registry's marker ({row['usable_from']})")
        for key in sorted(set(READS) - listed):
            c.compared += 1; c.failed += 1; c.fail(f"a file needed to rebuild the run is not in inputs.csv: {key}")
        extra = sorted(listed - set(READS))
        if extra:
            c.notes.append(f"inputs.csv lists {len(extra)} file(s) the verifier did not read (engine-side gate reads): {[x.split('/')[-1] for x in extra[:6]]}")
        c.notes.append(f"{len(READS)} files read by the verifier, {len(listed)} listed in inputs.csv")
    run_check(C, "C-data", c_data)

    def c_sc100(c):
        for first, fn in (("2011-11-24", lambda f: rd(F_MASTER["SC100"], f)), ("2004-01-01", lambda f: rd(F_MASTER["SC100"], f)),
                          ("2011-10-02", lambda f: _read_master(F_MASTER["SC100"], f))):
            c.compared += 1
            try:
                fn(first)
                c.failed += 1; c.fail(f"the verifier did not refuse a Smallcap 100 signal read from {first}")
            except RuntimeError:
                pass
        c.compared += 1
        try:
            rd(F_MASTER["SC100"])
            c.failed += 1; c.fail("a restricted file was registered without a first read date")
        except RuntimeError:
            pass
        rd(F_MASTER["SC100"], SC100_SIGNAL_FROM)                 # restore the legitimate registration (the refusals above must not leave a trace)
        c.compared += 1
        if APPROVED[F_MASTER["SC100"]]["usable_from"] != "2011-11-25":
            c.failed += 1; c.fail("the registry row of the Smallcap 100 Master carries no usable-from 2011-11-25")
        c.compared += 1
        if READS[F_MASTER["SC100"]]["first_date"] != "2011-11-25":
            c.failed += 1; c.fail(f"the verifier read the Smallcap 100 Master from {READS[F_MASTER['SC100']]['first_date']}")
        c.compared += 1
        if (dec_m["label_SC100"] < "2011-11-25").any():
            c.failed += 1; c.fail("a Smallcap 100 decision reads a Master row dated before 2011-11-25")
        for nm in ("decisions.csv", "decisions_r3.csv"):
            d0 = E.get(nm)
            if d0 is not None and "label_SC100" in d0.columns:
                c.compared += 1
                if (d0["label_SC100"].astype(str) < "2011-11-25").any():
                    c.failed += 1; c.fail(f"the engine's {nm} reads a Smallcap 100 Master row dated before 2011-11-25")
    run_check(C, "C-sc100-restriction", c_sc100)

    # ------------------------------------------------------------------ the frozen text's numbers and Step 1's file against the verifier's own derivation
    def c_frozen(c):
        fz = FROZEN[wname]
        for p in BK:
            for window in WINDOWS:
                R = RULE[p][window]
                f = fz.get(window, {})
                pairs = []
                if wname == "w2" and p == "SCMO_0007":
                    exp_weeks = f.get("weeks_0007", f.get("weeks")) if window == "full" else f.get("weeks")
                else:
                    exp_weeks = f.get("weeks")
                if exp_weeks is not None:
                    pairs.append(("weeks", R["weeks"], exp_weeks))
                for nm, mine, key in (("first_state", R["first_state"], "first_state"), ("weeks_OUT_SELL", R["weeks_OUT_SELL"], "out_sell"),
                                      ("OUT_SELL_spells", R["OUT_SELL_spells"], "sell_spells"), ("round_trips", min(R["in_spells"], R["out_spells"]), "round_trips"),
                                      ("OUT_SELL_lengths", R["OUT_SELL_lengths"], "sell_lengths")):
                    if key in f:
                        pairs.append((nm, mine, f[key]))
                if window == "full" and not (wname == "w2" and p == "SCMO_0007"):
                    for nm, mine, key in (("weeks_IN", R["weeks_IN"], "in_"), ("weeks_OUT_BUY", R["weeks_OUT_BUY"], "out_buy")):
                        if key in f:
                            pairs.append((nm, mine, f[key]))
                if "trades" in f and not (wname == "w2" and p == "SCMO_0007"):
                    for r_, v_ in f["trades"].items():
                        pairs.append((f"trades_due[{r_}]", R["trades_due"][r_], v_))
                if wname == "w2" and window == "full":
                    pairs.append(("bounds", dict(lo_in=R["bounds"]["lo_in"], hi_in=R["bounds"]["hi_in"], lo_out=R["bounds"]["lo_out"], hi_out=R["bounds"]["hi_out"],
                                                 lo_buy=R["g_bounds"]["lo_buy"], hi_buy=R["g_bounds"]["hi_buy"], lo_sell=R["g_bounds"]["lo_sell"], hi_sell=R["g_bounds"]["hi_sell"]),
                                  dict(lo_in=2, hi_in=46, lo_out=2, hi_out=40, lo_buy=2, hi_buy=68, lo_sell=2, hi_sell=28)))
                if "tuples" in f:
                    G = R["g"]
                    for nm, k, S, lo, hi in (("in_", R["in_spells"], R["S_in"], R["bounds"]["lo_in"], R["bounds"]["hi_in"]),
                                             ("out", R["out_spells"], R["S_out"], R["bounds"]["lo_out"], R["bounds"]["hi_out"]),
                                             ("buy", G["in_spells"], G["S_in"], R["g_bounds"]["lo_buy"], R["g_bounds"]["hi_buy"]),
                                             ("sell", G["out_spells"], G["S_out"], R["g_bounds"]["lo_sell"], R["g_bounds"]["hi_sell"])):
                        pairs.append((f"tuples[{nm}]", n_ways(k, S, lo, hi), f["tuples"][nm]))
                for nm, mine, want in pairs:
                    c.compared += 1
                    if mine != want:
                        c.failed += 1; c.fail(f"{p}|{window} {nm}: verifier {mine!r} vs T14.md {want!r}")
            # baskets (W1: 19 per book, the first the initial one on 2014-09-01)
            if wname == "w1":
                bt = D["baskets"][D["baskets"]["book"] == p]
                c.compared += 2
                if len(bt) != N_BASKETS_W1 or bt["session_date"].iloc[0] != "2014-09-01":
                    c.failed += 1; c.fail(f"{p}: {len(bt)} baskets T0 to END (T11 / Step 1: 19, the first on 2014-09-01)")
                if bt["available_date"].iloc[-1] != "2018-12-17":
                    c.failed += 1; c.fail(f"{p}: last basket effective {bt['available_date'].iloc[-1]} (T11: 2018-12-17)")
                if D["meta"][p]["skipped_dropped"] and any(pd.Timestamp(x) >= pd.Timestamp("2014-09-01") and pd.Timestamp(x) <= cal_end for x in D["meta"][p]["skipped_dropped"]):
                    c.failed += 1; c.fail(f"{p}: a skipped basket inside the window")
                c.compared += 1
                if "2017-10-19" not in D["meta"][p]["sessions_without_any_d18_bar"]:
                    c.failed += 1; c.fail(f"{p}: 2017-10-19 has D18 bars for some stock (T11: none)")
        if STEP1 is None:
            c.notes.append("logs/step_1_spell_counts.json not found; not compared"); return
        for p in BK:
            for window in WINDOWS:
                if wname == "w1":
                    e = STEP1["w1"]["full" if window == "full" else "r3"]
                else:
                    e = STEP1["w2"][p]["full" if window == "full" else "live"]
                R = RULE[p][window]
                G = R["g"]
                pairs = [("weeks", R["weeks"]), ("sessions", R["sessions"]), ("first_state", R["first_state"]), ("last_state", R["last_state"]),
                         ("in_spells", R["in_spells"]), ("out_spells", R["out_spells"]), ("weeks_in", R["S_in"]), ("weeks_out", R["S_out"]),
                         ("round_trips", min(R["in_spells"], R["out_spells"])), ("in_lengths", R["in_lengths"]), ("out_lengths", R["out_lengths"]),
                         ("start", R["start"]), ("end", R["end"]), ("weeks_IN", R["weeks_IN"]), ("weeks_OUT_BUY", R["weeks_OUT_BUY"]),
                         ("weeks_OUT_SELL", R["weeks_OUT_SELL"]), ("OUT_SELL_spells", R["OUT_SELL_spells"]), ("OUT_SELL_lengths", R["OUT_SELL_lengths"]),
                         ("OUT_BUY_spells", R["OUT_BUY_spells"]), ("OUT_BUY_lengths", R["OUT_BUY_lengths"]), ("g_flips", R["g_flips"]),
                         ("g_first_state", G["first_state"])]
                for k_, mv in pairs:
                    if k_ in e:
                        c.compared += 1
                        if mv != e[k_]:
                            c.failed += 1; c.fail(f"{p}|{window} {k_}: verifier {mv!r} vs logs/step_1_spell_counts.json {e[k_]!r}")
                if "OUT_SELL_spell_table" in e:
                    c.compared += 1
                    di = RULE[p][window]["dec_idx"]
                    cal_ = D["books"][p]["V"]["cal"] if window == "full" else D["books"][p]["Vr3"]["cal"]
                    reg = R["regime"]
                    mine_t = []
                    for a_, b_ in R["sell_spells_idx"]:
                        mine_t.append(dict(first_decision=str(cal_[di[a_]].date()), last_decision=str(cal_[di[b_]].date()), weeks=b_ - a_ + 1,
                                           entered_from="start" if a_ == 0 else REG_NAMES[reg[a_ - 1]],
                                           exited_to="window end" if b_ + 1 >= len(reg) else REG_NAMES[reg[b_ + 1]]))
                    if mine_t != e["OUT_SELL_spell_table"]:
                        c.failed += 1; c.fail(f"{p}|{window} OUT-SELL spell table differs from Step 1's: {mine_t[:2]} vs {e['OUT_SELL_spell_table'][:2]}")
                for r_, v_ in e.get("rules", {}).items():
                    for k_, mv in (("trades_from_regime_and_gold_changes", R["trades_due"][r_]), ("weeks_with_e_0.5", R["weeks_e_half"][r_]),
                                   ("weeks_holding_no_parent_no_gold", R["weeks_no_parent_no_gold"][r_])):
                        c.compared += 1
                        if mv != v_[k_]:
                            c.failed += 1; c.fail(f"{p}|{window} rule {r_} {k_}: verifier {mv!r} vs Step 1 {v_[k_]!r}")
                c.compared += 1
                if not (min(R["in_spells"], R["out_spells"]) >= 4 and R["OUT_SELL_spells"] >= 4):
                    c.failed += 1; c.fail(f"{p}|{window}: not reportable (fewer than 4 round trips or OUT-SELL spells)")
            if wname == "w1":
                eb = STEP1["baskets_w1"][p]
                bt = D["baskets"][D["baskets"]["book"] == p]
                c.compared += 2
                if eb["baskets_T0_to_END"] != len(bt):
                    c.failed += 1; c.fail(f"{p}: Step 1 counts {eb['baskets_T0_to_END']} baskets, verifier {len(bt)}")
                if eb["effective_dates"] not in (bt["available_date"].tolist(), bt["session_date"].tolist()):
                    c.failed += 1; c.fail(f"{p}: Step 1's effective basket dates differ from the verifier's")
    run_check(C, "C-frozen-counts", c_frozen)

    # ------------------------------------------------------------------ decisions, regimes, point-in-time
    def c_dec(c):
        s_cols = ["trade_date", "sign_Nifty100", "sign_MC100", "sign_SC100", "label_Nifty100", "label_MC100", "label_SC100", "latest_label", "decision_date",
                  "all_three_buy", "sign_MAUc1", "label_MAUc1", "regime", "window"]
        n_cols = ["decision_idx", "label_age_days", "state", "g"] + ENAMES
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
        mine = dec_full[dec_full["book"].isin(BK)][["book", "decision_date", "decision_idx", "regime"]]
        compare_frames(c, mine, ev[["book", "decision_date", "decision_idx", "regime"]], ["book", "decision_date"], num_cols=["decision_idx"], str_cols=["regime"], tol=0.0)
    run_check(C, "C-regimes", c_regimes)

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
                    if not np.array_equal(real_npz[key].astype(np.uint8), RULE[p][w][k]):
                        c.failed += 1; c.fail(f"real_states.npz {key} differs from the verifier's series")
    run_check(C, "C-real-states", c_real_states)

    date_idx = {p: {str(d.date()): i for i, d in enumerate(D["books"][p]["V"]["cal"])} for p in D["books"]}

    def c_pit(c):
        """V2: labels <= decision date, every trade after its decision (the next session), a basket change on a basket's availableDate session."""
        lcs = ["label_Nifty100", "label_MC100", "label_SC100", "label_MAUc1"]
        for fn in ("decisions.csv", "decisions_r3.csv"):
            ev = E.get(fn, c)
            if ev is None:
                continue
            for lc in lcs:
                if lc not in ev.columns:
                    c.miss(f"{fn} column {lc}"); continue
                ok = (ev[lc].astype(str) <= ev["decision_date"].astype(str)).values
                c.compared += len(ev); c.failed += int((~ok).sum())
                if (~ok).any(): c.fail("label after decision date: %s" % ev[~ok].iloc[0][["book", "j", "decision_date", lc]].to_dict())
            tdm = ev["trade_date"].notna()
            ok = (ev.loc[tdm, "trade_date"].astype(str) > ev.loc[tdm, "decision_date"].astype(str)).values
            c.compared += int(tdm.sum()); c.failed += int((~ok).sum())
            if (~ok).any(): c.fail("trade not after decision: %s" % ev.loc[tdm][~ok].iloc[0][["book", "j", "decision_date", "trade_date"]].to_dict())
        tr = E.get("trades.csv", c)
        evd = E.get("decisions.csv")
        if tr is not None and evd is not None:
            tr = tr[tr["book"].isin(BK)]
            dd = tr[tr["dec_j"].notna()].copy()
            dd["dec_j"] = dd["dec_j"].astype(int)
            m = dd.merge(evd[["book", "j", "decision_date", "trade_date"]], left_on=["book", "dec_j"], right_on=["book", "j"], how="left")
            okk = m["decision_date"].notna() & (m["date"].astype(str) > m["decision_date"].astype(str)) & (m["date"].astype(str) == m["trade_date"].astype(str))
            c.compared += len(m); c.failed += int((~okk).sum())
            if (~okk).any(): c.fail("a decision-driven trade is not on the session after its decision: %s" % m[~okk].iloc[0][["book", "run", "date", "dec_j"]].to_dict())
            keyset = set(zip(D["baskets"]["book"], D["baskets"]["session_date"].astype(str)))
            bc = tr[tr["kind"] == "basket_change"]
            okb = np.array([(b, str(d)) in keyset for b, d in zip(bc["book"], bc["date"])], dtype=bool)
            c.compared += len(bc); c.failed += int((~okb).sum())
            if (~okb).any(): c.fail("basket change not on a basket's availableDate session: %s" % bc[~okb].iloc[0][["book", "run", "date"]].to_dict())
        for lc in lcs:
            ok = (dec_m[lc] <= dec_m["decision_date"]).values
            c.compared += len(dec_m); c.failed += int((~ok).sum())
        mt = dec_m["trade_date"].notna()
        ok = (dec_m.loc[mt, "trade_date"] > dec_m.loc[mt, "decision_date"]).values
        c.compared += int(mt.sum()); c.failed += int((~ok).sum())
        for _, r in D["baskets"].iterrows():
            c.compared += 1
            cal_ = D["books"][r["book"]]["V"]["cal"]
            i = int(r["idx"])
            if cal_[i] < pd.Timestamp(r["available_date"]) or (i > 0 and cal_[i - 1] >= pd.Timestamp(r["available_date"])):
                c.failed += 1; c.fail(f"basket {r.to_dict()}: effect session is not the first session on or after availableDate")
        c.compared += 1
        if any(m_["end"] != str(cal_end.date()) for m_ in D["meta"].values()):
            c.failed += 1; c.fail(f"a book's calendar does not end at {cal_end.date()}")
    run_check(C, "C-pit", c_pit)

    def c_gold(c):
        wk = load_mauc1_weekly(wname)
        gd, gsg = D["gmaster"]
        mm = pd.DataFrame({"review": pd.to_datetime(gd), "msign": gsg})
        j = mm.merge(wk[["review", "SIGN", "signal"]], on="review", how="inner")
        c.compared += len(j)
        bad = (j["msign"] != j["SIGN"]) | ((j["signal"] == 1.0) != (j["SIGN"] == "BUY"))
        c.failed += int(bad.sum())
        if bad.any(): c.fail("Master_MAUc1 SIGN / weekly csv SIGN / signal disagree: %s" % j[bad].iloc[0].to_dict())
        c.notes.append(f"Master_MAUc1 rows {len(mm)}, weekly csv rows {len(wk)}, shared dates {len(j)}")
        wd = wk["review"].values
        for r in dec_full.itertuples():
            pos = int(np.searchsorted(wd, np.datetime64(pd.Timestamp(r.decision_date)), side="right") - 1)
            c.compared += 1
            if pos < 0 or int(wk["signal"].iloc[pos]) != r.g or wk["SIGN"].iloc[pos] != r.sign_MAUc1 or str(wk["review"].iloc[pos].date()) != r.label_MAUc1:
                c.failed += 1; c.fail(f"g at {r.book} j={r.j} {r.decision_date}: Master {r.sign_MAUc1} (row {r.label_MAUc1}) vs weekly csv row {wk['review'].iloc[pos].date() if pos >= 0 else None}")
    run_check(C, "C-gold", c_gold)

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
    if env_all is not None:
        env_all = env_all[env_all["book"].isin(BK)].copy()
        env_all["cost_bps"] = r4(env_all["cost_bps"])
        env_all["date"] = env_all["date"].astype(str)

    def c_stats_all(c):
        """Every statistic of every stats.csv row (all kinds, windows, cash legs, costs): the six rules, the comparators, the constant mixes at each rule's
        own averages, R2 (liq), R3 and, on W1, the R7 variants (statistics only: trades, invested weeks of R7 rows are not compared, see step_3_log.md)."""
        if est_all is None:
            E.get("stats.csv", c); return
        for col in NUMS_ALL + INTS + CNT:
            if col not in est_all.columns:
                c.miss(f"stats.csv column {col}")
        keys = ["book", "window", "cash", "cost_bps", "kind"]
        is_r7 = mst["kind"].str.contains("_r7_")
        e_r7 = est_all["kind"].astype(str).str.contains("_r7_")
        compare_frames(c, mst[~is_r7][keys + NUMS_ALL + INTS + CNT], est_all[~e_r7][keys + NUMS_ALL + INTS + CNT], keys, num_cols=NUMS_ALL + INTS + CNT)
        compare_frames(c, mst[is_r7][keys + NUMS_ALL + INTS], est_all[e_r7][keys + NUMS_ALL + INTS], keys, num_cols=NUMS_ALL + INTS)
    run_check(C, "C-stats-all", c_stats_all)

    def c_nav(c):
        """The daily NAV of every run at every cost (and the six R7 variants x 2 on W1): the headline cell's whole daily_nav.csv."""
        if env_all is None:
            E.get("daily_nav.csv", c); return
        compare_frames(c, mnv, env_all, ["book", "date", "cost_bps", "run"], num_cols=["nav"])
    run_check(C, "C-nav", c_nav)

    def c_closed(c):
        for st in D["stats"].itertuples():
            if st.kind not in RULES or st.window != "full" or st.cash != "lbes":
                continue
            r_ = abs(st.end_from_segments - st.end_nav) / st.end_nav
            c.compared += 1
            c.worst_rel = max(c.worst_rel, r_, st.closed_rel)
            if r_ > TOL or st.closed_rel > TOL:
                c.failed += 1; c.fail(f"{st.book} {st.kind} cost {st.cost_bps}: segment product {st.end_from_segments!r} vs NAV {st.end_nav!r}, within-segment rel {st.closed_rel:.2e}")
            if est_all is None:
                continue
            e_ = est_all[(est_all["window"] == "full") & (est_all["cash"] == "lbes") & (est_all["book"] == st.book) & (est_all["cost_bps"] == round(st.cost_bps, 4))
                         & (est_all["kind"] == st.kind)]
            if len(e_):
                c.compared += 1
                rr = abs(st.end_from_segments - float(e_["end_nav"].iloc[0])) / float(e_["end_nav"].iloc[0])
                c.worst_rel = max(c.worst_rel, rr)
                if rr > TOL:
                    c.failed += 1; c.fail(f"{st.book} {st.kind} {st.cost_bps}: closed-form end NAV vs evidence end_nav rel {rr:.2e}")
            else:
                c.miss(f"evidence stats row for {st.book} {st.kind} {st.cost_bps}")
        if est_all is None:
            E.get("stats.csv", c)
    run_check(C, "C-nav-closed-form", c_closed)

    def c_parent_nav(c):
        """W1: the rebuilt parent NAV file: base 1.0 at T0 in every column, no '#' line, the caption in its sidecar, numbers equal the verifier's."""
        if wname != "w1":
            c.notes.append("W1 only"); return
        pn = E.get("parent_nav_2014-09-01_2019-01-02.csv", c)
        side = E.get("parent_nav_2014-09-01_2019-01-02.md", c)
        if side is not None:
            c.compared += 1
            if "not validated against a published NAV before 2019-01-02" not in side or "rebuilt from the parent's baskets and Eikon prices" not in side:
                c.failed += 1; c.fail("the sidecar caption of the rebuilt parent NAV is missing or altered")
        p_ = E.path("parent_nav_2014-09-01_2019-01-02.csv")
        if p_ is not None:
            c.compared += 1
            if p_.read_text(encoding="utf-8").lstrip().startswith("#"):
                c.failed += 1; c.fail("the parent NAV csv starts with a '#' comment line")
        if pn is None:
            return
        pn = pn[pn["book"].isin(BK)].copy()
        pn["date"] = pn["date"].astype(str)
        cmap = {"hold_parent_0bps": ("hold_parent", 0.0), "hold_parent_20.8bps": ("hold_parent", 20.8)}
        cmap.update({f"{r}_20.8bps": (r, 20.8) for r in RULES})
        first = pn.sort_values("date").groupby("book").head(1)
        for col in cmap:
            if col not in pn.columns:
                c.miss(f"parent NAV column {col}"); continue
            c.compared += len(first)
            bad = ((first[col].astype(float) - 1.0).abs() > 1e-12)
            c.failed += int(bad.sum())
            if bad.any(): c.fail(f"parent NAV {col}: first row is not 1.0")
            run, bps = cmap[col]
            m = mnv[(mnv["run"] == run) & (mnv["cost_bps"] == bps)][["book", "date", "nav"]].rename(columns={"nav": col})
            compare_frames(c, m, pn[["book", "date", col]], ["book", "date"], num_cols=[col])
    run_check(C, "C-parent-nav", c_parent_nav)

    def c_cmix(c):
        ev = E.get("constant_mix_params.csv", c)
        if ev is None:
            return
        ev = ev[ev["book"].isin(BK)]
        rows = [dict(book=p, rule=r, f=D["mix_params"][(p, r)][0], gw_bar=D["mix_params"][(p, r)][1]) for p in BK for r in RULES]
        compare_frames(c, pd.DataFrame(rows), ev[["book", "rule", "f", "gw_bar"]], ["book", "rule"], num_cols=["f", "gw_bar"], tol=1e-12)
    run_check(C, "C-cmix-params", c_cmix)

    def c_ledger(c):
        ev = E.get("regime_ledger.csv", c)
        if ev is None:
            return
        ev = ev[ev["book"].isin(BK)]
        led = D["ledger"]
        num = ["weeks", "parent_return", "goldbees_return", "cash_return"] + [f"ret_{r}" for r in RULES]
        s_ = ["first_decision", "last_decision", "span_from_close", "span_to_close", "entered_from", "exited_to"]
        r3_present = (ev["window"] == "r3").any()
        led_cmp = led if r3_present else led[led["window"] == "full"]
        compare_frames(c, led_cmp[led_cmp["book"].isin(BK)], ev, ["window", "book", "spell_no"], num_cols=num, str_cols=s_)
        # count per (window, book) equals the number of OUT-SELL spells of the verifier's series
        for p in BK:
            for w in WINDOWS if r3_present else ["full"]:
                c.compared += 1
                n_e = int(((ev["book"] == p) & (ev["window"] == w)).sum())
                if n_e != RULE[p][w]["OUT_SELL_spells"]:
                    c.failed += 1; c.fail(f"ledger has {n_e} rows for {p}|{w}, the series has {RULE[p][w]['OUT_SELL_spells']} OUT-SELL spells")
        if not r3_present:
            c.notes.append("regime_ledger.csv has no r3 rows although evidence_contract.md says 'full and r3'; only the full window's ledger could be compared (finding, see step_3_log.md; "
                           "C-ledger-r3-rows below is informational)")
    run_check(C, "C-ledger", c_ledger)

    def c_ledger_r3(c):
        ev = E.get("regime_ledger.csv")
        if ev is None:
            return
        for p in BK:
            c.compared += 1
            n_e = int(((ev["book"] == p) & (ev["window"] == "r3")).sum())
            if n_e != RULE[p]["r3"]["OUT_SELL_spells"]:
                c.failed += 1; c.fail(f"regime_ledger.csv holds {n_e} r3 rows for {p}; the r3 window has {RULE[p]['r3']['OUT_SELL_spells']} OUT-SELL spells (contract: 'full and r3')")
    run_check(C, "C-ledger-r3-rows", c_ledger_r3, gate=False)
    if False:
        pass

    # ------------------------------------------------------------------ trades and positions
    def prep_tr(df, run):
        t = df[df["run"] == run].copy()
        t["cost_bps"] = r4(t["cost_bps"])
        t["seq"] = t.groupby(["book", "cost_bps"]).cumcount()
        return t

    def c_trades(c):
        """Every trade of every run of the headline cell (the six rules, the comparators, the constant mixes): date, kind, e_after, gw_after (where the book is
        not fully in the parent), V, traded, cost, the before and after values of the three legs, NAV after, basket in force, the decision that caused it;
        the trade counts per (book, cost, run); the due-trade count of each rule against the one expected from the states alone."""
        tr = E.get("trades.csv", c)
        if tr is None:
            return
        tr = tr[tr["book"].isin(BK)]
        keys = ["book", "cost_bps", "seq"]
        num = ["idx", "e_after", "V", "traded", "cost", "nav_close_after", "stock_before", "gold_before", "cash_before", "stock_after", "gold_after", "cash_after", "dec_j"]
        for run in BASE_KINDS:
            mt = prep_tr(D["trades"], run)
            et = prep_tr(tr, run)
            if not len(mt) and not len(et):
                continue
            et["date"] = et["date"].astype(str)
            et["basket_eff"] = et["basket_eff"].astype(str)
            mt = mt.copy()
            mt["dec_j"] = mt["dec_j"].astype(float)
            compare_frames(c, mt[keys + num + ["date", "kind", "basket_eff"]], et[keys + num + ["date", "kind", "basket_eff"]], keys, num_cols=num,
                           str_cols=["date", "kind", "basket_eff"])
            compare_frames(c, mt[mt["e_after"] < 1][keys + ["gw_after"]], et[et["e_after"] < 1][keys + ["gw_after"]], keys, num_cols=["gw_after"], tol=0.0)
        mc = D["trades"].assign(cost_bps=r4(D["trades"]["cost_bps"])).groupby(["book", "cost_bps", "run"]).size().rename("n").reset_index()
        full_idx = pd.MultiIndex.from_product([BK, [round(x, 4) for x in COSTS], BASE_KINDS], names=["book", "cost_bps", "run"])
        mc = mc.set_index(["book", "cost_bps", "run"]).reindex(full_idx, fill_value=0).reset_index()
        ec = tr.assign(cost_bps=r4(tr["cost_bps"])).groupby(["book", "cost_bps", "run"]).size().rename("n").reset_index()
        ec = ec.set_index(["book", "cost_bps", "run"]).reindex(full_idx, fill_value=0).reset_index()
        compare_frames(c, mc, ec, ["book", "cost_bps", "run"], num_cols=["n"], tol=0.0)
        extra = sorted(set(tr["run"].unique()) - set(BASE_KINDS))
        c.compared += 1
        if extra:
            c.failed += 1; c.fail(f"runs in trades.csv the verifier does not know: {extra}")
        # decision-driven trades of each rule = the due trades expected from the states alone
        for p in BK:
            for r in RULES:
                for cst in COSTS:
                    c.compared += 1
                    n_dec = int(((tr["book"] == p) & (tr["run"] == r) & (r4(tr["cost_bps"]) == round(cst, 4)) & tr["dec_j"].notna()).sum())
                    if n_dec != RULE[p]["full"]["trades_due"][r]:
                        c.failed += 1; c.fail(f"{p} {r} {cst}: {n_dec} decision-driven trades recorded, {RULE[p]['full']['trades_due'][r]} due from the states")
    run_check(C, "C-trades", c_trades)

    def c_positions(c):
        ps = E.get("positions.csv", c)
        if ps is None:
            return
        ev = ps[(ps["units"] != 0) & ps["book"].isin(BK)].copy()
        ev["cost_bps"] = r4(ev["cost_bps"]); ev["date"] = ev["date"].astype(str)
        mine = D["positions"].copy(); mine["cost_bps"] = r4(mine["cost_bps"])
        mine = mine[mine["units"] != 0]
        compare_frames(c, mine, ev[["book", "cost_bps", "run", "date", "instrument", "units"]], ["book", "cost_bps", "run", "date", "instrument"], num_cols=["units"])
    run_check(C, "C-positions", c_positions)

    # ------------------------------------------------------------------ V6 identities on the evidence's own numbers
    def c_v6(c):
        """V6 (T11 + T14): cost = traded x bps / 2 / 1e4; value conservation (after = V - cost, the three legs summing to it); a full trade leaves the legs at
        (e, (1-e) gw, (1-e)(1-gw)) of the value after cost; a D1 partial basket change (0 < e < 1, the six rules) leaves GOLDBEES and cash untouched and the
        stock part at stock_before - cost; after every entry into OUT-SELL in -half the stock value = GOLDBEES = 0.5 of the value after cost, cash 0 (1e-12 of V);
        a 0-cost trade leaves the book's value unchanged."""
        tr = E.get("trades.csv", c)
        if tr is None:
            return
        tr = tr[tr["book"].isin(BK)]
        worst = 0.0
        n_d1 = n_half_in = 0
        for r in tr.itertuples():
            bps = float(r.cost_bps)
            Vv, cost = float(r.V), float(r.cost)
            sa, ga, ca_ = float(r.stock_after), float(r.gold_after), float(r.cash_after)
            c.compared += 3
            if abs(cost - float(r.traded) * bps / 2.0 / 10000.0) > TOL_ID * max(1.0, Vv):
                c.failed += 1; c.fail(f"cost != traded x bps/2/1e4: {r.book} {r.run} {r.date}")
            dv = abs((sa + ga + ca_) - (Vv - cost)) / Vv
            worst = max(worst, dv)
            if dv > TOL_ID:
                c.failed += 1; c.fail(f"value not conserved (after != V - cost) at {r.book} {r.run} {r.cost_bps} {r.date}: rel {dv:.2e}")
            sb, gb, cb = float(r.stock_before), float(r.gold_before), float(r.cash_before)
            if abs((sb + gb + cb) - Vv) / Vv > TOL_ID:
                c.failed += 1; c.fail(f"value before != V at {r.book} {r.run} {r.cost_bps} {r.date}")
            e, gw = float(r.e_after), float(r.gw_after)
            partial = (r.kind == "basket_change") and 0 < e < 1 and r.run in RULES
            c.compared += 1
            if partial:
                n_d1 += 1
                dd = max(abs(ga - gb), abs(ca_ - cb), abs(sa - (sb - cost))) / Vv
                worst = max(worst, dd)
                if dd > TOL_ID:
                    c.failed += 1; c.fail(f"D1 basket change inside the half regime changes GOLDBEES / cash or the stock part is not stock_before - cost: {r.book} {r.run} {r.cost_bps} {r.date} ({dd:.2e} of V)")
            else:
                aft = Vv - cost
                dd = max(abs(sa - e * aft), abs(ga - (1 - e) * gw * aft), abs(ca_ - (1 - e) * (1 - gw) * aft)) / Vv
                worst = max(worst, dd)
                if dd > TOL_ID:
                    c.failed += 1; c.fail(f"post-trade legs differ from the target by {dd:.2e} of V at {r.book} {r.run} {r.cost_bps} {r.date} {r.kind}")
            if bps == 0.0:
                c.compared += 1
                if abs(cost) > 0 or abs((sa + ga + ca_) - Vv) > TOL_ID * Vv:
                    c.failed += 1; c.fail(f"a 0-cost trade with a cost or a value jump: {r.book} {r.run} {r.date}")
            if r.run.endswith("-half") and r.kind == "regime_in":
                n_half_in += 1
                c.compared += 1
                aft = Vv - cost
                dd = max(abs(sa - 0.5 * aft), abs(ga - 0.5 * aft), abs(ca_)) / Vv
                worst = max(worst, dd)
                if dd > TOL_ID:
                    c.failed += 1; c.fail(f"entry into OUT-SELL in {r.run}: stock / GOLDBEES / cash are not 0.5 / 0.5 / 0 of the value after cost at {r.book} {r.cost_bps} {r.date} ({dd:.2e} of V)")
        c.worst_rel = max(c.worst_rel, worst)
        c.compared += 2
        if n_d1 == 0 and wname in ("w1", "w2") and BK:
            c.failed += 1; c.fail("no D1 basket change inside a -half regime was found in the evidence (the check compared nothing)")
        if n_half_in == 0:
            c.failed += 1; c.fail("no entry into OUT-SELL of a -half rule found")
        c.notes.append(f"{n_d1} D1 partial basket trades and {n_half_in} -half entries checked; worst_rel = largest deviation (of V)")
    run_check(C, "C-v6-identities", c_v6)

    def c_d1_units(c):
        """D1 on the positions: at a basket change inside the -half regime the GOLDBEES and LBES units equal those held after the rule's previous trade."""
        ps = E.get("positions.csv", c)
        tr = E.get("trades.csv", c)
        if ps is None or tr is None:
            return
        ps = ps[ps["book"].isin(BK)]
        tr = tr[tr["book"].isin(BK) & (r4(tr["cost_bps"]) == HEADLINE_COST) & tr["run"].isin(RULES)]
        u = {}
        for (b, run, d), g in ps.groupby(["book", "run", "date"]):
            u[(b, run, str(d))] = dict(zip(g["instrument"], g["units"].astype(float)))
        n = 0
        for (b, run), g in tr.groupby(["book", "run"]):
            prev = None
            for r in g.itertuples():
                cur = u.get((b, run, str(r.date)))
                c.compared += 1
                if cur is None:
                    c.missing += 1; c.fail(f"MISSING: positions after the trade {b} {run} {r.date}"); continue
                if r.kind == "basket_change" and 0 < float(r.e_after) < 1:
                    n += 1
                    if prev is None:
                        c.failed += 1; c.fail(f"a D1 basket change with no earlier trade: {b} {run} {r.date}"); continue
                    for ins in ("GOLDBEES", "LBES"):
                        a_, b_ = cur.get(ins, 0.0), prev.get(ins, 0.0)
                        c.compared += 1
                        rr = abs(a_ - b_) / max(abs(b_), 1e-300) if b_ != 0 else abs(a_)
                        c.worst_rel = max(c.worst_rel, rr)
                        if rr > TOL_ID:
                            c.failed += 1; c.fail(f"D1: {ins} units changed at an in-regime basket change: {b} {run} {r.date} ({b_!r} -> {a_!r})")
                prev = cur
        c.compared += 1
        if n == 0:
            c.failed += 1; c.fail("no D1 basket change found in positions (compared nothing)")
        c.notes.append(f"{n} D1 partial basket changes checked on the positions")
    run_check(C, "C-d1-units", c_d1_units)

    def c_liq_gold(c):
        """-liq: GOLDBEES units are 0 throughout the OUT-SELL regime: after every regime_in the GOLDBEES units and gold_after are 0, and the only trade of the
        rule before its next regime_out is that exit (no basket trade while e = 0); any trade that leaves e = 0 and gw = 0 holds no GOLDBEES."""
        tr = E.get("trades.csv", c)
        ps = E.get("positions.csv", c)
        if tr is None or ps is None:
            return
        tr = tr[tr["book"].isin(BK) & tr["run"].isin(["50-liq", "80-liq"])]
        ps = ps[ps["book"].isin(BK) & ps["run"].isin(["50-liq", "80-liq"])]
        u = {}
        for (b, run, d), g in ps.groupby(["book", "run", "date"]):
            u[(b, run, str(d))] = dict(zip(g["instrument"], g["units"].astype(float)))
        n_in = 0
        for (b, cs, run), g in tr.assign(cost_bps=r4(tr["cost_bps"])).groupby(["book", "cost_bps", "run"]):
            in_reg = False
            for r in g.itertuples():
                c.compared += 1
                if in_reg and r.kind != "regime_out":
                    c.failed += 1; c.fail(f"a {r.kind} trade inside the -liq regime (nothing may trade there): {b} {run} {cs} {r.date}")
                if r.kind == "regime_in":
                    n_in += 1
                    in_reg = True
                    c.compared += 1
                    if abs(float(r.gold_after)) > 0 or abs(float(r.stock_after)) > 0:
                        c.failed += 1; c.fail(f"-liq regime_in leaves GOLDBEES or stock: gold_after {r.gold_after!r} stock_after {r.stock_after!r} at {b} {run} {cs} {r.date}")
                elif r.kind == "regime_out":
                    in_reg = False
                if float(r.e_after) == 0.0 and float(r.gw_after) == 0.0:
                    c.compared += 1
                    if abs(float(r.gold_after)) > 0:
                        c.failed += 1; c.fail(f"a trade that leaves gw = 0 holds GOLDBEES: {b} {run} {cs} {r.date}")
                    if cs == HEADLINE_COST:
                        pu = u.get((b, run, str(r.date)))
                        c.compared += 1
                        if pu is None:
                            c.missing += 1; c.fail(f"MISSING: positions after {b} {run} {r.date}")
                        elif abs(pu.get("GOLDBEES", 0.0)) > 0:
                            c.failed += 1; c.fail(f"positions.csv: GOLDBEES units {pu['GOLDBEES']!r} inside the -liq regime at {b} {run} {r.date}")
        c.compared += 1
        if n_in == 0:
            c.failed += 1; c.fail("no -liq regime_in found (compared nothing)")
        c.notes.append(f"{n_in} -liq regime entries checked")
    run_check(C, "C-liq-gold", c_liq_gold)

    # ------------------------------------------------------------------ V4: regression against the stored T11 / T08 / T06 results
    def c_reg_nav(c):
        """V4(a)/(b): the verifier's 50-orig / 80-orig and comparator NAVs against the STORED daily_nav.csv of T11 (W1) / T08 (W2) and, for W2, T06's 'strategy'
        (the 50/50 sleeve) to 2026-10-22, all 3 costs, relative 1e-12 (the R7 variants too on W1)."""
        if wname == "w1":
            refs = [("T11", T11_EVIDENCE / "daily_nav.csv", {**STORED_NAV_MAP, **STORED_R7_MAP}, None)]
        else:
            refs = [("T08", T08_EVIDENCE / "daily_nav.csv", STORED_NAV_MAP, None), ("T06", T06_EVIDENCE / "daily_nav.csv", T06_NAV_MAP, T06_CUTOFF)]
        for tag, path, mp, cutoff in refs:
            if not path.exists():
                c.miss(f"{path}"); continue
            st = read_stored_nav(path, mp, BK, cutoff)
            mine = mnv[mnv["run"].isin(set(mp.values())) & mnv["book"].isin(BK)]
            if cutoff is not None:
                mine = mine[mine["date"] <= str(cutoff.date())]
            mine = mine.merge(st[["book", "cost_bps", "run"]].drop_duplicates(), on=["book", "cost_bps", "run"], how="inner")      # the costs the stored file has for that run
            compare_frames(c, mine, st, ["book", "date", "cost_bps", "run"], num_cols=["nav"], tol=TOL_REG)
            c.notes.append(f"{len(st)} stored rows of {tag}'s daily_nav.csv ({', '.join(sorted(set(mp.values()))[:4])}...); relative tolerance {TOL_REG}")
    run_check(C, "C-regress-nav", c_reg_nav)

    def c_reg_dec(c):
        """The decisions equal the stored decisions of T11 (W1) / T08 (W2) (states, signs, labels, g) on every decision of the books."""
        path = (T11_EVIDENCE if wname == "w1" else T08_EVIDENCE) / "decisions.csv"
        if not path.exists():
            c.miss(str(path)); return
        st = pd.read_csv(path)
        st = st[st["book"].isin(BK)].copy()
        if "window" in st.columns:
            st = st[st["window"] == "full"]
        cols = ["decision_date", "decision_idx", "state", "sign_Nifty100", "sign_MC100", "sign_SC100", "label_Nifty100", "label_MC100", "label_SC100", "sign_MAUc1",
                "label_MAUc1", "g", "trade_date"]
        a = dec_full[dec_full["book"].isin(BK)][["book", "j"] + cols].copy()
        b = st[["book", "j"] + cols].copy()
        a["trade_date"] = a["trade_date"].astype(object).where(a["trade_date"].notna(), "<NA>").astype(str)
        b["trade_date"] = b["trade_date"].astype(object).where(b["trade_date"].notna(), "<NA>").astype(str)
        compare_frames(c, a, b, ["book", "j"], num_cols=["decision_idx", "state", "g"], str_cols=[x for x in cols if x not in ("decision_idx", "state", "g")], tol=0.0)
    run_check(C, "C-regress-decisions", c_reg_dec)

    def c_one_instrument(c):
        for p in BK:
            for nm, d_ in D["one_instrument"][p]:
                c.compared += 1
                c.worst_rel = max(c.worst_rel, d_)
                if d_ > TOL_ID:
                    c.failed += 1; c.fail(f"{p} {nm}: always-in 0-cost one-instrument NAV differs from close / first close by {d_:.2e}")
        reg = E.get("regression.json")
        if reg is not None and "b_one_instrument" in reg:
            for p, v in reg["b_one_instrument"].items():
                c.compared += 1
                if v.get("pass") is False:
                    c.failed += 1; c.fail(f"regression.json b_one_instrument {p} says pass = false")
    run_check(C, "C-one-instrument", c_one_instrument)

    def c_g0(c):
        """W2: G0 (hold-the-parent 0-cost NAV against the published NAV: +-0.25 pp a year overall, +-0.5 pp each calendar year; verify_t08.py's reading) and
        its agreement with the engine's f_g0; W1: the 2019 seam (+-0.5 pp) and the engine's f_seam_2019."""
        reg = E.get("regression.json")
        if wname == "w2":
            ai = pd.DataFrame(D["g0"])
            for r in ai.itertuples():
                c.compared += 1
                c.worst_rel = max(c.worst_rel, abs(r.gap_pp))
                if abs(r.gap_pp) > r.limit_pp:
                    c.failed += 1; c.fail(f"G0 exceeded: {r}")
            if reg is not None and "f_g0" in reg:
                for p in BK:
                    e = reg["f_g0"].get(p)
                    if e is None:
                        c.miss(f"regression.json f_g0 {p}"); continue
                    a = ai[ai["book"] == p]
                    ov = float(a[a["scope"] == "overall"]["gap_pp"].iloc[0])
                    c.compared += 1
                    if abs(float(e["overall_pp_per_year"]) - ov) > 1e-6:
                        c.failed += 1; c.fail(f"G0 overall of {p}: engine {e['overall_pp_per_year']!r} vs verifier {ov!r}")
                    for y, v in e["yearly_pp"].items():
                        mv = a[a["scope"] == str(y)]["gap_pp"]
                        c.compared += 1
                        if not len(mv) or abs(float(v) - float(mv.iloc[0])) > 1e-6:
                            c.failed += 1; c.fail(f"G0 {y} of {p}: engine {v!r} vs verifier {mv.tolist()!r}")
            c.notes.append("; ".join(f"{p} overall {float(ai[(ai['book'] == p) & (ai['scope'] == 'overall')]['gap_pp'].iloc[0]):+.4f}" for p in BK))
        else:
            for r in D["seam"]:
                c.compared += 1
                c.worst_rel = max(c.worst_rel, abs(r["year_gap_pp"]))
                if abs(r["year_gap_pp"]) > r["limit_pp"]:
                    c.failed += 1; c.fail(f"seam gap {r['year_gap_pp']:+.4f} pp for {r['book']} exceeds {r['limit_pp']}")
                if reg is not None and r["book"] in reg.get("f_seam_2019", {}):
                    c.compared += 1
                    e = reg["f_seam_2019"][r["book"]]
                    if abs(float(e["year_gap_pp"]) - r["year_gap_pp"]) > 1e-6:
                        c.failed += 1; c.fail(f"seam gap of {r['book']}: engine {e['year_gap_pp']!r} vs verifier {r['year_gap_pp']!r} pp")
            c.notes.append("; ".join(f"{r['book']} {r['year_gap_pp']:+.4f}" for r in D["seam"]))
        if reg is None:
            E.get("regression.json", c)
    run_check(C, "C-g0-or-seam", c_g0)

    return C, dict(est_all=est_all, env_all=env_all, mst=mst, mnv=mnv, date_idx=date_idx)


# ----------------------------------------------------------------------------------------
# the checks, part 2 (the nulls' draws, the counts, the samplers, percentiles, the engine's own gate files)
# ----------------------------------------------------------------------------------------
_REGEN = {}
_STORED = {}


def expected_groups(books):
    """(book, window, cash, cost, family) groups draws.csv must hold, each with all six rules (contract 'draws.csv')."""
    g = []
    for p in books:
        for fam in ("F1", "F2", "F3", "F4"):
            for cst in COSTS:
                g.append((p, "full", "lbes", cst, fam))
        g.append((p, "full", "lbes", HEADLINE_COST, "F5"))
        g.append((p, "full", "liq", HEADLINE_COST, "F1"))
        g.append((p, "full", "liq", HEADLINE_COST, "F3"))
        g.append((p, "r3", "lbes", HEADLINE_COST, "F1"))
        g.append((p, "r3", "lbes", HEADLINE_COST, "F3"))
    return g


def table_rows(D):
    rows = []
    for p in D["rule"]:
        for window in ("full", "r3"):
            R = D["rule"][p][window]
            G = R["g"]
            B_, GB = R["bounds"], R["g_bounds"]
            for series, state, k, S, lo, hi in (("io", "in", R["in_spells"], R["S_in"], B_["lo_in"], B_["hi_in"]),
                                                ("io", "out", R["out_spells"], R["S_out"], B_["lo_out"], B_["hi_out"]),
                                                ("gold", "buy", G["in_spells"], G["S_in"], GB["lo_buy"], GB["hi_buy"]),
                                                ("gold", "sell", G["out_spells"], G["S_out"], GB["lo_sell"], GB["hi_sell"])):
                rows.append(dict(book=p, window=window, series=series, state=state, k=k, S=S, lo=lo, hi=hi, n_ways=n_ways(k, S, lo, hi)))
    return rows


def trades_due_2d(rule, S, G):
    """Trades due in each row of (draws, weeks) arrays: decisions j = 1..D-2 with e[j] != e[j-1] or (e[j] < 1 and gw[j] != gw[j-1])."""
    E, GW = rule_arrays(rule, S, G)
    Dn = S.shape[1]
    if Dn < 3:
        return np.zeros(len(S), dtype=int)
    due = (E[:, 1:Dn - 1] != E[:, 0:Dn - 2]) | ((E[:, 1:Dn - 1] < 1) & (GW[:, 1:Dn - 1] != GW[:, 0:Dn - 2]))
    return due.sum(axis=1).astype(int)


class SimCache:
    def __init__(self):
        self.d = {}

    def run(self, V, T, bps, tag):
        key = (tag, float(bps), np.asarray(T["e"]).tobytes(), np.asarray(T["gw"]).tobytes())
        if key not in self.d:
            self.d[key] = simulate(V, T, bps, "rule")
        return self.d[key]


SIMS = SimCache()


def stored_states(wname):
    if wname not in _STORED:
        p = (T11_EVIDENCE if wname == "w1" else T08_EVIDENCE) / "draw_states.npz"
        _STORED[wname] = np.load(p) if p.exists() else None
    return _STORED[wname]


def compare_part2(wname, D, E, BK, C, ctx):
    nd_draws = N_DRAWS
    RULE = D["rule"]
    WINDOWS = ["full", "r3"]
    SD = SEEDS[wname]
    mst = ctx["mst"]
    draws = E.get("draws.csv")
    if draws is not None:
        draws = draws[draws["book"].isin(BK)].copy()
        draws["cost_bps"] = r4(draws["cost_bps"])
    states_npz = E.get("draw_states.npz")
    curves_npz = E.get("draw_curves_20.8.npz")
    TYPES_IO = ["N4.9", "N4.10"]
    TYPES_GOLD = ["N4.9-g", "N4.10-g"]
    FEATS = {}
    stored_win = {"full": "full", "r3": "r3" if wname == "w1" else "live"}

    def states_of(book, window, dom, typ):
        key = f"{book}|{window}|{dom}|{typ}"
        if states_npz is None or key not in states_npz.files:
            return None
        return states_npz[key]

    def feat(book, window, dom, typ):
        key = (book, window, dom, typ)
        if key not in FEATS:
            R = RULE[book][window]
            if typ == "real":
                arr = (R["states"] if dom == "io" else R["gstates"])[None, :]
            else:
                arr = states_of(book, window, dom, typ)
            FEATS[key] = None if arr is None else Feat(arr, cover=R["cover"] if dom == "io" else None)
        return FEATS[key]

    def c_states(c_struct, c_len, c_gold):
        """V3, structure of EVERY saved draw (as T11): weeks, first / last state, spell counts, IN / BUY weeks; N4.9 sorted lengths identical to the real series';
        N4.10 lengths within the computed bounds and summing to the totals; the four books' arrays identical."""
        if states_npz is None:
            for cc in (c_struct, c_len, c_gold):
                E.get("draw_states.npz", cc)
            return
        for p in BK:
            for window in WINDOWS:
                R = RULE[p][window]
                G = R["g"]
                bi, bg = R["bounds"], R["g_bounds"]
                for dom, typs, RR, (lo1, hi1, lo0, hi0) in (("io", TYPES_IO, R, (bi["lo_in"], bi["hi_in"], bi["lo_out"], bi["hi_out"])),
                                                           ("gold", TYPES_GOLD, G, (bg["lo_buy"], bg["hi_buy"], bg["lo_sell"], bg["hi_sell"]))):
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
                                ok = (len(ins) > 0 and min(ins) >= lo1 and max(ins) <= hi1 and len(outs) > 0 and min(outs) >= lo0 and max(outs) <= hi0
                                      and sum(ins) == RR["S_in"] and sum(outs) == RR["S_out"])
                                why = f"{typ} bounds [{lo1},{hi1}]/[{lo0},{hi0}] or sums ({RR['S_in']}, {RR['S_out']}) violated"
                            if not ok:
                                cl.failed += 1; cl.fail(f"{p}|{window}|{dom}|{typ} draw {i}: {why}: ones {ins} zeros {outs}")
        for window in WINDOWS:
            for dom, typs in (("io", TYPES_IO), ("gold", TYPES_GOLD)):
                for typ in typs:
                    ref = states_of(BK[0], window, dom, typ)
                    for p in BK[1:]:
                        a = states_of(p, window, dom, typ)
                        if a is None or ref is None:
                            continue
                        if RULE[p][window]["weeks"] != RULE[BK[0]][window]["weeks"]:
                            c_struct.notes.append(f"{p}|{window}|{dom}|{typ}: {RULE[p][window]['weeks']} weeks against {BK[0]}'s {RULE[BK[0]][window]['weeks']} (SCMO_0007 starts two sessions later in W2): "
                                                  "its draws are its own and are not compared with another book's")
                            continue
                        c_struct.compared += 1
                        if not np.array_equal(a, ref):
                            c_struct.failed += 1; c_struct.fail(f"draw states of {p}|{window}|{dom}|{typ} differ from {BK[0]}'s (the books with the same series share their draws)")

    cs = {n: Check(n) for n in ["C-states-struct", "C-states-lengths", "C-gold-states"]}
    C.update(cs)
    try:
        c_states(cs["C-states-struct"], cs["C-states-lengths"], cs["C-gold-states"])
    except Exception as ex:
        cs["C-states-struct"].failed += 1
        cs["C-states-struct"].fail(f"verifier exception in C-states: {ex!r} | {traceback.format_exc(limit=3).strip().splitlines()[-1]}")

    rows_cache = {}

    def due_of(p, w, fam, rule, fi, fg):
        key = (p, w, fam, rule)
        if key not in rows_cache:
            io_t, go_t = FAMILY[fam]
            Sx = fi.arr.astype(int)
            Gx = fg.arr.astype(int)
            if Sx.shape[0] == 1 and Gx.shape[0] > 1:
                Sx = np.repeat(Sx, Gx.shape[0], axis=0)
            if Gx.shape[0] == 1 and Sx.shape[0] > 1:
                Gx = np.repeat(Gx, Sx.shape[0], axis=0)
            rows_cache[key] = (trades_due_2d(rule, Sx, Gx), ((Sx == 0) & (Gx == 0)).sum(axis=1).astype(int))
        return rows_cache[key]

    def c_rows(c_csv, c_sess, c_sig):
        """Every draws.csv row against its saved states: tags, invested (IN) weeks, OUT-SELL weeks, spell counts and lengths, sessions invested, gold BUY weeks
        and spells, trades due of the rule, signatures."""
        if draws is None:
            for cc in (c_csv, c_sess):
                E.get("draws.csv", cc)
            return
        for key, g_ in draws.groupby(["book", "window", "cash", "cost_bps", "family", "rule"]):
            p, w, ca, cst, fam, rule = key
            if fam not in FAMILY or w not in WINDOWS or p not in BK or rule not in RULES:
                c_csv.compared += 1; c_csv.failed += 1; c_csv.fail(f"unexpected row group {key}"); continue
            io_t, go_t = FAMILY[fam]
            fi, fg = feat(p, w, "io", io_t), feat(p, w, "gold", go_t)
            if fi is None or fg is None:
                c_csv.miss(f"draw_states.npz arrays for family {fam} of {p}|{w}"); continue
            R = RULE[p][w]
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
            due, osw = due_of(p, w, fam, rule, fi, fg)
            pairs = [("invested_weeks", fi.w1[ii], False), ("out_sell_weeks", osw[ids] if len(osw) > 1 else np.full(len(ids), osw[0]), False),
                     ("n_in_spells", fi.n1[ii], False), ("n_out_spells", fi.n0[ii], False),
                     ("in_lengths", fi.s1[ii], True), ("out_lengths", fi.s0[ii], True),
                     ("g_buy_weeks", fg.w1[ig], False), ("n_buy_spells", fg.n1[ig], False), ("n_sell_spells", fg.n0[ig], False),
                     ("g_buy_lengths", fg.s1[ig], True), ("g_sell_lengths", fg.s0[ig], True),
                     ("trades_due", due[ids] if len(due) > 1 else np.full(len(ids), due[0]), False)]
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
        """Every expected (book, window, cash, cost, family) group holds all six rules, each with exactly the draw ids 0..N-1 (so every F1 / F3 draw has both the
        original and the variant, the R6 pairing); the stored curves are exactly the first 20 ids and the 20 from default_rng([17, 1]).choice(N, 20) of the contract."""
        if draws is None:
            E.get("draws.csv", c); return
        gb = {k: v for k, v in draws.groupby(["book", "window", "cash", "cost_bps", "family", "rule"])}
        exp = expected_groups(BK)
        for (p, w, ca, cst, fam) in exp:
            for rule in RULES:
                k = (p, w, ca, round(cst, 4), fam, rule)
                c.compared += 1
                g_ = gb.get(k)
                if g_ is None:
                    c.miss(f"draws.csv group {k}"); continue
                ids = g_["draw_id"].values
                if len(ids) != nd_draws or set(ids.tolist()) != set(range(nd_draws)):
                    c.failed += 1; c.fail(f"draws.csv group {k}: {len(ids)} rows, ids not exactly 0..{nd_draws - 1}")
        extra = set(gb) - {(p, w, ca, round(cst, 4), fam, rule) for (p, w, ca, cst, fam) in exp for rule in RULES}
        c.notes.append(f"{len(exp)} expected (book, window, cash, cost, family) groups x 6 rules; unexpected groups present: {len(extra)}")
        if extra:
            c.compared += 1; c.failed += 1; c.fail(f"unexpected draws.csv groups: {sorted(extra)[:3]}")
        if curves_npz is not None:
            exp_ids = set(range(min(20, nd_draws))) | set(int(x) for x in np.random.default_rng([17, 1]).choice(nd_draws, min(20, nd_draws), replace=False))
            have = {}
            for kname in curves_npz.files:
                bk_, fam_, rl_, id_ = kname.split("|")
                have.setdefault((bk_, fam_, rl_), set()).add(int(id_))
            for p in BK:
                for fam in ("F1", "F3"):
                    for rule in RULES:
                        c.compared += 1
                        got = have.get((p, fam, rule), set())
                        if got != exp_ids:
                            c.failed += 1; c.fail(f"draw_curves: ({p}, {fam}, {rule}) holds ids {sorted(got)[:5]}... ({len(got)}), expected {len(exp_ids)} (first 20 + the contract's 20)")
            extra_k = [k for k in have if k[0] not in BK]
            c.compared += 1
            if extra_k:
                c.failed += 1; c.fail(f"draw_curves holds curves of books outside {BK}")
        else:
            E.get("draw_curves_20.8.npz", c)
    run_check(C, "C-draws-coverage", c_cover)

    # ------------------------------------------------------------------ regeneration from the seeds, and the stored states of T11 / T08
    def regen(kind, window, dom, n, book):
        key = (wname, kind, window, dom, n, book)
        if key not in _REGEN:
            R = RULE[book][window]
            if kind == "n49":
                s, sb = (R["states"], SD["n49"]) if dom == "io" else (R["gstates"], SD["n49g"])
                _REGEN[key] = np.array([n49_states(s, sb, i) for i in range(n)])
            else:
                if dom == "io":
                    b = R["bounds"]
                    par1, par0, fs, sb = (R["in_spells"], R["S_in"], b["lo_in"], b["hi_in"]), (R["out_spells"], R["S_out"], b["lo_out"], b["hi_out"]), R["first_state"], SD["n410"]
                else:
                    G, b = R["g"], R["g_bounds"]
                    par1, par0, fs, sb = (G["in_spells"], G["S_in"], b["lo_buy"], b["hi_buy"]), (G["out_spells"], G["S_out"], b["lo_sell"], b["hi_sell"]), G["first_state"], SD["n410g"]
                tabs = {par1: ways_table(*par1), par0: ways_table(*par0)}
                _REGEN[key] = np.array([n410_states_own(fs, par1, par0, sb, i, tabs) for i in range(n)])
        return _REGEN[key]

    def c_regen(c, which):
        if states_npz is None:
            E.get("draw_states.npz", c); return
        for p in BK:
            for window in WINDOWS:
                for dom, typ in ((("io", "N4.9"), ("gold", "N4.9-g")) if which == "n49" else (("io", "N4.10"), ("gold", "N4.10-g"))):
                    arr = states_of(p, window, dom, typ)
                    if arr is None:
                        c.miss(f"draw_states.npz key {p}|{window}|{dom}|{typ}"); continue
                    mine_ = regen(which, window, dom, arr.shape[0], p)
                    c.compared += arr.shape[0]
                    if mine_.shape != arr.shape:
                        c.failed += arr.shape[0]; c.fail(f"{p}|{window}|{dom}|{typ}: shape {arr.shape} vs regenerated {mine_.shape}"); continue
                    bad = np.flatnonzero((mine_ != arr).any(axis=1))
                    c.failed += len(bad)
                    if len(bad):
                        c.fail(f"{p}|{window}|{dom}|{typ} draw {int(bad[0])}: states differ from the verifier's own regeneration from the seed ({len(bad)} of {arr.shape[0]} draws)")
    run_check(C, "C-n49-regen", lambda c: c_regen(c, "n49"))
    run_check(C, "C-n410-regen", lambda c: c_regen(c, "n410"))

    def c_stored(c):
        """V3: every saved draw state array equals the STORED draw_states.npz of T11 (W1) / T08 (W2; its 'live' = r3): the evidence's, and independently the
        verifier's own regeneration from the seed."""
        sto = stored_states(wname)
        if sto is None:
            c.miss(f"stored draw_states.npz of {'T11' if wname == 'w1' else 'T08'}"); return
        if states_npz is None:
            E.get("draw_states.npz", c); return
        for p in BK:
            for window in WINDOWS:
                for dom, typ in (("io", "N4.9"), ("io", "N4.10"), ("gold", "N4.9-g"), ("gold", "N4.10-g")):
                    key = f"{p}|{stored_win[window]}|{dom}|{typ}"
                    arr = states_of(p, window, dom, typ)
                    c.compared += 2
                    if key not in sto.files:
                        c.missing += 2; c.fail(f"MISSING: stored key {key}"); continue
                    st = sto[key]
                    n = arr.shape[0] if arr is not None else nd_draws
                    if arr is None:
                        c.miss(f"draw_states.npz key {p}|{window}|{dom}|{typ}")
                    elif arr.shape[0] > st.shape[0] or not np.array_equal(arr.astype(np.uint8), st[:n].astype(np.uint8)):
                        c.failed += 1; c.fail(f"draw states {p}|{window}|{dom}|{typ} differ from the stored {key} of the earlier test")
                    mine_ = regen("n49" if typ.startswith("N4.9") else "n410", window, dom, n, p)
                    if mine_ is not None and not np.array_equal(mine_.astype(np.uint8), st[:n].astype(np.uint8)):
                        c.failed += 1; c.fail(f"the verifier's own regeneration of {typ} {window} {dom} differs from the stored {key}")
        c.notes.append(f"stored file: tests/{'T11' if wname == 'w1' else 'T08'}/evidence/headline/draw_states.npz; compared the first {nd_draws} draws")
    run_check(C, "C-states-stored", c_stored)

    # ------------------------------------------------------------------ the NAVs of the draws
    def view_of(bk, w, ca):
        if w == "full":
            return (bk["V"] if ca == "lbes" else bk["Vliq"]), bk["dec_idx"]
        return bk["Vr3"], bk["dec_idx_r3"]

    def c_draw_nav(c):
        """The first 20 and 20 random draws (own seed) of every row group and book, all six rules, re-simulated and every statistic compared with draws.csv; the
        20.8 bps LBES curve compared with draw_curves_20.8.npz for the stored ids (and every id sampled)."""
        if draws is None or states_npz is None:
            E.get("draws.csv", c); E.get("draw_states.npz", c); return
        idx = draws.set_index(["book", "window", "cash", "cost_bps", "family", "rule", "draw_id"]).sort_index()
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
                    continue
                c.compared += 1
                dv = float(abs(st[col] - float(row[col])) / max(abs(float(row[col])), 1e-12))
                c.worst_rel = max(c.worst_rel, dv)
                if dv > TOL:
                    c.failed += 1; c.fail(f"{key} {col}: verifier {st[col]!r} vs draws.csv {row[col]!r}")

        def curve_cmp(p, fam, rule, i, r):
            ck = f"{p}|{fam}|{rule}|{i}"
            c.compared += 1
            if ck not in curves_npz.files:
                return False
            cu = curves_npz[ck].astype(float)
            if cu.shape != r["nav"].shape:
                c.failed += 1; c.fail(f"curve {ck}: shape {cu.shape} vs {r['nav'].shape}")
            else:
                rr = float(np.max(np.abs(cu - r["nav"]) / np.abs(r["nav"])))
                curve_chk[0] = max(curve_chk[0], rr); curve_chk[1] += 1
                c.worst_rel = max(c.worst_rel, rr)
                if rr > TOL:
                    c.failed += 1; c.fail(f"curve {ck}: max relative difference {rr:.2e} > {TOL}")
            return True

        stored_ids = {}
        if curves_npz is not None:
            for kname in curves_npz.files:
                bk_, fam_, rl_, id_ = kname.split("|")
                stored_ids.setdefault((bk_, fam_), set()).add(int(id_))
        for (p, w, ca, cst, fam) in expected_groups(BK):
            io_t, go_t = FAMILY[fam]
            fi, fg = feat(p, w, "io", io_t), feat(p, w, "gold", go_t)
            if fi is None or fg is None:
                c.miss(f"states for family {fam} of {p}|{w}"); continue
            navail = min(fi.n if io_t != "real" else 10 ** 9, fg.n if go_t != "real" else 10 ** 9)
            bk = D["books"][p]
            V, dI = view_of(bk, w, ca)
            is_curve_cell = (w, ca) == ("full", "lbes") and fam in ("F1", "F3") and abs(cst - HEADLINE_COST) < 1e-9
            ids_ = set(sample_ids(p, (w, ca, fam), pool=nd_draws, seed=20261123))
            if is_curve_cell:
                ids_ |= stored_ids.get((p, fam), set())
            for i in sorted(x for x in ids_ if x < navail):
                s_i = (fi.arr[i] if io_t != "real" else fi.arr[0]).astype(int)
                g_i = (fg.arr[i] if go_t != "real" else fg.arr[0]).astype(int)
                for rule in RULES:
                    r = SIMS.run(V, mk_T(rule, s_i, g_i, dI), cst, (p, w, ca))
                    nsim += 1
                    compare_row((p, w, ca, round(cst, 4), fam, rule, i), r)
                    if is_curve_cell:
                        if curves_npz is None:
                            E.get("draw_curves_20.8.npz", c); continue
                        if i in stored_ids.get((p, fam), set()):
                            if not curve_cmp(p, fam, rule, i, r):
                                c.missing += 1; c.fail(f"MISSING: curve {p}|{fam}|{rule}|{i}")
        c.notes.append(f"{nsim} draw x rule realisations re-simulated (first 20 and 20 random draws per book and row group, six rules); {curve_chk[1]} draw curves "
                       f"compared at 20.8 bps; worst relative difference {curve_chk[0]:.2e}")
    run_check(C, "C-draw-nav", c_draw_nav)

    # ------------------------------------------------------------------ C-count, C-support, C-sampler
    D["count_rows"] = table_rows(D)

    def c_count(c):
        ct = E.get("count_table.json", c)
        mine = [r for r in D["count_rows"] if r["book"] in BK]
        if ct is not None:
            tabs = ct.get("tables", {})
            for r in mine:
                key = f"{r['book']}|{r['window']}|{r['series']}|{r['state']}"
                c.compared += 1
                l = tabs.get(key)
                if l is None:
                    c.miss(f"count_table.json table {key}"); continue
                try:
                    ok = (int(str(l["n_ways"])) == r["n_ways"] and int(str(l["n_ways_inclusion_exclusion"])) == r["n_ways"] and int(l["spells_k"]) == r["k"]
                          and int(l["weeks_S"]) == r["S"] and int(l["lo"]) == r["lo"] and int(l["hi"]) == r["hi"]
                          and l.get("dp_equals_inclusion_exclusion") is True and l.get("rule_lengths_within_bounds") is True)
                except Exception:
                    ok = False
                if not ok:
                    c.failed += 1; c.fail(f"{key}: count table {l} vs verifier k={r['k']} S={r['S']} lo={r['lo']} hi={r['hi']} n_ways={r['n_ways']}")
            b = ct.get("bounds")
            c.compared += 1
            if b is None:
                c.miss("count_table.json 'bounds'")
            else:
                R0 = RULE[BK[0]]
                try:
                    bf, gf_ = R0["full"]["bounds"], R0["full"]["g_bounds"]
                    want_full = {"in": [bf["lo_in"], bf["hi_in"]], "out": [bf["lo_out"], bf["hi_out"]], "buy": [gf_["lo_buy"], gf_["hi_buy"]], "sell": [gf_["lo_sell"], gf_["hi_sell"]]}
                    b3, g3 = R0["r3"]["bounds"], R0["r3"]["g_bounds"]
                    want_r3 = {"io_in": [b3["lo_in"], b3["hi_in"]], "io_out": [b3["lo_out"], b3["hi_out"]], "gold_buy": [g3["lo_buy"], g3["hi_buy"]], "gold_sell": [g3["lo_sell"], g3["hi_sell"]]}
                    got_full = b["full"]["io"] if "io" in b["full"] else b["full"]
                    ok = {k: list(v) for k, v in got_full.items()} == want_full and {k: list(v) for k, v in b["r3"].items()} == want_r3
                except Exception:
                    ok = False
                if not ok:
                    c.failed += 1; c.fail(f"count_table.json bounds {b} vs the verifier's computed bounds")
        for r in mine:
            c.compared += 1
            dp = ways_table(r["k"], r["S"], r["lo"], r["hi"])[r["k"]][r["S"]]
            if dp != r["n_ways"]:
                c.failed += 1; c.fail(f"{r['book']}|{r['window']}|{r['series']}|{r['state']}: inclusion-exclusion {r['n_ways']} vs DP {dp}")
        c.compared += 1
        if n_ways(3, 12, 2, 6) != 19:
            c.failed += 1; c.fail(f"inclusion-exclusion gives {n_ways(3, 12, 2, 6)} for k=3,S=12,[2,6]; expected 19")
        c.notes.append("tuple counts of W1 compared with the frozen text in C-frozen-counts")
    run_check(C, "C-count", c_count)

    def c_support(c):
        """The real lengths lie within the bounds (so every N4.9 / N4.9-g draw is an allowed N4.10 / N4.10-g configuration), tables feasible, the seeds are the
        reused ones (W1: T11's, W2: T08's), the reportability gate (>= 4 round trips, >= 4 OUT-SELL spells, >= 4 gold spells holding an OUT week), and W2's
        bounds are T08's [2,46] / [2,40] / [2,68] / [2,28]."""
        c.compared += 1
        if SD != SEEDS[wname] or (wname == "w1" and not all(v[0] == 14 for v in SD.values())) or (wname == "w2" and SD != dict(n49=[3], n410=[6], n49g=[11, 3], n410g=[11, 6])):
            c.failed += 1; c.fail(f"seeds {SD} are not the reused tests'")
        for p in BK:
            for window in WINDOWS:
                R = RULE[p][window]
                G = R["g"]
                bi, bg = R["bounds"], R["g_bounds"]
                for nm, lens, lo, hi in (("in", R["in_lengths"], bi["lo_in"], bi["hi_in"]), ("out", R["out_lengths"], bi["lo_out"], bi["hi_out"]),
                                         ("buy", G["in_lengths"], bg["lo_buy"], bg["hi_buy"]), ("sell", G["out_lengths"], bg["lo_sell"], bg["hi_sell"])):
                    c.compared += 1
                    ok = all(lo <= l <= hi for l in lens) and lo * len(lens) <= sum(lens) <= hi * len(lens)
                    if not ok:
                        c.failed += 1; c.fail(f"{p}|{window}|{nm}: the real lengths {lens} are outside [{lo}, {hi}] or the totals cannot be split within the bounds")
                c.compared += 3
                if min(R["in_spells"], R["out_spells"]) < 4:
                    c.failed += 1; c.fail(f"{p}|{window}: fewer than 4 round trips of the in-or-out switch")
                if R["OUT_SELL_spells"] < 4:
                    c.failed += 1; c.fail(f"{p}|{window}: fewer than 4 OUT-SELL spells")
                if R["g_spells_with_an_out_week"] < 4:
                    c.failed += 1; c.fail(f"{p}|{window}: fewer than 4 gold spells containing an OUT week")
    run_check(C, "C-support", c_support)

    def c_sampler(c):
        """V5: the verifier's own sampler passes the chi-square on the 19-tuple case; the DP equals the formula; over the saved N4.10 / N4.10-g draws the mean
        length at every position is within 4 standard errors of S / k."""
        st = sampler_selftest()
        c.compared += 2
        if not st["all_seen"] or st["n_ways_formula"] != 19 or st["n_ways_dp"] != 19:
            c.failed += 1; c.fail(f"sampler self-test enumeration wrong: {st}")
        if st["p"] is not None and st["p"] <= 0.001:
            c.failed += 1; c.fail(f"the verifier's own sampler fails the chi-square (p = {st['p']:.4g})")
        c.notes.append(f"own-sampler chi-square on 19 tuples: chi2 = {st['chi2']:.2f} (df {st['df']}), p = {st['p']}; samples {st['n_samples']}")
        stj = E.get("sampler_selftest.json")
        if stj is not None:
            c.compared += 1
            if stj.get("a_small_case", {}).get("pass") is False or stj.get("pass") is False:
                c.failed += 1; c.fail("sampler_selftest.json says pass = false")
        if states_npz is None:
            E.get("draw_states.npz", c); return
        worst = 0.0
        for p in BK:
            for window in WINDOWS:
                R = RULE[p][window]
                G = R["g"]
                bi, bg = R["bounds"], R["g_bounds"]
                for dom, typ, RR, (lo1, hi1, lo0, hi0) in (("io", "N4.10", R, (bi["lo_in"], bi["hi_in"], bi["lo_out"], bi["hi_out"])),
                                                          ("gold", "N4.10-g", G, (bg["lo_buy"], bg["hi_buy"], bg["lo_sell"], bg["hi_sell"]))):
                    f = feat(p, window, dom, typ)
                    if f is None:
                        c.miss(f"states {p}|{window}|{dom}|{typ}"); continue
                    for nm, k, S, lo, hi, lens_all in (("ones", RR["in_spells"], RR["S_in"], lo1, hi1, f.ones), ("zeros", RR["out_spells"], RR["S_out"], lo0, hi0, f.zeros)):
                        if any(len(x) != k for x in lens_all):
                            c.failed += 1; c.fail(f"{p}|{window}|{dom}|{typ}|{nm}: draws do not all have {k} spells"); continue
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
        c.notes.append("worst_rel in this check is the largest |z| (standard errors) over the positions (with only a handful of draws the test is weak)")
    run_check(C, "C-sampler", c_sampler)

    # ------------------------------------------------------------------ percentiles (twice) and the R6 pairing
    D["percentiles"] = []

    def c_percentile(c):
        """Percentile (draws worse + 0.5 ties) / draws and p = (1 + at least as good) / (draws + 1) of each rule among ITS OWN draws (same family, cost, cash,
        window), every statistic, computed twice (vectorised and by loop); the rows go to verify_t14.json."""
        if draws is None:
            E.get("draws.csv", c); return
        rows = []
        for (p, w, ca, cst, fam, rule), g_ in draws.groupby(["book", "window", "cash", "cost_bps", "family", "rule"]):
            m = mst[(mst["book"] == p) & (mst["window"] == w) & (mst["cash"] == ca) & (mst["cost_bps"] == cst) & (mst["kind"] == rule)]
            if not len(m):
                continue
            row = dict(book=p, window=w, cash=ca, cost_bps=float(cst), family=fam, rule=rule, n_draws=len(g_))
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
                    c.failed += 1; c.fail(f"{p} {w} {ca} {cst} {fam} {rule} {stat}: vectorised percentile {pc!r}/{pv!r} vs loop {pc2!r}/{pv2!r}")
                row[f"{stat}_pctile"] = pc; row[f"{stat}_p"] = pv
            rows.append(row)
        D["percentiles"] = rows
        c.notes.append("worst_rel in this check is the largest difference between the two own implementations")
    run_check(C, "C-percentile", c_percentile)

    def c_r6(c):
        """R6 needs both rules on every draw: for each F1 / F3 group and each new rule, the variant's draw ids equal its original's, one row per id."""
        if draws is None:
            E.get("draws.csv", c); return
        for (p, w, ca, cst, fam) in expected_groups(BK):
            if fam not in ("F1", "F3"):
                continue
            for r in NEW_RULES:
                a = draws[(draws["book"] == p) & (draws["window"] == w) & (draws["cash"] == ca) & (draws["cost_bps"] == round(cst, 4)) & (draws["family"] == fam) & (draws["rule"] == r)]
                b = draws[(draws["book"] == p) & (draws["window"] == w) & (draws["cash"] == ca) & (draws["cost_bps"] == round(cst, 4)) & (draws["family"] == fam) & (draws["rule"] == ORIG_OF[r])]
                c.compared += 1
                if len(a) != len(b) or sorted(a["draw_id"].tolist()) != sorted(b["draw_id"].tolist()) or a["draw_id"].duplicated().any():
                    c.failed += 1; c.fail(f"R6 pairing: {r} and {ORIG_OF[r]} do not hold the same draw ids for {(p, w, ca, cst, fam)}")
    run_check(C, "C-r6-pairs", c_r6)

    # ------------------------------------------------------------------ regression on the stored draws of T11 / T08
    def c_reg_draws(c):
        """V4: the -orig rows of draws.csv (50-orig, 80-orig) against the stored draws.csv of T11 (W1) / T08 (W2): every statistic, tag and signature, to 1e-12
        (80-orig = their 'timed', 50-orig = their 'fixed50'; their 'live' = r3)."""
        path = (T11_EVIDENCE if wname == "w1" else T08_EVIDENCE) / "draws.csv"
        if draws is None:
            E.get("draws.csv", c); return
        if not path.exists():
            c.miss(str(path)); return
        usecols = ["book", "window", "cash", "cost_bps", "family", "sleeve_mode", "draw_id"] + DRAW_STAT_NUM + DRAW_STAT_STR
        hdr = pd.read_csv(path, nrows=0).columns
        usecols = [u for u in usecols if u in hdr]
        st = pd.read_csv(path, usecols=usecols, dtype=STR_COLS_DRAWS)
        st = st[st["book"].isin(BK) & (st["draw_id"] < nd_draws)].copy()
        st["window"] = st["window"].replace({"live": "r3"})
        st["cash"] = st["cash"].replace({"liquidcase": "liq"})
        st["rule"] = st["sleeve_mode"].map({"timed": "80-orig", "fixed50": "50-orig"})
        st["cost_bps"] = r4(st["cost_bps"])
        ev = draws[draws["rule"].isin(["50-orig", "80-orig"])]
        combos = st[["window", "cash", "cost_bps", "family", "rule"]].drop_duplicates()
        ev = ev.merge(combos, on=["window", "cash", "cost_bps", "family", "rule"], how="inner")
        keys = ["book", "window", "cash", "cost_bps", "family", "rule", "draw_id"]
        nums = [x for x in DRAW_STAT_NUM if x in st.columns and x in ev.columns]
        strs = [x for x in DRAW_STAT_STR if x in st.columns and x in ev.columns]
        compare_frames(c, ev[keys + nums + strs], st[keys + nums + strs], keys, num_cols=nums, str_cols=strs, tol=TOL_REG)
        c.notes.append(f"{len(st)} stored draw rows of {'T11' if wname == 'w1' else 'T08'} compared (columns {len(nums) + len(strs)}); relative tolerance {TOL_REG}")
    run_check(C, "C-regress-draws", c_reg_draws)

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
                                c.failed += 1; c.fail(f"regression.json {path}/pass = false")
                        else:
                            walk_pass(vv, path + "/" + str(kk))
            walk_pass(reg)
            sc = reg.get("c_shared_code", {})
            c.compared += 1
            if sc.get("unexpected_changes") or sc.get("required_not_identical"):
                c.failed += 1; c.fail(f"regression.json c_shared_code lists unexpected changes: {sc.get('unexpected_changes')} {sc.get('required_not_identical')}")
            c.notes.append("V4(d) (AST diff of shared functions against t11_engine.py / t08_engine.py) is the engine's own gate: the verifier may not open the engines; "
                           "its recorded result is read here")
        A = E.get("audit.json")
        if A is not None:
            gates = A.get("gates")
            if isinstance(gates, dict):
                for k, v in gates.items():
                    c.compared += 1
                    if v is False:
                        c.failed += 1; c.fail(f"audit.json gate {k} = false")
            v2 = A.get("v2", {})
            c.compared += 2
            if not (isinstance(v2.get("checks"), (int, float)) and v2["checks"] > 0):
                c.failed += 1; c.fail(f"audit.json v2.checks = {v2.get('checks')!r}: V2 needs a count > 0")
            if v2.get("violations") != 0:
                c.failed += 1; c.fail(f"audit.json v2.violations = {v2.get('violations')!r}: must be 0")
            books = A.get("books", {})
            for p in BK:
                a = books.get(p)
                if a is None:
                    c.miss(f"{p} in audit.json"); continue
                R = RULE[p]["full"]
                pairs = [("decisions", D["meta"][p]["decisions"]), ("sessions", D["meta"][p]["sessions"]), ("first_state", R["first_state"]), ("in_lengths", R["in_lengths"]),
                         ("out_lengths", R["out_lengths"]), ("round_trips", min(R["in_spells"], R["out_spells"])), ("weeks_IN", R["weeks_IN"]),
                         ("weeks_OUT_BUY", R["weeks_OUT_BUY"]), ("weeks_OUT_SELL", R["weeks_OUT_SELL"]), ("out_sell_lengths", R["OUT_SELL_lengths"]),
                         ("out_buy_lengths", R["OUT_BUY_lengths"]), ("g_flips", R["g_flips"]), ("g_first_state", R["g"]["first_state"]),
                         ("start", R["start"]), ("end", R["end"]), ("g_buy_lengths", R["g"]["in_lengths"]), ("g_sell_lengths", R["g"]["out_lengths"]),
                         ("trades_due_per_rule", R["trades_due"]),
                         ("bounds", {"in": [R["bounds"]["lo_in"], R["bounds"]["hi_in"]], "out": [R["bounds"]["lo_out"], R["bounds"]["hi_out"]],
                                     "buy": [R["g_bounds"]["lo_buy"], R["g_bounds"]["hi_buy"]], "sell": [R["g_bounds"]["lo_sell"], R["g_bounds"]["hi_sell"]]})]
                for nm, mv in pairs:
                    if nm in a:
                        c.compared += 1
                        if a[nm] != mv:
                            c.failed += 1; c.fail(f"{p} {nm}: verifier={mv!r} audit.json={a[nm]!r}")
        sj = E.get("sampler_selftest.json")
        if sj is not None:
            c.compared += 1
            if sj.get("pass") is False:
                c.failed += 1; c.fail("sampler_selftest.json says pass = false")
    run_check(C, "C-engine-files", c_engine_files)

    def c_r7_tables(c):
        """W1: r7_flagged_days.csv and r7_export.csv (held export-priced stock-sessions and the two end NAVs of hold-the-parent) against the verifier's own."""
        if wname != "w1":
            c.notes.append("W1 only"); return
        fl = E.get("r7_flagged_days.csv", c)
        ex = E.get("r7_export.csv", c)
        if fl is not None:
            fl = fl[fl["book"].isin(BK)].copy()
            fl["date"] = fl["date"].astype(str)
            mine = pd.DataFrame([r for p in BK for r in D["r7"][p]["flagged"]])
            if not len(mine):
                mine = pd.DataFrame(columns=["book", "date", "stock", "prev_close", "close", "ret", "w_prev", "w_cur", "w_prev_n", "w_cur_n", "src"])
            compare_frames(c, mine[["book", "date", "stock", "prev_close", "close", "ret", "src"]], fl[["book", "date", "stock", "prev_close", "close", "ret", "src"]],
                           ["book", "date", "stock"], num_cols=["prev_close", "close", "ret"], str_cols=["src"])
        if ex is not None:
            ex = ex[ex["book"].isin(BK)]
            for p in BK:
                r7 = D["r7"][p]
                e_ = ex[ex["book"] == p]
                hold_end = float(D["hold0"][p][-1])
                noexp = [r for kind_, bps, r in r7["sims"] if kind_ == "hold_parent_r7_noexport" and bps == 0.0][0]["nav"][-1]
                got = {str(s).replace(".NS", ""): int(v) for s, v in zip(e_["stock"], e_["held_sessions_export"])}
                c.compared += 1
                if got != r7["export_by_stock"]:
                    c.failed += 1; c.fail(f"{p}: r7_export.csv held export sessions {got} vs verifier {r7['export_by_stock']}")
                for col, want in (("end_nav_hold_parent", hold_end), ("end_nav_hold_parent_noexport", float(noexp))):
                    for v in e_[col].astype(float):
                        c.compared += 1
                        d_ = abs(v - want) / abs(want)
                        c.worst_rel = max(c.worst_rel, d_)
                        if d_ > TOL:
                            c.failed += 1; c.fail(f"{p}: r7_export.csv {col} {v!r} vs verifier {want!r}")
    run_check(C, "C-r7-tables", c_r7_tables)
    return C


def compare_all(wname, D, E, BK):
    C, ctx = compare_part1(wname, D, E, BK)
    return compare_part2(wname, D, E, BK, C, ctx)


# ----------------------------------------------------------------------------------------
# self-test: a corrupted copy must be detected, each corruption by its own check
# ----------------------------------------------------------------------------------------
def _swap_two_out_spells(arr_row, first_state):
    """A state row with two OUT (0) spells of different lengths swapped: still inside the bounds with the same totals, so only the saved-vs-stored /
    regenerated comparisons can see it."""
    sp = spells_of_rows(arr_row[None, :])[0]
    ones, zeros = list(sp[0]), list(sp[1])
    for a in range(len(zeros)):
        for b in range(a + 1, len(zeros)):
            if zeros[a] != zeros[b]:
                zeros[a], zeros[b] = zeros[b], zeros[a]
                return states_from_lengths(first_state, ones, zeros)
    return None


def corrupt_copy(ev, dst, D, books, wname, only=None):
    """Corruptions, each of a file and each caught by its own check: a -half target changed on an OUT-SELL week (decisions.csv, C-dec); a regime changed
    (regimes.csv, C-regimes); a NAV column x 1.001 (daily_nav.csv, C-nav); a -half basket trade replaced by a full reset to 50/50 (trades.csv, C-v6-identities;
    its GOLDBEES units moved in positions.csv, C-d1-units); a -liq regime week holding GOLDBEES (positions.csv units, and a trade's gold_after, C-liq-gold);
    one trade removed (trades.csv, C-trades); a draw state out of bounds, N4.10 and N4.10-g (draw_states.npz, C-states-lengths / C-gold-states); a draw state
    swapped inside the bounds (C-states-stored); a draw's cagr altered (draws.csv, C-draw-nav); a stats cagr altered (stats.csv, C-stats-all); a ledger
    return altered (regime_ledger.csv, C-ledger); the Smallcap 100 usable_from lowered (inputs.csv, C-data)."""
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True)
    info = {}
    p0 = books[0]

    def on(label):
        return only is None or only == label
    dpath = ev.path("decisions.csv")
    if dpath is not None:
        dec = pd.read_csv(dpath)
        cand = dec.index[(dec["book"] == p0) & (dec["regime"] == "OUT-SELL")]
        if len(cand) and on("flipped_decision_rows"):
            dec.loc[cand[len(cand) // 2], "e_50-half"] = 0.0
            dec.loc[cand[len(cand) // 3], "e_80-half"] = 1.0
            info["flipped_decision_rows"] = [int(cand[len(cand) // 2]), int(cand[len(cand) // 3])]
        dec.to_csv(dst / "decisions.csv", index=False)
    rpath = ev.path("regimes.csv")
    if rpath is not None:
        rg = pd.read_csv(rpath)
        cand = rg.index[(rg["book"] == p0) & (rg["regime"] == "OUT-SELL")]
        if len(cand) and on("flipped_regime_row"):
            rg.loc[cand[0], "regime"] = "OUT-BUY"
            info["flipped_regime_row"] = int(cand[0])
        rg.to_csv(dst / "regimes.csv", index=False)
    npath = ev.path("daily_nav.csv")
    if npath is not None and on("scaled_nav"):
        nav = pd.read_csv(npath)
        m = (nav["run"] == "80-half") & (nav["cost_bps"] == 0.0)
        nav.loc[m, "nav"] = nav.loc[m, "nav"] * 1.001
        nav.to_csv(dst / "daily_nav.csv", index=False)
        info["scaled_nav"] = "80-half, cost 0, x 1.001"
    tpath = ev.path("trades.csv")
    ppath = ev.path("positions.csv")
    pos = pd.read_csv(ppath) if ppath is not None else None
    if tpath is not None:
        tr = pd.read_csv(tpath)
        base = (tr["book"] == p0) & (tr["cost_bps"].astype(float) == HEADLINE_COST)
        cand = tr.index[base & (tr["run"] == "50-half") & (tr["kind"] == "basket_change") & (tr["e_after"].astype(float) == 0.5)]
        if len(cand) and on("d1_full_reset_trade"):
            i = cand[0]
            aft = float(tr.loc[i, "V"]) - float(tr.loc[i, "cost"])
            tr.loc[i, ["stock_after", "gold_after", "cash_after"]] = [0.5 * aft, 0.5 * aft, 0.0]
            info["d1_full_reset_trade"] = f"{p0} 50-half basket_change {tr.loc[i, 'date']} replaced by a full reset to 50/50"
        if len(cand) and on("d1_units_changed"):
            i = cand[0]
            if pos is not None:
                msk = (pos["book"] == p0) & (pos["run"] == "50-half") & (pos["date"] == tr.loc[i, "date"]) & (pos["instrument"] == "GOLDBEES")
                if msk.any():
                    pos.loc[msk, "units"] = pos.loc[msk, "units"] * 1.1
                    info["d1_units_changed"] = f"{p0} 50-half GOLDBEES units x 1.1 on {tr.loc[i, 'date']}"
        cand2 = tr.index[base & (tr["run"] == "80-liq") & (tr["kind"] == "regime_in")]
        if len(cand2) and on("liq_gold_after"):
            tr.loc[cand2[0], "gold_after"] = 0.05
            info["liq_gold_after"] = f"{p0} 80-liq regime_in {tr.loc[cand2[0], 'date']} gold_after 0.05"
        cand3 = tr.index[base & (tr["run"] == "80-orig") & (tr["kind"] == "basket_change")]
        if len(cand3) > 2 and on("removed_basket_trade"):
            tr = tr.drop(index=cand3[2])
            info["removed_basket_trade"] = f"{p0}, 20.8 bps, 3rd basket_change of 80-orig"
        tr.to_csv(dst / "trades.csv", index=False)
    if pos is not None:
        if tpath is not None:
            tr0 = pd.read_csv(tpath)
            c4 = tr0.index[(tr0["book"] == p0) & (tr0["cost_bps"].astype(float) == HEADLINE_COST) & (tr0["run"] == "50-liq") & (tr0["kind"] == "regime_in")]
            if len(c4) and on("liq_gold_units"):
                dt = tr0.loc[c4[0], "date"]
                msk = (pos["book"] == p0) & (pos["run"] == "50-liq") & (pos["date"] == dt) & (pos["instrument"] == "GOLDBEES")
                if msk.any():
                    pos.loc[msk, "units"] = 0.01
                else:
                    pos = pd.concat([pos, pd.DataFrame([dict(book=p0, window="full", cost_bps=HEADLINE_COST, run="50-liq", date=dt, instrument="GOLDBEES", units=0.01)])], ignore_index=True)
                info["liq_gold_units"] = f"{p0} 50-liq regime_in {dt}: GOLDBEES units 0.01 in positions.csv"
        pos.to_csv(dst / "positions.csv", index=False)
    spath = ev.path("draw_states.npz")
    wpath = ev.path("draws.csv")
    w = pd.read_csv(wpath, dtype=str) if wpath is not None else None
    if spath is not None:
        z = np.load(spath)
        data = {k: z[k] for k in z.files}
        R = D["rule"][p0]["full"]
        key = f"{p0}|full|io|N4.10"
        if key in data and data[key].shape[0] > 5 and on("corrupted_n410_draw"):
            arr = data[key].copy()
            new_row, ins, outs = _widen_first_spell(arr[5], int(arr[5][0]), R["bounds"]["hi_in"])
            if len(new_row) == arr.shape[1]:
                arr[5] = new_row
                data[key] = arr
                info["corrupted_n410_draw"] = dict(key=key, draw_id=5, in_lengths=ins, out_lengths=outs)
                if w is not None:
                    msk = (w["book"] == p0) & (w["window"] == "full") & (w["io_null"] == "N4.10") & (w["draw_id"] == "5")
                    w.loc[msk, "in_lengths"] = "|".join(map(str, ins))
        key6 = f"{p0}|full|io|N4.10"
        if key6 in data and data[key6].shape[0] > 6 and on("swapped_n410_draw"):
            arr = data[key6].copy()
            sw = _swap_two_out_spells(arr[6], int(arr[6][0]))
            if sw is not None and len(sw) == arr.shape[1]:
                arr[6] = sw
                data[key6] = arr
                info["swapped_n410_draw"] = dict(key=key6, draw_id=6)
        key = f"{p0}|full|gold|N4.10-g"
        if key in data and data[key].shape[0] > 7 and on("corrupted_n410g_draw"):
            arr = data[key].copy()
            new_row, buys, sells = _widen_first_spell(arr[7], int(arr[7][0]), R["g_bounds"]["hi_buy"])
            if len(new_row) == arr.shape[1]:
                arr[7] = new_row
                data[key] = arr
                info["corrupted_n410g_draw"] = dict(key=key, draw_id=7, buy_lengths=buys, sell_lengths=sells)
                if w is not None:
                    msk = (w["book"] == p0) & (w["window"] == "full") & (w["gold_null"] == "N4.10-g") & (w["draw_id"] == "7")
                    w.loc[msk, "g_buy_lengths"] = "|".join(map(str, buys))
        np.savez(dst / "draw_states.npz", **data)
    if w is not None:
        msk = (w["book"] == p0) & (w["window"] == "full") & (w["cash"] == "lbes") & (w["family"] == "F3") & (w["rule"] == "80-half") \
              & (w["draw_id"] == "3") & (w["cost_bps"].astype(float) == HEADLINE_COST)
        if msk.any() and on("altered_draw_cagr"):
            w.loc[msk, "cagr"] = (w.loc[msk, "cagr"].astype(float) * 1.01).astype(str)
            info["altered_draw_cagr"] = f"{p0} F3 draw 3, 20.8 bps, 80-half, cagr x 1.01"
        w.to_csv(dst / "draws.csv", index=False)
    spp = ev.path("stats.csv")
    if spp is not None:
        st = pd.read_csv(spp)
        msk = (st["book"] == p0) & (st["kind"] == "50-liq") & (st["window"] == "full") & (st["cash"] == "lbes") & (st["cost_bps"] == HEADLINE_COST)
        if msk.any() and on("altered_stats_cagr"):
            st.loc[msk, "cagr"] = st.loc[msk, "cagr"] * 1.0001
            info["altered_stats_cagr"] = f"{p0} 50-liq 20.8 bps cagr x 1.0001"
        st.to_csv(dst / "stats.csv", index=False)
    lpath = ev.path("regime_ledger.csv")
    if lpath is not None:
        lg = pd.read_csv(lpath)
        msk = lg.index[lg["book"] == p0]
        if len(msk) and on("altered_ledger_return"):
            lg.loc[msk[0], "parent_return"] = lg.loc[msk[0], "parent_return"] * 1.01 + 0.001
            info["altered_ledger_return"] = f"{p0} spell 1 parent_return x 1.01 + 0.001"
        lg.to_csv(dst / "regime_ledger.csv", index=False)
    ipath = ev.path("inputs.csv")
    if ipath is not None:
        inp = pd.read_csv(ipath)
        msk = inp["file"].astype(str).str.replace("\\", "/", regex=False).str.contains("Master_SC100")
        if msk.any() and "usable_from" in inp.columns and on("lowered_usable_from"):
            inp["usable_from"] = inp["usable_from"].astype(object)
            inp.loc[msk, "usable_from"] = "2004-01-01"
            inp.to_csv(dst / "inputs.csv", index=False)
            info["lowered_usable_from"] = "Smallcap 100 Master row of inputs.csv set to 2004-01-01"
    return info


EVIDENCE_FILES = ["inputs.csv", "decisions.csv", "decisions_r3.csv", "regimes.csv", "stats.csv", "daily_nav.csv", "trades.csv", "positions.csv", "draws.csv",
                  "draw_states.npz", "real_states.npz", "draw_curves_20.8.npz", "regime_ledger.csv", "constant_mix_params.csv", "regression.json",
                  "sampler_selftest.json", "count_table.json", "audit.json"]
EVIDENCE_FILES_W1 = ["parent_nav_2014-09-01_2019-01-02.csv", "parent_nav_2014-09-01_2019-01-02.md", "r7_flagged_days.csv", "r7_export.csv"]
SELFTEST_WANTS = [("flipped_decision_rows", "C-dec", "decision_target_changed"), ("flipped_regime_row", "C-regimes", "regime_changed"),
                  ("scaled_nav", "C-nav", "nav_scaled"), ("d1_full_reset_trade", "C-v6-identities", "half_basket_trade_as_full_reset"),
                  ("d1_units_changed", "C-d1-units", "half_basket_units_changed"), ("liq_gold_units", "C-liq-gold", "liq_week_goldbees_units"),
                  ("liq_gold_after", "C-liq-gold", "liq_trade_gold_after"), ("removed_basket_trade", "C-trades", "trade_removed"),
                  ("corrupted_n410_draw", "C-states-lengths", "n410_draw_out_of_bounds"), ("corrupted_n410g_draw", "C-gold-states", "n410g_draw_out_of_bounds"),
                  ("swapped_n410_draw", "C-states-stored", "n410_draw_swapped_inside_bounds"), ("altered_draw_cagr", "C-draw-nav", "draw_cagr_altered"),
                  ("altered_stats_cagr", "C-stats-all", "stats_cagr_altered"), ("altered_ledger_return", "C-ledger", "ledger_return_altered"),
                  ("lowered_usable_from", "C-data", "sc100_usable_from_lowered")]


def close_ev(E):
    for obj in E._cache.values():
        if hasattr(obj, "close"):
            try:
                obj.close()
            except Exception:
                pass


def _jsonable_rule(rule):
    out = {}
    for p, rw in rule.items():
        out[p] = {}
        for w, R in rw.items():
            out[p][w] = {k: v for k, v in R.items() if not isinstance(v, np.ndarray)}
            out[p][w]["g"] = {k: v for k, v in R["g"].items() if not isinstance(v, np.ndarray)}
    return out


def run_window(wname, evdir, books, selftest, scratch, isolated=False):
    t = time.time()
    D = derive(wname, books)
    print(f"[{wname} {time.time()-t:6.1f}s] derivation complete (books {books}, draws per group {N_DRAWS})", flush=True)
    E = Evidence(evdir)
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
    pct_real, count_real = D["percentiles"], D["count_rows"]
    st_rep = None
    if selftest:
        cdir = scratch / f"corrupt_evidence_t14_{wname}"
        info = corrupt_copy(E, cdir, D, books, wname)
        Ec = Evidence(cdir, fallback=evdir)
        Cc = compare_all(wname, D, Ec, books)
        close_ev(Ec)
        print_table(Cc, f"SELF-TEST {wname}: corrupted copy in {cdir}")
        cc, cf = summarise(Cc)
        by = {k: (v.failed + v.missing) for k, v in Cc.items()}
        detected_by, applied = {}, {}
        for ikey, chk, label in SELFTEST_WANTS:
            applied[label] = ikey in info
            detected_by[label] = by.get(chk, 0) > 0
        detected = cf > 0 and all(applied.values()) and all(detected_by.values())
        st_rep = dict(dir=str(cdir), corruptions=info, applied=applied, gate_compared=cc, gate_failures=cf, detected=bool(detected), detected_by=detected_by,
                      checks={k: v.to_dict() for k, v in Cc.items()})
        print(f"[{wname}] corrupted copy detected: {detected} (failures {cf}; applied {applied}; detected by {detected_by})", flush=True)
        shutil.rmtree(cdir, ignore_errors=True)
        if isolated:
            iso = {}
            for ikey, chk, label in SELFTEST_WANTS:
                i2 = corrupt_copy(E, cdir, D, books, wname, only=ikey)
                Ei = Evidence(cdir, fallback=evdir)
                Ci = compare_all(wname, D, Ei, books)
                close_ev(Ei)
                fired = sorted(k for k, v in Ci.items() if v.gate and (v.failed + v.missing) > 0)
                iso[label] = dict(applied=ikey in i2, own_check=chk, own_check_fired=chk in fired, checks_fired=fired)
                print(f"[{wname}] isolated corruption {label}: applied {ikey in i2}; own check {chk} fired {chk in fired}; all checks that fired: {fired}", flush=True)
                shutil.rmtree(cdir, ignore_errors=True)
            st_rep["isolated"] = iso
            st_rep["detected"] = bool(st_rep["detected"] and all(v["applied"] and v["own_check_fired"] for v in iso.values()))
    D["percentiles"], D["count_rows"] = pct_real, count_real
    ok_real = gate_compared > 0 and gate_fail == 0 and not extra_missing
    ok = ok_real and (st_rep is None or st_rep["detected"])
    reads = {}
    for k, v in D["reads"].items():
        try:
            sha = sha256_file(AA / k)
        except Exception:
            sha = None
        reads[k] = dict(v, sha256=sha)
    rep = dict(verifier="analysis/verify_t14.py", window=wname, evidence=str(evdir), books=books, draws_expected=N_DRAWS, end=str(D["END"].date()),
               gate_compared=int(gate_compared), gate_failures_and_missing=int(gate_fail), n_checks=len(C), n_gate_checks=sum(1 for c in C.values() if c.gate),
               missing_evidence_files=extra_missing, checks={k: v.to_dict() for k, v in C.items()}, meta=D["meta"], rule=_jsonable_rule(D["rule"]),
               count_rows=[{**r, "n_ways": str(r["n_ways"])} for r in D["count_rows"]], percentiles=D["percentiles"], g0=D["g0"], seam=D["seam"],
               one_instrument={p: v for p, v in D["one_instrument"].items()}, approved_data_files_read=reads, selftest=st_rep, exit_ok=bool(ok),
               closed_form="NAV_end = prod over segments of (trade-day jump x fixed-unit segment growth)")
    if wname == "w1":
        rep["export_sessions"] = {p: dict(total=D["r7"][p]["export_total"], by_stock=D["r7"][p]["export_by_stock"]) for p in books}
    out = Path(evdir) / "verify_t14.json"
    try:
        out.write_text(json.dumps(rep, indent=1, default=str))
        print(f"wrote {out}")
    except Exception as ex:
        print(f"could not write {out}: {ex!r}")
    print(f"\n[{wname}] rows compared (gate checks): {gate_compared}; failures + missing: {gate_fail}; real run ok: {ok_real}; exit ok: {ok}; time {time.time()-t:.1f} s", flush=True)
    return ok, gate_compared, gate_fail


def main():
    global N_DRAWS
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="headline", help="evidence run name under tests/T14/evidence/ (holds w1/ and w2/)")
    ap.add_argument("--evidence", default=None, help="evidence directory holding w1/ and w2/ (overrides --run)")
    ap.add_argument("--window", default="both", choices=["w1", "w2", "both"])
    ap.add_argument("--no-selftest", action="store_true", help="skip the in-process corrupted-copy test")
    ap.add_argument("--draws", type=int, default=None, help="draws per row group the evidence must hold (2000 for headline, 20 for smoke)")
    ap.add_argument("--selftest-isolated", action="store_true", help="also apply each corruption ALONE and require its own check to fire (slow; one comparison pass per corruption)")
    ap.add_argument("--books", default=None, help="comma-separated books (default: those found in the evidence's decisions.csv)")
    ap.add_argument("--scratch", default=None, help="directory for the corrupted copies (default: a fresh temporary directory)")
    args = ap.parse_args()
    root = Path(args.evidence) if args.evidence else AA / "tests" / "T14" / "evidence" / args.run
    N_DRAWS = int(args.draws) if args.draws else (20 if (args.run == "smoke" and not args.evidence) else 2000)
    windows = ["w1", "w2"] if args.window == "both" else [args.window]
    scratch = Path(args.scratch) if args.scratch else Path(tempfile.mkdtemp(prefix="verify_t14_"))
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
        results[wn] = run_window(wn, evdir, books, not args.no_selftest, scratch, args.selftest_isolated)
    ok = all(r[0] for r in results.values())
    print("\n==== summary ====")
    for wn, (o, gc, gf) in results.items():
        print(f"{wn}: rows compared (gate checks) {gc}; failures + missing {gf}; exit ok {o}")
    print(f"total time {time.time()-t:.1f} s; exit {'0' if ok else '1'}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
