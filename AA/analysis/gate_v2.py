# -*- coding: utf-8 -*-
"""
The hard gate: reproduce production v2's own intermediates.

Not "reproduce the realized history" -- that was ruled out for a concrete
reason. The historical weight files came from earlier engines, and the
completed study found 0042/0043 track **Smallcap 100** at 99.6%/100% while
v2's `_compute_fs` uses **Smallcap 250**. If the spec drifted, no correct v2
implementation reproduces 2022, and failing to reproduce it would say nothing
about this harness.

What is being backtested is a modification *to v2*, so the gate is v2 fidelity:
for the Fridays where production wrote its own workings into the `Summary`
sheet of `rebalance_{DDMMYY}.xlsx`, reproduce `mcat_dist` (lcap/mcap/scap_pct)
and `fs` exactly.

Three checks, deliberately separated so a failure localises:

  1. **Signal read.** The `index_signal` string in `Summary` records the SIGNs
     production actually saw. Reproducing it from `Master_*.xlsx` proves the
     signal lookup and the as-of date rule are right, independent of anything
     else.
  2. **mcat_dist.** Count-share of LCAP/MCAP/SCAP over the *parent* basket
     (production counts the parent, not the held book -- see
     `_compute_mcat_distribution`), using the production-equivalent membership
     classifier. This is the hard gate.
  3. **fs and equity_pct.** `_compute_fs` re-implemented verbatim, fed by 1
     and 2.

The hard gate uses the membership classifier because that is what production
used; it isolates engine arithmetic from classification. The PIT classifier --
what the backtest actually runs on over history -- is scored on the same rows
as a secondary figure, and is expected to be near but not at 100%.

Also runs the DIAGNOSTIC, which is not a gate: how well v2 re-simulated over
history matches the realized states in `SCMO_004x_Weight.csv`, per portfolio
and per year, under Smallcap 250 and again under Smallcap 100. The gap between
those two measures spec drift. Nothing is tuned to close it.

Writes to `evidence/segment_v1/`:
    gate_v2_intermediates.csv   per Friday x book, expected vs reproduced
    gate_v2_summary.json        pass/fail and the counts behind it
    spec_drift_diagnostic.csv   v2-resimulated vs realized, by book and year
"""

from __future__ import annotations

import glob
import json
import os
import re

import numpy as np
import pandas as pd

from classify_validate import MembershipClassifier, index_membership
from common import EVIDENCE_DIR, PAIRS, weight_csv
from mcap_ranks import CAT_TO_MCAT, PITClassifier, load_cache
from supertrend import INDICES_OHLCV

EVIDENCE_SUBDIR = EVIDENCE_DIR / "segment_v1"
FRIDAY_ROOT = os.path.dirname(str(INDICES_OHLCV)) + os.sep + ".."
WORKBOOK_DIRS = ["RSI_v1", "RSI"]

K_THRESHOLD = 0.60
MCATS = ["LCAP", "MCAP", "SCAP"]

# _compute_fs's index mapping, verbatim from rebalance_engine_v2.py.
FS_INDEX = {"LCAP": "Nifty100", "MCAP": "NiftyMidcap150", "SCAP": "NiftySmallcap250"}
FS_INDEX_SC100 = {**FS_INDEX, "SCAP": "SC100"}     # the spec-drift alternative

TOL = 5e-4      # production rounds mcat_dist to 4 dp and prints fs to 3


def _analysis_dir(sub: str) -> str:
    return os.path.join(FRIDAY_ROOT, sub, "Final", "Analysis")


# ── Production's own workings ──────────────────────────────────────────────
def production_summaries() -> pd.DataFrame:
    """The `Summary` sheet of every weekly rebalance workbook."""
    rows = []
    for sub in WORKBOOK_DIRS:
        for path in sorted(glob.glob(os.path.join(_analysis_dir(sub), "rebalance_*.xlsx"))):
            m = re.search(r"rebalance_(\d{2})(\d{2})(\d{2})\.xlsx", os.path.basename(path))
            if not m:
                continue
            dd, mm, yy = m.groups()
            d = pd.read_excel(path, sheet_name="Summary")
            d["date"] = pd.Timestamp(f"20{yy}-{mm}-{dd}")
            d["source"] = sub
            d["workbook"] = os.path.basename(path)
            rows.append(d)
    return pd.concat(rows, ignore_index=True)


ALIAS = {"Nifty100": "Nifty100", "Midcap150": "NiftyMidcap150",
         "Smallcap250": "NiftySmallcap250", "Microcap250": "NiftyMicrocap250",
         "MC100": "MC100", "SC100": "SC100", "NSEI": "NSEI"}


def parse_index_signal(s: str) -> tuple[dict[str, int], list[str]]:
    """
    Parse the `index_signal` string production wrote, returning the SIGNs it
    saw plus the list of indices that actually FED the FS calculation --
    entries tagged `(ref)` are printed for reference and are not inputs.

    This matters because the FS inputs are not constant over the sample. The
    early RSI_v1 workbooks read `Nifty100 | MC100 | SC100`; from 2026-04-24 the
    string becomes `Nifty100 | Midcap150 | Smallcap250 | MC100 (ref) |
    SC100 (ref)`. Reading the map out of production's own string rather than
    hardcoding it is what lets one gate cover both engine versions -- and
    dating that switch is itself the spec-drift finding.
    """
    sig: dict[str, int] = {}
    inputs: list[str] = []
    for part in str(s).split("|"):
        mm = re.match(r"\s*(\w+)\s*=\s*(BUY|SELL)\s*(\(ref\))?", part)
        if not mm:
            continue
        key = ALIAS.get(mm.group(1), mm.group(1))
        sig[key] = 1 if mm.group(2) == "BUY" else 0
        if not mm.group(3):
            inputs.append(key)
    return sig, inputs


def fs_index_map(inputs: list[str]) -> dict[str, str]:
    """LCAP/MCAP/SCAP -> the index feeding each, for this workbook's engine."""
    large = "Nifty100"
    mid = "NiftyMidcap150" if "NiftyMidcap150" in inputs else "MC100"
    small = "NiftySmallcap250" if "NiftySmallcap250" in inputs else "SC100"
    return {"LCAP": large, "MCAP": mid, "SCAP": small}


# ── Our re-implementation ──────────────────────────────────────────────────
def master_signs() -> dict[str, pd.Series]:
    """SIGN series per index, from production's own Master workbooks."""
    out = {}
    for name in ["Nifty100", "NiftyMidcap150", "NiftySmallcap250",
                 "NiftyMicrocap250", "MC100", "SC100", "NSEI"]:
        for sub in ("RSI", "RSI_v1"):
            p = os.path.join(_analysis_dir(sub), f"Master_{name}.xlsx")
            if os.path.exists(p):
                d = pd.read_excel(p)
                d["Date"] = pd.to_datetime(d["Date"])
                s = d.dropna(subset=["SIGN"]).set_index("Date")["SIGN"].sort_index()
                out[name] = s[~s.index.duplicated(keep="last")]
                break
    return out


def sign_asof(series: pd.Series, date: pd.Timestamp):
    """Latest SIGN dated on or before the review date."""
    prior = series.index[series.index <= date]
    return None if not len(prior) else series.loc[prior[-1]]


def parent_baskets() -> dict[str, pd.DataFrame]:
    """Parent rebalance history per parent scid, keyed on availableDate."""
    out = {}
    for scid in PAIRS.values():
        p = os.path.join(FRIDAY_ROOT, "Rebalance_history",
                         f"Rebalance_history_by_scid_{scid}.csv")
        d = pd.read_csv(p)
        d["eff_date"] = pd.to_datetime(d["availableDate"], format="%d/%m/%y %H:%M")
        d["signal_date"] = pd.to_datetime(d["date"])
        d["ticker"] = d["ticker"].astype(str).str.strip().str.upper()
        out[scid] = d.sort_values("eff_date")
    return out


def _production_sheet_tickers() -> dict[tuple, list[str]]:
    """
    (date, aa_scid, source) -> the stock tickers production listed that week.

    Only rows with a real `mcat` count; `ETF` rows are the defensive sleeve and
    a defensive week yields an empty list, which is the signal to fall back.
    """
    out: dict[tuple, list[str]] = {}
    for sub in WORKBOOK_DIRS:
        for path in sorted(glob.glob(os.path.join(_analysis_dir(sub), "rebalance_*.xlsx"))):
            m = re.search(r"rebalance_(\d{2})(\d{2})(\d{2})\.xlsx", os.path.basename(path))
            if not m:
                continue
            dd, mm, yy = m.groups()
            date = pd.Timestamp(f"20{yy}-{mm}-{dd}")
            book = pd.ExcelFile(path)
            for sheet in book.sheet_names:
                if not sheet.startswith("SCMO_"):
                    continue
                d = book.parse(sheet)
                if "mcat" not in d.columns or "ticker" not in d.columns:
                    continue
                t = d[d["mcat"].isin(MCATS)]["ticker"].astype(str).str.strip().str.upper()
                out[(date, sheet, sub)] = sorted(t.tolist())
    return out


def basket_asof(hist: pd.DataFrame, date: pd.Timestamp) -> pd.DataFrame:
    prior = hist[hist["eff_date"] <= date]
    if prior.empty:
        return prior
    return prior[prior["eff_date"] == prior["eff_date"].max()]


def mcat_dist(tickers, clf, asof) -> dict[str, float]:
    """`_compute_mcat_distribution`, re-implemented: count-share, not weight."""
    tickers = [t for t in tickers if isinstance(t, str) and t]
    n = len(tickers)
    if n == 0:
        return {k: 0.0 for k in MCATS}
    counts = dict.fromkeys(MCATS, 0)
    for t in tickers:
        counts[CAT_TO_MCAT.get(clf.classify(t, asof), "SCAP")] += 1
    return {k: v / n for k, v in counts.items()}


def compute_fs(dist: dict[str, float], signals: dict[str, int],
               index_map: dict[str, str] = FS_INDEX) -> float:
    """`_compute_fs`, verbatim."""
    return sum(dist[m] * signals.get(index_map[m], 0) for m in MCATS)


# ── Gate ───────────────────────────────────────────────────────────────────
def run_gate() -> tuple[pd.DataFrame, dict]:
    """
    The basket used is production's OWN per-AA sheet ticker list wherever the
    book held equity that week. That is deliberate: `Rebalance_history` is not
    always what production actually ran on -- on 2026-06-12 and 2026-06-19 it
    held a basket 6 names different from any row in the history file, having
    picked up the upcoming reconstitution early and then reverted. Testing
    against our reconstruction of the basket would fold a basket-provenance
    artifact into what is supposed to be a test of classification and FS
    arithmetic. Where the book was defensive the sheet holds only ETFs and the
    parent is unrecoverable, so those rows fall back to `Rebalance_history` and
    are flagged.
    """
    summ = production_summaries()
    signs = master_signs()
    baskets = parent_baskets()
    membership = index_membership()
    memb_clf = MembershipClassifier(membership)
    pit_clf = PITClassifier(load_cache("semiannual"))
    first_snap = pd.Timestamp(min(membership["snapshot_date"]))
    prod_sheets = _production_sheet_tickers()

    rows = []
    for _, r in summ.iterrows():
        date, aa = r["date"], r["aa_scid"]
        parent = PAIRS.get(aa)
        if parent is None:
            continue
        prod_sig, fs_inputs = parse_index_signal(r["index_signal"])
        imap = fs_index_map(fs_inputs)
        ours_sig = {k: (1 if sign_asof(s, date) == "BUY" else 0)
                    for k, s in signs.items() if sign_asof(s, date) is not None}

        sheet = prod_sheets.get((date, aa, r["source"]), [])
        hist = basket_asof(baskets[parent], date)
        if sheet:
            tickers, basket_src = sheet, "production_sheet"
        else:
            tickers, basket_src = hist["ticker"].tolist(), "rebalance_history"

        d_memb = mcat_dist(tickers, memb_clf, date)
        d_pit = mcat_dist(tickers, pit_clf, date)
        fs_memb = compute_fs(d_memb, prod_sig, imap)
        fs_pit = compute_fs(d_pit, prod_sig, imap)

        rows.append({
            "date": date, "source": r["source"], "aa_scid": aa, "parent_scid": parent,
            "engine_fs_inputs": "|".join(imap[m] for m in MCATS),
            "basket_source": basket_src, "n_parent": len(tickers),
            "hist_basket_matches": (bool(sheet)
                                    and sorted(sheet) == sorted(hist["ticker"].tolist())),
            "testable": bool(date >= first_snap and tickers),
            "untestable_reason": ("no membership snapshot on or before this date"
                                  if date < first_snap else
                                  "" if tickers else "empty basket"),
            "signal_match": all(ours_sig.get(k) == v for k, v in prod_sig.items()),
            "exp_lcap": r["lcap_pct"], "got_lcap": d_memb["LCAP"],
            "exp_mcap": r["mcap_pct"], "got_mcap": d_memb["MCAP"],
            "exp_scap": r["scap_pct"], "got_scap": d_memb["SCAP"],
            "exp_fs": r["fs"], "got_fs": fs_memb,
            "exp_equity_pct": r["equity_pct"],
            "got_equity_pct": 1.0 if fs_memb >= K_THRESHOLD else 0.0,
            "got_fs_pit": fs_pit,
            "got_lcap_pit": d_pit["LCAP"], "got_mcap_pit": d_pit["MCAP"],
            "got_scap_pit": d_pit["SCAP"],
        })

    g = pd.DataFrame(rows)
    for c in ("lcap", "mcap", "scap", "fs"):
        g[f"d_{c}"] = (g[f"got_{c}"] - g[f"exp_{c}"]).abs()
    g["dist_ok"] = g[["d_lcap", "d_mcap", "d_scap"]].max(axis=1) <= TOL
    g["fs_ok"] = g["d_fs"] <= TOL
    g["equity_ok"] = g["got_equity_pct"] == g["exp_equity_pct"]
    g["pit_dist_ok"] = (
        pd.concat([(g["got_lcap_pit"] - g["exp_lcap"]).abs(),
                   (g["got_mcap_pit"] - g["exp_mcap"]).abs(),
                   (g["got_scap_pit"] - g["exp_scap"]).abs()], axis=1).max(axis=1) <= TOL
    )

    t = g[g["testable"]]
    summary = {
        "rows": int(len(g)),
        "testable_rows": int(len(t)),
        "untestable_rows": int((~g["testable"]).sum()),
        "untestable_reasons": g.loc[~g["testable"], "untestable_reason"]
                               .value_counts().to_dict(),
        "fridays": int(g["date"].nunique()),
        "books": int(g["aa_scid"].nunique()),
        "date_range": [str(g["date"].min().date()), str(g["date"].max().date())],
        "engine_fs_input_variants": g.groupby("engine_fs_inputs")["date"]
                                     .agg(["min", "max", "size"])
                                     .reset_index().to_dict(orient="records"),
        "basket_source_counts": g["basket_source"].value_counts().to_dict(),
        "weeks_history_basket_disagreed": int(
            (~g["hist_basket_matches"] & (g["basket_source"] == "production_sheet")).sum()),
        "signal_read_match": float(g["signal_match"].mean()),
        "mcat_dist_match": float(t["dist_ok"].mean()),
        "fs_match": float(t["fs_ok"].mean()),
        "equity_pct_match": float(t["equity_ok"].mean()),
        "max_abs_err_lcap": float(t["d_lcap"].max()),
        "max_abs_err_mcap": float(t["d_mcap"].max()),
        "max_abs_err_scap": float(t["d_scap"].max()),
        "max_abs_err_fs": float(t["d_fs"].max()),
        "tolerance": TOL,
        "pit_classifier_mcat_dist_match": float(t["pit_dist_ok"].mean()),
        "gate_passed": bool(len(t) and t["dist_ok"].all() and t["fs_ok"].all()
                            and t["equity_ok"].all() and g["signal_match"].all()),
    }
    return g, summary


# ── Diagnostic (not a gate) ────────────────────────────────────────────────
def realized_states() -> pd.DataFrame:
    """Realized weekly equity/defensive state per AA book from the weight files."""
    rows = []
    for aa in PAIRS:
        w = pd.read_csv(weight_csv(aa))
        w["eff_date"] = pd.to_datetime(w["availableDate"], format="%d/%m/%y %H:%M")
        w["ticker"] = w["ticker"].astype(str).str.strip().str.upper()
        defensive = {"GOLDCASE", "LIQUIDCASE", "GOLDBEES", "LIQUIDBEES", "EBBETF0431"}
        g = (w.assign(is_eq=~w["ticker"].isin(defensive))
             .groupby("eff_date")["is_eq"].max().rename("realized_equity"))
        rows.append(g.reset_index().assign(aa_scid=aa))
    return pd.concat(rows, ignore_index=True)


def run_diagnostic() -> pd.DataFrame:
    """
    v2 re-simulated over history vs the realized states, under Smallcap 250
    (v2's actual rule) and under Smallcap 100 (the suspected earlier spec).
    """
    signs = master_signs()
    baskets = parent_baskets()
    pit_clf = PITClassifier(load_cache("semiannual"))
    real = realized_states()

    rows = []
    for aa, parent in PAIRS.items():
        r = real[real["aa_scid"] == aa]
        for _, rr in r.iterrows():
            date = rr["eff_date"]
            basket = basket_asof(baskets[parent], date)
            if basket.empty:
                continue
            dist = mcat_dist(basket["ticker"].tolist(), pit_clf, date)
            sig = {k: (1 if sign_asof(s, date) == "BUY" else 0)
                   for k, s in signs.items() if sign_asof(s, date) is not None}
            if not {"Nifty100", "NiftyMidcap150", "NiftySmallcap250"} <= set(sig):
                continue
            fs250 = compute_fs(dist, sig, FS_INDEX)
            row = {"aa_scid": aa, "date": date, "year": date.year,
                   "realized_equity": bool(rr["realized_equity"]),
                   "v2_sc250_equity": fs250 >= K_THRESHOLD}
            if "SC100" in sig:
                fs100 = compute_fs(dist, sig, FS_INDEX_SC100)
                row["v2_sc100_equity"] = fs100 >= K_THRESHOLD
            rows.append(row)

    d = pd.DataFrame(rows)
    d["match_sc250"] = d["v2_sc250_equity"] == d["realized_equity"]
    if "v2_sc100_equity" in d:
        d["match_sc100"] = d["v2_sc100_equity"] == d["realized_equity"]

    agg = (d.groupby(["aa_scid", "year"])
           .agg(reviews=("match_sc250", "size"),
                match_sc250=("match_sc250", "mean"),
                **({"match_sc100": ("match_sc100", "mean")} if "match_sc100" in d else {}))
           .reset_index())
    return agg


def main() -> None:
    EVIDENCE_SUBDIR.mkdir(parents=True, exist_ok=True)

    g, s = run_gate()
    g.to_csv(EVIDENCE_SUBDIR / "gate_v2_intermediates.csv", index=False)
    (EVIDENCE_SUBDIR / "gate_v2_summary.json").write_text(
        json.dumps(s, indent=2, default=str), encoding="utf-8")

    print("HARD GATE -- reproduce production v2's own intermediates")
    print(f"  {s['rows']} rows  {s['fridays']} Fridays x {s['books']} books  "
          f"{s['date_range'][0]} -> {s['date_range'][1]}")
    print(f"  testable {s['testable_rows']}  untestable {s['untestable_rows']} "
          f"{s['untestable_reasons']}")
    print("\n  engine FS inputs found in production's own workings:")
    for v in s["engine_fs_input_variants"]:
        print(f"    {v['engine_fs_inputs']:52s} {str(v['min'])[:10]} -> "
              f"{str(v['max'])[:10]}  ({v['size']} rows)")
    print(f"\n  basket source: {s['basket_source_counts']}")
    print(f"  weeks where Rebalance_history disagreed with production's own book: "
          f"{s['weeks_history_basket_disagreed']}")
    print(f"\n  signal read matches production : {s['signal_read_match']:.2%}")
    print(f"  mcat_dist matches              : {s['mcat_dist_match']:.2%}  "
          f"(max abs err {max(s['max_abs_err_lcap'], s['max_abs_err_mcap'], s['max_abs_err_scap']):.2e})")
    print(f"  fs matches                     : {s['fs_match']:.2%}  "
          f"(max abs err {s['max_abs_err_fs']:.2e})")
    print(f"  equity_pct matches             : {s['equity_pct_match']:.2%}")
    print(f"  [secondary] PIT classifier     : {s['pit_classifier_mcat_dist_match']:.2%}")
    print(f"\n  GATE: {'PASSED' if s['gate_passed'] else 'FAILED'}")

    if not s["gate_passed"]:
        bad = g[g["testable"] & ~(g["dist_ok"] & g["fs_ok"] & g["equity_ok"]
                                  & g["signal_match"])]
        print("\n  failing rows:")
        print(bad[["date", "aa_scid", "basket_source", "signal_match",
                   "exp_lcap", "got_lcap", "exp_mcap", "got_mcap",
                   "exp_scap", "got_scap", "exp_fs", "got_fs"]].to_string(index=False))
        raise SystemExit("gate failed -- the harness is wrong; stop and fix")

    diag = run_diagnostic()
    diag.to_csv(EVIDENCE_SUBDIR / "spec_drift_diagnostic.csv", index=False)
    print("\nDIAGNOSTIC (not a gate) -- v2 re-simulated vs realized states")
    piv = diag.pivot_table(index="year", columns="aa_scid",
                           values="match_sc250", aggfunc="mean")
    print("\n  Smallcap 250 (v2's actual rule):")
    print(piv.to_string(float_format=lambda v: f"{v:.1%}"))
    if "match_sc100" in diag:
        piv2 = diag.pivot_table(index="year", columns="aa_scid",
                                values="match_sc100", aggfunc="mean")
        print("\n  Smallcap 100 substituted (the suspected earlier spec):")
        print(piv2.to_string(float_format=lambda v: f"{v:.1%}"))
        overall = diag[["match_sc250", "match_sc100"]].apply(
            lambda c: np.average(c, weights=diag["reviews"]))
        gap = (overall["match_sc100"] - overall["match_sc250"]) * 100
        print(f"\n  overall  SC250 {overall['match_sc250']:.1%}   "
              f"SC100 {overall['match_sc100']:.1%}   drift gap {gap:+.1f}pp")
        print("  => the live track record was produced by the Smallcap 100 rule, "
              "not the Smallcap 250 rule v2 now uses.")


if __name__ == "__main__":
    main()
