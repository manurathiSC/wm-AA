"""Tag of a stock on a date: one shared, rule-independent lookup (T07 plan, step 0B). Stdlib + pandas + numpy only.

    from tag_lookup import TagLookup
    t = TagLookup.from_files(rank_csv, membership_csv, symbology_csv)
    t.tag("INE002A01018", "2024-06-14")  ->  {"band": "Large", "source": "rank", "snapshot": "2024-05-31", "detail": 12, "via": "isin"}

The rule (frozen in T07.md §3 once written; decided by Manu 2026-11-11):
  * cutoff = the first membership snapshot date.
  * asof >= cutoff : the latest membership snapshot on or before asof. Listed in an index -> that index's band, source "membership".
                     Not listed -> the rank band below, source "nonmember_rank".
  * asof <  cutoff : the latest rank snapshot (the market-cap table) on or before asof -> its band, source "rank".
  * no rank for the stock on that snapshot -> band "Small and below", source "unranked" (counted by the caller, never silent).
  * Bands: Large (rank 1-100 / Nifty 100), Mid (101-250 / Midcap 150), Small and below (above 250 / Smallcap 250, Microcap 250).
  * No averaging. "Latest" means the latest snapshot on or before asof, never a later one (checked in the self-test).
ISIN renames: a stock is found by its ISIN, or through symbology_changes by any other ISIN that shares its quote_id.
No parent, event, signal or weekly review is mentioned here: any rule may call it.
    python -I analysis/tag_lookup.py --selftest
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

LARGE, MID, SMALL = "Large", "Mid", "Small and below"


class TagLookup:
    def __init__(self, rank_panel: pd.DataFrame, membership_panel: pd.DataFrame, symbology: pd.DataFrame):
        rp = rank_panel
        self._rank_dates = np.array(sorted(pd.to_datetime(rp["date"]).unique()), dtype="datetime64[ns]")
        self._rank_by_date = {pd.Timestamp(d): g for d, g in rp.assign(_d=pd.to_datetime(rp["date"])).groupby("_d")}
        self._rank_cache: dict = {}
        mp = membership_panel
        self._memb_dates = np.array(sorted(pd.to_datetime(mp["snapshot_date"]).unique()), dtype="datetime64[ns]")
        self.cutoff = pd.Timestamp(self._memb_dates[0]) if len(self._memb_dates) else None
        self._memb: dict = {}
        for d, g in mp.assign(_d=pd.to_datetime(mp["snapshot_date"])).groupby("_d"):
            self._memb[pd.Timestamp(d)] = {r.isin: (r.index_name, r.band) for r in g.itertuples()}
        # identity: ISIN -> quote_ids, quote_id -> ISINs (from symbology and from the rank panel)
        q_of_i: dict = {}
        i_of_q: dict = {}

        def link(isin, qid):
            if isinstance(isin, str) and isin and pd.notna(qid):
                q_of_i.setdefault(isin, set()).add(int(qid))
                i_of_q.setdefault(int(qid), set()).add(isin)

        for col in ("isin", "new_isin"):
            for isin, qid in zip(symbology[col], symbology["quote_id"]):
                link(isin, qid)
        for isin, qid in zip(rp["isin"], rp["quote_id"]):
            link(isin, qid)
        self._q_of_i, self._i_of_q = q_of_i, i_of_q

    @classmethod
    def from_files(cls, rank_csv, membership_csv, symbology_csv) -> "TagLookup":
        rp = pd.read_csv(rank_csv, dtype={"isin": str, "ticker": str}, keep_default_na=False, na_values=[""])
        mp = pd.read_csv(membership_csv, dtype=str, keep_default_na=False, na_values=[""])
        sy = pd.read_csv(symbology_csv, dtype={"isin": str, "new_isin": str}, keep_default_na=False, na_values=[""],
                         usecols=["quote_id", "isin", "new_isin"], low_memory=False)
        return cls(rp, mp, sy)

    # -- helpers ----------------------------------------------------------------
    @staticmethod
    def _latest(dates: np.ndarray, d: pd.Timestamp):
        i = np.searchsorted(dates, np.datetime64(d), side="right") - 1
        return None if i < 0 else pd.Timestamp(dates[i])

    def _equivalents(self, isin: str) -> list[str]:
        """The ISIN itself first, then every other ISIN that shares a quote_id with it."""
        out = [isin]
        for q in sorted(self._q_of_i.get(isin, ())):
            for alt in sorted(self._i_of_q.get(q, ())):
                if alt not in out:
                    out.append(alt)
        return out

    def _rank_snapshot(self, snap: pd.Timestamp):
        if snap not in self._rank_cache:
            g = self._rank_by_date[snap]
            self._rank_cache[snap] = (dict(zip(g["quote_id"].astype(int), zip(g["rank"], g["band"]))),
                                      {i: int(q) for i, q in zip(g["isin"], g["quote_id"]) if isinstance(i, str)})
        return self._rank_cache[snap]

    def _rank_hit(self, snap: pd.Timestamp, isin: str):
        by_q, by_i = self._rank_snapshot(snap)
        if isin in by_i:
            r, b = by_q[by_i[isin]]
            return int(r), b, "isin"
        for q in sorted(self._q_of_i.get(isin, ())):
            if q in by_q:
                r, b = by_q[q]
                return int(r), b, "symbology"
        return None

    # -- the lookup -------------------------------------------------------------
    def tag(self, isin, asof) -> dict:
        d = pd.Timestamp(asof)
        none = {"band": SMALL, "source": "unranked", "snapshot": None, "detail": None, "via": None}
        if not isinstance(isin, str) or not isin:
            return none
        if self.cutoff is not None and d >= self.cutoff:
            s = self._latest(self._memb_dates, d)
            members = self._memb[s]
            for alt in self._equivalents(isin):
                if alt in members:
                    idx, band = members[alt]
                    return {"band": band, "source": "membership", "snapshot": str(s.date()), "detail": idx,
                            "via": "isin" if alt == isin else "symbology"}
            src = "nonmember_rank"
        else:
            src = "rank"
        s = self._latest(self._rank_dates, d)
        if s is None:
            return none
        hit = self._rank_hit(s, isin)
        if hit is None:
            return {**none, "snapshot": str(s.date())}
        rank, band, via = hit
        return {"band": band, "source": src, "snapshot": str(s.date()), "detail": rank, "via": via}


# -- self-test on synthetic data ------------------------------------------------------
def _selftest() -> None:
    def panel(date, n, off=0):
        mcap = np.linspace(1e12, 1e9, n)  # rank 1 = quote_id 1000+off, ...
        return pd.DataFrame({"date": date, "quote_id": [1000 + i for i in range(n)], "isin": [f"IN{i:04d}" for i in range(n)],
                             "ticker": [f"T{i}" for i in range(n)], "mcap": mcap, "rank": range(1, n + 1),
                             "n_ranked": n, "band": [LARGE if r <= 100 else MID if r <= 250 else SMALL for r in range(1, n + 1)]})

    rp = pd.concat([panel("2026-03-31", 300), panel("2026-04-30", 300)], ignore_index=True)
    # 2026-04-30 snapshot: IN0299 (rank 300) is renamed to NEW0299 on that date, and IN0150 has no ISIN (null) on that date
    rp.loc[(rp["date"] == "2026-04-30") & (rp["isin"] == "IN0299"), "isin"] = "NEW0299"
    rp.loc[(rp["date"] == "2026-04-30") & (rp["isin"] == "IN0150"), "isin"] = np.nan
    mp = pd.DataFrame([{"snapshot_date": "2026-04-09", "index_name": "NIFTY 100", "isin": "IN0299", "symbol": "X", "band": LARGE},
                       {"snapshot_date": "2026-04-09", "index_name": "NIFTY MIDCAP 150", "isin": "IN0005", "symbol": "Y", "band": MID}])
    sy = pd.DataFrame({"quote_id": [1299, 1150], "isin": ["IN0299", "IN0150"], "new_isin": ["NEW0299", np.nan]})
    t = TagLookup(rp, mp, sy)
    eq = lambda got, **kw: all(got[k] == v for k, v in kw.items()) or (_ for _ in ()).throw(AssertionError(f"{got} != {kw}"))

    assert t.cutoff == pd.Timestamp("2026-04-09")
    # before the cutoff: rank snapshot, bands at the boundaries
    eq(t.tag("IN0099", "2026-04-08"), band=LARGE, source="rank", snapshot="2026-03-31", detail=100)
    eq(t.tag("IN0100", "2026-04-08"), band=MID, source="rank", detail=101)
    eq(t.tag("IN0249", "2026-04-08"), band=MID, detail=250)
    eq(t.tag("IN0250", "2026-04-08"), band=SMALL, detail=251)
    # membership applies from the cutoff itself, and overrides rank (IN0299 is rank 300 -> Small by rank, Large by membership)
    eq(t.tag("IN0299", "2026-04-08"), band=SMALL, source="rank")
    eq(t.tag("IN0299", "2026-04-09"), band=LARGE, source="membership", snapshot="2026-04-09", detail="NIFTY 100")
    # point in time: on 2026-04-29 the 2026-04-30 rank snapshot must not be used (non-member falls back to 03-31)
    eq(t.tag("IN0050", "2026-04-29"), source="nonmember_rank", snapshot="2026-03-31")
    eq(t.tag("IN0050", "2026-04-30"), source="nonmember_rank", snapshot="2026-04-30")
    # no snapshot at all before the first rank date
    eq(t.tag("IN0050", "2026-01-01"), source="unranked", band=SMALL, snapshot=None)
    # renamed ISIN: the holding still carries the old ISIN, the 04-30 snapshot has the new one (found through symbology)
    eq(t.tag("IN0299", "2026-05-10"), source="membership", via="isin")   # member list still has the old ISIN
    eq(t.tag("NEW0299", "2026-05-10"), source="membership", via="symbology")
    # a stock whose ISIN is null on the snapshot is found through its quote_id, not lost
    eq(t.tag("IN0150", "2026-05-10"), source="nonmember_rank", via="symbology", detail=151, band=MID)
    # unknown or empty ISIN: unranked, never an error
    eq(t.tag("INXXXX", "2026-05-10"), source="unranked", band=SMALL, snapshot="2026-04-30")
    eq(t.tag(None, "2026-05-10"), source="unranked")
    eq(t.tag("", "2026-05-10"), source="unranked")
    print("tag_lookup self-test: all checks passed")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        print(__doc__)
