"""T12 independent verifier (Step 3, gate V1 of tests/T12/T12.md section 2).

Re-derives T12's decisions, tags (its own rank lookup on the D23b panel), events, targets, NAVs, costs, trades, positions, null-draw
structure, null-draw NAVs, the R6 links, the R7 flagged days and spliced re-runs, the V7 oracle, the percentiles and the V4(a) regression
against T07's and T06's stored NAVs, from the RAW approved files only (plain numpy / pandas, its own loaders, tag lookup, simulator, subset
counting, sampler replay, oracle and percentile code), and compares them with the engine's evidence in tests/T12/evidence/<run>/.

It imports nothing from the engine (analysis/t12_engine.py), from analysis/t07_engine.py, t11_engine.py, tag_lookup.py, approved_data.py,
data/check_approved_data.py or any other module in analysis/ or data/, and its author never read their source. It is a fork of
analysis/verify_t07.py (T07's verifier, written the same way), with the D26 calendar, T0 and stand-in conventions of T11.md section 3 (read
in analysis/verify_t11.py, itself a verifier). The rules are those of tests/T12/logs/verifier_spec.md (a list of changes to
tests/T07/logs/verifier_spec.md) and T12.md sections 1-3 (frozen; T12.md wins). Readings of the frozen text: tests/T12/logs/step_3_log.md.

Usage (from AA/, as `python -I`):
    python -I analysis/verify_t12.py                                   # headline evidence + self-test on corrupted copies
    python -I analysis/verify_t12.py --evidence tests/T12/evidence/smoke --books SCMO_0003
    python -I analysis/verify_t12.py --evidence DIR --no-selftest --out FILE
    python -I analysis/verify_t12.py --regress-only                    # C-regress alone (needs no T12 evidence)

Exit code 0 only if rows were compared in every gate check, none failed, none were missing, and (in the default run) every deliberate
corruption of a copy of the evidence was detected by its own check. A missing evidence file is reported as MISSING (a failure).
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
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

AA = Path(__file__).resolve().parents[1]
BOOKS = ["SCMO_0003", "SCMO_0007", "SCMO_0010", "SCMO_0029"]
R6_BOOKS = ["SCMO_0007", "SCMO_0010"]
COSTS = [0.0, 20.8, 50.0]
HEADLINE_COST = 20.8
T0_FULL = pd.Timestamp("2014-09-01")            # T12.md section 3 step 1
END = pd.Timestamp("2019-01-02")
R2_START = pd.Timestamp("2015-01-02")           # R2: from the first D26 session on or after this date
END_D17 = pd.Timestamp("2019-12-31")            # V4(a) / C-regress slice
SC100_SIGNAL_FROM = pd.Timestamp("2011-11-25")  # standing rule 7 (D03 Smallcap 100 rows usable from)
N_DECISIONS_FULL = 228
TOL = 1e-9                                      # relative tolerance on NAVs and statistics
TOL_REGRESSION = 1e-12
TOL_CURVE = 1e-6                                # float32 draw curves (the spec's 1e-9 cannot be met by float32 storage)
R7_THRESHOLD = 0.20
BANDS = ["Large", "Mid", "Small and below"]
BAND_INDEX = {"Large": 0, "Mid": 1, "Small and below": 2}
INDEX_NAMES = ["Nifty100", "MC100", "SC100"]
SEED_PREFIX = 15                                # T12.md section 3 steps 11-12
# R6 (T12.md section 2): the two unranked holdings read by "the quote_id the D20b review identified". T12.md quotes 236783369047 (Hexaware)
# and 236798428431 (DHFL); those are the holdings' CURRENT quote_ids (2025 listings, already linked to their ISINs through D22, no panel row
# before 2025-02), so they give no rank in 2014-19. The review (data/review/2026-11-17_mcap_pre2018/REVIEW.md, the identity-gap table and
# its note "DHFL 55837400085 -> 236798428431; Hexaware 55837401060 -> 236783369047") identifies the in-window listings as the OLD
# quote_ids, both ranked Mid. Reading (step_3_log.md): 'review' (default) uses the old ids; 'frozen' uses the quoted ids (R6 then changes
# nothing). --r6-ids selects.
R6_LINKS_REVIEW = {"INE093A01041": 55837401060, "INE202B01038": 55837400085}
R6_LINKS_FROZEN = {"INE093A01041": 236783369047, "INE202B01038": 236798428431}
R6_LINKS = dict(R6_LINKS_REVIEW)
EXPECTED_UNRANKED = {"SCMO_0003": set(), "SCMO_0007": {"INE093A01041"}, "SCMO_0010": {"INE202B01038"}, "SCMO_0029": set()}
STANDIN_D18 = ["2017-10-19"]                    # T12.md section 3 step 1: a D26 session with no D18 bar for any stock
STANDIN_GOLD = ["2016-10-30"]                   # a D26 session with no GOLDBEES bar
SCRATCH = Path(r"C:\Users\manur\AppData\Local\Temp\claude\d384933f9ddb0ecb\25ca8e7b-9fb5-45af-a5f8-d3a7953e6ac8\scratchpad")
APPROVED_MD = AA / "data" / "APPROVED_DATA.md"
T06_EVIDENCE = AA / "tests" / "T06" / "evidence" / "headline"
T07_EVIDENCE = AA / "tests" / "T07" / "evidence" / "headline"
T11_HEADLINE = AA / "tests" / "T11" / "evidence" / "headline"
THROUGH_EXEMPT_IDS = {"D19", "D05"}             # verifier_spec C-data: D19 and D05 end earlier by design; D12 is not read
F_CAL = "Historical Data/extended_2026-11-12/index_daily_pre2019/nse_trading_days.csv"                          # D26
F_RANK = "Historical Data/extended_2026-11-17/mcap_universe_from_2013-12/mcap_rank_panel_from_2013-12.csv"       # D23b combined
F_MEMBER = "Historical Data/extended_2026-11-12/tags/membership_panel.csv"                                      # D23 (cutoff only)
F_SYMB = "Historical Data/extended_2026-11-12/symbology/symbology_changes.csv"                                  # D22
F_D20B = "Historical Data/extended_2026-11-17/mcap_universe_from_2013-12/mcap_universe_ordinary_2013-12_2017-12.csv"   # info only
F_D20 = "Historical Data/extended_2026-11-12/mcap_universe/mcap_universe_ordinary.csv"                          # info only
F_GDAILY = "Historical Data/extended_2026-11-12/MAUc1_from_2003/mauc1_daily_clean_extended.csv"                # D24b: MCX range only
F_D09 = "analysis/cache/why_gold_ohlc_eikon_extended_2026-11-04.parquet"
F_LBES = "Historical Data/LBES_Adjusted_Price_data_extended_2026-11-05.csv"
F_LIQ = "Historical Data/liquidEtfFinal_extended_2026-11-05.csv"
F_CORR = "data/holdings_matrix/price_corrections.csv"
READ_KW = dict(keep_default_na=False, na_values=[""])     # D20-D23: only the empty string is null
RETAG_SKIPPED_BASKET = True     # T12.md section 3 step 4(iii) (T07's reading): a basket arriving while nothing is held trades nothing; its tags become current
WINDOWS = ("full", "r2", "full_r6")
R2_INIT = "drift"               # r2's initial position: 'drift' (T07's live-window convention) or 'fresh' (bought at r2 T0's OHLC4); see --r2-init


def windows_of(p):
    return ("full", "r2", "full_r6") if p in R6_BOOKS else ("full", "r2")


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
        note = "|".join(parts[5:])
        m = re.search(r"\[usable-from:\s*(\d{4}-\d{2}-\d{2})\]", note)
        rows[norm_path(parts[2])] = dict(status=parts[0], id=parts[1], file=parts[2], through=parts[3], sha=parts[4].lower(), note=note,
                                         usable_from=m.group(1) if m else None)
    return rows


APPROVED = parse_approved()
READS = {}          # relative path -> dict(sha, gate_only)
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
    """Register a read of an AA-relative path; refuse anything that is not an APPROVED row. A restricted row ([usable-from: d], standing
    rule 7) needs the first date the read will use and refuses an earlier one. gate_only: read for the regression / information only."""
    key = norm_path(rel)
    row = APPROVED.get(key)
    if row is None:
        raise RuntimeError(f"file not in APPROVED_DATA.md: {rel}")
    if row["status"] != "APPROVED":
        raise RuntimeError(f"file is {row['status']} in APPROVED_DATA.md: {rel}")
    if row["usable_from"] is not None:
        if first_date is None or pd.Timestamp(first_date) < pd.Timestamp(row["usable_from"]):
            raise RuntimeError(f"{rel} is restricted (usable from {row['usable_from']}); first read date {first_date}")
    prev = READS.get(key)
    READS[key] = dict(sha=None, gate_only=bool(gate_only) and (prev is None or prev["gate_only"]))
    return AA / rel


# ----------------------------------------------------------------------------------------
# raw loaders
# ----------------------------------------------------------------------------------------
def load_calendar():
    d = pd.read_csv(rd(F_CAL))
    dates = pd.DatetimeIndex(pd.to_datetime(d["date"])).sort_values()
    assert dates.is_unique
    return dates


def load_published_nav(p):
    d = pd.read_csv(rd(f"Historical Data/extended_2026-11-06/published_nav/{p}.csv", gate_only=True))
    d["date"] = pd.to_datetime(d["_id.date"], format="%Y/%m/%d")
    return d.set_index("date")["index"].sort_index()


def load_masters():
    out = {}
    for name in INDEX_NAMES:
        first = SC100_SIGNAL_FROM if name == "SC100" else None
        m = pd.read_excel(rd(f"Historical Data/extended_2026-10-30/Master/Master_{name}.xlsx", first))
        m = m[["Date", "SIGN"]].copy()
        m["SIGN"] = m["SIGN"].astype("object")
        m = m[m["SIGN"].notna()]
        m["SIGN"] = m["SIGN"].astype(str).str.strip().str.upper()
        m = m[m["SIGN"] != ""]
        m["Date"] = pd.to_datetime(m["Date"])
        if first is not None:
            m = m[m["Date"] >= first]             # rows before the usable-from date are dropped at load and never used
        m = m.sort_values("Date").reset_index(drop=True)
        assert set(m["SIGN"]) <= {"BUY", "SELL"}, (name, set(m["SIGN"]))
        out[name] = (m["Date"].values, m["SIGN"].values)
    return out


def load_gold():
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
    """T12.md section 3 step 7: OHLC4 with the open, high and low clipped to the GOLDBEES close x (1 +- (MCX range / MCX close + 0.5%)),
    high and low re-bounded by the open and the close; the raw OHLC4 on a session with no MCX bar. Returns (fill, MCX range or NaN)."""
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
    assert series.index[-1] >= cal[-1], f"{name}: the file ends {series.index[-1].date()} before the last session {cal[-1].date()}"
    assert series.index[0] <= cal[0], f"{name}: the file starts after the first session"
    lv = series.reindex(cal, method="ffill").values.astype(float)
    assert not np.isnan(lv).any(), f"{name}: NaN level on a session"
    return lv


def load_corrections():
    c = pd.read_csv(rd(F_CORR))
    c["ex_date"] = pd.to_datetime(c["ex_date"])
    return c


_PRICES = {}


def load_book_prices(p, corr):
    """D18 bars of book p on D18's own dates, Polyplex correction applied: close forward-filled, and the fill price (OHLC4; the close if
    the bar lacks an open, high or low; the last close where the stock has no bar that day)."""
    if p in _PRICES:
        return _PRICES[p]
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
    fill = ohlc4.where(all4, W["close"])
    fill = fill.where(bar, close_ff)
    _PRICES[p] = dict(d18=d18, close_ff=close_ff, fill=fill)
    return _PRICES[p]


_BASKETS = {}


def load_baskets(p):
    """D19 listed weights per availableDate; skipped baskets (D05's `skipped` flag, cross-checked with D19's sources trace) dropped."""
    if p in _BASKETS:
        return _BASKETS[p]
    m = pd.read_csv(rd(f"data/holdings_matrix/{p}_holding_weight_matrix.csv"))
    m = m.rename(columns={m.columns[0]: "avail"})
    m["avail"] = pd.to_datetime(m["avail"])
    d5 = pd.read_csv(rd(f"Historical Data/frozen_2026-09-25/Rebalance_history/Rebalance_history_by_scid_{p}.csv"), usecols=["skipped", "availableDate"])
    d5["avail"] = pd.to_datetime(d5["availableDate"], format="%d/%m/%y %H:%M").dt.normalize()
    sk = d5.groupby("avail")["skipped"].apply(lambda s: bool(s.astype(str).str.strip().str.lower().eq("true").any()))
    skipped = set(sk[sk].index)
    s = pd.read_csv(rd(f"data/holdings_matrix/{p}_holding_weight_sources.csv"))
    s["rebalance_date"] = pd.to_datetime(s["rebalance_date"])
    src_skipped = set(s.loc[s["source"] == "csv_only_skipped", "rebalance_date"])
    m = m[~m["avail"].isin(skipped | src_skipped)].sort_values("avail").reset_index(drop=True)
    cols = [c for c in m.columns if c != "avail"]
    Wraw = m[cols].fillna(0.0).values.astype(float)
    cm = pd.read_csv(rd(f"data/holdings_matrix/{p}_columns.csv"))
    isin_of = dict(zip(cm["stock"], cm["ISIN"]))
    _BASKETS[p] = dict(avail=m["avail"].values, cols=cols, Wraw=Wraw, isin_of=isin_of, skipped_d05=sorted(str(x.date()) for x in skipped),
                       skipped_src=sorted(str(x.date()) for x in src_skipped))
    return _BASKETS[p]


# ----------------------------------------------------------------------------------------
# the tag rule: own rank lookup on the D23b combined panel (T12.md section 3 "The tag rule")
# ----------------------------------------------------------------------------------------
def rank_band(r):
    return "Large" if r <= 100 else ("Mid" if r <= 250 else "Small and below")


class RankTags:
    """Every date this verifier tags is before the membership cutoff (the first D23 membership snapshot, 2026-04-09; asserted), so every tag
    is a rank tag: the band of the stock's rank on the latest D23b snapshot on or before the date (1-100 Large, 101-250 Mid, above 250 Small
    and below). The stock is found by its ISIN, else through any other ISIN sharing its quote_id (D22 isin / new_isin and the panel's own
    isin-quote_id pairs), else by the quote_id itself; the exact ISIN is preferred, then the lowest rank. Not found = 'Small and below',
    source 'unranked'. r6=True: an R6 holding that would read unranked is read by the rank of its linked quote_id (source 'rank_linked',
    via 'r6_link'). No snapshot dated after the date is ever used."""

    def __init__(self):
        pn = pd.read_csv(rd(F_RANK), usecols=["date", "quote_id", "isin", "rank", "n_ranked", "band"], **READ_KW)
        pn["date"] = pd.to_datetime(pn["date"])
        self.panel = pn
        self.dates = np.array(sorted(pn["date"].unique()), dtype="datetime64[ns]")
        self.pos = {np.datetime64(k, "ns"): v for k, v in pn.groupby("date").indices.items()}
        self.q = pn["quote_id"].values.astype(np.int64)
        self.isin = pn["isin"].astype(object).where(pn["isin"].notna(), None).values
        self.rank = pn["rank"].values.astype(np.int64)
        self.nr = pn["n_ranked"].values.astype(np.int64)
        self.band_col = pn["band"].values
        mp = pd.read_csv(rd(F_MEMBER), usecols=["snapshot_date"], **READ_KW)
        self.cutoff = pd.Timestamp(pd.to_datetime(mp["snapshot_date"]).min())
        d22 = pd.read_csv(rd(F_SYMB), usecols=["quote_id", "isin", "new_isin"], **READ_KW)
        self.q_of_isin = defaultdict(set)
        self.isins_of_q = defaultdict(set)
        for qq, a, b in zip(d22["quote_id"].values, d22["isin"].values, d22["new_isin"].values):
            for x in (a, b):
                if isinstance(x, str):
                    self.q_of_isin[x].add(int(qq)); self.isins_of_q[int(qq)].add(x)
        pairs = pd.DataFrame({"q": self.q, "i": self.isin}).dropna().drop_duplicates()
        for qq, x in zip(pairs["q"].values, pairs["i"].values):
            self.q_of_isin[x].add(int(qq)); self.isins_of_q[int(qq)].add(x)
        self._grp = {}
        self._snap = {}

    def group(self, isin):
        if isin not in self._grp:
            qs = set(self.q_of_isin.get(isin, set()))
            gi = {isin}
            for qq in qs:
                gi |= self.isins_of_q[qq]
            self._grp[isin] = (gi, qs)
        return self._grp[isin]

    def snapshot(self, t):
        """(isin -> (rank, n_ranked), quote_id -> (rank, n_ranked)) of snapshot t, lowest rank kept."""
        if t not in self._snap:
            by_i, by_q = {}, {}
            for k in self.pos[t]:
                r = (int(self.rank[k]), int(self.nr[k]))
                i = self.isin[k]
                if i is not None and (i not in by_i or r[0] < by_i[i][0]):
                    by_i[i] = r
                qq = int(self.q[k])
                if qq not in by_q or r[0] < by_q[qq][0]:
                    by_q[qq] = r
            self._snap[t] = (by_i, by_q)
        return self._snap[t]

    def snap_date(self, asof):
        i = np.searchsorted(self.dates, np.datetime64(pd.Timestamp(asof), "ns"), side="right") - 1
        return None if i < 0 else self.dates[i]

    def tag(self, isin, asof, r6=False):
        asof = pd.Timestamp(asof)
        assert asof < self.cutoff, f"tag date {asof.date()} is on or after the membership cutoff {self.cutoff.date()}"
        t = self.snap_date(asof)
        if t is not None:
            by_i, by_q = self.snapshot(t)
            snap = str(pd.Timestamp(t).date())
            if isin in by_i:
                r = by_i[isin]
                return dict(band=rank_band(r[0]), source="rank", snapshot=snap, detail=r[0], n_ranked=r[1], via="isin")
            gi, qs = self.group(isin)
            cand = [by_i[x] for x in gi if x in by_i] + [by_q[qq] for qq in qs if qq in by_q]
            if cand:
                r = min(cand)
                return dict(band=rank_band(r[0]), source="rank", snapshot=snap, detail=r[0], n_ranked=r[1], via="quote_id")
            if r6 and isin in R6_LINKS and R6_LINKS[isin] in by_q:
                r = by_q[R6_LINKS[isin]]
                return dict(band=rank_band(r[0]), source="rank_linked", snapshot=snap, detail=r[0], n_ranked=r[1], via="r6_link",
                            linked_quote_id=R6_LINKS[isin])
        return dict(band="Small and below", source="unranked", snapshot="", detail=None, n_ranked=None, via="")


class TagView:
    """A RankTags in plain or R6 mode (the object derive_events calls)."""

    def __init__(self, base, r6=False):
        self.base, self.r6 = base, r6

    def tag(self, isin, asof):
        return self.base.tag(isin, asof, r6=self.r6)


# ----------------------------------------------------------------------------------------
# market arrays, book construction and windows (T12.md section 3 steps 1, 4(i), 7)
# ----------------------------------------------------------------------------------------
def market_arrays(cal, gold, mcx, lbes, liq):
    fill_s, rng = despiked_goldbees_fill(gold, mcx)
    gc = gold["close"].reindex(cal, method="ffill").values.astype(float)
    gf = fill_s.reindex(cal).values.astype(float)
    own = np.array([d in gold.index for d in cal])
    gf = np.where(np.isnan(gf), gc, gf)                  # no GOLDBEES bar (2016-10-30): the previous close is valuation and fill
    raw = np.isnan(rng.reindex(cal).values.astype(float))
    return dict(gc=gc, gf=gf, own_gold_bar=own, raw=raw, L=asof_levels(cal, lbes, "LBES"), L2=asof_levels(cal, liq, "LIQUIDCASE"))


def build_book(p, cal, MK, corr):
    """Book p on calendar cal (T0 = cal[0]). Stock closes: the latest D18 close on or before each session (2017-10-19 has no D18 bar:
    the previous close stands in); fills: the D18 fill on a D18 date, else the previous close."""
    PR = load_book_prices(p, corr)
    BS = load_baskets(p)
    n = len(cal)
    avail = BS["avail"]
    eff = np.searchsorted(cal.values, avail, side="left")
    basket_at = {}
    for k in range(len(avail)):
        if eff[k] < n:
            basket_at[int(eff[k])] = k                 # a later availableDate with the same effect session overrides
    used = sorted(set(basket_at.values()))
    S_cols = [c for j, c in enumerate(BS["cols"]) if (BS["Wraw"][used, j] > 0).any()]
    ci = [BS["cols"].index(c) for c in S_cols]
    Wraw = BS["Wraw"][:, ci]
    miss = [c for c in S_cols if c not in PR["close_ff"].columns]
    assert not miss, (p, miss)
    C = PR["close_ff"][S_cols].reindex(cal, method="ffill").values
    on_d18 = np.array([d in PR["d18"] for d in cal])
    Fd = PR["fill"][S_cols].reindex(cal).values
    F = np.where(on_d18[:, None], Fd, C)
    isins = [BS["isin_of"][s] for s in S_cols]
    return dict(p=p, cal=cal, n=n, S=S_cols, isins=isins, C=C, Cn=np.nan_to_num(C, nan=0.0), F=F, gc=MK["gc"], gf=MK["gf"], L=MK["L"],
                L2=MK["L2"], raw=MK["raw"], own_gold_bar=MK["own_gold_bar"], Wraw=Wraw, basket_at_full=basket_at, avail=avail, d18=PR["d18"],
                fill_d18=PR["fill"][S_cols], on_d18=on_d18, skipped_d05=BS["skipped_d05"], skipped_src=BS["skipped_src"])


def make_view(B, a, b, cash="lbes", init="drift"):
    """Sessions [a, b) of book B; session a is the window's T0 (NAV 1.000 at its close). W = listed weights, Wn = rows renormalised.
    init 'drift': the T0 basket bought at the fills of its own first D18 session on or after its availableDate (T07's convention; for the
    full window that session IS T0); 'fresh': bought at T0's own fills."""
    full = B["basket_at_full"]
    rel = {k - a: v for k, v in full.items() if k < b}
    keys = sorted(rel)
    k_t0 = max(k for k in keys if k <= 0)
    k0 = rel[k_t0]
    if init == "fresh":
        init_fill = B["F"][a]
        first_d18 = B["cal"][a]
    else:
        first_d18 = B["d18"][np.searchsorted(B["d18"].values, B["avail"][k0], side="left")]
        init_fill = B["fill_d18"].loc[first_d18].values
    W = B["Wraw"]
    rs = W.sum(axis=1, keepdims=True)
    Wn = np.divide(W, rs, out=np.zeros_like(W), where=rs > 0)     # rows of baskets outside the window can be all zero here
    return dict(p=B["p"], cal=B["cal"][a:b], n=b - a, a=a, S=B["S"], isins=B["isins"], C=B["C"][a:b], Cn=B["Cn"][a:b], F=B["F"][a:b],
                gc=B["gc"][a:b], gf=B["gf"][a:b], L=(B["L"] if cash == "lbes" else B["L2"])[a:b], raw=B["raw"][a:b], W=W,
                Wn=Wn, avail=B["avail"], basket_at=rel, b_idx=keys,
                changes=[k for k in keys if 0 < k < b - a], k0=k0, init_fill=init_fill, first_d18=first_d18, init=init)


def basket_key(V, i):
    return V["b_idx"][np.searchsorted(V["b_idx"], i, side="right") - 1]


def decisions_for_window(V, window, masters):
    """T0, then the last session of each ISO week after T0; the latest Master row on or before the date for each index."""
    cal = V["cal"]
    n = len(cal)
    t0 = cal[0]
    iso = cal.isocalendar()
    key = iso["year"].astype(int).values * 100 + iso["week"].astype(int).values
    df = pd.DataFrame({"date": cal, "key": key, "idx": np.arange(n)})
    last = df.groupby("key").tail(1)
    last = last[last["date"] > t0]
    dec_idx = np.array(sorted(set([0] + last["idx"].values.tolist())))
    rows = []
    for j, ix in enumerate(dec_idx):
        d = cal[ix]
        signs, labels = [], []
        for nm in INDEX_NAMES:
            dates, sg = masters[nm]
            pos = int(np.searchsorted(dates, np.datetime64(d), side="right") - 1)
            assert pos >= 0, (nm, d)
            signs.append(sg[pos]); labels.append(pd.Timestamp(dates[pos]))
        latest = max(labels)
        buy = all(s == "BUY" for s in signs)
        sell = all(s == "SELL" for s in signs)
        trade = cal[ix + 1] if (ix + 1 < n and j < len(dec_idx) - 1) else None
        rows.append(dict(book=V["p"], window=window, j=j, decision_date=str(d.date()), decision_idx=int(ix),
                         trade_date=None if trade is None else str(trade.date()),
                         sign_Nifty100=signs[0], sign_MC100=signs[1], sign_SC100=signs[2],
                         label_Nifty100=str(labels[0].date()), label_MC100=str(labels[1].date()), label_SC100=str(labels[2].date()),
                         latest_label=str(latest.date()), label_age_days=int((d - latest).days),
                         all_three_buy=bool(buy), state=int(buy), disagree=bool(not buy and not sell),
                         pattern="".join(s[0] for s in signs)))
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------------------------
# events (T12.md section 3 steps 4-6)
# ----------------------------------------------------------------------------------------
def derive_events(V, dec, tagger, mode="rule"):
    """mode: 'rule' (tags), 'tied' (whole-book switch: every stock follows IN iff all three BUY), 'allin', 'allout'.
    Returns (events, pit counters)."""
    n = V["n"]
    cal = V["cal"]
    didx = dec["decision_idx"].values
    D = len(dec)
    signs = np.stack([dec["sign_Nifty100"].values, dec["sign_MC100"].values, dec["sign_SC100"].values], axis=1)
    buy_all = dec["all_three_buy"].values.astype(bool)
    pit = dict(decisions_checked=0, decision_violations=0, sc100_rows_checked=0, sc100_violations=0, tags_checked=0, tag_violations=0,
               trades_checked=0, trade_violations=0, t0_exempt_tags=0)
    for j in range(D):
        pit["decisions_checked"] += 1
        for c in ("label_Nifty100", "label_MC100", "label_SC100"):
            if pd.Timestamp(dec[c].iloc[j]) > pd.Timestamp(dec["decision_date"].iloc[j]):
                pit["decision_violations"] += 1
        pit["sc100_rows_checked"] += 1
        if pd.Timestamp(dec["label_SC100"].iloc[j]) < SC100_SIGNAL_FROM:
            pit["sc100_violations"] += 1
    sig_session = {}
    for j in range(1, D - 1):
        if didx[j] + 1 < n:
            sig_session[int(didx[j]) + 1] = j
    S = len(V["S"])

    def on(j, band):
        if mode == "tied":
            return bool(buy_all[j])
        if mode == "allin":
            return True
        if mode == "allout":
            return False
        return signs[j, BAND_INDEX[band]] == "BUY"

    def build(i, kind, info_idx, jstate):
        k = V["basket_at"][basket_key(V, i)]
        w = V["W"][k]
        held = np.flatnonzero(w > 0)
        tags = []
        for si in held:
            if mode == "rule":
                tg = tagger.tag(V["isins"][si], cal[info_idx])
                pit["tags_checked"] += 1
                if tg["snapshot"] and pd.Timestamp(tg["snapshot"]) > cal[info_idx]:
                    pit["tag_violations"] += 1
            else:
                tg = dict(band="Large", source="n/a", snapshot="", detail=None, n_ranked=None, via="")
            tags.append(tg)
        kept = np.array([on(jstate, tg["band"]) for tg in tags], dtype=bool) if len(held) else np.zeros(0, dtype=bool)
        kfull = np.zeros(S, dtype=bool)
        kfull[held[kept]] = True
        return dict(idx=int(i), kind=kind, info_idx=int(info_idx), j=int(jstate), k=int(k), bkey=int(basket_key(V, i)), held=held, tags=tags,
                    kept=kept, kfull=kfull)

    def jstate_for(info_idx):
        return int(np.searchsorted(didx, info_idx, side="right") - 1)

    events = []
    e0 = build(0, "initial", 0, 0)
    events.append(e0)
    pit["t0_exempt_tags"] = len(e0["held"]) if mode == "rule" else 0
    cur_held, cur_bands, cur_dropped = e0["held"], [t["band"] for t in e0["tags"]], set(e0["held"][~e0["kept"]].tolist())
    cur_has_kept = bool(e0["kept"].any())
    if mode in ("allin", "allout"):
        sig_session = {}
    changes = set(V["changes"])
    for s in sorted(set(sig_session) | changes):
        sig = False
        if s in sig_session:
            j = sig_session[s]
            newdrop = set(int(si) for si, bd in zip(cur_held, cur_bands) if not on(j, bd))
            sig = newdrop != cur_dropped
        bsk = (s in changes) and cur_has_kept
        if RETAG_SKIPPED_BASKET and mode == "rule" and (s in changes) and not cur_has_kept and not sig:
            ev = build(s, "basket", s - 1, jstate_for(s - 1))          # tags re-read as of the session before, nothing traded
            cur_held, cur_bands = ev["held"], [t["band"] for t in ev["tags"]]
            cur_dropped = set(int(x) for x in ev["held"])
            continue
        if not (sig or bsk):
            continue
        kind = "signal+basket" if (sig and bsk) else ("signal" if sig else "basket")
        info_idx = s - 1
        ev = build(s, kind, info_idx, jstate_for(info_idx))
        pit["trades_checked"] += 1
        if not (didx[ev["j"]] <= info_idx < s):
            pit["trade_violations"] += 1
        events.append(ev)
        cur_held, cur_bands = ev["held"], [t["band"] for t in ev["tags"]]
        cur_dropped = set(ev["held"][~ev["kept"]].tolist())
        cur_has_kept = bool(ev["kept"].any())
    return events, pit


def event_numbers(V, ev):
    w = V["Wn"][ev["k"]][ev["held"]]
    kept = ev["kept"]
    bands = [BAND_INDEX[t["band"]] for t in ev["tags"]]
    Dw = float(w[~kept].sum())
    Sw = float(w.sum())
    nh = len(w)
    nd = int((~kept).sum())
    return dict(n_held=nh, n_large=bands.count(0), n_mid=bands.count(1), n_small=bands.count(2), n_dropped=nd, dropped_weight=Dw,
                sum_weights=Sw, sleeve_share_s=Dw / Sw if Sw > 0 else float("nan"), partial=bool(0 < nd < nh),
                tau=0.5 * float(w.min()) if nh else float("nan"))


# ----------------------------------------------------------------------------------------
# the simulation (T12.md section 3 steps 4(i), 6, 7, 8)
# ----------------------------------------------------------------------------------------
def simulate(V, evs, bps, mixf=None, positions=False, C_over=None, F_over=None):
    """evs[0] is the initial event (idx 0); the others are trade sessions. Listed weights renormalised per basket (T12.md step 6).
    mixf: the constant-mix comparator. C_over / F_over: spliced closes / fills (R7)."""
    n = V["n"]
    C = V["C"] if C_over is None else C_over
    Cn = np.nan_to_num(C, nan=0.0)
    F = V["F"] if F_over is None else F_over
    gc, gf, L = V["gc"], V["gf"], V["L"]
    Wsel = V["Wn"]
    S = len(V["S"])
    e0 = evs[0]
    assert e0["idx"] == 0
    w0 = V["W"][e0["k"]]
    sh0 = np.where(w0 > 0, w0 / V["init_fill"], 0.0)       # R7's splice starts after T0, so the initial fills are never spliced
    sh0 = sh0 / float((sh0 * Cn[0]).sum())
    val0 = sh0 * Cn[0]
    if mixf is not None:
        shares = sh0 * mixf
        sleeve = 1.0 - mixf
    else:
        kept0 = e0["kfull"]
        shares = np.where(kept0, sh0, 0.0)
        sleeve = float(val0[~kept0].sum())
    gu = sleeve / 2.0 / gc[0]
    cu = sleeve / 2.0 / L[0]
    segs = [(0, shares.copy(), gu, cu)]
    trades = []
    for ev in evs[1:]:
        i = ev["idx"]
        pf = F[i]
        w = Wsel[ev["k"]]
        held = w > 0
        cur_hold = shares != 0
        if np.isnan(pf[held | cur_hold]).any():
            raise RuntimeError(f"missing fill price for a needed stock at {V['cal'][i]}")
        pfz = np.where(np.isnan(pf), 0.0, pf)
        cur_stock = np.where(cur_hold, shares * pfz, 0.0)
        cur_g = gu * gf[i]
        cur_c = cu * L[i]
        Vv = cur_stock.sum() + cur_g + cur_c
        if mixf is not None:
            tgt_stock = np.where(held, mixf * Vv * w, 0.0)
            tgt_g = tgt_c = (1.0 - mixf) / 2.0 * Vv
            s_ = 1.0 - mixf
        else:
            kept = ev["kfull"] & held
            tgt_stock = np.where(kept, Vv * w, 0.0)
            Dw = float(w[held & ~kept].sum())
            Sw = float(w[held].sum())
            s_ = Dw / Sw
            tgt_g = tgt_c = Vv * s_ / 2.0
        traded = np.abs(tgt_stock - cur_stock).sum() + abs(tgt_g - cur_g) + abs(tgt_c - cur_c)
        cost = traded * bps / 2.0 / 10000.0
        f = (Vv - cost) / Vv
        shares = np.where(tgt_stock > 0, tgt_stock * f / np.where(np.isnan(pf), 1.0, pf), 0.0)
        gold_traded = abs(tgt_g - cur_g) > 0
        gu = tgt_g * f / gf[i]
        cu = tgt_c * f / L[i]
        segs.append((i, shares.copy(), gu, cu))
        ts = float(tgt_stock.sum())
        trades.append(dict(idx=int(i), date=str(V["cal"][i].date()), kind=ev["kind"], e_after=ts / (ts + 2.0 * tgt_g) if ts + tgt_g > 0 else 0.0,
                           e_after_alt=1.0 - s_, basket_eff=str(pd.Timestamp(V["avail"][ev["k"]]).date()),
                           basket_eff_session=str(V["cal"][ev["bkey"]].date()) if ev.get("bkey", 0) >= 0 else None,
                           V=float(Vv), traded=float(traded), cost=float(cost), raw_gold_fill=bool(V["raw"][i] and gold_traded)))
    nav = np.empty(n)
    sval = np.empty(n)
    seg_end = [s[0] for s in segs[1:]] + [n]
    for (i0, sh, gu_, cu_), i1 in zip(segs, seg_end):
        nz = sh != 0
        if np.isnan(C[i0:i1][:, nz]).any():
            raise RuntimeError("held stock without a close")
        sv = Cn[i0:i1] @ sh
        sval[i0:i1] = sv
        nav[i0:i1] = sv + gc[i0:i1] * gu_ + L[i0:i1] * cu_
    for t in trades:
        t["nav_close_after"] = float(nav[t["idx"]])
    out = dict(nav=nav, trades=trades, stock_value=sval, n_segments=len(segs))
    if positions:
        pos = []
        for (i0, sh, gu_, cu_), dt in zip(segs, [str(V["cal"][0].date())] + [t["date"] for t in trades]):
            for nm, u in zip(V["S"], sh):
                if u != 0:
                    pos.append((dt, nm, float(u)))
            pos.append((dt, "GOLDBEES", float(gu_)))
            pos.append((dt, "CASH", float(cu_)))
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


STAT_COLS = ["end_nav", "cagr", "max_dd", "vol", "ulcer", "days_below_10pct", "longest_underwater", "calmar", "sessions"]
STAT_DIR = {"cagr": True, "max_dd": True, "vol": False, "ulcer": False, "days_below_10pct": False, "longest_underwater": False, "calmar": True}
EXACT_COLS = ("trades", "days_below_10pct", "longest_underwater", "sessions")


# ----------------------------------------------------------------------------------------
# allowed subsets, samplers (own code)
# ----------------------------------------------------------------------------------------
def subset_sums(w):
    s = np.zeros(1)
    for x in w:
        s = np.concatenate([s, s + x])
    return s


def allowed_subsets(w, Dw, tol=1e-12):
    """Every subset X (bitmask, increasing) with |sum w(X) - Dw| <= tau, tau = half the smallest listed weight (ties within 1e-12)."""
    w = np.asarray(w, dtype=float)
    tau = 0.5 * float(w.min())
    sums = subset_sums(w)
    d = np.abs(sums - Dw)
    A = np.flatnonzero(d <= tau + tol)
    return A, tau, float(np.min(np.abs(d[A] - tau))) if len(A) else float("inf")


def mask_of(drop_bool):
    return int(sum(1 << i for i, b in enumerate(drop_bool) if b))


def n46_draw(evinfo, draw_id, book_no):
    """N4.6 (T12.md section 3 step 11): held stocks in ISIN order, one uniform per event in event order, A[floor(u |A|)]."""
    rng = np.random.default_rng([SEED_PREFIX, 7, draw_id, book_no])
    out = []
    for e in evinfo:
        A = e["A"]
        u = rng.random()
        out.append(int(A[int(math.floor(u * len(A)))]))
    return out


def n48_draw(evinfo, isins_all, draw_id, book_no):
    """N4.8: one score per ISIN the book ever holds (ISIN order); at each event rank held stocks by descending score: the first n_L Large,
    the next n_M Mid, the rest Small and below. Returns per event a dict isin -> label (0, 1, 2)."""
    rng = np.random.default_rng([SEED_PREFIX, 8, draw_id, book_no])
    score = dict(zip(isins_all, rng.random(len(isins_all))))
    res = []
    for e in evinfo:
        order = sorted(e["isins"], key=lambda x: (-score[x], x))
        lab = {}
        for r, isn in enumerate(order):
            lab[isn] = 0 if r < e["n_large"] else (1 if r < e["n_large"] + e["n_mid"] else 2)
        res.append(lab)
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
    worse = tied = ge = 0
    for v in draws:
        v = float(v)
        if abs(v - x) <= tol * max(abs(v), abs(x)):
            tied += 1; ge += 1
        elif (v < x) == higher_better:
            worse += 1
        else:
            ge += 1
    n = len(draws)
    return (worse + 0.5 * tied) / n * 100.0, (1 + ge) / (n + 1)


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
        self.sub = {}

    def fail(self, desc):
        if self.first_fail is None:
            self.first_fail = desc

    def miss(self, desc):
        self.missing += 1
        self.fail("MISSING: " + desc)

    def count(self, key, compared, failed):
        s = self.sub.setdefault(key, [0, 0])
        s[0] += int(compared); s[1] += int(failed)

    def to_dict(self):
        return dict(compared=int(self.compared), failed=int(self.failed), missing=int(self.missing),
                    worst_rel=float(self.worst_rel), first_fail=self.first_fail, gate=self.gate, notes=self.notes,
                    parts={k: dict(compared=v[0], failed=v[1]) for k, v in self.sub.items()})


def rel(a, b):
    a = np.asarray(a, dtype=float); b = np.asarray(b, dtype=float)
    return np.abs(a - b) / np.maximum(np.abs(b), 1e-12)


def _norm_str(s):
    return s.astype(object).where(s.notna(), "<NA>").astype(str)


def bstr(s):
    def f(x):
        if x is None or (isinstance(x, float) and np.isnan(x)) or (x is pd.NA):
            return "<na>"
        if isinstance(x, (bool, np.bool_)):
            return "true" if x else "false"
        t = str(x).strip().lower()
        return {"true": "true", "false": "false", "1": "true", "0": "false", "1.0": "true", "0.0": "false"}.get(t, t)
    return s.map(f)


def dstr(s):
    dt = pd.to_datetime(s, errors="coerce")
    return dt.dt.strftime("%Y-%m-%d").where(dt.notna(), "<NA>")


def compare_frames(chk, mine, ev, keys, num_cols=(), str_cols=(), tol=TOL, part=None):
    """Outer-join on keys; rows on both sides are compared; rows on one side only are missing (a failure)."""
    mine = mine.copy(); ev = ev.copy()
    for k in keys:
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
        a = _norm_str(both[c + "_v"]).values
        b = _norm_str(both[c + "_e"]).values
        bc = a != b
        if bc.any() and first_desc is None:
            i = int(np.argmax(bc))
            first_desc = "first differing row %s col %s: verifier=%r evidence=%r" % ({k: both.iloc[i][k] for k in keys}, c, a[i], b[i])
        bad |= bc
    chk.compared += len(both)
    chk.failed += int(bad.sum())
    if part:
        chk.count(part, len(both) + len(miss), int(bad.sum()) + len(miss))
    if first_desc:
        chk.fail(first_desc)


def r4(x):
    return np.round(np.asarray(x, dtype=float), 4)


# ----------------------------------------------------------------------------------------
# R7 (T12.md section 2): flagged held stock-days and the splice
# ----------------------------------------------------------------------------------------
R7_VARIANTS = ("either", "today", "prev")      # 'held' = listed weight > 0 in the basket in force on t-1 or t / on t / on t-1


def r7_flags(V, variant):
    """|close_t / close_(t-1) - 1| >= 0.20 (D18 closes with the Polyplex correction, previous session's close; the 2017-10-19 stand-in
    has a zero move) on a held stock-day. Returns (rows, boolean flag matrix)."""
    n = V["n"]
    C = V["C"]
    wrow = np.array([V["basket_at"][basket_key(V, i)] for i in range(n)])
    Wr = V["Wn"][wrow]
    with np.errstate(divide="ignore", invalid="ignore"):
        ret = C[1:] / C[:-1] - 1.0
    if variant == "either":
        held = (Wr[:-1] > 0) | (Wr[1:] > 0)
    elif variant == "today":
        held = Wr[1:] > 0
    else:
        held = Wr[:-1] > 0
    flag = np.zeros((n, len(V["S"])), dtype=bool)
    flag[1:] = (np.abs(ret) >= R7_THRESHOLD) & held & ~np.isnan(ret)
    rows = []
    for t, i in zip(*np.nonzero(flag)):
        rows.append(dict(book=V["p"], isin=V["isins"][i], stock=V["S"][i], date=str(V["cal"][t].date()), close_prev=float(C[t - 1, i]),
                         close=float(C[t, i]), move=float(ret[t - 1, i])))
    return rows, flag


def r7_splice(V, flag):
    """T11's R7 splice: each flagged day's return set to zero for that stock (closes and fills from that day on x close_(t-1) / close_t)."""
    C = V["C"]
    M = np.ones_like(C)
    for t, i in zip(*np.nonzero(flag)):
        M[t:, i] *= C[t - 1, i] / C[t, i]
    return C * M, V["F"] * M


# ----------------------------------------------------------------------------------------
# derive everything that does not depend on the evidence
# ----------------------------------------------------------------------------------------
class Derived:
    """Calendar, books, views (full, r2, full_r6; lbes and liq), decisions, events (all modes), simulations on demand (cached)."""

    def __init__(self, books=BOOKS, verbose=True, r2_init=R2_INIT):
        self.books = list(books)
        t = time.time()
        self.cal_all = load_calendar()
        cal = self.cal_all[(self.cal_all >= T0_FULL) & (self.cal_all <= END)]
        self.cal = cal
        self.masters = load_masters()
        self.gold, self.mcx = load_gold()
        self.lbes, self.liq = load_lbes(), load_liquidcase()
        self.corr = load_corrections()
        self.tagger = RankTags()
        self.r2_init = r2_init
        assert self.tagger.cutoff > END_D17, f"membership cutoff {self.tagger.cutoff.date()} is not after the windows"
        if verbose:
            print(f"[{time.time()-t:6.1f}s] sources loaded: D26 sessions {len(cal)} ({cal[0].date()} -> {cal[-1].date()}), "
                  f"D23b snapshots {len(self.tagger.dates)}, membership cutoff {self.tagger.cutoff.date()}", flush=True)
        self.MK = market_arrays(cal, self.gold, self.mcx, self.lbes, self.liq)
        self.B, self.V, self.dec = {}, {}, {}
        for p in self.books:
            B = build_book(p, cal, self.MK, self.corr)
            self.B[p] = B
            n = B["n"]
            a_r2 = int(np.searchsorted(cal.values, np.datetime64(R2_START), side="left"))
            B["a_r2"] = a_r2
            for cash in ("lbes", "liq"):
                self.V[(p, "full", cash)] = make_view(B, 0, n, cash, "drift")
            self.V[(p, "r2", "lbes")] = make_view(B, a_r2, n, "lbes", r2_init)
            self.dec[(p, "full")] = decisions_for_window(self.V[(p, "full", "lbes")], "full", self.masters)
            self.dec[(p, "r2")] = decisions_for_window(self.V[(p, "r2", "lbes")], "r2", self.masters)
            if p in R6_BOOKS:
                self.V[(p, "full_r6", "lbes")] = self.V[(p, "full", "lbes")]
                d6 = self.dec[(p, "full")].copy(); d6["window"] = "full_r6"
                self.dec[(p, "full_r6")] = d6
            if verbose:
                print(f"[{time.time()-t:6.1f}s] {p}: built (sessions {n}, r2 from {cal[a_r2].date()}, stocks {len(B['S'])}, "
                      f"baskets in the window {len(B['basket_at_full'])}, skipped dropped D05 {[d for d in B['skipped_d05'] if d >= '2014']} "
                      f"/ sources {[d for d in B['skipped_src'] if d >= '2014']})", flush=True)
        self._events = {}
        self._sims = {}
        self.r7_variant = "either"
        self.t = t

    def tagger_for(self, window):
        return TagView(self.tagger, r6=(window == "full_r6"))

    def events(self, p, window, mode):
        key = (p, window, mode)
        if key not in self._events:
            self._events[key] = derive_events(self.V[(p, window, "lbes")], self.dec[(p, window)], self.tagger_for(window), mode)
        return self._events[key]

    def r7(self, p, variant=None):
        return r7_flags(self.V[(p, "full", "lbes")], variant or self.r7_variant)

    def sim(self, p, window, cash, kind, bps, positions=False, mix_variant="a"):
        key = (p, window, cash, kind, round(float(bps), 4), positions, mix_variant, self.r7_variant if kind.endswith("_r7") else "")
        if key in self._sims:
            return self._sims[key]
        V = self.V[(p, window, cash)]
        base = kind[:-3] if kind.endswith("_r7") else kind
        mode = {"segment": "rule", "whole_book": "tied", "parent": "allin", "sleeve100": "allout"}.get(base)
        if base == "constant_mix":
            rule_evs, _ = self.events(p, window, "rule")
            r = self.sim(p, window, cash, "segment", bps if mix_variant == "a" else 0.0)
            f = float(np.mean(r["stock_value"] / r["nav"]))
            res = simulate(V, rule_evs, bps, mixf=f, positions=positions)
            res["mixf"] = f
        elif mode is None:
            raise KeyError(kind)
        else:
            evs, _ = self.events(p, window, mode)
            if kind.endswith("_r7"):
                C2, F2 = r7_splice(V, self.r7(p)[1])
                res = simulate(V, evs, bps, positions=positions, C_over=C2, F_over=F2)
            else:
                res = simulate(V, evs, bps, positions=positions)
        self._sims[key] = res
        return res


def event_frames(DV, p, window):
    """Expected events.csv and event_stocks.csv rows of one book and window (own derivation)."""
    V = DV.V[(p, window, "lbes")]
    evs, _ = DV.events(p, window, "rule")
    dec = DV.dec[(p, window)]
    rule_sim = DV.sim(p, window, "lbes", "segment", HEADLINE_COST)
    tr = {t["idx"]: t for t in rule_sim["trades"]}
    erows, srows = [], []
    for no, ev in enumerate(evs):
        num = event_numbers(V, ev)
        w = V["Wn"][ev["k"]]
        A, tau, _ = allowed_subsets(w[ev["held"]], num["dropped_weight"]) if 0 < len(ev["held"]) <= 16 else (np.array([]), num["tau"], 0)
        j = ev["j"]
        info_idx = ev["info_idx"]
        t = tr.get(ev["idx"], {})
        erows.append(dict(book=p, window=window, event_no=no, kind=ev["kind"], trade_date=str(V["cal"][ev["idx"]].date()), trade_idx=ev["idx"],
                          info_date=str(V["cal"][info_idx].date()), decision_date=dec["decision_date"].iloc[j],
                          state_Nifty100=dec["sign_Nifty100"].iloc[j], state_MC100=dec["sign_MC100"].iloc[j], state_SC100=dec["sign_SC100"].iloc[j],
                          basket_eff=str(pd.Timestamp(V["avail"][ev["k"]]).date()),
                          basket_eff_session=str(V["cal"][max(ev["bkey"], 0)].date()), n_allowed_subsets=int(len(A)),
                          V_before=t.get("V", np.nan), traded=t.get("traded", np.nan), cost=t.get("cost", np.nan), **num))
        for si, tg, kp in zip(ev["held"], ev["tags"], ev["kept"]):
            srows.append(dict(book=p, window=window, event_no=no, trade_date=str(V["cal"][ev["idx"]].date()),
                              info_date=str(V["cal"][info_idx].date()), isin=V["isins"][si], stock=V["S"][si], listed_weight=float(w[si]),
                              band=tg["band"], tag_source=tg["source"], tag_snapshot=tg["snapshot"],
                              tag_detail=np.nan if tg["detail"] is None else float(tg["detail"]),
                              tag_n_ranked=np.nan if tg["n_ranked"] is None else float(tg["n_ranked"]), tag_via=tg["via"],
                              linked_quote_id=tg.get("linked_quote_id"), kept=bool(kp),
                              band_sign=dec[["sign_Nifty100", "sign_MC100", "sign_SC100"][BAND_INDEX[tg["band"]]]].iloc[j]))
    return pd.DataFrame(erows), pd.DataFrame(srows)


def derive_sets(DV):
    out = dict(events={}, stocks={})
    for p in DV.books:
        for window in windows_of(p):
            e, s = event_frames(DV, p, window)
            out["events"][(p, window)] = e
            out["stocks"][(p, window)] = s
    return out


def r6_rows(SETS, books):
    """Expected r6_links.csv: every event row of full_r6 where R6 re-tags a holding."""
    rows = []
    for p in books:
        if p not in R6_BOOKS:
            continue
        s = SETS["stocks"][(p, "full_r6")]
        for _, r in s[s["tag_source"] == "rank_linked"].iterrows():
            rows.append(dict(book=p, isin=r["isin"], stock=r["stock"], original_source="unranked", linked_quote_id=int(r["linked_quote_id"]),
                             info_date=r["info_date"], trade_date=r["trade_date"], linked_rank=int(r["tag_detail"]), linked_band=r["band"]))
    return pd.DataFrame(rows, columns=["book", "isin", "stock", "original_source", "linked_quote_id", "info_date", "trade_date", "linked_rank",
                                       "linked_band"])


# ----------------------------------------------------------------------------------------
# C-regress: the D17 calendar of 2019 against T07's and T06's stored NAVs (V4(a)), and T11 (V4(b)) if its headline exists
# ----------------------------------------------------------------------------------------
def derive_regression(DV, books, verbose=True):
    t = time.time()
    out = dict(books={}, nav={})
    for p in books:
        pub = load_published_nav(p)
        cal17 = pub.index[pub.index <= END_D17]
        MK17 = market_arrays(cal17, DV.gold, DV.mcx, DV.lbes, DV.liq)
        B = build_book(p, cal17, MK17, DV.corr)
        V = make_view(B, 0, len(cal17), "lbes", "drift")
        dec = decisions_for_window(V, "d17", DV.masters)
        tv = TagView(DV.tagger)
        ev_rule, _ = derive_events(V, dec, tv, "rule")
        ev_tied, _ = derive_events(V, dec, tv, "tied")
        for bps in COSTS:
            out["nav"][(p, "segment", bps)] = pd.Series(simulate(V, ev_rule, bps)["nav"], index=cal17)
            out["nav"][(p, "whole_book", bps)] = pd.Series(simulate(V, ev_tied, bps)["nav"], index=cal17)
        out["books"][p] = dict(first=str(cal17[0].date()), last=str(cal17[-1].date()), sessions=len(cal17), decisions=len(dec), events=len(ev_rule))
        if verbose:
            print(f"[{time.time()-t:6.1f}s] {p}: D17-calendar regression runs ({len(cal17)} sessions from {cal17[0].date()}, {len(ev_rule)} events)", flush=True)
    return out


# ----------------------------------------------------------------------------------------
# evidence loading (a missing file is None, never an exception)
# ----------------------------------------------------------------------------------------
EVIDENCE_FILES = ["inputs.csv", "decisions.csv", "events.csv", "event_stocks.csv", "stats.csv", "draws.csv", "draw_drops.npz",
                  "draw_labels.npz", "draw_curves_20.8.npz", "daily_nav.csv", "trades.csv", "positions.csv", "count_table.json",
                  "controls_oracle.json", "regression.json", "r6_links.csv", "r7_flagged_days.csv", "audit.json"]
HEADLINE_ONLY = {"controls_oracle.json", "regression.json", "audit.json"}


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
                        obj = pd.read_csv(p, keep_default_na=False, na_values=[""])
                    elif name.endswith(".json"):
                        obj = json.load(open(p))
                    elif name.endswith(".npz"):
                        z = np.load(p)
                        obj = {k: z[k] for k in z.files}
                except Exception as ex:
                    self.missing_files.append(f"{name} (unreadable: {ex!r})")
                    obj = None
            self._cache[name] = obj
        if obj is None and chk is not None:
            chk.miss(f"evidence file {name}")
        return obj


ONLY = None        # set of check names to run (self-test of single corruptions); None = all


def run_check(C, name, fn, gate=True):
    c = Check(name, gate=gate)
    if ONLY is not None and name not in ONLY:
        return c
    C[name] = c
    try:
        fn(c)
    except Exception as ex:
        c.failed += 1
        c.fail(f"verifier exception in {name}: {ex!r} | {traceback.format_exc(limit=3).strip().splitlines()[-1]}")
    return c


def with_window(df, default="full"):
    df = df.copy()
    if "window" not in df.columns:
        df["window"] = default
    return df


def sample_ids(book, typ, pool, n_first=20, n_rand=20, seed=20261117):
    rng = np.random.default_rng([seed, BOOKS.index(book), 0 if typ == "N4.6" else 1])
    first = list(range(min(n_first, pool)))
    rest = np.arange(len(first), pool)
    k = min(n_rand, len(rest))
    return first + (sorted(rng.choice(rest, size=k, replace=False).tolist()) if k > 0 else [])


def find_book(obj, book):
    if isinstance(obj, dict):
        if book in obj:
            return obj[book]
        for v in obj.values():
            r = find_book(v, book)
            if r is not None:
                return r
    elif isinstance(obj, list):
        for v in obj:
            if isinstance(v, dict) and v.get("book") == book:
                return v
    return None


def first_key(d, pats):
    for k in d:
        lk = k.lower()
        if any(re.search(p, lk) for p in pats):
            return k
    return None


def count_records(entry, window):
    if isinstance(entry, dict) and window in entry:
        entry = entry[window]
    elif isinstance(entry, dict) and any(w in entry for w in WINDOWS):
        return []                       # the book has windows, but not this one
    if isinstance(entry, dict):
        for k, v in entry.items():
            if isinstance(v, list) and v and isinstance(v[0], dict):
                return v
        for v in entry.values():
            if isinstance(v, dict):
                r = count_records(v, window)
                if r:
                    return r
    if isinstance(entry, list) and entry and isinstance(entry[0], dict):
        return entry
    return []


def all_numbers(obj, pat):
    """Every (key path, number) in a nested JSON whose last key matches pat."""
    out = []

    def walk(o, path):
        if isinstance(o, dict):
            for k, v in o.items():
                walk(v, path + [str(k)])
        elif isinstance(o, list):
            for i, v in enumerate(o):
                walk(v, path + [str(i)])
        elif isinstance(o, (int, float)) and not isinstance(o, bool) and path and re.search(pat, path[-1].lower()):
            out.append(("/".join(path), float(o)))
    walk(obj, [])
    return out


def audit_unranked(obj, p, w):
    """ISINs that audit.json's 'unranked' gives for book p and window w, whether keyed '<book>|<window>' or nested book -> window; None if
    no entry exists."""
    key = f"{p}|{w}"
    hits = []

    def walk(o):
        if isinstance(o, dict):
            for k, v_ in o.items():
                if k == key:
                    hits.append(v_)
                elif k == p and isinstance(v_, dict) and w in v_:
                    hits.append(v_[w])
                else:
                    walk(v_)
        elif isinstance(o, list):
            for v_ in o:
                walk(v_)
    walk(obj)
    if not hits:
        return None
    return set(re.findall(r"INE[0-9A-Z]{9}", json.dumps(hits)))


def oracle_choice(DV, p, variant):
    """V7 oracle: at each event the allowed subset with the lowest sum of listed weight x realised log return from the trade session to the
    next event's trade session (the last event: to the last close); ties to the lowest bitmask. 'fill': fill to fill (T0 at its close);
    'close': close to close."""
    V = DV.V[(p, "full", "lbes")]
    evs, _ = DV.events(p, "full", "rule")
    n = V["n"]
    new = []
    for no, e in enumerate(evs):
        w = V["Wn"][e["k"]][e["held"]]
        num = event_numbers(V, e)
        A, tau, _ = allowed_subsets(w, num["dropped_weight"])
        nxt = evs[no + 1]["idx"] if no + 1 < len(evs) else n - 1
        s_ = e["idx"]
        held = e["held"]
        if variant == "fill":
            p0 = V["F"][s_][held] if s_ > 0 else V["C"][0][held]
            p1 = (V["F"][nxt][held] if no + 1 < len(evs) else V["Cn"][n - 1][held])
        else:
            p0 = V["C"][s_][held]; p1 = V["C"][nxt][held]
        r = np.log(np.where(np.isnan(p1) | np.isnan(p0), 1.0, p1 / p0))
        sums = subset_sums(w * r)
        best = A[int(np.argmin(sums[A]))]
        kept = np.array([not ((best >> i) & 1) for i in range(len(held))], dtype=bool)
        kf = np.zeros(len(V["S"]), dtype=bool); kf[held[kept]] = True
        e2 = dict(e); e2["kfull"] = kf; e2["kept"] = kept
        new.append(e2)
    res = simulate(V, new, HEADLINE_COST)
    return new, stats_of(res["nav"])["cagr"]


def event_infos(DV, p, window):
    """Per event of the rule: held stocks in ISIN order, their renormalised weights, the allowed N4.6 subsets (bitmasks over that order)."""
    V = DV.V[(p, window, "lbes")]
    evs, _ = DV.events(p, window, "rule")
    out = []
    for e in evs:
        held = sorted(((V["isins"][si], si) for si in e["held"]))
        w = np.array([V["Wn"][e["k"]][si] for _, si in held])
        kept_map = dict(zip(e["held"].tolist(), e["kept"].tolist()))
        Dw = float(sum(x for (_, si), x in zip(held, w) if not kept_map[si]))
        A, tau, _ = allowed_subsets(w, Dw)
        nums = event_numbers(V, e)
        out.append(dict(A=A, isins=[i for i, _ in held], sis=[si for _, si in held], w=w, n_large=nums["n_large"], n_mid=nums["n_mid"],
                        n_small=nums["n_small"]))
    return out


# ----------------------------------------------------------------------------------------
# the checks
# ----------------------------------------------------------------------------------------
RUNS = ["segment", "whole_book", "parent", "constant_mix", "sleeve100"]
R7_RUNS = ["segment_r7", "whole_book_r7"]


def regress_check(c, DV, REG, E, run_name):
    """C-regress (V4(a), V4(b)): my D17-calendar runs against the stored NAVs of T07 (rule, every cost) and T06 (whole book)."""
    t7 = pd.read_csv(T07_EVIDENCE / "daily_nav.csv"); t7["date"] = pd.to_datetime(t7["date"]); t7["cost_bps"] = r4(t7["cost_bps"])
    t6 = pd.read_csv(T06_EVIDENCE / "daily_nav.csv"); t6["date"] = pd.to_datetime(t6["date"]); t6["cost_bps"] = r4(t6["cost_bps"])
    mine_v4a = {}
    for p in DV.books:
        rec = dict(sessions=REG["books"][p]["sessions"], first=REG["books"][p]["first"], last=REG["books"][p]["last"])
        for tag, src, run_mine, run_src in (("t07", t7, "segment", "segment"), ("t06", t6, "whole_book", "strategy")):
            worst = 0.0; nses = 0
            for bps in COSTS:
                m = REG["nav"][(p, run_mine, bps)]
                s_ = src[(src["book"] == p) & (src["run"] == run_src) & (src["cost_bps"] == bps)].set_index("date")["nav"]
                if not len(s_):
                    c.miss(f"{tag} stored daily_nav.csv rows for {p} {run_src} {bps}"); continue
                s_ = s_.reindex(m.index)
                if s_.isna().any():
                    c.miss(f"{tag} stored NAV lacks {int(s_.isna().sum())} D17 sessions for {p} {bps}"); continue
                d_ = rel(m.values, s_.values)
                bad = int((d_ > TOL_REGRESSION).sum())
                c.compared += len(d_); c.failed += bad; c.count(f"v4a_{tag}", len(d_), bad)
                c.worst_rel = max(c.worst_rel, float(d_.max()))
                worst = max(worst, float(d_.max())); nses += len(d_)
                if bad:
                    i = int(np.argmax(d_ > TOL_REGRESSION)); c.fail(f"{p} {bps} bps {m.index[i].date()}: {run_mine} differs from {tag}'s stored NAV by {d_[i]:.3e}")
            rec[f"{tag}_sessions_x_costs"] = nses; rec[f"{tag}_max_rel"] = worst
        mine_v4a[p] = rec
        c.notes.append(f"{p}: D17 {rec['first']} -> {rec['last']} ({rec['sessions']} sessions); rule vs T07 max rel {rec['t07_max_rel']:.2e}, "
                       f"whole book vs T06 max rel {rec['t06_max_rel']:.2e} (limit {TOL_REGRESSION:g})")
    DV.v4a = mine_v4a
    # V4(b): T11's headline, if it exists
    t11 = T11_HEADLINE.exists()
    if t11:
        dn = pd.read_csv(T11_HEADLINE / "daily_nav.csv"); dn["cost_bps"] = r4(dn["cost_bps"]); dn["date"] = dstr(dn["date"])
        for p in DV.books:
            ds = [str(d.date()) for d in DV.V[(p, "full", "lbes")]["cal"]]
            for bps in COSTS:
                for mine_k, t11_k in (("whole_book", "strategy_fixed50"), ("parent", "hold_parent")):
                    s_ = dn[(dn["book"] == p) & (dn["run"] == t11_k) & (dn["cost_bps"] == bps)].set_index("date")["nav"].reindex(ds)
                    if s_.isna().any():
                        c.miss(f"T11 headline {p} {t11_k} {bps}: {int(s_.isna().sum())} sessions missing"); continue
                    d_ = rel(DV.sim(p, "full", "lbes", mine_k, bps)["nav"], s_.values)
                    bad = int((d_ > TOL).sum()); c.compared += len(d_); c.failed += bad; c.count("v4b_t11", len(d_), bad)
                    c.worst_rel = max(c.worst_rel, float(d_.max()))
                    if bad:
                        c.fail(f"{p} {bps} {mine_k}: differs from T11's {t11_k} by up to {d_.max():.3e}")
        c.notes.append("V4(b) run: T11 headline evidence exists")
    else:
        c.notes.append("V4(b) not run: tests/T11/evidence/headline/ does not exist")
    # regression.json (the engine's own V4 record)
    rj = E.get("regression.json", c if run_name == "headline" else None) if E is not None else None
    if rj is None:
        return
    for p in DV.books:
        ent = find_book(rj.get("v4a", rj), p)
        if ent is None:
            c.miss(f"regression.json v4a entry for {p}"); continue
        nums = all_numbers(ent, r"max|rel|diff")
        c.compared += 1
        bad = (not nums) or any(v > TOL_REGRESSION for _, v in nums)
        c.count("regression_json_v4a", 1, int(bad))
        if bad:
            c.failed += 1; c.fail(f"regression.json v4a {p}: reported differences {nums[:4]} (none, or above {TOL_REGRESSION:g})")
        ses = [v for k, v in all_numbers(ent, r"session") if v > 0]
        if ses:
            c.compared += 1
            ok = any(int(v) in (mine_v4a[p]["sessions"], mine_v4a[p]["sessions"] * 3) for v in ses)
            c.count("regression_json_sessions", 1, int(not ok))
            if not ok:
                c.failed += 1; c.fail(f"regression.json v4a {p}: sessions {ses[:4]} vs mine {mine_v4a[p]['sessions']} (x3 costs: {mine_v4a[p]['sessions']*3})")
    v4b = rj.get("v4b")
    if v4b is not None:
        c.compared += 1
        txt = json.dumps(v4b).lower()
        bad = ("not run" in txt) == t11
        c.count("regression_json_v4b_status", 1, int(bad))
        if bad:
            c.failed += 1; c.fail(f"regression.json v4b says {'not run' if not t11 else 'run'} but T11's headline {'exists' if t11 else 'does not exist'}")
    v4d = rj.get("v4d")
    if v4d is not None:
        mm = all_numbers(v4d, r"mismatch")
        c.compared += 1
        bad = (not mm) or any(v != 0 for _, v in mm)
        c.count("regression_json_v4d", 1, int(bad))
        if bad:
            c.failed += 1; c.fail(f"regression.json v4d mismatches {mm[:4]}")


def compare_all(DV, SETS, E, run_name, REG):
    C = {}
    books = DV.books
    strict = run_name == "headline"

    def my_windows(ev_windows=None):
        out = [(p, w) for p in books for w in windows_of(p)]
        if not strict and ev_windows is not None:
            out = [(p, w) for p, w in out if w in ev_windows]
        return out

    # ------------------------------------------------------------------ C-data
    def c_data(c):
        inp = E.get("inputs.csv", c)
        for key in sorted(READS):
            row = APPROVED.get(key)
            c.compared += 1
            ok = row is not None and row["status"] == "APPROVED"
            if ok:
                sha = sha256_file(AA / key)
                READS[key]["sha"] = sha
                ok = sha.startswith(row["sha"])
                if ok and row["through"].lower() != "n/a" and row["id"] not in THROUGH_EXEMPT_IDS and not READS[key]["gate_only"]:
                    ok = pd.Timestamp(row["through"]) >= END
            if not ok:
                c.failed += 1; c.fail(f"verifier-read file not an APPROVED, matching, covering row: {key}")
        c.count("verifier_reads", len(READS), 0)
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
            c.compared += 1
            if not sha.startswith(row["sha"]):
                c.failed += 1; c.fail(f"sha256 of {key} in inputs.csv ({sha[:16]}) does not start with the approved prefix {row['sha']}")
            c.compared += 1
            disk = sha256_file(AA / key) if (AA / key).exists() else None
            if disk is None or (sha and disk != sha and not disk.startswith(sha)):
                c.failed += 1; c.fail(f"sha256 of {key} in inputs.csv differs from the file on disk")
            c.compared += 1
            if row["through"].lower() != "n/a" and row["id"] not in THROUGH_EXEMPT_IDS and pd.Timestamp(row["through"]) < END:
                c.failed += 1; c.fail(f"approved through-date of {key} ({row['through']}) does not cover the window's end {END.date()}")
            if "through" in cols:
                c.compared += 1
                th = str(r[cols["through"]]).strip()
                if th.lower() not in ("n/a", "nan") and row["through"].lower() != "n/a" and th != row["through"]:
                    c.failed += 1; c.fail(f"through of {key} in inputs.csv ({th}) differs from APPROVED_DATA.md ({row['through']})")
        c.compared += 1
        if norm_path(F_RANK) not in listed:
            c.failed += 1; c.fail(f"inputs.csv does not list the D23b combined rank panel {F_RANK}")
        not_listed = sorted(k for k in set(READS) - listed if not READS[k]["gate_only"])
        if not_listed:
            c.notes.append(f"{len(not_listed)} file(s) the verifier read for the T12 window are not in inputs.csv (not a failure under the spec): {not_listed[:5]}")
        c.notes.append(f"through-date exempt roles: {sorted(THROUGH_EXEMPT_IDS)}; gate-only reads (D17 for C-regress, D20/D20b for the information cross-check) are not required in inputs.csv")
    run_check(C, "C-data", c_data)

    # ------------------------------------------------------------------ C-dec
    def c_dec(c):
        ev = E.get("decisions.csv", c)
        if ev is None:
            return
        ev = with_window(ev)
        ev = ev[ev["book"].isin(books)]
        wins = sorted(set(ev["window"]))
        mine = pd.concat([DV.dec[(p, w)] for p in books for w in ("full", "r2") if w in wins or w == "full"], ignore_index=True)
        num = [x for x in ("decision_idx", "label_age_days") if x in ev.columns]
        strc = [x for x in ("decision_date", "trade_date", "sign_Nifty100", "sign_MC100", "sign_SC100", "label_Nifty100", "label_MC100",
                            "label_SC100", "latest_label", "pattern") if x in ev.columns]
        mm, ee = mine.copy(), ev.copy()
        for col in ("decision_date", "trade_date", "label_Nifty100", "label_MC100", "label_SC100", "latest_label"):
            if col in ee.columns:
                mm[col] = dstr(mm[col]); ee[col] = dstr(ee[col])
        for col in ("all_three_buy", "disagree"):
            if col in ee.columns:
                mm[col] = bstr(mm[col]); ee[col] = bstr(ee[col]); strc.append(col)
        if "state" in ee.columns and pd.api.types.is_numeric_dtype(ee["state"]):
            num.append("state")
        compare_frames(c, mm, ee, ["book", "window", "j"], num_cols=num, str_cols=strc, tol=0.0, part="decisions")
        for p in books:
            nfull = int(((ev["book"] == p) & (ev["window"] == "full")).sum())
            c.compared += 1
            if nfull != N_DECISIONS_FULL:
                c.failed += 1; c.fail(f"{p}: {nfull} full-window decisions in decisions.csv, T12.md says {N_DECISIONS_FULL}")
        c.notes.append(f"decisions compared in windows {wins}; full-window disagreement weeks (mine): "
                       + ", ".join(f"{p} {int(DV.dec[(p, 'full')]['disagree'].sum())}" for p in books))
    run_check(C, "C-dec", c_dec)

    # ------------------------------------------------------------------ C-tag
    def c_tag(c):
        es = E.get("event_stocks.csv", c)
        if es is None:
            return
        es = with_window(es)
        es = es[es["book"].isin(books)].copy()
        mine = pd.concat([SETS["stocks"][k] for k in my_windows(set(es["window"]))], ignore_index=True)
        for x in (mine, es):
            for col in ("trade_date", "info_date", "tag_snapshot"):
                x[col] = dstr(x[col])
            x["kept"] = bstr(x["kept"])
        unr = mine["tag_source"] == "unranked"
        mine.loc[unr, "tag_snapshot"] = "<NA>"
        es.loc[es["tag_source"].astype(str) == "unranked", "tag_snapshot"] = "<NA>"
        compare_frames(c, mine, es, ["book", "window", "trade_date", "isin"], num_cols=["listed_weight"],
                       str_cols=["band", "tag_source", "tag_snapshot", "kept", "info_date"], tol=1e-9, part="event_stocks")
        # the rank behind each rank tag (tag_detail), n_ranked of its snapshot (tag_n_ranked), tag_via of the R6-linked rows
        ranked_m = mine[mine["tag_source"].isin(["rank", "rank_linked"])]
        for col in ("tag_detail", "tag_n_ranked"):
            if col not in es.columns:
                if col == "tag_n_ranked":
                    c.miss("event_stocks.csv column tag_n_ranked (evidence contract point 3)")
                continue
            e2 = es[es["tag_source"].astype(str).isin(["rank", "rank_linked"])].copy()
            e2[col] = pd.to_numeric(e2[col].astype(str).str.extract(r"(-?\d+(?:\.\d+)?)")[0], errors="coerce")
            compare_frames(c, ranked_m[["book", "window", "trade_date", "isin", col]], e2[["book", "window", "trade_date", "isin", col]],
                           ["book", "window", "trade_date", "isin"], num_cols=[col], tol=0.0, part=col)
        if "tag_via" in es.columns:
            lk = mine[mine["tag_source"] == "rank_linked"][["book", "window", "trade_date", "isin", "tag_via"]]
            e2 = es[es["tag_source"].astype(str) == "rank_linked"][["book", "window", "trade_date", "isin", "tag_via"]]
            compare_frames(c, lk, e2, ["book", "window", "trade_date", "isin"], str_cols=["tag_via"], tol=0.0, part="tag_via_r6")
        if "band_signal" in es.columns:
            vals = set(es["band_signal"].astype(str).unique())
            m2 = mine.copy()
            if vals <= {"BUY", "SELL"}:
                m2["band_signal"] = m2["band_sign"]
            elif vals <= set(INDEX_NAMES):
                m2["band_signal"] = m2["band"].map(lambda b: INDEX_NAMES[BAND_INDEX[b]])
            else:
                m2 = None
                c.notes.append(f"band_signal values {sorted(vals)[:4]} not recognised; not compared")
            if m2 is not None:
                compare_frames(c, m2, es, ["book", "window", "trade_date", "isin"], str_cols=["band_signal"], tol=0.0, part="band_signal")
        # unranked holdings: mine against Step 1's list and against audit.json
        au = E.get("audit.json", c if strict else None)
        for p in books:
            for w in windows_of(p):
                s = SETS["stocks"][(p, w)]
                got = set(s.loc[s["tag_source"] == "unranked", "isin"])
                exp = set() if w == "full_r6" and R6_LINKS == R6_LINKS_REVIEW else EXPECTED_UNRANKED[p]
                c.compared += 1; c.count("unranked_vs_step1", 1, int(got != exp))
                if got != exp:
                    c.failed += 1; c.fail(f"{p} {w}: unranked holdings at events {sorted(got)}, expected {sorted(exp)}")
                if au is not None and isinstance(au.get("unranked"), (dict, list)):
                    claimed = audit_unranked(au["unranked"], p, w)
                    if claimed is None:
                        c.miss(f"audit.json 'unranked' has no entry for {p} {w}"); continue
                    c.compared += 1; c.count("unranked_vs_audit", 1, int(claimed != got))
                    if claimed != got:
                        c.failed += 1; c.fail(f"{p} {w}: audit.json lists unranked {sorted(claimed)}, verifier {sorted(got)}")
        c.notes.append("tag_source counts (mine, rows): " + json.dumps(mine["tag_source"].value_counts().to_dict()))
        c.notes.append(f"R6 quote_ids used: {R6_LINKS} ({'review reading' if R6_LINKS == R6_LINKS_REVIEW else 'frozen-text reading'})")
    run_check(C, "C-tag", c_tag)

    # ------------------------------------------------------------------ C-r6
    def c_r6(c):
        need = [p for p in books if p in R6_BOOKS]
        if not need:
            c.gate = False
            c.notes.append("not applicable: no R6 book (SCMO_0007, SCMO_0010) selected"); return
        rl = E.get("r6_links.csv", c)
        if rl is None:
            return
        mine = r6_rows(SETS, books)
        ev = rl[rl["book"].isin(need)].copy()
        for x in (mine, ev):
            x["info_date"] = dstr(x["info_date"])
        num = [x for x in ("linked_quote_id", "linked_rank") if x in ev.columns]
        strc = [x for x in ("linked_band", "original_source") if x in ev.columns]
        compare_frames(c, mine, ev, ["book", "isin", "info_date"], num_cols=num, str_cols=strc, tol=0.0, part="r6_links")
        c.compared += 1
        c.notes.append(f"R6 rows (mine): {len(mine)}; " + ", ".join(f"{p} {int((mine['book'] == p).sum())}" for p in need))
    run_check(C, "C-r6", c_r6)

    # ------------------------------------------------------------------ C-events
    def c_events(c):
        ev = E.get("events.csv", c)
        if ev is None:
            return
        ev = with_window(ev)
        ev = ev[ev["book"].isin(books)].copy()
        mine = pd.concat([SETS["events"][k] for k in my_windows(set(ev["window"]))], ignore_index=True)
        for x in (mine, ev):
            x["trade_date"] = dstr(x["trade_date"]); x["info_date"] = dstr(x["info_date"]); x["partial"] = bstr(x["partial"])
        ev_num = [x for x in ("trade_idx", "n_held", "n_large", "n_mid", "n_small", "n_dropped", "dropped_weight", "sum_weights",
                              "sleeve_share_s", "tau") if x in ev.columns]
        ev_str = [x for x in ("kind", "info_date", "partial", "state_Nifty100", "state_MC100", "state_SC100") if x in ev.columns]
        compare_frames(c, mine, ev, ["book", "window", "trade_date"], num_cols=ev_num, str_cols=ev_str, tol=1e-9, part="events")
        if "basket_eff" in ev.columns:
            m2, e2 = mine.copy(), ev.copy()
            e2["be"] = dstr(e2["basket_eff"])
            m2["be_avail"] = dstr(m2["basket_eff"]); m2["be_sess"] = dstr(m2["basket_eff_session"])
            j = m2.merge(e2[["book", "window", "trade_date", "be"]], on=["book", "window", "trade_date"], how="inner")
            okb = (j["be"] == j["be_avail"]) | (j["be"] == j["be_sess"])
            c.compared += len(j); c.failed += int((~okb).sum()); c.count("basket_eff", len(j), int((~okb).sum()))
            if (~okb).any():
                r = j[~okb].iloc[0]; c.fail(f"basket_eff differs at {r['book']} {r['window']} {r['trade_date']}: evidence {r['be']} vs {r['be_avail']} / {r['be_sess']}")
        for (p, w), g in mine.groupby(["book", "window"]):
            ne = int(((ev["book"] == p) & (ev["window"] == w)).sum())
            c.compared += 1
            c.count("event_count", 1, int(ne != len(g)))
            if ne != len(g):
                c.failed += 1; c.fail(f"{p} {w}: evidence has {ne} events, verifier {len(g)}")
        for w in ("full", "r2"):
            c.notes.append(f"events ({w}): " + ", ".join(f"{p} {int(((mine['book'] == p) & (mine['window'] == w)).sum())}" for p in books)
                           + "; partial (0 < share < 1): " + ", ".join(f"{p} {int(((mine['book'] == p) & (mine['window'] == w) & (mine['partial'] == 'true')).sum())}" for p in books))
    run_check(C, "C-events", c_events)

    # ------------------------------------------------------------------ C-target (events V / traded / cost, trades, positions)
    def c_target(c):
        ev = E.get("events.csv")
        if ev is not None:
            ev = with_window(ev)
            mine = pd.concat([SETS["events"][k] for k in my_windows(set(ev["window"]))], ignore_index=True)
            mine = mine[mine["trade_idx"] > 0].copy(); mine["trade_date"] = dstr(mine["trade_date"])
            e2 = ev[ev["book"].isin(books)].copy(); e2["trade_date"] = dstr(e2["trade_date"])
            e2 = e2[e2["trade_idx"].astype(float) > 0] if "trade_idx" in e2.columns else e2
            cols = [x for x in ("V_before", "traded", "cost") if x in e2.columns]
            if cols:
                compare_frames(c, mine[["book", "window", "trade_date"] + cols], e2[["book", "window", "trade_date"] + cols],
                               ["book", "window", "trade_date"], num_cols=cols, tol=TOL, part="events_V_traded_cost")
        tr = E.get("trades.csv", c)
        ps = E.get("positions.csv", c)
        if tr is not None:
            rows = []
            for p in books:
                for bps in COSTS:
                    for run in RUNS:
                        for t in DV.sim(p, "full", "lbes", run, bps)["trades"]:
                            rows.append(dict(book=p, cost_bps=bps, run=run, **t))
            mine = pd.DataFrame(rows)
            ev = tr[tr["book"].isin(books) & tr["run"].isin(RUNS)].copy()
            ev["cost_bps"] = r4(ev["cost_bps"])
            if "idx" in ev.columns:
                ev = ev[ev["idx"].astype(float) > 0]
            ev["date"] = dstr(ev["date"]); mine["date"] = dstr(mine["date"])
            cols = [x for x in ("V", "traded", "cost", "nav_close_after", "idx") if x in ev.columns]
            compare_frames(c, mine, ev, ["book", "cost_bps", "run", "date"], num_cols=cols, tol=TOL, part="trades")
            j = mine.merge(ev[["book", "cost_bps", "run", "date", "e_after"]], on=["book", "cost_bps", "run", "date"], suffixes=("_v", "_e")) if "e_after" in ev.columns else None
            if j is not None and len(j):
                ok = (np.abs(j["e_after_v"].astype(float) - j["e_after_e"].astype(float)) < 1e-9) | (np.abs(j["e_after_alt"].astype(float) - j["e_after_e"].astype(float)) < 1e-9)
                c.compared += len(j); c.failed += int((~ok).sum()); c.count("trades_e_after", len(j), int((~ok).sum()))
                if (~ok).any():
                    r = j[~ok].iloc[0]; c.fail(f"e_after differs at {r['book']} {r['cost_bps']} {r['run']} {r['date']}: evidence {r['e_after_e']!r} vs {r['e_after_v']!r} / {r['e_after_alt']!r}")
        if ps is not None:
            rows = []
            for p in books:
                for bps in COSTS:
                    for run in RUNS:
                        for dt, nm, u in DV.sim(p, "full", "lbes", run, bps, positions=True)["positions"]:
                            rows.append(dict(book=p, cost_bps=bps, run=run, date=dt, instrument=nm, units=u))
            mine = pd.DataFrame(rows)
            ev = ps[ps["book"].isin(books) & ps["run"].isin(RUNS)].copy()
            ev["cost_bps"] = r4(ev["cost_bps"])
            t0s = {p: str(DV.V[(p, "full", "lbes")]["cal"][0].date()) for p in books}
            ev["date"] = dstr(ev["date"])
            if not (ev["date"] == ev["book"].map(t0s)).any():
                mine = mine[mine["date"] != mine["book"].map(t0s)]
            stocks_all = set(sum([DV.V[(p, "full", "lbes")]["S"] for p in books], []))
            ev["instrument"] = ev["instrument"].map(lambda x: x if (x in stocks_all or x == "GOLDBEES") else "CASH")
            mine = mine[np.abs(mine["units"]) > 0]; ev = ev[np.abs(ev["units"].astype(float)) > 0]
            compare_frames(c, mine, ev, ["book", "cost_bps", "run", "date", "instrument"], num_cols=["units"], tol=TOL, part="positions")
    run_check(C, "C-target", c_target)

    # ------------------------------------------------------------------ C-r7 (flagged days; picks the 'held' reading the NAV checks use)
    def c_r7(c):
        fl = E.get("r7_flagged_days.csv", c)
        if fl is None:
            return
        ev = fl[fl["book"].isin(books)].copy()
        ev["date"] = dstr(ev["date"])
        results = {}
        for var in R7_VARIANTS:
            mine = pd.DataFrame([r for p in books for r in DV.r7(p, var)[0]],
                                columns=["book", "isin", "stock", "date", "close_prev", "close", "move"])
            cc = Check("tmp")
            compare_frames(cc, mine, ev, ["book", "isin", "date"], num_cols=[x for x in ("close_prev", "close", "move") if x in ev.columns],
                           tol=1e-9)
            results[var] = (cc, len(mine))
        best = min(R7_VARIANTS, key=lambda v_: (results[v_][0].failed + results[v_][0].missing, R7_VARIANTS.index(v_)))
        cc, nm = results[best]
        c.compared += 1                                   # the flagged list as a whole: same number of rows (an empty list can agree)
        c.count("r7_row_count", 1, int(nm != len(ev)))
        if nm != len(ev):
            c.failed += 1; c.fail(f"r7_flagged_days.csv has {len(ev)} rows, the verifier {nm} ('held' reading {best})")
        c.compared += cc.compared + cc.missing; c.failed += cc.failed; c.missing += cc.missing
        c.worst_rel = max(c.worst_rel, cc.worst_rel); c.count("r7_flagged_days", cc.compared + cc.missing, cc.failed + cc.missing)
        if cc.first_fail:
            c.fail(cc.first_fail)
        DV.r7_variant = best
        c.notes.append(f"'held' reading that matches: {best} ({ {k: (v[0].failed + v[0].missing, v[1]) for k, v in results.items()} } = (problems, my rows)); "
                       f"evidence rows {len(ev)}; threshold |move| >= {R7_THRESHOLD}")
    run_check(C, "C-r7", c_r7)

    # ------------------------------------------------------------------ C-nav (daily NAVs and statistics)
    def c_nav(c):
        dn = E.get("daily_nav.csv", c)
        if dn is not None:
            ev = dn[dn["book"].isin(books)].copy()
            ev["cost_bps"] = r4(ev["cost_bps"]); ev["date"] = dstr(ev["date"])
            ev = ev[ev["run"].isin(RUNS + R7_RUNS)]
            rows = []
            have_r7 = set(zip(ev.loc[ev["run"].isin(R7_RUNS), "run"], ev.loc[ev["run"].isin(R7_RUNS), "cost_bps"]))
            for p in books:
                ds = [str(d.date()) for d in DV.V[(p, "full", "lbes")]["cal"]]
                for bps in COSTS:
                    for run in RUNS:
                        rows.append(pd.DataFrame(dict(book=p, date=ds, cost_bps=bps, run=run, nav=DV.sim(p, "full", "lbes", run, bps)["nav"])))
                for run in R7_RUNS:
                    for bps in sorted({b for r_, b in have_r7 if r_ == run} | {0.0, HEADLINE_COST}):
                        rows.append(pd.DataFrame(dict(book=p, date=ds, cost_bps=bps, run=run, nav=DV.sim(p, "full", "lbes", run, bps)["nav"])))
            mine = pd.concat(rows, ignore_index=True)
            compare_frames(c, mine, ev, ["book", "run", "cost_bps", "date"], num_cols=["nav"], tol=TOL, part="daily_nav")
            for p in books:
                for bps in COSTS:
                    e_ = ev[(ev["book"] == p) & (ev["run"] == "segment") & (ev["cost_bps"] == bps)].sort_values("date")
                    if len(e_):
                        c.compared += 1
                        d_ = float(rel(e_["nav"].iloc[-1], DV.sim(p, "full", "lbes", "segment", bps)["nav"][-1]))
                        c.worst_rel = max(c.worst_rel, d_)
                        c.count("end_nav", 1, int(d_ > TOL))
                        if d_ > TOL:
                            c.failed += 1; c.fail(f"end NAV of segment {p} {bps}: relative difference {d_:.3e}")
        st = E.get("stats.csv", c)
        if st is None:
            return
        st = with_window(st)
        st = st[st["book"].isin(books)].copy()
        st["cost_bps"] = r4(st["cost_bps"])
        exp = set()
        for p in books:
            for bps in COSTS:
                for kind in RUNS:
                    exp.add((p, "full", "lbes", bps, kind))
            exp.add((p, "full", "liq", HEADLINE_COST, "segment"))
            if strict or "r2" in set(st["window"]):
                exp.add((p, "r2", "lbes", HEADLINE_COST, "segment"))
            if p in R6_BOOKS:
                exp.add((p, "full_r6", "lbes", HEADLINE_COST, "segment")); exp.add((p, "full_r6", "lbes", HEADLINE_COST, "whole_book"))
            for bps in (0.0, HEADLINE_COST):
                for kind in R7_RUNS:
                    exp.add((p, "full", "lbes", bps, kind))
        have = set(zip(st["book"], st["window"], st["cash"], st["cost_bps"], st["kind"]))
        for key in sorted(exp - have):
            c.miss(f"stats.csv row {key}")
        variants_used = defaultdict(int)
        skipped = []
        for _, r in st.iterrows():
            p, w, ca, bps, kind = r["book"], r["window"], r["cash"], float(r["cost_bps"]), r["kind"]
            if (p, w, ca) not in DV.V or kind not in RUNS + R7_RUNS or (w != "full" and kind.endswith("_r7")):
                skipped.append((p, w, ca, bps, kind)); continue
            cand = []
            for var in (("a", "b") if kind == "constant_mix" else ("a",)):
                res = DV.sim(p, w, ca, kind, bps, mix_variant=var)
                s_ = stats_of(res["nav"]); s_["trades"] = len(res["trades"]); s_["cost_paid"] = sum(t["cost"] for t in res["trades"]); s_["_var"] = var
                cand.append(s_)
            if kind == "segment" and "events" in st.columns and not pd.isna(r["events"]):
                ne = len(DV.events(p, w, "rule")[0])
                c.compared += 1
                bad_e = int(float(r["events"]) not in (ne, ne - 1))
                c.count("stats_events", 1, bad_e)
                if bad_e:
                    c.failed += 1; c.fail(f"stats.csv events {r['events']} for {p} {w} {ca} {bps} vs verifier {ne} (incl. T0) / {ne-1}")
            best = None
            for cd in cand:
                bad = 0; wr = 0.0; first = None
                for col in STAT_COLS + ["trades", "cost_paid"]:
                    if col not in st.columns or col not in cd or pd.isna(r[col]):
                        continue
                    exact = col in EXACT_COLS
                    d_ = float(abs(float(r[col]) - cd[col])) if exact else float(rel(float(r[col]), cd[col]))
                    if not exact:
                        wr = max(wr, d_)
                    if d_ > (0.0 if exact else TOL):
                        bad += 1; first = first or f"{col}: evidence {float(r[col])!r} vs verifier {cd[col]!r}"
                if best is None or bad < best[0]:
                    best = (bad, wr, cd.get("_var"), first)
                if bad == 0:
                    break
            c.compared += 1
            c.worst_rel = max(c.worst_rel, best[1])
            c.count("stats", 1, int(best[0] > 0))
            if kind == "constant_mix":
                variants_used[best[2]] += int(best[0] == 0)
            if best[0] > 0:
                c.failed += 1; c.fail(f"stats.csv row {p} {w} {ca} {bps} {kind}: {best[0]} column(s) differ ({best[3]})")
        if variants_used:
            c.notes.append(f"constant_mix average-share variants that matched (a = the rule's path at the same cost, b = at 0 cost): {dict(variants_used)}")
        if skipped:
            c.notes.append(f"{len(skipped)} stats.csv rows of a kind / window / cash the verifier does not derive, not compared: {skipped[:6]}")
        c3 = {}
        for p in books:
            for w in windows_of(p):
                a = stats_of(DV.sim(p, w, "lbes", "segment", HEADLINE_COST)["nav"])["cagr"]
                b = stats_of(DV.sim(p, w, "lbes", "whole_book", HEADLINE_COST)["nav"])["cagr"]
                c3[f"{p}|{w}"] = a - b
        c.notes.append("C3 (rule minus whole book, CAGR, 20.8 bps, lbes): " + json.dumps({k: round(v, 6) for k, v in c3.items()}))
        DV.c3 = c3
    run_check(C, "C-nav", c_nav)

    # ------------------------------------------------------------------ C-always-in (no G0 before 2019: my always-in against the engine's parent run)
    def c_always_in(c):
        dn = E.get("daily_nav.csv", c)
        if dn is None:
            return
        ev = dn[(dn["book"].isin(books)) & (dn["run"] == "parent") & (np.abs(dn["cost_bps"].astype(float)) < 1e-12)].copy()
        ev["date"] = dstr(ev["date"])
        mine = pd.concat([pd.DataFrame(dict(book=p, date=[str(d.date()) for d in DV.V[(p, "full", "lbes")]["cal"]],
                                            nav=DV.sim(p, "full", "lbes", "parent", 0.0)["nav"])) for p in books], ignore_index=True)
        compare_frames(c, mine, ev[["book", "date", "nav"]], ["book", "date"], num_cols=["nav"], tol=TOL, part="parent_0bps")
        for p in books:
            nv = DV.sim(p, "full", "lbes", "parent", 0.0)["nav"]
            c.notes.append(f"{p}: always-in (rebuilt, no published NAV) end NAV {nv[-1]:.6f}, CAGR {stats_of(nv)['cagr']:.4%}")
    run_check(C, "C-always-in", c_always_in)

    # ------------------------------------------------------------------ C-regress
    run_check(C, "C-regress", lambda c: regress_check(c, DV, REG, E, run_name))

    # ------------------------------------------------------------------ C-standin
    def c_standin(c):
        for p in books:
            B = DV.B[p]
            mine_d18 = [str(d.date()) for d, on in zip(B["cal"], B["on_d18"]) if not on]
            mine_g = [str(d.date()) for d, on in zip(B["cal"], B["own_gold_bar"]) if not on]
            for nm, got, exp in (("no D18 bar", mine_d18, STANDIN_D18), ("no GOLDBEES bar", mine_g, STANDIN_GOLD)):
                c.compared += 1; c.count("standin_sessions", 1, int(got != exp))
                if got != exp:
                    c.failed += 1; c.fail(f"{p}: sessions with {nm} {got}, T12.md section 3 step 1 says {exp}")
            raw = [t["date"] for t in DV.sim(p, "full", "lbes", "segment", HEADLINE_COST)["trades"] if t["raw_gold_fill"]]
            c.notes.append(f"{p}: rule trades (20.8 bps) whose GOLDBEES leg used the raw OHLC4 (no MCX range): {raw}")
        au = E.get("audit.json", c if strict else None)
        if au is not None:
            sd = au.get("standins")
            c.compared += 1
            txt = json.dumps(sd) if sd is not None else ""
            bad = sd is None or not all(d in txt for d in STANDIN_D18 + STANDIN_GOLD)
            c.count("audit_standins", 1, int(bad))
            if bad:
                c.failed += 1; c.fail(f"audit.json 'standins' missing or does not name {STANDIN_D18 + STANDIN_GOLD}")
        c.notes.append(f"sessions without an MCX range in the window: {[str(d.date()) for d, r_ in zip(DV.cal, DV.MK['raw']) if r_]}")
    run_check(C, "C-standin", c_standin)

    # ------------------------------------------------------------------ the draws: shared preparation
    drops_all = E.get("draw_drops.npz")
    labels_all = E.get("draw_labels.npz")
    es_all = E.get("event_stocks.csv")
    draws_df = E.get("draws.csv")
    prep = {}

    def dec_sell(p, window, ev, b):
        d = DV.dec[(p, window)]
        return d[["sign_Nifty100", "sign_MC100", "sign_SC100"][b]].iloc[ev["j"]] == "SELL"

    def prepare(p, window):
        """Row map of the engine's event_stocks rows of (book, window) to my rows, and per-row arrays from MY derivation."""
        if (p, window) in prep:
            return prep[(p, window)]
        evd = with_window(es_all)
        evd = evd[(evd["book"] == p) & (evd["window"] == window)].copy()
        evd["trade_date"] = dstr(evd["trade_date"])
        mine = SETS["stocks"][(p, window)].reset_index(drop=True)
        mine_t = dstr(mine["trade_date"])
        key_to_i = {(d, i): k for k, (d, i) in enumerate(zip(mine_t.values, mine["isin"].values))}
        rmap = np.array([key_to_i.get((d, i), -1) for d, i in zip(evd["trade_date"].values, evd["isin"].values)], dtype=int)
        ok = len(rmap) == len(mine) and (rmap >= 0).all() and len(set(rmap.tolist())) == len(mine)
        evs, _ = DV.events(p, window, "rule")
        res = dict(ok=ok, rmap=rmap, mine=mine, evs=evs, V=DV.V[(p, window, "lbes")], E_n=len(evs))
        if ok:
            ev_of_row = mine["event_no"].values.astype(int)[rmap]
            w_row = mine["listed_weight"].values.astype(float)[rmap]
            erows = SETS["events"][(p, window)]
            res.update(ev_of_row=ev_of_row, w_row=w_row, Dw=erows["dropped_weight"].values.astype(float),
                       tau=erows["tau"].values.astype(float), n_held=erows["n_held"].values.astype(int),
                       n_cnt=erows[["n_large", "n_mid", "n_small"]].values.astype(int),
                       sell=np.array([[dec_sell(p, window, ev, b) for b in range(3)] for ev in evs]))
            E_n = len(evs)
            res["Wmat"] = np.zeros((len(rmap), E_n)); res["Wmat"][np.arange(len(rmap)), ev_of_row] = w_row
            res["Cmat"] = np.zeros((len(rmap), E_n)); res["Cmat"][np.arange(len(rmap)), ev_of_row] = 1.0
        prep[(p, window)] = res
        return res

    def types_of(window):
        return ("N4.6",) if window == "full_r6" else ("N4.6", "N4.8")

    # ------------------------------------------------------------------ C-count (brute force over all 2^n subsets)
    def c_count(c):
        ev = E.get("events.csv", c)
        ct = E.get("count_table.json", c)
        evw = with_window(ev) if ev is not None else None
        for p, window in my_windows(set(evw["window"]) if evw is not None else None):
            V = DV.V[(p, window, "lbes")]
            evs, _ = DV.events(p, window, "rule")
            frame = SETS["events"][(p, window)]
            recs = count_records(find_book(ct, p), window) if ct is not None else []
            for no, e in enumerate(evs):
                w = V["Wn"][e["k"]][e["held"]]
                num = event_numbers(V, e)
                if len(w) > 16:
                    c.miss(f"{p} {window} event {no}: n_held {len(w)} > 16"); continue
                A, tau, near = allowed_subsets(w, num["dropped_weight"])
                rule_mask = mask_of(~e["kept"])
                c.compared += 1
                inA = rule_mask in set(A.tolist())
                c.count("rule_subset_in_A", 1, int(not inA))
                if not inA:
                    c.failed += 1; c.fail(f"{p} {window} event {no}: the rule's own drop set is not among the {len(A)} allowed subsets (V5c)")
                if near < 1e-9:
                    c.notes.append(f"{p} {window} event {no}: a subset lies within 1e-9 of the tau boundary (|diff - tau| = {near:.2e})")
                if evw is not None and "n_allowed_subsets" in evw.columns:
                    row = evw[(evw["book"] == p) & (evw["window"] == window) & (dstr(evw["trade_date"]) == str(V["cal"][e["idx"]].date()))]
                    c.compared += 1
                    bad = (len(row) != 1) or (int(float(row["n_allowed_subsets"].iloc[0])) != len(A))
                    c.count("events_csv_n_allowed", 1, int(bad))
                    if bad:
                        c.failed += 1; c.fail(f"{p} {window} event {no}: events.csv n_allowed_subsets {row['n_allowed_subsets'].tolist()} vs brute force {len(A)}")
                if ct is not None:
                    if no < len(recs):
                        rec = recs[no]
                        k = first_key(rec, [r"allowed", r"n_subsets", r"^count"])
                        c.compared += 1
                        bad = k is None or int(str(rec[k])) != len(A)
                        c.count("count_table", 1, int(bad))
                        if bad:
                            c.failed += 1; c.fail(f"{p} {window} event {no}: count_table.json {rec.get(k) if k else None!r} vs brute force {len(A)}")
                    else:
                        c.miss(f"count_table.json record for {p} {window} event {no}")
            n_part = int(frame["partial"].sum())
            if ct is not None:
                ent = find_book(ct, p)
                if isinstance(ent, dict):
                    sub = ent.get(window) if isinstance(ent.get(window), dict) else ent
                    k = first_key(sub, [r"partial"])
                    if k is not None and not isinstance(sub[k], (dict, list)):
                        c.compared += 1
                        c.count("n_partial", 1, int(int(sub[k]) != n_part))
                        if int(sub[k]) != n_part:
                            c.failed += 1; c.fail(f"{p} {window}: count_table.json events with partial {sub[k]} vs {n_part}")
            c.notes.append(f"{p} {window}: events {len(evs)}, with 0 < equity share < 1: {n_part}{'  (BELOW the reportability gate of 6)' if n_part < 6 else ''}")
    run_check(C, "C-count", c_count)

    # ------------------------------------------------------------------ C-draws (structure of every draw)
    def c_draws(c):
        if drops_all is None:
            c.miss("evidence file draw_drops.npz"); return
        if es_all is None:
            c.miss("evidence file event_stocks.csv"); return
        wins = set(with_window(es_all)["window"])
        for p, window in my_windows(wins):
            pr = prepare(p, window)
            if not pr["ok"]:
                c.miss(f"{p} {window}: the engine's event_stocks rows do not map one-to-one to the verifier's (see C-tag)"); continue
            E_n = pr["E_n"]
            R = len(pr["rmap"])
            k46 = f"{p}|{window}|N4.6"
            if k46 in drops_all:
                dr = drops_all[k46]
                if dr.ndim != 2 or dr.shape[1] != R:
                    c.failed += 1; c.fail(f"{k46}: shape {dr.shape} but event_stocks has {R} rows")
                else:
                    c.compared += dr.size
                    bad_val = int(((dr != 0) & (dr != 1)).sum())
                    c.count("N4.6_values_01", dr.size, bad_val); c.failed += bad_val
                    dropw = dr.astype(float) @ pr["Wmat"]
                    dropn = dr.astype(float) @ pr["Cmat"]
                    diff = np.abs(dropw - pr["Dw"][None, :])
                    bad = diff > pr["tau"][None, :] * (1 + 1e-9) + 1e-12
                    c.compared += bad.size
                    c.count("N4.6_dropped_weight_within_tau", bad.size, int(bad.sum())); c.failed += int(bad.sum())
                    if bad.any():
                        di, ei = np.argwhere(bad)[0]
                        c.fail(f"{k46} draw {di} event {ei}: dropped weight {dropw[di, ei]:.6f} vs rule {pr['Dw'][ei]:.6f} (tau {pr['tau'][ei]:.6f})")
                    c.worst_rel = max(c.worst_rel, float((diff / np.maximum(pr["tau"][None, :], 1e-300)).max()))
                    none = pr["Dw"] == 0
                    all_drop = np.array([bool((~e["kept"]).all()) and len(e["kept"]) > 0 for e in pr["evs"]])
                    b1 = (dropn[:, none] != 0); b2 = (dropn[:, all_drop] != pr["n_held"][None, all_drop])
                    c.compared += b1.size + b2.size
                    c.count("N4.6_drops_nothing_or_everything", b1.size + b2.size, int(b1.sum() + b2.sum())); c.failed += int(b1.sum() + b2.sum())
                    if b1.any() or b2.any():
                        c.fail(f"{k46}: a draw does not drop nothing / everything where the rule does")
                    c.notes.append(f"{k46}: {dr.shape[0]} draws x {E_n} events checked")
            else:
                c.miss(f"draw_drops.npz key {k46}")
            if "N4.8" not in types_of(window):
                continue
            k48 = f"{p}|{window}|N4.8"
            if k48 not in drops_all:
                c.miss(f"draw_drops.npz key {k48}"); continue
            dr = drops_all[k48]
            if labels_all is None or k48 not in labels_all:
                c.miss(f"draw_labels.npz key {k48}"); continue
            lb = labels_all[k48]
            if dr.shape != lb.shape or dr.shape[1] != R:
                c.failed += 1; c.fail(f"{k48}: shapes {dr.shape} / {lb.shape} vs {R} rows"); continue
            nd = dr.shape[0]
            tot = 0; badn = 0
            for lab in range(3):
                cnt = (lb == lab).astype(float) @ pr["Cmat"]
                badn += int((cnt != pr["n_cnt"][:, lab][None, :]).sum()); tot += cnt.size
            c.compared += tot; c.failed += badn; c.count("N4.8_label_counts", tot, badn)
            if badn:
                c.fail(f"{k48}: the number of stocks per label differs from the rule's n_large, n_mid, n_small at {badn} draw-events")
            bad_lab = int((lb > 2).sum()); c.failed += bad_lab; c.compared += lb.size; c.count("N4.8_label_values", lb.size, bad_lab)
            sell_row = pr["sell"][pr["ev_of_row"][None, :], np.clip(lb, 0, 2)]
            badd = int((sell_row.astype(np.uint8) != dr).sum())
            c.compared += dr.size; c.failed += badd; c.count("N4.8_drop_iff_label_SELL", dr.size, badd)
            if badd:
                c.fail(f"{k48}: a stock is dropped although its label's signal is BUY (or kept although SELL) in {badd} cells")
            isin_row = pd.factorize(pr["mine"]["isin"].values[pr["rmap"]])[0]
            nI = int(isin_row.max()) + 1
            badp = 0
            for dd in range(nd):
                M = np.full((E_n, nI), np.nan)
                M[pr["ev_of_row"], isin_row] = lb[dd]
                diffm = np.where(np.isnan(M[:, :, None] - M[:, None, :]), 0, M[:, :, None] - M[:, None, :])
                badp += int(((diffm > 0).any(axis=0) & (diffm < 0).any(axis=0)).sum() // 2)
            c.compared += nd * E_n; c.failed += badp; c.count("N4.8_persistent_order", nd * E_n, badp)
            if badp:
                c.fail(f"{k48}: {badp} ISIN pairs change their relative order between events within a draw (labels are not from one persistent score)")
            c.notes.append(f"{k48}: {nd} draws x {E_n} events checked")
        if draws_df is None:
            c.miss("evidence file draws.csv"); return
        dd = with_window(draws_df)
        for (p, window, typ), g in dd.groupby(["book", "window", "draw_type"]):
            if p not in books:
                continue
            key = f"{p}|{window}|{typ}"
            if key not in drops_all or (p, window) not in SETS["stocks"]:
                continue
            pr = prepare(p, window)
            if not pr["ok"]:
                continue
            mean_w = (drops_all[key].astype(float) @ pr["Wmat"]).mean(axis=1)
            ids = g["draw_id"].astype(int).values
            ok_ids = ids < len(mean_w)
            c.compared += int(ok_ids.sum()) * 2
            if "mean_dropped_weight" in g.columns:
                d_ = rel(g["mean_dropped_weight"].astype(float).values[ok_ids], mean_w[ids[ok_ids]])
                badc = int((d_ > TOL).sum()); c.failed += badc; c.count("draws_csv_mean_dropped_weight", int(ok_ids.sum()), badc)
                c.worst_rel = max(c.worst_rel, float(d_.max()) if len(d_) else 0.0)
                if badc:
                    c.fail(f"draws.csv {key}: mean_dropped_weight differs from the saved drops in {badc} rows")
            if "n_events" in g.columns:
                badn = int((g["n_events"].astype(float).values[ok_ids] != pr["E_n"]).sum()); c.failed += badn
                c.count("draws_csv_n_events", int(ok_ids.sum()), badn)
                if badn:
                    c.fail(f"draws.csv {key}: n_events != the rule's {pr['E_n']} in {badn} rows")
            if (~ok_ids).any():
                c.failed += int((~ok_ids).sum()); c.fail(f"draws.csv {key}: draw ids beyond the saved array")
        if strict:
            for p, window in my_windows():
                for typ in types_of(window):
                    key = f"{p}|{window}|{typ}"
                    c.compared += 1
                    if key in drops_all and drops_all[key].shape[0] != 2000:
                        c.failed += 1; c.fail(f"{key}: {drops_all[key].shape[0]} draws, the headline run needs 2,000")
        else:
            c.notes.append(f"run '{run_name}': draw counts per key not required to be 2,000 (only the headline run is)")
    run_check(C, "C-draws", c_draws)

    # ------------------------------------------------------------------ C-draw-seed (information: the saved N4.6 draws are the seeds' draws)
    def c_draw_seed(c):
        if drops_all is None or es_all is None:
            return
        for p in books:
            bi = BOOKS.index(p)
            for window in windows_of(p):
                key = f"{p}|{window}|N4.6"
                if key not in drops_all or (p, window) not in SETS["stocks"]:
                    continue
                pr = prepare(p, window)
                if not pr["ok"]:
                    continue
                info = event_infos(DV, p, window)
                arr = drops_all[key]
                mine = pr["mine"]
                row_of = {(td, isn): r for r, (td, isn) in enumerate(zip(dstr(mine["trade_date"]).values[pr["rmap"]], mine["isin"].values[pr["rmap"]]))}
                V = pr["V"]
                bad = 0
                ids = list(range(min(20, arr.shape[0])))
                for d in ids:
                    masks = n46_draw(info, d, bi)
                    for e, inf, mk in zip(pr["evs"], info, masks):
                        td = str(V["cal"][e["idx"]].date())
                        for k, isn in enumerate(inf["isins"]):
                            bad += int(arr[d, row_of[(td, isn)]] != ((mk >> k) & 1))
                c.compared += len(ids)
                c.failed += int(bad > 0)
                c.count(f"N4.6_seed_replay_{window}", len(ids), int(bad > 0))
                if bad:
                    c.fail(f"{key}: the first {len(ids)} saved draws differ from the seed [15, 7, draw_id, book_no] replay in {bad} cells")
        c.notes.append("information only: replays default_rng([15, 7, draw_id, book_no]) for the first 20 N4.6 draws of every window")
    run_check(C, "C-draw-seed", c_draw_seed, gate=False)

    # ------------------------------------------------------------------ C-draw-nav
    curves = E.get("draw_curves_20.8.npz")

    def kept_from_drops(p, window, drow):
        pr = prepare(p, window)
        V = pr["V"]
        mine = pr["mine"]
        by_ev = defaultdict(list)
        for r_, mi in enumerate(pr["rmap"]):
            by_ev[int(pr["ev_of_row"][r_])].append((r_, mi))
        isin_to_si = {isn: k for k, isn in enumerate(V["isins"])}
        evs = []
        for no, e in enumerate(pr["evs"]):
            kf = np.zeros(len(V["S"]), dtype=bool)
            for r_, mi in by_ev[no]:
                kf[isin_to_si[mine["isin"].iloc[mi]]] = (drow[r_] == 0)
            e2 = dict(e); e2["kfull"] = kf
            evs.append(e2)
        return evs

    def c_draw_nav(c):
        if drops_all is None or draws_df is None:
            E.get("draw_drops.npz", c); E.get("draws.csv", c); return
        dd = with_window(draws_df).copy()
        dd["cost_bps"] = r4(dd["cost_bps"])
        statcols = [x for x in STAT_COLS + ["trades", "cost_paid"] if x in dd.columns]
        configs = [("full", "lbes", HEADLINE_COST, "headline"), ("full", "lbes", 0.0, "extra"), ("full", "lbes", 50.0, "extra"),
                   ("full", "liq", HEADLINE_COST, "extra"), ("r2", "lbes", HEADLINE_COST, "extra"), ("full_r6", "lbes", HEADLINE_COST, "extra")]
        nsim = 0
        for p in books:
            for window, cash, bps, tag in configs:
                if window not in windows_of(p):
                    continue
                for typ in types_of(window):
                    key = f"{p}|{window}|{typ}"
                    if key not in drops_all:
                        continue
                    pr = prepare(p, window)
                    if not pr["ok"]:
                        continue
                    pool = drops_all[key].shape[0]
                    ids = sample_ids(p, typ, pool) if tag == "headline" else list(range(min(3, pool)))
                    V = DV.V[(p, window, cash)]
                    for did in ids:
                        res = simulate(V, kept_from_drops(p, window, drops_all[key][did]), bps)
                        nsim += 1
                        st = stats_of(res["nav"]); st["trades"] = len(res["trades"]); st["cost_paid"] = float(sum(t["cost"] for t in res["trades"]))
                        row = dd[(dd["book"] == p) & (dd["window"] == window) & (dd["cash"] == cash) & (dd["cost_bps"] == bps) &
                                 (dd["draw_type"] == typ) & (dd["draw_id"].astype(int) == did)]
                        if len(row) != 1:
                            c.miss(f"draws.csv row {p} {window} {cash} {bps} {typ} {did}"); continue
                        bad = 0; first = None
                        for col in statcols:
                            exact = col in EXACT_COLS
                            d_ = abs(float(row[col].iloc[0]) - st[col]) if exact else float(rel(float(row[col].iloc[0]), st[col]))
                            if not exact:
                                c.worst_rel = max(c.worst_rel, d_)
                            if d_ > (0 if exact else TOL):
                                bad += 1; first = first or f"{col}: evidence {float(row[col].iloc[0])!r} vs verifier {st[col]!r}"
                        c.compared += 1; c.failed += int(bad > 0); c.count(f"draw_stats_{tag}", 1, int(bad > 0))
                        if bad:
                            c.fail(f"{p} {window} {cash} {bps} {typ} draw {did}: {bad} statistic(s) differ ({first})")
                        if tag == "headline":
                            if curves is None:
                                c.miss("evidence file draw_curves_20.8.npz"); continue
                            ck = f"{p}|{typ}_{did}"
                            if ck not in curves:
                                c.miss(f"draw_curves_20.8.npz key {ck}"); continue
                            cv = curves[ck].astype(float)
                            d_ = rel(cv, res["nav"]) if len(cv) == len(res["nav"]) else np.array([np.inf])
                            c.compared += len(d_); badc = int((d_ > TOL_CURVE).sum()); c.failed += badc; c.count("draw_curves", len(d_), badc)
                            if badc:
                                c.fail(f"{ck}: daily NAV differs from the re-simulation (max relative {d_.max():.2e}, float32 limit {TOL_CURVE:g})")
        c.notes.append(f"{nsim} draw re-simulations (first 20 and 20 random draws per book and null at 20.8 bps, full, LBES; draws 0-2 at 0 / 50 bps, LIQUIDCASE, r2, full_r6)")
    run_check(C, "C-draw-nav", c_draw_nav)

    # ------------------------------------------------------------------ C-oracle
    def c_oracle(c):
        co = E.get("controls_oracle.json", c if strict else None)
        dd = with_window(draws_df) if draws_df is not None else None
        for p in books:
            cg = {v_: oracle_choice(DV, p, v_)[1] for v_ in ("fill", "close")}
            if co is None:
                c.compared += 1
            d_ = None
            if dd is not None:
                g = dd[(dd["book"] == p) & (dd["window"] == "full") & (dd["cash"] == "lbes") & (dd["draw_type"] == "N4.6") & (np.abs(dd["cost_bps"].astype(float) - HEADLINE_COST) < 1e-9)]
                if len(g):
                    d_ = {v_: pct_and_p(cg[v_], g["cagr"].values, True)[0] for v_ in cg}
            c.notes.append(f"{p}: oracle CAGR {cg['fill']:.6f} (fill-to-fill) / {cg['close']:.6f} (close-to-close)" + (f"; percentile against the evidence's N4.6 draws {d_['fill']:.2f} / {d_['close']:.2f}" if d_ else ""))
            if co is None:
                continue
            ent = find_book(co, p)
            if not isinstance(ent, dict):
                c.miss(f"controls_oracle.json entry for {p}"); continue
            kc = first_key(ent, [r"^oracle_cagr$", r"cagr"])
            kp = first_key(ent, [r"pct", r"percentile"])
            if kc is None:
                c.miss(f"controls_oracle.json {p}: no CAGR field"); continue
            c.compared += 1
            best_v = min(cg, key=lambda v_: abs(cg[v_] - float(ent[kc])))
            dif = float(rel(float(ent[kc]), cg[best_v]))
            c.worst_rel = max(c.worst_rel, dif)
            c.count("oracle_cagr", 1, int(dif > TOL))
            if dif > TOL:
                c.failed += 1; c.fail(f"{p}: oracle CAGR evidence {float(ent[kc])!r} vs verifier {cg['fill']!r} (fill) / {cg['close']!r} (close)")
            else:
                c.notes.append(f"{p}: the evidence's oracle matches the '{best_v}' return convention")
            if kp is not None and d_ is not None:
                c.compared += 1
                dp = abs(float(ent[kp]) - d_[best_v])
                c.count("oracle_percentile", 1, int(dp > 1e-6))
                if dp > 1e-6:
                    c.failed += 1; c.fail(f"{p}: oracle percentile evidence {float(ent[kp])!r} vs verifier {d_[best_v]!r}")
    run_check(C, "C-oracle", c_oracle)

    # ------------------------------------------------------------------ C-percentile
    DV.percentiles = []

    def c_percentile(c):
        if draws_df is None:
            E.get("draws.csv", c); return
        dd = with_window(draws_df).copy(); dd["cost_bps"] = r4(dd["cost_bps"])
        rows = []
        for (p, w, ca, cst, typ), g_ in dd.groupby(["book", "window", "cash", "cost_bps", "draw_type"]):
            if p not in books or (p, w, ca) not in DV.V:
                continue
            mine = stats_of(DV.sim(p, w, ca, "segment", float(cst))["nav"])
            row = dict(book=p, window=w, cash=ca, cost_bps=float(cst), draw_type=typ, n_draws=len(g_))
            for stat, hb in STAT_DIR.items():
                if stat not in g_.columns:
                    continue
                pc, pv = pct_and_p(mine[stat], g_[stat].values, hb)
                pc2, pv2 = pct_and_p_loop(mine[stat], g_[stat].values, hb)
                c.compared += 1
                d_ = max(abs(pc - pc2), abs(pv - pv2))
                c.worst_rel = max(c.worst_rel, d_)
                if d_ > 1e-9:
                    c.failed += 1; c.fail(f"{p} {w} {ca} {cst} {typ} {stat}: vectorised {pc!r}/{pv!r} vs loop {pc2!r}/{pv2!r}")
                row[f"{stat}_pctile"] = pc; row[f"{stat}_p"] = pv
            sd = float(np.std(g_["cagr"].astype(float).values, ddof=1)) if len(g_) > 1 else float("nan")
            row["null_sd_cagr"] = sd; row["mde_c1"] = 2.8 * sd
            rows.append(row)
        DV.percentiles = rows
        c.notes.append("worst_rel here is the largest difference between the verifier's two own percentile implementations")
        cand = [E.dir / "analysis.log", E.dir.parent / "analysis.log", E.dir.parent.parent / "analysis.log"]
        logp = next((x for x in cand if x.exists()), None)
        if logp is None:
            c.notes.append("analysis.log not found beside the evidence (written in Step 5); no printed percentile compared")
            return
        nums = set(re.findall(r"-?\d+\.\d+", logp.read_text(encoding="utf-8", errors="replace")))
        for r in rows:
            if r["window"] == "full" and r["cash"] == "lbes" and abs(r["cost_bps"] - HEADLINE_COST) < 1e-9:
                for stat in ("cagr", "max_dd"):
                    v_ = r.get(f"{stat}_pctile")
                    if v_ is None:
                        continue
                    c.compared += 1
                    if not any(f"{v_:.{nd}f}" in nums for nd in (1, 2)):
                        c.failed += 1; c.fail(f"{r['book']} {r['draw_type']} {stat} percentile {v_:.2f} not printed in {logp.name}")
        c.notes.append(f"read {logp}")
    run_check(C, "C-percentile", c_percentile)

    # ------------------------------------------------------------------ C-pit
    def c_pit(c):
        tot = defaultdict(int)
        for p in books:
            for window in windows_of(p):
                for mode in ("rule", "tied"):
                    _, pit = DV.events(p, window, mode)
                    if mode == "tied":
                        for k in ("decisions_checked", "decision_violations", "sc100_rows_checked", "sc100_violations", "trades_checked", "trade_violations"):
                            tot[k] += pit[k]
                    else:
                        for k, v_ in pit.items():
                            tot[k] += v_
        for k in ("decisions_checked", "tags_checked", "trades_checked", "sc100_rows_checked"):
            c.compared += tot[k]
            if tot[k] <= 0:
                c.failed += 1; c.fail(f"{k} = 0: V2 needs a count > 0")
        for k in ("decision_violations", "tag_violations", "trade_violations", "sc100_violations"):
            c.failed += tot[k]
            if tot[k]:
                c.fail(f"{k} = {tot[k]}")
        c.notes.append("verifier's own counts: " + json.dumps(dict(tot)) + " (T0 tags are read as of T0 itself)")
        es = E.get("event_stocks.csv")
        if es is not None:
            a = pd.to_datetime(es["tag_snapshot"], errors="coerce"); b = pd.to_datetime(es["info_date"], errors="coerce")
            ok = a.notna()
            c.compared += int(ok.sum()); bad = int((a[ok] > b[ok]).sum()); c.failed += bad
            c.count("evidence_tag_snapshot_le_info_date", int(ok.sum()), bad)
            if bad:
                c.fail(f"event_stocks.csv: {bad} rows use a tag snapshot dated after the information date")
            t = pd.to_datetime(es["trade_date"], errors="coerce")
            c.compared += int(b.notna().sum()); bad = int((b > t).sum()); c.failed += bad
            c.count("evidence_info_date_le_trade_date", int(b.notna().sum()), bad)
            if bad:
                c.fail(f"event_stocks.csv: {bad} rows have an information date after the trade date")
        dc = E.get("decisions.csv")
        if dc is not None:
            for col in ("label_Nifty100", "label_MC100", "label_SC100"):
                if col in dc.columns:
                    a = pd.to_datetime(dc[col], errors="coerce"); b = pd.to_datetime(dc["decision_date"], errors="coerce")
                    c.compared += len(dc); bad = int((a > b).sum()); c.failed += bad
                    c.count("evidence_master_label_le_decision", len(dc), bad)
                    if bad:
                        c.fail(f"decisions.csv {col}: {bad} rows use a Master row dated after the decision date")
            if "label_SC100" in dc.columns:
                a = pd.to_datetime(dc["label_SC100"], errors="coerce")
                c.compared += len(dc); bad = int((a < SC100_SIGNAL_FROM).sum()); c.failed += bad
                c.count("evidence_sc100_row_usable", len(dc), bad)
                if bad:
                    c.fail(f"decisions.csv: {bad} rows read a Smallcap 100 Master row dated before {SC100_SIGNAL_FROM.date()} (rule 7)")
            tdv = pd.to_datetime(dc["trade_date"], errors="coerce"); dcd = pd.to_datetime(dc["decision_date"], errors="coerce")
            okt = tdv.notna()
            c.compared += int(okt.sum()); bad = int((tdv[okt] <= dcd[okt]).sum()); c.failed += bad
            c.count("evidence_trade_after_decision", int(okt.sum()), bad)
            if bad:
                c.fail(f"decisions.csv: {bad} rows trade on or before the decision date")
    run_check(C, "C-pit", c_pit)
    return C


def tag_panel_check(DV):
    """Information only: the D23b panel's ranks against my own ranking of the raw market caps (D20b for 2013-12 -> 2017-12, D20 for 2018;
    ordinary shares, market cap descending, ties by quote_id, null market cap not ranked), on every snapshot dated up to END."""
    out = dict(snapshots=0, rows=0, rank_mismatches=0, band_column_mismatches=0)
    pn = DV.tagger.panel
    for f in (F_D20B, F_D20):
        raw = pd.read_csv(rd(f, gate_only=True), usecols=["date", "quote_id", "mcap", "instrument_class"], **READ_KW)
        raw["date"] = pd.to_datetime(raw["date"])
        raw = raw[(raw["instrument_class"] == "ordinary") & (raw["date"] <= END)]
        for d, g in raw.groupby("date"):
            g = g[g["mcap"].notna()].copy()
            g["q"] = g["quote_id"].astype(np.int64)
            g = g.sort_values(["mcap", "q"], ascending=[False, True])
            g["r"] = np.arange(1, len(g) + 1)
            pg = pn[pn["date"] == d]
            j = g.merge(pg, left_on="q", right_on="quote_id", how="outer", indicator=True)
            out["snapshots"] += 1; out["rows"] += len(j)
            out["rank_mismatches"] += int((j["_merge"] != "both").sum() + (j.loc[j["_merge"] == "both", "r"] != j.loc[j["_merge"] == "both", "rank"]).sum())
    out["band_column_mismatches"] = int((pn["rank"].map(rank_band) != pn["band"]).sum())
    return out


# ----------------------------------------------------------------------------------------
# reporting, self-test and main
# ----------------------------------------------------------------------------------------
def summarise(C):
    gate_fail = sum(c.failed + c.missing for c in C.values() if c.gate)
    gate_compared = sum(c.compared for c in C.values() if c.gate)
    return gate_compared, gate_fail


def print_table(C, title):
    print(f"\n=== {title} ===")
    print(f"{'check':14s} {'compared':>10s} {'failed':>8s} {'missing':>8s} {'worst':>10s}  gate")
    for c in C.values():
        print(f"{c.name:14s} {c.compared:10d} {c.failed:8d} {c.missing:8d} {c.worst_rel:10.2e}  {'yes' if c.gate else 'info'}")
        if c.first_fail:
            print(f"    first problem: {c.first_fail}")


def make_corruption(kind, E, dst, books):
    """Write ONE deliberately corrupted evidence file into dst (the rest is read through the fallback). Returns (info, checks that must fail)."""
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True)
    p0 = books[0]
    if kind == "flip_tag":
        es = E.get("event_stocks.csv").copy()
        r = int(len(es) // 3)
        es.loc[r, "band"] = {"Large": "Small and below", "Mid": "Large", "Small and below": "Mid"}[es.loc[r, "band"]]
        es.to_csv(dst / "event_stocks.csv", index=False)
        return dict(file="event_stocks.csv", row=r, column="band"), ["C-tag"]
    if kind == "change_target_weight":
        es = E.get("event_stocks.csv").copy()
        r = int(len(es) // 2)
        es.loc[r, "listed_weight"] = float(es.loc[r, "listed_weight"]) * 1.05
        es.to_csv(dst / "event_stocks.csv", index=False)
        return dict(file="event_stocks.csv", row=r, column="listed_weight x 1.05"), ["C-tag"]
    if kind == "change_position":
        ps = E.get("positions.csv").copy()
        r = int(len(ps) // 2)
        ps.loc[r, "units"] = float(ps.loc[r, "units"]) * 1.01
        ps.to_csv(dst / "positions.csv", index=False)
        return dict(file="positions.csv", row=r, column="units x 1.01"), ["C-target"]
    if kind == "scale_nav":
        dn = E.get("daily_nav.csv").copy()
        m = (dn["run"] == "segment") & (np.abs(dn["cost_bps"].astype(float) - HEADLINE_COST) < 1e-9) & (dn["book"] == p0)
        dn.loc[m, "nav"] = dn.loc[m, "nav"].astype(float) * 1.001
        dn.to_csv(dst / "daily_nav.csv", index=False)
        return dict(file="daily_nav.csv", rows=int(m.sum()), what=f"{p0} segment 20.8 bps x 1.001"), ["C-nav"]
    if kind == "delete_event":
        ev = E.get("events.csv").copy()
        r = int(len(ev) // 2)
        ev = ev.drop(index=r)
        ev.to_csv(dst / "events.csv", index=False)
        return dict(file="events.csv", row=r), ["C-events"]
    if kind == "move_drop":
        dr = E.get("draw_drops.npz")
        es = with_window(E.get("event_stocks.csv"))
        key = f"{p0}|full|N4.6"
        sub = es[(es["book"] == p0) & (es["window"] == "full")].reset_index(drop=True)
        arr = dr[key].copy()
        w = sub["listed_weight"].astype(float).values
        for td, g in sub.groupby("trade_date"):
            if len(g) < 3:
                continue
            idx = g.index.values
            tau = 0.5 * w[idx].min()
            Dw = float(g[bstr(g["kept"]) == "false"]["listed_weight"].astype(float).sum())
            for i in idx:
                arr[0, i] = 1 - arr[0, i]
                if abs(float(arr[0, idx].astype(float) @ w[idx]) - Dw) > tau * 1.01 + 1e-9:
                    data = dict(dr); data[key] = arr
                    np.savez(dst / "draw_drops.npz", **data)
                    return dict(file="draw_drops.npz", key=key, draw=0, trade_date=str(td), row=int(i)), ["C-draws"]
                arr[0, i] = 1 - arr[0, i]
        raise RuntimeError("no event found for the moved-drop corruption")
    if kind == "change_r6_rank":
        rl = E.get("r6_links.csv")
        if rl is None or not len(rl):
            raise RuntimeError("no r6_links.csv rows to corrupt")
        rl = rl.copy()
        rl.loc[0, "linked_rank"] = int(rl.loc[0, "linked_rank"]) + 7
        rl.to_csv(dst / "r6_links.csv", index=False)
        return dict(file="r6_links.csv", row=0, column="linked_rank + 7"), ["C-r6"]
    raise ValueError(kind)


CORRUPTIONS = ["flip_tag", "change_target_weight", "change_position", "scale_nav", "delete_event", "move_drop", "change_r6_rank"]


def run_selftest(DV, SETS, E, evdir, run_name, books, base_dir, REG):
    """C-corrupt: each corruption alone must make its relevant check fail; then all of them together make the whole verifier fail."""
    global ONLY
    results = {}
    rl = E.get("r6_links.csv")
    has_r6 = any(p in R6_BOOKS for p in books) and rl is not None and len(rl) > 0
    kinds = [k for k in CORRUPTIONS if k != "change_r6_rank" or has_r6]
    if not has_r6:
        results["change_r6_rank"] = dict(skipped=True, detected=True,
                                         note="no R6 book selected, or r6_links.csv has no rows (e.g. --r6-ids frozen: R6 re-tags nothing)")
        print("  C-corrupt change_r6_rank         -> skipped: no r6_links.csv rows to corrupt", flush=True)
    for kind in kinds:
        cdir = base_dir / f"corrupt_{kind}"
        try:
            info, must = make_corruption(kind, E, cdir, books)
        except Exception as ex:
            results[kind] = dict(error=repr(ex), detected=False)
            print(f"  C-corrupt {kind:22s} -> could not be made: {ex!r}", flush=True)
            continue
        ONLY = set(must)
        try:
            Cc = compare_all(DV, SETS, Evidence(cdir, fallback=evdir), run_name, REG)
        finally:
            ONLY = None
        nfail = {k: v.failed + v.missing for k, v in Cc.items()}
        results[kind] = dict(info=info, relevant_checks=must, failures_in_relevant_checks=nfail, detected=all(nfail.get(k, 0) > 0 for k in must))
        print(f"  C-corrupt {kind:22s} -> {must}: failures {nfail}  detected={results[kind]['detected']}", flush=True)
    cdir = base_dir / "corrupt_all"
    if cdir.exists():
        shutil.rmtree(cdir)
    cdir.mkdir(parents=True)
    o = E.get("event_stocks.csv")
    for kind in kinds:
        if results.get(kind, {}).get("error"):
            continue
        for f in (base_dir / f"corrupt_{kind}").iterdir():
            if f.name == "event_stocks.csv" and (cdir / f.name).exists():
                a = pd.read_csv(cdir / f.name, keep_default_na=False, na_values=[""]); b = pd.read_csv(f, keep_default_na=False, na_values=[""])
                a.loc[b["band"] != o["band"], "band"] = b.loc[b["band"] != o["band"], "band"]
                a.loc[b["listed_weight"] != o["listed_weight"], "listed_weight"] = b.loc[b["listed_weight"] != o["listed_weight"], "listed_weight"]
                a.to_csv(cdir / f.name, index=False)
            else:
                shutil.copy(f, cdir / f.name)
    Call = compare_all(DV, SETS, Evidence(cdir, fallback=evdir), run_name, REG)
    cc, cf = summarise(Call)
    print_table(Call, f"SELF-TEST (C-corrupt): all corruptions in one copy ({cdir})")
    all_ok = cf > 0 and all(v.get("detected") for v in results.values())
    return dict(dir=str(base_dir), corruptions=results, combined=dict(dir=str(cdir), gate_compared=cc, gate_failures=cf), detected=bool(all_ok)), Call


def choose_r2_init(DV, E):
    """--r2-init auto: the r2 initial position convention whose 20.8 bps rule end NAV matches stats.csv (drift preferred on a tie)."""
    st = E.get("stats.csv")
    if st is None or "window" not in st.columns:
        return "drift", "no stats.csv r2 row: drift (T07's convention)"
    out = {}
    for mode in ("drift", "fresh"):
        diffs = []
        for p in DV.books:
            r = st[(st["book"] == p) & (st["window"] == "r2") & (st["cash"] == "lbes") & (st["kind"] == "segment") & (np.abs(st["cost_bps"].astype(float) - HEADLINE_COST) < 1e-9)]
            if not len(r):
                continue
            B = DV.B[p]
            V = make_view(B, B["a_r2"], B["n"], "lbes", mode)
            evs, _ = derive_events(V, DV.dec[(p, "r2")], DV.tagger_for("r2"), "rule")
            diffs.append(float(rel(float(r["end_nav"].iloc[0]), simulate(V, evs, HEADLINE_COST)["nav"][-1])))
        out[mode] = max(diffs) if diffs else None
    if out["drift"] is None:
        return "drift", "no stats.csv r2 row: drift (T07's convention)"
    best = "drift" if out["drift"] <= TOL or out["drift"] <= out["fresh"] else "fresh"
    return best, f"r2 end NAV relative difference: drift {out['drift']:.2e}, fresh {out['fresh']:.2e}"


def main():
    global RETAG_SKIPPED_BASKET, R6_LINKS
    ap = argparse.ArgumentParser()
    ap.add_argument("--evidence", default=str(AA / "tests" / "T12" / "evidence" / "headline"))
    ap.add_argument("--no-selftest", action="store_true", help="skip the in-process corrupted-copy test (C-corrupt)")
    ap.add_argument("--out", default=None)
    ap.add_argument("--books", default=",".join(BOOKS))
    ap.add_argument("--r2-init", default="auto", choices=["auto", "drift", "fresh"])
    ap.add_argument("--r6-ids", default="review", choices=["review", "frozen", "literal"],
                    help="R6 quote_ids: review = the in-window listings the D20b review identified (default, the coordinator's instruction 2026-11-17, pending Manu); frozen (alias literal) = the ids T12.md section 2 R6 quotes")
    ap.add_argument("--literal-skipped-basket", action="store_true", help="DIAGNOSTIC ONLY: no re-tag on a basket that arrives while nothing is held")
    ap.add_argument("--regress-only", action="store_true", help="run C-regress only (no T12 evidence needed)")
    ap.add_argument("--corrupt-dir", default=None)
    args = ap.parse_args()
    books = [b for b in args.books.split(",") if b]
    RETAG_SKIPPED_BASKET = not args.literal_skipped_basket
    R6_LINKS = dict(R6_LINKS_REVIEW if args.r6_ids == "review" else R6_LINKS_FROZEN)
    evdir = Path(args.evidence)
    run_name = evdir.name
    t = time.time()
    DV = Derived(books=books)
    REG = derive_regression(DV, books)
    if args.regress_only:
        C = {}
        run_check(C, "C-regress", lambda c: regress_check(c, DV, REG, None, "regress-only"))
        print_table(C, "C-regress only")
        for n_ in C["C-regress"].notes:
            print("  " + n_)
        gc_, gf_ = summarise(C)
        out = Path(args.out) if args.out else SCRATCH / "verify_t12_regress.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(dict(checks={k: v.to_dict() for k, v in C.items()}, v4a=getattr(DV, "v4a", None)), indent=1, default=str))
        print(f"wrote {out}\nC-regress: compared {gc_}, failures {gf_}")
        sys.exit(0 if gc_ > 0 and gf_ == 0 else 1)
    E = Evidence(evdir)
    r2_note = f"set on the command line: {args.r2_init}"
    r2_mode = args.r2_init
    if args.r2_init == "auto":
        r2_mode, r2_note = choose_r2_init(DV, E)
    if r2_mode != DV.r2_init:
        DV = Derived(books=books, verbose=False, r2_init=r2_mode)
        REG = derive_regression(DV, books, verbose=False)
    print(f"r2 initial position: {r2_mode} ({r2_note}); R6 quote_ids: {R6_LINKS}", flush=True)
    SETS = derive_sets(DV)
    try:
        tp = tag_panel_check(DV)
    except Exception as ex:
        tp = dict(error=repr(ex))
    print(f"[{time.time()-t:6.1f}s] derivation complete", flush=True)
    C = compare_all(DV, SETS, E, run_name, REG)
    print(f"[{time.time()-t:6.1f}s] checks complete", flush=True)
    for nm in EVIDENCE_FILES:
        if E.path(nm) is None and nm not in E.missing_files:
            E.missing_files.append(nm)
    extra_missing = sorted(set(E.missing_files))
    if run_name != "headline":
        extra_missing = [x for x in extra_missing if x not in HEADLINE_ONLY]
    if not any(p in R6_BOOKS for p in books):
        extra_missing = [x for x in extra_missing if x != "r6_links.csv"]
    if extra_missing:
        print("\nMISSING EVIDENCE FILES: " + ", ".join(extra_missing))
    print_table(C, f"verifier vs evidence in {evdir}")
    gate_compared, gate_fail = summarise(C)
    print(f"\nown ranking of the raw market caps against the D23b panel (information): {tp}")
    print("\n=== recomputed percentiles (20.8 bps, LBES; pass mark 90) ===")
    for r in DV.percentiles:
        if r["cash"] == "lbes" and abs(r["cost_bps"] - HEADLINE_COST) < 1e-9:
            print(f"{r['book']} {r['window']:7s} {r['draw_type']:5s} CAGR pctile {r.get('cagr_pctile', float('nan')):7.2f} (p {r.get('cagr_p', float('nan')):.4f})   "
                  f"max-DD pctile {r.get('max_dd_pctile', float('nan')):7.2f}   n {r['n_draws']}")
    selftest = None
    if not args.no_selftest:
        base = Path(args.corrupt_dir) if args.corrupt_dir else SCRATCH / "corrupt_evidence_t12"
        base.mkdir(parents=True, exist_ok=True)
        selftest, _ = run_selftest(DV, SETS, E, evdir, run_name, books, base, REG)
        print(f"C-corrupt: every corruption detected by its check and the combined copy fails: {selftest['detected']}")
    ok_real = gate_compared > 0 and gate_fail == 0 and not extra_missing and all(c.compared > 0 for c in C.values() if c.gate)
    ok = ok_real and (selftest is None or selftest["detected"])
    rep = dict(verifier="analysis/verify_t12.py", evidence=str(evdir), r2_init=r2_mode, r2_init_note=r2_note, r6_quote_ids=R6_LINKS,
               r7_held_reading=DV.r7_variant, gate_compared=int(gate_compared), gate_failures_and_missing=int(gate_fail),
               missing_evidence_files=extra_missing, checks={k: v.to_dict() for k, v in C.items()},
               c_corrupt=dict(compared=0 if selftest is None else 1, failed=0 if (selftest is None or selftest["detected"]) else 1),
               tag_panel_crosscheck=tp, v4a=getattr(DV, "v4a", None), c3_rule_minus_whole_book=getattr(DV, "c3", None),
               percentiles=DV.percentiles, approved_data_files_read=READS, selftest=selftest, exit_ok=bool(ok))
    out = Path(args.out) if args.out else evdir / "verify_t12.json"
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
