# -*- coding: utf-8 -*-
"""
Segment-level allocation backtest.

The production overlay is all-or-nothing: a count-weighted signal score flips
the entire book between the parent basket and a 50/50 gold+cash sleeve. This
tests the alternative -- hold the stocks whose *own* market-cap bucket is in
BUY, drop the rest.

Arms:

  `sleeve`          hold a stock iff its own bucket's SIGN is BUY; survivors
                    keep parent weights; freed weight -> 50% GOLDCASE +
                    50% LIQUIDCASE.
  `rotate`          same selection, freed weight redistributed equally across
                    survivors, so the book stays 100% equity. Falls back to
                    the sleeve only when no bucket is BUY -- a book cannot
                    hold nothing.
  `sleeve_n100gate` `sleeve` plus a large-cap confirmation: hold iff own
                    bucket is BUY AND Nifty 100 is BUY. When Nifty 100 is SELL
                    the book goes fully defensive. The gate is redundant for
                    Largecap holdings, so it bites only on Mid/Small/Micro/
                    Unknown.

Baselines: the un-overlaid parent, and production's v2 rule (FS >= 0.60)
re-simulated on the same mechanics so the comparison is like-for-like.

Point-in-time discipline (house rule 4), asserted rather than assumed:

  * a SIGN dated for a Friday review applies from the NEXT session, never the
    same one;
  * the parent basket is keyed on `availableDate`, never `date`;
  * a cap rank is read from the latest snapshot dated on or before the review;
  * every one of those is asserted per row, and the violation counts are
    written into `audit.json`.

Mechanics follow `simulate()`: units not weights, OHLC4 fills, forward-filled
close for interior marking, the rebalance session stamped at the fill price,
cost charged on the change in each position. Gross and net are always reported
together (house rule 3) at 0 / 20.8 / 50 bps round-trip, half charged per side.
"""

from __future__ import annotations

import os

import numpy as np
import pandas as pd

from common import CACHE_DIR, PAIRS
from index_builder import Panel, universe_ohlcv
from mcap_ranks import PITClassifier, load_cache
from prices import cash_total_return, defensive_prices
from supertrend import INDICES_OHLCV

FRIDAY_ROOT = os.path.dirname(str(INDICES_OHLCV)) + os.sep + ".."
MASTER_DIR = os.path.join(FRIDAY_ROOT, "RSI", "Final", "Analysis")

WINDOW_START = pd.Timestamp("2021-11-01")
WINDOW_END = pd.Timestamp("2026-08-21")
CALENDAR_CSV = os.path.join(FRIDAY_ROOT, "Data", "calendar.csv")

GOLD = "GOLDBEES"      # GOLDCASE's tradable proxy; the sleeve's gold leg
COST_BPS = [0.0, 20.8, 50.0]
K_THRESHOLD = 0.60

# Bucket -> Master workbook, per arm's microcap treatment.
SIGNAL_MAP = {
    "micro_proxy": {"Largecap": "Nifty100", "Midcap": "NiftyMidcap150",
                    "Smallcap": "NiftySmallcap250", "Microcap": "NiftySmallcap250",
                    "Unknown": "NiftySmallcap250"},
    "micro_own": {"Largecap": "Nifty100", "Midcap": "NiftyMidcap150",
                  "Smallcap": "NiftySmallcap250", "Microcap": "NiftyMicrocap250",
                  "Unknown": "NiftySmallcap250"},
}
ARMS = ["sleeve", "rotate", "sleeve_n100gate"]


# ── Inputs ─────────────────────────────────────────────────────────────────
def session_calendar() -> pd.DatetimeIndex:
    """Window sessions plus one lead-in session (F-M08)."""
    d = pd.read_csv(CALENDAR_CSV)
    idx = pd.DatetimeIndex(pd.to_datetime(d["date"]).unique()).sort_values()
    idx = idx[idx <= WINDOW_END]
    prior = idx[idx < WINDOW_START]
    return idx[idx >= prior[-1]]


def master_signs() -> pd.DataFrame:
    """Weekly BUY/SELL per index, from production's own Master workbooks."""
    cols = {}
    for name in ["Nifty100", "NiftyMidcap150", "NiftySmallcap250", "NiftyMicrocap250"]:
        d = pd.read_excel(os.path.join(MASTER_DIR, f"Master_{name}.xlsx"))
        d["Date"] = pd.to_datetime(d["Date"])
        s = d.dropna(subset=["SIGN"]).set_index("Date")["SIGN"].sort_index()
        cols[name] = s[~s.index.duplicated(keep="last")]
    return pd.DataFrame(cols).sort_index()


def parent_history(parent_scid: str) -> pd.DataFrame:
    p = os.path.join(FRIDAY_ROOT, "Rebalance_history",
                     f"Rebalance_history_by_scid_{parent_scid}.csv")
    d = pd.read_csv(p)
    d["eff_date"] = pd.to_datetime(d["availableDate"], format="%d/%m/%y %H:%M")
    d["signal_date"] = pd.to_datetime(d["date"])
    d["ticker"] = d["ticker"].astype(str).str.strip().str.upper()
    d["weight"] = pd.to_numeric(d["weight"], errors="coerce")
    return d.sort_values("eff_date")


# ── Target construction ────────────────────────────────────────────────────
def build_targets(parent_scid: str, arm: str, micro: str, signs: pd.DataFrame,
                  clf: PITClassifier, calendar: pd.DatetimeIndex,
                  audit: dict) -> pd.DataFrame:
    """
    One row per (entry session, ticker) with the target weight for this arm.

    `review` is the Friday the SIGN is dated for; `entry` is the next session
    on the calendar. Nothing is ever applied on the review session itself.
    """
    hist = parent_history(parent_scid)
    smap = SIGNAL_MAP[micro]
    reviews = signs.index[(signs.index >= WINDOW_START) & (signs.index <= WINDOW_END)]

    rows = []
    for review in reviews:
        later = calendar[calendar > review]
        if not len(later):
            audit["reviews_past_calendar_end"] += 1
            continue
        entry = later[0]
        assert review < entry, "PIT violation: entry must follow the review"
        audit["pit_signal_before_entry_ok"] += 1

        prior = hist[hist["eff_date"] <= review]
        if prior.empty:
            audit["reviews_no_parent_basket"] += 1
            continue
        basket = prior[prior["eff_date"] == prior["eff_date"].max()]
        assert basket["eff_date"].max() <= review, "PIT violation: future basket"
        audit["pit_basket_not_future_ok"] += 1

        snap = clf.snapshot_asof(review)
        if snap is None:
            audit["reviews_no_rank_snapshot"] += 1
            continue
        assert pd.Timestamp(snap) <= review, "PIT violation: future rank snapshot"
        audit["pit_rank_not_future_ok"] += 1

        w = basket["weight"].to_numpy(dtype=float)
        tot = np.nansum(w)
        if not np.isfinite(tot) or tot <= 0:
            audit["reviews_empty_basket"] += 1
            continue

        n100_buy = signs.loc[review, "Nifty100"] == "BUY"
        keep = []
        for tkr, wt in zip(basket["ticker"], w / tot):
            bucket = clf.classify(tkr, review)
            idx = smap[bucket]
            sig = signs.loc[review, idx]
            if pd.isna(sig):
                # No signal published for this index yet (Microcap 250 before
                # 2022-02-18). Fall back to the Smallcap 250 read, which is
                # production's own convention and which Work item 1 showed
                # tracks the official microcap signal at 97.5%.
                sig = signs.loc[review, "NiftySmallcap250"]
                audit["signal_fallback_rows"] += 1
            hold = sig == "BUY"
            if arm == "sleeve_n100gate":
                hold = hold and n100_buy
            rows.append({"review": review, "entry": entry, "ticker": tkr,
                         "parent_weight": wt, "bucket": bucket, "index": idx,
                         "sign": sig, "hold": hold})
            if hold:
                keep.append(tkr)

        if not keep:
            audit["reviews_fully_defensive"] += 1

    t = pd.DataFrame(rows)
    if t.empty:
        return t

    # Weights per arm.
    held = t[t["hold"]]
    if arm == "rotate":
        n = held.groupby("entry")["ticker"].transform("size")
        t["target_weight"] = np.where(t["hold"], 0.0, 0.0)
        t.loc[t["hold"], "target_weight"] = 1.0 / n
    else:
        t["target_weight"] = np.where(t["hold"], t["parent_weight"], 0.0)

    eq = t.groupby("entry")["target_weight"].transform("sum")
    t["sleeve_weight"] = (1.0 - eq).clip(lower=0.0)
    # `rotate` holds no sleeve unless nothing is held at all.
    if arm == "rotate":
        t["sleeve_weight"] = np.where(eq > 1e-9, 0.0, 1.0)
    return t


def production_targets(parent_scid: str, signs: pd.DataFrame, clf: PITClassifier,
                       calendar: pd.DatetimeIndex, audit: dict) -> pd.DataFrame:
    """Baseline: production v2's FS >= 0.60 all-or-nothing rule, same mechanics."""
    hist = parent_history(parent_scid)
    reviews = signs.index[(signs.index >= WINDOW_START) & (signs.index <= WINDOW_END)]
    fs_idx = {"Largecap": "Nifty100", "Midcap": "NiftyMidcap150",
              "Smallcap": "NiftySmallcap250", "Microcap": "NiftySmallcap250",
              "Unknown": "NiftySmallcap250"}
    rows = []
    for review in reviews:
        later = calendar[calendar > review]
        if not len(later):
            continue
        entry = later[0]
        prior = hist[hist["eff_date"] <= review]
        if prior.empty or clf.snapshot_asof(review) is None:
            continue
        basket = prior[prior["eff_date"] == prior["eff_date"].max()]
        tick = basket["ticker"].tolist()
        n = len(tick)
        if not n:
            continue
        # mcat_dist is a COUNT share of the parent, not a weight share.
        buckets = [clf.classify(t, review) for t in tick]
        fs = 0.0
        for b in set(buckets):
            share = sum(1 for x in buckets if x == b) / n
            fs += share * (1.0 if signs.loc[review, fs_idx[b]] == "BUY" else 0.0)
        equity = fs >= K_THRESHOLD
        w = basket["weight"].to_numpy(dtype=float)
        w = w / np.nansum(w)
        for tkr, wt in zip(basket["ticker"], w):
            rows.append({"review": review, "entry": entry, "ticker": tkr,
                         "parent_weight": wt, "bucket": clf.classify(tkr, review),
                         "index": "FS", "sign": "BUY" if equity else "SELL",
                         "hold": equity,
                         "target_weight": wt if equity else 0.0,
                         "sleeve_weight": 0.0 if equity else 1.0})
    return pd.DataFrame(rows)


def parent_targets(parent_scid: str, signs: pd.DataFrame, clf: PITClassifier,
                   calendar: pd.DatetimeIndex, audit: dict) -> pd.DataFrame:
    """Baseline: the un-overlaid parent, rebalanced on the same review grid."""
    t = production_targets(parent_scid, signs, clf, calendar, audit)
    if t.empty:
        return t
    t = t.copy()
    t["hold"] = True
    t["sign"] = "BUY"
    t["target_weight"] = t["parent_weight"]
    t["sleeve_weight"] = 0.0
    return t


# ── Simulation ─────────────────────────────────────────────────────────────
def simulate(targets: pd.DataFrame, panel: Panel, sleeve: pd.DataFrame,
             cost_bps: float, audit: dict) -> tuple[pd.Series, pd.DataFrame]:
    """
    Units-based NAV. The sleeve is carried as two synthetic unit holdings --
    gold at its traded price, cash at the reinvested LIQUIDBEES total-return
    level -- so it rebalances and costs exactly like any other position.
    """
    cal = panel.calendar
    pos = {d: i for i, d in enumerate(cal)}
    one_way = (cost_bps / 2.0) / 10_000.0

    entries = sorted(d for d in targets["entry"].unique() if d in pos)
    if not entries:
        raise ValueError("no target entry date falls on the calendar")

    nav = np.full(len(cal), np.nan)
    first = pos[entries[0]]
    nav[:first] = 1.0
    units: dict[str, float] = {}
    log = []

    by_entry = {d: g for d, g in targets.groupby("entry")}
    sleeve_cols = list(sleeve.columns)
    # The intended book at the last rebalance. A review that asks for the same
    # names at the same intended weights is not a trade -- positions are left
    # to drift, exactly as `simulate()` does. Re-trimming to target every week
    # would manufacture turnover in every held name and, on the un-overlaid
    # parent baseline, suppress the within-period drift that the published
    # parent index actually earns.
    last_target: dict[str, float] | None = None
    TARGET_TOL = 1e-9

    def price(t: str, i: int, kind: str) -> float:
        if t in sleeve_cols:
            v = sleeve[t].iloc[i]           # sleeve legs have no intraday bar
            return float(v) if np.isfinite(v) else np.nan
        src = panel.fill if kind == "fill" else panel.mark
        v = src.iloc[i].get(t, np.nan)
        return float(v) if np.isfinite(v) else np.nan

    for k, d in enumerate(entries):
        i = pos[d]
        g = by_entry[d]

        nav_now = 0.0
        for t, u in units.items():
            p = price(t, i, "fill")
            if not np.isfinite(p):
                p = price(t, i, "mark")
            nav_now += u * (p if np.isfinite(p) else 0.0)
        if k == 0:
            nav_now = 1.0
        if not np.isfinite(nav_now) or nav_now <= 0:
            break

        tgt: dict[str, float] = {}
        for tkr, w in zip(g["ticker"], g["target_weight"]):
            if w > 0:
                tgt[tkr] = tgt.get(tkr, 0.0) + float(w)
        sw = float(g["sleeve_weight"].iloc[0])
        if sw > 1e-9:
            tgt[GOLD] = tgt.get(GOLD, 0.0) + sw * 0.5
            tgt["CASH"] = tgt.get("CASH", 0.0) + sw * 0.5

        # Drop unfillable names and renormalise onto what can actually trade.
        fillable = {}
        for t, w in tgt.items():
            p = price(t, i, "fill")
            if np.isfinite(p) and p > 0:
                fillable[t] = w
            else:
                audit["target_rows_no_price"] += 1
        s = sum(fillable.values())
        if s <= 0:
            audit["entries_nothing_fillable"] += 1
            continue
        fillable = {t: w / s for t, w in fillable.items()}

        unchanged = (
            last_target is not None
            and set(fillable) == set(last_target)
            and all(abs(fillable[t] - last_target[t]) <= TARGET_TOL for t in fillable)
        )
        if unchanged:
            audit["reviews_no_trade"] += 1
            # Mark forward on the drifted book; do not touch units.
            end = pos[entries[k + 1]] if k + 1 < len(entries) else len(cal)
            for j in range(i, end):
                v = 0.0
                for t, u in units.items():
                    p = price(t, j, "mark")
                    if np.isfinite(p):
                        v += u * p
                nav[j] = v
            continue

        new_units = {t: (nav_now * w) / price(t, i, "fill") for t, w in fillable.items()}
        last_target = dict(fillable)

        traded = 0.0
        for t in set(units) | set(new_units):
            p = price(t, i, "fill")
            if not np.isfinite(p):
                p = price(t, i, "mark")
            if np.isfinite(p):
                traded += abs(new_units.get(t, 0.0) - units.get(t, 0.0)) * p
        cost = traded * one_way
        units = new_units
        if cost > 0:
            scale = (nav_now - cost) / nav_now
            units = {t: u * scale for t, u in units.items()}

        nav[i] = nav_now - cost
        log.append({"entry": d, "n_target": len(tgt), "n_filled": len(new_units),
                    "sleeve_weight": sw, "turnover_value": traded,
                    "cost": cost, "nav": nav[i]})

        end = pos[entries[k + 1]] if k + 1 < len(entries) else len(cal)
        for j in range(i + 1, end):
            v = 0.0
            for t, u in units.items():
                p = price(t, j, "mark")
                if np.isfinite(p):
                    v += u * p
            nav[j] = v

    s = pd.Series(nav, index=cal, name="nav").ffill()
    return s / s.iloc[0], pd.DataFrame(log)


def sleeve_frame(calendar: pd.DatetimeIndex) -> pd.DataFrame:
    """Gold price level and a cash total-return level, on the calendar."""
    dp = defensive_prices()
    gold = dp[GOLD].reindex(calendar.union(dp.index)).ffill().reindex(calendar)
    cash_r = cash_total_return(calendar).fillna(0.0)
    cash = (1.0 + cash_r).cumprod()
    return pd.DataFrame({GOLD: gold, "CASH": cash}, index=calendar)


def new_audit() -> dict:
    return dict.fromkeys([
        "pit_signal_before_entry_ok", "pit_basket_not_future_ok",
        "pit_rank_not_future_ok", "reviews_past_calendar_end",
        "reviews_no_parent_basket", "reviews_no_rank_snapshot",
        "reviews_empty_basket", "reviews_fully_defensive",
        "signal_fallback_rows", "target_rows_no_price",
        "entries_nothing_fillable", "reviews_no_trade",
    ], 0)
