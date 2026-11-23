"""T10 independent verifier (Step 3).

Re-derives T10's weekly decisions, tags, FS counts, states, events, trades, daily NAVs, statistics, comparators, threshold curve,
stretch table, bootstrap intervals and R4 tag-error draws from the RAW approved files only (plain numpy / pandas, its own loaders, its
own tag lookup, simulator and event builder) and compares them with the engine's evidence in tests/T10/evidence/<run>/.

It imports nothing from the engine, from analysis/tag_lookup.py, from analysis/approved_data.py or from any other module in analysis/
or data/, and never read their source. The rules are those of tests/T10/logs/verifier_spec.md, logs/evidence_contract.md and T10.md
sections 1-3 (frozen; T10.md wins). Style and structure forked from analysis/verify_t07.py (read for style only; that is another
verifier, not an engine).

Usage (from AA/, as `python -I`):
    python -I analysis/verify_t10.py --run smoke4
    python -I analysis/verify_t10.py --run headline --evidence-dir DIR --no-selftest

Exit code 0 only if every check compared at least one row, none failed, none was missing, and (default) the deliberately corrupted
copies were all detected (C-corrupt). Writes verify_t10.json into the evidence directory.
"""
import argparse
import hashlib
import json
import math
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

AA = Path(__file__).resolve().parents[1]
BOOKS = ["SCMO_0003", "SCMO_0007", "SCMO_0010", "SCMO_0029"]
BOOK_NO = {b: i for i, b in enumerate(BOOKS)}
COSTS = [0.0, 20.8, 50.0]
HEADLINE_COST = 20.8
END = pd.Timestamp("2026-10-30")               # window end (T10.md header, section 3 step 1)
LIVE_START = pd.Timestamp("2021-11-01")
T06_LAST = pd.Timestamp("2026-10-22")          # T06's window end (shared sessions for C-t06)
TOL = 1e-9                                     # relative tolerance on NAVs and statistics
TOL_REGRESSION = 1e-12
G0_OVERALL_PP = 0.25
G0_YEAR_PP = 0.5
BANDS = ["Large", "Mid", "Small and below"]
BAND_INDEX = {b: i for i, b in enumerate(BANDS)}
INDEX_NAMES = ["Nifty100", "MC100", "SC100"]
INDEX_TO_BAND = {"NIFTY 100": "Large", "NIFTY MIDCAP 150": "Mid", "NIFTY SMALLCAP 250": "Small and below",
                 "NIFTY MICROCAP 250": "Small and below"}
APPROVED_MD = AA / "data" / "APPROVED_DATA.md"
T06_EVIDENCE = AA / "tests" / "T06" / "evidence" / "headline"
# approved rows whose through-date is deliberately earlier than the window's end (APPROVED_DATA.md "Latest usable date by role")
THROUGH_EXEMPT_IDS = {"D12", "D19", "D05"}
EXT = "Historical Data/extended_2026-11-12"
READ_KW = dict(keep_default_na=False, na_values=[""])     # D20-D23: only the empty string is null
R4_RATE = 0.0793
USE_D20_PAIRS = False     # also link ISINs through the (isin, quote_id) pairs of D20 itself (identity links only); False = D22 only
THRESHOLDS = {"thr_2/5": (2, 5), "thr_1/2": (1, 2), "thr_7/10": (7, 10), "thr_4/5": (4, 5)}
TIME0 = time.time()


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
READS = {}          # relative path -> True for every file this verifier read
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
    READS[key] = True
    return AA / rel


# ----------------------------------------------------------------------------------------
# raw loaders
# ----------------------------------------------------------------------------------------
def load_published_nav(p):
    d = pd.read_csv(rd(f"Historical Data/extended_2026-11-06/published_nav/{p}.csv"))
    d["date"] = pd.to_datetime(d["_id.date"], format="%Y/%m/%d")
    return d.set_index("date")["index"].sort_index()


def load_masters():
    out = {}
    for name in INDEX_NAMES:
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
    """T10.md section 3 step 7 / verifier spec: open, high and low clipped to the GOLDBEES close x (1 +- (MCX range / MCX close +
    0.5%)) where the MCX file has a bar that day, high and low re-bounded to include open and close, then (O+H+L+C)/4; the raw OHLC4
    where the MCX file has no bar (after its last date)."""
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


def chained_liq(lbes, liq, switch=pd.Timestamp("2024-01-24")):
    """R3 cash level as in T06 (verifier spec): the LBES level to the session before `switch`, then chained with the LIQUIDCASE daily
    returns (level[t] = level[t-1] x liq[t]/liq[t-1]) on LIQUIDCASE's own dates from `switch`."""
    base = lbes[lbes.index < switch]
    lq = liq[liq.index >= switch]
    prev_liq = liq[liq.index < switch].iloc[-1]
    ratio = lq.values / np.concatenate([[prev_liq], lq.values[:-1]])
    lv = base.iloc[-1] * np.cumprod(ratio)
    return pd.concat([base, pd.Series(lv, index=lq.index)]).sort_index()


def asof_levels(cal, series, name):
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
    fill = ohlc4.where(all4, W["close"])         # a blank open/high/low -> the close
    fill = fill.where(bar, close_ff)              # no bar that session -> the last close
    return d18, close_ff, fill


def load_baskets(p):
    """Listed weights per availableDate (skipped baskets dropped), the column-to-ISIN map."""
    m = pd.read_csv(rd(f"data/holdings_matrix/{p}_holding_weight_matrix.csv"))
    m = m.rename(columns={m.columns[0]: "avail"})
    m["avail"] = pd.to_datetime(m["avail"])
    s = pd.read_csv(rd(f"data/holdings_matrix/{p}_holding_weight_sources.csv"))
    s["rebalance_date"] = pd.to_datetime(s["rebalance_date"])
    skipped = set(s.loc[s["source"] == "csv_only_skipped", "rebalance_date"])
    dropped = sorted(skipped)
    m = m[~m["avail"].isin(skipped)].sort_values("avail").reset_index(drop=True)
    cols = [c for c in m.columns if c != "avail"]
    Wraw = m[cols].fillna(0.0).values.astype(float)
    cm = pd.read_csv(rd(f"data/holdings_matrix/{p}_columns.csv"))
    isin_of = dict(zip(cm["stock"], cm["ISIN"]))
    return m["avail"].values, cols, Wraw, isin_of, [str(pd.Timestamp(x).date()) for x in dropped]


# ----------------------------------------------------------------------------------------
# the tag rule (own implementation of T10.md section 3 "The tag rule")
# ----------------------------------------------------------------------------------------
def rank_band(r):
    return "Large" if r <= 100 else ("Mid" if r <= 250 else "Small and below")


class OwnTags:
    """cutoff = first D21 snapshot. On or after it: the latest D21 snapshot on or before the date, band of the index the stock is
    listed in (Nifty 100 Large, Midcap 150 Mid, Smallcap 250 and Microcap 250 Small and below); a stock in none of the four indices
    falls back to the rank rule ('nonmember_rank'). Before it: the rank on the latest D20 snapshot on or before the date (ordinary
    shares, market cap descending, ties by quote_id, 1-100 Large, 101-250 Mid, above 250 Small and below; null market cap not
    ranked). A stock is found by its ISIN or any ISIN sharing its quote_id (D22 isin and new_isin; ISIN-quote_id pairs of D20 itself
    are used only to link identifiers, never to read a rank from a later snapshot). Not found = 'Small and below', 'unranked'. No
    snapshot dated after the date is ever used."""

    def __init__(self):
        d20 = pd.read_csv(rd(f"{EXT}/mcap_universe/mcap_universe_ordinary.csv"),
                          usecols=["date", "quote_id", "isin", "mcap", "instrument_class"], **READ_KW)
        d20 = d20[d20["instrument_class"] == "ordinary"].reset_index(drop=True)
        d20["date"] = pd.to_datetime(d20["date"])
        self.q20 = d20["quote_id"].values.astype(np.int64)
        self.isin20 = d20["isin"].astype(object).where(d20["isin"].notna(), None).values
        self.mcap20 = d20["mcap"].values.astype(float)
        self.dates20 = np.array(sorted(d20["date"].unique()), dtype="datetime64[ns]")
        self.pos20 = {np.datetime64(k, "ns"): v for k, v in d20.groupby("date").indices.items()}
        self._snap = {}
        d21 = pd.read_csv(rd(f"{EXT}/membership/index_constituents_monthly.csv"), usecols=["snapshot_date", "index_name", "isin"], **READ_KW)
        d21["snapshot_date"] = pd.to_datetime(d21["snapshot_date"])
        self.dates21 = np.array(sorted(d21["snapshot_date"].unique()), dtype="datetime64[ns]")
        self.cutoff = self.dates21[0]
        self.mem = {}
        for k, g in d21.groupby("snapshot_date"):
            dd = {}
            for isn, nm in zip(g["isin"].values, g["index_name"].values):
                dd.setdefault(isn, []).append(INDEX_TO_BAND[nm])
            self.mem[np.datetime64(k, "ns")] = dd
        d22 = pd.read_csv(rd(f"{EXT}/symbology/symbology_changes.csv"), usecols=["quote_id", "isin", "new_isin"], **READ_KW)
        self.q_of_isin = defaultdict(set)
        self.isins_of_q = defaultdict(set)
        for q, a, b in zip(d22["quote_id"].values, d22["isin"].values, d22["new_isin"].values):
            for x in (a, b):
                if isinstance(x, str):
                    self.q_of_isin[x].add(int(q)); self.isins_of_q[int(q)].add(x)
        if USE_D20_PAIRS:
            pairs = pd.DataFrame({"q": self.q20, "i": self.isin20}).dropna().drop_duplicates()
            for q, x in zip(pairs["q"].values, pairs["i"].values):
                self.q_of_isin[x].add(int(q)); self.isins_of_q[int(q)].add(x)
        self._grp = {}
        self._cache = {}
        self.multi_band = 0

    def group(self, isin):
        if isin not in self._grp:
            qs = set(self.q_of_isin.get(isin, set()))
            gi = {isin}
            for q in qs:
                gi |= self.isins_of_q[q]
            self._grp[isin] = (gi, qs)
        return self._grp[isin]

    def snapshot_ranks(self, t):
        """dicts isin -> best rank and quote_id -> best rank for the snapshot t (null market cap not ranked)."""
        if t not in self._snap:
            pos = self.pos20[t]
            m = self.mcap20[pos]
            q = self.q20[pos]
            isn = self.isin20[pos]
            ok = np.flatnonzero(~np.isnan(m))
            order = ok[np.lexsort((q[ok], -m[ok]))]          # market cap descending, ties by quote_id ascending
            by_isin, by_q = {}, {}
            for r, k in enumerate(order, start=1):
                if isn[k] is not None and isn[k] not in by_isin:
                    by_isin[isn[k]] = r
                if int(q[k]) not in by_q:
                    by_q[int(q[k])] = r
            self._snap[t] = (by_isin, by_q, len(order))
        return self._snap[t]

    def rank_lookup(self, gi, qs, asof, isin):
        i = np.searchsorted(self.dates20, np.datetime64(asof, "ns"), side="right") - 1
        if i < 0:
            return None
        t = self.dates20[i]
        by_isin, by_q, _ = self.snapshot_ranks(t)
        r = by_isin.get(isin)
        via = "isin"
        if r is None:                               # not under this ISIN that day: any ISIN or quote_id of the same instrument
            cand = [by_isin[x] for x in gi if x in by_isin] + [by_q[q] for q in qs if q in by_q]
            if not cand:
                return None
            r = min(cand)
            via = "symbology"
        return (t, int(r), via)

    def tag(self, isin, asof):
        key = (isin, pd.Timestamp(asof))
        if key in self._cache:
            return self._cache[key]
        asof64 = np.datetime64(pd.Timestamp(asof), "ns")
        gi, qs = self.group(isin)
        res = None
        if asof64 >= self.cutoff:
            j = np.searchsorted(self.dates21, asof64, side="right") - 1
            t = self.dates21[j]
            dd = self.mem[t]
            hit = [x for x in ([isin] + sorted(gi - {isin})) if x in dd]
            if hit:
                bands = dd[hit[0]]
                if len(set(bands)) > 1:
                    self.multi_band += 1
                band = sorted(bands, key=lambda b: BAND_INDEX[b])[0]
                res = dict(band=band, source="membership", snapshot=str(pd.Timestamp(t).date()), detail=f"isin={hit[0]}",
                           via="isin" if hit[0] == isin else "symbology")
            src = "nonmember_rank"
        else:
            src = "rank"
        if res is None:
            r = self.rank_lookup(gi, qs, asof, isin)
            if r is None:
                res = dict(band="Small and below", source="unranked", snapshot="", detail="not found", via="")
            else:
                res = dict(band=rank_band(r[1]), source=src, snapshot=str(pd.Timestamp(r[0]).date()), detail=str(r[1]), via=r[2])
        self._cache[key] = res
        return res


# ----------------------------------------------------------------------------------------
# book construction and windows
# ----------------------------------------------------------------------------------------
def build_book(p, gold_fill, gold_close, lbes, liq, corr):
    nav = load_published_nav(p)
    t0 = nav.index[0]
    cal = nav.index[(nav.index >= t0) & (nav.index <= END)]
    n_full = len(cal)
    d18, close_ff, fill = load_book_prices(p, corr)
    avail, cols, Wraw, isin_of, dropped = load_baskets(p)
    S_cols = [c for c, any_ in zip(cols, (Wraw > 0).any(axis=0)) if any_]
    ci = [cols.index(c) for c in S_cols]
    Wraw = Wraw[:, ci]
    assert not [c for c in S_cols if c not in close_ff.columns], p
    miss = [d for d in cal if d not in close_ff.index]
    assert not miss, (p, miss[:3])
    C = close_ff[S_cols].reindex(cal).values
    F = fill[S_cols].reindex(cal).values
    Cn = np.nan_to_num(C, nan=0.0)
    gclose = gold_close.reindex(cal, method="ffill").values
    gfill = gold_fill.reindex(cal).values
    gfill = np.where(np.isnan(gfill), gclose, gfill)
    L = asof_levels(cal, lbes, "LBES")
    L2 = asof_levels(cal, liq, "LIQUIDCASE")
    Lchain = asof_levels(cal, chained_liq(lbes, liq), "LBES+LIQUIDCASE chain")
    eff = np.searchsorted(cal.values, avail, side="left")        # first session on or after availableDate
    basket_at = {}
    for k in range(len(avail)):
        if eff[k] < n_full:
            basket_at[int(eff[k])] = k
    isins = [isin_of[s] for s in S_cols]
    return dict(p=p, t0=t0, cal=cal, n_full=n_full, S=S_cols, isins=isins, C=C, Cn=Cn, F=F, gc=gclose, gf=gfill, L=L, L2=L2, Lchain=Lchain,
                Wraw=Wraw, basket_at_full=basket_at, avail=avail, d18=d18, Ffl=fill[S_cols], dropped=dropped, pub=nav)


def make_view(B, a, b, cash="lbes"):
    """Sessions [a, b) of book B; session a is the window's T0 (NAV 1.000 at its close). Wn = every basket row divided by its row
    sum (T06's convention, the verifier spec)."""
    full = B["basket_at_full"]
    rel = {k - a: v for k, v in full.items() if k < b}
    keys = sorted(rel)
    k_t0 = max(k for k in keys if k <= 0)
    k0 = rel[k_t0]
    first_d18 = B["d18"][np.searchsorted(B["d18"].values, B["avail"][k0], side="left")]
    W = B["Wraw"]
    return dict(p=B["p"], cal=B["cal"][a:b], n=b - a, a=a, S=B["S"], isins=B["isins"], C=B["C"][a:b], Cn=B["Cn"][a:b], F=B["F"][a:b],
                gc=B["gc"][a:b], gf=B["gf"][a:b], L=(B["L"] if cash == "lbes" else B["L2"] if cash == "liq" else B["Lchain"])[a:b],
                W=W, Wn=W / W.sum(axis=1, keepdims=True), avail=B["avail"], basket_at=rel, b_idx=keys,
                changes=[k for k in keys if 0 < k < b - a], k0=k0, init_fill=B["Ffl"].loc[first_d18].values, first_d18=first_d18)


def basket_key(V, i):
    return V["b_idx"][np.searchsorted(V["b_idx"], i, side="right") - 1]


def basket_row(V, i):
    return V["basket_at"][basket_key(V, i)]


def decision_dates(V, window, masters):
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
            signs.append(sg[pos]); labels.append(pd.Timestamp(dates[pos]))
        trade = cal[ix + 1] if (ix + 1 < n and j < len(dec_idx) - 1) else None
        rows.append(dict(book=V["p"], window=window, j=j, decision_date=str(d.date()), decision_idx=int(ix),
                         trade_date=None if trade is None else str(trade.date()),
                         sign_Nifty100=signs[0], sign_MC100=signs[1], sign_SC100=signs[2],
                         label_Nifty100=str(labels[0].date()), label_MC100=str(labels[1].date()), label_SC100=str(labels[2].date()),
                         pattern="".join("B" if s == "BUY" else "S" for s in signs)))
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------------------------
# the FS decision (T10.md section 3 step 4) and the states of every rule kind
# ----------------------------------------------------------------------------------------
def float_fs(counts, n, on, order):
    s = 0.0
    for b in order:
        if counts[b] > 0:
            s += (counts[b] / n) * (1.0 if on[b] else 0.0)
    return s


def fs_decisions(V, dec, tagger, window):
    """Per weekly decision: the basket in force, every held stock's tag as of the decision date (increasing ISIN string order),
    n, the band counts, k, FS, weight FS, states. Returns (decisions frame, stock rows frame, per-decision lists for R4)."""
    drows, srows, per = [], [], []
    for r in dec.itertuples(index=False):
        ix = r.decision_idx
        bk = basket_key(V, ix)
        k = V["basket_at"][bk]
        w = V["Wn"][k]
        held = sorted(np.flatnonzero(w > 0).tolist(), key=lambda s: V["isins"][s])
        on_ix = [r.sign_Nifty100 == "BUY", r.sign_MC100 == "BUY", r.sign_SC100 == "BUY"]       # Large, Mid, Small and below
        d = pd.Timestamp(r.decision_date)
        tags = [tagger.tag(V["isins"][s], d) for s in held]
        bands = [BAND_INDEX[t["band"]] for t in tags]
        n = len(held)
        counts = [bands.count(0), bands.count(1), bands.count(2)]
        kon = sum(1 for b in bands if on_ix[b])
        wfs = float(sum(w[s] for s, b in zip(held, bands) if on_ix[b]))
        st_rule = int(5 * kon >= 3 * n)
        st_switch = int(r.pattern == "BBB")
        f1 = float_fs(counts, n, on_ix, [0, 1, 2])
        f2 = float_fs(counts, n, on_ix, [2, 1, 0])
        drows.append(dict(book=V["p"], window=window, j=r.j, decision_date=r.decision_date, decision_idx=ix, trade_date=r.trade_date,
                          sign_Nifty100=r.sign_Nifty100, sign_MC100=r.sign_MC100, sign_SC100=r.sign_SC100,
                          label_Nifty100=r.label_Nifty100, label_MC100=r.label_MC100, label_SC100=r.label_SC100, pattern=r.pattern,
                          basket_eff=str(pd.Timestamp(V["avail"][k]).date()), n_held=n, n_large=counts[0], n_mid=counts[1],
                          n_small=counts[2], k_on=kon, fs=kon / n, weight_fs=wfs, state_rule=st_rule, state_switch=st_switch,
                          extra=bool(st_rule == 1 and st_switch == 0), tie=bool(5 * kon == 3 * n), float_fs_LMS=f1, float_fs_SML=f2,
                          float_differs=bool((f1 >= 0.60) != bool(st_rule) or (f2 >= 0.60) != bool(st_rule)),
                          state_weight_fs=int(wfs >= 0.60 - 1e-12)))
        for s, t, b in zip(held, tags, bands):
            srows.append(dict(book=V["p"], window=window, j=r.j, decision_date=r.decision_date, isin=V["isins"][s], stock=V["S"][s],
                              listed_weight=float(w[s]), band=BANDS[b], tag_source=t["source"], tag_snapshot=t["snapshot"],
                              tag_detail=t["detail"], tag_via=t["via"], band_signal="BUY" if on_ix[b] else "SELL", on=bool(on_ix[b]),
                              tag_snapshot_date=t["snapshot"], _decision=r.j))
        per.append(dict(j=r.j, held=held, bands=bands, srcs=[t["source"] for t in tags], on_ix=on_ix, n=n, w=[float(w[s]) for s in held]))
    return pd.DataFrame(drows), pd.DataFrame(srows), per


def states_of_kind(ddf, kind):
    if kind == "rule":
        return ddf["state_rule"].values.astype(int)
    if kind == "switch":
        return ddf["state_switch"].values.astype(int)
    if kind == "parent":
        return np.ones(len(ddf), dtype=int)
    if kind == "sleeve100":
        return np.zeros(len(ddf), dtype=int)
    if kind == "weight_fs":
        return ddf["state_weight_fs"].values.astype(int)
    if kind in THRESHOLDS:
        num, den = THRESHOLDS[kind]
        return (ddf["k_on"].values * den >= num * ddf["n_held"].values).astype(int)
    raise ValueError(kind)


# ----------------------------------------------------------------------------------------
# events (T10.md section 3 step 5; verifier spec "States: ... Events: ...")
# ----------------------------------------------------------------------------------------
def build_events(V, didx, state):
    """state[j] in {0,1} per weekly decision. Returns (events, skipped baskets, pit counters).
    Event dict: idx, kind, k (basket row in force at the trade session), state held after, jl (latest decision made before the
    session; for T0 the decision at T0)."""
    n = V["n"]
    D = len(didx)
    changes = set(V["changes"])
    state_sess = {}
    for j in range(1, D):
        s = int(didx[j]) + 1
        if s < n and j < D - 1:                       # the decision at the last session is made but not traded
            state_sess[s] = j
    held = int(state[0])
    evs = [dict(idx=0, kind="initial", k=basket_row(V, 0), state=held, jl=0)]
    skipped = []
    pit = dict(trades_checked=1, trade_violations=0, t0_trades=1)
    for s in sorted(set(state_sess) | changes):
        jl = int(np.searchsorted(didx, s, side="left") - 1)       # latest decision made strictly before the trade session
        st = int(state[jl])
        se = (s in state_sess) and (st != held)
        isb = s in changes
        be = isb and st == 1
        if isb and st == 0:
            skipped.append(dict(book=V["p"], trade_date=str(V["cal"][s].date()), basket_eff=str(pd.Timestamp(V["avail"][basket_row(V, s)]).date()),
                                had_state_event=bool(se)))
        if not (se or be):
            continue
        kind = "state+basket" if (se and be) else ("state" if se else "basket")
        pit["trades_checked"] += 1
        if not (didx[jl] < s):
            pit["trade_violations"] += 1
        held = st
        evs.append(dict(idx=int(s), kind=kind, k=basket_row(V, s), state=st, jl=jl))
    return evs, skipped, pit


# ----------------------------------------------------------------------------------------
# the simulation (T10.md section 3 steps 5-8; T06's trade())
# ----------------------------------------------------------------------------------------
def simulate(V, evs, bps, mixf=None):
    """evs[0] is the initial event (idx 0); the others are trade sessions. Per event: idx, k (basket row in force), state, kind.
    mixf: constant-mix comparator (stock share f in the basket's stocks, half the rest in each of GOLDBEES and cash, rebalanced at
    every event of the rule; T0 free)."""
    n = V["n"]
    C, Cn, F = V["C"], V["Cn"], V["F"]
    gc, gf, L = V["gc"], V["gf"], V["L"]
    e0 = evs[0]
    assert e0["idx"] == 0
    w0 = V["W"][e0["k"]]
    sh0 = np.where(w0 > 0, w0 / V["init_fill"], 0.0)            # basket as drifted from its availableDate's first D18 session (OHLC4)
    sh0 = sh0 / float((sh0 * Cn[0]).sum())                       # scaled to NAV 1.000 at T0's close
    if mixf is not None:
        shares = sh0 * mixf
        sleeve = 1.0 - mixf
    elif e0["state"] == 1:
        shares = sh0.copy()
        sleeve = 0.0
    else:
        shares = np.zeros_like(sh0)
        sleeve = 1.0
    gu = sleeve / 2.0 / gc[0]
    cu = sleeve / 2.0 / L[0]
    segs = [(0, shares.copy(), gu, cu)]
    trades = []
    for ev in evs[1:]:
        i = ev["idx"]
        pf = F[i]
        wn = V["Wn"][ev["k"]]
        held = wn > 0
        cur_hold = shares != 0
        if np.isnan(pf[held | cur_hold]).any():
            raise RuntimeError(f"missing fill price for a needed stock at {V['cal'][i]}")
        pfz = np.where(np.isnan(pf), 0.0, pf)
        cur_stock = np.where(cur_hold, shares * pfz, 0.0)
        cur_g = gu * gf[i]
        cur_c = cu * L[i]
        Vv = cur_stock.sum() + cur_g + cur_c
        if mixf is not None:
            tgt_stock = np.where(held, mixf * Vv * wn, 0.0)
            tgt_g = tgt_c = (1.0 - mixf) / 2.0 * Vv
        elif ev["state"] == 1:
            tgt_stock = np.where(held, Vv * wn, 0.0)
            tgt_g = tgt_c = 0.0
        else:
            tgt_stock = np.zeros_like(wn)
            tgt_g = tgt_c = Vv / 2.0
        traded = np.abs(tgt_stock - cur_stock).sum() + abs(tgt_g - cur_g) + abs(tgt_c - cur_c)
        cost = traded * bps / 2.0 / 10000.0
        f = (Vv - cost) / Vv
        shares = np.where(tgt_stock > 0, tgt_stock * f / np.where(np.isnan(pf), 1.0, pf), 0.0)
        gu = tgt_g * f / gf[i]
        cu = tgt_c * f / L[i]
        segs.append((i, shares.copy(), gu, cu))
        ts = float(tgt_stock.sum())
        trades.append(dict(idx=int(i), date=str(V["cal"][i].date()), kind=ev["kind"], e_after=ts / (ts + tgt_g + tgt_c) if ts + tgt_g + tgt_c > 0 else 0.0,
                           basket_eff=str(pd.Timestamp(V["avail"][ev["k"]]).date()), V=float(Vv), traded=float(traded), cost=float(cost)))
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
    return dict(nav=nav, trades=trades, stock_value=sval)


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
    def f(x):
        if x is None or x is pd.NA or (isinstance(x, float) and np.isnan(x)):
            return "<NA>"
        if isinstance(x, (bool, np.bool_)):
            return "True" if x else "False"
        return str(x)
    return s.map(f)


def compare_frames(chk, mine, ev, keys, num_cols=(), str_cols=(), tol=TOL, part=None, evidence_extra_ok=False):
    """Outer-join on keys; rows on both sides are compared (numbers by relative difference, strings exactly); rows on one side only
    are missing (a failure), except evidence-only rows when evidence_extra_ok."""
    mine = mine.copy(); ev = ev.copy()
    for k in keys:
        if pd.api.types.is_numeric_dtype(mine[k]) and pd.api.types.is_numeric_dtype(ev[k]):
            mine[k] = mine[k].astype(float); ev[k] = ev[k].astype(float)
        else:
            mine[k] = _norm_str(mine[k]).astype(str); ev[k] = _norm_str(ev[k]).astype(str)
    for cc in num_cols:                      # a numeric column that is absent on one side counts as all-NaN there (NaN must meet NaN)
        if cc not in mine.columns and cc in ev.columns:
            mine[cc] = np.nan
        if cc not in ev.columns and cc in mine.columns:
            ev[cc] = np.nan
    cols_m = list(keys) + [c for c in list(num_cols) + list(str_cols) if c in mine.columns]
    cols_e = list(keys) + [c for c in list(num_cols) + list(str_cols) if c in ev.columns]
    m = mine[cols_m].merge(ev[cols_e], on=keys, how="outer", suffixes=("_v", "_e"), indicator=True)
    both = m[m["_merge"] == "both"]
    miss = m[m["_merge"] != "both"]
    if evidence_extra_ok:
        miss = miss[miss["_merge"] == "left_only"]
    chk.missing += len(miss)
    if len(miss):
        r = miss.iloc[0]
        chk.fail("missing row (%s): %s" % ("verifier only" if r["_merge"] == "left_only" else "evidence only", {k: r[k] for k in keys}))
    bad = np.zeros(len(both), dtype=bool)
    first_desc = None
    for c in num_cols:
        if c + "_e" not in both.columns or c + "_v" not in both.columns:
            chk.fail(f"column {c} absent from the evidence or the derivation")
            bad |= True
            continue
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
        if c + "_e" not in both.columns or c + "_v" not in both.columns:
            chk.fail(f"column {c} absent from the evidence or the derivation")
            bad |= True
            continue
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


# ----------------------------------------------------------------------------------------
# evidence
# ----------------------------------------------------------------------------------------
EVIDENCE_FILES = ["inputs.csv", "decisions.csv", "decision_stocks.csv", "events.csv", "skipped_baskets.csv", "stats.csv",
                  "daily_nav.csv", "trades.csv", "stretches.csv", "bootstrap.csv", "r4_tag_error.csv", "g_engine.csv",
                  "v4_exact.json", "audit.json", "regression_t06.json"]


class Evidence:
    """Reads the engine's evidence files; a corrupted copy overrides single files and falls back to the real directory."""

    def __init__(self, d, fallback=None):
        self.dirs = [Path(d)] + ([Path(fallback)] if fallback else [])
        self.cache = {}
        self.missing_files = []

    def path(self, name):
        for d in self.dirs:
            if (d / name).exists():
                return d / name
        return None

    def get(self, name):
        if name in self.cache:
            return self.cache[name]
        p = self.path(name)
        if p is None:
            if name not in self.missing_files:
                self.missing_files.append(name)
            self.cache[name] = None
            return None
        if name.endswith(".json"):
            val = json.loads(p.read_text(encoding="utf-8"))
        else:
            val = pd.read_csv(p, keep_default_na=False, na_values=[""])
        self.cache[name] = val
        return val

    def books(self):
        d = self.get("decisions.csv")
        return [b for b in BOOKS if d is not None and b in set(d["book"])]


# ----------------------------------------------------------------------------------------
# derive everything that does not depend on the evidence
# ----------------------------------------------------------------------------------------
class Derived:
    """Books, views, tags, decisions, states, events, simulations on demand (cached)."""

    def __init__(self, books=BOOKS, verbose=True):
        self.books = list(books)
        self.masters = load_masters()
        g, mcx = load_gold()
        self.gfill, self.gclose, self.mcx_last = despiked_goldbees_fill(g, mcx)
        self.lbes = load_lbes()
        self.liq = load_liquidcase()
        self.corr = load_corrections()
        self.tagger = OwnTags()
        self.B, self.dec, self._view, self._ev, self._sim = {}, {}, {}, {}, {}
        for p in self.books:
            B = build_book(p, self.gfill, self.gclose, self.lbes, self.liq, self.corr)
            B["a_live"] = int(np.searchsorted(B["cal"].values, np.datetime64(LIVE_START), side="left"))
            self.B[p] = B
            for w in ("full", "live"):
                V = self.view(p, w)
                dec = decision_dates(V, w, self.masters)
                ddf, sdf, per = fs_decisions(V, dec, self.tagger, w)
                self.dec[(p, w)] = dict(ddf=ddf, sdf=sdf, per=per, didx=ddf["decision_idx"].values.astype(int))
            if verbose:
                print(f"[{time.time()-TIME0:6.1f}s] derived decisions and tags for {p}", flush=True)

    def view(self, p, window, cash="lbes"):
        key = (p, window, cash)
        if key not in self._view:
            B = self.B[p]
            self._view[key] = make_view(B, 0 if window == "full" else B["a_live"], B["n_full"], cash)
        return self._view[key]

    def states(self, p, window, kind):
        return states_of_kind(self.dec[(p, window)]["ddf"], kind)

    def events(self, p, window, kind):
        key = (p, window, kind)
        if key not in self._ev:
            self._ev[key] = build_events(self.view(p, window), self.dec[(p, window)]["didx"], self.states(p, window, kind))
        return self._ev[key]

    def sim(self, p, window, kind, bps, cash="lbes"):
        key = (p, window, kind, float(bps), cash)
        if key not in self._sim:
            V = self.view(p, window, cash)
            if kind == "constant_mix":
                rule = self.sim(p, window, "rule", bps, cash)
                f = float(np.mean(rule["stock_value"] / rule["nav"]))
                evs = self.events(p, window, "rule")[0]
                r = simulate(V, evs, bps, mixf=f)
                r["f"] = f
                r["events"] = evs
            else:
                evs = self.events(p, window, kind)[0]
                r = simulate(V, evs, bps)
                r["events"] = evs
            self._sim[key] = r
        return self._sim[key]

    def published(self, p, window):
        V = self.view(p, window)
        pub = self.B[p]["pub"].reindex(V["cal"]).values.astype(float)
        return pub / pub[0]

    def published_aa(self, p, window):
        aa = {"SCMO_0003": "SCMO_0042", "SCMO_0007": "SCMO_0043", "SCMO_0010": "SCMO_0044", "SCMO_0029": "SCMO_0045"}[p]
        s = load_published_nav(aa)
        V = self.view(p, window)
        x = s.reindex(V["cal"]).values.astype(float)
        return aa, x / x[0]

    def ndec(self, p, window):
        return len(self.dec[(p, window)]["ddf"])


# ----------------------------------------------------------------------------------------
# expected tables (the verifier's own derivation, in the layout of the evidence contract)
# ----------------------------------------------------------------------------------------
CASH_VIEW = {"lbes": "lbes", "liq": "liqchain"}          # the evidence's cash label -> this verifier's cash level
MAIN_KINDS = ["rule", "switch", "parent", "constant_mix", "sleeve100"]
THR_KINDS = ["thr_2/5", "thr_1/2", "thr_7/10", "thr_4/5", "weight_fs"]
STATE_KINDS = ["rule", "switch", "parent", "sleeve100"] + THR_KINDS


def exp_decisions(D, books):
    return pd.concat([D.dec[(p, w)]["ddf"] for p in books for w in ("full", "live")], ignore_index=True)


def exp_stocks(D, books):
    return pd.concat([D.dec[(p, w)]["sdf"] for p in books for w in ("full", "live")], ignore_index=True)


def exp_events(D, books):
    rows, skipped = [], []
    for p in books:
        for w in ("full", "live"):
            V = D.view(p, w)
            ddf = D.dec[(p, w)]["ddf"]
            didx = D.dec[(p, w)]["didx"]
            evs, sk, _ = D.events(p, w, "rule")
            trades = D.sim(p, w, "rule", HEADLINE_COST)["trades"]
            for no, ev in enumerate(evs):
                jl = ev["jl"]
                if no == 0:
                    vb, tr, co = 1.0, 0.0, 0.0
                else:
                    t = trades[no - 1]
                    vb, tr, co = t["V"], t["traded"], t["cost"]
                rows.append(dict(book=p, window=w, event_no=no, kind=ev["kind"], trade_date=str(V["cal"][ev["idx"]].date()),
                                 trade_idx=ev["idx"], decision_idx_used=int(didx[jl]), decision_date_used=ddf["decision_date"].iloc[jl],
                                 state="IN" if ev["state"] == 1 else "OUT", basket_eff=str(pd.Timestamp(V["avail"][ev["k"]]).date()),
                                 n_held=int((V["Wn"][ev["k"]] > 0).sum()), V_before=vb, traded=tr, cost=co,
                                 sleeve_share=0 if ev["state"] == 1 else 1))
            for s in sk:
                skipped.append(dict(book=p, window=w, trade_date=s["trade_date"], basket_eff=s["basket_eff"], had_state_event=s["had_state_event"]))
    return pd.DataFrame(rows), pd.DataFrame(skipped)


def stat_row(D, p, w, cash, kind, bps):
    cv = CASH_VIEW[cash]
    ndec = D.ndec(p, w)
    row = dict(book=p, window=w, cash=cash, kind=kind, cost_bps=bps if bps is not None else np.nan)
    if kind == "published_parent":
        row.update(stats_of(D.published(p, w)))
        row["invested_weeks"] = float(ndec)
        return row
    if kind == "published_aa":
        aa, nav = D.published_aa(p, w)
        row.update(stats_of(nav))
        row["aa_scid"] = aa
        return row
    res = D.sim(p, w, kind, bps, cv)
    row.update(stats_of(res["nav"]))
    row["trades"] = float(len(res["trades"]))
    row["cost_paid"] = float(sum(t["cost"] for t in res["trades"]))
    row["events"] = float(len(res["events"]))
    if kind == "constant_mix":
        row["invested_weeks"] = ndec * res["f"]
        row["mix_share_f"] = res["f"]
    else:
        row["invested_weeks"] = float(D.states(p, w, kind).sum())
    return row


def exp_stats(D, books, kinds):
    """The rows of stats.csv for `kinds` in the blocks of the evidence contract."""
    rows = []
    for p in books:
        blocks = [("full", "lbes", c) for c in COSTS] + [("full", "liq", HEADLINE_COST), ("live", "lbes", HEADLINE_COST)]
        for (w, cash, c) in blocks:
            for k in kinds:
                if k in THR_KINDS:
                    if (w, cash, c) == ("full", "lbes", HEADLINE_COST):
                        rows.append(stat_row(D, p, w, cash, k, c))
                elif k in ("published_parent",):
                    rows.append(stat_row(D, p, w, cash, k, c))
                elif k == "published_aa":
                    if w == "live":
                        rows.append(stat_row(D, p, w, cash, k, None))
                else:
                    rows.append(stat_row(D, p, w, cash, k, c))
    return pd.DataFrame(rows)


def with_ckey(df):
    df = df.copy()
    df["ckey"] = df["cost_bps"].astype(float).fillna(-1.0)
    return df


STATS_NUM = STAT_COLS + ["invested_weeks", "trades", "cost_paid", "events", "mix_share_f"]


def exp_nav_trades(D, books):
    dn, tr = [], []
    for p in books:
        V = D.view(p, "full")
        dates = [str(d.date()) for d in V["cal"]]
        for c in COSTS:
            for k in MAIN_KINDS:
                res = D.sim(p, "full", k, c)
                dn.append(pd.DataFrame(dict(book=p, date=dates, ckey=c, run=k, nav=res["nav"])))
                if k != "constant_mix":
                    for no, t in enumerate(res["trades"], start=1):
                        tr.append(dict(book=p, ckey=c, run=k, event_no=no, date=t["date"], idx=t["idx"], kind=t["kind"], e_after=t["e_after"],
                                       basket_eff=t["basket_eff"], V=t["V"], traded=t["traded"], cost=t["cost"], nav_close_after=t["nav_close_after"]))
        dn.append(pd.DataFrame(dict(book=p, date=dates, ckey=-1.0, run="published_parent", nav=D.published(p, "full"))))
    return pd.concat(dn, ignore_index=True), pd.DataFrame(tr)


# ----------------------------------------------------------------------------------------
# checks
# ----------------------------------------------------------------------------------------
def ev_or_missing(chk, E, name):
    x = E.get(name)
    if x is None:
        chk.miss(f"evidence file {name}")
    return x


def check_data(D, E):
    c = Check("C-data")
    inp = ev_or_missing(c, E, "inputs.csv")
    if inp is None:
        return c
    window_end = END
    seen = set()
    for r in inp.itertuples(index=False):
        key = norm_path(r.file)
        seen.add(key)
        bad = []
        row = APPROVED.get(key)
        if row is None:
            bad.append("not in APPROVED_DATA.md")
        else:
            if row["status"] != "APPROVED":
                bad.append(f"status {row['status']}")
            if str(r.approved_row).strip() != f"{row['status']} {row['id']}":
                bad.append(f"approved_row {r.approved_row!r} != {row['status']} {row['id']}")
            if not str(r.sha256).lower().startswith(row["sha"]):
                bad.append("evidence sha256 prefix differs from the registry")
            p = AA / key
            if not p.exists():
                bad.append("file missing on disk")
            else:
                if not sha256_file(p).startswith(row["sha"]):
                    bad.append("sha256 of the file on disk differs from the registry")
                if sha256_file(p) != str(r.sha256).lower():
                    bad.append("full sha256 on disk differs from the evidence")
                if p.stat().st_size != int(r.bytes):
                    bad.append("size differs from the evidence")
            th = row["through"]
            if str(r.through) != th:
                bad.append(f"through {r.through} != registry {th}")
            if th != "n/a" and row["id"] not in THROUGH_EXEMPT_IDS:
                if pd.Timestamp(th) < window_end:
                    bad.append(f"through-date {th} does not cover {window_end.date()}")
        c.compared += 1
        if bad:
            c.failed += 1
            c.fail(f"{key}: " + "; ".join(bad))
    mine = sorted(k for k in READS if k not in seen)
    c.notes.append(f"inputs rows: {len(seen)}; files read by this verifier but not listed in inputs.csv: {mine}")
    c.count("inputs_rows", c.compared, c.failed)
    return c


def check_dec(D, E):
    c = Check("C-dec")
    ev = ev_or_missing(c, E, "decisions.csv")
    if ev is None:
        return c
    mine = exp_decisions(D, D.books)
    ev = ev[ev["book"].isin(D.books)]
    compare_frames(c, mine, ev, ["book", "window", "j"],
                   num_cols=["decision_idx", "n_held"],
                   str_cols=["decision_date", "trade_date", "sign_Nifty100", "sign_MC100", "sign_SC100", "label_Nifty100", "label_MC100",
                             "label_SC100", "pattern", "basket_eff"], part="decisions")
    return c


def check_tag(D, E):
    c = Check("C-tag")
    ev = ev_or_missing(c, E, "decision_stocks.csv")
    if ev is None:
        return c
    mine = exp_stocks(D, D.books)
    ev = ev[ev["book"].isin(D.books)]
    compare_frames(c, mine, ev, ["book", "window", "j", "isin"], num_cols=["listed_weight"],
                   str_cols=["band", "tag_source", "tag_snapshot", "band_signal", "on", "decision_date", "stock"], part="stock_reads")
    ci = Check("C-tag-info", gate=False)       # information only: how the stock was found, and the rank for rank-sourced tags
    compare_frames(ci, mine, ev, ["book", "window", "j", "isin"], str_cols=["tag_via"])
    mr = mine[mine["tag_source"].isin(["rank", "nonmember_rank"])]
    compare_frames(ci, mr, ev[ev["tag_source"].isin(["rank", "nonmember_rank"])], ["book", "window", "j", "isin"], str_cols=["tag_detail"])
    c.notes.append(f"information (not gated): tag_via (all rows) and tag_detail (rank-sourced rows) compared on {ci.compared} cells, "
                   f"{ci.failed} differ; multi-band membership rows seen: {D.tagger.multi_band}")
    # row order: decision order then increasing ISIN string order
    order_bad = 0
    for (b, w), g in ev.groupby(["book", "window"], sort=False):
        isin = g["isin"].astype(str).values
        jj = g["j"].values
        same = jj[1:] == jj[:-1]
        order_bad += int(((isin[1:] < isin[:-1]) & same).sum() + (jj[1:] < jj[:-1]).sum())
    c.compared += 1
    c.failed += int(order_bad > 0)
    if order_bad:
        c.fail(f"evidence rows not in decision order / increasing ISIN order ({order_bad} breaks)")
    c.count("row_order", 1, int(order_bad > 0))
    return c


def v4_expected(D, books):
    out = {}
    for p in books:
        out[p] = {}
        for w in ("full", "live"):
            d = D.dec[(p, w)]["ddf"]
            ex = d["extra"].values.astype(bool)
            runs, cur = [], 0
            for x in ex:
                if x:
                    cur += 1
                elif cur:
                    runs.append(cur); cur = 0
            if cur:
                runs.append(cur)
            out[p][w] = dict(weeks=len(d), rule_out_while_switch_in=int(((d["state_switch"] == 1) & (d["state_rule"] == 0)).sum()),
                             float_differs_weeks=sorted(d.loc[d["float_differs"].astype(bool), "decision_date"].tolist()),
                             tie_weeks=int(d["tie"].sum()), extra_weeks=int(ex.sum()), extra_stretches=runs)
    return out


def check_fs(D, E):
    c = Check("C-fs")
    ev = ev_or_missing(c, E, "decisions.csv")
    if ev is None:
        return c
    mine = exp_decisions(D, D.books)
    ev = ev[ev["book"].isin(D.books)]
    compare_frames(c, mine, ev, ["book", "window", "j"],
                   num_cols=["n_held", "n_large", "n_mid", "n_small", "k_on", "fs", "weight_fs", "state_rule", "state_switch", "tie",
                             "float_fs_LMS", "float_fs_SML", "state_weight_fs"],
                   str_cols=["extra", "float_differs"], part="decision_columns")
    # no decision has the rule OUT while the switch is IN (mine and the evidence's own columns)
    bad_mine = int(((mine["state_rule"] == 0) & (mine["state_switch"] == 1)).sum())
    bad_ev = int(((ev["state_rule"] == 0) & (ev["state_switch"] == 1)).sum())
    c.compared += 2
    c.failed += int(bad_mine > 0) + int(bad_ev > 0)
    c.count("no_rule_out_while_switch_in", 2, int(bad_mine > 0) + int(bad_ev > 0))
    if bad_mine or bad_ev:
        c.fail(f"rule OUT while switch IN in {bad_mine} (verifier) / {bad_ev} (evidence) decisions")
    # v4_exact.json
    v4 = E.get("v4_exact.json")
    if v4 is None:
        c.miss("evidence file v4_exact.json")
        return c
    exp = v4_expected(D, D.books)
    n_cmp = n_bad = 0
    for p in D.books:
        for w in ("full", "live"):
            e = v4.get("books", {}).get(p, {}).get(w)
            if e is None:
                c.miss(f"v4_exact.json lacks {p} {w}")
                continue
            evd = ev[(ev["book"] == p) & (ev["window"] == w)]
            ident = int((~np.isclose(evd["fs"].values, evd["k_on"].values / evd["n_held"].values, rtol=0, atol=1e-15)
                         | (evd["k_on"].values > evd["n_held"].values) | (evd["k_on"].values < 0)).sum())
            rule_fail = int((evd["state_rule"].values != (5 * evd["k_on"].values >= 3 * evd["n_held"].values).astype(int)).sum())
            mineexp = dict(exp[p][w], fs_identity_failures=ident, state_rule_failures=rule_fail)
            for k, vv in mineexp.items():
                n_cmp += 1
                if e.get(k) != vv:
                    n_bad += 1
                    c.fail(f"v4_exact.json {p} {w} {k}: engine={e.get(k)!r} verifier={vv!r}")
    c.compared += n_cmp
    c.failed += n_bad
    c.count("v4_exact_json_fields", n_cmp, n_bad)
    return c


def check_events(D, E):
    c = Check("C-events")
    ev = ev_or_missing(c, E, "events.csv")
    sk = ev_or_missing(c, E, "skipped_baskets.csv")
    if ev is None or sk is None:
        return c
    mine, msk = exp_events(D, D.books)
    ev = ev[ev["book"].isin(D.books)]
    compare_frames(c, mine, ev, ["book", "window", "event_no"], num_cols=["trade_idx", "decision_idx_used", "n_held", "V_before", "traded", "cost",
                                                                          "sleeve_share"],
                   str_cols=["kind", "trade_date", "decision_date_used", "state", "basket_eff"], part="events")
    sk = sk[sk["book"].isin(D.books)]
    if len(msk) == 0:
        msk = pd.DataFrame(columns=["book", "window", "trade_date", "basket_eff", "had_state_event"])
    compare_frames(c, msk, sk, ["book", "window", "trade_date"], str_cols=["basket_eff"], part="skipped_baskets")
    n_coinc = int(msk["had_state_event"].sum()) if len(msk) else 0
    c.notes.append(f"reading: a basket change on a session where the book is OUT after the latest decision is 'skipped' even when a state "
                   f"event (IN to OUT) falls on the same session; such coincident rows: {n_coinc} of {len(msk)}")
    return c


def nav_compare(c, mine, ev, label, part):
    compare_frames(c, mine, ev, ["book", "window", "cash", "kind", "ckey"], num_cols=STATS_NUM, tol=TOL, part=part)


def check_nav(D, E):
    c = Check("C-nav")
    st = ev_or_missing(c, E, "stats.csv")
    dn = ev_or_missing(c, E, "daily_nav.csv")
    tr = ev_or_missing(c, E, "trades.csv")
    if st is None or dn is None or tr is None:
        return c
    st = with_ckey(st[st["book"].isin(D.books)])
    kinds = MAIN_KINDS + ["published_parent", "published_aa"]
    mine = with_ckey(exp_stats(D, D.books, kinds))
    evk = st[st["kind"].isin(kinds)]
    nav_compare(c, mine, evk, "stats", "stats_rows")
    unc = sorted(set(st["kind"]) - set(kinds) - set(THR_KINDS))
    c.notes.append(f"stats kinds not covered here: {unc} (t07_rule is descriptive and is not verified)")
    # daily NAV
    dn = dn[dn["book"].isin(D.books)].copy()
    dn["ckey"] = dn["cost_bps"].astype(float).fillna(-1.0)
    mdn, mtr = exp_nav_trades(D, D.books)
    nrow_unc = int((dn["run"] == "t07_rule").sum())
    dn = dn[dn["run"].isin(MAIN_KINDS + ["published_parent"])]
    compare_frames(c, mdn, dn, ["book", "date", "ckey", "run"], num_cols=["nav"], tol=TOL, part="daily_nav")
    c.notes.append(f"daily_nav rows of t07_rule not verified: {nrow_unc}")
    tr = tr[tr["book"].isin(D.books)].copy()
    tr["ckey"] = tr["cost_bps"].astype(float)
    compare_frames(c, mtr, tr, ["book", "ckey", "run", "event_no"], num_cols=["idx", "e_after", "V", "traded", "cost", "nav_close_after"],
                   str_cols=["date", "kind", "basket_eff"], tol=TOL, part="trades")
    return c


def check_thr(D, E):
    c = Check("C-thr")
    st = ev_or_missing(c, E, "stats.csv")
    if st is None:
        return c
    st = with_ckey(st[st["book"].isin(D.books)])
    mine = with_ckey(exp_stats(D, D.books, THR_KINDS))
    nav_compare(c, mine, st[st["kind"].isin(THR_KINDS)], "stats", "threshold_rows")
    return c


def check_t06(D, E):
    """C-t06, the independent anchor: state = IN iff all three SIGN BUY. This verifier's own simulator against T06's recorded daily NAV
    (strategy, hold_parent, sleeve_only, published_D17) on every shared session up to 2026-10-22 at a relative 1e-12, and the
    decisions against T06's decisions.csv on every shared date."""
    c = Check("C-t06")
    tn = pd.read_csv(T06_EVIDENCE / "daily_nav.csv")
    tn["date"] = pd.to_datetime(tn["date"])
    td = pd.read_csv(T06_EVIDENCE / "decisions.csv", keep_default_na=False, na_values=[""])
    worst = 0.0
    for p in D.books:
        V = D.view(p, "full")
        for t06run, kind in [("strategy", "switch"), ("hold_parent", "parent"), ("sleeve_only", "sleeve100")]:
            for bps in COSTS:
                ref = tn[(tn["book"] == p) & (tn["run"] == t06run) & (tn["cost_bps"] == bps)].set_index("date")["nav"].sort_index()
                mine = pd.Series(D.sim(p, "full", kind, bps)["nav"], index=V["cal"])
                common = ref.index.intersection(mine.index)
                common = common[common <= T06_LAST]
                r = rel(mine[common].values, ref[common].values)
                nbad = int((r > TOL_REGRESSION).sum())
                worst = max(worst, float(r.max()) if len(r) else 0.0)
                c.compared += len(common)
                c.failed += nbad
                c.count(f"nav_{t06run}", len(common), nbad)
                if nbad:
                    c.fail(f"{p} {t06run} {bps}: {nbad} sessions differ by more than {TOL_REGRESSION}")
                if len(common) == 0:
                    c.miss(f"no shared sessions for {p} {t06run} {bps}")
        ref = tn[(tn["book"] == p) & (tn["run"] == "published_D17")].drop_duplicates("date").set_index("date")["nav"].sort_index()
        mine = pd.Series(D.published(p, "full"), index=V["cal"])
        common = ref.index.intersection(mine.index)
        common = common[common <= T06_LAST]
        if len(common):
            ref_n = ref[common].values / ref[common].values[0]
            r = rel(mine[common].values / mine[common].values[0], ref_n)
            c.compared += len(common)
            c.failed += int((r > TOL_REGRESSION).sum())
            c.count("nav_published_D17", len(common), int((r > TOL_REGRESSION).sum()))
    c.worst_rel = worst
    # decisions
    td = td[td["book"].isin(D.books)]
    mine = D.dec
    rows = []
    for p in D.books:
        ddf = D.dec[(p, "full")]["ddf"]
        rows.append(ddf[["book", "decision_date", "decision_idx", "trade_date", "sign_Nifty100", "sign_MC100", "sign_SC100", "label_Nifty100",
                         "label_MC100", "label_SC100", "state_switch"]].rename(columns={"state_switch": "state"}))
    mine = pd.concat(rows, ignore_index=True)
    shared = td.merge(mine[["book", "decision_date"]], on=["book", "decision_date"])
    td_shared = td[td.set_index(["book", "decision_date"]).index.isin(shared.set_index(["book", "decision_date"]).index)]
    mine_shared = mine[mine.set_index(["book", "decision_date"]).index.isin(td_shared.set_index(["book", "decision_date"]).index)]
    cd = Check("tmp")
    compare_frames(cd, mine_shared, td_shared, ["book", "decision_date"], num_cols=["decision_idx", "state"],
                   str_cols=["trade_date", "sign_Nifty100", "sign_MC100", "sign_SC100", "label_Nifty100", "label_MC100", "label_SC100"])
    c.compared += cd.compared
    c.failed += cd.failed + cd.missing
    c.count("decisions", cd.compared, cd.failed + cd.missing)
    if cd.first_fail:
        c.fail("decisions: " + cd.first_fail)
    c.notes.append(f"T06 decisions shared with this verifier's: {len(td_shared)} of {len(td)} (T06's last decision is on 2026-10-22, "
                   f"which is not a weekly decision date of the longer calendar)")
    reg = E.get("regression_t06.json")
    if reg is not None:
        c.notes.append(f"engine's regression_t06.json compared sessions: "
                       f"{sum(x.get('dates_compared', 0) for b in reg.get('books', {}).values() for x in b.get('nav', []))}")
    return c


def calendar_year_returns(cal, nav):
    yrs = cal.year.values
    out = {}
    prev = nav[0]
    for y in sorted(set(yrs)):
        last = np.flatnonzero(yrs == y)[-1]
        out[int(y)] = nav[last] / prev - 1.0
        prev = nav[last]
    return out


def check_always_in(D, E):
    """C-always-in: every stock held at 0 cost against the published NAV (G0: +-0.25 pp/yr overall, +-0.5 pp in every year)."""
    c = Check("C-always-in")
    g = ev_or_missing(c, E, "g_engine.csv")
    if g is None:
        return c
    rows = []
    for p in D.books:
        V = D.view(p, "full")
        nav = D.sim(p, "full", "parent", 0.0)["nav"]
        pub = D.published(p, "full")
        n = len(nav)
        yrs = (n - 1) / 252.0
        cyrs = (V["cal"][-1] - V["cal"][0]).days / 365.25      # G0's annual gap is read in calendar years (matches g_engine.csv to 1e-16)
        gap = (nav[-1] ** (1 / cyrs) - pub[-1] ** (1 / cyrs)) * 100.0
        gap252 = (nav[-1] ** (1 / yrs) - pub[-1] ** (1 / yrs)) * 100.0
        ya, yb = calendar_year_returns(V["cal"], nav), calendar_year_returns(V["cal"], pub)
        gaps = {y: (ya[y] - yb[y]) * 100.0 for y in ya}
        wy = max(gaps, key=lambda y: abs(gaps[y]))
        overall = "PASS" if abs(gap) <= G0_OVERALL_PP else "FAIL"
        yearly = "PASS" if all(abs(v) <= G0_YEAR_PP for v in gaps.values()) else "FAIL"
        rows.append(dict(book=p, cagr_gap_pp_yr=abs(gap), overall=overall, worst_year=wy, worst_year_gap_pp=abs(gaps[wy]), yearly=yearly,
                         window_first=str(V["cal"][0].date()), window_last=str(V["cal"][-1].date())))
        c.notes.append(f"{p}: CAGR gap {gap:+.4f} pp/yr in calendar years ({gap252:+.4f} with years = (sessions - 1) / 252); worst year "
                       f"{wy} {gaps[wy]:+.4f} pp; {len(gaps)} calendar years")
        if overall != "PASS" or yearly != "PASS":
            c.fail(f"{p}: G0 not met by this verifier's own always-in NAV ({overall}, {yearly})")
            c.failed += 1
        c.compared += 1 + len(gaps)
    mine = pd.DataFrame(rows)
    g = g[g["book"].isin(D.books)]
    compare_frames(c, mine, g, ["book"], num_cols=["cagr_gap_pp_yr", "worst_year", "worst_year_gap_pp"],
                   str_cols=["overall", "yearly", "window_first", "window_last"], tol=1e-7, part="g_engine")
    return c


def stretch_tables(D, books):
    rows = []
    for p in books:
        for w in ("full", "live"):
            ddf = D.dec[(p, w)]["ddf"]
            didx = D.dec[(p, w)]["didx"]
            V = D.view(p, w)
            n = V["n"]
            ex = ddf["extra"].values.astype(bool)
            fs = ddf["fs"].values
            nr = D.sim(p, w, "rule", HEADLINE_COST)["nav"]
            ns = D.sim(p, w, "switch", HEADLINE_COST)["nav"]
            lr, ls = np.diff(np.log(nr)), np.diff(np.log(ns))
            runs, j = [], 0
            while j < len(ex):
                if ex[j]:
                    k = j
                    while k + 1 < len(ex) and ex[k + 1]:
                        k += 1
                    runs.append((j, k)); j = k + 1
                else:
                    j += 1
            best, best_abs, spans = None, -1.0, []
            for no, (j0, j1) in enumerate(runs, start=1):
                s0 = int(didx[j0])
                s1 = int(didx[j1 + 1]) if j1 + 1 < len(didx) else n - 1
                rr, sr = float(np.log(nr[s1] / nr[s0])), float(np.log(ns[s1] / ns[s0]))
                spans.append((s0, s1))
                rows.append(dict(book=p, window=w, stretch_no=no, first_decision_date=ddf["decision_date"].iloc[j0],
                                 last_decision_date=ddf["decision_date"].iloc[j1], weeks=j1 - j0 + 1, mean_fs=float(fs[j0:j1 + 1].mean()),
                                 span_start_date=str(V["cal"][s0].date()), span_end_date=str(V["cal"][s1].date()), rule_log_return=rr,
                                 switch_log_return=sr, diff_log_return=rr - sr))
                if abs(rr - sr) > best_abs:
                    best, best_abs = no - 1, abs(rr - sr)
            yrs = (n - 1) / 252.0
            all_diff = (np.exp(lr.sum() / yrs) - 1) - (np.exp(ls.sum() / yrs) - 1)
            summ = dict(book=p, window=w, stretch_no=0, weeks=int(ex.sum()), cagr_diff_all=float(all_diff))
            if best is not None:
                s0, s1 = spans[best]
                keep = np.ones(len(lr), dtype=bool)
                keep[s0:s1] = False                                # returns of sessions s0+1 .. s1
                ny = keep.sum() / 252.0
                summ["cagr_diff_without_largest"] = float((np.exp(lr[keep].sum() / ny) - 1) - (np.exp(ls[keep].sum() / ny) - 1))
            rows.append(summ)
    return pd.DataFrame(rows)


def check_r7(D, E):
    c = Check("C-r7")
    ev = ev_or_missing(c, E, "stretches.csv")
    if ev is None:
        return c
    mine = stretch_tables(D, D.books)
    ev = ev[ev["book"].isin(D.books)]
    compare_frames(c, mine, ev, ["book", "window", "stretch_no"],
                   num_cols=["weeks", "mean_fs", "rule_log_return", "switch_log_return", "diff_log_return", "cagr_diff_all",
                             "cagr_diff_without_largest"],
                   str_cols=["first_decision_date", "last_decision_date", "span_start_date", "span_end_date"], part="stretches")
    for p in D.books:
        for w in ("full", "live"):
            k = int((mine[(mine["book"] == p) & (mine["window"] == w)]["stretch_no"] > 0).sum())
            c.notes.append(f"{p} {w}: {k} stretches (reportability gate: at least 5)")
    return c


def boot_cagr_diffs(lr_a, lr_b, book_no, nres=1000):
    n = len(lr_a)
    nb = int(math.ceil(n / 20))
    yrs = n / 252.0
    blk = np.arange(20)
    out = np.empty(nres)
    for r in range(nres):
        rng = np.random.default_rng([11, r, book_no])
        starts = rng.integers(0, n - 19, size=nb)
        idx = (starts[:, None] + blk[None, :]).ravel()[:n]
        out[r] = (np.exp(lr_a[idx].sum() / yrs) - 1.0) - (np.exp(lr_b[idx].sum() / yrs) - 1.0)
    return out


def check_boot(D, E):
    c = Check("C-boot")
    ev = ev_or_missing(c, E, "bootstrap.csv")
    if ev is None:
        return c
    rows = []
    for p in D.books:
        nr = D.sim(p, "full", "rule", HEADLINE_COST)["nav"]
        lr = np.diff(np.log(nr))
        yrs = len(lr) / 252.0
        for comp, kind in [("switch", "switch"), ("parent", "parent")]:
            nc = D.sim(p, "full", kind, HEADLINE_COST)["nav"]
            lc = np.diff(np.log(nc))
            d = boot_cagr_diffs(lr, lc, BOOK_NO[p])
            rows.append(dict(book=p, comparator=comp, point_cagr_diff=(np.exp(lr.sum() / yrs) - 1) - (np.exp(lc.sum() / yrs) - 1),
                             ci_low=float(np.percentile(d, 2.5)), ci_high=float(np.percentile(d, 97.5))))
    ev = ev[ev["book"].isin(D.books)]
    compare_frames(c, pd.DataFrame(rows), ev, ["book", "comparator"], num_cols=["point_cagr_diff", "ci_low", "ci_high"], part="bootstrap")
    return c


class R4Book:
    def __init__(self, D, p):
        self.p = p
        per = D.dec[(p, "full")]["per"]
        ddf = D.dec[(p, "full")]["ddf"]
        self.D_ = D
        dec_of, band, isr = [], [], []
        for d, pj in enumerate(per):
            for b, s in zip(pj["bands"], pj["srcs"]):
                dec_of.append(d); band.append(b); isr.append(s in ("rank", "nonmember_rank"))
        self.dec_of = np.array(dec_of, dtype=int)
        self.band = np.array(band, dtype=int)
        self.isr = np.array(isr, dtype=bool)
        self.on_ix = np.array([pj["on_ix"] for pj in per], dtype=int)
        self.n = np.array([pj["n"] for pj in per], dtype=int)
        self.state0 = ddf["state_rule"].values.astype(int)
        self.R = int(self.isr.sum())
        self.V = D.view(p, "full")
        self.didx = D.dec[(p, "full")]["didx"]
        ns = D.sim(p, "full", "switch", HEADLINE_COST)["nav"]
        self.cagr_switch = ns[-1] ** (252.0 / (len(ns) - 1)) - 1.0

    def draw(self, draw_id):
        rng = np.random.default_rng([10, int(draw_id), BOOK_NO[self.p]])
        u = rng.random((self.R, 2))
        rep = u[:, 0] < R4_RATE
        b = self.band[self.isr]
        first = np.where(b == 0, 1, 0)
        second = np.where(b == 2, 1, 2)
        newb = np.where(rep, np.where(u[:, 1] < 0.5, first, second), b)
        band2 = self.band.copy()
        band2[self.isr] = newb
        on = self.on_ix[self.dec_of, band2]
        k = np.bincount(self.dec_of, weights=on, minlength=len(self.n)).astype(int)
        state = (5 * k >= 3 * self.n).astype(int)
        evs, _, _ = build_events(self.V, self.didx, state)
        nav = simulate(self.V, evs, HEADLINE_COST)["nav"]
        cagr = nav[-1] ** (252.0 / (len(nav) - 1)) - 1.0
        return dict(cagr=cagr, diff_vs_switch=cagr - self.cagr_switch, weeks_changed=int((state != self.state0).sum()),
                    n_decisions=len(self.n), rank_tag_reads=self.R, flipped=int(rep.sum()))


def check_r4(D, E):
    c = Check("C-r4")
    ev = ev_or_missing(c, E, "r4_tag_error.csv")
    if ev is None:
        return c
    rows = []
    skipped = 0
    for p in D.books:
        evb = ev[ev["book"] == p]
        have = set(evb["draw_id"].astype(int))
        ids = list(range(20)) + [int(x) for x in np.random.default_rng([13, BOOK_NO[p]]).choice(500, 20, replace=False)]
        ids = sorted(set(ids))
        R4 = R4Book(D, p)
        for i in ids:
            if i not in have:
                if len(have) >= 500:
                    c.miss(f"{p} draw {i} absent from the evidence")
                else:
                    skipped += 1
                continue
            rows.append(dict(book=p, draw_id=i, **R4.draw(i)))
        c.notes.append(f"{p}: draws in the evidence {len(have)}; draws re-derived {sum(1 for r in rows if r['book'] == p)} "
                       f"(first 20 and the random 20: {ids})")
    c.notes.append(f"random draw ids not present in a shorter evidence file (not compared): {skipped}")
    mine = pd.DataFrame(rows)
    ev = ev[ev["book"].isin(D.books)]
    compare_frames(c, mine, ev, ["book", "draw_id"], num_cols=["cagr", "diff_vs_switch", "weeks_changed", "n_decisions", "rank_tag_reads",
                                                               "flipped"], part="r4_draws", evidence_extra_ok=True)
    return c


class D23Reader:
    """A direct read of the D23 panels (mcap_rank_panel.csv, membership_panel.csv) with the tag rule of T10.md section 3; ISIN
    renames are linked with the D22 groups of the verifier's own tagger."""

    def __init__(self, tagger):
        self.t = tagger
        rp = pd.read_csv(rd(f"{EXT}/tags/mcap_rank_panel.csv"), usecols=["date", "quote_id", "isin", "rank", "band"], **READ_KW)
        rp["date"] = pd.to_datetime(rp["date"])
        self.rdates = np.array(sorted(rp["date"].unique()), dtype="datetime64[ns]")
        self.rpos = {np.datetime64(k, "ns"): v for k, v in rp.groupby("date").indices.items()}
        self.r_isin = rp["isin"].astype(object).where(rp["isin"].notna(), None).values
        self.r_q = rp["quote_id"].values.astype(np.int64)
        self.r_rank = rp["rank"].values.astype(np.int64)
        self.r_band = rp["band"].values
        mp = pd.read_csv(rd(f"{EXT}/tags/membership_panel.csv"), usecols=["snapshot_date", "isin", "band"], **READ_KW)
        mp["snapshot_date"] = pd.to_datetime(mp["snapshot_date"])
        self.mdates = np.array(sorted(mp["snapshot_date"].unique()), dtype="datetime64[ns]")
        self.mem = {}
        for k, g in mp.groupby("snapshot_date"):
            dd = {}
            for isn, b in zip(g["isin"].values, g["band"].values):
                dd.setdefault(isn, []).append(b)
            self.mem[np.datetime64(k, "ns")] = dd
        self._snap = {}

    def snap(self, t):
        if t not in self._snap:
            pos = self.rpos[t]
            by_isin, by_q = {}, {}
            for k in pos[np.argsort(self.r_rank[pos])]:
                if self.r_isin[k] is not None and self.r_isin[k] not in by_isin:
                    by_isin[self.r_isin[k]] = (int(self.r_rank[k]), self.r_band[k])
                if int(self.r_q[k]) not in by_q:
                    by_q[int(self.r_q[k])] = (int(self.r_rank[k]), self.r_band[k])
            self._snap[t] = (by_isin, by_q)
        return self._snap[t]

    def read(self, isin, asof):
        asof64 = np.datetime64(pd.Timestamp(asof), "ns")
        gi, qs = self.t.group(isin)
        if asof64 >= self.mdates[0]:
            j = np.searchsorted(self.mdates, asof64, side="right") - 1
            dd = self.mem[self.mdates[j]]
            hit = [x for x in ([isin] + sorted(gi - {isin})) if x in dd]
            if hit:
                return "membership", sorted(dd[hit[0]], key=lambda b: BAND_INDEX[b])[0], str(pd.Timestamp(self.mdates[j]).date())
            src = "nonmember_rank"
        else:
            src = "rank"
        i = np.searchsorted(self.rdates, asof64, side="right") - 1
        if i < 0:
            return "unranked", "Small and below", ""
        t = self.rdates[i]
        by_isin, by_q = self.snap(t)
        if isin in by_isin:
            r, b = by_isin[isin]
        else:
            cand = [by_isin[x] for x in gi if x in by_isin] + [by_q[q] for q in qs if q in by_q]
            if not cand:
                return "unranked", "Small and below", ""
            r, b = min(cand)
        return src, b, str(pd.Timestamp(t).date())


def check_v5(D, E):
    c = Check("C-v5")
    ev = ev_or_missing(c, E, "decision_stocks.csv")
    dec = ev_or_missing(c, E, "decisions.csv")
    if ev is None or dec is None:
        return c
    rdr = D23Reader(D.tagger)
    audit = E.get("audit.json")
    tot_disagree_mine = 0
    for p in D.books:
        rows = ev[(ev["book"] == p) & (ev["window"] == "full")].reset_index(drop=True)
        idx = np.random.default_rng([12, BOOK_NO[p]]).choice(len(rows), 500, replace=False)
        nbad = nmine = 0
        for i in idx:
            r = rows.iloc[int(i)]
            src, band, snap = rdr.read(r["isin"], pd.Timestamp(r["decision_date"]))
            c.compared += 1
            ok = (src == r["tag_source"]) and (band == r["band"])
            nbad += int(not ok)
            if not ok:
                c.failed += 1
                c.fail(f"{p} {r['decision_date']} {r['isin']}: engine ({r['tag_source']}, {r['band']}) vs D23 read ({src}, {band})")
            mt = D.tagger.tag(r["isin"], pd.Timestamp(r["decision_date"]))
            nmine += int(not (mt["source"] == src and mt["band"] == band))
        tot_disagree_mine += nmine
        c.count(f"sample_{p}", len(idx), nbad)
        c.notes.append(f"{p}: sample of {len(idx)} full-window (stock, week) reads; engine disagrees with the D23 read in {nbad}; "
                       f"this verifier's own lookup disagrees with the D23 read in {nmine}")
    # number of weekly tag reads = sum of stocks held over the decisions
    for p in D.books:
        for w in ("full", "live"):
            d = dec[(dec["book"] == p) & (dec["window"] == w)]
            nrows = int(((ev["book"] == p) & (ev["window"] == w)).sum())
            mine_n = int(D.dec[(p, w)]["ddf"]["n_held"].sum())
            c.compared += 1
            ok = nrows == int(d["n_held"].sum()) == mine_n
            if audit is not None:
                a = audit.get("v5", {}).get("per_book_window", {}).get(p, {}).get(w)
                ok = ok and (a is not None and a.get("tag_reads") == mine_n and a.get("rows") == nrows)
            if not ok:
                c.failed += 1
                c.fail(f"{p} {w}: rows {nrows}, engine sum n_held {int(d['n_held'].sum())}, verifier {mine_n}")
            c.count("tag_reads_equal_sum_n_held", 1, int(not ok))
    c.notes.append(f"all-sample disagreements between this verifier's lookup and the D23 read: {tot_disagree_mine}")
    return c


def check_pit(D, E):
    c = Check("C-pit")
    ev_ev = ev_or_missing(c, E, "events.csv")
    ev_dec = ev_or_missing(c, E, "decisions.csv")
    ev_stk = ev_or_missing(c, E, "decision_stocks.csv")
    if ev_ev is None or ev_dec is None or ev_stk is None:
        return c
    cnt = dict(decisions=0, decision_violations=0, tags=0, tag_violations=0, trades=0, trade_violations=0, t0=0, decision_trade=0,
               decision_trade_violations=0)

    def run(ddf, sdf, events, src):
        dd = pd.to_datetime(ddf["decision_date"])
        for col in ("label_Nifty100", "label_MC100", "label_SC100"):
            cnt["decisions"] += len(ddf)
            cnt["decision_violations"] += int((pd.to_datetime(ddf[col]) > dd).sum())
        snap = sdf["tag_snapshot"].astype(object)
        has = snap.notna() & (snap.astype(str) != "") & (snap.astype(str) != "nan")
        sd = pd.to_datetime(sdf.loc[has, "tag_snapshot"])
        dd2 = pd.to_datetime(sdf.loc[has, "decision_date"])
        cnt["tags"] += int(has.sum())
        cnt["tag_violations"] += int((sd > dd2).sum())
        tr = ddf[ddf["trade_date"].notna()]
        cnt["decision_trade"] += len(tr)
        cnt["decision_trade_violations"] += int((pd.to_datetime(tr["trade_date"]) <= pd.to_datetime(tr["decision_date"])).sum())
        t0 = events["event_no"] == 0
        cnt["t0"] += int(t0.sum())
        rest = events[~t0]
        cnt["trades"] += len(rest)
        cnt["trade_violations"] += int((pd.to_datetime(rest["decision_date_used"]) >= pd.to_datetime(rest["trade_date"])).sum())

    mine_e, _ = exp_events(D, D.books)
    run(exp_decisions(D, D.books), exp_stocks(D, D.books), mine_e, "verifier")
    run(ev_dec[ev_dec["book"].isin(D.books)], ev_stk[ev_stk["book"].isin(D.books)], ev_ev[ev_ev["book"].isin(D.books)], "evidence")
    total = cnt["decisions"] + cnt["tags"] + cnt["trades"] + cnt["decision_trade"]
    viol = cnt["decision_violations"] + cnt["tag_violations"] + cnt["trade_violations"] + cnt["decision_trade_violations"]
    c.compared = total
    c.failed = viol
    c.count("decisions_label_dates", cnt["decisions"], cnt["decision_violations"])
    c.count("tag_snapshot_dates", cnt["tags"], cnt["tag_violations"])
    c.count("trade_after_decision", cnt["trades"], cnt["trade_violations"])
    c.count("decision_trade_after_decision", cnt["decision_trade"], cnt["decision_trade_violations"])
    c.notes.append(f"counts (verifier's derivation plus the evidence's own columns): {cnt}; T0 events (decision and trade on the same "
                   f"session, excluded) counted separately: {cnt['t0']}")
    if viol:
        c.fail(f"point-in-time violations: {cnt}")
    return c



# ----------------------------------------------------------------------------------------
# runner, reporting, C-corrupt self-test and main
# ----------------------------------------------------------------------------------------
CHECKS = [("C-data", check_data), ("C-dec", check_dec), ("C-tag", check_tag), ("C-fs", check_fs), ("C-events", check_events),
          ("C-nav", check_nav), ("C-thr", check_thr), ("C-t06", check_t06), ("C-always-in", check_always_in), ("C-r7", check_r7),
          ("C-boot", check_boot), ("C-r4", check_r4), ("C-v5", check_v5), ("C-pit", check_pit)]


def compare_all(D, E, only=None, verbose=True):
    C = {}
    for name, fn in CHECKS:
        if only is not None and name not in only:
            continue
        t = time.time()
        try:
            ch = fn(D, E)
        except Exception as ex:                       # a check that cannot run is a failed check
            traceback.print_exc()
            ch = Check(name)
            ch.failed += 1
            ch.fail("exception: " + repr(ex))
        ch.name = name
        C[name] = ch
        if verbose:
            print(f"[{time.time()-TIME0:6.1f}s] {name:12s} compared {ch.compared:8d} failed {ch.failed:6d} missing {ch.missing:4d} "
                  f"worst {ch.worst_rel:9.2e}  ({time.time()-t:.1f}s)", flush=True)
    return C


def summarise(C):
    gate = [c for c in C.values() if c.gate]
    return sum(c.compared for c in gate), sum(c.failed + c.missing for c in gate)


def print_table(C, title):
    print(f"\n=== {title} ===")
    print(f"{'check':12s} {'compared':>10s} {'failed':>8s} {'missing':>8s} {'worst':>10s}")
    for c in C.values():
        print(f"{c.name:12s} {c.compared:10d} {c.failed:8d} {c.missing:8d} {c.worst_rel:10.2e}")
        if c.first_fail:
            print(f"    first problem: {c.first_fail}")


def real_ok(C, E):
    required = [f for f in EVIDENCE_FILES if f not in ("audit.json", "regression_t06.json")]
    miss_files = sorted(set(f for f in required if E.path(f) is None))
    ok = bool(C) and all(c.compared > 0 and c.failed == 0 and c.missing == 0 for c in C.values() if c.gate) and not miss_files
    return ok, miss_files


def flip_band(b):
    return {"Large": "Small and below", "Mid": "Large", "Small and below": "Mid"}[b]


CORRUPTIONS = {
    "flip_tag_band": ["C-tag"],
    "flip_state_rule": ["C-fs"],
    "change_decision_basket_eff": ["C-dec"],
    "change_trade_cost": ["C-nav"],
    "scale_nav": ["C-nav"],
    "delete_event": ["C-events"],
    "change_stretch_span": ["C-r7"],
    "change_r4_cagr": ["C-r4"],
    "change_bootstrap_ci": ["C-boot"],
    "change_threshold_stat": ["C-thr"],
    "change_input_sha": ["C-data"],
    "change_g_engine": ["C-always-in"],
    "tag_snapshot_after_decision": ["C-pit"],
    "change_v5_audit_count": ["C-v5"],
}


def apply_corruption(kind, F, books):
    """Apply ONE corruption to the mutable evidence objects F (name -> DataFrame / dict). Returns (info, files touched)."""
    p0 = books[0]
    if kind == "flip_tag_band":
        d = F["decision_stocks.csv"]
        r = len(d) // 3
        d.loc[r, "band"] = flip_band(d.loc[r, "band"])
        return dict(file="decision_stocks.csv", row=int(r), column="band"), ["decision_stocks.csv"]
    if kind == "flip_state_rule":
        d = F["decisions.csv"]
        rr = d.index[(d["extra"].astype(str) == "True")]
        r = int(rr[len(rr) // 2])
        d.loc[r, "state_rule"] = 0
        return dict(file="decisions.csv", row=r, column="state_rule 1 -> 0 (an extra week)"), ["decisions.csv"]
    if kind == "change_decision_basket_eff":
        d = F["decisions.csv"]
        r = len(d) // 2
        d.loc[r, "basket_eff"] = "1999-01-01"
        return dict(file="decisions.csv", row=int(r), column="basket_eff"), ["decisions.csv"]
    if kind == "change_trade_cost":
        d = F["trades.csv"]
        m = d.index[(d["book"] == p0) & (d["cost_bps"] == HEADLINE_COST) & (d["run"] == "rule")]
        r = int(m[len(m) // 2])
        d.loc[r, "cost"] = float(d.loc[r, "cost"]) * 1.5 + 1e-4
        return dict(file="trades.csv", row=r, column="cost x 1.5"), ["trades.csv"]
    if kind == "scale_nav":
        d = F["daily_nav.csv"]
        m = (d["run"] == "rule") & (d["cost_bps"] == HEADLINE_COST) & (d["book"] == p0)
        d.loc[m, "nav"] = d.loc[m, "nav"].astype(float) * 1.001
        return dict(file="daily_nav.csv", rows=int(m.sum()), what=f"{p0} rule 20.8 bps x 1.001"), ["daily_nav.csv"]
    if kind == "delete_event":
        d = F["events.csv"]
        r = int(d.index[len(d) // 2])
        F["events.csv"] = d.drop(index=r).reset_index(drop=True)
        return dict(file="events.csv", row=r), ["events.csv"]
    if kind == "change_stretch_span":
        d = F["stretches.csv"]
        m = d.index[(d["stretch_no"] > 0) & (d["book"] == p0)]
        r = int(m[len(m) // 2])
        dt = pd.Timestamp(d.loc[r, "span_end_date"]) + pd.Timedelta(days=7)
        d.loc[r, "span_end_date"] = str(dt.date())
        return dict(file="stretches.csv", row=r, column="span_end_date + 7 days"), ["stretches.csv"]
    if kind == "change_r4_cagr":
        d = F["r4_tag_error.csv"]
        r = int(d.index[(d["book"] == p0) & (d["draw_id"] == 3)][0])
        d.loc[r, "cagr"] = float(d.loc[r, "cagr"]) + 0.001
        return dict(file="r4_tag_error.csv", row=r, column="cagr + 0.001"), ["r4_tag_error.csv"]
    if kind == "change_bootstrap_ci":
        d = F["bootstrap.csv"]
        d.loc[0, "ci_high"] = float(d.loc[0, "ci_high"]) + 0.01
        return dict(file="bootstrap.csv", row=0, column="ci_high + 0.01"), ["bootstrap.csv"]
    if kind == "change_threshold_stat":
        d = F["stats.csv"]
        r = int(d.index[(d["kind"] == "thr_2/5") & (d["book"] == p0)][0])
        d.loc[r, "end_nav"] = float(d.loc[r, "end_nav"]) * 1.01
        return dict(file="stats.csv", row=r, column="end_nav of thr_2/5 x 1.01"), ["stats.csv"]
    if kind == "change_input_sha":
        d = F["inputs.csv"]
        s = str(d.loc[3, "sha256"])
        d.loc[3, "sha256"] = ("0" if s[0] != "0" else "1") + s[1:]
        return dict(file="inputs.csv", row=3, column="sha256"), ["inputs.csv"]
    if kind == "change_g_engine":
        d = F["g_engine.csv"]
        d.loc[0, "cagr_gap_pp_yr"] = float(d.loc[0, "cagr_gap_pp_yr"]) + 0.05
        return dict(file="g_engine.csv", row=0, column="cagr_gap_pp_yr + 0.05"), ["g_engine.csv"]
    if kind == "tag_snapshot_after_decision":
        d = F["decision_stocks.csv"]
        r = (2 * len(d)) // 3
        dt = pd.Timestamp(d.loc[r, "decision_date"]) + pd.Timedelta(days=30)
        d.loc[r, "tag_snapshot"] = str(dt.date())
        return dict(file="decision_stocks.csv", row=int(r), column="tag_snapshot = decision date + 30 days"), ["decision_stocks.csv"]
    if kind == "change_v5_audit_count":
        a = F["audit.json"]
        a["v5"]["per_book_window"][p0]["full"]["tag_reads"] += 1
        return dict(file="audit.json", what="v5 tag_reads + 1"), ["audit.json"]
    raise ValueError(kind)


def load_working_copy(E, names):
    F = {}
    for n in names:
        x = E.get(n)
        if x is None:
            continue
        F[n] = x.copy() if isinstance(x, pd.DataFrame) else json.loads(json.dumps(x))
    return F


def write_files(F, names, dst):
    for n in names:
        if n.endswith(".json"):
            (dst / n).write_text(json.dumps(F[n], indent=1))
        else:
            F[n].to_csv(dst / n, index=False)


def run_selftest(D, E, evdir, books, base_dir):
    """C-corrupt: each corruption alone must make its relevant check fail; then all corruptions in one copy must make the whole
    verifier fail (non-zero exit status)."""
    base_dir.mkdir(parents=True, exist_ok=True)
    results = {}
    all_files = sorted({n for n in EVIDENCE_FILES if E.get(n) is not None})
    for kind, must in CORRUPTIONS.items():
        cdir = base_dir / f"corrupt_{kind}"
        if cdir.exists():
            shutil.rmtree(cdir)
        cdir.mkdir(parents=True)
        try:
            F = load_working_copy(E, all_files)
            info, touched = apply_corruption(kind, F, books)
            write_files(F, touched, cdir)
            Cc = compare_all(D, Evidence(cdir, fallback=evdir), only=set(must), verbose=False)
        except Exception as ex:
            traceback.print_exc()
            results[kind] = dict(error=repr(ex), detected=False)
            continue
        nfail = {k: v.failed + v.missing for k, v in Cc.items()}
        results[kind] = dict(info=info, relevant_checks=must, failures_in_relevant_checks=nfail,
                             detected=all(nfail.get(k, 0) > 0 for k in must))
        print(f"  C-corrupt {kind:28s} -> {must}: failures {nfail}  detected={results[kind]['detected']}", flush=True)
    # all corruptions in one copy: the whole run must fail
    cdir = base_dir / "corrupt_all"
    if cdir.exists():
        shutil.rmtree(cdir)
    cdir.mkdir(parents=True)
    F = load_working_copy(E, all_files)
    touched_all = set()
    for kind in CORRUPTIONS:
        if results.get(kind, {}).get("error"):
            continue
        _, touched = apply_corruption(kind, F, books)
        touched_all |= set(touched)
    write_files(F, sorted(touched_all), cdir)
    Eall = Evidence(cdir, fallback=evdir)
    Call = compare_all(D, Eall, verbose=False)
    ok_all, _ = real_ok(Call, Eall)
    cc, cf = summarise(Call)
    print_table(Call, f"SELF-TEST (C-corrupt): all {len(CORRUPTIONS)} corruptions in one copy ({cdir})")
    # the script itself, run on a full copy of the evidence with every corruption applied, must exit with status 1
    full = base_dir / "corrupt_all_full"
    if full.exists():
        shutil.rmtree(full)
    full.mkdir(parents=True)
    for f in Path(evdir).iterdir():
        if f.suffix in (".csv", ".json") and f.name != "verify_t10.json":
            shutil.copy(f, full / f.name)
    for f in cdir.iterdir():
        shutil.copy(f, full / f.name)
    rc = subprocess.run([sys.executable, "-I", str(Path(__file__).resolve()), "--run", "corrupt_all", "--evidence-dir", str(full),
                         "--no-selftest", "--books", ",".join(books), "--out", str(full / "verify_t10_child.json")],
                        capture_output=True, text=True).returncode
    print(f"  C-corrupt: the script run on the fully corrupted copy exits with status {rc} (required: 1)", flush=True)
    detected = all(v.get("detected") for v in results.values()) and (not ok_all) and rc == 1
    return dict(dir=str(base_dir), corruptions=results,
                combined=dict(dir=str(cdir), gate_compared=int(cc), gate_failures=int(cf), would_exit=0 if ok_all else 1,
                              subprocess_exit_status=int(rc), checks={k: v.to_dict() for k, v in Call.items()}),
                detected=bool(detected)), Call


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True, help="run name: the evidence is read from tests/T10/evidence/<run> unless --evidence-dir")
    ap.add_argument("--evidence-dir", default=None)
    ap.add_argument("--no-selftest", action="store_true", help="skip the corrupted-copy self-test (C-corrupt)")
    ap.add_argument("--corrupt-dir", default=None, help="where the corrupted copies are written (default: a temp folder)")
    ap.add_argument("--books", default=None)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    evdir = Path(args.evidence_dir) if args.evidence_dir else AA / "tests" / "T10" / "evidence" / args.run
    out = Path(args.out) if args.out else evdir / "verify_t10.json"
    E = Evidence(evdir)
    books = [b for b in args.books.split(",") if b] if args.books else E.books()
    if not books:
        print(f"no evidence found in {evdir}")
        sys.exit(2)
    print(f"verify_t10: run {args.run}, evidence {evdir}, books {books}", flush=True)
    D = Derived(books)
    C = compare_all(D, E)
    ok_real, miss_files = real_ok(C, E)
    if miss_files:
        print("MISSING EVIDENCE FILES: " + ", ".join(miss_files))
    print_table(C, f"verifier vs evidence in {evdir}")
    gate_compared, gate_fail = summarise(C)
    selftest = None
    if not args.no_selftest:
        base = Path(args.corrupt_dir) if args.corrupt_dir else Path(tempfile.gettempdir()) / "verify_t10_corrupt" / args.run
        selftest, _ = run_selftest(D, E, evdir, books, base)
        print(f"C-corrupt: every corruption detected by its check and the combined copy exits non-zero: {selftest['detected']}")
    ok = ok_real and (selftest is None or selftest["detected"])
    anchor = C.get("C-t06")
    rep = dict(verifier="analysis/verify_t10.py", run=args.run, evidence=str(evdir), books=books,
               gate_compared=int(gate_compared), gate_failures_and_missing=int(gate_fail), missing_evidence_files=miss_files,
               checks={k: v.to_dict() for k, v in C.items()},
               anchor_c_t06=None if anchor is None else dict(compared=anchor.compared, failed=anchor.failed, worst_rel=anchor.worst_rel),
               c_corrupt=None if selftest is None else dict(detected=selftest["detected"], corruptions=selftest["corruptions"],
                                                            combined_would_exit=selftest["combined"]["would_exit"],
                                                            subprocess_exit_status=selftest["combined"]["subprocess_exit_status"]),
               approved_data_files_read=sorted(READS), real_run_ok=bool(ok_real), exit_ok=bool(ok),
               seconds=round(time.time() - TIME0, 1))
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(rep, indent=1, default=str))
        print(f"wrote {out}")
    except Exception as ex:
        print(f"could not write {out}: {ex!r}")
    print(f"\nrows compared (gated checks): {gate_compared}; failures + missing: {gate_fail}; real run ok: {ok_real}; exit ok: {ok}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
