# -*- coding: utf-8 -*-
"""
Segment-level overlay v2: the engine.

The rule under test (`sleeve`). At each event, tag every parent holding with
its market-cap index and hold it only if that index's supertrend is BUY.
Held names keep their parent weights. The weight freed by names whose index
is in SELL goes to 50% gold and 50% cash. The rule is fixed in
`evidence/segment_v2/PREREGISTRATION.md`.

What is new against Study 2's `segment_backtest.py`:

  * **Tags come from a point-in-time cascade** (`HybridTagger`). Real index
    membership is used where a snapshot exists, monthly ranks before that,
    with explicit handling for non-members and unranked names. Every tag
    records which step of the cascade decided it.
  * **Re-tagging happens at events, not every week.** An event is a flip in
    any of the four index signals, or a change of parent basket. Between
    events the book drifts, so a stock crossing a rank boundary does not
    trade by itself.
  * **Securities are keyed on ISIN** (see `segment_v2_data`), so renames no
    longer drop names.
  * **The simulator is vectorised.** `Simulator.run` reproduces
    `segment_backtest.simulate` step for step; `regression_v2.py` checks the
    two agree to 1e-12. It is fast enough for the ~6,000 runs the two nulls
    need.

Point-in-time discipline, asserted per row as in Study 2:
  * a review's decision fills on the next session, never the same one;
  * the parent basket is keyed on `availableDate`;
  * no rank or membership snapshot is ever dated after the review that uses
    it.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

import segment_v2_data as D
from common import EVIDENCE_DIR
from mcap_ranks import MICRO_CEILING

EVIDENCE_SUBDIR = EVIDENCE_DIR / "segment_v2"
PREREG = EVIDENCE_SUBDIR / "PREREGISTRATION.md"

COST_BPS = [0.0, 20.8, 50.0]
PRIMARY_BPS = 20.8
K_THRESHOLD = 0.60
TARGET_TOL = 1e-9
GOLD, CASH = "GOLDBEES", "CASH"

N100, MC150, SC250, MICRO, SC100 = (
    "Nifty100", "NiftyMidcap150", "NiftySmallcap250", "NiftyMicrocap250", "SC100")
EVENT_COLS = [N100, MC150, SC250, MICRO]
SHORT = {N100: "N100", MC150: "MC150", SC250: "SC250", MICRO: "Micro250", SC100: "SC100"}
OWN_INDEX = {"Largecap": N100, "Midcap": MC150, "Smallcap": SC250, "Microcap": MICRO}
PRIORITY = ["Largecap", "Midcap", "Smallcap", "Microcap"]
# Production's FS map: Small, Micro and Unknown all read Smallcap 250.
FS_INDEX = {"Largecap": N100, "Midcap": MC150}
UNKNOWNISH = {"nonmember_rank", "rank>900", "unranked"}


def prereg_sha256() -> str:
    return hashlib.sha256(PREREG.read_bytes()).hexdigest()


# ── Signals and calendar ───────────────────────────────────────────────────
def load_signs(master_dir=None) -> pd.DataFrame:
    """
    Weekly BUY/SELL per index from the frozen Master workbooks.

    The review grid is the union of the four event indices' dates, exactly as
    Study 2 built it. SC100, used only by the whole-book `N100 AND SC100`
    comparator, is aligned onto that grid rather than allowed to add dates.
    """
    master_dir = master_dir or D.MASTER_DIR

    def one(name):
        d = pd.read_excel(master_dir / f"Master_{name}.xlsx")
        d["Date"] = pd.to_datetime(d["Date"])
        s = d.dropna(subset=["SIGN"]).set_index("Date")["SIGN"].sort_index()
        return s[~s.index.duplicated(keep="last")]

    signs = pd.DataFrame({n: one(n) for n in EVENT_COLS}).sort_index()
    sc100 = one(SC100)
    signs[SC100] = sc100.reindex(signs.index.union(sc100.index)).ffill().reindex(signs.index)
    return signs


def effective_signs(signs: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    """
    Apply the Microcap fallback once, up front: wherever Microcap 250 has no
    SIGN (before 2022-02-18, and on its in-window NaNs), read Smallcap 250.
    Returns the effective frame and the fallback mask.
    """
    e = signs.copy()
    fb = e[MICRO].isna()
    e.loc[fb, MICRO] = e.loc[fb, SC250]
    return e, fb


def window_reviews(signs: pd.DataFrame) -> pd.DatetimeIndex:
    return signs.index[(signs.index >= D.WINDOW_START) & (signs.index <= D.WINDOW_END)]


def session_calendar() -> pd.DatetimeIndex:
    """Window sessions plus one lead-in session, as in Study 2."""
    d = pd.read_csv(D.CALENDAR_CSV)
    idx = pd.DatetimeIndex(pd.to_datetime(d["date"]).unique()).sort_values()
    idx = idx[idx <= D.WINDOW_END]
    prior = idx[idx < D.WINDOW_START]
    return idx[idx >= prior[-1]]


def common_start(calendar: pd.DatetimeIndex, reviews) -> pd.Timestamp:
    """
    The session every series is rebased on: the last session on or before the
    first review that also exists in the published NAV files. This is
    2021-11-03, not 2021-11-04. The 2021-11-04 Diwali muhurat session is in the
    trading calendar but not in `parentIndices.csv` / `indices.csv`, so
    rebasing on it hands the published series one extra day of return. The
    simulated books hold nothing until the first fill (2021-11-08) either way.
    """
    from common import PARENT_INDEX_CSV  # noqa: PLC0415

    raw = pd.read_csv(PARENT_INDEX_CSV, usecols=["date"])
    pub = pd.DatetimeIndex(pd.to_datetime(raw["date"], format="%d/%m/%y %H:%M").unique())
    both = calendar.intersection(pub)
    return both[both <= reviews[0]][-1]


def shift_signs(sig: pd.DataFrame, reviews: pd.DatetimeIndex, k: int) -> pd.DataFrame:
    """G4: roll the whole in-window signal matrix by k reviews, wrapping."""
    out = sig.copy()
    block = sig.loc[reviews].to_numpy(dtype=object)
    out.loc[reviews] = np.roll(block, k, axis=0)
    return out


# ── Tags ───────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Tag:
    bucket: str            # Largecap / Midcap / Smallcap / Microcap / Unknown
    source: str            # manual / membership / nonmember_rank / rank / rank>900 / unranked
    snapshot: pd.Timestamp | None
    rank: int | None


def _latest(snaps: np.ndarray, when) -> pd.Timestamp | None:
    """Latest snapshot dated on or before `when` (snaps: sorted datetime64)."""
    i = np.searchsorted(snaps, np.datetime64(pd.Timestamp(when)), side="right")
    return pd.Timestamp(snaps[i - 1]) if i else None


class HybridTagger:
    """
    The pre-registered cascade. For each holding, first match wins:

        manual override → membership → non-member's rank band →
        rank band (before the first membership snapshot) →
        rank > 900 → unranked

    `membership=None` gives the ranks-only sensitivity.
    """

    def __init__(self, ranks: pd.DataFrame, membership: pd.DataFrame | None = None,
                 overrides: pd.DataFrame | None = None):
        r = ranks.sort_values(["snapshot_date", "rank"], ascending=[True, False])
        self._rsnaps = np.array(sorted(pd.to_datetime(r["snapshot_date"].unique())), dtype="datetime64[ns]")
        self._r_isin, self._r_tkr = {}, {}
        for d, g in r.groupby("snapshot_date"):
            vals = list(zip(g["rank"].astype(int), g["category"]))
            # Sorted rank-descending so the best rank wins a duplicate key.
            self._r_isin[pd.Timestamp(d)] = dict(zip(g["isin"].fillna(""), vals))
            self._r_tkr[pd.Timestamp(d)] = dict(zip(g["ticker"], vals))

        self._msnaps = np.array([], dtype="datetime64[ns]")
        self._m_isin, self._m_sym = {}, {}
        if membership is not None and len(membership):
            m = membership.copy()
            m["pri"] = m["category"].map(PRIORITY.index)
            m = m.sort_values(["snapshot_date", "pri"], ascending=[True, False])
            self._msnaps = np.array(sorted(pd.to_datetime(m["snapshot_date"].unique())), dtype="datetime64[ns]")
            for d, g in m.groupby("snapshot_date"):
                self._m_isin[pd.Timestamp(d)] = dict(zip(g["isin"].fillna(""), g["category"]))
                self._m_sym[pd.Timestamp(d)] = dict(zip(g["symbol"], g["category"]))

        self._ov_isin, self._ov_tkr = {}, {}
        if overrides is not None and len(overrides):
            for _, o in overrides.iterrows():
                if o.get("isin"):
                    self._ov_isin[str(o["isin"]).upper()] = o["bucket"]
                if o.get("ticker"):
                    self._ov_tkr[str(o["ticker"]).upper()] = o["bucket"]
        self._cache: dict = {}

    def _rank(self, snap, isin, ticker):
        if snap is None:
            return None
        v = self._r_isin[snap].get(isin) if isin else None
        return v if v is not None else self._r_tkr[snap].get(ticker)

    def tag(self, isin: str, ticker: str, when) -> Tag:
        when = pd.Timestamp(when)
        rsnap = _latest(self._rsnaps, when)
        msnap = _latest(self._msnaps, when) if len(self._msnaps) else None
        ck = (isin, ticker, rsnap, msnap)
        if ck in self._cache:
            return self._cache[ck]

        if isin in self._ov_isin or ticker in self._ov_tkr:
            t = Tag(self._ov_isin.get(isin) or self._ov_tkr[ticker], "manual", None, None)
            self._cache[ck] = t
            return t

        if rsnap is not None:
            assert rsnap <= when, "PIT violation: future rank snapshot"
        rk = self._rank(rsnap, isin, ticker)
        rank, band = (rk if rk else (None, None))

        if msnap is not None:
            assert msnap <= when, "PIT violation: future membership snapshot"
            cat = (self._m_isin[msnap].get(isin) if isin else None) \
                or self._m_sym[msnap].get(ticker)
            if cat:
                t = Tag(cat, "membership", msnap, rank)
            elif rank is not None:
                t = Tag(band if rank <= MICRO_CEILING else "Unknown",
                        "nonmember_rank", rsnap, rank)
            else:
                t = Tag("Unknown", "unranked", None, None)
        elif rank is not None:
            t = (Tag(band, "rank", rsnap, rank) if rank <= MICRO_CEILING
                 else Tag("Unknown", "rank>900", rsnap, rank))
        else:
            t = Tag("Unknown", "unranked", None, None)
        self._cache[ck] = t
        return t


class V1Tagger:
    """Study 2's `PITClassifier`, behind the v2 interface, for the regression."""

    def __init__(self, clf):
        self.clf = clf

    def tag(self, isin: str, ticker: str, when) -> Tag:
        snap = self.clf.snapshot_asof(when)
        return Tag(self.clf.classify(ticker, when), "rank", snap, self.clf.rank(ticker, when))


def signal_index(tag: Tag, variant: str) -> str | None:
    """Which index's SIGN decides this holding, or None for never-hold."""
    b, src = tag.bucket, tag.source
    if variant == "micro_proxy":
        return OWN_INDEX[b] if b in ("Largecap", "Midcap") else SC250
    if variant == "unknown_to_sleeve" and src in UNKNOWNISH:
        return None
    if variant == "unknown_to_sc250" and src in UNKNOWNISH:
        return SC250
    if b in OWN_INDEX:
        return OWN_INDEX[b]
    # Unknown: ranked beyond the Microcap band reads Microcap 250, the nearest
    # trend for something smaller than micro; unranked reads Smallcap 250.
    return MICRO if tag.rank is not None else SC250


# ── Parent context ─────────────────────────────────────────────────────────
@dataclass
class ParentCtx:
    parent: str
    reviews: list
    entry_i: list
    basket_eff: list
    baskets: dict                     # eff_date -> list[(key, ticker, name, isin, w)]
    audit: dict = field(default_factory=dict)


def parent_ctx(parent: str, hist: pd.DataFrame, reviews, calendar: pd.DatetimeIndex,
               key_col: str = "key") -> ParentCtx:
    """
    Pre-compute, per review: the entry session and the basket in effect.
    `key_col="ticker"` reproduces Study 2's ticker keying for the regression.
    """
    effs = np.array(sorted(hist["eff_date"].unique()), dtype="datetime64[ns]")
    baskets = {}
    for e, g in hist.groupby("eff_date"):
        w = g["weight"].to_numpy(dtype=float)
        tot = np.nansum(w)
        if not np.isfinite(tot) or tot <= 0:
            continue
        baskets[pd.Timestamp(e)] = [
            (k, t, n, i, float(x)) for k, t, n, i, x in
            zip(g[key_col], g["ticker"], g["name"], g.get("isin", g["ticker"]), w / tot)]

    cal = calendar.to_numpy(dtype="datetime64[ns]")
    rv, ei, be = [], [], []
    audit = {"reviews_no_parent_basket": 0, "reviews_past_calendar_end": 0,
             "pit_signal_before_entry_ok": 0, "pit_basket_not_future_ok": 0}
    for r in reviews:
        j = np.searchsorted(cal, np.datetime64(r), side="right")
        if j >= len(cal):
            audit["reviews_past_calendar_end"] += 1
            continue
        assert cal[j] > np.datetime64(r), "PIT violation: entry must follow the review"
        audit["pit_signal_before_entry_ok"] += 1
        k = np.searchsorted(effs, np.datetime64(r), side="right")
        if k == 0:
            audit["reviews_no_parent_basket"] += 1
            continue
        eff = pd.Timestamp(effs[k - 1])
        assert eff <= r, "PIT violation: future basket"
        audit["pit_basket_not_future_ok"] += 1
        if eff not in baskets:
            continue
        rv.append(pd.Timestamp(r)); ei.append(int(j)); be.append(eff)
    return ParentCtx(parent, rv, ei, be, baskets, audit)


def tag_table(ctx: ParentCtx, tagger) -> dict:
    """tags[review][key] -> Tag, for every review and every name in its basket."""
    out = {}
    for r, eff in zip(ctx.reviews, ctx.basket_eff):
        out[r] = {k: tagger.tag(i if isinstance(i, str) else "", t, r)
                  for k, t, _, i, _ in ctx.baskets[eff]}
    return out


# ── Target builders ────────────────────────────────────────────────────────
@dataclass
class Step:
    review: pd.Timestamp
    entry_i: int
    weights: dict                     # key -> target weight (> 0 only)
    sleeve: float
    event: bool = False
    trigger: str = ""
    rows: list | None = None


def _flip_labels(prev, cur) -> list[str]:
    out = []
    for c, a, b in zip(EVENT_COLS, prev, cur):
        if a != b:
            out.append(f"{SHORT[c]} {a}→{b}")
    return out


def _events(ctx: ParentCtx, sig: pd.DataFrame):
    """Yield (review, is_event, trigger) with the pre-registered event rule."""
    rows = sig.loc[ctx.reviews, EVENT_COLS].fillna("NA").to_numpy(dtype=object)
    prev, prev_eff = None, None
    for n, (r, eff) in enumerate(zip(ctx.reviews, ctx.basket_eff)):
        cur = tuple(rows[n])
        if prev is None:
            yield r, True, "first review"
        else:
            parts = _flip_labels(prev, cur)
            if eff != prev_eff:
                parts.append("parent rebalance")
            yield r, bool(parts), "; ".join(parts)
        prev, prev_eff = cur, eff


def build_sleeve(ctx: ParentCtx, sig: pd.DataFrame, tags: dict, retag: str = "event",
                 variant: str = "micro_own", n100gate: bool = False,
                 detail: bool = False) -> list[Step]:
    steps, tag_ref = [], None
    srows = sig.loc[ctx.reviews]
    for (r, is_event, trig), ei, eff in zip(_events(ctx, sig), ctx.entry_i, ctx.basket_eff):
        if retag == "weekly" or is_event or tag_ref is None:
            tag_ref = r
        s = srows.loc[r]
        n100_buy = s[N100] == "BUY"
        w, rows = {}, [] if detail else None
        for key, tkr, name, isin, pw in ctx.baskets[eff]:
            tg = tags[tag_ref][key]
            idx = signal_index(tg, variant)
            sign = s[idx] if idx else "n/a"
            hold = bool(idx) and sign == "BUY"
            if n100gate:
                hold = hold and n100_buy
            if hold:
                w[key] = w.get(key, 0.0) + pw
            if detail:
                rows.append({"key": key, "ticker": tkr, "name": name, "parent_weight": pw,
                             "bucket": tg.bucket, "tag_source": tg.source,
                             "tag_snapshot": tg.snapshot, "rank": tg.rank,
                             "signal_index": SHORT.get(idx, "none"), "sign": sign,
                             "hold": hold})
        eq = sum(w.values())
        steps.append(Step(r, ei, w, max(0.0, 1.0 - eq), is_event, trig, rows))
    return steps


def build_production(ctx: ParentCtx, sig: pd.DataFrame, tags: dict,
                     detail: bool = False) -> list[Step]:
    """
    Production v2's whole-book rule: count-weighted FS ≥ 0.60, re-tagged every
    review as production does, on the same tags as the arm.
    """
    steps = []
    srows = sig.loc[ctx.reviews]
    for (r, is_event, trig), ei, eff in zip(_events(ctx, sig), ctx.entry_i, ctx.basket_eff):
        basket = ctx.baskets[eff]
        s = srows.loc[r]
        buckets = [tags[r][k].bucket for k, *_ in basket]
        n = len(buckets)
        fs = 0.0
        for b in set(buckets):
            share = sum(1 for x in buckets if x == b) / n
            fs += share * (1.0 if s[FS_INDEX.get(b, SC250)] == "BUY" else 0.0)
        equity = fs >= K_THRESHOLD
        w = {}
        if equity:
            for k, _, _, _, pw in basket:
                w[k] = w.get(k, 0.0) + pw
        rows = None
        if detail:
            rows = [{"key": k, "ticker": t, "name": nm, "parent_weight": pw,
                     "bucket": tags[r][k].bucket, "tag_source": tags[r][k].source,
                     "tag_snapshot": tags[r][k].snapshot, "rank": tags[r][k].rank,
                     "signal_index": "FS", "sign": f"FS={fs:.2f}", "hold": equity}
                    for k, t, nm, _, pw in basket]
        steps.append(Step(r, ei, w, 0.0 if equity else 1.0, is_event, trig, rows))
    return steps


def build_parent(ctx: ParentCtx, sig: pd.DataFrame, tags: dict | None = None,
                 detail: bool = False) -> list[Step]:
    steps = []
    for (r, is_event, trig), ei, eff in zip(_events(ctx, sig), ctx.entry_i, ctx.basket_eff):
        w = {}
        for k, _, _, _, pw in ctx.baskets[eff]:
            w[k] = w.get(k, 0.0) + pw
        steps.append(Step(r, ei, w, 0.0, is_event, trig, None))
    return steps


def build_whole_book_and(ctx: ParentCtx, sig: pd.DataFrame, keys=(N100, SC100),
                         detail: bool = False) -> list[Step]:
    """Study 1's winner: hold the whole parent iff every named index is BUY."""
    steps = []
    srows = sig.loc[ctx.reviews]
    for (r, is_event, trig), ei, eff in zip(_events(ctx, sig), ctx.entry_i, ctx.basket_eff):
        s = srows.loc[r]
        equity = all(s[k] == "BUY" for k in keys)
        w = {}
        if equity:
            for k, _, _, _, pw in ctx.baskets[eff]:
                w[k] = w.get(k, 0.0) + pw
        steps.append(Step(r, ei, w, 0.0 if equity else 1.0, is_event, trig, None))
    return steps


# ── Simulation ─────────────────────────────────────────────────────────────
class Simulator:
    """
    Units-based NAV, reproducing `segment_backtest.simulate` exactly, on
    numpy arrays. The sleeve is carried as two unit holdings: gold at
    GOLDBEES's traded price, and cash at the reinvested LIQUIDBEES
    total-return level.
    """

    def __init__(self, panel, sleeve: pd.DataFrame, close: pd.DataFrame | None = None,
                 sleeve_fill: pd.DataFrame | None = None):
        """
        `close` (raw, not forward-filled, same calendar and columns as the
        panel) switches on the close fallback: a session whose OHLC4 is
        incomplete but which has a close fills at that close. Without it the
        name is unfillable on that session, as in Study 2. That matters on
        2025-11-24, when the price table has a close but no open for 2,401 of
        2,768 rows: Study 2's rule piled every book into the handful of names
        with a full bar for a week. `regression_v2.py` runs without `close`,
        so it still reproduces Study 2 exactly.

        `sleeve_fill` (optional, same columns as `sleeve`) gives the sleeve
        assets their own fill price, e.g. GOLDBEES at the entry session's
        OHLC4. Where it is missing the sleeve fills at its marking level, as
        before; without it every earlier study reproduces unchanged.
        """
        self.cal = panel.calendar
        keys = list(panel.fill.columns) + list(sleeve.columns)
        self.col = {k: i for i, k in enumerate(keys)}
        sl = sleeve.reindex(self.cal).to_numpy(dtype=float)
        sl_fill = sl
        if sleeve_fill is not None:
            sf = sleeve_fill.reindex(index=self.cal, columns=sleeve.columns).to_numpy(dtype=float)
            sl_fill = np.where(np.isfinite(sf), sf, sl)
        f = panel.fill.to_numpy(dtype=float)
        self.close_fallback_cells = 0
        if close is not None:
            c = close.reindex(index=self.cal, columns=panel.fill.columns).to_numpy(dtype=float)
            use = ~np.isfinite(f) & np.isfinite(c)
            self.close_fallback_cells = int(use.sum())
            f = np.where(use, c, f)
        self.fill = np.hstack([f, sl_fill])
        self.mark = np.hstack([panel.mark.to_numpy(dtype=float), sl])
        self.mark0 = np.where(np.isfinite(self.mark), self.mark, 0.0)

    def _p(self, t: str, i: int, kind: str) -> float:
        c = self.col.get(t)
        if c is None:
            return np.nan
        v = (self.fill if kind == "fill" else self.mark)[i, c]
        return float(v) if np.isfinite(v) else np.nan

    def _pf(self, t, i):
        p = self._p(t, i, "fill")
        return p if np.isfinite(p) else self._p(t, i, "mark")

    def _mark_range(self, units: dict, lo: int, hi: int, nav: np.ndarray) -> None:
        if hi <= lo:
            return
        if not units:
            nav[lo:hi] = 0.0
            return
        cols = [self.col[t] for t in units if t in self.col]
        u = np.array([units[t] for t in units if t in self.col])
        nav[lo:hi] = self.mark0[lo:hi][:, cols] @ u if cols else 0.0

    def run(self, steps: list[Step], cost_bps: float, gold_share: float | dict = 0.5,
            audit: dict | None = None, positions: bool = False, close_on_trade_day: bool = False):
        """
        `close_on_trade_day`: value the book at the trade session's close
        (units bought at the fill, marked at the close). The default keeps
        the original convention, where the trade session's NAV is its value
        at the fill prices, so every earlier study reproduces unchanged.
        """
        audit = audit if audit is not None else {}
        for k in ("target_rows_no_price", "entries_nothing_fillable", "reviews_no_trade"):
            audit.setdefault(k, 0)
        n = len(self.cal)
        one_way = (cost_bps / 2.0) / 10_000.0

        by_entry: dict[int, Step] = {}
        for s in steps:                       # later review wins a shared entry
            by_entry[s.entry_i] = s
        entries = sorted(by_entry)
        if not entries:
            raise ValueError("no target entry date falls on the calendar")

        nav = np.full(n, np.nan)
        nav[:entries[0]] = 1.0
        units: dict[str, float] = {}
        last_target: dict | None = None
        log, pos_log = [], []

        for k, i in enumerate(entries):
            st = by_entry[i]
            nav_now = 0.0
            for t, u in units.items():
                p = self._pf(t, i)
                nav_now += u * (p if np.isfinite(p) else 0.0)
            if k == 0:
                nav_now = 1.0
            if not np.isfinite(nav_now) or nav_now <= 0:
                break

            tgt = {t: w for t, w in st.weights.items() if w > 0}
            if st.sleeve > 1e-9:
                # `gold_share` is a constant, or a {review: share} map for a
                # sleeve whose gold/cash split is itself decided each week.
                gs = gold_share.get(st.review, 0.5) if isinstance(gold_share, dict) else gold_share
                if gs > 0:
                    tgt[GOLD] = tgt.get(GOLD, 0.0) + st.sleeve * gs
                if gs < 1:
                    tgt[CASH] = tgt.get(CASH, 0.0) + st.sleeve * (1.0 - gs)

            fillable = {}
            for t, w in tgt.items():
                p = self._p(t, i, "fill")
                if np.isfinite(p) and p > 0:
                    fillable[t] = w
                else:
                    audit["target_rows_no_price"] += 1
            s = sum(fillable.values())
            if s <= 0:
                audit["entries_nothing_fillable"] += 1
                continue
            fillable = {t: w / s for t, w in fillable.items()}

            end = entries[k + 1] if k + 1 < len(entries) else n
            unchanged = (last_target is not None and set(fillable) == set(last_target)
                         and all(abs(fillable[t] - last_target[t]) <= TARGET_TOL
                                 for t in fillable))
            if unchanged:
                audit["reviews_no_trade"] += 1
                self._mark_range(units, i, end, nav)
                continue

            before = {}
            if positions:
                for t, u in units.items():
                    p = self._pf(t, i)
                    before[t] = u * (p if np.isfinite(p) else 0.0) / nav_now

            new_units = {t: (nav_now * w) / self._p(t, i, "fill") for t, w in fillable.items()}
            last_target = dict(fillable)
            traded = 0.0
            for t in set(units) | set(new_units):
                p = self._pf(t, i)
                if np.isfinite(p):
                    traded += abs(new_units.get(t, 0.0) - units.get(t, 0.0)) * p
            cost = traded * one_way
            units = new_units
            if cost > 0:
                scale = (nav_now - cost) / nav_now
                units = {t: u * scale for t, u in units.items()}
            nav[i] = nav_now - cost
            nav_fill = nav[i]
            if close_on_trade_day:
                cols = [self.col[t] for t in units if t in self.col]
                u_ = np.array([units[t] for t in units if t in self.col])
                nav[i] = float(self.mark0[i, cols] @ u_) if cols else 0.0
            log.append({"entry": self.cal[i], "review": st.review, "n_target": len(tgt),
                        "n_filled": len(new_units), "sleeve_weight": st.sleeve,
                        "turnover_value": traded, "turnover_frac": traded / nav_now,
                        "cost": cost, "nav": nav[i], "nav_at_fill": nav_fill})
            if positions:
                for t in set(before) | set(fillable):
                    pos_log.append({"entry": self.cal[i], "review": st.review, "key": t,
                                    "w_before": before.get(t, 0.0),
                                    "w_after": fillable.get(t, 0.0),
                                    "fill_price": self._p(t, i, "fill")})
            self._mark_range(units, i + 1, end, nav)

        s = pd.Series(nav, index=self.cal, name="nav").ffill()
        out = s / s.iloc[0]
        if positions:
            return out, pd.DataFrame(log), pd.DataFrame(pos_log)
        return out, pd.DataFrame(log)


def exposure(steps: list[Step], calendar: pd.DatetimeIndex) -> pd.Series:
    """Target equity weight in force on each session (after the entry fill)."""
    s = pd.Series(np.nan, index=calendar)
    for st in steps:
        s.iloc[st.entry_i] = sum(st.weights.values())
    return s.ffill().fillna(0.0)
