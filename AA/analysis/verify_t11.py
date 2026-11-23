"""T11 independent verifier (Step 3, gate V1 of tests/T11/T11.md section 2).

Re-derives T11's decisions (index and MAUc1 gold signal), the hold-the-parent, Part A (fixed 50/50 sleeve) and Part B (MAUc1-timed sleeve)
NAVs at 0 / 20.8 / 50 bps, every basket, exit, entry and sleeve trade, the comparators, the R7 variants, the nulls' draws (structure of EVERY
saved draw, the NAV of the first 20 and 20 random draws of every row group), the tuple counts and the V4(a)/(b)/(d)/(e)/(f) regression and
identity checks from the RAW approved files only (plain numpy / pandas / scipy, its own loaders, its own cost, basket, counting and
percentile code), and compares them with the engine's evidence in tests/T11/evidence/<run>/.

It imports nothing from the engine or from any other module in analysis/ or data/, and it never reads the engine's source. The rules are those of
tests/T11/T11.md sections 1-3 (frozen) and tests/T11/logs/evidence_contract.md; the conventions are T08's and T09's verifiers' (forked from
verify_t08.py and verify_t09.py), except where T11.md differs (D26 calendar, own T0 = 2014-09-01, rule starts IN, D24b for MAUc1, seeds [14, ...],
bounds computed from the series). Its own spec, in its own words: tests/T11/logs/verifier_spec.md.

Gate-only read: V4(e) needs D24 (APPROVED row; T11.md section 3 lists it as 'Not read' by the test itself). It is opened here for that one check
only and is excluded from the 'every file the verifier read must be listed in inputs.csv' rule.

Usage (from AA/):
    python analysis/verify_t11.py                      # headline run + self-test on a corrupted copy
    python analysis/verify_t11.py --run smoke          # the smoke run (20 draws per group, one book)
    python analysis/verify_t11.py --evidence DIR --draws 30 --no-selftest
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
TOL = 1e-9                  # relative tolerance on NAVs and statistics (T11.md V1)
TOL_REG = 1e-12             # V4(a) regression against T06 / T08 stored NAVs
TOL_ID = 1e-12              # identities (V6)
TOL_CURVE = 1e-5            # float32 draw curves
N_DRAWS = 2000              # draws per row group (--draws overrides, for short runs)
T0_FULL = pd.Timestamp("2014-09-01")
END = pd.Timestamp("2019-01-02")
R3_START = pd.Timestamp("2015-01-02")
END_D17 = pd.Timestamp("2019-12-31")            # V4(a)/(f) slice
SC100_SIGNAL_FROM = pd.Timestamp("2011-11-25")  # standing rule 7
GW_BUY, GW_SELL, GW_FIX = 0.8, 0.2, 0.5
G0_YEAR_PP = 0.5
SEEDS = dict(n49=[14, 3], n410=[14, 6], n49g=[14, 11, 3], n410g=[14, 11, 6])     # seed = list + [draw_id]
FAMILY = {"F1": ("N4.10", "real"), "F2": ("N4.9", "real"), "F3": ("real", "N4.10-g"), "F4": ("real", "N4.9-g"), "F5": ("N4.10", "N4.10-g")}
STAT_COLS_ALL = ["end_nav", "cagr", "max_dd", "vol", "ulcer", "days_below_10pct", "longest_underwater", "calmar", "sessions"]
RUN_KINDS = ["strategy", "strategy_fixed50", "hold_parent", "constant_mix", "constant_mix_timed", "sleeve_only", "sleeve_only_timed"]
R7_BASE = ["strategy", "strategy_fixed50", "hold_parent"]
R7_KINDS = [f"{k}_r7_{v}" for v in ("flagged", "noexport") for k in R7_BASE]
APPROVED_MD = AA / "data" / "APPROVED_DATA.md"
T06_EVIDENCE = AA / "tests" / "T06" / "evidence" / "headline"
T08_EVIDENCE = AA / "tests" / "T08" / "evidence" / "headline"
STEP1_JSON = AA / "tests" / "T11" / "logs" / "step_1_spell_counts.json"
T11_MD = AA / "tests" / "T11" / "T11.md"

F_CAL = "Historical Data/extended_2026-11-12/index_daily_pre2019/nse_trading_days.csv"
F_MASTER = {n: f"Historical Data/extended_2026-10-30/Master/Master_{n}.xlsx" for n in ["Nifty100", "MC100", "SC100"]}
F_GMASTER = "Historical Data/extended_2026-11-12/MAUc1_from_2003/Master_MAUc1.xlsx"
F_GWEEKLY = "Historical Data/extended_2026-11-12/MAUc1_from_2003/mauc1_supertrend_weekly_extended.csv"
F_GDAILY = "Historical Data/extended_2026-11-12/MAUc1_from_2003/mauc1_daily_clean_extended.csv"
F_D24_MASTER = "Historical Data/extended_2026-11-06/MAUc1/Master_MAUc1.xlsx"       # gate-only (V4e)
F_D09 = "analysis/cache/why_gold_ohlc_eikon_extended_2026-11-04.parquet"
F_LBES = "Historical Data/LBES_Adjusted_Price_data_extended_2026-11-05.csv"
F_LIQ = "Historical Data/liquidEtfFinal_extended_2026-11-05.csv"
F_CORR = "data/holdings_matrix/price_corrections.csv"
# registry ids that T11.md section 3 lists as 'Not read' by the test (D24 is read here by the verifier only, as a gate-only read)
NOT_READ_IDS = {"D25", "D20", "D21", "D22", "D23", "D20b", "D23b", "D09b", "D12", "D03b", "D15", "D24"}

# ---- the frozen text's own numbers (T11.md section 2 and 3), the oracle for the verifier's re-derivation ----
FROZEN = {
    "full": dict(sessions=1070, weeks=228, first_state=1, last_state=0, in_spells=8, out_spells=8, S_in=93, S_out=135,
                 in_lengths=[7, 1, 6, 6, 28, 28, 14, 3], out_lengths=[7, 9, 16, 34, 12, 11, 30, 16],
                 g_first_state=1, g_last_state=1, g_buy_spells=10, g_sell_spells=9, g_S_buy=132, g_S_sell=96,
                 g_buy_lengths=[2, 4, 8, 12, 36, 15, 17, 24, 9, 5], g_sell_lengths=[19, 12, 6, 11, 15, 14, 5, 12, 2],
                 g_flips=18, g_flips_while_out_both_sides=9, g_flips_on_an_exit_decision=2, g_flips_while_in=7,
                 g_flip_dates_while_out=["2015-01-23", "2015-05-15", "2015-07-10", "2015-11-13", "2016-01-29", "2017-01-20", "2018-06-29", "2018-11-22", "2018-12-07"],
                 g_weeks_buy_while_out=81, g_weeks_sell_while_out=54, g_spells_with_an_out_week=16,
                 bounds=dict(in_=(1, 28), out=(2, 34), buy=(2, 36), sell=(2, 19)),
                 tuples=dict(in_=4024559144, out=19406343528, buy=6835192844305, sell=4976743356)),
    "r3": dict(sessions=989, weeks=210, first_state=0, in_spells=6, out_spells=7, S_in=85, S_out=125, g_first_state=0,
               g_buy_spells=9, g_sell_spells=9, g_S_buy=130, g_S_sell=80, g_flips=17, g_flips_while_out_both_sides=9,
               bounds=dict(in_=(2, 28), out=(2, 34), buy=(2, 36), sell=(2, 15)),
               tuples=dict(in_=7654290, out=659773128, buy=426468399525, sell=644288463)),
}
N_BASKETS = 19
FROZEN_EXPORT_SESSIONS = {"SCMO_0003": 574, "SCMO_0007": 123, "SCMO_0010": 556, "SCMO_0029": 122}
FROZEN_EXPORT_BY_STOCK = {"SCMO_0003": {"DISH": 164, "GEOM": 42, "MOL": 246, "OSCM": 122}, "SCMO_0007": {"HEXT": 62, "LAKSHVILAS": 61},
                          "SCMO_0010": {"DISH": 62, "GEOM": 42, "JMCPROJECT": 62, "LAKSHVILAS": 62, "MOL": 102, "OSCM": 60, "PEL": 42, "PIRAMALFIN": 124},
                          "SCMO_0029": {"GEOM": 122}}


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


# ----------------------------------------------------------------------------------------
# raw loaders
# ----------------------------------------------------------------------------------------
def load_calendar():
    d = pd.read_csv(rd(F_CAL))
    dates = pd.DatetimeIndex(pd.to_datetime(d["date"])).sort_values()
    assert dates.is_unique
    return dates[(dates >= T0_FULL) & (dates <= END)]


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


def load_mauc1_master():
    return _read_master(F_GMASTER)


def load_mauc1_weekly():
    w = pd.read_csv(rd(F_GWEEKLY))
    w["review"] = pd.to_datetime(w["review"])
    w["SIGN"] = w["SIGN"].astype(str).str.strip().str.upper()
    return w.sort_values("review").reset_index(drop=True)


def load_gold_files():
    g = pd.read_parquet(rd(F_D09))
    g = g[["date", "open", "high", "low", "close"]].copy()
    g["date"] = pd.to_datetime(g["date"]).dt.normalize()
    g = g.set_index("date").sort_index()
    m = pd.read_csv(rd(F_GDAILY))
    m = m.rename(columns={m.columns[0]: "date"})
    m["date"] = pd.to_datetime(m["date"]).dt.normalize()
    m = m.set_index("date").sort_index()
    return g, m


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


# ----------------------------------------------------------------------------------------
# market arrays on a calendar, book construction, windows
# ----------------------------------------------------------------------------------------
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


def decisions_for_window(p, cal, a, b, window, masters, gmaster):
    """Decision dates: the window's T0, then the last D26 session of each later ISO week. Evidence column layout, plus the MAUc1 columns. Every Master
    (the three indices and MAUc1) is read as-of: the latest row dated on or before the decision date."""
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
        rows.append(dict(book=p, window=window, j=j, decision_date=str(d.date()), decision_idx=int(ix),
                         trade_date=None if trade is None else str(trade.date()),
                         sign_Nifty100=signs[0], sign_MC100=signs[1], sign_SC100=signs[2],
                         label_Nifty100=str(labels[0].date()), label_MC100=str(labels[1].date()), label_SC100=str(labels[2].date()),
                         latest_label=str(latest.date()), label_age_days=int((d - latest).days),
                         all_three_buy=bool(buy), state=int(buy),
                         sign_MAUc1=gs, label_MAUc1=str(gl.date()), g=g, gw=GW_BUY if g == 1 else GW_SELL))
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------------------------
# the simulation (own implementation, T11.md section 3 steps 4-9)
# ----------------------------------------------------------------------------------------
def build_switches(states, gws, dec_idx, mix_f, e_fixed):
    """Session index -> (e_new, gw_new, kind, decision j) for every scheduled trade.
    strategy : a trade exists at decision j (traded on the next session) iff the equity target changes, or the target stays 0 and the sleeve's
               gold weight changes; the last decision is made, not traded. A change of g while IN is not a trade.
    mix      : every decision but the last (rebalance to e = f, gold weight gws[j] of the non-stock share), including after T0's decision.
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


def simulate(V, states, bps, dec_idx, gws, mix_f=None, e_fixed=None, closed_form=False, positions=False, W_override=None, Cn_override=None,
             F_override=None, C_override=None):
    """One realisation on view V (sessions 0..n-1).

    states : decision states s_0..s_(D-1); dec_idx : the decisions' session indices in V; gws : the gold weight of the sleeve at every decision.
    mix_f  : constant mix comparator (e = f, rebalance at every decision's next session and at every basket change)
    e_fixed: hold-the-parent (1) or sleeve only (0) at every decision."""
    n = V["n"]
    C = V["C"] if C_override is None else C_override
    Cn = V["Cn"] if Cn_override is None else Cn_override
    F = V["F"] if F_override is None else F_override
    gc, gf, L = V["gc"], V["gf"], V["L"]
    W = V["W"] if W_override is None else W_override
    S = len(V["S"])
    b_idx = V["b_idx"]
    basket_at = V["basket_at"]
    gws = np.asarray(gws, dtype=float)
    assert len(gws) == len(states)

    def basket_key(i):
        return b_idx[np.searchsorted(b_idx, i, side="right") - 1]

    w0 = W[V["k0"]]
    sh0 = np.where(w0 > 0, w0 / V["init_fill"], 0.0)       # the initial position, bought at the fills of the basket's first session; free of cost
    sh0 = sh0 / float((sh0 * Cn[0]).sum())                  # NAV = 1.000 at T0's close
    if mix_f is not None:
        e = float(mix_f)
    elif e_fixed is not None:
        e = float(e_fixed)
    else:
        e = float(states[0])
    gw_cur = float(gws[0])
    shares = sh0 * e if e > 0 else np.zeros(S)
    gu = (1 - e) * gw_cur / gc[0]
    cu = (1 - e) * (1 - gw_cur) / L[0]

    sw = build_switches(states, gws, dec_idx, mix_f, e_fixed)
    chg = [i for i in V["changes"] if i < n]
    events = sorted(set(k for k in sw if k < n) | set(chg))

    segs = [(0, shares.copy(), gu, cu)]
    trades = []
    for i in events:
        bk = basket_key(i)
        w = W[basket_at[bk]]
        pf = F[i]
        if i in sw:
            e_new, gw_new, kind, jdec = sw[i]
        else:
            e_new, gw_new, kind, jdec = e, gw_cur, "basket_change", None
            if e <= 0.0:
                continue      # basket change while OUT: nothing traded
        held = shares != 0
        tgt_stock = e_new * 1.0 * w
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
                           basket_eff=str(pd.Timestamp(V["avail"][basket_at[bk]]).date()),
                           V=Vv, traded=traded, cost=cost, j=jdec, gw_before=gw_before,
                           gold_before=cur_g, cash_before=cur_c, gold_after=tgt_g * f, cash_after=tgt_c * f,
                           raw_fill=bool(V["raw"][i])))

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


def gws_of(g, mode="timed"):
    g = np.asarray(g)
    if mode == "fixed50":
        return np.full(len(g), GW_FIX)
    return np.where(g == 1, GW_BUY, GW_SELL).astype(float)


# ----------------------------------------------------------------------------------------
# spells, nulls, counting (own implementations of T11.md section 3 step 11)
# ----------------------------------------------------------------------------------------
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


# ----------------------------------------------------------------------------------------
# derive everything that does not depend on the evidence
# ----------------------------------------------------------------------------------------
def basket_table(B):
    """The baskets effective from T0 to the window's end (availableDate on or after T0, effect session inside the window; skipped ones already dropped)."""
    rows = []
    no = 0
    for k in range(len(B["avail"])):
        if B["avail"][k] >= np.datetime64(B["cal"][0]) and B["eff"][k] < B["n"]:
            rows.append(dict(book=B["p"], basket_no=no, available_date=str(pd.Timestamp(B["avail"][k]).date()),
                             session_date=str(B["cal"][B["eff"][k]].date()), idx=int(B["eff"][k]), n_held=int((B["Wraw"][k] > 0).sum()),
                             raw_weight_sum=float(B["raw_sum"][k]), role="initial" if B["eff"][k] == 0 else "change"))
            no += 1
    return pd.DataFrame(rows)


def rule_for(states, gstates, dec_idx, n_sessions, start, end):
    R = rule_structure(states)
    R["g"] = rule_structure(gstates)
    R["states"] = states.astype(np.uint8)
    R["gstates"] = gstates.astype(np.uint8)
    R["dec_idx"] = dec_idx
    R["cover"] = week_cover(dec_idx)
    R["sessions"] = int(n_sessions)
    R["start"] = start
    R["end"] = end
    R["bounds"] = bounds_of(R)
    G = R["g"]
    R["g_bounds"] = dict(lo_buy=min(2, G["shortest_in"]), hi_buy=G["longest_in"], lo_sell=min(2, G["shortest_out"]), hi_sell=G["longest_out"])
    D_ = len(states)
    R["sleeve_trades"] = sum(1 for j in range(1, D_ - 1) if states[j] == 0 and states[j - 1] == 0 and gstates[j] != gstates[j - 1])
    R["sessions_invested"] = int((states.astype(np.int64) * R["cover"]).sum())
    gr = runs_of(gstates)
    pos, n_with = 0, 0
    for v_, l_ in gr:
        if (states[pos:pos + l_] == 0).any():
            n_with += 1
        pos += l_
    R["g_spells_with_an_out_week"] = n_with
    R["g_flips"] = len(gr) - 1
    R["g_flips_on_an_exit_decision"] = sum(1 for j in range(1, D_) if gstates[j] != gstates[j - 1] and states[j] == 0 and states[j - 1] == 1)
    R["g_flips_while_in"] = sum(1 for j in range(1, D_) if gstates[j] != gstates[j - 1] and states[j] == 1)
    R["g_flips_on_an_entry_decision"] = sum(1 for j in range(1, D_) if gstates[j] != gstates[j - 1] and states[j] == 1 and states[j - 1] == 0)
    R["g_weeks_buy_while_out"] = int(((gstates == 1) & (states == 0)).sum())
    R["g_weeks_sell_while_out"] = int(((gstates == 0) & (states == 0)).sum())
    return R


def r7_derive(B, V, states, gws_t, gws_5, dec_idx, cal):
    """R7 (contract point 7): flagged stock-days (|ffilled close return| >= 20% of a stock with weight > 0 in the basket in force on t-1 or t), the
    return-preserving splice, and the strategy / strategy_fixed50 / hold_parent NAVs at 0 and 20.8 bps with the flagged days (and with every
    export-priced held stock-day) set to a zero return."""
    n = V["n"]
    C = V["C"]
    b_idx, basket_at, W = V["b_idx"], V["basket_at"], V["W"]
    Wraw = B["Wraw"]
    wrow = np.array([basket_at[b_idx[np.searchsorted(b_idx, i, side="right") - 1]] for i in range(n)])
    Wr = W[wrow]                                       # renormalised weights in force on each session
    Wraw_s = Wraw[wrow]
    with np.errstate(divide="ignore", invalid="ignore"):
        ret = C[1:] / C[:-1] - 1.0
    held = (Wr[:-1] > 0) | (Wr[1:] > 0)                # basket in force on t-1 or t
    flag = np.zeros((n, len(V["S"])), dtype=bool)
    flag[1:] = (np.abs(ret) >= 0.20) & held & ~np.isnan(ret)
    PR = load_book_prices(B["p"], load_corrections())
    srcm = PR["src"][V["S"]].reindex(cal).values
    exp = np.zeros_like(flag)
    exp[1:] = (srcm[1:] == "export") & held
    rows = []
    for t, i in zip(*np.nonzero(flag)):
        rows.append(dict(book=B["p"], date=str(cal[t].date()), stock=V["S"][i], prev_close=float(C[t - 1, i]), close=float(C[t, i]), ret=float(ret[t - 1, i]),
                         w_prev=float(Wraw_s[t - 1, i]), w_cur=float(Wraw_s[t, i]), w_prev_n=float(Wr[t - 1, i]), w_cur_n=float(Wr[t, i]),
                         src=str(srcm[t, i])))
    # held stock-sessions priced from an export (T11.md section 3 contaminants): weight > 0 in the basket in force on that session
    exp_held = (srcm == "export") & (Wr > 0)
    by_stock = {V["S"][i].replace(".NS", ""): int(exp_held[:, i].sum()) for i in range(len(V["S"])) if exp_held[:, i].any()}
    out = dict(flagged=rows, export_by_stock=by_stock, export_total=int(exp_held.sum()), sims=[])
    ones = np.ones(len(states), dtype=int)
    for tag, msk in (("flagged", flag), ("noexport", exp)):
        M = np.ones((n, len(V["S"])))
        for t, i in zip(*np.nonzero(msk)):
            M[t:, i] *= C[t - 1, i] / C[t, i]
        C2 = C * M
        F2 = V["F"] * M
        Cn2 = np.nan_to_num(C2, nan=0.0)
        for bps in (0.0, HEADLINE_COST):
            for kind, st, gw, ef in (("strategy", states, gws_t, None), ("strategy_fixed50", states, gws_5, None), ("hold_parent", ones, gws_5, 1.0)):
                r = simulate(V, st, bps, dec_idx, gw, e_fixed=ef, Cn_override=Cn2, F_override=F2, C_override=C2)
                out["sims"].append((f"{kind}_r7_{tag}", bps, r))
    return out


def derive(books_main, verbose=True):
    t = time.time()
    cal = load_calendar()
    masters = load_masters()
    gmaster = load_mauc1_master()
    gold, mcx = load_gold_files()
    lbes, liq = load_lbes(), load_liquidcase()
    corr = load_corrections()
    MK = market_arrays(cal, gold, mcx, lbes, liq)
    n = len(cal)
    a_r3 = int(np.searchsorted(cal.values, np.datetime64(R3_START), side="left"))
    D = {"books": {}, "dec": [], "nav": [], "stats": [], "trades": [], "positions": [], "meta": {}, "rule": {}, "baskets": [], "r7": {}, "cal": cal,
         "masters": masters, "gmaster": gmaster, "MK": MK, "mcx": mcx, "gold": gold, "lbes": lbes, "liq": liq, "corr": corr, "a_r3": a_r3,
         "one_instrument": {}, "hold0": {}}
    for p in books_main:
        B = build_book(p, cal, MK, corr)
        V = make_view(B, 0, n, "lbes")
        Vliq = make_view(B, 0, n, "liq")
        Vr3 = make_view(B, a_r3, n, "lbes")
        dec = decisions_for_window(p, cal, 0, n, "full", masters, gmaster)
        dec3 = decisions_for_window(p, cal, a_r3, n, "r3", masters, gmaster)
        s, gs, di = dec["state"].values.astype(int), dec["g"].values.astype(int), dec["decision_idx"].values
        s3, gs3, di3 = dec3["state"].values.astype(int), dec3["g"].values.astype(int), dec3["decision_idx"].values
        nd = len(s)
        f_mix = s.sum() / nd
        rule = {"full": rule_for(s, gs, di, n, str(cal[0].date()), str(cal[-1].date())),
                "r3": rule_for(s3, gs3, di3, n - a_r3, str(cal[a_r3].date()), str(cal[-1].date()))}
        D["rule"][p] = rule
        bt = basket_table(B)
        D["baskets"].append(bt)
        D["meta"][p] = dict(sessions=n, decisions=nd, invested_weeks=int(s.sum()), t0=str(cal[0].date()), end=str(cal[-1].date()), f=f_mix,
                            in_spells=rule["full"]["in_spells"], out_spells=rule["full"]["out_spells"], baskets=len(bt),
                            sleeve_trades=rule["full"]["sleeve_trades"], sessions_invested=rule["full"]["sessions_invested"],
                            stale=int(((dec["label_age_days"] >= 5) & (dec["j"] > 0)).sum()), skipped_dropped=[str(pd.Timestamp(x).date()) for x in B["skipped"]],
                            sessions_without_any_d18_bar=B["sessions_all_stocks_no_bar"],
                            no_mcx_range_sessions=[str(cal[i].date()) for i in np.flatnonzero(MK["raw"])],
                            no_own_gold_bar_sessions=[str(cal[i].date()) for i in np.flatnonzero(~MK["own_gold_bar"])])
        D["dec"].extend([dec, dec3])
        gw_t, gw_5 = gws_of(gs), gws_of(gs, "fixed50")
        gw_t3, gw_53 = gws_of(gs3), gws_of(gs3, "fixed50")
        D["books"][p] = dict(B=B, V=V, Vliq=Vliq, Vr3=Vr3, dec_idx=di, dec_idx_r3=di3, s=s, s_r3=s3, g=gs, g_r3=gs3, gw_t=gw_t, gw_5=gw_5,
                             gw_t3=gw_t3, gw_53=gw_53, f=f_mix)

        def add(window, cash, kind, bps, r, wk):
            st = stats_of(r["nav"])
            ev = [x["e_after"] for x in r["trades"]]
            st.update(book=p, window=window, cash=cash, cost_bps=bps, kind=kind, trades=len(r["trades"]),
                      cost_paid=float(sum(x["cost"] for x in r["trades"])), closed_rel=r["closed_rel"], n_segments=r["n_segments"],
                      end_from_segments=r["end_from_segments"], invested_weeks=float(wk),
                      sleeve_trades=int(sum(1 for x in r["trades"] if x["kind"] == "sleeve_rebalance")),
                      basket_trades=int(sum(1 for x in r["trades"] if x["kind"] == "basket_change")))
            D["stats"].append(st)

        ones, zeros = np.ones(nd, dtype=int), np.zeros(nd, dtype=int)
        for bps in COSTS:
            runs = {
                "strategy": (simulate(V, s, bps, di, gw_t, closed_form=True, positions=True), float(s.sum())),
                "strategy_fixed50": (simulate(V, s, bps, di, gw_5), float(s.sum())),
                "hold_parent": (simulate(V, ones, bps, di, gw_5, e_fixed=1.0), float(nd)),
                "constant_mix": (simulate(V, s, bps, di, gw_5, mix_f=f_mix), f_mix * nd),
                "constant_mix_timed": (simulate(V, s, bps, di, gw_t, mix_f=f_mix), f_mix * nd),
                "sleeve_only": (simulate(V, zeros, bps, di, gw_5, e_fixed=0.0), 0.0),
                "sleeve_only_timed": (simulate(V, zeros, bps, di, gw_t, e_fixed=0.0), 0.0),
            }
            for kind, (r, wk) in runs.items():
                add("full", "lbes", kind, bps, r, wk)
                D["nav"].append(pd.DataFrame(dict(book=p, date=[str(d.date()) for d in cal], cost_bps=bps, run=kind, nav=r["nav"])))
                for x in r["trades"]:
                    D["trades"].append(dict(book=p, cost_bps=bps, run=kind, **x))
                if kind == "strategy":
                    for dt, nm, u in r["positions"]:
                        D["positions"].append(dict(book=p, cost_bps=bps, run="strategy", date=dt, instrument=nm, units=u))
                if kind == "hold_parent" and bps == 0.0:
                    D["hold0"][p] = r["nav"]
        add("full", "liq", "strategy", HEADLINE_COST, simulate(Vliq, s, HEADLINE_COST, di, gw_t), float(s.sum()))
        add("full", "liq", "strategy_fixed50", HEADLINE_COST, simulate(Vliq, s, HEADLINE_COST, di, gw_5), float(s.sum()))
        add("r3", "lbes", "strategy", HEADLINE_COST, simulate(Vr3, s3, HEADLINE_COST, di3, gw_t3), float(s3.sum()))
        add("r3", "lbes", "strategy_fixed50", HEADLINE_COST, simulate(Vr3, s3, HEADLINE_COST, di3, gw_53), float(s3.sum()))
        # R7
        r7 = r7_derive(B, V, s, gw_t, gw_5, di, cal)
        D["r7"][p] = r7
        for kind, bps, r in r7["sims"]:
            wk = float(nd) if kind.startswith("hold_parent") else float(s.sum())
            add("full", "lbes", kind, bps, r, wk)
            D["nav"].append(pd.DataFrame(dict(book=p, date=[str(d.date()) for d in cal], cost_bps=bps, run=kind, nav=r["nav"])))
        # V4(b): one instrument at weight 1, 0 cost, always in = close / first close
        W0 = B["W"][V["k0"]]
        res = []
        for i in np.flatnonzero(W0 > 0):
            W1 = np.zeros_like(B["W"]); W1[:, i] = 1.0
            r = simulate(V, ones, 0.0, di, gw_5, e_fixed=1.0, W_override=W1)
            tgt = V["C"][:, i] / V["C"][0, i]
            res.append((B["S"][i], float(np.max(np.abs(r["nav"] - tgt) / np.abs(tgt)))))
        D["one_instrument"][p] = res
        if verbose:
            print(f"[{time.time()-t:6.1f}s] {p}: derived (sessions {n}, stocks {len(B['S'])}, baskets {len(bt)}, f={f_mix:.4f}, sleeve trades {rule['full']['sleeve_trades']})", flush=True)
    D["dec"] = pd.concat(D["dec"], ignore_index=True)
    D["nav"] = pd.concat(D["nav"], ignore_index=True)
    D["stats"] = pd.DataFrame(D["stats"])
    D["trades"] = pd.DataFrame(D["trades"])
    D["positions"] = pd.DataFrame(D["positions"])
    D["baskets"] = pd.concat(D["baskets"], ignore_index=True)
    return D


def derive_regression(D, verbose=True):
    """V4(a) and V4(f): with D17's calendar (each book's own first date to 2019-12-31) the verifier's runs against the stored daily_nav.csv of T08 and
    T06 on the same sessions; the hold-the-parent 0-cost NAV against the published NAV (seam). All four books."""
    t = time.time()
    masters, gmaster, gold, mcx, lbes, liq, corr = D["masters"], D["gmaster"], D["gold"], D["mcx"], D["lbes"], D["liq"], D["corr"]
    out = dict(books={}, t08=[], t06=[], seam=[], t08_dec={}, t06_dec={})
    for p in BOOKS:
        pub = load_published_nav(p)
        cal17 = pub.index[pub.index <= END_D17]
        MK17 = market_arrays(cal17, gold, mcx, lbes, liq)
        B = build_book(p, cal17, MK17, corr)
        n = len(cal17)
        V = make_view(B, 0, n)
        dec = decisions_for_window(p, cal17, 0, n, "d17", masters, gmaster)
        s, g, di = dec["state"].values.astype(int), dec["g"].values.astype(int), dec["decision_idx"].values
        out["books"][p] = dict(first=str(cal17[0].date()), last=str(cal17[-1].date()), sessions=n, decisions=len(s), dec=dec)
        nd = len(s)
        ones, zeros = np.ones(nd, dtype=int), np.zeros(nd, dtype=int)
        gw_t, gw_5 = gws_of(g), gws_of(g, "fixed50")
        for tag, mixf in (("t08", None), ("t06", None)):
            pass
        d8 = pd.read_csv(T08_EVIDENCE / "decisions.csv")
        d6 = pd.read_csv(T06_EVIDENCE / "decisions.csv")
        f08 = float(d8[d8["book"] == p]["state"].mean())
        f06 = float(d6[d6["book"] == p]["state"].mean())
        for bps in COSTS:
            r8 = {"strategy": simulate(V, s, bps, di, gw_t), "strategy_fixed50": simulate(V, s, bps, di, gw_5),
                  "hold_parent": simulate(V, ones, bps, di, gw_5, e_fixed=1.0),
                  "constant_mix": simulate(V, s, bps, di, gw_5, mix_f=f08), "constant_mix_timed": simulate(V, s, bps, di, gw_t, mix_f=f08),
                  "sleeve_only": simulate(V, zeros, bps, di, gw_5, e_fixed=0.0), "sleeve_only_timed": simulate(V, zeros, bps, di, gw_t, e_fixed=0.0)}
            for k, r in r8.items():
                out["t08"].append(pd.DataFrame(dict(book=p, date=[str(d.date()) for d in cal17], cost_bps=bps, run=k, nav=r["nav"])))
            r6 = {"strategy": r8["strategy_fixed50"], "hold_parent": r8["hold_parent"], "sleeve_only": r8["sleeve_only"],
                  "constant_mix": simulate(V, s, bps, di, gw_5, mix_f=f06)}
            for k, r in r6.items():
                out["t06"].append(pd.DataFrame(dict(book=p, date=[str(d.date()) for d in cal17], cost_bps=bps, run=k, nav=r["nav"])))
            if bps == 0.0:
                nv = r8["hold_parent"]["nav"]
                pv = pub.loc[cal17].values
                gap = float((nv[-1] / nv[0] - pv[-1] / pv[0]) * 100.0)
                out["seam"].append(dict(book=p, first=str(cal17[0].date()), last=str(cal17[-1].date()), year_gap_pp=gap, limit_pp=G0_YEAR_PP))
        out["t08_dec"][p] = dec
        if verbose:
            print(f"[{time.time()-t:6.1f}s] {p}: D17-calendar regression runs done ({n} sessions from {cal17[0].date()})", flush=True)
    out["t08"] = pd.concat(out["t08"], ignore_index=True)
    out["t06"] = pd.concat(out["t06"], ignore_index=True)
    return out


# ----------------------------------------------------------------------------------------
# evidence access and helpers for the checks
# ----------------------------------------------------------------------------------------
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


def required_through(key):
    """Latest date an approved row must reach: the window's end (2019-01-02); the published NAVs are read to 2019-12-31 (V4(a), V4(f))."""
    return END_D17 if "published_nav" in key else END


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


# ----------------------------------------------------------------------------------------
# the checks (part 1: data, signals, NAVs, trades, sleeve, regression)
# ----------------------------------------------------------------------------------------
STEP1 = json.load(open(STEP1_JSON)) if STEP1_JSON.exists() else None


def compare_part1(D, REG, E, BK):
    C = {}
    nd_draws = N_DRAWS
    cal = D["cal"]
    dates_str = [str(d.date()) for d in cal]
    date_idx = {s: i for i, s in enumerate(dates_str)}
    RULE = D["rule"]
    WINDOWS = ["full", "r3"]
    NUMS = ["end_nav", "cagr", "max_dd", "vol"]
    NUMS_ALL = NUMS + ["ulcer", "calmar"]
    INTS = ["days_below_10pct", "longest_underwater", "sessions"]

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
                    ok = pd.Timestamp(row["through"]) >= required_through(key)
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
                c.failed += 1; c.fail(f"inputs.csv lists {key} (row {row['id']}), which T11.md section 3 lists under 'Not read'")
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
                if row["through"].lower() != "n/a" and pd.Timestamp(row["through"]) < required_through(key):
                    c.failed += 1; c.fail(f"approved through-date of {key} ({row['through']}) does not cover the window's end")
                if th.lower() not in ("n/a", "nan") and row["through"].lower() != "n/a" and th != row["through"]:
                    c.failed += 1; c.fail(f"through of {key} in inputs.csv ({th}) differs from APPROVED_DATA.md ({row['through']})")
            if "usable_from" in cols:          # standing rule 7: the usable_from of a restricted file in inputs.csv is the registry's marker
                c.compared += 1
                uv = r[cols["usable_from"]]
                uv = None if (uv is None or (isinstance(uv, float) and np.isnan(uv)) or str(uv).strip() in ("", "nan", "None")) else str(uv).strip()
                if uv != row["usable_from"]:
                    c.failed += 1; c.fail(f"usable_from of {key} in inputs.csv ({uv}) differs from the registry's marker ({row['usable_from']})")
        for key in sorted(set(READS) - listed):          # a file needed to rebuild the run but not listed by the engine (gate-only reads excepted)
            if READS[key]["gate_only"]:
                c.notes.append(f"gate-only read (not part of the run, V4(e)): {key}")
                continue
            c.compared += 1; c.failed += 1; c.fail(f"a file needed to rebuild the run is not in inputs.csv: {key}")
        extra = sorted(listed - set(READS))
        if extra:
            c.notes.append(f"inputs.csv lists {len(extra)} file(s) the verifier did not read: {extra[:4]}")
        c.notes.append(f"{len(READS)} files read by the verifier, {len(listed)} listed in inputs.csv")
    run_check(C, "C-data", c_data)

    # ------------------------------------------------------------------ standing rule 7 (V1, V2)
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
        c.compared += 1
        if APPROVED[F_MASTER["SC100"]]["usable_from"] != "2011-11-25":
            c.failed += 1; c.fail("the registry row of the Smallcap 100 Master carries no usable-from 2011-11-25")
        c.compared += 1
        if READS[F_MASTER["SC100"]]["first_date"] != "2011-11-25":
            c.failed += 1; c.fail(f"the verifier read the Smallcap 100 Master from {READS[F_MASTER['SC100']]['first_date']}")
        c.compared += 1
        if (D["dec"]["label_SC100"] < "2011-11-25").any():
            c.failed += 1; c.fail("a Smallcap 100 decision reads a Master row dated before 2011-11-25")
        d0 = E.get("decisions.csv")
        if d0 is not None and "label_SC100" in d0.columns:
            c.compared += 1
            if (d0["label_SC100"].astype(str) < "2011-11-25").any():
                c.failed += 1; c.fail("the engine's decisions read a Smallcap 100 Master row dated before 2011-11-25")
    run_check(C, "C-sc100-restriction", c_sc100)

    # ------------------------------------------------------------------ the frozen text's numbers (T11.md section 2) against the verifier's own derivation
    def c_frozen(c):
        for p in BK:
            for window in WINDOWS:
                R = RULE[p][window]
                G = R["g"]
                fz = FROZEN[window]
                pairs = [("sessions", R["sessions"], fz["sessions"]), ("weeks", R["weeks"], fz["weeks"]), ("first_state", R["first_state"], fz["first_state"]),
                         ("in_spells", R["in_spells"], fz["in_spells"]), ("out_spells", R["out_spells"], fz["out_spells"]), ("S_in", R["S_in"], fz["S_in"]),
                         ("S_out", R["S_out"], fz["S_out"]), ("g_first_state", G["first_state"], fz["g_first_state"]), ("g_buy_spells", G["in_spells"], fz["g_buy_spells"]),
                         ("g_sell_spells", G["out_spells"], fz["g_sell_spells"]), ("g_S_buy", G["S_in"], fz["g_S_buy"]), ("g_S_sell", G["S_out"], fz["g_S_sell"]),
                         ("g_flips", R["g_flips"], fz["g_flips"]), ("sleeve_trades", R["sleeve_trades"], fz["g_flips_while_out_both_sides"]),
                         ("bound_in", (R["bounds"]["lo_in"], R["bounds"]["hi_in"]), fz["bounds"]["in_"]),
                         ("bound_out", (R["bounds"]["lo_out"], R["bounds"]["hi_out"]), fz["bounds"]["out"]),
                         ("bound_buy", (R["g_bounds"]["lo_buy"], R["g_bounds"]["hi_buy"]), fz["bounds"]["buy"]),
                         ("bound_sell", (R["g_bounds"]["lo_sell"], R["g_bounds"]["hi_sell"]), fz["bounds"]["sell"])]
                if window == "full":
                    pairs += [("last_state", R["last_state"], fz["last_state"]), ("in_lengths", R["in_lengths"], fz["in_lengths"]), ("out_lengths", R["out_lengths"], fz["out_lengths"]),
                              ("g_last_state", G["last_state"], fz["g_last_state"]), ("g_buy_lengths", G["in_lengths"], fz["g_buy_lengths"]),
                              ("g_sell_lengths", G["out_lengths"], fz["g_sell_lengths"]), ("g_flips_on_an_exit_decision", R["g_flips_on_an_exit_decision"], fz["g_flips_on_an_exit_decision"]),
                              ("g_flips_while_in", R["g_flips_while_in"], fz["g_flips_while_in"]), ("g_weeks_buy_while_out", R["g_weeks_buy_while_out"], fz["g_weeks_buy_while_out"]),
                              ("g_weeks_sell_while_out", R["g_weeks_sell_while_out"], fz["g_weeks_sell_while_out"]),
                              ("g_spells_with_an_out_week", R["g_spells_with_an_out_week"], fz["g_spells_with_an_out_week"])]
                for nm, mine, want in pairs:
                    c.compared += 1
                    if mine != want:
                        c.failed += 1; c.fail(f"{p}|{window} {nm}: verifier {mine!r} vs T11.md {want!r}")
                # tuple counts (inclusion-exclusion) against the frozen text
                for nm, k, S, lo, hi in (("in_", R["in_spells"], R["S_in"], R["bounds"]["lo_in"], R["bounds"]["hi_in"]),
                                         ("out", R["out_spells"], R["S_out"], R["bounds"]["lo_out"], R["bounds"]["hi_out"]),
                                         ("buy", G["in_spells"], G["S_in"], R["g_bounds"]["lo_buy"], R["g_bounds"]["hi_buy"]),
                                         ("sell", G["out_spells"], G["S_out"], R["g_bounds"]["lo_sell"], R["g_bounds"]["hi_sell"])):
                    c.compared += 1
                    if n_ways(k, S, lo, hi) != fz["tuples"][nm]:
                        c.failed += 1; c.fail(f"{p}|{window} {nm}: inclusion-exclusion {n_ways(k, S, lo, hi)} vs T11.md {fz['tuples'][nm]}")
            # flip dates while OUT on both sides, 228 decisions, and the first decision date
            dec = D["dec"][(D["dec"]["book"] == p) & (D["dec"]["window"] == "full")].reset_index(drop=True)
            s_, g_ = dec["state"].values, dec["g"].values
            fd = [dec["decision_date"].iloc[j] for j in range(1, len(dec) - 1) if s_[j] == 0 and s_[j - 1] == 0 and g_[j] != g_[j - 1]]
            c.compared += 2
            if fd != FROZEN["full"]["g_flip_dates_while_out"]:
                c.failed += 1; c.fail(f"{p}: flip dates while OUT {fd} vs T11.md")
            if dec["decision_date"].iloc[0] != "2014-09-01" or dec["decision_date"].iloc[-1] != "2019-01-02":
                c.failed += 1; c.fail(f"{p}: first / last decision date {dec['decision_date'].iloc[0]} / {dec['decision_date'].iloc[-1]}")
            # baskets
            bt = D["baskets"][D["baskets"]["book"] == p]
            c.compared += 3
            if len(bt) != N_BASKETS or bt["role"].iloc[0] != "initial" or bt["session_date"].iloc[0] != "2014-09-01" or (bt["role"].iloc[1:] != "change").any():
                c.failed += 1; c.fail(f"{p}: {len(bt)} baskets T0 to END (T11.md: 19, the first the initial one on 2014-09-01)")
            if bt["available_date"].iloc[-1] != "2018-12-17":
                c.failed += 1; c.fail(f"{p}: last basket effective {bt['available_date'].iloc[-1]} (T11.md: 2018-12-17)")
            if D["meta"][p]["skipped_dropped"]:
                c.compared += 1
                if any(pd.Timestamp(x) >= T0_FULL and pd.Timestamp(x) <= END for x in D["meta"][p]["skipped_dropped"]):
                    c.failed += 1; c.fail(f"{p}: a skipped basket inside the window ({D['meta'][p]['skipped_dropped']}); T11.md says none")
            # the export stock-sessions (T11.md section 3 contaminants)
            r7 = D["r7"][p]
            c.compared += 1
            if r7["export_total"] != FROZEN_EXPORT_SESSIONS[p] or r7["export_by_stock"] != FROZEN_EXPORT_BY_STOCK[p]:
                c.failed += 1; c.fail(f"{p}: export-priced held stock-sessions {r7['export_total']} {r7['export_by_stock']} vs T11.md {FROZEN_EXPORT_SESSIONS[p]} {FROZEN_EXPORT_BY_STOCK[p]}")
            c.compared += 1
            if "2017-10-19" not in D["meta"][p]["sessions_without_any_d18_bar"]:
                c.failed += 1; c.fail(f"{p}: 2017-10-19 has D18 bars for some stock (T11.md: none)")
        if STEP1 is not None:
            for window in WINDOWS:
                e = STEP1[window]
                for p in BK:
                    R = RULE[p][window]; G = R["g"]
                    pairs = [("weeks", R["weeks"]), ("sessions", R["sessions"]), ("first_state", R["first_state"]), ("last_state", R["last_state"]),
                             ("in_spells", R["in_spells"]), ("out_spells", R["out_spells"]), ("S_in", R["S_in"]), ("S_out", R["S_out"]),
                             ("in_lengths", R["in_lengths"]), ("out_lengths", R["out_lengths"]), ("start", R["start"]), ("end", R["end"]),
                             ("g_first_state", G["first_state"]), ("g_last_state", G["last_state"]), ("g_buy_spells", G["in_spells"]),
                             ("g_sell_spells", G["out_spells"]), ("g_S_buy", G["S_in"]), ("g_S_sell", G["S_out"]), ("g_buy_lengths", G["in_lengths"]),
                             ("g_sell_lengths", G["out_lengths"]), ("g_weeks_buy_while_out", R["g_weeks_buy_while_out"]),
                             ("g_weeks_sell_while_out", R["g_weeks_sell_while_out"]), ("g_flips_while_out_both_sides", R["sleeve_trades"]),
                             ("g_flips", R["g_flips"]), ("g_spells_with_an_out_week", R["g_spells_with_an_out_week"]),
                             ("round_trips", min(R["in_spells"], R["out_spells"]))]
                    for k_, mv in pairs:
                        if k_ in e:
                            c.compared += 1
                            if mv != e[k_]:
                                c.failed += 1; c.fail(f"{p}|{window} {k_}: verifier {mv!r} vs logs/step_1_spell_counts.json {e[k_]!r}")
        else:
            c.notes.append("logs/step_1_spell_counts.json not found; not compared")
    run_check(C, "C-frozen-counts", c_frozen)

    # ------------------------------------------------------------------ C-dec, C-pit
    dec_m = D["dec"]

    def c_dec(c):
        ev = E.get("decisions.csv", c)
        if ev is None:
            return
        ev = ev[ev["book"].isin(BK)].copy()
        ev["all_three_buy"] = ev["all_three_buy"].astype(str)
        mine = dec_m[(dec_m["window"] == "full") & dec_m["book"].isin(BK)].copy()
        mine["all_three_buy"] = mine["all_three_buy"].astype(str)
        str_cols = ["trade_date", "sign_Nifty100", "sign_MC100", "sign_SC100", "label_Nifty100", "label_MC100", "label_SC100",
                    "latest_label", "decision_date", "all_three_buy", "sign_MAUc1", "label_MAUc1"]
        compare_frames(c, mine, ev, ["book", "j"], num_cols=["decision_idx", "label_age_days", "state", "g", "gw"], str_cols=str_cols)
    run_check(C, "C-dec", c_dec)

    def c_pit(c):
        ev = E.get("decisions.csv", c)
        lcs = ["label_Nifty100", "label_MC100", "label_SC100", "label_MAUc1"]
        bsk = E.get("baskets.csv", c)
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
                # a basket change is on the session of its availableDate (the first session on or after it)
                bc = tr[tr["kind"] == "basket_change"]
                if bsk is not None:
                    keyset = set(zip(bsk["book"], bsk["session_date"].astype(str)))
                    okb = np.array([(b, str(d)) in keyset for b, d in zip(bc["book"], bc["date"])], dtype=bool)
                    c.compared += len(bc); c.failed += int((~okb).sum())
                    if (~okb).any(): c.fail("basket change not on a basket's availableDate session: %s" % bc[~okb].iloc[0][["book", "run", "date"]].to_dict())
            stt = E.get("sleeve_trades.csv", c)
            if stt is not None:
                ok = (stt["date"].astype(str) > stt["decision_date"].astype(str)).values
                c.compared += len(stt); c.failed += int((~ok).sum())
                if (~ok).any(): c.fail("sleeve trade not after its decision: %s" % stt[~ok].iloc[0][["book", "decision_date", "date"]].to_dict())
        md = dec_m[dec_m["window"] == "full"]
        for lc in lcs:
            ok = (md[lc] <= md["decision_date"]).values
            c.compared += len(md); c.failed += int((~ok).sum())
        mt = md["trade_date"].notna()
        ok = (md.loc[mt, "trade_date"] > md.loc[mt, "decision_date"]).values
        c.compared += int(mt.sum()); c.failed += int((~ok).sum())
        bt = D["baskets"]
        for _, r in bt.iterrows():                 # my own baskets: effect session = first session on or after availableDate, none after END
            c.compared += 1
            i = int(r["idx"])
            if cal[i] < pd.Timestamp(r["available_date"]) or (i > 0 and cal[i - 1] >= pd.Timestamp(r["available_date"])):
                c.failed += 1; c.fail(f"basket {r.to_dict()}: effect session is not the first session on or after availableDate")
        c.compared += 1
        if any(m["end"] != str(END.date()) for m in D["meta"].values()):
            c.failed += 1; c.fail("a book's calendar does not end at 2019-01-02")
    run_check(C, "C-pit", c_pit)

    # ------------------------------------------------------------------ the gold signal, V4(d), V4(e)
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
        wd = wk["review"].values
        for r in dec_m[dec_m["window"] == "full"].itertuples():
            pos = int(np.searchsorted(wd, np.datetime64(pd.Timestamp(r.decision_date)), side="right") - 1)
            c.compared += 1
            if pos < 0 or int(wk["signal"].iloc[pos]) != r.g or wk["SIGN"].iloc[pos] != r.sign_MAUc1 or str(wk["review"].iloc[pos].date()) != r.label_MAUc1:
                c.failed += 1; c.fail(f"g at {r.book} j={r.j} {r.decision_date}: Master {r.sign_MAUc1} (row {r.label_MAUc1}) vs weekly csv row {wk['review'].iloc[pos].date() if pos >= 0 else None}")
        gs_ev = E.get("gold_signal.csv", c)
        if gs_ev is not None:
            gs_ev = gs_ev[gs_ev["book"].isin(BK)]
            mine = dec_m[(dec_m["window"] == "full") & dec_m["book"].isin(BK)][["book", "j", "decision_date", "label_MAUc1", "sign_MAUc1", "g", "gw"]]
            compare_frames(c, mine, gs_ev[["book", "j", "decision_date", "label_MAUc1", "sign_MAUc1", "g", "gw"]], ["book", "j"],
                           num_cols=["g", "gw"], str_cols=["decision_date", "label_MAUc1", "sign_MAUc1"])
    run_check(C, "C-gold", c_gold)

    def c_d24(c):
        """V4(e): D24b equals D24 on every shared decision date (gate-only read of D24's Master)."""
        d24 = _read_master(F_D24_MASTER, None, gate_only=True)
        b = D["gmaster"]
        first24 = pd.Timestamp(d24[0][0])
        s24 = pd.Series(d24[1], index=pd.to_datetime(d24[0]))
        sb = pd.Series(b[1], index=pd.to_datetime(b[0]))
        sh = s24.index.intersection(sb.index)
        c.compared += len(sh)
        bad = int((s24.loc[sh].values != sb.loc[sh].values).sum())
        c.failed += bad
        if bad: c.fail(f"D24 and D24b SIGN differ on {bad} of {len(sh)} shared Master weeks")
        # every shared Master week of D24 inside the window is in D24b
        inwin = s24.index[(s24.index >= pd.Timestamp("2014-08-01")) & (s24.index <= END + pd.Timedelta(days=7))]
        c.compared += len(inwin)
        c.failed += int((~inwin.isin(sb.index)).sum())
        nshared = 0
        for r in dec_m[(dec_m["window"] == "full") & (dec_m["book"] == dec_m["book"].iloc[0])].itertuples():
            if pd.Timestamp(r.decision_date) < first24:
                continue
            s_, l_ = _asof(d24[0], d24[1], pd.Timestamp(r.decision_date))
            nshared += 1
            c.compared += 1
            if s_ != r.sign_MAUc1 or str(l_.date()) != r.label_MAUc1:
                c.failed += 1; c.fail(f"decision {r.decision_date}: D24b {r.sign_MAUc1} (row {r.label_MAUc1}) vs D24 {s_} (row {l_.date()})")
        c.compared += 1
        if nshared == 0:
            c.failed += 1; c.fail("no shared decision date between D24 and D24b was compared")
        c.notes.append(f"D24's first SIGN row {first24.date()}; {nshared} shared decision dates; {len(sh)} shared Master weeks; gate-only read (T11.md section 3 lists D24 as not read by the test)")
        reg = E.get("regression.json")
        if reg is not None and "e_d24b_vs_d24" in reg:
            c.notes.append(f"the engine compared D24b with T08's stored gold signal on 2019 only: {json.dumps(reg['e_d24b_vs_d24'])[:160]}")
    run_check(C, "C-d24b-vs-d24", c_d24)

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

    def est(window="full", cash="lbes"):
        return est_all[(est_all["window"] == window) & (est_all["cash"] == cash)]

    def nav_subset(df, kinds, costs):
        return df[df["run"].isin(kinds) & df["cost_bps"].isin(costs)]

    def stat_subset(df, kinds, costs, window="full", cash="lbes", col="kind"):
        m = df[df[col].isin(kinds) & df["cost_bps"].isin(costs)]
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
        """Every statistic of every full-window LBES stats row (secondary statistics, trades, cost paid, invested weeks, sleeve and basket trades), seven runs, all costs."""
        if est_all is None:
            E.get("stats.csv", c); return
        keys = ["book", "cost_bps", "kind"]
        cols = NUMS_ALL + INTS + ["trades", "cost_paid", "invested_weeks", "sleeve_trades", "basket_trades"]
        for cc in cols:
            if cc not in est_all.columns:
                c.miss(f"stats.csv column {cc}")
        cols = [cc for cc in cols if cc in est_all.columns]
        compare_frames(c, stat_subset(mst, RUN_KINDS, COSTS)[keys + cols], stat_subset(est(), RUN_KINDS, COSTS)[keys + cols], keys, num_cols=cols)
    run_check(C, "C-stats-all", c_stats_all)

    def c_comp(c):
        """NAVs of every run but the strategy (Part A, hold-the-parent, constant mixes, sleeve-only) at every cost, and of the six R7 variants (0 and 20.8)."""
        if env_all is None or est_all is None:
            E.get("daily_nav.csv", c); E.get("stats.csv", c); return
        kinds = [k for k in RUN_KINDS if k != "strategy"]
        compare_frames(c, nav_subset(mnv, kinds, COSTS), nav_subset(env_all, kinds, COSTS), ["book", "date", "cost_bps", "run"], num_cols=["nav"])
        compare_frames(c, nav_subset(mnv, R7_KINDS, [0.0, HEADLINE_COST]), nav_subset(env_all, R7_KINDS, [0.0, HEADLINE_COST]), ["book", "date", "cost_bps", "run"], num_cols=["nav"])
        keys = ["book", "cost_bps", "kind"]
        compare_frames(c, stat_subset(mst, R7_KINDS, [0.0, HEADLINE_COST])[keys + NUMS_ALL + INTS], stat_subset(est(), R7_KINDS, [0.0, HEADLINE_COST])[keys + NUMS_ALL + INTS],
                       keys, num_cols=NUMS_ALL + INTS)
    run_check(C, "C-comparators-r7", c_comp)

    def c_r2r3(c):
        if est_all is None:
            E.get("stats.csv", c); return
        keys = ["book", "window", "cash", "cost_bps", "kind"]
        cols = NUMS_ALL + INTS + ["trades", "cost_paid", "invested_weeks", "sleeve_trades", "basket_trades"]
        for window, cash in (("full", "liq"), ("r3", "lbes")):
            m = mst[(mst["window"] == window) & (mst["cash"] == cash)][keys + cols]
            e = est_all[(est_all["window"] == window) & (est_all["cash"] == cash) & (est_all["cost_bps"] == HEADLINE_COST)][keys + cols]
            compare_frames(c, m, e, keys, num_cols=cols)
    run_check(C, "C-stats-liquidcase-r3", c_r2r3)

    def c_parent_nav(c):
        """The rebuilt parent NAV file: base 1.0 at T0 in every column, no '#' line, the caption in its sidecar, and the numbers equal the verifier's."""
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
        cmap = {"hold_parent_0bps": ("hold_parent", 0.0), "hold_parent_20.8bps": ("hold_parent", 20.8), "part_a_20.8bps": ("strategy_fixed50", 20.8),
                "part_b_20.8bps": ("strategy", 20.8)}
        first = pn.sort_values("date").groupby("book").head(1)
        for col in cmap:
            c.compared += len(first)
            bad = ((first[col].astype(float) - 1.0).abs() > 1e-12)
            c.failed += int(bad.sum())
            if bad.any(): c.fail(f"parent NAV {col}: first row is not 1.0")
        for col, (run, bps) in cmap.items():
            m = mnv[(mnv["run"] == run) & (mnv["cost_bps"] == bps)][["book", "date", "nav"]].rename(columns={"nav": col})
            compare_frames(c, m, pn[["book", "date", col]], ["book", "date"], num_cols=[col])
    run_check(C, "C-parent-nav", c_parent_nav)

    # ------------------------------------------------------------------ baskets
    def c_baskets(c):
        ev = E.get("baskets.csv", c)
        if ev is None:
            return
        ev = ev[ev["book"].isin(BK)].copy()
        ev["available_date"] = ev["available_date"].astype(str); ev["session_date"] = ev["session_date"].astype(str)
        compare_frames(c, D["baskets"][D["baskets"]["book"].isin(BK)], ev, ["book", "basket_no"], num_cols=["idx", "n_held", "raw_weight_sum"],
                       str_cols=["available_date", "session_date", "role"], tol=1e-9)
    run_check(C, "C-baskets", c_baskets)

    # ------------------------------------------------------------------ trades and positions
    def prep_tr(df, run):
        t = df[df["run"] == run].copy()
        t["cost_bps"] = r4(t["cost_bps"])
        t["seq"] = t.groupby(["book", "cost_bps"]).cumcount()
        return t

    def c_trades(c):
        """Every trade of every run (strategy, strategy_fixed50, hold_parent, both constant mixes, sleeve_only_timed): exits, entries, sleeve rebalances,
        basket changes, mix rebalances."""
        tr = E.get("trades.csv", c)
        if tr is None:
            return
        tr = tr[tr["book"].isin(BK)]
        keys = ["book", "cost_bps", "seq"]
        for run in RUN_KINDS:
            mt = prep_tr(D["trades"], run)
            et = prep_tr(tr, run)
            if not len(mt) and not len(et):
                continue
            et["date"] = et["date"].astype(str)
            et["basket_eff"] = et["basket_eff"].astype(str)
            num = ["idx", "e_after", "V", "traded", "cost", "nav_close_after"]
            compare_frames(c, mt, et, keys, num_cols=num, str_cols=["date", "kind", "basket_eff"])
            if run in ("strategy", "strategy_fixed50", "sleeve_only_timed"):
                if "gw_after" not in et.columns:
                    c.miss("trades.csv column gw_after")
                else:       # gw_after is compared on the trades that leave the book OUT (what an IN trade carries is not defined)
                    compare_frames(c, mt[mt["e_after"] == 0][keys + ["gw_after"]], et[et["e_after"] == 0][keys + ["gw_after"]], keys, num_cols=["gw_after"], tol=0.0)
            compare_frames(c, mt.groupby(["book", "cost_bps"]).size().rename("n").reset_index(),
                           et.groupby(["book", "cost_bps"]).size().rename("n").reset_index(), ["book", "cost_bps"], num_cols=["n"], tol=0.0)
        extra = set(tr["run"].unique()) - set(RUN_KINDS)
        c.notes.append(f"runs in trades.csv the verifier does not know: {sorted(extra)}")
    run_check(C, "C-trades", c_trades)

    decd = {(r.book, r.j): r.decision_date for r in dec_m[dec_m["window"] == "full"].itertuples()}
    decg = {(r.book, r.j): r.g for r in dec_m[dec_m["window"] == "full"].itertuples()}

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
        st = st[st["book"].isin(BK)].copy()
        st["cost_bps"] = r4(st["cost_bps"])
        st["seq"] = st.groupby(["book", "cost_bps"]).cumcount()
        st["date"] = st["date"].astype(str)
        st["decision_date"] = st["decision_date"].astype(str)
        for col in ("g_before", "g_after"):
            st[col] = [norm_g(x) for x in st[col]]
        st["gold_fill_raw"] = [int(norm_bool(x)) for x in st["gold_fill_raw"]]
        mine = my_sleeve_rows()
        keys = ["book", "cost_bps", "seq"]
        cols = ["g_after", "gw_after", "gold_value_after", "cash_value_after", "traded", "cost", "gold_fill_raw"]
        compare_frames(c, mine[keys + ["date", "kind", "decision_date"] + cols], st[keys + ["date", "kind", "decision_date"] + cols], keys, num_cols=cols,
                       str_cols=["date", "kind", "decision_date"])
        bcols = ["g_before", "gw_before", "gold_value_before", "cash_value_before"]
        compare_frames(c, mine[mine["kind"] == "sleeve_rebalance"][keys + bcols], st[st["kind"] == "sleeve_rebalance"][keys + bcols], keys, num_cols=bcols)
        tr = E.get("trades.csv", c)
        if tr is not None:
            tr = tr[tr["book"].isin(BK)]
            a = mine[mine["kind"] == "sleeve_rebalance"].groupby(["book", "cost_bps"]).size().rename("n").reset_index()
            t2 = tr[(tr["run"] == "strategy") & (tr["kind"] == "sleeve_rebalance")].copy(); t2["cost_bps"] = r4(t2["cost_bps"])
            b = st[st["kind"] == "sleeve_rebalance"].groupby(["book", "cost_bps"]).size().rename("n").reset_index()
            compare_frames(c, b, t2.groupby(["book", "cost_bps"]).size().rename("n").reset_index(), ["book", "cost_bps"], num_cols=["n"], tol=0.0)
            compare_frames(c, a, b, ["book", "cost_bps"], num_cols=["n"], tol=0.0)
        c.notes.append(f"{len(mine)} exits and sleeve rebalances of the verifier's strategy (all costs)")
    run_check(C, "C-sleeve", c_sleeve)

    def c_sleeve_identity(c):
        """V6 on the engine's own sleeve numbers: cost = traded x bps/2/1e4, value conservation, the post-trade split equals gw_after of the value after cost,
        a sleeve rebalance needs a change of g, an exit holds nothing in the sleeve before, the raw-fill flag follows the MCX range, 0-cost continuity."""
        st = E.get("sleeve_trades.csv", c)
        if st is None:
            return
        st = st[st["book"].isin(BK)]
        raw = D["MK"]["raw"]
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
            di = date_idx.get(str(r.date))
            if di is None or bool(norm_bool(r.gold_fill_raw)) != bool(raw[di]):
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
            else:
                c.compared += 1
                if abs(float(r.gold_value_before)) > 1e-12 or abs(float(r.cash_value_before)) > 1e-12:
                    c.failed += 1; c.fail(f"an exit with a non-empty sleeve before it: {r}")
        mine = my_sleeve_rows()
        n_mine = int((mine["kind"] == "sleeve_rebalance").sum())
        n_ev = int((st["kind"] == "sleeve_rebalance").sum())
        c.compared += 1
        if n_mine != n_ev:
            c.failed += 1; c.fail(f"sleeve rebalances: verifier {n_mine}, engine {n_ev}")
    run_check(C, "C-sleeve-identity", c_sleeve_identity)

    def c_positions(c):
        ps = E.get("positions.csv", c)
        if ps is None:
            return
        ev = ps[(ps["units"] != 0) & ps["book"].isin(BK)].copy(); ev["cost_bps"] = r4(ev["cost_bps"]); ev["date"] = ev["date"].astype(str)
        ev = ev[ev["run"] == "strategy"]
        mine = D["positions"].copy(); mine["cost_bps"] = r4(mine["cost_bps"])
        mine = mine[mine["units"] != 0]
        compare_frames(c, mine, ev[["book", "cost_bps", "run", "date", "instrument", "units"]], ["book", "cost_bps", "run", "date", "instrument"], num_cols=["units"])
    run_check(C, "C-positions", c_positions)

    def c_v6_targets(c):
        """V6 at every exit, entry, basket change and sleeve rebalance of the strategy (all costs): the evidence's post-trade units, valued at the
        fills, equal the targets (stock_i = e x w_i x (V - cost), GOLDBEES = (1 - e) gw (V - cost), cash = (1 - e)(1 - gw)(V - cost)) to 1e-12 of V; value
        after = V - cost (so at 0 cost the book's value is continuous through the trade); while IN the weights equal the basket in force (renormalised)."""
        ps = E.get("positions.csv", c)
        tr = E.get("trades.csv", c)
        if ps is None or tr is None:
            return
        ps = ps[ps["book"].isin(BK)]
        tr = tr[(tr["run"] == "strategy") & tr["book"].isin(BK)]
        pos = {}
        for (b, cs, d), g in ps[ps["run"] == "strategy"].groupby(["book", "cost_bps", "date"]):
            pos[(b, round(float(cs), 4), str(d))] = dict(zip(g["instrument"], g["units"].astype(float)))
        worst = 0.0
        for r in tr.itertuples():
            b, cs, d = r.book, round(float(r.cost_bps), 4), str(r.date)
            c.compared += 1
            u = pos.get((b, cs, d))
            if u is None:
                c.missing += 1; c.fail(f"MISSING: positions after the trade {b} {cs} {d}"); continue
            BKb = D["books"][b]
            V = BKb["V"]
            i = date_idx[d]
            bk = V["b_idx"][np.searchsorted(V["b_idx"], i, side="right") - 1]
            w = V["W"][V["basket_at"][bk]]
            Vv, cost_e, e = float(r.V), float(r.cost), float(r.e_after)
            vals = np.array([u.get(nm, 0.0) * (V["F"][i][k] if not np.isnan(V["F"][i][k]) else 0.0) for k, nm in enumerate(V["S"])])
            vg = u.get("GOLDBEES", 0.0) * V["gf"][i]
            vc = u.get("LBES", 0.0) * V["L"][i]
            unknown = [k for k in u if k not in set(V["S"]) | {"GOLDBEES", "LBES"}]
            if unknown:
                c.failed += 1; c.fail(f"positions after {b} {cs} {d} hold instruments outside the book: {unknown[:3]}"); continue
            aft = Vv - cost_e
            gw = float(r.gw_after)
            dev = max(float(np.max(np.abs(vals - e * w * aft))) if len(vals) else 0.0, abs(vg - (1 - e) * gw * aft), abs(vc - (1 - e) * (1 - gw) * aft),
                      abs(vals.sum() + vg + vc - aft)) / Vv
            worst = max(worst, dev)
            if dev > TOL_ID:
                c.failed += 1; c.fail(f"post-trade holdings differ from the targets by {dev:.2e} of V at {b} {cs} {d} {r.kind}")
            if e > 0 and vals.sum() > 0:                       # weights while IN equal the basket's, right after an entry and a basket change
                c.compared += 1
                dw = float(np.max(np.abs(vals / vals.sum() - w)))
                worst = max(worst, dw)
                if dw > TOL_ID:
                    c.failed += 1; c.fail(f"weights after {r.kind} {b} {cs} {d} differ from the basket's by {dw:.2e}")
            if cs == 0.0:
                c.compared += 1
                if abs(cost_e) > 0 or abs(aft - Vv) > TOL_ID * Vv:
                    c.failed += 1; c.fail(f"a 0-cost trade with a cost or a value jump: {b} {d}")
            c.compared += 1
            if abs(cost_e - float(r.traded) * cs / 2.0 / 10000.0) > TOL_ID * max(1.0, Vv):
                c.failed += 1; c.fail(f"cost != traded x bps/2/1e4 at {b} {cs} {d}")
        c.worst_rel = max(c.worst_rel, worst)
        c.notes.append("worst_rel = largest deviation (of V) of the evidence's post-trade values from the targets, and of the weights from the basket's")
    run_check(C, "C-v6-targets", c_v6_targets)

    # ------------------------------------------------------------------ V4(a), (b), (f): regression on the D17 calendar, one-instrument identity, seam
    def c_reg_t08(c):
        """V4(a), T08: the verifier's runs on D17's dates (each book's first date to 2019-12-31) against T08's stored daily_nav.csv (strategy, strategy_fixed50,
        hold_parent, sleeve_only, sleeve_only_timed, constant mixes at T08's f), 3 costs, relative 1e-12."""
        p8 = T08_EVIDENCE / "daily_nav.csv"
        if not p8.exists():
            c.miss("tests/T08/evidence/headline/daily_nav.csv"); return
        n8 = pd.read_csv(p8)
        n8 = n8[n8["run"].isin(RUN_KINDS) & (n8["date"] <= str(END_D17.date()))].copy()
        n8["cost_bps"] = r4(n8["cost_bps"])
        mine = REG["t08"].copy(); mine["cost_bps"] = r4(mine["cost_bps"])
        compare_frames(c, mine, n8, ["book", "date", "cost_bps", "run"], num_cols=["nav"], tol=TOL_REG)
        c.notes.append(f"{len(n8)} stored rows of tests/T08/evidence/headline/daily_nav.csv to 2019-12-31; relative tolerance {TOL_REG}")
    run_check(C, "C-regress-t08", c_reg_t08)

    def c_reg_t06(c):
        p6 = T06_EVIDENCE / "daily_nav.csv"
        if not p6.exists():
            c.miss("tests/T06/evidence/headline/daily_nav.csv"); return
        n6 = pd.read_csv(p6)
        n6 = n6[n6["run"].isin(["strategy", "hold_parent", "sleeve_only", "constant_mix"]) & (n6["date"] <= str(END_D17.date()))].copy()
        n6["cost_bps"] = r4(n6["cost_bps"])
        mine = REG["t06"].copy(); mine["cost_bps"] = r4(mine["cost_bps"])
        compare_frames(c, mine, n6, ["book", "date", "cost_bps", "run"], num_cols=["nav"], tol=TOL_REG)
        c.notes.append(f"{len(n6)} stored rows of tests/T06/evidence/headline/daily_nav.csv to 2019-12-31 (T06 'strategy' = the 50/50 sleeve); relative tolerance {TOL_REG}")
    run_check(C, "C-regress-t06", c_reg_t06)

    def c_reg_dec(c):
        """The decisions of 2019 on D17's calendar equal T08's and T06's stored decisions (states, signs, labels, g) on every shared decision date."""
        for tag, path, extra in (("t08", T08_EVIDENCE / "decisions.csv", ["sign_MAUc1", "label_MAUc1", "g", "gw"]), ("t06", T06_EVIDENCE / "decisions.csv", [])):
            if not path.exists():
                c.miss(str(path)); continue
            st = pd.read_csv(path)
            for p in BOOKS:
                a = REG["t08_dec"][p]
                a = a[a["decision_date"] < "2019-12-30"]
                b = st[(st["book"] == p) & (st["decision_date"] < "2019-12-30")]
                cols = ["decision_date", "decision_idx", "state", "sign_Nifty100", "sign_MC100", "sign_SC100", "label_Nifty100", "label_MC100", "label_SC100"] + extra
                a = a[["j"] + cols].copy(); b = b[["j"] + cols].copy()
                compare_frames(c, a, b, ["j"], num_cols=["decision_idx", "state"] + [x for x in extra if x in ("g", "gw")],
                               str_cols=[x for x in cols if x not in ("decision_idx", "state", "g", "gw")], tol=0.0)
    run_check(C, "C-regress-decisions", c_reg_dec)

    def c_one_instrument(c):
        """V4(b): the engine-independent simulator on a one-instrument book at weight 1, 0 cost, always in, reproduces close / first close (1e-12) for every
        stock of each book's T0 basket."""
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

    def c_seam(c):
        """V4(f): hold-the-parent 0-cost NAV on 2019-01-02 (0007: 2019-01-04) to 2019-12-31 against D17's published NAV, calendar-year gap within +-0.5 pp."""
        reg = E.get("regression.json")
        for r in REG["seam"]:
            c.compared += 1
            c.worst_rel = max(c.worst_rel, abs(r["year_gap_pp"]))
            if abs(r["year_gap_pp"]) > r["limit_pp"]:
                c.failed += 1; c.fail(f"seam gap {r['year_gap_pp']:+.4f} pp for {r['book']} exceeds the G0 limit {r['limit_pp']}")
            if reg is not None and r["book"] in reg.get("f_seam", {}):
                c.compared += 1
                e = reg["f_seam"][r["book"]]
                if abs(float(e["year_gap_pp"]) - r["year_gap_pp"]) > 1e-6:
                    c.failed += 1; c.fail(f"seam gap of {r['book']}: engine {e['year_gap_pp']!r} vs verifier {r['year_gap_pp']!r} pp")
        if reg is None:
            E.get("regression.json", c)
        c.notes.append("worst_rel in this check is the largest absolute seam gap in pp (limit 0.5); " + "; ".join(f"{r['book']} {r['year_gap_pp']:+.4f}" for r in REG["seam"]))
    run_check(C, "C-seam", c_seam)

    return C, dict(date_idx=date_idx, est_all=est_all, env_all=env_all, mst=mst, mnv=mnv)


# ----------------------------------------------------------------------------------------
# the checks (part 2: the nulls' draws, the counts, the samplers, percentiles, the engine's own gate files)
# ----------------------------------------------------------------------------------------
def compare_part2(D, E, BK, C, ctx):
    nd_draws = N_DRAWS
    RULE = D["rule"]
    WINDOWS = ["full", "r3"]
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
        """Structure of EVERY saved draw (V3): in-or-out arrays (weeks, first state, spell counts, invested weeks identical; N4.9 sorted lengths identical;
        N4.10 lengths within the computed bounds and summing to the totals) and gold arrays (weeks, first gold state, spell counts, BUY weeks identical;
        N4.9-g sorted lengths identical; N4.10-g lengths within their bounds and summing to the totals); the four books' arrays identical."""
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
        for window in WINDOWS:           # the four books share their draws
            for dom, typs in (("io", TYPES_IO), ("gold", TYPES_GOLD)):
                for typ in typs:
                    ref = states_of(BK[0], window, dom, typ)
                    for p in BK[1:]:
                        a = states_of(p, window, dom, typ)
                        if a is None or ref is None:
                            continue
                        c_struct.compared += 1
                        if not np.array_equal(a, ref):
                            c_struct.failed += 1; c_struct.fail(f"draw states of {p}|{window}|{dom}|{typ} differ from {BK[0]}'s (the four books share their draws)")

    cs = {n: Check(n) for n in ["C-states-struct", "C-states-lengths", "C-gold-states"]}
    C.update(cs)
    try:
        c_states(cs["C-states-struct"], cs["C-states-lengths"], cs["C-gold-states"])
    except Exception as ex:
        cs["C-states-struct"].failed += 1
        cs["C-states-struct"].fail(f"verifier exception in C-states: {ex!r} | {traceback.format_exc(limit=3).strip().splitlines()[-1]}")

    def c_rows(c_csv, c_sess, c_sig):
        """Every draws.csv row against the saved states: family tags, invested weeks, spell counts and lengths, sessions invested, gold BUY weeks and spells,
        sleeve trades."""
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
                if mode == "fixed50" and col == "gold_null":
                    want = "real"                    # the gold state does not enter a fixed-50 draw (contract)
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
            if mode == "fixed50":     # the gold columns of a fixed-50 draw describe the real gold series (the gold state does not enter)
                gr = feat(p, w, "gold", "real")
                pairs = [x for x in pairs if not x[0].startswith("g_") and x[0] not in ("n_buy_spells", "n_sell_spells")] + [
                    ("g_buy_weeks", np.full(len(ids), gr.w1[0]), False), ("n_buy_spells", np.full(len(ids), gr.n1[0]), False),
                    ("n_sell_spells", np.full(len(ids), gr.n0[0]), False)]
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

    def regen(kind, window, dom, n):
        key = (kind, window, dom, n)
        if key not in REGEN:
            R = RULE[BK[0]][window]
            if kind == "n49":
                s, sb = (R["states"], SEEDS["n49"]) if dom == "io" else (R["gstates"], SEEDS["n49g"])
                REGEN[key] = np.array([n49_states(s, sb, i) for i in range(n)])
            else:
                if dom == "io":
                    b = R["bounds"]
                    par1, par0, fs, sb = (R["in_spells"], R["S_in"], b["lo_in"], b["hi_in"]), (R["out_spells"], R["S_out"], b["lo_out"], b["hi_out"]), R["first_state"], SEEDS["n410"]
                else:
                    G, b = R["g"], R["g_bounds"]
                    par1, par0, fs, sb = (G["in_spells"], G["S_in"], b["lo_buy"], b["hi_buy"]), (G["out_spells"], G["S_out"], b["lo_sell"], b["hi_sell"]), G["first_state"], SEEDS["n410g"]
                tabs = {par1: ways_table(*par1), par0: ways_table(*par0)}
                REGEN[key] = np.array([n410_states_own(fs, par1, par0, sb, i, tabs) for i in range(n)])
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
    def view_of(bk, w, ca):
        if w == "full":
            return (bk["V"] if ca == "lbes" else bk["Vliq"]), bk["dec_idx"]
        return bk["Vr3"], bk["dec_idx_r3"]

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
                    continue
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
            bk = D["books"][p]
            V, dI = view_of(bk, w, ca)
            for i in [x for x in sample_ids(p, (w, ca, fam, mode), pool=nd_draws) if x < navail]:
                s_i = (fi.arr[i] if io_t != "real" else fi.arr[0]).astype(int)
                g_i = (fg.arr[i] if go_t != "real" else fg.arr[0]).astype(int)
                r = SIMS.run(V, s_i, cst, dI, gws_of(g_i, mode), (p, w, ca))
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
        c.notes.append(f"{nsim} draws re-simulated (first 20 and 20 random per book and row group); {curve_chk[1]} draw curves compared at 20.8 bps; "
                       f"worst relative difference {curve_chk[0]:.2e} (float32 tolerance {TOL_CURVE})")
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
                    want_full = dict(io=dict(**{"in": [R0["full"]["bounds"]["lo_in"], R0["full"]["bounds"]["hi_in"]], "out": [R0["full"]["bounds"]["lo_out"], R0["full"]["bounds"]["hi_out"]]}),
                                     gold=dict(buy=[R0["full"]["g_bounds"]["lo_buy"], R0["full"]["g_bounds"]["hi_buy"]], sell=[R0["full"]["g_bounds"]["lo_sell"], R0["full"]["g_bounds"]["hi_sell"]]))
                    want_r3 = {"in": [R0["r3"]["bounds"]["lo_in"], R0["r3"]["bounds"]["hi_in"]], "out": [R0["r3"]["bounds"]["lo_out"], R0["r3"]["bounds"]["hi_out"]],
                               "buy": [R0["r3"]["g_bounds"]["lo_buy"], R0["r3"]["g_bounds"]["hi_buy"]], "sell": [R0["r3"]["g_bounds"]["lo_sell"], R0["r3"]["g_bounds"]["hi_sell"]]}
                    got_r3 = b["r3"]
                    if "io" in got_r3:       # nested layout (io/gold) or flat layout, whichever the engine wrote
                        got_r3 = {**got_r3["io"], **got_r3["gold"]}
                    ok = b["full"] == want_full and {k: list(v) for k, v in got_r3.items()} == want_r3
                except Exception:
                    ok = False
                if not ok:
                    c.failed += 1; c.fail(f"count_table.json bounds {b} vs the verifier's computed bounds")
        for r in mine:           # V5(b): inclusion-exclusion against a plain DP, for every table
            c.compared += 1
            dp = ways_table(r["k"], r["S"], r["lo"], r["hi"])[r["k"]][r["S"]]
            if dp != r["n_ways"]:
                c.failed += 1; c.fail(f"{r['book']}|{r['window']}|{r['series']}|{r['state']}: inclusion-exclusion {r['n_ways']} vs DP {dp}")
        c.compared += 1
        if n_ways(3, 12, 2, 6) != 19:
            c.failed += 1; c.fail(f"inclusion-exclusion gives {n_ways(3, 12, 2, 6)} for k=3,S=12,[2,6]; T11.md says 19")
        c.notes.append("tuple counts compared with T11.md section 3 step 11 in C-frozen-counts: in 4,024,559,144, out 19,406,343,528, BUY 6,835,192,844,305, SELL 4,976,743,356 (full); "
                       "r3 7,654,290, 659,773,128, 426,468,399,525, 644,288,463")
        if STEP1 is not None:
            for p in BK:
                for window in WINDOWS:
                    e = STEP1[window]
                    for tabname, series, tabd in (("io_tables", "io", ("in", "out")), ("gold_tables", "gold", ("buy", "sell"))):
                        for sname, key in zip(tabd, ("in", "out")):
                            m = [r for r in mine if r["book"] == p and r["window"] == window and r["series"] == series and r["state"] == sname]
                            if not m:
                                continue
                            f = e[tabname][key]
                            c.compared += 1
                            if str(m[0]["n_ways"]) != str(f["n_ways"]) or m[0]["k"] != f["k"] or m[0]["S"] != f["S"] or m[0]["hi"] != f["hi"] or m[0]["lo"] != f["lo"]:
                                c.failed += 1; c.fail(f"step_1_spell_counts.json {p}|{window}|{series}|{sname} {f} differs from the verifier's count {m[0]}")
    run_check(C, "C-count", c_count)

    def c_support(c):
        """The rule's own lengths lie within the bounds (so every N4.9 / N4.9-g draw is an allowed N4.10 / N4.10-g configuration), the tables are feasible
        (lo*k <= S <= hi*k), the seeds' first element is 14, and the reportability gate holds (>= 4 round trips; >= 4 gold spells with an OUT week)."""
        c.compared += 1
        if not all(s[0] == 14 for s in SEEDS.values()) or SEEDS != dict(n49=[14, 3], n410=[14, 6], n49g=[14, 11, 3], n410g=[14, 11, 6]):
            c.failed += 1; c.fail(f"seeds {SEEDS} are not T11.md's")
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
                c.compared += 2
                if min(R["in_spells"], R["out_spells"]) < 4:
                    c.failed += 1; c.fail(f"{p}|{window}: fewer than 4 round trips of the in-or-out switch")
                if R["g_spells_with_an_out_week"] < 4:
                    c.failed += 1; c.fail(f"{p}|{window}: fewer than 4 gold spells containing an OUT week")
    run_check(C, "C-support", c_support)

    def c_sampler(c):
        """V5: (a) the verifier's own sampler passes the chi-square on the 19-tuple case; (b) the DP equals the formula (C-count); (c) over the saved N4.10 /
        N4.10-g draws the mean length at every position is within 4 standard errors of S / k (the exact mean of an exchangeable uniform tuple)."""
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
            c.notes.append("analysis.log not found beside the evidence (written by Step 4, not required here); nothing compared")
            return
        txt = logp.read_text(encoding="utf-8", errors="replace")
        nums = set(re.findall(r"\d+\.\d+", txt))
        for r in D["percentiles"]:
            if r["window"] == "full" and r["cash"] == "lbes" and abs(r["cost_bps"] - HEADLINE_COST) < 1e-9 and r["family"] in ("F1", "F2", "F3", "F4"):
                for stat in ("cagr", "max_dd"):
                    v = r.get(f"{stat}_pctile")
                    if v is None:
                        continue
                    c.compared += 1
                    if not any(f"{v:.{nd}f}" in nums for nd in (1, 2)):
                        c.failed += 1; c.fail(f"{r['book']} {r['family']} {r['mode']} {stat} percentile {v:.2f} not printed in {logp.name}")
        c.notes.append(f"read {logp}")
    run_check(C, "C-percentile-log", c_percentile_log, gate=False)

    # ------------------------------------------------------------------ the engine's own gate files (read, not trusted: V2-V6 flags must not be False)
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
            c.notes.append("V4(c) (AST comparison of the engine with t08_engine.py) is the engine's own gate: the verifier may not open the engines; its recorded result is read here")
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
                m = D["meta"][p]; R = RULE[p]["full"]
                pairs = [("t0", m["t0"]), ("sessions", m["sessions"]), ("decisions", m["decisions"]), ("invested_weeks", m["invested_weeks"]),
                         ("in_spells", m["in_spells"]), ("out_spells", m["out_spells"]), ("round_trips", min(m["in_spells"], m["out_spells"])),
                         ("sessions_invested_rule", R["sessions_invested"]), ("last_session", str(END.date())), ("first_state", R["first_state"]),
                         ("in_lengths", R["in_lengths"]), ("out_lengths", R["out_lengths"])]
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
        """R7 tables: r7_flagged_days.csv (the flagged stock-days of the verifier's rule) and r7_export.csv (held export-priced stock-sessions and the two end NAVs)."""
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
            if len(mine) and len(fl):
                mm = mine.merge(fl, on=["book", "date", "stock"], suffixes=("_v", "_e"))
                for a_, b_ in (("w_prev", "w_cur"),):
                    c.compared += len(mm)
                    raw_ok = (np.abs(mm["w_prev_v"] - mm["w_prev_e"]) < 1e-9) & (np.abs(mm["w_cur_v"] - mm["w_cur_e"]) < 1e-9)
                    nrm_ok = (np.abs(mm["w_prev_n"] - mm["w_prev_e"]) < 1e-9) & (np.abs(mm["w_cur_n"] - mm["w_cur_e"]) < 1e-9)
                    bad = ~(raw_ok | nrm_ok)
                    c.failed += int(bad.sum())
                    if bad.any(): c.fail("flagged-day weights differ (neither the listed nor the renormalised weights)")
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


def compare_all(D, REG, E, BK):
    C, ctx = compare_part1(D, REG, E, BK)
    return compare_part2(D, E, BK, C, ctx)


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
# self-test: a corrupted copy must be detected, each corruption by its own check
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
    """Nine corruptions, each of a different file: 5 decisions flipped (decisions.csv); a NAV column x 1.001 (daily_nav.csv); one N4.10 in-or-out draw out
    of bounds (draw_states.npz and draws.csv); one N4.10-g gold draw out of bounds; 3 gold-signal weeks flipped (gold_signal.csv); one sleeve rebalance
    removed (sleeve_trades.csv); one basket trade removed (trades.csv); the Smallcap 100 usable_from lowered (inputs.csv); one F3 draw's end NAV x 1.001."""
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True)
    info = {}
    p0 = books[0]
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
        R = D["rule"][p0]["full"]
        key = f"{p0}|full|io|N4.10"
        if key in data and data[key].shape[0] > 5:
            arr = data[key].copy()
            new_row, ins, outs = _widen_first_spell(arr[5], int(arr[5][0]), R["bounds"]["hi_in"])
            if len(new_row) == arr.shape[1]:
                arr[5] = new_row
                data[key] = arr
                info["corrupted_n410_draw"] = dict(key=key, draw_id=5, in_lengths=ins, out_lengths=outs)
                if w is not None:
                    msk = (w["book"] == p0) & (w["window"] == "full") & (w["io_null"] == "N4.10") & (w["draw_id"] == "5")
                    w.loc[msk, "in_lengths"] = "|".join(map(str, ins))
        key = f"{p0}|full|gold|N4.10-g"
        if key in data and data[key].shape[0] > 7:
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
        msk = (w["book"] == p0) & (w["window"] == "full") & (w["cash"] == "lbes") & (w["family"] == "F3") & (w["sleeve_mode"] == "timed") \
              & (w["draw_id"] == "3") & (w["cost_bps"].astype(float) == HEADLINE_COST)
        if msk.any():
            w.loc[msk, "end_nav"] = (w.loc[msk, "end_nav"].astype(float) * 1.001).astype(str)
            info["scaled_draw_end_nav"] = f"{p0} F3 draw 3, 20.8 bps, end_nav x 1.001"
        w.to_csv(dst / "draws.csv", index=False)
    gpath = ev.path("gold_signal.csv")
    if gpath is not None:
        gs = pd.read_csv(gpath)
        rows = gs.index[(gs["book"] == p0)][[40, 150, 200]]
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
    tpath = ev.path("trades.csv")
    if tpath is not None:
        tr = pd.read_csv(tpath)
        cand = tr.index[(tr["run"] == "strategy") & (tr["kind"] == "basket_change") & (tr["book"] == p0) & (tr["cost_bps"].astype(float) == HEADLINE_COST)]
        if len(cand) > 2:
            tr = tr.drop(index=cand[2])
            tr.to_csv(dst / "trades.csv", index=False)
            info["removed_basket_trade"] = f"{p0}, 20.8 bps, 3rd basket_change of the strategy"
    ipath = ev.path("inputs.csv")
    if ipath is not None:
        inp = pd.read_csv(ipath)
        msk = inp["file"].astype(str).str.replace("\\", "/", regex=False).str.contains("Master_SC100")
        if msk.any() and "usable_from" in inp.columns:
            inp["usable_from"] = inp["usable_from"].astype(object)
            inp.loc[msk, "usable_from"] = "2004-01-01"
            inp.to_csv(dst / "inputs.csv", index=False)
            info["lowered_usable_from"] = "Smallcap 100 Master row of inputs.csv set to 2004-01-01"
    return info


EVIDENCE_FILES = ["inputs.csv", "decisions.csv", "gold_signal.csv", "baskets.csv", "stats.csv", "draws.csv", "draw_states.npz", "real_states.npz",
                  "draw_curves_20.8.npz", "trades.csv", "sleeve_trades.csv", "positions.csv", "daily_nav.csv", "parent_nav_2014-09-01_2019-01-02.csv",
                  "parent_nav_2014-09-01_2019-01-02.md", "r7_flagged_days.csv", "r7_export.csv", "count_table.json", "sampler_selftest.json",
                  "regression.json", "audit.json"]
SELFTEST_WANTS = [("flipped_decision_rows", "C-dec", "decisions_flipped"), ("flipped_gold_weeks", "C-gold", "gold_signal_week_flipped"),
                  ("scaled_nav", "C-nav0", "nav_scaled"), ("corrupted_n410_draw", "C-states-lengths", "n410_draw_out_of_bounds"),
                  ("corrupted_n410g_draw", "C-gold-states", "n410g_draw_out_of_bounds"), ("removed_sleeve_trade", "C-sleeve", "sleeve_rebalance_removed"),
                  ("removed_basket_trade", "C-trades", "basket_trade_removed"), ("lowered_usable_from", "C-data", "sc100_usable_from_lowered"),
                  ("scaled_draw_end_nav", "C-draw-nav", "f3_draw_nav_scaled")]


def headline_table(D, books):
    """Print the six criteria of T11.md section 2 from the verifier's own percentiles (20.8 bps, LBES, full window), plus the companion nulls."""
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


def _jsonable_rule(rule):
    out = {}
    for p, rw in rule.items():
        out[p] = {}
        for w, R in rw.items():
            out[p][w] = {k: v for k, v in R.items() if not isinstance(v, np.ndarray)}
            out[p][w]["g"] = {k: v for k, v in R["g"].items()}
    return out


def main():
    global N_DRAWS
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="headline", help="evidence run name under tests/T11/evidence/ (headline, smoke)")
    ap.add_argument("--evidence", default=None, help="evidence directory (overrides --run)")
    ap.add_argument("--no-selftest", action="store_true", help="skip the in-process corrupted-copy test")
    ap.add_argument("--out", default=None)
    ap.add_argument("--draws", type=int, default=None, help="draws per row group the evidence must hold (2000 for headline, 20 for smoke)")
    ap.add_argument("--books", default=None, help="comma-separated books (default: those found in the evidence's decisions.csv)")
    ap.add_argument("--scratch", default=None, help="directory for the corrupted copy (default: a fresh temporary directory)")
    args = ap.parse_args()
    evdir = Path(args.evidence) if args.evidence else AA / "tests" / "T11" / "evidence" / args.run
    smoke = (args.run == "smoke") and not args.evidence
    N_DRAWS = int(args.draws) if args.draws else (20 if smoke else 2000)
    if args.books:
        books = [b.strip() for b in args.books.split(",")]
    else:
        dp = evdir / "decisions.csv"
        books = [b for b in BOOKS if dp.exists() and b in set(pd.read_csv(dp, usecols=["book"])["book"])] or list(BOOKS)
    out = Path(args.out) if args.out else evdir / "verify_t11.json"
    t = time.time()
    D = derive(books)
    print(f"[{time.time()-t:6.1f}s] derivation complete (books {books}, draws per group {N_DRAWS})", flush=True)
    REG = derive_regression(D)
    print(f"[{time.time()-t:6.1f}s] D17-calendar regression derived", flush=True)
    E = Evidence(evdir)
    C = compare_all(D, REG, E, books)
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
    print("\n=== V4(f) seam (hold-the-parent 0-cost NAV vs D17, 2019, pp; limit 0.5) ===")
    for r in REG["seam"]:
        print(f"{r['book']}: {r['first']} -> {r['last']}  {r['year_gap_pp']:+.4f} pp")

    pct_real, count_real = D["percentiles"], D["count_rows"]
    selftest = None
    if not args.no_selftest:
        scratch = Path(args.scratch) if args.scratch else Path(tempfile.mkdtemp(prefix="verify_t11_"))
        cdir = scratch / "corrupt_evidence_t11"
        info = corrupt_copy(E, cdir, D, books)
        Ec = Evidence(cdir, fallback=evdir)
        Cc = compare_all(D, REG, Ec, books)
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
    reads = {}
    for k, v in READS.items():
        try:
            sha = sha256_file(AA / k)
        except Exception:
            sha = None
        reads[k] = dict(v, sha256=sha)
    rep = dict(verifier="analysis/verify_t11.py", evidence=str(evdir), books=books, draws_expected=N_DRAWS, end=str(END.date()),
               gate_compared=int(gate_compared), gate_failures_and_missing=int(gate_fail), n_checks=len(C), n_gate_checks=sum(1 for c in C.values() if c.gate),
               missing_evidence_files=extra_missing, checks={k: v.to_dict() for k, v in C.items()}, meta=D["meta"], rule=_jsonable_rule(D["rule"]),
               count_rows=[{**r, "n_ways": str(r["n_ways"])} for r in D["count_rows"]], percentiles=D["percentiles"], criteria=crit,
               seam=REG["seam"], one_instrument={p: v for p, v in D["one_instrument"].items()},
               export_sessions={p: dict(total=D["r7"][p]["export_total"], by_stock=D["r7"][p]["export_by_stock"]) for p in books},
               r7_flagged_days={p: [{k: v for k, v in r.items() if not k.endswith("_n")} for r in D["r7"][p]["flagged"]] for p in books},
               approved_data_files_read=reads, selftest=selftest, exit_ok=bool(ok),
               closed_form="NAV_end = prod over segments of (trade-day jump x fixed-unit segment growth)")
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(rep, indent=1, default=str))
        print(f"wrote {out}")
    except Exception as ex:
        print(f"could not write {out}: {ex!r}")
    print(f"\nrows compared (gate checks): {gate_compared}; failures + missing: {gate_fail}; real run ok: {ok_real}; exit ok: {ok}")
    print(f"total time {time.time()-t:.1f} s")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
