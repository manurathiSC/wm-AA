"""T07 independent verifier (Step 3).

Re-derives T07's decisions, tags, events, targets, NAVs, costs, trades, positions, null-draw structure and null-draw NAVs from the RAW
approved files only (plain numpy / pandas, its own loaders, its own tag lookup, simulator, subset counting, oracle and percentile code)
and compares them with the engine's evidence in tests/T07/evidence/<run>/.

It imports nothing from the engine, from analysis/tag_lookup.py, from analysis/approved_data.py or from any other module in analysis/ or
data/. It never reads their source. The rules are those of tests/T07/logs/verifier_spec.md and of T07.md sections 1-3 (frozen; T07.md wins).
Style and structure forked from analysis/verify_t06.py (read for style only).

Usage (from AA/, as `python -I`):
    python -I analysis/verify_t07.py                                   # headline evidence + self-test on a corrupted copy
    python -I analysis/verify_t07.py --evidence tests/T07/evidence/smoke
    python -I analysis/verify_t07.py --evidence DIR --no-selftest --out FILE --weights raw|norm|auto

Exit code 0 only if rows were compared, none failed, none were missing, and (in the default run) the deliberately corrupted copy was
detected by the relevant checks. A missing evidence file is reported as MISSING (a failure).
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
COSTS = [0.0, 20.8, 50.0]
HEADLINE_COST = 20.8
END = pd.Timestamp("2026-10-30")               # window end (T07.md header, section 3 step 1)
LIVE_START = pd.Timestamp("2021-11-01")
T06_LAST = pd.Timestamp("2026-10-22")          # T06's window end (shared sessions for C-t06)
TOL = 1e-9                                     # relative tolerance on NAVs and statistics
TOL_REGRESSION = 1e-12
TOL_CURVE = 1e-6                               # float32 draw curves (the spec's 1e-9 cannot be met by float32 storage)
G0_OVERALL_PP = 0.25
G0_YEAR_PP = 0.5
BANDS = ["Large", "Mid", "Small and below"]
BAND_INDEX = {"Large": 0, "Mid": 1, "Small and below": 2}
INDEX_NAMES = ["Nifty100", "MC100", "SC100"]
INDEX_TO_BAND = {"NIFTY 100": "Large", "NIFTY MIDCAP 150": "Mid", "NIFTY SMALLCAP 250": "Small and below",
                 "NIFTY MICROCAP 250": "Small and below"}
SCRATCH = Path(r"C:\Users\manur\AppData\Local\Temp\claude\d384933f9ddb0ecb\ea0af580-06c7-4ce3-8c4f-77d4828a38b0\scratchpad")
APPROVED_MD = AA / "data" / "APPROVED_DATA.md"
T06_EVIDENCE = AA / "tests" / "T06" / "evidence" / "headline"
# approved rows whose through-date is deliberately earlier than the window's end (APPROVED_DATA.md "Latest usable date by role")
THROUGH_EXEMPT_IDS = {"D12", "D19", "D05"}
EXT = "Historical Data/extended_2026-11-12"
READ_KW = dict(keep_default_na=False, na_values=[""])     # D20-D23: only the empty string is null


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
READS = {}          # relative path -> full sha256 of every file this verifier read (filled by C-data)
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
    """T07.md section 3 step 7: the de-spiked OHLC4 where the MCX file has a bar (open clipped, high and low clipped to the close x
    (1 +- (MCX range / MCX close + 0.5%))), the raw OHLC4 after the MCX file ends."""
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
    rd(f"Historical Data/frozen_2026-09-25/Rebalance_history/Rebalance_history_by_scid_{p}.csv")     # registered for C-data
    return m["avail"].values, cols, Wraw, isin_of, [str(pd.Timestamp(x).date()) for x in dropped]


# ----------------------------------------------------------------------------------------
# the tag rule (own implementation of T07.md section 3 "The tag rule")
# ----------------------------------------------------------------------------------------
def rank_band(r):
    return "Large" if r <= 100 else ("Mid" if r <= 250 else "Small and below")


class OwnTags:
    """cutoff = first D21 snapshot. On or after it: the latest D21 snapshot on or before the date, band of the index the stock is
    listed in; a stock in none of the four indices falls back to the rank rule ('nonmember_rank'). Before it: the rank on the latest D20
    snapshot on or before the date (ordinary shares, market cap descending, ties by quote_id, 1-100 Large, 101-250 Mid, above 250 Small
    and below; null market cap not ranked). A stock is found by its ISIN or any ISIN sharing its quote_id (D22 isin and new_isin; also
    the D20 isin-quote_id pairs). Not found = 'Small and below', 'unranked'. No snapshot dated after the date is ever used."""

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
        self._rank_cache = {}
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
        pairs = pd.DataFrame({"q": self.q20, "i": self.isin20}).dropna().drop_duplicates()
        for q, x in zip(pairs["q"].values, pairs["i"].values):
            self.q_of_isin[x].add(int(q)); self.isins_of_q[int(q)].add(x)
        self._grp = {}
        self.multi_band = 0

    def group(self, isin):
        if isin not in self._grp:
            qs = set(self.q_of_isin.get(isin, set()))
            gi = {isin}
            for q in qs:
                gi |= self.isins_of_q[q]
            self._grp[isin] = (gi, qs)
        return self._grp[isin]

    def ranks_at(self, t):
        """(positions, rank array) of the snapshot t; rank 0 = not ranked (null market cap)."""
        if t not in self._rank_cache:
            pos = self.pos20[t]
            m = self.mcap20[pos]
            q = self.q20[pos]
            ok = np.flatnonzero(~np.isnan(m))
            order = np.lexsort((q[ok], -m[ok]))                 # market cap descending, ties by quote_id ascending
            rank = np.zeros(len(pos), dtype=np.int64)
            rank[ok[order]] = np.arange(1, len(ok) + 1)
            self._rank_cache[t] = (pos, rank)
        return self._rank_cache[t]

    def rank_lookup(self, gi, qs, asof, isin):
        i = np.searchsorted(self.dates20, np.datetime64(asof, "ns"), side="right") - 1
        if i < 0:
            return None
        t = self.dates20[i]
        pos, rank = self.ranks_at(t)
        best = None
        isn = self.isin20[pos]
        qq = self.q20[pos]
        cand = [k for k in range(len(pos)) if (isn[k] in gi if isn[k] is not None else False) or int(qq[k]) in qs]
        # prefer the exact ISIN match, then any ranked row (lowest rank)
        cand.sort(key=lambda k: (0 if isn[k] == isin else 1, rank[k] if rank[k] > 0 else 10 ** 9))
        for k in cand:
            if rank[k] > 0:
                best = (t, int(rank[k]))
                break
        return best

    def tag(self, isin, asof):
        asof = np.datetime64(pd.Timestamp(asof), "ns")
        gi, qs = self.group(isin)
        if asof >= self.cutoff:
            j = np.searchsorted(self.dates21, asof, side="right") - 1
            t = self.dates21[j]
            dd = self.mem[t]
            hit = [x for x in ([isin] + sorted(gi - {isin})) if x in dd]
            if hit:
                bands = dd[hit[0]]
                if len(set(bands)) > 1:
                    self.multi_band += 1
                band = sorted(bands, key=lambda b: BAND_INDEX[b])[0]
                return dict(band=band, source="membership", snapshot=str(pd.Timestamp(t).date()), detail=f"isin={hit[0]}")
            r = self.rank_lookup(gi, qs, asof, isin)
            src = "nonmember_rank"
        else:
            r = self.rank_lookup(gi, qs, asof, isin)
            src = "rank"
        if r is None:
            return dict(band="Small and below", source="unranked", snapshot="", detail="not found")
        return dict(band=rank_band(r[1]), source=src, snapshot=str(pd.Timestamp(r[0]).date()), detail=f"rank={r[1]}")


# ----------------------------------------------------------------------------------------
# book construction and windows
# ----------------------------------------------------------------------------------------
def build_book(p, gold_fill, gold_close, mcx_last, lbes, liq, corr):
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
    eff = np.searchsorted(cal.values, avail, side="left")        # first session on or after availableDate
    basket_at = {}
    for k in range(len(avail)):
        if eff[k] < n_full:
            basket_at[int(eff[k])] = k
    isins = [isin_of[s] for s in S_cols]
    return dict(p=p, t0=t0, cal=cal, n_full=n_full, S=S_cols, isins=isins, C=C, Cn=Cn, F=F, gc=gclose, gf=gfill, L=L, L2=L2,
                Wraw=Wraw, basket_at_full=basket_at, avail=avail, d18=d18, Ffl=fill[S_cols], dropped=dropped, pub=nav)


def make_view(B, a, b, cash="lbes"):
    """Sessions [a, b) of book B; session a is the window's T0 (NAV 1.000 at its close). W = listed weights, Wn = rows renormalised."""
    full = B["basket_at_full"]
    rel = {k - a: v for k, v in full.items() if k < b}
    keys = sorted(rel)
    k_t0 = max(k for k in keys if k <= 0)
    k0 = rel[k_t0]
    first_d18 = B["d18"][np.searchsorted(B["d18"].values, B["avail"][k0], side="left")]
    W = B["Wraw"]
    return dict(p=B["p"], cal=B["cal"][a:b], n=b - a, a=a, S=B["S"], isins=B["isins"], C=B["C"][a:b], Cn=B["Cn"][a:b], F=B["F"][a:b],
                gc=B["gc"][a:b], gf=B["gf"][a:b], L=(B["L"] if cash == "lbes" else B["L2"])[a:b], W=W,
                Wn=W / W.sum(axis=1, keepdims=True), avail=B["avail"], basket_at=rel, b_idx=keys,
                changes=[k for k in keys if 0 < k < b - a], k0=k0, init_fill=B["Ffl"].loc[first_d18].values, first_d18=first_d18)


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
                         all_three_buy=bool(buy), state=int(buy), disagree=bool(not buy and not sell)))
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------------------------
# events (T07.md section 3 steps 4-6)
# ----------------------------------------------------------------------------------------
RETAG_SKIPPED_BASKET = True      # coordinator's reading (2026-11-12): a basket that arrives while nothing is held trades nothing but its tags (as of the session before) become the current tags


def derive_events(V, dec, tagger, mode="rule"):
    """mode: 'rule' (tags), 'tied' (whole-book switch: every stock follows IN iff all three BUY), 'allin' (nothing ever dropped),
    'allout' (everything dropped). Returns (events, pit counters)."""
    n = V["n"]
    cal = V["cal"]
    didx = dec["decision_idx"].values
    D = len(dec)
    signs = np.stack([dec["sign_Nifty100"].values, dec["sign_MC100"].values, dec["sign_SC100"].values], axis=1)
    buy_all = dec["all_three_buy"].values.astype(bool)
    pit = dict(decisions_checked=0, decision_violations=0, tags_checked=0, tag_violations=0, trades_checked=0, trade_violations=0,
               t0_exempt_tags=0)
    for j in range(D):                                  # every decision reads Master rows dated on or before the decision date
        pit["decisions_checked"] += 1
        for c in ("label_Nifty100", "label_MC100", "label_SC100"):
            if pd.Timestamp(dec[c].iloc[j]) > pd.Timestamp(dec["decision_date"].iloc[j]):
                pit["decision_violations"] += 1
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
                tg = dict(band="Large", source="n/a", snapshot="", detail="")
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
    for s in sorted(set(sig_session) | set(V["changes"])):
        sig = False
        if s in sig_session:
            j = sig_session[s]
            newdrop = set(int(si) for si, bd in zip(cur_held, cur_bands) if not on(j, bd))
            sig = newdrop != cur_dropped
        bsk = (s in set(V["changes"])) and cur_has_kept
        if RETAG_SKIPPED_BASKET and mode == "rule" and (s in set(V["changes"])) and not cur_has_kept and not sig:
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


def event_numbers(V, ev, wmode):
    """Counts and listed-weight sums of an event (the weights are the chosen convention's)."""
    W = V["Wn"] if wmode == "norm" else V["W"]
    w = W[ev["k"]][ev["held"]]
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
# the simulation (T07.md section 3 steps 4(i), 6, 7, 8)
# ----------------------------------------------------------------------------------------
def simulate(V, evs, bps, wmode="raw", mixf=None, positions=False):
    """evs[0] is the initial event (idx 0); the others are trade sessions. Per event: idx, k (basket row), kfull (kept mask over the
    view's stocks), kind. mixf: constant-mix comparator (stock share f in the basket's stocks, half the rest in each of GOLDBEES and cash)."""
    n = V["n"]
    C, Cn, F = V["C"], V["Cn"], V["F"]
    gc, gf, L = V["gc"], V["gf"], V["L"]
    Wsel = V["Wn"] if wmode == "norm" else V["W"]
    S = len(V["S"])
    e0 = evs[0]
    assert e0["idx"] == 0
    w0 = V["W"][e0["k"]]
    sh0 = np.where(w0 > 0, w0 / V["init_fill"], 0.0)
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
        gu = tgt_g * f / gf[i]
        cu = tgt_c * f / L[i]
        segs.append((i, shares.copy(), gu, cu))
        ts = float(tgt_stock.sum())
        trades.append(dict(idx=int(i), date=str(V["cal"][i].date()), kind=ev["kind"], e_after=ts / (ts + 2.0 * tgt_g) if ts + tgt_g > 0 else 0.0,
                           e_after_alt=1.0 - s_, basket_eff=str(pd.Timestamp(V["avail"][ev["k"]]).date()),
                           basket_eff_session=str(V["cal"][ev["bkey"]].date()) if ev.get("bkey", 0) >= 0 else None,
                           V=float(Vv), traded=float(traded), cost=float(cost)))
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


# ----------------------------------------------------------------------------------------
# allowed subsets, samplers, oracle (own code)
# ----------------------------------------------------------------------------------------
def subset_sums(w):
    """sums[mask] = total of w over the bits set in mask (bit i = stock i)."""
    s = np.zeros(1)
    for x in w:
        s = np.concatenate([s, s + x])
    return s


def allowed_subsets(w, Dw, tol=1e-12):
    """Every subset X (bitmask, increasing) with |sum w(X) - Dw| <= tau, tau = half the smallest listed weight. n <= 16."""
    w = np.asarray(w, dtype=float)
    tau = 0.5 * float(w.min())
    sums = subset_sums(w)
    d = np.abs(sums - Dw)
    A = np.flatnonzero(d <= tau + tol)
    return A, tau, float(np.min(np.abs(d[A] - tau))) if len(A) else float("inf")


def mask_of(drop_bool):
    return int(sum(1 << i for i, b in enumerate(drop_bool) if b))


def n46_draw(evinfo, draw_id, book_no):
    """One N4.6 draw (T07.md section 3 step 11): held stocks in ISIN order, one uniform per event in event order, A[floor(u |A|)].
    evinfo: list of dicts with sorted-by-ISIN weights and D. Returns a list of masks (bit i = i-th stock in ISIN order)."""
    rng = np.random.default_rng([7, draw_id, book_no])
    out = []
    for e in evinfo:
        A = e["A"]
        u = rng.random()
        out.append(int(A[int(math.floor(u * len(A)))]))
    return out


def n48_draw(evinfo, isins_all, draw_id, book_no):
    """One N4.8 draw: one uniform score per ISIN the book ever holds (ISIN order); at each event rank held stocks by score (descending),
    the first n_L Large, next n_M Mid, rest Small and below; dropped iff the label's band signal is SELL. Returns (labels, drops) per event
    as dicts isin -> label / dropped."""
    rng = np.random.default_rng([8, draw_id, book_no])
    score = dict(zip(isins_all, rng.random(len(isins_all))))
    res = []
    for e in evinfo:
        order = sorted(e["isins"], key=lambda x: (-score[x], x))
        lab = {}
        for r, isn in enumerate(order):
            lab[isn] = 0 if r < e["n_large"] else (1 if r < e["n_large"] + e["n_mid"] else 2)
        res.append(lab)
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
    """booleans as 'true' / 'false' / '<na>' whatever their stored form"""
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


def compare_frames(chk, mine, ev, keys, num_cols=(), str_cols=(), tol=TOL, part=None, missing_ok_evidence_only=False):
    """Outer-join on keys; rows on both sides are compared; others are missing (a failure)."""
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
    if missing_ok_evidence_only:
        miss = miss[miss["_merge"] == "left_only"]
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
# derive everything that does not depend on the evidence
# ----------------------------------------------------------------------------------------
class Derived:
    """Books, views, decisions, events (all modes), simulations on demand (cached)."""

    def __init__(self, books=BOOKS, wmode="raw", verbose=True):
        self.books = list(books)
        self.wmode = wmode
        t = time.time()
        self.masters = load_masters()
        g, mcx = load_gold()
        gfill, gclose, mcx_last = despiked_goldbees_fill(g, mcx)
        lbes = load_lbes()
        liq = load_liquidcase()
        corr = load_corrections()
        self.tagger = OwnTags()
        if verbose:
            print(f"[{time.time()-t:6.1f}s] tag sources loaded (cutoff {pd.Timestamp(self.tagger.cutoff).date()})", flush=True)
        self.B, self.V, self.dec, self.ev, self.pit = {}, {}, {}, {}, {}
        for p in self.books:
            B = build_book(p, gfill, gclose, mcx_last, lbes, liq, corr)
            self.B[p] = B
            n = B["n_full"]
            a_live = int(np.searchsorted(B["cal"].values, np.datetime64(LIVE_START), side="left"))
            B["a_live"] = a_live
            for window, a in (("full", 0), ("live", a_live)):
                for cash in ("lbes", "liq"):
                    self.V[(p, window, cash)] = make_view(B, a, n, cash)
                Vw = self.V[(p, window, "lbes")]
                self.dec[(p, window)] = decisions_for_window(Vw, window, self.masters)
            if verbose:
                print(f"[{time.time()-t:6.1f}s] {p}: built (sessions {n}, live from {B['cal'][a_live].date()}, stocks {len(B['S'])}, "
                      f"baskets {len(B['basket_at_full'])}, skipped baskets dropped {B['dropped']})", flush=True)
        self._events = {}
        self._sims = {}
        self.t = t

    def events(self, p, window, mode):
        key = (p, window, mode)
        if key not in self._events:
            self._events[key] = derive_events(self.V[(p, window, "lbes")], self.dec[(p, window)], self.tagger, mode)
        return self._events[key]

    def engine_events(self, p, window, mode, wmode=None):
        evs, _ = self.events(p, window, mode)
        return evs

    def sim(self, p, window, cash, kind, bps, positions=False, mix_variant="a", wmode=None):
        wmode = wmode or self.wmode
        key = (p, window, cash, kind, round(float(bps), 4), positions, mix_variant, wmode)
        if key in self._sims:
            return self._sims[key]
        V = self.V[(p, window, cash)]
        mode = {"segment": "rule", "whole_book": "tied", "parent": "allin", "sleeve100": "allout"}.get(kind)
        if kind == "constant_mix":
            rule_evs, _ = self.events(p, window, "rule")
            if mix_variant == "a":
                r = self.sim(p, window, cash, "segment", bps, wmode=wmode)
            else:
                r = self.sim(p, window, cash, "segment", 0.0, wmode=wmode)
            f = float(np.mean(r["stock_value"] / r["nav"]))
            res = simulate(V, rule_evs, bps, wmode, mixf=f, positions=positions)
            res["mixf"] = f
        else:
            evs, _ = self.events(p, window, mode)
            res = simulate(V, evs, bps, wmode, positions=positions)
        self._sims[key] = res
        return res


def always_in_rows(p, nav_m, pub):
    pub = pub / pub.iloc[0]
    yrs = (len(nav_m) - 1) / 252.0
    cg_m = nav_m.iloc[-1] ** (1 / yrs) - 1
    cg_p = pub.iloc[-1] ** (1 / yrs) - 1
    rows = [dict(book=p, scope="overall", gap_pp=float((cg_m - cg_p) * 100), limit_pp=G0_OVERALL_PP)]
    yc = (nav_m.index[-1] - nav_m.index[0]).days / 365.25          # the same gap with calendar years (the G0 gate of the parent rebuild)
    rows.append(dict(book=p, scope="overall_calendar_years", gap_pp=float((nav_m.iloc[-1] ** (1 / yc) - pub.iloc[-1] ** (1 / yc)) * 100),
                     limit_pp=G0_OVERALL_PP))
    ye_m = nav_m.groupby(nav_m.index.year).last()
    ye_p = pub.groupby(pub.index.year).last()
    ym = ye_m / ye_m.shift(1).fillna(1.0) - 1
    yp = ye_p / ye_p.shift(1).fillna(1.0) - 1
    for y in ym.index:
        rows.append(dict(book=p, scope=str(y), gap_pp=float((ym[y] - yp[y]) * 100), limit_pp=G0_YEAR_PP))
    return rows


def event_frames(DV, p, window):
    """Expected events.csv rows and event_stocks.csv rows of one book and window (own derivation)."""
    V = DV.V[(p, window, "lbes")]
    evs, _ = DV.events(p, window, "rule")
    dec = DV.dec[(p, window)]
    rule_sim = DV.sim(p, window, "lbes", "segment", HEADLINE_COST)
    tr = {t["idx"]: t for t in rule_sim["trades"]}
    erows, srows = [], []
    for no, ev in enumerate(evs):
        num = event_numbers(V, ev, DV.wmode)
        w = (V["Wn"] if DV.wmode == "norm" else V["W"])[ev["k"]]
        A, tau, _ = allowed_subsets(w[ev["held"]], num["dropped_weight"]) if 0 < len(ev["held"]) <= 16 else (np.array([]), num["tau"], 0)
        j = ev["j"]
        info_idx = ev["info_idx"]
        t = tr.get(ev["idx"], {})
        erows.append(dict(book=p, window=window, event_no=no, kind=ev["kind"], trade_date=str(V["cal"][ev["idx"]].date()), trade_idx=ev["idx"],
                          info_date=str(V["cal"][info_idx].date()), state_Nifty100=dec["sign_Nifty100"].iloc[j],
                          state_MC100=dec["sign_MC100"].iloc[j], state_SC100=dec["sign_SC100"].iloc[j],
                          basket_eff=str(pd.Timestamp(V["avail"][ev["k"]]).date()),
                          basket_eff_session=str(V["cal"][ev["bkey"]].date()), n_allowed_subsets=int(len(A)),
                          V_before=t.get("V", np.nan), traded=t.get("traded", np.nan), cost=t.get("cost", np.nan), **num))
        for si, tg, kp in zip(ev["held"], ev["tags"], ev["kept"]):
            srows.append(dict(book=p, window=window, event_no=no, trade_date=str(V["cal"][ev["idx"]].date()),
                              info_date=str(V["cal"][info_idx].date()), isin=V["isins"][si], stock=V["S"][si], listed_weight=float(w[si]),
                              band=tg["band"], tag_source=tg["source"], tag_snapshot=tg["snapshot"], kept=bool(kp),
                              band_sign=dec[["sign_Nifty100", "sign_MC100", "sign_SC100"][BAND_INDEX[tg["band"]]]].iloc[j]))
    return pd.DataFrame(erows), pd.DataFrame(srows)


def derive_sets(DV):
    out = dict(events={}, stocks={}, stats=[], always_in=[], rule={})
    for p in DV.books:
        for window in ("full", "live"):
            e, s = event_frames(DV, p, window)
            out["events"][(p, window)] = e
            out["stocks"][(p, window)] = s
        nav_m = pd.Series(DV.sim(p, "full", "lbes", "parent", 0.0)["nav"], index=DV.V[(p, "full", "lbes")]["cal"])
        out["always_in"].extend(always_in_rows(p, nav_m, DV.B[p]["pub"].loc[nav_m.index]))
    return out


# ----------------------------------------------------------------------------------------
# evidence loading (a missing file is None, never an exception)
# ----------------------------------------------------------------------------------------
EVIDENCE_FILES = ["inputs.csv", "decisions.csv", "events.csv", "event_stocks.csv", "stats.csv", "draws.csv", "draw_drops.npz",
                  "draw_labels.npz", "draw_curves_20.8.npz", "daily_nav.csv", "trades.csv", "positions.csv", "g_engine.csv",
                  "count_table.json", "controls_oracle.json"]


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


def infer_weights(E):
    """'raw' if the engine's listed weights sum to 0.9996-1.0005 (not renormalised), 'norm' if they sum to 1 on every event."""
    ev = E.get("events.csv")
    if ev is None or "sum_weights" not in ev.columns:
        return "norm", "no events.csv/sum_weights: renormalised rows (T06's convention; coordinator's clarification 2026-11-12)"
    sw = ev["sum_weights"].astype(float).values
    if np.all(np.abs(sw - 1.0) < 1e-13):
        return "norm", "events.csv sum_weights equal 1 on every event (listed weights renormalised, as in T06 and as ruled by the coordinator on 2026-11-12; the frozen text's wording says not)"
    return "raw", f"events.csv sum_weights range {sw.min():.6f}..{sw.max():.6f} (not renormalised, as the frozen text says)"


# ----------------------------------------------------------------------------------------
# helpers to align the engine's draw arrays with my own event-stock rows
# ----------------------------------------------------------------------------------------
def draw_row_map(DV, p, window, E_stocks, mine_stocks):
    """For the engine's event_stocks rows of (book, window) in file order: the index of the matching row of my own event_stocks (by
    trade_date and ISIN), or -1."""
    ev = E_stocks[(E_stocks["book"] == p) & (E_stocks["window"] == window)]
    mine = mine_stocks[(p, window)].reset_index(drop=True)
    key_to_i = {(d, i): k for k, (d, i) in enumerate(zip(mine["trade_date"].values, mine["isin"].values))}
    td = dstr(ev["trade_date"]).values
    return np.array([key_to_i.get((d, i), -1) for d, i in zip(td, ev["isin"].values)], dtype=int), mine


def sample_ids(book, typ, pool, n_first=20, n_rand=20, seed=20261112):
    rng = np.random.default_rng([seed, BOOKS.index(book), 0 if typ == "N4.6" else 1])
    first = list(range(min(n_first, pool)))
    rest = np.arange(len(first), pool)
    k = min(n_rand, len(rest))
    return first + (sorted(rng.choice(rest, size=k, replace=False).tolist()) if k > 0 else [])


# ----------------------------------------------------------------------------------------
# tolerant readers of the two JSON files whose exact layout the contract does not fix
# ----------------------------------------------------------------------------------------
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
    """List of per-event records of one book (and window) inside count_table.json, tolerant of nesting."""
    if isinstance(entry, dict) and window in entry:
        entry = entry[window]
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


def oracle_choice(DV, p, variant):
    """V7 oracle (T07.md section 2): at each event the allowed subset with the lowest sum of listed weight x realised log return from
    the trade session to the next event's trade session (the last event: to the window's last session); ties to the lowest bitmask.
    variant 'fill': fill price (OHLC4) to fill price, last event to the last close; 'close': close to close. Returns (events, stats)."""
    V = DV.V[(p, "full", "lbes")]
    evs, _ = DV.events(p, "full", "rule")
    n = V["n"]
    new = []
    for no, e in enumerate(evs):
        w = (V["Wn"] if DV.wmode == "norm" else V["W"])[e["k"]][e["held"]]
        num = event_numbers(V, e, DV.wmode)
        A, tau, _ = allowed_subsets(w, num["dropped_weight"])
        nxt = evs[no + 1]["idx"] if no + 1 < len(evs) else n - 1
        s_ = e["idx"]
        held = e["held"]
        if variant == "fill":
            p0 = V["F"][s_][held] if s_ > 0 else V["C"][0][held]          # the T0 position is struck at T0's closes
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
    res = simulate(V, new, HEADLINE_COST, DV.wmode)
    return new, stats_of(res["nav"])["cagr"]


def oracle_cagr(DV, p, variant):
    return oracle_choice(DV, p, variant)[1]


def event_infos(DV, p, window):
    """Per event of the rule: held stocks in ISIN order, their listed weights, the allowed N4.6 subsets (bitmasks over that order)."""
    V = DV.V[(p, window, "lbes")]
    evs, _ = DV.events(p, window, "rule")
    Wsel = V["Wn"] if DV.wmode == "norm" else V["W"]
    out = []
    for e in evs:
        held = sorted(((V["isins"][si], si) for si in e["held"]))
        w = np.array([Wsel[e["k"]][si] for _, si in held])
        kept_map = dict(zip(e["held"].tolist(), e["kept"].tolist()))
        Dw = float(sum(x for (_, si), x in zip(held, w) if not kept_map[si]))
        A, tau, _ = allowed_subsets(w, Dw)
        nums = event_numbers(V, e, DV.wmode)
        out.append(dict(A=A, isins=[i for i, _ in held], sis=[si for _, si in held], w=w, n_large=nums["n_large"], n_mid=nums["n_mid"],
                        n_small=nums["n_small"]))
    return out


# ----------------------------------------------------------------------------------------
# the checks
# ----------------------------------------------------------------------------------------
def compare_all(DV, SETS, E, wnote, run_name):
    C = {}
    books = DV.books
    end_dates = {p: DV.V[(p, "full", "lbes")]["cal"][-1] for p in books}
    end = max(end_dates.values())

    # ------------------------------------------------------------------ C-data
    def c_data(c):
        inp = E.get("inputs.csv", c)
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
        not_listed = sorted(set(READS) - listed)
        if not_listed:
            c.notes.append(f"{len(not_listed)} file(s) the verifier read are not in inputs.csv (not a failure under the spec): {not_listed[:4]}")
        c.notes.append(f"through-date exempt roles (earlier than the window by design): {sorted(THROUGH_EXEMPT_IDS)}")
    run_check(C, "C-data", c_data)

    # ------------------------------------------------------------------ C-dec
    def c_dec(c):
        ev = E.get("decisions.csv", c)
        if ev is None:
            return
        ev = with_window(ev)
        mine = pd.concat([DV.dec[(p, w)] for p in books for w in ("full", "live")], ignore_index=True)
        mine = mine[mine["window"].isin(set(ev["window"]))]
        ev = ev[ev["book"].isin(books)]
        num = [x for x in ("decision_idx", "label_age_days") if x in ev.columns]
        strc = [x for x in ("decision_date", "trade_date", "sign_Nifty100", "sign_MC100", "sign_SC100", "label_Nifty100", "label_MC100",
                            "label_SC100", "latest_label") if x in ev.columns]
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
        c.notes.append(f"decisions compared in windows {sorted(set(ev['window']))}; the evidence has {len(ev)} rows")
    run_check(C, "C-dec", c_dec)

    # ------------------------------------------------------------------ C-tag
    def c_tag(c):
        es = E.get("event_stocks.csv", c)
        if es is None:
            return
        es = with_window(es)
        mine = pd.concat([SETS["stocks"][(p, w)] for p in books for w in ("full", "live")], ignore_index=True)
        mine = mine[mine["window"].isin(set(es["window"]))].copy()
        es = es[es["book"].isin(books)].copy()
        mine["trade_date"] = dstr(mine["trade_date"]); es["trade_date"] = dstr(es["trade_date"])
        mine["info_date"] = dstr(mine["info_date"]); es["info_date"] = dstr(es["info_date"])
        mine["tag_snapshot"] = dstr(mine["tag_snapshot"]); es["tag_snapshot"] = dstr(es["tag_snapshot"])
        mine["kept"] = bstr(mine["kept"]); es["kept"] = bstr(es["kept"])
        # unranked rows carry no snapshot: compare the snapshot only where I have one
        unr = mine["tag_source"] == "unranked"
        mine.loc[unr, "tag_snapshot"] = "<NA>"; esu = es["tag_source"].astype(str) == "unranked"
        es.loc[esu, "tag_snapshot"] = "<NA>"
        compare_frames(c, mine, es, ["book", "window", "trade_date", "isin"], num_cols=["listed_weight"],
                       str_cols=["band", "tag_source", "tag_snapshot", "kept", "info_date"], tol=1e-9, part="event_stocks")
        # band_signal: BUY/SELL of the band's index, or the index name (the contract names both ways)
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
        c.notes.append(f"weights convention used for listed_weight: {DV.wmode}; {wnote}")
        c.notes.append("tag_source counts (mine, rows): " + json.dumps(mine["tag_source"].value_counts().to_dict()))
    run_check(C, "C-tag", c_tag)

    # ------------------------------------------------------------------ C-events
    def c_events(c):
        ev = E.get("events.csv", c)
        if ev is None:
            return
        ev = with_window(ev)
        mine = pd.concat([SETS["events"][(p, w)] for p in books for w in ("full", "live")], ignore_index=True)
        mine = mine[mine["window"].isin(set(ev["window"]))].copy()
        ev = ev[ev["book"].isin(books)].copy()
        mine["trade_date"] = dstr(mine["trade_date"]); ev["trade_date"] = dstr(ev["trade_date"])
        mine["info_date"] = dstr(mine["info_date"]); ev["info_date"] = dstr(ev["info_date"])
        for col in ("partial",):
            mine[col] = bstr(mine[col]); ev[col] = bstr(ev[col])
        # basket_eff: the availableDate of the basket in force (contract); the effective session is accepted too (compared below)
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
            c.notes.append(f"basket_eff matches the availableDate on {int((j['be'] == j['be_avail']).sum())} rows, the effective session on {int((j['be'] == j['be_sess']).sum())}")
        # events per book and window
        for (p, w), g in mine.groupby(["book", "window"]):
            ne = int(((ev["book"] == p) & (ev["window"] == w)).sum())
            c.compared += 1
            c.count("event_count", 1, int(ne != len(g)))
            if ne != len(g):
                c.failed += 1; c.fail(f"{p} {w}: evidence has {ne} events, verifier {len(g)}")
        c.notes.append("events (full): " + ", ".join(f"{p} {int(((mine['book']==p)&(mine['window']=='full')).sum())}" for p in books)
                       + "; with 0<share<1 (partial): " + ", ".join(f"{p} {int(((mine['book']==p)&(mine['window']=='full')&(mine['partial']=='true')).sum())}" for p in books))
    run_check(C, "C-events", c_events)

    # ------------------------------------------------------------------ C-target (events V/traded/cost, trades, positions)
    def trades_frame(p, kind_run, cost, window="full", cash="lbes"):
        res = DV.sim(p, window, cash, kind_run, cost, positions=False)
        return res

    RUNS = {"segment": "segment", "whole_book": "whole_book", "parent": "parent", "constant_mix": "constant_mix", "sleeve100": "sleeve100"}

    def c_target(c):
        ev = E.get("events.csv")
        if ev is not None:
            ev = with_window(ev)
            mine = pd.concat([SETS["events"][(p, w)] for p in books for w in ("full", "live")], ignore_index=True)
            mine = mine[mine["trade_idx"] > 0].copy(); mine["trade_date"] = dstr(mine["trade_date"])
            e2 = ev[ev["book"].isin(books)].copy(); e2["trade_date"] = dstr(e2["trade_date"])
            e2 = e2[e2["trade_idx"].astype(float) > 0] if "trade_idx" in e2.columns else e2
            cols = [x for x in ("V_before", "traded", "cost") if x in e2.columns]
            if cols:
                compare_frames(c, mine[["book", "window", "trade_date"] + cols], e2[["book", "window", "trade_date"] + cols],
                               ["book", "window", "trade_date"], num_cols=cols, tol=TOL, part="events_V_traded_cost")
        tr = E.get("trades.csv", c)
        ps = E.get("positions.csv", c)
        for nm, evf in (("trades.csv", tr), ("positions.csv", ps)):
            pass
        if tr is not None:
            rows = []
            for p in books:
                for bps in COSTS:
                    for run in RUNS:
                        for t in DV.sim(p, "full", "lbes", run, bps)["trades"]:
                            rows.append(dict(book=p, cost_bps=bps, run=run, **t))
            mine = pd.DataFrame(rows)
            ev = tr[tr["book"].isin(books)].copy()
            ev["cost_bps"] = r4(ev["cost_bps"])
            if "idx" in ev.columns:
                ev = ev[ev["idx"].astype(float) > 0]
            ev["date"] = dstr(ev["date"]); mine["date"] = dstr(mine["date"])
            cols = [x for x in ("V", "traded", "cost", "nav_close_after", "idx") if x in ev.columns]
            compare_frames(c, mine, ev, ["book", "cost_bps", "run", "date"], num_cols=cols, tol=TOL, part="trades")
            # e_after: the stock share after the trade, accepted as stock value / post-trade targets or as 1 - s
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
                        res = DV.sim(p, "full", "lbes", run, bps, positions=True)
                        for dt, nm, u in res["positions"]:
                            rows.append(dict(book=p, cost_bps=bps, run=run, date=dt, instrument=nm, units=u))
            mine = pd.DataFrame(rows)
            ev = ps[ps["book"].isin(books)].copy()
            ev["cost_bps"] = r4(ev["cost_bps"])
            t0s = {p: str(DV.V[(p, "full", "lbes")]["cal"][0].date()) for p in books}
            ev["date"] = dstr(ev["date"])
            if not (ev["date"] == ev["book"].map(t0s)).any():          # the engine writes positions after trades only: drop my T0 rows
                mine = mine[mine["date"] != mine["book"].map(t0s)]
            # cash instrument name is not fixed by the contract: treat anything that is not a stock or GOLDBEES as the cash leg
            stocks_all = set(sum([DV.V[(p, "full", "lbes")]["S"] for p in books], []))
            ev["instrument"] = ev["instrument"].map(lambda x: x if (x in stocks_all or x == "GOLDBEES") else "CASH")
            mine = mine[np.abs(mine["units"]) > 0]; ev = ev[np.abs(ev["units"].astype(float)) > 0]
            compare_frames(c, mine, ev, ["book", "cost_bps", "run", "date", "instrument"], num_cols=["units"], tol=TOL, part="positions")
    run_check(C, "C-target", c_target)

    # ------------------------------------------------------------------ C-nav (daily NAVs and statistics)
    def c_nav(c):
        dn = E.get("daily_nav.csv", c)
        if dn is not None:
            rows = []
            for p in books:
                cal = DV.V[(p, "full", "lbes")]["cal"]
                ds = [str(d.date()) for d in cal]
                for bps in COSTS:
                    for run in RUNS:
                        rows.append(pd.DataFrame(dict(book=p, date=ds, cost_bps=bps, run=run, nav=DV.sim(p, "full", "lbes", run, bps)["nav"])))
            mine = pd.concat(rows, ignore_index=True)
            ev = dn[dn["book"].isin(books)].copy()
            ev["cost_bps"] = r4(ev["cost_bps"]); ev["date"] = dstr(ev["date"])
            ev = ev[ev["run"].isin(RUNS)]
            compare_frames(c, mine, ev, ["book", "run", "cost_bps", "date"], num_cols=["nav"], tol=TOL, part="daily_nav")
            # the end NAV of the rule at every cost within 1e-9 (the spec's headline comparison)
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
        if st is not None:
            st = with_window(st)
            st = st[st["book"].isin(books)].copy()
            st["cost_bps"] = r4(st["cost_bps"])
            rows = []
            variants_used = defaultdict(int)
            exp = set()
            for p in books:
                for bps in COSTS:
                    for kind in list(RUNS) + ["published_parent"]:
                        exp.add((p, "full", "lbes", bps, kind))
                exp.add((p, "full", "liq", HEADLINE_COST, "segment")); exp.add((p, "live", "lbes", HEADLINE_COST, "segment"))
            have = set(zip(st["book"], st["window"], st["cash"], st["cost_bps"], st["kind"]))
            for key in sorted(exp - have):
                c.miss(f"stats.csv row {key}")
            for _, r in st.iterrows():
                p, w, ca, bps, kind = r["book"], r["window"], r["cash"], float(r["cost_bps"]), r["kind"]
                if kind == "published_parent":
                    V = DV.V[(p, w, "lbes")]
                    pub = DV.B[p]["pub"].loc[V["cal"]].values
                    mine = stats_of(pub / pub[0])
                    cand = [mine]
                elif kind == "constant_mix":
                    cand = []
                    for var in ("a", "b"):
                        res = DV.sim(p, w, ca, "constant_mix", bps, mix_variant=var)
                        s_ = stats_of(res["nav"]); s_["trades"] = len(res["trades"]); s_["cost_paid"] = sum(t["cost"] for t in res["trades"]); s_["_var"] = var
                        cand.append(s_)
                elif kind in RUNS:
                    res = DV.sim(p, w, ca, kind, bps)
                    s_ = stats_of(res["nav"]); s_["trades"] = len(res["trades"]); s_["cost_paid"] = sum(t["cost"] for t in res["trades"])
                    cand = [s_]
                else:
                    continue
                if kind == "segment" and "events" in st.columns and not pd.isna(r["events"]):
                    ne = len(DV.events(p, w, "rule")[0])
                    c.compared += 1
                    bad_e = int(float(r["events"]) not in (ne, ne - 1))
                    c.count("stats_events", 1, bad_e)
                    if bad_e:
                        c.failed += 1; c.fail(f"stats.csv events {r['events']} for {p} {w} {ca} {bps} vs verifier {ne} (incl. T0) / {ne-1}")
                best = None
                for cd in cand:
                    bad = 0; wr = 0.0
                    for col in STAT_COLS + ["trades", "cost_paid"]:
                        if col not in st.columns or col not in cd or pd.isna(r[col]):
                            continue
                        if kind == "published_parent" and col in ("trades", "cost_paid"):
                            continue
                        d_ = float(rel(float(r[col]), cd[col])) if col not in ("trades", "days_below_10pct", "longest_underwater", "sessions") else float(abs(float(r[col]) - cd[col]))
                        wr = max(wr, d_ if col not in ("trades", "days_below_10pct", "longest_underwater", "sessions") else 0.0)
                        if d_ > (TOL if col not in ("trades", "days_below_10pct", "longest_underwater", "sessions") else 0.0):
                            bad += 1
                    if best is None or bad < best[0]:
                        best = (bad, wr, cd.get("_var"))
                    if bad == 0:
                        break
                c.compared += 1
                c.worst_rel = max(c.worst_rel, best[1])
                c.count("stats", 1, int(best[0] > 0))
                if best[2]:
                    variants_used[best[2]] += int(best[0] == 0)
                if best[0] > 0:
                    c.failed += 1; c.fail(f"stats.csv row {p} {w} {ca} {bps} {kind}: {best[0]} column(s) differ")
            if variants_used:
                c.notes.append(f"constant_mix average-share variants that matched (a = the rule's path at the same cost, b = at 0 cost): {dict(variants_used)}")
            # C3: rule minus whole book, after cost, 20.8 bps
            c3 = {}
            for p in books:
                for w in ("full", "live"):
                    a = stats_of(DV.sim(p, w, "lbes", "segment", HEADLINE_COST)["nav"])["cagr"]
                    b = stats_of(DV.sim(p, w, "lbes", "whole_book", HEADLINE_COST)["nav"])["cagr"]
                    c3[f"{p}|{w}"] = a - b
            c.notes.append("C3 (rule minus whole book, CAGR, 20.8 bps, lbes): " + json.dumps({k: round(v, 6) for k, v in c3.items()}))
            DV.c3 = c3
    run_check(C, "C-nav", c_nav)

    # ------------------------------------------------------------------ C-t06 (own simulator against T06's evidence)
    def c_t06(c):
        navp, decp = T06_EVIDENCE / "daily_nav.csv", T06_EVIDENCE / "decisions.csv"
        if not navp.exists() or not decp.exists():
            c.miss("AA/tests/T06/evidence/headline/{daily_nav,decisions}.csv"); return
        t6 = pd.read_csv(navp)
        t6 = t6[t6["run"] == "strategy"].copy()
        t6["cost_bps"] = r4(t6["cost_bps"]); t6["date"] = pd.to_datetime(t6["date"])
        d6 = pd.read_csv(decp)
        results = {}
        for wm in ("norm", "raw"):
            worst = 0.0; nrows = 0
            for p in books:
                V = DV.V[(p, "full", "lbes")]
                for bps in COSTS:
                    res = DV.sim(p, "full", "lbes", "whole_book", bps, wmode=wm)
                    mine = pd.Series(res["nav"], index=V["cal"])
                    t = t6[(t6["book"] == p) & (t6["cost_bps"] == bps)].set_index("date")["nav"]
                    sh = mine.index.intersection(t.index)
                    sh = sh[sh <= T06_LAST]
                    d_ = rel(mine.loc[sh].values, t.loc[sh].values)
                    worst = max(worst, float(d_.max())); nrows += len(sh)
                    if wm == "norm":
                        c.compared += len(sh)
                        bad = int((d_ > TOL_REGRESSION).sum()); c.failed += bad
                        c.count("nav_shared_sessions", len(sh), bad)
                        c.worst_rel = max(c.worst_rel, float(d_.max()))
                        if bad:
                            i = int(np.argmax(d_ > TOL_REGRESSION)); c.fail(f"{p} {bps} bps {sh[i].date()}: whole-book NAV differs from T06's by {d_[i]:.3e}")
            results[wm] = (nrows, worst)
        c.notes.append("whole-book run with listed weights renormalised to 1 per basket (T06's convention): max relative difference "
                       f"{results['norm'][1]:.3e} over {results['norm'][0]} shared sessions (gate, limit {TOL_REGRESSION:g})")
        c.notes.append("same run with listed weights NOT renormalised (the frozen T07 text): max relative difference "
                       f"{results['raw'][1]:.3e} (information: the two conventions cannot both reproduce T06 to 1e-12)")
        # decisions on every shared decision date
        for p in books:
            mine = DV.dec[(p, "full")]
            t = d6[d6["book"] == p]
            j = mine.merge(t, on="decision_date", suffixes=("_v", "_t"))
            for col in ("sign_Nifty100", "sign_MC100", "sign_SC100"):
                c.compared += len(j); bad = int((j[col + "_v"].astype(str) != j[col + "_t"].astype(str)).sum()); c.failed += bad
                c.count("decisions_shared_dates", len(j), bad)
            c.compared += len(j); bad = int((j["state_v"].astype(int) != j["state_t"].astype(int)).sum()); c.failed += bad
            c.count("decisions_shared_dates", len(j), bad)
            if bad:
                c.fail(f"{p}: whole-book state differs from T06's on {bad} shared decision dates")
            c.notes.append(f"{p}: {len(j)} shared decision dates")
    run_check(C, "C-t06", c_t06)

    # ------------------------------------------------------------------ C-always-in
    def c_always_in(c):
        ai = pd.DataFrame(SETS["always_in"])
        for p in books:
            a = ai[ai["book"] == p]
            for _, r in a.iterrows():
                c.compared += 1
                bad = abs(r["gap_pp"]) > r["limit_pp"]
                c.count("g0", 1, int(bad))
                if bad:
                    c.failed += 1; c.fail(f"{p} {r['scope']}: always-in minus published {r['gap_pp']:+.4f} pp exceeds the G0 limit {r['limit_pp']}")
        g = E.get("g_engine.csv", c)
        if g is not None:
            for p in books:
                r = g[g["book"] == p]
                a = ai[ai["book"] == p]
                if not len(r):
                    c.miss(f"g_engine.csv row for {p}"); continue
                r = r.iloc[0]
                ov = float(a[a["scope"] == "overall"]["gap_pp"].iloc[0])
                ovc = float(a[a["scope"] == "overall_calendar_years"]["gap_pp"].iloc[0])
                yy = a[~a["scope"].isin(["overall", "overall_calendar_years"])]
                w = yy.iloc[int(yy["gap_pp"].abs().values.argmax())]
                for col, val in (("cagr_gap_pp_yr", ov), ("worst_year_gap_pp", float(w["gap_pp"]))):
                    if col in g.columns and not pd.isna(r[col]):
                        c.compared += 1
                        bad = abs(float(r[col]) - val) > 1e-6
                        if col == "cagr_gap_pp_yr" and bad and abs(float(r[col]) - ovc) <= 1e-6:
                            bad = False            # T06's engine measures the overall gap in calendar years; accepted
                            c.notes.append(f"g_engine.csv {p} cagr_gap_pp_yr matches the calendar-year form ({ovc:.6f})")
                        c.count("g_engine", 1, int(bad))
                        if bad:
                            c.failed += 1; c.fail(f"g_engine.csv {p} {col}: evidence {float(r[col]):.8f} vs verifier {val:.8f}")
                if "worst_year" in g.columns and not pd.isna(r["worst_year"]):
                    c.compared += 1
                    bad = str(int(float(r["worst_year"]))) != str(w["scope"]) and abs(float(w["gap_pp"])) > 1e-9
                    c.count("g_engine", 1, int(bad))
                    if bad:
                        c.failed += 1; c.fail(f"g_engine.csv {p} worst_year {r['worst_year']} vs verifier {w['scope']}")
        c.notes.append("always-in = the 'parent' run (every stock held, 0 cost) against the published NAV rebased; limits: overall +-0.25 pp/yr (years = (sessions-1)/252), each calendar year +-0.5 pp")
        for p in books:
            a = ai[ai["book"] == p]
            yy = a[~a["scope"].isin(["overall", "overall_calendar_years"])]
            c.notes.append(f"{p}: overall {float(a[a['scope']=='overall']['gap_pp'].iloc[0]):+.4f} pp/yr (calendar-year form "
                           f"{float(a[a['scope']=='overall_calendar_years']['gap_pp'].iloc[0]):+.4f}); worst calendar year "
                           f"{yy.iloc[int(yy['gap_pp'].abs().values.argmax())]['scope']} {float(yy['gap_pp'].abs().max()):.4f} pp")
    run_check(C, "C-always-in", c_always_in)

    # ------------------------------------------------------------------ the draws: shared preparation
    drops_all = E.get("draw_drops.npz")
    labels_all = E.get("draw_labels.npz")
    es_all = E.get("event_stocks.csv")
    draws_df = E.get("draws.csv")
    prep = {}

    def prepare(p, window):
        """Row map of the engine's event_stocks rows to my rows, and per-row arrays from MY derivation."""
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
        V = DV.V[(p, window, "lbes")]
        eidx = mine["event_no"].values.astype(int)
        E_n = len(evs)
        res = dict(ok=ok, rmap=rmap, mine=mine, evs=evs, V=V, E_n=E_n)
        if ok:
            ev_of_row = eidx[rmap]
            w_row = mine["listed_weight"].values.astype(float)[rmap]
            band_row = mine["band"].map(BAND_INDEX).values.astype(int)[rmap]
            erows = SETS["events"][(p, window)]
            res.update(ev_of_row=ev_of_row, w_row=w_row, band_row=band_row, Dw=erows["dropped_weight"].values.astype(float),
                       tau=erows["tau"].values.astype(float), n_held=erows["n_held"].values.astype(int),
                       n_cnt=erows[["n_large", "n_mid", "n_small"]].values.astype(int),
                       sell=np.array([[dec_sell(DV, p, window, ev, b) for b in range(3)] for ev in evs]),
                       mine_rule_drop=(~mine["kept"].values.astype(bool))[rmap])
            res["Wmat"] = np.zeros((len(rmap), E_n)); res["Wmat"][np.arange(len(rmap)), ev_of_row] = w_row
            res["Cmat"] = np.zeros((len(rmap), E_n)); res["Cmat"][np.arange(len(rmap)), ev_of_row] = 1.0
        prep[(p, window)] = res
        return res

    def dec_sell(DV_, p, window, ev, b):
        d = DV_.dec[(p, window)]
        return d[["sign_Nifty100", "sign_MC100", "sign_SC100"][b]].iloc[ev["j"]] == "SELL"

    # ------------------------------------------------------------------ C-count (brute force over all 2^n subsets)
    def c_count(c):
        ev = E.get("events.csv", c)
        ct = E.get("count_table.json", c)
        for p in books:
            for window in ("full", "live"):
                V = DV.V[(p, window, "lbes")]
                evs, _ = DV.events(p, window, "rule")
                frame = SETS["events"][(p, window)]
                recs = count_records(find_book(ct, p), window) if ct is not None else []
                for no, e in enumerate(evs):
                    w = (V["Wn"] if DV.wmode == "norm" else V["W"])[e["k"]][e["held"]]
                    num = event_numbers(V, e, DV.wmode)
                    if len(w) > 16:
                        c.miss(f"{p} {window} event {no}: n_held {len(w)} > 16"); continue
                    A, tau, near = allowed_subsets(w, num["dropped_weight"])
                    rule_mask = mask_of(~e["kept"])
                    c.compared += 1
                    c.count("rule_subset_in_A", 1, int(rule_mask not in set(A.tolist())))
                    if rule_mask not in set(A.tolist()):
                        c.failed += 1; c.fail(f"{p} {window} event {no}: the rule's own drop set is not among the {len(A)} allowed subsets (V5c)")
                    if near < 1e-9:
                        c.notes.append(f"{p} {window} event {no}: a subset lies within 1e-9 of the tau boundary (|diff - tau| = {near:.2e})")
                    # against events.csv
                    if ev is not None and "n_allowed_subsets" in ev.columns:
                        row = with_window(ev)
                        row = row[(row["book"] == p) & (row["window"] == window) & (dstr(row["trade_date"]) == str(V["cal"][e["idx"]].date()))]
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
                                c.failed += 1; c.fail(f"{p} {window} event {no}: count_table.json {rec.get(k)!r} vs brute force {len(A)}")
                        else:
                            c.miss(f"count_table.json record for {p} {window} event {no}")
                n_part = int(frame["partial"].sum())
                if ct is not None:
                    ent = find_book(ct, p)
                    if isinstance(ent, dict):
                        k = first_key(ent, [r"partial"])
                        if k is None and isinstance(ent.get(window), dict):
                            ent = ent[window]; k = first_key(ent, [r"partial"])
                        if k is not None and not isinstance(ent[k], (dict, list)):
                            c.compared += 1
                            c.count("n_partial", 1, int(int(ent[k]) != n_part))
                            if int(ent[k]) != n_part:
                                c.failed += 1; c.fail(f"{p} {window}: count_table.json events with partial {ent[k]} vs {n_part}")
                c.notes.append(f"{p} {window}: events {len(evs)}, with 0 < equity share < 1: {n_part}"
                               f"{'  (BELOW the reportability gate of 6)' if n_part < 6 else ''}")
        c.notes.append("count = number of subsets X of the held stocks with |sum w(X) - D| <= tau = half the smallest listed weight, by enumeration of all 2^n masks")
    run_check(C, "C-count", c_count)

    # ------------------------------------------------------------------ C-draws (structure of every draw)
    def c_draws(c):
        if drops_all is None:
            c.miss("evidence file draw_drops.npz"); return
        if es_all is None:
            c.miss("evidence file event_stocks.csv"); return
        for p in books:
            for window in ("full", "live"):
                pr = prepare(p, window)
                if not pr["ok"]:
                    c.miss(f"{p} {window}: the engine's event_stocks rows do not map one-to-one to the verifier's (see C-tag)"); continue
                E_n = pr["E_n"]
                k46 = f"{p}|{window}|N4.6"
                if k46 in drops_all:
                    dr = drops_all[k46]
                    R = len(pr["rmap"])
                    if dr.ndim != 2 or dr.shape[1] != R:
                        c.failed += 1; c.fail(f"{k46}: shape {dr.shape} but event_stocks has {R} rows"); continue
                    nd = dr.shape[0]
                    c.compared += dr.size
                    bad_val = int(((dr != 0) & (dr != 1)).sum())
                    c.count("N4.6_values_01", dr.size, bad_val); c.failed += bad_val
                    dropw = dr.astype(float) @ pr["Wmat"]                 # (draws, events) dropped listed weight
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
                    c.notes.append(f"{k46}: {nd} draws x {E_n} events checked")
                else:
                    c.miss(f"draw_drops.npz key {k46}")
                k48 = f"{p}|{window}|N4.8"
                if k48 in drops_all:
                    dr = drops_all[k48]
                    if labels_all is None or k48 not in labels_all:
                        c.miss(f"draw_labels.npz key {k48}"); continue
                    lb = labels_all[k48]
                    R = len(pr["rmap"])
                    if dr.shape != lb.shape or dr.shape[1] != R:
                        c.failed += 1; c.fail(f"{k48}: shapes {dr.shape} / {lb.shape} vs {R} rows"); continue
                    nd = dr.shape[0]
                    # number of stocks per label per event equals the rule's counts
                    tot = 0; badn = 0
                    for lab in range(3):
                        cnt = (lb == lab).astype(float) @ pr["Cmat"]            # (draws, events)
                        badn += int((cnt != pr["n_cnt"][:, lab][None, :]).sum()); tot += cnt.size
                    c.compared += tot; c.failed += badn; c.count("N4.8_label_counts", tot, badn)
                    if badn:
                        c.fail(f"{k48}: the number of stocks per label differs from the rule's n_large, n_mid, n_small at {badn} draw-events")
                    bad_lab = int((lb > 2).sum()); c.failed += bad_lab; c.compared += lb.size; c.count("N4.8_label_values", lb.size, bad_lab)
                    # a stock is dropped iff its label's band signal at that event is SELL
                    sell_row = pr["sell"][pr["ev_of_row"][None, :], np.clip(lb, 0, 2)]           # (draws, R)
                    badd = int((sell_row.astype(np.uint8) != dr).sum())
                    c.compared += dr.size; c.failed += badd; c.count("N4.8_drop_iff_label_SELL", dr.size, badd)
                    if badd:
                        c.fail(f"{k48}: a stock is dropped although its label's signal is BUY (or kept although SELL) in {badd} cells")
                    # persistence: the same ISIN pair is in the same order at every event of a draw
                    isin_row = pd.factorize(prepare(p, window)["mine"]["isin"].values[pr["rmap"]])[0]
                    nI = int(isin_row.max()) + 1
                    badp = 0
                    for dd in range(nd):
                        M = np.full((E_n, nI), np.nan)
                        M[pr["ev_of_row"], isin_row] = lb[dd]
                        diffm = M[:, :, None] - M[:, None, :]
                        pos = np.nansum(diffm > 0, axis=0) > 0 if False else (np.where(np.isnan(diffm), 0, diffm) > 0).any(axis=0)
                        neg = (np.where(np.isnan(diffm), 0, diffm) < 0).any(axis=0)
                        badp += int((pos & neg).sum() // 2)
                    c.compared += nd * E_n; c.failed += badp; c.count("N4.8_persistent_order", nd * E_n, badp)
                    if badp:
                        c.fail(f"{k48}: {badp} ISIN pairs change their relative order between events within a draw (labels are not from one persistent score)")
                    c.notes.append(f"{k48}: {nd} draws x {E_n} events checked")
                else:
                    c.miss(f"draw_drops.npz key {k48}")
        # per-draw mean_dropped_weight and n_events against draws.csv
        if draws_df is None:
            c.miss("evidence file draws.csv"); return
        dd = with_window(draws_df)
        for (p, window, typ), g in dd.groupby(["book", "window", "draw_type"]):
            if p not in books:
                continue
            key = f"{p}|{window}|{typ}"
            if key not in drops_all:
                continue
            pr = prepare(p, window)
            if not pr["ok"]:
                continue
            dropw = drops_all[key].astype(float) @ pr["Wmat"]
            mean_w = dropw.mean(axis=1)
            ids = g["draw_id"].astype(int).values
            ok_ids = ids < len(mean_w)
            c.compared += int(ok_ids.sum()) * 2
            if "mean_dropped_weight" in g.columns:
                d_ = rel(g["mean_dropped_weight"].astype(float).values[ok_ids], mean_w[ids[ok_ids]])
                badc = int((d_ > TOL).sum()); c.failed += badc; c.count("draws_csv_mean_dropped_weight", int(ok_ids.sum()), badc)
                c.worst_rel = max(c.worst_rel, float(d_.max()) if len(d_) else 0.0)
                if badc:
                    c.fail(f"draws.csv {key}: mean_dropped_weight differs from the saved drops in {badc} rows (e.g. draw {ids[ok_ids][int(np.argmax(d_ > TOL))]})")
            if "n_events" in g.columns:
                badn = int((g["n_events"].astype(float).values[ok_ids] != pr["E_n"]).sum()); c.failed += badn
                c.count("draws_csv_n_events", int(ok_ids.sum()), badn)
                if badn:
                    c.fail(f"draws.csv {key}: n_events != the rule's {pr['E_n']} in {badn} rows")
            if (~ok_ids).any():
                c.failed += int((~ok_ids).sum()); c.fail(f"draws.csv {key}: draw ids beyond the saved array")
        if run_name == "headline":
            for p in books:
                for window in ("full", "live"):
                    for typ in ("N4.6", "N4.8"):
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
        for bi, p in enumerate(books):
            for window in ("full",):
                key = f"{p}|{window}|N4.6"
                pr = prepare(p, window)
                if key not in drops_all or not pr["ok"]:
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
                c.count("N4.6_seed_replay", len(ids), int(bad > 0))
                if bad:
                    c.fail(f"{key}: the first {len(ids)} saved draws differ from the seed [7, draw_id, book_no] replay in {bad} cells (the contract's seed order: held stocks in ISIN order, one rng.random() per event, A[floor(u |A|)])")
        c.notes.append("information only: replays default_rng([7, draw_id, book_no]) for the first 20 N4.6 draws of the full window")
    run_check(C, "C-draw-seed", c_draw_seed, gate=False)

    # ------------------------------------------------------------------ C-draw-nav
    curves = E.get("draw_curves_20.8.npz")

    def kept_from_drops(p, window, drow):
        """Events (copies of mine) with kfull rebuilt from one saved draw (a 0/1 row in the engine's event_stocks order)."""
        pr = prepare(p, window)
        V = pr["V"]
        evs = []
        mine = pr["mine"]
        by_ev = defaultdict(list)
        for r_, mi in enumerate(pr["rmap"]):
            by_ev[int(pr["ev_of_row"][r_])].append((r_, mi))
        isin_to_si = {isn: k for k, isn in enumerate(V["isins"])}
        for no, e in enumerate(pr["evs"]):
            kf = np.zeros(len(V["S"]), dtype=bool)
            for r_, mi in by_ev[no]:
                si = isin_to_si[mine["isin"].iloc[mi]]
                kf[si] = (drow[r_] == 0)
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
                   ("full", "liq", HEADLINE_COST, "extra"), ("live", "lbes", HEADLINE_COST, "extra")]
        nsim = 0
        for p in books:
            for typ in ("N4.6", "N4.8"):
                for window, cash, bps, tag in configs:
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
                        evs = kept_from_drops(p, window, drops_all[key][did])
                        res = simulate(V, evs, bps, DV.wmode)
                        nsim += 1
                        st = stats_of(res["nav"]); st["trades"] = len(res["trades"]); st["cost_paid"] = float(sum(t["cost"] for t in res["trades"]))
                        row = dd[(dd["book"] == p) & (dd["window"] == window) & (dd["cash"] == cash) & (dd["cost_bps"] == bps) &
                                 (dd["draw_type"] == typ) & (dd["draw_id"].astype(int) == did)]
                        if len(row) != 1:
                            c.miss(f"draws.csv row {p} {window} {cash} {bps} {typ} {did}"); continue
                        bad = 0; first = None
                        for col in statcols:
                            exact = col in ("days_below_10pct", "longest_underwater", "sessions", "trades")
                            d_ = abs(float(row[col].iloc[0]) - st[col]) if exact else float(rel(float(row[col].iloc[0]), st[col]))
                            if not exact:
                                c.worst_rel = max(c.worst_rel, d_)
                            if d_ > (0 if exact else TOL):
                                bad += 1; first = first or f"{col}: evidence {float(row[col].iloc[0])!r} vs verifier {st[col]!r}"
                        c.compared += 1; c.failed += int(bad > 0); c.count(f"draw_stats_{tag}", 1, int(bad > 0))
                        if bad:
                            c.fail(f"{p} {window} {cash} {bps} {typ} draw {did}: {bad} statistic(s) differ ({first})")
                        if tag == "headline" and curves is not None:
                            ck = f"{p}|{typ}_{did}"
                            if ck not in curves:
                                c.miss(f"draw_curves_20.8.npz key {ck}"); continue
                            cv = curves[ck].astype(float)
                            d_ = rel(cv, res["nav"]) if len(cv) == len(res["nav"]) else np.array([np.inf])
                            c.compared += len(d_); badc = int((d_ > TOL_CURVE).sum()); c.failed += badc; c.count("draw_curves", len(d_), badc)
                            if badc:
                                c.fail(f"{ck}: daily NAV differs from the re-simulation (max relative {d_.max():.2e}, float32 limit {TOL_CURVE:g})")
                        elif tag == "headline" and curves is None:
                            c.miss("evidence file draw_curves_20.8.npz")
        c.notes.append(f"{nsim} draw re-simulations (headline sample: first 20 and 20 random draws per book and null at 20.8 bps; extra: draws 0-2 at 0 / 50 bps, LIQUIDCASE and live window)")
        c.notes.append("daily curves are stored as float32, so they are compared at a relative 1e-6 (the spec's 1e-9 applies to the end NAV in draws.csv)")
    run_check(C, "C-draw-nav", c_draw_nav)

    # ------------------------------------------------------------------ C-oracle
    def c_oracle(c):
        co = E.get("controls_oracle.json", c if run_name == "headline" else None)
        dd = with_window(draws_df) if draws_df is not None else None
        if co is None and run_name != "headline":
            c.notes.append(f"run '{run_name}': controls_oracle.json not written (V7 is a headline-run control); the oracle is only re-derived")
        for p in books:
            cg = {v: oracle_cagr(DV, p, v) for v in ("fill", "close")}
            if co is None and run_name != "headline":
                c.compared += 1
            d_ = None
            if dd is not None:
                g = dd[(dd["book"] == p) & (dd["window"] == "full") & (dd["cash"] == "lbes") & (dd["draw_type"] == "N4.6") & (np.abs(dd["cost_bps"].astype(float) - HEADLINE_COST) < 1e-9)]
                if len(g):
                    d_ = {v: pct_and_p(cg[v], g["cagr"].values, True)[0] for v in cg}
            c.notes.append(f"{p}: oracle CAGR {cg['fill']:.6f} (fill-to-fill returns) / {cg['close']:.6f} (close-to-close)" + (f"; percentile against the evidence's N4.6 draws {d_['fill']:.2f} / {d_['close']:.2f}" if d_ else ""))
            if co is None:
                continue
            ent = find_book(co, p)
            if not isinstance(ent, dict):
                c.miss(f"controls_oracle.json entry for {p}"); continue
            kc = first_key(ent, [r"cagr"])
            kp = first_key(ent, [r"pct", r"percentile"])
            if kc is None:
                c.miss(f"controls_oracle.json {p}: no CAGR field"); continue
            c.compared += 1
            best_v = min(cg, key=lambda v: abs(cg[v] - float(ent[kc])))
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
                if float(ent[kp]) < 99:
                    c.notes.append(f"{p}: oracle percentile {float(ent[kp]):.2f} is below the V7 line of 99 (engine's gate, not the verifier's)")
    run_check(C, "C-oracle", c_oracle)

    # ------------------------------------------------------------------ C-percentile
    DV.percentiles = []

    def c_percentile(c):
        if draws_df is None:
            E.get("draws.csv", c); return
        dd = with_window(draws_df).copy(); dd["cost_bps"] = r4(dd["cost_bps"])
        rows = []
        for (p, w, ca, cst, typ), g_ in dd.groupby(["book", "window", "cash", "cost_bps", "draw_type"]):
            if p not in books:
                continue
            res = DV.sim(p, w, ca, "segment", float(cst))
            mine = stats_of(res["nav"])
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
            rows.append(row)
        DV.percentiles = rows
        c.notes.append("worst_rel here is the largest difference between the verifier's two own percentile implementations")
        st = E.get("stats.csv")
        if st is not None:
            pcc = [x for x in st.columns if "pctile" in x.lower() or "percentile" in x.lower()]
            if pcc:
                c.notes.append(f"stats.csv carries percentile columns {pcc}; compared")
                st = with_window(st); st["cost_bps"] = r4(st["cost_bps"])
                for pcol in pcc:
                    stat = pcol.lower().replace("_pctile", "").replace("_percentile", "").replace("pctile_", "")
                    for r in rows:
                        e = st[(st["book"] == r["book"]) & (st["window"] == r["window"]) & (st["cash"] == r["cash"]) & (st["cost_bps"] == round(r["cost_bps"], 4)) & (st["kind"] == "segment")]
                        if len(e) and f"{stat}_pctile" in r and not pd.isna(e[pcol].iloc[0]):
                            c.compared += 1
                            if abs(float(e[pcol].iloc[0]) - r[f"{stat}_pctile"]) > 1e-6:
                                c.failed += 1; c.fail(f"stats.csv {pcol} differs for {r['book']} {r['window']} {r['cost_bps']}")
        # analysis.log, if it exists: the headline percentiles must be printed in it
        cand = [E.dir / "analysis.log", E.dir.parent / "analysis.log", E.dir.parent.parent / "analysis.log"]
        logp = next((x for x in cand if x.exists()), None)
        if logp is None:
            c.notes.append("analysis.log not found beside the evidence (written in Step 5); no printed percentile compared")
        else:
            nums = set(re.findall(r"-?\d+\.\d+", logp.read_text(encoding="utf-8", errors="replace")))
            for r in rows:
                if r["window"] == "full" and r["cash"] == "lbes" and abs(r["cost_bps"] - HEADLINE_COST) < 1e-9:
                    for stat in ("cagr", "max_dd"):
                        v = r.get(f"{stat}_pctile")
                        if v is None:
                            continue
                        c.compared += 1
                        if not any(f"{v:.{nd}f}" in nums for nd in (1, 2)):
                            c.failed += 1; c.fail(f"{r['book']} {r['draw_type']} {stat} percentile {v:.2f} not printed in {logp.name}")
            c.notes.append(f"read {logp}")
    run_check(C, "C-percentile", c_percentile)

    # ------------------------------------------------------------------ C-pit
    def c_pit(c):
        tot = defaultdict(int)
        for p in books:
            for window in ("full", "live"):
                for mode in ("rule", "tied"):
                    _, pit = DV.events(p, window, mode)
                    if mode == "tied":
                        tot["decisions_checked"] += pit["decisions_checked"]; tot["decision_violations"] += pit["decision_violations"]
                        tot["trades_checked"] += pit["trades_checked"]; tot["trade_violations"] += pit["trade_violations"]
                    else:
                        for k, v in pit.items():
                            tot[k] += v
        for k in ("decisions_checked", "tags_checked", "trades_checked"):
            c.compared += tot[k]
            if tot[k] <= 0:
                c.failed += 1; c.fail(f"{k} = 0: V2 needs a count > 0")
        for k in ("decision_violations", "tag_violations", "trade_violations"):
            c.failed += tot[k]
            if tot[k]:
                c.fail(f"{k} = {tot[k]}")
        c.notes.append("verifier's own counts: " + json.dumps(dict(tot)) + " (T0 tags are read as of T0 itself and are exempt from 'session before the trade session')")
        # the evidence's own rows
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
            tdv = pd.to_datetime(dc["trade_date"], errors="coerce"); dcd = pd.to_datetime(dc["decision_date"], errors="coerce")
            okt = tdv.notna()
            c.compared += int(okt.sum()); bad = int((tdv[okt] <= dcd[okt]).sum()); c.failed += bad
            c.count("evidence_trade_after_decision", int(okt.sum()), bad)
            if bad:
                c.fail(f"decisions.csv: {bad} rows trade on or before the decision date")
    run_check(C, "C-pit", c_pit)
    return C


def tag_panel_check(DV, books):
    """Information only (not a gate): my own ranks and bands against the D23 panels, which `analysis/tag_lookup.py` reads."""
    t = DV.tagger
    rk = pd.read_csv(rd(f"{EXT}/tags/mcap_rank_panel.csv"), usecols=["date", "quote_id", "rank", "band"], **READ_KW)
    rk["date"] = pd.to_datetime(rk["date"])
    rows = 0; bad = 0
    for d, g in rk.groupby("date"):
        pos, rank = t.ranks_at(np.datetime64(d, "ns"))
        mine = pd.DataFrame({"quote_id": t.q20[pos], "rank": rank})
        mine = mine[mine["rank"] > 0]
        j = mine.merge(g, on="quote_id", suffixes=("_v", "_p"))
        rows += len(j) ; bad += int((j["rank_v"] != j["rank_p"]).sum() + (len(mine) != len(g)))
    mp = pd.read_csv(rd(f"{EXT}/tags/membership_panel.csv"), usecols=["snapshot_date", "index_name", "isin", "band"], **READ_KW)
    mp["snapshot_date"] = pd.to_datetime(mp["snapshot_date"])
    mb = 0
    for r in mp.itertuples(index=False):
        mm = t.mem[np.datetime64(r.snapshot_date, "ns")].get(r.isin, [])
        mb += int(r.band not in mm)
    return dict(rank_rows_compared=int(rows), rank_mismatches=int(bad), membership_rows_compared=int(len(mp)), membership_mismatches=int(mb))


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
    """Write ONE deliberately corrupted evidence file into dst (the rest is read from the real evidence through the fallback).
    Returns (info, checks that must fail)."""
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
        es = E.get("event_stocks.csv")
        key = f"{p0}|full|N4.6"
        sub = es[(es["book"] == p0) & (es["window"] == "full")].reset_index(drop=True)
        arr = dr[key].copy()
        w = sub["listed_weight"].astype(float).values
        for td, g in sub.groupby("trade_date"):
            if len(g) < 3:
                continue
            idx = g.index.values
            tau = 0.5 * w[idx].min()
            Dw = float(g[g["kept"].astype(str).str.lower() == "false"]["listed_weight"].astype(float).sum())
            for i in idx:                                       # toggle one stock of draw 0 until it leaves the allowed band
                arr[0, i] = 1 - arr[0, i]
                if abs(float(arr[0, idx].astype(float) @ w[idx]) - Dw) > tau * 1.01 + 1e-9:
                    data = dict(dr); data[key] = arr
                    np.savez(dst / "draw_drops.npz", **data)
                    return dict(file="draw_drops.npz", key=key, draw=0, trade_date=str(td), row=int(i)), ["C-draws"]
                arr[0, i] = 1 - arr[0, i]
        raise RuntimeError("no event found for the moved-drop corruption")
    raise ValueError(kind)


CORRUPTIONS = ["flip_tag", "change_target_weight", "change_position", "scale_nav", "delete_event", "move_drop"]


def run_selftest(DV, SETS, E, evdir, wnote, run_name, books, base_dir):
    """C-corrupt: each corruption alone must make its relevant check fail; then all of them together make the whole verifier fail."""
    global ONLY
    results = {}
    for kind in CORRUPTIONS:
        cdir = base_dir / f"corrupt_{kind}"
        try:
            info, must = make_corruption(kind, E, cdir, books)
        except Exception as ex:
            results[kind] = dict(error=repr(ex), detected=False)
            continue
        ONLY = set(must)
        try:
            Cc = compare_all(DV, SETS, Evidence(cdir, fallback=evdir), wnote, run_name)
        finally:
            ONLY = None
        nfail = {k: v.failed + v.missing for k, v in Cc.items()}
        results[kind] = dict(info=info, relevant_checks=must, failures_in_relevant_checks=nfail, detected=all(nfail.get(k, 0) > 0 for k in must))
        print(f"  C-corrupt {kind:22s} -> {must}: failures {nfail}  detected={results[kind]['detected']}", flush=True)
    # all corruptions together in one copy: the whole run must fail (exit non-zero)
    cdir = base_dir / "corrupt_all"
    if cdir.exists():
        shutil.rmtree(cdir)
    cdir.mkdir(parents=True)
    for kind in CORRUPTIONS:
        if results.get(kind, {}).get("error"):
            continue
        for f in (base_dir / f"corrupt_{kind}").iterdir():
            if f.name == "event_stocks.csv" and (cdir / f.name).exists():
                # two corruptions touch event_stocks.csv (a flipped band, a changed listed weight): keep both
                a = pd.read_csv(cdir / f.name, keep_default_na=False, na_values=[""]); b = pd.read_csv(f, keep_default_na=False, na_values=[""])
                o = E.get("event_stocks.csv")
                a.loc[b["band"] != o["band"], "band"] = b.loc[b["band"] != o["band"], "band"]
                a.loc[b["listed_weight"] != o["listed_weight"], "listed_weight"] = b.loc[b["listed_weight"] != o["listed_weight"], "listed_weight"]
                a.to_csv(cdir / f.name, index=False)
            else:
                shutil.copy(f, cdir / f.name)
    Call = compare_all(DV, SETS, Evidence(cdir, fallback=evdir), wnote, run_name)
    cc, cf = summarise(Call)
    print_table(Call, f"SELF-TEST (C-corrupt): all six corruptions in one copy ({cdir})")
    all_ok = cf > 0 and all(v.get("detected") for v in results.values())
    return dict(dir=str(base_dir), corruptions=results, combined=dict(dir=str(cdir), gate_compared=cc, gate_failures=cf,
                checks={k: v.to_dict() for k, v in Call.items()}), detected=bool(all_ok)), Call


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--evidence", default=str(AA / "tests" / "T07" / "evidence" / "headline"))
    ap.add_argument("--no-selftest", action="store_true", help="skip the in-process corrupted-copy test (C-corrupt)")
    ap.add_argument("--out", default=None)
    ap.add_argument("--weights", default="auto", choices=["auto", "raw", "norm"],
                    help="listed weights: norm = each basket row divided by its sum (T06's convention, the coordinator's ruling of 2026-11-12); raw = as listed (the frozen text's wording); auto = as the evidence's sum_weights show")
    ap.add_argument("--books", default=",".join(BOOKS))
    ap.add_argument("--literal-skipped-basket", action="store_true",
                    help="DIAGNOSTIC ONLY: do not re-tag on a basket that arrives while nothing is held (the literal reading of the frozen text)")
    ap.add_argument("--corrupt-dir", default=None)
    args = ap.parse_args()
    books = [b for b in args.books.split(",") if b]
    global RETAG_SKIPPED_BASKET
    RETAG_SKIPPED_BASKET = not args.literal_skipped_basket
    evdir = Path(args.evidence)
    run_name = evdir.name
    out = Path(args.out) if args.out else evdir / "verify_t07.json"
    t = time.time()
    E = Evidence(evdir)
    if args.weights == "auto":
        wmode, wnote = infer_weights(E)
    else:
        wmode, wnote = args.weights, "set on the command line"
    print(f"weights convention: {wmode} ({wnote})", flush=True)
    DV = Derived(books=books, wmode=wmode)
    SETS = derive_sets(DV)
    try:                                                     # information: my tag lookup against the D23 panels
        tp = tag_panel_check(DV, books)
    except Exception as ex:
        tp = dict(error=repr(ex))
    print(f"[{time.time()-t:6.1f}s] derivation complete", flush=True)
    C = compare_all(DV, SETS, E, wnote, run_name)
    print(f"[{time.time()-t:6.1f}s] checks complete", flush=True)
    for nm in EVIDENCE_FILES:
        if E.path(nm) is None and nm not in E.missing_files:
            E.missing_files.append(nm)
    extra_missing = sorted(set(E.missing_files))
    if run_name != "headline":                       # quick runs do not write the controls (V6, V7)
        extra_missing = [x for x in extra_missing if x != "controls_oracle.json"]
    if extra_missing:
        print("\nMISSING EVIDENCE FILES: " + ", ".join(extra_missing))
    print_table(C, f"verifier vs evidence in {evdir}")
    gate_compared, gate_fail = summarise(C)
    print(f"\nown tag lookup against the D23 panels (information): {tp}")
    print("\n=== recomputed percentiles (20.8 bps, LBES, full window; pass mark 90) ===")
    for r in DV.percentiles:
        if r["window"] == "full" and r["cash"] == "lbes" and abs(r["cost_bps"] - HEADLINE_COST) < 1e-9:
            print(f"{r['book']} {r['draw_type']:5s} CAGR pctile {r['cagr_pctile']:7.2f} (p {r['cagr_p']:.4f})   max-DD pctile {r['max_dd_pctile']:7.2f} (p {r['max_dd_p']:.4f})")
    selftest = None
    if not args.no_selftest:
        base = Path(args.corrupt_dir) if args.corrupt_dir else SCRATCH / "corrupt_evidence_t07"
        base.mkdir(parents=True, exist_ok=True)
        selftest, _ = run_selftest(DV, SETS, E, evdir, wnote, run_name, books, base)
        print(f"C-corrupt: every corruption detected by its check and the combined copy fails: {selftest['detected']}")
    ok_real = gate_compared > 0 and gate_fail == 0 and not extra_missing and all(c.compared > 0 for c in C.values() if c.gate)
    ok = ok_real and (selftest is None or selftest["detected"])
    c_corrupt = dict(compared=0 if selftest is None else 1, failed=0 if (selftest is None or selftest["detected"]) else 1, note="C-corrupt: the corrupted copy must make the relevant checks fail")
    rep = dict(verifier="analysis/verify_t07.py", evidence=str(evdir), weights_convention=wmode, weights_note=wnote,
               gate_compared=int(gate_compared), gate_failures_and_missing=int(gate_fail), missing_evidence_files=extra_missing,
               checks={k: v.to_dict() for k, v in C.items()}, c_corrupt=c_corrupt, tag_panel_crosscheck=tp,
               always_in=SETS["always_in"], c3_rule_minus_whole_book=getattr(DV, "c3", None), percentiles=DV.percentiles,
               approved_data_files_read={k: v for k, v in READS.items()}, selftest=selftest, exit_ok=bool(ok))
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
