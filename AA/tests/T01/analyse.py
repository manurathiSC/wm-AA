# -*- coding: utf-8 -*-
"""T01 analysis: score the gates, criteria and robustness checks pre-registered in T01.md §2.

Why it exists
    AGENT.md rule 4: numbers are generated, never typed. This script reads ONLY the shipped
    evidence of T01 and prints every table that §4 of T01.md is filled from, to stdout and to
    analysis.log beside this file.

What it reads (nothing else)
    evidence/headline/      sleeve 'gold_cash' (50/50 GOLDBEES / LBES of the non-equity part)
    evidence/cash_sleeve/   sleeve 'cash' (100% LBES of the non-equity part), robustness R4
        each with spliced_inputs.csv, realisations.csv, decisions_all_configs.csv,
        decisions_reference.csv, trades.csv, daily_reference.csv, audit.json
    verify_headline.json, verify_cash_sleeve.json   written by verify_own_momentum.py
        (plus any other verify_*.json in this folder, e.g. a corrupted-copy record)

What it prints, in order
    4.0  gates V1-V5, then the null check measured for R (AGENT.md §5.1 rule 4)
    4.1  the headline for R = pct_w65_q25 (weekly), before and after cost, with its null
    verdicts C1-C3, robustness R4-R7, hypotheses H1-H3, the outcome-map row
    multiplicity (best row vs the null of best rows), the descriptive sweep, per-year returns

The only constants below are the pre-registered thresholds and names of T01.md §2-§3. Every
result printed is computed from the evidence files.

Run from wm-research/:   python -X utf8 AA/tests/T01/analyse.py
                         python -X utf8 AA/tests/T01/analyse.py --root <a T01-shaped folder>
Exit codes: 0 = every gate passed and every table printed; 3 = a validity gate failed (every
table is still printed, marked unreadable); 2 = a required evidence file or column is missing,
or the evidence breaks the schema (nothing is scored).
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent

# ----------------------------------------------------------------------------------------------
# Pre-registered names and thresholds (T01.md §2-§3). Not results.
# ----------------------------------------------------------------------------------------------
RUNS = {"headline": "gold_cash", "cash_sleeve": "cash"}
WINDOWS = ["W1", "W2"]
N_BOOKS = 4
R = "pct_w65_q25"                       # T01.md's 'pct_w65_q25_weekly'
DAILY = "pct_w65_q25_daily"
NEIGHBOURS = ["pct_w40_q25", "pct_w130_q25", "pct_w65_q10", "pct_w65_q40"]
PCT_GRID = [f"pct_w{w}_q{q}" for w in (20, 40, 65, 130, 250) for q in (10, 25, 40)]
SWEEP = PCT_GRID + ["pct_w65_hyst", "pct_w65_step", DAILY,
                    "sma_50", "sma_100", "sma_200", "tsmom_65", "tsmom_130", "tsmom_250",
                    "ddhigh_250_x7p5", "ddhigh_250_x10", "ddhigh_250_x15", "st_weekly"]
DESCRIPTIVE = ["triple", "triple_and_pct25"]
ALL_CONFIGS = SWEEP + DESCRIPTIVE
SWEEP_WEEKLY = [c for c in SWEEP if c != DAILY]
assert len(SWEEP) == 28 and len(ALL_CONFIGS) == 30 and len(SWEEP_WEEKLY) == 27

C1_PCT = 90.0            # C1: after-cost CAGR percentile >= 90 ...
NEED_BOOKS = 3           # ... in >= 3 of 4 books, each window
C2_PP = 5.0              # C2: max DD at least 5.0 pp shallower than B&H
R6_PCT = 75.0            # R6: neighbours' after-cost percentile >= 75
REP_MIN_SWITCHES = 4     # reportability: fewer than 4 switches -> NOT REPORTABLE
REP_SHARE_LO, REP_SHARE_HI = 0.05, 0.95   # ... or < 5% / > 95% of weeks in the sleeve
MDE_MULT = 2.8           # MDE = 2.8 x null_sd
V3_MAX_GAP = 2           # V3: |switches(draw) - switches(strategy)| <= 2
V4_TOL = 1e-12           # V4: max |diff| < 1e-12
V5_TOL = 1e-9            # V5: within 1e-9
K_MIN = {"weekly": 8, "daily": 40}   # null offsets: k_min <= k <= n+1-k_min
TIE_TOL = 1e-12          # percentile ties: |draw - strategy| <= 1e-12 x max(1, |strategy|)

KEY = ["config", "book", "window", "cost_bps"]
FILES = {
    "spliced_inputs.csv": ["date", "P_SCMO_0003", "P_SCMO_0007", "P_SCMO_0010", "P_SCMO_0029",
                           "gold", "cash"],
    "realisations.csv": ["config", "book", "parent", "window", "cost_bps", "sleeve", "kind",
                         "shift_k", "cagr", "total_return", "nav_end", "max_dd", "vol", "sharpe",
                         "calmar", "share_sleeve_weeks", "avg_equity_weight", "n_switches",
                         "n_spells", "n_decisions", "target_level_counts", "observed_se"],
    "decisions_all_configs.csv": ["config", "book", "window", "decision_date", "value",
                                  "equity_target", "data_last_date", "trade_session", "traded"],
    "decisions_reference.csv": ["config", "book", "window", "decision_date", "value",
                                "equity_target", "data_last_date", "trade_session", "traded"],
    "trades.csv": ["config", "book", "window", "cost_bps", "sleeve", "decision_date",
                   "trade_session", "kind", "from_equity", "to_equity", "nav_before",
                   "nav_after", "value_traded_frac"],
    "daily_reference.csv": ["date", "book", "window", "cost_bps", "nav", "nav_bh", "w_equity",
                            "w_gold", "w_cash"],
    "audit.json": None,
}
VERIFY = {"headline": "verify_headline.json", "cash_sleeve": "verify_cash_sleeve.json"}

INTERPRETATIONS = [
    "Percentile = (draws worse + 0.5 x draws equal) / draws x 100 (§2). 'Equal' is "
    "|draw - strategy| <= 1e-12 x max(1, |strategy|), not bit equality: a draw and the strategy "
    "that are both fully invested through the same equity fall have the same drawdown in exact "
    "arithmetic but differ by float noise, and bit equality would put such draws on either side "
    "at random. The percentile under bit equality is computed too, and the script prints how many "
    "realisations it would move and by how much.",
    "null_sd = sample SD (ddof = 1) of after-cost CAGR across the realisation's draws; "
    "MDE = 2.8 x null_sd (§3 step 11).",
    "A book whose config-book-window is NOT REPORTABLE (fewer than 4 switches, or share of "
    "decision sessions in the sleeve < 0.05 or > 0.95) cannot count towards a percentile "
    "criterion (C1, R4, R5, R6, R7-C1): its percentile may not be quoted, so it is counted as "
    "not meeting the threshold; the denominator stays 4. The count ignoring reportability is "
    "printed beside it. C2, C3 and R7-C2 compare with B&H, not with the null, so the "
    "reportability gate does not apply to them.",
    "Reportability is judged per row (config x book x window x cost x sleeve) from that row's "
    "own n_switches and share_sleeve_weeks; these are cost- and sleeve-independent by "
    "construction, and the script prints whether they actually are.",
    "C2: (strategy max_dd - B&H max_dd) x 100 >= 5.0, both negative fractions, after cost. "
    "C3: strategy Calmar > B&H Calmar, strictly. B&H is the 'bh' row (no cost).",
    "R6 passes only if each of the four neighbours separately reaches percentile >= 75 in >= 3 of "
    "4 books in W1 and in W2. Each neighbour's own verdict is printed too.",
    "R7 applies C1 and C2 exactly as written to pct_w65_q25_daily (headline run, after cost).",
    "Multiplicity: the daily config is rotated in sessions, so its offsets k do not align with "
    "the weekly configs' offsets (k weeks). It is EXCLUDED from both the best row and the null "
    "of best rows; the best row is the best of the 27 weekly-rotated sweep configs, ranked "
    "against max-over-27-configs after-cost CAGR at each offset k present for all 27. The daily "
    "config's own CAGR and percentile are printed beside it, flagged when it beats the weekly "
    "best. T01.md says 'all 28 configs shifted by the same k', which cannot be applied as written "
    "(the daily config's k is in sessions and its null has no draw below k = 40), so the literal "
    "version is printed beside as a sensitivity: the best of all 28 against the max of all 28 at "
    "the same numeric k, over the offsets where all 28 have a draw.",
    "V1 is read from verify_headline.json and verify_cash_sleeve.json (verify_own_momentum.py's "
    "report): mode 'verify', verdict PASS, every check passed having compared rows, and total "
    "failures, missing rows and extra rows all 0; plus the verifier's --corrupt-test report "
    "verify_<run>_corrupt.json (else any verify_*_corrupt.json: one corrupted-copy test checks "
    "the checker, whichever run it copied): corrupted-copy verdict FAIL and every planted defect "
    "detected. Without a corrupted-copy report V1 is FAIL (unconfirmed), as the gate requires "
    "it. A report written under one of the verifier's diagnostic switches "
    "(diagnostic_reading_not_predeclared not False) cannot pass V1; the readings the verifier used, "
    "and any reading it changed after the evidence existed, are printed. Whether null rows were "
    "checked (not required by V1) is printed. A report in any other shape is read generically: a "
    "pass flag or exit code 0, rows compared > 0, failures 0.",
    "V3 also requires the null grid to be complete: every k with k_min <= k <= n+1-k_min must be "
    "present (n+1 = the realisation's decision count in decisions_all_configs.csv), because the "
    "gate is stated for every draw.",
    "Target-level multisets are compared as parsed JSON (levels rounded to 4 decimals, zero "
    "counts dropped), not as raw strings, so key order cannot fail a draw.",
    "Per-year returns: NAV at the year's last session / NAV at the previous year's last session "
    "(the first year from T0) - 1, from daily_reference.csv; first and last years are partial and "
    "printed with their dates.",
]


class EvidenceError(Exception):
    """A required file or column is missing, or the evidence breaks its schema."""


class Tee:
    def __init__(self, path: Path):
        self.f = open(path, "w", encoding="utf-8", newline="\n")
        self.out = sys.stdout

    def write(self, s):
        self.out.write(s)
        self.f.write(s)

    def flush(self):
        self.out.flush()
        self.f.flush()

    def close(self):
        self.f.close()


# ----------------------------------------------------------------------------------------------
# formatting
# ----------------------------------------------------------------------------------------------
def isna(x) -> bool:
    try:
        return x is None or bool(pd.isna(x))
    except (TypeError, ValueError):
        return False


def P(x, d=2):            # fraction -> %
    return "—" if isna(x) else f"{float(x) * 100:.{d}f}%"


def SP(x, d=2):           # fraction -> signed %
    return "—" if isna(x) else f"{float(x) * 100:+.{d}f}%"


def PP(x, d=2):           # already in pp, signed
    return "—" if isna(x) else f"{float(x):+.{d}f}"


def F(x, d=2):
    return "—" if isna(x) else f"{float(x):.{d}f}"


def PC(x):
    return "—" if isna(x) else f"{float(x):.1f}"


def I(x):
    return "—" if isna(x) else f"{int(round(float(x)))}"


def E(x):
    return "—" if isna(x) else f"{float(x):.3e}"


def short(book: str) -> str:
    return str(book).replace("SCMO_", "")


def table(header, rows, align=None):
    print("| " + " | ".join(header) + " |")
    print("|" + "|".join(align or (["---"] * 1 + ["--:"] * (len(header) - 1))) + "|")
    for r in rows:
        print("| " + " | ".join(str(c) for c in r) + " |")


STATE = {"gates_ok": True}


def section(title: str):
    print()
    print("=" * 100)
    tag = "" if STATE["gates_ok"] else "   [UNREADABLE — a validity gate failed]"
    print(title + tag)
    print("=" * 100)


def sub(title: str):
    tag = "" if STATE["gates_ok"] else "   [UNREADABLE]"
    print(f"\n--- {title}{tag}")


# ----------------------------------------------------------------------------------------------
# loading, with loud failures
# ----------------------------------------------------------------------------------------------
def check_files(root: Path) -> None:
    missing = []
    for run in RUNS:
        for f in FILES:
            p = root / "evidence" / run / f
            if not p.exists():
                missing.append(str(p))
        p = root / VERIFY[run]
        if not p.exists():
            missing.append(str(p))
    if missing:
        raise EvidenceError("missing evidence file(s):\n  " + "\n  ".join(missing))


def read_csv(path: Path, need: list[str], **kw) -> pd.DataFrame:
    if not path.exists():
        raise EvidenceError(f"missing file: {path}")
    head = pd.read_csv(path, nrows=0)
    miss = [c for c in need if c not in head.columns]
    if miss:
        raise EvidenceError(f"{path}: missing column(s) {miss}; it has {list(head.columns)}")
    # only an empty cell is missing: pandas' default NA list contains 'null', which is a
    # value of realisations.csv's `kind` column
    kw.setdefault("keep_default_na", False)
    kw.setdefault("na_values", [""])
    return pd.read_csv(path, **kw)


def read_json(path: Path) -> dict:
    if not path.exists():
        raise EvidenceError(f"missing file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def need_key(d: dict, key: str, where: str):
    if not isinstance(d, dict) or key not in d:
        raise EvidenceError(f"{where}: missing key '{key}'")
    return d[key]


def norm_cost(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="raise").astype(float).round(6)


def load_run(root: Path, run: str) -> dict:
    d = root / "evidence" / run
    for f, cols in FILES.items():               # header check of every CSV in the contract
        if cols is not None:
            read_csv(d / f, cols, nrows=0)
    rz = read_csv(d / "realisations.csv", FILES["realisations.csv"],
                  dtype={"config": str, "book": str, "parent": str, "window": str,
                         "sleeve": str, "kind": str, "target_level_counts": str})
    rz["cost_bps"] = norm_cost(rz["cost_bps"])
    for c in ["cagr", "total_return", "nav_end", "max_dd", "vol", "sharpe", "calmar",
              "share_sleeve_weeks", "avg_equity_weight", "n_switches", "n_spells",
              "n_decisions", "observed_se", "shift_k"]:
        rz[c] = pd.to_numeric(rz[c], errors="raise")
    kinds = set(rz["kind"].dropna().unique())
    if not kinds <= {"strategy", "null", "bh"}:
        raise EvidenceError(f"{run}/realisations.csv: unexpected kind values {kinds}")
    strat = rz[rz.kind == "strategy"].copy()
    nul = rz[rz.kind == "null"].copy()
    bh = rz[rz.kind == "bh"].copy()
    if strat.empty or nul.empty or bh.empty:
        raise EvidenceError(f"{run}/realisations.csv: needs strategy, null and bh rows "
                            f"(found {len(strat)}, {len(nul)}, {len(bh)})")
    if nul["shift_k"].isna().any():
        raise EvidenceError(f"{run}/realisations.csv: null rows with empty shift_k")
    nul["shift_k"] = nul["shift_k"].astype(int)
    for nm, frame, key in (("strategy", strat, KEY), ("null", nul, KEY + ["shift_k"]),
                           ("bh", bh, ["book", "window"])):
        dup = frame.duplicated(key).sum()
        if dup:
            raise EvidenceError(f"{run}/realisations.csv: {dup} duplicate {nm} rows on {key}")
    bad_sleeve = set(pd.concat([strat, nul]).sleeve.unique()) - {RUNS[run]}
    if bad_sleeve:
        raise EvidenceError(f"{run}/realisations.csv: sleeve {bad_sleeve}, expected "
                            f"'{RUNS[run]}'")
    costs = sorted(strat.cost_bps.unique())
    if len(costs) != 2 or costs[0] != 0.0:
        raise EvidenceError(f"{run}: expected two cost levels, the lower 0; found {costs}")
    books = sorted(strat.book.unique())
    if len(books) != N_BOOKS:
        raise EvidenceError(f"{run}: expected {N_BOOKS} books, found {books}")
    wins = sorted(strat.window.unique())
    if wins != WINDOWS:
        raise EvidenceError(f"{run}: expected windows {WINDOWS}, found {wins}")
    have = set(map(tuple, strat[KEY].itertuples(index=False, name=None)))
    want = {(c, b, w, k) for c in ALL_CONFIGS for b in books for w in WINDOWS for k in costs}
    miss = sorted(want - have)
    if miss:
        raise EvidenceError(f"{run}: {len(miss)} strategy realisation(s) missing, e.g. "
                            f"{miss[:5]}")
    extra = sorted(set(strat.config.unique()) - set(ALL_CONFIGS))
    bh_have = set(map(tuple, bh[["book", "window"]].itertuples(index=False, name=None)))
    bh_miss = sorted({(b, w) for b in books for w in WINDOWS} - bh_have)
    if bh_miss:
        raise EvidenceError(f"{run}: bh rows missing for {bh_miss}")
    parent = strat.drop_duplicates("book").set_index("book")["parent"].to_dict()

    dec = read_csv(d / "decisions_all_configs.csv", ["config", "book", "window",
                                                    "decision_date", "equity_target"],
                   usecols=["config", "book", "window", "decision_date", "equity_target"],
                   dtype={"config": str, "book": str, "window": str, "decision_date": str})
    ref = read_csv(d / "decisions_reference.csv", ["config"], usecols=["config"],
                   dtype={"config": str})
    dr = read_csv(d / "daily_reference.csv", FILES["daily_reference.csv"],
                  dtype={"book": str, "window": str})
    dr["cost_bps"] = norm_cost(dr["cost_bps"])
    dr["date"] = pd.to_datetime(dr["date"], errors="raise")
    audit = read_json(d / "audit.json")
    return dict(run=run, rz=rz, strat=strat, nul=nul, bh=bh, costs=costs, books=books,
                parent=parent, extra=extra, dec=dec, ref=ref, dr=dr, audit=audit)


# ----------------------------------------------------------------------------------------------
# statistics
# ----------------------------------------------------------------------------------------------
def canon_levels(s) -> tuple | None:
    if isna(s):
        return None
    d = json.loads(s)
    return tuple(sorted((round(float(k), 4), int(v)) for k, v in d.items() if int(v) != 0))


def canon_series(s: pd.Series) -> pd.Series:
    u = {v: canon_levels(v) for v in s.dropna().unique()}
    return s.map(lambda v: u.get(v) if not isna(v) else None)


def pct_table(strat: pd.DataFrame, nul: pd.DataFrame, stat: str, higher_better: bool):
    """Per realisation: (draws worse + 0.5 x equal) / draws x 100 on `stat`.

    'Equal' is |draw - strategy| <= 1e-12 x max(1, |strategy|): values that are equal in exact
    arithmetic (e.g. the same equity fall seen fully invested by both) differ by float noise,
    and exact equality would put them on either side at random. The exact-equality percentile
    is kept beside it so the effect of the tolerance can be printed."""
    s = strat[KEY + [stat]].rename(columns={stat: "_s"})
    m = nul[KEY + [stat]].merge(s, on=KEY, how="inner")
    x = m[stat].to_numpy(float)
    y = m["_s"].to_numpy(float)
    with np.errstate(invalid="ignore"):
        tie = (x == y) | (np.abs(x - y) <= TIE_TOL * np.maximum(1.0, np.abs(y)))
        worse_raw = (x < y) if higher_better else (x > y)
    exact = x == y
    worse = worse_raw & ~tie
    near = tie & ~exact
    nan = np.isnan(x) | np.isnan(y)
    m = m.assign(_w=worse, _t=tie, _wr=worse_raw, _x=exact, _n=near, _nan=nan)
    g = m.groupby(KEY)
    n = g.size()
    return pd.DataFrame({"pct": (g["_w"].sum() + 0.5 * g["_t"].sum()) / n * 100,
                         "pct_exact": (g["_wr"].sum() + 0.5 * g["_x"].sum()) / n * 100,
                         "ties": g["_t"].sum(), "near_ties": g["_n"].sum(),
                         "nan": g["_nan"].sum()})


SECONDARY = [("cagr", True), ("max_dd", True), ("vol", False), ("sharpe", True),
             ("calmar", True)]


def build_table(D: dict) -> pd.DataFrame:
    strat, nul, bh = D["strat"], D["nul"], D["bh"]
    g = nul.groupby(KEY)
    ns = pd.DataFrame({"null_median": g["cagr"].median(), "null_sd": g["cagr"].std(ddof=1),
                       "null_min": g["cagr"].min(), "null_max": g["cagr"].max(),
                       "n_draws": g.size(),
                       "null_share_min": g["share_sleeve_weeks"].min(),
                       "null_share_max": g["share_sleeve_weeks"].max(),
                       "null_avgeq_min": g["avg_equity_weight"].min(),
                       "null_avgeq_max": g["avg_equity_weight"].max(),
                       "null_sw_min": g["n_switches"].min(),
                       "null_sw_med": g["n_switches"].median(),
                       "null_sw_max": g["n_switches"].max(),
                       "null_sp_min": g["n_spells"].min(),
                       "null_sp_max": g["n_spells"].max()})
    T = strat.set_index(KEY).join(ns)
    D["tie_notes"] = {}
    for stat, hb in SECONDARY:
        p = pct_table(strat, nul, stat, hb)
        T[f"pct_{stat}"] = p["pct"]
        moved = (p["pct"] - p["pct_exact"]).abs()
        D["tie_notes"][stat] = (int(p["ties"].sum()), int(p["near_ties"].sum()),
                                int(p["nan"].sum()), int((moved > 0).sum()),
                                float(moved.max()) if len(moved) else 0.0)
    T = T.reset_index()
    b = bh.set_index(["book", "window"])[["cagr", "total_return", "max_dd", "vol", "sharpe",
                                          "calmar"]].add_prefix("bh_").reset_index()
    T = T.merge(b, on=["book", "window"], how="left")
    T["cagr_bh_pp"] = (T.cagr - T.bh_cagr) * 100
    T["edge_pp"] = (T.cagr - T.null_median) * 100
    T["null_sd_pp"] = T.null_sd * 100
    T["mde_pp"] = MDE_MULT * T.null_sd_pp
    T["obs_se_pp"] = T.observed_se * 100
    T["sd_ratio"] = np.where(T.observed_se > 0, T.null_sd / T.observed_se, np.nan)
    T["dd_diff_pp"] = (T.max_dd - T.bh_max_dd) * 100      # > 0: shallower than B&H
    T["reportable"] = ~((T.n_switches < REP_MIN_SWITCHES) | (T.share_sleeve_weeks < REP_SHARE_LO)
                        | (T.share_sleeve_weeks > REP_SHARE_HI))
    return T


def n_decisions_map(dec: pd.DataFrame) -> pd.Series:
    return dec.groupby(["config", "book", "window"]).size()


def v3_check(D: dict, ndec: pd.Series) -> pd.DataFrame:
    strat, nul = D["strat"], D["nul"]
    s = strat[KEY + ["target_level_counts", "n_switches"]].copy()
    s["lev_s"] = canon_series(s["target_level_counts"])
    s = s.rename(columns={"n_switches": "sw_s"}).drop(columns="target_level_counts")
    m = nul[KEY + ["shift_k", "target_level_counts", "n_switches"]].merge(
        s, on=KEY, how="left", indicator=True)
    orphans = int((m["_merge"] != "both").sum())
    if orphans:
        raise EvidenceError(f"{D['run']}: {orphans} null rows have no strategy row")
    lev = canon_series(m["target_level_counts"])
    m["lev_ok"] = [a is not None and a == b for a, b in zip(lev, m["lev_s"])]
    m["gap"] = (m["n_switches"] - m["sw_s"]).abs()
    m["sw_ok"] = m["gap"] <= V3_MAX_GAP
    g = m.groupby(KEY)
    out = pd.DataFrame({"draws": g.size(), "lev_fail": g["lev_ok"].apply(lambda x: int((~x).sum())),
                        "sw_fail": g["sw_ok"].apply(lambda x: int((~x).sum())),
                        "max_gap": g["gap"].max()})
    ks = g["shift_k"].apply(lambda x: frozenset(x.tolist()))
    grid_ok, expected = [], []
    for key, have in ks.items():
        cfg, book, win, _ = key
        kmin = K_MIN["daily"] if cfg == DAILY else K_MIN["weekly"]
        n1 = ndec.get((cfg, book, win))
        if n1 is None:
            grid_ok.append(False)
            expected.append(np.nan)
            continue
        want = frozenset(range(kmin, int(n1) - kmin + 1))
        grid_ok.append(have == want)
        expected.append(len(want))
    out["grid_ok"] = grid_ok
    out["draws_expected"] = expected
    # strategy realisations with no draws at all
    allkeys = strat.set_index(KEY).index
    out = out.reindex(allkeys)
    out["grid_ok"] = out["grid_ok"].fillna(False).astype(bool)
    out["draws"] = out["draws"].fillna(0)
    return out.reset_index()


# ----------------------------------------------------------------------------------------------
# V1 reader: the verifier's JSON format is not fixed by the spec, so read it defensively
# ----------------------------------------------------------------------------------------------
PASS_KEYS = {"pass", "passed", "all_match", "all_pass", "all_passed", "ok", "all_ok", "success",
             "match", "all_agree"}
CORRUPT_WORDS = ("corrupt", "tamper", "negative_control", "mutat", "sabotag", "planted")


def flatten(obj, prefix=""):
    out = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.update(flatten(v, f"{prefix}{k}."))
    elif isinstance(obj, list):
        out[prefix[:-1]] = ("__list__", len(obj))
    else:
        out[prefix[:-1]] = obj
    return out


def is_num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


NOT_A_COUNT = ("tol", "threshold", "limit", "allowed", "max_rel", "max_abs", "rel_diff",
               "abs_diff")


def read_verdict(items: dict):
    """-> (pass_flags, exit_codes, compared, failed) from flattened items.

    A count is an integer leaf whose key path names it ('compared' / 'checked' for rows
    compared, 'fail' / 'mismatch' for failures); tolerances and diffs are never counts."""
    pf, ec, cmp_, fl = [], [], [], []
    for k, v in items.items():
        path = k.lower()
        last = path.split(".")[-1]
        if any(w in path for w in NOT_A_COUNT):
            continue
        if last in PASS_KEYS and isinstance(v, bool):
            pf.append((k, v))
        if "exit" in last and is_num(v):
            ec.append((k, int(v)))
        if ("compared" in path or "checked" in path) and isinstance(v, int) \
                and not isinstance(v, bool):
            cmp_.append((k, v))
        if ("fail" in path or "mismatch" in path) and not isinstance(v, bool):
            if isinstance(v, int):
                fl.append((k, v))
            elif isinstance(v, tuple) and v and v[0] == "__list__":
                fl.append((k, v[1]))
    return pf, ec, cmp_, fl


def corrupt_detected(items: dict):
    """True / False / None (cannot tell): did the verifier reject the corrupted copy?"""
    if not items:
        return None
    pf, ec, _, fl = read_verdict(items)
    for k, v in items.items():
        last = k.split(".")[-1].lower()
        if any(w in last for w in ("detect", "caught", "nonzero", "non_zero", "rejected",
                                   "as_expected", "flagged")) and isinstance(v, bool):
            return v
    if ec:
        return all(c != 0 for _, c in ec)
    if fl:
        return sum(v for _, v in fl) > 0
    if pf:
        return not all(v for _, v in pf)
    return None


def corrupt_record(root: Path, run: str):
    """The verifier's --corrupt-test report: verify_<run>_corrupt.json, else any
    verify_*_corrupt.json (one corrupted-copy test checks the checker, whichever run it used)."""
    own = root / f"verify_{run}_corrupt.json"
    cands = [own] if own.exists() else sorted(root.glob("verify_*_corrupt.json"))
    for p in cands:
        c = read_json(p)
        if isinstance(c, dict) and c.get("mode") == "corrupt-test":
            planted = c.get("planted") or []
            n_det = sum(1 for x in planted if isinstance(x, dict) and x.get("detected") is True)
            ok = (str(c.get("verdict", "")).startswith("PASS")
                  and c.get("corrupted_copy_verdict") == "FAIL"
                  and len(planted) > 0 and n_det == len(planted))
            return ok, dict(src=p.name, verdict=c.get("verdict"),
                            copy_verdict=c.get("corrupted_copy_verdict"),
                            planted=len(planted), detected=n_det,
                            source=c.get("source_run_dir"))
    return None, None


def v1_gate(root: Path, run: str):
    path = root / VERIFY[run]
    v = read_json(path)
    if isinstance(v, dict) and "checks" in v and "verdict" in v and isinstance(v["checks"], dict):
        return v1_gate_known(root, run, path, v)
    flat = flatten(v)
    corr = {k: x for k, x in flat.items() if any(w in k.lower() for w in CORRUPT_WORDS)}
    main = {k: x for k, x in flat.items() if k not in corr}
    pf, ec, cmp_, fl = read_verdict(main)
    det = corrupt_detected(corr)
    corr_src = path.name if corr else None
    if det is None:      # a separate corrupted-copy record, if the verifier writes one
        extra = sorted(p for p in root.glob("verify_*.json")
                       if p.name not in VERIFY.values()
                       and any(w in p.name.lower() for w in CORRUPT_WORDS)
                       and (run in p.name or not any(r in p.name for r in RUNS)))
        for p in extra:
            d2 = corrupt_detected(flatten(read_json(p)))
            if d2 is not None:
                det, corr_src = d2, p.name
                break
    if pf:
        flag_ok = all(x for _, x in pf)
    elif ec:
        flag_ok = all(c == 0 for _, c in ec)
    else:
        flag_ok = None
    n_cmp = sum(x for _, x in cmp_)
    n_fail = sum(x for _, x in fl)
    reasons = []
    if flag_ok is None:
        reasons.append("no pass flag or exit code found")
    elif not flag_ok:
        reasons.append("verifier reports failure")
    if n_cmp <= 0:
        reasons.append("no rows compared")
    if n_fail > 0:
        reasons.append(f"{n_fail:g} failures")
    if det is None:
        reasons.append("corrupted-copy run not recorded (unconfirmed)")
    elif not det:
        reasons.append("corrupted copy was NOT rejected")
    ok = not reasons
    return ok, dict(kind="generic", path=path.name, pass_flags=pf, exit_codes=ec, compared=cmp_,
                    failed=fl, n_cmp=n_cmp, n_fail=n_fail, corrupt=det, corrupt_src=corr_src,
                    corrupt_items=corr, reasons=reasons,
                    scalars={k: x for k, x in main.items() if "." not in k})


def v1_gate_known(root: Path, run: str, path: Path, v: dict):
    """verify_own_momentum.py's report: verdict, checks{name: compared / failures / missing_rows /
    extra_rows / passed}, totals; plus its --corrupt-test report."""
    rows, reasons = [], []
    for name, c in v["checks"].items():
        rows.append([name, I(c.get("compared")), I(c.get("failures")), I(c.get("missing_rows")),
                     I(c.get("extra_rows")), "PASS" if c.get("passed") else "FAIL"])
        if not c.get("passed") or not c.get("compared"):
            reasons.append(f"check {name} did not pass")
    tot = {k: v.get(k) for k in ("total_compared", "total_failures", "total_missing_rows",
                                 "total_extra_rows")}
    if v.get("mode") != "verify":
        reasons.append(f"mode is {v.get('mode')!r}, not 'verify'")
    if v.get("verdict") != "PASS":
        reasons.append(f"verdict {v.get('verdict')!r}")
    if not tot["total_compared"]:
        reasons.append("no rows compared")
    for k in ("total_failures", "total_missing_rows", "total_extra_rows"):
        if tot[k] is None or tot[k] != 0:
            reasons.append(f"{k} = {tot[k]}")
    if v.get("every_check_compared_rows") is not True:
        reasons.append("not every check compared rows")
    if v.get("sleeve") is not None and v.get("sleeve") != RUNS[run]:
        reasons.append(f"verified sleeve {v.get('sleeve')!r}, expected {RUNS[run]!r}")
    # the verifier's diagnostic switches are never part of the gate (its docstring): a report
    # written under one cannot pass V1
    if v.get("diagnostic_reading_not_predeclared") is not False:
        reasons.append("the verifier report was written under a diagnostic reading "
                       f"(diagnostic_reading_not_predeclared = "
                       f"{v.get('diagnostic_reading_not_predeclared')!r})")
    cok, cinfo = corrupt_record(root, run)
    if cok is None:
        reasons.append("no corrupted-copy report (verify_*_corrupt.json) found (unconfirmed)")
    elif not cok:
        reasons.append("the corrupted-copy test did not detect every planted defect")
    readings = {k: v.get(k) for k in ("sleeve_price_carry_reading_used",
                                      "st_weekly_midweek_reading_used",
                                      "diagnostic_reading_not_predeclared")}
    changed = v.get("readings_changed_after_evidence") or []
    return not reasons, dict(kind="known", path=path.name, rows=rows, tot=tot,
                             nulls_checked=v.get("nulls_checked"),
                             every=v.get("every_check_compared_rows"), verdict=v.get("verdict"),
                             corrupt_ok=cok, corrupt=cinfo, reasons=reasons,
                             readings=readings, changed=changed)


def leaf_sum(x, where: str):
    """A count that may be an int or a dict / list of ints."""
    if is_num(x):
        return float(x)
    if isinstance(x, dict):
        return sum(leaf_sum(v, where) for v in x.values()
                   if is_num(v) or isinstance(v, (dict, list)))
    if isinstance(x, list):
        return sum(leaf_sum(v, where) for v in x if is_num(v) or isinstance(v, (dict, list)))
    raise EvidenceError(f"{where}: cannot read a count from {x!r}")


def bh_tieout_rows(t, where: str):
    """-> list of (book, engine, published, absdiff) from audit['bh_tieout_W2']."""
    items = []
    if isinstance(t, dict):
        for k, v in t.items():
            if isinstance(v, dict):
                items.append((k, v))
    elif isinstance(t, list):
        for v in t:
            if isinstance(v, dict):
                b = next((v[c] for c in ("book", "scid", "parent") if c in v), None)
                items.append((b, v))
    if not items:
        raise EvidenceError(f"{where}: no per-book entries in bh_tieout_W2: {t!r}")
    rows = []
    for book, v in items:
        num = {k: x for k, x in v.items() if is_num(x)}
        diff_k = next((k for k in num if "diff" in k.lower()), None)
        eng_k = next((k for k in num if "engine" in k.lower() and k != diff_k), None)
        pub_k = next((k for k in num if ("publish" in k.lower() or "parent" in k.lower())
                      and k not in (diff_k, eng_k)), None)
        eng = num.get(eng_k) if eng_k else np.nan
        pub = num.get(pub_k) if pub_k else np.nan
        if diff_k is not None:
            dif = abs(num[diff_k])
        elif not isna(eng) and not isna(pub):
            dif = abs(eng - pub)
        else:
            raise EvidenceError(f"{where}: bh_tieout_W2[{book}] has no readable diff: {v!r}")
        rows.append((str(book), eng, pub, dif))
    return rows


# ----------------------------------------------------------------------------------------------
# criteria
# ----------------------------------------------------------------------------------------------
def judge(T, config, cost, test, need=NEED_BOOKS):
    res = {}
    for w in WINDOWS:
        s = T[(T.config == config) & (T.cost_bps == cost) & (T.window == w)].sort_values("book")
        if len(s) != N_BOOKS:
            raise EvidenceError(f"{config} {w} {cost}: {len(s)} books, expected {N_BOOKS}")
        ok = s.apply(test, axis=1).astype(bool)
        res[w] = (int(ok.sum()), s, ok)
    a, b = res["W1"][0] >= need, res["W2"][0] >= need
    verdict = ("PASS" if a and b else "FAIL — passes W1 only" if a else
               "FAIL — passes W2 only" if b else "FAIL")
    return verdict, res


def pct_test(thr):
    return lambda r: bool(r.reportable) and (not isna(r.pct_cagr)) and r.pct_cagr >= thr


def pct_test_raw(thr):
    return lambda r: (not isna(r.pct_cagr)) and r.pct_cagr >= thr


def c2_test(r):
    return (not isna(r.dd_diff_pp)) and r.dd_diff_pp >= C2_PP


def c3_test(r):
    return (not isna(r.calmar)) and (not isna(r.bh_calmar)) and r.calmar > r.bh_calmar


def detail_pct(res, raw_res=None):
    out = []
    for w in WINDOWS:
        n, s, ok = res[w]
        cells = []
        for (_, r), o in zip(s.iterrows(), ok):
            cells.append(f"{short(r.book)} {PC(r.pct_cagr)}"
                         + ("" if r.reportable else " (NOT REPORTABLE)")
                         + (" ✓" if o else ""))
        extra = f"; ignoring reportability {raw_res[w][0]} of {N_BOOKS}" if raw_res else ""
        out.append(f"    {w}: {n} of {N_BOOKS}{extra} — " + ", ".join(cells))
    return out


def mde_line(res):
    parts = []
    for w in WINDOWS:
        _, s, _ = res[w]
        parts.append(f"{w} " + ", ".join(f"{short(r.book)} {F(r.mde_pp)}" for _, r in s.iterrows()))
    return "    MDE (pp of CAGR, 2.8 × null_sd): " + "; ".join(parts)


# ----------------------------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------------------------
def main(root: Path) -> int:
    check_files(root)
    DS = {run: load_run(root, run) for run in RUNS}
    H = DS["headline"]
    C0, CA = H["costs"]
    for run, D in DS.items():
        if D["costs"] != H["costs"]:
            raise EvidenceError(f"{run}: cost levels {D['costs']} differ from headline "
                                f"{H['costs']}")
    ndec = {run: n_decisions_map(D["dec"]) for run, D in DS.items()}
    TT = {run: build_table(D) for run, D in DS.items()}
    V3 = {run: v3_check(D, ndec[run]) for run, D in DS.items()}

    print("T01 analysis — every number below is computed from the shipped evidence")
    print(f"root: {root}")
    for run, D in DS.items():
        a = D["audit"]
        print(f"  evidence/{run}: sleeve '{RUNS[run]}', {len(D['strat'])} strategy rows, "
              f"{len(D['nul'])} null rows, {len(D['bh'])} bh rows; cost levels "
              + " / ".join(f"{c:g} bps" for c in D["costs"])
              + (f"; purpose: {a['purpose']}" if isinstance(a, dict) and "purpose" in a else ""))
        if D["extra"]:
            print(f"    configs not in the pre-registered list (ignored): {D['extra']}")
    print("\nAnalysis interpretations (choices this script makes where §2 leaves room):")
    for i, s in enumerate(INTERPRETATIONS, 1):
        print(f"  A{i}. {s}")
    ai = H["audit"].get("interpretations") if isinstance(H["audit"], dict) else None
    if ai:
        print("\nEngine interpretations (audit.json, headline):")
        for i, s in enumerate(ai, 1):
            print(f"  E{i}. {s}")
    cv = H["audit"].get("caveats") if isinstance(H["audit"], dict) else None
    if cv:
        print("\nEngine caveats (audit.json, headline):")
        for s in (cv if isinstance(cv, list) else [cv]):
            print(f"  - {s}")

    # ============================================================ 4.0 gates
    gates: dict[str, bool] = {}
    section("4.0 VALIDITY GATES (T01.md §2) — if any fails, nothing below may be read")

    print("\nV1  independent check verify_own_momentum.py (from verify_*.json)")
    ok1 = True
    for run in RUNS:
        ok, info = v1_gate(root, run)
        ok1 &= ok
        if info["kind"] == "known":
            t = info["tot"]
            print(f"  {run}: {info['path']} verdict {info['verdict']}; total compared "
                  f"{I(t['total_compared'])}, failures {I(t['total_failures'])}, missing rows "
                  f"{I(t['total_missing_rows'])}, extra rows {I(t['total_extra_rows'])}; every "
                  f"check compared rows: {info['every']}; null rows checked: "
                  f"{info['nulls_checked']}")
            table(["check", "compared", "failures", "missing", "extra", "result"], info["rows"],
                  ["---", "--:", "--:", "--:", "--:", "---"])
            rd = info["readings"]
            print(f"  verifier readings: sleeve carry {rd['sleeve_price_carry_reading_used']!r}; "
                  f"st_weekly mid-week {rd['st_weekly_midweek_reading_used']!r}; diagnostic run "
                  f"{rd['diagnostic_reading_not_predeclared']!r}")
            for ch in info["changed"]:
                if isinstance(ch, dict):
                    print(f"  reading changed after the evidence existed ({ch.get('date')}, by "
                          f"{ch.get('by')}): {ch.get('reading')}: pre-declared "
                          f"{ch.get('predeclared_by_verifier')!r} -> adopted {ch.get('adopted')!r}. "
                          f"Reason: {ch.get('reason')} Effect: {ch.get('effect')}")
            c = info["corrupt"]
            if c:
                print(f"  corrupted copy ({c['src']}, source {c['source']}): copy verdict "
                      f"{c['copy_verdict']}; planted defects detected {c['detected']} of "
                      f"{c['planted']}; report verdict {c['verdict']}")
            else:
                print("  corrupted copy: no verify_*_corrupt.json report found")
            print(f"  -> {'PASS' if ok else 'FAIL: ' + '; '.join(info['reasons'])}")
            continue
        pf = ", ".join(f"{k}={v}" for k, v in info["pass_flags"]) or "—"
        ec = ", ".join(f"{k}={v}" for k, v in info["exit_codes"]) or "—"
        cm = ", ".join(f"{k}={v:g}" for k, v in info["compared"]) or "—"
        fl = ", ".join(f"{k}={v:g}" for k, v in info["failed"]) or "—"
        cr = {True: "rejected by the verifier", False: "NOT rejected",
              None: "not recorded"}[info["corrupt"]]
        print(f"  {run:11s} {info['path']}: pass flags [{pf}]; exit codes [{ec}]")
        print(f"              rows compared [{cm}] (total {info['n_cmp']:g}); failures [{fl}] "
              f"(total {info['n_fail']:g})")
        print(f"              corrupted copy: {cr}"
              + (f" (from {info['corrupt_src']})" if info["corrupt_src"] else "")
              + (": " + ", ".join(f"{k}={v}" for k, v in info["corrupt_items"].items())
                 if info["corrupt_items"] else ""))
        print(f"              -> {'PASS' if ok else 'FAIL: ' + '; '.join(info['reasons'])}")
    gates["V1"] = ok1

    print("\nV2  point in time (audit.json point_in_time)")
    ok2 = True
    for run, D in DS.items():
        pit = need_key(D["audit"], "point_in_time", f"{run}/audit.json")
        chk = leaf_sum(need_key(pit, "checks", f"{run}/audit.json point_in_time"), run)
        vio = leaf_sum(need_key(pit, "violations", f"{run}/audit.json point_in_time"), run)
        ok = chk > 0 and vio == 0
        ok2 &= ok
        print(f"  {run:11s} rule: {pit.get('rule', '—')}")
        print(f"              checks {chk:g} {json.dumps(pit['checks']) if not is_num(pit['checks']) else ''}"
              f"; violations {vio:g} -> {'PASS' if ok else 'FAIL'}")
        bc = pit.get("by_check")
        if isinstance(bc, dict):
            for k, v in bc.items():
                print(f"                {k}: {json.dumps(v)}")
    gates["V2"] = ok2

    print("\nV3  the null holds what the table says: every draw has the strategy's target-level "
          f"counts, |switch gap| <= {V3_MAX_GAP}, and the k grid is complete")
    ok3 = True
    for run, v in V3.items():
        draws = int(v.draws.sum())
        lev = int(v.lev_fail.fillna(0).sum())
        sw = int(v.sw_fail.fillna(0).sum())
        grid_bad = int((~v.grid_ok).sum())
        mg = v.max_gap.max()
        ok = draws > 0 and lev == 0 and sw == 0 and grid_bad == 0
        ok3 &= ok
        print(f"  {run:11s} realisations {len(v)} ({v.config.nunique()} configs × books × "
              f"windows × costs); draws checked {draws}; levels differ in {lev}; "
              f"|switch gap| > {V3_MAX_GAP} in {sw} (max gap {I(mg)}); incomplete k grid in "
              f"{grid_bad} of {len(v)} -> {'PASS' if ok else 'FAIL'}")
        if grid_bad:
            bad = v[~v.grid_ok].head(5)
            for _, r in bad.iterrows():
                print(f"              e.g. {r.config} {r.book} {r.window} {r.cost_bps:g}bps: "
                      f"{I(r.draws)} draws, expected {I(r.draws_expected)}")
        if lev or sw:
            bad = v[(v.lev_fail.fillna(0) > 0) | (v.sw_fail.fillna(0) > 0)].head(5)
            for _, r in bad.iterrows():
                print(f"              e.g. {r.config} {r.book} {r.window} {r.cost_bps:g}bps: "
                      f"levels differ {I(r.lev_fail)}, switch gap > {V3_MAX_GAP} "
                      f"{I(r.sw_fail)} of {I(r.draws)}")
    gates["V3"] = ok3

    print(f"\nV4  splice (audit.json splice_check): max |diff| < {V4_TOL:g} on both sides")
    ok4 = True
    for run, D in DS.items():
        sc = need_key(D["audit"], "splice_check", f"{run}/audit.json")
        hs = float(need_key(sc, "max_abs_diff_harness_side", f"{run} splice_check"))
        ps = float(need_key(sc, "max_abs_diff_published_side", f"{run} splice_check"))
        nc = leaf_sum(need_key(sc, "n_compared", f"{run} splice_check"), run)
        ok = hs < V4_TOL and ps < V4_TOL and nc > 0
        ok4 &= ok
        print(f"  {run:11s} harness side {E(hs)}; published side {E(ps)}; compared {nc:g} "
              f"-> {'PASS' if ok else 'FAIL'}")
    gates["V4"] = ok4

    print(f"\nV5  B&H ties out in W2 (audit.json bh_tieout_W2): |diff| <= {V5_TOL:g}; "
          "realisations.csv 'bh' total_return shown beside it")
    ok5 = True
    for run, D in DS.items():
        t = need_key(D["audit"], "bh_tieout_W2", f"{run}/audit.json")
        rows = bh_tieout_rows(t, f"{run}/audit.json")
        spans = {str(k): f"{v.get('from', '?')} → {v.get('to', '?')}" for k, v in t.items()
                 if isinstance(v, dict)} if isinstance(t, dict) else {}
        bhw2 = D["bh"][D["bh"].window == "W2"].set_index("book")["total_return"]
        out = []
        books_seen = set()
        for book, eng, pub, dif in rows:
            ok = (not isna(dif)) and dif <= V5_TOL
            ok5 &= ok
            books_seen.add(book)
            rz = bhw2.get(book, np.nan)
            out.append([run, book, spans.get(book, "—"), F(eng, 10), F(pub, 10), E(dif),
                        F(rz, 10),
                        E(abs(rz - eng)) if not isna(rz) and not isna(eng) else "—",
                        "PASS" if ok else "FAIL"])
        if len(rows) < N_BOOKS:
            ok5 = False
            out.append([run, f"only {len(rows)} books", "", "", "", "", "", "", "FAIL"])
        table(["run", "book", "dates", "engine B&H TR", "published TR", "|diff|",
               "realisations bh TR",
               "|rz − engine|", "gate"], out)
    gates["V5"] = ok5

    print("\nGATES: " + "  ".join(f"{k} {'PASS' if v else 'FAIL'}" for k, v in gates.items()))
    if not all(gates.values()):
        STATE["gates_ok"] = False
        print("GATE FAILED — nothing below may be read")
    else:
        print("All validity gates pass.")

    # ------------------------------------------------------------ schema and cross-layer notes
    section("Schema and cross-layer identity (not pre-registered gates; printed so they can be seen)")
    for run, D in DS.items():
        T = TT[run]
        s = D["strat"]
        inv = s.groupby(["config", "book", "window"])[["n_switches", "share_sleeve_weeks",
                                                       "target_level_counts"]].nunique()
        n_var = int((inv.max(axis=1) > 1).sum())
        dec = D["dec"]
        nd = ndec[run]
        nd_rz = s.groupby(["config", "book", "window"])["n_decisions"].first()
        both = nd_rz.to_frame("rz").join(nd.rename("dec"), how="left")
        nd_mis = int((both.rz != both.dec).sum())
        # strategy target-level counts vs the decision log
        dc = dec.assign(lv=dec.equity_target.astype(float).round(4)) \
            .groupby(["config", "book", "window", "lv"]).size()
        dlev = {k: tuple(sorted((lv, int(c)) for (*_, lv), c in g.items()))
                for k, g in dc.groupby(level=[0, 1, 2])}
        slev = s.drop_duplicates(["config", "book", "window"]).set_index(
            ["config", "book", "window"])["target_level_counts"].map(canon_levels)
        lev_agree = sum(1 for k, v in slev.items() if dlev.get(k) == v)
        nref = int((dec.config == R).sum())
        print(f"  {run:11s} decision-independent columns vary across cost levels in {n_var} of "
              f"{len(inv)} config-book-windows; n_decisions vs rows in decisions_all_configs.csv "
              f"disagree in {nd_mis} of {len(both)}; strategy target_level_counts equal the "
              f"decision log's equity_target counts in {lev_agree} of {len(slev)}; "
              f"decisions_reference.csv rows {len(D['ref'])} vs {nref} {R} rows in the whole log "
              f"({'same' if len(D['ref']) == nref else 'DIFFERENT'})")
        # daily_reference end vs realisations
        dr = D["dr"]
        last = dr.sort_values("date").groupby(["book", "window", "cost_bps"]).last()
        rr = T[T.config == R].set_index(["book", "window", "cost_bps"])
        j = last.join(rr[["nav_end", "bh_total_return"]], how="inner")
        d_nav = (j.nav / j.nav_end - 1).abs().max()
        d_bh = (j.nav_bh / (1 + j.bh_total_return) - 1).abs().max()
        first = dr.sort_values("date").groupby(["book", "window", "cost_bps"]).first()
        print(f"              daily_reference.csv ({len(j)} {R} realisations): max rel |final nav "
              f"/ nav_end − 1| {E(d_nav)}; max rel |final nav_bh / (1 + B&H TR) − 1| {E(d_bh)}; "
              f"first-row nav range {F(first.nav.min(), 6)}–{F(first.nav.max(), 6)}")
        tn = D["tie_notes"]
        print("              percentile ties, per statistic: tied draws (within 1e-12) / of "
              "which not bit-equal / NaN comparisons / realisations whose percentile bit "
              "equality would move / largest move (pct points)")
        print("              " + "; ".join(f"{k} {a}/{b}/{c}/{d}/{F(e, 1)}"
                                         for k, (a, b, c, d, e) in tn.items()))

    # ------------------------------------------------------------ null check measured
    section(f"4.0b NULL CHECK MEASURED for R = {R} (AGENT.md §5.1 rule 4): strategy vs its draws")
    print("Held: share of decision sessions in the sleeve and the target levels (must be identical).")
    print("Not matched: the switch count (wrap point) and what the sleeve earned (null spread).")
    for run in RUNS:
        T = TT[run]
        v = V3[run].set_index(KEY)
        sub(f"run {run} (sleeve {RUNS[run]})")
        rows = []
        for w in WINDOWS:
            for c in (C0, CA):
                for _, r in T[(T.config == R) & (T.window == w) & (T.cost_bps == c)] \
                        .sort_values("book").iterrows():
                    vv = v.loc[(R, r.book, w, c)]
                    rows.append([w, short(r.book), f"{c:g}", F(r.share_sleeve_weeks, 4),
                                 f"{F(r.null_share_min, 4)}–{F(r.null_share_max, 4)}",
                                 f"{I(vv.draws - vv.lev_fail)} of {I(vv.draws)}",
                                 F(r.avg_equity_weight, 4),
                                 f"{F(r.null_avgeq_min, 4)}–{F(r.null_avgeq_max, 4)}",
                                 I(r.n_switches),
                                 f"{I(r.null_sw_min)} / {F(r.null_sw_med, 1)} / {I(r.null_sw_max)}",
                                 I(vv.max_gap), I(r.n_spells),
                                 f"{I(r.null_sp_min)}–{I(r.null_sp_max)}",
                                 F(r.null_sd_pp), f"{SP(r.null_min)} / {SP(r.null_max)}"])
        table(["win", "book", "bps", "share sleeve", "null share min–max", "levels identical",
               "avg eq wt", "null avg eq min–max", "switches", "null sw min / med / max",
               "max |gap|", "spells", "null spells", "null_sd CAGR (pp)", "null CAGR min / max"],
              rows)

    # ------------------------------------------------------------ 4.1 headline
    T = TT["headline"]
    section(f"4.1 HEADLINE — R = {R} (weekly), run headline (sleeve {RUNS['headline']}), "
            f"{C0:g} and {CA:g} bps")
    print("Percentile = (draws below + 0.5 × equal) / draws × 100 on CAGR, against the "
          "realisation's own circular-shift draws.")

    def headline_tables(T, run_label):
        rowsA, rowsB = [], []
        for w in WINDOWS:
            for _, r in T[(T.config == R) & (T.window == w)].sort_values(["book", "cost_bps"]) \
                    .iterrows():
                lab = f"{r.book} ({r.parent})"
                rowsA.append([w, lab, f"{r.cost_bps:g}", P(r.cagr), P(r.bh_cagr),
                              PP(r.cagr_bh_pp), P(r.null_median), PP(r.edge_pp),
                              PC(r.pct_cagr), F(r.null_sd_pp), F(r.mde_pp), F(r.obs_se_pp),
                              F(r.sd_ratio), I(r.n_draws),
                              "yes" if r.reportable else "NOT REPORTABLE"])
                rowsB.append([w, short(r.book), f"{r.cost_bps:g}", SP(r.max_dd), SP(r.bh_max_dd),
                              PP(r.dd_diff_pp), F(r.calmar), F(r.bh_calmar),
                              ">" if (not isna(r.calmar) and r.calmar > r.bh_calmar) else "≤",
                              PC(r.pct_max_dd), PC(r.pct_vol), PC(r.pct_sharpe),
                              PC(r.pct_calmar), P(r.vol), F(r.sharpe), P(r.bh_vol),
                              F(r.bh_sharpe), F(r.share_sleeve_weeks, 3),
                              F(r.avg_equity_weight, 3), I(r.n_switches), I(r.n_spells)])
        sub(f"{run_label}: return against the null")
        table(["win", "book (parent)", "bps", "CAGR", "B&H CAGR", "CAGR − B&H (pp)",
               "null median", "edge (pp)", "pct CAGR", "null_sd (pp)", "MDE (pp)",
               "observed_se (pp)", "null_sd / obs_se", "draws", "reportable"], rowsA)
        sub(f"{run_label}: risk, against B&H and with secondary percentiles vs the same draws "
            "(max DD: shallower better; vol: lower better)")
        table(["win", "book", "bps", "max DD", "B&H max DD", "DD − B&H (pp, + shallower)",
               "Calmar", "B&H Calmar", "vs B&H", "pct maxDD", "pct vol", "pct Sharpe", "pct Calmar",
               "vol", "Sharpe", "B&H vol", "B&H Sharpe", "share sleeve", "avg eq wt",
               "switches", "spells"], rowsB)

    headline_tables(T, "headline")

    # ------------------------------------------------------------ reportability
    section("REPORTABILITY GATE (§2): NOT REPORTABLE if switches < 4, or share in the sleeve "
            "< 0.05 or > 0.95")
    shown = None
    for run in RUNS:
        Tr = TT[run]
        nr = Tr[~Tr.reportable]
        print(f"  {run}: {len(nr)} of {len(Tr)} strategy rows NOT REPORTABLE")
        keys = sorted(map(tuple, nr[["config", "window", "book", "cost_bps"]]
                          .itertuples(index=False, name=None)))
        if shown is not None and keys == shown:
            print(f"    the same config-book-window-cost rows as {next(iter(RUNS))} "
                  "(reportability is sleeve-independent)")
            continue
        shown = keys
        if len(nr):
            g = nr.groupby(["config", "window", "book"]).agg(
                costs=("cost_bps", lambda x: "/".join(f"{c:g}" for c in sorted(x))),
                sw=("n_switches", "first"), sh=("share_sleeve_weeks", "first"))
            rows = [[c, w, short(b), r.costs, I(r.sw), F(r.sh, 3)] for (c, w, b), r in g.iterrows()]
            table(["config", "window", "book", "cost levels", "switches", "share sleeve"], rows)

    # ------------------------------------------------------------ verdicts
    section("VERDICTS — pre-registered criteria (config R, after cost, 50/50 sleeve, each window "
            "judged separately, 4 books per window)")
    vC1, rC1 = judge(T, R, CA, pct_test(C1_PCT))
    _, rC1raw = judge(T, R, CA, pct_test_raw(C1_PCT))
    vC2, rC2 = judge(T, R, CA, c2_test)
    vC3, rC3 = judge(T, R, CA, c3_test)
    crit_text = {
        "C1": f"Timing (H1): after-cost CAGR percentile vs its circular-shift null ≥ {C1_PCT:g} in "
              f"≥ {NEED_BOOKS} of {N_BOOKS} books in W1 and in ≥ {NEED_BOOKS} of {N_BOOKS} books "
              "in W2",
        "C2": f"Protection (H2): daily maximum drawdown, after cost, at least {C2_PP:.1f} pp "
              f"shallower than B&H in ≥ {NEED_BOOKS} of {N_BOOKS} books in W1 and in W2",
        "C3": f"Risk-adjusted (H3): after-cost Calmar > B&H Calmar in ≥ {NEED_BOOKS} of {N_BOOKS} "
              "books in W1 and in W2",
    }
    rows = []
    for nm, v, res in (("C1", vC1, rC1), ("C2", vC2, rC2), ("C3", vC3, rC3)):
        mde = ""
        if nm == "C1" and v != "PASS":
            mde = "see MDE line below"
        elif v != "PASS":
            mde = "none pre-registered (comparison with B&H, not with the null)"
        rows.append([nm, crit_text[nm], f"{res['W1'][0]} of {N_BOOKS}",
                     f"{res['W2'][0]} of {N_BOOKS}", f"**{v}**", mde])
    table(["#", "criterion", "W1", "W2", "verdict", "MDE beside FAIL"], rows,
          ["---", "---", "--:", "--:", "---", "---"])
    print("\nC1 per book (after-cost CAGR percentile; ✓ = counts):")
    for ln in detail_pct(rC1, rC1raw):
        print(ln)
    if vC1 != "PASS":
        print(mde_line(rC1))
    print("C2 per book (DD − B&H, pp; ✓ = ≥ threshold):")
    for w in WINDOWS:
        _, s, ok = rC2[w]
        print(f"    {w}: " + ", ".join(f"{short(r.book)} {PP(r.dd_diff_pp)}" + (" ✓" if o else "")
                                     for (_, r), o in zip(s.iterrows(), ok)))
    print("C3 per book (Calmar vs B&H Calmar; ✓ = strictly greater):")
    for w in WINDOWS:
        _, s, ok = rC3[w]
        print(f"    {w}: " + ", ".join(f"{short(r.book)} {F(r.calmar)} vs {F(r.bh_calmar)}"
                                     + (" ✓" if o else "") for (_, r), o in zip(s.iterrows(), ok)))

    # ------------------------------------------------------------ robustness
    section("ROBUSTNESS — pre-registered; reported, they decide a finding's status, not the verdicts")
    TC = TT["cash_sleeve"]
    vR4, rR4 = judge(TC, R, CA, pct_test(C1_PCT))
    _, rR4raw = judge(TC, R, CA, pct_test_raw(C1_PCT))
    vR5, rR5 = judge(T, R, C0, pct_test(C1_PCT))
    _, rR5raw = judge(T, R, C0, pct_test_raw(C1_PCT))
    r6 = {}
    for nb in NEIGHBOURS:
        r6[nb] = (judge(T, nb, CA, pct_test(R6_PCT)), judge(T, nb, CA, pct_test_raw(R6_PCT)))
    vR6 = "PASS" if all(x[0][0] == "PASS" for x in r6.values()) else "FAIL"
    vR7a, rR7a = judge(T, DAILY, CA, pct_test(C1_PCT))
    _, rR7araw = judge(T, DAILY, CA, pct_test_raw(C1_PCT))
    vR7b, rR7b = judge(T, DAILY, CA, c2_test)
    rows = [["R4", f"C1 with a 100% LBES sleeve (cash_sleeve run), {CA:g} bps",
             f"{rR4['W1'][0]} of {N_BOOKS}", f"{rR4['W2'][0]} of {N_BOOKS}", f"**{vR4}**"],
            ["R5", f"C1 before cost ({C0:g} bps), headline run",
             f"{rR5['W1'][0]} of {N_BOOKS}", f"{rR5['W2'][0]} of {N_BOOKS}", f"**{vR5}**"]]
    for nb, ((v, res), _) in r6.items():
        rows.append([f"R6 {nb}", f"after-cost percentile ≥ {R6_PCT:g} in ≥ {NEED_BOOKS} of "
                     f"{N_BOOKS} books in each window", f"{res['W1'][0]} of {N_BOOKS}",
                     f"{res['W2'][0]} of {N_BOOKS}", v])
    rows.append(["R6", "all four neighbours of R pass", "", "", f"**{vR6}**"])
    rows.append(["R7 C1", f"C1 applied to {DAILY}", f"{rR7a['W1'][0]} of {N_BOOKS}",
                 f"{rR7a['W2'][0]} of {N_BOOKS}", f"**{vR7a}**"])
    rows.append(["R7 C2", f"C2 applied to {DAILY}", f"{rR7b['W1'][0]} of {N_BOOKS}",
                 f"{rR7b['W2'][0]} of {N_BOOKS}", f"**{vR7b}**"])
    table(["#", "check", "W1", "W2", "verdict"], rows, ["---", "---", "--:", "--:", "---"])
    print("\nR4 per book (cash sleeve, after-cost CAGR percentile):")
    for ln in detail_pct(rR4, rR4raw):
        print(ln)
    if vR4 != "PASS":
        print(mde_line(rR4))
    print("R5 per book (before cost):")
    for ln in detail_pct(rR5, rR5raw):
        print(ln)
    if vR5 != "PASS":
        print(mde_line(rR5))
    for nb, ((v, res), (_, raw)) in r6.items():
        print(f"R6 {nb}:")
        for ln in detail_pct(res, raw):
            print(ln)
        if v != "PASS":
            print(mde_line(res))
    print(f"R7 {DAILY} C1:")
    for ln in detail_pct(rR7a, rR7araw):
        print(ln)
    if vR7a != "PASS":
        print(mde_line(rR7a))
    print(f"R7 {DAILY} C2 (DD − B&H, pp):")
    for w in WINDOWS:
        _, s, ok = rR7b[w]
        print(f"    {w}: " + ", ".join(f"{short(r.book)} {PP(r.dd_diff_pp)}" + (" ✓" if o else "")
                                     for (_, r), o in zip(s.iterrows(), ok)))
    headline_tables(TC, "R4 cash_sleeve run, R")
    sub(f"R7 {DAILY}, headline run")
    rows = []
    for w in WINDOWS:
        for _, r in T[(T.config == DAILY) & (T.window == w)].sort_values(["book", "cost_bps"]) \
                .iterrows():
            rows.append([w, short(r.book), f"{r.cost_bps:g}", P(r.cagr), P(r.bh_cagr),
                         P(r.null_median), PP(r.edge_pp), PC(r.pct_cagr), F(r.mde_pp),
                         F(r.sd_ratio), I(r.n_draws), SP(r.max_dd), PP(r.dd_diff_pp),
                         F(r.calmar), F(r.share_sleeve_weeks, 3), I(r.n_switches),
                         "yes" if r.reportable else "NOT REPORTABLE"])
    table(["win", "book", "bps", "CAGR", "B&H CAGR", "null median", "edge (pp)", "pct CAGR",
           "MDE (pp)", "null_sd / obs_se", "draws", "max DD", "DD − B&H (pp)", "Calmar",
           "share sleeve", "switches", "reportable"], rows)

    # ------------------------------------------------------------ hypotheses
    section("HYPOTHESES (R, after cost, 50/50 sleeve)")
    hyp = [("H1", "timing", "C1", vC1), ("H2", "protection", "C2", vC2),
           ("H3", "risk-adjusted", "C3", vC3)]
    table(["hypothesis", "", "criterion", "criterion verdict", "hypothesis"],
          [[h, nm, c, v, "**NOT FALSIFIED**" if v == "PASS" else "**FALSIFIED**"]
           for h, nm, c, v in hyp], ["---", "---", "---", "---", "---"])
    if not STATE["gates_ok"]:
        pattern = "V-gate fails"
    elif vC1 in ("FAIL — passes W1 only", "FAIL — passes W2 only"):
        pattern = "C1 PASS in one window only"
    elif vC1 == "PASS" and vC2 == "PASS":
        pattern = "C1 PASS, C2 PASS"
    elif vC1 == "FAIL" and vC2 == "PASS":
        pattern = "C1 FAIL, C2 PASS"
    elif vC1 == "FAIL" and vC2 != "PASS":
        pattern = "C1 FAIL, C2 FAIL"
    else:
        pattern = f"not in the pre-registered outcome map (C1 {vC1}, C2 {vC2})"
    print(f"\nOutcome-map row (T01.md §2): {pattern}")

    # ------------------------------------------------------------ multiplicity
    section(f"MULTIPLICITY — best of the {len(SWEEP_WEEKLY)} weekly-rotated sweep configs vs the "
            f"null of best rows (headline, {CA:g} bps)")
    print(f"{DAILY} is excluded from the best row and its null: it is rotated in sessions, so its "
          "offsets do not align with the weekly offsets (interpretation A8). It is shown beside.")
    H_nul = H["nul"]
    rows = []
    for w in WINDOWS:
        for b in H["books"]:
            nb_ = H_nul[(H_nul.cost_bps == CA) & (H_nul.window == w) & (H_nul.book == b)
                        & (H_nul.config.isin(SWEEP_WEEKLY))]
            piv = nb_.pivot(index="shift_k", columns="config", values="cagr")
            missing_cfg = sorted(set(SWEEP_WEEKLY) - set(piv.columns))
            if missing_cfg:
                raise EvidenceError(f"multiplicity {w} {b}: no draws for {missing_cfg}")
            n_all = len(piv)
            piv = piv.dropna()
            best_null = piv.max(axis=1).to_numpy(float)
            st = T[(T.cost_bps == CA) & (T.window == w) & (T.book == b)
                   & (T.config.isin(SWEEP_WEEKLY))].set_index("config")
            bc = st.cagr.idxmax()
            bv = float(st.cagr.max())
            tie = np.abs(best_null - bv) <= TIE_TOL * max(1.0, abs(bv))
            pct = (((best_null < bv) & ~tie).sum() + 0.5 * tie.sum()) / len(best_null) * 100
            dl = T[(T.cost_bps == CA) & (T.window == w) & (T.book == b) & (T.config == DAILY)] \
                .iloc[0]
            # sensitivity, the literal text ("all 28 configs shifted by the same k"): the daily
            # config joins at the same NUMERIC k (sessions), so only the offsets where all 28
            # have a draw are used (the daily null starts at k = 40)
            dn = H_nul[(H_nul.cost_bps == CA) & (H_nul.window == w) & (H_nul.book == b)
                       & (H_nul.config == DAILY)].set_index("shift_k")["cagr"]
            k28 = piv.index.intersection(dn.index)
            b28 = np.maximum(piv.loc[k28].max(axis=1).to_numpy(float),
                             dn.loc[k28].to_numpy(float))
            bv28 = max(bv, float(dl.cagr))
            bc28 = DAILY if float(dl.cagr) > bv else bc
            tie28 = np.abs(b28 - bv28) <= TIE_TOL * max(1.0, abs(bv28))
            pct28 = ((((b28 < bv28) & ~tie28).sum() + 0.5 * tie28.sum()) / len(b28) * 100
                     if len(b28) else np.nan)
            rows.append([w, short(b), bc, P(bv), PC(st.loc[bc, "pct_cagr"]),
                         "yes" if st.loc[bc, "reportable"] else "NOT REPORTABLE",
                         P(np.median(best_null)), F(np.std(best_null, ddof=1) * 100),
                         PC(pct), f"{len(best_null)} of {n_all}",
                         f"{P(dl.cagr)} (pct {PC(dl.pct_cagr)})"
                         + (" — beats the weekly best" if dl.cagr > bv else ""),
                         f"{PC(pct28)} (best {bc28}; k {int(k28.min()) if len(k28) else '—'}–"
                         f"{int(k28.max()) if len(k28) else '—'}, {len(k28)} offsets)"])
    table(["win", "book", "best config", "its CAGR", "its own pct", "reportable",
           "null-of-best median", "null-of-best sd (pp)", "pct vs null of best",
           "offsets used (all 27 present)", f"{DAILY} CAGR",
           "sensitivity: pct vs null of best of all 28 at the same numeric k"], rows)

    # ------------------------------------------------------------ descriptive sweep
    section(f"DESCRIPTIVE SWEEP — every config, headline run, after cost ({CA:g} bps); "
            "no claims")
    for w in WINDOWS:
        for b in H["books"]:
            sub(f"{w} {b} ({H['parent'].get(b, '')})")
            s = T[(T.cost_bps == CA) & (T.window == w) & (T.book == b)].set_index("config") \
                .loc[ALL_CONFIGS]
            rows = []
            for cfg, r in s.iterrows():
                nm = f"**{cfg}**" if cfg == R else cfg + (" (descriptive)" if cfg in DESCRIPTIVE else "")
                rows.append([nm, P(r.cagr), SP(r.max_dd), F(r.calmar), PC(r.pct_cagr),
                             PP(r.edge_pp), F(r.sd_ratio), F(r.share_sleeve_weeks, 3),
                             I(r.n_switches), I(r.n_spells),
                             "yes" if r.reportable else "NOT REPORTABLE"])
            bh = s.iloc[0]
            rows.append(["B&H (no cost)", P(bh.bh_cagr), SP(bh.bh_max_dd), F(bh.bh_calmar),
                         "", "", "", "", "", "", ""])
            table(["config", "CAGR", "max DD", "Calmar", "pct CAGR", "edge (pp)",
                   "null_sd / obs_se", "share sleeve", "switches", "spells", "reportable"], rows)

    sub(f"Sweep summary across books, after cost: books with pct ≥ {C1_PCT:g} (reportable) and "
        "median pct, per window")
    rows = []
    for cfg in ALL_CONFIGS:
        row = [cfg]
        for w in WINDOWS:
            s = T[(T.cost_bps == CA) & (T.window == w) & (T.config == cfg)]
            k = int(((s.pct_cagr >= C1_PCT) & s.reportable).sum())
            row += [f"{k} of {len(s)}", PC(s.pct_cagr.median()), f"{int(s.reportable.sum())}",
                    PP(s.edge_pp.median())]
        rows.append(row)
    table(["config"] + [f"{w} {x}" for w in WINDOWS for x in
                        (f"pct≥{C1_PCT:g}", "median pct", "reportable", "median edge (pp)")], rows)

    sub("Distinct realisations: distinct weekly target series among the sweep configs "
        "(decisions_all_configs.csv)")
    dec = H["dec"].sort_values(["config", "book", "window", "decision_date"])
    rows = []
    for w in WINDOWS:
        for b in H["books"]:
            d = dec[(dec.window == w) & (dec.book == b) & (dec.config.isin(SWEEP_WEEKLY))]
            seqs = d.groupby("config")["equity_target"].apply(
                lambda x: tuple(np.round(x.astype(float).to_numpy(), 4)))
            rows.append([w, short(b), f"{seqs.nunique()} of {len(seqs)}"])
    table(["win", "book", "distinct target series (27 weekly sweep configs)"], rows)

    # ------------------------------------------------------------ per-year
    section(f"PER-YEAR RETURNS — R = {R} vs B&H, headline run (daily_reference.csv); descriptive")
    dr = H["dr"]
    for w in WINDOWS:
        for b in H["books"]:
            sub(f"{w} {b}")
            yrs = {}
            for c in (C0, CA):
                g = dr[(dr.window == w) & (dr.book == b) & (dr.cost_bps == c)].sort_values("date")
                if g.empty:
                    raise EvidenceError(f"daily_reference.csv: no rows for {w} {b} {c:g} bps")
                yrs[c] = g
            rows = []
            gA, g0 = yrs[CA], yrs[C0]
            base_d = gA.date.iloc[0]
            baseA, base0, baseB = gA.nav.iloc[0], g0.nav.iloc[0], gA.nav_bh.iloc[0]
            restA = gA.iloc[1:]
            rest0 = g0.iloc[1:].set_index("date")
            for y, gy in restA.groupby(restA.date.dt.year):
                endd = gy.date.iloc[-1]
                ra = gy.nav.iloc[-1] / baseA - 1
                rb = gy.nav_bh.iloc[-1] / baseB - 1
                y0 = rest0[rest0.index.year == y]
                r0 = y0.nav.iloc[-1] / base0 - 1
                rows.append([str(y), f"{base_d.date()} → {endd.date()}", str(len(gy)), SP(r0),
                             SP(ra), SP(rb), PP((ra - rb) * 100), F(gy.w_equity.mean(), 3)])
                base_d, baseA, base0, baseB = endd, gy.nav.iloc[-1], y0.nav.iloc[-1], \
                    gy.nav_bh.iloc[-1]
            table(["year", "from → to", "sessions", f"R {C0:g} bps", f"R {CA:g} bps", "B&H",
                   f"R {CA:g} − B&H (pp)", "mean equity wt (drifted)"], rows)

    print()
    print("GATES: " + "  ".join(f"{k} {'PASS' if v else 'FAIL'}" for k, v in gates.items()))
    if not STATE["gates_ok"]:
        print("GATE FAILED — nothing below the gate block (4.0) may be read")
    return 0 if STATE["gates_ok"] else 3


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--root", default=str(HERE),
                    help="folder holding evidence/ and verify_*.json (default: this folder)")
    a = ap.parse_args()
    root = Path(a.root).resolve()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    try:
        check_files(root)
    except EvidenceError as e:
        print(f"EVIDENCE ERROR: {e}", file=sys.stderr)
        sys.exit(2)
    tee = Tee(root / "analysis.log")
    real = sys.stdout
    sys.stdout = tee
    try:
        code = main(root)
    except EvidenceError as e:
        print(f"\nEVIDENCE ERROR: {e}")
        code = 2
    finally:
        sys.stdout = real
        tee.close()
    sys.exit(code)
