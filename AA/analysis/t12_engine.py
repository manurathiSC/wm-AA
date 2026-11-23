# -*- coding: utf-8 -*-
"""T12 engine: T07's segment holding (each stock follows the signal of its own market-cap band) against a size-matched random exclusion (N4.6, decides)
and a persistent label permutation (N4.8, beside it), on the four REAL parents, 2014-09-01 -> 2019-01-02 (T11's window), before the published NAVs.

A FORK of analysis/t07_engine.py (copied, not imported): the event rule, the tags through the reviewed analysis/tag_lookup.py (unchanged, read only at
events), the two nulls, `sim()`, `stats()`, V2-V7, R5, the comparators and the --rerun CLI are T07's. The window, the D26 calendar, the initial position at
T0, the stand-ins (2017-10-19 stocks, 2016-10-30 GOLDBEES) and the D24b gold-range code are analysis/t11_engine.py's (copied, not imported). Changes against
T07: window 2014-09-01 -> 2019-01-02 on D26; windows `full`, `r2` (from 2015-01-02) and `full_r6` (R6: the two unranked holdings tagged by their other
quote_id); no D17 calendar in the run (kept only for the V4(a) regression, `--calendar d17`), no G0, no live window, no AA-book R6; new R7 (T11's
splice); seeds start with 15; V4 as T12.md section 2; V6 passes at <= 17 of 100. Pre-registration: tests/T12/T12.md sections 1-3 (frozen;
`python tests/T12/check_prereg.py`); evidence contract: tests/T12/logs/evidence_contract.md (amends tests/T07/logs/evidence_contract.md). Every data file is
opened through `approved_data.require()` (an APPROVED row of data/APPROVED_DATA.md), its sha256 prefix is checked, and the Smallcap 100 Master goes through
`approved_data.guard_window`. Readings of the places the frozen text is silent are in READINGS and are written to audit.json.

    python -I analysis/t12_engine.py --run NAME [--draws N] [--quick] [--controls] [--books B1,B2] [--jobs J]          (from AA/)
    python -I analysis/t12_engine.py --rerun --book B --type N4.6|N4.8 --id N --cost C --window full|r2|full_r6 [--cash lbes|liq] --out f.json
    python -I analysis/t12_engine.py --calendar d17 [--books ...] [--run NAME]       (V4(a) only: writes regression_d17.json)

Writes tests/T12/evidence/<run>/. Exit code 0 only if every gate that ran passed. The engine prints gates and counts only, no performance figure.

Trade rule (one function, `sim`): at an event session t, with fill prices (stocks OHLC4, GOLDBEES de-spiked OHLC4, cash at its level), V = value of all
holdings at those prices. Targets: kept stock V*w_i (w_i its listed weight, renormalised), GOLDBEES and cash V*s/2 each, s = (listed weight dropped)/(sum of
listed weights). traded = sum |target - held| over every line; cost = traded*cost_bps/2/1e4; every target is then scaled by (V-cost)/V. T0 is the free
initial position.
"""
from __future__ import annotations

import argparse
import ast
import copy
import json
import math
import os
import sys
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import approved_data as AD  # noqa: E402
from approved_data import NotApprovedError  # noqa: E402
from tag_lookup import TagLookup  # noqa: E402

AA = Path(__file__).resolve().parents[1]
HD = AA / "Historical Data"
HM = AA / "data" / "holdings_matrix"
IDX_DIR = HD / "extended_2026-11-12" / "index_daily_pre2019"
D24B_DIR = HD / "extended_2026-11-12" / "MAUc1_from_2003"
MASTER_DIR = HD / "extended_2026-10-30" / "Master"
D17_DIR = HD / "extended_2026-11-06" / "published_nav"
GOLD_D09 = AA / "analysis" / "cache" / "why_gold_ohlc_eikon_extended_2026-11-04.parquet"
CAL_FILE = IDX_DIR / "nse_trading_days.csv"
T12 = AA / "tests" / "T12"
T07E = AA / "tests" / "T07" / "evidence" / "headline"      # read-only test evidence, V4(a)
T06E = AA / "tests" / "T06" / "evidence" / "headline"      # read-only test evidence, V4(a)
T11E = AA / "tests" / "T11" / "evidence" / "headline"      # read-only test evidence, V4(b) if it exists
T07_ENGINE = Path(__file__).with_name("t07_engine.py")     # source text read by the V4(c) AST comparison only
STEP1 = T12 / "logs" / "step_1_counts.json"

PARENTS = ["SCMO_0003", "SCMO_0007", "SCMO_0010", "SCMO_0029"]
T0 = pd.Timestamp("2014-09-01")                # the first basket effective on or after 2014-07-01, one date for all four parents (asserted)
END = pd.Timestamp("2019-01-02")               # the first date of the published NAVs (T07 starts there)
R2_START = pd.Timestamp("2015-01-02")          # R2 sub-window (T11's R3 start)
END_D17 = pd.Timestamp("2019-12-31")           # V4(a) regression window end (T0 = the book's first D17 date)
FIRST_PRICE_DAY = pd.Timestamp("2014-07-01")   # D18's and D09's first bar
SC_USABLE_FROM = pd.Timestamp("2011-11-25")    # rule 7: D03 Smallcap 100 Master rows
NO_D18_SESSION = pd.Timestamp("2017-10-19")    # Diwali Muhurat evening: in D26, no D18 bar
NO_GOLD_SESSION = pd.Timestamp("2016-10-30")   # Muhurat: in D26, no GOLDBEES bar
COSTS = (0.0, 20.8, 50.0)
PRIMARY = 20.8
N_DRAWS = 2000
N_R5 = 500
R5_RATE = 0.0793
V6_SHIFTS, V6_DRAWS = 100, 200
V6_XMAX_FROZEN = 17                            # T12.md section 2 V6: at most 17 of 100
SEED = 15                                      # first element of every seed (T12.md section 3 steps 11-12)
R7_THRESHOLD = 0.20


def v6_xmax(K: int, p: float = 0.10, alpha: float = 0.05 / 4) -> int:
    """AMENDMENT 2026-11-12 (T07.md 'Amendments before the run'): the largest count X of information-free signals reaching the 90th
    percentile that still passes V6 for K shifts, i.e. the largest X with P(Binomial(K, p) >= X) >= alpha (one-sided, alpha = 0.05 / 4 books).
    K = 100: 17 (a book fails at 18 or more). Replaces the frozen two-sided band 10% +- 2 sqrt(0.1 x 0.9 / K) = [4%, 16%]."""
    tail = 0.0
    for X in range(K, -1, -1):
        tail += math.comb(K, X) * p ** X * (1 - p) ** (K - X)
        if tail >= alpha:
            return X
    return K


DESPIKE_TOL = 0.005
REL_TOL_NAV = 1e-12
SUBSET_TOL = 1e-12                           # tolerance on |sum - D| <= tau (floating point; ties count as allowed)
BANDS = ["Large", "Mid", "Small and below"]
BAND_IDX = {b: i for i, b in enumerate(BANDS)}
SIGNALS = ["Nifty100", "MC100", "SC100"]
RANK_SOURCES = ("rank", "nonmember_rank")
TAG_FILES = dict(rank=HD / "extended_2026-11-17" / "mcap_universe_from_2013-12" / "mcap_rank_panel_from_2013-12.csv",
                 memb=HD / "extended_2026-11-12" / "tags" / "membership_panel.csv",
                 symb=HD / "extended_2026-11-12" / "symbology" / "symbology_changes.csv")
# R6 (T12.md section 2): the two unranked holdings and the quote_id of their other listing.
# "frozen" = the quote_ids T12.md section 2 and the contract list (the default). They are the CURRENT listings (Hexaware relisted 2025, PIRAMALFIN today)
# and have no D23b row before 2025-02-28 / 2025-11-28, so in this window they never rank and R6 as frozen re-tags nothing (READINGS R6b).
# "review" = the old listings the D20b review's table names (Hexaware 55837401060, DHFL 55837400085), which rank Mid in the window. Not used unless
# `--r6-ids review` is given (Manu's decision; see tests/T12/logs/step_2_log.md).
R6_LINK_SETS = {"frozen": {"SCMO_0007": {"INE093A01041": 236783369047},     # Hexaware (HEXT)
                           "SCMO_0010": {"INE202B01038": 236798428431}},    # DHFL (listed as PIRAMALFIN)
                "review": {"SCMO_0007": {"INE093A01041": 55837401060},
                           "SCMO_0010": {"INE202B01038": 55837400085}}}
R6_IDS = "frozen"
R6_LINKS = R6_LINK_SETS[R6_IDS]

READINGS = {
    "E1": "calendar = D26's dates from T0 = 2014-09-01 to END = 2019-01-02 (1,070 sessions, asserted; T11 E1). 2017-10-19 is a D26 session with no D18 bar for any stock: every stock's previous close "
          "(D18 close ffilled over the union of D26 and D18 dates) is its valuation and fill price there (T11's stand-in), counted; any other held stock-session without a bar is treated the same way and counted",
    "E2": "decision dates = T0 and the last D26 session of every later ISO week (228); the decision at END is made but not traded (it has no later session)",
    "E3": "state of a decision = the triple of the latest Master SIGN row of each index dated <= the decision date (BUY/SELL); the Smallcap 100 Master is sliced to rows >= 2011-11-25 on read (rule 7, guard_window); "
          "T06's 'state' (1 iff all three BUY) is kept in decisions.csv",
    "E4": "initial position at T0 (free, T11's E4 with T07's split): the basket in force at T0 (effective 2014-09-01, T0's own availableDate session) at its renormalised weights, bought at the OHLC4 of its first D18 "
          "session on or after its availableDate (T0 itself, so no drift) and scaled to NAV 1.000 at T0's close; the stocks dropped at T0 (tags and state read as of T0 itself) are kept at T0's closes in value and "
          "converted half to GOLDBEES, half to cash units at T0's closes. For the r2 window the basket in force at its T0 (effective 2014-12-01) is drifted from the OHLC4 of its availableDate session to r2's T0 close",
    "E5": "WEIGHTS ARE RENORMALISED TO 1, AS T06 AND T07 DO (T07 E5; T12.md step 6 says so explicitly): listed_weight in event_stocks.csv is the renormalised weight, listed_weight_raw the matrix value; "
          "sum_weights is 1.0 and s = D; tau = half the smallest renormalised weight",
    "E6": "a basket takes effect on the first calendar session on or after its availableDate (D19's index = D05's non-skipped availableDate, asserted for T0..END); skipped baskets are dropped (none in the window)",
    "E7": "stock fill = OHLC4 of the Eikon bar (close if any of open/high/low is blank; the previous close if the stock has no bar that session), Polyplex correction applied (constant in this window)",
    "E8": "cash level: the extended LBES (D11) as-of on sessions; asserted to cover the window (0 accrued sessions). R3 'liq' = liquidEtfFinal (LIQUIDCASE) as-of over the whole window (T07's 2024-01-24 splice "
          "date lies after the window, so the cash leg is LIQUIDCASE throughout; T11 E9)",
    "E9": "GOLDBEES fill: OHLC4 with open/high/low clipped to MCX gold's range that day + 0.5% of the close, the range from D24b's daily file (mauc1_daily_clean_extended.csv); a session with a GOLDBEES bar and no MCX "
          "range is filled at the raw OHLC4 (counted); 2016-10-30 has no GOLDBEES bar: the previous close is its valuation AND fill (T11 E8), counted. Book.gold_raw (read by T07's unchanged sim) marks the no-range sessions",
    "EV1": "event rule (step 4, T07 EV1 unchanged): candidates are the trade sessions of decisions j>=1 (decision_idx+1, if the session exists) and the sessions of non-skipped basket changes. At a decision candidate "
           "the set the CURRENT tags (those read at the last event) would drop under that decision's state is compared with the set the book currently drops; a difference makes a signal event. A basket candidate "
           "without a signal event is an event unless the book holds no stock (every held stock currently dropped); then nothing is traded. Two events on one session are one event ('signal+basket'). At an event "
           "the state is the triple of the latest decision made before the session, the tags of every held stock are read as of the previous D26 session (info date). The T0 event reads tags and state at T0 "
           "itself (T12.md step 4(i)), counted apart in audit.json v2",
    "EV2": "SKIPPED BASKET EVENT (no stock held; T07 EV2): nothing is traded and no event is written, but the basket in force changes; the tags of the new basket's stocks are read as of the previous session "
           "(a tag read without a trade, counted in V2 and in R5's random stream) and become the 'current tags'; the book 'currently drops' all of them. Listed in audit.json (skipped_basket_events)",
    "EV3": "the whole-book switch (bands tied) is the same event code with every stock following 'IN iff all three BUY'; its events equal T06's/T11's (a trade only when the stock share changes, basket events only "
           "while IN). hold the parent = mode 'parent' (nothing dropped, T0 and basket events only); the 100% sleeve = T0 with everything dropped",
    "N1": "N4.6: held stocks of an event in increasing ISIN string order (bit i of a subset mask = stock i); allowed set = masks with |sum w - D| <= tau (+1e-12; exact ties allowed), listed in increasing mask "
          "order; u = rng.random() from default_rng([15, 7, draw_id, book_no]), one per event in event order (T0 event first), index = min(floor(u*count), count-1); the same draw ids at every cost, cash and "
          "window (r2 and full_r6 have their own event lists and use the same seeds)",
    "N1b": "allowed sets are homogeneous in the weights, so renormalisation does not change any set; exact ties |sum - D| = tau are allowed (1e-12 tolerance) and counted per event (count_table.json "
           "boundary_cases). ISIN order = Python string order",
    "N2": "N4.8: one score per ISIN of the realisation's universe (the sorted ISINs of its event_stocks rows; r2 has its own) from default_rng([15, 8, draw_id, book_no]).random(n); at an event the held stocks are "
          "ranked by score DESCENDING, the first n_L get label Large, the next n_M Mid, the rest Small and below (n_* = the rule's counts); dropped iff the label's band signal is SELL. Not run on full_r6 (contract)",
    "R5": "R5 tag error: default_rng([15, 5, draw_id, book_no]); at every tag read (every event and every skipped-basket read) each held stock whose tag source is 'rank' or 'nonmember_rank' consumes two "
          "uniforms: the first < 0.0793 flips its band, the second picks one of the other two bands (order Large, Mid, Small; first if < 0.5). Unranked tags are not perturbed. Events are rebuilt under the "
          "perturbed tags. Reported: the draw's after-cost CAGR (20.8 bps, full window) minus the whole-book switch's",
    "R6": "R6: in the window full_r6 (books SCMO_0007 and SCMO_0010 only) a tag read of Hexaware (INE093A01041) or DHFL (INE202B01038) whose source under tag_lookup is 'unranked' is replaced by the rank and band "
          "of the linked quote_id (236783369047 / 236798428431) on THE SAME snapshot tag_lookup used (the latest D23b rank snapshot on or before the information date), read from the D23b panel through "
          "TagLookup's own snapshot table (its `_rank_snapshot`, called, not modified); source 'rank_linked', via 'r6_link'. Reads where the stock is ranked are left alone ('instead of Small and below'); if the "
          "linked quote_id is not on that snapshot the tag stays unranked (counted). full_r6 has its own events and own N4.6 draws (same seeds); its stats are 'segment' and 'whole_book' at 20.8 bps, LBES",
    "R6b": "FROZEN TEXT INCONSISTENT WITH THE DATA (reported, not resolved by the engine): T12.md section 2 R6 says the two holdings 'rank Mid under their other quote_ids' and names 236783369047 (Hexaware) "
           "and 236798428431 (DHFL). Those are today's listings: in D23b they have rows only from 2025-02-28 (Hexaware, relisted 2025) and 2025-11-28 (PIRAMALFIN), so on every snapshot of the window the "
           "linked quote_id is absent and R6 as frozen re-tags nothing (full_r6 equals full; r6_links.csv is empty; misses counted in audit.json). The D20b review's table names the old listings "
           "(Hexaware 55837401060 / INE093A01033, DHFL 55837400085 / INE202B01012), which rank Mid in the window. The engine runs the frozen ids by default and the review ids only with "
           "`--r6-ids review`; which one R6 uses is Manu's decision",
    "R7": "R7 (T11 E12): a stock-day (i, t), t = 1..T-1 of the full window, is listed iff the ffilled D18 close (Polyplex correction applied) moves |close[t]/close[t-1]-1| >= 0.20 and the stock has weight > 0 in "
          "the basket in force on session t-1 or t; 'return set to zero' = return-preserving splice (every later price of that stock, closes and OHLC4 fills, multiplied by close[t-1]/close[t]); the rule and the "
          "whole-book switch are re-run on the spliced prices with their own (unchanged) event lists, since events read no price; stats and NAVs at 0 and 20.8 bps, full window, LBES",
    "V6": "V6: the weekly joint state matrix (decisions x 3) is rolled by k decisions, k drawn without replacement (100) from the DISTINCT circular shifts 26 <= k <= n-26 with default_rng([15, 9, 100000, book_no]); "
          "shift number i (0-based) uses default_rng([15, 9, i, book_no]) for its null: one stream, draw d takes the next n_events uniforms. Full window, LBES, 20.8 bps, 200 draws; pass iff n_pass90 <= 17 "
          "(T12.md section 2; equals T07's amended one-sided rule v6_xmax(100), asserted)",
    "V7": "V7 oracle: at each event pick, from that event's allowed N4.6 set, the subset with the lowest sum of listed weight x log(end/start), start = OHLC4 at the trade session (T0: the close), end = OHLC4 at the "
          "next event's trade session (the last event: the close of the last session); ties to the lowest mask. 20.8 bps, full window; percentile against the run's N4.6 draws at 20.8",
    "S1": "constant mix: f = the average over all sessions of (value of stocks / NAV) of the rule's path at the SAME cost; stocks f x w_i, half of (1-f) in GOLDBEES and half in cash, rebalanced at the rule's events",
    "S2": "invested_weeks = sum over the weekly decisions of the share of listed weight the current tags keep under that decision's state; constant mix J*f; sleeve100 0; parent J",
    "S4": "stats.events = the number of events including T0; trades = the number of trades after T0 (every event after T0 trades)",
    "V2": "V2 counts: decisions (Master label date <= decision date), tags (snapshot <= info date), events (info date < trade session and latest decision < trade session), decision trade dates after decision dates. "
          "The T0 event reads as of T0 itself and is counted separately, not as a violation",
    "V4": "V4(a): `--calendar d17` = each book's own D17 dates, T0 = its first (SCMO_0007 2019-01-04), end 2019-12-31, every input cut at 2019-12-31, the decision at 2019-12-31 not traded; the engine's rule, "
          "whole-book, parent and 100%-sleeve NAVs at 0/20.8/50 bps against T07's stored segment, whole_book, parent, sleeve100 and the whole-book, parent and sleeve against T06's stored strategy, hold_parent, "
          "sleeve_only on EVERY session of that slice (dates_compared == sessions), relative 1e-12; decisions (sign triple, decision_idx) against T07's decisions.csv. The stored runs read D23 and D12 where this "
          "engine reads D23b and D24b. V4(b): only if tests/T11/evidence/headline/ exists when the run starts: whole_book vs T11's strategy_fixed50 and parent vs T11's hold_parent on the full window at each "
          "cost present, relative 1e-12; else 'not run'. V4(c): AST comparison (functions and classes, docstrings included) with t07_engine.py: the required-identical list must be identical and every changed "
          "name must be in the expected list. V4(d): every tag of every event row (all windows) against a direct pandas read of the D23b panel and D22 (latest snapshot <= info date, by ISIN, else by a quote_id "
          "linked through D22 isin/new_isin or the panel's own isin-quote_id pairs), comparing band, rank, snapshot and source; 0 mismatches",
    "G1": "reportability: a (book, window) needs >= 5 separate disagreement stretches (runs of decisions where the three SIGN are neither all BUY nor all SELL) and >= 6 events with 0 < n_dropped < n_held; "
          "written to audit.json and count_table.json. Draws are run for every realisation whether reportable or not",
    "G2": "events.csv, event_stocks.csv, count_table.json are written for the rule at the full, r2 and full_r6 windows; costs do not change events",
    "G3": "the oracle (V7), V6 and R5 are run per book inside its worker; V6 does not depend on --draws; a run without --controls (--quick) reports V6 and V7 as not run and exits 0 if V2-V5 pass",
    "C1": "event counts: the engine's events (T0 included) are compared with Step 1's coarse upper bound (events_coarse_upper_bound) and its events in disagreement weeks (after T0) with events_in_mixed_weeks",
    "T1": "event_stocks.csv tag_n_ranked = n_ranked of the snapshot the tag used (read from the panel's n_ranked column through TagLookup's snapshot groups); empty for an unranked read with no snapshot",
    "ST": "stand-ins are counted in audit.json standins: held stock-sessions priced by a previous close, the sessions concerned, GOLDBEES sessions without a bar and without an MCX range, and the number of event "
          "sessions of every realisation (rule, comparators, r2, full_r6, R5 and V6 rebuilds included) that fall on any of them; trades of the recorded runs priced by a stand-in come from sim's own counters",
}

# ── approved raw inputs ───────────────────────────────────────────────────────
USED: dict[str, dict] = {}
CHECK_SHA = True


def ap(path) -> Path:
    """The only way the engine opens a data file: APPROVED row required, sha256 prefix checked once per file (main process)."""
    p = AD.require(path)
    rel = p.relative_to(AA).as_posix()
    if rel not in USED:
        if CHECK_SHA:
            USED[rel] = AD.check_sha(p)
        else:
            r = AD.row_for(p)
            USED[rel] = {"file": rel, "approved_row": "APPROVED " + r["id"], "id": r["id"], "through": r["through"], "bytes": p.stat().st_size, "sha256": "",
                         "usable_from": AD.usable_from(p)}
    return p


_COMMON: dict = {}


def common(end: pd.Timestamp = END) -> dict:
    """Calendar (D26), the three D03 Master files, GOLDBEES (D09) with the D24b de-spike, cash (D11); everything cut at `end`."""
    key = pd.Timestamp(end)
    if key in _COMMON:
        return _COMMON[key]
    cal_all = pd.DatetimeIndex(sorted(pd.to_datetime(pd.read_csv(ap(CAL_FILE))["date"])))
    assert cal_all.is_unique and cal_all.max() >= min(key, END), f"D26 ends {cal_all.max().date()} before {key.date()}"
    ms = {}
    for n in SIGNALS:
        p = ap(MASTER_DIR / f"Master_{n}.xlsx")
        if n == "SC100":
            AD.guard_window(p, SC_USABLE_FROM)
        d = pd.read_excel(p, parse_dates=["Date"])
        s = d.dropna(subset=["SIGN"]).set_index("Date")["SIGN"].sort_index()
        s = s[~s.index.duplicated(keep="last")]
        assert s.index.max() >= key, f"{n}: Master ends {s.index.max().date()} before {key.date()}"
        s = s[s.index <= key]
        if n == "SC100":
            s = s[s.index >= SC_USABLE_FROM]                   # rule 7: nothing before the usable-from date is kept
        assert set(s.unique()) <= {"BUY", "SELL"}, f"Master_{n}: unexpected SIGN values {set(s.unique())}"
        ms[n] = s
    m = pd.read_csv(ap(D24B_DIR / "mauc1_daily_clean_extended.csv"), index_col=0, parse_dates=True)
    m.columns = [c.strip().lower() for c in m.columns]
    g = pd.read_parquet(ap(GOLD_D09))
    g["date"] = pd.to_datetime(g["date"])
    g = g.set_index("date").sort_index()
    g = g[~g.index.duplicated(keep="last")]
    assert g.index.min() <= FIRST_PRICE_DAY and g.index.max() >= key
    rng = ((m["high"] - m["low"]) / m["close"]).reindex(g.index)
    band = rng + DESPIKE_TOL
    lo, hi = g["close"] * (1 - band), g["close"] * (1 + band)
    has = rng.notna()
    o = g["open"].where(~has, g["open"].clip(lower=lo, upper=hi))
    h = g["high"].where(~has, g["high"].clip(upper=hi))
    l_ = g["low"].where(~has, g["low"].clip(lower=lo))
    h = np.maximum(h, np.maximum(o, g["close"]))
    l_ = np.minimum(l_, np.minimum(o, g["close"]))
    gfill = (o + h + l_ + g["close"]) / 4
    norange = pd.DatetimeIndex(g.index[~has.values])
    lb = pd.read_csv(ap(HD / "LBES_Adjusted_Price_data_extended_2026-11-05.csv"))
    lb["date"] = pd.to_datetime(lb["date"], format="%d/%m/%y %H:%M")
    lb = lb.set_index("date")["price"].sort_index()
    lq = pd.read_csv(ap(HD / "liquidEtfFinal_extended_2026-11-05.csv"))
    lq["date"] = pd.to_datetime(lq["date"], format="mixed", dayfirst=True)
    lq = lq.set_index("date")["liquid_case"].sort_index()
    assert lb.index.max() >= key and lq.index.max() >= key
    _COMMON[key] = dict(cal_all=cal_all, master=ms, gclose=g["close"][g.index <= key], gfill=gfill[gfill.index <= key], norange=norange[norange <= key],
                        lbes=lb[lb.index <= key], liq=lq[lq.index <= key], lbes_last=lb.index.max(), liq_last=lq.index.max(), gold_last=g.index.max(),
                        mcx_last=m.index.max(), gold_first=g.index.min())
    return _COMMON[key]


def read_pub(p: str, end: pd.Timestamp) -> pd.Series:
    """D17 (extended published NAV), cut at `end`. Used for the V4(a) calendar only."""
    n = pd.read_csv(ap(D17_DIR / f"{p}.csv"))
    assert (n["_id.scid"] == p).all()
    pub = pd.Series(n["index"].values, index=pd.to_datetime(n["_id.date"], format="%Y/%m/%d")).sort_index()
    assert not pub.index.duplicated().any() and pub.index.max() >= end
    return pub[pub.index <= end]


_RAW: dict = {}


def raw_parent(p: str, end: pd.Timestamp = END) -> dict:
    """Stock prices (D18 with the price corrections, cut at `end`), baskets (D19, skipped dropped, renormalised), ISINs (D19 columns), D05 availableDates."""
    key = (p, pd.Timestamp(end))
    if key in _RAW:
        return _RAW[key]
    wm = pd.read_csv(ap(HM / f"{p}_holding_weight_matrix.csv"), index_col=0)
    wm.index = pd.to_datetime(wm.index)
    src = pd.read_csv(ap(HM / f"{p}_holding_weight_sources.csv"))
    src["rebalance_date"] = pd.to_datetime(src["rebalance_date"])
    skipped = set(src.loc[src["source"] == "csv_only_skipped", "rebalance_date"])
    wm = wm[~wm.index.isin(skipped)]
    wraw = wm.copy()
    wm = wm.div(wm.sum(axis=1), axis=0)
    stocks = list(wm.columns)
    cm = pd.read_csv(ap(HM / f"{p}_columns.csv")).set_index("stock")["ISIN"]
    assert set(stocks) <= set(cm.index) and cm.loc[stocks].notna().all() and not cm.loc[stocks].duplicated().any(), f"{p}: ISIN map incomplete"
    isin = np.array([cm.loc[s] for s in stocks], dtype=object)
    h = pd.read_csv(ap(HD / "frozen_2026-09-25" / "Rebalance_history" / f"Rebalance_history_by_scid_{p}.csv"), usecols=["skipped", "date", "availableDate"]).drop_duplicates(["date"])
    h["eff"] = pd.to_datetime(h["availableDate"], format="%d/%m/%y %H:%M").dt.normalize()
    d05 = pd.DatetimeIndex(sorted(h.loc[h["skipped"].astype(str).str.lower() != "true", "eff"].unique()))
    o = pd.read_csv(ap(HM / f"{p}_ohlc.csv"), parse_dates=["date"]).drop_duplicates(["date", "stock"])
    assert o["date"].max() >= end, f"{p}: D18 ends {o['date'].max().date()} before {pd.Timestamp(end).date()}"
    o = o[o["date"] <= end]                                    # nothing after the window's end is used
    piv = {f: o.pivot(index="date", columns="stock", values=f).sort_index().reindex(columns=stocks) for f in ("open", "high", "low", "close")}
    cor = pd.read_csv(ap(HM / "price_corrections.csv"), parse_dates=["ex_date"])
    for r in cor.itertuples():
        if p in r.applies_to.split(";") and r.stock in stocks:
            for f in piv:
                piv[f].loc[piv[f].index < r.ex_date, r.stock] *= r.factor
    close_raw = piv["close"]
    o4 = ((piv["open"] + piv["high"] + piv["low"] + piv["close"]) / 4).fillna(close_raw)       # NaN only where the stock has no bar that session
    _RAW[key] = dict(W=wm, Wraw=wraw, stocks=stocks, isin=isin, close_raw=close_raw, o4=o4, skipped=sorted(skipped), d05=d05, d18_dates=close_raw.index, d18_last=o["date"].max())
    return _RAW[key]


def cash_levels(cal: pd.DatetimeIndex, kind: str = "lbes", end: pd.Timestamp = END) -> tuple[np.ndarray, dict]:
    """E8. Level on every session of cal (as-of); nothing is accrued past a file's end."""
    c = common(end)
    ser = c["lbes"] if kind == "lbes" else c["liq"]
    last_file = c["lbes_last"] if kind == "lbes" else c["liq_last"]
    assert not (cal > last_file).any(), f"cash file ends {last_file.date()} before the window's last session: stop and ask Manu"
    lv = ser.reindex(ser.index.union(cal)).ffill().reindex(cal)
    assert lv.notna().all()
    return lv.values.astype(float), {"file_last": str(last_file.date()), "accrued_sessions": 0, "cash": kind}


class Book:
    """Everything a run needs for one parent and one window, as plain arrays on the calendar. calendar 'd26' = the test's; 'd17' = the V4(a) regression's (D17 dates)."""

    def __init__(self, parent: str, start: pd.Timestamp | None = None, end: pd.Timestamp = END, cash: str = "lbes", calendar: str = "d26"):
        r = raw_parent(parent, end)
        c = common(end)
        if calendar == "d26":
            cal_all = c["cal_all"]
            t0 = T0 if start is None else cal_all[cal_all.searchsorted(start)]
            assert t0 in cal_all
        else:
            assert calendar == "d17"
            cal_all = read_pub(parent, end).index
            t0 = cal_all[0] if start is None else cal_all[cal_all.searchsorted(start)]
        cal = cal_all[(cal_all >= t0) & (cal_all <= end)]
        assert cal[0] == t0 and cal[-1] == end, (cal[0], cal[-1], end)
        self.parent, self.cal, self.T, self.t0, self.calendar, self.end, self.cash = parent, cal, len(cal), t0, calendar, pd.Timestamp(end), cash
        self.stocks, self.N = r["stocks"], len(r["stocks"])
        self.isin = r["isin"]
        union = cal.union(r["close_raw"].index)
        Cf = r["close_raw"].reindex(union).ffill().reindex(cal)       # the previous close stands in on a session without a bar (E1, E7)
        P = r["o4"].reindex(cal)
        self.nobar = P.isna().values                                  # stock has no bar that session
        P = P.fillna(Cf)
        self.C = np.nan_to_num(Cf.values.astype(float), nan=0.0)
        self.P = np.nan_to_num(P.values.astype(float), nan=0.0)
        gunion = cal.union(c["gclose"].index)
        gc = c["gclose"].reindex(gunion).ffill().reindex(cal)
        assert gc.notna().all()
        gf = c["gfill"].reindex(cal).fillna(gc)                       # no GOLDBEES bar that session: the previous close is the fill too (E9)
        self.g, self.gf = gc.values.astype(float), gf.values.astype(float)
        own = cal.isin(c["gclose"].index)
        self.gold_nobar = ~np.asarray(own)
        self.gold_norange = np.asarray(cal.isin(c["norange"]))        # GOLDBEES bar but no MCX range: raw OHLC4 fill
        self.gold_raw = self.gold_norange                             # the flag T07's sim records per trade
        self.L, self.cash_info = cash_levels(cal, cash, end)
        W = r["W"]
        self.W = W.values.astype(float)
        self.Wraw = r["Wraw"].values.astype(float)
        self.eff = W.index
        bidx = np.searchsorted(cal.values, self.eff.values)          # first session on or after availableDate
        self.bidx = bidx
        self.b0 = int(np.flatnonzero(bidx <= 0)[-1])                 # basket in force at T0 (E4/E6)
        self.basket_events = {int(i) for i in bidx if 0 < i < self.T}
        self.basket_at = np.array([int(np.flatnonzero(bidx <= t)[-1]) if (bidx <= t).any() else 0 for t in range(self.T)])
        ax = r["d18_dates"]
        s0 = ax[ax.searchsorted(self.eff[self.b0])]
        w = self.W[self.b0]
        nzs = np.flatnonzero(w > 0)
        p = r["o4"].loc[s0].values[nzs]
        p = np.where(np.isnan(p), r["close_raw"].ffill().loc[s0].values[nzs], p)
        u = np.zeros(self.N)
        u[nzs] = w[nzs] / p
        v0 = float((u * self.C[0]).sum())
        self.u0 = u / v0
        self.initial_basket_switch_session = str(s0.date())
        self._held: dict = {}

    def held(self, b: int) -> np.ndarray:
        """Columns with listed weight > 0 in basket b, in increasing ISIN string order (the order of the subset bits)."""
        if b not in self._held:
            cols = np.flatnonzero(self.W[b] > 0)
            self._held[b] = cols[np.argsort(self.isin[cols], kind="stable")]
        return self._held[b]

    def decisions(self) -> tuple[pd.DataFrame, np.ndarray, np.ndarray]:
        """T06's decision table plus the state matrix S (decisions x 3, 1 = BUY, columns Nifty100, MC100, SC100) and decision_idx."""
        cal = self.cal
        iso = cal.isocalendar()
        last = pd.Series(np.arange(self.T), index=cal).groupby([iso.year.values, iso.week.values]).max().values
        idx = np.array([0] + [int(i) for i in sorted(last) if i > 0])
        ms = common(self.end)["master"]
        rows, S = [], []
        for j, i in enumerate(idx):
            d = cal[i]
            lab, state, trip = {}, 1, []
            for n in SIGNALS:
                s = ms[n]
                k = s.index.searchsorted(d, side="right") - 1
                assert k >= 0, f"{n}: no Master row on or before {d.date()}"
                lab[n] = (s.index[k], s.iloc[k])
                state &= int(s.iloc[k] == "BUY")
                trip.append(int(s.iloc[k] == "BUY"))
            S.append(trip)
            ld = max(v[0] for v in lab.values())
            rows.append({"book": self.parent, "j": j, "decision_date": d.date(), "decision_idx": int(i),
                         "trade_date": (cal[i + 1].date() if i + 1 < self.T else None),
                         **{f"sign_{n}": v[1] for n, v in lab.items()}, **{f"label_{n}": v[0].date() for n, v in lab.items()},
                         "latest_label": ld.date(), "label_age_days": (d - min(v[0] for v in lab.values())).days,
                         "all_three_buy": bool(state), "state": int(state),
                         "disagree": bool(0 < sum(trip) < 3), "pattern": "".join("B" if x else "S" for x in trip)})
        return pd.DataFrame(rows), np.array(S, dtype=np.int8), idx


# ── tags ──────────────────────────────────────────────────────────────────────
_TL: dict = {}


def load_taglookup() -> TagLookup:
    if "tl" not in _TL:
        _TL["tl"] = TagLookup.from_files(ap(TAG_FILES["rank"]), ap(TAG_FILES["memb"]), ap(TAG_FILES["symb"]))
        tl = _TL["tl"]
        assert tl.cutoff is not None and tl.cutoff > END_D17, f"membership cutoff {tl.cutoff} inside the window: every tag must be a rank tag"
        _TL["n_ranked"] = {d: int(g["n_ranked"].iloc[0]) for d, g in tl._rank_by_date.items()}
    return _TL["tl"]


class Tagger:
    """Tags through the reviewed tag_lookup.TagLookup (never our own ranking), cached by (isin, date). links (R6 only): isin -> the quote_id whose rank
    replaces an 'unranked' read on the same snapshot (READINGS R6)."""

    def __init__(self, links: dict | None = None):
        self.tl = load_taglookup()
        self.nr = _TL["n_ranked"]
        self.links = dict(links or {})
        self.cache: dict = {}
        self.linked_missing = 0

    def get(self, isin: str, d: pd.Timestamp) -> dict:
        k = (isin, d)
        r = self.cache.get(k)
        if r is None:
            r = dict(self.tl.tag(isin, d))
            if isin in self.links and r["source"] == "unranked" and r["snapshot"] is not None:
                by_q, _ = self.tl._rank_snapshot(pd.Timestamp(r["snapshot"]))
                q = self.links[isin]
                if q in by_q:
                    rank, band = by_q[q]
                    r = {"band": band, "source": "rank_linked", "snapshot": r["snapshot"], "detail": int(rank), "via": "r6_link", "linked_quote_id": q}
                else:
                    self.linked_missing += 1
            r["n_ranked"] = self.nr.get(pd.Timestamp(r["snapshot"])) if r["snapshot"] is not None else None
            self.cache[k] = r
        return r


class Perturb:
    """R5: the tag-error draw (READINGS R5)."""

    def __init__(self, draw_id: int, book_no: int, rate: float = R5_RATE):
        self.rng = np.random.default_rng([SEED, 5, draw_id, book_no])
        self.rate = rate
        self.flipped = 0
        self.rank_reads = 0

    def apply(self, bands: np.ndarray, src: list[str]) -> np.ndarray:
        out = bands.copy()
        for i, s in enumerate(src):
            if s in RANK_SOURCES:
                u1, u2 = self.rng.random(), self.rng.random()
                self.rank_reads += 1
                if u1 < self.rate:
                    others = [b for b in (0, 1, 2) if b != int(out[i])]
                    out[i] = others[0 if u2 < 0.5 else 1]
                    self.flipped += 1
        return out


# ── events (T07.md section 3 step 4-6, unchanged) ────────────────────────────
def dropped_of(mode: str, bands: np.ndarray, st: np.ndarray) -> np.ndarray:
    if mode == "seg":
        return st[bands] == 0
    if mode == "whole":
        return np.full(len(bands), not bool(st.all()))
    return np.zeros(len(bands), dtype=bool)


class Events:
    def __init__(self, evs: list, skipped: list, kept_share: np.ndarray, v2: dict, mode: str):
        self.evs, self.skipped, self.kept_share, self.v2, self.mode = evs, skipped, kept_share, v2, mode
        self.n = len(evs)
        self.off = np.concatenate([[0], np.cumsum([len(e["cols"]) for e in evs])]).astype(int)
        self.R = int(self.off[-1])
        self.dflat = np.concatenate([e["drop"] for e in evs]).astype(np.uint8)
        self.w_flat = np.concatenate([e["w"] for e in evs])
        self.universe = None
        self.allowed_done = False

    def counts(self) -> dict:
        kinds = [e["kind"] for e in self.evs]
        return {"events": self.n, **{k: kinds.count(k) for k in ("initial", "signal", "basket", "signal+basket")},
                "partial": int(sum(1 for e in self.evs if 0 < e["drop"].sum() < len(e["drop"])))}


def build_events(bk: Book, dec_idx: np.ndarray, S: np.ndarray, mode: str, tagger: Tagger | None = None, perturb: Perturb | None = None,
                 keep_tags: bool = False) -> Events:
    """The event list of one realisation. mode: 'seg' (each stock follows its band), 'whole' (every stock follows IN iff all three BUY), 'parent' (nothing dropped)."""
    T, J = bk.T, len(dec_idx)
    v2 = {"tags_checked": 0, "tag_snapshot_after_info": 0, "events_checked": 0, "event_info_not_before_trade": 0, "event_decision_not_before_trade": 0,
          "initial_position_tag_reads_asof_T0": 0}
    skipped: list = []

    def read(cols: np.ndarray, info_idx: int, initial: bool):
        n = len(cols)
        if mode != "seg":
            return np.zeros(n, dtype=np.int8), ["na"] * n, [None] * n
        d = bk.cal[info_idx]
        tags = [tagger.get(bk.isin[c], d) for c in cols]
        bands = np.array([BAND_IDX[t["band"]] for t in tags], dtype=np.int8)
        src = [t["source"] for t in tags]
        for t in tags:
            if initial:
                v2["initial_position_tag_reads_asof_T0"] += 1
            else:
                v2["tags_checked"] += 1
            if t["snapshot"] is not None and pd.Timestamp(t["snapshot"]) > d:
                v2["tag_snapshot_after_info"] += 1
        if perturb is not None:
            bands = perturb.apply(bands, src)
        return bands, src, tags

    def make(k: int, kind: str, s: int, info_idx: int, jst: int, b: int, cols, bands, src, tags) -> dict:
        w = bk.W[b][cols]
        drop = dropped_of(mode, bands, S[jst])
        return {"k": k, "kind": kind, "t": s, "info_idx": info_idx, "jst": jst, "b": b, "cols": cols, "w": w, "wraw": bk.Wraw[b][cols],
                "bands": bands, "src": src, "tags": tags if keep_tags else None, "drop": drop, "state": tuple(int(x) for x in S[jst])}

    cols0 = bk.held(bk.b0)
    bands0, src0, tags0 = read(cols0, 0, True)
    evs = [make(0, "initial", 0, 0, 0, bk.b0, cols0, bands0, src0, tags0)]
    cur_b, cur_cols, cur_bands, cur_drop = bk.b0, cols0, bands0, evs[0]["drop"]
    kept_share = np.full(J, np.nan)
    sig_at = {int(dec_idx[j]) + 1: j for j in range(1, J) if int(dec_idx[j]) + 1 < T}
    wcur = bk.W[cur_b][cur_cols]
    kept_share[0] = float(wcur[~cur_drop].sum() / wcur.sum())
    for s in sorted(set(sig_at) | bk.basket_events):
        j = sig_at.get(s)
        isb = s in bk.basket_events
        trig = False
        if j is not None:
            dn = dropped_of(mode, cur_bands, S[j])
            wc = bk.W[cur_b][cur_cols]
            kept_share[j] = float(wc[~dn].sum() / wc.sum())
            trig = mode != "parent" and not np.array_equal(dn, cur_drop)
        if not trig and not isb:
            continue
        b = int(bk.basket_at[s])
        cols = bk.held(b)
        if not trig and cur_drop.all():
            # a basket change while the book holds no stock: nothing is traded and no event is written (EV2); the new basket becomes the
            # one the next signal test looks at, its tags read as of the previous session, everything in it 'currently dropped'
            bands, src, tags = read(cols, s - 1, False)
            skipped.append({"session": s, "date": str(bk.cal[s].date()), "basket_eff": str(bk.eff[b].date()), "n_held_new_basket": int(len(cols))})
            cur_b, cur_cols, cur_bands, cur_drop = b, cols, bands, np.ones(len(cols), dtype=bool)
            continue
        jst = int(np.searchsorted(dec_idx, s - 1, side="right") - 1)
        bands, src, tags = read(cols, s - 1, False)
        kind = "signal+basket" if (trig and isb) else ("signal" if trig else "basket")
        ev = make(len(evs), kind, s, s - 1, jst, b, cols, bands, src, tags)
        v2["events_checked"] += 1
        v2["event_info_not_before_trade"] += int(not (ev["info_idx"] < s))
        v2["event_decision_not_before_trade"] += int(not (int(dec_idx[jst]) < s))
        evs.append(ev)
        cur_b, cur_cols, cur_bands, cur_drop = b, cols, bands, ev["drop"]
    # decisions without a candidate session (the last one has no later session): the share the current tags keep
    for j in range(J):
        if np.isnan(kept_share[j]):
            dn = dropped_of(mode, cur_bands, S[j])
            wc = bk.W[cur_b][cur_cols]
            kept_share[j] = float(wc[~dn].sum() / wc.sum())
    return Events(evs, skipped, kept_share, v2, mode)


# ── subsets and nulls ─────────────────────────────────────────────────────────
_BITS: dict = {}


def bits_matrix(n: int) -> np.ndarray:
    """(2^n, n) uint8: row m, column i = bit i of m."""
    if n not in _BITS:
        _BITS[n] = ((np.arange(1 << n)[:, None] >> np.arange(n)) & 1).astype(np.uint8)
    return _BITS[n]


def subset_sums(w: np.ndarray) -> np.ndarray:
    """Sum of w over every subset, indexed by bitmask (bit i = w[i]); built by doubling."""
    s = np.zeros(1)
    for x in w:
        s = np.concatenate([s, s + x])
    return s


_ACACHE: dict = {}


def prepare_allowed(E: Events, strict: bool = True) -> None:
    """For every event: D, tau, the allowed masks A (increasing), their bits, count. Asserts the rule's own set is in A."""
    if E.allowed_done:
        return
    for ev in E.evs:
        w, drop = ev["w"], ev["drop"]
        n = len(w)
        assert 1 <= n <= 16, f"{n} held stocks at an event: N4.6 enumerates at most 16"
        key = (w.tobytes(), drop.tobytes())
        if key not in _ACACHE:
            D = float(w[drop].sum())
            tau = 0.5 * float(w.min())
            sums = subset_sums(w)
            diff = np.abs(sums - D)
            A = np.flatnonzero(diff <= tau + SUBSET_TOL).astype(np.int64)
            boundary = int((np.abs(diff - tau) < 1e-9).sum())
            rule_mask = int((drop.astype(np.int64) << np.arange(n)).sum())
            assert rule_mask in set(A.tolist()), "the rule's own drop set is outside its allowed set"
            _ACACHE[key] = (D, tau, A, bits_matrix(n)[A], boundary)
        D, tau, A, Ab, boundary = _ACACHE[key]
        ev["D"], ev["tau"], ev["A"], ev["Abits"], ev["nA"], ev["boundary"] = D, tau, A, Ab, int(len(A)), boundary
    E.allowed_done = True


def pick_index(u: np.ndarray, count: int) -> np.ndarray:
    """floor(u * count), clamped to count-1 (u < 1 so the clamp only guards floating-point rounding)."""
    return np.minimum((np.asarray(u) * count).astype(np.int64), count - 1)


def draws_n46(E: Events, book_no: int, ids) -> np.ndarray:
    """(len(ids), R) uint8 drops of the N4.6 draws; one uniform per event in event order from default_rng([15, 7, id, book_no])."""
    prepare_allowed(E)
    U = np.array([np.random.default_rng([SEED, 7, int(i), book_no]).random(E.n) for i in ids])
    out = np.zeros((len(ids), E.R), dtype=np.uint8)
    for k, ev in enumerate(E.evs):
        out[:, E.off[k]:E.off[k + 1]] = ev["Abits"][pick_index(U[:, k], ev["nA"])]
    return out


def draws_n48(E: Events, book_no: int, ids, isin_of_col: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(drops, labels), both (len(ids), R) uint8. One score per ISIN of the universe (default_rng([15, 8, id, book_no])), labels by descending score with the rule's counts per band."""
    uni = sorted({str(isin_of_col[c]) for ev in E.evs for c in ev["cols"]})
    pos = {x: i for i, x in enumerate(uni)}
    Sc = np.array([np.random.default_rng([SEED, 8, int(i), book_no]).random(len(uni)) for i in ids])
    drops = np.zeros((len(ids), E.R), dtype=np.uint8)
    labels = np.zeros((len(ids), E.R), dtype=np.uint8)
    for k, ev in enumerate(E.evs):
        ui = np.array([pos[str(isin_of_col[c])] for c in ev["cols"]])
        sub = Sc[:, ui]
        order = np.argsort(-sub, axis=1, kind="stable")
        rank = np.argsort(order, axis=1, kind="stable")
        nL, nM = int((ev["bands"] == 0).sum()), int((ev["bands"] == 1).sum())
        lab = np.where(rank < nL, 0, np.where(rank < nL + nM, 1, 2)).astype(np.uint8)
        off = (np.array(ev["state"]) == 0)                       # label's band signal is SELL
        labels[:, E.off[k]:E.off[k + 1]] = lab
        drops[:, E.off[k]:E.off[k + 1]] = off[lab].astype(np.uint8)
    E.universe = uni
    return drops, labels


def v3_n46(E: Events, drops: np.ndarray) -> dict:
    """V3 for N4.6: every event of every draw: inside the held set (by construction of the array), weight within tau of the rule's,
    nothing/everything dropped where the rule drops nothing/everything, the event list equals the rule's (same R)."""
    bad = {"dropped_weight_outside_tau": 0, "empty_or_full_not_matched": 0, "event_list_differs": 0}
    checked = 0
    if drops.shape[1] != E.R:
        bad["event_list_differs"] += int(drops.shape[0])
    for k, ev in enumerate(E.evs):
        d = drops[:, E.off[k]:E.off[k + 1]].astype(float)
        dw = d @ ev["w"]
        bad["dropped_weight_outside_tau"] += int((np.abs(dw - ev["D"]) > ev["tau"] + SUBSET_TOL).sum())
        nd = int(ev["drop"].sum())
        n = len(ev["drop"])
        if nd == 0:
            bad["empty_or_full_not_matched"] += int((d.sum(axis=1) != 0).sum())
        elif nd == n:
            bad["empty_or_full_not_matched"] += int((d.sum(axis=1) != n).sum())
        checked += len(d)
    return {"draws_x_events_checked": int(checked), "failures": bad, "pass": bool(checked > 0 and sum(bad.values()) == 0)}


def v3_n48(E: Events, labels: np.ndarray) -> dict:
    bad = {"label_counts_differ": 0}
    checked = 0
    for k, ev in enumerate(E.evs):
        lab = labels[:, E.off[k]:E.off[k + 1]]
        for b in range(3):
            bad["label_counts_differ"] += int(((lab == b).sum(axis=1) != int((ev["bands"] == b).sum())).sum())
        checked += len(lab)
    return {"draws_x_events_checked": int(checked), "failures": bad, "pass": bool(checked > 0 and sum(bad.values()) == 0)}


# ── simulation (T07's, unchanged) ─────────────────────────────────────────────
def sim(bk: Book, E: Events, dflat, cost_bps: float, mix_f: float | None = None, record: bool = False, share: bool = False):
    """Run an event list. dflat: uint8 drops over E's rows (ignored when mix_f is given). Returns a dict: nav, trades (count), cost_paid,
    and with record: the trade and position logs; with share: the daily share of NAV held in stocks."""
    T, ow, N = bk.T, cost_bps / 2e4, bk.N
    C, P, g, gf, L = bk.C, bk.P, bk.g, bk.gf, bk.L
    ev0 = E.evs[0]
    u = np.zeros(N)
    if mix_f is not None:
        u = bk.u0 * mix_f
        gu = (1 - mix_f) / 2 / g[0]
        cu = (1 - mix_f) / 2 / L[0]
    else:
        d0 = dflat[E.off[0]:E.off[1]].astype(bool)
        kc, dc = ev0["cols"][~d0], ev0["cols"][d0]
        u[kc] = bk.u0[kc]
        val = float((bk.u0[dc] * C[0, dc]).sum())
        gu, cu = val / 2 / g[0], val / 2 / L[0]
    nav = np.empty(T)
    shr = np.empty(T) if share else None
    nz = np.flatnonzero(u)
    a = 0
    ntr, cpaid = 0, 0.0
    trades, pos_log = [], []

    def fill(a, t):
        sv = C[a:t][:, nz] @ u[nz] if len(nz) else np.zeros(t - a)
        nav[a:t] = sv + g[a:t] * gu + L[a:t] * cu
        if share:
            shr[a:t] = sv / nav[a:t]

    for k in range(1, E.n):
        ev = E.evs[k]
        t = ev["t"]
        fill(a, t)
        a = t
        ps, gp, lv = P[t], gf[t], L[t]
        held_s = u * ps
        V = held_s.sum() + gu * gp + cu * lv
        w = ev["w"]
        if mix_f is not None:
            wt, s = w * mix_f, 1.0 - mix_f
        else:
            d = dflat[E.off[k]:E.off[k + 1]].astype(bool)
            nd = int(d.sum())
            wt = np.where(d, 0.0, w)
            s = 0.0 if nd == 0 else (1.0 if nd == len(d) else float(w[d].sum() / w.sum()))
        Te = np.zeros(N)
        Te[ev["cols"]] = V * wt
        Tg = Tc = V * s / 2
        traded = np.abs(Te - held_s).sum() + abs(Tg - gu * gp) + abs(Tc - cu * lv)
        cost = ow * traded
        kk = (V - cost) / V
        pos = (Te > 0) & (ps > 0)
        assert not ((Te > 0) & (ps <= 0)).any(), f"no price for a stock to buy at session {bk.cal[t].date()}"
        if record:
            nobar_n = int((bk.nobar[t] & ((Te > 0) | (held_s > 0))).sum())
            gold_raw_trade = bool(bk.gold_raw[t] and abs(Tg - gu * gp) > 0)
        new_u = np.zeros(N)
        new_u[pos] = kk * Te[pos] / ps[pos]
        u, gu, cu = new_u, kk * Tg / gp, kk * Tc / lv
        nz = np.flatnonzero(u)
        ntr += 1
        cpaid += cost
        if record:
            nav_close = float(C[t][nz] @ u[nz] + gu * g[t] + cu * L[t]) if len(nz) else float(gu * g[t] + cu * L[t])
            trades.append({"k": k, "date": bk.cal[t].date(), "idx": t, "kind": ev["kind"], "e_after": 1.0 - s, "basket_eff": bk.eff[ev["b"]].date(),
                           "V": V, "traded": traded, "cost": cost, "nav_close_after": nav_close, "n_dropped": (int(d.sum()) if mix_f is None else 0),
                           "stock_no_bar": nobar_n, "gold_raw": gold_raw_trade})
            for i in nz:
                pos_log.append({"date": bk.cal[t].date(), "instrument": bk.stocks[i], "units": u[i]})
            if gu > 0:
                pos_log.append({"date": bk.cal[t].date(), "instrument": "GOLDBEES", "units": gu})
            if cu > 0:
                pos_log.append({"date": bk.cal[t].date(), "instrument": "LBES", "units": cu})
    fill(a, T)
    out = {"nav": nav, "trades": ntr, "cost_paid": cpaid}
    if share:
        out["share"] = shr
    if record:
        out["trade_log"], out["pos_log"] = trades, pos_log
    return out


def stats(nav: np.ndarray) -> dict:
    T = len(nav)
    yrs = (T - 1) / 252
    r = nav[1:] / nav[:-1] - 1
    peak = np.maximum.accumulate(nav)
    dd = nav / peak - 1
    under = (dd < 0).astype(np.int8)
    ch = np.flatnonzero(np.diff(np.concatenate([[0], under, [0]])))
    longest = int((ch[1::2] - ch[0::2]).max()) if len(ch) else 0
    cagr = nav[-1] ** (1 / yrs) - 1
    mdd = float(dd.min())
    return {"end_nav": float(nav[-1]), "cagr": float(cagr), "max_dd": mdd, "vol": float(r.std(ddof=1) * math.sqrt(252)),
            "ulcer": float(math.sqrt(np.mean((100 * dd) ** 2))), "days_below_10pct": int((dd <= -0.10).sum()),
            "longest_underwater": longest, "calmar": float(cagr / abs(mdd)) if mdd < 0 else float("nan"), "sessions": T}


def pctile(x: float, draws, higher_better: bool = True) -> float:
    """(draws worse + 0.5 x draws tied) / draws x 100; ties are equal within a relative 1e-12."""
    d = np.asarray(draws, dtype=float)
    tie = np.abs(d - x) <= 1e-12 * np.maximum(np.maximum(np.abs(d), abs(x)), 1e-300)
    worse = (d < x) if higher_better else (d > x)
    worse &= ~tie
    return float((worse.sum() + 0.5 * tie.sum()) / len(d) * 100)


# ── V5 (a) ────────────────────────────────────────────────────────────────────
def gammaincc(a: float, x: float) -> float:
    """Regularised upper incomplete gamma Q(a, x) (series / continued fraction)."""
    if x <= 0:
        return 1.0
    gln = math.lgamma(a)
    if x < a + 1:
        ap_, s, de = a, 1.0 / a, 1.0 / a
        for _ in range(10000):
            ap_ += 1
            de *= x / ap_
            s += de
            if abs(de) < abs(s) * 1e-16:
                break
        return 1.0 - s * math.exp(-x + a * math.log(x) - gln)
    b = x + 1 - a
    c = 1e300
    d = 1 / b
    h = d
    for i in range(1, 10000):
        an = -i * (i - a)
        b += 2
        d = an * d + b
        d = 1e-300 if abs(d) < 1e-300 else d
        c = b + an / c
        c = 1e-300 if abs(c) < 1e-300 else c
        d = 1 / d
        de = d * c
        h *= de
        if abs(de - 1) < 1e-16:
            break
    return math.exp(-x + a * math.log(x) - gln) * h


def sampler_selftest(n: int = 200_000) -> dict:
    """V5(a): a small unequal-weight basket; every allowed subset enumerated by brute force (itertools over index tuples, exact Fractions);
    n samples drawn with the production index rule floor(u x count) from the production subset enumeration; chi-square against equal frequencies.
    Seed default_rng([15, 7, 123456789, 99]) (T07's [7, 123456789, 99] with the T12 prefix)."""
    from fractions import Fraction
    from itertools import combinations
    w_f = [Fraction(x, 100) for x in (22, 17, 14, 12, 10, 9, 8, 5, 3)]            # sums to 1, unequal
    w = np.array([float(x) for x in w_f])
    D_f = Fraction(30, 100)
    tau_f = min(w_f) / 2
    brute = []
    for r in range(len(w_f) + 1):
        for cmb in combinations(range(len(w_f)), r):
            if abs(sum(w_f[i] for i in cmb) - D_f) <= tau_f:
                brute.append(sum(1 << i for i in cmb))
    brute.sort()
    sums = subset_sums(w)
    A = np.flatnonzero(np.abs(sums - float(D_f)) <= 0.5 * w.min() + SUBSET_TOL)
    rng = np.random.default_rng([SEED, 7, 123456789, 99])
    idx = pick_index(rng.random(n), len(A))
    cnt = np.bincount(idx, minlength=len(A))
    exp = n / len(A)
    chi = float(((cnt - exp) ** 2 / exp).sum())
    df = len(A) - 1
    p = gammaincc(df / 2, chi / 2)
    return {"weights": [str(x) for x in w_f], "D": str(D_f), "tau": str(tau_f), "n_allowed_brute_force": len(brute), "n_allowed_engine": int(len(A)),
            "sets_equal": bool(list(A) == brute), "samples": n, "seed": [SEED, 7, 123456789, 99], "expected_each": exp, "min_count": int(cnt.min()), "max_count": int(cnt.max()),
            "chi2": chi, "df": df, "p": p, "pass": bool(list(A) == brute and len(A) >= 10 and p > 0.001)}


# ── per-book processing ───────────────────────────────────────────────────────
def kind_row(book, window, cash, cost, kind, nav, events, trades, cost_paid, invested, extra=None) -> dict:
    return {"book": book, "window": window, "cash": cash, "cost_bps": cost, "kind": kind, **stats(nav), "invested_weeks": invested,
            "trades": trades, "cost_paid": cost_paid, "events": events, **(extra or {})}


def run_variants(bk: Book, E: Events, Ew: Events, Ep: Events | None, Es: Events | None, cost: float, window: str, cash: str, record_all: bool, p: str, rows: list):
    """Rule + comparators at one cost on one calendar/cash (no published NAV in this window). Ep/Es None (full_r6): the rule and the whole-book switch only.
    Returns the records (trade log, nav, share of the rule)."""
    J = len(E.kept_share)
    rule = sim(bk, E, E.dflat, cost, record=True, share=True)
    f = float(rule["share"].mean())
    whole = sim(bk, Ew, Ew.dflat, cost, record=record_all)
    rows += [kind_row(p, window, cash, cost, "segment", rule["nav"], E.n, rule["trades"], rule["cost_paid"], float(E.kept_share.sum())),
             kind_row(p, window, cash, cost, "whole_book", whole["nav"], Ew.n, whole["trades"], whole["cost_paid"], float(Ew.kept_share.sum()))]
    out = {"segment": rule, "whole_book": whole, "f": f}
    if Ep is not None:
        par = sim(bk, Ep, Ep.dflat, cost, record=record_all)
        mix = sim(bk, E, None, cost, mix_f=f, record=record_all)
        slp = sim(bk, Es, Es.dflat, cost, record=record_all)
        rows += [kind_row(p, window, cash, cost, "parent", par["nav"], Ep.n, par["trades"], par["cost_paid"], float(J)),
                 kind_row(p, window, cash, cost, "constant_mix", mix["nav"], E.n, mix["trades"], mix["cost_paid"], J * f, {"mix_share_f": f}),
                 kind_row(p, window, cash, cost, "sleeve100", slp["nav"], Es.n, slp["trades"], slp["cost_paid"], 0.0)]
        out.update({"parent": par, "constant_mix": mix, "sleeve100": slp})
    return out


def draw_rows(bk: Book, E: Events, drops: np.ndarray, dtype: str, window: str, cash: str, cost: float, w_flat: np.ndarray, curves: dict | None, book: str) -> list:
    dw = np.add.reduceat(drops.astype(float) * w_flat[None, :], E.off[:-1], axis=1).mean(axis=1)
    rows = []
    for d in range(len(drops)):
        r = sim(bk, E, drops[d], cost)
        rows.append({"book": book, "window": window, "cash": cash, "cost_bps": cost, "draw_type": dtype, "draw_id": d, **stats(r["nav"]),
                     "trades": r["trades"], "cost_paid": r["cost_paid"], "mean_dropped_weight": float(dw[d]), "n_events": E.n})
        if curves is not None:
            curves[f"{book}|{dtype}_{d}"] = r["nav"].astype(np.float32)
    return rows


def event_tables(p: str, window: str, E: Events, bk: Book, rec_trades: list, dec: pd.DataFrame, nA_ok: bool = True):
    """events.csv rows, event_stocks.csv rows of the rule (T12: tag_n_ranked added)."""
    by_k = {t["k"]: t for t in rec_trades}
    ev_rows, st_rows = [], []
    row0 = 0
    for k, ev in enumerate(E.evs):
        t = ev["t"]
        n = len(ev["cols"])
        nd = int(ev["drop"].sum())
        sw = float(ev["w"].sum())
        D = float(ev["w"][ev["drop"]].sum())
        tr = by_k.get(k)
        ev_rows.append({"book": p, "window": window, "event_no": k, "kind": ev["kind"], "trade_date": bk.cal[t].date(), "trade_idx": t,
                        "info_date": bk.cal[ev["info_idx"]].date(), "decision_date": dec["decision_date"].iloc[ev["jst"]],
                        **{f"state_{SIGNALS[i]}": ("BUY" if ev["state"][i] else "SELL") for i in range(3)},
                        "basket_eff": bk.eff[ev["b"]].date(), "n_held": n, "n_large": int((ev["bands"] == 0).sum()), "n_mid": int((ev["bands"] == 1).sum()),
                        "n_small": int((ev["bands"] == 2).sum()), "n_dropped": nd, "dropped_weight": D, "sum_weights": sw,
                        "sum_weights_raw": float(ev["wraw"].sum()), "sleeve_share_s": (0.0 if nd == 0 else 1.0 if nd == n else D / sw),
                        "partial": bool(0 < nd < n), "n_allowed_subsets": ev["nA"], "tau": ev["tau"],
                        "V_before": (tr["V"] if tr else 1.0), "traded": (tr["traded"] if tr else 0.0), "cost": (tr["cost"] if tr else 0.0)})
        for i, c in enumerate(ev["cols"]):
            tg = ev["tags"][i]
            st_rows.append({"book": p, "window": window, "event_no": k, "row": row0 + i, "trade_date": bk.cal[t].date(), "info_date": bk.cal[ev["info_idx"]].date(),
                            "isin": bk.isin[c], "stock": bk.stocks[c], "listed_weight": float(ev["w"][i]), "listed_weight_raw": float(ev["wraw"][i]),
                            "band": BANDS[int(ev["bands"][i])], "tag_source": tg["source"], "tag_snapshot": tg["snapshot"], "tag_detail": tg["detail"],
                            "tag_n_ranked": tg.get("n_ranked"), "tag_via": tg["via"], "band_signal": "BUY" if ev["state"][int(ev["bands"][i])] else "SELL",
                            "kept": bool(not ev["drop"][i])})
        row0 += n
    return ev_rows, st_rows


def stretches(flags) -> list:
    out, c = [], 0
    for f in flags:
        if f:
            c += 1
        elif c:
            out.append(c)
            c = 0
    if c:
        out.append(c)
    return out


def oracle_drops(bk: Book, E: Events) -> np.ndarray:
    """V7: per event the subset of the allowed set with the lowest sum of w x log return from the trade session to the next event's trade session."""
    prepare_allowed(E)
    out = np.zeros(E.R, dtype=np.uint8)
    for k, ev in enumerate(E.evs):
        cols = ev["cols"]
        start = bk.C[0, cols] if k == 0 else bk.P[ev["t"], cols]
        end = bk.C[bk.T - 1, cols] if k == E.n - 1 else bk.P[E.evs[k + 1]["t"], cols]
        with np.errstate(divide="ignore", invalid="ignore"):
            lr = np.where((start > 0) & (end > 0), np.log(end / start), 0.0)
        score = ev["Abits"].astype(float) @ (ev["w"] * lr)
        out[E.off[k]:E.off[k + 1]] = ev["Abits"][int(np.argmin(score))]
    return out


# ── R7 (T11's code, copied) ──────────────────────────────────────────────────
def held_either(bk: Book) -> np.ndarray:
    """(T, N) bool: the stock has weight > 0 in the basket in force on session t-1 or on session t (t = 0: session 0 only)."""
    held = bk.W[bk.basket_at] > 0
    prev = np.vstack([held[:1], held[:-1]])
    return held | prev


def flagged_days(bk: Book, thr: float = R7_THRESHOLD) -> tuple[np.ndarray, np.ndarray]:
    """mask[t, i] iff t >= 1, both ffilled closes are positive, |close[t]/close[t-1] - 1| >= thr and the stock is held on t-1 or t."""
    C = bk.C
    prev = np.vstack([C[:1], C[:-1]])
    ok = (C > 0) & (prev > 0)
    ret = np.zeros_like(C)
    ret[ok] = C[ok] / prev[ok] - 1
    mask = ok & (np.abs(ret) >= thr) & held_either(bk)
    mask[0] = False
    return mask, ret


def zero_return_book(bk: Book, mask: np.ndarray) -> Book:
    """A copy of the book whose prices carry the return-preserving splice: for every flagged (t, i), all prices of stock i from t on (closes and OHLC4 fills)
    are multiplied by close[t-1]/close[t], so the return of day t is exactly 0 and no other return changes."""
    C = bk.C
    prev = np.vstack([C[:1], C[:-1]])
    ok = mask & (C > 0) & (prev > 0)
    ratio = np.ones_like(C)
    ratio[ok] = prev[ok] / C[ok]
    s = np.cumprod(ratio, axis=0)
    new = copy.copy(bk)
    new.C, new.P = C * s, bk.P * s
    return new


def standin_sessions(bk: Book) -> dict:
    """ST: sessions where something is priced by a stand-in (previous close for a held stock or for GOLDBEES, raw OHLC4 for GOLDBEES)."""
    held = bk.W[bk.basket_at] > 0
    stock = np.flatnonzero((held & bk.nobar).any(axis=1))
    return {"stock_prev_close": set(int(t) for t in stock), "gold_prev_close": set(int(t) for t in np.flatnonzero(bk.gold_nobar)),
            "gold_raw_ohlc4": set(int(t) for t in np.flatnonzero(bk.gold_norange)), "held_stock_sessions_prev_close": int((held & bk.nobar).sum())}


def events_on(E: Events, sess: dict) -> dict:
    ts = [ev["t"] for ev in E.evs[1:]]
    return {k: int(sum(1 for t in ts if t in v)) for k, v in sess.items() if isinstance(v, set)}


def process_book(p: str, cfg: dict) -> dict:
    """Everything for one parent: the full, r2 (and full_r6) windows, all costs, cash variants, comparators, draws, R7, controls, R5, V4(a)/(b)."""
    global CHECK_SHA, R6_IDS, R6_LINKS
    CHECK_SHA = cfg.get("check_sha", False)
    R6_IDS = cfg.get("r6_ids", "frozen")
    R6_LINKS = R6_LINK_SETS[R6_IDS]
    t_start = time.time()
    book_no = PARENTS.index(p)
    nd = cfg["draws"]
    ids = np.arange(nd)
    tagger = Tagger()
    res = {"book": p, "stats": [], "draws": [], "nav": {}, "trades": [], "positions": [], "events": [], "event_stocks": [], "drops": {}, "labels": {}, "curves": {},
           "audit": {}, "count_table": {}, "v3": {}, "v5": {"count_equal": 0, "count_unequal": 0, "rule_in_allowed": 0, "events": 0}, "controls": {}, "r5": [],
           "r7_flagged": [], "r6_links": []}
    a_book = res["audit"]
    st_events = {}
    realisations = {}
    windows = ["full", "r2"] + (["full_r6"] if p in R6_LINKS else [])
    for window in windows:
        bk = Book(p, start=R2_START if window == "r2" else None)
        dec, S, idx = bk.decisions()
        tg = Tagger(R6_LINKS[p]) if window == "full_r6" else tagger
        E = build_events(bk, idx, S, "seg", tg, keep_tags=True)
        prepare_allowed(E)
        Ew = build_events(bk, idx, S, "whole")
        Ep = build_events(bk, idx, S, "parent") if window != "full_r6" else None
        Es = build_events(bk, idx, np.zeros_like(S), "whole") if window != "full_r6" else None
        sess = standin_sessions(bk)
        st_events[window] = {"rule": events_on(E, sess), "whole_book": events_on(Ew, sess), **({"parent": events_on(Ep, sess), "sleeve100": events_on(Es, sess)} if Ep else {})}
        if window == "full":
            res["decisions"] = dec
            sess_full = sess
        # V5(b)/(c)
        for ev in E.evs:
            w = ev["w"]
            alt = bits_matrix(len(w)).astype(float) @ w
            cnt_alt = int((np.abs(alt - ev["D"]) <= ev["tau"] + SUBSET_TOL).sum())
            res["v5"]["events"] += 1
            res["v5"]["count_equal" if cnt_alt == ev["nA"] else "count_unequal"] += 1
            res["v5"]["rule_in_allowed"] += int(int((ev["drop"].astype(np.int64) << np.arange(len(w))).sum()) in set(ev["A"].tolist()))
        # draws (the same for every cost and cash)
        n46 = draws_n46(E, book_no, ids)
        res["drops"][f"{p}|{window}|N4.6"] = n46
        res["v3"][f"{p}|{window}"] = {"N4.6": v3_n46(E, n46)}
        types = [("N4.6", n46)]
        if window != "full_r6":
            n48, lab48 = draws_n48(E, book_no, ids, bk.isin)
            res["drops"][f"{p}|{window}|N4.8"], res["labels"][f"{p}|{window}|N4.8"] = n48, lab48
            res["v3"][f"{p}|{window}"]["N4.8"] = v3_n48(E, lab48)
            types.append(("N4.8", n48))
        reals = [("lbes", c) for c in COSTS] + [("liq", PRIMARY)] if window == "full" else [("lbes", PRIMARY)]
        bkc = {"lbes": bk, "liq": Book(p, cash="liq") if window == "full" else None}
        for cash, cost in reals:
            b2 = bkc[cash]
            headline = (window == "full" and cash == "lbes")
            vr = run_variants(b2, E, Ew, Ep, Es, cost, window, cash, headline, p, res["stats"])
            if cash == "lbes" and cost == PRIMARY:
                rule = vr["segment"]
                ev_rows, st_rows = event_tables(p, window, E, b2, rule["trade_log"], dec)
                res["events"] += ev_rows
                res["event_stocks"] += st_rows
                realisations[window] = {"E": E, "Ew": Ew, "bk": b2, "dec": dec, "S": S, "idx": idx, "whole_cagr": stats(vr["whole_book"]["nav"])["cagr"]}
                a_book.setdefault("rule_counters", {})[window] = {
                    "stock_lines_priced_by_previous_close_at_trades": int(sum(t["stock_no_bar"] for t in rule["trade_log"])),
                    "goldbees_trades_filled_at_raw_OHLC4_no_MCX_range": int(sum(t["gold_raw"] for t in rule["trade_log"]))}
            if headline:
                for name in ("segment", "whole_book", "parent", "constant_mix", "sleeve100"):
                    rr = vr[name]
                    res["nav"][(p, cost, name)] = rr["nav"]
                    res["trades"] += [{"book": p, "cost_bps": cost, "run": name, **{k: v for k, v in t.items() if k not in ("stock_no_bar", "gold_raw", "k")}, "event_no": t["k"]}
                                      for t in rr["trade_log"]]
                    res["positions"] += [{"book": p, "cost_bps": cost, "run": name, **q} for q in rr["pos_log"]]
                    a_book.setdefault("recorded_trade_counters", {})[f"{name}|{cost}"] = {
                        "trades_with_a_stock_priced_by_previous_close": int(sum(1 for t in rr["trade_log"] if t["stock_no_bar"] > 0)),
                        "trades_goldbees_raw_OHLC4": int(sum(t["gold_raw"] for t in rr["trade_log"])),
                        "trades_on_goldbees_no_bar_session": int(sum(1 for t in rr["trade_log"] if t["idx"] in sess_full["gold_prev_close"]))}
            for dtype, dr in types:
                res["draws"] += draw_rows(b2, E, dr, dtype, window, cash, cost, E.w_flat,
                                          res["curves"] if (headline and cost == PRIMARY) else None, p)
        if window == "full":
            res["cal_full"] = bk.cal
            # R7: flagged days and the spliced re-runs (events unchanged: they read no price)
            mask, ret = flagged_days(bk)
            for t, i in zip(*np.nonzero(mask)):
                res["r7_flagged"].append({"book": p, "isin": bk.isin[i], "stock": bk.stocks[i], "date": str(bk.cal[t].date()), "close_prev": float(bk.C[t - 1, i]),
                                          "close": float(bk.C[t, i]), "move": float(ret[t, i])})
            bkx = zero_return_book(bk, mask)
            for cost in (0.0, PRIMARY):
                for name, EE in (("segment_r7", E), ("whole_book_r7", Ew)):
                    r = sim(bkx, EE, EE.dflat, cost)
                    res["stats"].append(kind_row(p, "full", "lbes", cost, name, r["nav"], EE.n, r["trades"], r["cost_paid"], float(EE.kept_share.sum())))
                    res["nav"][(p, cost, name)] = r["nav"]
            a_book["r7"] = {"flagged_stock_days": int(mask.sum()), "threshold": R7_THRESHOLD}
        if window == "full_r6":
            for r in res["event_stocks"]:
                if r["window"] == "full_r6" and r["tag_source"] == "rank_linked":
                    res["r6_links"].append({"book": p, "isin": r["isin"], "stock": r["stock"], "original_source": "unranked", "linked_quote_id": R6_LINKS[p][r["isin"]],
                                            "info_date": str(r["info_date"]), "linked_rank": r["tag_detail"], "linked_band": r["band"], "event_no": r["event_no"]})
            a_book["r6_linked_quote_id_missing_on_snapshot"] = tg.linked_missing
        # counts, reportability
        flags = dec["disagree"].values
        stch = stretches(flags)
        cnt = E.counts()
        res["count_table"][window] = {
            "events": [{"event_no": k, "trade_date": str(bk.cal[ev["t"]].date()), "n_allowed_subsets": str(ev["nA"]), "tau": ev["tau"], "n_held": len(ev["cols"]),
                        "n_dropped": int(ev["drop"].sum()), "dropped_weight": ev["D"], "weights": [float(x) for x in ev["w"]], "boundary_cases": ev["boundary"]}
                       for k, ev in enumerate(E.evs)],
            "events_with_partial": cnt["partial"], "disagreement_stretches": stch, "n_disagreement_stretches": len(stch)}
        in_dis = int(sum(1 for ev in E.evs[1:] if dec["disagree"].iloc[ev["jst"]]))
        # Step 1's attribution (READINGS C1): a signal event belongs to its decision, a basket-only event to the first decision on or after its session
        j_after = lambda t: min(int(np.searchsorted(idx, t, side="left")), len(idx) - 1)
        in_dis_s1 = int(sum(1 for ev in E.evs[1:] if flags[ev["jst"] if ev["kind"] != "basket" else j_after(ev["t"])]))
        no_flip = int(sum(1 for ev in E.evs[1:] if ev["kind"] != "basket" and ev["jst"] > 0 and (S[ev["jst"]] == S[ev["jst"] - 1]).all()))
        ws = [ev["nA"] for ev in E.evs]
        src_cnt = pd.Series([r["tag_source"] for r in res["event_stocks"] if r["window"] == window]).value_counts().to_dict()
        unr = [{"isin": r["isin"], "stock": r["stock"], "event_no": r["event_no"], "info_date": str(r["info_date"]), "tag_snapshot": r["tag_snapshot"]}
               for r in res["event_stocks"] if r["window"] == window and r["tag_source"] == "unranked"]
        a_book.setdefault("windows", {})[window] = {
            "t0": str(bk.t0.date()), "last_session": str(bk.cal[-1].date()), "sessions": bk.T, "decisions": len(dec),
            "initial_basket_switch_session": bk.initial_basket_switch_session, "initial_basket_eff": str(bk.eff[bk.b0].date()), "cash": bk.cash_info,
            "disagreement_weeks": int(flags.sum()), "disagreement_stretches": len(stch), "stretch_lengths": stch,
            "events": cnt, "events_in_disagreement_weeks": in_dis, "events_in_disagreement_weeks_step1_attribution": in_dis_s1,
            "signal_events_without_a_change_of_the_triple": no_flip, "n_allowed_subsets_min_median_max": [int(min(ws)), int(np.median(ws)), int(max(ws))],
            "events_with_one_allowed_subset": int(sum(1 for x in ws if x == 1)), "tau_boundary_cases": int(sum(ev["boundary"] for ev in E.evs)),
            "skipped_basket_events": E.skipped, "whole_book_events": Ew.counts(), "whole_book_skipped_basket_events": len(Ew.skipped),
            "tag_source_event_rows": src_cnt, "unranked_event_rows": unr, "v2": E.v2,
            "reportable": bool(len(stch) >= 5 and cnt["partial"] >= 6),
            "mean_dropped_weight_rule": float(np.mean([ev["D"] for ev in E.evs])),
            "n_universe_N4.8": (len(E.universe) if E.universe is not None else None),
            "pattern_counts": dec["pattern"].value_counts().to_dict(),
            "sc100_earliest_label": str(pd.to_datetime(dec["label_SC100"]).min().date())}
        wv2 = a_book["windows"][window]["v2"]
        wv2["decisions_checked"] = int(len(dec))
        wv2["decisions_label_after_decision"] = int((pd.to_datetime(dec["latest_label"]) > pd.to_datetime(dec["decision_date"])).sum())
        wv2["sc100_label_before_usable_from"] = int((pd.to_datetime(dec["label_SC100"]) < SC_USABLE_FROM).sum())
        td = pd.to_datetime(dec["trade_date"].dropna())
        dd = pd.to_datetime(dec.loc[dec["trade_date"].notna(), "decision_date"])
        wv2["decision_trades_checked"] = int(len(td))
        wv2["decision_trade_not_after_decision"] = int((td.values <= dd.values).sum())
    # stand-ins (full window sessions; event sessions of every realisation)
    a_book["standins"] = {"held_stock_sessions_priced_by_previous_close": sess_full["held_stock_sessions_prev_close"],
                          "sessions_with_a_held_stock_without_bar": [str(res["cal_full"][t].date()) for t in sorted(sess_full["stock_prev_close"])],
                          "goldbees_no_bar_sessions": [str(res["cal_full"][t].date()) for t in sorted(sess_full["gold_prev_close"])],
                          "goldbees_no_mcx_range_sessions": [str(res["cal_full"][t].date()) for t in sorted(sess_full["gold_raw_ohlc4"])],
                          "event_sessions_on_standin_sessions": st_events}
    a_book["seconds_core"] = round(time.time() - t_start)
    full = realisations["full"]
    if cfg["controls"]:
        res["controls"] = controls_book(p, book_no, full, res, tagger, cfg, sess_full)
    if cfg["r5"] > 0:
        res["r5"], r5_st = r5_book_st(p, book_no, full, tagger, cfg["r5"], sess_full)
        a_book["standins"]["r5_event_sessions_on_standin_sessions"] = r5_st
    if cfg.get("v4a", True):
        res["v4a"] = d17_book(p)
    res["v4b"] = v4b_book(p, res, cfg.get("v4b_dir"))
    a_book["seconds"] = round(time.time() - t_start)
    res["usedfiles"] = USED
    res["tag_cache_size"] = len(tagger.cache)
    return res


def controls_book(p: str, book_no: int, full: dict, res: dict, tagger: Tagger, cfg: dict, sess: dict | None = None) -> dict:
    """V6 (negative control) and V7 (oracle) for one book, full window, LBES, 20.8 bps."""
    bk, dec, S, idx, E = full["bk"], full["dec"], full["S"], full["idx"], full["E"]
    J = len(idx)
    out = {}
    # V7
    od = oracle_drops(bk, E)
    ro = sim(bk, E, od, PRIMARY)
    so = stats(ro["nav"])
    n46_c = np.array([r["cagr"] for r in res["draws"] if r["draw_type"] == "N4.6" and r["window"] == "full" and r["cash"] == "lbes" and r["cost_bps"] == PRIMARY])
    pc = pctile(so["cagr"], n46_c)
    out["v7"] = {"book": p, "oracle_cagr": so["cagr"], "oracle_max_dd": so["max_dd"], "percentile_vs_N4.6": pc,
                 "n46_draws": int(len(n46_c)), "events_with_a_choice": int(sum(1 for ev in E.evs if ev["nA"] > 1)), "pass_ge_99": bool(pc >= 99)}
    # V6
    n = J
    shifts = np.arange(26, n - 26 + 1)
    chosen = np.random.default_rng([SEED, 9, 100000, book_no]).choice(shifts, size=cfg["v6_shifts"], replace=False)
    rows = []
    v3_bad, v3_checked, st_ev = 0, 0, 0
    for i, k in enumerate(chosen):
        Ssh = np.roll(S, int(k), axis=0)
        Esh = build_events(bk, idx, Ssh, "seg", tagger)
        prepare_allowed(Esh)
        if sess is not None:
            st_ev += sum(events_on(Esh, sess).values())
        rng = np.random.default_rng([SEED, 9, i, book_no])
        U = rng.random((cfg["v6_draws"], Esh.n))
        drops = np.zeros((cfg["v6_draws"], Esh.R), dtype=np.uint8)
        for kk, ev in enumerate(Esh.evs):
            drops[:, Esh.off[kk]:Esh.off[kk + 1]] = ev["Abits"][pick_index(U[:, kk], ev["nA"])]
        v = v3_n46(Esh, drops)
        v3_bad += sum(v["failures"].values())
        v3_checked += v["draws_x_events_checked"]
        rr = stats(sim(bk, Esh, Esh.dflat, PRIMARY)["nav"])
        dcagr = np.array([stats(sim(bk, Esh, drops[d], PRIMARY)["nav"])["cagr"] for d in range(len(drops))])
        pc_i = pctile(rr["cagr"], dcagr)
        rows.append({"book": p, "shift_index": i, "shift_k": int(k), "n_events": Esh.n, "cagr": rr["cagr"], "percentile": pc_i, "pass90": bool(pc_i >= 90)})
    n6 = len(rows)
    x6 = V6_XMAX_FROZEN
    assert n6 != 100 or v6_xmax(n6) == x6, "T12.md V6 (17 of 100) differs from T07's amended rule"
    npass = int(sum(r["pass90"] for r in rows))
    out["v6"] = {"book": p, "n_shifts": n6, "draws_per_shift": cfg["v6_draws"], "n_pass90": npass, "x_max": x6,
                 "share_pass90": (npass / n6 if n6 else float("nan")), "pass": bool(n6 > 0 and npass <= x6),
                 "v3_failures": int(v3_bad), "v3_draws_x_events_checked": int(v3_checked), "event_sessions_on_standin_sessions": int(st_ev)}
    out["v6_rows"] = rows
    return out


def r5_book(p: str, book_no: int, full: dict, tagger: Tagger, n: int) -> list:
    bk, S, idx = full["bk"], full["S"], full["idx"]
    out = []
    for d in range(n):
        pt = Perturb(d, book_no)
        Ed = build_events(bk, idx, S, "seg", tagger, perturb=pt)
        r = stats(sim(bk, Ed, Ed.dflat, PRIMARY)["nav"])
        out.append({"book": p, "draw_id": d, "cagr": r["cagr"], "diff_vs_whole_book": r["cagr"] - full["whole_cagr"], "n_events": Ed.n,
                    "rank_tag_reads": pt.rank_reads, "flipped": pt.flipped, "error_rate": R5_RATE})
    return out


def r5_book_st(p: str, book_no: int, full: dict, tagger: Tagger, n: int, sess: dict) -> tuple[list, int]:
    """r5_book plus the count of R5 event sessions on stand-in sessions (rebuilds the events once more per draw; cheap)."""
    out = r5_book(p, book_no, full, tagger, n)
    bk, S, idx = full["bk"], full["S"], full["idx"]
    st = 0
    for d in range(n):
        Ed = build_events(bk, idx, S, "seg", tagger, perturb=Perturb(d, book_no))
        st += sum(events_on(Ed, sess).values())
    return out, int(st)


# ── V4 ────────────────────────────────────────────────────────────────────────
def d17_book(p: str) -> dict:
    """V4(a): the engine on the book's D17 dates (first date to 2019-12-31) against T07's and T06's stored daily NAVs and T07's decisions."""
    bk = Book(p, calendar="d17", end=END_D17)
    dec, S, idx = bk.decisions()
    tagger = Tagger()
    E = build_events(bk, idx, S, "seg", tagger)
    Ew = build_events(bk, idx, S, "whole")
    Ep = build_events(bk, idx, S, "parent")
    Es = build_events(bk, idx, np.zeros_like(S), "whole")
    mine = {}
    for cost in COSTS:
        for name, EE in (("segment", E), ("whole_book", Ew), ("parent", Ep), ("sleeve100", Es)):
            mine[(name, cost)] = sim(bk, EE, EE.dflat, cost)["nav"]
    out = {"window": {"t0": str(bk.t0.date()), "last": str(bk.cal[-1].date()), "sessions": bk.T, "decisions": len(dec), "events_rule": E.n}, "t07": [], "t06": [], "decisions": {}}
    ok = True
    maps = {"t07": (T07E, {"segment": "segment", "whole_book": "whole_book", "parent": "parent", "sleeve100": "sleeve100"}),
            "t06": (T06E, {"strategy": "whole_book", "hold_parent": "parent", "sleeve_only": "sleeve100"})}
    for tag, (folder, names) in maps.items():
        st = pd.read_csv(folder / "daily_nav.csv")
        st = st[(st["book"] == p) & st["cost_bps"].notna()]
        n_rows = 0
        for (run, cost), gdf in st.groupby(["run", "cost_bps"]):
            if run not in names:
                continue
            gs = gdf.assign(date=pd.to_datetime(gdf["date"])).set_index("date")["nav"]
            mv = pd.Series(mine[(names[run], float(cost))], index=bk.cal)
            cd = gs.index.intersection(mv.index)
            rel = float((mv.loc[cd] / gs.loc[cd] - 1).abs().max()) if len(cd) else float("nan")
            passed = bool(len(cd) == bk.T and rel < REL_TOL_NAV)
            ok &= passed
            n_rows += 1
            out[tag].append({"book": p, "stored_run": run, "engine_run": names[run], "cost_bps": float(cost), "dates_compared": int(len(cd)), "sessions": bk.T,
                             "max_rel_diff": rel, "pass": passed})
        ok &= n_rows > 0
    # decisions against T07's stored decisions (sign triple, decision_idx); the engine's last decision (2019-12-31) has no counterpart
    t7d = pd.read_csv(T07E / "decisions.csv")
    b = t7d[t7d["book"] == p]
    a = dec.assign(decision_date=dec["decision_date"].astype(str))
    cols = ["decision_idx"] + [f"sign_{n}" for n in SIGNALS]
    m = a[["decision_date"] + cols].merge(b[["decision_date"] + cols], on="decision_date", how="left", suffixes=("", "_t07"))
    hit = m["decision_idx_t07"].notna()
    mism = int(sum(((m[c] != m[f"{c}_t07"]) & hit).sum() for c in cols))
    unmatched = m.loc[~hit, "decision_date"].tolist()
    good = bool(mism == 0 and hit.sum() > 0 and unmatched in ([], [a["decision_date"].iloc[-1]]))
    out["decisions"] = {"compared": int(hit.sum()), "mismatches": mism, "unmatched_dates_in_engine": unmatched, "pass": good}
    ok &= good
    out["max_rel_diff"] = float(max([r["max_rel_diff"] for r in out["t07"] + out["t06"]] or [float("inf")]))
    out["pass"] = bool(ok)
    return out


def v4b_book(p: str, res: dict, alt_dir: str | None = None) -> dict:
    """V4(b): whole_book vs T11's Part A strategy (strategy_fixed50) and parent vs T11's hold_parent on the full window, if T11's headline exists.
    alt_dir (testing only, never the gate): another T11 evidence folder to compare against."""
    folder = Path(alt_dir) if alt_dir else T11E
    if not (folder / "daily_nav.csv").exists():
        return {"status": "not run", "reason": f"{folder.relative_to(AA).as_posix() if folder.is_relative_to(AA) else folder} does not exist when the run started"}
    st = pd.read_csv(folder / "daily_nav.csv")
    st = st[(st["book"] == p) & st["cost_bps"].notna()]
    if st.empty:
        return {"status": "not run", "reason": f"no rows for {p} in {folder}"}
    names = {"strategy_fixed50": "whole_book", "hold_parent": "parent"}
    rows, ok = [], True
    cal = res["cal_full"]
    for (run, cost), gdf in st.groupby(["run", "cost_bps"]):
        if run not in names or (p, float(cost), names[run]) not in res["nav"]:
            continue
        gs = gdf.assign(date=pd.to_datetime(gdf["date"])).set_index("date")["nav"]
        mv = pd.Series(res["nav"][(p, float(cost), names[run])], index=cal)
        cd = gs.index.intersection(mv.index)
        rel = float((mv.loc[cd] / gs.loc[cd] - 1).abs().max()) if len(cd) else float("nan")
        passed = bool(len(cd) == len(cal) and rel < REL_TOL_NAV)
        ok &= passed
        rows.append({"book": p, "t11_run": run, "engine_run": names[run], "cost_bps": float(cost), "dates_compared": int(len(cd)), "max_rel_diff": rel, "pass": passed})
    return {"status": "run", "folder": str(folder), "rows": rows, "pass": bool(ok and len(rows) > 0), "used_for_gate": alt_dir is None}


V4C_REQUIRED_IDENTICAL = ["v6_xmax", "dropped_of", "Events", "build_events", "bits_matrix", "subset_sums", "prepare_allowed", "pick_index", "v3_n46", "v3_n48", "sim",
                          "stats", "pctile", "gammaincc", "kind_row", "draw_rows", "stretches", "oracle_drops", "r5_book"]
V4C_EXPECTED_CHANGED = {
    "ap": "records usable_from; no D17-specific note",
    "common": "T11's: D26 calendar, cut at `end`, D24b MCX range, Smallcap 100 guard",
    "raw_parent": "T11's: cut at `end`, D05 availableDates parsed; no D17 NAV",
    "cash_levels": "T11's: LIQUIDCASE as-of over the window (no 2024-01-24 splice inside it)",
    "Book": "T11's calendar (d26 / d17), T0, stand-ins and gold flags, plus T07's isin/Wraw/held/decisions",
    "Tagger": "D23b rank panel; R6 links; n_ranked",
    "Perturb": "seed prefix 15",
    "draws_n46": "seed prefix 15",
    "draws_n48": "seed prefix 15",
    "sampler_selftest": "seed prefix 15",
    "run_variants": "no published_parent row; reduced set for full_r6",
    "event_tables": "tag_n_ranked column",
    "process_book": "windows full / r2 / full_r6, R7, stand-ins, V4(a)/(b) per book",
    "controls_book": "seed prefix 15; V6 pass at <= 17 of 100 (T12.md)",
    "input_list": "T12's inputs",
    "check_inputs": "T12's through-dates and self-test",
    "rerun": "windows full / r2 / full_r6",
    "main": "T12's files and gates",
}


def shared_code_diff() -> dict:
    """V4(c): module-level functions and classes shared with t07_engine.py. Identical = the same AST (docstrings included)."""
    def defs(path):
        tree = ast.parse(Path(path).read_text(encoding="utf-8"))
        return {n.name: ast.dump(n) for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
    a, b = defs(T07_ENGINE), defs(Path(__file__))
    common_names = sorted(set(a) & set(b))
    changed = [n for n in common_names if a[n] != b[n]]
    unexpected = [n for n in changed if n not in V4C_EXPECTED_CHANGED]
    req_bad = [n for n in V4C_REQUIRED_IDENTICAL if n not in a or n not in b or a[n] != b[n]]
    return {"functions": {n: ("unchanged" if a[n] == b[n] else "changed") for n in common_names},
            "required_identical": V4C_REQUIRED_IDENTICAL, "required_not_identical": req_bad, "changed": changed,
            "expected_changes": V4C_EXPECTED_CHANGED, "changed_and_expected": [n for n in changed if n in V4C_EXPECTED_CHANGED], "unexpected_changes": unexpected,
            "dropped_from_t07": sorted(set(a) - set(b)), "new_in_t12": sorted(set(b) - set(a)), "pass": bool(not req_bad and not unexpected)}


def v4d_direct_tags(es: pd.DataFrame) -> dict:
    """V4(d): every event row's tag against a direct read of the D23b panel and D22 (not through tag_lookup)."""
    rp = pd.read_csv(ap(TAG_FILES["rank"]), usecols=["date", "quote_id", "isin", "rank", "band", "n_ranked"], dtype={"isin": str}, keep_default_na=False, na_values=[""])
    rp["date"] = pd.to_datetime(rp["date"])
    sy = pd.read_csv(ap(TAG_FILES["symb"]), usecols=["quote_id", "isin", "new_isin"], dtype={"isin": str, "new_isin": str}, keep_default_na=False, na_values=[""], low_memory=False)
    qid = {}
    for col in ("isin", "new_isin"):
        for i, q in zip(sy[col], sy["quote_id"]):
            if isinstance(i, str) and i and pd.notna(q):
                qid.setdefault(i, set()).add(int(q))
    for i, q in zip(rp["isin"], rp["quote_id"]):
        if isinstance(i, str) and i and pd.notna(q):
            qid.setdefault(i, set()).add(int(q))
    dates = np.array(sorted(rp["date"].unique()), dtype="datetime64[ns]")
    need = sorted(set(pd.to_datetime(es["info_date"])))
    snap_of = {d: pd.Timestamp(dates[np.searchsorted(dates, np.datetime64(d), side="right") - 1]) for d in need}
    by = {}
    for s in set(snap_of.values()):
        g = rp[rp["date"] == s]
        by[s] = ({i: (int(r), b) for i, r, b in zip(g["isin"], g["rank"], g["band"]) if isinstance(i, str)},
                 {int(q): (int(r), b) for q, r, b in zip(g["quote_id"], g["rank"], g["band"])}, int(g["n_ranked"].iloc[0]))
    bad, checked, examples = 0, 0, []
    for r in es.itertuples(index=False):
        s = snap_of[pd.Timestamp(r.info_date)]
        bi, bq, nr = by[s]
        if r.isin in bi:
            exp = ("rank", int(bi[r.isin][0]), bi[r.isin][1])
        else:
            hit = None
            for q in sorted(qid.get(r.isin, ())):
                if q in bq:
                    hit = q
                    break
            exp = ("rank", bq[hit][0], bq[hit][1]) if hit is not None else ("unranked", None, "Small and below")
        if r.tag_source == "rank_linked":
            q = R6_LINKS[r.book][r.isin]
            exp = ("rank_linked", bq[q][0], bq[q][1]) if (exp[0] == "unranked" and q in bq) else exp
        got_rank = None if (r.tag_detail is None or (isinstance(r.tag_detail, float) and np.isnan(r.tag_detail))) else int(r.tag_detail)
        ok = (r.tag_source == exp[0] and got_rank == exp[1] and r.band == exp[2] and str(r.tag_snapshot) == str(s.date())
              and (r.tag_n_ranked is None or (isinstance(r.tag_n_ranked, float) and np.isnan(r.tag_n_ranked)) or int(r.tag_n_ranked) == nr))
        checked += 1
        if not ok:
            bad += 1
            if len(examples) < 10:
                examples.append({"book": r.book, "window": r.window, "isin": r.isin, "info_date": str(r.info_date), "engine": [r.tag_source, got_rank, r.band, r.tag_snapshot],
                                 "direct": [exp[0], exp[1], exp[2], str(s.date())]})
    return {"rows_checked": checked, "mismatches": bad, "examples": examples, "pass": bool(checked > 0 and bad == 0)}


# ── main ──────────────────────────────────────────────────────────────────────
def input_list() -> tuple[list, list]:
    inputs = [CAL_FILE] + [MASTER_DIR / f"Master_{n}.xlsx" for n in SIGNALS]
    inputs += [GOLD_D09, D24B_DIR / "mauc1_daily_clean_extended.csv", HD / "LBES_Adjusted_Price_data_extended_2026-11-05.csv",
               HD / "liquidEtfFinal_extended_2026-11-05.csv", HM / "price_corrections.csv"]
    for p in PARENTS:
        inputs += [HM / f"{p}_{x}.csv" for x in ("ohlc", "holding_weight_matrix", "holding_weight_sources", "columns")]
        inputs += [HD / "frozen_2026-09-25" / "Rebalance_history" / f"Rebalance_history_by_scid_{p}.csv", D17_DIR / f"{p}.csv"]
    inputs += list(TAG_FILES.values())
    return inputs, []


def check_inputs() -> tuple[dict, list]:
    """Open every input through the approved table (sha256 checked), assert the window is covered, and run the non-approved-open self-test."""
    inputs, not_parsed = input_list()
    for f in inputs + not_parsed:
        ap(f)
    for rel, r in USED.items():
        if r["through"] in ("n/a",) or r["id"] in ("D19", "D05"):
            continue
        need = END_D17 if r["id"] == "D17" else END
        assert r["through"] >= str(need.date()), f"{rel}: approved through {r['through']}, before {need.date()}: stop and ask Manu"
    st = {}
    for name, f in (("superseded_master", HD / "frozen_2026-09-25" / "Master" / "Master_Nifty100.xlsx"),
                    ("superseded_goldbees", AA / "analysis" / "cache" / "why_gold_ohlc_eikon.parquet"),
                    ("superseded_lbes", HD / "LBES_Adjusted_Price_data_2026_08_10.csv"),
                    ("pending_candidate_d03b", HD / "extended_2026-11-12" / "SC100_signal_from_2011-10-03" / "Master_SC100.xlsx"),
                    ("not_in_table", HD / "no_such_file.csv"),
                    ("off_limits_SOURCE_md", HD / "extended_2026-11-12" / "SOURCE.md")):
        try:
            AD.require(f)
            st[name] = {"raised": False}
        except NotApprovedError as e:
            st[name] = {"raised": True, "message": str(e)}
    try:
        AD.guard_window(MASTER_DIR / "Master_SC100.xlsx", str((SC_USABLE_FROM - pd.Timedelta(days=1)).date()))
        st["guard_sc100_signal_before_usable_from"] = {"raised": False}
    except NotApprovedError as e:
        st["guard_sc100_signal_before_usable_from"] = {"raised": True, "message": str(e)}
    st["pass"] = all(v["raised"] for v in st.values() if isinstance(v, dict))
    return st, [x.relative_to(AA).as_posix() for x in not_parsed]


def rerun(a) -> int:
    """Rebuild one draw from its id (evidence_contract CLI)."""
    global CHECK_SHA
    CHECK_SHA = False
    cash, cost, p = a.cash, a.cost, a.book
    assert p in PARENTS and a.type in ("N4.6", "N4.8") and a.window in ("full", "r2", "full_r6")
    assert not (a.window == "full_r6" and (p not in R6_LINKS or a.type != "N4.6")), "full_r6: books SCMO_0007 / SCMO_0010 and N4.6 only"
    book_no = PARENTS.index(p)
    bk = Book(p, start=R2_START if a.window == "r2" else None, cash=cash)
    dec, S, idx = bk.decisions()
    tagger = Tagger(R6_LINKS[p] if a.window == "full_r6" else None)
    E = build_events(bk, idx, S, "seg", tagger)
    if a.type == "N4.6":
        d = draws_n46(E, book_no, [a.id])
    else:
        d, _ = draws_n48(E, book_no, [a.id], bk.isin)
    r = sim(bk, E, d[0], cost)
    s = stats(r["nav"])
    Path(a.out).write_text(json.dumps({"end_nav": s["end_nav"], "cagr": s["cagr"], "max_dd": s["max_dd"], "drops": [int(x) for x in d[0]]}), encoding="utf-8")
    print(f"rerun {p} {a.window} {a.type} id {a.id} cost {cost} cash {cash} -> {a.out}")
    return 0


def main():
    global CHECK_SHA
    ap_ = argparse.ArgumentParser()
    ap_.add_argument("--run", default="headline")
    ap_.add_argument("--draws", type=int, default=N_DRAWS)
    ap_.add_argument("--quick", action="store_true", help="smoke test: one book (SCMO_0003), no controls unless --controls, R5 with --r5 draws")
    ap_.add_argument("--controls", action="store_true", help="run V6 and V7 (always on in a full run)")
    ap_.add_argument("--v6-shifts", type=int, default=V6_SHIFTS)
    ap_.add_argument("--v6-draws", type=int, default=V6_DRAWS)
    ap_.add_argument("--r5", type=int, default=None, help="R5 draws per book (default 500; 20 with --quick)")
    ap_.add_argument("--jobs", type=int, default=None)
    ap_.add_argument("--books", default=None, help="comma-separated parents (default: SCMO_0003 with --quick, else all four); for tests")
    ap_.add_argument("--out-root", default=None, help="evidence root (default tests/T12/evidence); for scratch tests")
    ap_.add_argument("--calendar", choices=["d26", "d17"], default="d26", help="d17: run only the V4(a) regression and write regression_d17.json")
    ap_.add_argument("--v4b-dir", default=None, help="testing only: compare V4(b) against this T11 evidence folder (never the gate)")
    ap_.add_argument("--r6-ids", choices=sorted(R6_LINK_SETS), default="frozen",
                     help="R6 link set: 'frozen' (T12.md's quote_ids, default) or 'review' (the old listings of the D20b review; only on Manu's decision, READINGS R6b)")
    ap_.add_argument("--rerun", action="store_true")
    ap_.add_argument("--book")
    ap_.add_argument("--type")
    ap_.add_argument("--id", type=int)
    ap_.add_argument("--cost", type=float)
    ap_.add_argument("--window", default="full")
    ap_.add_argument("--cash", default="lbes")
    ap_.add_argument("--out")
    a = ap_.parse_args()
    global R6_IDS, R6_LINKS
    R6_IDS, R6_LINKS = a.r6_ids, R6_LINK_SETS[a.r6_ids]
    if a.rerun:
        sys.exit(rerun(a))
    outdir = (Path(a.out_root) if a.out_root else T12 / "evidence") / a.run
    outdir.mkdir(parents=True, exist_ok=True)
    t_start = time.time()
    t11_seen = bool((T11E / "daily_nav.csv").exists())
    books = a.books.split(",") if a.books else (PARENTS[:1] if a.quick else PARENTS)
    assert all(b in PARENTS for b in books)
    CHECK_SHA = True
    st, not_parsed = check_inputs()
    print(f"data: window {T0.date()} -> {END.date()}, approved data as of {AD.as_of()}, {len(USED)} inputs checked (sha256); non-approved open and the Smallcap 100 guard raise: {st['pass']}", flush=True)
    if a.calendar == "d17":
        reg = {p: d17_book(p) for p in books}
        ok = all(r["pass"] for r in reg.values())
        (outdir / "regression_d17.json").write_text(json.dumps({"books": reg, "pass": ok}, indent=1, default=str), encoding="utf-8")
        print("V4(a):", {p: (r["max_rel_diff"], r["decisions"]["mismatches"], r["pass"]) for p, r in reg.items()})
        sys.exit(0 if ok else 1)
    controls = (not a.quick) or a.controls
    r5 = a.r5 if a.r5 is not None else (20 if a.quick else N_R5)
    jobs = a.jobs if a.jobs is not None else (1 if len(books) == 1 else min(len(books), os.cpu_count() or 1))
    cfg = {"draws": a.draws, "controls": controls, "r5": r5, "v6_shifts": a.v6_shifts, "v6_draws": a.v6_draws, "check_sha": False, "v4b_dir": a.v4b_dir, "r6_ids": a.r6_ids}
    small = sampler_selftest()
    print(f"V5(a): {small['n_allowed_brute_force']} allowed subsets, chi2 {small['chi2']:.1f} df {small['df']} p {small['p']:.3f} pass {small['pass']}", flush=True)

    results = {}
    if jobs > 1:
        from concurrent.futures import ProcessPoolExecutor
        with ProcessPoolExecutor(max_workers=jobs) as ex:
            futs = {p: ex.submit(process_book, p, cfg) for p in books}
            for p, f in futs.items():
                results[p] = f.result()
                print(f"{p}: done in {results[p]['audit']['seconds']}s", flush=True)
    else:
        for p in books:
            results[p] = process_book(p, cfg)
            print(f"{p}: done in {results[p]['audit']['seconds']}s (core {results[p]['audit']['seconds_core']}s)", flush=True)
    for r in results.values():
        for k, v in r["usedfiles"].items():
            USED.setdefault(k, v)

    # ── write ──
    R = [results[p] for p in books]
    pd.concat([r["decisions"] for r in R]).to_csv(outdir / "decisions.csv", index=False)
    pd.DataFrame([x for r in R for x in r["events"]]).to_csv(outdir / "events.csv", index=False)
    es_df = pd.DataFrame([x for r in R for x in r["event_stocks"]])
    es_df.to_csv(outdir / "event_stocks.csv", index=False)
    stats_df = pd.DataFrame([x for r in R for x in r["stats"]])
    stats_df.to_csv(outdir / "stats.csv", index=False)
    pd.DataFrame([x for r in R for x in r["draws"]]).to_csv(outdir / "draws.csv", index=False)
    pd.DataFrame([x for r in R for x in r["trades"]]).to_csv(outdir / "trades.csv", index=False)
    pd.DataFrame([x for r in R for x in r["positions"]]).to_csv(outdir / "positions.csv", index=False)
    daily = []
    for r in R:
        for (b_, cost, name), nv in r["nav"].items():
            daily.append(pd.DataFrame({"book": b_, "date": r["cal_full"], "cost_bps": cost, "run": name, "nav": nv}))
    pd.concat(daily).to_csv(outdir / "daily_nav.csv", index=False)
    np.savez_compressed(outdir / "draw_drops.npz", **{k: v for r in R for k, v in r["drops"].items()})
    np.savez_compressed(outdir / "draw_labels.npz", **{k: v for r in R for k, v in r["labels"].items()})
    np.savez_compressed(outdir / "draw_curves_20.8.npz", **{k: v for r in R for k, v in r["curves"].items()})
    pd.DataFrame([x for r in R for x in r["r7_flagged"]], columns=["book", "isin", "stock", "date", "close_prev", "close", "move"]).to_csv(outdir / "r7_flagged_days.csv", index=False)
    pd.DataFrame([x for r in R for x in r["r6_links"]], columns=["book", "isin", "stock", "original_source", "linked_quote_id", "info_date", "linked_rank", "linked_band", "event_no"]
                 ).to_csv(outdir / "r6_links.csv", index=False)
    wins = lambda r: [w for w in ("full", "r2", "full_r6") if w in r["count_table"]]
    ct = {r["book"]: {**r["count_table"], "events_with_partial": {w: r["count_table"][w]["events_with_partial"] for w in wins(r)}} for r in R}
    (outdir / "count_table.json").write_text(json.dumps({"books": ct, "note": "n_allowed_subsets is the exact count of N4.6 subsets per event (string); weights are the renormalised listed weights in increasing ISIN order"}, indent=1), encoding="utf-8")
    (outdir / "sampler_selftest.json").write_text(json.dumps(small, indent=1, default=str), encoding="utf-8")

    # V4
    v4a = {r["book"]: r["v4a"] for r in R}
    v4a_ok = bool(all(x["pass"] for x in v4a.values()))
    v4b = {r["book"]: r["v4b"] for r in R}
    if not t11_seen or all(x["status"] == "not run" for x in v4b.values()):
        v4b_out = {"status": "not run", "reason": "tests/T11/evidence/headline/ does not exist when the run started", "books": v4b}
        v4b_ok = None
    else:
        v4b_out = {"status": "run", "books": v4b}
        v4b_ok = bool(all(x.get("pass", False) for x in v4b.values()))
        v4b_out["pass"] = v4b_ok
    if a.v4b_dir:                                       # testing only: never part of the gate
        v4b_out = {"status": "not run (gate)", "reason": "--v4b-dir given: comparison against a non-headline folder for testing", "test_comparison": v4b}
        v4b_ok = None
    v4c = shared_code_diff()
    v4d = v4d_direct_tags(es_df)
    v4_ok = bool(v4a_ok and v4c["pass"] and v4d["pass"] and (v4b_ok in (None, True)))
    reg = {"tolerance_rel": REL_TOL_NAV, "v4a": {"books": v4a, "max_rel_diff": float(max(x["max_rel_diff"] for x in v4a.values())), "pass": v4a_ok},
           "v4b": v4b_out, "v4c": v4c, "v4d": v4d, "pass": v4_ok}
    (outdir / "regression.json").write_text(json.dumps(reg, indent=1, default=str), encoding="utf-8")

    # controls
    v6_ok = v7_ok = None
    if controls:
        cr = [r["controls"] for r in R]
        pd.DataFrame([x for c in cr for x in c["v6_rows"]]).to_csv(outdir / "controls_negative.csv", index=False)
        v6 = {c["v6"]["book"]: c["v6"] for c in cr}
        v6_ok = bool(all(v["pass"] and v["v3_failures"] == 0 for v in v6.values()))
        (outdir / "controls_negative.json").write_text(json.dumps({"books": v6, "x_max": V6_XMAX_FROZEN, "pass": v6_ok}, indent=1, default=str), encoding="utf-8")
        v7 = {c["v7"]["book"]: c["v7"] for c in cr}
        v7_ok = bool(all(v["pass_ge_99"] for v in v7.values()))
        (outdir / "controls_oracle.json").write_text(json.dumps({"books": v7, "pass": v7_ok}, indent=1, default=str), encoding="utf-8")
    if r5 > 0:
        pd.DataFrame([x for r in R for x in r["r5"]]).to_csv(outdir / "r5_tag_error.csv", index=False)

    # V2, V3, V5 summaries
    v2 = {"decisions_checked": 0, "decision_label_after_decision": 0, "sc100_label_before_usable_from": 0, "tags_checked": 0, "tag_snapshot_after_info": 0, "events_checked": 0,
          "event_info_not_before_trade": 0, "event_decision_not_before_trade": 0, "decision_trades_checked": 0, "decision_trade_not_after_decision": 0,
          "initial_position_tag_reads_asof_T0": 0}
    for r in R:
        for w, wa in r["audit"]["windows"].items():
            x = wa["v2"]
            v2["decisions_checked"] += x["decisions_checked"]
            v2["decision_label_after_decision"] += x["decisions_label_after_decision"]
            v2["sc100_label_before_usable_from"] += x["sc100_label_before_usable_from"]
            v2["decision_trades_checked"] += x["decision_trades_checked"]
            v2["decision_trade_not_after_decision"] += x["decision_trade_not_after_decision"]
            for k in ("tags_checked", "tag_snapshot_after_info", "events_checked", "event_info_not_before_trade", "event_decision_not_before_trade", "initial_position_tag_reads_asof_T0"):
                v2[k] += x[k]
    v2["violations"] = int(v2["decision_label_after_decision"] + v2["sc100_label_before_usable_from"] + v2["tag_snapshot_after_info"] + v2["event_info_not_before_trade"]
                           + v2["event_decision_not_before_trade"] + v2["decision_trade_not_after_decision"])
    v2["checked"] = int(v2["decisions_checked"] + v2["tags_checked"] + v2["events_checked"] + v2["decision_trades_checked"])
    v2["pass"] = bool(v2["violations"] == 0 and v2["decisions_checked"] > 0 and v2["tags_checked"] > 0 and v2["events_checked"] > 0)
    v3 = {k: v for r in R for k, v in r["v3"].items()}
    v3_ok = bool(all(x["pass"] for w in v3.values() for x in w.values()))
    v5 = {"a_small_case": small, "b_count_equal": int(sum(r["v5"]["count_equal"] for r in R)), "b_count_unequal": int(sum(r["v5"]["count_unequal"] for r in R)),
          "c_rule_in_allowed": int(sum(r["v5"]["rule_in_allowed"] for r in R)), "events_checked": int(sum(r["v5"]["events"] for r in R))}
    v5["pass"] = bool(small["pass"] and v5["b_count_unequal"] == 0 and v5["c_rule_in_allowed"] == v5["events_checked"] > 0)
    (outdir / "v5_counts.json").write_text(json.dumps(v5, indent=1, default=str), encoding="utf-8")

    # Step 1 counts and the coarse bounds
    s1 = json.loads(STEP1.read_text(encoding="utf-8"))
    assert s1["T0"] == str(T0.date()) and s1["END"] == str(END.date()) and s1["calendar"] == "D26"
    cmp_, s1_ok = {}, True
    for r in R:
        p = r["book"]
        bk_s1 = s1["books"][p]
        for w in ("full", "r2"):
            mine = r["audit"]["windows"][w]
            coarse = bk_s1[w]
            row = {"engine_events_incl_T0": mine["events"]["events"], "engine_events_after_T0": mine["events"]["events"] - 1, "coarse_events_section2": coarse["events_coarse_upper_bound"],
                   "engine_le_coarse": bool(mine["events"]["events"] <= coarse["events_coarse_upper_bound"]),
                   "engine_events_in_disagreement_weeks": mine["events_in_disagreement_weeks"],
                   "engine_events_in_disagreement_weeks_step1_attribution": mine["events_in_disagreement_weeks_step1_attribution"],
                   "coarse_in_mixed_weeks": coarse["events_in_mixed_weeks"],
                   "engine_le_coarse_in_disagreement": bool(mine["events_in_disagreement_weeks_step1_attribution"] <= coarse["events_in_mixed_weeks"]),
                   "signal_events_without_a_change_of_the_triple": mine["signal_events_without_a_change_of_the_triple"],
                   "engine_partial_events": mine["events"]["partial"], "disagreement_stretches": mine["disagreement_stretches"], "step1_mixed_spells": coarse["mixed_spells"],
                   "stretch_lengths_equal_step1": bool(mine["stretch_lengths"] == coarse["mixed_spell_lengths"]),
                   "decisions_equal_step1": bool(mine["decisions"] == coarse["weeks"]), "patterns_equal_step1": bool(mine["pattern_counts"] == coarse["patterns_N100_MC100_SC100"]),
                   "reportable": mine["reportable"]}
            s1_ok &= row["stretch_lengths_equal_step1"] and row["decisions_equal_step1"] and row["patterns_equal_step1"]
            cmp_[f"{p}|{w}"] = row
    # unranked holdings at events against Step 1's two
    unr = {f"{r['book']}|{w}": sorted({x["isin"] for x in r["audit"]["windows"][w]["unranked_event_rows"]}) for r in R for w in r["audit"]["windows"]}
    c_ = common(END)
    audit = {"readings": READINGS, "books": {r["book"]: r["audit"] for r in R}, "v2": v2, "v3": {"per_book_window": v3, "pass": v3_ok},
             "v4": {"pass": v4_ok, "a_max_rel_diff": reg["v4a"]["max_rel_diff"], "a_pass": v4a_ok, "b": v4b_out.get("status"), "c_pass": v4c["pass"], "d_pass": v4d["pass"]},
             "v5": {"pass": v5["pass"]}, "events_vs_section2_coarse_counts": cmp_, "step1_counts_reproduced": bool(s1_ok),
             "unranked": {"isins_per_book_window": unr, "rows": {f"{r['book']}|{w}": r["audit"]["windows"][w]["unranked_event_rows"] for r in R for w in r["audit"]["windows"]}},
             "standins": {"no_d18_session": str(NO_D18_SESSION.date()), "no_goldbees_session": str(NO_GOLD_SESSION.date()), "books": {r["book"]: r["audit"]["standins"] for r in R}},
             "t11_headline_seen": t11_seen,
             "r6": {"ids": R6_IDS, "links": {b: {i: q for i, q in v.items()} for b, v in R6_LINKS.items()}, "re_tagged_event_rows": int(sum(len(r["r6_links"]) for r in R)),
                    "linked_quote_id_absent_on_snapshot": {r["book"]: r["audit"].get("r6_linked_quote_id_missing_on_snapshot") for r in R},
                    "note": READINGS["R6b"]},
             "data": {"approved_data_as_of": AD.as_of(), "window": [str(T0.date()), str(END.date())], "inputs": int(len(USED)), "registered_not_parsed": not_parsed, "non_approved_open_raises": st,
                      "cash_accrued_sessions": 0, "goldbees": {"mcx_file_last": str(c_["mcx_last"].date()), "goldbees_first": str(c_["gold_first"].date()),
                                                               "no_mcx_range_sessions_in_window": [str(d.date()) for d in c_["norange"] if T0 <= d <= END]},
                      "tag_membership_cutoff": str(load_taglookup().cutoff.date())},
             "tag_error_r5": {"rate": R5_RATE, "draws_per_book": r5, "source": "data/review/2026-11-12_tag_sources/REVIEW.md check 6: 92.07% agreement"},
             "run": {"name": a.run, "draws": a.draws, "quick": a.quick, "controls": controls, "jobs": jobs, "seconds": round(time.time() - t_start),
                     "seeds": "N4.6 default_rng([15, 7, draw_id, book_no]); N4.8 default_rng([15, 8, draw_id, book_no]); V6 [15, 9, 100000, book_no] / [15, 9, shift_index, book_no]; "
                              "R5 [15, 5, draw_id, book_no]; V5(a) [15, 7, 123456789, 99]"}}
    audit["prereg_sha256"] = (T12 / "T12.md").read_text(encoding="utf-8").split("§1–§3 sha256:** `")[1].split("`")[0]
    gates = {"V2": v2["pass"], "V3": v3_ok, "V4": v4_ok, "V5": v5["pass"], "V6": v6_ok, "V7": v7_ok, "approved_data_selftest": st["pass"], "step1_counts_reproduced": bool(s1_ok)}
    ran = [v for v in gates.values() if v is not None]
    gates["all_that_ran"] = bool(all(ran))
    gates["V6_V7_ran"] = bool(controls)
    audit["gates"] = gates
    (outdir / "audit.json").write_text(json.dumps(audit, indent=1, default=str), encoding="utf-8")
    # inputs last, so every file the workers opened is listed
    pd.DataFrame([{k: v.get(k) for k in ("file", "through", "bytes", "sha256", "approved_row", "usable_from")} for v in sorted(USED.values(), key=lambda x: x["file"])]).to_csv(outdir / "inputs.csv", index=False)

    print("events vs coarse (engine, bound, in-disagreement by state decision, by Step 1 attribution, bound, partial, stretches, reportable):",
          {k: (v["engine_events_incl_T0"], v["coarse_events_section2"], v["engine_events_in_disagreement_weeks"], v["engine_events_in_disagreement_weeks_step1_attribution"],
               v["coarse_in_mixed_weeks"], v["engine_partial_events"], v["disagreement_stretches"], v["reportable"]) for k, v in cmp_.items()})
    print(f"R6 ids: {R6_IDS} {R6_LINKS}; re-tagged event rows: {sum(len(r['r6_links']) for r in R)}; linked quote_id absent on the snapshot: "
          f"{ {r['book']: r['audit'].get('r6_linked_quote_id_missing_on_snapshot') for r in R} }")
    print("unranked at events:", unr)
    print(f"V2 {v2['pass']} ({v2['checked']} checked, {v2['violations']} violations)  V3 {v3_ok}  V4 {v4_ok} (a max rel diff {reg['v4a']['max_rel_diff']:.2e}; b {v4b_out['status']}; "
          f"c {v4c['pass']}; d {v4d['pass']} {v4d['rows_checked']} rows)  V5 {v5['pass']}  V6 {v6_ok}  V7 {v7_ok}")
    print(f"gates: {gates}")
    print(f"done in {time.time() - t_start:.0f}s -> {outdir}")
    sys.exit(0 if gates["all_that_ran"] else 1)


if __name__ == "__main__":
    main()
