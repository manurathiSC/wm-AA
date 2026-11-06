# -*- coding: utf-8 -*-
"""
Compare the final-strategy backtest under ST.py's MAUc1 signal (baseline:
evidence/final_strategy/) and under the user's weekly file (impact/user/).
Also checks that impact/stpy/ (harness, ST.py signal) reproduces the baseline.

Writes (impact/ only):
  repro_check.csv               every file main() writes: baseline vs impact/stpy, identical?
  review_signal_compare.csv     every review, both windows: ST.py vs user gold signal, decision, gold_w
  gold_weight_changes.csv       reviews where the sleeve's gold weight differs
  final_rule_stats_compare.csv  FINAL rule per book + 4-book average: CAGR, max DD (daily, Friday), diffs
  all_rules_stats_compare.csv   every strategy row, baseline vs user
  trade_changes.csv             FINAL-rule trades added / removed / changed, per book and window
"""
from __future__ import annotations

import filecmp
import json
import pathlib

import numpy as np
import pandas as pd

HERE = pathlib.Path(__file__).resolve().parent
BASE = HERE.parents[2]                     # evidence/final_strategy
STPY, USER = HERE / "stpy", HERE / "user"
FINAL = "FINAL: triple + 80/20 gold-timed sleeve (weekly re-check)"
PER = {"live": "live 2021-11 -> 2026-08", "2014_2021": "before the books 2014-07 -> 2021-10"}
BOOKS = ["SCMO_0042", "SCMO_0043", "SCMO_0044", "SCMO_0045"]


def frame_equal(a: pathlib.Path, b: pathlib.Path):
    if a.suffix == ".json":
        return json.loads(a.read_text()) == json.loads(b.read_text()), np.nan
    x, y = pd.read_csv(a), pd.read_csv(b)
    if x.shape != y.shape or list(x.columns) != list(y.columns):
        return False, np.nan
    num = x.select_dtypes("number").columns
    d = float(np.nanmax(np.abs(x[num].values - y[num].values))) if len(num) else 0.0
    ok = x.drop(columns=num).fillna("").astype(str).equals(y.drop(columns=num).fillna("").astype(str))
    ok = ok and bool(((x[num] == y[num]) | (x[num].isna() & y[num].isna())).all().all())
    return ok, d


def repro():
    rows = []
    for f in sorted(STPY.iterdir()):
        b = BASE / f.name
        if not b.exists():
            rows.append({"file": f.name, "baseline_exists": False}); continue
        same_bytes = filecmp.cmp(f, b, shallow=False)
        eq, d = frame_equal(f, b)
        rows.append({"file": f.name, "baseline_exists": True, "byte_identical": same_bytes,
                     "values_identical": eq, "max_abs_numeric_diff": d})
    r = pd.DataFrame(rows)
    r.to_csv(HERE / "repro_check.csv", index=False)
    return r


def noise_floor():
    """
    Run-to-run noise of the unmodified pipeline: the same ST.py-signal harness run under
    PYTHONHASHSEED=1 and =2 (string-set iteration order changes float summation order).
    position_log is compared after sorting by its keys (its row order within a trade
    follows set order). Written to repro_noise_floor.csv.
    """
    runs = {"baseline": BASE, "stpy": STPY, "seed1": HERE / "stpy_seed1", "seed2": HERE / "stpy_seed2"}
    runs = {k: v for k, v in runs.items() if (v / "summary_stats.csv").exists()}
    pairs = [("baseline", "stpy"), ("baseline", "seed1"), ("baseline", "seed2"), ("seed1", "seed2")]
    rows = []
    for a, b in pairs:
        if a not in runs or b not in runs:
            continue
        for f in sorted(p.name for p in STPY.iterdir()):
            if f.endswith(".json"):
                continue
            x, y = pd.read_csv(runs[a] / f), pd.read_csv(runs[b] / f)
            if f == "position_log.csv":
                k = ["period", "aa", "strategy", "entry", "review", "key"]
                x, y = x.sort_values(k).reset_index(drop=True), y.sort_values(k).reset_index(drop=True)
            num = x.select_dtypes("number").columns
            txt_same = x.drop(columns=num).fillna("").astype(str).equals(y.drop(columns=num).fillna("").astype(str))
            rows.append({"a": a, "b": b, "file": f, "shape_same": x.shape == y.shape, "text_cols_same": txt_same,
                         "max_abs_numeric_diff": float(np.nanmax(np.abs(x[num].values - y[num].values))) if len(num) else 0.0,
                         "byte_identical": filecmp.cmp(runs[a] / f, runs[b] / f, shallow=False)})
    r = pd.DataFrame(rows)
    r.to_csv(HERE / "repro_noise_floor.csv", index=False)
    return r


def review_compare():
    out = []
    for lab, per in PER.items():
        b = pd.read_csv(BASE / f"weekly_signals_{lab}.csv", parse_dates=["review"])
        u = pd.read_csv(USER / f"weekly_signals_{lab}.csv", parse_dates=["review"])
        assert (b.review.values == u.review.values).all() and (b.decision.values == u.decision.values).all()
        m = pd.DataFrame({"window": lab, "review": b.review, "weekday": b.review.dt.day_name(),
                          "entry_session": b.entry_session, "decision": b.decision,
                          "gold_signal_stpy": b.gold_signal, "gold_signal_user": u.gold_signal,
                          "gold_w_stpy": b.gold_w, "gold_w_user": u.gold_w,
                          "cash_w_stpy": b.cash_w, "cash_w_user": u.cash_w,
                          "variant_gold_w_stpy": b.variant_gold_w, "variant_gold_w_user": u.variant_gold_w})
        out.append(m)
    m = pd.concat(out, ignore_index=True)
    sig = lambda s: s.map({1.0: "BUY", 0.0: "SELL"}).fillna("none")
    m["signal_differs"] = sig(m.gold_signal_stpy) != sig(m.gold_signal_user)
    m["gold_w_differs"] = (m.gold_w_stpy - m.gold_w_user).abs() > 1e-12
    m["variant_gold_w_differs"] = (m.variant_gold_w_stpy - m.variant_gold_w_user).abs() > 1e-12
    # the user row each review read: must be the same ISO week as the review (no stale reads)
    t = pd.read_csv(USER / "gold_supertrend_weekly.csv", parse_dates=["review", "user_week_ending"])
    t = t.dropna(subset=["signal"]).set_index("review").sort_index()
    rd = []
    for r in m.review:
        idx = t.index[t.index <= r]
        rd.append(t.loc[idx[-1], "user_week_ending"] if len(idx) else pd.NaT)
    m["user_week_read"] = pd.DatetimeIndex(rd)
    ic = lambda s: list(zip(s.dt.isocalendar().year, s.dt.isocalendar().week))
    m["same_iso_week"] = [a == b for a, b in zip(ic(m.review), ic(m.user_week_read.fillna(pd.Timestamp("1900-01-01"))))]
    m.to_csv(HERE / "review_signal_compare.csv", index=False)
    ch = m[m.gold_w_differs | m.variant_gold_w_differs]
    ch.to_csv(HERE / "gold_weight_changes.csv", index=False)
    return m, ch


def stats_compare():
    b = pd.read_csv(BASE / "summary_stats.csv")
    u = pd.read_csv(USER / "summary_stats.csv")
    key = ["period", "aa", "strategy"]
    # strategy names that embed the same-average gold share differ between runs: align them by position
    norm = lambda s: s.str.replace(r"fixed \d+% gold sleeve", "fixed X% gold sleeve", regex=True)
    b["strategy_key"], u["strategy_key"] = norm(b.strategy), norm(u.strategy)
    k2 = ["period", "aa", "strategy_key"]
    cols = ["cagr", "max_dd_daily", "max_dd_friday", "calmar", "sharpe_vs_cash", "total_return",
            "switches_equity_sleeve", "sleeve_resplits", "trades", "cost_paid_share_of_nav"]
    j = b[k2 + ["strategy"] + cols].merge(u[k2 + ["strategy"] + cols], on=k2, suffixes=("_stpy", "_user"))
    for c in cols:
        j[f"{c}_diff"] = j[f"{c}_user"] - j[f"{c}_stpy"]
    j.to_csv(HERE / "all_rules_stats_compare.csv", index=False)
    f = j[j.strategy_key == FINAL].copy()
    rows = []
    for lab, per in PER.items():
        x = f[f.period == per].set_index("aa").loc[BOOKS]
        for aa, r in x.iterrows():
            rows.append({"window": lab, "book": aa, **{c: r[c] for c in x.columns if c.split("_")[0] in
                         ("cagr", "max", "trades", "sleeve", "switches")}})
        avg = {"window": lab, "book": "4-book average"}
        for c in x.columns:
            if c.split("_")[0] in ("cagr", "max", "trades", "sleeve", "switches"):
                avg[c] = float(x[c].mean())
        rows.append(avg)
    fs = pd.DataFrame(rows)
    fs.to_csv(HERE / "final_rule_stats_compare.csv", index=False)
    return fs, j


def trades_compare():
    b = pd.read_csv(BASE / "trade_log.csv", parse_dates=["entry", "review"])
    u = pd.read_csv(USER / "trade_log.csv", parse_dates=["entry", "review"])
    b, u = b[b.strategy == FINAL], u[u.strategy == FINAL]
    k = ["period", "aa", "entry", "review"]
    j = b.merge(u, on=k, how="outer", suffixes=("_stpy", "_user"), indicator=True)
    j["status"] = j["_merge"].astype(str).map({"left_only": "removed (ST.py only)", "right_only": "added (user only)",
                                               "both": "both"}).astype(object)
    both = j["_merge"] == "both"
    diff = both & ((j.gold_share_of_sleeve_stpy - j.gold_share_of_sleeve_user).abs() > 1e-12)
    j.loc[diff, "status"] = "changed gold share"
    tchg = both & ~diff & ((j.turnover_frac_stpy - j.turnover_frac_user).abs() > 1e-9)
    j.loc[tchg, "status"] = "same target, different size (NAV drift)"
    j = j.drop(columns="_merge").sort_values(k)
    keep = ["period", "aa", "entry", "review", "status", "kind_stpy", "kind_user", "gold_share_of_sleeve_stpy",
            "gold_share_of_sleeve_user", "sleeve_weight_stpy", "sleeve_weight_user", "turnover_frac_stpy",
            "turnover_frac_user", "cost_stpy", "cost_user", "nav_stpy", "nav_user"]
    j[keep].to_csv(HERE / "trade_changes.csv", index=False)
    return j[keep]


if __name__ == "__main__":
    pd.set_option("display.width", 250); pd.set_option("display.max_columns", 40); pd.set_option("display.max_rows", 200)
    r = repro()
    print("REPRO:", int(r.values_identical.sum()), "of", len(r), "files value-identical;",
          int(r.byte_identical.sum()), "byte-identical")
    print(r.to_string(index=False))
    nf = noise_floor()
    print("\nNOISE FLOOR (max |diff| per pair over all files):")
    print(nf.groupby(["a", "b"]).agg(files=("file", "size"), text_same=("text_cols_same", "all"),
                                      shapes_same=("shape_same", "all"), max_abs=("max_abs_numeric_diff", "max"),
                                      byte_identical_files=("byte_identical", "sum")).to_string())
    print(nf[nf.file == "summary_stats.csv"].to_string(index=False))
    m, ch = review_compare()
    print("\nreviews:", len(m), "| signal differs at", int(m.signal_differs.sum()), "| gold_w differs at",
          int(m.gold_w_differs.sum()), "| variant gold_w differs at", int(m.variant_gold_w_differs.sum()))
    post = m[m.review >= "2015-03-06"]
    print("reviews on/after 2015-03-06 whose user read is the same ISO week:", int(post.same_iso_week.sum()), "of", len(post))
    print(m[m.signal_differs].to_string(index=False))
    fs, j = stats_compare()
    print("\n", fs.to_string(index=False))
    t = trades_compare()
    print("\n", t.status.value_counts().to_string())
    print(t[t.status != "both"].to_string(index=False))
